@echo off
:: ============================================================
:: HootBot - Start the bot
:: Double-click this to run the bot in a console window.
:: The window must stay open while the bot is running.
:: For always-on background service use install_service.bat.
:: ============================================================
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Virtual environment not found. Run setup_windows.bat first.
    pause & exit /b 1
)

if not exist ".env" (
    echo [ERROR] .env file missing. Copy .env.example to .env and set DISCORD_TOKEN.
    pause & exit /b 1
)

echo Starting HootBot... (close this window to stop)
.venv\Scripts\python.exe main.py
echo.
echo Bot stopped.
pause
