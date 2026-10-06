#!/usr/bin/env bash
# Updates yt-dlp in HootBot's venv; restarts the bot only if the version changed.
# Run by hootbot-update.timer (daily). Runs as root, does pip work as the bot user.
set -e
BOT_USER=roy-hernandez
PY=/home/roy-hernandez/HootBot/.venv/bin/python
ver() { runuser -u "$BOT_USER" -- "$PY" -m pip show yt-dlp 2>/dev/null | awk '/^Version:/{print $2}'; }

before=$(ver)
runuser -u "$BOT_USER" -- "$PY" -m pip install -q --upgrade yt-dlp
after=$(ver)

if [ "$before" != "$after" ]; then
    echo "yt-dlp updated $before -> $after, restarting hootbot"
    systemctl try-restart hootbot
else
    echo "yt-dlp already up to date ($after)"
fi
