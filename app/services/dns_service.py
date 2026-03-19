from __future__ import annotations

try:
    from .. import cloudflared_cli as cf
except (ImportError, ValueError):
    import cloudflared_cli as cf  # type: ignore


class DnsRouteService:
    """Application service for manual and pre-start DNS route handling."""

    def validate_hostname(self, hostname: str) -> str | None:
        return cf.validate_ingress_hostname(hostname)

    def route_hostname(self, cloudflared_path: str, tunnel_name: str, hostname: str) -> tuple[bool, str]:
        return cf.route_dns(cloudflared_path, tunnel_name, hostname)

    def ensure_routes(self, cloudflared_path: str, tunnel_name: str, hostnames: list[str]) -> dict:
        payload = {"ok": True, "messages": [], "warnings": []}
        if not hostnames:
            payload["warnings"].append("配置未设置 hostname，已跳过 DNS 路由检查，将按当前配置启动。")
            return payload

        for hostname in hostnames:
            ok, out = self.route_hostname(cloudflared_path, tunnel_name, hostname)
            if ok:
                payload["messages"].append(f"DNS 路由已配置: {hostname}")
                continue
            if "already exists" in out:
                payload["warnings"].append(f"DNS 记录已存在: {hostname}")
                continue
            payload.update({"ok": False, "hostname": hostname, "error": out})
            return payload
        return payload
