"""
日志管理服务
提供日志查询、过滤、导出等功能
"""

import os
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any
from dataclasses import dataclass
from enum import Enum
import json
import gzip


class LogLevel(Enum):
    """日志级别"""
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


@dataclass
class LogEntry:
    """日志条目"""
    timestamp: datetime
    level: str
    module: str
    message: str
    user_id: Optional[str] = None
    request_id: Optional[str] = None
    extra: Optional[Dict[str, Any]] = None


class LogManager:
    """日志管理器"""

    def __init__(self, log_dir: str = "logs"):
        self.log_dir = log_dir
        os.makedirs(log_dir, exist_ok=True)
        self.logger = logging.getLogger(__name__)

    def query_logs(
        self,
        level: Optional[str] = None,
        module: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        keyword: Optional[str] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[LogEntry]:
        """
        查询日志

        Args:
            level: 日志级别过滤
            module: 模块名称过滤
            start_time: 开始时间
            end_time: 结束时间
            keyword: 关键词搜索
            limit: 返回数量限制
            offset: 偏移量

        Returns:
            日志条目列表
        """
        logs = []
        log_files = self._get_log_files(start_time, end_time)

        for log_file in log_files:
            try:
                with open(log_file, 'r', encoding='utf-8') as f:
                    for line in f:
                        entry = self._parse_log_line(line)
                        if entry and self._match_filters(entry, level, module, keyword):
                            logs.append(entry)
            except Exception as e:
                self.logger.error(f"读取日志文件失败 {log_file}: {e}")

        # 按时间倒序排序
        logs.sort(key=lambda x: x.timestamp, reverse=True)

        return logs[offset:offset + limit]

    def get_log_statistics(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """
        获取日志统计信息

        Returns:
            包含各级别日志数量、错误率等统计信息
        """
        stats = {
            "total": 0,
            "by_level": {level.value: 0 for level in LogLevel},
            "error_rate": 0.0,
            "top_errors": [],
            "time_range": {
                "start": start_time.isoformat() if start_time else None,
                "end": end_time.isoformat() if end_time else None
            }
        }

        logs = self.query_logs(start_time=start_time, end_time=end_time, limit=10000)
        stats["total"] = len(logs)

        error_messages = {}

        for log in logs:
            # 统计各级别数量
            if log.level in stats["by_level"]:
                stats["by_level"][log.level] += 1

            # 收集错误信息
            if log.level in ["ERROR", "CRITICAL"]:
                error_messages[log.message] = error_messages.get(log.message, 0) + 1

        # 计算错误率
        if stats["total"] > 0:
            error_count = stats["by_level"]["ERROR"] + stats["by_level"]["CRITICAL"]
            stats["error_rate"] = round(error_count / stats["total"] * 100, 2)

        # 统计最常见的错误
        stats["top_errors"] = [
            {"message": msg, "count": count}
            for msg, count in sorted(error_messages.items(), key=lambda x: x[1], reverse=True)[:10]
        ]

        return stats

    def export_logs(
        self,
        output_path: str,
        level: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        compress: bool = True
    ) -> str:
        """
        导出日志到文件

        Args:
            output_path: 输出文件路径
            level: 日志级别过滤
            start_time: 开始时间
            end_time: 结束时间
            compress: 是否压缩

        Returns:
            导出文件路径
        """
        logs = self.query_logs(
            level=level,
            start_time=start_time,
            end_time=end_time,
            limit=100000
        )

        if compress:
            output_path = output_path + '.gz'
            with gzip.open(output_path, 'wt', encoding='utf-8') as f:
                for log in logs:
                    f.write(self._format_log_entry(log) + '\n')
        else:
            with open(output_path, 'w', encoding='utf-8') as f:
                for log in logs:
                    f.write(self._format_log_entry(log) + '\n')

        return output_path

    def cleanup_old_logs(self, days: int = 30) -> int:
        """
        清理旧日志

        Args:
            days: 保留天数

        Returns:
            删除的文件数量
        """
        cutoff_date = datetime.now() - timedelta(days=days)
        deleted_count = 0

        for filename in os.listdir(self.log_dir):
            filepath = os.path.join(self.log_dir, filename)
            if os.path.isfile(filepath):
                file_time = datetime.fromtimestamp(os.path.getmtime(filepath))
                if file_time < cutoff_date:
                    try:
                        os.remove(filepath)
                        deleted_count += 1
                        self.logger.info(f"删除旧日志: {filename}")
                    except Exception as e:
                        self.logger.error(f"删除日志失败 {filename}: {e}")

        return deleted_count

    def _get_log_files(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None
    ) -> List[str]:
        """获取日志文件列表"""
        log_files = []

        for filename in os.listdir(self.log_dir):
            if filename.endswith('.log'):
                filepath = os.path.join(self.log_dir, filename)

                # 根据时间过滤
                file_time = datetime.fromtimestamp(os.path.getmtime(filepath))
                if start_time and file_time < start_time:
                    continue
                if end_time and file_time > end_time:
                    continue

                log_files.append(filepath)

        return sorted(log_files, reverse=True)

    def _parse_log_line(self, line: str) -> Optional[LogEntry]:
        """解析日志行"""
        try:
            # 假设日志格式: 2025-01-25 12:00:00 - module - LEVEL - message
            parts = line.strip().split(' - ', 3)
            if len(parts) >= 4:
                timestamp = datetime.strptime(parts[0], '%Y-%m-%d %H:%M:%S')
                module = parts[1]
                level = parts[2]
                message = parts[3]

                return LogEntry(
                    timestamp=timestamp,
                    level=level,
                    module=module,
                    message=message
                )
        except Exception as e:
            self.logger.debug(f"解析日志行失败: {e}")

        return None

    def _match_filters(
        self,
        entry: LogEntry,
        level: Optional[str] = None,
        module: Optional[str] = None,
        keyword: Optional[str] = None
    ) -> bool:
        """检查日志条目是否匹配过滤条件"""
        if level and entry.level != level:
            return False

        if module and entry.module != module:
            return False

        if keyword and keyword.lower() not in entry.message.lower():
            return False

        return True

    def _format_log_entry(self, entry: LogEntry) -> str:
        """格式化日志条目"""
        return f"{entry.timestamp.strftime('%Y-%m-%d %H:%M:%S')} - {entry.module} - {entry.level} - {entry.message}"


# 全局日志管理器实例
log_manager = LogManager()
