@echo off
setlocal EnableExtensions

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..") do set "REPO_ROOT=%%~fI"
cd /d "%REPO_ROOT%"

REM Check for --console flag to force console mode (must be the first arg).
set "FORCE_CONSOLE=0"
if /I "%~1"=="--console" (
  set "FORCE_CONSOLE=1"
  shift
)

REM Prefer venv Python to avoid dependency/path issues.
set "PY_EXE="
set "PYW_EXE="

if exist ".venv\Scripts\python.exe" set "PY_EXE=.venv\Scripts\python.exe"
if exist ".venv\Scripts\pythonw.exe" set "PYW_EXE=.venv\Scripts\pythonw.exe"
if "%PY_EXE%"=="" if exist "venv\Scripts\python.exe" set "PY_EXE=venv\Scripts\python.exe"
if "%PYW_EXE%"=="" if exist "venv\Scripts\pythonw.exe" set "PYW_EXE=venv\Scripts\pythonw.exe"

if "%PY_EXE%"=="" (
  where python.exe >nul 2>&1 && set "PY_EXE=python.exe"
)
if "%PYW_EXE%"=="" (
  where pythonw.exe >nul 2>&1 && set "PYW_EXE=pythonw.exe"
)

if "%PY_EXE%"=="" (
  echo [ERROR] Python not found. Please install Python or create .venv.
  pause
  exit /b 1
)

REM Use pythonw.exe for GUI (no console) unless --console is specified
if "%FORCE_CONSOLE%"=="1" (
  "%PY_EXE%" -m app.main %*
) else if not "%PYW_EXE%"=="" (
  "%PYW_EXE%" -m app.main %*
) else (
  "%PY_EXE%" -m app.main %*
)

if errorlevel 1 (
  echo.
  echo [ERROR] Application exited with error code %errorlevel%
  echo Check logs\tunnel_supervisor.log for details.
  pause
)
endlocal
