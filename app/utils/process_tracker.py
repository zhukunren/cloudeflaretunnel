#! -*- coding: utf-8 -*-
"""
跨组件的 cloudflared 进程跟踪工具。
负责记录各隧道对应的 PID、来源管理器以及元数据，
帮助 GUI、守护进程和脚本避免相互冲突。
"""

from __future__ import annotations

import json
import os
import socket
import time
from dataclasses import dataclass
from datetime import datetime
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from .file_lock import FileLock


@dataclass
class ProcessRecord:
    """表示一个正在运行（或记录在案）的隧道进程"""
    name: str
    pid: int
    manager: str
    mode: str
    created_at: str
    host: str
    note: str | None = None
    metadata: dict | None = None
    alive: bool = False
    path: Path | None = None


class ProcessTracker:
    """封装 PID 文件的读写和清理逻辑"""

    def __init__(self, base_dir: Path | None = None):
        self.base_dir = base_dir or Path(__file__).resolve().parent.parent
        self.pid_dir = self.base_dir / "logs" / "pids"
        self.pid_dir.mkdir(parents=True, exist_ok=True)
        self._lock = FileLock(self.pid_dir / ".tracker.lock")

    def _entry_path(self, tunnel_name: str) -> Path:
        safe_name = tunnel_name.replace("/", "_")
        return self.pid_dir / f"{safe_name}.pid.json"

    @contextmanager
    def _locked(self):
        acquired = self._lock.acquire(timeout=2.0)
        try:
            yield acquired
        finally:
            if acquired:
                self._lock.release()

    @staticmethod
    def _write_json_atomic(path: Path, payload: Dict[str, Any]):
        """原子写入，避免并发或崩溃留下损坏文件。"""
        temp = path.with_suffix(path.suffix + ".tmp")
        temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(path)

    def register(
        self,
        tunnel_name: str,
        pid: int,
        manager: str,
        *,
        mode: str = "manual",
        note: str | None = None,
        metadata: Optional[dict] = None,
    ) -> ProcessRecord:
        record = ProcessRecord(
            name=tunnel_name,
            pid=int(pid),
            manager=manager,
            mode=mode,
            created_at=datetime.utcnow().isoformat() + "Z",
            host=socket.gethostname(),
            note=note,
            metadata=metadata or {},
            alive=True,
            path=self._entry_path(tunnel_name),
        )
        payload: Dict[str, Any] = {
            "name": record.name,
            "pid": record.pid,
            "manager": record.manager,
            "mode": record.mode,
            "created_at": record.created_at,
            "host": record.host,
            "note": record.note,
            "metadata": record.metadata,
        }
        record.path.parent.mkdir(parents=True, exist_ok=True)
        with self._locked() as locked:
            if not locked:
                print("ProcessTracker: 获取锁超时，继续无锁写入（风险较高）。")
            self._write_json_atomic(record.path, payload)
        return record

    def read(self, tunnel_name: str) -> ProcessRecord | None:
        path = self._entry_path(tunnel_name)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None

        try:
            pid = int(data.get("pid", 0) or 0)
        except Exception:
            pid = 0
        alive = self._is_pid_running(pid)
        return ProcessRecord(
            name=str(data.get("name") or tunnel_name),
            pid=pid,
            manager=str(data.get("manager") or ""),
            mode=str(data.get("mode") or ""),
            created_at=str(data.get("created_at") or ""),
            host=str(data.get("host") or ""),
            note=data.get("note"),
            metadata=data.get("metadata") if isinstance(data.get("metadata"), dict) else {},
            alive=alive,
            path=path,
        )

    def unregister(self, tunnel_name: str, *, expected_pid: int | None = None):
        path = self._entry_path(tunnel_name)
        if not path.exists():
            return
        with self._locked() as locked:
            if expected_pid is not None:
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    if int(data.get("pid", 0) or 0) != int(expected_pid):
                        return
                except Exception:
                    return
            if not locked:
                print("ProcessTracker: 获取锁超时，最佳努力删除 pid 文件。")
            path.unlink(missing_ok=True)

    def list_records(self) -> Iterable[ProcessRecord]:
        for file in sorted(self.pid_dir.glob("*.pid.json")):
            try:
                name = file.stem.replace(".pid", "")
                record = self.read(name)
                if record:
                    yield record
            except Exception:
                continue

    def cleanup_dead(self):
        """删除对应进程已经消失的 PID 文件"""
        # 清理属于“最佳努力”行为，不应阻塞 GUI 主线程；获取不到锁则跳过即可
        with self._lock.locked(timeout=0.0) as locked:
            if not locked:
                return
            for record in list(self.list_records()):
                if record.pid <= 0 or not record.alive:
                    if record.path:
                        record.path.unlink(missing_ok=True)

    @staticmethod
    def _is_pid_running(pid: int) -> bool:
        if not pid or pid <= 0:
            return False
        if os.name == "nt":
            return ProcessTracker._is_pid_running_windows(pid)
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except Exception:
            return False
        return True

    @staticmethod
    def _is_pid_running_windows(pid: int) -> bool:
        """Windows 下判断 PID 是否仍在运行。

        不能使用 os.kill(pid, 0)：在 Windows / Python 3.12 上可能触发 WinError 87，
        甚至升级为 SystemError（<class 'OSError'> returned a result with an exception set）。
        """
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel32.GetExitCodeProcess.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, wintypes.DWORD(pid))
        if not handle:
            # ERROR_ACCESS_DENIED：进程存在但无权限查询
            if ctypes.get_last_error() == 5:
                return True
            return False

        try:
            exit_code = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return True
            STILL_ACTIVE = 259
            return exit_code.value == STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)

    def terminate_pid(self, pid: int) -> bool:
        """向目标 PID 发送 SIGTERM/SIGKILL（用于守护进程停止隧道）"""
        if not pid or pid <= 0:
            return False
        try:
            if os.name == "nt":
                import subprocess

                subprocess.run(
                    ["taskkill", "/PID", str(pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=0x08000000,
                    check=False,
                )
            else:
                os.kill(pid, 15)
                time.sleep(0.5)
                if self._is_pid_running(pid):
                    os.kill(pid, 9)
            return True
        except Exception:
            return False


class SupervisorLock:
    """用于避免多个守护进程/GUI 同时调度隧道"""

    def __init__(self, base_dir: Path | None = None):
        self.base_dir = base_dir or Path(__file__).resolve().parent.parent
        self.lock_path = self.base_dir / "logs" / "pids" / "tunnel_supervisor.lock"
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = FileLock(self.lock_path.with_suffix(".lockfile"))
        self._held = False

    @staticmethod
    def _write_json_atomic(path: Path, payload: dict):
        """原子写入锁文件，避免并发/崩溃导致损坏。"""
        temp = path.with_suffix(path.suffix + ".tmp")
        temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(path)

    @staticmethod
    def _boot_time_epoch() -> float | None:
        if os.name == "nt":
            try:
                import ctypes

                uptime_ms = ctypes.windll.kernel32.GetTickCount64()  # type: ignore[attr-defined]
                return time.time() - (float(uptime_ms) / 1000.0)
            except Exception:
                return None

        uptime_path = Path("/proc/uptime")
        if not uptime_path.exists():
            return None
        try:
            uptime = float(uptime_path.read_text(encoding="utf-8", errors="ignore").split()[0])
            return time.time() - uptime
        except Exception:
            return None

    @staticmethod
    def _created_at_epoch(value: str) -> float | None:
        raw = (value or "").strip()
        if not raw:
            return None
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            return dt.timestamp()
        except Exception:
            return None

    def info(self) -> dict | None:
        if not self.lock_path.exists():
            return None
        try:
            data = json.loads(self.lock_path.read_text(encoding="utf-8"))
        except Exception:
            return None
        pid = int(data.get("pid", 0) or 0)
        alive = ProcessTracker._is_pid_running(pid)

        boot_time = self._boot_time_epoch()
        created_at = self._created_at_epoch(str(data.get("created_at") or ""))
        if boot_time and created_at and created_at < (boot_time - 1.0):
            alive = False

        data["alive"] = alive
        data["path"] = str(self.lock_path)
        return data

    def acquire(self, owner: str):
        if self._held:
            return
        if not self._lock.acquire(timeout=2.0):
            raise RuntimeError("SupervisorLock: 获取锁超时，无法安全启动守护进程")

        try:
            info = self.info()
            if info and info.get("alive"):
                raise RuntimeError(
                    f"已有守护进程在运行 (PID: {info.get('pid')}, owner: {info.get('owner', '?')})"
                )
            payload = {
                "pid": os.getpid(),
                "owner": owner,
                "created_at": datetime.utcnow().isoformat() + "Z",
                "host": socket.gethostname(),
            }
            self._write_json_atomic(self.lock_path, payload)
            self._held = True
        except Exception:
            try:
                self._lock.release()
            finally:
                self._held = False
            raise

    def release(self):
        try:
            try:
                self.lock_path.unlink(missing_ok=True)
            except Exception:
                pass
        finally:
            if self._held:
                try:
                    self._lock.release()
                finally:
                    self._held = False

    def is_active(self) -> bool:
        info = self.info()
        return bool(info and info.get("alive"))
