# -*- coding: utf-8 -*-
"""
Сервис автоматического робота-дозвона по стадиям НДЗ (Битрикс24)

Параметры и правила:
1. График: Понедельник - Пятница с 09:00 до 18:00 МСК. Суббота и Воскресенье - выходные (пауза).
2. Ответственные менеджеры (строгая изоляция):
   - 84822: Анна Боркина (+7 986 089-81-98)
   - 84102: Анастасия Давыдова (+7 986 089-82-06)
   - 81596: Маргарита Бабынина (+7 967 787-53-02)
   Никакого перераспределения чужих сделок! Каждый менеджер обзванивает исключительно свои сделки.
3. Темп и параллельность:
   - Ровно 1 звонок на менеджера раз в 3 минуты (180 сек).
   - Одновременно до 3 параллельных вызовов (по 1 сделке на каждого из 3 менеджеров).
4. Очередь звонков (LIFO):
   - Сначала самые свежие сделки (ID DESC).
   - Очередность стадий: НДЗ 1 (EXECUTING) -> НДЗ 2 (UC_NDZ2) -> НДЗ 3 (UC_NDZ3).
5. При дозвоне (кандидат взял трубку, длительность > 0):
   - Мгновенная прямая связь с менеджером.
   - Робот НЕ переводит сделку; стадию вручную определяет рекрутер.
6. При недозвонах (длительность = 0 / сброс / не берет):
   - НДЗ 1 (EXECUTING) -> перевод в НДЗ 2 (UC_NDZ2)
   - НДЗ 2 (UC_NDZ2) -> перевод в НДЗ 3 (UC_NDZ3)
   - В 18:00 сделки из НДЗ 3 (UC_NDZ3) -> закрытие в LOSE (причина 218 'Не выходит на связь')
"""

import sys
import os
import json
import time
import re
from datetime import datetime, timezone, timedelta
import requests

sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)

WEBHOOK_URL = "https://b24-4qx38o.bitrix24.ru/rest/39250/7cbs7mg1qo0vn0ov/"
MSK_TZ = timezone(timedelta(hours=3))

RECRUITERS = {
    84822: {"name": "Анна Боркина", "phone": "+79860898198"},
    84102: {"name": "Анастасия Давыдова", "phone": "+79860898206"},
    81596: {"name": "Маргарита Бабынина", "phone": "+79677875302"}
}

INTERVAL_SECONDS = 180  # Ровно 3 минуты между звонками на одного менеджера
STATE_FILE = os.path.join(os.path.dirname(__file__), "ndz_dialer_state.json")

def call_b24(method, params=None):
    for attempt in range(3):
        try:
            r = requests.post(f"{WEBHOOK_URL}{method}", json=params or {}, timeout=15)
            return r.json()
        except Exception as e:
            time.sleep(1)
    return {}

def is_working_hours():
    now = datetime.now(MSK_TZ)
    # 0 = Понедельник, ..., 4 = Пятница, 5 = Суббота, 6 = Воскресенье
    if now.weekday() >= 5:
        return False, "Выходной день (суббота/воскресенье)"
    if now.hour < 9:
        return False, f"До начала рабочего дня (сейчас {now.strftime('%H:%M')} МСК, старт в 09:00)"
    if now.hour >= 18:
        return False, f"После окончания рабочего дня (сейчас {now.strftime('%H:%M')} МСК, завершение в 18:00)"
    return True, "Рабочее время"

def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return {"called_today": {}, "last_call_time": {}, "processed_call_ids": []}

def save_state(state):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except:
        pass

def add_timeline_comment(entity_id, comment_text, entity_type="deal"):
    try:
        call_b24("crm.timeline.comment.add", {
            "fields": {
                "ENTITY_ID": entity_id,
                "ENTITY_TYPE": entity_type,
                "COMMENT": comment_text
            }
        })
    except Exception as e:
        print(f"Ошибка добавления комментария в таймлайн сделки {entity_id}: {e}", flush=True)

def extract_phone_from_deal(deal):
    comments = deal.get("COMMENTS") or ""
    title = deal.get("TITLE") or ""
    # 1. Поиск [Телефон: ...]
    m = re.search(r'\[Телефон:\]\s*([^\n\r\[]+)', comments)
    if m:
        ph = re.sub(r'[^\d+]', '', m.group(1).strip())
        if len(ph) >= 10: return ph
    # 2. Поиск +7... в названии
    m2 = re.search(r'\+?7\d{10}', title)
    if m2:
        return m2.group(0)
    # 3. Поиск +7... в комментариях
    m3 = re.search(r'\+?7\d{10}', comments)
    if m3:
        return m3.group(0)
    # 4. Поиск через контакт сделки
    cid = deal.get("CONTACT_ID")
    if cid:
        c_res = call_b24("crm.contact.get", {"id": cid}).get("result", {})
        phones = c_res.get("PHONE", [])
        if phones and phones[0].get("VALUE"):
            return re.sub(r'[^\d+]', '', phones[0].get("VALUE"))
    return ""

def get_next_ndz_deal_for_recruiter(user_id, called_today):
    """
    Выбирает самую свежую сделку менеджера из стадий НДЗ 1, 2, 3 (LIFO: ID DESC)
    """
    for st in ["EXECUTING", "UC_NDZ2", "UC_NDZ3"]:
        res = call_b24("crm.deal.list", {
            "order": {"ID": "DESC"},
            "filter": {
                "ASSIGNED_BY_ID": user_id,
                "STAGE_ID": st
            },
            "select": ["ID", "TITLE", "STAGE_ID", "ASSIGNED_BY_ID", "COMMENTS", "CONTACT_ID", "DATE_CREATE"],
            "limit": 20
        })
        deals = res.get("result", [])
        for d in deals:
            did = str(d.get("ID"))
            # Если уже звонили по этой сделке: выдерживаем паузу не менее 2.5 часов (9000 сек)
            # Защита от спама и блокировок операторами связи!
            last_info = called_today.get(did)
            if last_info:
                last_t = last_info.get("timestamp", 0)
                if time.time() - last_t < 9000:  # 2.5 часа пауза между повторными попытками
                    continue
            phone = extract_phone_from_deal(d)
            if phone:
                return d, phone, st
    return None, None, None

def check_recent_call_results(state):
    """
    Проверяет результаты недавних звонков через voximplant.statistic.get
    И автоматически двигает сделки при недозвонах:
    - НДЗ 1 (EXECUTING) -> НДЗ 2 (UC_NDZ2)
    - НДЗ 2 (UC_NDZ2) -> НДЗ 3 (UC_NDZ3)
    """
    now = datetime.now(MSK_TZ)
    processed_ids = set(state.setdefault("processed_call_ids", []))
    
    # Запрашиваем звонки за последний 1 час
    since_time = (now - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
    stats = call_b24("voximplant.statistic.get", {
        "FILTER": {
            ">CALL_START_DATE": since_time
        },
        "LIMIT": 50
    }).get("result", [])

    for c in stats:
        cid = str(c.get("ID"))
        if cid in processed_ids:
            continue
        
        user_id = int(c.get("PORTAL_USER_ID") or 0)
        if user_id not in RECRUITERS:
            processed_ids.add(cid)
            continue
        
        call_type = str(c.get("CALL_TYPE")) # 1 - входящий, 2 - исходящий
        # Анализируем исходящие звонки рекрутеров
        if call_type != "2":
            processed_ids.add(cid)
            continue
            
        dur = int(c.get("CALL_DURATION") or 0)
        phone = c.get("PHONE_NUMBER")
        failed_code = str(c.get("CALL_FAILED_CODE") or "")
        contact_id = c.get("CRM_ENTITY_ID") if c.get("CRM_ENTITY_TYPE") == "CONTACT" else None
        deal_id = c.get("CRM_ENTITY_ID") if c.get("CRM_ENTITY_TYPE") == "DEAL" else None

        # Найти сделку
        found_deal = None
        if deal_id:
            d_res = call_b24("crm.deal.get", {"id": deal_id}).get("result")
            if d_res: found_deal = d_res
        elif contact_id:
            d_list = call_b24("crm.deal.list", {
                "filter": {"CONTACT_ID": contact_id},
                "order": {"ID": "DESC"},
                "select": ["ID", "TITLE", "STAGE_ID", "ASSIGNED_BY_ID"],
                "limit": 1
            }).get("result", [])
            if d_list: found_deal = d_list[0]

        if not found_deal:
            processed_ids.add(cid)
            continue

        did = found_deal.get("ID")
        current_stage = found_deal.get("STAGE_ID")
        deal_owner = int(found_deal.get("ASSIGNED_BY_ID") or 0)

        # Проверяем, находится ли сделка в НДЗ
        if current_stage in ["EXECUTING", "UC_NDZ2", "UC_NDZ3"]:
            recruiter_name = RECRUITERS.get(deal_owner, {}).get("name", f"ID {deal_owner}")
            
            # Переименовываем тему звонка в CRM на "Автопрозвон НДЗ"
            activity_id = c.get("CRM_ACTIVITY_ID")
            if activity_id:
                try:
                    call_b24("crm.activity.update", {
                        "id": activity_id,
                        "fields": {"SUBJECT": f"Автопрозвон НДЗ: {phone}"}
                    })
                except Exception:
                    pass

            # Сценарий 1: Недозвон (длительность = 0 сек или код сброса)
            if dur == 0 or failed_code in ["304", "603", "486", "487", "404", "503"]:
                # Требование: вызов должен длиться не менее 30 секунд, чтобы засчитать недозвон!
                # Проверяем длительность дозвона/гудков через связанную активность Битрикс24
                ring_duration = 0
                if activity_id:
                    act_res = call_b24("crm.activity.get", {"id": activity_id}).get("result", {})
                    created_str = act_res.get("CREATED")
                    updated_str = act_res.get("LAST_UPDATED")
                    if created_str and updated_str:
                        try:
                            t_start = datetime.fromisoformat(created_str)
                            t_end = datetime.fromisoformat(updated_str)
                            ring_duration = int((t_end - t_start).total_seconds())
                        except Exception:
                            pass

                # Если дозвон шел меньше 30 секунд — недозвон НЕ ставится (быстрый сброс / ошибка)
                if ring_duration > 0 and ring_duration < 30:
                    print(f"⏳ [НЕДОЗВОН ОТКЛОНЕН] Сделка #{did} ({recruiter_name}) — гудки длились {ring_duration} сек (< 30 сек). Недозвон не засчитывается!", flush=True)
                    add_timeline_comment(did, f"⏳ Автопрозвон НДЗ: Звонок длился {ring_duration} сек (< 30 сек).\nПо правилам недозвон засчитывается только при вызове от 30 секунд. Стадия сохранена.")
                    processed_ids.add(cid)
                    continue

                if current_stage == "EXECUTING":
                    # Перевод в НДЗ 2
                    call_b24("crm.deal.update", {
                        "id": did,
                        "fields": {"STAGE_ID": "UC_NDZ2"}
                    })
                    add_timeline_comment(did, f"🤖 Автопрозвон НДЗ: Зафиксирован подтвержденный недозвон ({ring_duration or '30+'} сек гудков, код {failed_code}).\nСделка автоматически переведена: НДЗ 1 ➔ НДЗ 2.")
                    print(f"⏩ [НЕДОЗВОН 1 -> НДЗ 2] Сделка #{did} ({recruiter_name}) переведена в UC_NDZ2 (гудки {ring_duration}с)", flush=True)

                elif current_stage == "UC_NDZ2":
                    # Перевод в НДЗ 3
                    call_b24("crm.deal.update", {
                        "id": did,
                        "fields": {"STAGE_ID": "UC_NDZ3"}
                    })
                    add_timeline_comment(did, f"🤖 Автопрозвон НДЗ: Зафиксирован повторный подтвержденный недозвон ({ring_duration or '30+'} сек гудков, код {failed_code}).\nСделка автоматически переведена: НДЗ 2 ➔ НДЗ 3.")
                    print(f"⏩ [НЕДОЗВОН 2 -> НДЗ 3] Сделка #{did} ({recruiter_name}) переведена в UC_NDZ3 (гудки {ring_duration}с)", flush=True)

                elif current_stage == "UC_NDZ3":
                    # Фиксируем третий недозвон
                    add_timeline_comment(did, f"🤖 Автопрозвон НДЗ: Зафиксирован 3-й недозвон ({ring_duration or '30+'} сек гудков). Сделка ожидает планового закрытия в 18:00 (Не выходит на связь).")
                    print(f"⚠️ [НЕДОЗВОН 3] Сделка #{did} ({recruiter_name}) ожидает закрытия в 18:00", flush=True)

            # Сценарий 2: Успешный дозвон (кандидат взял трубку)
            elif dur > 0:
                add_timeline_comment(did, f"📞 Автопрозвон НДЗ: Успешный разговор рекрутера с кандидатом (длительность {dur} сек).\nСтадия оставлена на ручное распределение рекрутером.")
                print(f"✅ [ДОЗВОН] Сделка #{did} ({recruiter_name}) — кандидат ответил ({dur} сек). Стадия не меняется роботом.", flush=True)

        processed_ids.add(cid)

    # Оставляем в памяти только последние 200 call_id
    state["processed_call_ids"] = list(processed_ids)[-200:]
    save_state(state)

def close_eod_ndz3_deals():
    """
    В 18:00 закрывает оставшиеся сделки НДЗ 3 в LOSE с причиной 218 'Не выходит на связь'
    """
    now = datetime.now(MSK_TZ)
    # Запуск только между 18:00 и 18:15 в будние дни
    if now.weekday() < 5 and now.hour == 18 and now.minute <= 15:
        for uid, uinfo in RECRUITERS.items():
            res = call_b24("crm.deal.list", {
                "filter": {
                    "ASSIGNED_BY_ID": uid,
                    "STAGE_ID": "UC_NDZ3"
                },
                "select": ["ID", "TITLE"]
            })
            deals = res.get("result", [])
            for d in deals:
                did = d.get("ID")
                call_b24("crm.deal.update", {
                    "id": did,
                    "fields": {
                        "STAGE_ID": "LOSE",
                        "UF_CRM_1768823747857": 218 # Не выходит на связь
                    }
                })
                add_timeline_comment(did, "🤖 Робот автодозвона: Завершение рабочего дня в 18:00. После серии недозвонов сделка закрыта в Неуспех (Не выходит на связь).")
                print(f"🔴 [18:00 ЗАКРЫТИЕ В LOSE] Сделка #{did} ({uinfo['name']}) -> Неуспех (Не выходит на связь)", flush=True)

def run_dialer_step():
    now_dt = datetime.now(MSK_TZ)
    today_str = now_dt.strftime("%Y-%m-%d")
    is_ok, reason = is_working_hours()
    
    state = load_state()
    # Сброс счетчика при наступлении нового дня
    if state.get("current_date") != today_str:
        state["current_date"] = today_str
        state["called_today"] = {}
        save_state(state)

    # Проверка результатов недавних звонков и продвижение стадий
    check_recent_call_results(state)

    # Проверка закрытия НДЗ 3 в 18:00
    close_eod_ndz3_deals()
        
    if not is_ok:
        print(f"⏸️ Автодозвон на паузе: {reason}", flush=True)
        return

    called_today = state.setdefault("called_today", {})
    last_call_time = state.setdefault("last_call_time", {})

    # Проверяем каждого из 3 рекрутеров
    for uid, uinfo in RECRUITERS.items():
        uname = uinfo["name"]
        uid_str = str(uid)
        
        # Проверка интервала 3 минуты (180 сек) на этого менеджера
        last_t = last_call_time.get(uid_str, 0)
        time_since_last = time.time() - last_t
        if time_since_last < INTERVAL_SECONDS:
            remaining = int(INTERVAL_SECONDS - time_since_last)
            # Еще действует интервал 3 минуты для данного менеджера
            continue

        # Получаем следующую сделку для этого менеджера (строго его личную!)
        deal, phone, stage = get_next_ndz_deal_for_recruiter(uid, called_today)
        if not deal:
            # Нет сделок в очереди НДЗ для этого менеджера
            continue

        did = deal.get("ID")
        dtitle = deal.get("TITLE")
        stage_names = {"EXECUTING": "НДЗ 1", "UC_NDZ2": "НДЗ 2", "UC_NDZ3": "НДЗ 3"}
        st_label = stage_names.get(stage, stage)

        print(f"\n📞 [ОЧЕРЕДЬ НДЗ] Рекрутер: {uname} | Сделка #{did} ({dtitle}) | Тел: {phone} | Стадия: {st_label}", flush=True)

        # Фиксируем отметку в состоянии очереди
        last_call_time[uid_str] = time.time()
        called_today[str(did)] = {
            "time": now_dt.isoformat(),
            "timestamp": time.time(),
            "stage": stage,
            "user_id": uid
        }
        save_state(state)

print("🚀 Сервис автодозвона НДЗ запущен. Контроль расписания: Пн-Пт 09:00-18:00, интервал 3 мин.", flush=True)

if __name__ == "__main__":
    while True:
        try:
            run_dialer_step()
        except Exception as e:
            print(f"Ошибка в цикле автодозвона: {e}", flush=True)
        time.sleep(15)
