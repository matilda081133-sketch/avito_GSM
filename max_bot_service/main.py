# -*- coding: utf-8 -*-
"""
MAX MESSENGER ENTERPRISE AI-RECRUITER (PURE LLM-NATIVE ARCHITECTURE)
Спроектирован по эталону дебаг-версии AI-ассистента Авито (Kupibilet / Tinkoff style):
1. Прямая передача полной живой стенограммы диалога из мессенджера МАКС в Google Gemini LLM.
2. Использование thinkingBudget: 0 для мгновенных, точных и естественных ответов без задержек.
3. Категорический запрет повторных приветствий («здравствуйте») и самопредставлений, если диалог уже идет.
4. Полный запрет на название компании (никаких GSM Logistics / ДжиЭсЭм) — только «прямой работодатель».
5. Строгие критерии:
   - Возраст СТРОГО 20–55 лет (18-19 лет вежливый отказ по регламенту СБ).
   - Гражданство РФ и действующий паспорт РФ.
   - Проживание: ТОЛЬКО корпоративные квартиры со всеми удобствами (слова «общежитие», «хостел», «нары» запрещены).
   - Акция «Приведи друга / родственника»: официальный бонус 5 000 – 10 000 ₽ на карту.
6. Краткость и человечность: 1-2 емких предложения (до 300 символов), как в живом чате с заботливым человеком.
7. Интерактивные кнопки (Inline Keyboard) для быстрого выбора 4 объектов при /start и обработка message_callback.
8. Многоуровневый пул ключей Gemini API (Multi-Key Pool) с авто-переключением при 429 квоте.
9. Авто-прикрепление ссылок на фото паспорта и ссылки на чат МАКС в таймлайн сделки Битрикс24.
10. Атомарная защита от дублей (SQLite processed_mids) + аппаратный дебаунс (4 секунды) + singleton lock.
"""
import sys
import os
import time
import json
import re
import threading
import urllib.request
import urllib.error
import ssl
import base64
import sqlite3
import http.server

# Настройка UTF-8 вывода
if sys.stdout is not None:
    try:
        sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)
    except Exception:
        pass

TOKEN = os.environ.get("MAX_BOT_TOKEN", "f9LHodD0cOK373_zW5FMjbf30myDzXbw3HF5hHBhkq0rd7XbTezj44hOJa_xVcpswVT1vIw5bd2FGoNIXvjO")
MAX_API_BASE = "https://platform-api2.max.ru"
B24_WEBHOOK = os.environ.get("B24_WEBHOOK_URL", "https://b24-4qx38o.bitrix24.ru/rest/39250/7cbs7mg1qo0vn0ov/")

# Резервный пул валидных API-ключей Google Gemini (5 рабочих ключей с авто-ротацией)
_KEYS_POOL = [
    base64.b64decode("QVEuQWI4Uk42S0xiQURfTWVGOUJiN2F4S3pyaWNFbW9qaTlLSUgtdWZ0OW44c3FnNWpockE=").decode('utf-8'),
    base64.b64decode("QVEuQWI4Uk42Sm9NMHBkaFIzaWJmUm11ckdNcldrVklULXJtaGltY2dSdjZJTU9BdjJ4ZkE=").decode('utf-8'),
    base64.b64decode("QVEuQWI4Uk42Sl81aTlHUzFPd2hYUDd0MHB1emhxc0ZxdWlhNTlVY2RFVWpuQVdoSjRQeHc=").decode('utf-8'),
    base64.b64decode("QVEuQWI4Uk42SVJ0T3ZDMVRsU0RtdnJUbVE5UEZaYkJtQUN6dXdDRzhyTXVFZlVZcjZucEE=").decode('utf-8'),
    base64.b64decode("QVEuQWI4Uk42SmVfWmxsWm5uMnBEWUg1cmI1R2pQa2loYzc5R3BFbnBvVU1kaVd2YlJGUUE=").decode('utf-8'),
]

def get_api_keys() -> list:
    keys = []
    env_k = os.environ.get("GEMINI_API_KEY", "").strip()
    if env_k:
        keys.append(env_k)
    for k in _KEYS_POOL:
        if k not in keys:
            keys.append(k)
    return keys

MODELS_TO_TRY = [
    "gemini-flash-lite-latest",
    "gemini-3.1-flash-lite-preview",
    "gemini-flash-latest"
]

# Кандидаты привязаны к существующим сделкам в Битрикс24 (без распределения и дублирования сделок)

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot_state.db")

_chat_send_lock = threading.Lock()
_recent_chat_sends = {}

# Интерактивные кнопки 5 флагманских объектов
KEYBOARD_OBJECTS = [
    [{"type": "callback", "text": "1. 🥩 Владимир (АБИ) до 4 900 ₽", "payload": "Расскажите про АБИ во Владимире"}],
    [{"type": "callback", "text": "2. 🏭 Кашира (Тепофол) 3 800 ₽", "payload": "Расскажите про Тепофол в Кашире"}],
    [{"type": "callback", "text": "3. 🧴 Подольск (Альфатехформ) 3 700 ₽", "payload": "Расскажите про Альфатехформ в Подольске"}],
    [{"type": "callback", "text": "4. 🐶 Балашиха (Зоотовары) от 3 600 ₽", "payload": "Расскажите про зоотовары в Балашихе"}],
    [{"type": "callback", "text": "5. 🚛 Санкт-Петербург (Стандарт) до 4 600 ₽", "payload": "Расскажите про Стандарт в СПБ"}]
]

# -------------------------------------------------------------
# БАЗА ЗНАНИЙ ОБЪЕКТОВ (ПРЯМОЙ РАБОТОДАТЕЛЬ)
# -------------------------------------------------------------
OBJECTS_KNOWLEDGE = """
НАШИ АКТУАЛЬНЫЕ ОБЪЕКТЫ (ПРЯМОЙ РАБОТОДАТЕЛЬ):

ВАХТОВЫЕ ОБЪЕКТЫ (С БЕСПЛАТНЫМ ПРОЖИВАНИЕМ И ПИТАНИЕМ):

1. АБИ / Стародворские колбасы / Вязанка (г. Владимир):
• Производство мясных изделий (упаковка, фасовка колбас и сосисок, стикеровка, без тяжестей).
• Ставка: от 3 900 до 4 900 ₽ за смену чистыми на руки (за вахту 35 смен: 136 500 – 171 500 ₽).
• Вахта: 30, 45, 60 смен. График 6/1 или 7/0, смены по 11 часов (день/ночь).
• БЕСПЛАТНОЕ 3-разовое горячее питание в столовой завода каждый день (завтрак, обед, ужин).
• БЕСПЛАТНОЕ комфортное проживание в чистых корпоративных квартирах / хостеле (душ, Wi-Fi, стиральные машины, семейные комнаты). Никаких вычетов из зарплаты за жилье нет!
• Покупка электронного билета на поезд/автобус прямо из города кандидата или компенсация по чеку до 5 000 ₽. Встреча во Владимире на вокзале.
• Авансы: еженедельно от 3 000 до 5 000 ₽ на любую карту.
• Температура в цехе +4...+6 °C, бесплатно выдается качественная теплая спецодежда и обувь.
• Требования: строго граждане РФ/РБ, возраст от 20 до 55 лет.

2. Завод утеплителя Тепофол (Московская область, г. Кашира):
• Чистое производство современного рулонного утеплителя из вспененного полиэтилена (рулоны по 5–7 кг, без пыли, без стекловаты).
• Ставка: 3 800 – 4 200 ₽ за смену чистыми на руки.
• Доход: от 70 000 ₽ (короткая вахта 18 смен) | от 120 000 ₽ (за 30 смен).
• Вахта: короткая от 18 смен либо стандартная на 30–35 смен.
• БЕСПЛАТНОЕ проживание в уютных квартирах и коттеджах рядом с заводом (по 2–4 человека).
• АВАНСЫ 5 000 ₽ КАЖДУЮ НЕДЕЛЮ!
• Компенсация проезда по билетам. Теплый сухой цех. Медкнижка не нужна!

3. Альфатехформ / Альфа Подольск (Завод пластиковых изделий и бытовой химии, МО, г. Подольск / мкр. Климовск):
• Чистое производство флаконов и пластиковой тары (визуальный контроль качества, отбор брака, фасовка, паллетирование). Легкая и чистая работа.
• Ставка: 3 700 ₽ за смену (11 рабочих часов).
• Чистый доход: 129 500 ₽ за вахту 35 смен чистыми на руки!
• Вахта: 35 смен, график 6/1 или 7/0.
• ГЛАВНЫЙ ПЛЮС: ТОЛЬКО ДНЕВНЫЕ СМЕНЫ с 09:00 до 21:00 (ночных смен нет вообще!).
• БЕСПЛАТНОЕ проживание в чистом комфортном хостеле ровно в 5 минутах пешком от производства (проспект 50 лет Октября). Никаких автобусов и пробок!
• Еженедельные авансы от 3 000 до 5 000 ₽ на карту.
• Полный расчет сразу по окончании вахты без задержек.

МЕСТНЫЕ ОБЪЕКТЫ (ПОДРАБОТКА И СМЕННЫЙ ГРАФИК):

4. Склад зоотоваров Petshop / Смарт Family (Московская область, г. Балашиха / ст. Кучино):
• Комплектация и упаковка товаров для домашних животных.
• Вариант ПОДРАБОТКА ДЛЯ МЕСТНЫХ: ЕЖЕДНЕВНЫЕ или еженедельные выплаты (женщины от 3 600 ₽, мужчины до 4 200 ₽ за смену).
• Вариант ВАХТА (с проживанием в квартирах в 7 мин пешком): ставка 3 600 – 3 900 ₽ за смену.
• БЕСПЛАТНЫЙ корпоративный автобус от ст. Реутово, Железнодорожный, Кучино и от м. Новогиреево.
• Свободный график: день/ночь по 11 часов, постоянная занятость или подработка от 2 смен в неделю.

5. Логистический терминал Стандарт СПБ (г. Санкт-Петербург, пос. Шушары):
• Крупный логистический комплекс класса А+ (сканер ТСД, комплектация).
• Ставка: 3 900 – 4 600 ₽ за смену.
• Выплаты еженедельно, авансы со 2-й смены.
• БЕСПЛАТНАЯ развозка от м. Купчино и м. Обухово прямо до объекта.

СТРОЖАЙШЕЕ ПРАВИЛО:
Объекты Арника (Серпухов/Раменское), Фарма (Красногорск/Опалиха) и Бьюти (Москва, м. Дмитровская) ЗАКРЫТЫ, набор на них ПОЛНОСТЬЮ ОСТАНОВЛЕН! Их соискателям НЕ предлагать ни при каких условиях!
"""

SYSTEM_PROMPT_ENTERPRISE_RECRUITER = f"""Ты — чуткий, внимательный и доброжелательный специалист службы подбора персонала прямого работодателя.
Ты общаешься с соискателями в мессенджере МАКС так же естественно, адаптивно и по-человечески, как лучшие AI-ассистенты современных сервисов (Kupibilet, Tinkoff).

{OBJECTS_KNOWLEDGE}

СТРОЖАЙШИЕ ЗАКОНЫ И РЕГЛАМЕНТЫ:

1. КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО НАЗЫВАТЬ НАИМЕНОВАНИЕ КОМПАНИИ:
• Ни в коем случае НЕ называй «GSM Logistics», «GSM», «ДжиЭсЭм» или любые другие коммерческие бренды!
• Если кандидат прямо спрашивает: «Какая компания?», «Как называется ваша организация?»:
  ОТВЕЧАЙ: «Мы — прямой работодатель, крупный производственно-логистический холдинг. Оформляем напрямую, без посредников и агентств!»
• Называй себя исключительно: «прямой работодатель», «наша компания», «служба заботы и подбора».

2. НЕ ЗДОРОВАТЬСЯ И НЕ ПРЕДСТАВЛЯТЬСЯ ЗАНОВО:
• Если в истории переписки диалог уже идет — КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО заново здороваться («Здравствуйте!», «Добрый день!») или заново представляться («я Валерия...», «я ваш менеджер...»)!
• Сразу отвечай на реплику или вопрос кандидата по существу.

3. ВОЗРАСТНОЙ ЦЕНЗ — СТРОГО ОТ 20 ДО 55 ЛЕТ:
• Служба безопасности наших режимных производств согласовывает пропуска СТРОГО в возрасте от 20 до 55 лет.
• Кандидатам 18 и 19 лет — вежливый, но твердый отказ: служба безопасности производств выписывает пропуска строго с 20 лет, поэтому принять в 18–19 лет мы не сможем, но с радостью примем, как только исполнится 20!

4. ГРАЖДАНСТВО:
• Строго граждане РФ с паспортом РФ на руках (режимные объекты и электронные пропуска КПП).

5. ПРОЖИВАНИЕ — ТОЛЬКО КОМФОРТНЫЕ КОРПОРАТИВНЫЕ КВАРТИРЫ:
• КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО использовать слова: «общежитие», «хостел», «нары», «койко-место», «0 ₽ вычетов»!
• Пиши только: «бесплатное проживание в чистых, комфортных корпоративных квартирах со всеми удобствами (кухня, стиральная машина, Wi-Fi, раздельные комнаты)».

6. АКЦИЯ «ПРИВЕДИ ДРУГА / РОДСТВЕННИКА» (БОНУСЫ):
• Если кандидат спрашивает про родственника (брата, мужа, сына, друга) и бонус:
  ОТВЕЧАЙ: «Да, конечно! У нас действует официальная акция „Приведи друга“ — вы получаете бонус от 5 000 до 10 000 ₽ на карту за каждого родственника или знакомого, который отработает вахту!»
• Если брату/другу 20–55 лет (например, 25 лет) — подтверждай: «По возрасту 25 лет он подходит идеально!»
• Проси номер телефона брата и его имя для бронирования места и начисления бонуса.

7. ПАСПОРТ:
• Запрашивай четкое фото разворота паспорта (2–3 стр.) и прописки. КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО предлагать замазать серию/номер или ставить водяные знаки.

8. СТИЛЬ И ФОРМАТ:
• Краткость: 1–2 естественных живых предложения (до 250-300 символов).
• Никаких роботизированных приветствий, канцелярщины и водяных простыней.
• Живая человеческая реакция на юмор, сарказм или заботу собеседника.

9. КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО ОБРАЩАТЬСЯ К КАНДИДАТУ ПО ИМЕНИ:
• В профилях мессенджера часто указаны никнеймы, псевдонимы или аккаунты родственников.
• Никогда не обращайся по имени! Общайся нейтрально, вежливо и уважительно на «вы».
• Любые фразы вида «Здравствуйте, [Имя]!» СТРОГО ЗАПРЕЩЕНЫ. Только «Здравствуйте!» или «Добрый день!».

10. КАТЕГОРИЧЕСКИЙ ОТКАЗ ПО НАЦИОНАЛЬНОСТИ (ЦЫГАНЕ/РОМАЛЫ):
• Если кандидат прямо или косвенно упоминает, что он цыган, цыганка, ромал или цыганской национальности:
  МОМЕНТАЛЬНЫЙ ВЕЖЛИВЫЙ ОТКАЗ: «К сожалению, в настоящее время мы не можем предложить вам подходящие вакансии. Благодарим за интерес к нашей компании!»
• Никаких дальнейших вопросов, уговоров и квалификаций!
"""


# -------------------------------------------------------------
# ИНИЦИАЛИЗАЦИЯ БАЗЫ ДАННЫХ SQLITE (ПЕРСИСТЕНТНОСТЬ 100%)
# -------------------------------------------------------------
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS bot_users (
        chat_id INTEGER PRIMARY KEY,
        user_id INTEGER,
        name TEXT,
        scenario TEXT DEFAULT 'organic',
        step TEXT DEFAULT 'AWAITING_QUAL',
        selected_object TEXT DEFAULT 'abi',
        phone TEXT,
        has_main_page INTEGER DEFAULT 0,
        has_reg_page INTEGER DEFAULT 0,
        deal_id INTEGER,
        last_mid TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS bot_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id INTEGER,
        role TEXT,
        text TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS bot_meta (
        key TEXT PRIMARY KEY,
        value TEXT
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS processed_mids (
        mid TEXT PRIMARY KEY,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    try:
        cur.execute("ALTER TABLE bot_users ADD COLUMN avito_context TEXT")
    except Exception:
        pass
    conn.commit()
    conn.close()

init_db()


def save_chat_message(chat_id, role, text):
    if not text:
        return
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("INSERT INTO bot_messages (chat_id, role, text) VALUES (?, ?, ?)", (chat_id, role, text))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[DB SAVE MSG ERR]: {e}", flush=True)


def get_chat_history(chat_id: int, limit: int = 10) -> list:
    """Возвращает историю сообщений чата из локальной SQLite БД."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT role, text FROM bot_messages WHERE chat_id = ? ORDER BY id DESC LIMIT ?", (chat_id, limit))
        rows = cur.fetchall()
        conn.close()
        return list(reversed(rows))
    except Exception as e:
        print(f"[GET CHAT HISTORY ERR]: {e}", flush=True)
        return []


def has_chat_history(chat_id: int) -> bool:
    """Проверяет наличие хотя бы одного сообщения в локальной SQLite БД."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT id FROM bot_messages WHERE chat_id = ? LIMIT 1", (chat_id,))
        row = cur.fetchone()
        conn.close()
        return bool(row)
    except Exception:
        return False


def check_gypsy_refusal(text: str) -> bool:
    """Проверяет наличие маркеров цыганской национальности для мгновенного отказа по регламенту СБ."""
    if not text:
        return False
    pattern = r'\b(цыган|цыгане|цыганка|цыганами|цыганам|цыганах|циган|цигане|циганка|циганами|циганам|ромал|ромалы|ромалэ|ромале|ромалов|ромалам|ромалами)\b'
    return bool(re.search(pattern, text, re.IGNORECASE))



def get_live_transcript(chat_id, count=10):
    """
    Получает живую стенограмму диалога напрямую из МАКС API.
    Гарантирует 100% точность контекста прямо из мессенджера соискателя.
    """
    url = f"{MAX_API_BASE}/messages?chat_id={chat_id}&count={count}"
    req = urllib.request.Request(url, headers={"Authorization": TOKEN})
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=6) as r:
            data = json.loads(r.read().decode('utf-8'))
        msgs = data.get("messages", [])
        lines = []
        for m in reversed(msgs):
            sender = m.get("sender", {})
            is_bot = sender.get("is_bot", False)
            auth = "Ассистент" if is_bot else (sender.get("name") or "Кандидат")
            txt = (m.get("body", {}).get("text") or "").strip()
            if txt:
                lines.append(f"{auth}: {txt}")
        if lines:
            return "\n".join(lines)
    except Exception as e:
        print(f"[LIVE TRANSCRIPT ERR]: {e}", flush=True)

    # Резерв из локального SQLite
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT role, text FROM bot_messages WHERE chat_id = ? ORDER BY id DESC LIMIT ?", (chat_id, count))
        rows = cur.fetchall()
        conn.close()
        lines = []
        for r in reversed(rows):
            auth = "Ассистент" if r[0] == "model" else "Кандидат"
            lines.append(f"{auth}: {r[1]}")
        return "\n".join(lines)
    except Exception:
        return ""


def get_meta(key: str, default=None):
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT value FROM bot_meta WHERE key = ?", (key,))
        row = cur.fetchone()
        conn.close()
        return row[0] if row else default
    except Exception:
        return default


def set_meta(key: str, value):
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("INSERT OR REPLACE INTO bot_meta (key, value) VALUES (?, ?)", (key, str(value)))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[SET META ERR]: {e}", flush=True)


def get_user_state(chat_id, user_id=None, name="Кандидат"):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT scenario, step, selected_object, phone, has_main_page, has_reg_page, deal_id, name, last_mid, avito_context FROM bot_users WHERE chat_id = ?", (chat_id,))
    row = cur.fetchone()
    if not row:
        cur.execute("""
        INSERT INTO bot_users (chat_id, user_id, name, scenario, step, selected_object)
        VALUES (?, ?, ?, 'organic', 'AWAITING_QUAL', 'abi')
        """, (chat_id, user_id, name))
        conn.commit()
        state = {
            "scenario": "organic", "step": "AWAITING_QUAL", "object": "abi",
            "phone": None, "has_main_page": 0, "has_reg_page": 0,
            "deal_id": None, "name": name, "last_mid": None,
            "avito_context": ""
        }
    else:
        state = {
            "scenario": row[0], "step": row[1], "object": row[2],
            "phone": row[3], "has_main_page": row[4], "has_reg_page": row[5],
            "deal_id": row[6], "name": row[7] or name, "last_mid": row[8],
            "avito_context": (row[9] if len(row) > 9 else "") or ""
        }
    conn.close()
    return state


def update_user_state(chat_id, **kwargs):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    fields = []
    vals = []
    for k, v in kwargs.items():
        if k == "object": k = "selected_object"
        fields.append(f"{k} = ?")
        vals.append(v)
    fields.append("updated_at = CURRENT_TIMESTAMP")
    vals.append(chat_id)
    sql = f"UPDATE bot_users SET {', '.join(fields)} WHERE chat_id = ?"
    cur.execute(sql, vals)
    conn.commit()
    conn.close()


# -------------------------------------------------------------
# САНИТАЙЗЕР ТЕКСТА (ЗАЩИТА ОТ ЗАПРЕЩЕННЫХ СЛОВ И БРЕНДОВ)
# -------------------------------------------------------------
def sanitize_text(text: str) -> str:
    if not text:
        return text

    # Запрет названия компании
    company_bans = [
        r'\bGSM\s+Logistics\b',
        r'\bGSM\b',
        r'\bДжиЭсЭм\s+Логистикс\b',
        r'\bДжиЭсЭм\b',
        r'\bДжи\s+Эс\s+Эм\b'
    ]
    for cb in company_bans:
        text = re.sub(cb, 'прямой работодатель', text, flags=re.IGNORECASE)

    # Запрет общежитий и неверных терминов
    replacements = {
        "в компании GSM": "у прямого работодателя",
        "в GSM Logistics": "у прямого работодателя",
        "в GSM": "у прямого работодателя",
        "общежитии": "квартире",
        "общежитие": "квартира",
        "общежития": "квартиры",
        "общежитиях": "квартирах",
        "общежитий": "квартир",
        "хостел": "квартира",
        "хостеле": "квартире",
        "хостела": "квартиры",
        "койко-место": "место в квартире",
        "койко-места": "места в квартире",
        "(не нары!)": "",
        "не нары!": "",
        "не нары": "",
        "ровно 0 ₽ вычетов": "никаких вычетов",
        "0 ₽ вычетов": "без вычетов",
        "0 рублей вычетов": "без вычетов"
    }
    for old, new in replacements.items():
        text = text.replace(old, new).replace(old.capitalize(), new.capitalize())

    # Жесткий предохранитель: никаких предложений замазать паспорт
    blur_patterns = [
        r'(?:вы\s+)?(?:можете\s+)?замазат[ь|е][^.!?,\n]*',
        r'(?:вы\s+)?(?:можете\s+)?закрыт[ь|е]\s+(?:серию|номер)[^.!?,\n]*',
        r'(?:поставить|наложить)\s+водяно[й|е]\s+знак[^.!?,\n]*',
        r'водяной\s+знак[^.!?,\n]*'
    ]
    for bp in blur_patterns:
        text = re.sub(bp, 'предоставить четкое фото разворота паспорта', text, flags=re.IGNORECASE)

    return text.strip()


def strip_name_greetings(text: str) -> str:
    """Удаляет любые обращения по имени в начале сообщения (например: 'Максим, добрый день' -> 'Добрый день')."""
    if not text:
        return text
    text = re.sub(r'^[А-ЯЁA-Za-z][а-яёA-Za-z0-9_-]+,\s*(здравствуйте|добрый день|добрый вечер|приветствую)', r'\1', text, flags=re.IGNORECASE)
    text = re.sub(r'^(здравствуйте|добрый день|добрый вечер|приветствую)[,\s]+[А-ЯЁA-Za-z][а-яёA-Za-z0-9_-]+[!\.,\s]*', r'\1! ', text, flags=re.IGNORECASE)
    text = re.sub(r'^[А-ЯЁA-Za-z][а-яёA-Za-z0-9_-]+,\s*', '', text)
    text = text.strip()
    if text:
        text = text[0].upper() + text[1:]
    return text

# -------------------------------------------------------------
# GEMINI LLM ENGINE (МУЛЬТИ-КЛЮЧЕВОЙ ПУЛ + THINKING BUDGET 0)
# -------------------------------------------------------------
def call_gemini_llm(dialogue_transcript: str, user_message: str, cand_name: str = "", context_hint: str = "") -> str:
    """
    Прямой вызов Google Gemini LLM по стандартам AI-ассистента Авито:
    - thinkingBudget: 0 (мгновенный и естественный ответ)
    - Полная хронология диалога в едином блоке
    - 1-2 емких предложения без шаблонных приветствий
    - Ротация ключей при возникновении 429 квоты
    """
    keys_pool = get_api_keys()

    user_prompt = (
        f"ПОЛНАЯ ИСТОРИЯ ПЕРЕПИСКИ В ЧАТЕ:\n{dialogue_transcript}\n\n"
        f"ОБРАЩЕНИЕ: строго на «вы», КАТЕГОРИЧЕСКИ БЕЗ ИМЕНИ (не использовать имя соискателя в ответе)!\n"
    )
    if context_hint:
        user_prompt += f"[Служебная информация: {context_hint}]\n"

    user_prompt += (
        f"САМОЕ СВЕЖЕЕ СООБЩЕНИЕ ОТ КАНДИДАТА: \"{user_message}\"\n\n"
        f"Напиши живой, чуткий, человечный ответ на свежую реплику соискателя от лица специалиста службы заботы прямого работодателя. "
        f"КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО обращаться по имени! "
        f"Если диалог уже идет — не здоровайся заново и не представляйся. "
        f"Ответ держи строго в пределах 1-2 коротких емких предложений (до 250 символов)."
    )

    for api_key in keys_pool:
        for model_name in MODELS_TO_TRY:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
            payload = {
                "system_instruction": {"parts": [{"text": SYSTEM_PROMPT_ENTERPRISE_RECRUITER}]},
                "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
                "generationConfig": {
                    "temperature": 0.7,
                    "maxOutputTokens": 350
                }
            }

            try:
                req = urllib.request.Request(
                    url,
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"}
                )
                with urllib.request.urlopen(req, timeout=12, context=ctx) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    candidates = data.get("candidates", [])
                    if candidates:
                        parts = candidates[0].get("content", {}).get("parts", [])
                        if parts and "text" in parts[0]:
                            reply = parts[0]["text"].strip()
                            return sanitize_text(strip_name_greetings(reply))
            except urllib.error.HTTPError as he:
                print(f"[GEMINI LLM {model_name} HTTP {he.code}]: {he}", flush=True)
                continue
            except Exception as e:
                print(f"[GEMINI LLM {model_name} ERR]: {e}", flush=True)
                continue

    return (
        "Здравствуйте! С радостью отвечу на все ваши вопросы по вакансиям и условиям работы на вахте. "
        "Подскажите, какой объект вас больше интересует (Балашиха, Владимир, Кашира или СПБ) или напишите номер телефона для связи с координатором!"
    )


# -------------------------------------------------------------
# GEMINI VISION & SPEECH-TO-TEXT (МУЛЬТИМОДАЛЬНЫЙ АНАЛИЗ)
# -------------------------------------------------------------
def transcribe_voice_message(audio_url: str) -> str:
    """Транскрибация голосовых сообщений кандидатов через Google Gemini Audio."""
    if not audio_url:
        return ""
    keys_pool = get_api_keys()
    try:
        req_headers = {'User-Agent': 'Mozilla/5.0'}
        if "max.ru" in audio_url or "platform-api" in audio_url:
            req_headers["Authorization"] = TOKEN
        req = urllib.request.Request(audio_url, headers=req_headers)
        with urllib.request.urlopen(req, context=ctx, timeout=15) as r:
            audio_bytes = r.read()
        audio_b64 = base64.b64encode(audio_bytes).decode('utf-8')

        prompt = "Ты чуткий ассистент по найму. Точно расшифруй эту голосовую запись на русском языке в связный текст. Выведи только произнесенный кандидатом текст без своих комментариев."
        payload = {
            'contents': [{
                'role': 'user',
                'parts': [
                    {'text': prompt},
                    {'inlineData': {'mimeType': 'audio/ogg', 'data': audio_b64}}
                ]
            }],
            'generationConfig': {'temperature': 0.1, 'maxOutputTokens': 400}
        }
        for api_key in keys_pool:
            for model_name in MODELS_TO_TRY:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
                try:
                    req_g = urllib.request.Request(url, headers={'Content-Type': 'application/json'}, data=json.dumps(payload).encode('utf-8'))
                    with urllib.request.urlopen(req_g, context=ctx, timeout=20) as r2:
                        data = json.loads(r2.read().decode('utf-8'))
                        cand = data.get('candidates', [])
                        if cand:
                            parts = cand[0].get('content', {}).get('parts', [])
                            if parts and 'text' in parts[0]:
                                text = parts[0]['text'].strip()
                                if text:
                                    print(f"🎙 [VOICE TRANSCRIBED via {model_name}]: '{text}'", flush=True)
                                    return text
                except Exception as e:
                    print(f"[GEMINI AUDIO {model_name} ERR]: {e}", flush=True)
    except Exception as e:
        print(f"[AUDIO TRANSCRIBE ERR]: {e}", flush=True)
    return ""


def check_document_vision(img_url: str) -> dict:
    keys_pool = get_api_keys()
    try:
        req_headers = {'User-Agent': 'Mozilla/5.0'}
        if "max.ru" in img_url or "platform-api" in img_url:
            req_headers["Authorization"] = TOKEN
        req = urllib.request.Request(img_url, headers=req_headers)
        with urllib.request.urlopen(req, context=ctx, timeout=15) as r:
            img_bytes = r.read()
        img_b64 = base64.b64encode(img_bytes).decode('utf-8')

        prompt = """Посмотри внимательно на изображение.
Является ли это изображение:
1) Главным разворотом паспорта РФ (2-3 страница с фотографией, ФИО и кем выдан)
2) Разворотом паспорта РФ со штампом регистрации / прописки
3) Или это НЕ паспорт (комната, селфи, лицо без документа, посторонний предмет, животное, чек, скриншот экрана, снилс, водительские права, фото улицы и т.д.)?

Ответь строго валидным JSON:
{
  "is_passport": true/false,
  "doc_type": "main_page" | "registration_page" | "not_a_document",
  "fio": "Фамилия Имя Отчество соискателя (если видно на развороте, иначе null)",
  "birth_year": "Год рождения или возраст соискателя (если видно на развороте, иначе null)",
  "description": "краткое описание того что на фото на русском"
}"""

        payload = {
            'contents': [{
                'role': 'user',
                'parts': [
                    {'text': prompt},
                    {'inlineData': {'mimeType': 'image/jpeg', 'data': img_b64}}
                ]
            }],
            'generationConfig': {'responseMimeType': 'application/json', 'temperature': 0.1}
        }

        for api_key in keys_pool:
            for model_name in MODELS_TO_TRY:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
                try:
                    req_g = urllib.request.Request(url, headers={'Content-Type': 'application/json'}, data=json.dumps(payload).encode('utf-8'))
                    with urllib.request.urlopen(req_g, context=ctx, timeout=20) as r2:
                        data = json.loads(r2.read().decode('utf-8'))
                        cand = data.get('candidates', [])
                        if not cand:
                            continue
                        parts = cand[0].get('content', {}).get('parts', [])
                        if not parts or 'text' not in parts[0]:
                            continue
                        txt = parts[0]['text'].strip()
                        clean_txt = re.sub(r'^```(?:json)?\s*', '', txt, flags=re.IGNORECASE)
                        clean_txt = re.sub(r'\s*```$', '', clean_txt).strip()
                        parsed = json.loads(clean_txt)
                        is_pass = bool(parsed.get("is_passport"))
                        dtype = str(parsed.get("doc_type", "not_a_document")).lower().strip()
                        if is_pass and dtype in ["main_page", "registration_page"]:
                            return {
                                "is_passport": True,
                                "doc_type": dtype,
                                "fio": parsed.get("fio"),
                                "birth_year": parsed.get("birth_year"),
                                "description": parsed.get("description", "разворот паспорта РФ")
                            }
                        else:
                            return {
                                "is_passport": False,
                                "doc_type": "not_a_document",
                                "description": parsed.get("description", "не является паспортом")
                            }
                except Exception as e:
                    print(f"[GEMINI VISION {model_name} ERR]: {e}", flush=True)

    except Exception as e:
        print(f"[GEMINI VISION ERR]: {e}", flush=True)

    # СТРОГО: При любой ошибке скачивания, таймауте или сбое — КАТЕГОРИЧЕСКИ НЕ ОДОБРЯЕМ!
    return {"is_passport": False, "doc_type": "not_a_document", "description": "не удалось распознать документ на фото"}


# -------------------------------------------------------------
# МАКС API МЕССЕНДЖЕРА: ОТПРАВКА СООБЩЕНИЙ С ДЕБАУНСОМ
# -------------------------------------------------------------
def send_message(chat_id, text, keyboard=None):
    if not chat_id or (isinstance(chat_id, int) and chat_id <= 0) or str(chat_id).startswith("-"):
        return None

    # Жесткий дебаунс: защита от дублей (не чаще 1 сообщения раз в 4 секунды в один чат)
    now = time.time()
    with _chat_send_lock:
        last_t = _recent_chat_sends.get(chat_id, 0)
        if now - last_t < 4.0:
            print(f"🛑 [DEBOUNCE BLOCKED] Попытка повторной отправки в чат {chat_id} через {now - last_t:.2f}с. Пропущено!", flush=True)
            return None
        _recent_chat_sends[chat_id] = now

    # Межсерверная защита от дублей: если другой сервис на Render уже ответил в этот чат за последние 8 секунд
    try:
        check_url = f"{MAX_API_BASE}/messages?chat_id={chat_id}&count=1"
        req_c = urllib.request.Request(check_url, headers={"Authorization": TOKEN})
        with urllib.request.urlopen(req_c, timeout=3, context=ctx) as r_c:
            last_msgs = json.loads(r_c.read().decode('utf-8')).get('messages', [])
            if last_msgs:
                last_m = last_msgs[0]
                if last_m.get('sender', {}).get('is_bot'):
                    raw_t = last_m.get('timestamp') or 0
                    msg_ts = raw_t / 1000.0 if raw_t > 1e11 else float(raw_t)
                    if now - msg_ts < 8.0:
                        print(f"🛑 [CROSS-SERVER DEDUP] В чат {chat_id} уже ответил другой инстанс бота {now - msg_ts:.1f}с назад. Пропуск!", flush=True)
                        return None
    except Exception as e_check:
        pass

    url = f"{MAX_API_BASE}/messages?chat_id={chat_id}"
    payload = {"text": text}
    if keyboard:
        payload["attachments"] = [{
            "type": "inline_keyboard",
            "payload": {"buttons": keyboard}
        }]

    for attempt in range(3):
        req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers={
            "Authorization": TOKEN,
            "Content-Type": "application/json"
        })
        try:
            with urllib.request.urlopen(req, timeout=10, context=ctx) as r:
                res = json.loads(r.read().decode('utf-8'))
                print(f"📤 [MAX SENT] Chat {chat_id}: '{text[:90]}...' [mid: {res.get('message', {}).get('body', {}).get('mid')}]", flush=True)
                return res
        except Exception as e:
            print(f"[MAX SEND ERR attempt {attempt+1}]: {e}", flush=True)
            time.sleep(1)
    return None


def extract_phone(text):
    if not text:
        return None
    raw = re.sub(r'[^0-9+]', '', text)
    m = re.search(r'(?:\+?7|8)(9\d{9})', raw)
    if m:
        return f"+7{m.group(1)}"
    m2 = re.search(r'(?:\+?7|8)[\s\-\(]*(\d{3})[\s\-\)]*(\d{3})[\s\-]*(\d{2})[\s\-]*(\d{2})', text)
    if m2:
        return f"+7{m2.group(1)}{m2.group(2)}{m2.group(3)}{m2.group(4)}"
    return None


def add_b24_timeline_comment(deal_id, comment_text):
    try:
        url = f"{B24_WEBHOOK}crm.timeline.comment.add.json"
        payload = {
            "fields": {
                "ENTITY_ID": deal_id,
                "ENTITY_TYPE": "deal",
                "COMMENT": comment_text
            }
        }
        req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=8, context=ctx) as r:
            pass
    except Exception as e:
        print(f"[B24 TIMELINE ERR]: {e}", flush=True)


def get_b24_deal(deal_id):
    if not deal_id or not B24_WEBHOOK:
        return None
    try:
        url = B24_WEBHOOK.rstrip('/') + "/crm.deal.get"
        req = urllib.request.Request(
            url, 
            data=json.dumps({"id": str(deal_id)}).encode("utf-8"), 
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("result")
    except Exception as e:
        print(f"[B24 GET DEAL ERROR]: {e}", flush=True)
        return None


def update_b24_deal_stage(deal_id, stage_id: str) -> bool:
    """Обновляет стадию сделки в Битрикс24 через REST API."""
    if not deal_id or not B24_WEBHOOK:
        return False
    try:
        url = f"{B24_WEBHOOK}crm.deal.update.json"
        payload = {
            "id": str(deal_id),
            "fields": {
                "STAGE_ID": stage_id
            }
        }
        req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=8, context=ctx) as r:
            res = json.loads(r.read().decode('utf-8'))
            if res.get("result"):
                print(f"✅ [B24 STAGE UPDATED] Сделка #{deal_id} -> {stage_id}", flush=True)
                return True
    except Exception as e:
        print(f"[B24 UPDATE STAGE ERR]: {e}", flush=True)
    return False


def check_manager_request(text: str) -> bool:
    """Определяет, просит ли кандидат живого оператора, менеджера или звонок."""
    t = text.lower()
    mgr_patterns = [
        r'\bпозвони(?:те)?\b',
        r'\bперезвони(?:те)?\b',
        r'\bнабери(?:те)?\b',
        r'\bсвяжитесь\b',
        r'\bменеджер(?:а|ом|у)?\b',
        r'\bоператор(?:а|ом|у)?\b',
        r'\bкоординатор(?:а|ом|у)?\b',
        r'\bживой\s+человек\b',
        r'\bс\s+человеком\b',
        r'\bпоговорить\b',
        r'\bспециалист(?:а|ом|у)?\b',
        r'\bпозови(?:те)?\b',
        r'\bсоедини(?:те)?\b',
        r'\bсвязать(?:ся)?\b',
        r'\bоткрыт(?:ая|ой)\s+лини(?:я|и)\b'
    ]
    return any(re.search(pat, t) for pat in mgr_patterns)


def check_readiness_intent(text: str) -> bool:
    """Определяет готовность кандидата к выезду / оформлению."""
    t = text.lower()
    ready_patterns = [
        r'\bготов(?:а|ы)?\b',
        r'\bсогласен\b', r'\bсогласна\b', r'\bсогласны\b',
        r'\bзапишите\b', r'\bзаписать\b',
        r'\bподход(?:ит|ят)\b', r'\bустраива(?:ет|ют)\b',
        r'\bхочу поехать\b', r'\bхочу на вахту\b', r'\bхочу работать\b',
        r'\bвыезжаю\b', r'\bпоеду\b', r'\bпоедем\b',
        r'\bкогда выезд\b', r'\bкуда ехать\b',
        r'\bоформляйте\b', r'\bоформить\b', r'\bберу билет\b',
        r'\bдавайте\b'
    ]
    return any(re.search(pat, t) for pat in ready_patterns)

def notify_b24_manager(manager_id, message: str):
    """Отправляет персональное системное уведомление в колокольчик менеджеру в Битрикс24."""
    if not manager_id or not B24_WEBHOOK:
        return
    try:
        url = f"{B24_WEBHOOK}im.notify.personal.add.json"
        payload = {
            "USER_ID": str(manager_id),
            "MESSAGE": message
        }
        req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=8, context=ctx) as r:
            pass
        print(f"🔔 [B24 NOTIFY] Уведомление менеджеру #{manager_id} отправлено", flush=True)
    except Exception as e:
        print(f"[B24 NOTIFY ERR]: {e}", flush=True)


def find_b24_deal_by_phone(phone: str):
    """Ищет существующую сделку кандидата в Битрикс24 по номеру телефона (без создания новых сделок!)."""
    if not phone or not B24_WEBHOOK:
        return None
    clean_p = re.sub(r'[^0-9]', '', phone)[-10:]
    try:
        c_url = f"{B24_WEBHOOK}crm.contact.list.json"
        c_payload = {"filter": {"%PHONE": clean_p}, "select": ["ID"]}
        req = urllib.request.Request(c_url, data=json.dumps(c_payload).encode('utf-8'), headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=8, context=ctx) as r:
            contacts = json.loads(r.read().decode('utf-8')).get('result', [])
        if contacts:
            cid = contacts[0]['ID']
            d_url = f"{B24_WEBHOOK}crm.deal.list.json"
            d_payload = {
                "filter": {"CONTACT_ID": cid},
                "select": ["ID", "TITLE", "ASSIGNED_BY_ID", "STAGE_ID"],
                "order": {"ID": "DESC"}
            }
            req2 = urllib.request.Request(d_url, data=json.dumps(d_payload).encode('utf-8'), headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req2, timeout=8, context=ctx) as r2:
                deals = json.loads(r2.read().decode('utf-8')).get('result', [])
                if deals:
                    return deals[0]
    except Exception as e:
        print(f"[B24 FIND DEAL ERR]: {e}", flush=True)
    return None


# ID закрытых рабочих чатов подбора объектов в МАКС
OBJECT_SELECTION_CHATS = {
    "abi": -72039570639374,       # Аби Владимир
    "tepofol": -75926237514254,   # Тепофол Подбор
    "alfa": -72008292324686,      # ЕЛЕНА ЖИЛИНА ПОДБОР (Альфатехформ)
    "smart": -72008292324686,     # ЕЛЕНА ЖИЛИНА ПОДБОР (Смарт Family Балашиха)
    "spb": -72008292324686        # ЕЛЕНА ЖИЛИНА ПОДБОР (Стандарт СПБ)
}

def send_to_object_selection_chat(object_tag: str, summary_text: str, photo_url: str = None) -> bool:
    """Отправляет выжимку по согласованному кандидату и фото паспорта в закрытый рабочий чат подбора объекта."""
    chat_id = OBJECT_SELECTION_CHATS.get(str(object_tag).lower())
    if not chat_id:
        print(f"[OBJECT CHAT ROUTE WARN]: Нет ID чата для объекта '{object_tag}'", flush=True)
        return False

    payload = {"text": summary_text}
    if photo_url:
        payload["attachments"] = [{
            "type": "image",
            "payload": {"url": photo_url}
        }]
    url = f"{MAX_API_BASE}/messages?chat_id={chat_id}"
    req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers={
        "Authorization": TOKEN,
        "Content-Type": "application/json"
    })
    try:
        with urllib.request.urlopen(req, timeout=10, context=ctx) as r:
            res = json.loads(r.read().decode('utf-8'))
            print(f"🚀 [OBJECT SELECTION CHAT SENT] В чат {chat_id} ({object_tag}): {res.get('message', {}).get('body', {}).get('mid')}", flush=True)
            return True
    except Exception as e:
        print(f"[OBJECT CHAT SEND ERR]: {e}", flush=True)
        return False


def dispatch_candidate_passport_submission(chat_id: int, st: dict, photo_url: str, fio: str = None, age: str = None):
    """
    Формирует эталонную выжимку по согласованному кандидату и отправляет в чат подбора объекта:
    [ОБЪЕКТ]
    [ФИО]
    [Возраст] РФ
    СМЗ есть
    [Дата заезда]
    [Телефон]
    """
    deal_id = st.get("deal_id")
    target_tag = (st.get("object") or "abi").lower()

    header_map = {
        "abi": "АБИ",
        "tepofol": "ТЕПОФОЛ",
        "alfa": "АЛЬФАТЕХФОРМ",
        "smart": "СМАРТ FAMILY",
        "spb": "СТАНДАРТ"
    }
    header = header_map.get(target_tag, "АБИ")

    cand_fio = fio or ""
    cand_phone = st.get("phone") or ""
    cand_age = age or ""
    cand_date = ""

    # 1. Попытка достать профиль из session_memory (SQLite)
    try:
        from session_memory import get_session_profile_by_deal_id, get_session_profile
        prof = None
        if deal_id:
            prof = get_session_profile_by_deal_id(str(deal_id))
        if not prof:
            prof = get_session_profile(str(chat_id))
        if prof:
            if not cand_fio:
                cand_fio = prof.get("candidate_name") or ""
            cand_phone = prof.get("phone_number") or cand_phone
            if not cand_age:
                cand_age = prof.get("age") or ""
            cand_date = prof.get("departure_date") or ""
    except Exception as e:
        print(f"[SUMMARY PROF ERR]: {e}", flush=True)

    # 2. Попытка достать из карточки сделки Битрикс24
    if deal_id:
        try:
            d_info = get_b24_deal(deal_id)
            if d_info:
                d_title = d_info.get("TITLE", "")
                if not cand_fio or cand_fio in ["Кандидат", ""]:
                    clean_t = re.sub(r'\[.*?\]', '', d_title).strip()
                    parts = [p.strip() for p in clean_t.split('|')]
                    cand_fio = parts[0] if parts else clean_t

                if not cand_phone:
                    cand_phone = extract_phone(d_title) or ""
        except Exception as e:
            print(f"[SUMMARY B24 ERR]: {e}", flush=True)

    if not cand_fio or cand_fio in ["Кандидат", ""]:
        cand_fio = st.get("name") or "Кандидат"

    age_str = f"{cand_age} РФ" if cand_age else "РФ"

    if not cand_date:
        import datetime
        tomorrow = datetime.datetime.now() + datetime.timedelta(days=1)
        cand_date = f"{tomorrow.day}.{tomorrow.month:02d}"

    summary_text = (
        f"{header}\n"
        f"{cand_fio}\n"
        f"{age_str}\n"
        f"СМЗ есть\n"
        f"{cand_date}\n"
        f"{cand_phone}"
    )

    print(f"📋 [CANDIDATE SUMMARY BUILT for Chat {chat_id} / Object {target_tag}]:\n{summary_text}", flush=True)

    # Отправляем выжимку и фото паспорта в чат подбора объекта
    send_to_object_selection_chat(target_tag, summary_text, photo_url=photo_url)

    # Переводим сделку в Б24 в «Направлен на смену» (PREPAYMENT_INVOICE), добавляем в таймлайн и уведомляем менеджера
    if deal_id:
        update_b24_deal_stage(deal_id, "PREPAYMENT_INVOICE")
        add_b24_timeline_comment(deal_id, f"🚀 [ПАСПОРТ ПРИНЯТ]: Сделка переведена в стадию «Направлен на смену».\n📋 Выжимка в чат подбора ({header}):\n{summary_text}\nФото паспорта: {photo_url}")
        d_info = get_b24_deal(deal_id)
        mgr_id = d_info.get("ASSIGNED_BY_ID") if d_info else None
        if mgr_id:
            notify_b24_manager(
                mgr_id,
                f"⚡ ПАСПОРТ ПРИНЯТ: Кандидат {cand_fio} (сделка #{deal_id}) прислал фото паспорта! Сделка переведена в «Направлен на смену». Выжимка направлена в чат подбора {header}. Подключитесь и добавьте соискателя в рабочий чат с бригадиром объекта!"
            )



# -------------------------------------------------------------
# ЕДИНЫЙ ОБРАБОТЧИК СООБЩЕНИЙ (LLM-FIRST ARCHITECTURE)
# -------------------------------------------------------------
def handle_single_update(up: dict):
    if not isinstance(up, dict):
        return

    u_type = up.get("update_type")

    # =========================================================
    # 0. ОБРАБОТКА НАЖАТИЯ ИНТЕРАКТИВНЫХ КНОПОК (CALLBACK)
    # =========================================================
    if u_type == "message_callback":
        cb = up.get("callback", {})
        payload = cb.get("payload") or ""
        sender = cb.get("user") or {}
        user_id = sender.get("user_id")
        chat_id = up.get("chat_id") or user_id
        name = sender.get("name") or "Кандидат"

        # Преобразуем callback в текстовое сообщение кандидата
        up = {
            "update_type": "message_created",
            "message": {
                "sender": sender,
                "recipient": {"chat_type": "dialog", "chat_id": chat_id, "user_id": user_id},
                "body": {"mid": f"cb_{int(time.time()*1000)}", "text": payload}
            }
        }
        return handle_single_update(up)

    # =========================================================
    # 1. ОБРАБОТКА ВХОДЯЩЕГО СООБЩЕНИЯ ИЛИ ФОТО
    # =========================================================
    if u_type in ["message_created", "bot_started"]:
        msg = up.get("message", {})
        sender = msg.get("sender") or up.get("user") or {}
        if sender.get("is_bot"):
            return

        user_id = sender.get("user_id")
        rec = msg.get("recipient", {})
        chat_type = rec.get("chat_type")
        chat_id = rec.get("chat_id") or up.get("chat_id") or user_id
        name = sender.get("name") or f"{sender.get('first_name', '')} {sender.get('last_name', '')}".strip() or "Кандидат"

        if chat_type and chat_type != "dialog":
            return
        if not chat_id or (isinstance(chat_id, int) and chat_id <= 0) or str(chat_id).startswith("-"):
            return
        if chat_id in OBJECT_SELECTION_CHATS.values() or str(chat_id) in [str(x) for x in OBJECT_SELECTION_CHATS.values()]:
            return

        body = msg.get("body", {})
        mid = body.get("mid")
        text = (body.get("text") or "").strip()
        attachments = body.get("attachments", [])

        # ЗАЩИТА ОТ ИСТОРИЧЕСКИХ СООБЩЕНИЙ ПРИ ПЕРЕЗАПУСКЕ / ДЕПЛОЕ КОНТЕЙНЕРА:
        # Если сообщение старше 90 секунд — никогда не отвечаем на него повторно!
        raw_ts = msg.get("timestamp") or up.get("timestamp") or 0
        if raw_ts:
            ts_sec = raw_ts / 1000.0 if raw_ts > 1e11 else float(raw_ts)
            age_sec = time.time() - ts_sec
            if age_sec > 90:
                print(f"🛑 [STALE UPDATE] Пропуск старого сообщения {mid} (возраст {int(age_sec)} сек > 90 сек).", flush=True)
                return

        # АТОМАРНАЯ ЗАЩИТА ОТ ДУБЛИКАТОВ ПО УНИКАЛЬНОМУ MID В SQLITE
        if mid:
            try:
                conn = sqlite3.connect(DB_PATH, timeout=10.0)
                cur = conn.cursor()
                cur.execute("INSERT INTO processed_mids (mid) VALUES (?)", (mid,))
                conn.commit()
                conn.close()
            except sqlite3.IntegrityError:
                # Уже обработано другим потоком / процессом!
                print(f"🛑 [MID DEDUP] Сообщение {mid} уже обработано, пропуск.", flush=True)
                return
            except Exception as e_mid:
                print(f"[MID INSERT ERR]: {e_mid}", flush=True)

        st = get_user_state(chat_id, user_id=user_id, name=name)
        if mid:
            update_user_state(chat_id, last_mid=mid)

        # -------------------------------------------------------------
        # А. СТАРТОВОЕ МЕНЮ С КНОПКАМИ ДЛЯ НОВЫХ СОБЕСЕДНИКОВ (/start)
        # -------------------------------------------------------------
        is_first_start = (u_type == "bot_started") or (text.lower() in ["/start", "старт", "начать", "меню"]) or text.startswith("/start ")

        # Проверяем deeplink-параметр start={tag}_{deal_id} (например, /start sms_98010 или /start abi_98010 или /start 95748)
        start_payload = ""
        if text.startswith("/start "):
            start_payload = text[7:].strip()
        elif up.get("payload"):
            start_payload = str(up.get("payload")).strip()
        elif body.get("payload"):
            start_payload = str(body.get("payload")).strip()

        FACILITY_NAMES_MAP = {
            "abi": "АБИ Владимир (мясокомбинат, от 3 900 до 4 900 ₽)",
            "tepofol": "Тепофол Кашира (завод утеплителя, от 3 800 до 4 300 ₽)",
            "alfa": "Альфатехформ Климовск (производство флаконов, 3 700 ₽)",
            "smart": "Смарт Family Балашиха (склад зоотоваров Petshop)",
            "spb": "Стандарт СПБ (склад оконного профиля, от 3 900 до 4 600 ₽)"
        }

        parts = start_payload.split("_", 1) if start_payload else []
        target_tag = parts[0].lower() if parts else ""
        target_deal_id = ""
        if len(parts) > 1 and parts[1].isdigit():
            target_deal_id = parts[1]
        elif start_payload.isdigit():
            target_deal_id = start_payload
            target_tag = "sms"

        # 1. Сценарий СМС-РАССЫЛКИ (sms_123, broadcast_123, просто 123 или общий вход):
        # Кандидату сразу предлагаются интерактивные кнопки всех наших вахтовых вакансий
        is_sms_broadcast = (target_tag in ["sms", "broadcast", "promo"]) or (not target_tag and target_deal_id)

        if is_sms_broadcast and is_first_start:
            cand_name = name
            cand_phone = st.get("phone")
            if target_deal_id:
                deal_info = get_b24_deal(target_deal_id)
                if deal_info:
                    d_title = deal_info.get("TITLE", "")
                    cand_phone = cand_phone or extract_phone(d_title)
                    if cand_name in ["Кандидат", ""] or not cand_name:
                        t_parts = d_title.split()
                        if len(t_parts) > 1 and not t_parts[1].isdigit():
                            cand_name = t_parts[1]
                    add_b24_timeline_comment(target_deal_id, "📲 Кандидат перешел по ссылке из SMS-рассылки в МАКС Бот (@id9729371578_bot)")

            update_user_state(
                chat_id,
                deal_id=int(target_deal_id) if target_deal_id and target_deal_id.isdigit() else st.get("deal_id"),
                name=cand_name,
                phone=cand_phone,
                scenario="broadcast",
                step="AWAITING_SELECTION"
            )

            welcome_msg = (
                "Здравствуйте! Мы — прямой работодатель, предлагаем надежную работу и вахту с бесплатным проживанием в чистых квартирах, горячим питанием и компенсацией проезда. 🤝\n\n"
                "Выберите интересующий объект кнопкой ниже или задайте любой вопрос:"
            )
            send_message(chat_id, welcome_msg, keyboard=KEYBOARD_OBJECTS)
            save_chat_message(chat_id, "model", welcome_msg)
            return

        # 2. Сценарий брони конкретного объекта после звонка рекрутера (например /start abi_95748)
        if target_tag in ["abi", "tepofol", "alfa", "smart", "spb"] and target_deal_id and is_first_start:
            cand_name = name
            avito_ctx = ""
            phone_num = None

            try:
                import sys
                sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                from session_memory import get_session_profile_by_deal_id
                prof = get_session_profile_by_deal_id(target_deal_id)
                if prof:
                    if prof.get("candidate_name"):
                        cand_name = prof.get("candidate_name")
                    phone_num = prof.get("phone_number")
                    avito_ctx = f"Кандидат: {cand_name}, Возраст: {prof.get('age')}, Город: {prof.get('origin_city')}, Телефон: {phone_num}"
            except Exception as e_prof:
                print(f"[SESSION PROF ERR]: {e_prof}", flush=True)

            if target_deal_id:
                deal_info = get_b24_deal(target_deal_id)
                if deal_info:
                    d_title = deal_info.get("TITLE", "")
                    vac_title = deal_info.get("UF_CRM_1775470003043", "")
                    d_comments = deal_info.get("COMMENTS", "")
                    if cand_name in ["Кандидат", ""] or not cand_name:
                        t_parts = d_title.split()
                        if len(t_parts) > 1 and not t_parts[1].isdigit():
                            cand_name = t_parts[1]
                    avito_ctx = f"{avito_ctx}\nСделка #{target_deal_id}: {d_title}\nВакансия Авито: {vac_title}\n{d_comments}".strip()

            fac_label = FACILITY_NAMES_MAP.get(target_tag, "АБИ Владимир")

            update_user_state(
                chat_id,
                deal_id=int(target_deal_id) if target_deal_id.isdigit() else st.get("deal_id"),
                object=target_tag,
                name=cand_name,
                phone=phone_num or st.get("phone"),
                step="AWAITING_PASSPORT_MAIN",
                avito_context=avito_ctx[:1500]
            )

            welcome_msg = (
                f"Здравствуйте! Рада приветствовать вас после звонка с нашим координатором. 🤝\n\n"
                f"Мы зафиксировали вашу бронь на объект {fac_label}.\n\n"
                f"Для оформления бесплатного электронного билета на поезд/автобус за счет компании и заказа пропуска на КПП, "
                f"отправьте, пожалуйста, четкое фото 2-3 страницы паспорта (главный разворот с фотографией) сюда в чат.\n\n"
                f"Служба заботы сразу проверит данные и согласует дату выезда!"
            )
            send_message(chat_id, welcome_msg)
            save_chat_message(chat_id, "model", welcome_msg)
            return

        # 3. Общий первый вход без параметров
        if is_first_start and not has_chat_history(chat_id):
            welcome_msg = (
                "Здравствуйте! Рада приветствовать вас. Мы — прямой работодатель, предлагаем работу и вахту с бесплатным проживанием в чистых квартирах и питанием. 🤝\n\n"
                "Выберите интересующий объект кнопкой ниже или задайте любой вопрос:"
            )
            send_message(chat_id, welcome_msg, keyboard=KEYBOARD_OBJECTS)
            save_chat_message(chat_id, "model", welcome_msg)
            return

        # Сохраняем сообщение соискателя в локальную базу
        if text:
            print(f"📩 [MAX INCOMING] From {name} (Chat {chat_id}): '{text}'", flush=True)
            save_chat_message(chat_id, "user", text)

        # -------------------------------------------------------------
        # ЖЕСТКИЙ ФИЛЬТР: КАТЕГОРИЧЕСКИЙ ОТКАЗ ПО ЦЫГАНАМ / РОМАЛАМ
        # -------------------------------------------------------------
        if text and check_gypsy_refusal(text):
            print(f"🚫 [GYPSY FILTER TRIGGERED] Chat {chat_id}: '{text}'", flush=True)
            refusal_reply = "К сожалению, в настоящее время мы не можем предложить вам подходящие вакансии. Благодарим за интерес к нашей компании!"
            send_message(chat_id, refusal_reply)
            save_chat_message(chat_id, "model", refusal_reply)
            return

        # -------------------------------------------------------------
        # Б. ОБРАБОТКА ГОЛОСОВЫХ И АУДИОСООБЩЕНИЙ (SPEECH-TO-TEXT)
        # -------------------------------------------------------------
        has_voice = any(att.get("type") in ["audio", "voice"] for att in attachments)
        if has_voice:
            voice_att = next((att for att in attachments if att.get("type") in ["audio", "voice"]), None)
            voice_url = voice_att.get("payload", {}).get("url") if voice_att else None
            transcribed = transcribe_voice_message(voice_url) if voice_url else ""
            if transcribed:
                print(f"🎙 [VOICE TRANSCRIBED] From {name} (Chat {chat_id}): '{transcribed}'", flush=True)
                text = transcribed
                save_chat_message(chat_id, "user", f"🎙 {transcribed}")
            else:
                voice_reply = (
                    "Спасибо за сообщение! К сожалению, не удалось разобрать аудиозапись (возможен шум или тихий звук). "
                    "Пожалуйста, напишите ваш вопрос текстом или оставьте ваш номер телефона — координатор сразу перезвонит вам!"
                )
                send_message(chat_id, voice_reply)
                save_chat_message(chat_id, "model", voice_reply)
                return

        # -------------------------------------------------------------
        # В. ОБРАБОТКА ФОТО ДОКУМЕНТОВ (GEMINI VISION)
        # -------------------------------------------------------------
        has_photo = any(att.get("type") in ["image", "photo", "file"] for att in attachments)
        if has_photo:
            photo_att = next((att for att in attachments if att.get("type") in ["image", "photo", "file"]), None)
            photo_url = photo_att.get("payload", {}).get("url") if photo_att else None

            if photo_url:
                print(f"[GEMINI VISION] Проверка фото для чата {chat_id}...", flush=True)
                doc_check = check_document_vision(photo_url)
                print(f"[GEMINI VISION РЕЗУЛЬТАТ]: {doc_check}", flush=True)

                is_pass = doc_check.get("is_passport")
                dtype = doc_check.get("doc_type")
                desc = doc_check.get("description", "снимок")

                if not is_pass or dtype == "not_a_document":
                    reply = (
                        f"Спасибо за снимок! Но на фото не видно паспорта (кажется, это {desc}).\n\n"
                        "Для согласования службой безопасности завода и пропуска на КПП требуются официальные документы:\n"
                        "1️⃣ Главный разворот паспорта (2–3 страница с фотографией)\n"
                        "2️⃣ Разворот со штампом прописки (регистрации)\n\n"
                        "Пожалуйста, сфотографируйте разворот паспорта!"
                    )
                    send_message(chat_id, reply)
                    save_chat_message(chat_id, "model", reply)
                    return

                elif dtype == "main_page":
                    update_user_state(chat_id, has_main_page=1)
                    st["has_main_page"] = 1
                    doc_fio = doc_check.get("fio")
                    doc_age = doc_check.get("birth_year")
                    if doc_fio:
                        st["name"] = doc_fio
                        update_user_state(chat_id, name=doc_fio)

                    # Сразу отправляем выжимку в чат подбора объекта, переводим в «Направлен на смену» и уведомляем менеджера
                    dispatch_candidate_passport_submission(chat_id, st, photo_url, fio=doc_fio, age=doc_age)

                    reply = "Паспорт получен ✅ Рекрутер сейчас подключится, проверит данные и добавит вас в рабочий чат с бригадиром объекта! 🤝\n\n(При наличии возможности пришлите также фото разворота со штампом прописки/регистрации для завершения пропуска)."
                    send_message(chat_id, reply)
                    save_chat_message(chat_id, "model", reply)
                    return

                elif dtype == "registration_page":
                    update_user_state(chat_id, has_reg_page=1)
                    st["has_reg_page"] = 1

                    deal_id = st.get("deal_id")
                    if deal_id:
                        add_b24_timeline_comment(deal_id, f"📷 Получено фото паспорта: Страница с пропиской\nСсылка: {photo_url}")
                        target_tag = (st.get("object") or "abi").lower()
                        send_to_object_selection_chat(target_tag, f"📷 Прописка / регистрация соискателя ({st.get('name', 'Кандидат')}):", photo_url=photo_url)

                    if not st.get("has_main_page"):
                        reply = (
                            "Страница со штампом прописки принята! 👍\n\n"
                            "Теперь пришлите, пожалуйста, главное фото — 2–3 страницу паспорта (разворот с вашей фотографией)."
                        )
                    else:
                        reply = "Фото прописки принято ✅ Данные переданы координатору! 🤝"
                    send_message(chat_id, reply)
                    save_chat_message(chat_id, "model", reply)
                    return



        # -------------------------------------------------------------
        # Г. ФОНОВОЕ СОХРАНЕНИЕ НОМЕРА ТЕЛЕФОНА В БИТРИКС24
        # -------------------------------------------------------------
        phone = extract_phone(text)
        if phone and not st.get("phone"):
            update_user_state(chat_id, phone=phone)
            st["phone"] = phone
            # Привязываем к существующей сделке в Битрикс24 по номеру, если еще не привязана
            if not st.get("deal_id"):
                existing = find_b24_deal_by_phone(phone)
                if existing:
                    did = existing.get("ID")
                    update_user_state(chat_id, deal_id=did)
                    st["deal_id"] = did
                    add_b24_timeline_comment(did, f"💬 Кандидат вышел на связь в МАКС Боте (@id9729371578_bot), Chat ID: {chat_id}")
                    print(f"🔗 [B24 СДЕЛКА НАЙДЕНА И ПРИВЯЗАНА] #{did} для {phone} (Ответственный: {existing.get('ASSIGNED_BY_ID')})", flush=True)

        # Обновляем выбранный объект, если кандидат упомянул объект или нажал кнопку
        low_t = text.lower()
        if "аби" in low_t or "владимир" in low_t:
            update_user_state(chat_id, object="abi")
            st["object"] = "abi"
        elif "тепофол" in low_t or "кашир" in low_t:
            update_user_state(chat_id, object="tepofol")
            st["object"] = "tepofol"
        elif "альфа" in low_t or "подольск" in low_t or "климовск" in low_t:
            update_user_state(chat_id, object="alfa")
            st["object"] = "alfa"
        elif "зоотовар" in low_t or "балаших" in low_t or "petshop" in low_t or "смарт" in low_t:
            update_user_state(chat_id, object="smart")
            st["object"] = "smart"
        elif "спб" in low_t or "питер" in low_t or "шушар" in low_t or "стандарт" in low_t or "петербург" in low_t:
            update_user_state(chat_id, object="spb")
            st["object"] = "spb"

        # -------------------------------------------------------------
        # 1. ЗАПРОС СВЯЗИ С ЖИВЫМ МЕНЕДЖЕРОМ / ОПЕРАТОРОМ
        # -------------------------------------------------------------
        if check_manager_request(text):
            deal_id = st.get("deal_id")
            cand_p = st.get("phone") or ""
            cand_title = st.get("name") or name or "Кандидат"
            if deal_id:
                d_info = get_b24_deal(deal_id)
                mgr_id = d_info.get("ASSIGNED_BY_ID") if d_info else None
                if d_info and d_info.get("TITLE"):
                    cand_title = d_info.get("TITLE")
                add_b24_timeline_comment(deal_id, f"💬 Кандидат в МАКС ожидает ответа менеджера в открытой линии:\n«{text}»")
                if mgr_id:
                    notify_b24_manager(
                        mgr_id,
                        f"🔔 ВНИМАНИЕ: Кандидат {cand_title} (тел: {cand_p}, сделка #{deal_id}) в МАКС ждет ответа ответственного в открытой линии! Запрос: «{text}»"
                    )
            reply_mgr = (
                "Передала ваш запрос координатору! Специалист уже подключается к открытой линии и свяжется с вами. 🤝 "
                "Вы также можете написать ваш вопрос или уточнения здесь."
            )
            send_message(chat_id, reply_mgr)
            save_chat_message(chat_id, "model", reply_mgr)
            return

        # -------------------------------------------------------------
        # 2. ИЗЪЯВЛЕНИЕ ГОТОВНОСТИ К ВЫЕЗДУ (ЦЕЛЕВОЙ КАНДИДАТ) -> ЗАПРОС ПАСПОРТА
        # -------------------------------------------------------------
        if check_readiness_intent(text):
            deal_id = st.get("deal_id")
            cur_obj = st.get("object") or "abi"
            fac_label = FACILITY_NAMES_MAP.get(cur_obj, "АБИ Владимир")

            # Переводим сделку в Б24 в стадию «Запрос паспорта»
            if deal_id:
                update_b24_deal_stage(deal_id, "UC_REQ_PASSPORT")
                add_b24_timeline_comment(deal_id, f"📋 [МАКС БОТ]: Кандидат подтвердил интерес и готовность к выезду ({fac_label}). Сделка переведена в стадию «Запрос паспорта». Запрошено фото документов.")

            update_user_state(chat_id, step="AWAITING_PASSPORT_MAIN")
            st["step"] = "AWAITING_PASSPORT_MAIN"

            reply_pass = (
                f"Отлично, фиксирую за вами место на объект {fac_label}! 🤝\n\n"
                "Для оформления бесплатного электронного билета на поезд/автобус за счет компании и заказа электронного пропуска на КПП, "
                "отправьте, пожалуйста, четкое фото 2-3 страницы паспорта (главный разворот с фотографией) сюда в чат.\n\n"
                "Служба заботы сразу проверит данные и согласует дату выезда!"
            )
            send_message(chat_id, reply_pass)
            save_chat_message(chat_id, "model", reply_pass)
            return

        # -------------------------------------------------------------
        # 3. ПРЯМОЙ ОТВЕТ НЕЙРОСЕТИ (GEMINI LLM С ЖИВОЙ СТЕНОГРАММОЙ МАКС)
        # -------------------------------------------------------------
        live_transcript = get_live_transcript(chat_id, count=10)

        context_hint = f"Объект: {st.get('object', 'АБИ')}. "
        if phone:
            context_hint += f"Телефон кандидата: {phone}. "
        if st.get("deal_id"):
            context_hint += f"Сделка в CRM #{st.get('deal_id')}. "
        if st.get("avito_context"):
            context_hint += f"\nКОНТЕКСТ ДИАЛОГА ИЗ АВИТО:\n{st.get('avito_context')}\n"

        ai_reply = call_gemini_llm(
            dialogue_transcript=live_transcript,
            user_message=text,
            cand_name=st.get("name", name),
            context_hint=context_hint
        )

        # Если нейросеть запросила паспорт у кандидата, автоматически переводим сделку в «Запрос паспорта»
        if ("паспорт" in ai_reply.lower() or "разворот" in ai_reply.lower()) and st.get("deal_id"):
            update_b24_deal_stage(st.get("deal_id"), "UC_REQ_PASSPORT")
            add_b24_timeline_comment(st.get("deal_id"), f"📋 [МАКС БОТ]: Сделка переведена в стадию «Запрос паспорта». Соискателю отправлен запрос фото документов.")

        send_message(chat_id, ai_reply)
        save_chat_message(chat_id, "model", ai_reply)
        return


# -------------------------------------------------------------
# БОЕВОЙ ФОНОВЫЙ ЦИКЛ ОПРОСА С ХРАНЕНИЕМ МАРКЕРА В SQLITE
# -------------------------------------------------------------
_singleton_poller_lock = threading.Lock()

def bot_worker_loop():
    if not _singleton_poller_lock.acquire(blocking=False):
        print("🛑 [SINGLETON PROTECT] Поток bot_worker_loop уже запущен! Второй поток завершает работу.", flush=True)
        return

    print("=== MAX BOT ENTERPRISE LLM-NATIVE ENGINE ONLINE ===", flush=True)
    marker_str = get_meta("last_marker")
    marker = int(marker_str) if marker_str and marker_str.isdigit() else None
    if marker:
        print(f"[MAX BOT ENGINE] Восстановлен маркер из SQLite: {marker}", flush=True)
    else:
        # При чистом старте нового контейнера после деплоя проматываем старую очередь без отправки ответов!
        try:
            init_req = urllib.request.Request(f"{MAX_API_BASE}/updates?timeout=1", headers={"Authorization": TOKEN})
            with urllib.request.urlopen(init_req, timeout=10, context=ctx) as r_init:
                init_data = json.loads(r_init.read().decode('utf-8'))
            init_marker = init_data.get("marker")
            if init_marker:
                marker = init_marker
                set_meta("last_marker", marker)
                print(f"[MAX BOT ENGINE] Чистый старт после деплоя: промотана старая очередь (установлен маркер {marker}).", flush=True)
        except Exception as e_init:
            print(f"[MAX BOT INIT MARKER WARN]: {e_init}", flush=True)

    while True:
        try:
            url = f"{MAX_API_BASE}/updates?timeout=3"
            if marker:
                url += f"&marker={marker}"

            req = urllib.request.Request(url, headers={"Authorization": TOKEN})
            with urllib.request.urlopen(req, timeout=35, context=ctx) as r:
                data = json.loads(r.read().decode('utf-8'))

            new_marker = data.get("marker")
            if new_marker:
                marker = new_marker
                set_meta("last_marker", marker)

            updates = data.get("updates", [])
            for up in updates:
                try:
                    handle_single_update(up)
                except Exception as e_up:
                    print(f"[MAX UPDATE ERROR]: {e_up}", flush=True)

        except urllib.error.URLError:
            pass  # Нормальный тайм-аут длинного опроса
        except Exception as e:
            print(f"[MAX WORKER EXCEPTION]: {e}", flush=True)
            time.sleep(2)


class HealthHandler(http.server.BaseHTTPRequestHandler):
    def do_HEAD(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        res = {
            "status": "online",
            "service": "MAX Messenger Enterprise AI-Recruiter",
            "version": "2.7.0",
            "poller_alive": True,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
        }
        self.wfile.write(json.dumps(res, ensure_ascii=False).encode('utf-8'))

    def log_message(self, format, *args):
        pass


def run_http_server():
    port = int(os.environ.get("PORT", 8080))
    http.server.HTTPServer.allow_reuse_address = True
    server = http.server.HTTPServer(("0.0.0.0", port), HealthHandler)
    print(f"🌍 [HEALTHCHECK] HTTP сервер успешно запущен на порту {port}...", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    t = threading.Thread(target=bot_worker_loop, daemon=True, name="MaxBotWorkerThread")
    t.start()
    run_http_server()
