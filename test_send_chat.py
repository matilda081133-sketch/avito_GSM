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

# Try to add current user (82166) to chat 100312
add_res = call_b24('im.chat.user.add', {'CHAT_ID': 100312, 'USERS': [82166]})
print("im.chat.user.add:", add_res)

# Or imopenlines.session.operator.transfer
transfer_res = call_b24('imopenlines.session.operator.transfer', {'SESSION_ID': 109970, 'OPERATOR_ID': 82166})
print("imopenlines.session.operator.transfer:", transfer_res)

# Let's test im.message.add again
msg_res = call_b24('im.message.add', {'CHAT_ID': 100312, 'MESSAGE': 'Тест связи'})
print("im.message.add:", msg_res)
