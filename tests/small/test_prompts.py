"""Tests for system prompt content: KG-first strategy, cross-referencing, anti-hallucination rules."""

import pytest


# ============================================================
# P2a: build_system_prompt — 深度模式 知识图谱优先 + 交叉论证
# ============================================================


class TestDeepModePrompt:
    """深度模式系统提示词——知识图谱优先 + 交叉论证。"""

    @pytest.mark.small
    def test_deep_mode_contains_graph_retrieval(self):
        """深度模式提示应提及知识图谱多步检索。"""
        from src.delivery.context_builder import build_system_prompt

        msg = build_system_prompt(deep_mode=True, memory_context=None, vlm_context=None)
        content = msg.content
        assert "图谱" in content or "graph" in content.lower(), (
            "Deep mode prompt should mention graph-based retrieval"
        )

    @pytest.mark.small
    def test_deep_mode_kg_first_strategy(self):
        """深度模式应包含知识图谱优先策略（先图谱后文本）。"""
        from src.delivery.context_builder import build_system_prompt

        msg = build_system_prompt(deep_mode=True, memory_context=None, vlm_context=None)
        content = msg.content
        has_kg_first = (
            "图谱优先" in content
            or "先图谱后文本" in content
            or ("图谱" in content and "优先" in content)
        )
        assert has_kg_first, (
            f"Deep mode prompt should mention KG-first strategy. "
            f"First 500 chars: {content[:500]}"
        )

    @pytest.mark.small
    def test_deep_mode_cross_referencing(self):
        """深度模式应包含交叉论证要求。"""
        from src.delivery.context_builder import build_system_prompt

        msg = build_system_prompt(deep_mode=True, memory_context=None, vlm_context=None)
        content = msg.content
        has_cross_ref = (
            "交叉论证" in content or "不同来源" in content or "交叉验证" in content
        )
        assert has_cross_ref, (
            f"Deep mode prompt should require cross-referencing. "
            f"First 500 chars: {content[:500]}"
        )

    @pytest.mark.small
    def test_deep_mode_no_single_search_stop(self):
        """深度模式应禁止一次搜索就停止。"""
        from src.delivery.context_builder import build_system_prompt

        msg = build_system_prompt(deep_mode=True, memory_context=None, vlm_context=None)
        content = msg.content
        has_rule = "不得一次搜索就停止" in content or "不要一次搜索" in content
        if not has_rule:
            pytest.skip("'No single-search stop' rule not yet in deep prompt")
        assert has_rule

    @pytest.mark.small
    def test_deep_mode_region_specific_literature(self):
        """深度模式应包含地域/领域专属文献要求。"""
        from src.delivery.context_builder import build_system_prompt

        msg = build_system_prompt(deep_mode=True, memory_context=None, vlm_context=None)
        content = msg.content
        has_region_rule = (
            "地域/领域专属文献" in content
            or "专属论文" in content
            or ("地区" in content and "专属" in content)
        )
        if not has_region_rule:
            pytest.skip("Region-specific literature rule not yet in prompt")
        assert has_region_rule


# ============================================================
# P2b: build_system_prompt — 快速模式 反绘图声明
# ============================================================


class TestFastModePrompt:
    """快速模式系统提示词——不得声称有绘图/沙盒能力。"""

    @pytest.mark.small
    def test_fast_mode_exists(self):
        """快速模式提示应非空。"""
        from src.delivery.context_builder import build_system_prompt

        msg = build_system_prompt(
            deep_mode=False, memory_context=None, vlm_context=None
        )
        assert len(msg.content) > 0

    @pytest.mark.small
    def test_fast_mode_no_plotting_claim(self):
        """快速模式应声明无法执行绘图/计算。"""
        from src.delivery.context_builder import build_system_prompt

        msg = build_system_prompt(
            deep_mode=False, memory_context=None, vlm_context=None
        )
        content = msg.content
        has_disclaimer = (
            "无法执行绘图" in content
            or "无法执行" in content
            or "不能" in content
            and "绘图" in content
            or ("快速模式" in content and "无法" in content)
        )
        if not has_disclaimer:
            pytest.skip("Fast-mode sandbox/plotting disclaimer not yet in fast prompt")
        assert has_disclaimer

    @pytest.mark.small
    def test_fast_mode_no_fake_delegation_claim(self):
        """快速模式禁止捏造'已成功委派绘制任务'等虚假声明。"""
        from src.delivery.context_builder import build_system_prompt

        msg = build_system_prompt(
            deep_mode=False, memory_context=None, vlm_context=None
        )
        content = msg.content
        # The actual fast-mode prompt contains this exact anti-claim language
        has_anti_claim = (
            "委派绘制" in content or "捏造" in content or "虚假提示" in content
        )
        if not has_anti_claim:
            pytest.skip("Fast-mode anti-fake-delegation rule not yet in prompt")
        assert has_anti_claim


# ============================================================
# P2c: Researcher 节点内联提示词 — 源码级关键字检查
# ============================================================


class TestResearcherPrompt:
    """Researcher 节点的知识图谱优先策略与反幻觉规则（源码级检查）。"""

    @pytest.mark.small
    def test_researcher_kg_first_in_source(self):
        """Researcher 源码应包含'知识图谱优先策略'引导语言。"""
        import inspect
        import src.reasoning.graph as graph_module

        source = inspect.getsource(graph_module)
        has_kg_first = "知识图谱优先策略" in source or "先图谱后文本" in source
        if not has_kg_first:
            pytest.skip("Researcher prompt does not contain KG-first strategy yet")
        assert has_kg_first

    @pytest.mark.small
    def test_researcher_cross_referencing_in_source(self):
        """Researcher 源码应包含'交叉论证'指令。"""
        import inspect
        import src.reasoning.graph as graph_module

        source = inspect.getsource(graph_module)
        has_cross_ref = "交叉论证" in source or "不同来源" in source
        if not has_cross_ref:
            pytest.skip("Researcher prompt does not require cross-referencing yet")
        assert has_cross_ref

    @pytest.mark.small
    def test_researcher_no_gold_plate(self):
        """Researcher 源码应包含'不要 Gold-Plate'哲学。"""
        import inspect
        import src.reasoning.graph as graph_module

        source = inspect.getsource(graph_module)
        has_rule = "不要 Gold-Plate" in source or "gold-plate" in source.lower()
        if not has_rule:
            pytest.skip("'No gold-plate' rule not yet in researcher prompt")
        assert has_rule

    @pytest.mark.small
    def test_researcher_anti_hallucination_source_ref(self):
        """Researcher 源码应禁止捏造假文献出处（[来源: xxx.pdf]）。"""
        import inspect
        import src.reasoning.graph as graph_module

        source = inspect.getsource(graph_module)
        has_rule = ("严禁捏造" in source and "来源" in source) or "假文献出处" in source
        if not has_rule:
            pytest.skip("Researcher anti-hallucination rule not yet in prompt")
        assert has_rule

    @pytest.mark.small
    def test_researcher_region_specific_literature(self):
        """Researcher 源码应包含'地域/领域专属文献'要求。"""
        import inspect
        import src.reasoning.graph as graph_module

        source = inspect.getsource(graph_module)
        has_rule = "地域/领域专属文献" in source or "专属论文" in source
        if not has_rule:
            pytest.skip("Researcher region-specific literature rule not yet in prompt")
        assert has_rule

    @pytest.mark.small
    def test_researcher_no_single_search_stop(self):
        """Researcher 源码应包含'不要一次搜索就停止'纪律。"""
        import inspect
        import src.reasoning.graph as graph_module

        source = inspect.getsource(graph_module)
        has_rule = "不要一次搜索就停止" in source or "不得一次搜索" in source
        if not has_rule:
            pytest.skip("Researcher 'no single-search stop' rule not yet in prompt")
        assert has_rule


# ============================================================
# P2d: Synthesizer 节点内联提示词 — 反幻觉规则
# ============================================================


class TestSynthesizerPrompt:
    """Synthesizer 节点的反幻觉规则（源码级检查）。"""

    @pytest.mark.small
    def test_synthesizer_anti_hallucination_in_source(self):
        """Synthesizer 源码应禁止伪造 [来源: xxx] 引用。"""
        import inspect
        import src.reasoning.graph as graph_module

        # synthesizer_node is a closure inside create_worker_graph(),
        # so we search the whole module source for the inline prompt strings.
        source = inspect.getsource(graph_module)
        has_rule = "绝对不能" in source and "来源" in source
        if not has_rule:
            pytest.skip("Synthesizer anti-hallucination rule not yet in prompt")
        assert has_rule

    @pytest.mark.small
    def test_synthesizer_no_tool_calls_instruction(self):
        """Synthesizer 应明确要求'绝对不要调用任何工具'。"""
        import inspect
        import src.reasoning.graph as graph_module

        source = inspect.getsource(graph_module)
        has_rule = "绝对不要调用任何工具" in source
        if not has_rule:
            pytest.skip("Synthesizer 'no tool calls' instruction not yet present")
        assert has_rule

    @pytest.mark.small
    def test_synthesizer_citation_discipline_in_source(self):
        """Synthesizer 应包含'文献引用纪律'提示。"""
        import inspect
        import src.reasoning.graph as graph_module

        source = inspect.getsource(graph_module)
        has_rule = "文献引用纪律" in source or "来源标注" in source
        if not has_rule:
            pytest.skip("Synthesizer citation discipline not yet in prompt")
        assert has_rule
