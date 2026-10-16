import requests
import json
import time

WEBHOOK = "https://b24-4qx38o.bitrix24.ru/rest/82166/lhremlfdcravw215/"

def get_recent_deals():
    r = requests.post(WEBHOOK + 'crm.deal.list', json={
        'order': {'ID': 'DESC'},
        'select': ['ID', 'TITLE', 'STAGE_ID', 'COMMENTS', 'DATE_CREATE', 'UF_CRM_1775470003043', 'UF_CRM_1768816011673', 'UF_CRM_1768816356722'],
        'limit': 15
    })
    return r.json().get('result', [])

def get_openline_sessions():
    # List active openline sessions or recent dialogs
    r = requests.post(WEBHOOK + 'imopenlines.session.get', json={})
    print("imopenlines.session.get:", r.json())

def check_deal_activities(deal_id):
    r = requests.post(WEBHOOK + 'crm.activity.list', json={
        'filter': {'OWNER_TYPE_ID': 2, 'OWNER_ID': deal_id},
        'order': {'ID': 'DESC'},
        'limit': 5
    })
    return r.json().get('result', [])

if __name__ == '__main__':
    deals = get_recent_deals()
    print(f"Found {len(deals)} recent deals:")
    for d in deals:
        print(f"Deal #{d['ID']}: {d.get('TITLE')} | Stage: {d.get('STAGE_ID')} | Created: {d.get('DATE_CREATE')}")
        acts = check_deal_activities(d['ID'])
        for a in acts:
            print(f"   Act #{a['ID']} (Type: {a.get('PROVIDER_ID') or a.get('TYPE_ID')}): {a.get('SUBJECT')[:60] if a.get('SUBJECT') else 'No subj'} | Descr: {(a.get('DESCRIPTION') or '')[:80]}")
