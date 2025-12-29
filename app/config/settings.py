#! -*- coding: utf-8 -*-
"""
应用程序配置管理
"""
import json
from pathlib import Path
from typing import Any, Optional

try:
    from ..utils.paths import get_config_dir
except Exception:
    try:
        from utils.paths import get_config_dir  # type: ignore
    except Exception:
        def get_config_dir() -> Path:  # type: ignore
            return Path.cwd() / "config"


class Settings:
    """应用设置管理器"""

    def __init__(self, config_file: Optional[Path] = None):
        self.config_file = config_file or (get_config_dir() / "app_config.json")
        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        self._settings = self._load_settings()

    def _load_settings(self) -> dict:
        """加载配置"""
        if self.config_file.exists():
            try:
                return json.loads(self.config_file.read_text(encoding="utf-8"))
            except Exception:
                pass
        return self._default_settings()

    def _default_settings(self) -> dict:
        """默认配置"""
        return {
            "window": {
                "width": 1200,
                "height": 700,
                "min_width": 1000,
                "min_height": 600,
                "remember_position": True,
                "x": None,
                "y": None
            },
            "cloudflared": {
                "path": "",
                "auto_find": True
            },
            "ui": {
                "theme": "modern",  # modern, classic
                "language": "zh_CN",
                "show_sidebar": True,
                "compact_mode": False
            },
            "log": {
                "max_lines": 1000,
                "auto_scroll": True,
                "show_timestamp": True,
                "level": "info"  # debug, info, warning, error
            },
            "tunnel": {
                "auto_route_dns": True,
                "save_last_selected": True,
                "last_selected": None,
                "persist_on_exit": False,
                "auto_start_enabled": False,
                "auto_start_tunnel": None
            }
        }

    def save(self):
        """保存配置"""
        try:
            self.config_file.write_text(
                json.dumps(self._settings, indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
        except Exception as e:
            print(f"保存配置失败: {e}")

    def get(self, key: str, default: Any = None) -> Any:
        """获取配置值 (支持点号路径)"""
        keys = key.split(".")
        value = self._settings
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default
        return value

    def set(self, key: str, value: Any):
        """设置配置值 (支持点号路径)"""
        keys = key.split(".")
        target = self._settings
        for k in keys[:-1]:
            if k not in target:
                target[k] = {}
            target = target[k]
        target[keys[-1]] = value
        self.save()

    def get_all(self) -> dict:
        """获取所有配置"""
        return self._settings.copy()

    def reset(self):
        """重置为默认配置"""
        self._settings = self._default_settings()
        self.save()
