"""
系统配置数据模型 - SQLAlchemy ORM模型
"""

from sqlalchemy import Column, Integer, String, DateTime, Boolean, Float, Text
from sqlalchemy.sql import func
import uuid

from app.database import Base


class SystemConfig(Base):
    """系统配置表（Agent系统专用）"""
    __tablename__ = "agent_system_configs"  # 添加agent_前缀

    id = Column(Integer, primary_key=True, index=True)
    config_key = Column(String(100), unique=True, index=True, nullable=False)
    config_value = Column(Text)
    config_type = Column(String(20), default="string")  # string, int, float, bool, json
    description = Column(Text)
    is_public = Column(Boolean, default=False)  # 是否可以被前端访问
    category = Column(String(50))  # 配置分类

    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


class UserConfig(Base):
    """用户配置表（Agent系统专用）"""
    __tablename__ = "agent_user_configs"  # 添加agent_前缀

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String(64), nullable=False, index=True)
    config_key = Column(String(100), nullable=False)
    config_value = Column(Text)
    config_type = Column(String(20), default="string")

    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())