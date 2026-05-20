#!/bin/bash
# 启动 Xiaoye 后端（清除代理以避免 SSE/OpenAI 错误）

cd "/home/xiaohezi/Desktop/prase _claudecode/xiaoye"

# 清除代理环境变量（保留 localhost/127.0.0.1）
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY all_proxy ALL_PROXY proxy HTTP_PROXY GRPC_PROXY GRPCS_PROXY

# 使用 xiaoye conda 环境
./env_xiaoye/bin/python main.py