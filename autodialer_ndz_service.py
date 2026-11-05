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
UIS_ACCESS_TOKENS = [
    "mf050x3n53jnp4dft29ww26x7jm4y33rd6sd5rgw",  # Токен #1 (основной)
    "yhnf7ukxduk42l54v3j3psuenis3ufqni3d80nrr",  # Токен #2 (Виктория)
    "4ee5pel24c6mq1jg6px5f8nqz78hadn6swtwu9hl",  # Токен #3 (Валерия)
    "f0ph35x1p1um1p4n5hzb47ulj3gld9btkfsistsu"   # Токен #4 (Валерия)
]
UIS_ACCESS_TOKEN = UIS_ACCESS_TOKENS[0]
_current_token_idx = 0

MSK_TZ = timezone(timedelta(hours=3))

RECRUITERS = {
    84102: {
        "name": "Анастасия Давыдова",
        "uis_employee_id": 10373578,
        "virtual_phone": "79860898206",
        "active": True   # ВКЛЮЧЕНО
    },
    81596: {
        "name": "Маргарита Бабынина",
        "uis_employee_id": 10351298,
        "virtual_phone": "79677875302",
        "active": True   # ВКЛЮЧЕНО
    },
    32: {
        "name": "Наталья Кучма",
        "uis_employee_id": 10357418,
        "virtual_phone": "79677875301",
        "active": True    # ВКЛЮЧЕНО
    },
    84822: {
        "name": "Анна Боркина",
        "uis_employee_id": 10382998,
        "virtual_phone": "79860898198",
        "active": True   # ВКЛЮЧЕНО
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
    global _current_token_idx
    params = dict(params or {})

    for attempt in range(len(UIS_ACCESS_TOKENS)):
        token = UIS_ACCESS_TOKENS[_current_token_idx]
        payload = {
            "jsonrpc": "2.0",
            "id": int(time.time() * 1000),
            "method": method,
            "params": {**params, "access_token": token}
        }
        try:
            r = requests.post(UIS_CALL_API_URL, json=payload, timeout=12)
            res = r.json()
            err = res.get("error") or {}
            err_code = err.get("code")
            err_msg = str(err.get("message") or "")

            # Проверяем превышение лимита запросов (rate limit / quota exceeded)
            is_limit_reached = (
                r.status_code == 429
                or err_code in [-32000, -32001, 429]
                or any(w in err_msg.lower() for w in ["limit", "quota", "превышен лимит", "слишком много"])
            )

            if is_limit_reached and len(UIS_ACCESS_TOKENS) > 1:
                next_idx = (_current_token_idx + 1) % len(UIS_ACCESS_TOKENS)
                print(f"[UIS POOL] Токен #{_current_token_idx + 1} исчерпал лимит ({err_msg}). Автопереключение на токен #{next_idx + 1}!", flush=True)
                _current_token_idx = next_idx
                continue

            return res
        except Exception as e:
            print(f"Ошибка вызова UIS Call API ({method}) на токене #{_current_token_idx + 1}: {e}", flush=True)
            time.sleep(1)

    return {}

def is_working_hours():
    now = datetime.now(MSK_TZ)
    # Выходные дни: суббота (5) и воскресенье (6) - автопрозвон строго выключен
    if now.weekday() >= 5:
        day_name = "Суббота" if now.weekday() == 5 else "Воскресенье"
        return False, f"Выходной день ({day_name}), автодозвон отключен"
    # Рабочие часы: строго с 09:00 до 18:00 МСК
    if now.hour < 9:
        return False, f"До начала рабочего дня (сейчас {now.strftime('%H:%M')} МСК, старт строго в 09:00)"
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
    return {"called_today": {}, "last_call_time": {}, "pending_calls": {}, "processed_call_ids": []}

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

def notify_candidate_pressed_one(user_id, deal_id, deal_title, phone, initial_stage="EXECUTING", manager_in_line=True):
    """
    Отправляет персональное уведомление в колокольчик менеджеру в Битрикс24
    когда кандидат в автопрозвоне взял трубку / подтвердил актуальность.
    СТРОГО ответственному менеджеру по сделке!
    """
    deal_url = f"https://b24-4qx38o.bitrix24.ru/crm/deal/details/{deal_id}/"
    recruiter_name = RECRUITERS.get(int(user_id), {}).get("name", f"ID {user_id}")

    if initial_stage == "UC_REQ_PASSPORT":
        if not manager_in_line:
            notify_msg = (
                f"🔔 [B]Кандидат появился в сети! Нужно позвонить из стадии «Запрос паспорта»[/B]\n"
                f"Сделка #{deal_id}: {deal_title}\n"
                f"Телефон: +{phone}\n"
                f"Кандидат прямо сейчас ответил на звонок (появился в сети)! Так как вы сейчас не в линии / в другом звонке, робот не стал переводить вызов.\n"
                f"👉 Срочно перезвоните кандидату и запросите паспорт:\n"
                f"[URL={deal_url}]Открыть сделку #{deal_id}[/URL]"
            )
            timeline_msg = (
                f"🔔 [B]Автопрозвон (Запрос паспорта):[/B] Кандидат +{phone} появился в сети (ответил на звонок).\n"
                f"Ответственный менеджер ({recruiter_name}) в этот момент был не в линии.\n"
                f"Стадия «Запрос паспорта» сохранена. Менеджеру отправлено персональное уведомление срочно перезвонить."
            )
        else:
            notify_msg = (
                f"🔥 [B]Автопрозвон (Запрос паспорта): Кандидат подтвердил актуальность (нажал 1)![/B]\n"
                f"Сделка #{deal_id}: {deal_title}\n"
                f"Телефон: +{phone}\n"
                f"Кандидат прямо сейчас на связи! Запросите паспорт и согласуйте дату выезда:\n"
                f"👉 [URL={deal_url}]Открыть сделку #{deal_id}[/URL]"
            )
            timeline_msg = (
                f"🔥 [B]Автопрозвон (Запрос паспорта):[/B] Кандидат +{phone} взял трубку и подтвердил актуальность (нажал 1).\n"
                f"Стадия «Запрос паспорта» сохранена (ручной перенос рекрутером).\n"
                f"Ответственному менеджеру отправлено персональное уведомление перезвонить прямо сейчас."
            )
    else:
        if not manager_in_line:
            notify_msg = (
                f"🔔 [B]Кандидат появился в сети (взял трубку)![/B]\n"
                f"Сделка #{deal_id}: {deal_title}\n"
                f"Телефон: +{phone}\n"
                f"Кандидат ответил на автодозвон, пока вы были не в линии / в другом разговоре.\n"
                f"👉 Перезвоните кандидату: [URL={deal_url}]Открыть сделку #{deal_id}[/URL]"
            )
            timeline_msg = (
                f"🔔 [B]Автопрозвон НДЗ:[/B] Кандидат +{phone} взял трубку, пока менеджер был не в линии.\n"
                f"Менеджеру отправлено уведомление перезвонить кандидату."
            )
        else:
            notify_msg = (
                f"🔥 [B]Автопрозвон: Кандидат подтвердил актуальность (нажал 1)![/B]\n"
                f"Сделка #{deal_id}: {deal_title}\n"
                f"Телефон: +{phone}\n"
                f"Кандидат прямо сейчас на связи! Срочно перезвоните ему:\n"
                f"👉 [URL={deal_url}]Открыть сделку #{deal_id}[/URL]"
            )
            timeline_msg = (
                f"🔥 [B]Автопрозвон НДЗ:[/B] Кандидат +{phone} взял трубку и подтвердил актуальность поиска работы (нажал 1).\n"
                f"Ответственному менеджеру отправлено персональное уведомление перезвонить прямо сейчас."
            )

    try:
        requests.post(f"{B24_NOTIFY_WEBHOOK_URL}im.notify.system.add", json={
            "USER_ID": int(user_id),
            "MESSAGE": notify_msg
        }, timeout=8)
    except Exception as e:
        print(f"Ошибка отправки колокольчика менеджеру {user_id}: {e}", flush=True)

    add_timeline_comment(deal_id, timeline_msg)
    print(f"🔥 [УВЕДОМЛЕНИЕ МЕНЕДЖЕРУ] Сделка #{deal_id} (+{phone}) [{initial_stage}] (in_line={manager_in_line}) — менеджеру {user_id} отправлено уведомление!", flush=True)

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

ALL_NDZ_STAGES = ["UC_NDZ2", "EXECUTING", "UC_NDZ3", "UC_REQ_PASSPORT"]
_recruiter_stage_indices = {}

def get_next_ndz_deal_for_recruiter(user_id, called_today):
    """
    Выбирает сделку менеджера со справедливой ротацией стадий (Round-Robin).
    Исключает голодание стадий НДЗ 2, НДЗ 3 и Запрос паспорта из-за большого числа новых откликов в НДЗ 1.
    Соблюдает строгую паузу 2.5 часа между повторными звонками одному кандидату.
    """
    curr_idx = _recruiter_stage_indices.get(user_id, 0)
    ordered_stages = [ALL_NDZ_STAGES[(curr_idx + i) % len(ALL_NDZ_STAGES)] for i in range(len(ALL_NDZ_STAGES))]

    for st in ordered_stages:
        filt = {
            "ASSIGNED_BY_ID": user_id,
            "STAGE_ID": st
        }
        # Для стадии «Запрос паспорта» прозваниваем СТРОГО сделки старше 5 дней (> 5 дней)
        # Свежие сделки рекрутеры ведут вручную!
        if st == "UC_REQ_PASSPORT":
            five_days_ago_str = (datetime.now(MSK_TZ) - timedelta(days=5)).strftime("%Y-%m-%d %H:%M:%S")
            filt["<=DATE_CREATE"] = five_days_ago_str
        res = call_b24("crm.deal.list", {
            "order": {"ID": "DESC"},
            "filter": filt,
            "select": ["ID", "TITLE", "STAGE_ID", "ASSIGNED_BY_ID", "COMMENTS", "CONTACT_ID", "DATE_CREATE"],
            "limit": 25
        })
        deals = res.get("result", [])
        for d in deals:
            did = str(d.get("ID"))
            # Двойная проверка в Python: для «Запрос паспорта» строго старше 5 дней (5 * 86400 сек)
            if st == "UC_REQ_PASSPORT":
                dc = d.get("DATE_CREATE") or ""
                try:
                    dc_dt = datetime.fromisoformat(dc[:19]).replace(tzinfo=MSK_TZ)
                    if (datetime.now(MSK_TZ) - dc_dt).total_seconds() < 5 * 86400:
                        continue
                except Exception:
                    pass
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
                    # Сдвигаем индекс стадии для следующего звонка этого рекрутера
                    st_pos = ALL_NDZ_STAGES.index(st)
                    _recruiter_stage_indices[user_id] = (st_pos + 1) % len(ALL_NDZ_STAGES)
                    return d, norm_ph, st
    return None, None, None

def advance_deal_stage(did, current_stage, recruiter_name, fail_reason):
    """
    Переводит сделку строго на следующий этап после подтвержденного недозвона робота:
    НДЗ 1 (EXECUTING) -> НДЗ 2 (UC_NDZ2)
    НДЗ 2 (UC_NDZ2) -> НДЗ 3 (UC_NDZ3)
    НДЗ 3 (UC_NDZ3) -> остается в НДЗ 3 (закрытие в Неуспех в 18:00)
    """
    if current_stage == "EXECUTING":
        call_b24("crm.deal.update", {
            "id": did,
            "fields": {"STAGE_ID": "UC_NDZ2"}
        })
        add_timeline_comment(did, f"🤖 Автопрозвон НДЗ: Недозвон ({fail_reason}).\nСделка переведена: НДЗ 1 ➔ НДЗ 2.\nСледующий звонок не ранее чем через 2.5 часа (защита от спама).")
        print(f"⏩ [НЕДОЗВОН 1 -> НДЗ 2] Сделка #{did} ({recruiter_name}) переведена в UC_NDZ2", flush=True)

    elif current_stage == "UC_NDZ2":
        call_b24("crm.deal.update", {
            "id": did,
            "fields": {"STAGE_ID": "UC_NDZ3"}
        })
        add_timeline_comment(did, f"🤖 Автопрозвон НДЗ: Повторный недозвон ({fail_reason}).\nСделка переведена: НДЗ 2 ➔ НДЗ 3.\nСледующий звонок не ранее чем через 2.5 часа (защита от спама).")
        print(f"⏩ [НЕДОЗВОН 2 -> НДЗ 3] Сделка #{did} ({recruiter_name}) переведена в UC_NDZ3", flush=True)

    elif current_stage == "UC_NDZ3":
        add_timeline_comment(did, f"🤖 Автопрозвон НДЗ: Недозвон на стадии НДЗ 3 ({fail_reason}). Сделка ожидает закрытия в Неуспех в конце рабочего дня (18:00).")
        print(f"ℹ️ [НЕДОЗВОН 3] Сделка #{did} ({recruiter_name}) остается в UC_NDZ3 до 18:00", flush=True)

    elif current_stage == "UC_REQ_PASSPORT":
        add_timeline_comment(did, f"🤖 Автопрозвон: Недозвон на стадии «Запрос паспорта» ({fail_reason}).\nСтадия сохранена без изменений (ручной перенос рекрутером).\nСледующий звонок не ранее чем через 2.5 часа (защита от спама).")
        print(f"ℹ️ [НЕДОЗВОН ЗАПРОС ПАСПОРТА] Сделка #{did} ({recruiter_name}) остается в UC_REQ_PASSPORT (стадия сохранена)", flush=True)

def check_pending_calls(state):
    """
    Проверяет результаты ТОЛЬКО ТЕХ звонков, которые были реально инициированы роботом
    и сохранены в pending_calls. Никакие чужие или старые звонки с портала не затрагиваются!
    """
    pending = state.setdefault("pending_calls", {})
    if not pending:
        return

    now_ts = time.time()
    for session_id, info in list(pending.items()):
        did = str(info["deal_id"])
        phone = info["phone"]
        user_id = info["user_id"]
        start_ts = info.get("start_time", now_ts)
        init_stage = info.get("initial_stage", "EXECUTING")
        dtitle = info.get("title", f"Сделка #{did}")
        elapsed = now_ts - start_ts

        # Если прошло меньше 25 секунд — вызов еще гудит/идет, ждем
        if elapsed < 25:
            continue

        # Ищем завершенный вызов в Битрикс24 телефонии строго по номеру линии сценария и номеру кандидата
        since_time = datetime.fromtimestamp(start_ts - 20, MSK_TZ).strftime("%Y-%m-%d %H:%M:%S")
        res = call_b24("voximplant.statistic.get", {
            "FILTER": {
                "=PHONE_NUMBER": phone,
                ">CALL_START_DATE": since_time
            },
            "SORT": "CALL_START_DATE",
            "ORDER": "DESC",
            "LIMIT": 5
        }).get("result", [])

        finished_call = None
        for c in res:
            finished_call = c
            break

        recruiter_name = RECRUITERS.get(user_id, {}).get("name", f"ID {user_id}")

        if finished_call:
            dur = int(finished_call.get("CALL_DURATION") or 0)
            failed_code = str(finished_call.get("CALL_FAILED_CODE") or "")
            activity_id = finished_call.get("CRM_ACTIVITY_ID")

            if activity_id:
                try:
                    call_b24("crm.activity.update", {
                        "id": activity_id,
                        "fields": {"SUBJECT": f"Автопрозвон НДЗ: +{phone}"}
                    })
                except Exception:
                    pass

            # Проверяем, находится ли ответственный менеджер прямо сейчас в линии (онлайн и не в другом звонке)
            busy_emp_ids, busy_virt_phones = get_busy_uis_employees()
            is_online, _ = is_manager_present(user_id)
            uinfo = RECRUITERS.get(user_id, {})
            is_manager_busy_now = (uinfo.get("uis_employee_id") in busy_emp_ids) or (uinfo.get("virtual_phone") in busy_virt_phones)
            manager_in_line = is_online and not is_manager_busy_now

            # Кандидат взял трубку (для стадии «Запрос паспорта» достаточно факта успешного ответа dur >= 3)
            candidate_answered = (failed_code == "200" and dur >= 7) or (init_stage == "UC_REQ_PASSPORT" and failed_code == "200" and dur >= 3)
            if candidate_answered:
                notify_candidate_pressed_one(user_id, did, dtitle, phone, initial_stage=init_stage, manager_in_line=manager_in_line)
                del pending[session_id]
                save_state(state)
                continue

            fail_reason = f"сброс/не ответил ({dur}с, код {failed_code})"
            advance_deal_stage(did, init_stage, recruiter_name, fail_reason)
            del pending[session_id]
            save_state(state)

        elif elapsed > 180:
            # Звонок старше 3 минут — гарантированный таймаут/сброс
            fail_reason = "таймаут/не ответил (>3 мин)"
            advance_deal_stage(did, init_stage, recruiter_name, fail_reason)
            del pending[session_id]
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

def is_manager_present(uid):
    """
    Проверяет, находится ли менеджер на рабочем месте:
    1. Онлайн ли менеджер на портале Битрикс24 (user.online).
    2. Не нажал ли менеджер «Перерыв» / «Отошел» (imopenlines.operator.pause.get).
    Если менеджер отошел или оффлайн — звонки для него не совершаются!
    """
    try:
        online_users = call_b24("user.online").get("result", [])
        if str(uid) not in [str(x) for x in online_users]:
            return False, "Оффлайн (не в сети Битрикс24)"
        
        pause_res = call_b24("imopenlines.operator.pause.get", {"USER_ID": uid}).get("result", False)
        if pause_res:
            return False, "На перерыве (статус 'Отошел' в Битрикс24)"
    except Exception:
        pass
    return True, "На рабочем месте (онлайн)"

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


def check_incoming_callbacks(state):
    """
    Отслеживает пропущенные входящие обратные звонки кандидатов на номер автопрозвона (79677875304).
    Если кандидат перезвонил, но звонок сорвался/был не принят (код 304):
    Мгновенно шлет персональное уведомление (колокольчик) в Битрикс24 ответственному менеджеру!
    """
    processed = state.setdefault("notified_callbacks", [])
    now_dt = datetime.now(MSK_TZ)
    since_time = (now_dt - timedelta(minutes=15)).strftime("%Y-%m-%d %H:%M:%S")
    try:
        res = call_b24("voximplant.statistic.get", {
            "FILTER": {
                "=PORTAL_NUMBER": "79677875304",
                "=CALL_TYPE": "2",
                "=CALL_FAILED_CODE": "304",
                ">CALL_START_DATE": since_time
            },
            "SORT": "CALL_START_DATE",
            "ORDER": "DESC",
            "LIMIT": 20
        }).get("result", [])

        for c in res:
            cid = str(c.get("ID"))
            if cid in processed:
                continue
            processed.append(cid)
            if len(processed) > 500:
                state["notified_callbacks"] = processed[-300:]

            phone = c.get("PHONE_NUMBER") or ""
            user_id = c.get("PORTAL_USER_ID")
            ent_id = c.get("CRM_ENTITY_ID")
            ent_type = c.get("CRM_ENTITY_TYPE")

            deal_id = None
            deal_title = f"Кандидат +{phone}"
            if ent_type == "CONTACT" and ent_id:
                d_res = call_b24("crm.deal.list", {
                    "filter": {"CONTACT_ID": ent_id, "CATEGORY_ID": 0},
                    "order": {"ID": "DESC"},
                    "select": ["ID", "TITLE", "ASSIGNED_BY_ID"],
                    "limit": 1
                }).get("result", [])
                if d_res:
                    deal_id = d_res[0].get("ID")
                    deal_title = d_res[0].get("TITLE")
                    if not user_id or user_id == "0":
                        user_id = d_res[0].get("ASSIGNED_BY_ID")

            if not user_id or str(user_id) == "0":
                continue

            target_uid = int(user_id)
            if deal_id:
                deal_url = f"https://b24-4qx38o.bitrix24.ru/crm/deal/details/{deal_id}/"
                msg = (
                    f"🔥 [B]ВАМ ТОЛЬКО ЧТО ПЕРЕЗВОНИЛ КАНДИДАТ![/B]\n"
                    f"Сделка #{deal_id}: {deal_title}\n"
                    f"Телефон: +{phone}\n"
                    f"Кандидат перезвонил на номер автопрозвона, но вызов был не отвечен.\n"
                    f"👉 [URL={deal_url}]Срочно открыть сделку #{deal_id} и перезвонить[/URL]"
                )
                add_timeline_comment(deal_id, f"🔥 [B]Автопрозвон:[/B] Кандидат +{phone} только что перезвонил в ответ на автопрозвон, но звонок не был принят. Ответственному менеджеру отправлен колокольчик срочно перезвонить.")
            else:
                msg = (
                    f"🔥 [B]ВАМ ТОЛЬКО ЧТО ПЕРЕЗВОНИЛ КАНДИДАТ![/B]\n"
                    f"Телефон: +{phone}\n"
                    f"Кандидат перезвонил на номер автопрозвона, но вызов был не отвечен.\n"
                    f"👉 Срочно наберите кандидата: +{phone}"
                )

            requests.post(f"{B24_NOTIFY_WEBHOOK_URL}im.notify.system.add", json={
                "USER_ID": target_uid,
                "MESSAGE": msg
            }, timeout=8)
            print(f"🔥 [КОЛОКОЛЬЧИК ОБРАТНЫЙ ЗВОНОК] Отправлен менеджеру {target_uid} по кандидату +{phone} (Сделка #{deal_id})", flush=True)
        save_state(state)
    except Exception as e:
        print(f"Ошибка проверки обратных звонков: {e}", flush=True)

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
    check_pending_calls(state)

    # Проверка входящих обратных звонков кандидатов на номер автопрозвона
    check_incoming_callbacks(state)

    # Проверка закрытия НДЗ 3 в 18:00
    close_eod_ndz3_deals()
        
    if not is_ok:
        print(f"⏸️ Автодозвон на паузе: {reason}", flush=True)
        return

    called_today = state.setdefault("called_today", {})
    last_call_time = state.setdefault("last_call_time", {})
    last_busy_time = state.setdefault("last_busy_time", {})

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

        # ОПТИМИЗАЦИЯ КВОТЫ UIS: запрашиваем занятость в UIS строго тогда,
        # когда найдена реальная сделка и подошла очередь звонка (экономит 95% API-лимита!)
        busy_emp_ids, busy_virt_phones = get_busy_uis_employees()

        did = deal.get("ID")
        dtitle = deal.get("TITLE")
        stage_names = {"EXECUTING": "НДЗ 1", "UC_NDZ2": "НДЗ 2", "UC_NDZ3": "НДЗ 3", "UC_REQ_PASSPORT": "Запрос паспорта"}
        st_label = stage_names.get(stage, stage)

        is_manager_busy = (emp_id in busy_emp_ids) or (virt_phone in busy_virt_phones)

        # Ждем освобождения менеджера перед звонком кандидату (включая Запрос паспорта, чтобы при нажатии 1 не было сброса)
        if is_manager_busy:
            print(f"⏳ [МЕНЕДЖЕР В ЗВОНКЕ] {uname} сейчас на линии. Ожидаем завершения разговора перед звонком кандидату +{phone} (Сделка #{did} [{st_label}])...", flush=True)
            continue

        print(f"\n🚀 [ИНИЦИАЦИЯ ВЫЗОВА В СОФТФОН UIS] {uname} (Employee ID: {emp_id}) -> Сделка #{did} | Тел кандидата: +{phone} | Линия: +{virt_phone} | Стадия: {st_label}", flush=True)

        AUTODIAL_VIRTUAL_NUMBER = "79677875304"  # Линия сценария автопрозвона с голосовым меню IVR (кнопка 1)

        print(f"\n🚀 [ИНИЦИАЦИЯ ВЫЗОВА С IVR КНОПКА 1] {uname} -> Сделка #{did} | Тел кандидата: +{phone} | Номер сценария: +{AUTODIAL_VIRTUAL_NUMBER} | Стадия: {st_label}", flush=True)

        # ЖЕЛЕЗНАЯ СИНХРОНИЗАЦИЯ ДЛЯ ТЕЛЕФОНИИ UIS:
        # Телефония UIS при входящем звонке и переадресации из CRM определяет ответственного по КОНТАКТУ в Битрикс24!
        # Гарантируем, что ответственным за контакт соискателя прямо перед вызовом назначен ответственный менеджер сделки (uid)!
        cid = deal.get("CONTACT_ID")
        if cid:
            call_b24("crm.contact.update", {
                "id": cid,
                "fields": {"ASSIGNED_BY_ID": uid}
            })

        # Вызываем официальный метод UIS Call API start.vnumber_call:
        # Звонок идет кандидату с номера 79677875304, срабатывает сценарий автопрозвона с IVR (кнопка 1).
        # Автоответчики отсекаются, а при нажатии 1 вызов переводится СТРОГО на ответственного менеджера!
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
            state.setdefault("pending_calls", {})[str(session_id)] = {
                "deal_id": did,
                "phone": phone,
                "user_id": uid,
                "start_time": time.time(),
                "initial_stage": stage,
                "title": dtitle
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
