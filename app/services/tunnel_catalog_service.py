from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

try:
    from .. import cloudflared_cli as cf
    from .tunnel_config_service import TunnelConfigService
    from ..utils.paths import get_repo_root
except (ImportError, ValueError):
    import cloudflared_cli as cf  # type: ignore
    from services.tunnel_config_service import TunnelConfigService  # type: ignore
    from utils.paths import get_repo_root  # type: ignore


@dataclass(frozen=True)
class TunnelCatalogLoadResult:
    ok: bool
    source: str
    tunnels: list[dict] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    error: str | None = None


@dataclass(frozen=True)
class TunnelCatalogMutationResult:
    ok: bool
    message: str
    detail: str = ""
    warnings: list[str] = field(default_factory=list)
    error: str | None = None


class TunnelCatalogService:
    """Application service for listing, syncing, creating, and deleting tunnels."""

    def __init__(self, project_root: Path | None = None, config_service: TunnelConfigService | None = None):
        self.project_root = Path(project_root) if project_root else get_repo_root()
        self.tunnels_dir = self.project_root / "tunnels"
        self.config_service = config_service or TunnelConfigService()

    def config_path_for(self, tunnel_name: str) -> Path:
        return self.tunnels_dir / tunnel_name / "config.yml"

    def load_tunnels(self, cloudflared_path: str) -> TunnelCatalogLoadResult:
        data: list[dict] = []
        error_msg: str | None = None

        try:
            result = cf.list_tunnels(cloudflared_path, return_error=True, timeout=15)
            if isinstance(result, tuple):
                data, error_msg = result
            else:
                data, error_msg = result, None
        except cf.CloudflaredBinaryError as exc:
            return TunnelCatalogLoadResult(
                ok=False,
                source="binary-error",
                error=str(exc),
            )
        except Exception as exc:
            error_msg = str(exc)

        messages: list[str] = []
        warnings: list[str] = []

        if not data:
            local_tunnels = cf.load_local_tunnels(self.project_root)
            if local_tunnels:
                sync_messages, sync_warnings = self._sync_tunnel_configs(local_tunnels)
                if error_msg:
                    warnings.append(f"无法访问 Cloudflare API: {error_msg}")
                warnings.append("已切换为本地配置的隧道列表（离线模式）。")
                messages.extend(sync_messages)
                warnings.extend(sync_warnings)
                return TunnelCatalogLoadResult(
                    ok=True,
                    source="offline",
                    tunnels=local_tunnels,
                    messages=messages,
                    warnings=warnings,
                )

            return TunnelCatalogLoadResult(
                ok=False,
                source="error",
                error=error_msg or "未获取到任何隧道数据",
            )

        sync_messages, sync_warnings = self._sync_tunnel_configs(data)
        messages.extend(sync_messages)
        warnings.extend(sync_warnings)
        return TunnelCatalogLoadResult(
            ok=True,
            source="online",
            tunnels=data,
            messages=messages,
            warnings=warnings,
        )

    def create_tunnel(
        self,
        cloudflared_path: str,
        tunnel_name: str,
        origin_cert: str | Path | None,
    ) -> TunnelCatalogMutationResult:
        ok, output = cf.create_tunnel(cloudflared_path, tunnel_name, origin_cert)
        detail = str(output or "").strip()
        if ok:
            return TunnelCatalogMutationResult(
                ok=True,
                message=f"隧道 {tunnel_name} 创建成功",
                detail=detail,
            )

        return TunnelCatalogMutationResult(
            ok=False,
            message=f"隧道 {tunnel_name} 创建失败",
            detail=detail,
            error=detail or "创建失败",
        )

    def delete_tunnel(self, cloudflared_path: str, tunnel_name: str) -> TunnelCatalogMutationResult:
        ok, output = cf.delete_tunnel(cloudflared_path, tunnel_name)
        detail = str(output or "").strip()
        warnings: list[str] = []

        if not ok:
            return TunnelCatalogMutationResult(
                ok=False,
                message=f"隧道 {tunnel_name} 删除失败",
                detail=detail,
                error=detail or "删除失败",
            )

        config_dir = self.tunnels_dir / tunnel_name
        if config_dir.exists():
            try:
                shutil.rmtree(config_dir)
            except Exception as exc:
                warnings.append(f"删除配置目录失败: {exc}")

        return TunnelCatalogMutationResult(
            ok=True,
            message=f"隧道 {tunnel_name} 已删除",
            detail=detail,
            warnings=warnings,
        )

    def _sync_tunnel_configs(self, tunnels: list[dict]) -> tuple[list[str], list[str]]:
        messages: list[str] = []
        warnings: list[str] = []

        for tunnel in tunnels:
            name = tunnel.get("name", "")
            tunnel_id = cf.extract_tunnel_id(tunnel)
            if not (name and tunnel_id):
                continue

            config_path = self.config_path_for(name)
            if not config_path.exists():
                continue
            message, warning = self.config_service.sync_existing_config(name, tunnel_id, config_path)
            if message:
                messages.append(message)
            if warning:
                warnings.append(warning)

        return messages, warnings
