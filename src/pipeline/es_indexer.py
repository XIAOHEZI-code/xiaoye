import os
from elasticsearch import Elasticsearch, helpers
from langchain_openai import OpenAIEmbeddings
from src.core.config import settings
from typing import List, Dict

class ElasticsearchIndexer:
    def __init__(self):
        self.es = Elasticsearch(settings.ELASTICSEARCH_URL)
        # We use QWEN's text-embedding-v3 via OpenAI compatible API
        self.embeddings = OpenAIEmbeddings(
            model=settings.QWEN_EMBEDDING_MODEL,
            api_key=settings.QWEN_API_KEY,
            base_url=settings.QWEN_BASE_URL,
            # QWen embedding v3 usually gives 1024 or 1536 dim, depending on specific flavor. 
            # Note: Need to initialize index with correct dims before insertion.
        )
        self.index_name = "metallurgy_chunks"
        self._create_index_if_not_exists()

    def _create_index_if_not_exists(self):
        """
        Creates the ES index with Dense Vector + Rich Media Provenance configuration.
        M1 升级：增加 source_pdf_id, page_number, bbox, image_uri, chunk_type 字段
        """
        if not self.es.indices.exists(index=self.index_name):
            mapping = {
                "mappings": {
                    "properties": {
                        "doc_id": {"type": "keyword"},
                        "chunk_id": {"type": "keyword"},
                        "content": {"type": "text", "analyzer": "ik_max_word"},
                        "source_type": {"type": "keyword"},  # text_chunk | image_description
                        # === M1 新增：富媒体溯源字段 ===
                        "source_pdf_id": {"type": "keyword"},   # 原始 PDF 文件标识
                        "page_number": {"type": "integer"},     # 所在页码 (1-indexed)
                        "bbox": {                               # PDF 页面上的矩形区域
                            "type": "object",
                            "enabled": False,  # 不索引，仅存储用于前端渲染
                        },
                        "image_uri": {"type": "keyword"},       # 图片/截图存储路径
                        "chunk_type": {"type": "keyword"},      # text | table | figure | formula
                        # === 向量字段（不变） ===
                        "vector": {
                            "type": "dense_vector",
                            "dims": 1024,
                            "index": True,
                            "similarity": "cosine"
                        }
                    }
                }
            }
            self.es.indices.create(index=self.index_name, body=mapping, ignore=400)

    def index_chunks(self, chunks: List[str], doc_id: str, source_type: str = "text_chunk"):
        """
        [旧接口 - 向后兼容] 索引纯文本 chunks 列表。
        新代码请使用 index_chunk_documents() 以获取富媒体溯源能力。
        """
        if not chunks:
            return

        print(f"Generating embeddings for {len(chunks)} chunks...")
        vectors = self.embeddings.embed_documents(chunks)

        actions = []
        for i, (chunk, vector) in enumerate(zip(chunks, vectors)):
            action = {
                "_index": self.index_name,
                "_id": f"{doc_id}_{i}",
                "_source": {
                    "doc_id": doc_id,
                    "chunk_id": f"chunk_{i}",
                    "content": chunk,
                    "source_type": source_type,
                    "vector": vector
                }
            }
            actions.append(action)

        print("Bulk indexing into Elasticsearch...")
        helpers.bulk(self.es, actions)

    def index_chunk_documents(self, chunks: List["ChunkDocument"]):
        """
        [M1 新接口] 索引带有完整溯源元数据的 ChunkDocument 列表。
        每个 chunk 携带 page_number, bbox, image_uri, chunk_type 等富媒体字段。
        """
        if not chunks:
            return

        texts = [c.text_content for c in chunks]
        print(f"Generating embeddings for {len(texts)} rich chunks...")
        vectors = self.embeddings.embed_documents(texts)

        actions = []
        for chunk, vector in zip(chunks, vectors):
            source = chunk.to_dict()
            source["vector"] = vector
            actions.append({
                "_index": self.index_name,
                "_id": f"{chunk.doc_id}_{chunk.chunk_id}",
                "_source": source,
            })

        print(f"Bulk indexing {len(actions)} rich chunks into Elasticsearch...")
        helpers.bulk(self.es, actions)
