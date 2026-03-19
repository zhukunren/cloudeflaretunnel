#! -*- coding: utf-8 -*-
"""
现代化UI组件库
"""
import tkinter as tk
from tkinter import ttk
from typing import Callable, Optional

try:
    from ..utils.theme import Theme
except:
    import sys
    import os
    sys.path.append(os.path.dirname(__file__))
    from utils.theme import Theme


class ModernButton(tk.Button):
    """现代化按钮组件"""

    def __init__(self, parent, text="", command=None, style_type="primary", icon="", **kwargs):
        self.style_type = style_type
        self.icon = icon

        # 组合图标和文字
        display_text = Theme.ui_text(f"{icon} {text}" if icon else text)

        # 根据样式类型设置颜色
        colors = self._get_colors(style_type)

        super().__init__(
            parent,
            text=display_text,
            command=command,
            bg=colors["bg"],
            fg=colors["fg"],
            activebackground=colors["hover"],
            activeforeground=colors["fg"],
            font=(Theme.FONT_FAMILY, Theme.FONT_SIZE_BASE),
            bd=0,
            relief=tk.FLAT,
            padx=Theme.PADDING_MD,
            pady=Theme.PADDING_SM,
            cursor="hand2",
            **kwargs
        )

        # 保存颜色配置
        self._colors = colors

        # 绑定悬停效果
        self.bind("<Enter>", self._on_hover)
        self.bind("<Leave>", self._on_leave)

    def _get_colors(self, style_type: str) -> dict:
        """获取按钮颜色配置"""
        color_schemes = {
            "primary": {
                "bg": Theme.PRIMARY,
                "fg": Theme.TEXT_LIGHT,
                "hover": Theme.PRIMARY_DARK
            },
            "success": {
                "bg": Theme.SUCCESS,
                "fg": Theme.TEXT_LIGHT,
                "hover": Theme.SUCCESS_HOVER
            },
            "warning": {
                "bg": Theme.WARNING,
                "fg": Theme.TEXT_LIGHT,
                "hover": Theme.WARNING_HOVER
            },
            "danger": {
                "bg": Theme.ERROR,
                "fg": Theme.TEXT_LIGHT,
                "hover": Theme.ERROR_HOVER
            },
            "info": {
                "bg": Theme.INFO,
                "fg": Theme.TEXT_LIGHT,
                "hover": Theme.INFO_HOVER
            },
            "outline": {
                "bg": Theme.BG_CARD,
                "fg": Theme.PRIMARY,
                "hover": Theme.BTN_HOVER
            }
        }
        return color_schemes.get(style_type, color_schemes["primary"])

    def _on_hover(self, event):
        """鼠标悬停效果"""
        self.configure(bg=self._colors["hover"])

    def _on_leave(self, event):
        """鼠标离开效果"""
        self.configure(bg=self._colors["bg"])


class IconButton(tk.Button):
    """图标按钮（仅图标）"""

    def __init__(self, parent, icon: str, command=None, tooltip="", size=32, **kwargs):
        super().__init__(
            parent,
            text=Theme.ui_text(icon),
            command=command,
            bg=kwargs.pop("bg", Theme.BG_TOOLBAR),
            fg=kwargs.pop("fg", Theme.TEXT_LIGHT),
            font=(Theme.FONT_FAMILY, Theme.FONT_SIZE_LG),
            bd=0,
            relief=tk.FLAT,
            width=2,
            height=1,
            cursor="hand2",
            **kwargs
        )

        self.default_bg = self.cget("bg")
        self.hover_bg = kwargs.pop("hover_bg", Theme.PRIMARY)

        # 绑定悬停效果
        self.bind("<Enter>", lambda e: self.configure(bg=self.hover_bg))
        self.bind("<Leave>", lambda e: self.configure(bg=self.default_bg))

        # TODO: 添加tooltip支持
        self.tooltip = tooltip


class Card(tk.Frame):
    """卡片容器组件"""

    def __init__(self, parent, title="", icon="", **kwargs):
        super().__init__(
            parent,
            bg=Theme.BG_CARD,
            relief=tk.FLAT,
            bd=0,
            highlightbackground=Theme.BORDER,
            highlightthickness=1,
            **kwargs
        )

        # 标题栏
        if title:
            self.header = tk.Frame(self, bg=Theme.BG_CARD, height=45)
            self.header.pack(fill=tk.X)
            self.header.pack_propagate(False)

            title_text = Theme.ui_text(f"{icon} {title}" if icon else title)
            tk.Label(
                self.header,
                text=title_text,
                bg=Theme.BG_CARD,
                fg=Theme.TEXT_PRIMARY,
                font=(Theme.FONT_FAMILY, Theme.FONT_SIZE_MD, "bold"),
                padx=Theme.PADDING_MD
            ).pack(side=tk.LEFT, fill=tk.Y)

            # ���割线
            tk.Frame(self, bg=Theme.DIVIDER, height=1).pack(fill=tk.X)

        # 内容区
        self.content = tk.Frame(self, bg=Theme.BG_CARD)
        self.content.pack(fill=tk.BOTH, expand=True, padx=Theme.PADDING_MD, pady=Theme.PADDING_MD)


class Badge(tk.Label):
    """徽章组件"""

    def __init__(self, parent, text="", status="default", icon="", **kwargs):
        # 确定颜色方案
        color_schemes = {
            "success": (Theme.SUCCESS_BG, Theme.SUCCESS),
            "warning": (Theme.WARNING_BG, Theme.WARNING),
            "error": (Theme.ERROR_BG, Theme.ERROR),
            "info": (Theme.INFO_BG, Theme.INFO),
            "default": (Theme.BG_HOVER, Theme.TEXT_SECONDARY)
        }

        bg_color, fg_color = color_schemes.get(status, color_schemes["default"])
        display_text = Theme.ui_text(f"{icon} {text}" if icon else text)

        super().__init__(
            parent,
            text=display_text,
            bg=bg_color,
            fg=fg_color,
            font=(Theme.FONT_FAMILY, Theme.FONT_SIZE_SM, "bold"),
            padx=Theme.PADDING_SM,
            pady=Theme.PADDING_XS,
            **kwargs
        )


class StatusIndicator(tk.Frame):
    """状态指示器"""

    def __init__(self, parent, label="", value="", status="default", icon=""):
        super().__init__(parent, bg=Theme.BG_CARD)

        # 确定颜色
        color_schemes = {
            "success": (Theme.SUCCESS_BG, Theme.SUCCESS),
            "warning": (Theme.WARNING_BG, Theme.WARNING),
            "error": (Theme.ERROR_BG, Theme.ERROR),
            "info": (Theme.INFO_BG, Theme.INFO),
            "default": (Theme.BG_HOVER, Theme.TEXT_SECONDARY)
        }

        bg_color, fg_color = color_schemes.get(status, color_schemes["default"])

        # 容器
        container = tk.Frame(self, bg=bg_color)
        container.pack(fill=tk.BOTH, padx=2, pady=2)

        content = tk.Frame(container, bg=bg_color)
        content.pack(padx=Theme.PADDING_BASE, pady=Theme.PADDING_SM)

        # 图标
        if icon:
            tk.Label(
                content,
                text=Theme.ui_text(icon),
                bg=bg_color,
                fg=fg_color,
                font=(Theme.FONT_FAMILY, Theme.FONT_SIZE_BASE)
            ).pack(side=tk.LEFT, padx=(0, 6))

        # 标签和值
        label_frame = tk.Frame(content, bg=bg_color)
        label_frame.pack(side=tk.LEFT)

        tk.Label(
            label_frame,
            text=label,
            bg=bg_color,
            fg=Theme.TEXT_MUTED,
            font=(Theme.FONT_FAMILY, Theme.FONT_SIZE_XS)
        ).pack(anchor="w")

        self.value_label = tk.Label(
            label_frame,
            text=value,
            bg=bg_color,
            fg=fg_color,
            font=(Theme.FONT_FAMILY, Theme.FONT_SIZE_BASE, "bold")
        )
        self.value_label.pack(anchor="w")

    def set_value(self, value: str):
        """更新值"""
        self.value_label.configure(text=value)


class SearchBox(tk.Frame):
    """搜索框组件"""

    def __init__(self, parent, placeholder="搜索...", on_change: Optional[Callable] = None):
        super().__init__(
            parent,
            bg=Theme.BG_CARD,
            highlightbackground=Theme.BORDER,
            highlightthickness=1
        )

        # 搜索图标
        tk.Label(
            self,
            text=Theme.ui_text("🔍"),
            bg=Theme.BG_CARD,
            fg=Theme.TEXT_MUTED,
            font=(Theme.FONT_FAMILY, Theme.FONT_SIZE_BASE)
        ).pack(side=tk.LEFT, padx=(6, 4))

        # 输入框
        self.entry_var = tk.StringVar()
        self.entry = tk.Entry(
            self,
            textvariable=self.entry_var,
            bg=Theme.BG_CARD,
            fg=Theme.TEXT_PRIMARY,
            bd=0,
            relief=tk.FLAT,
            font=(Theme.FONT_FAMILY, Theme.FONT_SIZE_BASE),
            insertbackground=Theme.TEXT_PRIMARY
        )
        self.entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2, pady=4)

        # 清除按钮
        self.clear_btn = tk.Button(
            self,
            text="✕",
            command=self.clear,
            bg=Theme.BG_CARD,
            fg=Theme.TEXT_MUTED,
            bd=0,
            relief=tk.FLAT,
            font=(Theme.FONT_FAMILY, Theme.FONT_SIZE_SM),
            activebackground=Theme.BG_CARD,
            cursor="hand2",
            state=tk.DISABLED
        )
        self.clear_btn.pack(side=tk.RIGHT, padx=(4, 6))

        # 绑定变化事件
        if on_change:
            self.entry_var.trace_add("write", lambda *_: on_change(self.get_text()))

        self.entry_var.trace_add("write", lambda *_: self._update_clear_button())

        # 绑定ESC键清除
        self.entry.bind("<Escape>", lambda e: self.clear())

    def get_text(self) -> str:
        """获取搜索文本"""
        return self.entry_var.get()

    def set_text(self, text: str):
        """设置搜索文本"""
        self.entry_var.set(text)

    def clear(self):
        """清空搜索框"""
        self.entry_var.set("")
        self.entry.focus_set()

    def _update_clear_button(self):
        """更新清除按钮状态"""
        state = tk.NORMAL if self.get_text() else tk.DISABLED
        self.clear_btn.configure(state=state)
