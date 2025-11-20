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

# 配置参数
TUNNEL_NAME = "homepage"  # 默认隧道名称
CHECK_INTERVAL = 60  # 检查间隔（秒）
RESTART_DELAY = 5  # 重启延迟（秒）
MAX_RESTART_ATTEMPTS = 3  # 最大重启尝试次数
LOG_FILE = Path(__file__).parent.parent / "logs" / "tunnel_monitor.log"

# 确保日志目录存在
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

# 全局变量
running = True
cloudflared_process = None

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
    """检查隧道连接状态"""
    try:
        # 使用 cloudflared tunnel info 检查状态
        result = subprocess.run(
            ["cloudflared", "tunnel", "info", tunnel_name],
            capture_output=True,
            text=True,
            timeout=10
        )

        if result.returncode == 0:
            # 检查是否有活跃连接
            output = result.stdout
            # 检查输出中是否包含 CONNECTOR ID（表示有连接器在运行）
            if "CONNECTOR ID" in output and "EDGE" in output:
                # 进一步检查连接是否真的在工作
                return check_tunnel_connectivity(tunnel_name)
            else:
                log("WARNING", f"隧道 {tunnel_name} 没有活跃的连接器")
                return False
        else:
            log("ERROR", f"无法获取隧道 {tunnel_name} 信息")
            return False

    except subprocess.TimeoutExpired:
        log("ERROR", "检查隧道状态超时")
        return False
    except Exception as e:
        log("ERROR", f"检查隧道状态失败: {e}")
        return False

def check_tunnel_connectivity(tunnel_name: str) -> bool:
    """检查隧道连通性"""
    try:
        # 检查 cloudflared 进程是否在运行
        result = subprocess.run(
            ["pgrep", "-f", f"tunnel run {tunnel_name}"],
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
        cmd = [
            "cloudflared",
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

    try:
        monitor_tunnel(tunnel_name)
    except Exception as e:
        log("ERROR", f"监控服务异常退出: {e}")
    finally:
        stop_tunnel()
        log("INFO", "监控服务已停止")

if __name__ == "__main__":
    main()