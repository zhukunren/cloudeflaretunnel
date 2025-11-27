try:
    # Package mode: python -m app.main
    from .modern_gui import run_modern_app
    from .utils.process_cleaner import cleanup_on_startup
    from .tunnel_monitor_improved import monitor_tunnel
except Exception:
    # Script mode: python app/main.py or python path\to\app\main.py
    import os
    import sys
    sys.path.append(os.path.dirname(__file__))
    from modern_gui import run_modern_app
    from utils.process_cleaner import cleanup_on_startup
    from tunnel_monitor_improved import monitor_tunnel


if __name__ == "__main__":
    import sys

    # 如果有隧道名参数，则作为隧道监控脚本运行
    if len(sys.argv) > 1:
        tunnel_name = sys.argv[1]
        # 直接启动隧道监控（不执行cleanup，避免与systemd服务冲突）
        monitor_tunnel(tunnel_name)
    else:
        # 否则作为GUI应用运行
        # 先执行进程清理，然后启动GUI
        cleanup_on_startup()
        run_modern_app()
