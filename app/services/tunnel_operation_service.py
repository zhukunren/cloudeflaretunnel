from __future__ import annotations

from typing import Any


class TunnelOperationService:
    """Build normalized start/stop results for direct and supervisor-managed flows."""

    @staticmethod
    def payload_message(payload: dict[str, Any], default: str) -> str:
        return str(payload.get("message") or payload.get("stderr") or default)

    def new_start_result(self, tunnel_name: str, managed_by: str, **overrides) -> dict[str, Any]:
        result: dict[str, Any] = {
            "ok": False,
            "stage": "prepare",
            "tunnel_name": tunnel_name,
            "managed_by": managed_by,
            "message": "",
            "summary": "",
            "detail": "",
            "messages": [],
            "warnings": [],
            "logs": [],
            "proc": None,
            "protocol": None,
            "capture_output": None,
            "log_file": None,
            "error": None,
            "hostname": None,
        }
        result.update(overrides)
        return result

    def build_direct_start_result(
        self,
        tunnel_name: str,
        launch: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        ok = bool(launch.get("ok"))
        detail = str(launch.get("detail") or "").strip()
        error = str(launch.get("error") or "").strip()
        message = detail or error or (f"隧道 {tunnel_name} 已启动" if ok else f"隧道 {tunnel_name} 启动失败")

        result = self.new_start_result(
            tunnel_name,
            "gui",
            ok=ok,
            stage="running" if ok else "launch",
            message=message,
            summary=detail or error,
            detail=detail,
            messages=list(context.get("messages", []) or []),
            warnings=list(context.get("warnings", []) or []),
            proc=launch.get("proc"),
            protocol=launch.get("protocol"),
            capture_output=launch.get("capture_output", True),
            log_file=launch.get("log_file"),
        )
        if error:
            result["error"] = error
        return result

    def build_supervisor_start_result(self, tunnel_name: str, payload: dict[str, Any]) -> dict[str, Any]:
        ok = bool(payload.get("ok"))
        default = f"隧道 {tunnel_name} {'已由守护进程启动' if ok else '启动失败'}"
        message = self.payload_message(payload, default)
        logs = payload.get("logs")
        result = self.new_start_result(
            tunnel_name,
            "supervisor",
            ok=ok,
            stage="accepted" if ok else "launch",
            message=message,
            summary=message,
            detail=str(payload.get("detail") or payload.get("stderr") or "").strip(),
            logs=list(logs) if isinstance(logs, list) else [],
        )
        if not ok:
            result["error"] = str(payload.get("stderr") or message).strip()
        return result

    def build_start_exception_result(self, tunnel_name: str, exc: Exception) -> dict[str, Any]:
        error = str(exc).strip()
        return self.new_start_result(
            tunnel_name,
            "gui",
            ok=False,
            stage="exception",
            message=error,
            summary=error,
            error=error,
        )

    def new_stop_result(self, tunnel_name: str, managed_by: str, **overrides) -> dict[str, Any]:
        result: dict[str, Any] = {
            "ok": False,
            "stage": "stop",
            "tunnel_name": tunnel_name,
            "managed_by": managed_by,
            "message": "",
            "summary": "",
            "detail": "",
            "logs": [],
            "pid": None,
            "method": None,
            "error": None,
        }
        result.update(overrides)
        return result

    def build_direct_stop_result(self, tunnel_name: str, payload: dict[str, Any]) -> dict[str, Any]:
        ok = bool(payload.get("ok"))
        message = str(payload.get("message") or "").strip()
        error = str(payload.get("error") or "").strip()
        summary = message or error or (f"隧道 {tunnel_name} 已停止" if ok else f"隧道 {tunnel_name} 停止失败")
        result = self.new_stop_result(
            tunnel_name,
            "gui",
            ok=ok,
            stage="stopped" if ok else "stop",
            message=summary,
            summary=summary,
            detail=message,
            pid=payload.get("pid"),
            method=payload.get("method"),
        )
        if error:
            result["error"] = error
        return result

    def build_supervisor_stop_result(self, tunnel_name: str, payload: dict[str, Any]) -> dict[str, Any]:
        ok = bool(payload.get("ok"))
        default = f"隧道 {tunnel_name} {'已由守护进程停止' if ok else '停止失败'}"
        message = self.payload_message(payload, default)
        logs = payload.get("logs")
        result = self.new_stop_result(
            tunnel_name,
            "supervisor",
            ok=ok,
            stage="accepted" if ok else "stop",
            message=message,
            summary=message,
            detail=str(payload.get("detail") or payload.get("stderr") or "").strip(),
            logs=list(logs) if isinstance(logs, list) else [],
        )
        if not ok:
            result["error"] = str(payload.get("stderr") or message).strip()
        return result

    def build_stop_exception_result(self, tunnel_name: str, exc: Exception) -> dict[str, Any]:
        error = str(exc).strip()
        return self.new_stop_result(
            tunnel_name,
            "gui",
            ok=False,
            stage="exception",
            message=error,
            summary=error,
            error=error,
            method="exception",
        )
