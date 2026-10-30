import sys
import requests
import json

sys.stdout.reconfigure(encoding='utf-8')
WEBHOOK_URL = "https://b24-4qx38o.bitrix24.ru/rest/39250/7cbs7mg1qo0vn0ov/"

# 1. Check telephony info
res = requests.get(f"{WEBHOOK_URL}telephony.lines.get").json()
print("Telephony lines:", res)

# 2. Check call activities to see PROVIDER_ID and PROVIDER_TYPE_ID
res_act = requests.get(f"{WEBHOOK_URL}crm.activity.list", params={"filter[TYPE_ID]": 2, "order[ID]": "DESC", "limit": 5}).json()
print("\nRecent call activities:")
for a in res_act.get("result", []):
    print(f"ID {a.get('ID')}: {a.get('SUBJECT')} | Provider: {a.get('PROVIDER_ID')} | Type: {a.get('PROVIDER_TYPE_ID')} | Direction: {a.get('DIRECTION')} | Author: {a.get('AUTHOR_ID')}")
