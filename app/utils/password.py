"""
密码工具模块
使用bcrypt进行密码加密和验证
"""
import bcrypt


def hash_password(password: str) -> str:
    """
    加密密码

    Args:
        password: 明文密码

    Returns:
        str: bcrypt加密后的密码hash
    """
    # 生成salt并加密
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
    return hashed.decode('utf-8')


def verify_password(password: str, password_hash: str) -> bool:
    """
    验证密码

    Args:
        password: 明文密码
        password_hash: 加密后的密码hash

    Returns:
        bool: 密码是否正确
    """
    try:
        return bcrypt.checkpw(password.encode('utf-8'), password_hash.encode('utf-8'))
    except Exception:
        return False


def generate_default_password() -> str:
    """
    生成默认密码

    Returns:
        str: 默认密码（明文）
    """
    return "Welcome123!"
