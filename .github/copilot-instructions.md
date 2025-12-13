## Repository quick orientation

This repository contains a small Discord music bot implemented in a single Python file: `main.py`.
It uses `discord.ext.commands` for bot commands and `yt_dlp` + FFmpeg for audio extraction and playback.

Key runtime/dependencies (discoverable from `main.py`):
- Python 3.x
- discord.py (or a compatible fork providing `discord` and `discord.ext.commands`)
- yt-dlp
- FFmpeg on PATH (used by `discord.FFmpegPCMAudio`)

## Big-picture architecture / flow
- `main.py` is the single source of truth: it configures bot intents, command prefix (`!`) and the bot client.
- Commands implemented: `!join`, `!leave`, `!play`, `!pause`, `!resume`, `!stop`, `!volume`, `!queue`, `!skeet`.
- Music lifecycle:
  - `!play` extracts info with `yt_dlp` (often via `run_in_executor`) and either plays immediately or queues URLs in `song_queue`.
  - `play_next_in_queue(ctx)` pops the next URL and uses `YTDLSource` + `FFmpegPCMAudio` to play it via the guild's `voice_client`.
  - When the queue empties, a per-guild idle timeout task (`timeout_tasks[guild_id]`) is created which will call `leave(ctx)` after `IDLE_TIMEOUT_SECONDS` of inactivity.

## Project-specific patterns and gotchas (important for edits)
- Single-file project: changes almost always touch `main.py`. Be careful merging responsibilities — there are duplicate or overlapping definitions (for example `ytdl_format_options` and `play_next_in_queue` are re-assigned later). Search `main.py` before editing.
- Global mutable state is used heavily: `song_queue`, `Current_volume`, and `timeout_tasks`. Prefer to keep concurrent modifications guarded when introducing async changes.
- `yt_dlp.extract_info` is run inside `bot.loop.run_in_executor(...)` throughout the code. Maintain this pattern to avoid blocking the event loop.
- `FFmpegPCMAudio` is created with `options`/`before_options` passed through `ffmpeg_options`. Keep those options when changing streaming behavior.
- Sensitive data: a Discord token string appears directly in `main.py`. Do not commit tokens to VCS; prefer using `os.environ['DISCORD_TOKEN']` or a local `.env` when changing code.
- Minor bugs to be aware of (detectable from `main.py`):
  - `Current_volume` is a module-level variable but `YTDLSource.set_volume` assigns to a local variable `Current_volume` (it should use `global` or instance state).
  - `ytdl_format_options` is declared twice; follow the later definition but consider consolidating.
  - `play_next_in_queue` is defined twice in the file; the latter version supersedes the earlier one. Refactor carefully.

## How to run & debug (Windows PowerShell examples)
- Install dependencies (example):
```powershell
python -m pip install -U yt-dlp discord.py
# Ensure ffmpeg is installed and available on PATH (download from ffmpeg.org)
```
- Run the bot (replace token handling before committing):
```powershell
$env:DISCORD_TOKEN = 'your-token-here'
python main.py
```
Note: `main.py` currently calls `bot.run(TOKEN)` directly. Prefer editing the file to read from `os.environ['DISCORD_TOKEN']` before running in non-test edits.

## Editing guidance for AI agents
- When changing playback logic, preserve non-blocking behaviour: keep `ytdl.extract_info` inside `run_in_executor` and create FFmpeg sources similarly.
- When touching queue/timeout logic, update `timeout_tasks` consistently per-guild. Tests/changes should ensure that cancelling/creating tasks uses the same guild id key.
- Avoid introducing synchronous blocking calls in command handlers. Use `bot.loop.create_task(...)` for background work (this repo uses that pattern for playlist queuing and play-next logic).

## Files to inspect when making changes
- `main.py` — primary file for all behaviors. Search it for `song_queue`, `timeout_tasks`, `YTDLSource`, and both `play_next_in_queue` definitions.

## Post-edit checklist for PRs
- Verify no secrets (tokens) are left in `main.py`.
- Run the bot locally and exercise these commands in a test server: `!join`, `!play <url>`, `!queue`, `!volume 50`, `!stop`, `!leave`.
- Confirm FFmpeg is on PATH and streaming works for both single videos and playlists.

If anything above is unclear or you'd like this file to include additional examples (fix PR snippets, test harness suggestions, or an explicit requirements.txt), tell me which section to expand.
