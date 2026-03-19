from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

try:
    from .. import cloudflared_cli as cf
except (ImportError, ValueError):
    import cloudflared_cli as cf  # type: ignore


@dataclass(frozen=True)
class DiagnosticLine:
    text: str
    tag: str | None = None


class TunnelDiagnosticsService:
    """Build UI-agnostic tunnel diagnostic reports."""

    def build_report(
        self,
        cloudflared_path: str,
        tunnel_name: str,
        tunnel_id: str | None,
        config_path: Path,
        is_running: Callable[[str], bool],
    ) -> list[DiagnosticLine]:
        lines: list[DiagnosticLine] = []
        lines.extend(self._config_lines(config_path))
        config_valid = self._last_config_valid(lines)
        hostnames = cf.extract_hostnames(config_path)
        lines.extend(self._hostname_lines(hostnames, config_valid))
        lines.extend(self._connection_lines(cloudflared_path, tunnel_name))
        lines.extend(self._local_service_lines(config_path))
        lines.extend(self._credential_lines(tunnel_id))
        lines.extend(self._runtime_lines(tunnel_name, hostnames, is_running))
        return lines

    @staticmethod
    def _last_config_valid(lines: list[DiagnosticLine]) -> bool:
        for line in lines:
            if line.text.startswith("   ✓ "):
                return True
            if line.text.startswith("   ✗ "):
                return False
        return False

    def _config_lines(self, config_path: Path) -> list[DiagnosticLine]:
        lines = [DiagnosticLine("1. 验证配置文件...\n", "info")]
        if config_path.exists():
            ok, msg = cf.validate_config(config_path)
            lines.append(DiagnosticLine(f"   {'✓' if ok else '✗'} {msg}\n", "success" if ok else "error"))
        else:
            lines.append(DiagnosticLine("   ✗ 配置文件不存在\n", "error"))
            lines.append(DiagnosticLine("   请先编辑配置文件\n", "warning"))
        lines.append(DiagnosticLine("\n"))
        return lines

    def _hostname_lines(self, hostnames: list[str], config_valid: bool) -> list[DiagnosticLine]:
        lines = [DiagnosticLine("2. 检查 DNS 主机名...\n", "info")]
        if hostnames:
            for host in hostnames:
                lines.append(DiagnosticLine(f"   {'✓' if config_valid else '!'} {host}\n", "success" if config_valid else "warning"))
            if not config_valid:
                lines.append(DiagnosticLine("   ! 当前配置验证未通过，请先修复 hostname / ingress 配置\n", "warning"))
        else:
            lines.append(DiagnosticLine("   ✗ 未找到 hostname，请在 ingress 中配置\n", "error"))
        lines.append(DiagnosticLine("\n"))
        return lines

    def _connection_lines(self, cloudflared_path: str, tunnel_name: str) -> list[DiagnosticLine]:
        ok, msg = cf.test_connection(cloudflared_path, tunnel_name)
        return [
            DiagnosticLine("3. 测试隧道信息获取...\n", "info"),
            DiagnosticLine(f"   {'✓' if ok else '✗'} {msg}\n", "success" if ok else "error"),
            DiagnosticLine("\n"),
        ]

    def _local_service_lines(self, config_path: Path) -> list[DiagnosticLine]:
        lines = [DiagnosticLine("4. 测试本地服务...\n", "info")]
        if not config_path.exists():
            lines.append(DiagnosticLine("   跳过 - 配置文件缺失\n", "warning"))
            lines.append(DiagnosticLine("\n"))
            return lines

        services = cf.extract_http_services(config_path)
        if not services:
            lines.append(DiagnosticLine("   未找到 HTTP 服务配置\n", "warning"))
            lines.append(DiagnosticLine("\n"))
            return lines

        for service in services:
            ok, msg = cf.test_local_service(service)
            lines.append(DiagnosticLine(f"   测试 {service}...\n", "info"))
            lines.append(DiagnosticLine(f"   {'✓' if ok else '✗'} {msg}\n", "success" if ok else "error"))

        lines.append(DiagnosticLine("\n"))
        return lines

    def _credential_lines(self, tunnel_id: str | None) -> list[DiagnosticLine]:
        lines = [DiagnosticLine("5. 检查凭证文件...\n", "info")]
        if tunnel_id:
            cred_path = cf.default_credentials_path(tunnel_id)
            if cred_path.exists():
                lines.append(DiagnosticLine(f"   ✓ 凭证存在: {cred_path}\n", "success"))
            else:
                lines.append(DiagnosticLine(f"   ✗ 凭证文件不存在: {cred_path}\n", "error"))
        else:
            lines.append(DiagnosticLine("   ✗ 无法获取隧道ID\n", "error"))
        lines.append(DiagnosticLine("\n"))
        return lines

    def _runtime_lines(self, tunnel_name: str, hostnames: list[str], is_running: Callable[[str], bool]) -> list[DiagnosticLine]:
        lines = [DiagnosticLine("6. 检查运行状态...\n", "info")]
        if is_running(tunnel_name):
            lines.append(DiagnosticLine("   ✓ 隧道正在运行\n", "success"))
            if hostnames:
                lines.append(DiagnosticLine("   可用域名:\n", "info"))
                for host in hostnames:
                    lines.append(DiagnosticLine(f"     • https://{host}\n", "success"))
        else:
            lines.append(DiagnosticLine("   ○ 隧道未运行\n", "warning"))

        lines.append(DiagnosticLine("\n测试完成！\n", "info"))
        return lines
