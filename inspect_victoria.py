from avito_api import AvitoClient
from config import AVITO_CLIENT_ID, AVITO_CLIENT_SECRET, AVITO_USER_ID
import json, sys

sys.stdout.reconfigure(encoding='utf-8')
client = AvitoClient(AVITO_CLIENT_ID, AVITO_CLIENT_SECRET, AVITO_USER_ID)
msgs = client.get_chat_messages('u2i-pC53khfN8_XHVHegKgR8ig', limit=10)
print('Total messages in Victoria chat:', len(msgs))
for m in reversed(msgs):
    author = "WE" if m.get('author_id') == AVITO_USER_ID else "CANDIDATE"
    print(f"[{m.get('created')}] {author}: {m.get('content', {}).get('text')}")
