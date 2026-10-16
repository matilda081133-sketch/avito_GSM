# -*- coding: utf-8 -*-
"""
VACANCY CRITERIA & CANDIDATE QUALIFICATION MODULE
Модуль сверки данных кандидата со строгими требованиями каждого объекта GSM Logistics.
Запрещено обнадеживать («да конечно вы подходите»).
"""
import re

VACANCY_CRITERIA = {
    "SMART_BALASHIKHA": {
        "name": "Склад зоотоваров (Балашиха / Салтыковка)",
        "keywords": ["зоо", "смарт", "балаших", "салтыков", "кучин"],
        "min_age": 18,
        "max_age": 55,
        "allowed_citizenship": ["рф", "рб", "еаэс", "беларусь", "россия", "казахстан", "киргизия", "кыргызстан", "армения"],
        "requires_patent_for_cis": True,
        "region_patent": "Московская область (или Москва с областью)",
        "requires_medbook": False,
        "physical_load": "средняя (на ногах, фасовка/упаковка)",
        "schedule": "Дневные смены с 08:00 до 20:00, ночные — с 20:00 до 08:00. Возможна подработка 3–4 дня в неделю или постоянный график.",
        "rate": "от 3 600 до 4 200 ₽ за смену (выплаты еженедельно или ежедневно по согласованию)"
    },
    "BEAUTY_MOSCOW": {
        "name": "Склад косметики (Москва)",
        "keywords": ["косметик", "бьюти", "дмитровск"],
        "min_age": 18,
        "max_age": 50,
        "allowed_citizenship": ["рф", "рб", "еаэс", "беларусь", "россия", "казахстан", "киргизия", "кыргызстан", "армения"],
        "requires_patent_for_cis": True,
        "region_patent": "Москва",
        "requires_medbook": False,
        "physical_load": "легкая (стикеровка, упаковка косметики)",
        "schedule": "Дневные смены 08:00–20:00. Графики 2/2, 5/2 или подработка.",
        "rate": "от 3 500 до 4 000 ₽ за смену"
    },
    "ABI_VLADIMIR": {
        "name": "Мясокомбинат АБИ (Владимир / Вахта)",
        "keywords": ["аби", "владимир", "мясо", "колбас", "вязанк", "стародвор"],
        "min_age": 18,
        "max_age": 50,
        "allowed_citizenship": ["рф", "рб", "еаэс", "беларусь", "россия"],
        "requires_patent_for_cis": False,
        "requires_medbook": True,
        "physical_load": "пищевое производство (прохладные цеха, требуется медкнижка и проверка СБ)",
        "schedule": "Вахта от 30 смен. Смены по 11 часов. Бесплатное 3-разовое горячее питание и проживание.",
        "rate": "от 3 900 до 4 400 ₽ за смену чистыми на руки"
    },
    "TEPOFOL_KASHIRA": {
        "name": "Завод Тепофол (Кашира / Вахта)",
        "keywords": ["тепофол", "кашир", "утеплит"],
        "min_age": 18,
        "max_age": 55,
        "allowed_citizenship": ["рф", "рб", "еаэс", "беларусь", "россия"],
        "requires_patent_for_cis": False,
        "requires_medbook": False,
        "physical_load": "упаковка рулонного утеплителя",
        "schedule": "Вахта 18 или 30 смен. Бесплатное проживание в квартирах.",
        "rate": "от 3 800 до 4 200 ₽ за смену"
    },
    "FARM_OPALIKHA": {
        "name": "Фасовка чая / Фарма (Красногорск / Опалиха)",
        "keywords": ["фарма", "опалих", "красногорск", "аптеч", "чай"],
        "min_age": 18,
        "max_age": 55,
        "allowed_citizenship": ["рф", "рб", "еаэс", "россия", "беларусь"],
        "requires_patent_for_cis": True,
        "region_patent": "Московская область",
        "requires_medbook": False,
        "physical_load": "фасовка и укладка чая/аптечной продукции",
        "schedule": "Смены 08:00–20:00. Выплаты на следующий день.",
        "rate": "от 3 800 до 4 500 ₽ за смену (расчет ежедневно)"
    },
    "LOADER_HEAVY": {
        "name": "Грузчик / Подсобный рабочий (Тяжелые склады / производство)",
        "keywords": ["грузчик", "мебель", "подсобный", "тяжел"],
        "min_age": 18,
        "max_age": 50,
        "allowed_citizenship": ["рф", "рб", "еаэс", "россия", "беларусь"],
        "requires_patent_for_cis": True,
        "region_patent": "Москва / МО",
        "requires_medbook": False,
        "physical_load": "высокая (погрузка, перемещение грузов)",
        "schedule": "Смены по 11–12 часов.",
        "rate": "от 3 800 до 4 500 ₽ за смену"
    },
    "GENERAL_VAHTA": {
        "name": "Вахта с проживанием",
        "keywords": ["вахт"],
        "min_age": 18,
        "max_age": 55,
        "allowed_citizenship": ["рф", "рб", "еаэс", "россия", "беларусь"],
        "requires_patent_for_cis": False,
        "requires_medbook": False,
        "physical_load": "производственные и складские операции",
        "schedule": "Вахта от 20–30 смен. Бесплатное проживание.",
        "rate": "от 3 800 до 4 400 ₽ за смену"
    },
    "GENERAL_LOCAL": {
        "name": "Склад / производство (местные смены)",
        "keywords": [],
        "min_age": 18,
        "max_age": 55,
        "allowed_citizenship": ["рф", "рб", "еаэс", "россия", "беларусь"],
        "requires_patent_for_cis": True,
        "region_patent": "Москва / МО",
        "requires_medbook": False,
        "physical_load": "комплектовка, фасовка, упаковка",
        "schedule": "Дневные смены 08:00–20:00, ночные 20:00–08:00.",
        "rate": "от 3 600 до 4 200 ₽ за смену"
    }
}

def detect_vacancy_profile(title: str) -> dict:
    t = (title or "").lower()
    for key, vac in VACANCY_CRITERIA.items():
        if vac["keywords"] and any(k in t for k in vac["keywords"]):
            return vac
    if "вахт" in t:
        return VACANCY_CRITERIA["GENERAL_VAHTA"]
    return VACANCY_CRITERIA["GENERAL_LOCAL"]

def evaluate_candidate_fit(vacancy_prof: dict, age_str: str, cit_str: str) -> dict:
    """
    Сверяет возраст и гражданство кандидата с требованиями вакансии.
    Возвращает статус:
    - 'UNDERAGE': моложе 18 лет (строгий стоп-фактор)
    - 'OVERAGE': старше допустимого максимума объекта
    - 'REQUIRES_PATENT': требуется патент СНГ
    - 'NEEDS_VERIFICATION': в рамках нормы, но требует финальной проверки координатором
    НИКОГДА не говорит «вы подходите».
    """
    res = {
        "status": "NEEDS_VERIFICATION",
        "age_note": "",
        "cit_note": "",
        "rule_summary": f"Требования по вакансии: возраст {vacancy_prof['min_age']}–{vacancy_prof['max_age']} лет."
    }

    age_val = None
    if age_str:
        m = re.search(r'\d+', str(age_str))
        if m:
            age_val = int(m.group(0))

    if age_val is not None:
        if age_val < vacancy_prof["min_age"]:
            res["status"] = "UNDERAGE"
            res["age_note"] = f"К сожалению, по правилам объектов трудоустройство строго с {vacancy_prof['min_age']} лет."
            return res
        elif age_val > vacancy_prof["max_age"]:
            res["status"] = "OVERAGE"
            res["age_note"] = (
                f"По правилам данного объекта рассматриваются кандидаты до {vacancy_prof['max_age']} лет "
                f"в связи с физическими нагрузками. Допуск или альтернативные варианты согласовываются координатором."
            )
        else:
            res["age_note"] = f"Возрастные рамки на объекте — от {vacancy_prof['min_age']} до {vacancy_prof['max_age']} лет."

    cit_lower = (cit_str or "").lower().strip()
    if cit_lower:
        is_direct = any(c in cit_lower for c in ["рф", "росси", "рб", "беларус"])
        is_eaeu = any(c in cit_lower for c in ["казах", "армен", "кырг", "киргиз", "еаэс"])
        if is_direct:
            res["cit_note"] = "Гражданство подходит под прямое оформление."
        elif is_eaeu:
            res["cit_note"] = "Для граждан ЕАЭС необходимы паспорт, миграционная карта, регистрация, СНИЛС и ИНН."
        else:
            res["status"] = "REQUIRES_PATENT"
            res["cit_note"] = (
                f"Для иностранных граждан обязателен действующий трудовой патент в регионе "
                f"«{vacancy_prof.get('region_patent', 'Москва/МО')}» и оплаченные чеки."
            )

    return res
