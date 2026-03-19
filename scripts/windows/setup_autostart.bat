@echo off
setlocal EnableExtensions EnableDelayedExpansion

rem ------------------------------------------------------------
rem Location: scripts/windows/setup_autostart.bat (repo root)
rem Windows autostart installer for this project.
rem Tries Scheduled Task first, then falls back to HKCU Run.
rem ------------------------------------------------------------

set "ACTION=%~1"
set "TARGET=%~2"
set "TUNNEL_NAME=%~3"

if "%ACTION%"=="" goto usage
if "%TARGET%"=="" goto usage

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..\..") do set "REPO_ROOT=%%~fI"

if not exist "%REPO_ROOT%\app\main.py" (
  echo [ERROR] Cannot locate repo root from: %SCRIPT_DIR%
  echo         Expected: %REPO_ROOT%\app\main.py
  exit /b 1
)

call :resolve_python "%REPO_ROOT%"
if "%PY_EXE%"=="" (
  echo [ERROR] Failed to resolve Python interpreter.
  exit /b 1
)

call :select_target "%TARGET%" "%ACTION%" "%TUNNEL_NAME%"
if errorlevel 1 goto usage

if /I "%ACTION%"=="install" goto do_install
if /I "%ACTION%"=="uninstall" goto do_uninstall
if /I "%ACTION%"=="status" goto do_status
goto usage

:do_install
rem Scheduled Tasks are commonly blocked by policy; Registry Run (HKCU) is the most compatible option.
call :install_run
if errorlevel 1 (
  echo [ERROR] Failed to create Registry Run entry: %NAME%
  exit /b 1
)
echo [OK] Installed autostart (Registry Run): %NAME%
exit /b 0

:do_uninstall
call :uninstall_schtasks
call :uninstall_run
echo [OK] Removed autostart (Scheduled Task / Registry): %NAME%
exit /b 0

:do_status
call :status_schtasks
if not errorlevel 1 exit /b 0
call :status_run
if not errorlevel 1 exit /b 0
echo [INFO] Autostart not installed: %NAME%
exit /b 1

:resolve_python
set "PY_EXE="
set "ROOT=%~1"

rem Prefer pythonw.exe to avoid a console window.
if exist "%ROOT%\.venv\Scripts\pythonw.exe" set "PY_EXE=%ROOT%\.venv\Scripts\pythonw.exe"
if "%PY_EXE%"=="" if exist "%ROOT%\.venv\Scripts\python.exe" set "PY_EXE=%ROOT%\.venv\Scripts\python.exe"
if "%PY_EXE%"=="" if exist "%ROOT%\venv\Scripts\pythonw.exe" set "PY_EXE=%ROOT%\venv\Scripts\pythonw.exe"
if "%PY_EXE%"=="" if exist "%ROOT%\venv\Scripts\python.exe" set "PY_EXE=%ROOT%\venv\Scripts\python.exe"
if "%PY_EXE%"=="" set "PY_EXE=pythonw.exe"
exit /b 0

:select_target
set "NAME="
set "PY_SCRIPT="
set "PY_ARGS="

if /I "%~1"=="supervisor" (
  set "NAME=CloudflareTunnelSupervisor"
  set "PY_SCRIPT=%REPO_ROOT%\app\tunnel_supervisor.py"
  set "PY_ARGS=watch --interval 30"
  exit /b 0
)

if /I "%~1"=="gui" (
  set "NAME=CloudflareTunnelManagerGUI"
  set "PY_SCRIPT=%REPO_ROOT%\app\main.py"
  set "PY_ARGS="
  exit /b 0
)

if /I "%~1"=="monitor" (
  set "NAME=CloudflareTunnelMonitor"
  set "PY_SCRIPT=%REPO_ROOT%\app\main.py"
  if /I "%~2"=="install" (
    if "%~3"=="" (
      echo [ERROR] Missing tunnel name.
      echo         Example: %~nx0 install monitor my-tunnel
      exit /b 2
    )
    set "PY_ARGS=%~3"
  )
  exit /b 0
)

exit /b 1

:install_schtasks
rem Note: this variant avoids nested quoting; it requires no spaces in PY_EXE/PY_SCRIPT.
set "TR_CMD=%PY_EXE% %PY_SCRIPT%"
if not "%PY_ARGS%"=="" set "TR_CMD=%TR_CMD% %PY_ARGS%"
schtasks /Create /F /TN "%NAME%" /SC ONLOGON /RL LIMITED /TR "%TR_CMD%" >nul 2>&1
exit /b %errorlevel%

:uninstall_schtasks
schtasks /Delete /F /TN "%NAME%" >nul 2>&1
exit /b 0

:install_run
rem Build the command string for registry
set "REG_CMD=\"%PY_EXE%\" \"%PY_SCRIPT%\""
if not "%PY_ARGS%"=="" set "REG_CMD=%REG_CMD% %PY_ARGS%"
rem Use reg add directly (handles Unicode paths better than PowerShell param passing)
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "%NAME%" /t REG_SZ /d "%REG_CMD%" /f >nul 2>&1
exit /b %errorlevel%

:uninstall_run
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "%NAME%" /f >nul 2>&1
exit /b 0

:status_schtasks
schtasks /Query /TN "%NAME%" >nul 2>&1
if errorlevel 1 exit /b 1
echo [OK] Scheduled Task installed: %NAME%
schtasks /Query /TN "%NAME%"
exit /b 0

:status_run
reg query "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "%NAME%" >nul 2>&1
if errorlevel 1 exit /b 1
echo [OK] Registry Run entry installed: %NAME%
reg query "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "%NAME%"
exit /b 0

:usage
echo Usage:
echo   %~nx0 install supervisor
echo   %~nx0 install gui
echo   %~nx0 install monitor ^<tunnel_name^>
echo.
echo   %~nx0 uninstall supervisor
echo   %~nx0 uninstall gui
echo   %~nx0 uninstall monitor
echo.
echo   %~nx0 status supervisor
echo   %~nx0 status gui
echo   %~nx0 status monitor
exit /b 2
