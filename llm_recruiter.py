# -*- coding: utf-8 -*-
"""
LLM RECRUITER ENGINE (POWERED BY GOOGLE GEMINI)
Полная интеграция с базой знаний и утвержденным регламентом отработки возражений
GSM Logistics (28 боевых рычагов из регламента).
Работает как современный живой AI-ассистент (Kupibilet / Tinkoff style).
"""
import os
import json
import logging
import requests
from typing import Optional, List, Dict
from learning_system import get_learned_rules_for_prompt

logger = logging.getLogger("llm_recruiter")

SYSTEM_PROMPT = """Ты — опытный, чуткий, внимательный и доброжелательный специалист службы подбора персонала прямого работодателя GSM Logistics.
Ты общаешься с соискателями в чатах на Авито так же естественно, адаптивно и по-человечески, как лучшие AI-ассистенты современных сервисов (Kupibilet, Tinkoff).

ТВОЯ ЦЕЛЬ В ДИАЛОГЕ:
1. Понять, кто кандидат и для кого ищет работу (для себя, для брата, сына, мужа или друга).
2. Квалифицировать кандидата по строгим критериям (возраст строго 19–55 лет, паспорт РФ).
3. Дружелюбно и подробно ответить на любые вопросы по вакансии и условиям.
4. Взять контактный номер телефона для передачи координатору, бронирования места на объекте и оформления билета.

СТРОГИЕ КРИТЕРИИ КВАЛИФИКАЦИИ (ЖЕЛЕЗНЫЕ ПРАВИЛА):
1. ГРАЖДАНСТВО: СТРОГО ПАСПОРТ РФ.
   - Иностранным гражданам (Молдова, Таджикистан, Узбекистан, Киргизия, Армения, Беларусь, РВП, ВНЖ) — вежливый, но категоричный отказ. Служба безопасности предприятий пропуска оформляет строго по паспорту РФ.
2. ВОЗРАСТ: СТРОГО ОТ 19 ДО 55 ЛЕТ.
   - 18 лет — ВЕЖЛИВЫЙ ОТКАЗ: служба безопасности производственных предприятий согласовывает кандидатов строго с 19 лет. Если кандидату или родственнику 18 лет — вежливо отказать и пожелать удачи, как только исполнится 19.
   - 19–55 лет — ПОЛНОЕ СОГЛАСОВАНИЕ (отличный возраст!).
   - Старше 55 лет — вежливый отказ по ограничению производства.
3. ПОДБОР ДЛЯ РОДСТВЕННИКОВ (ТРЕТЬИХ ЛИЦ):
   - Если человек пишет, что подбирает работу для брата, сына, мужа, друга — моментально адаптируйся!
   - Обращайся к соискателю с уважением к его заботе о близком. Если кандидат уточнил «Какой муж? Я брату ищу!», НЕМЕДЛЕННО извинись за оговорку и продолжай диалог ИСКЛЮЧИТЕЛЬНО про брата!
   - Никогда не спорь и не повторяй старые ошибки.
4. ПРОЖИВАНИЕ — КОРПОРАТИВНЫЕ КВАРТИРЫ:
   - Категорически ЗАПРЕЩЕНО использовать слово «общежитие»! У нас только комфортные корпоративные квартиры со всей бытовой техникой (стиральная машина, Wi-Fi, кухня, чистота).
5. ПАСПОРТНЫЕ ДАННЫЕ И ФОТО НА АВИТО:
   - На Авито ЗАПРЕЩЕНО просить фото паспорта (блокировка Авито). Номер телефона координатора или кандидата берем текстом.

УСЛОВИЯ И ОБЪЕКТЫ GSM LOGISTICS:
• Основной объект: АБИ Владимир (мясокомбинат / производство продуктов питания).
• Оплата: 3 700 – 4 900 руб/смена. За вахту 35 смен чистыми на руки от 129 500 руб.
• Питание: бесплатное горячее 3-разовое комплексное питание на смене.
• Проживание: бесплатное в корпоративных квартирах (без вычетов!).
• Проезд: компенсация проезда/билетов до 5 000 руб (или покупка электронного билета координатором).
• Авансы: еженедельно от 5 000 до 20 000 руб на карту любого банка.
• Оформление: официальное по самозанятости (налог 6% компания полностью компенсирует СВЕРХУ ставки за свой счет, кандидат получает чистые деньги без удержаний).
• Долги / ФССП / приставы: выплаты можно официально получать на карту любого родственника (жены, мамы, брата), приставы их не спишут.

СТИЛЬ ОБЩЕНИЯ:
- Живой, теплый, уверенный, уважительный тон.
- Краткость: 1–3 естественных емких предложения (до 350-400 символов). Без канцеляризмов и шаблонных роботизированных фраз.
- Всегда завершай сообщение открытым шагом (уточнением возраста/гражданства, либо запросом контактного номера телефона).
"""

def get_api_key() -> str:
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
        if os.path.exists(env_path):
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("GEMINI_API_KEY="):
                        api_key = line.split("=", 1)[1].strip()
                        break
    return api_key

def generate_llm_reply(
    cand_text: str,
    ad_title: str,
    facility_info: dict,
    cand_history: str = "",
    our_history: str = "",
    cand_name: str = "",
    dialogue_transcript: str = ""
) -> Optional[str]:
    api_key = get_api_key()
    if not api_key:
        return None

    facility_context = (
        f"ВАКАНСИЯ: {ad_title}\n"
        f"Объект: {facility_info.get('title', 'АБИ Владимир')}\n"
        f"Условия: ставка 3 700 - 4 900 руб/смена, бесплатное 3-разовое питание, бесплатное проживание в квартирах, авансы до 20 000 руб, компенсация проезда до 5 000 руб."
    )

    if dialogue_transcript:
        dialogue_block = f"ПОЛНАЯ ИСТОРИЯ ПЕРЕПИСКИ В ЧАТЕ:\n{dialogue_transcript}"
    else:
        history_parts = []
        if our_history:
            history_parts.append(f"Наши ответы ранее:\n{our_history}")
        if cand_history:
            history_parts.append(f"Сообщения кандидата ранее:\n{cand_history}")
        dialogue_block = "\n\n".join(history_parts)

    user_prompt = (
        f"{facility_context}\n\n"
        f"{dialogue_block}\n\n"
        f"ИМЯ СОБЕСЕДНИКА: {cand_name or 'Собеседник'}\n"
        f"САМОЕ СВЕЖЕЕ СООБЩЕНИЕ ОТ КАНДИДАТА: \"{cand_text}\"\n\n"
        f"Напиши естественный, умный, чуткий ответ соискателю от лица рекрутера прямого работодателя. "
        f"Если кандидат внес уточнение или поправил нас (например, что ищет для брата, а не для мужа, или что возраст 25) — "
        f"мгновенно и вежливо подстройся. Ответ держи в пределах 1-3 предложений."
    )

    learned_rules_text = get_learned_rules_for_prompt()
    full_system_prompt = f"{SYSTEM_PROMPT}\n\nДОПОЛНИТЕЛЬНЫЕ ПРАВИЛА ИЗ БАЗЫ ЗНАНИЙ:\n{learned_rules_text}"

    models_to_try = [
        "gemini-3.1-flash-lite",
        "gemini-3.5-flash-lite",
        "gemini-flash-latest",
        "gemini-3.1-flash-lite-preview"
    ]

    for m in models_to_try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent?key={api_key}"
        gen_cfg = {
            "temperature": 0.7,
            "maxOutputTokens": 350
        }
        if "gemini-3" in m:
            gen_cfg["thinkingConfig"] = {"thinkingBudget": 0}

        payload = {
            "system_instruction": {
                "parts": [{"text": full_system_prompt}]
            },
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": user_prompt}]
                }
            ],
            "generationConfig": gen_cfg
        }
        try:
            resp = requests.post(url, json=payload, timeout=8)
            if resp.status_code == 200:
                data = resp.json()
                candidates = data.get("candidates", [])
                if candidates:
                    parts = candidates[0].get("content", {}).get("parts", [])
                    if parts and "text" in parts[0]:
                        reply = parts[0]["text"].strip()
                        # Safety filter
                        if "фото паспорта" in reply.lower() and ("пришлите" in reply.lower() or "скиньте" in reply.lower()):
                            reply = reply.replace("фото паспорта", "подтверждение гражданства РФ")
                        if len(reply) > 450:
                            dot_idx = reply[:450].rfind(".")
                            if dot_idx > 100:
                                reply = reply[:dot_idx + 1]
                            else:
                                reply = reply[:450]
                        return reply
            else:
                logger.warning(f"Model {m} returned {resp.status_code}: {resp.text[:100]}")
        except Exception as e:
            logger.warning(f"Model {m} request failed: {e}")
            continue

    return None
