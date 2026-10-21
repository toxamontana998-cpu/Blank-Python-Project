# Telegram Video Bot

A Telegram bot that accepts HTTPS video links from Instagram, TikTok, YouTube,
and VK. It allows three successful downloads per user per UTC day.

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
