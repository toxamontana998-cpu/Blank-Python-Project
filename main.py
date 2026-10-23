import os
import threading
from flask import Flask
import telebot
from telebot import types
import sqlite3
from datetime import datetime
import time

# --- ТОКЕН ---
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
ADMIN_ID = 6385559900

if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError("Set TELEGRAM_BOT_TOKEN")

bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)
app = Flask(__name__)
DB_PATH = 'personal_assistant.db'

# --- БАЗА ДАННЫХ ---
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS tasks (id INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT, status INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS shifts (id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT, pay INTEGER)''')
    c.execute('''CREATE TABLE IF NOT EXISTS reminders (id INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT, time TEXT, is_sent INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS notes (id INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT)''')
    conn.commit()
    conn.close()

@app.route('/')
def home():
    return "Personal Assistant is alive!"

# --- ЗАЩИТА ОТ ПОСТОРОННИХ ---
@bot.message_handler(func=lambda message: message.chat.id != ADMIN_ID, content_types=['text', 'photo', 'video', 'document'])
def deny_access(message):
    bot.send_message(message.chat.id, "⛔ Прочь, смертный. Сии покои доступны лишь Царю-батюшке.")

# --- МЕНЮ ---
def get_main_menu():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        types.KeyboardButton("👑 Внести смену"),
        types.KeyboardButton("📜 Статистика"),
        types.KeyboardButton("✍️ Издать указ"),
        types.KeyboardButton("📜 Скрижали"),
        types.KeyboardButton("🕊️ Послать гонца")
    )
    return markup

@bot.message_handler(commands=['start', 'menu'], func=lambda message: message.chat.id == ADMIN_ID)
def start(message):
    text = ("👑 **Да здравствует Царь-батюшка!**\n\n"
            "Твой верный цифровой холоп готов к службе. Изволь выбрать, что прикажешь сделать:\n\n"
            "👑 **Внести смену** — записать доход в казну.\n"
            "📜 **Статистика** — посмотреть сводку из архивов.\n"
            "✍️ **Издать указ** — добавить задачу (через /add).\n"
            "📜 **Скрижали** — прочесть или записать заметку (через /note).\n"
            "🕊️ **Послать гонца** — поставить напоминание (через /remind).")
    bot.send_message(message.chat.id, text, parse_mode="Markdown", reply_markup=get_main_menu())

# --- ФИЧА 1: УЧЕТ СМЕН ---
@bot.message_handler(func=lambda message: message.text == "👑 Внести смену" and message.chat.id == ADMIN_ID)
def quick_shift_calc(message):
    STD_HOURS = 12
    STD_ORDERS = 54
    base_pay = (STD_HOURS * 110) + (STD_ORDERS * 35) + (STD_HOURS * 10)
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("🌧 + Осадки (540р)", callback_data="shift_rain"),
        types.InlineKeyboardButton("📅 + Выходной (180р)", callback_data="shift_weekend"),
        types.InlineKeyboardButton("🔥 + Всё сразу (720р)", callback_data="shift_both"),
        types.InlineKeyboardButton("✅ Внести в летопись", callback_data="shift_save")
    )
    
    text = (f"👑 **Ваша смена, Царь-батюшка:**\n"
            f"⏱ {STD_HOURS} ч | 📦 {STD_ORDERS} заказов\n\n"
            f"💵 Казна пополнится на: {base_pay} ₽\n\n"
            f"Соизволите добавить бонусы?")
    bot.send_message(message.chat.id, text, parse_mode="Markdown", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('shift_') and call.message.chat.id == ADMIN_ID)
def process_shift_bonus(call):
    STD_HOURS = 12
    STD_ORDERS = 54
    base_pay = (STD_HOURS * 110) + (STD_ORDERS * 35) + (STD_HOURS * 10)
    
    if call.data == "shift_save":
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        today = datetime.now().strftime("%d.%m")
        c.execute("INSERT INTO shifts (date, pay) VALUES (?, ?)", (today, base_pay))
        conn.commit(); conn.close()
        bot.answer_callback_query(call.id, "Внесено в летопись!")
        bot.edit_message_text(f"✅ Смена записана в летопись, Царь-батюшка. Казна пополнена на {base_pay} ₽.", 
                              chat_id=call.message.chat.id, message_id=call.message.message_id)
        return

    bonus = 0
    bonus_text = ""
    if call.data == "shift_rain": bonus = 540; bonus_text = "🌧 Осадки"
    elif call.data == "shift_weekend": bonus = 180; bonus_text = "📅 Выходной"
    elif call.data == "shift_both": bonus = 720; bonus_text = "🌧+📅"

    total = base_pay + bonus
    text = (f"👑 **Смена (Обновлено):**\n"
            f"➕ {bonus_text} (+{bonus} ₽)\n\n"
            f"💰 **ИТОГО В КАЗНУ: {total} ₽**")
    bot.edit_message_text(text, chat_id=call.message.chat.id, message_id=call.message.message_id, parse_mode="Markdown")

# --- СТАТИСТИКА ---
@bot.message_handler(func=lambda message: message.text == "📜 Статистика" and message.chat.id == ADMIN_ID)
def show_stats(message):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT SUM(pay), COUNT(id) FROM shifts")
    total_pay, total_shifts = c.fetchone()
    c.execute("SELECT COUNT(id) FROM tasks WHERE status = 0")
    active_tasks = c.fetchone()[0]
    conn.close()
    
    text = (f"📜 **Сводка из царских архивов:**\n\n"
            f"💰 Всего в казне: {total_pay or 0} ₽\n"
            f"📅 Отработано смен: {total_shifts or 0}\n"
            f"⚔️ Указов в ожидании: {active_tasks}\n\n"
            f"Царь-батюшка, вы велики!")
    bot.send_message(message.chat.id, text, parse_mode="Markdown")

# --- ЗАДАЧИ ---
@bot.message_handler(commands=['add'], func=lambda message: message.chat.id == ADMIN_ID)
def add_task(message):
    text = message.text.replace('/add', '').strip()
    if text:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("INSERT INTO tasks (text) VALUES (?)", (text,))
        conn.commit(); conn.close()
        bot.reply_to(message, f"⚔️ Указ принят и внесен в список дел, Царь-батюшка.")
    else:
        bot.reply_to(message, "Царь-батюшка, соизвольте написать текст указа после /add")

@bot.message_handler(func=lambda message: message.text == "✍️ Издать указ" and message.chat.id == ADMIN_ID)
def show_tasks(message):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, text FROM tasks WHERE status = 0")
    tasks = c.fetchall()
    conn.close()
    
    if not tasks:
        bot.send_message(message.chat.id, "⚔️ Список указов пуст, Царь-батюшка. Напиши `/add [текст]`, чтобы издать новый.")
        return
        
    markup = types.InlineKeyboardMarkup(row_width=1)
    text = "⚔️ **Ваши указы на сегодня:**\n\n"
    for t in tasks:
        text += f"• {t[1]}\n"
        markup.add(types.InlineKeyboardButton(f"✅ Исполнено: {t[1][:15]}", callback_data=f"done_{t[0]}"))
    bot.send_message(message.chat.id, text, parse_mode="Markdown", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('done_') and call.message.chat.id == ADMIN_ID)
def mark_done(call):
    task_id = call.data.split('_')[1]
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE tasks SET status = 1 WHERE id = ?", (task_id,))
    conn.commit(); conn.close()
    bot.answer_callback_query(call.id, "Слушаюсь, Царь-батюшка!")
    bot.delete_message(call.message.chat.id, call.message.message_id)
    bot.send_message(call.message.chat.id, "🗑 Указ исполнен и вычеркнут из списка.")

# --- ЗАМЕТКИ ---
@bot.message_handler(commands=['note'], func=lambda message: message.chat.id == ADMIN_ID)
def add_note(message):
    text = message.text.replace('/note', '').strip()
    if text:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("INSERT INTO notes (text) VALUES (?)", (text,))
        conn.commit(); conn.close()
        bot.reply_to(message, f"🖋️ Ваша запись навеки запечатлена на скрижалях, Царь-батюшка.")
    else:
        bot.reply_to(message, "Царь-батюшка, соизвольте написать текст после /note")

@bot.message_handler(func=lambda message: message.text == "📜 Скрижали" and message.chat.id == ADMIN_ID)
def show_notes(message):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, text FROM notes")
    notes = c.fetchall()
    conn.close()
    
    if not notes:
        bot.send_message(message.chat.id, "🖋️ Скрижали пусты. Начертать новое: `/note [текст]`", parse_mode="Markdown")
        return
        
    text = "🖋️ **Ваши скрижали:**\n\n"
    for n in notes:
        text += f"• {n[1]}\n"
    bot.send_message(message.chat.id, text, parse_mode="Markdown")

# --- НАПОМИНАНИЯ ---
@bot.message_handler(commands=['remind'], func=lambda message: message.chat.id == ADMIN_ID)
def add_reminder(message):
    parts = message.text.replace('/remind', '').strip().split(' ', 2)
    if len(parts) < 3:
        bot.reply_to(message, "Формат: `/remind ГГГГ-ММ-ДД ЧЧ:ММ Текст`\nПример: `/remind 2026-10-25 15:30 Купить хлеб`", parse_mode="Markdown")
        return
    
    time_str = f"{parts[0]} {parts[1]}"
    text = parts[2]
    
    try:
        datetime.strptime(time_str, "%Y-%m-%d %H:%M")
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("INSERT INTO reminders (text, time) VALUES (?, ?)", (text, time_str))
        conn.commit(); conn.close()
        bot.reply_to(message, f"🕊️ Гонец отправлен. В {time_str} я непременно извещу вас, Царь-батюшка.")
    except ValueError:
        bot.reply_to(message, "❌ Ошибка формата. Соизвольте использовать: ГГГГ-ММ-ДД ЧЧ:ММ")

@bot.message_handler(func=lambda message: message.text == "🕊️ Послать гонца" and message.chat.id == ADMIN_ID)
def show_reminders(message):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, text, time FROM reminders WHERE is_sent = 0 ORDER BY time ASC")
    rems = c.fetchall()
    conn.close()
    
    if not rems:
        bot.send_message(message.chat.id, "🕊️ Гонцов в пути нет. Чтобы послать: `/remind [дата] [время] [текст]`")
        return
        
    text = "🕊️ **Ожидающие гонцы:**\n\n"
    for r in rems:
        text += f"📅 {r[2]} — {r[1]}\n"
    bot.send_message(message.chat.id, text, parse_mode="Markdown")

# --- ФОНОВЫЙ ПРОЦЕСС НАПОМИНАНИЙ ---
def check_reminders():
    while True:
        try:
            now = datetime.now().strftime("%Y-%m-%d %H:%M")
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("SELECT id, text FROM reminders WHERE time <= ? AND is_sent = 0", (now,))
            due = c.fetchall()
            for r in due:
                bot.send_message(ADMIN_ID, f"🔔 **ВНИМАНИЕ, ЦАРЬ-БАТЮШКА! ГОНЕЦ ПРИБЫЛ:**\n{r[1]}", parse_mode="Markdown")
                c.execute("UPDATE reminders SET is_sent = 1 WHERE id = ?", (r[0],))
            conn.commit()
            conn.close()
        except Exception:
            pass
        time.sleep(30) 

def main():
    init_db()
    threading.Thread(target=check_reminders, daemon=True).start()
    
    def run_flask():
        port = int(os.environ.get('PORT', 8080))
        app.run(host='0.0.0.0', port=port)
    threading.Thread(target=run_flask).start()
    bot.infinity_polling(timeout=20, long_polling_timeout=10)

if __name__ == "__main__":
    main()
