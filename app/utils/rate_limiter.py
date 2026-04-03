"""
速率限制工具 - 防止API滥用

使用简单的内存式速率限制器，追踪用户请求频率。
"""

import time
import logging
from collections import defaultdict
from typing import Dict, Tuple, Optional
from threading import RLock

logger = logging.getLogger(__name__)


class RateLimiter:
    """简单的内存式速率限制器"""

    def __init__(self, max_requests: int = 10, window_seconds: int = 60):
        """
        初始化速率限制器

        Args:
            max_requests: 时间窗口内允许的最大请求数
            window_seconds: 时间窗口大小（秒）
        """
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        # 存储用户的请求时间戳列表
        self.requests: Dict[str, list] = defaultdict(list)
        self.lock = RLock()

    def is_allowed(self, identifier: str) -> Tuple[bool, int]:
        """
        检查是否允许请求

        Args:
            identifier: 用户/客户端标识符（如user_id或IP地址）

        Returns:
            (是否允许, 剩余重试等待秒数)
            - 如果允许，返回 (True, 0)
            - 如果被限制，返回 (False, 剩余等待秒数)
        """
        with self.lock:
            current_time = time.time()
            user_requests = self.requests[identifier]

            # 移除过期的请求记录
            user_requests[:] = [
                req_time for req_time in user_requests
                if current_time - req_time < self.window_seconds
            ]

            # 检查是否超出限制
            if len(user_requests) >= self.max_requests:
                # 计算剩余等待时间
                oldest_request = user_requests[0]
                retry_after = int(self.window_seconds - (current_time - oldest_request)) + 1
                return False, max(1, retry_after)

            # 记录当前请求
            user_requests.append(current_time)
            return True, 0

    def reset(self, identifier: str) -> None:
        """重置用户的速率限制记录"""
        with self.lock:
            if identifier in self.requests:
                del self.requests[identifier]

    def get_usage(self, identifier: str) -> Dict[str, int]:
        """获取用户的速率限制使用情况"""
        with self.lock:
            current_time = time.time()
            user_requests = self.requests.get(identifier, [])

            # 清理过期请求
            valid_requests = [
                req_time for req_time in user_requests
                if current_time - req_time < self.window_seconds
            ]

            return {
                "used": len(valid_requests),
                "limit": self.max_requests,
                "remaining": max(0, self.max_requests - len(valid_requests)),
                "reset_in_seconds": (
                    int(self.window_seconds - (current_time - valid_requests[0])) + 1
                    if valid_requests else 0
                )
            }


# AI生成请求限制器：每个用户每分钟最多10个请求
ai_generation_limiter = RateLimiter(max_requests=10, window_seconds=60)

# AI优化请求限制器：每个用户每分钟最多20个请求（更宽松）
ai_refinement_limiter = RateLimiter(max_requests=20, window_seconds=60)
