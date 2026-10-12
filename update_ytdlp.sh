#!/usr/bin/env bash
# Updates yt-dlp and its JS challenge solver (yt-dlp-ejs) in HootBot's venv;
# restarts the bot only if either version changed.
# Run by hootbot-update.timer (daily). Runs as root, does pip work as the bot user.
# Tracks nightly builds (--pre): YouTube changes faster than stable releases, and
# on 2026-10-12 stable 2026.8.19 got intermittent 403s on downloads that nightly did not.
set -e
BOT_USER=roy-hernandez
PY=/home/roy-hernandez/HootBot/.venv/bin/python
ver() { runuser -u "$BOT_USER" -- "$PY" -m pip show yt-dlp yt-dlp-ejs 2>/dev/null | awk '/^Name:/{n=$2} /^Version:/{printf "%s %s ", n, $2}'; }

before=$(ver)
runuser -u "$BOT_USER" -- "$PY" -m pip install -q --upgrade --pre yt-dlp yt-dlp-ejs
after=$(ver)

if [ "$before" != "$after" ]; then
    echo "yt-dlp updated $before -> $after, restarting hootbot"
    systemctl try-restart hootbot
else
    echo "yt-dlp already up to date ($after)"
fi
