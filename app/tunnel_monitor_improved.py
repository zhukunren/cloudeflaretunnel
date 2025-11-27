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
import re
from datetime import datetime
from pathlib import Path
import urllib.request
import urllib.error
import socket
import hashlib

try:
    from utils.file_lock import FileLock
except Exception:
    # 容错导入，避免脚本模式下失败
    FileLock = None

# 配置参数
TUNNEL_NAME = "homepage"  # 默认隧道名称
CHECK_INTERVAL = 30  # 检查间隔（秒）- 缩短到30秒
RESTART_DELAY = 10  # 重启延迟（秒）- 增加到10秒
MAX_RESTART_ATTEMPTS = 5  # 最大重启尝试次数 - 增加到5次
METRICS_PORT = None  # Metrics端口，运行时按隧道名生成，避免冲突
LOG_FILE = Path(__file__).parent.parent / "logs" / "tunnel_monitor_improved.log"
PROJECT_ROOT = Path(__file__).parent.parent
LOCK_FILE = Path(__file__).parent.parent / "logs" / "pids" / "tunnel_supervisor.lock"
_log_lock = FileLock(LOG_FILE.parent / ".tunnel_monitor_improved.log.lock") if FileLock else None


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


def get_metrics_port(tunnel_name: str) -> int:
    """根据隧道名生成确定性的 metrics 端口，避免多隧道冲突。"""
    # 使用哈希确保同名端口固定，不同名分散在可接受区间
    hash_val = int(hashlib.md5(tunnel_name.encode("utf-8")).hexdigest()[:4], 16)
    base = 20244
    return base + (hash_val % 200)  # 20244-20443


def _current_metrics_port(tunnel_name: str | None = None) -> int:
    """获取当前监控隧道对应的 metrics 端口。"""
    name = tunnel_name or current_tunnel_name or TUNNEL_NAME
    return METRICS_PORT or get_metrics_port(name)

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
    if _log_lock:
        with _log_lock.locked(timeout=1.0) as locked:
            if not locked:
                print(f"[{timestamp}] [WARNING] 无法获取日志锁，继续无锁写入")
            with open(LOG_FILE, 'a', encoding='utf-8') as f:
                f.write(log_message + '\n')
    else:
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
    port = _current_metrics_port()
    try:
        req = urllib.request.Request(f"http://localhost:{port}/ready")
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

def _check_connection_freshness(tunnel_name: str, max_age_seconds: int = 600) -> bool:
    """检查连接是否新鲜（在指定时间内建立的）

    防止长期未更新的过期连接被认为仍然活跃。
    返回 True 如果至少有一个新鲜连接。
    """
    try:
        cloudflared = get_cloudflared_path()
        result = subprocess.run(
            [cloudflared, "tunnel", "info", "--output", "json", tunnel_name],
            capture_output=True,
            text=True,
            timeout=10
        )

        if result.returncode != 0:
            log("DEBUG", "无法获取隧道信息检查新鲜度")
            return False

        data = json.loads(result.stdout)
        connectors = data.get("conns", [])

        if not connectors:
            log("DEBUG", "没有找到任何连接器")
            return False

        # 检查最新的连接是否在 max_age_seconds 内建立的
        from datetime import datetime, timedelta, timezone
        now = datetime.now(timezone.utc)
        max_age = timedelta(seconds=max_age_seconds)
        parsed_any = False

        for connector in connectors:
            if not isinstance(connector, dict):
                continue

            run_at_str = connector.get("run_at", "") or connector.get("created_at", "")
            if not run_at_str:
                continue

            try:
                # 解析 ISO 格式的时间戳
                run_at = datetime.fromisoformat(run_at_str.replace('Z', '+00:00'))
                if run_at.tzinfo is None:
                    run_at = run_at.replace(tzinfo=timezone.utc)
                parsed_any = True
                age = now - run_at

                if age < max_age:
                    log("DEBUG", f"检测到新鲜连接，年龄: {age.total_seconds():.0f}秒")
                    return True
            except Exception as e:
                log("DEBUG", f"解析时间戳失败: {e}")
                continue

        if not parsed_any:
            # 如果时间戳不可解析，但已有活跃连接，避免误判为过期
            log("WARNING", "无法解析连接时间戳，跳过新鲜度判断（不触发重启）")
            return True

        log("WARNING", "所有连接都过期（可能是僵尸连接）")
        return False

    except subprocess.TimeoutExpired:
        log("DEBUG", "连接新鲜度检查超时")
        return False
    except Exception as e:
        log("DEBUG", f"连接新鲜度检查异常: {e}")
        return False


def comprehensive_health_check(tunnel_name: str) -> bool:
    """综合健康检查 - 更严格的标准

    检查项：
    1. 进程是否运行
    2. Metrics 端点是否可用
    3. 是否有活跃连接
    4. 连接是否新鲜
    """
    # 1. 检查进程
    process_running = check_tunnel_process(tunnel_name)
    if not process_running:
        log("WARNING", "隧道进程未运行")
        return False

    # 2. 检查metrics端点
    metrics_status = check_metrics_endpoint()
    if not metrics_status["ready"]:
        log("WARNING", f"Metrics端点不健康: {metrics_status['status']}")
        # Metrics 端点失败可能只是暂时的，记录但继续检查其他项

    # 3. 检查实际连接
    connected, status = check_tunnel_connections(tunnel_name)
    if not connected:
        log("WARNING", f"隧道连接检查失败: {status}")
        return False

    # 4. ✓ 检查连接新鲜度（新增）- 增加超时时间，避免过度重启
    # 注：如果连接已建立，我们不应该因为连接"老化"而重启
    # 只有当连接真正失效时才重启，连接新鲜度检查在调试模式启用
    # if not _check_connection_freshness(tunnel_name, max_age_seconds=3600):
    #     log("WARNING", "隧道连接过期或不新鲜")
    #     return False

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
        metrics_port = _current_metrics_port(tunnel_name)
        cmd = [
            cloudflared,
            "--config", str(config_path),
            "--metrics", f"localhost:{metrics_port}",
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

        # 等待隧道完全启动 - 简化验证逻辑，只检查进程是否运行
        log("INFO", "等待隧道启动...")
        startup_timeout = 60  # 最多等待60秒
        for i in range(startup_timeout):
            time.sleep(1)

            # 检查进程是否仍在运行
            if cloudflared_process.poll() is not None:
                log("ERROR", f"隧道进程意外退出，退出码: {cloudflared_process.returncode}")
                return None

            # 仅在前30秒内尝试验证连接（不要让启动卡住）
            if i >= 5 and i % 5 == 0 and i <= 30:
                try:
                    # 尝试检查 metrics 端点
                    metrics_status = check_metrics_endpoint()
                    if metrics_status["ready"]:
                        log("INFO", f"隧道 {tunnel_name} Metrics端点已可用，PID: {cloudflared_process.pid}")
                        return cloudflared_process
                except Exception as e:
                    log("DEBUG", f"Metrics检查异常: {e}")

        # 如果60秒后进程仍在运行，则认为启动成功
        log("INFO", f"隧道 {tunnel_name} 进程启动成功，PID: {cloudflared_process.pid}（监控脚本将在后续检查连接状态）")
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
                # ✓ 安全地获取进程组，避免 PID 重用导致误杀其他进程
                pgid = None
                try:
                    pgid = os.getpgid(cloudflared_process.pid)
                except (ProcessLookupError, OSError):
                    pgid = None

                if pgid is not None:
                    try:
                        os.killpg(pgid, signal.SIGTERM)
                    except (ProcessLookupError, OSError):
                        log("DEBUG", "进程已退出，尝试直接杀死")
                        try:
                            cloudflared_process.terminate()
                        except ProcessLookupError:
                            pass
                else:
                    # 降级：直接发送信号而不是杀死进程组
                    try:
                        cloudflared_process.terminate()
                    except ProcessLookupError:
                        pass
            else:
                cloudflared_process.terminate()

            # 等待进程结束
            cloudflared_process.wait(timeout=30)
            log("INFO", "隧道已停止")

        except subprocess.TimeoutExpired:
            log("WARNING", "隧道停止超时，强制终止")
            if os.name != 'nt':
                # ✓ 强制杀死前再次安全检查
                pgid = None
                try:
                    pgid = os.getpgid(cloudflared_process.pid)
                except (ProcessLookupError, OSError):
                    pgid = None

                if pgid is not None:
                    try:
                        os.killpg(pgid, signal.SIGKILL)
                    except (ProcessLookupError, OSError):
                        try:
                            cloudflared_process.kill()
                        except ProcessLookupError:
                            pass
                else:
                    try:
                        cloudflared_process.kill()
                    except ProcessLookupError:
                        pass
            else:
                cloudflared_process.kill()
            cloudflared_process.wait(timeout=5)
        except Exception as e:
            log("ERROR", f"停止隧道失败: {e}")
        finally:
            cloudflared_process = None

    # 额外清理：仅终止命令行中明确包含 "tunnel run <name>" 的残留进程，避免前缀误杀
    try:
        ps = subprocess.run(
            ["ps", "-eo", "pid,command"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if ps.returncode == 0:
            pattern = re.compile(rf"\btunnel\s+run\s+{re.escape(target_tunnel)}(\s|$)")
            for line in ps.stdout.splitlines():
                parts = line.strip().split(None, 1)
                if len(parts) != 2:
                    continue
                pid_str, cmd = parts
                if not pattern.search(cmd):
                    continue
                try:
                    pid = int(pid_str)
                    if pid == os.getpid():
                        continue
                    os.kill(pid, signal.SIGTERM)
                except Exception:
                    continue
    except Exception as e:
        log("DEBUG", f"清理残留进程失败: {e}")

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
            last_restart_time = time.time()
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
    log("INFO", f"Metrics端口: {_current_metrics_port(tunnel_name)}")

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
                continue

            # 健康检查失败时，先确认进程是否还活着，避免误杀活跃隧道
            proc_alive = check_tunnel_process(tunnel_name)
            if proc_alive:
                connected, detail = check_tunnel_connections(tunnel_name)
                if connected:
                    log("WARNING", f"健康检查失败但隧道仍有活跃连接，跳过重启。原因：{detail}")
                    consecutive_failures = 0
                    continue
                # 进程在，但无连接，可能是暂时抖动，先累积计数

            consecutive_failures += 1
            log("WARNING", f"隧道健康检查失败 (连续失败: {consecutive_failures})")

            # 只有当进程不在运行，或连续失败达到阈值时才重启，避免误重启
            if (not proc_alive and consecutive_failures >= 1) or consecutive_failures >= 3:
                log("WARNING", "连续健康检查失败，尝试重启隧道")
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
    global current_tunnel_name, METRICS_PORT

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
    METRICS_PORT = get_metrics_port(tunnel_name)

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
