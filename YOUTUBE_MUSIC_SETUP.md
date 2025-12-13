# YouTube Music Premium Setup Guide

Your bot now supports YouTube Music Premium! Follow these steps to authenticate:

## Step 1: Install a Cookie Exporter Extension

### For Chrome/Edge:
1. Go to Chrome Web Store
2. Search for "Get cookies.txt LOCALLY"
3. Install the extension

### For Firefox:
1. Go to Firefox Add-ons
2. Search for "cookies.txt"
3. Install the extension

## Step 2: Export Your Cookies

1. Open your browser and go to: https://music.youtube.com
2. **Make sure you're logged in** to your YouTube Premium/Music account
3. Click the cookie extension icon in your toolbar
4. Click "Export" or "Download" to save `cookies.txt`

## Step 3: Save Cookies to Bot Folder

1. Save the downloaded `cookies.txt` file to:
   ```
   C:\Users\herna\Desktop\HootBot\cookies.txt
   ```
2. Make sure the filename is exactly `cookies.txt` (not `cookies.txt.txt`)

## Step 4: Restart Your Bot

1. Stop the bot (Ctrl+C)
2. Start it again: `python main.py`
3. Look for this message in the console:
   ```
   ✅ Found cookies.txt - YouTube Premium/Music features enabled!
   ```

## Step 5: Test It!

Try your YouTube Music playlist again:
```
!playlist https://music.youtube.com/playlist?list=PL1KWG1zabUhjc9XnzoMTxsAgDHXlkzTCQ
```

## Troubleshooting

**"No cookies.txt found" message:**
- Make sure the file is in the same folder as `main.py`
- Check the filename is exactly `cookies.txt`

**Still getting "Video unavailable" errors:**
- Your cookies may have expired - export them again
- Make sure you were logged in to YouTube Music when exporting
- Try updating yt-dlp: `pip install -U yt-dlp`

**Cookies expire regularly:**
- YouTube cookies typically expire after a few weeks
- You'll need to re-export them when they expire
- The bot will still work for regular YouTube videos without cookies

## Security Note

⚠️ **Keep your `cookies.txt` file private!** 
- Don't share it with anyone
- Don't commit it to git/GitHub
- It contains your login session information

## What This Enables

With cookies, you can access:
- ✅ YouTube Music playlists
- ✅ Premium-only content
- ✅ Age-restricted videos
- ✅ Region-restricted content (if available in your region)
- ✅ Member-only content you have access to
