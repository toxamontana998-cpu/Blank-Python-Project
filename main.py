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
    c.execute('''CREATE TABLE IF NOT EXISTS debts (id INTEGER PRIMARY KEY AUTOINCREMENT, type TEXT, name TEXT, amount INTEGER)''')
    c.execute('''CREATE TABLE IF NOT EXISTS bot_status (key TEXT PRIMARY KEY, value TEXT)''')
    
    c.execute("PRAGMA table_info(vakhta)")
    columns = [info[1] for info in c.fetchall()]
    if 'w_start' not in columns:
        c.execute("ALTER TABLE vakhta ADD COLUMN w_start TEXT")
    if 'w_end' not in columns:
        c.execute("ALTER TABLE vakhta ADD COLUMN w_end TEXT")
    if 'w_days' not in columns:
        c.execute("ALTER TABLE vakhta ADD COLUMN w_days TEXT")
        
    conn.commit()
    conn.close()

def get_main_menu():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        types.KeyboardButton("🏰 Пополнить казну"),
        types.KeyboardButton("🧠 Спросить советника"),
        types.KeyboardButton("🕯️ Царская сводка"),
        types.KeyboardButton("🪶 Список указов"),
        types.KeyboardButton("📖 Рукописи"),
        types.KeyboardButton("🕊️ Гонцы"),
        types.KeyboardButton("⚔️ Царская вахта"),
        types.KeyboardButton("💸 Траты из казны"),
        types.KeyboardButton("💰 Прибыток за вахту"),
        types.KeyboardButton("🔮 Предсказание прибытка"),
        types.KeyboardButton("💣 Служба завтра"),
        types.KeyboardButton("📕 Долговая книга"),
        types.KeyboardButton("📜 Свиток помощи")
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
            "🪶 <b>Список указов</b> — добавить задачу (через /add).\n"
            "📖 <b>Рукописи</b> — записать заметку (через /note).\n"
            "🕊️ <b>Гонцы</b> — поставить напоминание (через /remind).\n"
            "⚔️ <b>Царская вахта</b> — сроки и график службы.\n"
            "💸 <b>Траты из казны</b> — записать издержки.\n"
            "💰 <b>Прибыток за вахту</b> — узреть чистую монету.\n"
            "🔮 <b>Предсказание прибытка</b> — узреть, сколько привезёшь домой.\n"
            "💣 <b>Служба завтра</b> — послать гонца с напоминанием.\n"
            "📕 <b>Долговая книга</b> — учесть долги.\n\n"
            "📜 <i>Свиток со скрытыми командами — нажми кнопку «Свиток помощи» внизу.</i>")
    bot.send_message(message.chat.id, text, parse_mode="HTML", reply_markup=get_main_menu())

@bot.message_handler(func=lambda m: m.text == "📜 Свиток помощи" and m.chat.id == ADMIN_ID)
def help_button(message):
    text = ("📜 <b>Царские скрытые команды:</b>\n\n"
            "🔹 /add [текст] — издать новый указ\n"
            "🔹 /note [текст] — записать в рукописи\n"
            "🔹 /remind ГГГГ-ММ-ДД ЧЧ:ММ [текст] — послать гонца\n"
            "🔹 /set_vakhta — задать даты (можно через кнопку ⚔️ Царская вахта)\n"
            "🔹 /reset — <b>СТЕРЕТЬ ВСЕ ДАННЫЕ</b> (казну, траты, записи) для теста\n\n"
            "💡 <i>Чтобы задать график службы, нажми ⚔️ Царская вахта и выбери нужный пункт.</i>")
    bot.send_message(message.chat.id, text, parse_mode="HTML")

@bot.message_handler(commands=['help'], func=lambda m: m.chat.id == ADMIN_ID)
def help_command(message):
    help_button(message)

@bot.message_handler(commands=['reset'], func=lambda m: m.chat.id == ADMIN_ID)
def reset_data(message):
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("✅ Да, стереть всё", callback_data="confirm_reset"))
    markup.add(types.InlineKeyboardButton("❌ Отмена", callback_data="cancel_reset"))
    bot.send_message(message.chat.id, "⚠️ <b>Государь, изволь подтвердить.</b>\n\nЭто сотрет ВСЕ данные: казну, траты, указы, рукописи и настройки вахты. Начать всё с чистого листа?", parse_mode="HTML", reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data in ['confirm_reset', 'cancel_reset'] and c.message.chat.id == ADMIN_ID)
def process_reset(call):
    if call.data == 'confirm_reset':
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("DELETE FROM shifts")
        c.execute("DELETE FROM expenses")
        c.execute("DELETE FROM tasks")
        c.execute("DELETE FROM notes")
        c.execute("DELETE FROM reminders")
        c.execute("DELETE FROM vakhta")
        c.execute("DELETE FROM debts")
        c.execute("DELETE FROM bot_status")
        conn.commit()
        conn.close()
        bot.edit_message_text("✅ <b>Всё стерто с лица земли, государь!</b>\n\nЛетописи чисты, можно начинать сначала.", chat_id=call.message.chat.id, message_id=call.message.message_id, parse_mode="HTML")
    else:
        bot.delete_message(call.message.chat.id, call.message.message_id)

@bot.message_handler(content_types=['voice'])
def handle_voice(message):
    if message.chat.id == ADMIN_ID:
        bot.send_message(message.chat.id, "🎙️ Государь, голосовые пока в опале, изволь писать текстом.")

# --- ИИ ---
@bot.message_handler(func=lambda m: m.chat.id == ADMIN_ID and m.text and not m.text.startswith('/') and m.text not in [
    "🏰 Пополнить казну", "🧠 Спросить советника", "🕯️ Царская сводка", 
    "🪶 Список указов", "📖 Рукописи", "🕊️ Гонцы", "⚔️ Царская вахта", 
    "💸 Траты из казны", "💰 Прибыток за вахту", "🔮 Предсказание прибытка",
    "💣 Служба завтра", "📕 Долговая книга", "📜 Свиток помощи"
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
    bot.send_message(message.chat.id, f"🕯️ <b>Сводка из царских архивов:</b>\n\n🏦 Всего в казне: {total_pay or 0} ₽\n📅 Отработано смен: {total_shifts or 0}\n📜 Указов в ожидании: {active_tasks}", parse_mode="HTML")# --- ВАХТА ---
@bot.message_handler(func=lambda m: m.text == "⚔️ Царская вахта" and m.chat.id == ADMIN_ID)
def vakhta_menu(message):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT start_date, end_date, w_start, w_end, w_days FROM vakhta WHERE id = 1")
    row = c.fetchone()
    conn.close()
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(types.InlineKeyboardButton("📅 Задать/изменить даты вахты", callback_data="setup_vakhta_dates"))
    markup.add(types.InlineKeyboardButton("⏰ Задать/изменить график службы", callback_data="setup_vakhta_schedule"))
    
    if row:
        start, end, w_start, w_end, w_days = row
        try:
            d2 = datetime.strptime(end, "%d.%m.%Y")
            today = datetime.now()
            left = (d2 - today).days
            if left < 0:
                status = "Вахта завершена, государь. Изволь отдохнуть."
            else:
                status = f"Осталось нести службу: <b>{left} дней</b>."
            text = f"⚔️ <b>Текущая вахта:</b>\nС {start} по {end}\n{status}\n\n"
            
            if w_start and w_end and w_days:
                days_map = {"1": "Пн", "2": "Вт", "3": "Ср", "4": "Чт", "5": "Пт", "6": "Сб", "7": "Вс"}
                days_str = ", ".join([days_map.get(d.strip(), d) for d in w_days.split(',')])
                text += f"⏰ <b>График:</b> с {w_start} до {w_end}\n📅 <b>Дни:</b> {days_str}\n\n"
            else:
                text += "⏰ График службы ещё не задан.\n\n"
                
            text += "Изволь выбрать, что настроить:"
        except:
            text = "❌ Смилуйся, государь, но в датах вышла путаница.\nИзволь выбрать, что настроить:"
    else:
        text = "⚔️ Государь, сроки вахты ещё не начертаны.\nИзволь выбрать, что настроить:"
        
    bot.send_message(message.chat.id, text, parse_mode="HTML", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "setup_vakhta_dates" and call.message.chat.id == ADMIN_ID)
def setup_vakhta_dates_cb(call):
    bot.edit_message_text("📅 <b>Соизволь молвить, с какого дня начинается служба? (ДД.ММ.ГГГГ)</b>", chat_id=call.message.chat.id, message_id=call.message.message_id, parse_mode="HTML")
    bot.register_next_step_handler(call.message, set_vakhta_end)

def set_vakhta_end(message):
    start_date = message.text.strip()
    try:
        datetime.strptime(start_date, "%d.%m.%Y")
    except:
        bot.send_message(message.chat.id, "❌ Смилуйся, государь, формат не тот. Начни заново через ⚔️ Царская вахта.")
        return
    msg = bot.send_message(message.chat.id, "📅 <b>А когда изволишь вернуться? (ДД.ММ.ГГГГ)</b>", parse_mode="HTML")
    bot.register_next_step_handler(msg, save_vakhta, start_date)

def save_vakhta(message, start_date):
    end_date = message.text.strip()
    try:
        datetime.strptime(end_date, "%d.%m.%Y")
    except:
        bot.send_message(message.chat.id, "❌ Смилуйся, государь, формат не тот. Начни заново через ⚔️ Царская вахта.")
        return
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("REPLACE INTO vakhta (id, start_date, end_date) VALUES (1, ?, ?)", (start_date, end_date))
    conn.commit(); conn.close()
    bot.send_message(message.chat.id, f"✅ Сроки вахты начертаны: с {start_date} по {end_date}!", reply_markup=get_main_menu())

@bot.callback_query_handler(func=lambda call: call.data == "setup_vakhta_schedule" and call.message.chat.id == ADMIN_ID)
def setup_vakhta_schedule_cb(call):
    msg = bot.send_message(call.message.chat.id, "⏰ <b>Во сколько начинается служба? (ЧЧ:ММ)</b>\nНапример: 08:00", parse_mode="HTML")
    bot.register_next_step_handler(msg, process_w_start)

def process_w_start(message):
    w_start = message.text.strip()
    try:
        datetime.strptime(w_start, "%H:%M")
        user_data[message.chat.id] = {'w_start': w_start}
        msg = bot.send_message(message.chat.id, "⏰ <b>Во сколько заканчивается? (ЧЧ:ММ)</b>\nНапример: 20:00", parse_mode="HTML")
        bot.register_next_step_handler(msg, process_w_end)
    except:
        bot.send_message(message.chat.id, "❌ Смилуйся, государь, формат не тот. Начни заново через ⚔️ Царская вахта.")
        
def process_w_end(message):
    w_end = message.text.strip()
    try:
        datetime.strptime(w_end, "%H:%M")
        user_data[message.chat.id]['w_end'] = w_end
        msg = bot.send_message(message.chat.id, "📅 <b>В какие дни изволишь служить?</b>\nНапиши дни словами через запятую. Например: <b>Пн, Вт, Ср, Чт, Пт, Сб</b> (или цифрами от 1 до 7).", parse_mode="HTML")
        bot.register_next_step_handler(msg, process_w_days)
    except:
        bot.send_message(message.chat.id, "❌ Смилуйся, государь, формат не тот. Начни заново через ⚔️ Царская вахта.")

def process_w_days(message):
    raw_text = message.text.strip().lower().replace(',', ' ').replace('.', ' ').split()
    
    days_map = {
        'пн': '1', 'вт': '2', 'ср': '3', 'чт': '4', 'пт': '5', 'сб': '6', 'вс': '7',
        'понедельник': '1', 'вторник': '2', 'среда': '3', 'четверг': '4', 'пятница': '5', 'суббота': '6', 'воскресенье': '7'
    }
    
    valid_days = []
    for d in raw_text:
        if d in days_map:
            valid_days.append(days_map[d])
        elif d.isdigit() and 1 <= int(d) <= 7:
            valid_days.append(d)
            
    unique_days = []
    for d in valid_days:
        if d not in unique_days:
            unique_days.append(d)

    if not unique_days:
        bot.send_message(message.chat.id, "❌ Смилуйся, государь, не разобрал дни. Начни заново через ⚔️ Царская вахта.")
        return

    w_days = ",".join(unique_days)
    w_start = user_data[message.chat.id].get('w_start', '00:00')
    w_end = user_data[message.chat.id].get('w_end', '00:00')
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id FROM vakhta WHERE id = 1")
    if c.fetchone():
        c.execute("UPDATE vakhta SET w_start=?, w_end=?, w_days=? WHERE id=1", (w_start, w_end, w_days))
    else:
        c.execute("INSERT INTO vakhta (id, w_start, w_end, w_days) VALUES (1, ?, ?, ?)", (w_start, w_end, w_days))
    conn.commit()
    conn.close()
    
    days_map_out = {"1": "Пн", "2": "Вт", "3": "Ср", "4": "Чт", "5": "Пт", "6": "Сб", "7": "Вс"}
    days_str = ", ".join([days_map_out[d] for d in unique_days])
    
    bot.send_message(message.chat.id, f"✅ График службы начертан: с {w_start} до {w_end}, дни: {days_str}.", reply_markup=get_main_menu())
    if message.chat.id in user_data: del user_data[message.chat.id]

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

# --- ПРЕДСКАЗАНИЕ ПРИБЫТКА ---
@bot.message_handler(func=lambda m: m.text == "🔮 Предсказание прибытка" and m.chat.id == ADMIN_ID)
def vakhta_forecast(message):
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
        start_dt = datetime.strptime(start_date, "%d.%m.%Y")
        end_dt = datetime.strptime(end_date, "%d.%m.%Y")
        today = datetime.now()
        
        total_days = (end_dt - start_dt).days
        days_passed = (today - start_dt).days
        
        if days_passed <= 0:
            bot.send_message(message.chat.id, "🔮 Государь, служба только начинается. Изволь подождать пару дней для предсказания.", parse_mode="HTML")
            conn.close()
            return
            
        if days_passed > total_days:
            days_passed = total_days

        c.execute("SELECT SUM(pay) FROM shifts WHERE date >= ?", (start_date,))
        earned = c.fetchone()[0] or 0
        c.execute("SELECT SUM(amount) FROM expenses WHERE date >= ?", (start_date,))
        spent = c.fetchone()[0] or 0
        conn.close()
        
        net_earned = earned - spent
        avg_daily = net_earned / days_passed
        forecast = int(avg_daily * total_days)
        
        text = (f"🔮 <b>Предсказание прибытка</b>\n\n"
                f"Государь, за {days_passed} дней службы ты изволил накопить <b>{int(net_earned)} ₽</b>.\n"
                f"Если будешь служить так же, к концу вахты (ещё {total_days - days_passed} дней) "
                f"твой прибыток составит примерно: <b>{forecast} ₽</b>.")
        bot.send_message(message.chat.id, text, parse_mode="HTML")
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Смилуйся, государь, но звёзды молчат. Ошибка: {e}")

# --- ДОЛГОВАЯ КНИГА ---
@bot.message_handler(func=lambda m: m.text == "📕 Долговая книга" and m.chat.id == ADMIN_ID)
def debt_menu(message):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, type, name, amount FROM debts")
    debts = c.fetchall()
    conn.close()
    
    i_owe = sum(d[3] for d in debts if d[1] == 'i_owe')
    they_owe = sum(d[3] for d in debts if d[1] == 'they_owe')
    
    text = f"📕 <b>Долговая книга</b>\n\n"
    text += f"🔴 Ты должен: <b>{i_owe} ₽</b>\n"
    text += f"🟢 Тебе должны: <b>{they_owe} ₽</b>\n\n"
    
    if not debts:
        text += "Летопись долгов пуста, государь."
    else:
        text += "<b>Подробности:</b>\n"
        for d in debts:
            if d[1] == 'i_owe':
                text += f"🔴 Я должен {d[2]} — {d[3]} ₽\n"
            else:
                text += f"🟢 {d[2]} должен мне — {d[3]} ₽\n"

    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(types.InlineKeyboardButton("➕ Занял я (должен)", callback_data="debt_add_i_owe"))
    markup.add(types.InlineKeyboardButton("➕ Дали мне (должны)", callback_data="debt_add_they_owe"))
    
    bot.send_message(message.chat.id, text, parse_mode="HTML", reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data.startswith('debt_add_') and c.message.chat.id == ADMIN_ID)
def add_debt_start(call):
    debt_type = "i_owe" if call.data == "debt_add_i_owe" else "they_owe"
    user_data[call.message.chat.id] = {'debt_type': debt_type}
    label = "кому изволил задолжать" if debt_type == "i_owe" else "кто изволил задолжать тебе"
    msg = bot.send_message(call.message.chat.id, f"📝 <b>Напиши имя того, {label}?</b>", parse_mode="HTML")
    bot.register_next_step_handler(msg, process_debt_name)

def process_debt_name(message):
    user_data[message.chat.id]['debt_name'] = message.text.strip()
    msg = bot.send_message(message.chat.id, "💰 <b>Сколько монет?</b>", parse_mode="HTML")
    bot.register_next_step_handler(msg, process_debt_amount)

def process_debt_amount(message):
    try:
        amount = int(message.text)
        d_type = user_data[message.chat.id]['debt_type']
        d_name = user_data[message.chat.id]['debt_name']
        
        conn = sqlite3.connect(DB_PATH)
        conn.cursor().execute("INSERT INTO debts (type, name, amount) VALUES (?, ?, ?)", (d_type, d_name, amount))
        conn.commit(); conn.close()
        
        bot.send_message(message.chat.id, f"✅ Запись в долговую книгу внесена!", reply_markup=get_main_menu())
        if message.chat.id in user_data: del user_data[message.chat.id]
    except:
        bot.send_message(message.chat.id, "❌ Смилуйся, государь, но мне нужны только цифры.", reply_markup=get_main_menu())

# --- СЛУЖБА ЗАВТРА ---
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
        bot.send_message(message.chat.id, "🪶 <b>Указ принят!</b> Твой слуга внёс его в список.", parse_mode="HTML")
    else: bot.send_message(message.chat.id, "Царь-батюшка, соизволь написать текст указа после /add")

@bot.message_handler(func=lambda m: m.text == "🪶 Список указов" and m.chat.id == ADMIN_ID)
def show_tasks(message):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, text FROM tasks WHERE status = 0")
    tasks = c.fetchall(); conn.close()
    if not tasks:
        bot.send_message(message.chat.id, "🪶 <b>Список указов пуст.</b> Напиши /add [текст], чтобы издать новый.", parse_mode="HTML")
        return
    markup = types.InlineKeyboardMarkup(row_width=1)
    text = "🪶 <b>Твои указы на сегодня:</b>\n\n"
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

# --- УТРЕННИЙ ДОКЛАД ---
def morning_report():
    while True:
        try:
            now = datetime.now()
            today_str = now.strftime("%Y-%m-%d")
            if now.hour == 7 and now.minute == 0:
                conn = sqlite3.connect(DB_PATH)
                c = conn.
