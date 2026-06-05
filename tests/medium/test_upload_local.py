"""Medium test: 测试 upload_local_pdf 极速上传端点 (Electron 专供)

测试目标：
- 正常 PDF 文件上传成功
- 文件不存在时返回 400
- 非 PDF 文件返回 400
- 重复文件触发 fast_resume
"""

import os
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

# 需要在测试前 mock 掉数据库依赖
# main.py 在 import 时就触发了数据库连接，所以需要先 mock


@pytest.fixture
def client():
    """创建带 mock DB 的 TestClient"""
    # Mock 数据库会话，避免连接真实 PostgreSQL
    with patch("src.api.upload_routes.get_db_session") as mock_get_session:
        mock_session = MagicMock()
        mock_get_session.return_value = mock_session

        # Mock 启动时的数据库初始化
        with patch("src.db.session.engine"), patch("src.db.session.Base"):
            from main import app
            from src.api.upload_routes import STORAGE_DIR

            # 确保存储目录存在
            os.makedirs(STORAGE_DIR, exist_ok=True)

            yield TestClient(app), mock_session


class TestUploadLocalPdf:
    """upload_local_pdf 端点测试套件"""

    def test_upload_local_pdf_not_found(self, client):
        """文件不存在时应返回 400"""
        tc, _ = client
        response = tc.post(
            "/api/v1/upload_local_pdf", json={"filepath": "/nonexistent/path/file.pdf"}
        )
        assert response.status_code == 400
        assert "不存在" in response.json()["detail"]

    def test_upload_local_pdf_not_a_pdf(self, client):
        """非 PDF 文件应返回 400"""
        tc, _ = client
        # 使用 /etc/hostname 作为非 PDF 文件（Linux 通用存在）
        test_file = "/etc/hostname"
        if not os.path.exists(test_file):
            pytest.skip("测试所需的 /etc/hostname 文件不存在")
        response = tc.post("/api/v1/upload_local_pdf", json={"filepath": test_file})
        assert response.status_code == 400
        assert (
            "不是 PDF" in response.json()["detail"]
            or "PDF" in response.json()["detail"]
        )

    def test_upload_local_pdf_success(self, client):
        """正常 PDF 上传应成功，返回 documentId"""
        tc, mock_session = client

        # 需要 mock 掉 shutil.copy、DedupChecker、以及后台任务
        with (
            patch("src.api.upload_routes.shutil.copy") as mock_copy,
            patch("src.ingestion.dedup.DedupChecker") as mock_dedup_cls,
            patch("src.api.upload_routes.run_ingestion_pipeline_task") as mock_pipeline,
        ):
            import uuid
            mock_dedup = MagicMock()
            mock_dedup.compute_hash.return_value = "rand_" + uuid.uuid4().hex[:6]
            mock_dedup.check_existing.return_value = None
            mock_dedup_cls.compute_hash = mock_dedup.compute_hash
            mock_dedup_cls.check_existing = mock_dedup.check_existing

            # 创建一个临时 PDF 文件用于测试
            test_pdf = "/tmp/test_upload_small.pdf"
            # 创建一个最小有效的 PDF 文件
            with open(test_pdf, "wb") as f:
                f.write(
                    b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
                    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
                    b"3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R>>endobj\n"
                    b"xref\n0 4\n0000000000 65535 f \n0000000009 00000 n \n"
                    b"0000000058 00000 n \n0000000115 00000 n \n"
                    b"trailer<</Size 4/Root 1 0 R>>\nstartxref\n190\n%%EOF\n"
                )

            try:
                response = tc.post(
                    "/api/v1/upload_local_pdf", json={"filepath": test_pdf}
                )

                assert response.status_code == 200
                data = response.json()
                assert data["status"] == "success"
                assert "documentId" in data
                assert len(data["documentId"]) > 0
                assert data["filename"] == "test_upload_small.pdf"

                # 验证 shutil.copy 被调用
                mock_copy.assert_called_once()
                # 验证 pipeline 被触发
                mock_pipeline.assert_called_once()
            finally:
                # 清理临时文件
                if os.path.exists(test_pdf):
                    os.remove(test_pdf)

    def test_upload_local_pdf_dedup_fast_resume(self, client):
        """重复文件应触发 fast_resume，不走完整入库流程"""
        tc, mock_session = client

        with (
            patch("src.api.upload_routes.shutil.copy") as mock_copy,
            patch("src.ingestion.dedup.DedupChecker") as mock_dedup_cls,
            patch("src.api.upload_routes.run_ingestion_pipeline_task") as mock_pipeline,
        ):
            # Mock 去重检查器返回已有记录
            mock_dedup_cls.compute_hash.return_value = "existing_hash"
            mock_dedup_cls.check_existing.return_value = {
                "id": "existing_doc_123",
                "filename": "already_uploaded.pdf",
            }

            test_pdf = "/tmp/test_dedup.pdf"
            with open(test_pdf, "wb") as f:
                f.write(
                    b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
                    b"xref\n0 2\n0000000000 65535 f \n0000000009 00000 n \n"
                    b"trailer<</Size 2/Root 1 0 R>>\nstartxref\n55\n%%EOF\n"
                )

            try:
                response = tc.post(
                    "/api/v1/upload_local_pdf", json={"filepath": test_pdf}
                )

                assert response.status_code == 200
                data = response.json()
                assert data["status"] == "fast_resume"
                assert data["documentId"] == "existing_doc_123"
                assert data["filename"] == "already_uploaded.pdf"

                # 不应触发拷贝和入库
                mock_copy.assert_not_called()
                mock_pipeline.assert_not_called()
            finally:
                if os.path.exists(test_pdf):
                    os.remove(test_pdf)


class TestUploadLocalPdfEdgeCases:
    """边界情况测试"""

    def test_upload_local_pdf_empty_filepath(self, client):
        """空路径应返回 400"""
        tc, _ = client
        response = tc.post("/api/v1/upload_local_pdf", json={"filepath": ""})
        assert response.status_code == 400

    def test_upload_local_pdf_missing_field(self, client):
        """缺少 filepath 字段应返回 422 (Pydantic 校验)"""
        tc, _ = client
        response = tc.post("/api/v1/upload_local_pdf", json={})
        assert response.status_code == 422
