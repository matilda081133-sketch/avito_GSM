# -*- coding: utf-8 -*-
import urllib.request, json, ssl, time, sys, re
from avito_api import AvitoClient
from ai_engine import AIRecruiterEngine, extract_phone, get_uis_phone_for_vacancy
from vacancy_rules import detect_vacancy_profile, evaluate_candidate_fit
from b24_sync import sync_candidate_to_b24_deal, get_or_reveal_candidate_phone
from config import AVITO_CLIENT_ID, AVITO_CLIENT_SECRET, AVITO_USER_ID, B24_WEBHOOK_URL

sys.stdout.reconfigure(encoding='utf-8')
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

client = AvitoClient(AVITO_CLIENT_ID, AVITO_CLIENT_SECRET, AVITO_USER_ID)
engine = AIRecruiterEngine()

# Core team in Bitrix24
VALERIA_MARKETER_ID = 82166    # Валерия Цицилина (Маркетолог)
RECRUITERS = [
    {"id": 40, "name": "Виктория Фарафонова"},
    {"id": 32, "name": "Наталья Кучма"},
    {"id": 81596, "name": "Маргарита Бабынина"},
]
RECRUITER_IDS = [40, 32, 81596]
NOTIFY_USER_IDS = [VALERIA_MARKETER_ID, 40, 32, 81596]

_recruiter_cycle = 0

def get_next_recruiter_id():
    global _recruiter_cycle
    rec_id = RECRUITER_IDS[_recruiter_cycle % len(RECRUITER_IDS)]
    _recruiter_cycle += 1
    return rec_id

def create_b24_call_task(candidate_name: str, vacancy: str, phone: str, details: str, chat_id: str, responsible_id: int = None):
    if not responsible_id:
        responsible_id = get_next_recruiter_id()
    avito_url = f"https://www.avito.ru/profile/messenger/channel/{chat_id}"
    desc = (
        f"🔥 [B]Кандидат успешно квалифицирован ботом на Авито![/B]\n\n"
        f"• [B]Кандидат:[/B] {candidate_name}\n"
        f"• [B]Телефон:[/B] {phone or 'уточняется в чате'}\n"
        f"• [B]Вакансия:[/B] {vacancy}\n"
        f"• [B]Детали:[/B] {details}\n\n"
        f"👉 [URL={avito_url}]Открыть диалог на Авито[/URL]"
    )
    payload = json.dumps({
        'fields': {
            'TITLE': f"📞 ПОЗВОНИТЬ: {candidate_name} ({vacancy[:30]})",
            'DESCRIPTION': desc,
            'RESPONSIBLE_ID': responsible_id,
            'PRIORITY': 2
        }
    }).encode('utf-8')
    req = urllib.request.Request(B24_WEBHOOK_URL + 'tasks.task.add', data=payload, headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, context=ctx) as resp:
            res = json.loads(resp.read().decode('utf-8'))
            task_id = res.get('result', {}).get('task', {}).get('id')
            print(f">>> CRM TASK CREATED for manager {responsible_id}! Task ID: {task_id}")
            return task_id
    except Exception as e:
        print("Task create error:", e)
        return None

def send_b24_notification(title: str, text: str, chat_id: str, phone: str = ""):
    avito_chat_url = f"https://www.avito.ru/profile/messenger/channel/{chat_id}"
    msg_parts = [
        f"🚨 [B]{title}[/B]",
        f"💬 {text}",
    ]
    if phone:
        msg_parts.append(f"📞 Телефон: [B]{phone}[/B]")
    msg_parts.append(f"👉 [URL={avito_chat_url}]Открыть чат на Авито[/URL]")
    
    full_msg = "\n".join(msg_parts)
    for uid in NOTIFY_USER_IDS:
        payload = json.dumps({'USER_ID': uid, 'MESSAGE': full_msg}).encode('utf-8')
        req = urllib.request.Request(B24_WEBHOOK_URL + 'im.notify.system.add', data=payload, headers={'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(req, context=ctx) as resp:
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
    
    known_places = [
        "петушки", "салтыковка", "кучино", "балашиха", "железнодорожный",
        "реутов", "люберцы", "химки", "москва", "зарайск", "кашира",
        "владимир", "опалиха", "красногорск", "павловский посад", "новогиреево",
        "звенигород", "долгопрудный", "мытищи", "королев", "одинцово", "подольск", "тула", "донской"
    ]
    for p in known_places:
        if re.search(rf'\b{re.escape(p)}[а-я]*\b', cleaned.lower()):
            return p.capitalize()

    # Точные паттерны проживания
    m_dist = re.search(r'\b(?:живу в|живу около|живу на|метро|город|г\.|ст\.|станци[яи]|район)\s+([а-яa-z\-]+)', cleaned, re.IGNORECASE)
    if m_dist:
        match_str = m_dist.group(1).strip()
        stop_words = ["москвы", "области", "россии", "работы", "опыта", "вами", "связаться", "сообщение", "отклики", "раздела", "вакансию", "сохранились", "этого", "договорились"]
        if match_str.lower() not in stop_words and len(match_str) > 2:
            return match_str.capitalize()

    return ""

def extract_candidate_ready_date(text: str) -> str:
    if not text:
        return ""
    t_low = text.lower()
    m = re.search(
        r'\b(?:на\s+завтра|завтра|сегодня|со\s+следующей\s+недели|'
        r'с\s+понедельник[а-я]*|со\s+вторник[а-я]*|со?\s+среды|с\s+четверг[а-я]*|с\s+пятниц[а-я]*|в\s+выходные|'
        r'хоть\s+сейчас|хоть\s+завтра|прямо\s+сейчас|готов[а-я]*\s+выйти|могу\s+выйти|выйти\s+с|выйти\s+со|'
        r'с\s+\d{1,2}(?:\s+[а-я]+|\.\d{2})?|на\s+этой\s+неделе)\b', 
        t_low
    )
    if m:
        return m.group(0).strip()
    return ""

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

    raw_msgs = client.get_chat_messages(chat_id, limit=25)
    if not raw_msgs:
        return False

    msgs = list(reversed(raw_msgs))
    
    # =========================================================================
    # ПРАВИЛО 1: СТОП-ФРАЗЫ И ОТКАЗЫ В ПЕРЕПИСКЕ
    # =========================================================================
    all_chat_texts = " ".join([str(m.get('content', {}).get('text', '')).lower() for m in msgs])
    stop_phrases = [
        "остановили выбор", "других кандидатах", "не соответствует требованиям",
        "сохраним ваши контакты", "приостанов", "набор закрыт", "вакансия закрыта",
        "вакансия неактуальн", "не готовы предложить", "вынуждены отказать",
        "не подходите", "не подходит", "больше не пишите", "уже устроился",
        "уже нашел", "уже нашла", "не актуально", "неактуально", "не беспокойте",
        "отменили", "✘ кандидат не соответствует"
    ]
    if any(sp in all_chat_texts for sp in stop_phrases):
        return False

    # =========================================================================
    # ПРАВИЛО 2: ОПРЕДЕЛЯЕМ НАШЕ ПОСЛЕДНЕЕ СООБЩЕНИЕ И НОВЫЕ СООБЩЕНИЯ КАНДИДАТА
    # =========================================================================
    our_last_idx = -1
    for i, m in enumerate(msgs):
        if m.get('author_id') == AVITO_USER_ID:
            our_last_idx = i

    # Если последнее сообщение отправлено НАМИ — ждать ответа кандидата, ничего не отправлять!
    if our_last_idx == len(msgs) - 1:
        return False

    new_candidate_msgs = msgs[our_last_idx + 1:]
    if not new_candidate_msgs:
        return False

    # Фильтр свежести: проверяем самое свежее входящее сообщение
    latest_msg = new_candidate_msgs[-1]
    msg_timestamp = latest_msg.get('created', 0)
    hours_ago = (time.time() - msg_timestamp) / 3600.0
    if hours_ago > 36.0:
        return False

    # Собираем весь текст новых сообщений от кандидата
    new_text_list = [str(m.get('content', {}).get('text', '')).strip() for m in new_candidate_msgs]
    new_text = " \n ".join([t for t in new_text_list if t and "не поддерживается" not in t.lower()]).strip()
    if not new_text:
        return False

    # =========================================================================
    # ПРАВИЛО 3: КОРОТКИЕ ЗАКРЫВАЮЩИЕ РЕПЛИКИ ВЕЖЛИВОСТИ (НЕ СПАМИТЬ!)
    # =========================================================================
    clean_text_for_closing = re.sub(r'\[Системное сообщение\].*?(?:\n|$)', '', new_text, flags=re.IGNORECASE)
    clean_text_for_closing = re.sub(r'данные сохранились.*?(?:\n|$)', '', clean_text_for_closing, flags=re.IGNORECASE)
    clean_new = re.sub(r'[^а-яa-z\s]', '', clean_text_for_closing.lower()).strip()
    closing_words = ["спасибо", "хорошо спасибо", "спасибо большое", "ясно", "понятно", "ок", "хорошо", "договорились", "до свидания"]
    if clean_new in closing_words and our_last_idx != -1:
        return False

    # =========================================================================
    # СБОР И АНАЛИЗ ВСЕЙ ИСТОРИИ ДИАЛОГА (СТРОГАЯ ПАМЯТЬ)
    # =========================================================================
    all_cand_msgs = [m for m in msgs if m.get('author_id') != AVITO_USER_ID]
    all_our_msgs = [m for m in msgs if m.get('author_id') == AVITO_USER_ID]

    all_cand_text = " \n ".join([str(m.get('content', {}).get('text', '')) for m in all_cand_msgs])
    all_our_text = " \n ".join([str(m.get('content', {}).get('text', '')) for m in all_our_msgs]).lower()

    # 1. Телефон
    new_phone = extract_phone(new_text)
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

    # 3. Район / город проживания
    cand_district = extract_candidate_district(all_cand_text)
    district_known = bool(cand_district)

    # 4. Дата готовности к выходу
    cand_ready_date = extract_candidate_ready_date(all_cand_text)
    ready_date_known = bool(cand_ready_date)

    # 5. Что мы УЖЕ спрашивали у кандидата в переписке (чтобы не повторяться!)
    already_asked_district = ("в каком районе" in all_our_text or "где вы проживаете" in all_our_text or "где проживаете" in all_our_text)
    already_asked_date = ("с какого числа" in all_our_text or "когда готовы" in all_our_text or "когда вам удобно" in all_our_text)
    already_asked_phone = ("номер телефона" in all_our_text or "номер для связи" in all_our_text or "контактный номер" in all_our_text)

    # 6. Актуализировали ли мы уже анкету
    already_verified_profile = any(
        phrase in all_our_text for phrase in [
            "данные актуальны", "вижу вашу анкету", "вижу анкету", "анкета актуальна"
        ]
    )

    # =========================================================================
    # ПРАВИЛО 4: СТРОЖАЙШИЙ ЗАПРЕТ НА ПОВТОРНЫЕ ПРИВЕТСТВИЯ В ОДИН ДЕНЬ
    # Если мы уже хоть раз отправляли сообщение кандидату -> НИКАКИХ "Здравствуйте"!
    # =========================================================================
    already_greeted = (our_last_idx != -1)
    if already_greeted:
        prefix = f"{first_name}, " if first_name else ""
    else:
        prefix = f"Здравствуйте, {first_name}!\n" if first_name else "Здравствуйте!\n"

    vac_prof = detect_vacancy_profile(item_title)
    eval_res = evaluate_candidate_fit(vac_prof, known_age, known_cit)

    cand_data_dict = {
        "name": first_name or cand_name,
        "age": known_age,
        "citizenship": known_cit,
        "phone": known_phone,
        "vacancy": item_title,
        "district": cand_district,
        "ready_date": cand_ready_date,
        "schedule_pref": ""
    }

    # Очищаем текст от системных уведомлений платформы
    clean_cand_text = re.sub(r'\[Системное сообщение\].*?(?:\n|$)', '', new_text, flags=re.IGNORECASE)
    clean_cand_text = re.sub(r'данные сохранились.*?(?:\n|$)', '', clean_cand_text, flags=re.IGNORECASE)
    clean_cand_text = re.sub(r'кандидат откликнулся.*?(?:\n|$)', '', clean_cand_text, flags=re.IGNORECASE)
    clean_cand_text = clean_cand_text.lower().strip()

    t_new_lower = clean_cand_text
    print(f"\n=======================================================")
    print(f"Chat: {chat_id} | Candidate: {cand_name} | Already greeted: {already_greeted}")
    print(f"Clean candidate text: '{t_new_lower}'")
    print(f"Phone known: {phone_known} ({known_phone}) | District: {district_known} ({cand_district}) | Date: {ready_date_known} ({cand_ready_date})")

    # =========================================================================
    # СЦЕНАРИЙ 1: СТОП-ФАКТОР ПО ВОЗРАСТУ (МЛАДШЕ 18 ЛЕТ)
    # =========================================================================
    if eval_res["status"] == "UNDERAGE":
        reply = (
            f"{prefix}К сожалению, по требованиям охраны труда на объектах трудоустройство строго с 18 лет. "
            f"Будем рады сотрудничеству по достижении совершеннолетия!"
        )
        client.send_message(chat_id, reply)
        print(">>> SENT underage polite refusal.")
        sync_candidate_to_b24_deal(chat_id, cand_data_dict)
        return True

    # =========================================================================
    # СЦЕНАРИЙ 2: КАНДИДАТ ПИШЕТ «Я УЖЕ НАПИСАЛА / УЖЕ ОТВЕТИЛА»
    # =========================================================================
    if t_new_lower and any(w in t_new_lower for w in ["уже написал", "уже ответил", "ужэ написал", "написала вам", "я же написала", "я же сказал"]):
        if phone_known:
            reply = (
                f"{prefix}Да, всё верно! Ваши контакты ({known_phone}) зафиксировала и передала координатору. "
                f"Он свяжется с вами в ближайшее время для записи на смену."
            )
        else:
            reply = (
                f"{prefix}Прошу прощения за накладку! Чтобы координатор мог набрать вас и закрепить смену, "
                f"напишите, пожалуйста, ваш контактный номер телефона."
            )
        client.send_message(chat_id, reply)
        print(">>> SENT candidate already answered acknowledgment.")
        sync_candidate_to_b24_deal(chat_id, cand_data_dict)
        return True

    # =========================================================================
    # СЦЕНАРИЙ 3: КАНДИДАТ СПРАШИВАЕТ «КАК СВЯЗАТЬСЯ / ПРЯМОЙ НОМЕР»
    # =========================================================================
    if t_new_lower and any(w in t_new_lower for w in ["как связа", "позвон", "прямой номер", "какой номер", "номер для связи"]):
        direct_phone = get_uis_phone_for_vacancy(item_title)
        reply = (
            f"{prefix}Прямой номер координатора объекта: {direct_phone} (звонок бесплатный). "
            f"Либо оставьте ваш номер телефона, и координатор наберет вас сам."
        )
        client.send_message(chat_id, reply)
        print(">>> SENT direct UIS contact number.")
        sync_candidate_to_b24_deal(chat_id, cand_data_dict)
        return True

    # Блок верификации анкеты (если еще не верифицировали)
    profile_parts = []
    if known_age:
        profile_parts.append(format_age(known_age))
    if known_cit:
        profile_parts.append(f"гражданство {known_cit}")

    if profile_parts:
        verification_block = f"Вижу вашу анкету ({', '.join(profile_parts)}) — подскажите, данные актуальны?"
    else:
        verification_block = "Подскажите ваш возраст и гражданство — данные актуальны?"

    # =========================================================================
    # СЦЕНАРИЙ 4: КАНДИДАТ ОТВЕТИЛ «ДА / ВСЁ ВЕРНО / АКТУАЛЬНО» НА НАШ ВОПРОС ПО АНКЕТЕ
    # =========================================================================
    if already_verified_profile and t_new_lower in ["да", "актуально", "да актуально", "все верно", "всё верно", "верно", "всё так", "все так", "конечно", "верны", "да все верно", "да всё верно"]:
        needed_questions = []
        if not district_known and not already_asked_district:
            needed_questions.append("В каком районе вы проживаете?")
        if not ready_date_known and not already_asked_date:
            needed_questions.append("С какого числа готовы выйти на смену?")
        if not phone_known:
            needed_questions.append("И напишите номер телефона для связи — координатор наберет и запишет вас.")
        else:
            needed_questions.append(f"Координатор свяжется с вами по номеру {known_phone} для согласования записи!")

        reply = f"{prefix}Отлично! " + " ".join(needed_questions)
        client.send_message(chat_id, reply)
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

    # 5.4. Вопрос про график / смены / часы / подработку
    if any(w in t_new_lower for w in ["график", "с каких", "до каких", "ночн", "дневн", "подработк", "дня в неделю"]):
        if not any("дневной смены" in ap for ap in answer_parts):
            answered_intent = True
            answer_parts.append(
                "По графику: дневные смены с 08:00 до 20:00, ночные — с 20:00 до 08:00. На подработку можно выходить по 3–4 смены в неделю в удобные дни."
            )

    # 5.5. Вопрос про адрес / где находится / как добираться / транспорт
    if any(w in t_new_lower for w in ["где", "находит", "локац", "адрес", "добира", "салтыков", "кучин", "далеко", "транспорт", "автобус"]):
        answered_intent = True
        if any(w in vac_lower for w in ["зоо", "смарт", "балаших"]):
            answer_parts.append("Склад находится в Балашихе (микрорайон Салтыковка, 5–10 минут от станций Кучино или Салтыковская).")
        elif "зарайск" in vac_lower or "кашир" in vac_lower:
            answer_parts.append("Объект с бесплатным проживанием и питанием, организован корпоративный транспорт.")
        else:
            answer_parts.append(f"Объект: {item_title}. Координатор подробно сориентирует по маршруту.")

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

    # 5.14. УНИВЕРСАЛЬНЫЙ ПЕРЕХВАТ ЛЮБЫХ НЕОТВЕЧЕННЫХ ВОПРОСОВ (CATCH-ALL)
    # Гарантирует, что ни один вопрос кандидата не останется без ответа!
    is_candidate_question = (
        "?" in new_text or any(w in t_new_lower for w in [
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
        needed_questions.append("В каком районе вы проживаете?")
    if not ready_date_known and not already_asked_date:
        needed_questions.append("С какого числа готовы выйти на смену?")
    if not phone_known:
        if not already_asked_phone:
            needed_questions.append("И напишите номер телефона для связи — координатор наберет и согласует запись.")
        else:
            needed_questions.append("Подскажите контактный номер для звонка координатора.")

    # Если кандидат прислал НОВЫЙ телефон прямо сейчас
    if new_phone:
        ack_phone_str = f"Номер {new_phone} зафиксировала!"
        lead_block = f"{verification_block}\n" if not already_verified_profile else ""
        if answer_parts:
            reply = f"{prefix}{lead_block}{ack_phone_str} " + " ".join(answer_parts) + "\nКоординатор свяжется с вами для записи на смену!"
        else:
            reply = f"{prefix}{lead_block}Спасибо, номер {new_phone} зафиксировала! Координатор свяжется с вами для записи и ответит на все вопросы."
        
        client.send_message(chat_id, reply)
        print(">>> SENT phone acknowledgment + answers.")
        
        send_b24_notification(
            title=f"КАНДИДАТ ОСТАВИЛ ТЕЛЕФОН: {first_name or cand_name}",
            text=f"Вакансия: {item_title}",
            chat_id=chat_id,
            phone=new_phone
        )
        create_b24_call_task(
            candidate_name=first_name or cand_name,
            vacancy=item_title,
            phone=new_phone,
            details=f"Кандидат оставил телефон: {new_phone}\nВозраст: {format_age(known_age) if known_age else 'уточняется'}\nРайон: {cand_district or 'уточняется'}",
            chat_id=chat_id
        )
        sync_candidate_to_b24_deal(chat_id, cand_data_dict)
        return True

    # Если мы ответили на конкретные вопросы кандидата
    if answered_intent:
        lead_block = f"{verification_block}\n" if not already_verified_profile else ""
        main_answer = " ".join(answer_parts)
        
        closing_parts = []
        if needed_questions:
            closing_parts.append(" ".join(needed_questions))
        elif phone_known:
            closing_parts.append(f"Координатор наберет вас по номеру {known_phone} и согласует запись на смену!")

        reply = f"{prefix}{lead_block}{main_answer}\n\n" + " ".join(closing_parts)
        client.send_message(chat_id, reply.strip())
        print(">>> SENT targeted answer to candidate questions without duplicate inquiries.")
        sync_candidate_to_b24_deal(chat_id, cand_data_dict)
        return True

    # =========================================================================
    # СЦЕНАРИЙ 7: ПЕРВИЧНЫЙ ОТКЛИК ИЛИ ПРОДОЛЖЕНИЕ ДИАЛОГА
    # =========================================================================
    if not already_verified_profile:
        # Первое настоящее сообщение кандидату (актуализация анкеты)
        closing_q = " ".join(needed_questions) if needed_questions else "Координатор свяжется с вами для согласования выхода!"
        if already_greeted:
            reply = f"{prefix}{verification_block}\n{closing_q}"
        else:
            reply = (
                f"{prefix}Вакансия актуальна, как раз ведем запись на смены.\n"
                f"{verification_block}\n"
                f"{closing_q}"
            )

        client.send_message(chat_id, reply.strip())
        print(">>> SENT initial verification response.")
        
        send_b24_notification(
            title=f"Отклик взят в работу: {first_name or cand_name}",
            text=f"Вакансия: {item_title}",
            chat_id=chat_id,
            phone=known_phone
        )
        sync_candidate_to_b24_deal(chat_id, cand_data_dict)
        return True

    # Если анкета УЖЕ была актуализирована ранее в диалоге:
    if needed_questions:
        reply = f"{prefix}" + " ".join(needed_questions)
    elif phone_known:
        reply = (
            f"{prefix}Ваши данные записаны! Координатор свяжется с вами в ближайшее время по номеру {known_phone}. "
            f"Если остались вопросы по объекту — напишите, с удовольствием подскажу!"
        )
    else:
        reply = (
            f"{prefix}Чтобы закрепить за вами смену и передать информацию координатору, "
            f"напишите, пожалуйста, ваш номер телефона для связи."
        )

    client.send_message(chat_id, reply.strip())
    print(">>> SENT dialog continuation reply without repeating questions.")
    sync_candidate_to_b24_deal(chat_id, cand_data_dict)
    return True

if __name__ == '__main__':
    print("Manual check of live unread chats...")
    unread_chats = client.get_unread_chats(limit=30)
    print(f"Total unread chats fetched: {len(unread_chats)}")
    for c in unread_chats:
        try:
            process_single_chat(c)
        except Exception as e:
            print("Error processing chat:", e)
