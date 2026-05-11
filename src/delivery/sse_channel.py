"""
Delivery Pipeline — SSE 推送统一抽象层

将所有分散在各模块中的 Redis PubSub 推送逻辑统一收口到此处。
任何管线需要推送 SSE 事件，都通过此模块的 SSEChannel 接口。

好处：
  1. 消除 tools.py / chat_worker.py / upload_routes.py 中重复的 Redis 推送代码
  2. 统一事件格式和错误处理
  3. 便于未来替换推送后端（如 WebSocket）
"""

import json
from typing import Any, Optional


class SSEChannel:
    """统一的 SSE 推送通道"""

    def __init__(self, channel_name: str = "xiaoye_sse"):
        self.channel_name = channel_name

    def publish(self, event_type: str, data: dict):
        """
        同步发布 SSE 事件到 Redis PubSub。

        Args:
            event_type: 事件类型标识
            data:       事件数据字典
        """
        try:
            import redis as sync_redis
            from src.core.config import settings
            rc = sync_redis.from_url(settings.CELERY_BROKER_URL)
            payload = {"type": event_type, **data}
            rc.publish(self.channel_name, json.dumps(payload, ensure_ascii=False))
            rc.close()
        except Exception as e:
            print(f"[SSEChannel] Publish failed (non-fatal): {e}")

    async def async_publish(self, event_type: str, data: dict):
        """
        异步发布 SSE 事件到 Redis PubSub。

        Args:
            event_type: 事件类型标识
            data:       事件数据字典
        """
        try:
            import redis.asyncio as async_redis
            from src.core.config import settings
            rc = async_redis.from_url(settings.CELERY_BROKER_URL)
            payload = {"type": event_type, **data}
            async with rc as r:
                await r.publish(self.channel_name, json.dumps(payload, ensure_ascii=False))
        except Exception as e:
            print(f"[SSEChannel] Async publish failed (non-fatal): {e}")

    def publish_chat_patch(self, task_id: str, patch: str):
        """推送聊天内容增量补丁（快捷方法）"""
        self.publish("chat_patch", {"task_id": task_id, "patch": patch})

    async def async_publish_chat_patch(self, task_id: str, patch: str):
        """异步推送聊天内容增量补丁"""
        try:
            import redis.asyncio as async_redis
            from src.core.config import settings
            rc = async_redis.from_url(settings.CELERY_BROKER_URL)
            async with rc as r:
                await r.publish(self.channel_name, json.dumps({
                    "task_id": task_id,
                    "patch": patch,
                }, ensure_ascii=False))
        except Exception as e:
            print(f"[SSEChannel] Async chat patch failed (non-fatal): {e}")


# 全局单例
_global_channel: Optional[SSEChannel] = None


def get_sse_channel() -> SSEChannel:
    """获取全局 SSE 通道单例"""
    global _global_channel
    if _global_channel is None:
        _global_channel = SSEChannel()
    return _global_channel
