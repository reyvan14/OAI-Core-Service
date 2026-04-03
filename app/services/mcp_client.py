"""
MCP客户端服务
负责启动、管理和调用MCP服务器
"""
import asyncio
import json
import logging
import subprocess
from typing import Dict, List, Any, Optional
from datetime import datetime
from sqlalchemy.orm import Session

from app.models.mcp_server import MCPServerConfig
from app.database import SessionLocal

logger = logging.getLogger(__name__)


class MCPServerProcess:
    """单个MCP服务器进程管理"""

    def __init__(self, config: MCPServerConfig):
        self.config = config
        self.process: Optional[subprocess.Popen] = None
        self.tools: List[Dict[str, Any]] = []
        self.resources: List[Dict[str, Any]] = []
        self.last_error: Optional[str] = None

    async def start(self) -> bool:
        """启动MCP服务器进程"""
        if self.config.server_type != "stdio":
            logger.warning(f"暂不支持 {self.config.server_type} 类型的MCP服务器")
            return False

        try:
            # 构建启动命令
            cmd = [self.config.command] + (self.config.args or [])
            env = dict(self.config.env_vars or {}) if self.config.env_vars else None

            # 启动进程
            self.process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                text=True,
                bufsize=1
            )

            # 发送初始化请求
            init_request = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {
                        "name": "ai-oa-system",
                        "version": "1.0.0"
                    }
                }
            }

            self.process.stdin.write(json.dumps(init_request) + "\n")
            self.process.stdin.flush()

            # 读取初始化响应
            response_line = self.process.stdout.readline()
            if response_line:
                response = json.loads(response_line)
                if "result" in response:
                    # 获取服务器能力
                    capabilities = response["result"].get("capabilities", {})
                    logger.info(f"MCP服务器 {self.config.name} 启动成功")

                    # 发送初始化完成通知
                    initialized_notification = {
                        "jsonrpc": "2.0",
                        "method": "notifications/initialized"
                    }
                    self.process.stdin.write(json.dumps(initialized_notification) + "\n")
                    self.process.stdin.flush()

                    # 获取工具列表
                    await self._load_tools()

                    return True

            return False

        except Exception as e:
            logger.error(f"启动MCP服务器失败 {self.config.name}: {e}")
            self.last_error = str(e)
            return False

    async def _load_tools(self):
        """加载MCP服务器的工具列表"""
        try:
            tools_request = {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/list"
            }

            self.process.stdin.write(json.dumps(tools_request) + "\n")
            self.process.stdin.flush()

            response_line = self.process.stdout.readline()
            if response_line:
                response = json.loads(response_line)
                if "result" in response:
                    self.tools = response["result"].get("tools", [])
                    logger.info(f"加载了 {len(self.tools)} 个工具")

        except Exception as e:
            logger.error(f"加载工具列表失败: {e}")

    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """调用MCP工具"""
        try:
            tool_call_request = {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": tool_name,
                    "arguments": arguments
                }
            }

            self.process.stdin.write(json.dumps(tool_call_request) + "\n")
            self.process.stdin.flush()

            response_line = self.process.stdout.readline()
            if response_line:
                response = json.loads(response_line)
                if "result" in response:
                    return {
                        "success": True,
                        "result": response["result"]
                    }
                elif "error" in response:
                    return {
                        "success": False,
                        "error": response["error"].get("message", "Unknown error")
                    }

        except Exception as e:
            logger.error(f"调用工具失败 {tool_name}: {e}")
            return {
                "success": False,
                "error": str(e)
            }

        return {
            "success": False,
            "error": "No response from MCP server"
        }

    async def stop(self):
        """停止MCP服务器进程"""
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=5)
            except:
                self.process.kill()
            finally:
                self.process = None

    def is_running(self) -> bool:
        """检查进程是否运行中"""
        return self.process is not None and self.process.poll() is None


class MCPClientService:
    """MCP客户端服务 - 管理所有MCP服务器"""

    def __init__(self):
        self.servers: Dict[str, MCPServerProcess] = {}
        self._lock = asyncio.Lock()

    async def start_enabled_servers(self):
        """启动所有已启用的MCP服务器"""
        db = SessionLocal()
        try:
            enabled_servers = db.query(MCPServerConfig).filter(
                MCPServerConfig.enabled == True
            ).all()

            for config in enabled_servers:
                await self.start_server(config)

        finally:
            db.close()

    async def start_server(self, config: MCPServerConfig) -> bool:
        """启动单个MCP服务器"""
        async with self._lock:
            if config.id in self.servers and self.servers[config.id].is_running():
                logger.info(f"MCP服务器 {config.name} 已在运行")
                return True

            server_process = MCPServerProcess(config)
            success = await server_process.start()

            if success:
                self.servers[config.id] = server_process

                # 更新数据库状态
                db = SessionLocal()
                try:
                    db_server = db.query(MCPServerConfig).filter(
                        MCPServerConfig.id == config.id
                    ).first()
                    if db_server:
                        db_server.status = "active"
                        db_server.last_connected = datetime.utcnow()
                        db_server.available_tools = server_process.tools
                        db_server.error_message = None
                        db.commit()
                finally:
                    db.close()

            return success

    async def stop_server(self, server_id: str):
        """停止MCP服务器"""
        async with self._lock:
            if server_id in self.servers:
                await self.servers[server_id].stop()
                del self.servers[server_id]

                # 更新数据库状态
                db = SessionLocal()
                try:
                    db_server = db.query(MCPServerConfig).filter(
                        MCPServerConfig.id == server_id
                    ).first()
                    if db_server:
                        db_server.status = "inactive"
                        db.commit()
                finally:
                    db.close()

    async def get_all_tools(self) -> List[Dict[str, Any]]:
        """获取所有运行中MCP服务器的工具列表"""
        all_tools = []

        for server_id, server_process in self.servers.items():
            if server_process.is_running():
                for tool in server_process.tools:
                    all_tools.append({
                        "server_id": server_id,
                        "server_name": server_process.config.name,
                        "tool": tool
                    })

        return all_tools

    async def call_tool(self, server_id: str, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """调用指定MCP服务器的工具"""
        if server_id not in self.servers:
            return {
                "success": False,
                "error": f"MCP服务器 {server_id} 未运行"
            }

        server_process = self.servers[server_id]
        if not server_process.is_running():
            return {
                "success": False,
                "error": f"MCP服务器 {server_id} 已停止"
            }

        return await server_process.call_tool(tool_name, arguments)

    async def shutdown_all(self):
        """关闭所有MCP服务器"""
        tasks = []
        for server_id in list(self.servers.keys()):
            tasks.append(self.stop_server(server_id))

        if tasks:
            await asyncio.gather(*tasks)


# 全局MCP客户端服务实例
mcp_client_service = MCPClientService()
