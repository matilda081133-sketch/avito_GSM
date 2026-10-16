import urllib.request, json, ssl, sys

sys.stdout.reconfigure(encoding='utf-8')
ctx = ssl.create_default_context()

USER_ID = 358201685
TOKEN = "kYu61AdIRBqXRXxpoSmcFgBOhKRRrHGdWpJhqpr3"

# Check items list
url = f"https://api.avito.ru/core/v1/items?per_page=20&status=active"
req = urllib.request.Request(url, headers={
    "Authorization": f"Bearer {TOKEN}"
})

try:
    with urllib.request.urlopen(req, context=ctx) as resp:
        res = json.loads(resp.read().decode("utf-8"))
        print("Total active items:", res.get("meta", {}).get("total"))
        resources = res.get("resources", [])
        print(f"Sample {len(resources)} items:")
        for it in resources[:5]:
            print(f"ID: {it.get('id')} | Title: {it.get('title')} | Category: {it.get('category_id')}")
            # Get item details
            it_id = it.get('id')
            url_it = f"https://api.avito.ru/core/v1/items/{it_id}"
            req_it = urllib.request.Request(url_it, headers={"Authorization": f"Bearer {TOKEN}"})
            try:
                with urllib.request.urlopen(req_it, context=ctx) as r_it:
                    det = json.loads(r_it.read().decode("utf-8"))
                    print(f"   Phone/Contacts: {det.get('phone')} | Manager: {det.get('manager_name')} | Address: {det.get('address')}")
            except Exception as e_it:
                print(f"   Detail error: {e_it}")
except Exception as e:
    print("Error:", e)
