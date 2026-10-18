"""Companies named in Telegram topics (Financially Free community), with point-in-time post times (2026-10-18).

Shivam: read 2026 concalls only for companies covered in the Telegram feed (PEAD 683 + Big Orders 7). Big Orders posts
are image cards (daily 'Orderbook Recap' lists, single-order cards), so this downloads each post's image (read-only on
Telegram, copy of the session), OCRs it with RapidOCR (DirectML), stores media_file_path + ocr_extracted_text on
telegram_posts, and resolves companies by: Chart/Screener button symbol; OCR'd NSE symbol or BSE code; OCR'd company-name
line matched to master_companies (name wins when the OCR'd symbol disagrees, e.g. 'OBSCPL' for OBSCP).

Writes tg_company_mentions(topic_id, post_id, message_id, post_ts_utc, symbol, isin, source) and
data/tg_company_isins.json (union over PEAD signals + these mentions) used by concall_deepseek.py.
Private paid-community content: private DB only, never GitHub.

    python -m reality_engine.scripts.tg_company_mentions [--topics 7] [--no-download]
"""
import argparse
import asyncio
import json
import os
import re
import shutil
import sqlite3
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "reality_engine/data/equity_intelligence.db"
MEDIA = ROOT / "reality_engine/data/telegram_media"
SESSION = ROOT / "reality_engine/data/telegram_session"
CHANNEL = -1002413883243
OUT_JSON = ROOT / "reality_engine/data/tg_company_isins.json"
DDL = """CREATE TABLE IF NOT EXISTS tg_company_mentions (topic_id INTEGER, post_id TEXT, message_id INTEGER,
    post_ts_utc TEXT, symbol TEXT, isin TEXT, source TEXT, PRIMARY KEY (post_id, isin))"""
SUFFIX = re.compile(r"\b(limited|ltd|pvt|private|india|the|co|company|corporation|corp|industries|inds)\b\.?")


def norm_name(s):
    s = re.sub(r"[^a-z0-9& ]+", " ", (s or "").lower().replace("…", " ").replace("...", " "))
    return " ".join(SUFFIX.sub(" ", s).split())


async def download(topics):
    from telethon import TelegramClient
    from reality_engine.scripts import ingest_annual_reports as ar
    env = ar.user_env()
    tmp = Path(tempfile.mkdtemp()) / "c"
    shutil.copy(str(SESSION) + ".session", str(tmp) + ".session")
    cl = TelegramClient(str(tmp), int(env["TELEGRAM_API_ID"]), env["TELEGRAM_API_HASH"])
    await cl.connect()
    ent = await cl.get_entity(CHANNEL)
    got = {}
    for t in topics:
        (MEDIA / str(t)).mkdir(parents=True, exist_ok=True)
        async for m in cl.iter_messages(ent, reply_to=t, limit=None):
            if not m.photo:
                continue
            dst = MEDIA / str(t) / f"{m.id}.jpg"
            if not dst.exists():
                await m.download_media(file=str(dst))
            got[(t, m.id)] = dst
    await cl.disconnect()
    return got


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--topics", default="7")
    ap.add_argument("--no-download", action="store_true")
    a = ap.parse_args()
    topics = [int(x) for x in a.topics.split(",")]
    db = sqlite3.connect(DB, timeout=600)
    db.execute(DDL)
    if not a.no_download:
        got = asyncio.run(download(topics))
        print(f"images on disk: {len(got)}")
    from reality_engine.processing.ocr_engine import FinancialOCREngine
    ocr = FinancialOCREngine()
    by_sym, by_bse, by_name = {}, {}, {}
    for isin, nse, bse, name in db.execute("SELECT isin, nse_symbol, bse_code, company_name FROM master_companies"):
        if nse: by_sym.setdefault(nse.upper(), isin)
        if bse: by_bse.setdefault(str(bse), isin)
        if name: by_name.setdefault(norm_name(name), isin)
    sym_of = {i: s for s, i in by_sym.items()}
    stats = {"posts": 0, "ocr": 0, "mentions": 0, "posts_without_company": 0}
    for t in topics:
        db.execute("DELETE FROM tg_company_mentions WHERE topic_id=?", (t,))
        posts = db.execute("SELECT id, message_id, post_timestamp, raw_message_text, button_links_json, ocr_extracted_text "
                           "FROM telegram_posts WHERE thread_topic_id=?", (t,)).fetchall()
        for pid, mid, ts, text, bl, old_ocr in posts:
            stats["posts"] += 1
            img = MEDIA / str(t) / f"{mid}.jpg"
            o = old_ocr
            if img.exists() and not o:
                o = ocr.process_image(str(img)).get("raw_text") or ""
                db.execute("UPDATE telegram_posts SET media_file_path=?, ocr_extracted_text=? WHERE id=?", (str(img), o, pid))
                stats["ocr"] += 1
            found = {}
            bj = json.loads(bl or "{}") or {}
            for b in (bj if isinstance(bj, list) else bj.get("buttons", [])):
                mm = re.search(r"symbol=(?:NSE|BSE):([A-Z0-9&_.-]+)|screener\.in/company/([A-Z0-9&_.-]+)/", (b or {}).get("url", ""))
                if mm:
                    s = mm.group(1) or mm.group(2)
                    i = by_sym.get(s) or by_bse.get(s)
                    if i: found.setdefault(i, (s, "button"))
            unmapped = []
            for ex, code in re.findall(r"\b(NSE|BSE)\s*:\s*([A-Z0-9&_-]{2,20})", text or ""):   # 'NSE: PARTH | BSE: 5xxxxx'
                i = by_sym.get(code) if ex == "NSE" else by_bse.get(code)
                if i:
                    found.setdefault(i, (sym_of.get(i) or code, "text_symbol"))
                else:
                    unmapped.append(f"{ex}:{code}")
            lines = [l.strip() for l in ((o or "") + "\n" + (text or "")).splitlines() if l.strip()]
            for l in lines:      # company-name lines first (they win over OCR'd symbols)
                n = norm_name(l)
                if len(n) >= 4 and n in by_name:
                    found.setdefault(by_name[n], (sym_of.get(by_name[n]), "ocr_name"))
            for l in lines:
                # a card prints the symbol / BSE code ALONE on its line; tokens inside sentences ('ORDER VALUE',
                # 'NSE/BSE filings') matched real symbols VALUE/BSE 140 times in the first version
                tok = re.sub(r"[^A-Z0-9&]+$", "", l.strip())
                if re.fullmatch(r"[A-Z][A-Z0-9&]{2,14}|5\d{5}", tok):
                    i = by_sym.get(tok) or by_bse.get(tok)
                    if i and i not in found:
                        found[i] = (tok, "ocr_symbol")
            if not found:
                # older hand-written posts: 'PTC Industries Limited (PTCIL)' or 'Supreme Power won 28cr order ...'
                for code in re.findall(r"\(([A-Z][A-Z0-9&]{1,14})\)", (o or "") + " " + (text or "")):
                    if code in by_sym:
                        found.setdefault(by_sym[code], (code, "bracket_symbol"))
                first = norm_name(" ".join((text or "").split()[:3]))
                for k in (3, 2):
                    pre = " ".join(first.split()[:k])
                    hits = {i for n, i in by_name.items() if len(pre) >= 6 and (n == pre or n.startswith(pre + " "))}
                    if not found and len(hits) == 1:
                        i = hits.pop(); found[i] = (sym_of.get(i), "text_name_prefix")
            if not found and unmapped:
                # a company the post names but our master_companies lacks (mostly NSE SME): kept, isin NULL, so the
                # coverage gap is visible instead of silently dropped
                for u in sorted(set(unmapped)):
                    db.execute("INSERT OR REPLACE INTO tg_company_mentions VALUES (?,?,?,?,?,?,?)",
                               (t, pid, mid, ts, u, None, "not_in_master"))
                stats["names_not_in_master"] = stats.get("names_not_in_master", 0) + 1
                continue
            if not found:
                stats["posts_without_company"] += 1
            for i, (s, src) in found.items():
                db.execute("INSERT OR REPLACE INTO tg_company_mentions VALUES (?,?,?,?,?,?,?)", (t, pid, mid, ts, s, i, src))
                stats["mentions"] += 1
        db.commit()
    pead = {r[0] for r in db.execute("SELECT isin FROM tg_pead_signals WHERE isin IS NOT NULL AND is_test_post=0")}
    ment = {r[0] for r in db.execute("SELECT isin FROM tg_company_mentions WHERE isin IS NOT NULL")}
    OUT_JSON.write_text(json.dumps(sorted(pead | ment)), encoding="utf-8")
    print(json.dumps(stats), f"| companies: PEAD {len(pead)}, Big Orders {len(ment)}, union {len(pead | ment)} -> {OUT_JSON.name}")


if __name__ == "__main__":
    main()
