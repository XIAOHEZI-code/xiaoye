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
    cmd = [
        marker_bin,
        filepath,
        "--output_dir", out_dir
    ]
    
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
    images = glob.glob(os.path.join(image_dir, "*.png")) + glob.glob(os.path.join(image_dir, "*.webp"))
    images = [os.path.abspath(img) for img in images]

    return md_text, images, out_metadata


def split_markdown_into_chunk_documents(
    md_text: str,
    out_metadata: dict,
    doc_id: str,
    source_pdf_id: str,
    chunk_size: int = 1000,
    chunk_overlap: int = 200
) -> List[ChunkDocument]:
    from src.models.chunk_document import make_text_chunk
    
    chunks = []
    
    import jieba
    # Simple semantic splitting based on double newlines
    paragraphs = md_text.split('\n\n')
    
    current_chunk = ""
    for p in paragraphs:
        if len(current_chunk) + len(p) > chunk_size and current_chunk:
            page_number = -1
            bbox = None
            
            if out_metadata and "blocks" in out_metadata:
                # Naive matching of the first 20 chars of chunk to blocks
                sample = current_chunk[:20].strip()
                for b in out_metadata["blocks"]:
                    if sample in b.get("text", ""):
                        if "pnums" in b and len(b["pnums"]) > 0:
                            page_number = b["pnums"][0]
                        if "bbox" in b:
                            bbox = b["bbox"]
                        break
            
            doc = make_text_chunk(
                text=current_chunk,
                doc_id=doc_id,
                source_pdf_id=source_pdf_id,
                page_number=page_number,
                bbox=bbox
            )
            chunks.append(doc)
            # Take overlap: simple string slicing for prototyping
            current_chunk = current_chunk[-chunk_overlap:] + "\n\n" + p if chunk_overlap > 0 else p
        else:
            current_chunk += ("\n\n" + p) if current_chunk else p
            
    if current_chunk.strip():
        page_number = -1
        bbox = None
        doc = make_text_chunk(
            text=current_chunk,
            doc_id=doc_id,
            source_pdf_id=source_pdf_id,
            page_number=page_number,
            bbox=bbox
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
        print(f"[process_figures] 未在 Markdown 中找到图片引用，"
              f"使用文件列表 ({len(image_paths)} 张)")
        return _create_basic_image_chunks(image_paths, doc_id, source_pdf_id)

    # 2. 过滤出有意义的图表（有图注或关键词的）
    meaningful = [f for f in figures if is_figure_item(f)]
    print(f"[process_figures] 提取到 {len(figures)} 张图片引用，"
          f"其中 {len(meaningful)} 张为有意义图表")

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
            description = "\n\n".join(desc_parts) if desc_parts else f"图片: {fig.image_filename}"

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
        print(f"[process_figures] 另有 {len(unreferenced)} 张图片未在 Markdown 中找到引用")
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
            print(f"  ✓ 已分析: {fig.image_filename} → {result.category}/{result.sub_category}")

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
