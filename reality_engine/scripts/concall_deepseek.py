"""2026 concall transcripts -> DeepSeek V4.1 Flash on OpenCode Go (Shivam, 2026-10-18: 2026 transcripts are read by
DeepSeek, the blind-judge winner; older years stay as chunks + embeddings).

Order: companies with a PEAD post (data/concall_priority_pead.json) first, then everything else; newest filing first.
Skips: duplicate filings (same sha256 or same ISIN + day), cover letters (< MIN_CHARS of text; they link to the transcript
on the company site), unreadable PDFs. Prompt: data/concall_pilot/prompt_v2.md. Each answer goes through
concall_pilot.machine_check (quote verbatim, numbers in text, basis said) before storage.

Output: data/concall_facts.db
  cc_docs  (doc_id = corporate_documents.id, isin, symbol, filed_at = real filing time, status, model, tokens, cost...)
  cc_items (doc_id, list_name, idx, item_json + main fields)  -- only items that passed machine_check
Budget guard (Go per-model limits; DeepSeek V4.1 Flash $80/month on Go): never call during peak hours (Mon-Fri
01:00-04:00 and 06:00-10:00 UTC = 06:30-09:30 and 11:30-15:30 IST); spend in any rolling 5 h stays under FIVE_H_CAP and in
7 days under WEEK_CAP (estimated from tokens at off-peak prices); an HTTP 429 limit answer benches the key for 30 min.
Resumable: a doc with status ok/skip_* is never re-read.

    python -m reality_engine.scripts.concall_deepseek [--workers 8] [--limit N] [--keys OPENCODE_GO_API_KEY_2] [--dry-run]
"""
import argparse
import concurrent.futures as cf
import datetime as dt
import json
import sqlite3
import threading
import time
from pathlib import Path

from reality_engine.scripts import ingest_annual_reports as ar
from reality_engine.scripts.concall_period import parse_period
from reality_engine.scripts.concall_pilot import LISTS, PILOT, call_go, machine_check, parse_json

ROOT = Path(__file__).resolve().parents[2]
MAIN_DB = ROOT / "reality_engine/data/equity_intelligence.db"
OUT_DB = ROOT / "reality_engine/data/concall_facts.db"
PRIORITY = ROOT / "reality_engine/data/concall_priority_pead.json"
LOG = ROOT / "reality_engine/data/logs/concall_deepseek.log"
MODEL = "deepseek-v4.1-flash"
PRICE_IN, PRICE_OUT = 0.15, 0.60          # $/M tokens off-peak (we never call at peak)
FIVE_H_CAP, WEEK_CAP = 15.0, 38.0         # Go windows are $16 / $40 (20% / 50% of $80); keep a margin
MIN_CHARS = 4000
SINCE = "2026-01-01"

DDL = """
CREATE TABLE IF NOT EXISTS cc_docs (doc_id INTEGER PRIMARY KEY, isin TEXT, symbol TEXT, filed_at TEXT, status TEXT,
    model TEXT, key_name TEXT, chars INTEGER, in_tok INTEGER, out_tok INTEGER, cost_usd REAL, seconds REAL,
    checks_json TEXT, raw_json TEXT, error TEXT, run_at TEXT, priority INTEGER,
    period_discussed TEXT, period_q INTEGER, period_fy INTEGER);
CREATE TABLE IF NOT EXISTS cc_items (doc_id INTEGER, list_name TEXT, idx INTEGER, isin TEXT, filed_at TEXT,
    metric TEXT, value TEXT, unit TEXT, period TEXT, basis TEXT, direction TEXT, firmness TEXT, signal TEXT,
    statement TEXT, quote TEXT, item_json TEXT, PRIMARY KEY (doc_id, list_name, idx));
CREATE INDEX IF NOT EXISTS idx_cc_items_isin ON cc_items(isin, filed_at);
CREATE INDEX IF NOT EXISTS idx_cc_docs_run ON cc_docs(run_at);
"""
lock = threading.Lock()


def log(msg):
    line = f"{dt.datetime.now():%Y-%m-%d %H:%M:%S} {msg}"
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def is_peak(now=None):
    u = (now or dt.datetime.now(dt.timezone.utc))
    return u.weekday() < 5 and (1 <= u.hour < 4 or 6 <= u.hour < 10)


def queue(out):
    main = sqlite3.connect(f"file:{MAIN_DB}?mode=ro", uri=True)
    rows = main.execute("""SELECT id, isin, symbol, COALESCE(bse_dissem_ts, publication_date, call_date) AS filed,
                                  local_file_path, sha256_hash
                           FROM corporate_documents WHERE doc_type='CONCALL_TRANSCRIPT'
                             AND COALESCE(bse_dissem_ts, publication_date, call_date) >= ?
                             AND local_file_path IS NOT NULL AND local_file_path <> ''""", (SINCE,)).fetchall()
    pr = {r["isin"]: n for n, r in enumerate(json.loads(PRIORITY.read_text(encoding="utf-8")))} if PRIORITY.exists() else {}
    done = {d for (d,) in out.execute("SELECT doc_id FROM cc_docs WHERE status='ok' OR status LIKE 'skip_%'")}
    # duplicates decided oldest-first: the EARLIEST public filing of a PDF is the one we keep (point-in-time); a later
    # re-filing of the same file (same sha256) or a second filing on the same ISIN + day is skipped
    dup_ids, seen_sha, seen_day = set(), set(), set()
    for r in sorted(rows, key=lambda r: (r[3] or "", r[0])):
        key_day = (r[1], (r[3] or "")[:10])
        if (r[5] and r[5] in seen_sha) or key_day in seen_day:
            dup_ids.add(r[0])
        seen_day.add(key_day)
        if r[5]:
            seen_sha.add(r[5])
    rows.sort(key=lambda r: (0 if r[1] in pr else 1, "".join(chr(255 - ord(c)) for c in (r[3] or ""))))
    return [(r, r[0] in dup_ids, 0 if r[1] in pr else 1) for r in rows if r[0] not in done]


def spent(out, hours):
    since = (dt.datetime.now() - dt.timedelta(hours=hours)).isoformat(timespec="seconds")
    return out.execute("SELECT COALESCE(SUM(cost_usd),0) FROM cc_docs WHERE run_at >= ?", (since,)).fetchone()[0]


def wait_budget(out_path):
    while True:
        con = sqlite3.connect(out_path, timeout=60)
        s5, s7 = spent(con, 5), spent(con, 24 * 7)
        con.close()
        if is_peak():
            log("peak hours: waiting 10 min"); time.sleep(600); continue
        if s5 >= FIVE_H_CAP or s7 >= WEEK_CAP:
            log(f"budget pause: 5h ${s5:.2f}/{FIVE_H_CAP}, 7d ${s7:.2f}/{WEEK_CAP}; waiting 10 min"); time.sleep(600); continue
        return


def text_of(path):
    import pymupdf
    with pymupdf.open(path) as d:
        return "\n".join(p.get_text() for p in d)


def prompt(symbol, filed, text):
    p = (PILOT / "prompt_v2.md").read_text(encoding="utf-8")
    return p.replace("{company}", symbol or "").replace("{symbol}", symbol or "").replace("{date}", (filed or "")[:10]).replace("{text}", text)


def save(out_path, row):
    with lock:
        con = sqlite3.connect(out_path, timeout=120)
        with con:
            con.execute("INSERT OR REPLACE INTO cc_docs VALUES (:doc_id,:isin,:symbol,:filed_at,:status,:model,:key_name,"
                        ":chars,:in_tok,:out_tok,:cost_usd,:seconds,:checks_json,:raw_json,:error,:run_at,:priority,"
                        ":period_discussed,:period_q,:period_fy)", {"period_discussed": None, "period_q": None, "period_fy": None, **row})
            if row["status"] == "ok":
                data = json.loads(row["raw_json"])
                con.execute("DELETE FROM cc_items WHERE doc_id=?", (row["doc_id"],))
                for k in LISTS:
                    for i, it in enumerate(data.get(k) or []):
                        if not isinstance(it, dict):
                            continue
                        period = it.get("period") or it.get("as_of") or it.get("timeline")
                        if k == "guidance" and not period:
                            period = "unspecified"
                        con.execute("INSERT INTO cc_items VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                            row["doc_id"], k, i, row["isin"], row["filed_at"],
                            it.get("metric") or it.get("item") or it.get("segment_or_market"), str(it.get("value") or it.get("amount") or ""),
                            it.get("unit"), period, _enum("basis", it.get("basis")),
                            _enum("direction", it.get("direction")), _enum("firmness", it.get("firmness")),
                            _enum("signal", it.get("signal")), it.get("statement"), it.get("quote"),
                            json.dumps(it, ensure_ascii=False)))
        con.close()


# allowed label values (prompt_v2); anything else is stored as NULL in the column, the model's text stays in item_json
ENUMS = {"basis": {"standalone", "consolidated", "segment", "unknown"},
         "direction": {"new", "raised", "maintained", "lowered", "withdrawn", "unclear"},
         "firmness": {"firm", "indicative", "aspirational"},
         "signal": {"positive", "neutral", "negative", "mixed"}}


def _enum(name, v):
    v = (v or "").strip().lower() if isinstance(v, str) else v
    return v if v in ENUMS[name] else None


def renormalise(out_path):
    """re-save every ok doc from its stored answer (no API): applies current period parsing + label normalisation"""
    con = sqlite3.connect(out_path, timeout=120)
    rows = con.execute("SELECT * FROM cc_docs WHERE status='ok'").fetchall()
    cols = [d[0] for d in con.execute("SELECT * FROM cc_docs LIMIT 0").description]
    con.close()
    for r in rows:
        row = dict(zip(cols, r))
        pq = parse_period(row.get("period_discussed"))
        row["period_q"], row["period_fy"] = (pq if pq else (None, None))
        save(out_path, row)
    log(f"renormalised {len(rows)} docs")


bench = {}


def work(item, keys, out_path):
    (doc_id, isin, symbol, filed, path, sha), dup, prio = item
    base = {"doc_id": doc_id, "isin": isin, "symbol": symbol, "filed_at": filed, "model": MODEL, "key_name": None,
            "chars": None, "in_tok": None, "out_tok": None, "cost_usd": 0.0, "seconds": None, "checks_json": None,
            "raw_json": None, "error": None, "run_at": dt.datetime.now().isoformat(timespec="seconds"), "priority": prio}
    if dup:
        save(out_path, {**base, "status": "skip_duplicate"}); return "skip_duplicate"
    try:
        text = text_of(path)
    except Exception as e:
        save(out_path, {**base, "status": "skip_unreadable", "error": str(e)[:200]}); return "skip_unreadable"
    base["chars"] = len(text.strip())
    if base["chars"] < MIN_CHARS:
        save(out_path, {**base, "status": "skip_cover_letter"}); return "skip_cover_letter"
    env = ar.user_env()
    for attempt in range(4):
        wait_budget(out_path)
        kname = min(keys, key=lambda k: bench.get(k, 0))
        if bench.get(kname, 0) > time.time():
            time.sleep(bench[kname] - time.time())
        t0 = time.time()
        try:
            out, it, ot = call_go(MODEL, prompt(symbol, filed, text), env[kname])
            cost = ((it or 0) * PRICE_IN + (ot or 0) * PRICE_OUT) / 1e6
            try:
                data = parse_json(out)
            except Exception as e:
                save(out_path, {**base, "status": "error_json", "key_name": kname, "in_tok": it, "out_tok": ot,
                                "cost_usd": cost, "seconds": round(time.time() - t0, 1), "error": str(e)[:200],
                                "run_at": dt.datetime.now().isoformat(timespec="seconds")})
                continue
            data, checks = machine_check(text, data)
            pq = parse_period(data.get("period_discussed"))
            save(out_path, {**base, "status": "ok", "period_discussed": data.get("period_discussed"),
                            "period_q": pq[0] if pq else None, "period_fy": pq[1] if pq else None, "key_name": kname, "in_tok": it, "out_tok": ot, "cost_usd": cost,
                            "seconds": round(time.time() - t0, 1), "checks_json": json.dumps(checks),
                            "raw_json": json.dumps(data, ensure_ascii=False),
                            "run_at": dt.datetime.now().isoformat(timespec="seconds")})
            return "ok"
        except Exception as e:
            msg = str(e)
            if "429" in msg:
                bench[kname] = time.time() + 1800
                log(f"{kname} 429 -> benched 30 min: {msg[:160]}")
            else:
                time.sleep(20)
            last = msg
    save(out_path, {**base, "status": "error", "error": last[:300], "run_at": dt.datetime.now().isoformat(timespec="seconds")})
    return "error"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--sample", type=int, default=0, help="random validation batch of N docs (seeded by N)")
    ap.add_argument("--keys", default="OPENCODE_GO_API_KEY_2")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--renormalise", action="store_true", help="re-save stored answers with current label rules; no API")
    a = ap.parse_args()
    if a.renormalise:
        return renormalise(OUT_DB)
    out = sqlite3.connect(OUT_DB, timeout=120)
    out.executescript(DDL)
    todo = queue(out)
    if a.sample:   # validation batch: random docs across the year and both priority groups, duplicates included
        import random
        random.Random(a.sample).shuffle(todo)
        todo = todo[:a.sample]
    if a.limit:
        todo = todo[:a.limit]
    real = [t for t in todo if not t[1]]
    log(f"queue {len(todo)} (duplicates {len(todo) - len(real)}, PEAD-first {sum(1 for t in todo if t[2] == 0)}); "
        f"spent 5h ${spent(out, 5):.2f}, 7d ${spent(out, 168):.2f}")
    out.close()
    if a.dry_run:
        return
    keys = [k.strip() for k in a.keys.split(",") if k.strip()]
    n = {}
    with cf.ThreadPoolExecutor(a.workers) as ex:
        for i, st in enumerate(ex.map(lambda t: work(t, keys, OUT_DB), todo), 1):
            n[st] = n.get(st, 0) + 1
            if i % 25 == 0:
                con = sqlite3.connect(OUT_DB, timeout=60)
                log(f"[{i}/{len(todo)}] {n} | spent 5h ${spent(con, 5):.2f} 7d ${spent(con, 168):.2f}")
                con.close()
    log(f"RUN_COMPLETE {n}")


if __name__ == "__main__":
    main()
