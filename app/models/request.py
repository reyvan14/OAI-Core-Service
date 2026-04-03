"""
请求数据模型 - SQLAlchemy ORM模型
"""

from sqlalchemy import Column, Integer, String, DateTime, Text, JSON, Float, Boolean, Enum
from sqlalchemy.sql import func
from datetime import datetime
import uuid
import enum

from app.database import Base


class UserRole(enum.Enum):
    """用户角色枚举"""
    employee = "employee"
    manager = "manager"
    director = "director"
    admin = "admin"
    guest = "guest"


class RequestStatus(enum.Enum):
    """请求状态枚举"""
    success = "success"
    error = "error"
    pending = "pending"


class ActionType(enum.Enum):
    """操作类型枚举"""
    chat = "chat"
    form_submit = "form_submit"
    approval = "approval"
    file_upload = "file_upload"
    data_export = "data_export"


class UserRequest(Base):
    """用户请求记录表（Agent系统专用）"""
    __tablename__ = "agent_user_requests"  # 添加agent_前缀

    id = Column(Integer, primary_key=True, index=True)
    request_id = Column(String(64), unique=True, index=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(64), nullable=False, index=True)  # 增加长度以匹配UUID
    session_id = Column(String(128), nullable=False, index=True)  # 增加长度
    user_role = Column(Enum(UserRole), nullable=False)
    department = Column(String(100))
    message = Column(Text, nullable=False)
    response = Column(Text)
    request_metadata = Column(JSON)
    client_ip = Column(String(45))
    device_info = Column(JSON)
    processing_time = Column(Float)
    success = Column(Boolean, default=True)
    error_message = Column(Text)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


class RequestHistory(Base):
    """请求历史记录表（Agent系统专用）"""
    __tablename__ = "agent_request_history"  # 添加agent_前缀

    id = Column(Integer, primary_key=True, index=True)
    request_id = Column(String(64), index=True)
    user_id = Column(String(64), nullable=False, index=True)  # 增加长度
    session_id = Column(String(128), nullable=False, index=True)  # 增加长度
    action_type = Column(Enum(ActionType), nullable=False)
    request_data = Column(JSON)
    response_data = Column(JSON)
    status = Column(Enum(RequestStatus), default=RequestStatus.success)
    processing_time = Column(Float)
    error_message = Column(Text)
    created_at = Column(DateTime, default=func.now())


class ChatMessage(Base):
    """聊天消息记录表（Agent系统专用）"""
    __tablename__ = "agent_chat_messages"  # 添加agent_前缀，避免与server.py的chat_messages冲突

    id = Column(Integer, primary_key=True, index=True)
    message_id = Column(String(64), unique=True, index=True, default=lambda: str(uuid.uuid4()))
    session_id = Column(String(64), nullable=False, index=True)
    user_id = Column(String(50), nullable=False, index=True)
    message_type = Column(String(20), default="user")  # user, assistant, system
    content = Column(Text, nullable=False)
    request_metadata = Column(JSON)
    ai_model_used = Column(String(50))
    tokens_used = Column(Integer)
    processing_time = Column(Float)
    created_at = Column(DateTime, default=func.now())


class AIServiceLog(Base):
    """AI服务调用日志表（Agent系统专用）"""
    __tablename__ = "agent_ai_service_logs"  # 添加agent_前缀

    id = Column(Integer, primary_key=True, index=True)
    log_id = Column(String(64), unique=True, index=True, default=lambda: str(uuid.uuid4()))
    service_type = Column(String(50), nullable=False)  # decision_analysis, data_extraction, prediction
    request_id = Column(String(64), index=True)
    user_id = Column(String(50), nullable=False, index=True)
    request_data = Column(JSON)
    response_data = Column(JSON)
    ai_model = Column(String(50))
    api_endpoint = Column(String(200))
    confidence_score = Column(Float)
    processing_time = Column(Float)
    success = Column(Boolean, default=True)
    error_message = Column(Text)
    created_at = Column(DateTime, default=func.now())