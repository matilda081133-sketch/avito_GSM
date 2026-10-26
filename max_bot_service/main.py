# -*- coding: utf-8 -*-
"""
MAX MESSENGER AUTONOMOUS RECRUITER BOT (RENDER CLOUD SERVICE)
1. Built-in HTTP Healthcheck server on PORT / $PORT for Render 24/7 uptime (ZERO dependencies!).
2. Background thread with Long Polling for @id9729371578_bot.
3. Strictly 1-on-1 private dialogs with candidates (chat_type == 'dialog').
4. ZERO interaction with group chats (chats of objects / selection / recruiters).
5. Automatic Bitrix24 deal creation in rotation strictly among Margarita, Anastasia, Anna.
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

# UTF-8 stdout configuration
if sys.stdout is not None:
    try:
        sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)
    except Exception:
        pass

TOKEN = os.environ.get("MAX_BOT_TOKEN", "f9LHodD0cOK373_zW5FMjbf30myDzXbw3HF5hHBhkq0rd7XbTezj44hOJa_xVcpswVT1vIw5bd2FGoNIXvjO")
MAX_API_BASE = "https://platform-api2.max.ru"
B24_WEBHOOK = os.environ.get("B24_WEBHOOK_URL", "https://b24-4qx38o.bitrix24.ru/rest/39250/7cbs7mg1qo0vn0ov/")

# Rotation among the 3 girl managers
GIRLS_QUEUE = ["81596", "84102", "84822"] # Margarita (81596), Anastasia (84102), Anna (84822)
current_girl_idx = 0

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

OBJECTS_DATA = {
    "abi": {
        "title": "АБИ (г. Владимир)",
        "code": "АБИ Владимир",
        "btn_text": "1. г. Владимир — от 3 700 до 4 900 ₽ (АБИ)",
        "excerpt": (
            "Вахта в г. Владимир на производство «Стародворские колбасы»\n"
            "Адрес: ул. Полины Осипенко, 41\n"
            "Вахта: 35 смен\n\n"
            "🔵 Ставка: от 3 700 до 4 900 ₽/смена (от 130 000 ₽ чистыми)\n"
            "🔵 Питание: бесплатное горячее 3 раза в день в столовой\n"
            "🔵 Проживание: бесплатный хостел (семейные пары в квартирах)\n"
            "🔵 Авансы: еженедельно 5 000 ₽, усиленный аванс до 20 000 ₽\n"
            "🔵 Билеты: покупка билета или компенсация дороги до 5 000 ₽\n"
            "🔵 Бонусы: акция «Приведи друга» 10 000 ₽, перевахтовка 5 000 ₽\n"
            "🔵 Спецодежда: выдается бесплатно, по приезду во Владимир такси"
        )
    },
    "tepofol": {
        "title": "Тепофол (МО, г. Кашира)",
        "code": "Тепофол вахта",
        "btn_text": "2. МО, г. Кашира — 3 800 ₽ (Тепофол)",
        "excerpt": (
            "Вахта в Каширу (МО) на производство теплоизоляционных материалов\n"
            "Продукция легкая (вспененный полиэтилен), без стекловаты и пыли!\n"
            "Вахта: 18 смен или 35 смен на выбор\n\n"
            "🔵 Ставка: 3 800 ₽/смена (от 70 000 до 133 000 ₽)\n"
            "🔵 Проживание: бесплатная 2-комнатная квартира или хостел\n"
            "🔵 Питание: бесплатное 2 раза в день\n"
            "🔵 Авансы: 5 000 ₽ каждый понедельник, на 3-й неделе усиленный до 20 000 ₽\n"
            "🔵 Дорога: компенсация проезда 5 000 ₽ + такси по приезду в Каширу\n"
            "🔵 Бонусы: приведи друга 5 000 ₽, перевахтовка 5 000 ₽\n"
            "🔵 График: 6/1 или 7/0, смены с 8-20 и с 20-8"
        )
    },
    "arnika": {
        "title": "Арника (МО, г. Раменское)",
        "code": "Арника",
        "btn_text": "3. МО, г. Раменское — 4 200 ₽ (Арника)",
        "excerpt": (
            "Вахта в Раменское (МО) на современный мебельный склад\n"
            "Вахта: 18 смен или 30 смен на выбор\n\n"
            "🔵 Ставка: 4 200 ₽/смена (от 75 000 до 126 000 ₽)\n"
            "🔵 Проживание: бесплатная квартира в шаговой доступности от склада\n"
            "🔵 Авансы: еженедельно 5 000 ₽ (первый аванс уже после 3-й смены)\n"
            "🔵 Дорога: компенсация проезда до 5 000 ₽ при вахте 30 смен\n"
            "🔵 Бонусы: приведи друга 5 000 ₽, перевахтовка 5 000 ₽\n"
            "🔵 График: 6/1, смены с 8:00 до 20:00"
        )
    },
    "smart": {
        "title": "Смарт Family (МО, г. Балашиха)",
        "code": "Смарт Family вахта",
        "btn_text": "4. МО, г. Балашиха — от 3 600 до 4 200 ₽ (Смарт)",
        "excerpt": (
            "Склад товаров для животных Смарт Family (МО, г. Балашиха / ст. Кучино)\n"
            "Теплый чистый склад зоотоваров (корма, игрушки, аксессуары)\n"
            "Формат: вахта (15, 35, 45 смен) или смены для местных\n\n"
            "🔵 Ставка: от 3 600 до 4 200 ₽/смена\n"
            "🔵 Выплаты: ЕЖЕДНЕВНО (для местных) или еженедельные авансы по 5 000 ₽\n"
            "🔵 Проживание: бесплатная 2-комнатная квартира рядом со складом (7-10 мин)\n"
            "🔵 Транспорт: бесплатный автобус от м. Новогиреево, станций Реутово, Кучино\n"
            "🔵 Бонусы: приведи друга 5 000 ₽, перевахтовка 5 000 ₽"
        )
    }
}

WELCOME_TEXT = """Здравствуйте! Вы перешли по поводу вахты от 4 500 ₽/смена с бесплатным жильем и питанием.

Прямо сейчас места открыты на 4 прямых объектах:
────────────────────────

1. г. Владимир — Пищевой комбинат АБИ
🔵 Ставка: от 3 700 до 4 900 ₽/смена (от 130 000 ₽ за 35 смен)
🔵 3-разовое питание бесплатно, хостел бесплатно, билет покупаем

2. МО, г. Кашира — Завод утеплителя Тепофол
🔵 Ставка: 3 800 ₽/смена (от 70 000 до 133 000 ₽)
🔵 Короткая вахта от 18 смен, бесплатные квартиры, еда 2 раза

3. МО, г. Раменское — Мебельный склад Арника
🔵 Ставка: 4 200 ₽/смена (от 75 000 до 126 000 ₽)
🔵 Бесплатное жилье рядом, аванс 5 000 ₽/нед, компенсация билета

4. МО, г. Балашиха — Склад зоотоваров Смарт Family
🔵 Ставка: от 3 600 до 4 200 ₽/смена
🔵 Выплаты каждый день, бесплатные квартиры, автобус от метро

────────────────────────
Нажмите на интересующий вас объект на кнопках ниже:"""

KEYBOARD = [
    [{"type": "callback", "text": OBJECTS_DATA["abi"]["btn_text"], "payload": "abi"}],
    [{"type": "callback", "text": OBJECTS_DATA["tepofol"]["btn_text"], "payload": "tepofol"}],
    [{"type": "callback", "text": OBJECTS_DATA["arnika"]["btn_text"], "payload": "arnika"}],
    [{"type": "callback", "text": OBJECTS_DATA["smart"]["btn_text"], "payload": "smart"}]
]

USER_STATES = {}

def send_message(chat_id, text, keyboard=None):
    # АБСОЛЮТНЫЙ ПРЕДОХРАНИТЕЛЬ:
    # Запрещено отправлять в групповые чаты (чаты подбора, чаты объектов и т.д.).
    # Все группы в МАКС имеют отрицательный chat_id (< 0).
    if not chat_id or (isinstance(chat_id, int) and chat_id <= 0) or str(chat_id).startswith("-"):
        print(f"[BLOCKED GROUP SEND] Attempt to send to group chat {chat_id} was BLOCKED.", flush=True)
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
    req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers={
        "Authorization": TOKEN,
        "Content-Type": "application/json"
    })
    try:
        with urllib.request.urlopen(req, timeout=5, context=ctx) as r:
            return json.loads(r.read().decode('utf-8'))
    except Exception as e:
        try:
            req_empty = urllib.request.Request(url, data=json.dumps({}).encode('utf-8'), headers={
                "Authorization": TOKEN,
                "Content-Type": "application/json"
            })
            with urllib.request.urlopen(req_empty, timeout=5, context=ctx) as r2:
                return json.loads(r2.read().decode('utf-8'))
        except Exception as e2:
            print(f"[CALLBACK ERR] {e2}", flush=True)
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
        # Create contact
        c_url = f"{B24_WEBHOOK}crm.contact.add.json"
        c_payload = {
            "fields": {
                "NAME": name or "Кандидат МАКС",
                "PHONE": [{"VALUE": phone, "VALUE_TYPE": "WORK"}]
            }
        }
        req = urllib.request.Request(c_url, data=json.dumps(c_payload).encode('utf-8'), headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as r:
            cid = json.loads(r.read().decode('utf-8'))['result']

        # Create deal
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
        with urllib.request.urlopen(req2, timeout=10) as r2:
            did = json.loads(r2.read().decode('utf-8'))['result']
        print(f"[B24 DEAL CREATED] #{did} for {name} ({phone}), Object: {obj['title']}, Assigned: {manager_id}", flush=True)
        return did
    except Exception as e:
        print(f"[B24 CREATE ERR] {e}", flush=True)
        return None

def get_object_message(obj):
    return (
        f"{obj['excerpt']}\n\n"
        "────────────────────────\n"
        "⚠️ ВАЖНО: На ближайший заезд осталось всего 3 свободных места!\n\n"
        "📞 На какой номер телефона забронировать за вами место?\n"
        "Напишите номер в ответном сообщении — менеджер сразу закрепит бронь за вами."
    )

def bot_worker_loop():
    print("=== MAX BOT CLOUD WORKER STARTED (RENDER 24/7) ===", flush=True)
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
                
                # --- A. КЛИК ПО ИНЛАЙН-КНОПКЕ ---
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
                    
                    # ИГНОРИРОВАТЬ любые групповые чаты (chat, channel)
                    if chat_type and chat_type != "dialog":
                        continue
                    if (isinstance(chat_id, int) and chat_id <= 0) or str(chat_id).startswith("-"):
                        continue
                    
                    if payload in OBJECTS_DATA and chat_id:
                        obj = OBJECTS_DATA[payload]
                        st = USER_STATES.setdefault(chat_id, {})
                        st["object"] = payload
                        st["name"] = name
                        st["step"] = "AWAITING_PHONE"
                        
                        if cb_id:
                            answer_callback(cb_id, f"Выбран: {obj['title']}")
                            
                        # Отправляем выжимку и вопрос-призыв с ограничением мест
                        send_message(chat_id, get_object_message(obj))

                # --- B. ВХОДЯЩЕЕ ТЕКСТОВОЕ СООБЩЕНИЕ / ФОТО ---
                elif u_type == "message_created":
                    msg = up.get("message", {})
                    sender = msg.get("sender", {})
                    if sender.get("is_bot"):
                        continue
                        
                    user_id = sender.get("user_id")
                    rec = msg.get("recipient", {})
                    chat_type = rec.get("chat_type")
                    chat_id = rec.get("chat_id") or user_id
                    
                    # СТРОГАЯ ЗАЩИТА: ТОЛЬКО ЛИЧНЫЕ ДИАЛОГИ С КАНДИДАТОМ (dialog)!
                    # В групповые чаты подбора, чаты с менеджерами объектов, каналы — НЕ ПИСАТЬ НИКОГДА!
                    if chat_type != "dialog" or (isinstance(chat_id, int) and chat_id <= 0) or str(chat_id).startswith("-"):
                        continue
                        
                    body = msg.get("body", {})
                    text = (body.get("text") or "").strip()
                    attachments = body.get("attachments", [])
                    name = sender.get("name") or f"{sender.get('first_name', '')} {sender.get('last_name', '')}".strip() or "Кандидат"
                    
                    if not chat_id:
                        continue
                        
                    st = USER_STATES.setdefault(chat_id, {"step": "NEW", "object": "abi", "name": name, "deal_id": None})
                    
                    has_photo = any(att.get("type") in ["image", "photo", "file"] for att in attachments) or "фото" in text.lower()
                    phone = extract_phone(text)
                    
                    # 1. Если прислан номер телефона
                    if phone:
                        st["phone"] = phone
                        obj_k = st.get("object", "abi")
                        obj_info = OBJECTS_DATA.get(obj_k, OBJECTS_DATA["abi"])
                        did = create_b24_deal(name, phone, obj_k)
                        st["deal_id"] = did
                        st["step"] = "COMPLETED"
                        
                        reply = (
                            f"Спасибо! Номер {phone} принят.\n\n"
                            f"Место на объекте {obj_info['title']} забронировано за вами!\n"
                            "Наш менеджер перезвонит вам в ближайшее время, подробно ответит на все вопросы и согласует удобную дату выезда."
                        )
                        send_message(chat_id, reply)
                        continue
                        
                    # 2. Если соискатель прислал фото документов
                    if has_photo or "паспорт" in text.lower():
                        reply = (
                            "Фото получено и прикреплено к вашей анкете!\n\n"
                            "Менеджер свяжется с вами по указанному телефону для подтверждения деталей."
                        )
                        send_message(chat_id, reply)
                        continue

                    # 3. Если соискатель отправил цифру 1, 2, 3, 4 текстом
                    num_map = {"1": "abi", "2": "tepofol", "3": "arnika", "4": "smart"}
                    matched_key = None
                    for num, k in num_map.items():
                        if text == num or text.startswith(num + ".") or text.startswith(num + ")"):
                            matched_key = k
                            break
                    if not matched_key:
                        t_low = text.lower()
                        if "аби" in t_low or "владимир" in t_low: matched_key = "abi"
                        elif "тепофол" in t_low or "кашир" in t_low: matched_key = "tepofol"
                        elif "арник" in t_low or "раменск" in t_low: matched_key = "arnika"
                        elif "смарт" in t_low or "балаших" in t_low: matched_key = "smart"
                        
                    if matched_key:
                        obj = OBJECTS_DATA[matched_key]
                        st["object"] = matched_key
                        st["name"] = name
                        st["step"] = "AWAITING_PHONE"
                        send_message(chat_id, get_object_message(obj))
                        continue

                    # 4. Если кандидат уже выбрал объект и мы ждем телефон, но он пишет любой вопрос/текст
                    if st.get("step") == "AWAITING_PHONE":
                        obj_k = st.get("object", "abi")
                        obj_info = OBJECTS_DATA.get(obj_k, OBJECTS_DATA["abi"])
                        reminder = (
                            f"Чтобы наш менеджер набрал вас, ответил на все вопросы по объекту {obj_info['title']} "
                            "и закрепил за вами одно из 3 свободных мест — напишите, пожалуйста, ваш номер телефона для связи."
                        )
                        send_message(chat_id, reminder)
                        continue

                    # 5. Любое первое приветствие / старт -> Главное меню с кнопками
                    send_message(chat_id, WELCOME_TEXT, KEYBOARD)

        except urllib.error.URLError:
            pass # Timeout on long polling is normal
        except Exception as e:
            print(f"[BOT WORKER EXCEPTION] {e}", flush=True)
            time.sleep(1)

# --- NATIVE HTTP SERVER FOR RENDER HEALTHCHECK ---
class HealthHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        res = {
            "status": "online",
            "service": "MAX Messenger Autonomous Recruiter Bot",
            "mode": "dialog_only",
            "group_chats_blocked": True,
            "rotation": ["Маргарита (81596)", "Анастасия (84102)", "Анна (84822)"],
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
        }
        self.wfile.write(json.dumps(res, ensure_ascii=False).encode("utf-8"))

    def log_message(self, format, *args):
        pass # Silence healthcheck logs

def run_server():
    port = int(os.environ.get("PORT", 8080))
    server = http.server.HTTPServer(("0.0.0.0", port), HealthHandler)
    print(f"[HEALTHCHECK SERVER] Running on port {port}...", flush=True)
    server.serve_forever()

if __name__ == "__main__":
    # Start bot worker in background daemon thread
    t = threading.Thread(target=bot_worker_loop, daemon=True)
    t.start()
    
    # Run HTTP server on main thread for Render
    run_server()
