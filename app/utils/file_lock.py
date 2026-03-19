#! -*- coding: utf-8 -*-
"""
轻量级跨平台文件锁，避免多进程/多线程同时读写同一文件。
优先使用 fcntl/msvcrt，缺失时降级为最佳努力的空锁。
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from pathlib import Path

try:
    import fcntl  # type: ignore

    _HAS_FCNTL = True
except Exception:  # pragma: no cover - Windows/无法导入时
    _HAS_FCNTL = False

try:
    import msvcrt  # type: ignore

    _HAS_MSVCRT = True
except Exception:  # pragma: no cover - 非 Windows
    _HAS_MSVCRT = False


class FileLock:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._fh = None

    def acquire(self, timeout: float = 2.0, poll_interval: float = 0.05) -> bool:
        """
        尝试获取锁。返回是否成功。
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fh = open(self.path, "a+b")
        start = time.time()

        while True:
            try:
                if _HAS_FCNTL:
                    fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                elif _HAS_MSVCRT:
                    # msvcrt 需要指定长度，取 1 字节占位即可
                    fh.seek(0)
                    msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
                # 若无可用锁机制，直接继续（降级为无锁模式）
                self._fh = fh
                return True
            except BlockingIOError:
                if timeout is not None and time.time() - start >= timeout:
                    fh.close()
                    return False
                time.sleep(poll_interval)
            except OSError:
                fh.close()
                return False

    def release(self):
        fh = self._fh
        if not fh:
            return
        try:
            if _HAS_FCNTL:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            elif _HAS_MSVCRT:
                try:
                    fh.seek(0)
                    msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
                except Exception:
                    pass
        finally:
            try:
                fh.close()
            finally:
                self._fh = None

    @contextmanager
    def locked(self, timeout: float = 2.0, poll_interval: float = 0.05):
        acquired = self.acquire(timeout=timeout, poll_interval=poll_interval)
        try:
            yield acquired
        finally:
            if acquired:
                self.release()

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.release()
