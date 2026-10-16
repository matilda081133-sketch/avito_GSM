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
    try:
        with urllib.request.urlopen(req, context=ctx) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        return json.loads(e.read().decode('utf-8'))
    except Exception as e:
        return {'error': str(e)}

# Test imopenlines.crm.message.add
print("Testing imopenlines.crm.message.add empty:")
res1 = call_b24('imopenlines.crm.message.add', {})
print(res1)

print("\nTesting imopenlines.crm.chat.get for deal 90092:")
res2 = call_b24('imopenlines.crm.chat.get', {'CRM_ENTITY_TYPE': 'DEAL', 'CRM_ENTITY_ID': 90092})
print(res2)

print("\nTesting imopenlines.crm.chat.user.add:")
res3 = call_b24('imopenlines.crm.chat.user.add', {'CRM_ENTITY_TYPE': 'DEAL', 'CRM_ENTITY_ID': 90092, 'USER_ID': 82166})
print(res3)
