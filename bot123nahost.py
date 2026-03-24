"""
TELEGRAM БОТ ДЛЯ 30-ДНЕВНОГО МАРАФОНА
Версия: 3.5 - С ДИАГНОСТИКОЙ
Дата: 2026-03-24
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

MOSCOW_TZ = pytz.timezone('Europe/Moscow')

if TOKEN == "YOUR_BOT_TOKEN_HERE":
    raise ValueError("❌ Токен не найден! Добавьте переменную окружения BOT_TOKEN")

REMINDER_HOUR = 23
REMINDER_MINUTE = 59

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
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
    cur.execute('CREATE INDEX IF NOT EXISTS idx_active_users ON users(is_active, completed_30)')
    
    conn.commit()
    conn.close()
    logger.info("База данных инициализирована")

def db_add_user(user_id: int, username: str, first_name: str):
    with DB_LOCK:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "INSERT OR IGNORE INTO users (user_id, username, first_name, start_date, current_day, has_info_shown) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, username or "", first_name or "", get_moscow_now().isoformat(), 1, 0)
        )
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
        cur.execute(
            "INSERT INTO daily_reports (user_id, day, report_date, tasks_completed, total_tasks, status) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, day, get_moscow_now().isoformat(), completed, total, status)
        )
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
        cur.execute("""
            SELECT user_id, username, first_name, current_day, completed_30, last_report_date 
            FROM users 
            ORDER BY current_day DESC, start_date DESC
        """)
        result = cur.fetchall()
        conn.close()
        return result

def db_reset_user(user_id: int):
    with DB_LOCK:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM daily_reports WHERE user_id = ?", (user_id,))
        cur.execute("""
            UPDATE users 
            SET current_day = 1, 
                last_task_date = NULL, 
                last_report_date = NULL, 
                completed_30 = 0, 
                is_active = 1,
                start_date = ?,
                has_info_shown = 0
            WHERE user_id = ?
        """, (get_moscow_now().isoformat(), user_id))
        conn.commit()
        conn.close()
    logger.info(f"Пользователь {user_id} полностью сброшен")

def db_get_user_reports(user_id: int) -> list:
    with DB_LOCK:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT day, status, report_date, tasks_completed, total_tasks FROM daily_reports WHERE user_id = ? ORDER BY day", (user_id,))
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

def db_get_info_shown(user_id: int) -> bool:
    with DB_LOCK:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT has_info_shown FROM users WHERE user_id = ?", (user_id,))
        result = cur.fetchone()
        conn.close()
        return result[0] == 1 if result else False

# ==================== КОНТЕНТ ====================

START_MESSAGE = """
🌟 *Привет! Это твой личный спутник на ближайшие 30 дней.*

Выполняя систему обязанностей, которую я буду высылать тебе каждый день, ты изменишь свою жизнь на «до» и «после». Главное помнить: я просто бот, а мои создатели — просто люди, и никакого волшебства здесь нет. Всё зависит только от тебя и твоего желания измениться.

Я не просто уверен — я знаю: наступит момент, когда станет очень тяжко. И тогда у тебя будет выбор: либо пройти отбор, не откладывая ни на секунду запланированные действия, либо сдаться. И если ты выберешь второе — попроси свой мозг напомнить тебе, что ты только что вошёл в 98% тех, кто сдаётся и не хочет покорять вершины, а только мечтает о них.

*Ну что, рассказать вкратце, что тебя ждёт? Нажми на кнопку «Получить информацию».*
"""

INFO_MESSAGE = """
📋 *Это 30-дневный марафон, созданный для твоего удобства. Пройдёшь его — станешь другим человеком.*

🔹 *1–6 день* — ты втягиваешься в процесс. Но даже за этот период без особых усилий ты прочитаешь книгу, которая при качественном прочтении и следовании инструкциям нанесёт колоссальный урон тому «Я», который просто мечтает. Научишься вести дневники, которые будут помогать тебе меняться, поддерживать тебя и вести к успеху.

🔹 Дальше ты каждый день выполняешь задания, которые войдут в твой новый распорядок. Ты узнаешь себя лучше, следишь за контролем над собой, учишься не срываться на быстрый дофамин.

❗️ *ИНФОРМАЦИЯ*

Думаю, ты готов. После того как нажмёшь кнопку *«Я ГОТОВ»*, тебе придёт задание на День 1.

Если у тебя сейчас утро или день — начинай действовать прямо сейчас. Да, сначала может быть странно, непонятно и без видимости того, как это поможет. Но ты уже заплатил 😉 Просто начни и доверься.
"""

SUPPORT_MESSAGES = {
    1: "✨ *Первый день позади!*\n\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\nЭто было просто знакомство — с ботом, с дневниками, с новым режимом. Если всё сделал — ты красава. Если что-то пошло не так — не парься, ты только разгоняешься.\n\n*Главное, что ты начал!*\n\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
    7: "🔥 *Первая неделя позади!*\n\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\nТы прочитал книгу, заполнил дневники, сделал кучу мелких, но важных дел. Если где-то проседал — не страшно.\n\n*Главное, что ты still here. Отдохни сегодня, завтра стартуем «45 татуировок». Это будет интересно!*\n\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
    14: "⚡️ *ЭКВАДОР! 14 дней*\n\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\nПоловина пути. Ты завел третий дневник, подвел итоги, посмотрел на себя со стороны. Это уровень.\n\nЕсли сейчас чувствуешь усталость — это норм. Дальше пойдет тяжелее, но и результат будет жестче.\n\n*Ты справляешься!* 👊\n\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
    21: "🚀 *ТРИ НЕДЕЛИ! 21 день*\n\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\nЭто уже не просто эксперимент, это новая реальность. Ты благодарил, помогал, медитировал, смотрел на себя через 5 лет.\n\n*Осталось 9 дней. Не сбавляй темп!*\n\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
    25: "💪 *25 дней! Осталось всего 5*\n\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\nТы разбирал завалы, искал красоту, считал деньги, смотрел страхам в лицо. Сейчас может быть тяжело — это нормально, так и должно быть.\n\n*Дожми. Осталось чуть-чуть!*\n\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
}

FINAL_MESSAGE = """
🎉 *Ну что, друг... 30 дней позади.* 🎉

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Помнишь первый день? Каким ты был, когда нажал «Старт»? Может, неуверенным, может, полным сомнений, может, просто любопытным. А сейчас? Посмотри на себя.

*Ты дошел. Ты сделал это.*

Я просто бот, но я видел, как ты выполнял задания, как заполнял дневники, как иногда, наверное, хотел забить — но не забивал. И это всё ты. Не я, не создатели, не магия. Только ты.

Эти 30 дней были твоим прыжком. Кто-то прыгает и падает, кто-то прыгает и летит.

*Ты полетел.*

Дневник №1 теперь твой личный компас. Записывай туда свои мысли, страхи, победы. А цветок... пусть растет. Как напоминание: ты тоже растешь. Каждый день. Даже когда не замечаешь.

Я отключаюсь, но ты остаешься. Уже другой. Уже сильнее.

Иди дальше. Меняйся. Ошибайся. Вставай. Иди снова.

*Был рад быть рядом. Искренне твой,*
🤖 *Спутник*

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

REMINDER_MESSAGE = """
⚠️ *Ты забыл отчитаться о выполнении задач, надеюсь ты выполнил все!*

*Вот тебе следующие задачи на грядущий день.*
"""

# ==================== ЗАДАНИЯ ПО ДНЯМ ====================
DAILY_TASKS: Dict[int, Dict[str, Any]] = {
    1: {"title": "ДЕНЬ 1 | ТОЧКА А", "tasks": ["📖 *1. Чтение*\nПрочитай первые 3 темы книги. Остановись на теме «Дневники».", "📓 *2. Дневники*\nВнимательно прочти файл с инструкцией «Как пользоваться дневниками». Это ключевой инструмент.\nhttps://disk.yandex.ru/i/m5w3A1NDOdVddg", "🌙 *3. Перед сном*\nЗаполни Дневник №1 и Дневник №2.", "🎯 *4. Главное намерение*\nВ Дневник №1 запиши 3 вещи, которые ты хочешь изменить в себе за этот месяц.", "⚡ *5. Действие дня*\nСегодня все решения принимай за 1 минуту. Что есть на обед, куда пойти, что надеть. Не парься, просто делай выбор."], "total": 5},
    2: {"title": "ДЕНЬ 2 | ЧИСТКА ПРОСТРАНСТВА", "tasks": ["📖 *1. Чтение*\nПрочитай главы про дневники и зацепи тему «Окружение». Остановись на теме «Посторонний шум».", "🌙 *2. Перед сном*\nЗаполни дневники №1 и №2.", "🔇 *3. Цифровая гигиена*\nУбери телефон за 30 минут до сна. Просто положи подальше.", "🧹 *4. Действие дня*\nОтпишись от 3 каналов/пабликов, которые бесят или не несут пользы.", "👀 *5. Наблюдение*\nОбрати внимание, когда сегодня ты ловил себя на «залипании» в телефоне. Просто отметь в уме."], "total": 5},
    3: {"title": "ДЕНЬ 3 | ЛИЦОМ К СТРАХАМ", "tasks": ["📖 *1. Чтение*\nПрочитай 4 главы. Начни с темы «Посторонний шум», закончи на теме «Меня себя».", "🌙 *2. Перед сном*\nЗаполни дневники №1 и №2.", "📝 *3. Дневниковая работа*\nВ Дневник №1 выпиши все страхи, которые мешают тебе принимать быстрые решения.", "💧 *4. Действие дня*\nВыпей сегодня 2 литра чистой воды. Серьёзно, 2 литра.", "🧠 *5. Осознанность*\nНайди одну мысль, которая сегодня тебя тормозила. Запиши её в дневник."], "total": 5},
    4: {"title": "ДЕНЬ 4 | ПРОДУКТИВНОСТЬ", "tasks": ["📖 *1. Чтение*\nПрочитай 4 главы. Начни с темы «Привычки», закончи на теме «Не спорьте».", "🌙 *2. Перед сном*\nЗаполни дневники №1 и №2.", "⚡ *3. Действие дня*\nСделай одно дело, которое давно откладывал (звонок, уборка, запись к врачу, починка вещи). Любой ценой.", "💪 *4. Физика*\nСделай 20 приседаний или отжиманий в любой момент дня.", "📚 *5. Рефлексия*\nЗапиши одну ошибку сегодняшнего дня и один урок из неё в дневник №1."], "total": 5},
    5: {"title": "ДЕНЬ 5 | ТИШИНА", "tasks": ["📖 *1. Чтение*\nПрочитай 4 главы. Начни с темы «Принимай решения быстро», закончи на теме «Трудности».", "🌙 *2. Перед сном*\nЗаполни дневники №1 и №2.", "📵 *3. Цифровой детокс*\nПосле пробуждения полчаса без телефона. Вообще. Умылся, заправил кровать, выпил воды — и только потом телефон.", "🙊 *4. Действие дня*\nСегодня ни с кем не спорь. Даже если хочется — просто промолчи или согласись."], "total": 4},
    6: {"title": "ДЕНЬ 6 | ФИНИШ ПЕРВОЙ КНИГИ", "tasks": ["📖 *1. Чтение*\nПрочитай 4 главы. Начни с темы «Удача», закончи на теме «Думай меньше».", "🌙 *2. Перед сном*\nЗаполни дневники №1 и №2.", "💡 *3. Инсайты*\nВ Дневник №2 выпиши 3 главных инсайта за первые 6 дней.", "🧹 *4. Повторение*\nОтпишись ещё от 3 каналов/пабликов, которые бесят или не несут пользы. Чистота прежде всего.", "💧 *5. Водный баланс*\nВыпей сегодня 2 литра чистой воды.\n\n*Анонс завтра:* ЗАВТРА ВАЖНЫЙ ДЕНЬ. Подведение итогов первой недели и старт новой книги. Приготовься."], "total": 5},
    7: {"title": "ДЕНЬ 7 | ИТОГИ НЕДЕЛИ И СТАРТ НОВОЙ КНИГИ", "tasks": ["📖 *1. Чтение (итоговое по первой книге)*\nПрочитай 3 главы. Начни с темы «Индивидуальность», закончи на теме «Итог».", "🌙 *2. Перед сном*\nЗаполни дневники №1 и №2.", "🔄 *3. Точка изменений*\nЗапиши в Дневник №1: «Что я теперь буду делать иначе?».", "⭐ *4. Визуализация*\nОпиши в 5 предложениях свой идеальный день через год. В Дневник №1 или просто на листик, но сконцентрируйся на этой мысли.", "⚡ *5. Задание на скорость*\nСегодня все решения принимай за 1 минуту. Закрепляем навык.", "📢 *6. ВАЖНО! Новая книга*\nЗавтра стартуем новую книгу — *«45 татуировок личности» (Максим Батырев)*.\nВот файл со ссылками: https://disk.yandex.ru/i/AN2Sk3MtrK7ZpQ. Там есть где читать, где слушать онлайн и артикулы для заказа физической книги. Пока книга едет — читай/слушай онлайн. Определись с форматом сегодня."], "total": 6},
}

# Заполняем остальные дни (8-30) - для краткости оставлю структуру, в полном коде они есть
for day in range(8, 31):
    if day not in DAILY_TASKS:
        DAILY_TASKS[day] = {"title": f"ДЕНЬ {day}", "tasks": ["📖 *1. Чтение*\nПрочитай главу из книги."], "total": 1}

# ==================== ОЦЕНКИ ЗА ДНИ ====================
FEEDBACK_MESSAGES: Dict[int, Dict[str, str]] = {
    1: {"5/5": "✅ *Всё сделал (5/5):*\nОгонь старт! Ты не просто нажал кнопку, ты реально начал. Первый день — всегда самый непонятный, но ты справился. Горжусь 🔥", "3-4/5": "🟡 *Сделал больше половины (3-4/5):*\nНеплохо! Двигай дальше 👊", "0-2/5": "🔴 *Сделал мало или ничего (0-2/5):*\nБывает. Завтра будет лучше."},
    2: {"5/5": "✅ *Всё сделал (5/5):*\nЧистка пространства зашла. 3 канала минус, телефон подальше — ты уже чище, чем вчера. Красава!", "3-4/5": "🟡 *Сделал больше половины (3-4/5):*\nХорошо идешь! Так держать 💪", "0-2/5": "🔴 *Сделал мало или ничего (0-2/5):*\nНичего страшного. Завтра наверстаешь."},
    3: {"5/5": "✅ *Всё сделал (5/5):*\n2 литра воды + страхи на бумаге. Ты серьезный человек. Страхи теперь не в голове, а в дневнике — так и должно быть.", "3-4/5": "🟡 *Сделал больше половины (3-4/5):*\nМолодец! Продолжай в том же духе 🔥", "0-2/5": "🔴 *Сделал мало или ничего (0-2/5):*\nНу ок. Завтра новый день."},
    4: {"5/5": "✅ *Всё сделал (5/5):*\nОдно отложенное дело сделано. Ты кайфанул? Я кайфанул. Привычки начинаются с таких дней.", "3-4/5": "🟡 *Сделал больше половины (3-4/5):*\nТак держать! С каждым днем все лучше 👊", "0-2/5": "🔴 *Сделал мало или ничего (0-2/5):*\nНе зашло сегодня. Завтра получится."},
    5: {"5/5": "✅ *Всё сделал (5/5):*\nПолчаса утра без телефона — это уровень. Целый день без споров — вообще джедайство. Ты растешь.", "3-4/5": "🟡 *Сделал больше половины (3-4/5):*\nХороший день! Продолжай в том же духе 💪", "0-2/5": "🔴 *Сделал мало или ничего (0-2/5):*\nБывает. Завтра просто сделай чуть больше."},
    6: {"5/5": "✅ *Всё сделал (5/5):*\nПервая книга позади. 6 дней, 3 инсайта, минус 6 каналов, 4 литра воды. Ты в отрыве 🚀", "3-4/5": "🟡 *Сделал больше половины (3-4/5):*\nМолодец! Хороший темп 🔥", "0-2/5": "🔴 *Сделал мало или ничего (0-2/5):*\nНе фортануло? Завтра все получится."},
    7: {"6/6": "✅ *Всё сделал (6/6):*\nПервая неделя. Итоги, визуализация, подготовка к новой книге. Ты не просто читал — ты менялся. Отдохни сегодня.", "4-5/6": "🟡 *Сделал больше половины (4-5/6):*\nТак держать! Неделя позади — это серьезно 💪", "0-3/6": "🔴 *Сделал мало или ничего (0-3/6):*\nНеделя была длинной. Отдохни и завтра с новыми силами."},
}

# Добавляем для остальных дней
for day in range(8, 31):
    FEEDBACK_MESSAGES[day] = {
        "5/5": f"✅ *Всё сделал (5/5):*\nОтлично! День {day} выполнен! Продолжай в том же духе! 🚀",
        "3-4/5": f"🟡 *Сделал больше половины (3-4/5):*\nХорошо! День {day} почти позади. Завтра будет лучше! 💪",
        "0-2/5": f"🔴 *Сделал мало или ничего (0-2/5):*\nБывает. Завтра новый день! 🌟"
    }

# ==================== КНОПКИ ====================
def get_main_keyboard() -> ReplyKeyboardMarkup:
    kb = [[KeyboardButton(text="📋 Получить информацию")], [KeyboardButton(text="✅ Я ГОТОВ")]]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

def get_report_keyboard(day: int) -> InlineKeyboardMarkup:
    total = DAILY_TASKS[day]["total"]
    builder = InlineKeyboardBuilder()
    
    if total == 6:
        builder.row(InlineKeyboardButton(text="✅ Выполнил 6/6", callback_data=f"report_6/6_{day}"), InlineKeyboardButton(text="🟡 Выполнил 4-5/6", callback_data=f"report_4-5/6_{day}"))
        builder.row(InlineKeyboardButton(text="🔴 Выполнил 0-3/6", callback_data=f"report_0-3/6_{day}"))
    elif total == 5:
        builder.row(InlineKeyboardButton(text="✅ Выполнил 5/5", callback_data=f"report_5/5_{day}"), InlineKeyboardButton(text="🟡 Выполнил 3-4/5", callback_data=f"report_3-4/5_{day}"))
        builder.row(InlineKeyboardButton(text="🔴 Выполнил 0-2/5", callback_data=f"report_0-2/5_{day}"))
    elif total == 4:
        builder.row(InlineKeyboardButton(text="✅ Выполнил 4/4", callback_data=f"report_4/4_{day}"), InlineKeyboardButton(text="🟡 Выполнил 2-3/4", callback_data=f"report_2-3/4_{day}"))
        builder.row(InlineKeyboardButton(text="🔴 Выполнил 0-1/4", callback_data=f"report_0-1/4_{day}"))
    elif total == 3:
        builder.row(InlineKeyboardButton(text="✅ Выполнил 3/3", callback_data=f"report_3/3_{day}"), InlineKeyboardButton(text="🟡 Выполнил 2/3", callback_data=f"report_2/3_{day}"))
        builder.row(InlineKeyboardButton(text="🔴 Выполнил 0-1/3", callback_data=f"report_0-1/3_{day}"))
    
    return builder.as_markup()

# ==================== ИНИЦИАЛИЗАЦИЯ БОТА ====================
bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode="Markdown"))
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

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
    
    if completed_30 == 1:
        await message.answer("🎉 *Ты уже прошел марафон!*\n\nСпасибо, что был со мной эти 30 дней!\n\nЕсли хочешь пройти марафон заново, администратор может сбросить твой прогресс.", parse_mode="Markdown", reply_markup=types.ReplyKeyboardRemove())
        return
    
    if current_day > 1:
        has_report = db_get_report_status(user.id, current_day)
        status = "✅ Ты уже отчитался за сегодня. Готов к следующему дню?" if has_report else "📝 У тебя есть задания на сегодня. Выполни их и отправь отчет."
        await message.answer(f"👋 *С возвращением!*\n\nТы на *{current_day} дне* из 30.\n\n{status}\n\nНажми *«✅ Я ГОТОВ»*, чтобы продолжить.", parse_mode="Markdown", reply_markup=get_main_keyboard())
    else:
        await message.answer(START_MESSAGE, parse_mode="Markdown", reply_markup=get_main_keyboard())

@dp.message(Command("my_status"))
async def my_status_command(message: types.Message):
    user_id = message.from_user.id
    user_data = db_get_user(user_id)
    
    if not user_data:
        await message.answer("❌ Вы не зарегистрированы. Нажмите /start")
        return
    
    current_day = user_data[4]
    completed_30 = user_data[8]
    reports = db_get_user_reports(user_id)
    
    status_text = f"📊 *Ваш статус в марафоне*\n\n📅 *День:* {current_day} из 30\n✅ *Завершил марафон:* {'Да' if completed_30 == 1 else 'Нет'}\n📝 *Всего отчетов:* {len(reports)}\n"
    if reports:
        last_day, last_status, _, _, _ = reports[-1]
        status_text += f"📋 *Последний отчет:* день {last_day}, статус {last_status}\n"
    
    await message.answer(status_text, parse_mode="Markdown")

@dp.message(F.text == "📋 Получить информацию")
async def get_info(message: types.Message):
    db_set_info_shown(message.from_user.id)
    await message.answer(INFO_MESSAGE, parse_mode="Markdown", reply_markup=get_main_keyboard())

@dp.message(F.text == "✅ Я ГОТОВ")
async def i_am_ready(message: types.Message):
    user_id = message.from_user.id
    user_data = db_get_user(user_id)
    
    if not user_data:
        await message.answer("Произошла ошибка. Нажми /start")
        return
    
    current_day = user_data[4]
    completed_30 = user_data[8]
    
    if completed_30 == 1:
        await message.answer("🎉 *Ты уже завершил марафон!*\n\nСпасибо, что был со мной эти 30 дней!", parse_mode="Markdown", reply_markup=types.ReplyKeyboardRemove())
        return
    
    has_report = db_get_report_status(user_id, current_day)
    
    if has_report:
        next_day = current_day + 1
        if next_day <= 30:
            db_update_user_day(user_id, next_day)
            day_tasks = DAILY_TASKS[next_day]
            tasks_text = f"*{day_tasks['title']}*\n\n" + "\n\n".join(day_tasks["tasks"])
            tasks_text += f"\n\n*Как выполнишь задачи, нажми одну из кнопок:*"
            await message.answer(tasks_text, parse_mode="Markdown", reply_markup=get_report_keyboard(next_day))
            db_update_last_task_date(user_id)
        else:
            db_complete_marathon(user_id)
            await message.answer(FINAL_MESSAGE, parse_mode="Markdown")
            await message.answer("🎉 *Марафон завершен!*\n\nСпасибо, что был со мной эти 30 дней!", parse_mode="Markdown", reply_markup=types.ReplyKeyboardRemove())
    else:
        day_tasks = DAILY_TASKS[current_day]
        tasks_text = f"*{day_tasks['title']}*\n\n" + "\n\n".join(day_tasks["tasks"])
        tasks_text += f"\n\n*Как выполнишь задачи, нажми одну из кнопок:*"
        await message.answer(tasks_text, parse_mode="Markdown", reply_markup=get_report_keyboard(current_day))
        db_update_last_task_date(user_id)

@dp.callback_query(lambda c: c.data.startswith('report_'))
async def process_report(callback: types.CallbackQuery):
    """Обработка отчетов с диагностикой"""
    user_id = callback.from_user.id
    callback_data = callback.data
    
    # ДИАГНОСТИКА - отправляем админу
    await bot.send_message(ADMIN_ID, f"🔍 *ПОЛУЧЕН CALLBACK*\n\n📝 Данные: `{callback_data}`\n👤 От: {user_id}", parse_mode="Markdown")
    
    # Разбираем
    without_prefix = callback_data.replace('report_', '')
    parts = without_prefix.rsplit('_', 1)
    
    if len(parts) != 2:
        await callback.answer("❌ Ошибка формата отчета", show_alert=True)
        return
    
    report_value = parts[0]
    reported_day = int(parts[1])
    
    await bot.send_message(ADMIN_ID, f"📊 *РАЗБОР*\n\nreport_value: `{report_value}`\nreported_day: {reported_day}", parse_mode="Markdown")
    
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
    
    if not user_data[5]:
        await callback.answer("Сначала нажми «✅ Я ГОТОВ», чтобы получить задачи!", show_alert=True)
        return
    
    if db_get_report_status(user_id, current_day):
        await callback.answer("❌ Ты уже отчитался за этот день!", show_alert=True)
        await callback.message.delete()
        return
    
    # Сохраняем
    completed_map = {"5/5": 5, "3-4/5": 3, "0-2/5": 1, "6/6": 6, "4-5/6": 4, "0-3/6": 1, "4/4": 4, "2-3/4": 2, "0-1/4": 0, "3/3": 3, "2/3": 2, "0-1/3": 0}
    completed = completed_map.get(report_value, 0)
    db_save_report(user_id, current_day, completed, DAILY_TASKS[current_day]["total"], report_value)
    db_update_last_report_date(user_id)
    
    await callback.message.delete()
    
    # ОТПРАВЛЯЕМ FEEDBACK
    day_feedback = FEEDBACK_MESSAGES.get(current_day, {})
    
    await bot.send_message(ADMIN_ID, f"📚 *ПОИСК FEEDBACK*\n\nДень {current_day}\nКлюч: `{report_value}`\nДоступные ключи: {list(day_feedback.keys())}\nСовпадение: {report_value in day_feedback}", parse_mode="Markdown")
    
    feedback_text = None
    
    # Пробуем найти
    if report_value in day_feedback:
        feedback_text = day_feedback[report_value]
        await bot.send_message(ADMIN_ID, f"✅ *Найдено точное совпадение!*", parse_mode="Markdown")
    else:
        # Ищем по вхождению
        for key, text in day_feedback.items():
            if key in report_value or report_value in key:
                feedback_text = text
                await bot.send_message(ADMIN_ID, f"🔄 *Найдено по вхождению!* Ключ: `{key}`", parse_mode="Markdown")
                break
    
    if feedback_text:
        await callback.message.answer(feedback_text, parse_mode="Markdown")
    else:
        await bot.send_message(ADMIN_ID, f"❌ *FEEDBACK НЕ НАЙДЕН!*", parse_mode="Markdown")
        await callback.message.answer(f"✅ Спасибо за отчет!", parse_mode="Markdown")
    
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
        await callback.message.answer("🎉 *Марафон завершен!*", parse_mode="Markdown", reply_markup=types.ReplyKeyboardRemove())
        await callback.answer()
        return
    
    # Следующий день
    next_day = current_day + 1
    db_update_user_day(user_id, next_day)
    
    day_tasks = DAILY_TASKS[next_day]
    tasks_text = f"*{day_tasks['title']}*\n\n" + "\n\n".join(day_tasks["tasks"])
    tasks_text += f"\n\n*Как выполнишь задачи, нажми одну из кнопок:*"
    
    await callback.message.answer(tasks_text, parse_mode="Markdown", reply_markup=get_report_keyboard(next_day))
    db_update_last_task_date(user_id)
    await callback.answer()

# ==================== АДМИН-КОМАНДЫ (сокращенно) ====================

@dp.message(Command("admin"))
async def admin_command(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("❌ У вас нет доступа.")
        return
    await message.answer("📊 *Панель администратора*\n\nКоманды:\n/admin_info ID\n/admin_reset ID\n/admin_sync ID\n/admin_diagnose ID", parse_mode="Markdown")

@dp.message(Command("admin_reset"))
async def admin_reset_user(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    args = message.text.split()
    if len(args) < 2:
        await message.answer("❌ Использование: /admin_reset user_id")
        return
    try:
        user_id = int(args[1])
        db_reset_user(user_id)
        await message.answer(f"✅ Пользователь {user_id} сброшен")
        await bot.send_message(user_id, "🔄 Администратор сбросил ваш прогресс! Нажмите /start")
    except:
        await message.answer("❌ Ошибка")

@dp.message(Command("admin_sync"))
async def admin_sync_user(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    args = message.text.split()
    if len(args) < 2:
        await message.answer("❌ Использование: /admin_sync user_id")
        return
    try:
        user_id = int(args[1])
        reports = db_get_user_reports(user_id)
        has_day30 = any(r[0] == 30 for r in reports)
        correct_completed = 1 if has_day30 else 0
        
        if reports:
            max_day = max(r[0] for r in reports)
            correct_day = max_day + 1 if max_day < 30 else 30
        else:
            correct_day = 1
        
        with DB_LOCK:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("UPDATE users SET completed_30 = ?, current_day = ? WHERE user_id = ?", (correct_completed, correct_day, user_id))
            conn.commit()
            conn.close()
        
        await message.answer(f"✅ Синхронизировано: день={correct_day}, completed={correct_completed}")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")

@dp.message(Command("admin_diagnose"))
async def admin_diagnose_user(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    args = message.text.split()
    if len(args) < 2:
        await message.answer("❌ Использование: /admin_diagnose user_id")
        return
    try:
        user_id = int(args[1])
        user = db_get_user(user_id)
        if not user:
            await message.answer(f"❌ Пользователь {user_id} не найден")
            return
        reports = db_get_user_reports(user_id)
        await message.answer(f"📊 *Диагностика*\n\nДень: {user[4]}\nЗавершил: {user[8]}\nОтчетов: {len(reports)}\nПоследний отчет: {reports[-1] if reports else 'нет'}", parse_mode="Markdown")
    except:
        await message.answer("❌ Ошибка")

# ==================== ФОНОВЫЕ ЗАДАЧИ ====================
async def check_reminders():
    last_check_date = None
    while True:
        try:
            now = get_moscow_now()
            current_date = now.date()
            if now.hour == REMINDER_HOUR and now.minute >= REMINDER_MINUTE:
                if last_check_date != current_date:
                    last_check_date = current_date
                    users = db_get_all_active_users()
                    for user_id, current_day in users:
                        try:
                            if not db_get_report_status(user_id, current_day):
                                await bot.send_message(user_id, REMINDER_MESSAGE, parse_mode="Markdown")
                                next_day = current_day + 1
                                if next_day <= 30:
                                    day_tasks = DAILY_TASKS[next_day]
                                    tasks_text = f"*{day_tasks['title']}*\n\n" + "\n\n".join(day_tasks["tasks"])
                                    tasks_text += f"\n\n*Как выполнишь задачи, нажми одну из кнопок:*"
                                    await bot.send_message(user_id, tasks_text, parse_mode="Markdown", reply_markup=get_report_keyboard(next_day))
                                    db_update_user_day(user_id, next_day)
                                    db_update_last_task_date(user_id)
                        except Exception as e:
                            logger.error(f"Ошибка: {e}")
            await asyncio.sleep(30)
        except Exception as e:
            logger.error(f"Ошибка: {e}")
            await asyncio.sleep(60)

# ==================== ЗАПУСК ====================
async def set_commands():
    commands = [BotCommand(command="start", description="Запустить бота"), BotCommand(command="my_status", description="Мой статус")]
    await bot.set_my_commands(commands)

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
