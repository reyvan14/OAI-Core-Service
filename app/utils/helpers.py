"""
辅助工具函数
"""

import logging
import json
import asyncio
import ipaddress
from typing import Any, Optional
from datetime import datetime
import uuid

logger = logging.getLogger(__name__)

def safe_response(message: str, error_code: str = None, details: str = None) -> dict:
    """创建安全的响应数据"""
    response = {"message": message}

    if error_code:
        response["error_code"] = error_code

    if details:
        response["details"] = details

    # 清理敏感信息
    for key in response:
        if isinstance(response[key], str):
            response[key] = response[key][:500]  # 限制长度

    return response

def get_client_ip() -> str:
    """获取客户端IP地址"""
    try:
        # 这里需要从FastAPI的请求对象中获取
        # 这是一个简化版本，实际使用时需要调整
        return "127.0.0.1"  # 实际应该从request.client.host获取
    except Exception as e:
        logger.warning(f"无法获取客户端IP: {e}")
        return "unknown"

def generate_request_id() -> str:
    """生成唯一的请求ID"""
    return f"{int(datetime.now().timestamp())}_{uuid.uuid4().hex[:8]}"

def format_file_size(size_bytes: int) -> str:
    """格式化文件大小"""
    if size_bytes == 0:
        return "0 B"

    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0

    return f"{size_bytes:.1f} PB"

def extract_amount_from_text(text: str) -> Optional[float]:
    """从文本中提取金额"""
    import re

    # 匹配各种金额格式
    patterns = [
        r'(\d+(?:\.\d+)?)\s*元',  # 123元, 123.45元
        r'(\d+(?:\.\d+)?)\s*万元',  # 123万元, 123.45万元
        r'RMB\s*(\d+(?:\.\d+)?)',  # RMB 123, RMB 123.45
        r'人民币\s*(\d+(?:\.\d+)?)',  # 人民币 123
    ]

    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            amount = float(match.group(1))

            # 如果是万元，转换为元
            if '万' in pattern and '万元' in match.group(0):
                amount *= 10000

            return amount

    return None

def safe_serialize(obj: Any) -> str:
    """安全序列化对象"""
    try:
        return json.dumps(obj, ensure_ascii=False, default=str)
    except Exception as e:
        logger.error(f"序列化对象失败: {e}")
        return "{}"

def safe_deserialize(json_str: str, default: Any = None) -> Any:
    """安全反序列化对象"""
    try:
        return json.loads(json_str)
    except Exception as e:
        logger.error(f"反序列化对象失败: {e}")
        return default

def mask_sensitive_data(data: dict) -> dict:
    """
    掩盖敏感数据
    """
    sensitive_fields = {
        'password', 'token', 'secret', 'key', 'api_key', 'authorization',
        'credit_card', 'bank_account', 'id_number', 'phone_number'
    }

    masked_data = {}
    for key, value in data.items():
        if any(sensitive in key.lower() for sensitive in sensitive_fields):
            if isinstance(value, str) and len(value) > 4:
                # 保留前2位和后2位，中间用*代替
                masked_data[key] = value[:2] + "*" * (len(value) - 4) + value[-2:]
            else:
                masked_data[key] = "*****"
        else:
            masked_data[key] = value

    return masked_data

def validate_ip_address(ip: str) -> bool:
    """验证IP地址格式"""
    try:
        ipaddress.ip_address(ip)
        return True
    except ValueError:
        return False

def is_safe_url(url: str) -> bool:
    """检查URL是否安全"""
    dangerous_patterns = [
        'javascript:', 'data:', 'vbscript:',
        '<script', 'onclick', 'onerror', 'onload',
        '../', '..\\', 'file://'
    ]

    url_lower = url.lower()
    return not any(pattern in url_lower for pattern in dangerous_patterns)

async def run_with_timeout(coro, timeout: float):
    """带超时运行协程"""
    try:
        return await asyncio.wait_for(coro, timeout=timeout)
    except asyncio.TimeoutError:
        logger.error(f"操作超时: {timeout}秒")
        raise TimeoutError(f"操作超时（{timeout}秒）")

def calculate_file_hash(file_path: str, algorithm: str = "md5") -> str:
    """计算文件哈希值"""
    import hashlib

    try:
        hash_algo = getattr(hashlib, algorithm)
        with open(file_path, 'rb') as f:
            return hash_algo(f.read()).hexdigest()
    except Exception as e:
        logger.error(f"计算文件哈希失败: {e}")
        return ""

def truncate_string(text: str, max_length: int = 100) -> str:
    """截断字符串"""
    if len(text) <= max_length:
        return text
    return text[:max_length] + "..."

def generate_traceback() -> str:
    """生成格式化的错误堆栈"""
    import traceback

    return "".join(traceback.format_exc())

class MetricsCollector:
    """性能指标收集器"""

    __instance = None
    __metrics = []

    def __new__(cls):
        if cls.__instance is None:
            cls.__instance = super().__new__(cls)
        return cls.__instance

    def __init__(self):
        self.__metrics = []

    def add_metric(self, name: str, value: float, metadata: dict = None):
        """添加指标"""
        metric = {
            "name": name,
            "value": value,
            "timestamp": datetime.now().isoformat(),
            "metadata": metadata or {}
        }
        self.__metrics.append(metric)

        # 限制指标数量
        if len(self.__metrics) > 10000:
            self.__metrics = self.__metrics[-5000:]

    def get_metrics(self, limit: int = 100) -> list:
        """获取最新的指标"""
        return self.__metrics[-limit:]

    def clear_metrics(self):
        """清除所有指标"""
        self.__metrics = []

# 全局指标收集器实例
metrics_collector = MetricsCollector()