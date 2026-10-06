# Code layout

`main.py` used to hold the whole bot (~3,100 lines). It's now split into the `hootbot/`
package; `main.py` only imports it and starts the bot, so `start.sh`, the systemd
service and the Windows `.bat` files still run `main.py` as before.

| File | What's in it |
|---|---|
| `main.py` | Entry point: imports the package and calls `bot.run()` |
| `hootbot/config.py` | Settings (`FORCE_DOWNLOAD`, `IDLE_TIMEOUT`, ...), `.env` values, logging setup |
| `hootbot/core.py` | The `bot` object, `admin_only` check, `HootContext` (output-channel redirect) |
| `hootbot/music.py` | `MusicBot`: YouTube search, extraction, downloads, cache, playlist loading |
| `hootbot/sources.py` | Audio wrappers: `YTDLSource` (volume), `IntroThenResume`, `ChannelContext` |
| `hootbot/playback.py` | `play_audio`, `play_next`, idle leave, voice reconnect |
| `hootbot/utils.py` | Small helpers (URL checks, one-command-per-message) |
| `hootbot/events.py` | `on_message`, `on_ready`, `on_command_error`, `on_voice_state_update` |
| `hootbot/welcome.py` | The welcome-intro joke and `.welcomeon/.welcomeoff/.welcomestatus` |
| `hootbot/commands/music.py` | `.play`, `.playlist`, `.playnext`, `.more`, `.skip`, `.volume`, ... |
| `hootbot/commands/queue.py` | `.queue`, `.remove`, `.shuffle` |
| `hootbot/commands/admin.py` | `.files`, `.cleanup`, `.debug`, `.checkupdates` (admin only) |
| `hootbot/commands/help.py` | `.help`, `.commands` |
| `hootbot/commands/fun.py` | `.skeet` and its cat facts |

## Notes for editing

- `DEBUG` and `Current_volume` change at runtime, so always use them as
  `config.DEBUG` / `config.Current_volume` (not `from .config import DEBUG`).
- Paths: use `config.BASE_DIR` (the HootBot folder), not `__file__` — modules live one level down.
- A new command goes in the matching `hootbot/commands/*.py` file with `@bot.command(...)`;
  a new command file must be added to `hootbot/commands/__init__.py`.
- The split moved code without changing it (verified by comparing syntax trees), except
  for the import of `playback_finished` inside `MusicBot.create_after_callback`
  (avoids a circular import) and the welcome part of `on_voice_state_update`, which is
  now `welcome.handle_welcome()`.
