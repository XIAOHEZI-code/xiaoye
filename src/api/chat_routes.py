from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import Optional
import json

from src.db.session import get_db
from src.models.document import DocumentMetadata
from src.core.logger import setup_logger

logger = setup_logger("xiaoye.chat")

router = APIRouter()


def get_db_session():
    from src.db.session import SessionLocal

    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class ChatRequest(BaseModel):
    task_id: str
    document_id: Optional[str] = None  # Pydantic v2: Optional 才能接收 null
    message: str
    deep_mode: bool = False


async def background_chat_worker(req: ChatRequest, doc_status: str = "knowledge_base"):
    """
    后台对话 Worker 入口。
    委托给 chat_worker.dispatch_chat_worker，实现文献检索增强的三模式回答：
      - VLM 上下文模式（已 Fork 分析过 PDF 区域）
      - RAG 检索模式（search_metallurgy_text 技能 + 知识库）
      - 通用降级模式（Elasticsearch/Neo4j 不可用时）
    """
    try:
        import redis.asyncio as redis
        from src.core.config import settings
        from src.delivery.chat_worker import dispatch_chat_worker
        from src.delivery.session import SessionManager

        session_manager = SessionManager()
        history = await session_manager.get_history(req.task_id)

        await dispatch_chat_worker(
            task_id=req.task_id,
            message=req.message,
            document_id=req.document_id,
            history=history,
            deep_mode=req.deep_mode,
        )
    except Exception as e:
        logger.error(f"Error in background_chat_worker: {e}", exc_info=True)


@router.post("/chat")
async def chat(req: ChatRequest, background_tasks: BackgroundTasks):
    """
    用户对话 API。
    立即返回 202 Accepted，后台异步运行 chat_worker 流水线。
    结果通过 SSE (/api/v1/notebook/stream) 推送给前端。
    """
    from src.db.session import SessionLocal

    db = SessionLocal()
    doc_status = "knowledge_base"

    # 若提供了 document_id，验证其合法性
    logger.info(
        f"Incoming chat request for task {req.task_id} on doc {req.document_id} [deep_mode={req.deep_mode}]: {req.message[:50]}..."
    )
    if req.document_id:
        doc = (
            db.query(DocumentMetadata)
            .filter(DocumentMetadata.id == req.document_id)
            .first()
        )
        if not doc:
            db.close()
            raise HTTPException(
                status_code=403, detail="无效的 document_id，文档不存在"
            )
        doc_status = doc.status
    db.close()

    background_tasks.add_task(background_chat_worker, req, doc_status)
    return {
        "status": "received",
        "message": "对话已提交，Agent 正在检索与思考...",
        "mode": doc_status,
    }


@router.get("/chat/sessions")
async def list_chat_sessions():
    """
    列出所有存储在 Redis 中的对话会话。
    扫描 xiaoye:chat:*:history 键，返回会话列表和摘要。
    """
    import redis.asyncio as redis
    from src.core.config import settings

    try:
        rc = redis.from_url(settings.CELERY_BROKER_URL)
        async with rc as r:
            keys = []
            async for key in r.scan_iter(match="xiaoye:chat:*:history"):
                keys.append(key.decode("utf-8") if isinstance(key, bytes) else key)

            sessions = []
            for key in keys:
                # 提取 task_id: xiaoye:chat:{task_id}:history
                parts = key.split(":")
                if len(parts) >= 4:
                    task_id = parts[2]
                else:
                    continue

                raw = await r.get(key)
                if not raw:
                    continue

                history = json.loads(raw)
                if not history:
                    continue

                # 取最后一条对话作为预览
                last_entry = history[-1]
                preview = last_entry.get("user", "")[:60]

                sessions.append({
                    "task_id": task_id,
                    "message_count": len(history),
                    "preview": preview,
                    "last_user_msg": last_entry.get("user", "")[:100],
                })

            return {"sessions": sessions, "total": len(sessions)}
    except Exception as e:
        logger.error(f"Failed to list chat sessions: {e}")
        return {"sessions": [], "total": 0}


@router.delete("/chat/sessions/{task_id}")
async def delete_chat_session(task_id: str):
    """删除指定的对话会话（Redis 中的历史 + VLM 上下文）"""
    import redis.asyncio as redis
    from src.core.config import settings

    try:
        rc = redis.from_url(settings.CELERY_BROKER_URL)
        async with rc as r:
            await r.delete(f"xiaoye:chat:{task_id}:history")
            await r.delete(f"xiaoye:chat:{task_id}")
        return {"status": "deleted", "task_id": task_id}
    except Exception as e:
        logger.error(f"Failed to delete session {task_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

