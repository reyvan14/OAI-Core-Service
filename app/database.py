"""
数据库配置和连接管理
支持SQLite、PostgreSQL等数据库
"""

import logging
from typing import Optional, Any, Dict
from sqlalchemy import create_engine, MetaData, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool
import os

logger = logging.getLogger(__name__)

# 数据库配置
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://reyvan@localhost:5432/ai_oa"  # 默认使用PostgreSQL (psycopg3)
)

# 兼容psycopg2的URL格式（自动转换为psycopg3）
if DATABASE_URL.startswith("postgresql://") and "+psycopg" not in DATABASE_URL:
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)

# 创建数据库引擎
if "postgresql" in DATABASE_URL:
    engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True,
        pool_recycle=300,
        pool_size=20,
        max_overflow=30,
        pool_timeout=30,
        echo=os.getenv("DEBUG", "false").lower() == "true",
        # 性能优化配置
        connect_args={
            "application_name": "ai_oa_system",
            "connect_timeout": 10
        }
    )
else:
    # SQLite 配置（用于测试或开发环境）
    engine = create_engine(
        DATABASE_URL,
        connect_args={
            "check_same_thread": False,
            "timeout": 30
        },
        poolclass=StaticPool,
        echo=os.getenv("DEBUG", "false").lower() == "true",
        # SQLite性能优化
        execution_options={
            "sqlite_raw_colnames": True
        }
    )

# 创建会话工厂
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# 创建Agent系统专用的基础模型类（与server.py完全隔离）
# 这是独立的declarative_base，避免与server.py的Base冲突
AgentBase = declarative_base()

# 为了兼容性，保留Base别名（指向AgentBase）
Base = AgentBase

# 导出AgentBase供Agent模型使用
__all__ = ['Base', 'AgentBase', 'db_manager', 'get_db', 'init_database']

# 元数据
metadata = MetaData()


class DatabaseManager:
    """数据库管理器"""

    def __init__(self):
        self.engine = engine
        self.SessionLocal = SessionLocal

    def get_session(self) -> Session:
        """获取数据库会话"""
        return self.SessionLocal()

    async def create_tables(self):
        """创建所有数据表（Agent系统专用）"""
        try:
            # 导入所有模型以确保它们被注册到AgentBase
            from app.models.user import User, UserSession, UserPreference, UserActivity
            from app.models.request import UserRequest, RequestHistory, ChatMessage, AIServiceLog
            from app.models.config import SystemConfig, UserConfig
            from app.models.metrics import PerformanceMetrics, PainReliefMetrics, SystemHealthMetrics
            from app.models.workflow import WorkflowTemplate, WorkflowNode, WorkflowInstanceDB
            from app.models.mcp_server import MCPServerConfig

            # 使用AgentBase的metadata创建所有表（与server.py完全隔离）
            AgentBase.metadata.create_all(bind=self.engine)
            logger.info("✅ Agent系统数据库表创建成功（使用独立metadata）")
            return True

        except Exception as e:
            logger.error(f"❌ 创建Agent数据库表失败: {e}")
            return False

    async def drop_tables(self):
        """删除所有数据表（Agent系统专用）"""
        try:
            AgentBase.metadata.drop_all(bind=self.engine)
            logger.info("✅ Agent系统数据库表删除成功")
            return True

        except Exception as e:
            logger.error(f"❌ 删除Agent数据库表失败: {e}")
            return False

    def health_check(self) -> Dict[str, Any]:
        """数据库健康检查"""
        try:
            with self.get_session() as session:
                # 执行简单查询测试连接
                session.execute(text("SELECT 1"))

                return {
                    "status": "healthy",
                    "database_url": DATABASE_URL.split("@")[0] + "@***",  # 隐藏密码
                    "connected": True
                }

        except Exception as e:
            logger.error(f"数据库健康检查失败: {e}")
            return {
                "status": "unhealthy",
                "database_url": DATABASE_URL.split("@")[0] + "@***",
                "connected": False,
                "error": str(e)
            }

    def get_database_info(self) -> Dict[str, Any]:
        """获取数据库信息"""
        try:
            with self.get_session() as session:
                if "postgresql" in DATABASE_URL:
                    # PostgreSQL 查询
                    result = session.execute(text("""
                        SELECT tablename FROM pg_tables
                        WHERE schemaname = 'public'
                    """))
                else:
                    # SQLite 查询
                    result = session.execute(text("""
                        SELECT name FROM sqlite_master
                        WHERE type='table' AND name NOT LIKE 'sqlite_%'
                    """))

                tables = [row[0] for row in result.fetchall()]

                return {
                    "database_type": "postgresql" if "postgresql" in DATABASE_URL else "sqlite",
                    "tables_count": len(tables),
                    "tables": tables,
                    "database_url": DATABASE_URL.split("@")[0] + "@***"
                }

        except Exception as e:
            logger.error(f"获取数据库信息失败: {e}")
            return {
                "database_type": "postgresql" if "postgresql" in DATABASE_URL else "sqlite",
                "error": str(e)
            }


# 全局数据库管理器实例
db_manager = DatabaseManager()


# 数据库依赖注入函数
def get_db():
    """获取数据库会话的依赖注入函数"""
    session = db_manager.get_session()
    try:
        yield session
    finally:
        session.close()


# 数据库初始化函数
async def init_database():
    """初始化数据库"""
    logger.info("🗄️ 初始化数据库...")

    success = await db_manager.create_tables()
    if success:
        logger.info("✅ 数据库初始化完成")
    else:
        logger.error("❌ 数据库初始化失败")

    return success


# 数据库操作辅助类
class DatabaseHelper:
    """数据库操作辅助类"""

    @staticmethod
    def execute_query(query: str, params: Optional[tuple] = None) -> list:
        """执行查询语句"""
        try:
            with db_manager.get_session() as session:
                result = session.execute(query, params or ())
                return result.fetchall()
        except Exception as e:
            logger.error(f"执行查询失败: {e}")
            return []

    @staticmethod
    def execute_insert(table: str, data: dict) -> bool:
        """执行插入操作"""
        try:
            with db_manager.get_session() as session:
                # 构建插入语句
                columns = ", ".join(data.keys())
                placeholders = ", ".join(["?"] * len(data))
                query = f"INSERT INTO {table} ({columns}) VALUES ({placeholders})"

                session.execute(query, tuple(data.values()))
                session.commit()
                return True
        except Exception as e:
            logger.error(f"执行插入失败: {e}")
            return False

    @staticmethod
    def execute_update(table: str, data: dict, where_clause: str, where_params: tuple) -> bool:
        """执行更新操作"""
        try:
            with db_manager.get_session() as session:
                # 构建更新语句
                set_clause = ", ".join([f"{k} = ?" for k in data.keys()])
                query = f"UPDATE {table} SET {set_clause} WHERE {where_clause}"

                params = tuple(data.values()) + where_params
                session.execute(query, params)
                session.commit()
                return True
        except Exception as e:
            logger.error(f"执行更新失败: {e}")
            return False

    @staticmethod
    def execute_delete(table: str, where_clause: str, where_params: tuple) -> bool:
        """执行删除操作"""
        try:
            with db_manager.get_session() as session:
                query = f"DELETE FROM {table} WHERE {where_clause}"
                session.execute(query, where_params)
                session.commit()
                return True
        except Exception as e:
            logger.error(f"执行删除失败: {e}")
            return False