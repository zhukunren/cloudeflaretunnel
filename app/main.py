from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


APP_DIR = Path(__file__).resolve().parent
REPO_ROOT = APP_DIR.parent
LOCAL_TCL_ROOT = REPO_ROOT / ".local_tcl"


def _ensure_script_import_path() -> None:
    """Support direct script execution like `python app/main.py`."""
    app_dir = str(APP_DIR)
    if app_dir not in sys.path:
        sys.path.append(app_dir)


def _bootstrap_local_tk_runtime() -> None:
    """Mirror Tcl/Tk scripts into the repo so Tk can start on restricted setups."""
    if os.environ.get("TCL_LIBRARY") and os.environ.get("TK_LIBRARY"):
        return

    tcl_dst = LOCAL_TCL_ROOT / "tcl8.6"
    tk_dst = LOCAL_TCL_ROOT / "tk8.6"

    if not tcl_dst.joinpath("init.tcl").exists() or not tk_dst.joinpath("tk.tcl").exists():
        source_root = Path(getattr(sys, "base_prefix", sys.prefix)) / "tcl"
        tcl_src = source_root / "tcl8.6"
        tk_src = source_root / "tk8.6"
        if not tcl_src.exists() or not tk_src.exists():
            return

        LOCAL_TCL_ROOT.mkdir(parents=True, exist_ok=True)
        shutil.copytree(tcl_src, tcl_dst, dirs_exist_ok=True)
        shutil.copytree(tk_src, tk_dst, dirs_exist_ok=True)

    os.environ["TCL_LIBRARY"] = str(tcl_dst)
    os.environ["TK_LIBRARY"] = str(tk_dst)


def _import_run_modern_app():
    try:
        from .modern_gui import run_modern_app
    except Exception:
        _ensure_script_import_path()
        from modern_gui import run_modern_app
    return run_modern_app


def _import_run_qt_app():
    try:
        from .qt_gui import run_qt_app
    except Exception:
        _ensure_script_import_path()
        from qt_gui import run_qt_app
    return run_qt_app


def _import_cleanup_and_monitor():
    try:
        from .utils.process_cleaner import cleanup_on_startup
        from .tunnel_monitor_improved import monitor_tunnel
    except Exception:
        _ensure_script_import_path()
        from utils.process_cleaner import cleanup_on_startup
        from tunnel_monitor_improved import monitor_tunnel
    return cleanup_on_startup, monitor_tunnel


def main() -> int:
    cleanup_on_startup, monitor_tunnel = _import_cleanup_and_monitor()
    args = sys.argv[1:]

    # 如果有隧道名参数，则作为隧道监控脚本运行
    if args and args[0] not in {"--classic", "--tk"}:
        tunnel_name = args[0]
        # 直接启动隧道监控（不执行cleanup，避免与systemd服务冲突）
        monitor_tunnel(tunnel_name)
    else:
        # 否则作为GUI应用运行
        cleanup_on_startup()
        if args and args[0] in {"--classic", "--tk"}:
            _bootstrap_local_tk_runtime()
            run_modern_app = _import_run_modern_app()
            run_modern_app()
            return 0

        try:
            run_qt_app = _import_run_qt_app()
        except (ImportError, ModuleNotFoundError):
            _bootstrap_local_tk_runtime()
            run_modern_app = _import_run_modern_app()
            run_modern_app()
        else:
            return int(run_qt_app() or 0)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
