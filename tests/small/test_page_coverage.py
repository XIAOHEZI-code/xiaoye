import pytest
from src.ingestion.pdf_parser import _build_page_map, split_markdown_into_chunk_documents

# 构造包含 TOC 标题和图片页码锚点的假数据
DUMMY_MD = """# 第一章 绪论
这是第一段内容，用于测试前向继承。
这是第二段内容。
在这里我们插入了一张图片 ![](_page_2_figure1.png)
这是图片下面的文字，它应该继承图片的页码。

# 第二章 实验方法
开始介绍实验方法。
这是一些详细的步骤说明。
"""

DUMMY_META = {
    "table_of_contents": [
        {"title": "第一章 绪论", "page_id": 0},  # TOC page_id 0 -> 对应物理页码 1
        {"title": "第二章 实验方法", "page_id": 4} # TOC page_id 4 -> 对应物理页码 5
    ]
}

def test_build_page_map_strategies():
    """测试三种页码推断策略：图片锚点、TOC匹配、前向继承"""
    lines = DUMMY_MD.split('\n')
    page_map = _build_page_map(DUMMY_MD, DUMMY_META.get("table_of_contents", []))
    
    # 确保 page_map 的长度与文本行数完全一致
    assert len(page_map) == len(lines), "page_map 长度必须与行数一致"
    
    # Line 0: "# 第一章 绪论" -> TOC 命中，page_id 0 -> 页码 1
    assert page_map[0] == 1, "TOC 标题匹配策略失效"
    
    # Line 1-2: 没有任何锚点，应该触发“前向继承”，继承页码 1
    assert page_map[1] == 1, "前向继承策略失效"
    assert page_map[2] == 1, "前向继承策略失效"
    
    # Line 3: 图片锚点 `![](_page_2_figure1.png)` -> page_id 2 -> 页码 3
    assert page_map[3] == 3, "图片引用锚点解析策略失效"
    
    # Line 4: 图片下方的文字 -> 前向继承，继承页码 3
    assert page_map[4] == 3, "跨段落前向继承策略失效"
    
    # Line 6: "# 第二章 实验方法" -> TOC 命中，page_id 4 -> 页码 5
    # (Line 5 is empty due to \n\n)
    assert page_map[6] == 5, "多章节 TOC 标题匹配策略失效"

def test_split_chunk_page_coverage():
    """测试分块算法是否能利用 page_map 正确赋予 chunk 页码"""
    # 将 chunk_size 设置极小，强制每个段落被单独切分为 chunk
    chunks = split_markdown_into_chunk_documents(
        md_text=DUMMY_MD,
        out_metadata=DUMMY_META,
        doc_id="test-doc",
        source_pdf_id="test.pdf",
        chunk_size=10,
        chunk_overlap=0
    )
    
    assert len(chunks) > 0, "应当成功生成 Chunk 列表"
    
    # 验证所有的 chunk 都有合法的 page_number (>0)，证明全覆盖
    missing_pages = [c for c in chunks if c.page_number <= 0]
    assert len(missing_pages) == 0, f"发现缺失页码的 Chunk: {missing_pages}"
    
    # 抽样验证：包含“绪论”的 chunk 应该被分配在第 1 页
    intro_chunk = next((c for c in chunks if "绪论" in getattr(c, 'text_content', getattr(c, 'content', ''))), None)
    assert intro_chunk is not None
    assert intro_chunk.page_number == 1
    
    # 包含“实验方法”的 chunk 应该被分配在第 5 页
    method_chunk = next((c for c in chunks if "实验方法" in getattr(c, 'text_content', getattr(c, 'content', ''))), None)
    assert method_chunk is not None
    assert method_chunk.page_number == 5
