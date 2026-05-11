"""
Ingestion Status Tracker — 入库进度追踪与 SSE 推送

管线每一步完成后通过 Redis PubSub 推送进度事件到前端，
前端可实时展示入库进度条。

事件格式:
  {
    "type": "ingestion_progress",
    "doc_id": "xxx",
    "stage": "parsing|chunking|figures|indexing|completed|failed",
    "message": "描述文本"
  }
"""

import json
from enum import Enum
from typing import Optional


class IngestionStage(str, Enum):
    """入库管线阶段枚举"""
    STARTED = "started"
    PARSING = "parsing"
    CHUNKING = "chunking"
    FIGURES = "figures"
    INDEXING = "indexing"
    COMPLETED = "completed"
    FAILED = "failed"


class StatusTracker:
    """入库进度追踪器，通过 Redis PubSub 推送 SSE 事件"""

    def __init__(self, doc_id: str):
        self.doc_id = doc_id

    def emit(self, stage: IngestionStage, message: str = ""):
        """
        发送入库进度事件到 Redis PubSub。

        Args:
            stage:   当前阶段
            message: 进度描述
        """
        try:
            import redis as sync_redis
            from src.core.config import settings
            rc = sync_redis.from_url(settings.CELERY_BROKER_URL)
            rc.publish("xiaoye_sse", json.dumps({
                "type": "ingestion_progress",
                "doc_id": self.doc_id,
                "stage": stage.value,
                "message": message,
            }, ensure_ascii=False))
            rc.close()
        except Exception as e:
            # SSE 推送失败不阻断入库流程
            print(f"[StatusTracker] SSE push failed (non-fatal): {e}")
