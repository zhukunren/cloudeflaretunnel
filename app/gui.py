#! -*- coding: utf-8 -*-
import threading
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog, filedialog
from pathlib import Path
import queue
import platform
import urllib.request
import urllib.error
import os

try:
    from . import cloudflared_cli as cf
except Exception:
    # Support running as a standalone script
    import sys
    sys.path.append(os.path.dirname(__file__))
    import cloudflared_cli as cf


APP_TITLE = "Cloudflare 内网穿透管理器"
BASE_DIR = Path.cwd()
TUNNELS_DIR = BASE_DIR / "tunnels"


class ConfigEditor(tk.Toplevel):
    """内置的YAML配置编辑器 - 增强版"""
    def __init__(self, parent, config_path: Path, tunnel_name: str, tunnel_id: str):
        super().__init__(parent)
        self.parent_window = parent
        self.config_path = config_path
        self.tunnel_name = tunnel_name
        self.tunnel_id = tunnel_id

        self.title(f"配置隧道 - {tunnel_name}")
        self.geometry("900x700")
        self.minsize(700, 500)

        # 设置为模态窗口，但不grab，避免遮挡弹窗
        self.transient(parent)
        # 不使用 grab_set()，让弹窗可以显示在最前面

        self._build_ui()
        self._load_config()

    def _build_ui(self):
        """构建编辑器UI - 增强版"""
        # ========== 左侧：快捷配置面板 ==========
        main_container = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        main_container.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        left_panel = ttk.Frame(main_container)
        right_panel = ttk.Frame(main_container)
        main_container.add(left_panel, weight=1)
        main_container.add(right_panel, weight=2)

        # 左侧：快捷配置
        ttk.Label(left_panel, text="⚡ 快捷配置", font=("", 12, "bold")).pack(pady=10)

        # 快捷配置表单
        form_frame = ttk.LabelFrame(left_panel, text="基本设置", padding=10)
        form_frame.pack(fill=tk.BOTH, padx=10, pady=5)

        # 隧道ID（只读）
        ttk.Label(form_frame, text="隧道ID:").grid(row=0, column=0, sticky=tk.W, pady=5)
        id_label = ttk.Label(form_frame, text=self.tunnel_id[:16]+"...", foreground="blue")
        id_label.grid(row=0, column=1, sticky=tk.W, pady=5)

        # 域名配置
        ttk.Label(form_frame, text="域名 (hostname):").grid(row=1, column=0, sticky=tk.W, pady=5)
        self.hostname_var = tk.StringVar()
        hostname_entry = ttk.Entry(form_frame, textvariable=self.hostname_var, width=25)
        hostname_entry.grid(row=1, column=1, sticky=tk.W+tk.E, pady=5, padx=5)

        # 本地服务端口
        ttk.Label(form_frame, text="本地端口:").grid(row=2, column=0, sticky=tk.W, pady=5)
        self.port_var = tk.StringVar(value="8080")
        port_entry = ttk.Entry(form_frame, textvariable=self.port_var, width=25)
        port_entry.grid(row=2, column=1, sticky=tk.W+tk.E, pady=5, padx=5)

        # 协议选择
        ttk.Label(form_frame, text="协议:").grid(row=3, column=0, sticky=tk.W, pady=5)
        self.protocol_var = tk.StringVar(value="http")
        protocol_frame = ttk.Frame(form_frame)
        protocol_frame.grid(row=3, column=1, sticky=tk.W, pady=5)
        ttk.Radiobutton(protocol_frame, text="HTTP", variable=self.protocol_var, value="http").pack(side=tk.LEFT)
        ttk.Radiobutton(protocol_frame, text="HTTPS", variable=self.protocol_var, value="https").pack(side=tk.LEFT, padx=5)

        form_frame.columnconfigure(1, weight=1)

        # 快捷操作按钮
        action_frame = ttk.LabelFrame(left_panel, text="快捷操作", padding=10)
        action_frame.pack(fill=tk.X, padx=10, pady=10)

        ttk.Button(
            action_frame,
            text="📝 应用快捷配置",
            command=self._apply_quick_config
        ).pack(fill=tk.X, pady=3)

        ttk.Button(
            action_frame,
            text="🌐 配置DNS路由",
            command=self._setup_dns_route
        ).pack(fill=tk.X, pady=3)

        ttk.Button(
            action_frame,
            text="🔄 重置为默认",
            command=self._reset_default
        ).pack(fill=tk.X, pady=3)

        # 说明文本
        help_frame = ttk.LabelFrame(left_panel, text="💡 使用说明", padding=10)
        help_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        help_text = tk.Text(help_frame, wrap=tk.WORD, height=8, font=("", 9))
        help_text.pack(fill=tk.BOTH, expand=True)
        help_text.insert("1.0", """使用步骤：

1. 填写您的域名和本地端口
2. 点击"应用快捷配置"生成配置
3. 点击"配置DNS路由"自动绑定域名
4. 保存配置并启动隧道

提示：
- 域名示例: app.example.com
- 端口示例: 8080, 3000, 8501
- DNS路由会自动调用cloudflared命令""")
        help_text.config(state=tk.DISABLED)

        # ========== 右侧：高级配置编辑器 ==========
        ttk.Label(right_panel, text="🛠 高级配置 (YAML)", font=("", 12, "bold")).pack(pady=10)

        # 工具栏
        toolbar = ttk.Frame(right_panel)
        toolbar.pack(fill=tk.X, padx=5, pady=5)

        ttk.Label(toolbar, text="配置文件:").pack(side=tk.LEFT)
        ttk.Label(toolbar, text=str(self.config_path.name), foreground="blue").pack(side=tk.LEFT, padx=5)

        ttk.Button(toolbar, text="💾 保存", command=self._save_config).pack(side=tk.RIGHT, padx=2)
        ttk.Button(toolbar, text="➕ 添加路由", command=self._add_route).pack(side=tk.RIGHT, padx=2)

        # YAML编辑区
        edit_frame = ttk.LabelFrame(right_panel, text="YAML配置内容")
        edit_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # 添加滚动条
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
            selectbackground="#214283"
        )
        self.text_editor.pack(fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.text_editor.yview)

        # 状态栏
        self.status_var = tk.StringVar(value="就绪")
        status_bar = ttk.Label(self, textvariable=self.status_var, relief=tk.SUNKEN, anchor=tk.W)
        status_bar.pack(fill=tk.X)

    def _load_config(self):
        """加载配置文件并解析到快捷配置"""
        if self.config_path.exists():
            try:
                content = self.config_path.read_text(encoding="utf-8")
                self.text_editor.delete(1.0, tk.END)
                self.text_editor.insert(1.0, content)

                # 尝试解析现有配置到快捷表单
                self._parse_config_to_form(content)

                self.status_var.set("配置已加载")
            except Exception as e:
                messagebox.showerror("错误", f"无法加载配置文件: {e}", parent=self)
                self._reset_default()
        else:
            self._reset_default()

    def _parse_config_to_form(self, content):
        """从YAML内容解析到表单"""
        try:
            lines = content.split('\n')
            for line in lines:
                if 'hostname:' in line and 'example.com' not in line:
                    hostname = line.split('hostname:')[1].strip()
                    self.hostname_var.set(hostname)
                elif 'service:' in line and 'localhost' in line:
                    # 解析 http://localhost:8080
                    service = line.split('service:')[1].strip()
                    if '://' in service:
                        protocol, rest = service.split('://', 1)
                        self.protocol_var.set(protocol)
                        if ':' in rest:
                            port = rest.split(':')[-1].split('/')[0]
                            self.port_var.set(port)
        except Exception:
            pass  # 解析失败就使用默认值

    def _apply_quick_config(self):
        """应用快捷配置到YAML"""
        hostname = self.hostname_var.get().strip()
        port = self.port_var.get().strip()
        protocol = self.protocol_var.get()

        if not hostname:
            messagebox.showwarning("提示", "请填写域名！", parent=self)
            return

        if not port.isdigit():
            messagebox.showwarning("提示", "端口必须是数字！", parent=self)
            return

        # 生成配置
        service_url = f"{protocol}://localhost:{port}"

        config_content = f"""tunnel: {self.tunnel_id}
credentials-file: {cf.default_credentials_path(self.tunnel_id).as_posix()}
ingress:
  - hostname: {hostname}
    service: {service_url}
  - service: http_status:404
"""

        # 更新编辑器
        self.text_editor.delete(1.0, tk.END)
        self.text_editor.insert(1.0, config_content)

        self.status_var.set(f"已生成配置: {hostname} -> {service_url}")
        messagebox.showinfo(
            "配置已生成",
            f"快捷配置已应用！\n\n域名: {hostname}\n服务: {service_url}\n\n请点击'保存'按钮保存配置。",
            parent=self
        )

    def _setup_dns_route(self):
        """配置DNS路由 - 整合功能"""
        hostname = self.hostname_var.get().strip()

        if not hostname:
            messagebox.showwarning("提示", "请先填写域名！", parent=self)
            return

        # 获取cloudflared路径
        try:
            # 从父窗口获取路径
            if hasattr(self.parent_window, 'cloudflared_path'):
                path = self.parent_window.cloudflared_path.get().strip()
            else:
                path = cf.find_cloudflared()

            if not path:
                messagebox.showerror("错误", "未找到cloudflared，请先设置路径！", parent=self)
                return

            self.status_var.set(f"正在配置DNS路由: {hostname}...")

            # 调用DNS路由命令
            ok, out = cf.route_dns(path, self.tunnel_name, hostname)

            if ok:
                self.status_var.set(f"DNS路由配置成功: {hostname}")
                messagebox.showinfo(
                    "DNS路由成功",
                    f"域名 {hostname} 已成功绑定到隧道 {self.tunnel_name}！\n\n"
                    f"现在可以保存配置并启动隧道。",
                    parent=self
                )
            else:
                if "already exists" in out:
                    messagebox.showwarning(
                        "DNS记录已存在",
                        f"域名 {hostname} 的DNS记录已存在！\n\n"
                        f"如果要使用此域名，请：\n"
                        f"1. 使用不同的子域名，或\n"
                        f"2. 在Cloudflare控制台删除现有记录",
                        parent=self
                    )
                else:
                    messagebox.showerror("DNS路由失败", out, parent=self)
                self.status_var.set("DNS路由失败")

        except Exception as e:
            messagebox.showerror("错误", f"配置DNS路由时出错: {e}", parent=self)
            self.status_var.set("DNS路由失败")

    def _save_config(self):
        """保存配置 - 修复弹窗遮挡问题"""
        try:
            content = self.text_editor.get(1.0, tk.END).strip()
            if not content:
                messagebox.showwarning("警告", "配置内容不能为空", parent=self)
                return

            # 创建目录
            self.config_path.parent.mkdir(parents=True, exist_ok=True)

            # 保存文件
            self.config_path.write_text(content + "\n", encoding="utf-8")
            self.status_var.set("配置已保存")

            # 确保弹窗显示在最前面
            self.attributes('-topmost', False)  # 临时取消置顶
            messagebox.showinfo("保存成功", "配置已保存！\n\n您现在可以关闭此窗口并启动隧道。", parent=self)
            self.attributes('-topmost', True)   # 恢复

        except Exception as e:
            self.attributes('-topmost', False)
            messagebox.showerror("错误", f"保存失败: {e}", parent=self)
            self.attributes('-topmost', True)
            self.status_var.set("保存失败")

    def _reset_default(self):
        """重置为默认配置 - 修复bug"""
        current_content = self.text_editor.get(1.0, tk.END).strip()

        # 如果已有内容，先确认
        if current_content:
            self.attributes('-topmost', False)
            response = messagebox.askyesno(
                "确认重置",
                "确定要重置为默认配置吗？\n\n当前的编辑内容将丢失！",
                parent=self
            )
            self.attributes('-topmost', True)

            if not response:
                return

        # 生成默认配置
        default_config = f"""tunnel: {self.tunnel_id}
credentials-file: {cf.default_credentials_path(self.tunnel_id).as_posix()}
ingress:
  - hostname: app.example.com
    service: http://localhost:8080
  - service: http_status:404
"""

        # 清空并插入新内容
        self.text_editor.delete("1.0", tk.END)
        self.text_editor.insert("1.0", default_config)

        # 重置表单
        self.hostname_var.set("")
        self.port_var.set("8080")
        self.protocol_var.set("http")

        self.status_var.set("已重置为默认配置")

        self.attributes('-topmost', False)
        messagebox.showinfo("重置成功", "配置已重置为默认模板！\n\n请修改域名和端口后保存。", parent=self)
        self.attributes('-topmost', True)

    def _add_route(self):
        """添加新路由规则"""
        # 弹出对话框获取信息
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

            # 获取当前配置
            content = self.text_editor.get(1.0, tk.END)
            lines = content.split('\n')

            # 查找插入位置（在最后的 service: http_status:404 之前）
            insert_pos = -1
            for i, line in enumerate(lines):
                if 'service: http_status:404' in line:
                    insert_pos = i
                    break

            if insert_pos > 0:
                # 插入新规则
                new_rule = f"  - hostname: {hostname}\n    service: {service}"
                lines.insert(insert_pos, new_rule)

                # 更新编辑器
                self.text_editor.delete(1.0, tk.END)
                self.text_editor.insert(1.0, '\n'.join(lines))
                self.status_var.set(f"已添加路由: {hostname} -> {service}")

            dialog.destroy()

        button_frame = ttk.Frame(dialog)
        button_frame.grid(row=2, column=0, columnspan=2, pady=10)
        ttk.Button(button_frame, text="添加", command=add_to_config).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="取消", command=dialog.destroy).pack(side=tk.LEFT, padx=5)


class TunnelManagerApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("900x600")
        self.minsize(840, 520)

        self.cloudflared_path = tk.StringVar(value=cf.find_cloudflared() or "")
        self.status_var = tk.StringVar(value="Ready")

        self.proc = None
        self.proc_thread = None
        self.proc_queue = queue.Queue()

        self._build_ui()
        self._refresh_version()
        self.refresh_tunnels()

        self.after(150, self._drain_proc_queue)

    def _build_ui(self):
        top = ttk.Frame(self, name="topbar")
        top.pack(fill=tk.X, padx=8, pady=6)

        ttk.Label(top, text="cloudflared 路径:").pack(side=tk.LEFT)
        path_entry = ttk.Entry(top, textvariable=self.cloudflared_path, width=60)
        path_entry.pack(side=tk.LEFT, padx=6)
        ttk.Button(top, text="下载", command=self._download_cloudflared).pack(side=tk.LEFT)
        ttk.Button(top, text="检查更新", command=self._check_update_cloudflared).pack(side=tk.LEFT, padx=(4, 0))
        ttk.Button(top, text="浏览", command=self._choose_cloudflared).pack(side=tk.LEFT)
        ttk.Button(top, text="登录", command=self._login).pack(side=tk.LEFT, padx=(12, 0))
        ttk.Button(top, text="检测版本", command=self._refresh_version).pack(side=tk.LEFT, padx=6)

        self.version_label = ttk.Label(top, text="")
        self.version_label.pack(side=tk.LEFT, padx=10)

        main = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        main.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)

        left = ttk.Frame(main)
        right = ttk.Frame(main)
        main.add(left, weight=1)
        main.add(right, weight=2)

        toolbar = ttk.Frame(left)
        toolbar.pack(fill=tk.X)
        ttk.Button(toolbar, text="刷新", command=self.refresh_tunnels).pack(side=tk.LEFT)
        ttk.Button(toolbar, text="新建隧道", command=self._create_tunnel).pack(side=tk.LEFT, padx=6)
        ttk.Button(toolbar, text="删除选中", command=self._delete_selected).pack(side=tk.LEFT, padx=6)
        ttk.Button(toolbar, text="编辑配置", command=self._edit_selected_config).pack(side=tk.LEFT, padx=6)

        self.tunnel_list = tk.Listbox(left, exportselection=False)
        self.tunnel_list.pack(fill=tk.BOTH, expand=True, pady=(6, 0))
        self.tunnel_list.bind("<<ListboxSelect>>", lambda e: self._on_select())

        right_top = ttk.Frame(right)
        right_top.pack(fill=tk.X)
        ttk.Button(right_top, text="启动", command=self._start_selected).pack(side=tk.LEFT)
        ttk.Button(right_top, text="停止", command=self._stop_running).pack(side=tk.LEFT, padx=6)
        ttk.Button(right_top, text="测试", command=self._test_tunnel).pack(side=tk.LEFT, padx=6)
        ttk.Button(right_top, text="DNS 路由", command=self._route_dns_selected).pack(side=tk.LEFT, padx=6)
        ttk.Button(right_top, text="打开配置目录", command=self._open_config_dir).pack(side=tk.LEFT, padx=6)

        self.log = tk.Text(right, height=18)
        self.log.pack(fill=tk.BOTH, expand=True, pady=(6, 0))

        status = ttk.Frame(self)
        status.pack(fill=tk.X, padx=8, pady=6)
        ttk.Label(status, textvariable=self.status_var).pack(side=tk.LEFT)

    def _choose_cloudflared(self):
        initial = self.cloudflared_path.get() or ("cloudflared.exe" if cf._is_windows() else "cloudflared")
        file = filedialog.askopenfilename(title="选择 cloudflared 可执行文件", initialfile=initial)
        if file:
            self.cloudflared_path.set(file)
            self._refresh_version()

    def _guess_download_url(self) -> str:
        system = platform.system().lower()
        arch = (platform.machine() or "").lower()
        if system.startswith("win"):
            if "arm" in arch and "64" in arch:
                return "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-arm64.exe"
            else:
                return "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe"
        if system == "darwin":
            if "arm" in arch:
                return "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-darwin-arm64.tgz"
            return "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-darwin-amd64.tgz"
        if "arm" in arch and "64" in arch:
            return "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64"
        return "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64"

    def _download_cloudflared(self):
        url = self._guess_download_url()
        default_name = "cloudflared.exe" if cf._is_windows() else "cloudflared"
        save_path = filedialog.asksaveasfilename(title="保存 cloudflared 可执行文件", initialfile=default_name)
        if not save_path:
            return

        def _worker():
            try:
                self.status_var.set("下载中…")
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req) as resp:
                    total = int(resp.headers.get("Content-Length", "0"))
                    read = 0
                    chunk = 1024 * 64
                    with open(save_path, "wb") as f:
                        while True:
                            data = resp.read(chunk)
                            if not data:
                                break
                            f.write(data)
                            read += len(data)
                            if total:
                                pct = int(read * 100 / total)
                                self.status_var.set(f"下载中… {pct}%")
                if not cf._is_windows():
                    try:
                        os.chmod(save_path, 0o755)
                    except Exception:
                        pass
                self.cloudflared_path.set(save_path)
                self._append_log(f"已下载: {save_path}\n")
                self._refresh_version()
                self.status_var.set("下载完成")
            except urllib.error.URLError as e:
                messagebox.showerror("下载失败", f"无法下载 cloudflared:\n{e}")
                self.status_var.set("下载失败")
            except Exception as e:
                messagebox.showerror("下载失败", str(e))
                self.status_var.set("下载失败")

        threading.Thread(target=_worker, daemon=True).start()

    def _check_update_cloudflared(self):
        if cf._is_windows():
            messagebox.showinfo("检查更新", "该功能仅适用于 Linux/macOS 版本。")
            return

        target = Path.cwd() / "cloudflared"
        self.status_var.set("检查更新中…")

        def progress(pct: int):
            self.after(0, lambda: self.status_var.set(f"下载中… {pct}%"))

        def _worker():
            ok, msg, version = cf.download_cloudflared_linux(target, progress_cb=progress)

            def _finish():
                cert_ok, cert_detail = self._cert_status_detail()
                cert_append = f"\n\n证书状态：\n{cert_detail}"
                if ok:
                    self.cloudflared_path.set(str(target))
                    self._refresh_version()
                    extra = f"\n版本: {version}" if version else ""
                    self._append_log(f"{msg}{extra}\n")
                    dialog = messagebox.showinfo if cert_ok else messagebox.showwarning
                    title = "更新完成" if cert_ok else "更新完成（需登录）"
                    dialog(title, msg + extra + cert_append)
                    self.status_var.set("更新完成" if cert_ok else "缺少认证")
                else:
                    self._append_log(f"{msg}\n")
                    messagebox.showerror("更新失败", msg + cert_append)
                    self.status_var.set("更新失败")
                self._append_log(cert_detail + "\n")

            self.after(0, _finish)

        threading.Thread(target=_worker, daemon=True).start()

    def _cert_status_detail(self) -> tuple[bool, str]:
        exists, cert_path, updated = cf.origin_cert_status(None)
        if exists and cert_path:
            detail = f"认证证书已就绪：{cert_path}"
            if updated:
                detail += f"\n最后更新：{updated}"
        else:
            detail = "未找到 Cloudflare 认证证书 cert.pem，请点击“登录”完成授权。"
        return exists, detail

    def _refresh_version(self):
        path = self.cloudflared_path.get().strip()
        if not path:
            self.version_label.config(text="未找到 cloudflared")
            return
        ver = cf.version(path)
        self.version_label.config(text=ver or "无法获取版本")

    def _login(self):
        path = self.cloudflared_path.get().strip()
        if not path:
            messagebox.showerror("错误", "请先设置 cloudflared 路径")
            return

        # 检查是否已存在认证文件
        cert_path = Path.home() / ".cloudflared" / "cert.pem"
        if cert_path.exists():
            response = messagebox.askyesno(
                "已存在认证",
                "检测到已存在 Cloudflare 认证文件。\n"
                "是否要删除现有认证并重新登录？\n\n"
                "选择'是'将删除现有认证重新登录\n"
                "选择'否'将跳过登录（使用现有认证）"
            )
            if response:
                try:
                    cert_path.unlink()
                    self._append_log("已删除旧认证文件\n")
                except Exception as e:
                    messagebox.showerror("错误", f"无法删除认证文件：{e}")
                    return
            else:
                self.status_var.set("使用现有认证")
                return

        try:
            proc = cf.login(path)
        except cf.CloudflaredBinaryError as e:
            messagebox.showerror("无法登录", str(e))
            return
        self.status_var.set("已启动登录流程，请在浏览器中完成授权…")
        self.after(2000, lambda: self.status_var.set("Ready"))

    def refresh_tunnels(self):
        path = self.cloudflared_path.get().strip()
        self.tunnel_list.delete(0, tk.END)
        if not path:
            return
        try:
            data = cf.list_tunnels(path)
        except cf.CloudflaredBinaryError as e:
            messagebox.showerror("cloudflared 不可用", str(e))
            self.status_var.set("cloudflared 不可用")
            return
        self._tunnels = data
        for item in data:
            name = item.get("name") or item.get("tunnel name") or item.get("col1") or "<unknown>"
            tid = cf.extract_tunnel_id(item) or "?"
            self.tunnel_list.insert(tk.END, f"{name}  ({tid})")
        self.status_var.set(f"共 {len(data)} 个隧道")

    def _get_selected(self):
        sel = self.tunnel_list.curselection()
        if not sel:
            return None
        idx = sel[0]
        return self._tunnels[idx]

    def _on_select(self):
        item = self._get_selected()
        if not item:
            return
        name = item.get("name") or item.get("tunnel name") or item.get("col1") or "<unknown>"
        tid = cf.extract_tunnel_id(item) or "?"
        self._append_log(f"选中: {name} ({tid})\n")

    def _create_tunnel(self):
        path = self.cloudflared_path.get().strip()
        if not path:
            messagebox.showerror("错误", "请先设置 cloudflared 路径")
            return
        cert = cf.find_origin_cert(None)
        if cert is None:
            messagebox.showerror(
                "缺少认证",
                "未找到 Cloudflare 认证证书 cert.pem。\n请先点击“登录”完成授权。",
            )
            return
        name = simpledialog.askstring("新建隧道", "请输入隧道名称:")
        if not name:
            return
        ok, out = cf.create_tunnel(path, name, cert)
        if not ok:
            messagebox.showerror("创建失败", out)
            return
        self._append_log(out + "\n")
        self.refresh_tunnels()

    def _delete_selected(self):
        path = self.cloudflared_path.get().strip()
        item = self._get_selected()
        if not (path and item):
            return
        name = item.get("name") or item.get("tunnel name") or item.get("col1")
        if not name:
            return
        if not messagebox.askyesno("确认删除", f"确定删除隧道 {name} ?"):
            return
        ok, out = cf.delete_tunnel(path, name)
        if not ok:
            messagebox.showerror("删除失败", out)
            return
        self._append_log(out + "\n")
        self.refresh_tunnels()

    def _config_path_for(self, tunnel_name: str) -> Path:
        return TUNNELS_DIR / tunnel_name / "config.yml"

    def _edit_selected_config(self):
        item = self._get_selected()
        if not item:
            messagebox.showinfo("提示", "请先选择一个隧道")
            return
        name = item.get("name") or item.get("tunnel name") or item.get("col1") or "unknown"
        tid = cf.extract_tunnel_id(item)

        if not tid:
            messagebox.showerror("错误", "无法获取隧道ID")
            return

        cfg = self._config_path_for(name)

        # 打开内置配置编辑器
        editor = ConfigEditor(self, cfg, name, tid)
        self.wait_window(editor)  # 等待编辑器窗口关闭

        # 编辑器关闭后，可以添加一些后续操作
        self._append_log(f"配置编辑完成: {name}\n")

    def _start_selected(self):
        if self.proc is not None:
            messagebox.showinfo("提示", "已有隧道运行中，请先停止")
            return
        path = self.cloudflared_path.get().strip()
        item = self._get_selected()
        if not (path and item):
            return
        name = item.get("name") or item.get("tunnel name") or item.get("col1") or "unknown"
        cfg = self._config_path_for(name)
        if not cfg.exists():
            tid = cf.extract_tunnel_id(item)
            if tid:
                cf.write_basic_config(cfg, name, tid)
        self._append_log(f"启动隧道: {name}\n")
        try:
            self.proc = cf.run_tunnel(path, name, cfg)
        except Exception as e:
            self._append_log(f"启动失败: {e}\n")
            if isinstance(e, cf.CloudflaredBinaryError):
                messagebox.showerror("启动失败", str(e))
            self.proc = None
            return
        self.proc_thread = threading.Thread(target=self._read_proc_output, daemon=True)
        self.proc_thread.start()
        self.status_var.set(f"运行中: {name}")

    def _stop_running(self):
        if not self.proc:
            return
        try:
            cf.stop_process(self.proc)
        except Exception:
            pass
        self.proc = None
        self.status_var.set("已停止")

    def _read_proc_output(self):
        try:
            assert self.proc is not None
            for line in self.proc.stdout:
                self.proc_queue.put(line)
        except Exception:
            pass

    def _drain_proc_queue(self):
        drained = False
        while True:
            try:
                line = self.proc_queue.get_nowait()
            except queue.Empty:
                break
            self._append_log(line)
            drained = True
        if drained:
            self.log.see(tk.END)
        self.after(200, self._drain_proc_queue)

    def _open_config_dir(self):
        TUNNELS_DIR.mkdir(parents=True, exist_ok=True)
        try:
            if cf._is_windows():
                os.startfile(str(TUNNELS_DIR))
            else:
                import subprocess
                subprocess.Popen(["xdg-open", str(TUNNELS_DIR)])
        except Exception:
            messagebox.showinfo("目录", f"配置目录: {TUNNELS_DIR}")

    def _append_log(self, text: str):
        self.log.insert(tk.END, text)

    def _route_dns_selected(self):
        path = self.cloudflared_path.get().strip()
        item = self._get_selected()
        if not (path and item):
            messagebox.showinfo("提示", "请先选择隧道并设置 cloudflared 路径")
            return
        name = item.get("name") or item.get("tunnel name") or item.get("col1") or ""
        if not name:
            messagebox.showerror("错误", "无法获取隧道名称")
            return
        hostname = simpledialog.askstring("DNS 路由", "输入要绑定的主机名 (例如: app.example.com)")
        if not hostname:
            return
        ok, out = cf.route_dns(path, name, hostname)
        if ok:
            self._append_log(f"已路由 {hostname} -> {name}\n{out}\n")
            messagebox.showinfo("成功", f"已为 {name} 绑定 {hostname}")
        else:
            self._append_log(out + "\n")
            # 解析常见错误并提供友好提示
            if "already exists" in out:
                error_msg = (
                    f"DNS记录 {hostname} 已存在！\n\n"
                    "可能的原因：\n"
                    "1. 该域名已绑定到其他隧道\n"
                    "2. 该域名已有A/AAAA/CNAME记录\n\n"
                    "解决方案：\n"
                    "1. 使用不同的子域名\n"
                    "2. 在Cloudflare控制台删除现有DNS记录\n"
                    "3. 如果要更换隧道，先删除旧的DNS记录"
                )
                messagebox.showerror("DNS记录已存在", error_msg)
            elif "1003" in out:
                messagebox.showerror("DNS冲突",
                    f"无法创建DNS记录，{hostname} 与现有记录冲突。\n"
                    "请检查Cloudflare DNS设置。")
            else:
                messagebox.showerror("失败", out)

    def _test_tunnel(self):
        """测试隧道功能"""
        path = self.cloudflared_path.get().strip()
        if not path:
            messagebox.showwarning("提示", "请先设置 cloudflared 路径")
            return

        item = self._get_selected()
        if not item:
            messagebox.showwarning("提示", "请先选择一个隧道")
            return

        name = item.get("name") or item.get("tunnel name") or item.get("col1") or "unknown"
        tid = cf.extract_tunnel_id(item)
        cfg = self._config_path_for(name)

        # 创建测试对话框
        dialog = tk.Toplevel(self)
        dialog.title(f"测试隧道 - {name}")
        dialog.geometry("600x500")
        dialog.transient(self)

        # 测试结果显示区
        result_frame = ttk.LabelFrame(dialog, text="测试结果")
        result_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        result_text = tk.Text(result_frame, wrap=tk.WORD, height=20)
        result_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # 添加滚动条
        scrollbar = ttk.Scrollbar(result_frame, command=result_text.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        result_text.config(yscrollcommand=scrollbar.set)

        # 按钮区
        button_frame = ttk.Frame(dialog)
        button_frame.pack(fill=tk.X, padx=10, pady=5)

        def append_result(text: str, tag: str = None):
            """添加测试结果"""
            result_text.insert(tk.END, text)
            if tag:
                # 添加颜色标签
                start = result_text.index(f"end-{len(text)+1}c")
                end = result_text.index("end-1c")
                result_text.tag_add(tag, start, end)
            result_text.see(tk.END)
            dialog.update()

        # 配置文本标签样式
        result_text.tag_config("success", foreground="green")
        result_text.tag_config("error", foreground="red")
        result_text.tag_config("info", foreground="blue")
        result_text.tag_config("warning", foreground="orange")

        def run_tests():
            """执行所有测试"""
            result_text.delete(1.0, tk.END)
            append_result(f"=== 开始测试隧道: {name} ===\n\n", "info")

            # 1. 测试配置文件
            append_result("1. 验证配置文件...\n", "info")
            if cfg.exists():
                ok, msg = cf.validate_config(cfg)
                if ok:
                    append_result(f"   ✓ {msg}\n", "success")
                else:
                    append_result(f"   ✗ {msg}\n", "error")
            else:
                append_result("   ✗ 配置文件不存在\n", "error")
                append_result("   请先编辑配置文件\n", "warning")

            append_result("\n")

            # 2. 测试隧道连接
            append_result("2. 测试隧道信息获取...\n", "info")
            ok, msg = cf.test_connection(path, name)
            if ok:
                append_result(f"   ✓ {msg}\n", "success")
            else:
                append_result(f"   ✗ {msg}\n", "error")

            append_result("\n")

            # 3. 测试本地服务（从配置文件读取）
            append_result("3. 测试本地服务...\n", "info")
            if cfg.exists():
                try:
                    content = cfg.read_text(encoding="utf-8")
                    services_tested = 0

                    for line in content.split('\n'):
                        if 'service:' in line and 'http' in line:
                            service = line.split('service:')[1].strip()
                            if service.startswith(('http://', 'https://')):
                                append_result(f"   测试 {service}...\n", "info")
                                ok, msg = cf.test_local_service(service)
                                if ok:
                                    append_result(f"   ✓ {msg}\n", "success")
                                else:
                                    append_result(f"   ✗ {msg}\n", "error")
                                services_tested += 1

                    if services_tested == 0:
                        append_result("   未找到HTTP服务配置\n", "warning")
                except Exception as e:
                    append_result(f"   读取配置失败: {e}\n", "error")
            else:
                append_result("   跳过 - 配置文件不存在\n", "warning")

            append_result("\n")

            # 4. 检查凭证文件
            append_result("4. 检查凭证文件...\n", "info")
            if tid:
                cred_path = cf.default_credentials_path(tid)
                if cred_path.exists():
                    append_result(f"   ✓ 凭证文件存在: {cred_path}\n", "success")
                else:
                    append_result(f"   ✗ 凭证文件不存在: {cred_path}\n", "error")
                    append_result("   需要先创建隧道或重新登录\n", "warning")
            else:
                append_result("   ✗ 无法获取隧道ID\n", "error")

            append_result("\n")

            # 5. 检查隧道是否运行中
            append_result("5. 检查隧道运行状态...\n", "info")
            if self.proc and self.proc.poll() is None:
                append_result("   ✓ 隧道正在运行中\n", "success")

                # 尝试解析运行中的域名
                if cfg.exists():
                    try:
                        content = cfg.read_text(encoding="utf-8")
                        hostnames = []
                        for line in content.split('\n'):
                            if 'hostname:' in line:
                                hostname = line.split('hostname:')[1].strip()
                                hostnames.append(hostname)
                        if hostnames:
                            append_result("   可访问的域名:\n", "info")
                            for h in hostnames:
                                append_result(f"     • https://{h}\n", "success")
                    except:
                        pass
            else:
                append_result("   ○ 隧道未运行\n", "warning")
                append_result("   点击'启动'按钮来启动隧道\n", "info")

            append_result("\n" + "="*50 + "\n", "info")
            append_result("测试完成！\n", "info")

            # 总结
            summary = []
            if cfg.exists():
                ok, _ = cf.validate_config(cfg)
                if ok:
                    summary.append("配置文件 ✓")
                else:
                    summary.append("配置文件 ✗")

            if tid and cf.default_credentials_path(tid).exists():
                summary.append("凭证文件 ✓")
            else:
                summary.append("凭证文件 ✗")

            if self.proc and self.proc.poll() is None:
                summary.append("隧道运行中 ✓")

            append_result(f"\n总结: {' | '.join(summary)}\n", "info")

        # 开始测试按钮
        ttk.Button(button_frame, text="开始测试", command=run_tests).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="关闭", command=dialog.destroy).pack(side=tk.RIGHT, padx=5)

        # 自动开始测试
        dialog.after(100, run_tests)


def run_app():
    app = TunnelManagerApp()
    app.mainloop()
