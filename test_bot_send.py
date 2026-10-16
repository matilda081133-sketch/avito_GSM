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

# Test imopenlines.bot.session.message.send with BOT_ID
res1 = call_b24('imopenlines.bot.session.message.send', {
    'BOT_ID': 68616,
    'CHAT_ID': 100312,
    'MESSAGE': 'Здравствуйте, Клавдия! Склад находится в Балашихе (микрорайон Салтыковка / Кучино, ул. Новомилетская). От станции Салтыковская или Кучино всего 5-10 минут на транспорте (МЦД-4 либо автобусы 142, 100).'
})
print("Result with BOT_ID 68616:", res1)

res2 = call_b24('imbot.message.add', {
    'BOT_ID': 68616,
    'DIALOG_ID': 'chat100312',
    'MESSAGE': 'Здравствуйте, Клавдия!'
})
print("Result imbot.message.add 68616:", res2)
