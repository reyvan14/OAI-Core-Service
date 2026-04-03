"""
工作流数据模型
"""

from datetime import datetime
from enum import Enum
from typing import Dict, List, Any, Optional
from pydantic import BaseModel, Field
from sqlalchemy import Column, String, Integer, Float, DateTime, Boolean, Text, JSON

# 使用Agent系统的AgentBase，避免创建独立的declarative_base
from app.database import Base


class NodeType(str, Enum):
    """节点类型枚举"""
    START = "start"          # 开始节点
    APPROVAL = "approval"     # 审批节点
    CONDITION = "condition"   # 条件分支节点
    PARALLEL = "parallel"     # 并行节点
    NOTIFY = "notify"         # 通知节点
    END = "end"              # 结束节点


class WorkflowStatus(str, Enum):
    """工作流状态枚举"""
    DRAFT = "draft"          # 草稿
    ACTIVE = "active"        # 激活
    SUSPENDED = "suspended"   # 暂停
    ARCHIVED = "archived"    # 归档


class AssigneeType(str, Enum):
    """审批人类型枚举"""
    USER = "user"            # 指定用户
    ROLE = "role"            # 指定角色
    DEPARTMENT = "department" # 指定部门
    SUPERIOR = "superior"    # 上级
    SCRIPT = "script"        # 脚本动态分配


class WorkflowTemplate(Base):
    """工作流模板数据表"""
    __tablename__ = "workflow_templates"

    id = Column(String(50), primary_key=True)
    name = Column(String(200), nullable=False)
    description = Column(Text)
    category = Column(String(100))
    status = Column(String(20), default=WorkflowStatus.DRAFT)
    version = Column(Integer, default=1)

    # 流程配置
    start_node_id = Column(String(50))
    end_node_ids = Column(JSON)  # 可能有多个结束节点

    # 元数据
    created_by = Column(String(50))
    created_at = Column(DateTime, default=datetime.now)
    updated_by = Column(String(50))
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    # 配置数据
    node_definitions = Column(JSON)  # 节点定义
    transitions = Column(JSON)       # 转换规则
    variables = Column(JSON)         # 流程变量

    # 统计信息
    usage_count = Column(Integer, default=0)
    last_used_at = Column(DateTime)


class WorkflowNode(Base):
    """工作流节点数据表"""
    __tablename__ = "workflow_nodes"

    id = Column(String(50), primary_key=True)
    template_id = Column(String(50), nullable=False)

    # 节点基本信息
    name = Column(String(200), nullable=False)
    description = Column(Text)
    node_type = Column(String(20), nullable=False)

    # 节点配置
    assignees = Column(JSON)          # 审批人配置
    conditions = Column(JSON)         # 条件规则
    actions = Column(JSON)           # 节点动作
    time_limits = Column(JSON)       # 时间限制

    # 节点行为
    is_required = Column(Boolean, default=True)
    allow_parallel = Column(Boolean, default=False)
    auto_approve = Column(Boolean, default=False)

    # 显示信息
    position = Column(JSON)          # 在流程图中的位置
    display_config = Column(JSON)    # 显示配置


class WorkflowInstanceDB(Base):
    """工作流实例数据表"""
    __tablename__ = "workflow_instances"

    id = Column(String(50), primary_key=True)
    template_id = Column(String(50), nullable=False)
    template_name = Column(String(200))
    template_version = Column(Integer, default=1)

    # 实例状态
    current_node_id = Column(String(50))  # 当前所在节点
    status = Column(String(20))  # running, completed, rejected, cancelled
    variables = Column(JSON)  # 流程变量值

    # 参与者
    initiator_id = Column(String(50), nullable=False)
    current_assignees = Column(JSON)  # 当前审批人列表

    # 时间信息
    started_at = Column(DateTime, default=datetime.now)
    completed_at = Column(DateTime)

    # 业务数据
    business_data = Column(JSON)
    title = Column(String(500))
    description = Column(Text)

    # 审批历史
    approval_history = Column(JSON)  # 审批记录列表


# Pydantic 模型用于API请求/响应

class AssigneeConfig(BaseModel):
    """审批人配置"""
    type: AssigneeType
    value: str  # 用户ID、角色名、部门名等
    fallback: Optional[List[str]] = None  # 备选审批人


class NodeCondition(BaseModel):
    """节点条件"""
    field: str      # 条件字段
    operator: str   # 操作符: ==, !=, >, <, >=, <=, in, contains
    value: Any     # 条件值
    logic: str = "and"  # 逻辑操作符: and, or


class TimeLimit(BaseModel):
    """时间限制配置"""
    enabled: bool = False
    business_hours_only: bool = True
    limit_hours: Optional[int] = None
    warning_hours: Optional[int] = None
    escalation_action: Optional[str] = None


class WorkflowNodeConfig(BaseModel):
    """工作流节点配置"""
    id: str
    name: str
    description: Optional[str] = ""
    node_type: NodeType
    assignees: List[AssigneeConfig]
    conditions: List[NodeCondition] = []
    actions: List[str] = []  # 节点执行的动作
    time_limits: Optional[TimeLimit] = None

    # 节点行为
    is_required: bool = True
    allow_parallel: bool = False
    auto_approve: bool = False

    # 可视化配置
    position: Optional[Dict[str, float]] = None
    display_config: Optional[Dict[str, Any]] = None


class WorkflowTransition(BaseModel):
    """工作流转换规则"""
    from_node: str
    to_node: str
    condition: Optional[str] = None  # 转换条件表达式
    action: Optional[str] = None     # 转换时执行的动作


class WorkflowVariable(BaseModel):
    """工作流变量"""
    name: str
    type: str  # string, number, boolean, date, array, object
    default_value: Any = None
    description: Optional[str] = ""
    required: bool = False


class WorkflowTemplateRequest(BaseModel):
    """创建工作流模板请求"""
    name: str
    description: Optional[str] = ""
    category: Optional[str] = ""
    start_node_id: str
    end_node_ids: List[str]
    nodes: List[WorkflowNodeConfig]
    transitions: List[WorkflowTransition]
    variables: List[WorkflowVariable] = []


class WorkflowTemplateResponse(BaseModel):
    """工作流模板响应"""
    id: str
    name: str
    description: str
    category: str
    status: WorkflowStatus
    version: int
    start_node_id: str
    end_node_ids: List[str]
    nodes: List[WorkflowNodeConfig]
    transitions: List[WorkflowTransition]
    variables: List[WorkflowVariable]

    # 元数据
    created_by: str
    created_at: datetime
    updated_by: Optional[str] = None
    updated_at: datetime

    # 统计信息
    usage_count: int
    last_used_at: Optional[datetime] = None


class WorkflowInstance(BaseModel):
    """工作流实例"""
    id: str
    template_id: str
    template_name: str
    template_version: int

    # 实例状态
    current_nodes: List[str]
    status: str
    variables: Dict[str, Any] = {}

    # 参与者
    initiator_id: str
    current_assignees: List[str]

    # 时间信息
    started_at: datetime
    completed_at: Optional[datetime] = None

    # 业务数据
    business_data: Dict[str, Any] = {}
    title: str
    description: str


class ApprovalActionRequest(BaseModel):
    """审批操作请求"""
    action: str  # approve, reject
    comment: Optional[str] = ""
    user_id: str  # 操作人ID


class ApprovalActionResponse(BaseModel):
    """审批操作响应"""
    success: bool
    message: str
    instance_id: str
    new_status: str
    current_node_id: Optional[str] = None


class PendingTask(BaseModel):
    """待处理任务"""
    instance_id: str
    template_name: str
    title: str
    description: str
    current_node_name: str
    initiator_id: str
    submitted_at: datetime
    status: str
    urgency: str = "normal"  # high, normal, low


# 预定义的常用流程模板

class CommonWorkflowTemplates:
    """常用工作流模板定义"""

    @staticmethod
    def get_expense_approval_template() -> WorkflowTemplateRequest:
        """获取费用报销审批流程模板"""
        return WorkflowTemplateRequest(
            name="费用报销审批流程",
            description="用于处理各种费用报销申请的审批流程",
            category="财务",
            start_node_id="start",
            end_node_ids=["end"],
            nodes=[
                WorkflowNodeConfig(
                    id="start",
                    name="提交申请",
                    node_type=NodeType.START,
                    assignees=[AssigneeConfig(type=AssigneeType.USER, value="${initiator}")]
                ),
                WorkflowNodeConfig(
                    id="manager_approval",
                    name="经理审批",
                    node_type=NodeType.APPROVAL,
                    assignees=[AssigneeConfig(type=AssigneeType.SUPERIOR, value="${initiator}")],
                    conditions=[
                        NodeCondition(field="amount", operator="<=", value=5000)
                    ]
                ),
                WorkflowNodeConfig(
                    id="director_approval",
                    name="总监审批",
                    node_type=NodeType.APPROVAL,
                    assignees=[AssigneeConfig(type=AssigneeType.ROLE, value="部门总监")],
                    conditions=[
                        NodeCondition(field="amount", operator=">", value=5000)
                    ]
                ),
                WorkflowNodeConfig(
                    id="end",
                    name="完成",
                    node_type=NodeType.END,
                    assignees=[]
                )
            ],
            transitions=[
                WorkflowTransition(from_node="start", to_node="manager_approval"),
                WorkflowTransition(from_node="start", to_node="director_approval"),
                WorkflowTransition(from_node="manager_approval", to_node="end"),
                WorkflowTransition(from_node="director_approval", to_node="end")
            ],
            variables=[
                WorkflowVariable(name="amount", type="number", description="报销金额", required=True),
                WorkflowVariable(name="expense_type", type="string", description="费用类型", required=True),
                WorkflowVariable(name="description", type="string", description="费用说明", required=True)
            ]
        )

    @staticmethod
    def get_leave_request_template() -> WorkflowTemplateRequest:
        """获取请假申请流程模板"""
        return WorkflowTemplateRequest(
            name="请假申请审批流程",
            description="用于处理各种请假申请的审批流程",
            category="人事",
            start_node_id="start",
            end_node_ids=["end"],
            nodes=[
                WorkflowNodeConfig(
                    id="start",
                    name="提交请假申请",
                    node_type=NodeType.START,
                    assignees=[AssigneeConfig(type=AssigneeType.USER, value="${initiator}")]
                ),
                WorkflowNodeConfig(
                    id="manager_approval",
                    name="直属领导审批",
                    node_type=NodeType.APPROVAL,
                    assignees=[AssigneeConfig(type=AssigneeType.SUPERIOR, value="${initiator}")]
                ),
                WorkflowNodeConfig(
                    id="hr_notification",
                    name="HR备案",
                    node_type=NodeType.NOTIFY,
                    assignees=[AssigneeConfig(type=AssigneeType.ROLE, value="HR专员")]
                ),
                WorkflowNodeConfig(
                    id="end",
                    name="完成",
                    node_type=NodeType.END,
                    assignees=[]
                )
            ],
            transitions=[
                WorkflowTransition(from_node="start", to_node="manager_approval"),
                WorkflowTransition(from_node="manager_approval", to_node="hr_notification"),
                WorkflowTransition(from_node="hr_notification", to_node="end")
            ],
            variables=[
                WorkflowVariable(name="leave_type", type="string", description="请假类型", required=True),
                WorkflowVariable(name="start_date", type="date", description="开始日期", required=True),
                WorkflowVariable(name="end_date", type="date", description="结束日期", required=True),
                WorkflowVariable(name="reason", type="string", description="请假原因", required=True)
            ]
        )


class WorkflowGenerationHistory(Base):
    """AI工作流生成历史记录表"""
    __tablename__ = "workflow_generation_history"

    id = Column(String(50), primary_key=True)

    # 用户信息
    user_id = Column(String(50), nullable=False, index=True)

    # 生成信息
    description = Column(Text, nullable=False)  # 用户的工作流需求描述
    initial_workflow = Column(JSON, nullable=False)  # 初始生成的工作流
    final_workflow = Column(JSON)  # 最终保存的工作流（可能经过多次优化）

    # 优化历史
    refinement_rounds = Column(Integer, default=0)  # 优化轮数
    refinement_feedbacks = Column(JSON)  # 每一轮的反馈内容

    # 状态信息
    status = Column(String(20), default="generated")  # generated/saved/discarded

    # 元数据
    created_at = Column(DateTime, default=datetime.now, index=True)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    # 统计信息
    generation_time_ms = Column(Integer)  # LLM调用耗时（毫秒）
    total_time_ms = Column(Integer)  # 总耗时（毫秒）
    model_used = Column(String(50))  # 使用的LLM模型