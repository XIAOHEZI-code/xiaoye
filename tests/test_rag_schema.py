import pytest
import os
import uuid
from elasticsearch import Elasticsearch
from src.retrieval.semantic_search import SemanticSearchTool
from src.pipeline.es_indexer import ElasticsearchIndexer

import sys
from unittest.mock import MagicMock
sys.modules['marker'] = MagicMock()
sys.modules['marker.convert'] = MagicMock()
sys.modules['marker.models'] = MagicMock()

from src.pipeline.pdf_parser import split_markdown_into_chunk_documents
from src.core.config import settings

# Mock OpenAIEmbeddings before anything initializes it
from unittest.mock import patch
mock_embeddings_patcher = patch('langchain_openai.OpenAIEmbeddings.embed_documents', return_value=[[0.1]*1024])
mock_embeddings_patcher.start()
mock_query_patcher = patch('langchain_openai.OpenAIEmbeddings.embed_query', return_value=[0.1]*1024)
mock_query_patcher.start()

@pytest.fixture
def es_client():
    es = Elasticsearch(settings.ELASTICSEARCH_URL)
    yield es

@pytest.fixture
def setup_test_index(es_client):
    indexer = ElasticsearchIndexer()
    test_index = "test_metallurgy_chunks_" + uuid.uuid4().hex[:6]
    indexer.index_name = test_index
    indexer._create_index_if_not_exists()
    yield indexer
    # Cleanup
    if es_client.indices.exists(index=test_index):
        es_client.indices.delete(index=test_index)

@pytest.mark.asyncio
async def test_end_to_end_rag_schema(setup_test_index):
    indexer = setup_test_index
    doc_id = "test_doc_123"
    pdf_id = "sample_metallurgy.pdf"
    
    # 1. 模拟 Marker 输出与文本分块
    md_text = "This is a dummy text about thermodynamics. The quick brown fox jumps over the lazy dog."
    mock_metadata = {
        "blocks": [
            {"text": "This is a dummy text about thermodynamics. The quick brown", "pnums": [5], "bbox": [0,0,10,10]}
        ]
    }
    
    chunk_docs = split_markdown_into_chunk_documents(
        md_text=md_text,
        out_metadata=mock_metadata,
        doc_id=doc_id,
        source_pdf_id=pdf_id,
        chunk_size=100
    )
    
    # Verify parsing extracted page number
    assert len(chunk_docs) > 0
    assert chunk_docs[0].page_number == 5
    assert chunk_docs[0].bbox is not None
    assert chunk_docs[0].source_pdf_id == pdf_id
    
    # 2. 模拟入库
    indexer.index_chunk_documents(chunk_docs)
    
    # Refresh index for immediate search
    indexer.es.indices.refresh(index=indexer.index_name)
    
    # 3. 模拟检索
    search_tool = SemanticSearchTool()
    search_tool.index_name = indexer.index_name 
    
    results = search_tool.search("thermodynamics", top_k=2)
    
    assert len(results) > 0
    top_result = results[0]
    
    # Verify Schema bounds preservation
    assert top_result.doc_id == doc_id
    assert top_result.page_number == 5
    assert top_result.source_pdf_id == pdf_id
    assert top_result.bbox is not None
    assert "thermodynamics" in top_result.text_content
