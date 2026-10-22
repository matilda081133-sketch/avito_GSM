# -*- coding: utf-8 -*-
import time
import sys
from avito_api import AvitoClient
from process_live_chats import process_single_chat
from config import AVITO_CLIENT_ID, AVITO_CLIENT_SECRET, AVITO_USER_ID

if sys.stdout is not None:
    try:
        sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)
    except Exception:
        pass
if sys.stderr is not None:
    try:
        sys.stderr.reconfigure(encoding='utf-8', line_buffering=True)
    except Exception:
        pass
client = AvitoClient(AVITO_CLIENT_ID, AVITO_CLIENT_SECRET, AVITO_USER_ID)

print("="*60)
print("🚀 АВТОНОМНЫЙ ДЕЖУРНЫЙ AI-РЕКРУТЕР АВИТО ЗАПУЩЕН")
print("⏱ Опрос входящих сообщений на Авито: каждые 15 секунд")
print("ℹ️ CRM-запросы выполняются строго точечно по факту входящих сообщений")
print("="*60)

while True:
    try:
        now_str = time.strftime('%H:%M:%S')

        # Сканирование новых сообщений кандидатов на Авито (точечная обработка)
        unread = client.get_unread_chats(limit=50)
        recent = client.get_recent_chats(limit=30)

        seen = set()
        all_chats = []
        for c in (unread + recent):
            cid = c.get('id')
            if cid and cid not in seen:
                seen.add(cid)
                all_chats.append(c)

        if all_chats:
            sent = 0
            for c in all_chats:
                try:
                    if process_single_chat(c):
                        sent += 1
                        time.sleep(1.0)
                except Exception as e_c:
                    print(f"Ошибка в диалоге: {e_c}")
            if sent > 0:
                print(f"[{now_str}] Отправлено новых ответов: {sent}")
            else:
                print(f"[{now_str}] Проверено {len(all_chats)} чатов: всё обработано, ожидаем новых сообщений.")
        else:
            print(f"[{now_str}] Новых чатов нет.")
            
    except Exception as e:
        print(f"Ошибка цикла: {e}")
        
    print(f"Следующая проверка через 15 секунд...")
    time.sleep(15)
