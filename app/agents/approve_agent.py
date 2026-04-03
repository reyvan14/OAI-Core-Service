"""
审批Agent - 生产实现
专门处理审批请求、风险识别、建议生成等场景
解决"审批流程繁琐"的痛点

集成工作流模型，提供真实的审批能力
"""

import json
import logging
import time
from typing import Dict, Any, List, Optional
from datetime import datetime

from sqlalchemy import and_

from app.services.llm_service import LLMService
from app.database import db_manager
from app.models.workflow import (
    WorkflowTemplate, WorkflowNode, WorkflowInstanceDB,
    WorkflowStatus, NodeType
)
from app.models.user import User
from app.utils.metrics import monitor_agent_performance

logger = logging.getLogger(__name__)


class ApproveAgent:
    """审批Agent - 生产实现，集成工作流模型"""

    def __init__(self, llm_service: Optional[LLMService] = None):
        self.llm_service = llm_service if llm_service else LLMService()
        self.db_manager = db_manager
        self.approval_history: List[Dict[str, Any]] = []
        self._approval_rules_cache: Optional[Dict[str, Any]] = None

    async def warm_up(self) -> None:
        """预热Agent - 加载审批规则"""
        logger.info("ApproveAgent 预热中...")

        # 验证数据库连接
        health = self.db_manager.health_check()
        if health.get("status") != "healthy":
            logger.warning(f"数据库连接异常: {health}")
        else:
            # 预加载审批规则
            self._approval_rules_cache = self._load_approval_rules_from_db()
            logger.info(f"加载审批规则完成: {len(self._approval_rules_cache.get('templates', []))} 个模板")

        logger.info("ApproveAgent 预热完成")

    def _load_approval_rules_from_db(self) -> Dict[str, Any]:
        """从数据库加载审批规则"""
        with self.db_manager.get_session() as session:
            # 加载激活的工作流模板
            templates = session.query(WorkflowTemplate).filter(
                WorkflowTemplate.status == WorkflowStatus.ACTIVE.value
            ).all()

            # 提取审批规则
            rules = {
                "templates": [],
                "amount_thresholds": {},
                "risk_keywords": ["异常", "超额", "违规", "紧急", "特殊情况", "大额"],
                "auto_approve_conditions": []
            }

            for template in templates:
                template_info = {
                    "id": template.id,
                    "name": template.name,
                    "category": template.category,
                    "nodes": template.node_definitions or []
                }
                rules["templates"].append(template_info)

                # 从节点定义中提取阈值
                if template.node_definitions:
                    for node in template.node_definitions:
                        conditions = node.get("conditions", [])
                        for cond in conditions:
                            if cond.get("field") == "amount":
                                role = node.get("name", "unknown")
                                rules["amount_thresholds"][role] = cond.get("value", 0)

                        # 检查自动审批条件
                        if node.get("auto_approve"):
                            rules["auto_approve_conditions"].append({
                                "node": node.get("name"),
                                "conditions": conditions
                            })

            return rules

    @property
    def approval_rules(self) -> Dict[str, Any]:
        """获取审批规则（带缓存）"""
        if self._approval_rules_cache is None:
            self._approval_rules_cache = self._load_approval_rules_from_db()
        return self._approval_rules_cache

    @monitor_agent_performance("approve_agent", "smart_approval")
    async def smart_approval(self, approval_requests: List[Dict], approver_context: Dict[str, Any], execution_context: Optional[Dict] = None, **kwargs) -> Dict[str, Any]:
        """
        智能审批 - 主要入口
        """
        start_time = time.time()

        try:
            logger.info(f"开始智能审批: requests={len(approval_requests)}, approver={approver_context.get('user_id')}")

            if not approval_requests:
                return {
                    "success": False,
                    "error": "没有审批请求",
                    "message": "请提供审批申请信息",
                    "processing_time": time.time() - start_time
                }

            # 1. 分析每个审批请求
            analyzed_requests = []
            for request in approval_requests:
                analysis = await self._analyze_approval_request(request, approver_context)
                analyzed_requests.append(analysis)

            # 2. 生成审批建议
            approval_recommendations = await self._generate_approval_recommendations(analyzed_requests, approver_context)

            # 3. 记录审批历史
            self._record_approval_history(approval_requests, approver_context, approval_recommendations)

            processing_time = time.time() - start_time

            return {
                "success": True,
                "approval_requests": approval_requests,
                "analyzed_requests": analyzed_requests,
                "recommendations": approval_recommendations,
                "total_amount": sum(req.get("amount", 0) for req in approval_requests),
                "processing_time": processing_time,
                "auto_approve_count": sum(1 for rec in approval_recommendations if rec.get("auto_approve", False)),
                "manual_review_count": sum(1 for rec in approval_recommendations if not rec.get("auto_approve", False))
            }

        except Exception as e:
            logger.error(f"智能审批失败: {e}")
            return {
                "success": False,
                "error": str(e),
                "message": "审批过程中遇到问题，请稍后重试",
                "processing_time": time.time() - start_time
            }

    async def _analyze_approval_request(self, request: Dict, approver_context: Dict) -> Dict[str, Any]:
        """分析单个审批请求"""
        try:
            prompt = f"""
            分析审批申请，评估风险和合规性：

            申请信息：{request}
            审批人：{approver_context.get('user_id')} - {approver_context.get('user_role')}

            请分析并返回JSON格式结果，包含：
            1. risk_level：风险等级（低、中、高）
            2. compliance_score：合规评分（0-1）
            3. auto_approve：是否可以自动审批
            4. risk_factors：风险因素列表
            5. recommended_action：建议操作（批准、拒绝、需进一步审核）

            评估标准：
            - 金额：低于5000元风险低，高于20000元风险高
            - 历史：申请人历史记录良好风险低
            - 合规：符合公司政策风险低
            """

            response = await self.llm_service.generate(prompt)

            # 简单的解析逻辑
            if response.success and response.content:
                content = str(response.content or "").strip()
                if "高" in content or "high" in content.lower():
                    risk_level = "高"
                elif "中" in content or "medium" in content.lower():
                    risk_level = "中"
                else:
                    risk_level = "低"

                amount = request.get("amount", 0)
                auto_approve = amount < 1000 and "低" in risk_level

                return {
                    "request_id": request.get("id", "unknown"),
                    "risk_level": risk_level,
                    "compliance_score": 0.8 if risk_level == "低" else 0.5,
                    "auto_approve": auto_approve,
                    "risk_factors": [],
                    "recommended_action": "批准" if auto_approve else "需要审核",
                    "amount": amount
                }

            # 备用分析
            return self._fallback_approval_analysis(request)

        except Exception as e:
            logger.error(f"审批请求分析失败: {e}")
            return self._fallback_approval_analysis(request)

    def _fallback_approval_analysis(self, request: Dict) -> Dict[str, Any]:
        """基于工作流规则的审批分析"""
        amount = request.get("amount", 0)
        description = request.get("description", "")
        request_type = request.get("type", "expense")

        # 从规则缓存获取阈值
        thresholds = self.approval_rules.get("amount_thresholds", {})
        risk_keywords = self.approval_rules.get("risk_keywords", [])

        # 风险评估
        risk_level = "低"
        risk_factors = []
        compliance_score = 0.9
        auto_approve = True

        # 基于金额的风险评估
        manager_threshold = thresholds.get("经理审批", 5000)
        director_threshold = thresholds.get("总监审批", 20000)

        if amount > director_threshold:
            risk_level = "高"
            auto_approve = False
            compliance_score = 0.5
            risk_factors.append(f"金额超过总监审批限额({director_threshold}元)")
        elif amount > manager_threshold:
            risk_level = "中"
            auto_approve = False
            compliance_score = 0.7
            risk_factors.append(f"金额超过经理审批限额({manager_threshold}元)")

        # 基于关键词的风险评估
        for keyword in risk_keywords:
            if keyword in description:
                risk_level = "高" if risk_level != "高" else "高"
                risk_factors.append(f"包含风险关键词: {keyword}")
                auto_approve = False
                compliance_score = min(compliance_score, 0.6)

        # 检查历史记录（如果有申请人信息）
        applicant_id = request.get("applicant_id")
        if applicant_id:
            history_risk = self._check_applicant_history(applicant_id)
            if history_risk:
                risk_factors.extend(history_risk)
                auto_approve = False

        return {
            "request_id": request.get("id", "unknown"),
            "risk_level": risk_level,
            "compliance_score": round(compliance_score, 2),
            "auto_approve": auto_approve,
            "risk_factors": risk_factors,
            "recommended_action": "批准" if auto_approve else "需要审核",
            "amount": amount,
            "analysis_source": "workflow_rules"
        }

    def _check_applicant_history(self, applicant_id: str) -> List[str]:
        """检查申请人历史记录"""
        risk_factors = []

        with self.db_manager.get_session() as session:
            # 查询最近30天的审批历史
            from datetime import timedelta
            thirty_days_ago = datetime.now() - timedelta(days=30)

            # 查询被拒绝的请求
            rejected_count = session.query(WorkflowInstanceDB).filter(
                and_(
                    WorkflowInstanceDB.initiator_id == applicant_id,
                    WorkflowInstanceDB.status == "rejected",
                    WorkflowInstanceDB.started_at >= thirty_days_ago
                )
            ).count()

            if rejected_count > 2:
                risk_factors.append(f"近30天有{rejected_count}次审批被拒绝")

            # 查询频繁申请
            total_requests = session.query(WorkflowInstanceDB).filter(
                and_(
                    WorkflowInstanceDB.initiator_id == applicant_id,
                    WorkflowInstanceDB.started_at >= thirty_days_ago
                )
            ).count()

            if total_requests > 10:
                risk_factors.append(f"近30天提交{total_requests}次申请，频率较高")

        return risk_factors

    async def _generate_approval_recommendations(self, analyzed_requests: List[Dict], approver_context: Dict) -> List[Dict]:
        """生成审批建议"""
        recommendations = []

        for request in analyzed_requests:
            recommendation = {
                "request_id": request["request_id"],
                "action": request["recommended_action"],
                "auto_approve": request["auto_approve"],
                "risk_level": request["risk_level"],
                "reason": self._generate_approval_reason(request),
                "conditions": [],
                "estimated_time": "30分钟" if request["auto_approve"] else "2小时"
            }
            recommendations.append(recommendation)

        return recommendations

    def _generate_approval_reason(self, request: Dict) -> str:
        """生成审批理由"""
        if request["auto_approve"]:
            return "申请金额较低，风险等级低，符合自动审批条件"
        elif request["risk_level"] == "高":
            return "金额较大，需要详细审核和必要审批"
        else:
            return "申请需要进一步审核确认"

    def _record_approval_history(self, requests: List[Dict], approver: Dict, recommendations: List[Dict]) -> None:
        """记录审批历史"""
        self.approval_history.append({
            "approver_id": approver.get("user_id"),
            "request_count": len(requests),
            "total_amount": sum(req.get("amount", 0) for req in requests),
            "recommendations": recommendations,
            "timestamp": datetime.now().isoformat()
        })

        # 限制历史记录数量
        if len(self.approval_history) > 1000:
            self.approval_history = self.approval_history[-500:]

    async def get_system_status(self) -> Dict[str, Any]:
        """获取审批Agent状态"""
        db_health = self.db_manager.health_check()
        rules = self.approval_rules

        return {
            "agent_status": "healthy" if db_health.get("status") == "healthy" else "degraded",
            "database_connected": db_health.get("connected", False),
            "workflow_templates_count": len(rules.get("templates", [])),
            "approval_rules_loaded": len(rules) > 0,
            "approval_history_count": len(self.approval_history),
            "last_updated": datetime.now().isoformat()
        }

    def get_pending_tasks(self, approver_id: str) -> List[Dict[str, Any]]:
        """
        获取指定审批人的待处理任务

        Args:
            approver_id: 审批人ID

        Returns:
            待处理任务列表
        """
        with self.db_manager.get_session() as session:
            # 查询当前审批人在current_assignees中的运行中实例
            pending_instances = session.query(WorkflowInstanceDB).filter(
                WorkflowInstanceDB.status == "running"
            ).all()

            pending_tasks = []
            for instance in pending_instances:
                # 检查approver_id是否在current_assignees中
                current_assignees = instance.current_assignees or []
                if approver_id in current_assignees:
                    pending_tasks.append({
                        "instance_id": instance.id,
                        "template_name": instance.template_name,
                        "title": instance.title,
                        "description": instance.description,
                        "initiator_id": instance.initiator_id,
                        "current_node_id": instance.current_node_id,
                        "started_at": instance.started_at.isoformat() if instance.started_at else None,
                        "business_data": instance.business_data
                    })

            return pending_tasks

    def record_approval_action(
        self,
        instance_id: str,
        approver_id: str,
        action: str,
        comment: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        记录审批操作到工作流实例

        Args:
            instance_id: 工作流实例ID
            approver_id: 审批人ID
            action: 操作类型 (approve/reject)
            comment: 审批意见

        Returns:
            操作结果
        """
        with self.db_manager.get_session() as session:
            instance = session.query(WorkflowInstanceDB).filter(
                WorkflowInstanceDB.id == instance_id
            ).first()

            if not instance:
                return {"success": False, "error": f"实例不存在: {instance_id}"}

            # 添加审批记录
            approval_record = {
                "approver_id": approver_id,
                "action": action,
                "comment": comment,
                "node_id": instance.current_node_id,
                "timestamp": datetime.now().isoformat()
            }

            # 更新approval_history
            history = instance.approval_history or []
            history.append(approval_record)
            instance.approval_history = history

            # 更新实例状态
            if action == "reject":
                instance.status = "rejected"
                instance.completed_at = datetime.now()
            elif action == "approve":
                # 简化处理：这里应该根据工作流定义移动到下一节点
                # 实际实现应该调用WorkflowEngine
                instance.approval_history = history

            session.commit()

            return {
                "success": True,
                "instance_id": instance_id,
                "action": action,
                "new_status": instance.status,
                "timestamp": approval_record["timestamp"]
            }

    def invalidate_rules_cache(self) -> None:
        """使规则缓存失效，下次访问时重新加载"""
        self._approval_rules_cache = None
        logger.info("审批规则缓存已失效")