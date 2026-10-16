import requests
import json
import sys

# Set stdout encoding to utf-8
sys.stdout.reconfigure(encoding='utf-8')

WEBHOOK = "https://b24-4qx38o.bitrix24.ru/rest/82166/lhremlfdcravw215/"

# Try to get session info or history
# Let's inspect imopenlines.session.get or imopenlines.bot.session.message
r = requests.post(WEBHOOK + 'imopenlines.session.get', json={'SESSION_ID': 109992})
print("Session 109992 info:", json.dumps(r.json(), ensure_ascii=False, indent=2))
