#! -*- coding: utf-8 -*-
"""
增强的主题系统
"""


class Theme:
    """现代化配色主题 - 2025增强版"""

    # ============= 主色调 =============
    PRIMARY = "#6366F1"           # 主色（靛蓝）
    PRIMARY_DARK = "#4F46E5"      # 深色主色
    PRIMARY_LIGHT = "#818CF8"     # 浅色主色
    ACCENT = "#8B5CF6"            # 强调色（紫色）
    ACCENT_LIGHT = "#A78BFA"      # 浅紫色

    # ============= 背景色 =============
    BG_MAIN = "#F8FAFC"           # 主背景（极浅灰）
    BG_CARD = "#FFFFFF"           # 卡片背景（纯白）
    BG_HOVER = "#F1F5F9"          # 悬停背景
    BG_SIDEBAR = "#1E293B"        # 侧边栏（深蓝灰）
    BG_TOOLBAR = "#0F172A"        # 顶栏（更深蓝灰）

    # ============= 文字色 =============
    TEXT_PRIMARY = "#0F172A"      # 主文字（深灰蓝）
    TEXT_SECONDARY = "#64748B"    # 次要文字（中灰）
    TEXT_MUTED = "#94A3B8"        # 弱化文字（浅灰）
    TEXT_LIGHT = "#FFFFFF"        # 浅色文字（白色）

    # ============= 状态色 =============
    SUCCESS = "#10B981"           # 成功（翠绿）
    SUCCESS_BG = "#D1FAE5"        # 成功背景
    SUCCESS_HOVER = "#059669"     # 成功悬停

    WARNING = "#F59E0B"           # 警告（琥珀）
    WARNING_BG = "#FEF3C7"        # 警告背景
    WARNING_HOVER = "#D97706"     # 警告悬停

    ERROR = "#EF4444"             # 错误（红色）
    ERROR_BG = "#FEE2E2"          # 错误背景
    ERROR_HOVER = "#DC2626"       # 错误悬停

    INFO = "#3B82F6"              # 信息（蓝色）
    INFO_BG = "#DBEAFE"           # 信息背景
    INFO_HOVER = "#2563EB"        # 信息悬停

    # ============= 边框和分割线 =============
    BORDER = "#E2E8F0"            # 边框色
    BORDER_STRONG = "#CBD5E1"     # 强边框
    BORDER_HOVER = "#94A3B8"      # 悬停边框
    DIVIDER = "#F1F5F9"           # 分割线色

    # ============= 按钮状态 =============
    BTN_HOVER = "#EEF2FF"         # 按钮悬停背景
    BTN_ACTIVE = "#E0E7FF"        # 按钮激活背景

    # ============= 阴影 =============
    SHADOW_SM = "#0000000D"       # 小阴影 (5% opacity)
    SHADOW_MD = "#0000001A"       # 中阴影 (10% opacity)
    SHADOW_LG = "#00000026"       # 大阴影 (15% opacity)

    # ============= 日志终端 =============
    LOG_BG = "#0B1120"            # 日志背景
    LOG_TEXT = "#E2E8F0"          # 日志文字
    LOG_BORDER = "#1E293B"        # 日志边框
    LOG_CURSOR = "#38BDF8"        # 光标颜色

    # ============= 字体 =============
    FONT_FAMILY = "Segoe UI"
    FONT_MONO = "Consolas"

    # 字体大小
    FONT_SIZE_XL = 16
    FONT_SIZE_LG = 14
    FONT_SIZE_MD = 12
    FONT_SIZE_BASE = 10
    FONT_SIZE_SM = 9
    FONT_SIZE_XS = 8

    # ============= 间距 =============
    PADDING_XL = 30
    PADDING_LG = 20
    PADDING_MD = 15
    PADDING_BASE = 12
    PADDING_SM = 8
    PADDING_XS = 6

    # ============= 圆角 =============
    RADIUS_LG = 12
    RADIUS_MD = 8
    RADIUS_SM = 6
    RADIUS_XS = 4

    # ============= 动画时间 =============
    TRANSITION_FAST = 150
    TRANSITION_BASE = 200
    TRANSITION_SLOW = 300


class DarkTheme(Theme):
    """暗色主题 - 未来扩展"""

    # 重写颜色
    BG_MAIN = "#0F172A"
    BG_CARD = "#1E293B"
    BG_HOVER = "#334155"

    TEXT_PRIMARY = "#F1F5F9"
    TEXT_SECONDARY = "#CBD5E1"
    TEXT_MUTED = "#94A3B8"

    BORDER = "#334155"
    BORDER_STRONG = "#475569"
    DIVIDER = "#1E293B"


# 主题注册表
THEMES = {
    "modern": Theme,
    "dark": DarkTheme
}


def get_theme(name: str = "modern") -> type[Theme]:
    """获取主题类"""
    return THEMES.get(name, Theme)
