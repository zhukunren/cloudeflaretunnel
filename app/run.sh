#!/bin/bash
# Cloudflare Tunnel Manager - 快速启动脚本

cd "$(dirname "$0")"

# 激活虚拟环境
if [ -d "venv" ]; then
    source venv/bin/activate
fi

# 启动应用(现代UI)
python -m app.main "$@"
