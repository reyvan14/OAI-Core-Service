"""
LLM服务层 - 统一的大语言模型接口
支持智谱API，具备模型路由、重试机制和性能监控
"""

import logging
import asyncio
import json
import time
import jwt
from typing import Dict, Any, List, Optional, Union
from dataclasses import dataclass
from enum import Enum
import httpx
from datetime import datetime, timedelta

from app.utils.metrics import performance_metrics, monitor_agent_performance
from app.utils.helpers import safe_serialize, safe_deserialize, generate_request_id

logger = logging.getLogger(__name__)


class CircuitBreaker:
    """熔断器，用于防止级联故障"""

    def __init__(self, failure_threshold: int = 5, timeout: int = 60):
        self.failure_threshold = failure_threshold
        self.timeout = timeout
        self.failure_count = 0
        self.last_failure_time = None
        self.state = "CLOSED"  # CLOSED, OPEN, HALF_OPEN

    def __call__(self, func):
        """装饰器实现"""
        async def wrapper(*args, **kwargs):
            if self.state == "OPEN":
                if time.time() - self.last_failure_time > self.timeout:
                    self.state = "HALF_OPEN"
                    logger.info("熔断器进入半开状态")
                else:
                    raise Exception("服务暂时不可用（熔断器开启）")

            try:
                result = await func(*args, **kwargs)
                if self.state == "HALF_OPEN":
                    self.state = "CLOSED"
                    self.failure_count = 0
                    logger.info("熔断器恢复正常状态")
                return result
            except Exception as e:
                self.failure_count += 1
                self.last_failure_time = time.time()

                if self.failure_count >= self.failure_threshold:
                    self.state = "OPEN"
                    logger.error(f"熔断器开启，失败次数: {self.failure_count}")

                raise e

        return wrapper


class LLMProvider(Enum):
    """LLM提供商枚举"""
    ZHIPU = "zhipu"
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    LOCAL = "local"


@dataclass
class LLMRequest:
    """LLM请求数据结构"""
    messages: List[Dict[str, str]]
    model: str = "glm-4"
    temperature: float = 0.7
    max_tokens: Optional[int] = None
    stream: bool = False
    top_p: float = 0.9
    request_id: str = ""
    provider: LLMProvider = LLMProvider.ZHIPU


@dataclass
class LLMResponse:
    """LLM响应数据结构"""
    content: str
    usage: Dict[str, int]
    model: str
    request_id: str
    response_time: float
    success: bool
    error: Optional[str] = None
    finish_reason: Optional[str] = None


class LLMService:
    """统一LLM服务接口"""

    def __init__(self):
        self.api_key = None
        self.base_url = "https://open.bigmodel.cn/api/paas/v4/chat/completions"  # 直接设置默认URL
        self.provider = LLMProvider.ZHIPU
        self.default_model = "glm-4"
        self.timeout = 60
        self.max_retries = 3
        self.request_history = []
        self.is_mock_mode = False
        self.rate_limiter = {
            "tokens_per_minute": 120000,
            "requests_per_minute": 500,
            "current_tokens": 0,
            "current_requests": 0,
            "reset_time": datetime.now() + timedelta(minutes=1)
        }
        # 添加熔断器
        self.circuit_breaker = CircuitBreaker(failure_threshold=5, timeout=60)
        # 添加备用响应缓存
        self.fallback_cache = {}

    def _generate_token(self) -> str:
        """生成智谱AI JWT Token"""
        try:
            # 安全检查：确保api_key存在
            if not self.api_key:
                logger.error("API Key未设置")
                return ""

            api_key_parts = self.api_key.split(".")
            if len(api_key_parts) != 2:
                return self.api_key

            api_key_id, api_key_secret = api_key_parts

            # 边界检查：确保key部分不为空
            if not api_key_id or not api_key_secret:
                logger.warning("API Key格式无效")
                return self.api_key

            payload = {
                "api_key": api_key_id,
                "exp": int(time.time()) + 3600,
                "timestamp": int(time.time() * 1000)
            }

            token = jwt.encode(
                payload,
                api_key_secret,
                algorithm="HS256",
                headers={"alg": "HS256", "sign_type": "SIGN"}
            )

            # 确保token是字符串
            if isinstance(token, bytes):
                token = token.decode('utf-8')

            return token
        except Exception as e:
            logger.warning(f"Token生成失败: {e}, 使用原始API Key")
            return self.api_key

    async def initialize(self) -> None:
        """初始化LLM服务"""
        from app.core.config import settings

        # 配置智谱API
        api_key = settings.ZHIPU_API_KEY if settings.ZHIPU_API_KEY else None

        if not api_key:
            logger.warning("ZHIPU_API_KEY未设置，自动切换到 Mock 模式 (仅供演示)")
            self.is_mock_mode = True
            return

        self.is_mock_mode = False
        self.api_key = api_key
        self.base_url = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
        self.provider = LLMProvider.ZHIPU

        logger.info("LLM服务初始化完成")

    @monitor_agent_performance("llm_service", "generate")
    async def generate(self, prompt: str, model: Optional[str] = None, temperature: float = 0.7, **kwargs) -> LLMResponse:
        """生成文本的简化接口"""
        messages = [{"role": "user", "content": prompt}]
        return await self.chat_completion(messages, model or self.default_model, temperature, **kwargs)

    @monitor_agent_performance("llm_service", "chat_completion")
    async def chat_completion(self, messages: List[Dict[str, str]], model: Optional[str] = None,
                           temperature: float = 0.7, max_tokens: Optional[int] = None,
                           stream: bool = False, **kwargs) -> LLMResponse:
        """聊天补全接口"""
        request_id = generate_request_id()
        start_time = time.time()

        try:
            # 检查速率限制
            await self._check_rate_limit()

            # 构建请求
            request = LLMRequest(
                messages=messages,
                model=model or self.default_model,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=stream,
                request_id=request_id,
                **kwargs
            )

            # 执行请求
            response = await self._execute_request(request)

            # 记录性能指标
            response_time = time.time() - start_time
            performance_metrics.record_request_time("llm_request", response_time * 1000, response.success)

            return response

        except Exception as e:
            response_time = time.time() - start_time
            performance_metrics.record_request_time("llm_request", response_time * 1000, False)

            logger.error(f"LLM请求失败 {request_id}: {e}")
            return LLMResponse(
                content="",
                usage={},
                model=model or self.default_model,
                request_id=request_id,
                response_time=response_time,
                success=False,
                error=str(e)
            )

    async def _check_rate_limit(self) -> None:
        """检查速率限制"""
        now = datetime.now()

        # 每分钟重置
        if now >= self.rate_limiter["reset_time"]:
            self.rate_limiter["current_tokens"] = 0
            self.rate_limiter["current_requests"] = 0
            self.rate_limiter["reset_time"] = now + timedelta(minutes=1)

        # 检查是否超出限制
        if self.rate_limiter["current_requests"] >= self.rate_limiter["requests_per_minute"]:
            wait_time = (self.rate_limiter["reset_time"] - now).total_seconds()
            if wait_time > 0:
                logger.warning(f"达到速率限制，等待 {wait_time:.1f} 秒")
                await asyncio.sleep(wait_time)

    @CircuitBreaker(failure_threshold=5, timeout=60)
    async def _execute_request(self, request: LLMRequest, retry_count: int = 0) -> LLMResponse:
        """执行LLM请求"""

        # 检查是否为mock模式
        if self.is_mock_mode:
            logger.info("使用Mock模式响应LLM请求")
            return await self._mock_response(request)

        # 生成JWT Token
        token = self._generate_token()

        if not token:
            logger.error("Token生成失败")
            raise ValueError("Token生成失败")

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

        # 构建请求数据
        payload = {
            "model": request.model,
            "messages": request.messages,
            "temperature": request.temperature,
            "top_p": request.top_p,
            "stream": request.stream
        }

        if request.max_tokens:
            payload["max_tokens"] = request.max_tokens

        start_time = time.time()

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    self.base_url,
                    headers=headers,
                    json=payload
                )

            response_time = time.time() - start_time

            # 更新速率限制计数
            self.rate_limiter["current_requests"] += 1
            if response.status_code == 200:
                response_data = response.json()
                self.rate_limiter["current_tokens"] += response_data.get("usage", {}).get("total_tokens", 0)

            # 处理响应
            return await self._process_response(response, request, response_time)

        except httpx.TimeoutException:
            error_msg = f"请求超时（{self.timeout}秒）"
            if retry_count < self.max_retries:
                logger.warning(f"请求超时，重试 {retry_count + 1}/{self.max_retries}")
                await asyncio.sleep(2 ** retry_count)  # 指数退避
                return await self._execute_request(request, retry_count + 1)

            return LLMResponse(
                content="",
                usage={},
                model=request.model,
                request_id=request.request_id,
                response_time=response_time,
                success=False,
                error=error_msg
            )

        except Exception as e:
            logger.error(f"LLM请求异常: {e}")
            return LLMResponse(
                content="",
                usage={},
                model=request.model,
                request_id=request.request_id,
                response_time=time.time() - start_time,
                success=False,
                error=str(e)
            )

    async def _process_response(self, http_response: httpx.Response, request: LLMRequest, response_time: float) -> LLMResponse:
        """处理HTTP响应"""
        try:
            if http_response.status_code == 200:
                response_data = http_response.json()

                # 智谱API响应格式
                if "choices" in response_data and len(response_data["choices"]) > 0:
                    choice = response_data["choices"][0]
                    content = choice.get("message", {}).get("content", "")
                    finish_reason = choice.get("finish_reason")
                else:
                    content = ""
                    finish_reason = None

                usage = response_data.get("usage", {})

                # 记录请求历史
                self.request_history.append({
                    "request_id": request.request_id,
                    "model": request.model,
                    "input_tokens": usage.get("prompt_tokens", 0),
                    "output_tokens": usage.get("completion_tokens", 0),
                    "total_tokens": usage.get("total_tokens", 0),
                    "response_time": response_time,
                    "timestamp": datetime.now().isoformat(),
                    "success": True
                })

                # 限制历史记录数量
                if len(self.request_history) > 1000:
                    self.request_history = self.request_history[-500:]

                return LLMResponse(
                    content=content,
                    usage=usage,
                    model=response_data.get("model", request.model),
                    request_id=request.request_id,
                    response_time=response_time,
                    success=True,
                    finish_reason=finish_reason
                )

            else:
                # 处理错误响应
                error_data = {}
                try:
                    error_data = http_response.json()
                except:
                    pass

                error_message = error_data.get("error", {}).get("message", f"HTTP {http_response.status_code}")

                logger.error(f"LLM API错误: {http_response.status_code} - {error_message}")

                return LLMResponse(
                    content="",
                    usage={},
                    model=request.model,
                    request_id=request.request_id,
                    response_time=response_time,
                    success=False,
                    error=f"API错误: {error_message}"
                )

        except Exception as e:
            logger.error(f"处理响应时发生错误: {e}")
            return LLMResponse(
                content="",
                usage={},
                model=request.model,
                request_id=request.request_id,
                response_time=response_time,
                success=False,
                error=f"响应处理错误: {str(e)}"
            )

    async def get_model_info(self, model: str = None) -> Dict[str, Any]:
        """获取模型信息"""
        model = model or self.default_model

        # 基于模型配置返回信息
        model_configs = {
            "glm-4": {
                "name": "GLM-4",
                "description": "智谱AI第四代大语言模型",
                "max_tokens": 8192,
                "supports_streaming": True,
                "supports_function_calling": True,
                "provider": "zhipu"
            },
            "glm-3-turbo": {
                "name": "GLM-3-Turbo",
                "description": "智谱AI第三代大语言模型",
                "max_tokens": 4096,
                "supports_streaming": True,
                "supports_function_calling": True,
                "provider": "zhipu"
            }
        }

        return model_configs.get(model, {
            "name": model,
            "description": "未知模型",
            "max_tokens": 4096,
            "supports_streaming": True,
            "supports_function_calling": False,
            "provider": "unknown"
        })

    def get_usage_statistics(self) -> Dict[str, Any]:
        """获取使用统计"""
        if not self.request_history:
            return {
                "total_requests": 0,
                "total_tokens": 0,
                "average_response_time": 0,
                "success_rate": 1.0,
                "daily_usage": {}
            }

        # 计算总体统计
        total_requests = len(self.request_history)
        successful_requests = sum(1 for req in self.request_history if req["success"])
        total_tokens = sum(req["total_tokens"] for req in self.request_history)
        avg_response_time = sum(req["response_time"] for req in self.request_history) / total_requests
        success_rate = successful_requests / total_requests

        # 计算今日使用量
        today = datetime.now().date()
        daily_usage = {}

        for req in self.request_history:
            req_date = datetime.fromisoformat(req["timestamp"]).date()
            date_str = req_date.isoformat()

            if date_str not in daily_usage:
                daily_usage[date_str] = {
                    "requests": 0,
                    "tokens": 0,
                    "successful_requests": 0
                }

            daily_usage[date_str]["requests"] += 1
            daily_usage[date_str]["tokens"] += req["total_tokens"]
            if req["success"]:
                daily_usage[date_str]["successful_requests"] += 1

        return {
            "total_requests": total_requests,
            "total_tokens": total_tokens,
            "average_response_time": round(avg_response_time, 2),
            "success_rate": round(success_rate, 3),
            "daily_usage": daily_usage,
            "current_rate_limit": {
                "requests_per_minute": self.rate_limiter["current_requests"],
                "tokens_per_minute": self.rate_limiter["current_tokens"],
                "reset_in_seconds": max(0, (self.rate_limiter["reset_time"] - datetime.now()).total_seconds())
            }
        }

    async def health_check(self) -> Dict[str, Any]:
        """健康检查"""
        try:
            # 发送简单的测试请求
            test_response = await self.generate("你好", model=self.default_model)

            return {
                "status": "healthy" if test_response.success else "unhealthy",
                "provider": self.provider.value,
                "model": self.default_model,
                "last_check": datetime.now().isoformat(),
                "api_accessible": test_response.success,
                "response_time": test_response.response_time,
                "error": test_response.error if not test_response.success else None
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "provider": self.provider.value,
                "model": self.default_model,
                "last_check": datetime.now().isoformat(),
                "api_accessible": False,
                "error": str(e)
            }

    async def load_system_prompt(self) -> None:
        """
        加载系统提示词
        初始化时加载预设的系统提示词模板
        """
        try:
            # 这里可以加载预设的系统提示词
            system_prompt = """
你是一个专业的企业办公自动化助手，专门帮助用户解决传统OA系统的痛点：

**核心能力：**
1. **智能表格填写** - 自动识别表格类型，智能填写，减少错误率
2. **审批流程优化** - 智能分析审批请求，提供决策建议
3. **信息快速检索** - 快速定位所需信息，解决信息孤岛问题
4. **操作指导** - 提供操作指导，减少新手学习成本
5. **合规检查** - 自动检查业务合规性，降低风险
6. **持续学习** - 从用户交互中学习，不断优化服务质量

**服务原则：**
- 以用户需求为中心，专注解决实际问题
- 提供准确、高效、安全的服务
- 保护用户隐私和数据安全
- 持续学习和改进

**痛点解决导向：**
- 识别用户遇到的具体痛点
- 提供针对性的解决方案
- 量化解决方案的效果
- 不断优化用户体验

请以专业、友好的态度为用户提供服务。
            """

            # 存储系统提示词
            self.system_prompt = system_prompt.strip()
            logger.info("系统提示词加载成功")

        except Exception as e:
            logger.error(f"加载系统提示词失败: {e}")
            # 设置默认提示词
            self.system_prompt = "你是一个专业的企业办公自动化助手。"

    async def _mock_response(self, request: LLMRequest) -> LLMResponse:
        """生成Mock响应"""
        # 模拟网络延迟
        await asyncio.sleep(0.1)

        # 分析用户消息并生成合适的响应
        user_message = ""
        if request.messages:
            user_message = request.messages[-1].get("content", "")

        # 根据用户消息生成智能响应
        if "报销" in user_message or "expense" in user_message.lower():
            mock_content = """
关于差旅报销政策，我为您说明如下：

**差旅报销标准：**
- 交通费：飞机经济舱/高铁二等座，实报实销
- 住宿费：一线城市800元/晚，二线城市600元/晚
- 餐补：150元/天
- 市内交通：50元/天

**报销流程：**
1. 填写差旅报销申请单
2. 附上相关票据（发票、行程单等）
3. 提交部门主管审批
4. 财务部门审核通过后打款

**注意事项：**
- 所有费用需提供合规发票
- 出差申请需提前提交并获得批准
- 报销需在出差结束后10个工作日内完成

希望这能帮到您！如果需要填写报销申请，我可以协助您。
            """.strip()
        elif "请假" in user_message or "leave" in user_message.lower():
            mock_content = """
关于请假政策，我为您说明如下：

**请假类型：**
- 年假：根据工龄享受5-15天
- 病假：提供医疗证明，享受带薪病假
- 事假：需提前申请，不超过3天/次
- 婚假/产假：按国家规定执行

**请假流程：**
1. 提交请假申请单
2. 注明请假类型、时间、事由
3. 部门主管审批
4. 人事部门备案

**注意事项：**
- 突急情况可事后补办手续
- 请假期间需做好工作交接
- 年假需提前一周申请

如需要申请请假，我可以帮助您填写申请单。
            """.strip()
        elif "审批" in user_message or "approval" in user_message.lower():
            mock_content = """
关于审批流程，我为您说明如下：

**审批时效：**
- 日常事务：1-2个工作日内完成
- 重要事项：3-5个工作日内完成
- 紧急事项：2小时内完成

**审批节点：**
1. 直接主管初审（1天）
2. 部门负责人复审（1-2天）
3. 相关部门会签（1-2天）
4. 最终审批（1天）

**加急处理：**
- 标记"紧急"的申请可加快处理
- 事前沟通可获得更快响应

**查询进度：**
- 系统自动推送审批状态
- 可随时查询当前审批进度
- 超时会自动提醒相关人员

如果您有具体的审批申请需要查询，我可以帮您查看当前状态。
            """.strip()
        else:
            mock_content = f"""
您好！我是您的企业办公自动化助手。

我理解您的问题是："{user_message}"

作为您的智能助手，我可以帮助您：
- 填写各类申请表格
- 解答公司政策和流程
- 协助处理审批事务
- 提供操作指导和建议

请告诉我具体需要什么帮助，我会为您提供专业的解决方案！

我们的AI系统能够：
✓ 减少表格填写时间80%
✓ 降低错误率90%
✓ 提高审批效率60%
✓ 节省查找信息时间70%

期待为您提供更好的服务体验！
            """.strip()

        return LLMResponse(
            content=mock_content,
            usage={"prompt_tokens": len(user_message), "completion_tokens": len(mock_content), "total_tokens": len(user_message) + len(mock_content)},
            model=request.model,
            request_id=request.request_id,
            response_time=0.1,
            success=True,
            finish_reason="stop"
        )

    async def test_provider(self, config: Dict[str, Any], test_prompt: str = "Hello") -> str:
        """测试LLM提供商连接"""
        try:
            provider_type = config.get("provider_type", "openai")
            api_key = config.get("api_key")
            api_base = config.get("api_base")
            model_name = config.get("model_name", "gpt-3.5-turbo")
            timeout = config.get("timeout", 30)

            headers = {
                "Content-Type": "application/json",
            }

            # 根据不同的提供商类型设置认证头和请求体
            if provider_type == "zhipu":
                # 智谱AI使用JWT认证
                # 临时设置api_key用于token生成
                original_api_key = self.api_key
                self.api_key = api_key
                headers["Authorization"] = f"Bearer {self._generate_token()}"
                self.api_key = original_api_key
                url = api_base or "https://open.bigmodel.cn/api/paas/v4/chat/completions"
                data = {
                    "model": model_name,
                    "messages": [{"role": "user", "content": test_prompt}]
                }
            elif provider_type in ["openai", "custom"]:
                # OpenAI协议
                headers["Authorization"] = f"Bearer {api_key}"
                url = api_base or "https://api.openai.com/v1/chat/completions"
                if not url.endswith("/chat/completions"):
                    url = f"{url.rstrip('/')}/chat/completions"
                data = {
                    "model": model_name,
                    "messages": [{"role": "user", "content": test_prompt}],
                    "max_tokens": 100
                }
            elif provider_type == "azure_openai":
                # Azure OpenAI
                headers["api-key"] = api_key
                deployment_name = config.get("deployment_name", model_name)
                api_version = config.get("api_version", "2024-02-01")
                url = f"{api_base}/openai/deployments/{deployment_name}/chat/completions?api-version={api_version}"
                data = {
                    "messages": [{"role": "user", "content": test_prompt}],
                    "max_tokens": 100
                }
            elif provider_type == "anthropic":
                # Anthropic Claude
                headers["x-api-key"] = api_key
                headers["anthropic-version"] = "2023-06-01"
                url = api_base or "https://api.anthropic.com/v1/messages"
                data = {
                    "model": model_name,
                    "messages": [{"role": "user", "content": test_prompt}],
                    "max_tokens": 100
                }
            else:
                raise ValueError(f"不支持的提供商类型: {provider_type}")

            # 发送请求
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(url, json=data, headers=headers)
                response.raise_for_status()
                result = response.json()

                # 解析响应
                if provider_type == "anthropic":
                    content = result["content"][0]["text"]
                else:
                    content = result["choices"][0]["message"]["content"]

                return content

        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP错误: {e.response.status_code} - {e.response.text}")
            raise Exception(f"API调用失败: {e.response.status_code} - {e.response.text}")
        except Exception as e:
            logger.error(f"测试提供商失败: {str(e)}")
            raise

    async def shutdown(self) -> None:
        """关闭服务"""
        logger.info("LLM服务正在关闭...")

        # 保存使用统计到日志
        stats = self.get_usage_statistics()
        logger.info(f"LLM服务使用统计: {stats}")

        logger.info("LLM服务已关闭")


# 全局LLM服务实例
llm_service = LLMService()