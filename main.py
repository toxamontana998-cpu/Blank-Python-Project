import os
import threading
from flask import Flask
import telebot
from telebot import types
import requests
import yt_dlp
from yt_dlp.networking.impersonate import ImpersonateTarget
import sqlite3
from datetime import datetime
import traceback
import subprocess

# --- ТОКЕНЫ ---
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
FASTSAVER_API_KEY = os.environ.get("FASTSAVER_API_KEY")
YOUTUBE_COOKIES = os.environ.get("YOUTUBE_COOKIES")

ADMIN_ID = 6385559900

if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError("Set TELEGRAM_BOT_TOKEN")

if YOUTUBE_COOKIES:
    with open("cookies.txt", "w", encoding="utf-8") as f:
        f.write(YOUTUBE_COOKIES)

bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)
app = Flask(__name__)
DB_PATH = 'users.db'

# --- БАЗА ДАННЫХ ---
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users 
                 (user_id INTEGER PRIMARY KEY, count INTEGER, last_date TEXT, premium_level INTEGER, current_mode TEXT)''')
    try:
        c.execute("SELECT current_mode FROM users LIMIT 1")
    except sqlite3.OperationalError:
        c.execute("ALTER TABLE users ADD COLUMN current_mode TEXT DEFAULT 'video'")
    conn.commit()
    conn.close()

def set_mode(user_id, mode):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET current_mode = ? WHERE user_id = ?", (mode, user_id))
    if c.rowcount == 0:
        today = datetime.now().strftime("%Y-%m-%d")
        c.execute("INSERT INTO users (user_id, count, last_date, premium_level, current_mode) VALUES (?, 0, ?, 0, ?)", (user_id, today, mode))
    conn.commit()
    conn.close()

def get_mode(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT current_mode FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row[0] if row and row[0] else 'video'

def check_limit(user_id, action_type='video'):
    if user_id == ADMIN_ID:
        return True
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    today = datetime.now().strftime("%Y-%m-%d")
    c.execute("SELECT count, last_date, premium_level FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    
    if row:
        count, last_date, level = row
        if level == 2: 
            conn.close()
            return True
        if level == 1 and action_type == 'video': 
            conn.close()
            return True
        if last_date != today:
            c.execute("UPDATE users SET count = 1, last_date = ? WHERE user_id = ?", (today, user_id))
            conn.commit()
            conn.close()
            return True
        if count >= 3:
            conn.close()
            return False 
        c.execute("UPDATE users SET count = count + 1 WHERE user_id = ?", (user_id,))
        conn.commit()
        conn.close()
        return True
    else:
        c.execute("INSERT INTO users (user_id, count, last_date, premium_level, current_mode) VALUES (?, 1, ?, 0, 'video')", (user_id, today))
        conn.commit()
        conn.close()
        return True

def set_premium(user_id, level):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET premium_level = ? WHERE user_id = ?", (level, user_id))
    if c.rowcount == 0:
        c.execute("INSERT INTO users (user_id, count, last_date, premium_level, current_mode) VALUES (?, 0, '', ?, 'video')", (user_id, level))
    conn.commit()
    conn.close()

@app.route('/')
def home():
    return "Bot is alive!"

# --- МЕНЮ ---
def get_main_menu():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        types.KeyboardButton("📥 Скачать Видео"),
        types.KeyboardButton("🎬 Вытащить Звук (MP3)"),
        types.KeyboardButton("💎 Купить Премиум"),
        types.KeyboardButton("ℹ️ Помощь"),
        types.KeyboardButton("🔄 Перезапустить")
    )
    return markup

@bot.message_handler(commands=['start', 'menu'])
def start(message):
    user_id = message.chat.id
    set_mode(user_id, 'video')
    text = ("👋 Привет! Я — Контент-качалка.\n\n"
            "📸 Instagram | 🎵 TikTok | 🔵 VK\n\n"
            "Я качаю видео БЕЗ водяных знаков и вытаскиваю MP3 из любого видео!\n\n"
            "🔥 Бесплатно: 3 видео в сутки.")
    bot.send_message(user_id, text, reply_markup=get_main_menu())

# --- КНОПКИ МЕНЮ ---
@bot.message_handler(func=lambda message: message.text in ["📥 Скачать Видео", "🎬 Вытащить Звук (MP3)", "💎 Купить Премиум", "ℹ️ Помощь", "🔄 Перезапустить"])
def handle_menu_buttons(message):
    user_id = message.chat.id
    if message.text == "🔄 Перезапустить":
        start(message)
        return
        
    inline_markup = types.InlineKeyboardMarkup()
    inline_markup.add(types.InlineKeyboardButton("🔙 Вернуться в меню", callback_data="back_to_menu"))

    if message.text == "📥 Скачать Видео":
        set_mode(user_id, 'video')
        bot.send_message(user_id, "📥 <b>Режим: Скачивание Видео</b>\n\nОтправь мне ссылку, и я скачаю видео без логотипов.", parse_mode="HTML", reply_markup=inline_markup)
    elif message.text == "🎬 Вытащить Звук (MP3)":
        set_mode(user_id, 'audio_extract')
        bot.send_message(user_id, "🎬 <b>Режим: Вытащить Звук</b>\n\nОтправь мне ссылку на видео, и я вытащу из него MP3.\n\n⚠️ <i>Доступно с тарифом Максимум (75⭐).</i>", parse_mode="HTML", reply_markup=inline_markup)
    elif message.text == "ℹ️ Помощь":
        set_mode(user_id, 'video')
        bot.send_message(user_id, "1. Жми на кнопку внизу.\n2. Кидай ссылку.\n3. Бот отправит файл.\n\nПо вопросам: @da_da_eto_Miha", reply_markup=inline_markup)
    elif message.text == "💎 Купить Премиум":
        show_buy_menu(user_id)

@bot.callback_query_handler(func=lambda call: call.data == "back_to_menu")
def back_to_menu(call):
    user_id = call.message.chat.id
    set_mode(user_id, 'video')
    bot.answer_callback_query(call.id, "Меню обновлено")
    bot.send_message(user_id, "👋 Вы в главном меню.\nВыбери действие:", reply_markup=get_main_menu())

# --- ОПЛАТА ---
def show_buy_menu(chat_id):
    markup = types.InlineKeyboardMarkup(row_width=1)
    btn_50 = types.InlineKeyboardButton("🥈 Базовый (Безлимит на видео) - 50 ⭐", callback_data="pay_50")
    btn_75 = types.InlineKeyboardButton("🥇 Максимум (+ Вытаскивание MP3) - 75 ⭐", callback_data="pay_75")
    markup.add(btn_50, btn_75)
    bot.send_message(chat_id, "💎 <b>Выбери свой тариф:</b>", reply_markup=markup, parse_mode="HTML")

@bot.callback_query_handler(func=lambda call: call.data.startswith('pay_'))
def process_payment(call):
    amount, title = (50, "Базовый") if call.data == "pay_50" else (75, "Максимум")
    prices = [types.LabeledPrice(label=f"Премиум {title}", amount=amount)]
    bot.send_invoice(call.message.chat.id, title=f"Тариф {title}", description="Доступ к безлимитному скачиванию.",
        invoice_payload=call.data, provider_token="", currency="XTR", prices=prices, start_parameter="buy_premium")

@bot.pre_checkout_query_handler(func=lambda query: True)
def checkout(pre_checkout_query):
    bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True, error_message="Ошибка.")

@bot.message_handler(content_types=['successful_payment'])
def got_payment(message):
    payload = message.successful_payment.invoice_payload
    level = 1 if payload == "pay_50" else 2
    set_premium(message.chat.id, level)
    bot.send_message(message.chat.id, f"🎉 Тариф активирован! Приятного пользования.", reply_markup=get_main_menu())

# --- СКАЧИВАНИЕ ---
@bot.message_handler(content_types=['text'])
def handle_link(message):
    if message.text.startswith('/'):
        return
    url = message.text.strip()
    if not url.startswith('http'):
        bot.reply_to(message, "🤷‍♂️ Это не ссылка.", reply_markup=get_main_menu())
        return

    user_id = message.chat.id
    action_type = get_mode(user_id)
    set_mode(user_id, 'video')
    process_download(message, url, action_type)

def process_download(message, url, action_type):
    user_id = message.chat.id
    is_youtube = "youtube.com" in url or "youtu.be" in url
    is_insta = "instagram.com" in url

    if is_youtube and user_id != ADMIN_ID:
        bot.reply_to(message, "❌ YouTube доступен только создателю.", reply_markup=get_main_menu())
        return

    if not check_limit(user_id, action_type=action_type):
        if action_type == 'video':
            bot.reply_to(message, "❌ Лимит (3 видео) исчерпан!\nКупи Премиум за 50 ⭐. Жми /buy")
        elif action_type == 'audio_extract':
            bot.reply_to(message, "❌ Для MP3 нужен тариф «Максимум» (75 ⭐). Жми /buy")
        return

    msg = bot.reply_to(message, "⏳ Обрабатываю, подожди...")
    video_file = f"video_{user_id}.mp4"
    audio_file = f"audio_{user_id}.mp3"

    try:
        if is_insta:
            # ИНСТАГРАМ (ВСЕГДА ЧЕРЕЗ FASTSAVER - ОН УБИРАЕТ ВОДЯНОЙ ЗНАК)
            headers = {"X-Api-Key": FASTSAVER_API_KEY}
            res = requests.get(f"https://api.fastsaver.io/v1/fetch?url={url}", headers=headers)
            video_url = res.json().get("download_url")
            
            if video_url:
                if action_type == 'video':
                    bot.send_video(message.chat.id, video_url, caption="🔥 Держи видео!", reply_markup=get_main_menu())
                else:
                    # Если нужен звук, качаем видео и вырезаем MP3
                    vid_data = requests.get(video_url).content
                    with open(video_file, 'wb') as f:
                        f.write(vid_data)
                    
                    subprocess.run(['ffmpeg', '-i', video_file, '-vn', '-acodec', 'libmp3lame', '-q:a', '2', audio_file, '-y'], check=True)
                    with open(audio_file, 'rb') as audio:
                        bot.send_audio(message.chat.id, audio, caption="🎵 Держи трек!", reply_markup=get_main_menu())
                    os.remove(video_file)
                    os.remove(audio_file)
            else:
                bot.edit_message_text("❌ Ошибка скачивания (FastSaver).", chat_id=message.chat.id, message_id=msg.message_id)
        
        else:
            # ТИКТОК И ВК (ЧЕРЕЗ YT-DLP)
            # Используем специальные форматы, чтобы гарантированно не было водяных знаков
            if action_type == 'audio_extract':
                ydl_opts = {
                    'format': 'bestaudio/best',
                    'postprocessors': [{
                        'key': 'FFmpegExtractAudio',
                        'preferredcodec': 'mp3',
                        'preferredquality': '192',
                    }],
                    'outtmpl': audio_file.replace('.mp3', ''),
                    'quiet': True,
                    'impersonate': ImpersonateTarget.from_str('chrome'),
                }
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([url])
                
                with open(audio_file, 'rb') as audio:
                    bot.send_audio(message.chat.id, audio, caption="🎵 Держи трек!", reply_markup=get_main_menu())
                os.remove(audio_file)
            else:
                # Для видео: bv*+ba/b гарантирует лучшее качество без логотипов
                ydl_opts = {
                    'format': 'bv*+ba/b',
                    'outtmpl': video_file,
                    'quiet': True,
                    'impersonate': ImpersonateTarget.from_str('chrome'),
                }
                if is_youtube and os.path.exists("cookies.txt"):
                    ydl_opts['cookiefile'] = 'cookies.txt'

                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([url])
                    
                with open(video_file, 'rb') as video:
                    bot.send_video(message.chat.id, video, caption="🔥 Держи видео!", reply_markup=get_main_menu())
                os.remove(video_file)
                
        bot.delete_message(message.chat.id, msg.message_id)

    except Exception as e:
        traceback.print_exc()
        error_text = repr(e)
        bot.edit_message_text(f"❌ Ошибка: {error_text[:200]}", chat_id=message.chat.id, message_id=msg.message_id, reply_markup=get_main_menu())
        if os.path.exists(video_file): os.remove(video_file)
        if os.path.exists(audio_file): os.remove(audio_file)

def main():
    init_db()
    def run_flask():
        port = int(os.environ.get('PORT', 8080))
        app.run(host='0.0.0.0', port=port)
    threading.Thread(target=run_flask).start()
    bot.infinity_polling(timeout=20, long_polling_timeout=10)

if __name__ == "__main__":
    main()
