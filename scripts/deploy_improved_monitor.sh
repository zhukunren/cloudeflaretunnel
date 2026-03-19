#!/bin/bash
# 快速部署改进的隧道监控服务

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

echo "========================================"
echo "Cloudflared 隧道稳定性改进部署脚本"
echo "========================================"

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 检查Python3
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}错误: 未找到Python3${NC}"
    exit 1
fi

# 安装Python依赖
echo -e "${YELLOW}1. 安装Python依赖...${NC}"
pip3 install requests --user 2>/dev/null || true

# 停止当前监控服务
echo -e "${YELLOW}2. 停止当前监控服务...${NC}"
sudo systemctl stop tunnel-monitor-improved.service 2>/dev/null || true
pkill -f tunnel_monitor_improved.py 2>/dev/null || true

# 备份当前配置
echo -e "${YELLOW}3. 备份当前配置...${NC}"
BACKUP_DIR="$PROJECT_ROOT/backups/$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BACKUP_DIR"

if [ -f "$PROJECT_ROOT/tunnels/homepage/config.yml" ]; then
    cp "$PROJECT_ROOT/tunnels/homepage/config.yml" "$BACKUP_DIR/"
    echo "   配置已备份到: $BACKUP_DIR"
fi

# 选择配置版本
echo -e "${YELLOW}4. 选择隧道配置版本${NC}"
echo "   1) 使用优化配置（推荐）"
echo "   2) 保留当前配置"
read -p "请选择 (1/2): " config_choice

if [ "$config_choice" = "1" ]; then
    echo "   应用优化配置..."
    cp "$PROJECT_ROOT/tunnels/homepage/config_optimized.yml" "$PROJECT_ROOT/tunnels/homepage/config.yml"
    echo -e "${GREEN}   ✓ 优化配置已应用${NC}"
else
    echo "   保留当前配置"
fi

# 优化系统设置（需要sudo）
echo -e "${YELLOW}5. 是否优化系统UDP缓冲区？（需要sudo权限）${NC}"
read -p "优化系统设置? (y/n): " optimize_choice

if [ "$optimize_choice" = "y" ]; then
    chmod +x "$PROJECT_ROOT/scripts/optimize_udp_buffer.sh"
    sudo "$PROJECT_ROOT/scripts/optimize_udp_buffer.sh"
    echo -e "${GREEN}   ✓ 系统优化完成${NC}"
fi

# 测试改进的监控脚本
echo -e "${YELLOW}6. 测试改进的监控脚本...${NC}"
timeout 10 python3 "$PROJECT_ROOT/app/tunnel_monitor_improved.py" homepage &
TEST_PID=$!
sleep 5

if ps -p $TEST_PID > /dev/null 2>&1; then
    echo -e "${GREEN}   ✓ 监控脚本运行正常${NC}"
    kill $TEST_PID 2>/dev/null || true
else
    echo -e "${RED}   ✗ 监控脚本启动失败${NC}"
    exit 1
fi

# 安装systemd服务
echo -e "${YELLOW}7. 安装systemd服务...${NC}"
sudo cp "$PROJECT_ROOT/tunnel-monitor-improved.service" /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable tunnel-monitor-improved.service
echo -e "${GREEN}   ✓ 服务已安装并设置开机自启${NC}"

# 启动服务
echo -e "${YELLOW}8. 启动监控服务...${NC}"
sudo systemctl start tunnel-monitor-improved.service

# 等待服务启动
sleep 3

# 检查服务状态
if systemctl is-active --quiet tunnel-monitor-improved.service; then
    echo -e "${GREEN}   ✓ 服务启动成功${NC}"
else
    echo -e "${RED}   ✗ 服务启动失败${NC}"
    echo "查看日志: sudo journalctl -u tunnel-monitor-improved.service -n 50"
    exit 1
fi

echo ""
echo -e "${GREEN}========================================"
echo "部署完成！"
echo "========================================${NC}"
echo ""
echo "有用的命令："
echo "  查看服务状态:  systemctl status tunnel-monitor-improved.service"
echo "  查看实时日志:  tail -f $PROJECT_ROOT/logs/tunnel_monitor_improved.log"
echo "  重启服务:      sudo systemctl restart tunnel-monitor-improved.service"
echo "  停止服务:      sudo systemctl stop tunnel-monitor-improved.service"
echo "  查看隧道状态:  $PROJECT_ROOT/cloudflared tunnel info homepage"
echo ""
echo "如果遇到问题，请查看日志文件："
echo "  - 监控日志: $PROJECT_ROOT/logs/tunnel_monitor_improved.log"
echo "  - 隧道日志: $PROJECT_ROOT/logs/persistent/cloudflared_homepage.log"
