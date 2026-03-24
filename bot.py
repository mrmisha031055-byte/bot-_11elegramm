"""
TELEGRAM БОТ ДЛЯ 30-ДНЕВНОГО МАРАФОНА
Версия: FINAL
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
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    BotCommand, InlineKeyboardButton, KeyboardButton, 
    ReplyKeyboardMarkup, InlineKeyboardMarkup
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.client.default import DefaultBotProperties

TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
ADMIN_ID = 8406317983

if TOKEN == "YOUR_BOT_TOKEN_HERE":
    raise ValueError("❌ Токен не найден!")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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

def db_reset_user(user_id: int):
    with DB_LOCK:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM daily_reports WHERE user_id = ?", (user_id,))
        cur.execute("UPDATE users SET current_day = 1, last_task_date = NULL, last_report_date = NULL, completed_30 = 0, is_active = 1, start_date = ?, has_info_shown = 0 WHERE user_id = ?",
                    (datetime.now().isoformat(), user_id))
        conn.commit()
        conn.close()

# ==================== FEEDBACK ТЕКСТЫ ====================
FEEDBACK_TEXTS = {
    1: {"5/5": "✅ *Всё сделал (5/5)!*\nОгонь старт! Горжусь 🔥", "3-4/5": "🟡 *Сделал больше половины!*\nНеплохо! 👊", "0-2/5": "🔴 *Сделал мало!*\nБывает. Завтра будет лучше."},
    2: {"5/5": "✅ *Всё сделал (5/5)!*\nЧистка пространства зашла. Красава!", "3-4/5": "🟡 *Сделал больше половины!*\nХорошо идешь! 💪", "0-2/5": "🔴 *Сделал мало!*\nНичего страшного."},
    3: {"5/5": "✅ *Всё сделал (5/5)!*\n2 литра воды + страхи на бумаге. Ты серьезный человек.", "3-4/5": "🟡 *Сделал больше половины!*\nМолодец! 🔥", "0-2/5": "🔴 *Сделал мало!*\nНу ок. Завтра новый день."},
    4: {"5/5": "✅ *Всё сделал (5/5)!*\nОдно отложенное дело сделано. Привычки начинаются с таких дней.", "3-4/5": "🟡 *Сделал больше половины!*\nТак держать! 👊", "0-2/5": "🔴 *Сделал мало!*\nНе зашло сегодня. Завтра получится."},
    5: {"5/5": "✅ *Всё сделал (5/5)!*\nПолчаса утра без телефона — это уровень. Ты растешь.", "3-4/5": "🟡 *Сделал больше половины!*\nХороший день! 💪", "0-2/5": "🔴 *Сделал мало!*\nБывает. Завтра сделай чуть больше."},
    6: {"5/5": "✅ *Всё сделал (5/5)!*\nПервая книга позади. Ты в отрыве 🚀", "3-4/5": "🟡 *Сделал больше половины!*\nМолодец! 🔥", "0-2/5": "🔴 *Сделал мало!*\nНе фортануло? Завтра все получится."},
    7: {"6/6": "✅ *Всё сделал (6/6)!*\nПервая неделя. Ты не просто читал — ты менялся.", "4-5/6": "🟡 *Сделал больше половины!*\nТак держать! 💪", "0-3/6": "🔴 *Сделал мало!*\nНеделя была длинной. Отдохни."},
}

for day in range(8, 31):
    FEEDBACK_TEXTS[day] = {
        "5/5": f"✅ *День {day} выполнен!*\nТы красава! 🔥",
        "3-4/5": f"🟡 *День {day}* - больше половины! 👊",
        "0-2/5": f"🔴 *День {day}* - бывает. Завтра лучше!"
    }

# ==================== ЗАДАНИЯ ====================
DAILY_TASKS = {}

for day in range(1, 31):
    if day == 1:
        DAILY_TASKS[day] = {
            "title": "ДЕНЬ 1 | ТОЧКА А",
            "tasks": [
                "📖 *1. Чтение*\nПрочитай первые 3 темы книги.",
                "📓 *2. Дневники*\nИнструкция: https://disk.yandex.ru/i/m5w3A1NDOdVddg",
                "🌙 *3. Перед сном*\nЗаполни Дневник №1 и №2.",
                "🎯 *4. Главное намерение*\nЗапиши 3 вещи, которые хочешь изменить.",
                "⚡ *5. Действие дня*\nВсе решения за 1 минуту."
            ],
            "total": 5
        }
    elif day == 2:
        DAILY_TASKS[day] = {
            "title": "ДЕНЬ 2 | ЧИСТКА ПРОСТРАНСТВА",
            "tasks": [
                "📖 *1. Чтение*\nПрочитай главы про дневники.",
                "🌙 *2. Перед сном*\nЗаполни дневники №1 и №2.",
                "🔇 *3. Цифровая гигиена*\nУбери телефон за 30 мин до сна.",
                "🧹 *4. Действие дня*\nОтпишись от 3 каналов.",
                "👀 *5. Наблюдение*\nОтметь залипание в телефоне."
            ],
            "total": 5
        }
    else:
        DAILY_TASKS[day] = {
            "title": f"ДЕНЬ {day}",
            "tasks": [f"📖 *1. Чтение*\nЗадание на день {day}"],
            "total": 5
        }

# ==================== КНОПКИ ====================
def get_main_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📋 Получить информацию")], [KeyboardButton(text="✅ Я ГОТОВ")]],
        resize_keyboard=True
    )

def get_report_keyboard(day: int):
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ 5/5", callback_data=f"rep_5/5_{day}"),
        InlineKeyboardButton(text="🟡 3-4/5", callback_data=f"rep_3-4/5_{day}")
    )
    builder.row(
        InlineKeyboardButton(text="🔴 0-2/5", callback_data=f"rep_0-2/5_{day}")
    )
    return builder.as_markup()

# ==================== БОТ ====================
bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode="Markdown"))
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

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
        await message.answer("🎉 Ты уже прошел марафон!")
        return
    
    if current_day > 1:
        has_report = db_get_report_status(user.id, current_day)
        status = "✅ Ты уже отчитался." if has_report else "📝 Выполни задания и отправь отчет."
        await message.answer(f"👋 С возвращением! Ты на {current_day} дне.\n\n{status}\n\nНажми «✅ Я ГОТОВ»", reply_markup=get_main_keyboard())
    else:
        await message.answer("🌟 *Привет!* Это твой спутник на 30 дней.\n\nНажми *«Получить информацию»* чтобы узнать подробности.", reply_markup=get_main_keyboard())

@dp.message(F.text == "📋 Получить информацию")
async def get_info(message: types.Message):
    await message.answer("📋 *30-дневный марафон* поможет изменить жизнь.\n\nНажми *«Я ГОТОВ»* чтобы начать!", reply_markup=get_main_keyboard())

@dp.message(F.text == "✅ Я ГОТОВ")
async def i_am_ready(message: types.Message):
    user_id = message.from_user.id
    user_data = db_get_user(user_id)
    if not user_data:
        await message.answer("Ошибка")
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
            await message.answer("🎉 *Поздравляю!* Ты прошел марафон! 🚀")
    else:
        day_tasks = DAILY_TASKS[current_day]
        tasks_text = f"*{day_tasks['title']}*\n\n" + "\n\n".join(day_tasks["tasks"])
        tasks_text += f"\n\n*Как выполнишь задачи, нажми кнопку:*"
        await message.answer(tasks_text, reply_markup=get_report_keyboard(current_day))
        db_update_last_task_date(user_id)

@dp.callback_query(lambda c: c.data.startswith('rep_'))
async def process_report(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    data = callback.data[4:]  # убираем "rep_"
    parts = data.split('_')
    
    if len(parts) < 2:
        await callback.answer("Ошибка", show_alert=True)
        return
    
    report_key = parts[0]  # "5/5", "3-4/5" или "0-2/5"
    reported_day = int(parts[1])
    
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
    
    completed_map = {"5/5":5, "3-4/5":3, "0-2/5":1}
    completed = completed_map.get(report_key, 0)
    
    db_save_report(user_id, current_day, completed, DAILY_TASKS[current_day]["total"], report_key)
    db_update_last_report_date(user_id)
    
    await callback.message.delete()
    
    # ОТПРАВЛЯЕМ ПРАВИЛЬНЫЙ FEEDBACK
    feedback = FEEDBACK_TEXTS.get(current_day, {}).get(report_key)
    await callback.message.answer(feedback, parse_mode="Markdown")
    
    # Поддержка для 1,7,14,21,25 дней
    support_days = {1: "✨ *Первый день позади!* Ты красава!", 7: "🔥 *Первая неделя позади!* Так держать!", 14: "⚡️ *ЭКВАДОР! 14 дней!* Половина пути!", 21: "🚀 *ТРИ НЕДЕЛИ!* Осталось 9 дней!", 25: "💪 *25 дней!* Осталось всего 5!"}
    if current_day in support_days:
        await asyncio.sleep(1)
        await callback.message.answer(support_days[current_day], parse_mode="Markdown")
        await asyncio.sleep(2)
    else:
        await asyncio.sleep(2)
    
    if current_day == 30:
        db_complete_marathon(user_id)
        await callback.message.answer("🎉 *Поздравляю!* Ты прошел марафон! 🚀", parse_mode="Markdown")
        await callback.answer()
        return
    
    next_day = current_day + 1
    db_update_user_day(user_id, next_day)
    
    day_tasks = DAILY_TASKS[next_day]
    tasks_text = f"*{day_tasks['title']}*\n\n" + "\n\n".join(day_tasks["tasks"])
    tasks_text += f"\n\n*Как выполнишь задачи, нажми кнопку:*"
    
    await callback.message.answer(tasks_text, parse_mode="Markdown", reply_markup=get_report_keyboard(next_day))
    db_update_last_task_date(user_id)
    await callback.answer()

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
    except:
        await message.answer("❌ Ошибка")

async def check_reminders():
    while True:
        try:
            now = datetime.now()
            if now.hour == 23 and now.minute >= 59:
                users = db_get_all_active_users()
                for user_id, current_day in users:
                    if not db_get_report_status(user_id, current_day):
                        await bot.send_message(user_id, "⚠️ *Ты забыл отчитаться!*")
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

async def set_commands():
    await bot.set_my_commands([
        BotCommand(command="start", description="Запустить"),
        BotCommand(command="my_status", description="Мой статус")
    ])

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
