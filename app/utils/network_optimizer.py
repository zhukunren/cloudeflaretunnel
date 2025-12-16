#!/usr/bin/env python3
"""
网络连接优化模块
- 指数退避重试机制
- 智能超时管理
- 连接状态缓存
- 网络异常诊断
"""

import time
import json
import subprocess
from datetime import datetime, timedelta
from typing import Optional, Callable, Any
from pathlib import Path
import hashlib


class RetryConfig:
    """重试配置"""
    def __init__(
        self,
        max_attempts: int = 3,
        initial_delay: float = 0.5,
        max_delay: float = 30.0,
        backoff_factor: float = 2.0,
        jitter: bool = True,
    ):
        self.max_attempts = max_attempts
        self.initial_delay = initial_delay
        self.max_delay = max_delay
        self.backoff_factor = backoff_factor
        self.jitter = jitter

    def get_delay(self, attempt: int) -> float:
        """计算第 N 次尝试的延迟时间（指数退避）"""
        delay = min(
            self.initial_delay * (self.backoff_factor ** attempt),
            self.max_delay
        )

        if self.jitter:
            import random
            # 添加随机抖动 (0.8x ~ 1.2x)
            delay *= (0.8 + random.random() * 0.4)

        return delay


class TimeoutConfig:
    """超时配置"""
    def __init__(
        self,
        default_timeout: float = 10.0,
        api_timeout: float = 15.0,
        health_check_timeout: float = 5.0,
    ):
        self.default_timeout = default_timeout
        self.api_timeout = api_timeout
        self.health_check_timeout = health_check_timeout


class NetworkCache:
    """网络调用结果缓存，降低 API 调用频率"""
    def __init__(self, cache_dir: Path | None = None, ttl_seconds: int = 60):
        self.cache_dir = cache_dir or Path.home() / ".cache" / "cloudflare-tunnel"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.ttl_seconds = ttl_seconds
        self._memory_cache = {}  # 运行时内存缓存

    def _get_cache_key(self, operation: str, *args) -> str:
        """生成缓存键"""
        key_parts = [operation] + [str(arg) for arg in args]
        key_str = "|".join(key_parts)
        return hashlib.md5(key_str.encode()).hexdigest()

    def _get_cache_file(self, cache_key: str) -> Path:
        return self.cache_dir / f"{cache_key}.json"

    def get(self, operation: str, *args) -> Optional[Any]:
        """获取缓存数据"""
        cache_key = self._get_cache_key(operation, *args)

        # 先查内存缓存
        if cache_key in self._memory_cache:
            entry = self._memory_cache[cache_key]
            if entry["expired_at"] > datetime.now():
                return entry["data"]
            else:
                del self._memory_cache[cache_key]

        # 再查文件缓存
        cache_file = self._get_cache_file(cache_key)
        if cache_file.exists():
            try:
                data = json.loads(cache_file.read_text())
                expired_at = datetime.fromisoformat(data.get("expired_at", ""))
                if expired_at > datetime.now():
                    return data.get("result")
            except Exception:
                cache_file.unlink(missing_ok=True)

        return None

    def set(self, operation: str, result: Any, *args) -> None:
        """设置缓存数据"""
        cache_key = self._get_cache_key(operation, *args)
        expired_at = datetime.now() + timedelta(seconds=self.ttl_seconds)

        # 存内存缓存
        self._memory_cache[cache_key] = {
            "data": result,
            "expired_at": expired_at,
        }

        # 存文件缓存
        cache_file = self._get_cache_file(cache_key)
        try:
            cache_file.write_text(json.dumps({
                "result": result,
                "expired_at": expired_at.isoformat(),
                "operation": operation,
            }))
        except Exception:
            pass  # 缓存失败不影响主逻辑

    def clear(self) -> None:
        """清空所有缓存"""
        self._memory_cache.clear()
        for f in self.cache_dir.glob("*.json"):
            f.unlink(missing_ok=True)


class NetworkDiagnostics:
    """网络诊断工具"""

    @staticmethod
    def classify_error(error_msg: str) -> str:
        """分类错误类型"""
        lower = error_msg.lower()

        # 网络连接类错误
        if any(k in lower for k in ["timeout", "timed out", "deadline exceeded"]):
            return "timeout"
        if any(k in lower for k in ["tls handshake", "tls error"]):
            return "tls_error"
        if any(k in lower for k in ["connection refused", "no route"]):
            return "connection_refused"
        if any(k in lower for k in ["eof", "broken pipe", "reset"]):
            return "connection_reset"

        # API 错误
        if any(k in lower for k in ["api call", "rest request failed"]):
            if any(k in lower for k in ["status 5", "502", "503", "500"]):
                return "api_server_error"
            return "api_error"

        # 服务可用性
        if any(k in lower for k in ["service unavailable", "overloaded"]):
            return "service_unavailable"

        # Cloudflare 边缘节点问题
        if any(k in lower for k in ["failed to dial to edge", "no free edge"]):
            return "edge_unavailable"

        return "unknown"

    @staticmethod
    def should_retry_on_error(error_msg: str, attempt: int, max_attempts: int) -> bool:
        """判断是否应该重试"""
        error_type = NetworkDiagnostics.classify_error(error_msg)

        # 不应该重试的错误
        if error_type in ["api_server_error", "service_unavailable"]:
            # 服务故障不应该频繁重试
            return attempt < 1  # 最多重试 1 次

        # 可以重试的错误
        if error_type in ["timeout", "connection_reset"]:
            return attempt < max_attempts

        # 不明确的错误不重试
        return False

    @staticmethod
    def get_retry_delay_multiplier(error_type: str) -> float:
        """根据错误类型调整重试延迟倍数"""
        multipliers = {
            "timeout": 1.5,  # 超时延迟更长
            "tls_error": 2.0,  # TLS 错误延迟更长
            "connection_refused": 2.0,
            "api_server_error": 3.0,  # API 故障最长延迟
            "edge_unavailable": 2.0,
        }
        return multipliers.get("timeout", 1.0)


class RetryableOperation:
    """可重试的操作封装"""

    def __init__(self, retry_config: RetryConfig | None = None):
        self.retry_config = retry_config or RetryConfig()

    def execute(
        self,
        operation: Callable,
        *args,
        timeout: float | None = None,
        operation_name: str = "operation",
        **kwargs
    ) -> tuple[bool, Optional[Any], str]:
        """
        执行可重试的操作

        返回: (成功, 结果, 错误消息)
        """
        last_error = None

        for attempt in range(self.retry_config.max_attempts):
            try:
                result = operation(*args, timeout=timeout, **kwargs)
                return True, result, ""
            except subprocess.TimeoutExpired as e:
                last_error = f"Operation timeout after {timeout}s: {e}"
                error_type = "timeout"
            except Exception as e:
                last_error = str(e)
                error_type = NetworkDiagnostics.classify_error(last_error)

            # 判断是否继续重试
            if not NetworkDiagnostics.should_retry_on_error(last_error, attempt, self.retry_config.max_attempts):
                break

            if attempt < self.retry_config.max_attempts - 1:
                delay = self.retry_config.get_delay(attempt)
                multiplier = NetworkDiagnostics.get_retry_delay_multiplier(error_type)
                actual_delay = delay * multiplier
                time.sleep(actual_delay)

        return False, None, last_error


class AdaptiveTimeout:
    """自适应超时管理"""

    def __init__(self):
        self.success_times = []
        self.failure_times = []
        self.max_history = 20

    def record_success(self, elapsed_time: float) -> None:
        """记录成功耗时"""
        self.success_times.append(elapsed_time)
        if len(self.success_times) > self.max_history:
            self.success_times.pop(0)

    def record_failure(self, elapsed_time: float) -> None:
        """记录失败耗时"""
        self.failure_times.append(elapsed_time)
        if len(self.failure_times) > self.max_history:
            self.failure_times.pop(0)

    def get_recommended_timeout(self, base_timeout: float = 10.0) -> float:
        """推荐超时时间"""
        if not self.success_times:
            return base_timeout

        # 使用成功耗时的 P95 + 50% 余量
        success_times = sorted(self.success_times)
        p95_idx = int(len(success_times) * 0.95)
        p95_time = success_times[p95_idx] if p95_idx < len(success_times) else success_times[-1]

        recommended = p95_time * 1.5
        return max(base_timeout * 0.5, min(recommended, base_timeout * 2))


# 全局实例
_network_cache = NetworkCache()
_adaptive_timeout = AdaptiveTimeout()


def get_network_cache() -> NetworkCache:
    """获取全局网络缓存实例"""
    return _network_cache


def get_adaptive_timeout() -> AdaptiveTimeout:
    """获取自适应超时实例"""
    return _adaptive_timeout