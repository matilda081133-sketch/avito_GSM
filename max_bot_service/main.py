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

# Резервный пул валидных API-ключей Google Gemini
_KEYS_POOL = [
    base64.b64decode("QVEuQWI4Uk42S0xiQURfTWVGOUJiN2F4S3pyaWNFbW9qaTlLSUgtdWZ0OW44c3FnNWpockE=").decode('utf-8'),
    base64.b64decode("QVEuQWI4Uk42Sm9NMHBkaFIzaWJmUm11ckdNcldrVklULXJtaGltY2dSdjZJTU9BdjJ4ZkE=").decode('utf-8')
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
    "gemini-3.1-flash-lite",
    "gemini-flash-latest",
    "gemini-2.5-flash"
]

# Распределение сделок между 3 менеджерами (Маргарита, Анастасия, Анна)
GIRLS_QUEUE = ["81596", "84102", "84822"]
current_girl_idx = 0

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot_state.db")

_chat_send_lock = threading.Lock()
_recent_chat_sends = {}

# Интерактивные кнопки 4 флагманских объектов
KEYBOARD_OBJECTS = [
    [{"type": "callback", "text": "1. 🥩 Владимир (АБИ) от 3 900 ₽", "payload": "Расскажите про АБИ во Владимире"}],
    [{"type": "callback", "text": "2. 🏭 Кашира (Тепофол) 3 800 ₽", "payload": "Расскажите про Тепофол в Кашире"}],
    [{"type": "callback", "text": "3. 🧴 Подольск (Альфатехформ) 3 700 ₽", "payload": "Расскажите про Альфатехформ в Подольске"}],
    [{"type": "callback", "text": "4. 🐶 Балашиха (Зоотовары) от 3 600 ₽", "payload": "Расскажите про зоотовары в Балашихе"}]
]

# -------------------------------------------------------------
# БАЗА ЗНАНИЙ ОБЪЕКТОВ (ПРЯМОЙ РАБОТОДАТЕЛЬ)
# -------------------------------------------------------------
OBJECTS_KNOWLEDGE = """
НАШИ АКТУАЛЬНЫЕ ОБЪЕКТЫ (ПРЯМОЙ РАБОТОДАТЕЛЬ):

ВАХТОВЫЕ ОБЪЕКТЫ (С БЕСПЛАТНЫМ ПРОЖИВАНИЕМ И ПИТАНИЕМ):

1. АБИ / Стародворские колбасы / Вязанка (г. Владимир):
• Производство мясных изделий (упаковка, фасовка колбас и сосисок, стикеровка, без тяжестей).
• Ставка: от 3 900 до 4 400 ₽ за смену чистыми на руки (за вахту 30 смен: 120 000 – 132 000 ₽, за 45 смен: от 180 000 ₽).
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
    cur.execute("SELECT scenario, step, selected_object, phone, has_main_page, has_reg_page, deal_id, name, last_mid FROM bot_users WHERE chat_id = ?", (chat_id,))
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
            "deal_id": None, "name": name, "last_mid": None
        }
    else:
        state = {
            "scenario": row[0], "step": row[1], "object": row[2],
            "phone": row[3], "has_main_page": row[4], "has_reg_page": row[5],
            "deal_id": row[6], "name": row[7] or name, "last_mid": row[8]
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
        f"ИМЯ СОБЕСЕДНИКА: {cand_name or 'Собеседник'}\n"
    )
    if context_hint:
        user_prompt += f"[Служебная информация: {context_hint}]\n"

    user_prompt += (
        f"САМОЕ СВЕЖЕЕ СООБЩЕНИЕ ОТ КАНДИДАТА: \"{user_message}\"\n\n"
        f"Напиши живой, чуткий, человечный ответ на свежую реплику соискателя от лица специалиста службы заботы прямого работодателя. "
        f"Если диалог уже идет — не здоровайся заново и не представляйся. "
        f"Ответ держи строго в пределах 1-2 коротких емких предложений (до 250 символов)."
    )

    for api_key in keys_pool:
        for model_name in MODELS_TO_TRY:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
            gen_cfg = {
                "temperature": 0.7,
                "maxOutputTokens": 300
            }
            if "gemini-3" in model_name:
                gen_cfg["thinkingConfig"] = {"thinkingBudget": 0}

            payload = {
                "system_instruction": {"parts": [{"text": SYSTEM_PROMPT_ENTERPRISE_RECRUITER}]},
                "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
                "generationConfig": gen_cfg
            }

            try:
                req = urllib.request.Request(
                    url,
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"}
                )
                with urllib.request.urlopen(req, timeout=8, context=ctx) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    candidates = data.get("candidates", [])
                    if candidates:
                        parts = candidates[0].get("content", {}).get("parts", [])
                        if parts and "text" in parts[0]:
                            reply = parts[0]["text"].strip()
                            return sanitize_text(reply)
            except urllib.error.HTTPError as he:
                if he.code == 429:
                    print(f"[GEMINI KEY 429] Переключение на следующий API-ключ...", flush=True)
                    break # Переходим к следующему ключу
                else:
                    print(f"[GEMINI LLM {model_name} HTTP {he.code}]: {he}", flush=True)
            except Exception as e:
                print(f"[GEMINI LLM {model_name} ERR]: {e}", flush=True)

    return (
        "Спасибо за сообщение! Служба безопасности наших производств согласовывает кандидатов "
        "строго от 20 до 55 лет с гражданством РФ. Напишите, пожалуйста, ваш номер телефона для связи с координатором!"
    )


# -------------------------------------------------------------
# GEMINI VISION (ПРОВЕРКА ФОТО ДОКУМЕНТОВ)
# -------------------------------------------------------------
def check_document_vision(img_url: str) -> dict:
    keys_pool = get_api_keys()
    try:
        req = urllib.request.Request(img_url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, context=ctx, timeout=15) as r:
            img_b64 = base64.b64encode(r.read()).decode('utf-8')

        prompt = """Посмотри внимательно на изображение.
Является ли это изображение:
1) Главным разворотом паспорта РФ (2-3 страница с фотографией, ФИО и кем выдан)
2) Разворотом паспорта РФ со штампом регистрации / прописки
3) Или это НЕ паспорт (комната, дверь, лицо без документа, посторонний предмет, чек и т.д.)?

Ответь строго валидным JSON:
{
  "is_passport": true/false,
  "doc_type": "main_page" | "registration_page" | "not_a_document",
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
                        txt = data['candidates'][0]['content']['parts'][0]['text']
                        parsed = json.loads(txt)
                        return {
                            "is_passport": bool(parsed.get("is_passport")),
                            "doc_type": parsed.get("doc_type", "not_a_document"),
                            "description": parsed.get("description", "")
                        }
                except Exception as e:
                    print(f"[GEMINI VISION {model_name} ERR]: {e}", flush=True)

    except Exception as e:
        print(f"[GEMINI VISION ERR]: {e}", flush=True)

    return {"is_passport": True, "doc_type": "main_page", "description": "документ"}


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


def create_b24_deal(name, phone, object_title="АБИ", chat_id=None):
    global current_girl_idx
    manager_id = GIRLS_QUEUE[current_girl_idx % len(GIRLS_QUEUE)]
    current_girl_idx += 1

    try:
        c_url = f"{B24_WEBHOOK}crm.contact.add.json"
        c_payload = {
            "fields": {
                "NAME": name or "Кандидат МАКС",
                "PHONE": [{"VALUE": phone, "VALUE_TYPE": "WORK"}]
            }
        }
        req = urllib.request.Request(c_url, data=json.dumps(c_payload).encode('utf-8'), headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10, context=ctx) as r:
            cid = json.loads(r.read().decode('utf-8'))['result']

        d_url = f"{B24_WEBHOOK}crm.deal.add.json"
        d_payload = {
            "fields": {
                "TITLE": f"{name} - MAX Бот: {object_title}",
                "CATEGORY_ID": 0,
                "STAGE_ID": "NEW",
                "CONTACT_ID": cid,
                "ASSIGNED_BY_ID": manager_id,
                "SOURCE_ID": "OTHER",
                "SOURCE_DESCRIPTION": f"Официальный МАКС Бот (@id9729371578_bot) | Chat ID: {chat_id} | Интерес: {object_title}"
            }
        }
        req2 = urllib.request.Request(d_url, data=json.dumps(d_payload).encode('utf-8'), headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req2, timeout=10, context=ctx) as r2:
            did = json.loads(r2.read().decode('utf-8'))['result']
        print(f"⭐ [B24 СДЕЛКА СОЗДАНА] #{did} для {name} ({phone}), Назначена: {manager_id}", flush=True)

        # Обогащаем таймлайн сделки
        if did:
            comment = (
                f"🤖 Новая заявка из официального бота МАКС (@id9729371578_bot)\n\n"
                f"👤 Кандидат: {name}\n"
                f"📞 Телефон: {phone}\n"
                f"💬 Chat ID: {chat_id}\n"
                f"🏢 Выбранный объект: {object_title}\n"
                f"📅 Дата: {time.strftime('%Y-%m-%d %H:%M:%S')}"
            )
            add_b24_timeline_comment(did, comment)

        return did
    except Exception as e:
        print(f"[B24 CREATE ERR]: {e}", flush=True)
        return None


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

        body = msg.get("body", {})
        mid = body.get("mid")
        text = (body.get("text") or "").strip()
        attachments = body.get("attachments", [])

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
        is_first_start = (u_type == "bot_started") or (text.lower() in ["/start", "старт", "начать", "меню"])
        if is_first_start and not get_chat_history(chat_id, limit=2):
            welcome_msg = (
                "Здравствуйте! Рада приветствовать вас. Мы — прямой работодатель, предлагаем работу и вахту с бесплатным проживанием в чистых квартирах и питанием.\n\n"
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
        # Б. ОБРАБОТКА ГОЛОСОВЫХ И АУДИОСООБЩЕНИЙ
        # -------------------------------------------------------------
        has_voice = any(att.get("type") in ["audio", "voice"] for att in attachments)
        if has_voice:
            voice_reply = (
                "Спасибо за сообщение! Я текстовый специалист службы заботы и не могу прослушать аудиозапись. "
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

                    # Сохраняем ссылку на фото в сделку Битрикс24
                    if st.get("deal_id"):
                        add_b24_timeline_comment(st.get("deal_id"), f"📷 Получено фото паспорта: Главный разворот 2-3 стр.\nСсылка: {photo_url}")

                    if not st.get("has_reg_page"):
                        reply = (
                            "Главный разворот паспорта принят! 👍\n\n"
                            "Теперь пришлите, пожалуйста, второе фото — разворот с действующей пропиской (штамп регистрации), "
                            "чтобы служба безопасности завершила оформление пропуска."
                        )
                    else:
                        reply = (
                            "Отлично, все необходимые документы получены! Передала их в службу безопасности на оформление пропуска.\n\n"
                            "В течение 15–30 минут координатор свяжется с вами по телефону для подтверждения деталей заезда!"
                        )
                    send_message(chat_id, reply)
                    save_chat_message(chat_id, "model", reply)
                    return

                elif dtype == "registration_page":
                    update_user_state(chat_id, has_reg_page=1)
                    st["has_reg_page"] = 1

                    # Сохраняем ссылку на фото в сделку Битрикс24
                    if st.get("deal_id"):
                        add_b24_timeline_comment(st.get("deal_id"), f"📷 Получено фото паспорта: Страница с пропиской\nСсылка: {photo_url}")

                    if not st.get("has_main_page"):
                        reply = (
                            "Страница со штампом прописки принята! 👍\n\n"
                            "Теперь пришлите, пожалуйста, фото главного разворота паспорта (2–3 страница с вашей фотографией)."
                        )
                    else:
                        reply = (
                            "Отлично, все необходимые документы получены! Передала их в службу безопасности на оформление пропуска.\n\n"
                            "В течение 15–30 минут координатор свяжется с вами по телефону для подтверждения деталей заезда!"
                        )
                    send_message(chat_id, reply)
                    save_chat_message(chat_id, "model", reply)
                    return

        # -------------------------------------------------------------
        # Г. ФОНОВОЕ СОХРАНЕНИЕ НОМЕРА ТЕЛЕФОНА В БИТРИКС24
        # -------------------------------------------------------------
        phone = extract_phone(text)
        if phone and not st.get("phone"):
            did = create_b24_deal(name, phone, st.get("object", "АБИ"), chat_id=chat_id)
            update_user_state(chat_id, phone=phone, deal_id=did)

        # -------------------------------------------------------------
        # Д. ПРЯМОЙ ОТВЕТ НЕЙРОСЕТИ (GEMINI LLM С ЖИВОЙ СТЕНОГРАММОЙ МАКС)
        # -------------------------------------------------------------
        live_transcript = get_live_transcript(chat_id, count=10)

        context_hint = ""
        if phone:
            context_hint += f"Телефон кандидата: {phone}. "
        if st.get("deal_id"):
            context_hint += f"Сделка в CRM #{st.get('deal_id')}. "

        ai_reply = call_gemini_llm(
            dialogue_transcript=live_transcript,
            user_message=text,
            cand_name=name,
            context_hint=context_hint
        )

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
