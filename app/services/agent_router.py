"""
智能体路由服务
根据配置将请求分发到本地模型或云端API
支持RAG（检索增强生成）用于知识库助手
"""

import logging
import uuid
from typing import Dict, Any, Optional
from sqlalchemy.orm import Session

from app.models.agent_config import AgentConfig, AgentType, ModelSource
from app.services.llm_service import llm_service
from app.services.openvino_service import openvino_service
from app.services.rag_service import rag_service

logger = logging.getLogger(__name__)


class AgentRouter:
    """智能体路由器"""

    def __init__(self):
        self._config_cache: Dict[str, AgentConfig] = {}

    def get_active_config(self, db: Session, agent_type: str) -> Optional[AgentConfig]:
        """获取指定类型智能体的活跃配置"""
        config = db.query(AgentConfig).filter(
            AgentConfig.agent_type == agent_type,
            AgentConfig.is_active == True
        ).first()
        return config

    async def chat(
        self,
        db: Session,
        agent_type: str,
        message: str,
        conversation_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        统一对话接口

        Args:
            db: 数据库会话
            agent_type: 智能体类型 (process/knowledge)
            message: 用户消息
            conversation_id: 对话ID

        Returns:
            对话响应
        """
        config = self.get_active_config(db, agent_type)

        if not config:
            # 无配置时使用默认云端模型
            logger.warning(f"未找到{agent_type}智能体配置，使用默认云端模型")
            return await self._chat_cloud_default(agent_type, message, conversation_id)

        # 知识库助手使用RAG
        if agent_type == AgentType.KNOWLEDGE.value:
            return await self._chat_with_rag(config, message, conversation_id)

        # 根据模型来源路由（流程助手等）
        if config.model_source == ModelSource.LOCAL.value:
            return await self._chat_local(config, message, conversation_id)
        else:
            return await self._chat_cloud(config, message, conversation_id)

    async def _chat_cloud_default(
        self,
        agent_type: str,
        message: str,
        conversation_id: Optional[str]
    ) -> Dict[str, Any]:
        """使用默认云端模型"""
        conv_id = conversation_id or str(uuid.uuid4())

        # 根据智能体类型设置系统提示词
        if agent_type == AgentType.PROCESS.value:
            system_prompt = self._get_process_system_prompt()
        else:
            system_prompt = self._get_knowledge_system_prompt()

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": message}
        ]

        response = await llm_service.chat_completion(messages)

        return {
            "agent_type": agent_type,
            "message": response.content if response.success else f"请求失败: {response.error}",
            "model_source": "cloud",
            "model_name": response.model,
            "conversation_id": conv_id,
            "success": response.success
        }

    async def _chat_cloud(
        self,
        config: AgentConfig,
        message: str,
        conversation_id: Optional[str]
    ) -> Dict[str, Any]:
        """使用云端模型"""
        conv_id = conversation_id or str(uuid.uuid4())

        # 优先使用配置中的system_prompt，否则使用默认
        if config.system_prompt:
            system_prompt = config.system_prompt
        elif config.agent_type == AgentType.PROCESS.value:
            system_prompt = self._get_process_system_prompt()
        else:
            system_prompt = self._get_knowledge_system_prompt()

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": message}
        ]

        response = await llm_service.chat_completion(
            messages,
            model=config.model_name
        )

        return {
            "agent_type": config.agent_type,
            "message": response.content if response.success else f"请求失败: {response.error}",
            "model_source": "cloud",
            "model_name": config.model_name,
            "conversation_id": conv_id,
            "success": response.success
        }

    async def _chat_with_rag(
        self,
        config: AgentConfig,
        message: str,
        conversation_id: Optional[str]
    ) -> Dict[str, Any]:
        """使用RAG进行知识库问答"""
        conv_id = conversation_id or str(uuid.uuid4())

        try:
            # 获取配置的知识库集合（如果有）
            collections = None
            if config.knowledge_base_id:
                collections = [config.knowledge_base_id]

            # 使用配置中的system_prompt
            system_prompt = config.system_prompt if config.system_prompt else None

            # 调用RAG服务
            rag_result = await rag_service.query(
                question=message,
                collections=collections,
                top_k=5,
                system_prompt=system_prompt,
                include_sources=True
            )

            if rag_result.get("success"):
                answer = rag_result.get("answer", "")
                sources = rag_result.get("sources", [])

                # 如果有来源，添加来源引用
                if sources and rag_result.get("retrieved_count", 0) > 0:
                    source_refs = []
                    for i, src in enumerate(sources[:3], 1):
                        category = src.get("category", "")
                        doc_type = src.get("type", "")
                        if category or doc_type:
                            source_refs.append(f"{category}/{doc_type}" if category and doc_type else category or doc_type)

                    if source_refs:
                        answer += f"\n\n📚 参考来源：{', '.join(source_refs)}"

                return {
                    "agent_type": config.agent_type,
                    "message": answer,
                    "model_source": "rag",
                    "model_name": config.model_name,
                    "conversation_id": conv_id,
                    "success": True,
                    "rag_info": {
                        "retrieved_count": rag_result.get("retrieved_count", 0),
                        "sources": sources
                    }
                }
            else:
                # RAG查询失败，回退到普通云端模型
                logger.warning("RAG查询失败，回退到云端模型")
                return await self._chat_cloud(config, message, conversation_id)

        except Exception as e:
            logger.error(f"RAG处理失败: {e}")
            # 发生异常时回退到普通云端模型
            return await self._chat_cloud(config, message, conversation_id)

    async def _chat_local(
        self,
        config: AgentConfig,
        message: str,
        conversation_id: Optional[str]
    ) -> Dict[str, Any]:
        """使用本地OpenVINO模型"""
        conv_id = conversation_id or str(uuid.uuid4())

        if not openvino_service.is_available():
            logger.error("OpenVINO不可用")
            return {
                "agent_type": config.agent_type,
                "message": "本地模型服务不可用，请检查OpenVINO配置",
                "model_source": "local",
                "model_name": config.model_name,
                "conversation_id": conv_id,
                "success": False
            }

        if not config.local_model_path:
            return {
                "agent_type": config.agent_type,
                "message": "未配置本地模型路径",
                "model_source": "local",
                "model_name": config.model_name,
                "conversation_id": conv_id,
                "success": False
            }

        # 构建提示词 - 优先使用配置中的system_prompt
        if config.system_prompt:
            system_prompt = config.system_prompt
        elif config.agent_type == AgentType.PROCESS.value:
            system_prompt = self._get_process_system_prompt()
        else:
            system_prompt = self._get_knowledge_system_prompt()

        prompt = f"<|im_start|>system\n{system_prompt}<|im_end|>\n<|im_start|>user\n{message}<|im_end|>\n<|im_start|>assistant\n"

        result = await openvino_service.generate_text(
            model_path=config.local_model_path,
            prompt=prompt,
            device=config.local_device or "CPU",
            max_tokens=512,
            temperature=0.7
        )

        if result.get("success"):
            # 提取assistant回复
            generated = result.get("generated_text", "")
            # 移除prompt部分
            if "<|im_start|>assistant" in generated:
                response_text = generated.split("<|im_start|>assistant")[-1]
                response_text = response_text.replace("<|im_end|>", "").strip()
            else:
                response_text = generated

            return {
                "agent_type": config.agent_type,
                "message": response_text,
                "model_source": "local",
                "model_name": config.model_name,
                "conversation_id": conv_id,
                "success": True,
                "performance": {
                    "tokens_per_second": result.get("tokens_per_second"),
                    "first_token_latency": result.get("first_token_latency")
                }
            }
        else:
            return {
                "agent_type": config.agent_type,
                "message": f"本地模型推理失败: {result.get('error', '未知错误')}",
                "model_source": "local",
                "model_name": config.model_name,
                "conversation_id": conv_id,
                "success": False
            }

    def _get_process_system_prompt(self) -> str:
        """流程助手系统提示词"""
        return """你是AI-OA系统的流程助手，专门帮助用户处理企业办公自动化相关事务。

你的核心能力：
1. 智能表格填写 - 识别表格类型，智能填写
2. 审批流程优化 - 分析审批请求，提供决策建议
3. 信息快速检索 - 定位所需信息
4. 操作指导 - 提供操作指引
5. 合规检查 - 检查业务合规性

请用简洁专业的语言回答用户问题。"""

    def _get_knowledge_system_prompt(self) -> str:
        """知识库助手系统提示词"""
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


# 全局实例
agent_router = AgentRouter()
