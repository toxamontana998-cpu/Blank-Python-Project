import os
import threading
from flask import Flask
import logging
import os
import re
import sqlite3
import tempfile
import io
import json
from datetime import datetime, timezone
from urllib.parse import quote, urlsplit

import telebot
import requests
import yt_dlp
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is alive!"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("video_bot")

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
FASTSAVER_API_KEY = os.environ.get("FASTSAVER_API_KEY")
if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError(
        "Set TELEGRAM_BOT_TOKEN in Replit Secrets before starting the bot."
    )

DAILY_LIMIT = 3
MAX_FILE_SIZE = 49 * 1024 * 1024
DATABASE_PATH = os.environ.get("BOT_DATABASE_PATH", "bot_limits.sqlite3")
FASTSAVER_API_URL = "https://api.fastsaver.io/v1/fetch"
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
ALLOWED_DOMAINS = (
    "instagram.com",
    "tiktok.com",
    "youtube.com",
    "youtu.be",
    "vk.com",
)
VIDEO_EXTENSIONS = {".mp4", ".m4v", ".mov", ".webm", ".mkv"}

bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)


class FastSaverApiError(RuntimeError):
    def __init__(self, status_code: int, response_body: str) -> None:
        super().__init__(f"FastSaver API returned HTTP {status_code}")
        self.status_code = status_code
        self.response_body = response_body


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


def safe_error_detail(error: Exception) -> str:
    detail = str(error).strip() or type(error).__name__
    detail = re.sub(
        r"(https?://[^\s?#]+)\?[^\s]+",
        r"\1?[query redacted]",
        detail,
    )
    detail = re.sub(
        r"(?i)(authorization|password|token)\s*[:=]\s*\S+",
        r"\1=[redacted]",
        detail,
    )
    for secret in (TELEGRAM_BOT_TOKEN, FASTSAVER_API_KEY):
        if secret:
            detail = detail.replace(secret, "[secret redacted]")
    detail = detail.replace(os.getcwd(), "[project]")
    detail = re.sub(r"/tmp/telegram-video-[^\s/]+", "[temporary directory]", detail)
    return detail[:1200]


def update_status(chat_id: int, message_id: int, text: str) -> None:
    try:
        bot.edit_message_text(text, chat_id=chat_id, message_id=message_id)
    except Exception:
        logger.warning("Could not update status message in chat %s", chat_id)


def format_fastsaver_response(response: requests.Response) -> str:
    try:
        body = json.dumps(response.json(), ensure_ascii=False, indent=2)
    except ValueError:
        body = response.text or "<empty response>"

    for secret in (TELEGRAM_BOT_TOKEN, FASTSAVER_API_KEY):
        if secret:
            body = body.replace(secret, "[secret redacted]")
    return body


def send_fastsaver_error_report(chat_id: int, error: FastSaverApiError) -> None:
    report = (
        f"FastSaver API response (HTTP {error.status_code}):\n"
        f"{error.response_body}"
    )
    try:
        if len(report) <= 3900:
            bot.send_message(chat_id, report)
        else:
            document = io.BytesIO(report.encode("utf-8"))
            document.name = "fastsaver-error.json"
            bot.send_document(
                chat_id,
                document,
                caption=f"FastSaver API response (HTTP {error.status_code})",
            )
    except Exception:
        logger.exception("Could not send the FastSaver error report to Telegram")


def get_fastsaver_video_urls(instagram_url: str) -> list[str]:
    if not FASTSAVER_API_KEY:
        raise RuntimeError("FASTSAVER_API_KEY is not configured")

    encoded_url = quote(instagram_url, safe="")
    response = requests.get(
        f"{FASTSAVER_API_URL}?url={encoded_url}",
        headers={"X-Api-Key": FASTSAVER_API_KEY},
        timeout=(10, 30),
    )
    if response.status_code != 200:
        raise FastSaverApiError(
            response.status_code,
            format_fastsaver_response(response),
        )

    try:
        payload = response.json()
    except ValueError as error:
        raise FastSaverApiError(
            response.status_code,
            format_fastsaver_response(response),
        ) from error

    if not isinstance(payload, dict):
        raise FastSaverApiError(
            response.status_code,
            format_fastsaver_response(response),
        )
    if not payload.get("ok"):
        raise FastSaverApiError(
            response.status_code,
            format_fastsaver_response(response),
        )

    if payload.get("type") == "video":
        candidates = [payload.get("download_url")]
    elif payload.get("type") == "album":
        items = payload.get("items")
        candidates = [
            item.get("download_url")
            for item in items or []
            if isinstance(item, dict) and item.get("type") == "video"
        ]
    else:
        candidates = []

    video_urls = []
    for candidate in candidates:
        if not isinstance(candidate, str) or not candidate:
            continue
        parsed = urlsplit(candidate)
        if parsed.scheme != "https" or not parsed.hostname:
            raise RuntimeError("FastSaver returned an invalid video URL")
        video_urls.append(candidate)

    if not video_urls:
        raise FastSaverApiError(
            response.status_code,
            format_fastsaver_response(response),
        )
    return video_urls


def download_video_to_temp(video_url: str, temp_dir: str) -> str:
    suffix = os.path.splitext(urlsplit(video_url).path)[1].lower()
    if suffix not in VIDEO_EXTENSIONS:
        suffix = ".mp4"

    temp_file = tempfile.NamedTemporaryFile(
        prefix="fastsaver-",
        suffix=suffix,
        dir=temp_dir,
        delete=False,
    )
    filename = temp_file.name
    total_size = 0

    try:
        with temp_file, requests.get(
            video_url,
            headers={"User-Agent": USER_AGENT},
            stream=True,
            timeout=(10, 60),
        ) as response:
            response.raise_for_status()
            content_length = response.headers.get("Content-Length")
            if content_length and int(content_length) > MAX_FILE_SIZE:
                raise ValueError("Video is too large to send")

            for chunk in response.iter_content(chunk_size=256 * 1024):
                if not chunk:
                    continue
                total_size += len(chunk)
                if total_size > MAX_FILE_SIZE:
                    raise ValueError("Video is too large to send")
                temp_file.write(chunk)

        if total_size == 0:
            raise RuntimeError("FastSaver returned an empty video file")
        return filename
    except Exception:
        try:
            os.remove(filename)
        except FileNotFoundError:
            pass
        raise


def send_fastsaver_video(
    chat_id: int,
    video_url: str,
    caption: str | None,
    temp_dir: str,
) -> None:
    try:
        bot.send_video(
            chat_id,
            video_url,
            caption=caption,
            supports_streaming=True,
        )
        return
    except Exception as error:
        logger.warning(
            "Telegram could not send FastSaver URL directly (%s); uploading locally",
            type(error).__name__,
        )

    filename = download_video_to_temp(video_url, temp_dir)
    with open(filename, "rb") as video:
        bot.send_video(
            chat_id,
            video,
            caption=caption,
            supports_streaming=True,
        )


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
            if "instagram.com" in url.lower():
                video_urls = get_fastsaver_video_urls(url)
                for index, video_url in enumerate(video_urls):
                    caption = "Готово! Вот доступное видео." if index == 0 else None
                    send_fastsaver_video(
                        message.chat.id,
                        video_url,
                        caption,
                        temp_dir,
                    )
            else:
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
                    "extractor_args": {
                        "youtube": {
                            "player_client": ["android"],
                        },
                    },
                    "http_headers": {
                        "User-Agent": USER_AGENT,
                    },
                }

                with yt_dlp.YoutubeDL(ydl_options) as downloader:
                    info = downloader.extract_info(url, download=True)
                    if not info:
                        raise RuntimeError("No video information returned")
                    filename = downloader.prepare_filename(info)

                if not os.path.isfile(filename):
                    raise FileNotFoundError("Downloaded video file was not found")
                filenames = [filename]

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
        try:
            release_daily_slot(user_id, usage_date)
        except sqlite3.Error:
            logger.exception("Could not release daily quota after download failure")
        if isinstance(error, FastSaverApiError):
            logger.error(
                "FastSaver API returned HTTP %s:\n%s",
                error.status_code,
                error.response_body,
            )
            update_status(
                message.chat.id,
                status_message.message_id,
                f"FastSaver returned HTTP {error.status_code}. Full response follows.",
            )
            send_fastsaver_error_report(message.chat.id, error)
            return

        detail = safe_error_detail(error)
        logger.error(
            "Video request failed for user %s (%s): %s",
            user_id,
            type(error).__name__,
            detail,
        )
        update_status(
            message.chat.id,
            status_message.message_id,
            f"Ошибка загрузки ({type(error).__name__}):\n{detail}",
        )


def main() -> None:
    initialize_database()
    logger.info("Telegram video bot is running...")
    
    def run_flask():
        port = int(os.environ.get('PORT', 8080))
        app.run(host='0.0.0.0', port=port)
        
    threading.Thread(target=run_flask).start()
    
    bot.infinity_polling(timeout=20, long_polling_timeout=10)

if __name__ == "__main__":
    main()
