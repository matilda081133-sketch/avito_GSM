# -*- coding: utf-8 -*-
import os
import time
import requests
import json
from config import AVITO_CLIENT_ID, AVITO_CLIENT_SECRET, AVITO_USER_ID

class AvitoClient:
    def __init__(self, client_id, client_secret, user_id):
        self.client_id = client_id
        self.client_secret = client_secret
        self.user_id = user_id
        self.access_token = None
        self.token_expires_at = 0
        self.session = requests.Session()
        self.cache_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".avito_token_cache.json")
        self._load_cached_token()

    def _load_cached_token(self):
        try:
            if os.path.exists(self.cache_file):
                with open(self.cache_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if data.get("access_token") and time.time() < data.get("expires_at", 0) - 120:
                        self.access_token = data["access_token"]
                        self.token_expires_at = data["expires_at"]
        except Exception:
            pass

    def _save_cached_token(self):
        try:
            with open(self.cache_file, "w", encoding="utf-8") as f:
                json.dump({
                    "access_token": self.access_token,
                    "expires_at": self.token_expires_at
                }, f)
        except Exception:
            pass

    def _request_with_retry(self, method: str, url: str, **kwargs) -> requests.Response:
        max_retries = 3
        for attempt in range(1, max_retries + 1):
            try:
                resp = self.session.request(method, url, **kwargs)
                return resp
            except (requests.exceptions.SSLError, requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
                # Re-create session on socket/ssl error to clear poisoned socket pool
                self.session = requests.Session()
                if attempt == max_retries:
                    raise
                time.sleep(attempt * 1.5)
            except Exception:
                if attempt == max_retries:
                    raise
                time.sleep(attempt * 1.0)

    def get_token(self):
        if self.access_token and time.time() < self.token_expires_at - 60:
            return self.access_token

        url = "https://api.avito.ru/token"
        data = {
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret
        }
        for attempt in range(1, 4):
            try:
                resp = self._request_with_retry("POST", url, data=data, timeout=12)
                res = resp.json()
                if "access_token" in res:
                    self.access_token = res["access_token"]
                    self.token_expires_at = time.time() + res.get("expires_in", 86400)
                    self._save_cached_token()
                    return self.access_token
                else:
                    print(f"[AvitoClient] Token refresh response warning: {res}")
            except Exception as e:
                print(f"[AvitoClient] Token refresh attempt {attempt} error: {e}")
            time.sleep(2)
        return self.access_token or ""

    def send_message(self, chat_id: str, text: str) -> dict:
        token = self.get_token()
        url = f"https://api.avito.ru/messenger/v1/accounts/{self.user_id}/chats/{chat_id}/messages"
        payload = {
            "message": {
                "text": text
            },
            "type": "text"
        }
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        resp = self._request_with_retry("POST", url, json=payload, headers=headers, timeout=12)
        if resp.status_code not in (200, 201):
            try:
                err_data = resp.json()
            except Exception:
                err_data = resp.text
            raise RuntimeError(f"Avito send_message HTTP {resp.status_code}: {err_data}")
        try:
            return resp.json()
        except Exception:
            return {"status": "ok"}

    def get_chat_messages(self, chat_id: str, limit: int = 25) -> list:
        token = self.get_token()
        url = f"https://api.avito.ru/messenger/v3/accounts/{self.user_id}/chats/{chat_id}/messages/?limit={limit}"
        headers = {
            "Authorization": f"Bearer {token}"
        }
        resp = self._request_with_retry("GET", url, headers=headers, timeout=12)
        return resp.json().get("messages", [])

    def get_unread_chats(self, limit: int = 50) -> list:
        token = self.get_token()
        url = f"https://api.avito.ru/messenger/v2/accounts/{self.user_id}/chats?unread_only=true&limit={limit}"
        headers = {
            "Authorization": f"Bearer {token}"
        }
        resp = self._request_with_retry("GET", url, headers=headers, timeout=12)
        return resp.json().get("chats", [])

    def get_recent_chats(self, limit: int = 50) -> list:
        token = self.get_token()
        url = f"https://api.avito.ru/messenger/v2/accounts/{self.user_id}/chats?limit={limit}"
        headers = {
            "Authorization": f"Bearer {token}"
        }
        resp = self._request_with_retry("GET", url, headers=headers, timeout=12)
        return resp.json().get("chats", [])

    def mark_chat_as_read(self, chat_id: str) -> bool:
        try:
            token = self.get_token()
            url = f"https://api.avito.ru/messenger/v1/accounts/{self.user_id}/chats/{chat_id}/read"
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            }
            resp = self._request_with_retry("POST", url, json={}, headers=headers, timeout=6)
            return resp.status_code == 200
        except Exception:
            return False

    _cached_chat_titles = {}
    _cached_item_details = {}
    _cache_file_items = os.path.join(os.path.dirname(__file__), "avito_items_cache.json")

    def _load_items_cache(self) -> dict:
        if not self._cached_item_details and os.path.exists(self._cache_file_items):
            try:
                with open(self._cache_file_items, "r", encoding="utf-8") as f:
                    self._cached_item_details = json.load(f)
            except Exception:
                self._cached_item_details = {}
        return self._cached_item_details

    def _save_items_cache(self):
        try:
            with open(self._cache_file_items, "w", encoding="utf-8") as f:
                json.dump(self._cached_item_details, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def get_item_details(self, item_id: str) -> dict:
        """
        Получает и кэширует полные данные объявления Авито по item_id:
        - autoload_item_id (Код вакансии из автозагрузки, например ALFA_NEW_0040)
        - description (Полный текст описания вакансии)
        - address (Адрес из объявления)
        """
        if not item_id:
            return {}
        item_id = str(item_id).strip()
        cache = self._load_items_cache()
        if item_id in cache and cache[item_id].get("description"):
            return cache[item_id]

        info = cache.get(item_id, {"autoload_item_id": "", "description": "", "address": "", "url": ""})
        try:
            token = self.get_token()
            headers = {"Authorization": f"Bearer {token}"}
            # 1. Получаем код вакансии (autoload_item_id) через Core API
            r_core = self._request_with_retry(
                "GET",
                f"https://api.avito.ru/core/v1/accounts/{self.user_id}/items/{item_id}/",
                headers=headers,
                timeout=8
            )
            if r_core.status_code == 200:
                c_data = r_core.json()
                info["autoload_item_id"] = c_data.get("autoload_item_id") or info.get("autoload_item_id", "")
                info["url"] = c_data.get("url") or info.get("url", "")

            # 2. Получаем полное описание и адрес вакансии через Job API v2
            r_job = self._request_with_retry(
                "GET",
                f"https://api.avito.ru/job/v2/vacancies/{item_id}",
                headers=headers,
                timeout=8
            )
            if r_job.status_code == 200:
                j_data = r_job.json()
                info["description"] = j_data.get("description") or info.get("description", "")
                addr = j_data.get("addressDetails", {}).get("address") or ""
                info["address"] = addr or info.get("address", "")
                if not info.get("autoload_item_id") and j_data.get("custom_employer_name"):
                    info["custom_employer_name"] = j_data.get("custom_employer_name")

            cache[item_id] = info
            self._save_items_cache()
        except Exception as e:
            print(f"[AvitoClient] get_item_details({item_id}) error: {e}")

        return info

    def get_chat_context_title(self, chat_id: str) -> str:
        """Получает точное название объявления Авито, на которое пришел отклик (из контекста чата)."""
        if not chat_id:
            return ""
        if chat_id in self._cached_chat_titles:
            return self._cached_chat_titles[chat_id]
        try:
            token = self.get_token()
            url = f"https://api.avito.ru/messenger/v2/accounts/{self.user_id}/chats/{chat_id}"
            headers = {"Authorization": f"Bearer {token}"}
            resp = self._request_with_retry("GET", url, headers=headers, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                title = data.get("context", {}).get("value", {}).get("title", "").strip()
                if title:
                    self._cached_chat_titles[chat_id] = title
                    return title
        except Exception as e:
            pass
        return ""

    _cached_negotiations_phones = None
    _last_negotiations_fetch = 0
    _cache_file_neg = os.path.join(os.path.dirname(__file__), "avito_negotiations_phones.json")

    def _load_negotiations_cache(self) -> dict:
        if self._cached_negotiations_phones is None:
            self._cached_negotiations_phones = {}
            if os.path.exists(self._cache_file_neg):
                try:
                    with open(self._cache_file_neg, "r", encoding="utf-8") as f:
                        self._cached_negotiations_phones = json.load(f)
                except Exception:
                    self._cached_negotiations_phones = {}
        return self._cached_negotiations_phones

    def _save_negotiations_cache(self):
        try:
            with open(self._cache_file_neg, "w", encoding="utf-8") as f:
                json.dump(self._cached_negotiations_phones, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def get_negotiations_phone(self, chat_id: str) -> str:
        """
        Ищет номер телефона кандидата в разделе «Отклики» (Avito Job Negotiations API).
        Работает для откликов с переданным резюме или когда рекрутер нажал кнопку «Посмотреть телефон».
        Кэширует данные с учетом лимита Авито (не чаще 1 запроса в 65 секунд).
        """
        cache = self._load_negotiations_cache()
        if chat_id in cache:
            return cache[chat_id]

        now = time.time()
        if now - self._last_negotiations_fetch >= 65:
            self._last_negotiations_fetch = now
            try:
                token = self.get_token()
                headers = {"Authorization": f"Bearer {token}"}
                resp = requests.get("https://api.avito.ru/job/v1/negotiations", headers=headers, timeout=12)
                if resp.status_code == 200:
                    data = resp.json()
                    for item in data.get("result", []):
                        cid = item.get("chat_id")
                        raw_p = item.get("phone")
                        if cid and raw_p:
                            clean_p = re.sub(r'[^\d+]', '', str(raw_p))
                            if len(clean_p) >= 10:
                                p = '+7' + clean_p[-10:]
                                cache[cid] = p
                    self._save_negotiations_cache()
                elif resp.status_code == 429:
                    retry_sec = int(resp.headers.get("x-ratelimit-retry-after") or 60)
                    self._last_negotiations_fetch = now + retry_sec - 60
            except Exception:
                pass

        return cache.get(chat_id, "")
