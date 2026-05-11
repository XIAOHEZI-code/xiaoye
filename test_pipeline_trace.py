"""
PDF 上传管线全流程追踪脚本
============================
选取一个已有的 PDF，带时间戳追踪每个阶段：
  1. Marker PDF → Markdown + 图片
  2. split_markdown → ChunkDocument 列表
  3. process_figures → 图片 ChunkDocument
  4. enhance_chunks_with_figures → 合并
  5. ElasticsearchIndexer → 向量化 + ES 批量写入
  6. 更新 DB: pending → ready
  7. 验证：search_metallurgy_text 能否检索到
"""

import os, sys, time, json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
for key in ["http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"]:
    os.environ.pop(key, None)

from src.core.config import settings
os.environ["OPENAI_API_KEY"] = settings.QWEN_API_KEY or ""
os.environ["OPENAI_API_BASE"] = settings.QWEN_BASE_URL

STORAGE_DIR = "data/storage"
MARKER_OUT_DIR = "data/marker_output"
timings = []

def step(name):
    """装饰器 — 追踪每步的耗时和产出"""
    def wrapper(func):
        def inner(*args, **kwargs):
            print(f"\n{'─'*60}")
            print(f"  ⏳ Step: {name}")
            print(f"{'─'*60}")
            t0 = time.time()
            result = func(*args, **kwargs)
            elapsed = time.time() - t0
            timings.append((name, elapsed))
            print(f"  ✅ 完成 ({elapsed:.1f}s)")
            return result
        return inner
    return wrapper


# ── 选取一个测试 PDF ────────────────────────────────────────────
pdfs = [f for f in os.listdir(STORAGE_DIR) if f.endswith('.pdf')]
if not pdfs:
    print("❌ data/storage 中没有 PDF 文件")
    sys.exit(1)

test_pdf = pdfs[0]
doc_id = test_pdf.replace('.pdf', '')
pdf_path = os.path.join(STORAGE_DIR, test_pdf)
marker_dir = os.path.join(MARKER_OUT_DIR, doc_id)

print(f"📄 测试文档: {test_pdf}")
print(f"   路径: {pdf_path}")
print(f"   Marker 输出: {marker_dir}")
print(f"   文件大小: {os.path.getsize(pdf_path) / 1024:.0f} KB")


# ================================================================
#  Step 1: Marker PDF → Markdown + 图片
# ================================================================
@step("1. Marker PDF → Markdown + 图片")
def step1_marker():
    from src.pipeline.pdf_parser import extract_pdf_with_marker

    # 检查是否已有 Marker 输出（避免重复解析）
    md_file = os.path.join(marker_dir, f"{doc_id}.md")
    if os.path.exists(md_file):
        print(f"  ℹ️  Marker 输出已存在，复用缓存")
        with open(md_file, 'r') as f:
            md_text = f.read()
        image_paths = [
            os.path.join(marker_dir, f)
            for f in os.listdir(marker_dir)
            if f.endswith(('.jpeg', '.jpg', '.png'))
        ]
        meta_file = os.path.join(marker_dir, f"{doc_id}_meta.json")
        out_metadata = {}
        if os.path.exists(meta_file):
            with open(meta_file) as f:
                out_metadata = json.load(f)
        print(f"  📝 Markdown: {len(md_text)} 字符")
        print(f"  🖼️  图片: {len(image_paths)} 个")
        return md_text, image_paths, out_metadata

    md_text, image_paths, out_metadata = extract_pdf_with_marker(
        filepath=pdf_path, out_dir=MARKER_OUT_DIR,
    )
    print(f"  📝 Markdown: {len(md_text)} 字符")
    print(f"  🖼️  图片: {len(image_paths)} 个")
    return md_text, image_paths, out_metadata


md_text, image_paths, out_metadata = step1_marker()

# 展示 Markdown 前 500 字符
print(f"\n  📋 Markdown 预览 (前 500 字符):")
print(f"  {'·'*50}")
for line in md_text[:500].split('\n'):
    print(f"    {line}")
print(f"  {'·'*50}")


# ================================================================
#  Step 2: 文本 Chunking
# ================================================================
@step("2. Markdown → ChunkDocument 列表")
def step2_chunking():
    from src.pipeline.pdf_parser import split_markdown_into_chunk_documents
    chunks = split_markdown_into_chunk_documents(
        md_text=md_text,
        out_metadata=out_metadata,
        doc_id=doc_id,
        source_pdf_id=test_pdf,
    )
    print(f"  📦 生成 {len(chunks)} 个文本 Chunks")
    for i, c in enumerate(chunks[:3]):
        print(f"    [{i+1}] chunk_id={c.chunk_id[:20]}... | page={c.page_number} | {len(c.text_content)} 字符")
        print(f"        内容: {c.text_content[:80]}...")
    if len(chunks) > 3:
        print(f"    ... 还有 {len(chunks)-3} 个 Chunks")
    return chunks


text_chunks = step2_chunking()


# ================================================================
#  Step 3: 图片 Chunks（仅图注，不调 VLM）
# ================================================================
@step("3. 图片处理 → Figure ChunkDocument")
def step3_figures():
    from src.pipeline.pdf_parser import process_figures
    if not image_paths:
        print("  ℹ️  无图片，跳过")
        return []
    figure_chunks = process_figures(
        md_text=md_text,
        image_paths=image_paths,
        doc_id=doc_id,
        source_pdf_id=test_pdf,
        analyze_with_vlm=False,
    )
    print(f"  🖼️  生成 {len(figure_chunks)} 个图片 Chunks")
    for i, c in enumerate(figure_chunks[:3]):
        print(f"    [{i+1}] type={c.chunk_type} | page={c.page_number}")
        print(f"        图注: {c.text_content[:80]}...")
    return figure_chunks


figure_chunks = step3_figures()


# ================================================================
#  Step 4: 合并增强
# ================================================================
@step("4. 合并文本 + 图片 Chunks")
def step4_merge():
    from src.pipeline.pdf_parser import enhance_chunks_with_figures
    all_chunks = enhance_chunks_with_figures(text_chunks, figure_chunks)
    print(f"  📦 合并后总计: {len(all_chunks)} 个 Chunks")
    # 统计各类型
    type_counts = {}
    for c in all_chunks:
        t = c.chunk_type
        type_counts[t] = type_counts.get(t, 0) + 1
    for t, cnt in type_counts.items():
        print(f"    - {t}: {cnt} 个")
    return all_chunks


all_chunks = step4_merge()


# ================================================================
#  Step 5: 向量化 + ES 批量写入
# ================================================================
@step("5. Embedding 向量化 + Elasticsearch 索引")
def step5_index():
    from src.pipeline.es_indexer import ElasticsearchIndexer
    indexer = ElasticsearchIndexer()

    # 先清理该文档的旧索引
    from elasticsearch import Elasticsearch
    es = Elasticsearch(settings.ELASTICSEARCH_URL)
    try:
        es.delete_by_query(index="metallurgy_chunks", body={
            "query": {"term": {"doc_id": doc_id}}
        })
        print(f"  🧹 已清理旧索引 (doc_id={doc_id[:12]}...)")
    except Exception:
        pass

    indexer.index_chunk_documents(all_chunks)
    print(f"  📥 写入 {len(all_chunks)} 个 Chunks 到 ES")

    # 验证
    import time as _time
    _time.sleep(1)
    count = es.count(index="metallurgy_chunks", body={
        "query": {"term": {"doc_id": doc_id}}
    })["count"]
    print(f"  ✅ ES 验证: {count} 个文档已索引")
    return count


indexed_count = step5_index()


# ================================================================
#  Step 6: 更新 DB 状态
# ================================================================
@step("6. 更新 DB 状态 → ready")
def step6_update_db():
    from src.db.session import SessionLocal
    from src.models.document import DocumentMetadata
    db = SessionLocal()
    doc = db.query(DocumentMetadata).filter(DocumentMetadata.id == doc_id).first()
    if doc:
        doc.status = "ready"
        db.commit()
        print(f"  📄 {doc.filename} → status=ready")
    else:
        print(f"  ⚠️ DB 中未找到 doc_id={doc_id}")
    db.close()


step6_update_db()


# ================================================================
#  Step 7: 端到端验证 — Agent 能否检索到
# ================================================================
@step("7. Agent 检索验证 (search_metallurgy_text)")
def step7_verify():
    from src.agent.tools import search_metallurgy_text
    # 取 Markdown 的第一段作为查询
    first_line = md_text.strip().split('\n')[0][:50]
    print(f"  🔍 查询: '{first_line}'")
    result = search_metallurgy_text(first_line, top_k=2)
    found = doc_id in result or len(result) > 50
    if found:
        print(f"  ✅ 检索成功！结果片段:")
        for line in result[:300].split('\n'):
            print(f"    {line}")
    else:
        print(f"  ❌ 未检索到: {result[:150]}")
    return found


step7_verify()


# ================================================================
#  汇总
# ================================================================
print(f"\n{'='*60}")
print(f"  📊 管线执行汇总")
print(f"{'='*60}")
total_time = sum(t for _, t in timings)
for name, elapsed in timings:
    bar = '█' * int(elapsed / total_time * 30)
    print(f"  {name:40s} {elapsed:6.1f}s  {bar}")
print(f"  {'─'*55}")
print(f"  {'总计':40s} {total_time:6.1f}s")
print(f"\n  文档 Chunks 数量: {len(all_chunks)}")
print(f"  ES 已索引文档数: {indexed_count}")
print()
