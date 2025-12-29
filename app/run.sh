#!/bin/bash
# Cloudflare Tunnel Manager - 快速启动脚本

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

# 激活虚拟环境
if [ -d ".venv" ]; then
    # 推荐：项目根目录 .venv
    source .venv/bin/activate
elif [ -d "venv" ]; then
    # 兼容：项目根目录 venv
    source venv/bin/activate
elif [ -d "$SCRIPT_DIR/venv" ]; then
    # 兼容：历史版本 app/venv
    source "$SCRIPT_DIR/venv/bin/activate"
fi

# 启动应用(现代UI)
python -m app.main "$@"
