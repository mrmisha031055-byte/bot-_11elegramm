"""
TELEGRAM БОТ ДЛЯ 30-ДНЕВНОГО МАРАФОНА
Версия: 3.7 - ДИАГНОСТИКА В ОТВЕТЕ
"""

import asyncio
import logging
import sqlite3
import threading
import os
from datetime import datetime
import pytz
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

# ==================== НАСТРОЙКИ ====================
TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
ADMIN_ID = 8406317983

MOSCOW_TZ = pytz.timezone('Europe/Moscow')

if TOKEN == "YOUR_BOT_TOKEN_HERE":
    raise ValueError("❌ Токен не найден!")

REMINDER_HOUR = 23
REMINDER_MINUTE = 59

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def get_moscow_now():
    return datetime.now(MOSCOW_TZ)

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
                    (user_id, username or "", first_name or "", get_moscow_now().isoformat(), 1, 0))
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
        cur.execute("UPDATE users SET last_task_date = ? WHERE user_id = ?", (get_moscow_now().isoformat(), user_id))
        conn.commit()
        conn.close()

def db_update_last_report_date(user_id: int):
    with DB_LOCK:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("UPDATE users SET last_report_date = ? WHERE user_id = ?", (get_moscow_now().isoformat(), user_id))
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
                    (user_id, day, get_moscow_now().isoformat(), completed, total, status))
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
                    (get_moscow_now().isoformat(), user_id))
        conn.commit()
        conn.close()

# ==================== КОНТЕНТ ====================
START_MESSAGE = "🌟 *Привет!* Это твой личный спутник на 30 дней.\n\nНажми *«Получить информацию»* чтобы узнать подробности."
INFO_MESSAGE = "📋 *30-дневный марафон* поможет тебе изменить жизнь.\n\nНажми *«Я ГОТОВ»* чтобы начать!"

SUPPORT_MESSAGES = {
    1: "✨ *Первый день позади!* Ты красава!",
    7: "🔥 *Первая неделя позади!* Так держать!",
    14: "⚡️ *ЭКВАДОР! 14 дней!* Половина пути!",
    21: "🚀 *ТРИ НЕДЕЛИ!* Осталось 9 дней!",
    25: "💪 *25 дней!* Осталось всего 5!"
}

FINAL_MESSAGE = "🎉 *Поздравляю!* Ты прошел 30-дневный марафон! 🚀"
REMINDER_MESSAGE = "⚠️ *Ты забыл отчитаться!* Вот задачи на следующий день."

# ==================== ЗАДАНИЯ ====================
DAILY_TASKS: Dict[int, Dict[str, Any]] = {}
for day in range(1, 31):
    DAILY_TASKS[day] = {
        "title": f"ДЕНЬ {day}",
        "tasks": [f"📖 Задание на день {day}"],
        "total": 5
    }

# ==================== ОЦЕНКИ ====================
FEEDBACK_MESSAGES: Dict[int, Dict[str, str]] = {}

# Заполняем для всех дней
for day in range(1, 31):
    FEEDBACK_MESSAGES[day] = {
        "5/5": f"✅ *Всё сделал (5/5)!*\nОгонь! Ты красава! 🔥",
        "3-4/5": f"🟡 *Сделал больше половины (3-4/5)!*\nНеплохо! Двигай дальше 👊",
        "0-2/5": f"🔴 *Сделал мало или ничего (0-2/5)!*\nБывает. Завтра будет лучше!"
    }

# ==================== КНОПКИ ====================
def get_main_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📋 Получить информацию")], [KeyboardButton(text="✅ Я ГОТОВ")]], resize_keyboard=True)

def get_report_keyboard(day: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Выполнил 5/5", callback_data=f"report_5/5_{day}"),
        InlineKeyboardButton(text="🟡 Выполнил 3-4/5", callback_data=f"report_3-4/5_{day}")
    )
    builder.row(InlineKeyboardButton(text="🔴 Выполнил 0-2/5", callback_data=f"report_0-2/5_{day}"))
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
            tasks_text += f"\n\n*Нажми кнопку:*"
            await message.answer(tasks_text, reply_markup=get_report_keyboard(next_day))
            db_update_last_task_date(user_id)
        else:
            db_complete_marathon(user_id)
            await message.answer(FINAL_MESSAGE)
    else:
        day_tasks = DAILY_TASKS[current_day]
        tasks_text = f"*{day_tasks['title']}*\n\n" + "\n\n".join(day_tasks["tasks"])
        tasks_text += f"\n\n*Нажми кнопку:*"
        await message.answer(tasks_text, reply_markup=get_report_keyboard(current_day))
        db_update_last_task_date(user_id)

@dp.callback_query(lambda c: c.data.startswith('report_'))
async def process_report(callback: types.CallbackQuery):
    """Обработка отчетов с диагностикой"""
    user_id = callback.from_user.id
    callback_data = callback.data
    
    # 1. Показываем диагностику пользователю
    await callback.message.answer(
        f"🔍 *ДИАГНОСТИКА*\n\n"
        f"Получен callback: `{callback_data}`\n"
        f"Длина: {len(callback_data)}",
        parse_mode="Markdown"
    )
    
    # Разбираем
    without_prefix = callback_data.replace('report_', '')
    await callback.message.answer(f"📌 Без префикса: `{without_prefix}`", parse_mode="Markdown")
    
    parts = without_prefix.rsplit('_', 1)
    await callback.message.answer(f"📌 Разбор: {parts}", parse_mode="Markdown")
    
    if len(parts) != 2:
        await callback.answer("❌ Ошибка формата", show_alert=True)
        return
    
    report_value = parts[0]
    reported_day = int(parts[1])
    
    await callback.message.answer(
        f"📌 report_value: `{report_value}` (длина {len(report_value)})\n"
        f"📌 reported_day: {reported_day}\n"
        f"📌 Символы report_value: {[ord(c) for c in report_value]}",
        parse_mode="Markdown"
    )
    
    user_data = db_get_user(user_id)
    if not user_data:
        await callback.message.answer("Ошибка: пользователь не найден")
        await callback.answer()
        return
    
    current_day = user_data[4]
    
    await callback.message.answer(
        f"📌 Текущий день в БД: {current_day}\n"
        f"📌 Совпадают: {reported_day == current_day}",
        parse_mode="Markdown"
    )
    
    if reported_day != current_day:
        await callback.answer(f"❌ Кнопка для дня {reported_day}, а вы на дне {current_day}", show_alert=True)
        await callback.message.delete()
        return
    
    if not user_data[5]:
        await callback.answer("Сначала нажми «Я ГОТОВ»", show_alert=True)
        return
    
    if db_get_report_status(user_id, current_day):
        await callback.answer("❌ Уже отчитался!", show_alert=True)
        await callback.message.delete()
        return
    
    # Сохраняем отчет
    db_save_report(user_id, current_day, 5, 5, report_value)
    db_update_last_report_date(user_id)
    await callback.message.delete()
    
    # ПОИСК FEEDBACK
    day_feedback = FEEDBACK_MESSAGES.get(current_day, {})
    
    await callback.message.answer(
        f"📚 *ПОИСК FEEDBACK*\n\n"
        f"День {current_day}:\n"
        f"Доступные ключи: {list(day_feedback.keys())}\n"
        f"Ищем: `{report_value}`\n"
        f"Прямое совпадение: {report_value in day_feedback}\n\n"
        f"Проверка символов:\n"
        f"Искомый: {[ord(c) for c in report_value]}\n"
        f"Ключ '5/5': {[ord(c) for c in '5/5']}",
        parse_mode="Markdown"
    )
    
    # Пробуем найти
    feedback_text = None
    if report_value in day_feedback:
        feedback_text = day_feedback[report_value]
        await callback.message.answer("✅ *Найдено точное совпадение!*", parse_mode="Markdown")
    else:
        # Пробуем нормализовать (убрать пробелы)
        normalized = report_value.replace(' ', '').strip()
        if normalized in day_feedback:
            feedback_text = day_feedback[normalized]
            await callback.message.answer(f"✅ *Найдено после нормализации!* `{normalized}`", parse_mode="Markdown")
        else:
            await callback.message.answer("❌ *FEEDBACK НЕ НАЙДЕН!*", parse_mode="Markdown")
            feedback_text = None
    
    if feedback_text:
        await callback.message.answer(feedback_text, parse_mode="Markdown")
    else:
        await callback.message.answer(f"✅ Спасибо за отчет! (День {current_day})", parse_mode="Markdown")
    
    # Поддержка
    if current_day in SUPPORT_MESSAGES:
        await asyncio.sleep(1)
        await callback.message.answer(SUPPORT_MESSAGES[current_day], parse_mode="Markdown")
    
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
    tasks_text += f"\n\n*Нажми кнопку:*"
    
    await callback.message.answer(tasks_text, parse_mode="Markdown", reply_markup=get_report_keyboard(next_day))
    db_update_last_task_date(user_id)
    await callback.answer()

# ==================== НАПОМИНАНИЯ ====================
async def check_reminders():
    last_check_date = None
    while True:
        try:
            now = get_moscow_now()
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
                                tasks_text += f"\n\n*Нажми кнопку:*"
                                await bot.send_message(user_id, tasks_text, reply_markup=get_report_keyboard(next_day))
                                db_update_user_day(user_id, next_day)
                                db_update_last_task_date(user_id)
            await asyncio.sleep(30)
        except Exception as e:
            logger.error(f"Ошибка: {e}")
            await asyncio.sleep(60)

# ==================== ЗАПУСК ====================
async def set_commands():
    await bot.set_my_commands([BotCommand(command="start", description="Запустить бота")])

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
