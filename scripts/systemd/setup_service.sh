#!/bin/bash
#
# Cloudflared 隧道监控服务安装脚本
# 用于设置开机自启动的系统服务
#

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 配置
SERVICE_NAME="cloudflared-monitor"
SERVICE_FILE="${SERVICE_NAME}.service"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_SOURCE="${SCRIPT_DIR}/${SERVICE_FILE}"
SERVICE_DEST="/etc/systemd/system/${SERVICE_FILE}"
MONITOR_SCRIPT="${SCRIPT_DIR}/app/tunnel_monitor.py"

# 打印带颜色的消息
print_msg() {
    local color=$1
    local msg=$2
    echo -e "${color}${msg}${NC}"
}

# 检查是否以 root 权限运行
check_root() {
    if [ "$EUID" -ne 0 ]; then
        print_msg $RED "错误: 此脚本需要 root 权限运行"
        echo "请使用: sudo $0"
        exit 1
    fi
}

# 检查必要文件
check_files() {
    print_msg $YELLOW "检查必要文件..."

    if [ ! -f "$SERVICE_SOURCE" ]; then
        print_msg $RED "错误: 服务文件不存在: $SERVICE_SOURCE"
        exit 1
    fi

    if [ ! -f "$MONITOR_SCRIPT" ]; then
        print_msg $RED "错误: 监控脚本不存在: $MONITOR_SCRIPT"
        exit 1
    fi

    # 检查 cloudflared 是否安装
    if ! command -v cloudflared &> /dev/null; then
        print_msg $RED "错误: cloudflared 未安装"
        echo "请先安装 cloudflared"
        exit 1
    fi

    print_msg $GREEN "✓ 文件检查通过"
}

# 安装服务
install_service() {
    print_msg $YELLOW "安装系统服务..."

    # 复制服务文件
    cp "$SERVICE_SOURCE" "$SERVICE_DEST"
    chmod 644 "$SERVICE_DEST"

    # 重新加载 systemd
    systemctl daemon-reload

    print_msg $GREEN "✓ 服务安装完成"
}

# 启动服务
start_service() {
    print_msg $YELLOW "启动服务..."

    # 启用开机自启动
    systemctl enable "$SERVICE_NAME"

    # 启动服务
    systemctl start "$SERVICE_NAME"

    # 等待几秒钟
    sleep 3

    # 检查服务状态
    if systemctl is-active --quiet "$SERVICE_NAME"; then
        print_msg $GREEN "✓ 服务启动成功"
    else
        print_msg $RED "✗ 服务启动失败"
        echo "查看日志: journalctl -u $SERVICE_NAME -n 50"
        exit 1
    fi
}

# 显示服务状态
show_status() {
    print_msg $YELLOW "\n服务状态:"
    systemctl status "$SERVICE_NAME" --no-pager || true

    print_msg $YELLOW "\n最近日志:"
    journalctl -u "$SERVICE_NAME" -n 10 --no-pager || true
}

# 卸载服务
uninstall_service() {
    print_msg $YELLOW "卸载服务..."

    # 停止服务
    systemctl stop "$SERVICE_NAME" 2>/dev/null || true

    # 禁用服务
    systemctl disable "$SERVICE_NAME" 2>/dev/null || true

    # 删除服务文件
    rm -f "$SERVICE_DEST"

    # 重新加载 systemd
    systemctl daemon-reload

    print_msg $GREEN "✓ 服务卸载完成"
}

# 显示使用帮助
show_usage() {
    echo "使用方法:"
    echo "  $0 install   - 安装并启动服务"
    echo "  $0 uninstall - 卸载服务"
    echo "  $0 restart   - 重启服务"
    echo "  $0 stop      - 停止服务"
    echo "  $0 start     - 启动服务"
    echo "  $0 status    - 查看服务状态"
    echo "  $0 logs      - 查看服务日志"
}

# 主函数
main() {
    case "${1:-}" in
        install)
            check_root
            check_files
            install_service
            start_service
            show_status
            print_msg $GREEN "\n✓ 安装完成！服务将在系统启动时自动运行"
            ;;
        uninstall)
            check_root
            uninstall_service
            ;;
        restart)
            check_root
            systemctl restart "$SERVICE_NAME"
            print_msg $GREEN "✓ 服务已重启"
            show_status
            ;;
        stop)
            check_root
            systemctl stop "$SERVICE_NAME"
            print_msg $GREEN "✓ 服务已停止"
            ;;
        start)
            check_root
            systemctl start "$SERVICE_NAME"
            print_msg $GREEN "✓ 服务已启动"
            show_status
            ;;
        status)
            show_status
            ;;
        logs)
            journalctl -u "$SERVICE_NAME" -f
            ;;
        *)
            show_usage
            ;;
    esac
}

# 执行主函数
main "$@"