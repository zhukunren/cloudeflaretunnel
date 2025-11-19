#!/bin/bash
# Cloudflare Tunnel Manager - 快速安装脚本

set -e

echo "================================"
echo "Cloudflare Tunnel Manager 安装"
echo "================================"
echo ""

# 检查Python版本
echo "1. 检查Python版本..."
python_version=$(python3 --version 2>&1 | grep -oP '\d+\.\d+' | head -1)
required_version="3.8"

if ! python3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)"; then
    echo "错误: 需要 Python 3.8 或更高版本"
    echo "当前版本: $python_version"
    exit 1
fi
echo "✓ Python版本: $python_version"

# 创建虚拟环境
echo ""
echo "2. 创建虚拟环境..."
if [ -d "venv" ]; then
    echo "虚拟环境已存在,跳过创建"
else
    python3 -m venv venv
    echo "✓ 虚拟环境创建成功"
fi

# 激活虚拟环境
echo ""
echo "3. 激活虚拟环境..."
source venv/bin/activate
echo "✓ 虚拟环境已激活"

# 升级pip
echo ""
echo "4. 升级pip..."
pip install --upgrade pip > /dev/null
echo "✓ pip 已升级"

# 安装依赖
echo ""
echo "5. 安装依赖..."
pip install -r requirements.txt
echo "✓ 依赖安装完成"

# 检查cloudflared
echo ""
echo "6. 检查cloudflared..."
if command -v cloudflared &> /dev/null; then
    echo "✓ cloudflared 已安装: $(cloudflared --version | head -1)"
elif [ -f "../cloudflared" ]; then
    echo "✓ cloudflared 找到: ../cloudflared"
else
    echo "⚠ cloudflared 未找到"
    echo "  选项1: 应用内点击'⬇'图标自动下载"
    echo "  选项2: 手动下载 https://github.com/cloudflare/cloudflared/releases"
fi

# 创建必要目录
echo ""
echo "7. 创建目录结构..."
mkdir -p assets config logs tunnels
echo "✓ 目录创建完成"

# 完成
echo ""
echo "================================"
echo "✓ 安装完成!"
echo "================================"
echo ""
echo "启动应用:"
echo "  python -m app.main          # 现代UI"
echo "  python -m app.main --classic # 经典UI"
echo ""
echo "查看文档:"
echo "  cat README.md               # 项目说明"
echo "  cat USAGE.md                # 使用指南"
echo ""
