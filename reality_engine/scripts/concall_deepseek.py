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
# Shivam 2026-10-18: read ONLY companies covered in the Telegram feed (PEAD + Big Orders topics); built by tg_company_isins
TG_ISINS = ROOT / "reality_engine/data/tg_company_isins.json"
LOG = ROOT / "reality_engine/data/logs/concall_deepseek.log"
MODEL = "deepseek-v4.1-flash"
PROMPT_FILE = "prompt_v2.md"
REREAD_MODELS = set()   # --prompt; the tag (v2/v3) is stored in cc_docs.checks_json["prompt"]
FREE_MODELS = {"beam-free", "minimax-m3.1-flash-free", "longcat-2.5-preview-free"}   # no spend guard, cost 0
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


def queue(out, only_tg=True):
    main = sqlite3.connect(f"file:{MAIN_DB}?mode=ro", uri=True)
    rows = main.execute("""SELECT id, isin, symbol, COALESCE(bse_dissem_ts, publication_date, call_date) AS filed,
                                  local_file_path, sha256_hash
                           FROM corporate_documents WHERE doc_type='CONCALL_TRANSCRIPT'
                             AND COALESCE(bse_dissem_ts, publication_date, call_date) >= ?
                             AND local_file_path IS NOT NULL AND local_file_path <> ''""", (SINCE,)).fetchall()
    pr = {r["isin"]: n for n, r in enumerate(json.loads(PRIORITY.read_text(encoding="utf-8")))} if PRIORITY.exists() else {}
    if only_tg:
        allowed = set(json.loads(TG_ISINS.read_text(encoding="utf-8")))
        rows = [r for r in rows if r[1] in allowed]
    done = {d for (d,) in out.execute("SELECT doc_id FROM cc_docs WHERE status='ok' OR status LIKE 'skip_%'")}
    # docs a 429 interrupted (status 'queued_429', 2026-10-20) go first
    q429 = {d for (d,) in out.execute("SELECT doc_id FROM cc_docs WHERE status='queued_429'")}
    if REREAD_MODELS:   # re-read docs these readers stored under an older prompt (2026-10-20: v2 -> v3)
        tag = PROMPT_FILE.replace("prompt_", "").replace(".md", "")
        old = {d for d, m, ck in out.execute("SELECT doc_id, model, checks_json FROM cc_docs WHERE status='ok'")
               if m in REREAD_MODELS and (json.loads(ck or "{}").get("prompt") or "v2") != tag}
        done -= old
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
    rows.sort(key=lambda r: (0 if r[0] in q429 else 1, 0 if r[1] in pr else 1, "".join(chr(255 - ord(c)) for c in (r[3] or ""))))
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
    p = (PILOT / PROMPT_FILE).read_text(encoding="utf-8")
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
# Upstream 429 = the whole model lane is rate-limited (both keys at once, Beam 2026-10-20 11:52-20:00+). Shivam
# 2026-10-20: never turn a 429 into a permanent 'error'; while the lane is down every worker waits and exactly ONE
# worker taps it with a single call every LANE_TAP_S; the first answer reopens the lane for all workers.
LANE_TAP_S = 900
lane = {"down": False, "until": 0.0, "probing": False}


def lane_gate():
    """Block while the lane is down; return True when this worker is the one allowed to send the probe call."""
    while True:
        with lock:
            now = time.time()
            if not lane["down"]:
                return False
            if lane["until"] <= now and not lane["probing"]:
                lane["probing"] = True
                return True
            wait = max(5.0, lane["until"] - now) if lane["until"] > now else 5.0
        time.sleep(min(wait, 60))


def lane_result(ok, probe):
    with lock:
        if ok:
            if lane["down"]:
                log("lane answered again: all workers resume")
            lane.update(down=False, probing=False)
        else:   # 429
            first = not lane["down"]
            lane.update(down=True, until=time.time() + LANE_TAP_S, probing=False)
            if first or probe:
                log(f"lane 429 ({'tap failed' if probe else 'lane down'}): next single tap in {LANE_TAP_S // 60} min")


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
    attempt = 0
    last = "4 broken-JSON answers"   # 2026-10-20: unset when every attempt was error_json -> UnboundLocalError killed the run
    while attempt < 4:
        attempt += 1
        if MODEL.split("~")[0] not in FREE_MODELS:   # free Go readers: no spend window, no peak pause
            wait_budget(out_path)
        kname = min(keys, key=lambda k: bench.get(k, 0))
        if bench.get(kname, 0) > time.time():
            time.sleep(bench[kname] - time.time())
        probe = lane_gate()
        t0 = time.time()
        try:
            out, it, ot = call_go(MODEL, prompt(symbol, filed, text), env[kname])
            lane_result(True, probe)
            cost = 0.0 if MODEL.split("~")[0] in FREE_MODELS else ((it or 0) * PRICE_IN + (ot or 0) * PRICE_OUT) / 1e6
            try:
                data = parse_json(out)
            except Exception as e:
                save(out_path, {**base, "status": "error_json", "key_name": kname, "in_tok": it, "out_tok": ot,
                                "cost_usd": cost, "seconds": round(time.time() - t0, 1), "error": str(e)[:200],
                                "run_at": dt.datetime.now().isoformat(timespec="seconds")})
                continue
            data, checks = machine_check(text, data)
            checks["prompt"] = PROMPT_FILE.replace("prompt_", "").replace(".md", "")
            pq = parse_period(data.get("period_discussed"))
            save(out_path, {**base, "status": "ok", "period_discussed": data.get("period_discussed"),
                            "period_q": pq[0] if pq else None, "period_fy": pq[1] if pq else None, "key_name": kname, "in_tok": it, "out_tok": ot, "cost_usd": cost,
                            "seconds": round(time.time() - t0, 1), "checks_json": json.dumps(checks),
                            "raw_json": json.dumps(data, ensure_ascii=False),
                            "run_at": dt.datetime.now().isoformat(timespec="seconds")})
            return "ok"
        except Exception as e:
            msg = str(e)
            if "GoUsageLimitError" in msg:
                # Go's 5-hour / weekly window is spent: wait for it to roll, without using up this doc's attempts
                # (2026-10-19 00:06: four 30-min retries would have turned the rest of the queue into errors)
                bench[kname] = time.time() + 900
                attempt -= 1
                with lock:
                    if time.time() - bench.get("_logged", 0) > 600:
                        bench["_logged"] = time.time(); log(f"{kname} Go usage limit reached; waiting 15 min steps")
                continue
            if "429" in msg:
                lane_result(False, probe)
                attempt -= 1     # a rate limit is not the doc's fault: never spend its attempts on it
                continue
            if probe:
                with lock:
                    lane["probing"] = False
            time.sleep(20)
            last = msg
    save(out_path, {**base, "status": "error", "error": last[:300], "run_at": dt.datetime.now().isoformat(timespec="seconds")})
    return "error"


def _set_caps(week, five_h):
    global WEEK_CAP, FIVE_H_CAP
    WEEK_CAP, FIVE_H_CAP = week, five_h


def main():
    global MODEL, SINCE, LOG, PROMPT_FILE, REREAD_MODELS
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--sample", type=int, default=0, help="random validation batch of N docs (seeded by N)")
    ap.add_argument("--keys", default="OPENCODE_GO_API_KEY_2")
    ap.add_argument("--week-cap", type=float, default=WEEK_CAP,
                    help="our own 7-day spend guard; Go's weekly limit resets on a fixed day, so set this high and let "
                         "Go's 429 (bench 30 min) enforce the week when a reset is due")
    ap.add_argument("--five-h-cap", type=float, default=FIVE_H_CAP)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--all-companies", action="store_true", help="ignore the Telegram company list (off by default)")
    ap.add_argument("--renormalise", action="store_true", help="re-save stored answers with current label rules; no API")
    # 2026-10-20 (Shivam): the rest of the transcripts (all years, all companies) go to the FREE Go readers, Beam and
    # MiniMax (high effort), on both keys; DeepSeek checks their output. Shards split the queue so two readers never
    # read the same transcript (doc_id % n in the listed residues).
    ap.add_argument("--model", default=MODEL, help="Go model id, '<id>~<effort>' for reasoning effort")
    ap.add_argument("--since", default=SINCE, help="earliest filing date to read")
    ap.add_argument("--shard", default="", help="'r1,r2/n': only docs with doc_id %% n in {r1,r2}")
    ap.add_argument("--max-out", type=int, default=32000, help="output-token cap per call")
    ap.add_argument("--prompt", default=PROMPT_FILE, help="prompt file in data/concall_pilot (v3 from 2026-10-20)")
    ap.add_argument("--reread-models", default="", help="re-read docs these models stored under another prompt")
    a = ap.parse_args()
    MODEL, SINCE, PROMPT_FILE = a.model, a.since, a.prompt
    REREAD_MODELS = {m for m in a.reread_models.split(",") if m}
    if MODEL.split("~")[0] in FREE_MODELS:
        LOG = ROOT / f"reality_engine/data/logs/concall_{MODEL.split('~')[0]}.log"
    from reality_engine.scripts import concall_pilot
    concall_pilot.MAX_OUT = a.max_out
    _set_caps(a.week_cap, a.five_h_cap)
    if a.renormalise:
        return renormalise(OUT_DB)
    out = sqlite3.connect(OUT_DB, timeout=120)
    out.executescript(DDL)
    todo = queue(out, only_tg=not a.all_companies)
    if a.shard:
        res, n = a.shard.split("/")
        keep = {int(r) for r in res.split(",")}
        todo = [t for t in todo if t[0][0] % int(n) in keep]
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
