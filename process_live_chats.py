# -*- coding: utf-8 -*-
import urllib.request, json, ssl, time, sys, re, datetime
from avito_api import AvitoClient
from ai_engine import AIRecruiterEngine, extract_phone
from vacancy_rules import (
    detect_vacancy_profile, evaluate_candidate_fit,
    detect_citizenship_from_text, detect_city_from_text,
    PROJECT_ENUM_IDS
)
from b24_sync import (
    sync_candidate_to_b24_deal, get_or_reveal_candidate_phone, extract_facility_name,
    RECRUITERS, RECRUITER_IDS, NOTIFY_USER_IDS, VALERIA_MARKETER_ID, get_next_recruiter_id, DealSyncResult
)
from config import AVITO_CLIENT_ID, AVITO_CLIENT_SECRET, AVITO_USER_ID, B24_WEBHOOK_URL

sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

client = AvitoClient(AVITO_CLIENT_ID, AVITO_CLIENT_SECRET, AVITO_USER_ID)
engine = AIRecruiterEngine()

B24_PORTAL_URL = "https://b24-4qx38o.bitrix24.ru"

def create_b24_call_task(candidate_name: str, vacancy: str, phone: str, details: str, chat_id: str, responsible_id: int = None, deal_id: int = None, is_text_only: bool = False):
    if not responsible_id:
        responsible_id = get_next_recruiter_id()
    
    facility = extract_facility_name(text=vacancy)
    deal_url = f"{B24_PORTAL_URL}/crm/deal/details/{deal_id}/" if deal_id else f"{B24_PORTAL_URL}/crm/deal/list/"
    deadline_str = (datetime.datetime.now() + datetime.timedelta(minutes=15)).strftime('%Y-%m-%d %H:%M:%S')
    
    if is_text_only:
        task_title = f"💬 НАПИСАТЬ (НЕ ЗВОНИТЬ! ГЛУХОНЕМОЙ): [{facility}] {candidate_name} ({phone or 'номер в сделке'})"
        desc = (
            f"⚠️ [B]ВНИМАНИЕ РЕКРУТЕРУ! КАНДИДАТ НЕ СЛЫШИТ / ГЛУХОНЕМОЙ![/B]\n"
            f"[B]ЗВОНИТЬ СТРОГО ЗАПРЕЩЕНО![/B]\n\n"
            f"📍 [B]Объект:[/B] [{facility}]\n"
            f"👤 [B]Кандидат:[/B] {candidate_name}\n"
            f"📞 [B]Телефон кандидата:[/B] [B]{phone or 'уточняется'}[/B]\n"
            f"💼 [B]Вакансия:[/B] {vacancy}\n"
            f"📝 [B]Детали:[/B] {details}\n\n"
            f"👉 [B][URL={deal_url}]ОТКРЫТЬ СДЕЛКУ В БИТРИКС24[/URL][/B]\n\n"
            f"⏱ Норматив ответа: до 15 минут!\n"
            f"⚠️ [B]Общаться СТРОГО текстом:[/B] напишите кандидату в чат Авито!"
        )
    else:
        task_title = f"🔥 ПОЗВОНИТЬ: [{facility}] {candidate_name} ({phone or 'номер в сделке'})"
        desc = (
            f"🔥 [B]Кандидат оставил номер телефона и готов к звонку![/B]\n\n"
            f"📍 [B]Объект:[/B] [{facility}]\n"
            f"👤 [B]Кандидат:[/B] {candidate_name}\n"
            f"📞 [B]Телефон:[/B] [B]{phone or 'уточняется'}[/B]\n"
            f"💼 [B]Вакансия:[/B] {vacancy}\n"
            f"📝 [B]Детали:[/B] {details}\n\n"
            f"👉 [B][URL={deal_url}]ОТКРЫТЬ СДЕЛКУ В БИТРИКС24 ДЛЯ ЗВОНКА[/URL][/B]\n\n"
            f"⏱ Норматив звонка по рыночному SLA: 10–15 минут!\n"
            f"⚠️ В чат Авито писать НЕ нужно — переписку ведет бот, менеджер совершает прямой звонок по телефону!"
        )

    task_fields = {
        'TITLE': task_title,
        'DESCRIPTION': desc,
        'RESPONSIBLE_ID': responsible_id,
        'PRIORITY': 2,
        'DEADLINE': deadline_str
    }
    if deal_id:
        task_fields['UF_CRM_TASK'] = [f'D_{deal_id}']
    
    payload = json.dumps({'fields': task_fields}).encode('utf-8')
    req = urllib.request.Request(B24_WEBHOOK_URL + 'tasks.task.add', data=payload, headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=10) as resp:
            res = json.loads(resp.read().decode('utf-8'))
            task_id = res.get('result', {}).get('task', {}).get('id')
            print(f">>> CRM TASK CREATED for manager {responsible_id}! Task ID: {task_id}, Deal: {deal_id}, Facility: [{facility}]")
            
            # Отправка яркого, заметного уведомления о задаче
            send_b24_task_alert(
                candidate_name=candidate_name,
                facility=facility,
                phone=phone,
                details=details,
                deal_id=deal_id,
                responsible_id=responsible_id,
                is_text_only=is_text_only
            )
            return task_id
    except Exception as e:
        print("Task create error:", e)
        return None

def send_b24_task_alert(candidate_name: str, facility: str, phone: str, details: str, deal_id: int, responsible_id: int, is_text_only: bool = False):
    """
    Отправляет видное, привлекающее внимание уведомление в колокольчик/чат Битрикс24.
    Уведомления отправляются СТРОГО по новым задачам!
    """
    deal_url = f"{B24_PORTAL_URL}/crm/deal/details/{deal_id}/" if deal_id else f"{B24_PORTAL_URL}/crm/deal/list/"
    if is_text_only:
        msg = (
            f"🚨 💬 [B]КАНДИДАТ НЕ СЛЫШИТ / ГЛУХОНЕМОЙ! ЗВОНИТЬ ЗАПРЕЩЕНО![/B]\n\n"
            f"📍 [B]Объект:[/B] [{facility}]\n"
            f"👤 [B]Кандидат:[/B] {candidate_name}\n"
            f"📞 [B]Телефон:[/B] [B]{phone}[/B]\n"
            f"📝 [B]Детали:[/B] {details}\n\n"
            f"👉 [B][URL={deal_url}]ОТКРЫТЬ СДЕЛКУ #{deal_id}[/URL][/B]\n\n"
            f"⚠️ Кандидат просит писать в чат Авито! Звонить нельзя!"
        )
    else:
        msg = (
            f"🚨 🔥 [B]НОВАЯ ВАЖНАЯ ЗАДАЧА: СРОЧНО ПОЗВОНИТЬ КАНДИДАТУ![/B]\n\n"
            f"📍 [B]Объект:[/B] [{facility}]\n"
            f"👤 [B]Кандидат:[/B] {candidate_name}\n"
            f"📞 [B]Телефон:[/B] [B]{phone}[/B]\n"
            f"📝 [B]Детали:[/B] {details}\n\n"
            f"👉 [B][URL={deal_url}]НАЖМИТЕ ЗДЕСЬ, ЧТОБЫ ОТКРЫТЬ СДЕЛКУ #{deal_id} И ПОЗВОНИТЬ[/URL][/B]\n\n"
            f"⏱ Регламент первого звонка по SLA: до 15 минут!\n"
            f"⚠️ Задача привязана к сделке. В чат Авито писать не нужно — звоните по телефону!"
        )
    # Массовая рассылка отключена: уведомление получает ТОЛЬКО назначенный рекрутер
    recipients = [responsible_id] if responsible_id else []
    for uid in recipients:
        payload = json.dumps({'USER_ID': uid, 'MESSAGE': msg}).encode('utf-8')
        req = urllib.request.Request(B24_WEBHOOK_URL + 'im.notify.system.add', data=payload, headers={'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(req, context=ctx, timeout=10) as resp:
                pass
        except Exception:
            pass

def format_age(a):
    try:
        n = int(a)
        if 11 <= n % 100 <= 14: return f"{n} лет"
        elif n % 10 == 1: return f"{n} год"
        elif 2 <= n % 10 <= 4: return f"{n} года"
        else: return f"{n} лет"
    except:
        return f"{a} лет"

def extract_candidate_district(text: str) -> str:
    if not text:
        return ""
    # Очищаем системные уведомления Авито
    cleaned = re.sub(r'\[Системное сообщение\].*?(?:\n|$)', '', text, flags=re.IGNORECASE)
    cleaned = re.sub(r'данные сохранились.*?(?:\n|$)', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'кандидат откликнулся.*?(?:\n|$)', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'отклики.*?(?:\n|$)', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'ФИО\s*[—\-:]\s*[^\n\r]+', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'Гражданство\s*[—\-:]\s*[^\n\r]+', '', cleaned, flags=re.IGNORECASE)
    
    # Нормализация сокращений и склеенных символов (г.Истра -> г. Истра, МО,г. -> МО г. )
    normalized = re.sub(r'([гст]|мо|обл)\.([а-яa-z])', r'\1. \2', cleaned, flags=re.IGNORECASE)
    normalized = re.sub(r'([,;!?:])([а-яa-z])', r'\1 \2', normalized, flags=re.IGNORECASE)

    known_places = [
        "истра", "дедовск", "нахабино", "павловская слобода", "снегири",
        "петушки", "салтыковка", "кучино", "балашиха", "железнодорожный",
        "реутов", "люберцы", "химки", "москва", "зарайск", "кашира",
        "владимир", "опалиха", "красногорск", "павловский посад", "новогиреево",
        "звенигород", "долгопрудный", "мытищи", "королев", "одинцово", "подольск",
        "тула", "донской", "серпухов", "чехов", "ногинск", "электросталь", "раменское",
        "жуковский", "щелково", "ивантеевка", "пушкино", "лобня", "зеленоград",
        "солнечногорск", "клин", "дмитров", "сергиев посад", "орехово-зуево",
        "воскресенск", "коломна", "ступино", "домодедово", "видное", "иваново",
        "ковров", "муром", "александров", "санкт-петербург", "питер", "спб", "шушары",
        "рязань", "тверь", "ярославль", "калуга", "нижний новгород", "чебоксары",
        "казань", "уфа", "самара", "саратов", "волгоград", "ростов", "краснодар",
        "руза", "волоколамск", "можайск", "наро-фоминск", "апрелевка", "селятино"
    ]
    for p in known_places:
        if re.search(rf'\b{re.escape(p)}[а-я]*\b', normalized.lower()):
            return p.capitalize()

    # Точные паттерны проживания (с предлогами и без: "живу истра", "живу в истре", "из города", "г. Истра")
    m_dist = re.search(r'\b(?:живу|проживаю|нахожусь|из города|из г\.|город|г\.|ст\.|станци[яи]|район|р-н)\s+(?:в|на|около|возле)?\s*([а-яa-z\-]+)', normalized, re.IGNORECASE)
    if m_dist:
        match_str = m_dist.group(1).strip()
        stop_words = ["москвы", "области", "россии", "работы", "опыта", "вами", "связаться", "сообщение", "отклики", "раздела", "вакансию", "сохранились", "этого", "договорились", "городе"]
        if match_str.lower() not in stop_words and len(match_str) > 2:
            return match_str.capitalize()

    return ""

def extract_candidate_ready_date(text: str) -> str:
    if not text:
        return ""
    t_low = text.lower()

    # ПРЯМОЙ ПОИСК ДАТЫ ФОРМАТА ДД.ММ (например: 22.10, с 25.10, 01.11) ДО очистки времени!
    m_ddmm = re.search(r'\b(?:с\s+|на\s+|со?\s+)?((?:0?[1-9]|[12]\d|3[01])\.(?:0[1-9]|1[0-2]))\b', t_low)
    if m_ddmm:
        return m_ddmm.group(0).strip()

    # Очищаем временные интервалы смен (08:00, 20:00, с 8 до 20), но НЕ даты
    cleaned_time = re.sub(r'\b\d{1,2}:\d{2}\b', '', t_low)
    cleaned_time = re.sub(r'\b(?:0?[89]|1\d|20)\.00\b', '', cleaned_time)
    cleaned_time = re.sub(r'\bс\s+\d{1,2}\s+до\s+\d{1,2}\b', '', cleaned_time)

    # Календарные даты месяца ('19 октября', '20-го', '21.10', 'на 25 число')
    m_cal = re.search(
        r'\b(?:с\s+|на\s+|со?\s+)?('
        r'\d{1,2}\s+(?:январ[а-я]*|феврал[а-я]*|март[а-я]*|апрел[а-я]*|ма[яе]|июн[а-я]*|июл[а-я]*|август[а-я]*|сентябр[а-я]*|октябр[а-я]*|ноябр[а-я]*|декабр[а-я]*)'
        r'|\b\d{1,2}-(?:го|ого)\b'
        r')',
        cleaned_time
    )
    if m_cal:
        return m_cal.group(0).strip()

    m = re.search(
        r'\b(?:на\s+завтра|завтра|послезавтра|сегодня|со\s+следующей\s+недели|'
        r'с\s+понедельник[а-я]*|со\s+вторник[а-я]*|со?\s+среды|с\s+четверг[а-я]*|с\s+пятниц[а-я]*|'
        r'в\s+выходн[а-я]*|в\s+субботу|в\s+воскресенье|'
        r'хоть\s+сейчас|хоть\s+завтра|прямо\s+сейчас|в\s+любое\s+время|с\s+любого\s+числа|'
        r'на\s+этой\s+неделе)\b', 
        cleaned_time
    )
    if m:
        return m.group(0).strip()
    return ""
    return ""

def evaluate_candidate_qualification(cand_name: str, known_age: str, known_cit: str, clean_text: str, all_cand_text: str, vac_prof: dict, item_title: str, has_avito_rejection: bool = False):
    """
    Проверяет кандидата на целесообразность/стоп-факторы:
    0. Автосообщение Авито: ✘ Кандидат не соответствует требованиям вакансии
    1. Возраст (строго 18+, и не старше max_age конкретного объекта)
    2. Гражданство (требования объекта: например, АБИ строго РФ/РБ; наличие патента/документов)
    3. Отказ от работы в процессе опроса ("уже нашел", "не актуально", "передумал", "удаленка")
    
    Возвращает (is_disqualified: bool, reason: str, reply_text: str)
    """
    first_name = cand_name.split()[0].capitalize() if cand_name else ""
    prefix = ""
    t_low = (clean_text or "").lower()

    # 0. СТОП-ФАКТОР: Автосообщение Авито о несоответствии требованиям
    if has_avito_rejection:
        reason = "Автосообщение Авито: Кандидат не соответствует требованиям вакансии"
        reply = (
            f"{prefix}К сожалению, ваш отклик не соответствует требованиям данной вакансии. "
            f"Спасибо за интерес к нашей компании!"
        )
        return True, reason, reply
    
    # 1. СТОП-ФАКТОР: Младше 18 лет
    age_int = None
    if known_age:
        m_a = re.search(r'\d+', str(known_age))
        if m_a: age_int = int(m_a.group(0))

    if age_int is not None and age_int < 18:
        reason = f"Несовершеннолетний (возраст {age_int} лет, на объектах строго с 18 лет)"
        reply = (
            f"{prefix}К сожалению, по требованиям охраны труда на объектах трудоустройство строго с 18 лет. "
            f"Будем рады сотрудничеству по достижении совершеннолетия!"
        )
        return True, reason, reply

    underage_match = re.search(r'\b(?:мне|возраст)\s*(1[0-7])\b|\b(1[0-7])\s*(?:лет|года)\b', t_low)
    if underage_match:
        found_age = underage_match.group(1) or underage_match.group(2)
        reason = f"Несовершеннолетний (указан возраст {found_age} лет, строго с 18)"
        reply = (
            f"{prefix}К сожалению, по требованиям охраны труда на объектах трудоустройство строго с 18 лет. "
            f"Будем рады сотрудничеству по достижении совершеннолетия!"
        )
        return True, reason, reply

    # 2. СТОП-ФАКТОР: Старше максимального возраста вакансии (OVERAGE)
    max_age = vac_prof.get("max_age", 55)
    if age_int is not None and age_int > max_age:
        reason = f"Возраст {age_int} лет превышает согласованный лимит объекта ({max_age} лет)"
        reply = (
            f"{prefix}К сожалению, по регламенту данного объекта согласование проводится строго до {max_age} лет "
            f"в связи с высокими физическими нагрузками. Спасибо за отклик и понимание!"
        )
        return True, reason, reply

    # 3. СТОП-ФАКТОР: Гражданство — СТРОГО ТОЛЬКО РФ! (СНГ и иностранцев категорически не берем)
    if known_cit:
        cit_l = known_cit.lower()
        is_rf = any(c in cit_l for c in ["рф", "росси", "россия"]) and not any(neg in cit_l for neg in ["не рф", "не россия", "узбек", "таджик", "кыргыз", "киргиз", "снг", "патент", "рб", "беларус", "казах", "армян", "азерб", "молдав"])
        if not is_rf:
            reason = f"Гражданство «{known_cit}»: работаем строго только с гражданами РФ (СНГ не рассматриваем)"
            reply = (
                f"{prefix}К сожалению, на всех наших объектах оформление проводится строго только для граждан РФ "
                f"(с гражданами СНГ не работаем). Спасибо за понимание и успехов в поиске работы!"
            )
            return True, reason, reply

    # Проверка ключевых слов СНГ / патента / иностранных государств в тексте
    sng_patterns = [
        r'\bснг\b', r'\bпатент', r'\bвнж\b', r'\bрвп\b', r'\bузбек', r'\bтаджик',
        r'\bкыргыз', r'\bкиргиз', r'\bказах', r'\bармян', r'\bазерб', r'\bмолдав',
        r'\bбеларус', r'\bрб\b', r'\bиностран'
    ]
    if any(re.search(pat, t_low) for pat in sng_patterns):
        reason = "Кандидат из СНГ / иностранный гражданин (работаем строго только с гражданами РФ)"
        reply = (
            f"{prefix}К сожалению, на всех наших объектах трудоустройство проводится строго только для граждан РФ "
            f"(с гражданами СНГ и иностранцами не работаем). Спасибо за отклик!"
        )
        return True, reason, reply

    # Кандидат прямо пишет об отсутствии документов / патента
    no_docs = any(p in t_low for p in [
        "нет документов", "без документов", "нет патента", "без патента",
        "патент просрочен", "просрочен патент", "нет регистрации", "нелегал"
    ])
    if no_docs:
        reason = "Отсутствуют необходимые документы/патент для официального трудоустройства"
        reply = (
            f"{prefix}К сожалению, без действующего пакета документов (патент, регистрация) "
            f"официальное оформление на объектах невозможно."
        )
        return True, reason, reply

    # 4. СТОП-ФАКТОР: Отказ от работы в процессе опроса
    refusal = any(p in t_low for p in [
        "уже нашел работу", "уже нашла работу", "уже устроился", "уже устроилась",
        "не актуально", "неактуально", "передумал", "передумала", "отмените отклик",
        "отмените", "не интересует", "не хочу", "не надо", "больше не пишите",
        "не буду работать"
    ])
    if refusal:
        reason = "Кандидат отказался от вакансии в диалоге (не актуально / нашел другое)"
        reply = (
            f"{prefix}Спасибо за обратную связь! Зафиксировали. "
            f"Если поиск работы снова станет актуальным — обращайтесь, будем рады помочь!"
        )
        return True, reason, reply

    # Несовместимый формат (удаленка, школьники)
    remote = any(p in t_low for p in ["удаленк", "удалёнк", "на дому", "онлайн", "для школьник"])
    if remote:
        reason = "Кандидат ищет несовместимый формат (удаленка / на дому)"
        reply = (
            f"{prefix}На наших объектах предусмотрена только очная работа на складах и производствах (полные смены)."
        )
        return True, reason, reply

    return False, "", ""

def get_cabinet_uis_phone(item_id: str = "", item_title: str = "") -> str:
    """
    Возвращает официальный номер коллтрекинга UIS, привязанный к данному объявлению в кабинете Авито.
    Категорически запрещено давать личные или прямые номера бригадиров/координаторов!
    Только подтвержденные номера UIS из выгрузки объявлений кабинета.
    """
    SDS_ITEMS_WITH_925 = [
        "8276181745", "8510931894", "7442184610", "8178841067", "8326652344",
        "8304949277", "8177989785", "8418775858", "8082177117", "8282883310",
        "8394589818", "8434943096"
    ]
    t = (item_title or "").lower()
    if str(item_id) in SDS_ITEMS_WITH_925 or any(w in t for w in ["уборщик на теплый склад", "уборщик служебных", "поломоечн"]):
        return "+7 (925) 087-81-44"
    else:
        return "+7 (958) 565-19-78"

def sanitize_bot_reply(reply: str, already_greeted: bool, first_name: str) -> str:
    cleaned = reply.strip()
    if already_greeted:
        # 1. Вырезаем любые приветствия ("Здравствуйте", "Здравствуйте, Ильмира!" и т.д.)
        cleaned = re.sub(r'^(?:(?:Здравствуйте|Добрый день|Добрый вечер|Доброе утро|Приветствую|Привет)[^!?,.\n]*[!?,.\n]*\s*)+', '', cleaned, flags=re.IGNORECASE).strip()
        # 2. Вырезаем шаблонную фразу о начале диалога
        cleaned = re.sub(r'Вакансия актуальна,\s*как раз ведем запись на смены\.?\s*', '', cleaned, flags=re.IGNORECASE).strip()
        # 3. Вырезаем блок верификации анкеты, если диалог уже идет
        cleaned = re.sub(r'Вижу вашу анкету\s*\([^)]*\)\s*—?\s*(?:данные актуальны\??|всё отлично подходит\.?)\s*', '', cleaned, flags=re.IGNORECASE).strip()
        if first_name and cleaned.lower().startswith(first_name.lower()):
            cleaned = re.sub(rf'^{re.escape(first_name)}[!?,.]*\s*', '', cleaned, flags=re.IGNORECASE).strip()
        if cleaned:
            cleaned = cleaned[0].upper() + cleaned[1:]
    return cleaned

def safe_send_message(chat_id: str, reply: str, already_greeted: bool, first_name: str) -> bool:
    cleaned = sanitize_bot_reply(reply, already_greeted, first_name)
    if not cleaned or not cleaned.strip():
        return False

    # ЖЕЛЕЗНЫЙ ЗАПРЕТ 1: Проверка последнего сообщения в чате ПЕРЕД отправкой
    # Категорический запрет на отправку двух сообщений подряд от бота/компании!
    try:
        recent = client.get_chat_messages(chat_id, limit=3)
        if recent and len(recent) > 0:
            latest_m = recent[0] # Самое свежее сообщение
            if latest_m.get('author_id') == AVITO_USER_ID:
                print(f"[BLOCKED DOUBLE-MESSAGE] Чат {chat_id}: последнее сообщение уже отправлено нами! Повторная отправка отменена.", flush=True)
                try:
                    client.mark_chat_as_read(chat_id)
                except Exception:
                    pass
                return False

            # ЖЕЛЕЗНЫЙ ЗАПРЕТ 2: Проверка на дублирование текста
            for m in recent:
                if m.get('author_id') == AVITO_USER_ID:
                    prev_text = (m.get('content', {}).get('text') or '').strip().lower()
                    if cleaned.strip().lower() == prev_text:
                        print(f"[BLOCKED DUPLICATE TEXT] Чат {chat_id}: такое сообщение уже было отправлено ранее! Отменено.", flush=True)
                        try:
                            client.mark_chat_as_read(chat_id)
                        except Exception:
                            pass
                        return False
    except Exception as e_check:
        print(f"[SAFE-SEND CHECK ERROR] {e_check}", flush=True)

    client.send_message(chat_id, cleaned)
    try:
        client.mark_chat_as_read(chat_id)
    except Exception:
        pass
    return True

def process_single_chat(chat_summary):
    chat_id = chat_summary.get('id')
    users = chat_summary.get('users', [])
    cand_name = ""
    for u in users:
        if u.get('id') != AVITO_USER_ID:
            cand_name = u.get('name', '')
            break

    context = chat_summary.get('context', {})
    item_title = ""
    if context.get('type') == 'item':
        item_title = context.get('value', {}).get('title', '')

    raw_msgs = client.get_chat_messages(chat_id, limit=100)
    if not raw_msgs:
        return False

    msgs = list(reversed(raw_msgs))
    
    # =========================================================================
    # ПРАВИЛО 1: СТОП-ФРАЗЫ И ОТКАЗЫ В ПЕРЕПИСКЕ (ТОЛЬКО ЖИВЫЕ СООБЩЕНИЯ, НЕ СИСТЕМНЫЕ!)
    # =========================================================================
    # ВНИМАНИЕ: Системные плашки Авито («✘ Кандидат не соответствует требованиям вакансии»)
    # НЕ являются отказом! Такие кандидаты (например, ЕАЭС/Армения) полностью подходят нам.
    human_msgs = [
        m for m in msgs
        if m.get('author_id') not in [0] and
        m.get('type') != 'system' and
        not str(m.get('content', {}).get('text', '')).strip().startswith("[Системное сообщение]") and
        "данные сохранились" not in str(m.get('content', {}).get('text', '')).lower() and
        "кандидат не соответствует" not in str(m.get('content', {}).get('text', '')).lower() and
        "кандидат соответствует" not in str(m.get('content', {}).get('text', '')).lower()
    ]
    human_chat_texts = " ".join([str(m.get('content', {}).get('text', '')).lower() for m in human_msgs])
    # =========================================================================
    # ПРАВИЛО 1: ОПРЕДЕЛЯЕМ НАШЕ ПОСЛЕДНЕЕ СООБЩЕНИЕ И НОВЫЕ СООБЩЕНИЯ КАНДИДАТА
    # =========================================================================
    our_last_idx = -1
    for i, m in enumerate(msgs):
        if m.get('author_id') == AVITO_USER_ID:
            our_last_idx = i

    # Если последнее сообщение отправлено НАМИ — ждать ответа кандидата, ничего не отправлять!
    if our_last_idx == len(msgs) - 1:
        client.mark_chat_as_read(chat_id)
        return False

    new_candidate_msgs = msgs[our_last_idx + 1:] if our_last_idx != -1 else msgs
    new_candidate_texts = " ".join([str(m.get('content', {}).get('text', '')) for m in new_candidate_msgs]).lower()

    # Проверка на отказ со стороны самого кандидата в новых сообщениях
    cand_refusal_phrases = [
        "больше не пишите", "уже устроился", "уже устроилась", "уже нашел", "уже нашла",
        "не актуально", "неактуально", "не беспокойте", "отмените", "передумал", "передумала"
    ]
    if any(rp in new_candidate_texts for rp in cand_refusal_phrases):
        print(f">>> Candidate explicitly refused in chat {chat_id}. Marking as read.")
        client.mark_chat_as_read(chat_id)
        return False

    # Если в переписке ранее было сообщение об отказе от компании («остановили выбор на других кандидатах»),
    # но кандидат после этого всё равно написал свой номер телефона или готовность к работе — НЕ СЛИВАТЬ ЕГО!
    # Обрабатываем новые входящие данные и передаем рекрутеру.
    # Если же новых данных нет — чат закрыт.
    company_stop_phrases = [
        "остановили выбор", "других кандидатах", "вынуждены отказать",
        "вы нам не подходите", "набор закрыт", "вакансия закрыта"
    ]
    last_our_text = str(msgs[our_last_idx].get('content', {}).get('text', '')).lower() if our_last_idx != -1 else ""
    is_reopened = any(rp in last_our_text for rp in ["прошу прощения", "накладка", "подходит", "зафиксировала", "передала", "свяжется", "актуальн"])
    had_company_refusal = any(sp in human_chat_texts for sp in company_stop_phrases) and not is_reopened
    cand_sent_phone_or_location = bool(extract_phone(new_candidate_texts)) or bool(extract_candidate_district(new_candidate_texts))
    if had_company_refusal and not cand_sent_phone_or_location:
        client.mark_chat_as_read(chat_id)
        return False

    new_candidate_msgs = msgs[our_last_idx + 1:]
    if not new_candidate_msgs:
        return False

    # Фильтр свежести: обрабатываем свежие сообщения за сегодня (строго до 24 часов)
    latest_msg = new_candidate_msgs[-1]
    msg_timestamp = latest_msg.get('created', 0)
    hours_ago = (time.time() - msg_timestamp) / 3600.0
    if hours_ago > 24.0:
        client.mark_chat_as_read(chat_id)
        return False

    # Разделяем реальные сообщения человека от системных сообщений Авито
    real_cand_msgs = [
        m for m in new_candidate_msgs
        if m.get('author_id') not in [0, AVITO_USER_ID] and
        m.get('type') != 'system' and
        not str(m.get('content', {}).get('text', '')).strip().startswith("[Системное сообщение]") and
        "данные сохранились" not in str(m.get('content', {}).get('text', '')).lower() and
        "кандидат откликнулся" not in str(m.get('content', {}).get('text', '')).lower() and
        "кандидат не соответствует" not in str(m.get('content', {}).get('text', '')).lower() and
        "кандидат соответствует" not in str(m.get('content', {}).get('text', '')).lower()
    ]
    real_cand_text = " \n ".join([str(m.get('content', {}).get('text', '')).strip() for m in real_cand_msgs if "не поддерживается" not in str(m.get('content', {}).get('text', '')).lower()]).strip()
    has_real_cand_text = bool(real_cand_text)
    clean_new = re.sub(r'[^а-яa-z0-9\s]', '', real_cand_text.lower()).strip()

    # Если кандидат НЕ написал ни одного живого сообщения (только системный отклик)
    # и прошло больше 2 часов — не отправлять ничего с опозданием
    if not has_real_cand_text and hours_ago > 2.0:
        client.mark_chat_as_read(chat_id)
        return False

    # Если мы УЖЕ вели диалог с кандидатом (our_last_idx != -1),
    # а в новых сообщениях НЕТ живого текста от человека (только системная плашка / карточка анкеты от Авито) —
    # НЕ спамить кандидата повторными репликами!
    if our_last_idx != -1 and not has_real_cand_text:
        client.mark_chat_as_read(chat_id)
        return False


    # =========================================================================
    # СБОР И АНАЛИЗ ВСЕЙ ИСТОРИИ ДИАЛОГА (СТРОГАЯ ПАМЯТЬ)
    # =========================================================================
    all_cand_msgs = [m for m in msgs if m.get('author_id') != AVITO_USER_ID]
    all_our_msgs = [m for m in msgs if m.get('author_id') == AVITO_USER_ID]

    all_cand_text = " \n ".join([str(m.get('content', {}).get('text', '')) for m in all_cand_msgs])
    all_our_text = " \n ".join([str(m.get('content', {}).get('text', '')) for m in all_our_msgs]).lower()

    # 1. Телефон
    new_phone = extract_phone(real_cand_text) if has_real_cand_text else ""
    known_phone = new_phone or extract_phone(all_cand_text)
    if not known_phone:
        retrieved_phone, phone_src = get_or_reveal_candidate_phone(chat_id, client=client, context=context)
        if retrieved_phone:
            known_phone = retrieved_phone
            print(f">>> Auto-revealed candidate phone via {phone_src}: {known_phone}")
    phone_known = bool(known_phone)

    # 2. Имя, возраст, гражданство из системных блоков анкеты
    known_age = ""
    known_cit = ""
    known_fio = ""
    for m in msgs:
        txt = m.get('content', {}).get('text', '')
        m_fio = re.search(r'ФИО\s*[—\-:]\s*([^\n\r]+)', txt, re.IGNORECASE)
        m_age = re.search(r'Возраст\s*[—\-:]\s*(\d+)', txt, re.IGNORECASE)
        m_cit = re.search(r'Гражданство\s*[—\-:]\s*([^\n\r]+)', txt, re.IGNORECASE)
        if m_fio and not known_fio: known_fio = m_fio.group(1).strip()
        if m_age and not known_age: known_age = m_age.group(1).strip()
        if m_cit and not known_cit: known_cit = m_cit.group(1).strip()

    if not known_age:
        m_plain_age = re.search(r'\b(\d{2})\s*(?:лет|года|г)?\b', all_cand_text)
        if m_plain_age and 18 <= int(m_plain_age.group(1)) <= 70:
            known_age = m_plain_age.group(1)

    first_name = ""
    if known_fio:
        parts = known_fio.strip().split()
        if len(parts) >= 2:
            first_name = parts[1].capitalize()
        elif parts:
            first_name = parts[0].capitalize()
    if not first_name and cand_name:
        first_name = cand_name.split()[0].capitalize()

    if not known_cit:
        cit_enum, cit_label = detect_citizenship_from_text(all_cand_text)
        if cit_label:
            known_cit = cit_label

    # 3. Район / город проживания
    cand_district = extract_candidate_district(all_cand_text)
    if not cand_district:
        city_name, city_id = detect_city_from_text(all_cand_text)
        if city_name:
            cand_district = city_name
    district_known = bool(cand_district)

    # 4. Дата готовности к выходу
    cand_ready_date = extract_candidate_ready_date(all_cand_text)
    ready_date_known = bool(cand_ready_date)

    # 5. Что мы УЖЕ спрашивали у кандидата в переписке (чтобы не повторяться!)
    already_asked_district = ("в каком районе" in all_our_text or "где вы проживаете" in all_our_text or "где проживаете" in all_our_text)
    already_asked_date = ("с какого числа" in all_our_text or "когда готовы" in all_our_text or "когда вам удобно" in all_our_text)
    already_asked_phone = ("номер телефона" in all_our_text or "номер для связи" in all_our_text or "контактный номер" in all_our_text)

    # 6. Актуализировали ли мы уже анкету и отправляли ли заключительный ответ
    any_our_msg = any(m.get('author_id') == AVITO_USER_ID for m in msgs)
    already_greeted = (our_last_idx != -1) or any_our_msg or (len(msgs) > len(new_candidate_msgs))
    already_verified_profile = already_greeted or any(
        phrase in all_our_text for phrase in [
            "данные актуальны", "вижу вашу анкету", "вижу анкету", "анкета актуальна",
            "по вашей анкете", "отлично подходит"
        ]
    )

    already_finalized = any(
        phrase in all_our_text for phrase in [
            "ваши данные записаны",
            "данные записаны",
            "координатор свяжется с вами",
            "координатор свяжется для записи",
            "координатор наберет вас",
            "координатор наберет и согласует",
            "координатор позвонит",
            "закрепил за вами место",
            "закрепила за вами место"
        ]
    )

    # Если заключительный ответ УЖЕ отправлялся, и кандидат пишет реплику подтверждения/вежливости — НЕ ОТВЕЧАТЬ!
    closing_phrases = [
        "спасибо", "хорошо спасибо", "спасибо большое", "ясно", "понятно", "ок", "хорошо",
        "договорились", "до свидания", "жду", "хорошо жду", "хорошо ладно", "ладно", "буду ждать",
        "д", "да", "жду напишут", "напишут", "это моя номер", "это мой номер", "угу", "ага",
        "прямой работодатель", "ладно хорошо", "все понятно", "всё понятно", "отлично"
    ]
    if already_finalized and (clean_new in closing_phrases or any(clean_new == p for p in closing_phrases) or not has_real_cand_text):
        print(f">>> Final answer was already sent previously to {cand_name} ({chat_id}). No further spam.")
        client.mark_chat_as_read(chat_id)
        return False

    # =========================================================================
    # ПРАВИЛО 4: СТРОЖАЙШИЙ ЗАПРЕТ НА ПОВТОРНЫЕ ПРИВЕТСТВИЯ В ОДИН ДЕНЬ
    # Если мы уже хоть раз отправляли сообщение кандидату -> НИКАКИХ "Здравствуйте"!
    # =========================================================================
    if already_greeted:
        prefix = ""
    else:
        prefix = f"Здравствуйте, {first_name}!\n" if first_name else "Здравствуйте!\n"

    vac_prof = detect_vacancy_profile(item_title)
    eval_res = evaluate_candidate_fit(vac_prof, known_age, known_cit)

    # Проверка на глухонемого / слабослышащего / требование общаться только текстом
    # Проверяется ПО ВСЕЙ истории диалога (железная память на весь чат!)
    is_text_only = any(w in all_cand_text.lower() for w in [
        "глухонем", "глухомен", "не слыш", "плохо слыш", "слабослыш", "по слуху", "инвалид", "глухой", "глухая",
        "только писать", "только напишите", "только пишите", "только смс",
        "только сообщение", "не могу говорить", "не звоните", "не звонить",
        "без звонков", "только вотсап", "только whatsapp", "только макс", "только авито"
    ])

    coord_contact_phrase = "напишет вам здесь в чате" if is_text_only else "свяжется с вами"
    coord_call_phrase = "напишет вам здесь в чате" if is_text_only else "наберет вас"

    cand_data_dict = {
        "name": first_name or cand_name,
        "age": known_age,
        "citizenship": known_cit,
        "phone": known_phone,
        "vacancy": item_title,
        "district": cand_district,
        "ready_date": cand_ready_date,
        "schedule_pref": "",
        "is_text_only": is_text_only
    }

    # =========================================================================
    # ПРАВИЛО 2: КОРОТКИЕ ЗАКРЫВАЮЩИЕ РЕПЛИКИ ВЕЖЛИВОСТИ / РАЗГОВОР НИ О ЧЕМ
    # Если кандидат пишет формальные реплики («спасибо», «хорошо», «ок», «ладно», «жду», «д», «угу»),
    # и мы уже дали ответ / зафиксировали контакты — НЕ спамить в ответ!
    # =========================================================================
    closing_words = [
        "спасибо", "хорошо спасибо", "спасибо большое", "ясно", "понятно", "ок", "хорошо",
        "договорились", "до свидания", "хорошо ладно", "ладно", "да хорошо", "хорошо жду",
        "жду", "буду ждать", "понятно спасибо", "поняла спасибо", "поняла", "поняла хорошо",
        "хорошо поняла", "хорошо ждем", "ждем", "спасибо жду", "будем ждать", "добро", "принято",
        "д", "да", "угу", "ага", "жду напишут", "напишут", "это моя номер", "это мой номер",
        "прямой работодатель", "ладно хорошо", "все понятно", "всё понятно", "отлично"
    ]
    is_closing = (clean_new in closing_words) or any(clean_new.startswith(cw) and len(clean_new.split()) <= 3 for cw in ["хорошо", "спасибо", "понял", "поняла", "ладно", "жду", "ок"])
    if (is_closing or already_finalized) and our_last_idx != -1 and (clean_new in closing_words or not has_real_cand_text):
        print(f">>> Candidate sent closing/politeness/idle word ('{clean_new}'). Chat marked as read without extra reply.", flush=True)
        client.mark_chat_as_read(chat_id)
        return False

    # =========================================================================
    # ПРАВИЛО 2.5: ОБРАБОТКА ПРЯМОГО ОТКАЗА КАНДИДАТА («НЕТ / НЕ ХОЧУ / НЕ АКТУАЛЬНО»)
    # Категорический запрет на навязывание записи при отказе! Вежливо закрываем чат.
    # =========================================================================
    clean_check = clean_new.strip()
    is_direct_refusal = (
        clean_check in ["нет", "не", "отказ", "не хочу", "не надо", "не нужно", "не актуально", "неактуально", "передумал", "передумала", "уже нашел", "уже нашла", "уже устроился", "уже устроилась"] or
        clean_check.startswith("нет ") or clean_check.endswith(" нет") or
        any(rw in clean_check for rw in ["не актуальн", "не интересн", "уже нашел", "уже нашла", "уже устрои", "другую работу"])
    )
    if is_direct_refusal:
        farewell = f"Поняла вас{f', {first_name}' if first_name else ''}! Спасибо за ответ. Если в будущем понадобится работа или подработка — обращайтесь, будем рады помочь! Всего вам доброго!"
        safe_send_message(chat_id, farewell, already_greeted, first_name)
        print(f">>> SENT polite farewell on candidate direct refusal ('{clean_new}'). Chat closed.")
        client.mark_chat_as_read(chat_id)
        sync_candidate_to_b24_deal(chat_id, cand_data_dict, is_disqualified=True, disqualify_reason="Кандидат ответил отказом в чате")
        return True

    # Текст кандидата для анализа интентов — СТРОГО очищенный от системных блоков!
    t_new_lower = clean_new
    print(f"\n=======================================================")
    print(f"Chat: {chat_id} | Candidate: {cand_name} | Already greeted: {already_greeted}")
    print(f"Clean candidate text: '{t_new_lower}'")
    print(f"Phone known: {phone_known} ({known_phone}) | District: {district_known} ({cand_district}) | Date: {ready_date_known} ({cand_ready_date})")

    # =========================================================================
    # СЦЕНАРИЙ 1: ПРОВЕРКА НА НЕЦЕЛЕВОГО КАНДИДАТА (ДИСКВАЛИФИКАЦИЯ)
    # Проверяются:
    # 0. Автосообщение Авито («✘ Кандидат не соответствует требованиям вакансии»)
    # 1. Возраст (<18 или >max_age объекта), гражданство (только РФ/РБ на АБИ),
    # 2. Отказ от работы, отсутствие документов/патента.
    # Нецелевой кандидат перемещается в отдельную воронку 'Нецелевые' (Category 44) в Битрикс24!
    # Задачи и уведомления для рекрутеров НЕ СОЗДАЮТСЯ!
    # =========================================================================
    has_avito_rejection = False
    for m in msgs:
        t_msg = str(m.get('content', {}).get('text', '')).lower()
        if 'не соответствует требованиям' in t_msg or 'не\xa0соответствует требованиям' in t_msg or '✘' in t_msg:
            has_avito_rejection = True
            break

    is_disq, disq_reason, disq_reply = evaluate_candidate_qualification(
        cand_name=first_name or cand_name,
        known_age=known_age,
        known_cit=known_cit,
        clean_text=t_new_lower,
        all_cand_text=all_cand_text,
        vac_prof=vac_prof,
        item_title=item_title,
        has_avito_rejection=has_avito_rejection
    )
    if is_disq:
        sent = safe_send_message(chat_id, disq_reply, already_greeted, first_name)
        if sent:
            print(f">>> SENT polite refusal to non-target candidate: {disq_reason}")
            sync_candidate_to_b24_deal(chat_id, cand_data_dict, is_disqualified=True, disqualify_reason=disq_reason)
        else:
            print(f">>> Refusal was already sent earlier to non-target candidate {cand_name} ({chat_id}). Marking as read.")
        client.mark_chat_as_read(chat_id)
        return False

    # =========================================================================
    # СЦЕНАРИЙ 2: КАНДИДАТ ПИШЕТ «Я УЖЕ НАПИСАЛА / УЖЕ ОТВЕТИЛА / БЫЛО РАНЬШЕ»
    # =========================================================================
    cand_said_already = any(w in t_new_lower for w in [
        "уже написал", "уже ответил", "ужэ написал", "написала вам", "я же написала",
        "я же сказал", "я же говорила", "я уже сказала", "уже сказала", "было раньше",
        "раньше писала", "раньше говорила", "уже говорила", "уже скинул", "уже давал", "уже давала"
    ])
    if t_new_lower and cand_said_already:
        if phone_known:
            if is_text_only:
                reply = (
                    f"{prefix}Да, всё зафиксировано: ваш номер {known_phone}, город {cand_district or 'указан'}, "
                    f"пометку «только писать (не звонить), кандидат не слышит» менеджеру передала. "
                    f"Координатор напишет вам здесь в чате для записи на смену!"
                )
            else:
                reply = (
                    f"{prefix}Да, всё верно! Ваши контакты ({known_phone}) зафиксировала и передала координатору. "
                    f"Он свяжется с вами в ближайшее время для записи на смену."
                )
        else:
            reply = (
                f"{prefix}Прошу прощения за накладку! Чтобы координатор мог связаться с вами и закрепить смену, "
                f"напишите, пожалуйста, ваш контактный номер телефона."
            )
        safe_send_message(chat_id, reply, already_greeted, first_name)
        print(">>> SENT candidate already answered acknowledgment.")
        sync_candidate_to_b24_deal(chat_id, cand_data_dict)
        return True

    # =========================================================================
    # СЦЕНАРИЙ 2b: КАНДИДАТ ТРЕБУЕТ ОТВЕТОВ НА ВСЕ ВОПРОСЫ («Ответьте на все вопросы...»)
    # =========================================================================
    demands_answers = any(phrase in t_new_lower for phrase in [
        "ответьте на все вопросы", "ответьте на вопросы", "ответьте на вопрос",
        "вы не ответили", "почему не отвечаете", "ответьте мне", "жду ответ",
        "я же спросил", "я же написала", "я же спросила"
    ])
    if demands_answers:
        complaint_answers = []
        full_cand_history = all_cand_text.lower()
        vac_lower_c = item_title.lower()
        
        if any(w in full_cand_history for w in ["уборщ", "клининг", "обязанност", "что делать", "в чем суть"]):
            if any(w in vac_lower_c for w in ["уборщ", "клининг"]):
                complaint_answers.append("• По обязанностям: уборка складских и служебных помещений, инвентарь и форма выдаются бесплатно.")
            else:
                complaint_answers.append(f"• По обязанностям: комплектовка и упаковка товаров на теплом складе («{item_title}»), это не уборка.")
        
        if any(w in full_cand_history for w in ["график", "смен", "время", "со скольк", "во скольк", "не успеваю", "к 8"]):
            complaint_answers.append("• По графику: дневные смены с 08:00 до 20:00, ночные — с 20:00 до 08:00. Если к 08:00 не успеваете, время выхода согласуется индивидуально с координатором.")
        
        if any(w in full_cand_history for w in ["карту", "третьего лица", "чужую"]):
            complaint_answers.append("• По выплатам: перечисление на карту другого лица возможно по заявлению.")
            
        if any(w in full_cand_history for w in ["скольк", "ставк", "оплат", "зарплат"]):
            rate_str = vac_prof.get("rate", "от 3 600 до 4 200 ₽ за смену")
            complaint_answers.append(f"• По оплате: ставка составляет {rate_str}, выплаты без задержек.")
            
        if any(w in full_cand_history for w in ["где", "адрес", "добира"]):
            complaint_answers.append(f"• По адресу: объект «{item_title}», подробный маршрут подскажет координатор.")

        if not complaint_answers:
            complaint_answers.append("Прошу прощения за задержку с ответом! Обязательно отвечу на все интересующие вопросы.")

        closing = f"Координатор {coord_contact_phrase} по номеру {known_phone} и согласует все детали!" if phone_known else f"Подскажите номер телефона для связи — координатор {coord_call_phrase} и подробно ответит на все нюансы."
        
        reply = (
            f"{prefix}Прошу прощения за ожидание! Отвечаю на ваши вопросы:\n\n"
            + "\n".join(complaint_answers) + "\n\n"
            + closing
        )
        safe_send_message(chat_id, reply, already_greeted, first_name)
        print(">>> SENT comprehensive response to candidate complaint/demands.")
        sync_candidate_to_b24_deal(chat_id, cand_data_dict)
        return True

    # =========================================================================
    # СЦЕНАРИЙ 3: КАНДИДАТ СПРАШИВАЕТ «КАК СВЯЗАТЬСЯ / ПРЯМОЙ НОМЕР»
    # =========================================================================
    if t_new_lower and any(w in t_new_lower for w in ["как связа", "позвон", "прямой номер", "какой номер", "номер для связи"]):
        item_id_str = str(context.get('value', {}).get('id', ''))
        uis_phone = get_cabinet_uis_phone(item_id_str, item_title)
        if phone_known:
            reply = (
                f"{prefix}Номер телефона из объявления: {uis_phone} (звонок бесплатный). "
                f"Также координатор объекта {coord_contact_phrase} по указанному номеру {known_phone} для согласования записи на смену!"
            )
        else:
            reply = (
                f"{prefix}Номер телефона из объявления: {uis_phone} (звонок бесплатный). "
                f"Либо оставьте ваш контактный номер телефона, и координатор {coord_call_phrase} сам в ближайшее время!"
            )
        safe_send_message(chat_id, reply, already_greeted, first_name)
        print(f">>> SENT official cabinet UIS tracking phone {uis_phone} from ad.")
        sync_candidate_to_b24_deal(chat_id, cand_data_dict)
        return True

    # Блок верификации анкеты (партнерский тон, без бюрократических переспросов)
    cand_stated_profile = bool(re.search(r'\b\d{2}\s*(?:лет|года)?\b', all_cand_text)) or bool(re.search(r'\b(?:рф|росси[яи]|гражданство)\b', all_cand_text.lower()))
    profile_parts = []
    if known_age:
        profile_parts.append(format_age(known_age))
    if known_cit:
        profile_parts.append(f"гражданство {known_cit}")

    if profile_parts:
        if cand_stated_profile:
            verification_block = f"По вашей анкете ({', '.join(profile_parts)}) всё отлично подходит!"
        else:
            verification_block = f"Вижу вашу анкету ({', '.join(profile_parts)}) — всё отлично подходит."
    else:
        verification_block = "Уточните, пожалуйста, ваш возраст и гражданство для согласования на объекте."

    # =========================================================================
    # СЦЕНАРИЙ 3.5: КАНДИДАТУ НЕ ПОДХОДИТ ТЕРРИТОРИАЛЬНО ДАННЫЙ ОБЪЕКТ
    # =========================================================================
    has_negation = any(neg in t_new_lower for neg in [
        "не подходит", "неподходит", "не актуально", "неактуально", "не готов", "не готова",
        "не хочу", "не интересн", "не буду", "далек", "неудобн", "другой город", "нет"
    ])

    is_location_mismatch = any(w in t_new_lower for w in [
        "территориально не подходит", "не подходит территориально", "территориально далеко",
        "не подходит по району", "не подходит локация", "далеко добираться",
        "неудобно добираться", "далековато", "в другом городе", "другой конец", "далеко от меня"
    ]) or ("не подходит" in t_new_lower and any(w in t_new_lower for w in ["территориальн", "расположен", "город", "район", "адрес", "место"]))

    # Если в текущем или прошлых сообщениях был отказ по территории
    had_location_rejection = any(
        "не подходит" in str(m.get('content', {}).get('text', '')).lower() or
        "территориальн" in str(m.get('content', {}).get('text', '')).lower()
        for m in human_msgs
    )

    # Кандидат сообщил город/район после возражения по локации (например: "Зеленоград")
    if (is_location_mismatch or had_location_rejection) and cand_district and len(real_cand_text.strip().split()) <= 4:
        reply = (
            f"{prefix}Поняла вас, {cand_district}! Поблизости к вам есть складские и производственные объекты "
            f"(например, в Химках и Красногорске, а также вахтовые объекты с бесплатным проживанием и горячим питанием). "
        )
        if phone_known:
            reply += f"Я передала ваши пожелания по локации координатору — он {coord_contact_phrase} по номеру {known_phone} и предложит ближайшие к вам варианты!"
        else:
            reply += f"Напишите контактный номер телефона, и координатор {coord_contact_phrase} для подбора ближайшего объекта!"
        safe_send_message(chat_id, reply.strip(), already_greeted, first_name)
        print(f">>> SENT nearby facility proposal for {cand_district} after location objection.")
        sync_candidate_to_b24_deal(chat_id, cand_data_dict)
        return True

    if is_location_mismatch:
        reply = (
            f"{prefix}Поняла вас! А в каком городе или районе вам территориально удобно работать? "
            f"У нас есть другие склады и производства по Москве и области (а также вахта с бесплатным проживанием и питанием) — "
            f"подскажите, где вы находитесь, я подберу подходящий вариант!"
        )
        safe_send_message(chat_id, reply.strip(), already_greeted, first_name)
        print(">>> SENT location mismatch alternative inquiry (empathetic, no 'Отлично').")
        sync_candidate_to_b24_deal(chat_id, cand_data_dict)
        return True

    # =========================================================================
    # СЦЕНАРИЙ 4: КАНДИДАТ ПОДТВЕРДИЛ ИНТЕРЕС («ДА / ВСЁ ВЕРНО / АКТУАЛЬНО / ПОДХОДИТ»)
    # =========================================================================
    # СТРОГИЙ ЗАПРЕТ на совпадение при наличии частицы "НЕ" или отрицания ("не подходит", "не готов" и т.д.)
    is_confirming = (not has_negation) and any(
        re.search(rf'(?<![а-яa-z]){re.escape(w)}(?![а-яa-z])', t_new_lower) for w in [
            "актуально", "да актуально", "все верно", "всё верно", "верно",
            "подходит", "готов", "готова", "хочу", "интересно", "можно", "да"
        ]
    )
    if already_verified_profile and is_confirming:
        needed_questions = []
        if not known_cit:
            needed_questions.append("Ваше гражданство?")
        if not district_known and not already_asked_district:
            needed_questions.append("В каком городе и районе вы проживаете?")
        if not ready_date_known and not already_asked_date:
            needed_questions.append("С какого числа готовы выйти на смену?")
        if not phone_known:
            needed_questions.append(f"И напишите номер телефона для связи — координатор {coord_call_phrase} и запишет вас.")
        else:
            needed_questions.append(f"Координатор {coord_contact_phrase} по номеру {known_phone} для согласования записи!")

        if district_known and ready_date_known and phone_known:
            reply = (
                f"{prefix}Отлично, все данные приняты!\n\nДля записи на смену и передачи информации бригадиру (менеджеру объекта) перейдите, пожалуйста, в наш чат в MAX:\n👉 https://max.ru/id9729371578_bot\n\nНажмите там «Начать» или отправьте любое сообщение — там оформим пропуск на объект и согласуем дату заселения/выхода!"
            )
            safe_send_message(chat_id, reply.strip(), already_greeted, first_name)
            print(">>> SENT MAX bot transfer invitation after profile confirmation.")
            sync_candidate_to_b24_deal(chat_id, cand_data_dict)
            return True

        reply = f"{prefix}Хорошо, договорились! " + " ".join(needed_questions)
        safe_send_message(chat_id, reply.strip(), already_greeted, first_name)
        print(">>> SENT profile confirmation acknowledgment + next missing questions.")
        sync_candidate_to_b24_deal(chat_id, cand_data_dict)
        return True

    # =========================================================================
    # СЦЕНАРИЙ 5: ВОПРОСЫ ПО ВАКАНСИИ (ОБЯЗАННОСТИ, ВРЕМЯ НАЧАЛА, ОПЛАТА, ГРАФИК И ДР.)
    # =========================================================================
    answered_intent = False
    answer_parts = []
    vac_lower = item_title.lower()

    # 5.0. Вопрос по типу вакансии и обязанностям (уборщица, клининг, комплектовщик, что делать, обязанности)
    vac_role_query = any(w in t_new_lower for w in [
        "ваканси", "уборщиц", "уборка", "клининг", "мыть", "убирать",
        "обязанност", "что делать", "что входит", "что нужно делать",
        "в чем суть", "суть работы", "что за работа", "какая работа",
        "комплектовщ", "упаковщ", "грузчик", "разнорабоч"
    ])
    if vac_role_query:
        answered_intent = True
        # Специфический вопрос про уборку / уборщицу: "Вакансия уборщицы?"
        if any(w in t_new_lower for w in ["уборщиц", "уборк", "клининг", "мыть", "убирать"]):
            if any(w in vac_lower for w in ["уборщ", "клининг"]):
                answer_parts.append(
                    "Да, вакансия — уборщик(ца) на теплый склад. Обязанности: поддержание чистоты складских и служебных помещений (сухая и влажная уборка), вынос мусора. Весь инвентарь и спецодежду предоставляем бесплатно."
                )
            else:
                answer_parts.append(
                    f"На данном объекте открыта вакансия «{item_title}» (комплектовка и упаковка товаров на современном складе, это не уборка). Опыт не требуется — всему обучаем на месте."
                )
        else:
            # Общий вопрос про обязанности / что за вакансия
            if any(w in vac_lower for w in ["уборщ", "клининг"]):
                answer_parts.append(
                    "По вакансии уборщика: обязанности включают поддержание чистоты и порядка на складе (сухая и влажная уборка помещений), вынос мусора. Склад теплый, инвентарь выдаем."
                )
            elif any(w in vac_lower for w in ["комплект", "упаков", "стикеров", "фасов"]):
                answer_parts.append(
                    "По вакансии: сборка заказов по терминалу сбора данных (ТСД), комплектовка, упаковка и маркировка товаров на теплом складе. Опыт не требуется, обучение в первый же день."
                )
            elif any(w in vac_lower for w in ["грузчик", "разнорабоч"]):
                answer_parts.append(
                    "По вакансии: погрузочно-разгрузочные работы, размещение и перемещение коробок и паллет по складу."
                )
            else:
                answer_parts.append(
                    f"По вакансии «{item_title}»: простые и понятные складские операции, работа в тепле, обучение в первый день смены."
                )

    # 5.1. Время начала смены / опоздание / к 8 не успеваю
    if any(w in t_new_lower for w in ["не успеваю", "к 8", "к 9", "к скольки", "со скольки", "со скольких", "во сколько начало", "во сколько смен", "опозда", "позже при", "время работы", "время смены"]):
        answered_intent = True
        answer_parts.append(
            "По времени начала смен: стандартное время дневной смены — с 08:00 до 20:00 (ночной — с 20:00 до 08:00). Если к 08:00 приехать не успеваете, координатор может согласовать индивидуальное время выхода или подобрать удобную смену (например, в ночной график с 20:00)."
        )

    # 5.2. Вопрос про периодичность выплат / ежедневная оплата
    if any(w in t_new_lower for w in ["каждый день", "ежедневн", "каждую смену", "2 раза", "раз в месяц", "раз в неделю", "когда расчет", "как оплачива", "как у вас оплата", "как с оплатой", "когда оплата"]):
        answered_intent = True
        if any(w in vac_lower for w in ["зоо", "смарт", "балаших", "посад", "чай", "опалих"]):
            answer_parts.append("Выплаты ежедневные — расчет сразу после отработанной смены от 3 600 ₽ чистыми на руки.")
        elif "вахт" in vac_lower:
            answer_parts.append("На вахте выплаты стабильные: еженедельные авансы и полный расчет в конце вахты.")
        else:
            rate_str = vac_prof.get("rate", "от 3 600 до 4 200 ₽ за смену")
            answer_parts.append(f"Ставка {rate_str}, выплаты официальные и регулярные без задержек.")

    # 5.3. Вопрос про ставку / сколько платят
    elif any(w in t_new_lower for w in ["скольк", "ставк", "зарплат", "деньг", "в час"]):
        answered_intent = True
        rate_str = vac_prof.get("rate", "от 3 600 до 4 200 ₽ за смену")
        answer_parts.append(f"Ставка на объекте составляет {rate_str}, выплаты без задержек.")

    # 5.4a. Вопрос: обязательны ли ночи / можно ли только в день
    if any(w in t_new_lower for w in ["только день", "только в день", "только дневн", "ночь обязательн", "ночи обязательн", "ночь это обязательн", "можно без ноч", "можно только день", "обязательно в ночь"]):
        answered_intent = True
        answer_parts.append("По графику: ночные смены не обязательны! Можно выходить только в дневные смены (с 08:00 до 20:00). График подбирается индивидуально под вас.")

    # 5.4b. Вопрос про график / смены / часы / подработку
    elif any(w in t_new_lower for w in ["график", "с каких", "до каких", "ночн", "дневн", "подработк", "дня в неделю", "ночь", "смен"]):
        if not any("дневной смены" in ap for ap in answer_parts):
            answered_intent = True
            answer_parts.append(
                "По графику: дневные смены с 08:00 до 20:00, ночные — с 20:00 до 08:00. На подработку можно выходить по 3–4 смены в неделю в удобные дни."
            )

    # 5.5. Вопрос про адрес / где находится / как добираться / транспорт
    if any(w in t_new_lower for w in ["где", "находит", "локац", "адрес", "добира", "салтыков", "кучин", "далеко", "транспорт", "автобус", "какой адрес", "в каком город", "находится ли в"]):
        answered_intent = True
        if any(w in vac_lower for w in ["зоо", "смарт", "балаших"]):
            answer_parts.append("Склад находится в Балашихе (Носовихинское шоссе вл 253 с 14, микрорайон Салтыковка, 10–12 минут пешком от станции Кучино).")
        elif any(w in vac_lower for w in ["химк", "сдс"]):
            answer_parts.append("Склад находится в г. Химки (Вашутинское шоссе). Предусмотрен удобный подъезд и транспорт.")
        elif any(w in vac_lower for w in ["спб", "санкт-петербург", "обухов"]):
            answer_parts.append("Объект находится в Санкт-Петербурге (проспект Обуховской Обороны, рядом с метро Обухово).")
        elif "вахт" in vac_lower or "билет" in vac_lower or "проживан" in vac_lower:
            answer_parts.append("Объекты вахты расположены в Московской области (а также во Владимире). Для кандидатов из других городов мы полностью оплачиваем проезд (покупаем билет до объекта), предоставляем бесплатное комфортное проживание и питание. Заселение сразу в день приезда!")
        else:
            answer_parts.append(f"Объект «{item_title}»: точный адрес и подробный маршрут координатор отправит вам при согласовании смены.")

    # 5.6. Вопрос: сидячая или стоячая работа / нагрузка
    if any(w in t_new_lower for w in ["сидяч", "стояч", "на ногах", "физическ", "тяжел"]):
        answered_intent = True
        if any(w in vac_lower for w in ["чай", "фарма", "косметик", "бьюти", "аптеч"]):
            answer_parts.append("На упаковке и стикеровке можно работать сидя за столом или чередовать сидя/стоя. Возможность работать сидя есть!")
        else:
            answer_parts.append("Работа активная в движении (комплектовка и упаковка на складе), предусмотрены перерывы на отдых и обед.")

    # 5.7. "Не успела прочитать" / "повторите" / "что за работа"
    if any(w in t_new_lower for w in ["не успел", "не прочитал", "повтори"]):
        answered_intent = True
        rate_str = vac_prof.get("rate", "от 3 600 до 4 200 ₽ за смену")
        answer_parts.append(f"Напоминаю условия: {item_title}. Ставка {rate_str}, выплаты без задержек.")

    # 5.8. Вопрос про запись / можно ли выйти / записаться на завтра / смену
    if any(w in t_new_lower for w in ["записа", "выйти на смену", "на завтра", "с завтра", "когда можно выйти"]):
        answered_intent = True
        answer_parts.append("Записаться на смену возможность есть, как раз согласовываем график.")

    # 5.9. Выплата на карту третьего лица / чужую карту
    if any(w in t_new_lower for w in ["третьего лица", "чужую карту", "карту мужа", "карту жены", "карту друга", "карту мамы", "другую карту", "карту родственника"]):
        answered_intent = True
        answer_parts.append("Этот вопрос согласуется индивидуально с координатором: на ряде объектов перечисление на карту другого лица возможно по заявлению. Координатор при звонке сориентирует по правилам.")

    # 5.10. Длительность смены / сколько часов
    if any(w in t_new_lower for w in ["сколько длится", "длительность", "сколько часов", "по времени"]):
        if not any("12 часов" in ap or "08:00 до 20:00" in ap for ap in answer_parts):
            answered_intent = True
            answer_parts.append("Смена длится 12 часов, предусмотрены перерывы на отдых и обед.")

    # 5.11. Актуальна ли вакансия
    if any(w in t_new_lower for w in ["актуально еще", "актуальна еще", "еще актуальн", "актуально ли", "вакансия открыта"]):
        answered_intent = True
        answer_parts.append("Да, вакансия полностью актуальна, как раз ведем запись на смены!")

    # 5.12. Документы для трудоустройства
    if any(w in t_new_lower for w in ["документ", "паспорт", "снилс", "инн", "что нужно для"]):
        answered_intent = True
        answer_parts.append("Для оформления понадобятся паспорт, СНИЛС и ИНН (для иностранных граждан — также патент/регистрация). Оформление быстрое в день обращения.")

    # 5.13. Проживание и питание
    if any(w in t_new_lower for w in ["проживан", "общежити", "хостел", "жиль", "комнат", "питан", "обед"]):
        answered_intent = True
        answer_parts.append("Для сотрудников предоставляется бесплатное комфортное проживание (общежитие со всеми удобствами) и оборудованная комната приема пищи.")

    # 5.14. Вопрос «Вы бот?» / «Это робот?» / «Позовите человека»
    if any(w in t_new_lower for w in ["вы бот", "это бот", "вы робот", "это робот", "живой человек", "с кем я общаюсь", "позовите человека", "оператор", "переведите на оператора"]):
        answered_intent = True
        answer_parts.append("Я специалист по первичному оформлению на смены. Чтобы живой координатор с объекта набрал вас и ответил на все детальные вопросы, мы сейчас согласуем запись.")

    # 5.15. ОСОБЫЙ СЛУЧАЙ: Кандидат глухонемой / слабослышащий / просит только писать
    is_hearing_impaired = any(w in t_new_lower for w in [
        "не слышу", "плохо слышу", "плохо слыш", "по слуху", "инвалид", "глухонемой", "глухонемая", "глухоменная", "глухой", "глухая",
        "слабослышащ", "только напишите", "только пишите", "не могу говорить", "не звоните"
    ])
    if is_hearing_impaired:
        answered_intent = True
        answer_parts.append(
            "Поняла вас, обязательно передала координатору пометку, что вам нужно только писать "
            "(здесь в чате Авито), звонить не будут. Координатор напишет вам сюда!"
        )

    # 5.16. Собеседование / куда приехать / когда можно
    if any(w in t_new_lower for w in ["собеседован", "куда приехать", "куда придти", "когда числа", "когда можно"]):
        answered_intent = True
        answer_parts.append(
            "Собеседование у нас проходит дистанционно по анкете — ехать в офис не нужно! "
            "А на объекте сразу проводится вводный инструктаж и выход в смену. "
            "Координатор свяжется с вами и согласует удобную дату и детали выхода."
        )

    # 5.17. Вопросы и отработка возражений по отправке паспорта
    if any(w in t_new_lower for w in ["зачем паспорт", "почему паспорт", "боюсь скидывать", "не дам паспорт", "зачем фото", "безопасно ли", "куда данные", "зачем данные паспорта"]):
        answered_intent = True
        answer_parts.append(
            "Понимаю ваши переживания! Фото разворота нужно исключительно для оформления пропуска "
            "на охраняемую территорию предприятия и согласования смены службой безопасности. Мы прямой работодатель и работаем строго по законодательству РФ с соблюдением конфиденциальности. "
            "Для оформления требуется четкое фото главного разворота (с серией и номером) без бликов, засветов и посторонних предметов, чтобы пропуск был успешно выписан к вашему приезду."
        )

    # 5.18. Кандидат прислал или подтвердил отправку фото паспорта
    if any(w in t_new_lower for w in ["скинул фото", "отправил фото", "скинула фото", "отправила фото", "скинул паспорт", "скинула паспорт", "паспорт отправил", "паспорт отправила", "вот паспорт", "фото паспорта"]):
        answered_intent = True
        answer_parts.append(
            "Фото зафиксировали, спасибо! Данные переданы для оформления пропуска на объект. "
            "Координатор свяжется с вами для окончательного подтверждения выхода на смену!"
        )

    # 5.19. УНИВЕРСАЛЬНЫЙ ПЕРЕХВАТ ЛЮБЫХ НЕОТВЕЧЕННЫХ ВОПРОСОВ (CATCH-ALL)
    # Гарантирует, что ни один вопрос кандидата не останется без ответа!
    is_candidate_question = (
        "?" in real_cand_text or any(w in t_new_lower for w in [
            "подскажите", "можно ли", "как быть", "где", "когда", "почему",
            "сколько", "что", "есть ли", "бывает ли", "возможно ли", "со скольки"
        ])
    )
    if is_candidate_question and not answered_intent:
        answered_intent = True
        answer_parts.append("По вашему вопросу координатор объекта подробно проконсультирует вас при согласовании смены.")

    # =========================================================================
    # СЦЕНАРИЙ 6: ОБРАБОТКА ТЕЛЕФОНА ИЛИ ОТВЕТОВ НА ВОПРОСЫ
    # =========================================================================
    # Формируем список ТОЛЬКО тех вопросов, на которые кандидат ЕЩЁ НЕ ДАВАЛ ответа
    # и которые мы ЕЩЁ НЕ СПРАШИВАЛИ!
    needed_questions = []
    if not district_known and not already_asked_district:
        needed_questions.append("В каком городе и районе вы проживаете?")
    if not ready_date_known and not already_asked_date:
        needed_questions.append("С какого числа готовы выйти на смену?")
    if not phone_known:
        if not already_asked_phone:
            needed_questions.append(f"И напишите номер телефона для связи — координатор {coord_call_phrase} и согласует запись.")
        else:
            needed_questions.append("Подскажите контактный номер для связи координатора.")

    # ЖЕЛЕЗНОЕ ПРАВИЛО: если город, дата и телефон УЖЕ известны из переписки —
    # КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО задавать какие-либо вопросы повторно!
    if district_known and ready_date_known and phone_known:
        needed_questions = []

    # Если кандидат прислал НОВЫЙ телефон прямо сейчас
    if new_phone:
        ack_phone_str = f"Спасибо, номер {new_phone} зафиксировала!"
        
        # Обязательно проверяем, указал ли кандидат город и дату выхода на смену
        missing_info = []
        if not district_known:
            missing_info.append("в каком городе вы проживаете")
        if not ready_date_known:
            missing_info.append("с какого числа готовы выйти на смену")

        if missing_info:
            followup = f"Уточните ещё, пожалуйста, {' и '.join(missing_info)}? Чтобы координатор сразу закрепил за вами место."
            if answer_parts:
                reply = f"{prefix}{ack_phone_str} " + " ".join(answer_parts) + f"\n\n{followup}"
            else:
                reply = f"{prefix}{ack_phone_str} {followup}"
        else:
            max_invite = (
                "Для записи на смену и передачи информации бригадиру (менеджеру объекта) перейдите, пожалуйста, в наш чат в MAX:\n👉 https://max.ru/id9729371578_bot\n\nНажмите там «Начать» или напишите любое сообщение — там оформим пропуск на объект и запишем вас на смену/заселение!"
            )
            if answer_parts:
                reply = f"{prefix}{ack_phone_str} " + " ".join(answer_parts) + f"\n\n{max_invite}"
            else:
                reply = f"{prefix}{ack_phone_str}\n\n{max_invite}"
        
        safe_send_message(chat_id, reply, already_greeted, first_name)
        print(">>> SENT phone acknowledgment + city/date questions.")
        
        deal_res = sync_candidate_to_b24_deal(chat_id, cand_data_dict)
        create_b24_call_task(
            candidate_name=first_name or cand_name,
            vacancy=item_title,
            phone=new_phone,
            details=f"Кандидат оставил телефон: {new_phone}\nВозраст: {format_age(known_age) if known_age else 'уточняется'}\nГород/Район: {cand_district or 'уточняется'}\nДата выхода: {cand_ready_date or 'уточняется'}",
            chat_id=chat_id,
            responsible_id=deal_res.responsible_id,
            deal_id=deal_res.deal_id,
            is_text_only=is_text_only
        )
        return True

    # Если мы ответили на конкретные вопросы кандидата
    if answered_intent:
        main_answer = " ".join(answer_parts)
        
        closing_parts = []
        if needed_questions:
            closing_parts.append(" ".join(needed_questions))
        elif phone_known and not already_finalized:
            closing_parts.append(
                "Для записи на смену и передачи информации бригадиру (менеджеру объекта) перейдите, пожалуйста, в наш чат в MAX:\n👉 https://max.ru/id9729371578_bot\n\nНажмите там «Начать» или отправьте любое сообщение — там оформим пропуск на объект и запишем вас на смену!"
            )

        reply = f"{prefix}{main_answer}\n\n" + " ".join(closing_parts) if closing_parts else f"{prefix}{main_answer}"
        safe_send_message(chat_id, reply.strip(), already_greeted, first_name)
        print(">>> SENT targeted answer to candidate questions without duplicate inquiries.")
        sync_candidate_to_b24_deal(chat_id, cand_data_dict)
        return True

    # =========================================================================
    # СЦЕНАРИЙ 7: ПЕРВИЧНЫЙ ОТКЛИК — ВЫЖИМКА ПО ВАКАНСИИ (ФОРМАТ НАТАЛЬИ)
    # =========================================================================
    if not already_verified_profile:
        summary_card = vac_prof.get("summary_card")
        if not summary_card:
            summary_card = (
                "Носовихинское шоссе вл 253 с 14\n"
                "От ст Кучино 12 мин ходьбы\n"
                "Упаковка зоотоваров\n"
                "3600 смена\n"
                "Ежедневные выплаты\n"
                "Смены с 8-20\n"
                "График любой\n"
                "Оформление по Самозанятости налог оплачивает компания\n"
                "Актуально?"
            )
        reply = f"{prefix}{summary_card}".strip()
        safe_send_message(chat_id, reply, already_greeted, first_name)
        print(">>> SENT initial vacancy summary card (Natalia style).")
        
        # Синхронизация сделки в CRM (БЕЗ спам-уведомлений, пока нет задачи на звонок!)
        sync_candidate_to_b24_deal(chat_id, cand_data_dict)
        return True

    # Если анкета УЖЕ была актуализирована ранее в диалоге:
    if needed_questions:
        reply = f"{prefix}" + " ".join(needed_questions)
    elif phone_known:
        if already_finalized:
            print(f">>> Final confirmation already sent previously to {cand_name} ({chat_id}). No duplicate message.")
            client.mark_chat_as_read(chat_id)
            return False
        reply = (
            f"{prefix}Ваши данные записаны!\n\nДля записи на смену и передачи информации бригадиру (менеджеру объекта) перейдите, пожалуйста, в наш чат в MAX:\n👉 https://max.ru/id9729371578_bot\n\nНажмите там «Начать» или напишите любое сообщение — там оформим пропуск на объект и согласуем дату выхода!"
        )
    else:
        reply = (
            f"{prefix}Чтобы закрепить за вами смену и передать информацию координатору, "
            f"напишите, пожалуйста, ваш номер телефона для связи."
        )

    sent = safe_send_message(chat_id, reply.strip(), already_greeted, first_name)
    if sent:
        print(">>> SENT dialog continuation reply without repeating questions.")
        sync_candidate_to_b24_deal(chat_id, cand_data_dict)
        return True
    else:
        print(f">>> Duplicate reply blocked for {cand_name} ({chat_id}). Marking as read.")
        client.mark_chat_as_read(chat_id)
        return False

if __name__ == '__main__':
    print("Manual check of live unread chats...")
    unread_chats = client.get_unread_chats(limit=30)
    print(f"Total unread chats fetched: {len(unread_chats)}")
    for c in unread_chats:
        try:
            process_single_chat(c)
        except Exception as e:
            print("Error processing chat:", e)
