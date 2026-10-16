import urllib.request, json, ssl, sys

sys.stdout.reconfigure(encoding='utf-8')
ctx = ssl.create_default_context()

USER_ID = 358201685
CHAT_ID = "u2i-YyTiqh7FyZ6b0qlBZBmLyA"
TOKEN = "kYu61AdIRBqXRXxpoSmcFgBOhKRRrHGdWpJhqpr3"

# 1. Get chat messages
url_get = f"https://api.avito.ru/messenger/v3/accounts/{USER_ID}/chats/{CHAT_ID}/messages/"
req_get = urllib.request.Request(url_get, headers={
    "Authorization": f"Bearer {TOKEN}"
})
try:
    with urllib.request.urlopen(req_get, context=ctx) as resp:
        res = json.loads(resp.read().decode("utf-8"))
        print(f"Messages count in chat {CHAT_ID}: {len(res.get('messages', []))}")
        for m in res.get('messages', [])[:5]:
            print(f"[{m.get('created')}] {m.get('author_id')}: {m.get('content', {}).get('text')}")
except urllib.error.HTTPError as e:
    print("HTTP Error get msgs:", e.code, e.read().decode("utf-8"))
