"""Collect YouTube links from selected Telegram forum topics (read-only) -> analysis/tg_video_links.csv."""
import asyncio, csv, os, re, shutil, tempfile
from pathlib import Path
from telethon import TelegramClient
S = Path('reality_engine/data/telegram_session')
TOPICS = {13: 'Daily Bytes', 11: 'Interesting - Interviews', 1: 'General'}
YT = re.compile(r'https?://(?:www\.|m\.)?(?:youtu\.be/|youtube\.com/(?:watch\?v=|live/|shorts/))([A-Za-z0-9_-]{11})')

async def main():
    tmp = Path(tempfile.mkdtemp()) / 'c'; shutil.copy(str(S) + '.session', str(tmp) + '.session')
    c = TelegramClient(str(tmp), int(os.environ['TELEGRAM_API_ID']), os.environ['TELEGRAM_API_HASH']); await c.connect()
    ent = await c.get_entity(-1002413883243)
    rows, seen = [], set()
    for tid, name in TOPICS.items():
        async for m in c.iter_messages(ent, reply_to=tid, limit=None):
            urls = list(YT.finditer(m.message or ''))
            for e in (m.entities or []):
                u = getattr(e, 'url', None)
                if u:
                    mm = YT.search(u)
                    if mm: urls.append(mm)
            for mm in urls:
                vid = mm.group(1)
                rows.append((name, m.id, m.date.isoformat(), vid, f'https://youtu.be/{vid}', vid in seen))
                seen.add(vid)
    with open('analysis/tg_video_links.csv', 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f); w.writerow(['topic', 'message_id', 'posted_utc', 'video_id', 'url', 'duplicate']); w.writerows(rows)
    print(len(rows), 'link rows,', len(seen), 'unique videos')
    await c.disconnect()
asyncio.run(main())
