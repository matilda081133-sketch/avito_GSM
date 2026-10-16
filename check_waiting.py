import sys, time
from avito_api import AvitoClient
from config import AVITO_CLIENT_ID, AVITO_CLIENT_SECRET, AVITO_USER_ID

sys.stdout.reconfigure(encoding='utf-8')
client = AvitoClient(AVITO_CLIENT_ID, AVITO_CLIENT_SECRET, AVITO_USER_ID)
unread = client.get_unread_chats(limit=30)
recent = client.get_recent_chats(limit=30)

seen = set()
all_chats = []
for c in (unread + recent):
    cid = c.get('id')
    if cid and cid not in seen:
        seen.add(cid)
        all_chats.append(c)

print(f"Total chats to check: {len(all_chats)}")
now = time.time()
waiting_candidates = []

for c in all_chats:
    cid = c.get('id')
    raw_msgs = client.get_chat_messages(cid, limit=5)
    if not raw_msgs:
        continue
    last = raw_msgs[0]
    author_id = last.get('author_id')
    if author_id != AVITO_USER_ID:
        created = last.get('created', 0)
        mins_ago = (now - created) / 60.0
        txt = last.get('content', {}).get('text', '')
        users = c.get('users', [])
        cand_name = [u.get('name') for u in users if u.get('id') != AVITO_USER_ID]
        waiting_candidates.append({
            'chat_id': cid,
            'name': cand_name,
            'text': txt,
            'mins_ago': mins_ago,
            'chat': c
        })

print(f"\nFOUND {len(waiting_candidates)} candidates waiting for answer:")
for w in waiting_candidates:
    print(f"\n--- Chat: {w['chat_id']} | Candidate: {w['name']} | Sent: {w['mins_ago']:.1f} mins ago")
    print(f"Message: {w['text']}")
