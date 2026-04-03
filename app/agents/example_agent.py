"""
示例Agent - 演示如何基于BaseAgent开发自定义Agent

这是一个简单的问答Agent，展示了Agent开发的基本流程：
1. 继承BaseAgent
2. 实现process方法
3. 加载提示词
4. 调用LLM
5. 处理响应
"""

import logging
from typing import Dict, Any
from app.agents.base import BaseAgent

logger = logging.getLogger(__name__)


class ExampleAgent(BaseAgent):
    """
    示例Agent - 简单的问答助手

    功能：根据用户问题，提供友好的回答
    """

    async def process(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        处理用户问题

        Args:
            input_data: {
                "query": str,           # 用户问题（必需）
                "context": str,         # 上下文信息（可选）
                "history": List[Dict]   # 历史对话（可选）
            }

        Returns:
            {
                "success": bool,
                "answer": str,          # AI回答
                "error": str,           # 错误信息（如果有）
                "model": str            # 使用的模型
            }
        """
        try:
            # 1. 验证输入
            self._validate_input(input_data, required_fields=["query"])

            query = input_data["query"]
            context = input_data.get("context", "")
            history = input_data.get("history", [])

            logger.info(f"ExampleAgent处理问题: {query[:50]}...")

            # 2. 加载提示词
            # 注意：提示词文件需要在 prompts/agents/example.txt
            # 如果文件不存在，会使用默认值
            system_prompt = self._load_prompt(
                "agent.example",
                default="你是一个友好的AI助手，帮助用户回答问题。"
            )

            # 3. 构建用户提示词
            user_prompt = self._build_user_prompt(query, context)

            # 4. 构建消息列表
            messages = self._build_messages(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                history=history
            )

            # 5. 调用LLM
            response = await self._call_llm(
                messages=messages,
                model="glm-4",
                temperature=0.7,
                max_tokens=1000
            )

            # 6. 返回结果
            return {
                "success": True,
                "answer": response.content,
                "model": "glm-4",
                "error": None
            }

        except Exception as e:
            logger.error(f"ExampleAgent处理失败: {e}")
            return {
                "success": False,
                "answer": None,
                "error": str(e),
                "model": None
            }

    def _build_user_prompt(self, query: str, context: str = "") -> str:
        """
        构建用户提示词

        Args:
            query: 用户问题
            context: 上下文信息

        Returns:
            格式化的用户提示词
        """
        if context:
            return f"""上下文信息：
{context}

用户问题：
{query}

请根据上下文信息回答用户问题。如果上下文信息不足，请基于你的知识回答。"""
        else:
            return query


# ============ 使用示例 ============

async def example_usage():
    """
    ExampleAgent使用示例

    演示如何创建和使用自定义Agent
    """
    # 创建Agent实例
    agent = ExampleAgent()

    # 示例1：简单问答
    result1 = await agent.process({
        "query": "什么是人工智能？"
    })
    print(f"回答1: {result1['answer']}")

    # 示例2：带上下文的问答
    result2 = await agent.process({
        "query": "如何使用？",
        "context": "我们提供了一个基于Python的Agent开发框架"
    })
    print(f"回答2: {result2['answer']}")

    # 示例3：带历史对话的问答
    result3 = await agent.process({
        "query": "那它有什么优势？",
        "history": [
            {"role": "user", "content": "什么是Agent框架？"},
            {"role": "assistant", "content": "Agent框架是一个用于开发AI代理的标准化工具..."}
        ]
    })
    print(f"回答3: {result3['answer']}")


if __name__ == "__main__":
    import asyncio

    # 运行示例
    asyncio.run(example_usage())
