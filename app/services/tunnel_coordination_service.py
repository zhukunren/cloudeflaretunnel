from __future__ import annotations

from dataclasses import dataclass
from typing import Any

try:
    from ..utils.process_tracker import SupervisorLock
    from ..utils.supervisor_client import SupervisorClient
except (ImportError, ValueError):
    from utils.process_tracker import SupervisorLock  # type: ignore
    from utils.supervisor_client import SupervisorClient  # type: ignore


_API_ERROR_KEYWORDS = (
    "rest request failed",
    "api call",
    "internal server error",
    "service unavailable",
    "status 5",
    "error parsing tunnel",
    "隧道信息不完整",
)


@dataclass(frozen=True)
class SupervisorSyncResult:
    active: bool
    available: bool
    info: dict[str, Any] | None
    ui_message: str | None = None
    ui_level: str = "info"
    logger_message: str | None = None


@dataclass(frozen=True)
class AutoStartToggleResult:
    enabled: bool
    target: str | None
    trigger_now: bool
    auto_start_done: bool
    ui_message: str | None = None
    ui_level: str = "info"
    logger_message: str | None = None
    dialog_title: str | None = None
    dialog_message: str | None = None


@dataclass(frozen=True)
class AutoStartPlan:
    action: str
    target: str | None = None
    ui_message: str | None = None
    ui_level: str = "info"
    logger_message: str | None = None


@dataclass(frozen=True)
class HealthCheckResult:
    ok: bool | None
    detail: str
    reason: str


@dataclass(frozen=True)
class AutoHealDecision:
    next_failure_count: int | None = None
    clear_failure: bool = False
    mark_pending: bool = False
    restart: bool = False
    ui_message: str | None = None
    ui_level: str = "info"
    logger_message: str | None = None
    status_message: str | None = None


class TunnelCoordinationService:
    """Coordinate supervisor ownership, auto-start, and auto-heal decisions."""

    def __init__(
        self,
        supervisor_lock: SupervisorLock | None = None,
        supervisor_client: SupervisorClient | None = None,
    ):
        self.supervisor_lock = supervisor_lock
        self.supervisor_client = supervisor_client

    @staticmethod
    def _clean_name(value: str | None) -> str | None:
        text = str(value or "").strip()
        return text or None

    def sync_supervisor_state(
        self,
        previous_active: bool,
        *,
        log_message: bool = True,
    ) -> SupervisorSyncResult:
        available = self.supervisor_client.is_available() if self.supervisor_client else False
        info = self.supervisor_lock.info() if self.supervisor_lock else None
        active = bool(info and info.get("alive"))

        if not log_message:
            return SupervisorSyncResult(active=active, available=available, info=info)

        if active and not previous_active:
            pid = info.get("pid", "?") if info else "?"
            owner = info.get("owner", "tunnel-supervisor") if info else "tunnel-supervisor"
            if available:
                return SupervisorSyncResult(
                    active=active,
                    available=available,
                    info=info,
                    ui_message=f"检测到守护进程 (PID: {pid}, owner: {owner}) 正在运行，GUI 将通过守护进程执行操作。",
                    ui_level="info",
                    logger_message="GUI 将把启动/停止请求转发给守护进程",
                )
            return SupervisorSyncResult(
                active=active,
                available=available,
                info=info,
                ui_message=f"检测到守护进程正在管理隧道 (PID: {pid})，GUI 无法直接控制。",
                ui_level="warning",
                logger_message="守护进程运行中但缺少客户端支持",
            )

        if not active and previous_active:
            return SupervisorSyncResult(
                active=active,
                available=available,
                info=info,
                ui_message="守护进程已离线，GUI 恢复直接管理。",
                ui_level="info",
                logger_message="守护进程离线，GUI 恢复控制权",
            )

        return SupervisorSyncResult(active=active, available=available, info=info)

    def evaluate_autostart_toggle(
        self,
        enabled: bool,
        *,
        selected_name: str | None,
        last_selected: str | None,
    ) -> AutoStartToggleResult:
        if not enabled:
            return AutoStartToggleResult(
                enabled=False,
                target=None,
                trigger_now=False,
                auto_start_done=True,
                ui_message="已关闭自动启动选项。",
                ui_level="info",
                logger_message="关闭自动启动",
            )

        target = self._clean_name(selected_name) or self._clean_name(last_selected)
        if not target:
            return AutoStartToggleResult(
                enabled=False,
                target=None,
                trigger_now=False,
                auto_start_done=True,
                ui_message="自动启动已启用，但尚未指定隧道，请先选择一个隧道。",
                ui_level="warning",
                logger_message="自动启动缺少目标",
                dialog_title="自动启动",
                dialog_message="请先选择准备自动启动的隧道，然后再次启用该选项。",
            )

        return AutoStartToggleResult(
            enabled=True,
            target=target,
            trigger_now=True,
            auto_start_done=False,
            ui_message=f"自动启动已启用，将尝试激活隧道: {target}",
            ui_level="info",
            logger_message=f"启用自动启动: {target}",
        )

    def plan_autostart(
        self,
        *,
        already_done: bool,
        force: bool,
        enabled: bool,
        target: str | None,
        supervisor_active: bool,
        supervisor_available: bool,
        is_running: bool,
    ) -> AutoStartPlan:
        if already_done and not force:
            return AutoStartPlan(action="noop")

        if not enabled:
            return AutoStartPlan(action="noop")

        target = self._clean_name(target)
        if not target:
            return AutoStartPlan(
                action="noop",
                ui_message="自动启动已启用，但未找到可用的隧道记录。",
                ui_level="warning",
                logger_message="自动启动缺少目标",
            )

        if supervisor_active and supervisor_available:
            return AutoStartPlan(action="supervisor", target=target)

        if supervisor_active:
            return AutoStartPlan(
                action="noop",
                target=target,
                ui_level="warning",
                logger_message="检测到守护进程运行中，但 GUI 无法通信，自动启动跳过",
            )

        if is_running:
            return AutoStartPlan(
                action="noop",
                target=target,
                ui_message=f"自动启动: 隧道 {target} 已在运行。",
                ui_level="info",
                logger_message=f"自动启动跳过，{target} 已运行",
            )

        return AutoStartPlan(
            action="direct",
            target=target,
            ui_message=f"开机自动激活隧道: {target}",
            ui_level="info",
            logger_message=f"开始自动激活隧道: {target}",
        )

    @staticmethod
    def normalize_health_check(ok: bool | None, detail: str | None) -> HealthCheckResult:
        detail_text = str(detail or "").strip()
        if ok is True:
            return HealthCheckResult(ok=True, detail=detail_text, reason="healthy")
        if ok is None:
            return HealthCheckResult(ok=None, detail=detail_text, reason="unknown")

        lower_detail = detail_text.lower()
        if any(keyword in lower_detail for keyword in _API_ERROR_KEYWORDS):
            return HealthCheckResult(ok=None, detail=detail_text, reason="api_error")
        if "超时" in lower_detail or "timeout" in lower_detail:
            return HealthCheckResult(ok=False, detail=detail_text, reason="timeout")
        return HealthCheckResult(ok=False, detail=detail_text, reason="unhealthy")

    @staticmethod
    def plan_auto_heal(
        tunnel_name: str,
        *,
        health: HealthCheckResult,
        enabled: bool,
        supervisor_managed: bool,
        process_running: bool,
        failure_count: int,
        pending: bool,
        failure_threshold: int = 3,
    ) -> AutoHealDecision:
        if health.reason == "api_error":
            return AutoHealDecision(
                clear_failure=True,
                ui_message=f"健康检查返回 API/5xx 错误，跳过自动重连。详情：{health.detail}",
                ui_level="info",
                logger_message=f"自动重连跳过（API/5xx）：{health.detail}",
            )

        if health.ok is None:
            return AutoHealDecision()

        if not enabled or supervisor_managed or not process_running or health.ok is True:
            return AutoHealDecision(clear_failure=True)

        if health.reason == "timeout":
            return AutoHealDecision(
                clear_failure=True,
                ui_message=f"健康检查超时但隧道仍在运行，忽略自动重连。详情：{health.detail}",
                ui_level="warning",
            )

        if pending:
            return AutoHealDecision()

        next_failures = max(0, failure_count) + 1
        if next_failures < failure_threshold:
            return AutoHealDecision(next_failure_count=next_failures)

        notice = health.detail or "无活跃连接"
        return AutoHealDecision(
            next_failure_count=0,
            mark_pending=True,
            restart=True,
            ui_message=f"检测到隧道 {tunnel_name} 无活跃连接，自动重连中… ({notice})",
            ui_level="warning",
            logger_message=f"自动重连：{tunnel_name} 无活跃连接，准备重启 ({notice})",
            status_message=f"自动重连 {tunnel_name}…",
        )
