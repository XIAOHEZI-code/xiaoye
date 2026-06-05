"""
PDF 解析流水线 — Marker-PDF 封装 + 图注增强

V2 增强（2026-04-26）：
  - 新增 process_figures(): 从 Markdown 提取图片引用，关联图注/上下文
  - 新增 enhance_chunks_with_figures(): 将增强后的图片 Chunk 合并到文本 Chunk 列表
  - 集成 figure_extractor.py + image_analyzer.py 的上下文感知分析
"""

import os
import subprocess
import glob
from typing import Tuple, List, Optional
from src.models.chunk_document import ChunkDocument
from src.ingestion.figure_extractor import (
    extract_figures_from_markdown,
    FigureInfo,
    is_figure_item,
)


def extract_pdf_with_marker(filepath: str, out_dir: str) -> Tuple[str, List[str], dict]:
    """
    Extracts Markdown, images, and metadata from a PDF using marker CLI.
    """
    if not os.path.exists(out_dir):
        os.makedirs(out_dir)

    print(f"Running Marker-PDF CLI for: {filepath}")

    # Marker 1.0+ CLI syntax
    import sys

    marker_bin = os.path.join(sys.prefix, "bin", "marker_single")
    cmd = [marker_bin, filepath, "--output_dir", out_dir]

    # Marker / Surya VRAM Optimization for ~8GB GPU
    env = os.environ.copy()
    env["DETECTOR_BATCH_SIZE"] = "2"
    env["RECOGNITION_BATCH_SIZE"] = "2"
    env["LAYOUT_BATCH_SIZE"] = "2"
    env["TABLE_REC_BATCH_SIZE"] = "2"
    env["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"

    result = subprocess.run(cmd, env=env, capture_output=True, text=True)
    if result.returncode != 0:
        print("Marker extraction failed:")
        print(result.stderr)
        raise RuntimeError(f"Marker failed with return code {result.returncode}")

    print("Marker-PDF extraction completed successfully.")

    # Locate generated markdown file and metadata in out_dir/<basename>
    basename = os.path.splitext(os.path.basename(filepath))[0]
    result_dir = os.path.join(out_dir, basename)

    if os.path.exists(result_dir):
        # Marker creates a subdirectory with the basename
        md_file = os.path.join(result_dir, f"{basename}.md")
        meta_file = os.path.join(result_dir, f"{basename}_meta.json")
        image_dir = result_dir
    else:
        # Fallback if no subdirectory was created
        md_file = os.path.join(out_dir, f"{basename}.md")
        meta_file = os.path.join(out_dir, f"{basename}_meta.json")
        image_dir = out_dir

    # Read text
    md_text = ""
    if os.path.exists(md_file):
        with open(md_file, "r", encoding="utf-8") as f:
            md_text = f.read()

    # Read meta
    import json

    out_metadata = {}
    if os.path.exists(meta_file):
        with open(meta_file, "r", encoding="utf-8") as f:
            out_metadata = json.load(f)

    # Gather images
    images = (
        glob.glob(os.path.join(image_dir, "*.png"))
        + glob.glob(os.path.join(image_dir, "*.webp"))
        + glob.glob(os.path.join(image_dir, "*.jpg"))
        + glob.glob(os.path.join(image_dir, "*.jpeg"))
    )
    images = [os.path.abspath(img) for img in images]

    return md_text, images, out_metadata


def _get_page_from_toc(chunk_text: str, toc_entries: list) -> int:
    """Find which page a chunk belongs to by matching against TOC section titles.

    Strategy: Find the last TOC entry whose title appears in the chunk text or
    appears earlier in the markdown, and return its page_id (converted to 1-indexed).
    """
    if not toc_entries:
        return -1

    import re

    clean_chunk = re.sub(r"[#*`\[\]()>_~\\|]", "", chunk_text[:500]).strip()

    best_page = -1
    best_pos = -1

    for entry in toc_entries:
        title = entry.get("title", "")
        page_id = entry.get("page_id", -1)
        if not title or page_id < 0:
            continue
        pos = clean_chunk.find(title)
        if pos >= 0 and (best_pos < 0 or pos < best_pos):
            best_pos = pos
            best_page = page_id + 1  # Convert 0-indexed to 1-indexed

    return best_page


def _build_page_map(md_text: str, toc_entries: list) -> list[int]:
    """构建 Markdown 每一行的页码映射表。

    数据源（优先级从高到低）：
    1. 图片引用锚点: ![](_page_N_xxx) → 该行属于第 N+1 页 (Marker 页码0-indexed)
    2. TOC 标题锚点: 行文本匹配到 TOC entry 的 title → 使用该 entry 的 page_id+1
    3. 前向继承: 未匹配到任何锚点的行 → 继承上一个已知页码

    Returns:
        list[int]: 与 md_text.split('\\n') 等长的页码列表 (1-indexed, -1=未知)
    """
    import re

    lines = md_text.split("\n")
    page_map = [-1] * len(lines)

    # Pass 1: 图片引用锚点 — ![](_page_N_xxx.jpeg)
    img_pattern = re.compile(r"!\[.*?\]\(.*?_page_(\d+)_.*?\)")
    for i, line in enumerate(lines):
        m = img_pattern.search(line)
        if m:
            page_map[i] = int(m.group(1)) + 1  # 0-indexed → 1-indexed

    # Pass 2: TOC 标题匹配
    if toc_entries:
        # 按 page_id 排序，确保从前到后
        sorted_toc = sorted(
            [e for e in toc_entries if e.get("title") and e.get("page_id", -1) >= 0],
            key=lambda e: e["page_id"],
        )
        for i, line in enumerate(lines):
            if page_map[i] > 0:
                continue  # 已被图片锚点标注
            clean_line = re.sub(r"[#*`\[\]()>_~\\|]", "", line).strip()
            if not clean_line or len(clean_line) < 2:
                continue
            for entry in sorted_toc:
                title = entry["title"].strip()
                if len(title) >= 2 and title in clean_line:
                    page_map[i] = entry["page_id"] + 1
                    break

    # Pass 3: 前向继承 — 未标注的行继承上一个已知页码
    # 第一页默认从 page 1 开始
    last_known = 1
    for i in range(len(page_map)):
        if page_map[i] > 0:
            last_known = page_map[i]
        else:
            page_map[i] = last_known

    return page_map


def _get_chunk_page(chunk_start_line: int, chunk_end_line: int, page_map: list[int]) -> int:
    """从 page_map 中取 chunk 覆盖行范围内出现最多的页码（众数策略）。"""
    from collections import Counter

    start = max(0, chunk_start_line)
    end = min(len(page_map), chunk_end_line + 1)
    if start >= end:
        return page_map[start] if start < len(page_map) else -1

    pages_in_range = page_map[start:end]
    counter = Counter(pages_in_range)
    # 返回出现次数最多的页码
    return counter.most_common(1)[0][0]


def split_markdown_into_chunk_documents(
    md_text: str,
    out_metadata: dict,
    doc_id: str,
    source_pdf_id: str,
    chunk_size: int = 1000,
    chunk_overlap: int = 200,
) -> List[ChunkDocument]:
    from src.models.chunk_document import make_text_chunk

    chunks = []

    import jieba

    # Build page map for accurate page number assignment
    toc_entries = out_metadata.get("table_of_contents", []) if out_metadata else []
    page_map = _build_page_map(md_text, toc_entries)

    # Track line positions for each paragraph
    lines = md_text.split("\n")
    # Build paragraph → line range mapping
    # Paragraphs are separated by double newlines (\n\n = empty line between blocks)
    paragraphs = md_text.split("\n\n")

    # Calculate the starting line index of each paragraph
    para_start_lines = []
    current_line = 0
    for p in paragraphs:
        para_start_lines.append(current_line)
        # Each paragraph spans its own lines + 1 empty line separator (except last)
        current_line += p.count("\n") + 1 + 1  # +1 for lines in paragraph, +1 for \n\n separator

    current_chunk = ""
    chunk_start_para = 0  # Index into paragraphs[] for current chunk's start

    for para_idx, p in enumerate(paragraphs):
        if len(current_chunk) + len(p) > chunk_size and current_chunk:
            # Determine line range for this chunk
            chunk_start_line = para_start_lines[chunk_start_para]
            chunk_end_line = para_start_lines[para_idx] - 1 if para_idx < len(para_start_lines) else len(lines) - 1
            page_number = _get_chunk_page(chunk_start_line, chunk_end_line, page_map)

            doc = make_text_chunk(
                text=current_chunk,
                doc_id=doc_id,
                source_pdf_id=source_pdf_id,
                page_number=page_number,
                bbox=None,
            )
            chunks.append(doc)
            # Take overlap: simple string slicing for prototyping
            if chunk_overlap > 0:
                current_chunk = current_chunk[-chunk_overlap:] + "\n\n" + p
                # After overlap, the new chunk conceptually starts from this paragraph
                chunk_start_para = para_idx
            else:
                current_chunk = p
                chunk_start_para = para_idx
        else:
            current_chunk += ("\n\n" + p) if current_chunk else p

    if current_chunk.strip():
        chunk_start_line = para_start_lines[chunk_start_para] if chunk_start_para < len(para_start_lines) else 0
        chunk_end_line = len(lines) - 1
        page_number = _get_chunk_page(chunk_start_line, chunk_end_line, page_map)

        doc = make_text_chunk(
            text=current_chunk,
            doc_id=doc_id,
            source_pdf_id=source_pdf_id,
            page_number=page_number,
            bbox=None,
        )
        chunks.append(doc)

    return chunks


# =============================================================
#  V2 新增：图注提取与上下文感知图像分析
# =============================================================


def process_figures(
    md_text: str,
    image_paths: List[str],
    doc_id: str,
    source_pdf_id: str,
    image_dir: str = "",
    analyze_with_vlm: bool = False,
) -> List[ChunkDocument]:
    """从 Markdown 中提取图片，关联图注和上下文，生成增强的图像 Chunk。

    双模式：
    - analyze_with_vlm=True: 调用 Qwen-VL 进行上下文感知分析（需 API Key）
    - analyze_with_vlm=False: 仅提取图注和上下文，不做 VL 分析（节省 API 调用）

    Args:
        md_text: Marker-PDF 输出的完整 Markdown 文本
        image_paths: Marker 提取的图片文件路径列表
        doc_id: 文档 ID
        source_pdf_id: 源 PDF 标识（文件名或 UUID）
        image_dir: 图片目录（用于解析相对路径）
        analyze_with_vlm: 是否调用 Qwen-VL 分析图片

    Returns:
        增强后的 Image ChunkDocument 列表
    """
    from src.models.chunk_document import make_image_chunk

    # 1. 从 Markdown 提取图片引用 + 图注 + 上下文
    figures = extract_figures_from_markdown(
        md_text=md_text,
        image_dir=image_dir,
    )

    if not figures:
        # 降级：如果 Markdown 中没有图片引用，直接用文件列表创建基础 chunk
        print(
            f"[process_figures] 未在 Markdown 中找到图片引用，"
            f"使用文件列表 ({len(image_paths)} 张)"
        )
        return _create_basic_image_chunks(image_paths, doc_id, source_pdf_id)

    # 2. 过滤出有意义的图表（有图注或关键词的）
    meaningful = [f for f in figures if is_figure_item(f)]
    print(
        f"[process_figures] 提取到 {len(figures)} 张图片引用，"
        f"其中 {len(meaningful)} 张为有意义图表"
    )

    # 3. 为每个有意义的图片创建增强 chunk
    result_chunks = []

    if analyze_with_vlm:
        # 模式 A: 调用 Qwen-VL 分析
        result_chunks = _analyze_figures_with_vlm(meaningful, doc_id, source_pdf_id)
    else:
        # 模式 B: 仅使用图注和上下文创建描述
        for fig in meaningful:
            # 构建描述文本（图注 + 上下文摘要）
            desc_parts = []
            if fig.caption:
                desc_parts.append(f"【图注】{fig.caption}")
            if fig.context_above:
                desc_parts.append(f"【上文】{fig.context_above[-100:]}")
            if fig.context_below:
                desc_parts.append(f"【下文】{fig.context_below[:100]}")
            description = (
                "\n\n".join(desc_parts) if desc_parts else f"图片: {fig.image_filename}"
            )

            chunk = make_image_chunk(
                description=description,
                doc_id=doc_id,
                source_pdf_id=source_pdf_id,
                image_uri=fig.image_path,
                chunk_type="figure",
            )
            result_chunks.append(chunk)

    # 4. 添加剩余未在 Markdown 中找到引用的图片（作为补充）
    referenced_paths = {f.image_path for f in figures}
    unreferenced = [p for p in image_paths if p not in referenced_paths]
    if unreferenced:
        print(
            f"[process_figures] 另有 {len(unreferenced)} 张图片未在 Markdown 中找到引用"
        )
        result_chunks.extend(
            _create_basic_image_chunks(unreferenced, doc_id, source_pdf_id)
        )

    return result_chunks


def _create_basic_image_chunks(
    image_paths: List[str],
    doc_id: str,
    source_pdf_id: str,
) -> List[ChunkDocument]:
    """为图片文件创建基础的 Image Chunk（无分析）。

    Args:
        image_paths: 图片文件路径列表
        doc_id: 文档 ID
        source_pdf_id: 源 PDF 标识

    Returns:
        基础 Image ChunkDocument 列表
    """
    from src.models.chunk_document import make_image_chunk

    chunks = []
    for img_path in image_paths:
        chunk = make_image_chunk(
            description=f"Extracted image from {source_pdf_id}",
            doc_id=doc_id,
            source_pdf_id=source_pdf_id,
            image_uri=img_path,
            chunk_type="figure",
        )
        chunks.append(chunk)
    return chunks


def _analyze_figures_with_vlm(
    figures: List["FigureInfo"],
    doc_id: str,
    source_pdf_id: str,
) -> List[ChunkDocument]:
    """调用 Qwen-VL 对图片进行上下文感知分析。

    使用增强后的 analyze_metallurgy_image_with_context()，
    将图注和上下文传入 Prompt。

    Args:
        figures: 图片信息列表
        doc_id: 文档 ID
        source_pdf_id: 源 PDF 标识

    Returns:
        经 VLM 分析后的 Image ChunkDocument 列表
    """
    from src.models.chunk_document import make_image_chunk
    from src.ingestion.image_analyzer import analyze_metallurgy_image_with_context
    import base64

    chunks = []
    for fig in figures:
        try:
            # 读取图片文件并转为 Base64
            with open(fig.image_path, "rb") as f:
                img_data = f.read()
            img_b64 = base64.b64encode(img_data).decode("utf-8")

            # 上下文感知分析
            result = analyze_metallurgy_image_with_context(
                image_base64=img_b64,
                caption=fig.caption if fig.caption else None,
                context_above=fig.context_above if fig.context_above else None,
                context_below=fig.context_below if fig.context_below else None,
            )

            # 构建描述文本（VLM 分析结果 + 图注）
            desc_parts = []
            if fig.caption:
                desc_parts.append(f"**{fig.caption}**")
            desc_parts.append(f"分类: {result.category}/{result.sub_category}")
            desc_parts.append(f"描述: {result.description}")
            if result.key_metrics:
                desc_parts.append(f"关键指标: {', '.join(result.key_metrics)}")

            description = "\n\n".join(desc_parts)

            chunk = make_image_chunk(
                description=description,
                doc_id=doc_id,
                source_pdf_id=source_pdf_id,
                image_uri=fig.image_path,
                chunk_type="figure",
            )
            chunks.append(chunk)
            print(
                f"  ✓ 已分析: {fig.image_filename} → {result.category}/{result.sub_category}"
            )

        except Exception as e:
            print(f"  ✗ 分析失败: {fig.image_filename}: {e}")
            # 降级：使用图注信息作为描述
            desc = fig.caption if fig.caption else f"图片: {fig.image_filename}"
            chunk = make_image_chunk(
                description=desc,
                doc_id=doc_id,
                source_pdf_id=source_pdf_id,
                image_uri=fig.image_path,
                chunk_type="figure",
            )
            chunks.append(chunk)

    return chunks


def enhance_chunks_with_figures(
    text_chunks: List[ChunkDocument],
    figure_chunks: List[ChunkDocument],
) -> List[ChunkDocument]:
    """将文本 Chunk 和图片 Chunk 合并，按文档顺序排列。

    参考 RAGFlow 的 insert_table_figures 思路：
    将图片 Chunk 插入到其引用的文本位置附近。
    目前简单策略：图片 chunk 放在文本 chunk 之后。

    Args:
        text_chunks: 文本 Chunk 列表
        figure_chunks: 图片 Chunk 列表

    Returns:
        合并后的完整 Chunk 列表
    """
    return text_chunks + figure_chunks
