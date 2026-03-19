from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

try:
    from .. import cloudflared_cli as cf
except (ImportError, ValueError):
    import cloudflared_cli as cf  # type: ignore


@dataclass(frozen=True)
class OriginCertStatus:
    exists: bool
    path: Path | None
    updated: str | None


class AuthService:
    """Application service for Cloudflare authentication flows."""

    def get_origin_cert_status(self, custom_path: str | Path | None = None) -> OriginCertStatus:
        exists, path, updated = cf.origin_cert_status(custom_path)
        return OriginCertStatus(exists=exists, path=path, updated=updated)

    def find_origin_cert(self, custom_path: str | Path | None = None) -> Path | None:
        return cf.find_origin_cert(custom_path)

    def delete_origin_cert(self, cert_path: Path) -> tuple[bool, str]:
        try:
            cert_path.unlink()
            return True, f"已删除旧认证文件: {cert_path}"
        except Exception as exc:
            return False, f"无法删除认证文件：{exc}"

    def start_login(self, cloudflared_path: str) -> tuple[bool, str]:
        try:
            cf.login(cloudflared_path)
            return True, "已启动登录流程，请在浏览器中完成授权。"
        except cf.CloudflaredBinaryError as exc:
            return False, str(exc)
