from __future__ import annotations

import os
from pathlib import Path

ENV_PROJECT_ROOT = "TUNNEL_MANAGER_ROOT"


def get_repo_root() -> Path:
    """返回仓库根目录（包含 app/、config/、tunnels/、logs/ 的目录）。"""
    env_root = os.environ.get(ENV_PROJECT_ROOT)
    if env_root:
        candidate = Path(env_root).expanduser()
        try:
            candidate = candidate.resolve()
        except Exception:
            candidate = candidate.absolute()
        if candidate.exists():
            return candidate

    # app/utils/paths.py -> app/utils -> app -> repo root
    return Path(__file__).resolve().parents[2]


def get_config_dir() -> Path:
    return get_repo_root() / "config"


def get_logs_dir() -> Path:
    return get_repo_root() / "logs"


def get_persistent_logs_dir() -> Path:
    return get_logs_dir() / "persistent"


def get_tunnels_dir() -> Path:
    return get_repo_root() / "tunnels"

