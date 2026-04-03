"""
Skill 执行引擎

统一执行 Skill：加载 Prompt → 组装 messages → 调 LLM → 解析结果。
替代 core_server.py 中 14 处重复的 ZhipuAI().chat.completions.create() 调用。

三种执行模式：
1. 普通调用：Prompt → LLM → content → JSON 解析
2. Function Call：Prompt + tools → LLM → tool_calls → 提取 arguments
3. 流式调用：Prompt → LLM stream → SSE generator
"""

import os
import json
import logging
import re
from typing import Dict, Any, Optional, AsyncGenerator

from zhipuai import ZhipuAI
from app.services.skill_loader import skill_loader, Skill

logger = logging.getLogger(__name__)


def _clean_json(text: str) -> str:
    """清洗 LLM 返回的 JSON 文本，去除 markdown 包裹"""
    text = text.strip()
    # 去除 ```json ... ``` 包裹（支持多行内容）
    match = re.search(r'```(?:json)?\s*\n?(.*?)\n?\s*```', text, re.DOTALL)
    if match:
        text = match.group(1).strip()
    # 如果没有 ``` 包裹，尝试找第一个 { 或 [ 开头的 JSON
    elif not text.startswith('{') and not text.startswith('['):
        for i, ch in enumerate(text):
            if ch in '{[':
                text = text[i:]
                break
    return text.strip()


class SkillExecutor:
    """
    Skill 统一执行引擎

    用法：
        result = await executor.run("intent_analyze", user_message="帮我请假3天")
        stream = executor.run_stream("chat", messages=[...])
    """

    def __init__(self):
        self._api_key = os.getenv("ZHIPU_API_KEY")

    def _get_client(self) -> ZhipuAI:
        return ZhipuAI(api_key=self._api_key)

    async def run(
        self,
        skill_name: str,
        user_message: str = "",
        *,
        messages: Optional[list] = None,
        context: Optional[Dict[str, Any]] = None,
        model_override: Optional[str] = None,
        temperature_override: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        执行 Skill，返回结构化结果。

        自动判断模式：
        - Skill 有 tools → Function Call 模式
        - Skill 无 tools → 普通模式（返回 content 并尝试 JSON 解析）

        Args:
            skill_name: Skill 名称
            user_message: 用户输入文本
            messages: 完整 messages 列表（如提供则忽略 user_message）
            context: 额外上下文，会追加到 system_prompt 末尾
            model_override: 覆盖 Skill 定义的 model
            temperature_override: 覆盖 Skill 定义的 temperature

        Returns:
            {
                "success": True,
                "data": { ... },           # 解析后的结构化数据
                "raw": "...",              # LLM 原始返回文本
                "model": "glm-5",
                "usage": { "total_tokens": ... },
                "mode": "function_call" | "json_parse"
            }
        """
        skill = skill_loader.load(skill_name)
        if not skill:
            return {"success": False, "error": f"Skill '{skill_name}' not found"}

        # 组装 system_prompt
        system_prompt = skill.content
        if context:
            context_text = "\n".join(f"{k}: {v}" for k, v in context.items() if v)
            system_prompt += f"\n\n## 当前上下文\n{context_text}"

        # 组装 messages
        if messages is None:
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ]
        else:
            # 确保 system_prompt 在最前面
            if not messages or messages[0].get("role") != "system":
                messages = [{"role": "system", "content": system_prompt}] + messages
            else:
                messages = [{"role": "system", "content": system_prompt}] + messages[1:]

        model = model_override or skill.model
        temperature = temperature_override if temperature_override is not None else skill.temperature

        call_kwargs = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }
        if skill.max_tokens:
            call_kwargs["max_tokens"] = skill.max_tokens

        client = self._get_client()

        # Function Call 模式
        if skill.has_tools:
            return await self._run_function_call(client, call_kwargs, skill)

        # 普通模式
        return await self._run_json_parse(client, call_kwargs, skill)

    async def _run_function_call(
        self, client: ZhipuAI, call_kwargs: dict, skill: Skill
    ) -> Dict[str, Any]:
        """Function Call 模式：LLM 返回 tool_calls"""
        call_kwargs["tools"] = skill.tools
        call_kwargs["tool_choice"] = "auto"

        try:
            response = client.chat.completions.create(**call_kwargs)
            message = response.choices[0].message
            usage = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            }

            if message.tool_calls:
                data = json.loads(message.tool_calls[0].function.arguments)
                return {
                    "success": True,
                    "data": data,
                    "raw": message.tool_calls[0].function.arguments,
                    "model": call_kwargs["model"],
                    "usage": usage,
                    "mode": "function_call",
                }

            # LLM 未触发 function call，尝试从 content 解析
            logger.warning(f"Skill '{skill.name}' function call 未触发，尝试从 content 解析")
            return self._parse_content_as_json(message.content or "", call_kwargs["model"], usage)

        except Exception as e:
            logger.error(f"Skill '{skill.name}' function call 执行失败: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    async def _run_json_parse(
        self, client: ZhipuAI, call_kwargs: dict, skill: Skill
    ) -> Dict[str, Any]:
        """普通模式：LLM 返回 content，尝试 JSON 解析"""
        # 注：GLM-5 不需要 thinking 参数控制

        try:
            response = client.chat.completions.create(**call_kwargs)
            content = response.choices[0].message.content or ""
            usage = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            }
            return self._parse_content_as_json(content, call_kwargs["model"], usage)

        except Exception as e:
            logger.error(f"Skill '{skill.name}' 执行失败: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    def _parse_content_as_json(self, content: str, model: str, usage: dict) -> Dict[str, Any]:
        """尝试将 content 解析为 JSON，失败则作为纯文本返回"""
        cleaned = _clean_json(content)
        try:
            data = json.loads(cleaned)
            return {
                "success": True,
                "data": data,
                "raw": content,
                "model": model,
                "usage": usage,
                "mode": "json_parse",
            }
        except json.JSONDecodeError:
            # 不是 JSON，作为纯文本返回（chat 类场景）
            return {
                "success": True,
                "data": {"content": content},
                "raw": content,
                "model": model,
                "usage": usage,
                "mode": "text",
            }

    async def run_stream(
        self,
        skill_name: str,
        *,
        messages: Optional[list] = None,
        user_message: str = "",
        model_override: Optional[str] = None,
    ) -> AsyncGenerator[str, None]:
        """
        流式执行 Skill，返回 SSE 数据块的异步生成器。

        Yields:
            "data: {content}\n\n" 格式的 SSE 事件
        """
        skill = skill_loader.load(skill_name)
        if not skill:
            yield f"data: {json.dumps({'error': f'Skill {skill_name} not found'})}\n\n"
            return

        if messages is None:
            messages = [
                {"role": "system", "content": skill.content},
                {"role": "user", "content": user_message},
            ]
        elif not messages or messages[0].get("role") != "system":
            messages = [{"role": "system", "content": skill.content}] + messages

        model = model_override or skill.model
        client = self._get_client()

        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                stream=True,
                temperature=skill.temperature,
            )

            for chunk in response:
                if chunk.choices and chunk.choices[0].delta.content:
                    content = chunk.choices[0].delta.content
                    yield f"data: {content}\n\n"

            yield "data: [DONE]\n\n"

        except Exception as e:
            logger.error(f"Skill '{skill.name}' 流式执行失败: {e}")
            yield f"data: {json.dumps({'error': str(e)})}\n\n"


# 全局实例
skill_executor = SkillExecutor()
