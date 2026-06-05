import pytest
import json
import time
from unittest.mock import patch, MagicMock, AsyncMock
from src.tooling.definitions import execute_metallurgy_python, delegate_scientific_visualization, current_task_id
from src.delivery.fork_worker import _handle_sandbox_agent

@pytest.mark.small
@patch("src.tooling.definitions.get_sandbox")
@patch("redis.from_url")
def test_execute_metallurgy_python_success(mock_redis_from_url, mock_get_sandbox):
    # Mock sandbox output
    mock_sandbox = MagicMock()
    mock_sandbox.run_code.return_value = "Result: 42"
    mock_get_sandbox.return_value = mock_sandbox

    # Run tool
    result = execute_metallurgy_python("print(42)")

    # Assert sandbox run
    mock_sandbox.run_code.assert_called_once_with("print(42)")
    assert result == "Result: 42"
    # No image, so no Redis publish should occur
    mock_redis_from_url.assert_not_called()


@pytest.mark.small
@patch("src.tooling.definitions.get_sandbox")
@patch("redis.from_url")
def test_execute_metallurgy_python_with_image(mock_redis_from_url, mock_get_sandbox):
    # Mock sandbox output containing image sighting
    image_text = "[System: Sighted an Image - base64_image_data_here]"
    mock_sandbox = MagicMock()
    mock_sandbox.run_code.return_value = f"Finished plotting.\n{image_text}"
    mock_get_sandbox.return_value = mock_sandbox

    # Mock Redis client
    mock_redis = MagicMock()
    mock_redis_from_url.return_value = mock_redis

    # Run tool
    result = execute_metallurgy_python("import matplotlib.pyplot as plt\nplt.plot()")

    # Assert results and Redis SSE publication
    assert "Sighted an Image" in result
    mock_redis.publish.assert_called_once()
    published_data = mock_redis.publish.call_args[0][1]
    parsed = json.loads(published_data)
    assert parsed["type"] == "sandbox_image"
    assert image_text in parsed["content"]


@pytest.mark.small
@patch("src.delivery.fork_worker.dispatch_fork_subagent")
def test_delegate_scientific_visualization(mock_dispatch):
    # Set current task id context
    token = current_task_id.set("test_parent_task")
    try:
        res = delegate_scientific_visualization("绘制304不锈钢强度曲线")
        assert "后台委派成功" in res
        assert "sub_test_parent_task" in res
        
        # Wait a tiny bit to let the daemon thread/async task invoke mock_dispatch
        time.sleep(0.1)
        mock_dispatch.assert_called_once_with(
            task_id="sub_test_parent_task",
            task_type="sandbox_agent",
            instruction="绘制304不锈钢强度曲线"
        )
    finally:
        current_task_id.reset(token)


@pytest.mark.small
@patch("src.delivery.fork_worker.redis_client")
@patch("src.delivery.fork_worker.execute_metallurgy_python")
@patch("langchain_openai.ChatOpenAI")
@pytest.mark.asyncio
async def test_handle_sandbox_agent_success(mock_chat, mock_execute_python, mock_redis):
    # Mock ChatOpenAI response
    mock_llm_instance = MagicMock()
    mock_llm_instance.ainvoke = AsyncMock()
    mock_response = MagicMock()
    mock_response.content = "```python\nprint('sandbox test')\n```"
    mock_llm_instance.ainvoke.return_value = mock_response
    mock_chat.return_value = mock_llm_instance

    # Mock execute_metallurgy_python output
    mock_execute_python.return_value = "Calculation success: 100"

    # Run the handler
    await _handle_sandbox_agent("sub_test_task", "绘制曲线")

    # Assert LLM call
    mock_llm_instance.ainvoke.assert_called_once()
    # Assert execute_metallurgy_python is called with SciencePlots prepended
    mock_execute_python.assert_called_once()
    call_arg = mock_execute_python.call_args[0][0]
    assert "scienceplots" in call_arg
    assert "plt.style.use" in call_arg
    assert "print('sandbox test')" in call_arg

    # Assert SSE events published to Redis
    assert mock_redis.publish.call_count >= 3
    # Verify some key outputs are published
    published_patches = []
    for call in mock_redis.publish.call_args_list:
        parsed_evt = json.loads(call[0][1])
        if "patch" in parsed_evt:
            published_patches.append(parsed_evt["patch"])
            
    assert any("有状态计算沙盒子智能体" in p for p in published_patches)
    assert any("正在沙盒中执行以下 Python 代码" in p for p in published_patches)
    assert any("Calculation success: 100" in p for p in published_patches)
