import os
import html
import threading
import sqlite3
from datetime import datetime, timedelta
import time
import traceback
import requests
import telebot
from telebot import types
from http.server import BaseHTTPRequestHandler, HTTPServer

# --- ТОКЕНЫ ---
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
ADMIN_ID = 6385559900

if not TELEGRAM_BOT_TOKEN: raise RuntimeError("НЕТ ТОКЕНА БОТА")
if not OPENROUTER_API_KEY: raise RuntimeError("НЕТ КЛЮЧА OPENROUTER")

# --- МОДЕЛЬ OPENROUTER ---
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL_NAME = "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free"

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
    c.execute('''CREATE TABLE IF NOT EXISTS vakhta (id INTEGER PRIMARY KEY CHECK (id = 1), start_date TEXT, end_date TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS expenses (id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT, amount INTEGER, description TEXT)''')
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
        types.KeyboardButton("🕊️ Гонцы"),
        types.KeyboardButton("⚔️ Царская вахта"),
        types.KeyboardButton("💸 Траты из казны"),
        types.KeyboardButton("💰 Прибыток за вахту"),
        types.KeyboardButton("💣 Служба завтра")
    )
    return markup

@bot.message_handler(func=lambda m: m.chat.id != ADMIN_ID, content_types=['text', 'photo', 'video', 'document', 'voice'])
def deny_access(message):
    bot.send_message(message.chat.id, "⛔ <b>Прочь, смертный.</b>", parse_mode="HTML")

@bot.message_handler(commands=['start', 'menu'], func=lambda m: m.chat.id == ADMIN_ID)
def start(message):
    text = ("👑 <b>Да здравствует Царь-батюшка!</b>\n\nТвой верный слуга приветствует тебя. Изволь выбрать, что прикажешь:\n\n"
            "🏰 <b>Пополнить казну</b> — внести данные о службе.\n"
            "🧠 <b>Спросить советника</b> — вопросить мудрость.\n"
            "🕯️ <b>Царская сводка</b> — узреть статистику за всё время.\n"
            "📜 <b>Список указов</b> — добавить задачу (через /add).\n"
            "📖 <b>Рукописи</b> — записать заметку (через /note).\n"
            "🕊️ <b>Гонцы</b> — поставить напоминание (через /remind).\n"
            "⚔️ <b>Царская вахта</b> — узреть сроки службы.\n"
            "💸 <b>Траты из казны</b> — записать издержки.\n"
            "💰 <b>Прибыток за вахту</b> — узреть чистую монету.\n"
            "💣 <b>Служба завтра</b> — послать гонца с напоминанием.")
    bot.send_message(message.chat.id, text, parse_mode="HTML", reply_markup=get_main_menu())

@bot.message_handler(content_types=['voice'])
def handle_voice(message):
    if message.chat.id == ADMIN_ID:
        bot.send_message(message.chat.id, "🎙️ Государь, голосовые пока в опале, изволь писать текстом.")

# --- ИИ ---
@bot.message_handler(func=lambda m: m.chat.id == ADMIN_ID and m.text and not m.text.startswith('/') and m.text not in [
    "🏰 Пополнить казну", "🧠 Спросить советника", "🕯️ Царская сводка", 
    "📜 Список указов", "📖 Рукописи", "🕊️ Гонцы", "⚔️ Царская вахта", 
    "💸 Траты из казны", "💰 Прибыток за вахту", "💣 Служба завтра"
])
def process_ai_question(message):
    msg = bot.send_message(message.chat.id, "⏳ <i>Слуга твой ищет ответ в древних свитках...</i>", parse_mode="HTML")
    try:
        headers = {"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"}
        payload = {
            "model": MODEL_NAME,
            "messages": [{"role": "system", "content": AI_PERSONA}, {"role": "user", "content": message.text}],
            "max_tokens": 1000
        }
        response = requests.post(OPENROUTER_URL, headers=headers, json=payload, timeout=60)
        if response.status_code != 200:
            bot.edit_message_text(f"❌ Смилуйся, государь. Ошибка ({response.status_code}): {html.escape(response.text[:200])}", chat_id=message.chat.id, message_id=msg.message_id, parse_mode="HTML")
            return
        data = response.json()
        reply_text = data['choices'][0]['message']['content'] or "Смилуйся, государь, но летописи молчат."
        display_text = reply_text if len(reply_text) <= 3500 else reply_text[:3500] + "..."
        bot.edit_message_text(html.escape(display_text), chat_id=message.chat.id, message_id=msg.message_id, parse_mode="HTML")
    except Exception as e:
        bot.edit_message_text(f"❌ Смилуйся, государь. Ошибка: {html.escape(str(e)[:150])}", chat_id=message.chat.id, message_id=msg.message_id, parse_mode="HTML")

@bot.message_handler(func=lambda m: m.text == "🧠 Спросить советника" and m.chat.id == ADMIN_ID)
def ask_ai_start(message):
    bot.send_message(message.chat.id, "🧠 <b>Изволь задать вопрос, государь.</b> Твой слуга внимает.", parse_mode="HTML")

# --- КАЗНА ---
@bot.message_handler(func=lambda m: m.text == "🏰 Пополнить казну" and m.chat.id == ADMIN_ID)
def start_shift_report(message):
    user_data[message.chat.id] = {}
    msg = bot.send_message(message.chat.id, "⚖️ <b>Царь-батюшка, приступим к учёту казны.</b>\n\nСколько часов изволили отслужить во благо?", parse_mode="HTML")
    bot.register_next_step_handler(msg, process_hours)

def process_hours(message):
    try:
        hours = float(message.text.replace(',', '.'))
        user_data[message.chat.id]['hours'] = hours
        msg = bot.send_message(message.chat.id, "📦 <b>А сколько доставок совершили, государь?</b>", parse_mode="HTML")
        bot.register_next_step_handler(msg, process_orders)
    except:
        bot.send_message(message.chat.id, "❌ Смилуйся, государь, но мне нужны только цифры.", reply_markup=get_main_menu())

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
        bot.send_message(message.chat.id, f"📊 <b>Предварительный расчёт:</b>\nБаза: {int(base_pay)} ₽\n\nИзволите добавить надбавки?", parse_mode="HTML", reply_markup=markup)
    except:
        bot.send_message(message.chat.id, "❌ Смилуйся, государь, но мне нужны только цифры.", reply_markup=get_main_menu())

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
        bot.edit_message_text(f"✅ <b>Летопись обновлена!</b>\n🏰 В казну добавлено {int(base_pay)} ₽. Твой слуга служит верой и правдой!", chat_id=call.message.chat.id, message_id=call.message.message_id, parse_mode="HTML")
        return
    total = int(base_pay + bonus)
    markup = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("✅ Начертать в летописи", callback_data=f"confirm_save_{total}"))
    bot.edit_message_text(f"⚖️ <b>Итог службы:</b>\n➕ {bonus_text} (+{int(bonus)} ₽)\n🏰 <b>ИТОГО: {total} ₽</b>", chat_id=call.message.chat.id, message_id=call.message.message_id, parse_mode="HTML", reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data.startswith('confirm_save_') and c.message.chat.id == ADMIN_ID)
def confirm_save(call):
    try:
        total = int(call.data.split('_')[2])
        save_shift_to_db(call.message.chat.id, total)
        bot.edit_message_text(f"✅ <b>Служба записана в летопись!</b>\n🏰 В казну добавлено {total} ₽.", chat_id=call.message.chat.id, message_id=call.message.message_id, parse_mode="HTML")
    except: pass

def save_shift_to_db(chat_id, pay):
    conn = sqlite3.connect(DB_PATH)
    conn.cursor().execute("INSERT INTO shifts (date, pay) VALUES (?, ?)", (datetime.now().strftime("%d.%m.%Y"), pay))
    conn.commit(); conn.close()
    if chat_id in user_data: del user_data[chat_id]

# --- СВОДКА (общая) ---
@bot.message_handler(func=lambda m: m.text == "🕯️ Царская сводка" and m.chat.id == ADMIN_ID)
def show_stats(message):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT SUM(pay), COUNT(id) FROM shifts")
    total_pay, total_shifts = c.fetchone()
    c.execute("SELECT COUNT(id) FROM tasks WHERE status = 0")
    active_tasks = c.fetchone()[0]
    conn.close()
    bot.send_message(message.chat.id, f"🕯️ <b>Сводка из царских архивов:</b>\n\n🏦 Всего в казне: {total_pay or 0} ₽\n📅 Отработано смен: {total_shifts or 0}\n📜 Указов в ожидании: {active_tasks}", parse_mode="HTML")
                            # --- ВАХТА ---
@bot.message_handler(func=lambda m: m.text == "⚔️ Царская вахта" and m.chat.id == ADMIN_ID)
def vakhta_menu(message):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT start_date, end_date FROM vakhta WHERE id = 1")
    row = c.fetchone()
    conn.close()
    if row:
        start, end = row
        try:
            d2 = datetime.strptime(end, "%d.%m.%Y")
            today = datetime.now()
            left = (d2 - today).days
            if left < 0:
                status = "Вахта завершена, государь. Изволь отдохнуть."
            else:
                status = f"Осталось нести службу: <b>{left} дней</b>."
            text = f"⚔️ <b>Текущая вахта:</b>\nС {start} по {end}\n{status}\n\nИзволишь переустановить сроки? Напиши /set_vakhta"
        except:
            text = "❌ Смилуйся, государь, но в датах вышла путаница. Переустанови через /set_vakhta"
    else:
        text = "⚔️ Государь, сроки вахты ещё не начертаны.\nИзволь написать /set_vakhta, чтобы задать даты."
    bot.send_message(message.chat.id, text, parse_mode="HTML")

@bot.message_handler(commands=['set_vakhta'], func=lambda m: m.chat.id == ADMIN_ID)
def set_vakhta_start(message):
    msg = bot.send_message(message.chat.id, "📅 <b>Соизволь молвить, с какого дня начинается служба? (ДД.ММ.ГГГГ)</b>", parse_mode="HTML")
    bot.register_next_step_handler(msg, set_vakhta_end)

def set_vakhta_end(message):
    start_date = message.text.strip()
    try:
        datetime.strptime(start_date, "%d.%m.%Y")
    except:
        bot.send_message(message.chat.id, "❌ Смилуйся, государь, формат не тот. Начни заново /set_vakhta")
        return
    msg = bot.send_message(message.chat.id, "📅 <b>А когда изволишь вернуться? (ДД.ММ.ГГГГ)</b>", parse_mode="HTML")
    bot.register_next_step_handler(msg, save_vakhta, start_date)

def save_vakhta(message, start_date):
    end_date = message.text.strip()
    try:
        datetime.strptime(end_date, "%d.%m.%Y")
    except:
        bot.send_message(message.chat.id, "❌ Смилуйся, государь, формат не тот. Начни заново /set_vakhta")
        return
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("REPLACE INTO vakhta (id, start_date, end_date) VALUES (1, ?, ?)", (start_date, end_date))
    conn.commit(); conn.close()
    bot.send_message(message.chat.id, f"✅ Сроки вахты начертаны: с {start_date} по {end_date}!", reply_markup=get_main_menu())

# --- РАСХОДЫ ---
@bot.message_handler(func=lambda m: m.text == "💸 Траты из казны" and m.chat.id == ADMIN_ID)
def expense_menu(message):
    msg = bot.send_message(message.chat.id, "💰 <b>Изволь назвать, сколько монет изволил потратить?</b>", parse_mode="HTML")
    bot.register_next_step_handler(msg, process_expense_amount)

def process_expense_amount(message):
    try:
        amount = int(message.text)
        user_data[message.chat.id] = {'expense_amount': amount}
        msg = bot.send_message(message.chat.id, "📝 <b>На какие нужды изволил потратить?</b>", parse_mode="HTML")
        bot.register_next_step_handler(msg, process_expense_desc)
    except:
        bot.send_message(message.chat.id, "❌ Смилуйся, государь, но мне нужны только цифры.", reply_markup=get_main_menu())

def process_expense_desc(message):
    desc = message.text.strip()
    amount = user_data[message.chat.id].get('expense_amount', 0)
    conn = sqlite3.connect(DB_PATH)
    conn.cursor().execute("INSERT INTO expenses (date, amount, description) VALUES (?, ?, ?)", (datetime.now().strftime("%d.%m.%Y"), amount, desc))
    conn.commit(); conn.close()
    bot.send_message(message.chat.id, f"✅ Записано: {amount} ₽ на «{html.escape(desc)}».", parse_mode="HTML", reply_markup=get_main_menu())
    if message.chat.id in user_data: del user_data[message.chat.id]

# --- СВОДКА ЗА ВАХТУ ---
@bot.message_handler(func=lambda m: m.text == "💰 Прибыток за вахту" and m.chat.id == ADMIN_ID)
def vakhta_stats(message):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT start_date, end_date FROM vakhta WHERE id = 1")
    row = c.fetchone()
    if not row:
        bot.send_message(message.chat.id, "❌ Государь, сроки вахты не установлены. Изволь сначала задать их через ⚔️ Царская вахта.", parse_mode="HTML")
        conn.close()
        return
    start_date, end_date = row
    try:
        c.execute("SELECT SUM(pay) FROM shifts WHERE date >= ?", (start_date,))
        earned = c.fetchone()[0] or 0
        c.execute("SELECT SUM(amount) FROM expenses WHERE date >= ?", (start_date,))
        spent = c.fetchone()[0] or 0
        conn.close()
        net = earned - spent
        text = (f"💰 <b>Итог службы за вахту</b> (с {start_date}):\n\n"
                f"🏦 В казну прибыло: <b>{earned} ₽</b>\n"
                f"💸 Из казны убыло: <b>{spent} ₽</b>\n"
                f"📈 Чистый доход: <b>{net} ₽</b>")
        bot.send_message(message.chat.id, text, parse_mode="HTML")
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Смилуйся, государь, летописи запутались. Ошибка: {e}")

# --- СМЕНА ЗАВТРА ---
@bot.message_handler(func=lambda m: m.text == "💣 Служба завтра" and m.chat.id == ADMIN_ID)
def remind_shift_tomorrow(message):
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    remind_time = f"{tomorrow} 18:00"
    text = "Гонец донес: завтра изволишь нести службу. Не изволь опоздать, государь!"
    conn = sqlite3.connect(DB_PATH)
    conn.cursor().execute("INSERT INTO reminders (id, text, time) VALUES (?, ?, ?)", (str(time.time()), text, remind_time))
    conn.commit(); conn.close()
    bot.send_message(message.chat.id, f"🕊️ Гонец отправлен. Извещу тебя завтра о службе.", reply_markup=get_main_menu())

# --- УКАЗЫ ---
@bot.message_handler(commands=['add'], func=lambda m: m.chat.id == ADMIN_ID)
def add_task(message):
    text = message.text.replace('/add', '').strip()
    if text:
        conn = sqlite3.connect(DB_PATH)
        conn.cursor().execute("INSERT INTO tasks (text) VALUES (?)", (text,))
        conn.commit(); conn.close()
        bot.send_message(message.chat.id, "📜 <b>Указ принят!</b> Твой слуга внёс его в список.", parse_mode="HTML")
    else: bot.send_message(message.chat.id, "Царь-батюшка, соизволь написать текст указа после /add")

@bot.message_handler(func=lambda m: m.text == "📜 Список указов" and m.chat.id == ADMIN_ID)
def show_tasks(message):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, text FROM tasks WHERE status = 0")
    tasks = c.fetchall(); conn.close()
    if not tasks:
        bot.send_message(message.chat.id, "📜 <b>Список указов пуст.</b> Напиши /add [текст], чтобы издать новый.", parse_mode="HTML")
        return
    markup = types.InlineKeyboardMarkup(row_width=1)
    text = "📜 <b>Твои указы на сегодня:</b>\n\n"
    for t in tasks:
        text += f"⚔️ {t[1]}\n"
        markup.add(types.InlineKeyboardButton(f"✅ Исполнено: {t[1][:15]}", callback_data=f"done_{t[0]}"))
    bot.send_message(message.chat.id, text, parse_mode="HTML", reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data.startswith('done_') and c.message.chat.id == ADMIN_ID)
def mark_done(call):
    task_id = call.data.split('_')[1]
    conn = sqlite3.connect(DB_PATH)
    conn.cursor().execute("UPDATE tasks SET status = 1 WHERE id = ?", (task_id,))
    conn.commit(); conn.close()
    bot.answer_callback_query(call.id, "Слушаюсь!")
    bot.delete_message(call.message.chat.id, call.message.message_id)
    bot.send_message(call.message.chat.id, "✅ <b>Указ исполнен.</b>", parse_mode="HTML")

# --- РУКОПИСИ ---
@bot.message_handler(commands=['note'], func=lambda m: m.chat.id == ADMIN_ID)
def add_note(message):
    text = message.text.replace('/note', '').strip()
    if text:
        conn = sqlite3.connect(DB_PATH)
        conn.cursor().execute("INSERT INTO notes (text) VALUES (?)", (text,))
        conn.commit(); conn.close()
        bot.send_message(message.chat.id, "📖 <b>Запись сохранена.</b>", parse_mode="HTML")
    else: bot.send_message(message.chat.id, "Царь-батюшка, напиши текст после /note")

@bot.message_handler(func=lambda m: m.text == "📖 Рукописи" and m.chat.id == ADMIN_ID)
def show_notes(message):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT text FROM notes")
    notes = c.fetchall(); conn.close()
    if not notes: bot.send_message(message.chat.id, "📖 <b>Рукописи пусты.</b> Начертать новое: /note [текст]", parse_mode="HTML")
    else: bot.send_message(message.chat.id, "📖 <b>Твои рукописи:</b>\n\n" + "\n".join([f"🖋️ {html.escape(n[0])}" for n in notes]), parse_mode="HTML")

# --- НАПОМИНАНИЯ ---
@bot.message_handler(commands=['remind'], func=lambda m: m.chat.id == ADMIN_ID)
def add_reminder(message):
    parts = message.text.replace('/remind', '').strip().split(' ', 2)
    if len(parts) < 3:
        bot.send_message(message.chat.id, "Изволь писать так: /remind ГГГГ-ММ-ДД ЧЧ:ММ Текст")
        return
    try:
        datetime.strptime(f"{parts[0]} {parts[1]}", "%Y-%m-%d %H:%M")
        conn = sqlite3.connect(DB_PATH)
        conn.cursor().execute("INSERT INTO reminders (id, text, time) VALUES (?, ?, ?)", (str(time.time()), parts[2], f"{parts[0]} {parts[1]}"))
        conn.commit(); conn.close()
        bot.send_message(message.chat.id, f"🕊️ <b>Гонец отправлен.</b> В {parts[0]} {parts[1]} я извещу тебя, государь.", parse_mode="HTML")
    except: bot.send_message(message.chat.id, "❌ Ошибка в датах. Изволь писать так: /remind ГГГГ-ММ-ДД ЧЧ:ММ Текст")

@bot.message_handler(func=lambda m: m.text == "🕊️ Гонцы" and m.chat.id == ADMIN_ID)
def show_reminders(message):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT text, time FROM reminders WHERE is_sent = 0 ORDER BY time ASC")
    rems = c.fetchall(); conn.close()
    if not rems: bot.send_message(message.chat.id, "🕊️ <b>Гонцов в пути нет.</b> Чтобы послать: /remind [дата] [время] [текст]", parse_mode="HTML")
    else: bot.send_message(message.chat.id, "🕊️ <b>Ожидающие гонцы:</b>\n\n" + "\n".join([f"📅 {r[1]} — {html.escape(r[0])}" for r in rems]), parse_mode="HTML")

def check_reminders():
    while True:
        try:
            now = datetime.now().strftime("%Y-%m-%d %H:%M")
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("SELECT id, text FROM reminders WHERE time <= ? AND is_sent = 0", (now,))
            due = c.fetchall()
            for r in due:
                bot.send_message(ADMIN_ID, f"🔔 <b>ВНИМАНИЕ, ЦАРЬ-БАТЮШКА! ГОНЕЦ ПРИБЫЛ:</b>\n\n{html.escape(r[1])}", parse_mode="HTML")
                c.execute("UPDATE reminders SET is_sent = 1 WHERE id = ?", (r[0],))
            conn.commit(); conn.close()
        except: pass
        time.sleep(30)

# --- ЗАГЛУШКА ДЛЯ RENDER ---
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
    print("=== СТАРТ БОТА ===")
    init_db()
    threading.Thread(target=check_reminders, daemon=True).start()
    threading.Thread(target=run_server, daemon=True).start()
    
    print("=== ОЧИСТКА ВЕБХУКА ===")
    bot.remove_webhook()
    try:
        bot.delete_webhook(drop_pending_updates=True)
    except Exception as e:
        print(f"Очистка не удалась: {e}")

    print("=== СЕРВЕР ЗАПУЩЕН ===")
    time.sleep(3)
    
    try:
        bot.infinity_polling(timeout=20, long_polling_timeout=10, skip_pending=True)
    except Exception as e:
        print(f"!!! ОШИБКА БОТА !!! {traceback.format_exc()}")

if __name__ == "__main__":
    main()
