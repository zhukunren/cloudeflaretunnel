"""
进程清理工具

在应用启动时清理重复的监控脚本进程和僵尸进程，
确保只有systemd服务管理隧道，避免进程冲突。
"""

import os
import subprocess
import signal
import time
import sys
from pathlib import Path
from datetime import datetime
from typing import Optional


class ProcessCleaner:
    """进程清理器 - 清理重复的监控脚本和僵尸进程"""

    def __init__(self, log_file: Path = None):
        """初始化清理器

        Args:
            log_file: 日志文件路径，默认为项目logs目录
        """
        self.project_root = Path(__file__).parent.parent.parent
        self.log_file = log_file or self.project_root / "logs" / "process_cleanup.log"
        self.cleanup_log_file()

    def cleanup_log_file(self):
        """确保日志目录存在"""
        self.log_file.parent.mkdir(parents=True, exist_ok=True)

    def _log(self, level: str, message: str):
        """记录清理日志"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        log_msg = f"[{timestamp}] [{level}] {message}"
        print(log_msg)

        try:
            with open(self.log_file, 'a', encoding='utf-8') as f:
                f.write(log_msg + '\n')
        except Exception as e:
            print(f"Warning: 无法写入日志文件: {e}")

    def _get_process_info(self, pid: int) -> dict:
        """获取进程信息"""
        try:
            result = subprocess.run(
                ['ps', '-p', str(pid), '-o', 'pid=,user=,cmd='],
                capture_output=True,
                text=True,
                timeout=2
            )
            if result.returncode == 0 and result.stdout.strip():
                parts = result.stdout.strip().split(None, 2)
                return {
                    'pid': int(parts[0]) if parts else None,
                    'user': parts[1] if len(parts) > 1 else 'unknown',
                    'cmd': parts[2] if len(parts) > 2 else 'unknown'
                }
        except Exception:
            pass
        return None

    def _is_tunnel_monitor_process(self, cmd: str) -> bool:
        """判断是否为隧道监控脚本进程"""
        keywords = [
            'tunnel_monitor',
            'tunnel_supervisor',
        ]
        return any(keyword in cmd for keyword in keywords)

    def _systemd_unit_from_pid(self, pid: int) -> Optional[str]:
        """从 /proc/<pid>/cgroup 推断 systemd unit（仅识别 *.service）。"""
        try:
            cgroup_path = Path(f"/proc/{pid}/cgroup")
            if not cgroup_path.exists():
                return None
            content = cgroup_path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return None

        for line in content.splitlines():
            if ".service" not in line:
                continue
            parts = line.split(":", 2)
            cgroup = parts[-1] if parts else ""
            if ".service" not in cgroup:
                continue
            unit = cgroup.split("/")[-1]
            if unit.endswith(".service"):
                return unit
        return None

    def _is_systemd_managed(self, pid: int) -> bool:
        """检查进程是否由 systemd 服务单元管理（避免误杀 systemd 运行的监控/守护进程）。"""
        return self._systemd_unit_from_pid(pid) is not None

    def _kill_process(self, pid: int, force: bool = False) -> bool:
        """安全地杀死进程

        Args:
            pid: 进程ID
            force: 是否使用SIGKILL强制杀死

        Returns:
            成功返回True，失败返回False
        """
        try:
            if os.name == "nt":
                flags = ["/F"] if force else []
                subprocess.run(
                    ["taskkill", "/PID", str(pid), "/T", *flags],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=0x08000000,
                    check=False,
                )
                signal_name = "taskkill /F" if force else "taskkill"
                self._log("INFO", f"已发送 {signal_name} 给进程 {pid}")
                return True
            signal_type = signal.SIGKILL if force else signal.SIGTERM
            os.kill(pid, signal_type)
            signal_name = "SIGKILL" if force else "SIGTERM"
            self._log("INFO", f"已发送 {signal_name} 信号给进程 {pid}")
            return True
        except ProcessLookupError:
            self._log("DEBUG", f"进程 {pid} 已不存在")
            return True  # 进程已不存在也算成功
        except PermissionError:
            self._log("WARNING", f"权限不足，无法杀死进程 {pid}")
            return False
        except Exception as e:
            self._log("ERROR", f"杀死进程 {pid} 失败: {e}")
            return False

    def clean_duplicate_monitors(self) -> int:
        """清理重复的监控脚本进程

        Returns:
            清理的进程数
        """
        self._log("INFO", "开始清理重复的监控脚本进程...")

        try:
            # 获取所有运行中的进程
            result = subprocess.run(
                ['ps', 'aux'],
                capture_output=True,
                text=True,
                timeout=5
            )

            monitor_processes = []
            systemd_pids = set()

            for line in result.stdout.split('\n'):
                if not line.strip():
                    continue

                parts = line.split(None, 10)
                if len(parts) < 2:
                    continue

                try:
                    pid = int(parts[1])
                    cmd = parts[10] if len(parts) > 10 else ''
                except (ValueError, IndexError):
                    continue

                # 识别监控脚本进程
                if self._is_tunnel_monitor_process(cmd):
                    monitor_processes.append((pid, cmd))
                    if self._is_systemd_managed(pid):
                        systemd_pids.add(pid)

            monitor_pids = [pid for pid, _ in monitor_processes]
            if not monitor_pids:
                self._log("INFO", "没有发现监控脚本进程")
                return 0

            keep_pids = set()
            if systemd_pids:
                keep_pids = set(systemd_pids)
            elif len(monitor_pids) <= 1:
                self._log("INFO", "只发现 1 个监控脚本进程且非 systemd 管理，跳过清理")
                return 0
            else:
                keep_pid = min(monitor_pids)
                keep_pids = {keep_pid}
                self._log("WARNING", f"未检测到 systemd 管理的监控进程，将保留 PID {keep_pid} 并清理其他进程")

            # 清理重复的监控脚本（保留 systemd 管理的进程/或保留一个）
            killed_count = 0
            for pid in monitor_pids:
                if pid in keep_pids or pid == os.getpid():
                    if pid in keep_pids:
                        unit = self._systemd_unit_from_pid(pid)
                        msg = f"保留 systemd 管理的进程 {pid}" if unit else f"保留进程 {pid}"
                        if unit:
                            msg += f" ({unit})"
                        self._log("DEBUG", msg)
                    continue

                info = self._get_process_info(pid)
                if info:
                    self._log("WARNING", f"发现重复的监控脚本: PID {pid} - {info['cmd']}")
                    if self._kill_process(pid, force=False):
                        killed_count += 1
                        # 等待一下，让进程优雅关闭
                        time.sleep(0.5)
                        # 如果进程还在，强制杀死
                        if self._get_process_info(pid):
                            self._kill_process(pid, force=True)
                            killed_count += 1

            if killed_count > 0:
                self._log("INFO", f"已清理 {killed_count} 个重复的监控脚本进程")
            else:
                self._log("INFO", "没有发现重复的监控脚本进程")

            return killed_count

        except Exception as e:
            self._log("ERROR", f"清理监控脚本失败: {e}")
            return 0

    def clean_zombie_processes(self) -> int:
        """清理僵尸进程

        Returns:
            清理的进程数
        """
        self._log("INFO", "开始清理僵尸进程...")

        try:
            result = subprocess.run(
                ['ps', 'aux'],
                capture_output=True,
                text=True,
                timeout=5
            )

            zombie_count = 0
            for line in result.stdout.split('\n'):
                if '<defunct>' not in line:
                    continue

                parts = line.split(None, 10)
                if len(parts) < 2:
                    continue

                try:
                    pid = int(parts[1])
                    cmd = parts[10] if len(parts) > 10 else '<defunct>'
                    self._log("WARNING", f"发现僵尸进程: PID {pid} - {cmd}")
                    zombie_count += 1
                except (ValueError, IndexError):
                    continue

            if zombie_count > 0:
                self._log("INFO", f"发现 {zombie_count} 个僵尸进程（无需主动清理，父进程回收时自动清理）")
            else:
                self._log("INFO", "没有发现僵尸进程")

            return zombie_count

        except Exception as e:
            self._log("ERROR", f"检查僵尸进程失败: {e}")
            return 0

    def verify_systemd_service(self) -> bool:
        """验证systemd服务状态

        Returns:
            服务运行中返回True，否则False
        """
        if os.name == "nt":
            self._log("INFO", "Windows 环境，跳过 systemd 服务检查。")
            return True

        self._log("INFO", "检查 systemd 服务状态...")

        candidates = [
            (["systemctl", "is-active", "--quiet", "tunnel-monitor-improved.service"], "tunnel-monitor-improved.service"),
            (["systemctl", "is-active", "--quiet", "tunnel-supervisor.service"], "tunnel-supervisor.service"),
            (["systemctl", "--user", "is-active", "--quiet", "cloudflared-homepage.service"], "cloudflared-homepage.service"),
        ]

        for cmd, unit in candidates:
            try:
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=2)
                if result.returncode == 0:
                    self._log("INFO", f"✓ systemd 服务运行中: {unit}")
                    return True
            except Exception:
                continue

        self._log("WARNING", "⚠ 未检测到运行中的 systemd 隧道服务（建议启用 tunnel-monitor-improved.service 或 tunnel-supervisor.service）")
        return False

    def cleanup_all(self) -> dict:
        """执行全部清理操作

        Returns:
            清理结果字典
        """
        if os.name == "nt":
            self._log("INFO", "Windows 环境，跳过进程清理流程（systemd/ps 不适用）。")
            return {
                'duplicate_monitors_killed': 0,
                'zombies_found': 0,
                'systemd_service_ok': True,
            }

        self._log("INFO", "=" * 60)
        self._log("INFO", "开始执行进程清理流程")
        self._log("INFO", "=" * 60)

        results = {
            'duplicate_monitors_killed': self.clean_duplicate_monitors(),
            'zombies_found': self.clean_zombie_processes(),
            'systemd_service_ok': self.verify_systemd_service()
        }

        self._log("INFO", "=" * 60)
        self._log("INFO", "进程清理流程完成")
        self._log("INFO", f"- 清理重复监控脚本: {results['duplicate_monitors_killed']} 个")
        self._log("INFO", f"- 发现僵尸进程: {results['zombies_found']} 个")
        self._log("INFO", f"- systemd 服务状态: {'正常' if results['systemd_service_ok'] else '异常'}")
        self._log("INFO", "=" * 60)

        return results


def cleanup_on_startup():
    """在应用启动时执行清理"""
    if os.name == "nt":
        try:
            try:
                from .process_tracker import ProcessTracker  # type: ignore
            except Exception:
                from process_tracker import ProcessTracker  # type: ignore

            base_dir = Path(__file__).resolve().parent.parent.parent
            ProcessTracker(base_dir).cleanup_dead()
        except Exception:
            pass
        return

    try:
        cleaner = ProcessCleaner()
        cleaner.cleanup_all()
        time.sleep(1)  # 给清理流程充分时间完成
    except Exception as e:
        print(f"Error during process cleanup: {e}", file=sys.stderr)
        # 不中断应用启动，即使清理失败


if __name__ == "__main__":
    cleanup_on_startup()
