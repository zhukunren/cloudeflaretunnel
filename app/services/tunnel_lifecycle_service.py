from __future__ import annotations

import subprocess
import time
from pathlib import Path

try:
    from .. import cloudflared_cli as cf
    from .dns_service import DnsRouteService
    from .tunnel_config_service import TunnelConfigService
except (ImportError, ValueError):
    import cloudflared_cli as cf  # type: ignore
    from services.dns_service import DnsRouteService  # type: ignore
    from services.tunnel_config_service import TunnelConfigService  # type: ignore


class TunnelLifecycleService:
    """Application service for direct tunnel start/stop preparation and launch."""

    def __init__(
        self,
        dns_service: DnsRouteService | None = None,
        config_service: TunnelConfigService | None = None,
    ):
        self.dns_service = dns_service or DnsRouteService()
        self.config_service = config_service or TunnelConfigService()

    def cleanup_residual_tunnel(self, tunnel_name: str) -> tuple[bool, str | None, str | None]:
        try:
            cleaned, msg = cf.kill_tunnel_by_name(tunnel_name)
            return cleaned, msg, None
        except Exception as exc:
            return False, None, str(exc)

    def prepare_start_config(self, tunnel_name: str, tunnel_id: str, config_path: Path) -> dict:
        return self.config_service.ensure_start_config(tunnel_name, tunnel_id, config_path)

    def normalize_and_validate_config(self, config_path: Path) -> dict:
        return self.config_service.normalize_and_validate(config_path)

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
                return {"ok": True, "method": "proc", "pid": proc.pid}

            ok, msg = cf.kill_tunnel_by_name(tunnel_name)
            return {"ok": ok, "method": "kill", "message": msg}
        except Exception as exc:
            return {"ok": False, "method": "exception", "error": str(exc)}
