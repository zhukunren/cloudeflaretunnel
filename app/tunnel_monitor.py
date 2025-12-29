#!/usr/bin/env python3
"""
Cloudflared 隧道监控和自动重连脚本
自动检测隧道状态并在断开时重新连接
"""

import subprocess
import time
import signal
import sys
import os
import json
from datetime import datetime
from pathlib import Path

try:
    from . import cloudflared_cli as cf  # type: ignore
except Exception:
    try:
        import cloudflared_cli as cf  # type: ignore
    except Exception:
        cf = None  # type: ignore

# 配置参数
TUNNEL_NAME = "homepage"  # 默认隧道名称
CHECK_INTERVAL = 60  # 检查间隔（秒）
RESTART_DELAY = 5  # 重启延迟（秒）
MAX_RESTART_ATTEMPTS = 3  # 最大重启尝试次数
LOG_FILE = Path(__file__).parent.parent / "logs" / "tunnel_monitor.log"
PROJECT_ROOT = Path(__file__).parent.parent

# 确保日志目录存在
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
LOCK_FILE = Path(__file__).parent.parent / "logs" / "pids" / "tunnel_supervisor.lock"

# 全局变量
running = True
cloudflared_process = None


def get_cloudflared_path() -> str:
    """获取 cloudflared 可执行文件路径"""
    # 首先尝试从配置文件读取
    config_file = PROJECT_ROOT / "config" / "tunnels.json"
    if config_file.exists():
        try:
            data = json.loads(config_file.read_text(encoding="utf-8"))
            path = data.get("cloudflared_path")
            if path and Path(path).exists():
                return path
        except Exception:
            pass

    # 然后尝试项目根目录
    candidates = [PROJECT_ROOT / "cloudflared"]
    if os.name == "nt":
        candidates.insert(0, PROJECT_ROOT / "cloudflared.exe")
    for local_path in candidates:
        if local_path.exists():
            return str(local_path)

    # 最后使用系统 PATH 中的 cloudflared
    return "cloudflared"



def _is_pid_running(pid: int) -> bool:
    if not pid or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def supervisor_active() -> bool:
    if not LOCK_FILE.exists():
        return False
    try:
        data = json.loads(LOCK_FILE.read_text(encoding="utf-8"))
    except Exception:
        return False
    pid = int(data.get("pid", 0) or 0)
    if _is_pid_running(pid):
        owner = data.get("owner", "tunnel_supervisor")
        log("ERROR", f"检测到隧道守护进程 {owner} (PID {pid}) 正在运行，本监控脚本将退出以避免冲突。")
        return True
    return False

def log(level: str, message: str):
    """写入日志"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_message = f"[{timestamp}] [{level}] {message}"
    print(log_message)

    # 写入文件
    with open(LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(log_message + '\n')

def signal_handler(signum, frame):
    """处理退出信号"""
    global running
    log("INFO", f"接收到信号 {signum}，准备优雅退出...")
    running = False
    stop_tunnel()
    sys.exit(0)

def get_tunnel_config_path(tunnel_name: str) -> Path:
    """获取隧道配置文件路径"""
    base_path = Path(__file__).parent.parent
    config_path = base_path / "tunnels" / tunnel_name / "config.yml"
    return config_path

def check_tunnel_status(tunnel_name: str) -> bool:
    """检查隧道连接状态，使用 JSON 输出精确统计连接数"""
    cloudflared = get_cloudflared_path()
    try:
        # 使用 cloudflared tunnel info --output json 检查状态
        result = subprocess.run(
            [cloudflared, "tunnel", "info", "--output", "json", tunnel_name],
            capture_output=True,
            text=True,
            timeout=15
        )

        if result.returncode == 0:
            try:
                data = json.loads(result.stdout)
                # 统计活跃连接数
                total_conns = 0
                if isinstance(data, dict):
                    for connector in data.get("conns", []):
                        if isinstance(connector, dict):
                            inner_conns = connector.get("conns", [])
                            total_conns += len(inner_conns)

                if total_conns > 0:
                    log("DEBUG", f"隧道 {tunnel_name} 有 {total_conns} 条活跃连接")
                    return True
                else:
                    log("WARNING", f"隧道 {tunnel_name} 没有活跃连接")
                    return False
            except json.JSONDecodeError:
                # JSON 解析失败，回退到文本解析
                output = result.stdout
                if "CONNECTOR ID" in output and "EDGE" in output:
                    log("DEBUG", f"隧道 {tunnel_name} 检测到连接器（文本模式）")
                    return True
                else:
                    log("WARNING", f"隧道 {tunnel_name} 没有活跃的连接器")
                    return False
        else:
            log("ERROR", f"无法获取隧道 {tunnel_name} 信息: {result.stderr}")
            return False

    except subprocess.TimeoutExpired:
        log("ERROR", "检查隧道状态超时")
        return False
    except Exception as e:
        log("ERROR", f"检查隧道状态失败: {e}")
        return False

def check_tunnel_connectivity(tunnel_name: str) -> bool:
    """检查隧道连通性（检查进程是否存在）"""
    if cf:
        try:
            return any(t.get("name") == tunnel_name for t in cf.get_running_tunnels())
        except Exception:
            pass
    try:
        result = subprocess.run(
            ["pgrep", "-f", f"tunnel.*run.*{tunnel_name}"],
            capture_output=True,
            timeout=5
        )

        if result.returncode == 0:
            pids = result.stdout.decode().strip().split('\n')
            if pids and pids[0]:
                log("DEBUG", f"找到隧道进程 PID: {pids}")
                return True

        return False

    except Exception as e:
        log("ERROR", f"检查隧道连通性失败: {e}")
        return False

def start_tunnel(tunnel_name: str) -> subprocess.Popen:
    """启动隧道"""
    global cloudflared_process

    config_path = get_tunnel_config_path(tunnel_name)

    if not config_path.exists():
        log("ERROR", f"配置文件不存在: {config_path}")
        return None

    try:
        # 设置环境变量以增加 UDP 缓冲区大小
        env = os.environ.copy()

        # 启动 cloudflared 进程
        log("INFO", f"正在启动隧道 {tunnel_name}...")

        # 构建启动命令
        cloudflared = get_cloudflared_path()
        cmd = [
            cloudflared,
            "--config", str(config_path),
            "tunnel", "run", tunnel_name
        ]

        # 使用 subprocess.Popen 启动进程
        cloudflared_process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            preexec_fn=os.setsid if os.name != 'nt' else None
        )

        # 等待几秒确认启动成功
        time.sleep(5)

        # 检查进程是否仍在运行
        if cloudflared_process.poll() is None:
            log("INFO", f"隧道 {tunnel_name} 启动成功，PID: {cloudflared_process.pid}")
            return cloudflared_process
        else:
            log("ERROR", f"隧道 {tunnel_name} 启动后立即退出")
            return None

    except Exception as e:
        log("ERROR", f"启动隧道失败: {e}")
        return None

def stop_tunnel():
    """停止隧道"""
    global cloudflared_process

    if cloudflared_process:
        try:
            log("INFO", "正在停止隧道...")

            # 发送 SIGTERM 信号优雅关闭
            if os.name != 'nt':
                os.killpg(os.getpgid(cloudflared_process.pid), signal.SIGTERM)
            else:
                cloudflared_process.terminate()

            # 等待进程结束
            cloudflared_process.wait(timeout=10)
            log("INFO", "隧道已停止")

        except subprocess.TimeoutExpired:
            log("WARNING", "隧道停止超时，强制终止")
            cloudflared_process.kill()
        except Exception as e:
            log("ERROR", f"停止隧道失败: {e}")
        finally:
            cloudflared_process = None

def restart_tunnel(tunnel_name: str, attempts: int = 0) -> bool:
    """重启隧道"""
    if attempts >= MAX_RESTART_ATTEMPTS:
        log("ERROR", f"已达到最大重启次数 ({MAX_RESTART_ATTEMPTS})，停止重试")
        return False

    log("INFO", f"正在重启隧道 (尝试 {attempts + 1}/{MAX_RESTART_ATTEMPTS})...")

    # 先停止现有隧道
    stop_tunnel()

    # 等待一段时间
    time.sleep(RESTART_DELAY)

    # 启动新隧道
    proc = start_tunnel(tunnel_name)

    if proc:
        # 再次检查状态
        time.sleep(10)
        if check_tunnel_status(tunnel_name):
            log("INFO", "隧道重启成功")
            return True
        else:
            log("WARNING", "隧道启动但状态检查失败，将再次尝试")
            return restart_tunnel(tunnel_name, attempts + 1)
    else:
        return restart_tunnel(tunnel_name, attempts + 1)

def monitor_tunnel(tunnel_name: str):
    """监控隧道主循环"""
    global running

    log("INFO", f"开始监控隧道 {tunnel_name}")
    log("INFO", f"检查间隔: {CHECK_INTERVAL} 秒")

    # 初始启动隧道
    if not check_tunnel_status(tunnel_name):
        log("INFO", "隧道未运行，正在启动...")
        restart_tunnel(tunnel_name)

    consecutive_failures = 0

    while running:
        try:
            # 等待检查间隔
            time.sleep(CHECK_INTERVAL)

            # 检查隧道状态
            if check_tunnel_status(tunnel_name):
                log("DEBUG", "隧道运行正常")
                consecutive_failures = 0
            else:
                consecutive_failures += 1
                log("WARNING", f"隧道断开检测 (连续失败: {consecutive_failures})")

                # 如果连续失败，尝试重启
                if consecutive_failures >= 2:
                    log("WARNING", "连续多次检测失败，尝试重启隧道")
                    if restart_tunnel(tunnel_name):
                        consecutive_failures = 0
                    else:
                        log("ERROR", "隧道重启失败，将在下次检查时重试")

        except KeyboardInterrupt:
            log("INFO", "接收到键盘中断")
            break
        except Exception as e:
            log("ERROR", f"监控循环异常: {e}")
            time.sleep(CHECK_INTERVAL)

def main():
    """主函数"""
    # 设置信号处理
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # 从命令行参数获取隧道名称
    if len(sys.argv) > 1:
        tunnel_name = sys.argv[1]
    else:
        tunnel_name = TUNNEL_NAME

    log("INFO", "="*50)
    log("INFO", "Cloudflared 隧道监控服务启动")
    log("INFO", f"监控隧道: {tunnel_name}")
    log("INFO", "="*50)

    if supervisor_active():
        return

    try:
        monitor_tunnel(tunnel_name)
    except Exception as e:
        log("ERROR", f"监控服务异常退出: {e}")
    finally:
        stop_tunnel()
        log("INFO", "监控服务已停止")

if __name__ == "__main__":
    main()
