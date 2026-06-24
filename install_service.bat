@echo off
:: ============================================================
:: HootBot - Install as a Windows Service (auto-starts on boot)
:: Requires NSSM: https://nssm.cc/download
:: Run as Administrator.
:: ============================================================
cd /d "%~dp0"

:: Check for admin
net session >nul 2>&1
if errorlevel 1 (
    echo [ERROR] This script must be run as Administrator.
    echo Right-click install_service.bat and choose "Run as administrator".
    pause & exit /b 1
)

:: Check for NSSM
where nssm >nul 2>&1
if errorlevel 1 (
    echo [ERROR] nssm.exe not found on PATH.
    echo.
    echo  1. Download NSSM from https://nssm.cc/download
    echo  2. Extract nssm.exe (from win64 folder) to C:\Windows\System32\
    echo  3. Re-run this script as Administrator.
    pause & exit /b 1
)

set SERVICE_NAME=HootBot
set BOT_DIR=%~dp0
set PYTHON=%BOT_DIR%.venv\Scripts\python.exe
set SCRIPT=%BOT_DIR%main.py

echo Installing HootBot as Windows service "%SERVICE_NAME%"...

nssm install %SERVICE_NAME% "%PYTHON%" "%SCRIPT%"
nssm set %SERVICE_NAME% AppDirectory "%BOT_DIR%"
nssm set %SERVICE_NAME% DisplayName "HootBot Discord Music Bot"
nssm set %SERVICE_NAME% Description "HootBot - Discord music bot. Managed by NSSM."
nssm set %SERVICE_NAME% Start SERVICE_AUTO_START
nssm set %SERVICE_NAME% AppStdout "%BOT_DIR%service_stdout.log"
nssm set %SERVICE_NAME% AppStderr "%BOT_DIR%service_stderr.log"
nssm set %SERVICE_NAME% AppRotateFiles 1
nssm set %SERVICE_NAME% AppRotateBytes 5242880

echo.
echo Starting service...
nssm start %SERVICE_NAME%

echo.
echo === Done! ===
echo HootBot is now running as a Windows service and will start automatically on boot.
echo.
echo Useful commands:
echo   nssm status HootBot        -- check if running
echo   nssm restart HootBot       -- restart
echo   nssm stop HootBot          -- stop
echo   nssm edit HootBot          -- open GUI editor
echo   uninstall_service.bat      -- remove the service completely
echo.
pause
