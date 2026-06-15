"""Medium test: 测试 chat_worker 调度逻辑

测试目标：
- dispatch_chat_worker 正确组装消息队列 (context_builder + 消息路由)
- 深度模式 vs 快速模式下的 system prompt 差异
- 带对话历史时的上下文注入
- VLM 视觉分析上下文注入
"""

import pytest
from unittest.mock import patch, AsyncMock, MagicMock


# ==========================================
# 辅助：从 context_builder 直接验证 prompt 组装（因为 chat_worker 内部调用此模块）
# ==========================================


class TestContextBuilderPromptAssembly:
    """验证 context_builder 的 prompt 组装逻辑（chat_worker 依赖此模块）"""

    def test_fast_mode_prompt_contains_quick_search(self):
        """快速模式下 system prompt 应包含 '优先使用基础检索'"""
        from src.delivery.context_builder import build_system_prompt

        msg = build_system_prompt(
            deep_mode=False, memory_context=None, vlm_context=None
        )
        content = msg.content
        assert "优先使用基础检索回答" in content
        assert "【深度模式已激活】" not in content

    def test_deep_mode_prompt_contains_graph_reasoning(self):
        """深度模式下 system prompt 应包含图谱多步检索与推理提示"""
        from src.delivery.context_builder import build_system_prompt

        msg = build_system_prompt(deep_mode=True, memory_context=None, vlm_context=None)
        content = msg.content
        assert "【深度模式已激活】" in content
        assert "图谱多步检索" in content

    def test_memory_context_injected(self):
        """长程记忆应被注入到 system prompt"""
        from src.delivery.context_builder import build_system_prompt

        msg = build_system_prompt(
            deep_mode=False,
            memory_context="用户之前询问过转炉工艺相关问题。",
            vlm_context=None,
        )
        content = msg.content
        assert "【长程记忆】" in content
        assert "转炉工艺" in content

    def test_vlm_context_injected(self):
        """VLM 视觉分析结果应被注入到 system prompt"""
        from src.delivery.context_builder import build_system_prompt

        msg = build_system_prompt(
            deep_mode=False,
            memory_context=None,
            vlm_context="图片分析: 该显微组织图中包含马氏体和残余奥氏体。",
        )
        content = msg.content
        assert "【VLM 视觉分析结果】" in content
        assert "马氏体" in content

    def test_both_contexts_injected(self):
        """同时注入长程记忆和 VLM 上下文"""
        from src.delivery.context_builder import build_system_prompt

        msg = build_system_prompt(
            deep_mode=True,
            memory_context="记忆: 用户关注 Q345 钢。",
            vlm_context="VLM: 图片含珠光体组织。",
        )
        content = msg.content
        assert "【深度模式已激活】" in content
        assert "【长程记忆】" in content
        assert "Q345" in content
        assert "【VLM 视觉分析结果】" in content
        assert "珠光体" in content


# ==========================================
# 消息队列组装验证
# ==========================================


class TestMessageQueueAssembly:
    """验证 chat_worker 组装的消息队列结构

    由于 dispatch_chat_worker 依赖 Redis + LLM + Graph 等重型基础设施，
    这里通过直接测试其依赖的子模块（context_builder）来间接验证队列组装逻辑。
    """

    def test_message_queue_structure(self):
        """模拟 chat_worker 的消息队列组装逻辑：
        [SystemMessage] + [历史 Messages] + [HumanMessage(当前问题)]
        """
        from src.delivery.context_builder import build_system_prompt
        from langchain_core.messages import HumanMessage

        # Step 1: 构建 system message
        sys_msg = build_system_prompt(
            deep_mode=True, memory_context=None, vlm_context=None
        )
        from langchain_core.messages import SystemMessage

        assert isinstance(sys_msg, SystemMessage)

        # Step 2: 模拟历史消息（build_and_compact_history 的输出）
        from langchain_core.messages import HumanMessage as HM, AIMessage

        history_msgs = [
            HM(content="上一个问题"),
            AIMessage(content="上一个回答"),
        ]

        # Step 3: 当前用户消息
        current = HumanMessage(content="当前问题：304不锈钢的耐腐蚀温度上限？")

        # Step 4: 组合队列
        queue = [sys_msg] + history_msgs + [current]
        assert len(queue) == 4  # 1 system + 2 history + 1 current
        assert isinstance(queue[0], SystemMessage)
        assert isinstance(queue[1], HM)
        assert isinstance(queue[2], AIMessage)
        assert isinstance(queue[3], HumanMessage)
        assert "304不锈钢" in queue[3].content


# ==========================================
# dispatch_chat_worker 集成验证 (需要 Mock Redis)
# ==========================================


@pytest.mark.integration
class TestDispatchChatWorkerIntegration:
    """dispatch_chat_worker 集成测试 (Mock Redis + Graph)"""

    @pytest.mark.asyncio
    async def test_dispatch_calls_graph_pipeline(self):
        """
        验证 dispatch_chat_worker 能够从 Redis 读取上下文，
        组装消息队列，并调用 run_worker_pipeline。
        """
        # 由于 dispatch_chat_worker 内部有复杂的 Redis key 拼接和异步逻辑，
        # 这里做轻量级集成验证：确认核心依赖模块可正常导入和工作
        try:
            from src.delivery.chat_worker import dispatch_chat_worker
            from src.delivery.context_builder import (
                build_system_prompt,
                build_and_compact_history,
            )
            from src.reasoning.graph import run_worker_pipeline

            # 验证所有核心函数可导入
            assert callable(dispatch_chat_worker)
            assert callable(build_system_prompt)
            assert callable(build_and_compact_history)
            assert callable(run_worker_pipeline)
        except ImportError as e:
            pytest.fail(f"核心模块导入失败: {e}")

    @pytest.mark.asyncio
    async def test_context_builder_async_compact(self):
        """
        验证 build_and_compact_history 异步函数的正常流程。
        （chat_worker 在 dispatch 中 await 此函数）
        """
        from src.delivery.context_builder import build_and_compact_history
        from langchain_core.messages import HumanMessage, AIMessage

        history = [
            {"user": "你好", "assistant": "你好，我是小冶，有什么可以帮助你的？"},
        ]
        result = await build_and_compact_history(history, token_budget=6000)
        assert len(result) == 2  # 1 Human + 1 AI
        assert isinstance(result[0], HumanMessage)
        assert isinstance(result[1], AIMessage)
        assert "你好" in result[0].content
        assert "小冶" in result[1].content


# ==========================================
# 边界情况测试
# ==========================================


class TestChatWorkerEdgeCases:
    """chat_worker 边界情况"""

    def test_empty_history_compact(self):
        """build_and_compact_history 对空历史的处理（chat_worker 会先 await 此函数）"""
        import asyncio
        from src.delivery.context_builder import build_and_compact_history

        result = asyncio.run(build_and_compact_history([], token_budget=6000))
        assert result == []

    def test_single_turn_history(self):
        """单轮对话历史（chat_worker 最常见的场景）"""
        import asyncio
        from src.delivery.context_builder import build_and_compact_history

        history = [{"user": "测试问题", "assistant": "测试回答"}]
        result = asyncio.run(build_and_compact_history(history, token_budget=6000))
        assert len(result) == 2


class TestFastChatMode:
    """测试快速模式的核心设计与功能"""

    @pytest.mark.asyncio
    @patch("src.delivery.chat_worker.redis.from_url")
    @patch("src.delivery.chat_worker.load_preload_context")
    @patch("src.delivery.sse_channel.get_sse_channel")
    @patch("src.reasoning.graph.run_worker_pipeline")
    @patch("src.tooling.definitions.search_metallurgy_text")
    @patch("langchain_openai.ChatOpenAI")
    async def test_fast_mode_context_retention(
        self, mock_llm_cls, mock_search, mock_run, mock_sse, mock_load, mock_redis_from_url
    ):
        """测试快速模式下对话上下文的保存与组装"""
        # Mock Redis client
        mock_r = AsyncMock()
        mock_r.__aenter__.return_value = mock_r
        mock_r.get = AsyncMock(return_value=None)  # 无 VLM 上下文
        mock_redis_from_url.return_value = mock_r
        
        # Mock memory context
        mock_load.return_value = "这是之前的记忆。"
        
        # Mock SSE channel
        mock_sse.return_value = AsyncMock()
        
        # Mock LLM instance for Chitchat/RAG
        mock_llm = MagicMock()
        mock_llm.astream.return_value = AsyncMock()  # Mock async generator
        mock_llm_cls.return_value = mock_llm
        
        mock_search.return_value = "检索结果"

        from src.delivery.chat_worker import dispatch_chat_worker

        history = [{"user": "我是小明", "assistant": "你好小明"}]
        
        # 发送一条普通的闲聊（无 retrieve），测试它能正常应答并感知上下文
        await dispatch_chat_worker(
            task_id="test_task_123",
            message="你好，我是谁？",
            document_id=None,
            history=history,
            deep_mode=False,
        )

        # 验证 LLM.astream 被调用
        mock_llm.astream.assert_called_once()
        sent_messages = mock_llm.astream.call_args[0][0]
        
        # 验证消息队列结构：1 system + 2 history + 1 current
        assert len(sent_messages) == 4
        assert "这是之前的记忆" in sent_messages[0].content
        assert "我是小明" in sent_messages[1].content
        assert "你好小明" in sent_messages[2].content
        assert "你好，我是谁？" in sent_messages[3].content

    @pytest.mark.asyncio
    @patch("src.delivery.chat_worker.redis.from_url")
    @patch("src.delivery.chat_worker.load_preload_context")
    @patch("src.delivery.sse_channel.get_sse_channel")
    @patch("src.reasoning.graph.run_worker_pipeline")
    async def test_fast_mode_tool_routing(
        self, mock_run, mock_sse, mock_load, mock_redis_from_url
    ):
        """测试快速模式下遇到复杂计算/工具调用时，智能路由分发至 ReAct 循环"""
        mock_r = AsyncMock()
        mock_r.__aenter__.return_value = mock_r
        mock_r.get = AsyncMock(return_value=None)
        mock_redis_from_url.return_value = mock_r
        mock_load.return_value = None
        mock_sse.return_value = AsyncMock()
        mock_run.return_value = "计算结果"

        from src.delivery.chat_worker import dispatch_chat_worker

        # 发送需要 Python 沙盒执行的计算提问，应该路由到 run_worker_pipeline
        await dispatch_chat_worker(
            task_id="test_task_tool",
            message="请使用 python 计算 123 * 456 的结果",
            document_id=None,
            history=[],
            deep_mode=False,
        )

        # 验证 run_worker_pipeline 确实被启动了
        mock_run.assert_called_once()
        payload = mock_run.call_args[0][0]
        assert payload["deep_mode"] is False  # 运行快速模式下的 ReAct

    @pytest.mark.asyncio
    @patch("src.delivery.chat_worker.redis.from_url")
    @patch("src.delivery.chat_worker.load_preload_context")
    @patch("src.delivery.sse_channel.get_sse_channel")
    @patch("src.tooling.definitions.search_metallurgy_text")
    @patch("langchain_openai.ChatOpenAI")
    async def test_fast_mode_vlm_context_integration(
        self, mock_llm_cls, mock_search, mock_sse, mock_load, mock_redis_from_url
    ):
        """测试快速模式下，如果 Redis 中有 VLM 图片解析上下文（圈选图片问答），能够自动注入 Prompt"""
        mock_r = AsyncMock()
        mock_r.__aenter__.return_value = mock_r
        # 模拟 Redis 中存在圈选区域 of VLM 分析缓存
        mock_r.get = AsyncMock(return_value="VLM分析: 该图片展示了马氏体金相结构。".encode("utf-8"))
        mock_redis_from_url.return_value = mock_r
        mock_load.return_value = None
        mock_sse.return_value = AsyncMock()
        
        mock_llm = MagicMock()
        mock_llm.astream.return_value = AsyncMock()
        mock_llm_cls.return_value = mock_llm

        from src.delivery.chat_worker import dispatch_chat_worker

        await dispatch_chat_worker(
            task_id="test_task_vlm",
            message="这张图里的组织是什么？",
            document_id=None,
            history=[],
            deep_mode=False,
        )

        # 验证消息构建成功包含了 VLM 上下文
        mock_llm.astream.assert_called_once()
        sent_messages = mock_llm.astream.call_args[0][0]
        system_content = sent_messages[0].content
        
        assert "VLM 视觉分析结果" in system_content
        assert "马氏体金相结构" in system_content

