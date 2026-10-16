# -*- coding: utf-8 -*-
import time
import sys
from avito_api import AvitoClient
from process_live_chats import process_single_chat
from config import AVITO_CLIENT_ID, AVITO_CLIENT_SECRET, AVITO_USER_ID

sys.stdout.reconfigure(encoding='utf-8')
client = AvitoClient(AVITO_CLIENT_ID, AVITO_CLIENT_SECRET, AVITO_USER_ID)

print("="*60)
print("🚀 АВТОНОМНЫЙ ДЕЖУРНЫЙ AI-РЕКРУТЕР АВИТО ЗАПУЩЕН")
print("⏱ Интервал проверки новых сообщений: каждые 2 минуты")
print("="*60)

while True:
    try:
        now_str = time.strftime('%H:%M:%S')
        print(f"\n[{now_str}] Сканирование новых сообщений на Авито...")
        unread = client.get_unread_chats(limit=30)
        
        if unread:
            print(f"Найдено непрочитанных диалогов: {len(unread)}")
            sent = 0
            for c in unread:
                try:
                    if process_single_chat(c):
                        sent += 1
                        time.sleep(1.5)
                except Exception as e_c:
                    print(f"Ошибка в диалоге: {e_c}")
            if sent > 0:
                print(f"[{now_str}] Отправлено ответов соискателям: {sent}")
        else:
            print(f"[{now_str}] Новых неотвеченных сообщений нет.")
            
    except Exception as e:
        print(f"Ошибка цикла: {e}")
        
    print(f"Следующая проверка через 2 минуты...")
    time.sleep(120)
