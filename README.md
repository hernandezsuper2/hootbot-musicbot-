HootBot (Discord music bot)

Local setup (Windows PowerShell)

1) Create a local .env file from the example and set your token:

```powershell
cd "C:\Users\herna\Desktop\HootBot"
Copy-Item .env.example .env
(notepad .env) # paste your real token after DISCORD_TOKEN=
```

Or set the environment variable for the current session:

```powershell
$env:DISCORD_TOKEN = 'YOUR_REAL_TOKEN_HERE'
python main.py
```

2) (Optional) Install python-dotenv so the repo will auto-load .env.

```powershell
pip install python-dotenv
```

3) Run the bot:

```powershell
python main.py
```

Security note: Never commit the real `.env` or tokens into source control. If you believe a token has been leaked, rotate it immediately in the Discord Developer Portal.
