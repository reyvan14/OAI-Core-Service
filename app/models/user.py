"""
用户相关数据模型 - SQLAlchemy ORM模型
"""

from sqlalchemy import Column, Integer, String, DateTime, Boolean, Float, Text, JSON
from sqlalchemy.sql import func
from datetime import datetime
import uuid

from app.database import Base


class User(Base):
    """用户表（Agent系统专用）"""
    __tablename__ = "agent_users"  # 添加agent_前缀避免与server.py的users表冲突

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String(64), unique=True, index=True, default=lambda: str(uuid.uuid4()))
    username = Column(String(50), unique=True, index=True, nullable=False)
    email = Column(String(100), unique=True, index=True, nullable=False)
    full_name = Column(String(100), nullable=False)
    role = Column(String(20), default="employee")  # employee, manager, director, admin, guest
    department = Column(String(100))
    position = Column(String(100))
    phone = Column(String(20))
    status = Column(String(20), default="active")  # active, inactive, suspended, deleted

    # 权限相关
    approval_limit = Column(Float, default=1000.0)
    can_approve = Column(Boolean, default=False)
    can_access_analytics = Column(Boolean, default=False)
    can_manage_users = Column(Boolean, default=False)

    # 登录相关
    last_login_at = Column(DateTime)
    login_count = Column(Integer, default=0)

    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


class UserSession(Base):
    """用户会话表（Agent系统专用）"""
    __tablename__ = "agent_user_sessions"  # 添加agent_前缀

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String(128), unique=True, index=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(64), nullable=False, index=True)
    token = Column(String(255), unique=True, index=True)
    ip_address = Column(String(45))
    user_agent = Column(Text)
    is_active = Column(Boolean, default=True)
    expires_at = Column(DateTime)

    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


class UserPreference(Base):
    """用户偏好设置表（Agent系统专用）"""
    __tablename__ = "agent_user_preferences"  # 添加agent_前缀

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String(64), unique=True, index=True)

    # 界面偏好
    theme = Column(String(20), default="light")  # light, dark
    language = Column(String(10), default="zh-CN")
    timezone = Column(String(50), default="Asia/Shanghai")

    # 通知偏好
    email_notifications = Column(Boolean, default=True)
    push_notifications = Column(Boolean, default=True)
    auto_approval_threshold = Column(Float, default=500.0)

    # AI服务偏好
    preferred_ai_model = Column(String(50), default="glm-4")
    ai_response_language = Column(String(10), default="zh")

    # 其他设置
    preferences_json = Column(Text)  # 存储额外的偏好设置

    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


class UserActivity(Base):
    """用户活动记录表（Agent系统专用）"""
    __tablename__ = "agent_user_activities"  # 添加agent_前缀

    id = Column(Integer, primary_key=True, index=True)
    activity_id = Column(String(64), unique=True, index=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(64), nullable=False, index=True)
    session_id = Column(String(128), index=True)

    activity_type = Column(String(50), nullable=False)  # login, logout, chat, form_submit, approval, etc.
    activity_description = Column(Text)
    activity_metadata = Column(JSON)  # JSON格式的额外信息

    ip_address = Column(String(45))
    user_agent = Column(Text)

    created_at = Column(DateTime, default=func.now())