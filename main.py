# -*- coding: utf-8 -*-
"""
AVITO AI RECRUITER & B24 ENHANCER (MAIN ENTRYPOINT)
Автономный фоновый сервис 24/7
"""
from fastapi import FastAPI, Request, BackgroundTasks
import uvicorn
import asyncio
import time
import os
from config import PORT, HOST, AVITO_CLIENT_ID, AVITO_CLIENT_SECRET, AVITO_USER_ID
from ai_engine import AIRecruiterEngine
from b24_sync import call_b24, parse_and_enhance_deal
from process_live_chats import process_single_chat
from avito_api import AvitoClient

app = FastAPI(title="Avito AI Recruiter Bot")
ai_engine = AIRecruiterEngine()
avito_client = AvitoClient(AVITO_CLIENT_ID, AVITO_CLIENT_SECRET, AVITO_USER_ID)

@app.get("/")
def health_check():
    return {
        "status": "online",
        "service": "Avito AI Recruiter & B24 Enhancer",
        "uptime": "24/7 active",
        "version": "1.2.0"
    }

async def poll_avito_chats_loop():
    """
    Фоновый диспетчер: каждые 2 минуты (120 секунд) проверяет входящие сообщения
    в чатах Авито и автоматически отвечает кандидатам.
    """
    print("[AVITO POLLER] Фоновый мониторинг чатов Авито запущен (интервал: 2 минуты).")
    while True:
        try:
            print(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] Проверка новых сообщений на Авито...")
            unread_chats = avito_client.get_unread_chats(limit=30)
            if unread_chats:
                print(f"Найдено непрочитанных чатов: {len(unread_chats)}")
                answered = 0
                for c in unread_chats:
                    try:
                        if process_single_chat(c):
                            answered += 1
                            await asyncio.sleep(2)
                    except Exception as e_chat:
                        print(f"Ошибка обработки чата: {e_chat}")
                if answered > 0:
                    print(f"Успешно отправлено ответов в этом цикле: {answered}")
            else:
                print("Новых сообщений нет, все чаты обработаны.")
        except Exception as e:
            print(f"[AVITO POLLER ERROR] {e}")

        # Пауза 2 минуты перед следующей проверкой
        await asyncio.sleep(120)

async def poll_and_enhance_deals():
    """
    Фоновый диспетчер CRM: каждые 30 секунд проверяет новые сделки из Авито
    и переименовывает их в [Объект] Имя | Телефон | Возраст (Пол)
    """
    while True:
        try:
            res = call_b24("crm.deal.list", {
                "order": {"ID": "DESC"},
                "filter": {"CATEGORY_ID": 0, "%TITLE": "Avito Wappi"},
                "select": ["ID", "TITLE", "COMMENTS", "UF_CRM_1775470003043", "UF_CRM_1768816011673", "UF_CRM_1768816356722"],
                "limit": 10
            })
            deals = res.get("result", [])
            for d in deals:
                parse_and_enhance_deal(d)
        except Exception as e:
            print(f"[CRM POLLER ERROR] {e}")
        await asyncio.sleep(30)

@app.on_event("startup")
async def startup_event():
    # Запускаем фоновые циклы
    asyncio.create_task(poll_avito_chats_loop())
    asyncio.create_task(poll_and_enhance_deals())
    print("[STARTUP] Все фоновые службы (Avito + CRM) успешно стартовали.")

if __name__ == "__main__":
    uvicorn.run("main:app", host=HOST, port=PORT, reload=False)
