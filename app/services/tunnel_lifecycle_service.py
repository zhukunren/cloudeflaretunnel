from __future__ import annotations

import subprocess
import time
from pathlib import Path

try:
    from .. import cloudflared_cli as cf
    from .dns_service import DnsRouteService
    from .tunnel_operation_service import TunnelOperationService
    from .tunnel_config_service import TunnelConfigService
except (ImportError, ValueError):
    import cloudflared_cli as cf  # type: ignore
    from services.dns_service import DnsRouteService  # type: ignore
    from services.tunnel_operation_service import TunnelOperationService  # type: ignore
    from services.tunnel_config_service import TunnelConfigService  # type: ignore


class TunnelLifecycleService:
    """Application service for direct tunnel start/stop preparation and launch."""

    def __init__(
        self,
        dns_service: DnsRouteService | None = None,
        config_service: TunnelConfigService | None = None,
        operation_service: TunnelOperationService | None = None,
    ):
        self.dns_service = dns_service or DnsRouteService()
        self.config_service = config_service or TunnelConfigService()
        self.operation_service = operation_service or TunnelOperationService()

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

    def start_direct_tunnel(
        self,
        cloudflared_path: str,
        tunnel_name: str,
        tunnel_id: str,
        config_path: Path,
        capture_output: bool,
        log_file: Path | None,
    ) -> dict:
        payload = self.operation_service.new_start_result(tunnel_name, "gui")

        cleaned, msg, error = self.cleanup_residual_tunnel(tunnel_name)
        if cleaned and msg:
            payload["messages"].append(f"启动前清理残留隧道: {msg}")
        if error:
            payload["warnings"].append(f"清理残留隧道异常: {error}")

        config_result = self.prepare_start_config(tunnel_name, tunnel_id, config_path)
        payload["messages"].extend(config_result.get("messages", []))
        payload["warnings"].extend(config_result.get("warnings", []))
        if not config_result.get("ok"):
            message = str(config_result.get("error") or "配置处理失败").strip()
            payload.update(
                {
                    "ok": False,
                    "stage": "config",
                    "message": message,
                    "summary": message,
                    "error": message,
                }
            )
            return payload

        validate_result = self.normalize_and_validate_config(config_path)
        payload["warnings"].extend(validate_result.get("warnings", []))
        hostnames = list(validate_result.get("hostnames", []) or [])
        payload["hostnames"] = hostnames
        if not validate_result.get("ok"):
            message = str(validate_result.get("error") or "配置校验失败").strip()
            payload.update(
                {
                    "ok": False,
                    "stage": "config",
                    "message": message,
                    "summary": message,
                    "error": message,
                }
            )
            return payload

        dns_result = self.ensure_dns_routes(cloudflared_path, tunnel_name, hostnames)
        payload["messages"].extend(dns_result.get("messages", []))
        payload["warnings"].extend(dns_result.get("warnings", []))
        if not dns_result.get("ok"):
            message = str(dns_result.get("error") or "DNS 路由失败").strip()
            payload.update(
                {
                    "ok": False,
                    "stage": "dns",
                    "hostname": dns_result.get("hostname"),
                    "message": message,
                    "summary": message,
                    "error": message,
                }
            )
            return payload

        launch = self.launch_tunnel(
            cloudflared_path,
            tunnel_name,
            config_path,
            capture_output,
            log_file,
        )
        return self.operation_service.build_direct_start_result(tunnel_name, launch, payload)

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
