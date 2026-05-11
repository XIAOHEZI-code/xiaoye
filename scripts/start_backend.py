#!/usr/bin/env python3
import os
import subprocess
import time
import signal

# 清除代理
for k in ['http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY', 'all_proxy', 'ALL_PROXY']:
    os.environ.pop(k, None)

# 启动后端
proc = subprocess.Popen(
    ['/media/xiaohezi/Data/conda_envs/xiaoye/bin/python', '-c', 
     'import uvicorn; from main import app; uvicorn.run(app, host="0.0.0.0", port=8000, reload=False)'],
    cwd='/home/xiaohezi/Desktop/prase _claudecode/xiaoye',
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL
)

print(f'Started backend, PID: {proc.pid}')

# 等待启动
for i in range(10):
    time.sleep(1)
    import requests
    try:
        r = requests.get('http://localhost:8000/docs', timeout=1)
        if r.status_code == 200:
            print('Backend ready!')
            break
    except:
        pass

# 保持运行
try:
    proc.wait()
except KeyboardInterrupt:
    proc.terminate()