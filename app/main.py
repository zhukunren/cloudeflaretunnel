try:
    # Package mode: python -m app.main
    from .modern_gui import run_modern_app
except Exception:
    # Script mode: python app/main.py or python path\to\app\main.py
    import os
    import sys
    sys.path.append(os.path.dirname(__file__))
    from modern_gui import run_modern_app


if __name__ == "__main__":
    # 启动现代化 GUI
    run_modern_app()
