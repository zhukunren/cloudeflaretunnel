#! -*- coding: utf-8 -*-
"""
与 tunnel_supervisor CLI 交互的辅助模块。
GUI 通过该模块向守护进程发起 start/stop/status 等命令，
从而让无开发经验的用户也能通过图形界面完成日常运维。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Tuple


class SupervisorClient:
    """封装 `python -m app.tunnel_supervisor` 调用"""

    def __init__(self, project_root: Path | None = None, python_exec: str | None = None):
        self.project_root = project_root or Path(__file__).resolve().parent.parent.parent
        self.python_exec = python_exec or sys.executable
        self.module = "app.tunnel_supervisor"

    def is_available(self) -> bool:
        return (self.project_root / "app" / "tunnel_supervisor.py").exists()

    def _run_json(self, args: list[str], timeout: int = 30) -> dict[str, Any]:
        cmd = [self.python_exec, "-m", self.module, "--json", *args]
        try:
            result = subprocess.run(
                cmd,
                cwd=str(self.project_root),
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except FileNotFoundError:
            return {"ok": False, "message": "未找到 Python 解释器"}
        except subprocess.TimeoutExpired:
            return {"ok": False, "message": "守护进程命令超时"}

        output = result.stdout.strip()
        error = result.stderr.strip()
        payload: dict[str, Any] | None = None

        for candidate in (output, output.splitlines()[-1] if output else ""):
            if not candidate:
                continue
            try:
                loaded = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            if isinstance(loaded, dict):
                payload = loaded
                break

        if payload is None:
            payload = {"ok": result.returncode == 0, "message": output or error or ""}

        payload.setdefault("ok", result.returncode == 0)
        payload.setdefault("message", output or error or "")
        payload["returncode"] = result.returncode
        if error:
            payload.setdefault("stderr", error)
        return payload

    def _run(self, args: list[str], timeout: int = 30) -> Tuple[bool, str]:
        payload = self._run_json(args, timeout=timeout)
        ok = bool(payload.get("ok"))
        message = str(payload.get("message") or payload.get("stderr") or "")
        return ok, message

    def _payload_result(self, payload: dict[str, Any]) -> Tuple[bool, str]:
        ok = bool(payload.get("ok"))
        message = str(payload.get("message") or payload.get("stderr") or "")
        return ok, message

    def start_tunnel_payload(self, name: str) -> dict[str, Any]:
        return self._run_json(["start", name])

    def start_tunnel(self, name: str) -> Tuple[bool, str]:
        return self._payload_result(self.start_tunnel_payload(name))

    def stop_tunnel_payload(self, name: str) -> dict[str, Any]:
        return self._run_json(["stop", name])

    def stop_tunnel(self, name: str) -> Tuple[bool, str]:
        return self._payload_result(self.stop_tunnel_payload(name))

    def restart_tunnel_payload(self, name: str) -> dict[str, Any]:
        return self._run_json(["restart", name])

    def restart_tunnel(self, name: str) -> Tuple[bool, str]:
        return self._payload_result(self.restart_tunnel_payload(name))

    def status(self, name: str | None = None) -> Tuple[bool, str]:
        return self._payload_result(self.status_payload(name))

    def status_payload(self, name: str | None = None) -> dict[str, Any]:
        args = ["status"]
        if name:
            args.append(name)
        return self._run_json(args, timeout=90)

    def watch_once(self) -> Tuple[bool, str]:
        return self._run(["status"], timeout=90)
