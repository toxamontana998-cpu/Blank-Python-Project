import os
import threading
from flask import Flask
import telebot
from telebot import types
import requests
import yt_dlp
import sqlite3
from datetime import datetime

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
FASTSAVER_API_KEY = os.environ.get("FASTSAVER_API_KEY")

if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError("Set TELEGRAM_BOT_TOKEN in Environment Variables")

bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)
app = Flask(__name__)
DB_PATH = 'users.db'

# --- БАЗА ДАННЫХ ---
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users 
                 (user_id INTEGER PRIMARY KEY, count INTEGER, last_date TEXT, is_premium INTEGER)''')
    conn.commit()
    conn.close()

def check_limit(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    today = datetime.now().strftime("%Y-%m-%d")
    c.execute("SELECT count, last_date, is_premium FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()

    if row:
        count, last_date, is_premium = row
        if is_premium == 1:
            conn.close()
            return True # Премиум качает безлимит
        if last_date != today:
            c.execute("UPDATE users SET count = 1, last_date = ? WHERE user_id = ?", (today, user_id))
            conn.commit()
            conn.close()
            return True
        if count >= 3:
            conn.close()
            return False # Лимит исчерпан
        c.execute("UPDATE users SET count = count + 1 WHERE user_id = ?", (user_id,))
        conn.commit()
        conn.close()
        return True
    else:
        c.execute("INSERT INTO users (user_id, count, last_date, is_premium) VALUES (?, 1, ?, 0)", (user_id, today))
        conn.commit()
        conn.close()
        return True

def set_premium(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET is_premium = 1 WHERE user_id = ?", (user_id,))
    # Если юзера нет, создаем
    if c.rowcount == 0:
        c.execute("INSERT INTO users (user_id, count, last_date, is_premium) VALUES (?, 0, '', 1)", (user_id,))
    conn.commit()
    conn.close()

# --- ВЕБ-СЕРВЕР ДЛЯ RENDER ---
@app.route('/')
def home():
    return "Bot is alive!"

# --- КОМАНДЫ БОТА ---
@bot.message_handler(commands=['start'])
def start(message):
    bot.send_message(message.chat.id, 
                 "Привет! 📥 Я — Контент-качалка.\n\n"
                 "Просто отправь мне ссылку на видео из Instagram, TikTok, YouTube или VK, "
                 "и я скачаю его БЕЗ водяных знаков.\n\n"
                 "🔥 Бесплатно: 3 видео в сутки. Хочешь больше — жми /buy")

@bot.message_handler(commands=['buy'])
def buy(message):
    prices = [types.LabeledPrice(label="Премиум подписка", amount=50)]
    bot.send_invoice(
        message.chat.id,
        title="Безлимит навсегда (тест)",
        description="Снимает лимит в 3 видео в день. Качай сколько хочешь!",
        invoice_payload="premium_sub",
        provider_token="", 
        currency="XTR", 
        prices=prices,
        start_parameter="buy_premium"
    )

@bot.pre_checkout_query_handler(func=lambda query: True)
def checkout(pre_checkout_query):
    bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True, error_message="Что-то пошло не так.")

@bot.message_handler(content_types=['successful_payment'])
def got_payment(message):
    set_premium(message.chat.id)
    bot.send_message(message.chat.id, "🎉 Оплата прошла успешно! Теперь у тебя Премиум. Качай без ограничений!")

# --- ОБРАБОТКА ССЫЛОК ---
@bot.message_handler(content_types=['text'])
def handle_link(message):
    if message.text.startswith('/'):
        return
        
    url = message.text.strip()
    if not url.startswith('http'):
        bot.reply_to(message, "🤷‍♂️ Это не похоже на ссылку. Кидай ссылку на видео!")
        return

    # Проверка лимита
    user_id = message.chat.id
    if not check_limit(user_id):
        bot.reply_to(message, "❌ Твой бесплатный лимит (3 видео) на сегодня исчерпан.\n\nКупи Премиум за 50 ⭐, чтобы качать без ограничений! Жми /buy")
        return

    msg = bot.reply_to(message, "⏳ Скачиваю видео, подожди...")
    filename = f"video_{message.chat.id}.mp4"

    try:
        if "instagram.com" in url:
            headers = {"X-Api-Key": FASTSAVER_API_KEY}
            res = requests.get(f"https://api.fastsaver.io/v1/fetch?url={url}", headers=headers)
            data = res.json()
            video_url = data.get("download_url")
            
            if video_url:
                bot.send_video(message.chat.id, video_url, caption="🔥 Держи видео!")
                bot.delete_message(message.chat.id, msg.message_id)
            else:
                bot.edit_message_text(f"❌ Ошибка FastSaver: {data}", chat_id=message.chat.id, message_id=msg.message_id)
        else:
            ydl_opts = {'format': 'best[ext=mp4]/best', 'outtmpl': filename, 'quiet': True}
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
                
            with open(filename, 'rb') as video:
                bot.send_video(message.chat.id, video, caption="🔥 Держи видео без логотипов!")
                
            os.remove(filename)
            bot.delete_message(message.chat.id, msg.message_id)

    except Exception as e:
        bot.edit_message_text(f"❌ Ошибка: {e}", chat_id=message.chat.id, message_id=msg.message_id)
        if os.path.exists(filename):
            os.remove(filename)

# --- ЗАПУСК ---
def main():
    init_db()
    def run_flask():
        port = int(os.environ.get('PORT', 8080))
        app.run(host='0.0.0.0', port=port)

    threading.Thread(target=run_flask).start()
    bot.infinity_polling(timeout=20, long_polling_timeout=10)

if __name__ == "__main__":
    main()
