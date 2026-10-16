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

res = call_b24('user.get', {'ACTIVE': True})
users = res.get('result', [])
print(f'Active users total: {len(users)}')
for u in users:
    name = f"{u.get('NAME')} {u.get('LAST_NAME')}"
    pos = u.get('WORK_POSITION') or 'Без должности'
    dept = u.get('UF_DEPARTMENT')
    email = u.get('EMAIL')
    print(f"ID {u.get('ID')}: {name} | {pos} | {email}")
