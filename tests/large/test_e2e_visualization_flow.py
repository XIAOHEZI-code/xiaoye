"""大型端到端测试 (Large E2E)：验证完整数据检索与画图子智能体委派流程。

测试目标：
1. 正常执行检索命令从文献库中获取 2021 年真实数据。
2. 将真实数据下发给 subagent 进行科学绘图委派。
3. subagent 在 Python 沙盒环境中编写并成功运行作图代码。
4. 生成的图片成功推送到 Redis SSE。

⚠️ 此测试会消耗真实 LLM Token，默认跳过。
   如需运行，请设置环境变量: RUN_E2E=true
"""

import os
import json
import pytest
import asyncio
import redis.asyncio as redis
from langchain_core.messages import HumanMessage
from src.core.config import settings
from src.reasoning.graph import run_worker_pipeline


@pytest.mark.asyncio
@pytest.mark.e2e
@pytest.mark.skipif(
    os.getenv("RUN_E2E", "").lower() != "true",
    reason="E2E tests consume real LLM tokens. Set RUN_E2E=true to enable.",
)
async def test_e2e_retrieval_and_visualization_flow():
    # 1. 订阅 Redis SSE 频道以监听绘图图片推送事件
    rc = redis.from_url(settings.CELERY_BROKER_URL)
    pubsub = rc.pubsub()
    await pubsub.subscribe("xiaoye_sse")

    # 2. 构建真实任务：要求查询姜国庆的论文并画出 2021 年磷石膏产量、利用量和利用率数据
    task_id = "test_e2e_viz_flow_123"
    query = (
        "结合文献《工业固废磷石膏综合治理现状及对策_姜国庆.pdf》，"
        "查询2021年我国磷石膏产量、利用量和利用率数据，并调用画图工具进行学术图表展示。"
    )

    payload = {
        "messages": [HumanMessage(content=query)],
        "deep_mode": True  # 启用深度思考模式 (qwen-max) 以确保多步 ReAct 规划精度
    }

    # 3. 异步启动端到端 Worker 流程
    pipeline_task = asyncio.create_task(run_worker_pipeline(payload, task_id))

    image_received = False
    received_patches = []
    
    try:
        # 设置超时时间（为检索+大模型长思考+沙盒绘图留出充裕的 60 秒时间）
        timeout_seconds = 60.0
        start_time = asyncio.get_event_loop().time()
        
        while (asyncio.get_event_loop().time() - start_time) < timeout_seconds:
            try:
                # 轮询获取 Redis 频道中的发布消息
                msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if msg:
                    data = json.loads(msg["data"])
                    # 记录接收到的 patch 用于调试和后续断言
                    if "patch" in data:
                        received_patches.append(data["patch"])
                    
                    # 验证要求 4：检测是否推成了图片对象或 Markdown 图片 base64 格式
                    if data.get("type") == "sandbox_image":
                        image_received = True
                        print("[Test E2E] Successfully intercepted 'sandbox_image' event from Redis SSE.")
                        break
                    elif "data:image/png;base64" in data.get("patch", ""):
                        image_received = True
                        print("[Test E2E] Successfully intercepted base64 image path patch from Redis SSE.")
                        break
            except asyncio.TimeoutError:
                pass
            
            # 如果管道已完成，提前跳出
            if pipeline_task.done():
                break

    finally:
        # 确保管道协程运行完成（捕捉可能得异常）
        try:
            final_response = await pipeline_task
            print(f"[Test E2E] Pipeline finished. Final response length: {len(final_response)}")
        except Exception as err:
            pytest.fail(f"E2E Pipeline crashed with exception: {err}")
        finally:
            await pubsub.unsubscribe("xiaoye_sse")
            await rc.close()

    # 4. 断言验证
    # 验证要求 1: 检查是否执行了 search_metallurgy_text 检索并检索到了真实数据
    all_patches_combined = "".join(received_patches)
    assert any("search_metallurgy_text" in p or "启动深度" in p for p in received_patches) or "3650" in all_patches_combined, (
        f"未检测到数据库检索调用或未正确使用 2021 年真实数据。收到 patches: {received_patches}"
    )

    # 验证要求 2 & 3: 检查是否执行了绘图委派
    assert any("delegate_scientific_visualization" in p or "委派成功" in p for p in received_patches), (
        "未检测到科学计算与绘图任务委派过程。"
    )

    # 验证要求 4: 检查 Redis 中是否收到了生成的图表图片
    assert image_received, "未在 Redis SSE 通道上监听到推送的 base64 绘图图片。"
    print("[Test E2E] All 4 requirements successfully verified!")
