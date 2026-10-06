# ============================================================================
# HootBot - Discord Music Bot
# ============================================================================
# A high-performance Discord music bot with YouTube integration
# Features: Queue management, playlist support, fast playback, auto-cleanup
# ============================================================================
# The code lives in the hootbot/ package; this file just starts it.
# ============================================================================
from hootbot.config import TOKEN, logger
from hootbot.core import bot
import hootbot.commands  # noqa: F401  (registers commands)
import hootbot.events    # noqa: F401  (registers event handlers)
import hootbot.welcome   # noqa: F401  (registers .welcomeon/.welcomeoff/.welcomestatus)

if __name__ == '__main__':
    print('Starting HootBot...')
    try:
        bot.run(TOKEN)
    except Exception as e:
        print(f'Bot failed to start: {e}')
        logger.error(f'Startup failed: {e}')
