"""
Fork Worker — dual-mode subagent dispatcher for Xiaoye Metallurgy AI platform.

Mode 1: analyze_region — direct Chinese VLM analysis with image display.
Mode 2: deep_research  — VLM pre-analysis → retrieval pipeline for deep research.
"""

import base64
import json
import os

import redis.asyncio as redis
from src.core.config import settings
from src.core.logger import setup_logger
from src.tooling.definitions import execute_metallurgy_python

logger = setup_logger("xiaoye.fork")
redis_client = redis.from_url(settings.CELERY_BROKER_URL)

# ---------------------------------------------------------------------------
# VLM Prompt Constants (Chinese)
# ---------------------------------------------------------------------------

SYSTEM_ANALYZE = (
    "你是小冶，一名专业的冶金学视觉分析专家。"
    "请以中文直接输出分析结果，使用Markdown格式。"
)

SYSTEM_DEEP = "你是小冶，一名冶金学视觉分析专家。请以中文简要描述图片的关键信息。"

PROMPT_ANALYZE = """
请用中文详细分析这张冶金学文献中的图片或表格区域：

1. **图片类型**：这是金相图、SEM图、TEM图、XRD图谱、应力-应变曲线、S-N曲线、数据表格，还是其他类型？
2. **关键数据**：提取图中可见的数值、标注、坐标轴含义、图例等
3. **冶金学解读**：基于你看到的微观组织/曲线趋势/数据，给出专业的冶金学分析
4. **研究意义**：该图在该研究中的作用和结论

请仅用中文回答，使用 Markdown 格式组织你的回答。"""

PROMPT_DEEP_RESEARCH = """
请用中文简要描述这张冶金学图片：

1. 图片类型
2. 关键特征或数据（50-100字）
3. 最可能的冶金学含义

请用中文简要回答，不要展开。"""


# ---------------------------------------------------------------------------
# Helper: Save cropped base64 image to disk
# ---------------------------------------------------------------------------


def _save_cropped_image(img_b64: str, task_id: str) -> str:
    """Save cropped base64 PNG to disk, returning the filesystem path."""
    save_dir = "data/cropped_images"
    os.makedirs(save_dir, exist_ok=True)
    img_path = os.path.join(save_dir, f"{task_id}.png")
    with open(img_path, "wb") as f:
        f.write(base64.b64decode(img_b64))
    return img_path


# ---------------------------------------------------------------------------
# Helper: Lookup document in DB — early-exit pattern with SSE error broadcast
# ---------------------------------------------------------------------------


async def _lookup_document(document_id: str, task_id: str):
    """Return ``(doc, pdf_path)`` or ``(None, None)``, publishing SSE error on miss."""
    from src.db.session import SessionLocal
    from src.models.document import DocumentMetadata

    db = SessionLocal()
    try:
        doc = (
            db.query(DocumentMetadata)
            .filter(DocumentMetadata.id == document_id)
            .first()
        )
        if not doc:
            await redis_client.publish(
                "xiaoye_sse",
                json.dumps(
                    {
                        "task_id": task_id,
                        "patch": (
                            f"\n\n**Error:** Document {document_id} not found.\n"
                        ),
                    }
                ),
            )
            return None, None
        return doc, doc.real_path
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Helper: Clear proxies and set OpenAI-compatible env vars for Aliyun Dashscope
# ---------------------------------------------------------------------------


def _setup_llm_environment():
    """Set env vars for Aliyun Dashscope VLM, clearing any proxy settings."""
    os.environ["OPENAI_API_KEY"] = settings.QWEN_API_KEY
    os.environ["OPENAI_API_BASE"] = settings.QWEN_BASE_URL
    for key in [
        "http_proxy",
        "https_proxy",
        "all_proxy",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
    ]:
        os.environ.pop(key, None)


# ---------------------------------------------------------------------------
# Helper: Build VLM messages (image + text)
# ---------------------------------------------------------------------------


def _build_vlm_messages(system_prompt: str, user_prompt: str, img_b64: str) -> list:
    """Build LangChain message list for a multimodal VLM call."""
    from langchain_core.messages import HumanMessage, SystemMessage

    vl_content = [
        {"type": "text", "text": user_prompt},
        {
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{img_b64}"},
        },
    ]
    return [
        SystemMessage(content=system_prompt),
        HumanMessage(content=vl_content),
    ]


# ---------------------------------------------------------------------------
# Helper: Stream VLM response chunks to SSE, returning accumulated text
# ---------------------------------------------------------------------------


async def _stream_vlm_response(llm, messages: list, task_id: str) -> str:
    """Stream VLM output to Redis SSE channel chunk-by-chunk.

    Returns the full accumulated response text.
    """
    full_response = ""
    async for chunk in llm.astream(messages):
        if hasattr(chunk, "thinking") and chunk.thinking:
            await redis_client.publish(
                "xiaoye_sse",
                json.dumps(
                    {
                        "task_id": task_id,
                        "type": "reasoning",
                        "thinking": chunk.thinking,
                    }
                ),
            )
        if chunk.content:
            full_response += chunk.content
            await redis_client.publish(
                "xiaoye_sse",
                json.dumps(
                    {
                        "task_id": task_id,
                        "type": "content",
                        "patch": chunk.content,
                    }
                ),
            )
    return full_response


# ===================================================================
# Mode Handlers
# ===================================================================


async def _handle_analyze_region(task_id: str, img_b64: str):
    """Mode 1 — direct Chinese VLM analysis, streaming result to SSE."""
    from langchain_openai import ChatOpenAI

    await redis_client.publish(
        "xiaoye_sse",
        json.dumps(
            {
                "task_id": task_id,
                "patch": (
                    "\n> Status: Applying Vision LLM (`qwen-vl-max`) to Local PDF Render "
                    f"({len(img_b64)} bytes Base64)\n\n### VLM Stream Report\n"
                ),
            }
        ),
    )

    llm = ChatOpenAI(
        model="qwen-vl-max",
        streaming=True,
        max_retries=2,
        api_key=settings.QWEN_API_KEY,
        base_url=settings.QWEN_BASE_URL,
    )

    messages = _build_vlm_messages(SYSTEM_ANALYZE, PROMPT_ANALYZE, img_b64)

    try:
        full_response = await _stream_vlm_response(llm, messages, task_id)
        await redis_client.set(f"xiaoye:chat:{task_id}", full_response)
    except Exception as e:
        await redis_client.publish(
            "xiaoye_sse",
            json.dumps(
                {
                    "task_id": task_id,
                    "patch": (
                        f"\n\n**[Connection Error] LLM Stream Interrupted:** {e}\n"
                    ),
                }
            ),
        )


async def _handle_deep_research(task_id: str, img_b64: str):
    """Mode 2 — VLM quick analysis → build context → deep retrieval pipeline."""
    from langchain_openai import ChatOpenAI

    llm = ChatOpenAI(
        model="qwen-vl-max",
        streaming=True,
        max_retries=2,
        api_key=settings.QWEN_API_KEY,
        base_url=settings.QWEN_BASE_URL,
    )

    messages = _build_vlm_messages(SYSTEM_DEEP, PROMPT_DEEP_RESEARCH, img_b64)

    # --- Step A: VLM quick analysis ---
    await redis_client.publish(
        "xiaoye_sse",
        json.dumps(
            {
                "task_id": task_id,
                "patch": (
                    "\n> 🔬 **深度科研模式** — VLM 视觉预分析中...\n\n"
                    "### 视觉分析快照\n"
                ),
            }
        ),
    )

    vl_result = ""
    vl_error = False
    try:
        vl_result = await _stream_vlm_response(llm, messages, task_id)
    except Exception as e:
        vl_error = True
        await redis_client.publish(
            "xiaoye_sse",
            json.dumps(
                {
                    "task_id": task_id,
                    "patch": f"\n\n> ⚠️ **VLM 分析暂时不可用**: {e}\n",
                }
            ),
        )

    # --- Step B: Build research context ---
    if vl_error or not vl_result.strip():
        task_description = (
            "[注意：图片分析暂时不可用]\n"
            "用户选中了论文中的一张图/表。请基于知识库文献，搜索可能相关的冶金学知识。\n"
            '如果无法确定具体图片内容，请说明"图片分析不可用，以下是基于文献检索的相关信息"。'
        )
    else:
        task_description = f"""
[视觉分析上下文]
用户选中了论文中的一张图/表区域。经视觉大模型(qwen-vl-max)分析：
{vl_result}

[任务]
基于以上视觉分析结果，结合知识库中的冶金文献资料，深入解释该图/表蕴含的冶金学机理。
请搜索相关资料佐证你的分析，回答需包含具体数据、因果解释和来源引用 [来源: xxx.pdf, p.X]。
"""

    # --- Step C: Run retrieval pipeline ---
    await redis_client.publish(
        "xiaoye_sse",
        json.dumps(
            {
                "task_id": task_id,
                "patch": "\n> 🧠 **启动深度知识库检索...**\n",
            }
        ),
    )

    from src.reasoning.graph import run_worker_pipeline
    from langchain_core.messages import HumanMessage

    payload = {
        "messages": [HumanMessage(content=task_description)],
        "deep_mode": True
    }
    await run_worker_pipeline(payload, task_id)


# ---------------------------------------------------------------------------
# Sandbox Subagent Handling (Mode 3)
# ---------------------------------------------------------------------------

SYSTEM_SANDBOX_AGENT = (
    "你是小冶，一个专业的冶金学计算与科学绘图助手。\n"
    "你的任务是根据用户的需求，生成高质量的 Python 代码来执行冶金学计算、热力学相图模拟或 Matplotlib 绘图，从而回答用户的问题。\n"
    "【重要规范】：\n"
    "1. 绘图必须使用 `matplotlib.pyplot`，并强制使用 `scienceplots` 的学术风格。代码的最开始必须包含：\n"
    "   ```python\n"
    "   import matplotlib.pyplot as plt\n"
    "   import scienceplots\n"
    "   plt.style.use(['science', 'no-latex'])\n"
    "   ```\n"
    "2. 保证图表标签、图例、字体大小适中，且完全是中文或英文学术标签（必须包含单位，如 'Temperature (°C)', 'Tensile Strength (MPa)' 等）。\n"
    "3. 色彩必须搭配美观高雅，不要使用原色（红、绿、蓝），请使用柔和的学术渐变色或 HSL tailormade 配色。\n"
    "4. 你的输出必须有且仅有一个 Python 代码块，格式如下：\n"
    "   ```python\n"
    "   # 你的 Python 代码\n"
    "   ```\n"
    "   请勿添加任何多余的解释文字，只返回该代码块。"
)


async def _handle_sandbox_agent(task_id: str, instruction: str):
    """Mode 3 — sandbox_agent — Async calculation & SciencePlots visualization subagent."""
    from langchain_openai import ChatOpenAI
    from langchain_core.messages import HumanMessage, SystemMessage
    import asyncio

    # ── Step A: Publish start status ──
    await redis_client.publish(
        "xiaoye_sse",
        json.dumps(
            {
                "task_id": task_id,
                "patch": (
                    "\n> ⚙️ **有状态计算沙盒子智能体** — 正在设计计算逻辑与学术配图...\n\n"
                ),
            }
        ),
    )

    llm = ChatOpenAI(
        model="qwen-max",
        streaming=False,
        max_retries=2,
        api_key=settings.QWEN_API_KEY,
        base_url=settings.QWEN_BASE_URL,
    )

    messages = [
        SystemMessage(content=SYSTEM_SANDBOX_AGENT),
        HumanMessage(content=f"用户指令：{instruction}\n\n请直接生成执行此任务的 Python 代码块。")
    ]

    logger.info(f"[{task_id}][qwen-max][执行: sandbox_agent 代码生成][输入: {instruction[:50]}...]")
    try:
        response = await llm.ainvoke(messages)
        code_resp = response.content.strip()
    except Exception as e:
        logger.error(f"[{task_id}][qwen-max][执行: sandbox_agent 代码生成][异常: {e}]")
        await redis_client.publish(
            "xiaoye_sse",
            json.dumps(
                {
                    "task_id": task_id,
                    "patch": f"\n\n**Error [LLM Generation Failed]:** {e}\n"
                }
            ),
        )
        return

    # Extract python code block
    code = ""
    if "```python" in code_resp:
        code = code_resp.split("```python")[1].split("```")[0].strip()
    elif "```" in code_resp:
        code = code_resp.split("```")[1].split("```")[0].strip()
    else:
        code = code_resp

    if not code:
        logger.warning(f"[{task_id}][qwen-max][执行: sandbox_agent 代码生成][异常: 生成代码为空]")
        await redis_client.publish(
            "xiaoye_sse",
            json.dumps(
                {
                    "task_id": task_id,
                    "patch": "\n\n**Error:** LLM 生成的代码为空。\n"
                }
            ),
        )
        return
    logger.info(f"[{task_id}][qwen-max][执行: sandbox_agent 代码生成][结果: 代码长度 {len(code)} 字节]")

    # Ensure pre_inject style is there
    preamble = (
        "import matplotlib.pyplot as plt\n"
        "import scienceplots\n"
        "plt.style.use(['science', 'no-latex'])\n\n"
    )
    if "plt.style.use" not in code:
        full_code = preamble + code
    else:
        full_code = code

    # Publish the code to SSE
    await redis_client.publish(
        "xiaoye_sse",
        json.dumps(
            {
                "task_id": task_id,
                "patch": (
                    f"**正在沙盒中执行以下 Python 代码进行物理计算与绘图：**\n```python\n{full_code}\n```\n\n"
                    "> 🚀 **执行中...**\n"
                ),
            }
        ),
    )

    logger.info(f"[{task_id}][python-sandbox][执行: sandbox 代码运行][代码: {full_code[:100].replace('\n', ' ')}...]")
    try:
        # Run code in thread pool to avoid blocking the main event loop
        result = await asyncio.to_thread(execute_metallurgy_python, full_code)

        logger.info(f"[{task_id}][python-sandbox][执行: sandbox 代码运行][结果: {result[:100].replace('\n', ' ')}...]")
        
        # Clean user-facing output from system image logs
        clean_result = "\n".join([line for line in result.split("\n") if "[System: Sighted an Image" not in line])
        
        # Publish completion output to SSE
        await redis_client.publish(
            "xiaoye_sse",
            json.dumps(
                {
                    "task_id": task_id,
                    "patch": f"\n\n**运行结果输出：**\n\n{clean_result}\n"
                }
            ),
        )
        # Store full execution text in Redis chat memory
        await redis_client.set(f"xiaoye:chat:{task_id}", result)

        # Append subagent clean result to parent session history in Redis
        parent_session_id = task_id.replace("sub_", "")
        parent_history_key = f"xiaoye:chat:{parent_session_id}:history"
        try:
            raw_history = await redis_client.get(parent_history_key)
            if raw_history:
                history = json.loads(raw_history)
                if history and isinstance(history, list):
                    last_turn = history[-1]
                    if "assistant" in last_turn:
                        last_turn["assistant"] += f"\n\n**运行结果输出：**\n\n{clean_result}"
                        await redis_client.set(parent_history_key, json.dumps(history, ensure_ascii=False))
                        logger.info(f"Successfully persisted subagent output to parent session history: {parent_history_key}")
        except Exception as persist_err:
            logger.error(f"Failed to persist subagent output to parent session history: {persist_err}")

    except Exception as e:
        logger.error(f"[{task_id}][python-sandbox][执行: sandbox 代码运行][异常: {e}]")
        await redis_client.publish(
            "xiaoye_sse",
            json.dumps(
                {
                    "task_id": task_id,
                    "patch": f"\n\n**Error [Sandbox Execution Failed]:** {e}\n"
                }
            ),
        )


# ===================================================================
# Main Dispatcher
# ===================================================================


async def dispatch_fork_subagent(
    task_id: str,
    task_type: str,
    bbox: dict | None = None,
    document_id: str | None = None,
    instruction: str | None = None,
):
    """Dual-mode subagent fork engine.

    Routes to ``_handle_analyze_region``, ``_handle_deep_research`` or ``_handle_sandbox_agent``
    based on *task_type*. Bypasses PDF lookup and crop steps for sandbox_agent.
    """
    print(
        f"[ForkSubagent] Awakening for task {task_id}. "
        f"Document: {document_id}, BBox: {bbox}, Type: {task_type}, Instruction: {instruction}"
    )

    # ---- Guard: API key ----
    if not settings.QWEN_API_KEY:
        await redis_client.publish(
            "xiaoye_sse",
            json.dumps(
                {
                    "task_id": task_id,
                    "patch": (
                        "\n\n**Error:** `QWEN_API_KEY` not found in "
                        "`.env` backend configuration.\n"
                    ),
                }
            ),
        )
        return

    _setup_llm_environment()

    # ---- Route sandbox_agent immediately ----
    if task_type == "sandbox_agent":
        await redis_client.publish(
            "xiaoye_sse",
            json.dumps(
                {
                    "type": "fork_start",
                    "task_id": task_id,
                    "patch": "\n> 🧪 **计算沙盒子智能体已启动**\n",
                }
            ),
        )
        await _handle_sandbox_agent(task_id, instruction)
        await redis_client.publish(
            "xiaoye_sse", json.dumps({"task_id": task_id, "patch": "\n\n---\n"})
        )
        print(f"[ForkSubagent] Task {task_id} gracefully completed and unmounted.")
        return

    # ---- Guard: document lookup ----
    _doc, pdf_path = await _lookup_document(document_id, task_id)
    if pdf_path is None:
        return

    # ---- Crop image from PDF ----
    from src.tools.pdf_cropper import crop_pdf_to_base64_png

    try:
        img_b64 = crop_pdf_to_base64_png(pdf_path, bbox.get("pageNumber", 1), bbox)
        _save_cropped_image(img_b64, task_id)
    except Exception as crop_err:
        await redis_client.publish(
            "xiaoye_sse",
            json.dumps(
                {
                    "task_id": task_id,
                    "patch": (
                        f"\n\n**Error:** PDF 文件裁剪失败 — {crop_err}\n"
                        f"文档路径: `{pdf_path}`\n"
                    ),
                }
            ),
        )
        # 发送结束信号，防止前端僵尸任务
        await redis_client.publish(
            "xiaoye_sse", json.dumps({"task_id": task_id, "patch": "\n\n---\n"})
        )
        print(f"[ForkSubagent] Task {task_id} failed at PDF crop: {crop_err}")
        return

    # ---- Publish fork_start SSE event ----
    await redis_client.publish(
        "xiaoye_sse",
        json.dumps(
            {
                "type": "fork_start",
                "task_id": task_id,
                "image_url": f"/api/images/{task_id}.png",
                "patch": f"\n> 📷 **选区截图已捕获** ({len(img_b64)} bytes)\n",
            }
        ),
    )

    # ---- Route by task_type ----
    if task_type == "analyze_region":
        await _handle_analyze_region(task_id, img_b64)
    elif task_type == "deep_research":
        await _handle_deep_research(task_id, img_b64)
    else:
        await redis_client.publish(
            "xiaoye_sse",
            json.dumps(
                {
                    "task_id": task_id,
                    "patch": f"\n\n**Error:** Unknown task_type `{task_type}`.\n",
                }
            ),
        )

    # ---- Closing separator ----
    await redis_client.publish(
        "xiaoye_sse", json.dumps({"task_id": task_id, "patch": "\n\n---\n"})
    )
    print(f"[ForkSubagent] Task {task_id} gracefully completed and unmounted.")
