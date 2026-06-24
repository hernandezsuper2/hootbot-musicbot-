@echo off
:: ============================================================
:: HootBot - First-time Windows setup
:: Run this ONCE on the server laptop before starting the bot.
:: ============================================================
setlocal enabledelayedexpansion

echo === HootBot Setup ===
echo.

:: --- Python check ---
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Download and install Python 3.11+ from https://www.python.org/downloads/
    echo         Make sure to check "Add Python to PATH" during install.
    pause & exit /b 1
)
python --version

:: --- Node.js check (needed by yt-dlp for YouTube) ---
node --version >nul 2>&1
if errorlevel 1 (
    echo [WARNING] Node.js not found. yt-dlp may fail on some YouTube videos.
    echo           Install from https://nodejs.org/ then re-run this script.
) else (
    echo Node.js found: & node --version
)

:: --- ffmpeg check ---
ffmpeg -version >nul 2>&1
if errorlevel 1 (
    echo [WARNING] ffmpeg not found on PATH.
    echo           Install via winget:  winget install --id Gyan.FFmpeg -e
    echo           Or download from https://ffmpeg.org/download.html and add to PATH.
) else (
    echo ffmpeg found.
)

:: --- Create virtual environment if missing ---
if not exist ".venv\Scripts\python.exe" (
    echo.
    echo Creating virtual environment...
    python -m venv .venv
    if errorlevel 1 ( echo [ERROR] Failed to create venv. & pause & exit /b 1 )
)

:: --- Install / upgrade dependencies ---
echo.
echo Installing Python dependencies...
.venv\Scripts\python.exe -m pip install --upgrade pip -q
.venv\Scripts\pip install -r requirements.txt
if errorlevel 1 ( echo [ERROR] pip install failed. & pause & exit /b 1 )

:: --- Ensure .env exists ---
if not exist ".env" (
    echo.
    echo [ACTION REQUIRED] No .env file found. Creating from template...
    copy .env.example .env
    echo Edit .env and paste your Discord bot token, then re-run start.bat.
)

:: --- Create downloads and intros folders ---
if not exist "downloads" mkdir downloads
if not exist "intros"    mkdir intros

echo.
echo === Setup complete! ===
echo Next steps:
echo   1. Edit .env and set DISCORD_TOKEN=your_token_here
echo   2. Run start.bat to launch the bot
echo   3. (Optional) Run install_service.bat to auto-start on boot
echo.
pause
