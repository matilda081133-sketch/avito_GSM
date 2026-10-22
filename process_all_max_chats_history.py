# -*- coding: utf-8 -*-
"""
Пакетная синхронизация всей истории сообщений из групповых чатов объектов МАКС в Битрикс24.
1. Скачивает ВСЮ историю сообщений из всех чатов МАКС (от старых к новым).
2. Находит анкеты кандидатов, телефоны, сопоставляет со сделками в Битрикс24.
3. Проставляет актуальные статусы: «Направлен на смену», «1 смена», «2 смена», «не доехал» (с постановкой задачи рекрутеру).
"""
import sys, os, requests, json, time, urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
sys.stdout.reconfigure(encoding='utf-8')

sys.path.insert(0, os.path.dirname(__file__))
from max_recruiter_bot import (
    HEADERS, MAX_API_BASE, OBJECT_CHATS, extract_phones,
    handle_group_chat_message, load_state, save_state
)

def fetch_all_chat_messages(cid):
    messages = []
    before = None
    while True:
        url = f"{MAX_API_BASE}/messages?chat_id={cid}&count=100"
        if before:
            url += f"&before={before}"
        try:
            r = requests.get(url, headers=HEADERS, verify=False, timeout=15)
            if r.status_code != 200:
                break
            batch = r.json().get("messages", [])
            if not batch:
                break
            messages.extend(batch)
            if len(batch) < 100:
                break
            before = batch[-1].get("timestamp", 0) - 1
            time.sleep(0.1)
        except Exception as e:
            print(f"Error fetching batch for {cid}: {e}", flush=True)
            time.sleep(1)
            break
    # Возвращаем в хронологическом порядке (от старых к новым)
    messages.reverse()
    return messages

def run_sync():
    print("==================================================", flush=True)
    print("🚀 НАЧАЛО ПОЛНОГО АНАЛИЗА И ОБРАБОТКИ ВСЕХ ЧАТОВ МАКС", flush=True)
    print("==================================================", flush=True)

    state = load_state()
    total_processed = 0
    total_phones_found = set()

    for cid, info in OBJECT_CHATS.items():
        title = info.get("title")
        print(f"\n📥 Скачивание полной истории чата «{title}» (ID {cid})...", flush=True)
        msgs = fetch_all_chat_messages(cid)
        print(f"✅ Получено сообщений: {len(msgs)}. Начинаем хронологическую обработку...", flush=True)

        for m in msgs:
            raw_body = m.get("body") or {}
            if isinstance(raw_body, dict):
                body = raw_body.get("text") or raw_body.get("body") or ""
            else:
                body = str(raw_body or "")

            attachments = m.get("attachments") or []
            link = m.get("link") or {}
            sender = m.get("sender") or {}
            sender_name = f"{sender.get('first_name', '')} {sender.get('last_name', '')}".strip() or "Участник"

            # Считаем телефоны
            phones = extract_phones(body)
            if link and isinstance(link, dict):
                r_msg = link.get("message")
                if isinstance(r_msg, dict):
                    r_body = r_msg.get("body") or {}
                    if isinstance(r_body, dict):
                        r_text = r_body.get("text") or ""
                    else:
                        r_text = str(r_body or "")
                    phones.extend(extract_phones(r_text))

            for p in phones:
                total_phones_found.add(p)

            try:
                handle_group_chat_message(str(cid), sender_name, body, attachments, link, state)
                total_processed += 1
            except Exception as e:
                print(f"Ошибка при обработке сообщения в {title}: {e}", flush=True)

        save_state(state)
        print(f"✅ Завершена обработка чата «{title}». Привязано кандидатов в памяти: {len(state.get('tracked_candidates', {}))}")

    print("\n==================================================", flush=True)
    print(f"🎉 ВСЕ ЧАТЫ МАКС ПОЛНОСТЬЮ ОБРАБОТАНЫ!")
    print(f"Всего обработано сообщений: {total_processed}")
    print(f"Найдено уникальных телефонов: {len(total_phones_found)}")
    print(f"Кандидатов на отслеживании со сделками в CRM: {len(state.get('tracked_candidates', {}))}")
    print("==================================================", flush=True)

if __name__ == "__main__":
    run_sync()
