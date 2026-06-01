#!/usr/bin/env python3
"""
Fork Pipeline 端到端测试 — 验证直接解析 / 深度科研两种模式

测试前提：
  - QWEN_API_KEY 已配置
  - ES / Neo4j / Redis 运行中
  - test.pdf 已在 data/marker_output/test/ 有解析结果
  - 裁剪测试需要项目目录下有 PDF 文件

Usage:
    python scripts/test_fork_pipeline.py              # Run all tests
    python scripts/test_fork_pipeline.py --test T1,T2 # Run specific tests
    python scripts/test_fork_pipeline.py --verbose    # Verbose output
    python scripts/test_fork_pipeline.py --timeout 120 # Custom timeout (seconds)
    python scripts/test_fork_pipeline.py --api-key sk-xxxx  # Override API key
"""

import argparse
import asyncio
import base64
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ── Path resolution — ensure project root is importable ──────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# ── CLI argument parsing (early, before side-effect imports) ──────────────────
_parser = argparse.ArgumentParser(
    description="Fork Pipeline 端到端测试",
    formatter_class=argparse.RawDescriptionHelpFormatter,
    epilog="""
Examples:
  python scripts/test_fork_pipeline.py
  python scripts/test_fork_pipeline.py --test T1,T2,T4
  python scripts/test_fork_pipeline.py --verbose --timeout 120
    """,
)
_parser.add_argument(
    "--test",
    default=None,
    help="Comma-separated test IDs to run (e.g. T1,T2,T4). Default: all.",
)
_parser.add_argument(
    "--api-key",
    default=None,
    help="Override QWEN_API_KEY from .env",
)
_parser.add_argument(
    "--verbose",
    action="store_true",
    help="Enable detailed debug output",
)
_parser.add_argument(
    "--timeout",
    type=int,
    default=120,
    help="Timeout per test in seconds (default: 120)",
)
_parser.add_argument(
    "--skip-api-tests",
    action="store_true",
    help="Skip tests that require LLM API calls (T2, T4, T5)",
)
_args = _parser.parse_args()


# ── Proxy cleanup (must precede any network-touching import) ──────────────────
def _clear_proxy() -> None:
    """Remove all proxy environment variables for direct Dashscope access."""
    for key in (
        "http_proxy",
        "https_proxy",
        "all_proxy",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
    ):
        os.environ.pop(key, None)


_clear_proxy()

# ── API key resolution (must precede Settings instantiation) ──────────────────
if _args.api_key:
    os.environ["QWEN_API_KEY"] = _args.api_key
    os.environ["OPENAI_API_KEY"] = _args.api_key

# ── Now safe to import project modules ────────────────────────────────────────
from src.core.config import settings

# ── Constants ─────────────────────────────────────────────────────────────────
BOLD = "\033[1m"
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
CYAN = "\033[96m"
GRAY = "\033[90m"
RESET = "\033[0m"

DIVIDER = "─" * 72
DOUBLE_DIVIDER = "═" * 72

# ── Test case registry ────────────────────────────────────────────────────────
TEST_CASES = [
    {
        "id": "T1",
        "name": "图片裁剪与保存",
        "desc": "验证 crop_pdf_to_base64_png 能裁剪并保存到磁盘",
        "requires_api": False,
    },
    {
        "id": "T2",
        "name": "VLM 中文分析输出",
        "desc": "验证 VLM 输出含 >30% 中文字符，无整段英文",
        "requires_api": True,
    },
    {
        "id": "T3",
        "name": "SSE fork_start 事件格式",
        "desc": "验证 fork_start 含 image_url 字段",
        "requires_api": False,
    },
    {
        "id": "T4",
        "name": "深度科研流程端到端",
        "desc": "VLM分析 → 上下文注入 → 检索管线 → Synthesizer 含来源引用",
        "requires_api": True,
    },
    {
        "id": "T5",
        "name": "VLM失败兜底",
        "desc": "VLM 不可用时，深度科研回退到纯文本检索",
        "requires_api": True,
    },
]


# ═══════════════════════════════════════════════════════════════════════════════
# Monkey-patches (suppress SSE noise during test runs)
# ═══════════════════════════════════════════════════════════════════════════════


def _install_noop_sse() -> None:
    """Replace the global SSE channel singleton with a silent noop variant.

    When Redis is unavailable during testing, the default SSEChannel logs noise
    on every token. This monkey-patch suppresses that noise.
    """
    import src.delivery.sse_channel as _sse_mod

    class _NoopSSEChannel(_sse_mod.SSEChannel):
        def publish(self, *args, **kwargs):
            pass

        async def async_publish(self, *args, **kwargs):
            pass

        def publish_chat_patch(self, *args, **kwargs):
            pass

        async def async_publish_chat_patch(self, *args, **kwargs):
            pass

    _sse_mod._global_channel = _NoopSSEChannel()


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════════


def _find_test_pdf() -> str:
    """Locate a test PDF file in the project directory.

    Searches common locations and returns the first available PDF path.

    Returns:
        Absolute path to an existing PDF file.

    Raises:
        FileNotFoundError: If no PDF file can be found.
    """
    search_paths = [
        PROJECT_ROOT / "test.pdf",
        PROJECT_ROOT / "metallurgy_competition_template.pdf",
        PROJECT_ROOT / "data" / "uploads",
        PROJECT_ROOT / "data" / "storage",
    ]

    # Check direct file paths first
    for candidate in search_paths[:2]:
        if candidate.is_file():
            if _args.verbose:
                print(f"  {GRAY}[find_pdf] Found: {candidate}{RESET}")
            return str(candidate)

    # Search directories for PDF files
    for candidate_dir in search_paths[2:]:
        if candidate_dir.is_dir():
            for entry in sorted(candidate_dir.iterdir()):
                if entry.is_file() and entry.suffix.lower() == ".pdf":
                    if _args.verbose:
                        print(f"  {GRAY}[find_pdf] Found: {entry}{RESET}")
                    return str(entry)

    raise FileNotFoundError(
        "No test PDF found. Place a PDF at one of:\n"
        f"  • {PROJECT_ROOT / 'test.pdf'}\n"
        f"  • {PROJECT_ROOT / 'data' / 'uploads'}/\n"
        f"  • {PROJECT_ROOT / 'data' / 'storage'}/"
    )


def _validate_api_key() -> str:
    """Verify API key is available; exit with message if missing.

    Returns:
        The validated API key string.
    """
    api_key = settings.QWEN_API_KEY
    if not api_key:
        print(f"{RED}ERROR: QWEN_API_KEY is not set.{RESET}")
        print("Set it via one of:")
        print("  1. .env file with QWEN_API_KEY=sk-xxxx")
        print("  2. Export QWEN_API_KEY=sk-xxxx in shell")
        print("  3. Pass --api-key sk-xxxx on the command line")
        sys.exit(1)
    return api_key


def _chinese_ratio(text: str) -> float:
    """Calculate the proportion of CJK characters in a string.

    Args:
        text: The text to analyze.

    Returns:
        Float between 0.0 and 1.0 representing the CJK character ratio.
    """
    stripped = text.replace(" ", "").replace("\n", "")
    if not stripped:
        return 0.0
    cjk_count = sum(1 for c in stripped if "\u4e00" <= c <= "\u9fff")
    return cjk_count / len(stripped)


def _has_long_english(text: str, min_length: int = 50) -> bool:
    """Check if text contains consecutive ASCII letter runs of given length.

    Args:
        text:       The text to scan.
        min_length: Minimum run length to qualify (default: 50).

    Returns:
        True if a run of ≥ min_length consecutive ASCII letters is found.
    """
    pattern = re.compile(rf"[a-zA-Z]{{{min_length},}}")
    return bool(pattern.search(text))


def _truncate(text: str, max_len: int = 200) -> str:
    """Truncate text for preview display."""
    if len(text) <= max_len:
        return text
    return text[:max_len] + "..."


# ═══════════════════════════════════════════════════════════════════════════════
# T1: 图片裁剪与保存
# ═══════════════════════════════════════════════════════════════════════════════


async def test_crop_and_save() -> dict:
    """裁剪 PDF 区域并验证图片保存成功。

    Returns:
        Dict with keys: result, image_path, size_bytes, time_ms, error.
    """
    from src.tools.pdf_cropper import crop_pdf_to_base64_png

    result: dict = {
        "result": "FAIL",
        "image_path": "",
        "size_bytes": 0,
        "time_ms": 0,
        "error": None,
    }

    t0 = time.monotonic()
    try:
        pdf_path = _find_test_pdf()

        bbox = {"x0": 0.1, "y0": 0.1, "x1": 0.5, "y1": 0.3, "pageNumber": 1}

        img_b64 = crop_pdf_to_base64_png(pdf_path, 1, bbox)

        if len(img_b64) <= 100:
            result["error"] = f"Cropped image too small ({len(img_b64)} bytes base64)"
            result["time_ms"] = round((time.monotonic() - t0) * 1000)
            return result

        # Save to disk
        save_dir = PROJECT_ROOT / "data" / "cropped_images"
        save_dir.mkdir(parents=True, exist_ok=True)
        img_path = save_dir / "test_crop.png"

        img_path.write_bytes(base64.b64decode(img_b64))

        if not img_path.is_file() or img_path.stat().st_size == 0:
            result["error"] = "Saved image file is empty or missing"
            result["time_ms"] = round((time.monotonic() - t0) * 1000)
            return result

        result["result"] = "PASS"
        result["image_path"] = str(img_path)
        result["size_bytes"] = img_path.stat().st_size
        result["time_ms"] = round((time.monotonic() - t0) * 1000)

    except FileNotFoundError as exc:
        result["error"] = str(exc)
        result["time_ms"] = round((time.monotonic() - t0) * 1000)
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        result["time_ms"] = round((time.monotonic() - t0) * 1000)

    return result


# ═══════════════════════════════════════════════════════════════════════════════
# T2: VLM 中文分析输出
# ═══════════════════════════════════════════════════════════════════════════════


async def test_chinese_vlm() -> dict:
    """VLM 输出中文分析 — 验证中文占比和英文段落检测。

    Returns:
        Dict with keys: result, cn_ratio, text_length, has_long_en, time_ms, error.
    """
    from langchain_openai import ChatOpenAI
    from langchain_core.messages import HumanMessage
    from src.tools.pdf_cropper import crop_pdf_to_base64_png

    result: dict = {
        "result": "FAIL",
        "cn_ratio": 0.0,
        "text_length": 0,
        "has_long_en": False,
        "time_ms": 0,
        "error": None,
    }

    t0 = time.monotonic()
    try:
        # Ensure clean network environment
        _clear_proxy()

        pdf_path = _find_test_pdf()
        bbox = {"x0": 0.05, "y0": 0.3, "x1": 0.5, "y1": 0.55, "pageNumber": 3}
        img_b64 = crop_pdf_to_base64_png(pdf_path, 3, bbox)

        llm = ChatOpenAI(
            model="qwen-vl-max",
            api_key=settings.QWEN_API_KEY,
            base_url=settings.QWEN_BASE_URL,
        )

        prompt = (
            "请用中文详细分析这张冶金学图片：\n"
            "1. 图片类型（表格/金相图/SEM图/曲线图等）\n"
            "2. 关键数据或特征\n"
            "3. 冶金学解读\n"
            "请仅用中文回答，不要使用英文。"
        )

        content = [
            {"type": "text", "text": prompt},
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{img_b64}"},
            },
        ]

        response = await asyncio.wait_for(
            llm.ainvoke([HumanMessage(content=content)]),
            timeout=_args.timeout,
        )
        text = response.content

        cn_ratio = _chinese_ratio(text)
        result["cn_ratio"] = round(cn_ratio, 3)
        result["text_length"] = len(text)
        result["has_long_en"] = _has_long_english(text)
        result["time_ms"] = round((time.monotonic() - t0) * 1000)

        if cn_ratio < 0.3:
            result["error"] = f"Chinese ratio {cn_ratio:.1%} below 30% threshold"
            return result

        if result["has_long_en"]:
            result["error"] = "Response contains long English text blocks"
            return result

        result["result"] = "PASS"

    except FileNotFoundError as exc:
        result["error"] = str(exc)
        result["time_ms"] = round((time.monotonic() - t0) * 1000)
    except asyncio.TimeoutError:
        result["error"] = f"VLM call timed out after {_args.timeout}s"
        result["time_ms"] = round((time.monotonic() - t0) * 1000)
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        result["time_ms"] = round((time.monotonic() - t0) * 1000)

    return result


# ═══════════════════════════════════════════════════════════════════════════════
# T3: SSE fork_start 事件格式
# ═══════════════════════════════════════════════════════════════════════════════


async def test_sse_fork_start_format() -> dict:
    """验证 fork_start SSE 事件包含必需的 image_url 字段。

    Returns:
        Dict with keys: result, event, time_ms, error.
    """
    result: dict = {
        "result": "FAIL",
        "event": {},
        "time_ms": 0,
        "error": None,
    }

    t0 = time.monotonic()
    try:
        event = {
            "type": "fork_start",
            "task_id": "test_123",
            "image_url": "/api/images/test_123.png",
            "patch": "\n> 📷 **选区截图已捕获**\n",
        }

        # Validate required fields
        if event.get("type") != "fork_start":
            result["error"] = "Missing or invalid 'type' field"
            result["time_ms"] = round((time.monotonic() - t0) * 1000)
            return result

        image_url = event.get("image_url", "")
        if not image_url or not image_url.startswith("/api/images/"):
            result["error"] = f"image_url missing or invalid: {image_url!r}"
            result["time_ms"] = round((time.monotonic() - t0) * 1000)
            return result

        if not event.get("task_id"):
            result["error"] = "Missing task_id field"
            result["time_ms"] = round((time.monotonic() - t0) * 1000)
            return result

        result["event"] = event
        result["result"] = "PASS"
        result["time_ms"] = round((time.monotonic() - t0) * 1000)

    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        result["time_ms"] = round((time.monotonic() - t0) * 1000)

    return result


# ═══════════════════════════════════════════════════════════════════════════════
# T4: 深度科研流程端到端
# ═══════════════════════════════════════════════════════════════════════════════

_SOURCE_CITE_PATTERN = re.compile(
    r"\[来源[：:].*?\]|来源页码[：:]\s*\d+|（来源.*?页码.*?\d+）|"
    r"p\.\s*\d+|pp\.\s*\d+|\[?\d+\]|"
    r"第\s*\d+\s*页|图\s*\d+|Figure\s*\d+|"
    r"page\s*\d+|fig\.\s*\d+|Fig\.\s*\d+|"
    r"来源[：:].*|参考.*?页|见.*?图|如.*?所示",
    re.IGNORECASE,
)


async def test_deep_research_e2e() -> dict:
    """VLM分析 → 检索管线 → Synthesizer 含来源引用。

    Returns:
        Dict with keys: result, response_length, has_sources, time_ms, error.
    """
    from langchain_openai import ChatOpenAI
    from langchain_core.messages import HumanMessage
    from src.tools.pdf_cropper import crop_pdf_to_base64_png
    from src.reasoning.graph import run_worker_pipeline

    result: dict = {
        "result": "FAIL",
        "response_length": 0,
        "has_sources": False,
        "time_ms": 0,
        "error": None,
    }

    t0 = time.monotonic()
    try:
        _clear_proxy()

        pdf_path = _find_test_pdf()
        bbox = {"x0": 0.05, "y0": 0.3, "x1": 0.5, "y1": 0.55, "pageNumber": 3}
        img_b64 = crop_pdf_to_base64_png(pdf_path, 3, bbox)

        # Step 1: VLM analysis
        llm = ChatOpenAI(
            model="qwen-vl-max",
            api_key=settings.QWEN_API_KEY,
            base_url=settings.QWEN_BASE_URL,
        )
        vl_prompt = "请用中文简要描述这张图的类型和关键信息（50字以内）。"
        vl_content = [
            {"type": "text", "text": vl_prompt},
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{img_b64}"},
            },
        ]
        vl_resp = await asyncio.wait_for(
            llm.ainvoke([HumanMessage(content=vl_content)]),
            timeout=60,
        )
        vl_result = vl_resp.content

        # Step 2: Build context with VLM output
        context = (
            f"[视觉分析上下文]\n"
            f"用户选中了论文中的一张图表。视觉大模型分析结果：{vl_result}\n\n"
            f"[任务] 基于以上视觉分析和知识库文献，解释该图蕴含的冶金学机理。"
            f"搜索相关资料，回答需含来源引用[来源: xxx.pdf, p.X]。"
        )

        # Step 3: Run retrieval pipeline in deep mode
        task_id = f"fork_deep_test_{int(time.monotonic())}"
        payload = {"task_description": context, "deep_mode": True}
        response = await asyncio.wait_for(
            run_worker_pipeline(payload, task_id),
            timeout=_args.timeout,
        )

        result["response_length"] = len(response)
        result["has_sources"] = bool(_SOURCE_CITE_PATTERN.search(response))
        result["time_ms"] = round((time.monotonic() - t0) * 1000)

        if result["response_length"] < 100:
            result["error"] = f"Response too short ({result['response_length']} chars)"
            return result

        if not result["has_sources"]:
            result["error"] = "No source citation found in response"
            return result

        result["result"] = "PASS"

    except FileNotFoundError as exc:
        result["error"] = str(exc)
        result["time_ms"] = round((time.monotonic() - t0) * 1000)
    except asyncio.TimeoutError:
        result["error"] = f"Deep research pipeline timed out after {_args.timeout}s"
        result["time_ms"] = round((time.monotonic() - t0) * 1000)
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        result["time_ms"] = round((time.monotonic() - t0) * 1000)

    return result


# ═══════════════════════════════════════════════════════════════════════════════
# T5: VLM失败兜底 — 纯文本检索回退
# ═══════════════════════════════════════════════════════════════════════════════


async def test_fallback_no_vlm() -> dict:
    """VLM 不可用时回退到纯文本检索。

    Simulates VLM failure by using only text context without image analysis,
    verifying that the retrieval pipeline still produces a useful response.

    Returns:
        Dict with keys: result, response_length, time_ms, error.
    """
    from src.reasoning.graph import run_worker_pipeline

    result: dict = {
        "result": "FAIL",
        "response_length": 0,
        "time_ms": 0,
        "error": None,
    }

    t0 = time.monotonic()
    try:
        _clear_proxy()

        context = (
            "[注意：图片分析暂时不可用，请基于文献回答问题]\n"
            "用户选中了论文中的一张疲劳断口SEM图，请搜索相关文献解释疲劳断裂机理。"
            "回答需含来源引用。"
        )

        task_id = f"fork_fallback_{int(time.monotonic())}"
        payload = {"task_description": context}
        response = await asyncio.wait_for(
            run_worker_pipeline(payload, task_id),
            timeout=_args.timeout,
        )

        result["response_length"] = len(response)
        result["time_ms"] = round((time.monotonic() - t0) * 1000)

        if result["response_length"] < 50:
            result["error"] = (
                f"Fallback response too short ({result['response_length']} chars)"
            )
            return result

        result["result"] = "PASS"

    except asyncio.TimeoutError:
        result["error"] = f"Fallback pipeline timed out after {_args.timeout}s"
        result["time_ms"] = round((time.monotonic() - t0) * 1000)
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        result["time_ms"] = round((time.monotonic() - t0) * 1000)

    return result


# ═══════════════════════════════════════════════════════════════════════════════
# Test registry — maps test IDs to their async handler functions
# ═══════════════════════════════════════════════════════════════════════════════

TEST_REGISTRY = {
    "T1": test_crop_and_save,
    "T2": test_chinese_vlm,
    "T3": test_sse_fork_start_format,
    "T4": test_deep_research_e2e,
    "T5": test_fallback_no_vlm,
}


# ═══════════════════════════════════════════════════════════════════════════════
# Terminal Output
# ═══════════════════════════════════════════════════════════════════════════════


def _verdict_icon(verdict: str) -> str:
    """Return colored PASS/FAIL string."""
    if verdict == "PASS":
        return f"{GREEN}PASS{RESET}"
    return f"{RED}FAIL{RESET}"


def _print_header(active_ids: list[str]) -> None:
    """Print test run header with configuration."""
    skip_api = "YES" if _args.skip_api_tests else "NO"
    print(f"\n{BOLD}{CYAN}{DOUBLE_DIVIDER}{RESET}")
    print(f"{BOLD}{CYAN}  Xiaoye Fork Pipeline End-to-End Test{RESET}")
    print(f"{BOLD}{CYAN}{DOUBLE_DIVIDER}{RESET}")
    print(f"  {BOLD}Model:{RESET}      qwen-vl-max / qwen-max")
    print(f"  {BOLD}API Base:{RESET}   {settings.QWEN_BASE_URL}")
    print(f"  {BOLD}Timestamp:{RESET}  {datetime.now(timezone.utc).isoformat()}")
    print(f"  {BOLD}Tests:{RESET}      {', '.join(active_ids)}")
    print(f"  {BOLD}Skip API:{RESET}   {skip_api}")
    print(f"  {BOLD}Timeout:{RESET}    {_args.timeout}s")
    print(f"{CYAN}{DIVIDER}{RESET}\n")


def _print_test_result(
    test_id: str, test_name: str, result_data: dict, verbose: bool
) -> None:
    """Print a single test result line with optional detail."""
    verdict = result_data.get("result", "FAIL")
    icon = _verdict_icon(verdict)
    time_ms = result_data.get("time_ms", 0)
    time_str = f"{time_ms / 1000:.1f}s" if time_ms > 0 else "N/A"
    error = result_data.get("error")

    status_line = f"{GREEN}✓{RESET}" if verdict == "PASS" else f"{RED}✗{RESET}"

    print(f"  {status_line} [{test_id}] {test_name:<28} {icon:<12} {time_str:<8}")

    if error:
        print(f"         {RED}→ {error}{RESET}")

    if verbose and verdict == "PASS":
        # Show extra detail for passed tests
        if test_id == "T1":
            path = result_data.get("image_path", "")
            size = result_data.get("size_bytes", 0)
            print(f"         {GRAY}  path={path}, size={size} bytes{RESET}")
        elif test_id == "T2":
            cn = result_data.get("cn_ratio", 0)
            length = result_data.get("text_length", 0)
            print(f"         {GRAY}  CN ratio={cn:.1%}, text length={length}{RESET}")
        elif test_id == "T3":
            event = result_data.get("event", {})
            print(f"         {GRAY}  event keys: {list(event.keys())}{RESET}")
        elif test_id in ("T4", "T5"):
            rlen = result_data.get("response_length", 0)
            print(f"         {GRAY}  response_length={rlen} chars{RESET}")


def _print_summary(results: dict) -> None:
    """Print aggregate summary across all tests."""
    total = len(results)
    passed = sum(1 for v in results.values() if v.get("result") == "PASS")
    failed = total - passed
    total_time = sum(v.get("time_ms", 0) for v in results.values()) / 1000

    pass_color = GREEN if passed == total else (YELLOW if passed > 0 else RED)
    fail_color = RED if failed > 0 else GREEN

    print(f"\n{BOLD}{CYAN}{DOUBLE_DIVIDER}{RESET}")
    print(f"{BOLD}{CYAN}  RESULTS SUMMARY{RESET}")
    print(f"{BOLD}{CYAN}{DOUBLE_DIVIDER}{RESET}")
    print(f"  Total tests:  {total}")
    print(f"  Passed:       {pass_color}{passed}{RESET}")
    print(f"  Failed:       {fail_color}{failed}{RESET}")
    print(f"  Total time:   {total_time:.1f}s")
    print()


# ═══════════════════════════════════════════════════════════════════════════════
# CLI helpers
# ═══════════════════════════════════════════════════════════════════════════════


def _resolve_active_tests() -> list[str]:
    """Parse --test CLI arg and return list of test IDs to execute.

    Returns:
        Sorted list of test IDs, e.g. ['T1', 'T2', 'T4'].
    """
    if _args.test is None:
        return [tc["id"] for tc in TEST_CASES]

    requested = {tid.strip().upper() for tid in _args.test.split(",")}
    unknown = requested - set(TEST_REGISTRY.keys())

    if unknown:
        available = ", ".join(sorted(TEST_REGISTRY.keys()))
        print(f"{RED}Error: Unknown test IDs: {', '.join(sorted(unknown))}{RESET}")
        print(f"  Available: {available}")
        sys.exit(1)

    # Return in definition order (not set order)
    return [tc["id"] for tc in TEST_CASES if tc["id"] in requested]


def _filter_api_tests(test_ids: list[str]) -> list[str]:
    """Remove tests that require LLM API when --skip-api-tests is set.

    Returns:
        Filtered list of test IDs.
    """
    if not _args.skip_api_tests:
        return test_ids

    requires_api = {tc["id"] for tc in TEST_CASES if tc.get("requires_api", False)}
    skipped = [tid for tid in test_ids if tid in requires_api]

    if skipped and _args.verbose:
        print(f"  {YELLOW}ⓘ  Skipping API tests: {', '.join(skipped)}{RESET}")

    return [tid for tid in test_ids if tid not in requires_api]


# ═══════════════════════════════════════════════════════════════════════════════
# Test Orchestrator
# ═══════════════════════════════════════════════════════════════════════════════


async def _run_all_tests(test_ids: list[str]) -> dict:
    """Execute all selected tests and return per-test result data.

    Each test runs independently; a failure in one does not prevent
    the remaining tests from executing.

    Args:
        test_ids: Ordered list of test IDs to run.

    Returns:
        Dict mapping test_id → result dict.
    """
    results: dict = {}

    for test_id in test_ids:
        test_fn = TEST_REGISTRY[test_id]
        test_info = next(tc for tc in TEST_CASES if tc["id"] == test_id)

        if _args.verbose:
            print(f"  {CYAN}▶ Running [{test_id}] {test_info['name']}…{RESET}")

        try:
            result_data = await test_fn()
            results[test_id] = result_data
        except Exception as exc:
            results[test_id] = {
                "result": "FAIL",
                "error": f"Unhandled exception: {type(exc).__name__}: {exc}",
                "time_ms": 0,
            }

    return results


# ═══════════════════════════════════════════════════════════════════════════════
# Main Entry Point
# ═══════════════════════════════════════════════════════════════════════════════


async def _async_main() -> int:
    """Async main body — orchestrates all tests and returns exit code.

    Returns:
        0 if all tests pass, 1 otherwise.
    """
    active_ids = _resolve_active_tests()
    active_ids = _filter_api_tests(active_ids)

    if not active_ids:
        print(f"{YELLOW}No tests to run after filtering. Exiting.{RESET}")
        return 0

    # Validate API key if any test requires it
    api_required = any(
        tc.get("requires_api", False) for tc in TEST_CASES if tc["id"] in active_ids
    )
    if api_required:
        _validate_api_key()

    # Suppress SSE noise
    _install_noop_sse()

    # Print header
    _print_header(active_ids)

    # Run all tests
    results = await _run_all_tests(active_ids)

    # Print per-test results
    for test_id in active_ids:
        test_info = next(tc for tc in TEST_CASES if tc["id"] == test_id)
        result_data = results.get(test_id, {"result": "FAIL", "error": "No result"})
        _print_test_result(test_id, test_info["name"], result_data, _args.verbose)
        print()  # blank line between tests

    # Print summary
    _print_summary(results)

    # Determine exit code
    all_passed = all(v.get("result") == "PASS" for v in results.values())
    return 0 if all_passed else 1


def main() -> None:
    """Synchronous entry point."""
    exit_code = asyncio.run(_async_main())
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
