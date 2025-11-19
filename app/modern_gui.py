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
import platform
import urllib.request
import urllib.error
import os
import json
import shutil
from datetime import datetime

# ============= 导入模块 =============
# 支持包模式和脚本模式运行
try:
    # 包模式导入
    from . import cloudflared_cli as cf
    from .utils.theme import Theme
    from .components.widgets import ModernButton, IconButton, Card, Badge, StatusIndicator, SearchBox
    from .config.settings import Settings
    from .utils.logger import LogManager, LogLevel
except (ImportError, ValueError):
    # 脚本模式导入
    import sys
    sys.path.append(os.path.dirname(__file__))
    import cloudflared_cli as cf
    from utils.theme import Theme
    from components.widgets import ModernButton, IconButton, Card, Badge, StatusIndicator, SearchBox
    from config.settings import Settings
    from utils.logger import LogManager, LogLevel


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
        self.selected_index = None
        self.empty_state = None

        # 标题栏
        header = tk.Frame(self, bg=Theme.PRIMARY, height=40)
        header.pack(fill=tk.X)
        header.pack_propagate(False)

        tk.Label(
            header,
            text="🚇 隧道列表",
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

    def update_tunnel_status(self, tunnel_name: str, is_active: bool):
        """更新特定隧道的状态显示"""
        for item_data in self.items:
            if item_data["data"].get("name") == tunnel_name:
                # 更新状态条颜色
                status_bar = item_data.get("status_bar")
                if status_bar:
                    status_bar.configure(bg=Theme.SUCCESS if is_active else Theme.BORDER)

                # 更新徽章
                badge_label = item_data.get("badge_label")
                if badge_label:
                    if is_active:
                        badge_label.configure(
                            text="● 已激活",
                            bg=Theme.SUCCESS_BG,
                            fg=Theme.SUCCESS
                        )
                    else:
                        badge_label.configure(
                            text="○ 未激活",
                            bg=Theme.BG_HOVER,
                            fg=Theme.TEXT_MUTED
                        )
                break

    def refresh_all_status(self):
        """刷新所有隧道的状态"""
        parent_window = self.winfo_toplevel()
        if hasattr(parent_window, 'running_tunnels'):
            running_tunnels = parent_window.running_tunnels
            for item_data in self.items:
                tunnel_name = item_data["data"].get("name")
                is_active = tunnel_name in running_tunnels
                self.update_tunnel_status(tunnel_name, is_active)

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
            text="🕳️",
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
        self.items.append({
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
        })

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

        self.title("🚇 Cloudflare Tunnel Manager")

        # 初始化配置管理器
        self.settings = Settings()

        # 初始化日志管理器
        self.logger = LogManager(
            max_lines=self.settings.get("log.max_lines", 1000),
            save_to_file=True
        )

        # 从配置恢复窗口大小和位置
        self._restore_window_geometry()

        # 设置窗口图标和样式
        self.configure(bg=Theme.BG_MAIN)

        # 初始化变量
        self.cloudflared_path = tk.StringVar(
            value=self.settings.get("cloudflared.path") or cf.find_cloudflared() or ""
        )
        self.status_var = tk.StringVar(value="就绪")
        self.search_var = tk.StringVar()
        self.proc = None
        self.proc_thread = None
        self.proc_queue = queue.Queue()
        self._tunnels = []
        self.running_tunnels = {}  # 存储系统中运行的隧道信息
        self._manual_operation = False  # 标记手动操作状态
        self._last_status_state = None  # 记录上次状态，避免闪烁
        self.toggle_button = None
        self.toggle_button_var = tk.StringVar(value="▶ 启动")
        self._search_clear_btn = None
        self._search_entry = None
        self.persist_var = tk.BooleanVar(value=self.settings.get("tunnel.persist_on_exit", False))
        self.autostart_var = tk.BooleanVar(value=self.settings.get("tunnel.auto_start_enabled", False))
        self.autostart_hint_var = tk.StringVar()
        self._auto_start_done = False
        self._refresh_autostart_hint()

        # 绑定窗口关闭事件
        self.protocol("WM_DELETE_WINDOW", self._on_closing)

        # 创建UI
        self._build_modern_ui()

        # 初始化
        self.after(100, self._init_app)
        self.after(200, self._drain_proc_queue)

        # 日志回调
        self.logger.add_callback(self._on_log_message)

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
        # 保存窗口几何配置
        self._save_window_geometry()

        # 保存cloudflared路径
        self.settings.set("cloudflared.path", self.cloudflared_path.get())

        # 停止运行的进程（如未启用持久化）
        keep_running = bool(self.persist_var.get())
        if self.proc and self.proc.poll() is None:
            if keep_running:
                self._append_log("保持隧道运行：已启用持久化，退出时不终止 cloudflared。\n", "info")
                self.logger.info("退出时保留隧道运行")
            else:
                try:
                    cf.stop_process(self.proc)
                except Exception:
                    pass

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

        # 在主线程中更新UI
        self.after(0, lambda: self._append_log(message + "\n", tag))

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

        # 版本信息（简洁显示）
        self.version_label = tk.Label(
            toolbar,
            text="",
            bg=Theme.BG_TOOLBAR,
            fg=Theme.TEXT_MUTED,
            font=(Theme.FONT_FAMILY, 9)
        )
        self.version_label.pack(side=tk.RIGHT, padx=(15, 0))

        # 工具按钮组（更紧凑的设计）
        tool_buttons = tk.Frame(toolbar, bg=Theme.BG_TOOLBAR)
        tool_buttons.pack(side=tk.RIGHT)

        self._create_icon_button(tool_buttons, "🔑", self._login, "登录认证")
        self._create_icon_button(tool_buttons, "⬇", self._download_cloudflared, "下载工具")
        self._create_icon_button(tool_buttons, "📁", self._choose_cloudflared, "选择文件")

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

        # 快捷操作按钮
        quick_actions = tk.Frame(list_header, bg=Theme.BG_MAIN)
        quick_actions.pack(side=tk.RIGHT)

        self._create_compact_button(quick_actions, "🔄", self.refresh_tunnels, Theme.INFO, "刷新")
        self._create_compact_button(quick_actions, "➕", self._create_tunnel, Theme.SUCCESS, "新建")
        self._create_compact_button(quick_actions, "🗑", self._delete_selected, Theme.ERROR, "删除")

        # 搜索输入框
        search_wrapper = tk.Frame(list_header, bg=Theme.BG_MAIN)
        search_wrapper.pack(side=tk.RIGHT, padx=(0, 10))

        search_box = tk.Frame(
            search_wrapper,
            bg=Theme.BG_CARD,
            highlightbackground=Theme.BORDER,
            highlightthickness=1
        )
        search_box.pack(fill=tk.X)

        tk.Label(
            search_box,
            text="🔍",
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

        # 控制卡片
        control_section = tk.Frame(right_panel, bg=Theme.BG_MAIN)
        control_section.pack(fill=tk.X, pady=(0, 15))

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
        secondary_actions = tk.Frame(control_section, bg=Theme.BG_MAIN)
        secondary_actions.pack(fill=tk.X, pady=(12, 0))

        # 使用更现代的图标按钮
        self._create_outline_button(secondary_actions, "🌐 DNS路由", self._route_dns_selected)
        self._create_outline_button(secondary_actions, "✏ 编辑配置", self._edit_selected_config)
        self._create_outline_button(secondary_actions, "🧪 诊断测试", self._test_tunnel)

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
            text="关闭应用后保持隧道运行",
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
            text="启动应用时自动激活上次隧道",
            variable=self.autostart_var,
            command=self._on_autostart_toggle,
            bg=Theme.BG_CARD,
            fg=Theme.TEXT_PRIMARY,
            selectcolor=Theme.BG_CARD,
            activebackground=Theme.BG_CARD,
            anchor="w"
        )
        autostart_cb.pack(fill=tk.X, pady=(2, 2))

        tk.Label(
            options_card,
            textvariable=self.autostart_hint_var,
            bg=Theme.BG_CARD,
            fg=Theme.TEXT_MUTED,
            font=(Theme.FONT_FAMILY, 9),
            wraplength=360,
            justify=tk.LEFT
        ).pack(fill=tk.X, pady=(4, 0))

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
        enabled = bool(self.autostart_var.get())
        self.settings.set("tunnel.auto_start_enabled", enabled)
        trigger_now = False
        if enabled:
            selected = self.tunnel_list.get_selected() if hasattr(self, "tunnel_list") else None
            target = (selected.get("name") if selected else None) or self.settings.get("tunnel.last_selected")
            if target:
                self._set_autostart_target(target)
                self._append_log(f"自动启动已启用，将尝试激活隧道: {target}\n", "info")
                self.logger.info(f"启用自动启动: {target}")
                trigger_now = True
            else:
                self._append_log("自动启动已启用，但尚未指定隧道，请先选择一个隧道。\n", "warning")
                self.logger.warning("自动启动缺少目标")
                messagebox.showinfo("自动启动", "请先选择准备自动启动的隧道，然后再次启用该选项。")
                self.autostart_var.set(False)
                self.settings.set("tunnel.auto_start_enabled", False)
                enabled = False
        else:
            self._append_log("已关闭自动启动选项。\n", "info")
            self.logger.info("关闭自动启动")
            self._auto_start_done = True
        self._refresh_autostart_hint()
        if enabled and trigger_now:
            self._auto_start_done = False
            self._auto_start_if_enabled(force=True)

    def _restore_selection_if_needed(self):
        """恢复上次选择的隧道"""
        if not hasattr(self, "tunnel_list"):
            return
        if self.tunnel_list.get_selected():
            return
        preferred = self.settings.get("tunnel.last_selected")
        if preferred:
            self.tunnel_list.select_by_name(preferred)

        # 配置日志颜色
        self.log.tag_config("info", foreground=Theme.INFO)
        self.log.tag_config("success", foreground=Theme.SUCCESS)
        self.log.tag_config("warning", foreground=Theme.WARNING)
        self.log.tag_config("error", foreground=Theme.ERROR)

        # ========== 底部状态栏 ==========
        statusbar = tk.Frame(self, bg=Theme.BG_TOOLBAR, height=35)
        statusbar.pack(fill=tk.X)
        statusbar.pack_propagate(False)

        # 状态文本
        status_container = tk.Frame(statusbar, bg=Theme.BG_TOOLBAR)
        status_container.pack(side=tk.LEFT, fill=tk.Y, padx=20)

        tk.Label(
            status_container,
            textvariable=self.status_var,
            bg=Theme.BG_TOOLBAR,
            fg=Theme.TEXT_LIGHT,
            font=(Theme.FONT_FAMILY, 9)
        ).pack(side=tk.LEFT)

        # Cloudflared路径指示（简洁版）
        path_indicator = tk.Frame(statusbar, bg=Theme.BG_TOOLBAR)
        path_indicator.pack(side=tk.RIGHT, padx=20)

        tk.Label(
            path_indicator,
            text="📍",
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

        title_text = f"{icon} {title}" if icon else title
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
            text=icon,
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
            text=icon,
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
            text=text,
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

        running = self.proc is not None and self.proc.poll() is None

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

    def _refresh_proc_state(self):
        """检查子进程状态并同步UI"""
        # 首先检查self.proc（如果是GUI启动的）
        if self.proc and self.proc.poll() is not None:
            self._append_log("隧道进程已退出\n", "warning")
            self.logger.warning("隧道进程已退出")
            self.proc = None
            self.proc_thread = None
            self.status_var.set("隧道已停止")

        # 检查系统中运行的隧道
        running_tunnels = cf.get_running_tunnels()
        old_running = set(self.running_tunnels.keys())
        new_running = {t["name"] for t in running_tunnels}

        # 如果运行状态有变化，刷新列表状态
        if old_running != new_running:
            self.running_tunnels = {t["name"]: t for t in running_tunnels}
            # 刷新左侧列表的状态显示
            if hasattr(self, "tunnel_list"):
                self.tunnel_list.refresh_all_status()
        else:
            self.running_tunnels = {t["name"]: t for t in running_tunnels}

        # 如果GUI启动的隧道正在运行，确保它在running_tunnels中
        if self.proc and self.proc.poll() is None:
            selected = self.tunnel_list.get_selected()
            if selected:
                tunnel_name = selected.get("name")
                if tunnel_name and tunnel_name not in self.running_tunnels:
                    # 添加GUI启动的隧道到running_tunnels
                    self.running_tunnels[tunnel_name] = {
                        "name": tunnel_name,
                        "pid": self.proc.pid
                    }
                    # 刷新列表状态
                    if hasattr(self, "tunnel_list"):
                        self.tunnel_list.refresh_all_status()

        # 只在非手动操作时更新UI（避免闪烁）
        if not self._manual_operation:
            self._update_status_display()
            self._update_toggle_button_state()

    def _is_tunnel_running(self, tunnel_name: str = None) -> bool:
        """检查隧道是否在运行（包括外部启动的）"""
        # 如果没有指定名称，检查是否有任何隧道在运行
        if tunnel_name is None:
            # 首先检查self.proc
            if self.proc and self.proc.poll() is None:
                return True
            # 然后检查系统中的隧道
            return len(getattr(self, 'running_tunnels', {})) > 0

        # 检查特定隧道
        # 首先检查是否是当前GUI管理的隧道
        if self.proc and self.proc.poll() is None:
            # 需要从当前选中的隧道获取名称来比较
            selected = self.tunnel_list.get_selected()
            if selected and selected.get("name") == tunnel_name:
                return True

        # 检查系统中的隧道
        return tunnel_name in getattr(self, 'running_tunnels', {})

    def _get_running_tunnel_info(self, tunnel_name: str) -> dict | None:
        """获取运行中隧道的信息"""
        return getattr(self, 'running_tunnels', {}).get(tunnel_name)

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

    def _init_app(self):
        """初始化应用"""
        self.logger.info("应用程序启动")
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
        if self._auto_start_done and not force:
            return

        enabled = self.settings.get("tunnel.auto_start_enabled", False)
        if not enabled:
            self._auto_start_done = True
            return

        target = self.settings.get("tunnel.autostart_tunnel") or self.settings.get("tunnel.last_selected")
        if not target:
            self._append_log("自动启动已启用，但未找到可用的隧道记录。\n", "warning")
            self.logger.warning("自动启动缺少目标")
            self._auto_start_done = True
            return

        if self._is_tunnel_running(target):
            self._append_log(f"自动启动: 隧道 {target} 已在运行。\n", "info")
            self.logger.info(f"自动启动跳过，{target} 已运行")
            self._auto_start_done = True
            return

        if hasattr(self, "tunnel_list"):
            if not self.tunnel_list.select_by_name(target):
                self._append_log(f"自动启动失败：未找到隧道 {target}\n", "error")
                self.logger.error(f"自动启动失败，未找到 {target}")
                self._auto_start_done = True
                return
        else:
            self._auto_start_done = True
            return

        self._append_log(f"开机自动激活隧道: {target}\n", "info")
        self.logger.info(f"开始自动激活隧道: {target}")
        self._start_selected()
        self._auto_start_done = True

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
        cf_installed = bool(self.cloudflared_path.get())
        selected = self.tunnel_list.get_selected()
        current_tunnel_name = selected.get("name") if selected else None
        is_activated = self._is_tunnel_running(current_tunnel_name) if current_tunnel_name else False

        # 获取运行的隧道信息
        running_info = ""
        if is_activated and current_tunnel_name:
            tunnel_info = self._get_running_tunnel_info(current_tunnel_name)
            if tunnel_info:
                running_info = f" (PID: {tunnel_info['pid']})"

        # 如果状态没有变化，不重新创建widgets（避免闪烁）
        if hasattr(self, '_last_status_state'):
            last_state = self._last_status_state
            current_state = (cf_installed, current_tunnel_name, is_activated, running_info)
            if last_state == current_state:
                return  # 状态没有变化，不更新

        # 保存当前状态
        self._last_status_state = (cf_installed, current_tunnel_name, is_activated, running_info)

        # 清空状态显示
        for widget in self.status_display.winfo_children():
            widget.destroy()

        # 创建网格布局
        status_grid = tk.Frame(self.status_display, bg=Theme.BG_CARD)
        status_grid.pack(fill=tk.BOTH, expand=True)

        # 第一行
        row1 = tk.Frame(status_grid, bg=Theme.BG_CARD)
        row1.pack(fill=tk.X, pady=8)

        # Cloudflared 状态
        self._add_status_badge(
            row1,
            "Cloudflared",
            "已就绪" if cf_installed else "未安装",
            "success" if cf_installed else "error",
            "✓" if cf_installed else "✗"
        )

        # 隧道激活状态（统一术语）
        self._add_status_badge(
            row1,
            "隧道状态",
            f"已激活{running_info}" if is_activated else "未激活",
            "success" if is_activated else "default",
            "●" if is_activated else "○"
        )

        # 第二行
        row2 = tk.Frame(status_grid, bg=Theme.BG_CARD)
        row2.pack(fill=tk.X, pady=8)

        # 隧道总数
        tunnel_count = len(self._tunnels)
        self._add_status_badge(
            row2,
            "隧道总数",
            f"{tunnel_count} 个",
            "info" if tunnel_count > 0 else "default",
            "📊"
        )

        # 当前选中隧道
        selected = self.tunnel_list.get_selected()
        selected_name = selected.get("name", "未选择") if selected else "未选择"
        self._add_status_badge(
            row2,
            "当前选中",
            selected_name,
            "info" if selected else "default",
            "📍"
        )

    def _add_status_badge(self, parent, label, value, status="default", icon=""):
        """添加状态徽章"""
        container = tk.Frame(parent, bg=Theme.BG_CARD)
        container.pack(side=tk.LEFT, padx=8)

        # 确定颜色方案
        if status == "success":
            bg_color = Theme.SUCCESS_BG
            fg_color = Theme.SUCCESS
        elif status == "error":
            bg_color = Theme.ERROR_BG
            fg_color = Theme.ERROR
        elif status == "warning":
            bg_color = Theme.WARNING_BG
            fg_color = Theme.WARNING
        elif status == "info":
            bg_color = Theme.INFO_BG
            fg_color = Theme.INFO
        else:
            bg_color = Theme.BG_HOVER
            fg_color = Theme.TEXT_SECONDARY

        # 徽章容器
        badge = tk.Frame(
            container,
            bg=bg_color,
            highlightthickness=0
        )
        badge.pack(fill=tk.BOTH, padx=2, pady=2)

        # 内容
        content = tk.Frame(badge, bg=bg_color)
        content.pack(padx=12, pady=8)

        # 图标和标签
        if icon:
            tk.Label(
                content,
                text=icon,
                bg=bg_color,
                fg=fg_color,
                font=(Theme.FONT_FAMILY, 11)
            ).pack(side=tk.LEFT, padx=(0, 6))

        label_frame = tk.Frame(content, bg=bg_color)
        label_frame.pack(side=tk.LEFT)

        tk.Label(
            label_frame,
            text=label,
            bg=bg_color,
            fg=Theme.TEXT_MUTED,
            font=(Theme.FONT_FAMILY, 8)
        ).pack(anchor="w")

        tk.Label(
            label_frame,
            text=value,
            bg=bg_color,
            fg=fg_color,
            font=(Theme.FONT_FAMILY, 10, "bold")
        ).pack(anchor="w")

    def _cert_status_summary(self) -> tuple[bool, str, str]:
        """返回证书的状态标签和详细描述"""
        exists, cert_path, updated = cf.origin_cert_status(None)
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

    # ========== 功能方法 ==========

    def _choose_cloudflared(self):
        """选择 cloudflared 可执行文件"""
        path = filedialog.askopenfilename(
            title="选择 cloudflared 可执行文件",
            filetypes=[("可执行文件", "*.exe"), ("所有文件", "*.*")] if cf._is_windows() else [("所有文件", "*")]
        )
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
        if cf._is_windows():
            title = "检查更新" if mode == "update" else "下载"
            messagebox.showinfo(title, "该功能仅适用于 Linux/macOS 环境。")
            return

        target = Path.cwd() / "cloudflared"
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
            ok, msg, version = cf.download_cloudflared_linux(target, progress_cb=progress)

            def _finish():
                cert_ok, _, cert_detail = self._cert_status_summary()
                cert_append = f"\n\n证书状态：\n{cert_detail}"
                extra = f"\n版本: {version}" if version else ""
                if ok:
                    self.cloudflared_path.set(str(target))
                    self.settings.set("cloudflared.path", str(target))
                    self._refresh_version()
                    self._append_log(f"{msg}{extra}\n", "success")
                    self.logger.info(f"{msg}{extra}")
                    dialog = messagebox.showinfo if cert_ok else messagebox.showwarning
                    title = success_label if cert_ok else f"{success_label}（需登录）"
                    dialog(title, msg + extra + cert_append)
                    tag = "success" if cert_ok else "warning"
                    self._append_log(cert_detail + "\n", tag)
                    self.status_var.set(success_label if cert_ok else "缺少认证")
                else:
                    self._append_log(f"{msg}\n", "error")
                    self.logger.error(msg)
                    messagebox.showerror(f"{fail_label}", msg + cert_append)
                    tag = "success" if cert_ok else "warning"
                    self._append_log(cert_detail + "\n", tag)
                    self.status_var.set(fail_label)

                self._update_status_display()
            self.after(0, _finish)

        threading.Thread(target=_worker, daemon=True).start()

    def _login(self):
        """登录 Cloudflare"""
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
                    self._append_log("已删除旧认证文件\n", "info")
                    self.logger.info("已删除旧认证文件")
                except Exception as e:
                    messagebox.showerror("错误", f"无法删除认证文件：{e}")
                    self.logger.error(f"无法删除认证文件: {e}")
                    return
            else:
                self.status_var.set("使用现有认证")
                return

        try:
            proc = cf.login(path)
        except cf.CloudflaredBinaryError as e:
            messagebox.showerror("无法登录", str(e))
            self._append_log(f"登录失败: {e}\n", "error")
            self.logger.error(f"登录失败: {e}")
            return
        self.status_var.set("已启动登录流程，请在浏览器中完成授权…")
        self._append_log("正在打开浏览器进行 Cloudflare 授权...\n", "info")
        self.logger.info("已启动 Cloudflare 登录流程")
        self.after(2000, lambda: self.status_var.set("就绪"))

    def _refresh_version(self):
        """刷新版本信息"""
        path = self.cloudflared_path.get().strip()
        if not path:
            self.version_label.config(text="Cloudflared: 未安装")
            return
        ver = cf.version(path)
        if ver:
            # 简化版本显示
            ver_short = ver.split("(")[0].strip() if "(" in ver else ver
            self.version_label.config(text=f"Cloudflared: {ver_short}")
            self.logger.debug(f"Cloudflared 版本: {ver_short}")
        else:
            self.version_label.config(text="Cloudflared: 版本未知")

    def refresh_tunnels(self):
        """刷新隧道列表"""
        path = self.cloudflared_path.get().strip()
        if not path:
            self.tunnel_list.set_tunnels([], "尚未配置 cloudflared", "点击右上角的按钮设置 cloudflared 可执行文件。")
            self._append_log("未设置 cloudflared 路径\n", "warning")
            self.logger.warning("未设置 cloudflared 路径")
            self.status_var.set("请先设置 cloudflared 路径")
            return

        self.tunnel_list.set_tunnels([], "正在刷新隧道列表…", "cloudflared 正在返回最新的隧道信息。")
        self._append_log("正在刷新隧道列表...\n", "info")
        self.logger.info("开始刷新隧道列表")
        try:
            data = cf.list_tunnels(path)
        except cf.CloudflaredBinaryError as e:
            self._append_log(f"刷新隧道失败: {e}\n", "error")
            self.logger.error(f"刷新隧道失败: {e}")
            messagebox.showerror("cloudflared 不可用", str(e))
            self.status_var.set("cloudflared 不可用")
            self.tunnel_list.set_tunnels([], "加载失败", "请检查 cloudflared 是否可执行，或重新选择可执行文件。")
            return
        self._tunnels = data

        # 同步配置文件
        self._sync_tunnel_configs(data)

        self._apply_tunnel_filter()
        self._append_log(f"已加载 {len(data)} 个隧道\n", "success")
        self.logger.info(f"成功加载 {len(data)} 个隧道")

    def _sync_tunnel_configs(self, tunnels):
        """同步所有隧道的配置文件"""
        for tunnel in tunnels:
            name = tunnel.get("name", "")
            tid = cf.extract_tunnel_id(tunnel)
            if not (name and tid):
                continue

            cfg = self._config_path_for(name)
            if cfg.exists():
                # 验证并更新配置文件
                if not cf.validate_tunnel_config(cfg, tid):
                    self._append_log(f"同步配置文件: {name}\n", "info")
                    if cf.update_config_tunnel_id(cfg, tid):
                        self.logger.info(f"已同步隧道 {name} 的配置文件UUID")
                    else:
                        self.logger.warning(f"同步隧道 {name} 的配置文件失败")

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
        path = self.cloudflared_path.get().strip()
        if not path:
            messagebox.showerror("错误", "请先设置 cloudflared 路径")
            return

        cert = cf.find_origin_cert(None)
        if cert is None:
            messagebox.showerror("缺少认证", '未找到 Cloudflare 认证证书 cert.pem，请先点击"登录"完成授权。')
            self._append_log("未找到 cert.pem，请先运行登录\n", "warning")
            self.logger.warning("未找到认证证书，无法创建隧道")
            return

        name = simpledialog.askstring("新建隧道", "请输入隧道名称:")
        if not name:
            return

        self._append_log(f"正在创建隧道: {name}...\n", "info")
        self.logger.info(f"开始创建隧道: {name}")
        ok, out = cf.create_tunnel(path, name, cert)

        if ok:
            self._append_log(f"隧道 {name} 创建成功\n{out}\n", "success")
            self.logger.info(f"隧道 {name} 创建成功")
            self.refresh_tunnels()
        else:
            self._append_log(f"创建失败: {out}\n", "error")
            self.logger.error(f"创建隧道失败: {out}")
            messagebox.showerror("创建失败", out)

    def _delete_selected(self):
        """删除选中的隧道"""
        path = self.cloudflared_path.get().strip()
        item = self.tunnel_list.get_selected()

        if not (path and item):
            messagebox.showwarning("提示", "请先选择要删除的隧道")
            return

        name = item.get("name", "")
        if not messagebox.askyesno("确认删除", f"确定要删除隧道 '{name}' 吗？\n此操作不可恢复。"):
            return

        self._append_log(f"正在删除隧道: {name}...\n", "warning")
        self.logger.warning(f"开始删除隧道: {name}")
        ok, out = cf.delete_tunnel(path, name)

        if ok:
            # 同时删除配置目录
            config_dir = Path.cwd() / "tunnels" / name
            if config_dir.exists():
                try:
                    shutil.rmtree(config_dir)
                    self._append_log(f"已删除配置目录: {config_dir}\n", "info")
                    self.logger.info(f"已删除配置目录: {config_dir}")
                except Exception as e:
                    self._append_log(f"删除配置目录失败: {e}\n", "warning")
                    self.logger.warning(f"删除配置目录失败: {e}")

            self._append_log(f"隧道 {name} 已删除\n", "success")
            self.logger.info(f"隧道 {name} 已删除")
            self.refresh_tunnels()
        else:
            self._append_log(f"删除失败: {out}\n", "error")
            self.logger.error(f"删除隧道失败: {out}")
            messagebox.showerror("删除失败", out)

    def _config_path_for(self, tunnel_name: str) -> Path:
        """获取隧道配置文件路径"""
        return Path.cwd() / "tunnels" / tunnel_name / "config.yml"

    def _extract_hostnames(self, cfg_path: Path) -> list[str]:
        """读取配置文件中的 hostname 列表"""
        hostnames: list[str] = []
        if not cfg_path.exists():
            return hostnames

        try:
            import yaml
            data = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
            ingress = data.get("ingress", [])
            if isinstance(ingress, list):
                for rule in ingress:
                    hostname = rule.get("hostname")
                    if hostname:
                        host = str(hostname).strip()
                        if host:
                            hostnames.append(host)
            if hostnames:
                return hostnames
        except Exception:
            pass

        try:
            for line in cfg_path.read_text(encoding="utf-8").splitlines():
                if "hostname:" in line:
                    part = line.split("hostname:")[1].strip()
                    if part:
                        hostnames.append(part.split()[0])
        except Exception:
            pass
        return hostnames

    def _ensure_dns_routes(self, cloudflared_path: str, tunnel_name: str, hostnames: list[str]) -> bool:
        """为所有主机名配置DNS路由"""
        if not hostnames:
            messagebox.showerror("缺少DNS路由", "请先在配置文件中设置 ingress.hostname")
            return False

        for hostname in hostnames:
            self._append_log(f"检查 DNS 路由: {hostname} -> {tunnel_name}\n", "info")
            self.logger.info(f"检查 DNS 路由: {hostname} -> {tunnel_name}")
            ok, out = cf.route_dns(cloudflared_path, tunnel_name, hostname)
            if ok:
                self._append_log(f"DNS 路由已配置: {hostname}\n", "success")
                self.logger.info(f"DNS 路由已配置: {hostname}")
            else:
                if "already exists" in out:
                    self._append_log(f"DNS 记录已存在: {hostname}\n", "warning")
                    self.logger.warning(f"DNS 记录已存在: {hostname}")
                    continue
                self._append_log(f"DNS 路由失败: {out}\n", "error")
                self.logger.error(f"DNS 路由失败: {out}")
                messagebox.showerror("DNS 路由失败", f"{hostname} 配置失败：\n{out}")
                return False
        return True

    def _edit_selected_config(self):
        """编辑配置（使用内置编辑器）"""
        item = self.tunnel_list.get_selected()
        if not item:
            messagebox.showinfo("提示", "请先选择一个隧道")
            return

        name = item.get("name", "unknown")
        tid = cf.extract_tunnel_id(item)

        if not tid:
            messagebox.showerror("错误", "无法获取隧道ID")
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
        """启动选中的隧道"""
        self._refresh_proc_state()

        path = self.cloudflared_path.get().strip()
        item = self.tunnel_list.get_selected()

        if not (path and item):
            messagebox.showwarning("提示", "请先选择要启动的隧道")
            return

        name = item.get("name", "unknown")

        # 检查是否已有同名隧道在运行
        if self._is_tunnel_running(name):
            existing_info = self._get_running_tunnel_info(name)
            if existing_info:
                pid_info = f" (PID: {existing_info['pid']})"
            else:
                pid_info = ""
            messagebox.showinfo("提示", f"隧道 {name} 已在运行中{pid_info}")
            self._append_log(f"隧道 {name} 已在运行中{pid_info}\n", "warning")
            self.logger.warning(f"隧道 {name} 已在运行中")
            return

        cfg = self._config_path_for(name)
        tid = cf.extract_tunnel_id(item)

        if not tid:
            self._append_log("无法获取隧道ID\n", "error")
            self.logger.error("无法获取隧道ID")
            return

        # 检查配置文件是否存在
        if cfg.exists():
            # 验证配置文件中的UUID是否匹配
            if not cf.validate_tunnel_config(cfg, tid):
                self._append_log(f"检测到配置文件UUID不匹配，正在更新...\n", "warning")
                self.logger.warning(f"配置文件UUID不匹配，尝试更新")

                # 更新配置文件中的UUID
                if cf.update_config_tunnel_id(cfg, tid):
                    self._append_log(f"配置文件UUID已更新为: {tid}\n", "success")
                    self.logger.info(f"配置文件UUID已更新为: {tid}")
                else:
                    # 如果更新失败，重新生成配置文件
                    self._append_log(f"更新配置文件失败，重新生成配置文件...\n", "warning")
                    cf.write_basic_config(cfg, name, tid)
                    self._append_log(f"已重新生成配置文件\n", "success")
                    self.logger.info("已重新生成配置文件")
        else:
            # 配置文件不存在，生成新的配置文件
            cf.write_basic_config(cfg, name, tid)
            self._append_log(f"已生成默认配置文件\n", "info")
            self.logger.info("已生成默认配置文件")

        normalized, changes = cf.normalize_local_service_protocols(cfg)
        if normalized:
            self._append_log("检测到本地服务协议与配置不一致，已自动修正:\n", "warning")
            self.logger.warning("检测到本地服务协议与配置不一致，已尝试修正")
            for detail in changes:
                self._append_log(f"  · {detail}\n", "warning")
                self.logger.warning(detail)

        hostnames = self._extract_hostnames(cfg)
        if not hostnames:
            self._append_log("启动失败：配置缺少 hostname，请先进行 DNS 路由设置\n", "error")
            self.logger.error("启动失败：配置缺少 hostname")
            messagebox.showerror("缺少 DNS 路由", '请在配置文件的 ingress 中设置 hostname，并通过"DNS 路由"按钮绑定域名。')
            return

        if not self._ensure_dns_routes(path, name, hostnames):
            return

        self._append_log(f"正在启动隧道: {name}...\n", "info")
        self.logger.info(f"开始启动隧道: {name}")

        try:
            persist_enabled = bool(self.persist_var.get())
            capture_output = not persist_enabled
            log_file = None
            if persist_enabled:
                log_dir = Path.cwd() / "logs" / "persistent"
                log_dir.mkdir(parents=True, exist_ok=True)
                log_file = log_dir / f"{name}.log"

            self.proc = cf.run_tunnel(path, name, cfg, capture_output=capture_output, log_file=log_file)
            self.status_var.set(f"隧道 {name} 已激活")
            self._append_log(f"隧道 {name} 已启动并激活\n", "success")
            self.logger.info(f"隧道 {name} 已成功启动并激活")

            # 将隧道添加到激活列表
            self.running_tunnels[name] = {
                "name": name,
                "pid": self.proc.pid
            }

            if self.settings.get("tunnel.save_last_selected", True):
                self.settings.set("tunnel.last_selected", name)
            if self.autostart_var.get():
                self._set_autostart_target(name)

            # 启动日志读取线程（仅在捕获输出时）
            if capture_output:
                self.proc_thread = threading.Thread(target=self._read_proc_output, daemon=True)
                self.proc_thread.start()
            else:
                self.proc_thread = None
                if log_file:
                    self._append_log(f"持久化模式：cloudflared 输出写入 {log_file}\n", "info")
                    self.logger.info(f"持久化日志写入 {log_file}")

            # 立即同步激活状态（无闪烁）
            self._last_status_state = None  # 强制下次更新
            self._immediate_status_sync()
        except Exception as e:
            self._append_log(f"启动失败: {e}\n", "error")
            self.logger.error(f"启动隧道失败: {e}")
            messagebox.showerror("启动失败", str(e))
            self.proc = None
            self._update_toggle_button_state()

    def _stop_running(self):
        """停止运行中的隧道"""
        # 获取当前选中的隧道
        selected = self.tunnel_list.get_selected()
        if not selected:
            messagebox.showinfo("提示", "请先选择要停止的隧道")
            return

        tunnel_name = selected.get("name", "unknown")

        # 检查隧道是否在运行
        if not self._is_tunnel_running(tunnel_name):
            messagebox.showinfo("提示", f"隧道 {tunnel_name} 未在运行")
            return

        self._append_log(f"正在停止隧道 {tunnel_name}...\n", "warning")
        self.logger.warning(f"正在停止隧道 {tunnel_name}")

        # 如果是GUI启动的，用原有方法停止
        if self.proc and self.proc.poll() is None:
            cf.stop_process(self.proc)
            self.proc = None
            self.proc_thread = None
        else:
            # 如果是外部启动的，用新方法停止
            ok, msg = cf.kill_tunnel_by_name(tunnel_name)
            if ok:
                self._append_log(f"{msg}\n", "success")
                self.logger.info(msg)
            else:
                self._append_log(f"{msg}\n", "error")
                self.logger.error(msg)
                messagebox.showerror("停止失败", msg)
                return

        self.status_var.set("隧道已停止")
        self._append_log(f"隧道 {tunnel_name} 已停止并取消激活\n", "success")
        self.logger.info(f"隧道 {tunnel_name} 已停止并取消激活")

        # 立即从running_tunnels中移除，确保取消激活状态
        if tunnel_name in self.running_tunnels:
            del self.running_tunnels[tunnel_name]

        # 立即同步取消激活状态（无闪烁）
        self._last_status_state = None  # 强制下次更新
        self._immediate_status_sync()

    def _test_tunnel(self):
        """测试隧道（内置诊断）"""
        path = self.cloudflared_path.get().strip()
        if not path:
            messagebox.showwarning("提示", "请先设置 cloudflared 路径")
            return

        item = self.tunnel_list.get_selected()
        if not item:
            messagebox.showwarning("提示", "请先选择一个隧道")
            return

        name = item.get("name", "unknown")
        tid = cf.extract_tunnel_id(item)
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
            append_result(f"=== 开始测试隧道: {name} ===\n\n", "info")
            self.logger.info(f"开始测试隧道: {name}")

            # 1. 配置验证
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

            # 2. 主机名检查
            append_result("2. 检查 DNS 主机名...\n", "info")
            hostnames = self._extract_hostnames(cfg)
            if hostnames:
                for host in hostnames:
                    append_result(f"   ✓ {host}\n", "success")
            else:
                append_result("   ✗ 未找到 hostname，请在 ingress 中配置\n", "error")

            append_result("\n")

            # 3. 隧道连接测试
            append_result("3. 测试隧道信息获取...\n", "info")
            ok, msg = cf.test_connection(path, name)
            if ok:
                append_result(f"   ✓ {msg}\n", "success")
            else:
                append_result(f"   ✗ {msg}\n", "error")

            append_result("\n")

            # 4. 本地服务测试
            append_result("4. 测试本地服务...\n", "info")
            services_tested = 0
            if cfg.exists():
                try:
                    for line in cfg.read_text(encoding="utf-8").splitlines():
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
                        append_result("   未找到 HTTP 服务配置\n", "warning")
                except Exception as e:
                    append_result(f"   读取配置失败: {e}\n", "error")
            else:
                append_result("   跳过 - 配置文件缺失\n", "warning")

            append_result("\n")

            # 5. 凭证文件检查
            append_result("5. 检查凭证文件...\n", "info")
            if tid:
                cred_path = cf.default_credentials_path(tid)
                if cred_path.exists():
                    append_result(f"   ✓ 凭证存在: {cred_path}\n", "success")
                else:
                    append_result(f"   ✗ 凭证文件不存在: {cred_path}\n", "error")
            else:
                append_result("   ✗ 无法获取隧道ID\n", "error")

            append_result("\n")

            # 6. 运行状态
            append_result("6. 检查运行状态...\n", "info")
            if self.proc and self.proc.poll() is None:
                append_result("   ✓ 隧道正在运行\n", "success")
                if hostnames:
                    append_result("   可用域名:\n", "info")
                    for host in hostnames:
                        append_result(f"     • https://{host}\n", "success")
            else:
                append_result("   ○ 隧道未运行\n", "warning")

            append_result("\n测试完成！\n", "info")
            self.logger.info(f"隧道测试完成: {name}")

        ttk.Button(button_frame, text="开始测试", command=run_tests).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="关闭", command=dialog.destroy).pack(side=tk.RIGHT, padx=5)

        dialog.after(100, run_tests)

    def _route_dns_selected(self):
        """配置DNS路由"""
        path = self.cloudflared_path.get().strip()
        item = self.tunnel_list.get_selected()

        if not (path and item):
            messagebox.showinfo("提示", "请先选择隧道")
            return

        name = item.get("name", "")
        hostname = simpledialog.askstring("DNS 路由", "输入要绑定的主机名 (例如: app.example.com)")

        if not hostname:
            return

        self._append_log(f"正在配置 DNS 路由: {hostname} -> {name}...\n", "info")
        self.logger.info(f"正在配置 DNS 路由: {hostname} -> {name}")
        ok, out = cf.route_dns(path, name, hostname)

        if ok:
            self._append_log(f"DNS 路由配置成功: {hostname} -> {name}\n", "success")
            self.logger.info(f"DNS 路由配置成功: {hostname} -> {name}")
            messagebox.showinfo("成功", f"已为 {name} 绑定 {hostname}")
        else:
            self._append_log(f"DNS 路由失败: {out}\n", "error")
            self.logger.error(f"DNS 路由失败: {out}")
            if "already exists" in out:
                messagebox.showerror("DNS记录已存在",
                    f"DNS记录 {hostname} 已存在！\n\n"
                    "请使用不同的子域名或在Cloudflare控制台删除现有记录。")
            else:
                messagebox.showerror("失败", out)

    def _open_config_dir(self):
        """打开配置目录"""
        config_dir = Path.cwd() / "tunnels"
        config_dir.mkdir(parents=True, exist_ok=True)

        try:
            if cf._is_windows():
                os.startfile(str(config_dir))
            else:
                import subprocess
                subprocess.Popen(["xdg-open", str(config_dir)])
            self._append_log(f"已打开配置目录: {config_dir}\n", "info")
            self.logger.info(f"已打开配置目录: {config_dir}")
        except Exception:
            messagebox.showinfo("配置目录", f"配置目录位置:\n{config_dir}")

    def _append_log(self, text: str, tag: str = None):
        """添加日志"""
        self.log.insert(tk.END, f"[{datetime.now().strftime('%H:%M:%S')}] {text}")

        if tag:
            # 获取最后一行的索引
            last_line = self.log.index("end-2c linestart")
            end = self.log.index("end-1c")
            self.log.tag_add(tag, last_line, end)

        self.log.see(tk.END)

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
            messagebox.showinfo("复制日志", "暂无日志可复制。")
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
            messagebox.showinfo("保存日志", "暂无日志可保存。")
            return
        default_name = f"cloudflared-log-{datetime.now().strftime('%Y%m%d-%H%M%S')}.log"
        file_path = filedialog.asksaveasfilename(
            title="保存日志",
            defaultextension=".log",
            initialfile=default_name,
            filetypes=[("日志文件", "*.log"), ("所有文件", "*.*")]
        )
        if not file_path:
            return
        try:
            Path(file_path).write_text(text + "\n", encoding="utf-8")
            messagebox.showinfo("保存成功", f"日志已保存到:\n{file_path}")
            self.logger.info(f"日志已保存到: {file_path}")
        except Exception as exc:
            messagebox.showerror("保存失败", str(exc))
            self.logger.error(f"日志保存失败: {exc}")

    def _toggle_start_selected(self):
        """双击列表切换启动/停止"""
        try:
            self._refresh_proc_state()

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
        except Exception:
            pass

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
        """处理进程输出队列"""
        drained = False
        while not self.proc_queue.empty():
            try:
                line = self.proc_queue.get_nowait()
                # 根据内容判断日志类型
                if "error" in line.lower():
                    tag = "error"
                elif "success" in line.lower() or "connected" in line.lower():
                    tag = "success"
                elif "warning" in line.lower():
                    tag = "warning"
                else:
                    tag = "info"

                self._append_log(line, tag)
                drained = True
            except queue.Empty:
                break

        if drained:
            self.log.see(tk.END)

        self.after(200, self._drain_proc_queue)


# ============= 主入口 =============
def run_modern_app():
    """运行现代化应用"""
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


if __name__ == "__main__":
    run_modern_app()
