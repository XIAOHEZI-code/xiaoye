import pytest
import redis
import threading
import time

@pytest.mark.integration
def test_redis_pubsub_for_sse():
    """
    测试 Redis 的发布订阅机制 (用于 SSE 流式推送后台任务状态)
    中型测试：连接本地 Redis 进行真实的队列通信，如果 Redis 未启动则优雅跳过。
    """
    try:
        r = redis.Redis.from_url("redis://localhost:6379/0")
        if not r.ping():
            pytest.skip("Redis 未在 localhost:6379 运行，跳过该测试。")
    except Exception as e:
        pytest.skip(f"Redis 连接失败，跳过测试: {e}")
        
    pubsub = r.pubsub()
    channel_name = "xiaoye_test_sse_channel"
    pubsub.subscribe(channel_name)
    
    # 在后台线程中发布消息，模拟 Celery 或后台进程的推送
    def publish_msg():
        time.sleep(0.1) # 稍等主线程 subscribe 成功
        r.publish(channel_name, "TEST_SSE_CHUNK")
        
    t = threading.Thread(target=publish_msg)
    t.start()
    
    # 阻塞接收消息
    received = False
    for message in pubsub.listen():
        if message["type"] == "message":
            data = message["data"].decode("utf-8")
            assert data == "TEST_SSE_CHUNK", "接收到的流式数据应该与发布的一致"
            received = True
            break
            
    assert received, "未能成功通过 Redis PubSub 接收到测试消息"
    t.join()
