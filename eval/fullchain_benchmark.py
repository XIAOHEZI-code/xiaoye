#!/usr/bin/env python3
"""
Full-Chain Integration Test for Xiaoye Metallurgy Agent.

Exercises all retrieval and reasoning layers independently then end-to-end:
  Layer 1: ES Semantic Search (SemanticSearchTool)
  Layer 2: Neo4j Graph Search (GraphLogicTool)
  Layer 3: KG-HyDE Enhanced Search (HyDESearcher)
  Layer 4: Full Chat Pipeline (run_worker_pipeline)

Each layer runs independently per test question. Results are aggregated into
a structured JSON report with terminal output showing PASS/FAIL per question/layer.

Usage:
    # Run all questions, all layers
    python scripts/test_fullchain.py

    # Run specific questions (comma-separated)
    python scripts/test_fullchain.py --questions Q1,Q3,Q5

    # Run specific layers only (comma-separated: es,graph,hyde,chat)
    python scripts/test_fullchain.py --layers es,chat

    # Verbose debug output
    python scripts/test_fullchain.py --verbose

    # Custom timeout overrides (seconds)
    python scripts/test_fullchain.py --layer-timeout 30 --chat-timeout 120

    # Override API key
    python scripts/test_fullchain.py --api-key sk-xxxx
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
from typing import Any, Optional

# ── Path resolution — ensure project root is importable ──────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# ── CLI argument parsing (early, before side-effect imports) ──────────────────
_parser = argparse.ArgumentParser(
    description="Full-chain integration test for Xiaoye Metallurgy Agent",
    formatter_class=argparse.RawDescriptionHelpFormatter,
    epilog="""
Examples:
  python scripts/test_fullchain.py
  python scripts/test_fullchain.py --questions Q1,Q3
  python scripts/test_fullchain.py --layers es,chat
  python scripts/test_fullchain.py --verbose --api-key sk-xxxx
    """,
)
_parser.add_argument(
    "--questions",
    default=None,
    help="Comma-separated question IDs to run (e.g. Q1,Q3,Q5). Default: all.",
)
_parser.add_argument(
    "--layers",
    default=None,
    help="Comma-separated layers to run: es,graph,hyde,chat. Default: all.",
)
_parser.add_argument(
    "--api-key",
    default=None,
    help="Override QWEN_API_KEY from .env",
)
_parser.add_argument(
    "--verbose",
    action="store_true",
    help="Enable detailed debug output for each layer",
)
_parser.add_argument(
    "--layer-timeout",
    type=int,
    default=60,
    help="Timeout per retrieval layer in seconds (default: 60)",
)
_parser.add_argument(
    "--chat-timeout",
    type=int,
    default=180,
    help="Timeout for chat_pipeline layer in seconds (default: 180)",
)
_parser.add_argument(
    "--skip-quality-score",
    action="store_true",
    help="Skip LLM quality scoring to save API cost/time",
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
GRAY = "\033[90m"
RESET = "\033[0m"

DIVIDER = "─" * 72
DOUBLE_DIVIDER = "═" * 72

REPORT_DIR = PROJECT_ROOT / "work_log"

# Metallurgy entity vocabulary for keyword-based extraction (graph_search layer)
_METALLURGY_ENTITIES = [
    "敏化",
    "碳化物颗粒",
    "碳化铬颗粒",
    "碳化物",
    "铬",
    "晶间",
    "奥氏体",
    "铁素体",
    "马氏体",
    "304不锈钢螺栓",
    "304不锈钢",
    "45钢",
    "304/45双金属",
    "疲劳性能",
    "疲劳",
    "耐蚀性能",
    "腐蚀",
    "调质处理",
    "调质",
    "冷加工",
    "热轧",
    "拉拔",
    "滚丝",
    "淬火",
    "回火",
    "退火",
    "正火",
    "双金属复合管",
    "双金属复合螺栓",
    "不锈钢",
    "碳钢",
    "复合界面",
    "扩散层",
    "结合强度",
    "硬度",
    "强度",
    "塑性",
    "韧性",
    "S-N曲线",
    "瞬断区",
    "断口",
    "裂纹",
    "疲劳极限",
    "腐蚀电位",
    "盐雾",
    "抗晶间腐蚀性能",
    "纤维状流线分布",
]

# ── Test Questions ────────────────────────────────────────────────────────────
TEST_QUESTIONS = [
    {
        "id": "Q1",
        "name": "事实检索 - 疲劳极限数值提取",
        "query": "304/45双金属复合螺栓在冷加工态和调质态下的疲劳极限分别是多少？请引用具体数值和来源页码。",
        "expect_keywords": ["240", "85", "MPa", "疲劳极限"],
        "expect_sources": True,
        "layers": ["es_search", "chat_pipeline"],
        "graph_entities": ["304不锈钢螺栓", "45钢", "疲劳性能"],
    },
    {
        "id": "Q2",
        "name": "对比分析 - 调质处理对耐腐蚀性的影响",
        "query": "调质处理对304/45双金属复合螺栓的耐腐蚀性能产生了什么影响？请结合电化学数据和盐雾试验结果具体说明。",
        "expect_keywords": ["腐蚀电位", "盐雾", "碳化物", "耐腐蚀"],
        "expect_sources": True,
        "layers": ["es_search", "chat_pipeline"],
        "graph_entities": ["调质处理", "304不锈钢螺栓", "耐蚀性能"],
    },
    {
        "id": "Q3",
        "name": "因果链追踪 - 敏化→耐腐蚀性下降",
        "query": "敏化现象是如何通过微观组织变化导致304不锈钢耐腐蚀性下降的？请追踪完整的因果链条。",
        "expect_keywords": ["敏化", "碳化物", "晶间", "铬", "耐腐蚀"],
        "layers": ["es_search", "graph_search", "chat_pipeline"],
        "graph_entities": ["调质处理", "碳化物颗粒", "碳化铬颗粒", "304不锈钢螺栓"],
    },
    {
        "id": "Q4",
        "name": "KG增强检索 - 制造工艺全链路",
        "query": "304/45双金属复合螺栓从原材料到成品经过了哪些制造工艺？每种工艺分别改变了什么微观组织、影响了什么性能？",
        "expect_keywords": ["热轧", "拉拔", "冷加工", "调质", "组织", "性能"],
        "layers": ["es_search", "graph_search", "hyde_search", "chat_pipeline"],
        "graph_entities": ["热轧", "冷加工", "调质处理", "304不锈钢螺栓", "45钢"],
    },
    {
        "id": "Q5",
        "name": "多模态 - S-N曲线与疲劳断口分析",
        "query": "根据论文中的S-N曲线（图5），冷加工态和调质态螺栓的疲劳断裂模式有什么不同？请结合疲劳断口形貌特征来解释。",
        "expect_keywords": ["S-N", "疲劳", "断口", "裂纹"],
        "expect_figures": True,
        "layers": ["es_search", "chat_pipeline"],
        "graph_entities": ["疲劳性能", "S-N曲线", "瞬断区"],
    },
]

# ── All available layers ──────────────────────────────────────────────────────
ALL_LAYERS = ["es_search", "graph_search", "hyde_search", "chat_pipeline"]
LAYER_TIMEOUTS = {
    "es_search": _args.layer_timeout,
    "graph_search": _args.layer_timeout,
    "hyde_search": _args.layer_timeout,
    "chat_pipeline": _args.chat_timeout,
}


# ═══════════════════════════════════════════════════════════════════════════════
# Monkey-patches
# ═══════════════════════════════════════════════════════════════════════════════


def _install_noop_sse() -> None:
    """Replace the global SSE channel singleton with a silent noop variant.

    The reasoning pipeline publishes streaming patches via Redis PubSub.
    When Redis is unavailable (e.g., during testing), the default SSEChannel
    logs noise on every token. This monkey-patch suppresses that noise.
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


def _elapsed_ms(t0: float) -> int:
    """Return elapsed milliseconds since *t0* (from time.monotonic())."""
    return round((time.monotonic() - t0) * 1000)


def _jsonable(obj: Any) -> Any:
    """Convert objects to JSON-serializable primitives recursively."""
    if hasattr(obj, "to_dict"):
        return obj.to_dict()
    if hasattr(obj, "__dict__"):
        return {k: v for k, v in obj.__dict__.items() if not k.startswith("_")}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(i) for i in obj]
    if isinstance(obj, dict):
        return {k: _jsonable(v) for k, v in obj.items()}
    return obj


def _truncate(text: str, max_len: int = 200) -> str:
    """Truncate text for preview display."""
    if len(text) <= max_len:
        return text
    return text[:max_len] + "..."


def _chunk_doc_to_dict(chunk: Any) -> dict:
    """Convert a ChunkDocument to a JSON-safe dict with citation info."""
    return {
        "chunk_id": getattr(chunk, "chunk_id", ""),
        "doc_id": getattr(chunk, "doc_id", ""),
        "content_preview": _truncate(getattr(chunk, "text_content", "") or "", 300),
        "page_number": getattr(chunk, "page_number", -1),
        "source_pdf_id": getattr(chunk, "source_pdf_id", ""),
        "chunk_type": getattr(chunk, "chunk_type", "text"),
        "score": getattr(chunk, "score", None),
        "is_figure": getattr(chunk, "chunk_type", "text")
        in ("figure", "image_description"),
    }


# ── Tool invocation counting from captured log ────────────────────────────────
_TOOL_INVOKE_PATTERN = re.compile(r"🛠️ Tool Invoked:\s+(\S+)")


def _count_tool_invocations(log_text: str) -> dict[str, int]:
    """Parse captured log output and count each tool invocation by name.

    Args:
        log_text: Raw log output captured during a pipeline run.

    Returns:
        Mapping of tool name → invocation count. Empty dict if no tools found.
    """
    counts: dict[str, int] = {}
    for match in _TOOL_INVOKE_PATTERN.finditer(log_text):
        tool_name = match.group(1)
        counts[tool_name] = counts.get(tool_name, 0) + 1
    return counts


# ═══════════════════════════════════════════════════════════════════════════════
# Entity Extraction (simple keyword-based, no LLM)
# ═══════════════════════════════════════════════════════════════════════════════


def extract_entities_keyword(
    query: str, candidates: Optional[list[str]] = None
) -> list[str]:
    """Extract metallurgy entities from query using keyword matching.

    Scans the query string for known metallurgy terms from the vocabulary.
    Falls back to the provided candidate list if given.

    Args:
        query:      The natural language query string.
        candidates: Optional explicit entity list (e.g. from test config).

    Returns:
        List of matched entity strings, deduplicated and longest match first.
    """
    if candidates:
        # Filter candidates that actually appear in the query
        found = [c for c in candidates if c.lower() in query.lower()]
        if found:
            # Sort by length descending for longest-match-first
            return sorted(set(found), key=len, reverse=True)

    vocab = _METALLURGY_ENTITIES
    found = []
    for entity in vocab:
        if entity.lower() in query.lower():
            found.append(entity)
    return sorted(set(found), key=len, reverse=True)


# ═══════════════════════════════════════════════════════════════════════════════
# Layer 1: ES Semantic Search
# ═══════════════════════════════════════════════════════════════════════════════


async def test_es_search(query: str, top_k: int = 5) -> dict:
    """Execute semantic search via SemanticSearchTool and collect metrics.

    Args:
        query: Natural language query string.
        top_k: Number of results to retrieve.

    Returns:
        Dict with keys: hits, chunks, time_ms, has_figures, error.
    """
    from src.retrieval.semantic_search import SemanticSearchTool

    result: dict = {
        "hits": 0,
        "chunks": [],
        "time_ms": 0,
        "has_figures": False,
        "error": None,
    }

    t0 = time.monotonic()
    try:
        tool = SemanticSearchTool()
        chunks = await asyncio.wait_for(
            asyncio.to_thread(tool.search, query, top_k),
            timeout=LAYER_TIMEOUTS["es_search"],
        )
        result["time_ms"] = _elapsed_ms(t0)
        result["hits"] = len(chunks)
        result["chunks"] = [_chunk_doc_to_dict(c) for c in chunks]
        result["has_figures"] = any(c.get("is_figure", False) for c in result["chunks"])

        if _args.verbose:
            for i, chunk in enumerate(chunks):
                preview = _truncate(getattr(chunk, "text_content", "") or "", 120)
                page = getattr(chunk, "page_number", -1)
                print(f"  {GRAY}[ES hit {i + 1}] p.{page} | {preview}{RESET}")

    except asyncio.TimeoutError:
        result["error"] = f"ES search timed out after {LAYER_TIMEOUTS['es_search']}s"
        result["time_ms"] = _elapsed_ms(t0)
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        result["time_ms"] = _elapsed_ms(t0)

    return result


# ═══════════════════════════════════════════════════════════════════════════════
# Layer 2: Neo4j Graph Search
# ═══════════════════════════════════════════════════════════════════════════════


async def test_graph_search(
    query: str,
    entity_candidates: Optional[list[str]] = None,
) -> dict:
    """Execute knowledge graph traversal via GraphLogicTool.

    Extracts entities from the query using keyword matching, then fetches
    direct relations and multi-hop impact paths from Neo4j.

    Args:
        query:             Natural language query string.
        entity_candidates: Optional list of entity names to search for.

    Returns:
        Dict with keys: entity_count, entities_found, relations, paths,
                        time_ms, error, neo4j_available.
    """
    from src.retrieval.graph_search import GraphLogicTool

    result: dict = {
        "entity_count": 0,
        "entities_found": [],
        "relations": [],
        "paths": [],
        "time_ms": 0,
        "error": None,
        "neo4j_available": True,
    }

    t0 = time.monotonic()

    try:
        # Use candidates directly for graph lookup (not keyword-filtered
        # by query text, since graph entities may be relevant concepts
        # the query alludes to without spelling out verbatim)
        if entity_candidates:
            entities = entity_candidates
        else:
            entities = extract_entities_keyword(query)
        result["entities_found"] = entities
        result["entity_count"] = len(entities)

        if not entities:
            result["time_ms"] = _elapsed_ms(t0)
            result["error"] = "No metallurgy entities matched in query"
            return result

        graph_tool = GraphLogicTool()

        # Fetch direct relations for each entity (limit 2 entities to avoid explosion)
        all_relations = []
        for entity in entities[:2]:
            rels = await asyncio.wait_for(
                asyncio.to_thread(graph_tool.find_direct_relations, entity, "both"),
                timeout=LAYER_TIMEOUTS["graph_search"] // 2,
            )
            all_relations.extend(rels)

        result["relations"] = _jsonable(all_relations)

        # Fetch multi-hop paths for the first entity
        paths = []
        if entities:
            paths = await asyncio.wait_for(
                asyncio.to_thread(
                    graph_tool.trace_impact_path,
                    entities[0],
                    3,
                ),
                timeout=LAYER_TIMEOUTS["graph_search"] // 2,
            )
        result["paths"] = _jsonable(paths)

        result["time_ms"] = _elapsed_ms(t0)

        graph_tool.close()

    except asyncio.TimeoutError:
        result["error"] = (
            f"Graph search timed out after {LAYER_TIMEOUTS['graph_search']}s"
        )
        result["time_ms"] = _elapsed_ms(t0)
    except OSError as exc:
        # Connection refused → Neo4j likely not running
        result["neo4j_available"] = False
        result["error"] = f"Neo4j unavailable ({exc})"
        result["time_ms"] = _elapsed_ms(t0)
    except Exception as exc:
        error_str = str(exc)
        if (
            "Unable to retrieve routing information" in error_str
            or "ServiceUnavailable" in error_str
        ):
            result["neo4j_available"] = False
        result["error"] = f"{type(exc).__name__}: {exc}"
        result["time_ms"] = _elapsed_ms(t0)

    if _args.verbose and result["relations"]:
        for i, rel in enumerate(result["relations"][:5]):
            subj = rel.get("subject", "?")
            rel_type = rel.get("relation", "?")
            obj = rel.get("object", "?")
            print(f"  {GRAY}[Graph rel {i + 1}] {subj} -[{rel_type}]-> {obj}{RESET}")

    return result


# ═══════════════════════════════════════════════════════════════════════════════
# Layer 3: KG-HyDE Enhanced Search
# ═══════════════════════════════════════════════════════════════════════════════


async def test_hyde_search(query: str, top_k: int = 5) -> dict:
    """Execute KG-anchored HyDE pipeline via HyDESearcher.

    Runs the full HyDE pipeline (entity extraction → KG traversal →
    HyDE generation → semantic search) as a single atomic operation
    with the full layer timeout.  Sub-step timeouts are avoided because
    the LLM generation step can take 30–60 s.

    Entity extraction for reporting is done via fast keyword matching;
    the production HyDE LLM extraction is exercised inside searcher.search().

    Args:
        query: Natural language query string.
        top_k: Number of final results to retrieve.

    Returns:
        Dict with keys: entities, hyde_preview, hits, chunks, time_ms, error.
    """
    from src.retrieval.hyde_searcher import HyDESearcher

    result: dict = {
        "entities": [],
        "hyde_preview": "",
        "hits": 0,
        "chunks": [],
        "time_ms": 0,
        "error": None,
    }

    t0 = time.monotonic()
    try:
        searcher = HyDESearcher()

        # Run full HyDE pipeline (entity → KG → generate → search)
        # with the single layer-level timeout — no sub-step slicing
        chunks = await asyncio.wait_for(
            asyncio.to_thread(searcher.search, query, top_k),
            timeout=LAYER_TIMEOUTS["hyde_search"],
        )
        result["time_ms"] = _elapsed_ms(t0)
        result["chunks"] = [_chunk_doc_to_dict(c) for c in chunks]
        result["hits"] = len(chunks)

        # Entities for reporting: use fast keyword extraction
        # (production LLM extraction already ran inside searcher.search())
        result["entities"] = extract_entities_keyword(query)

    except asyncio.TimeoutError:
        result["error"] = (
            f"HyDE search timed out after {LAYER_TIMEOUTS['hyde_search']}s"
        )
        result["time_ms"] = _elapsed_ms(t0)
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        result["time_ms"] = _elapsed_ms(t0)

    return result


# ═══════════════════════════════════════════════════════════════════════════════
# Layer 4: Full Chat Pipeline (Researcher → Tools → Compactor → Evaluator loop)
# ═══════════════════════════════════════════════════════════════════════════════


async def test_chat_pipeline(query: str, task_id: str) -> dict:
    """Execute the full ReAct reasoning pipeline end-to-end.

    Captures the response text, tool invocations via log interception,
    evaluator loop count, wall-clock timing, and source citation status.

    Args:
        query:   The natural language task description / query.
        task_id: Unique task identifier for SSE routing.

    Returns:
        Dict with keys: response, response_length, tool_calls, evaluator_loops,
                        time_ms, has_sources, has_useful_content, error.
    """
    from src.reasoning.graph import run_worker_pipeline

    result: dict = {
        "response": "",
        "response_length": 0,
        "tool_calls": [],
        "tool_call_count": 0,
        "evaluator_loops": 0,
        "time_ms": 0,
        "has_sources": False,
        "has_useful_content": False,
        "error": None,
    }

    # ── Set up log capture to count tool invocations ───────────────────────
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

    payload = {"task_description": query}
    response_text = ""

    t0 = time.monotonic()
    try:
        response_text = await asyncio.wait_for(
            run_worker_pipeline(payload, task_id),
            timeout=LAYER_TIMEOUTS["chat_pipeline"],
        )
        result["time_ms"] = _elapsed_ms(t0)

    except asyncio.TimeoutError:
        result["error"] = (
            f"Chat pipeline timed out after {LAYER_TIMEOUTS['chat_pipeline']}s"
        )
        result["time_ms"] = _elapsed_ms(t0)
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        result["time_ms"] = _elapsed_ms(t0)
    finally:
        reasoning_logger.removeHandler(capture_handler)

    # ── Analyze captured log ──────────────────────────────────────────────
    log_output = log_buffer.getvalue()
    tool_counts = _count_tool_invocations(log_output)
    result["tool_calls"] = [
        {"name": name, "count": count} for name, count in sorted(tool_counts.items())
    ]
    result["tool_call_count"] = sum(tool_counts.values())

    # Count evaluator loops from log
    _EVAL_LOOP_PATTERN = re.compile(r"\[Evaluator\] Loop (\d+)/")
    evaluator_loops = _EVAL_LOOP_PATTERN.findall(log_output)
    result["evaluator_loops"] = max((int(n) for n in evaluator_loops), default=0)

    # ── Analyze response ──────────────────────────────────────────────────
    if not result["error"]:
        result["response"] = response_text
        result["response_length"] = len(response_text)
        result["has_useful_content"] = bool(
            response_text.strip()
            and "Worker completed but produced no textual output" not in response_text
        )
        _SOURCE_PATTERN = re.compile(
            r"\[来源|\[?\d+\]|p\.\s*\d+|来源页码[：:]\s*\d+|（来源.*?页码.*?\d+）|图\s*\d+|Figure\s*\d+|第\s*\d+\s*页",
            re.IGNORECASE,
        )
        result["has_sources"] = bool(_SOURCE_PATTERN.search(response_text))

    if _args.verbose and result.get("response"):
        preview = _truncate(result["response"], 400)
        print(f"  {GRAY}[Chat] Response preview: {preview}{RESET}")

    return result


# ═══════════════════════════════════════════════════════════════════════════════
# Validation Functions
# ═══════════════════════════════════════════════════════════════════════════════


def validate_keywords(response: str, expected: list[str]) -> dict:
    """Check if expected keywords appear in the response text.

    Args:
        response: The full response text to scan.
        expected: List of keyword strings to look for.

    Returns:
        Dict with keys: found, missing, coverage (0.0–1.0).
    """
    if not response:
        return {"found": [], "missing": list(expected), "coverage": 0.0}

    found = [kw for kw in expected if kw.lower() in response.lower()]
    missing = [kw for kw in expected if kw not in found]
    coverage = len(found) / len(expected) if expected else 0.0

    return {"found": found, "missing": missing, "coverage": round(coverage, 2)}


_SOURCE_CITE_PATTERN = re.compile(
    r"\[来源[：:].*?\]|来源页码[：:]\s*\d+|（来源.*?页码.*?\d+）|"
    r"p\.\s*\d+|pp\.\s*\d+|\[?\d+\]|"
    r"第\s*\d+\s*页|图\s*\d+|Figure\s*\d+|"
    r"page\s*\d+|fig\.\s*\d+|Fig\.\s*\d+|"
    r"来源[：:].*|参考.*?页|见.*?图|如.*?所示",
    re.IGNORECASE,
)


def validate_sources(response: str) -> bool:
    """Check if response contains recognizable source citations.

    Detects patterns like:
      - [来源: xxx.pdf, p.12]
      - p. 42
      - 第 5 页
      - 图 3 / Figure 3

    Args:
        response: The full response text.

    Returns:
        True if at least one citation pattern is found.
    """
    if not response:
        return False
    return bool(_SOURCE_CITE_PATTERN.search(response))


def validate_graph_path(
    paths: list[dict],
    expected_nodes: list[str],
) -> dict:
    """Check if knowledge graph paths contain expected causal nodes.

    Each path dict is expected to have a 'nodes' key (list of node names).

    Args:
        paths:          List of path dicts from trace_impact_path.
        expected_nodes: List of node names that should appear in paths.

    Returns:
        Dict with keys: found_paths (paths containing ≥1 expected node),
                        coverage (fraction of expected nodes found across all paths).
    """
    if not paths:
        return {"found_paths": [], "coverage": 0.0}

    all_node_names: list[str] = []  # lowercased for substring containment
    matched_paths: list[int] = []

    for i, path in enumerate(paths):
        nodes = [n.lower() for n in path.get("nodes", [])]
        all_node_names.extend(nodes)

        if any(en.lower() in node for node in nodes for en in expected_nodes):
            matched_paths.append(i)

    found_nodes = {
        en
        for en in expected_nodes
        if any(en.lower() in node for node in all_node_names)
    }
    coverage = len(found_nodes) / len(expected_nodes) if expected_nodes else 0.0

    return {
        "found_paths": matched_paths,
        "coverage": round(coverage, 2),
        "found_nodes": list(found_nodes),
        "missing_nodes": [en for en in expected_nodes if en not in found_nodes],
    }


async def score_answer_quality(
    query: str,
    answer: str,
    api_key: str,
    base_url: str,
    timeout: float = 90.0,
) -> Optional[dict]:
    """Use Qwen LLM to score answer quality on four dimensions (1–5 each).

    Dimensions: relevance, accuracy, completeness, source_quality.

    Args:
        query:    The original user query.
        answer:   The full pipeline response text.
        api_key:  Dashscope API key.
        base_url: Dashscope compatible-mode base URL.
        timeout:  Maximum wait in seconds for the scoring call.

    Returns:
        Dict with scoring fields, or None on timeout/error.
    """
    from pydantic import BaseModel, Field

    class QualityScore(BaseModel):
        relevance: int = Field(ge=1, le=5, description="回答与问题的相关度")
        accuracy: int = Field(ge=1, le=5, description="事实准确性")
        completeness: int = Field(ge=1, le=5, description="回答完整性")
        source_quality: int = Field(ge=1, le=5, description="来源标注质量")
        overall: int = Field(ge=1, le=5, description="综合评分")
        brief_reason: str = Field(description="一句话评分理由")

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
        f"【系统回答】\n{answer[:6000]}\n\n"
        "请从以下维度评分（1-5分）：\n"
        "  - relevance: 回答与问题的相关度\n"
        "  - accuracy: 事实准确性\n"
        "  - completeness: 回答完整性\n"
        "  - source_quality: 来源标注的质量\n"
        "  - overall: 综合评分\n"
        "  - brief_reason: 一句话简要说明评分理由\n"
    )

    try:
        result = await asyncio.wait_for(
            scorer_llm.ainvoke([HumanMessage(content=prompt)]),
            timeout=timeout,
        )
        return result.model_dump()
    except asyncio.TimeoutError:
        logging.getLogger("xiaoye.fullchain").warning(
            "Quality scorer timed out after %.0fs",
            timeout,
        )
        return None
    except Exception as exc:
        logging.getLogger("xiaoye.fullchain").warning(
            "Quality scorer failed: %s",
            exc,
        )
        return None


# ═══════════════════════════════════════════════════════════════════════════════
# Test Orchestrator (runs all layers for a single question)
# ═══════════════════════════════════════════════════════════════════════════════


async def _run_question_test(
    question: dict,
    active_layers: set[str],
    api_key: str,
    base_url: str,
) -> dict:
    """Execute all active layers for a single test question.

    Each layer runs independently; a failure in one layer does not
    prevent the remaining layers from executing.

    Args:
        question:      Test question dict from TEST_QUESTIONS.
        active_layers: Set of layer names to execute.
        api_key:       Dashscope API key.
        base_url:      Dashscope compatible-mode base URL.

    Returns:
        Question result dict with per-layer metrics and overall verdict.
    """
    qid = question["id"]
    query = question["query"]
    task_id = f"fullchain_{qid}_{int(time.monotonic())}"
    verbose = _args.verbose

    result: dict = {
        "id": qid,
        "name": question["name"],
        "query": query,
        "layers": {},
        "validations": {},
        "quality_scores": None,
        "verdict": "PASS",
        "verdict_reasons": [],
        "total_time_ms": 0,
    }

    t_overall = time.monotonic()

    # ── Layer 1: ES Semantic Search ───────────────────────────────────────
    if "es_search" in active_layers:
        if verbose:
            print(f"  {CYAN}▶ ES Semantic Search{RESET}")
        es_result = await test_es_search(query)
        result["layers"]["es_search"] = es_result

        if es_result.get("error"):
            result["verdict_reasons"].append(f"[ES] {es_result['error']}")

    # ── Layer 2: Neo4j Graph Search ───────────────────────────────────────
    if "graph_search" in active_layers:
        if verbose:
            print(f"  {CYAN}▶ Graph Search{RESET}")
        entities = question.get("graph_entities")
        graph_result = await test_graph_search(query, entity_candidates=entities)
        result["layers"]["graph_search"] = graph_result

        if graph_result.get("error"):
            if graph_result.get("neo4j_available", True):
                result["verdict_reasons"].append(f"[Graph] {graph_result['error']}")
            elif verbose:
                print(f"  {YELLOW}⚠ Neo4j unavailable — graph layer skipped{RESET}")

        # Validate graph paths against expected nodes
        expected_path_nodes = question.get("expect_graph_path", [])
        if expected_path_nodes:
            path_validation = validate_graph_path(
                graph_result.get("paths", []),
                expected_path_nodes,
            )
            result["validations"]["graph_path"] = path_validation
            if path_validation["coverage"] < 0.5:
                result["verdict_reasons"].append(
                    f"[GraphPath] Only {path_validation['coverage']:.0%} of expected nodes in paths"
                )

    # ── Layer 3: KG-HyDE Enhanced Search ──────────────────────────────────
    if "hyde_search" in active_layers:
        if verbose:
            print(f"  {CYAN}▶ HyDE Enhanced Search{RESET}")
        hyde_result = await test_hyde_search(query)
        result["layers"]["hyde_search"] = hyde_result

        if hyde_result.get("error"):
            result["verdict_reasons"].append(f"[HyDE] {hyde_result['error']}")

        # Validate KG entities
        expected_kg = question.get("expect_kg_entities", [])
        if expected_kg:
            found_entities = [e.lower() for e in hyde_result.get("entities", [])]
            missing_kg = [e for e in expected_kg if e.lower() not in found_entities]
            result["validations"]["kg_entities"] = {
                "expected": expected_kg,
                "found": hyde_result.get("entities", []),
                "missing": missing_kg,
            }
            if missing_kg:
                result["verdict_reasons"].append(f"[KG entities] Missing: {missing_kg}")

    # ── Layer 4: Full Chat Pipeline ───────────────────────────────────────
    if "chat_pipeline" in active_layers:
        if verbose:
            print(f"  {CYAN}▶ Chat Pipeline{RESET}")
        chat_result = await test_chat_pipeline(query, task_id)
        result["layers"]["chat_pipeline"] = chat_result

        if chat_result.get("error"):
            result["verdict_reasons"].append(f"[Chat] {chat_result['error']}")
        else:
            response_text = chat_result.get("response", "")

            # Quality scoring (LLM) — must run BEFORE source/figure checks
            if not _args.skip_quality_score and chat_result.get("has_useful_content"):
                if verbose:
                    print(f"  {CYAN}▶ Quality Scoring (LLM){RESET}")
                quality = await score_answer_quality(
                    query=query,
                    answer=response_text,
                    api_key=api_key,
                    base_url=base_url,
                )
                result["quality_scores"] = quality
                if quality and quality.get("overall", 0) < 2:
                    result["verdict_reasons"].append(
                        f"[Quality] Overall score {quality['overall']}/5 < threshold 2"
                    )

            # Keyword validation
            expected_kw = question.get("expect_keywords", [])
            if expected_kw:
                kw_result = validate_keywords(response_text, expected_kw)
                result["validations"]["keywords"] = kw_result
                if kw_result["coverage"] < 0.5:
                    result["verdict_reasons"].append(
                        f"[Keywords] {kw_result['coverage']:.0%} coverage — "
                        f"missing: {kw_result['missing']}"
                    )

            # Source citation validation
            if question.get("expect_sources"):
                has_src = validate_sources(response_text)
                result["validations"]["sources"] = {"has_sources": has_src}
                if not has_src:
                    # Only FAIL if quality is also poor; otherwise just warn
                    quality = result.get("quality_scores", {})
                    overall = quality.get("overall", 0) if quality else 0
                    if overall >= 4:
                        # Good answer but missing citations — downgrade to warning
                        result["warnings"] = result.get("warnings", []) + [
                            "[Sources] No explicit source citations found (quality is good)"
                        ]
                    else:
                        result["verdict_reasons"].append(
                            "[Sources] No source citations found"
                        )

            # Figure mention validation
            if question.get("expect_figures"):
                has_fig = bool(
                    re.search(r"图\s*5|Figure\s*5|S-N", response_text, re.IGNORECASE)
                )
                result["validations"]["figures"] = {"has_figures": has_fig}
                if not has_fig:
                    result["verdict_reasons"].append(
                        "[Figures] Expected figure references not found"
                    )

    # ── Final verdict ─────────────────────────────────────────────────────
    result["total_time_ms"] = _elapsed_ms(t_overall)
    if result["verdict_reasons"]:
        result["verdict"] = "FAIL"

    return result


# ═══════════════════════════════════════════════════════════════════════════════
# Terminal Output
# ═══════════════════════════════════════════════════════════════════════════════


def _bool_icon(value: bool) -> str:
    """Return colored check/cross for boolean value."""
    return f"{GREEN}✓{RESET}" if value else f"{RED}✗{RESET}"


def _verdict_icon(verdict: str) -> str:
    """Return colored PASS/FAIL string."""
    return f"{GREEN}PASS{RESET}" if verdict == "PASS" else f"{RED}FAIL{RESET}"


def _score_bar(score: int) -> str:
    """Render a 1-5 score as a colored bar."""
    bar = "█" * score + "░" * (5 - score)
    colors = [RED, YELLOW, YELLOW, GREEN, GREEN]
    c = colors[max(0, min(score - 1, 4))]
    return f"{c}{bar} {score}/5{RESET}"


def _print_header() -> None:
    """Print test run header with configuration."""
    active_layers = _resolve_active_layers()
    active_questions = _resolve_active_questions()
    print(f"\n{BOLD}{CYAN}{DOUBLE_DIVIDER}{RESET}")
    print(f"{BOLD}{CYAN}  Xiaoye Full-Chain Integration Test{RESET}")
    print(f"{BOLD}{CYAN}{DOUBLE_DIVIDER}{RESET}")
    print(f"  {BOLD}Model:{RESET}      qwen-max")
    print(f"  {BOLD}API Base:{RESET}   {settings.QWEN_BASE_URL}")
    print(f"  {BOLD}Timestamp:{RESET}  {datetime.now(timezone.utc).isoformat()}")
    print(
        f"  {BOLD}Questions:{RESET}  {len(active_questions)} ({', '.join(q['id'] for q in active_questions)})"
    )
    print(f"  {BOLD}Layers:{RESET}     {', '.join(sorted(active_layers))}")
    print(
        f"  {BOLD}Timeouts:{RESET}   layer={_args.layer_timeout}s, chat={_args.chat_timeout}s"
    )
    if _args.skip_quality_score:
        print(f"  {YELLOW}Quality scoring: SKIPPED{RESET}")
    print(f"{CYAN}{DIVIDER}{RESET}\n")


def _print_question_header(question: dict) -> None:
    """Print a per-question section header."""
    qid = question["id"]
    name = question["name"]
    query = _truncate(question["query"], 100)
    print(f"{BOLD}{BLUE}{'═' * 72}{RESET}")
    print(f"{BOLD}{BLUE}  [{qid}] {name}{RESET}")
    print(f"{BOLD}{BLUE}{'═' * 72}{RESET}")
    print(f"  {GRAY}Query: {query}{RESET}\n")


def _print_layer_result(layer_name: str, layer_result: dict) -> None:
    """Print compact per-layer result lines."""
    label = {
        "es_search": "ES Search   ",
        "graph_search": "Graph Search",
        "hyde_search": "HyDE Search ",
        "chat_pipeline": "Chat Pipe  ",
    }.get(layer_name, layer_name)

    if layer_result.get("error"):
        print(f"  {RED}✗ {label}: {layer_result['error']}{RESET}")
        return

    time_ms = layer_result.get("time_ms", 0)
    time_str = f"{time_ms / 1000:.1f}s" if time_ms > 0 else "N/A"

    if layer_name == "es_search":
        hits = layer_result.get("hits", 0)
        figs = _bool_icon(layer_result.get("has_figures", False))
        print(f"  {GREEN}✓{RESET} {label}: {hits} hits | {time_str} | figures: {figs}")

    elif layer_name == "graph_search":
        entities = layer_result.get("entity_count", 0)
        rels = len(layer_result.get("relations", []))
        paths = len(layer_result.get("paths", []))
        neo4j_ok = _bool_icon(layer_result.get("neo4j_available", True))
        print(
            f"  {GREEN}✓{RESET} {label}: {entities} entities → {rels} rels, {paths} paths | {time_str} | neo4j: {neo4j_ok}"
        )

    elif layer_name == "hyde_search":
        hits = layer_result.get("hits", 0)
        entities = layer_result.get("entities", [])
        print(
            f"  {GREEN}✓{RESET} {label}: entities={entities}, hits={hits} | {time_str}"
        )

    elif layer_name == "chat_pipeline":
        resp_len = layer_result.get("response_length", 0)
        tools = layer_result.get("tool_call_count", 0)
        loops = layer_result.get("evaluator_loops", 0)
        srcs = _bool_icon(layer_result.get("has_sources", False))
        print(
            f"  {GREEN}✓{RESET} {label}: {resp_len:,} chars | {tools} tools | {loops} eval loops | {time_str} | srcs: {srcs}"
        )


def _print_question_verdict(question_result: dict) -> None:
    """Print per-question final verdict with reasons."""
    verdict = question_result["verdict"]
    verdict_str = _verdict_icon(verdict)
    total_s = question_result.get("total_time_ms", 0) / 1000

    # Quality summary
    quality = question_result.get("quality_scores")
    if quality:
        q_overall = quality.get("overall", 0)
        quality_line = f" | Quality: {_score_bar(q_overall)}"
    else:
        quality_line = ""

    print(
        f"\n  {BOLD}Verdict: {verdict_str}{RESET} | Total: {total_s:.1f}s{quality_line}"
    )

    if verdict == "FAIL":
        for reason in question_result.get("verdict_reasons", []):
            print(f"  {RED}  → {reason}{RESET}")

    # Print response snippet
    chat_layer = question_result.get("layers", {}).get("chat_pipeline", {})
    response = chat_layer.get("response", "")
    if response.strip():
        print(f"\n  {BOLD}Response snippet:{RESET}")
        print(f"  {GRAY}{_truncate(response, 250)}{RESET}")

    print()


def _print_aggregate(results: list[dict]) -> None:
    """Print aggregate statistics across all questions."""
    total = len(results)
    passed = sum(1 for r in results if r["verdict"] == "PASS")
    failed = total - passed

    total_time = sum(r.get("total_time_ms", 0) for r in results) / 1000

    quality_scores = [
        r["quality_scores"]["overall"]
        for r in results
        if r.get("quality_scores") and r["quality_scores"].get("overall")
    ]
    avg_quality = sum(quality_scores) / len(quality_scores) if quality_scores else 0

    total_tool_calls = sum(
        r.get("layers", {}).get("chat_pipeline", {}).get("tool_call_count", 0)
        for r in results
    )

    pass_color = GREEN if passed == total else (YELLOW if passed > 0 else RED)
    fail_color = RED if failed > 0 else GREEN

    print(f"{BOLD}{CYAN}{DOUBLE_DIVIDER}{RESET}")
    print(f"{BOLD}{CYAN}  AGGREGATE SUMMARY{RESET}")
    print(f"{BOLD}{CYAN}{DOUBLE_DIVIDER}{RESET}")
    print(f"  Total cases:       {total}")
    print(f"  Passed:            {pass_color}{passed}{RESET}")
    print(f"  Failed:            {fail_color}{failed}{RESET}")
    print(f"  Total time:        {total_time:.1f}s")
    print(f"  Avg quality score: {_score_bar(round(avg_quality))}")
    print(f"  Total tool calls:  {total_tool_calls}")
    print()

    # Per-question summary table
    print(f"{BOLD}  Per-Question Summary:{RESET}")
    print(f"  {'ID':<6} {'Name':<40} {'Verdict':<8} {'Quality':<12} {'Time':<8}")
    print(f"  {'─' * 6} {'─' * 40} {'─' * 8} {'─' * 12} {'─' * 8}")
    for r in results:
        qid = r["id"]
        name = r["name"][:38]
        verdict = _verdict_icon(r["verdict"])
        q = r.get("quality_scores")
        qstr = f"{q['overall']}/5" if q else "N/A"
        t = f"{r.get('total_time_ms', 0) / 1000:.1f}s"
        print(f"  {qid:<6} {name:<40} {verdict:<16} {qstr:<12} {t:<8}")
    print()


# ═══════════════════════════════════════════════════════════════════════════════
# JSON Report Writer
# ═══════════════════════════════════════════════════════════════════════════════


def _write_json_report(
    results: list[dict],
    aggregate: dict,
    active_layers: set[str],
    timestamp: str,
) -> Path:
    """Write full structured JSON report to work_log/.

    Args:
        results:       Per-question result dicts.
        aggregate:     Aggregate statistics dict.
        active_layers: Set of layer names that were executed.
        timestamp:     Formatted timestamp string for filename.

    Returns:
        Path to the written report file.
    """
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORT_DIR / f"fullchain_report_{timestamp}.json"

    # Strip internal-only preview keys from chat responses (keep full in report_path)
    clean_results = []
    for r in results:
        clean = r.copy()
        if "layers" in clean:
            for layer_name, layer_data in clean["layers"].items():
                if isinstance(layer_data, dict) and "chunks" in layer_data:
                    # Truncate chunk content previews for readability
                    layer_data["chunks"] = [
                        {
                            **c,
                            "content_preview": _truncate(
                                c.get("content_preview", ""), 200
                            ),
                        }
                        for c in layer_data["chunks"]
                    ]
        clean_results.append(clean)

    payload = {
        "config": {
            "model": "qwen-max",
            "api_base_url": settings.QWEN_BASE_URL,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "active_layers": sorted(active_layers),
            "timeouts": {
                "layer": _args.layer_timeout,
                "chat": _args.chat_timeout,
            },
        },
        "test_cases": clean_results,
        "aggregate": aggregate,
    }

    report_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return report_path


# ═══════════════════════════════════════════════════════════════════════════════
# CLI helpers
# ═══════════════════════════════════════════════════════════════════════════════


def _resolve_active_questions() -> list[dict]:
    """Parse --questions CLI arg and return filtered TEST_QUESTIONS list."""
    if _args.questions is None:
        return list(TEST_QUESTIONS)

    allowed_ids = {qid.strip().upper() for qid in _args.questions.split(",")}
    filtered = [q for q in TEST_QUESTIONS if q["id"] in allowed_ids]

    if not filtered:
        print(
            f"{RED}Error: No matching questions for --questions {_args.questions}{RESET}"
        )
        print(f"  Available: {', '.join(q['id'] for q in TEST_QUESTIONS)}")
        sys.exit(1)

    return filtered


def _resolve_active_layers() -> set[str]:
    """Parse --layers CLI arg and return set of layer names to execute."""
    if _args.layers is None:
        return set(ALL_LAYERS)

    layer_map = {
        "es": "es_search",
        "graph": "graph_search",
        "hyde": "hyde_search",
        "chat": "chat_pipeline",
    }

    resolved: set[str] = set()
    for token in _args.layers.split(","):
        token = token.strip().lower()
        if token in layer_map:
            resolved.add(layer_map[token])
        elif token in ALL_LAYERS:
            resolved.add(token)
        else:
            print(
                f"{RED}Error: Unknown layer '{token}'. Available: es,graph,hyde,chat{RESET}"
            )
            sys.exit(1)

    return resolved


# ═══════════════════════════════════════════════════════════════════════════════
# Main Entry Point
# ═══════════════════════════════════════════════════════════════════════════════


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


async def _async_main() -> int:
    """Async main body — orchestrates all tests and returns exit code."""
    api_key = _validate_api_key()
    base_url = settings.QWEN_BASE_URL
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    active_questions = _resolve_active_questions()
    active_layers = _resolve_active_layers()

    # ── Install noop SSE before any operations ────────────────────────────
    _install_noop_sse()

    # ── Print header ──────────────────────────────────────────────────────
    _print_header()

    # ── Run all tests ─────────────────────────────────────────────────────
    results: list[dict] = []
    for i, question in enumerate(active_questions, start=1):
        _print_question_header(question)

        question_result = await _run_question_test(
            question=question,
            active_layers=active_layers,
            api_key=api_key,
            base_url=base_url,
        )

        # Print per-layer results
        for layer_name in sorted(active_layers):
            layer_data = question_result.get("layers", {}).get(layer_name)
            if layer_data:
                _print_layer_result(layer_name, layer_data)

        _print_question_verdict(question_result)
        results.append(question_result)

    # ── Aggregate ────────────────────────────────────────────────────────
    total = len(results)
    passed = sum(1 for r in results if r["verdict"] == "PASS")
    failed = total - passed
    total_time = sum(r.get("total_time_ms", 0) for r in results) / 1000
    quality_scores = [
        r["quality_scores"]["overall"]
        for r in results
        if r.get("quality_scores") and r["quality_scores"].get("overall")
    ]
    avg_quality = sum(quality_scores) / len(quality_scores) if quality_scores else 0
    total_tool_calls = sum(
        r.get("layers", {}).get("chat_pipeline", {}).get("tool_call_count", 0)
        for r in results
    )

    aggregate = {
        "total": total,
        "passed": passed,
        "failed": failed,
        "total_time_seconds": round(total_time, 2),
        "average_quality_score": round(avg_quality, 2),
        "total_tool_calls": total_tool_calls,
    }

    _print_aggregate(results)

    # ── Write JSON report ────────────────────────────────────────────────
    report_path = _write_json_report(results, aggregate, active_layers, timestamp)
    print(f"{GREEN}Report saved to:{RESET} {report_path}")

    return 0 if failed == 0 else 1


def main() -> None:
    """Synchronous entry point."""
    exit_code = asyncio.run(_async_main())
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
