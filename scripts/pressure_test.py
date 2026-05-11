import os
import sys
import time
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

# ------------------------------------------------------------
# Environment preparation
# ------------------------------------------------------------
# Mock the heavy marker-pdf library to avoid import errors in test env
sys.modules['marker'] = MagicMock()
sys.modules['marker.convert'] = MagicMock()
sys.modules['marker.models'] = MagicMock()

# Mock OpenAIEmbeddings to prevent external API calls during indexing/search
embed_doc_patch = patch('langchain_openai.OpenAIEmbeddings.embed_documents', return_value=[[0.1] * 1024])
embed_query_patch = patch('langchain_openai.OpenAIEmbeddings.embed_query', return_value=[0.1] * 1024)

with embed_doc_patch, embed_query_patch:
    # Import after mocks are in place
    from src.pipeline.pdf_parser import extract_pdf_with_marker, split_markdown_into_chunk_documents
    from src.pipeline.es_indexer import ElasticsearchIndexer
    from src.retrieval.semantic_search import SemanticSearchTool
    from src.core.config import settings

    # ------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------
    PDF_ROOT = Path('/home/xiaohezi/Downloads/冶金科技竞赛')
    if not PDF_ROOT.is_dir():
        raise FileNotFoundError(f"PDF directory not found: {PDF_ROOT}")

    # Create a unique Elasticsearch index for this pressure test
    test_index_name = f"pressure_test_{uuid.uuid4().hex[:8]}"
    indexer = ElasticsearchIndexer()
    indexer.index_name = test_index_name
    indexer._create_index_if_not_exists()

    start_time = time.time()
    total_chunks = 0
    processed_files = 0

    for pdf_path in PDF_ROOT.rglob('*.pdf'):
        try:
            # 1️⃣ Extract markdown and metadata via Marker‑PDF (mocked)
            md_text, out_metadata = extract_pdf_with_marker(str(pdf_path))
            # 2️⃣ Split into ChunkDocument objects (rich media metadata)
            chunk_docs = split_markdown_into_chunk_documents(
                md_text=md_text,
                out_metadata=out_metadata,
                doc_id=pdf_path.stem,
                source_pdf_id=pdf_path.name,
                chunk_size=500  # reasonable chunk size for stress test
            )
            # 3️⃣ Index the chunks into Elasticsearch
            indexer.index_chunk_documents(chunk_docs)
            total_chunks += len(chunk_docs)
            processed_files += 1
        except Exception as e:
            print(f"[WARN] Failed processing {pdf_path}: {e}")

    elapsed = time.time() - start_time
    print(f"🛠️  Processed {processed_files} PDFs → {total_chunks} chunks in {elapsed:.2f}s")
    print(f"📦  Index name: {test_index_name}")

    # ------------------------------------------------------------
    # Simple retrieval benchmark
    # ------------------------------------------------------------
    search_tool = SemanticSearchTool()
    search_tool.index_name = test_index_name
    query = "热力学"
    t0 = time.time()
    results = search_tool.search(query, top_k=5)
    t1 = time.time()
    print(f"🔎  Search for '{query}' returned {len(results)} results in {(t1 - t0):.3f}s")
    for i, doc in enumerate(results, 1):
        print(f"   {i}. {doc.doc_id} – page {doc.page_number} – score {doc.score:.4f}")

    # ------------------------------------------------------------
    # Cleanup – delete the test index to keep ES tidy
    # ------------------------------------------------------------
    search_tool.es.indices.delete(index=test_index_name, ignore=[400, 404])
    print(f"🧹  Deleted test index {test_index_name}")
