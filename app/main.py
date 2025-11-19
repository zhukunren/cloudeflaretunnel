try:
    # Package mode: python -m app.main
    from .gui import run_app
    from .modern_gui import run_modern_app
except Exception:
    # Script mode: python app/main.py or python path\to\app\main.py
    import os
    import sys
    sys.path.append(os.path.dirname(__file__))
    from gui import run_app
    from modern_gui import run_modern_app


if __name__ == "__main__":
    import sys

    args = set(sys.argv[1:])
    force_modern = any(flag in args for flag in ("--modern", "-m"))
    force_classic = any(flag in args for flag in ("--classic", "-c"))

    if force_classic and force_modern:
        print("无法同时指定 --modern 与 --classic，默认使用现代界面。")

    if force_classic and not force_modern:
        run_app()
    else:
        # 默认使用现代UI；如需经典UI运行: python main.py --classic
        run_modern_app()
