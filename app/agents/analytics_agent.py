"""
数据分析Agent - 生产实现
专门处理数据分析、报表生成、趋势预测等场景

集成数据库查询，提供真实的业务数据分析能力
"""

import json
import logging
import time
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta

from sqlalchemy import func, and_
from sqlalchemy.orm import Session

from app.services.llm_service import LLMService
from app.database import db_manager
from app.models.user import User, UserSession, UserActivity
from app.models.request import UserRequest, RequestHistory, ChatMessage, AIServiceLog
from app.models.metrics import PerformanceMetrics, PainReliefMetrics, SystemHealthMetrics
from app.utils.metrics import monitor_agent_performance

logger = logging.getLogger(__name__)


class AnalyticsAgent:
    """数据分析Agent - 生产实现，查询真实数据库"""

    def __init__(self, llm_service: Optional[LLMService] = None):
        self.llm_service = llm_service if llm_service else LLMService()
        self.db_manager = db_manager
        self.analysis_history: List[Dict[str, Any]] = []

    async def warm_up(self) -> None:
        """预热Agent - 验证数据库连接"""
        logger.info("AnalyticsAgent 预热中...")

        # 验证数据库连接
        health = self.db_manager.health_check()
        if health.get("status") != "healthy":
            logger.warning(f"数据库连接异常: {health}")
        else:
            logger.info("数据库连接正常")

        logger.info("AnalyticsAgent 预热完成")

    @monitor_agent_performance("analytics_agent", "generate_insights")
    async def generate_insights(self, analysis_type: str, user_context: Dict[str, Any], execution_context: Optional[Dict] = None, **kwargs) -> Dict[str, Any]:
        """
        生成分析洞察 - 主要入口
        """
        start_time = time.time()

        try:
            logger.info(f"开始生成分析洞察: type={analysis_type}, user={user_context.get('user_id')}")

            # 1. 获取分析数据
            analysis_data = await self._get_analysis_data(analysis_type, user_context)

            # 2. 生成洞察
            insights = await self._generate_insights_from_data(analysis_data, analysis_type, user_context)

            # 3. 生成可视化建议
            visualizations = await self._suggest_visualizations(analysis_data, insights)

            # 4. 记录分析历史
            self._record_analysis_history(analysis_type, user_context, insights)

            processing_time = time.time() - start_time

            return {
                "success": True,
                "analysis_type": analysis_type,
                "data_summary": analysis_data,
                "insights": insights,
                "visualizations": visualizations,
                "processing_time": processing_time,
                "generated_at": datetime.now().isoformat()
            }

        except Exception as e:
            logger.error(f"生成分析洞察失败: {e}")
            return {
                "success": False,
                "error": str(e),
                "message": "分析过程中遇到问题，请稍后重试",
                "processing_time": time.time() - start_time
            }

    async def _get_analysis_data(self, analysis_type: str, user_context: Dict) -> Dict[str, Any]:
        """获取分析数据 - 从真实数据库查询"""
        if analysis_type == "usage_statistics":
            return self._get_usage_statistics(user_context)
        elif analysis_type == "performance_metrics":
            return self._get_performance_metrics(user_context)
        elif analysis_type == "user_satisfaction":
            return self._get_user_satisfaction_data(user_context)
        elif analysis_type == "system_health":
            return self._get_system_health_data(user_context)
        else:
            raise ValueError(f"不支持的分析类型: {analysis_type}")

    def _get_usage_statistics(self, user_context: Dict) -> Dict[str, Any]:
        """获取使用统计数据 - 真实数据库查询"""
        with self.db_manager.get_session() as session:
            # 总用户数
            total_users = session.query(func.count(User.id)).scalar() or 0

            # 活跃用户数（最近7天有登录或活动）
            seven_days_ago = datetime.now() - timedelta(days=7)
            active_users = session.query(func.count(User.id)).filter(
                User.last_login_at >= seven_days_ago
            ).scalar() or 0

            # 今日请求数
            today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            daily_requests = session.query(func.count(UserRequest.id)).filter(
                UserRequest.created_at >= today_start
            ).scalar() or 0

            # 功能使用统计（按action_type分组）
            feature_stats = session.query(
                RequestHistory.action_type,
                func.count(RequestHistory.id).label('count')
            ).group_by(RequestHistory.action_type).all()

            popular_features = [
                {"feature": str(stat[0].value) if stat[0] else "unknown", "count": stat[1]}
                for stat in sorted(feature_stats, key=lambda x: x[1], reverse=True)[:5]
            ]

            # 用户增长率（本月vs上月）
            this_month_start = datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            last_month_start = (this_month_start - timedelta(days=1)).replace(day=1)

            this_month_users = session.query(func.count(User.id)).filter(
                User.created_at >= this_month_start
            ).scalar() or 0

            last_month_users = session.query(func.count(User.id)).filter(
                and_(User.created_at >= last_month_start, User.created_at < this_month_start)
            ).scalar() or 1  # 避免除零

            growth_rate = ((this_month_users - last_month_users) / last_month_users) * 100

            # 留存率（活跃用户/总用户）
            retention_rate = (active_users / total_users * 100) if total_users > 0 else 0

            return {
                "total_users": total_users,
                "active_users": active_users,
                "daily_requests": daily_requests,
                "popular_features": popular_features,
                "user_growth_rate": f"{growth_rate:.1f}%",
                "retention_rate": f"{retention_rate:.1f}%",
                "data_source": "database",
                "query_time": datetime.now().isoformat()
            }

    def _get_performance_metrics(self, user_context: Dict) -> Dict[str, Any]:
        """获取性能指标 - 真实数据库查询"""
        with self.db_manager.get_session() as session:
            # 最近24小时的数据
            last_24h = datetime.now() - timedelta(hours=24)

            # 平均响应时间
            avg_response_time = session.query(
                func.avg(UserRequest.processing_time)
            ).filter(
                UserRequest.created_at >= last_24h
            ).scalar() or 0

            # 成功率
            total_requests = session.query(func.count(UserRequest.id)).filter(
                UserRequest.created_at >= last_24h
            ).scalar() or 0

            successful_requests = session.query(func.count(UserRequest.id)).filter(
                and_(UserRequest.created_at >= last_24h, UserRequest.success == True)
            ).scalar() or 0

            success_rate = (successful_requests / total_requests) if total_requests > 0 else 0
            error_rate = 1 - success_rate

            # AI服务成功率
            ai_total = session.query(func.count(AIServiceLog.id)).filter(
                AIServiceLog.created_at >= last_24h
            ).scalar() or 0

            ai_success = session.query(func.count(AIServiceLog.id)).filter(
                and_(AIServiceLog.created_at >= last_24h, AIServiceLog.success == True)
            ).scalar() or 0

            ai_success_rate = (ai_success / ai_total) if ai_total > 0 else 0

            # 平均满意度评分
            avg_satisfaction = session.query(
                func.avg(PainReliefMetrics.user_satisfaction)
            ).filter(
                PainReliefMetrics.created_at >= last_24h
            ).scalar() or 0

            return {
                "average_response_time": round(avg_response_time, 2),
                "success_rate": round(success_rate, 4),
                "error_rate": round(error_rate, 4),
                "ai_success_rate": round(ai_success_rate, 4),
                "satisfaction_score": round(avg_satisfaction, 1),
                "total_requests_24h": total_requests,
                "data_source": "database",
                "query_time": datetime.now().isoformat()
            }

    def _get_user_satisfaction_data(self, user_context: Dict) -> Dict[str, Any]:
        """获取用户满意度数据 - 真实数据库查询"""
        with self.db_manager.get_session() as session:
            # 最近30天的数据
            last_30d = datetime.now() - timedelta(days=30)

            # 整体满意度
            overall_satisfaction = session.query(
                func.avg(PainReliefMetrics.user_satisfaction)
            ).filter(
                PainReliefMetrics.created_at >= last_30d
            ).scalar() or 0

            # 按服务类型分组的满意度
            service_satisfaction = session.query(
                PainReliefMetrics.service_type,
                func.avg(PainReliefMetrics.user_satisfaction).label('avg_satisfaction')
            ).filter(
                PainReliefMetrics.created_at >= last_30d
            ).group_by(PainReliefMetrics.service_type).all()

            feature_satisfaction = {
                stat[0]: round(stat[1], 1) for stat in service_satisfaction if stat[0]
            }

            # 正面反馈比例（满意度>=7的比例）
            total_ratings = session.query(func.count(PainReliefMetrics.id)).filter(
                and_(
                    PainReliefMetrics.created_at >= last_30d,
                    PainReliefMetrics.user_satisfaction.isnot(None)
                )
            ).scalar() or 0

            positive_ratings = session.query(func.count(PainReliefMetrics.id)).filter(
                and_(
                    PainReliefMetrics.created_at >= last_30d,
                    PainReliefMetrics.user_satisfaction >= 7
                )
            ).scalar() or 0

            positive_ratio = (positive_ratings / total_ratings) if total_ratings > 0 else 0

            # 需要改进的领域（满意度低于平均的服务）
            improvement_areas = [
                service for service, score in feature_satisfaction.items()
                if score < overall_satisfaction
            ]

            return {
                "overall_satisfaction": round(overall_satisfaction, 1),
                "feature_satisfaction": feature_satisfaction,
                "improvement_areas": improvement_areas,
                "positive_feedback_ratio": round(positive_ratio, 2),
                "total_feedback_count": total_ratings,
                "data_source": "database",
                "query_time": datetime.now().isoformat()
            }

    def _get_system_health_data(self, user_context: Dict) -> Dict[str, Any]:
        """获取系统健康数据 - 真实数据库查询"""
        with self.db_manager.get_session() as session:
            # 最新的系统健康指标
            latest_health = session.query(SystemHealthMetrics).order_by(
                SystemHealthMetrics.created_at.desc()
            ).first()

            if latest_health:
                return {
                    "cpu_usage": latest_health.cpu_usage,
                    "memory_usage": latest_health.memory_usage,
                    "disk_usage": latest_health.disk_usage,
                    "active_sessions": latest_health.active_sessions,
                    "concurrent_users": latest_health.concurrent_users,
                    "requests_per_minute": latest_health.requests_per_minute,
                    "ai_api_calls": latest_health.ai_api_calls,
                    "ai_response_time_avg": latest_health.ai_response_time_avg,
                    "ai_success_rate": latest_health.ai_success_rate,
                    "error_rate": latest_health.error_rate,
                    "data_source": "database",
                    "query_time": datetime.now().isoformat()
                }
            else:
                return {
                    "message": "暂无系统健康数据",
                    "data_source": "database",
                    "query_time": datetime.now().isoformat()
                }

    async def _generate_insights_from_data(self, data: Dict, analysis_type: str, user_context: Dict) -> List[str]:
        """从数据生成洞察"""
        try:
            prompt = f"""
            基于以下数据生成分析洞察：

            分析类型：{analysis_type}
            用户角色：{user_context.get('user_role')}
            数据：{json.dumps(data, ensure_ascii=False, indent=2)}

            请生成3-5个关键洞察，每条洞察包含：
            1. 发现的趋势或模式
            2. 可能的原因分析
            3. 建议的改进措施

            请以列表格式返回洞察内容。
            """

            response = await self.llm_service.generate(prompt)

            if response.success:
                # 简单解析，提取要点
                content = response.content or ""
                insights = []

                # 分割成行并过滤
                lines = [line.strip() for line in content.split('\n') if line.strip()]
                for line in lines:
                    if len(line) > 20:  # 过滤太短的行
                        insights.append(line)

                return insights if insights else ["数据分析完成，发现系统运行稳定"]

            # 备用洞察
            return self._fallback_insights(data, analysis_type)

        except Exception as e:
            logger.error(f"生成洞察失败: {e}")
            return self._fallback_insights(data, analysis_type)

    def _fallback_insights(self, data: Dict, analysis_type: str) -> List[str]:
        """基于真实数据生成基础洞察"""
        insights = []

        if analysis_type == "usage_statistics":
            total_users = data.get("total_users", 0)
            active_users = data.get("active_users", 0)
            daily_requests = data.get("daily_requests", 0)

            if total_users > 0:
                active_rate = (active_users / total_users) * 100
                insights.append(f"当前共有 {total_users} 名用户，活跃用户 {active_users} 人（活跃率 {active_rate:.1f}%）")

            if daily_requests > 0:
                insights.append(f"今日处理请求 {daily_requests} 次")

            popular = data.get("popular_features", [])
            if popular:
                top_feature = popular[0].get("feature", "未知") if isinstance(popular[0], dict) else popular[0]
                insights.append(f"最常用功能：{top_feature}")

        elif analysis_type == "performance_metrics":
            avg_time = data.get("average_response_time", 0)
            success_rate = data.get("success_rate", 0)
            total_requests = data.get("total_requests_24h", 0)

            if total_requests > 0:
                insights.append(f"过去24小时处理 {total_requests} 次请求，平均响应时间 {avg_time:.2f} 秒")
                insights.append(f"请求成功率 {success_rate*100:.1f}%")

            satisfaction = data.get("satisfaction_score", 0)
            if satisfaction > 0:
                insights.append(f"用户满意度评分 {satisfaction}/10")

        elif analysis_type == "user_satisfaction":
            overall = data.get("overall_satisfaction", 0)
            positive_ratio = data.get("positive_feedback_ratio", 0)
            total_feedback = data.get("total_feedback_count", 0)

            if total_feedback > 0:
                insights.append(f"基于 {total_feedback} 条反馈，整体满意度 {overall}/10")
                insights.append(f"正面反馈比例 {positive_ratio*100:.1f}%")

            improvement_areas = data.get("improvement_areas", [])
            if improvement_areas:
                insights.append(f"需要改进的领域：{', '.join(improvement_areas)}")

        else:
            insights.append("数据分析完成")
            insights.append(f"数据来源：{data.get('data_source', 'unknown')}")

        return insights if insights else ["暂无足够数据生成洞察"]

    async def _suggest_visualizations(self, data: Dict, insights: List[str]) -> List[Dict[str, Any]]:
        """建议可视化方案"""
        visualizations = []

        if "用户增长率" in str(data):
            visualizations.append({
                "type": "line_chart",
                "title": "用户增长趋势",
                "description": "展示用户数量随时间的变化趋势"
            })

        if "满意度" in str(insights):
            visualizations.append({
                "type": "bar_chart",
                "title": "用户满意度分析",
                "description": "不同功能模块的用户满意度对比"
            })

        if "成功率" in str(data):
            visualizations.append({
                "type": "pie_chart",
                "title": "系统成功率分析",
                "description": "展示成功和失败请求的比例分布"
            })

        if not visualizations:
            visualizations.append({
                "type": "summary_card",
                "title": "数据概览",
                "description": "关键指标的摘要展示"
            })

        return visualizations

    def _record_analysis_history(self, analysis_type: str, user_context: Dict, insights: List[str]) -> None:
        """记录分析历史"""
        self.analysis_history.append({
            "analysis_type": analysis_type,
            "user_id": user_context.get("user_id"),
            "insight_count": len(insights),
            "timestamp": datetime.now().isoformat()
        })

        # 限制历史记录数量
        if len(self.analysis_history) > 1000:
            self.analysis_history = self.analysis_history[-500:]

    async def get_system_status(self) -> Dict[str, Any]:
        """获取分析Agent状态"""
        db_health = self.db_manager.health_check()

        return {
            "agent_status": "healthy" if db_health.get("status") == "healthy" else "degraded",
            "database_connected": db_health.get("connected", False),
            "analysis_history_count": len(self.analysis_history),
            "supported_analysis_types": [
                "usage_statistics",
                "performance_metrics",
                "user_satisfaction",
                "system_health"
            ],
            "last_updated": datetime.now().isoformat()
        }