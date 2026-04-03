"""
知识库服务
提供基于向量数据库的文档存储和检索功能
"""

import logging
import hashlib
import os
from typing import List, Dict, Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

# 尝试导入ChromaDB，如果不可用则使用简单的内存实现
try:
    import chromadb
    from chromadb.config import Settings
    CHROMADB_AVAILABLE = True
except ImportError:
    CHROMADB_AVAILABLE = False
    logger.warning("ChromaDB未安装，使用内存知识库。运行: pip install chromadb")


class Document:
    """文档类"""
    def __init__(
        self,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
        doc_id: Optional[str] = None
    ):
        self.content = content
        self.metadata = metadata or {}
        self.doc_id = doc_id or self._generate_id(content)
        self.created_at = datetime.now().isoformat()

    def _generate_id(self, content: str) -> str:
        """根据内容生成唯一ID"""
        return hashlib.md5(content.encode()).hexdigest()[:16]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "doc_id": self.doc_id,
            "content": self.content,
            "metadata": self.metadata,
            "created_at": self.created_at
        }


class SimpleVectorStore:
    """简单的内存向量存储（当ChromaDB不可用时使用）"""

    def __init__(self):
        self.documents: Dict[str, Document] = {}
        self.collections: Dict[str, Dict[str, Document]] = {}

    def create_collection(self, name: str) -> None:
        if name not in self.collections:
            self.collections[name] = {}

    def add_documents(self, collection: str, documents: List[Document]) -> None:
        if collection not in self.collections:
            self.create_collection(collection)
        for doc in documents:
            self.collections[collection][doc.doc_id] = doc

    def search(self, collection: str, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """简单的关键词搜索（非向量搜索）- 支持中文分词"""
        import re

        if collection not in self.collections:
            return []

        results = []
        query_lower = query.lower()

        # 提取中文和英文关键词
        chinese_chars = re.findall(r'[\u4e00-\u9fff]+', query_lower)
        english_words = re.findall(r'[a-zA-Z]+', query_lower)

        # 合并关键词
        keywords = []
        for chars in chinese_chars:
            # 中文按2-3字分词（简单n-gram）
            for i in range(len(chars)):
                if i + 2 <= len(chars):
                    keywords.append(chars[i:i+2])
                if i + 3 <= len(chars):
                    keywords.append(chars[i:i+3])
            keywords.append(chars)  # 完整词
        keywords.extend(english_words)

        if not keywords:
            keywords = query_lower.split()

        for doc in self.collections[collection].values():
            content_lower = doc.content.lower()
            # 计算相关性分数 - 使用OR逻辑
            score = 0
            matched_keywords = 0
            for keyword in keywords:
                if keyword in content_lower:
                    score += 1
                    matched_keywords += 1

            if matched_keywords > 0:
                # 归一化分数
                normalized_score = (matched_keywords / len(keywords)) * 0.5 + min(score / 5, 0.5)
                results.append({
                    "doc_id": doc.doc_id,
                    "content": doc.content,
                    "metadata": doc.metadata,
                    "score": normalized_score
                })

        # 按分数排序
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]

    def delete_collection(self, name: str) -> bool:
        if name in self.collections:
            del self.collections[name]
            return True
        return False

    def list_collections(self) -> List[str]:
        return list(self.collections.keys())

    def get_collection_stats(self, name: str) -> Dict[str, Any]:
        if name not in self.collections:
            return {"exists": False}
        return {
            "exists": True,
            "document_count": len(self.collections[name]),
            "name": name
        }


class ChromaVectorStore:
    """ChromaDB向量存储"""

    def __init__(self, persist_directory: str = "./data/chromadb"):
        self.persist_directory = persist_directory
        os.makedirs(persist_directory, exist_ok=True)

        self.client = chromadb.PersistentClient(
            path=persist_directory,
            settings=Settings(anonymized_telemetry=False)
        )
        logger.info(f"ChromaDB初始化完成，数据目录: {persist_directory}")

    def create_collection(self, name: str) -> None:
        """创建或获取集合"""
        try:
            self.client.get_or_create_collection(name=name)
            logger.info(f"集合 {name} 已创建/获取")
        except Exception as e:
            logger.error(f"创建集合失败: {e}")
            raise

    def add_documents(self, collection: str, documents: List[Document]) -> None:
        """添加文档到集合"""
        try:
            coll = self.client.get_or_create_collection(name=collection)

            ids = [doc.doc_id for doc in documents]
            contents = [doc.content for doc in documents]
            metadatas = [doc.metadata for doc in documents]

            coll.add(
                documents=contents,
                metadatas=metadatas,
                ids=ids
            )
            logger.info(f"已添加 {len(documents)} 个文档到集合 {collection}")
        except Exception as e:
            logger.error(f"添加文档失败: {e}")
            raise

    def search(self, collection: str, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """向量搜索"""
        try:
            coll = self.client.get_collection(name=collection)
            results = coll.query(
                query_texts=[query],
                n_results=top_k
            )

            search_results = []
            if results and results["documents"]:
                for i, doc in enumerate(results["documents"][0]):
                    search_results.append({
                        "doc_id": results["ids"][0][i] if results["ids"] else None,
                        "content": doc,
                        "metadata": results["metadatas"][0][i] if results["metadatas"] else {},
                        "score": 1.0 - (results["distances"][0][i] if results["distances"] else 0)
                    })

            return search_results
        except Exception as e:
            logger.error(f"搜索失败: {e}")
            return []

    def delete_collection(self, name: str) -> bool:
        """删除集合"""
        try:
            self.client.delete_collection(name=name)
            logger.info(f"集合 {name} 已删除")
            return True
        except Exception as e:
            logger.error(f"删除集合失败: {e}")
            return False

    def list_collections(self) -> List[str]:
        """列出所有集合"""
        return [c.name for c in self.client.list_collections()]

    def get_collection_stats(self, name: str) -> Dict[str, Any]:
        """获取集合统计信息"""
        try:
            coll = self.client.get_collection(name=name)
            return {
                "exists": True,
                "document_count": coll.count(),
                "name": name
            }
        except Exception:
            return {"exists": False}


class KnowledgeBaseService:
    """知识库服务"""

    def __init__(self, persist_directory: str = "./data/knowledge_base"):
        """
        初始化知识库服务

        Args:
            persist_directory: 数据持久化目录
        """
        self.persist_directory = persist_directory

        # 根据可用性选择向量存储
        if CHROMADB_AVAILABLE:
            self.vector_store = ChromaVectorStore(persist_directory)
            self.use_chromadb = True
            logger.info("使用ChromaDB向量存储")
        else:
            self.vector_store = SimpleVectorStore()
            self.use_chromadb = False
            logger.info("使用简单内存存储（建议安装chromadb以获得更好的搜索效果）")

        # 初始化默认知识库
        self._init_default_knowledge_bases()

    def _init_default_knowledge_bases(self) -> None:
        """初始化默认知识库"""
        # 创建企业知识库集合
        default_collections = ["company_policies", "procedures", "faq"]
        for collection in default_collections:
            self.vector_store.create_collection(collection)

        # 添加一些默认的企业知识
        self._add_default_knowledge()

    def _add_default_knowledge(self) -> None:
        """添加默认知识内容"""
        # 检查是否已有数据
        stats = self.vector_store.get_collection_stats("company_policies")
        if stats.get("document_count", 0) > 0:
            return

        # 公司政策
        policies = [
            Document(
                content="差旅费报销标准：国内出差住宿费上限500元/天，一线城市可上浮20%。交通费实报实销，需提供发票。餐费补贴100元/天，无需发票。",
                metadata={"category": "报销政策", "type": "差旅费", "version": "2024"}
            ),
            Document(
                content="年假制度：员工工龄1-5年享有5天年假，5-10年享有10天年假，10年以上享有15天年假。年假需提前3天申请，跨年不可累积。",
                metadata={"category": "假期政策", "type": "年假", "version": "2024"}
            ),
            Document(
                content="病假管理：员工因病请假需提供医院证明。病假前3天带薪，超过3天按基本工资80%发放。全年累计病假不超过30天。",
                metadata={"category": "假期政策", "type": "病假", "version": "2024"}
            ),
            Document(
                content="加班审批流程：加班需提前1天提交申请，经部门经理审批后方可执行。工作日加班按1.5倍计算，周末按2倍计算，法定节假日按3倍计算。",
                metadata={"category": "加班政策", "type": "审批流程", "version": "2024"}
            ),
            Document(
                content="采购审批权限：5000元以下由部门经理审批，5000-20000元需总监审批，20000元以上需副总裁审批。紧急采购可先执行后补审批。",
                metadata={"category": "采购政策", "type": "审批权限", "version": "2024"}
            ),
            Document(
                content="招待费标准：部门级别招待每次不超过500元，需提供消费清单。总监级别招待每次不超过1000元。所有招待费需提前申请，事后24小时内提交报销。",
                metadata={"category": "报销政策", "type": "招待费", "version": "2024"}
            ),
            Document(
                content="薪资发放时间：每月15日发放上月工资，如遇节假日提前至最近工作日。年终奖于次年1月发放。",
                metadata={"category": "薪资政策", "type": "发放时间", "version": "2024"}
            ),
            Document(
                content="员工培训政策：新员工入职后需完成为期3天的入职培训。每位员工每年有3000元培训预算，可用于外部培训或购买学习资料。",
                metadata={"category": "培训政策", "type": "培训预算", "version": "2024"}
            ),
        ]

        self.vector_store.add_documents("company_policies", policies)

        # 常见问题
        faqs = [
            Document(
                content="问：如何申请年假？答：登录OA系统，进入请假模块，选择年假类型，填写请假天数和原因，提交后等待部门经理审批。",
                metadata={"category": "FAQ", "type": "请假", "question": "如何申请年假"}
            ),
            Document(
                content="问：报销需要哪些材料？答：需要提供发票原件、费用明细单、审批通过的申请单。电子发票需打印并签字确认。",
                metadata={"category": "FAQ", "type": "报销", "question": "报销需要哪些材料"}
            ),
            Document(
                content="问：如何查询工资条？答：登录OA系统，进入人事模块，点击我的工资条，可查看近12个月的工资详情。",
                metadata={"category": "FAQ", "type": "薪资", "question": "如何查询工资条"}
            ),
            Document(
                content="问：忘记OA密码怎么办？答：点击登录页面的忘记密码，通过绑定的手机号或邮箱重置密码。也可联系IT部门处理。",
                metadata={"category": "FAQ", "type": "系统", "question": "忘记OA密码怎么办"}
            ),
        ]

        self.vector_store.add_documents("faq", faqs)

        logger.info("默认知识库内容已初始化")

    def add_documents(
        self,
        collection: str,
        documents: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        添加文档到知识库

        Args:
            collection: 集合名称
            documents: 文档列表，每个文档包含content和可选的metadata

        Returns:
            添加结果
        """
        try:
            docs = [
                Document(
                    content=doc["content"],
                    metadata=doc.get("metadata", {}),
                    doc_id=doc.get("doc_id")
                )
                for doc in documents
            ]

            self.vector_store.add_documents(collection, docs)

            return {
                "success": True,
                "added_count": len(docs),
                "collection": collection
            }
        except Exception as e:
            logger.error(f"添加文档失败: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    def search(
        self,
        query: str,
        collections: Optional[List[str]] = None,
        top_k: int = 5
    ) -> List[Dict[str, Any]]:
        """
        搜索知识库

        Args:
            query: 搜索查询
            collections: 要搜索的集合列表，None表示搜索所有
            top_k: 返回结果数量

        Returns:
            搜索结果列表
        """
        if collections is None:
            collections = self.vector_store.list_collections()

        all_results = []
        for collection in collections:
            results = self.vector_store.search(collection, query, top_k)
            for result in results:
                result["collection"] = collection
            all_results.extend(results)

        # 按分数排序
        all_results.sort(key=lambda x: x.get("score", 0), reverse=True)
        return all_results[:top_k]

    def create_collection(self, name: str) -> Dict[str, Any]:
        """创建新集合"""
        try:
            self.vector_store.create_collection(name)
            return {"success": True, "collection": name}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def delete_collection(self, name: str) -> Dict[str, Any]:
        """删除集合"""
        success = self.vector_store.delete_collection(name)
        return {"success": success, "collection": name}

    def list_collections(self) -> List[str]:
        """列出所有集合"""
        return self.vector_store.list_collections()

    def get_collection_stats(self, name: str) -> Dict[str, Any]:
        """获取集合统计信息"""
        return self.vector_store.get_collection_stats(name)

    def get_status(self) -> Dict[str, Any]:
        """获取知识库服务状态"""
        collections = self.list_collections()
        total_docs = 0
        collection_stats = {}

        for coll in collections:
            stats = self.get_collection_stats(coll)
            collection_stats[coll] = stats
            total_docs += stats.get("document_count", 0)

        return {
            "status": "healthy",
            "use_chromadb": self.use_chromadb,
            "total_collections": len(collections),
            "total_documents": total_docs,
            "collections": collection_stats,
            "persist_directory": self.persist_directory
        }


# 全局实例 - 延迟初始化
_knowledge_base_service: Optional[KnowledgeBaseService] = None


def get_knowledge_base_service() -> KnowledgeBaseService:
    """获取知识库服务实例（延迟初始化）"""
    global _knowledge_base_service
    if _knowledge_base_service is None:
        logger.info("初始化知识库服务...")
        _knowledge_base_service = KnowledgeBaseService()
    return _knowledge_base_service


# 兼容旧代码的属性访问
class _LazyKnowledgeBaseService:
    """延迟加载的知识库服务代理"""
    def __getattr__(self, name):
        return getattr(get_knowledge_base_service(), name)


knowledge_base_service = _LazyKnowledgeBaseService()
