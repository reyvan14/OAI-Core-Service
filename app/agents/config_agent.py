"""
配置管理Agent - 生产实现
专门处理系统配置、个性化设置、权限管理等功能

集成数据库持久化，提供真实的配置管理能力
"""

import json
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime

from app.services.llm_service import LLMService
from app.database import db_manager
from app.models.user import User, UserPreference
from app.models.config import SystemConfig, UserConfig

logger = logging.getLogger(__name__)


class ConfigAgent:
    """配置管理Agent - 生产实现，配置持久化到数据库"""

    def __init__(self, llm_service: Optional[LLMService] = None):
        self.llm_service = llm_service if llm_service else LLMService()
        self.db_manager = db_manager
        # 内存缓存用于快速访问
        self._config_cache: Dict[str, Any] = {}
        self._system_settings_cache: Optional[Dict[str, Any]] = None
        self._cache_ttl = 300  # 缓存5分钟

    async def warm_up(self) -> None:
        """预热Agent - 从数据库加载配置"""
        logger.info("ConfigAgent 预热中...")

        # 验证数据库连接
        health = self.db_manager.health_check()
        if health.get("status") != "healthy":
            logger.warning(f"数据库连接异常: {health}")
        else:
            # 从数据库加载系统配置
            self._system_settings_cache = self._load_system_settings_from_db()
            logger.info("系统配置加载完成")

        logger.info("ConfigAgent 预热完成")

    def _load_system_settings_from_db(self) -> Dict[str, Any]:
        """从数据库加载系统配置"""
        settings = {
            "system_defaults": {
                "working_hours": {"start": "09:00", "end": "18:00"},
                "approval_limits": {"employee": 1000, "manager": 5000, "director": 20000},
                "notification_preferences": {
                    "email_enabled": True,
                    "sms_enabled": False,
                    "push_enabled": True
                }
            },
            "feature_flags": {
                "auto_approval_enabled": True,
                "ocr_processing_enabled": True,
                "advanced_analytics_enabled": True
            }
        }

        with self.db_manager.get_session() as session:
            # 尝试从数据库加载系统配置
            system_configs = session.query(SystemConfig).all()

            for config in system_configs:
                # 解析配置值
                try:
                    if config.config_key.startswith("system_defaults."):
                        key = config.config_key.replace("system_defaults.", "")
                        settings["system_defaults"][key] = json.loads(config.config_value) if config.config_value.startswith("{") else config.config_value
                    elif config.config_key.startswith("feature_flags."):
                        key = config.config_key.replace("feature_flags.", "")
                        settings["feature_flags"][key] = config.config_value.lower() == "true"
                except (json.JSONDecodeError, AttributeError):
                    pass

        return settings

    @property
    def system_settings(self) -> Dict[str, Any]:
        """获取系统配置（带缓存）"""
        if self._system_settings_cache is None:
            self._system_settings_cache = self._load_system_settings_from_db()
        return self._system_settings_cache

    @property
    def config_cache(self) -> Dict[str, Any]:
        """兼容旧接口"""
        return self._config_cache

    @property
    def permission_matrix(self) -> Dict[str, Any]:
        """权限矩阵"""
        return self.system_settings.get("system_defaults", {}).get("approval_limits", {})

    async def get_user_config(self, user_request: Any, analysis: Dict, **kwargs) -> Dict[str, Any]:
        """
        获取用户配置 - 主要入口
        """
        try:
            logger.info(f"获取用户配置: user={getattr(user_request, 'user_id', 'unknown')}")

            # 1. 获取用户信息
            user_info = await self._get_user_info(user_request)

            # 2. 获取用户个性化配置
            user_config = await self._get_user_preferences(user_info["user_id"])

            # 3. 获取权限配置
            permissions = await self._get_user_permissions(user_info)

            # 4. 合并系统默认配置
            merged_config = await self._merge_configs(user_config, permissions)

            # 5. 生成配置建议
            suggestions = await self._generate_config_suggestions(user_info, merged_config)

            return {
                "success": True,
                "user_info": user_info,
                "config": merged_config,
                "suggestions": suggestions,
                "config_updated_at": datetime.now().isoformat()
            }

        except Exception as e:
            logger.error(f"获取用户配置失败: {e}")
            return {
                "success": False,
                "error": str(e),
                "config_updated_at": datetime.now().isoformat()
            }

    async def update_user_config(self, config_data: Dict, user_context: Dict, **kwargs) -> Dict[str, Any]:
        """更新用户配置"""
        try:
            user_id = user_context.get("user_id")

            # 验证配置数据
            validation_result = await self._validate_config_data(config_data)
            if not validation_result["valid"]:
                return {
                    "success": False,
                    "error": f"配置验证失败: {validation_result['errors']}"
                }

            # 更新配置
            await self._save_user_preferences(user_id, config_data)

            # 清除缓存
            cache_key = f"user_config_{user_id}"
            if cache_key in self.config_cache:
                del self.config_cache[cache_key]

            return {
                "success": True,
                "message": "配置更新成功",
                "updated_at": datetime.now().isoformat()
            }

        except Exception as e:
            logger.error(f"更新用户配置失败: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    async def get_system_config(self, **kwargs) -> Dict[str, Any]:
        """获取系统配置"""
        try:
            return {
                "success": True,
                "system_settings": self.system_settings,
                "feature_flags": self.system_settings.get("feature_flags", {}),
                "system_defaults": self.system_settings.get("system_defaults", {}),
                "retrieved_at": datetime.now().isoformat()
            }

        except Exception as e:
            logger.error(f"获取系统配置失败: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    async def _get_user_info(self, user_request: Any) -> Dict[str, Any]:
        """获取用户信息"""
        return {
            "user_id": getattr(user_request, 'user_id', 'unknown'),
            "user_role": getattr(user_request, 'user_role', 'employee'),
            "department": getattr(user_request, 'department', 'unknown'),
            "position": getattr(user_request, 'position', 'unknown'),
            "email": getattr(user_request, 'email', ''),
            "phone": getattr(user_request, 'phone', '')
        }

    async def _get_user_preferences(self, user_id: str) -> Dict[str, Any]:
        """获取用户个性化配置 - 从数据库加载"""
        cache_key = f"user_config_{user_id}"

        # 检查缓存
        if cache_key in self._config_cache:
            return self._config_cache[cache_key]

        # 从数据库获取用户配置
        with self.db_manager.get_session() as session:
            user_pref = session.query(UserPreference).filter(
                UserPreference.user_id == user_id
            ).first()

            if user_pref:
                # 解析存储的偏好设置
                extra_prefs = {}
                if user_pref.preferences_json:
                    try:
                        extra_prefs = json.loads(user_pref.preferences_json)
                    except json.JSONDecodeError:
                        pass

                user_preferences = {
                    "theme": user_pref.theme or "light",
                    "language": user_pref.language or "zh-CN",
                    "timezone": user_pref.timezone or "Asia/Shanghai",
                    "notifications": {
                        "email": user_pref.email_notifications,
                        "push": user_pref.push_notifications,
                        "sms": False
                    },
                    "ai_preferences": {
                        "preferred_model": user_pref.preferred_ai_model,
                        "response_language": user_pref.ai_response_language
                    },
                    "auto_approval_threshold": user_pref.auto_approval_threshold,
                    **extra_prefs
                }
            else:
                # 默认配置
                user_preferences = {
                    "theme": "light",
                    "language": "zh-CN",
                    "timezone": "Asia/Shanghai",
                    "notifications": {
                        "email": True,
                        "push": True,
                        "sms": False
                    },
                    "workflow_preferences": {
                        "auto_save": True,
                        "quick_actions": True,
                        "shortcuts_enabled": True
                    },
                    "dashboard_layout": {
                        "default_view": "overview",
                        "widgets": ["pending_tasks", "recent_forms", "notifications"]
                    }
                }

        # 缓存配置
        self._config_cache[cache_key] = user_preferences
        return user_preferences

    async def _get_user_permissions(self, user_info: Dict) -> Dict[str, Any]:
        """获取用户权限配置"""
        user_role = user_info.get("user_role", "employee")
        department = user_info.get("department", "")

        # 基于角色的权限配置
        role_permissions = {
            "employee": {
                "approval_limit": 1000,
                "can_approve": False,
                "can_view_reports": False,
                "can_manage_users": False
            },
            "manager": {
                "approval_limit": 5000,
                "can_approve": True,
                "can_view_reports": True,
                "can_manage_users": False
            },
            "director": {
                "approval_limit": 20000,
                "can_approve": True,
                "can_view_reports": True,
                "can_manage_users": True
            },
            "admin": {
                "approval_limit": 999999,
                "can_approve": True,
                "can_view_reports": True,
                "can_manage_users": True
            }
        }

        base_permissions = role_permissions.get(user_role, role_permissions["employee"])

        # 部门特定权限
        department_permissions = {}
        if department == "财务部":
            department_permissions = {
                "can_access_finance_reports": True,
                "can_process_refunds": True
            }
        elif department == "技术部":
            department_permissions = {
                "can_access_system_logs": True,
                "can_manage_integrations": True
            }

        return {
            **base_permissions,
            **department_permissions,
            "role": user_role,
            "department": department
        }

    async def _merge_configs(self, user_config: Dict, permissions: Dict) -> Dict[str, Any]:
        """合并用户配置和权限"""
        system_defaults = self.system_settings.get("system_defaults", {})

        return {
            "user_preferences": user_config,
            "permissions": permissions,
            "system_defaults": system_defaults,
            "effective_settings": {
                "working_hours": system_defaults.get("working_hours", {}),
                "approval_limit": permissions.get("approval_limit", 0),
                "notifications": {
                    **system_defaults.get("notification_preferences", {}),
                    **user_config.get("notifications", {})
                }
            }
        }

    async def _generate_config_suggestions(self, user_info: Dict, config: Dict) -> List[str]:
        """生成配置建议"""
        suggestions = []

        user_role = user_info.get("user_role")
        user_preferences = config.get("user_preferences", {})

        # 基于角色的建议
        if user_role == "manager":
            suggestions.append("建议开启审批通知功能，以便及时处理团队申请")
            suggestions.append("可以配置团队仪表板，查看成员工作状态")

        if user_role == "employee":
            suggestions.append("建议设置表格填写快捷方式，提高工作效率")
            suggestions.append("可以开启自动保存功能，避免数据丢失")

        # 基于使用习惯的建议
        if not user_preferences.get("notifications", {}).get("push", True):
            suggestions.append("建议开启推送通知，及时获取重要信息")

        # 基于部门的建议
        department = user_info.get("department")
        if department == "财务部":
            suggestions.append("建议配置财务报表快捷访问，提高审批效率")
        elif department == "技术部":
            suggestions.append("建议配置开发工具集成，提升开发体验")

        return suggestions

    async def _validate_config_data(self, config_data: Dict) -> Dict[str, Any]:
        """验证配置数据"""
        errors = []

        # 检查必需字段
        if "theme" in config_data:
            valid_themes = ["light", "dark", "auto"]
            if config_data["theme"] not in valid_themes:
                errors.append(f"无效的主题设置，可选值: {valid_themes}")

        if "language" in config_data:
            valid_languages = ["zh-CN", "en-US", "ja-JP"]
            if config_data["language"] not in valid_languages:
                errors.append(f"无效的语言设置，可选值: {valid_languages}")

        # 检查通知设置
        if "notifications" in config_data:
            notifications = config_data["notifications"]
            if not isinstance(notifications, dict):
                errors.append("通知设置必须是对象格式")
            else:
                for key in notifications:
                    if key not in ["email", "push", "sms"]:
                        errors.append(f"未知的通知类型: {key}")
                    elif not isinstance(notifications[key], bool):
                        errors.append(f"通知设置 {key} 必须是布尔值")

        return {
            "valid": len(errors) == 0,
            "errors": errors
        }

    async def _save_user_preferences(self, user_id: str, config_data: Dict) -> None:
        """保存用户配置到数据库"""
        with self.db_manager.get_session() as session:
            # 查找或创建用户偏好记录
            user_pref = session.query(UserPreference).filter(
                UserPreference.user_id == user_id
            ).first()

            if not user_pref:
                user_pref = UserPreference(user_id=user_id)
                session.add(user_pref)

            # 更新字段
            if "theme" in config_data:
                user_pref.theme = config_data["theme"]
            if "language" in config_data:
                user_pref.language = config_data["language"]
            if "timezone" in config_data:
                user_pref.timezone = config_data["timezone"]

            # 更新通知设置
            if "notifications" in config_data:
                notifications = config_data["notifications"]
                if "email" in notifications:
                    user_pref.email_notifications = notifications["email"]
                if "push" in notifications:
                    user_pref.push_notifications = notifications["push"]

            # 更新AI偏好
            if "ai_preferences" in config_data:
                ai_prefs = config_data["ai_preferences"]
                if "preferred_model" in ai_prefs:
                    user_pref.preferred_ai_model = ai_prefs["preferred_model"]
                if "response_language" in ai_prefs:
                    user_pref.ai_response_language = ai_prefs["response_language"]

            # 更新自动审批阈值
            if "auto_approval_threshold" in config_data:
                user_pref.auto_approval_threshold = config_data["auto_approval_threshold"]

            # 存储额外的偏好设置
            extra_keys = set(config_data.keys()) - {
                "theme", "language", "timezone", "notifications",
                "ai_preferences", "auto_approval_threshold"
            }
            if extra_keys:
                extra_prefs = {k: config_data[k] for k in extra_keys}
                user_pref.preferences_json = json.dumps(extra_prefs, ensure_ascii=False)

            session.commit()

        # 更新缓存
        cache_key = f"user_config_{user_id}"
        if cache_key in self._config_cache:
            del self._config_cache[cache_key]

        logger.info(f"用户配置已保存到数据库: {user_id}")

    async def get_system_status(self) -> Dict[str, Any]:
        """获取配置Agent状态"""
        db_health = self.db_manager.health_check()

        return {
            "agent_status": "healthy" if db_health.get("status") == "healthy" else "degraded",
            "database_connected": db_health.get("connected", False),
            "config_cache_size": len(self._config_cache),
            "system_settings_loaded": self._system_settings_cache is not None,
            "feature_flags": self.system_settings.get("feature_flags", {}),
            "last_updated": datetime.now().isoformat()
        }

    def invalidate_cache(self, user_id: Optional[str] = None) -> None:
        """
        使缓存失效

        Args:
            user_id: 指定用户ID，None表示清除所有缓存
        """
        if user_id:
            cache_key = f"user_config_{user_id}"
            if cache_key in self._config_cache:
                del self._config_cache[cache_key]
                logger.info(f"用户配置缓存已清除: {user_id}")
        else:
            self._config_cache.clear()
            self._system_settings_cache = None
            logger.info("所有配置缓存已清除")

    def reload_system_settings(self) -> Dict[str, Any]:
        """重新加载系统配置"""
        self._system_settings_cache = self._load_system_settings_from_db()
        return {
            "success": True,
            "settings": self._system_settings_cache,
            "reloaded_at": datetime.now().isoformat()
        }