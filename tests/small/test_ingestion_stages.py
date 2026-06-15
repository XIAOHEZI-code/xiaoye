"""Tests for IngestionStage enum (new GRAPHING/VERIFYING/VERIFY_FAILED values)."""

import pytest


class TestIngestionStages:
    """验证 IngestionStage 枚举包含所有新阶段。"""

    @pytest.mark.small
    def test_graphing_stage_exists(self):
        from src.ingestion.status_tracker import IngestionStage

        assert hasattr(IngestionStage, "GRAPHING")
        assert IngestionStage.GRAPHING.value == "graphing"

    @pytest.mark.small
    def test_verifying_stage_exists(self):
        from src.ingestion.status_tracker import IngestionStage

        assert hasattr(IngestionStage, "VERIFYING")
        assert IngestionStage.VERIFYING.value == "verifying"

    @pytest.mark.small
    def test_verify_failed_stage_exists(self):
        from src.ingestion.status_tracker import IngestionStage

        assert hasattr(IngestionStage, "VERIFY_FAILED")
        assert IngestionStage.VERIFY_FAILED.value == "verify_failed"

    @pytest.mark.small
    def test_all_stages_have_unique_values(self):
        """所有 stage value 必须唯一。"""
        from src.ingestion.status_tracker import IngestionStage

        values = [s.value for s in IngestionStage]
        assert len(values) == len(set(values)), (
            f"Duplicate stage values found: {values}"
        )

    @pytest.mark.small
    def test_graphing_before_verifying(self):
        """GRAPHING 应该在 VERIFYING 之前（逻辑顺序）。"""
        from src.ingestion.status_tracker import IngestionStage

        stages = list(IngestionStage)
        graphing_idx = stages.index(IngestionStage.GRAPHING)
        verifying_idx = stages.index(IngestionStage.VERIFYING)
        assert graphing_idx < verifying_idx, "GRAPHING should come before VERIFYING"

    @pytest.mark.small
    def test_verifying_before_completed(self):
        """VERIFYING 应该在 COMPLETED 之前。"""
        from src.ingestion.status_tracker import IngestionStage

        stages = list(IngestionStage)
        verifying_idx = stages.index(IngestionStage.VERIFYING)
        completed_idx = stages.index(IngestionStage.COMPLETED)
        assert verifying_idx < completed_idx, "VERIFYING should come before COMPLETED"
