"""
Skill 加载服务（核心服务器版本）
负责加载和解析 Skill 文件（Markdown + YAML frontmatter 格式）
"""

import os
import logging
from typing import Optional, Dict
from dataclasses import dataclass, field

import yaml

logger = logging.getLogger(__name__)

# 获取项目根目录
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@dataclass
class Skill:
    """Skill 数据结构"""
    name: str
    content: str
    metadata: Dict = field(default_factory=dict)

    def to_dict(self) -> Dict:
        """转换为字典（用于 API 响应）"""
        return {
            "name": self.name,
            "content": self.content,
            "metadata": self.metadata
        }


class SkillLoader:
    """
    Skill 加载器

    从指定目录加载 .md 格式的 Skill 文件，
    支持 YAML frontmatter 解析和内存缓存。
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

        # 检查缓存
        if skill_name in self._cache:
            return self._cache[skill_name]

        # 构建文件路径
        file_path = os.path.join(self.skill_dir, f"{skill_name}.md")

        if not os.path.exists(file_path):
            logger.warning(f"Skill 文件不存在: {file_path}")
            return None

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()

            # 解析 YAML frontmatter
            metadata = {}
            body = content

            if content.startswith("---"):
                parts = content.split("---", 2)
                if len(parts) >= 3:
                    try:
                        metadata = yaml.safe_load(parts[1]) or {}
                    except yaml.YAMLError as e:
                        logger.error(f"Skill {skill_name} YAML 解析失败: {e}")
                        metadata = {}
                    body = parts[2].strip()

            skill = Skill(
                name=metadata.get("name", skill_name),
                content=body,
                metadata=metadata,
            )

            # 缓存
            self._cache[skill_name] = skill
            logger.info(f"加载 Skill: {skill_name}")

            return skill

        except IOError as e:
            logger.error(f"读取 Skill 文件失败 {skill_name}: {e}")
            return None

    def get_default_skill_name(self, agent_type: str) -> str:
        """
        获取智能体类型的默认 Skill 名称

        Args:
            agent_type: 智能体类型 (process/knowledge)

        Returns:
            默认 Skill 名称
        """
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
        # 确定 Skill 名称
        if not skill_name:
            skill_name = self.get_default_skill_name(agent_type)

        # 加载 Skill
        skill = self.load(skill_name)

        if skill:
            base_prompt = skill.content
        else:
            # 降级到硬编码默认值
            base_prompt = self._get_fallback_prompt(agent_type)

        # 追加额外指令
        if extra_prompt:
            base_prompt += f"\n\n## 补充指令\n{extra_prompt}"

        return base_prompt

    def _get_fallback_prompt(self, agent_type: str) -> str:
        """获取降级的硬编码提示词"""
        if agent_type == "process":
            return """你是AI-OA系统的流程助手，专门帮助用户处理企业办公自动化相关事务。

你的核心能力：
1. 智能表格填写 - 识别表格类型，智能填写
2. 审批流程优化 - 分析审批请求，提供决策建议
3. 信息快速检索 - 定位所需信息
4. 操作指导 - 提供操作指引
5. 合规检查 - 检查业务合规性

请用简洁专业的语言回答用户问题。"""
        else:
            return """你是AI-OA系统的知识库助手，专门帮助用户查询企业知识库和文档。

你的核心能力：
1. 知识检索 - 从知识库中查找相关信息
2. 文档问答 - 基于文档内容回答问题
3. 政策解读 - 解释公司政策和规章制度
4. 流程说明 - 说明各类业务流程

回答时请：
- 基于知识库内容回答
- 如无相关信息，明确告知用户
- 引用来源（如有）"""

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
                            "description": skill.metadata.get("description", "")
                        })
        return skills

    def clear_cache(self) -> None:
        """清除缓存（用于热更新场景）"""
        self._cache.clear()
        logger.info("Skill 缓存已清除")


# 全局实例
skill_loader = SkillLoader()
