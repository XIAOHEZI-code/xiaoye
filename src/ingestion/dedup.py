"""
Ingestion Dedup — PDF 去重检测

将 upload_routes.py 中的 SHA-256 hash 防重逻辑独立化，
支持未来扩展到内容级去重（相似度检测）。
"""

import hashlib
from typing import Optional, Tuple


class DedupChecker:
    """PDF 文件去重检测器"""

    @staticmethod
    def compute_hash(content: bytes) -> str:
        """计算文件内容的 SHA-256 哈希"""
        return hashlib.sha256(content).hexdigest()

    @staticmethod
    def check_existing(file_hash: str) -> Optional[dict]:
        """
        查询数据库是否已存在相同 hash 的文档。

        Args:
            file_hash: SHA-256 哈希值

        Returns:
            已存在则返回 {"id": doc_id, "filename": filename}，否则 None
        """
        from src.db.session import SessionLocal
        from src.models.document import DocumentMetadata

        db = SessionLocal()
        try:
            existing = db.query(DocumentMetadata).filter(
                DocumentMetadata.hash == file_hash
            ).first()
            if existing:
                return {"id": existing.id, "filename": existing.filename}
            return None
        finally:
            db.close()
