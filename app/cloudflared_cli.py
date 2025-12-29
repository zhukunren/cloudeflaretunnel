from __future__ import annotations
import base64
import json
import re
import os
import shlex
import subprocess
import sys
import tarfile
import tempfile
import shutil
import signal
from pathlib import Path
from typing import Iterable, Callable, Optional
import platform
import urllib.request
import urllib.error
from urllib.parse import urlparse
import http.client
import ssl
import socket
from datetime import datetime


def _is_windows():
    return os.name == "nt"


def _is_macos():
    return platform.system().lower() == "darwin"


def _shell_split(cmd: str):
    if _is_windows():
        return cmd
    return shlex.split(cmd)


def find_cloudflared(custom_path: str | None = None) -> str | None:
    if custom_path:
        p = Path(custom_path)
        if p.exists():
            return str(p)

    exe = "cloudflared.exe" if _is_windows() else "cloudflared"

    # 首先检查当前目录和父目录
    current_dir = Path.cwd()
    local_paths = [
        current_dir / exe,  # 当前目录
        current_dir.parent / exe,  # 父目录
        Path(__file__).parent.parent / exe,  # app的父目录
    ]

    for candidate in local_paths:
        if candidate.exists():
            return str(candidate)

    # 然后检查系统PATH
    for folder in os.environ.get("PATH", "").split(os.pathsep):
        candidate = Path(folder) / exe
        if candidate.exists():
            return str(candidate)

    return None


class CloudflaredBinaryError(RuntimeError):
    """Raised when the selected cloudflared binary cannot run on the current system."""


def _ensure_binary(cloudflared_path: str) -> str:
    if not cloudflared_path:
        raise CloudflaredBinaryError("请先设置 cloudflared 可执行文件路径。")

    path = Path(cloudflared_path).expanduser()
    if not path.exists():
        raise CloudflaredBinaryError(f"找不到 cloudflared 可执行文件: {path}")
    if not path.is_file():
        raise CloudflaredBinaryError(f"cloudflared 路径不是文件: {path}")

    if _is_windows():
        if path.suffix.lower() != ".exe":
            raise CloudflaredBinaryError("当前系统为 Windows，请选择 cloudflared.exe")
    else:
        if path.suffix.lower() == ".exe":
            raise CloudflaredBinaryError("当前系统不是 Windows，请下载 Linux/macOS 版本（无 .exe 后缀）。")
        if not os.access(path, os.X_OK):
            raise CloudflaredBinaryError(f"{path} 没有执行权限，请执行 chmod +x cloudflared")

    return str(path)


def version(cloudflared_path: str) -> str | None:
    try:
        binary = _ensure_binary(cloudflared_path)
    except CloudflaredBinaryError:
        return None
    try:
        out = subprocess.check_output([binary, "--version"], text=True, encoding="utf-8")
        return out.strip()
    except Exception:
        return None


def login(cloudflared_path: str) -> subprocess.Popen:
    binary = _ensure_binary(cloudflared_path)
    creationflags = 0x08000000 if _is_windows() else 0
    return subprocess.Popen([binary, "login"], creationflags=creationflags)


def list_tunnels(
    cloudflared_path: str,
    return_error: bool = False,
    timeout: int = 15,
) -> list[dict] | tuple[list[dict], str | None]:
    """
    列出 Cloudflare 隧道。

    return_error=True 时返回 (列表, 错误消息) 便于上层友好提示。
    """
    binary = _ensure_binary(cloudflared_path)
    error_msg = None
    try:
        out = subprocess.check_output(
            [binary, "tunnel", "list", "--output", "json"],
            text=True,
            encoding="utf-8",
            stderr=subprocess.PIPE,
            timeout=timeout,
        )
        data = json.loads(out)
        result = data if isinstance(data, list) else []
        return (result, None) if return_error else result
    except subprocess.TimeoutExpired:
        error_msg = f"cloudflared tunnel list 超时（{timeout}s）"
        result: list[dict] = []
        return (result, error_msg) if return_error else result
    except Exception as exc:
        if isinstance(exc, subprocess.CalledProcessError):
            error_msg = (exc.stderr or exc.output or "").strip() or str(exc)
        else:
            error_msg = str(exc)

        try:
            out = subprocess.check_output(
                [binary, "tunnel", "list"],
                text=True,
                encoding="utf-8",
                stderr=subprocess.PIPE,
                timeout=timeout,
            )
            lines = [l for l in out.splitlines() if l.strip()]
            if not lines:
                result = []
            else:
                header = [h.strip().lower() for h in lines[0].split("\t")]
                items = []
                for line in lines[1:]:
                    cols = [c.strip() for c in line.split("\t")]
                    item = {
                        header[i] if i < len(header) else f"col{i}": cols[i]
                        for i in range(min(len(cols), len(header)))
                    }
                    items.append(item)
                result = items
        except Exception as exc2:
            if isinstance(exc2, subprocess.CalledProcessError):
                error_msg = error_msg or (exc2.stderr or exc2.output or "").strip() or str(exc2)
            else:
                error_msg = error_msg or str(exc2)
            result = []

        return (result, error_msg) if return_error else result


def load_local_tunnels(base_dir: str | os.PathLike[str] | None = None) -> list[dict]:
    """从本地配置加载隧道列表，用于离线模式。"""
    root = Path(base_dir) if base_dir else Path(__file__).resolve().parent.parent
    tunnels: list[dict] = []
    seen: set[str] = set()

    config_json = root / "config" / "tunnels.json"
    if config_json.exists():
        try:
            data = json.loads(config_json.read_text(encoding="utf-8"))
            for item in data.get("tunnels", []):
                name = item.get("name")
                if not name or name in seen:
                    continue
                cfg_raw = item.get("config") or f"tunnels/{name}/config.yml"
                cfg_path = Path(cfg_raw)
                if not cfg_path.is_absolute():
                    cfg_path = root / cfg_path
                tid = extract_tunnel_id_from_config(cfg_path) or ""
                tunnels.append(
                    {
                        "name": name,
                        "id": tid,
                        "config": str(cfg_path),
                        "source": "local-config",
                    }
                )
                seen.add(name)
        except Exception:
            pass

    tunnels_dir = root / "tunnels"
    if tunnels_dir.exists():
        for cfg in tunnels_dir.glob("*/config.yml"):
            name = cfg.parent.name
            if name in seen:
                continue
            tid = extract_tunnel_id_from_config(cfg) or ""
            tunnels.append(
                {
                    "name": name,
                    "id": tid,
                    "config": str(cfg),
                    "source": "local-scan",
                }
            )
            seen.add(name)

    return tunnels


def create_tunnel(cloudflared_path: str, name: str, origin_cert: str | os.PathLike[str] | None = None) -> tuple[bool, str]:
    try:
        binary = _ensure_binary(cloudflared_path)
    except CloudflaredBinaryError as e:
        return False, str(e)
    cert_path = find_origin_cert(origin_cert)
    if cert_path is None:
        return False, (
            "未找到 Cloudflare 认证证书 cert.pem。\n"
            "请先点击“登录”完成授权，或把 cert.pem 放到 ~/.cloudflared 目录后重试。"
        )

    env = os.environ.copy()
    env["TUNNEL_ORIGIN_CERT"] = str(cert_path)
    try:
        out = subprocess.check_output([binary, "tunnel", "create", name],
                                      stderr=subprocess.STDOUT, text=True, encoding="utf-8", env=env)
        return True, out
    except subprocess.CalledProcessError as e:
        output = e.output or ""
        if "origincert" in output.lower():
            output = (
                "Cloudflared 报告 origin cert 参数缺失，"
                "请重新登录或确认 cert.pem 路径。\n\n" + output
            )
        return False, output


def delete_tunnel(cloudflared_path: str, name: str) -> tuple[bool, str]:
    try:
        binary = _ensure_binary(cloudflared_path)
    except CloudflaredBinaryError as e:
        return False, str(e)
    try:
        out = subprocess.check_output([binary, "tunnel", "delete", "-f", name],
                                       stderr=subprocess.STDOUT, text=True, encoding="utf-8")
        return True, out
    except subprocess.CalledProcessError as e:
        return False, e.output


def route_dns(cloudflared_path: str, tunnel: str, hostname: str) -> tuple[bool, str]:
    try:
        binary = _ensure_binary(cloudflared_path)
    except CloudflaredBinaryError as e:
        return False, str(e)
    try:
        out = subprocess.check_output([binary, "tunnel", "route", "dns", tunnel, hostname],
                                       stderr=subprocess.STDOUT, text=True, encoding="utf-8")
        return True, out
    except subprocess.CalledProcessError as e:
        return False, e.output


def _expand_candidate(candidate: str | os.PathLike[str]) -> Path:
    """Expand ~ and resolve relative segments."""
    return Path(candidate).expanduser()


def _candidate_files_from_dirs(directories: Iterable[Path]) -> list[Path]:
    """Append cert.pem to each directory."""
    return [directory / "cert.pem" for directory in directories]


def find_origin_cert(custom_path: str | os.PathLike[str] | None = None) -> Path | None:
    """Locate the Cloudflare origin certificate used for tunnel create commands."""
    candidates: list[Path] = []

    env_cert = os.environ.get("TUNNEL_ORIGIN_CERT")
    if env_cert:
        candidates.append(_expand_candidate(env_cert))

    if custom_path:
        candidates.append(_expand_candidate(custom_path))

    home = Path.home()
    default_dirs = [
        home / ".cloudflared",
        home / ".cloudflare-warp",
        home / "cloudflared-warp",
        home / ".cloudflared-warp",
        Path("/etc/cloudflared"),
        Path("/usr/local/etc/cloudflared"),
    ]

    candidates.extend(_candidate_files_from_dirs(default_dirs))

    # Allow directories directly in candidate list
    for raw in list(candidates):
        if raw.is_dir():
            candidates.append(raw / "cert.pem")

    seen: set[Path] = set()
    for cand in candidates:
        normalized = cand.expanduser()
        if normalized in seen:
            continue
        seen.add(normalized)
        if normalized.is_file():
            return normalized
    return None


def origin_cert_status(custom_path: str | os.PathLike[str] | None = None) -> tuple[bool, Path | None, Optional[str]]:
    """Return whether cert.pem exists alongside its path and last modification time."""
    cert = find_origin_cert(custom_path)
    if cert is None:
        return False, None, None

    modified: Optional[str] = None
    try:
        ts = cert.stat().st_mtime
        modified = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        modified = None
    return True, cert, modified


def _linux_arch_slug() -> str:
    machine = (platform.machine() or "").lower()
    if machine in ("x86_64", "amd64"):
        return "amd64"
    if machine in ("aarch64", "arm64"):
        return "arm64"
    if machine in ("armv7l", "armv6l", "arm"):
        return "arm"
    if machine in ("i386", "i686", "x86"):
        return "386"
    raise RuntimeError(f"暂不支持当前架构: {machine or 'unknown'}")


def _macos_arch_slug() -> str:
    machine = (platform.machine() or "").lower()
    if machine in ("arm64", "aarch64"):
        return "arm64"
    if machine in ("x86_64", "amd64"):
        return "amd64"
    raise RuntimeError(f"暂不支持当前架构: {machine or 'unknown'}")


def _windows_arch_slug() -> str:
    machine = (platform.machine() or "").lower()
    if machine in ("x86_64", "amd64"):
        return "amd64"
    if machine in ("i386", "i686", "x86"):
        return "386"
    if machine in ("aarch64", "arm64"):
        return "arm64"
    raise RuntimeError(f"暂不支持当前架构: {machine or 'unknown'}")


def _latest_linux_download_url(arch_slug: str) -> tuple[str, Optional[str]]:
    api_url = "https://api.github.com/repos/cloudflare/cloudflared/releases/latest"
    headers = {
        "User-Agent": "cloudflared-gui",
        "Accept": "application/vnd.github+json",
    }
    try:
        req = urllib.request.Request(api_url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        assets = data.get("assets") or []
        target_name = f"cloudflared-linux-{arch_slug}"
        for asset in assets:
            name = asset.get("name", "")
            download_url = asset.get("browser_download_url")
            if name == target_name and download_url:
                return download_url, data.get("tag_name")
    except Exception:
        pass
    fallback = f"https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-{arch_slug}"
    return fallback, None


def _latest_macos_download_url(arch_slug: str) -> tuple[str, Optional[str]]:
    api_url = "https://api.github.com/repos/cloudflare/cloudflared/releases/latest"
    headers = {
        "User-Agent": "cloudflared-gui",
        "Accept": "application/vnd.github+json",
    }
    try:
        req = urllib.request.Request(api_url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        assets = data.get("assets") or []
        target_name = f"cloudflared-darwin-{arch_slug}.tgz"
        for asset in assets:
            name = asset.get("name", "")
            download_url = asset.get("browser_download_url")
            if name == target_name and download_url:
                return download_url, data.get("tag_name")
    except Exception:
        pass
    fallback = f"https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-darwin-{arch_slug}.tgz"
    return fallback, None


def _latest_windows_download_url(arch_slug: str) -> tuple[str, Optional[str]]:
    api_url = "https://api.github.com/repos/cloudflare/cloudflared/releases/latest"
    headers = {
        "User-Agent": "cloudflared-gui",
        "Accept": "application/vnd.github+json",
    }
    try:
        req = urllib.request.Request(api_url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        assets = data.get("assets") or []
        target_name = f"cloudflared-windows-{arch_slug}.exe"
        for asset in assets:
            name = asset.get("name", "")
            download_url = asset.get("browser_download_url")
            if name == target_name and download_url:
                return download_url, data.get("tag_name")
    except Exception:
        pass
    fallback = (
        "https://github.com/cloudflare/cloudflared/releases/latest/download/"
        f"cloudflared-windows-{arch_slug}.exe"
    )
    return fallback, None


def _download_file(url: str, destination: Path, progress_cb: Callable[[int], None] | None = None) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "cloudflared-gui"})
    with urllib.request.urlopen(req, timeout=30) as resp, open(destination, "wb") as f:
        total = int(resp.headers.get("Content-Length", "0"))
        read = 0
        chunk = 64 * 1024
        while True:
            data = resp.read(chunk)
            if not data:
                break
            f.write(data)
            read += len(data)
            if progress_cb and total:
                pct = max(1, int(read * 100 / total))
                progress_cb(min(pct, 100))


def download_cloudflared(
    target_path: Path | None = None,
    progress_cb: Callable[[int], None] | None = None,
) -> tuple[bool, str, Optional[str]]:
    """下载适用于当前系统的 cloudflared。"""
    if _is_windows():
        return _download_cloudflared_windows(target_path, progress_cb)
    if _is_macos():
        return _download_cloudflared_macos(target_path, progress_cb)
    return _download_cloudflared_linux(target_path, progress_cb)


def download_cloudflared_linux(target_path: Path | None = None,
                               progress_cb: Callable[[int], None] | None = None) -> tuple[bool, str, Optional[str]]:
    """下载适用于当前 Linux/macOS 的 cloudflared，并赋予执行权限。"""
    if _is_windows():
        return False, "检查更新仅适用于 Linux/macOS 环境。", None

    if _is_macos():
        return _download_cloudflared_macos(target_path, progress_cb)

    return _download_cloudflared_linux(target_path, progress_cb)


def _download_cloudflared_windows(
    target_path: Path | None,
    progress_cb: Callable[[int], None] | None,
) -> tuple[bool, str, Optional[str]]:
    try:
        arch_slug = _windows_arch_slug()
    except RuntimeError as e:
        return False, str(e), None

    url, version = _latest_windows_download_url(arch_slug)
    base_dir = Path(__file__).resolve().parent.parent
    target = Path(target_path) if target_path else (base_dir / "cloudflared.exe")
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = Path(f"{target}.tmp")

    try:
        _download_file(url, tmp_path, progress_cb)
        tmp_path.replace(target)
        message = f"cloudflared (windows-{arch_slug}) 已更新到 {target}"
        return True, message, version
    except urllib.error.URLError as e:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        return False, f"下载失败: {e}", version
    except Exception as e:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        return False, f"更新失败: {e}", version


def _download_cloudflared_linux(target_path: Path | None,
                                progress_cb: Callable[[int], None] | None) -> tuple[bool, str, Optional[str]]:
    try:
        arch_slug = _linux_arch_slug()
    except RuntimeError as e:
        return False, str(e), None

    url, version = _latest_linux_download_url(arch_slug)
    base_dir = Path(__file__).resolve().parent.parent
    target = Path(target_path) if target_path else (base_dir / "cloudflared")
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = Path(f"{target}.tmp")

    try:
        _download_file(url, tmp_path, progress_cb)
        tmp_path.replace(target)
        os.chmod(target, 0o755)
        message = f"cloudflared ({arch_slug}) 已更新到 {target}"
        return True, message, version
    except urllib.error.URLError as e:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        return False, f"下载失败: {e}", version
    except Exception as e:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        return False, f"更新失败: {e}", version


def _download_cloudflared_macos(target_path: Path | None,
                                progress_cb: Callable[[int], None] | None) -> tuple[bool, str, Optional[str]]:
    try:
        arch_slug = _macos_arch_slug()
    except RuntimeError as e:
        return False, str(e), None

    url, version = _latest_macos_download_url(arch_slug)
    base_dir = Path(__file__).resolve().parent.parent
    target = Path(target_path) if target_path else (base_dir / "cloudflared")
    target.parent.mkdir(parents=True, exist_ok=True)
    archive_tmp = Path(f"{target}.tgz.tmp")
    binary_tmp = Path(f"{target}.tmp")

    try:
        _download_file(url, archive_tmp, progress_cb)
        with tarfile.open(archive_tmp, "r:gz") as tar:
            member = next((m for m in tar.getmembers() if m.isfile() and m.name.endswith("cloudflared")), None)
            if member is None:
                raise RuntimeError("压缩包中未找到 cloudflared 可执行文件")
            extracted = tar.extractfile(member)
            if extracted is None:
                raise RuntimeError("无法读取 cloudflared 可执行文件")
            try:
                with open(binary_tmp, "wb") as dst:
                    shutil.copyfileobj(extracted, dst)
            finally:
                extracted.close()

        os.chmod(binary_tmp, 0o755)
        binary_tmp.replace(target)
        message = f"cloudflared ({arch_slug}, macOS) 已更新到 {target}"
        return True, message, version
    except urllib.error.URLError as e:
        return False, f"下载失败: {e}", version
    except Exception as e:
        return False, f"更新失败: {e}", version
    finally:
        archive_tmp.unlink(missing_ok=True)
        binary_tmp.unlink(missing_ok=True)


def default_credentials_path(tunnel_id: str) -> Path:
    home = Path.home()
    return home / ".cloudflared" / f"{tunnel_id}.json"


def write_basic_config(config_path: Path, tunnel_name: str, tunnel_id: str, service_url: str | None = None, hostname: str | None = None) -> None:
    credentials = default_credentials_path(tunnel_id)
    lines = []
    lines.append(f"tunnel: {tunnel_id}")
    lines.append(f"credentials-file: {credentials.as_posix()}")
    lines.append("ingress:")
    if hostname and service_url:
        lines.append(f"  - hostname: {hostname}")
        lines.append(f"    service: {service_url}")
    else:
        lines.append("  - service: http://localhost:8080")
    lines.append("  - service: http_status:404")
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text("\n".join(lines), encoding="utf-8")


_LOCAL_SERVICE_HOSTS = {
    "localhost",
    "127.0.0.1",
    "0.0.0.0",
    "::1",
    "[::1]",
}


def _probe_local_service(host: str, port: int, use_https: bool, timeout: float = 1.5) -> bool:
    """Attempt a quick HEAD request to determine whether HTTP/HTTPS is available."""
    clean_host = host.strip("[]") if host else host
    conn = None
    try:
        if use_https:
            context = ssl._create_unverified_context()
            conn = http.client.HTTPSConnection(clean_host, port, timeout=timeout, context=context)
        else:
            conn = http.client.HTTPConnection(clean_host, port, timeout=timeout)
        conn.request("HEAD", "/")
        conn.getresponse()
        return True
    except (ssl.SSLError, socket.timeout, ConnectionRefusedError, OSError):
        return False
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def normalize_local_service_protocols(config_path: Path) -> tuple[bool, list[str]]:
    """
    Ensure ingress rules pointing to local services use the protocol that is actually available.
    Returns (changed, changes_description).
    """
    if not config_path.exists():
        return False, []

    try:
        import yaml
        data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except Exception:
        return False, []

    ingress = data.get("ingress")
    if not isinstance(ingress, list):
        return False, []

    changed = False
    changes: list[str] = []

    for rule in ingress:
        service = rule.get("service") if isinstance(rule, dict) else None
        if not isinstance(service, str):
            continue
        parsed = urlparse(service)
        if parsed.scheme not in ("http", "https"):
            continue
        host = parsed.hostname
        if not host or host.lower() not in _LOCAL_SERVICE_HOSTS:
            continue

        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        http_ok = _probe_local_service(host, port, use_https=False)
        https_ok = _probe_local_service(host, port, use_https=True)

        new_scheme = None
        if parsed.scheme == "https" and not https_ok and http_ok:
            new_scheme = "http"
        elif parsed.scheme == "http" and not http_ok and https_ok:
            new_scheme = "https"

        if new_scheme:
            new_service = service.replace(f"{parsed.scheme}://", f"{new_scheme}://", 1)
            rule["service"] = new_service
            changed = True
            changes.append(f"{service} -> {new_service}")

    if not changed:
        return False, []

    try:
        import io
        with io.open(config_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
    except Exception:
        return False, []

    return True, changes


def _create_popen(
    cmd: list[str],
    workdir: Path | None = None,
    capture_output: bool = True,
    log_file: Path | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.Popen:
    creationflags = 0x08000000 if _is_windows() else 0
    preexec_fn = None if _is_windows() else os.setsid
    stdout = subprocess.PIPE if capture_output else subprocess.DEVNULL
    stderr = subprocess.STDOUT if capture_output else subprocess.DEVNULL
    log_handle = None

    if not capture_output and log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        log_handle = open(log_file, "ab", buffering=0)
        stdout = log_handle
        stderr = subprocess.STDOUT

    proc = subprocess.Popen(
        cmd,
        cwd=str(workdir) if workdir else None,
        stdout=stdout,
        stderr=stderr,
        text=True,
        encoding="utf-8",
        env=env,
        creationflags=creationflags,
        preexec_fn=preexec_fn,
    )
    if log_handle:
        try:
            log_handle.close()
        except Exception:
            pass
    return proc


def extract_credentials_file_from_config(config_path: Path) -> str | None:
    """从配置文件中提取 credentials-file 字段"""
    if not config_path.exists():
        return None

    try:
        import yaml
        data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        cred = data.get("credentials-file")
        if isinstance(cred, str) and cred.strip():
            return cred.strip()
    except Exception:
        try:
            for line in config_path.read_text(encoding="utf-8").splitlines():
                raw = line.strip()
                if raw.startswith("credentials-file:"):
                    value = raw.split(":", 1)[1].strip().strip("\"'").strip()
                    return value or None
        except Exception:
            return None
    return None


def resolve_credentials_path(config_path: Path) -> Path | None:
    """将配置文件里的 credentials-file 解析为本机 Path（相对路径按 config 同目录）"""
    cred = extract_credentials_file_from_config(config_path)
    if not cred:
        return None
    path = Path(cred).expanduser()
    if not path.is_absolute():
        path = (config_path.parent / path)
    return path


class TunnelCredentialsError(RuntimeError):
    """Raised when tunnel credentials/token cannot be obtained for running a tunnel."""


def tunnel_token(cloudflared_path: str, tunnel_name: str, timeout: int = 20) -> str:
    """获取 tunnel token（不会在异常信息中泄露 token）"""
    binary = _ensure_binary(cloudflared_path)
    try:
        out = subprocess.check_output(
            [binary, "tunnel", "token", tunnel_name],
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            timeout=timeout,
        )
        token = (out or "").strip()
        if not token:
            raise TunnelCredentialsError("获取隧道 token 失败：cloudflared 返回空输出")
        return token
    except subprocess.TimeoutExpired as exc:
        raise TunnelCredentialsError("获取隧道 token 超时，请检查网络或稍后重试") from exc
    except subprocess.CalledProcessError as exc:
        msg = (exc.output or "").strip()
        raise TunnelCredentialsError(f"获取隧道 token 失败：{msg or 'cloudflared 返回非零退出码'}") from None


def _credentials_from_token(token: str) -> dict[str, str]:
    token = (token or "").strip()
    if not token:
        raise TunnelCredentialsError("解析隧道 token 失败：token 为空")

    try:
        padded = token + ("=" * (-len(token) % 4))
        payload_raw = base64.b64decode(padded.encode("utf-8"))
        payload = json.loads(payload_raw.decode("utf-8"))
    except Exception:
        raise TunnelCredentialsError("解析隧道 token 失败：token 格式异常") from None

    if not isinstance(payload, dict):
        raise TunnelCredentialsError("解析隧道 token 失败：token 内容异常")

    account_tag = payload.get("a")
    tunnel_secret = payload.get("s")
    tunnel_id = payload.get("t")
    if not (isinstance(account_tag, str) and isinstance(tunnel_secret, str) and isinstance(tunnel_id, str)):
        raise TunnelCredentialsError("解析隧道 token 失败：token 内容缺少必要字段")
    if not (account_tag.strip() and tunnel_secret.strip() and tunnel_id.strip()):
        raise TunnelCredentialsError("解析隧道 token 失败：token 内容为空")

    return {
        "AccountTag": account_tag.strip(),
        "TunnelSecret": tunnel_secret.strip(),
        "TunnelID": tunnel_id.strip(),
    }


def write_credentials_file(credentials_path: Path, credentials: dict[str, str]) -> None:
    """写入 cloudflared tunnel credentials 文件（JSON，utf-8 无 BOM）"""
    credentials_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = credentials_path.with_suffix(credentials_path.suffix + ".tmp")
    try:
        tmp_path.write_text(json.dumps(credentials, ensure_ascii=False), encoding="utf-8")
        tmp_path.replace(credentials_path)
        if not _is_windows():
            try:
                os.chmod(credentials_path, 0o600)
            except Exception:
                pass
    finally:
        tmp_path.unlink(missing_ok=True)


def update_config_credentials_file(config_path: Path, credentials_path: Path) -> bool:
    """更新配置文件中的 credentials-file 路径（尽量保持原格式，仅替换对应行）"""
    if not config_path.exists():
        return False

    new_value = str(credentials_path)
    try:
        lines = config_path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return False

    updated: list[str] = []
    replaced = False
    for line in lines:
        stripped = line.lstrip()
        if stripped.startswith("credentials-file:"):
            indent = line[: len(line) - len(stripped)]
            updated.append(f"{indent}credentials-file: {new_value}")
            replaced = True
        else:
            updated.append(line)

    if not replaced:
        inserted: list[str] = []
        done = False
        for line in updated:
            inserted.append(line)
            if not done and line.lstrip().startswith("tunnel:"):
                indent = line[: len(line) - len(line.lstrip())]
                inserted.append(f"{indent}credentials-file: {new_value}")
                done = True
        updated = inserted if done else updated

    try:
        config_path.write_text("\n".join(updated) + "\n", encoding="utf-8")
        return True
    except Exception:
        return False


def get_config_protocol(config_path: Path) -> str | None:
    """读取配置文件中的协议设置（例如 http2/quic），未设置时返回 None。"""
    if not config_path.exists():
        return None
    try:
        import yaml
        data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        protocol = data.get("protocol")
        if isinstance(protocol, str) and protocol.strip():
            return protocol.strip()
    except Exception:
        return None
    return None


def run_tunnel(cloudflared_path: str, name: str, config_path: Path,
               capture_output: bool = True, log_file: Path | None = None,
               protocol: str | None = None) -> subprocess.Popen:
    binary = _ensure_binary(cloudflared_path)

    env: dict[str, str] | None = None
    credentials_override: Path | None = None

    config_cred_path = resolve_credentials_path(config_path)
    if config_cred_path and config_cred_path.is_file():
        credentials_override = None  # 使用配置文件里的 credentials-file
    else:
        tunnel_id = extract_tunnel_id_from_config(config_path) or ""
        default_cred = default_credentials_path(tunnel_id) if tunnel_id else None
        if default_cred and default_cred.is_file():
            credentials_override = default_cred
        elif default_cred:
            token = tunnel_token(cloudflared_path, name)
            try:
                creds = _credentials_from_token(token)
                if creds.get("TunnelID") != tunnel_id:
                    raise TunnelCredentialsError("获取隧道凭据失败：token 与配置中的 tunnel UUID 不一致")
                write_credentials_file(default_cred, creds)
                credentials_override = default_cred
            except Exception:
                # 兜底：无法落盘时仍尝试用 token 启动（但启动稳定性会依赖 Cloudflare API）
                env = os.environ.copy()
                env["TUNNEL_TOKEN"] = token
        else:
            token = tunnel_token(cloudflared_path, name)
            env = os.environ.copy()
            env["TUNNEL_TOKEN"] = token

        if credentials_override and (not config_cred_path or config_cred_path != credentials_override):
            update_config_credentials_file(config_path, credentials_override)

    cmd = [binary, "--config", str(config_path)]
    if protocol:
        cmd.extend(["--protocol", protocol])
    cmd.extend(["tunnel", "run"])
    if credentials_override:
        cmd.extend(["--credentials-file", str(credentials_override)])
    cmd.append(name)
    return _create_popen(
        cmd,
        workdir=config_path.parent,
        capture_output=capture_output,
        log_file=log_file,
        env=env,
    )


def stop_process(proc: subprocess.Popen, timeout: float = 5.0) -> None:
    """停止 cloudflared 进程，必要时强杀整个进程组。"""
    if proc.poll() is not None:
        return

    try:
        if _is_windows():
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/F", "/T"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            try:
                proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                pass
            return

        pgid = None
        try:
            pgid = os.getpgid(proc.pid)
        except Exception:
            pgid = None

        def _signal_group(sig):
            if pgid is not None:
                os.killpg(pgid, sig)
            else:
                proc.send_signal(sig)

        _signal_group(signal.SIGTERM)
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            _signal_group(signal.SIGKILL)
            try:
                proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                pass
    finally:
        try:
            if proc.stdout and not proc.stdout.closed:
                proc.stdout.close()
        except Exception:
            pass


def extract_tunnel_id(tunnel_item: dict) -> str | None:
    for k in ("id", "tunnel_id", "tunnel id"):
        if k in tunnel_item:
            return str(tunnel_item[k])
    return None


def extract_tunnel_id_from_config(config_path: Path) -> str | None:
    """从配置文件中提取隧道ID"""
    if not config_path.exists():
        return None

    try:
        import yaml
        data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        return data.get("tunnel")
    except Exception:
        # 如果YAML解析失败，尝试简单的文本解析
        try:
            for line in config_path.read_text(encoding="utf-8").splitlines():
                if line.startswith("tunnel:"):
                    return line.split(":", 1)[1].strip()
        except Exception:
            pass
    return None


def validate_tunnel_config(config_path: Path, actual_tunnel_id: str) -> bool:
    """验证配置文件中的隧道ID是否与实际ID匹配"""
    config_tunnel_id = extract_tunnel_id_from_config(config_path)
    return config_tunnel_id == actual_tunnel_id


def update_config_tunnel_id(config_path: Path, new_tunnel_id: str) -> bool:
    """更新配置文件中的隧道ID"""
    if not config_path.exists():
        return False

    try:
        import yaml
        # 读取现有配置
        data = yaml.safe_load(config_path.read_text(encoding="utf-8"))

        # 更新隧道ID和凭证文件路径
        data["tunnel"] = new_tunnel_id
        data["credentials-file"] = str(default_credentials_path(new_tunnel_id))

        # 写回配置
        import io
        with io.open(config_path, 'w', encoding='utf-8') as f:
            yaml.dump(data, f, default_flow_style=False, allow_unicode=True)
        return True
    except Exception:
        # 如果YAML处理失败，尝试简单的文本替换
        try:
            lines = []
            for line in config_path.read_text(encoding="utf-8").splitlines():
                if line.startswith("tunnel:"):
                    lines.append(f"tunnel: {new_tunnel_id}")
                elif line.startswith("credentials-file:"):
                    lines.append(f"credentials-file: {default_credentials_path(new_tunnel_id).as_posix()}")
                else:
                    lines.append(line)
            config_path.write_text("\n".join(lines), encoding="utf-8")
            return True
        except Exception:
            return False


def _extract_tunnel_name_from_cmdline(cmdline: str) -> str | None:
    if not cmdline:
        return None
    match = re.search(r"(?:^|\s)tunnel\s+run\s+([^\s]+)", cmdline)
    if not match:
        return None
    name = match.group(1).strip().strip("\"'").strip()
    return name or None


def _windows_cloudflared_processes() -> list[tuple[int, str]]:
    import csv
    import io

    if shutil.which("wmic"):
        try:
            cmd = [
                "wmic",
                "process",
                "where",
                'name="cloudflared.exe"',
                "get",
                "ProcessId,CommandLine",
                "/format:csv",
            ]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="ignore",
                check=False,
            )
            rows = list(csv.DictReader(io.StringIO(result.stdout or "")))
            processes: list[tuple[int, str]] = []
            for row in rows:
                pid_raw = (row.get("ProcessId") or row.get("ProcessID") or "").strip()
                cmdline = (row.get("CommandLine") or "").strip()
                if pid_raw.isdigit():
                    processes.append((int(pid_raw), cmdline))
            if processes:
                return processes
        except Exception:
            pass

    if shutil.which("powershell"):
        try:
            ps_script = (
                "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; "
                "$items = Get-CimInstance Win32_Process -Filter \"Name='cloudflared.exe'\" "
                "| Select-Object ProcessId,CommandLine; "
                "$items | ConvertTo-Json -Compress"
            )
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_script],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="ignore",
                check=False,
            )
            raw = (result.stdout or "").strip().lstrip("\ufeff")
            if not raw:
                return []
            data = json.loads(raw)
            if not data:
                return []
            items = data if isinstance(data, list) else [data]
            processes = []
            for item in items:
                if not isinstance(item, dict):
                    continue
                pid = item.get("ProcessId")
                cmdline = item.get("CommandLine") or ""
                try:
                    pid_int = int(pid)
                except Exception:
                    continue
                processes.append((pid_int, str(cmdline)))
            return processes
        except Exception:
            return []

    return []


def _running_tunnels_from_tracker() -> list[dict]:
    tracker_type = None
    try:
        from .utils.process_tracker import ProcessTracker as tracker_type  # type: ignore
    except Exception:
        try:
            from utils.process_tracker import ProcessTracker as tracker_type  # type: ignore
        except Exception:
            tracker_type = None

    if tracker_type is None:
        return []

    base_dir = Path(__file__).resolve().parent.parent
    try:
        tracker = tracker_type(base_dir)
        running: list[dict] = []
        for record in tracker.list_records():
            if record.alive:
                running.append({"pid": record.pid, "name": record.name})
        return running
    except Exception:
        return []


def find_running_tunnel(tunnel_name: str) -> dict | None:
    """检测指定隧道是否在系统中运行"""
    for item in get_running_tunnels():
        if item.get("name") == tunnel_name and str(item.get("pid", "")).isdigit():
            return {"pid": int(item["pid"]), "name": tunnel_name}
    return None


def get_running_tunnels() -> list[dict]:
    """获取所有运行中的隧道信息（跨平台）"""
    running_tunnels: list[dict] = []
    seen: set[tuple[int, str]] = set()

    def _add(pid: int, name: str):
        key = (int(pid), name)
        if key in seen:
            return
        seen.add(key)
        running_tunnels.append({"pid": int(pid), "name": name})

    for item in _running_tunnels_from_tracker():
        pid = item.get("pid")
        name = item.get("name")
        if isinstance(name, str) and str(pid or "").isdigit():
            _add(int(pid), name)

    try:
        if _is_windows():
            for pid, cmdline in _windows_cloudflared_processes():
                name = _extract_tunnel_name_from_cmdline(cmdline)
                if name:
                    _add(pid, name)
            return running_tunnels

        result = subprocess.run(["ps", "aux"], capture_output=True, text=True, check=False)
        for line in (result.stdout or "").splitlines():
            if "cloudflared" not in line:
                continue
            name = _extract_tunnel_name_from_cmdline(line)
            if not name:
                continue
            parts = line.split()
            if len(parts) < 2 or not parts[1].isdigit():
                continue
            _add(int(parts[1]), name)
    except Exception:
        pass

    return running_tunnels


def kill_tunnel_by_name(tunnel_name: str) -> tuple[bool, str]:
    """通过隧道名称停止运行的隧道"""
    running = [t for t in get_running_tunnels() if t.get("name") == tunnel_name and t.get("pid")]
    if not running:
        return False, f"隧道 {tunnel_name} 未在运行"

    pids = sorted({int(t["pid"]) for t in running if str(t.get("pid", "")).isdigit()})
    if not pids:
        return False, f"隧道 {tunnel_name} 未在运行"

    def _pid_alive(pid: int) -> bool:
        if not _is_windows():
            try:
                stat_path = Path(f"/proc/{pid}/stat")
                if stat_path.exists():
                    parts = stat_path.read_text(encoding="utf-8", errors="ignore").split()
                    if len(parts) > 2 and parts[2].upper() == "Z":
                        return False
            except Exception:
                pass
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except Exception:
            return True

    errors: list[str] = []

    try:
        import time

        if _is_windows():
            for pid in pids:
                try:
                    subprocess.run(['taskkill', '/PID', str(pid), '/F'], check=True)
                except Exception as e:
                    errors.append(f"PID {pid}: {e}")
            ok = not errors
            msg = f"已停止隧道 {tunnel_name} (PIDs: {', '.join(map(str, pids))})"
            if errors:
                msg += f"；失败: {', '.join(errors)}"
            return ok, msg

        for pid in pids:
            try:
                os.kill(pid, signal.SIGTERM)
            except Exception as e:
                errors.append(f"PID {pid}: {e}")

        time.sleep(1)
        still_alive = [pid for pid in pids if _pid_alive(pid)]
        for pid in still_alive:
            try:
                os.kill(pid, signal.SIGKILL)
            except Exception as e:
                errors.append(f"PID {pid} SIGKILL: {e}")

        time.sleep(0.5)
        remaining = [pid for pid in pids if _pid_alive(pid)]
        ok = not remaining
        msg = f"已停止隧道 {tunnel_name} (PIDs: {', '.join(map(str, pids))})"
        if remaining:
            msg += f"；仍存活: {', '.join(map(str, remaining))}"
        if errors:
            msg += f"；错误: {', '.join(errors)}"
        return ok, msg

    except Exception as e:
        return False, f"停止隧道失败: {e}"


def test_connection(cloudflared_path: str, tunnel_name: str, timeout: int = 10) -> tuple[bool | None, str]:
    """测试隧道连接是否正常"""
    try:
        binary = _ensure_binary(cloudflared_path)
    except CloudflaredBinaryError as e:
        return False, str(e)

    json_output: str | None = None
    text_output: str | None = None

    def _looks_like_edge(obj: object) -> bool:
        return isinstance(obj, dict) and ("colo_name" in obj or "origin_ip" in obj or "opened_at" in obj)

    def _collect_connectors(payload: dict) -> list[dict]:
        """兼容不同 cloudflared 版本的连接器字段"""
        connectors: list[dict] = []

        def _pick(source: list[object] | None):
            if not isinstance(source, list):
                return
            for item in source:
                if isinstance(item, dict) and not _looks_like_edge(item):
                    connectors.append(item)

        for key in ("conns", "connectors", "connections"):
            _pick(payload.get(key))

        tunnel_block = payload.get("tunnel")
        if isinstance(tunnel_block, dict):
            for key in ("conns", "connectors", "connections"):
                _pick(tunnel_block.get(key))

        return connectors

    def _collect_edges(connector: dict) -> list[dict]:
        edges: list[dict] = []
        for key in ("conns", "connections", "edges"):
            candidates = connector.get(key)
            if isinstance(candidates, list):
                edges.extend([e for e in candidates if isinstance(e, dict)])
        return edges

    def _format_json_summary(data: dict) -> tuple[int, str]:
        connectors = _collect_connectors(data)
        lines: list[str] = []
        total = 0
        for connector in connectors:
            cid = connector.get("id", "未知ID")
            version = connector.get("version", "")
            arch = connector.get("arch", "")
            run_at = connector.get("run_at", connector.get("created_at", ""))
            edges = _collect_edges(connector)
            # 某些版本只返回计数字段
            if not edges and isinstance(connector.get("num_connections"), int):
                total += int(connector.get("num_connections", 0))
            else:
                total += len(edges)

            lines.append(f"- 连接器 {cid} ({version} {arch}) 启动于 {run_at}")
            for edge in edges:
                colo = edge.get("colo_name", "?")
                origin_ip = edge.get("origin_ip", "?")
                opened = edge.get("opened_at", edge.get("started_at", ""))
                edge_id = edge.get("id", "")
                lines.append(f"    · 节点 {colo} ({origin_ip}) - {edge_id} @ {opened}")
        summary = "\n".join(lines) if lines else ""
        return total, summary

    def _parse_text_edges(text: str) -> int:
        """从 text 模式的输出中解析边缘连接数，避免 JSON 结构变化导致误报"""
        total = 0
        in_table = False
        for raw in text.splitlines():
            line = raw.strip()
            if not line:
                continue
            if line.startswith("CONNECTOR ID"):
                in_table = True
                continue
            if not in_table:
                continue
            parts = line.split()
            if len(parts) < 6:
                continue
            edge_field = " ".join(parts[5:])
            for match in re.finditer(r"(\d+)x", edge_field):
                total += int(match.group(1))
        return total

    def _classify_failure(detail_text: str) -> tuple[bool | None, str]:
        """区分 API/网络异常与真实无连接，避免误杀"""
        detail = detail_text or ""
        lower = detail.lower()
        api_keywords = ("rest request failed", "api call", "status 5", "internal server error", "service unavailable")
        network_keywords = (
            "timeout",
            "timed out",
            "context deadline exceeded",
            "tls handshake",
            "failed to dial to edge",
            "no recent network activity",
            "no free edge addresses",
        )
        if any(k in lower for k in api_keywords):
            return None, f"Cloudflare API 返回错误，跳过自动重启判定：\n{detail}"
        if any(k in lower for k in network_keywords):
            return None, f"到 Cloudflare 边缘的连接异常（可能网络抖动/被阻断），跳过自动重启判定：\n{detail}"
        if "no active connector" in lower or "no active connection" in lower:
            return False, detail or "隧道没有活跃连接"
        return False, detail or "隧道信息不完整"

    try:
        json_output = subprocess.check_output(
            [binary, "tunnel", "info", "--output", "json", tunnel_name],
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            timeout=timeout,
        )
        data = json.loads(json_output)
        active, summary = _format_json_summary(data if isinstance(data, dict) else {})
        try:
            text_output = subprocess.check_output(
                [binary, "tunnel", "info", tunnel_name],
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                timeout=timeout,
            )
        except Exception:
            text_output = None

        # JSON 结构发生变化时，回退到文本解析以避免误报无连接
        if active == 0 and text_output:
            parsed_edges = _parse_text_edges(text_output)
            if parsed_edges > 0:
                active = parsed_edges
                if not summary:
                    summary = text_output

        detail = summary or (text_output or json_output)
        name = data.get("name", tunnel_name) if isinstance(data, dict) else tunnel_name
        if active > 0:
            return True, f"隧道 {name} 有 {active} 条活跃连接\n{detail}"
        classified_ok, classified_detail = _classify_failure(detail)
        if classified_ok is None:
            return None, classified_detail
        return False, f"隧道 {name} 没有任何活跃连接\n请确认 cloudflared 进程正在运行。\n{classified_detail}"
    except subprocess.CalledProcessError as e:
        text_output = e.output or text_output
    except subprocess.TimeoutExpired:
        return None, "测试超时（可能网络抖动），跳过自动重启判定"
    except (json.JSONDecodeError, ValueError):
        pass

    try:
        if text_output is None:
            text_output = subprocess.check_output(
                [binary, "tunnel", "info", tunnel_name],
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                timeout=timeout,
            )
        classified_ok, classified_detail = _classify_failure(text_output)
        if classified_ok is None:
            return None, classified_detail
        lower = text_output.lower()
        if "no active connector" in lower or "no active connection" in lower:
            return False, f"隧道没有任何活动连接\n{classified_detail}"
        parsed_edges = _parse_text_edges(text_output)
        if parsed_edges > 0:
            return True, f"隧道 {tunnel_name} 有 {parsed_edges} 条活跃连接\n{text_output}"
        if tunnel_name.lower() in lower or "connection" in lower:
            return True, f"隧道 {tunnel_name} 信息获取成功\n{text_output}"
        if classified_ok is None:
            return None, classified_detail
        return False, f"隧道信息不完整\n{classified_detail}"
    except subprocess.TimeoutExpired:
        return None, "测试超时（可能网络抖动），跳过自动重启判定"
    except subprocess.CalledProcessError as e:
        return None, f"测试失败（cloudflared 返回非零，视为未知）：{e.output}"
    except Exception as e:
        return False, f"测试出错: {str(e)}"


def test_local_service(service_url: str) -> tuple[bool, str]:
    """测试本地服务是否可访问"""
    import urllib.request
    import urllib.error
    import socket

    # 解析服务URL
    if not service_url.startswith(('http://', 'https://')):
        return False, "服务URL必须以 http:// 或 https:// 开头"

    try:
        # 设置短超时
        with urllib.request.urlopen(service_url, timeout=3) as response:
            status_code = response.getcode()
            return True, f"本地服务 {service_url} 可访问 (状态码: {status_code})"
    except urllib.error.HTTPError as e:
        # HTTP错误但服务是活的
        return True, f"本地服务 {service_url} 响应 (状态码: {e.code})"
    except urllib.error.URLError as e:
        if isinstance(e.reason, socket.timeout):
            return False, f"连接 {service_url} 超时"
        else:
            return False, f"无法连接到 {service_url}: {e.reason}"
    except Exception as e:
        return False, f"测试 {service_url} 时出错: {str(e)}"


def validate_config(config_path: Path) -> tuple[bool, str]:
    """验证配置文件格式"""
    if not config_path.exists():
        return False, "配置文件不存在"

    try:
        import yaml
    except ImportError:
        # 如果没有yaml库，做基础验证
        try:
            content = config_path.read_text(encoding="utf-8")
            required_fields = ["tunnel:", "credentials-file:", "ingress:"]
            missing = []
            for field in required_fields:
                if field not in content:
                    missing.append(field.rstrip(':'))

            if missing:
                return False, f"配置缺少必要字段: {', '.join(missing)}"

            # 检查是否有至少一个ingress规则
            if "service:" not in content:
                return False, "配置缺少ingress服务规则"

            return True, "配置文件格式正确"
        except Exception as e:
            return False, f"读取配置文件失败: {str(e)}"

    # 如果有yaml库，做完整验证
    try:
        content = config_path.read_text(encoding="utf-8")
        import yaml
        config = yaml.safe_load(content)

        # 验证必要字段
        if not config.get('tunnel'):
            return False, "配置缺少 tunnel 字段"
        if not config.get('credentials-file'):
            return False, "配置缺少 credentials-file 字段"
        if not config.get('ingress'):
            return False, "配置缺少 ingress 字段"

        # 验证ingress规则
        ingress = config['ingress']
        if not isinstance(ingress, list) or len(ingress) == 0:
            return False, "ingress 必须是非空列表"

        # 检查最后一个规则是否是默认规则
        last_rule = ingress[-1]
        if 'hostname' in last_rule:
            return False, "最后一个ingress规则应该是默认规则(不带hostname)"

        return True, f"配置文件验证通过 ({len(ingress)}条规则)"

    except yaml.YAMLError as e:
        return False, f"YAML格式错误: {str(e)}"
    except Exception as e:
        return False, f"验证配置时出错: {str(e)}"
