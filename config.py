# -*- coding: utf-8 -*-
import os

# Автозагрузка .env если файл существует локально
env_path = os.path.join(os.path.dirname(__file__), ".env")
if os.path.exists(env_path):
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

# Bitrix24 Webhook URL
B24_WEBHOOK_URL = os.getenv("B24_WEBHOOK_URL", "")

# Wappi API Settings
WAPPI_TOKEN = os.getenv("WAPPI_TOKEN", "")
WAPPI_PROFILE_ID = os.getenv("WAPPI_PROFILE_ID", "")

# UIS Telephony Numbers (заполняются только при наличии подтвержденного официального номера 8-800 / UIS)
UIS_HOTLINE_PHONE = os.getenv("UIS_HOTLINE_PHONE", "")

# Avito Direct API (кабинет по умолчанию)
AVITO_CLIENT_ID = os.getenv("AVITO_CLIENT_ID", "oawHPlf75CBY-Hm4Rqpl")
AVITO_CLIENT_SECRET = os.getenv("AVITO_CLIENT_SECRET", "vPKPG4c6xEi34NDRQL7OU7mxPYaIcc_rXwMQTiiA")
AVITO_USER_ID = int(os.getenv("AVITO_USER_ID", "358201685"))

# МУЛЬТИ-КАБИНЕТНАЯ СИСТЕМА АВИТО (Все активные кабинеты компании)
AVITO_CABINETS = [
    {
        "id": 358201685,
        "name": "Прямой работодатель",
        "client_id": os.getenv("AVITO_CLIENT_ID", "oawHPlf75CBY-Hm4Rqpl"),
        "client_secret": os.getenv("AVITO_CLIENT_SECRET", "vPKPG4c6xEi34NDRQL7OU7mxPYaIcc_rXwMQTiiA"),
    },
    {
        "id": int(os.getenv("AVITO_CABINET_2_USER_ID", "358202810")),
        "name": os.getenv("AVITO_CABINET_2_NAME", "Работа без границ!"),
        "client_id": os.getenv("AVITO_CABINET_2_CLIENT_ID", "Z32uhj720CIlmoMai4uR"),
        "client_secret": os.getenv("AVITO_CABINET_2_CLIENT_SECRET", "6hPPbeGC3XzfT6JNLSdUNeAY9kaKn4Rp8FMjr2Md"),
    },
    {
        "id": int(os.getenv("AVITO_CABINET_3_USER_ID", "438887068")),
        "name": os.getenv("AVITO_CABINET_3_NAME", "Хороший выбор"),
        "client_id": os.getenv("AVITO_CABINET_3_CLIENT_ID", "eIXr4FQgBJRbcw9cvKdK"),
        "client_secret": os.getenv("AVITO_CABINET_3_CLIENT_SECRET", "BL0jAD9Fwe5D22ToWAKHoneUQ_bIkhJr6wf_sOOu"),
    },
    {
        "id": int(os.getenv("AVITO_CABINET_4_USER_ID", "438376151")),
        "name": os.getenv("AVITO_CABINET_4_NAME", "Работа для Вас"),
        "client_id": os.getenv("AVITO_CABINET_4_CLIENT_ID", "67Js9dIM_z8fV4vRcoOI"),
        "client_secret": os.getenv("AVITO_CABINET_4_CLIENT_SECRET", "cfVTA_lUwWzhCEWqkaQ72aKsaS1OMWWfNn7PoQnq"),
    }
]

# Server Settings
PORT = int(os.getenv("PORT", 8080))
HOST = os.getenv("HOST", "0.0.0.0")
