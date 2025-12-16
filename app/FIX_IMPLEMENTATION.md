# 具体修复代码方案

## 修复 #1：隧道名称混淆 (tunnel_monitor_improved.py)

### 问题位置：
```python
# 第55行
current_tunnel_name = None  # ❌ 初始化为 None

# 第101行
def stop_tunnel(tunnel_name: str = None):
    target_tunnel = tunnel_name or TUNNEL_NAME

# 第428行（太晚了）
current_tunnel_name = tunnel_name
```

### 修复代码：

```python
# 在 signal_handler 前面，确保 current_tunnel_name 总是有值
import sys

TUNNEL_NAME = "homepage"  # 默认隧道名称
current_tunnel_name = TUNNEL_NAME  # ✓ 初始化为默认值

def main():
    """主函数"""
    global current_tunnel_name

    # 设置信号处理（移到这里）
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # 从命令行参数获取隧道名称
    if len(sys.argv) > 1:
        tunnel_name = sys.argv[1]
    else:
        tunnel_name = TUNNEL_NAME

    # ✓ 立即设置全局变量，在启动任何操作前
    current_tunnel_name = tunnel_name

    log("INFO", "=" * 60)
    # ... 后续逻辑 ...
```

---

## 修复 #2：启动验证时间 (tunnel_supervisor.py)

### 问题位置：
```python
# 第178-181行
time.sleep(2)  # ❌ 仅等待2秒
if proc.poll() is not None:
    self._log("ERROR", f"隧道 {name} 启动后异常退出，返回码 {proc.returncode}")
    return False
```

### 修复代码：

```python
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

    try:
        proc = cf.run_tunnel(
            self.cloudflared_path,
            name,
            spec.config,
            capture_output=False,
            log_file=log_file,
        )
    except Exception as exc:
        self._log("ERROR", f"启动隧道 {name} 失败: {exc}")
        return False

    # ✓ 等待隧道完全启动（最多10秒）
    max_wait = 10
    for i in range(max_wait):
        time.sleep(1)

        # 检查进程是否仍在运行
        if proc.poll() is not None:
            self._log("ERROR", f"隧道 {name} 启动后异常退出，返回码 {proc.returncode}")
            return False

        # 每2秒检查一次连接状态
        if i % 2 == 1:
            ok, msg = self._health_check(name)
            if ok:
                self.tracker.register(
                    name,
                    proc.pid,
                    manager="tunnel_supervisor",
                    mode="supervised",
                    metadata={"reason": reason, "log_file": str(log_file)},
                )
                self._log("INFO", f"隧道 {name} 启动成功，PID {proc.pid}")
                return True

    # 如果10秒后仍未连接，返回失败
    self._log("WARNING", f"隧道 {name} 启动超时（{max_wait}秒无活跃连接），可能网络问题")
    return False
```

---

## 修复 #3：日志写入竞争 (tunnel_supervisor.py)

### 添加日志锁：

```python
from .utils.file_lock import FileLock  # ✓ 导入文件锁

class TunnelSupervisor:
    def __init__(self, config_path: Path | None = None):
        self.base_dir = Path(__file__).resolve().parent.parent
        self.settings = Settings(self.base_dir / "config" / "app_config.json")
        self.tracker = ProcessTracker(self.base_dir)
        self.lock = SupervisorLock(self.base_dir)
        self.log_file = self.base_dir / "logs" / "tunnel_supervisor.log"
        self.log_file.parent.mkdir(parents=True, exist_ok=True)

        # ✓ 添加日志文件锁
        self._log_lock = FileLock(self.log_file.parent / ".log.lock")

        self.config_path = config_path or (self.base_dir / "config" / "tunnels.json")
        # ... 其他初始化 ...

    def _log(self, level: str, message: str):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{timestamp}] [{level}] {message}\n"
        print(line.rstrip('\n'))

        # ✓ 使用文件锁保护写入
        with self._log_lock.locked(timeout=1.0) as locked:
            if not locked:
                print(f"[{timestamp}] [WARNING] 日志文件锁超时，可能存在日志丢失")
            with open(self.log_file, "a", encoding="utf-8") as fh:
                fh.write(line)
```

### 修复 tunnel_monitor_improved.py 中的日志：

```python
from utils.file_lock import FileLock

# 添加全局日志锁
_log_lock = FileLock(LOG_FILE.parent / ".log.lock")

def log(level: str, message: str):
    """写入日志"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    log_message = f"[{timestamp}] [{level}] {message}"
    print(log_message)

    # ✓ 使用文件锁保护写入
    with _log_lock.locked(timeout=1.0) as locked:
        if not locked:
            print(f"[{timestamp}] [WARNING] 日志文件锁超时")
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(log_message + '\n')
```

---

## 修复 #4：进程组死亡竞争 (tunnel_monitor_improved.py)

### 问题位置：
```python
# 第295-323行
if os.name != 'nt':
    os.killpg(os.getpgid(cloudflared_process.pid), signal.SIGTERM)  # ❌ 无错误处理
```

### 修复代码：

```python
def stop_tunnel(tunnel_name: str = None):
    """停止隧道"""
    global cloudflared_process

    # 如果没有指定隧道名，使用默认值
    target_tunnel = tunnel_name or TUNNEL_NAME

    if cloudflared_process:
        try:
            log("INFO", "正在停止隧道...")

            # ✓ 检查进程是否仍在运行
            if cloudflared_process.poll() is not None:
                log("INFO", "隧道进程已退出")
                cloudflared_process = None
                return

            # 发送 SIGTERM 信号优雅关闭
            if os.name != 'nt':
                try:
                    pgid = os.getpgid(cloudflared_process.pid)
                    os.killpg(pgid, signal.SIGTERM)
                except (ProcessLookupError, OSError) as e:
                    log("DEBUG", f"进程组已死亡 ({e})，尝试直接杀死进程")
                    try:
                        cloudflared_process.terminate()
                    except ProcessLookupError:
                        pass
            else:
                cloudflared_process.terminate()

            # 等待进程结束
            try:
                cloudflared_process.wait(timeout=30)
                log("INFO", "隧道已停止")
            except subprocess.TimeoutExpired:
                log("WARNING", "隧道停止超时，强制终止")
                if os.name != 'nt':
                    try:
                        pgid = os.getpgid(cloudflared_process.pid)
                        os.killpg(pgid, signal.SIGKILL)
                    except (ProcessLookupError, OSError):
                        try:
                            cloudflared_process.kill()
                        except ProcessLookupError:
                            pass
                else:
                    cloudflared_process.kill()
                try:
                    cloudflared_process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    log("ERROR", "强制终止失败")
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
    except Exception as e:
        log("DEBUG", f"pkill 失败: {e}")
```

同样修复 `cloudflared_cli.py` 中的 `stop_process()` 函数（第654-700行）。

---

## 修复 #5：锁文件原子性 (utils/process_tracker.py)

### 问题位置：
```python
# 第226-241行
def acquire(self, owner: str):
    with self._lock.locked(timeout=2.0) as locked:
        if not locked:
            print("SupervisorLock: 获取锁超时，继续无锁尝试。")  # ❌ 继续！
        # ... 检查 ...
        self.lock_path.write_text(...)  # ❌ 非原子
```

### 修复代码：

```python
class SupervisorLock:
    """用于避免多个守护进程/GUI 同时调度隧道"""

    def __init__(self, base_dir: Path | None = None):
        self.base_dir = base_dir or Path(__file__).resolve().parent.parent
        self.lock_path = self.base_dir / "logs" / "pids" / "tunnel_supervisor.lock"
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = FileLock(self.lock_path.with_suffix(".lockfile"))

    @staticmethod
    def _write_json_atomic(path: Path, payload: dict):
        """原子写入，避免崩溃留下损坏文件"""
        temp = path.with_suffix(path.suffix + ".tmp")
        temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(path)  # 原子操作

    def info(self) -> dict | None:
        if not self.lock_path.exists():
            return None
        try:
            data = json.loads(self.lock_path.read_text(encoding="utf-8"))
        except Exception:
            return None
        pid = int(data.get("pid", 0) or 0)
        alive = ProcessTracker._is_pid_running(pid)
        data["alive"] = alive
        data["path"] = str(self.lock_path)
        return data

    def acquire(self, owner: str):
        # ✓ 如果获取锁失败，立即抛出异常
        with self._lock.locked(timeout=2.0) as locked:
            if not locked:
                raise RuntimeError(
                    "SupervisorLock: 获取锁超时，无法安全启动守护进程"
                )

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
            # ✓ 使用原子写入
            self._write_json_atomic(self.lock_path, payload)

    def release(self):
        with self._lock.locked(timeout=2.0) as locked:
            if not locked:
                print("SupervisorLock: 获取锁超时，尝试无锁释放。")
            self.lock_path.unlink(missing_ok=True)
```

---

## 修复 #6：重启时间计算 (tunnel_monitor_improved.py)

### 问题位置：
```python
# 第333-359行
def restart_tunnel_with_backoff(tunnel_name: str, attempt: int = 0) -> bool:
    global last_restart_time

    current_time = time.time()  # ❌ 过早获取时间
    # ... 中间可能耗时 30 秒 ...
    if comprehensive_health_check(tunnel_name):
        log("INFO", "隧道重启成功")
        last_restart_time = current_time  # ❌ 使用过时的时间
        return True
```

### 修复代码：

```python
def restart_tunnel_with_backoff(tunnel_name: str, attempt: int = 0) -> bool:
    global last_restart_time

    if attempt >= MAX_RESTART_ATTEMPTS:
        log("ERROR", f"已达到最大重启次数 ({MAX_RESTART_ATTEMPTS})")
        return False

    # ✓ 仅在第一次尝试时检查冷却时间
    if attempt == 0:
        current_time = time.time()
        if current_time - last_restart_time < restart_cooldown:
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
            # ✓ 在成功后立即更新时间戳
            last_restart_time = time.time()
            return True
        else:
            log("WARNING", f"隧道启动但健康检查失败，继续尝试...")
            return restart_tunnel_with_backoff(tunnel_name, attempt + 1)
    else:
        return restart_tunnel_with_backoff(tunnel_name, attempt + 1)
```

---

## 修复 #7：Metrics 端口冲突 (tunnel_monitor_improved.py)

### 问题位置：
```python
# 第24行
METRICS_PORT = 20244  # ❌ 硬编码，冲突
```

### 修复代码：

```python
import hashlib

def get_metrics_port(tunnel_name: str) -> int:
    """生成唯一的metrics端口

    基于隧道名称计算，确保同一隧道总是使用相同的端口，
    但不同隧道使用不同的端口。
    """
    # 使用 MD5 哈希获得确定性的伪随机数
    hash_val = int(hashlib.md5(tunnel_name.encode()).hexdigest()[:4], 16)
    # 在 20244-20444 范围内分配（200个端口）
    return 20244 + (hash_val % 200)

# 使用动态端口而不是硬编码
TUNNEL_NAME = "homepage"  # 默认隧道名称
METRICS_PORT = None  # 在 main() 中初始化

def main():
    global METRICS_PORT, TUNNEL_NAME

    # 从命令行参数获取隧道名称
    if len(sys.argv) > 1:
        TUNNEL_NAME = sys.argv[1]

    # ✓ 基于隧道名称计算端口
    METRICS_PORT = get_metrics_port(TUNNEL_NAME)

    log("INFO", f"隧道 {TUNNEL_NAME} 将使用 Metrics 端口: {METRICS_PORT}")
    # ... 后续逻辑 ...
```

同时更新 `start_tunnel()` 函数中的 Metrics 参数：

```python
def start_tunnel(tunnel_name: str) -> subprocess.Popen:
    """启动隧道"""
    # ... 前置检查 ...

    try:
        env = os.environ.copy()
        env['QUIC_GO_UDP_RECEIVE_BUFFER_SIZE'] = '7340032'

        log("INFO", f"正在启动隧道 {tunnel_name}...")

        cloudflared = get_cloudflared_path()
        cmd = [
            cloudflared,
            "--config", str(config_path),
            "--metrics", f"localhost:{get_metrics_port(tunnel_name)}",  # ✓ 使用函数
            "--grace-period", "30s",
            "tunnel", "run",
            tunnel_name
        ]

        # ... 后续代码 ...
```

---

## 修复 #8：健康检查策略 (tunnel_monitor_improved.py)

### 问题位置：
```python
# 第194-214行
def comprehensive_health_check(tunnel_name: str) -> bool:
    # ... 检查但不使用 metrics_status ...
    if not metrics_status["ready"]:
        log("WARNING", f"Metrics端点不健康: {metrics_status['status']}")
        # 不立即返回False，导致检查不准确
```

### 修复代码：

```python
def comprehensive_health_check(tunnel_name: str) -> bool:
    """综合健康检查 - 更严格的标准"""

    # 1. 检查进程是否运行
    process_running = check_tunnel_process(tunnel_name)
    if not process_running:
        log("WARNING", "隧道进程未运行")
        return False

    # 2. 检查metrics端点可用性
    metrics_status = check_metrics_endpoint()
    if not metrics_status["ready"]:
        log("WARNING", f"Metrics端点不健康: {metrics_status['status']}")
        # ✓ 如果是第一次失败，继续；但多次失败则视为不健康
        # （在主循环中处理连续失败计数）
        pass

    # 3. 检查实际连接
    connected, status = check_tunnel_connections(tunnel_name)
    if not connected:
        log("WARNING", f"隧道连接检查失败: {status}")
        return False

    # 4. 验证连接是否活跃（有数据传输）
    # 这是一个新增的检查，确保连接不是过期的
    if not _check_connection_freshness(tunnel_name):
        log("WARNING", "隧道连接已过期，需要重启")
        return False

    return True

def _check_connection_freshness(tunnel_name: str, max_age_seconds: int = 300) -> bool:
    """检查连接是否新鲜（在指定时间内建立的）

    防止长期未更新的过期连接被认为仍然活跃。
    """
    try:
        result = subprocess.run(
            [get_cloudflared_path(), "tunnel", "info", "--output", "json", tunnel_name],
            capture_output=True,
            text=True,
            timeout=10
        )

        if result.returncode != 0:
            return False

        data = json.loads(result.stdout)
        connectors = data.get("conns", [])

        if not connectors:
            return False

        # 检查最新的连接是否在 max_age_seconds 内建立的
        from datetime import datetime, timedelta
        now = datetime.utcnow()
        max_age = timedelta(seconds=max_age_seconds)

        for connector in connectors:
            if not isinstance(connector, dict):
                continue

            run_at_str = connector.get("run_at", "")
            try:
                # 解析 ISO 格式的时间戳
                run_at = datetime.fromisoformat(run_at_str.replace('Z', '+00:00'))
                age = now - run_at

                if age < max_age:
                    return True  # 至少有一个新鲜连接
            except Exception:
                continue

        log("WARNING", "所有连接都过期（可能是僵尸连接）")
        return False

    except Exception as e:
        log("DEBUG", f"检查连接新鲜度失败: {e}")
        return False
```

在主循环中，使用更智能的连续失败计数：

```python
def monitor_tunnel(tunnel_name: str):
    """监控隧道主循环"""
    global running, consecutive_failures

    log("INFO", f"开始监控隧道 {tunnel_name}")
    log("INFO", f"检查间隔: {CHECK_INTERVAL} 秒")
    log("INFO", f"Metrics端口: {get_metrics_port(tunnel_name)}")

    # 初始启动隧道
    if not comprehensive_health_check(tunnel_name):
        log("INFO", "隧道未运行或不健康，正在启动...")
        restart_tunnel_with_backoff(tunnel_name)

    consecutive_failures = 0
    metrics_failure_count = 0  # ✓ 追踪 metrics 端点的失败次数

    while running:
        try:
            time.sleep(CHECK_INTERVAL)

            # 执行综合健康检查
            if comprehensive_health_check(tunnel_name):
                if consecutive_failures > 0:
                    log("INFO", f"隧道恢复正常 (之前连续失败: {consecutive_failures})")
                consecutive_failures = 0
                metrics_failure_count = 0
            else:
                consecutive_failures += 1
                log("WARNING", f"隧道健康检查失败 (连续失败: {consecutive_failures})")

                # ✓ 更灵活的重启策略
                # - 第一次失败：等待
                # - 第二次失败：考虑重启
                # - 第三次失败：确定重启
                should_restart = False

                if consecutive_failures >= 3:
                    should_restart = True
                elif consecutive_failures == 2 and metrics_failure_count >= 2:
                    # 如果 metrics 端点也连续失败，更早重启
                    should_restart = True

                if should_restart:
                    log("WARNING", "多次健康检查失败，尝试重启隧道")
                    if restart_tunnel_with_backoff(tunnel_name):
                        consecutive_failures = 0
                        metrics_failure_count = 0
                    else:
                        log("ERROR", "隧道重启失败")
                        time.sleep(60)  # 等待一分钟后重试

        except KeyboardInterrupt:
            log("INFO", "接收到键盘中断")
            break
        except Exception as e:
            log("ERROR", f"监控循环异常: {e}")
            time.sleep(CHECK_INTERVAL)
```

---

## 验证修复的测试方案

建议添加以下测试来验证修复效果：

```python
# test_stability.py
import time
import subprocess
from pathlib import Path

def test_multiple_tunnels_no_conflict():
    """测试：多个隧道不会冲突"""
    # 启动 tunnel_supervisor watch
    supervisor = subprocess.Popen(
        ["python", "tunnel_supervisor.py", "watch", "--interval", "5"]
    )

    time.sleep(2)

    # 启动多个监控脚本
    monitors = []
    for tunnel in ["homepage", "api", "admin"]:
        proc = subprocess.Popen(
            ["python", "tunnel_monitor_improved.py", tunnel]
        )
        monitors.append(proc)

    # 运行 30 秒
    time.sleep(30)

    # 检查：所有进程应该仍在运行
    assert supervisor.poll() is None, "Supervisor 意外退出"
    for i, proc in enumerate(monitors):
        assert proc.poll() is None, f"Monitor {i} 意外退出"

    # 清理
    supervisor.terminate()
    for proc in monitors:
        proc.terminate()

def test_signal_handling():
    """测试：信号处理不会杀死错误的隧道"""
    # 启动两个隧道
    tunnel1 = subprocess.Popen(
        ["python", "cloudflared_cli.py", "run", "homepage"]
    )
    tunnel2 = subprocess.Popen(
        ["python", "cloudflared_cli.py", "run", "api"]
    )

    time.sleep(5)

    # 发送信号给监控脚本
    monitor = subprocess.Popen(
        ["python", "tunnel_monitor_improved.py", "homepage"]
    )
    time.sleep(2)
    monitor.send_signal(15)  # SIGTERM
    monitor.wait()

    # 检查：api 隧道应该仍在运行
    assert tunnel2.poll() is None, "API 隧道被误杀"

    # 清理
    tunnel1.terminate()
    tunnel2.terminate()
```

