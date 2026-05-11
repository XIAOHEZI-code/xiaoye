#!/usr/bin/env python3
"""Clear proxy environment and run main.py"""
import os
import subprocess
import sys

# Clear all proxy environment variables
proxy_vars = ['http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY', 
              'all_proxy', 'ALL_PROXY', 'proxy']
for var in proxy_vars:
    if var in os.environ:
        del os.environ[var]

# Also clear any lower-case variants
os.environ.pop('http_proxy', None)
os.environ.pop('https_proxy', None)
os.environ.pop('HTTP_PROXY', None)
os.environ.pop('HTTPS_PROXY', None)
os.environ.pop('all_proxy', None)
os.environ.pop('ALL_PROXY', None)
os.environ.pop('proxy', None)

# Run main.py
result = subprocess.run([sys.executable, 'main.py'], cwd=os.path.dirname(os.path.abspath(__file__)))
sys.exit(result.returncode)