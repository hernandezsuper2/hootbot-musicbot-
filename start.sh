#!/usr/bin/env bash
# ============================================================
# HootBot - Linux launcher
# Used after the laptop wipe + Linux install.
# Run manually or let systemd call it (see hootbot.service).
# ============================================================
set -e
cd "$(dirname "$0")"

if [ ! -f ".venv/bin/python" ]; then
    echo "[ERROR] Virtual environment not found. Run:"
    echo "  python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
    exit 1
fi

if [ ! -f ".env" ]; then
    echo "[ERROR] .env missing. Copy .env.example to .env and set DISCORD_TOKEN."
    exit 1
fi

exec .venv/bin/python main.py
