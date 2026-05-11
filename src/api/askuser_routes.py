"""
AskUser Routes — AI 主动求问断点 API

当 Agent 在对话过程中遇到不确定性时（如缺少关键参数、需要用户确认危险操作），
可以通过 SSE 推送 ask_user 事件暂停执行，等待用户回复后恢复。

数据流：
  1. chat_worker 调用 trigger_ask_user() → 发布 ask_user SSE 事件 + 写入 Redis 待回复队列
  2. 前端收到 ask_user 事件 → 弹出 AskUserModal
  3. 用户回复 → POST /api/v1/ask_user/reply → 写入 Redis
  4. chat_worker 通过 wait_for_user_reply() 轮询 Redis → 收到回复后继续执行
"""

import json
import uuid
from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional, List
import redis.asyncio as redis

from src.core.config import settings

router = APIRouter()

redis_client = redis.from_url(settings.CELERY_BROKER_URL)


class AskUserOption(BaseModel):
    """选择题的选项"""
    label: str
    value: str


class AskUserEvent(BaseModel):
    """AI 发起的求问事件"""
    ask_id: str                             # 唯一 ID
    task_id: str                            # 关联的会话 ID
    question: str                           # 问题文本
    ask_type: str = "confirm"               # 类型: confirm / choice / text
    options: Optional[List[AskUserOption]] = None  # 选择题选项
    default_value: Optional[str] = None     # 默认值
    timeout_seconds: int = 300              # 超时秒数（默认5分钟）


class AskUserReply(BaseModel):
    """用户对求问的回复"""
    ask_id: str
    task_id: str
    reply: str                              # 回复内容（confirm: "yes"/"no", choice: value, text: 自由文本）


@router.post("/ask_user/reply")
async def submit_reply(reply: AskUserReply):
    """
    接收用户对 AI 求问的回复。
    将回复写入 Redis，chat_worker 通过 wait_for_user_reply() 获取。
    """
    reply_key = f"xiaoye:ask_user:{reply.ask_id}:reply"
    async with redis_client as r:
        await r.set(reply_key, json.dumps({
            "reply": reply.reply,
            "task_id": reply.task_id,
        }, ensure_ascii=False))
        # 同时发布通知事件（用于唤醒等待的 worker）
        await r.publish(
            f"xiaoye:ask_user:{reply.ask_id}:notify",
            "replied"
        )

    return {"status": "ok", "message": "回复已提交"}


async def trigger_ask_user(
    task_id: str,
    question: str,
    ask_type: str = "confirm",
    options: Optional[List[dict]] = None,
    default_value: Optional[str] = None,
    timeout_seconds: int = 300,
) -> str:
    """
    Worker 内部调用：触发一个 AskUser 事件，通过 SSE 推送到前端。

    Args:
        task_id:          当前会话 ID
        question:         要问用户的问题
        ask_type:         'confirm' | 'choice' | 'text'
        options:          选择题的选项列表 [{"label": "...", "value": "..."}]
        default_value:    默认值
        timeout_seconds:  超时秒数
    Returns:
        ask_id: 用于后续 wait_for_user_reply 的唯一标识
    """
    ask_id = str(uuid.uuid4())[:8]

    event_data = {
        "task_id": task_id,
        "type": "ask_user",
        "ask_id": ask_id,
        "question": question,
        "ask_type": ask_type,
        "options": options or [],
        "default_value": default_value,
        "timeout_seconds": timeout_seconds,
    }

    r = redis.from_url(settings.CELERY_BROKER_URL)
    async with r:
        await r.publish("xiaoye_sse", json.dumps(event_data, ensure_ascii=False))

    return ask_id


async def wait_for_user_reply(ask_id: str, timeout: int = 300) -> Optional[str]:
    """
    Worker 内部调用：阻塞等待用户回复。

    使用 Redis Pub/Sub 监听通知，避免轮询。
    超时后返回 None。

    Args:
        ask_id:  由 trigger_ask_user 返回的唯一标识
        timeout: 最大等待秒数
    Returns:
        用户的回复文本，超时返回 None
    """
    import asyncio

    r = redis.from_url(settings.CELERY_BROKER_URL)
    async with r:
        pubsub = r.pubsub()
        notify_channel = f"xiaoye:ask_user:{ask_id}:notify"
        await pubsub.subscribe(notify_channel)

        try:
            # 等待通知（或超时）
            end_time = asyncio.get_event_loop().time() + timeout
            while asyncio.get_event_loop().time() < end_time:
                message = await pubsub.get_message(
                    ignore_subscribe_messages=True,
                    timeout=1.0,
                )
                if message and message['type'] == 'message':
                    # 收到通知，读取实际回复
                    reply_key = f"xiaoye:ask_user:{ask_id}:reply"
                    raw = await r.get(reply_key)
                    if raw:
                        data = json.loads(raw)
                        # 清理临时 key
                        await r.delete(reply_key)
                        return data.get("reply")
        finally:
            await pubsub.unsubscribe(notify_channel)

    return None
