"""Backfill Telegram forum-topic history (TEXT + LINKS + timestamps only; no media downloads).

Read-only on Telegram (uses a COPY of the session). Idempotent: telegram_posts.id is the same key the live listener
uses, INSERT OR IGNORE. Also resolves the real topic names (older rows carry placeholders like 'Topic #683') and adds
each new text post to the search index (intelligence_fts, source_type 'TG_<topic>').
Private paid-community content: keep in the private DB only, never on GitHub.

    python reality_engine/scripts/tg_backfill.py [--topics 13,7,683]
"""
import argparse, asyncio, json, os, re, shutil, sqlite3, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from telethon import TelegramClient
from telethon.tl.types import MessageEntityTextUrl, MessageEntityUrl
from reality_engine.ingestion.telegram_client import TelegramListener

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "reality_engine/data/equity_intelligence.db"
SESSION = ROOT / "reality_engine/data/telegram_session"
CHANNEL = -1002413883243
SCOPE = {13: "Daily Bytes", 7: "Big Orders", 683: "PEAD", 2397: "Concall Highlights", 4: "#BuyBacks",
         10: "Interesting Announcement", 11: "Interesting - Interviews", 3: "#Demerger", 165: "Shipping Data",
         1625: "Open Offers/ Take Overs"}


async def main(topics):
    tmp = Path(tempfile.mkdtemp()) / "c"
    shutil.copy(str(SESSION) + ".session", str(tmp) + ".session")
    cl = TelegramClient(str(tmp), int(os.environ["TELEGRAM_API_ID"]), os.environ["TELEGRAM_API_HASH"])
    await cl.connect()
    if not await cl.is_user_authorized():
        print("session not authorized"); return 3
    ent = await cl.get_entity(CHANNEL)
    title = getattr(ent, "title", "Financially Free Premium Community")
    db = sqlite3.connect(DB, timeout=600)
    cid = str(CHANNEL)
    for tid, name in topics.items():
        db.execute("update telegram_posts set thread_topic_name=? where channel_id=? and thread_topic_id=?", (name, cid, tid))
        new = seen = 0
        async for m in cl.iter_messages(ent, reply_to=tid, limit=None):
            seen += 1
            text = m.message or ""
            urls = []
            for e, t in (m.get_entities_text() or []):
                if isinstance(e, MessageEntityTextUrl): urls.append(e.url)
                elif isinstance(e, MessageEntityUrl): urls.append(t)
            btn = []
            for row in (m.buttons or []):
                for b in row:
                    if getattr(b, "url", None): btn.append({"text": b.text, "url": b.url})
            post_id = f"{TelegramListener._sanitize_filename_component(cid)}_{m.id}"
            ts = m.date.isoformat()
            cur = db.execute(
                "insert or ignore into telegram_posts (id, channel_id, channel_title, thread_topic_id, thread_topic_name, message_id,"
                " raw_message_text, has_media, media_file_path, ocr_extracted_text, detected_symbols_json, post_timestamp, button_links_json)"
                " values (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (post_id, cid, title, tid, name, m.id, text, 1 if m.media else 0, None, None, "[]", ts,
                 json.dumps({"buttons": btn, "urls": sorted(set(urls))})))
            if cur.rowcount and len(text.strip()) >= 20:
                new += 1
                db.execute("insert into intelligence_fts(chunk_id, symbol, isin, source_type, document_date, document_text) values (?,?,?,?,?,?)",
                           (f"tg:{post_id}", "", "", "TG_" + re.sub(r"[^A-Za-z0-9]+", "", name), ts[:10],
                            f"[Metadata: Symbol:  | Doc: TG_{name} | Date: {ts[:10]} | posted={ts}]\n{text[:4000]}"))
            if seen % 200 == 0:
                db.commit()
        db.commit()
        print(f"topic {tid} {name}: seen={seen} new_text_posts_indexed={new}", flush=True)
    await cl.disconnect()
    return 0

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--topics", default="")
    a = ap.parse_args()
    sel = {int(t): SCOPE[int(t)] for t in a.topics.split(",") if t} if a.topics else SCOPE
    sys.exit(asyncio.run(main(sel)))
