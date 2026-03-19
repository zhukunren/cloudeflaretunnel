#!/usr/bin/env python3
"""
多隧道 Cloudflared 守护进程。

功能：
1. 根据 config/tunnels.json 描述批量启动/监控隧道
2. 写入 PID 文件，方便 GUI/脚本检测冲突
3. 通过 cloudflared tunnel info 进行健康检查，异常时自动重启
4. 提供 CLI 命令：start/stop/restart/status/list/watch/cleanup
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

try:
    from . import cloudflared_cli as cf  # type: ignore
    from .config.settings import Settings  # type: ignore
    from .services import TunnelLifecycleService  # type: ignore
    from .utils.process_tracker import ProcessTracker, SupervisorLock  # type: ignore
    from .utils.file_lock import FileLock  # type: ignore
except (ImportError, ValueError):
    CURRENT_DIR = Path(__file__).resolve().parent
    if str(CURRENT_DIR) not in sys.path:
        sys.path.append(str(CURRENT_DIR))
    import cloudflared_cli as cf  # type: ignore
    from config.settings import Settings  # type: ignore
    from services import TunnelLifecycleService  # type: ignore
    from utils.process_tracker import ProcessTracker, SupervisorLock  # type: ignore
    from utils.file_lock import FileLock  # type: ignore


@dataclass
class TunnelSpec:
    name: str
    config: Path
    auto_start: bool = True
    health_check: bool = True
    tags: list[str] = field(default_factory=list)


class TunnelSupervisor:
    def __init__(self, config_path: Path | None = None, echo_logs: bool = True):
        self.base_dir = Path(__file__).resolve().parent.parent
        self.settings = Settings(self.base_dir / "config" / "app_config.json")
        self.tracker = ProcessTracker(self.base_dir)
        self.lock = SupervisorLock(self.base_dir)
        self.log_file = self.base_dir / "logs" / "tunnel_supervisor.log"
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        self._log_lock = FileLock(self.log_file.parent / ".tunnel_supervisor.log.lock")
        self.lifecycle_service = TunnelLifecycleService()
        self.config_path = config_path or (self.base_dir / "config" / "tunnels.json")
        self.manager_name = f"tunnel_supervisor@{os.getpid()}"
        self.echo_logs = echo_logs
        self.specs: Dict[str, TunnelSpec] = {}
        self.cloudflared_path: Optional[str] = None
        self.auto_restart_default = True
        self._running = True
        self._captured_logs: list[str] | None = None
        self._load_config()

    # ------------------------------------------------------------------ #
    # 配置与日志
    # ------------------------------------------------------------------ #
    def _log(self, level: str, message: str):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{timestamp}] [{level}] {message}"
        if self._captured_logs is not None:
            self._captured_logs.append(line)
        if self.echo_logs:
            print(line)
        with self._log_lock.locked(timeout=1.0) as locked:
            if not locked:
                warning = f"[{timestamp}] [WARNING] 无法获取日志锁，继续无锁写入。"
                if self._captured_logs is not None:
                    self._captured_logs.append(warning)
                if self.echo_logs:
                    print(warning)
            with open(self.log_file, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")

    def capture_command(self, action: Callable[[], Any]) -> tuple[Any, list[str]]:
        previous = self._captured_logs
        captured: list[str] = []
        self._captured_logs = captured
        try:
            result = action()
        finally:
            self._captured_logs = previous
        return result, captured

    def _discover_cloudflared(self) -> str | None:
        configured = self.settings.get("cloudflared.path")
        if configured:
            return configured
        return cf.find_cloudflared()

    def _write_default_config(self):
        tunnels_dir = self.base_dir / "tunnels"
        entries: list[dict] = []
        if tunnels_dir.exists():
            for cfg in sorted(tunnels_dir.glob("*/config.yml")):
                name = cfg.parent.name
                relative = cfg.relative_to(self.base_dir)
                entries.append(
                    {
                        "name": name,
                        "config": str(relative),
                        "auto_start": True,
                        "health_check": True,
                    }
                )
        payload = {
            "cloudflared_path": self._discover_cloudflared() or "",
            "auto_restart": True,
            "tunnels": entries,
        }
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _load_config(self):
        if not self.config_path.exists():
            self._log("WARNING", f"未找到 {self.config_path}，正在生成默认配置。")
            self._write_default_config()

        try:
            data = json.loads(self.config_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise RuntimeError(f"无法解析 {self.config_path}: {exc}") from exc

        configured_path = str(data.get("cloudflared_path") or "").strip()
        discovered_path = self._discover_cloudflared()
        cloudflared_path = configured_path or (discovered_path or "")

        # 配置可能来自其他系统（例如 Linux 路径），此处做一次兜底校验，避免启动阶段直接失败。
        if configured_path and cf.version(configured_path) is None:
            self._log(
                "WARNING",
                f"config/tunnels.json 中 cloudflared_path 无效：{configured_path}，将自动使用探测路径",
            )
            cloudflared_path = discovered_path or ""

        self.cloudflared_path = cloudflared_path
        if not self.cloudflared_path:
            raise RuntimeError("无法确定 cloudflared 可执行文件路径，请在 config/tunnels.json 中设置 cloudflared_path")
        self.cloudflared_path = str(self.cloudflared_path)

        self.auto_restart_default = bool(data.get("auto_restart", True))
        specs: Dict[str, TunnelSpec] = {}

        for item in data.get("tunnels", []):
            name = item.get("name")
            if not name:
                continue
            raw_cfg = item.get("config") or f"tunnels/{name}/config.yml"
            cfg_path = Path(raw_cfg)
            if not cfg_path.is_absolute():
                cfg_path = self.base_dir / cfg_path
            specs[name] = TunnelSpec(
                name=name,
                config=cfg_path,
                auto_start=bool(item.get("auto_start", True)),
                health_check=bool(item.get("health_check", True)),
                tags=item.get("tags") or [],
            )

        # 兼容 GUI 创建/管理的隧道：自动扫描 tunnels/<name>/config.yml，
        # 将未出现在 config/tunnels.json 的隧道纳入守护范围，默认 auto_start=True。
        tunnels_dir = self.base_dir / "tunnels"
        if tunnels_dir.exists():
            for cfg in sorted(tunnels_dir.glob("*/config.yml")):
                name = cfg.parent.name
                if not name:
                    continue
                if name in specs:
                    continue
                specs[name] = TunnelSpec(
                    name=name,
                    config=cfg,
                    auto_start=True,
                    health_check=True,
                    tags=["discovered"],
                )

        for spec in specs.values():
            if not spec.config.exists():
                self._log("WARNING", f"隧道 {spec.name} 配置文件不存在，将跳过自动启动：{spec.config}")

        if not specs:
            self._log("WARNING", "配置中未包含任何隧道，守护进程将空闲等待。")
        self.specs = specs

    # ------------------------------------------------------------------ #
    # 核心操作
    # ------------------------------------------------------------------ #
    def start_tunnel(self, name: str, reason: str = "manual") -> bool:
        spec = self.specs.get(name)
        if not spec:
            self._log("ERROR", f"未知隧道: {name}")
            return False

        if not spec.config.exists():
            self._log("ERROR", f"配置文件不存在: {spec.config}")
            return False

        record = self.tracker.read(name)
        if record and record.alive:
            if record.manager != "tunnel_supervisor":
                self._log("ERROR", f"隧道 {name} 当前由 {record.manager} 管理 (PID {record.pid})，无法接管。")
                return False
            self._log("INFO", f"隧道 {name} 已在运行 (PID {record.pid})")
            return True

        self._log("INFO", f"正在启动隧道 {name} ({reason})...")
        log_dir = self.base_dir / "logs" / "persistent"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / f"{name}.log"
        result = self.lifecycle_service.launch_tunnel(
            self.cloudflared_path,
            name,
            spec.config,
            capture_output=False,
            log_file=log_file,
            health_timeout=8,
            max_wait_seconds=12,
        )
        if result.get("ok"):
            proc = result.get("proc")
            protocol = result.get("protocol", "默认")
            detail = result.get("detail", "")
            if not proc:
                self._log("ERROR", f"隧道 {name} 启动结果缺少进程句柄")
                return False

            self.tracker.register(
                name,
                proc.pid,
                manager="tunnel_supervisor",
                mode="supervised",
                metadata={"reason": reason, "log_file": str(log_file), "protocol": protocol},
            )
            self._log("INFO", f"隧道 {name} 启动成功（协议 {protocol}），PID {proc.pid}")
            if detail and "Cloudflare API 无响应" in detail:
                self._log("INFO", f"隧道 {name} 健康状态未知，保持运行：{detail}")
            return True

        error = result.get("error") or "未检测到活跃连接"
        if result.get("error_type") == "credentials":
            self._log("ERROR", f"启动隧道 {name} 失败: {error}")
            if spec.auto_start and "auto" in reason:
                spec.auto_start = False
                self._log(
                    "WARNING",
                    f"已自动关闭隧道 {name} 的 auto_start（无法获取凭据/token）。"
                    "请确认隧道已创建且当前账号已登录 cloudflared。",
                )
            return False

        self._log(
            "WARNING",
            f"隧道 {name} 启动超时（12s 内未检测到活跃连接），稍后将由监控重试。"
            f"{' 详情: ' + error if error else ''}",
        )
        return False

    def stop_tunnel(self, name: str, reason: str = "manual") -> bool:
        record = self.tracker.read(name)
        if record and record.alive:
            self._log("INFO", f"正在停止隧道 {name} ({reason})...")
            if self.tracker.terminate_pid(record.pid):
                self.tracker.unregister(name, expected_pid=record.pid)
                self._log("INFO", f"隧道 {name} 已停止")
                return True
            self._log("WARNING", f"无法通过 PID {record.pid} 停止隧道 {name}，尝试使用 cloudflared 命令。")

        ok, msg = cf.kill_tunnel_by_name(name)
        if ok:
            self.tracker.unregister(name)
            self._log("INFO", msg)
            return True
        else:
            self._log("ERROR", msg)
            return False

    def restart_tunnel(self, name: str, reason: str = "health-check") -> bool:
        if not self.stop_tunnel(name, reason=f"{reason}-stop"):
            return False
        time.sleep(2)
        return self.start_tunnel(name, reason=f"{reason}-start")

    def _health_check(self, name: str) -> tuple[bool, str]:
        try:
            ok, msg = cf.test_connection(self.cloudflared_path, name, timeout=8)
            return ok, msg
        except Exception as exc:
            return None, f"health-check 执行失败（未知状态）：{exc}"

    def _should_auto_start(self, spec: TunnelSpec) -> bool:
        if not spec.config.exists():
            return False
        # 显式关闭时必须尊重配置，未配置时才退回全局默认
        if spec.auto_start is False:
            return False
        if spec.auto_start is True:
            return True
        return bool(self.auto_restart_default)

    @staticmethod
    def _status_summary(detail: str) -> str:
        if not detail:
            return ""
        for line in detail.splitlines():
            text = line.strip()
            if text:
                if len(text) > 160:
                    return text[:157] + "..."
                return text
        return ""

    @staticmethod
    def _status_state(configured: bool, running: bool, healthy: bool | None) -> str:
        if not configured:
            return "未配置"
        if not running:
            return "未运行"
        if healthy is True:
            return "健康"
        if healthy is None:
            return "状态未知"
        return "异常"

    def _status_entry(self, name: str) -> dict:
        spec = self.specs.get(name)
        if not spec:
            return {
                "name": name,
                "configured": False,
                "running": False,
                "healthy": False,
                "state": self._status_state(False, False, False),
                "manager": None,
                "pid": None,
                "auto_start": None,
                "summary": "",
                "detail": "",
                "config": None,
            }

        record = self.tracker.read(name)
        running = bool(record and record.alive)
        manager = record.manager if record else None
        pid = record.pid if record else None
        healthy: bool | None = False
        detail = ""
        if running and manager == "tunnel_supervisor":
            healthy, detail = self._health_check(name)
        elif running:
            healthy = True

        return {
            "name": name,
            "configured": True,
            "running": running,
            "healthy": healthy,
            "state": self._status_state(True, running, healthy),
            "manager": manager,
            "pid": pid,
            "auto_start": spec.auto_start,
            "summary": self._status_summary(detail),
            "detail": detail.strip(),
            "config": str(spec.config),
            "health_check": spec.health_check,
            "tags": list(spec.tags),
        }

    def status_entries(self, target: str | None = None) -> list[dict]:
        names = [target] if target else list(self.specs.keys())
        return [self._status_entry(name) for name in names]

    def render_status_entries(self, entries: list[dict]) -> str:
        lines: list[str] = []
        for entry in entries:
            if not entry.get("configured"):
                lines.append(f"- {entry['name']}: 未在配置中定义")
                continue

            manager = entry.get("manager") or "-"
            pid = entry.get("pid") if entry.get("pid") is not None else "-"
            lines.append(
                f"- {entry['name']:12} state={entry.get('state')} "
                f"running={entry['running']} healthy={entry['healthy']} "
                f"manager={manager} pid={pid} auto_start={entry['auto_start']}"
            )
            summary = entry.get("summary")
            if summary:
                lines.append(f"    {summary}")
        return "\n".join(lines)

    def render_status(self, target: str | None = None) -> str:
        return self.render_status_entries(self.status_entries(target))

    def specs_data(self) -> list[dict]:
        return [
            {
                "name": spec.name,
                "config": str(spec.config),
                "auto_start": spec.auto_start,
                "health_check": spec.health_check,
                "tags": list(spec.tags),
            }
            for spec in self.specs.values()
        ]

    def render_specs(self) -> str:
        lines = [
            f"- {item['name']:12} auto_start={item['auto_start']} health_check={item['health_check']} "
            f"config={item['config']}"
            for item in self.specs_data()
        ]
        return "\n".join(lines)

    def lock_status_data(self) -> dict | None:
        info = self.lock.info()
        if not info:
            return None
        return dict(info)

    def render_lock_status(self) -> str:
        info = self.lock_status_data()
        if not info:
            return "未发现运行中的隧道守护进程。"
        return (
            f"锁文件: {info.get('path')}\n"
            f"PID: {info.get('pid')} (alive={info.get('alive')})\n"
            f"Owner: {info.get('owner')} @ {info.get('host')} 创建于 {info.get('created_at')}"
        )

    # ------------------------------------------------------------------ #
    # 状态/监控
    # ------------------------------------------------------------------ #
    def list_specs(self):
        text = self.render_specs()
        if text:
            print(text)

    def print_status(self, target: str | None = None):
        text = self.render_status(target)
        if text:
            print(text)

    def watch(self, interval: int = 30):
        if self.lock.is_active():
            info = self.lock.info()
            raise RuntimeError(
                f"已有守护进程正在运行 (PID {info.get('pid')}, owner {info.get('owner')})"
            )
        self.lock.acquire(self.manager_name)
        self._log("INFO", f"守护进程启动，间隔 {interval}s，监控 {len(self.specs)} 个隧道。")

        def _handle_signal(signum, _frame):
            self._log("INFO", f"接收到信号 {signum}，准备退出。")
            self._running = False

        signal.signal(signal.SIGINT, _handle_signal)
        signal.signal(signal.SIGTERM, _handle_signal)

        try:
            while self._running:
                sleep_seconds = interval
                try:
                    self.tracker.cleanup_dead()
                    for spec in self.specs.values():
                        record = self.tracker.read(spec.name)
                        if record and record.alive and record.manager != "tunnel_supervisor":
                            self._log(
                                "WARNING",
                                f"检测到隧道 {spec.name} 由 {record.manager} 管理 (PID {record.pid})，跳过自动控制。",
                            )
                            continue

                        if record and record.alive:
                            if spec.health_check:
                                ok, detail = self._health_check(spec.name)
                                if ok is False:
                                    self._log("WARNING", f"{spec.name} 健康检查失败：{detail}")
                                    self.restart_tunnel(spec.name, reason="health-check")
                                elif ok is None:
                                    self._log("INFO", f"{spec.name} 健康状态未知（跳过自动重启）：{detail}")
                            continue

                        if self._should_auto_start(spec):
                            self.start_tunnel(spec.name, reason="auto-start")
                except Exception:
                    import traceback

                    self._log("ERROR", f"监控循环异常:\n{traceback.format_exc()}")
                    sleep_seconds = min(interval, 5)

                time.sleep(sleep_seconds)
        finally:
            self.lock.release()
            self._log("INFO", "守护进程已退出并释放锁。")

    # ------------------------------------------------------------------ #
    # 维护操作
    # ------------------------------------------------------------------ #
    def cleanup_pid_files(self):
        self.tracker.cleanup_dead()
        self._log("INFO", "已清理失效的 PID 文件。")

    def lock_status(self):
        print(self.render_lock_status())


def _command_message(logs: list[str], default: str) -> str:
    if not logs:
        return default
    last = logs[-1].strip()
    parts = last.split("] ", 2)
    if len(parts) == 3:
        return parts[2].strip()
    return last


def _emit_json(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Cloudflared 多隧道守护进程")
    parser.add_argument("--config", help="指定隧道配置文件 (默认: config/tunnels.json)")
    parser.add_argument("--json", action="store_true", dest="json_output", help="以 JSON 输出结果")

    sub = parser.add_subparsers(dest="command")

    start_cmd = sub.add_parser("start", help="启动指定隧道")
    start_cmd.add_argument("name", help="隧道名称")

    stop_cmd = sub.add_parser("stop", help="停止指定隧道")
    stop_cmd.add_argument("name", help="隧道名称")

    restart_cmd = sub.add_parser("restart", help="重启指定隧道")
    restart_cmd.add_argument("name", help="隧道名称")

    status_cmd = sub.add_parser("status", help="查看隧道运行状态")
    status_cmd.add_argument("name", nargs="?", help="可选的隧道名称")

    sub.add_parser("list", help="列出所有配置的隧道")
    sub.add_parser("cleanup", help="清理失效 PID 文件")
    sub.add_parser("lock-status", help="查看守护进程锁文件状态")

    watch_cmd = sub.add_parser("watch", help="以守护模式运行")
    watch_cmd.add_argument("--interval", type=int, default=30, help="健康检查间隔 (秒)")

    return parser


def main() -> int:
    parser = build_parser()
    try:
        args = parser.parse_args()
        config_path = Path(args.config).resolve() if args.config else None
        supervisor = TunnelSupervisor(config_path=config_path, echo_logs=not args.json_output)

        if args.command == "start":
            ok, logs = supervisor.capture_command(lambda: supervisor.start_tunnel(args.name, reason="manual-cli"))
            if args.json_output:
                _emit_json(
                    {
                        "ok": bool(ok),
                        "command": "start",
                        "name": args.name,
                        "logs": logs,
                        "message": _command_message(logs, f"隧道 {args.name} {'启动成功' if ok else '启动失败'}"),
                    }
                )
            return 0 if ok else 1
        if args.command == "stop":
            ok, logs = supervisor.capture_command(lambda: supervisor.stop_tunnel(args.name, reason="manual-cli"))
            if args.json_output:
                _emit_json(
                    {
                        "ok": bool(ok),
                        "command": "stop",
                        "name": args.name,
                        "logs": logs,
                        "message": _command_message(logs, f"隧道 {args.name} {'已停止' if ok else '停止失败'}"),
                    }
                )
            return 0 if ok else 1
        if args.command == "restart":
            ok, logs = supervisor.capture_command(lambda: supervisor.restart_tunnel(args.name, reason="manual-cli"))
            if args.json_output:
                _emit_json(
                    {
                        "ok": bool(ok),
                        "command": "restart",
                        "name": args.name,
                        "logs": logs,
                        "message": _command_message(logs, f"隧道 {args.name} {'重启成功' if ok else '重启失败'}"),
                    }
                )
            return 0 if ok else 1
        if args.command == "status":
            if args.json_output:
                entries = supervisor.status_entries(args.name)
                configured = not args.name or bool(entries and entries[0].get("configured"))
                _emit_json(
                    {
                        "ok": configured,
                        "command": "status",
                        "name": args.name,
                        "entries": entries,
                        "message": supervisor.render_status_entries(entries),
                    }
                )
                return 0 if configured else 1
            supervisor.print_status(args.name)
            return 0
        if args.command == "list":
            if args.json_output:
                _emit_json(
                    {
                        "ok": True,
                        "command": "list",
                        "tunnels": supervisor.specs_data(),
                        "message": supervisor.render_specs(),
                    }
                )
                return 0
            supervisor.list_specs()
            return 0
        if args.command == "cleanup":
            if args.json_output:
                _, logs = supervisor.capture_command(supervisor.cleanup_pid_files)
                _emit_json(
                    {
                        "ok": True,
                        "command": "cleanup",
                        "logs": logs,
                        "message": _command_message(logs, "已清理失效的 PID 文件。"),
                    }
                )
                return 0
            supervisor.cleanup_pid_files()
            return 0
        if args.command == "lock-status":
            if args.json_output:
                info = supervisor.lock_status_data()
                _emit_json(
                    {
                        "ok": True,
                        "command": "lock-status",
                        "active": bool(info),
                        "lock": info,
                        "message": supervisor.render_lock_status(),
                    }
                )
                return 0
            supervisor.lock_status()
            return 0
        if args.command == "watch":
            if args.json_output:
                _emit_json(
                    {
                        "ok": False,
                        "command": "watch",
                        "message": "watch 模式不支持 JSON 流式输出。",
                    }
                )
                return 1
            supervisor.watch(interval=args.interval)
            return 0

        parser.print_help()
        return 1
    except Exception as exc:
        if "args" in locals() and getattr(args, "json_output", False):
            _emit_json({"ok": False, "command": getattr(args, "command", None), "message": str(exc)})
        else:
            print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
