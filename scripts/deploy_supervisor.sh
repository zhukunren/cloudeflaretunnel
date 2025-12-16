#!/bin/bash
# 安装/更新 Cloudflared Tunnel Supervisor systemd 服务

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE_NAME="tunnel-supervisor.service"
SERVICE_SRC="${PROJECT_ROOT}/scripts/systemd/${SERVICE_NAME}"
SERVICE_DEST="/etc/systemd/system/${SERVICE_NAME}"

info() { echo -e "\033[1;34m[INFO]\033[0m $*"; }
warn() { echo -e "\033[1;33m[WARN]\033[0m $*"; }
err() { echo -e "\033[1;31m[ERR ]\033[0m $*" >&2; }

require_root() {
    if [[ $EUID -ne 0 ]]; then
        err "此脚本需要 root 权限，请使用 sudo 运行。"
        exit 1
    fi
}

stop_old_services() {
    local services=(
        tunnel-monitor-improved.service
        tunnel-monitor.service
        cloudflared-monitor.service
    )
    for svc in "${services[@]}"; do
        if systemctl list-unit-files | grep -q "^${svc}"; then
            warn "停止并禁用旧服务: ${svc}"
            systemctl stop "$svc" 2>/dev/null || true
            systemctl disable "$svc" 2>/dev/null || true
        fi
    done
}

install_service() {
    info "安装 ${SERVICE_NAME}"
    install -Dm0644 "$SERVICE_SRC" "$SERVICE_DEST"
    systemctl daemon-reload
    systemctl enable "$SERVICE_NAME"
    systemctl restart "$SERVICE_NAME"
    sleep 2
    if systemctl is-active --quiet "$SERVICE_NAME"; then
        info "tunnel-supervisor 已运行。"
    else
        err "服务启动失败，请运行: journalctl -u ${SERVICE_NAME} -n 50"
        exit 1
    fi
}

show_hint() {
    cat <<EOF

下一步:
  • 查看服务状态: sudo systemctl status ${SERVICE_NAME}
  • 观察日志:       sudo journalctl -u ${SERVICE_NAME} -f
  • 更新配置:       ${PROJECT_ROOT}/config/tunnels.json
  • 手动控制:       python -m app.tunnel_supervisor status
EOF
}

main() {
    require_root
    if [[ ! -f "$SERVICE_SRC" ]]; then
        err "未找到服务模板: $SERVICE_SRC"
        exit 1
    fi

    stop_old_services
    install_service
    show_hint
}

main "$@"
