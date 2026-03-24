from __future__ import annotations

import html
import os
import sys
import tempfile
import threading
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from PyQt6.QtCore import QObject, QRunnable, QSize, Qt, QThreadPool, QTimer, pyqtSignal
from PyQt6.QtGui import QCloseEvent, QFont, QKeySequence, QTextCursor, QShortcut
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStatusBar,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

try:
    from . import cloudflared_cli as cf
    from .config.settings import Settings
    from .services import (
        AuthService,
        CloudflaredBinaryService,
        DnsRouteService,
        TunnelCatalogLoadResult,
        TunnelCatalogMutationResult,
        TunnelCatalogService,
        TunnelConfigService,
        TunnelCoordinationService,
        TunnelDiagnosticsService,
        TunnelLifecycleService,
        TunnelOperationService,
        TunnelRuntimeService,
    )
    from .utils.logger import LogLevel, LogManager
    from .utils.paths import get_logs_dir, get_persistent_logs_dir, get_tunnels_dir
    from .utils.process_tracker import ProcessTracker, SupervisorLock
    from .utils.supervisor_client import SupervisorClient
except (ImportError, ValueError):
    import cloudflared_cli as cf  # type: ignore
    from config.settings import Settings  # type: ignore
    from services import (  # type: ignore
        AuthService,
        CloudflaredBinaryService,
        DnsRouteService,
        TunnelCatalogLoadResult,
        TunnelCatalogMutationResult,
        TunnelCatalogService,
        TunnelConfigService,
        TunnelCoordinationService,
        TunnelDiagnosticsService,
        TunnelLifecycleService,
        TunnelOperationService,
        TunnelRuntimeService,
    )
    from utils.logger import LogLevel, LogManager  # type: ignore
    from utils.paths import get_logs_dir, get_persistent_logs_dir, get_tunnels_dir  # type: ignore
    from utils.process_tracker import ProcessTracker, SupervisorLock  # type: ignore
    from utils.supervisor_client import SupervisorClient  # type: ignore


ACCENT = "#0F6CBD"
ACCENT_DARK = "#0B5EA8"
ACCENT_SOFT = "#EDF5FD"
WINDOW_BG = "#F3F3F3"
CARD_BG = "#FFFFFF"
SURFACE_BG = "#F7F8FA"
HOVER_BG = "#F5F8FC"
SELECTION_BG = "#F3F8FE"
BORDER = "#E1E4EA"
BORDER_STRONG = "#CCD3DB"
TEXT_PRIMARY = "#1B1B1F"
TEXT_SECONDARY = "#596273"
TEXT_MUTED = "#7A8390"
SUCCESS = "#107C10"
SUCCESS_BG = "#E8F5E8"
WARNING = "#CA5010"
WARNING_BG = "#FFF4E5"
ERROR = "#D13438"
ERROR_BG = "#FDE7E9"
INFO = ACCENT
INFO_BG = "#EAF3FC"
LOG_BG = "#F8FAFC"
LOG_TEXT = "#1F2937"


APP_STYLESHEET = f"""
QMainWindow, QWidget {{
    background: {WINDOW_BG};
    color: {TEXT_PRIMARY};
    font-family: "Segoe UI";
    font-size: 10pt;
}}
QWidget#TopBar, QWidget#StatusStrip {{
    background: {SURFACE_BG};
    border: 1px solid {BORDER};
    border-radius: 14px;
}}
QFrame[card="true"] {{
    background: {CARD_BG};
    border: 1px solid {BORDER};
    border-radius: 16px;
}}
QLabel#TitleLabel {{
    font-size: 18pt;
    font-weight: 600;
    color: {TEXT_PRIMARY};
}}
QLabel#SubtitleLabel {{
    color: {TEXT_SECONDARY};
}}
QLabel#MetaLabel {{
    color: {TEXT_MUTED};
    font-size: 9pt;
}}
QLabel#SectionTitle {{
    font-size: 10pt;
    font-weight: 600;
    color: {TEXT_PRIMARY};
}}
QPushButton {{
    background: {CARD_BG};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    border-radius: 10px;
    padding: 7px 12px;
}}
QPushButton:hover {{
    background: {HOVER_BG};
    border-color: {BORDER_STRONG};
}}
QPushButton:pressed {{
    background: {ACCENT_SOFT};
}}
QPushButton[variant="toolbar"] {{
    min-width: 70px;
    color: {TEXT_SECONDARY};
}}
QPushButton[variant="primary"] {{
    background: {ACCENT};
    color: white;
    border-color: {ACCENT};
    font-weight: 600;
    padding: 10px 14px;
}}
QPushButton[variant="primary"]:hover {{
    background: {ACCENT_DARK};
    border-color: {ACCENT_DARK};
}}
QPushButton[variant="danger"] {{
    background: {ERROR};
    color: white;
    border-color: {ERROR};
    font-weight: 600;
    padding: 10px 14px;
}}
QPushButton[variant="danger"]:hover {{
    background: #b52e31;
    border-color: #b52e31;
}}
QPushButton[variant="ghost"] {{
    background: {ACCENT_SOFT};
    color: {ACCENT};
    border-color: #c5dcf4;
}}
QPushButton[variant="ghost"]:hover {{
    background: #e4f0fb;
}}
QLineEdit {{
    background: {CARD_BG};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    border-radius: 10px;
    padding: 8px 12px;
    selection-background-color: {ACCENT};
}}
QLineEdit:focus {{
    border-color: {ACCENT};
}}
QListWidget {{
    background: transparent;
    border: none;
    outline: none;
}}
QListWidget::item {{
    border: none;
    padding: 0px;
    margin: 0px;
}}
QTextEdit {{
    background: {LOG_BG};
    color: {LOG_TEXT};
    border: 1px solid {BORDER};
    border-radius: 12px;
    padding: 10px;
    selection-background-color: #d7e8f9;
}}
QCheckBox {{
    color: {TEXT_PRIMARY};
    spacing: 8px;
}}
QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border: 1px solid {BORDER_STRONG};
    border-radius: 4px;
    background: white;
}}
QCheckBox::indicator:checked {{
    background: {ACCENT};
    border-color: {ACCENT};
}}
QSplitter::handle {{
    background: transparent;
}}
"""


def _status_palette(status: str) -> tuple[str, str, str]:
    if status == "success":
        return SUCCESS_BG, SUCCESS, SUCCESS
    if status == "warning":
        return WARNING_BG, WARNING, WARNING
    if status == "error":
        return ERROR_BG, ERROR, ERROR
    if status == "info":
        return INFO_BG, INFO, INFO
    return SURFACE_BG, TEXT_SECONDARY, BORDER


class UiBridge(QObject):
    log_entry = pyqtSignal(str, str, str)
    refresh_requested = pyqtSignal(str)


class TaskSignals(QObject):
    finished = pyqtSignal(object)
    failed = pyqtSignal(str, str)


class FunctionTask(QRunnable):
    def __init__(self, fn: Callable[[], Any]):
        super().__init__()
        self.fn = fn
        self.signals = TaskSignals()

    def run(self) -> None:
        try:
            result = self.fn()
        except Exception as exc:
            self.signals.failed.emit(str(exc), traceback.format_exc())
        else:
            self.signals.finished.emit(result)


class StatusTile(QFrame):
    def __init__(self, title: str, parent: QWidget | None = None):
        super().__init__(parent)
        self._title = QLabel(title, self)
        self._title.setObjectName("MetaLabel")
        self._value = QLabel("—", self)
        self._value.setStyleSheet("font-size: 11pt; font-weight: 600;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(4)
        layout.addWidget(self._title)
        layout.addWidget(self._value)
        self.set_content(title, "—", "default")

    def set_content(self, title: str, value: str, tone: str = "default") -> None:
        bg, fg, border_color = _status_palette(tone)
        self._title.setText(title)
        self._value.setText(value)
        self._value.setStyleSheet(f"font-size: 11pt; font-weight: 600; color: {fg};")
        self.setStyleSheet(
            f"background: {bg}; border: 1px solid {border_color}; border-radius: 12px;"
        )


class TunnelListItemWidget(QFrame):
    def __init__(self, tunnel: dict[str, Any], runtime: dict[str, Any] | None):
        super().__init__()
        self.tunnel = tunnel
        self.runtime = runtime
        self._selected = False
        self._hovered = False
        self.setObjectName("TunnelCard")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self.indicator = QFrame(self)
        self.indicator.setFixedWidth(4)

        self.name_label = QLabel(str(tunnel.get("name") or "Unnamed"), self)
        self.name_label.setStyleSheet("font-size: 10.5pt; font-weight: 600; color: #1b1b1f;")

        self.badge_label = QLabel(self)
        self.badge_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.badge_label.setMinimumWidth(72)

        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(10)
        top_row.addWidget(self.name_label)
        top_row.addStretch(1)
        top_row.addWidget(self.badge_label)

        tunnel_id = str(
            tunnel.get("id")
            or tunnel.get("tunnel_id")
            or tunnel.get("tunnel id")
            or ""
        )
        short_id = tunnel_id[:8] + "..." if len(tunnel_id) > 8 else tunnel_id or "未解析"
        created = str(tunnel.get("created_at") or "")[:10] or "未知"

        self.meta_label = QLabel(f"ID {short_id}  ·  创建 {created}", self)
        self.meta_label.setObjectName("MetaLabel")

        content_layout = QVBoxLayout()
        content_layout.setContentsMargins(12, 10, 12, 10)
        content_layout.setSpacing(6)
        content_layout.addLayout(top_row)
        content_layout.addWidget(self.meta_label)

        root_layout = QHBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        root_layout.addWidget(self.indicator)
        root_layout.addLayout(content_layout, 1)

        self._apply_runtime()
        self._apply_card_style()

        for child in self.findChildren(QWidget):
            if child is not self:
                child.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def sizeHint(self) -> QSize:
        return QSize(320, 74)

    def enterEvent(self, event) -> None:  # type: ignore[override]
        self._hovered = True
        self._apply_card_style()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # type: ignore[override]
        self._hovered = False
        self._apply_card_style()
        super().leaveEvent(event)

    def set_selected(self, selected: bool) -> None:
        self._selected = bool(selected)
        self._apply_card_style()

    def _apply_runtime(self) -> None:
        runtime = self.runtime or {}
        if runtime.get("healthy") is True:
            label = "已连接"
            tone = "success"
        elif runtime.get("healthy") is False:
            label = "异常"
            tone = "warning"
        elif runtime:
            label = "检测中"
            tone = "info"
        else:
            label = "未启动"
            tone = "default"

        bg, fg, border_color = _status_palette(tone)
        line_color = fg if tone != "default" else BORDER
        self.indicator.setStyleSheet(
            f"background: {line_color}; border: none; border-radius: 2px;"
        )
        self.badge_label.setText(label)
        self.badge_label.setStyleSheet(
            f"background: {bg}; color: {fg}; border: 1px solid {border_color}; "
            "border-radius: 9px; padding: 3px 8px; font-size: 8.5pt; font-weight: 600;"
        )

    def _apply_card_style(self) -> None:
        if self._selected:
            bg = SELECTION_BG
            border_color = ACCENT
        elif self._hovered:
            bg = HOVER_BG
            border_color = BORDER_STRONG
        else:
            bg = CARD_BG
            border_color = BORDER

        self.setStyleSheet(
            f"QFrame#TunnelCard {{ background: {bg}; border: 1px solid {border_color}; "
            "border-radius: 14px; }}"
        )


class ConfigEditorDialog(QDialog):
    def __init__(
        self,
        config_path: Path,
        tunnel_name: str,
        tunnel_id: str,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.config_path = Path(config_path)
        self.tunnel_name = tunnel_name
        self.tunnel_id = tunnel_id

        self.setWindowTitle(f"配置隧道 - {tunnel_name}")
        self.resize(920, 720)
        self.setMinimumSize(760, 560)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        title = QLabel("YAML 配置", self)
        title.setObjectName("TitleLabel")
        subtitle = QLabel(str(self.config_path), self)
        subtitle.setObjectName("MetaLabel")

        header = QVBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(2)
        header.addWidget(title)
        header.addWidget(subtitle)
        layout.addLayout(header)

        hint = QLabel("直接编辑完整 config.yml。启动时会按配置自动补齐 DNS 路由。", self)
        hint.setObjectName("MetaLabel")
        layout.addWidget(hint)

        self.editor = QTextEdit(self)
        self.editor.setObjectName("YamlEditor")
        self.editor.setAcceptRichText(False)
        self.editor.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self.editor.setFont(QFont("Consolas", 10))
        layout.addWidget(self.editor, 1)

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        footer.setSpacing(8)

        self.status_label = QLabel("就绪", self)
        self.status_label.setObjectName("MetaLabel")
        footer.addWidget(self.status_label)
        footer.addStretch(1)

        self.validate_button = QPushButton("验证", self)
        self.save_button = QPushButton("保存", self)
        self.close_button = QPushButton("关闭", self)
        self.validate_button.setProperty("variant", "ghost")
        self.save_button.setProperty("variant", "primary")
        self.close_button.setProperty("variant", "toolbar")
        self.validate_button.clicked.connect(self.validate_config)
        self.save_button.clicked.connect(self.save_config)
        self.close_button.clicked.connect(self.reject)
        footer.addWidget(self.validate_button)
        footer.addWidget(self.save_button)
        footer.addWidget(self.close_button)
        layout.addLayout(footer)

        QShortcut(QKeySequence("Ctrl+S"), self, activated=self.save_config)
        self._load_config()

    def _load_config(self) -> None:
        if self.config_path.exists():
            try:
                content = self.config_path.read_text(encoding="utf-8")
            except Exception as exc:
                QMessageBox.critical(self, "加载失败", f"无法读取配置文件:\n{exc}")
                return
            self.editor.setPlainText(content)
            self.status_label.setText("配置已加载")
            return

        self.editor.setPlainText(self._default_config_text())
        self.status_label.setText("已载入默认模板（尚未保存）")

    def _default_config_text(self) -> str:
        return (
            f"tunnel: {self.tunnel_id}\n"
            f"credentials-file: {cf.default_credentials_path(self.tunnel_id).as_posix()}\n"
            "ingress:\n"
            "  - hostname: app.example.com\n"
            "    service: http://localhost:8080\n"
            "  - service: http_status:404\n"
        )

    def _content(self) -> str:
        return self.editor.toPlainText().strip()

    def _validate_content(self, content: str) -> tuple[bool, str]:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir) / "config.yml"
            temp_path.write_text(content + "\n", encoding="utf-8")
            return cf.validate_config(temp_path)

    def validate_config(self) -> bool:
        content = self._content()
        if not content:
            QMessageBox.warning(self, "验证失败", "配置内容不能为空。")
            return False

        ok, message = self._validate_content(content)
        self.status_label.setText(message)
        if ok:
            QMessageBox.information(self, "验证通过", message)
        else:
            QMessageBox.warning(self, "验证失败", message)
        return ok

    def save_config(self) -> None:
        content = self._content()
        if not content:
            QMessageBox.warning(self, "保存失败", "配置内容不能为空。")
            return

        try:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            self.config_path.write_text(content + "\n", encoding="utf-8")
        except Exception as exc:
            QMessageBox.critical(self, "保存失败", f"写入配置文件失败:\n{exc}")
            self.status_label.setText("保存失败")
            return

        ok, message = self._validate_content(content)
        self.status_label.setText("配置已保存" if ok else f"配置已保存，{message}")
        if ok:
            self.accept()
            return
        QMessageBox.warning(self, "保存完成", f"配置已保存，但校验未通过:\n\n{message}")


class DiagnosticsDialog(QDialog):
    def __init__(self, tunnel_name: str, lines: list[tuple[str, str | None]], parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(f"诊断 - {tunnel_name}")
        self.resize(820, 620)
        self.setMinimumSize(680, 460)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        title = QLabel(f"隧道诊断: {tunnel_name}", self)
        title.setObjectName("TitleLabel")
        layout.addWidget(title)

        self.report_view = QTextEdit(self)
        self.report_view.setReadOnly(True)
        self.report_view.setFont(QFont("Consolas", 10))
        layout.addWidget(self.report_view, 1)

        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        button_box.rejected.connect(self.reject)
        button_box.accepted.connect(self.accept)
        layout.addWidget(button_box)

        self._set_report(lines)

    def _set_report(self, lines: list[tuple[str, str | None]]) -> None:
        color_map = {
            "success": SUCCESS,
            "warning": WARNING,
            "error": ERROR,
            "info": INFO,
            None: LOG_TEXT,
        }
        parts: list[str] = []
        for text, tag in lines:
            color = color_map.get(tag, LOG_TEXT)
            parts.append(
                f'<span style="color: {color}; white-space: pre-wrap;">{html.escape(text)}</span>'
            )
        self.report_view.setHtml("<br>".join(parts))


class QtTunnelManager(QMainWindow):
    def __init__(self):
        super().__init__()
        self.project_root = Path(__file__).resolve().parent.parent
        self.settings = Settings()
        self.thread_pool = QThreadPool(self)
        self.ui_bridge = UiBridge()
        self.ui_bridge.log_entry.connect(self._append_log_entry)
        self.ui_bridge.refresh_requested.connect(
            lambda tunnel_name: self.refresh_tunnels(select_name=tunnel_name, silent=True)
        )

        self.binary_service = CloudflaredBinaryService(self.project_root)
        self.runtime_service = TunnelRuntimeService(self.binary_service)
        self.auth_service = AuthService()
        self.config_service = TunnelConfigService()
        self.catalog_service = TunnelCatalogService(self.project_root, self.config_service)
        self.dns_service = DnsRouteService()
        self.operation_service = TunnelOperationService()
        self.diagnostics_service = TunnelDiagnosticsService()
        self.proc_tracker = ProcessTracker(self.project_root)
        self.supervisor_lock = SupervisorLock(self.project_root)
        self.supervisor_client = SupervisorClient(self.project_root)
        self.coordination_service = TunnelCoordinationService(
            self.supervisor_lock,
            self.supervisor_client,
        )
        self.lifecycle_service = TunnelLifecycleService(
            self.dns_service,
            self.config_service,
            self.operation_service,
        )

        self.logger = LogManager(
            max_lines=int(self.settings.get("log.max_lines", 1000) or 1000),
            save_to_file=True,
        )
        self.logger.add_callback(self._handle_logger_callback)

        self.health_cache: dict[str, dict[str, Any]] = {}
        self.proc_map: dict[str, Any] = {}
        self.running_tunnels: dict[str, dict[str, Any]] = {}
        self._tunnels: list[dict[str, Any]] = []
        self._list_source = "local"
        self._busy = False
        self._refreshing = False
        self._pending_select_name = str(self.settings.get("tunnel.last_selected") or "")
        self._selected_name = self._pending_select_name
        self._autostart_consumed = False
        self._supervisor_active = False
        self._supervisor_available = self.supervisor_client.is_available()

        self.cloudflared_path = str(
            self.settings.get("cloudflared.path")
            or self.binary_service.resolve_path()
            or ""
        )

        self.setWindowTitle("Cloudflare Tunnel")
        self.setMinimumSize(
            int(self.settings.get("window.min_width", 1080) or 1080),
            int(self.settings.get("window.min_height", 680) or 680),
        )
        self.resize(
            int(self.settings.get("window.width", 1320) or 1320),
            int(self.settings.get("window.height", 820) or 820),
        )
        self._restore_window_position()
        self._build_ui()
        self._apply_styles()
        self._update_path_status()
        self._refresh_version()
        self._update_autostart_hint()
        self._update_selected_panel()

        self.refresh_timer = QTimer(self)
        self.refresh_timer.setInterval(8000)
        self.refresh_timer.timeout.connect(self._poll_runtime_status)
        self.refresh_timer.start()

        QTimer.singleShot(0, lambda: self.refresh_tunnels(silent=True))

    def _apply_styles(self) -> None:
        app = QApplication.instance()
        if app is not None:
            app.setStyle("Fusion")
            app.setStyleSheet(APP_STYLESHEET)

    def _restore_window_position(self) -> None:
        if not self.settings.get("window.remember_position", True):
            return
        x = self.settings.get("window.x")
        y = self.settings.get("window.y")
        if x is None or y is None:
            return
        try:
            self.move(int(x), int(y))
        except Exception:
            pass

    def _save_window_state(self) -> None:
        self.settings.set("window.width", self.width())
        self.settings.set("window.height", self.height())
        if self.settings.get("window.remember_position", True):
            self.settings.set("window.x", self.x())
            self.settings.set("window.y", self.y())

    def _build_ui(self) -> None:
        root = QWidget(self)
        root.setObjectName("Root")
        self.setCentralWidget(root)

        main_layout = QVBoxLayout(root)
        main_layout.setContentsMargins(18, 18, 18, 12)
        main_layout.setSpacing(12)

        topbar = QWidget(self)
        topbar.setObjectName("TopBar")
        topbar_layout = QHBoxLayout(topbar)
        topbar_layout.setContentsMargins(16, 14, 16, 14)
        topbar_layout.setSpacing(12)

        title_block = QVBoxLayout()
        title_block.setContentsMargins(0, 0, 0, 0)
        title_block.setSpacing(2)
        title = QLabel("Cloudflare Tunnel", topbar)
        title.setObjectName("TitleLabel")
        subtitle = QLabel("Win11 风格紧凑界面", topbar)
        subtitle.setObjectName("SubtitleLabel")
        title_block.addWidget(title)
        title_block.addWidget(subtitle)
        topbar_layout.addLayout(title_block)
        topbar_layout.addStretch(1)

        self.version_label = QLabel("Cloudflared: 检测中", topbar)
        self.version_label.setObjectName("MetaLabel")
        topbar_layout.addWidget(self.version_label)

        self.login_button = self._make_button("登录", "toolbar", self._login)
        self.choose_binary_button = self._make_button("选择程序", "toolbar", self._choose_cloudflared)
        self.update_binary_button = self._make_button("更新", "toolbar", self._check_update_cloudflared)
        for button in (self.login_button, self.choose_binary_button, self.update_binary_button):
            topbar_layout.addWidget(button)

        main_layout.addWidget(topbar)

        splitter = QSplitter(Qt.Orientation.Horizontal, root)
        splitter.setChildrenCollapsible(False)
        main_layout.addWidget(splitter, 1)

        left_panel = self._make_card()
        left_panel_layout = left_panel.layout()
        splitter.addWidget(left_panel)

        left_header = QHBoxLayout()
        left_header.setContentsMargins(0, 0, 0, 0)
        left_header.setSpacing(10)
        left_header.addWidget(self._make_section_label("我的隧道"))
        left_header.addStretch(1)

        self.search_input = QLineEdit(left_panel)
        self.search_input.setPlaceholderText("搜索名称、UUID、日期")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.textChanged.connect(self._apply_filter)
        self.search_input.setMinimumWidth(240)
        left_header.addWidget(self.search_input)

        self.refresh_button = self._make_button("刷新", "ghost", lambda: self.refresh_tunnels())
        self.create_button = self._make_button("新建", "ghost", self._create_tunnel)
        self.delete_button = self._make_button("删除", "ghost", self._delete_selected)
        left_header.addWidget(self.refresh_button)
        left_header.addWidget(self.create_button)
        left_header.addWidget(self.delete_button)
        left_panel_layout.addLayout(left_header)

        self.empty_label = QLabel("暂无隧道", left_panel)
        self.empty_label.setObjectName("MetaLabel")
        left_panel_layout.addWidget(self.empty_label)

        self.tunnel_list = QListWidget(left_panel)
        self.tunnel_list.currentItemChanged.connect(self._on_selection_changed)
        self.tunnel_list.itemSelectionChanged.connect(self._sync_list_item_styles)
        left_panel_layout.addWidget(self.tunnel_list, 1)

        right_column = QWidget(root)
        right_layout = QVBoxLayout(right_column)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(12)
        splitter.addWidget(right_column)
        splitter.setStretchFactor(0, 36)
        splitter.setStretchFactor(1, 64)

        overview_card = self._make_card("当前隧道")
        overview_layout = overview_card.layout()
        self.selected_name_label = QLabel("未选择隧道", overview_card)
        self.selected_name_label.setObjectName("TitleLabel")
        self.selected_meta_label = QLabel("请从左侧选择一个隧道。", overview_card)
        self.selected_meta_label.setObjectName("MetaLabel")
        self.selected_path_label = QLabel("", overview_card)
        self.selected_path_label.setObjectName("MetaLabel")
        overview_layout.addWidget(self.selected_name_label)
        overview_layout.addWidget(self.selected_meta_label)
        overview_layout.addWidget(self.selected_path_label)

        self.toggle_button = self._make_button("启动隧道", "primary", self._toggle_start_selected)
        overview_layout.addWidget(self.toggle_button)

        action_grid = QGridLayout()
        action_grid.setContentsMargins(0, 0, 0, 0)
        action_grid.setHorizontalSpacing(8)
        action_grid.setVerticalSpacing(8)
        self.edit_button = self._make_button("编辑配置", "toolbar", self._edit_selected_config)
        self.diagnose_button = self._make_button("诊断", "toolbar", self._diagnose_selected)
        self.open_dir_button = self._make_button("打开目录", "toolbar", self._open_config_dir)
        action_grid.addWidget(self.edit_button, 0, 0)
        action_grid.addWidget(self.diagnose_button, 0, 1)
        action_grid.addWidget(self.open_dir_button, 1, 0, 1, 2)
        overview_layout.addLayout(action_grid)
        right_layout.addWidget(overview_card)

        options_card = self._make_card("运行选项")
        options_layout = options_card.layout()
        self.persist_checkbox = QCheckBox("退出后保持隧道运行", options_card)
        self.persist_checkbox.setChecked(bool(self.settings.get("tunnel.persist_on_exit", False)))
        self.persist_checkbox.toggled.connect(self._on_persist_changed)
        self.autostart_checkbox = QCheckBox("启动时自动拉起目标隧道", options_card)
        self.autostart_checkbox.setChecked(bool(self.settings.get("tunnel.auto_start_enabled", False)))
        self.autostart_checkbox.toggled.connect(self._on_autostart_changed)
        self.autostart_hint = QLabel("", options_card)
        self.autostart_hint.setObjectName("MetaLabel")
        options_layout.addWidget(self.persist_checkbox)
        options_layout.addWidget(self.autostart_checkbox)
        options_layout.addWidget(self.autostart_hint)
        right_layout.addWidget(options_card)

        status_card = self._make_card("状态")
        status_layout = status_card.layout()
        status_grid = QGridLayout()
        status_grid.setContentsMargins(0, 0, 0, 0)
        status_grid.setHorizontalSpacing(10)
        status_grid.setVerticalSpacing(10)
        self.source_tile = StatusTile("列表来源", status_card)
        self.runtime_tile = StatusTile("运行状态", status_card)
        self.health_tile = StatusTile("连接状态", status_card)
        self.cert_tile = StatusTile("认证", status_card)
        status_grid.addWidget(self.source_tile, 0, 0)
        status_grid.addWidget(self.runtime_tile, 0, 1)
        status_grid.addWidget(self.health_tile, 1, 0)
        status_grid.addWidget(self.cert_tile, 1, 1)
        status_layout.addLayout(status_grid)
        right_layout.addWidget(status_card)

        log_card = self._make_card("日志")
        log_layout = log_card.layout()
        log_toolbar = QHBoxLayout()
        log_toolbar.setContentsMargins(0, 0, 0, 0)
        log_toolbar.setSpacing(8)
        log_toolbar.addWidget(self._make_section_label("最近事件"))
        log_toolbar.addStretch(1)
        self.copy_log_button = self._make_button("复制", "toolbar", self._copy_log)
        self.save_log_button = self._make_button("保存", "toolbar", self._save_log_to_file)
        self.clear_log_button = self._make_button("清空", "toolbar", self._clear_log)
        log_toolbar.addWidget(self.copy_log_button)
        log_toolbar.addWidget(self.save_log_button)
        log_toolbar.addWidget(self.clear_log_button)
        log_layout.addLayout(log_toolbar)

        self.log_view = QTextEdit(log_card)
        self.log_view.setReadOnly(True)
        log_layout.addWidget(self.log_view, 1)
        right_layout.addWidget(log_card, 1)

        statusbar = QStatusBar(self)
        statusbar.setObjectName("StatusStrip")
        statusbar.setSizeGripEnabled(False)
        self.setStatusBar(statusbar)
        self.path_status_label = QLabel("", self)
        self.path_status_label.setObjectName("MetaLabel")
        self.mode_status_label = QLabel("GUI 直连", self)
        self.mode_status_label.setObjectName("MetaLabel")
        statusbar.addPermanentWidget(self.mode_status_label)
        statusbar.addPermanentWidget(self.path_status_label, 1)
        self.statusBar().showMessage("就绪")

    def _make_card(self, title: str | None = None) -> QFrame:
        card = QFrame(self)
        card.setProperty("card", True)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)
        if title:
            layout.addWidget(self._make_section_label(title))
        return card

    def _make_section_label(self, text: str) -> QLabel:
        label = QLabel(text, self)
        label.setObjectName("SectionTitle")
        return label

    def _make_button(self, text: str, variant: str, callback: Callable[[], None]) -> QPushButton:
        button = QPushButton(text, self)
        button.setProperty("variant", variant)
        button.clicked.connect(callback)
        return button

    def _set_button_variant(self, button: QPushButton, variant: str) -> None:
        button.setProperty("variant", variant)
        button.style().unpolish(button)
        button.style().polish(button)
        button.update()

    def _handle_logger_callback(self, timestamp: datetime, level: LogLevel, message: str) -> None:
        self.ui_bridge.log_entry.emit(
            timestamp.strftime("%H:%M:%S"),
            level.name.lower(),
            str(message),
        )

    def _append_log_entry(self, timestamp: str, level: str, message: str) -> None:
        color_map = {
            "debug": TEXT_MUTED,
            "info": INFO,
            "success": SUCCESS,
            "warning": WARNING,
            "error": ERROR,
        }
        color = color_map.get(level, LOG_TEXT)
        cursor = self.log_view.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        escaped = html.escape(message)
        cursor.insertHtml(
            f'<span style="color: {TEXT_MUTED};">[{timestamp}]</span> '
            f'<span style="color: {color}; white-space: pre-wrap;">{escaped}</span>'
        )
        cursor.insertBlock()
        self.log_view.setTextCursor(cursor)
        self.log_view.ensureCursorVisible()

    def _log(self, level: str, message: str, *, status: str | None = None) -> None:
        method = getattr(self.logger, level, self.logger.info)
        method(message)
        self.statusBar().showMessage(status or message)

    def _run_background(
        self,
        fn: Callable[[], Any],
        on_done: Callable[[Any], None],
        on_error: Callable[[str, str], None] | None = None,
    ) -> None:
        task = FunctionTask(fn)
        if on_error is None:
            on_error = self._handle_task_error
        task.signals.finished.connect(on_done)
        task.signals.failed.connect(on_error)
        self.thread_pool.start(task)

    def _set_busy(self, busy: bool, status: str | None = None) -> None:
        self._busy = busy
        controls = [
            self.refresh_button,
            self.create_button,
            self.delete_button,
            self.login_button,
            self.choose_binary_button,
            self.update_binary_button,
            self.toggle_button,
            self.edit_button,
            self.diagnose_button,
            self.open_dir_button,
        ]
        for control in controls:
            control.setEnabled(not busy)
        if status:
            self.statusBar().showMessage(status)
        self._update_selected_panel()

    def _handle_task_error(self, message: str, tb: str) -> None:
        self._set_busy(False, "操作失败")
        self._refreshing = False
        self._log("error", message or "后台任务失败", status="操作失败")
        crash_log = get_logs_dir() / "qt_gui_crash.log"
        crash_log.parent.mkdir(parents=True, exist_ok=True)
        crash_log.write_text(tb + "\n", encoding="utf-8")

    def _update_path_status(self) -> None:
        text = self.cloudflared_path or "未设置 cloudflared 路径"
        self.path_status_label.setText(text)

    def _refresh_version(self) -> None:
        resolved = self._resolve_cloudflared_path(store_if_found=False)
        info = self.binary_service.version_info(resolved or None)
        self.version_label.setText(info.display_text)
        self._update_path_status()

    def _resolve_cloudflared_path(self, *, require: bool = False, store_if_found: bool = True) -> str:
        preferred = self.cloudflared_path.strip()
        resolved = self.binary_service.resolve_path(preferred) or ""
        if resolved and resolved != self.cloudflared_path:
            self.cloudflared_path = resolved
        if resolved and store_if_found:
            self.settings.set("cloudflared.path", resolved)
        self._refresh_version_text_only(resolved)
        self._update_path_status()
        if require and not resolved:
            QMessageBox.warning(self, "缺少 cloudflared", "请先选择或安装 cloudflared 可执行文件。")
        return resolved

    def _refresh_version_text_only(self, path: str) -> None:
        info = self.binary_service.version_info(path or None)
        self.version_label.setText(info.display_text)

    def refresh_tunnels(self, *, select_name: str | None = None, silent: bool = False) -> None:
        if self._refreshing or self._busy:
            return

        self._refreshing = True
        if select_name is not None:
            self._pending_select_name = select_name
        elif self._selected_name:
            self._pending_select_name = self._selected_name

        path = self._resolve_cloudflared_path(store_if_found=False)
        if not silent:
            self.statusBar().showMessage("刷新中…")

        def worker() -> dict[str, Any]:
            sync = self.coordination_service.sync_supervisor_state(
                self._supervisor_active,
                log_message=False,
            )
            if path:
                result = self.catalog_service.load_tunnels(path)
                running = self.runtime_service.get_running_tunnels_with_health(
                    path,
                    self.health_cache,
                    cache_ttl=8,
                    timeout=10,
                )
            else:
                local_tunnels = cf.load_local_tunnels(self.project_root)
                result = TunnelCatalogLoadResult(
                    ok=bool(local_tunnels),
                    source="local" if local_tunnels else "empty",
                    tunnels=local_tunnels,
                    error=None if local_tunnels else "未配置 cloudflared 路径",
                    warnings=[] if local_tunnels else ["未配置 cloudflared 路径，仅显示本地数据。"],
                )
                running = cf.get_running_tunnels()
                for entry in running:
                    entry["healthy"] = None
            return {
                "result": result,
                "running": running,
                "supervisor": sync,
            }

        self._run_background(worker, self._apply_refresh_result)

    def _apply_refresh_result(self, payload: dict[str, Any]) -> None:
        self._refreshing = False
        result: TunnelCatalogLoadResult = payload["result"]
        running_entries = payload["running"]
        supervisor = payload["supervisor"]

        self._supervisor_active = bool(supervisor.active)
        self._supervisor_available = bool(supervisor.available)
        self.mode_status_label.setText(
            "守护进程接管" if self._supervisor_active and self._supervisor_available else "GUI 直连"
        )

        self._list_source = result.source
        self.running_tunnels = {
            str(entry.get("name") or ""): entry
            for entry in running_entries
            if entry.get("name")
        }
        self._tunnels = list(result.tunnels or [])

        if result.messages:
            for message in result.messages:
                self._log("info", message)
        if result.warnings:
            for warning in result.warnings:
                self._log("warning", warning)
        if result.error:
            self._log("warning", result.error, status=result.error)

        self._apply_filter()
        self._update_status_tiles()

        if self._tunnels:
            self.statusBar().showMessage(f"共 {len(self._tunnels)} 个隧道")
        else:
            self.statusBar().showMessage("未发现可用隧道")

        if not self._autostart_consumed:
            self._apply_autostart_if_needed()

    def _poll_runtime_status(self) -> None:
        self.refresh_tunnels(silent=True)

    def _apply_filter(self) -> None:
        query = self.search_input.text().strip().lower()
        self.tunnel_list.clear()
        filtered: list[dict[str, Any]] = []
        for tunnel in self._tunnels:
            if not query:
                filtered.append(tunnel)
                continue
            fields = [
                str(tunnel.get("name") or ""),
                str(tunnel.get("id") or ""),
                str(tunnel.get("tunnel_id") or ""),
                str(tunnel.get("tunnel id") or ""),
                str(tunnel.get("created_at") or ""),
            ]
            combined = " ".join(fields).lower()
            if query in combined:
                filtered.append(tunnel)

        self.empty_label.setVisible(not filtered)
        self.tunnel_list.setVisible(bool(filtered))
        target_name = self._pending_select_name or self._selected_name

        for tunnel in filtered:
            name = str(tunnel.get("name") or "")
            runtime = self.running_tunnels.get(name)
            item = QListWidgetItem(self.tunnel_list)
            item.setData(Qt.ItemDataRole.UserRole, tunnel)
            widget = TunnelListItemWidget(tunnel, runtime)
            item.setSizeHint(widget.sizeHint())
            self.tunnel_list.addItem(item)
            self.tunnel_list.setItemWidget(item, widget)

        selected = False
        if target_name:
            for index in range(self.tunnel_list.count()):
                item = self.tunnel_list.item(index)
                data = item.data(Qt.ItemDataRole.UserRole) or {}
                if str(data.get("name") or "") == target_name:
                    self.tunnel_list.setCurrentItem(item)
                    selected = True
                    break
        if not selected and self.tunnel_list.count():
            self.tunnel_list.setCurrentRow(0)

        self._pending_select_name = ""
        self._sync_list_item_styles()
        self._update_selected_panel()
        self._update_status_tiles()

    def _sync_list_item_styles(self) -> None:
        current = self.tunnel_list.currentItem()
        for index in range(self.tunnel_list.count()):
            item = self.tunnel_list.item(index)
            widget = self.tunnel_list.itemWidget(item)
            if isinstance(widget, TunnelListItemWidget):
                widget.set_selected(item is current)

    def _on_selection_changed(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None) -> None:
        tunnel = current.data(Qt.ItemDataRole.UserRole) if current is not None else None
        self._selected_name = str((tunnel or {}).get("name") or "")
        if self._selected_name:
            self.settings.set("tunnel.last_selected", self._selected_name)
            if self.autostart_checkbox.isChecked():
                self.settings.set("tunnel.autostart_tunnel", self._selected_name)
        self._update_selected_panel()
        self._update_status_tiles()
        self._sync_list_item_styles()

    def _current_tunnel(self) -> dict[str, Any] | None:
        current = self.tunnel_list.currentItem()
        if current is None:
            return None
        data = current.data(Qt.ItemDataRole.UserRole)
        return data if isinstance(data, dict) else None

    def _is_tunnel_running(self, tunnel_name: str | None) -> bool:
        if not tunnel_name:
            return False
        return bool(self.running_tunnels.get(tunnel_name))

    def _selected_tunnel_id(self, tunnel: dict[str, Any]) -> str | None:
        tunnel_id = self.runtime_service.extract_tunnel_id(tunnel)
        if tunnel_id:
            return tunnel_id
        name = str(tunnel.get("name") or "")
        if not name:
            return None
        config_path = self.catalog_service.config_path_for(name)
        return cf.extract_tunnel_id_from_config(config_path)

    def _update_selected_panel(self) -> None:
        tunnel = self._current_tunnel()
        has_tunnel = tunnel is not None
        for button in (self.delete_button, self.toggle_button, self.edit_button, self.diagnose_button):
            button.setEnabled(has_tunnel and not self._busy)

        if not tunnel:
            self.selected_name_label.setText("未选择隧道")
            self.selected_meta_label.setText("请从左侧选择一个隧道。")
            self.selected_path_label.setText("")
            self.toggle_button.setText("启动隧道")
            self._set_button_variant(self.toggle_button, "primary")
            return

        name = str(tunnel.get("name") or "Unnamed")
        tunnel_id = self._selected_tunnel_id(tunnel) or "未解析"
        short_id = tunnel_id[:8] + "..." if len(tunnel_id) > 8 else tunnel_id
        created = str(tunnel.get("created_at") or "")[:10] or "未知"
        config_path = self.catalog_service.config_path_for(name)
        runtime = self.running_tunnels.get(name)

        self.selected_name_label.setText(name)
        self.selected_meta_label.setText(f"UUID {short_id}  ·  创建 {created}")
        manager_text = "守护进程" if runtime and runtime.get("manager") else "GUI"
        self.selected_path_label.setText(f"{config_path}  ·  管理方式 {manager_text}")

        if self._is_tunnel_running(name):
            self.toggle_button.setText("停止隧道")
            self._set_button_variant(self.toggle_button, "danger")
        else:
            self.toggle_button.setText("启动隧道")
            self._set_button_variant(self.toggle_button, "primary")

    def _update_status_tiles(self) -> None:
        tunnel = self._current_tunnel()
        if self._list_source == "online":
            self.source_tile.set_content("列表来源", "在线", "success")
        elif self._list_source == "offline":
            self.source_tile.set_content("列表来源", "离线", "warning")
        elif self._list_source == "local":
            self.source_tile.set_content("列表来源", "本地", "info")
        else:
            self.source_tile.set_content("列表来源", "空", "default")

        if not tunnel:
            self.runtime_tile.set_content("运行状态", "未选择", "default")
            self.health_tile.set_content("连接状态", "—", "default")
        else:
            name = str(tunnel.get("name") or "")
            runtime = self.running_tunnels.get(name)
            if runtime:
                self.runtime_tile.set_content("运行状态", "运行中", "success")
                healthy = runtime.get("healthy")
                if healthy is True:
                    self.health_tile.set_content("连接状态", "正常", "success")
                elif healthy is False:
                    self.health_tile.set_content("连接状态", "异常", "warning")
                else:
                    self.health_tile.set_content("连接状态", "检测中", "info")
            else:
                self.runtime_tile.set_content("运行状态", "未运行", "default")
                self.health_tile.set_content("连接状态", "空闲", "default")

        cert_status = self.auth_service.get_origin_cert_status(None)
        if cert_status.exists and cert_status.path:
            label = "cert.pem"
            if cert_status.updated:
                label = f"cert.pem · {cert_status.updated}"
            self.cert_tile.set_content("认证", label, "success")
        else:
            self.cert_tile.set_content("认证", "未认证", "warning")

    def _on_persist_changed(self, checked: bool) -> None:
        self.settings.set("tunnel.persist_on_exit", bool(checked))
        self._log("info", "已更新退出后保持运行设置")

    def _update_autostart_hint(self) -> None:
        if not self.autostart_checkbox.isChecked():
            self.autostart_hint.setText("自动启动：已关闭")
            return
        target = str(self.settings.get("tunnel.autostart_tunnel") or "").strip()
        if target:
            self.autostart_hint.setText(f"自动启动目标：{target}")
        else:
            self.autostart_hint.setText("自动启动目标：未指定")

    def _on_autostart_changed(self, checked: bool) -> None:
        enabled = bool(checked)
        self.settings.set("tunnel.auto_start_enabled", enabled)
        target = self._selected_name or str(self.settings.get("tunnel.last_selected") or "")
        self.settings.set("tunnel.autostart_tunnel", target if enabled else None)
        self._update_autostart_hint()
        self._log("info", "已更新自动启动设置")

    def _apply_autostart_if_needed(self) -> None:
        if not self.autostart_checkbox.isChecked():
            return
        target = str(self.settings.get("tunnel.autostart_tunnel") or "").strip()
        if not target or self._is_tunnel_running(target):
            self._autostart_consumed = True
            return
        for tunnel in self._tunnels:
            if str(tunnel.get("name") or "") == target:
                self._autostart_consumed = True
                self._pending_select_name = target
                self._apply_filter()
                self._start_tunnel(tunnel)
                return

    def _choose_cloudflared(self) -> None:
        filetypes = self.binary_service.selectable_filetypes()
        filters: list[str] = []
        for label, pattern in filetypes:
            filters.append(f"{label} ({pattern})")
        selected, _ = QFileDialog.getOpenFileName(
            self,
            "选择 cloudflared 可执行文件",
            str(self.project_root),
            ";;".join(filters) or "All Files (*)",
        )
        if not selected:
            return
        self.cloudflared_path = selected
        self.settings.set("cloudflared.path", selected)
        self._refresh_version()
        self.refresh_tunnels(silent=True)
        self._log("info", f"已选择 cloudflared: {selected}")

    def _login(self) -> None:
        path = self._resolve_cloudflared_path(require=True)
        if not path:
            return
        ok, message = self.auth_service.start_login(path)
        self._log("info" if ok else "error", message, status=message)
        self._update_status_tiles()

    def _check_update_cloudflared(self) -> None:
        if self._busy:
            return
        self._set_busy(True, "下载/更新 cloudflared…")

        def worker() -> Any:
            return self.binary_service.download_binary()

        def done(result: Any) -> None:
            self._set_busy(False, "下载完成")
            if result.ok:
                self.cloudflared_path = str(result.target_path)
                self.settings.set("cloudflared.path", self.cloudflared_path)
                self._refresh_version()
                self.refresh_tunnels(silent=True)
                self._log("info", result.message, status=result.message)
            else:
                self._log("error", result.message, status=result.message)

        self._run_background(worker, done)

    def _create_tunnel(self) -> None:
        if self._busy:
            return
        path = self._resolve_cloudflared_path(require=True)
        if not path:
            return

        name, ok = QInputDialog.getText(self, "新建隧道", "输入隧道名称：")
        tunnel_name = name.strip()
        if not ok or not tunnel_name:
            return

        self._set_busy(True, f"创建隧道 {tunnel_name}…")

        def worker() -> TunnelCatalogMutationResult:
            cert_path = self.auth_service.find_origin_cert()
            return self.catalog_service.create_tunnel(path, tunnel_name, cert_path)

        def done(result: TunnelCatalogMutationResult) -> None:
            self._set_busy(False, result.message)
            level = "info" if result.ok else "error"
            self._log(level, result.message, status=result.message)
            if result.detail:
                self._log("info" if result.ok else "warning", result.detail)
            for warning in result.warnings:
                self._log("warning", warning)
            if result.ok:
                self.refresh_tunnels(select_name=tunnel_name, silent=True)

        self._run_background(worker, done)

    def _delete_selected(self) -> None:
        if self._busy:
            return
        tunnel = self._current_tunnel()
        if not tunnel:
            return
        path = self._resolve_cloudflared_path(require=True)
        if not path:
            return

        name = str(tunnel.get("name") or "")
        confirm = QMessageBox.question(
            self,
            "删除隧道",
            f"确认删除隧道 {name}？此操作不可恢复。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        self._set_busy(True, f"删除 {name}…")

        def worker() -> TunnelCatalogMutationResult:
            return self.catalog_service.delete_tunnel(path, name)

        def done(result: TunnelCatalogMutationResult) -> None:
            self._set_busy(False, result.message)
            self._log("info" if result.ok else "error", result.message, status=result.message)
            if result.detail:
                self._log("info" if result.ok else "warning", result.detail)
            for warning in result.warnings:
                self._log("warning", warning)
            self.refresh_tunnels(select_name="", silent=True)

        self._run_background(worker, done)

    def _edit_selected_config(self) -> None:
        tunnel = self._current_tunnel()
        if not tunnel:
            return
        name = str(tunnel.get("name") or "")
        tunnel_id = self._selected_tunnel_id(tunnel)
        if not tunnel_id:
            self._log("warning", f"无法解析隧道 {name} 的 UUID", status="无法打开配置")
            return
        dialog = ConfigEditorDialog(
            self.catalog_service.config_path_for(name),
            name,
            tunnel_id,
            self,
        )
        if dialog.exec():
            self._log("info", f"{name} 配置已保存", status="配置已保存")
            self.refresh_tunnels(select_name=name, silent=True)

    def _diagnose_selected(self) -> None:
        tunnel = self._current_tunnel()
        if not tunnel or self._busy:
            return
        path = self._resolve_cloudflared_path(require=True)
        if not path:
            return

        name = str(tunnel.get("name") or "")
        tunnel_id = self._selected_tunnel_id(tunnel)
        config_path = self.catalog_service.config_path_for(name)
        self._set_busy(True, f"诊断 {name}…")

        def worker() -> list[tuple[str, str | None]]:
            report = self.diagnostics_service.build_report(
                path,
                name,
                tunnel_id,
                config_path,
                self._is_tunnel_running,
            )
            return [(line.text, line.tag) for line in report]

        def done(lines: list[tuple[str, str | None]]) -> None:
            self._set_busy(False, f"诊断完成: {name}")
            dialog = DiagnosticsDialog(name, lines, self)
            dialog.exec()
            self._log("info", f"已完成诊断: {name}", status=f"诊断完成: {name}")

        self._run_background(worker, done)

    def _open_config_dir(self) -> None:
        tunnel = self._current_tunnel()
        if tunnel:
            target = self.catalog_service.config_path_for(str(tunnel.get("name") or "")).parent
        else:
            target = get_tunnels_dir()
        target.mkdir(parents=True, exist_ok=True)
        try:
            if sys.platform.startswith("win"):
                os.startfile(str(target))  # type: ignore[attr-defined]
            else:
                QMessageBox.information(self, "目录路径", str(target))
            self._log("info", f"已打开目录: {target}", status="目录已打开")
        except Exception as exc:
            self._log("warning", f"无法打开目录，路径如下：{target}\n{exc}", status="无法打开目录")

    def _toggle_start_selected(self) -> None:
        if self._busy:
            return
        tunnel = self._current_tunnel()
        if not tunnel:
            return
        name = str(tunnel.get("name") or "")
        if self._is_tunnel_running(name):
            self._stop_tunnel(name)
        else:
            self._start_tunnel(tunnel)

    def _start_tunnel(self, tunnel: dict[str, Any]) -> None:
        path = self._resolve_cloudflared_path(require=True)
        if not path or self._busy:
            return

        name = str(tunnel.get("name") or "")
        tunnel_id = self._selected_tunnel_id(tunnel)
        if not tunnel_id:
            self._log("warning", f"无法解析隧道 {name} 的 UUID", status="启动失败")
            return

        self._set_busy(True, f"启动 {name}…")

        def worker() -> dict[str, Any]:
            if self._supervisor_active and self._supervisor_available:
                payload = self.supervisor_client.start_tunnel_payload(name)
                return self.operation_service.build_supervisor_start_result(name, payload)
            if self._supervisor_active:
                return self.operation_service.build_start_exception_result(
                    name,
                    RuntimeError("守护进程在线，但当前 GUI 无法与其通信。"),
                )

            config_path = self.catalog_service.config_path_for(name)
            log_file = get_persistent_logs_dir() / f"{name}.log"
            return self.lifecycle_service.start_direct_tunnel(
                path,
                name,
                tunnel_id,
                config_path,
                True,
                log_file,
            )

        def done(result: dict[str, Any]) -> None:
            self._set_busy(False, result.get("message") or f"{name} 已处理")
            self._consume_operation_result(result)
            if result.get("ok") and result.get("managed_by") == "gui":
                proc = result.get("proc")
                if proc is not None:
                    self.proc_map[name] = proc
                    try:
                        self.proc_tracker.register(name, int(proc.pid), "qt-gui", mode="manual")
                    except Exception:
                        pass
                    threading.Thread(
                        target=self._pipe_process_output,
                        args=(name, proc),
                        daemon=True,
                    ).start()
            if result.get("ok") and self.autostart_checkbox.isChecked():
                self.settings.set("tunnel.autostart_tunnel", name)
                self._update_autostart_hint()
            self.refresh_tunnels(select_name=name, silent=True)

        self._run_background(worker, done)

    def _stop_tunnel(self, tunnel_name: str) -> None:
        path = self._resolve_cloudflared_path(require=True)
        if not path or self._busy:
            return

        self._set_busy(True, f"停止 {tunnel_name}…")

        def worker() -> dict[str, Any]:
            if self._supervisor_active and self._supervisor_available:
                payload = self.supervisor_client.stop_tunnel_payload(tunnel_name)
                return self.operation_service.build_supervisor_stop_result(tunnel_name, payload)
            if self._supervisor_active:
                return self.operation_service.build_stop_exception_result(
                    tunnel_name,
                    RuntimeError("守护进程在线，但当前 GUI 无法与其通信。"),
                )

            proc = self.proc_map.get(tunnel_name)
            raw = self.lifecycle_service.stop_tunnel(tunnel_name, proc)
            if raw.get("ok"):
                try:
                    self.proc_tracker.unregister(tunnel_name, expected_pid=raw.get("pid"))
                except Exception:
                    pass
            return self.operation_service.build_direct_stop_result(tunnel_name, raw)

        def done(result: dict[str, Any]) -> None:
            self._set_busy(False, result.get("message") or f"{tunnel_name} 已处理")
            self._consume_operation_result(result)
            if result.get("ok"):
                self.proc_map.pop(tunnel_name, None)
                try:
                    self.proc_tracker.unregister(tunnel_name)
                except Exception:
                    pass
            self.refresh_tunnels(select_name=tunnel_name, silent=True)

        self._run_background(worker, done)

    def _consume_operation_result(self, result: dict[str, Any]) -> None:
        ok = bool(result.get("ok"))
        level = "info" if ok else "error"
        for message in result.get("messages", []) or []:
            self._log("info", str(message))
        for warning in result.get("warnings", []) or []:
            self._log("warning", str(warning))
        for entry in result.get("logs", []) or []:
            self._log("info", str(entry))
        detail = str(result.get("detail") or "").strip()
        message = str(result.get("message") or result.get("summary") or "").strip()
        if detail and detail != message:
            self._log("info" if ok else "warning", detail)
        if message:
            self._log(level, message, status=message)

    def _pipe_process_output(self, tunnel_name: str, proc: Any) -> None:
        stdout = getattr(proc, "stdout", None)
        if stdout is None:
            return
        try:
            for line in iter(stdout.readline, ""):
                text = str(line).rstrip()
                if not text:
                    continue
                lower = text.lower()
                if "error" in lower or "failed" in lower:
                    level = "error"
                elif "warning" in lower:
                    level = "warning"
                elif "connected" in lower or "success" in lower:
                    level = "success"
                else:
                    level = "info"
                self._log(level, f"[{tunnel_name}] {text}")
        except Exception:
            pass
        finally:
            try:
                returncode = proc.wait(timeout=0.5)
            except Exception:
                returncode = None
            if returncode not in (None, 0):
                self._log("warning", f"{tunnel_name} 已退出，退出码 {returncode}")
            self.ui_bridge.refresh_requested.emit(tunnel_name)

    def _copy_log(self) -> None:
        text = self.log_view.toPlainText().strip()
        if not text:
            return
        QApplication.clipboard().setText(text)
        self.statusBar().showMessage("日志已复制")

    def _save_log_to_file(self) -> None:
        text = self.log_view.toPlainText().strip()
        if not text:
            return
        default_name = f"cloudflared-log-{datetime.now().strftime('%Y%m%d-%H%M%S')}.log"
        selected, _ = QFileDialog.getSaveFileName(
            self,
            "保存日志",
            str(self.project_root / default_name),
            "Log Files (*.log);;All Files (*)",
        )
        if not selected:
            return
        Path(selected).write_text(text + "\n", encoding="utf-8")
        self.statusBar().showMessage("日志已保存")

    def _clear_log(self) -> None:
        self.log_view.clear()
        self.logger.clear()
        self.statusBar().showMessage("日志已清空")

    def closeEvent(self, event: QCloseEvent) -> None:  # type: ignore[override]
        self._save_window_state()
        self.settings.set("cloudflared.path", self.cloudflared_path)
        keep_running = self.persist_checkbox.isChecked()

        if not keep_running:
            for tunnel_name, proc in list(self.proc_map.items()):
                try:
                    if proc and proc.poll() is None:
                        self.lifecycle_service.stop_tunnel(tunnel_name, proc)
                except Exception:
                    pass
                try:
                    self.proc_tracker.unregister(tunnel_name)
                except Exception:
                    pass
        super().closeEvent(event)


def run_qt_app() -> int:
    app = QApplication.instance()
    owns_app = app is None
    if app is None:
        app = QApplication(sys.argv)

    app.setApplicationName("Cloudflare Tunnel")
    app.setFont(QFont("Segoe UI", 10))

    window = QtTunnelManager()
    window.show()
    if owns_app:
        return app.exec()
    return 0


if __name__ == "__main__":
    raise SystemExit(run_qt_app())
