import os
import threading
from flask import Flask
import telebot
from telebot import types
import requests
import yt_dlp

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
FASTSAVER_API_KEY = os.environ.get("FASTSAVER_API_KEY")

if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError("Set TELEGRAM_BOT_TOKEN in Environment Variables")

bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is alive!"

@bot.message_handler(commands=['start'])
def start(message):
    bot.send_message(message.chat.id, 
                     "Привет! 📥 Я скачиваю видео из Instagram, TikTok, YouTube или VK.\n\n"
                     "Отправь ссылку на видео. Бесплатный лимит — 3 видео.\n"
                     "Хочешь безлимит? Жми /buy")

@bot.message_handler(commands=['buy'])
def buy(message):
    prices = [types.LabeledPrice(label="Премиум подписка", amount=50)]
    bot.send_invoice(
        message.chat.id,
        title="Безлимит на 30 дней",
        description="Снимает лимит в 3 видео в день. Качай сколько хочешь!",
        invoice_payload="premium_sub",
        provider_token="", 
        currency="XTR", 
        prices=prices,
        start_parameter="buy_premium"
    )

@bot.pre_checkout_query_handler(func=lambda query: True)
def checkout(pre_checkout_query):
    bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True, error_message="Что-то пошло не так. Попробуй еще раз.")

@bot.message_handler(content_types=['successful_payment'])
def got_payment(message):
    bot.send_message(message.chat.id, "🎉 Оплата прошла успешно! Теперь у тебя Премиум.")

@bot.message_handler(content_types=['text'])
def handle_link(message):
    if message.text.startswith('/'):
        return
        
    url = message.text.strip()
    if not url.startswith('http'):
        bot.reply_to(message, "🤷‍♂️ Это не похоже на ссылку. Кидай ссылку на видео!")
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
            ydl_opts = {
                'format': 'best[ext=mp4]/best',
                'outtmpl': filename,
                'quiet': True,
            }
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

def main():
    def run_flask():
        port = int(os.environ.get('PORT', 8080))
        app.run(host='0.0.0.0', port=port)

    threading.Thread(target=run_flask).start()
    bot.infinity_polling(timeout=20, long_polling_timeout=10)

if __name__ == "__main__":
    main()
