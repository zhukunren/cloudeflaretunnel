#! -*- coding: utf-8 -*-
"""
经典配置编辑器

此模块实现经典 UI 中的 ConfigEditor，以便 modern_gui 的“编辑配置”功能可以复用
原有的快捷配置和 YAML 编辑体验。
"""

from __future__ import annotations

import os
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
    """内置 YAML 配置编辑器（含快捷配置）"""

    def __init__(self, parent, config_path: Path, tunnel_name: str, tunnel_id: str):
        super().__init__(parent)
        self.parent_window = parent
        self.config_path = Path(config_path)
        self.tunnel_name = tunnel_name
        self.tunnel_id = tunnel_id

        self.title(f"配置隧道 - {tunnel_name}")
        self.geometry("900x700")
        self.minsize(700, 500)

        # 设置为模态窗口，但不 grab，避免遮挡弹窗
        self.transient(parent)

        self._build_ui()
        self._load_config()

    def _build_ui(self):
        """构建快捷配置 + YAML 编辑界面"""
        main_container = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        main_container.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        left_panel = ttk.Frame(main_container)
        right_panel = ttk.Frame(main_container)
        main_container.add(left_panel, weight=1)
        main_container.add(right_panel, weight=2)

        ttk.Label(left_panel, text="⚡ 快捷配置", font=("", 12, "bold")).pack(pady=10)

        form_frame = ttk.LabelFrame(left_panel, text="基本设置", padding=10)
        form_frame.pack(fill=tk.BOTH, padx=10, pady=5)

        ttk.Label(form_frame, text="隧道ID:").grid(row=0, column=0, sticky=tk.W, pady=5)
        id_label = ttk.Label(form_frame, text=self.tunnel_id[:16] + "...", foreground="blue")
        id_label.grid(row=0, column=1, sticky=tk.W, pady=5)

        ttk.Label(form_frame, text="域名 (hostname):").grid(row=1, column=0, sticky=tk.W, pady=5)
        self.hostname_var = tk.StringVar()
        ttk.Entry(form_frame, textvariable=self.hostname_var, width=25).grid(
            row=1, column=1, sticky=tk.W + tk.E, pady=5, padx=5
        )

        ttk.Label(form_frame, text="本地端口:").grid(row=2, column=0, sticky=tk.W, pady=5)
        self.port_var = tk.StringVar(value="8080")
        ttk.Entry(form_frame, textvariable=self.port_var, width=25).grid(
            row=2, column=1, sticky=tk.W + tk.E, pady=5, padx=5
        )

        ttk.Label(form_frame, text="协议:").grid(row=3, column=0, sticky=tk.W, pady=5)
        self.protocol_var = tk.StringVar(value="http")
        protocol_frame = ttk.Frame(form_frame)
        protocol_frame.grid(row=3, column=1, sticky=tk.W, pady=5)
        ttk.Radiobutton(protocol_frame, text="HTTP", variable=self.protocol_var, value="http").pack(side=tk.LEFT)
        ttk.Radiobutton(protocol_frame, text="HTTPS", variable=self.protocol_var, value="https").pack(side=tk.LEFT, padx=5)

        form_frame.columnconfigure(1, weight=1)

        action_frame = ttk.LabelFrame(left_panel, text="快捷操作", padding=10)
        action_frame.pack(fill=tk.X, padx=10, pady=10)

        ttk.Button(action_frame, text="📝 应用快捷配置", command=self._apply_quick_config).pack(fill=tk.X, pady=3)
        ttk.Button(action_frame, text="🌐 配置DNS路由", command=self._setup_dns_route).pack(fill=tk.X, pady=3)
        ttk.Button(action_frame, text="🔄 重置为默认", command=self._reset_default).pack(fill=tk.X, pady=3)

        help_frame = ttk.LabelFrame(left_panel, text="💡 使用说明", padding=10)
        help_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        help_text = tk.Text(help_frame, wrap=tk.WORD, height=8, font=("", 9))
        help_text.pack(fill=tk.BOTH, expand=True)
        help_text.insert(
            "1.0",
            """使用步骤：

1. 填写域名与本地端口
2. 点击“应用快捷配置”生成 YAML
3. 点击“配置DNS路由”自动绑定域名
4. 保存配置并回到主界面启动隧道

提示：
- 域名示例: app.example.com
- 端口示例: 8080, 3000, 8501
- DNS 路由会自动调用 cloudflared 命令""",
        )
        help_text.config(state=tk.DISABLED)

        ttk.Label(right_panel, text="🛠 高级配置 (YAML)", font=("", 12, "bold")).pack(pady=10)

        toolbar = ttk.Frame(right_panel)
        toolbar.pack(fill=tk.X, padx=5, pady=5)

        ttk.Label(toolbar, text="配置文件:").pack(side=tk.LEFT)
        ttk.Label(toolbar, text=str(self.config_path.name), foreground="blue").pack(side=tk.LEFT, padx=5)

        ttk.Button(toolbar, text="💾 保存", command=self._save_config).pack(side=tk.RIGHT, padx=2)
        ttk.Button(toolbar, text="➕ 添加路由", command=self._add_route).pack(side=tk.RIGHT, padx=2)

        edit_frame = ttk.LabelFrame(right_panel, text="YAML配置内容")
        edit_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        scrollbar = ttk.Scrollbar(edit_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.text_editor = tk.Text(
            edit_frame,
            wrap=tk.NONE,
            yscrollcommand=scrollbar.set,
            font=("Consolas", 10),
            bg="#2B2B2B",
            fg="#A9B7C6",
            insertbackground="white",
            selectbackground="#214283",
        )
        self.text_editor.pack(fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.text_editor.yview)

        self.status_var = tk.StringVar(value="就绪")
        ttk.Label(self, textvariable=self.status_var, relief=tk.SUNKEN, anchor=tk.W).pack(fill=tk.X)

    def _load_config(self):
        """读取现有 YAML，并解析基础字段"""
        if self.config_path.exists():
            try:
                content = self.config_path.read_text(encoding="utf-8")
                self.text_editor.delete(1.0, tk.END)
                self.text_editor.insert(1.0, content)
                self._parse_config_to_form(content)
                self.status_var.set("配置已加载")
                return
            except Exception as exc:
                messagebox.showerror("错误", f"无法加载配置文件: {exc}", parent=self)
        self._reset_default(show_prompt=False)

    def _parse_config_to_form(self, content: str):
        """尝试从 YAML 中提取 hostname/service"""
        try:
            for line in content.splitlines():
                if "hostname:" in line and "example.com" not in line:
                    hostname = line.split("hostname:")[1].strip()
                    self.hostname_var.set(hostname)
                elif "service:" in line and "localhost" in line:
                    service = line.split("service:")[1].strip()
                    if "://" in service:
                        protocol, rest = service.split("://", 1)
                        self.protocol_var.set(protocol)
                        if ":" in rest:
                            port = rest.split(":")[-1].split("/")[0]
                            if port.isdigit():
                                self.port_var.set(port)
        except Exception:
            pass

    def _apply_quick_config(self):
        hostname = self.hostname_var.get().strip()
        port = self.port_var.get().strip()
        protocol = self.protocol_var.get()

        if not hostname:
            messagebox.showwarning("提示", "请填写域名！", parent=self)
            return
        if not port.isdigit():
            messagebox.showwarning("提示", "端口必须是数字！", parent=self)
            return

        service_url = f"{protocol}://localhost:{port}"
        config_content = (
            f"tunnel: {self.tunnel_id}\n"
            f"credentials-file: {cf.default_credentials_path(self.tunnel_id).as_posix()}\n"
            "ingress:\n"
            f"  - hostname: {hostname}\n"
            f"    service: {service_url}\n"
            "  - service: http_status:404\n"
        )

        self.text_editor.delete(1.0, tk.END)
        self.text_editor.insert(1.0, config_content)
        self.status_var.set(f"已生成配置: {hostname} -> {service_url}")
        messagebox.showinfo(
            "配置已生成",
            f"快捷配置已应用！\n\n域名: {hostname}\n服务: {service_url}\n\n请点击“保存”按钮保存配置。",
            parent=self,
        )

    def _setup_dns_route(self):
        hostname = self.hostname_var.get().strip()

        if not hostname:
            messagebox.showwarning("提示", "请先填写域名！", parent=self)
            return

        try:
            if hasattr(self.parent_window, "cloudflared_path"):
                path = self.parent_window.cloudflared_path.get().strip()
            else:
                path = cf.find_cloudflared()

            if not path:
                messagebox.showerror("错误", "未找到 cloudflared，请先设置路径！", parent=self)
                return

            self.status_var.set(f"正在配置DNS路由: {hostname}…")
            ok, out = cf.route_dns(path, self.tunnel_name, hostname)

            if ok:
                self.status_var.set(f"DNS路由配置成功: {hostname}")
                messagebox.showinfo(
                    "DNS路由成功",
                    f"域名 {hostname} 已成功绑定到隧道 {self.tunnel_name}！\n\n现在可以保存配置并启动隧道。",
                    parent=self,
                )
            else:
                if "already exists" in out:
                    messagebox.showwarning(
                        "DNS记录已存在",
                        "检测到 DNS 记录已存在。\n使用其他子域名或在 Cloudflare 控制台删除现有记录。",
                        parent=self,
                    )
                else:
                    messagebox.showerror("DNS路由失败", out, parent=self)
                self.status_var.set("DNS路由失败")

        except Exception as exc:
            messagebox.showerror("错误", f"配置DNS路由时出错: {exc}", parent=self)
            self.status_var.set("DNS路由失败")

    def _save_config(self):
        try:
            content = self.text_editor.get(1.0, tk.END).strip()
            if not content:
                messagebox.showwarning("警告", "配置内容不能为空", parent=self)
                return

            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            self.config_path.write_text(content + "\n", encoding="utf-8")
            self.status_var.set("配置已保存")

            self.attributes("-topmost", False)
            messagebox.showinfo("保存成功", "配置已保存！\n\n您现在可以关闭此窗口并启动隧道。", parent=self)
            self.attributes("-topmost", True)

        except Exception as exc:
            self.attributes("-topmost", False)
            messagebox.showerror("错误", f"保存失败: {exc}", parent=self)
            self.attributes("-topmost", True)
            self.status_var.set("保存失败")

    def _reset_default(self, show_prompt: bool = True):
        current_content = self.text_editor.get(1.0, tk.END).strip()
        if show_prompt and current_content:
            self.attributes("-topmost", False)
            response = messagebox.askyesno(
                "确认重置",
                "确定要重置为默认配置吗？\n\n当前的编辑内容将丢失！",
                parent=self,
            )
            self.attributes("-topmost", True)
            if not response:
                return

        default_config = (
            f"tunnel: {self.tunnel_id}\n"
            f"credentials-file: {cf.default_credentials_path(self.tunnel_id).as_posix()}\n"
            "ingress:\n"
            "  - hostname: app.example.com\n"
            "    service: http://localhost:8080\n"
            "  - service: http_status:404\n"
        )

        self.text_editor.delete("1.0", tk.END)
        self.text_editor.insert("1.0", default_config)

        self.hostname_var.set("")
        self.port_var.set("8080")
        self.protocol_var.set("http")

        self.status_var.set("已重置为默认配置")

        if show_prompt:
            self.attributes("-topmost", False)
            messagebox.showinfo("重置成功", "配置已重置为默认模板！\n\n请修改域名和端口后保存。", parent=self)
            self.attributes("-topmost", True)

    def _add_route(self):
        dialog = tk.Toplevel(self)
        dialog.title("添加路由规则")
        dialog.geometry("400x150")
        dialog.transient(self)
        dialog.grab_set()

        ttk.Label(dialog, text="主机名 (如: api.example.com):").grid(row=0, column=0, padx=5, pady=5, sticky=tk.W)
        hostname_entry = ttk.Entry(dialog, width=30)
        hostname_entry.grid(row=0, column=1, padx=5, pady=5)

        ttk.Label(dialog, text="本地服务 (如: http://localhost:3000):").grid(row=1, column=0, padx=5, pady=5, sticky=tk.W)
        service_entry = ttk.Entry(dialog, width=30)
        service_entry.grid(row=1, column=1, padx=5, pady=5)
        service_entry.insert(0, "http://localhost:8080")

        def add_to_config():
            hostname = hostname_entry.get().strip()
            service = service_entry.get().strip()
            if not hostname or not service:
                messagebox.showwarning("警告", "请填写完整信息", parent=dialog)
                return
            if service.endswith(":"):
                messagebox.showwarning("警告", "请填写完整的服务地址，例如 http://localhost:8080", parent=dialog)
                return

            content = self.text_editor.get(1.0, tk.END)
            lines = content.split("\n")

            insert_pos = -1
            for idx, line in enumerate(lines):
                if "service: http_status:404" in line:
                    insert_pos = idx
                    break

            if insert_pos > 0:
                new_rule = f"  - hostname: {hostname}\n    service: {service}"
                lines.insert(insert_pos, new_rule)
                self.text_editor.delete(1.0, tk.END)
                self.text_editor.insert(1.0, "\n".join(lines))
                self.status_var.set(f"已添加路由: {hostname} -> {service}")

            dialog.destroy()

        button_frame = ttk.Frame(dialog)
        button_frame.grid(row=2, column=0, columnspan=2, pady=10)
        ttk.Button(button_frame, text="添加", command=add_to_config).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="取消", command=dialog.destroy).pack(side=tk.LEFT, padx=5)

