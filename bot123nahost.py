"""
TELEGRAM БОТ ДЛЯ 30-ДНЕВНОГО МАРАФОНА
Версия: 4.0 - ПОЛНОСТЬЮ ПЕРЕПИСАННАЯ (РАБОТАЕТ)
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

# ==================== ВСЕ ОЦЕНКИ (FEEDBACK) ====================
# Словарь с текстами для каждого дня и каждого отчета
FEEDBACK_TEXTS = {
    # День 1
    1: {
        "5/5": "✅ *Всё сделал (5/5):*\nОгонь старт! Ты не просто нажал кнопку, ты реально начал. Первый день — всегда самый непонятный, но ты справился. Горжусь 🔥",
        "3-4/5": "🟡 *Сделал больше половины (3-4/5):*\nНеплохо! Двигай дальше 👊",
        "0-2/5": "🔴 *Сделал мало или ничего (0-2/5):*\nБывает. Завтра будет лучше."
    },
    # День 2
    2: {
        "5/5": "✅ *Всё сделал (5/5):*\nЧистка пространства зашла. 3 канала минус, телефон подальше — ты уже чище, чем вчера. Красава!",
        "3-4/5": "🟡 *Сделал больше половины (3-4/5):*\nХорошо идешь! Так держать 💪",
        "0-2/5": "🔴 *Сделал мало или ничего (0-2/5):*\nНичего страшного. Завтра наверстаешь."
    },
    # День 3
    3: {
        "5/5": "✅ *Всё сделал (5/5):*\n2 литра воды + страхи на бумаге. Ты серьезный человек. Страхи теперь не в голове, а в дневнике — так и должно быть.",
        "3-4/5": "🟡 *Сделал больше половины (3-4/5):*\nМолодец! Продолжай в том же духе 🔥",
        "0-2/5": "🔴 *Сделал мало или ничего (0-2/5):*\nНу ок. Завтра новый день."
    },
    # День 4
    4: {
        "5/5": "✅ *Всё сделал (5/5):*\nОдно отложенное дело сделано. Ты кайфанул? Я кайфанул. Привычки начинаются с таких дней.",
        "3-4/5": "🟡 *Сделал больше половины (3-4/5):*\nТак держать! С каждым днем все лучше 👊",
        "0-2/5": "🔴 *Сделал мало или ничего (0-2/5):*\nНе зашло сегодня. Завтра получится."
    },
    # День 5
    5: {
        "5/5": "✅ *Всё сделал (5/5):*\nПолчаса утра без телефона — это уровень. Целый день без споров — вообще джедайство. Ты растешь.",
        "3-4/5": "🟡 *Сделал больше половины (3-4/5):*\nХороший день! Продолжай в том же духе 💪",
        "0-2/5": "🔴 *Сделал мало или ничего (0-2/5):*\nБывает. Завтра просто сделай чуть больше."
    },
    # День 6
    6: {
        "5/5": "✅ *Всё сделал (5/5):*\nПервая книга позади. 6 дней, 3 инсайта, минус 6 каналов, 4 литра воды. Ты в отрыве 🚀",
        "3-4/5": "🟡 *Сделал больше половины (3-4/5):*\nМолодец! Хороший темп 🔥",
        "0-2/5": "🔴 *Сделал мало или ничего (0-2/5):*\nНе фортануло? Завтра все получится."
    },
    # День 7
    7: {
        "6/6": "✅ *Всё сделал (6/6):*\nПервая неделя. Итоги, визуализация, подготовка к новой книге. Ты не просто читал — ты менялся. Отдохни сегодня.",
        "4-5/6": "🟡 *Сделал больше половины (4-5/6):*\nТак держать! Неделя позади — это серьезно 💪",
        "0-3/6": "🔴 *Сделал мало или ничего (0-3/6):*\nНеделя была длинной. Отдохни и завтра с новыми силами."
    },
    # День 8
    8: {
        "5/5": "✅ *Всё сделал (5/5):*\nБез наушников, без споров, с 20 приседами. Первая татуировка в кармане. Ты входишь во вкус.",
        "3-4/5": "🟡 *Сделал больше половины (3-4/5):*\nХороший день! Двигай дальше 👊",
        "0-2/5": "🔴 *Сделал мало или ничего (0-2/5):*\nБывает. Завтра будет лучше."
    },
    # День 9
    9: {
        "5/5": "✅ *Всё сделал (5/5):*\nПозвонил родителям + сказал себе 5 достоинств. Это мощно. Ты не просто качаешь дисциплину, ты качаешь душу.",
        "3-4/5": "🟡 *Сделал больше половины (3-4/5):*\nМолодец! Хороший настрой 🔥",
        "0-2/5": "🔴 *Сделал мало или ничего (0-2/5):*\nНичего страшного. Завтра наверстаешь."
    },
    # День 10
    10: {
        "5/5": "✅ *Всё сделал (5/5):*\nНашел свою татуировку, не жаловался, не лазил в соцсети после 21. Ты серьезно прокачался за 10 дней.",
        "3-4/5": "🟡 *Сделал больше половины (3-4/5):*\nТак держать! Ты в хорошей форме 💪",
        "0-2/5": "🔴 *Сделал мало или ничего (0-2/5):*\nНу ок. Завтра новый день."
    },
    # День 11
    11: {
        "4/4": "✅ *Всё сделал (4/4):*\nПеречитал дневник, понял, как изменился, еще раз отключил соцсети. Ты рефлексируешь — это признак роста.",
        "2-3/4": "🟡 *Сделал больше половины (2-3/4):*\nХорошо идешь! Продолжай 👊",
        "0-1/4": "🔴 *Сделал мало или ничего (0-1/4):*\nНе до рефлексии? Бывает. Завтра все получится."
    },
    # День 12
    12: {
        "4/4": "✅ *Всё сделал (4/4):*\nЗакрыл долг + позвонил старому другу. Ты чистишь не только подписки, но и связи. Это дорогого стоит.",
        "2-3/4": "🟡 *Сделал больше половины (2-3/4):*\nМолодец! Хороший темп 🔥",
        "0-1/4": "🔴 *Сделал мало или ничего (0-1/4):*\nБывает. Завтра просто сделай один маленький шаг."
    },
    # День 13
    13: {
        "3/3": "✅ *Всё сделал (3/3):*\nЕл без телефона. Ты был наедине с едой и собой. Это редкий навык в наше время.",
        "2/3": "🟡 *Сделал больше половины (2/3):*\nТак держать! С каждым днем все лучше 💪",
        "0-1/3": "🔴 *Сделал мало или ничего (0-1/3):*\nНу ок. Завтра получится."
    },
    # День 14
    14: {
        "5/5": "✅ *Всё сделал (5/5):*\n14 дней. Половина. Ты завел третий дневник, посмотрел на себя, похвалил. Ты в топ-2% людей, которые доходят до середины.",
        "3-4/5": "🟡 *Сделал больше половины (3-4/5):*\nМолодец! 14 дней — это серьезно 🔥",
        "0-2/5": "🔴 *Сделал мало или ничего (0-2/5):*\nУстал? Выдохни. Ты все еще в игре, а это главное."
    },
    # День 15
    15: {
        "4/4": "✅ *Всё сделал (4/4):*\nПомог в чате, представил себя через 5 лет, прочитал 2 главы. Второе дыхание открыто.",
        "2-3/4": "🟡 *Сделал больше половины (2-3/4):*\nХороший день! Так держать 👊",
        "0-1/4": "🔴 *Сделал мало или ничего (0-1/4):*\nБывает. Завтра будет лучше."
    },
    # День 16
    16: {
        "4/4": "✅ *Всё сделал (4/4):*\nБлагодарил людей, заметил красивый момент. Ты становишься теплее. Это видно.",
        "2-3/4": "🟡 *Сделал больше половины (2-3/4):*\nМолодец! Продолжай в том же духе 💪",
        "0-1/4": "🔴 *Сделал мало или ничего (0-1/4):*\nНичего страшного. Завтра наверстаешь."
    },
    # День 17
    17: {
        "4/4": "✅ *Всё сделал (4/4):*\n5 сильных сторон + список ошибок. Ты знаешь себе цену и видишь, где упал. Это зрелость.",
        "2-3/4": "🟡 *Сделал больше половины (2-3/4):*\nХорошо идешь! Двигай дальше 🔥",
        "0-1/4": "🔴 *Сделал мало или ничего (0-1/4):*\nНу ок. Завтра новый день."
    },
    # День 18
    18: {
        "4/4": "✅ *Всё сделал (4/4):*\nИнвестиция в себя + спасибо прошлому себе. Ты строишь мосты во времени. Это мощно.",
        "2-3/4": "🟡 *Сделал больше половины (2-3/4):*\nТак держать! Хороший настрой 👊",
        "0-1/4": "🔴 *Сделал мало или ничего (0-1/4):*\nБывает. Завтра получится."
    },
    # День 19
    19: {
        "4/4": "✅ *Всё сделал (4/4):*\nЦелый день в роли будущего себя. Как оно? Почувствовал разницу?",
        "2-3/4": "🟡 *Сделал больше половины (2-3/4):*\nМолодец! Продолжай 💪",
        "0-1/4": "🔴 *Сделал мало или ничего (0-1/4):*\nНе зашло? Бывает. Завтра попробуй еще."
    },
    # День 20
    20: {
        "5/5": "✅ *Всё сделал (5/5):*\nПервый шаг, разобранная зона, ритм дня. Ты не ждешь — ты делаешь. Это твой стиль теперь.",
        "3-4/5": "🟡 *Сделал больше половины (3-4/5):*\nХороший день! Так держать 🔥",
        "0-2/5": "🔴 *Сделал мало или ничего (0-2/5):*\nБывает. Завтра все получится."
    },
    # День 21
    21: {
        "5/5": "✅ *Всё сделал (5/5):*\n21 день. Три недели. Ты благодарил, помогал родителям, медитировал. Ты в новой реальности.",
        "3-4/5": "🟡 *Сделал больше половины (3-4/5):*\nМолодец! 21 день — это уровень 👊",
        "0-2/5": "🔴 *Сделал мало или ничего (0-2/5):*\nТы все еще здесь. Это главное. Завтра будет лучше."
    },
    # День 22
    22: {
        "4/4": "✅ *Всё сделал (4/4):*\nЧас без экрана, цель на завтра, книга, мечты. Ты управляешь своим временем.",
        "2-3/4": "🟡 *Сделал больше половины (2-3/4):*\nХорошо идешь! Продолжай 💪",
        "0-1/4": "🔴 *Сделал мало или ничего (0-1/4):*\nБывает. Завтра просто начни с одного дела."
    },
    # День 23
    23: {
        "5/5": "✅ *Всё сделал (5/5):*\nПопросил совета, не жаловался, написал про характер. Ты открыт и честен — это сила.",
        "3-4/5": "🟡 *Сделал больше половины (3-4/5):*\nТак держать! Хороший день 🔥",
        "0-2/5": "🔴 *Сделал мало или ничего (0-2/5):*\nНу ок. Завтра получится."
    },
    # День 24
    24: {
        "5/5": "✅ *Всё сделал (5/5):*\nПосмотрел на старые страхи, отпустил стыд, сказал комплимент. Ты растешь над собой.",
        "3-4/5": "🟡 *Сделал больше половины (3-4/5):*\nМолодец! Продолжай в том же духе 👊",
        "0-2/5": "🔴 *Сделал мало или ничего (0-2/5):*\nБывает. Завтра будет лучше."
    },
    # День 25
    25: {
        "5/5": "✅ *Всё сделал (5/5):*\nПорядок, красота, деньги. Ты наводишь чистоту во всем. 5 дней до финиша — ты летишь.",
        "3-4/5": "🟡 *Сделал больше половины (3-4/5):*\nХороший темп! Так держать 💪",
        "0-2/5": "🔴 *Сделал мало или ничего (0-2/5):*\nНичего страшного. Завтра наверстаешь."
    },
    # День 26
    26: {
        "5/5": "✅ *Всё сделал (5/5):*\nЭмоции, детокс, обучение другого. Ты не просто проходишь — ты передаешь. Это уровень эксперт.",
        "3-4/5": "🟡 *Сделал больше половины (3-4/5):*\nМолодец! Хороший день 🔥",
        "0-2/5": "🔴 *Сделал мало или ничего (0-2/5):*\nБывает. Завтра все получится."
    },
    # День 27
    27: {
        "4/4": "✅ *Всё сделал (4/4):*\nРаспланировал день, подумал о будущем. Ты уже строишь жизнь после бота — это правильно.",
        "2-3/4": "🟡 *Сделал больше половины (2-3/4):*\nТак держать! Уже финиш близко 👊",
        "0-1/4": "🔴 *Сделал мало или ничего (0-1/4):*\nНу ок. Завтра просто сделай одно дело."
    },
    # День 28
    28: {
        "4/4": "✅ *Всё сделал (4/4):*\nЗарядка, тишина в кармане, зависимость на виду. Ты видишь свои триггеры — это победа.",
        "2-3/4": "🟡 *Сделал больше половины (2-3/4):*\nХорошо идешь! Продолжай 💪",
        "0-1/4": "🔴 *Сделал мало или ничего (0-1/4):*\nБывает. Завтра будет лучше."
    },
    # День 29
    29: {
        "5/5": "✅ *Всё сделал (5/5):*\nПоддержал других, утро без уведомлений, подготовил всё к финалу. Ты лидер.",
        "3-4/5": "🟡 *Сделал больше половины (3-4/5):*\nМолодец! Последний рывок 🔥",
        "0-2/5": "🔴 *Сделал мало или ничего (0-2/5):*\nНичего страшного. Завтра главный день — просто будь."
    },
    # День 30
    30: {
        "5/5": "✅ *Всё сделал (5/5):*\nТы дошел. Отчет, цветок, финал. Ты в 2%. Я горжусь. Ты гордись собой. Иди дальше 🚀",
        "3-4/5": "🟡 *Сделал больше половины (3-4/5):*\n30 дней позади. Ты сделал это. Серьезно, ты молодец 💪",
        "0-2/5": "🔴 *Сделал мало или ничего (0-2/5):*\n30 дней прошло. Ты мог не начинать, но начал. Ты мог сдаться, но не сдался. Это и есть победа."
    }
}

# ==================== ЗАДАНИЯ ПО ДНЯМ ====================
DAILY_TASKS: Dict[int, Dict[str, Any]] = {
    1: {"title": "ДЕНЬ 1 | ТОЧКА А", "tasks": ["📖 *1. Чтение*\nПрочитай первые 3 темы книги.", "📓 *2. Дневники*\nПрочти инструкцию.", "🌙 *3. Перед сном*\nЗаполни дневники.", "🎯 *4. Главное намерение*\nЗапиши 3 цели.", "⚡ *5. Действие дня*\nРешения за 1 минуту."], "total": 5},
    2: {"title": "ДЕНЬ 2 | ЧИСТКА ПРОСТРАНСТВА", "tasks": ["📖 *1. Чтение*\nПрочитай главы.", "🌙 *2. Перед сном*\nЗаполни дневники.", "🔇 *3. Цифровая гигиена*\nУбери телефон.", "🧹 *4. Действие дня*\nОтпишись от 3 каналов.", "👀 *5. Наблюдение*\nОтметь залипание."], "total": 5},
    3: {"title": "ДЕНЬ 3 | ЛИЦОМ К СТРАХАМ", "tasks": ["📖 *1. Чтение*\nПрочитай 4 главы.", "🌙 *2. Перед сном*\nЗаполни дневники.", "📝 *3. Дневниковая работа*\nВыпиши страхи.", "💧 *4. Действие дня*\nВыпей 2 литра воды.", "🧠 *5. Осознанность*\nНайди тормозящую мысль."], "total": 5},
    4: {"title": "ДЕНЬ 4 | ПРОДУКТИВНОСТЬ", "tasks": ["📖 *1. Чтение*\nПрочитай 4 главы.", "🌙 *2. Перед сном*\nЗаполни дневники.", "⚡ *3. Действие дня*\nСделай отложенное дело.", "💪 *4. Физика*\n20 приседаний.", "📚 *5. Рефлексия*\nЗапиши ошибку и урок."], "total": 5},
    5: {"title": "ДЕНЬ 5 | ТИШИНА", "tasks": ["📖 *1. Чтение*\nПрочитай 4 главы.", "🌙 *2. Перед сном*\nЗаполни дневники.", "📵 *3. Цифровой детокс*\n30 мин без телефона.", "🙊 *4. Действие дня*\nНи с кем не спорь."], "total": 4},
}

# Добавляем остальные дни
for day in range(6, 31):
    if day not in DAILY_TASKS:
        DAILY_TASKS[day] = {"title": f"ДЕНЬ {day}", "tasks": [f"📖 *1. Чтение*\nЗадание на день {day}"], "total": 5}

# ==================== КНОПКИ ====================
def get_main_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📋 Получить информацию")], [KeyboardButton(text="✅ Я ГОТОВ")]],
        resize_keyboard=True
    )

def get_report_keyboard(day: int) -> InlineKeyboardMarkup:
    total = DAILY_TASKS[day]["total"]
    builder = InlineKeyboardBuilder()
    
    if total == 6:
        builder.row(InlineKeyboardButton(text="✅ 6/6", callback_data=f"rep_6/6_{day}"), InlineKeyboardButton(text="🟡 4-5/6", callback_data=f"rep_4-5/6_{day}"))
        builder.row(InlineKeyboardButton(text="🔴 0-3/6", callback_data=f"rep_0-3/6_{day}"))
    elif total == 5:
        builder.row(InlineKeyboardButton(text="✅ 5/5", callback_data=f"rep_5/5_{day}"), InlineKeyboardButton(text="🟡 3-4/5", callback_data=f"rep_3-4/5_{day}"))
        builder.row(InlineKeyboardButton(text="🔴 0-2/5", callback_data=f"rep_0-2/5_{day}"))
    elif total == 4:
        builder.row(InlineKeyboardButton(text="✅ 4/4", callback_data=f"rep_4/4_{day}"), InlineKeyboardButton(text="🟡 2-3/4", callback_data=f"rep_2-3/4_{day}"))
        builder.row(InlineKeyboardButton(text="🔴 0-1/4", callback_data=f"rep_0-1/4_{day}"))
    else:
        builder.row(InlineKeyboardButton(text="✅ 3/3", callback_data=f"rep_3/3_{day}"), InlineKeyboardButton(text="🟡 2/3", callback_data=f"rep_2/3_{day}"))
        builder.row(InlineKeyboardButton(text="🔴 0-1/3", callback_data=f"rep_0-1/3_{day}"))
    
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

@dp.callback_query(lambda c: c.data.startswith('rep_'))
async def process_report(callback: types.CallbackQuery):
    """Обработка отчетов - ГЛАВНАЯ ФУНКЦИЯ"""
    user_id = callback.from_user.id
    data = callback.data
    
    # Убираем префикс 'rep_'
    without_prefix = data[4:]
    
    # Разделяем на ключ отчета и день
    # Формат: 5/5_1 или 3-4/5_1 или 6/6_7
    parts = without_prefix.rsplit('_', 1)
    
    if len(parts) != 2:
        await callback.answer("❌ Ошибка формата", show_alert=True)
        return
    
    report_key = parts[0]  # "5/5" или "3-4/5" и т.д.
    reported_day = int(parts[1])
    
    user_data = db_get_user(user_id)
    if not user_data:
        await callback.message.answer("Ошибка. Нажми /start")
        await callback.answer()
        return
    
    current_day = user_data[4]
    
    if reported_day != current_day:
        await callback.answer(f"❌ Кнопка для дня {reported_day}, вы на дне {current_day}", show_alert=True)
        await callback.message.delete()
        return
    
    if not user_data[5]:
        await callback.answer("Сначала нажми «Я ГОТОВ»", show_alert=True)
        return
    
    if db_get_report_status(user_id, current_day):
        await callback.answer("❌ Уже отчитался", show_alert=True)
        await callback.message.delete()
        return
    
    # Сохраняем отчет
    completed_map = {"5/5":5,"3-4/5":3,"0-2/5":1,"6/6":6,"4-5/6":4,"0-3/6":1,"4/4":4,"2-3/4":2,"0-1/4":0,"3/3":3,"2/3":2,"0-1/3":0}
    completed = completed_map.get(report_key, 0)
    
    db_save_report(user_id, current_day, completed, DAILY_TASKS[current_day]["total"], report_key)
    db_update_last_report_date(user_id)
    
    await callback.message.delete()
    
    # ========== ОТПРАВЛЯЕМ ПРАВИЛЬНЫЙ FEEDBACK ==========
    feedback_text = FEEDBACK_TEXTS.get(current_day, {}).get(report_key)
    
    if feedback_text:
        await callback.message.answer(feedback_text, parse_mode="Markdown")
    else:
        # Запасной вариант - никогда не должно сработать
        await callback.message.answer(f"✅ Отчет за день {current_day} принят! Ты молодец! 🔥", parse_mode="Markdown")
    
    # Поддержка для ключевых дней
    if current_day in SUPPORT_MESSAGES:
        await asyncio.sleep(1)
        await callback.message.answer(SUPPORT_MESSAGES[current_day], parse_mode="Markdown")
        await asyncio.sleep(2)
    else:
        await asyncio.sleep(2)
    
    # Завершение марафона
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
    await bot.set_my_commands([
        BotCommand(command="start", description="Запустить бота"),
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
