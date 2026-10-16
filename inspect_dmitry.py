from avito_api import AvitoClient
from config import AVITO_CLIENT_ID, AVITO_CLIENT_SECRET, AVITO_USER_ID
import json, sys

sys.stdout.reconfigure(encoding='utf-8')
client = AvitoClient(AVITO_CLIENT_ID, AVITO_CLIENT_SECRET, AVITO_USER_ID)
msgs = client.get_chat_messages('u2i-YR_jSnh3bYNb2mfWifOoFg', limit=3)
for m in msgs:
    print(f"[{m.get('created')}] {m.get('author_id')}: {m.get('content', {}).get('text')}")
