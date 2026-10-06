# HootBot Speed Optimizations

## Original problem (December 2025)
- ~25-second delay from `.play` to audio
- Each song was extracted twice (once for the title, again for playback)
- Slow download fallback logic on top of that

## What fixed it

### 1. Single-pass extraction
- `.play` does one full extraction with `extract_info_fast()`
- The info is cached on the `QueueEntry`, and `play_audio` reuses it
- 1 extraction per song instead of 2

### 2. Two yt-dlp instances
- **ytdl_fast**: minimal extraction (5s timeout, 1 retry, first playlist item only)
- **ytdl**: standard instance, used for downloads and as a fallback when fast extraction fails

### 3. Info cache
- Extracted info is cached for `CACHE_DURATION` (5 minutes)
- Expired entries are pruned, and the cache is capped at 200 entries so memory stays bounded on a 24/7 server

### 4. Background preloading
- While a song plays, the next song in the queue is extracted and (with `FORCE_DOWNLOAD`) downloaded in the background
- Only the first song of a session waits for its download; later songs start immediately

## Current settings

```python
FORCE_DOWNLOAD = True             # Download every song before playing it
FORCE_DOWNLOAD_FRAGMENTED = True  # Also download fragmented (DASH/m3u8) formats
ULTRA_FAST = True                 # Use the ytdl_fast extraction path
CACHE_DURATION = 300              # Seconds to keep extracted info
```

## Why FORCE_DOWNLOAD stays on

Note: earlier versions of this doc said `FORCE_DOWNLOAD = False`. That was never the
committed setting; it has been `True` since the first commit.

Measured on the Linux server (October 2026):

| Step | Time |
|---|---|
| Extraction (needed either way) | ~1.2s |
| Streaming: time to first audio | ~0.2s |
| Downloading: full download | ~2.1s |

The old Windows log agrees: across 371 downloads, median 2s, p90 3s.

- **Cost of downloading:** ~2 extra seconds, and only on the first song. Preloading hides it for the rest of the queue.
- **Benefit:** a downloaded file always plays to the end. Streamed YouTube URLs can expire, get throttled or return 403 mid-song, which cuts the song off.
- The original reason (fragmented formats starting mid-song) hasn't shown up recently (0 fragmented formats in the last 372 plays), but downloading costs so little that streaming isn't worth the risk.

Possible small win if the first-song delay ever matters: `download_audio` re-runs extraction
even though the info is already cached. Reusing it would cut the first-song wait to ~1s.

## Playback path

1. Use cached info from the queue entry, or extract now (fast path, falling back to standard extraction)
2. Pick the best audio format (`select_format`)
3. Use the preloaded file if there is one, otherwise download
4. Play the file with FFmpeg; it is deleted when the song finishes
5. Start preloading the next song

Streaming is still used if `FORCE_DOWNLOAD` is turned off and the format isn't fragmented.

## Monitoring

Live logs: `journalctl -u hootbot -f` (also written to `hootsbot.log`).

```
Fast extraction complete for: <title>   # extraction succeeded
Using cached info for <url>             # cache hit
Using pre-downloaded file: <path>       # preload worked, instant start
Download successful: <path> (<bytes>)   # download path
Streaming from URL: <title>             # only when FORCE_DOWNLOAD is off
```

## Troubleshooting

- **Songs suddenly fail / 403 errors:** YouTube changed something. yt-dlp updates daily via
  `hootbot-update.timer`; to update right now, run `sudo systemctl start hootbot-update`.
- **Need more detail:** `.debug on` (admin only) for verbose logs.
- **FFmpeg missing:** `sudo apt install ffmpeg`.
