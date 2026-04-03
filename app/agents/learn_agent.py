"""
学习优化Agent - 生产实现
专门处理用户行为学习、系统优化、效果评估等场景

集成数据库持久化，提供真实的学习能力
"""

import json
import logging
import time
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta

from sqlalchemy import func, and_

from app.services.llm_service import LLMService
from app.database import db_manager
from app.models.request import UserRequest, RequestHistory
from app.models.metrics import PainReliefMetrics, PerformanceMetrics
from app.models.user import UserActivity, UserPreference
from app.utils.metrics import monitor_agent_performance

logger = logging.getLogger(__name__)


class LearnAgent:
    """学习优化Agent - 生产实现，数据持久化到数据库"""

    def __init__(self, llm_service: Optional[LLMService] = None):
        self.llm_service = llm_service if llm_service else LLMService()
        self.db_manager = db_manager
        # 内存缓存用于快速访问，定期同步到数据库
        self._learning_cache: Dict[str, Any] = {}
        self._cache_dirty = False

    async def warm_up(self) -> None:
        """预热Agent - 从数据库加载学习模型"""
        logger.info("LearnAgent 预热中...")

        # 验证数据库连接
        health = self.db_manager.health_check()
        if health.get("status") != "healthy":
            logger.warning(f"数据库连接异常: {health}")
        else:
            # 从数据库加载历史学习数据
            self._learning_cache = self._load_learning_data_from_db()
            logger.info(f"加载学习数据完成: {len(self._learning_cache.get('user_preference', {}))} 个用户模型")

        logger.info("LearnAgent 预热完成")

    def _load_learning_data_from_db(self) -> Dict[str, Any]:
        """从数据库加载学习数据"""
        learning_data = {
            "user_preference": {},
            "pattern_recognition": {},
            "performance_optimization": {}
        }

        with self.db_manager.get_session() as session:
            # 加载用户偏好数据
            user_prefs = session.query(UserPreference).all()
            for pref in user_prefs:
                learning_data["user_preference"][pref.user_id] = {
                    "theme": pref.theme,
                    "language": pref.language,
                    "preferred_ai_model": pref.preferred_ai_model,
                    "email_notifications": pref.email_notifications,
                    "push_notifications": pref.push_notifications
                }

            # 加载性能优化数据（最近7天）
            seven_days_ago = datetime.now() - timedelta(days=7)

            # 按服务类型分组的性能数据
            perf_stats = session.query(
                PerformanceMetrics.service_name,
                func.avg(PerformanceMetrics.value).label('avg_value'),
                func.count(PerformanceMetrics.id).label('count')
            ).filter(
                PerformanceMetrics.created_at >= seven_days_ago
            ).group_by(PerformanceMetrics.service_name).all()

            for stat in perf_stats:
                if stat[0]:
                    learning_data["performance_optimization"][stat[0]] = {
                        "average_value": round(stat[1], 2),
                        "total_count": stat[2]
                    }

        return learning_data

    @property
    def learning_models(self) -> Dict[str, Any]:
        """获取学习模型（带缓存）"""
        return self._learning_cache

    @monitor_agent_performance("learn_agent", "record_interaction")
    async def record_interaction(
        self,
        user_request: Any,
        analysis: Dict,
        result: Dict,
        timestamp: str,
        **kwargs
    ) -> Dict[str, Any]:
        """
        记录交互数据 - 主要入口，持久化到数据库

        Args:
            user_request: 用户请求对象或字典
            analysis: 分析结果
            result: 处理结果
            timestamp: 时间戳

        Returns:
            记录结果
        """
        try:
            user_id = user_request.get('user_id', 'unknown') if isinstance(user_request, dict) else getattr(user_request, 'user_id', 'unknown')
            logger.info(f"记录交互数据: user={user_id}")

            # 1. 提取学习数据
            learning_data = self._extract_learning_data(user_request, analysis, result)

            # 2. 持久化到数据库
            persist_result = self._persist_learning_data(learning_data)

            # 3. 更新内存缓存
            self._update_cache(learning_data)

            # 4. 生成优化建议
            optimizations = self._generate_optimization_suggestions_sync(learning_data)

            return {
                "success": True,
                "recorded_at": datetime.now().isoformat(),
                "learning_data": learning_data,
                "optimizations": optimizations,
                "persisted": persist_result.get("success", False),
                "models_updated": True
            }

        except Exception as e:
            logger.error(f"记录交互数据失败: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "recorded_at": datetime.now().isoformat()
            }

    def _extract_learning_data(self, user_request: Any, analysis: Dict, result: Dict) -> Dict[str, Any]:
        """提取学习数据"""
        if isinstance(user_request, dict):
            user_id = user_request.get('user_id', 'unknown')
            user_role = user_request.get('user_role', 'unknown')
            session_id = user_request.get('session_id', 'unknown')
        else:
            user_id = getattr(user_request, 'user_id', 'unknown')
            user_role = getattr(user_request, 'user_role', 'unknown')
            session_id = getattr(user_request, 'session_id', 'unknown')

        return {
            "user_id": user_id,
            "user_role": user_role,
            "session_id": session_id,
            "request_type": analysis.get("request_type", "unknown"),
            "pain_points": analysis.get("pain_points", []),
            "processing_time": result.get("processing_time", 0),
            "success": result.get("success", False),
            "satisfaction": result.get("effect_metrics", {}).get("user_satisfaction", 0),
            "interaction_timestamp": datetime.now().isoformat()
        }

    def _persist_learning_data(self, learning_data: Dict) -> Dict[str, Any]:
        """持久化学习数据到数据库"""
        try:
            with self.db_manager.get_session() as session:
                import uuid

                # 1. 记录用户活动
                activity = UserActivity(
                    activity_id=str(uuid.uuid4()),
                    user_id=learning_data["user_id"],
                    session_id=learning_data["session_id"],
                    activity_type=learning_data["request_type"],
                    activity_description=f"执行{learning_data['request_type']}操作",
                    activity_metadata={
                        "processing_time": learning_data["processing_time"],
                        "success": learning_data["success"],
                        "satisfaction": learning_data["satisfaction"]
                    }
                )
                session.add(activity)

                # 2. 记录性能指标
                if learning_data["processing_time"] > 0:
                    perf_metric = PerformanceMetrics(
                        metric_id=str(uuid.uuid4()),
                        metric_name="processing_time",
                        metric_type="response_time",
                        service_name=learning_data["request_type"],
                        value=learning_data["processing_time"],
                        unit="seconds",
                        user_id=learning_data["user_id"],
                        session_id=learning_data["session_id"]
                    )
                    session.add(perf_metric)

                # 3. 记录痛点缓解指标（如果有满意度数据）
                if learning_data["satisfaction"] > 0:
                    pain_metric = PainReliefMetrics(
                        metric_id=str(uuid.uuid4()),
                        user_id=learning_data["user_id"],
                        session_id=learning_data["session_id"],
                        pain_point_type=",".join(learning_data.get("pain_points", [])) or "general",
                        service_type=learning_data["request_type"],
                        success_rate=1.0 if learning_data["success"] else 0.0,
                        processing_time=learning_data["processing_time"],
                        user_satisfaction=learning_data["satisfaction"]
                    )
                    session.add(pain_metric)

                session.commit()

                return {"success": True, "persisted_at": datetime.now().isoformat()}

        except Exception as e:
            logger.error(f"持久化学习数据失败: {e}")
            return {"success": False, "error": str(e)}

    def _update_cache(self, learning_data: Dict) -> None:
        """更新内存缓存"""
        user_id = learning_data["user_id"]
        request_type = learning_data["request_type"]

        # 更新用户偏好缓存
        if user_id not in self._learning_cache.get("user_preference", {}):
            self._learning_cache.setdefault("user_preference", {})[user_id] = {
                "preferred_features": {},
                "interaction_count": 0
            }

        user_cache = self._learning_cache["user_preference"][user_id]
        user_cache["preferred_features"][request_type] = user_cache["preferred_features"].get(request_type, 0) + 1
        user_cache["interaction_count"] = user_cache.get("interaction_count", 0) + 1

        # 更新性能优化缓存
        if request_type not in self._learning_cache.get("performance_optimization", {}):
            self._learning_cache.setdefault("performance_optimization", {})[request_type] = {
                "total_time": 0,
                "count": 0,
                "success_count": 0
            }

        perf_cache = self._learning_cache["performance_optimization"][request_type]
        perf_cache["total_time"] += learning_data["processing_time"]
        perf_cache["count"] += 1
        if learning_data["success"]:
            perf_cache["success_count"] += 1

        self._cache_dirty = True

    def _generate_optimization_suggestions_sync(self, learning_data: Dict) -> List[str]:
        """生成优化建议（同步方法）"""
        suggestions = []

        # 基于性能数据的建议
        perf_data = self._learning_cache.get("performance_optimization", {})
        for request_type, perf_model in perf_data.items():
            count = perf_model.get("count", 0)
            if count > 0:
                avg_time = perf_model.get("total_time", 0) / count
                success_rate = perf_model.get("success_count", 0) / count

                if avg_time > 5.0:
                    suggestions.append(f"优化{request_type}功能的处理速度，当前平均{avg_time:.1f}秒")

                if success_rate < 0.9:
                    suggestions.append(f"提升{request_type}功能的成功率，当前{success_rate:.1%}")

        # 基于用户偏好的建议
        user_id = learning_data["user_id"]
        user_model = self._learning_cache.get("user_preference", {}).get(user_id, {})
        preferred_features = user_model.get("preferred_features", {})

        if preferred_features:
            most_used = max(preferred_features.items(), key=lambda x: x[1])
            suggestions.append(f"用户最常用的功能是{most_used[0]}，可以考虑优化此功能的体验")

        return suggestions

    async def get_system_status(self) -> Dict[str, Any]:
        """获取学习Agent状态"""
        db_health = self.db_manager.health_check()

        return {
            "agent_status": "healthy" if db_health.get("status") == "healthy" else "degraded",
            "database_connected": db_health.get("connected", False),
            "learning_models_loaded": len(self._learning_cache) > 0,
            "user_models_count": len(self._learning_cache.get("user_preference", {})),
            "performance_models_count": len(self._learning_cache.get("performance_optimization", {})),
            "cache_dirty": self._cache_dirty,
            "last_updated": datetime.now().isoformat()
        }

    def get_user_learning_profile(self, user_id: str) -> Dict[str, Any]:
        """
        获取用户学习档案

        Args:
            user_id: 用户ID

        Returns:
            用户学习档案
        """
        with self.db_manager.get_session() as session:
            # 查询用户活动统计
            activity_stats = session.query(
                UserActivity.activity_type,
                func.count(UserActivity.id).label('count')
            ).filter(
                UserActivity.user_id == user_id
            ).group_by(UserActivity.activity_type).all()

            # 查询用户满意度趋势
            satisfaction_data = session.query(
                PainReliefMetrics.user_satisfaction,
                PainReliefMetrics.created_at
            ).filter(
                PainReliefMetrics.user_id == user_id
            ).order_by(PainReliefMetrics.created_at.desc()).limit(10).all()

            return {
                "user_id": user_id,
                "activity_summary": {
                    stat[0]: stat[1] for stat in activity_stats
                },
                "satisfaction_trend": [
                    {"score": sat[0], "date": sat[1].isoformat() if sat[1] else None}
                    for sat in satisfaction_data
                ],
                "from_cache": self._learning_cache.get("user_preference", {}).get(user_id, {}),
                "retrieved_at": datetime.now().isoformat()
            }

    def reload_from_database(self) -> Dict[str, Any]:
        """从数据库重新加载学习数据"""
        self._learning_cache = self._load_learning_data_from_db()
        self._cache_dirty = False
        return {
            "success": True,
            "user_models_count": len(self._learning_cache.get("user_preference", {})),
            "reloaded_at": datetime.now().isoformat()
        }