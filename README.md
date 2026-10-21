# Telegram Video Bot

A Telegram bot that accepts HTTPS video links from Instagram, TikTok, YouTube,
and VK. Instagram links are resolved through the FastSaver API; other supported
platforms continue to use yt-dlp. The bot allows three successful downloads per
user per UTC day.

Set `FASTSAVER_API_KEY` in Replit Secrets to use Instagram downloads. FastSaver
supports public media and may consume API credits per request.

## Setup

```bash
uv sync
uv run python main.py
```

Set `TELEGRAM_BOT_TOKEN` as a Replit Secret before starting the bot. Never put
the token in source code. The bot stores daily usage counts in
`bot_limits.sqlite3`.

Only send links to videos you have permission to download. The bot downloads an
available source file; it does not remove watermarks.
