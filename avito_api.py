import urllib.request, urllib.parse, json, ssl, time

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

def safe_urlopen(req, retries=3, delay=1.0):
    last_err = None
    for attempt in range(retries):
        try:
            return urllib.request.urlopen(req, context=ctx, timeout=15)
        except Exception as e:
            last_err = e
            time.sleep(delay * (attempt + 1))
    raise last_err

class AvitoClient:
    def __init__(self, client_id: str, client_secret: str, user_id: int = 358201685):
        self.client_id = client_id.strip()
        self.client_secret = client_secret.strip()
        self.user_id = user_id
        self.access_token = None
        self.token_expires_at = 0

    def get_token(self):
        if self.access_token and time.time() < self.token_expires_at - 60:
            return self.access_token

        url = "https://api.avito.ru/token"
        data = urllib.parse.urlencode({
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret
        }).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
        })
        with safe_urlopen(req) as resp:
            res = json.loads(resp.read().decode("utf-8"))
            self.access_token = res["access_token"]
            self.token_expires_at = time.time() + res.get("expires_in", 86400)
            return self.access_token

    def send_message(self, chat_id: str, text: str) -> dict:
        token = self.get_token()
        url = f"https://api.avito.ru/messenger/v1/accounts/{self.user_id}/chats/{chat_id}/messages"
        payload = json.dumps({
            "message": {
                "text": text
            },
            "type": "text"
        }).encode("utf-8")

        req = urllib.request.Request(url, data=payload, headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
        })
        with safe_urlopen(req) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def get_chat_messages(self, chat_id: str, limit: int = 25) -> list:
        token = self.get_token()
        url = f"https://api.avito.ru/messenger/v3/accounts/{self.user_id}/chats/{chat_id}/messages/?limit={limit}"
        req = urllib.request.Request(url, headers={
            "Authorization": f"Bearer {token}",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
        })
        with safe_urlopen(req) as resp:
            res = json.loads(resp.read().decode("utf-8"))
            return res.get("messages", [])

    def get_unread_chats(self, limit: int = 50) -> list:
        token = self.get_token()
        url = f"https://api.avito.ru/messenger/v2/accounts/{self.user_id}/chats?unread_only=true&limit={limit}"
        req = urllib.request.Request(url, headers={
            "Authorization": f"Bearer {token}",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
        })
        with safe_urlopen(req) as resp:
            res = json.loads(resp.read().decode("utf-8"))
            return res.get("chats", [])

    def get_recent_chats(self, limit: int = 50) -> list:
        token = self.get_token()
        url = f"https://api.avito.ru/messenger/v2/accounts/{self.user_id}/chats?limit={limit}"
        req = urllib.request.Request(url, headers={
            "Authorization": f"Bearer {token}",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
        })
        with safe_urlopen(req) as resp:
            res = json.loads(resp.read().decode("utf-8"))
            return res.get("chats", [])
