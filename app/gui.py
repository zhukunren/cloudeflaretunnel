#! -*- coding: utf-8 -*-
"""
纯 YAML 配置编辑器

modern_gui 复用此模块打开隧道配置。
编辑器只负责 YAML 编辑、校验和保存，不再提供快捷配置或 DNS 路由入口。
"""

from __future__ import annotations

import os
import tempfile
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

try:
    from . import cloudflared_cli as cf
except Exception:
    import sys

    sys.path.append(os.path.dirname(__file__))
    import cloudflared_cli as cf  # type: ignore


class ConfigEditor(tk.Toplevel):
    """内置 YAML 配置编辑器"""

    def __init__(self, parent, config_path: Path, tunnel_name: str, tunnel_id: str):
        super().__init__(parent)
        self.config_path = Path(config_path)
        self.tunnel_name = tunnel_name
        self.tunnel_id = tunnel_id

        self.title(f"配置隧道 - {tunnel_name}")
        self.geometry("880x680")
        self.minsize(720, 520)

        self.transient(parent)

        self._build_ui()
        self._load_config()
        self.bind("<Control-s>", self._on_ctrl_s)

    def _build_ui(self):
        """构建纯 YAML 编辑界面"""
        main_container = ttk.Frame(self, padding=8)
        main_container.pack(fill=tk.BOTH, expand=True)

        header = ttk.Frame(main_container)
        header.pack(fill=tk.X, pady=(0, 8))

        ttk.Label(header, text="YAML 配置", font=("", 12, "bold")).pack(side=tk.LEFT)
        ttk.Label(header, text=self.config_path.name, foreground="blue").pack(side=tk.LEFT, padx=(8, 0))

        action_bar = ttk.Frame(header)
        action_bar.pack(side=tk.RIGHT)
        ttk.Button(action_bar, text="关闭", command=self.destroy).pack(side=tk.RIGHT)
        ttk.Button(action_bar, text="保存", command=self._save_config).pack(side=tk.RIGHT, padx=(6, 0))
        ttk.Button(action_bar, text="验证", command=self._validate_config).pack(side=tk.RIGHT, padx=(6, 0))

        ttk.Label(
            main_container,
            text="直接编辑完整 config.yml。启动时会按配置自动补齐 DNS 路由。",
            foreground="gray",
        ).pack(anchor=tk.W, pady=(0, 8))

        edit_frame = ttk.Frame(main_container)
        edit_frame.pack(fill=tk.BOTH, expand=True)

        y_scrollbar = ttk.Scrollbar(edit_frame, orient=tk.VERTICAL)
        y_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        x_scrollbar = ttk.Scrollbar(edit_frame, orient=tk.HORIZONTAL)
        x_scrollbar.pack(side=tk.BOTTOM, fill=tk.X)

        self.text_editor = tk.Text(
            edit_frame,
            wrap=tk.NONE,
            yscrollcommand=y_scrollbar.set,
            xscrollcommand=x_scrollbar.set,
            font=("Consolas", 10),
            bg="#2B2B2B",
            fg="#A9B7C6",
            insertbackground="white",
            selectbackground="#214283",
        )
        self.text_editor.pack(fill=tk.BOTH, expand=True)
        y_scrollbar.config(command=self.text_editor.yview)
        x_scrollbar.config(command=self.text_editor.xview)

        self.status_var = tk.StringVar(value="就绪")
        ttk.Label(self, textvariable=self.status_var, relief=tk.SUNKEN, anchor=tk.W).pack(fill=tk.X)

    def _load_config(self):
        """读取现有 YAML，缺失时填入默认模板"""
        if self.config_path.exists():
            try:
                content = self.config_path.read_text(encoding="utf-8")
                self.text_editor.delete(1.0, tk.END)
                self.text_editor.insert(1.0, content)
                self.status_var.set("配置已加载")
                return
            except Exception as exc:
                messagebox.showerror("错误", f"无法加载配置文件: {exc}", parent=self)
        self.text_editor.delete(1.0, tk.END)
        self.text_editor.insert(1.0, self._default_config_text())
        self.status_var.set("已载入默认模板（尚未保存）")

    def _default_config_text(self) -> str:
        return (
            f"tunnel: {self.tunnel_id}\n"
            f"credentials-file: {cf.default_credentials_path(self.tunnel_id).as_posix()}\n"
            "ingress:\n"
            "  - hostname: app.example.com\n"
            "    service: http://localhost:8080\n"
            "  - service: http_status:404\n"
        )

    def _editor_content(self) -> str:
        return self.text_editor.get(1.0, tk.END).strip()

    def _validate_content(self, content: str) -> tuple[bool, str]:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir) / "config.yml"
            temp_path.write_text(content + "\n", encoding="utf-8")
            return cf.validate_config(temp_path)

    def _validate_config(self):
        content = self._editor_content()
        if not content:
            messagebox.showwarning("提示", "配置内容不能为空", parent=self)
            return

        ok, message = self._validate_content(content)
        self.status_var.set(message)
        if ok:
            messagebox.showinfo("验证通过", message, parent=self)
        else:
            messagebox.showerror("验证失败", message, parent=self)

    def _save_config(self):
        try:
            content = self._editor_content()
            if not content:
                messagebox.showwarning("警告", "配置内容不能为空", parent=self)
                return

            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            self.config_path.write_text(content + "\n", encoding="utf-8")
            ok, message = self._validate_content(content)
            self.status_var.set("配置已保存" if ok else f"配置已保存，{message}")

            if ok:
                messagebox.showinfo("保存成功", "配置已保存并通过验证。", parent=self)
            else:
                messagebox.showwarning("保存成功", f"配置已保存，但校验未通过：\n\n{message}", parent=self)

        except Exception as exc:
            messagebox.showerror("错误", f"保存失败: {exc}", parent=self)
            self.status_var.set("保存失败")

    def _on_ctrl_s(self, _event=None):
        self._save_config()
        return "break"
