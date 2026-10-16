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

def sync_candidate_to_b24_deal(chat_id: str, cand_data: dict) -> bool:
    """
    Синхронизирует все полученные из чата данные в соответствующие поля сделки в Битрикс24:
    - Поля: ФИО, Телефон, Возраст, Код/Объект, Ссылка на чат Авито
    - Контакт: привязка и обновление номера телефона
    - Стадия сделки: перевод на 'В работе МЕСТНЫЕ' или 'В работе ВАХТА' при получении телефона
    - Таймлайн: фиксация комментария со всеми деталями (город, район, готовность, график)
    """
    try:
        # Поиск сделки по ссылке на чат Авито
        deal_id = None
        contact_id = None
        current_deal = None

        res = call_b24('crm.deal.list', {
            'filter': {'%UF_CRM_1770280572875': chat_id},
            'select': ['ID', 'TITLE', 'CONTACT_ID', 'STAGE_ID', 'UF_CRM_1775470003043', 'UF_CRM_1768816011673', 'UF_CRM_1768816356722']
        })
        deals = res.get('result', [])
        if not deals:
            # Резервный поиск по комментариям
            res = call_b24('crm.deal.list', {
                'filter': {'%COMMENTS': chat_id},
                'select': ['ID', 'TITLE', 'CONTACT_ID', 'STAGE_ID', 'UF_CRM_1775470003043', 'UF_CRM_1768816011673', 'UF_CRM_1768816356722']
            })
            deals = res.get('result', [])

        if deals:
            current_deal = deals[0]
            deal_id = current_deal.get('ID')
            contact_id = current_deal.get('CONTACT_ID')

        if not deal_id:
            print(f"[B24 SYNC] Сделка для чата {chat_id} пока не найдена в Битрикс24.")
            return False

        upd_fields = {}
        name = cand_data.get('name')
        age = cand_data.get('age')
        phone = cand_data.get('phone')
        vacancy = cand_data.get('vacancy') or current_deal.get('UF_CRM_1775470003043')

        if name and not current_deal.get('UF_CRM_1768816011673'):
            upd_fields['UF_CRM_1768816011673'] = name
        if age and (not current_deal.get('UF_CRM_1768816356722') or current_deal.get('UF_CRM_1768816356722') == '0'):
            upd_fields['UF_CRM_1768816356722'] = str(age)
        if vacancy and not current_deal.get('UF_CRM_1775470003043'):
            upd_fields['UF_CRM_1775470003043'] = vacancy

        # Обновление заголовка сделки
        obj_clean = vacancy or "Объект не определен"
        parts = [f"[{obj_clean}]"]
        if name:
            name_parts = name.split()
            clean_n = " ".join([p.capitalize() for p in name_parts[:2]])
            parts.append(clean_n)
        if phone:
            parts.append(phone)
        if age:
            parts.append(f"{age}л")

        if len(parts) > 1:
            upd_fields['TITLE'] = f"{parts[0]} {' | '.join(parts[1:])}"

        # Перевод стадии при получении телефона
        if phone:
            is_vahta = "вахт" in (vacancy or "").lower()
            upd_fields['STAGE_ID'] = 'UC_G0AG7S' if is_vahta else 'PREPARATION'

        if upd_fields:
            call_b24('crm.deal.update', {'id': deal_id, 'fields': upd_fields})

        # Привязка телефона к контакту
        if phone and contact_id:
            call_b24('crm.contact.update', {
                'id': contact_id,
                'fields': {
                    'PHONE': [{'VALUE': phone, 'VALUE_TYPE': 'WORK'}]
                }
            })

        # Запись деталей в историю таймлайна сделки
        details_list = []
        if name: details_list.append(f"• Имя: {name}")
        if phone: details_list.append(f"• Телефон: {phone}")
        if age: details_list.append(f"• Возраст: {age} лет")
        if cand_data.get('citizenship'): details_list.append(f"• Гражданство: {cand_data.get('citizenship')}")
        if cand_data.get('district'): details_list.append(f"• Район/Город: {cand_data.get('district')}")
        if cand_data.get('ready_date'): details_list.append(f"• Готовность к выходу: {cand_data.get('ready_date')}")
        if cand_data.get('schedule_pref'): details_list.append(f"• График/Пожелания: {cand_data.get('schedule_pref')}")

        if details_list:
            comment_text = "🤖 [B]Данные кандидата из переписки на Авито:[/B]\n" + "\n".join(details_list)
            call_b24('crm.timeline.comment.add', {
                'fields': {
                    'ENTITY_ID': deal_id,
                    'ENTITY_TYPE': 'deal',
                    'COMMENT': comment_text
                }
            })
        print(f"[B24 SYNC] Сделка #{deal_id} успешно обновлена данными кандидата!")
        return True
    except Exception as e:
        print(f"[B24 SYNC ERROR] {e}")
        return False

