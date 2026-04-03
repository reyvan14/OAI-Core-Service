from __future__ import annotations

"""
Agent调度协调器 - 增强版

负责Agent的调度、协调和编排，实现多Agent的智能协作
包含完整的异常处理、任务依赖管理、性能监控和自适应优化
"""

import asyncio
import logging
import traceback
import time
from typing import Dict, List, Any, Optional, Set, Tuple
from dataclasses import dataclass, field
from enum import Enum
import json
import uuid
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor

from app.agents.form_agent import FormAgent
from app.agents.search_agent import SearchAgent
from app.agents.approve_agent import ApproveAgent
from app.agents.analytics_agent import AnalyticsAgent
from app.agents.config_agent import ConfigAgent
from app.agents.learn_agent import LearnAgent
# UserRequest延迟导入，避免metadata冲突
from app.models.metrics import PainReliefMetrics
from app.utils.metrics import performance_metrics, monitor_agent_performance
from app.utils.helpers import safe_response, generate_request_id

logger = logging.getLogger(__name__)


class UserRole(Enum):
    """用户角色枚举"""
    EMPLOYEE = "employee"
    MANAGER = "manager"
    APPROVER = "approver"
    LEADER = "leader"
    ADMIN = "admin"


class RequestType(Enum):
    """请求类型枚举"""
    FORM_PROCESSING = "form"
    SEARCH = "search"
    APPROVAL = "approval"
    ANALYTICS = "analytics"
    CONFIGURATION = "config"
    LEARNING = "learning"


@dataclass
class AgentTask:
    """Agent任务定义 - 增强版"""
    agent_name: str
    tool_name: str
    parameters: Dict[str, Any]
    dependencies: List[str] = field(default_factory=list)
    priority: int = 1
    timeout: int = 30
    retry_count: int = 0
    max_retries: int = 3
    task_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: datetime = field(default_factory=datetime.now)

    def __post_init__(self):
        if not self.task_id:
            self.task_id = str(uuid.uuid4())


@dataclass
class TaskResult:
    """任务执行结果"""
    task_id: str
    agent_name: str
    tool_name: str
    success: bool
    result: Any = None
    error: Optional[str] = None
    execution_time: float = 0.0
    retry_count: int = 0
    timestamp: datetime = field(default_factory=datetime.now)
    performance_metrics: Dict[str, Any] = field(default_factory=dict)


class TaskStatus(Enum):
    """任务状态枚举"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


class OrchestratorError(Exception):
    """Orchestrator自定义异常"""
    pass


class AgentNotAvailableError(OrchestratorError):
    """Agent不可用异常"""
    pass


class TaskExecutionError(OrchestratorError):
    """任务执行异常"""
    pass


class AgentOrchestrator:
    """Agent调度协调器 - 增强版"""

    def __init__(self, llm_service=None):
        # 性能监控 - 必须在初始化Agent之前
        self.agent_health: Dict[str, bool] = {}
        self.agent_performance: Dict[str, Dict] = {}
        self.llm_service = llm_service

        # 初始化所有Agent
        self.agents = self._initialize_agents()

        # 任务管理
        self.execution_history: List[TaskResult] = []
        self.active_tasks: Dict[str, AgentTask] = {}
        self.task_status: Dict[str, TaskStatus] = {}

        self.request_queue = asyncio.Queue()

        # 并发控制
        self.max_concurrent_tasks = 10
        self.semaphore = asyncio.Semaphore(self.max_concurrent_tasks)
        self.executor = ThreadPoolExecutor(max_workers=4)

        # 缓存和优化
        self.request_cache = {}
        self.cache_ttl = timedelta(minutes=5)

        # 监控和日志
        self.request_id = None
        self.start_time = None

    def _initialize_agents(self) -> Dict[str, Any]:
        """初始化所有Agent并进行健康检查"""
        agents = {}

        agent_classes = {
            "form_agent": FormAgent,
            "search_agent": SearchAgent,
            "approve_agent": ApproveAgent,
            "analytics_agent": AnalyticsAgent,
            "config_agent": ConfigAgent,
            "learn_agent": LearnAgent
        }

        for agent_name, agent_class in agent_classes.items():
            try:
                # Pass the LLM service to each agent if available
                if self.llm_service:
                    agents[agent_name] = agent_class(llm_service=self.llm_service)
                else:
                    agents[agent_name] = agent_class()
                self.agent_health[agent_name] = True
                self.agent_performance[agent_name] = {
                    "total_calls": 0,
                    "successful_calls": 0,
                    "average_response_time": 0.0,
                    "last_called": None,
                    "error_count": 0
                }
                logger.info(f"Agent {agent_name} 初始化成功")
            except Exception as e:
                self.agent_health[agent_name] = False
                logger.error(f"Agent {agent_name} 初始化失败: {e}")
                agents[agent_name] = None

        return agents

    async def warm_up_agents(self) -> None:
        """预热所有Agent"""
        logger.info("正在预热Agent...")
        for agent_name, agent in self.agents.items():
            try:
                await agent.warm_up()
                logger.info(f"Agent {agent_name} 预热完成")
            except Exception as e:
                logger.error(f"Agent {agent_name} 预热失败: {e}")

    @monitor_agent_performance("orchestrator", "process_request")
    async def process_request(self, user_request: UserRequest | Dict[str, Any]) -> Dict[str, Any]:
        """处理用户请求的主要入口 - 增强版

        Args:
            user_request: UserRequest对象或包含请求数据的字典
        """
        # 延迟导入UserRequest，避免metadata冲突
        from app.models.request import UserRequest as UserRequestClass

        # 如果传入的是字典，转换为UserRequest对象
        if isinstance(user_request, dict):
            user_request = UserRequestClass(
                user_id=user_request.get("user_id", "unknown"),
                message=user_request.get("message", ""),
                user_role=user_request.get("user_role", "employee"),
                department=user_request.get("department", ""),
                session_id=user_request.get("session_id")
            )

        self.request_id = generate_request_id()
        self.start_time = time.time()

        logger.info(f"开始处理请求 {self.request_id} from user {user_request.user_id}")

        try:
            # 0. 检查缓存
            cache_key = self._generate_cache_key(user_request)
            cached_result = self._get_cached_result(cache_key)
            if cached_result:
                logger.info(f"从缓存返回结果 {self.request_id}")
                return cached_result

            # 1. 请求分析和分类
            request_analysis = await self._analyze_request(user_request)

            # 2. Agent选择和任务规划
            task_plan = await self._create_task_plan(request_analysis)

            # 验证任务计划
            if not task_plan:
                raise TaskExecutionError("无法生成有效的任务执行计划")

            # 3. 任务执行和协作
            execution_results = await self._execute_task_plan_enhanced(task_plan)

            # 4. 结果整合和优化
            final_result = await self._integrate_results_enhanced(execution_results, user_request, request_analysis)

            # 5. 缓存结果
            self._cache_result(cache_key, final_result)

            # 6. 异步记录和学习（不阻塞响应）
            asyncio.create_task(self._record_interaction_async(user_request, request_analysis, final_result))

            # 记录性能指标
            total_time = time.time() - self.start_time
            performance_metrics.record_request_time("process_request", total_time * 1000, True)

            logger.info(f"请求 {self.request_id} 处理完成，耗时 {total_time:.2f}s")

            return final_result

        except Exception as e:
            # 记录错误和性能指标
            total_time = time.time() - self.start_time
            performance_metrics.record_request_time("process_request", total_time * 1000, False)

            # 详细的错误日志
            error_traceback = traceback.format_exc()
            logger.error(f"处理请求 {self.request_id} 时发生错误: {e}")
            logger.error(f"错误堆栈: {error_traceback}")

            # 返回安全的错误响应
            return safe_response(
                message=f"处理请求时遇到问题，请稍后重试",
                error_code="PROCESSING_ERROR",
                details=str(e) if logger.isEnabledFor(logging.DEBUG) else None,
                request_id=self.request_id
            )

    def _generate_cache_key(self, user_request: UserRequest) -> str:
        """生成缓存键"""
        import hashlib
        content = f"{user_request.message}_{user_request.user_role}_{user_request.department}"
        return hashlib.md5(content.encode()).hexdigest()

    def _get_cached_result(self, cache_key: str) -> Optional[Dict[str, Any]]:
        """获取缓存结果"""
        if cache_key in self.request_cache:
            cached_item = self.request_cache[cache_key]
            if datetime.now() - cached_item["timestamp"] < self.cache_ttl:
                return cached_item["result"]
            else:
                del self.request_cache[cache_key]
        return None

    def _cache_result(self, cache_key: str, result: Dict[str, Any]) -> None:
        """缓存结果"""
        self.request_cache[cache_key] = {
            "result": result,
            "timestamp": datetime.now()
        }

        # 清理过期缓存
        if len(self.request_cache) > 1000:
            current_time = datetime.now()
            expired_keys = [
                key for key, item in self.request_cache.items()
                if current_time - item["timestamp"] > self.cache_ttl
            ]
            for key in expired_keys:
                del self.request_cache[key]

    async def _analyze_request(self, request: UserRequest) -> Dict[str, Any]:
        """分析和分类用户请求"""
        analysis = {
            "user_role": self._identify_user_role(request),
            "request_type": self._classify_request_type(request),
            "pain_points": self._identify_pain_points(request),
            "intent": self._extract_intent(request),
            "context": self._build_context(request),
            "priority": self._calculate_priority(request)
        }

        logger.info(f"请求分析完成: {analysis}")
        return analysis

    def _identify_user_role(self, request: UserRequest) -> UserRole:
        """识别用户角色"""
        role_mapping = {
            "employee": UserRole.EMPLOYEE,
            "manager": UserRole.MANAGER,
            "approver": UserRole.APPROVER,
            "leader": UserRole.LEADER,
            "admin": UserRole.ADMIN
        }
        return role_mapping.get(request.user_role, UserRole.EMPLOYEE)

    def _classify_request_type(self, request: UserRequest) -> RequestType:
        """分类请求类型"""
        keywords_mapping = {
            RequestType.FORM_PROCESSING: ["报销", "申请", "表单", "填写", "提交"],
            RequestType.SEARCH: ["找", "搜索", "查询", "获取", "查看"],
            RequestType.APPROVAL: ["审批", "批准", "审核", "检查", "同意"],
            RequestType.ANALYTICS: ["分析", "报告", "数据", "趋势", "统计"],
            RequestType.CONFIGURATION: ["配置", "设置", "部署", "安装", "调整"],
            RequestType.LEARNING: ["学习", "优化", "改进", "提升", "效果"]
        }

        message = request.message.lower()
        for request_type, keywords in keywords_mapping.items():
            if any(keyword in message for keyword in keywords):
                return request_type

        return RequestType.SEARCH  # 默认搜索类型

    def _identify_pain_points(self, request: UserRequest) -> List[str]:
        """识别用户痛点"""
        pain_keywords = {
            "复杂": ["复杂", "麻烦", "困难", "繁琐"],
            "耗时": ["时间长", "慢", "等待", "效率低"],
            "错误": ["错误", "不对", "有问题", "失败"],
            "不清楚": ["不知道", "不明确", "找不到", "看不懂"]
        }

        message = request.message.lower()
        identified_pains = []

        for pain_type, keywords in pain_keywords.items():
            if any(keyword in message for keyword in keywords):
                identified_pains.append(pain_type)

        return identified_pains

    def _extract_intent(self, request: UserRequest) -> str:
        """提取用户意图"""
        # 简化版意图提取
        message = request.message.lower()

        if "报销" in message:
            return "处理报销申请"
        elif "搜索" in message or "找" in message:
            return "查找信息"
        elif "审批" in message:
            return "处理审批请求"
        elif "分析" in message or "报告" in message:
            return "生成分析报告"
        else:
            return "通用协助"

    def _build_context(self, request: UserRequest) -> Dict[str, Any]:
        """构建上下文信息"""
        return {
            "user_id": request.user_id,
            "user_role": request.user_role,
            "department": request.department,
            "timestamp": datetime.now().isoformat(),  # 使用当前时间戳
            "session_id": request.session_id
        }

    def _calculate_priority(self, request: UserRequest) -> int:
        """计算请求优先级"""
        base_priority = 5

        # 根据用户角色调整优先级
        role_priority = {
            UserRole.LEADER: 3,
            UserRole.APPROVER: 2,
            UserRole.MANAGER: 1,
            UserRole.EMPLOYEE: 0,
            UserRole.ADMIN: 2
        }

        priority = base_priority + role_priority.get(self._identify_user_role(request), 0)
        return min(priority, 10)

    async def _create_task_plan(self, analysis: Dict[str, Any]) -> List[AgentTask]:
        """创建任务执行计划"""
        tasks = []
        request_type = analysis["request_type"]
        user_role = analysis["user_role"]

        # 根据请求类型和用户角色选择Agent
        if request_type == RequestType.FORM_PROCESSING:
            tasks.append(AgentTask(
                agent_name="form_agent",
                tool_name="process_form",
                parameters={
                    "message": analysis["context"].get("message", ""),
                    "user_context": analysis["context"]
                }
            ))

        elif request_type == RequestType.SEARCH:
            tasks.append(AgentTask(
                agent_name="search_agent",
                tool_name="intelligent_search",
                parameters={
                    "query": analysis["intent"],
                    "user_context": analysis["context"]
                }
            ))

        elif request_type == RequestType.APPROVAL:
            if user_role in [UserRole.APPROVER, UserRole.MANAGER, UserRole.LEADER]:
                tasks.append(AgentTask(
                    agent_name="approve_agent",
                    tool_name="smart_approval",
                    parameters={
                        "approval_requests": [],  # 需要从上下文获取
                        "approver_context": analysis["context"]
                    }
                ))

        elif request_type == RequestType.ANALYTICS:
            if user_role in [UserRole.LEADER, UserRole.MANAGER, UserRole.ADMIN]:
                tasks.append(AgentTask(
                    agent_name="analytics_agent",
                    tool_name="generate_insights",
                    parameters={
                        "analysis_type": analysis["intent"],
                        "user_context": analysis["context"]
                    }
                ))

        # 学习Agent始终参与，用于持续优化
        tasks.append(AgentTask(
            agent_name="learn_agent",
            tool_name="record_interaction",
            parameters={
                "request_data": analysis,
                "agent_tasks": [task.agent_name for task in tasks]
            },
            dependencies=[task.agent_name for task in tasks]
        ))

        # 按优先级排序
        tasks.sort(key=lambda x: x.priority, reverse=True)

        return tasks

    async def _execute_task_plan_enhanced(self, tasks: List[AgentTask]) -> Dict[str, TaskResult]:
        """执行任务计划 - 增强版（支持并发执行和智能依赖管理）"""
        results: Dict[str, TaskResult] = {}
        task_graph = self._build_task_dependency_graph(tasks)
        execution_context: Dict[str, Any] = {}

        # 按依赖顺序分组执行
        while task_graph:
            # 找到可以执行的任务（所有依赖都已完成）
            ready_tasks = [
                task for task in task_graph
                if all(dep in results for dep in task.dependencies)
            ]

            if not ready_tasks:
                # 检查是否有循环依赖
                logger.error("检测到循环依赖或无法满足的依赖关系")
                break

            # 并发执行准备好的任务
            semaphore_tasks = []
            for task in ready_tasks:
                semaphore_tasks.append(
                    self._execute_single_task_with_semaphore(task, execution_context)
                )

            # 等待这批任务完成
            batch_results = await asyncio.gather(*semaphore_tasks, return_exceptions=True)

            # 处理结果
            for task, result in zip(ready_tasks, batch_results):
                task_key = f"{task.agent_name}_{task.tool_name}"

                if isinstance(result, Exception):
                    # 处理异常
                    task_result = TaskResult(
                        task_id=task.task_id,
                        agent_name=task.agent_name,
                        tool_name=task.tool_name,
                        success=False,
                        error=str(result),
                        retry_count=task.retry_count
                    )
                    logger.error(f"任务 {task_key} 执行失败: {result}")

                    # 尝试重试
                    if task.retry_count < task.max_retries:
                        task.retry_count += 1
                        task.timeout *= 1.5  # 增加超时时间
                        logger.info(f"重试任务 {task_key}，第 {task.retry_count} 次重试")
                        continue  # 留在下一批执行

                else:
                    task_result = result
                    if task_result.success:
                        execution_context[f"{task.agent_name}_context"] = task_result.result
                        logger.info(f"任务 {task_key} 执行成功，耗时 {task_result.execution_time:.2f}s")
                    else:
                        logger.warning(f"任务 {task_key} 执行失败: {task_result.error}")

                results[task_key] = task_result

                # 从任务图中移除已完成的任务
                if task in task_graph:
                    task_graph.remove(task)

        return results

    def _build_task_dependency_graph(self, tasks: List[AgentTask]) -> List[AgentTask]:
        """构建任务依赖图"""
        # 按优先级排序
        sorted_tasks = sorted(tasks, key=lambda x: (-x.priority, x.created_at))
        return sorted_tasks

    async def _execute_single_task_with_semaphore(self, task: AgentTask, execution_context: Dict[str, Any]) -> TaskResult:
        """使用信号量控制并发的单个任务执行"""
        async with self.semaphore:
            return await self._execute_single_task_enhanced(task, execution_context)

    @monitor_agent_performance("{task.agent_name}", "{task.tool_name}")
    async def _execute_single_task_enhanced(self, task: AgentTask, execution_context: Dict[str, Any]) -> TaskResult:
        """执行单个任务 - 增强版"""
        task_key = f"{task.agent_name}.{task.tool_name}"
        start_time = time.time()

        self.task_status[task.task_id] = TaskStatus.RUNNING
        logger.info(f"开始执行任务: {task_key} (ID: {task.task_id})")

        try:
            # 检查Agent健康状态
            if not self.agent_health.get(task.agent_name, False):
                raise AgentNotAvailableError(f"Agent {task.agent_name} 不可用")

            # 检查Agent是否存在
            agent = self.agents.get(task.agent_name)
            if not agent:
                raise AgentNotAvailableError(f"Agent {task.agent_name} 不存在")

            # 检查方法是否存在
            method = getattr(agent, task.tool_name, None)
            if not method:
                raise AttributeError(f"Agent {task.agent_name} 没有方法 {task.tool_name}")

            # 准备参数（包含上下文）
            enhanced_parameters = task.parameters.copy()
            enhanced_parameters["execution_context"] = execution_context

            # 执行任务
            logger.debug(f"调用方法: {task_key} with parameters: {enhanced_parameters}")

            result = await asyncio.wait_for(
                method(**enhanced_parameters),
                timeout=task.timeout
            )

            # 记录成功执行
            execution_time = time.time() - start_time
            self._update_agent_performance(task.agent_name, True, execution_time)

            task_result = TaskResult(
                task_id=task.task_id,
                agent_name=task.agent_name,
                tool_name=task.tool_name,
                success=True,
                result=result,
                execution_time=execution_time,
                retry_count=task.retry_count,
                performance_metrics={
                    "parameters_count": len(enhanced_parameters),
                    "context_size": len(str(execution_context)),
                    "timeout_used": execution_time / task.timeout
                }
            )

            self.task_status[task.task_id] = TaskStatus.COMPLETED
            logger.info(f"任务 {task_key} 执行成功")

            return task_result

        except asyncio.TimeoutError:
            execution_time = time.time() - start_time
            self._update_agent_performance(task.agent_name, False, execution_time)

            error_msg = f"任务执行超时（{task.timeout}秒）"
            logger.error(f"任务 {task_key} 超时")

            task_result = TaskResult(
                task_id=task.task_id,
                agent_name=task.agent_name,
                tool_name=task.tool_name,
                success=False,
                error=error_msg,
                execution_time=execution_time,
                retry_count=task.retry_count
            )

            self.task_status[task.task_id] = TaskStatus.TIMEOUT
            return task_result

        except Exception as e:
            execution_time = time.time() - start_time
            self._update_agent_performance(task.agent_name, False, execution_time)

            error_msg = str(e)
            error_traceback = traceback.format_exc()

            logger.error(f"任务 {task_key} 执行失败: {error_msg}")
            logger.debug(f"错误堆栈: {error_traceback}")

            task_result = TaskResult(
                task_id=task.task_id,
                agent_name=task.agent_name,
                tool_name=task.tool_name,
                success=False,
                error=error_msg,
                execution_time=execution_time,
                retry_count=task.retry_count
            )

            self.task_status[task.task_id] = TaskStatus.FAILED
            return task_result

    def _update_agent_performance(self, agent_name: str, success: bool, execution_time: float) -> None:
        """更新Agent性能统计"""
        if agent_name not in self.agent_performance:
            return

        perf = self.agent_performance[agent_name]
        perf["total_calls"] += 1
        perf["last_called"] = datetime.now()

        if success:
            perf["successful_calls"] += 1

            # 更新平均响应时间
            total_time = perf["average_response_time"] * (perf["successful_calls"] - 1) + execution_time
            perf["average_response_time"] = total_time / perf["successful_calls"]
        else:
            perf["error_count"] += 1

        # 记录到全局性能指标
        performance_metrics.record_agent_performance(
            agent_name=agent_name,
            tool_name="unknown",
            duration_ms=execution_time * 1000,
            success=success
        )

    async def _integrate_results_enhanced(self, execution_results: Dict[str, TaskResult], user_request: UserRequest, request_analysis: Dict[str, Any]) -> Dict[str, Any]:
        """整合Agent执行结果 - 增强版"""
        logger.info(f"开始整合 {len(execution_results)} 个任务的执行结果")

        try:
            # 1. 分析执行结果质量
            result_analysis = self._analyze_execution_results(execution_results)

            # 2. 计算执行效果指标
            effect_metrics = await self._calculate_comprehensive_metrics(execution_results, user_request, request_analysis)

            # 3. 生成智能响应
            intelligent_response = await self._generate_intelligent_response(execution_results, request_analysis, user_request)

            # 4. 提取具体的表单数据（关键修复）
            form_data = {}
            validation_result = {}
            pain_relief_metrics = {}
            fill_statistics = {}

            # 从执行结果中提取表单相关数据
            for task_key, result in execution_results.items():
                if result.success and result.result and isinstance(result.result, dict):
                    # 提取表单数据
                    if "filled_fields" in result.result:
                        form_data = result.result["filled_fields"]

                    # 提取验证结果
                    if "validation_result" in result.result:
                        validation_result_raw = result.result["validation_result"]
                        if hasattr(validation_result_raw, 'to_dict'):
                            validation_result = validation_result_raw.to_dict()
                        else:
                            validation_result = validation_result_raw

                    # 提取痛点缓解指标
                    if "pain_relief_metrics" in result.result:
                        pain_relief_data = result.result["pain_relief_metrics"]
                        if hasattr(pain_relief_data, 'to_dict'):
                            pain_relief_metrics = pain_relief_data.to_dict()
                        else:
                            pain_relief_metrics = pain_relief_data

                    # 提取填写统计
                    if "fill_statistics" in result.result:
                        fill_statistics = result.result["fill_statistics"]

            # 5. 构建最终响应（修复数据传递）
            final_result = {
                "success": result_analysis["overall_success"],
                "message": self._generate_result_message(result_analysis),
                "response": intelligent_response,
                # 表单相关数据（新增）
                "filled_fields": form_data,
                "validation_result": validation_result,
                "pain_relief_metrics": pain_relief_metrics,
                "fill_statistics": fill_statistics,
                # 原有数据
                "execution_summary": {
                    "total_tasks": len(execution_results),
                    "successful_tasks": result_analysis["successful_tasks"],
                    "failed_tasks": result_analysis["failed_tasks"],
                    "total_execution_time": result_analysis["total_execution_time"],
                    "agent_performance": result_analysis["agent_performance"]
                },
                "effect_metrics": effect_metrics,
                "user_context": self._build_enhanced_context(user_request, request_analysis),
                "request_id": self.request_id,
                "timestamp": self._get_current_time(),
                "recommendations": await self._generate_recommendations(execution_results, request_analysis)
            }

            # 5. 记录执行历史
            self._record_execution_history(execution_results, final_result)

            logger.info(f"结果整合完成，成功率: {result_analysis['success_rate']:.2%}")

            return final_result

        except Exception as e:
            error_traceback = traceback.format_exc()
            logger.error(f"整合结果时发生错误: {e}")
            logger.error(f"错误堆栈: {error_traceback}")

            # 返回安全的基础响应
            return safe_response(
                message="系统处理完成，但结果整合时遇到问题",
                error_code="INTEGRATION_WARNING",
                details=str(e) if logger.isEnabledFor(logging.DEBUG) else None,
                request_id=self.request_id
            )

    def _analyze_execution_results(self, execution_results: Dict[str, TaskResult]) -> Dict[str, Any]:
        """分析执行结果质量"""
        successful_tasks = sum(1 for result in execution_results.values() if result.success)
        failed_tasks = len(execution_results) - successful_tasks
        total_tasks = len(execution_results)

        total_execution_time = sum(result.execution_time for result in execution_results.values())
        success_rate = successful_tasks / total_tasks if total_tasks > 0 else 0

        # 分析Agent性能
        agent_performance = {}
        for task_result in execution_results.values():
            agent_name = task_result.agent_name
            if agent_name not in agent_performance:
                agent_performance[agent_name] = {
                    "tasks_executed": 0,
                    "successful_tasks": 0,
                    "total_time": 0.0,
                    "average_time": 0.0
                }

            agent_perf = agent_performance[agent_name]
            agent_perf["tasks_executed"] += 1
            agent_perf["total_time"] += task_result.execution_time

            if task_result.success:
                agent_perf["successful_tasks"] += 1

            agent_perf["average_time"] = agent_perf["total_time"] / agent_perf["tasks_executed"]
            agent_perf["success_rate"] = agent_perf["successful_tasks"] / agent_perf["tasks_executed"]

        # 确定整体成功状态
        overall_success = success_rate >= 0.7  # 至少70%的任务成功

        return {
            "overall_success": overall_success,
            "successful_tasks": successful_tasks,
            "failed_tasks": failed_tasks,
            "total_tasks": total_tasks,
            "success_rate": success_rate,
            "total_execution_time": total_execution_time,
            "agent_performance": agent_performance,
            "quality_score": self._calculate_quality_score(execution_results)
        }

    def _calculate_quality_score(self, execution_results: Dict[str, TaskResult]) -> float:
        """计算执行质量分数"""
        if not execution_results:
            return 0.0

        scores = []

        for result in execution_results.values():
            task_score = 0.0

            # 成功得分（40%）
            if result.success:
                task_score += 0.4

            # 执行时间得分（30%） - 越快越好
            time_score = max(0, 1.0 - (result.execution_time / 10.0))  # 10秒为基准
            task_score += time_score * 0.3

            # 重试次数得分（30%） - 重试越少越好
            retry_score = max(0, 1.0 - (result.retry_count / 3.0))
            task_score += retry_score * 0.3

            scores.append(task_score)

        return sum(scores) / len(scores)

    async def _generate_intelligent_response(self, execution_results: Dict[str, TaskResult], request_analysis: Dict[str, Any], user_request: UserRequest) -> str:
        """生成智能响应"""
        successful_results = {
            task_key: result for task_key, result in execution_results.items()
            if result.success
        }

        if not successful_results:
            return "抱歉，处理您的请求时遇到了问题，请稍后重试或联系管理员。"

        # 基于成功的Agent结果生成响应
        responses = []

        for task_key, result in successful_results.items():
            if result.result and isinstance(result.result, dict):
                if "response" in result.result:
                    responses.append(result.result["response"])
                elif "message" in result.result:
                    responses.append(result.result["message"])
                elif "suggestions" in result.result:
                    suggestions = result.result["suggestions"]
                    if suggestions:
                        if isinstance(suggestions, list):
                            responses.extend([str(s) for s in suggestions if s])
                        else:
                            responses.append(str(suggestions))

        # 如果有具体的响应内容，优先使用
        if responses:
            # 清理和合并响应
            cleaned_responses = []
            for resp in responses:
                if resp and isinstance(resp, str) and resp.strip():
                    cleaned_responses.append(resp.strip())

            if cleaned_responses:
                # 合并和优化响应
                combined_response = " ".join(cleaned_responses)
                # 可以进一步调用LLM优化响应
                return combined_response[:500]  # 限制长度
            else:
                # 如果清理后为空，返回默认响应
                return "系统处理完成，但没有生成具体响应内容。"

        # 默认响应
        user_intent = request_analysis.get("intent", "通用协助")
        return f"已为您处理{user_intent}相关的任务，系统运行正常。如有需要，请提供更多详细信息。"

    def _generate_result_message(self, result_analysis: Dict[str, Any]) -> str:
        """生成结果消息"""
        success_rate = result_analysis["success_rate"]
        total_tasks = result_analysis["total_tasks"]

        if success_rate >= 1.0:
            return "所有任务执行完成"
        elif success_rate >= 0.8:
            return f"大部分任务执行完成（{result_analysis['successful_tasks']}/{total_tasks}）"
        elif success_rate >= 0.5:
            return f"部分任务执行完成（{result_analysis['successful_tasks']}/{total_tasks}）"
        else:
            return "处理过程中遇到较多问题，但已完成核心任务"

    def _build_enhanced_context(self, user_request: UserRequest, request_analysis: Dict[str, Any]) -> Dict[str, Any]:
        """构建增强的上下文信息"""
        return {
            "user_id": user_request.user_id,
            "user_role": user_request.user_role,
            "department": user_request.department,
            "session_id": user_request.session_id,
            "timestamp": datetime.now().isoformat(),  # 使用当前时间戳
            "identified_pain_points": request_analysis.get("pain_points", []),
            "request_intent": request_analysis.get("intent", ""),
            "request_priority": request_analysis.get("priority", 5)
        }

    async def _generate_recommendations(self, execution_results: Dict[str, TaskResult], request_analysis: Dict[str, Any]) -> List[str]:
        """生成建议"""
        recommendations = []

        # 基于执行结果的建议
        failed_tasks = [result for result in execution_results.values() if not result.success]
        if failed_tasks:
            recommendations.append("建议检查网络连接或稍后重试")

        # 基于用户痛点的建议
        pain_points = request_analysis.get("pain_points", [])
        if "复杂" in pain_points:
            recommendations.append("建议使用逐步分解的方式处理复杂任务")
        if "耗时" in pain_points:
            recommendations.append("系统正在优化处理速度，您的反馈对我们很重要")

        return recommendations

    async def _calculate_comprehensive_metrics(self, execution_results: Dict[str, TaskResult], user_request: UserRequest, request_analysis: Dict[str, Any]) -> Dict[str, Any]:
        """计算综合效果指标"""
        # 基础指标
        successful_results = [r for r in execution_results.values() if r.success]
        total_time = sum(r.execution_time for r in execution_results.values())

        # 痛点缓解指标
        pain_points = request_analysis.get("pain_points", [])
        time_saved = 0
        complexity_reduction = 0.0

        if successful_results:
            # 基于任务类型估算节省的时间
            for result in successful_results:
                if result.agent_name == "form_agent":
                    time_saved += 25  # 表格填写预计节省25分钟
                    complexity_reduction += 0.8
                elif result.agent_name == "search_agent":
                    time_saved += 10  # 搜索预计节省10分钟
                    complexity_reduction += 0.6
                elif result.agent_name == "approve_agent":
                    time_saved += 15  # 审批预计节省15分钟
                    complexity_reduction += 0.7

        # 计算满意度（基于成功率和时间节省）
        success_rate = len(successful_results) / len(execution_results) if execution_results else 0
        satisfaction = min(5.0, success_rate * 3 + (time_saved / 30) * 2)

        return {
            "time_saved_minutes": round(time_saved, 1),
            "processing_time_seconds": round(total_time, 2),
            "success_rate": round(success_rate, 3),
            "pain_relief_score": round(complexity_reduction / len(pain_points) if pain_points else 0.5, 3),
            "user_satisfaction": round(satisfaction, 1),
            "tasks_completed": len(successful_results),
            "tasks_total": len(execution_results),
            "agent_effectiveness": self._calculate_agent_effectiveness(execution_results)
        }

    def _calculate_agent_effectiveness(self, execution_results: Dict[str, TaskResult]) -> Dict[str, float]:
        """计算Agent有效性"""
        effectiveness = {}

        for agent_name in set(r.agent_name for r in execution_results.values()):
            agent_results = [r for r in execution_results.values() if r.agent_name == agent_name]
            if agent_results:
                success_rate = sum(1 for r in agent_results if r.success) / len(agent_results)
                avg_time = sum(r.execution_time for r in agent_results) / len(agent_results)
                # 有效性 = 成功率 * 时间效率
                effectiveness[agent_name] = success_rate * (1.0 / max(avg_time, 0.1))

        return effectiveness

    def _record_execution_history(self, execution_results: Dict[str, TaskResult], final_result: Dict[str, Any]) -> None:
        """记录执行历史"""
        for task_result in execution_results.values():
            self.execution_history.append(task_result)

        # 限制历史记录数量
        if len(self.execution_history) > 1000:
            self.execution_history = self.execution_history[-500:]

        logger.info(f"执行历史已更新，当前记录数: {len(self.execution_history)}")

    async def _record_interaction_async(self, user_request: UserRequest, request_analysis: Dict[str, Any], result: Dict[str, Any]) -> None:
        """异步记录交互数据（不阻塞主流程）"""
        try:
            await self._record_interaction(user_request, request_analysis, result)
        except Exception as e:
            logger.error(f"异步记录交互数据失败: {e}")

    def _calculate_effect_metrics(self, results: Dict[str, Any]) -> PainReliefMetrics:
        """计算效果指标"""
        success_count = sum(1 for result in results.values() if result.get("success", False))
        total_count = len(results)

        return PainReliefMetrics(
            success_rate=success_count / total_count if total_count > 0 else 0,
            processing_time=self._calculate_total_processing_time(results),
            pain_relief_score=self._calculate_pain_relief_score(results),
            user_satisfaction=4.5  # 这里需要根据实际反馈计算
        )

    def _calculate_total_processing_time(self, results: Dict[str, Any]) -> float:
        """计算总处理时间"""
        total_time = 0
        for result in results.values():
            if isinstance(result, dict) and "processing_time" in result:
                total_time += result["processing_time"]
        return total_time

    def _calculate_pain_relief_score(self, results: Dict[str, Any]) -> float:
        """计算痛苦缓解分数"""
        score = 0.0
        count = 0

        for result in results.values():
            if isinstance(result, dict) and "pain_relief_score" in result:
                score += result["pain_relief_score"]
                count += 1

        return score / count if count > 0 else 0.0

    async def _record_interaction(self, user_request: UserRequest, analysis: Dict[str, Any], result: Dict[str, Any]) -> None:
        """记录交互数据用于学习优化"""
        try:
            learn_agent = self.agents.get("learn_agent")
            if learn_agent:
                await learn_agent.record_interaction(
                    user_request=user_request,
                    analysis=analysis,
                    result=result,
                    timestamp=self._get_current_time()
                )
        except Exception as e:
            logger.error(f"记录交互数据时发生错误: {e}")

    def _get_current_time(self) -> str:
        """获取当前时间戳"""
        from datetime import datetime
        return datetime.now().isoformat()

    async def get_system_status(self) -> Dict[str, Any]:
        """获取系统状态"""
        return {
            "agents_health": self.agent_health,
            "agents_performance": self.agent_performance,
            "active_tasks": len(self.active_tasks),
            "execution_history_size": len(self.execution_history),
            "cache_size": len(self.request_cache),
            "system_uptime": (datetime.now() - self.start_time).total_seconds() if self.start_time else 0
        }

    async def health_check(self) -> Dict[str, Any]:
        """健康检查"""
        healthy_agents = sum(1 for status in self.agent_health.values() if status)
        total_agents = len(self.agent_health)

        return {
            "orchestrator_status": "healthy",
            "agent_health_rate": healthy_agents / total_agents if total_agents > 0 else 0,
            "healthy_agents": healthy_agents,
            "total_agents": total_agents,
            "last_request_id": self.request_id,
            "system_metrics": await self.get_system_status()
        }

    async def shutdown(self) -> None:
        """关闭AgentOrchestrator"""
        logger.info("正在关闭AgentOrchestrator...")

        # 关闭线程池执行器
        if hasattr(self, 'executor'):
            self.executor.shutdown(wait=True)

        # 关闭所有Agent
        for agent_name, agent in self.agents.items():
            try:
                if hasattr(agent, 'shutdown'):
                    await agent.shutdown()
                logger.info(f"Agent {agent_name} 已关闭")
            except Exception as e:
                logger.error(f"关闭Agent {agent_name} 时发生错误: {e}")

        # 清理资源
        self.active_tasks.clear()
        self.task_status.clear()
        self.request_cache.clear()

        logger.info("AgentOrchestrator 已完全关闭")