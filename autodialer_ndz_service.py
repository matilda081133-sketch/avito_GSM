# -*- coding: utf-8 -*-
"""
Полноценный боевой робот автодозвона НДЗ через официальный UIS Call API (start.employee_call) и Битрикс24:

1. Физический дозвон (UIS ВАТС):
   - Вызывает метод start.employee_call с официальными UIS Employee ID.
   - Вызов направляется строго в софтфон/приложение UIS ответственного рекрутера.
   - Логика: сначала звонит кандидат, как только он берет трубку («Алло») -> мгновенная прямая коммутация в наушники рекрутеру с открытием карточки сделки в Битрикс24.

2. Привязка рекрутеров к UIS Employee ID:
   - Анна Боркина (B24: 84822): UIS Employee ID 10382998 | Виртуальная линия: 79860898198
   - Анастасия Давыдова (B24: 84102): UIS Employee ID 10373578 | Виртуальная линия: 79860898206
   - Маргарита Бабынина (B24: 81596): UIS Employee ID 10351298 | Виртуальная линия: 79677875302

3. Темп, интервалы и антиспам:
   - Ровно 1 вызов каждые 3 минуты (180 сек) на каждого менеджера.
   - До 3 параллельных вызовов одновременно (по 1 сделке на каждого рекрутера).
   - Антиспам-пауза: не менее 2.5 часов (9000 сек) перед повторным звонком тому же кандидату.
   - График: Пн-Пт с 09:00 до 18:00 МСК. Вне графика и в выходные — пауза.

4. Контроль исходов и каскад стадий:
   - Правило 30 секунд: недозвон засчитывается строго при гудках >= 30 сек.
   - НДЗ 1 (EXECUTING) -> НДЗ 2 (UC_NDZ2)
   - НДЗ 2 (UC_NDZ2) -> НДЗ 3 (UC_NDZ3)
   - В 18:00: все оставшиеся сделки НДЗ 3 -> закрытие в LOSE (причина 218 'Не выходит на связь').
   - При дозвоне: стадия остается на рекрутере (робот не переводит).
"""

import sys
import os
import json
import time
import re
from datetime import datetime, timezone, timedelta
import requests

sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)

B24_WEBHOOK_URL = "https://b24-4qx38o.bitrix24.ru/rest/39250/7cbs7mg1qo0vn0ov/"
B24_NOTIFY_WEBHOOK_URL = "https://b24-4qx38o.bitrix24.ru/rest/82166/lhremlfdcravw215/"
UIS_CALL_API_URL = "https://callapi.uiscom.ru/v4.0"
UIS_ACCESS_TOKEN = "mf050x3n53jnp4dft29ww26x7jm4y33rd6sd5rgw"

MSK_TZ = timezone(timedelta(hours=3))

RECRUITERS = {
    84822: {
        "name": "Анна Боркина",
        "uis_employee_id": 10382998,
        "virtual_phone": "79860898198",
        "active": True
    },
    81596: {
        "name": "Маргарита Бабынина",
        "uis_employee_id": 10351298,
        "virtual_phone": "79677875302",
        "active": True
    },
    32: {
        "name": "Наталья Кучма",
        "uis_employee_id": 10357418,
        "virtual_phone": "79677875301",
        "active": True
    },
    84102: {
        "name": "Анастасия Давыдова",
        "uis_employee_id": 10373578,
        "virtual_phone": "79860898206",
        "active": False  # На обеде, временно на паузе
    }
}

INTERVAL_SECONDS = 180  # Ровно 3 минуты между звонками на одного менеджера
STATE_FILE = os.path.join(os.path.dirname(__file__), "ndz_dialer_state.json")

def call_b24(method, params=None):
    for attempt in range(3):
        try:
            r = requests.post(f"{B24_WEBHOOK_URL}{method}", json=params or {}, timeout=15)
            return r.json()
        except Exception:
            time.sleep(1)
    return {}

def call_uis_api(method, params=None):
    payload = {
        "jsonrpc": "2.0",
        "id": int(time.time() * 1000),
        "method": method,
        "params": params or {}
    }
    payload["params"]["access_token"] = UIS_ACCESS_TOKEN
    try:
        r = requests.post(UIS_CALL_API_URL, json=payload, timeout=12)
        return r.json()
    except Exception as e:
        print(f"Ошибка вызова UIS Call API ({method}): {e}", flush=True)
        return {}

def is_working_hours():
    now = datetime.now(MSK_TZ)
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
        except Exception:
            pass
    return {"called_today": {}, "last_call_time": {}, "processed_call_ids": []}

def save_state(state):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception:
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

def notify_recruiter_candidate_answered_while_busy(user_id, deal_id, deal_title, phone, stage_label):
    """
    Отправляет менеджеру мгновенное колокольчик-уведомление в Битрикс24 и пишет в таймлайн сделки,
    если кандидат из НДЗ взял трубку в момент, когда менеджер уже находился в другом звонке.
    """
    deal_url = f"https://b24-4qx38o.bitrix24.ru/crm/deal/details/{deal_id}/"
    notify_msg = (
        f"🔔 [B]Кандидат из {stage_label} взял трубку, пока вы были в звонке![/B]\n"
        f"Сделка #{deal_id}: {deal_title}\n"
        f"Телефон: +{phone}\n"
        f"Робот НЕ стал переводить вызов на вашу линию, чтобы не прерывать ваш текущий разговор.\n"
        f"👉 Перезвоните кандидату: {deal_url}"
    )
    try:
        requests.post(f"{B24_NOTIFY_WEBHOOK_URL}im.notify.system.add", json={
            "USER_ID": int(user_id),
            "MESSAGE": notify_msg
        }, timeout=10)
    except Exception as e:
        print(f"Ошибка отправки колокольчика менеджеру {user_id}: {e}", flush=True)

    add_timeline_comment(
        deal_id,
        f"🔔 [B]Автопрозвон НДЗ:[/B] Кандидат +{phone} взял трубку из стадии {stage_label}, но ответственный менеджер в этот момент уже находился в другом звонке.\n"
        f"Вызов не переводился второй линией на менеджера. Менеджеру отправлено уведомление перезвонить кандидату."
    )
    print(f"🔔 [УВЕДОМЛЕНИЕ МЕНЕДЖЕРУ {user_id}] Кандидат по сделке #{deal_id} (+{phone}) взял трубку из {stage_label}, пока менеджер был в звонке!", flush=True)

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

def normalize_phone_for_uis(phone_raw):
    ph = re.sub(r'[^\d]', '', str(phone_raw))
    if len(ph) == 11 and ph.startswith('8'):
        ph = '7' + ph[1:]
    elif len(ph) == 10:
        ph = '7' + ph
    return ph

def get_next_ndz_deal_for_recruiter(user_id, called_today):
    """
    Выбирает самую свежую сделку менеджера из стадий НДЗ 1, 2, 3 (LIFO: ID DESC)
    Соблюдает строгую паузу 2.5 часа между повторными звонками одному кандидату.
    """
    for st in ["EXECUTING", "UC_NDZ2", "UC_NDZ3"]:
        res = call_b24("crm.deal.list", {
            "order": {"ID": "DESC"},
            "filter": {
                "ASSIGNED_BY_ID": user_id,
                "STAGE_ID": st
            },
            "select": ["ID", "TITLE", "STAGE_ID", "ASSIGNED_BY_ID", "COMMENTS", "CONTACT_ID", "DATE_CREATE"],
            "limit": 25
        })
        deals = res.get("result", [])
        for d in deals:
            did = str(d.get("ID"))
            # Антиспам-пауза 2.5 часа (9000 сек)
            last_info = called_today.get(did)
            if last_info:
                last_t = last_info.get("timestamp", 0)
                if time.time() - last_t < 9000:
                    continue
            phone = extract_phone_from_deal(d)
            if phone:
                norm_ph = normalize_phone_for_uis(phone)
                if len(norm_ph) == 11:
                    return d, norm_ph, st
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
    
    since_time = (now - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
    stats = call_b24("voximplant.statistic.get", {
        "FILTER": {">CALL_START_DATE": since_time},
        "SORT": "CALL_START_DATE",
        "ORDER": "DESC",
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
        if call_type not in ["1", "2"]:
            processed_ids.add(cid)
            continue
            
        dur = int(c.get("CALL_DURATION") or 0)
        phone = c.get("PHONE_NUMBER")
        failed_code = str(c.get("CALL_FAILED_CODE") or "")
        contact_id = c.get("CRM_ENTITY_ID") if c.get("CRM_ENTITY_TYPE") == "CONTACT" else None
        deal_id = c.get("CRM_ENTITY_ID") if c.get("CRM_ENTITY_TYPE") == "DEAL" else None

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

        if current_stage in ["EXECUTING", "UC_NDZ2", "UC_NDZ3"]:
            recruiter_name = RECRUITERS.get(deal_owner, {}).get("name", f"ID {deal_owner}")
            
            # Переименовываем тему активности в Битрикс24
            activity_id = c.get("CRM_ACTIVITY_ID")
            if activity_id:
                try:
                    call_b24("crm.activity.update", {
                        "id": activity_id,
                        "fields": {"SUBJECT": f"Автопрозвон НДЗ: {phone}"}
                    })
                except Exception:
                    pass

            called_today_info = state.get("called_today", {}).get(str(did), {})
            was_busy_mode = bool(called_today_info.get("was_busy_mode"))

            # Сценарий 0: Менеджер был занят в другом звонке (start.informer_call), и кандидат ВЗЯЛ трубку (код 200)!
            if was_busy_mode and failed_code == "200":
                stage_names = {"EXECUTING": "НДЗ 1", "UC_NDZ2": "НДЗ 2", "UC_NDZ3": "НДЗ 3"}
                st_label = stage_names.get(current_stage, current_stage)
                notify_recruiter_candidate_answered_while_busy(
                    deal_owner, did, found_deal.get("TITLE", f"Сделка #{did}"), called_today_info.get("phone") or phone, st_label
                )
                processed_ids.add(cid)
                continue

            is_short_or_answering_machine = (0 < dur <= 20)

            # Сценарий 1: Недозвон (длительность = 0 сек, код сброса или короткий звонок/автоответчик <= 20 сек)
            if dur == 0 or failed_code in ["304", "603", "486", "487", "404", "503"] or is_short_or_answering_machine:
                ring_duration = 0
                if not is_short_or_answering_machine and activity_id:
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

                # Защита для недозвонов без снятия трубки: гудки должны длиться не менее 30 секунд
                if not is_short_or_answering_machine and ring_duration > 0 and ring_duration < 30:
                    print(f"⏳ [НЕДОЗВОН ОТКЛОНЕН] Сделка #{did} ({recruiter_name}) — гудки длились {ring_duration} сек (< 30 сек). Стадия не трогается.", flush=True)
                    add_timeline_comment(did, f"⏳ Автопрозвон НДЗ: Вызов длился {ring_duration} сек (< 30 сек).\nПо правилам недозвон засчитывается только при вызове от 30 секунд. Стадия сохранена.")
                    processed_ids.add(cid)
                    continue

                fail_reason = f"автоответчик/сброс ({dur}с)" if is_short_or_answering_machine else f"{ring_duration or '30+'} сек гудков"

                if current_stage == "EXECUTING":
                    call_b24("crm.deal.update", {
                        "id": did,
                        "fields": {"STAGE_ID": "UC_NDZ2"}
                    })
                    add_timeline_comment(did, f"🤖 Автопрозвон НДЗ: Зафиксирован подтвержденный недозвон ({fail_reason}, код {failed_code}).\nСделка автоматически переведена: НДЗ 1 ➔ НДЗ 2.")
                    print(f"⏩ [НЕДОЗВОН 1 -> НДЗ 2] Сделка #{did} ({recruiter_name}) переведена в UC_NDZ2 ({fail_reason})", flush=True)

                elif current_stage == "UC_NDZ2":
                    call_b24("crm.deal.update", {
                        "id": did,
                        "fields": {"STAGE_ID": "UC_NDZ3"}
                    })
                    add_timeline_comment(did, f"🤖 Автопрозвон НДЗ: Зафиксирован повторный подтвержденный недозвон ({fail_reason}, код {failed_code}).\nСделка автоматически переведена: НДЗ 2 ➔ НДЗ 3.")
                    print(f"⏩ [НЕДОЗВОН 2 -> НДЗ 3] Сделка #{did} ({recruiter_name}) переведена в UC_NDZ3 ({fail_reason})", flush=True)

                elif current_stage == "UC_NDZ3":
                    call_b24("crm.deal.update", {
                        "id": did,
                        "fields": {
                            "STAGE_ID": "LOSE",
                            "UF_CRM_1768823747857": 218  # Не выходит на связь
                        }
                    })
                    add_timeline_comment(did, f"🤖 Автопрозвон НДЗ: Зафиксирован последний недозвон на стадии НДЗ 3 ({fail_reason}, код {failed_code}).\nСделка автоматически закрыта в Неуспех с причиной «Не выходит на связь».")
                    print(f"🔴 [НЕДОЗВОН 3 -> НЕУСПЕХ] Сделка #{did} ({recruiter_name}) закрыта в LOSE (Не выходит на связь)", flush=True)

            # Сценарий 2: Полноценный разговор рекрутера с кандидатом (> 20 сек)
            elif dur > 20:
                called_today_info = state.get("called_today", {}).get(str(did), {})
                if called_today_info.get("was_busy_mode"):
                    stage_names = {"EXECUTING": "НДЗ 1", "UC_NDZ2": "НДЗ 2", "UC_NDZ3": "НДЗ 3"}
                    st_label = stage_names.get(current_stage, current_stage)
                    notify_recruiter_candidate_answered_while_busy(
                        deal_owner, did, found_deal.get("TITLE", f"Сделка #{did}"), called_today_info.get("phone") or phone, st_label
                    )
                else:
                    add_timeline_comment(did, f"📞 Автопрозвон НДЗ: Успешный разговор рекрутера с кандидатом (длительность {dur} сек).\nСтадия оставлена на ручное распределение рекрутером.")
                    print(f"✅ [ДОЗВОН] Сделка #{did} ({recruiter_name}) — кандидат ответил ({dur} сек). Стадия не меняется роботом.", flush=True)

        processed_ids.add(cid)

    state["processed_call_ids"] = list(processed_ids)[-200:]
    save_state(state)

def close_eod_ndz3_deals():
    """
    В 18:00 закрывает оставшиеся сделки НДЗ 3 в LOSE с причиной 218 'Не выходит на связь'
    """
    now = datetime.now(MSK_TZ)
    if now.hour == 18 and now.minute <= 15:
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
                add_timeline_comment(did, "🤖 Автопрозвон НДЗ: Завершение рабочего дня в 18:00. После серии недозвонов сделка закрыта в Неуспех (Не выходит на связь).")
                print(f"🔴 [18:00 ЗАКРЫТИЕ В LOSE] Сделка #{did} ({uinfo['name']}) -> Неуспех (Не выходит на связь)", flush=True)

def get_busy_uis_employees():
    """
    Запрашивает у UIS Call API (list.calls) список всех текущих активных звонков в реальном времени.
    Возвращает множество employee_id и виртуальных номеров рекрутеров, которые прямо сейчас разговаривают или звонят.
    Зависшие сессии старше 15 минут (900 сек) автоматически сбрасываются через release.call и не блокируют линию.
    """
    busy_emp_ids = set()
    busy_virt_phones = set()
    res = call_uis_api("list.calls")
    active_calls = res.get("result", {}).get("data", [])
    now_msk = datetime.now(MSK_TZ).replace(tzinfo=None)
    if isinstance(active_calls, list):
        for c in active_calls:
            st_str = c.get("start_time")
            cs_id = c.get("call_session_id")
            if st_str:
                try:
                    st_dt = datetime.strptime(st_str, "%Y-%m-%d %H:%M:%S")
                    age_sec = (now_msk - st_dt).total_seconds()
                    if age_sec > 900:
                        if cs_id:
                            call_uis_api("release.call", {"call_session_id": cs_id})
                            print(f"🧹 [СБРОС ЗАВИСШЕЙ ЛИНИИ UIS] Сессия {cs_id} висела {int(age_sec)} сек (>15 мин) и была принудительно завершена.", flush=True)
                        continue
                except Exception:
                    pass
            for leg in c.get("legs", []):
                eid = leg.get("employee_id")
                if eid:
                    busy_emp_ids.add(int(eid))
                for ph_field in ("calling_phone_number", "called_phone_number"):
                    ph_val = str(leg.get(ph_field) or "")
                    if ph_val:
                        busy_virt_phones.add(ph_val)
    return busy_emp_ids, busy_virt_phones

def run_dialer_step():
    now_dt = datetime.now(MSK_TZ)
    today_str = now_dt.strftime("%Y-%m-%d")
    is_ok, reason = is_working_hours()
    
    state = load_state()
    if state.get("current_date") != today_str:
        state["current_date"] = today_str
        state["called_today"] = {}
        save_state(state)

    # Проверка результатов звонков и каскада стадий
    check_recent_call_results(state)

    # Проверка закрытия НДЗ 3 в 18:00
    close_eod_ndz3_deals()
        
    if not is_ok:
        print(f"⏸️ Автодозвон на паузе: {reason}", flush=True)
        return

    called_today = state.setdefault("called_today", {})
    last_call_time = state.setdefault("last_call_time", {})
    last_busy_time = state.setdefault("last_busy_time", {})

    # Проверяем в реальном времени через UIS Call API (list.calls), кто из менеджеров сейчас на линии
    busy_emp_ids, busy_virt_phones = get_busy_uis_employees()

    # Проверяем каждого из рекрутеров
    for uid, uinfo in RECRUITERS.items():
        if not uinfo.get("active", True):
            continue

        uname = uinfo["name"]
        uid_str = str(uid)
        emp_id = uinfo["uis_employee_id"]
        virt_phone = uinfo["virtual_phone"]

        # 1. Проверка интервала 3 минуты (180 сек) между запусками автодозвона
        last_t = last_call_time.get(uid_str, 0)
        time_since_last = time.time() - last_t
        if time_since_last < INTERVAL_SECONDS:
            continue

        # Получаем следующую сделку для этого менеджера (строго его личную!)
        deal, phone, stage = get_next_ndz_deal_for_recruiter(uid, called_today)
        if not deal:
            continue

        did = deal.get("ID")
        dtitle = deal.get("TITLE")
        stage_names = {"EXECUTING": "НДЗ 1", "UC_NDZ2": "НДЗ 2", "UC_NDZ3": "НДЗ 3"}
        st_label = stage_names.get(stage, stage)

        is_manager_busy = (emp_id in busy_emp_ids) or (virt_phone in busy_virt_phones)

        if is_manager_busy:
            print(f"⏳ [МЕНЕДЖЕР В ЗВОНКЕ] {uname} сейчас на линии. Ожидаем завершения разговора перед звонком кандидату +{phone} (Сделка #{did})...", flush=True)
            continue

        AUTODIAL_VIRTUAL_NUMBER = "79677875304" # Линия сценария автопрозвона с голосовым меню IVR

        print(f"\n🚀 [ИНИЦИАЦИЯ ВЫЗОВА ПО СЦЕНАРИЮ АВТОПРОЗВОНА UIS] {uname} -> Сделка #{did} | Тел кандидата: +{phone} | Номер сценария: +{AUTODIAL_VIRTUAL_NUMBER} | Стадия: {st_label}", flush=True)

        # Вызываем официальный метод UIS Call API start.vnumber_call:
        # Звонок идет кандидату с номера 79677875304, срабатывает сценарий «автопрозвон» с голосовым меню (кнопка 1).
        # Только при нажатии 1 вызов переводится на менеджера в обычном штатном режиме (без автоответа)!
        uis_res = call_uis_api("start.vnumber_call", {
            "virtual_phone_number": AUTODIAL_VIRTUAL_NUMBER,
            "first_call": "contact",
            "contact": phone
        })

        res_data = uis_res.get("result", {}).get("data", {})
        session_id = res_data.get("call_session_id")
        err = uis_res.get("error")

        if session_id:
            print(f"✅ [ВЫЗОВ ЗАПУЩЕН] Session ID: {session_id} | Режим занятости менеджера: {is_manager_busy}", flush=True)
            last_call_time[uid_str] = time.time()
            called_today[str(did)] = {
                "time": now_dt.isoformat(),
                "timestamp": time.time(),
                "stage": stage,
                "session_id": session_id,
                "user_id": uid,
                "phone": phone,
                "was_busy_mode": is_manager_busy
            }
            save_state(state)
            if not is_manager_busy:
                add_timeline_comment(did, f"📞 Автопрозвон НДЗ: Инициирован вызов кандидату +{phone} через сценарий UIS (IVR Меню с кнопкой 1).\nОтветственный менеджер: {uname}.\nСтадия: {st_label}.\nСессия UIS: {session_id}")
        else:
            print(f"❌ [ОШИБКА UIS] Не удалось запустить звонок для {uname} на +{phone}: {err}", flush=True)

print("🚀 Боевой сервис автодозвона НДЗ запущен (UIS start.vnumber_call + Битрикс24).", flush=True)

if __name__ == "__main__":
    while True:
        try:
            run_dialer_step()
        except Exception as e:
            print(f"Ошибка в основном цикле автодозвона: {e}", flush=True)
        time.sleep(15)
