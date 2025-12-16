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
from typing import Dict, Iterable, List, Optional

try:
    from . import cloudflared_cli as cf  # type: ignore
    from .config.settings import Settings  # type: ignore
    from .utils.process_tracker import ProcessTracker, SupervisorLock  # type: ignore
    from .utils.file_lock import FileLock  # type: ignore
except (ImportError, ValueError):
    CURRENT_DIR = Path(__file__).resolve().parent
    if str(CURRENT_DIR) not in sys.path:
        sys.path.append(str(CURRENT_DIR))
    import cloudflared_cli as cf  # type: ignore
    from config.settings import Settings  # type: ignore
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
    def __init__(self, config_path: Path | None = None):
        self.base_dir = Path(__file__).resolve().parent.parent
        self.settings = Settings(self.base_dir / "config" / "app_config.json")
        self.tracker = ProcessTracker(self.base_dir)
        self.lock = SupervisorLock(self.base_dir)
        self.log_file = self.base_dir / "logs" / "tunnel_supervisor.log"
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        self._log_lock = FileLock(self.log_file.parent / ".tunnel_supervisor.log.lock")
        self.config_path = config_path or (self.base_dir / "config" / "tunnels.json")
        self.manager_name = f"tunnel_supervisor@{os.getpid()}"
        self.specs: Dict[str, TunnelSpec] = {}
        self.cloudflared_path: Optional[str] = None
        self.auto_restart_default = True
        self._running = True
        self._load_config()

    # ------------------------------------------------------------------ #
    # 配置与日志
    # ------------------------------------------------------------------ #
    def _log(self, level: str, message: str):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{timestamp}] [{level}] {message}"
        print(line)
        with self._log_lock.locked(timeout=1.0) as locked:
            if not locked:
                print(f"[{timestamp}] [WARNING] 无法获取日志锁，继续无锁写入。")
            with open(self.log_file, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")

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

        self.cloudflared_path = data.get("cloudflared_path") or self._discover_cloudflared()
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

        max_wait = 12
        cfg_protocol = (cf.get_config_protocol(spec.config) or "").lower() or None
        protocol_candidates: list[tuple[str | None, str]] = []
        # 首选配置文件中的协议（或默认）
        protocol_candidates.append((cfg_protocol, cfg_protocol or "默认"))
        # 如果未显式使用 http2，则在失败时自动回退
        if cfg_protocol != "http2":
            protocol_candidates.append(("http2", "http2"))

        def _wait_ready(proc: subprocess.Popen, label: str) -> tuple[bool, str]:
            last_detail = ""
            unknown_seen = False
            unknown_detail = ""
            for i in range(max_wait):
                time.sleep(1)
                if proc.poll() is not None:
                    return False, f"cloudflared 进程异常退出，返回码 {proc.returncode}"
                if i % 2 == 1:
                    ok, detail = self._health_check(name)
                    last_detail = detail
                    if ok is True:
                        self.tracker.register(
                            name,
                            proc.pid,
                            manager="tunnel_supervisor",
                            mode="supervised",
                            metadata={"reason": reason, "log_file": str(log_file), "protocol": label},
                        )
                        self._log("INFO", f"隧道 {name} 启动成功（协议 {label}），PID {proc.pid}")
                        return True, detail
                    if ok is None:
                        unknown_seen = True
                        unknown_detail = detail
                        continue
            if unknown_seen and proc.poll() is None:
                self.tracker.register(
                    name,
                    proc.pid,
                    manager="tunnel_supervisor",
                    mode="supervised",
                    metadata={"reason": reason, "log_file": str(log_file), "protocol": label},
                )
                self._log(
                    "INFO",
                    f"隧道 {name} 健康状态未知（可能 Cloudflare API 不可用），保持运行，PID {proc.pid}",
                )
                return True, unknown_detail or "Cloudflare API 无响应"
            return False, last_detail

        last_detail = ""
        for idx, (proto, label) in enumerate(protocol_candidates):
            try:
                proc = cf.run_tunnel(
                    self.cloudflared_path,
                    name,
                    spec.config,
                    capture_output=False,
                    log_file=log_file,
                    protocol=proto,
                )
            except Exception as exc:
                self._log("ERROR", f"启动隧道 {name} 失败（协议 {label}）: {exc}")
                continue

            ok, detail = _wait_ready(proc, label)
            if ok:
                return True

            last_detail = detail
            # 未连通则停止当前尝试，准备回退
            cf.stop_process(proc)
            if idx + 1 < len(protocol_candidates):
                self._log("WARNING", f"隧道 {name} 使用协议 {label} 未检测到活跃连接，尝试使用 http2 重新启动。")

        self._log(
            "WARNING",
            f"隧道 {name} 启动超时（{max_wait}s 内未检测到活跃连接），稍后将由监控重试。"
            f"{' 详情: ' + last_detail if last_detail else ''}",
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
        # 显式关闭时必须尊重配置，未配置时才退回全局默认
        if spec.auto_start is False:
            return False
        if spec.auto_start is True:
            return True
        return bool(self.auto_restart_default)

    # ------------------------------------------------------------------ #
    # 状态/监控
    # ------------------------------------------------------------------ #
    def list_specs(self):
        for spec in self.specs.values():
            print(
                f"- {spec.name:12} auto_start={spec.auto_start} health_check={spec.health_check} "
                f"config={spec.config}"
            )

    def print_status(self, target: str | None = None):
        names = [target] if target else list(self.specs.keys())
        for name in names:
            spec = self.specs.get(name)
            if not spec:
                print(f"- {name}: 未在配置中定义")
                continue
            record = self.tracker.read(name)
            running = bool(record and record.alive)
            manager = record.manager if record else "-"
            pid = record.pid if record else "-"
            healthy = False
            detail = ""
            if running and manager == "tunnel_supervisor":
                healthy, detail = self._health_check(name)
            elif running:
                healthy = True

            print(
                f"- {name:12} running={running} healthy={healthy} manager={manager} "
                f"pid={pid} auto_start={spec.auto_start}"
            )
            if detail:
                print(f"    {detail.strip()}")

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

                time.sleep(interval)
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
        info = self.lock.info()
        if not info:
            print("未发现运行中的隧道守护进程。")
            return
        print(
            f"锁文件: {info.get('path')}\n"
            f"PID: {info.get('pid')} (alive={info.get('alive')})\n"
            f"Owner: {info.get('owner')} @ {info.get('host')} 创建于 {info.get('created_at')}"
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Cloudflared 多隧道守护进程")
    parser.add_argument("--config", help="指定隧道配置文件 (默认: config/tunnels.json)")

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


def main():
    parser = build_parser()
    args = parser.parse_args()
    config_path = Path(args.config).resolve() if args.config else None
    supervisor = TunnelSupervisor(config_path=config_path)

    if args.command == "start":
        supervisor.start_tunnel(args.name, reason="manual-cli")
    elif args.command == "stop":
        supervisor.stop_tunnel(args.name, reason="manual-cli")
    elif args.command == "restart":
        supervisor.restart_tunnel(args.name, reason="manual-cli")
    elif args.command == "status":
        supervisor.print_status(args.name)
    elif args.command == "list":
        supervisor.list_specs()
    elif args.command == "cleanup":
        supervisor.cleanup_pid_files()
    elif args.command == "lock-status":
        supervisor.lock_status()
    elif args.command == "watch":
        supervisor.watch(interval=args.interval)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
