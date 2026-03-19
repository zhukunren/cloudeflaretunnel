from __future__ import annotations

import time
from subprocess import Popen

try:
    from .. import cloudflared_cli as cf
    from .cloudflared_binary_service import CloudflaredBinaryService
except (ImportError, ValueError):
    import cloudflared_cli as cf  # type: ignore
    from services.cloudflared_binary_service import CloudflaredBinaryService  # type: ignore


class TunnelRuntimeService:
    """Runtime probes and process operations shared by GUI and background flows."""

    def __init__(self, binary_service: CloudflaredBinaryService | None = None):
        self.binary_service = binary_service or CloudflaredBinaryService()

    def resolve_cloudflared_path(self, preferred_path: str | None = None) -> str | None:
        return self.binary_service.resolve_path(preferred_path)

    def extract_tunnel_id(self, tunnel_item: dict) -> str | None:
        return cf.extract_tunnel_id(tunnel_item)

    def stop_process(self, proc: Popen, timeout: float = 5.0) -> None:
        cf.stop_process(proc, timeout=timeout)

    def test_connection(self, cloudflared_path: str, tunnel_name: str, timeout: int = 10) -> tuple[bool | None, str]:
        return cf.test_connection(cloudflared_path, tunnel_name, timeout=timeout)

    def get_health_status(
        self,
        tunnel_name: str,
        preferred_path: str | None,
        health_cache: dict[str, dict],
        *,
        ttl: int,
        timeout: int,
        force: bool = False,
    ) -> tuple[bool | None, str]:
        now = time.time()
        cached = health_cache.get(tunnel_name)
        if cached and not force and now - cached.get("ts", 0) < ttl:
            return cached.get("ok"), cached.get("detail", "")

        path = self.resolve_cloudflared_path(preferred_path)
        if not path:
            detail = "未配置 cloudflared 路径"
            health_cache[tunnel_name] = {"ok": None, "detail": detail, "ts": now}
            return None, detail

        ok, detail = self.test_connection(path, tunnel_name, timeout=timeout)
        health_cache[tunnel_name] = {"ok": ok, "detail": detail, "ts": now}
        return ok, detail

    def get_running_tunnels_with_health(
        self,
        preferred_path: str | None,
        health_cache: dict[str, dict],
        *,
        cache_ttl: int,
        timeout: int,
    ) -> list[dict]:
        cloudflared_path = self.resolve_cloudflared_path(preferred_path)
        running_tunnels = cf.get_running_tunnels()

        for tunnel in running_tunnels:
            tunnel_name = tunnel["name"]
            ok, detail = self.get_health_status(
                tunnel_name,
                cloudflared_path,
                health_cache,
                ttl=cache_ttl,
                timeout=timeout,
            )
            if ok is True:
                tunnel["healthy"] = True
            elif ok is False:
                tunnel["healthy"] = False
            else:
                tunnel["healthy"] = None
            if detail:
                tunnel["detail"] = detail
            tunnel["_health_ok"] = ok

        return running_tunnels
