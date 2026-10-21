import logging
import os
import sqlite3
import tempfile
from datetime import datetime, timezone
from urllib.parse import urlsplit

import telebot
import yt_dlp


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("video_bot")

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError(
        "Set TELEGRAM_BOT_TOKEN in Replit Secrets before starting the bot."
    )

DAILY_LIMIT = 3
MAX_FILE_SIZE = 49 * 1024 * 1024
DATABASE_PATH = os.environ.get("BOT_DATABASE_PATH", "bot_limits.sqlite3")
ALLOWED_DOMAINS = (
    "instagram.com",
    "tiktok.com",
    "youtube.com",
    "youtu.be",
    "vk.com",
)

bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)


def initialize_database() -> None:
    with sqlite3.connect(DATABASE_PATH, timeout=15) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS daily_usage (
                user_id INTEGER NOT NULL,
                usage_date TEXT NOT NULL,
                count INTEGER NOT NULL CHECK (count >= 0),
                PRIMARY KEY (user_id, usage_date)
            )
            """
        )


def current_usage_date() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def reserve_daily_slot(user_id: int, usage_date: str) -> bool:
    with sqlite3.connect(DATABASE_PATH, timeout=15) as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT count FROM daily_usage WHERE user_id = ? AND usage_date = ?",
            (user_id, usage_date),
        ).fetchone()
        if row and row[0] >= DAILY_LIMIT:
            connection.rollback()
            return False

        connection.execute(
            """
            INSERT INTO daily_usage (user_id, usage_date, count)
            VALUES (?, ?, 1)
            ON CONFLICT (user_id, usage_date)
            DO UPDATE SET count = count + 1
            """,
            (user_id, usage_date),
        )
        return True


def release_daily_slot(user_id: int, usage_date: str) -> None:
    with sqlite3.connect(DATABASE_PATH, timeout=15) as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            """
            UPDATE daily_usage
            SET count = count - 1
            WHERE user_id = ? AND usage_date = ? AND count > 0
            """,
            (user_id, usage_date),
        )
        connection.execute(
            "DELETE FROM daily_usage WHERE user_id = ? AND usage_date = ? AND count = 0",
            (user_id, usage_date),
        )


def is_supported_video_url(url: str) -> bool:
    try:
        parsed = urlsplit(url)
        hostname = (parsed.hostname or "").lower().rstrip(".")
        port = parsed.port
    except ValueError:
        return False

    if (
        parsed.scheme != "https"
        or not hostname
        or parsed.username
        or parsed.password
        or port not in (None, 443)
    ):
        return False

    return any(
        hostname == domain or hostname.endswith(f".{domain}")
        for domain in ALLOWED_DOMAINS
    )


def update_status(chat_id: int, message_id: int, text: str) -> None:
    try:
        bot.edit_message_text(text, chat_id=chat_id, message_id=message_id)
    except Exception:
        logger.warning("Could not update status message in chat %s", chat_id)


@bot.message_handler(commands=["start"])
def start(message: telebot.types.Message) -> None:
    bot.send_message(
        message.chat.id,
        "Привет! Я скачиваю доступные видео по ссылкам из Instagram, TikTok, "
        "YouTube или VK.\n\n"
        "Отправь HTTPS-ссылку на видео. Бесплатный лимит — 3 видео в сутки "
        "(сброс в 00:00 UTC).",
    )


@bot.message_handler(content_types=["text"])
def handle_link(message: telebot.types.Message) -> None:
    url = (message.text or "").strip()
    user_id = message.from_user.id if message.from_user else 0

    if not is_supported_video_url(url):
        bot.reply_to(
            message,
            "Отправь HTTPS-ссылку на видео из Instagram, TikTok, YouTube или VK.",
        )
        return

    usage_date = current_usage_date()
    try:
        reserved = reserve_daily_slot(user_id, usage_date)
    except sqlite3.Error:
        logger.exception("Could not reserve daily download quota")
        bot.reply_to(message, "Не удалось проверить дневной лимит. Попробуй позже.")
        return

    if not reserved:
        bot.reply_to(
            message,
            "Лимит на сегодня исчерпан (3 видео). Он обновится в 00:00 UTC.",
        )
        return

    status_message = bot.reply_to(message, "Скачиваю видео, подожди…")
    try:
        with tempfile.TemporaryDirectory(prefix="telegram-video-") as temp_dir:
            output_template = os.path.join(temp_dir, "%(id)s.%(ext)s")
            ydl_options = {
                "format": "best[ext=mp4]/best",
                "outtmpl": output_template,
                "quiet": True,
                "no_warnings": True,
                "noplaylist": True,
                "max_filesize": MAX_FILE_SIZE,
                "socket_timeout": 20,
                "retries": 1,
            }

            with yt_dlp.YoutubeDL(ydl_options) as downloader:
                info = downloader.extract_info(url, download=True)
                if not info:
                    raise RuntimeError("No video information returned")
                filename = downloader.prepare_filename(info)

            if not os.path.isfile(filename):
                raise FileNotFoundError("Downloaded video file was not found")
            if os.path.getsize(filename) > MAX_FILE_SIZE:
                raise ValueError("Video is too large to send")

            caption = "Готово! Вот доступное видео."
            with open(filename, "rb") as video:
                if filename.lower().endswith(".mp4"):
                    bot.send_video(
                        message.chat.id,
                        video,
                        caption=caption,
                        supports_streaming=True,
                    )
                else:
                    bot.send_document(
                        message.chat.id,
                        video,
                        caption=caption,
                    )

        update_status(
            message.chat.id,
            status_message.message_id,
            "Видео отправлено.",
        )
    except Exception as error:
        release_daily_slot(user_id, usage_date)
        logger.warning(
            "Video request failed for user %s (%s)",
            user_id,
            type(error).__name__,
        )
        update_status(
            message.chat.id,
            status_message.message_id,
            "Не удалось скачать или отправить видео. Проверь ссылку и попробуй позже.",
        )


def main() -> None:
    initialize_database()
    logger.info("Telegram video bot is running")
    bot.infinity_polling(timeout=20, long_polling_timeout=20)


if __name__ == "__main__":
    main()
