import urllib.request, json, ssl, sys

sys.stdout.reconfigure(encoding='utf-8')
ctx = ssl.create_default_context()

USER_ID = 358201685
TOKEN = "kYu61AdIRBqXRXxpoSmcFgBOhKRRrHGdWpJhqpr3"

# List chats with unread messages
url_chats = f"https://api.avito.ru/messenger/v2/accounts/{USER_ID}/chats?unread_only=true"
req = urllib.request.Request(url_chats, headers={
    "Authorization": f"Bearer {TOKEN}"
})

try:
    with urllib.request.urlopen(req, context=ctx) as resp:
        res = json.loads(resp.read().decode("utf-8"))
        chats = res.get("chats", [])
        print(f"Total unread chats: {len(chats)}")
        for c in chats:
            print(f"Chat {c.get('id')} | User: {c.get('users', [{}])[0].get('name')} | Last msg: {c.get('last_message', {}).get('content', {}).get('text')[:80]}")
except Exception as e:
    print("Error listing chats:", e)
