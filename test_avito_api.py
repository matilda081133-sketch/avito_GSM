import urllib.request, urllib.parse, json, ssl, sys

sys.stdout.reconfigure(encoding='utf-8')
ctx = ssl.create_default_context()

CLIENT_ID = "oawHPlf75CBY-Hm4Rqpl"
CLIENT_SECRET = "vPKPG4c6xEi34NDRQL7OU7mxPYaIcc_rXwMQTiiA"

def get_token():
    url = "https://api.avito.ru/token"
    data = urllib.parse.urlencode({
        "grant_type": "client_credentials",
        "client_id": CLIENT_ID.strip(),
        "client_secret": CLIENT_SECRET.strip()
    }).encode("utf-8")
    
    req = urllib.request.Request(url, data=data, headers={
        "Content-Type": "application/x-www-form-urlencoded"
    })
    try:
        with urllib.request.urlopen(req, context=ctx) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print("HTTP Error:", e.code, e.read().decode("utf-8"))
        return None

token_data = get_token()
print("Token response:", token_data)
if token_data and "access_token" in token_data:
    token = token_data["access_token"]
    # Get account info
    req_acc = urllib.request.Request("https://api.avito.ru/core/v1/accounts/self", headers={
        "Authorization": f"Bearer {token}"
    })
    try:
        with urllib.request.urlopen(req_acc, context=ctx) as resp:
            acc = json.loads(resp.read().decode("utf-8"))
            print("Account info:", acc)
    except Exception as e:
        print("Account error:", e)
