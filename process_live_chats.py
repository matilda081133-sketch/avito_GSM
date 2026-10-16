import urllib.request, json, ssl, time, sys, re
from avito_api import AvitoClient
from ai_engine import AIRecruiterEngine, extract_phone, get_uis_phone_for_vacancy
from vacancy_rules import detect_vacancy_profile, evaluate_candidate_fit
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
            print(f">>> CRM TASK CREATED for manager {responsible_id}! Task ID:", res.get('result', {}).get('task', {}).get('id'))
    except Exception as e:
        print("Task create error:", e)

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
        except Exception as e:
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

    raw_msgs = client.get_chat_messages(chat_id, limit=20)
    if not raw_msgs:
        return False

    msgs = list(reversed(raw_msgs))
    
    # =========================================================================
    # ПРАВИЛО 1: СТРОГАЯ ПРОВЕРКА ИСТОРИИ НА ПРИОСТАНОВКУ / ОТКАЗ / СТОП-ФАКТОРЫ
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
        print(f"Skipping chat {chat_id} ({cand_name}): найдено сообщение об отказе/приостановке в истории переписки!")
        return False

    last_msg = msgs[-1]
    
    # Если последнее сообщение отправлено НАМИ — ничего не пишем
    if last_msg.get('author_id') == AVITO_USER_ID:
        return False

    # =========================================================================
    # ПРАВИЛО 2: СТРОГИЙ ФИЛЬТР СВЕЖЕСТИ (НЕ ОТВЕЧАТЬ СТАРЫМ ОТКЛИКАМ СТАРШЕ 24 ЧАСОВ)
    # =========================================================================
    msg_timestamp = last_msg.get('created', 0)
    hours_ago = (time.time() - msg_timestamp) / 3600.0
    if hours_ago > 24.0:
        print(f"Skipping old chat {chat_id} (last message was {hours_ago:.1f} hours ago)")
        return False

    last_text = last_msg.get('content', {}).get('text', '').strip()
    if not last_text or "не поддерживается" in last_text.lower():
        return False

    # =========================================================================
    # ПРАВИЛО 3: КОРОТКИЕ ЗАКРЫВАЮЩИЕ РЕПЛИКИ ВЕЖЛИВОСТИ (CLOSING MESSAGES)
    # Если кандидат просто написал «спасибо», «хорошо», «понятно» — НЕ НАДО СПАМИТЬ!
    # =========================================================================
    clean_last = re.sub(r'[^а-яa-z\s]', '', last_text.lower()).strip()
    closing_words = ["спасибо", "хорошо спасибо", "спасибо большое", "ясно", "понятно", "ок", "хорошо", "договорились", "до свидания"]
    if clean_last in closing_words:
        # Проверяем, было ли уже наше сообщение в диалоге
        had_our_msg = any(m.get('author_id') == AVITO_USER_ID for m in msgs)
        if had_our_msg:
            print(f"Skipping chat {chat_id}: кандидат просто ответил вежливостью ('{last_text}'), диалог уже закрыт.")
            return False

    print(f"\n=======================================================")
    print(f"Processing chat: {chat_id} | Candidate: {cand_name} | Ad: {item_title}")
    print(f"Last candidate message: {last_text}")

    # Извлечение всех известных параметров из истории
    known_phone = ""
    known_age = ""
    known_cit = ""
    known_fio = ""

    all_candidate_text = " ".join([m.get('content', {}).get('text', '') for m in msgs if m.get('author_id') != AVITO_USER_ID])
    
    extracted_phone = extract_phone(all_candidate_text)
    if extracted_phone:
        known_phone = extracted_phone

    for m in msgs:
        txt = m.get('content', {}).get('text', '')
        m_fio = re.search(r'ФИО\s*[—\-:]\s*([^\n\r]+)', txt, re.IGNORECASE)
        m_age = re.search(r'Возраст\s*[—\-:]\s*(\d+)', txt, re.IGNORECASE)
        m_cit = re.search(r'Гражданство\s*[—\-:]\s*([^\n\r]+)', txt, re.IGNORECASE)
        if m_fio and not known_fio: known_fio = m_fio.group(1).strip()
        if m_age and not known_age: known_age = m_age.group(1).strip()
        if m_cit and not known_cit: known_cit = m_cit.group(1).strip()

    if not known_age:
        m_plain_age = re.search(r'\b(\d{2})\s*(?:лет|года|г)?\b', all_candidate_text)
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

    greeting = f"Здравствуйте, {first_name}!" if first_name else "Здравствуйте!"

    # =========================================================================
    # СЦЕНАРИЙ А: КАНДИДАТ ПРИСЛАЛ НОМЕР ТЕЛЕФОНА
    # =========================================================================
    current_phone = extract_phone(last_text)
    if current_phone:
        reply = (
            "Спасибо, контакты зафиксировала! Координатор свяжется с вами для согласования всех деталей и даты выхода. "
            "Если появятся вопросы — пишите прямо сюда в чат, мы на связи!"
        )
        client.send_message(chat_id, reply)
        print(">>> SENT phone confirmation acknowledgment.")
        
        send_b24_notification(
            title=f"КАНДИДАТ ОСТАВИЛ ТЕЛЕФОН: {first_name or cand_name}",
            text=f"Вакансия: {item_title}",
            chat_id=chat_id,
            phone=current_phone
        )
        create_b24_call_task(
            candidate_name=first_name or cand_name,
            vacancy=item_title,
            phone=current_phone,
            details=f"Кандидат оставил телефон в чате: {current_phone}\nВозраст: {format_age(known_age) if known_age else 'уточняется'}\nГражданство: {known_cit or 'РФ'}",
            chat_id=chat_id
        )
        return True

    # =========================================================================
    # СЦЕНАРИЙ Б: КАНДИДАТ СПРАШИВАЕТ «КАК СВЯЗАТЬСЯ / НОМЕР ДЛЯ ЗВОНКА»
    # =========================================================================
    t_lower = last_text.lower()
    if any(w in t_lower for w in ["связа", "позвон", "номер", "телефон", "сохран", "контакт"]):
        direct_phone = get_uis_phone_for_vacancy(item_title)
        reply = (
            f"Вы можете позвонить напрямую по номеру {direct_phone} (звонок бесплатный). "
            f"Это прямой номер координатора объекта!\n\n"
            f"Либо напишите, в какое время вам удобно принять звонок, и мы вас наберем!"
        )
        client.send_message(chat_id, reply)
        print(">>> SENT direct UIS contact number.")
        send_b24_notification(
            title=f"Кандидат запросил контакты: {first_name or cand_name}",
            text=f"Выдан номер {direct_phone} по вакансии {item_title}",
            chat_id=chat_id
        )
        return True

    # =========================================================================
    # СЦЕНАРИЙ В: КАНДИДАТ ЗАДАЛ КОНКРЕТНЫЙ ВОПРОС (ГРАФИК / ОПЛАТА / АДРЕС / ВОЗРАСТ)
    # МЫ ОБЯЗАНЫ ОТВЕТИТЬ ПРЯМО НА ЕГО ВОПРОС БЕЗ ЛОЖНЫХ ОБЕЩАНИЙ!
    # =========================================================================
    vac_prof = detect_vacancy_profile(item_title)
    eval_res = evaluate_candidate_fit(vac_prof, known_age, known_cit)

    # Проверка на несовершеннолетие (строгий стоп-фактор)
    if eval_res["status"] == "UNDERAGE":
        reply = (
            f"{greeting} К сожалению, по требованиям охраны труда на наших объектах трудоустройство возможно строго с 18 лет. "
            f"Будем рады сотрудничеству, когда вам исполнится 18!"
        )
        client.send_message(chat_id, reply)
        print(">>> SENT underage polite refusal.")
        return True

    # 1. Вопрос про график (3-4 дня, подработка, день/ночь, часы смены)
    if any(w in t_lower for w in ["график", "с каких", "до каких", "часов", "ночн", "дневн", "смен", "подработк", "дня в неделю"]):
        reply = (
            f"{greeting}\n"
            f"По графику на позиции «{vac_prof['name']}»:\n"
            f"• Смены: дневные обычно с 08:00 до 20:00, ночные — с 20:00 до 08:00 (предусмотрены перерывы и обед).\n"
            f"• Подработка: график согласуется — возможен выход 3–4 дня в неделю или в ваши свободные дни, а также совмещение дневных и ночных смен.\n\n"
            f"По требованиям объекта: возраст от {vac_prof['min_age']} до {vac_prof['max_age']} лет. "
            f"Окончательное согласование графика и запись проводит координатор объекта при проверке документов.\n\n"
            f"Подскажите, пожалуйста:\n"
            f"1. В каком районе вы проживаете и когда вам удобно выйти на первую смену?\n"
            f"2. Ваш контактный номер телефона для связи — координатор наберет вас и зафиксирует запись!"
        )
        client.send_message(chat_id, reply)
        print(">>> SENT detailed schedule & part-time answer (verified against vacancy).")
        return True

    # 2. Вопрос про возраст / подхожу ли я по возрасту
    if any(w in t_lower for w in ["подойд", "возраст", "45", "49", "50", "55", "60", "пенсион"]):
        if eval_res["status"] == "OVERAGE":
            reply = (
                f"{greeting} По регламенту данного объекта («{vac_prof['name']}») рассматриваются кандидаты до {vac_prof['max_age']} лет "
                f"из-за интенсивных физических нагрузок на смене. Окончательное решение о допуске или наличии альтернативных легких участков "
                f"принимает координатор объекта при звонке. Напишите ваш номер телефона для консультации с координатором."
            )
        else:
            reply = (
                f"{greeting} По позиции «{vac_prof['name']}» базовый возрастной критерий — от {vac_prof['min_age']} до {vac_prof['max_age']} лет. "
                f"Мы не даем предварительных гарантий в переписке — финальное согласование и запись проводит координатор объекта после сверки анкеты и документов.\n\n"
                f"Подскажите, в каком районе вы проживаете и с какого числа готовы выйти на смену?\n"
                f"И напишите ваш контактный номер телефона для связи."
            )
        client.send_message(chat_id, reply)
        print(">>> SENT neutral age criteria explanation (no false promises).")
        return True

    # 3. Вопрос про адрес / где находится / локацию / как добраться
    if any(w in t_lower for w in ["где", "находит", "локац", "адрес", "добира", "салтыков", "кучин"]):
        if any(w in item_title.lower() for w in ["зоо", "смарт", "балаших"]):
            reply = (
                f"{greeting} Склад зоотоваров находится в Балашихе (микрорайон Салтыковка, Носовихинское шоссе). "
                f"От станций «Салтыковская» или «Кучино» добираться всего 5–10 минут на транспорте (МЦД-4 либо автобусы 142, 100).\n\n"
                f"Подскажите, в каком районе вы проживаете и с какого числа готовы выйти на первую смену?\n"
                f"И напишите ваш контактный номер — координатор наберет вас и подскажет точный маршрут!"
            )
            client.send_message(chat_id, reply)
            print(">>> SENT location answer.")
            return True

    # 4. Вопрос про ставку / сколько платят / выплаты
    if any(w in t_lower for w in ["скольк", "оплат", "плат", "ставк", "зарплат", "деньг", "в час"]):
        rate_str = vac_prof.get("rate", "от 3 600 до 4 200 ₽ за смену (чистыми на руки)")
        reply = (
            f"{greeting} Ставка на объекте составляет {rate_str}, выплаты официальные без задержек!\n\n"
            f"Подскажите, в каком районе вы проживаете и когда готовы выйти на смену?\n"
            f"И напишите ваш контактный номер телефона для связи — координатор наберет и всё подробно расскажет."
        )
        client.send_message(chat_id, reply)
        print(">>> SENT salary/rate answer.")
        return True

    # =========================================================================
    # СЦЕНАРИЙ Г: ПЕРВИЧНЫЙ ОТКЛИК (ЕСЛИ ДАННЫЕ УКАЗАНЫ — НЕ ПЕРЕСПРАШИВАТЬ!)
    # =========================================================================
    if eval_res["status"] == "OVERAGE":
        reply = (
            f"{greeting} Вакансия актуальна. По регламенту объекта «{vac_prof['name']}» "
            f"рассматриваются кандидаты до {vac_prof['max_age']} лет (смены на ногах). "
            f"Возможность записи или альтернативные участки согласует координатор объекта при звонке.\n\n"
            f"Подскажите ваш контактный номер телефона для связи?"
        )
        client.send_message(chat_id, reply)
        print(">>> SENT overage notification (no false approval).")
        return True

    profile_parts = []
    if known_age:
        profile_parts.append(format_age(known_age))
    if known_cit:
        profile_parts.append(f"гражданство {known_cit}")

    if profile_parts:
        status_line = (
            f"Вижу вашу анкету ({', '.join(profile_parts)}).\n"
            f"По объекту «{vac_prof['name']}» базовые требования: возраст от {vac_prof['min_age']} до {vac_prof['max_age']} лет. "
            f"Окончательное согласование и запись на смену проводит координатор после сверки документов.\n"
        )
    else:
        status_line = ""

    missing_questions = []
    if not known_age and not known_cit:
        missing_questions.append("Ваш возраст и гражданство")
    elif not known_age:
        missing_questions.append("Ваш возраст")
    elif not known_cit:
        missing_questions.append("Ваше гражданство")

    missing_questions.append("В каком районе вы проживаете и с какого числа готовы выйти на смену")
    if not known_phone:
        missing_questions.append("Ваш контактный номер телефона для связи (координатор наберет и согласует запись)")

    questions_formatted = "\n".join([f"{i+1}. {q}" for i, q in enumerate(missing_questions)])

    reply = (
        f"{greeting} Вакансия актуальна, как раз ведем запись на смены.\n\n"
        f"{status_line}\n"
        f"Подскажите, пожалуйста:\n"
        f"{questions_formatted}"
    )

    client.send_message(chat_id, reply)
    print(">>> SENT tailored response (respecting known profile and vacancy criteria).")
    
    send_b24_notification(
        title=f"Отклик взят в работу: {first_name or cand_name}",
        text=f"Вакансия: {item_title}. Заданы уточняющие вопросы по выходу.",
        chat_id=chat_id,
        phone=known_phone
    )
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
