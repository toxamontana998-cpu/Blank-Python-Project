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

# Словарь для запоминания действий пользователей (ждет ссылку на видео или аудио)
user_states = {}

# --- БАЗА ДАННЫХ (0 - бесплатно, 1 - Базовый, 2 - Музыкальный, 3 - Максимум) ---
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users 
                 (user_id INTEGER PRIMARY KEY, count INTEGER, last_date TEXT, premium_level INTEGER)''')
    conn.commit()
    conn.close()

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
        # Проверка премиум-доступа
        if level == 3: # Максимум
            conn.close()
            return True
        if level == 2 and action_type in ['video', 'audio_vk']: # Музыкальный
            conn.close()
            return True
        if level == 1 and action_type == 'video': # Базовый
            conn.close()
            return True
            
        # Бесплатный доступ
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
        c.execute("INSERT INTO users (user_id, count, last_date, premium_level) VALUES (?, 1, ?, 0)", (user_id, today))
        conn.commit()
        conn.close()
        return True

def set_premium(user_id, level):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET premium_level = ? WHERE user_id = ?", (level, user_id))
    if c.rowcount == 0:
        c.execute("INSERT INTO users (user_id, count, last_date, premium_level) VALUES (?, 0, '', ?)", (user_id, level))
    conn.commit()
    conn.close()

# --- ВЕБ-СЕРВЕР ---
@app.route('/')
def home():
    return "Bot is alive!"

# --- ИНТЕРФЕЙС (МЕНЮ) ---
@bot.message_handler(commands=['start'])
def start(message):
    markup = types.InlineKeyboardMarkup(row_width=2)
    btn_video = types.InlineKeyboardButton("📥 Скачать Видео", callback_data="mode_video")
    btn_audio_vk = types.InlineKeyboardButton("🎵 Музыка из ВК", callback_data="mode_audio_vk")
    btn_audio_mp3 = types.InlineKeyboardButton("🎬 Вытащить Звук (MP3)", callback_data="mode_audio_mp3")
    btn_buy = types.InlineKeyboardButton("💎 Купить Премиум", callback_data="buy_menu")
    btn_help = types.InlineKeyboardButton("ℹ️ Помощь", callback_data="help_info")
    markup.add(btn_video, btn_audio_vk, btn_audio_mp3, btn_buy, btn_help)

    text = ("👋 Привет! Я — Контент-качалка.\n\n"
            "Я умею вытаскивать видео и музыку из:\n"
            "📸 Instagram | 🎵 TikTok | 🔵 VK\n\n"
            "🔥 Бесплатно: 3 видео в сутки.\n"
            "Выбери действие, а затем просто отправь мне ссылку:")
    bot.send_message(message.chat.id, text, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: True)
def callback_inline(call):
    user_id = call.message.chat.id
    bot.answer_callback_query(call.id)
    
    if call.data == "mode_video":
        user_states[user_id] = 'video'
        bot.send_message(user_id, "📥 **Режим: Скачивание Видео**\n\nОтправь мне ссылку на видео (TikTok, Insta, VK, YouTube), и я скачаю его без логотипов.")
    
    elif call.data == "mode_audio_vk":
        user_states[user_id] = 'audio_vk'
        bot.send_message(user_id, "🎵 **Режим: Музыка из ВК**\n\nОтправь мне ссылку на трек из ВК (vk.com/audio...), и я скачаю музыку.\n\n⚠️ *Доступно с тарифом Музыкальный (70⭐).*")
        
    elif call.data == "mode_audio_mp3":
        user_states[user_id] = 'audio_extract'
        bot.send_message(user_id, "🎬 **Режим: Вытащить Звук**\n\nОтправь мне ссылку на видео, и я вытащу из него MP3.\n\n⚠️ *Доступно с тарифом Максимум (90⭐).*")
        
    elif call.data == "help_info":
        user_states[user_id] = 'video' # сбрасываем в дефолт
        bot.send_message(user_id, "1. Жми на нужную кнопку.\n2. Кидай ссылку.\n3. Бот отправит файл.\n\nПо вопросам: @da_da_eto_Miha")
    
    elif call.data == "buy_menu":
        show_buy_menu(user_id)

# --- ОПЛАТА ---
def show_buy_menu(chat_id):
    markup = types.InlineKeyboardMarkup(row_width=1)
    btn_50 = types.InlineKeyboardButton("🥉 Базовый (Видео) - 50 ⭐", callback_data="pay_50")
    btn_70 = types.InlineKeyboardButton("🥈 Музыкальный (+ Музыка ВК) - 70 ⭐", callback_data="pay_70")
    btn_90 = types.InlineKeyboardButton("🥇 Максимум (+ MP3 из видео) - 90 ⭐", callback_data="pay_90")
    markup.add(btn_50, btn_70, btn_90)
    bot.send_message(chat_id, "💎 **Выбери свой тариф:**", reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: call.data.startswith('pay_'))
def process_payment(call):
    amount = 50
    title = "Базовый"
    if call.data == "pay_70": 
        amount, title = 70, "Музыкальный"
    elif call.data == "pay_90": 
        amount, title = 90, "Максимум"
    
    prices = [types.LabeledPrice(label=f"Премиум {title}", amount=amount)]
    bot.send_invoice(
        call.message.chat.id,
        title=f"Тариф {title}",
        description="Доступ к безлимитному скачиванию.",
        invoice_payload=call.data,
        provider_token="", 
        currency="XTR", 
        prices=prices,
        start_parameter="buy_premium"
    )

@bot.pre_checkout_query_handler(func=lambda query: True)
def checkout(pre_checkout_query):
    bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True, error_message="Ошибка.")

@bot.message_handler(content_types=['successful_payment'])
def got_payment(message):
    payload = message.successful_payment.invoice_payload
    if payload == "pay_50":
        set_premium(message.chat.id, 1)
        bot.send_message(message.chat.id, "🎉 Тариф Базовый активирован! Теперь ты можешь качать видео без ограничений.")
    elif payload == "pay_70":
        set_premium(message.chat.id, 2)
        bot.send_message(message.chat.id, "🎉 Тариф Музыкальный активирован! Теперь тебе доступны безлимитные видео и музыка из ВК.")
    elif payload == "pay_90":
        set_premium(message.chat.id, 3)
        bot.send_message(message.chat.id, "🎉 Тариф Максимум активирован! Теперь тебе доступно всё: безлимитные видео, музыка ВК и вытаскивание MP3 из видео.")

# --- СКАЧИВАНИЕ ---
@bot.message_handler(content_types=['text'])
def handle_link(message):
    if message.text.startswith('/'):
        return
        
    url = message.text.strip()
    if not url.startswith('http'):
        bot.reply_to(message, "🤷‍♂️ Это не ссылка. Нажми на кнопку в меню и отправь ссылку.")
        return

    user_id = message.chat.id
    
    # Получаем текущий режим пользователя (по умолчанию видео)
    action_type = user_states.get(user_id, 'video')
    
    # Если пользователь кинул ссылку ВК-музыки, но забыл нажать кнопку — сами распознаем
    if "vk.com/audio" in url or "vk.com/music" in url:
        if action_type == 'video': 
            action_type = 'audio_vk'
            
    # После получения ссылки сбрасываем состояние в дефолт
    user_states[user_id] = 'video'
    
    process_download(message, url, action_type)

def process_download(message, url, action_type):
    user_id = message.chat.id
    is_youtube = "youtube.com" in url or "youtu.be" in url

    if is_youtube and user_id != ADMIN_ID:
        bot.reply_to(message, "❌ YouTube доступен только создателю бота.")
        return

    if not check_limit(user_id, action_type=action_type):
        if action_type == 'video':
            bot.reply_to(message, "❌ Лимит (3 видео) исчерпан!\nКупи Премиум за 50 ⭐, чтобы качать без ограничений. Жми /buy")
        elif action_type == 'audio_vk':
            bot.reply_to(message, "❌ Для скачивания музыки из ВК нужен тариф «Музыкальный» (70 ⭐). Жми /buy")
        elif action_type == 'audio_extract':
            bot.reply_to(message, "❌ Для вытаскивания MP3 из видео нужен тариф «Максимум» (90 ⭐). Жми /buy")
        return

    msg = bot.reply_to(message, "⏳ Обрабатываю, подожди...")
    video_file = f"video_{user_id}.mp4"
    audio_file = f"audio_{user_id}.mp3"

    try:
        if "instagram.com" in url and action_type == 'video':
            # ИНСТАГРАМ (Только видео через FastSaver)
            headers = {"X-Api-Key": FASTSAVER_API_KEY}
            res = requests.get(f"https://api.fastsaver.io/v1/fetch?url={url}", headers=headers)
            video_url = res.json().get("download_url")
            
            if video_url:
                bot.send_video(message.chat.id, video_url, caption="🔥 Держи видео!")
                bot.delete_message(message.chat.id, msg.message_id)
            else:
                bot.edit_message_text("❌ Ошибка скачивания (FastSaver).", chat_id=message.chat.id, message_id=msg.message_id)
        
        else:
            # ТИКТОК, ВК, ЮТУБ (через yt-dlp)
            if action_type in ['audio_extract', 'audio_vk']:
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
                    bot.send_audio(message.chat.id, audio, caption="🎵 Держи трек!")
                
                os.remove(audio_file)
                bot.delete_message(message.chat.id, msg.message_id)
            else:
                # Видео
                ydl_opts = {
                    'format': 'best[ext=mp4]/best',
                    'outtmpl': video_file,
                    'quiet': True,
                    'impersonate': ImpersonateTarget.from_str('chrome'),
                }
                if is_youtube and os.path.exists("cookies.txt"):
                    ydl_opts['cookiefile'] = 'cookies.txt'

                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([url])
                    
                with open(video_file, 'rb') as video:
                    bot.send_video(message.chat.id, video, caption="🔥 Держи видео!")
                    
                os.remove(video_file)
                bot.delete_message(message.chat.id, msg.message_id)

    except Exception as e:
        traceback.print_exc()
        error_text = repr(e)
        bot.edit_message_text(f"❌ Ошибка: {error_text[:200]}", chat_id=message.chat.id, message_id=msg.message_id)
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
