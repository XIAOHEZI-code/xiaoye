#!/usr/bin/env python3
"""
Xiaoye 后端 API 集成测试脚本
直接与后端服务通信，不依赖前端页面

使用方式:
    cd xiaoye
    python scripts/test_api.py
"""

import os
import sys
import subprocess
import requests
import json
import time
from pathlib import Path

BASE_URL = "http://localhost:8000"


def start_backend():
    """启动后端服务"""
    print("🚀 启动后端服务...")
    
    os.chdir("/home/xiaohezi/Desktop/prase _claudecode/xiaoye")
    
    env = os.environ.copy()
    env.pop("http_proxy", None)
    env.pop("https_proxy", None)
    env.pop("HTTP_PROXY", None)
    env.pop("HTTPS_PROXY", None)
    env.pop("all_proxy", None)
    env.pop("ALL_PROXY", None)
    
    proc = subprocess.Popen(
        ["/media/xiaohezi/Data/conda_envs/xiaoye/bin/python", "-c",
         "import uvicorn; from main import app; uvicorn.run(app, host='0.0.0.0', port=8000, reload=False)"],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    
    for i in range(10):
        time.sleep(1)
        try:
            requests.get(f"{BASE_URL}/docs", timeout=1)
            print("✅ 后端已启动!")
            return proc
        except:
            pass
    
    print("❌ 后端启动失败")
    return None


def test_upload_pdf():
    """测试 1: PDF 上传与防重"""
    print("\n" + "="*60)
    print("测试 1: POST /api/v1/upload_pdf")
    print("="*60)
    
    pdf_path = Path("/home/xiaohezi/Desktop/project/raptor_exp/data/双金属复合管热挤压过程数值模拟_刘建彬.pdf")
    if not pdf_path.exists():
        pdf_path = Path("/home/xiaohezi/Desktop/project/raptor_exp/data/双金属复合管热液压成形过程数值模拟_欧阳可欣.pdf")
    
    if not pdf_path.exists():
        print(f"❌ PDF 文件不存在")
        return None
    
    print(f"📤 上传文件: {pdf_path.name}")
    
    with open(pdf_path, "rb") as f:
        files = {"file": (pdf_path.name, f, "application/pdf")}
        resp = requests.post(f"{BASE_URL}/api/v1/upload_pdf", files=files)
    
    print(f"📥 响应状态: {resp.status_code}")
    data = resp.json()
    print(f"📥 响应内容: {json.dumps(data, indent=2, ensure_ascii=False)}")
    
    if data.get("documentId"):
        print(f"✅ 上传成功! documentId: {data['documentId']}")
        return data["documentId"]
    return None


def test_fork_agent(document_id: str):
    """测试 2: Fork Agent 触发"""
    print("\n" + "="*60)
    print("测试 2: POST /api/v1/fork_agent")
    print("="*60)
    
    payload = {
        "taskId": f"test_task_{int(time.time())}",
        "documentId": document_id,
        "type": "analyze_region",
        "bbox": {
            "x0": 0.1,
            "y0": 0.1,
            "x1": 0.5,
            "y1": 0.5,
            "pageNumber": 1
        }
    }
    
    print(f"📤 发送任务: {payload['taskId']}")
    print(f"📤 documentId: {document_id}")
    print(f"📤 bbox: {payload['bbox']}")
    
    resp = requests.post(f"{BASE_URL}/api/v1/fork_agent", json=payload)
    
    print(f"📥 响应状态: {resp.status_code}")
    data = resp.json()
    print(f"📥 响应内容: {json.dumps(data, indent=2, ensure_ascii=False)}")
    
    if data.get("status") == "ok":
        print("✅ Fork Agent 已触发!")
        return payload["taskId"]
    return None


def test_retrieval_semantic():
    """测试 3: 语义检索"""
    print("\n" + "="*60)
    print("测试 3: POST /api/v1/debug/retrieval/test (语义)")
    print("="*60)
    
    payload = {
        "query": "不锈钢 疲劳性能",
        "top_k": 3
    }
    
    print(f"📤 查询: {payload['query']}")
    
    try:
        resp = requests.post(f"{BASE_URL}/api/v1/debug/retrieval/test", json=payload)
        print(f"📥 响应状态: {resp.status_code}")
        
        if resp.status_code == 200:
            data = resp.json()
            print(f"📥 响应: {json.dumps(data, indent=2, ensure_ascii=False)[:500]}...")
            return data
        else:
            print(f"❌ 错误: {resp.text}")
    except Exception as e:
        print(f"❌ 请求失败: {e}")
    
    return None


def test_retrieval_graph():
    """测试 4: 图谱检索"""
    print("\n" + "="*60)
    print("测试 4: POST /api/v1/debug/retrieval/test (图谱)")
    print("="*60)
    
    payload = {
        "query": "304钢",
        "top_k": 3,
        "test_graph_entity": "304钢"
    }
    
    print(f"📤 查询实体: {payload['test_graph_entity']}")
    
    try:
        resp = requests.post(f"{BASE_URL}/api/v1/debug/retrieval/test", json=payload)
        print(f"📥 响应状态: {resp.status_code}")
        
        if resp.status_code == 200:
            data = resp.json()
            print(f"📥 图谱关系: {json.dumps(data.get('graph_direct_relations'), indent=2, ensure_ascii=False)[:500] if data.get('graph_direct_relations') else '无数据'}")
            return data
        else:
            print(f"❌ 错误: {resp.text}")
    except Exception as e:
        print(f"❌ 请求失败: {e}")
    
    return None


def test_langchain_stream():
    """测试 5: LangGraph 流式调试"""
    print("\n" + "="*60)
    print("测试 5: POST /api/v1/debug/langchain/test_stream")
    print("="*60)
    
    payload = {
        "query": "解释什么是双金属复合管的疲劳性能"
    }
    
    print(f"📤 查询: {payload['query']}")
    
    try:
        resp = requests.post(f"{BASE_URL}/api/v1/debug/langchain/test_stream", json=payload, timeout=60)
        print(f"📥 响应状态: {resp.status_code}")
        
        if resp.status_code == 200:
            data = resp.json()
            print(f"📥 Agent 轨迹: {json.dumps(data, indent=2, ensure_ascii=False)[:1000]}...")
            return data
        else:
            print(f"❌ 错误: {resp.text}")
    except Exception as e:
        print(f"❌ 请求失败: {e}")
    
    return None


def test_vlm():
    """测试 6: VLM 图像分析"""
    print("\n" + "="*60)
    print("测试 6: POST /api/v1/debug/vlm/test")
    print("="*60)
    
    img_path = Path("../冶金科技竞赛/双金属复合管热挤压过程数值模拟_刘建彬.pdf")
    if not img_path.exists():
        print("❌ 无测试图片")
        return None
    
    print(f"📤 上传图片: {img_path.name}")
    
    with open(img_path, "rb") as f:
        files = {"file": (img_path.name, f, "application/pdf")}
        resp = requests.post(f"{BASE_URL}/api/v1/debug/vlm/test", files=files)
    
    print(f"📥 响应状态: {resp.status_code}")
    data = resp.json()
    print(f"📥 VLM 结果: {json.dumps(data, indent=2, ensure_ascii=False)[:500]}...")
    
    return data


def test_sse_stream():
    """测试 7: SSE 流式接收"""
    print("\n" + "="*60)
    print("测试 7: GET /api/v1/notebook/stream")
    print("="*60)
    print("📡 启动 SSE 监听 (5秒超时)...")
    
    try:
        resp = requests.get(f"{BASE_URL}/api/v1/notebook/stream", stream=True, timeout=5)
        print(f"📥 连接状态: {resp.status_code}")
        
        count = 0
        for line in resp.iter_lines():
            if count >= 5:
                break
            if line:
                decoded = line.decode('utf-8')
                if decoded.startswith('data:'):
                    print(f"📥 收到: {decoded[:100]}...")
                    count += 1
        
        print(f"✅ 收到 {count} 条消息")
        return True
    except Exception as e:
        print(f"❌ SSE 连接失败: {e}")
    
    return None


def main():
    print("🚀 Xiaoye API 集成测试")
    print(f"📡 后端地址: {BASE_URL}")
    
    print("\n" + "="*60)
    print("测试 1: PDF 上传与防重")
    print("="*60)
    doc_id = test_upload_pdf()
    
    if doc_id:
        print("\n" + "="*60)
        print("测试 2: Fork Agent 触发")
        print("="*60)
        test_fork_agent(doc_id)
    
    print("\n" + "="*60)
    print("测试 3: 语义检索")
    print("="*60)
    test_retrieval_semantic()
    
    print("\n" + "="*60)
    print("测试 4: 图谱检索")
    print("="*60)
    test_retrieval_graph()
    
    print("\n" + "="*60)
    print("测试 5: LangGraph 流式")
    print("="*60)
    test_langchain_stream()
    
    print("\n" + "="*60)
    print("测试 6: SSE 流式")
    print("="*60)
    test_sse_stream()
    
    print("\n" + "="*60)
    print("✅ 所有测试完成!")
    print("="*60)


if __name__ == "__main__":
    backend_proc = start_backend()
    if backend_proc:
        try:
            main()
        finally:
            print("\n🛑 关闭后端...")
            backend_proc.terminate()
    else:
        print("❌ 无法启动后端，测试取消")