"""
搜索Agent - 生产实现
专门处理信息查找、政策搜索等场景
解决"信息查找困难"的痛点

集成RAG服务，提供语义搜索和智能回答生成能力
"""

import json
import logging
import time
from typing import Dict, Any, List, Optional
from datetime import datetime

from app.services.llm_service import LLMService
from app.services.rag_service import rag_service
from app.services.knowledge_base_service import knowledge_base_service
from app.utils.metrics import monitor_agent_performance

logger = logging.getLogger(__name__)


class SearchAgent:
    """搜索Agent - 生产实现，集成RAG服务"""

    def __init__(self, llm_service: Optional[LLMService] = None):
        self.llm_service = llm_service if llm_service else LLMService()
        self.rag_service = rag_service
        self.knowledge_base = knowledge_base_service
        self.search_history: List[Dict[str, Any]] = []

    async def warm_up(self) -> None:
        """预热Agent - 验证服务可用性"""
        logger.info("SearchAgent 预热中...")

        # 验证知识库服务状态
        kb_status = self.knowledge_base.get_status()
        if kb_status.get("status") != "healthy":
            logger.warning(f"知识库服务状态异常: {kb_status}")
        else:
            logger.info(f"知识库就绪: {kb_status.get('total_documents', 0)} 个文档")

        logger.info("SearchAgent 预热完成")

    @monitor_agent_performance("search_agent", "intelligent_search")
    async def intelligent_search(
        self,
        query: str,
        user_context: Dict[str, Any],
        execution_context: Optional[Dict] = None,
        collections: Optional[List[str]] = None,
        top_k: int = 5,
        **kwargs
    ) -> Dict[str, Any]:
        """
        智能搜索 - 主要入口

        Args:
            query: 用户搜索查询
            user_context: 用户上下文（user_id, user_role, department等）
            execution_context: 执行上下文
            collections: 指定搜索的知识库集合，None表示搜索所有
            top_k: 返回结果数量

        Returns:
            包含搜索结果、回答和来源的响应
        """
        start_time = time.time()

        try:
            user_id = user_context.get("user_id", "unknown")
            logger.info(f"开始智能搜索: query={query[:50]}..., user={user_id}")

            # 1. 分析搜索意图（用于记录和优化）
            search_analysis = await self._analyze_search_query(query, user_context)

            # 2. 使用RAG服务进行语义搜索和回答生成
            rag_result = await self.rag_service.query(
                question=query,
                collections=collections,
                top_k=top_k,
                include_sources=True
            )

            # 3. 处理RAG结果
            if not rag_result.get("success"):
                raise ValueError(rag_result.get("error", "RAG查询失败"))

            # 4. 记录搜索历史
            self._record_search_history(query, user_context, rag_result)

            processing_time = time.time() - start_time

            return {
                "success": True,
                "query": query,
                "search_analysis": search_analysis,
                "answer": rag_result.get("answer", ""),
                "sources": rag_result.get("sources", []),
                "retrieved_count": rag_result.get("retrieved_count", 0),
                "processing_time": processing_time,
                "suggestions": self._generate_search_suggestions_sync(
                    rag_result.get("retrieved_count", 0),
                    search_analysis
                )
            }

        except Exception as e:
            logger.error(f"智能搜索失败: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "message": "搜索过程中遇到问题，请稍后重试",
                "processing_time": time.time() - start_time
            }

    async def _analyze_search_query(self, query: str, user_context: Dict) -> Dict[str, Any]:
        """分析搜索查询"""
        prompt = f"""
        分析用户的搜索查询，提取关键信息：

        用户查询：{query}
        用户角色：{user_context.get('user_role')}
        部门：{user_context.get('department')}

        请分析并返回JSON格式结果，包含：
        1. search_type：搜索类型（政策、流程、信息、帮助）
        2. keywords：关键词列表
        3. intent：搜索意图
        4. scope：搜索范围（公司政策、部门流程等）

        搜索类型判断：
        - 包含"政策"、"规定"、"标准" → 政策搜索
        - 包含"流程"、"步骤"、"如何" → 流程搜索
        - 包含"信息"、"查询"、"查找" → 信息搜索
        - 包含"帮助"、"指导"、"教程" → 帮助搜索
        """

        try:
            response = await self.llm_service.generate(prompt)

            # 简单的JSON解析
            if response.success and response.content:
                content = str(response.content or "").strip()
                if "{" in content and "}" in content:
                    start = content.find("{")
                    end = content.rfind("}") + 1
                    json_str = content[start:end]
                    return json.loads(json_str)

            # 备用分析
            return self._fallback_search_analysis(query)

        except Exception as e:
            logger.error(f"搜索查询分析失败: {e}")
            return self._fallback_search_analysis(query)

    def _fallback_search_analysis(self, query: str) -> Dict[str, Any]:
        """备用搜索分析"""
        query_lower = query.lower()

        # 简单关键词提取
        keywords = []
        if "报销" in query_lower:
            keywords.append("报销")
        if "政策" in query_lower:
            keywords.append("政策")
        if "流程" in query_lower:
            keywords.append("流程")
        if "请假" in query_lower:
            keywords.append("请假")
        if "采购" in query_lower:
            keywords.append("采购")

        # 确定搜索类型
        search_type = "信息搜索"
        if any(word in query_lower for word in ["政策", "规定", "标准"]):
            search_type = "政策搜索"
        elif any(word in query_lower for word in ["流程", "步骤", "如何"]):
            search_type = "流程搜索"

        return {
            "search_type": search_type,
            "keywords": keywords,
            "intent": "查找" + "、".join(keywords) if keywords else "信息",
            "scope": "公司政策"
        }

    def _record_search_history(
        self,
        query: str,
        user_context: Dict[str, Any],
        rag_result: Dict[str, Any]
    ) -> None:
        """记录搜索历史"""
        self.search_history.append({
            "query": query,
            "user_id": user_context.get("user_id"),
            "retrieved_count": rag_result.get("retrieved_count", 0),
            "success": rag_result.get("success", False),
            "timestamp": datetime.now().isoformat()
        })

        # 限制历史记录数量
        if len(self.search_history) > 1000:
            self.search_history = self.search_history[-500:]

    def _generate_search_suggestions_sync(
        self,
        retrieved_count: int,
        search_analysis: Dict[str, Any]
    ) -> List[str]:
        """生成搜索建议（同步方法）"""
        suggestions = []
        search_type = search_analysis.get("search_type", "")

        if retrieved_count == 0:
            suggestions.append("未找到相关信息，建议使用更具体的关键词")
            suggestions.append("可以尝试搜索相关的政策或流程名称")
        else:
            suggestions.append(f"找到 {retrieved_count} 条相关信息")

            # 基于搜索类型提供针对性建议
            if search_type == "政策搜索":
                suggestions.append("如需最新政策，请联系人事部门确认")
            elif search_type == "流程搜索":
                suggestions.append("具体流程细节请参考OA系统操作指南")

        return suggestions

    async def get_system_status(self) -> Dict[str, Any]:
        """获取搜索Agent状态"""
        kb_status = self.knowledge_base.get_status()
        rag_status = self.rag_service.get_status()

        return {
            "agent_status": "healthy",
            "knowledge_base": kb_status,
            "rag_service": rag_status,
            "search_history_count": len(self.search_history),
            "last_updated": datetime.now().isoformat()
        }

    async def add_knowledge(
        self,
        collection: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        向知识库添加新知识

        Args:
            collection: 集合名称
            content: 文档内容
            metadata: 元数据

        Returns:
            添加结果
        """
        return await self.rag_service.add_knowledge(
            collection=collection,
            content=content,
            metadata=metadata
        )

    def get_search_history(
        self,
        user_id: Optional[str] = None,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        获取搜索历史

        Args:
            user_id: 用户ID，None表示获取所有
            limit: 返回数量限制

        Returns:
            搜索历史列表
        """
        history = self.search_history

        if user_id:
            history = [h for h in history if h.get("user_id") == user_id]

        return history[-limit:]