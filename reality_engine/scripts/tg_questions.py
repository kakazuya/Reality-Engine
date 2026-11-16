"""T-217: investor-question bank for the Telegram build queue (Shivam, 16 Nov 2026).

``python -m reality_engine.scripts.tg_questions harvest --only 1,2,3``   one agy run per company, then load
``python -m reality_engine.scripts.tg_questions load --raw <dir>``        (re)load raw JSON files, verify the links
``python -m reality_engine.scripts.tg_questions check --db <db> --min-companies 93``
``python -m reality_engine.scripts.tg_questions export --out <xlsx>``

Per company a web model (default ``gemini-3.8-flash-medium`` through ``answer/agy_call.run_agy``) searches the web
and YouTube for the questions investors really ask, then learns the company's own business and writes grounded
variants.  Only the company NAME and exchange symbol leave this machine (Shivam's approval covers names; nothing
else from the Telegram list is sent).  Each run has a working folder of its own
(``<root>/questions_raw/work/<isin>``, never the repo); the script keeps its JSON file as
``<root>/questions_raw/<isin>.json`` and the event logs in ``<root>/questions_logs``.

What the script (not the model) decides:
* **verified**: a ``found`` question keeps that kind only when its source page loads and names the company; else it
  is stored as ``found_unverified`` (search tools return summaries, and links taken from them were found invented,
  T-130).
* **grounded**: a ``created`` question without a ``grounding_fact`` and a ``data_needed`` is dropped and counted.
* **frozen**: half of each company's questions, per kind, chosen by hash, never drive a fix (T-172 rule).

The bank is private: ``questions.db`` and the Excel export live on D:, and no company list is written in the repo.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
import sqlite3
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path("D:/RealityEngine/tg_build")
DB = ROOT / "questions.db"
RAW = ROOT / "questions_raw"
QUEUE = ROOT / "build_queue.csv"
MODEL = "gemini-3.8-flash-medium"
THEMES = ("transcript", "revenue_sources", "segments", "geography", "integration_pivot", "forward_profitability",
          "next_two_quarters", "long_vs_short", "accounting", "other")
MIN_QUESTIONS = 20          # a company counts as covered from this many stored questions
MIN_FOUND = 5               # ... of which this many found on a page that loaded and names the company
STOP_WORDS = {"limited", "ltd", "india", "indian", "industries", "company", "corporation", "and", "the", "sons",
              "enterprises", "international", "technologies", "services", "solutions", "of", "co", "pvt", "private"}

DDL = """
CREATE TABLE IF NOT EXISTS question (
    id INTEGER PRIMARY KEY, isin TEXT NOT NULL, symbol TEXT, company TEXT, question TEXT NOT NULL, theme TEXT,
    kind TEXT NOT NULL, source_url TEXT, source_title TEXT, http_status INTEGER, grounding_fact TEXT,
    data_needed TEXT, model TEXT, fetched_at TEXT, frozen INTEGER NOT NULL DEFAULT 0, qhash TEXT NOT NULL,
    word_overlap REAL,
    UNIQUE (isin, qhash));
CREATE TABLE IF NOT EXISTS business_fact (isin TEXT NOT NULL, fact TEXT NOT NULL, source_url TEXT,
    UNIQUE (isin, fact));
CREATE TABLE IF NOT EXISTS harvest_run (isin TEXT, symbol TEXT, model TEXT, started_at TEXT, seconds REAL,
    ok INTEGER, error TEXT, tool_calls INTEGER, tokens TEXT, log TEXT, loaded TEXT);
"""

PROMPT = """You are collecting investor questions about one listed Indian company. Web research only: do not answer
the questions, give no price targets, edit no file except the one output file named at the end.

Company: {company} (exchange symbol {symbol})

Step 1. FOUND questions. Search the web and YouTube for questions real investors and analysts ask about THIS
company. Search at least: "{company} share analysis", "{company} concall questions", "{company} investor concerns",
"{symbol} valuepickr", "{company} reddit", "{company} moneycontrol forum", and on YouTube "{company} share analysis",
"{company} results analysis" (video titles, descriptions, chapters, visible comments). Open the page before you keep
a question from it. A YouTube link must be the video's own address (https://www.youtube.com/watch?v= and its
11-character id), never a search-result or redirect link: open the video and copy its final address. Earnings-call
transcripts on the company's or the exchange's website count: an analyst's question there is a found question.
Keep 15 to 25 questions, verbatim (translate Hindi or Hinglish to English), each with the exact
URL of the page you opened and that page's title. A statement that implies a question may be kept as the question
it implies. Fewer is fine when the web has fewer: never invent a found question or a link.

Step 2. BUSINESS facts. From the company's own website, latest results, investor presentation or annual report,
write 6 to 10 facts that define its business: its segments, main products or services, plants or sites, main
customers or markets, exports, order book or capacity, any recent pivot or integration. Each with the URL you read.

Step 3. CREATED questions. Write 20 to 30 more questions an investor should ask about this company: about half
conceptual (how the business earns and what drives it) and half detailed accounting (specific lines, ratios,
working capital, segment results, cash flow). Every created question must fit THIS company's own business: an
airline is asked about revenue per seat, never about hospital bed cost. Each must quote, in "grounding_fact", the
business fact from step 2 that makes it relevant. Cover these themes across the set:
transcript (what management said on a call), revenue_sources, segments (segment revenue and segment results),
geography (geographic split), integration_pivot (backward or forward integration, or a pivot),
forward_profitability (what tells an investor the coming profitability and revenue), next_two_quarters (do the next
two quarters look good or must one wait), long_vs_short (long-term or short-term bet), accounting.

For EVERY question (found and created) fill "data_needed": what a database must hold to answer it, as
"<document type>: <field or passage>", for example "quarterly results: segment revenue and segment result",
"concall transcript: management comment on order inflow", "shareholding pattern: promoter pledge",
"annual report: related-party transactions note", "price history: 200-day average".

Output. Write ONE file, UTF-8 JSON, at exactly this path: {out_path}
{{"company": "{company}", "symbol": "{symbol}",
 "business_facts": [{{"fact": "...", "source_url": "..."}}],
 "questions": [{{"question": "...", "kind": "found" or "created", "theme": one of {themes},
   "source_url": "... (found only)", "source_title": "... (found only)",
   "grounding_fact": "... (created only)", "data_needed": "..."}}]}}
Then reply with one line: the counts of found and created questions and any site you could not open.
"""


def connect(db: Path) -> sqlite3.Connection:
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db, timeout=60)
    conn.executescript(DDL)
    if "word_overlap" not in {r[1] for r in conn.execute("PRAGMA table_info(question)")}:
        conn.execute("ALTER TABLE question ADD COLUMN word_overlap REAL")
    return conn


def read_queue(path: Path) -> list[dict]:
    """The build queue in file order, without the demo ISINs; each row gains its 1-based position."""
    with open(path, encoding="utf-8-sig", newline="") as fh:
        rows = [r for r in csv.DictReader(fh) if not str(r.get("isin", "")).startswith("INE_AUTO_")]
    for position, row in enumerate(rows, 1):
        row["position"] = position
    return rows


def name_tokens(company: str, symbol: str) -> list[str]:
    """Words of the company name that identify it on a page (the symbol too)."""
    words = [w for w in re.findall(r"[a-z0-9]+", company.lower()) if len(w) > 2 and w not in STOP_WORDS]
    return [*words[:3], symbol.lower()] if symbol else words[:3]


def page_names_company(text: str, company: str, symbol: str) -> bool:
    low = text.lower()
    return any(token in low for token in name_tokens(company, symbol))


def fetch(url: str, timeout: float = 20.0) -> tuple[int, str]:
    """``(http status, page text)``; status 0 when the page could not be fetched."""
    if not re.match(r"https?://", url or ""):
        return 0, ""
    if "reddit.com" in url and not url.rstrip("/").endswith(".json"):
        url = url.split("?")[0].rstrip("/") + ".json"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "en"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return int(resp.status), resp.read(2_000_000).decode("utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001 - any fetch failure means "not verified", never a crash
        return int(getattr(exc, "code", 0) or 0), ""


def page_is_document(url: str, page: str) -> bool:
    return url.lower().split("?")[0].endswith(".pdf") or page.startswith("%PDF")


def url_names_company(url: str, company: str, symbol: str) -> bool:
    host = re.sub(r"^https?://(www\.)?", "", url.lower()).split("/")[0]
    return any(token in host for token in name_tokens(company, symbol) if len(token) > 3)


def word_overlap(question: str, page: str) -> float | None:
    """Share of the question's longer words that the page text holds (a hint for the hand-read, not a gate)."""
    words = {w for w in re.findall(r"[a-z]{5,}", question.lower())}
    if not words or not page:
        return None
    low = page.lower()
    return round(sum(1 for w in words if w in low) / len(words), 2)


def qhash(question: str) -> str:
    return hashlib.sha1(re.sub(r"[^a-z0-9]+", " ", question.lower()).strip().encode()).hexdigest()[:16]


def clean_rows(payload: dict, company: str, symbol: str, fetcher=fetch) -> tuple[list[dict], dict]:
    """Validate one company's raw JSON: ``(rows to store, counts of what was dropped or relabelled)``."""
    stats = {"found": 0, "found_unverified": 0, "created": 0, "dropped_ungrounded": 0, "dropped_empty": 0,
             "dropped_duplicate": 0}
    raw = [q for q in (payload.get("questions") or []) if isinstance(q, dict)]
    urls = sorted({str(q.get("source_url") or "").strip() for q in raw if str(q.get("kind")) == "found"} - {""})
    with ThreadPoolExecutor(max_workers=6) as pool:
        pages = dict(zip(urls, pool.map(fetcher, urls)))
    rows, seen = [], set()
    for q in raw:
        text = " ".join(str(q.get("question") or "").split())
        kind = str(q.get("kind") or "").strip().lower()
        if len(text) < 12 or kind not in ("found", "created"):
            stats["dropped_empty"] += 1
            continue
        key = qhash(text)
        if key in seen:
            stats["dropped_duplicate"] += 1
            continue
        theme = str(q.get("theme") or "other").strip().lower()
        row = {"question": text, "kind": kind, "theme": theme if theme in THEMES else "other", "qhash": key,
               "source_url": None, "source_title": None, "http_status": None, "word_overlap": None,
               "grounding_fact": " ".join(str(q.get("grounding_fact") or "").split()) or None,
               "data_needed": " ".join(str(q.get("data_needed") or "").split()) or None}
        if kind == "created":
            if not row["grounding_fact"] or not row["data_needed"]:
                stats["dropped_ungrounded"] += 1
                continue
        else:
            url = str(q.get("source_url") or "").strip()
            status, page = pages.get(url, (0, ""))
            row.update(source_url=url or None, source_title=str(q.get("source_title") or "").strip() or None,
                       http_status=status, word_overlap=word_overlap(text, page))
            # a PDF's bytes are not text: a document on the company's own site is taken on its address
            named = (url_names_company(url, company, symbol) if page_is_document(url, page)
                     else page_names_company(page, company, symbol))
            if not (status == 200 and named):
                row["kind"] = "found_unverified"
        seen.add(key)
        stats[row["kind"]] += 1
        rows.append(row)
    return rows, stats


def freeze_half(rows: list[dict]) -> None:
    """Mark every second question of each kind, in hash order, as frozen (deterministic, T-172)."""
    for kind in {r["kind"] for r in rows}:
        for i, row in enumerate(sorted((r for r in rows if r["kind"] == kind), key=lambda r: r["qhash"])):
            row["frozen"] = i % 2
    for row in rows:
        row.setdefault("frozen", 0)


def load_company(conn: sqlite3.Connection, entry: dict, payload: dict, model: str, fetcher=fetch) -> dict:
    """Replace one company's questions with the validated rows of ``payload``."""
    isin, symbol, company = entry["isin"], entry.get("symbol") or "", entry.get("company") or ""
    rows, stats = clean_rows(payload, company, symbol, fetcher)
    freeze_half(rows)
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    with conn:
        conn.execute("DELETE FROM question WHERE isin=?", (isin,))
        conn.execute("DELETE FROM business_fact WHERE isin=?", (isin,))
        conn.executemany(
            "INSERT INTO question (isin, symbol, company, question, theme, kind, source_url, source_title, "
            "http_status, grounding_fact, data_needed, model, fetched_at, frozen, qhash, word_overlap) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [(isin, symbol, company, r["question"], r["theme"], r["kind"], r["source_url"], r["source_title"],
              r["http_status"], r["grounding_fact"], r["data_needed"], model, now, r["frozen"], r["qhash"],
              r["word_overlap"])
             for r in rows])
        conn.executemany("INSERT OR IGNORE INTO business_fact (isin, fact, source_url) VALUES (?,?,?)",
                         [(isin, " ".join(str(f.get("fact") or "").split()), str(f.get("source_url") or "") or None)
                          for f in (payload.get("business_facts") or []) if isinstance(f, dict) and f.get("fact")])
    return stats


def read_payload(path: Path) -> dict | None:
    try:
        text = path.read_text(encoding="utf-8-sig", errors="replace").strip()
    except OSError:
        return None
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        data = json.loads(text)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def harvest_one(entry: dict, raw: Path, model: str, timeout: int, runner=None) -> dict:
    """One agy run for one company, in a working folder of its own.

    The model runs in ``<raw>/work/<isin>/`` and writes ``<isin>.json`` there; the script then moves that file to
    ``<raw>/<isin>.json``.  A run never sees another company's file or the logs (``<raw>/../questions_logs``): on
    16 Nov one run tidied the shared folder and deleted the log and fifteen other companies' raw files."""
    from reality_engine.answer import agy_call

    work = raw / "work" / entry["isin"]
    work.mkdir(parents=True, exist_ok=True)
    out_path = work / f"{entry['isin']}.json"
    out_path.unlink(missing_ok=True)
    prompt = PROMPT.format(company=entry["company"].title(), symbol=entry["symbol"],
                           out_path=out_path.as_posix(), themes=", ".join(THEMES))
    run = runner or agy_call.run_agy
    started = time.strftime("%Y-%m-%dT%H:%M:%S")
    reply = run(prompt, model, cwd=work, timeout=timeout,
                log_path=raw.parent / "questions_logs" / f"{entry['isin']}.jsonl")
    payload = read_payload(out_path)
    kept = raw / f"{entry['isin']}.json"
    if payload is not None:
        shutil.copy2(out_path, kept)
    shutil.rmtree(work, ignore_errors=True)
    return {"isin": entry["isin"], "symbol": entry["symbol"], "started_at": started, "reply": reply,
            "payload": payload, "out_path": str(kept)}


def cmd_harvest(args: argparse.Namespace) -> int:
    queue = read_queue(Path(args.queue))
    wanted = {int(x) for x in args.only.split(",")} if args.only else None
    conn = connect(Path(args.db))
    done = {r[0] for r in conn.execute("SELECT DISTINCT isin FROM question")}
    todo = [e for e in queue if (wanted is None or e["position"] in wanted) and (args.force or e["isin"] not in done)]
    if args.limit:
        todo = todo[: args.limit]
    raw = Path(args.raw)
    raw.mkdir(parents=True, exist_ok=True)
    print(f"harvest: {len(todo)} companies, model {args.model}, {args.workers} at a time", flush=True)
    failed = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for result in pool.map(lambda e: harvest_one(e, raw, args.model, args.timeout), todo):
            entry = next(e for e in todo if e["isin"] == result["isin"])
            reply, payload = result["reply"], result["payload"]
            stats = load_company(conn, entry, payload, args.model) if payload else {}
            error = "" if payload else (reply.get("error") or "no JSON file written")
            failed += 0 if payload else 1
            with conn:
                conn.execute("INSERT INTO harvest_run VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                             (entry["isin"], entry["symbol"], args.model, result["started_at"],
                              reply.get("seconds"), int(bool(payload)), error, reply.get("tool_calls"),
                              json.dumps(reply.get("tokens") or {}), reply.get("log"), json.dumps(stats)))
            print(f"  q{entry['position']:03d} {'ok ' if payload else 'FAIL'} {reply.get('seconds', 0):>6.0f}s "
                  f"tools={reply.get('tool_calls', 0)} {json.dumps(stats) if payload else error}", flush=True)
    conn.close()
    return 1 if failed else 0


def cmd_load(args: argparse.Namespace) -> int:
    by_isin = {e["isin"]: e for e in read_queue(Path(args.queue))}
    conn = connect(Path(args.db))
    for path in sorted(Path(args.raw).glob("*.json")):
        entry, payload = by_isin.get(path.stem), read_payload(path)
        if not entry or not payload:
            print(f"  skip {path.name}: {'not in the queue' if not entry else 'unreadable JSON'}")
            continue
        print(f"  q{entry['position']:03d} {json.dumps(load_company(conn, entry, payload, args.model))}", flush=True)
    conn.close()
    return 0


def summarise(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT isin, COUNT(*), SUM(kind='found'), SUM(kind='found_unverified'), SUM(kind='created'), "
        "SUM(frozen), COUNT(DISTINCT theme), SUM(data_needed IS NULL) FROM question GROUP BY isin").fetchall()
    return [{"isin": r[0], "total": r[1], "found": r[2], "found_unverified": r[3], "created": r[4], "frozen": r[5],
             "themes": r[6], "no_data_needed": r[7],
             "ok": r[1] >= MIN_QUESTIONS and r[2] >= MIN_FOUND} for r in rows]


def cmd_check(args: argparse.Namespace) -> int:
    conn = connect(Path(args.db))
    per = summarise(conn)
    position = {e["isin"]: e["position"] for e in read_queue(Path(args.queue))} if Path(args.queue).is_file() else {}
    conn.close()
    good = sum(1 for p in per if p["ok"])
    for p in sorted(per, key=lambda p: position.get(p["isin"], 999)):
        print(f"  q{position.get(p['isin'], 0):03d} total={p['total']:>3} found={p['found']:>2} "
              f"unverified={p['found_unverified']:>2} created={p['created']:>2} frozen={p['frozen']:>2} "
              f"themes={p['themes']} {'ok' if p['ok'] else 'SHORT'}")
    print(f"companies with >= {MIN_QUESTIONS} questions and >= {MIN_FOUND} verified found: {good} "
          f"(need {args.min_companies}); companies held: {len(per)}")
    return 0 if good >= args.min_companies else 1


def cmd_export(args: argparse.Namespace) -> int:
    from openpyxl import Workbook

    conn = connect(Path(args.db))
    book = Workbook()
    sheet = book.active
    sheet.title = "questions"
    head = ["company", "symbol", "isin", "kind", "theme", "frozen", "question", "grounding_fact", "data_needed",
            "source_title", "source_url", "http_status", "word_overlap", "model", "fetched_at"]
    sheet.append(head)
    for row in conn.execute(f"SELECT {', '.join(head)} FROM question ORDER BY company, kind, theme, id"):
        sheet.append(list(row))
    summary = book.create_sheet("companies")
    summary.append(["company", "symbol", "total", "found", "found_unverified", "created", "frozen", "themes"])
    for row in conn.execute(
            "SELECT company, symbol, COUNT(*), SUM(kind='found'), SUM(kind='found_unverified'), SUM(kind='created'), "
            "SUM(frozen), COUNT(DISTINCT theme) FROM question GROUP BY isin ORDER BY company"):
        summary.append(list(row))
    facts = book.create_sheet("business_facts")
    facts.append(["company", "fact", "source_url"])
    for row in conn.execute("SELECT (SELECT company FROM question q WHERE q.isin=b.isin LIMIT 1), fact, source_url "
                            "FROM business_fact b ORDER BY 1"):
        facts.append(list(row))
    conn.close()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    book.save(out)
    print(f"wrote {out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("harvest", "load", "check", "export"):
        p = sub.add_parser(name)
        p.add_argument("--db", default=str(DB))
        p.add_argument("--queue", default=str(QUEUE))
        if name in ("harvest", "load"):
            p.add_argument("--raw", default=str(RAW))
            p.add_argument("--model", default=MODEL)
        if name == "harvest":
            p.add_argument("--only", default=None, help="comma list of queue positions (1-based)")
            p.add_argument("--limit", type=int, default=0, help="at most this many companies this run")
            p.add_argument("--workers", type=int, default=2)
            p.add_argument("--timeout", type=int, default=1500)
            p.add_argument("--force", action="store_true", help="redo a company that already has questions")
        if name == "check":
            p.add_argument("--min-companies", type=int, default=1)
        if name == "export":
            p.add_argument("--out", default=f"D:/RealityEngine/reports/{time.strftime('%Y-%m-%d')}_tg_question_bank.xlsx")
    args = ap.parse_args(argv)
    return {"harvest": cmd_harvest, "load": cmd_load, "check": cmd_check, "export": cmd_export}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
