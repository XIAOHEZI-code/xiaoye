import pytest
from unittest.mock import patch, MagicMock
from src.ingestion.pdf_parser import (
    split_markdown_into_chunk_documents,
    process_figures,
)

# ==========================================
# 测试数据 (Fixtures)
# ==========================================
DUMMY_MD = """# Introduction
This is the first paragraph.
We reference an image here: ![](_page_1_Figure_1.png)

## Method
This is the method section.
Second paragraph of method.

# Results
Results are great.
"""

DUMMY_METADATA = {
    "table_of_contents": [
        {"title": "Introduction", "page_id": 0},
        {"title": "Method", "page_id": 1},
        {"title": "Results", "page_id": 2},
    ]
}

# ==========================================
# 测试用例 (Test Cases)
# ==========================================


@pytest.mark.small
def test_split_markdown_into_chunk_documents():
    """测试 Markdown 文本切块与页码映射逻辑 (禁止读写真实PDF)"""
    chunks = split_markdown_into_chunk_documents(
        md_text=DUMMY_MD,
        out_metadata=DUMMY_METADATA,
        doc_id="doc_123",
        source_pdf_id="test.pdf",
        chunk_size=50,  # 故意设置较小的 chunk_size 以触发切块
        chunk_overlap=10,
    )

    assert len(chunks) > 0, "应该生成至少一个以上的 Chunk"

    # 验证基础元数据
    assert chunks[0].doc_id == "doc_123"
    assert chunks[0].source_pdf_id == "test.pdf"

    # 验证页码推断逻辑 (Introduction 是 page_id=0，映射后应为页码1)
    assert chunks[0].page_number >= 1, "首个块的页码应该不小于1"

    # 验证文本截断
    assert len(chunks[0].text_content) > 0


@patch("src.ingestion.pdf_parser.is_figure_item")
@patch("src.ingestion.pdf_parser.extract_figures_from_markdown")
@pytest.mark.small
def test_process_figures_without_vlm(mock_extract, mock_is_figure):
    """测试纯文本图注提取，不调用外部 VLM API"""
    # 构造 Mock 的图片提取结果
    mock_fig = MagicMock()
    mock_fig.image_path = "/tmp/image1.png"
    mock_fig.caption = "Figure 1: 冶金高炉截面图"
    mock_fig.context_above = "如上图所示，高炉..."
    mock_fig.context_below = "从截面可以看出..."
    mock_fig.image_filename = "image1.png"

    mock_extract.return_value = [mock_fig]
    mock_is_figure.return_value = True

    image_paths = ["/tmp/image1.png"]

    chunks = process_figures(
        md_text=DUMMY_MD,
        image_paths=image_paths,
        doc_id="doc_123",
        source_pdf_id="test.pdf",
        analyze_with_vlm=False,
    )

    assert len(chunks) == 1, "应该生成 1 个图片 Chunk"
    assert chunks[0].chunk_type == "figure"
    assert chunks[0].image_uri == "/tmp/image1.png"

    # 验证描述中是否包含了图注和上下文（不依赖大模型，直接拼接）
    assert "Figure 1: 冶金高炉截面图" in chunks[0].text_content
    assert "如上图所示" in chunks[0].text_content


@patch("src.ingestion.pdf_parser._analyze_figures_with_vlm")
@patch("src.ingestion.pdf_parser.is_figure_item")
@patch("src.ingestion.pdf_parser.extract_figures_from_markdown")
@pytest.mark.small
def test_process_figures_with_vlm_mock(mock_extract, mock_is_figure, mock_analyze_vlm):
    """测试调用 VLM 时的流程，拦截大模型请求并返回假结果"""
    mock_fig = MagicMock()
    mock_fig.image_path = "/tmp/image2.png"

    mock_extract.return_value = [mock_fig]
    mock_is_figure.return_value = True

    # Mock VLM 分析结果的 Chunk
    from src.models.chunk_document import make_image_chunk

    mock_vlm_chunk = make_image_chunk(
        description="【Mock VLM分析结果】这里是马氏体结构。",
        doc_id="doc_123",
        source_pdf_id="test.pdf",
        image_uri="/tmp/image2.png",
        chunk_type="figure",
    )
    mock_analyze_vlm.return_value = [mock_vlm_chunk]

    chunks = process_figures(
        md_text="Dummy",
        image_paths=["/tmp/image2.png"],
        doc_id="doc_123",
        source_pdf_id="test.pdf",
        analyze_with_vlm=True,  # 开启 VLM 分析
    )

    assert len(chunks) == 1
    assert "【Mock VLM分析结果】这里是马氏体结构。" in chunks[0].text_content
    # 确保外部 API 被成功拦截并未真实发出
    mock_analyze_vlm.assert_called_once()


# ==========================================
# S3: _get_chunk_page 独立测试
# ==========================================


@pytest.mark.small
def test_get_chunk_page():
    """测试 chunk 行范围 → 页码映射（众数策略）"""
    from src.ingestion.pdf_parser import _get_chunk_page

    # 模拟 page_map: 行 0-2 属于第1页，行 3-5 属于第3页，行 6-8 属于第5页
    page_map = [1, 1, 1, 3, 3, 3, 5, 5, 5]

    # 完全在第1页范围内 → 应返回 1
    assert _get_chunk_page(0, 2, page_map) == 1

    # 完全在第3页范围内 → 应返回 3
    assert _get_chunk_page(3, 5, page_map) == 3

    # 跨两页边界 (行2-4: 1,3,3) → 众数为 3
    assert _get_chunk_page(2, 4, page_map) == 3

    # 跨三页 (行0-8) → 众数为任意一页（每页3行，平局取第一个）
    result = _get_chunk_page(0, 8, page_map)
    assert result in [1, 3, 5], f"跨全页结果应为 1/3/5，实际: {result}"

    # 单行
    assert _get_chunk_page(7, 7, page_map) == 5

    # 越界保护: start < 0 应被钳制
    assert _get_chunk_page(-5, 2, page_map) == 1

    # 越界保护: end 超出范围应被截断
    assert _get_chunk_page(7, 999, page_map) == 5

    # start >= end 边界情况 (start == end 已由上面单行用例覆盖)
    p2 = [1, 1, 2, 2]
    assert _get_chunk_page(300, 400, p2) == -1, "完全越界应返回 -1"
