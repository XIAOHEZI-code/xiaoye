# 富媒体 Chunk 数据结构定义
# 单一职责：定义 RAG 管线中从入库到检索到展示的统一数据契约

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional, Literal, List
from uuid import uuid4


@dataclass
class BoundingBox:
    """PDF 页面上的矩形区域坐标（归一化到 0-1 或绝对像素值）"""
    x0: float
    y0: float
    x1: float
    y1: float

    def to_dict(self) -> dict:
        return {"x0": self.x0, "y0": self.y0, "x1": self.x1, "y1": self.y1}

    @classmethod
    def from_dict(cls, d: dict) -> "BoundingBox":
        return cls(x0=d["x0"], y0=d["y0"], x1=d["x1"], y1=d["y1"])


# 支持的 Chunk 内容类型
ChunkType = Literal["text", "table", "figure", "formula"]


@dataclass
class ChunkDocument:
    """
    富媒体 Chunk 数据结构 — 贯穿入库、检索、展示三层的统一契约。

    设计原则（参考 Claude Code 的 WorkResponse 数据结构设计）：
    - 每个 Chunk 必须能被精准溯源到 PDF 的具体页面与矩形区域
    - 图片 / 表格类 Chunk 必须携带原始介质的存储地址
    - 所有字段均可被 JSON 序列化，以兼容 Elasticsearch 和前端渲染
    """

    # === 身份标识 ===
    chunk_id: str = field(default_factory=lambda: f"chunk_{uuid4().hex[:12]}")
    doc_id: str = ""                     # 所属文档的全局 ID

    # === 内容主体 ===
    text_content: str = ""               # 文本内容（Markdown 格式）
    chunk_type: ChunkType = "text"       # 内容类型

    # === 溯源坐标 ===
    source_pdf_id: str = ""              # 原始 PDF 文件标识（文件名或 UUID）
    page_number: int = -1                # 所在页码（1-indexed，-1 表示未知）
    bbox: Optional[BoundingBox] = None   # 在 PDF 页面上的矩形定位区域

    # === 富媒体附件 ===
    image_uri: Optional[str] = None      # 图片/表格截图的存储路径（本地路径或 S3 URI）

    # === 检索增强（由检索层填充，入库时不需要） ===
    score: Optional[float] = None        # RRF / 相似度得分
    source_type: str = "text_chunk"      # 兼容旧字段：text_chunk | image_description

    def to_dict(self) -> dict:
        """序列化为可存入 Elasticsearch 的扁平字典"""
        d = {
            "chunk_id": self.chunk_id,
            "doc_id": self.doc_id,
            "content": self.text_content,
            "chunk_type": self.chunk_type,
            "source_pdf_id": self.source_pdf_id,
            "page_number": self.page_number,
            "bbox": self.bbox.to_dict() if self.bbox else None,
            "image_uri": self.image_uri,
            "source_type": self.source_type,
        }
        return d

    @classmethod
    def from_es_hit(cls, source: dict, score: float = 0.0) -> "ChunkDocument":
        """从 Elasticsearch _source 文档反序列化"""
        bbox_raw = source.get("bbox")
        return cls(
            chunk_id=source.get("chunk_id", ""),
            doc_id=source.get("doc_id", ""),
            text_content=source.get("content", ""),
            chunk_type=source.get("chunk_type", "text"),
            source_pdf_id=source.get("source_pdf_id", ""),
            page_number=source.get("page_number", -1),
            bbox=BoundingBox.from_dict(bbox_raw) if bbox_raw else None,
            image_uri=source.get("image_uri"),
            score=score,
            source_type=source.get("source_type", "text_chunk"),
        )

    def to_citation_str(self) -> str:
        """生成供 LLM 引用的简洁来源标注字符串"""
        parts = []
        if self.source_pdf_id:
            parts.append(self.source_pdf_id)
        if self.page_number > 0:
            parts.append(f"p.{self.page_number}")
        if self.chunk_type != "text":
            parts.append(f"[{self.chunk_type}]")
        return f"[来源: {', '.join(parts)}]" if parts else "[来源: 未知]"


# === 便捷工厂函数 ===

def make_text_chunk(
    text: str,
    doc_id: str,
    source_pdf_id: str,
    page_number: int = -1,
    bbox: Optional[BoundingBox] = None,
) -> ChunkDocument:
    """快速创建文本类型的 ChunkDocument"""
    return ChunkDocument(
        doc_id=doc_id,
        text_content=text,
        chunk_type="text",
        source_pdf_id=source_pdf_id,
        page_number=page_number,
        bbox=bbox,
        source_type="text_chunk",
    )


def make_image_chunk(
    description: str,
    doc_id: str,
    source_pdf_id: str,
    image_uri: str,
    page_number: int = -1,
    bbox: Optional[BoundingBox] = None,
    chunk_type: ChunkType = "figure",
) -> ChunkDocument:
    """快速创建图片/图表类型的 ChunkDocument"""
    return ChunkDocument(
        doc_id=doc_id,
        text_content=description,
        chunk_type=chunk_type,
        source_pdf_id=source_pdf_id,
        page_number=page_number,
        bbox=bbox,
        image_uri=image_uri,
        source_type="image_description",
    )
