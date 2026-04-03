"""
MCP服务器配置数据模型
"""
from datetime import datetime
from typing import Dict, Any, Optional
from sqlalchemy import Column, String, Integer, DateTime, Text, Boolean, JSON
from app.database import AgentBase


class MCPServerConfig(AgentBase):
    """MCP服务器配置模型"""
    __tablename__ = "mcp_servers"

    id = Column(String(50), primary_key=True)
    name = Column(String(100), nullable=False, comment="服务器名称")
    description = Column(Text, comment="服务器描述")
    server_type = Column(String(20), nullable=False, default="stdio", comment="服务器类型: stdio|sse")

    # stdio类型配置
    command = Column(String(500), comment="启动命令（stdio类型）")
    args = Column(JSON, comment="命令参数列表（stdio类型）")
    env_vars = Column(JSON, comment="环境变量（stdio类型）")

    # sse类型配置
    url = Column(String(500), comment="服务器URL（sse类型）")

    # 通用配置
    enabled = Column(Boolean, default=True, comment="是否启用")
    icon = Column(String(100), comment="图标")
    category = Column(String(50), comment="分类")
    tags = Column(JSON, comment="标签")

    # 连接状态
    status = Column(String(20), default="inactive", comment="状态: active|inactive|error")
    last_connected = Column(DateTime, comment="最后连接时间")
    error_message = Column(Text, comment="错误信息")

    # 工具信息（缓存）
    available_tools = Column(JSON, comment="可用工具列表")
    available_resources = Column(JSON, comment="可用资源列表")

    # 元数据
    created_at = Column(DateTime, default=datetime.now, comment="创建时间")
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, comment="更新时间")
    created_by = Column(String(50), comment="创建人")

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "server_type": self.server_type,
            "command": self.command,
            "args": self.args,
            "env_vars": self.env_vars,
            "url": self.url,
            "enabled": self.enabled,
            "icon": self.icon,
            "category": self.category,
            "tags": self.tags,
            "status": self.status,
            "last_connected": self.last_connected.isoformat() if self.last_connected else None,
            "error_message": self.error_message,
            "available_tools": self.available_tools,
            "available_resources": self.available_resources,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "created_by": self.created_by
        }
