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

user_data = {}

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
    bot.send_message(message.chat.id, "⛔ **Прочь, смертный.** Сии покои доступны лишь Царю-батюшке.")

# --- МЕНЮ ---
def get_main_menu():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        types.KeyboardButton("🏰 Пополнить казну"),
        types.KeyboardButton("🕯️ Царская сводка"),
        types.KeyboardButton("📜 Список указов"),
        types.KeyboardButton("📖 Рукописи"),
        types.KeyboardButton("🕊️ Гонцы")
    )
    return markup

@bot.message_handler(commands=['start', 'menu'], func=lambda message: message.chat.id == ADMIN_ID)
def start(message):
    text = ("👑 **Да здравствует Царь-батюшка!**\n\n"
            "Твой верный цифровой холоп готов к службе. Изволь выбрать, что прикажешь:\n\n"
            "🏰 **Пополнить казну** — внести данные о службе.\n"
            "🕯️ **Царская сводка** — узреть статистику из архивов.\n"
            "📜 **Список указов** — добавить задачу (через `/add`).\n"
            "📖 **Рукописи** — записать заметку (через `/note`).\n"
            "🕊️ **Гонцы** — поставить напоминание (через `/remind`).")
    bot.send_message(message.chat.id, text, parse_mode="Markdown", reply_markup=get_main_menu())

# --- УЧЕТ КАЗНЫ (СТАРОРУССКИЙ ДИАЛОГ) ---
@bot.message_handler(func=lambda message: message.text == "🏰 Пополнить казну" and message.chat.id == ADMIN_ID)
def start_shift_report(message):
    user_data[message.chat.id] = {}
    msg = bot.send_message(message.chat.id, "⚖️ **Царь-батюшка, приступим к учету казны.**\n\nСколько часов изволили отслужить во благо? (Напиши число, например: 8 или 10.5)")
    bot.register_next_step_handler(msg, process_hours)

def process_hours(message):
    try:
        hours = float(message.text.replace(',', '.'))
        user_data[message.chat.id]['hours'] = hours
        msg = bot.send_message(message.chat.id, "📦 А сколько доставок совершили, государь? (Напиши число, например: 40)")
        bot.register_next_step_handler(msg, process_orders)
    except ValueError:
        bot.send_message(message.chat.id, "❌ Смилуйся, государь, но мне нужны только цифры. Напиши число (например, 8).", reply_markup=get_main_menu())

def process_orders(message):
    try:
        orders = int(message.text)
        user_data[message.chat.id]['orders'] = orders
        
        hours = user_data[message.chat.id]['hours']
        base_pay = (hours * 110) + (orders * 35)
        user_data[message.chat.id]['base_pay'] = base_pay
        
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            types.InlineKeyboardButton("🌧 За непогоду (+10р/доставка)", callback_data="shift_rain"),
            types.InlineKeyboardButton("📅 За выходной день (+15р/час)", callback_data="shift_weekend"),
            types.InlineKeyboardButton("🔥 За тяжкий труд 70ч (+10р/час)", callback_data="shift_70h"),
            types.InlineKeyboardButton("💎 За все тяготы сразу", callback_data="shift_all"),
            types.InlineKeyboardButton("⚖️ Внести в летопись без надбавок", callback_data="shift_save_base")
        )
        
        text = (f"📊 **Предварительный расчет казны:**\n"
                f"⏱ Время службы: {hours} ч\n"
                f"📦 Доставлено заказов: {orders}\n"
                f"💵 Базовое жалование: {base_pay} ₽\n\n"
                f"Изволите добавить надбавки за тяготы службы?")
        bot.send_message(message.chat.id, text, parse_mode="Markdown", reply_markup=markup)
    except ValueError:
        bot.send_message(message.chat.id, "❌ Смилуйся, государь, но мне нужны только цифры. Напиши число (например, 40).", reply_markup=get_main_menu())

@bot.callback_query_handler(func=lambda call: call.data.startswith('shift_') and call.message.chat.id == ADMIN_ID)
def process_shift_bonus(call):
    data = user_data.get(call.message.chat.id)
    if not data:
        bot.answer_callback_query(call.id, "Ошибка. Начни заново.")
        return

    base_pay = data['base_pay']
    hours = data['hours']
    orders = data['orders']
    bonus = 0
    bonus_text = ""

    if call.data == "shift_rain":
        bonus = orders * 10
        bonus_text = "🌧 Надбавка за непогоду"
    elif call.data == "shift_weekend":
        bonus = hours * 15
        bonus_text = "📅 Надбавка за выходной день"
    elif call.data == "shift_70h":
        bonus = hours * 10
        bonus_text = "🔥 Надбавка за 70 часов"
    elif call.data == "shift_all":
        bonus = (orders * 10) + (hours * 15) + (hours * 10)
        bonus_text = "💎 Все надбавки"
    elif call.data == "shift_save_base":
        save_shift_to_db(call.message.chat.id, base_pay)
        bot.edit_message_text(f"✅ **Летопись обновлена!**\n🏰 Царь-батюшка, в казну добавлено {base_pay} ₽. Служу верой и правдой!", 
                              chat_id=call.message.chat.id, message_id=call.message.message_id, parse_mode="Markdown")
        return

    total = base_pay + bonus
    text = (f"⚖️ **Итог службы с надбавками:**\n"
            f"➕ {bonus_text} (+{bonus} ₽)\n\n"
            f"🏰 **ИТОГО В КАЗНУ: {total} ₽**")
    
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("✅ Начертать в летописи", callback_data=f"confirm_save_{total}"))
    
    bot.edit_message_text(text, chat_id=call.message.chat.id, message_id=call.message.message_id, parse_mode="Markdown", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('confirm_save_') and call.message.chat.id == ADMIN_ID)
def confirm_save(call):
    total = int(call.data.split('_')[2])
    save_shift_to_db(call.message.chat.id, total)
    bot.edit_message_text(f"✅ **Служба записана в летопись!**\n🏰 В казну добавлено {total} ₽.", 
                          chat_id=call.message.chat.id, message_id=call.message.message_id, parse_mode="Markdown")

def save_shift_to_db(chat_id, pay):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    today = datetime.now().strftime("%d.%m")
    c.execute("INSERT INTO shifts (date, pay) VALUES (?, ?)", (today, pay))
    conn.commit(); conn.close()
    if chat_id in user_data:
        del user_data[chat_id]

# --- СТАТИСТИКА ---
@bot.message_handler(func=lambda message: message.text == "🕯️ Царская сводка" and message.chat.id == ADMIN_ID)
def show_stats(message):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT SUM(pay), COUNT(id) FROM shifts")
    total_pay, total_shifts = c.fetchone()
    c.execute("SELECT COUNT(id) FROM tasks WHERE status = 0")
    active_tasks = c.fetchone()[0]
    conn.close()
    
    text = (f"🕯️ **Сводка из царских архивов:**\n\n"
            f"🏦 Всего в казне: {total_pay or 0} ₽\n"
            f"📅 Отработано смен: {total_shifts or 0}\n"
            f"📜 Указов в ожидании: {active_tasks}\n\n"
            f"Царь-батюшка, вы велики!")
    bot.send_message(message.chat.id, text, parse_mode="Markdown")

# --- УКАЗЫ (ЗАДАЧИ) ---
@bot.message_handler(commands=['add'], func=lambda message: message.chat.id == ADMIN_ID)
def add_task(message):
    text = message.text.replace('/add', '').strip()
    if text:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("INSERT INTO tasks (text) VALUES (?)", (text,))
        conn.commit(); conn.close()
        bot.reply_to(message, f"📜 **Указ принят!** Внесен в список дел.")
    else:
        bot.reply_to(message, "Царь-батюшка, соизвольте написать текст указа после `/add`")

@bot.message_handler(func=lambda message: message.text == "📜 Список указов" and message.chat.id == ADMIN_ID)
def show_tasks(message):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, text FROM tasks WHERE status = 0")
    tasks = c.fetchall()
    conn.close()
    
    if not tasks:
        bot.send_message(message.chat.id, "📜 **Список указов пуст.** Напиши `/add [текст]`, чтобы издать новый.")
        return
        
    markup = types.InlineKeyboardMarkup(row_width=1)
    text = "📜 **Ваши указы на сегодня:**\n\n"
    for t in tasks:
        text += f"⚔️ {t[1]}\n"
        markup.add(types.InlineKeyboardButton(f"✅ Исполнено: {t[1][:15]}", callback_data=f"done_{t[0]}"))
    bot.send_message(message.chat.id, text, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('done_') and call.message.chat.id == ADMIN_ID)
def mark_done(call):
    task_id = call.data.split('_')[1]
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE tasks SET status = 1 WHERE id = ?", (task_id,))
    conn.commit(); conn.close()
    bot.answer_callback_query(call.id, "Слушаюсь!")
    bot.delete_message(call.message.chat.id, call.message.message_id)
    bot.send_message(call.message.chat.id, "✅ **Указ исполнен.**")

# --- РУКОПИСИ (ЗАМЕТКИ) ---
@bot.message_handler(commands=['note'], func=lambda message: message.chat.id == ADMIN_ID)
def add_note(message):
    text = message.text.replace('/note', '').strip()
    if text:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("INSERT INTO notes (text) VALUES (?)", (text,))
        conn.commit(); conn.close()
        bot.reply_to(message, f"📖 **Запись сохранена.**")
    else:
        bot.reply_to(message, "Царь-батюшка, напишите текст после `/note`")

@bot.message_handler(func=lambda message: message.text == "📖 Рукописи" and message.chat.id == ADMIN_ID)
def show_notes(message):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, text FROM notes")
    notes = c.fetchall()
    conn.close()
    
    if not notes:
        bot.send_message(message.chat.id, "📖 **Рукописи пусты.** Начертать новое: `/note [текст]`")
        return
        
    text = "📖 **Ваши рукописи:**\n\n"
    for n in notes:
        text += f"🖋️ {n[1]}\n"
    bot.send_message(message.chat.id, text)

# --- ГОНЦЫ (НАПОМИНАНИЯ) ---
@bot.message_handler(commands=['remind'], func=lambda message: message.chat.id == ADMIN_ID)
def add_reminder(message):
    parts = message.text.replace('/remind', '').strip().split(' ', 2)
    if len(parts) < 3:
        bot.reply_to(message, "Формат: `/remind ГГГГ-ММ-ДД ЧЧ:ММ Текст`\nПример: `/remind 2026-10-25 15:30 Купить хлеб`")
        return
    
    time_str = f"{parts[0]} {parts[1]}"
    text = parts[2]
    
    try:
        datetime.strptime(time_str, "%Y-%m-%d %H:%M")
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("INSERT INTO reminders (text, time) VALUES (?, ?)", (text, time_str))
        conn.commit(); conn.close()
        bot.reply_to(message, f"🕊️ **Гонец отправлен.** В {time_str} я извещу вас.")
    except ValueError:
        bot.reply_to(message, "❌ Ошибка формата. Используйте: ГГГГ-ММ-ДД ЧЧ:ММ")

@bot.message_handler(func=lambda message: message.text == "🕊️ Гонцы" and message.chat.id == ADMIN_ID)
def show_reminders(message):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, text, time FROM reminders WHERE is_sent = 0 ORDER BY time ASC")
    rems = c.fetchall()
    conn.close()
    
    if not rems:
        bot.send_message(message.chat.id, "🕊️ **Гонцов в пути нет.** Чтобы послать: `/remind [дата] [время] [текст]`")
        return
        
    text = "🕊️ **Ожидающие гонцы:**\n\n"
    for r in rems:
        text += f"📅 {r[2]} — {r[1]}\n"
    bot.send_message(message.chat.id, text)

# --- ФОН НАПОМИНАНИЙ ---
def check_reminders():
    while True:
        try:
            now = datetime.now().strftime("%Y-%m-%d %H:%M")
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("SELECT id, text FROM reminders WHERE time <= ? AND is_sent = 0", (now,))
            due = c.fetchall()
            for r in due:
                bot.send_message(ADMIN_ID, f"🔔 **ВНИМАНИЕ, ЦАРЬ-БАТЮШКА! ГОНЕЦ ПРИБЫЛ:**\n\n{r[1]}")
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
