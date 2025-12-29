#! -*- coding: utf-8 -*-
"""
增强的日志管理系统
"""
from datetime import datetime
from enum import Enum
from typing import Callable, Optional
from pathlib import Path

from .paths import get_logs_dir


class LogLevel(Enum):
    """日志级别"""
    DEBUG = 0
    INFO = 1
    WARNING = 2
    ERROR = 3


class LogManager:
    """日志管理器"""

    def __init__(self, max_lines: int = 1000, save_to_file: bool = False, log_dir: Optional[Path] = None):
        self.max_lines = max_lines
        self.save_to_file = save_to_file
        self.log_dir = log_dir or get_logs_dir()
        self.current_level = LogLevel.INFO
        self._log_buffer: list[tuple[datetime, LogLevel, str]] = []
        self._callbacks: list[Callable] = []

        if save_to_file:
            self.log_dir.mkdir(parents=True, exist_ok=True)

    def set_level(self, level: LogLevel):
        """设置日志级别"""
        self.current_level = level

    def add_callback(self, callback: Callable):
        """添加日志回调函数"""
        if callback not in self._callbacks:
            self._callbacks.append(callback)

    def remove_callback(self, callback: Callable):
        """移除日志回调函数"""
        if callback in self._callbacks:
            self._callbacks.remove(callback)

    def _should_log(self, level: LogLevel) -> bool:
        """判断是否应该记录日志"""
        return level.value >= self.current_level.value

    def _add_to_buffer(self, level: LogLevel, message: str):
        """添加到日志缓冲区"""
        timestamp = datetime.now()
        self._log_buffer.append((timestamp, level, message))

        # 限制缓冲区大小
        if len(self._log_buffer) > self.max_lines:
            self._log_buffer = self._log_buffer[-self.max_lines:]

        # 保存到文件
        if self.save_to_file:
            self._save_to_file(timestamp, level, message)

        # 触发回调
        for callback in self._callbacks:
            try:
                callback(timestamp, level, message)
            except Exception:
                pass

    def _save_to_file(self, timestamp: datetime, level: LogLevel, message: str):
        """保存日志到文件"""
        try:
            log_file = self.log_dir / f"tunnel_{timestamp.strftime('%Y%m%d')}.log"
            log_entry = f"[{timestamp.strftime('%Y-%m-%d %H:%M:%S')}] [{level.name}] {message}\n"
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(log_entry)
        except Exception:
            pass

    def debug(self, message: str):
        """记录调试日志"""
        if self._should_log(LogLevel.DEBUG):
            self._add_to_buffer(LogLevel.DEBUG, message)

    def info(self, message: str):
        """记录信息日志"""
        if self._should_log(LogLevel.INFO):
            self._add_to_buffer(LogLevel.INFO, message)

    def warning(self, message: str):
        """记录警告日志"""
        if self._should_log(LogLevel.WARNING):
            self._add_to_buffer(LogLevel.WARNING, message)

    def error(self, message: str):
        """记录错误日志"""
        if self._should_log(LogLevel.ERROR):
            self._add_to_buffer(LogLevel.ERROR, message)

    def get_logs(self, level: Optional[LogLevel] = None, limit: Optional[int] = None) -> list[tuple]:
        """获取日志记录"""
        logs = self._log_buffer
        if level is not None:
            logs = [log for log in logs if log[1] == level]
        if limit:
            logs = logs[-limit:]
        return logs

    def clear(self):
        """清空日志缓冲区"""
        self._log_buffer.clear()

    def export_to_string(self) -> str:
        """导出日志为字符串"""
        lines = []
        for timestamp, level, message in self._log_buffer:
            time_str = timestamp.strftime('%H:%M:%S')
            lines.append(f"[{time_str}] [{level.name}] {message}")
        return "\n".join(lines)

    def get_stats(self) -> dict:
        """获取日志统计信息"""
        stats = {level: 0 for level in LogLevel}
        for _, level, _ in self._log_buffer:
            stats[level] += 1
        return {
            "total": len(self._log_buffer),
            "debug": stats[LogLevel.DEBUG],
            "info": stats[LogLevel.INFO],
            "warning": stats[LogLevel.WARNING],
            "error": stats[LogLevel.ERROR]
        }
