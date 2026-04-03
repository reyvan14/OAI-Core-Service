"""
RAG服务
提供检索增强生成功能，结合知识库检索和LLM生成
"""

import logging
from typing import List, Dict, Any, Optional

from app.services.knowledge_base_service import knowledge_base_service
from app.services.llm_service import llm_service

logger = logging.getLogger(__name__)


class RAGService:
    """RAG（检索增强生成）服务"""

    def __init__(self):
        self.knowledge_base = knowledge_base_service
        self.llm = llm_service

    async def query(
        self,
        question: str,
        collections: Optional[List[str]] = None,
        top_k: int = 5,
        system_prompt: Optional[str] = None,
        include_sources: bool = True
    ) -> Dict[str, Any]:
        """
        RAG查询 - 检索相关文档并生成回答

        Args:
            question: 用户问题
            collections: 要搜索的集合列表
            top_k: 检索文档数量
            system_prompt: 自定义系统提示词
            include_sources: 是否在回答中包含来源

        Returns:
            包含回答和来源的结果
        """
        try:
            # 1. 检索相关文档
            logger.info(f"RAG查询: {question[:50]}...")
            retrieved_docs = self.knowledge_base.search(
                query=question,
                collections=collections,
                top_k=top_k
            )

            if not retrieved_docs:
                return await self._generate_no_context_response(question, system_prompt)

            # 2. 构建上下文
            context = self._build_context(retrieved_docs)

            # 3. 生成回答
            answer = await self._generate_answer(question, context, system_prompt)

            # 4. 构建响应
            response = {
                "success": True,
                "answer": answer,
                "retrieved_count": len(retrieved_docs)
            }

            if include_sources:
                response["sources"] = self._format_sources(retrieved_docs)

            return response

        except Exception as e:
            logger.error(f"RAG查询失败: {e}")
            return {
                "success": False,
                "error": str(e),
                "answer": "抱歉，查询过程中遇到问题，请稍后重试。"
            }

    def _build_context(self, documents: List[Dict[str, Any]]) -> str:
        """构建上下文文本"""
        context_parts = []
        for i, doc in enumerate(documents, 1):
            content = doc.get("content", "")
            metadata = doc.get("metadata", {})
            category = metadata.get("category", "")
            doc_type = metadata.get("type", "")

            header = f"[文档{i}]"
            if category:
                header += f" [{category}]"
            if doc_type:
                header += f" [{doc_type}]"

            context_parts.append(f"{header}\n{content}")

        return "\n\n".join(context_parts)

    async def _generate_answer(
        self,
        question: str,
        context: str,
        system_prompt: Optional[str] = None
    ) -> str:
        """使用LLM生成回答"""
        default_system = """你是AI-OA系统的知识库助手，专门帮助用户查询企业知识库和文档。

回答规则：
1. 基于提供的参考文档内容回答问题
2. 如果参考文档中没有相关信息，明确告知用户
3. 回答要准确、简洁、专业
4. 适当引用来源文档
5. 如有多个相关信息，分点列出"""

        system = system_prompt or default_system

        prompt = f"""请根据以下参考文档回答用户的问题。

===参考文档===
{context}

===用户问题===
{question}

===回答==="""

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt}
        ]

        response = await self.llm.chat_completion(messages)

        if response.success:
            return response.content
        else:
            logger.error(f"LLM生成失败: {response.error}")
            return self._fallback_answer(question, context)

    async def _generate_no_context_response(
        self,
        question: str,
        system_prompt: Optional[str] = None
    ) -> Dict[str, Any]:
        """当没有检索到文档时的响应"""
        default_system = """你是AI-OA系统的知识库助手。用户的问题在知识库中没有找到相关信息。
请友好地告知用户，并提供可能的帮助建议。"""

        system = system_prompt or default_system

        prompt = f"""用户问题: {question}

知识库中没有找到与此问题相关的信息。请友好地回复用户，并建议可能的解决方案。"""

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt}
        ]

        response = await self.llm.chat_completion(messages)

        answer = response.content if response.success else "抱歉，我在知识库中没有找到相关信息。建议您联系相关部门或查看公司内部文档获取帮助。"

        return {
            "success": True,
            "answer": answer,
            "retrieved_count": 0,
            "sources": [],
            "note": "知识库中未找到相关信息"
        }

    def _fallback_answer(self, question: str, context: str) -> str:
        """备用回答生成（当LLM不可用时）"""
        # 简单提取上下文中的关键信息
        if context:
            lines = context.split("\n")
            relevant_lines = [
                line for line in lines
                if any(word in line.lower() for word in question.lower().split())
            ]
            if relevant_lines:
                return "根据知识库信息：\n" + "\n".join(relevant_lines[:3])

        return "抱歉，暂时无法生成回答。请稍后重试或联系管理员。"

    def _format_sources(self, documents: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """格式化来源信息"""
        sources = []
        for doc in documents:
            metadata = doc.get("metadata", {})
            source = {
                "collection": doc.get("collection", "unknown"),
                "category": metadata.get("category", ""),
                "type": metadata.get("type", ""),
                "relevance": round(doc.get("score", 0), 2)
            }
            # 添加内容摘要
            content = doc.get("content", "")
            source["summary"] = content[:100] + "..." if len(content) > 100 else content
            sources.append(source)
        return sources

    async def add_knowledge(
        self,
        collection: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        添加知识到知识库

        Args:
            collection: 集合名称
            content: 文档内容
            metadata: 元数据

        Returns:
            添加结果
        """
        return self.knowledge_base.add_documents(
            collection=collection,
            documents=[{
                "content": content,
                "metadata": metadata or {}
            }]
        )

    async def batch_add_knowledge(
        self,
        collection: str,
        documents: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """批量添加知识"""
        return self.knowledge_base.add_documents(
            collection=collection,
            documents=documents
        )

    def get_status(self) -> Dict[str, Any]:
        """获取RAG服务状态"""
        kb_status = self.knowledge_base.get_status()
        return {
            "rag_service": "healthy",
            "knowledge_base": kb_status,
            "llm_available": True  # 假设LLM服务可用
        }


# 全局实例
rag_service = RAGService()
