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
B24_PORTAL_URL = "https://b24-4qx38o.bitrix24.ru"
from vacancy_rules import (
    PROJECT_ENUM_IDS,
    detect_citizenship_from_text,
    detect_city_from_text
)

import requests
import time

b24_session = requests.Session()
_last_b24_call_ts = 0.0
B24_MIN_CALL_INTERVAL = 0.35  # Троттлинг: максимум ~2.8 запроса в сек, защищает портал Битрикс24 от перегрузки

def call_b24(method: str, params: dict = None) -> dict:
    global _last_b24_call_ts
    url = B24_WEBHOOK_URL.rstrip('/') + '/' + method
    for attempt in range(3):
        try:
            elapsed = time.time() - _last_b24_call_ts
            if elapsed < B24_MIN_CALL_INTERVAL:
                time.sleep(B24_MIN_CALL_INTERVAL - elapsed)
            _last_b24_call_ts = time.time()

            if params:
                resp = b24_session.post(url, json=params, timeout=20)
            else:
                resp = b24_session.get(url, timeout=20)
            return resp.json()
        except Exception as e:
            if attempt == 2:
                print(f"[B24 API ERROR] {method}: {e}")
                return {}
            time.sleep(0.5)
    return {}

PROJECT_ID_TO_FACILITY = {
    "62": "АБИ Владимир",
    "132": "Фарма Цвет Опалиха",
    "3050": "Тепофол Кашира",
    "3052": "РусКлимат",
    "2988": "Аква Косметик",
    "2990": "ССТэнергомонтаж",
    "2966": "Склад Китайских Автозапчастей",
    "3054": "Прачечная",
    "64": "Прайм Спорт",
    "2962": "Основа Ногинск",
    "66": "Манго Фреш",
    "112": "Ока Спа Резорт",
    "114": "Единая Европа Элит",
    "116": "ЭкоТехПром",
    "118": "Бьюти Лайф",
    "120": "Рузком",
    "122": "Смарт Балашиха",
    "124": "СДС Химки",
    "126": "Стандарт СПБ",
    "128": "Королев Фарм",
    "130": "Арбиола Вармэ Рус",
    "134": "Азиано",
    "3086": "Арника",
    "3094": "Ароматный мир",
    "3096": "ДНС",
    "3098": "Смарт Family вахта"
}

def get_project_enum_id(facility_name: str, vacancy: str = "") -> str:
    """
    Возвращает точный ID проекта из списка UF_CRM_1768815865773.
    """
    comb = f"{facility_name or ''} {vacancy or ''}".lower()
    if any(w in comb for w in ["9268686", "новосистем", "служебн", "техподдержк"]):
        return ""
    if any(w in comb for w in ["запчаст", "китайск", "автозапчаст"]) or ("подольск" in comb and "коробок" in comb):
        return "2966" # Склад Китайских Автозапчастей
    elif any(w in comb for w in ["зоо", "смарт", "балаших", "салтыков", "кучин", "новомилет"]):
        return "122"  # Смарт Family (Балашиха)
    elif any(w in comb for w in ["аби", "владимир", "мясо", "колбас", "вязанк", "стародвор"]):
        return "62"   # АБИ Владимир
    elif any(w in comb for w in ["тепофол", "кашир", "утеплит"]):
        return "3050" # Тепофол Кашира
    elif any(w in comb for w in ["фарма", "опалих", "красногорск", "аптеч", "чай"]):
        return "132"  # Фарма Цвет
    elif any(w in comb for w in ["бьюти", "дмитровск", "косметик"]):
        return "118"  # Бьюти Лайф
    elif any(w in comb for w in ["спорт", "прайм", "электрик"]):
        return "64"   # Прайм Спорт
    elif any(w in comb for w in ["русклимат", "рус климат", "киржач"]):
        return "3052" # РусКлимат
    elif any(w in comb for w in ["аква косметик", "аквакосметик"]):
        return "2988" # Аква Косметик
    elif any(w in comb for w in ["сст", "энергомонтаж"]):
        return "2990" # ССТэнергомонтаж
    elif any(w in comb for w in ["прачечн"]):
        return "3054" # Прачечная
    elif any(w in comb for w in ["манго"]):
        return "66"   # Манго Фреш
    elif any(w in comb for w in ["сдс", "брехов", "пятницк", "химки", "khimki", "зеленоград", "zelenograd", "сходня", "лунево"]):
        return "124"  # СДС Химки
    elif any(w in comb for w in ["шушар", "спб", "санкт"]):
        return "126"  # Стандарт СПБ
    elif any(w in comb for w in ["королев фарм", "королёв"]):
        return "128"  # Королев Фарм
    elif any(w in comb for w in ["основа", "ногинск", "электросталь"]):
        return "2962" # Основа
    elif any(w in comb for w in ["арник", "серпухов"]):
        return "3086" # Арника
    elif "вахт" in comb:
        return "62"
    else:
        return "122"  # По умолчанию местный склад Смарт Family

def extract_facility_name(text: str = "", comments: str = "", vacancy_title: str = "", vacancy_url: str = "", proj_id: str = "", default: str = "Смарт Балашиха") -> str:
    """
    Определяет точное стандартизированное название объекта:
    Склад Китайских Автозапчастей, Смарт Балашиха, Фарма Цвет Опалиха,
    АБИ Владимир, СДС Химки, Тепофол Кашира, Бьюти Москва, Арника Серпухов и др.
    """
    combined = f"{text or ''} {comments or ''} {vacancy_title or ''} {vacancy_url or ''}".lower()
    if any(w in combined for w in ["9268686", "новосистем", "служебн", "техподдержк"]):
        return "Служебный звонок UIS"
    
    # 1. Автозапчасти Подольск
    if any(w in combined for w in ["автозапчаст", "запчаст", "китайск", "avtozapchast", "zapchast"]) or (any(p in combined for p in ["подольск", "podolsk"]) and any(k in combined for k in ["коробок", "распаков", "запчаст"])):
        return "Склад Китайских Автозапчастей"
    
    # 2. Фарма Опалиха / Красногорск / Чай / Травы
    if any(w in combined for w in ["фарма", "опалих", "красногорск", "аптеч", "чай", "травы", "трав", "фасовка чая", "сортировщик чая", "farma", "opalih", "krasnogorsk", "chaya"]):
        return "Фарма Цвет Опалиха"

    # 3. Зоотовары / Балашиха / Смарт
    if any(w in combined for w in ["зоо", "зоотовар", "смарт", "балаших", "салтыков", "кучин", "balashih", "zootovar", "zhivotnyh", "kuchin", "saltykov"]):
        return "Смарт Балашиха"

    # 4. СДС Химки / Брёхово
    if any(w in combined for w in ["сдс", "брехов", "брёхов", "пятницк", "фомичев", "brehov", "khimki", "sds", "зеленоград", "zelenograd", "сходня", "лунево", "ленинградк"]):
        return "СДС Химки"

    # 5. Тепофол Кашира
    if any(w in combined for w in ["тепофол", "кашир", "утеплит", "tepofol", "kashir"]):
        return "Тепофол Кашира"

    # 6. АБИ Владимир (строго при наличии владимир / мясо / колбаса / аби)
    if any(w in combined for w in ["аби", "владимир", "мясокомбинат", "мясо", "колбас", "вязанк", "стародвор", "vladimir", "kolbas"]):
        return "АБИ Владимир"

    # 7. Другие объекты по ключевым словам
    if any(w in combined for w in ["арник", "серпухов", "теплич"]):
        return "Арника"
    if any(w in combined for w in ["бьюти", "дмитровск", "косметик"]):
        return "Бьюти Лайф"
    if any(w in combined for w in ["шушар", "обухов", "спб", "санкт", "питер", "spb", "peterburg", "sankt", "lenoblast"]):
        return "Стандарт СПБ"
    if any(w in combined for w in ["зарайск", "обувн"]):
        return "Зарайск"
    if any(w in combined for w in ["рузком", "лыткарин", "руза", "ruza"]):
        return "Рузком"
    if any(w in combined for w in ["манго", "фреш", "домодедов"]):
        return "Манго Фреш"
    if any(w in combined for w in ["королев фарм", "королёв"]):
        return "Королев Фарм"
    if any(w in combined for w in ["экотехпром", "сортировк"]):
        return "ЭкоТехПром"
    if any(w in combined for w in ["основа", "электросталь", "ногинск"]):
        return "Основа Ногинск"
    if any(w in combined for w in ["павловский посад", "посад"]):
        return "Павловский Посад"
    if any(w in combined for w in ["звенигород"]):
        return "Звенигород"
    if any(w in combined for w in ["долгопрудн"]):
        return "Долгопрудный"
    if any(w in combined for w in ["мытищ"]):
        return "Мытищи"
    if any(w in combined for w in ["одинцов"]):
        return "Одинцово"
    if any(w in combined for w in ["тула", "донской"]):
        return "Тула"
    if any(w in combined for w in ["спорт", "прайм", "электрик"]):
        return "Прайм Спорт"
    if any(w in combined for w in ["клининг", "уборщик", "уборщиц", "уборк", "поломоечн"]):
        return "Клининг"
    if "вахт" in combined:
        return "СДС Химки"

    # 8. Проверяем системный проект Б24
    if str(proj_id) in PROJECT_ID_TO_FACILITY:
        return PROJECT_ID_TO_FACILITY[str(proj_id)]
    
    # 9. Резервный разбор текста объявления без скобок и обрезки
    bad_prefixes = ['объект не определен', 'новый лид', 'пропущенный лид', 'звонок', 'wappi', 'telegram', 'uis', 'whatsapp']
    if text and not any(bp in text.lower() for bp in bad_prefixes):
        clean = re.sub(r'[/\\|].*$', '', text).strip()
        clean = re.sub(r'^[\[\(]|[\]\)]$', '', clean).strip()
        clean = clean.lstrip('[').rstrip(']').strip()
        clean = re.sub(r'\b(?:вакансия|работа|на склад|теплый склад|срочно|требуется|ежедневные выплаты|без опыта)\b', '', clean, flags=re.IGNORECASE).strip()
        if len(clean) >= 3:
            return clean[:35].capitalize()
            
    return default or "Смарт Балашиха"

def parse_and_enhance_deal(deal: dict) -> dict:
    did = deal.get("ID")
    current_title = deal.get("TITLE") or ""
    comments = deal.get("COMMENTS") or ""
    
    raw_obj = deal.get("UF_CRM_1775470003043") or ""
    vac_title = deal.get("UF_CRM_1768817930019") or ""
    vac_url = deal.get("UF_CRM_1768819383825") or ""
    proj_id = str(deal.get("UF_CRM_1768815865773") or "")

    # Защита от ложного "Аби": если в raw_obj стоит "Аби", но в вакансии или url совсем другое — игнорируем
    comb_check = f"{vac_title} {vac_url} {comments}".lower()
    if raw_obj in ["Аби", "АБИ Владимир"] and not any(w in comb_check for w in ["аби", "владимир", "мясо", "колбас"]):
        raw_obj = ""

    m_title = re.search(r'\[Наименование:\]\s*([^\n\r\[]+)', comments)
    title_from_comm = m_title.group(1).strip() if m_title else ""
    
    object_name = extract_facility_name(
        text=raw_obj or vac_title or title_from_comm,
        comments=comments,
        vacancy_title=vac_title,
        vacancy_url=vac_url,
        proj_id=proj_id
    )

    # Имя и телефон кандидата
    phone = ""
    m_ph = re.search(r'\[Телефон:\]\s*([^\n\r\[]+)', comments)
    if m_ph:
        phone = m_ph.group(1).strip()
    if not phone:
        m_ph2 = re.search(r'\+7\d{10}', comments)
        if m_ph2:
            phone = m_ph2.group(0)

    name = deal.get("UF_CRM_1768816011673") or ""
    # Отсекаем названия кабинетов, которые Wappi ошибочно пишет в поле ФИО
    bad_names = ["работа без границ", "хороший выбор", "прямой работодатель", "avito wappi", "работа для вас", "wappi"]
    if any(b in name.lower() for b in bad_names):
        name = ""

    contact_id = deal.get("CONTACT_ID")
    if contact_id and (not name or not phone):
        c_res = call_b24("crm.contact.get", {"id": contact_id}).get("result", {})
        if not name:
            c_name = f"{c_res.get('LAST_NAME') or ''} {c_res.get('NAME') or ''}".strip()
            if c_name:
                name = c_name
        if not phone:
            phones = c_res.get("PHONE") or []
            if phones and isinstance(phones, list) and phones[0].get("VALUE"):
                phone = phones[0].get("VALUE")

    if not name:
        m_name = re.search(r'\[Имя:\]\s*([^\n\r\[]+)', comments)
        if m_name:
            name = m_name.group(1).strip()
        else:
            m_cand = re.search(r'\]\s*([A-Za-zА-Яа-яЁё\s]+?)\s*\|', current_title)
            if m_cand:
                name = m_cand.group(1).strip()
            else:
                m_cand2 = re.match(r'^([^-–|]+)', current_title)
                name = m_cand2.group(1).strip() if m_cand2 else "Кандидат"

    if any(b in name.lower() for b in bad_names):
        name = "Кандидат"

    name_clean = " ".join([w.capitalize() for w in name.split()[:2]])

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
    parts = [f"[{object_name or 'Смарт Балашиха'}]", name_clean]
    if phone: parts.append(phone)
    meta = []
    if age and age != "0": meta.append(f"{age}л")
    if gender: meta.append(f"({gender})")
    if meta: parts.append(" ".join(meta))
    
    new_title = " ".join([parts[0], " | ".join(parts[1:])])

    # Обновление в Битрикс24
    calculated_proj_enum = get_project_enum_id(object_name, f"{vac_title} {comments} {vac_url}")
    proj_enum = calculated_proj_enum if calculated_proj_enum else (proj_id if proj_id in PROJECT_ID_TO_FACILITY else "122")
    is_deal_vahta = "вахт" in (object_name or "").lower() or deal.get('STAGE_ID') == 'UC_G0AG7S'
    upd_fields = {
        "TITLE": new_title,
        "UF_CRM_1775470003043": object_name,
        "UF_CRM_1768815865773": proj_enum,
        "UF_CRM_1768816742475": "98" if is_deal_vahta else "96",
        "UF_CRM_1768827146250": "212" if is_deal_vahta else "214"
    }
    if name_clean and not deal.get("UF_CRM_1768816011673"):
        upd_fields["UF_CRM_1768816011673"] = name_clean
    if age and age != "0" and not deal.get("UF_CRM_1768816356722"):
        upd_fields["UF_CRM_1768816356722"] = age

    res = call_b24("crm.deal.update", {"id": did, "fields": upd_fields})
    return {"id": did, "title": new_title, "success": res.get("result", False)}

def get_or_reveal_candidate_phone(chat_id: str, client=None, context: dict = None) -> tuple:
    """
    Автоматически находит или раскрывает номер телефона кандидата («Показать телефон»):
    0. Проверяет раздел «Отклики» Авито (Avito Job Negotiations API) — куда попадают номера при отклике с резюме или по клику кнопки.
    1. Проверяет контекст чата на прикрепленное резюме Авито (GET /job/v1/resumes/{id}/contacts/).
    2. Ищет сделку и контакт в Битрикс24 по ID чата.
    3. Проверяет комментарии сделки (wa.me, [Телефон:], ID резюме).
    4. Если телефон раскрыт через Авито API, но отсутствует в CRM — сразу заносит его в Битрикс24!
    Возвращает (phone, source).
    """
    # 0. Проверка официального раздела «Отклики» Авито (Avito Job Negotiations API)
    if client and hasattr(client, 'get_negotiations_phone'):
        neg_p = client.get_negotiations_phone(chat_id)
        if neg_p:
            return neg_p, 'Avito Job Negotiations (Отклики Авито)'

    token = None
    if client:
        try:
            token = client.get_token()
        except Exception:
            token = None

    # 1. Проверка контекста чата на резюме (имитация кнопки "Показать телефон" на Авито)
    if context and context.get('type') == 'item':
        val = context.get('value', {})
        url = val.get('url', '')
        item_id = val.get('id')
        if item_id and token and ('/rezume/' in url or 'резюме' in val.get('title', '').lower()):
            try:
                r_url = f'https://api.avito.ru/job/v1/resumes/{item_id}/contacts/'
                req = urllib.request.Request(r_url, headers={'Authorization': f'Bearer {token}'})
                with urllib.request.urlopen(req, context=ctx) as resp:
                    cdata = json.loads(resp.read().decode('utf-8'))
                    for ct in cdata.get('contacts', []):
                        if ct.get('type') == 'phone' and ct.get('value'):
                            raw_p = re.sub(r'[^\d+]', '', str(ct.get('value')))
                            p = '+7' + raw_p[-10:] if len(raw_p) >= 10 else raw_p
                            return p, 'Avito Resume API (Показать телефон)'
            except Exception:
                pass

    # 2. Поиск сделки в Битрикс24
    res = call_b24('crm.deal.list', {
        'filter': {'%UF_CRM_1770280572875': chat_id},
        'select': ['ID', 'TITLE', 'CONTACT_ID', 'COMMENTS', 'UF_CRM_1775470003043']
    })
    deals = res.get('result', [])
    if not deals:
        res = call_b24('crm.deal.list', {
            'filter': {'%COMMENTS': chat_id},
            'select': ['ID', 'TITLE', 'CONTACT_ID', 'COMMENTS', 'UF_CRM_1775470003043']
        })
        deals = res.get('result', [])

    if deals:
        deal = deals[0]
        cid = deal.get('CONTACT_ID')
        if cid:
            c = call_b24('crm.contact.get', {'id': cid}).get('result', {})
            phones = c.get('PHONE', [])
            if phones and phones[0].get('VALUE'):
                return phones[0].get('VALUE'), 'B24 Contact'

        comments = deal.get('COMMENTS') or ''
        m_ph = re.search(r'\[Телефон:\]\s*([^\n\r\[]+)', comments)
        if m_ph and len(m_ph.group(1).strip()) >= 10:
            return m_ph.group(1).strip(), 'B24 Deal Comment'

        m_wa = re.search(r'wa\.me/\+?(\d{11})', comments)
        if m_wa:
            return '+' + m_wa.group(1), 'B24 WA Link'

        m_res = re.search(r'(?:резюме|resume)[^\d]*(\d{8,12})', comments, re.IGNORECASE)
        if m_res and token:
            r_id = m_res.group(1)
            try:
                r_url = f'https://api.avito.ru/job/v1/resumes/{r_id}/contacts/'
                req = urllib.request.Request(r_url, headers={'Authorization': f'Bearer {token}'})
                with urllib.request.urlopen(req, context=ctx) as resp:
                    cdata = json.loads(resp.read().decode('utf-8'))
                    for ct in cdata.get('contacts', []):
                        if ct.get('type') == 'phone' and ct.get('value'):
                            raw_p = re.sub(r'[^\d+]', '', str(ct.get('value')))
                            p = '+7' + raw_p[-10:] if len(raw_p) >= 10 else raw_p
                            return p, 'Avito Job API from B24 Comment'
            except Exception:
                pass

    return None, None

# Команда рекрутеров в Битрикс24
VALERIA_MARKETER_ID = 82166    # Валерия Цицилина (Маркетолог)
RECRUITERS = [
    {"id": 40, "name": "Виктория Фарафонова"},
    {"id": 32, "name": "Наталья Кучма"},
    {"id": 81596, "name": "Маргарита Бабынина"},
]
RECRUITER_IDS = [40, 32, 81596]
NOTIFY_USER_IDS = [40, 32, 81596] # Исключена Валерия (82166) по запросу отключения уведомлений

_recruiter_cycle = 0

def get_next_recruiter_id() -> int:
    global _recruiter_cycle
    rec_id = RECRUITER_IDS[_recruiter_cycle % len(RECRUITER_IDS)]
    _recruiter_cycle += 1
    return rec_id

def get_non_target_category_info():
    """
    Проверяет наличие отдельной воронки 'Нецелевые' в Битрикс24.
    Возвращает (category_id, stage_id).
    Если отдельная воронка еще не создана — возвращает (None, 'LOSE') для перемещения в стадию "Неуспех".
    """
    try:
        cats = call_b24('crm.dealcategory.list').get('result', [])
        for c in cats:
            name_low = (c.get('NAME') or '').lower()
            if 'нецелев' in name_low or 'нелеквид' in name_low:
                cat_id = c.get('ID')
                stages = call_b24('crm.dealcategory.stage.list', {'id': cat_id}).get('result', [])
                initial_stage = stages[0]['STATUS_ID'] if stages else f"C{cat_id}:NEW"
                return cat_id, initial_stage
    except Exception as e:
        print("get_non_target_category_info error:", e)
    return None, 'LOSE'

class DealSyncResult(int):
    """
    Универсальный результат синхронизации:
    - Ведет себя как int/str (deal_id) для полной обратной совместимости.
    - Поддерживает распаковку кортежа: deal_id, responsible_id = sync_candidate_to_b24_deal(...)
    - Предоставляет свойства .deal_id, .responsible_id, .is_disqualified
    """
    def __new__(cls, deal_id, responsible_id=None, is_disqualified=False):
        val = int(deal_id) if deal_id else 0
        obj = super().__new__(cls, val)
        obj.deal_id = int(deal_id) if deal_id else None
        obj.responsible_id = int(responsible_id) if responsible_id else None
        obj.is_disqualified = bool(is_disqualified)
        return obj

    def __iter__(self):
        yield self.deal_id
        yield self.responsible_id

def sync_candidate_to_b24_deal(chat_id: str, cand_data: dict, is_disqualified: bool = False, disqualify_reason: str = "") -> DealSyncResult:
    """
    Синхронизирует все полученные из чата данные в соответствующие поля сделки в Битрикс24:
    - Поля: ФИО, Телефон, Возраст, Код/Объект, Ссылка на чат Авито
    - Контакт: привязка и обновление номера телефона
    - Ответственный менеджер:
        * Смена ответственного допустима ТОЛЬКО на стадии "Новый отклик" ('NEW') или при создании новой сделки.
        * Если сделка ушла дальше стадии 'NEW' (менеджер обработал кандидата / взят в работу),
          менеджер закреплен за кандидатом НАВСЕГДА. Робот никогда его не перезаписывает!
          Сменить его можно только вручную в интерфейсе Битрикс24.
    - Нецелевые кандидаты:
        * Если кандидат нецелевой (отклик не соответствует требованиям вакансии по возрасту, полу,
          гражданству или в процессе опроса), отправляем его в отдельную воронку 'Нецелевые' (или стадию LOSE).
        * Заголовок сделки маркируется префиксом [НЕЦЕЛЕВОЙ], в таймлайн пишется точная причина.
    - Возвращает DealSyncResult (deal_id, responsible_id)
    """
    try:
        # Поиск сделки по ссылке на чат Авито
        deal_id = None
        contact_id = None
        current_deal = None

        res = call_b24('crm.deal.list', {
            'filter': {'%UF_CRM_1770280572875': chat_id},
            'select': ['ID', 'TITLE', 'CONTACT_ID', 'STAGE_ID', 'ASSIGNED_BY_ID', 'CATEGORY_ID', 
                       'UF_CRM_1775470003043', 'UF_CRM_1768815865773', 'UF_CRM_1768816011673', 
                       'UF_CRM_1768816356722', 'UF_CRM_1768816331873', 'UF_CRM_1768816641561', 'UF_CRM_1768816560167']
        })
        deals = res.get('result', [])
        if not deals:
            # Резервный поиск по комментариям
            res = call_b24('crm.deal.list', {
                'filter': {'%COMMENTS': chat_id},
                'select': ['ID', 'TITLE', 'CONTACT_ID', 'STAGE_ID', 'ASSIGNED_BY_ID', 'CATEGORY_ID', 
                           'UF_CRM_1775470003043', 'UF_CRM_1768815865773', 'UF_CRM_1768816011673', 
                           'UF_CRM_1768816356722', 'UF_CRM_1768816331873', 'UF_CRM_1768816641561', 'UF_CRM_1768816560167']
            })
            deals = res.get('result', [])

        if deals:
            nt_cat_id, _ = get_non_target_category_info()
            if is_disqualified and nt_cat_id:
                # Если кандидат нецелевой, выбираем сделку, которая уже в воронке Нецелевые (44)
                c44_deal = next((d for d in deals if str(d.get('CATEGORY_ID')) == str(nt_cat_id)), None)
                current_deal = c44_deal if c44_deal else deals[0]
            else:
                # Если кандидат целевой, выбираем активную сделку в воронке соискателей
                act_deal = next((d for d in deals if str(d.get('CATEGORY_ID')) != str(nt_cat_id) and d.get('STAGE_ID') != 'LOSE'), None)
                if not act_deal:
                    act_deal = next((d for d in deals if str(d.get('CATEGORY_ID')) != str(nt_cat_id)), None)
                current_deal = act_deal if act_deal else deals[0]

            deal_id = current_deal.get('ID')
            contact_id = current_deal.get('CONTACT_ID')

        name = cand_data.get('name')
        age = cand_data.get('age')
        phone = cand_data.get('phone')
        vacancy = cand_data.get('vacancy') or (current_deal.get('UF_CRM_1775470003043') if current_deal else '')

        existing_stage = current_deal.get('STAGE_ID', '') if current_deal else ''
        existing_assigned = int(current_deal.get('ASSIGNED_BY_ID') or 0) if current_deal else 0

        # =====================================================================
        # ПРАВИЛО ЗАКРЕПЛЕНИЯ МЕНЕДЖЕРА:
        # Смена ответственного допустима ТОЛЬКО на стадии "Новый отклик" ('NEW').
        # Дальше, если ответственный менеджер закрепился и обработал кандидата,
        # кандидат закрепляется за ним НАВСЕГДА. Только вручную можно сменить ответственного!
        # =====================================================================
        if not deal_id:
            # СТРОГИЙ РЕГЛАМЕНТ: если номера телефона нет и кандидат не дисквалифицирован,
            # сделку в CRM НЕ создаем до тех пор, пока не узнаем номер (в чате или из Авито)!
            if not phone and not is_disqualified:
                print(f"[B24 SYNC] Отклик в чате {chat_id}: номер еще не получен. Сделка в CRM НЕ создается до получения контакта.", flush=True)
                return DealSyncResult(None, None, False)

            # Новая сделка — распределяем дежурного рекрутера по очереди
            responsible_id = get_next_recruiter_id()
            facility_name = extract_facility_name(text=vacancy, comments="")
            proj_enum = get_project_enum_id(facility_name, vacancy)
            is_vahta = "вахт" in (vacancy or "").lower()
            
            parts = [f"[{facility_name}]"]
            if is_disqualified:
                parts.insert(0, "[НЕЦЕЛЕВОЙ]")
            if cand_data.get('is_text_only'):
                parts.insert(0, "[ТОЛЬКО ПИСАТЬ! НЕ ЗВОНИТЬ - ГЛУХОНЕМОЙ]")
            if name:
                name_parts = name.split()
                clean_n = " ".join([p.capitalize() for p in name_parts[:2]])
                parts.append(clean_n)
            if phone:
                parts.append(phone)
            if age and age != "0":
                parts.append(f"{age}л")

            init_stage = 'NEW'
            init_cat_id = 0
            if is_disqualified:
                nt_cat, nt_st = get_non_target_category_info()
                if nt_cat:
                    init_cat_id = nt_cat
                    init_stage = nt_st
                else:
                    init_stage = 'LOSE'
            elif phone:
                init_stage = 'UC_G0AG7S' if is_vahta else 'PREPARATION'

            deal_fields = {
                'TITLE': " ".join(parts),
                'STAGE_ID': init_stage,
                'SOURCE_ID': 'UC_25GHWZ', # Авито Прямой работодатель
                'ASSIGNED_BY_ID': responsible_id,
                'UF_CRM_1770280572875': f"https://www.avito.ru/profile/messenger/channel/{chat_id}",
                'UF_CRM_1775470003043': facility_name,
                'UF_CRM_1768815865773': proj_enum,
                'UF_CRM_1768816011673': name or '',
                'UF_CRM_1768816356722': str(age) if age else ''
            }
            if init_cat_id:
                deal_fields['CATEGORY_ID'] = init_cat_id

            # Авто-заполнение гражданства (если кандидат ответил)
            cit_val = cand_data.get('citizenship') or ''
            cit_enum, _ = detect_citizenship_from_text(cit_val)
            if cit_enum:
                deal_fields['UF_CRM_1768816331873'] = cit_enum

            # Авто-заполнение города проживания (если кандидат ответил)
            city_val = cand_data.get('district') or cand_data.get('city') or ''
            city_name, city_id = detect_city_from_text(city_val)
            if city_name:
                deal_fields['UF_CRM_1768816641561'] = city_name
            if city_id:
                deal_fields['UF_CRM_1768816560167'] = city_id

            # Авто-заполнение поля НАПРАВЛЕН (96: На смену, 98: На заселение)
            # и типа занятости (212: Вахта, 214: Местный/ подработка)
            deal_fields['UF_CRM_1768816742475'] = '98' if is_vahta else '96'
            deal_fields['UF_CRM_1768827146250'] = '212' if is_vahta else '214'

            if phone:
                clean_p = re.sub(r'\D', '', phone)[-10:]
                existing_contact_id = None
                dup_res = call_b24('crm.duplicate.findbycomm', {'type': 'PHONE', 'values': [phone, f"+7{clean_p}", f"8{clean_p}"]})
                dup_result = dup_res.get('result')
                if isinstance(dup_result, dict):
                    c_list = dup_result.get('CONTACT', [])
                    if c_list:
                        existing_contact_id = c_list[0]
                
                if existing_contact_id:
                    contact_id = existing_contact_id
                    print(f"[B24 SYNC] Найден существующий контакт #{contact_id} для {phone}, используем его.")
                    # Проверяем, есть ли уже активная открытая сделка по этому контакту
                    open_deals = call_b24('crm.deal.list', {
                        'filter': {'CONTACT_ID': existing_contact_id, 'CLOSED': 'N', 'CATEGORY_ID': 0},
                        'select': ['ID', 'TITLE', 'STAGE_ID', 'ASSIGNED_BY_ID']
                    }).get('result', [])
                    if open_deals:
                        deal_id = open_deals[0]['ID']
                        current_deal = open_deals[0]
                        print(f"[B24 SYNC] У контакта #{existing_contact_id} уже есть активная сделка #{deal_id}! Не создаем дубль, привязываем чат.")
                else:
                    c_res = call_b24('crm.contact.add', {
                        'fields': {
                            'NAME': name or 'Кандидат',
                            'PHONE': [{'VALUE': phone, 'VALUE_TYPE': 'WORK'}]
                        }
                    })
                    contact_id = c_res.get('result')
                
                if contact_id:
                    deal_fields['CONTACT_ID'] = contact_id
            
            if not deal_id:
                d_res = call_b24('crm.deal.add', {'fields': deal_fields})
                deal_id = d_res.get('result')
                print(f"[B24 SYNC] Создана новая сделка #{deal_id} (Менеджер {responsible_id}) для чата {chat_id}")
                current_deal = deal_fields
        else:
            # Сделка уже существовала ранее
            if existing_stage == 'NEW' or not existing_stage:
                # На стадии "Новый отклик" допустимо первичное закрепление или ротация
                if existing_assigned in RECRUITER_IDS:
                    responsible_id = existing_assigned
                else:
                    responsible_id = get_next_recruiter_id()
            else:
                # СТРОЖАЙШЕЕ ПРАВИЛО: стадия ушла дальше 'NEW' — менеджер зафиксирован НАВСЕГДА!
                # Бот НИКОГДА не перезаписывает ASSIGNED_BY_ID!
                responsible_id = existing_assigned if existing_assigned else get_next_recruiter_id()

        comm = current_deal.get('COMMENTS', '') if current_deal else ''
        existing_obj = current_deal.get('UF_CRM_1775470003043', '') if current_deal else ''
        facility_name = extract_facility_name(text=existing_obj or vacancy, comments=comm)
        proj_enum = get_project_enum_id(facility_name, vacancy)

        upd_fields = {}
        if name and not current_deal.get('UF_CRM_1768816011673'):
            upd_fields['UF_CRM_1768816011673'] = name
        if age and (not current_deal.get('UF_CRM_1768816356722') or current_deal.get('UF_CRM_1768816356722') == '0'):
            upd_fields['UF_CRM_1768816356722'] = str(age)
        
        # Поле ПРОЕКТ заполняется ВСЕГДА автоматически
        upd_fields['UF_CRM_1775470003043'] = facility_name
        upd_fields['UF_CRM_1768815865773'] = proj_enum

        # Поле НАПРАВЛЕН (96: На смену, 98: На заселение) исходя из стадий "В работе ВАХТА" или "В работе МЕСТНЫЕ"
        is_deal_vahta = (
            existing_stage == 'UC_G0AG7S' or 
            'вахт' in (vacancy or '').lower() or 
            'вахт' in (facility_name or '').lower() or
            current_deal.get('UF_CRM_1768827146250') == '212'
        )
        upd_fields['UF_CRM_1768816742475'] = '98' if is_deal_vahta else '96'
        upd_fields['UF_CRM_1768827146250'] = '212' if is_deal_vahta else '214'

        # Авто-заполнение гражданства (если кандидат ответил, а в сделке еще не заполнено)
        cit_val = cand_data.get('citizenship') or ''
        cit_enum, _ = detect_citizenship_from_text(cit_val)
        if cit_enum and not current_deal.get('UF_CRM_1768816331873'):
            upd_fields['UF_CRM_1768816331873'] = cit_enum

        # Авто-заполнение города проживания (если кандидат ответил, а в сделке еще не заполнено)
        city_val = cand_data.get('district') or cand_data.get('city') or ''
        city_name, city_id = detect_city_from_text(city_val)
        if city_name and not current_deal.get('UF_CRM_1768816641561'):
            upd_fields['UF_CRM_1768816641561'] = city_name
        if city_id and not current_deal.get('UF_CRM_1768816560167'):
            upd_fields['UF_CRM_1768816560167'] = city_id

        # Обновление заголовка сделки: строго [Объект] Имя | Телефон | Возраст
        parts = [f"[{facility_name}]"]
        if is_disqualified:
            parts.insert(0, "[НЕЦЕЛЕВОЙ]")
        if cand_data.get('is_text_only'):
            parts.insert(0, "[ТОЛЬКО ПИСАТЬ! НЕ ЗВОНИТЬ - ГЛУХОНЕМОЙ]")
        if name:
            name_parts = name.split()
            clean_n = " ".join([p.capitalize() for p in name_parts[:2]])
            parts.append(clean_n)
        if phone:
            parts.append(phone)
        if age and age != "0":
            parts.append(f"{age}л")

        upd_fields['TITLE'] = " ".join(parts)
        if not current_deal.get('SOURCE_ID'):
            upd_fields['SOURCE_ID'] = 'UC_25GHWZ'

        # Смена ответственного допустима ТОЛЬКО на стадии "Новый отклик"
        if (existing_stage == 'NEW' or not existing_stage) and responsible_id != existing_assigned:
            upd_fields['ASSIGNED_BY_ID'] = responsible_id

        # Маршрутизация стадий и воронок
        if is_disqualified:
            nt_cat_id, nt_stage = get_non_target_category_info()
            if nt_cat_id:
                if str(current_deal.get('CATEGORY_ID')) != str(nt_cat_id):
                    # В Bitrix24 REST API crm.deal.update не меняет CATEGORY_ID существующей сделки.
                    # Создаем сделку напрямую в воронке Нецелевые (44) и закрываем старую в воронке 0.
                    cat44_fields = dict(upd_fields)
                    cat44_fields['CATEGORY_ID'] = nt_cat_id
                    cat44_fields['STAGE_ID'] = nt_stage
                    cat44_fields['SOURCE_ID'] = current_deal.get('SOURCE_ID') or 'UC_25GHWZ'
                    cat44_fields['ASSIGNED_BY_ID'] = current_deal.get('ASSIGNED_BY_ID') or responsible_id
                    cat44_fields['CONTACT_ID'] = current_deal.get('CONTACT_ID')
                    cat44_fields['UF_CRM_1770280572875'] = current_deal.get('UF_CRM_1770280572875') or f'https://www.avito.ru/profile/messenger/channel/{chat_id}'
                    c44_res = call_b24('crm.deal.add', {'fields': cat44_fields})
                    new_c44_id = c44_res.get('result')
                    if new_c44_id:
                        call_b24('crm.deal.update', {
                            'id': deal_id, 
                            'fields': {
                                'STAGE_ID': 'LOSE', 
                                'COMMENTS': f'Перенесено в воронку Нецелевые (сделка #{new_c44_id})'
                            }
                        })
                        deal_id = new_c44_id
                        print(f"[B24 SYNC] Сделка пересоздана в отдельной воронке 'Нецелевые': #{deal_id}")
                else:
                    upd_fields['STAGE_ID'] = nt_stage
                    print(f"[B24 SYNC] Сделка #{deal_id} обновлена в воронке 'Нецелевые' (Stage: {nt_stage})")
            else:
                upd_fields['STAGE_ID'] = 'LOSE'
                print(f"[B24 SYNC] Сделка #{deal_id} дисквалифицирована -> перемещена в стадию LOSE (Неуспех)")
        elif existing_stage in ['EXECUTING', 'UC_NDZ2', 'UC_NDZ3']:
            # ВОССТАНОВЛЕНИЕ ИЗ НДЗ: Кандидат ответил в чате!
            is_vahta = "вахт" in (vacancy or "").lower() or (current_deal.get('UF_CRM_1768827146250') == '212')
            target_stage = 'UC_G0AG7S' if is_vahta else 'PREPARATION'
            upd_fields['STAGE_ID'] = target_stage
            print(f"[B24 SYNC] Кандидат ответил в чате после НДЗ! Перевод сделки #{deal_id} в {target_stage}")
            
            # Ставим срочную автозадачу ответственному рекрутеру
            deal_url = f"{B24_PORTAL_URL}/crm/deal/details/{deal_id}/"
            cand_display_name = name or 'Кандидат'
            task_title = f"🔥 ПЕРЕЗВОНИТЬ (ОТВЕТ ПОСЛЕ НДЗ): [{facility_name}] {cand_display_name} ({phone or 'в сделке'})"
            task_desc = (
                f"🚨 🔥 [B]КАНДИДАТ ОТВЕТИЛ В ЧАТЕ ПОСЛЕ НЕДОЗВОНА (НДЗ)![/B]\n\n"
                f"📍 [B]Объект:[/B] [{facility_name}]\n"
                f"👤 [B]Кандидат:[/B] {cand_display_name}\n"
                f"📞 [B]Телефон:[/B] [B]{phone or 'в сделке'}[/B]\n\n"
                f"👉 [B][URL={deal_url}]ОТКРЫТЬ СДЕЛКУ #{deal_id} И СРОЧНО ПЕРЕЗВОНИТЬ КАНДИДАТУ[/URL][/B]\n\n"
                f"⏱ Норматив: совершить звонок в течение 10–15 минут!\n"
                f"Стадия сделки автоматически возвращена из «НДЗ» в «В работе»."
            )
            try:
                call_b24('tasks.task.add', {
                    'fields': {
                        'TITLE': task_title,
                        'DESCRIPTION': task_desc,
                        'RESPONSIBLE_ID': responsible_id,
                        'PRIORITY': 2,
                        'DEADLINE': (datetime.datetime.now() + datetime.timedelta(minutes=15)).strftime('%Y-%m-%d %H:%M:%S'),
                        'UF_CRM_TASK': [f'D_{deal_id}']
                    }
                })
                alert_text = (
                    f"🚨 🔥 [B]ОТВЕТ ПОСЛЕ НДЗ ({facility_name})![/B]\n"
                    f"Кандидат {cand_display_name} ({phone or 'номер в сделке'}) ответил в чате Авито!\n"
                    f"⏱ Срочно наберите кандидата в течение 15 минут!\n"
                    f"👉 [URL={deal_url}]Открыть сделку #{deal_id}[/URL]"
                )
                call_b24('im.notify.system.add', {
                    'USER_ID': responsible_id,
                    'MESSAGE': alert_text
                })
            except Exception as e_ndz:
                print(f"[B24 SYNC ERROR] Ошибка постановки задачи после НДЗ: {e_ndz}")
        elif phone:
            # 1. Если сделка ранее была в воронке Нецелевые (44) из-за отсутствия телефона,
            # а теперь номер получен -> ВЫВОДИМ В ВОРОНКУ СОИСКАТЕЛИ (Category 0)!
            if str(current_deal.get('CATEGORY_ID')) == '44':
                is_vahta = "вахт" in (vacancy or "").lower() or (current_deal.get('UF_CRM_1768827146250') == '212')
                target_stage = 'UC_G0AG7S' if is_vahta else 'PREPARATION'
                cat0_fields = dict(upd_fields)
                cat0_fields['CATEGORY_ID'] = 0
                cat0_fields['STAGE_ID'] = target_stage
                cat0_fields['SOURCE_ID'] = current_deal.get('SOURCE_ID') or 'UC_25GHWZ'
                cat0_fields['ASSIGNED_BY_ID'] = current_deal.get('ASSIGNED_BY_ID') or responsible_id
                cat0_fields['CONTACT_ID'] = current_deal.get('CONTACT_ID')
                cat0_fields['UF_CRM_1770280572875'] = current_deal.get('UF_CRM_1770280572875')
                c0_res = call_b24('crm.deal.add', {'fields': cat0_fields})
                new_c0_id = c0_res.get('result')
                if new_c0_id:
                    call_b24('crm.deal.update', {
                        'id': deal_id,
                        'fields': {
                            'STAGE_ID': 'C44:WON',
                            'COMMENTS': f'Получен номер телефона {phone}. Переведено в воронку Соискатели (сделка #{new_c0_id})'
                        }
                    })
                    deal_id = new_c0_id
                    print(f"[B24 SYNC] Кандидат предоставил номер {phone}! Сделка успешно выведена из 'Нецелевые' в воронку 'Соискатели': #{deal_id}")
            elif existing_stage == 'NEW' or not existing_stage:
                is_vahta = "вахт" in (vacancy or "").lower()
                upd_fields['STAGE_ID'] = 'UC_G0AG7S' if is_vahta else 'PREPARATION'
        elif not phone and not is_disqualified:
            # 2. Если сделка создана Wappi в воронке 0 (Соискатели) БЕЗ НОМЕРА ТЕЛЕФОНА ->
            # Переводим в воронку «Нецелевые» (44), чтобы не засорять воронку соискателей!
            if str(current_deal.get('CATEGORY_ID')) == '0' and (existing_stage == 'NEW' or not existing_stage):
                nt_cat_id, nt_stage = get_non_target_category_info() # 44, C44:NEW
                if nt_cat_id:
                    cat44_fields = dict(upd_fields)
                    cat44_fields['CATEGORY_ID'] = nt_cat_id
                    cat44_fields['STAGE_ID'] = nt_stage
                    cat44_fields['SOURCE_ID'] = current_deal.get('SOURCE_ID') or 'UC_25GHWZ'
                    cat44_fields['ASSIGNED_BY_ID'] = current_deal.get('ASSIGNED_BY_ID') or responsible_id
                    cat44_fields['CONTACT_ID'] = current_deal.get('CONTACT_ID')
                    cat44_fields['UF_CRM_1770280572875'] = current_deal.get('UF_CRM_1770280572875')
                    c44_res = call_b24('crm.deal.add', {'fields': cat44_fields})
                    new_c44_id = c44_res.get('result')
                    if new_c44_id:
                        call_b24('crm.deal.delete', {'id': deal_id})
                        deal_id = new_c44_id
                        print(f"[B24 SYNC] Сделка без номера переведена в воронку 'Нецелевые': #{deal_id} (старая сделка в воронке 0 удалена)")

        if upd_fields and str(current_deal.get('CATEGORY_ID')) != '44':
            call_b24('crm.deal.update', {'id': deal_id, 'fields': upd_fields})

        if cand_data.get('is_text_only'):
            try:
                call_b24('crm.timeline.comment.add', {
                    'fields': {
                        'ENTITY_ID': deal_id,
                        'ENTITY_TYPE': 'deal',
                        'COMMENT': '⚠️ [B]ВНИМАНИЕ РЕКРУТЕРУ![/B] Кандидат не слышит / глухонемой! ЗВОНИТЬ ЗАПРЕЩЕНО! Писать строго в чат Авито!'
                    }
                })
            except Exception:
                pass

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
        if is_disqualified and disqualify_reason:
            details_list.append(f"❌ [КАНДИДАТ НЕЦЕЛЕВОЙ]: {disqualify_reason}")
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
        print(f"[B24 SYNC] Сделка #{deal_id} успешно обновлена данными кандидата! Менеджер: {responsible_id}")
        return DealSyncResult(deal_id, responsible_id, is_disqualified)
    except Exception as e:
        print(f"[B24 SYNC ERROR] {e}")
        return DealSyncResult(None, None, False)


