import asyncio
import json
import redis.asyncio as redis
from src.core.config import settings

redis_client = redis.from_url(settings.CELERY_BROKER_URL)

async def dispatch_fork_subagent(task_id: str, task_type: str, bbox: dict, document_id: str):
    """
    Subagent Fork Engine (Isolated Minimal Worker)
    
    This replaces the monolithic Graph state loops. It spawns a fresh pure Python agent / tool runner 
    that only knows about its specific bbox patch.
    """
    print(f"[ForkSubagent] Awakening for task {task_id}. Document: {document_id}, BBox: {bbox}")

    from src.db.session import SessionLocal
    from src.models.document import DocumentMetadata
    db = SessionLocal()
    try:
        doc = db.query(DocumentMetadata).filter(DocumentMetadata.id == document_id).first()
        if not doc:
            await redis_client.publish(
                "xiaoye_sse",
                json.dumps({"task_id": task_id, "patch": f"\n\n**Error:** Document {document_id} not found.\n"})
            )
            return
        pdf_path = doc.real_path
    finally:
        db.close()
    
    # 1. Start streaming to Notebook (UI Update)
    await redis_client.publish(
        "xiaoye_sse",
        json.dumps({
            "task_id": task_id,
            "patch": f"\n\n> 🤖 **Background Agent `[{task_id[:4]}]` Forked** \n> Context: Isolating target bounding box..."
        })
    )
    
    # 2. Setup LLM via Langchain
    if not settings.QWEN_API_KEY:
        await redis_client.publish(
            "xiaoye_sse",
            json.dumps({"task_id": task_id, "patch": "\n\n**Error:** `QWEN_API_KEY` not found in `.env` backend configuration.\n"})
        )
        return

    import os
    os.environ["OPENAI_API_KEY"] = settings.QWEN_API_KEY
    os.environ["OPENAI_API_BASE"] = settings.QWEN_BASE_URL
    # Bypass local proxies to connect directly to Aliyun Dashscope
    for key in ["http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"]:
        os.environ.pop(key, None)
    
    from langchain_openai import ChatOpenAI
    from langchain_core.messages import HumanMessage, SystemMessage
    from src.tools.pdf_cropper import crop_pdf_to_base64_png

    img_b64 = crop_pdf_to_base64_png(pdf_path, bbox.get('pageNumber', 1), bbox)

    await redis_client.publish(
        "xiaoye_sse",
        json.dumps({
            "task_id": task_id,
            "patch": f"\n> Status: Applying Vision LLM (`qwen3-vl-plus` + thinking) to Local PDF Render ({len(img_b64)} bytes Base64)\n\n### VLM Stream Report\n"
        })
    )

    # Claude Pattern: 升级到 Qwen3-VL + thinking
    llm = ChatOpenAI(
        model_name="qwen3-vl-plus",  # 升级到新版VL
        streaming=True,
        max_retries=2,
        api_key=settings.QWEN_API_KEY,
        base_url=settings.QWEN_BASE_URL,
        extra_body={
            "thinking": {"type": "auto"}  # 启用自动 thinking
        }
    )

    prompt = f"""
    Please analyze the following extracted bounding box region from a document:
    - Task Intent: {task_type}
    
    You have been provided with the raw pixels of this bounding box.
    If it's text, perform accurate OCR extraction.
    If it's a chart or figure, provide a highly technical analysis of its axes and trends.
    Answer concisely in Markdown format.
    """
    
    # Prepare the highly complex multimodal message array
    vl_content = [
        {"type": "text", "text": prompt},
        {
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{img_b64}"}
        }
    ]
    
    messages = [
        SystemMessage(content="You are Xiaoye, an expert metallurgy AI visual analyst. Answer directly in markdown format."),
        HumanMessage(content=vl_content)
    ]
    
    full_response = ""
    try:
        async for chunk in llm.astream(messages):
            # Claude Pattern: 区分 thinking 和 content 输出
            # 检查模型是否返回 thinking
            if hasattr(chunk, 'thinking') and chunk.thinking:
                # 流式输出 thinking（标记类型）
                await redis_client.publish(
                    "xiaoye_sse",
                    json.dumps({
                        "task_id": task_id,
                        "type": "reasoning",
                        "thinking": chunk.thinking
                    })
                )
            
            # 输出最终内容
            if chunk.content:
                full_response += chunk.content
                await redis_client.publish(
                    "xiaoye_sse",
                    json.dumps({
                        "task_id": task_id,
                        "type": "content",
                        "patch": chunk.content
                    })
                )

        await redis_client.set(f"xiaoye:chat:{task_id}", full_response)
    except Exception as e:
        await redis_client.publish(
            "xiaoye_sse",
            json.dumps({"task_id": task_id, "patch": f"\n\n**[Connection Error] LLM Stream Interrupted:** {str(e)}\n"})
        )
        
    # Append closing separator
    await redis_client.publish(
        "xiaoye_sse",
        json.dumps({"task_id": task_id, "patch": "\n\n---\n"})
    )
    
    print(f"[ForkSubagent] Task {task_id} gracefully completed and unmounted.")
