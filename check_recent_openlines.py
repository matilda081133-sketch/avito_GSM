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

# Let's inspect recent activities with type IMOPENLINES_SESSION
res = call_b24('crm.activity.list', {
    'filter': {'PROVIDER_ID': 'IMOPENLINES_SESSION'},
    'order': {'ID': 'DESC'},
    'limit': 10
})

print(f"Recent openline activities: {len(res.get('result', []))}")
for a in res.get('result', []):
    sess_id = a.get('ASSOCIATED_ENTITY_ID')
    deal_id = a.get('OWNER_ID')
    print(f"\n--- Deal #{deal_id} | Session #{sess_id} | Subject: {a.get('SUBJECT')}")
    # Get last message of session
    try:
        hist = call_b24('imopenlines.session.history.get', {'SESSION_ID': sess_id})
        msgs = hist.get('result', {}).get('message', {})
        if isinstance(msgs, dict):
            msgs = list(msgs.values())
        if msgs:
            last_m = msgs[0] # first in list is latest
            print(f"Last msg [{last_m.get('date')}]: {last_m.get('text')}")
    except Exception as e:
        print(f"Error fetching history: {e}")
