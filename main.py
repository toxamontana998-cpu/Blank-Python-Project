import os
import html
import threading
import sqlite3
from datetime import datetime
import time
import asyncio
import edge_tts
import io
import traceback
from google import genai
import telebot
from telebot import types
from http.server import BaseHTTPRequestHandler, HTTPServer

# --- ТОКЕНЫ ---
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
ADMIN_ID = 6385559900

if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError("НЕТ ТОКЕНА БОТА")
if not GEMINI_API_KEY:
    raise RuntimeError("НЕТ КЛЮЧА GEMINI")

# --- ИИ ---
client = genai.Client(api_key=GEMINI_API_KEY)

# --- ХАРАКТЕР: почтительный старинный слуга, красноречивый, расторопный, правдивый ---
AI_PERSONA = (
    "Ты — верный, почтительный и преданный цифровой слуга великого Царя-батюшки "
    "(пользователь — твой господин и повелитель).\n\n"
    "КАК ОБРАЩАТЬСЯ К ГОСПОДИНУ: 'государь', 'батюшка', 'мой господин', 'повелитель', "
    "'ваша милость', 'ваша светлость'.\n"
    "КАК ГОВОРИТЬ О СЕБЕ: 'твой верный слуга', 'твой покорный слуга', "
    "'смиренный служитель', 'слуга твой нижайший', 'недостойный твоего доверия слуга'.\n\n"
    "ТВОЙ ХАРАКТЕР:\n"
    "— Ты низко кланяешься господину в каждом ответе (словами: 'кланяюсь тебе, государь', "
    "'нижайше кланяюсь', 'бью челом, батюшка').\n"
    "— Ты искренне признаёшь мудрость, прозорливость и величие господина и восхваляешь его "
    "красиво, в старинной манере — но без грубой лести и без унижений.\n"
    "— Ты расторопен и услужлив: на любое поручение отвечаешь живо и почтительно — "
    "'сейчас исполню, государь', 'мигом сбегаю', 'сию минуту', 'не извольте беспокоиться, всё сделаю', "
    "'дозвольте броситься исполнять', 'слушаюсь, батюшка'.\n"
    "— Ты говоришь изящно, по-старинному: 'изволите', 'соизволите', 'повелеваете', 'дозвольте', "
    "'осмелюсь доложить', 'как прикажете', 'будет исполнено'.\n\n"
    "КРАСНОРЕЧИЕ (ОБЯЗАТЕЛЬНО):\n"
    "— Говори КРАСИВО, ОБРАЗНО и ЖИВО, как речь старинного верного слуги при царском дворе.\n"
    "— В каждом ответе должен звучать ПОКЛОН и ПОХВАЛА мудрости господина — это твоя природа.\n"
    "— Красноречие — неотъемлемая часть тебя: даже самый простой ответ произноси с достоинством и изяществом.\n\n"
    "ПРАВДИВОСТЬ И ТОЧНОСТЬ (ВАЖНЕЙШЕЕ ПРАВИЛО):\n"
    "— Говори ТОЛЬКО то, в чём уверен. Не выдумывай факты, имена, числа, даты, названия, события.\n"
    "— Если НЕ знаешь точного ответа — честно признайся, НО ПО-ПРЕЖНЕМУ КРАСИВО и с поклоном: "
    "'осмелюсь доложить, государь, но точных сведений у меня нет — не смею лукавить пред твоей мудростью'.\n"
    "— НИКОГДА не додумывай и не предполагай факты.\n"
    "— Правдивость НЕ отменяет красноречия: признание в незнании — тоже часть твоего искусства служить.\n\n"
    "ЧЕГО НЕЛЬЗЯ:\n"
    "— НИКОГДА не используй фразы вроде 'целовать ноги', 'прах у ног твоих', 'ничтожный раб'.\n"
    "— КАТЕГОРИЧЕСКИ ЗАПРЕЩЁН современный сленг, английские слова и интернет-термины.\n\n"
    "ОБЯЗАТЕЛЬНО: идеальная пунктуация. Говори ЧЁТКО, ЯСНО, КРАСИВО, ЖИВО, без мямленья."
)

async def synthesize_speech(text):
    voice = "ru-RU-DmitryNeural"
    async def _inner():
        communicate = edge_tts.Communicate(text, voice, rate="+10%", pitch="+0Hz")
        buf = b""
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                buf += chunk["data"]
        return buf
    return await asyncio.wait_for(_inner(), timeout=60)

# --- БОТ ---
bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)
DB_PATH = os.path.join(os.getcwd(), 'personal_assistant.db')
user_data = {}

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS tasks (id INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT, status INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS shifts (id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT, pay INTEGER)''')
    c.execute('''CREATE TABLE IF NOT EXISTS reminders (id TEXT PRIMARY KEY, text TEXT, time TEXT, is_sent INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS notes (id INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT)''')
    conn.commit()
    conn.close()

def get_main_menu():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        types.KeyboardButton("🏰 Пополнить казну"),
        types.KeyboardButton("🧠 Спросить советника"),
        types.KeyboardButton("🕯️ Царская сводка"),
        types.KeyboardButton("📜 Список указов"),
        types.KeyboardButton("📖 Рукописи"),
        types.KeyboardButton("🕊️ Гонцы")
    )
    return markup

@bot.message_handler(func=lambda m: m.chat.id != ADMIN_ID, content_types=['text', 'photo', 'video', 'document', 'voice'])
def deny_access(message):
    bot.send_message(message.chat.id, "⛔ <b>Прочь, смертный.</b>", parse_mode="HTML")

@bot.message_handler(commands=['start', 'menu'], func=lambda m: m.chat.id == ADMIN_ID)
def start(message):
    text = ("👑 <b>Да здравствует Царь-батюшка!</b>\n\nТвой верный слуга приветствует тебя.\n\n"
            "🏰 <b>Пополнить казну</b> — внести данные о службе.\n"
            "🧠 <b>Спросить советника</b> — вопросить мудрость.\n"
            "🕯️ <b>Царская сводка</b> — узреть статистику.\n"
            "📜 <b>Список указов</b> — добавить задачу (через /add).\n"
            "📖 <b>Рукописи</b> — записать заметку (через /note).\n"
            "🕊️ <b>Гонцы</b> — поставить напоминание (через /remind).\n\n"
            "🎙️ <i>Можешь отправить голосовое сообщение.</i>")
    bot.send_message(message.chat.id, text, parse_mode="HTML", reply_markup=get_main_menu())

@bot.message_handler(content_types=['voice'])
def handle_voice(message):
    if message.chat.id != ADMIN_ID: return
    msg = bot.reply_to(message, "🎙️ <i>Внимаю...</i>", parse_mode="HTML")
    try:
        file_info = bot.get_file(message.voice.file_id)
        downloaded = bot.download_file(file_info.file_path)
        audio_part = genai.types.Part.from_bytes(data=downloaded, mime_type="audio/ogg")
        
        # Исправлена модель на gemini-1.5-flash
        response = client.models.generate_content(
            model='gemini-1.5-flash',
            contents=[audio_part, "Расшифруй речь господина и ответь согласно роли."],
            config=genai.types.GenerateContentConfig(system_instruction=AI_PERSONA, temperature=0.5),
        )
        
        reply_text = response.text or "Смилуйся, государь, но я не разобрал."
        display_text = reply_text if len(reply_text) <= 3500 else reply_text[:3500] + "..."
        bot.edit_message_text(f"📜 <b>Ответ:</b>\n\n{html.escape(display_text)}", chat_id=message.chat.id, message_id=msg.message_id, parse_mode="HTML")
        
        voice_text = reply_text if len(reply_text) <= 800 else reply_text[:800] + "..."
        audio_data = asyncio.run(synthesize_speech(voice_text))
        audio_io = io.BytesIO(audio_data)
        audio_io.name = "voice.mp3" 
        bot.send_audio(message.chat.id, audio_io, title="Ответ слуги", caption="🕊️ Слушаюсь, государь!")
    except Exception as e:
        bot.edit_message_text(f"❌ Ошибка: {html.escape(str(e)[:100])}", chat_id=message.chat.id, message_id=msg.message_id, parse_mode="HTML")

@bot.message_handler(func=lambda m: m.text == "🧠 Спросить советника" and m.chat.id == ADMIN_ID)
def ask_ai_start(message):
    msg = bot.send_message(message.chat.id, "🧠 <b>Изволь задать вопрос.</b>", parse_mode="HTML")
    bot.register_next_step_handler(msg, process_ai_question)

def process_ai_question(message):
    if not message.text or message.text.startswith('/'):
        bot.send_message(message.chat.id, "Государь, изволь вопрошать словами.", reply_markup=get_main_menu())
        return
    msg = bot.send_message(message.chat.id, "⏳ <i>Ищу ответ...</i>", parse_mode="HTML")
    try:
        # Исправлена модель на gemini-1.5-flash
        response = client.models.generate_content(
            model='gemini-1.5-flash', 
            contents=message.text, 
            config=genai.types.GenerateContentConfig(system_instruction=AI_PERSONA, temperature=0.5)
        )
        reply_text = response.text or "Смилуйся, государь, но летописи молчат."
        bot.edit_message_text(html.escape(reply_text), chat_id=message.chat.id, message_id=msg.message_id, parse_mode="HTML", reply_markup=get_main_menu())
    except Exception as e:
        bot.edit_message_text(f"❌ Ошибка: {html.escape(str(e)[:100])}", chat_id=message.chat.id, message_id=msg.message_id, parse_mode="HTML", reply_markup=get_main_menu())

@bot.message_handler(func=lambda m: m.text == "🏰 Пополнить казну" and m.chat.id == ADMIN_ID)
def start_shift_report(message):
    user_data[message.chat.id] = {}
    msg = bot.send_message(message.chat.id, "⚖️ <b>Сколько часов отслужили?</b>", parse_mode="HTML")
    bot.register_next_step_handler(msg, process_hours)

def process_hours(message):
    try:
        hours = float(message.text.replace(',', '.'))
        user_data[message.chat.id]['hours'] = hours
        msg = bot.send_message(message.chat.id, "📦 <b>Сколько доставок?</b>", parse_mode="HTML")
        bot.register_next_step_handler(msg, process_orders)
    except:
        bot.send_message(message.chat.id, "❌ Нужны цифры.", reply_markup=get_main_menu())

def process_orders(message):
    try:
        orders = int(message.text)
        user_data[message.chat.id]['orders'] = orders
        hours = user_data[message.chat.id]['hours']
        base_pay = (hours * 110) + (orders * 35)
        user_data[message.chat.id]['base_pay'] = base_pay
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            types.InlineKeyboardButton("🌧 За непогоду", callback_data="shift_rain"),
            types.InlineKeyboardButton("📅 За выходной", callback_data="shift_weekend"),
            types.InlineKeyboardButton("🔥 За 70ч", callback_data="shift_70h"),
            types.InlineKeyboardButton("💎 Все надбавки", callback_data="shift_all"),
            types.InlineKeyboardButton("⚖️ Без надбавок", callback_data="shift_save_base")
        )
        bot.send_message(message.chat.id, f"📊 База: {int(base_pay)} ₽\nДобавить надбавки?", parse_mode="HTML", reply_markup=markup)
    except:
        bot.send_message(message.chat.id, "❌ Нужны цифры.", reply_markup=get_main_menu())

@bot.callback_query_handler(func=lambda c: c.data.startswith('shift_') and c.message.chat.id == ADMIN_ID)
def process_shift_bonus(call):
    data = user_data.get(call.message.chat.id)
    if not data: return
    base_pay, hours, orders = data['base_pay'], data['hours'], data['orders']
    bonus, bonus_text = 0, ""
    if call.data == "shift_rain": bonus, bonus_text = orders * 10, "Непогода"
    elif call.data == "shift_weekend": bonus, bonus_text = hours * 15, "Выходной"
    elif call.data == "shift_70h": bonus, bonus_text = hours * 10, "70ч"
    elif call.data == "shift_all": bonus, bonus_text = (orders * 10) + (hours * 15) + (hours * 10), "Все"
    elif call.data == "shift_save_base":
        save_shift_to_db(call.message.chat.id, int(base_pay))
        bot.edit_message_text(f"✅ Записано: {int(base_pay)} ₽", chat_id=call.message.chat.id, message_id=call.message.message_id, parse_mode="HTML")
        return
    total = int(base_pay + bonus)
    markup = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("✅ Сохранить", callback_data=f"confirm_save_{total}"))
    bot.edit_message_text(f"⚖️ Итого: {total} ₽ ({bonus_text})", chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data.startswith('confirm_save_') and c.message.chat.id == ADMIN_ID)
def confirm_save(call):
    try:
        total = int(call.data.split('_')[2])
        save_shift_to_db(call.message.chat.id, total)
        bot.edit_message_text(f"✅ Записано: {total} ₽", chat_id=call.message.chat.id, message_id=call.message.message_id)
    except: pass

def save_shift_to_db(chat_id, pay):
    conn = sqlite3.connect(DB_PATH)
    conn.cursor().execute("INSERT INTO shifts (date, pay) VALUES (?, ?)", (datetime.now().strftime("%d.%m.%Y"), pay))
    conn.commit(); conn.close()
    if chat_id in user_data: del user_data[chat_id]

@bot.message_handler(func=lambda m: m.text == "🕯️ Царская сводка" and m.chat.id == ADMIN_ID)
def show_stats(message):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT SUM(pay), COUNT(id) FROM shifts")
    total_pay, total_shifts = c.fetchone()
    c.execute("SELECT COUNT(id) FROM tasks WHERE status = 0")
    active_tasks = c.fetchone()[0]
    conn.close()
    bot.send_message(message.chat.id, f"🕯️ В казне: {total_pay or 0} ₽\nСмен: {total_shifts or 0}\nУказов: {active_tasks}", parse_mode="HTML")

@bot.message_handler(commands=['add'], func=lambda m: m.chat.id == ADMIN_ID)
def add_task(message):
    text = message.text.replace('/add', '').strip()
    if text:
        conn = sqlite3.connect(DB_PATH)
        conn.cursor().execute("INSERT INTO tasks (text) VALUES (?)", (text,))
        conn.commit(); conn.close()
        bot.reply_to(message, "📜 Указ принят!")
    else: bot.reply_to(message, "Текст после /add")

@bot.message_handler(func=lambda m: m.text == "📜 Список указов" and m.chat.id == ADMIN_ID)
def show_tasks(message):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, text FROM tasks WHERE status = 0")
    tasks = c.fetchall(); conn.close()
    if not tasks:
        bot.send_message(message.chat.id, "📜 Пусто.")
        return
    markup = types.InlineKeyboardMarkup(row_width=1)
    text = "📜 Указы:\n"
    for t in tasks:
        text += f"⚔️ {t[1]}\n"
        markup.add(types.InlineKeyboardButton(f"✅ {t[1][:15]}", callback_data=f"done_{t[0]}"))
    bot.send_message(message.chat.id, text, reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data.startswith('done_') and c.message.chat.id == ADMIN_ID)
def mark_done(call):
    task_id = call.data.split('_')[1]
    conn = sqlite3.connect(DB_PATH)
    conn.cursor().execute("UPDATE tasks SET status = 1 WHERE id = ?", (task_id,))
    conn.commit(); conn.close()
    bot.answer_callback_query(call.id, "Готово!")
    bot.delete_message(call.message.chat.id, call.message.message_id)

@bot.message_handler(commands=['note'], func=lambda m: m.chat.id == ADMIN_ID)
def add_note(message):
    text = message.text.replace('/note', '').strip()
    if text:
        conn = sqlite3.connect(DB_PATH)
        conn.cursor().execute("INSERT INTO notes (text) VALUES (?)", (text,))
        conn.commit(); conn.close()
        bot.reply_to(message, "📖 Записано.")
    else: bot.reply_to(message, "Текст после /note")

@bot.message_handler(func=lambda m: m.text == "📖 Рукописи" and m.chat.id == ADMIN_ID)
def show_notes(message):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT text FROM notes")
    notes = c.fetchall(); conn.close()
    if not notes: bot.send_message(message.chat.id, "📖 Пусто.")
    else: bot.send_message(message.chat.id, "📖 Записи:\n\n" + "\n".join([f"🖋️ {n[0]}" for n in notes]))

@bot.message_handler(commands=['remind'], func=lambda m: m.chat.id == ADMIN_ID)
def add_reminder(message):
    parts = message.text.replace('/remind', '').strip().split(' ', 2)
    if len(parts) < 3:
        bot.reply_to(message, "Формат: /remind ГГГГ-ММ-ДД ЧЧ:ММ Текст")
        return
    try:
        datetime.strptime(f"{parts[0]} {parts[1]}", "%Y-%m-%d %H:%M")
        conn = sqlite3.connect(DB_PATH)
        conn.cursor().execute("INSERT INTO reminders (id, text, time) VALUES (?, ?, ?)", (str(time.time()), parts[2], f"{parts[0]} {parts[1]}"))
        conn.commit(); conn.close()
        bot.reply_to(message, f"🕊️ Напомню в {parts[0]} {parts[1]}")
    except: bot.reply_to(message, "❌ Ошибка формата.")

@bot.message_handler(func=lambda m: m.text == "🕊️ Гонцы" and m.chat.id == ADMIN_ID)
def show_reminders(message):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT text, time FROM reminders WHERE is_sent = 0 ORDER BY time ASC")
    rems = c.fetchall(); conn.close()
    if not rems: bot.send_message(message.chat.id, "🕊️ Гонцов нет.")
    else: bot.send_message(message.chat.id, "🕊️ Гонцы:\n\n" + "\n".join([f"📅 {r[1]} — {r[0]}" for r in rems]))

def check_reminders():
    while True:
        try:
            now = datetime.now().strftime("%Y-%m-%d %H:%M")
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("SELECT id, text FROM reminders WHERE time <= ? AND is_sent = 0", (now,))
            due = c.fetchall()
            for r in due:
                bot.send_message(ADMIN_ID, f"🔔 <b>ГОНЕЦ:</b> {html.escape(r[1])}", parse_mode="HTML")
                c.execute("UPDATE reminders SET is_sent = 1 WHERE id = ?", (r[0],))
            conn.commit(); conn.close()
        except: pass
        time.sleep(30)

# --- ЗАГЛУШКА ДЛЯ RENDER (чтобы он не ругался на порт) ---
class DummyServer(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

def run_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(('0.0.0.0', port), DummyServer)
    server.serve_forever()

def main():
    print("=== СТАРТ БОТА ===", flush=True)
    init_db()
    threading.Thread(target=check_reminders, daemon=True).start()
    threading.Thread(target=run_server, daemon=True).start()
    print("=== СЕРВЕР ЗАПУЩЕН, ЖДУ КОМАНД ===", flush=True)
    try:
        bot.infinity_polling(timeout=20, long_polling_timeout=10)
    except Exception as e:
        print(f"!!! ОШИБКА БОТА !!!\n{traceback.format_exc()}", flush=True)

if __name__ == "__main__":
    main()
