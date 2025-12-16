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

    def _is_systemd_managed(self, pid: int) -> bool:
        """检查进程是否由systemd管理"""
        try:
            result = subprocess.run(
                ['systemctl', '--user', 'status', 'cloudflared-homepage.service'],
                capture_output=True,
                text=True,
                timeout=2
            )
            # 如果服务运行中且PID匹配，则说明由systemd管理
            if result.returncode == 0 and 'Main PID' in result.stdout:
                for line in result.stdout.split('\n'):
                    if 'Main PID' in line:
                        try:
                            systemd_pid = int(line.split()[-1])
                            return pid == systemd_pid
                        except (ValueError, IndexError):
                            pass
        except Exception:
            pass
        return False

    def _kill_process(self, pid: int, force: bool = False) -> bool:
        """安全地杀死进程

        Args:
            pid: 进程ID
            force: 是否使用SIGKILL强制杀死

        Returns:
            成功返回True，失败返回False
        """
        try:
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

            monitor_pids = []
            systemd_pid = None

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
                    monitor_pids.append(pid)

                # 识别systemd管理的进程
                if 'tunnel_monitor_improved.py' in cmd and self._is_systemd_managed(pid):
                    systemd_pid = pid

            # 清理重复的监控脚本（保留systemd管理的那个）
            killed_count = 0
            for pid in monitor_pids:
                if pid == systemd_pid:
                    self._log("DEBUG", f"保留 systemd 管理的进程 {pid}")
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
        self._log("INFO", "检查 systemd 服务状态...")

        try:
            result = subprocess.run(
                ['systemctl', '--user', 'status', 'cloudflared-homepage.service'],
                capture_output=True,
                text=True,
                timeout=2
            )

            if result.returncode == 0:
                self._log("INFO", "✓ systemd 隧道服务正常运行")
                return True
            else:
                self._log("WARNING", "⚠ systemd 隧道服务未运行，尝试启动...")
                # 尝试启动服务
                start_result = subprocess.run(
                    ['systemctl', '--user', 'start', 'cloudflared-homepage.service'],
                    capture_output=True,
                    timeout=5
                )
                if start_result.returncode == 0:
                    time.sleep(2)  # 等待服务启动
                    self._log("INFO", "✓ systemd 隧道服务已启动")
                    return True
                else:
                    self._log("ERROR", "✗ 启动 systemd 隧道服务失败")
                    return False
        except Exception as e:
            self._log("ERROR", f"检查 systemd 服务失败: {e}")
            return False

    def cleanup_all(self) -> dict:
        """执行全部清理操作

        Returns:
            清理结果字典
        """
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
    try:
        cleaner = ProcessCleaner()
        cleaner.cleanup_all()
        time.sleep(1)  # 给清理流程充分时间完成
    except Exception as e:
        print(f"Error during process cleanup: {e}", file=sys.stderr)
        # 不中断应用启动，即使清理失败


if __name__ == "__main__":
    cleanup_on_startup()
