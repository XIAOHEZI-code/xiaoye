"""Tests for chat_worker routing functions: should_use_react_agent() and is_chitchat()."""

import pytest


def _import_routing_functions():
    """延迟导入，避免模块级副作用。"""
    from src.delivery.chat_worker import should_use_react_agent, is_chitchat

    return should_use_react_agent, is_chitchat


class TestShouldUseReactAgent:
    """should_use_react_agent(message) — 判断是否走 ReAct Agent 路径。

    触发条件：message（lowered）中包含任一技术关键词。
    注意：deep_mode 的处理在 dispatch_chat_worker 调用处（OR 逻辑），
    函数本身只做关键词匹配，不接收 deep_mode 参数。
    """

    # ── 触发词测试 ──
    @pytest.mark.small
    def test_triggers_on_python(self):
        should_use_react_agent, _ = _import_routing_functions()
        assert should_use_react_agent("帮我用python画个相图") is True

    @pytest.mark.small
    def test_triggers_on_code(self):
        should_use_react_agent, _ = _import_routing_functions()
        assert should_use_react_agent("写代码计算疲劳寿命") is True

    @pytest.mark.small
    def test_triggers_on_calculate(self):
        should_use_react_agent, _ = _import_routing_functions()
        assert should_use_react_agent("计算这个反应的吉布斯自由能") is True

    @pytest.mark.small
    def test_triggers_on_graph(self):
        should_use_react_agent, _ = _import_routing_functions()
        assert should_use_react_agent("磷石膏在知识图谱里有哪些关联实体") is True

    @pytest.mark.small
    def test_triggers_on_curve_keyword(self):
        should_use_react_agent, _ = _import_routing_functions()
        # "曲线" 是关键词
        assert should_use_react_agent("用matplotlib画应力应变曲线") is True

    @pytest.mark.small
    def test_triggers_on_sandbox(self):
        should_use_react_agent, _ = _import_routing_functions()
        assert should_use_react_agent("在沙盒里运行这段代码") is True

    @pytest.mark.small
    def test_triggers_on_single_keyword(self):
        should_use_react_agent, _ = _import_routing_functions()
        assert should_use_react_agent("帮我写代码") is True  # 只含"代码"

    # ── 不触发 ──
    @pytest.mark.small
    def test_simple_question_no_trigger(self):
        should_use_react_agent, _ = _import_routing_functions()
        assert should_use_react_agent("什么是马氏体") is False

    @pytest.mark.small
    def test_greeting_no_trigger(self):
        should_use_react_agent, _ = _import_routing_functions()
        assert should_use_react_agent("你好") is False

    @pytest.mark.small
    def test_empty_string(self):
        should_use_react_agent, _ = _import_routing_functions()
        assert should_use_react_agent("") is False

    @pytest.mark.small
    def test_english_no_trigger(self):
        should_use_react_agent, _ = _import_routing_functions()
        assert (
            should_use_react_agent("What is the tensile strength of this alloy")
            is False
        )

    # ── 边界情况 ──
    @pytest.mark.small
    def test_keyword_in_middle_of_sentence(self):
        should_use_react_agent, _ = _import_routing_functions()
        assert should_use_react_agent("我想了解怎么用计算工具") is True

    @pytest.mark.small
    def test_partial_keyword_match(self):
        should_use_react_agent, _ = _import_routing_functions()
        # "图谱" 是关键词，应该触发
        assert should_use_react_agent("知识图谱怎么用") is True

    @pytest.mark.small
    def test_multiple_keywords_still_true(self):
        """多个关键词都命中时仍返回 True（不会短路变 False）。"""
        should_use_react_agent, _ = _import_routing_functions()
        assert should_use_react_agent("用python画个曲线图") is True


class TestIsChitchat:
    """is_chitchat(message) — 判断是否为纯闲聊（不需要检索的短消息）。

    条件：len(message) < 15 且 message（lowered）中包含任一寒暄关键词。
    两个条件缺一不可。
    """

    @pytest.mark.small
    def test_short_greeting(self):
        _, is_chitchat = _import_routing_functions()
        assert is_chitchat("你好") is True

    @pytest.mark.small
    def test_thanks(self):
        _, is_chitchat = _import_routing_functions()
        assert is_chitchat("谢谢") is True

    @pytest.mark.small
    def test_english_hi(self):
        _, is_chitchat = _import_routing_functions()
        assert is_chitchat("hi") is True

    @pytest.mark.small
    def test_english_hello(self):
        _, is_chitchat = _import_routing_functions()
        assert is_chitchat("hello") is True

    @pytest.mark.small
    def test_long_message_not_chitchat(self):
        """长度 >= 15 时即使含关键词也不视为闲聊。"""
        _, is_chitchat = _import_routing_functions()
        assert is_chitchat("你好啊我想请教一个问题关于材料学") is False  # len=16

    @pytest.mark.small
    def test_long_question_not_chitchat(self):
        _, is_chitchat = _import_routing_functions()
        assert is_chitchat("请帮我分析一下这个材料的疲劳性能") is False

    @pytest.mark.small
    def test_knowledge_question_not_chitchat(self):
        _, is_chitchat = _import_routing_functions()
        assert is_chitchat("什么是退火") is False

    @pytest.mark.small
    def test_empty_string_not_chitchat(self):
        """空字符串不含任何关键词 → 不视为闲聊。"""
        _, is_chitchat = _import_routing_functions()
        assert is_chitchat("") is False

    @pytest.mark.small
    def test_short_but_no_keyword(self):
        """消息虽短但不含寒暄词 → 不是闲聊。"""
        _, is_chitchat = _import_routing_functions()
        assert is_chitchat("什么是马氏体") is False  # len=6 < 15，但无寒暄词

    @pytest.mark.small
    def test_keyword_but_too_long(self):
        """含寒暄词但消息过长 → 不是闲聊。"""
        _, is_chitchat = _import_routing_functions()
        # "谢谢" 是关键词，但整句话 >= 15 字
        assert is_chitchat("谢谢你我学到了很多关于冶金方面的知识") is False  # len=18
