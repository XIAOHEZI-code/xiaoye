import pytest
import json
import os
from unittest.mock import patch, MagicMock
from src.tooling.definitions import crop_pdf_region, analyze_metallurgy_image

@pytest.mark.small
@patch("src.tooling.definitions.crop_pdf_to_base64_png")
@patch("src.tooling.definitions.os.path.exists")
def test_crop_pdf_region_success(mock_exists, mock_crop_pdf):
    # Mock PDF exists
    mock_exists.return_value = True
    # Mock cropper output
    mock_crop_pdf.return_value = "iVBORw0KGgoAAAANSUhEUgAA..."

    # Run tool
    result = crop_pdf_region("doc123", 2, 0.1, 0.1, 0.9, 0.9)

    # Assert correct parameters passed
    mock_crop_pdf.assert_called_once_with(
        os.path.join("data/storage", "doc123.pdf"),
        2,
        {"x0": 0.1, "y0": 0.1, "x1": 0.9, "y1": 0.9}
    )
    assert "Successfully cropped page 2 region" in result
    assert "[CROPPED_IMAGE_BASE64]:iVBORw0KGgoAAAANSUhEUgAA..." in result


@pytest.mark.small
@patch("src.tooling.definitions.analyze_metallurgy_image_with_context")
def test_analyze_metallurgy_image_success(mock_analyze):
    # Mock VLM analysis output model
    mock_result = MagicMock()
    mock_result.category = "微观组织表征图谱"
    mock_result.sub_category = "金相图"
    mock_result.description = "该图为调质态304不锈钢金相组织，显示均匀分布的奥氏体晶粒。"
    mock_result.key_metrics = "晶粒度约为8级"
    mock_analyze.return_value = mock_result

    # Run tool
    result_str = analyze_metallurgy_image("base64_data", "Caption: Fig 1", "Context above", "Context below")

    # Assert
    mock_analyze.assert_called_once_with(
        image_base64="base64_data",
        caption="Caption: Fig 1",
        context_above="Context above",
        context_below="Context below"
    )
    data = json.loads(result_str)
    assert data["category"] == "微观组织表征图谱"
    assert data["sub_category"] == "金相图"
    assert "奥氏体晶粒" in data["description"]
    assert data["key_metrics"] == "晶粒度约为8级"
