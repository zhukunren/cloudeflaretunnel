from __future__ import annotations

from pathlib import Path

try:
    from .. import cloudflared_cli as cf
except (ImportError, ValueError):
    import cloudflared_cli as cf  # type: ignore


class TunnelConfigService:
    """Shared config-file operations used by catalog and lifecycle flows."""

    def ensure_start_config(self, tunnel_name: str, tunnel_id: str, config_path: Path) -> dict:
        payload = {"ok": True, "messages": [], "warnings": []}
        try:
            if not config_path.exists():
                cf.write_basic_config(config_path, tunnel_name, tunnel_id)
                payload["messages"].append("已生成默认配置文件")
                return payload

            if cf.validate_tunnel_config(config_path, tunnel_id):
                return payload

            payload["warnings"].append("检测到配置文件 UUID 不匹配，正在更新...")
            if cf.update_config_tunnel_id(config_path, tunnel_id):
                payload["messages"].append(f"配置文件 UUID 已更新为: {tunnel_id}")
                return payload

            payload["warnings"].append("更新配置文件失败，正在重新生成配置文件...")
            cf.write_basic_config(config_path, tunnel_name, tunnel_id)
            payload["messages"].append("已重新生成配置文件")
            return payload
        except Exception as exc:
            payload.update({"ok": False, "error": str(exc)})
            return payload

    def sync_existing_config(self, tunnel_name: str, tunnel_id: str, config_path: Path) -> tuple[str | None, str | None]:
        if not config_path.exists():
            return None, None
        if cf.validate_tunnel_config(config_path, tunnel_id):
            return None, None
        if cf.update_config_tunnel_id(config_path, tunnel_id):
            return f"已同步隧道 {tunnel_name} 的配置文件 UUID", None
        return None, f"同步隧道 {tunnel_name} 的配置文件 UUID 失败"

    def normalize_and_validate(self, config_path: Path) -> dict:
        payload = {"ok": True, "warnings": [], "hostnames": []}
        try:
            normalized, changes = cf.normalize_local_service_protocols(config_path)
        except Exception:
            normalized, changes = False, []

        if normalized:
            payload["warnings"].append("检测到本地服务协议与配置不一致，已自动修正")
            for detail in changes:
                payload["warnings"].append(f"  - {detail}")

        ok, msg = cf.validate_config(config_path)
        if not ok:
            payload.update({"ok": False, "error": msg})
            return payload

        payload["hostnames"] = cf.extract_hostnames(config_path)
        return payload
