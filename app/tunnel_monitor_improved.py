#!/usr/bin/env python3
"""
改进的 Cloudflared 隧道监控和自动重连脚本
修复了连接检测不准确和重连不稳定的问题
"""

import subprocess
import time
import signal
import sys
import os
import json
from datetime import datetime
from pathlib import Path
import urllib.request
import urllib.error
import socket

# 配置参数
TUNNEL_NAME = "homepage"  # 默认隧道名称
CHECK_INTERVAL = 30  # 检查间隔（秒）- 缩短到30秒
RESTART_DELAY = 10  # 重启延迟（秒）- 增加到10秒
MAX_RESTART_ATTEMPTS = 5  # 最大重启尝试次数 - 增加到5次
METRICS_PORT = 20244  # Cloudflared metrics端口（避免与其他隧道占用 20242/20243）
LOG_FILE = Path(__file__).parent.parent / "logs" / "tunnel_monitor_improved.log"
PROJECT_ROOT = Path(__file__).parent.parent
LOCK_FILE = Path(__file__).parent.parent / "logs" / "pids" / "tunnel_supervisor.lock"


def get_cloudflared_path() -> str:
    """获取 cloudflared 可执行文件路径"""
    config_file = PROJECT_ROOT / "config" / "tunnels.json"
    if config_file.exists():
        try:
            data = json.loads(config_file.read_text(encoding="utf-8"))
            path = data.get("cloudflared_path")
            if path and Path(path).exists():
                return path
        except Exception:
            pass
    local_path = PROJECT_ROOT / "cloudflared"
    if local_path.exists():
        return str(local_path)
    return "cloudflared"

# 确保日志目录存在
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

# 全局变量
running = True
cloudflared_process = None
consecutive_failures = 0
last_restart_time = 0
restart_cooldown = 120  # 重启冷却时间（秒）
current_tunnel_name = None  # 当前监控的隧道名称


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
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
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
    stop_tunnel(current_tunnel_name)
    sys.exit(0)

def get_tunnel_config_path(tunnel_name: str) -> Path:
    """获取隧道配置文件路径"""
    base_path = Path(__file__).parent.parent
    config_path = base_path / "tunnels" / tunnel_name / "config.yml"
    return config_path

def check_metrics_endpoint() -> dict:
    """检查cloudflared metrics端点获取隧道状态"""
    try:
        req = urllib.request.Request(f"http://localhost:{METRICS_PORT}/ready")
        req.add_header('User-Agent', 'tunnel-monitor/1.0')

        with urllib.request.urlopen(req, timeout=5) as response:
            if response.getcode() == 200:
                return {"ready": True, "status": "healthy"}
            else:
                return {"ready": False, "status": "unhealthy"}
    except urllib.error.URLError as e:
        log("DEBUG", f"Metrics端点检查失败: {e}")
        return {"ready": False, "status": "unreachable"}
    except socket.timeout:
        log("DEBUG", "Metrics端点检查超时")
        return {"ready": False, "status": "timeout"}
    except Exception as e:
        log("DEBUG", f"Metrics端点检查异常: {e}")
        return {"ready": False, "status": "error"}

def check_tunnel_connections(tunnel_name: str) -> tuple[bool, str]:
    """使用cloudflared tunnel info命令检查隧道连接"""
    cloudflared = get_cloudflared_path()
    try:
        # 使用JSON输出格式获取更准确的信息
        result = subprocess.run(
            [cloudflared, "tunnel", "info", "--output", "json", tunnel_name],
            capture_output=True,
            text=True,
            timeout=15
        )

        if result.returncode == 0:
            try:
                data = json.loads(result.stdout)
                connectors = data.get("conns", [])

                active_connections = 0
                for connector in connectors:
                    if isinstance(connector, dict):
                        edges = connector.get("conns", [])
                        active_connections += len(edges)

                if active_connections > 0:
                    log("DEBUG", f"隧道有 {active_connections} 个活跃连接")
                    return True, f"Active connections: {active_connections}"
                else:
                    return False, "No active connections"

            except json.JSONDecodeError:
                # 回退到文本解析
                output = result.stdout.lower()
                if "connector id" in output:
                    return True, "Connector found"
                else:
                    return False, "No connector found"
        else:
            error_msg = result.stderr or result.stdout
            return False, f"Command failed: {error_msg}"

    except subprocess.TimeoutExpired:
        return False, "Check timeout"
    except Exception as e:
        return False, f"Check error: {e}"

def check_tunnel_process(tunnel_name: str) -> bool:
    """检查隧道进程是否在运行"""
    try:
        result = subprocess.run(
            ["pgrep", "-f", f"tunnel.*run.*{tunnel_name}"],
            capture_output=True,
            timeout=5
        )

        if result.returncode == 0:
            pids = result.stdout.decode().strip().split('\n')
            if pids and pids[0]:
                return True
        return False

    except Exception:
        return False

def comprehensive_health_check(tunnel_name: str) -> bool:
    """综合健康检查"""
    # 1. 检查进程
    process_running = check_tunnel_process(tunnel_name)
    if not process_running:
        log("WARNING", "隧道进程未运行")
        return False

    # 2. 检查metrics端点
    metrics_status = check_metrics_endpoint()
    if not metrics_status["ready"]:
        log("WARNING", f"Metrics端点不健康: {metrics_status['status']}")
        # 不立即返回False，因为metrics端点可能暂时不可用

    # 3. 检查实际连接
    connected, status = check_tunnel_connections(tunnel_name)
    if not connected:
        log("WARNING", f"隧道连接检查失败: {status}")
        return False

    return True

def start_tunnel(tunnel_name: str) -> subprocess.Popen:
    """启动隧道"""
    global cloudflared_process

    config_path = get_tunnel_config_path(tunnel_name)

    if not config_path.exists():
        log("ERROR", f"配置文件不存在: {config_path}")
        return None

    try:
        # 设置环境变量
        env = os.environ.copy()
        # 增加UDP缓冲区大小
        env['QUIC_GO_UDP_RECEIVE_BUFFER_SIZE'] = '7340032'  # 7MB

        log("INFO", f"正在启动隧道 {tunnel_name}...")

        # 构建启动命令，添加更多参数
        cloudflared = get_cloudflared_path()
        cmd = [
            cloudflared,
            "--config", str(config_path),
            "--metrics", f"localhost:{METRICS_PORT}",
            "--grace-period", "30s",  # 优雅关闭时间
            "tunnel", "run",
            tunnel_name
        ]

        # 创建日志文件
        log_dir = Path(__file__).parent.parent / "logs" / "persistent"
        log_dir.mkdir(parents=True, exist_ok=True)
        tunnel_log = log_dir / f"cloudflared_{tunnel_name}.log"

        with open(tunnel_log, 'a') as log_file:
            cloudflared_process = subprocess.Popen(
                cmd,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                env=env,
                preexec_fn=os.setsid if os.name != 'nt' else None
            )

        # 等待隧道完全启动
        log("INFO", "等待隧道启动...")
        for i in range(30):  # 最多等待30秒
            time.sleep(1)

            # 检查进程是否仍在运行
            if cloudflared_process.poll() is not None:
                log("ERROR", f"隧道进程意外退出，退出码: {cloudflared_process.returncode}")
                return None

            # 每5秒检查一次连接状态
            if i % 5 == 4:
                connected, _ = check_tunnel_connections(tunnel_name)
                if connected:
                    log("INFO", f"隧道 {tunnel_name} 启动成功，PID: {cloudflared_process.pid}")
                    return cloudflared_process

        log("WARNING", "隧道启动超时，但进程仍在运行")
        return cloudflared_process

    except Exception as e:
        log("ERROR", f"启动隧道失败: {e}")
        return None

def stop_tunnel(tunnel_name: str = None):
    """停止隧道"""
    global cloudflared_process

    # 如果没有指定隧道名，使用默认值
    target_tunnel = tunnel_name or TUNNEL_NAME

    if cloudflared_process:
        try:
            log("INFO", "正在停止隧道...")

            # 发送 SIGTERM 信号优雅关闭
            if os.name != 'nt':
                os.killpg(os.getpgid(cloudflared_process.pid), signal.SIGTERM)
            else:
                cloudflared_process.terminate()

            # 等待进程结束
            cloudflared_process.wait(timeout=30)
            log("INFO", "隧道已停止")

        except subprocess.TimeoutExpired:
            log("WARNING", "隧道停止超时，强制终止")
            if os.name != 'nt':
                os.killpg(os.getpgid(cloudflared_process.pid), signal.SIGKILL)
            else:
                cloudflared_process.kill()
            cloudflared_process.wait(timeout=5)
        except Exception as e:
            log("ERROR", f"停止隧道失败: {e}")
        finally:
            cloudflared_process = None

    # 额外清理：杀死所有相关进程（使用正确的隧道名称）
    try:
        subprocess.run(
            ["pkill", "-f", f"tunnel.*run.*{target_tunnel}"],
            timeout=5
        )
    except:
        pass

def restart_tunnel_with_backoff(tunnel_name: str, attempt: int = 0) -> bool:
    """带指数退避的重启隧道"""
    global last_restart_time

    if attempt >= MAX_RESTART_ATTEMPTS:
        log("ERROR", f"已达到最大重启次数 ({MAX_RESTART_ATTEMPTS})")
        return False

    # 检查重启冷却时间
    current_time = time.time()
    if current_time - last_restart_time < restart_cooldown and attempt == 0:
        log("INFO", f"距离上次重启不足{restart_cooldown}秒，跳过本次重启")
        return False

    # 计算退避时间：2^attempt * RESTART_DELAY
    backoff_time = (2 ** attempt) * RESTART_DELAY
    backoff_time = min(backoff_time, 300)  # 最大5分钟

    log("INFO", f"正在重启隧道 (尝试 {attempt + 1}/{MAX_RESTART_ATTEMPTS})，等待 {backoff_time}秒...")

    # 停止现有隧道
    stop_tunnel(tunnel_name)

    # 等待退避时间
    time.sleep(backoff_time)

    # 启动新隧道
    proc = start_tunnel(tunnel_name)

    if proc:
        # 检查启动是否成功
        time.sleep(15)
        if comprehensive_health_check(tunnel_name):
            log("INFO", "隧道重启成功")
            last_restart_time = current_time
            return True
        else:
            log("WARNING", f"隧道启动但健康检查失败，继续尝试...")
            return restart_tunnel_with_backoff(tunnel_name, attempt + 1)
    else:
        return restart_tunnel_with_backoff(tunnel_name, attempt + 1)

def monitor_tunnel(tunnel_name: str):
    """监控隧道主循环"""
    global running, consecutive_failures

    log("INFO", f"开始监控隧道 {tunnel_name}")
    log("INFO", f"检查间隔: {CHECK_INTERVAL} 秒")
    log("INFO", f"Metrics端口: {METRICS_PORT}")

    # 初始启动隧道
    if not comprehensive_health_check(tunnel_name):
        log("INFO", "隧道未运行或不健康，正在启动...")
        restart_tunnel_with_backoff(tunnel_name)

    consecutive_failures = 0

    while running:
        try:
            # 等待检查间隔
            time.sleep(CHECK_INTERVAL)

            # 执行综合健康检查
            if comprehensive_health_check(tunnel_name):
                if consecutive_failures > 0:
                    log("INFO", f"隧道恢复正常 (之前连续失败: {consecutive_failures})")
                consecutive_failures = 0
            else:
                consecutive_failures += 1
                log("WARNING", f"隧道健康检查失败 (连续失败: {consecutive_failures})")

                # 如果连续失败超过阈值，尝试重启
                if consecutive_failures >= 3:
                    log("WARNING", "连续多次健康检查失败，尝试重启隧道")
                    if restart_tunnel_with_backoff(tunnel_name):
                        consecutive_failures = 0
                    else:
                        log("ERROR", "隧道重启失败")
                        # 等待更长时间后再试
                        time.sleep(60)

        except KeyboardInterrupt:
            log("INFO", "接收到键盘中断")
            break
        except Exception as e:
            log("ERROR", f"监控循环异常: {e}")
            time.sleep(CHECK_INTERVAL)

def main():
    """主函数"""
    global current_tunnel_name

    # 设置信号处理
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # 从命令行参数获取隧道名称
    if len(sys.argv) > 1:
        tunnel_name = sys.argv[1]
    else:
        tunnel_name = TUNNEL_NAME

    # 设置全局变量，用于信号处理
    current_tunnel_name = tunnel_name

    log("INFO", "=" * 60)
    log("INFO", "改进的 Cloudflared 隧道监控服务启动")
    log("INFO", f"监控隧道: {tunnel_name}")
    log("INFO", f"Cloudflared路径: {get_cloudflared_path()}")
    log("INFO", "=" * 60)

    if supervisor_active():
        return

    try:
        monitor_tunnel(tunnel_name)
    except Exception as e:
        log("ERROR", f"监控服务异常退出: {e}")
        import traceback
        log("ERROR", traceback.format_exc())
    finally:
        stop_tunnel(tunnel_name)
        log("INFO", "监控服务已停止")

if __name__ == "__main__":
    main()
