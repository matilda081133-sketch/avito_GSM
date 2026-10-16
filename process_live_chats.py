import urllib.request, json, ssl, time, sys, re
from avito_api import AvitoClient
from ai_engine import AIRecruiterEngine, extract_phone, get_uis_phone_for_vacancy
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
            'PRIORITY': 2 # High priority
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
    last_msg = msgs[-1]
    
    # If the last message was sent by US, nothing to reply to right now
    if last_msg.get('author_id') == AVITO_USER_ID:
        return False

    # СТРОГИЙ ФИЛЬТР СВЕЖЕСТИ: не отвечать на старые отклики (старше 24 часов)
    msg_timestamp = last_msg.get('created', 0)
    hours_ago = (time.time() - msg_timestamp) / 3600.0
    if hours_ago > 24.0:
        return False

    last_text = last_msg.get('content', {}).get('text', '')
    if not last_text or "не поддерживается" in last_text.lower():
        return False

    print(f"\n=======================================================")
    print(f"Chat: {chat_id} | Candidate: {cand_name} | Ad: {item_title}")
    print(f"Last text: {last_text}")

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

    # 1. Если кандидат прислал номер телефона
    current_phone = extract_phone(last_text)
    if current_phone:
        reply = (
            "Спасибо, контакты зафиксировала! Координатор свяжется с вами для согласования всех деталей и даты выхода. "
            "Если появятся вопросы — пишите прямо сюда в чат, мы на связи!"
        )
        client.send_message(chat_id, reply)
        print(">>> SENT phone confirmation acknowledgment.")
        
        # Отправляем видное уведомление в Битрикс24 менеджерам!
        send_b24_notification(
            title=f"КАНДИДАТ ОСТАВИЛ ТЕЛЕФОН: {cand_name or known_fio}",
            text=f"Вакансия: {item_title}",
            chat_id=chat_id,
            phone=current_phone
        )
        
        # СТАВИМ ЗАДАЧУ МЕНЕДЖЕРУ НА ЗВОНОК С ВЫСОКИМ ПРИОРИТЕТОМ
        create_b24_call_task(
            candidate_name=cand_name or known_fio,
            vacancy=item_title,
            phone=current_phone,
            details=f"Кандидат оставил телефон в чате: {current_phone}\nВозраст: {known_age or 'уточняется'}\nГражданство: {known_cit or 'РФ'}",
            chat_id=chat_id
        )
        return True

    # 2. Если спрашивают как связаться / телефон
    t_lower = last_text.lower()
    if any(w in t_lower for w in ["связа", "позвон", "номер", "телефон", "сохран", "контакт"]):
        direct_phone = get_uis_phone_for_vacancy(item_title)
        reply = (
            f"Вы можете позвонить нам напрямую по номеру {direct_phone} (звонок бесплатный). "
            f"Это прямой номер координатора объекта!\n\n"
            f"Либо напишите, в какое время вам удобно принять звонок, и мы вас наберем!"
        )
        client.send_message(chat_id, reply)
        print(">>> SENT direct UIS contact number.")
        send_b24_notification(
            title=f"Кандидат запросил контакты: {cand_name}",
            text=f"Выдан номер {direct_phone} по вакансии {item_title}",
            chat_id=chat_id
        )
        return True

    # 3. Вопросы про локацию
    if any(w in t_lower for w in ["где", "находит", "локац", "адрес", "добира", "салтыков", "кучин"]):
        if any(w in item_title.lower() for w in ["зоо", "смарт", "балаших"]):
            reply = (
                "Склад зоотоваров находится в Балашихе (микрорайон Салтыковка, Носовихинское шоссе). "
                "От станций «Салтыковская» или «Кучино» добираться 5–10 минут на транспорте (МЦД-4 либо автобусы 142, 100).\n\n"
                "Подскажите, в каком районе вы проживаете и когда вам удобно выйти на первую смену?"
            )
            client.send_message(chat_id, reply)
            print(">>> SENT location answer.")
            return True

    # 4. Формирование ответа с уважением к известным данным анкеты
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
    
    def format_age(a):
        try:
            n = int(a)
            if 11 <= n % 100 <= 14: return f"{n} лет"
            elif n % 10 == 1: return f"{n} год"
            elif 2 <= n % 10 <= 4: return f"{n} года"
            else: return f"{n} лет"
        except:
            return f"{a} лет"

    missing_questions = []
    
    # ЕСЛИ ВОЗРАСТ И ГРАЖДАНСТВО УКАЗАНЫ — НЕ ПЕРЕСПРАШИВАТЬ!
    if known_age and known_cit:
        status_line = f"Вижу вашу анкету ({format_age(known_age)}, {known_cit}) — данные актуальны?\n"
    elif known_age:
        status_line = f"По возрасту ({format_age(known_age)}) всё отлично подходит!\n"
    else:
        status_line = ""
        missing_questions.append("Ваш возраст и гражданство")

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
    print(">>> SENT tailored response (respecting known profile).")
    
    send_b24_notification(
        title=f"Отклик взят в работу: {first_name or cand_name}",
        text=f"Вакансия: {item_title}. Заданы уточняющие вопросы по выходу.",
        chat_id=chat_id,
        phone=known_phone
    )
    return True

if __name__ == '__main__':
    print("Fetching unread chats from Avito...")
    unread_chats = client.get_unread_chats(limit=30)
    print(f"Total unread chats fetched: {len(unread_chats)}")
    
    sent_count = 0
    for c in unread_chats:
        try:
            if process_single_chat(c):
                sent_count += 1
                time.sleep(1.5)
                if sent_count >= 5:
                    break
        except Exception as e:
            print("Error processing chat:", e)

    print(f"\nDone batch! Sent {sent_count} live answers.")
