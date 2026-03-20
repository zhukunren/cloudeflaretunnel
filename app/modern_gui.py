#! -*- coding: utf-8 -*-
"""
现代化的 Cloudflare Tunnel GUI 管理器 - 优化重构版
具有美观的界面、流畅的动画和直观的用户体验
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
import threading
from pathlib import Path
import queue
import os
import json
import subprocess
import time
import traceback
from datetime import datetime
from typing import Callable

# ============= 导入模块 =============
# 支持包模式和脚本模式运行
try:
    # 包模式导入
    from .services import (
        AuthService,
        CloudflaredBinaryService,
        DnsRouteService,
        TunnelCoordinationService,
        TunnelCatalogLoadResult,
        TunnelCatalogService,
        TunnelConfigService,
        TunnelDiagnosticsService,
        TunnelLifecycleService,
        TunnelOperationService,
        TunnelRuntimeService,
    )
    from .utils.theme import Theme
    from .components.widgets import ModernButton, IconButton, Card, Badge, StatusIndicator, SearchBox
    from .config.settings import Settings
    from .utils.logger import LogManager, LogLevel
    from .utils.paths import get_logs_dir, get_persistent_logs_dir, get_tunnels_dir
    from .utils.process_tracker import ProcessTracker, SupervisorLock
    from .utils.supervisor_client import SupervisorClient
except (ImportError, ValueError):
    # 脚本模式导入
    import sys
    sys.path.append(os.path.dirname(__file__))
    from services import (
        AuthService,
        CloudflaredBinaryService,
        DnsRouteService,
        TunnelCoordinationService,
        TunnelCatalogLoadResult,
        TunnelCatalogService,
        TunnelConfigService,
        TunnelDiagnosticsService,
        TunnelLifecycleService,
        TunnelOperationService,
        TunnelRuntimeService,
    )
    from utils.theme import Theme
    from components.widgets import ModernButton, IconButton, Card, Badge, StatusIndicator, SearchBox
    from config.settings import Settings
    from utils.logger import LogManager, LogLevel
    from utils.paths import get_logs_dir, get_persistent_logs_dir, get_tunnels_dir
    from utils.process_tracker import ProcessTracker, SupervisorLock
    from utils.supervisor_client import SupervisorClient


# ============= 辅助组件 =============
class StatusBadge(tk.Frame):
    """状态徽章组件（保留用于兼容性）"""
    def __init__(self, parent, text="", status="info"):
        super().__init__(parent, bg=Theme.BG_CARD)

        colors = {
            "success": (Theme.SUCCESS, "#FFFFFF"),
            "warning": (Theme.WARNING, "#FFFFFF"),
            "error": (Theme.ERROR, "#FFFFFF"),
            "info": (Theme.INFO, "#FFFFFF"),
            "default": (Theme.BG_MAIN, Theme.TEXT_PRIMARY)
        }

        bg_color, fg_color = colors.get(status, colors["default"])

        self.label = tk.Label(
            self,
            text=text,
            bg=bg_color,
            fg=fg_color,
            font=(Theme.FONT_FAMILY, Theme.FONT_SIZE_SM, "bold"),
            padx=Theme.PADDING_SM,
            pady=Theme.PADDING_XS
        )
        self.label.pack()


# ============= 隧道列表组件 =============
class ModernTunnelList(tk.Frame):
    """现代化隧道列表"""
    def __init__(self, parent, on_select=None):
        super().__init__(parent, bg=Theme.BG_CARD)
        self.on_select = on_select
        self.items = []
        self._item_by_name: dict[str, dict] = {}
        self.selected_index = None
        self.empty_state = None

        # 标题栏
        header = tk.Frame(self, bg=Theme.PRIMARY, height=40)
        header.pack(fill=tk.X)
        header.pack_propagate(False)

        tk.Label(
            header,
            text=Theme.ui_text("🚇 隧道列表"),
            bg=Theme.PRIMARY,
            fg=Theme.TEXT_LIGHT,
            font=(Theme.FONT_FAMILY, 11, "bold"),
            padx=15
        ).pack(side=tk.LEFT, fill=tk.Y)

        # 列表容器
        self.container = tk.Frame(self, bg=Theme.BG_CARD)
        self.container.pack(fill=tk.BOTH, expand=True, padx=1)

        # 添加滚动条
        self.canvas = tk.Canvas(self.container, bg=Theme.BG_CARD, highlightthickness=0)
        scrollbar = ttk.Scrollbar(self.container, orient="vertical", command=self.canvas.yview)
        self.scrollable_frame = tk.Frame(self.canvas, bg=Theme.BG_CARD)

        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )

        self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=scrollbar.set)

        self.canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

    def update_tunnel_status(self, tunnel_name: str, running: bool, healthy: bool | None = None):
        """更新特定隧道的状态显示"""
        # running=True 但 healthy=False 表示进程仍在，但无活跃连接
        state_active = running and healthy is True
        state_unknown = running and healthy is None
        state_warning = running and healthy is False

        item_data = self._item_by_name.get(tunnel_name)
        if not item_data:
            for candidate in self.items:
                if candidate["data"].get("name") == tunnel_name:
                    item_data = candidate
                    break

        if not item_data:
            return

        # 更新状态条颜色
        status_bar = item_data.get("status_bar")
        if status_bar:
            if state_active:
                status_bar.configure(bg=Theme.SUCCESS)
            elif state_warning:
                status_bar.configure(bg=Theme.WARNING)
            elif state_unknown:
                status_bar.configure(bg=Theme.INFO)
            else:
                status_bar.configure(bg=Theme.BORDER)

        # 更新徽章
        badge_label = item_data.get("badge_label")
        if badge_label:
            if state_active:
                badge_label.configure(text="● 已激活", bg=Theme.SUCCESS_BG, fg=Theme.SUCCESS)
            elif state_warning:
                badge_label.configure(text="! 无连接", bg=Theme.WARNING_BG, fg=Theme.WARNING)
            elif state_unknown:
                badge_label.configure(text="… 检测中", bg=Theme.INFO_BG, fg=Theme.INFO)
            else:
                badge_label.configure(text="○ 未激活", bg=Theme.BG_HOVER, fg=Theme.TEXT_MUTED)

    def refresh_all_status(self):
        """刷新所有隧道的状态"""
        parent_window = self.winfo_toplevel()
        if hasattr(parent_window, 'running_tunnels'):
            running_tunnels = parent_window.running_tunnels
            for item_data in self.items:
                tunnel_name = item_data["data"].get("name")
                info = running_tunnels.get(tunnel_name) if isinstance(running_tunnels, dict) else None
                running = bool(info)
                healthy = info.get("healthy") if info else None
                self.update_tunnel_status(tunnel_name, running, healthy)

    def set_tunnels(self, tunnels: list[dict], empty_title: str | None = None,
                    empty_subtitle: str | None = None):
        """批量渲染隧道，支持空状态提示"""
        self.clear()
        if not tunnels:
            self._render_empty_state(
                empty_title or "暂无可用隧道",
                empty_subtitle or "点击新建按钮或刷新以加载隧道。"
            )
            return
        for tunnel in tunnels:
            self.add_tunnel(tunnel)

    def _render_empty_state(self, title: str, subtitle: str = ""):
        """显示空数据提示"""
        if self.empty_state:
            self.empty_state.destroy()
            self.empty_state = None

        wrapper = tk.Frame(self.scrollable_frame, bg=Theme.BG_CARD, pady=40)
        wrapper.pack(fill=tk.BOTH, expand=True)

        icon_label = tk.Label(
            wrapper,
            text=Theme.ui_text("🕳️"),
            bg=Theme.BG_CARD,
            fg=Theme.TEXT_MUTED,
            font=(Theme.FONT_FAMILY, 30)
        )
        icon_label.pack(pady=(0, 8))

        tk.Label(
            wrapper,
            text=title,
            bg=Theme.BG_CARD,
            fg=Theme.TEXT_SECONDARY,
            font=(Theme.FONT_FAMILY, 12, "bold")
        ).pack()

        if subtitle:
            tk.Label(
                wrapper,
                text=subtitle,
                bg=Theme.BG_CARD,
                fg=Theme.TEXT_MUTED,
                font=(Theme.FONT_FAMILY, 9),
                wraplength=260,
                justify=tk.CENTER
            ).pack(pady=(6, 0))

        self.empty_state = wrapper

    def add_tunnel(self, tunnel_data):
        """添加隧道项 - 重新设计的卡片"""
        index = len(self.items)

        # 外层容器（用于添加圆角和阴影效果）
        container = tk.Frame(
            self.scrollable_frame,
            bg=Theme.BG_CARD,
            highlightthickness=0
        )
        container.pack(fill=tk.X, padx=12, pady=6)

        # 创建隧道卡片
        card = tk.Frame(
            container,
            bg=Theme.BG_CARD,
            relief=tk.FLAT,
            bd=0,
            highlightbackground=Theme.BORDER,
            highlightthickness=1
        )
        card.pack(fill=tk.BOTH, expand=True)

        # 隧道信息
        name = tunnel_data.get("name", "Unknown")
        tid = tunnel_data.get("id", "")
        tid_short = tid[:8] + "..." if len(tid) > 8 else tid
        created = tunnel_data.get("created_at", "")[:10]

        # 初始状态设为未激活，后续由refresh_all_status更新
        status = "inactive"

        # 左侧状态指示条
        status_bar = tk.Frame(
            card,
            bg=Theme.SUCCESS if status == "active" else Theme.BORDER,
            width=4
        )
        status_bar.pack(side=tk.LEFT, fill=tk.Y)

        # 主内容区
        content_frame = tk.Frame(card, bg=Theme.BG_CARD)
        content_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=12, pady=12)

        # 顶部：名称和状态
        top_row = tk.Frame(content_frame, bg=Theme.BG_CARD)
        top_row.pack(fill=tk.X)

        # 隧道名称（使用更大字体）
        name_label = tk.Label(
            top_row,
            text=name,
            bg=Theme.BG_CARD,
            fg=Theme.TEXT_PRIMARY,
            font=(Theme.FONT_FAMILY, 12, "bold"),
            anchor="w"
        )
        name_label.pack(side=tk.LEFT)

        # 状态徽章
        status_badge = tk.Frame(top_row, bg=Theme.BG_CARD)
        status_badge.pack(side=tk.RIGHT, padx=5)

        if status == "active":
            badge_bg = Theme.SUCCESS_BG
            badge_fg = Theme.SUCCESS
            badge_text = "已激活"
            badge_icon = "●"
        else:
            badge_bg = Theme.BG_HOVER
            badge_fg = Theme.TEXT_MUTED
            badge_text = "未激活"
            badge_icon = "○"

        badge_label = tk.Label(
            status_badge,
            text=f"{badge_icon} {badge_text}",
            bg=badge_bg,
            fg=badge_fg,
            font=(Theme.FONT_FAMILY, 9, "bold"),
            padx=10,
            pady=4
        )
        badge_label.pack()

        # 中部：元数据信息
        meta_row = tk.Frame(content_frame, bg=Theme.BG_CARD)
        meta_row.pack(fill=tk.X, pady=(6, 0))

        # ID信息
        id_frame = tk.Frame(meta_row, bg=Theme.BG_CARD)
        id_frame.pack(side=tk.LEFT, padx=(0, 15))

        tk.Label(
            id_frame,
            text="ID",
            bg=Theme.BG_CARD,
            fg=Theme.TEXT_MUTED,
            font=(Theme.FONT_FAMILY, 8)
        ).pack(side=tk.LEFT, padx=(0, 4))

        tk.Label(
            id_frame,
            text=tid_short,
            bg=Theme.BG_CARD,
            fg=Theme.TEXT_SECONDARY,
            font=(Theme.FONT_MONO, 8)
        ).pack(side=tk.LEFT)

        # 创建日期
        date_frame = tk.Frame(meta_row, bg=Theme.BG_CARD)
        date_frame.pack(side=tk.LEFT)

        tk.Label(
            date_frame,
            text="创建于",
            bg=Theme.BG_CARD,
            fg=Theme.TEXT_MUTED,
            font=(Theme.FONT_FAMILY, 8)
        ).pack(side=tk.LEFT, padx=(0, 4))

        tk.Label(
            date_frame,
            text=created or "未知",
            bg=Theme.BG_CARD,
            fg=Theme.TEXT_SECONDARY,
            font=(Theme.FONT_FAMILY, 8)
        ).pack(side=tk.LEFT)

        # 交互效果
        def on_enter(e):
            card.configure(highlightbackground=Theme.PRIMARY)
            container.configure(cursor="hand2")

        def on_leave(e):
            if self.selected_index != index:
                card.configure(highlightbackground=Theme.BORDER)
            container.configure(cursor="")

        def on_click(e):
            self.select_item(index)

        # 绑定事件到所有子组件
        for widget in [card, content_frame, top_row, name_label, status_badge,
                       badge_label, meta_row, id_frame, date_frame]:
            widget.bind("<Enter>", on_enter)
            widget.bind("<Leave>", on_leave)
            widget.bind("<Button-1>", on_click)

        # 保存到列表
        item_payload = {
            "card": card,
            "container": container,
            "data": tunnel_data,
            "status_bar": status_bar,  # 保存状态条引用
            "badge_label": badge_label,  # 保存徽章标签引用
            "widgets": {
                "content_frame": content_frame,
                "name_label": name_label,
                "meta_row": meta_row,
                "status_badge": badge_label
            }
        }
        self.items.append(item_payload)
        tunnel_name = tunnel_data.get("name")
        if tunnel_name:
            self._item_by_name[str(tunnel_name)] = item_payload

    def select_item(self, index):
        """选择隧道项 - 优化视觉反馈"""
        if 0 <= index < len(self.items):
            # 重置之前选中的项
            if self.selected_index is not None and self.selected_index < len(self.items):
                old_card = self.items[self.selected_index]["card"]
                old_card.configure(highlightbackground=Theme.BORDER, highlightthickness=1)

            # 高亮新选中的项
            self.selected_index = index
            card = self.items[index]["card"]
            card.configure(highlightbackground=Theme.PRIMARY, highlightthickness=2)

            # 触发回调
            if self.on_select:
                self.on_select(self.items[index]["data"])

    def clear(self):
        """清空列表"""
        for item in self.items:
            item["card"].destroy()
        for widget in self.scrollable_frame.winfo_children():
            widget.destroy()
        self.items = []
        self._item_by_name = {}
        self.selected_index = None
        self.empty_state = None

    def get_selected(self):
        """获取选中的隧道数据"""
        if self.selected_index is not None and self.selected_index < len(self.items):
            return self.items[self.selected_index]["data"]
        return None

    def select_by_name(self, tunnel_name: str) -> bool:
        """根据名称选择隧道"""
        if not tunnel_name:
            return False
        for idx, item in enumerate(self.items):
            if item["data"].get("name") == tunnel_name:
                self.select_item(idx)
                return True
        return False


# ============= 主窗口管理器 =============
class ModernTunnelManager(tk.Tk):
    """现代化的隧道管理器主窗口 - 优化重构版"""

    def __init__(self):
        super().__init__()

        self.title(Theme.ui_text("🚇 Cloudflare Tunnel Manager"))

        # 初始化配置管理器
        self.settings = Settings()

        # 初始化日志管理器
        self.logger = LogManager(
            max_lines=self.settings.get("log.max_lines", 1000),
            save_to_file=True
        )
        self._crash_log_path = get_logs_dir() / "gui_crash.log"
        self._crash_log_path.parent.mkdir(parents=True, exist_ok=True)

        # 从配置恢复窗口大小和位置
        self._restore_window_geometry()

        # 设置窗口图标和样式
        self.configure(bg=Theme.BG_MAIN)

        # 初始化变量
        self._project_root = Path(__file__).resolve().parent.parent
        self.binary_service = CloudflaredBinaryService(self._project_root)
        self.runtime_service = TunnelRuntimeService(self.binary_service)
        self.cloudflared_path = tk.StringVar(
            value=self.settings.get("cloudflared.path") or self.binary_service.resolve_path() or ""
        )
        self.status_var = tk.StringVar(value="就绪")
        self.search_var = tk.StringVar()
        self.proc_tracker = ProcessTracker(self._project_root)
        self.supervisor_lock = SupervisorLock(self._project_root)
        self._supervisor_active = False
        self.supervisor_client = SupervisorClient(self._project_root)
        self._supervisor_available = self.supervisor_client.is_available()
        self.coordination_service = TunnelCoordinationService(self.supervisor_lock, self.supervisor_client)
        self.operation_service = TunnelOperationService()
        self.auth_service = AuthService()
        self.config_service = TunnelConfigService()
        self.catalog_service = TunnelCatalogService(self._project_root, self.config_service)
        self.dns_service = DnsRouteService()
        self.diagnostics_service = TunnelDiagnosticsService()
        self.lifecycle_service = TunnelLifecycleService(self.dns_service, self.config_service, self.operation_service)
        self.proc = None
        self.proc_thread = None
        self.proc_queue = queue.Queue()
        self.proc_map: dict[str, subprocess.Popen] = {}
        self._tunnels = []
        self.running_tunnels = {}  # 存储系统中运行的隧道信息
        self._health_cache: dict[str, dict] = {}  # 隧道健康状态缓存
        self._manual_operation = False  # 标记手动操作状态
        self._last_status_state = None  # 记录上次状态，避免闪烁
        self.toggle_button = None
        self.toggle_button_var = tk.StringVar(value="▶ 启动")
        self._search_clear_btn = None
        self._search_entry = None
        self.persist_var = tk.BooleanVar(value=self.settings.get("tunnel.persist_on_exit", False))
        self.autostart_var = tk.BooleanVar(value=self.settings.get("tunnel.auto_start_enabled", False))
        self.autostart_hint_var = tk.StringVar()
        self.setup_cloudflared_var = tk.StringVar(value="工具状态：正在检查 cloudflared…")
        self.setup_auth_var = tk.StringVar(value="登录状态：正在检查 Cloudflare 认证…")
        self.setup_next_step_var = tk.StringVar(value="下一步：启动后将自动给出建议。")
        self._auto_start_done = False
        self._refresh_autostart_hint()
        # 自动重连默认关闭，避免误杀稳定隧道
        self.auto_heal_var = tk.BooleanVar(value=self.settings.get("tunnel.auto_heal_enabled", False))
        self._health_failures: dict[str, int] = {}
        self._auto_heal_pending: set[str] = set()
        self._status_refresh_running = False  # 防止后台刷新并发执行
        self._tunnel_operation_in_progress = False  # 防止启动/停止操作重复触发
        self._tunnel_list_refreshing = False  # 防止刷新隧道列表并发执行

        # 绑定窗口关闭事件
        self.protocol("WM_DELETE_WINDOW", self._on_closing)

        # 创建UI
        self._build_modern_ui()

        # 初始化
        self.after(100, self._init_app)
        self.after(200, self._drain_proc_queue)

        # 日志回调
        self.logger.add_callback(self._on_log_message)

    def _write_crash_report(self, title: str, exc_type=None, exc_value=None, exc_traceback=None, extra: str | None = None):
        """Persist GUI crash details for cases where the window disappears before the user can read stderr."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        lines = [f"[{timestamp}] {title}"]
        if extra:
            lines.append(extra)

        if exc_type is not None:
            lines.extend(traceback.format_exception(exc_type, exc_value, exc_traceback))
        elif exc_value is not None:
            lines.append(str(exc_value))

        lines.append("")
        try:
            with open(self._crash_log_path, "a", encoding="utf-8") as fh:
                fh.write("\n".join(lines))
        except Exception:
            pass

    def report_callback_exception(self, exc, val, tb):
        """Capture Tk callback exceptions into the normal log and a dedicated crash log."""
        summary = f"Tk回调异常: {exc.__name__}: {val}"
        try:
            self.logger.error(summary)
        except Exception:
            pass
        self._write_crash_report("Tk Callback Exception", exc, val, tb)
        try:
            messagebox.showerror("GUI异常", f"{summary}\n\n详细信息已写入:\n{self._crash_log_path}")
        except Exception:
            pass

    def _restore_window_geometry(self):
        """恢复窗口几何配置"""
        width = self.settings.get("window.width", 1200)
        height = self.settings.get("window.height", 700)
        min_width = self.settings.get("window.min_width", 1000)
        min_height = self.settings.get("window.min_height", 600)

        self.geometry(f"{width}x{height}")
        self.minsize(min_width, min_height)

        # 恢复窗口位置
        if self.settings.get("window.remember_position", True):
            x = self.settings.get("window.x")
            y = self.settings.get("window.y")
            if x is not None and y is not None:
                self.geometry(f"{width}x{height}+{x}+{y}")

    def _save_window_geometry(self):
        """保存窗口几何配置"""
        # 获取当前窗口大小和位置
        geometry = self.geometry()
        # 格式: widthxheight+x+y
        parts = geometry.replace('+', 'x').replace('-', 'x').split('x')

        if len(parts) >= 2:
            self.settings.set("window.width", int(parts[0]))
            self.settings.set("window.height", int(parts[1]))

        if len(parts) >= 4 and self.settings.get("window.remember_position", True):
            self.settings.set("window.x", int(parts[2]))
            self.settings.set("window.y", int(parts[3]))

    def _on_closing(self):
        """窗口关闭事件处理"""
        try:
            self.logger.info("收到窗口关闭请求，准备退出GUI")
        except Exception:
            pass

        # 保存窗口几何配置
        self._save_window_geometry()

        # 保存cloudflared路径
        self.settings.set("cloudflared.path", self.cloudflared_path.get())

        # 停止运行的进程（如未启用持久化）
        keep_running = bool(self.persist_var.get())
        active_procs = [
            (name, proc)
            for name, proc in self.proc_map.items()
            if proc and proc.poll() is None
        ]

        if keep_running:
            if active_procs:
                self._append_log("保持隧道运行：已启用持久化，退出时不终止 cloudflared。\n", "info")
                self.logger.info("退出时保留隧道运行")
        else:
            for name, proc in active_procs:
                try:
                    self.runtime_service.stop_process(proc)
                    self.proc_tracker.unregister(name, expected_pid=proc.pid)
                except Exception:
                    pass
            self.proc_map.clear()
            self.proc = None
            self.proc_thread = None

        # 销毁窗口
        self.destroy()

    def _on_log_message(self, timestamp, level, message):
        """日志消息回调"""
        # 将LogLevel映射到日志标签
        level_map = {
            LogLevel.DEBUG: "info",
            LogLevel.INFO: "info",
            LogLevel.WARNING: "warning",
            LogLevel.ERROR: "error"
        }
        tag = level_map.get(level, "info")

        # 统一进入队列，由主线程批量刷新，避免卡顿/线程不安全
        try:
            self.proc_queue.put(("logger", message + "\n", tag))
        except Exception:
            pass

    def _build_modern_ui(self):
        """构建现代化UI - 2025重构版"""

        # ========== 顶部导航栏 ==========
        topbar = tk.Frame(self, bg=Theme.BG_TOOLBAR, height=65)
        topbar.pack(fill=tk.X)
        topbar.pack_propagate(False)

        # Logo和标题区
        brand_frame = tk.Frame(topbar, bg=Theme.BG_TOOLBAR)
        brand_frame.pack(side=tk.LEFT, padx=25, fill=tk.Y)

        # Logo图标（使用渐变效果）
        logo_canvas = tk.Canvas(brand_frame, bg=Theme.BG_TOOLBAR, width=32, height=32, highlightthickness=0)
        logo_canvas.pack(side=tk.LEFT, padx=(0, 12))
        # 绘制圆形渐变logo
        logo_canvas.create_oval(4, 4, 28, 28, fill=Theme.PRIMARY, outline=Theme.PRIMARY_LIGHT, width=2)
        logo_canvas.create_text(16, 16, text="☁", fill=Theme.TEXT_LIGHT, font=(Theme.FONT_FAMILY, 14))

        # 标题文字
        title_container = tk.Frame(brand_frame, bg=Theme.BG_TOOLBAR)
        title_container.pack(side=tk.LEFT)

        tk.Label(
            title_container,
            text="Cloudflare Tunnel",
            bg=Theme.BG_TOOLBAR,
            fg=Theme.TEXT_LIGHT,
            font=(Theme.FONT_FAMILY, 15, "bold")
        ).pack(anchor="w")

        tk.Label(
            title_container,
            text="内网穿透管理器",
            bg=Theme.BG_TOOLBAR,
            fg=Theme.TEXT_MUTED,
            font=(Theme.FONT_FAMILY, 9)
        ).pack(anchor="w")

        # 右侧工具栏
        toolbar = tk.Frame(topbar, bg=Theme.BG_TOOLBAR)
        toolbar.pack(side=tk.RIGHT, padx=20, fill=tk.Y)

        self.header_hint_label = tk.Label(
            toolbar,
            text="准备工具 → 登录授权 → 选择隧道 → 启动",
            bg=Theme.BG_TOOLBAR,
            fg=Theme.TEXT_MUTED,
            font=(Theme.FONT_FAMILY, 9)
        )
        self.header_hint_label.pack(side=tk.RIGHT, padx=(0, 16))

        # 版本信息（简洁显示）
        self.version_label = tk.Label(
            toolbar,
            text="",
            bg=Theme.BG_TOOLBAR,
            fg=Theme.TEXT_MUTED,
            font=(Theme.FONT_FAMILY, 9)
        )
        self.version_label.pack(side=tk.RIGHT)

        # ========== 主内容区 ==========
        main_container = tk.Frame(self, bg=Theme.BG_MAIN)
        main_container.pack(fill=tk.BOTH, expand=True, padx=0, pady=0)

        # 左侧面板：隧道列表
        left_panel = tk.Frame(main_container, bg=Theme.BG_MAIN, width=380)
        left_panel.pack(side=tk.LEFT, fill=tk.BOTH, padx=(20, 10), pady=20)
        left_panel.pack_propagate(False)

        # 列表头部（标题 + 操作按钮）
        list_header = tk.Frame(left_panel, bg=Theme.BG_MAIN, height=50)
        list_header.pack(fill=tk.X, pady=(0, 12))

        tk.Label(
            list_header,
            text="我的隧道",
            bg=Theme.BG_MAIN,
            fg=Theme.TEXT_PRIMARY,
            font=(Theme.FONT_FAMILY, 16, "bold")
        ).pack(side=tk.LEFT)

        # 搜索输入框
        search_wrapper = tk.Frame(list_header, bg=Theme.BG_MAIN)
        search_wrapper.pack(side=tk.RIGHT)

        search_box = tk.Frame(
            search_wrapper,
            bg=Theme.BG_CARD,
            highlightbackground=Theme.BORDER,
            highlightthickness=1
        )
        search_box.pack(fill=tk.X)

        tk.Label(
            search_box,
            text=Theme.ui_text("🔍"),
            bg=Theme.BG_CARD,
            fg=Theme.TEXT_MUTED,
            font=(Theme.FONT_FAMILY, 10)
        ).pack(side=tk.LEFT, padx=(6, 4))

        self._search_entry = tk.Entry(
            search_box,
            textvariable=self.search_var,
            bg=Theme.BG_CARD,
            fg=Theme.TEXT_PRIMARY,
            bd=0,
            relief=tk.FLAT,
            font=(Theme.FONT_FAMILY, 10),
            insertbackground=Theme.TEXT_PRIMARY
        )
        self._search_entry.pack(side=tk.LEFT, fill=tk.X, padx=2, pady=4)
        self._search_entry.bind("<Escape>", lambda e: self._clear_search())

        self._search_clear_btn = tk.Button(
            search_box,
            text="✕",
            command=self._clear_search,
            bg=Theme.BG_CARD,
            fg=Theme.TEXT_MUTED,
            bd=0,
            relief=tk.FLAT,
            font=(Theme.FONT_FAMILY, 9),
            activebackground=Theme.BG_CARD,
            cursor="hand2"
        )
        self._search_clear_btn.pack(side=tk.RIGHT, padx=(4, 6))
        self._search_clear_btn.configure(state=tk.DISABLED)

        # 隧道列表容器
        list_card = tk.Frame(
            left_panel,
            bg=Theme.BG_CARD,
            highlightbackground=Theme.BORDER,
            highlightthickness=1
        )
        list_card.pack(fill=tk.BOTH, expand=True)

        self.tunnel_list = ModernTunnelList(list_card, on_select=self._on_tunnel_select)
        self.tunnel_list.pack(fill=tk.BOTH, expand=True)
        self.search_var.trace_add("write", lambda *_: self._apply_tunnel_filter())

        # 右侧面板：控制和日志
        right_panel = tk.Frame(main_container, bg=Theme.BG_MAIN)
        right_panel.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(10, 20), pady=20)

        setup_card = self._create_modern_card(right_panel, "首次使用", icon="🧭")
        setup_card["card"].pack(fill=tk.X, pady=(0, 15))

        tk.Label(
            setup_card["content"],
            text="普通用户通常只需要先准备工具并完成登录，后续选择隧道后点击启动即可。",
            bg=Theme.BG_CARD,
            fg=Theme.TEXT_MUTED,
            font=(Theme.FONT_FAMILY, 9),
            wraplength=620,
            justify=tk.LEFT
        ).pack(anchor="w", pady=(0, 10))

        setup_actions_row = tk.Frame(setup_card["content"], bg=Theme.BG_CARD)
        setup_actions_row.pack(fill=tk.X)

        self._create_outline_button(setup_actions_row, "⬇ 下载/更新", self._check_update_cloudflared)
        self._create_outline_button(setup_actions_row, "📁 选择文件", self._choose_cloudflared)
        self._create_outline_button(setup_actions_row, "🔑 登录授权", self._login)

        setup_state_box = tk.Frame(
            setup_card["content"],
            bg=Theme.BG_HOVER,
            highlightbackground=Theme.BORDER,
            highlightthickness=1,
            padx=12,
            pady=10
        )
        setup_state_box.pack(fill=tk.X, pady=(12, 0))

        tk.Label(
            setup_state_box,
            textvariable=self.setup_cloudflared_var,
            bg=Theme.BG_HOVER,
            fg=Theme.TEXT_PRIMARY,
            font=(Theme.FONT_FAMILY, 10, "bold"),
            anchor="w",
            justify=tk.LEFT
        ).pack(fill=tk.X)

        tk.Label(
            setup_state_box,
            textvariable=self.setup_auth_var,
            bg=Theme.BG_HOVER,
            fg=Theme.TEXT_SECONDARY,
            font=(Theme.FONT_FAMILY, 9),
            anchor="w",
            justify=tk.LEFT
        ).pack(fill=tk.X, pady=(6, 0))

        tk.Label(
            setup_state_box,
            textvariable=self.setup_next_step_var,
            bg=Theme.BG_HOVER,
            fg=Theme.PRIMARY,
            font=(Theme.FONT_FAMILY, 9, "bold"),
            anchor="w",
            justify=tk.LEFT,
            wraplength=620
        ).pack(fill=tk.X, pady=(8, 0))

        action_card = self._create_modern_card(right_panel, "日常使用", icon="🚀")
        action_card["card"].pack(fill=tk.X, pady=(0, 15))
        control_section = action_card["content"]

        # 主控制按钮（大号启动/停止）
        self.toggle_button = tk.Button(
            control_section,
            textvariable=self.toggle_button_var,
            command=self._toggle_start_selected,
            bg=Theme.PRIMARY,
            fg=Theme.TEXT_LIGHT,
            font=(Theme.FONT_FAMILY, 13, "bold"),
            bd=0,
            padx=30,
            pady=15,
            cursor="hand2",
            relief=tk.FLAT,
            activebackground=Theme.PRIMARY_DARK
        )
        self.toggle_button.pack(fill=tk.X)

        # 绑定悬停效果
        self.toggle_button.bind("<Enter>", lambda e: self._on_toggle_hover(True))
        self.toggle_button.bind("<Leave>", lambda e: self._on_toggle_hover(False))

        # 次要操作行
        secondary_actions = tk.Frame(control_section, bg=Theme.BG_CARD)
        secondary_actions.pack(fill=tk.X, pady=(12, 0))

        self._create_outline_button(secondary_actions, "🔄 刷新列表", self.refresh_tunnels)
        self._create_outline_button(secondary_actions, "➕ 新建隧道", self._create_tunnel)
        self._create_outline_button(secondary_actions, "🗑 删除隧道", self._delete_selected)

        options_card = tk.Frame(
            control_section,
            bg=Theme.BG_CARD,
            highlightbackground=Theme.BORDER,
            highlightthickness=1,
            padx=12,
            pady=10
        )
        options_card.pack(fill=tk.X, pady=(12, 0))

        tk.Label(
            options_card,
            text="运行选项",
            bg=Theme.BG_CARD,
            fg=Theme.TEXT_SECONDARY,
            font=(Theme.FONT_FAMILY, 10, "bold")
        ).pack(anchor="w")

        persist_cb = tk.Checkbutton(
            options_card,
            text="关闭软件后继续保持隧道运行",
            variable=self.persist_var,
            command=self._on_persist_toggle,
            bg=Theme.BG_CARD,
            fg=Theme.TEXT_PRIMARY,
            selectcolor=Theme.BG_CARD,
            activebackground=Theme.BG_CARD,
            anchor="w"
        )
        persist_cb.pack(fill=tk.X, pady=(6, 2))

        autostart_cb = tk.Checkbutton(
            options_card,
            text="打开软件时自动启动当前选择的隧道",
            variable=self.autostart_var,
            command=self._on_autostart_toggle,
            bg=Theme.BG_CARD,
            fg=Theme.TEXT_PRIMARY,
            selectcolor=Theme.BG_CARD,
            activebackground=Theme.BG_CARD,
            anchor="w"
        )
        autostart_cb.pack(fill=tk.X, pady=(2, 2))

        autoheal_cb = tk.Checkbutton(
            options_card,
            text="连接异常时自动重连（高级）",
            variable=self.auto_heal_var,
            command=self._on_auto_heal_toggle,
            bg=Theme.BG_CARD,
            fg=Theme.TEXT_PRIMARY,
            selectcolor=Theme.BG_CARD,
            activebackground=Theme.BG_CARD,
            anchor="w"
        )
        autoheal_cb.pack(fill=tk.X, pady=(2, 2))

        tk.Label(
            options_card,
            textvariable=self.autostart_hint_var,
            bg=Theme.BG_CARD,
            fg=Theme.TEXT_MUTED,
            font=(Theme.FONT_FAMILY, 9),
            wraplength=360,
            justify=tk.LEFT
        ).pack(fill=tk.X, pady=(4, 0))

        advanced_card = self._create_modern_card(right_panel, "高级工具", icon="🧰")
        advanced_card["card"].pack(fill=tk.X, pady=(0, 15))

        tk.Label(
            advanced_card["content"],
            text="只有在需要自定义域名、编辑配置、诊断问题或查看守护进程时才需要使用这些功能。",
            bg=Theme.BG_CARD,
            fg=Theme.TEXT_MUTED,
            font=(Theme.FONT_FAMILY, 9),
            wraplength=620,
            justify=tk.LEFT
        ).pack(anchor="w", pady=(0, 10))

        advanced_row1 = tk.Frame(advanced_card["content"], bg=Theme.BG_CARD)
        advanced_row1.pack(fill=tk.X)
        self._create_outline_button(advanced_row1, "🌐 DNS路由", self._route_dns_selected)
        self._create_outline_button(advanced_row1, "✏ 编辑配置", self._edit_selected_config)
        self._create_outline_button(advanced_row1, "🧪 诊断测试", self._test_tunnel)

        advanced_row2 = tk.Frame(advanced_card["content"], bg=Theme.BG_CARD)
        advanced_row2.pack(fill=tk.X, pady=(10, 0))
        self._create_outline_button(advanced_row2, "📊 守护状态", self._show_supervisor_status)
        self._create_outline_button(advanced_row2, "📂 打开目录", self._open_config_dir)

        # 状态信息卡片
        status_card = self._create_modern_card(right_panel, "系统状态", icon="📊")
        status_card["card"].pack(fill=tk.X, pady=(0, 15))

        self.status_display = tk.Frame(status_card["content"], bg=Theme.BG_CARD)
        self.status_display.pack(fill=tk.X)

        # 日志卡片（增强工具栏）
        log_card = self._create_modern_card(right_panel, "运行日志", icon="📝")
        log_card["card"].pack(fill=tk.BOTH, expand=True)

        log_frame = log_card["content"]

        log_toolbar = tk.Frame(log_frame, bg=Theme.BG_CARD)
        log_toolbar.pack(fill=tk.X, pady=(0, 10))

        tk.Label(
            log_toolbar,
            text="最近事件",
            bg=Theme.BG_CARD,
            fg=Theme.TEXT_SECONDARY,
            font=(Theme.FONT_FAMILY, 10, "bold")
        ).pack(side=tk.LEFT)

        log_actions = tk.Frame(log_toolbar, bg=Theme.BG_CARD)
        log_actions.pack(side=tk.RIGHT)

        def _log_tool_button(text, command):
            return tk.Button(
                log_actions,
                text=text,
                command=command,
                bg=Theme.BG_CARD,
                fg=Theme.PRIMARY,
                bd=0,
                relief=tk.FLAT,
                font=(Theme.FONT_FAMILY, 9),
                padx=10,
                cursor="hand2",
                activebackground=Theme.BG_CARD
            )

        _log_tool_button("复制", self._copy_log).pack(side=tk.RIGHT, padx=(4, 0))
        _log_tool_button("保存", self._save_log_to_file).pack(side=tk.RIGHT, padx=(4, 0))
        _log_tool_button("清空", self._clear_log).pack(side=tk.RIGHT, padx=(4, 0))

        log_body = tk.Frame(
            log_frame,
            bg=Theme.LOG_BG,
            highlightbackground=Theme.LOG_BORDER,
            highlightthickness=1
        )
        log_body.pack(fill=tk.BOTH, expand=True)

        self.log = tk.Text(
            log_body,
            bg=Theme.LOG_BG,
            fg=Theme.LOG_TEXT,
            font=(Theme.FONT_MONO, 9),
            wrap=tk.WORD,
            relief=tk.FLAT,
            insertbackground=Theme.LOG_CURSOR,
            padx=12,
            pady=12,
            bd=0
        )
        self.log.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        log_scrollbar = ttk.Scrollbar(log_body, orient=tk.VERTICAL, command=self.log.yview)
        log_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.log.configure(yscrollcommand=log_scrollbar.set)

        # 配置日志颜色并初始化底部状态栏
        self.log.tag_config("info", foreground=Theme.INFO)
        self.log.tag_config("success", foreground=Theme.SUCCESS)
        self.log.tag_config("warning", foreground=Theme.WARNING)
        self.log.tag_config("error", foreground=Theme.ERROR)

        self._init_status_bar()

    def _init_status_bar(self):
        """初始化底部状态栏，避免重复创建"""
        if getattr(self, "_status_bar_inited", False):
            return

        statusbar = tk.Frame(self, bg=Theme.BG_TOOLBAR, height=35)
        statusbar.pack(fill=tk.X)
        statusbar.pack_propagate(False)

        status_container = tk.Frame(statusbar, bg=Theme.BG_TOOLBAR)
        status_container.pack(side=tk.LEFT, fill=tk.Y, padx=20)

        tk.Label(
            status_container,
            textvariable=self.status_var,
            bg=Theme.BG_TOOLBAR,
            fg=Theme.TEXT_LIGHT,
            font=(Theme.FONT_FAMILY, 9)
        ).pack(side=tk.LEFT)

        path_indicator = tk.Frame(statusbar, bg=Theme.BG_TOOLBAR)
        path_indicator.pack(side=tk.RIGHT, padx=20)

        tk.Label(
            path_indicator,
            text=Theme.ui_text("📍"),
            bg=Theme.BG_TOOLBAR,
            fg=Theme.TEXT_MUTED,
            font=(Theme.FONT_FAMILY, 10)
        ).pack(side=tk.LEFT, padx=(0, 5))

        self.path_label = tk.Label(
            path_indicator,
            textvariable=self.cloudflared_path,
            bg=Theme.BG_TOOLBAR,
            fg=Theme.TEXT_MUTED,
            font=(Theme.FONT_FAMILY, 8),
            width=50,
            anchor="e"
        )
        self.path_label.pack(side=tk.LEFT)

        self._status_bar_inited = True

    def _refresh_autostart_hint(self):
        """刷新自动启动提示"""
        if not self.autostart_var.get():
            self.autostart_hint_var.set("自动启动：已关闭")
            return
        target = self.settings.get("tunnel.autostart_tunnel")
        if target:
            self.autostart_hint_var.set(f"自动启动目标：{target}")
        else:
            self.autostart_hint_var.set("自动启动目标：未设置")

    def _set_autostart_target(self, tunnel_name: str):
        """设置自动启动的隧道"""
        if not tunnel_name:
            return
        self.settings.set("tunnel.autostart_tunnel", tunnel_name)
        self._refresh_autostart_hint()

    def _on_persist_toggle(self):
        """持久化选项切换"""
        enabled = bool(self.persist_var.get())
        self.settings.set("tunnel.persist_on_exit", enabled)
        if enabled:
            self._append_log("已启用隧道持久化，关闭应用后将保留正在运行的隧道。\n", "info")
            self.logger.info("启用隧道持久化")
        else:
            self._append_log("已关闭隧道持久化，退出时会终止由GUI启动的隧道。\n", "info")
            self.logger.info("关闭隧道持久化")

    def _on_autostart_toggle(self):
        """自动启动选项切换"""
        selected = self.tunnel_list.get_selected() if hasattr(self, "tunnel_list") else None
        decision = self.coordination_service.evaluate_autostart_toggle(
            bool(self.autostart_var.get()),
            selected_name=selected.get("name") if selected else None,
            last_selected=self.settings.get("tunnel.last_selected"),
        )

        self.autostart_var.set(decision.enabled)
        self.settings.set("tunnel.auto_start_enabled", decision.enabled)
        self._auto_start_done = decision.auto_start_done

        if decision.target:
            self._set_autostart_target(decision.target)
        if decision.ui_message:
            self._append_log(decision.ui_message + "\n", decision.ui_level)
        if decision.logger_message:
            self._logger_for_tag(decision.ui_level)(decision.logger_message)
        if decision.dialog_message:
            self._show_dialog(decision.dialog_title or "自动启动", decision.dialog_message)

        self._refresh_autostart_hint()
        if decision.enabled and decision.trigger_now:
            self._auto_start_if_enabled(force=True)

    def _on_auto_heal_toggle(self):
        """自动重连选项切换"""
        enabled = bool(self.auto_heal_var.get())
        self.settings.set("tunnel.auto_heal_enabled", enabled)
        if enabled:
            self._append_log("已开启自动重连：检测到无活跃连接时自动重启隧道。\n", "info")
            self.logger.info("启用自动重连")
        else:
            self._append_log("已关闭自动重连。\n", "info")
            self.logger.info("关闭自动重连")

    def _restore_selection_if_needed(self):
        """恢复上次选择的隧道"""
        if not hasattr(self, "tunnel_list"):
            return
        if self.tunnel_list.get_selected():
            return
        preferred = self.settings.get("tunnel.last_selected")
        if preferred:
            self.tunnel_list.select_by_name(preferred)

    def _create_modern_card(self, parent, title, icon=""):
        """创建现代化卡片容器"""
        card = tk.Frame(
            parent,
            bg=Theme.BG_CARD,
            relief=tk.FLAT,
            bd=0,
            highlightbackground=Theme.BORDER,
            highlightthickness=1
        )

        # 标题栏
        header = tk.Frame(card, bg=Theme.BG_CARD, height=45)
        header.pack(fill=tk.X)
        header.pack_propagate(False)

        title_text = Theme.ui_text(f"{icon} {title}" if icon else title)
        tk.Label(
            header,
            text=title_text,
            bg=Theme.BG_CARD,
            fg=Theme.TEXT_PRIMARY,
            font=(Theme.FONT_FAMILY, 12, "bold"),
            padx=15
        ).pack(side=tk.LEFT, fill=tk.Y)

        # 分割线
        tk.Frame(card, bg=Theme.DIVIDER, height=1).pack(fill=tk.X)

        # 内容区
        content = tk.Frame(card, bg=Theme.BG_CARD)
        content.pack(fill=tk.BOTH, expand=True, padx=15, pady=15)

        return {"card": card, "header": header, "content": content}

    def _create_icon_button(self, parent, icon, command, tooltip=""):
        """创建图标按钮（顶部工具栏）"""
        btn = tk.Button(
            parent,
            text=Theme.ui_text(icon),
            command=command,
            bg=Theme.BG_TOOLBAR,
            fg=Theme.TEXT_LIGHT,
            font=(Theme.FONT_FAMILY, 14),
            bd=0,
            padx=12,
            pady=8,
            cursor="hand2",
            activebackground=Theme.PRIMARY,
            activeforeground=Theme.TEXT_LIGHT,
            relief=tk.FLAT
        )
        btn.pack(side=tk.LEFT, padx=3)

        # 悬停效果
        def on_enter(e):
            btn.configure(bg=Theme.PRIMARY, fg=Theme.TEXT_LIGHT)

        def on_leave(e):
            btn.configure(bg=Theme.BG_TOOLBAR, fg=Theme.TEXT_LIGHT)

        btn.bind("<Enter>", on_enter)
        btn.bind("<Leave>", on_leave)

        return btn

    def _create_compact_button(self, parent, icon, command, color, tooltip=""):
        """创建紧凑按钮（列表操作）"""
        btn = tk.Button(
            parent,
            text=Theme.ui_text(icon),
            command=command,
            bg=color,
            fg=Theme.TEXT_LIGHT,
            font=(Theme.FONT_FAMILY, 11),
            bd=0,
            width=3,
            height=1,
            cursor="hand2",
            relief=tk.FLAT,
            activebackground=color
        )
        btn.pack(side=tk.LEFT, padx=3)

        return btn

    def _create_outline_button(self, parent, text, command):
        """创建边框按钮（次要操作）"""
        btn = tk.Button(
            parent,
            text=Theme.ui_text(text),
            command=command,
            bg=Theme.BG_CARD,
            fg=Theme.PRIMARY,
            font=(Theme.FONT_FAMILY, 10),
            bd=0,
            padx=15,
            pady=10,
            cursor="hand2",
            relief=tk.FLAT,
            highlightbackground=Theme.PRIMARY,
            highlightthickness=1
        )
        btn.pack(side=tk.LEFT, padx=5)

        # 悬停效果
        def on_enter(e):
            btn.configure(bg=Theme.BTN_HOVER)

        def on_leave(e):
            btn.configure(bg=Theme.BG_CARD)

        btn.bind("<Enter>", on_enter)
        btn.bind("<Leave>", on_leave)

        return btn

    def _clear_search(self):
        """清空搜索关键词"""
        if self.search_var.get():
            self.search_var.set("")
        if self._search_entry:
            self._search_entry.focus_set()
        else:
            self._apply_tunnel_filter()

    def _apply_tunnel_filter(self, *_):
        """根据搜索关键词过滤隧道列表"""
        if not hasattr(self, "tunnel_list"):
            return

        query = self.search_var.get().strip().lower()
        tunnels = getattr(self, "_tunnels", []) or []

        if not query:
            filtered = tunnels
            empty_title = None
            empty_subtitle = None
        else:
            def match(tunnel: dict) -> bool:
                fields = [
                    tunnel.get("name", ""),
                    tunnel.get("id", ""),
                    tunnel.get("tunnel_id", ""),
                    tunnel.get("tunnel id", ""),
                    tunnel.get("created_at", ""),
                ]
                combined = " ".join(str(value).lower() for value in fields if value)
                return query in combined

            filtered = [t for t in tunnels if match(t)]
            empty_title = "未找到匹配的隧道"
            empty_subtitle = f'没有包含"{self.search_var.get().strip()}"的隧道。'

        self.tunnel_list.set_tunnels(filtered, empty_title, empty_subtitle)

        # 刷新所有隧道的状态显示
        self.tunnel_list.refresh_all_status()

        total = len(tunnels)
        shown = len(filtered)
        if query:
            self.status_var.set(f"共 {total} 个隧道 · 匹配 {shown} 个")
        else:
            self.status_var.set(f"共 {total} 个隧道")

        if self._search_clear_btn:
            state = tk.NORMAL if query else tk.DISABLED
            self._search_clear_btn.configure(state=state)

        self._restore_selection_if_needed()
        self._update_status_display()

    def _on_toggle_hover(self, is_enter):
        """主控制按钮悬停效果"""
        if not self.toggle_button:
            return

        selected = self.tunnel_list.get_selected() if hasattr(self, "tunnel_list") else None
        target_name = selected.get("name") if selected else None
        running = self._is_tunnel_running(target_name)

        if is_enter:
            if running:
                self.toggle_button.configure(bg=Theme.ERROR)
            else:
                self.toggle_button.configure(bg=Theme.PRIMARY_DARK)
        else:
            if running:
                self.toggle_button.configure(bg=Theme.ERROR)
            else:
                self.toggle_button.configure(bg=Theme.PRIMARY)

    def _health_status(self, tunnel_name: str, force: bool = False) -> tuple[bool | None, str]:
        """获取隧道活跃连接状态，使用短期缓存避免频繁调用 cloudflared。"""
        return self.runtime_service.get_health_status(
            tunnel_name,
            self.cloudflared_path.get().strip(),
            self._health_cache,
            ttl=10,
            timeout=20,
            force=force,
        )

    def _handle_auto_heal(self, tunnel_name: str, health):
        """检测到无活跃连接时自动重启 GUI 管理的隧道"""
        proc = self.proc_map.get(tunnel_name)
        decision = self.coordination_service.plan_auto_heal(
            tunnel_name,
            health=health,
            enabled=bool(self.auto_heal_var.get()),
            supervisor_managed=self._supervisor_active and self._supervisor_available,
            process_running=bool(proc and proc.poll() is None),
            failure_count=self._health_failures.get(tunnel_name, 0),
            pending=tunnel_name in self._auto_heal_pending,
        )

        if decision.clear_failure:
            self._health_failures.pop(tunnel_name, None)
        elif decision.next_failure_count is not None:
            self._health_failures[tunnel_name] = decision.next_failure_count

        if decision.ui_message:
            self._append_log(decision.ui_message + "\n", decision.ui_level)
        if decision.logger_message:
            self._logger_for_tag(decision.ui_level)(decision.logger_message)
        if decision.status_message:
            self.status_var.set(decision.status_message)
        if not decision.restart:
            return

        if decision.mark_pending:
            self._auto_heal_pending.add(tunnel_name)

        persist_flag = bool(self.persist_var.get())
        path = self.runtime_service.resolve_cloudflared_path(self.cloudflared_path.get().strip())
        self.after(
            100,
            lambda n=tunnel_name, p=persist_flag, c=path: self._restart_gui_tunnel(
                n,
                cloudflared_path=c,
                persist_enabled=p,
            ),
        )

    def _cleanup_exited_gui_processes(self) -> bool:
        """清理已经退出的 GUI 托管进程，并同步相关运行态缓存。"""
        cleaned = False
        for name, proc in list(self.proc_map.items()):
            if not proc or proc.poll() is None:
                continue

            self._append_log(f"隧道 {name} 进程已退出\n", "warning")
            self.logger.warning(f"隧道 {name} 进程已退出")
            if proc is self.proc:
                self.proc = None
                self.proc_thread = None
            self.proc_tracker.unregister(name, expected_pid=proc.pid)
            del self.proc_map[name]
            self._health_failures.pop(name, None)
            self._auto_heal_pending.discard(name)
            cleaned = True
        return cleaned

    def _start_background_status_refresh(self):
        """启动后台状态刷新线程；若已有刷新任务则直接跳过。"""
        if self._status_refresh_running:
            return

        self._status_refresh_running = True
        cloudflared_path = self.runtime_service.resolve_cloudflared_path(self.cloudflared_path.get().strip())
        threading.Thread(
            target=self._background_status_check,
            args=(cloudflared_path,),
            daemon=True,
        ).start()

    def _apply_running_tunnel_health(self, tunnel: dict):
        """标准化单个运行中隧道的健康状态，并触发必要日志与自动修复。"""
        tunnel_name = tunnel["name"]
        detail = str(tunnel.get("detail", "") or "")
        health = self.coordination_service.normalize_health_check(
            tunnel.pop("_health_ok", None),
            detail,
        )
        tunnel["healthy"] = health.ok

        if health.ok is False:
            prev = self.running_tunnels.get(tunnel_name, {})
            if prev.get("healthy") is not False:
                self._append_log(f"隧道 {tunnel_name} 无活跃连接：{detail}\n", "warning")
                self.logger.warning(f"隧道 {tunnel_name} 无活跃连接：{detail}")
        elif health.ok is None and detail:
            reason = "API/5xx" if health.reason == "api_error" else "跳过自动重启"
            self.logger.info(f"隧道 {tunnel_name} 状态未知（{reason}）：{detail}")

        self._handle_auto_heal(tunnel_name, health)

    def _merge_gui_running_tunnels(self) -> bool:
        """补齐由 GUI 启动但尚未出现在系统探测结果中的隧道。"""
        added = False
        for name, proc in self.proc_map.items():
            if proc and proc.poll() is None and name not in self.running_tunnels:
                self.running_tunnels[name] = {
                    "name": name,
                    "pid": proc.pid,
                    "healthy": None,
                }
                added = True
        return added

    def _sync_running_tunnel_snapshot(self, running_tunnels_list: list) -> bool:
        """更新运行态快照，并返回是否需要刷新左侧列表状态。"""
        old_running = set(self.running_tunnels.keys())
        old_health = {name: info.get("healthy") for name, info in self.running_tunnels.items()}

        self.running_tunnels = {t["name"]: t for t in running_tunnels_list}
        new_running = {t["name"] for t in running_tunnels_list}
        new_health = {t["name"]: t.get("healthy") for t in running_tunnels_list}
        list_changed = old_running != new_running or old_health != new_health

        if self._merge_gui_running_tunnels():
            list_changed = True
        return list_changed

    def _refresh_proc_state(self):
        """检查子进程状态并同步UI（非阻塞版本）"""
        # 先在主线程快速检查本地进程状态（不阻塞）
        self.proc_tracker.cleanup_dead()
        self._check_supervisor_lock(log_message=False)
        cleaned = self._cleanup_exited_gui_processes()

        if cleaned and not self._manual_operation:
            self.status_var.set("隧道已停止")

        self._start_background_status_refresh()

    def _background_status_check(self, cloudflared_path: str | None):
        """后台线程：执行耗时的状态检查操作"""
        try:
            cache_ttl = int(self.settings.get("tunnel.health_cache_ttl", 30) or 30)
            test_timeout = int(self.settings.get("tunnel.health_check_timeout", 12) or 12)
            running_tunnels_list = self.runtime_service.get_running_tunnels_with_health(
                cloudflared_path,
                self._health_cache,
                cache_ttl=cache_ttl,
                timeout=test_timeout,
            )

            # 将结果传回主线程处理
            self.after(0, lambda data=running_tunnels_list: self._apply_status_update(data))
        except Exception as e:
            self.after(0, lambda: self._append_log(f"状态检查异常: {e}\n", "error"))
        finally:
            self._status_refresh_running = False

    def _apply_status_update(self, running_tunnels_list: list):
        """主线程：应用后台线程获取的状态更新"""
        for tunnel in running_tunnels_list:
            self._apply_running_tunnel_health(tunnel)

        if self._sync_running_tunnel_snapshot(running_tunnels_list) and hasattr(self, "tunnel_list"):
            self.tunnel_list.refresh_all_status()

        # 只在非手动操作时更新UI（避免闪烁）
        if not self._manual_operation:
            self._update_status_display()
            self._update_toggle_button_state()

    def _build_launch_output_options(self, tunnel_name: str, persist_enabled: bool) -> tuple[bool, Path | None]:
        """根据持久化开关生成启动输出选项。"""
        if not persist_enabled:
            return True, None

        log_dir = get_persistent_logs_dir()
        log_dir.mkdir(parents=True, exist_ok=True)
        return False, log_dir / f"{tunnel_name}.log"

    def _auto_heal_worker(self, tunnel_name: str, cloudflared_path: str, persist_enabled: bool):
        """后台执行自动重连，避免阻塞UI线程"""
        cfg = self._config_path_for(tunnel_name)
        capture_output, log_file = self._build_launch_output_options(tunnel_name, persist_enabled)

        self.after(0, lambda: self._append_log(f"自动重连：准备重启隧道 {tunnel_name} …\n", "info"))

        stop_pid = None
        try:
            proc = self.proc_map.get(tunnel_name)
            if proc and proc.poll() is None:
                self.runtime_service.stop_process(proc)
                stop_pid = proc.pid
        except Exception as exc:
            self.after(0, lambda e=exc: self._append_log(f"自动重连停止阶段异常: {e}\n", "error"))

        # 清理旧状态（在主线程）
        self.after(0, lambda pid=stop_pid: self._reset_proc_state(tunnel_name, expected_pid=pid))

        # 启动新隧道
        result = self._launch_tunnel_worker(cloudflared_path, tunnel_name, cfg, capture_output, log_file)
        self.after(0, lambda r=result: self._apply_auto_heal_result(tunnel_name, r))

    def _launch_tunnel_worker(self, cloudflared_path: str, tunnel_name: str, cfg: Path,
                              capture_output: bool, log_file: Path | None):
        """在后台启动隧道并等待健康检查（无UI操作）"""
        return self.lifecycle_service.launch_tunnel(
            cloudflared_path,
            tunnel_name,
            cfg,
            capture_output,
            log_file,
        )

    def _reset_proc_state(self, tunnel_name: str, expected_pid: int | None = None):
        """在主线程清理进程及运行状态"""
        proc = self.proc_map.get(tunnel_name)
        if expected_pid and proc and proc.pid != expected_pid:
            proc = None  # 仅清理匹配的旧进程
        if proc is self.proc:
            self.proc = None
            self.proc_thread = None
        self.proc_map.pop(tunnel_name, None)
        try:
            self.proc_tracker.unregister(tunnel_name, expected_pid=expected_pid or (proc.pid if proc else None))
        except Exception:
            pass
        self.running_tunnels.pop(tunnel_name, None)
        self._health_failures.pop(tunnel_name, None)
        self._last_status_state = None
        self._immediate_status_sync()

    def _clear_tunnel_runtime_state(self, tunnel_name: str, expected_pid: int | None = None):
        """清理隧道的运行态缓存，并取消自动重连标记。"""
        self._reset_proc_state(tunnel_name, expected_pid=expected_pid)
        self._auto_heal_pending.discard(tunnel_name)

    @staticmethod
    def _normalize_feedback_text(message: str | None) -> str:
        return str(message or "").strip()

    def _logger_for_tag(self, tag: str):
        return {
            "error": self.logger.error,
            "warning": self.logger.warning,
        }.get(tag, self.logger.info)

    def _messagebox_for_level(self, level: str):
        return {
            "error": messagebox.showerror,
            "warning": messagebox.showwarning,
        }.get(level, messagebox.showinfo)

    def _record_feedback(self, message: str | None, tag: str = "info"):
        """统一写入日志窗口和结构化 logger。"""
        text = self._normalize_feedback_text(message)
        if not text:
            return
        self._append_log(text + "\n", tag)
        self._logger_for_tag(tag)(text)

    def _record_feedback_lines(self, messages, tag: str = "info"):
        for message in messages or []:
            self._record_feedback(message, tag)

    def _notify_feedback(
        self,
        title: str,
        message: str | None,
        *,
        tag: str = "info",
        status: str | None = None,
        log_message: str | None = None,
        dialog_level: str | None = None,
    ):
        """统一处理状态栏、日志和弹窗。"""
        if status is not None:
            self.status_var.set(status)

        logged = log_message if log_message is not None else message
        self._record_feedback(logged, tag)

        text = self._normalize_feedback_text(message)
        if text:
            self._messagebox_for_level(dialog_level or tag)(title, text)

    def _show_dialog(self, title: str, message: str | None, level: str = "info"):
        text = self._normalize_feedback_text(message)
        if not text:
            return
        self._messagebox_for_level(level)(title, text)

    @staticmethod
    def _confirm_dialog(title: str, message: str) -> bool:
        return bool(messagebox.askyesno(title, message))

    @staticmethod
    def _prompt_text(title: str, prompt: str) -> str | None:
        return simpledialog.askstring(title, prompt)

    @staticmethod
    def _choose_open_file(title: str, filetypes) -> str:
        return filedialog.askopenfilename(title=title, filetypes=filetypes)

    @staticmethod
    def _choose_save_file(title: str, defaultextension: str, initialfile: str, filetypes) -> str:
        return filedialog.asksaveasfilename(
            title=title,
            defaultextension=defaultextension,
            initialfile=initialfile,
            filetypes=filetypes,
        )

    @staticmethod
    def _selected_tunnel_name(item: dict | None) -> str:
        return (item or {}).get("name", "unknown")

    def _require_cloudflared_path(
        self,
        *,
        title: str = "错误",
        message: str = "请先设置 cloudflared 路径",
        level: str = "error",
    ) -> str | None:
        path = self.cloudflared_path.get().strip()
        if path:
            return path
        self._messagebox_for_level(level)(title, message)
        return None

    def _require_selected_tunnel(
        self,
        *,
        title: str = "提示",
        message: str = "请先选择一个隧道",
        level: str = "info",
    ) -> dict | None:
        item = self.tunnel_list.get_selected()
        if item:
            return item
        self._messagebox_for_level(level)(title, message)
        return None

    def _require_tunnel_id(
        self,
        item: dict,
        *,
        title: str = "错误",
        message: str = "无法获取隧道ID",
        level: str = "error",
        log: bool = False,
    ) -> str | None:
        tunnel_id = self.runtime_service.extract_tunnel_id(item)
        if tunnel_id:
            return tunnel_id
        if log:
            self._record_feedback(message, level)
        self._messagebox_for_level(level)(title, message)
        return None

    def _notify_tunnel_running(self, tunnel_name: str):
        existing_info = self._get_running_tunnel_info(tunnel_name)
        pid_info = f" (PID: {existing_info['pid']})" if existing_info and existing_info.get("pid") else ""
        message = f"隧道 {tunnel_name} 已在运行中{pid_info}"
        self._show_dialog("提示", message)
        self._record_feedback(message, "warning")

    def _notify_tunnel_not_running(self, tunnel_name: str):
        self._show_dialog("提示", f"隧道 {tunnel_name} 未在运行")

    def _log_result_messages(self, result: dict):
        """将后台任务返回的消息和警告统一写入日志。"""
        self._record_feedback_lines(result.get("messages", []), "info")
        self._record_feedback_lines(result.get("warnings", []), "warning")

    def _adopt_running_tunnel(
        self,
        tunnel_name: str,
        launch: dict,
        *,
        source: str,
        status_text: str,
        success_log: str,
        success_logger: str,
        save_last_selected: bool = False,
        update_autostart: bool = False,
        log_persist_target: bool = False,
    ) -> bool:
        """接管已成功启动的隧道进程，并同步更新 GUI 状态。"""
        proc = launch.get("proc")
        if not proc:
            return False

        protocol = launch.get("protocol", "默认")
        detail = launch.get("detail", "")
        capture_output = launch.get("capture_output", True)
        log_file = launch.get("log_file")

        self.proc = proc
        self.proc_map[tunnel_name] = proc
        self.running_tunnels[tunnel_name] = {
            "name": tunnel_name,
            "pid": proc.pid,
            "healthy": True,
        }

        mode = "persist" if not capture_output else "interactive"
        try:
            self.proc_tracker.register(
                tunnel_name,
                proc.pid,
                manager="modern_gui",
                mode=mode,
                metadata={
                    "source": source,
                    "protocol": protocol,
                    "log_file": str(log_file) if log_file else "",
                },
            )
        except Exception:
            pass

        self.status_var.set(status_text.format(name=tunnel_name, protocol=protocol))
        self._append_log(success_log.format(name=tunnel_name, protocol=protocol) + "\n", "success")
        self.logger.info(success_logger.format(name=tunnel_name, protocol=protocol))
        if detail:
            self._append_log(f"{detail}\n", "info")

        if save_last_selected and self.settings.get("tunnel.save_last_selected", True):
            self.settings.set("tunnel.last_selected", tunnel_name)
        if update_autostart and self.autostart_var.get():
            self._set_autostart_target(tunnel_name)

        if capture_output:
            self.proc_thread = threading.Thread(target=self._read_proc_output, daemon=True)
            self.proc_thread.start()
        else:
            self.proc_thread = None
            if log_persist_target and log_file:
                self._append_log(f"持久化模式：cloudflared 输出写入 {log_file}\n", "info")
                self.logger.info(f"持久化日志写入 {log_file}")

        self._last_status_state = None
        self._immediate_status_sync()
        return True

    def _apply_adopted_running_result(
        self,
        tunnel_name: str,
        result: dict,
        *,
        source: str,
        status_text: str,
        success_log: str,
        success_logger: str,
        failure_message: str,
        failure_status: str,
        save_last_selected: bool = False,
        update_autostart: bool = False,
        log_persist_target: bool = False,
    ) -> bool:
        """接管成功启动的进程；若缺少进程句柄则统一按失败处理。"""
        adopted = self._adopt_running_tunnel(
            tunnel_name,
            result,
            source=source,
            status_text=status_text,
            success_log=success_log,
            success_logger=success_logger,
            save_last_selected=save_last_selected,
            update_autostart=update_autostart,
            log_persist_target=log_persist_target,
        )
        if adopted:
            return True

        self._record_feedback(failure_message, "error")
        self.status_var.set(failure_status)
        return False

    def _record_supervisor_command_acceptance(
        self,
        tunnel_name: str,
        result: dict,
        *,
        default_message: str,
        feedback_prefix: str,
        logger_prefix: str,
        status_text: str,
    ) -> str:
        """统一记录 supervisor 已接受命令时的状态栏、日志与提示文案。"""
        msg = self.operation_service.payload_message(result, default_message)
        feedback_text = f"{feedback_prefix}: {msg or default_message}"
        self._record_feedback(feedback_text, "success")
        self.logger.info(f"{logger_prefix} {tunnel_name}: {msg}")
        self.status_var.set(status_text)
        return msg

    def _notify_supervisor_result_failure(
        self,
        result: dict,
        *,
        title: str,
        default_message: str,
        log_message: str,
        status: str | None = None,
    ):
        """统一展示 supervisor 返回的失败结果。"""
        self._append_supervisor_payload_logs(result)
        message = self.operation_service.payload_message(result, default_message)
        self._notify_feedback(
            title,
            message,
            tag="error",
            status=status,
            log_message=log_message.format(message=message),
        )

    def _refresh_after_supervisor_command(self, tunnel_name: str | None = None):
        """在 supervisor 接管操作后同步本地运行态与 UI。"""
        if tunnel_name:
            self._clear_tunnel_runtime_state(tunnel_name)
            self._refresh_proc_state()
            return

        self._refresh_proc_state()
        self._immediate_status_sync()

    def _handle_start_success_result(self, tunnel_name: str, result: dict) -> bool:
        """处理统一启动结果中的成功分支。"""
        if not result.get("ok"):
            return False

        if result.get("managed_by") == "supervisor":
            self._record_supervisor_command_acceptance(
                tunnel_name,
                result,
                default_message="启动指令已发送",
                feedback_prefix="守护进程应答",
                logger_prefix="守护进程启动",
                status_text="启动指令已发送",
            )
            self._refresh_after_supervisor_command()
            return True

        return self._apply_adopted_running_result(
            tunnel_name,
            result,
            source="gui",
            status_text="隧道 {name} 已激活",
            success_log="隧道 {name} 已启动并激活（协议 {protocol}）",
            success_logger="隧道 {name} 已成功启动并激活，协议 {protocol}",
            failure_message=f"隧道 {tunnel_name} 启动失败：未获得进程句柄",
            failure_status="隧道启动失败",
            save_last_selected=True,
            update_autostart=True,
            log_persist_target=True,
        )

    def _handle_start_failure_result(self, tunnel_name: str, result: dict) -> bool:
        """处理手动启动流程中的失败结果。"""
        if result.get("ok"):
            return False

        stage = result.get("stage") or "launch"
        err = result.get("error") or result.get("message") or result.get("detail") or "未知错误"
        if result.get("managed_by") == "supervisor":
            self._notify_supervisor_result_failure(
                result,
                title="守护进程启动失败",
                default_message=str(err),
                log_message="守护进程启动失败: {message}",
                status="启动失败",
            )
            return True

        if stage == "dns":
            hostname = result.get("hostname") or ""
            self._notify_feedback(
                "DNS 路由失败",
                f"{hostname} 配置失败：\n{err}",
                tag="error",
                status="DNS 路由失败",
                log_message=f"DNS 路由失败: {hostname} - {err}",
            )
            return True

        if stage == "config":
            self._notify_feedback(
                "启动失败",
                f"配置处理失败：\n{err}",
                tag="error",
                status="启动失败",
                log_message=f"配置处理失败: {err}",
            )
            return True

        self._notify_feedback(
            "启动失败",
            f"未检测到活跃连接，隧道启动失败。\n{err}",
            tag="error",
            status="隧道启动失败",
            log_message=f"隧道 {tunnel_name} 启动失败：{err}",
        )
        return True

    def _finish_start_selected(self, tunnel_name: str, result: dict):
        """在主线程完成手动启动后的 UI 收尾。"""
        self._manual_operation = False
        try:
            self._log_result_messages(result)

            if self._handle_start_failure_result(tunnel_name, result):
                return

            if self._handle_start_success_result(tunnel_name, result):
                return

            self._record_feedback(f"隧道 {tunnel_name} 启动失败：未获得进程句柄", "error")
            self.status_var.set("隧道启动失败")
        finally:
            self._unlock_tunnel_operation()

    def _apply_auto_heal_result(self, tunnel_name: str, result: dict):
        """在主线程应用自动重连结果"""
        self._auto_heal_pending.discard(tunnel_name)
        if not result.get("ok"):
            err = result.get("error", "自动重连失败")
            self._record_feedback(f"自动重连失败：{err}", "error")
            self.status_var.set("自动重连失败")
            return

        self._apply_adopted_running_result(
            tunnel_name,
            result,
            source="auto-heal",
            status_text="隧道 {name} 已激活",
            success_log="隧道 {name} 自动重连成功（协议 {protocol}）",
            success_logger="自动重连成功：{name}，协议 {protocol}",
            failure_message="自动重连失败：未获得进程句柄",
            failure_status="自动重连失败",
        )

    def _restart_gui_tunnel(self, tunnel_name: str, cloudflared_path: str | None = None, persist_enabled: bool | None = None):
        """在GUI托管模式下安全地重启隧道（后台线程执行重连，避免卡顿）"""
        if self._supervisor_active and self._supervisor_available:
            self._auto_heal_pending.discard(tunnel_name)
            return

        path = cloudflared_path or self.runtime_service.resolve_cloudflared_path(self.cloudflared_path.get().strip())
        if not path:
            self._record_feedback("自动重连失败：未设置 cloudflared 路径", "error")
            self._auto_heal_pending.discard(tunnel_name)
            return

        if persist_enabled is None:
            persist_enabled = bool(self.persist_var.get())

        # 在后台线程执行重启，避免阻塞主线程
        threading.Thread(
            target=self._auto_heal_worker,
            args=(tunnel_name, path, persist_enabled),
            daemon=True,
        ).start()

    def _is_tunnel_running(self, tunnel_name: str = None) -> bool:
        """检查隧道是否在运行（包括外部启动的）"""
        # 如果没有指定名称，检查是否有任何隧道在运行
        if tunnel_name is None:
            if any(proc and proc.poll() is None for proc in self.proc_map.values()):
                return True
            return len(getattr(self, 'running_tunnels', {})) > 0

        # 检查特定隧道
        proc = self.proc_map.get(tunnel_name)
        if proc and proc.poll() is None:
            return True

        return tunnel_name in getattr(self, 'running_tunnels', {})

    def _get_running_tunnel_info(self, tunnel_name: str) -> dict | None:
        """获取运行中隧道的信息"""
        return getattr(self, 'running_tunnels', {}).get(tunnel_name)

    def _is_tunnel_active(self, tunnel_name: str | None = None) -> bool:
        """运行且有活跃连接才视为已激活。"""
        if not tunnel_name:
            return False
        if not self._is_tunnel_running(tunnel_name):
            return False
        info = self._get_running_tunnel_info(tunnel_name) or {}
        return info.get("healthy") is True

    def _update_toggle_button_state(self):
        """根据运行状态更新启动/停止按钮"""
        # 获取当前选中的隧道
        selected = self.tunnel_list.get_selected()
        tunnel_name = selected.get("name") if selected else None

        # 检查该隧道是否在运行
        running = self._is_tunnel_running(tunnel_name) if tunnel_name else False

        if not self.toggle_button:
            return

        if running:
            self.toggle_button_var.set("⏹ 停止")
            self.toggle_button.configure(bg=Theme.ERROR, activebackground=Theme.ERROR)
        else:
            self.toggle_button_var.set("▶ 启动")
            self.toggle_button.configure(bg=Theme.SUCCESS, activebackground=Theme.SUCCESS)

    def _check_supervisor_lock(self, log_message: bool = True) -> bool:
        """检测是否存在激活的隧道守护进程"""
        result = self.coordination_service.sync_supervisor_state(
            self._supervisor_active,
            log_message=log_message,
        )
        self._supervisor_available = result.available
        self._supervisor_active = result.active

        if result.ui_message:
            self._append_log(result.ui_message + "\n", result.ui_level)
        if result.logger_message:
            self._logger_for_tag(result.ui_level)(result.logger_message)

        return result.active

    def _format_supervisor_status_payload(self, payload: dict) -> str:
        entries = payload.get("entries")
        if not isinstance(entries, list):
            return str(payload.get("message") or "守护进程正在运行。")

        configured_entries = [entry for entry in entries if isinstance(entry, dict) and entry.get("configured")]
        running_entries = [entry for entry in configured_entries if entry.get("running")]
        healthy_count = sum(1 for entry in running_entries if entry.get("healthy") is True)
        unknown_count = sum(1 for entry in running_entries if entry.get("healthy") is None)

        lines = [
            f"已配置 {len(configured_entries)} 个隧道，运行中 {len(running_entries)} 个，健康 {healthy_count} 个，状态未知 {unknown_count} 个。"
        ]

        for entry in entries:
            if not isinstance(entry, dict):
                continue

            name = str(entry.get("name") or "unknown")
            state = str(entry.get("state") or ("未配置" if not entry.get("configured") else "未知"))
            extras = []
            pid = entry.get("pid")
            if pid:
                extras.append(f"PID {pid}")
            manager = entry.get("manager")
            if manager:
                extras.append(f"管理: {manager}")
            auto_start = entry.get("auto_start")
            if auto_start is not None:
                extras.append(f"自启: {'开' if auto_start else '关'}")

            line = f"- {name}: {state}"
            if extras:
                line += f" ({', '.join(extras)})"
            lines.append(line)

            summary = str(entry.get("summary") or "").strip()
            if summary:
                lines.append(f"  {summary}")

        return "\n".join(lines)

    def _append_supervisor_payload_logs(self, payload: dict):
        logs = payload.get("logs")
        if not isinstance(logs, list):
            return

        for raw in logs:
            line = str(raw).strip()
            if not line:
                continue

            ui_level = "info"
            logger = self.logger.info
            if "[ERROR]" in line:
                ui_level = "error"
                logger = self.logger.error
            elif "[WARNING]" in line or "[WARN" in line:
                ui_level = "warning"
                logger = self.logger.warning

            message = f"[supervisor] {line}"
            self._append_log(message + "\n", ui_level)
            logger(message)

    def _show_supervisor_status(self):
        """弹窗展示守护进程状态"""
        if not self._supervisor_available:
            self._show_dialog(
                "守护进程状态",
                "未检测到 tunnel_supervisor，可通过“部署 Supervisor”脚本启用。"
            )
            return

        payload = self.supervisor_client.status_payload()
        ok = bool(payload.get("ok"))
        if ok:
            display = self._format_supervisor_status_payload(payload)
            self._show_dialog("守护进程状态", display)
            self._append_log(f"守护进程状态:\n{display}\n", "info")
        else:
            error_text = self.operation_service.payload_message(payload, "无法获取守护进程状态。")
            self._show_dialog("守护进程状态", error_text, "error")
            self._append_log(f"守护进程状态查询失败: {error_text}\n", "error")

    def _can_control_tunnel(self, tunnel_name: str | None) -> bool:
        """确认 GUI 是否有权操作指定隧道"""
        if not tunnel_name:
            return False

        if self._supervisor_active:
            if not self._supervisor_available:
                self._show_dialog(
                    "守护进程限制",
                    "检测到隧道守护进程正在运行，但 GUI 无法与其通信，请先停止 tunnel_supervisor。",
                    "warning",
                )
                return False
            # 守护进程已连接，可继续操作（交由守护进程执行）
            return True

        record = self.proc_tracker.read(tunnel_name)
        if not record:
            return True

        if record.alive and record.manager not in {"modern_gui", "gui"}:
            self._show_dialog(
                "管理冲突",
                f"隧道 {tunnel_name} 正由 {record.manager} 管理 (PID: {record.pid})。\n"
                "请先停止对应进程或通过守护进程接口进行操作。",
                "error",
            )
            return False

        if not record.alive:
            self.proc_tracker.unregister(tunnel_name)
        return True

    def _init_app(self):
        """初始化应用"""
        self.logger.info("应用程序启动")
        self.proc_tracker.cleanup_dead()
        self._check_supervisor_lock()
        self._refresh_version()

        # 首先检测系统中运行的隧道
        self._refresh_proc_state()

        self.refresh_tunnels()

        # 刷新隧道列表的激活状态
        if hasattr(self, "tunnel_list"):
            self.tunnel_list.refresh_all_status()

        self._update_status_display()
        self._update_toggle_button_state()

        # 启动定期状态刷新
        self._schedule_status_refresh()
        self.after(1500, self._auto_start_if_enabled)

    def _auto_start_if_enabled(self, force: bool = False):
        """必要时自动启动隧道"""
        target = self.settings.get("tunnel.autostart_tunnel") or self.settings.get("tunnel.last_selected")
        plan = self.coordination_service.plan_autostart(
            already_done=self._auto_start_done,
            force=force,
            enabled=bool(self.settings.get("tunnel.auto_start_enabled", False)),
            target=target,
            supervisor_active=self._supervisor_active,
            supervisor_available=self._supervisor_available,
            is_running=self._is_tunnel_running(target) if target else False,
        )

        if plan.ui_message:
            self._append_log(plan.ui_message + "\n", plan.ui_level)
        if plan.logger_message:
            self._logger_for_tag(plan.ui_level)(plan.logger_message)

        if plan.action == "noop":
            self._auto_start_done = True
            return

        if plan.action == "supervisor" and plan.target:
            ok, msg = self.supervisor_client.start_tunnel(plan.target)
            if ok:
                self.logger.info(f"自动启动指令已发送给守护进程: {plan.target}")
            else:
                self.logger.error(f"守护进程自动启动 {plan.target} 失败: {msg}")
            self._auto_start_done = True
            return

        if plan.action != "direct" or not plan.target:
            self._auto_start_done = True
            return

        if hasattr(self, "tunnel_list"):
            if not self.tunnel_list.select_by_name(plan.target):
                self._append_log(f"自动启动失败：未找到隧道 {plan.target}\n", "error")
                self.logger.error(f"自动启动失败，未找到 {plan.target}")
                self._auto_start_done = True
                return
        else:
            self._auto_start_done = True
            return

        self._start_selected()
        self._auto_start_done = True

    def _begin_tunnel_operation(
        self,
        *,
        button_text: str,
        status_text: str,
        log_message: str,
        log_tag: str,
    ):
        """统一锁定隧道操作按钮，并同步操作中的 UI 文案。"""
        self._tunnel_operation_in_progress = True
        self._manual_operation = True
        if self.toggle_button:
            try:
                self.toggle_button.configure(state=tk.DISABLED)
            except Exception:
                pass
        self.toggle_button_var.set(button_text)
        self.status_var.set(status_text)
        self._append_log(log_message + "\n", log_tag)
        self._logger_for_tag(log_tag)(log_message)

    def _run_async_tunnel_operation(
        self,
        worker: Callable[[], dict],
        on_complete: Callable[[dict], None],
        on_exception: Callable[[Exception], dict],
    ):
        """在线程中执行隧道操作，并把结果安全地回送到主线程。"""
        def _thread_entry():
            try:
                result = worker()
            except Exception as exc:
                result = on_exception(exc)
            try:
                self.after(0, lambda r=result: on_complete(r))
            except Exception:
                pass

        threading.Thread(target=_thread_entry, daemon=True).start()

    def _schedule_status_refresh(self):
        """定期刷新隧道状态（每5秒）"""
        # 只有在没有进行其他操作时才自动刷新
        if not getattr(self, '_manual_operation', False):
            self._refresh_proc_state()

        # 继续计划下次刷新
        self.after(5000, self._schedule_status_refresh)

    def _immediate_status_sync(self):
        """立即同步状态（用于操作后）"""
        self._manual_operation = True
        # 更新UI
        self._update_status_display()
        self._update_toggle_button_state()
        # 刷新左侧隧道列表的状态显示
        if hasattr(self, "tunnel_list"):
            self.tunnel_list.refresh_all_status()
        # 短暂延迟后恢复自动刷新
        self.after(1000, lambda: setattr(self, '_manual_operation', False))

    def _update_status_display(self):
        """更新状态显示 - 避免闪烁的优化版本"""
        # 获取当前状态
        cloudflared_path = self.cloudflared_path.get().strip()
        cf_installed = bool(cloudflared_path and Path(cloudflared_path).exists())
        auth_ready, _, _ = self._cert_status_summary()
        selected = self.tunnel_list.get_selected()
        current_tunnel_name = selected.get("name") if selected else None
        is_running = self._is_tunnel_running(current_tunnel_name) if current_tunnel_name else False
        is_activated = self._is_tunnel_active(current_tunnel_name) if current_tunnel_name else False
        tunnel_count = len(self._tunnels)
        selected_name = selected.get("name", "未选择") if selected else "未选择"
        manager_text = "守护进程托管" if self._supervisor_active and self._supervisor_available else ("守护进程运行中" if self._supervisor_active else "GUI 直接管理")

        self._refresh_setup_guidance(
            cloudflared_ready=cf_installed,
            auth_ready=auth_ready,
            selected_name=current_tunnel_name,
            is_running=is_running,
            is_activated=is_activated,
        )

        # 获取运行的隧道信息
        running_info = ""
        if is_running and current_tunnel_name:
            tunnel_info = self._get_running_tunnel_info(current_tunnel_name)
            if tunnel_info:
                running_info = f" (PID: {tunnel_info['pid']})"

        # 如果状态没有变化，不重新创建widgets（避免闪烁）
        current_state = (
            cf_installed,
            auth_ready,
            manager_text,
            current_tunnel_name,
            is_running,
            is_activated,
            running_info,
            tunnel_count,
            selected_name,
        )
        if hasattr(self, '_last_status_state'):
            last_state = self._last_status_state
            if last_state == current_state:
                return  # 状态没有变化，不更新

        # 保存当前状态
        self._last_status_state = current_state
        self._ensure_status_badges()

        self._set_status_badge(
            "cloudflared",
            "Cloudflared",
            "已就绪" if cf_installed else "未安装",
            "success" if cf_installed else "error",
            "✓" if cf_installed else "✗"
        )
        self._set_status_badge(
            "auth_state",
            "Cloudflare 认证",
            "已授权" if auth_ready else "未登录",
            "success" if auth_ready else "warning",
            "🔑" if auth_ready else "!"
        )
        self._set_status_badge(
            "control_mode",
            "控制方式",
            manager_text,
            "info" if self._supervisor_active and self._supervisor_available else ("warning" if self._supervisor_active else "default"),
            "⚙"
        )
        self._set_status_badge(
            "tunnel_state",
            "隧道状态",
            f"已激活{running_info}" if is_activated else ("运行中(无连接)" if is_running else "未激活"),
            "success" if is_activated else ("warning" if is_running else "default"),
            "●" if is_activated else ("○" if not is_running else "!")
        )
        self._set_status_badge(
            "tunnel_count",
            "隧道总数",
            f"{tunnel_count} 个",
            "info" if tunnel_count > 0 else "default",
            "#"
        )
        self._set_status_badge(
            "selected_tunnel",
            "当前选中",
            selected_name,
            "info" if selected else "default",
            "•"
        )

    def _ensure_status_badges(self):
        """Create the status widgets once and update them in place."""
        if getattr(self, "_status_badges", None):
            return

        for widget in self.status_display.winfo_children():
            widget.destroy()

        status_grid = tk.Frame(self.status_display, bg=Theme.BG_CARD)
        status_grid.pack(fill=tk.BOTH, expand=True)

        row1 = tk.Frame(status_grid, bg=Theme.BG_CARD)
        row1.pack(fill=tk.X, pady=8)

        row2 = tk.Frame(status_grid, bg=Theme.BG_CARD)
        row2.pack(fill=tk.X, pady=8)

        self._status_badges = {
            "cloudflared": self._create_status_badge(row1),
            "auth_state": self._create_status_badge(row1),
            "control_mode": self._create_status_badge(row1),
            "tunnel_state": self._create_status_badge(row2),
            "tunnel_count": self._create_status_badge(row2),
            "selected_tunnel": self._create_status_badge(row2),
        }

    def _status_badge_colors(self, status: str) -> tuple[str, str]:
        """Resolve colors for a status badge."""
        if status == "success":
            return Theme.SUCCESS_BG, Theme.SUCCESS
        if status == "error":
            return Theme.ERROR_BG, Theme.ERROR
        if status == "warning":
            return Theme.WARNING_BG, Theme.WARNING
        if status == "info":
            return Theme.INFO_BG, Theme.INFO
        return Theme.BG_HOVER, Theme.TEXT_SECONDARY

    def _create_status_badge(self, parent):
        """Create a reusable status badge."""
        container = tk.Frame(parent, bg=Theme.BG_CARD)
        container.pack(side=tk.LEFT, padx=8)

        badge = tk.Frame(
            container,
            bg=Theme.BG_HOVER,
            highlightthickness=0
        )
        badge.pack(fill=tk.BOTH, padx=2, pady=2)

        content = tk.Frame(badge, bg=Theme.BG_HOVER)
        content.pack(padx=12, pady=8)

        icon_label = tk.Label(
            content,
            text="",
            bg=Theme.BG_HOVER,
            fg=Theme.TEXT_SECONDARY,
            font=(Theme.FONT_FAMILY, 11)
        )

        label_frame = tk.Frame(content, bg=Theme.BG_HOVER)
        label_frame.pack(side=tk.LEFT)

        label_label = tk.Label(
            label_frame,
            text="",
            bg=Theme.BG_HOVER,
            fg=Theme.TEXT_MUTED,
            font=(Theme.FONT_FAMILY, 8)
        )
        label_label.pack(anchor="w")

        value_label = tk.Label(
            label_frame,
            text="",
            bg=Theme.BG_HOVER,
            fg=Theme.TEXT_SECONDARY,
            font=(Theme.FONT_FAMILY, 10, "bold")
        )
        value_label.pack(anchor="w")

        return {
            "badge": badge,
            "content": content,
            "icon_label": icon_label,
            "label_frame": label_frame,
            "label_label": label_label,
            "value_label": value_label,
        }

    def _set_status_badge(self, key, label, value, status="default", icon=""):
        """Update an existing status badge."""
        refs = self._status_badges[key]
        bg_color, fg_color = self._status_badge_colors(status)

        refs["badge"].configure(bg=bg_color)
        refs["content"].configure(bg=bg_color)
        refs["label_frame"].configure(bg=bg_color)
        refs["label_label"].configure(text=label, bg=bg_color, fg=Theme.TEXT_MUTED)
        refs["value_label"].configure(text=value, bg=bg_color, fg=fg_color)

        icon_label = refs["icon_label"]
        if icon:
            icon_label.configure(text=Theme.ui_text(icon), bg=bg_color, fg=fg_color)
            if icon_label.winfo_manager() != "pack":
                icon_label.pack(side=tk.LEFT, padx=(0, 6), before=refs["label_frame"])
        elif icon_label.winfo_manager() == "pack":
            icon_label.pack_forget()

    def _cert_status_summary(self) -> tuple[bool, str, str]:
        """返回证书的状态标签和详细描述"""
        status = self.auth_service.get_origin_cert_status(None)
        exists, cert_path, updated = status.exists, status.path, status.updated
        if exists and cert_path:
            label = "✅ cert.pem"
            detail = f"认证证书已就绪：{cert_path}"
            if updated:
                label = f"✅ cert.pem ({updated})"
                detail += f"\n最后更新：{updated}"
        else:
            label = "❌ 未找到"
            detail = '未找到 Cloudflare 认证证书 cert.pem，请点击"登录"完成授权。'
        return exists, label, detail

    def _refresh_setup_guidance(
        self,
        *,
        cloudflared_ready: bool,
        auth_ready: bool,
        selected_name: str | None,
        is_running: bool,
        is_activated: bool,
    ):
        """更新面向普通用户的操作引导。"""
        cloudflared_text = "工具状态：已找到 cloudflared，可直接管理隧道。" if cloudflared_ready else "工具状态：尚未配置 cloudflared，请先下载或选择可执行文件。"
        auth_text = "登录状态：已检测到 Cloudflare 认证，可新建和管理隧道。" if auth_ready else "登录状态：尚未完成 Cloudflare 授权，先点击“登录授权”。"

        if not cloudflared_ready:
            next_step = "下一步：先点击“下载/更新”或“选择文件”，完成 cloudflared 准备。"
        elif not auth_ready:
            next_step = "下一步：点击“登录授权”，在浏览器中完成 Cloudflare 授权。"
        elif not self._tunnels:
            next_step = "下一步：点击“刷新列表”加载已有隧道，或点击“新建隧道”创建一个。"
        elif not selected_name:
            next_step = "下一步：从左侧列表选择一个隧道，然后点击“启动”。"
        elif is_activated:
            next_step = f"下一步：{selected_name} 已联通，可直接访问已绑定的域名。"
        elif is_running:
            next_step = f"下一步：{selected_name} 正在运行，但连接尚未完全建立，可稍等片刻后再访问。"
        else:
            next_step = f"下一步：点击“启动”激活 {selected_name}。"

        if self._supervisor_active and self._supervisor_available:
            next_step += " 当前由守护进程托管，启动/停止会自动转交给后台。"

        self.setup_cloudflared_var.set(cloudflared_text)
        self.setup_auth_var.set(auth_text)
        self.setup_next_step_var.set(next_step)

    # ========== 功能方法 ==========

    def _choose_cloudflared(self):
        """选择 cloudflared 可执行文件"""
        path = self._choose_open_file("选择 cloudflared 可执行文件", self.binary_service.selectable_filetypes())
        if path:
            self.cloudflared_path.set(path)
            self.settings.set("cloudflared.path", path)
            self.logger.info(f"已选择 cloudflared 路径: {path}")
            self._refresh_version()
            self.refresh_tunnels()
            self._update_status_display()

    def _download_cloudflared(self):
        """下载 cloudflared"""
        self._run_download_flow(mode="download")

    def _check_update_cloudflared(self):
        """检查并下载最新 cloudflared"""
        self._run_download_flow(mode="update")

    def _run_download_flow(self, mode: str):
        """共享的下载/更新流程"""
        start_log = "正在检查 cloudflared 更新...\n" if mode == "update" else "正在下载 cloudflared...\n"
        busy_status = "检查更新中…" if mode == "update" else "下载准备中…"
        success_label = "更新完成" if mode == "update" else "下载完成"
        fail_label = "更新失败" if mode == "update" else "下载失败"

        self._append_log(start_log, "info")
        self.logger.info(start_log.strip())
        self.status_var.set(busy_status)

        def progress(pct: int):
            self.after(0, lambda: self.status_var.set(f"下载中… {pct}%"))

        def _worker():
            result = self.binary_service.download_binary(progress_cb=progress)

            def _finish():
                cert_ok, _, cert_detail = self._cert_status_summary()
                cert_append = f"\n\n证书状态：\n{cert_detail}"
                extra = f"\n版本: {result.version}" if result.version else ""
                if result.ok:
                    self.cloudflared_path.set(str(result.target_path))
                    self.settings.set("cloudflared.path", str(result.target_path))
                    self._refresh_version()
                    self._record_feedback(f"{result.message}{extra}", "success")
                    title = success_label if cert_ok else f"{success_label}（需登录）"
                    self._show_dialog(title, result.message + extra + cert_append, "info" if cert_ok else "warning")
                    tag = "success" if cert_ok else "warning"
                    self._record_feedback(cert_detail, tag)
                    self.status_var.set(success_label if cert_ok else "缺少认证")
                else:
                    self._record_feedback(result.message, "error")
                    self._show_dialog(f"{fail_label}", result.message + cert_append, "error")
                    tag = "success" if cert_ok else "warning"
                    self._record_feedback(cert_detail, tag)
                    self.status_var.set(fail_label)

                self._update_status_display()
            self.after(0, _finish)

        threading.Thread(target=_worker, daemon=True).start()

    def _confirm_replace_origin_cert(self, cert_path: Path) -> bool:
        """确认是否删除现有认证并重新登录。"""
        response = self._confirm_dialog(
            "已存在认证",
            "检测到已存在 Cloudflare 认证文件。\n"
            f"路径：{cert_path}\n\n"
            "是否要删除现有认证并重新登录？\n\n"
            "选择'是'将删除现有认证重新登录\n"
            "选择'否'将跳过登录（使用现有认证）"
        )
        if response:
            return True

        self.status_var.set("使用现有认证")
        return False

    def _delete_origin_cert_for_login(self, cert_path: Path) -> bool:
        """删除已有 cert.pem，便于重新触发登录。"""
        ok, msg = self.auth_service.delete_origin_cert(cert_path)
        if ok:
            self._record_feedback(msg, "info")
            return True
        self._notify_feedback("错误", msg, tag="error")
        return False

    def _start_cloudflare_login(self, cloudflared_path: str) -> bool:
        """启动 Cloudflare 浏览器授权流程。"""
        ok, msg = self.auth_service.start_login(cloudflared_path)
        if not ok:
            self._notify_feedback("无法登录", msg, tag="error", log_message=f"登录失败: {msg}")
            return False

        self.status_var.set("已启动登录流程，请在浏览器中完成授权…")
        self._record_feedback("正在打开浏览器进行 Cloudflare 授权...", "info")
        self.logger.info("已启动 Cloudflare 登录流程")
        self.after(2000, lambda: self.status_var.set("就绪"))
        return True

    def _login(self):
        """登录 Cloudflare"""
        path = self._require_cloudflared_path()
        if not path:
            return

        cert_path = self.auth_service.find_origin_cert(None)
        if cert_path and not self._confirm_replace_origin_cert(cert_path):
            return
        if cert_path and not self._delete_origin_cert_for_login(cert_path):
            return

        self._start_cloudflare_login(path)

    def _refresh_version(self):
        """刷新版本信息"""
        path = self.cloudflared_path.get().strip()
        info = self.binary_service.version_info(path)
        self.version_label.config(text=info.display_text)
        if info.short_version:
            self.logger.debug(f"Cloudflared 版本: {info.short_version}")

    def refresh_tunnels(self):
        """刷新隧道列表"""
        path = self.cloudflared_path.get().strip()
        if not path:
            self.tunnel_list.set_tunnels([], "尚未配置 cloudflared", "点击右上角的按钮设置 cloudflared 可执行文件。")
            self._append_log("未设置 cloudflared 路径\n", "warning")
            self.logger.warning("未设置 cloudflared 路径")
            self.status_var.set("请先设置 cloudflared 路径")
            return

        if self._tunnel_list_refreshing:
            self.status_var.set("刷新中…")
            return

        self._tunnel_list_refreshing = True
        self.tunnel_list.set_tunnels([], "正在刷新隧道列表…", "cloudflared 正在返回最新的隧道信息。")
        self._append_log("正在刷新隧道列表...\n", "info")
        self.logger.info("开始刷新隧道列表")

        def _worker(cloudflared_path: str):
            result = self.catalog_service.load_tunnels(cloudflared_path)

            def _finish():
                self._tunnel_list_refreshing = False

                if result.source == "binary-error":
                    error_text = result.error or "cloudflared 不可用"
                    self._append_log(f"刷新隧道失败: {error_text}\n", "error")
                    self.logger.error(f"刷新隧道失败: {error_text}")
                    self._show_dialog("cloudflared 不可用", error_text, "error")
                    self.status_var.set("cloudflared 不可用")
                    self.tunnel_list.set_tunnels([], "加载失败", "请检查 cloudflared 是否可执行，或重新选择可执行文件。")
                    return

                self._apply_tunnel_list_result(result)

            try:
                self.after(0, _finish)
            except Exception:
                self._tunnel_list_refreshing = False

        threading.Thread(target=_worker, args=(path,), daemon=True).start()

    def _apply_tunnel_list_result(self, result: TunnelCatalogLoadResult):
        """应用隧道列表刷新结果（必须在主线程调用）"""
        self._record_feedback_lines(result.messages, "info")
        self._record_feedback_lines(result.warnings, "warning")

        if not result.ok:
            error_text = result.error or "刷新隧道失败"
            self._record_feedback(f"刷新隧道失败: {error_text}", "error")
            self.tunnel_list.set_tunnels([], "加载失败", "无法访问 Cloudflare API，请检查网络/代理或使用本地配置。")
            self.status_var.set("网络不可用")
            return

        self._tunnels = result.tunnels
        self._apply_tunnel_filter()
        if result.source == "offline":
            self.status_var.set("离线模式")
            self.logger.info(f"从本地配置加载 {len(result.tunnels)} 个隧道")
            return

        self.status_var.set(f"已加载 {len(result.tunnels)} 个隧道")
        self._record_feedback(f"已加载 {len(result.tunnels)} 个隧道", "success")

    def _on_tunnel_select(self, tunnel_data):
        """隧道选择事件"""
        name = tunnel_data.get("name", "Unknown")
        self._append_log(f"选中隧道: {name}\n", "info")
        self.logger.info(f"选中隧道: {name}")

        if self.settings.get("tunnel.save_last_selected", True):
            self.settings.set("tunnel.last_selected", name)
        if self.autostart_var.get() and not self.settings.get("tunnel.autostart_tunnel"):
            self._set_autostart_target(name)

        # 刷新进程状态
        self._refresh_proc_state()

        # 更新UI
        self._update_status_display()
        self._update_toggle_button_state()

    def _create_tunnel(self):
        """创建新隧道"""
        path = self._require_cloudflared_path()
        if not path:
            return

        cert = self.auth_service.find_origin_cert(None)
        if cert is None:
            self._show_dialog("缺少认证", '未找到 Cloudflare 认证证书 cert.pem，请先点击"登录"完成授权。', "error")
            self._append_log("未找到 cert.pem，请先运行登录\n", "warning")
            self.logger.warning("未找到认证证书，无法创建隧道")
            return

        name = self._prompt_text("新建隧道", "请输入隧道名称:")
        if not name:
            return

        self._append_log(f"正在创建隧道: {name}...\n", "info")
        self.logger.info(f"开始创建隧道: {name}")
        result = self.catalog_service.create_tunnel(path, name, cert)
        self._record_feedback_lines(result.warnings, "warning")

        if result.ok:
            self._record_feedback(result.message, "success")
            if result.detail:
                self._record_feedback(result.detail, "info")
            self.refresh_tunnels()
        else:
            error_text = result.error or result.detail or result.message
            self._notify_feedback("创建失败", error_text, tag="error", log_message=f"创建失败: {error_text}")

    def _delete_selected(self):
        """删除选中的隧道"""
        path = self._require_cloudflared_path()
        if not path:
            return

        item = self._require_selected_tunnel(message="请先选择要删除的隧道", level="warning")
        if not item:
            return

        name = self._selected_tunnel_name(item)
        if not self._confirm_dialog("确认删除", f"确定要删除隧道 '{name}' 吗？\n此操作不可恢复。"):
            return

        self._append_log(f"正在删除隧道: {name}...\n", "warning")
        self.logger.warning(f"开始删除隧道: {name}")
        result = self.catalog_service.delete_tunnel(path, name)
        self._record_feedback_lines(result.warnings, "warning")

        if result.ok:
            self._record_feedback(result.message, "success")
            if result.detail:
                self._record_feedback(result.detail, "info")
            self.refresh_tunnels()
        else:
            error_text = result.error or result.detail or result.message
            self._notify_feedback("删除失败", error_text, tag="error", log_message=f"删除失败: {error_text}")

    def _config_path_for(self, tunnel_name: str) -> Path:
        """获取隧道配置文件路径"""
        return self.catalog_service.config_path_for(tunnel_name)

    def _start_via_supervisor_if_available(self, tunnel_name: str) -> dict | None:
        """如果当前由 supervisor 托管，则转交给 supervisor 启动。"""
        if not (self._supervisor_active and self._supervisor_available):
            return None

        payload = self.supervisor_client.start_tunnel_payload(tunnel_name)
        return self.operation_service.build_supervisor_start_result(tunnel_name, payload)

    def _edit_selected_config(self):
        """编辑配置（使用内置编辑器）"""
        item = self._require_selected_tunnel()
        if not item:
            return

        name = self._selected_tunnel_name(item)

        if not self._can_control_tunnel(name):
            return
        tid = self._require_tunnel_id(item)
        if not tid:
            return

        cfg = self._config_path_for(name)

        # 导入并打开配置编辑器
        try:
            from .gui import ConfigEditor
        except:
            from gui import ConfigEditor

        editor = ConfigEditor(self, cfg, name, tid)
        self.wait_window(editor)

        self._append_log(f"配置编辑完成: {name}\n", "info")
        self.logger.info(f"配置编辑完成: {name}")

    def _start_selected(self):
        """启动选中的隧道（后台执行，避免阻塞UI）"""
        if self._tunnel_operation_in_progress:
            return

        self._refresh_proc_state()

        path = self._require_cloudflared_path()
        if not path:
            return

        item = self._require_selected_tunnel(message="请先选择要启动的隧道", level="warning")
        if not item:
            return

        name = self._selected_tunnel_name(item)
        if not self._can_control_tunnel(name):
            return

        # 已在运行则不重复启动
        if self._is_tunnel_running(name):
            self._notify_tunnel_running(name)
            return

        tid = self._require_tunnel_id(item, log=True)
        if not tid:
            return

        persist_enabled = bool(self.persist_var.get())
        capture_output, log_file = self._build_launch_output_options(name, persist_enabled)

        cfg = self._config_path_for(name)

        self._begin_tunnel_operation(
            button_text="⏳ 启动中…",
            status_text=f"启动中：{name}",
            log_message=f"正在启动隧道: {name}...",
            log_tag="info",
        )

        def _worker() -> dict:
            supervisor_result = self._start_via_supervisor_if_available(name)
            if supervisor_result is not None:
                return supervisor_result
            return self.lifecycle_service.start_direct_tunnel(
                path,
                name,
                tid,
                cfg,
                capture_output,
                log_file,
            )

        self._run_async_tunnel_operation(
            _worker,
            lambda result: self._finish_start_selected(name, result),
            lambda exc: self.operation_service.build_start_exception_result(name, exc),
        )

    def _stop_via_supervisor_if_available(self, tunnel_name: str) -> dict | None:
        """如果当前由 supervisor 托管，则转交给 supervisor 停止。"""
        if not (self._supervisor_active and self._supervisor_available):
            return None

        payload = self.supervisor_client.stop_tunnel_payload(tunnel_name)
        return self.operation_service.build_supervisor_stop_result(tunnel_name, payload)

    def _stop_tunnel_worker(self, tunnel_name: str, proc: subprocess.Popen | None) -> dict:
        """在后台执行停止逻辑，不直接操作 UI。"""
        supervisor_result = self._stop_via_supervisor_if_available(tunnel_name)
        if supervisor_result is not None:
            return supervisor_result

        raw_result = self.lifecycle_service.stop_tunnel(tunnel_name, proc)
        if raw_result.get("ok"):
            try:
                self.proc_tracker.unregister(tunnel_name, expected_pid=raw_result.get("pid"))
            except Exception:
                pass
        return self.operation_service.build_direct_stop_result(tunnel_name, raw_result)

    def _handle_supervisor_stop_result(self, tunnel_name: str, result: dict) -> bool:
        """处理由 supervisor 接管的停止结果。"""
        if result.get("managed_by") != "supervisor":
            return False

        ok = bool(result.get("ok"))
        if ok:
            self._record_supervisor_command_acceptance(
                tunnel_name,
                result,
                default_message="停止指令已发送",
                feedback_prefix="守护进程已执行停止指令",
                logger_prefix="守护进程停止",
                status_text="停止指令已发送",
            )
            self._refresh_after_supervisor_command(tunnel_name)
            return True

        self._notify_supervisor_result_failure(
            result,
            title="停止失败",
            default_message="守护进程拒绝操作",
            log_message="守护进程停止失败: {message}",
        )
        return True

    def _finish_stop_running(self, tunnel_name: str, result: dict):
        """在主线程完成手动停止后的 UI 收尾。"""
        self._manual_operation = False
        try:
            if self._handle_supervisor_stop_result(tunnel_name, result):
                return

            if not result.get("ok"):
                err = result.get("error") or result.get("message") or "停止失败"
                self._notify_feedback("停止失败", err, tag="error")
                return

            self._clear_tunnel_runtime_state(tunnel_name, expected_pid=result.get("pid"))
            self.status_var.set("隧道已停止")
            self._record_feedback(f"隧道 {tunnel_name} 已停止并取消激活", "success")
        finally:
            self._unlock_tunnel_operation()

    def _stop_running(self):
        """停止运行中的隧道（后台执行，避免阻塞UI）"""
        if self._tunnel_operation_in_progress:
            return

        selected = self._require_selected_tunnel(message="请先选择要停止的隧道")
        if not selected:
            return

        tunnel_name = self._selected_tunnel_name(selected)

        if not self._can_control_tunnel(tunnel_name):
            return

        if not self._is_tunnel_running(tunnel_name):
            self._notify_tunnel_not_running(tunnel_name)
            return

        self._begin_tunnel_operation(
            button_text="⏳ 停止中…",
            status_text=f"停止中：{tunnel_name}",
            log_message=f"正在停止隧道 {tunnel_name}...",
            log_tag="warning",
        )

        proc = self.proc_map.get(tunnel_name)

        self._run_async_tunnel_operation(
            lambda: self._stop_tunnel_worker(tunnel_name, proc),
            lambda result: self._finish_stop_running(tunnel_name, result),
            lambda exc: self.operation_service.build_stop_exception_result(tunnel_name, exc),
        )

    def _run_tunnel_diagnostics(
        self,
        cloudflared_path: str,
        tunnel_name: str,
        tunnel_id: str | None,
        cfg: Path,
        append_result: Callable[[str, str | None], None],
    ):
        """执行隧道诊断，并按步骤输出结果。"""
        append_result(f"=== 开始测试隧道: {tunnel_name} ===\n\n", "info")
        self.logger.info(f"开始测试隧道: {tunnel_name}")

        report = self.diagnostics_service.build_report(
            cloudflared_path,
            tunnel_name,
            tunnel_id,
            cfg,
            self._is_tunnel_running,
        )
        for line in report:
            append_result(line.text, line.tag)

        self.logger.info(f"隧道测试完成: {tunnel_name}")

    def _test_tunnel(self):
        """测试隧道（内置诊断）"""
        path = self._require_cloudflared_path(title="提示", message="请先设置 cloudflared 路径", level="warning")
        if not path:
            return

        item = self._require_selected_tunnel(level="warning")
        if not item:
            return

        name = self._selected_tunnel_name(item)
        tid = self.runtime_service.extract_tunnel_id(item)
        cfg = self._config_path_for(name)

        dialog = tk.Toplevel(self)
        dialog.title(f"测试隧道 - {name}")
        dialog.geometry("720x520")
        dialog.minsize(640, 420)
        dialog.transient(self)
        dialog.grab_set()

        result_frame = ttk.LabelFrame(dialog, text="测试结果")
        result_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        result_text = tk.Text(
            result_frame,
            wrap=tk.WORD,
            font=(Theme.FONT_MONO, 10),
            bg="#1E1E1E",
            fg="#E0E0E0"
        )
        result_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        scrollbar = ttk.Scrollbar(result_frame, command=result_text.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        result_text.config(yscrollcommand=scrollbar.set)

        for tag, color in {
            "success": "#27AE60",
            "error": "#E74C3C",
            "warning": "#F39C12",
            "info": "#3498DB"
        }.items():
            result_text.tag_config(tag, foreground=color)

        button_frame = ttk.Frame(dialog)
        button_frame.pack(fill=tk.X, padx=10, pady=5)

        def append_result(text: str, tag: str | None = None):
            result_text.insert(tk.END, text)
            if tag:
                start = result_text.index(f"end-{len(text)}c")
                end = result_text.index("end-1c")
                result_text.tag_add(tag, start, end)
            result_text.see(tk.END)
            dialog.update_idletasks()

        def run_tests():
            result_text.delete(1.0, tk.END)
            self._run_tunnel_diagnostics(path, name, tid, cfg, append_result)

        ttk.Button(button_frame, text="开始测试", command=run_tests).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="关闭", command=dialog.destroy).pack(side=tk.RIGHT, padx=5)

        dialog.after(100, run_tests)

    def _prompt_route_dns_hostname(self) -> str | None:
        """提示用户输入要绑定的 DNS 主机名，并做基础校验。"""
        hostname = self._prompt_text("DNS 路由", "输入要绑定的主机名 (例如: app.example.com)")
        if not hostname:
            return None

        normalized = hostname.strip()
        error = self.dns_service.validate_hostname(normalized)
        if error:
            self._show_dialog("主机名无效", error, "error")
            self._append_log(f"DNS 路由输入无效: {error}\n", "error")
            self.logger.error(f"DNS 路由输入无效: {error}")
            return None
        return normalized

    def _handle_route_dns_result(self, tunnel_name: str, hostname: str, ok: bool, output: str):
        """统一处理手动 DNS 路由的结果展示。"""
        if ok:
            self._record_feedback(f"DNS 路由配置成功: {hostname} -> {tunnel_name}", "success")
            self._show_dialog("成功", f"已为 {tunnel_name} 绑定 {hostname}")
            return

        self._record_feedback(f"DNS 路由失败: {output}", "error")
        if "already exists" in output:
            self._show_dialog(
                "DNS记录已存在",
                f"DNS记录 {hostname} 已存在！\n\n"
                "请使用不同的子域名或在Cloudflare控制台删除现有记录。",
                "error",
            )
            return
        self._show_dialog("失败", output, "error")

    def _route_dns_selected(self):
        """配置DNS路由"""
        path = self._require_cloudflared_path()
        if not path:
            return

        item = self._require_selected_tunnel(message="请先选择隧道")
        if not item:
            return

        name = self._selected_tunnel_name(item)
        hostname = self._prompt_route_dns_hostname()
        if not hostname:
            return

        self._append_log(f"正在配置 DNS 路由: {hostname} -> {name}...\n", "info")
        self.logger.info(f"正在配置 DNS 路由: {hostname} -> {name}")
        ok, out = self.dns_service.route_hostname(path, name, hostname)
        self._handle_route_dns_result(name, hostname, ok, out)

    def _open_config_dir(self):
        """打开配置目录"""
        config_dir = get_tunnels_dir()
        config_dir.mkdir(parents=True, exist_ok=True)

        try:
            if self.binary_service.is_windows():
                os.startfile(str(config_dir))
            else:
                import subprocess
                subprocess.Popen(["xdg-open", str(config_dir)])
            self._append_log(f"已打开配置目录: {config_dir}\n", "info")
            self.logger.info(f"已打开配置目录: {config_dir}")
        except Exception:
            self._show_dialog("配置目录", f"配置目录位置:\n{config_dir}")

    def _append_log(self, text: str, tag: str | None = None, *, autoscroll: bool | None = None, trim: bool = True):
        """添加日志"""
        if not hasattr(self, "log"):
            return

        show_timestamp = bool(self.settings.get("log.show_timestamp", True))
        auto_scroll = bool(self.settings.get("log.auto_scroll", True)) if autoscroll is None else bool(autoscroll)

        at_bottom = True
        if auto_scroll:
            try:
                at_bottom = self.log.yview()[1] >= 0.99
            except Exception:
                at_bottom = True

        prefix = f"[{datetime.now().strftime('%H:%M:%S')}] " if show_timestamp else ""
        start = self.log.index(tk.END)
        self.log.insert(tk.END, f"{prefix}{text}")
        end = self.log.index(tk.END)

        if tag:
            self.log.tag_add(tag, start, end)

        if trim:
            self._trim_log_widget()

        if auto_scroll and at_bottom:
            self.log.see(tk.END)

    def _trim_log_widget(self):
        """限制日志窗口行数，防止 Text 组件越来越慢"""
        if not hasattr(self, "log"):
            return
        max_lines = int(self.settings.get("log.max_lines", 1000) or 1000)
        if max_lines <= 0:
            return
        try:
            line_count = int(str(self.log.index("end-1c")).split(".", 1)[0])
        except Exception:
            return

        trim_margin = max(100, max_lines // 10)
        if line_count <= max_lines + trim_margin:
            return

        delete_to = max(1, line_count - max_lines)
        try:
            self.log.delete("1.0", f"{delete_to}.0")
        except Exception:
            pass

    def _clear_log(self):
        """清空日志内容"""
        if not hasattr(self, "log"):
            return
        self.log.delete(1.0, tk.END)
        self.logger.clear()
        self.status_var.set("日志已清空")

    def _copy_log(self):
        """复制日志到剪贴板"""
        if not hasattr(self, "log"):
            return
        text = self.log.get(1.0, tk.END).strip()
        if not text:
            self._show_dialog("复制日志", "暂无日志可复制。")
            return
        self.clipboard_clear()
        self.clipboard_append(text)
        self.status_var.set("日志已复制到剪贴板")

    def _save_log_to_file(self):
        """将日志保存到文件"""
        if not hasattr(self, "log"):
            return
        text = self.log.get(1.0, tk.END).strip()
        if not text:
            self._show_dialog("保存日志", "暂无日志可保存。")
            return
        default_name = f"cloudflared-log-{datetime.now().strftime('%Y%m%d-%H%M%S')}.log"
        file_path = self._choose_save_file("保存日志", ".log", default_name, [("日志文件", "*.log"), ("所有文件", "*.*")])
        if not file_path:
            return
        try:
            Path(file_path).write_text(text + "\n", encoding="utf-8")
            self._show_dialog("保存成功", f"日志已保存到:\n{file_path}")
            self.logger.info(f"日志已保存到: {file_path}")
        except Exception as exc:
            self._show_dialog("保存失败", str(exc), "error")
            self.logger.error(f"日志保存失败: {exc}")

    def _toggle_start_selected(self):
        """切换启动/停止隧道（带防重复点击保护）"""
        # 防止重复点击
        if self._tunnel_operation_in_progress:
            return

        # 获取当前选中的隧道
        selected = self.tunnel_list.get_selected()
        if not selected:
            return

        tunnel_name = selected.get("name")
        if not tunnel_name:
            return

        # 检查该隧道是否在运行
        if self._is_tunnel_running(tunnel_name):
            self._stop_running()
        else:
            self._start_selected()

    def _unlock_tunnel_operation(self):
        """解锁隧道操作"""
        self._tunnel_operation_in_progress = False
        if self.toggle_button:
            try:
                self.toggle_button.configure(state=tk.NORMAL)
            except Exception:
                pass
        self._update_toggle_button_state()

    def _read_proc_output(self):
        """读取进程输出"""
        if not self.proc or not getattr(self.proc, "stdout", None):
            return

        try:
            for line in iter(self.proc.stdout.readline, ''):
                if not line:
                    break
                self.proc_queue.put(line)
        except:
            pass

    def _drain_proc_queue(self):
        """处理进程输出/日志队列（节流，避免 UI 卡顿）"""
        max_items = int(self.settings.get("log.drain_batch", 200) or 200)
        auto_scroll = bool(self.settings.get("log.auto_scroll", True))
        at_bottom = True
        if auto_scroll and hasattr(self, "log"):
            try:
                at_bottom = self.log.yview()[1] >= 0.99
            except Exception:
                at_bottom = True

        processed = 0
        while processed < max_items:
            try:
                item = self.proc_queue.get_nowait()
            except queue.Empty:
                break

            processed += 1

            if isinstance(item, tuple) and item:
                kind = item[0]
                if kind == "logger" and len(item) >= 3:
                    _, message, tag = item[:3]
                    self._append_log(str(message), str(tag) if tag else None, autoscroll=False, trim=False)
                    continue

                item = " ".join(str(x) for x in item)

            line = str(item)
            lower = line.lower()
            if "error" in lower:
                tag = "error"
            elif "success" in lower or "connected" in lower:
                tag = "success"
            elif "warning" in lower:
                tag = "warning"
            else:
                tag = "info"

            self._append_log(line, tag, autoscroll=False, trim=False)

        if processed:
            self._trim_log_widget()
            if auto_scroll and at_bottom and hasattr(self, "log"):
                try:
                    self.log.see(tk.END)
                except Exception:
                    pass

        delay = 50 if not self.proc_queue.empty() else 200
        self.after(delay, self._drain_proc_queue)


# ============= 主入口 =============
def run_modern_app():
    """运行现代化应用"""
    app = None
    try:
        app = ModernTunnelManager()

        # 设置样式
        style = ttk.Style()
        style.theme_use('clam')

        # 自定义ttk组件样式
        style.configure('TButton', borderwidth=0, relief="flat", background=Theme.PRIMARY)
        style.map('TButton',
            background=[('active', Theme.PRIMARY_DARK)],
            foreground=[('active', 'white')]
        )

        app.mainloop()
    except KeyboardInterrupt:
        raise
    except Exception as exc:
        if app is not None:
            app._write_crash_report("GUI Mainloop Exception", type(exc), exc, exc.__traceback__)
        else:
            log_path = get_logs_dir() / "gui_crash.log"
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(log_path, "a", encoding="utf-8") as fh:
                fh.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] GUI Startup Exception\n")
                fh.write("".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
                fh.write("\n")
        raise


if __name__ == "__main__":
    run_modern_app()
