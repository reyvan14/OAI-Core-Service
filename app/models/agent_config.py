"""
智能体配置数据模型
支持流程助手和知识库助手的模型配置
"""

from sqlalchemy import Column, Integer, String, DateTime, Boolean, Text, Enum as SQLEnum
from sqlalchemy.sql import func
from enum import Enum

from app.database import Base


class AgentType(str, Enum):
    """智能体类型"""
    PROCESS = "process"      # 流程助手
    KNOWLEDGE = "knowledge"  # 知识库助手


class ModelSource(str, Enum):
    """模型来源"""
    LOCAL = "local"   # 本地OpenVINO
    CLOUD = "cloud"   # 云端API


class AgentConfig(Base):
    """智能体配置表"""
    __tablename__ = "agent_configs"

    id = Column(Integer, primary_key=True, index=True)

    # 智能体类型
    agent_type = Column(String(20), nullable=False, index=True)

    # 对话模型配置
    model_source = Column(String(20), nullable=False, default="cloud")
    model_name = Column(String(100), nullable=False)

    # 云端模型配置
    cloud_api_url = Column(String(500))
    cloud_api_key = Column(String(500))
    cloud_provider = Column(String(50))  # zhipu, openai, etc.

    # 本地模型配置
    local_model_path = Column(String(500))
    local_device = Column(String(20), default="CPU")  # CPU, GPU
    local_precision = Column(String(10), default="INT4")  # FP32, FP16, INT8, INT4

    # 流程助手专用：核心AI服务（流程调度必须使用）
    core_ai_url = Column(String(500))
    core_ai_key = Column(String(500))

    # 知识库助手专用
    knowledge_base_id = Column(String(64))
    embedding_model = Column(String(100))

    # 界面配置
    welcome_title = Column(String(100))  # 欢迎标题
    welcome_message = Column(Text)        # 欢迎消息
    quick_phrases = Column(Text)          # 快捷短语（JSON数组）
    system_prompt = Column(Text)          # 系统提示词

    # 状态
    is_active = Column(Boolean, default=True)
    description = Column(Text)

    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
