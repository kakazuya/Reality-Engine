"""PEAD signal table from the Financially Free 'PEAD' Telegram topic (683), for backtesting and transcript priority.

One row per (post, company) in tg_pead_signals: post id/message id, exact post time (UTC, Telegram server time = the
point-in-time stamp), company as named in the post, symbol (Chart/Screener button first: 'NSE:POLYCAB' or a BSE code;
else the listener's OCR/text detections), ISIN via master_companies, the label after ' - ' (e.g. 'Great Results'), the
filing link and how the symbol was found. Idempotent (rebuilt from telegram_posts each run). Private paid-community
content: private DB only, never GitHub.

    python -m reality_engine.scripts.tg_pead_signals [--since 2026-06-18] [--priority-out FILE]

--priority-out writes the concall-transcript priority list: companies with a PEAD post since --since, newest post first,
with their filed CONCALL_TRANSCRIPT doc ids (corporate_documents) and whether a transcript after the post exists.
"""
import argparse
import json
import re
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "reality_engine/data/equity_intelligence.db"
TOPIC = 683

DDL = """create table if not exists tg_pead_signals (
    post_id text not null, message_id integer not null, post_ts_utc text not null,
    company_text text, label text, symbol text, isin text, symbol_source text,
    filing_url text, screener_url text, is_test_post integer default 0,
    primary key (post_id, symbol))"""


def symbols_from_buttons(btns):
    """('POLYCAB', 'chart_button') from tradingview NSE:/BSE: or screener /company/<X>/ links."""
    out = []
    for b in btns:
        u = b.get("url", "")
        m = re.search(r"tradingview\.com/chart/\?symbol=(?:NSE|BSE):([A-Z0-9&_.-]+)", u)
        if m:
            out.append((m.group(1), "chart_button"))
        m = re.search(r"screener\.in/company/([A-Z0-9&_.-]+)/", u)
        if m:
            out.append((m.group(1), "screener_button"))
    seen, res = set(), []
    for s, src in sorted(out, key=lambda x: x[1] != "chart_button"):
        if s not in seen:
            seen.add(s); res.append((s, src))
    return res[:1]   # one company per post: chart button wins, screener is the fallback


def build(db):
    db.execute(DDL)
    db.execute("delete from tg_pead_signals")
    isin_of = {}
    for isin, nse, bse in db.execute("select isin, nse_symbol, bse_code from master_companies"):
        for k in (nse, bse):
            if k:
                isin_of.setdefault(str(k), isin)
    rows = db.execute("select id, message_id, post_timestamp, raw_message_text, detected_symbols_json, button_links_json "
                      "from telegram_posts where thread_topic_id=?", (TOPIC,)).fetchall()
    n = 0
    for pid, mid, ts, text, det, bl in rows:
        bj = json.loads(bl or "{}") or {}
        btns = [b for b in (bj if isinstance(bj, list) else bj.get("buttons", [])) if isinstance(b, dict)]   # older rows: bare list
        first = (text or "").split("\n")[0].strip()
        m = re.match(r"(.+?)\s+-\s+(.+)$", first)
        company, label = (m.group(1), re.sub(r"^[^\w]+", "", m.group(2)).strip()) if m else (None, None)
        filing = next((b["url"] for b in btns if "Filing" in b.get("text", "")), None)
        screener = next((b["url"] for b in btns if "screener.in" in b.get("url", "")), None)
        syms = symbols_from_buttons(btns) or [(s, "listener_detected") for s in json.loads(det or "[]")]
        test = int("TEST POST" in (text or "").upper())
        for s, src in syms:
            db.execute("insert or replace into tg_pead_signals values (?,?,?,?,?,?,?,?,?,?,?)",
                       (pid, mid, ts, company, label, s, isin_of.get(s), src, filing, screener, test))
            n += 1
    db.commit()
    return len(rows), n


def priority(db, since, out):
    q = """select s.isin, max(s.symbol), max(s.company_text), max(s.post_ts_utc), count(*)
           from tg_pead_signals s where s.isin is not null and s.is_test_post=0 and s.post_ts_utc>=?
           group by s.isin order by max(s.post_ts_utc) desc"""
    res = []
    for isin, sym, comp, last_ts, nposts in db.execute(q, (since,)).fetchall():
        docs = db.execute("""select id, coalesce(bse_dissem_ts, call_date, doc_date) d from corporate_documents
                             where doc_type='CONCALL_TRANSCRIPT' and isin=? order by d desc""", (isin,)).fetchall()
        res.append({"isin": isin, "symbol": sym, "company": comp, "last_pead_post_utc": last_ts, "pead_posts": nposts,
                    "transcript_doc_ids": [d[0] for d in docs],
                    "has_transcript_after_last_post": any((d[1] or "") >= last_ts[:10] for d in docs)})
    Path(out).write_text(json.dumps(res, indent=1, ensure_ascii=False), encoding="utf-8")
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2026-06-18")
    ap.add_argument("--priority-out", default=str(ROOT / "reality_engine/data/concall_priority_pead.json"))
    a = ap.parse_args()
    db = sqlite3.connect(DB, timeout=600)
    posts, sig = build(db)
    unresolved = db.execute("select count(*) from tg_pead_signals where isin is null").fetchone()[0]
    res = priority(db, a.since, a.priority_out)
    print(f"PEAD posts {posts}, signal rows {sig}, without ISIN {unresolved}; since {a.since}: {len(res)} companies, "
          f"{sum(bool(r['transcript_doc_ids']) for r in res)} with transcripts filed, "
          f"{sum(r['has_transcript_after_last_post'] for r in res)} with one after the last post, "
          f"{sum(len(r['transcript_doc_ids']) for r in res)} transcripts -> {a.priority_out}")


if __name__ == "__main__":
    main()
