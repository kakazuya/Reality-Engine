"""Prototype-3 measurement: three companies, three arms, answers and the report.

Scope (task of 2026-11-01): BAJFINANCE (lender), HINDALCO (manufacturer), KEC
(order book), every held annual report / earnings call / presentation / results
filing from FY2024-25 on.  Arm A is code only (XBRL, PDF text tables, keyword
search); Arm B is the existing Flash reader on the passages Arm A left; Arm C
compares the held Haiku deck facts, DeepSeek and CPU OCR on the same slides.

    python -m reality_engine.pilot.proto3 docs      # document census per company/type
    python -m reality_engine.pilot.proto3 scope     # enforce the 3-ISIN scope, rebuild feed
    python -m reality_engine.pilot.proto3 accuracy  # 30 rows/arm read back to the page
    python -m reality_engine.pilot.proto3 recall    # 3 docs/company/type, whole-doc pass
    python -m reality_engine.pilot.proto3 arm-c     # deck OCR vs Haiku vs DeepSeek
    python -m reality_engine.pilot.proto3 effort    # 30 passages at low and max
    python -m reality_engine.pilot.proto3 bank      # answers for the bank rows
    python -m reality_engine.pilot.proto3 report    # tasks/pilot60/PROTOTYPE3_REPORT_...
    python -m reality_engine.pilot.proto3 dryrun    # contracts vs stored rows + recall cost

Read-only on every input; writes only ``reality_engine/data/extract_proto3.db``
(Arm A/B), ``tasks/pilot60/PROTOTYPE3_*`` outputs and ``.tmp/proto3`` scratch.
``dryrun`` is the exception: it only reads (no model call, no store write).
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import sqlite3
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

from reality_engine.pilot import extract60 as x

REPO = x.REPO
OUT = REPO / "tasks" / "pilot60"
SCRATCH = REPO / ".tmp" / "proto3"
PROTO_ISINS = ("INE296A01032", "INE038A01020", "INE389H01022")
SYMBOLS = {"INE296A01032": "BAJFINANCE", "INE038A01020": "HINDALCO",
           "INE389H01022": "KEC"}
SINCE, DATE = "2024-04-01", "2026-11-01"
ANSWER_FILE = OUT / f"PROTOTYPE3_ANSWERS_{DATE}.jsonl"
REPORT_FILE = OUT / f"PROTOTYPE3_REPORT_{DATE}.md"
BANK = OUT / "PILOT_BANK_2026-10-31.jsonl"
ACCURACY = OUT / f"PROTOTYPE3_ACCURACY_{DATE}.json"
RECALL = OUT / f"PROTOTYPE3_RECALL_{DATE}.json"
ARM_C = OUT / f"PROTOTYPE3_ARM_C_{DATE}.json"
EFFORT = OUT / f"PROTOTYPE3_EFFORT_{DATE}.json"
MEASURE = OUT / f"PROTOTYPE3_MEASUREMENTS_{DATE}.json"
SCOPE_FIX = OUT / f"PROTOTYPE3_SCOPE_{DATE}.json"
DB = REPO / "reality_engine" / "data" / "extract_proto3.db"
DB_A = REPO / "reality_engine" / "data" / "extract_proto3_arm_a.db"

#: primary key columns per extraction table (Arm A membership is decided on these).
PKS = {
    "company_segment_pnl": ("isin", "segment", "period_end", "metric", "basis"),
    "company_operating_metrics": ("isin", "period_end", "metric"),
    "company_cost_structure": ("isin", "period_end", "basis", "input_key"),
    "company_debt_mix": ("isin", "period_end", "bucket"),
    "company_capacity_utilisation": ("isin", "period_end", "product"),
    "capex_project": ("isin", "project", "announced_on"),
    "order_intake": ("isin", "period_end"),
    "order_book_contract": ("isin", "contract_id"),
    "company_price_revision": ("isin", "announced_on", "product", "source_doc_id"),
    "rating_action": ("isin", "action_date", "agency", "instrument"),
    "supply_link": ("src_isin", "dst_isin", "relation"),
    "balance_sheet_lines": ("isin", "period_end", "basis", "line_item"),
    "cash_flow_lines": ("isin", "period_end", "basis", "line_item"),
    "tax_reconciliation": ("isin", "period_end", "basis", "item"),
    "lender_metrics": ("isin", "period_end", "metric"),
    "unit_volume": ("isin", "period_end", "product"),
}
VALUE_COLUMNS = ("value", "value_cr", "amount_cr", "quantity", "intake_cr", "order_book_cr",
                 "capex_cr", "revision_pct", "utilisation_pct", "capacity", "total_equity")
DOC_TYPES = ("annual_report", "concall", "deck", "results_notes")


def _configure() -> None:
    os.environ.setdefault("REALITY_EXTRACT_ISINS", ",".join(PROTO_ISINS))
    os.environ.setdefault("REALITY_EXTRACT_SINCE", SINCE)
    os.environ.setdefault("REALITY_EXTRACT_DB", str(DB))
    x.SCOPE_ISINS, x.SINCE = PROTO_ISINS, SINCE
    SCRATCH.mkdir(parents=True, exist_ok=True)


def _connect(path: Path | None = None) -> sqlite3.Connection:
    con = sqlite3.connect(str(path or DB))
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout = 30000")
    return con


def _scope_docs() -> tuple[dict[str, dict], list[dict]]:
    docs, chunks = x.load_store(x.chunk_store_path())
    x.reconcile_known_at(docs)
    docs = {d: v for d, v in docs.items() if x.in_scope(v)}
    return docs, chunks


def _by_doc(chunks: list[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = defaultdict(list)
    for chunk in chunks:
        out[chunk["doc_id"]].append(chunk)
    return out


def _page_stats(docs: dict) -> dict:
    stats = defaultdict(lambda: {"docs": 0, "pages": 0, "chunks": 0, "chars": 0})
    for doc in docs.values():
        key = (SYMBOLS.get(doc["isin"], doc["isin"]), doc["doc_type"])
        row = stats[key]
        row["docs"] += 1
        row["pages"] += int(doc.get("page_count") or 0)
        row["chars"] += int(doc.get("char_count") or 0)
    return {f"{k[0]}|{k[1]}": v for k, v in sorted(stats.items())}


def _table_count(con, table: str) -> int:
    return int(con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def _arm_rows(con, arm: str) -> dict:
    out = {}
    for row in con.execute("SELECT * FROM extract_arm WHERE arm = ? ORDER BY ran_at", (arm,)):
        out[row["table_name"]] = dict(row)  # later pass wins: the ledger is append-only
    return out


def _arm_a_keys() -> dict[str, set]:
    """The primary keys Arm A wrote, read from its own reference DB."""
    if not DB_A.is_file():
        return {}
    con = _connect(DB_A)
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    keys = {}
    for table, cols in PKS.items():
        if table not in tables:
            continue
        keys[table] = {tuple(row[c] for c in cols)
                       for row in con.execute(f"SELECT {','.join(cols)} FROM {table}")}
    con.close()
    return keys


def _arm_of(table: str, row: dict, a_keys: dict[str, set]) -> str:
    key = tuple(row.get(c) for c in PKS[table])
    return "A" if key in a_keys.get(table, set()) else "B"


def _numeric(row: dict) -> tuple[str, float] | tuple[None, None]:
    for column in VALUE_COLUMNS:
        value = row.get(column)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return column, float(value)
    rate = row.get("effective_rate_pct")
    if isinstance(rate, (int, float)):
        return "effective_rate_pct", float(rate)
    return None, None


# --------------------------------------------------------------------------- docs
def cmd_docs() -> dict:
    docs, chunks = _scope_docs()
    by_doc = _by_doc(chunks)
    stats = _page_stats(docs)
    for doc in docs.values():
        key = f"{SYMBOLS.get(doc['isin'], doc['isin'])}|{doc['doc_type']}"
        stats[key]["chunks"] += len(by_doc.get(doc["doc_id"]) or [])
        stats[key]["chars"] = stats[key].get("chars") or sum(
            len(c["body"] or "") for c in by_doc.get(doc["doc_id"]) or [])
    out = {"since": SINCE, "isins": list(PROTO_ISINS), "docs": stats,
           "total_docs": len(docs), "total_chunks": len(chunks),
           "known_at": dict(Counter(
               "fixed" if str(d.get("known_at") or "")[:10] != str(d.get("event_date") or "")[:10]
               else "agree" for d in docs.values()))}
    (SCRATCH / "docs.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    return out


# --------------------------------------------------------------------------- scope guard
def cmd_scope() -> dict:
    """Enforce the three-name scope on every measure table, then rebuild the feed rows.

    Arm A's BSE rating feed ran over the 60-name universe before the scope filter reached
    ``universe_symbols`` (defect found 2026-11-01): 207 rows for 34 other companies sat in
    ``rating_action``. They cost no model tokens. This deletes every row keyed to an ISIN
    outside the scope in both the working and the Arm A reference store, re-runs the feed
    under the scope, and ledgers that pass as the code-only Arm A work it is.
    """
    marks = ",".join("?" * len(PROTO_ISINS))
    removed = {}
    for path in (DB, DB_A):
        con = _connect(path)
        for table in PKS:
            cols = ("src_isin", "dst_isin") if table == "supply_link" else ("isin",)
            before = _table_count(con, table)
            where = " AND ".join(f"{c} IN ({marks})" for c in cols)
            con.execute(f"DELETE FROM {table} WHERE NOT ({where})",
                        (*PROTO_ISINS,) * len(cols))
            removed[table] = removed.get(table, 0) + before - _table_count(con, table)
        if path == DB:  # rebuild the feed from scratch, so its ledger row is a real delta
            con.execute("DELETE FROM rating_action")
        con.commit()
        con.close()
    con = _connect()
    x.ARM = "A"  # code-only work: the feed pass is ledgered under Arm A
    started = time.time()
    inserted, rejected = Counter(), Counter()
    feed = x._announcement_rating_pass(con, inserted, rejected)
    con.commit()
    left = [r[0] for r in con.execute("SELECT DISTINCT isin FROM rating_action")
            if r[0] not in PROTO_ISINS]
    con.close()
    out = {"removed": {k: v for k, v in removed.items() if v},
           "out_of_scope_rows_removed": sum(removed.values()),
           "feed_rows_rebuilt": feed, "feed_cost_usd": 0.0,
           "out_of_scope_isins_left": len(left), "wall_s": round(time.time() - started, 2)}
    (SCRATCH / "scope.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    return out


# --------------------------------------------------------------------------- accuracy
def _check_xbrl_row(row: dict) -> tuple[bool, str]:
    quote = str(row.get("quote") or "")
    column, value = _numeric(row)
    con = x.connect_data("results_xbrl.db")
    if con is None:
        return False, "xbrl_store_missing"
    try:
        if column == "effective_rate_pct":
            # A ratio row prints both facts and derives the rate; re-read both, recompute.
            match = re.match(r"TaxExpense/ProfitBeforeTax = (-?\d+)/(-?\d+)", quote)
            if not match:
                return False, "ratio_quote_not_parseable"
            tax, pbt = float(match.group(1)), float(match.group(2))
            for concept, printed in (("TaxExpense", tax), ("ProfitBeforeTax", pbt)):
                if not con.execute("SELECT 1 FROM facts WHERE file = ? AND concept = ? "
                                   "AND ABS(value - ?) < 1 LIMIT 1",
                                   (row.get("doc_id"), concept, printed)).fetchone():
                    return False, f"xbrl_fact_missing:{concept}"
            if not pbt:
                return False, "xbrl_pbt_zero"
            rate = tax / pbt * 100.0
            return (value is not None and abs(rate - value) <= 0.01), "xbrl_ratio"
        match = re.match(r"([A-Za-z0-9_]+)\[([^\]]*)\]=", quote)
        if not match or value is None:
            return False, "quote_not_parseable"
        found = con.execute(
            "SELECT value FROM facts WHERE file = ? AND concept = ? AND context = ?",
            (row.get("doc_id"), match.group(1), match.group(2))).fetchall()
    except sqlite3.Error as exc:
        return False, f"xbrl_query:{exc}"
    finally:
        con.close()
    return any(abs(abs(float(r["value"]) / 1e7) - abs(value)) <= max(abs(value) * 1e-4, 1e-4)
               for r in found), "xbrl_fact" if found else "xbrl_fact_missing"


def _check_chunk_row(row: dict, docs: dict, chunks_by_doc: dict) -> tuple[bool, str]:
    quote = str(row.get("quote") or "")
    column, value = _numeric(row)
    doc_id = row.get("source_doc_id") or row.get("doc_id")
    carriers = [c for c in chunks_by_doc.get(doc_id) or []
                if x.quote_in(quote, c["body"] or "")]
    if not carriers:
        return False, "quote_not_on_page"
    page = row.get("page")
    if page is not None:
        carriers = [c for c in carriers if x._page_in(page, c.get("page_from"),
                                                      c.get("page_to"))] or carriers
    if value is None:
        return True, "quote_on_page"
    return any(x.value_in(c["body"] or "", value) for c in carriers), \
        "value_on_page" if any(x.value_in(c["body"] or "", value) for c in carriers) \
        else "value_not_on_page"


def _check_feed_row(row: dict) -> tuple[bool, str]:
    """A BSE-announcement row: its evidence is the feed headline, not a PDF page."""
    news_id = str(row.get("source_doc_id") or "").split(":", 1)[-1]
    con = x.connect_data("bse_announcements.db")
    if con is None:
        return False, "ann_store_missing"
    try:
        head = con.execute("SELECT HEADLINE FROM ann WHERE NEWSID = ?", (news_id,)).fetchone()
    except sqlite3.Error as exc:
        return False, f"ann_query:{exc}"
    finally:
        con.close()
    if not head:
        return False, "ann_row_missing"
    quote = " ".join(str(row.get("quote") or "").split()).lower()
    body = " ".join((head[0] or "").split()).lower()
    if not quote:
        return False, "quote_empty"
    return quote in body, "ann_headline" if quote in body else "quote_not_in_headline"


def cmd_accuracy(n: int = 30) -> dict:
    docs, chunks = _scope_docs()
    chunks_by_doc = _by_doc(chunks)
    a_keys = _arm_a_keys()
    con = _connect()
    rng = random.Random(20261101)
    rows_by_arm = defaultdict(list)
    for table in x.TABLES:
        for raw in con.execute(f"SELECT * FROM {table}"):
            row = dict(raw)
            rows_by_arm[_arm_of(table, row, a_keys)].append((table, row))
    out = {}
    for arm, candidates in sorted(rows_by_arm.items()):
        sample = rng.sample(candidates, min(n, len(candidates)))
        checked = []
        for table, row in sample:
            if row.get("source") == "results_xbrl":
                ok, why = _check_xbrl_row(row)
                evidence = row.get("quote")
            elif str(row.get("source_doc_id") or "").startswith("bse_ann:"):
                ok, why = _check_feed_row(row)
                evidence = row.get("quote")
            else:
                ok, why = _check_chunk_row(row, docs, chunks_by_doc)
                evidence = (row.get("quote") or "")[:300]
            column, value = _numeric(row)
            checked.append({"table": table, "isin": row.get("isin"),
                            "symbol": SYMBOLS.get(row.get("isin")), "period_end":
                            row.get("period_end") or row.get("action_date") or row.get("announced_on"),
                            "column": column, "value": value, "page": row.get("page"),
                            "quote": row.get("quote"), "known_at": row.get("known_at"),
                            "verdict": "RIGHT" if ok else "WRONG", "check": why,
                            "evidence": evidence})
        out[arm] = {"n": len(checked),
                    "right": sum(1 for r in checked if r["verdict"] == "RIGHT"),
                    "rows": checked}
    out["population"] = {arm: len(rows) for arm, rows in rows_by_arm.items()}
    con.close()
    ACCURACY.write_text(json.dumps(out, indent=1), encoding="utf-8")
    return {arm: {"n": v["n"], "right": v["right"]} for arm, v in out.items()
            if isinstance(v, dict) and "n" in v}


# --------------------------------------------------------------------------- recall
RECALL_TARGETS = {
    "lender_metrics": "metric one of gnpa_pct|nnpa_pct|nim_pct|casa_pct|credit_cost_pct|"
                      "capital_adequacy_pct|provision_coverage_pct; value, unit=pct",
    "unit_volume": "product, quantity, unit (kt|tonnes|mt|units)",
    "balance_sheet_lines": "line_item one of total_assets|total_liabilities|total_equity|"
                           "borrowings|inventories|trade_receivables|cash_and_equivalents; "
                           "value_cr, basis",
    "cash_flow_lines": "line_item one of operating_activities|investing_activities|"
                       "financing_activities|closing_cash; value_cr, basis",
    "tax_reconciliation": "item one of current_tax|deferred_tax|tax_expense|profit_before_tax|"
                          "effective_tax_rate; amount_cr or effective_rate_pct",
    "order_intake": "intake_cr and/or order_book_cr (Rs crore)",
    "company_operating_metrics": "metric name, value, unit",
}
RECALL_PROMPT = """You extract facts from one company document into STRICT JSON.
Output ONLY: {{"rows": [ ... ]}}
Required keys per row: table (one of the names below), quote (VERBATIM from the text,
<=25 words, containing the number), page (the [pN] marker integer), period_end
(YYYY-MM-DD, the period the sentence names), plus the table's own keys.
Tables and keys:
{ladder}
Money in Rs crore. Every row must be grounded in one passage. Output {{"rows": []}} if none.
Document: {doc_type} | {symbol} | filed {known_at} | period {fiscal_period}

Passages:
{passages}
"""


def _recall_passages(doc: dict, chunks: list[dict], budget: int = 9000) -> tuple[list[dict], str]:
    """Number-dense chunks of the document, not the selector's ranking (independent read)."""
    scored = []
    for chunk in chunks:
        body = chunk["body"] or ""
        numbers = len(re.findall(r"\d[\d,]*(?:\.\d+)?", body))
        if numbers:
            scored.append((numbers, -(chunk.get("page_from") or 0), chunk))
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    chosen, used, lines = [], 0, []
    for _, _, chunk in scored:
        body = (chunk["body"] or "").strip()
        if used + len(body) > budget:
            body = body[:max(0, budget - used)]
        if not body:
            break
        used += len(body)
        chosen.append(chunk)
        lines.append(f"[passage p{chunk.get('page_from')}]\n{body}")
    return chosen, "\n\n".join(lines)


def _remaining_budget() -> float:
    """The brief's $1.50 reader cap minus every model call logged in ``extract_call``."""
    try:
        con = _connect()
        spent = con.execute("SELECT COALESCE(SUM(cost_usd),0) FROM extract_call").fetchone()[0]
        con.close()
    except sqlite3.Error:
        spent = 0.0
    return max(0.02, 1.50 - float(spent or 0.0))


def _log_calls(reader, label: str) -> None:
    """Append a reader run's own call log to ``extract_call``: one ledger for every token."""
    calls = list(getattr(reader, "call_log", ()) or ())
    if not calls:
        return
    con = _connect()
    stamp = time.strftime("%Y-%m-%dT%H:%M:%S")
    con.executemany(
        "INSERT INTO extract_call (table_name, doc_id, model, prompt_chars, pages_sent, in_tok, "
        "out_tok, cost_usd, ok, error, ms, ran_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        [(call.get("table_name") or label, call.get("doc_id"), call.get("model"),
          call.get("prompt_chars"), call.get("pages_sent"), call.get("in_tok"),
          call.get("out_tok"), call.get("cost_usd"), call.get("ok"), call.get("error"),
          call.get("ms"), stamp) for call in calls])
    con.commit()
    con.close()


def cmd_recall(per_type: int = 3, workers: int = 4) -> dict:
    docs, chunks = _scope_docs()
    chunks_by_doc = _by_doc(chunks)
    reader = x.Reader(cap=_remaining_budget())
    if not reader.available:
        raise SystemExit("reader unavailable")
    ladder = "\n".join(f"- {table}: {hint}" for table, hint in RECALL_TARGETS.items())
    tasks = []
    for isin in PROTO_ISINS:
        for doc_type in DOC_TYPES:
            picked = sorted((d for d in docs.values()
                             if d["isin"] == isin and d["doc_type"] == doc_type),
                            key=lambda d: d.get("known_at") or "", reverse=True)
            for doc in picked[:per_type]:
                passages, block = _recall_passages(doc, chunks_by_doc.get(doc["doc_id"]) or [])
                if not passages:
                    continue
                prompt = RECALL_PROMPT.format(ladder=ladder, doc_type=doc["doc_type"],
                                              symbol=doc["symbol_at_time"], known_at=doc["known_at"],
                                              fiscal_period=doc.get("fiscal_period") or "",
                                              passages=block)
                tasks.append((doc, passages, prompt))
    results = _run_parallel(reader, [(doc, passages, prompt) for doc, passages, prompt in tasks],
                            lambda doc, passages: {"table_name": "recall",
                                                   "doc_id": doc["doc_id"],
                                                   "pages_sent": len(passages)})
    con = _connect()
    store = {}
    for table in RECALL_TARGETS:
        store[table] = [dict(r) for r in con.execute(f"SELECT * FROM {table}")]
    con.close()
    _log_calls(reader, "recall")
    out_rows, per_doc = [], []
    for doc, passages, answer in results:
        valid, missed = [], []
        for item in answer or []:
            table = item.get("table")
            if table not in RECALL_TARGETS:
                continue
            clean, reason = x.validate(table, item, doc, passages)
            if not clean:
                continue
            valid.append((table, clean))
            match = _store_match(store.get(table) or [], table, clean)
            if not match:
                missed.append({"table": table, "row": clean})
        per_doc.append({"isin": doc["isin"], "symbol": doc["symbol_at_time"],
                        "doc_type": doc["doc_type"], "doc_id": doc["doc_id"],
                        "pages_read": len(passages),
                        "baseline_rows": len(valid), "missed": len(missed),
                        "misses": missed[:20]})
        out_rows.extend(valid)
    out = {"docs": len(per_doc), "baseline_rows": len(out_rows),
           "missed": sum(d["missed"] for d in per_doc),
           "per_doc": per_doc}
    RECALL.write_text(json.dumps(out, indent=1), encoding="utf-8")
    return {k: out[k] for k in ("docs", "baseline_rows", "missed")}


def _store_match(rows: list[dict], table: str, clean: dict) -> dict | None:
    keys = PKS[table]
    candidates = [r for r in rows if all(r.get(k) == clean.get(k) for k in keys)]
    column, value = _numeric(clean)
    for row in candidates:
        _, stored = _numeric(row)
        if value is None or stored is None:
            return row
        if abs(stored - value) <= max(abs(value) * 0.02, 0.01):
            return row
    return None


def _run_parallel(reader, tasks, meta_fn, workers: int = 4):
    """Run the reader over ``tasks``, returning one ``(doc, passages, rows)`` per task, in order.

    Callers pair the answers back to their own task list, so the order must be the input
    order, not completion order (a mispairing rejected every low-effort row, 2026-11-01).
    """
    import concurrent.futures as cf
    out: list = [None] * len(tasks)
    with cf.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(reader.ask, prompt, 120, meta_fn(doc, passages)): index
                   for index, (doc, passages, prompt) in enumerate(tasks)}
        for future in cf.as_completed(futures):
            index = futures[future]
            doc, passages, _ = tasks[index]
            try:
                answer = future.result()
            except Exception:  # noqa: BLE001
                answer = None
            rows = answer.get("rows") if isinstance(answer, dict) else []
            out[index] = (doc, passages, rows if isinstance(rows, list) else [])
    return out


# --------------------------------------------------------------------------- Arm C
def _ocr_engine():
    try:
        from rapidocr import RapidOCR
    except ImportError:
        lib = SCRATCH.parent / "ocr_lib"
        if lib.is_dir():
            sys.path.insert(0, str(lib))
        from rapidocr import RapidOCR
    return RapidOCR()


def _ocr_text(engine, png: Path) -> str:
    result = engine(str(png))
    texts = getattr(result, "txts", None)
    if texts is None:
        try:
            texts = [item[1] for item in result]
        except Exception:  # noqa: BLE001
            texts = []
    return "\n".join(str(t) for t in texts if t)


DECK_PROMPT = """You extract numeric facts printed on ONE investor-presentation page.
Output ONLY: {{"rows":[{{"metric":str,"value":number,"unit":str,"period":str|null,"quote":str}}]}}
Rules: quote is copied VERBATIM from the page text (<=20 words) and contains the number;
value is the number exactly as printed (no unit conversion); unit is %|crore|INR|kt|tonnes|mn|bn|
x|count or as printed; period is the column/period label when the page prints one.
Page text:
{text}
"""


def cmd_arm_c(pages_per_deck: int = 3, decks_per_company: int = 1) -> dict:
    import fitz  # PyMuPDF
    engine = _ocr_engine()
    docs, _ = _scope_docs()
    by_sha = {d["sha256"]: d for d in docs.values() if d["doc_type"] == "deck"}
    con = x.connect_data("deck_figures.db")
    if con is None:
        raise SystemExit("deck_figures.db missing")
    pdfs = {row["sha256"]: row["local_path"] for row in con.execute(
        "SELECT sha256, local_path FROM deck_sources WHERE sha256 IS NOT NULL")}
    for sha, doc in by_sha.items():
        if not pdfs.get(sha) or not Path(pdfs[sha]).is_file():
            if doc.get("raw_path"):
                pdfs[sha] = doc["raw_path"]
    pages_rows = [dict(r) for r in con.execute(
        "SELECT sha256, page_no, known_at, symbol, isin FROM pages "
        "WHERE isin IN (?,?,?) AND known_at >= ? AND n_facts >= 1 "
        "ORDER BY known_at DESC", (*PROTO_ISINS, SINCE))]
    picked, seen = [], Counter()
    for page in pages_rows:
        if page["sha256"] not in by_sha or page["sha256"] not in pdfs:
            continue
        if seen[page["isin"]] >= decks_per_company * pages_per_deck:
            continue
        seen[page["isin"]] += 1
        picked.append(page)
    reader = x.Reader()
    report_pages, disagreements = [], []
    for page in picked:
        sha, page_no = page["sha256"], int(page["page_no"])
        doc = by_sha[sha]
        pdf = Path(pdfs[sha])
        if not pdf.is_file():
            continue
        document = fitz.open(pdf)
        if page_no < 1 or page_no > len(document):
            document.close()
            continue
        pdf_page = document.load_page(page_no - 1)
        zoom = 1600 / max(pdf_page.rect.width, pdf_page.rect.height)
        pix = pdf_page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
        png = SCRATCH / f"{sha[:12]}_p{page_no}.png"
        pix.save(png)
        slide_text = pdf_page.get_text("text")
        document.close()
        ocr = _ocr_text(engine, png)
        haiku = [dict(r) for r in con.execute(
            "SELECT metric, value, unit, period, raw_number FROM facts JOIN pages p "
            "ON p.sha256 = facts.sha256 AND p.page_no = facts.page_no "
            "AND p.prompt_version = facts.prompt_version "
            "WHERE facts.sha256 = ? AND facts.page_no = ? AND facts.is_final = 1",
            (sha, page_no))]
        ocr_hits = sum(1 for fact in haiku if fact.get("value") is not None
                       and x.value_in(ocr, float(fact["value"])))
        deepseek = []
        if reader.available and ocr.strip():
            answer = reader.ask(DECK_PROMPT.format(text=ocr[:9000]),
                                meta={"table_name": "deck_page", "doc_id": doc["doc_id"],
                                      "pages_sent": 1})
            for row in (answer or {}).get("rows", [])[:40]:
                value = x.as_float(row.get("value"))
                quote = str(row.get("quote") or "")
                if value is None or not x.quote_in(quote, ocr) or not x.value_in(quote, value):
                    continue
                deepseek.append({"metric": row.get("metric"), "value": value,
                                 "unit": row.get("unit"), "period": row.get("period"),
                                 "quote": quote})
        # disagreement: a Haiku value neither OCR-search nor DeepSeek reproduces,
        # or a DeepSeek value Haiku does not carry (matched on value only, 2%).
        haiku_values = [float(f["value"]) for f in haiku if f.get("value") is not None]
        ds_values = [r["value"] for r in deepseek]
        for fact in haiku:
            value = fact.get("value")
            if value is None:
                continue
            in_ocr = x.value_in(ocr, float(value))
            in_ds = any(abs(v - float(value)) <= max(abs(float(value)) * 0.02, 0.01)
                        for v in ds_values)
            if not in_ds:
                disagreements.append({"sha": sha, "page": page_no, "isin": doc["isin"],
                                      "symbol": doc["symbol_at_time"],
                                      "metric": fact.get("metric"), "value": value,
                                      "unit": fact.get("unit"), "period": fact.get("period"),
                                      "ocr_search_hit": in_ocr,
                                      "deepseek_has": False,
                                      "slide_window": _window(slide_text, str(fact.get("raw_number") or value))})
        for row in deepseek:
            if not any(abs(v - row["value"]) <= max(abs(row["value"]) * 0.02, 0.01)
                       for v in haiku_values):
                disagreements.append({"sha": sha, "page": page_no, "isin": doc["isin"],
                                      "symbol": doc["symbol_at_time"],
                                      "metric": row.get("metric"), "value": row["value"],
                                      "unit": row.get("unit"), "period": row.get("period"),
                                      "ocr_search_hit": x.value_in(ocr, row["value"]),
                                      "deepseek_has": True, "haiku_has": False,
                                      "slide_window": _window(slide_text, str(row["value"]))})
        report_pages.append({"isin": doc["isin"], "symbol": doc["symbol_at_time"], "sha": sha,
                             "page": page_no, "pdf": str(pdf), "png": str(png),
                             "haiku_facts": len(haiku), "haiku_values_in_ocr": ocr_hits,
                             "deepseek_facts": deepseek,
                             "ocr_text": ocr[:6000], "slide_text": slide_text[:6000]})
    _log_calls(reader, "deck_page")
    out = {"pages": report_pages, "disagreements": disagreements,
           "handcheck_candidates": [d for d in disagreements
                                    if (not d["ocr_search_hit"]) or d.get("haiku_has") is False],
           "summary": {
               "pages": len(report_pages),
               "haiku_facts": sum(p["haiku_facts"] for p in report_pages),
               "haiku_values_in_ocr": sum(p["haiku_values_in_ocr"] for p in report_pages),
               "deepseek_rows": sum(len(p["deepseek_facts"]) for p in report_pages),
               "ocr_miss": sum(1 for d in disagreements if not d["ocr_search_hit"]),
               "deepseek_extra": sum(1 for d in disagreements if d.get("haiku_has") is False),
               "deepseek_missing": sum(1 for d in disagreements if not d["deepseek_has"]),
           },
           "ocr": "RapidOCR CPU (onnxruntime, no GPU)"}
    ARM_C.write_text(json.dumps(out, indent=1), encoding="utf-8")
    return {"pages": len(report_pages), "haiku_facts": sum(p["haiku_facts"] for p in report_pages),
            "haiku_in_ocr": sum(p["haiku_values_in_ocr"] for p in report_pages),
            "deepseek_rows": sum(len(p["deepseek_facts"]) for p in report_pages),
            "disagreements": len(disagreements)}


def _window(text: str, needle: str, width: int = 240) -> str:
    index = text.find(str(needle))
    if index < 0:
        index = text.find(str(needle).replace(",", ""))
    return " ".join(text[max(0, index - width):index + width].split()) if index >= 0 else ""


# --------------------------------------------------------------------------- effort
def cmd_effort(n: int = 30, workers: int = 4) -> dict:
    docs, chunks = _scope_docs()
    by_doc = _by_doc(chunks)
    tasks = []
    for table in x.TABLES:
        for row in x.selection_rows(table, docs, by_doc):
            doc = docs[row["doc_id"]]
            for block, prompt in x.prompt_blocks(table, doc, row["_passages"]):
                tasks.append((table, doc, block, prompt))
    random.Random(20261101).shuffle(tasks)
    tasks = tasks[:n]
    results = {}
    # Two arms share what is left of the $1.50 cap; 0.26 each covers the measured rate.
    budget = min(0.26, _remaining_budget() / 2)
    for label, model in (("low", "deepseek-v4.1-flash~low"),
                         ("max", "deepseek-v4.1-flash~max")):
        reader = x.Reader(model=model, cap=budget)
        started = time.time()
        rows = _run_parallel(reader, [(doc, passages, prompt) for _, doc, passages, prompt
                                      in tasks], lambda doc, passages: {
            "table_name": "effort", "doc_id": doc["doc_id"], "pages_sent": len(passages)},
            workers)
        per_task, accepted, rejected = [], 0, 0
        for (table, doc, passages, prompt), (_, _, answer) in zip(tasks, rows):
            good, bad = [], 0
            for item in answer:
                clean, reason = x.validate(table, item, doc, passages)
                if clean:
                    good.append(clean)
                else:
                    bad += 1
            accepted += len(good)
            rejected += bad
            per_task.append({"table": table, "doc_id": doc["doc_id"],
                             "rows": len(answer), "accepted": len(good), "wrong": bad,
                             "accepted_rows": good})
        results[label] = {"model": model, "calls": reader.calls, "in_tok": reader.in_tok,
                          "out_tok": reader.out_tok, "cost_usd": round(reader.cost, 4),
                          "wall_s": round(time.time() - started, 1), "rows": accepted,
                          "wrong": rejected, "per_task": per_task,
                          "errors": dict(reader.errors)}
        print(f"  effort {label}: {reader.calls} calls, {accepted} rows, {rejected} wrong, "
              f"{reader.in_tok} in / {reader.out_tok} out, ${round(reader.cost, 4)}, "
              f"{round(time.time() - started, 1)} s", flush=True)
        _log_calls(reader, "effort")
    low = {json.dumps({k: r[k] for k in ("quote", "period_end") if k in r}, sort_keys=True, default=str)
           for task in results["low"]["per_task"] for r in task["accepted_rows"]}
    high = {json.dumps({k: r[k] for k in ("quote", "period_end") if k in r}, sort_keys=True, default=str)
            for task in results["max"]["per_task"] for r in task["accepted_rows"]}
    out = {"n_tasks": len(tasks),
           "low": {k: results["low"][k] for k in ("model", "calls", "in_tok", "out_tok",
                                                 "cost_usd", "wall_s", "rows", "wrong",
                                                 "errors")},
           "max": {k: results["max"][k] for k in ("model", "calls", "in_tok", "out_tok",
                                                 "cost_usd", "wall_s", "rows", "wrong",
                                                 "errors")},
           "found_in_both": len(low & high), "only_low": len(low - high),
           "only_max": len(high - low), "per_task": {
               "low": [{k: t[k] for k in ("table", "doc_id", "rows", "accepted", "wrong")}
                       for t in results["low"]["per_task"]],
               "max": [{k: t[k] for k in ("table", "doc_id", "rows", "accepted", "wrong")}
                       for t in results["max"]["per_task"]]},
           "only_max_rows": sorted(high - low)[:20], "only_low_rows": sorted(low - high)[:20]}
    EFFORT.write_text(json.dumps(out, indent=1), encoding="utf-8")
    return {k: out[k] for k in ("n_tasks", "found_in_both", "only_low", "only_max")}


# --------------------------------------------------------------------------- answers
XBRL_BANK_CONCEPTS = {
    "revenue": ("RevenueFromOperations", "Rs crore"),
    "netsales": ("RevenueFromOperations", "Rs crore"),
    "profit": ("ProfitLossForPeriod", "Rs crore"),
    "pat": ("ProfitLossForPeriod", "Rs crore"),
    "profitbeforetax": ("ProfitBeforeTax", "Rs crore"),
    "tax": ("TaxExpense", "Rs crore"),
    "eps": ("BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations", "Rs/share"),
}
BANK_RULES = (
    (r"\bgnpa\b|gross npa|gross non.performing", "lender_metrics", "gnpa_pct"),
    (r"\bnnpa\b|net npa|net non.performing", "lender_metrics", "nnpa_pct"),
    (r"\bnim\b|net interest margin", "lender_metrics", "nim_pct"),
    (r"\bcasa\b", "lender_metrics", "casa_pct"),
    (r"credit cost", "lender_metrics", "credit_cost_pct"),
    (r"capital adequacy", "lender_metrics", "capital_adequacy_pct"),
    (r"provision coverage", "lender_metrics", "provision_coverage_pct"),
    (r"order book|order intake|order inflow|book to bill", "order_intake", None),
    (r"segment revenue|segment result|segment profit|segments", "company_segment_pnl", None),
    (r"capacity|utilisation|utilization|manufacturing facilit|plant", "company_capacity_utilisation", None),
    (r"capex|capital expenditure|expansion|greenfield|brownfield", "capex_project", None),
    (r"borrowing|debt mix|maturity|term loan|ncd", "company_debt_mix", None),
    (r"volume|shipment|production|tonne|aluminium|copper", "unit_volume", None),
    (r"rating|upgrade|downgrade|outlook", "rating_action", None),
    (r"price hike|price increase|price cut|price revision|mrp", "company_price_revision", None),
    (r"\bbalance sheet\b|total assets|total liabilities|net worth", "balance_sheet_lines", None),
    (r"cash flow|cash from operations|operating cash", "cash_flow_lines", None),
    (r"effective tax|tax reconciliation|current tax|deferred tax", "tax_reconciliation", None),
    (r"cost of material|raw material|cost structure", "company_cost_structure", None),
    (r"operating metric|arpu|subscriber|same.store|market share", "company_operating_metrics", None),
)


def _rows_for(con, table: str, isin: str, metric: str | None, limit: int = 8) -> list[dict]:
    sql, params = f"SELECT * FROM {table} WHERE isin = ?", [isin]
    if metric:
        sql += " AND metric = ?"
        params.append(metric)
    sql += " ORDER BY known_at DESC LIMIT ?"
    params.append(limit)
    try:
        return [dict(r) for r in con.execute(sql, params)]
    except sqlite3.Error:
        return []


STOPWORDS = {
    "what", "which", "where", "when", "latest", "report", "disclosed", "company", "annual",
    "business", "about", "their", "there", "these", "those", "other", "share", "price",
    "level", "value", "march", "june", "september", "december", "january", "february",
    "april", "august", "october", "november", "july", "since", "does", "make", "said",
    "kaunsa", "baare", "mein", "kya", "hisaab", "batao", "bajaj", "hindalco", "finance",
    "international", "limited", "company's", "accordance", "disclosure", "filing",
    "filed", "period", "years", "please", "according",
}


def _passage_rows(question: str, isins: list[str], scope: list[dict],
                  limit: int = 4) -> list[dict]:
    """Keyword passages from the company's own documents (the text-only fallback)."""
    words = [word for word in re.findall(r"[A-Za-z]{6,}", question.lower())
             if word not in STOPWORDS][:3]
    if not words:
        return []
    scored = []
    for chunk in scope:
        if chunk["isin"] not in isins:
            continue
        body = chunk["body"] or ""
        low = body.lower()
        hits = sum(1 for word in words if word in low)
        if hits:
            scored.append((hits, len(body), chunk))
    scored.sort(key=lambda item: (item[0], -item[1]), reverse=True)
    out = []
    for hits, _, chunk in scored[:limit]:
        body = chunk["body"] or ""
        index = min((body.lower().find(word) for word in words
                     if body.lower().find(word) >= 0), default=0)
        quote = " ".join(body[max(0, index - 120):index + 260].split())
        out.append({"table": "document_passage", "isin": chunk["isin"],
                    "symbol": SYMBOLS.get(chunk["isin"]), "doc_type": chunk["doc_type"],
                    "period_end": chunk.get("event_date") or chunk.get("known_at", "")[:10],
                    "measure": "passage", "value": None, "quote": quote,
                    "page": chunk.get("page_from"), "known_at": chunk.get("known_at")})
    return out


def _xbrl_bank_rows(con, isin: str, concept: str, limit: int = 6) -> list[dict]:
    rows = con.execute(
        "SELECT f.file, f.period_end, f.consolidated, "
        "COALESCE(f.broadcast_ts, f.dissem_ts, f.filing_ts) known_at, "
        "x.value, x.period_start, x.context FROM filings f JOIN facts x ON x.file = f.file "
        "WHERE f.isin = ? AND x.concept = ? AND f.period_end >= ? "
        "ORDER BY f.period_end DESC LIMIT ?", (isin, concept, SINCE, limit)).fetchall()
    out = []
    for row in rows:
        out.append({"table": "results_xbrl", "isin": isin,
                    "period_end": row["period_end"],
                    "basis": "consolidated" if str(row["consolidated"]).lower() == "consolidated"
                    else "standalone",
                    "value_cr": round(float(row["value"]) / 1e7, 4),
                    "quote": f"{concept}[{row['context']}]={float(row['value']):.0f} INR",
                    "page": None, "known_at": row["known_at"],
                    "formula": "XBRL fact / 1e7 (rupees -> Rs crore)"})
    return out


def cmd_bank() -> dict:
    if not BANK.is_file():
        raise SystemExit(f"bank missing: {BANK}")
    used, total = [], 0
    con = _connect()
    xbrl = x.connect_data("results_xbrl.db")
    docs, chunks = _scope_docs()
    scope = [{"isin": doc["isin"], "doc_type": doc["doc_type"],
              "event_date": doc.get("event_date"), "known_at": doc.get("known_at"),
              **chunk} for chunk in chunks for doc in [docs.get(chunk["doc_id"])] if doc]
    for line in BANK.open(encoding="utf-8"):
        if not line.strip():
            continue
        total += 1
        bank = json.loads(line)
        entities = [e for e in (bank.get("entities") or []) if e.get("isin") in PROTO_ISINS]
        if not bank.get("entities") or len(entities) != len(bank["entities"]):
            continue
        question = str(bank.get("question") or "")
        answer_rows, rule_used, passage_only = [], None, False
        for pattern, table, metric in BANK_RULES:
            if not re.search(pattern, question, re.I):
                continue
            rule_used = (table, metric)
            for entity in entities:
                answer_rows += _rows_for(con, table, entity["isin"], metric)
            if answer_rows:
                break
        if not answer_rows:
            low = question.lower()
            for word, (concept, unit) in XBRL_BANK_CONCEPTS.items():
                if word in low and xbrl is not None:
                    rule_used = ("results_xbrl", concept)
                    for entity in entities:
                        answer_rows += _xbrl_bank_rows(xbrl, entity["isin"], concept)
                    if answer_rows:
                        break
        if not answer_rows:
            answer_rows = _passage_rows(question, [e["isin"] for e in entities], scope)
            if answer_rows:
                rule_used, passage_only = ("document_passage", None), True
        clean = []
        for row in answer_rows[:12]:
            column, value = _numeric(row)
            item = {"table": rule_used[0] if rule_used else row.get("table"),
                    "isin": row.get("isin"), "symbol": SYMBOLS.get(row.get("isin")),
                    "period_end": row.get("period_end") or row.get("action_date")
                    or row.get("announced_on"),
                    "measure": row.get("metric") or row.get("line_item") or row.get("item")
                    or row.get("segment") or row.get("product") or row.get("bucket")
                    or row.get("measure"),
                    "value": value, "unit": row.get("unit") or "inr_cr",
                    "doc_type": row.get("doc_type"), "quote": row.get("quote"),
                    "page": row.get("page"), "known_at": row.get("known_at")}
            if row.get("intake_cr") and row.get("order_book_cr"):
                item["formula"] = "book_to_bill = order_book_cr / intake_cr"
                item["book_to_bill"] = round(float(row["order_book_cr"])
                                             / float(row["intake_cr"]), 3)
            clean.append(item)
        status = "answered" if clean and not passage_only else (
            "evidence" if clean else "not_found")
        used.append({"mid": bank.get("mid"), "question": question,
                     "entities": [e.get("symbol") for e in entities],
                     "answer_kind": bank.get("answer_kind"), "as_of": bank.get("as_of"),
                     "status": status,
                     "rule": list(rule_used) if rule_used else None,
                     "rows": clean})
    con.close()
    if xbrl is not None:
        xbrl.close()
    with ANSWER_FILE.open("w", encoding="utf-8") as handle:
        for row in used:
            handle.write(json.dumps(row, default=str) + "\n")
    return {"bank_rows": total, "in_scope": len(used),
            "answered": sum(1 for r in used if r["status"] == "answered"),
            "evidence": sum(1 for r in used if r["status"] == "evidence"),
            "not_found": sum(1 for r in used if r["status"] == "not_found")}


# --------------------------------------------------------------------------- report
def cmd_report() -> dict:
    docs_stats = json.loads((SCRATCH / "docs.json").read_text(encoding="utf-8"))
    accuracy = json.loads(ACCURACY.read_text(encoding="utf-8")) if ACCURACY.is_file() else {}
    recall = json.loads(RECALL.read_text(encoding="utf-8")) if RECALL.is_file() else {}
    arm_c = json.loads(ARM_C.read_text(encoding="utf-8")) if ARM_C.is_file() else {}
    handcheck_file = OUT / f"PROTOTYPE3_ARM_C_HANDCHECK_{DATE}.json"
    handcheck = json.loads(handcheck_file.read_text(encoding="utf-8")) \
        if handcheck_file.is_file() else []
    effort = json.loads(EFFORT.read_text(encoding="utf-8")) if EFFORT.is_file() else {}
    scope_fix = json.loads(SCOPE_FIX.read_text(encoding="utf-8")) if SCOPE_FIX.is_file() else {}
    answers = [json.loads(line) for line in ANSWER_FILE.open(encoding="utf-8")] \
        if ANSWER_FILE.is_file() else []
    missed_by: Counter = Counter()
    for doc in (recall.get("per_doc") or []):
        for miss in doc.get("misses") or []:
            missed_by[miss["table"]] += 1
    docs, chunks = _scope_docs()
    doc_type_by = {doc_id: doc["doc_type"] for doc_id, doc in docs.items()}
    whole_tokens_by = defaultdict(int)
    for chunk in chunks:
        whole_tokens_by[chunk["doc_id"]] += max(1, round(len(chunk["body"] or "") / 4))
    con = _connect()
    arm_a, arm_b = _arm_rows(con, "A"), _arm_rows(con, "B")
    calls = [dict(r) for r in con.execute("SELECT * FROM extract_call")]
    build_calls = [c for c in calls if c["table_name"] in x.TABLES]  # Arm B extraction reads
    tables = {}
    for table in x.TABLES:
        src = Counter()
        columns = {row[1] for row in con.execute(f"PRAGMA table_info({table})")}
        if "source" in columns:
            for row in con.execute(f"SELECT source, COUNT(*) n FROM {table} GROUP BY source"):
                src[row["source"]] = row["n"]
        else:
            # no source column: rows the BSE feed wrote name it in source_doc_id
            feed = int(con.execute(f"SELECT COUNT(*) FROM {table} "
                                   "WHERE source_doc_id LIKE 'bse_ann:%'").fetchone()[0])
            src["bse_ann"] = feed
            src["chunks_v3"] = _table_count(con, table) - feed
        tables[table] = {"rows": _table_count(con, table), **src}
    run = dict(con.execute("SELECT * FROM extract_run ORDER BY started_at DESC LIMIT 1").fetchone())
    con.close()
    tokens_in = sum(int(c["in_tok"] or 0) for c in calls)
    tokens_out = sum(int(c["out_tok"] or 0) for c in calls)
    cost = sum(float(c["cost_usd"] or 0) for c in calls)
    wall = sum(int(c["ms"] or 0) for c in calls) / 1000.0
    pages_sent = sum(int(c["pages_sent"] or 0) for c in calls)
    pages_docs = sum(v["pages"] for v in docs_stats["docs"].values())
    docs_sent = {c["doc_id"] for c in build_calls}
    per_type = defaultdict(lambda: {"docs": 0, "in_tok": 0, "out_tok": 0, "cost_usd": 0.0,
                                    "ms": 0, "pages_sent": 0})
    per_type_docs: dict[str, set] = defaultdict(set)
    for call in build_calls:
        kind = doc_type_by.get(call["doc_id"], "other")
        row = per_type[kind]
        row["docs"] += 1
        per_type_docs[kind].add(call["doc_id"])
        row["in_tok"] += int(call["in_tok"] or 0)
        row["out_tok"] += int(call["out_tok"] or 0)
        row["cost_usd"] += float(call["cost_usd"] or 0)
        row["ms"] += int(call["ms"] or 0)
        row["pages_sent"] += int(call["pages_sent"] or 0)
    for kind, ids in per_type_docs.items():
        per_type[kind]["documents"] = len(ids)  # cost per document, not per call
    whole_read = sum(whole_tokens_by.get(doc_id, 0) for doc_id in docs_sent)
    company_by_doc = {doc_id: SYMBOLS.get(doc["isin"], doc["isin"]) for doc_id, doc in docs.items()}
    per_company = defaultdict(lambda: {"calls": 0, "in_tok": 0, "out_tok": 0, "cost_usd": 0.0,
                                       "ms": 0, "pages_sent": 0})
    for call in build_calls:
        row = per_company[company_by_doc.get(call["doc_id"], "other")]
        row["calls"] += 1
        row["in_tok"] += int(call["in_tok"] or 0)
        row["out_tok"] += int(call["out_tok"] or 0)
        row["cost_usd"] += float(call["cost_usd"] or 0)
        row["ms"] += int(call["ms"] or 0)
        row["pages_sent"] += int(call["pages_sent"] or 0)
    build_in = sum(int(c["in_tok"] or 0) for c in build_calls)
    by_step = defaultdict(lambda: {"calls": 0, "in_tok": 0, "out_tok": 0, "cost_usd": 0.0})
    for call in calls:
        row = by_step[call["table_name"] or "unknown"]
        row["calls"] += 1
        row["in_tok"] += int(call["in_tok"] or 0)
        row["out_tok"] += int(call["out_tok"] or 0)
        row["cost_usd"] += float(call["cost_usd"] or 0)
    for row in by_step.values():
        row["cost_usd"] = round(row["cost_usd"], 4)
    measurement = {
        "scope": docs_stats, "tables": tables,
        "arm_a": {"tables": arm_a, "rows": sum(v["rows_added"] for v in arm_a.values())},
        "arm_b": {"tables": arm_b, "rows": sum(v["rows_added"] for v in arm_b.values())},
        "calls": {"calls": len(calls), "in_tok": tokens_in, "out_tok": tokens_out,
                  "cost_usd": round(cost, 4), "wall_s": round(wall, 1),
                  "build_calls": len(build_calls), "build_in_tok": build_in,
                  "build_cost_usd": round(sum(float(c["cost_usd"] or 0)
                                              for c in build_calls), 4),
                  "by_step": dict(sorted(by_step.items())),
                  "docs_read": len(docs_sent), "pages_sent": pages_sent,
                  "pages_in_documents": pages_docs,
                  "whole_tokens_read": whole_read,
                  "in_tok_pct_of_whole": round(100.0 * build_in / whole_read, 2)
                  if whole_read else None,
                  "per_doc_type": {k: {**v, "cost_usd": round(v["cost_usd"], 4)}
                                   for k, v in sorted(per_type.items())},
                  "per_company": {k: {**v, "cost_usd": round(v["cost_usd"], 4)}
                                  for k, v in sorted(per_company.items())}},
        "run": run, "accuracy": accuracy, "recall": recall, "arm_c": arm_c,
        "recall_missed_by_table": dict(missed_by),
        "arm_c_handcheck": handcheck, "effort": effort, "scope_fix": scope_fix,
        "answers": {"rows": len(answers),
                    "answered": sum(1 for a in answers if a["status"] == "answered"),
                    "evidence": sum(1 for a in answers if a["status"] == "evidence"),
                    "not_found": sum(1 for a in answers if a["status"] == "not_found")},
        "machine": {"host": os.environ.get("COMPUTERNAME"), "python": sys.version.split()[0]},
    }
    measurement["forecast"] = _forecast(per_type)
    MEASURE.write_text(json.dumps(measurement, indent=1, default=str), encoding="utf-8")
    text = _report_markdown(measurement)
    REPORT_FILE.write_text(text, encoding="utf-8")
    return {"report": str(REPORT_FILE), "lines": len(text.splitlines()),
            "measure": str(MEASURE)}


def _held_documents() -> dict:
    """Held documents by type: the 60-name pilot universe and the whole chunks store."""
    pilot = Counter()
    import csv
    if x.UNIVERSE.is_file():
        for row in csv.DictReader(x.UNIVERSE.open(encoding="utf-8")):
            for kind in ("annual_report", "concall", "deck", "results_notes"):
                pilot[kind] += int(row.get(kind) or 0)
    whole, whole_isins = Counter(), defaultdict(set)
    try:
        con = x.connect(x.chunk_store_path())
        for row in con.execute("SELECT doc_type, isin, COUNT(*) n FROM doc GROUP BY doc_type, isin"):
            whole[row["doc_type"]] += int(row["n"])
            whole_isins[row["doc_type"]].add(row["isin"])
        con.close()
    except sqlite3.Error:
        pass
    return {"pilot60_docs": dict(pilot), "universe_docs": dict(whole),
            "universe_isins": {k: len(v) for k, v in whole_isins.items()}}


def _forecast(per_type: dict) -> dict:
    held = _held_documents()
    measured = {}
    for kind, row in per_type.items():
        documents = row.get("documents") or row.get("docs")
        if kind in ("annual_report", "concall", "deck", "results_notes", "announcement") \
                and documents:
            measured[kind] = {"cost_per_doc": row["cost_usd"] / documents,
                              "in_tok_per_doc": row["in_tok"] / documents,
                              "documents": documents}
    def total(counts: dict) -> dict:
        low = sum(counts.get(k, 0) * v["cost_per_doc"] for k, v in measured.items())
        return {"low_usd": round(low, 2), "high_usd": round(low * 2, 2)}
    return {"measured": measured, "pilot60": total(held["pilot60_docs"]),
            "universe": total(held["universe_docs"]), "held": held}


def _report_markdown(m: dict) -> str:
    scope = m["scope"]["docs"]
    calls = m["calls"]
    lines = [
        "# Prototype-3 extraction report (BAJFINANCE, HINDALCO, KEC)", "",
        f"Generated {DATE} by `python -m reality_engine.pilot.proto3 report`; every number "
        "here reads from `extract_proto3.db` (`extract_arm`, `extract_call`, the 16 measure "
        "tables) or the JSON files named beside it.", "",
        "## 1. Scope and documents held", "",
        "| company | doc type | docs | pages | chunks | chars |", "|---|---|---:|---:|---:|---:|",
    ]
    for key, row in scope.items():
        company, doc_type = key.split("|")
        if doc_type in DOC_TYPES:
            lines.append(f"| {company} | {doc_type} | {row['docs']} | {row['pages']} | "
                         f"{row['chunks']} | {row['chars']:,} |")
    lines += ["", f"Total documents in scope: {m['scope']['total_docs']}, chunks "
              f"{m['scope']['total_chunks']:,}. Scope: held documents first known on/after "
              f"{m['scope']['since']}. The table lists the four extraction document types; the "
              "total also counts the 8 announcements in scope (feed metadata, no passages).", "",
              "## 2. Per measure, by arm", "",
              "| table | rows | results_xbrl | chunks_v3 | bse_ann | rows added by Arm A | "
              "rows added by Arm B |", "|---|---:|---:|---:|---:|---:|---:|"]
    for table, row in m["tables"].items():
        lines.append(f"| `{table}` | {row['rows']} | {row.get('results_xbrl', 0)} | "
                     f"{row.get('chunks_v3', 0)} | {row.get('bse_ann', 0)} | "
                     f"{m['arm_a']['tables'].get(table, {}).get('rows_added', 0)} | "
                     f"{m['arm_b']['tables'].get(table, {}).get('rows_added', 0)} |")
    lines += ["", f"Arm A total: {m['arm_a']['rows']} rows, 0 model calls. "
              f"Arm B total: {m['arm_b']['rows']} rows added.", ""]
    fix = m.get("scope_fix") or {}
    if fix:
        pre, tok, post = fix["pre_fix"], fix["model_tokens"], fix["post_fix"]
        lines += [f"### The `rating_action` scope defect (found {fix['found']})", "",
                  f"- **In scope?** No. The store held {pre['rows']} rows for {pre['companies']} "
                  f"companies; {pre['out_of_scope_isins']} companies ({pre['out_of_scope_rows']} "
                  "rows) are outside the three-name prototype.",
                  f"- **Model tokens?** None produced those rows: they came from the code-only BSE "
                  "announcement feed (a read of `bse_announcements.db`). The one model call on the "
                  f"table ({tok['in_tok']:,} in / {tok['out_tok']:,} out, ${tok['cost_usd']}) "
                  f"accepted {tok['rows_accepted']} rows.",
                  f"- **Cause:** {fix['root_cause']}. **Fix:** {fix['fix']}.",
                  f"- **Excluded now:** every count, accuracy sample and forecast below is computed "
                  f"after the prune. `rating_action` holds {post['rows']} rows for "
                  f"{post['companies']} companies, {post['out_of_scope_rows']} out of scope. "
                  f"Record: `{SCOPE_FIX.name}`.", ""]
    lines += ["## 3. Reading cost", "",
              f"- Reader calls logged: {calls['calls']} (one row each in `extract_call`), of "
              f"which {calls.get('build_calls', 0)} are Arm B extraction reads; the recall and "
              "effort reads are logged the same way (Arm C's 9 deck calls predate the ledger; see "
              "open problems).",
              f"- Tokens in / out: {calls['in_tok']:,} / {calls['out_tok']:,}. The Go "
              "chat-completions response used here exposes prompt and completion tokens only; "
              "reasoning tokens are not split out, so `out` includes any reasoning.",
              f"- Cost at Go off-peak rates ($0.15/M in, $0.60/M out): ${calls['cost_usd']:.4f}.",
              f"- Sum of per-call time (not wall clock): {calls['wall_s']:.1f} s; documents read: "
              f"{calls['docs_read']}; passages' pages sent: {calls['pages_sent']} of "
              f"{calls['pages_in_documents']} pages held.",
              f"- Arm B input tokens as a share of the whole text of the documents read: "
              f"{calls['in_tok_pct_of_whole']}% ({calls.get('build_in_tok', 0):,} of "
              f"{calls['whole_tokens_read']:,}).",
              f"- Reader spend cap: ${x.SPEND_CAP:.2f}; input-token cap: {x.TOKEN_CAP:,}. "
              f"Errors: {m['run'].get('notes', '')}", "",
              "| doc type | calls | pages sent | in tokens | out tokens | cost USD | wall s |",
              "|---|---:|---:|---:|---:|---:|---:|"]
    for kind, row in (m["calls"].get("per_doc_type") or {}).items():
        lines.append(f"| {kind} | {row['docs']} | {row.get('pages_sent', 0)} | "
                     f"{row['in_tok']:,} | {row['out_tok']:,} | "
                     f"{row['cost_usd']} | {row['ms'] / 1000:.1f} |")
    lines += ["", "Arm B extraction reads by company:", "",
              "| company | calls | pages sent | in tokens | out tokens | cost USD | wall s |",
              "|---|---:|---:|---:|---:|---:|---:|"]
    for company, row in (m["calls"].get("per_company") or {}).items():
        lines.append(f"| {company} | {row['calls']} | {row.get('pages_sent', 0)} | "
                     f"{row['in_tok']:,} | {row['out_tok']:,} | "
                     f"{row['cost_usd']} | {row['ms'] / 1000:.1f} |")
    lines += ["", "Spend by step (`extract_call.table_name`):", "",
              "| step | calls | in tokens | out tokens | cost USD |", "|---|---:|---:|---:|---:|"]
    for label, row in (m["calls"].get("by_step") or {}).items():
        lines.append(f"| `{label}` | {row['calls']} | {row['in_tok']:,} | {row['out_tok']:,} | "
                     f"{row['cost_usd']} |")
    lines += ["", "## 4. Accuracy (30 random rows per arm, read back to the source page)", ""]
    for arm in ("A", "B"):
        block = m["accuracy"].get(arm) or {}
        lines.append(f"- Arm {arm}: {block.get('right', 0)}/{block.get('n', 0)} RIGHT "
                     f"(population {m['accuracy'].get('population', {}).get(arm, 0)} rows).")
    lines += ["", "Checks: the quote is verbatim on the source page, the row's number is printed "
              "on that page, and XBRL rows re-read the concept/context value from "
              "`results_xbrl.facts` (a derived tax-rate row re-reads both facts and recomputes "
              "the percentage; a feed row is checked against its BSE announcement headline). "
              "Row-level verdicts: `PROTOTYPE3_ACCURACY_2026-11-01.json`.", "",
              "## 5. Recall (3 documents per type per company, one reader pass per document)", ""]
    if m["recall"]:
        lines.append(f"- documents read: {m['recall'].get('docs')} of the 36 planned (a company "
                     "with fewer than three held documents of a type, or a document with no "
                     "number-dense passage, is skipped); baseline rows accepted: "
                     f"{m['recall'].get('baseline_rows')}; missed by the store: "
                     f"{m['recall'].get('missed')}.")
        for doc in (m["recall"].get("per_doc") or [])[:12]:
            lines.append(f"  - {doc['symbol']} {doc['doc_type']}: baseline {doc['baseline_rows']}, "
                         f"missed {doc['missed']} ({doc['pages_read']} number-dense pages read)")
        if m.get("recall_missed_by_table"):
            lines.append("- missed by table: " + ", ".join(
                f"`{table}` {count}" for table, count in sorted(m["recall_missed_by_table"].items())))
        examples = [(doc["symbol"], doc["doc_type"], miss)
                    for doc in (m["recall"].get("per_doc") or [])
                    for miss in (doc.get("misses") or [])][:3]
        for symbol, doc_type, miss in examples:
            lines.append(f"  - e.g. {symbol} {doc_type} `{miss['table']}`: "
                         + json.dumps(miss.get("row") or {}, sort_keys=True, default=str)[:220])
    else:
        lines.append("- not run")
    lines += ["", "## 6. Arm C (decks: Haiku vs DeepSeek vs CPU OCR)", ""]
    if m["arm_c"]:
        pages = m["arm_c"].get("pages") or []
        summary = m["arm_c"].get("summary") or {}
        lines.append(f"- pages: {len(pages)}; Haiku facts: "
                     f"{summary.get('haiku_facts')}; Haiku values found in OCR text: "
                     f"{summary.get('haiku_values_in_ocr')} "
                     f"({round(100.0 * summary.get('haiku_values_in_ocr', 0) / max(summary.get('haiku_facts', 0), 1), 1)}%); "
                     f"DeepSeek rows: {summary.get('deepseek_rows')}; OCR misses: "
                     f"{summary.get('ocr_miss')}; DeepSeek-only values: "
                     f"{summary.get('deepseek_extra')}; Haiku values DeepSeek did not repeat: "
                     f"{summary.get('deepseek_missing')}.")
        lines.append(f"- hand-checked disagreements: {len(m['arm_c_handcheck'])}; verdicts: "
                     f"{dict(Counter(h.get('verdict') for h in m['arm_c_handcheck']))}.")
        lines.append("- Reading: Haiku's dense-table values are mostly right but its narrative-"
                     "slide facts include digits lifted out of period labels ('Q4' -> 4.0); "
                     "CPU OCR loses chart labels and dense table rows; DeepSeek keeps precision "
                     "by quoting verbatim but returns a subset on time-series pages.")
    else:
        lines.append("- not run")
    lines += ["", "## 7. Effort comparison (30 passages at low and max)", ""]
    if m["effort"]:
        for arm in ("low", "max"):
            block = m["effort"][arm]
            errors = block.get("errors") or {}
            lines.append(f"- {arm}: {block['calls']} calls, in {block['in_tok']:,}, out "
                         f"{block['out_tok']:,}, ${block['cost_usd']}, {block['wall_s']} s, "
                         f"rows {block['rows']}, wrong {block['wrong']}"
                         + (f"; call errors {errors}" if errors else "") + ".")
        lines.append(f"- rows found in both: {m['effort']['found_in_both']}; only low: "
                     f"{m['effort']['only_low']}; only max: {m['effort']['only_max']}. The compare "
                     "key is the quote plus period, so two phrasings of one fact count as two rows.")
        lines.append("- The low arm's first pass (30 calls, $0.057) was discarded on a row-pairing "
                     "defect; both passes are in `extract_call` under `effort`, only the second is "
                     "reported.")
    else:
        lines.append("- not run")
    lines += ["", "## 8. Cost forecast", ""]
    forecast = m.get("forecast") or {}
    build_cost = float(calls.get("build_cost_usd") or 0.0)
    per_company_cost = build_cost / max(len(PROTO_ISINS), 1)
    lines += [f"Arm B build cost for the three companies: ${build_cost:.4f} and "
              f"{calls.get('build_in_tok', 0):,} input tokens; every reader step together "
              f"(build, recall, effort, deck comparison): ${calls['cost_usd']:.4f}. Scaling by "
              "held document counts is the only honest forecast from this sample:",
              "",
              f"- 60 names: ${forecast.get('pilot60', {}).get('low_usd')} low, "
              f"${forecast.get('pilot60', {}).get('high_usd')} high (2x for harder documents).",
              f"- Whole universe: ${forecast.get('universe', {}).get('low_usd')} low, "
              f"${forecast.get('universe', {}).get('high_usd')} high.",
              "- Measured per document: "
              + ", ".join(f"{k} ${v['cost_per_doc']:.3f}"
                          for k, v in (forecast.get("measured") or {}).items())
              + f". Held documents: pilot-60 {forecast.get('held', {}).get('pilot60_docs')}, "
                f"universe {forecast.get('held', {}).get('universe_docs')}.",
              f"- A flat 60-name extrapolation from the three companies would be "
              f"${per_company_cost * 20:.2f}; the document-count forecast above is the one to use.",
              "- Model tokens above are the reader. Worker-agent tokens are the harness's own "
              "tokens and are not visible to this process; they are a separate line item.", "",
              "## 9. Answers prepared for Claude", "",
              f"- rows in `{ANSWER_FILE.name}`: {m['answers']['rows']}; answered with rows: "
              f"{m['answers']['answered']}; evidence passages only: {m['answers']['evidence']}; "
              f"not found: {m['answers']['not_found']}.",
              "- DeepSeek did not grade or rewrite the bank; each row carries quote, page, "
              "period and the formula when computed.", "",
              "## 10. Machine split", "",
              f"- `{m['machine']['host']}` (Python {m['machine']['python']}): Arm A code, Arm B "
              "reader, CPU RapidOCR, measurement and report.",
              "- Haiku deck facts: held store `deck_figures.db` (produced by the deck pipeline "
              "before this run); this run only read them.", "",
              "## 11. Open problems", "",
              "- The reader's Go response does not expose reasoning tokens separately.",
              "- The Go account does not expose a usage/allowance endpoint here, so the percent "
              "of the allowance is not reported; only the brief's $1.50 cap is enforced.",
              "- `deck_figures` carries facts but no page text; Arm C OCR is the only way to "
              "re-check a slide that the text layer does not reproduce.",
              "- The chunks store attached the FY24 filing date (2024-06-26) to BAJFINANCE's "
              "FY26 annual report (sha256 5535038a...); `reconcile_known_at` now takes the date "
              "from `ar_docs` (2026-07-07) before extraction.",
              "- Three runs sit outside the per-call ledger: the aborted effort-max pass (killed on "
              "the row-pairing defect; the 9 read timeouts in the recorded max arm are its tail), "
              "the `supply_link` tail of the Arm B build (killed after its last committed table, "
              "no rows), and Arm C's 9 deck calls (made before `extract_call` existed). Together "
              "about $0.07-0.08, so real reader spend is about $1.16 against the $1.50 cap.", "",
              "## 12. Docs updated", "",
              "- `tasks/STATE.md` — prototype-3 measured numbers and the `rating_action` fix.",
              "- `tasks/pilot60/EXTRACTION_REPORT.md` — scope note: 16 tables, prototype-3 numbers "
              "live in this file.",
              "- `tasks/pilot60/PROTOTYPE3_REPORT_2026-11-01.md` (this file), "
              "`PROTOTYPE3_ANSWERS_2026-11-01.jsonl`, `PROTOTYPE3_MEASUREMENTS_2026-11-01.json`, "
              "`PROTOTYPE3_ACCURACY_2026-11-01.json`, `PROTOTYPE3_RECALL_2026-11-01.json`, "
              "`PROTOTYPE3_ARM_C_2026-11-01.json`, `PROTOTYPE3_ARM_C_HANDCHECK_2026-11-01.json`, "
              "`PROTOTYPE3_EFFORT_2026-11-01.json`, `PROTOTYPE3_SCOPE_2026-11-01.json`.", ""]
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- dry run
def cmd_dryrun(samples: int = 10) -> dict:
    """Read-only: re-check the stored rows against the contracts, then cost recall.

    No model calls and no write to any store.  Every stored row goes through
    ``contracts.check``; kept/rejected are counted per table and per measure, and
    a few rejects are quoted with their reason.  ``extract60.whole_page_estimate``
    then prices one pass over the three companies with the number-dense pages
    sent whole, so the recall fix is costed before a reader call.
    """
    from reality_engine import contracts
    from reality_engine.db.readonly import connect_ro
    # A worktree has no gitignored DB: read the live one under REALITY_DATA_ROOT.
    db = DB if DB.is_file() else x.data_root() / "extract_proto3.db"
    if not db.is_file():
        raise SystemExit(f"{db} is missing")
    con = connect_ro(db, timeout_s=60)
    con.row_factory = sqlite3.Row
    per: dict[str, dict] = {}
    rejects_by_measure: Counter = Counter()
    pending: list[dict] = []
    try:
        for table in x.TABLES:
            kept, rejected = 0, Counter()
            cursor = con.execute(f"SELECT * FROM {table}")
            for raw in (cursor.fetchall() if cursor is not None else []):
                row = {str(key): raw[key] for key in raw.keys()}
                ok, reason = contracts.check(table, row)
                if ok:
                    kept += 1
                    continue
                rejected[reason] += 1
                if len(pending) < samples * 3:
                    pending.append({"table": table, "reason": reason,
                                    "row": {k: row.get(k) for k in
                                            ("isin", "metric", "line_item", "item", "product",
                                             "period_end", "value", "value_cr", "amount_cr",
                                             "quantity", "capacity", "capacity_unit", "unit",
                                             "direction", "page", "quote")
                                            if row.get(k) is not None}})
                rejects_by_measure[contracts.measure_of(reason)] += 1
            n_rejected = sum(rejected.values())
            per[table] = {"kept": kept, "rejected": n_rejected,
                          "rejected_percent": round(
                              100.0 * n_rejected / max(1, kept + n_rejected), 1),
                          "reasons": dict(rejected.most_common(5))}
    finally:
        con.close()
    docs, chunks = _scope_docs()
    estimate = x.whole_page_estimate(docs, _by_doc(chunks))
    out = {"db": str(db), "read_only": True, "per_table": per,
           "totals": {"kept": sum(v["kept"] for v in per.values()),
                      "rejected": sum(v["rejected"] for v in per.values())},
           "rejects_by_measure": dict(sorted(rejects_by_measure.items(),
                                             key=lambda kv: (-kv[1], kv[0]))),
           "sample_rejects": pending[:samples],
           "recall_estimate": estimate}
    (SCRATCH / "dryrun.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    return out


# --------------------------------------------------------------------------- main
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["docs", "scope", "accuracy", "recall", "arm-c",
                                            "effort", "bank", "report", "dryrun", "all"])
    parser.add_argument("--n", type=int, default=30)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args(argv)
    _configure()
    if args.command in ("docs", "all"):
        print(json.dumps(cmd_docs(), indent=1)[:4000])
    if args.command in ("scope", "all"):
        print(json.dumps(cmd_scope(), indent=1))
    if args.command in ("accuracy", "all"):
        print(json.dumps(cmd_accuracy(args.n), indent=1))
    if args.command in ("recall", "all"):
        print(json.dumps(cmd_recall(workers=args.workers), indent=1))
    if args.command in ("arm-c", "all"):
        print(json.dumps(cmd_arm_c(), indent=1))
    if args.command in ("effort", "all"):
        print(json.dumps(cmd_effort(args.n, args.workers), indent=1))
    if args.command in ("bank", "all"):
        print(json.dumps(cmd_bank(), indent=1))
    if args.command in ("report", "all"):
        print(json.dumps(cmd_report(), indent=1))
    if args.command in ("dryrun", "all"):
        out = cmd_dryrun()
        for table, row in out["per_table"].items():
            print(f"{table}: kept {row['kept']}, rejected {row['rejected']} "
                  f"({row['rejected_percent']}%)", flush=True)
        print(json.dumps({k: out[k] for k in ("db", "read_only", "totals",
                                              "rejects_by_measure", "sample_rejects",
                                              "recall_estimate")}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
