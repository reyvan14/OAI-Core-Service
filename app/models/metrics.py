"""
系统指标和效果评估数据模型 - SQLAlchemy ORM模型
"""

from sqlalchemy import Column, Integer, String, DateTime, Boolean, Float, Text, JSON
from sqlalchemy.sql import func
import uuid

from app.database import Base


class PerformanceMetrics(Base):
    """性能指标表（Agent系统专用）"""
    __tablename__ = "agent_performance_metrics"  # 添加agent_前缀

    id = Column(Integer, primary_key=True, index=True)
    metric_id = Column(String(64), unique=True, index=True, default=lambda: str(uuid.uuid4()))
    metric_name = Column(String(100), nullable=False)
    metric_type = Column(String(50), nullable=False)  # response_time, success_rate, throughput, etc.
    service_name = Column(String(50))  # chat, decision_analysis, data_extraction, etc.

    # 指标值
    value = Column(Float, nullable=False)
    unit = Column(String(20))  # ms, %, requests/sec, etc.

    # 关联信息
    user_id = Column(String(64), index=True)
    session_id = Column(String(64), index=True)
    request_id = Column(String(64), index=True)

    # 额外数据
    metrics_metadata = Column(JSON)
    tags = Column(JSON)  # 标签数组

    created_at = Column(DateTime, default=func.now())


class PainReliefMetrics(Base):
    """痛点缓解效果指标表（Agent系统专用）"""
    __tablename__ = "agent_pain_relief_metrics"  # 添加agent_前缀

    id = Column(Integer, primary_key=True, index=True)
    metric_id = Column(String(64), unique=True, index=True, default=lambda: str(uuid.uuid4()))

    # 关联信息
    user_id = Column(String(64), nullable=False, index=True)
    session_id = Column(String(64), index=True)
    request_id = Column(String(64), index=True)

    # 痛点类型
    pain_point_type = Column(String(50), nullable=False)  # form_complexity, approval_bureaucracy, etc.
    service_type = Column(String(50), nullable=False)  # chat, form_fill, approval, etc.

    # 核心指标
    success_rate = Column(Float, default=0.0)  # 成功率 0-1
    processing_time = Column(Float, default=0.0)  # 处理时间（秒）
    pain_relief_score = Column(Float, default=0.0)  # 痛点缓解评分 0-10
    user_satisfaction = Column(Float, default=0.0)  # 用户满意度 0-10
    error_count = Column(Integer, default=0)  # 错误次数

    # 衍生指标
    time_saved_minutes = Column(Float, default=0.0)  # 节省时间（分钟）
    complexity_reduction = Column(Float, default=0.0)  # 复杂度降低 0-1
    efficiency_gain = Column(Float, default=0.0)  # 效率提升 0-1

    # 反馈数据
    user_rating = Column(Integer)  # 用户评分 1-5
    user_comment = Column(Text)  # 用户评论
    improvement_suggestions = Column(Text)  # 改进建议

    # 对比数据
    baseline_time = Column(Float)  # 基准处理时间
    traditional_method_time = Column(Float)  # 传统方法时间

    created_at = Column(DateTime, default=func.now())


class SystemHealthMetrics(Base):
    """系统健康度指标表（Agent系统专用）"""
    __tablename__ = "agent_system_health_metrics"  # 添加agent_前缀

    id = Column(Integer, primary_key=True, index=True)
    metric_id = Column(String(64), unique=True, index=True, default=lambda: str(uuid.uuid4()))

    # 系统资源指标
    cpu_usage = Column(Float)  # CPU使用率
    memory_usage = Column(Float)  # 内存使用率
    disk_usage = Column(Float)  # 磁盘使用率
    network_io = Column(Float)  # 网络IO

    # 应用指标
    active_sessions = Column(Integer, default=0)  # 活跃会话数
    concurrent_users = Column(Integer, default=0)  # 并发用户数
    requests_per_minute = Column(Float, default=0.0)  # 每分钟请求数

    # AI服务指标
    ai_api_calls = Column(Integer, default=0)  # AI API调用次数
    ai_response_time_avg = Column(Float, default=0.0)  # AI平均响应时间
    ai_success_rate = Column(Float, default=0.0)  # AI成功率

    # 错误指标
    error_rate = Column(Float, default=0.0)  # 错误率
    timeout_rate = Column(Float, default=0.0)  # 超时率

    created_at = Column(DateTime, default=func.now())