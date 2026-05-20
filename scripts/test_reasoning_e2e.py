#!/usr/bin/env python3
"""
End-to-end reasoning pipeline test with real API calls.

Exercises the full Researcher → ToolNode → Compactor → Evaluator → Synthesizer
ReAct loop against the live Qwen API, measuring latency, tool invocation counts,
response quality, and source citation presence.

Usage:
    # Single query (default)
    python scripts/test_reasoning_e2e.py

    # Custom query
    python scripts/test_reasoning_e2e.py "稀土元素在轴承钢中的作用机理是什么？"

    # With custom task_id and doc_id (for report metadata)
    python scripts/test_reasoning_e2e.py --task-id my_task --doc-id doc_001 "test query"

    # Override API key
    python scripts/test_reasoning_e2e.py --api-key sk-xxxx "test query"

    # Batch mode — runs multiple queries and aggregates
    python scripts/test_reasoning_e2e.py --batch

    # Batch mode with custom queries
    python scripts/test_reasoning_e2e.py --batch --query "query1" --query "query2"
"""

import argparse
import asyncio
import io
import json
import logging
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
    description="E2E reasoning pipeline test",
    formatter_class=argparse.RawDescriptionHelpFormatter,
    epilog="""
Examples:
  python scripts/test_reasoning_e2e.py
  python scripts/test_reasoning_e2e.py "稀土元素在轴承钢中的作用机理是什么？"
  python scripts/test_reasoning_e2e.py --batch
  python scripts/test_reasoning_e2e.py --api-key sk-xxx "测试查询"
  python scripts/test_reasoning_e2e.py --task-id mytask --doc-id doc001 --timeout 90
    """,
)
_parser.add_argument(
    "query",
    nargs="?",
    default=None,
    help="Query to send through the reasoning pipeline",
)
_parser.add_argument(
    "--task-id",
    default=None,
    help="Task ID (auto-generated with timestamp if omitted)",
)
_parser.add_argument(
    "--doc-id",
    default=None,
    help="Document ID for report metadata (not used by pipeline currently)",
)
_parser.add_argument(
    "--api-key",
    default=None,
    help="Override QWEN_API_KEY from .env",
)
_parser.add_argument(
    "--batch",
    action="store_true",
    help="Run multiple test queries in batch mode",
)
_parser.add_argument(
    "--timeout",
    type=int,
    default=120,
    help="Timeout per test case in seconds (default: 120)",
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
from src.core.logger import setup_logger

# ── Constants ─────────────────────────────────────────────────────────────────
BOLD = "\033[1m"
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
CYAN = "\033[96m"
MAGENTA = "\033[95m"
RESET = "\033[0m"

DIVIDER = "─" * 72
DOUBLE_DIVIDER = "═" * 72

DEFAULT_QUERY = "请解释调质处理对304不锈钢螺栓性能的影响"

DEFAULT_BATCH_QUERIES = [
    "测试",  # basic sanity
    "请解释调质处理对304不锈钢螺栓性能的影响",  # previously successful
    "稀土元素在轴承钢中的作用机理是什么？",  # previously struggled
]

REPORT_DIR = PROJECT_ROOT / "work_log"
MIN_QUALITY_THRESHOLD = 2  # overall score ≥ 2 → PASS

# ── Pydantic model for quality scoring ────────────────────────────────────────
from pydantic import BaseModel, Field


class QualityScore(BaseModel):
    """Structured quality assessment of a pipeline answer."""

    relevance: int = Field(
        ge=1, le=5, description="How relevant the answer is to the query"
    )
    factual_depth: int = Field(
        ge=1, le=5, description="Depth and accuracy of factual content"
    )
    source_citation_quality: int = Field(
        ge=1, le=5, description="Quality and presence of source citations"
    )
    overall: int = Field(ge=1, le=5, description="Overall answer quality")
    brief_reason: str = Field(
        description="One-sentence justification for the overall score"
    )


# ── Helper: install noop SSE channel to suppress Redis connection noise ───────
def _install_noop_sse() -> None:
    """Replace the global SSE channel singleton with a silent noop variant.

    The reasoning pipeline publishes streaming patches via Redis PubSub.
    When Redis is unavailable (e.g., during E2E testing), the default
    SSEChannel logs noise on every token.  This monkey-patch suppresses
    that noise so the test output stays readable.
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


# ── Helper: tool invocation counting from captured log output ─────────────────
_TOOL_INVOKE_PATTERN = re.compile(r"🛠️ Tool Invoked:\s+(\S+)")


def _count_tool_invocations(log_text: str) -> dict[str, int]:
    """Parse captured log output and count each tool invocation by name.

    Args:
        log_text: Raw log output captured during a pipeline run.

    Returns:
        Mapping of tool name → invocation count.  Empty dict if no tools found.
    """
    counts: dict[str, int] = {}
    for match in _TOOL_INVOKE_PATTERN.finditer(log_text):
        tool_name = match.group(1)
        counts[tool_name] = counts.get(tool_name, 0) + 1
    return counts


# ── Helper: source citation detection ─────────────────────────────────────────
_SOURCE_PATTERN = re.compile(r"\[来源|\[?\d+\]|p\.\s*\d+", re.IGNORECASE)


def _has_source_citations(text: str) -> bool:
    """Detect whether the response text contains source citations.

    Looks for patterns like '[来源: ...]', '[1]', 'p. 12', etc.
    """
    return bool(_SOURCE_PATTERN.search(text))


# ── Helper: useful content detection ──────────────────────────────────────────
_NO_CONTENT_MARKER = "Worker completed but produced no textual output"


def _has_useful_content(text: str) -> bool:
    """Check whether the response contains actual content vs a fallback message."""
    return bool(text.strip()) and _NO_CONTENT_MARKER not in text


# ── Quality scorer ────────────────────────────────────────────────────────────
async def score_answer_quality(
    query: str,
    answer: str,
    api_key: str,
    base_url: str,
    timeout: float = 60.0,
) -> Optional[QualityScore]:
    """Ask the LLM to evaluate the answer quality on three dimensions.

    Uses a separate, tool-free LLM call to avoid contaminating the
    pipeline state.

    Args:
        query:      The original user query.
        answer:     The full pipeline response text.
        api_key:    Dashscope API key.
        base_url:   Dashscope compatible-mode base URL.
        timeout:    Maximum wait in seconds for the scoring call.

    Returns:
        QualityScore if successful, None on timeout or error.
    """
    from langchain_openai import ChatOpenAI
    from langchain_core.messages import HumanMessage

    scorer_llm = ChatOpenAI(
        model="qwen-max",
        api_key=api_key,
        base_url=base_url,
        temperature=0.0,
    ).with_structured_output(QualityScore, method="function_calling")

    prompt = (
        "请作为冶金领域专家，评估以下回答的质量。\n\n"
        f"【用户问题】\n{query}\n\n"
        f"【系统回答】\n{answer}\n\n"
        "请从以下三个维度评分（1-5分）：\n"
        "  - relevance: 回答与问题的相关度\n"
        "  - factual_depth: 事实深度与准确性\n"
        "  - source_citation_quality: 来源标注的质量\n"
        "  - overall: 综合评分\n"
        "  - brief_reason: 一句话简要说明评分理由\n"
    )

    try:
        result = await asyncio.wait_for(
            scorer_llm.ainvoke([HumanMessage(content=prompt)]),
            timeout=timeout,
        )
        return result
    except asyncio.TimeoutError:
        logging.getLogger("xiaoye.e2e").warning(
            "Quality scorer timed out after %.0fs", timeout
        )
        return None
    except Exception as exc:
        logging.getLogger("xiaoye.e2e").warning("Quality scorer failed: %s", exc)
        return None


# ── Single test case runner ───────────────────────────────────────────────────
async def _run_single_test(
    query: str,
    task_id: str,
    doc_id: Optional[str],
    api_key: str,
    base_url: str,
    timeout: float,
) -> dict:
    """Execute one query through the reasoning pipeline and collect metrics.

    Args:
        query:    The user query string.
        task_id:  Unique task identifier.
        doc_id:   Document ID for metadata (unused by pipeline).
        api_key:  Dashscope API key.
        base_url: Dashscope compatible-mode base URL.
        timeout:  Maximum wall-clock seconds for this test.

    Returns:
        Report dict with keys: config, metrics, quality_scores, verdict, error.
    """
    from src.reasoning.graph import run_worker_pipeline

    e2e_logger = logging.getLogger("xiaoye.e2e")
    payload = {"task_description": query}

    # ── Build config section ──────────────────────────────────────────────
    config = {
        "api_base_url": base_url,
        "model": "qwen-max",
        "query": query,
        "task_id": task_id,
        "doc_id": doc_id,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
    }

    # ── Set up log capture ────────────────────────────────────────────────
    log_buffer = io.StringIO()
    capture_handler = logging.StreamHandler(log_buffer)
    capture_handler.setLevel(logging.INFO)
    capture_handler.setFormatter(
        logging.Formatter(
            "[%(asctime)s] %(levelname)s [%(name)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    reasoning_logger = logging.getLogger("xiaoye.reasoning")
    reasoning_logger.addHandler(capture_handler)

    metrics = {
        "wall_clock_time_seconds": 0.0,
        "response_length_chars": 0,
        "tool_invocations": {},
        "has_useful_content": False,
        "has_source_citations": False,
        "error": None,
    }
    quality_scores: Optional[dict] = None
    response_text = ""
    error_msg: Optional[str] = None

    try:
        t_start = time.monotonic()
        response_text = await asyncio.wait_for(
            run_worker_pipeline(payload, task_id),
            timeout=timeout,
        )
        t_end = time.monotonic()
        metrics["wall_clock_time_seconds"] = round(t_end - t_start, 2)

    except asyncio.TimeoutError:
        t_end = time.monotonic()
        metrics["wall_clock_time_seconds"] = round(t_end - t_start, 2)
        error_msg = f"Pipeline timed out after {timeout}s"

    except Exception as exc:
        t_end = time.monotonic()
        metrics["wall_clock_time_seconds"] = round(t_end - t_start, 2)
        error_msg = f"{type(exc).__name__}: {exc}"

    finally:
        reasoning_logger.removeHandler(capture_handler)

    # ── Analyze captured log ──────────────────────────────────────────────
    log_output = log_buffer.getvalue()
    metrics["tool_invocations"] = _count_tool_invocations(log_output)
    # Expose log output for terminal display (caller handles printing)
    captured_log = log_output

    # ── Populate metrics from response ────────────────────────────────────
    if error_msg:
        metrics["error"] = error_msg
    else:
        metrics["response_length_chars"] = len(response_text)
        metrics["has_useful_content"] = _has_useful_content(response_text)
        metrics["has_source_citations"] = _has_source_citations(response_text)

    # ── Quality scoring ───────────────────────────────────────────────────
    if not error_msg and _has_useful_content(response_text):
        quality_result = await score_answer_quality(
            query=query,
            answer=response_text,
            api_key=api_key,
            base_url=base_url,
        )
        if quality_result is not None:
            quality_scores = quality_result.model_dump()

    # ── Verdict ───────────────────────────────────────────────────────────
    overall = quality_scores.get("overall", 0) if quality_scores else 0
    passed = (
        not error_msg
        and metrics["has_useful_content"]
        and overall >= MIN_QUALITY_THRESHOLD
    )
    verdict = "PASS" if passed else "FAIL"
    verdict_reason = ""
    if error_msg:
        verdict_reason = f"Error: {error_msg}"
    elif not metrics["has_useful_content"]:
        verdict_reason = "No useful content in response"
    elif overall < MIN_QUALITY_THRESHOLD:
        verdict_reason = f"Quality score {overall} < threshold {MIN_QUALITY_THRESHOLD}"

    report = {
        "config": config,
        "metrics": metrics,
        "quality_scores": quality_scores,
        "verdict": verdict,
        "verdict_reason": verdict_reason,
        "response_preview": response_text[:500] if response_text else "",
    }

    # Store for terminal display
    report["_captured_log"] = captured_log
    report["_response_full"] = response_text

    return report


# ── Terminal output helpers ───────────────────────────────────────────────────
def _print_banner(config: dict) -> None:
    """Print a formatted test banner to the terminal."""
    print(f"\n{BOLD}{CYAN}{DOUBLE_DIVIDER}{RESET}")
    print(f"{BOLD}{CYAN}  E2E Reasoning Pipeline Test{RESET}")
    print(f"{BOLD}{CYAN}{DOUBLE_DIVIDER}{RESET}")
    print(f"  {BOLD}API Base:{RESET}  {config['api_base_url']}")
    print(f"  {BOLD}Model:{RESET}     {config['model']}")
    print(f"  {BOLD}Task ID:{RESET}   {config['task_id']}")
    if config.get("doc_id"):
        print(f"  {BOLD}Doc ID:{RESET}    {config['doc_id']}")
    print(f"  {BOLD}Query:{RESET}     {config['query'][:80]}")
    print(f"{CYAN}{DIVIDER}{RESET}\n")


def _print_summary(report: dict) -> None:
    """Print a colored human-readable summary for a single test case."""
    m = report["metrics"]
    q = report.get("quality_scores") or {}
    v = report["verdict"]
    vr = report.get("verdict_reason", "")

    verdict_color = GREEN if v == "PASS" else RED
    print(f"\n{BOLD}{verdict_color}  VERDICT: {v}{RESET}")
    if vr:
        print(f"  {verdict_color}Reason:  {vr}{RESET}")

    print(f"\n  {BOLD}Metrics:{RESET}")
    wall = m["wall_clock_time_seconds"]
    time_color = GREEN if wall < 60 else (YELLOW if wall < 90 else RED)
    print(f"    Wall-clock time:     {time_color}{wall:.1f}s{RESET}")
    print(f"    Response length:     {m['response_length_chars']:,} chars")

    tools = m.get("tool_invocations", {})
    if tools:
        print(f"    Tool invocations:    {sum(tools.values())} total")
        for name, count in sorted(tools.items()):
            print(f"      {name}: {count}")
    else:
        print(f"    Tool invocations:    0")

    print(f"    Has useful content:  {_bool_icon(m['has_useful_content'])}")
    print(f"    Has source cites:    {_bool_icon(m['has_source_citations'])}")
    if m.get("error"):
        print(f"    {RED}Error:{RESET}               {m['error']}")

    if q:
        print(f"\n  {BOLD}Quality Scores (1-5):{RESET}")
        rel = q.get("relevance", 0)
        dep = q.get("factual_depth", 0)
        src = q.get("source_citation_quality", 0)
        ovr = q.get("overall", 0)
        print(f"    Relevance:           {_score_bar(rel)}")
        print(f"    Factual Depth:       {_score_bar(dep)}")
        print(f"    Source Citations:    {_score_bar(src)}")
        qual_color = GREEN if ovr >= MIN_QUALITY_THRESHOLD else RED
        print(
            f"    {BOLD}Overall:{RESET}              {qual_color}{_score_bar(ovr)}{RESET}"
        )
        if q.get("brief_reason"):
            print(f"    Reason:              {q['brief_reason']}")

    # Print captured pipeline log
    log_output = report.get("_captured_log", "")
    if log_output.strip():
        print(f"\n  {BOLD}{MAGENTA}Pipeline Log:{RESET}")
        print(f"  {MAGENTA}{'─' * 50}{RESET}")
        for line in log_output.strip().splitlines():
            # Color code by level
            if "ERROR" in line:
                print(f"  {RED}{line}{RESET}")
            elif "WARNING" in line or "⚠" in line:
                print(f"  {YELLOW}{line}{RESET}")
            else:
                print(f"  {line}")
        print(f"  {MAGENTA}{'─' * 50}{RESET}")

    # Print response preview
    response = report.get("_response_full", "")
    if response.strip():
        print(f"\n  {BOLD}Response Preview (first 600 chars):{RESET}")
        print(f"  {CYAN}{response[:600]}{RESET}")
        if len(response) > 600:
            print(f"  {CYAN}... (truncated, full text in JSON report){RESET}")

    print()


def _bool_icon(value: bool) -> str:
    return f"{GREEN}✓{RESET}" if value else f"{RED}✗{RESET}"


def _score_bar(score: int) -> str:
    """Render a 1-5 score as a colored bar."""
    bar = "█" * score + "░" * (5 - score)
    colors = [RED, YELLOW, YELLOW, GREEN, GREEN]
    c = colors[max(0, min(score - 1, 4))]
    return f"{c}{bar} {score}/5{RESET}"


# ── Batch runner ──────────────────────────────────────────────────────────────
async def _run_batch_tests(
    queries: list[str],
    task_id_prefix: str,
    doc_id: Optional[str],
    api_key: str,
    base_url: str,
    timeout: float,
) -> list[dict]:
    """Run multiple queries sequentially and return aggregated reports.

    A single failure does not abort the batch; all cases are attempted.
    """
    reports: list[dict] = []
    for idx, query in enumerate(queries, start=1):
        task_id = f"{task_id_prefix}_{idx}"
        print(f"\n{BOLD}{BLUE}{'═' * 72}{RESET}")
        print(f"{BOLD}{BLUE}  Batch case {idx}/{len(queries)}{RESET}")
        print(f"{BOLD}{BLUE}{'═' * 72}{RESET}")

        report = await _run_single_test(
            query=query,
            task_id=task_id,
            doc_id=doc_id,
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
        )
        _print_banner(report["config"])
        _print_summary(report)
        reports.append(report)

    return reports


def _print_batch_aggregate(reports: list[dict]) -> dict:
    """Print batch aggregate summary and return the aggregate dict."""
    total = len(reports)
    passed = sum(1 for r in reports if r["verdict"] == "PASS")
    failed = total - passed
    times = [r["metrics"]["wall_clock_time_seconds"] for r in reports]
    avg_time = sum(times) / total if total > 0 else 0
    scores = [
        r["quality_scores"]["overall"]
        for r in reports
        if r.get("quality_scores") and r["quality_scores"].get("overall")
    ]
    avg_quality = sum(scores) / len(scores) if scores else 0

    print(f"\n{BOLD}{CYAN}{DOUBLE_DIVIDER}{RESET}")
    print(f"{BOLD}{CYAN}  BATCH AGGREGATE{RESET}")
    print(f"{BOLD}{CYAN}{DOUBLE_DIVIDER}{RESET}")
    print(f"  Total cases:  {total}")
    pass_color = GREEN if passed == total else (YELLOW if passed > 0 else RED)
    print(f"  Passed:       {pass_color}{passed}{RESET}")
    print(f"  Failed:       {RED if failed > 0 else GREEN}{failed}{RESET}")
    print(f"  Avg time:     {avg_time:.1f}s")
    print(f"  Avg quality:  {_score_bar(round(avg_quality))}")
    print()

    return {
        "total": total,
        "passed": passed,
        "failed": failed,
        "average_time_seconds": round(avg_time, 2),
        "average_quality_score": round(avg_quality, 2),
    }


def _write_report(
    reports: list[dict], aggregate: Optional[dict], timestamp: str
) -> Path:
    """Write full structured JSON report to work_log/ and return the file path."""
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORT_DIR / f"test_report_{timestamp}.json"

    # Strip internal-only keys before serializing
    clean_reports = []
    for r in reports:
        clean = {k: v for k, v in r.items() if not k.startswith("_")}
        clean["response_full"] = r.get("_response_full", "")
        clean["pipeline_log"] = r.get("_captured_log", "")
        clean_reports.append(clean)

    payload = {"test_cases": clean_reports}
    if aggregate is not None:
        payload["batch_summary"] = aggregate

    report_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return report_path


# ── Entry point ───────────────────────────────────────────────────────────────
def _validate_api_key() -> str:
    """Verify API key is available; exit with message if missing."""
    api_key = settings.QWEN_API_KEY
    if not api_key:
        print(f"{RED}ERROR: QWEN_API_KEY is not set.{RESET}")
        print("Set it in one of these ways:")
        print("  1. Create a .env file with QWEN_API_KEY=sk-xxxx")
        print("  2. Export QWEN_API_KEY=sk-xxxx in your shell")
        print("  3. Pass --api-key sk-xxxx on the command line")
        sys.exit(1)
    return api_key


def main() -> None:
    """Parse CLI args, run tests, and write reports."""
    api_key = _validate_api_key()
    base_url = settings.QWEN_BASE_URL
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Determine single vs batch mode
    if _args.batch:
        # Batch mode: if user supplied a positional query, run that single query
        # as a batch-of-1 (useful for CI).  Otherwise use the 3 default queries.
        queries = [_args.query] if _args.query else DEFAULT_BATCH_QUERIES
    else:
        # Single mode: use provided positional or the default query
        queries = [_args.query or DEFAULT_QUERY]

    task_id_prefix = _args.task_id or f"e2e_{ts}"
    doc_id = _args.doc_id
    timeout = _args.timeout

    # Install silent SSE channel before any pipeline call
    _install_noop_sse()

    # Run tests
    if len(queries) == 1 and not _args.batch:
        # Single test case
        task_id = task_id_prefix if _args.task_id else f"{task_id_prefix}_1"
        report = asyncio.run(
            _run_single_test(
                query=queries[0],
                task_id=task_id,
                doc_id=doc_id,
                api_key=api_key,
                base_url=base_url,
                timeout=timeout,
            )
        )
        _print_banner(report["config"])
        _print_summary(report)

        reports = [report]
        aggregate = None
    else:
        # Batch mode
        reports = asyncio.run(
            _run_batch_tests(
                queries=queries,
                task_id_prefix=task_id_prefix,
                doc_id=doc_id,
                api_key=api_key,
                base_url=base_url,
                timeout=timeout,
            )
        )
        aggregate = _print_batch_aggregate(reports)

    # Write JSON report
    report_path = _write_report(reports, aggregate, ts)
    print(f"{GREEN}Report saved to:{RESET} {report_path}")

    # Exit code: 0 if all passed, 1 otherwise
    all_passed = all(r["verdict"] == "PASS" for r in reports)
    if not all_passed:
        sys.exit(1)


if __name__ == "__main__":
    main()
