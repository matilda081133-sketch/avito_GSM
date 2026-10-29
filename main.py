# -*- coding: utf-8 -*-
"""
UNIFIED PRODUCTION CLOUD ENTRYPOINT (RENDER / VPS / DOCKER)
Запуск единого автономного облачного сервиса 24/7:
1. FastAPI сервер с Healthcheck (порт 8080 / PORT из env) — удерживает сервис активным на Render.
2. Фоновый поток 1: Дежурный Авито AI-рекрутер (GSM Logistics) — интеллектуальный диалог, отработка всех возражений по регламенту, Gemini LLM + самообучение.
3. Фоновый поток 2: МАКС рекрутер-бот (@id9729371578_bot) — сценарий рассылки по UTM, автосценарий 4 объектов, Gemini LLM перехват нетипичных вопросов, Gemini Vision проверка паспортов.
4. Фоновый поток 3: Авто-обогащение и синхронизация сделок Битрикс24.
"""
import sys
import os
import time
import threading
import asyncio
from fastapi import FastAPI, Request
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

app = FastAPI(title="HR Cloud Autonomous Recruiter Service", version="2.5.0")

ENABLE_AVITO_ASSISTANT = os.environ.get("ENABLE_AVITO_ASSISTANT", "True").lower() in ("true", "1", "yes")
ENABLE_MAX_BOT = os.environ.get("ENABLE_MAX_BOT", "True").lower() in ("true", "1", "yes")
ENABLE_B24_ENHANCER = os.environ.get("ENABLE_B24_ENHANCER", "True").lower() in ("true", "1", "yes")

@app.get("/")
@app.get("/health")
@app.get("/healthz")
def healthcheck():
    return {
        "status": "online" if (ENABLE_AVITO_ASSISTANT or ENABLE_MAX_BOT) else "standby",
        "service": "Avito + MAX Cloud AI Recruiter (GSM Logistics) 24/7",
        "version": "2.6.0",
        "avito_active": ENABLE_AVITO_ASSISTANT,
        "max_active": ENABLE_MAX_BOT,
        "b24_enhancer_active": ENABLE_B24_ENHANCER,
        "message": "Autonomous cloud recruiter online and running 24/7 with Webhook & Long Polling",
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
    }


@app.post("/max-webhook")
async def max_webhook(request: Request):
    """
    Высокоскоростной входящий Webhook от MAX Messenger Bot API.
    Мгновенно пробуждает сервер Render и обрабатывает входящие сообщения за <1 сек.
    """
    try:
        body = await request.json()
        from max_bot_service.main import handle_single_update
        
        # Если пришел массив обновлений
        if isinstance(body, list):
            for item in body:
                handle_single_update(item)
        elif isinstance(body, dict):
            if "updates" in body and isinstance(body["updates"], list):
                for item in body["updates"]:
                    handle_single_update(item)
            else:
                handle_single_update(body)
                
        return {"status": "ok"}
    except Exception as e:
        print(f"[MAX WEBHOOK ERROR] {e}", flush=True)
        return {"status": "error", "message": str(e)}

def run_avito_poller_thread():
    """Фоновый поток дежурного рекрутера Авито (опрос каждые 12 сек)."""
    print("[CLOUD AVITO] Дежурный AI-рекрутер Авито запущен в облаке 24/7 (GSM Logistics).", flush=True)
    try:
        from run_demo_assistant import check_and_reply_valeria
        poll_count = 0
        while True:
            try:
                poll_count += 1
                check_and_reply_valeria()
                if poll_count % 15 == 0:
                    print(f"[CLOUD AVITO] Мониторинг чатов активен (проверок: {poll_count}).", flush=True)
                time.sleep(12)
            except Exception as e:
                print(f"[CLOUD AVITO POLLER ERROR] {e}", flush=True)
                time.sleep(10)
    except Exception as e_init:
        print(f"[CLOUD AVITO CRITICAL INIT ERROR] {e_init}", flush=True)

def run_b24_enhancer_thread():
    """Фоновый поток авто-обогащения и форматирования сделок Б24 (каждые 45 сек)."""
    print("[CLOUD B24] Сервис авто-обогащения сделок Битрикс24 запущен в облаке (интервал: 45с).", flush=True)
    try:
        from b24_sync import sync_recent_raw_deals
        while True:
            try:
                sync_recent_raw_deals(limit=30)
                time.sleep(45)
            except Exception as e:
                print(f"[CLOUD B24 ENHANCER ERROR] {e}", flush=True)
                time.sleep(30)
    except Exception as e_init:
        print(f"[CLOUD B24 INIT ERROR] {e_init}", flush=True)

def run_max_bot_thread():
    """Фоновый поток бота МАКС (@id9729371578_bot) и воронки подбора."""
    print("[CLOUD MAX] Сервис МАКС-бота запущен в облаке 24/7.", flush=True)
    try:
        from max_bot_service.main import bot_worker_loop
        bot_worker_loop()
    except Exception as e:
        print(f"[CLOUD MAX ERROR] {e}", flush=True)

@app.on_event("startup")
def startup_event():
    if ENABLE_AVITO_ASSISTANT:
        t_avito = threading.Thread(target=run_avito_poller_thread, daemon=True, name="AvitoPollerThread")
        t_avito.start()
        print("🚀 [STARTUP] Дежурный Авито AI-рекрутер запущен в облаке.", flush=True)
    else:
        print("⏸ [STANDBY] AI-ассистент Авито отключен переменной окружения.", flush=True)

    if ENABLE_MAX_BOT:
        try:
            from max_bot_service.main import register_webhook
            domain = os.environ.get("RENDER_EXTERNAL_URL", "https://avito-gsm.onrender.com").rstrip("/")
            register_webhook(f"{domain}/max-webhook")
        except Exception as e_wh:
            print(f"[STARTUP WEBHOOK REG ERROR] {e_wh}", flush=True)

        t_max = threading.Thread(target=run_max_bot_thread, daemon=True, name="MaxBotThread")
        t_max.start()
        print("🚀 [STARTUP] Бот МАКС запущен в облаке (Webhook + Polling).", flush=True)
    else:
        print("⏸ [STANDBY] Бот МАКС отключен переменной окружения.", flush=True)

    if ENABLE_B24_ENHANCER:
        t_b24 = threading.Thread(target=run_b24_enhancer_thread, daemon=True, name="B24EnhancerThread")
        t_b24.start()
        print("🚀 [STARTUP] Авто-обогащение сделок Битрикс24 запущено в облаке.", flush=True)
    else:
        print("⏸ [STANDBY] Авто-обогащение сделок Битрикс24 отключено.", flush=True)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", PORT if PORT else 8080))
    host = os.environ.get("HOST", "0.0.0.0")
    print(f"🌍 Запуск HTTP Healthcheck сервера на {host}:{port}...", flush=True)
    uvicorn.run("main:app", host=host, port=port, reload=False)
