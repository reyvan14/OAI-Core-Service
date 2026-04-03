"""
监控和分析系统
提供系统性能监控、用户行为分析和业务指标追踪
"""

import asyncio
import json
import time
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
from enum import Enum
import logging
import uuid
from collections import defaultdict, deque
import psutil
import redis

from sqlalchemy import Column, Integer, String, Float, DateTime, Text, Boolean, JSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.postgresql import UUID

Base = declarative_base()
logger = logging.getLogger(__name__)

class MetricType(Enum):
    """指标类型"""
    COUNTER = "counter"      # 计数器
    GAUGE = "gauge"          # 仪表盘
    HISTOGRAM = "histogram"  # 直方图
    TIMER = "timer"          # 计时器

class AlertLevel(Enum):
    """告警级别"""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"

@dataclass
class Metric:
    """监控指标"""
    name: str
    value: float
    metric_type: MetricType
    timestamp: datetime
    tags: Dict[str, str] = None
    unit: str = ""
    description: str = ""

    def __post_init__(self):
        if self.tags is None:
            self.tags = {}

@dataclass
class Alert:
    """告警信息"""
    id: str
    level: AlertLevel
    title: str
    message: str
    source: str
    timestamp: datetime
    resolved: bool = False
    metadata: Dict[str, Any] = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}

class UserActivityEvent(Base):
    """用户活动事件表"""
    __tablename__ = "user_activity_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(String(64), nullable=False, index=True)
    session_id = Column(String(128), nullable=False, index=True)
    event_type = Column(String(50), nullable=False, index=True)  # 页面访问、功能使用、错误等
    action = Column(String(100), nullable=False)  # 具体行为
    resource = Column(String(200))  # 操作的资源
    page_url = Column(String(500))  # 页面URL
    referrer = Column(String(500))  # 来源页面
    user_agent = Column(Text)  # 用户代理
    ip_address = Column(String(45))  # IP地址
    duration_ms = Column(Integer)  # 操作持续时间（毫秒）
    status_code = Column(Integer)  # 状态码
    error_message = Column(Text)  # 错误信息
    event_metadata = Column(JSON)  # 额外的结构化数据
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)

class PerformanceMetric(Base):
    """性能指标表"""
    __tablename__ = "performance_metrics"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    metric_name = Column(String(100), nullable=False, index=True)
    metric_type = Column(String(20), nullable=False)  # counter, gauge, histogram, timer
    value = Column(Float, nullable=False)
    unit = Column(String(20))
    tags = Column(JSON)  # 标签
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)

class SystemHealth(Base):
    """系统健康状态表"""
    __tablename__ = "system_health"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    component = Column(String(100), nullable=False, index=True)  # 组件名称
    status = Column(String(20), nullable=False)  # healthy, unhealthy, degraded
    response_time_ms = Column(Integer)  # 响应时间
    cpu_usage = Column(Float)  # CPU使用率
    memory_usage = Column(Float)  # 内存使用率
    disk_usage = Column(Float)  # 磁盘使用率
    active_connections = Column(Integer)  # 活跃连接数
    error_rate = Column(Float)  # 错误率
    last_check = Column(DateTime, default=datetime.utcnow)
    health_metadata = Column(JSON)  # 额外的健康信息

class MetricsCollector:
    """指标收集器"""

    def __init__(self, redis_client=None, max_metrics=10000):
        self.metrics: Dict[str, deque] = defaultdict(lambda: deque(maxlen=1000))
        self.counters: Dict[str, float] = {}
        self.gauges: Dict[str, float] = {}
        self.histograms: Dict[str, List[float]] = defaultdict(lambda: deque(maxlen=1000))
        self.timers: Dict[str, List[float]] = defaultdict(lambda: deque(maxlen=1000))
        self.redis_client = redis_client
        self.logger = logging.getLogger(__name__)
        self.max_metrics = max_metrics
        self.last_cleanup = time.time()

    def _cleanup_old_metrics(self):
        """定期清理旧的指标数据以防止内存泄漏"""
        current_time = time.time()
        if current_time - self.last_cleanup < 3600:  # 每小时清理一次
            return

        try:
            # 清理计数器
            if len(self.counters) > self.max_metrics:
                # 保留最近使用的指标
                items = list(self.counters.items())
                self.counters = dict(items[-self.max_metrics:])

            # 清理仪表盘
            if len(self.gauges) > self.max_metrics:
                items = list(self.gauges.items())
                self.gauges = dict(items[-self.max_metrics:])

            self.last_cleanup = current_time
            self.logger.debug(f"Metrics cleanup completed. Counters: {len(self.counters)}, Gauges: {len(self.gauges)}")

        except Exception as e:
            self.logger.error(f"Error during metrics cleanup: {e}")

    def _check_memory_usage(self):
        """检查内存使用情况并在必要时强制清理"""
        total_metrics = (
            len(self.counters) + len(self.gauges) +
            sum(len(hist) for hist in self.histograms.values()) +
            sum(len(timer) for timer in self.timers.values())
        )

        if total_metrics > self.max_metrics * 2:  # 超过限制2倍时强制清理
            self.logger.warning(f"Memory usage too high ({total_metrics} metrics), forcing cleanup")
            # 更激进的清理策略
            self.counters.clear()
            self.gauges.clear()
            for key in list(self.histograms.keys()):
                if len(self.histograms[key]) > 100:  # 只保留最近100个
                    self.histograms[key] = deque(list(self.histograms[key])[-100:], maxlen=1000)
            for key in list(self.timers.keys()):
                if len(self.timers[key]) > 100:
                    self.timers[key] = deque(list(self.timers[key])[-100:], maxlen=1000)

    def increment_counter(self, name: str, value: float = 1.0, tags: Dict[str, str] = None):
        """增加计数器"""
        key = self._make_key(name, tags)
        self.counters[key] += value
        self._record_metric(name, value, MetricType.COUNTER, tags)

    def set_gauge(self, name: str, value: float, tags: Dict[str, str] = None):
        """设置仪表盘值"""
        key = self._make_key(name, tags)
        self.gauges[key] = value
        self._record_metric(name, value, MetricType.GAUGE, tags)

    def record_histogram(self, name: str, value: float, tags: Dict[str, str] = None):
        """记录直方图数据"""
        key = self._make_key(name, tags)
        self.histograms[key].append(value)
        # 保持最近1000个值
        if len(self.histograms[key]) > 1000:
            self.histograms[key] = self.histograms[key][-1000:]
        self._record_metric(name, value, MetricType.HISTOGRAM, tags)

    def record_timer(self, name: str, duration_ms: float, tags: Dict[str, str] = None):
        """记录计时器"""
        key = self._make_key(name, tags)
        self.timers[key].append(duration_ms)
        # 保持最近1000个值
        if len(self.timers[key]) > 1000:
            self.timers[key] = self.timers[key][-1000:]
        self._record_metric(name, duration_ms, MetricType.TIMER, tags, unit="ms")

    def _make_key(self, name: str, tags: Dict[str, str] = None) -> str:
        """生成指标键"""
        if not tags:
            return name
        tag_str = ",".join(f"{k}={v}" for k, v in sorted(tags.items()))
        return f"{name}[{tag_str}]"

    def _record_metric(self, name: str, value: float, metric_type: MetricType,
                      tags: Dict[str, str] = None, unit: str = ""):
        """记录指标"""
        metric = Metric(
            name=name,
            value=value,
            metric_type=metric_type,
            timestamp=datetime.utcnow(),
            tags=tags,
            unit=unit
        )

        # 存储到内存
        self.metrics[name].append(metric)

        # 如果有Redis，也存储到Redis
        if self.redis_client:
            try:
                self._store_to_redis(metric)
            except Exception as e:
                self.logger.error(f"Failed to store metric to Redis: {e}")

    def _store_to_redis(self, metric: Metric):
        """存储指标到Redis"""
        key = f"metrics:{metric.name}"
        data = {
            "value": metric.value,
            "type": metric.metric_type.value,
            "timestamp": metric.timestamp.isoformat(),
            "tags": metric.tags,
            "unit": metric.unit
        }
        self.redis_client.lpush(key, json.dumps(data))
        # 只保留最新的10000条记录
        self.redis_client.ltrim(key, 0, 9999)

    def get_metrics_summary(self, name: str, minutes: int = 5) -> Dict[str, Any]:
        """获取指标摘要"""
        cutoff_time = datetime.utcnow() - timedelta(minutes=minutes)
        recent_metrics = [
            m for m in self.metrics.get(name, [])
            if m.timestamp > cutoff_time
        ]

        if not recent_metrics:
            return {}

        values = [m.value for m in recent_metrics]
        return {
            "count": len(values),
            "min": min(values),
            "max": max(values),
            "avg": sum(values) / len(values),
            "latest": values[-1] if values else None,
            "trend": self._calculate_trend(values)
        }

    def _calculate_trend(self, values: List[float]) -> str:
        """计算趋势"""
        if len(values) < 2:
            return "stable"

        # 简单的线性回归计算趋势
        n = len(values)
        x = list(range(n))
        sum_x = sum(x)
        sum_y = sum(values)
        sum_xy = sum(x[i] * values[i] for i in range(n))
        sum_x2 = sum(x[i] ** 2 for i in range(n))

        slope = (n * sum_xy - sum_x * sum_y) / (n * sum_x2 - sum_x ** 2)

        if slope > 0.1:
            return "increasing"
        elif slope < -0.1:
            return "decreasing"
        else:
            return "stable"

class UserBehaviorTracker:
    """用户行为追踪器"""

    def __init__(self, db_session):
        self.db_session = db_session
        self.logger = logging.getLogger(__name__)

    def track_page_view(self, user_id: str, session_id: str, page_url: str,
                       referrer: str = None, user_agent: str = None,
                       ip_address: str = None):
        """追踪页面访问"""
        try:
            event = UserActivityEvent(
                user_id=user_id,
                session_id=session_id,
                event_type="page_view",
                action="visit",
                page_url=page_url,
                referrer=referrer,
                user_agent=user_agent,
                ip_address=ip_address
            )
            self.db_session.add(event)
            self.db_session.commit()
            self.logger.debug(f"Successfully tracked page view for user {user_id}")
        except Exception as e:
            self.db_session.rollback()
            self.logger.error(f"Failed to track page view for user {user_id}: {e}")
            raise

    def track_feature_usage(self, user_id: str, session_id: str, feature: str,
                           action: str, resource: str = None, duration_ms: int = None,
                           status_code: int = 200, error_message: str = None,
                           metadata: Dict[str, Any] = None):
        """追踪功能使用"""
        try:
            event = UserActivityEvent(
                user_id=user_id,
                session_id=session_id,
                event_type="feature_usage",
                action=action,
                resource=f"{feature}:{resource}" if resource else feature,
                duration_ms=duration_ms,
                status_code=status_code,
                error_message=error_message,
                metadata=metadata
            )
            self.db_session.add(event)
            self.db_session.commit()
            self.logger.debug(f"Successfully tracked feature usage for user {user_id}, feature {feature}")
        except Exception as e:
            self.db_session.rollback()
            self.logger.error(f"Failed to track feature usage for user {user_id}, feature {feature}: {e}")
            raise

    def track_form_interaction(self, user_id: str, session_id: str, form_type: str,
                              action: str, fields: Dict[str, Any] = None,
                              duration_ms: int = None, success: bool = True,
                              error_message: str = None):
        """追踪表单交互"""
        metadata = {
            "form_type": form_type,
            "fields_count": len(fields) if fields else 0,
            "success": success
        }
        if fields:
            metadata["field_names"] = list(fields.keys())

        event = UserActivityEvent(
            user_id=user_id,
            session_id=session_id,
            event_type="form_interaction",
            action=action,
            resource=form_type,
            duration_ms=duration_ms,
            status_code=200 if success else 400,
            error_message=error_message,
            metadata=metadata
        )
        self.db_session.add(event)
        self.db_session.commit()

    def track_ai_interaction(self, user_id: str, session_id: str, interaction_type: str,
                           query: str, response_time_ms: int = None,
                           success: bool = True, tokens_used: int = None,
                           satisfaction_score: float = None):
        """追踪AI交互"""
        metadata = {
            "interaction_type": interaction_type,
            "query_length": len(query),
            "success": success,
            "tokens_used": tokens_used,
            "satisfaction_score": satisfaction_score
        }

        event = UserActivityEvent(
            user_id=user_id,
            session_id=session_id,
            event_type="ai_interaction",
            action=interaction_type,
            resource="ai_assistant",
            duration_ms=response_time_ms,
            status_code=200 if success else 500,
            metadata=metadata
        )
        self.db_session.add(event)
        self.db_session.commit()

    def get_user_activity_summary(self, user_id: str, days: int = 7) -> Dict[str, Any]:
        """获取用户活动摘要"""
        start_date = datetime.utcnow() - timedelta(days=days)

        events = self.db_session.query(UserActivityEvent).filter(
            UserActivityEvent.user_id == user_id,
            UserActivityEvent.timestamp >= start_date
        ).all()

        # 统计各种活动
        page_views = len([e for e in events if e.event_type == "page_view"])
        feature_usage = len([e for e in events if e.event_type == "feature_usage"])
        form_interactions = len([e for e in events if e.event_type == "form_interaction"])
        ai_interactions = len([e for e in events if e.event_type == "ai_interaction"])

        # 计算活跃天数
        active_days = len(set(e.timestamp.date() for e in events))

        # 平均响应时间
        avg_response_time = 0
        timed_events = [e for e in events if e.duration_ms is not None]
        if timed_events:
            avg_response_time = sum(e.duration_ms for e in timed_events) / len(timed_events)

        return {
            "user_id": user_id,
            "period_days": days,
            "active_days": active_days,
            "total_events": len(events),
            "page_views": page_views,
            "feature_usage": feature_usage,
            "form_interactions": form_interactions,
            "ai_interactions": ai_interactions,
            "avg_response_time_ms": avg_response_time,
            "success_rate": self._calculate_success_rate(events)
        }

    def _calculate_success_rate(self, events: List[UserActivityEvent]) -> float:
        """计算成功率"""
        if not events:
            return 0.0

        successful_events = len([e for e in events if e.status_code and e.status_code < 400])
        return successful_events / len(events)

class SystemHealthMonitor:
    """系统健康监控"""

    def __init__(self, db_session, metrics_collector: MetricsCollector):
        self.db_session = db_session
        self.metrics_collector = metrics_collector
        self.logger = logging.getLogger(__name__)
        self.health_checks = {}

    def register_health_check(self, component: str, check_func):
        """注册健康检查函数"""
        self.health_checks[component] = check_func

    async def check_all_components(self) -> Dict[str, Dict[str, Any]]:
        """检查所有组件健康状态"""
        results = {}

        for component, check_func in self.health_checks.items():
            try:
                start_time = time.time()
                is_healthy = await check_func()
                response_time = int((time.time() - start_time) * 1000)

                status = "healthy" if is_healthy else "unhealthy"

                # 记录健康状态到数据库
                health_record = SystemHealth(
                    component=component,
                    status=status,
                    response_time_ms=response_time
                )
                self.db_session.add(health_record)

                # 记录指标
                self.metrics_collector.set_gauge(
                    f"health_{component}",
                    1 if is_healthy else 0,
                    {"component": component}
                )
                self.metrics_collector.record_timer(
                    f"health_check_{component}",
                    response_time,
                    {"component": component}
                )

                results[component] = {
                    "status": status,
                    "response_time_ms": response_time,
                    "timestamp": datetime.utcnow().isoformat()
                }

            except Exception as e:
                self.logger.error(f"Health check failed for {component}: {e}")
                results[component] = {
                    "status": "error",
                    "error": str(e),
                    "timestamp": datetime.utcnow().isoformat()
                }

        self.db_session.commit()
        return results

    async def check_system_resources(self) -> Dict[str, float]:
        """检查系统资源使用情况"""
        try:
            cpu_percent = psutil.cpu_percent(interval=1)
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage('/')

            resources = {
                "cpu_usage": cpu_percent,
                "memory_usage": memory.percent,
                "disk_usage": disk.percent,
                "memory_available_gb": memory.available / (1024**3),
                "disk_free_gb": disk.free / (1024**3)
            }

            # 记录资源使用率指标
            for resource, value in resources.items():
                if 'usage' in resource:
                    self.metrics_collector.set_gauge(f"system_{resource}", value)

            # 更新系统整体健康状态
            overall_status = "healthy"
            if cpu_percent > 80 or memory.percent > 85 or disk.percent > 90:
                overall_status = "degraded"
            if cpu_percent > 95 or memory.percent > 95 or disk.percent > 95:
                overall_status = "unhealthy"

            health_record = SystemHealth(
                component="system",
                status=overall_status,
                cpu_usage=cpu_percent,
                memory_usage=memory.percent,
                disk_usage=disk.percent
            )
            self.db_session.add(health_record)
            self.db_session.commit()

            return resources

        except Exception as e:
            self.logger.error(f"Failed to check system resources: {e}")
            return {}

class AlertManager:
    """告警管理器"""

    def __init__(self, db_session, metrics_collector: MetricsCollector):
        self.db_session = db_session
        self.metrics_collector = metrics_collector
        self.logger = logging.getLogger(__name__)
        self.alert_rules = []
        self.active_alerts = {}

    def add_alert_rule(self, name: str, condition_func: callable, level: AlertLevel,
                      title: str, message_template: str):
        """添加告警规则"""
        rule = {
            "name": name,
            "condition": condition_func,
            "level": level,
            "title": title,
            "message_template": message_template
        }
        self.alert_rules.append(rule)

    async def check_alerts(self):
        """检查告警条件"""
        for rule in self.alert_rules:
            try:
                should_alert = await rule["condition"]()
                alert_id = rule["name"]

                if should_alert and alert_id not in self.active_alerts:
                    # 创建新告警
                    alert = Alert(
                        id=alert_id,
                        level=rule["level"],
                        title=rule["title"],
                        message=rule["message_template"],
                        source="monitoring_system",
                        timestamp=datetime.utcnow()
                    )

                    self.active_alerts[alert_id] = alert
                    self.logger.warning(f"Alert triggered: {alert.title}")

                    # 记录告警指标
                    self.metrics_collector.increment_counter(
                        "alerts_total",
                        tags={"level": alert.level.value, "source": alert.source}
                    )

                elif not should_alert and alert_id in self.active_alerts:
                    # 解决告警
                    alert = self.active_alerts[alert_id]
                    alert.resolved = True

                    self.logger.info(f"Alert resolved: {alert.title}")
                    del self.active_alerts[alert_id]

            except Exception as e:
                self.logger.error(f"Error checking alert rule {rule['name']}: {e}")

    def get_active_alerts(self) -> List[Dict[str, Any]]:
        """获取活跃告警"""
        return [asdict(alert) for alert in self.active_alerts.values()]

class MonitoringService:
    """监控服务主类"""

    def __init__(self, db_session, redis_client=None):
        self.db_session = db_session
        self.metrics_collector = MetricsCollector(redis_client)
        self.user_tracker = UserBehaviorTracker(db_session)
        self.health_monitor = SystemHealthMonitor(db_session, self.metrics_collector)
        self.alert_manager = AlertManager(db_session, self.metrics_collector)
        self.logger = logging.getLogger(__name__)

        # 设置默认告警规则
        self._setup_default_alerts()

        # 注册默认健康检查
        self._setup_default_health_checks()

    def _setup_default_alerts(self):
        """设置默认告警规则"""
        # 高CPU使用率告警
        self.alert_manager.add_alert_rule(
            "high_cpu_usage",
            lambda: self._get_cpu_usage() > 80,
            AlertLevel.WARNING,
            "高CPU使用率",
            "CPU使用率超过80%，当前值: {value}%"
        )

        # 高内存使用率告警
        self.alert_manager.add_alert_rule(
            "high_memory_usage",
            lambda: self._get_memory_usage() > 85,
            AlertLevel.WARNING,
            "高内存使用率",
            "内存使用率超过85%，当前值: {value}%"
        )

        # 错误率告警
        self.alert_manager.add_alert_rule(
            "high_error_rate",
            lambda: self._get_error_rate() > 0.05,
            AlertLevel.ERROR,
            "错误率过高",
            "5分钟内错误率超过5%，当前值: {value}%"
        )

    def _setup_default_health_checks(self):
        """设置默认健康检查"""
        # 数据库连接检查
        self.health_monitor.register_health_check(
            "database",
            self._check_database_health
        )

        # Redis连接检查（如果可用）
        if self.metrics_collector.redis_client:
            self.health_monitor.register_health_check(
                "redis",
                self._check_redis_health
            )

    async def _check_database_health(self) -> bool:
        """检查数据库健康状态"""
        try:
            self.db_session.execute("SELECT 1")
            return True
        except Exception as e:
            self.logger.error(f"Database health check failed: {e}")
            return False

    async def _check_redis_health(self) -> bool:
        """检查Redis健康状态"""
        try:
            self.metrics_collector.redis_client.ping()
            return True
        except Exception as e:
            self.logger.error(f"Redis health check failed: {e}")
            return False

    def _get_cpu_usage(self) -> float:
        """获取当前CPU使用率"""
        try:
            return psutil.cpu_percent(interval=0.1)
        except:
            return 0.0

    def _get_memory_usage(self) -> float:
        """获取当前内存使用率"""
        try:
            return psutil.virtual_memory().percent
        except:
            return 0.0

    def _get_error_rate(self) -> float:
        """获取最近5分钟的错误率"""
        summary = self.metrics_collector.get_metrics_summary("http_requests_total", minutes=5)
        if not summary:
            return 0.0

        # 这里需要根据实际的错误计数指标来计算
        # 暂时返回模拟值
        return 0.0

    async def start_monitoring(self, interval_seconds: int = 30):
        """开始监控"""
        self.logger.info("Starting monitoring service")

        while True:
            try:
                # 检查系统健康状态
                await self.health_monitor.check_all_components()
                await self.health_monitor.check_system_resources()

                # 检查告警
                await self.alert_manager.check_alerts()

                # 记录系统监控指标
                self.metrics_collector.increment_counter("monitoring_cycles")

                await asyncio.sleep(interval_seconds)

            except Exception as e:
                self.logger.error(f"Error in monitoring cycle: {e}")
                await asyncio.sleep(interval_seconds)

    def get_dashboard_data(self) -> Dict[str, Any]:
        """获取仪表板数据"""
        return {
            "metrics_summary": {
                name: self.metrics_collector.get_metrics_summary(name, minutes=5)
                for name in ["http_requests_total", "response_time", "cpu_usage", "memory_usage"]
                if name in self.metrics_collector.metrics
            },
            "active_alerts": self.alert_manager.get_active_alerts(),
            "system_resources": asyncio.run(self.health_monitor.check_system_resources()),
            "timestamp": datetime.utcnow().isoformat()
        }