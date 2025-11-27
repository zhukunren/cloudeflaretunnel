#!/bin/bash
# Cloudflared 隧道状态巡检脚本 (Supervisor 版)

set -euo pipefail

# 颜色
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
CONFIG_FILE="$PROJECT_ROOT/config/tunnels.json"
PID_DIR="$PROJECT_ROOT/logs/pids"
SUPERVISOR_SERVICE="tunnel-supervisor.service"
SUPERVISOR_LOG="$PROJECT_ROOT/logs/tunnel_supervisor.service.log"

# 读取 cloudflared 路径
CLOUDFLARED="$(python3 - "$CONFIG_FILE" <<'PY'
import json, pathlib, sys
cfg = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path("")
if cfg.exists():
    try:
        data = json.loads(cfg.read_text(encoding="utf-8"))
        path = data.get("cloudflared_path")
        if path:
            print(path)
    except Exception:
        pass
PY
)"
[ -z "$CLOUDFLARED" ] && CLOUDFLARED="$PROJECT_ROOT/cloudflared"

# 读取隧道列表
mapfile -t TUNNEL_LIST < <(python3 - "$CONFIG_FILE" <<'PY'
import json, pathlib, sys
cfg = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path("")
names = []
if cfg.exists():
    try:
        data = json.loads(cfg.read_text(encoding="utf-8"))
        for item in data.get("tunnels", []):
            name = item.get("name")
            if name:
                names.append(name)
    except Exception:
        pass
names = names or ["homepage"]
for name in names:
    print(name)
PY
)

usage() {
    echo "用法: $0 [--tunnel 名称] [--only-issues]"
    exit 1
}

TARGET_TUNNEL=""
ONLY_ISSUES=0
while [[ $# -gt 0 ]]; do
    case "$1" in
        -t|--tunnel)
            shift
            TARGET_TUNNEL="${1:-}"
            [[ -z "$TARGET_TUNNEL" ]] && usage
            ;;
        -i|--only-issues)
            ONLY_ISSUES=1
            ;;
        -h|--help)
            usage
            ;;
        *)
            usage
            ;;
    esac
    shift
done

if [[ -n "$TARGET_TUNNEL" ]]; then
    TUNNEL_LIST=("$TARGET_TUNNEL")
fi

echo -e "${BLUE}    Cloudflared 隧道状态检查${NC}"
echo -e "${BLUE}=====================================${NC}"
echo ""

# 1. Supervisor 服务
echo -e "${YELLOW}1. Supervisor 服务:${NC}"
if systemctl is-active --quiet "$SUPERVISOR_SERVICE" 2>/dev/null; then
    echo -e "   ${GREEN}✓ ${SUPERVISOR_SERVICE} 运行中${NC}"
    echo "   PID: $(systemctl show -p MainPID "$SUPERVISOR_SERVICE" | cut -d= -f2)"
else
    echo -e "   ${RED}✗ Supervisor 未运行${NC}"
    echo "     建议执行: sudo $PROJECT_ROOT/scripts/deploy_supervisor.sh"
fi
if systemctl is-active --quiet tunnel-monitor-improved.service 2>/dev/null || \
   systemctl is-active --quiet tunnel-monitor.service 2>/dev/null; then
    echo -e "   ${YELLOW}⚠ 仍检测到旧监控服务，请先停止以避免冲突${NC}"
fi
echo ""

# 2. 每个隧道的运行/连接状态
echo -e "${YELLOW}2. 隧道健康检查:${NC}"
printf "   %-15s %-8s %-10s %-10s\n" "名称" "PID" "连接数" "状态"
printf "   %-15s %-8s %-10s %-10s\n" "---------------" "------" "--------" "----------"

declare -A PIDS
declare -A CONNS
declare -A ISSUES
rows_printed=0

for tunnel in "${TUNNEL_LIST[@]}"; do
    pid="$(pgrep -o -f "tunnel.*run.*${tunnel}" 2>/dev/null || true)"
    PIDS["$tunnel"]="$pid"

    if [ -x "$CLOUDFLARED" ]; then
        json="$("$CLOUDFLARED" tunnel info --output json "$tunnel" 2>/dev/null || true)"
        conns="$(echo "$json" | python3 -c '
import json, sys
data = json.loads(sys.stdin.read() or "null")
total = 0
if isinstance(data, dict):
    for conn in data.get("conns", []):
        if isinstance(conn, dict):
            total += len(conn.get("conns", []))
print(total)
' 2>/dev/null || printf 0)"
    else
        json=""
        conns=0
    fi
    CONNS["$tunnel"]="$conns"

    status="${GREEN}健康${NC}"
    if [ -z "$pid" ]; then
        status="${RED}无进程${NC}"
        ISSUES["$tunnel"]=1
    elif [ "$conns" -eq 0 ]; then
        status="${YELLOW}无连接${NC}"
        ISSUES["$tunnel"]=1
    fi

    if [[ $ONLY_ISSUES -eq 1 && -z "${ISSUES[$tunnel]:-}" ]]; then
        continue
    fi

    printf "   %-15s %-8s %-10s %b\n" "$tunnel" "${pid:-'-'}" "$conns" "$status"
    rows_printed=$((rows_printed + 1))
done
if [[ $ONLY_ISSUES -eq 1 && $rows_printed -eq 0 ]]; then
    echo "   所有隧道运行正常。"
fi
echo ""

# 3. PID 文件/锁信息
echo -e "${YELLOW}3. PID/锁信息:${NC}"
LOCK_FILE="$PID_DIR/tunnel_supervisor.lock"
if [ -f "$LOCK_FILE" ]; then
    echo "   锁文件: $LOCK_FILE"
    cat "$LOCK_FILE"
else
    echo "   未找到锁文件"
fi
if ls "$PID_DIR"/*.pid.json >/dev/null 2>&1; then
    echo "   PID 记录:"
    for file in "$PID_DIR"/*.pid.json; do
        printf "     - %s\n" "$(basename "$file")"
    done
else
    echo "   暂无 PID 记录"
fi
echo ""

# 4. 最近日志
echo -e "${YELLOW}4. 最近日志:${NC}"
if [ -f "$SUPERVISOR_LOG" ]; then
    tail -n 5 "$SUPERVISOR_LOG" | sed 's/^/   /'
else
    echo "   ${YELLOW}日志文件不存在: $SUPERVISOR_LOG${NC}"
fi
echo ""

# 5. 系统 UDP 缓冲区
echo -e "${YELLOW}5. 系统 UDP 缓冲区:${NC}"
RMEM_MAX="$(sysctl -n net.core.rmem_max 2>/dev/null || echo 0)"
if [ "$RMEM_MAX" -ge 7340032 ]; then
    echo -e "   ${GREEN}✓ rmem_max=$RMEM_MAX${NC}"
else
    echo -e "   ${YELLOW}⚠ rmem_max=$RMEM_MAX，建议运行 sudo $PROJECT_ROOT/scripts/optimize_udp_buffer.sh${NC}"
fi
echo ""

# 总结
echo -e "${BLUE}=====================================${NC}"
echo -e "${BLUE}            状态总结${NC}"
echo -e "${BLUE}=====================================${NC}"

issue_count=0
if ! systemctl is-active --quiet "$SUPERVISOR_SERVICE" 2>/dev/null; then
    echo -e "${RED}• Supervisor 未运行${NC}"
    ((issue_count++))
fi

for tunnel in "${TUNNEL_LIST[@]}"; do
    if [[ -n "${ISSUES[$tunnel]:-}" ]]; then
        echo -e "${RED}• 隧道 ${tunnel} 异常 (PID=${PIDS[$tunnel]:--}, 连接数=${CONNS[$tunnel]})${NC}"
        ((issue_count++))
    fi
done

if [ "$issue_count" -eq 0 ]; then
    echo -e "${GREEN}✓ 所有隧道运行正常${NC}"
else
    echo ""
    echo -e "${YELLOW}建议操作:${NC}"
    echo " 1. sudo $PROJECT_ROOT/scripts/deploy_supervisor.sh"
    echo " 2. python -m app.tunnel_supervisor status"
    echo " 3. sudo journalctl -u $SUPERVISOR_SERVICE -n 50"
fi

echo ""
