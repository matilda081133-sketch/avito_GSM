# -*- coding: utf-8 -*-
"""
CONTINUOUS LEARNING SYSTEM & RULE REPOSITORY FOR AI-RECRUITER
Обеспечивает постоянное самообучение ассистента на основе реальных диалогов с кандидатами.
1. Хранит и динамически обновляет базу правил (learned_rules.json).
2. Обогащает системный промпт LLM Gemini актуальными правилами и запретами.
3. Предоставляет детерминированный перехват для резервного движка (failover).
4. Проводит автоматический аудит последних диалогов на предмет ошибок, повторов и непонятых вопросов.
"""
import os
import json
import time
import logging
import re
from typing import Optional, Tuple, Dict, Any, List

logger = logging.getLogger("learning_system")

RULES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "learned_rules.json")

_RULES_CACHE = None
_RULES_CACHE_TIME = 0

def load_learned_rules() -> Dict[str, Any]:
    global _RULES_CACHE, _RULES_CACHE_TIME
    now = time.time()
    if _RULES_CACHE is not None and (now - _RULES_CACHE_TIME < 10):
        return _RULES_CACHE
    
    if os.path.exists(RULES_FILE):
        try:
            with open(RULES_FILE, "r", encoding="utf-8") as f:
                _RULES_CACHE = json.load(f)
                _RULES_CACHE_TIME = now
                return _RULES_CACHE
        except Exception as e:
            logger.error(f"Error loading learned_rules.json: {e}")
    
    _RULES_CACHE = {"hard_constraints": [], "faq_answers": {}, "learned_patterns": []}
    _RULES_CACHE_TIME = now
    return _RULES_CACHE

def save_learned_rules(data: Dict[str, Any]) -> bool:
    global _RULES_CACHE, _RULES_CACHE_TIME
    try:
        data["last_updated"] = time.strftime("%Y-%m-%dT%H:%M:%SZ")
        with open(RULES_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        _RULES_CACHE = data
        _RULES_CACHE_TIME = time.time()
        return True
    except Exception as e:
        logger.error(f"Error saving learned_rules.json: {e}")
        return False

def get_learned_rules_for_prompt() -> str:
    """Генерирует блок системного промпта для LLM из актуальной базы обученных правил."""
    rules = load_learned_rules()
    lines = ["\nОБУЧЕННЫЕ ПРАВИЛА И ЗАПРЕТЫ (ИЗ ЖИВОГО ОПЫТА ДИАЛОГОВ):"]
    
    for c in rules.get("hard_constraints", []):
        desc = c.get("description", "")
        if desc:
            lines.append(f"• ВАЖНО: {desc}")
            
    faq = rules.get("faq_answers", {})
    if faq:
        lines.append("\nТИПОВЫЕ ТОЧНЫЕ ОТВЕТЫ НА СЛОЖНЫЕ ВОПРОСЫ:")
        for k, v in faq.items():
            resp = v.get("response", "").replace("\n", " ")
            lines.append(f"• Тема '{k}': «{resp}»")

    return "\n".join(lines)

def match_learned_rule(cand_text: str, cand_name: str = "") -> Tuple[Optional[str], bool, str]:
    """
    Проверяет входящее сообщение соискателя по базе обученных правил.
    Возвращает (reply_text, is_disqualified, reason) либо (None, False, "").
    """
    t = cand_text.lower().strip()
    rules = load_learned_rules()
    
    name_prefix = f"{cand_name}, " if cand_name else ""
    
    # 1. Вопрос про гражданство Молдовы / СНГ ("берете ли граждан Молдовы?", "берете ли граждан СНГ?")
    is_cit_question = any(w in t for w in ["берете ли", "берёте ли", "берете", "берёте", "принимаете", "возьмете", "устроиться"]) and any(c in t for c in [
        "молдов", "молдав", "тираспол", "приднестров", "пмр", "узбек", "таджик", "кырг", "киргиз",
        "армян", "армен", "азерб", "казах", "беларус", "белорус", "рб", "украин", "снг", "патент", "внж", "иностран"
    ])
    
    if is_cit_question:
        reason = "Запрос по гражданству не РФ (отказ)"
        reply = (
            f"{name_prefix}к сожалению, на наши объекты согласование СБ и оформление возможно строго при наличии паспорта гражданина РФ. "
            "Граждан других государств (включая Молдову и страны СНГ) мы не принимаем. "
            "Спасибо за обращение и удачи в поиске работы!"
        )
        return reply, True, reason

    # 2. Упоминание иностранного номера или города за пределами РФ (Тирасполь, Кишинев, Бендеры, Молдова)
    foreign_geo_or_phone = any(w in t for w in [
        "молдавский номер", "номер молдавский", "+373", "тираспол", "кишинев", "бендер", "приднестров", "пмр", "молдов", "из молдовы", "в молдове"
    ])
    
    if foreign_geo_or_phone:
        reply = (
            f"{name_prefix}подскажите, пожалуйста, два момента:\n"
            "1. Является ли кандидат (или муж) гражданином РФ (есть ли действующий паспорт РФ на руках)?\n"
            "2. Где вы сейчас фактически находитесь (в РФ или за границей)?\n\n"
            "На наши объекты принимаем только с гражданством РФ, а дорогу компания покупает/компенсирует только по территории России."
        )
        return reply, False, ""

    # 3. Вопрос про покупку дороги из Тирасполя / Молдовы / зарубежья
    if any(k in t for k in ["дорогу из тирасполя", "билет из тирасполя", "дорогу из молдовы", "билет из молдовы", "дорогу из-за границы", "билет из-за границы"]):
        reply = (
            f"{name_prefix}билеты из-за границы компания дистанционно приобрести не может. "
            "Но если муж самостоятельно доедет до территории РФ (например, до Москвы), проезд от Москвы до Владимира мы полностью берем на себя, "
            "а также компенсируем дорогу по РФ до 5 000 ₽ в первую выплату. Скажите, у него есть паспорт РФ на руках?"
        )
        return reply, False, ""

    # 4. Проверка совпадения с другими FAQ в learned_rules.json
    faq = rules.get("faq_answers", {})
    for item in faq.values():
        patterns = item.get("patterns", [])
        if any(p in t for p in patterns):
            resp = item.get("response", "")
            if resp:
                return f"{name_prefix}{resp}", False, ""

    return None, False, ""

def record_chat_insight(chat_id: str, candidate_text: str, bot_response: str, issue_type: str, suggested_action: str):
    """Фиксирует проблемный кейс или ошибку ассистента для самообучения."""
    rules = load_learned_rules()
    insights = rules.setdefault("learned_patterns", [])
    
    # Не дублировать похожие записи
    for existing in insights[-20:]:
        if existing.get("chat_id") == chat_id and existing.get("candidate_text") == candidate_text:
            return
            
    insights.append({
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "chat_id": chat_id,
        "candidate_text": candidate_text,
        "bot_response": bot_response[:200],
        "issue_type": issue_type,
        "suggested_action": suggested_action
    })
    
    # Ограничиваем историю 50 записями
    rules["learned_patterns"] = insights[-50:]
    save_learned_rules(rules)
    logger.info(f"Recorded learning insight for chat {chat_id}: {issue_type}")
