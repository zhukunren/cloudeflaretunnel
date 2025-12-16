#! -*- coding: utf-8 -*-
"""
与 tunnel_supervisor CLI 交互的辅助模块。
GUI 通过该模块向守护进程发起 start/stop/status 等命令，
从而让无开发经验的用户也能通过图形界面完成日常运维。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Tuple


class SupervisorClient:
    """封装 `python -m app.tunnel_supervisor` 调用"""

    def __init__(self, project_root: Path | None = None, python_exec: str | None = None):
        self.project_root = project_root or Path(__file__).resolve().parent.parent.parent
        self.python_exec = python_exec or sys.executable
        self.module = "app.tunnel_supervisor"

    def is_available(self) -> bool:
        return (self.project_root / "app" / "tunnel_supervisor.py").exists()

    def _run(self, args: list[str], timeout: int = 30) -> Tuple[bool, str]:
        cmd = [self.python_exec, "-m", self.module, *args]
        try:
            result = subprocess.run(
                cmd,
                cwd=str(self.project_root),
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except FileNotFoundError:
            return False, "未找到 Python 解释器"
        except subprocess.TimeoutExpired:
            return False, "守护进程命令超时"
        output = result.stdout.strip()
        error = result.stderr.strip()
        message = output or error or ""
        return result.returncode == 0, message

    def start_tunnel(self, name: str) -> Tuple[bool, str]:
        return self._run(["start", name])

    def stop_tunnel(self, name: str) -> Tuple[bool, str]:
        return self._run(["stop", name])

    def restart_tunnel(self, name: str) -> Tuple[bool, str]:
        return self._run(["restart", name])

    def status(self, name: str | None = None) -> Tuple[bool, str]:
        args = ["status"]
        if name:
            args.append(name)
        return self._run(args)

    def watch_once(self) -> Tuple[bool, str]:
        return self._run(["status"])
