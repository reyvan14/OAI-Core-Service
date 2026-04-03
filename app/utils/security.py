"""
安全工具模块
提供认证、授权、加密等安全功能
"""

import re
import bleach
import secrets
import hashlib
from typing import Any, Dict, Optional, List
from functools import wraps
import logging
from datetime import datetime, timedelta

# 尝试导入安全相关库
try:
    import jwt
    from passlib.context import CryptContext
    JWT_AVAILABLE = True
except ImportError:
    JWT_AVAILABLE = False
    logger = logging.getLogger(__name__)
    logger.warning("JWT库未安装，某些安全功能将不可用")

logger = logging.getLogger(__name__)

class InputValidator:
    """输入验证器"""

    # 危险模式
    XSS_PATTERN = re.compile(r'<[^>]*>', re.IGNORECASE)
    SQL_INJECTION_PATTERN = re.compile(r'(?i)(union|select|insert|update|delete|drop|alter|create|exec)', re.IGNORECASE)
    SCRIPT_PATTERN = re.compile(r'javascript:|onclick|onerror|onload', re.IGNORECASE)
    PATH_TRAVERSAL_PATTERN = re.compile(r'\.\./|\.\.', re.IGNORECASE)

    @classmethod
    def sanitize_text(cls, text: str) -> str:
        """清理文本，移除潜在危险内容"""
        if not isinstance(text, str):
            return ""

        # 长度检查
        if len(text) > 10000:
            raise ValueError("输入文本过长")

        # HTML清理
        text = bleach.clean(text)

        # SQL注入检查
        if cls.SQL_INJECTION_PATTERN.search(text):
            raise ValueError("输入包含潜在的SQL注入风险")

        # 脚本注入检查
        if cls.SCRIPT_PATTERN.search(text):
            raise ValueError("输入包含脚本注入风险")

        # 路径遍历检查
        if cls.PATH_TRAVERSAL_PATTERN.search(text):
            raise ValueError("输入包含路径遍历风险")

        return text.strip()

    @classmethod
    def validate_user_input(cls, message: str) -> str:
        """验证用户输入"""
        try:
            return cls.sanitize_text(message)
        except ValueError as e:
            logger.warning(f"用户输入验证失败: {e}")
            raise ValueError(f"输入不安全：{str(e)}")

def validate_request_data(func):
    """请求数据验证装饰器"""
    @wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            # 检查参数数量
            if len(args) > 10:  # 限制参数数量
                raise ValueError("参数数量过多")

            # 检查参数类型和值
            for arg in args:
                if isinstance(arg, str):
                    InputValidator.validate_user_input(arg)
                elif isinstance(arg, dict):
                    for key, value in arg.items():
                        if isinstance(value, str):
                            InputValidator.validate_user_input(value)

            return await func(*args, **kwargs)
        except Exception as e:
            logger.error(f"请求验证失败: {e}")
            raise ValueError(f"请求验证失败: {str(e)}")

    return wrapper


# 安全管理器类（如果JWT库可用）
if JWT_AVAILABLE:
    # 密码加密上下文
    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

    # JWT配置
    JWT_SECRET_KEY = secrets.token_urlsafe(32)
    JWT_ALGORITHM = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES = 30

    class SecurityManager:
        """安全管理器"""

        def __init__(self):
            self.failed_login_attempts: Dict[str, List[datetime]] = {}
            self.max_attempts = 5
            self.lockout_duration = timedelta(minutes=15)
            self.jwt_secret_key = JWT_SECRET_KEY

        def hash_password(self, password: str) -> str:
            """对密码进行加密"""
            return pwd_context.hash(password)

        def verify_password(self, plain_password: str, hashed_password: str) -> bool:
            """验证密码"""
            return pwd_context.verify(plain_password, hashed_password)

        def is_account_locked(self, identifier: str) -> bool:
            """检查账户是否被锁定"""
            if identifier not in self.failed_login_attempts:
                return False

            # 清理过期的失败记录
            now = datetime.now()
            self.failed_login_attempts[identifier] = [
                attempt_time for attempt_time in self.failed_login_attempts[identifier]
                if now - attempt_time < self.lockout_duration
            ]

            # 删除空记录
            if not self.failed_login_attempts[identifier]:
                del self.failed_login_attempts[identifier]
                return False

            return len(self.failed_login_attempts[identifier]) >= self.max_attempts

        def record_failed_attempt(self, identifier: str):
            """记录失败登录尝试"""
            if identifier not in self.failed_login_attempts:
                self.failed_login_attempts[identifier] = []
            self.failed_login_attempts[identifier].append(datetime.now())
            logger.warning(f"记录失败登录尝试: {identifier}, 总次数: {len(self.failed_login_attempts[identifier])}")

        def clear_failed_attempts(self, identifier: str):
            """清除失败登录记录"""
            if identifier in self.failed_login_attempts:
                del self.failed_login_attempts[identifier]

        def create_access_token(self, data: Dict[str, Any]) -> str:
            """创建访问令牌"""
            to_encode = data.copy()
            expire = datetime.utcnow() + timedelta(minutes=JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
            to_encode.update({"exp": expire})
            return jwt.encode(to_encode, self.jwt_secret_key, algorithm=JWT_ALGORITHM)

        def verify_token(self, token: str) -> Optional[Dict[str, Any]]:
            """验证令牌"""
            try:
                payload = jwt.decode(token, self.jwt_secret_key, algorithms=[JWT_ALGORITHM])
                return payload
            except jwt.ExpiredSignatureError:
                logger.warning("令牌已过期")
                return None
            except jwt.JWTError as e:
                logger.warning(f"令牌验证失败: {e}")
                return None

        def generate_session_id(self) -> str:
            """生成安全的会话ID"""
            return secrets.token_urlsafe(32)

        def generate_csrf_token(self) -> str:
            """生成CSRF令牌"""
            return secrets.token_urlsafe(32)

        def validate_csrf_token(self, token: str, expected_token: str) -> bool:
            """验证CSRF令牌"""
            return secrets.compare_digest(token, expected_token)

    # 创建全局安全管理器实例
    security_manager = SecurityManager()
else:
    class SecurityManager:
        """安全管理器（简化版）"""
        def __init__(self):
            pass

        def generate_session_id(self) -> str:
            """生成会话ID"""
            return secrets.token_urlsafe(32)

        def generate_csrf_token(self) -> str:
            """生成CSRF令牌"""
            return secrets.token_urlsafe(32)

        def validate_csrf_token(self, token: str, expected_token: str) -> bool:
            """验证CSRF令牌"""
            return secrets.compare_digest(token, expected_token)

    security_manager = SecurityManager()


def hash_data(data: str, salt: Optional[str] = None) -> str:
    """对数据进行哈希处理"""
    if salt is None:
        salt = secrets.token_hex(16)

    combined = f"{salt}{data}"
    return f"{salt}${hashlib.sha256(combined.encode()).hexdigest()}"


def verify_hashed_data(data: str, hashed_data: str) -> bool:
    """验证哈希数据"""
    try:
        salt, hash_value = hashed_data.split('$')
        combined = f"{salt}{data}"
        return hashlib.sha256(combined.encode()).hexdigest() == hash_value
    except ValueError:
        return False


def detect_sql_injection(input_string: str) -> bool:
    """检测SQL注入模式"""
    sql_patterns = [
        r'(\bUNION\b.*\bSELECT\b)',
        r'(\bSELECT\b.*\bFROM\b)',
        r'(\bINSERT\b.*\bINTO\b)',
        r'(\bUPDATE\b.*\bSET\b)',
        r'(\bDELETE\b.*\bFROM\b)',
        r'(\bDROP\b.*\bTABLE\b)',
        r'(\bCREATE\b.*\bTABLE\b)',
        r'(\bALTER\b.*\bTABLE\b)',
        r'(\'\s*;\s*)',
        r'(--\s*$)',
        r'(/\*.*\*/)',
        r'(\bOR\b\s*\d+\s*=\s*\d+)',
        r'(\bAND\b\s*\d+\s*=\s*\d+)',
        r'(\'\s*OR\s*\'.*\'\s*=\s*\'.*\')',
        r'(\"\s*OR\s*\".*\"\s*=\s*\".*\")',
    ]

    for pattern in sql_patterns:
        if re.search(pattern, input_string, re.IGNORECASE):
            logger.warning(f"检测到SQL注入模式: {input_string[:100]}")
            return True

    return False


def sanitize_filename(filename: str) -> str:
    """清理文件名"""
    # 移除危险字符
    cleaned = re.sub(r'[<>:"/\\|?*]', '', filename)

    # 移除控制字符
    cleaned = re.sub(r'[\x00-\x1f\x7f]', '', cleaned)

    # 移除前后的点和空格
    cleaned = cleaned.strip('. ')

    # 确保文件名不为空
    if not cleaned:
        cleaned = "unnamed_file"

    return cleaned[:255]  # 限制长度


def validate_file_path(file_path: str) -> bool:
    """验证文件路径，防止路径遍历攻击"""
    # 规范化路径
    normalized_path = re.sub(r'[\\/]+', '/', file_path)

    # 检查危险模式
    dangerous_patterns = [
        r'\.\.',           # 路径遍历
        r'^/',             # 绝对路径
        r'^\w:',           # Windows驱动器路径
        r'^\./',           # 相对路径
    ]

    for pattern in dangerous_patterns:
        if re.search(pattern, normalized_path):
            logger.warning(f"检测到危险文件路径: {file_path}")
            return False

    return True


def log_security_event(event_type: str, details: Dict[str, Any], severity: str = "warning"):
    """记录安全事件"""
    log_message = f"安全事件: {event_type} - {details}"
    if severity == "critical":
        logger.critical(log_message)
    elif severity == "warning":
        logger.warning(log_message)
    else:
        logger.info(log_message)


def check_rate_limit(identifier: str, limit: int, window_minutes: int = 1) -> bool:
    """检查速率限制（简单内存实现，生产环境应使用Redis）"""
    now = datetime.now()
    window_start = now - timedelta(minutes=window_minutes)

    # 使用内存存储（生产环境建议使用Redis）
    key = f"rate_limit:{identifier}"

    if not hasattr(check_rate_limit, '_rate_limits'):
        check_rate_limit._rate_limits = {}

    if key not in check_rate_limit._rate_limits:
        check_rate_limit._rate_limits[key] = []

    # 清理过期记录
    check_rate_limit._rate_limits[key] = [
        timestamp for timestamp in check_rate_limit._rate_limits[key]
        if timestamp > window_start
    ]

    # 检查是否超过限制
    if len(check_rate_limit._rate_limits[key]) >= limit:
        logger.warning(f"速率限制触发: {identifier}, 限制: {limit}/{window_minutes}分钟")
        return False

    # 记录当前请求
    check_rate_limit._rate_limits[key].append(now)
    return True


# ============================================================================
# API密钥加密管理
# ============================================================================

class SecretManager:
    """
    密钥管理器 - 使用Fernet对称加密
    用于安全存储API密钥等敏感信息
    """

    def __init__(self):
        import os
        try:
            from cryptography.fernet import Fernet
        except ImportError:
            logger.error("cryptography库未安装，无法使用密钥加密功能")
            logger.error("请运行: pip install cryptography")
            raise

        # 从环境变量获取加密密钥
        secret_key = os.getenv("ENCRYPTION_KEY")

        if not secret_key:
            # 生产环境必须设置
            if os.getenv("ENV") == "production":
                raise ValueError("生产环境必须设置ENCRYPTION_KEY环境变量")

            # 开发环境生成临时密钥并警告
            logger.warning("⚠️  未设置ENCRYPTION_KEY环境变量，使用临时密钥（仅开发环境）")
            logger.warning("   生产环境请设置: export ENCRYPTION_KEY=$(python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')")
            secret_key = Fernet.generate_key().decode()

        try:
            self.cipher = Fernet(secret_key.encode() if isinstance(secret_key, str) else secret_key)
        except Exception as e:
            logger.error(f"加密器初始化失败: {e}")
            raise

    def encrypt(self, plaintext: Optional[str]) -> Optional[str]:
        """
        加密明文

        Args:
            plaintext: 明文字符串

        Returns:
            加密后的密文（Base64编码）
        """
        if not plaintext:
            return None

        try:
            encrypted = self.cipher.encrypt(plaintext.encode())
            return encrypted.decode()
        except Exception as e:
            logger.error(f"加密失败: {e}")
            # 不抛出异常，返回None表示加密失败
            return None

    def decrypt(self, ciphertext: Optional[str]) -> Optional[str]:
        """
        解密密文

        Args:
            ciphertext: 密文（Base64编码）

        Returns:
            解密后的明文
        """
        if not ciphertext:
            return None

        try:
            decrypted = self.cipher.decrypt(ciphertext.encode())
            return decrypted.decode()
        except Exception as e:
            logger.error(f"解密失败: {e}")
            # 不抛出异常，返回None表示解密失败
            return None

    def mask_secret(self, secret: Optional[str], visible_chars: int = 4) -> Optional[str]:
        """
        部分隐藏密钥（用于显示）

        Args:
            secret: 原始密钥
            visible_chars: 首尾可见字符数

        Returns:
            部分隐藏的密钥，如 "sk-1234...xyz9"
        """
        if not secret:
            return None

        if len(secret) <= visible_chars * 2:
            return "***"

        return f"{secret[:visible_chars]}...{secret[-visible_chars:]}"


# 全局密钥管理器实例（延迟初始化）
_secret_manager = None


def get_secret_manager() -> SecretManager:
    """获取全局密钥管理器实例"""
    global _secret_manager
    if _secret_manager is None:
        _secret_manager = SecretManager()
    return _secret_manager