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
                os.environ.setdefault(k.strip(), v.strip())

# Bitrix24 Webhook URL
B24_WEBHOOK_URL = os.getenv("B24_WEBHOOK_URL", "")

# Wappi API Settings
WAPPI_TOKEN = os.getenv("WAPPI_TOKEN", "")
WAPPI_PROFILE_ID = os.getenv("WAPPI_PROFILE_ID", "")

# UIS Telephony Numbers (заполняются только при наличии подтвержденного официального номера 8-800 / UIS)
UIS_HOTLINE_PHONE = os.getenv("UIS_HOTLINE_PHONE", "")

# Avito Direct API (читаются безопасно из переменных окружения на сервере)
AVITO_CLIENT_ID = os.getenv("AVITO_CLIENT_ID", "")
AVITO_CLIENT_SECRET = os.getenv("AVITO_CLIENT_SECRET", "")
AVITO_USER_ID = int(os.getenv("AVITO_USER_ID", "358201685"))

# Server Settings
PORT = int(os.getenv("PORT", 8080))
HOST = os.getenv("HOST", "0.0.0.0")
