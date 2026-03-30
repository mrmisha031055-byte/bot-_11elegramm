"""
TELEGRAM БОТ ДЛЯ 30-ДНЕВНОГО МАРАФОНА
Версия: 9.0 - С УЛУЧШЕННЫМ ДИЗАЙНОМ И МЕНЮ
"""

import asyncio
import logging
import sqlite3
import threading
import os
from datetime import datetime
from typing import Tuple, Optional, List

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    BotCommand, InlineKeyboardButton, KeyboardButton, 
    ReplyKeyboardMarkup, InlineKeyboardMarkup, BotCommandScopeChat
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession

import pytz

# ==================== НАСТРОЙКИ ====================
TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
ADMIN_ID = 8406317983

if TOKEN == "YOUR_BOT_TOKEN_HERE":
    raise ValueError("❌ Токен не найден!")

# Время по МСК
MSK_TZ = pytz.timezone('Europe/Moscow')

# Расписание
REMINDER_HOUR = 23
REMINDER_MINUTE = 59
TASKS_RELEASE_HOUR = 23
TASKS_RELEASE_MINUTE = 59
PREVIEW_BUTTON_HOUR = 18
PREVIEW_BUTTON_MINUTE = 30

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ==================== ПРОВЕРКА АДМИНА ====================
def is_admin(user_id: int) -> bool:
    return user_id == ADMIN_ID

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
            has_info_shown INTEGER DEFAULT 0,
            has_started_marathon INTEGER DEFAULT 0
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
    logger.info("База данных инициализирована")

# ==================== ФУНКЦИИ БД ====================
def db_add_user(user_id: int, username: str, first_name: str):
    with DB_LOCK:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("INSERT OR IGNORE INTO users (user_id, username, first_name, start_date, current_day, has_info_shown, has_started_marathon) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (user_id, username or "", first_name or "", datetime.now(MSK_TZ).isoformat(), 1, 0, 0))
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
        cur.execute("UPDATE users SET last_task_date = ? WHERE user_id = ?", (datetime.now(MSK_TZ).isoformat(), user_id))
        conn.commit()
        conn.close()

def db_update_last_report_date(user_id: int):
    with DB_LOCK:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("UPDATE users SET last_report_date = ? WHERE user_id = ?", (datetime.now(MSK_TZ).isoformat(), user_id))
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
                    (user_id, day, datetime.now(MSK_TZ).isoformat(), completed, total, status))
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
        cur.execute("UPDATE users SET current_day = 1, last_task_date = NULL, last_report_date = NULL, completed_30 = 0, is_active = 1, start_date = ?, has_info_shown = 0, has_started_marathon = 0 WHERE user_id = ?",
                    (datetime.now(MSK_TZ).isoformat(), user_id))
        conn.commit()
        conn.close()
    logger.info(f"Пользователь {user_id} полностью сброшен")

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

def db_set_started_marathon(user_id: int):
    with DB_LOCK:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("UPDATE users SET has_started_marathon = 1 WHERE user_id = ?", (user_id,))
        conn.commit()
        conn.close()

# ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ====================
def get_progress_bar(current_day: int, total_days: int = 30, width: int = 20):
    """Создает визуальный прогресс-бар"""
    filled = int(current_day / total_days * width)
    empty = width - filled
    bar = "▰" * filled + "▱" * empty
    return bar

def get_avg_score(reports: list) -> float:
    """Вычисляет среднюю оценку пользователя"""
    if not reports:
        return 0
    
    scores = {
        "5/5": 5, "3-4/5": 3.5, "0-2/5": 1,
        "6/6": 6, "4-5/6": 4.5, "0-3/6": 1.5,
        "4/4": 4, "2-3/4": 2.5, "0-1/4": 0.5,
        "3/3": 3, "2/3": 2, "0-1/3": 0.5
    }
    
    total = sum(scores.get(r[1], 0) for r in reports)
    return total / len(reports)

def get_score_emoji(score: float) -> str:
    """Возвращает эмодзи для средней оценки"""
    if score >= 5:
        return "🏆 ОТЛИЧНО"
    elif score >= 4:
        return "🎉 ХОРОШО"
    elif score >= 3:
        return "👍 НОРМАЛЬНО"
    elif score >= 2:
        return "📝 МАЛОВАТО"
    else:
        return "⚠️ ПЛОХО"

# ==================== КОНТЕНТ (ТЕКСТЫ) ====================
START_MESSAGE = """
🌟 ДОБРО ПОЖАЛОВАТЬ В МАРАФОН

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Твой личный спутник на ближайшие 30 дней.

📌 ГЛАВНОЕ ПРАВИЛО:
Я просто бот — никакого волшебства. Всё зависит
только от твоих действий.

⚠️ ВАЖНО:
Наступит момент, когда станет тяжело. В этот миг
у тебя будет выбор:
• сдаться → войти в 98% тех, кто останавливается
• продолжить → стать одним из 2% дошедших

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

👇 Нажми кнопку, чтобы узнать, что тебя ждёт
"""

INFO_MESSAGE = """
📋 О МАРАФОНЕ

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🔹 1–6 день — втягиваешься в процесс. Прочитаешь книгу, научишься вести дневники.

🔹 Дальше — каждый день выполняешь задания, которые войдут в твой новый распорядок.

❗️ ИНФОРМАЦИЯ

После нажатия кнопки «✅ СТАРТ» тебе придёт задание на День 1.

Если у тебя сейчас утро или день — начинай действовать прямо сейчас.
"""

FINAL_MESSAGE = """
🎉 МАРАФОН ЗАВЕРШЕН!

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Помнишь первый день? Каким ты был, когда нажал
«Старт»?

Неуверенным? Сомневающимся? Просто любопытным?

А сейчас? Посмотри на себя.

🏆 ТЫ ДОШЕЛ. ТЫ СДЕЛАЛ ЭТО.

Ты вошел в 2% людей, которые доходят до конца.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🌱 Цветок, который ты купил на 30-й день,
   пусть растет вместе с твоей новой версией.

🚀 Иди дальше. Я в тебя верю.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

REMINDER_MESSAGE = """
⚠️ ВНИМАНИЕ!

┌─────────────────────────────────┐
│  Вы не отчитались за сегодня    │
│                                 │
│  📋 ЧТО ДЕЛАТЬ:                 │
│  1. Выполните задания дня       │
│  2. Нажмите кнопку отчета       │
│  3. Получите обратную связь     │
└─────────────────────────────────┘

💡 Если уже выполнили — просто отправьте отчет!
"""

def format_daily_tasks(day: int, tasks_data: dict, current_day: int):
    """Красивое форматирование заданий дня"""
    tasks = tasks_data["tasks"]
    total = tasks_data["total"]
    progress_bar = get_progress_bar(current_day)
    
    message = (
        f"📅 ДЕНЬ {day} | {tasks_data['title']}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{progress_bar} {current_day}/30 дней\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    )
    
    for i, task in enumerate(tasks, 1):
        if "\n" in task:
            title, desc = task.split("\n", 1)
            message += f"<b>{i}. {title}</b>\n"
            for line in desc.split("\n"):
                if "https://" in line:
                    line = "   🔗 <i>ссылка в описании</i>"
                message += f"   {line}\n"
        else:
            message += f"<b>{i}. {task}</b>\n"
        message += "\n"
    
    message += (
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 <b>Всего заданий:</b> {total}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"✅ <i>После выполнения нажми кнопку ниже</i>"
    )
    
    return message

def format_status_card(user_data: Tuple, reports: list):
    """Красивая карточка статуса"""
    current_day = user_data[4]
    completed = len(reports)
    avg_score = get_avg_score(reports)
    score_emoji = get_score_emoji(avg_score)
    progress_bar = get_progress_bar(current_day)
    
    message = (
        f"📊 ВАШ СТАТУС\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🎯 <b>День:</b> {current_day} из 30\n\n"
        f"{progress_bar} {current_day}/30\n\n"
        f"✅ <b>Выполнено отчетов:</b> {completed}\n"
        f"⭐ <b>Средняя оценка:</b> {avg_score:.1f}/5 — {score_emoji}\n\n"
        f"🏆 <b>До финиша:</b> {30 - current_day} дней\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    )
    
    if reports:
        last_day, last_status, _ = reports[-1]
        status_emoji = {
            "5/5": "🏆", "3-4/5": "👍", "0-2/5": "📝",
            "6/6": "🏆", "4-5/6": "👍", "0-3/6": "📝",
            "4/4": "🏆", "2-3/4": "👍", "0-1/4": "📝",
            "3/3": "🏆", "2/3": "👍", "0-1/3": "📝"
        }.get(last_status, "📊")
        message += f"📅 <b>Последний отчет:</b> День {last_day} — {status_emoji} {last_status}\n"
    
    message += f"\n💡 <i>/help — список команд</i>"
    
    return message

def format_compact_preview(day: int, tasks_data: dict):
    """Компактный предпросмотр задач на завтра"""
    tasks = tasks_data["tasks"]
    total = tasks_data["total"]
    
    # Берем первые 3 задания для краткого предпросмотра
    preview_tasks = []
    for i, task in enumerate(tasks[:3], 1):
        title = task.split("\n")[0] if "\n" in task else task
        # Убираем эмодзи и звездочки для краткости
        title = title.replace("*", "").replace("📖", "").replace("📓", "").replace("🌙", "").strip()
        preview_tasks.append(f"   {i}. {title[:50]}")
    
    message = (
        f"🔮 ЗАВТРАШНИЙ ДЕНЬ\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"ДЕНЬ {day} | {tasks_data['title']}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    )
    
    for task in preview_tasks:
        message += f"{task}\n"
    
    if total > 3:
        message += f"\n   <i>... и еще {total - 3} заданий</i>\n"
    
    message += (
        f"\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 <b>Всего заданий:</b> {total}\n\n"
        f"💡 <i>Полный список придет сегодня в 23:59</i>"
    )
    
    return message

def format_feedback(day: int, status: str, feedback_text: str):
    """Красивое форматирование обратной связи после отчета"""
    status_emoji = {
        "5/5": "🏆", "3-4/5": "👍", "0-2/5": "📝",
        "6/6": "🏆", "4-5/6": "👍", "0-3/6": "📝",
        "4/4": "🏆", "2-3/4": "👍", "0-1/4": "📝",
        "3/3": "🏆", "2/3": "👍", "0-1/3": "📝"
    }.get(status, "📊")
    
    status_text = {
        "5/5": "ОТЛИЧНО!", "3-4/5": "ХОРОШО!", "0-2/5": "БЫВАЕТ",
        "6/6": "ОТЛИЧНО!", "4-5/6": "ХОРОШО!", "0-3/6": "БЫВАЕТ",
        "4/4": "ОТЛИЧНО!", "2-3/4": "ХОРОШО!", "0-1/4": "БЫВАЕТ",
        "3/3": "ОТЛИЧНО!", "2/3": "ХОРОШО!", "0-1/3": "БЫВАЕТ"
    }.get(status, "ГОТОВО!")
    
    # Очищаем feedback_text от markdown
    feedback_clean = feedback_text.replace("*", "").replace("✅", "").replace("🟡", "").replace("🔴", "").strip()
    
    message = (
        f"{status_emoji} {status_text}\n\n"
        f"┌─────────────────────────────────┐\n"
        f"│  {feedback_clean[:48]}│\n"
        f"└─────────────────────────────────┘\n"
    )
    
    return message

# ==================== КНОПКИ ====================
def get_start_keyboard():
    """Клавиатура для нового пользователя (до старта марафона)"""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📋 О МАРАФОНЕ")],
            [KeyboardButton(text="✅ СТАРТ")]
        ],
        resize_keyboard=True
    )

def get_main_menu_keyboard():
    """Главное меню для активных участников"""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📊 МОЙ СТАТУС"), KeyboardButton(text="📅 ЗАДАЧИ НА ЗАВТРА")],
            [KeyboardButton(text="💬 ЕСЛИ ВОЗНИКЛИ ПРОБЛЕМЫ С БОТОМ")]
        ],
        resize_keyboard=True
    )

def get_report_keyboard(day: int):
    total = DAILY_TASKS[day]["total"]
    builder = InlineKeyboardBuilder()
    
    if total == 6:
        builder.row(
            InlineKeyboardButton(text="🏆 ОТЛИЧНО (6/6)", callback_data=f"report_6/6_{day}"),
            InlineKeyboardButton(text="👍 НОРМАЛЬНО (4-5/6)", callback_data=f"report_4-5/6_{day}")
        )
        builder.row(
            InlineKeyboardButton(text="📝 ПЛОХО (0-3/6)", callback_data=f"report_0-3/6_{day}")
        )
    elif total == 5:
        builder.row(
            InlineKeyboardButton(text="🏆 ОТЛИЧНО (5/5)", callback_data=f"report_5/5_{day}"),
            InlineKeyboardButton(text="👍 НОРМАЛЬНО (3-4/5)", callback_data=f"report_3-4/5_{day}")
        )
        builder.row(
            InlineKeyboardButton(text="📝 ПЛОХО (0-2/5)", callback_data=f"report_0-2/5_{day}")
        )
    elif total == 4:
        builder.row(
            InlineKeyboardButton(text="🏆 ОТЛИЧНО (4/4)", callback_data=f"report_4/4_{day}"),
            InlineKeyboardButton(text="👍 НОРМАЛЬНО (2-3/4)", callback_data=f"report_2-3/4_{day}")
        )
        builder.row(
            InlineKeyboardButton(text="📝 ПЛОХО (0-1/4)", callback_data=f"report_0-1/4_{day}")
        )
    else:
        builder.row(
            InlineKeyboardButton(text="🏆 ОТЛИЧНО (3/3)", callback_data=f"report_3/3_{day}"),
            InlineKeyboardButton(text="👍 НОРМАЛЬНО (2/3)", callback_data=f"report_2/3_{day}")
        )
        builder.row(
            InlineKeyboardButton(text="📝 ПЛОХО (0-1/3)", callback_data=f"report_0-1/3_{day}")
        )
    
    return builder.as_markup()

def get_hide_preview_keyboard():
    """Клавиатура для скрытия предпросмотра"""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="❌ Скрыть предпросмотр", callback_data="hide_preview")]
        ]
    )

def get_cancel_keyboard():
    """Клавиатура для отмены отправки сообщения админу"""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_report")]
        ]
    )

# ==================== БОТ ====================
bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

active_previews = {}
waiting_for_problem = {}

# ==================== ОСНОВНЫЕ ОБРАБОТЧИКИ ====================

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    user = message.from_user
    db_add_user(user.id, user.username, user.first_name)
    user_data = db_get_user(user.id)
    
    if not user_data:
        await message.answer("Произошла ошибка. Попробуйте позже.")
        return
    
    current_day = user_data[4]
    completed_30 = user_data[8]
    has_started = user_data[10] if len(user_data) > 10 else 0
    
    if completed_30 == 1:
        await message.answer(FINAL_MESSAGE, parse_mode="HTML", reply_markup=types.ReplyKeyboardRemove())
        return
    
    reports = db_get_user_reports(user.id)
    if len(reports) > 0 or has_started == 1:
        await message.answer(
            f"👋 С возвращением!\n\nТы на <b>{current_day} дне</b> из 30.",
            parse_mode="HTML",
            reply_markup=get_main_menu_keyboard()
        )
    else:
        await message.answer(START_MESSAGE, parse_mode="HTML", reply_markup=get_start_keyboard())

@dp.message(Command("my_status"))
async def my_status_command(message: types.Message):
    user_id = message.from_user.id
    user_data = db_get_user(user_id)
    
    if not user_data:
        await message.answer("❌ Вы не зарегистрированы. Нажмите /start")
        return
    
    reports = db_get_user_reports(user_id)
    status_text = format_status_card(user_data, reports)
    
    await message.answer(status_text, parse_mode="HTML")

@dp.message(F.text == "📋 О МАРАФОНЕ")
async def get_info(message: types.Message):
    user_id = message.from_user.id
    user_data = db_get_user(user_id)
    
    if not user_data:
        await message.answer("Произошла ошибка. Нажмите /start")
        return
    
    has_started = user_data[10] if len(user_data) > 10 else 0
    reports = db_get_user_reports(user_id)
    
    if len(reports) > 0 or has_started == 1:
        await message.answer(
            "⚠️ Ты уже начал марафон!\n\nТвои задачи на сегодня уже ждут тебя.",
            parse_mode="HTML"
        )
        return
    
    db_set_info_shown(user_id)
    await message.answer(INFO_MESSAGE, parse_mode="HTML", reply_markup=get_start_keyboard())

@dp.message(F.text == "✅ СТАРТ")
async def i_am_ready(message: types.Message):
    user_id = message.from_user.id
    user_data = db_get_user(user_id)
    
    if not user_data:
        await message.answer("Произошла ошибка. Нажми /start")
        return
    
    current_day = user_data[4]
    completed_30 = user_data[8]
    has_info_shown = user_data[9]
    has_started = user_data[10] if len(user_data) > 10 else 0
    
    reports = db_get_user_reports(user_id)
    if len(reports) > 0 or has_started == 1:
        await message.answer(
            f"⚠️ Ты уже начал марафон!\n\nТы на {current_day} дне.",
            parse_mode="HTML",
            reply_markup=get_main_menu_keyboard()
        )
        return
    
    if has_info_shown == 0:
        await message.answer(
            "⚠️ Сначала нажми кнопку «📋 О МАРАФОНЕ»!\n\nТам я расскажу, что тебя ждёт.",
            parse_mode="HTML"
        )
        return
    
    if completed_30 == 1:
        await message.answer(FINAL_MESSAGE, parse_mode="HTML", reply_markup=types.ReplyKeyboardRemove())
        return
    
    db_set_started_marathon(user_id)
    
    day_tasks = DAILY_TASKS[1]
    tasks_text = format_daily_tasks(1, day_tasks, 1)
    
    await message.answer(tasks_text, parse_mode="HTML", reply_markup=get_report_keyboard(1))
    db_update_last_task_date(user_id)
    
    await message.answer(
        "🎯 МАРАФОН НАЧАЛСЯ!\n\n"
        "Теперь у тебя будет главное меню.\n"
        "Кнопка «📅 ЗАДАЧИ НА ЗАВТРА» станет доступна после отчета или после 18:30.",
        parse_mode="HTML",
        reply_markup=get_main_menu_keyboard()
    )

@dp.message(F.text == "📊 МОЙ СТАТУС")
async def show_status(message: types.Message):
    user_id = message.from_user.id
    user_data = db_get_user(user_id)
    
    if not user_data:
        await message.answer("❌ Вы не зарегистрированы. Нажмите /start")
        return
    
    reports = db_get_user_reports(user_id)
    status_text = format_status_card(user_data, reports)
    
    await message.answer(status_text, parse_mode="HTML")

@dp.message(F.text == "📅 ЗАДАЧИ НА ЗАВТРА")
async def show_next_day_tasks(message: types.Message):
    user_id = message.from_user.id
    user_data = db_get_user(user_id)
    
    if not user_data:
        await message.answer("❌ Вы не зарегистрированы. Нажмите /start")
        return
    
    current_day = user_data[4]
    completed_30 = user_data[8]
    has_started = user_data[10] if len(user_data) > 10 else 0
    
    reports = db_get_user_reports(user_id)
    if len(reports) == 0 and has_started == 0:
        await message.answer(
            "⚠️ Ты еще не начал марафон!\n\n"
            "Сначала нажми «📋 О МАРАФОНЕ», а затем «✅ СТАРТ».",
            parse_mode="HTML"
        )
        return
    
    if completed_30 == 1:
        await message.answer("🎉 Ты уже завершил марафон!", parse_mode="HTML")
        return
    
    if current_day >= 30:
        await message.answer(
            "🎉 Это последний день марафона! Завтра уже не будет заданий.",
            parse_mode="HTML"
        )
        return
    
    next_day = current_day + 1
    previous_day = current_day - 1
    has_report_previous = db_get_report_status(user_id, previous_day) if previous_day >= 1 else False
    
    now = datetime.now(MSK_TZ)
    is_after_1830 = now.hour >= PREVIEW_BUTTON_HOUR and now.minute >= PREVIEW_BUTTON_MINUTE
    
    if current_day == 1:
        await message.answer(
            "📝 Ты на первом дне марафона!\n\n"
            "Сначала выполни задания 1 дня и отправь отчет.\n"
            "После этого станет доступен предпросмотр 2 дня.",
            parse_mode="HTML"
        )
        return
    
    if not has_report_previous and not is_after_1830:
        await message.answer(
            f"🔒 Предпросмотр задач на {next_day} день пока недоступен\n\n"
            f"📋 Условия для появления кнопки:\n"
            f"{'✅' if has_report_previous else '❌'} Отчитаться за {previous_day} день\n"
            f"{'✅' if is_after_1830 else '❌'} Наступление 18:30 по МСК\n\n"
            f"Твой текущий день: {current_day}\n"
            f"Текущее время: {now.strftime('%H:%M')} МСК",
            parse_mode="HTML"
        )
        return
    
    next_day_tasks = DAILY_TASKS[next_day]
    tasks_preview = format_compact_preview(next_day, next_day_tasks)
    
    sent_msg = await message.answer(tasks_preview, parse_mode="HTML", reply_markup=get_hide_preview_keyboard())
    active_previews[user_id] = sent_msg.message_id

@dp.message(F.text == "💬 ЕСЛИ ВОЗНИКЛИ ПРОБЛЕМЫ С БОТОМ")
async def report_problem(message: types.Message):
    user_id = message.from_user.id
    
    waiting_for_problem[user_id] = True
    
    await message.answer(
        "💬 НАПИШИТЕ ПРОБЛЕМУ\n\n"
        "Опишите подробно, что случилось.\n\n"
        "<i>Сообщение будет отправлено администратору.</i>",
        parse_mode="HTML",
        reply_markup=get_cancel_keyboard()
    )

@dp.callback_query(lambda c: c.data == "cancel_report")
async def cancel_report(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    
    if user_id in waiting_for_problem:
        del waiting_for_problem[user_id]
    
    await callback.message.delete()
    await callback.answer("Отправка отменена", show_alert=False)
    await callback.message.answer("✅ Отправка отменена.", parse_mode="HTML")

@dp.message()
async def handle_problem_message(message: types.Message):
    user_id = message.from_user.id
    
    if user_id not in waiting_for_problem:
        return
    
    del waiting_for_problem[user_id]
    
    user_data = db_get_user(user_id)
    current_day = user_data[4] if user_data else "неизвестно"
    
    problem_text = message.text
    username = message.from_user.username
    first_name = message.from_user.first_name
    
    admin_message = (
        f"🆘 <b>НОВОЕ СООБЩЕНИЕ ОТ ПОЛЬЗОВАТЕЛЯ</b>\n\n"
        f"👤 <b>ID:</b> <code>{user_id}</code>\n"
        f"📝 <b>Имя:</b> {first_name}\n"
        f"🔖 <b>Username:</b> @{username if username else 'нет'}\n"
        f"📅 <b>Текущий день:</b> {current_day}\n\n"
        f"💬 <b>Сообщение:</b>\n{problem_text}"
    )
    
    try:
        await bot.send_message(ADMIN_ID, admin_message, parse_mode="HTML")
        await message.answer(
            "✅ Сообщение отправлено администратору.\n\nМы свяжемся с вами в ближайшее время.",
            parse_mode="HTML"
        )
        logger.info(f"Проблема от {user_id} отправлена админу")
    except Exception as e:
        logger.error(f"Ошибка при отправке сообщения админу: {e}")
        await message.answer(
            "❌ Не удалось отправить сообщение. Попробуйте позже.",
            parse_mode="HTML"
        )

@dp.callback_query(lambda c: c.data == "hide_preview")
async def hide_preview(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    
    try:
        await callback.message.delete()
    except:
        pass
    
    if user_id in active_previews:
        del active_previews[user_id]
    
    await callback.answer("✅ Предпросмотр скрыт")

@dp.callback_query(lambda c: c.data.startswith('report_'))
async def process_report(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    callback_data = callback.data
    
    parts = callback_data.split('_')
    if len(parts) < 3:
        await callback.answer("❌ Ошибка формата", show_alert=True)
        return
    
    report_key = parts[1]
    reported_day = int(parts[2])
    
    user_data = db_get_user(user_id)
    if not user_data:
        await callback.message.answer("Произошла ошибка. Нажми /start")
        await callback.answer()
        return
    
    current_day = user_data[4]
    
    if reported_day != current_day:
        await callback.answer(f"❌ Эта кнопка для дня {reported_day}, а вы на дне {current_day}", show_alert=True)
        await callback.message.delete()
        return
    
    if db_get_report_status(user_id, current_day):
        await callback.answer("❌ Ты уже отчитался за этот день!", show_alert=True)
        await callback.message.delete()
        return
    
    completed_map = {
        "5/5": 5, "3-4/5": 3, "0-2/5": 1,
        "6/6": 6, "4-5/6": 4, "0-3/6": 1,
        "4/4": 4, "2-3/4": 2, "0-1/4": 0,
        "3/3": 3, "2/3": 2, "0-1/3": 0
    }
    completed = completed_map.get(report_key, 0)
    
    db_save_report(user_id, current_day, completed, DAILY_TASKS[current_day]["total"], report_key)
    db_update_last_report_date(user_id)
    
    await callback.message.delete()
    
    feedback_text = FEEDBACK_MESSAGES[current_day].get(report_key, f"✅ Отчет за день {current_day} принят! Ты молодец! 🔥")
    formatted_feedback = format_feedback(current_day, report_key, feedback_text)
    
    await callback.message.answer(formatted_feedback, parse_mode="HTML")
    
    if current_day in SUPPORT_MESSAGES:
        await asyncio.sleep(0.5)
        await callback.message.answer(SUPPORT_MESSAGES[current_day], parse_mode="HTML")
        await asyncio.sleep(1)
    
    if current_day == 30:
        db_complete_marathon(user_id)
        await callback.message.answer(FINAL_MESSAGE, parse_mode="HTML")
        await callback.answer()
        return
    
    next_day = current_day + 1
    db_update_user_day(user_id, next_day)
    
    await callback.message.answer(
        f"✅ ОТЛИЧНО! Отчёт за {current_day} день принят!\n\n"
        f"📅 Завтра (День {next_day}) в 23:59 МСК ты получишь новые задания.\n\n"
        f"А пока можешь посмотреть, что ждёт тебя завтра, нажав кнопку «📅 ЗАДАЧИ НА ЗАВТРА».",
        parse_mode="HTML",
        reply_markup=get_main_menu_keyboard()
    )
    
    await callback.answer()

# ==================== ФОНОВЫЕ ЗАДАЧИ ====================

async def check_reminders():
    """Напоминание о неотчете в 23:59 МСК"""
    last_check_date = None
    
    while True:
        try:
            now = datetime.now(MSK_TZ)
            current_date = now.date()
            
            if now.hour == REMINDER_HOUR and now.minute >= REMINDER_MINUTE:
                if last_check_date != current_date:
                    last_check_date = current_date
                    logger.info(f"Запуск проверки напоминаний на {current_date}")
                    
                    users = db_get_all_active_users()
                    
                    for user_id, current_day in users:
                        try:
                            has_report = db_get_report_status(user_id, current_day)
                            if has_report:
                                continue
                            
                            await bot.send_message(
                                user_id, 
                                REMINDER_MESSAGE,
                                parse_mode="HTML"
                            )
                            
                            day_tasks = DAILY_TASKS[current_day]
                            tasks_text = format_daily_tasks(current_day, day_tasks, current_day)
                            
                            await bot.send_message(
                                user_id, 
                                tasks_text, 
                                parse_mode="HTML", 
                                reply_markup=get_report_keyboard(current_day)
                            )
                            
                            logger.info(f"Напоминание отправлено пользователю {user_id} (день {current_day})")
                            
                        except Exception as e:
                            logger.error(f"Ошибка при отправке напоминания пользователю {user_id}: {e}")
            
            await asyncio.sleep(30)
            
        except Exception as e:
            logger.error(f"Критическая ошибка в check_reminders: {e}")
            await asyncio.sleep(60)

async def release_daily_tasks():
    """Выдает задачи в 23:59 МСК всем, кто отчитался за предыдущий день"""
    last_release_date = None
    
    while True:
        try:
            now = datetime.now(MSK_TZ)
            current_date = now.date()
            
            if now.hour == TASKS_RELEASE_HOUR and now.minute >= TASKS_RELEASE_MINUTE:
                if last_release_date != current_date:
                    last_release_date = current_date
                    logger.info(f"Запуск выдачи задач на {current_date}")
                    
                    users = db_get_all_active_users()
                    
                    for user_id, current_day in users:
                        try:
                            if current_day == 1:
                                continue
                            
                            previous_day = current_day - 1
                            has_report_previous = db_get_report_status(user_id, previous_day)
                            
                            if has_report_previous and current_day <= 30:
                                day_tasks = DAILY_TASKS[current_day]
                                tasks_text = format_daily_tasks(current_day, day_tasks, current_day)
                                
                                await bot.send_message(
                                    user_id, 
                                    tasks_text, 
                                    parse_mode="HTML", 
                                    reply_markup=get_report_keyboard(current_day)
                                )
                                db_update_last_task_date(user_id)
                                logger.info(f"✅ Задачи на день {current_day} выданы пользователю {user_id}")
                            else:
                                logger.info(f"⚠️ Пользователь {user_id} не отчитался за день {previous_day}, задачи на день {current_day} не выданы")
                                
                        except Exception as e:
                            logger.error(f"Ошибка при выдаче задач пользователю {user_id}: {e}")
            
            await asyncio.sleep(30)
            
        except Exception as e:
            logger.error(f"Критическая ошибка в release_daily_tasks: {e}")
            await asyncio.sleep(60)

# ==================== АДМИН-КОМАНДЫ ====================

@dp.message(Command("admin"))
async def admin_command(message: types.Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌ У вас нет доступа к этой команде.")
        return
    
    users = db_get_all_users()
    
    if not users:
        await message.answer("📊 Нет пользователей", parse_mode="HTML")
        return
    
    active = [u for u in users if u[4] != 30 and u[4] == 0]
    completed = [u for u in users if u[4] == 1]
    
    text = (
        f"📊 ПАНЕЛЬ АДМИНИСТРАТОРА\n\n"
        f"👥 Всего: {len(users)}\n"
        f"✅ Активных: {len(active)}\n"
        f"🏆 Завершили: {len(completed)}\n\n"
        f"📋 Доступные команды:\n"
        f"• /admin_info ID - информация о пользователе\n"
        f"• /admin_reset ID - сброс на день 1\n"
        f"• /admin_force_reset ID - полный сброс\n"
        f"• /admin_set_day ID день - установить день\n"
        f"• /admin_sync ID - синхронизация\n\n"
        f"Список активных пользователей:\n"
    )
    
    for user in active[:20]:
        user_id, username, first_name, day, _, _ = user
        name = first_name or username or str(user_id)
        text += f"👤 {name} (ID: <code>{user_id}</code>) — День {day}\n"
    
    if len(active) > 20:
        text += f"\n... и еще {len(active) - 20} пользователей"
    
    await message.answer(text, parse_mode="HTML")

@dp.message(Command("admin_info"))
async def admin_info(message: types.Message):
    if not is_admin(message.from_user.id):
        return
    
    args = message.text.split()
    if len(args) < 2:
        await message.answer("❌ Использование: /admin_info user_id", parse_mode="HTML")
        return
    
    try:
        user_id = int(args[1])
        user = db_get_user(user_id)
        
        if not user:
            await message.answer(f"❌ Пользователь с ID {user_id} не найден.")
            return
        
        reports = db_get_user_reports(user_id)
        
        info_text = (
            f"📊 ИНФОРМАЦИЯ О ПОЛЬЗОВАТЕЛЕ\n\n"
            f"👤 ID: <code>{user[0]}</code>\n"
            f"📝 Имя: {user[2] or 'Не указано'}\n"
            f"🔖 Username: @{user[1] if user[1] else 'Не указан'}\n"
            f"📅 Дата старта: {user[3].split('T')[0] if user[3] else 'Не указана'}\n"
            f"📊 Текущий день: {user[4]}\n"
            f"✅ Завершил марафон: {'Да' if user[8] == 1 else 'Нет'}\n"
            f"📝 Последний отчет: {user[6].split('T')[0] if user[6] else 'Нет'}\n\n"
        )
        
        if reports:
            info_text += f"📋 ОТЧЕТЫ ПО ДНЯМ:\n"
            for report in reports[-10:]:
                day, status, date = report
                date_short = date.split('T')[0] if date else 'Неизвестно'
                info_text += f"День {day}: {status} ({date_short})\n"
        else:
            info_text += f"📋 Нет ни одного отчета"
        
        await message.answer(info_text, parse_mode="HTML")
        
    except ValueError:
        await message.answer("❌ Неверный ID пользователя.")

@dp.message(Command("admin_reset"))
async def admin_reset_user(message: types.Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌ У вас нет доступа к этой команде.")
        return
    
    args = message.text.split()
    if len(args) < 2:
        await message.answer("❌ Использование: /admin_reset user_id", parse_mode="HTML")
        return
    
    try:
        user_id = int(args[1])
        user = db_get_user(user_id)
        
        if not user:
            await message.answer(f"❌ Пользователь с ID {user_id} не найден.")
            return
        
        db_reset_user(user_id)
        
        await message.answer(
            f"✅ Прогресс пользователя сброшен\n\n"
            f"👤 ID: {user_id}\n"
            f"📝 Имя: {user[2] or user[1] or 'Не указано'}\n"
            f"📊 Был на дне: {user[4]}\n"
            f"🔄 Сброшен на день: 1",
            parse_mode="HTML"
        )
        
        try:
            await bot.send_message(
                user_id, 
                "🔄 Администратор сбросил ваш прогресс в марафоне!\n\nТеперь вы можете начать марафон заново. Нажмите /start для начала.",
                parse_mode="HTML"
            )
        except:
            pass
            
    except ValueError:
        await message.answer("❌ Неверный ID пользователя.")

@dp.message(Command("admin_force_reset"))
async def admin_force_reset_user(message: types.Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌ У вас нет доступа к этой команде.")
        return
    
    args = message.text.split()
    if len(args) < 2:
        await message.answer("❌ Использование: /admin_force_reset user_id", parse_mode="HTML")
        return
    
    try:
        user_id = int(args[1])
        user = db_get_user(user_id)
        
        if not user:
            await message.answer(f"❌ Пользователь с ID {user_id} не найден.")
            return
        
        db_reset_user(user_id)
        
        await message.answer(
            f"✅ Принудительный полный сброс выполнен\n\n"
            f"👤 ID: {user_id}\n"
            f"🔄 Все данные очищены, пользователь сброшен на день 1",
            parse_mode="HTML"
        )
        
        try:
            await bot.send_message(
                user_id, 
                "🔄 Ваш прогресс был полностью сброшен администратором!\n\nТеперь вы можете начать марафон заново. Нажмите /start для начала.",
                parse_mode="HTML"
            )
        except:
            pass
            
    except ValueError:
        await message.answer("❌ Неверный ID пользователя.")

@dp.message(Command("admin_set_day"))
async def admin_set_user_day(message: types.Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌ У вас нет доступа к этой команде.")
        return
    
    args = message.text.split()
    if len(args) < 3:
        await message.answer("❌ Использование: /admin_set_day user_id день\n\nДень должен быть от 1 до 30", parse_mode="HTML")
        return
    
    try:
        user_id = int(args[1])
        new_day = int(args[2])
        
        if new_day < 1 or new_day > 30:
            await message.answer("❌ День должен быть от 1 до 30.")
            return
        
        user = db_get_user(user_id)
        if not user:
            await message.answer(f"❌ Пользователь с ID {user_id} не найден.")
            return
        
        old_day = user[4]
        db_update_user_day(user_id, new_day)
        
        if user[8] == 1:
            with DB_LOCK:
                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("UPDATE users SET completed_30 = 0, is_active = 1 WHERE user_id = ?", (user_id,))
                conn.commit()
                conn.close()
        
        await message.answer(
            f"✅ День пользователя изменен\n\n"
            f"👤 ID: {user_id}\n"
            f"📊 Был на дне: {old_day}\n"
            f"🔄 Установлен день: {new_day}",
            parse_mode="HTML"
        )
        
        try:
            await bot.send_message(
                user_id, 
                f"🔄 Администратор изменил ваш день в марафоне!\n\n📊 Текущий день: {new_day} из 30\n\nНажмите /start, чтобы продолжить.",
                parse_mode="HTML"
            )
        except:
            pass
            
    except ValueError:
        await message.answer("❌ Неверный ID пользователя или день.")

@dp.message(Command("admin_sync"))
async def admin_sync_user(message: types.Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌ У вас нет доступа к этой команде.")
        return
    
    args = message.text.split()
    if len(args) < 2:
        await message.answer("❌ Использование: /admin_sync user_id", parse_mode="HTML")
        return
    
    try:
        user_id = int(args[1])
        user = db_get_user(user_id)
        
        if not user:
            await message.answer(f"❌ Пользователь с ID {user_id} не найден.")
            return
        
        reports = db_get_user_reports(user_id)
        has_day30 = any(r[0] == 30 for r in reports)
        correct_completed = 1 if has_day30 else 0
        
        if reports:
            max_day = max(r[0] for r in reports)
            correct_day = max_day + 1 if max_day < 30 else 30
        else:
            correct_day = 1
        
        updates = []
        
        if user[8] != correct_completed:
            updates.append(f"completed_30: {user[8]} → {correct_completed}")
            with DB_LOCK:
                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("UPDATE users SET completed_30 = ? WHERE user_id = ?", (correct_completed, user_id))
                conn.commit()
                conn.close()
        
        if user[4] != correct_day:
            updates.append(f"current_day: {user[4]} → {correct_day}")
            with DB_LOCK:
                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("UPDATE users SET current_day = ? WHERE user_id = ?", (correct_day, user_id))
                conn.commit()
                conn.close()
        
        if updates:
            await message.answer(
                f"✅ Синхронизация выполнена\n\n"
                f"👤 ID: {user_id}\n"
                f"📊 Всего отчетов: {len(reports)}\n"
                f"🔧 Исправлено:\n" + "\n".join(updates),
                parse_mode="HTML"
            )
            
            try:
                await bot.send_message(
                    user_id, 
                    "🔄 Ваши данные в марафоне были синхронизированы!\n\nНажмите /start для продолжения.",
                    parse_mode="HTML"
                )
            except:
                pass
        else:
            await message.answer(
                f"✅ Синхронизация выполнена\n\n"
                f"👤 ID: {user_id}\n"
                f"✨ Данные уже корректны. Исправлений не требуется.",
                parse_mode="HTML"
            )
        
    except ValueError:
        await message.answer("❌ Неверный ID пользователя.")
    except Exception as e:
        await message.answer(f"❌ Произошла ошибка: {str(e)}")

@dp.message(Command("stats"))
async def stats_command(message: types.Message):
    if not is_admin(message.from_user.id):
        return
    
    users = db_get_all_users()
    
    if not users:
        await message.answer("Нет данных")
        return
    
    active = [u for u in users if u[4] != 30 and u[4] == 0]
    completed = [u for u in users if u[4] == 1]
    
    day_counts = {}
    for user in active:
        day = user[3]
        day_counts[day] = day_counts.get(day, 0) + 1
    
    text = (
        f"📈 РАСШИРЕННАЯ СТАТИСТИКА\n\n"
        f"👥 Всего пользователей: {len(users)}\n"
        f"✅ Активных: {len(active)}\n"
        f"🏆 Завершили: {len(completed)}\n\n"
        f"📊 Распределение по дням:\n"
    )
    
    for day in sorted(day_counts.keys()):
        text += f"День {day}: {day_counts[day]} пользователей\n"
    
    await message.answer(text, parse_mode="HTML")

# ==================== ЗАПУСК ====================
async def set_commands():
    public_commands = [
        BotCommand(command="start", description="Запустить бота"),
        BotCommand(command="my_status", description="Мой статус"),
    ]
    
    admin_commands = [
        BotCommand(command="admin", description="Админ-панель"),
        BotCommand(command="admin_info", description="Информация о пользователе"),
        BotCommand(command="admin_reset", description="Сброс пользователя"),
        BotCommand(command="admin_force_reset", description="Полный сброс"),
        BotCommand(command="admin_set_day", description="Установить день"),
        BotCommand(command="admin_sync", description="Синхронизация"),
        BotCommand(command="stats", description="Статистика")
    ]
    
    await bot.set_my_commands(public_commands)
    await bot.set_my_commands(admin_commands, scope=BotCommandScopeChat(chat_id=ADMIN_ID))
    
    logger.info("✅ Команды установлены")

async def on_startup():
    logger.info("🚀 Бот запускается...")
    init_db()
    await set_commands()
    asyncio.create_task(check_reminders())
    asyncio.create_task(release_daily_tasks())
    logger.info("✅ Бот готов к работе!")

async def on_shutdown():
    logger.info("🛑 Бот останавливается...")

async def main():
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)
    
    try:
        await dp.start_polling(bot)
    finally:
        await on_shutdown()

if __name__ == "__main__":
    asyncio.run(main())
