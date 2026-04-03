"""
Skill 加载服务（核心服务器版本）
负责加载和解析 Skill 文件（Markdown + YAML frontmatter 格式）

Skill 文件格式：
    ---
    name: 表单智能填写
    version: "1.0"
    description: 从自然语言提取表单字段
    model: glm-5
    temperature: 0.3
    max_tokens: 2000
    tools_ref: form_fill        # 引用同名 .tools.json
    ---
    你是智能表单助手...

扩展能力（2026-04-03 重构）：
- frontmatter 支持 model/temperature/max_tokens/tools_ref
- tools_ref 自动加载同目录下的 .tools.json sidecar 文件
- 兼容已有的 process_assistant.md / knowledge_assistant.md
"""

import os
import json
import logging
from typing import Optional, Dict, List, Any
from dataclasses import dataclass, field

import yaml

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@dataclass
class Skill:
    """Skill 数据结构"""
    name: str
    content: str
    metadata: Dict = field(default_factory=dict)
    tools: Optional[List[Dict[str, Any]]] = None

    def to_dict(self) -> Dict:
        """转换为字典（用于 API 响应）"""
        result = {
            "name": self.name,
            "content": self.content,
            "metadata": self.metadata,
        }
        if self.tools:
            result["tools"] = self.tools
        return result

    @property
    def model(self) -> str:
        """LLM 模型名称"""
        return self.metadata.get("model", "glm-5")

    @property
    def temperature(self) -> float:
        """温度参数"""
        return float(self.metadata.get("temperature", 0.7))

    @property
    def max_tokens(self) -> Optional[int]:
        """最大 token 数"""
        val = self.metadata.get("max_tokens")
        return int(val) if val is not None else None

    @property
    def tools_ref(self) -> Optional[str]:
        """关联的 tools.json 文件名（不含扩展名）"""
        return self.metadata.get("tools_ref")

    @property
    def description(self) -> str:
        return self.metadata.get("description", "")

    @property
    def version(self) -> str:
        return self.metadata.get("version", "1.0")

    @property
    def has_tools(self) -> bool:
        return self.tools is not None and len(self.tools) > 0


class SkillLoader:
    """
    Skill 加载器

    从指定目录加载 .md 格式的 Skill 文件，
    支持 YAML frontmatter 解析、tools.json sidecar 加载和内存缓存。
    """

    def __init__(self, skill_dir: str = None):
        self.skill_dir = skill_dir or os.path.join(BASE_DIR, "skills")
        self._cache: Dict[str, Skill] = {}

    def load(self, skill_name: str) -> Optional[Skill]:
        """
        加载指定名称的 Skill

        Args:
            skill_name: Skill 名称（不含 .md 后缀）

        Returns:
            Skill 对象，文件不存在或解析失败返回 None
        """
        if not skill_name:
            return None

        if skill_name in self._cache:
            return self._cache[skill_name]

        file_path = os.path.join(self.skill_dir, f"{skill_name}.md")

        if not os.path.exists(file_path):
            logger.warning(f"Skill 文件不存在: {file_path}")
            return None

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                raw = f.read()

            metadata, body = self._parse_frontmatter(raw, skill_name)

            # 加载关联的 tools.json
            tools = self._load_tools(metadata.get("tools_ref"), skill_name)

            skill = Skill(
                name=metadata.get("name", skill_name),
                content=body,
                metadata=metadata,
                tools=tools,
            )

            self._cache[skill_name] = skill
            logger.info(
                f"加载 Skill: {skill_name}"
                f" (model={skill.model}, tools={'yes' if skill.has_tools else 'no'})"
            )
            return skill

        except IOError as e:
            logger.error(f"读取 Skill 文件失败 {skill_name}: {e}")
            return None

    def _parse_frontmatter(self, raw: str, skill_name: str) -> tuple:
        """解析 YAML frontmatter，返回 (metadata, body)"""
        metadata = {}
        body = raw

        if raw.startswith("---"):
            parts = raw.split("---", 2)
            if len(parts) >= 3:
                try:
                    metadata = yaml.safe_load(parts[1]) or {}
                except yaml.YAMLError as e:
                    logger.error(f"Skill {skill_name} YAML 解析失败: {e}")
                    metadata = {}
                body = parts[2].strip()

        return metadata, body

    def _load_tools(self, tools_ref: Optional[str], skill_name: str) -> Optional[List[Dict[str, Any]]]:
        """
        加载 tools.json sidecar 文件

        查找顺序：
        1. tools_ref 指定的文件名：skills/{tools_ref}.tools.json
        2. 与 Skill 同名的文件：skills/{skill_name}.tools.json
        """
        candidates = []
        if tools_ref:
            candidates.append(os.path.join(self.skill_dir, f"{tools_ref}.tools.json"))
        candidates.append(os.path.join(self.skill_dir, f"{skill_name}.tools.json"))

        for path in candidates:
            if os.path.exists(path):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    # 支持两种格式：直接是 list，或者 {"tools": [...]}
                    if isinstance(data, list):
                        tools = data
                    elif isinstance(data, dict) and "tools" in data:
                        tools = data["tools"]
                    else:
                        logger.warning(f"tools.json 格式不符合预期: {path}")
                        continue
                    logger.info(f"加载 tools: {path} ({len(tools)} 个工具)")
                    return tools
                except (json.JSONDecodeError, IOError) as e:
                    logger.error(f"加载 tools.json 失败 {path}: {e}")
                    continue

        return None

    def get_default_skill_name(self, agent_type: str) -> str:
        """获取智能体类型的默认 Skill 名称"""
        defaults = {
            "process": "process_assistant",
            "knowledge": "knowledge_assistant",
        }
        return defaults.get(agent_type, "process_assistant")

    def get_system_prompt(self, agent_type: str, skill_name: str = None, extra_prompt: str = None) -> str:
        """
        获取完整的 system_prompt

        Args:
            agent_type: 智能体类型
            skill_name: 指定的 Skill 名称（可选）
            extra_prompt: 额外的补充指令（可选）

        Returns:
            完整的 system_prompt
        """
        if not skill_name:
            skill_name = self.get_default_skill_name(agent_type)

        skill = self.load(skill_name)

        if skill:
            base_prompt = skill.content
        else:
            base_prompt = self._get_fallback_prompt(agent_type)

        if extra_prompt:
            base_prompt += f"\n\n## 补充指令\n{extra_prompt}"

        return base_prompt

    def _get_fallback_prompt(self, agent_type: str) -> str:
        """获取降级的硬编码提示词"""
        if agent_type == "process":
            return (
                "你是AI-OA系统的流程助手，专门帮助用户处理企业办公自动化相关事务。\n"
                "请用简洁专业的语言回答用户问题。"
            )
        else:
            return (
                "你是AI-OA系统的知识库助手，专门帮助用户查询企业知识库和文档。\n"
                "回答时请基于知识库内容回答，如无相关信息，明确告知用户。"
            )

    def list_skills(self) -> list:
        """列出所有可用的 Skill"""
        skills = []
        if os.path.exists(self.skill_dir):
            for filename in os.listdir(self.skill_dir):
                if filename.endswith(".md"):
                    skill_name = filename[:-3]
                    skill = self.load(skill_name)
                    if skill:
                        skills.append({
                            "name": skill_name,
                            "display_name": skill.name,
                            "description": skill.description,
                            "model": skill.model,
                            "has_tools": skill.has_tools,
                        })
        return skills

    def clear_cache(self) -> None:
        """清除缓存（用于热更新场景）"""
        self._cache.clear()
        logger.info("Skill 缓存已清除")


# 全局实例
skill_loader = SkillLoader()
