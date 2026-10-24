"""Concall transcripts -> free readers on OpenCode Go / Kilo (patch 2026-10-24).

Order: companies with a PEAD post (data/concall_priority_pead.json) first, then everything else; newest filing first.
`--strict-date` drops both priority keys and sorts strictly newest -> oldest by the real call/filing date.
`--from-chunks` reads the text from document_chunks (overlap-aware join) when the recorded PDF is not on disk; a doc
with no readable text is `skip_unreadable_text`, which is RETRYABLE (never counted as done). Docs with neither a text
source nor a local path are left out of the queue ("not runnable yet") instead of burning a done status.
Undated transcripts (the 1,499 whose date was overwritten by the crawl stamp) get their call date parsed from the first
~3,000 chars of text; a date that fails the filing-date sanity rule is rejected, and `date_source` records where the
date came from.

Lanes: `--lanes KEY_ENV=model[,KEY_ENV=model...]` runs three interleaved lanes (e.g. Go key 2 Beam, Kilo key 1 and
Kilo key 2 Beam), each with its own 429 bench and a stable x-opencode-session per lane. Without --lanes the old
--keys/--model behaviour is kept (one lane per key, round-robin).

Output: data/concall_facts.db
  cc_docs  (doc_id = corporate_documents.id, isin, symbol, filed_at = real filing/call time, date_source, status, ...)
  cc_items (doc_id, list_name, idx, item_json + main fields)  -- only items that passed machine_check
Prompt: data/concall_pilot/prompt_v3.md (v2 is not on disk). Each answer goes through concall_pilot.machine_check
(quote verbatim, numbers in text, basis said) before storage.
Budget guard (paid models only): peak hours, rolling 5 h / 7 day caps; an HTTP 429 benches that lane, not the run.
Resumable: status ok and terminal skip_* are done; skip_unreadable / skip_unreadable_text / queued_429 / error retry.

    python -m reality_engine.scripts.concall_deepseek [--workers 8] [--limit N] [--keys OPENCODE_GO_API_KEY_2]
        [--from-chunks] [--strict-date] [--lanes "OPENCODE_GO_API_KEY_2=beam-free,KILO_API_KEY=reflection/beam-free"]
"""
import argparse
import concurrent.futures as cf
import datetime as dt
import json
import re
import sqlite3
import threading
import time
from pathlib import Path

from reality_engine.scripts import ingest_annual_reports as ar
from reality_engine.scripts.concall_period import parse_period
from reality_engine.scripts.concall_pilot import KILO_URL, LISTS, PILOT, call_go, machine_check, parse_json
from reality_engine.scripts.go_session import session_id

ROOT = Path(__file__).resolve().parents[2]
MAIN_DB = ROOT / "reality_engine/data/equity_intelligence.db"
OUT_DB = ROOT / "reality_engine/data/concall_facts.db"
PRIORITY = ROOT / "reality_engine/data/concall_priority_pead.json"
# Shivam 2026-10-18: read ONLY companies covered in the Telegram feed (PEAD + Big Orders topics); built by tg_company_isins
TG_ISINS = ROOT / "reality_engine/data/tg_company_isins.json"
LOG = ROOT / "reality_engine/data/logs/concall_deepseek.log"
MODEL = "deepseek-v4.1-flash"
PROMPT_FILE = "prompt_v3.md"
REREAD_MODELS = set()   # --prompt; the tag (v2/v3) is stored in cc_docs.checks_json["prompt"]
# Free readers: no spend guard, cost 0. Kilo serves the same Beam model under `reflection/beam-free`.
FREE_MODELS = {"beam-free", "minimax-m3.1-flash-free", "longcat-2.5-preview-free", "reflection/beam-free"}
GO_URL = "https://opencode.ai/zen/go/v1/chat/completions"
PRICE_IN, PRICE_OUT = 0.15, 0.60          # $/M tokens off-peak (we never call at peak)
FIVE_H_CAP, WEEK_CAP = 15.0, 38.0         # Go windows are $16 / $40 (20% / 50% of $80); keep a margin
MIN_CHARS = 4000
SINCE = "2026-01-01"
# Missing text and unreadable text are RETRYABLE: they must never sit in the done set (2026-10-24 fix; the old runner
# wrote `skip_unreadable` for 17,869 absent PDFs and the done-set counted it, permanently burning them).
RETRYABLE_STATUSES = ("skip_unreadable", "skip_unreadable_text")

DDL = """
CREATE TABLE IF NOT EXISTS cc_docs (doc_id INTEGER PRIMARY KEY, isin TEXT, symbol TEXT, filed_at TEXT, status TEXT,
    model TEXT, key_name TEXT, chars INTEGER, in_tok INTEGER, out_tok INTEGER, cost_usd REAL, seconds REAL,
    checks_json TEXT, raw_json TEXT, error TEXT, run_at TEXT, priority INTEGER,
    period_discussed TEXT, period_q INTEGER, period_fy INTEGER, date_source TEXT);
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


# ---------------------------------------------------------------- text from chunks (--from-chunks)
HEADER_RE = re.compile(r"\A\[Metadata:[^\]\n]*\]\s*", re.I)


def strip_chunk_header(text):
    """Drop the '[Metadata: Symbol: ... | Date: ...]' header the chunker puts in front of every chunk."""
    return HEADER_RE.sub("", text or "", count=1)


def join_chunks(contents, max_overlap=200):
    """Stitch stored chunks back into one transcript, dropping the word overlap the chunker repeats.

    The chunker stores overlapping windows (512 tokens with 64 tokens of overlap), each prefixed with the same metadata
    header. `max_overlap` is a word cap well above 64 so a different chunk size still joins; when no exact suffix/prefix
    match is found the chunk is appended on a new line (a gap in the stored chunks stays visible instead of being
    silently glued)."""
    parts, tail = [], []
    for raw in contents:
        body = strip_chunk_header(raw or "").strip()
        if not body:
            continue
        words = body.split()
        k = 0
        cap = min(max_overlap, len(tail), len(words))
        for kk in range(cap, 0, -1):
            if tail[-kk:] == words[:kk]:
                k = kk
                break
        new = words[k:]
        if new:
            if parts:
                parts.append("\n" if k == 0 else " ")
            parts.append(" ".join(new))
        tail = (tail + new)[-max_overlap:]
    return "".join(parts)


def chunks_text(raw_doc_id, limit=None, main_db=None):
    """Transcript text from document_chunks, ordered by chunk_index, overlap-aware. Empty string when there are none."""
    con = sqlite3.connect(f"file:{main_db or MAIN_DB}?mode=ro", uri=True)
    try:
        rows = con.execute("SELECT content FROM document_chunks WHERE doc_id=? ORDER BY chunk_index",
                           (raw_doc_id,)).fetchall()
    finally:
        con.close()
    text = join_chunks([r[0] for r in rows])
    return text[:limit] if limit else text


# ---------------------------------------------------------------- date resolver for the 1,499 undated transcripts
# Every transcript's first page carries the call date ("Q1 FY27 Earnings Conference Call ... August 11, 2026",
# "11th August 2026", "held on 04-Jun—19", "dated 30.05.2019"). The crawl stamp (doc_date) overwrote the filing date
# on 1,499 rows, so the text is the only PIT-safe source left for them.
MONTHS = {m: i for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)}
_MONTH_RE = (r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|"
             r"aug(?:ust)?|sep(?:t|tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?")
_DMY_NAME = re.compile(rf"\b(?P<d>\d{{1,2}})(?:st|nd|rd|th)?[\s\-—–.,]+(?P<m>{_MONTH_RE})[\s\-—–.,]+(?P<y>\d{{2,4}})\b",
                       re.I)
_MDY_NAME = re.compile(rf"\b(?P<m>{_MONTH_RE})[\s\-—–.,]+(?P<d>\d{{1,2}})(?:st|nd|rd|th)?,?[\s\-—–.,]+"
                       rf"(?P<y>\d{{2,4}})\b", re.I)
_NUM_Y4 = re.compile(r"(?<!\d)(?P<a>\d{1,2})[-/.](?P<b>\d{1,2})[-/.](?P<y>\d{4})(?!\d)")
_NUM_Y2 = re.compile(r"(?<!\d)(?P<a>\d{1,2})[-/.](?P<b>\d{1,2})[-/.](?P<y>\d{2})(?!\d)")
DATE_PATTERNS = (_DMY_NAME, _MDY_NAME, _NUM_Y4, _NUM_Y2)
CALL_CUE = re.compile(r"\b(?:earnings?\s+(?:conference\s+)?call|conference\s+call|concall|analyst\s+call|"
                      r"investor\s+call|management\s+call|held\s+on|call\s+(?:was\s+)?held|"
                      r"call\s+took\s+place|took\s+place\s+on)\b", re.I)
TRANS_CUE = re.compile(r"\b(?:transcript|dated|post\s+announcement|meeting|earnings)\b", re.I)
LETTER_CUE = re.compile(r"\b(?:letter|circular|communication)\s+dated\b", re.I)


def _year(raw):
    y = int(raw)
    if y < 100:
        y = 2000 + y if y <= 40 else 1900 + y
    if not 2000 <= y <= dt.date.today().year + 1:
        raise ValueError(f"year {y}")
    return y


def _date_from_match(m):
    g = m.groupdict()
    if g.get("m"):
        return dt.date(_year(g["y"]), MONTHS[g["m"][:3].lower()], int(g["d"]))
    a, b = int(g["a"]), int(g["b"])
    # Indian transcripts write DD-MM-YYYY; fall back to MM-DD-YYYY only when the second number cannot be a month.
    day, mon = (b, a) if b > 12 and a <= 12 else (a, b)
    return dt.date(_year(g["y"]), mon, day)


def _as_date(value):
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def resolve_call_date(text, filed=None, crawl_date=None, today=None):
    """Parse the call date from the first ~3,000 chars. Returns (iso|None, date_source, confidence, note).

    `date_source` is `text_call_date` (a call cue sits next to the date), `text_dateline` (an explicit date without a
    call cue) or `text_unverified` (bare number, low confidence: parsed but NOT used). Sanity: the call cannot follow
    its filing time and must be within ~60 days of it; when only the crawl stamp is known it is used as an upper bound
    (the stamp is not a filing time: the backfill wrote 2026-08 for calls held in 2017-2019)."""
    head = strip_chunk_header(text or "")[:3000]
    best = None
    for rx in DATE_PATTERNS:
        for m in rx.finditer(head):
            try:
                d = _date_from_match(m)
            except ValueError:
                continue
            ctx = head[max(0, m.start() - 180):m.end() + 180]
            score = 4 if CALL_CUE.search(ctx) else 0
            score += 1 if TRANS_CUE.search(ctx) else 0
            score += 1 if m.start() < 400 else 0
            if LETTER_CUE.search(head[max(0, m.start() - 80):m.start()]):
                score -= 3
            cand = (score, -m.start(), d)
            if best is None or cand[:2] > best[:2]:
                best = cand
    if best is None:
        return None, "no_date", "none", "no date pattern in the first 3000 chars"
    score, _, d = best
    source = "text_call_date" if score >= 4 else ("text_dateline" if score >= 1 else "text_unverified")
    confidence = "high" if score >= 4 else ("medium" if score >= 1 else "low")
    today = today or dt.date.today()
    if d > today + dt.timedelta(days=1):
        return None, source + "_future", confidence, f"{d} is in the future"
    filed_d = _as_date(filed)
    if filed_d:
        if d > filed_d + dt.timedelta(days=1):
            return None, source + "_after_filing", confidence, f"call {d} after filing {filed_d}"
        if (filed_d - d).days > 60:
            return None, source + "_outside_60d", confidence, f"call {d} is {(filed_d - d).days}d before filing"
        return d.isoformat(), source, confidence, f"{d} is {(filed_d - d).days}d before filing"
    crawl_d = _as_date(crawl_date)
    if crawl_d and d > crawl_d + dt.timedelta(days=1):
        return None, source + "_after_crawl", confidence, f"call {d} after crawl stamp {crawl_d}"
    return d.isoformat(), source, confidence, "no trusted filing time; crawl date used as upper bound only"


# ---------------------------------------------------------------- queue
def _chunk_map(main):
    """corporate_documents.id -> raw_documents.doc_id for docs whose transcript text is stored as chunks.

    Prefer sha256 (the chunker's idempotency key); fall back to source_url (how repair_transcript_dates joins)."""
    by_sha = {sha: rid for rid, sha in main.execute(
        "SELECT doc_id, sha256_hash FROM raw_documents WHERE sha256_hash IS NOT NULL")}
    chunked = {rid for (rid,) in main.execute("SELECT DISTINCT doc_id FROM document_chunks")}
    by_url = {}
    for rid, url in main.execute("SELECT doc_id, source_url FROM raw_documents "
                                 "WHERE source_url IS NOT NULL AND source_url<>''"):
        if rid in chunked:
            by_url.setdefault(url, rid)
    return by_sha, by_url, chunked


def _item_text(item, limit=None):
    """(text, source) for a queue row: the PDF when it exists, else stored chunks. Raises UnreadableText."""
    path = item.get("path")
    if path and Path(path).exists():
        try:
            text = text_of(path, limit)
            if text.strip():
                return text, "pdf"
        except Exception:   # noqa: BLE001 - a broken PDF must not take the chunk fallback down
            pass
    cid = item.get("chunk_doc")
    if cid is not None:
        try:
            text = chunks_text(cid, limit, main_db=item.get("main_db"))
            if text.strip():
                return text, "chunks"
        except Exception:   # noqa: BLE001
            pass
    raise UnreadableText(f"no readable text (pdf={path!r} exists={bool(path and Path(path).exists())}, "
                         f"chunk_doc={cid})")


class UnreadableText(Exception):
    pass


def _resolved_date(item, main_db):
    """Date for a doc that has neither bse_dissem_ts / publication_date / call_date. None when not confident."""
    try:
        text, _ = _item_text(item, limit=3000)
    except UnreadableText:
        return None
    iso, source, confidence, note = resolve_call_date(text, crawl_date=item.get("doc_date"))
    if iso and confidence in ("high", "medium"):
        item["date_note"] = note
        return iso, source
    item["date_note"] = f"{source}/{confidence}: {note}"
    return None


def queue(out, only_tg=True, from_chunks=False, strict_date=False, since=None, main_db=None):
    since = since or SINCE
    main = sqlite3.connect(f"file:{main_db or MAIN_DB}?mode=ro", uri=True)
    raw = main.execute("""SELECT id, isin, symbol, bse_dissem_ts, publication_date, call_date, doc_date,
                                 local_file_path, sha256_hash, source_url
                          FROM corporate_documents WHERE doc_type='CONCALL_TRANSCRIPT'""").fetchall()
    by_sha, by_url, chunked = _chunk_map(main)
    main.close()
    pr = {r["isin"]: n for n, r in enumerate(json.loads(PRIORITY.read_text(encoding="utf-8")))} if PRIORITY.exists() else {}
    allowed = set(json.loads(TG_ISINS.read_text(encoding="utf-8"))) if only_tg and TG_ISINS.exists() else None
    done = {d for (d,) in out.execute(
        "SELECT doc_id FROM cc_docs WHERE status='ok' OR (status LIKE 'skip_%' AND status NOT IN (?,?))",
        RETRYABLE_STATUSES)}
    q429 = {d for (d,) in out.execute("SELECT doc_id FROM cc_docs WHERE status='queued_429'")}
    if REREAD_MODELS:   # re-read docs these readers stored under an older prompt (2026-10-20: v2 -> v3)
        tag = PROMPT_FILE.replace("prompt_", "").replace(".md", "")
        old = {d for d, m, ck in out.execute("SELECT doc_id, model, checks_json FROM cc_docs WHERE status='ok'")
               if m in REREAD_MODELS and (json.loads(ck or "{}").get("prompt") or "v2") != tag}
        done -= old

    rows = []
    for did, isin, symbol, bse, pub, call, doc_date, path, sha, url in raw:
        if allowed is not None and isin not in allowed:
            continue
        chunk_doc = by_sha.get(sha) if sha else None
        if chunk_doc not in chunked:
            chunk_doc = by_url.get(url) if url else None
            if chunk_doc not in chunked:
                chunk_doc = None
        path_ok = bool(path and Path(path).exists())
        # A doc with neither a local file nor stored chunks is not runnable yet: leaving it out (not marking it done)
        # lets it enter the queue when its PDF lands. With --from-chunks this is the normal "PDF missing" case.
        if from_chunks and not (path_ok or chunk_doc is not None):
            continue
        if not from_chunks and not path:
            continue
        filed = bse or pub or call
        date_source = ("bse_dissem_ts" if bse else "publication_date" if pub else "call_date" if call else None)
        item = {"id": did, "isin": isin, "symbol": symbol, "filed": filed, "date_source": date_source,
                "path": path, "sha": sha, "chunk_doc": chunk_doc, "doc_date": doc_date,
                "main_db": main_db or MAIN_DB}
        if not filed:
            resolved = _resolved_date(item, main_db)
            if not resolved:
                continue        # no point-in-time date: strict ordering has nothing to sort it by
            item["filed"], item["date_source"] = resolved
        if (item["filed"] or "")[:10] < since:
            continue
        item["prio"] = 0 if isin in pr else 1
        rows.append(item)

    # duplicates decided oldest-first: the EARLIEST public filing of a PDF is the one we keep (point-in-time); a later
    # re-filing of the same file (same sha256) or a second filing on the same ISIN + day is skipped
    dup_ids, seen_sha, seen_day = set(), set(), set()
    for r in sorted(rows, key=lambda r: (r["filed"] or "", r["id"])):
        key_day = (r["isin"], (r["filed"] or "")[:10])
        if (r["sha"] and r["sha"] in seen_sha) or key_day in seen_day:
            dup_ids.add(r["id"])
        seen_day.add(key_day)
        if r["sha"]:
            seen_sha.add(r["sha"])
    if strict_date:
        rows.sort(key=lambda r: (r["filed"] or "", r["id"]), reverse=True)
    else:
        rows.sort(key=lambda r: (0 if r["id"] in q429 else 1, 0 if r["isin"] in pr else 1,
                                 "".join(chr(255 - ord(c)) for c in (r["filed"] or ""))))
    for r in rows:
        r["dup"] = r["id"] in dup_ids
    return [r for r in rows if r["id"] not in done]


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


def text_of(path, limit=None):
    import pymupdf
    out, n = [], 0
    with pymupdf.open(path) as d:
        for page in d:
            t = page.get_text()
            out.append(t)
            n += len(t)
            if limit and n >= limit:
                break
    text = "\n".join(out)
    return text[:limit] if limit else text


def prompt(symbol, filed, text):
    p = (PILOT / PROMPT_FILE).read_text(encoding="utf-8")
    return p.replace("{company}", symbol or "").replace("{symbol}", symbol or "").replace("{date}", (filed or "")[:10]).replace("{text}", text)


def _ensure_column(con, table, column, decl):
    cols = {r[1] for r in con.execute(f"PRAGMA table_info({table})")}
    if column not in cols:
        con.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


def save(out_path, row):
    with lock:
        con = sqlite3.connect(out_path, timeout=120)
        with con:
            con.execute("INSERT OR REPLACE INTO cc_docs (doc_id,isin,symbol,filed_at,status,model,key_name,chars,in_tok,"
                        "out_tok,cost_usd,seconds,checks_json,raw_json,error,run_at,priority,period_discussed,period_q,"
                        "period_fy,date_source) VALUES (:doc_id,:isin,:symbol,:filed_at,:status,:model,:key_name,:chars,"
                        ":in_tok,:out_tok,:cost_usd,:seconds,:checks_json,:raw_json,:error,:run_at,:priority,"
                        ":period_discussed,:period_q,:period_fy,:date_source)",
                        {"period_discussed": None, "period_q": None, "period_fy": None, "date_source": None, **row})
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
    con.executescript(DDL)
    _ensure_column(con, "cc_docs", "date_source", "TEXT")
    con.commit()
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
# Upstream 429 = one LANE is rate-limited (Beam 2026-10-20 11:52-20:00+ on Go; Kilo has its own gateway and its own
# bench). Shivam 2026-10-20: never turn a 429 into a permanent 'error'; while a lane is down its workers wait and
# exactly ONE worker taps it with a single call every LANE_TAP_S; the first answer reopens that lane only.
LANE_TAP_S = 900


def make_lane(key_name, model, index, env=None):
    env = env or ar.user_env()
    key = env.get(key_name, "")
    base = model.split("~")[0]
    url = KILO_URL if base.startswith(("reflection/", "kilo/")) else GO_URL
    return {"name": f"lane{index}:{key_name}:{base}", "key_name": key_name, "model": model, "url": url,
            "session": session_id("concall", model, key, lane_no=index),
            "down": False, "until": 0.0, "probing": False,
            "docs": 0, "ok": 0, "skips": 0, "errors": 0, "n429": 0, "seconds": 0.0, "items": 0}


def lane_gate(lane):
    """Block while this lane is down; return True when this worker is the one allowed to send the probe call."""
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


def lane_result(lane, ok, probe):
    with lock:
        if ok:
            if lane["down"]:
                log(f"{lane['name']} answered again: its workers resume")
            lane.update(down=False, probing=False)
        else:   # 429
            first = not lane["down"]
            lane.update(down=True, until=time.time() + LANE_TAP_S, probing=False)
            if first or probe:
                log(f"{lane['name']} 429 ({'tap failed' if probe else 'lane down'}): next single tap in "
                    f"{LANE_TAP_S // 60} min")


def work(item, lane, out_path):
    doc_id, isin, symbol, filed = item["id"], item["isin"], item["symbol"], item["filed"]
    base = {"doc_id": doc_id, "isin": isin, "symbol": symbol, "filed_at": filed, "model": lane["model"],
            "key_name": lane["key_name"], "chars": None, "in_tok": None, "out_tok": None, "cost_usd": 0.0,
            "seconds": None, "checks_json": None, "raw_json": None, "error": None,
            "date_source": item.get("date_source"),
            "run_at": dt.datetime.now().isoformat(timespec="seconds"), "priority": item.get("prio", 1)}
    if item.get("dup"):
        save(out_path, {**base, "status": "skip_duplicate"})
        return {"status": "skip_duplicate", "lane": lane["name"], "seconds": 0.0, "items": 0, "n429": 0}
    try:
        text, text_src = _item_text(item)
    except UnreadableText as e:
        # RETRYABLE: neither the PDF nor the chunks held text right now. Never a terminal skip (2026-10-24 bug fix).
        save(out_path, {**base, "status": "skip_unreadable_text", "error": str(e)[:300]})
        return {"status": "skip_unreadable_text", "lane": lane["name"], "seconds": 0.0, "items": 0, "n429": 0}
    base["chars"] = len(text.strip())
    if base["chars"] < MIN_CHARS:
        save(out_path, {**base, "status": "skip_cover_letter"})
        return {"status": "skip_cover_letter", "lane": lane["name"], "seconds": 0.0, "items": 0, "n429": 0}
    env = ar.user_env()
    key = env.get(lane["key_name"], "")
    if not key:
        raise SystemExit(f"lane {lane['name']}: {lane['key_name']} is not set")
    attempt = 0
    n429 = 0
    last = "4 broken-JSON answers"   # 2026-10-20: unset when every attempt was error_json -> UnboundLocalError killed the run
    while attempt < 4:
        attempt += 1
        if lane["model"].split("~")[0] not in FREE_MODELS:   # free readers: no spend window, no peak pause
            wait_budget(out_path)
        if bench.get(lane["key_name"], 0) > time.time():
            time.sleep(bench[lane["key_name"]] - time.time())
        probe = lane_gate(lane)
        t0 = time.time()
        try:
            out, it, ot = call_go(lane["model"], prompt(symbol, filed, text), key, session=lane["session"],
                                  url=lane["url"])
            lane_result(lane, True, probe)
            cost = 0.0 if lane["model"].split("~")[0] in FREE_MODELS else ((it or 0) * PRICE_IN + (ot or 0) * PRICE_OUT) / 1e6
            try:
                data = parse_json(out)
            except Exception as e:
                save(out_path, {**base, "status": "error_json", "in_tok": it, "out_tok": ot,
                                "cost_usd": cost, "seconds": round(time.time() - t0, 1), "error": str(e)[:200],
                                "run_at": dt.datetime.now().isoformat(timespec="seconds")})
                continue
            data, checks = machine_check(text, data)
            checks["prompt"] = PROMPT_FILE.replace("prompt_", "").replace(".md", "")
            checks["text_source"] = text_src
            items = sum(len(data.get(k) or []) for k in LISTS)
            pq = parse_period(data.get("period_discussed"))
            save(out_path, {**base, "status": "ok", "period_discussed": data.get("period_discussed"),
                            "period_q": pq[0] if pq else None, "period_fy": pq[1] if pq else None,
                            "in_tok": it, "out_tok": ot, "cost_usd": cost,
                            "seconds": round(time.time() - t0, 1), "checks_json": json.dumps(checks),
                            "raw_json": json.dumps(data, ensure_ascii=False),
                            "run_at": dt.datetime.now().isoformat(timespec="seconds")})
            return {"status": "ok", "lane": lane["name"], "seconds": round(time.time() - t0, 1),
                    "items": items, "n429": n429}
        except Exception as e:
            msg = str(e)
            if "GoUsageLimitError" in msg:
                # Go's 5-hour / weekly window is spent: wait for it to roll, without using up this doc's attempts
                # (2026-10-19 00:06: four 30-min retries would have turned the rest of the queue into errors)
                bench[lane["key_name"]] = time.time() + 900
                attempt -= 1
                with lock:
                    if time.time() - bench.get("_logged", 0) > 600:
                        bench["_logged"] = time.time(); log(f"{lane['key_name']} Go usage limit reached; waiting 15 min steps")
                continue
            if "429" in msg:
                lane_result(lane, False, probe)
                n429 += 1
                attempt -= 1     # a rate limit is not the doc's fault: never spend its attempts on it
                continue
            if probe:
                with lock:
                    lane["probing"] = False
            time.sleep(20)
            last = msg
    save(out_path, {**base, "status": "error", "error": last[:300],
                    "run_at": dt.datetime.now().isoformat(timespec="seconds")})
    return {"status": "error", "lane": lane["name"], "seconds": round(time.time() - t0, 1), "items": 0, "n429": n429}


def _set_caps(week, five_h):
    global WEEK_CAP, FIVE_H_CAP
    WEEK_CAP, FIVE_H_CAP = week, five_h


def _lanes(spec, model, keys):
    """--lanes 'KEY_ENV=model,KEY_ENV=model' -> lane dicts; else one lane per --keys entry on --model."""
    pairs = []
    if spec:
        for part in spec.split(","):
            if not part.strip():
                continue
            if "=" not in part:
                raise SystemExit(f"--lanes entry {part!r} is not KEY_ENV=model")
            key, mid = part.split("=", 1)
            pairs.append((key.strip(), mid.strip()))
    else:
        pairs = [(k, model) for k in keys]
    env = ar.user_env()
    missing = [k for k, _ in pairs if not env.get(k)]
    if missing:
        raise SystemExit(f"lane key(s) not set: {', '.join(missing)}")
    return [make_lane(k, m, i, env) for i, (k, m) in enumerate(pairs)]


def main():
    global MODEL, SINCE, LOG, PROMPT_FILE, REREAD_MODELS
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--sample", type=int, default=0, help="random validation batch of N docs (seeded by N)")
    ap.add_argument("--keys", default="OPENCODE_GO_API_KEY_2")
    ap.add_argument("--lanes", default="", help="KEY_ENV=model[,KEY_ENV=model...] (interleaved lanes)")
    ap.add_argument("--week-cap", type=float, default=WEEK_CAP,
                    help="our own 7-day spend guard; Go's weekly limit resets on a fixed day, so set this high and let "
                         "Go's 429 (bench 30 min) enforce the week when a reset is due")
    ap.add_argument("--five-h-cap", type=float, default=FIVE_H_CAP)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--all-companies", action="store_true", help="ignore the Telegram company list (off by default)")
    ap.add_argument("--renormalise", action="store_true", help="re-save stored answers with current label rules; no API")
    # 2026-10-20 (Shivam): the rest of the transcripts (all years, all companies) go to the FREE readers, on both
    # gateways; DeepSeek checks their output. Shards split the queue so two readers never read the same transcript.
    ap.add_argument("--model", default=MODEL, help="Go model id, '<id>~<effort>' for reasoning effort")
    ap.add_argument("--since", default=SINCE, help="earliest filing date to read")
    ap.add_argument("--shard", default="", help="'r1,r2/n': only docs with doc_id %% n in {r1,r2}")
    ap.add_argument("--max-out", type=int, default=32000, help="output-token cap per call")
    ap.add_argument("--prompt", default=PROMPT_FILE, help="prompt file in data/concall_pilot (v3 from 2026-10-20)")
    ap.add_argument("--reread-models", default="", help="re-read docs these models stored under another prompt")
    # 2026-10-24: the 17,869 concall PDFs are not on this laptop; 9,954 unread transcripts already sit in
    # document_chunks. --from-chunks feeds the reader from those chunks; --strict-date is the latest -> oldest queue.
    ap.add_argument("--from-chunks", action="store_true", help="read document_chunks when the PDF is not on disk")
    ap.add_argument("--strict-date", action="store_true",
                    help="strict newest -> oldest by real call/filing date (drops PEAD and queued_429-first sort)")
    a = ap.parse_args()
    MODEL, SINCE, PROMPT_FILE = a.model, a.since, a.prompt
    REREAD_MODELS = {m for m in a.reread_models.split(",") if m}
    lanes = _lanes(a.lanes, a.model, [k.strip() for k in a.keys.split(",") if k.strip()])
    LOG = ROOT / ("reality_engine/data/logs/concall_lanes.log" if len(lanes) > 1 else
                  f"reality_engine/data/logs/concall_{lanes[0]['model'].split('~')[0].replace('/', '_')}.log")
    from reality_engine.scripts import concall_pilot
    concall_pilot.MAX_OUT = a.max_out
    _set_caps(a.week_cap, a.five_h_cap)
    if a.renormalise:
        return renormalise(OUT_DB)
    out = sqlite3.connect(OUT_DB, timeout=120)
    out.executescript(DDL)
    _ensure_column(out, "cc_docs", "date_source", "TEXT")
    out.commit()
    todo = queue(out, only_tg=not a.all_companies, from_chunks=a.from_chunks, strict_date=a.strict_date,
                 since=a.since)
    if a.shard:
        res, n = a.shard.split("/")
        keep = {int(r) for r in res.split(",")}
        todo = [t for t in todo if t["id"] % int(n) in keep]
    if a.sample:   # validation batch: random docs across the year and both priority groups, duplicates included
        import random
        random.Random(a.sample).shuffle(todo)
        todo = todo[:a.sample]
    if a.limit:
        todo = todo[:a.limit]
    real = [t for t in todo if not t["dup"]]
    dates = [t["date_source"] for t in todo if t.get("date_source", "").startswith("text_")]
    log(f"queue {len(todo)} (duplicates {len(todo) - len(real)}, PEAD-first {sum(1 for t in todo if t['prio'] == 0)}, "
        f"text-dated {len(dates)}); lanes {[l['name'] for l in lanes]}; "
        f"spent 5h ${spent(out, 5):.2f}, 7d ${spent(out, 168):.2f}")
    out.close()
    if a.dry_run:
        for t in todo[:10]:
            log(f"  {t['filed'][:10] if t['filed'] else '?'} {t['symbol']:<14} doc {t['id']} "
                f"source={t['date_source']} chunk={t['chunk_doc']} dup={int(t['dup'])}")
        for i, t in enumerate(todo):
            lanes[i % len(lanes)]["docs"] += 1
        log("dry-run lane split: " + ", ".join(f"{l['name']}={l['docs']}" for l in lanes))
        return
    jobs = [(t, lanes[i % len(lanes)]) for i, t in enumerate(todo)]
    stats = {l["name"]: {"docs": 0, "ok": 0, "items": 0, "seconds": 0.0, "n429": 0, "by_status": {}} for l in lanes}
    n = {}
    with cf.ThreadPoolExecutor(a.workers) as ex:
        for i, r in enumerate(ex.map(lambda j: work(j[0], j[1], OUT_DB), jobs), 1):
            n[r["status"]] = n.get(r["status"], 0) + 1
            s = stats[r["lane"]]
            s["docs"] += 1
            s["ok"] += r["status"] == "ok"
            s["items"] += r["items"]
            s["seconds"] += r["seconds"]
            s["n429"] += r["n429"]
            b = s["by_status"]
            b[r["status"]] = b.get(r["status"], 0) + 1
            if i % 25 == 0:
                con = sqlite3.connect(OUT_DB, timeout=60)
                log(f"[{i}/{len(todo)}] {n} | spent 5h ${spent(con, 5):.2f} 7d ${spent(con, 168):.2f}")
                con.close()
    for l in lanes:
        s = stats[l["name"]]
        log(f"LANE {l['name']}: docs={s['docs']} ok={s['ok']} items={s['items']} "
            f"sec/doc={s['seconds'] / max(1, s['docs']):.1f} 429={s['n429']} status={s['by_status']}")
    log(f"RUN_COMPLETE {n}")


if __name__ == "__main__":
    main()
