import pytest
from src.delivery.context_builder import build_system_prompt

def test_build_system_prompt_fast_mode():
    """测试快速模式下的系统设定组装"""
    msg = build_system_prompt(
        deep_mode=False, 
        memory_context=None, 
        vlm_context=None
    )
    content = msg.content
    assert "优先使用基础检索回答" in content
    assert "【深度模式已激活】" not in content

def test_build_system_prompt_deep_mode():
    """测试深度模式下的系统设定组装"""
    msg = build_system_prompt(
        deep_mode=True, 
        memory_context=None, 
        vlm_context=None
    )
    content = msg.content
    assert "【深度模式已激活】" in content
    assert "优先使用基础检索回答" not in content

def test_build_system_prompt_with_memory_and_vlm():
    """测试带有长程记忆和视觉分析结果的设定组装"""
    msg = build_system_prompt(
        deep_mode=False,
        memory_context="用户上次提问了关于转炉的问题。",
        vlm_context="图片显示了一个包含马氏体的显微组织图。"
    )
    content = msg.content
    assert "【长程记忆】\n用户上次提问了关于转炉的问题。" in content
    assert "【VLM 视觉分析结果】" in content
    assert "图片显示了一个包含马氏体的显微组织图。" in content
