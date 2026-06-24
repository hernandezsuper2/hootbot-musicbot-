@echo off
:: ============================================================
:: HootBot - Remove Windows Service
:: Run as Administrator.
:: ============================================================
net session >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Run as Administrator.
    pause & exit /b 1
)

where nssm >nul 2>&1
if errorlevel 1 ( echo [ERROR] nssm not found. & pause & exit /b 1 )

set SERVICE_NAME=HootBot
echo Stopping and removing service "%SERVICE_NAME%"...
nssm stop %SERVICE_NAME%
nssm remove %SERVICE_NAME% confirm
echo Service removed.
pause
