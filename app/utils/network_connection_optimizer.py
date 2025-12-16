#!/usr/bin/env python3
"""
改进的隧道监控脚本 - 集成网络优化
优化项目：
1. 智能超时管理（自适应超时）
2. 指数退避重试（API 调用）
3. 网络异常诊断和恢复
4. 连接状态缓存（降低 API 调用频率）
5. 多阶段健康检查
"""

import subprocess
import time
import sys
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Tuple

try:
    from utils.network_optimizer import (
        RetryConfig,
        TimeoutConfig,
        NetworkDiagnostics,
        RetryableOperation,
        AdaptiveTimeout,
        get_network_cache,
        get_adaptive_timeout,
    )
except ImportError:
    # 降级处理：如果网络优化模块不可用，使用默认实现
    class RetryConfig:
        def __init__(self, max_attempts=3, initial_delay=0.5, max_delay=30.0, backoff_factor=2.0, jitter=True):
            self.max_attempts = max_attempts
            self.initial_delay = initial_delay
            self.max_delay = max_delay
            self.backoff_factor = backoff_factor
            self.jitter = jitter

    class TimeoutConfig:
        def __init__(self, default_timeout=10.0, api_timeout=15.0, health_check_timeout=5.0):
            self.default_timeout = default_timeout
            self.api_timeout = api_timeout
            self.health_check_timeout = health_check_timeout

    def get_network_cache():
        return None

    def get_adaptive_timeout():
        return None


class ImprovedTunnelMonitor:
    """改进的隧道监控器 - 集成网络优化"""

    def __init__(
        self,
        cloudflared_path: str,
        tunnel_name: str,
        check_interval: int = 30,
        max_restart_attempts: int = 5,
    ):
        self.cloudflared_path = cloudflared_path
        self.tunnel_name = tunnel_name
        self.check_interval = check_interval
        self.max_restart_attempts = max_restart_attempts

        # 网络优化配置
        self.retry_config = RetryConfig(
            max_attempts=3,
            initial_delay=0.5,
            max_delay=30.0,
            backoff_factor=2.0,
        )
        self.timeout_config = TimeoutConfig(
            default_timeout=10.0,
            api_timeout=15.0,
            health_check_timeout=5.0,
        )

        # 缓存和自适应超时
        self.network_cache = get_network_cache()
        self.adaptive_timeout = get_adaptive_timeout()

        # 状态跟踪
        self.last_restart_time = 0
        self.restart_cooldown = 120
        self.consecutive_failures = 0
        self.failure_history = []  # 跟踪最近的失败

    def _get_timeout(self, operation_type: str = "default") -> float:
        """获取自适应超时时间"""
        base_timeouts = {
            "api": self.timeout_config.api_timeout,
            "health": self.timeout_config.health_check_timeout,
            "default": self.timeout_config.default_timeout,
        }
        base = base_timeouts.get(operation_type, self.timeout_config.default_timeout)

        if self.adaptive_timeout:
            return self.adaptive_timeout.get_recommended_timeout(base)
        return base

    def check_tunnel_connection(self) -> Tuple[Optional[bool], str]:
        """
        检查隧道连接状态
        返回: (True/False/None, 描述信息)
        - True: 有活跃连接
        - False: 确认无连接
        - None: 状态未知（网络/API 异常）
        """
        # 尝试从缓存获取
        if self.network_cache:
            cached = self.network_cache.get("check_connection", self.tunnel_name)
            if cached is not None:
                return cached

        # 使用指数退避重试
        operation = RetryableOperation(self.retry_config)
        timeout = self._get_timeout("api")

        def _run_check():
            result = subprocess.run(
                [self.cloudflared_path, "tunnel", "info", "--output", "json", self.tunnel_name],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            if result.returncode != 0:
                raise Exception(result.stderr or "Command failed")
            return json.loads(result.stdout)

        success, data, error = operation.execute(
            _run_check,
            operation_name=f"check_connection:{self.tunnel_name}",
        )

        if not success:
            error_type = NetworkDiagnostics.classify_error(error)
            if error_type in ["timeout", "tls_error", "api_server_error"]:
                # 网络/API 异常，返回 None（跳过重启）
                if self.network_cache:
                    self.network_cache.set("check_connection", (None, error), self.tunnel_name)
                if self.adaptive_timeout:
                    self.adaptive_timeout.record_failure(timeout)
                return None, f"网络异常：{error_type} - {error}"

            # 其他错误，认为是无连接
            if self.network_cache:
                self.network_cache.set("check_connection", (False, error), self.tunnel_name)
            return False, error

        # 解析连接数
        try:
            conns = data.get("conns", [])
            active_edges = 0
            for conn in conns:
                if isinstance(conn, dict):
                    edges = conn.get("conns", [])
                    if isinstance(edges, list):
                        active_edges += len(edges)

            if active_edges > 0:
                result = (True, f"有 {active_edges} 条活跃连接")
                if self.network_cache:
                    self.network_cache.set("check_connection", result, self.tunnel_name)
                if self.adaptive_timeout:
                    self.adaptive_timeout.record_success(timeout)
                return result

            result = (False, "无活跃连接")
            if self.network_cache:
                self.network_cache.set("check_connection", result, self.tunnel_name)
            return result

        except Exception as e:
            error_msg = f"解析连接信息失败：{e}"
            if self.network_cache:
                self.network_cache.set("check_connection", (None, error_msg), self.tunnel_name)
            return None, error_msg

    def comprehensive_health_check(self) -> bool:
        """
        综合健康检查
        返回: True 表示健康，False 表示异常
        """
        # 1. 检查进程是否运行
        try:
            result = subprocess.run(
                ["pgrep", "-f", f"tunnel.*run.*{self.tunnel_name}"],
                capture_output=True,
                timeout=5,
            )
            if result.returncode != 0:
                return False
        except Exception:
            # pgrep 可能不可用，跳过进程检查
            pass

        # 2. 检查连接
        connected, msg = self.check_tunnel_connection()

        if connected is None:
            # 网络/API 异常，记录但不触发重启
            self.failure_history.append({
                "time": datetime.now(),
                "type": "network_error",
                "message": msg,
            })
            return True  # 认为健康（避免误杀）

        if connected:
            # 连接正常，清除失败计数
            self.consecutive_failures = 0
            return True

        # 连接失败
        self.consecutive_failures += 1
        self.failure_history.append({
            "time": datetime.now(),
            "type": "connection_failure",
            "message": msg,
        })

        # 只有连续失败多次才认为真正异常
        return self.consecutive_failures < 2

    def restart_tunnel(self, attempt: int = 0) -> bool:
        """带指数退避的隧道重启"""
        if attempt >= self.max_restart_attempts:
            return False

        # 检查冷却时间
        current_time = time.time()
        if current_time - self.last_restart_time < self.restart_cooldown and attempt == 0:
            return False

        # 计算退避时间
        backoff_delay = min((2 ** attempt) * 10, 300)
        if attempt > 0:
            time.sleep(backoff_delay)

        # 清空缓存以获取最新连接状态
        if self.network_cache:
            self.network_cache.clear()

        # 执行重启
        try:
            # 停止现有进程
            subprocess.run(
                ["pkill", "-f", f"tunnel.*run.*{self.tunnel_name}"],
                timeout=10,
            )
            time.sleep(2)

            # 启动新进程
            subprocess.Popen(
                [self.cloudflared_path, "tunnel", "run", self.tunnel_name],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

            self.last_restart_time = current_time
            self.consecutive_failures = 0
            return True

        except Exception as e:
            # 重启失败，继续重试
            if attempt < self.max_restart_attempts - 1:
                return self.restart_tunnel(attempt + 1)
            return False

    def monitor_loop(self):
        """主监控循环"""
        print(f"[{self.tunnel_name}] 开始监控，检查间隔 {self.check_interval} 秒")

        try:
            while True:
                # 执行健康检查
                if not self.comprehensive_health_check():
                    print(f"[{self.tunnel_name}] 隧道异常，准备重启...")
                    self.restart_tunnel()

                time.sleep(self.check_interval)

        except KeyboardInterrupt:
            print(f"[{self.tunnel_name}] 监控已停止")


def main():
    """主函数"""
    if len(sys.argv) < 2:
        print("用法: python network_connection_optimizer.py <cloudflared_path> [tunnel_name]")
        sys.exit(1)

    cloudflared_path = sys.argv[1]
    tunnel_name = sys.argv[2] if len(sys.argv) > 2 else "homepage"

    monitor = ImprovedTunnelMonitor(
        cloudflared_path=cloudflared_path,
        tunnel_name=tunnel_name,
    )
    monitor.monitor_loop()


if __name__ == "__main__":
    main()
