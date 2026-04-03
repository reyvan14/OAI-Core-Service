"""
性能指标收集和监控工具
用于收集系统性能、业务指标和痛点缓解效果
"""

import time
import asyncio
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
from functools import wraps
from collections import defaultdict, deque
import json

from app.utils.helpers import metrics_collector

logger = logging.getLogger(__name__)


class PerformanceMetrics:
    """性能指标收集器"""

    def __init__(self):
        self.request_times = deque(maxlen=1000)  # 保留最近1000个请求的时间
        self.request_counts = defaultdict(int)  # 请求计数
        self.error_counts = defaultdict(int)     # 错误计数
        self.agent_performance = defaultdict(list)  # Agent性能数据
        self.business_metrics = defaultdict(dict)   # 业务指标
        self.pain_relief_metrics = []  # 痛点缓解指标

    def record_request_time(self, endpoint: str, duration_ms: float, success: bool = True):
        """记录请求时间"""
        self.request_times.append({
            'endpoint': endpoint,
            'duration_ms': duration_ms,
            'success': success,
            'timestamp': datetime.now().isoformat()
        })

        self.request_counts[endpoint] += 1
        if not success:
            self.error_counts[endpoint] += 1

    def record_agent_performance(self, agent_name: str, tool_name: str,
                               duration_ms: float, success: bool = True,
                               error: str = None):
        """记录Agent性能"""
        performance_data = {
            'agent_name': agent_name,
            'tool_name': tool_name,
            'duration_ms': duration_ms,
            'success': success,
            'error': error,
            'timestamp': datetime.now().isoformat()
        }

        self.agent_performance[agent_name].append(performance_data)

        # 限制每个Agent的性能数据量
        if len(self.agent_performance[agent_name]) > 500:
            self.agent_performance[agent_name] = self.agent_performance[agent_name][-250:]

    def record_pain_relief_metric(self, user_id: str, pain_point: str,
                                time_saved_minutes: float, satisfaction_score: float):
        """记录痛点缓解指标"""
        metric = {
            'user_id': user_id,
            'pain_point': pain_point,
            'time_saved_minutes': time_saved_minutes,
            'satisfaction_score': satisfaction_score,
            'relief_score': min(1.0, time_saved_minutes / 30.0),  # 假设30分钟为完全缓解
            'timestamp': datetime.now().isoformat()
        }

        self.pain_relief_metrics.append(metric)

        # 限制指标数据量
        if len(self.pain_relief_metrics) > 10000:
            self.pain_relief_metrics = self.pain_relief_metrics[-5000:]

    def calculate_endpoint_statistics(self, endpoint: str, time_window_minutes: int = 5) -> Dict[str, Any]:
        """计算端点统计信息"""
        cutoff_time = datetime.now() - timedelta(minutes=time_window_minutes)

        # 过滤时间窗口内的请求
        recent_requests = [
            req for req in self.request_times
            if req['endpoint'] == endpoint and
               datetime.fromisoformat(req['timestamp']) > cutoff_time
        ]

        if not recent_requests:
            return {
                'endpoint': endpoint,
                'time_window_minutes': time_window_minutes,
                'request_count': 0,
                'average_response_time_ms': 0,
                'success_rate': 1.0,
                'requests_per_minute': 0
            }

        # 计算统计数据
        response_times = [req['duration_ms'] for req in recent_requests]
        success_count = sum(1 for req in recent_requests if req['success'])

        return {
            'endpoint': endpoint,
            'time_window_minutes': time_window_minutes,
            'request_count': len(recent_requests),
            'average_response_time_ms': sum(response_times) / len(response_times),
            'min_response_time_ms': min(response_times),
            'max_response_time_ms': max(response_times),
            'success_rate': success_count / len(recent_requests),
            'requests_per_minute': len(recent_requests) / time_window_minutes,
            'error_rate': (len(recent_requests) - success_count) / len(recent_requests)
        }

    def calculate_agent_statistics(self, agent_name: str) -> Dict[str, Any]:
        """计算Agent统计信息"""
        if agent_name not in self.agent_performance:
            return {
                'agent_name': agent_name,
                'total_executions': 0,
                'average_response_time_ms': 0,
                'success_rate': 1.0,
                'error_distribution': {}
            }

        performances = self.agent_performance[agent_name]

        if not performances:
            return {
                'agent_name': agent_name,
                'total_executions': 0,
                'average_response_time_ms': 0,
                'success_rate': 1.0,
                'error_distribution': {}
            }

        # 计算统计数据
        response_times = [p['duration_ms'] for p in performances if p['success']]
        success_count = sum(1 for p in performances if p['success'])

        # 错误分布
        error_distribution = defaultdict(int)
        for p in performances:
            if not p['success'] and p['error']:
                error_distribution[p['error']] += 1

        return {
            'agent_name': agent_name,
            'total_executions': len(performances),
            'successful_executions': success_count,
            'average_response_time_ms': sum(response_times) / len(response_times) if response_times else 0,
            'success_rate': success_count / len(performances),
            'error_distribution': dict(error_distribution),
            'last_execution': performances[-1]['timestamp'] if performances else None
        }

    def calculate_pain_relief_summary(self, time_window_hours: int = 24) -> Dict[str, Any]:
        """计算痛点缓解效果汇总"""
        cutoff_time = datetime.now() - timedelta(hours=time_window_hours)

        # 过滤时间窗口内的数据
        recent_metrics = [
            m for m in self.pain_relief_metrics
            if datetime.fromisoformat(m['timestamp']) > cutoff_time
        ]

        if not recent_metrics:
            return {
                'time_window_hours': time_window_hours,
                'total_users_helped': 0,
                'average_time_saved_minutes': 0,
                'average_satisfaction_score': 0,
                'overall_relief_score': 0,
                'pain_point_breakdown': {}
            }

        # 按痛点类型分组
        pain_point_groups = defaultdict(list)
        for metric in recent_metrics:
            pain_point_groups[metric['pain_point']].append(metric)

        # 计算总体统计
        total_time_saved = sum(m['time_saved_minutes'] for m in recent_metrics)
        total_satisfaction = sum(m['satisfaction_score'] for m in recent_metrics)
        total_relief_score = sum(m['relief_score'] for m in recent_metrics)
        unique_users = len(set(m['user_id'] for m in recent_metrics))

        # 痛点类型分解
        pain_point_breakdown = {}
        for pain_point, metrics in pain_point_groups.items():
            pain_point_breakdown[pain_point] = {
                'count': len(metrics),
                'total_time_saved': sum(m['time_saved_minutes'] for m in metrics),
                'average_time_saved': sum(m['time_saved_minutes'] for m in metrics) / len(metrics),
                'average_satisfaction': sum(m['satisfaction_score'] for m in metrics) / len(metrics),
                'average_relief_score': sum(m['relief_score'] for m in metrics) / len(metrics)
            }

        return {
            'time_window_hours': time_window_hours,
            'total_users_helped': unique_users,
            'total_interactions': len(recent_metrics),
            'average_time_saved_minutes': total_time_saved / len(recent_metrics),
            'average_satisfaction_score': total_satisfaction / len(recent_metrics),
            'overall_relief_score': total_relief_score / len(recent_metrics),
            'pain_point_breakdown': pain_point_breakdown
        }

    def get_system_overview(self) -> Dict[str, Any]:
        """获取系统概览指标"""
        # 最近5分钟的请求统计
        recent_request_stats = self.calculate_endpoint_statistics('all', 5)

        # Agent性能概览
        agent_overview = {}
        for agent_name in self.agent_performance.keys():
            agent_overview[agent_name] = self.calculate_agent_statistics(agent_name)

        # 痛点缓解效果
        pain_relief_summary = self.calculate_pain_relief_summary(24)

        # 计算系统健康评分
        health_score = self._calculate_health_score(recent_request_stats, agent_overview)

        return {
            'timestamp': datetime.now().isoformat(),
            'system_health_score': health_score,
            'recent_performance': recent_request_stats,
            'agent_overview': agent_overview,
            'pain_relief_impact': pain_relief_summary,
            'total_requests_processed': len(self.request_times),
            'total_agent_executions': sum(len(perfs) for perfs in self.agent_performance.values()),
            'total_pain_relief_interactions': len(self.pain_relief_metrics)
        }

    def _calculate_health_score(self, request_stats: Dict, agent_overview: Dict) -> float:
        """计算系统健康评分 (0-100)"""
        score = 100.0

        # 请求成功率影响 (权重: 30%)
        success_rate = request_stats.get('success_rate', 1.0)
        score -= (1.0 - success_rate) * 30

        # 响应时间影响 (权重: 20%)
        avg_response_time = request_stats.get('average_response_time_ms', 0)
        if avg_response_time > 2000:  # 超过2秒
            score -= min(20, (avg_response_time - 2000) / 100)

        # Agent成功率影响 (权重: 30%)
        if agent_overview:
            agent_success_rates = [agent.get('success_rate', 1.0) for agent in agent_overview.values()]
            avg_agent_success = sum(agent_success_rates) / len(agent_success_rates)
            score -= (1.0 - avg_agent_success) * 30

        # 错误率影响 (权重: 20%)
        error_rate = request_stats.get('error_rate', 0)
        score -= error_rate * 20

        return max(0.0, min(100.0, score))


# 全局性能指标实例
performance_metrics = PerformanceMetrics()


def monitor_performance(func):
    """性能监控装饰器"""
    @wraps(func)
    async def wrapper(*args, **kwargs):
        start_time = time.time()
        function_name = func.__name__

        try:
            result = await func(*args, **kwargs)
            success = True
            error = None
        except Exception as e:
            success = False
            error = str(e)
            logger.error(f"Function {function_name} failed: {e}")
            raise
        finally:
            duration_ms = (time.time() - start_time) * 1000

            # 记录性能指标
            performance_metrics.record_request_time(function_name, duration_ms, success)

            # 记录到全局指标收集器
            metrics_collector.add_metric(
                name=f"function_execution_time",
                value=duration_ms,
                metadata={
                    "function": function_name,
                    "success": success,
                    "error": error
                }
            )

        return result

    return wrapper


def monitor_agent_performance(agent_name: str, tool_name: str):
    """Agent性能监控装饰器"""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            start_time = time.time()

            try:
                result = await func(*args, **kwargs)
                success = True
                error = None
            except Exception as e:
                success = False
                error = str(e)
                logger.error(f"Agent {agent_name}.{tool_name} failed: {e}")
                raise
            finally:
                duration_ms = (time.time() - start_time) * 1000

                # 记录Agent性能
                performance_metrics.record_agent_performance(
                    agent_name, tool_name, duration_ms, success, error
                )

            return result

        return wrapper
    return decorator


async def collect_and_report_metrics():
    """定期收集和报告指标"""
    while True:
        try:
            # 获取系统概览
            overview = performance_metrics.get_system_overview()

            # 记录关键指标到日志
            logger.info(f"系统健康评分: {overview['system_health_score']:.1f}/100")
            logger.info(f"总请求数: {overview['total_requests_processed']}")
            logger.info(f"Agent执行次数: {overview['total_agent_executions']}")

            # 记录痛点缓解效果
            pain_impact = overview['pain_relief_impact']
            if pain_impact['total_users_helped'] > 0:
                logger.info(f"24小时内帮助用户: {pain_impact['total_users_helped']}人")
                logger.info(f"平均节省时间: {pain_impact['average_time_saved_minutes']:.1f}分钟")
                logger.info(f"用户满意度: {pain_impact['average_satisfaction_score']:.1f}/5.0")

            # 清理旧数据（保留7天）
            cutoff_time = datetime.now() - timedelta(days=7)

            # 清理请求时间数据
            performance_metrics.request_times = deque(
                (req for req in performance_metrics.request_times
                 if datetime.fromisoformat(req['timestamp']) > cutoff_time),
                maxlen=1000
            )

            # 清理痛点缓解指标
            performance_metrics.pain_relief_metrics = [
                m for m in performance_metrics.pain_relief_metrics
                if datetime.fromisoformat(m['timestamp']) > cutoff_time
            ]

        except Exception as e:
            logger.error(f"指标收集报告失败: {e}")

        # 每10分钟收集一次
        await asyncio.sleep(600)


# 启动指标收集任务
def start_metrics_collection():
    """启动指标收集后台任务"""
    asyncio.create_task(collect_and_report_metrics())
    logger.info("性能指标收集任务已启动")