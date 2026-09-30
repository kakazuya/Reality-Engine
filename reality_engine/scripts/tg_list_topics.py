"""Read-only: list forum topics of a Telegram channel with message counts and date range.

Downloads nothing and writes nothing except an optional CSV. Uses a COPY of the existing
Telethon session so the live session file is never locked or modified.

Needs your own credentials in the environment (never hard-code them):
    $env:TELEGRAM_API_ID   = "<your api_id>"
    $env:TELEGRAM_API_HASH = "<your api_hash>"
Usage:
    python reality_engine/scripts/tg_list_topics.py --channel -1002413883243 [--csv topics.csv]
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import os
import shutil
import sys
import tempfile
from pathlib import Path

from telethon import TelegramClient
from telethon.tl.functions.messages import GetForumTopicsRequest

SESSION = Path(__file__).resolve().parents[1] / "data" / "telegram_session"


async def main(channel: str, out_csv: str | None) -> int:
    api_id, api_hash = os.environ.get("TELEGRAM_API_ID"), os.environ.get("TELEGRAM_API_HASH")
    if not api_id or not api_hash:
        print("Set TELEGRAM_API_ID and TELEGRAM_API_HASH first.")
        return 2
    tmp = Path(tempfile.mkdtemp()) / "tg_copy"
    shutil.copy(str(SESSION) + ".session", str(tmp) + ".session")
    client = TelegramClient(str(tmp), int(api_id), api_hash)
    await client.connect()
    if not await client.is_user_authorized():
        print("Session is not authorized; log in once with the project's normal Telegram flow.")
        return 3
    ent = await client.get_entity(int(channel) if channel.lstrip("-").isdigit() else channel)
    print(f"Channel: {getattr(ent, 'title', ent)}  forum={getattr(ent, 'forum', False)}")
    res = await client(GetForumTopicsRequest(peer=ent, offset_date=None, offset_id=0, offset_topic=0, limit=100))
    rows = []
    for t in res.topics:
        newest = await client.get_messages(ent, limit=1, reply_to=t.id)
        oldest = await client.get_messages(ent, limit=1, reply_to=t.id, reverse=True)
        n = getattr(newest, "total", 0)
        last = newest[0].date if newest else None
        first = oldest[0].date if oldest else None
        rows.append((t.id, getattr(t, "title", ""), n, first, last))
        print(f"  topic {t.id:>6}  {getattr(t, 'title', '')[:40]:40s}  msgs={n:>6}  {first} -> {last}")
    if out_csv:
        with open(out_csv, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["topic_id", "title", "messages", "first", "last"])
            w.writerows(rows)
    await client.disconnect()
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--channel", required=True)
    ap.add_argument("--csv")
    a = ap.parse_args()
    sys.exit(asyncio.run(main(a.channel, a.csv)))
