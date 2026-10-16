import urllib.request, json, ssl, sys

sys.stdout.reconfigure(encoding='utf-8')
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE
webhook_base = 'https://b24-4qx38o.bitrix24.ru/rest/82166/lhremlfdcravw215/'

def call_b24(method, params=None):
    url = webhook_base + method
    data = json.dumps(params).encode('utf-8') if params else None
    req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'} if data else {})
    with urllib.request.urlopen(req, context=ctx) as resp:
        return json.loads(resp.read().decode('utf-8'))

res = call_b24('imopenlines.session.history.get', {'SESSION_ID': 109992})
chat_id = res.get('result', {}).get('chatId')
print('Chat ID:', chat_id)
messages = res.get('result', {}).get('message', {})
if isinstance(messages, dict):
    messages = list(messages.values())
print(f'Total messages: {len(messages)}')
for m in messages:
    print(f"[{m.get('date')}] ID {m.get('id')} (Author {m.get('author_id')}): {m.get('text')}")
