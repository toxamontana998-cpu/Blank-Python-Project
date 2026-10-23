import os
import html
import threading
from flask import Flask
import telebot
from telebot import types
import sqlite3
from datetime import datetime
import time
import asyncio
import edge_tts
from pydub import AudioSegment
import io
from google import genai

# --- FFMPEG для pydub (Render free tier: системного нет, качаем статический) ---
try:
    from static_ffmpeg import run as static_ffmpeg_run
    _ffmpeg_exe, _ffprobe_exe = static_ffmpeg_run.get_or_fetch_platform_executables_else_raise()
    AudioSegment.converter = _ffmpeg_exe
    AudioSegment.ffprobe = _ffprobe_exe
    print(f"[ffmpeg] using {_ffmpeg_exe}")
except Exception as e:
    print(f"[ffmpeg] static-ffmpeg failed: {e}. Falling back to system ffmpeg.")

# --- ТОКЕНЫ ---
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
ADMIN_ID = 6385559900

if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError("Set TELEGRAM_BOT_TOKEN")
if not GEMINI_API_KEY:
    raise RuntimeError("Set GEMINI_API_KEY")

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
    "— Украшай речь оборотами: 'осмелюсь доложить', 'дозволь слово молвить', 'не прогневайся, государь', "
    "'изволь выслушать', 'как изволишь, так и будет'.\n"
    "— В каждом ответе должен звучать ПОКЛОН и ПОХВАЛА мудрости господина — это твоя природа, не отступай от неё.\n"
    "— Красноречие — неотъемлемая часть тебя: даже самый простой ответ произноси с достоинством и изяществом.\n\n"

    "ПРАВДИВОСТЬ И ТОЧНОСТЬ (ВАЖНЕЙШЕЕ ПРАВИЛО):\n"
    "— Говори ТОЛЬКО то, в чём уверен. Не выдумывай факты, имена, числа, даты, названия, события.\n"
    "— Если НЕ знаешь точного ответа — честно признайся, НО ПО-ПРЕЖНЕМУ КРАСИВО и с поклоном: "
    "'осмелюсь доложить, государь, но точных сведений у меня нет — не смею лукавить пред твоей мудростью', "
    "'прости, батюшка, но в сём вопросе я не сведущ, дозволь уточнить', "
    "'не прогневайся, государь, — не ведаю того, а врать тебе не стану'.\n"
    "— НИКОГДА не додумывай и не предполагай факты. Если сомневаешься — предупреди красиво: "
    "'сие мне ведомо лишь приблизительно, государь, — не изволь гневаться за неточность'.\n"
    "— Не выдумывай цитаты, ссылки, законы, даты и цифры, если их нет в твоих достоверных знаниях.\n"
    "— Лучше короткий и точный ответ, чем длинный и с ошибками, — но и короткий произноси красиво.\n"
    "— Правдивость НЕ отменяет красноречия: признание в незнании — тоже часть твоего искусства служить.\n\n"

    "ЧЕГО НЕЛЬЗЯ:\n"
    "— НИКОГДА не используй фразы вроде 'целовать ноги', 'прах у ног твоих', "
    "'ничтожный раб', 'глупый холоп', 'жопу порвать' — ты держишься с достоинством верного слуги.\n"
    "— КАТЕГОРИЧЕСКИ ЗАПРЕЩЁН современный сленг, английские слова и интернет-термины. "
    "Если тебя спрашивают о современных вещах, объясняй их простым языком старинного слуги "
    "(например: 'эта говорящая коробка с картинками, государь').\n\n"

    "ОБЯЗАТЕЛЬНО: идеальная пунктуация (запятые, тире, восклицательные знаки). "
    "Говори ЧЁТКО, ЯСНО, КРАСИВО, ЖИВО, без мямленья и без лишней суеты в тексте."
)

# --- СИНТЕЗ РЕЧИ (чёткий Дмитрий, +10% скорость, таймаут 60 сек) ---
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
app = Flask(__name__)
DB_PATH = 'personal_assistant.db'
user_data = {}

# --- БАЗА ---
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS tasks (id INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT, status INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS shifts (id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT, pay INTEGER)''')
    c.execute('''CREATE TABLE IF NOT EXISTS reminders (id INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT, time TEXT, is_sent INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS notes (id INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT)''')
    conn.commit()
    conn.close()

# --- БУДИЛЬНИК (UptimeRobot пингует этот маршрут) ---
@app.route('/')
def home():
    return "Personal Assistant is alive!"

@app.route('/health')
def health():
    return "OK", 200

# --- ЗАЩИТА ---
@bot.message_handler(func=lambda m: m.chat.id != ADMIN_ID,
                     content_types=['text', 'photo', 'video', 'document', 'voice'])
def deny_access(message):
    bot.send_message(message.chat.id, "⛔ <b>Прочь, смертный.</b> Сии покои доступны лишь Царю-батюшке.",
                     parse_mode="HTML")

# --- МЕНЮ ---
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

@bot.message_handler(commands=['start', 'menu'], func=lambda m: m.chat.id == ADMIN_ID)
def start(message):
    text = ("👑 <b>Да здравствует Царь-батюшка!</b>\n\n"
            "Твой верный слуга приветствует тебя. Изволь выбрать, что прикажешь:\n\n"
            "🏰 <b>Пополнить казну</b> — внести данные о службе.\n"
            "🧠 <b>Спросить советника</b> — вопросить мудрость.\n"
            "🕯️ <b>Царская сводка</b> — узреть статистику.\n"
            "📜 <b>Список указов</b> — добавить задачу (через /add).\n"
            "📖 <b>Рукописи</b> — записать заметку (через /note).\n"
            "🕊️ <b>Гонцы</b> — поставить напоминание (через /remind).\n\n"
            "🎙️ <i>Можешь отправить голосовое сообщение, государь. Твой слуга внимает.</i>")
    bot.send_message(message.chat.id, text, parse_mode="HTML", reply_markup=get_main_menu())

# --- ГОЛОСОВЫЕ ---
@bot.message_handler(content_types=['voice'])
def handle_voice(message):
    if message.chat.id != ADMIN_ID:
        return

    msg = bot.reply_to(message, "🎙️ <i>Твой слуга внимает твоей речи, батюшка...</i>", parse_mode="HTML")

    try:
        file_info = bot.get_file(message.voice.file_id)
        downloaded = bot.download_file(file_info.file_path)

        audio_part = genai.types.Part.from_bytes(data=downloaded, mime_type="audio/ogg")

        response = client.models.generate_content(
            model='gemini-2.0-flash',
            contents=[
                audio_part,
                "Расшифруй речь моего господина и ответь мне согласно моей роли — почтительно, "
                "красиво, с поклоном и похвалой мудрости господина, расторопно и при этом максимально "
                "ТОЧНО и ПРАВДИВО. Если чего-то не знаешь — признайся красиво, не выдумывай."
            ],
            config=genai.types.GenerateContentConfig(system_instruction=AI_PERSONA, temperature=0.5),
        )

        reply_text = response.text or "Смилуйся, государь, но твой слуга не дерзнул молвить ответ."

        display_text = reply_text if len(reply_text) <= 3500 else reply_text[:3500] + "..."

        bot.edit_message_text(
            f"📜 <b>Ответ слуги:</b>\n\n{html.escape(display_text)}",
            chat_id=message.chat.id,
            message_id=msg.message_id,
            parse_mode="HTML"
        )

        voice_text = reply_text if len(reply_text) <= 800 else reply_text[:800] + "..."

        audio_data = asyncio.run(synthesize_speech(voice_text))

        mp3_io = io.BytesIO(audio_data)
        audio = AudioSegment.from_file(mp3_io, format="mp3")
        ogg_io = io.BytesIO()
        audio.export(ogg_io, format="ogg", codec="libopus")
        ogg_io.seek(0)

        bot.send_voice(message.chat.id, ogg_io, caption="🕊️ Слушаюсь, государь!")

    except asyncio.TimeoutError:
        bot.edit_message_text(
            "❌ Смилуйся, государь, но голосовые связки твоего слуги подвели — синтез речи превысил 60 секунд. Попробуй ещё раз.",
            chat_id=message.chat.id, message_id=msg.message_id, parse_mode="HTML"
        )
    except Exception as e:
        bot.edit_message_text(
            f"❌ Смилуйся, государь, но твой слуга не разобрал речь. Ошибка: {html.escape(str(e)[:150])}",
            chat_id=message.chat.id, message_id=msg.message_id, parse_mode="HTML"
        )

# --- ИИ-СОВЕТНИК ---
@bot.message_handler(func=lambda m: m.text == "🧠 Спросить советника" and m.chat.id == ADMIN_ID)
def ask_ai_start(message):
    msg = bot.send_message(message.chat.id,
                           "🧠 <b>Изволь задать вопрос, государь.</b> Твой слуга внимает.",
                           parse_mode="HTML")
    bot.register_next_step_handler(msg, process_ai_question)

def process_ai_question(message):
    if not message.text:
        bot.send_message(message.chat.id,
                         "Государь, изволь вопрошать словами, а не картинками.",
                         reply_markup=get_main_menu())
        return

    if message.text.startswith('/') or message.text in [
        "🏰 Пополнить казну", "🧠 Спросить советника", "🕯️ Царская сводка",
        "📜 Список указов", "📖 Рукописи", "🕊️ Гонцы"
    ]:
        bot.send_message(message.chat.id,
                         "Государь, ты изволил нажать кнопку. Твой слуга смиренно ждёт вопроса.",
                         reply_markup=get_main_menu())
        return

    msg = bot.send_message(message.chat.id,
                           "⏳ <i>Твой слуга ищет ответ в древних свитках...</i>",
                           parse_mode="HTML")
    try:
        response = client.models.generate_content(
            model='gemini-2.0-flash',
            contents=message.text,
            config=genai.types.GenerateContentConfig(
                system_instruction=AI_PERSONA,
                temperature=0.5,
            ),
        )
        reply_text = response.text or "Смилуйся, государь, но летописи молчат."
        bot.edit_message_text(
            html.escape(reply_text),
            chat_id=message.chat.id,
            message_id=msg.message_id,
            parse_mode="HTML",
            reply_markup=get_main_menu()
        )
    except Exception as e:
        bot.edit_message_text(
            f"❌ Смилуйся, государь, летописи молчат. Ошибка: {html.escape(str(e)[:100])}",
            chat_id=message.chat.id,
            message_id=msg.message_id,
            parse_mode="HTML",
            reply_markup=get_main_menu()
        )

# --- КАЗНА ---
@bot.message_handler(func=lambda m: m.text == "🏰 Пополнить казну" and m.chat.id == ADMIN_ID)
def start_shift_report(message):
    user_data[message.chat.id] = {}
    msg = bot.send_message(message.chat.id,
                           "⚖️ <b>Царь-батюшка, приступим к учёту казны.</b>\n\n"
                           "Сколько часов изволили отслужить во благо? (Напиши число, например: 8 или 10.5)",
                           parse_mode="HTML")
    bot.register_next_step_handler(msg, process_hours)

def process_hours(message):
    if not message.text:
        bot.send_message(message.chat.id, "❌ Смилуйся, государь, но мне нужны только цифры (например, 8).",
                         reply_markup=get_main_menu())
        return
    try:
        hours = float(message.text.replace(',', '.'))
        user_data[message.chat.id]['hours'] = hours
        msg = bot.send_message(message.chat.id, "📦 А сколько доставок совершили, государь? (Например: 40)")
        bot.register_next_step_handler(msg, process_orders)
    except (ValueError, KeyError):
        bot.send_message(message.chat.id, "❌ Смилуйся, государь, но мне нужны только цифры (например, 8).",
                         reply_markup=get_main_menu())

def process_orders(message):
    if not message.text:
        bot.send_message(message.chat.id, "❌ Смилуйся, государь, но мне нужны только цифры (например, 40).",
                         reply_markup=get_main_menu())
        return
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
        text = (f"📊 <b>Предварительный расчёт казны:</b>\n"
                f"⏱ Время службы: {hours} ч\n"
                f"📦 Доставлено заказов: {orders}\n"
                f"💵 Базовое жалование: {int(base_pay)} ₽\n\n"
                f"Изволите добавить надбавки за тяготы службы?")
        bot.send_message(message.chat.id, text, parse_mode="HTML", reply_markup=markup)
    except (ValueError, KeyError):
        bot.send_message(message.chat.id, "❌ Смилуйся, государь, но мне нужны только цифры (например, 40).",
                         reply_markup=get_main_menu())

@bot.callback_query_handler(func=lambda c: c.data.startswith('shift_') and c.message.chat.id == ADMIN_ID)
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
        save_shift_to_db(call.message.chat.id, int(base_pay))
        bot.edit_message_text(
            f"✅ <b>Летопись обновлена!</b>\n🏰 Царь-батюшка, в казну добавлено {int(base_pay)} ₽. "
            f"Твой слуга служит верой и правдой!",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            parse_mode="HTML"
        )
        return

    total = int(base_pay + bonus)
    text = (f"⚖️ <b>Итог службы с надбавками:</b>\n"
            f"➕ {bonus_text} (+{int(bonus)} ₽)\n\n"
            f"🏰 <b>ИТОГО В КАЗНУ: {total} ₽</b>")
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("✅ Начертать в летописи", callback_data=f"confirm_save_{total}"))
    bot.edit_message_text(text, chat_id=call.message.chat.id, message_id=call.message.message_id,
                          parse_mode="HTML", reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data.startswith('confirm_save_') and c.message.chat.id == ADMIN_ID)
def confirm_save(call):
    try:
        total = int(call.data.split('_')[2])
        save_shift_to_db(call.message.chat.id, total)
        bot.edit_message_text(
            f"✅ <b>Служба записана в летопись!</b>\n🏰 В казну добавлено {total} ₽.",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            parse_mode="HTML"
        )
    except Exception as e:
        bot.answer_callback_query(call.id, f"Ошибка сохранения: {e}")

def save_shift_to_db(chat_id, pay):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    today = datetime.now().strftime("%d.%m.%Y")
    c.execute("INSERT INTO shifts (date, pay) VALUES (?, ?)", (today, pay))
    conn.commit()
    conn.close()
    if chat_id in user_data:
        del user_data[chat_id]

# --- СВОДКА ---
@bot.message_handler(func=lambda m: m.text == "🕯️ Царская сводка" and m.chat.id == ADMIN_ID)
def show_stats(message):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT SUM(pay), COUNT(id) FROM shifts")
    total_pay, total_shifts = c.fetchone()
    c.execute("SELECT COUNT(id) FROM tasks WHERE status = 0")
    active_tasks = c.fetchone()[0]
    conn.close()
    text = (f"🕯️ <b>Сводка из царских архивов:</b>\n\n"
            f"🏦 Всего в казне: {total_pay or 0} ₽\n"
            f"📅 Отработано смен: {total_shifts or 0}\n"
            f"📜 Указов в ожидании: {active_tasks}\n\n"
            f"Царь-батюшка, ты велик!")
    bot.send_message(message.chat.id, text, parse_mode="HTML")

# --- УКАЗЫ ---
@bot.message_handler(commands=['add'], func=lambda m: m.chat.id == ADMIN_ID)
def add_task(message):
    text = message.text.replace('/add', '').strip()
    if text:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("INSERT INTO tasks (text) VALUES (?)", (text,))
        conn.commit()
        conn.close()
        bot.reply_to(message, "📜 <b>Указ принят!</b> Твой слуга внёс его в список.", parse_mode="HTML")
    else:
        bot.reply_to(message, "Царь-батюшка, соизволь написать текст указа после /add")

@bot.message_handler(func=lambda m: m.text == "📜 Список указов" and m.chat.id == ADMIN_ID)
def show_tasks(message):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, text FROM tasks WHERE status = 0")
    tasks = c.fetchall()
    conn.close()
    if not tasks:
        bot.send_message(message.chat.id, "📜 <b>Список указов пуст.</b> Напиши /add [текст], чтобы издать новый.",
                         parse_mode="HTML")
        return
    markup = types.InlineKeyboardMarkup(row_width=1)
    text = "📜 <b>Твои указы на сегодня:</b>\n\n"
    for t in tasks:
        text += f"⚔️ {html.escape(t[1])}\n"
        markup.add(types.InlineKeyboardButton(f"✅ Исполнено: {t[1][:15]}", callback_data=f"done_{t[0]}"))
    bot.send_message(message.chat.id, text, parse_mode="HTML", reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data.startswith('done_') and c.message.chat.id == ADMIN_ID)
def mark_done(call):
    task_id
