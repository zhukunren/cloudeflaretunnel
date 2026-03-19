from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

try:
    from .. import cloudflared_cli as cf
    from ..utils.paths import get_repo_root
except (ImportError, ValueError):
    import cloudflared_cli as cf  # type: ignore
    from utils.paths import get_repo_root  # type: ignore


@dataclass(frozen=True)
class CloudflaredDownloadResult:
    ok: bool
    message: str
    version: str | None
    target_path: Path


@dataclass(frozen=True)
class CloudflaredVersionInfo:
    installed: bool
    version: str | None
    display_text: str
    short_version: str | None = None


class CloudflaredBinaryService:
    """Binary discovery, version inspection, and download/update flows."""

    def __init__(self, project_root: Path | None = None):
        self.project_root = Path(project_root) if project_root else get_repo_root()

    def is_windows(self) -> bool:
        return bool(cf._is_windows())

    def selectable_filetypes(self) -> list[tuple[str, str]]:
        if self.is_windows():
            return [("可执行文件", "*.exe"), ("所有文件", "*.*")]
        return [("所有文件", "*")]

    def resolve_path(self, preferred_path: str | None = None) -> str | None:
        return cf.find_cloudflared(preferred_path)

    def download_target_path(self) -> Path:
        filename = "cloudflared.exe" if self.is_windows() else "cloudflared"
        return self.project_root / filename

    def version_info(self, cloudflared_path: str | None) -> CloudflaredVersionInfo:
        if not cloudflared_path:
            return CloudflaredVersionInfo(False, None, "Cloudflared: 未安装")

        version = cf.version(cloudflared_path)
        if not version:
            return CloudflaredVersionInfo(False, None, "Cloudflared: 版本未知")

        short_version = version.split("(")[0].strip() if "(" in version else version.strip()
        return CloudflaredVersionInfo(
            installed=True,
            version=version,
            short_version=short_version,
            display_text=f"Cloudflared: {short_version}",
        )

    def download_binary(self, progress_cb: Callable[[int], None] | None = None) -> CloudflaredDownloadResult:
        target_path = self.download_target_path()
        ok, message, version = cf.download_cloudflared(target_path, progress_cb=progress_cb)
        return CloudflaredDownloadResult(ok=ok, message=message, version=version, target_path=target_path)
