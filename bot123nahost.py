"""
TELEGRAM БОТ ДЛЯ 30-ДНЕВНОГО МАРАФОНА
Версия: 3.4 - ФИНАЛЬНАЯ РАБОЧАЯ
Дата: 2026-03-24
"""

import asyncio
import logging
import sqlite3
import threading
import os
from datetime import datetime
from typing import Tuple, Optional, Dict, Any

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    BotCommand, InlineKeyboardButton, KeyboardButton, 
    ReplyKeyboardMarkup, InlineKeyboardMarkup
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.client.default import DefaultBotProperties

# ==================== НАСТРОЙКИ ====================
TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
ADMIN_ID = 8406317983

if TOKEN == "YOUR_BOT_TOKEN_HERE":
    raise ValueError("❌ Токен не найден!")

REMINDER_HOUR = 23
REMINDER_MINUTE = 59

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ==================== БАЗА ДАННЫХ ====================
DB_LOCK = threading.Lock()

def get_db_connection():
    return sqlite3.connect('marathon_bot.db', check_same_thread=False)

def init_db():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            start_date TEXT,
            current_day INTEGER DEFAULT 1,
            last_task_date TEXT,
            last_report_date TEXT,
            is_active INTEGER DEFAULT 1,
            completed_30 INTEGER DEFAULT 0,
            has_info_shown INTEGER DEFAULT 0
        )
    ''')
    cur.execute('''
        CREATE TABLE IF NOT EXISTS daily_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            day INTEGER,
            report_date TEXT,
            tasks_completed INTEGER,
            total_tasks INTEGER,
            status TEXT
        )
    ''')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_user_day ON daily_reports(user_id, day)')
    conn.commit()
    conn.close()

def db_add_user(user_id: int, username: str, first_name: str):
    with DB_LOCK:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("INSERT OR IGNORE INTO users (user_id, username, first_name, start_date, current_day, has_info_shown) VALUES (?, ?, ?, ?, ?, ?)",
                    (user_id, username or "", first_name or "", datetime.now().isoformat(), 1, 0))
        conn.commit()
        conn.close()

def db_get_user(user_id: int) -> Optional[Tuple]:
    with DB_LOCK:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        result = cur.fetchone()
        conn.close()
        return result

def db_update_user_day(user_id: int, day: int):
    with DB_LOCK:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("UPDATE users SET current_day = ? WHERE user_id = ?", (day, user_id))
        conn.commit()
        conn.close()

def db_update_last_task_date(user_id: int):
    with DB_LOCK:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("UPDATE users SET last_task_date = ? WHERE user_id = ?", (datetime.now().isoformat(), user_id))
        conn.commit()
        conn.close()

def db_update_last_report_date(user_id: int):
    with DB_LOCK:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("UPDATE users SET last_report_date = ? WHERE user_id = ?", (datetime.now().isoformat(), user_id))
        conn.commit()
        conn.close()

def db_complete_marathon(user_id: int):
    with DB_LOCK:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("UPDATE users SET completed_30 = 1, is_active = 0 WHERE user_id = ?", (user_id,))
        conn.commit()
        conn.close()

def db_save_report(user_id: int, day: int, completed: int, total: int, status: str):
    with DB_LOCK:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("INSERT INTO daily_reports (user_id, day, report_date, tasks_completed, total_tasks, status) VALUES (?, ?, ?, ?, ?, ?)",
                    (user_id, day, datetime.now().isoformat(), completed, total, status))
        conn.commit()
        conn.close()

def db_get_report_status(user_id: int, day: int) -> bool:
    with DB_LOCK:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT id FROM daily_reports WHERE user_id = ? AND day = ?", (user_id, day))
        result = cur.fetchone() is not None
        conn.close()
        return result

def db_get_all_active_users() -> list:
    with DB_LOCK:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT user_id, current_day FROM users WHERE is_active = 1 AND completed_30 = 0")
        result = cur.fetchall()
        conn.close()
        return result

def db_get_all_users() -> list:
    with DB_LOCK:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT user_id, username, first_name, current_day, completed_30, last_report_date FROM users ORDER BY current_day DESC, start_date DESC")
        result = cur.fetchall()
        conn.close()
        return result

def db_reset_user(user_id: int):
    with DB_LOCK:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM daily_reports WHERE user_id = ?", (user_id,))
        cur.execute("UPDATE users SET current_day = 1, last_task_date = NULL, last_report_date = NULL, completed_30 = 0, is_active = 1, start_date = ?, has_info_shown = 0 WHERE user_id = ?",
                    (datetime.now().isoformat(), user_id))
        conn.commit()
        conn.close()

def db_get_user_reports(user_id: int) -> list:
    with DB_LOCK:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT day, status, report_date FROM daily_reports WHERE user_id = ? ORDER BY day", (user_id,))
        result = cur.fetchall()
        conn.close()
        return result

def db_set_info_shown(user_id: int):
    with DB_LOCK:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("UPDATE users SET has_info_shown = 1 WHERE user_id = ?", (user_id,))
        conn.commit()
        conn.close()

# ==================== КОНТЕНТ ====================
START_MESSAGE = """
🌟 *Привет! Это твой личный спутник на ближайшие 30 дней.*

Выполняя систему обязанностей, которую я буду высылать тебе каждый день, ты изменишь свою жизнь на «до» и «после». Главное помнить: я просто бот, а мои создатели — просто люди, и никакого волшебства здесь нет. Всё зависит только от тебя и твоего желания измениться.

*Ну что, рассказать вкратце, что тебя ждёт? Нажми на кнопку «Получить информацию».*
"""

INFO_MESSAGE = """
📋 *Это 30-дневный марафон, созданный для твоего удобства. Пройдёшь его — станешь другим человеком.*

🔹 *1–6 день* — ты втягиваешься в процесс.
🔹 Дальше ты каждый день выполняешь задания.

❗️ *ИНФОРМАЦИЯ*

Думаю, ты готов. После того как нажмёшь кнопку *«Я ГОТОВ»*, тебе придёт задание на День 1.
"""

SUPPORT_MESSAGES = {
    1: "✨ *Первый день позади!* Ты красава!",
    7: "🔥 *Первая неделя позади!* Так держать!",
    14: "⚡️ *ЭКВАДОР! 14 дней!* Половина пути!",
    21: "🚀 *ТРИ НЕДЕЛИ!* Осталось 9 дней!",
    25: "💪 *25 дней!* Осталось всего 5!"
}

FINAL_MESSAGE = "🎉 *Поздравляю!* Ты прошел 30-дневный марафон! 🚀"
REMINDER_MESSAGE = "⚠️ *Ты забыл отчитаться!* Вот задачи на следующий день."

# ==================== ЗАДАНИЯ ПО ДНЯМ ====================
DAILY_TASKS: Dict[int, Dict[str, Any]] = {}

# День 1
DAILY_TASKS[1] = {
    "title": "ДЕНЬ 1 | ТОЧКА А",
    "tasks": [
        "📖 *1. Чтение*\nПрочитай первые 3 темы книги. Остановись на теме «Дневники».",
        "📓 *2. Дневники*\nВнимательно прочти файл с инструкцией «Как пользоваться дневниками».\nhttps://disk.yandex.ru/i/m5w3A1NDOdVddg",
        "🌙 *3. Перед сном*\nЗаполни Дневник №1 и Дневник №2.",
        "🎯 *4. Главное намерение*\nВ Дневник №1 запиши 3 вещи, которые ты хочешь изменить в себе.",
        "⚡ *5. Действие дня*\nСегодня все решения принимай за 1 минуту."
    ],
    "total": 5
}

# День 2
DAILY_TASKS[2] = {
    "title": "ДЕНЬ 2 | ЧИСТКА ПРОСТРАНСТВА",
    "tasks": [
        "📖 *1. Чтение*\nПрочитай главы про дневники и зацепи тему «Окружение».",
        "🌙 *2. Перед сном*\nЗаполни дневники №1 и №2.",
        "🔇 *3. Цифровая гигиена*\nУбери телефон за 30 минут до сна.",
        "🧹 *4. Действие дня*\nОтпишись от 3 каналов/пабликов, которые бесят.",
        "👀 *5. Наблюдение*\nОбрати внимание, когда сегодня ты ловил себя на «залипании» в телефоне."
    ],
    "total": 5
}

# День 3
DAILY_TASKS[3] = {
    "title": "ДЕНЬ 3 | ЛИЦОМ К СТРАХАМ",
    "tasks": [
        "📖 *1. Чтение*\nПрочитай 4 главы. Начни с темы «Посторонний шум», закончи на теме «Меня себя».",
        "🌙 *2. Перед сном*\nЗаполни дневники №1 и №2.",
        "📝 *3. Дневниковая работа*\nВ Дневник №1 выпиши все страхи, которые мешают тебе принимать быстрые решения.",
        "💧 *4. Действие дня*\nВыпей сегодня 2 литра чистой воды.",
        "🧠 *5. Осознанность*\nНайди одну мысль, которая сегодня тебя тормозила."
    ],
    "total": 5
}

# День 4
DAILY_TASKS[4] = {
    "title": "ДЕНЬ 4 | ПРОДУКТИВНОСТЬ",
    "tasks": [
        "📖 *1. Чтение*\nПрочитай 4 главы. Начни с темы «Привычки», закончи на теме «Не спорьте».",
        "🌙 *2. Перед сном*\nЗаполни дневники №1 и №2.",
        "⚡ *3. Действие дня*\nСделай одно дело, которое давно откладывал.",
        "💪 *4. Физика*\nСделай 20 приседаний или отжиманий.",
        "📚 *5. Рефлексия*\nЗапиши одну ошибку сегодняшнего дня и один урок из неё."
    ],
    "total": 5
}

# День 5
DAILY_TASKS[5] = {
    "title": "ДЕНЬ 5 | ТИШИНА",
    "tasks": [
        "📖 *1. Чтение*\nПрочитай 4 главы. Начни с темы «Принимай решения быстро», закончи на теме «Трудности».",
        "🌙 *2. Перед сном*\nЗаполни дневники №1 и №2.",
        "📵 *3. Цифровой детокс*\nПосле пробуждения полчаса без телефона.",
        "🙊 *4. Действие дня*\nСегодня ни с кем не спорь."
    ],
    "total": 4
}

# День 6
DAILY_TASKS[6] = {
    "title": "ДЕНЬ 6 | ФИНИШ ПЕРВОЙ КНИГИ",
    "tasks": [
        "📖 *1. Чтение*\nПрочитай 4 главы. Начни с темы «Удача», закончи на теме «Думай меньше».",
        "🌙 *2. Перед сном*\nЗаполни дневники №1 и №2.",
        "💡 *3. Инсайты*\nВ Дневник №2 выпиши 3 главных инсайта за первые 6 дней.",
        "🧹 *4. Повторение*\nОтпишись ещё от 3 каналов/пабликов.",
        "💧 *5. Водный баланс*\nВыпей сегодня 2 литра чистой воды."
    ],
    "total": 5
}

# День 7
DAILY_TASKS[7] = {
    "title": "ДЕНЬ 7 | ИТОГИ НЕДЕЛИ",
    "tasks": [
        "📖 *1. Чтение (итоговое)*\nПрочитай 3 главы. Начни с темы «Индивидуальность», закончи на теме «Итог».",
        "🌙 *2. Перед сном*\nЗаполни дневники №1 и №2.",
        "🔄 *3. Точка изменений*\nЗапиши в Дневник №1: «Что я теперь буду делать иначе?».",
        "⭐ *4. Визуализация*\nОпиши в 5 предложениях свой идеальный день через год.",
        "⚡ *5. Задание на скорость*\nСегодня все решения принимай за 1 минуту.",
        "📢 *6. Новая книга*\nЗавтра стартуем книгу «45 татуировок личности».\nhttps://disk.yandex.ru/i/AN2Sk3MtrK7ZpQ"
    ],
    "total": 6
}

# День 8
DAILY_TASKS[8] = {
    "title": "ДЕНЬ 8 | ПЕРВАЯ ТАТУИРОВКА",
    "tasks": [
        "📖 *1. Чтение*\nПрочитай 1 главу из «45 татуировок личности».",
        "🌙 *2. Перед сном*\nЗаполни дневники №1 и №2.",
        "🔇 *3. Действие дня*\nПроведи день без наушников.",
        "🙊 *4. Осознанность*\nСегодня ни с кем не спорь.",
        "💪 *5. Физика*\nСделай 20 приседаний или отжиманий."
    ],
    "total": 5
}

# День 9
DAILY_TASKS[9] = {
    "title": "ДЕНЬ 9 | РАЗГОВОР С СОБОЙ",
    "tasks": [
        "📖 *1. Чтение*\nПрочитай 1 главу из «45 татуировок личности».",
        "🌙 *2. Перед сном*\nЗаполни дневники №1 и №2.",
        "🎯 *3. Целеполагание*\nВыпиши в Дневник №1, что ты хочешь в себе воспитать.",
        "👴 *4. Действие дня*\nПозвони родителям или бабушке/дедушке.",
        "🪞 *5. Упражнение*\nВстань перед зеркалом и скажи вслух 5 своих достоинств."
    ],
    "total": 5
}

# День 10
DAILY_TASKS[10] = {
    "title": "ДЕНЬ 10 | МОЯ ТАТУИРОВКА",
    "tasks": [
        "📖 *1. Чтение*\nПрочитай 1 главу из «45 татуировок личности».",
        "🌙 *2. Перед сном*\nЗаполни дневники №1 и №2.",
        "💉 *3. Анализ*\nВ Дневник №1 выпиши, какая «татуировка» у тебя УЖЕ есть.",
        "📵 *4. Цифровая гигиена*\nНе заходи в соцсети после 21:00.",
        "😤 *5. Действие дня*\nЦелый день не жаловаться вслух."
    ],
    "total": 5
}

# День 11-30 (остальные дни)
for day in range(11, 31):
    DAILY_TASKS[day] = {
        "title": f"ДЕНЬ {day}",
        "tasks": [f"📖 *1. Чтение*\nПрочитай 1 главу из книги.", f"🌙 *2. Перед сном*\nЗаполни дневники №1 и №2.", f"✨ *3. Действие дня*\nВыполни задание дня."],
        "total": 3
    }

# ==================== ОЦЕНКИ ====================
FEEDBACK_MESSAGES: Dict[int, Dict[str, str]] = {}

for day in range(1, 31):
    if day == 7:
        FEEDBACK_MESSAGES[day] = {
            "6/6": "✅ *Всё сделал (6/6)!*\nПервая неделя. Итоги, визуализация. Ты менялся. Отдохни сегодня.",
            "4-5/6": "🟡 *Сделал больше половины (4-5/6)!*\nТак держать! Неделя позади — это серьезно 💪",
            "0-3/6": "🔴 *Сделал мало или ничего (0-3/6)!*\nНеделя была длинной. Отдохни и завтра с новыми силами."
        }
    elif day == 5:
        FEEDBACK_MESSAGES[day] = {
            "5/5": "✅ *Всё сделал (5/5)!*\nПолчаса утра без телефона — это уровень. Целый день без споров — джедайство. Ты растешь.",
            "3-4/5": "🟡 *Сделал больше половины (3-4/5)!*\nХороший день! Продолжай в том же духе 💪",
            "0-2/5": "🔴 *Сделал мало или ничего (0-2/5)!*\nБывает. Завтра просто сделай чуть больше."
        }
    else:
        FEEDBACK_MESSAGES[day] = {
            "5/5": f"✅ *Всё сделал (5/5)!*\nОгонь! Ты красава! 🔥",
            "3-4/5": f"🟡 *Сделал больше половины (3-4/5)!*\nНеплохо! Двигай дальше 👊",
            "0-2/5": f"🔴 *Сделал мало или ничего (0-2/5)!*\nБывает. Завтра будет лучше!",
            "6/6": f"✅ *Всё сделал (6/6)!*\nОтлично! Ты справился! 🚀",
            "4-5/6": f"🟡 *Сделал больше половины (4-5/6)!*\nХорошо! Так держать! 💪",
            "0-3/6": f"🔴 *Сделал мало или ничего (0-3/6)!*\nНичего страшного!",
            "4/4": f"✅ *Всё сделал (4/4)!*\nМолодец! Продолжай! 🔥",
            "2-3/4": f"🟡 *Сделал больше половины (2-3/4)!*\nНеплохо! Двигайся дальше! 👊",
            "0-1/4": f"🔴 *Сделал мало или ничего (0-1/4)!*\nБывает. Завтра будет лучше!",
            "3/3": f"✅ *Всё сделал (3/3)!*\nОтлично! Ты справился! 🎉",
            "2/3": f"🟡 *Сделал больше половины (2/3)!*\nХорошо! Продолжай! 💪",
            "0-1/3": f"🔴 *Сделал мало или ничего (0-1/3)!*\nНичего страшного!"
        }

# ==================== КНОПКИ ====================
def get_main_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📋 Получить информацию")], [KeyboardButton(text="✅ Я ГОТОВ")]], resize_keyboard=True)

def get_report_keyboard(day: int) -> InlineKeyboardMarkup:
    total = DAILY_TASKS[day]["total"]
    builder = InlineKeyboardBuilder()
    
    if total == 6:
        builder.row(InlineKeyboardButton(text="✅ 6/6", callback_data=f"report_6/6_{day}"), InlineKeyboardButton(text="🟡 4-5/6", callback_data=f"report_4-5/6_{day}"))
        builder.row(InlineKeyboardButton(text="🔴 0-3/6", callback_data=f"report_0-3/6_{day}"))
    elif total == 5:
        builder.row(InlineKeyboardButton(text="✅ 5/5", callback_data=f"report_5/5_{day}"), InlineKeyboardButton(text="🟡 3-4/5", callback_data=f"report_3-4/5_{day}"))
        builder.row(InlineKeyboardButton(text="🔴 0-2/5", callback_data=f"report_0-2/5_{day}"))
    elif total == 4:
        builder.row(InlineKeyboardButton(text="✅ 4/4", callback_data=f"report_4/4_{day}"), InlineKeyboardButton(text="🟡 2-3/4", callback_data=f"report_2-3/4_{day}"))
        builder.row(InlineKeyboardButton(text="🔴 0-1/4", callback_data=f"report_0-1/4_{day}"))
    else:
        builder.row(InlineKeyboardButton(text="✅ 3/3", callback_data=f"report_3/3_{day}"), InlineKeyboardButton(text="🟡 2/3", callback_data=f"report_2/3_{day}"))
        builder.row(InlineKeyboardButton(text="🔴 0-1/3", callback_data=f"report_0-1/3_{day}"))
    
    return builder.as_markup()

# ==================== БОТ ====================
bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode="Markdown"))
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# ==================== ОБРАБОТЧИКИ ====================

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    user = message.from_user
    db_add_user(user.id, user.username, user.first_name)
    user_data = db_get_user(user.id)
    if not user_data:
        await message.answer("Ошибка")
        return
    
    current_day = user_data[4]
    completed_30 = user_data[8]
    
    if completed_30 == 1:
        await message.answer("🎉 Ты уже прошел марафон!", reply_markup=types.ReplyKeyboardRemove())
        return
    
    if current_day > 1:
        has_report = db_get_report_status(user.id, current_day)
        status = "✅ Ты уже отчитался." if has_report else "📝 Выполни задания и отправь отчет."
        await message.answer(f"👋 С возвращением! Ты на {current_day} дне.\n\n{status}\n\nНажми «✅ Я ГОТОВ»", reply_markup=get_main_keyboard())
    else:
        await message.answer(START_MESSAGE, reply_markup=get_main_keyboard())

@dp.message(F.text == "📋 Получить информацию")
async def get_info(message: types.Message):
    db_set_info_shown(message.from_user.id)
    await message.answer(INFO_MESSAGE, reply_markup=get_main_keyboard())

@dp.message(F.text == "✅ Я ГОТОВ")
async def i_am_ready(message: types.Message):
    user_id = message.from_user.id
    user_data = db_get_user(user_id)
    if not user_data:
        await message.answer("Ошибка. Нажми /start")
        return
    
    current_day = user_data[4]
    
    if db_get_report_status(user_id, current_day):
        next_day = current_day + 1
        if next_day <= 30:
            db_update_user_day(user_id, next_day)
            day_tasks = DAILY_TASKS[next_day]
            tasks_text = f"*{day_tasks['title']}*\n\n" + "\n\n".join(day_tasks["tasks"])
            tasks_text += f"\n\n*Как выполнишь задачи, нажми кнопку:*"
            await message.answer(tasks_text, reply_markup=get_report_keyboard(next_day))
            db_update_last_task_date(user_id)
        else:
            db_complete_marathon(user_id)
            await message.answer(FINAL_MESSAGE)
    else:
        day_tasks = DAILY_TASKS[current_day]
        tasks_text = f"*{day_tasks['title']}*\n\n" + "\n\n".join(day_tasks["tasks"])
        tasks_text += f"\n\n*Как выполнишь задачи, нажми кнопку:*"
        await message.answer(tasks_text, reply_markup=get_report_keyboard(current_day))
        db_update_last_task_date(user_id)

@dp.callback_query(lambda c: c.data.startswith('report_'))
async def process_report(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    parts = callback.data.split('_')
    
    if len(parts) < 3:
        await callback.answer("❌ Ошибка", show_alert=True)
        return
    
    report_key = parts[1]
    reported_day = int(parts[2])
    
    user_data = db_get_user(user_id)
    if not user_data:
        await callback.message.answer("Ошибка")
        await callback.answer()
        return
    
    current_day = user_data[4]
    
    if reported_day != current_day:
        await callback.answer(f"❌ Кнопка для дня {reported_day}", show_alert=True)
        await callback.message.delete()
        return
    
    if not user_data[5]:
        await callback.answer("Сначала нажми «Я ГОТОВ»", show_alert=True)
        return
    
    if db_get_report_status(user_id, current_day):
        await callback.answer("❌ Уже отчитался", show_alert=True)
        await callback.message.delete()
        return
    
    # Сохраняем
    completed_map = {"5/5":5,"3-4/5":3,"0-2/5":1,"6/6":6,"4-5/6":4,"0-3/6":1,"4/4":4,"2-3/4":2,"0-1/4":0,"3/3":3,"2/3":2,"0-1/3":0}
    completed = completed_map.get(report_key, 0)
    
    db_save_report(user_id, current_day, completed, DAILY_TASKS[current_day]["total"], report_key)
    db_update_last_report_date(user_id)
    
    await callback.message.delete()
    
    # Отправляем feedback
    feedback = FEEDBACK_MESSAGES[current_day].get(report_key, f"✅ Отчет за день {current_day} принят!")
    await callback.message.answer(feedback, parse_mode="Markdown")
    
    # Поддержка
    if current_day in SUPPORT_MESSAGES:
        await asyncio.sleep(1)
        await callback.message.answer(SUPPORT_MESSAGES[current_day], parse_mode="Markdown")
        await asyncio.sleep(2)
    else:
        await asyncio.sleep(2)
    
    # Завершение
    if current_day == 30:
        db_complete_marathon(user_id)
        await callback.message.answer(FINAL_MESSAGE, parse_mode="Markdown")
        await callback.answer()
        return
    
    # Следующий день
    next_day = current_day + 1
    db_update_user_day(user_id, next_day)
    
    day_tasks = DAILY_TASKS[next_day]
    tasks_text = f"*{day_tasks['title']}*\n\n" + "\n\n".join(day_tasks["tasks"])
    tasks_text += f"\n\n*Как выполнишь задачи, нажми кнопку:*"
    
    await callback.message.answer(tasks_text, parse_mode="Markdown", reply_markup=get_report_keyboard(next_day))
    db_update_last_task_date(user_id)
    await callback.answer()

# ==================== АДМИН ====================
@dp.message(Command("my_status"))
async def my_status(message: types.Message):
    user_data = db_get_user(message.from_user.id)
    if user_data:
        await message.answer(f"📊 *Статус*\n\nДень: {user_data[4]} из 30", parse_mode="Markdown")
    else:
        await message.answer("❌ Не зарегистрирован")

@dp.message(Command("admin_reset"))
async def admin_reset(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    args = message.text.split()
    if len(args) < 2:
        await message.answer("❌ /admin_reset user_id")
        return
    try:
        user_id = int(args[1])
        db_reset_user(user_id)
        await message.answer(f"✅ Пользователь {user_id} сброшен")
        await bot.send_message(user_id, "🔄 Администратор сбросил ваш прогресс! Нажмите /start")
    except:
        await message.answer("❌ Ошибка")

# ==================== НАПОМИНАНИЯ ====================
async def check_reminders():
    last_check_date = None
    while True:
        try:
            now = datetime.now()
            if now.hour == REMINDER_HOUR and now.minute >= REMINDER_MINUTE:
                if last_check_date != now.date():
                    last_check_date = now.date()
                    users = db_get_all_active_users()
                    for user_id, current_day in users:
                        if not db_get_report_status(user_id, current_day):
                            await bot.send_message(user_id, REMINDER_MESSAGE)
                            next_day = current_day + 1
                            if next_day <= 30:
                                day_tasks = DAILY_TASKS[next_day]
                                tasks_text = f"*{day_tasks['title']}*\n\n" + "\n\n".join(day_tasks["tasks"])
                                tasks_text += f"\n\n*Как выполнишь задачи, нажми кнопку:*"
                                await bot.send_message(user_id, tasks_text, reply_markup=get_report_keyboard(next_day))
                                db_update_user_day(user_id, next_day)
                                db_update_last_task_date(user_id)
            await asyncio.sleep(30)
        except Exception as e:
            logger.error(f"Ошибка: {e}")
            await asyncio.sleep(60)

# ==================== ЗАПУСК ====================
async def set_commands():
    await bot.set_my_commands([BotCommand(command="start", description="Запустить бота"), BotCommand(command="my_status", description="Мой статус")])

async def on_startup():
    logger.info("🚀 Бот запускается...")
    init_db()
    await set_commands()
    asyncio.create_task(check_reminders())
    logger.info("✅ Бот готов!")

async def main():
    dp.startup.register(on_startup)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
