#!/bin/bash
#
# Cloudflared 隧道监控服务状态检查脚本
# 快速查看隧道和监控服务状态
#

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

# 打印带颜色的消息
print_msg() {
    local color=$1
    local msg=$2
    echo -e "${color}${msg}${NC}"
}

# 打印分隔线
print_line() {
    echo "=================================="
}

# 检查服务状态
check_service() {
    print_line
    print_msg $CYAN "📊 监控服务状态"
    print_line

    if systemctl is-active --quiet tunnel-monitor-improved.service; then
        print_msg $GREEN "✅ 监控服务: 运行中"

        # 获取服务运行时间
        local uptime=$(systemctl show tunnel-monitor-improved.service --property=ActiveEnterTimestamp | cut -d= -f2)
        if [ -n "$uptime" ]; then
            print_msg $YELLOW "   启动时间: $uptime"
        fi

        # 获取主进程 PID
        local pid=$(systemctl show tunnel-monitor-improved.service --property=MainPID | cut -d= -f2)
        if [ "$pid" != "0" ]; then
            print_msg $YELLOW "   进程 PID: $pid"
        fi
    else
        print_msg $RED "❌ 监控服务: 未运行"
    fi

    if systemctl is-enabled --quiet tunnel-monitor-improved.service; then
        print_msg $GREEN "✅ 开机自启: 已启用"
    else
        print_msg $RED "❌ 开机自启: 未启用"
    fi
}

# 检查隧道状态
check_tunnel() {
    local tunnel_name="${1:-homepage}"

    print_line
    print_msg $CYAN "🌐 隧道状态 ($tunnel_name)"
    print_line

    # 检查 cloudflared 进程
    local cloudflared_pid=$(pgrep -f "cloudflared.*tunnel run $tunnel_name" | head -1)
    if [ -n "$cloudflared_pid" ]; then
        print_msg $GREEN "✅ Cloudflared 进程: 运行中 (PID: $cloudflared_pid)"

        # 获取进程内存使用
        local mem=$(ps -p $cloudflared_pid -o rss= 2>/dev/null | awk '{printf "%.1f MB", $1/1024}')
        if [ -n "$mem" ]; then
            print_msg $YELLOW "   内存使用: $mem"
        fi
    else
        print_msg $RED "❌ Cloudflared 进程: 未运行"
    fi

    # 检查隧道连接信息
    if cloudflared tunnel info "$tunnel_name" 2>/dev/null | grep -q "CONNECTOR ID"; then
        print_msg $GREEN "✅ 隧道连接: 正常"

        # 获取边缘节点信息
        local edge=$(cloudflared tunnel info "$tunnel_name" 2>/dev/null | grep "EDGE" | tail -1 | awk '{print $NF}')
        if [ -n "$edge" ]; then
            print_msg $YELLOW "   边缘节点: $edge"
        fi
    else
        print_msg $RED "❌ 隧道连接: 异常或未连接"
    fi
}

# 检查网站可访问性
check_website() {
    local domains=("dwzq.top" "www.dwzq.top")

    print_line
    print_msg $CYAN "🌍 网站访问测试"
    print_line

    for domain in "${domains[@]}"; do
        if timeout 3 curl -I "https://$domain" 2>/dev/null | grep -q "HTTP/2 200"; then
            print_msg $GREEN "✅ $domain: 可访问"
        else
            print_msg $RED "❌ $domain: 无法访问"
        fi
    done
}

# 显示最近日志
show_recent_logs() {
    print_line
    print_msg $CYAN "📝 最近监控日志 (最后5条)"
    print_line

    local log_file="/home/zhukunren/桌面/项目/内网穿透/logs/tunnel_monitor_improved.log"
    if [ -f "$log_file" ]; then
        tail -5 "$log_file" | while IFS= read -r line; do
            if echo "$line" | grep -q "ERROR"; then
                print_msg $RED "$line"
            elif echo "$line" | grep -q "WARNING"; then
                print_msg $YELLOW "$line"
            elif echo "$line" | grep -q "INFO"; then
                print_msg $GREEN "$line"
            else
                echo "$line"
            fi
        done
    else
        print_msg $YELLOW "日志文件不存在"
    fi
}

# 显示快捷命令
show_commands() {
    print_line
    print_msg $CYAN "🔧 常用命令"
    print_line
    echo "查看实时日志:"
    echo "  tail -f /home/zhukunren/桌面/项目/内网穿透/logs/tunnel_monitor_improved.log"
    echo ""
    echo "重启监控服务:"
    echo "  sudo systemctl restart tunnel-monitor-improved.service"
    echo ""
    echo "停止监控服务:"
    echo "  sudo systemctl stop tunnel-monitor-improved.service"
    echo ""
    echo "查看服务详细状态:"
    echo "  systemctl status tunnel-monitor-improved.service"
}

# 主函数
main() {
    clear
    print_msg $CYAN "======================================"
    print_msg $CYAN "   Cloudflared 隧道监控系统状态检查   "
    print_msg $CYAN "======================================"
    echo ""

    check_service
    echo ""
    check_tunnel "homepage"
    echo ""
    check_website
    echo ""
    show_recent_logs
    echo ""
    show_commands
    echo ""
    print_line
    print_msg $GREEN "状态检查完成 - $(date '+%Y-%m-%d %H:%M:%S')"
    print_line
}

# 执行主函数
main "$@"
