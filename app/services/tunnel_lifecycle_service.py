from __future__ import annotations

import subprocess
import time
from pathlib import Path

try:
    from .. import cloudflared_cli as cf
    from .dns_service import DnsRouteService
except (ImportError, ValueError):
    import cloudflared_cli as cf  # type: ignore
    from services.dns_service import DnsRouteService  # type: ignore


class TunnelLifecycleService:
    """Application service for direct tunnel start/stop preparation and launch."""

    def __init__(self, dns_service: DnsRouteService | None = None):
        self.dns_service = dns_service or DnsRouteService()

    def cleanup_residual_tunnel(self, tunnel_name: str) -> tuple[bool, str | None, str | None]:
        try:
            cleaned, msg = cf.kill_tunnel_by_name(tunnel_name)
            return cleaned, msg, None
        except Exception as exc:
            return False, None, str(exc)

    def prepare_start_config(self, tunnel_name: str, tunnel_id: str, config_path: Path) -> dict:
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

    def normalize_and_validate_config(self, config_path: Path) -> dict:
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

    def ensure_dns_routes(self, cloudflared_path: str, tunnel_name: str, hostnames: list[str]) -> dict:
        return self.dns_service.ensure_routes(cloudflared_path, tunnel_name, hostnames)

    def launch_tunnel(
        self,
        cloudflared_path: str,
        tunnel_name: str,
        config_path: Path,
        capture_output: bool,
        log_file: Path | None,
        *,
        health_timeout: int = 20,
        max_wait_seconds: int = 12,
        metrics_address: str | None = None,
        env_overrides: dict[str, str] | None = None,
    ) -> dict:
        last_detail = ""
        last_unknown_detail = ""
        cfg_protocol = (cf.get_config_protocol(config_path) or "").lower() or None
        protocol_candidates: list[tuple[str | None, str]] = [(cfg_protocol, cfg_protocol or "默认")]
        if cfg_protocol != "http2":
            protocol_candidates.append(("http2", "http2"))

        for proto, label in protocol_candidates:
            try:
                proc = cf.run_tunnel(
                    cloudflared_path,
                    tunnel_name,
                    config_path,
                    capture_output=capture_output,
                    log_file=log_file,
                    protocol=proto,
                    metrics_address=metrics_address,
                    env_overrides=env_overrides,
                )
            except cf.TunnelCredentialsError as exc:
                return {"ok": False, "error": str(exc), "error_type": "credentials"}
            except Exception as exc:
                last_detail = str(exc)
                continue

            unknown_seen = False
            for idx in range(max_wait_seconds):
                time.sleep(1)
                if proc.poll() is not None:
                    output_text = ""
                    if getattr(proc, "stdout", None):
                        try:
                            output_text, _ = proc.communicate(timeout=0.2)
                        except Exception:
                            output_text = ""
                    if output_text:
                        tail = "\n".join((output_text.strip().splitlines() or [])[-40:])
                        last_detail = f"cloudflared 退出码 {proc.returncode}\n{tail}"
                    else:
                        last_detail = f"cloudflared 退出码 {proc.returncode}"
                    break

                if idx % 2 == 1:
                    ok, detail = cf.test_connection(cloudflared_path, tunnel_name, timeout=health_timeout)
                    last_detail = detail
                    if ok is True:
                        return {
                            "ok": True,
                            "proc": proc,
                            "detail": detail,
                            "protocol": label,
                            "log_file": log_file,
                            "capture_output": capture_output,
                        }
                    if ok is None:
                        unknown_seen = True
                        last_unknown_detail = detail
                        continue

            if unknown_seen and proc.poll() is None:
                return {
                    "ok": True,
                    "proc": proc,
                    "detail": last_unknown_detail or "健康检查未得出结论（Cloudflare API 无响应），保持进程运行",
                    "protocol": label,
                    "log_file": log_file,
                    "capture_output": capture_output,
                }

            cf.stop_process(proc)

        return {"ok": False, "error": last_detail or last_unknown_detail or "未检测到活跃连接"}

    def stop_tunnel(self, tunnel_name: str, proc: subprocess.Popen | None) -> dict:
        try:
            if proc and proc.poll() is None:
                cf.stop_process(proc)
                return {"mode": "direct", "ok": True, "method": "proc", "pid": proc.pid}

            ok, msg = cf.kill_tunnel_by_name(tunnel_name)
            return {"mode": "direct", "ok": ok, "method": "kill", "message": msg}
        except Exception as exc:
            return {"mode": "direct", "ok": False, "method": "exception", "error": str(exc)}
