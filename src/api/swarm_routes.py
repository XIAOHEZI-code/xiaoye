import asyncio
from fastapi import APIRouter, BackgroundTasks, Request
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse
import redis.asyncio as redis

from src.core.config import settings
from src.core.logger import setup_logger

logger = setup_logger("xiaoye.swarm")

router = APIRouter()

# Initialize Redis client for Swarm communications
redis_client = redis.from_url(settings.CELERY_BROKER_URL)

class BBox(BaseModel):
    x0: float
    y0: float
    x1: float
    y1: float
    pageNumber: int

class ForkRequest(BaseModel):
    taskId: str
    documentId: str | None = None
    type: str
    bbox: BBox | None = None
    instruction: str | None = None

async def background_fork_worker(task_req: ForkRequest):
    """
    This intercepts the Fork sub-agent request and dispatches a background pipeline.
    """
    from src.delivery.fork_worker import dispatch_fork_subagent
    
    await dispatch_fork_subagent(
        task_id=task_req.taskId,
        task_type=task_req.type,
        bbox=task_req.bbox.model_dump() if task_req.bbox else None,
        document_id=task_req.documentId,
        instruction=task_req.instruction
    )

@router.post("/fork_agent")
async def fork_agent(request: ForkRequest, background_tasks: BackgroundTasks):
    """
    M3 Event Gateway: Accepts long-running task, immediately returns OK.
    The Background task will spin up the `forkSubagent` logic.
    """
    bbox_info = request.bbox.model_dump() if request.bbox else None
    logger.info(f"Fork Agent Dispatched -> Task: {request.taskId}, Type: {request.type}, BBox: {bbox_info}")
    background_tasks.add_task(background_fork_worker, request)
    return {"status": "ok", "message": "Fork deployed to background."}


@router.get("/notebook/stream")
async def notebook_stream(request: Request):
    """
    SSE stream endpoint for the notebook to receive realtime patches.
    """
    async def event_publisher():
        pubsub = redis_client.pubsub()
        await pubsub.subscribe("xiaoye_sse")
        
        try:
            while True:
                if await request.is_disconnected():
                    break
                
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if message and message['type'] == 'message':
                    yield {
                        "event": "message",
                        "data": message['data'].decode('utf-8') if isinstance(message['data'], bytes) else message['data']
                    }
        except asyncio.CancelledError:
            pass
        finally:
            await pubsub.unsubscribe("xiaoye_sse")

    return EventSourceResponse(event_publisher())
