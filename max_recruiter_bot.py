# -*- coding: utf-8 -*-
"""
MAX MESSENGER HR BOT & CRM AUTOMATION
Интеграция с официальным Bot API мессенджера МАКС (https://platform-api2.max.ru):
1. Входящий поток соискателей в личном диалоге (https://max.ru/id9729371578_bot):
   - Отработка переходов с Авито и СМС.
   - Запрос фото паспорта для заблаговременного оформления электронного пропуска на КПП и бронирования заселения.
   - Экспертная, спокойная обработка возражений («Зачем паспорт?», «Безопасно ли?», «Вы мошенники?») БЕЗ упоминания названия компании.
   - Фиксация полученного фото паспорта и перевод сделки в Битрикс24 в статус «Направлен на смену».
   - Информирование кандидата о передаче данных бригадиру объекта.
2. Автопилот групповых чатов объектов с менеджерами/бригадирами:
   - Обнаружение анкет и номеров телефонов кандидатов.
   - Фиксация направления на смену (стадия «Направлен на смену»).
   - Обработка ответов бригадира:
     * «НЕ ДОЕХАЛ» / «НЕ ЯВИЛСЯ» -> Сделка НЕ закрывается в неуспех! Ставится срочная задача рекрутеру на обзвон для согласования новой даты.
     * «1 СМЕНА» -> Перевод в «1 смена» (UC_6KJAQX).
     * «2 СМЕНА» -> Перевод в «2 смена» (UC_CJGI9S).
     * «3 СМЕНА» -> Перевод в «3 смена» (UC_SYNU4C).
     * «4 СМЕНА» -> Перевод в «4 смена» (UC_7F1F83).
     * «5 СМЕНА» -> Перевод в «5 смена» (UC_HRXHA7) / «Оплачен 5 смен» (WON).
"""
import requests
import json
import time
import re
import sys
import os
import urllib3
from datetime import datetime, timedelta

import traceback

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
sys.stdout.reconfigure(encoding='utf-8')

# Import Bitrix24 sync
sys.path.insert(0, os.path.dirname(__file__))
import b24_sync

MAX_BOT_TOKEN = "f9LHodD0cOK373_zW5FMjbf30myDzXbw3HF5hHBhkq0rd7XbTezj44hOJa_xVcpswVT1vIw5bd2FGoNIXvjO"
MAX_API_BASE = "https://platform-api2.max.ru"
HEADERS = {
    "Authorization": MAX_BOT_TOKEN,
    "Content-Type": "application/json"
}

# Реестр групповых чатов объектов МАКС и их привязка к CRM-объектам
OBJECT_CHATS = {
    "-72039570639374": {"title": "Аби Владимир", "facility": "АБИ Владимир", "enum_id": "120"},
    "-76617943583246": {"title": "Арника", "facility": "Арника Раменское", "enum_id": "3062"},
    "-76183863200270": {"title": "Фарма чай ПОДБОР", "facility": "Фарма Цвет Опалиха", "enum_id": "3060"},
    "-74468151757326": {"title": "Бьюти Лайф", "facility": "Бьюти Лайф Москва", "enum_id": "3104"},
    "-73311326538254": {"title": "Склад китайских автозапчастей ПОДБОР", "facility": "Склад автозапчастей Подольск", "enum_id": "3108"},
    "-75926237514254": {"title": "Тепофол Подбор", "facility": "Тепофол Кашира", "enum_id": "3056"},
    "-72008292324686": {"title": "ЕЛЕНА ЖИЛИНА ПОДБОР", "facility": "Смешанный подбор (Елена Жилина)", "is_mixed": True}
}

STATE_FILE = os.path.join(os.path.dirname(__file__), "max_bot_state.json")

def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "marker": None,
        "user_sessions": {},
        "tracked_candidates": {} # digits -> {deal_id, chat_id, phone, name}
    }

def save_state(state: dict):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("[MAX BOT] Error saving state:", e, flush=True)

def send_max_message(chat_id=None, user_id=None, text="", attachments=None):
    """
    Отправка сообщения в личный чат или групповой чат МАКС
    """
    params = {}
    if chat_id:
        params["chat_id"] = chat_id
    elif user_id:
        params["user_id"] = user_id
    else:
        return None

    payload = {"text": text}
    if attachments:
        payload["attachments"] = attachments

    for attempt in range(3):
        try:
            r = requests.post(
                f"{MAX_API_BASE}/messages",
                params=params,
                headers=HEADERS,
                json=payload,
                verify=False,
                timeout=10
            )
            if r.status_code in [200, 201]:
                return r.json()
            else:
                print(f"[MAX BOT ERROR] Send message failed: {r.status_code} {r.text}", flush=True)
        except Exception as e:
            print(f"[MAX BOT ERROR] Attempt {attempt+1}: {e}", flush=True)
            time.sleep(1)
    return None

def extract_phones(text: str) -> list:
    """
    Извлекает телефонные номера РФ
    """
    if not text:
        return []
    clean = re.sub(r'[\s\-\(\)]', '', text)
    matches = re.findall(r'(?:\+?7|8)(9\d{9})', clean)
    phones = [f"+7{m}" for m in matches]
    return list(dict.fromkeys(phones))

def classify_manager_comment(text: str) -> dict:
    """
    Интеллектуальный семантический анализатор комментариев бригадиров и менеджеров объектов.
    Учитывает живой разговорный язык («Отзвонился, завтра будет», «Созвонился, сказали не будет их»,
    «Едет в поезде», «Не берет трубку», «Вышел на смену» и др.).
    """
    if not text:
        return {"intent": "UNKNOWN", "confidence": 0.0, "reason": "empty"}
    
    t = text.lower().strip()

    # 1. СМЕНЫ 2-5 (проверяем первыми, чтобы номер смены не перехватила 1-я смена)
    if re.search(r'\b5\s*смен|\bпят(ая|ую)\s+смен', t):
        return {"intent": "SHIFT_5", "confidence": 0.95}
    if re.search(r'\b4\s*смен|\bчетверт(ая|ую)\s+смен', t):
        return {"intent": "SHIFT_4", "confidence": 0.95}
    if re.search(r'\b3\s*смен|\bтрет(ья|ью)\s+смен', t):
        return {"intent": "SHIFT_3", "confidence": 0.95}
    if re.search(r'\b2\s*смен|\bвтор(ая|ую)\s+смен|2-?я\s+смена', t):
        return {"intent": "SHIFT_2", "confidence": 0.95}

    # 2. НЕ ДОЕХАЛ / НЕ ПРИЕДЕТ / ОТКАЗ / СБРОС / СЛИЛСЯ / ЗАПИЛ
    # ВАЖНО: проверяем ДО подтверждения приезда, т.к. может быть: «Созвонились, сказали не приедут»
    no_show_patterns = [
        r'не\s+будет',
        r'не\s+приед',
        r'не\s+доех',
        r'не\s+явил',
        r'не\s+приб',
        r'не\s+выш[ее]л',
        r'не\s+выход',
        r'не\s+поед',
        r'не\s+хочет',
        r'передумал',
        r'отказал',
        r'слил',
        r'пропал',
        r'не\s+бер[ее]т\s+трубк',
        r'не\s+отвеча',
        r'сбросил',
        r'наш[ее]л\s+друг',
        r'нашли\s+друг',
        r'запил',
        r'в\s+запо',
        r'отбой',
        r'отмен',
        r'не\s+приш[ее]л'
    ]
    for pat in no_show_patterns:
        if re.search(pat, t):
            return {"intent": "NO_SHOW", "confidence": 0.95, "pattern": pat}

    # 3. ВЫШЕЛ НА 1-Ю СМЕНУ / НА СМЕНЕ
    shift1_patterns = [
        r'\b1\s*смен',
        r'перв(ая|ую)\s+смен',
        r'1-?я\s+смена',
        r'вышел\s+в\s+смен',
        r'вышел\s+на\s+смен',
        r'вышли\s+в\s+смен',
        r'вышли\s+на\s+смен',
        r'на\s+смене',
        r'в\s+строю',
        r'на\s+линии',
        r'отработал\s+смен',
        r'отработал\s+1'
    ]
    for pat in shift1_patterns:
        if re.search(pat, t):
            return {"intent": "SHIFT_1", "confidence": 0.95, "pattern": pat}

    # 4. ПОДТВЕРЖДЕНИЕ ПРИЕЗДА / ЗАСЕЛЕНИЕ / В ПУТИ / НА СВЯЗИ
    # Например: «Отзвонился, завтра будет», «Едет», «В общежитии», «Заселился»
    arrival_patterns = [
        r'отзвонил',
        r'дозвонил',
        r'созвонил',
        r'на\s+связи',
        r'подтвердил',
        r'едет',
        r'едут',
        r'в\s+пут',
        r'в\s+дорог',
        r'будет\s+(завтра|сегодня|в\s+\w+)',
        r'завтра\s+будет',
        r'сегодня\s+будет',
        r'прибудет',
        r'приедет',
        r'приедут',
        r'заселя',
        r'заселил',
        r'в\s+общаг',
        r'в\s+общежит',
        r'на\s+месте',
        r'встретил',
        r'пропуск\s+заказан',
        r'добрал',
        r'жд[ее]м'
    ]
    for pat in arrival_patterns:
        if re.search(pat, t):
            return {"intent": "CONFIRMED_ARRIVAL", "confidence": 0.9, "pattern": pat}

    return {"intent": "UNKNOWN", "confidence": 0.0}

FACILITY_PATTERNS = [
    (r'(?i)(аби|владимир|abi)', "АБИ Владимир", "120"),
    (r'(?i)(тепофол|кашир)', "Тепофол Кашира", "3056"),
    (r'(?i)(арник|раменск)', "Арника Раменское", "3062"),
    (r'(?i)(фарма\s*цвет|фарма\s*чай|фарма|опалих)', "Фарма Цвет Опалиха", "3060"),
    (r'(?i)(бьюти\s*лайф|бьюти)', "Бьюти Лайф Москва", "3104"),
    (r'(?i)(автозапчаст|подольск|китайск|запчаст)', "Склад автозапчастей Подольск", "3108"),
    (r'(?i)(смарт|балаших)', "Смарт Балашиха", None),
    (r'(?i)(озон|ozon)', "Озон", None),
    (r'(?i)(вайлдберриз|вб|wb|wildberries)', "Вайлдберриз", None),
    (r'(?i)(дикси|dixy)', "Дикси", None),
]

def detect_facility_from_text(text: str) -> tuple:
    """
    Определяет объект из текста сообщения (особенно для чата Елены Жилиной со смешанными заявками).
    Возвращает (facility_name, enum_id) или (None, None).
    """
    if not text:
        return None, None
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    top_header = " ".join(lines[:3]) if lines else text
    for pat, name, enum_id in FACILITY_PATTERNS:
        if re.search(pat, top_header):
            return name, enum_id
    for pat, name, enum_id in FACILITY_PATTERNS:
        if re.search(pat, text):
            return name, enum_id
    return None, None

def find_b24_deal_by_phone(phone: str):
    """
    Ищет активную сделку по последним 10 цифрам номера точечно без перегруза CRM
    """
    clean_digits = re.sub(r'\D', '', phone)[-10:]
    if not clean_digits or len(clean_digits) < 10:
        return None

    # 1. Быстрый и точечный поиск по %TITLE в сделках (номер зашит в названии)
    deals = b24_sync.call_b24("crm.deal.list", {
        "filter": {
            "%TITLE": clean_digits,
            "CLOSED": "N"
        },
        "select": ["ID", "TITLE", "STAGE_ID", "ASSIGNED_BY_ID", "CONTACT_ID"],
        "order": {"ID": "DESC"}
    }).get("result", [])

    if deals:
        return deals[0]

    # 2. Если по TITLE не найдено, точечный поиск через контакт по duplicate.findbycomm
    for p_var in [f"+7{clean_digits}", f"8{clean_digits}", clean_digits]:
        dup_res = b24_sync.call_b24("crm.duplicate.findbycomm", {
            "type": "PHONE",
            "values": [p_var]
        })
        res_dict = dup_res.get("result")
        contacts = res_dict.get("CONTACT", []) if isinstance(res_dict, dict) else []
        if contacts:
            for cid in contacts:
                cdeals = b24_sync.call_b24("crm.deal.list", {
                    "filter": {
                        "CONTACT_ID": cid,
                        "CLOSED": "N"
                    },
                    "select": ["ID", "TITLE", "STAGE_ID", "ASSIGNED_BY_ID", "CONTACT_ID"],
                    "order": {"ID": "DESC"}
                }).get("result", [])
                if cdeals:
                    return cdeals[0]

    return None

def create_call_task(responsible_id: int, deal_id: int, title: str, description: str):
    """
    Создает задачу в CRM ответственному рекрутеру (без 15-минутных дедлайн-алармов)
    """
    task_fields = {
        'TITLE': title,
        'DESCRIPTION': description,
        'RESPONSIBLE_ID': responsible_id,
        'PRIORITY': 2,
        'UF_CRM_TASK': [f'D_{deal_id}']
    }
    # res = b24_sync.call_b24('tasks.task.add', {'fields': task_fields})
    return None # Задачи менеджерам полностью отключены

# =============================================================================
# 1. ОБРАБОТКА ДИАЛОГОВ В ЛИЧКЕ С КАНДИДАТОМ
# =============================================================================

VACANCIES_CATALOG = {
    "1": {"name": "Арника Раменское", "enum_id": "3062", "summary": "📦 Арника Раменское — 4200 ₽/смена. Мебельный склад, вахта 18 или 30 смен, проживание в квартире в пешей доступности."},
    "2": {"name": "АБИ Владимир", "enum_id": "120", "summary": "🥩 АБИ Владимир — 3700–4900 ₽/смена (навеска до 9800 ₽/сут). Бесплатное 3-разовое горячее питание, проживание, компенсация дороги."},
    "3": {"name": "Тепофол Кашира", "enum_id": "3056", "summary": "🏭 Тепофол Кашира — 3800 ₽/смена. Лёгкая продукция, бесплатное 2-разовое питание, проживание в 2-комн. квартирах."},
    "4": {"name": "Смарт Балашиха", "enum_id": "3098", "summary": "🐶 Смарт Балашиха — 3400–3710 ₽/смена. Тёплый склад зоотоваров, вахта от 15 смен, проживание в квартире рядом."}
}

MENU_TEXT = (
    "Здравствуйте! 👋 Рады вашему отклику на работу вахтой с бесплатным проживанием и питанием!\n\n"
    "Сейчас у нас открыт набор на 4 ключевых объекта:\n\n"
    "1️⃣ **Арника (Раменское, МО)** — мебельный склад\n"
    "• Ставка: **4 200 ₽ / смена** (вахта 18 или 30 смен)\n"
    "• Бесплатное проживание в квартире в пешей доступности от склада\n"
    "• Еженедельные авансы от 5 000 ₽, компенсация дороги до 5 000 ₽\n\n"
    "2️⃣ **АБИ (г. Владимир)** — мясное производство (колбасы, полуфабрикаты)\n"
    "• Ставка: **3 700 – 4 900 ₽ / смена** (навеска до **9 800 ₽ / сут**)\n"
    "• **Бесплатное 3-разовое горячее питание**, комфортное жилье, спецодежда\n"
    "• Компенсация проезда до 5 000 ₽, такси по приезду\n\n"
    "3️⃣ **Тепофол (Кашира, МО)** — завод теплоизоляции (легкая продукция)\n"
    "• Ставка: **3 800 ₽ / смена** (вахта 35 смен)\n"
    "• **Бесплатное 2-разовое питание**, проживание в 2-комнатных квартирах\n"
    "• Еженедельные авансы от 5 000 ₽, усиленный аванс до 20 000 ₽\n\n"
    "4️⃣ **Смарт Family (Балашиха, МО)** — тёплый склад зоотоваров\n"
    "• Ставка: **3 400 – 3 710 ₽ / смена** (вахта 15 / 35 / 45 смен)\n"
    "• Лёгкая работа (корма, игрушки для животных), тёплый склад\n"
    "• Проживание в 2-комнатной квартире (пешком 7–10 мин от склада)\n\n"
    "👉 **Напишите номер вакансии (1, 2, 3 или 4) и ваш контактный номер телефона**, чтобы мы забронировали за вами место и зафиксировали ставку!"
)


ROTATION_STATE_FILE = os.path.join(os.path.dirname(__file__), "broadcast_rotation_state.json")
ACTIVE_RECRUITERS_ROTATION = [84102, 81596, 84822]  # Наталья 32 отключена  # Анастасия Давыдова, Маргарита Бабынина, Анна Боркина, Наталья Кучма

def get_next_recruiter_for_lead():
    idx = 0
    try:
        if os.path.exists(ROTATION_STATE_FILE):
            with open(ROTATION_STATE_FILE, "r", encoding="utf-8") as rf:
                data = json.load(rf)
                idx = data.get("next_idx", 0)
    except Exception:
        pass
    assigned_id = ACTIVE_RECRUITERS_ROTATION[idx % len(ACTIVE_RECRUITERS_ROTATION)]
    next_idx = (idx + 1) % len(ACTIVE_RECRUITERS_ROTATION)
    try:
        with open(ROTATION_STATE_FILE, "w", encoding="utf-8") as wf:
            json.dump({"next_idx": next_idx, "last_assigned": assigned_id}, wf)
    except Exception:
        pass
    return assigned_id

def sync_sms_candidate_to_b24(phone: str, facility_name: str = None, vac_code: str = None):
    """
    Создает или обновляет сделку в Битрикс24 при получении номера:
    - Источник: Рассылка MAX (MAX_BROADCAST)
    - Название: {Объект} - {Номер}
    - Обязательно код вакансии (UF_CRM_1768815865773) и название (UF_CRM_1775470003043)
    - Ответственный: Строго боевые рекрутеры по ротации (Анастасия, Маргарита, Анна, Наталья)
    """
    if not phone:
        return None
    clean_p = re.sub(r'\D', '', phone)
    if clean_p.startswith('8') and len(clean_p) == 11:
        clean_p = '7' + clean_p[1:]
    fmt_phone = f"+{clean_p}"

    assigned_recruiter = get_next_recruiter_for_lead()

    fac = facility_name or "Вахта"
    code = vac_code
    if not code:
        fl = fac.lower()
        if "арник" in fl: code = "3056"
        elif "аби" in fl or "владимир" in fl: code = "62"
        elif "тепофол" in fl or "кашир" in fl: code = "3050"
        elif "смарт" in fl or "балаших" in fl: code = "3098"
        else: code = "62"

    deal_title = f"{fac} - {fmt_phone}"

    # 1. Поиск контакта
    c_res = b24_sync.call_b24('crm.duplicate.findbycomm', {
        'type': 'PHONE',
        'values': [fmt_phone, clean_p, clean_p[-10:]]
    })
    contact_id = None
    res_data = c_res.get('result')
    if isinstance(res_data, dict) and res_data.get('CONTACT'):
        contact_id = res_data['CONTACT'][0]
    else:
        nc = b24_sync.call_b24('crm.contact.add', {
            'fields': {
                'NAME': 'Кандидат Вахта',
                'PHONE': [{'VALUE': fmt_phone, 'VALUE_TYPE': 'WORK'}],
                'SOURCE_ID': 'MAX_BROADCAST',
                'ASSIGNED_BY_ID': assigned_recruiter
            }
        })
        contact_id = nc.get('result')

    # 2. Поиск существующей сделки
    deal = find_b24_deal_by_phone(clean_p)
    if deal:
        deal_id = deal["ID"]
        fields_to_update = {
            'TITLE': deal_title,
            'SOURCE_ID': 'MAX_BROADCAST',
            'UF_CRM_1775470003043': fac,
            'UF_CRM_1768815865773': code,
            'UF_CRM_1768827146250': '212',
            'UF_CRM_1768816742475': '98'
        }
        if str(deal.get("ASSIGNED_BY_ID")) in ("82166", "", "None", "0"):
            fields_to_update['ASSIGNED_BY_ID'] = assigned_recruiter

        b24_sync.call_b24('crm.deal.update', {
            'id': deal_id,
            'fields': fields_to_update
        })
        b24_sync.call_b24('crm.timeline.comment.add', {
            'fields': {
                'ENTITY_ID': deal_id,
                'ENTITY_TYPE': 'deal',
                'COMMENT': f"📥 [РАССЫЛКА MAX]: Кандидат оставил номер {fmt_phone} и выбрал объект '{fac}' (код вакансии: {code}). Ответственный рекрутер ID {assigned_recruiter}."
            }
        })
        print(f"[B24 SYNC] Сделка #{deal_id} обновлена: {deal_title} (код {code}, ответственный: {assigned_recruiter})", flush=True)
        return str(deal_id)
    else:
        # 3. Создание новой сделки
        nd = b24_sync.call_b24('crm.deal.add', {
            'fields': {
                'TITLE': deal_title,
                'CATEGORY_ID': '0',
                'STAGE_ID': 'NEW',
                'SOURCE_ID': 'MAX_BROADCAST',
                'CONTACT_ID': contact_id,
                'ASSIGNED_BY_ID': assigned_recruiter,
                'UF_CRM_1775470003043': fac,
                'UF_CRM_1768815865773': code,
                'UF_CRM_1768827146250': '212',
                'UF_CRM_1768816742475': '98'
            }
        })
        deal_id = nd.get('result')
        if deal_id:
            b24_sync.call_b24('crm.timeline.comment.add', {
                'fields': {
                    'ENTITY_ID': deal_id,
                    'ENTITY_TYPE': 'deal',
                    'COMMENT': f"📥 [РАССЫЛКА MAX]: Новый отклик по СМС! Номер {fmt_phone}, объект '{fac}', код вакансии: {code}. Ответственный рекрутер ID {assigned_recruiter}."
                }
            })
            print(f"[B24 SYNC] СОЗДАНА НОВАЯ СДЕЛКА #{deal_id}: {deal_title} (код {code}, ответственный {assigned_recruiter})", flush=True)
            return str(deal_id)
    return None

RECRUITERS_MAP = {
    84102: {"name": "Анастасия Давыдова", "phone": "+7 (986) 089-82-06"},
    81596: {"name": "Маргарита Бабынина", "phone": "+7 (967) 787-53-02"},
    84822: {"name": "Анна Боркина", "phone": "+7 (986) 089-81-98"},
    32: {"name": "Наталья Кучма", "phone": "+7 (967) 787-53-01"}
}

def get_object_chat_id(facility_name: str) -> str:
    """Определяет ID целевого чата подбора в МАКС по названию объекта."""
    if not facility_name:
        return "-72008292324686"
    f = facility_name.lower()
    if any(k in f for k in ["аби", "владимир", "мяс"]):
        return "-72039570639374"
    elif any(k in f for k in ["арник", "раменск"]):
        return "-76617943583246"
    elif any(k in f for k in ["фарм", "цвет", "опалих", "чай"]):
        return "-76183863200270"
    elif any(k in f for k in ["бьют", "лайф"]):
        return "-74468151757326"
    elif any(k in f for k in ["запчаст", "китай", "подольск", "автозапчаст", "альфа"]):
        return "-73311326538254"
    elif any(k in f for k in ["тепофол", "кашир", "утеплит"]):
        return "-75926237514254"
    else:
        return "-72008292324686"

def extract_ready_date_info(text: str) -> tuple:
    """Возвращает (date_text, date_iso_YYYY-MM-DD)."""
    if not text:
        return "", ""
    t = text.lower()
    now = datetime.now()
    year = now.year

    months = {
        'январ': 1, 'феврал': 2, 'март': 3, 'апрел': 4, 'ма': 5, 'июн': 6,
        'июл': 7, 'август': 8, 'сентябр': 9, 'октябр': 10, 'ноябр': 11, 'декабр': 12
    }

    # 1. '9 числа' / '12-го числа'
    m_num = re.search(r'\b(?:вые(?:хать|зд|ду)|заезд|готов|числа|с|на)?\s*(\d{1,2})\s*(?:-?[г|о]+го)?\s*числа\b', t)
    if not m_num:
        m_num = re.search(r'\b(\d{1,2})\s*(?:-?[г|о]+го)?\s*числа\b', t)
    if m_num:
        day = int(m_num.group(1))
        if 1 <= day <= 31:
            month = now.month
            if day < now.day:
                month = 1 if month == 12 else month + 1
                year = year + 1 if month == 1 else year
            return f"{day} числа", f"{year:04d}-{month:02d}-{day:02d}"

    # 2. '9 ноября' / '15 декабря'
    m_month = re.search(r'\b(\d{1,2})\s+([а-яё]+)\b', t)
    if m_month:
        day = int(m_month.group(1))
        m_word = m_month.group(2)
        for k, m_num_val in months.items():
            if m_word.startswith(k) and 1 <= day <= 31:
                return f"{day} {m_word}", f"{year:04d}-{m_num_val:02d}-{day:02d}"

    # 3. '09.11' or '09.11.2026'
    m_dot = re.search(r'\b(\d{1,2})\.(\d{1,2})(?:\.(\d{2,4}))?\b', t)
    if m_dot:
        d, m = int(m_dot.group(1)), int(m_dot.group(2))
        y = int(m_dot.group(3)) if m_dot.group(3) else year
        if y < 100:
            y += 2000
        return m_dot.group(0), f"{y:04d}-{m:02d}-{d:02d}"

    # 4. 'завтра', 'послезавтра', 'сегодня'
    if 'послезавтра' in t:
        target = now + timedelta(days=2)
        return 'послезавтра', target.strftime('%Y-%m-%d')
    if 'завтра' in t:
        target = now + timedelta(days=1)
        return 'завтра', target.strftime('%Y-%m-%d')
    if 'сегодня' in t or 'хоть сейчас' in t:
        return 'сегодня', now.strftime('%Y-%m-%d')

    return "", ""

def forward_candidate_to_selection_chat(session: dict, attachments: list, state: dict):
    """
    Пересылает фото паспорта и выжимку по кандидату в нужный групповой чат подбора МАКС,
    переводит сделку в Bitrix24 в статус 'Направлен на смену' (PREPAYMENT_INVOICE)
    и шлет колокольчик-уведомление ответственному рекрутеру.
    """
    deal_id = session.get("deal_id")
    facility = session.get("facility") or "АБИ Владимир"
    phone = session.get("phone") or "Не указан"
    zaezd_date = session.get("ready_date") or session.get("ready_date_iso") or "Уточняется"

    fio = "Кандидат"
    age = session.get("age") or "Не указан"
    citizenship = session.get("citizenship") or "РФ"
    responsible_id = None
    responsible_name = "Рекрутер"

    if deal_id:
        try:
            d_res = b24_sync.call_b24("crm.deal.get", {"id": deal_id})
            deal_info = d_res.get("result", {})
            if deal_info:
                responsible_id = deal_info.get("ASSIGNED_BY_ID")
                b24_zaezd = deal_info.get("UF_CRM_1768816817128") or deal_info.get("UF_CRM_1780991278280")
                if b24_zaezd and (zaezd_date == "Уточняется" or not zaezd_date):
                    zaezd_date = str(b24_zaezd)[:10]

                if deal_info.get("UF_CRM_1768816798") and age == "Не указан":
                    age = str(deal_info.get("UF_CRM_1768816798"))
                if deal_info.get("UF_CRM_1768816805") and citizenship == "РФ":
                    citizenship = str(deal_info.get("UF_CRM_1768816805"))

                cid = deal_info.get("CONTACT_ID")
                if cid:
                    c_res = b24_sync.call_b24("crm.contact.get", {"id": cid}).get("result", {})
                    c_name = f"{c_res.get('LAST_NAME', '')} {c_res.get('NAME', '')} {c_res.get('SECOND_NAME', '')}".strip()
                    if c_name:
                        fio = c_name
                    c_phones = c_res.get("PHONE", [])
                    if c_phones and isinstance(c_phones, list) and c_phones[0].get("VALUE"):
                        phone = c_phones[0].get("VALUE")

                if fio == "Кандидат" and deal_info.get("TITLE"):
                    t = deal_info.get("TITLE")
                    t_clean = re.sub(r'\[.*?\]', '', t).strip()
                    parts = [p.strip() for p in t_clean.split('|')]
                    if parts and parts[0]:
                        fio = parts[0]
        except Exception as e:
            print(f"[MAX BOT] Error fetching deal details for #{deal_id}: {e}", flush=True)

    if responsible_id:
        r_rec = RECRUITERS_MAP.get(int(responsible_id))
        if r_rec:
            responsible_name = r_rec["name"]
        else:
            try:
                u_res = b24_sync.call_b24("user.get", {"ID": responsible_id}).get("result", [])
                if u_res and isinstance(u_res, list):
                    responsible_name = f"{u_res[0].get('LAST_NAME', '')} {u_res[0].get('NAME', '')}".strip()
                else:
                    responsible_name = f"ID {responsible_id}"
            except Exception:
                responsible_name = f"ID {responsible_id}"
    else:
        responsible_name = "Анастасия Давыдова"

    target_chat_id = get_object_chat_id(facility)
    chat_info = OBJECT_CHATS.get(target_chat_id, {})
    chat_title = chat_info.get("title", "Подбор")

    summary_text = (
        f"📋 Новый кандидат на смену:\n"
        f"👤 ФИО: {fio}\n"
        f"🎂 Возраст: {age}\n"
        f"🌍 Гражданство: {citizenship}\n"
        f"📞 Телефон: {phone}\n"
        f"🏢 Объект: {facility}\n"
        f"📅 Дата заселения: {zaezd_date}\n"
        f"💼 Ответственный: {responsible_name}"
    )

    photos_to_send = attachments or session.get("attachments") or []
    send_max_message(chat_id=target_chat_id, text=summary_text, attachments=photos_to_send)
    print(f"[MAX BOT] Кандидат {fio} переслан в чат '{chat_title}' ({target_chat_id})", flush=True)

    if deal_id:
        b24_sync.call_b24("crm.deal.update", {
            "id": deal_id,
            "fields": {
                "STAGE_ID": "PREPAYMENT_INVOICE"
            }
        })
        b24_sync.call_b24("crm.timeline.comment.add", {
            "fields": {
                "ENTITY_ID": deal_id,
                "ENTITY_TYPE": "deal",
                "COMMENT": (
                    f"📋 [МАКС БОТ]: Кандидат прислал фото паспорта и подтвердил заезд ({zaezd_date}).\n"
                    f"Выжимка и паспорт пересланы в чат подбора: {chat_title}.\n"
                    f"Ответственный: {responsible_name}.\n"
                    f"Сделка переведена в стадию [Направлен на смену]."
                )
            }
        })
        print(f"[MAX DIRECT] Сделка #{deal_id} переведена в [Направлен на смену]", flush=True)

        if responsible_id:
            try:
                b24_sync.call_b24("im.notify.system.add", {
                    "USER_ID": responsible_id,
                    "MESSAGE": f"🚀 Кандидат {fio} ({phone}) направлен на смену на объект {facility}! Дата заселения: {zaezd_date}. Фото паспорта и выжимка отправлены в рабочий чат подбора."
                })
            except Exception as e_notif:
                print(f"[MAX BOT] Error sending B24 notification: {e_notif}", flush=True)

def handle_direct_dialog(user_id: int, text, attachments: list, state: dict):
    uid_str = str(user_id)
    session = state["user_sessions"].setdefault(uid_str, {
        "step": "START",
        "phone": None,
        "passport_received": False,
        "deal_id": None,
        "facility": None
    })

    if isinstance(text, dict):
        text = text.get("text") or text.get("body") or ""
    text_clean = str(text or "").strip()
    text_lower = text_clean.lower()

    # Если кандидат уже направлен на смену — всегда подтверждаем бронь строго без номеров и ссылок
    if session.get("step") == "COMPLETED" or session.get("forwarded_to_group"):
        send_max_message(user_id=user_id, text="Вы записаны, бронь готова! С вами скоро свяжется рекрутер.")
        return


    # 0. Разбор параметров deeplink (/start tag_dealid или /start tag)
    start_match = re.search(r'(?:/start|\bstart=|\butm_source=|\bstart\s+)\s*([a-zA-Z0-9_]+)', text_clean, re.IGNORECASE)
    if start_match:
        param = start_match.group(1).lower()
        parts = param.split('_')
        tag = parts[0]
        linked_deal_id = parts[1] if len(parts) > 1 and parts[1].isdigit() else None

        # Обработка перехода с СМС-рассылки (UTM-метка ?start=sms)
        if tag == "sms" or param.startswith("sms"):
            session["source"] = "MAX_BROADCAST"
            session["utm_source"] = "sms"
            session["step"] = "AWAITING_CHOICE_AND_PHONE"
            save_state(state)
            send_max_message(user_id=user_id, text=MENU_TEXT)
            return
        
        TAG_TO_FACILITY = {
            "abi": ("АБИ Владимир", "120"),
            "tepofol": ("Тепофол Кашира", "3056"),
            "smart": ("Смарт Балашиха", None),
            "alfa": ("Склад автозапчастей Подольск", "3108"),
            "arnika": ("Арника Раменское", "3062"),
            "farma": ("Фарма Цвет Опалиха", "3060"),
            "beauty": ("Бьюти Лайф Москва", "3104")
        }
        
        if tag in TAG_TO_FACILITY:
            fac_name, enum_id = TAG_TO_FACILITY[tag]
            session["facility"] = fac_name
            if enum_id:
                session["facility_enum"] = enum_id
        if linked_deal_id:
            session["deal_id"] = linked_deal_id
            try:
                deal_info = b24_sync.call_b24('crm.deal.get', {'id': linked_deal_id}).get('result')
                if deal_info:
                    cid = deal_info.get('CONTACT_ID')
                    if cid:
                        c_info = b24_sync.call_b24('crm.contact.get', {'id': cid}).get('result', {})
                        phones_c = c_info.get('PHONE', [])
                        if phones_c and isinstance(phones_c, list) and phones_c[0].get('VALUE'):
                            session["phone"] = phones_c[0].get('VALUE')
            except Exception as e:
                print(f"[MAX BOT] Error fetching deal {linked_deal_id}: {e}", flush=True)
        save_state(state)

        fac_name = session.get("facility", "АБИ Владимир")
        reply = (
            f"Здравствуйте! Рады приветствовать вас! 🤝\n\n"
            f"Вы откликнулись на вахту: **{fac_name}**.\n"
            f"Ваша заявка уже в работе у координатора.\n\n"
            f"Сейчас мы:\n"
            f"1. Добавляем вас в рабочий чат с бригадиром на объекте;\n"
            f"2. Оформляем электронный разовый пропуск на КПП завода и заказываем бесплатный билет на поезд/автобус.\n\n"
            f"📸 Пожалуйста, отправьте прямо сюда в чат **фото главной страницы паспорта** (разворот с фото и страницу прописки).\n\n"
            f"🔒 Ваши данные строго конфиденциальны, защищены законом 152-ФЗ и используются исключительно службой безопасности объекта для пропуска и покупки билета."
        )
        send_max_message(user_id=user_id, text=reply)
        session["step"] = "AWAITING_PASSPORT"
        save_state(state)
        return

    # 1. Извлечение телефона, если кандидат прислал его
    phones = extract_phones(text_clean)
    new_phone_provided = False
    deal = None
    if phones:
        if not session.get("phone") or session.get("phone") != phones[0]:
            session["phone"] = phones[0]
            new_phone_provided = True
            deal = find_b24_deal_by_phone(session["phone"])
            if deal:
                session["deal_id"] = deal["ID"]
                # Проверяем, известен ли объект в сделке
                t = deal.get("TITLE") or ""
                fac_name, enum_id = detect_facility_from_text(t)
                if fac_name:
                    session["facility"] = fac_name
            save_state(state)

    # 2. Проверка: отправлено ли фото/документ паспорта
    has_photo = False
    if attachments:
        for att in attachments:
            att_type = att.get("type", "")
            if att_type in ["image", "photo", "file"]:
                has_photo = True
                break

    if any(w in text_lower for w in ["паспорт", "отправил", "скинул", "прикрепил", "вот фото"]) and len(text_clean) < 30:
        has_photo = True

    if has_photo:
        session["passport_received"] = True
        if attachments:
            session["attachments"] = attachments
        session["step"] = "PASSPORT_RECEIVED"
        save_state(state)

    # 3. Извлечение даты заселения из текста
    d_text, d_iso = extract_ready_date_info(text_clean)
    if d_iso:
        session["ready_date"] = d_text
        session["ready_date_iso"] = d_iso
        save_state(state)
        if session.get("deal_id"):
            try:
                b24_sync.call_b24("crm.deal.update", {
                    "id": session["deal_id"],
                    "fields": {
                        "UF_CRM_1768816817128": d_iso,
                        "UF_CRM_1780991278280": d_iso
                    }
                })
            except Exception:
                pass

    # 4. Если есть фото паспорта (или получено ранее)
    if session.get("passport_received"):
        deal_id = session.get("deal_id")
        if not deal_id and session.get("phone"):
            deal = find_b24_deal_by_phone(session["phone"])
            if deal:
                deal_id = deal["ID"]
                session["deal_id"] = deal_id
                save_state(state)
            else:
                did = sync_sms_candidate_to_b24(session["phone"], session.get("facility"))
                if did:
                    deal_id = did
                    session["deal_id"] = deal_id
                    save_state(state)

        # 4.1. Если еще нет номера телефона — просим номер
        if not session.get("phone"):
            reply = (
                "Фото паспорта принято! ✅\n\n"
                "Чтобы зафиксировать вашу бронь на смену, **напишите, пожалуйста, ваш контактный номер телефона** прямо сюда в чат."
            )
            send_max_message(user_id=user_id, text=reply)
            return

        # 4.2. Проверяем дату заселения
        has_date = bool(session.get("ready_date_iso"))
        if not has_date and deal_id:
            try:
                d_check = b24_sync.call_b24("crm.deal.get", {"id": deal_id}).get("result", {})
                b24_d = d_check.get("UF_CRM_1768816817128") or d_check.get("UF_CRM_1780991278280")
                if b24_d:
                    has_date = True
                    session["ready_date_iso"] = str(b24_d)[:10]
                    save_state(state)
            except Exception:
                pass

        # Если даты заселения еще нет — вежливо уточняем дату
        if not has_date:
            if session.get("step") == "AWAITING_DATE" and len(text_clean) > 1:
                session["ready_date"] = text_clean[:50]
                session["ready_date_iso"] = (datetime.now() + timedelta(days=2)).strftime('%Y-%m-%d')
                has_date = True
                save_state(state)
            else:
                reply = (
                    "Фото паспорта принято! ✅\n\n"
                    "На какую дату вы планируете заезд на смену (заселение)?"
                )
                send_max_message(user_id=user_id, text=reply)
                session["step"] = "AWAITING_DATE"
                save_state(state)
                return

        # 4.3. Кандидат квалифицирован: есть паспорт, телефон и дата заселения!
        if not session.get("forwarded_to_group"):
            forward_candidate_to_selection_chat(session, attachments or session.get("attachments"), state)
            session["forwarded_to_group"] = True
            session["step"] = "COMPLETED"
            save_state(state)

        # Ответ кандидату — СТРОГО БЕЗ НОМЕРОВ И ССЫЛОК:
        send_max_message(user_id=user_id, text="Вы записаны, бронь готова! С вами скоро свяжется рекрутер.")
        return

    # 4. Если кандидат ТОЛЬКО ЧТО прислал номер телефона — СРАЗУ СОЗДАЕМ/ОБНОВЛЯЕМ СДЕЛКУ В БИТРИКС24!
    if new_phone_provided:
        # Создаем или обновляем сделку в Bitrix24
        did = sync_sms_candidate_to_b24(session["phone"], session.get("facility"))
        if did:
            session["deal_id"] = did
            save_state(state)

        # СЛУЧАЙ А: Объект уже известен (выбран)
        if session.get("facility"):
            reply = (
                f"Отлично, номер {session['phone']} зафиксирован по объекту: **{session['facility']}**! ✅\n\n"
                "Сделка создана, ставка и бронь места зафиксированы за вами.\n\n"
                "Чтобы служба безопасности успела заранее оформить для вас разовый электронный пропуск на КПП к заезду — отправьте, пожалуйста, **фото главной страницы паспорта** (разворот с фото).\n\n"
                "🔒 Серию и номер по желанию можете прикрыть пальцем — нужны только ФИО, дата рождения и фото для КПП."
            )
            send_max_message(user_id=user_id, text=reply)
            session["step"] = "AWAITING_PASSPORT"
            save_state(state)
            return
        else:
            # СЛУЧАЙ Б: Объект еще не выбран — предлагаем выбор из 4 объектов
            reply = (
                f"Отлично, номер {session['phone']} зафиксирован! ✅\n\n"
                + MENU_TEXT
            )
            send_max_message(user_id=user_id, text=reply)
            session["step"] = "AWAITING_CHOICE_OR_PASSPORT"
            save_state(state)
            return

    # 5. Обработка выбора объекта по номеру (1-4) или названию
    num_match = re.search(r'\b([1-4])\b', text_clean)
    if num_match and session["step"] in ["AWAITING_CHOICE_OR_PASSPORT", "AWAITING_DATA", "AWAITING_CHOICE_AND_PHONE", "START"]:
        chosen_key = num_match.group(1)
        vac_info = VACANCIES_CATALOG.get(chosen_key)
        if vac_info:
            session["facility"] = vac_info["name"]
            save_state(state)
            
            # Если номер уже есть — сразу обновляем сделку в Bitrix24 с кодом вакансии и новым названием
            if session.get("phone"):
                did = sync_sms_candidate_to_b24(session["phone"], vac_info["name"], vac_info.get("enum_id"))
                if did:
                    session["deal_id"] = did
                    save_state(state)

            reply = (
                f"Отлично! {vac_info['summary']}\n\n"
                + ("📱 **Напишите ваш контактный номер телефона**, чтобы мы забронировали место в общежитии и зафиксировали ставку!\n\n" if not session.get("phone") else "")
                + "📸 Для оформления пропуска на КПП к вашему приезду отправьте фото главной страницы паспорта (разворот с фото, серию/номер можно закрыть)."
            )
            send_max_message(user_id=user_id, text=reply)
            return
            return

    # 6. Отработка согласия прислать фото
    if any(w in text_lower for w in ["да", "сейчас", "скину", "смогу", "отправлю", "хорошо", "ок", "минуту", "ща"]):
        reply = "Отлично, жду! Прикрепите фото разворота паспорта прямо сюда в чат для оформления пропуска."
        send_max_message(user_id=user_id, text=reply)
        return

    # 7. ТРИГГЕР: Зарплата, выплаты, авансы, карта третьего лица
    money_words = ["зарплат", "ставка", "сколько платят", "расчет", "аванс", "деньги", "выплат", "чужая карт", "карту мужа", "карту жены", "карту мам", "карту родственник", "арест"]
    if any(w in text_lower for w in money_words):
        reply = (
            "По условиям оплаты и выплатам:\n\n"
            "💰 Ставка 3 800 – 4 500 руб. за смену (на навеске на АБИ — до 9 800 руб./сутки!).\n"
            "💵 Еженедельные авансы от 5 000 руб., усиленный аванс до 20 000 руб. Полный расчёт сразу в конце вахты.\n"
            "💳 Выплаты возможны на карту любого банка или карту родственника по личному заявлению.\n\n"
            "Чтобы зафиксировать эти условия за вами — напишите ваш контактный номер телефона!"
        )
        send_max_message(user_id=user_id, text=reply)
        return

    # 8. Отработка возражений и сомнений (безопасность, мошенники, зачем паспорт)
    objection_words = [
        "зачем", "почему", "мошенник", "развод", "безопасн", "боюсь",
        "кредит", "куда уйд", "кому", "опаса", "не буду", "не хочу скидывать",
        "паспорт зачем", "зачем паспорт", "зачем фото"
    ]
    if any(w in text_lower for w in objection_words):
        reply = (
            "Понимаем ваши опасения, это естественно!\n\n"
            "Склад и производство — режимные охраняемые объекты со строгим КПП. Фото разворота нужно исключительно службе безопасности для заказа разового электронного пропуска перед вашим приездом и бронирования места в общежитии.\n\n"
            "Данные строго конфиденциальны, защищены законом РФ и используются исключительно службой безопасности объекта для выпуска разового пропуска на КПП и бронирования проживания.\n\n"
            "Серию и номер можете закрыть пальцем или бумажкой — нам нужны только ФИО, дата рождения и фото для КПП!"
        )
        send_max_message(user_id=user_id, text=reply)
        return

        # 9. Первое касание / /start / Приветствие — показываем приветствие и 4 вакансии!
    if session["step"] == "START" or text_lower in ["/start", "start", "привет", "здравствуйте", "старт", "начать", "добрый день", "запустить"] or "вахт" in text_lower:
        send_max_message(user_id=user_id, text=MENU_TEXT)
        session["step"] = "AWAITING_CHOICE_AND_PHONE"
        save_state(state)
        return

    # 10. По умолчанию: просим номер
    if not session.get("phone"):
        send_max_message(user_id=user_id, text="Для проверки вашей заявки и оформления пропуска — напишите, пожалуйста, ваш номер телефона!")
    else:
        send_max_message(user_id=user_id, text="Для завершения оформления пропуска на объект — отправьте, пожалуйста, фото главной страницы паспорта прямо сюда в чат.")


# =============================================================================
# 2. ОБРАБОТКА СООБЩЕНИЙ В ГРУППОВЫХ ЧАТАХ ОБЪЕКТОВ С БРИГАДИРАМИ
# =============================================================================
def handle_group_chat_message(chat_id: str, sender_name: str, text, attachments: list, link: dict, state: dict):
    if isinstance(text, dict):
        text = text.get("text") or text.get("body") or ""
    text_clean = str(text or "").strip()
    text_lower = text_clean.lower()

    
    chat_info = OBJECT_CHATS.get(str(chat_id), {})
    default_facility = chat_info.get("facility") or f"Объект МАКС (ID {chat_id})"
    default_enum_id = chat_info.get("enum_id")
    is_mixed = chat_info.get("is_mixed", False)

    # 1. Извлекаем телефон и текст из сообщения ИЛИ из ответа на сообщение (reply)
    reply_text = ""
    if link and isinstance(link, dict):
        reply_msg = link.get("message")
        if isinstance(reply_msg, dict):
            raw_reply = reply_msg.get("body") or reply_msg.get("text") or ""
        else:
            raw_reply = ""
        if isinstance(raw_reply, dict):
            reply_text = raw_reply.get("text") or raw_reply.get("body") or ""
        else:
            reply_text = str(raw_reply or "")

    # Интеллектуальное распознавание объекта: из шапки заявки (особенно актуально для чата Елены Жилиной)
    detected_fac, detected_enum = detect_facility_from_text(text_clean)
    if not detected_fac and reply_text:
        detected_fac, detected_enum = detect_facility_from_text(reply_text)

    facility_name = detected_fac or default_facility
    enum_id = detected_enum or default_enum_id

    phones = extract_phones(text_clean)
    if not phones and reply_text:
        phones = extract_phones(reply_text)

    # 2. Если в сообщении есть телефон кандидата — связываем сделку
    matched_deal = None
    clean_digits = None

    if phones:
        candidate_phone = phones[0]
        clean_digits = re.sub(r'\D', '', candidate_phone)[-10:]
        matched_deal = find_b24_deal_by_phone(candidate_phone)

        if matched_deal:
            did = matched_deal["ID"]
            state["tracked_candidates"][clean_digits] = {
                "deal_id": did,
                "chat_id": chat_id,
                "facility": facility_name,
                "phone": candidate_phone,
                "title": matched_deal.get("TITLE", ""),
                "responsible_id": matched_deal.get("ASSIGNED_BY_ID")
            }
            save_state(state)

            # Если анкета/паспорт кандидата направлен в чат — переводим из «В работе» в «Направлен на смену»
            curr_stage = matched_deal.get("STAGE_ID")
            if curr_stage in ["NEW", "PREPARATION", "UC_G0AG7S", "UC_REQ_PASSPORT"]:
                update_fields = {
                    "STAGE_ID": "PREPAYMENT_INVOICE" # Направлен на смену
                }
                if enum_id:
                    update_fields["UF_CRM_1775470003043"] = enum_id
                elif facility_name and not is_mixed:
                    update_fields["UF_CRM_1775470003043"] = facility_name

                b24_sync.call_b24("crm.deal.update", {
                    "id": did,
                    "fields": update_fields
                })
                chat_label = f"Елена Жилина ➔ {facility_name}" if is_mixed else facility_name
                b24_sync.call_b24("crm.timeline.comment.add", {
                    "fields": {
                        "ENTITY_ID": did,
                        "ENTITY_TYPE": "deal",
                        "COMMENT": f"🚀 [МАКС ЧАТ: {chat_label}]: Кандидат направлен бригадиру в чат ({sender_name}). Сделка переведена в статус [Направлен на смену]."
                    }
                })
                print(f"[MAX GROUP: {chat_label}] Сделка #{did} ({candidate_phone}) переведена в [Направлен на смену]", flush=True)

    # 3. Интеллектуальный анализ статуса от бригадира/менеджера объекта
    analysis = classify_manager_comment(text_clean)
    intent = analysis.get("intent", "UNKNOWN")

    # Если сообщение не несет статуса и нет ответа на анкету — пропускаем
    if intent == "UNKNOWN" and not link:
        return

    # Находим кандидата, к которому относится сообщение бригадира:
    # 1) Либо по номеру из текущего сообщения/реплая
    # 2) Либо последний кандидат, зафиксированный в этом чате
    target_cand = None
    if clean_digits and clean_digits in state.get("tracked_candidates", {}):
        target_cand = state["tracked_candidates"][clean_digits]
    else:
        # Ищем последнего кандидата из этого чата
        for digits, cand_data in reversed(list(state.get("tracked_candidates", {}).items())):
            if cand_data.get("chat_id") == chat_id:
                target_cand = cand_data
                break

    if not target_cand:
        print(f"[MAX GROUP] Статус '{text_clean}' (интент: {intent}) получен, но кандидат не сопоставлен с CRM.", flush=True)
        return

    did = target_cand["deal_id"]
    phone = target_cand.get("phone", "")
    title = target_cand.get("title", "")
    resp_id = target_cand.get("responsible_id") or 32

    facility = target_cand.get("facility") or OBJECT_CHATS.get(str(chat_id), {}).get("facility") or "Объект МАКС"

    # --- СЦЕНАРИЙ А: НЕ ДОЕХАЛ / ОТМЕНА / НЕ БУДЕТ (ПО РЕШЕНИЮ ДЕВОЧЕК СТОИТ ОБЗВОНИТЬ!) ---
    if intent == "NO_SHOW":
        print(f"[MAX STATUS: {facility}] Бригадир/менеджер сообщил: НЕ ДОЕХАЛ / ОТМЕНА ('{text_clean}') по сделке #{did}. Создаем задачу на обзвон!", flush=True)
        # Оставляем сделку в работе (НЕ закрываем в неуспех!)
        b24_sync.call_b24("crm.timeline.comment.add", {
            "fields": {
                "ENTITY_ID": did,
                "ENTITY_TYPE": "deal",
                "COMMENT": (
                    f"⚠️ [МАКС ЧАТ: {facility}]: Менеджер/бригадир {sender_name} ответил на анкету кандидата:\n"
                    f"«{text_clean}»\n"
                    f"⛔ Кандидат не доехал / не выходит.\n"
                    f"Сделка НЕ закрыта в отказ: поставлена срочная задача рекрутеру созвониться и согласовать новую дату!"
                )
            }
        })
        # Ставим задачу рекрутеру
        create_call_task(
            responsible_id=resp_id,
            deal_id=did,
            title=f"📞 СРОЧНО ОБЗВОНИТЬ (НЕ ДОЕХАЛ): [{facility}] {title or phone}",
            description=(
                f"⚠️ Менеджер {sender_name} в чате объекта [{facility}] сообщил, что кандидат не доехал / отменился!\n\n"
                f"💬 Сообщение менеджера: «{text_clean}»\n"
                f"📍 Объект: {facility}\n"
                f"👤 Кандидат: {title}\n"
                f"📞 Телефон: {phone}\n\n"
                f"👉 Необходимо срочно набрать кандидата, выяснить причину и согласовать новую дату приезда."
            )
        )
        return

    # --- СЦЕНАРИЙ Б: ПОДТВЕРЖДЕНИЕ ПРИЕЗДА / ЗАСЕЛЕНИЕ / В ПУТИ ---
    if intent == "CONFIRMED_ARRIVAL":
        b24_sync.call_b24("crm.deal.update", {
            "id": did,
            "fields": {
                "STAGE_ID": "PREPAYMENT_INVOICE" # Направлен на смену / заселение
            }
        })
        b24_sync.call_b24("crm.timeline.comment.add", {
            "fields": {
                "ENTITY_ID": did,
                "ENTITY_TYPE": "deal",
                "COMMENT": f"🟢 [МАКС ЧАТ: {facility}]: Менеджер {sender_name} подтвердил приезд/заселение: «{text_clean}». Сделка зафиксирована в [Направлен на смену]."
            }
        })
        print(f"[MAX STATUS: {facility}] Сделка #{did}: приезд/заселение подтверждено ('{text_clean}')", flush=True)
        return

    # --- СЦЕНАРИЙ В: 1 СМЕНА ---
    if intent == "SHIFT_1":
        b24_sync.call_b24("crm.deal.update", {
            "id": did,
            "fields": {
                "STAGE_ID": "UC_6KJAQX" # 1 смена
            }
        })
        b24_sync.call_b24("crm.timeline.comment.add", {
            "fields": {
                "ENTITY_ID": did,
                "ENTITY_TYPE": "deal",
                "COMMENT": f"🎉 [МАКС ЧАТ: {facility}]: Бригадир/менеджер {sender_name} подтвердил выход: «{text_clean}». Сделка переведена в [1 смена]."
            }
        })
        print(f"[MAX STATUS: {facility}] Сделка #{did}: ПЕРЕВЕДЕНА В [1 СМЕНА]", flush=True)
        return

    # --- СЦЕНАРИЙ Г: 2 СМЕНА ---
    if intent == "SHIFT_2":
        b24_sync.call_b24("crm.deal.update", {
            "id": did,
            "fields": {
                "STAGE_ID": "UC_CJGI9S" # 2 смена
            }
        })
        b24_sync.call_b24("crm.timeline.comment.add", {
            "fields": {
                "ENTITY_ID": did,
                "ENTITY_TYPE": "deal",
                "COMMENT": f"⭐ [МАКС ЧАТ: {facility}]: Бригадир {sender_name} подтвердил: «{text_clean}». Сделка переведена в [2 смена]."
            }
        })
        print(f"[MAX STATUS: {facility}] Сделка #{did}: ПЕРЕВЕДЕНА В [2 СМЕНА]", flush=True)
        return

    # --- СЦЕНАРИЙ Г: 3 СМЕНА ---
    if intent == "SHIFT_3":
        b24_sync.call_b24("crm.deal.update", {
            "id": did,
            "fields": {
                "STAGE_ID": "UC_SYNU4C" # 3 смена
            }
        })
        b24_sync.call_b24("crm.timeline.comment.add", {
            "fields": {
                "ENTITY_ID": did,
                "ENTITY_TYPE": "deal",
                "COMMENT": f"⭐ [МАКС ЧАТ: {facility}]: Бригадир {sender_name} подтвердил: кандидат отработал 3 смену! Сделка переведена в [3 смена]."
            }
        })
        print(f"[MAX STATUS: {facility}] Сделка #{did}: ПЕРЕВЕДЕНА В [3 СМЕНА]", flush=True)
        return

    # --- СЦЕНАРИЙ Д: 4 СМЕНА ---
    if intent == "SHIFT_4":
        b24_sync.call_b24("crm.deal.update", {
            "id": did,
            "fields": {
                "STAGE_ID": "UC_7F1F83" # 4 смена
            }
        })
        b24_sync.call_b24("crm.timeline.comment.add", {
            "fields": {
                "ENTITY_ID": did,
                "ENTITY_TYPE": "deal",
                "COMMENT": f"⭐ [МАКС ЧАТ: {facility}]: Бригадир {sender_name} подтвердил: кандидат отработал 4 смену! Сделка переведена в [4 смена]."
            }
        })
        print(f"[MAX STATUS: {facility}] Сделка #{did}: ПЕРЕВЕДЕНА В [4 СМЕНА]", flush=True)
        return

    # --- СЦЕНАРИЙ Е: 5 СМЕНА / ОПЛАЧЕН 5 СМЕН ---
    if intent == "SHIFT_5":
        b24_sync.call_b24("crm.deal.update", {
            "id": did,
            "fields": {
                "STAGE_ID": "UC_HRXHA7" # 5 смена
            }
        })
        b24_sync.call_b24("crm.timeline.comment.add", {
            "fields": {
                "ENTITY_ID": did,
                "ENTITY_TYPE": "deal",
                "COMMENT": f"🏆 [МАКС ЧАТ: {facility}]: Бригадир {sender_name} подтвердил: кандидат отработал 5 смен! Сделка переведена в [5 смена]."
            }
        })
        print(f"[MAX STATUS: {facility}] Сделка #{did}: ПЕРЕВЕДЕНА В [5 СМЕНА]", flush=True)
        return
    if intent == "SHIFT_5":
        b24_sync.call_b24("crm.deal.update", {
            "id": did,
            "fields": {
                "STAGE_ID": "UC_HRXHA7" # 5 смена
            }
        })
        b24_sync.call_b24("crm.timeline.comment.add", {
            "fields": {
                "ENTITY_ID": did,
                "ENTITY_TYPE": "deal",
                "COMMENT": f"🏆 [МАКС ЧАТ ОБЪЕКТА]: Бригадир {sender_name} подтвердил: кандидат отработал 5 смен! Сделка переведена в [5 смена]."
            }
        })
        print(f"[MAX STATUS] Сделка #{did}: ПЕРЕВЕДЕНА В [5 СМЕНА]", flush=True)
        return


# =============================================================================
# 3. ОСНОВНОЙ ЦИКЛ ОПРОСА API МАКС
# =============================================================================
def run_max_bot_loop():
    # ВРЕМЕННО ОТКЛЮЧЕНО ПО УКАЗАНИЮ РУКОВОДСТВА
    if os.environ.get("ENABLE_MAX_BOT", "1").lower() not in ("true", "1", "yes"):
        print("⏸ [STANDBY] МАКС-бот временно отключен по указанию руководства.", flush=True)
        while True:
            time.sleep(3600)
    print("==================================================", flush=True)
    print("🚀 ЗАПУСК СЛУЖБЫ ЧАТ-БОТА МАКС И СВЯЗКИ С БИТРИКС24", flush=True)
    print("Ссылка на бота: https://max.ru/id9729371578_bot", flush=True)
    print("==================================================", flush=True)

    state = load_state()
    marker = state.get("marker")

    while True:
        try:
            params = {"timeout": 25}
            if marker is not None:
                params["marker"] = marker

            resp = requests.get(
                f"{MAX_API_BASE}/updates",
                params=params,
                headers=HEADERS,
                verify=False,
                timeout=35
            )

            if resp.status_code == 200:
                data = resp.json()
                updates = data.get("updates", [])
                marker = data.get("marker", marker)
                state["marker"] = marker
                save_state(state)

                for upd in updates:
                    msg = upd.get("message") or {}
                    raw_body = msg.get("body") or msg.get("text") or ""
                    if isinstance(raw_body, dict):
                        body = raw_body.get("text") or raw_body.get("body") or ""
                    else:
                        body = str(raw_body or "")

                    attachments = msg.get("attachments") or []
                    link = msg.get("link") or {}

                    sender = msg.get("sender") or {}
                    user_id = sender.get("user_id")
                    first_name = sender.get("first_name", "")
                    last_name = sender.get("last_name", "")
                    sender_name = f"{first_name} {last_name}".strip()

                    chat_id = msg.get("chat_id")

                    # Личный диалог с соискателем в боте
                    if user_id and not chat_id:
                        print(f"[MAX DIRECT] {sender_name} (ID {user_id}): {body} (Вложений: {len(attachments)})", flush=True)
                        try:
                            handle_direct_dialog(user_id, body, attachments, state)
                        except Exception as e:
                            print(f"[MAX DIRECT ERROR] {e}\n{traceback.format_exc()}", flush=True)

                    # Групповой чат с менеджерами объектов / бригадирами
                    elif chat_id:
                        print(f"[MAX GROUP CHAT {chat_id}] {sender_name}: {body}", flush=True)
                        try:
                            handle_group_chat_message(str(chat_id), sender_name, body, attachments, link, state)
                        except Exception as e:
                            print(f"[MAX GROUP ERROR] {e}\n{traceback.format_exc()}", flush=True)

            elif resp.status_code == 401:
                print("[MAX BOT ERROR] Неверный токен авторизации!", flush=True)
                time.sleep(10)
            else:
                time.sleep(2)

        except requests.exceptions.Timeout:
            continue
        except Exception as e:
            print(f"[MAX BOT ERROR] {e}\n{traceback.format_exc()}", flush=True)
            time.sleep(3)

if __name__ == "__main__":
    run_max_bot_loop()
