"""
效果跟踪器 - 用于量化AI-OA系统的痛点缓解效果
"""

import logging
import time
import asyncio
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
from enum import Enum
import json

logger = logging.getLogger(__name__)


class PainPointType(Enum):
    """痛点类型枚举"""
    FORM_COMPLEXITY = "form_complexity"          # 表格填写复杂
    APPROVAL_BUREAUCRACY = "approval_bureaucracy"  # 审批流程繁琐
    INFORMATION_SILENCE = "information_silence"    # 信息查找困难
    OPERATION_ERRORS = "operation_errors"         # 操作错误频发
    LEARNING_COST = "learning_cost"              # 新手学习成本高


@dataclass
class EffectMetrics:
    """效果指标数据结构"""
    user_id: str
    session_id: str
    pain_point_type: PainPointType
    task_description: str

    # 时间指标
    traditional_time_minutes: float    # 传统方式预估时间
    ai_time_seconds: float            # AI实际用时
    time_saved_minutes: float          # 节省时间

    # 质量指标
    traditional_error_rate: float     # 传统方式错误率
    ai_error_rate: float              # AI方式错误率
    error_reduction: float            # 错误率降低

    # 满意度指标
    user_satisfaction: float          # 用户满意度 (0-5)
    task_completion_success: bool     # 任务是否成功完成

    # 业务指标
    form_complexity_score: float      # 表格复杂度评分
    approval_steps_count: int         # 审批步骤数
    information_search_time: float    # 信息搜索时间

    # 元数据
    timestamp: datetime
    agent_used: str                  # 使用的Agent
    tools_used: List[str]            # 使用的工具

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        data = asdict(self)
        data['pain_point_type'] = self.pain_point_type.value
        data['timestamp'] = self.timestamp.isoformat()
        return data


class EffectTracker:
    """效果跟踪器主类"""

    def __init__(self):
        self.metrics_history: List[EffectMetrics] = []
        self.baseline_data: Dict[str, Dict] = {}
        self.accumulated_effects: Dict[str, float] = {
            "total_time_saved_hours": 0.0,
            "total_error_reduction": 0.0,
            "total_satisfaction_score": 0.0,
            "total_tasks_completed": 0,
            "average_efficiency_improvement": 0.0
        }

    def record_task_effect(self, metrics: EffectMetrics) -> None:
        """记录任务效果指标"""
        self.metrics_history.append(metrics)

        # 更新累积效果
        self.accumulated_effects["total_time_saved_hours"] += metrics.time_saved_minutes / 60
        self.accumulated_effects["total_error_reduction"] += metrics.error_reduction
        self.accumulated_effects["total_satisfaction_score"] += metrics.user_satisfaction
        self.accumulated_effects["total_tasks_completed"] += 1 if metrics.task_completion_success else 0

        # 计算效率改善
        efficiency_improvement = self._calculate_efficiency_improvement(metrics)
        if efficiency_improvement > 0:
            total_tasks = self.accumulated_effects["total_tasks_completed"]
            current_avg = self.accumulated_effects["average_efficiency_improvement"]
            self.accumulated_effects["average_efficiency_improvement"] = (
                (current_avg * (total_tasks - 1) + efficiency_improvement) / total_tasks
            )

        logger.info(f"记录效果指标: {metrics.pain_point_type.value}, "
                   f"节省时间: {metrics.time_saved_minutes:.1f}分钟, "
                   f"用户满意度: {metrics.user_satisfaction:.1f}/5.0")

    def calculate_pain_relief_score(self, metrics: EffectMetrics) -> float:
        """
        计算痛点缓解分数 (0-1)

        Args:
            metrics: 效果指标

        Returns:
            痛点缓解分数
        """
        # 时间改善度 (0-1)
        time_improvement = max(0, (metrics.traditional_time_minutes - metrics.ai_time_seconds / 60) /
                              max(metrics.traditional_time_minutes, 0.1))

        # 错误率改善度 (0-1)
        error_improvement = max(0, (metrics.traditional_error_rate - metrics.ai_error_rate) /
                               max(metrics.traditional_error_rate, 0.01))

        # 满意度标准化 (0-1)
        satisfaction_normalized = min(1.0, metrics.user_satisfaction / 5.0)

        # 综合分数 (可配置权重)
        pain_relief_score = (
            time_improvement * 0.4 +
            error_improvement * 0.3 +
            satisfaction_normalized * 0.3
        )

        return max(0.0, min(1.0, pain_relief_score))

    def _calculate_efficiency_improvement(self, metrics: EffectMetrics) -> float:
        """计算效率改善百分比"""
        traditional_time_seconds = metrics.traditional_time_minutes * 60
        if traditional_time_seconds <= 0:
            return 0.0

        improvement = (traditional_time_seconds - metrics.ai_time_seconds) / traditional_time_seconds
        return max(0.0, improvement)

    def get_summary_statistics(self, time_window_hours: int = 24) -> Dict[str, Any]:
        """
        获取汇总统计信息

        Args:
            time_window_hours: 时间窗口（小时）

        Returns:
            统计信息汇总
        """
        cutoff_time = datetime.now() - timedelta(hours=time_window_hours)

        # 过滤时间窗口内的数据
        recent_metrics = [
            m for m in self.metrics_history
            if m.timestamp >= cutoff_time
        ]

        if not recent_metrics:
            return {
                "time_window_hours": time_window_hours,
                "total_tasks": 0,
                "total_time_saved_hours": 0.0,
                "average_satisfaction_score": 0.0,
                "overall_pain_relief_score": 0.0,
                "pain_point_breakdown": {},
                "agent_performance": {}
            }

        # 按痛点类型分组
        pain_point_stats = {}
        for pain_type in PainPointType:
            type_metrics = [m for m in recent_metrics if m.pain_point_type == pain_type]
            if type_metrics:
                pain_point_stats[pain_type.value] = {
                    "count": len(type_metrics),
                    "total_time_saved_hours": sum(m.time_saved_minutes for m in type_metrics) / 60,
                    "average_satisfaction": sum(m.user_satisfaction for m in type_metrics) / len(type_metrics),
                    "average_pain_relief_score": sum(self.calculate_pain_relief_score(m) for m in type_metrics) / len(type_metrics)
                }

        # 按Agent分组统计
        agent_stats = {}
        for metrics in recent_metrics:
            if metrics.agent_used not in agent_stats:
                agent_stats[metrics.agent_used] = {
                    "count": 0,
                    "total_time_saved_hours": 0.0,
                    "average_satisfaction": 0.0,
                    "success_rate": 0.0
                }

            agent_stats[metrics.agent_used]["count"] += 1
            agent_stats[metrics.agent_used]["total_time_saved_hours"] += metrics.time_saved_minutes / 60
            agent_stats[metrics.agent_used]["total_satisfaction"] += metrics.user_satisfaction
            if metrics.task_completion_success:
                agent_stats[metrics.agent_used]["successes"] = agent_stats[metrics.agent_used].get("successes", 0) + 1

        # 计算平均值和成功率
        for agent_data in agent_stats.values():
            agent_data["average_satisfaction"] = agent_data.get("total_satisfaction", 0) / agent_data["count"]
            agent_data["success_rate"] = agent_data.get("successes", 0) / agent_data["count"]
            # 清理临时字段
            agent_data.pop("total_satisfaction", None)
            agent_data.pop("successes", None)

        # 计算总体指标
        total_time_saved_hours = sum(m.time_saved_minutes for m in recent_metrics) / 60
        average_satisfaction = sum(m.user_satisfaction for m in recent_metrics) / len(recent_metrics)
        overall_pain_relief_score = sum(self.calculate_pain_relief_score(m) for m in recent_metrics) / len(recent_metrics)

        return {
            "time_window_hours": time_window_hours,
            "total_tasks": len(recent_metrics),
            "total_time_saved_hours": round(total_time_saved_hours, 2),
            "average_satisfaction_score": round(average_satisfaction, 2),
            "overall_pain_relief_score": round(overall_pain_relief_score, 3),
            "pain_point_breakdown": pain_point_stats,
            "agent_performance": agent_stats,
            "generated_at": datetime.now().isoformat()
        }

    def get_trend_analysis(self, days: int = 7) -> Dict[str, Any]:
        """
        获取趋势分析

        Args:
            days: 分析天数

        Returns:
            趋势分析数据
        """
        cutoff_time = datetime.now() - timedelta(days=days)

        # 过滤指定天数内的数据
        metrics_in_window = [m for m in self.metrics_history if m.timestamp >= cutoff_time]

        if len(metrics_in_window) < 2:
            return {
                "trend_period_days": days,
                "insufficient_data": True,
                "message": f"需要至少2天的数据进行趋势分析，当前只有{len(metrics_in_window)}天"
            }

        # 按天分组
        daily_stats = {}
        for metrics in metrics_in_window:
            day_key = metrics.timestamp.strftime("%Y-%m-%d")
            if day_key not in daily_stats:
                daily_stats[day_key] = {
                    "tasks": 0,
                    "total_time_saved": 0.0,
                    "total_satisfaction": 0.0,
                    "total_pain_relief": 0.0
                }

            daily_stats[day_key]["tasks"] += 1
            daily_stats[day_key]["total_time_saved"] += metrics.time_saved_minutes
            daily_stats[day_key]["total_satisfaction"] += metrics.user_satisfaction
            daily_stats[day_key]["total_pain_relief"] += self.calculate_pain_relief_score(metrics)

        # 计算每日平均值
        for day_data in daily_stats.values():
            if day_data["tasks"] > 0:
                day_data["avg_time_saved"] = day_data["total_time_saved"] / day_data["tasks"]
                day_data["avg_satisfaction"] = day_data["total_satisfaction"] / day_data["tasks"]
                day_data["avg_pain_relief"] = day_data["total_pain_relief"] / day_data["tasks"]

        # 计算趋势
        days_list = sorted(daily_stats.keys())
        if len(days_list) >= 2:
            first_day = daily_stats[days_list[0]]
            last_day = daily_stats[days_list[-1]]

            time_saved_trend = (last_day["avg_time_saved"] - first_day["avg_time_saved"]) / first_day["avg_time_saved"] if first_day["avg_time_saved"] > 0 else 0
            satisfaction_trend = (last_day["avg_satisfaction"] - first_day["avg_satisfaction"]) / first_day["avg_satisfaction"] if first_day["avg_satisfaction"] > 0 else 0
            pain_relief_trend = (last_day["avg_pain_relief"] - first_day["avg_pain_relief"]) / first_day["avg_pain_relief"] if first_day["avg_pain_relief"] > 0 else 0
        else:
            time_saved_trend = satisfaction_trend = pain_relief_trend = 0

        return {
            "trend_period_days": days,
            "daily_breakdown": daily_stats,
            "trends": {
                "time_saved_trend_percent": round(time_saved_trend * 100, 1),
                "satisfaction_trend_percent": round(satisfaction_trend * 100, 1),
                "pain_relief_trend_percent": round(pain_relief_trend * 100, 1)
            },
            "generated_at": datetime.now().isoformat()
        }

    def export_metrics(self, format: str = "json", time_window_hours: int = 24) -> str:
        """
        导出指标数据

        Args:
            format: 导出格式 (json, csv)
            time_window_hours: 时间窗口

        Returns:
            导出的数据字符串
        """
        cutoff_time = datetime.now() - timedelta(hours=time_window_hours)
        recent_metrics = [m for m in self.metrics_history if m.timestamp >= cutoff_time]

        if format.lower() == "json":
            data = {
                "export_info": {
                    "time_window_hours": time_window_hours,
                    "total_records": len(recent_metrics),
                    "export_timestamp": datetime.now().isoformat()
                },
                "metrics": [m.to_dict() for m in recent_metrics]
            }
            return json.dumps(data, ensure_ascii=False, indent=2)

        elif format.lower() == "csv":
            if not recent_metrics:
                return "user_id,session_id,pain_point_type,task_description,time_saved_minutes,user_satisfaction,timestamp\n"

            csv_lines = []
            csv_lines.append("user_id,session_id,pain_point_type,task_description,time_saved_minutes,user_satisfaction,timestamp")

            for m in recent_metrics:
                line = f"{m.user_id},{m.session_id},{m.pain_point_type.value},\"{m.task_description}\",{m.time_saved_minutes},{m.user_satisfaction},{m.timestamp.isoformat()}"
                csv_lines.append(line)

            return "\n".join(csv_lines)

        else:
            raise ValueError(f"不支持的导出格式: {format}")

    def get_accumulated_effects(self) -> Dict[str, float]:
        """获取累积效果统计"""
        return self.accumulated_effects.copy()

    def clear_old_data(self, days_to_keep: int = 30) -> None:
        """清理旧数据"""
        cutoff_time = datetime.now() - timedelta(days=days_to_keep)
        original_count = len(self.metrics_history)

        self.metrics_history = [m for m in self.metrics_history if m.timestamp >= cutoff_time]

        cleared_count = original_count - len(self.metrics_history)
        if cleared_count > 0:
            logger.info(f"清理了 {cleared_count} 条超过 {days_to_keep} 天的历史数据")


# 全局效果跟踪器实例
effect_tracker = EffectTracker()


async def initialize_baseline_data():
    """初始化基准数据"""
    # 传统OA系统的基准数据（基于行业调研）
    effect_tracker.baseline_data = {
        "form_filling": {
            "average_time_minutes": 15.0,
            "error_rate": 0.15,  # 15%的错误率
            "complexity_score": 0.7
        },
        "approval_process": {
            "average_time_minutes": 30.0,
            "error_rate": 0.08,
            "steps_count": 5
        },
        "information_search": {
            "average_time_minutes": 8.0,
            "success_rate": 0.6
        },
        "task_learning": {
            "average_time_minutes": 45.0,
            "error_rate": 0.25
        }
    }

    logger.info("基准数据初始化完成")


# 启动时初始化 - 在应用启动时调用
# asyncio.create_task(initialize_baseline_data())