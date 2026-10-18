"""Query speed check (PIPELINE_TODO Q1, 2026-10-19): a fixed list of the queries backtests and analysis run, each with a
time limit. Every query runs twice on a fresh read-only connection: `first` (cold if this is the first run after a
reboot, see boot_age_min) and `warm`. A query passes when both runs are under its limit.

Results: one JSON line per query per run appended to data/logs/query_speed.jsonl; a short markdown summary in
data/logs/query_speed_report.md, which the resource watchdog appends to its report (over-limit queries listed).
Run nightly (step in run_eod_market) and after every index / schema change. Read-only: never writes to a database.
A query is aborted at ABORT_X x its limit (min 20 s) so a missing index cannot hang the nightly job.

    python -m reality_engine.scripts.query_speed_check [--only name1,name2] [--no-log]
"""
import argparse
import json
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "reality_engine" / "data"
LOGS = DATA / "logs"
OUT = LOGS / "query_speed.jsonl"
REPORT = LOGS / "query_speed_report.md"
ABORT_X = 10

EI = DATA / "equity_intelligence.db"
RX = DATA / "results_xbrl.db"
AR = DATA / "ar_facts.db"
DK = DATA / "deck_figures.db"
CC = DATA / "concall_facts.db"

# Fixed probes: a company every store covers (results by trading ISIN via filings_isin), and a full quarter / day that every store has.
ISIN, SYMBOL = "INE511C01022", "POONAWALLA"
DAY = "2026-10-16"
QUARTER_END = "2024-12-31"

QUERIES = [
    # name, db, limit_s, sql, params
    ("price_one_stock_nse", EI, 0.1,
     "SELECT date, open, high, low, close, volume, turnover_lacs, delivery_pct FROM mkt_nse_full_daily "
     "WHERE symbol = ? AND series IN ('EQ','BE','BZ','SM','ST') ORDER BY date", (SYMBOL,)),
    ("price_one_stock_bse", EI, 0.1,
     "SELECT date, open, high, low, close, volume, turnover_inr FROM mkt_bse_eq_daily WHERE isin = ? ORDER BY date",
     (ISIN,)),
    ("price_market_one_day", EI, 0.5,
     "SELECT symbol, series, close, volume, turnover_lacs FROM mkt_nse_full_daily WHERE date = ?", (DAY,)),
    ("traded_value_20d_all", EI, 2.0,
     "SELECT symbol, AVG(turnover_lacs), COUNT(*) FROM mkt_nse_full_daily WHERE date IN "
     "(SELECT DISTINCT date FROM mkt_nse_full_daily WHERE date <= ? ORDER BY date DESC LIMIT 20) "
     "AND series IN ('EQ','BE','BZ','SM','ST') GROUP BY symbol", (DAY,)),
    ("results_one_company", RX, 0.1,
     "SELECT f.period_end, x.concept, x.context, x.value FROM filings_isin i JOIN filings f ON f.file = i.file "
     "JOIN facts x ON x.file = f.file WHERE i.isin = ? AND x.concept IN ('RevenueFromOperations','ProfitLossForPeriod','ProfitBeforeTax')",
     (ISIN,)),
    ("results_market_one_quarter", RX, 2.0,
     "SELECT f.isin, x.concept, x.value FROM filings f JOIN facts x ON x.file = f.file "
     "WHERE f.period_end = ? AND x.concept IN ('RevenueFromOperations','ProfitLossForPeriod')", (QUARTER_END,)),
    ("ar_one_company_category", AR, 0.5,
     "SELECT fiscal_year, item, value, unit, period, quote FROM ar_facts WHERE isin = ? AND category = 'borrowings'",
     (ISIN,)),
    ("ar_market_item_search_fts", AR, 1.0,
     "SELECT a.isin, a.fiscal_year, a.item, a.value FROM ar_facts_fts f JOIN ar_facts a ON a.rowid = f.rowid "
     "WHERE ar_facts_fts MATCH ? LIMIT 5000", ('item:"order book"',)),
    ("deck_one_company_kpis", DK, 0.5,
     "SELECT p.known_at, f.metric, f.period, f.value, f.unit FROM pages p JOIN facts f "
     "ON f.sha256 = p.sha256 AND f.page_no = p.page_no WHERE p.isin = ?", (ISIN,)),
    ("deck_market_metric_search", DK, 1.0,   # facts_metric_fts (build_query_indexes.py, Q3)
     "SELECT p.isin, p.known_at, f.metric, f.value FROM facts_metric_fts x JOIN facts f ON f.rowid = x.rowid "
     "JOIN pages p ON p.sha256 = f.sha256 AND p.page_no = f.page_no AND p.prompt_version = f.prompt_version "
     "WHERE facts_metric_fts MATCH ? LIMIT 5000", ('"order book"',)),
    ("concall_market_text_search", CC, 0.5,  # cc_items_fts (Q3)
     "SELECT i.isin, i.filed_at, i.metric, i.value FROM cc_items_fts x JOIN cc_items i ON i.rowid = x.rowid "
     "WHERE cc_items_fts MATCH ? LIMIT 2000", ('"order book"',)),
    ("policy_events_search", EI, 0.5,        # policy_events_fts + published_at index (Q3)
     "SELECT e.published_at, e.policy_name, e.stage FROM policy_events_fts x JOIN policy_events e ON e.id = x.rowid "
     "WHERE policy_events_fts MATCH ? ORDER BY e.published_at", ("customs OR duty",)),
    ("chunks_fts_keyword", EI, 0.5,
     "SELECT chunk_id, symbol, document_date FROM intelligence_fts WHERE intelligence_fts MATCH ? LIMIT 200",
     ('"order book" AND execution',)),
    ("concall_facts_one_company", CC, 0.1,
     "SELECT i.filed_at, i.metric, i.value, i.unit, i.period, i.direction, c.computed_direction FROM cc_items i "
     "LEFT JOIN cc_item_checks c USING (doc_id, list_name, idx) WHERE i.isin = ?", (ISIN,)),
]
VECTOR = ("vector_search_top20", 1.0)   # query embedding + dot product over the append store (store load reported apart)
PENDING = [("state_isin_t", 1.0, "after Q4 (reality_engine/query/state.py)")]


def boot_age_min():
    try:
        import psutil
        return round((time.time() - psutil.boot_time()) / 60)
    except Exception:
        return None


def time_sql(db, limit, sql, params):
    cap = max(20.0, ABORT_X * limit)
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=30)
    t0 = time.perf_counter()
    con.set_progress_handler(lambda: 1 if time.perf_counter() - t0 > cap else 0, 100_000)
    try:
        rows = len(con.execute(sql, params).fetchall())
        return time.perf_counter() - t0, rows, None
    except sqlite3.OperationalError as e:
        msg = "aborted at cap" if "interrupt" in str(e) else str(e)[:200]
        return time.perf_counter() - t0, None, msg
    finally:
        con.close()


def run_vector():
    from reality_engine.db.vector_store import VectorStoreManager
    t0 = time.perf_counter()
    vs = VectorStoreManager()
    load_s = time.perf_counter() - t0
    vs.embed("warm up the model", is_query=True)    # model load is not part of the query
    times, rows = [], 0
    for q in ("order book execution timeline", "margin guidance for next year"):
        t0 = time.perf_counter()
        rows = len(vs.search(q, top_k=20))
        times.append(time.perf_counter() - t0)
    return load_s, times, rows, len(vs._rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--no-log", action="store_true")
    a = ap.parse_args()
    only = {s.strip() for s in a.only.split(",") if s.strip()}
    run_id = datetime.now().isoformat(timespec="seconds")
    boot = boot_age_min()
    recs = []
    for name, db, limit, sql, params in QUERIES:
        if only and name not in only:
            continue
        first, rows, err = time_sql(db, limit, sql, params)
        warm, rows2, err2 = (first, rows, err) if err else time_sql(db, limit, sql, params)
        ok = err is None and err2 is None and first <= limit and warm <= limit
        recs.append({"run_id": run_id, "name": name, "db": db.name, "limit_s": limit, "first_s": round(first, 4),
                     "warm_s": round(warm, 4), "rows": rows, "ok": ok, "error": err or err2, "boot_age_min": boot})
    if not only or VECTOR[0] in only:
        try:
            load_s, (first, warm), rows, n = run_vector()
            recs.append({"run_id": run_id, "name": VECTOR[0], "db": "lancedb/vectors.f32", "limit_s": VECTOR[1],
                         "first_s": round(first, 4), "warm_s": round(warm, 4), "rows": rows,
                         "ok": first <= VECTOR[1] and warm <= VECTOR[1], "error": None, "boot_age_min": boot,
                         "store_load_s": round(load_s, 1), "store_rows": n})
        except Exception as e:   # noqa: BLE001 - report, do not fail the whole check
            recs.append({"run_id": run_id, "name": VECTOR[0], "db": "lancedb", "limit_s": VECTOR[1], "first_s": None,
                         "warm_s": None, "rows": None, "ok": False, "error": repr(e)[:200], "boot_age_min": boot})
    for name, limit, why in PENDING:
        if not only or name in only:
            recs.append({"run_id": run_id, "name": name, "limit_s": limit, "ok": None, "pending": why})

    print(f"query speed check {run_id} (boot age {boot} min)")
    for r in recs:
        if r.get("pending"):
            print(f"  PEND {r['name']:<28} limit {r['limit_s']:>5}s  {r['pending']}")
            continue
        extra = f"  store load {r['store_load_s']}s / {r['store_rows']} rows" if "store_load_s" in r else ""
        print(f"  {'ok  ' if r['ok'] else 'SLOW'} {r['name']:<28} limit {r['limit_s']:>5}s  first {r['first_s']}s  "
              f"warm {r['warm_s']}s  rows {r['rows']}{' ' + r['error'] if r['error'] else ''}{extra}")
    slow = [r for r in recs if r.get("ok") is False]
    if not a.no_log:
        LOGS.mkdir(parents=True, exist_ok=True)
        with OUT.open("a", encoding="utf-8") as fh:
            for r in recs:
                fh.write(json.dumps(r) + "\n")
        lines = [f"## Query speed check ({run_id}, boot age {boot} min): {len(recs) - len(slow)} of {len(recs)} "
                 f"under limit or pending"]
        lines += [f"- **over limit** {r['name']}: first {r['first_s']} s / warm {r['warm_s']} s vs {r['limit_s']} s"
                  f"{' (' + r['error'] + ')' if r.get('error') else ''}" for r in slow] or ["- none over limit"]
        REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("ALL UNDER LIMIT" if not slow else f"{len(slow)} OVER LIMIT")
    return 1 if slow else 0


if __name__ == "__main__":
    sys.exit(main())
