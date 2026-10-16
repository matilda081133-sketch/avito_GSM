# -*- coding: utf-8 -*-
"""
Модуль синхронизации с Битрикс24:
1. Авто-переименование сделок: [Объект] Имя | Телефон | Возраст (Пол)
2. Заполнение полей: Объект, ФИО, Возраст, Пол
3. Перевод сделки на стадию 'Квалифицирован / Ждет звонка' при получении телефона
"""
import urllib.request
import json
import ssl
import re
from config import B24_WEBHOOK_URL

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

def call_b24(method: str, params: dict = None) -> dict:
    url = B24_WEBHOOK_URL.rstrip('/') + '/' + method
    data = json.dumps(params).encode('utf-8') if params else None
    headers = {'Content-Type': 'application/json'} if data else {}
    req = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, context=ctx) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except Exception as e:
        print(f"[B24 API ERROR] {method}: {e}")
        return {}

def parse_and_enhance_deal(deal: dict) -> dict:
    did = deal.get("ID")
    current_title = deal.get("TITLE") or ""
    comments = deal.get("COMMENTS") or ""
    
    # Объект / Вакансия
    object_name = deal.get("UF_CRM_1775470003043") or ""
    if not object_name:
        m_code = re.search(r'\[Код вакансии:\]\s*([^\n\r\[]+)', comments)
        if m_code:
            object_name = m_code.group(1).strip()
        else:
            m_title = re.search(r'\[Наименование:\]\s*([^\n\r\[]+)', comments)
            if m_title:
                raw_ad = m_title.group(1).strip().lower()
                if any(w in raw_ad for w in ["аби", "владимир", "мясо", "колбас", "вязанк"]):
                    object_name = "АБИ Владимир"
                elif any(w in raw_ad for w in ["тепофол", "кашир", "утеплит"]):
                    object_name = "Тепофол Кашира"
                elif any(w in raw_ad for w in ["фарма", "опалих", "красногорск", "аптеч"]):
                    object_name = "Фарма Опалиха"
                elif any(w in raw_ad for w in ["арник", "серпухов", "теплич"]):
                    object_name = "Арника Серпухов"
                elif any(w in raw_ad for w in ["смарт", "балаших"]):
                    object_name = "Смарт Балашиха"
                elif any(w in raw_ad for w in ["сдс", "брехов", "брёхов", "зоо"]):
                    object_name = "СДС Химки"
                elif any(w in raw_ad for w in ["бьюти", "дмитровск", "косметик"]):
                    object_name = "Бьюти Москва"
                elif any(w in raw_ad for w in ["шушар", "обухов", "спб", "санкт"]):
                    object_name = "СПб Шушары"
                elif "вахт" in raw_ad:
                    object_name = "Вахта"
                else:
                    object_name = m_title.group(1).strip()[:20]

    # Имя
    name = deal.get("UF_CRM_1768816011673") or ""
    if not name:
        m_name = re.search(r'\[Имя:\]\s*([^\n\r\[]+)', comments)
        if m_name:
            name = m_name.group(1).strip()
        else:
            m_cand = re.match(r'^([^-–]+)\s*[-–]', current_title)
            name = m_cand.group(1).strip() if m_cand else "Кандидат"
    name_clean = " ".join([w.capitalize() for w in name.split()[:2]])

    # Телефон
    phone = ""
    m_ph = re.search(r'\[Телефон:\]\s*([^\n\r\[]+)', comments)
    if m_ph:
        phone = m_ph.group(1).strip()
    if not phone:
        m_ph2 = re.search(r'\+7\d{10}', comments)
        if m_ph2:
            phone = m_ph2.group(0)

    # Пол
    gender = ""
    m_gender = re.search(r'\[Пол(?: соискателя)?:\]\s*([^\n\r\[]+)', comments)
    if m_gender:
        g = m_gender.group(1).strip().lower()
        if "муж" in g: gender = "М"
        elif "жен" in g: gender = "Ж"

    # Возраст
    age = str(deal.get("UF_CRM_1768816356722") or "")
    if not age or age == "0":
        m_age = re.search(r'\[Возраст(?: соискателя)?:\]\s*(\d+)', comments)
        if m_age: age = m_age.group(1).strip()

    # Сборка чистого заголовка
    parts = [f"[{object_name or 'Объект не определен'}]", name_clean]
    if phone: parts.append(phone)
    meta = []
    if age and age != "0": meta.append(f"{age}л")
    if gender: meta.append(f"({gender})")
    if meta: parts.append(" ".join(meta))
    
    new_title = " ".join([parts[0], " | ".join(parts[1:])])

    # Обновление в Битрикс24
    upd_fields = {
        "TITLE": new_title,
        "UF_CRM_1775470003043": object_name
    }
    if name_clean and not deal.get("UF_CRM_1768816011673"):
        upd_fields["UF_CRM_1768816011673"] = name_clean
    if age and age != "0" and not deal.get("UF_CRM_1768816356722"):
        upd_fields["UF_CRM_1768816356722"] = age

    res = call_b24("crm.deal.update", {"id": did, "fields": upd_fields})
    return {"id": did, "title": new_title, "success": res.get("result", False)}
