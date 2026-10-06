#!/usr/bin/env bash
# ============================================================
# HootBot control panel (Linux)
# Opened by the "HootBot Control" desktop icon, or run: ~/HootBot/hootbot-control.sh
# Start/stop/restart ask for your password (sudo).
# ============================================================

SERVICE=hootbot

bold=$'\e[1m'; green=$'\e[32m'; red=$'\e[31m'; yellow=$'\e[33m'; reset=$'\e[0m'

is_playing() {
    # The bot runs ffmpeg while it's playing a song
    local pid
    pid=$(systemctl show -p MainPID --value "$SERVICE")
    [ "$pid" != "0" ] && pgrep -P "$pid" ffmpeg >/dev/null
}

show_status() {
    clear
    echo "${bold}=========== HootBot Control ===========${reset}"
    if systemctl is-active --quiet "$SERVICE"; then
        local since
        since=$(systemctl show -p ActiveEnterTimestamp --value "$SERVICE")
        echo "  Status:  ${green}RUNNING${reset} (since $since)"
        if is_playing; then
            echo "  Music:   ${yellow}playing a song right now${reset}"
        else
            echo "  Music:   idle"
        fi
    else
        echo "  Status:  ${red}STOPPED${reset}"
    fi
    echo "  yt-dlp:  $(~/HootBot/.venv/bin/python -m pip show yt-dlp 2>/dev/null | awk '/^Version:/{print $2}')"
    echo "${bold}=======================================${reset}"
    echo
    echo "  1) Start"
    echo "  2) Stop"
    echo "  3) Restart"
    echo "  4) Watch live log   (Ctrl+C to come back here)"
    echo "  5) Show last 50 log lines"
    echo "  6) Update yt-dlp now"
    echo "  q) Quit (the bot keeps running)"
    echo
}

confirm_if_playing() {
    if is_playing; then
        read -rp "${yellow}A song is playing and will be cut off. Continue? [y/N] ${reset}" ans
        [[ "$ans" =~ ^[Yy]$ ]]
    fi
}

pause() { echo; read -rp "Press Enter to go back to the menu..." _; }

while true; do
    show_status
    read -rp "Choose: " choice
    case "$choice" in
        1) sudo systemctl start "$SERVICE" && echo "${green}Started.${reset}"; pause ;;
        2) confirm_if_playing && sudo systemctl stop "$SERVICE" && echo "${green}Stopped.${reset}"; pause ;;
        3) confirm_if_playing && sudo systemctl restart "$SERVICE" && echo "${green}Restarted.${reset}"; pause ;;
        4) echo "Live log, press Ctrl+C to return to the menu..."; echo
           trap 'true' INT
           journalctl -u "$SERVICE" -f -n 30 -o cat
           trap - INT ;;
        5) journalctl -u "$SERVICE" -n 50 --no-pager -o cat; pause ;;
        6) echo "Updating yt-dlp (the bot restarts only if there's a new version)..."
           sudo systemctl start hootbot-update && journalctl -u hootbot-update -n 3 --no-pager -o cat | grep yt-dlp; pause ;;
        q|Q) exit 0 ;;
        *) ;;
    esac
done
