# -*- coding: utf-8 -*-
"""
UNIFIED PRODUCTION CLOUD ENTRYPOINT (RENDER / VPS / DOCKER)
Запуск единого автономного облачного сервиса 24/7:
1. FastAPI сервер с Healthcheck (порт 8080 / PORT из env) — удерживает сервис активным на Render.
2. Фоновый поток 1: Дежурный Авито AI-рекрутер (опрос каждые 15 сек, диалоги, синхронизация с Битрикс24).
3. Фоновый поток 2: МАКС рекрутер-бот и автопилот групповых чатов объектов с бригадирами.
"""
import sys
import os
import time
import threading
import asyncio
from fastapi import FastAPI
import uvicorn

# UTF-8 encoding support
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

from config import PORT, HOST, AVITO_CLIENT_ID, AVITO_CLIENT_SECRET, AVITO_USER_ID
from avito_api import AvitoClient
from process_live_chats import process_single_chat
import max_recruiter_bot

app = FastAPI(title="HR Cloud Autonomous Recruiter Service", version="2.0.0")

@app.get("/")
@app.get("/health")
@app.get("/healthz")
def healthcheck():
    return {
        "status": "online",
        "service": "Avito + MAX Cloud AI Recruiter 24/7",
        "version": "2.0.0",
        "avito_active": True,
        "max_active": True,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
    }

def run_avito_poller_thread():
    """Фоновый поток дежурного рекрутера Авито (опрос каждые 15 сек)."""
    print("[CLOUD AVITO] Дежурный рекрутер Авито запущен в облаке (интервал: 15с).", flush=True)
    client = AvitoClient(AVITO_CLIENT_ID, AVITO_CLIENT_SECRET, AVITO_USER_ID)
    while True:
        try:
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
                        print(f"[CLOUD AVITO CHAT ERROR] {e_c}", flush=True)
                if sent > 0:
                    print(f"[CLOUD AVITO] Отправлено ответов кандидатам: {sent}", flush=True)
            time.sleep(15)
        except Exception as e:
            print(f"[CLOUD AVITO POLLER ERROR] {e}", flush=True)
            time.sleep(10)

def run_b24_enhancer_thread():
    """Фоновый поток авто-обогащения и форматирования сделок Б24 (каждые 30 сек)."""
    print("[CLOUD B24] Сервис авто-обогащения сделок Битрикс24 запущен в облаке (интервал: 30с).", flush=True)
    from b24_sync import sync_recent_raw_deals
    while True:
        try:
            sync_recent_raw_deals(limit=40)
            time.sleep(30)
        except Exception as e:
            print(f"[CLOUD B24 ENHANCER ERROR] {e}", flush=True)
            time.sleep(15)


def run_max_bot_thread():
    """Фоновый поток бота МАКС и групповых чатов объектов."""
    print("[CLOUD MAX] Сервис МАКС-бота запущен в облаке.", flush=True)
    try:
        max_recruiter_bot.run_max_bot_loop()
    except Exception as e:
        print(f"[CLOUD MAX ERROR] {e}", flush=True)

@app.on_event("startup")
def startup_event():
    # Запуск Авито в отдельном фоновом потоке
    t_avito = threading.Thread(target=run_avito_poller_thread, daemon=True, name="AvitoPollerThread")
    t_avito.start()

    # Запуск МАКС в отдельном фоновом потоке
    t_max = threading.Thread(target=run_max_bot_thread, daemon=True, name="MaxBotThread")
    t_max.start()

    # Запуск фонового авто-обогащения сделок Битрикс24
    t_b24 = threading.Thread(target=run_b24_enhancer_thread, daemon=True, name="B24EnhancerThread")
    t_b24.start()
    print("🚀 [STARTUP] Все автономные службы (Авито + МАКС + CRM) успешно стартовали в облачном режиме!", flush=True)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", PORT if PORT else 8080))
    host = os.environ.get("HOST", "0.0.0.0")
    print(f"🌍 Запуск HTTP Healthcheck сервера на {host}:{port}...", flush=True)
    uvicorn.run("main:app", host=host, port=port, reload=False)
