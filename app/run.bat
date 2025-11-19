@echo off
REM Cloudflare Tunnel Manager - Windows 快速启动脚本

cd /d "%~dp0"

REM 激活虚拟环境
if exist venv (
    call venv\Scripts\activate.bat
)

REM 启动应用(现代UI)
python -m app.main %*
