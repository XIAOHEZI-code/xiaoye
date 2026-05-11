#!/bin/bash
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY all_proxy ALL_PROXY
exec /media/xiaohezi/Data/conda_envs/xiaoye/bin/python -c "
import uvicorn
from main import app
uvicorn.run(app, host='0.0.0.0', port=8000, reload=False)
"