# -*- coding: utf-8 -*-
import urllib.request, json, ssl, time, sys, re
from avito_api import AvitoClient
from ai_engine import AIRecruiterEngine, extract_phone, get_uis_phone_for_vacancy
from vacancy_rules import detect_vacancy_profile, evaluate_candidate_fit
from b24_sync import sync_candidate_to_b24_deal
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
    # Удаляем системные уведомления Авито
    cleaned = re.sub(r'\[Системное сообщение\].*?(?:\n|$)', '', text, flags=re.IGNORECASE)
    cleaned = re.sub(r'данные сохранились.*?(?:\n|$)', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'кандидат откликнулся.*?(?:\n|$)', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'отклики.*?(?:\n|$)', '', cleaned, flags=re.IGNORECASE)
    
    # Удаляем системные поля ФИО и Гражданство, чтобы отчество (например Владимировна) не путалось с городом (Владимир)
    cleaned = re.sub(r'ФИО\s*[—\-:]\s*[^\n\r]+', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'Гражданство\s*[—\-:]\s*[^\n\r]+', '', cleaned, flags=re.IGNORECASE)
    
    m_dist = re.search(r'\b(?:живу в|район|живу на|метро|город|г\.|ст\.|станци[яи]|\bиз\b|\bс\b)\s+([а-яa-z\-]+(?:\s+[а-яa-z\-]+)?)', cleaned, re.IGNORECASE)
    if m_dist:
        match_str = m_dist.group(1).strip()
        stop_words = ["москвы", "области", "россии", "работы", "опыта", "вами", "связаться", "сообщение", "отклики", "раздела", "вакансию", "сохранились", "этого"]
        if match_str.lower() not in stop_words and len(match_str) > 2:
            return match_str.capitalize()
    
    known_places = [
        "петушки", "салтыковка", "кучино", "балашиха", "железнодорожный",
        "реутов", "люберцы", "химки", "москва", "зарайск", "кашира",
        "владимир", "опалиха", "красногорск", "павловский посад"
    ]
    for p in known_places:
        if re.search(rf'\b{re.escape(p)}\b', cleaned.lower()):
            return p.capitalize()
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
    clean_new = re.sub(r'[^а-яa-z\s]', '', new_text.lower()).strip()
    closing_words = ["спасибо", "хорошо спасибо", "спасибо большое", "ясно", "понятно", "ок", "хорошо", "договорились", "до свидания"]
    if clean_new in closing_words and our_last_idx != -1:
        return False

    # =========================================================================
    # СБОР И АНАЛИЗ ВСЕЙ ИСТОРИИ ДИАЛОГА
    # =========================================================================
    all_cand_msgs = [m for m in msgs if m.get('author_id') != AVITO_USER_ID]
    all_our_msgs = [m for m in msgs if m.get('author_id') == AVITO_USER_ID]

    all_cand_text = " \n ".join([str(m.get('content', {}).get('text', '')) for m in all_cand_msgs])
    all_our_text = " \n ".join([str(m.get('content', {}).get('text', '')) for m in all_our_msgs]).lower()

    # Телефон: проверяем сначала в новых сообщениях, затем во всей истории кандидата
    new_phone = extract_phone(new_text)
    known_phone = new_phone or extract_phone(all_cand_text)
    phone_known = bool(known_phone)

    # Имя, возраст, гражданство из системных блоков анкеты
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

    # Район / город проживания
    cand_district = extract_candidate_district(all_cand_text)
    district_known = bool(cand_district)

    # Дата готовности к выходу
    cand_ready_date = ""
    m_date = re.search(r'(?:готов[а-я]* выйти|выйти|с|со)\s*(\d{1,2}(?:\s+[а-я]+|\.\d{2})?|завтра|понедельник[а-я]*|сегодня)', all_cand_text, re.IGNORECASE)
    if m_date:
        cand_ready_date = m_date.group(1).strip()
    ready_date_known = bool(cand_ready_date)

    # Что мы УЖЕ спрашивали у кандидата в переписке (чтобы не повторяться!)
    already_asked_district = ("в каком районе" in all_our_text or "где вы проживаете" in all_our_text or "где проживаете" in all_our_text)
    already_asked_date = ("с какого числа" in all_our_text or "когда готовы" in all_our_text or "когда вам удобно" in all_our_text)
    already_asked_phone = ("номер телефона" in all_our_text or "номер для связи" in all_our_text or "контактный номер" in all_our_text)

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
    print(f"Phone known: {phone_known} ({known_phone}) | District known: {district_known} ({cand_district})")

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

    # =========================================================================
    # СЦЕНАРИЙ 4: ВОПРОСЫ ПО ВАКАНСИИ (ОПЛАТА, ГРАФИК, АДРЕС, СТОЯЧАЯ/СИДЯЧАЯ)
    # =========================================================================
    answered_intent = False
    answer_parts = []

    # 4.1. Вопрос про периодичность выплат / ежедневная оплата
    if any(w in t_new_lower for w in ["каждый день", "ежедневн", "каждую смену", "2 раза", "раз в месяц", "раз в неделю", "когда расчет", "как оплачива", "как у вас оплата", "как с оплатой", "когда оплата"]):
        answered_intent = True
        vac_lower = item_title.lower()
        if any(w in vac_lower for w in ["зоо", "смарт", "балаших", "посад", "чай", "опалих"]):
            answer_parts.append("Выплаты ежедневные — расчет сразу после отработанной смены от 3 600 ₽ чистыми на руки.")
        elif "вахт" in vac_lower:
            answer_parts.append("На вахте выплаты стабильные: еженедельные авансы и полный расчет в конце вахты.")
        else:
            rate_str = vac_prof.get("rate", "от 3 600 до 4 200 ₽ за смену")
            answer_parts.append(f"Ставка {rate_str}, выплаты официальные и регулярные без задержек.")

    # 4.2. Вопрос про ставку / сколько платят
    elif any(w in t_new_lower for w in ["скольк", "ставк", "зарплат", "деньг", "в час"]):
        answered_intent = True
        rate_str = vac_prof.get("rate", "от 3 600 до 4 200 ₽ за смену")
        answer_parts.append(f"Ставка на объекте составляет {rate_str}, выплаты без задержек.")

    # 4.3. Вопрос про график / смены / часы / подработку
    if any(w in t_new_lower for w in ["график", "с каких", "до каких", "часов", "ночн", "дневн", "смен", "подработк", "дня в неделю"]):
        answered_intent = True
        answer_parts.append(
            "По графику: дневные смены с 08:00 до 20:00, ночные — с 20:00 до 08:00. "
            "На подработку можно выходить по 3–4 смены в неделю в удобные дни."
        )

    # 4.4. Вопрос про адрес / где находится / как добираться
    if any(w in t_new_lower for w in ["где", "находит", "локац", "адрес", "добира", "салтыков", "кучин", "далеко"]):
        answered_intent = True
        if any(w in item_title.lower() for w in ["зоо", "смарт", "балаших"]):
            answer_parts.append("Склад находится в Балашихе (микрорайон Салтыковка, 5–10 минут от станций Кучино или Салтыковская).")
        elif "зарайск" in item_title.lower() or "кашир" in item_title.lower():
            answer_parts.append("Объект с бесплатным проживанием и питанием, организован корпоративный транспорт.")
        else:
            answer_parts.append(f"Объект: {item_title}. Координатор подробно сориентирует по маршруту.")

    # 4.5. Вопрос: сидячая или стоячая работа / нагрузка
    if any(w in t_new_lower for w in ["сидяч", "стояч", "на ногах", "физическ", "тяжел"]):
        answered_intent = True
        vac_lower = item_title.lower()
        if any(w in vac_lower for w in ["чай", "фарма", "косметик", "бьюти", "аптеч"]):
            answer_parts.append("На упаковке и стикеровке можно работать сидя за столом или чередовать сидя/стоя. Возможность работать сидя есть!")
        else:
            answer_parts.append("Работа активная в движении (комплектовка и упаковка на складе), предусмотрены перерывы на отдых и обед.")

    # 4.6. "Не успела прочитать" / "повторите" / "что за работа"
    if any(w in t_new_lower for w in ["не успел", "не прочитал", "повтори", "что за работа"]):
        answered_intent = True
        rate_str = vac_prof.get("rate", "от 3 600 до 4 200 ₽ за смену")
        answer_parts.append(f"Напоминаю условия: {item_title}. Ставка {rate_str}, выплаты без задержек.")

    # =========================================================================
    # СЦЕНАРИЙ 5: СВЯЗКА ОТВЕТА С ФИКСАЦИЕЙ ДАННЫХ ИЛИ СЛЕДУЮЩИМ ШАГОМ
    # =========================================================================
    # Если кандидат прислал НОВЫЙ телефон прямо сейчас
    if new_phone:
        ack_phone_str = f"Номер {new_phone} зафиксировала!"
        if answer_parts:
            reply = f"{prefix}{ack_phone_str} " + " ".join(answer_parts) + "\nКоординатор свяжется с вами для записи на смену!"
        else:
            reply = f"{prefix}Спасибо, номер {new_phone} зафиксировала! Координатор свяжется с вами для записи и ответит на все вопросы."
        
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
        main_answer = " ".join(answer_parts)
        if phone_known:
            closing_step = "Координатор наберет вас по указанному номеру и согласует запись на смену!"
        elif not already_asked_phone:
            closing_step = "Напишите ваш контактный номер телефона для связи — координатор наберет и согласует запись."
        else:
            closing_step = "Подскажите номер для звонка координатора, чтобы записаться на смену."

        reply = f"{prefix}{main_answer}\n\n{closing_step}"
        client.send_message(chat_id, reply)
        print(">>> SENT targeted answer to candidate questions.")
        sync_candidate_to_b24_deal(chat_id, cand_data_dict)
        return True

    # =========================================================================
    # СЦЕНАРИЙ 6: ПЕРВИЧНЫЙ ОТКЛИК ИЛИ ПРОДОЛЖЕНИЕ ДИАЛОГА
    # Запрещено задавать одни и те же вопросы дважды!
    # =========================================================================
    if already_greeted:
        # Диалог УЖЕ идет, но кандидат написал что-то нейтральное
        if phone_known:
            reply = (
                f"{prefix}Ваши данные записаны! Координатор свяжется с вами в ближайшее время. "
                f"Если остались вопросы по объекту — напишите, с удовольствием подскажу!"
            )
        else:
            reply = (
                f"{prefix}Чтобы закрепить за вами смену и передать информацию координатору, "
                f"напишите, пожалуйста, ваш номер телефона для связи."
            )
        client.send_message(chat_id, reply)
        print(">>> SENT dialog continuation reply without repeating questions.")
        sync_candidate_to_b24_deal(chat_id, cand_data_dict)
        return True

    # ПЕРВИЧНЫЙ ОТКЛИК (Новый кандидат, пишем впервые)
    profile_parts = []
    if known_age: profile_parts.append(format_age(known_age))
    if known_cit: profile_parts.append(f"гражданство {known_cit}")

    status_line = f"Вижу вашу анкету ({', '.join(profile_parts)}).\n" if profile_parts else ""

    questions = []
    if not district_known:
        questions.append("В каком районе вы проживаете?")
    if not ready_date_known:
        questions.append("С какого числа готовы выйти на смену?")
    if not phone_known:
        questions.append("И напишите номер телефона для связи с координатором.")

    reply = (
        f"{prefix}Вакансия актуальна, как раз ведем запись на смены.\n"
        f"{status_line}"
        + " ".join(questions)
    )

    client.send_message(chat_id, reply)
    print(">>> SENT initial response to new candidate.")
    
    send_b24_notification(
        title=f"Новый отклик взят в работу: {first_name or cand_name}",
        text=f"Вакансия: {item_title}",
        chat_id=chat_id,
        phone=known_phone
    )
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
