import requests
import json

WEBHOOK = "https://b24-4qx38o.bitrix24.ru/rest/82166/lhremlfdcravw215/"

def get_deal(deal_id):
    r = requests.post(WEBHOOK + 'crm.deal.get', json={'id': deal_id})
    return r.json().get('result', {})

def get_deal_activities(deal_id):
    r = requests.post(WEBHOOK + 'crm.activity.list', json={
        'filter': {'OWNER_TYPE_ID': 2, 'OWNER_ID': deal_id},
        'order': {'ID': 'DESC'}
    })
    return r.json().get('result', [])

def get_chat_history(chat_id):
    r = requests.post(WEBHOOK + 'im.dialog.messages.get', json={
        'DIALOG_ID': f'chat{chat_id}',
        'LIMIT': 10
    })
    return r.json().get('result', {})

print("--- DEAL 90108 ---")
deal = get_deal(90108)
print(f"Title: {deal.get('TITLE')}")
print(f"Comments: {deal.get('COMMENTS')}")

acts = get_deal_activities(90108)
for a in acts:
    print(f"Activity #{a['ID']} | Type: {a.get('PROVIDER_ID') or a.get('TYPE_ID')} | AssociatedId: {a.get('ASSOCIATED_ENTITY_ID')}")
    print(f"Subject: {a.get('SUBJECT')}")
    print(f"Description: {a.get('DESCRIPTION')[:200] if a.get('DESCRIPTION') else ''}")
