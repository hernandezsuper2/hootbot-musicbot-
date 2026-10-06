"""Settings, .env values and logging setup."""
import os
import sys
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


# Load environment variables
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Absolute path to the directory containing this file — used for all relative paths below.
BASE_DIR = Path(__file__).resolve().parent.parent

# Ensure Node.js is on PATH so yt-dlp can solve YouTube's n-challenge (Windows only).
# Override the default location via NODEJS_PATH env var if Node is installed elsewhere.
if sys.platform == "win32":
    _nodejs_path = os.environ.get("NODEJS_PATH", r"C:\Program Files\nodejs")
    if _nodejs_path not in os.environ.get("PATH", ""):
        os.environ["PATH"] = _nodejs_path + os.pathsep + os.environ.get("PATH", "")

# ============================================================================
# CONFIGURATION
# ============================================================================

# Debug & Logging
DEBUG = True  # Enable debug logging to diagnose issues

# Performance Settings
IDLE_TIMEOUT = 30  # Seconds before bot leaves due to inactivity
ULTRA_FAST = True  # Skip all non-essential extraction steps
CACHE_DURATION = 300  # Cache stream URLs for 5 minutes (seconds)
INFO_REUSE_MAX_AGE = 1800  # Download from already-extracted info if it's newer than this (YouTube URLs expire after ~6h)

# Download Settings
FORCE_DOWNLOAD = True  # Always download to ensure songs start at 0:00 (slower but reliable)
FORCE_DOWNLOAD_FRAGMENTED = True  # Download fragmented formats to ensure proper start
DOWNLOAD_FOLDER = str(BASE_DIR / "downloads")

# Audio Settings
Current_volume = 0.1  # Default volume (10%)

# Discord Bot Token
TOKEN = os.environ.get('DISCORD_TOKEN', 'YOUR_TOKEN_HERE')

def _env_id(name):
    """A single Discord ID from the environment (.env), or None if unset."""
    value = os.environ.get(name, '').strip()
    return int(value) if value else None

def _env_ids(name):
    """Comma-separated Discord IDs from the environment (.env), as a set."""
    return {int(part) for part in os.environ.get(name, '').replace(' ', '').split(',') if part}

# Server-specific IDs and names live in .env (see .env.example). Anything unset is disabled.
TRUSTED_BOTS = _env_ids('TRUSTED_BOT_IDS')                # Bots allowed to send commands (e.g. OpenClaw)
BOT_OUTPUT_CHANNEL_ID = _env_id('BOT_OUTPUT_CHANNEL_ID')  # If set, all responses go to this text channel
SKEET_USER_ID = _env_id('SKEET_USER_ID')                  # User the .skeet command is aimed at

# Welcome sound: plays when WELCOME_USER_ID joins WELCOME_CHANNEL_NAME (and .welcomeon is set)
WELCOME_USER_ID = _env_id('WELCOME_USER_ID')
WELCOME_CHANNEL_NAME = os.environ.get('WELCOME_CHANNEL_NAME', '')
WELCOME_SOUND_FILE = str(BASE_DIR / "intros" / os.environ.get('WELCOME_SOUND', ''))

# ============================================================================
# LOGGING SETUP
# ============================================================================
# Reconfigure stderr to UTF-8 so emoji/unicode in log messages don't crash on
# Windows terminals that default to cp1252 (e.g. the '✅' UnicodeEncodeError).
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')
stream_handler = logging.StreamHandler()
stream_handler.stream = open(stream_handler.stream.fileno(), mode='w', encoding='utf-8', buffering=1)
stream_handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s: %(message)s'))
logging.basicConfig(level=logging.INFO, handlers=[stream_handler])
file_handler = RotatingFileHandler('hootsbot.log', maxBytes=5*1024*1024, backupCount=3, encoding='utf-8')
file_handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s'))
logging.getLogger().addHandler(file_handler)
logger = logging.getLogger('hootsbot')
