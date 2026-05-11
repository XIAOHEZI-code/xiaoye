"""
Delivery Pipeline — 会话管理器

管理用户会话生命周期，提供多用户隔离的基础。
当前实现基于 Redis，每个 task_id 对应一个独立会话。

未来可扩展为：
  - 用户认证 + JWT token 映射
  - 会话过期自动清理
  - 对话历史持久化到 PostgreSQL
"""

import json
from typing import Optional, List, Dict
import redis.asyncio as async_redis
from src.core.config import settings


class SessionManager:
    """会话管理器 — 管理对话历史和 VLM 上下文"""

    def __init__(self, redis_url: Optional[str] = None):
        self.redis_url = redis_url or settings.CELERY_BROKER_URL

    async def get_history(self, task_id: str) -> List[Dict]:
        """获取会话的对话历史"""
        rc = async_redis.from_url(self.redis_url)
        async with rc as r:
            history_key = f"xiaoye:chat:{task_id}:history"
            raw = await r.get(history_key)
            return json.loads(raw) if raw else []

    async def save_history(self, task_id: str, history: List[Dict]):
        """保存会话的对话历史（保留最近 10 轮）"""
        rc = async_redis.from_url(self.redis_url)
        async with rc as r:
            if len(history) > 10:
                history = history[-10:]
            history_key = f"xiaoye:chat:{task_id}:history"
            await r.set(history_key, json.dumps(history, ensure_ascii=False))

    async def get_vlm_context(self, task_id: str) -> Optional[str]:
        """获取 VLM 分析上下文"""
        rc = async_redis.from_url(self.redis_url)
        async with rc as r:
            vlm_key = f"xiaoye:chat:{task_id}"
            raw = await r.get(vlm_key)
            return raw.decode("utf-8") if raw else None

    async def append_and_save(self, task_id: str, user_msg: str, assistant_msg: str,
                               history: List[Dict]):
        """追加消息并保存历史"""
        history.append({"user": user_msg, "assistant": assistant_msg})
        await self.save_history(task_id, history)
