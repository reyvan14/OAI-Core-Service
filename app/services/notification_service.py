"""
消息通知服务
审批提醒、进度通知和多渠道消息推送
"""

import logging
import asyncio
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
from enum import Enum
from collections import defaultdict
import json

logger = logging.getLogger(__name__)


class NotificationType(str, Enum):
    """通知类型"""
    APPROVAL_PENDING = "approval_pending"       # 待审批提醒
    APPROVAL_APPROVED = "approval_approved"     # 审批通过
    APPROVAL_REJECTED = "approval_rejected"     # 审批拒绝
    APPROVAL_REMINDER = "approval_reminder"     # 审批超时提醒
    WORKFLOW_STARTED = "workflow_started"       # 流程开始
    WORKFLOW_COMPLETED = "workflow_completed"   # 流程完成
    SYSTEM_ALERT = "system_alert"              # 系统告警
    TASK_ASSIGNED = "task_assigned"            # 任务分配
    DEADLINE_WARNING = "deadline_warning"       # 截止日期提醒


class NotificationChannel(str, Enum):
    """通知渠道"""
    IN_APP = "in_app"           # 站内消息
    EMAIL = "email"             # 邮件
    SMS = "sms"                 # 短信
    WEBHOOK = "webhook"         # Webhook
    WECHAT = "wechat"          # 微信


class NotificationPriority(str, Enum):
    """通知优先级"""
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


@dataclass
class Notification:
    """通知消息"""
    id: str
    type: NotificationType
    title: str
    content: str
    recipient_id: str
    channels: List[NotificationChannel]
    priority: NotificationPriority
    created_at: str
    read: bool = False
    sent: bool = False
    metadata: Optional[Dict[str, Any]] = None


class NotificationService:
    """消息通知服务"""

    def __init__(self):
        self.notifications: Dict[str, List[Notification]] = defaultdict(list)
        self.notification_count = 0
        self.templates: Dict[str, Dict] = {}
        self.user_preferences: Dict[str, Dict] = {}
        self.pending_reminders: List[Dict] = []

        # 初始化通知模板
        self._initialize_templates()

    def _initialize_templates(self):
        """初始化通知模板"""
        self.templates = {
            NotificationType.APPROVAL_PENDING: {
                "title": "您有新的审批待处理",
                "content": "【{request_type}】{requester_name}提交的申请等待您审批。\n金额: {amount}元\n提交时间: {submit_time}",
                "priority": NotificationPriority.HIGH
            },
            NotificationType.APPROVAL_APPROVED: {
                "title": "您的申请已通过",
                "content": "【{request_type}】您提交的申请已通过审批。\n审批人: {approver_name}\n审批时间: {approve_time}\n备注: {comment}",
                "priority": NotificationPriority.NORMAL
            },
            NotificationType.APPROVAL_REJECTED: {
                "title": "您的申请被拒绝",
                "content": "【{request_type}】您提交的申请未通过审批。\n审批人: {approver_name}\n拒绝原因: {reason}",
                "priority": NotificationPriority.HIGH
            },
            NotificationType.APPROVAL_REMINDER: {
                "title": "审批超时提醒",
                "content": "【{request_type}】申请已等待{waiting_hours}小时未处理。\n申请人: {requester_name}\n请尽快处理。",
                "priority": NotificationPriority.URGENT
            },
            NotificationType.WORKFLOW_STARTED: {
                "title": "流程已启动",
                "content": "【{workflow_name}】流程已启动。\n实例ID: {instance_id}\n启动时间: {start_time}",
                "priority": NotificationPriority.NORMAL
            },
            NotificationType.WORKFLOW_COMPLETED: {
                "title": "流程已完成",
                "content": "【{workflow_name}】流程已完成。\n总耗时: {duration}\n最终状态: {status}",
                "priority": NotificationPriority.NORMAL
            },
            NotificationType.DEADLINE_WARNING: {
                "title": "截止日期提醒",
                "content": "【{task_name}】将于{deadline}截止，请及时处理。\n剩余时间: {remaining}",
                "priority": NotificationPriority.HIGH
            },
            NotificationType.SYSTEM_ALERT: {
                "title": "系统告警",
                "content": "{alert_message}",
                "priority": NotificationPriority.URGENT
            },
            NotificationType.TASK_ASSIGNED: {
                "title": "您有新任务",
                "content": "【{task_name}】已分配给您。\n分配人: {assigner}\n截止日期: {deadline}",
                "priority": NotificationPriority.NORMAL
            }
        }

    async def send_notification(self, notification_type: NotificationType,
                               recipient_id: str,
                               data: Dict[str, Any],
                               channels: Optional[List[NotificationChannel]] = None,
                               priority: Optional[NotificationPriority] = None) -> Dict[str, Any]:
        """发送通知"""
        # 安全检查：验证recipient_id
        if not recipient_id or not isinstance(recipient_id, str):
            return {"success": False, "error": "无效的接收者ID"}

        # 边界检查：限制data大小防止内存攻击
        if len(str(data)) > 10000:
            return {"success": False, "error": "通知数据过大"}

        # 获取模板
        template = self.templates.get(notification_type, {})

        # 格式化内容
        title = template.get("title", "通知")
        content_template = template.get("content", "{message}")

        try:
            # 安全：使用safe格式化，防止注入
            safe_data = {k: str(v)[:500] for k, v in data.items()}
            title = title.format(**safe_data)
            content = content_template.format(**safe_data)
        except KeyError as e:
            logger.warning(f"通知模板格式化失败: {e}")
            content = str(data)[:1000]

        # 确定优先级
        if not priority:
            priority = template.get("priority", NotificationPriority.NORMAL)

        # 确定渠道
        if not channels:
            channels = self._get_user_channels(recipient_id, notification_type)

        # 创建通知
        self.notification_count += 1
        notification_id = f"notif_{self.notification_count}_{datetime.now().strftime('%Y%m%d%H%M%S')}"

        notification = Notification(
            id=notification_id,
            type=notification_type,
            title=title,
            content=content,
            recipient_id=recipient_id,
            channels=channels,
            priority=priority,
            created_at=datetime.now().isoformat(),
            metadata=data
        )

        # 存储通知
        self.notifications[recipient_id].append(notification)

        # 限制存储数量
        if len(self.notifications[recipient_id]) > 1000:
            self.notifications[recipient_id] = self.notifications[recipient_id][-500:]

        # 发送到各渠道
        send_results = await self._send_to_channels(notification)

        notification.sent = all(send_results.values())

        logger.info(f"发送通知: {notification_id} -> {recipient_id}, 类型: {notification_type.value}")

        return {
            "success": True,
            "notification_id": notification_id,
            "recipient": recipient_id,
            "channels": [c.value for c in channels],
            "send_results": send_results,
            "timestamp": notification.created_at
        }

    def _get_user_channels(self, user_id: str,
                          notification_type: NotificationType) -> List[NotificationChannel]:
        """获取用户通知渠道偏好"""
        prefs = self.user_preferences.get(user_id, {})

        # 默认渠道
        default_channels = [NotificationChannel.IN_APP]

        # 紧急通知添加额外渠道
        if notification_type in [NotificationType.APPROVAL_REMINDER,
                                 NotificationType.SYSTEM_ALERT]:
            default_channels.append(NotificationChannel.EMAIL)

        return prefs.get("channels", default_channels)

    async def _send_to_channels(self, notification: Notification) -> Dict[str, bool]:
        """发送通知到各渠道"""
        results = {}

        for channel in notification.channels:
            try:
                if channel == NotificationChannel.IN_APP:
                    results[channel.value] = await self._send_in_app(notification)
                elif channel == NotificationChannel.EMAIL:
                    results[channel.value] = await self._send_email(notification)
                elif channel == NotificationChannel.SMS:
                    results[channel.value] = await self._send_sms(notification)
                elif channel == NotificationChannel.WEBHOOK:
                    results[channel.value] = await self._send_webhook(notification)
                elif channel == NotificationChannel.WECHAT:
                    results[channel.value] = await self._send_wechat(notification)
                else:
                    results[channel.value] = False
            except Exception as e:
                logger.error(f"发送通知失败 {channel.value}: {e}")
                results[channel.value] = False

        return results

    async def _send_in_app(self, notification: Notification) -> bool:
        """发送站内消息"""
        # 站内消息已存储，返回成功
        logger.debug(f"站内消息已存储: {notification.id}")
        return True

    async def _send_email(self, notification: Notification) -> bool:
        """发送邮件 (模拟)"""
        # TODO: 集成真实邮件服务
        logger.info(f"[模拟] 发送邮件给 {notification.recipient_id}: {notification.title}")
        await asyncio.sleep(0.1)  # 模拟发送延迟
        return True

    async def _send_sms(self, notification: Notification) -> bool:
        """发送短信 (模拟)"""
        # TODO: 集成真实短信服务
        logger.info(f"[模拟] 发送短信给 {notification.recipient_id}: {notification.title}")
        await asyncio.sleep(0.1)
        return True

    async def _send_webhook(self, notification: Notification) -> bool:
        """发送Webhook"""
        # TODO: 实现Webhook调用
        logger.info(f"[模拟] 发送Webhook: {notification.id}")
        return True

    async def _send_wechat(self, notification: Notification) -> bool:
        """发送微信消息 (模拟)"""
        # TODO: 集成企业微信API
        logger.info(f"[模拟] 发送微信消息给 {notification.recipient_id}")
        return True

    async def get_user_notifications(self, user_id: str,
                                    unread_only: bool = False,
                                    limit: int = 50) -> List[Dict]:
        """获取用户通知列表"""
        notifications = self.notifications.get(user_id, [])

        if unread_only:
            notifications = [n for n in notifications if not n.read]

        # 按时间倒序
        notifications = sorted(notifications, key=lambda x: x.created_at, reverse=True)

        return [asdict(n) for n in notifications[:limit]]

    async def mark_as_read(self, user_id: str,
                          notification_ids: Optional[List[str]] = None) -> Dict[str, Any]:
        """标记通知为已读"""
        notifications = self.notifications.get(user_id, [])
        marked_count = 0

        for notification in notifications:
            if notification_ids is None or notification.id in notification_ids:
                if not notification.read:
                    notification.read = True
                    marked_count += 1

        return {
            "success": True,
            "marked_count": marked_count,
            "timestamp": datetime.now().isoformat()
        }

    async def get_unread_count(self, user_id: str) -> int:
        """获取未读通知数量"""
        notifications = self.notifications.get(user_id, [])
        return sum(1 for n in notifications if not n.read)

    async def schedule_reminder(self, reminder_type: str,
                               recipient_id: str,
                               data: Dict[str, Any],
                               remind_at: datetime) -> Dict[str, Any]:
        """安排定时提醒"""
        reminder = {
            "id": f"reminder_{len(self.pending_reminders) + 1}",
            "type": reminder_type,
            "recipient_id": recipient_id,
            "data": data,
            "remind_at": remind_at.isoformat(),
            "created_at": datetime.now().isoformat(),
            "sent": False
        }

        self.pending_reminders.append(reminder)

        logger.info(f"安排提醒: {reminder['id']} -> {recipient_id} at {remind_at}")

        return {
            "success": True,
            "reminder_id": reminder["id"],
            "remind_at": remind_at.isoformat()
        }

    async def process_pending_reminders(self) -> Dict[str, Any]:
        """处理待发送的提醒"""
        now = datetime.now()
        sent_count = 0

        for reminder in self.pending_reminders:
            if reminder["sent"]:
                continue

            remind_at = datetime.fromisoformat(reminder["remind_at"])
            if now >= remind_at:
                # 发送提醒
                notification_type = NotificationType.APPROVAL_REMINDER
                if reminder["type"] == "deadline":
                    notification_type = NotificationType.DEADLINE_WARNING

                await self.send_notification(
                    notification_type,
                    reminder["recipient_id"],
                    reminder["data"]
                )

                reminder["sent"] = True
                sent_count += 1

        # 清理已发送的提醒
        self.pending_reminders = [r for r in self.pending_reminders if not r["sent"]]

        return {
            "processed": sent_count,
            "pending": len(self.pending_reminders),
            "timestamp": datetime.now().isoformat()
        }

    async def send_approval_notification(self, approval_id: str,
                                        action: str,
                                        data: Dict[str, Any]) -> Dict[str, Any]:
        """发送审批相关通知"""
        if action == "submit":
            # 通知审批人
            return await self.send_notification(
                NotificationType.APPROVAL_PENDING,
                data.get("approver_id", ""),
                data
            )
        elif action == "approve":
            # 通知申请人
            return await self.send_notification(
                NotificationType.APPROVAL_APPROVED,
                data.get("requester_id", ""),
                data
            )
        elif action == "reject":
            # 通知申请人
            return await self.send_notification(
                NotificationType.APPROVAL_REJECTED,
                data.get("requester_id", ""),
                data
            )

        return {"success": False, "error": "未知操作"}

    async def send_workflow_notification(self, workflow_id: str,
                                        action: str,
                                        data: Dict[str, Any]) -> Dict[str, Any]:
        """发送工作流相关通知"""
        if action == "start":
            return await self.send_notification(
                NotificationType.WORKFLOW_STARTED,
                data.get("initiator_id", ""),
                data
            )
        elif action == "complete":
            return await self.send_notification(
                NotificationType.WORKFLOW_COMPLETED,
                data.get("initiator_id", ""),
                data
            )

        return {"success": False, "error": "未知操作"}

    def set_user_preferences(self, user_id: str, preferences: Dict[str, Any]) -> Dict[str, Any]:
        """设置用户通知偏好"""
        self.user_preferences[user_id] = preferences

        return {
            "success": True,
            "user_id": user_id,
            "preferences": preferences
        }

    def get_notification_stats(self) -> Dict[str, Any]:
        """获取通知统计"""
        total_notifications = sum(len(notifs) for notifs in self.notifications.values())
        total_unread = sum(
            sum(1 for n in notifs if not n.read)
            for notifs in self.notifications.values()
        )

        # 按类型统计
        type_counts = defaultdict(int)
        for notifs in self.notifications.values():
            for n in notifs:
                type_counts[n.type.value] += 1

        return {
            "total_notifications": total_notifications,
            "total_unread": total_unread,
            "total_users": len(self.notifications),
            "pending_reminders": len(self.pending_reminders),
            "by_type": dict(type_counts),
            "timestamp": datetime.now().isoformat()
        }


# 全局实例
notification_service = NotificationService()
