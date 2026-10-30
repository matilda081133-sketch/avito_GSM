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

app = FastAPI(title="HR Cloud Autonomous Recruiter Service", version="2.7.2")

ENABLE_AVITO_ASSISTANT = os.environ.get("ENABLE_AVITO_ASSISTANT", "True").lower() in ("true", "1", "yes")
ENABLE_MAX_BOT = os.environ.get("ENABLE_MAX_BOT", "False").lower() in ("true", "1", "yes")
ENABLE_B24_ENHANCER = os.environ.get("ENABLE_B24_ENHANCER", "True").lower() in ("true", "1", "yes")

threads_state = {
    "avito": None,
    "max": None,
    "b24": None
}

_thread_lock = threading.Lock()

def ensure_threads_alive():
    """Самоисцеляющий сторож (Watchdog) с защитой от одновременных вызовов через Mutex."""
    with _thread_lock:
        restarted = []
        if ENABLE_AVITO_ASSISTANT:
            t = threads_state.get("avito")
            if t is None or not t.is_alive():
                t_av = threading.Thread(target=run_avito_poller_thread, daemon=True, name="AvitoPollerThread")
                t_av.start()
                threads_state["avito"] = t_av
                restarted.append("avito")

        if ENABLE_MAX_BOT:
            t = threads_state.get("max")
            if t is None or not t.is_alive():
                t_mx = threading.Thread(target=run_max_bot_thread, daemon=True, name="MaxBotThread")
                t_mx.start()
                threads_state["max"] = t_mx
                restarted.append("max")

        if ENABLE_B24_ENHANCER:
            t = threads_state.get("b24")
            if t is None or not t.is_alive():
                t_b = threading.Thread(target=run_b24_enhancer_thread, daemon=True, name="B24EnhancerThread")
                t_b.start()
                threads_state["b24"] = t_b
                restarted.append("b24")
                
        return restarted

pings_history = []

@app.get("/")
@app.get("/health")
@app.get("/healthz")
def healthcheck(request: Request):
    restarted = ensure_threads_alive()
    avito_alive = bool(threads_state.get("avito") and threads_state["avito"].is_alive())
    max_alive = bool(threads_state.get("max") and threads_state["max"].is_alive())
    b24_alive = bool(threads_state.get("b24") and threads_state["b24"].is_alive())

    client_ip = request.client.host if request.client else "unknown"
    ua = request.headers.get("user-agent", "unknown")
    now_ts = time.time()
    now_str = time.strftime("%Y-%m-%d %H:%M:%S")

    pings_history.append({
        "time": now_str,
        "ts": now_ts,
        "ip": client_ip,
        "user_agent": ua,
        "path": request.url.path
    })
    if len(pings_history) > 100:
        pings_history.pop(0)

    return {
        "status": "online",
        "service": "Avito + MAX Cloud AI Recruiter (GSM Logistics) 24/7",
        "version": "2.7.2",
        "threads": {
            "avito_alive": avito_alive,
            "max_alive": max_alive,
            "b24_alive": b24_alive
        },
        "restarted_on_ping": restarted,
        "total_pings_received": len(pings_history),
        "last_ping_user_agent": ua,
        "message": "Autonomous cloud recruiter online 24/7 with auto-healing watchdog",
        "timestamp": now_str
    }

@app.get("/cron-status")
def cron_status():
    """Детальная диагностика работы внешнего cron-job пингера."""
    cron_pings = [p for p in pings_history if "cron" in p.get("user_agent", "").lower()]
    return {
        "status": "ok",
        "total_pings": len(pings_history),
        "cron_detected": len(cron_pings) > 0,
        "cron_pings_count": len(cron_pings),
        "last_pings": pings_history[-20:]
    }



@app.get("/test-gemini")
def test_gemini_endpoint():
    """Тестовый эндпоинт для мгновенной диагностики вызова Gemini LLM из облака Render."""
    import requests
    from llm_recruiter import get_api_key
    api_key = get_api_key()
    diag = {
        "has_api_key": bool(api_key),
        "key_len": len(api_key) if api_key else 0,
        "key_prefix": api_key[:6] if api_key else "",
        "attempts": []
    }
    models = ["gemini-2.5-flash-lite", "gemini-flash-latest", "gemini-3.1-flash-lite", "gemini-3.5-flash-lite", "gemini-2.5-flash"]
    for m in models:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent?key={api_key}"
        try:
            r = requests.post(url, json={"contents": [{"parts": [{"text": "Ответь одним словом: Работает"}]}]}, timeout=5)
            diag["attempts"].append({
                "model": m,
                "status": r.status_code,
                "resp": r.text[:200]
            })
            if r.status_code == 200:
                diag["working_model"] = m
                break
        except Exception as e:
            diag["attempts"].append({
                "model": m,
                "error": str(e)
            })
    return diag

@app.post("/avito-webhook")
async def avito_webhook(request: Request):
    """
    Высокоскоростной входящий Webhook от Avito Messenger API V2.
    Реакция на входящие сообщения соискателей за ~1-2 секунды (Kupibilet / Tinkoff standard).
    """
    try:
        data = await request.json()
        payload = data.get("payload", {}).get("value", {})
        chat_id = payload.get("chat_id")
        user_id = payload.get("user_id")
        text_content = payload.get("content", {}).get("text", "")
        author_id = payload.get("author_id")

        if not chat_id or not text_content:
            return {"status": "ignored", "reason": "empty"}

        # Игнорируем собственные сообщения
        if author_id == AVITO_USER_ID:
            return {"status": "ok", "reason": "self"}

        print(f"[AVITO WEBHOOK] Входящее сообщение в чате {chat_id}: '{text_content[:60]}...'", flush=True)

        # Запускаем обработку в фоновом потоке, чтобы сразу вернуть HTTP 200 Авито
        def handle_async():
            try:
                from run_demo_assistant import client, process_valeria_chat
                chat_info = client.get_chat_messages(chat_id)
                # Получаем метаданные чата
                raw_chats = client.get_chats(unread_only=False)
                c_item = next((c for c in raw_chats if c.get("id") == chat_id), {})
                c_title = c_item.get("context", {}).get("value", {}).get("title", "")
                c_user = c_item.get("users", [{}])[0].get("name", "Кандидат")
                
                msgs = list(reversed(chat_info))
                process_valeria_chat(chat_id, c_user, c_title, msgs)
            except Exception as e_proc:
                print(f"[AVITO WEBHOOK ERROR] Ошибка обработки: {e_proc}", flush=True)

        threading.Thread(target=handle_async, daemon=True).start()
        return {"status": "ok", "chat_id": chat_id}
    except Exception as e:
        print(f"[AVITO WEBHOOK FATAL] {e}", flush=True)
        return {"status": "error", "error": str(e)}

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
    """Фоновый поток дежурного рекрутера Авито с вечным авто-перезапуском при любом сбое."""
    print("[CLOUD AVITO] Дежурный AI-рекрутер Авито запущен в облаке 24/7 (GSM Logistics).", flush=True)
    while True:
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
            print(f"[CLOUD AVITO CRITICAL INIT ERROR] {e_init}. Перезапуск через 10с...", flush=True)
            time.sleep(10)

def run_b24_enhancer_thread():
    """Фоновый поток авто-обогащения и форматирования сделок Б24 с авто-перезапуском."""
    print("[CLOUD B24] Сервис авто-обогащения сделок Битрикс24 запущен в облаке (интервал: 45с).", flush=True)
    while True:
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
            print(f"[CLOUD B24 INIT ERROR] {e_init}. Перезапуск через 15с...", flush=True)
            time.sleep(15)

def run_max_bot_thread():
    """Фоновый поток бота МАКС (@id9729371578_bot) с вечным авто-перезапуском."""
    print("[CLOUD MAX] Сервис МАКС-бота запущен в облаке 24/7.", flush=True)
    while True:
        try:
            from max_bot_service.main import bot_worker_loop
            bot_worker_loop()
        except Exception as e:
            print(f"[CLOUD MAX ERROR] {e}. Перезапуск через 5с...", flush=True)
            time.sleep(5)

@app.on_event("startup")
def startup_event():
    ensure_threads_alive()
    print("🚀 [STARTUP] Все фоновые сервисы успешно инициализированы в облаке.", flush=True)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", PORT if PORT else 8080))
    host = os.environ.get("HOST", "0.0.0.0")
    print(f"🌍 Запуск HTTP Healthcheck сервера на {host}:{port}...", flush=True)
    uvicorn.run("main:app", host=host, port=port, reload=False)
