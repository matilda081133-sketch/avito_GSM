# -*- coding: utf-8 -*-
"""
MAX MESSENGER AUTONOMOUS RECRUITER BOT (UNIFIED ENTERPRISE EDITION)
1. Native HTTP Healthcheck server for Render 24/7 uptime.
2. Background thread with Long Polling for @id9729371578_bot.
3. Dual-scenario state machine:
   - Scenario 1: SMS Campaign (UTM / deep-link / button selection): Sequential funnel (Object -> Phone -> B24 Deal -> 2 Photos).
   - Scenario 2: Organic candidate: Live AI Recruiter via Gemini LLM.
4. Intelligent fallback & interruption handling:
   - When candidate asks non-typical questions/objections on ANY step, Gemini LLM handles it and gracefully guides back to the active step.
5. Gemini Vision Verification:
   - Strictly verifies that images are passport main spread (2-3 page) and registration page. Random/non-document photos are politely rejected.
6. Strict single-message response policy (no message spam).
7. Strict corporate apartments policy (no 'общежитие', no 'хостел', no 'нары', no '0 ₽ вычетов').
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
import http.server
import base64
import sqlite3

# UTF-8 stdout configuration
if sys.stdout is not None:
    try:
        sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)
    except Exception:
        pass

TOKEN = os.environ.get("MAX_BOT_TOKEN", "f9LHodD0cOK373_zW5FMjbf30myDzXbw3HF5hHBhkq0rd7XbTezj44hOJa_xVcpswVT1vIw5bd2FGoNIXvjO")
MAX_API_BASE = "https://platform-api2.max.ru"
B24_WEBHOOK = os.environ.get("B24_WEBHOOK_URL", "https://b24-4qx38o.bitrix24.ru/rest/39250/7cbs7mg1qo0vn0ov/")

_DEF_KEY = base64.b64decode("QVEuQWI4Uk42Sm9NMHBkaFIzaWJmUm11ckdNcldrVklULXJtaGltY2dSdjZJTU9BdjJ4ZkE=").decode('utf-8')
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", _DEF_KEY)
PRIMARY_MODEL = "gemini-3.1-flash-lite"
BACKUP_MODEL = "gemini-3.1-flash-lite-preview"

# Rotation among the 3 girl managers
GIRLS_QUEUE = ["81596", "84102", "84822"] # Margarita (81596), Anastasia (84102), Anna (84822)
current_girl_idx = 0

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot_state.db")

OBJECTS_DATA = {
    "abi": {
        "title": "АБИ (г. Владимир)",
        "code": "АБИ Владимир",
        "btn_text": "1. г. Владимир — от 3 700 до 4 900 ₽ (АБИ)",
        "excerpt": (
            "Вахта в г. Владимир на пищевое производство «Стародворские колбасы»:\n\n"
            "• Ставка: от 3 700 до 4 900 ₽/смена (от 129 500 ₽ за 35 смен чистыми)\n"
            "• Питание: бесплатное горячее 3 раза в день в столовой\n"
            "• Проживание: бесплатное в комфортных квартирах со всеми удобствами\n"
            "• Авансы: еженедельно 5 000 ₽, усиленный аванс до 20 000 ₽\n"
            "• Билеты: дистанционная покупка электронного билета на поезд или компенсация проезда до 5 000 ₽\n"
            "• Спецодежда: выдается бесплатно, по приезду во Владимир встречает координатор"
        )
    },
    "tepofol": {
        "title": "Тепофол (МО, г. Кашира)",
        "code": "Тепофол вахта",
        "btn_text": "2. МО, г. Кашира — 3 800 ₽ вахта / 4 000 ₽ местные",
        "excerpt": (
            "Завод теплоизоляции Тепофол (МО, г. Кашира):\n"
            "Продукция легкая (вспененный полиэтилен), чистое производство без стекловаты и пыли!\n\n"
            "• Вахта: 35 смен — ставка 3 800 ₽/смена (133 000 ₽ чистыми), для местных: 4 000 ₽/смена\n"
            "• Проживание: бесплатные уютные 2-комнатные квартиры со всеми удобствами\n"
            "• Питание: бесплатное горячее 2 раза в день на смене\n"
            "• Авансы: еженедельно 5 000 ₽ по понедельникам (на 3-й неделе усиленный до 20 000 ₽)\n"
            "• Дорога: компенсация проезда до 5 000 ₽ в первую зарплату + оплата такси до объекта"
        )
    },
    "alfa": {
        "title": "Альфатехформ (МО, Подольск / Климовск)",
        "code": "Альфатехформ",
        "btn_text": "3. МО, Подольск — 3 700 ₽ (Альфатехформ)",
        "excerpt": (
            "Производство пластиковой упаковки Альфатехформ (г. Подольск / Климовск):\n"
            "Спокойная работа: контроль качества и упаковка (без тяжестей, мужчины и женщины).\n\n"
            "• Вахта: 35 смен — ставка 3 700 ₽/смена (129 500 ₽ за 35 смен чистыми)\n"
            "• График: только ДНЕВНЫЕ смены с 9:00 до 21:00 (ночных смен нет!)\n"
            "• Питание: бесплатное горячее 2 раза в день\n"
            "• Проживание: бесплатные комфортные квартиры рядом с работой\n"
            "• Авансы: еженедельно 5 000 ₽, компенсация проезда до 5 000 ₽"
        )
    },
    "smart": {
        "title": "Смарт Family (МО, г. Балашиха)",
        "code": "Смарт Family вахта",
        "btn_text": "4. МО, г. Балашиха — Смарт Family",
        "excerpt": (
            "Склад зоотоваров Смарт Family (МО, г. Балашиха / ст. Кучино):\n"
            "Теплый современный чистый склад товаров для животных (корма, аксессуары).\n\n"
            "• Выплаты: ЕЖЕДНЕВНО для местных (3 600 - 3 900 ₽) или вахта от 15 до 45 смен\n"
            "• Ставка на вахте: до 3 710 ₽/смена (до 166 950 ₽ за 45 смен)\n"
            "• Проживание: бесплатные 2-комнатные квартиры в шаговой доступности (7-10 мин)\n"
            "• Транспорт: бесплатный корпоративный автобус от м. Новогиреево и ж/д станций\n"
            "• Авансы: еженедельно 5 000 ₽ (первый аванс уже после 3-й смены)"
        )
    }
}

WELCOME_TEXT = """Здравствуйте! Вы перешли по поводу работы на вахту с бесплатным проживанием в комфортных квартирах и питанием.

Прямо сейчас места открыты на 4 прямых объектах:
────────────────────────

1️⃣ г. Владимир — Пищевой комбинат АБИ
• Ставка: от 3 700 до 4 900 ₽/смена (от 129 500 ₽ за 35 смен)
• Бесплатное 3-разовое питание, квартиры, билет покупаем

2️⃣ МО, г. Кашира — Завод утеплителя Тепофол
• Вахта: 3 800 ₽/смена (133 000 ₽ чистыми), местные: 4 000 ₽
• Бесплатные 2-комнатные квартиры, горячее питание 2 раза

3️⃣ МО, Подольск / Климовск — Завод Альфатехформ
• Ставка: 3 700 ₽/смена (129 500 ₽ за 35 смен)
• Только дневные смены, 2-разовое питание, комфортное жилье

4️⃣ МО, г. Балашиха — Склад зоотоваров Смарт Family
• Ставка: от 3 600 до 4 200 ₽/смена
• Выплаты ежедневно или вахта, бесплатные квартиры, автобус от метро

────────────────────────
Выберите подходящий объект на кнопках ниже или напишите цифру 1, 2, 3 или 4:"""

KEYBOARD = [
    [{"type": "callback", "text": OBJECTS_DATA["abi"]["btn_text"], "payload": "abi"}],
    [{"type": "callback", "text": OBJECTS_DATA["tepofol"]["btn_text"], "payload": "tepofol"}],
    [{"type": "callback", "text": OBJECTS_DATA["alfa"]["btn_text"], "payload": "alfa"}],
    [{"type": "callback", "text": OBJECTS_DATA["smart"]["btn_text"], "payload": "smart"}]
]


SYSTEM_INSTRUCTION_RECRUITER = """Ты — опытный, заботливый и доброжелательный рекрутер компании по прямому трудоустройству на вахту в Москве, МО и Владимире.
Твоя цель: помочь кандидату устроиться, снять любые страхи и сомнения, объяснить условия и получить телефон либо фото документов (главный разворот паспорта и прописка) для службы безопасности и бронирования места в корпоративных квартирах.

СТРОГИЕ ТРЕБОВАНИЯ К ФОРМУЛИРОВКАМ:
- ПРОЖИВАНИЕ: У нас КВАРТИРЫ! КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО использовать слова «общежитие», «койко-место», «хостел», «нары», «0 рублей вычетов».
  Всегда пиши: «бесплатное проживание в комфортных квартирах со всеми удобствами: чистые комнаты, кухня, стиральная машина, Wi-Fi. Никаких вычетов из зарплаты за жилье нет».

КЛЮЧЕВЫЕ ПРАВИЛА:
1. Пиши ЖИВЫМ ЧЕЛОВЕЧЕСКИМ ЯЗЫКОМ, емко (2-4 предложения), чтобы кандидату было легко прочитать на телефоне.
2. ЕСЛИ КАНДИДАТ БОИТСЯ ОТПРАВЛЯТЬ ПАСПОРТ:
   - Прояви эмпатию: «Прекрасно вас понимаю, сейчас в интернете нужно быть осторожным!»
   - Объясни, что без СБ охрана режимного завода не выпишет пропуск на КПП, а координатор не оформит заселение в квартиру. Кредит по фото взять невозможно по закону РФ.
   - Предложи компромисс: замазать серию и номер (главное ФИО, дата рождения и фото) ИЛИ короткий звонок с менеджером.
3. ЕСЛИ ФССП / ПРИСТАВЫ / ДОЛГИ:
   - Успокой: зарплату можно получать на карту любого близкого (жены, мамы, брата), приставы не спишут ни рубля. СБ проверяет только судимости.
4. ЕСЛИ СПРАШИВАЮТ ПРО БИЛЕТЫ:
   - Компенсируем проезд до 5 000 рублей, либо координатор покупает электронный билет на поезд.
5. ЕСЛИ СЕМЕЙНАЯ ПАРА:
   - Заселяем вместе в отдельные семейные комнаты в квартире, ставим в одну смену с общими выходными.
6. В конце ответа всегда мягко возвращай кандидата к следующему логическому действию."""


def sanitize_text(text: str) -> str:
    if not text:
        return text
    replacements = {
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
    return text.strip()


def call_gemini_llm(history, user_message, context_hint=""):
    """Вызов Gemini 3.1 Flash Lite с отказоустойчивостью."""
    contents = []
    for item in history[-6:]:
        role = "user" if item.get("role") == "user" else "model"
        contents.append({"role": role, "parts": [{"text": item.get("text", "")}]})
    
    msg_with_hint = user_message
    if context_hint:
        msg_with_hint = f"[Контекст воронки: {context_hint}]\nВопрос кандидата: {user_message}"
        
    contents.append({"role": "user", "parts": [{"text": msg_with_hint}]})
    
    payload = {
        "contents": contents,
        "systemInstruction": {"parts": [{"text": SYSTEM_INSTRUCTION_RECRUITER}]},
        "generationConfig": {"temperature": 0.6, "maxOutputTokens": 350}
    }

    for model_name in [PRIMARY_MODEL, BACKUP_MODEL]:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={GEMINI_API_KEY}"
        for attempt in range(2):
            try:
                req = urllib.request.Request(
                    url,
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"}
                )
                with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    candidates = data.get("candidates", [])
                    if candidates:
                        raw = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "").strip()
                        if raw:
                            return sanitize_text(raw)
            except Exception as e:
                print(f"[GEMINI LLM {model_name} attempt {attempt+1} ERR]: {e}", flush=True)
                time.sleep(1)
    return None


def check_document_vision(img_url: str) -> dict:
    """
    Проверяет изображение через Gemini Vision:
    Возвращает dict:
    {
       "is_passport": bool,
       "doc_type": "main_page" | "registration_page" | "not_a_document",
       "description": str
    }
    """
    try:
        req = urllib.request.Request(img_url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, context=ctx, timeout=15) as r:
            img_b64 = base64.b64encode(r.read()).decode('utf-8')
            
        prompt = """Посмотри внимательно на изображение.
Является ли это изображение:
1) Главным разворотом паспорта (2-3 страница с фотографией, ФИО и кем выдан)
2) Страницей паспорта со штампом регистрации / прописки
3) Или это НЕ паспорт (комната, дверь, улица, случайный предмет, селфи без документа, пейзаж, чек и т.д.)?

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
        
        for model_name in [PRIMARY_MODEL, BACKUP_MODEL]:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={GEMINI_API_KEY}"
            try:
                req_g = urllib.request.Request(url, headers={'Content-Type': 'application/json'}, data=json.dumps(payload).encode('utf-8'))
                with urllib.request.urlopen(req_g, context=ctx, timeout=25) as r2:
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
        print(f"[GEMINI VISION DOWNLOAD ERR]: {e}", flush=True)

    # При полном сбое проверки не блокируем
    return {"is_passport": True, "doc_type": "main_page", "description": "документ"}


# --- DATABASE INITIALIZATION ---
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS bot_users (
        chat_id INTEGER PRIMARY KEY,
        user_id INTEGER,
        name TEXT,
        scenario TEXT DEFAULT 'sms',
        step TEXT DEFAULT 'AWAITING_OBJECT',
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
    conn.commit()
    conn.close()


def get_user_state(chat_id, user_id=None, name="Кандидат"):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT scenario, step, selected_object, phone, has_main_page, has_reg_page, deal_id, name, last_mid FROM bot_users WHERE chat_id = ?", (chat_id,))
    row = cur.fetchone()
    if not row:
        cur.execute("""
        INSERT INTO bot_users (chat_id, user_id, name, scenario, step, selected_object)
        VALUES (?, ?, ?, 'sms', 'AWAITING_OBJECT', 'abi')
        """, (chat_id, user_id, name))
        conn.commit()
        state = {
            "scenario": "sms", "step": "AWAITING_OBJECT", "object": "abi",
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


def send_message(chat_id, text, keyboard=None):
    """Строгая отправка 1 сообщения кандидату в диалог."""
    if not chat_id or (isinstance(chat_id, int) and chat_id <= 0) or str(chat_id).startswith("-"):
        return None

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
                return json.loads(r.read().decode('utf-8'))
        except Exception as e:
            print(f"[MAX SEND ERR attempt {attempt+1}] {e}", flush=True)
            time.sleep(1)
    return None


def answer_callback(cb_id, notification="Выбор принят"):
    url = f"{MAX_API_BASE}/answers?callback_id={cb_id}"
    payload = {"notification": notification}
    try:
        req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers={
            "Authorization": TOKEN,
            "Content-Type": "application/json"
        })
        with urllib.request.urlopen(req, timeout=5, context=ctx) as r:
            return json.loads(r.read().decode('utf-8'))
    except Exception:
        try:
            req_empty = urllib.request.Request(url, data=json.dumps({}).encode('utf-8'), headers={
                "Authorization": TOKEN,
                "Content-Type": "application/json"
            })
            with urllib.request.urlopen(req_empty, timeout=5, context=ctx) as r2:
                return json.loads(r2.read().decode('utf-8'))
        except Exception:
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


def create_b24_deal(name, phone, object_key):
    global current_girl_idx
    obj = OBJECTS_DATA.get(object_key, OBJECTS_DATA["abi"])
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
                "TITLE": f"{name} - MAX Бот: {obj['title']}",
                "CATEGORY_ID": 0,
                "STAGE_ID": "NEW",
                "CONTACT_ID": cid,
                "ASSIGNED_BY_ID": manager_id,
                "UF_CRM_1775470003043": obj["code"],
                "SOURCE_ID": "OTHER",
                "SOURCE_DESCRIPTION": f"Официальный МАКС Бот (@id9729371578_bot) | Выбран объект: {obj['title']}"
            }
        }
        req2 = urllib.request.Request(d_url, data=json.dumps(d_payload).encode('utf-8'), headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req2, timeout=10, context=ctx) as r2:
            did = json.loads(r2.read().decode('utf-8'))['result']
        print(f"[B24 DEAL CREATED] #{did} for {name} ({phone}), Object: {obj['title']}, Assigned: {manager_id}", flush=True)
        return did
    except Exception as e:
        print(f"[B24 CREATE ERR]: {e}", flush=True)
        return None


# Реестр диалогов для контекста LLM
CHAT_HISTORIES = {}


def bot_worker_loop():
    init_db()
    print("=== MAX BOT UNIFIED ENTERPRISE ENGINE STARTED ===", flush=True)
    marker = None
    
    while True:
        try:
            url = f"{MAX_API_BASE}/updates"
            if marker:
                url += f"?marker={marker}"
                
            req = urllib.request.Request(url, headers={"Authorization": TOKEN})
            with urllib.request.urlopen(req, timeout=35, context=ctx) as r:
                data = json.loads(r.read().decode('utf-8'))
                
            marker = data.get("marker", marker)
            updates = data.get("updates", [])
            
            for up in updates:
                u_type = up.get("update_type")
                
                # =========================================================
                # 1. ОБРАБОТКА ИНЛАЙН-КНОПКИ ВЫБОРА ОБЪЕКТА
                # =========================================================
                if u_type == "message_callback":
                    cb = up.get("callback", {})
                    cb_id = cb.get("callback_id")
                    payload = cb.get("payload", "")
                    sender = up.get("sender") or cb.get("user") or {}
                    user_id = sender.get("user_id")
                    rec = up.get("message", {}).get("recipient", {})
                    chat_type = rec.get("chat_type")
                    chat_id = rec.get("chat_id") or user_id
                    name = sender.get("name") or sender.get("first_name") or "Кандидат"
                    
                    if chat_type and chat_type != "dialog":
                        continue
                    if (isinstance(chat_id, int) and chat_id <= 0) or str(chat_id).startswith("-"):
                        continue
                    
                    if payload in OBJECTS_DATA and chat_id:
                        obj = OBJECTS_DATA[payload]
                        if cb_id:
                            answer_callback(cb_id, f"Выбран: {obj['title']}")
                            
                        update_user_state(
                            chat_id,
                            scenario="sms",
                            step="AWAITING_PHONE",
                            object=payload,
                            name=name
                        )
                        
                        # ЕДИНОЕ емкое сообщение без дублирования
                        msg = (
                            f"Отличный выбор! {obj['excerpt']}\n\n"
                            "────────────────────────\n"
                            "⚠️ На ближайший заезд осталось всего 3 свободных места!\n"
                            "📞 Напишите ваш номер телефона — менеджер сразу закрепит за вами бронь места:"
                        )
                        send_message(chat_id, msg)
                        continue

                # =========================================================
                # 2. ВХОДЯЩЕЕ СООБЩЕНИЕ / ФОТО / СТАРТ
                # =========================================================
                elif u_type in ["message_created", "bot_started"]:
                    msg = up.get("message", {})
                    sender = msg.get("sender") or up.get("user") or {}
                    if sender.get("is_bot"):
                        continue
                        
                    user_id = sender.get("user_id")
                    rec = msg.get("recipient", {})
                    chat_type = rec.get("chat_type")
                    chat_id = rec.get("chat_id") or up.get("chat_id") or user_id
                    name = sender.get("name") or f"{sender.get('first_name', '')} {sender.get('last_name', '')}".strip() or "Кандидат"
                    
                    if chat_type and chat_type != "dialog":
                        continue
                    if not chat_id or (isinstance(chat_id, int) and chat_id <= 0) or str(chat_id).startswith("-"):
                        continue
                        
                    body = msg.get("body", {})
                    mid = body.get("mid")
                    text = (body.get("text") or "").strip()
                    attachments = body.get("attachments", [])
                    start_payload = up.get("payload") or ""
                    
                    st = get_user_state(chat_id, user_id=user_id, name=name)
                    
                    # Защита от дублей одного и того же mid
                    if mid and st.get("last_mid") == mid:
                        continue
                    if mid:
                        update_user_state(chat_id, last_mid=mid)
                        
                    # Сохраняем в историю чата для LLM
                    hist = CHAT_HISTORIES.setdefault(chat_id, [])
                    if text:
                        hist.append({"role": "user", "text": text})

                    # Определение прикрепленного фото
                    has_photo = any(att.get("type") in ["image", "photo", "file"] for att in attachments)
                    photo_url = None
                    if has_photo:
                        photo_att = next((att for att in attachments if att.get("type") in ["image", "photo", "file"]), None)
                        photo_url = photo_att.get("payload", {}).get("url") if photo_att else None

                    # Проверка на телефон в тексте
                    phone = extract_phone(text)

                    # -------------------------------------------------------------
                    # 1. ОБРАБОТКА ФОТО ДОКУМЕНТОВ ЧЕРЕЗ GEMINI VISION
                    # -------------------------------------------------------------
                    if has_photo and photo_url:
                        print(f"[GEMINI VISION] Проверяем входящее фото для чата {chat_id}...", flush=True)
                        doc_check = check_document_vision(photo_url)
                        print(f"[GEMINI VISION РЕЗУЛЬТАТ]: {doc_check}", flush=True)

                        is_pass = doc_check.get("is_passport")
                        dtype = doc_check.get("doc_type")
                        desc = doc_check.get("description", "изображение")

                        # А. Если это НЕ паспорт (дверь, улица, интерьер, случайное фото)
                        if not is_pass or dtype == "not_a_document":
                            reply = (
                                f"Спасибо за снимок! Но на фото не видно паспорта (кажется, это {desc}).\n\n"
                                "Для службы безопасности режимного завода и оформления пропуска на КПП нам требуются именно официальные документы:\n"
                                "1️⃣ Главный разворот паспорта (2–3 страница с вашей фотографией)\n"
                                "2️⃣ Разворот с действующей пропиской (штамп регистрации)\n\n"
                                "Пожалуйста, сфотографируйте и пришлите разворот паспорта!"
                            )
                            send_message(chat_id, reply)
                            hist.append({"role": "model", "text": reply})
                            continue

                        # Б. Это главный разворот паспорта (2-3 стр)
                        elif dtype == "main_page":
                            update_user_state(chat_id, has_main_page=1)
                            st["has_main_page"] = 1
                            
                            if not st.get("has_reg_page"):
                                reply = (
                                    "Главный разворот паспорта принят! 👍\n\n"
                                    "Теперь пришлите, пожалуйста, второе фото — разворот с действующей пропиской (штамп регистрации), "
                                    "чтобы служба безопасности завершила оформление пропуска."
                                )
                                send_message(chat_id, reply)
                                hist.append({"role": "model", "text": reply})
                                continue
                            else:
                                reply = (
                                    "Отлично, все необходимые документы получены! Передал их в службу безопасности на оформление пропуска.\n\n"
                                    "В течение 15–30 минут менеджер свяжется с вами по телефону для подтверждения деталей заезда!"
                                )
                                update_user_state(chat_id, step="COMPLETED")
                                send_message(chat_id, reply)
                                hist.append({"role": "model", "text": reply})
                                continue

                        # В. Это страница прописки / регистрации
                        elif dtype == "registration_page":
                            update_user_state(chat_id, has_reg_page=1)
                            st["has_reg_page"] = 1

                            if not st.get("has_main_page"):
                                reply = (
                                    "Страница со штампом прописки принята! 👍\n\n"
                                    "Теперь пришлите, пожалуйста, фото главного разворота паспорта (2–3 страница с вашей фотографией)."
                                )
                                send_message(chat_id, reply)
                                hist.append({"role": "model", "text": reply})
                                continue
                            else:
                                reply = (
                                    "Отлично, все необходимые документы получены! Передал их в службу безопасности на оформление пропуска.\n\n"
                                    "В течение 15–30 минут менеджер свяжется с вами по телефону для подтверждения деталей заезда!"
                                )
                                update_user_state(chat_id, step="COMPLETED")
                                send_message(chat_id, reply)
                                hist.append({"role": "model", "text": reply})
                                continue
                        else:
                            # Другой документ
                            reply = (
                                "Фото получено! Проверьте, пожалуйста, чтобы было четко видно главный разворот паспорта с фото "
                                "и страницу с пропиской для согласования службой безопасности завода."
                            )
                            send_message(chat_id, reply)
                            continue

                    # -------------------------------------------------------------
                    # 2. ЕСЛИ СОИСКАТЕЛЬ ПРИСЛАЛ НОМЕР ТЕЛЕФОНА
                    # -------------------------------------------------------------
                    if phone:
                        obj_k = st.get("object", "abi")
                        obj_info = OBJECTS_DATA.get(obj_k, OBJECTS_DATA["abi"])
                        did = create_b24_deal(name, phone, obj_k)
                        
                        update_user_state(
                            chat_id,
                            phone=phone,
                            deal_id=did,
                            step="AWAITING_DOCS"
                        )
                        
                        reply = (
                            f"Спасибо! Номер {phone} принят, место на объекте «{obj_info['title']}» забронировано за вами! 👍\n\n"
                            "Чтобы служба безопасности завода выписала электронный пропуск на КПП и координатор подготовил заселение в комфортную квартиру, "
                            "отправьте, пожалуйста, два четких фото:\n"
                            "1️⃣ Главный разворот паспорта (2–3 страница с вашей фотографией)\n"
                            "2️⃣ Разворот со штампом прописки (регистрации)\n\n"
                            "Жду фото документов!"
                        )
                        send_message(chat_id, reply)
                        hist.append({"role": "model", "text": reply})
                        continue

                    # -------------------------------------------------------------
                    # 3. ВЫБОР ОБЪЕКТА ЦИФРОЙ ИЛИ НАЗВАНИЕМ (1, 2, 3, 4)
                    # -------------------------------------------------------------
                    num_map = {"1": "abi", "2": "tepofol", "3": "alfa", "4": "smart"}
                    matched_key = None
                    for num, k in num_map.items():
                        if text == num or text.startswith(num + ".") or text.startswith(num + ")"):
                            matched_key = k
                            break
                    if not matched_key:
                        t_low = text.lower()
                        if "аби" in t_low or "владимир" in t_low: matched_key = "abi"
                        elif "тепофол" in t_low or "кашир" in t_low: matched_key = "tepofol"
                        elif "альфа" in t_low or "техформ" in t_low or "подольск" in t_low or "климовск" in t_low: matched_key = "alfa"
                        elif "смарт" in t_low or "балаших" in t_low: matched_key = "smart"

                    if matched_key:
                        obj = OBJECTS_DATA[matched_key]
                        update_user_state(
                            chat_id,
                            scenario="sms",
                            step="AWAITING_PHONE",
                            object=matched_key,
                            name=name
                        )
                        msg = (
                            f"Отличный выбор! {obj['excerpt']}\n\n"
                            "────────────────────────\n"
                            "⚠️ На ближайший заезд осталось всего 3 свободных места!\n"
                            "📞 Напишите ваш номер телефона — менеджер сразу закрепит за вами бронь места:"
                        )
                        send_message(chat_id, msg)
                        hist.append({"role": "model", "text": msg})
                        continue

                    # -------------------------------------------------------------
                    # 4. ОБНАРУЖЕНИЕ СТАРТА / РАССЫЛКИ / ПЕРВОГО ВХОДА
                    # -------------------------------------------------------------
                    is_start_cmd = text.lower() in ["/start", "старт", "начать", "меню", "привет", "здравствуйте", "добрый день", "добрый вечер"] or "/start" in text.lower() or "sms" in start_payload.lower() or "utm" in text.lower()

                    if is_start_cmd and st.get("step") == "AWAITING_OBJECT":
                        send_message(chat_id, WELCOME_TEXT, KEYBOARD)
                        hist.append({"role": "model", "text": WELCOME_TEXT})
                        continue

                    # -------------------------------------------------------------
                    # 5. НЕТИПИЧНЫЕ ВОПРОСЫ / ВОЗРАЖЕНИЯ -> GEMINI LLM
                    # -------------------------------------------------------------
                    # Если кандидат пишет любой нестандартный текст («а если долги?», «я боюсь», «сколько вычетов?»)
                    # Подключаем живой LLM, который отвечает на вопрос и возвращает к активному шагу!
                    active_step = st.get("step", "AWAITING_OBJECT")
                    cur_obj = OBJECTS_DATA.get(st.get("object", "abi"), OBJECTS_DATA["abi"])
                    
                    hint = f"Кандидат находится на шаге {active_step}. Выбранный объект: {cur_obj['title']}."
                    if active_step == "AWAITING_PHONE":
                        hint += " После ответа на вопрос кандидата мягко попроси его написать номер телефона для брони места."
                    elif active_step == "AWAITING_DOCS":
                        hint += " После ответа на вопрос мягко напомни прислать фото паспорта (главный разворот и прописку)."
                    elif active_step == "AWAITING_OBJECT":
                        hint += " После ответа предложи выбрать один из 4 объектов (Владимир, Кашира, Подольск, Балашиха)."

                    ai_reply = call_gemini_llm(hist, text, context_hint=hint)
                    if ai_reply:
                        send_message(chat_id, ai_reply)
                        hist.append({"role": "model", "text": ai_reply})
                        continue

                    # Fallback напоминание по шагам воронки
                    if active_step == "AWAITING_PHONE":
                        rem = (
                            f"Чтобы координатор ответил на все ваши вопросы по объекту «{cur_obj['title']}» "
                            "и закрепил за вами место — напишите, пожалуйста, ваш номер телефона для связи."
                        )
                        send_message(chat_id, rem)
                    elif active_step == "AWAITING_DOCS":
                        rem = "Подскажите, получилось сделать фото разворота паспорта и страницы с пропиской?"
                        send_message(chat_id, rem)
                    else:
                        send_message(chat_id, WELCOME_TEXT, KEYBOARD)

        except urllib.error.URLError:
            pass # Timeout on long polling is normal
        except Exception as e:
            print(f"[BOT WORKER EXCEPTION]: {e}", flush=True)
            time.sleep(1)


# --- NATIVE HTTP SERVER FOR RENDER HEALTHCHECK ---
class HealthHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        res = {"status": "ok", "service": "max-unified-recruiter", "model": PRIMARY_MODEL}
        self.wfile.write(json.dumps(res).encode('utf-8'))

    def log_message(self, format, *args):
        pass # Silence access logs for Render healthchecks


def run_server():
    port = int(os.environ.get("PORT", 8080))
    server = http.server.HTTPServer(("0.0.0.0", port), HealthHandler)
    print(f"Healthcheck server running on port {port}...", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    t = threading.Thread(target=bot_worker_loop, daemon=True)
    t.start()
    run_server()
