"""
智能审批流程引擎

核心功能：
1. 动态路由规则 - 基于业务规则和权限的智能路由
2. 多级审批流程 - 支持串行、并行、条件分支
3. 自动化决策 - 基于历史数据和规则的自动审批
4. 实时状态跟踪 - 全流程可视化和通知
5. 异常处理 - 超时、驳回、转交等异常情况处理
"""

import logging
import json
import uuid
from typing import Dict, List, Any, Optional, Tuple, Union, Set
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime, timedelta
import asyncio
from enum import Enum

from app.services.llm_service import LLMService
from app.models.request import UserRequest, UserRole
from app.utils.security import check_rate_limit

logger = logging.getLogger(__name__)


class ApprovalStatus(Enum):
    """审批状态"""
    PENDING = "pending"          # 待审批
    IN_PROGRESS = "in_progress"  # 审批中
    APPROVED = "approved"        # 已批准
    REJECTED = "rejected"        # 已驳回
    CANCELLED = "cancelled"      # 已取消
    EXPIRED = "expired"          # 已过期
    RETURNED = "returned"        # 已退回修改


class NodeType(Enum):
    """节点类型"""
    START = "start"              # 开始节点
    APPROVAL = "approval"        # 审批节点
    CONDITION = "condition"      # 条件节点
    PARALLEL = "parallel"        # 并行节点
    NOTIFY = "notify"           # 通知节点
    END = "end"                 # 结束节点


class ApprovalAction(Enum):
    """审批动作"""
    SUBMIT = "submit"            # 提交
    APPROVE = "approve"          # 批准
    REJECT = "reject"            # 驳回
    RETURN = "return"            # 退回
    FORWARD = "forward"          # 转交
    CANCEL = "cancel"            # 撤销


@dataclass
class ApprovalNode:
    """审批节点"""
    node_id: str
    node_type: NodeType
    node_name: str
    description: str
    approvers: List[str] = field(default_factory=list)  # 审批人ID列表
    conditions: Dict[str, Any] = field(default_factory=dict)  # 条件配置
    timeout_hours: int = 24  # 超时时间（小时）
    required_approvals: int = 1  # 所需审批数量
    parallel_execution: bool = False  # 是否并行执行
    auto_approve: bool = False  # 是否自动审批
    notification_rules: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ApprovalWorkflow:
    """审批工作流"""
    workflow_id: str
    workflow_name: str
    workflow_type: str  # expense_approval, leave_approval, etc.
    nodes: List[ApprovalNode] = field(default_factory=list)
    edges: Dict[str, List[str]] = field(default_factory=dict)  # 节点连接关系
    variables: Dict[str, Any] = field(default_factory=dict)  # 工作流变量
    created_at: datetime = field(default_factory=datetime.now)
    version: str = "1.0"


@dataclass
class ApprovalInstance:
    """审批实例"""
    instance_id: str
    workflow: ApprovalWorkflow
    form_data: Dict[str, Any]
    submitter_id: str
    current_nodes: List[str] = field(default_factory=list)
    completed_nodes: List[str] = field(default_factory=list)
    status: ApprovalStatus = ApprovalStatus.PENDING
    variables: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    deadline: Optional[datetime] = None
    approver_actions: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)


@dataclass
class ApprovalActionRecord:
    """审批动作记录"""
    action_id: str
    instance_id: str
    node_id: str
    approver_id: str
    action: ApprovalAction
    comment: str
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)


class WorkflowTemplateManager:
    """工作流模板管理器"""

    def __init__(self):
        self.templates = self._initialize_templates()

    def _initialize_templates(self) -> Dict[str, ApprovalWorkflow]:
        """初始化工作流模板"""
        templates = {}

        # 费用报销审批流程
        expense_nodes = [
            ApprovalNode(
                node_id="start",
                node_type=NodeType.START,
                node_name="开始",
                description="报销申请提交"
            ),
            ApprovalNode(
                node_id="manager_approval",
                node_type=NodeType.APPROVAL,
                node_name="部门经理审批",
                description="部门经理审核报销申请",
                approvers=["manager"],
                required_approvals=1,
                timeout_hours=24
            ),
            ApprovalNode(
                node_id="amount_condition",
                node_type=NodeType.CONDITION,
                node_name="金额条件判断",
                description="根据金额决定审批级别",
                conditions={"amount_threshold": 1000}
            ),
            ApprovalNode(
                node_id="finance_approval",
                node_type=NodeType.APPROVAL,
                node_name="财务审批",
                description="财务部门审核",
                approvers=["finance_manager"],
                required_approvals=1,
                timeout_hours=24
            ),
            ApprovalNode(
                node_id="end",
                node_type=NodeType.END,
                node_name="完成",
                description="审批流程结束"
            )
        ]

        expense_edges = {
            "start": ["manager_approval"],
            "manager_approval": ["amount_condition"],
            "amount_condition": ["finance_approval", "end"],
            "finance_approval": ["end"]
        }

        templates["expense_approval"] = ApprovalWorkflow(
            workflow_id="expense_approval_v1",
            workflow_name="费用报销审批流程",
            workflow_type="expense_approval",
            nodes=expense_nodes,
            edges=expense_edges
        )

        # 请假申请审批流程
        leave_nodes = [
            ApprovalNode(
                node_id="start",
                node_type=NodeType.START,
                node_name="开始",
                description="请假申请提交"
            ),
            ApprovalNode(
                node_id="duration_condition",
                node_type=NodeType.CONDITION,
                node_name="时长条件判断",
                description="根据请假天数决定审批级别",
                conditions={"days_threshold": 3}
            ),
            ApprovalNode(
                node_id="direct_manager_approval",
                node_type=NodeType.APPROVAL,
                node_name="直接主管审批",
                description="直接主管审核请假申请",
                approvers=["direct_manager"],
                required_approvals=1,
                timeout_hours=12
            ),
            ApprovalNode(
                node_id="hr_approval",
                node_type=NodeType.APPROVAL,
                node_name="HR审批",
                description="人力资源部审核",
                approvers=["hr_manager"],
                required_approvals=1,
                timeout_hours=24
            ),
            ApprovalNode(
                node_id="end",
                node_type=NodeType.END,
                node_name="完成",
                description="请假审批完成"
            )
        ]

        leave_edges = {
            "start": ["duration_condition"],
            "duration_condition": ["direct_manager_approval", "hr_approval"],
            "direct_manager_approval": ["end"],
            "hr_approval": ["end"]
        }

        templates["leave_approval"] = ApprovalWorkflow(
            workflow_id="leave_approval_v1",
            workflow_name="请假申请审批流程",
            workflow_type="leave_approval",
            nodes=leave_nodes,
            edges=leave_edges
        )

        # 采购申请审批流程
        procurement_nodes = [
            ApprovalNode(
                node_id="start",
                node_type=NodeType.START,
                node_name="开始",
                description="采购申请提交"
            ),
            ApprovalNode(
                node_id="department_approval",
                node_type=NodeType.APPROVAL,
                node_name="部门审批",
                description="申请部门负责人审批",
                approvers=["department_head"],
                required_approvals=1,
                timeout_hours=24
            ),
            ApprovalNode(
                node_id="budget_condition",
                node_type=NodeType.CONDITION,
                node_name="预算条件判断",
                description="根据金额决定审批流程",
                conditions={"budget_threshold": 5000}
            ),
            ApprovalNode(
                node_id="procurement_approval",
                node_type=NodeType.APPROVAL,
                node_name="采购部审批",
                description="采购部门审核",
                approvers=["procurement_manager"],
                required_approvals=1,
                timeout_hours=24
            ),
            ApprovalNode(
                node_id="finance_approval",
                node_type=NodeType.APPROVAL,
                node_name="财务审批",
                description="财务部门审核预算",
                approvers=["finance_manager"],
                required_approvals=1,
                timeout_hours=48
            ),
            ApprovalNode(
                node_id="end",
                node_type=NodeType.END,
                node_name="完成",
                description="采购审批完成"
            )
        ]

        procurement_edges = {
            "start": ["department_approval"],
            "department_approval": ["budget_condition"],
            "budget_condition": ["procurement_approval", "finance_approval"],
            "procurement_approval": ["finance_approval"],
            "finance_approval": ["end"]
        }

        templates["procurement_approval"] = ApprovalWorkflow(
            workflow_id="procurement_approval_v1",
            workflow_name="采购申请审批流程",
            workflow_type="procurement_approval",
            nodes=procurement_nodes,
            edges=procurement_edges
        )

        return templates

    def get_template(self, workflow_type: str) -> Optional[ApprovalWorkflow]:
        """获取工作流模板"""
        return self.templates.get(workflow_type)

    def add_template(self, workflow: ApprovalWorkflow):
        """添加工作流模板"""
        self.templates[workflow.workflow_type] = workflow


class IntelligentRoutingEngine:
    """智能路由引擎"""

    def __init__(self, llm_service: LLMService):
        self.llm_service = llm_service
        self.routing_rules = self._initialize_routing_rules()

    def _initialize_routing_rules(self) -> Dict[str, Any]:
        """初始化路由规则"""
        return {
            "expense_approval": {
                "amount_thresholds": [
                    {"amount": 1000, "next_node": "end"},
                    {"amount": 5000, "next_node": "finance_approval"},
                    {"amount": float('inf'), "next_node": "senior_finance_approval"}
                ],
                "role_routing": {
                    "manager": ["manager_approval"],
                    "employee": ["self_approval", "manager_approval"]
                }
            },
            "leave_approval": {
                "duration_thresholds": [
                    {"days": 1, "next_node": "end"},
                    {"days": 3, "next_node": "direct_manager_approval"},
                    {"days": float('inf'), "next_node": "hr_approval"}
                ],
                "leave_type_routing": {
                    "sick_leave": ["direct_manager_approval"],
                    "annual_leave": ["direct_manager_approval"],
                    "maternity_leave": ["hr_approval"]
                }
            }
        }

    async def determine_route(self, workflow_type: str, form_data: Dict[str, Any],
                             user_context: Dict[str, Any]) -> List[str]:
        """确定审批路由"""
        try:
            routing_prompt = f"""
            请基于表单数据和用户信息，确定审批路由：

            工作流类型：{workflow_type}
            表单数据：{json.dumps(form_data, ensure_ascii=False)}
            用户信息：{json.dumps(user_context, ensure_ascii=False)}

            请返回JSON格式的路由决策：
            {{
                "approval_chain": ["审批节点1", "审批节点2", "审批节点3"],
                "reasoning": "路由决策理由",
                "confidence": 0.0-1.0,
                "special_conditions": ["特殊情况1", "特殊情况2"]
            }}

            注意：
            1. 考虑用户角色和权限
            2. 考虑金额、时长等业务规则
            3. 考虑紧急程度和重要性
            4. 确保合规性要求
            """

            result = await self.llm_service.chat_completion([
                {"role": "system", "content": "你是一个专业的审批路由决策助手，擅长根据业务规则确定审批流程。"},
                {"role": "user", "content": routing_prompt}
            ])

            if result.get("success"):
                response_text = result.get("response", "{}")
                try:
                    routing_data = json.loads(response_text)
                    approval_chain = routing_data.get("approval_chain", [])
                    reasoning = routing_data.get("reasoning", "")

                    logger.info(f"智能路由决策完成: {approval_chain}, 理由: {reasoning}")
                    return approval_chain

                except (json.JSONDecodeError, KeyError) as e:
                    logger.warning(f"路由决策解析失败: {e}")

        except Exception as e:
            logger.error(f"智能路由失败: {e}")

        # 降级到规则路由
        return self._rule_based_routing(workflow_type, form_data, user_context)

    def _rule_based_routing(self, workflow_type: str, form_data: Dict[str, Any],
                           user_context: Dict[str, Any]) -> List[str]:
        """基于规则的降级路由"""
        if workflow_type not in self.routing_rules:
            return ["default_approval"]

        rules = self.routing_rules[workflow_type]

        # 根据工作流类型应用不同的路由规则
        if workflow_type == "expense_approval":
            amount = form_data.get("amount", 0)
            try:
                amount = float(amount)
            except (ValueError, TypeError):
                amount = 0

            # 金额路由
            for threshold in rules.get("amount_thresholds", []):
                if amount <= threshold["amount"]:
                    return [threshold["next_node"]]

        elif workflow_type == "leave_approval":
            days = form_data.get("leave_days", 0)
            try:
                days = int(days)
            except (ValueError, TypeError):
                days = 0

            # 时长路由
            for threshold in rules.get("duration_thresholds", []):
                if days <= threshold["days"]:
                    return [threshold["next_node"]]

        return ["default_approval"]


class ApprovalWorkflowEngine:
    """审批工作流引擎"""

    def __init__(self, llm_service: LLMService):
        self.llm_service = llm_service
        self.template_manager = WorkflowTemplateManager()
        self.routing_engine = IntelligentRoutingEngine(llm_service)
        self.active_instances = {}  # 活跃的审批实例
        self.action_history = {}  # 审批动作历史

    async def create_approval_instance(self, workflow_type: str, form_data: Dict[str, Any],
                                      submitter_context: Dict[str, Any]) -> ApprovalInstance:
        """创建审批实例"""
        try:
            # 获取工作流模板
            template = self.template_manager.get_template(workflow_type)
            if not template:
                raise ValueError(f"未找到工作流类型 {workflow_type} 的模板")

            # 智能路由决策
            custom_route = await self.routing_engine.determine_route(workflow_type, form_data, submitter_context)

            # 创建审批实例
            instance = ApprovalInstance(
                instance_id=str(uuid.uuid4()),
                workflow=template,
                form_data=form_data,
                submitter_id=submitter_context.get("user_id", ""),
                variables={"custom_route": custom_route}
            )

            # 初始化流程
            await self._initialize_workflow(instance)

            # 保存实例
            self.active_instances[instance.instance_id] = instance

            logger.info(f"创建审批实例: {instance.instance_id}, 工作流: {workflow_type}")
            return instance

        except Exception as e:
            logger.error(f"创建审批实例失败: {e}")
            raise

    async def _initialize_workflow(self, instance: ApprovalInstance):
        """初始化工作流程"""
        workflow = instance.workflow

        # 从开始节点开始
        start_nodes = [node for node in workflow.nodes if node.node_type == NodeType.START]
        if not start_nodes:
            raise ValueError("工作流必须包含开始节点")

        start_node = start_nodes[0]

        # 获取下一个节点
        next_nodes = workflow.edges.get(start_node.node_id, [])
        instance.current_nodes = next_nodes

        # 设置截止时间
        total_timeout = sum(node.timeout_hours for node in workflow.nodes if node.timeout_hours)
        instance.deadline = datetime.now() + timedelta(hours=total_timeout)

        logger.info(f"初始化工作流: {instance.instance_id}, 当前节点: {next_nodes}")

    async def process_approval_action(self, instance_id: str, approver_id: str, action: ApprovalAction,
                                    comment: str = "", metadata: Dict[str, Any] = None) -> Dict[str, Any]:
        """处理审批动作"""
        try:
            instance = self.active_instances.get(instance_id)
            if not instance:
                raise ValueError(f"审批实例 {instance_id} 不存在")

            # 检查权限
            if not await self._check_approval_permission(instance, approver_id):
                return {"success": False, "error": "无审批权限"}

            # 检查动作有效性
            if not await self._validate_action(instance, approver_id, action):
                return {"success": False, "error": "动作无效"}

            # 记录审批动作
            action_record = ApprovalActionRecord(
                action_id=str(uuid.uuid4()),
                instance_id=instance_id,
                node_id=instance.current_nodes[0] if instance.current_nodes else "",
                approver_id=approver_id,
                action=action,
                comment=comment,
                metadata=metadata or {}
            )

            if instance_id not in self.action_history:
                self.action_history[instance_id] = []
            self.action_history[instance_id].append({
                "action_id": action_record.action_id,
                "approver_id": approver_id,
                "action": action.value,
                "comment": comment,
                "timestamp": action_record.timestamp.isoformat()
            })

            # 处理不同的审批动作
            result = await self._handle_approval_action(instance, approver_id, action, comment, action_record)

            # 更新实例状态
            instance.updated_at = datetime.now()
            self.active_instances[instance_id] = instance

            return result

        except Exception as e:
            logger.error(f"处理审批动作失败: {e}")
            return {"success": False, "error": str(e)}

    async def _check_approval_permission(self, instance: ApprovalInstance, approver_id: str) -> bool:
        """检查审批权限"""
        for node_id in instance.current_nodes:
            # 找到对应的节点
            node = next((n for n in instance.workflow.nodes if n.node_id == node_id), None)
            if node and node.node_type == NodeType.APPROVAL:
                # 检查是否在审批人列表中
                if approver_id in node.approvers:
                    return True

        return False

    async def _validate_action(self, instance: ApprovalInstance, approver_id: str, action: ApprovalAction) -> bool:
        """验证动作有效性"""
        if instance.status == ApprovalStatus.COMPLETED:
            return False

        if action == ApprovalAction.APPROVE:
            # 检查是否已经审批过
            for record in self.action_history.get(instance.instance_id, []):
                if record["approver_id"] == approver_id and record["action"] in ["approve", "reject"]:
                    return False

        return True

    async def _handle_approval_action(self, instance: ApprovalInstance, approver_id: str,
                                      action: ApprovalAction, comment: str, action_record: ApprovalActionRecord) -> Dict[str, Any]:
        """处理审批动作"""
        current_node_id = instance.current_nodes[0] if instance.current_nodes else ""
        current_node = next((n for n in instance.workflow.nodes if n.node_id == current_node_id), None)

        if action == ApprovalAction.APPROVE:
            return await self._handle_approve(instance, approver_id, current_node, action_record)
        elif action == ApprovalAction.REJECT:
            return await self._handle_reject(instance, approver_id, current_node, action_record)
        elif action == ApprovalAction.RETURN:
            return await self._handle_return(instance, approver_id, current_node, action_record)
        elif action == ApprovalAction.FORWARD:
            return await self._handle_forward(instance, approver_id, current_node, action_record)
        elif action == ApprovalAction.CANCEL:
            return await self._handle_cancel(instance, approver_id, action_record)
        else:
            return {"success": False, "error": "不支持的动作类型"}

    async def _handle_approve(self, instance: ApprovalInstance, approver_id: str,
                             node: ApprovalNode, action_record: ApprovalActionRecord) -> Dict[str, Any]:
        """处理批准动作"""
        # 检查是否达到所需审批数量
        approvals = [r for r in self.action_history.get(instance.instance_id, [])
                   if r["action"] == "approve" and self._is_node_affected(r, node.node_id)]

        required_approvals = node.required_approvals

        if len(approvals) >= required_approvals:
            # 节点审批完成，移动到下一个节点
            next_nodes = instance.workflow.edges.get(node.node_id, [])

            if not next_nodes:
                # 流程结束
                instance.status = ApprovalStatus.APPROVED
                instance.current_nodes = []
                instance.completed_nodes.append(node.node_id)
            else:
                # 移动到下一个节点
                instance.current_nodes = next_nodes
                instance.completed_nodes.append(node.node_id)
        else:
            # 还需要更多审批
            logger.info(f"节点 {node.node_id} 需要更多审批: {len(approvals)}/{required_approvals}")

        return {
            "success": True,
            "action": "approved",
            "message": "审批成功",
            "current_status": instance.status.value,
            "next_nodes": instance.current_nodes
        }

    async def _handle_reject(self, instance: ApprovalInstance, approver_id: str,
                             node: ApprovalNode, action_record: ApprovalActionRecord) -> Dict[str, Any]:
        """处理驳回动作"""
        instance.status = ApprovalStatus.REJECTED
        instance.current_nodes = []
        instance.completed_nodes.append(node.node_id)

        return {
            "success": True,
            "action": "rejected",
            "message": "申请已驳回",
            "current_status": instance.status.value
        }

    async def _handle_return(self, instance: ApprovalInstance, approver_id: str,
                            node: ApprovalNode, action_record: ApprovalActionRecord) -> Dict[str, Any]:
        """处理退回修改动作"""
        instance.status = ApprovalStatus.RETURNED
        instance.current_nodes = []

        # 重置到开始节点
        start_nodes = [n.node_id for n in instance.workflow.nodes if n.node_type == NodeType.START]
        if start_nodes:
            next_nodes = instance.workflow.edges.get(start_nodes[0], [])
            instance.current_nodes = next_nodes

        return {
            "success": True,
            "action": "returned",
            "message": "申请已退回修改",
            "current_status": instance.status.value
        }

    async def _handle_forward(self, instance: ApprovalInstance, approver_id: str,
                              node: ApprovalNode, action_record: ApprovalActionRecord) -> Dict[str, Any]:
        """处理转交动作"""
        # 这里可以实现转交逻辑
        # 简化实现：添加新的审批人
        if "forward_to" in action_record.metadata:
            forward_to = action_record.metadata["forward_to"]
            if forward_to not in node.approvers:
                node.approvers.append(forward_to)

        return {
            "success": True,
            "action": "forwarded",
            "message": "申请已转交",
            "current_status": instance.status.value
        }

    async def _handle_cancel(self, instance: ApprovalInstance, approver_id: str,
                            action_record: ApprovalActionRecord) -> Dict[str, Any]:
        """处理撤销动作"""
        # 只有提交人可以撤销
        if approver_id == instance.submitter_id:
            instance.status = ApprovalStatus.CANCELLED
            instance.current_nodes = []

            return {
                "success": True,
                "action": "cancelled",
                "message": "申请已撤销",
                "current_status": instance.status.value
            }
        else:
            return {"success": False, "error": "只有提交人可以撤销申请"}

    def _is_node_affected(self, action_record: Dict[str, Any], node_id: str) -> bool:
        """检查动作记录是否影响指定节点"""
        # 简化实现，实际中需要更复杂的逻辑
        return True

    async def get_approval_status(self, instance_id: str) -> Dict[str, Any]:
        """获取审批状态"""
        instance = self.active_instances.get(instance_id)
        if not instance:
            return {"error": "审批实例不存在"}

        # 计算进度
        total_nodes = len([n for n in instance.workflow.nodes if n.node_type != NodeType.START])
        completed_nodes = len(instance.completed_nodes)
        progress = (completed_nodes / total_nodes * 100) if total_nodes > 0 else 0

        # 获取当前审批人
        current_approvers = []
        for node_id in instance.current_nodes:
            node = next((n for n in instance.workflow.nodes if n.node_id == node_id), None)
            if node:
                current_approvers.extend(node.approvers)

        # 检查是否超时
        is_overdue = False
        if instance.deadline and datetime.now() > instance.deadline:
            is_overdue = True

        return {
            "instance_id": instance_id,
            "status": instance.status.value,
            "progress": round(progress, 2),
            "current_nodes": instance.current_nodes,
            "completed_nodes": instance.completed_nodes,
            "current_approvers": current_approvers,
            "created_at": instance.created_at.isoformat(),
            "updated_at": instance.updated_at.isoformat(),
            "deadline": instance.deadline.isoformat() if instance.deadline else None,
            "is_overdue": is_overdue,
            "action_history": self.action_history.get(instance_id, [])
        }

    async def get_my_approvals(self, approver_id: str, status_filter: Optional[str] = None) -> List[Dict[str, Any]]:
        """获取待我审批的列表"""
        my_approvals = []

        for instance_id, instance in self.active_instances.items():
            # 检查当前节点是否需要该用户审批
            for node_id in instance.current_nodes:
                node = next((n for n in instance.workflow.nodes if n.node_id == node_id), None)
                if node and approver_id in node.approvers and node.node_type == NodeType.APPROVAL:
                    # 检查状态过滤
                    if status_filter is None or instance.status.value == status_filter:
                        # 检查是否已经审批过
                        has_approved = any(
                            r["approver_id"] == approver_id and r["action"] in ["approve", "reject"]
                            for r in self.action_history.get(instance_id, [])
                        )

                        if not has_approved:
                            approval_info = {
                                "instance_id": instance_id,
                                "workflow_name": instance.workflow.workflow_name,
                                "workflow_type": instance.workflow.workflow_type,
                                "submitter_id": instance.submitter_id,
                                "form_data": instance.form_data,
                                "node_id": node_id,
                                "node_name": node.node_name,
                                "description": node.description,
                                "deadline": instance.deadline.isoformat() if instance.deadline else None,
                                "created_at": instance.created_at.isoformat(),
                                "is_overdue": instance.deadline and datetime.now() > instance.deadline
                            }
                            my_approvals.append(approval_info)

        return my_approvals

    async def get_approval_statistics(self, user_id: str) -> Dict[str, Any]:
        """获取审批统计信息"""
        stats = {
            "submitted": 0,      # 提交数量
            "approved": 0,       # 被批准数量
            "rejected": 0,       # 被驳回数量
            "pending": 0,        # 待审批数量
            "my_approvals": 0,    # 我审批的数量
            "avg_approval_time": 0  # 平均审批时间
        }

        submitted_instances = []
        approval_times = []

        for instance_id, instance in self.active_instances.items():
            # 统计提交的申请
            if instance.submitter_id == user_id:
                stats["submitted"] += 1
                submitted_instances.append(instance)

                if instance.status == ApprovalStatus.APPROVED:
                    stats["approved"] += 1
                elif instance.status == ApprovalStatus.REJECTED:
                    stats["rejected"] += 1
                elif instance.status == ApprovalStatus.PENDING:
                    stats["pending"] += 1

            # 统计我审批的申请
            my_actions = self.action_history.get(instance_id, [])
            for action in my_actions:
                if action["approver_id"] == user_id and action["action"] in ["approve", "reject"]:
                    stats["my_approvals"] += 1

                    # 计算审批时间
                    submit_time = instance.created_at
                    approval_time = datetime.fromisoformat(action["timestamp"])
                    approval_duration = (approval_time - submit_time).total_seconds() / 3600  # 小时
                    approval_times.append(approval_duration)

        # 计算平均审批时间
        if approval_times:
            stats["avg_approval_time"] = round(sum(approval_times) / len(approval_times), 2)

        return stats

    def get_workflow_template(self, workflow_type: str) -> Optional[ApprovalWorkflow]:
        """获取工作流模板"""
        return self.template_manager.get_template(workflow_type)

    def cleanup_expired_instances(self):
        """清理过期的审批实例"""
        current_time = datetime.now()
        expired_instances = []

        for instance_id, instance in self.active_instances.items():
            if instance.deadline and current_time > instance.deadline:
                if instance.status == ApprovalStatus.PENDING:
                    instance.status = ApprovalStatus.EXPIRED
                    expired_instances.append(instance_id)

        logger.info(f"清理过期审批实例: {len(expired_instances)} 个")

    async def auto_approve_eligible_requests(self):
        """自动审批符合条件的申请"""
        auto_approved = []

        for instance_id, instance in self.active_instances.items():
            if instance.status != ApprovalStatus.PENDING:
                continue

            for node_id in instance.current_nodes:
                node = next((n for n in instance.workflow.nodes if n.node_id == node_id), None)
                if node and node.auto_approve:
                    # 检查自动审批条件
                    if await self._check_auto_approve_conditions(instance, node):
                        # 自动批准
                        action_record = ApprovalActionRecord(
                            action_id=str(uuid.uuid4()),
                            instance_id=instance_id,
                            node_id=node_id,
                            approver_id="system",
                            action=ApprovalAction.APPROVE,
                            comment="系统自动审批",
                            metadata={"auto_approve": True}
                        )

                        result = await self._handle_approve(instance, "system", node, action_record)
                        auto_approved.append(instance_id)
                        break

        logger.info(f"自动审批完成: {len(auto_approved)} 个申请")

    async def _check_auto_approve_conditions(self, instance: ApprovalInstance, node: ApprovalNode) -> bool:
        """检查自动审批条件"""
        try:
            # 基于表单数据检查自动审批条件
            form_data = instance.form_data

            # 例如：小额报销自动批准
            if instance.workflow.workflow_type == "expense_approval":
                amount = form_data.get("amount", 0)
                try:
                    amount = float(amount)
                    # 100元以下自动批准
                    if amount <= 100:
                        return True
                except (ValueError, TypeError):
                    pass

            # 例如：1天以下请假自动批准
            elif instance.workflow.workflow_type == "leave_approval":
                days = form_data.get("leave_days", 0)
                try:
                    days = int(days)
                    if days <= 1:
                        return True
                except (ValueError, TypeError):
                    pass

            return False

        except Exception as e:
            logger.error(f"检查自动审批条件失败: {e}")
            return False