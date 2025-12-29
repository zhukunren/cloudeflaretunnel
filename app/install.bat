@echo off
REM Cloudflare Tunnel Manager - Windows 快速安装脚本

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..") do set "REPO_ROOT=%%~fI"
cd /d "%REPO_ROOT%"

echo ================================
echo Cloudflare Tunnel Manager 安装
echo ================================
echo.

REM 检查Python
echo 1. 检查Python版本...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo 错误: 未找到Python
    echo 请从 https://www.python.org/downloads/ 下载安装Python 3.8+
    pause
    exit /b 1
)
python --version
echo ✓ Python 已安装

REM 创建虚拟环境
echo.
echo 2. 创建虚拟环境...
set "VENV_DIR=.venv"
if exist "%VENV_DIR%" (
    echo 虚拟环境已存在,跳过创建
) else (
    python -m venv "%VENV_DIR%"
    echo ✓ 虚拟环境创建成功
)

REM 激活虚拟环境
echo.
echo 3. 激活虚拟环境...
call "%VENV_DIR%\Scripts\activate.bat"
echo ✓ 虚拟环境已激活

REM 升级pip
echo.
echo 4. 升级pip...
python -m pip install --upgrade pip >nul 2>&1
echo ✓ pip 已升级

REM 安装依赖
echo.
echo 5. 安装依赖...
pip install -r app\requirements.txt
echo ✓ 依赖安装完成

REM 检查cloudflared
echo.
echo 6. 检查cloudflared...
if exist "cloudflared.exe" (
    cloudflared.exe --version
    echo ✓ cloudflared 已找到
) else (
    echo ⚠ cloudflared.exe 未找到
    echo   请下载: https://github.com/cloudflare/cloudflared/releases
    echo   或在应用内点击'📁'图标选择路径
)

REM 创建必要目录
echo.
echo 7. 创建目录结构...
if not exist config mkdir config
if not exist logs mkdir logs
if not exist tunnels mkdir tunnels
echo ✓ 目录创建完成

REM 完成
echo.
echo ================================
echo ✓ 安装完成!
echo ================================
echo.
echo 启动应用:
echo   python -m app.main          # 现代UI
echo   python -m app.main --classic # 经典UI
echo.
echo 查看文档:
echo   type README.md                   # 项目说明
echo   type docs\TROUBLESHOOTING.md     # 故障排查
echo.
pause
