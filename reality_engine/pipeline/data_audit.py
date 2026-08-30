"""
Data Pipeline Readiness Audit
=============================

Read-only diagnostic that answers one question: **is the data pipeline actually ready to
run the top-down funnel?**

It checks six things the checkpoint audit does not:

1. PRICE      - session coverage, gaps, per-session row counts, staleness
2. UNIVERSE   - master company integrity and Nifty tier flags
3. FUNDAMENTALS - quarterly / annual / forensic coverage across the target universe
4. DOCUMENTS  - corporate filings and RAG chunks, plus how many chunks are embedded
5. CAUSAL     - macro events, ripple DAG depth, top-down funnel tables
6. CACHE      - on-disk bhavcopy / PDF / inbox artifacts

Usage:
    python reality_engine/pipeline/data_audit.py
    python reality_engine/pipeline/data_audit.py --net     # also probe NSE/BSE reachability
    python reality_engine/pipeline/data_audit.py --json    # machine-readable output

Exit code is 0 when no CRITICAL failures, 1 otherwise.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = PROJECT_ROOT / "reality_engine" / "data" / "equity_intelligence.db"
DATA_DIR = PROJECT_ROOT / "reality_engine" / "data"

# A dataset older than this many calendar days is considered stale for EOD use.
STALE_AFTER_DAYS = 7

# NSE trading holidays falling on weekdays. Without this, every market holiday is
# misreported as a missing ingestion session.
# NOTE: must be refreshed each December when NSE publishes the next calendar year.
NSE_WEEKDAY_HOLIDAYS = {
    "2022-08-09",  # Muharram
    "2024-11-15",  # Guru Nanak Jayanti
    "2025-02-26",  # Mahashivratri
    "2025-03-14",  # Holi
    "2025-03-31",  # Eid-ul-Fitr
    "2025-04-10",  # Mahavir Jayanti
    "2025-04-14",  # Ambedkar Jayanti
    "2025-04-18",  # Good Friday
    "2025-05-01",  # Maharashtra Day
    "2025-08-15",  # Independence Day
    "2025-08-27",  # Ganesh Chaturthi
    "2025-10-02",  # Gandhi Jayanti
}

# Columns whose completeness actually matters for the funnel. Ratios and absolutes
# are checked separately because they come from different upstream sources.
ANNUAL_KEY_COLUMNS = [
    "revenue_inr_cr", "ebitda_inr_cr", "net_profit_inr_cr",
    "roce_pct", "roe_pct", "debt_inr_cr", "equity_inr_cr",
    "interest_coverage", "free_cash_flow_inr_cr", "opm_pct",
]
QUARTERLY_KEY_COLUMNS = [
    "revenue_inr_cr", "net_profit_inr_cr", "ebitda_margin_pct",
    "yoy_revenue_growth_pct", "yoy_pat_growth_pct", "eps_inr",
]


def _scalar(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> Any:
    try:
        row = conn.execute(sql, params).fetchone()
        return row[0] if row else None
    except sqlite3.Error:
        return None


def _rows(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> List[tuple]:
    try:
        return conn.execute(sql, params).fetchall()
    except sqlite3.Error:
        return []


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return bool(_scalar(conn, "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)))


def _status(ok: bool, degraded: bool = False) -> str:
    if ok:
        return "OK"
    return "DEGRADED" if degraded else "CRITICAL"


# ---------------------------------------------------------------------------
# 1. Price / delivery time series
# ---------------------------------------------------------------------------
def audit_price(conn: sqlite3.Connection, today: dt.date) -> Dict[str, Any]:
    out: Dict[str, Any] = {"section": "PRICE / DELIVERY"}
    total = _scalar(conn, "SELECT COUNT(*) FROM daily_price_delivery") or 0
    dmin = _scalar(conn, "SELECT MIN(date) FROM daily_price_delivery")
    dmax = _scalar(conn, "SELECT MAX(date) FROM daily_price_delivery")
    sessions = _scalar(conn, "SELECT COUNT(DISTINCT date) FROM daily_price_delivery") or 0
    symbols = _scalar(conn, "SELECT COUNT(DISTINCT symbol) FROM daily_price_delivery") or 0

    out["rows_total"] = total
    out["sessions"] = sessions
    out["distinct_symbols"] = symbols
    out["first_session"] = dmin
    out["latest_session"] = dmax

    staleness_days = None
    if dmax:
        try:
            staleness_days = (today - dt.date.fromisoformat(str(dmax)[:10])).days
        except ValueError:
            pass
    out["staleness_days"] = staleness_days

    # Missing weekdays between first and last session
    missing: List[str] = []
    if dmin and dmax:
        have = {str(r[0])[:10] for r in _rows(conn, "SELECT DISTINCT date FROM daily_price_delivery")}
        cur = dt.date.fromisoformat(str(dmin)[:10])
        end = dt.date.fromisoformat(str(dmax)[:10])
        while cur <= end:
            if cur.weekday() < 5 and cur.isoformat() not in have:
                missing.append(cur.isoformat())
            cur += dt.timedelta(days=1)
    known = [d for d in missing if d in NSE_WEEKDAY_HOLIDAYS]
    unexplained = [d for d in missing if d not in NSE_WEEKDAY_HOLIDAYS]
    out["market_holidays_excluded"] = known
    out["unexplained_gaps"] = unexplained
    out["unexplained_gap_count"] = len(unexplained)

    # Rows per session: detect thin sessions (possible partial ingests)
    per_session = _rows(
        conn,
        "SELECT date, COUNT(*) FROM daily_price_delivery GROUP BY date ORDER BY date DESC LIMIT 10",
    )
    out["recent_sessions_rows"] = [{"date": str(d)[:10], "rows": n} for d, n in per_session]
    if per_session:
        counts = [n for _, n in per_session]
        median = sorted(counts)[len(counts) // 2]
        out["thin_sessions"] = [
            {"date": str(d)[:10], "rows": n} for d, n in per_session if n < median * 0.5
        ]
    else:
        out["thin_sessions"] = []

    # Indicator completeness on the latest session
    if dmax:
        out["latest_session_indicators_null"] = {
            "sma_20": _scalar(conn, "SELECT COUNT(*) FROM daily_price_delivery WHERE date=? AND sma_20 IS NULL", (dmax,)) or 0,
            "rsi_14": _scalar(conn, "SELECT COUNT(*) FROM daily_price_delivery WHERE date=? AND rsi_14 IS NULL", (dmax,)) or 0,
            "delivery_spike_ratio": _scalar(
                conn, "SELECT COUNT(*) FROM daily_price_delivery WHERE date=? AND delivery_spike_ratio IS NULL", (dmax,)
            ) or 0,
            "sma_200": _scalar(conn, "SELECT COUNT(*) FROM daily_price_delivery WHERE date=? AND sma_200 IS NULL", (dmax,)) or 0,
        }

    fresh = staleness_days is not None and staleness_days <= STALE_AFTER_DAYS
    no_gaps = len(unexplained) == 0
    out["status"] = _status(fresh and total > 0 and no_gaps, degraded=fresh and total > 0)
    return out


# ---------------------------------------------------------------------------
# 2. Universe / master
# ---------------------------------------------------------------------------
def audit_universe(conn: sqlite3.Connection) -> Dict[str, Any]:
    out: Dict[str, Any] = {"section": "UNIVERSE / MASTER"}
    out["master_companies"] = _scalar(conn, "SELECT COUNT(*) FROM master_companies") or 0
    out["active"] = _scalar(conn, "SELECT COUNT(*) FROM master_companies WHERE is_active=1") or 0
    out["nifty50"] = _scalar(conn, "SELECT COUNT(*) FROM master_companies WHERE is_nifty50=1") or 0
    out["nifty100"] = _scalar(conn, "SELECT COUNT(*) FROM master_companies WHERE is_nifty100=1") or 0
    out["nifty200"] = _scalar(conn, "SELECT COUNT(*) FROM master_companies WHERE is_nifty200=1") or 0
    out["nifty500"] = _scalar(conn, "SELECT COUNT(*) FROM master_companies WHERE is_nifty500=1") or 0
    out["null_isin"] = _scalar(conn, "SELECT COUNT(*) FROM master_companies WHERE isin IS NULL OR isin=''") or 0
    out["null_symbol"] = _scalar(
        conn, "SELECT COUNT(*) FROM master_companies WHERE nse_symbol IS NULL OR nse_symbol=''"
    ) or 0
    out["null_industry"] = _scalar(
        conn, "SELECT COUNT(*) FROM master_companies WHERE industry IS NULL OR industry=''"
    ) or 0
    out["dup_isin"] = _scalar(
        conn, "SELECT COUNT(*) FROM (SELECT isin FROM master_companies WHERE isin IS NOT NULL GROUP BY isin HAVING COUNT(*)>1)"
    ) or 0

    ok = out["nifty200"] >= 150 and out["null_isin"] == 0 and out["dup_isin"] == 0
    degraded = out["nifty200"] > 0
    out["status"] = _status(ok, degraded=degraded)
    return out


# ---------------------------------------------------------------------------
# 3. Fundamentals coverage
# ---------------------------------------------------------------------------
def _coverage(conn: sqlite3.Connection, table: str, universe_n: int) -> Dict[str, Any]:
    """Coverage of a fundamentals table across the Nifty 200 universe."""
    if not _table_exists(conn, table):
        return {"exists": False}
    distinct = _scalar(
        conn,
        f"SELECT COUNT(DISTINCT m.nse_symbol) FROM master_companies m "
        f"JOIN {table} t ON t.symbol = m.nse_symbol WHERE m.is_nifty200=1",
    ) or 0
    return {
        "exists": True,
        "rows": _scalar(conn, f"SELECT COUNT(*) FROM {table}") or 0,
        "nifty200_covered": distinct,
        "coverage_pct": round(100.0 * distinct / universe_n, 1) if universe_n else 0.0,
    }


def _completeness(conn: sqlite3.Connection, table: str, columns: List[str]) -> Dict[str, Any]:
    """Row-level null audit restricted to the Nifty 200 universe.

    Symbol-level coverage alone is misleading: a symbol can be present with its core
    financial columns entirely null. This measures whether the numbers are actually there.
    """
    if not _table_exists(conn, table):
        return {}
    total = _scalar(
        conn,
        f"SELECT COUNT(*) FROM {table} t JOIN master_companies m ON m.nse_symbol = t.symbol WHERE m.is_nifty200=1",
    ) or 0
    if total == 0:
        return {"rows_nifty200": 0}
    nulls = {}
    for col in columns:
        n = _scalar(
            conn,
            f"SELECT COUNT(*) FROM {table} t JOIN master_companies m ON m.nse_symbol = t.symbol "
            f"WHERE m.is_nifty200=1 AND t.{col} IS NULL",
        )
        if n is None:
            continue  # column absent from this schema
        nulls[col] = {"null": n, "pct_null": round(100.0 * n / total, 1)}
    # Symbols with no usable absolute financials at all
    absent_symbols = _scalar(
        conn,
        f"SELECT COUNT(DISTINCT t.symbol) FROM {table} t "
        f"JOIN master_companies m ON m.nse_symbol = t.symbol "
        f"WHERE m.is_nifty200=1 AND t.revenue_inr_cr IS NULL",
    )
    return {
        "rows_nifty200": total,
        "nulls": nulls,
        "symbols_missing_revenue": absent_symbols or 0,
    }


def audit_fundamentals(conn: sqlite3.Connection, universe_n: int) -> Dict[str, Any]:
    out: Dict[str, Any] = {"section": "FUNDAMENTALS"}
    for tbl in ("quarterly_financials", "annual_financials", "company_forensic_health"):
        out[tbl] = _coverage(conn, tbl, universe_n)

    # Presence is not completeness - audit the actual values
    out["annual_completeness"] = _completeness(conn, "annual_financials", ANNUAL_KEY_COLUMNS)
    out["quarterly_completeness"] = _completeness(conn, "quarterly_financials", QUARTERLY_KEY_COLUMNS)

    # ROIC/WACC derivation needs debt + equity; count how much of the universe can support it
    if _table_exists(conn, "annual_financials"):
        out["capital_structure_available"] = _scalar(
            conn,
            "SELECT COUNT(DISTINCT t.symbol) FROM annual_financials t "
            "JOIN master_companies m ON m.nse_symbol = t.symbol "
            "WHERE m.is_nifty200=1 AND t.debt_inr_cr IS NOT NULL AND t.equity_inr_cr IS NOT NULL",
        ) or 0

    # Financial columns needed to derive ROIC / WACC
    if _table_exists(conn, "annual_financials"):
        out["annual_derived_inputs"] = {
            "roce_pct_null": _scalar(conn, "SELECT COUNT(*) FROM annual_financials WHERE roce_pct IS NULL") or 0,
            "roe_pct_null": _scalar(conn, "SELECT COUNT(*) FROM annual_financials WHERE roe_pct IS NULL") or 0,
            "debt_inr_cr_null": _scalar(conn, "SELECT COUNT(*) FROM annual_financials WHERE debt_inr_cr IS NULL") or 0,
            "equity_inr_cr_null": _scalar(conn, "SELECT COUNT(*) FROM annual_financials WHERE equity_inr_cr IS NULL") or 0,
            "interest_coverage_null": _scalar(
                conn, "SELECT COUNT(*) FROM annual_financials WHERE interest_coverage IS NULL"
            ) or 0,
            "free_cash_flow_null": _scalar(
                conn, "SELECT COUNT(*) FROM annual_financials WHERE free_cash_flow_inr_cr IS NULL"
            ) or 0,
        }

    q = out.get("quarterly_financials", {})
    a = out.get("annual_financials", {})
    ok = (q.get("coverage_pct", 0) >= 80) and (a.get("coverage_pct", 0) >= 80)
    degraded = q.get("coverage_pct", 0) > 0
    out["status"] = _status(ok, degraded=degraded)
    return out


# Columns that gate the ROIC > WACC stage of the top-down funnel.
ROIC_INPUTS = ("roce_pct", "debt_inr_cr", "equity_inr_cr", "interest_coverage")


# ---------------------------------------------------------------------------
# 4. Documents / RAG
# ---------------------------------------------------------------------------
def audit_documents(conn: sqlite3.Connection, universe_n: int) -> Dict[str, Any]:
    out: Dict[str, Any] = {"section": "DOCUMENTS / RAG"}
    out["corporate_documents"] = _scalar(conn, "SELECT COUNT(*) FROM corporate_documents") or 0
    out["corporate_documents_downloaded"] = (
        _scalar(
            conn,
            "SELECT COUNT(*) FROM corporate_documents WHERE local_file_path IS NOT NULL AND local_file_path != ''",
        )
        or 0
    )
    out["corporate_documents_processed"] = (
        _scalar(conn, "SELECT COUNT(*) FROM corporate_documents WHERE is_processed=1") or 0
    )
    out["raw_documents"] = _scalar(conn, "SELECT COUNT(*) FROM raw_documents") or 0
    out["document_chunks"] = _scalar(conn, "SELECT COUNT(*) FROM document_chunks") or 0
    out["chunks_with_embedding"] = (
        _scalar(conn, "SELECT COUNT(*) FROM document_chunks WHERE embedding IS NOT NULL AND embedding != ''") or 0
    )
    out["chunks_with_industry"] = (
        _scalar(conn, "SELECT COUNT(*) FROM document_chunks WHERE industry_id IS NOT NULL") or 0
    )
    if _table_exists(conn, "intelligence_fts"):
        out["fts_rows"] = _scalar(conn, "SELECT COUNT(*) FROM intelligence_fts") or 0
    out["visual_evidence_artifacts"] = _scalar(conn, "SELECT COUNT(*) FROM visual_evidence_artifacts") or 0

    # Does an on-disk PDF exist for each claimed local path?
    pdf_dir = DATA_DIR / "pdfs"
    out["pdf_dir_files"] = len(list(pdf_dir.glob("**/*.pdf"))) if pdf_dir.exists() else 0

    chunks = out["document_chunks"] or 0
    embedded = out["chunks_with_embedding"] or 0
    out["embedding_coverage_pct"] = round(100.0 * embedded / chunks, 1) if chunks else 0.0

    # RAG is optional for the funnel, so absence is degraded, not critical
    out["status"] = _status(chunks > 0, degraded=True)
    return out


# ---------------------------------------------------------------------------
# 5. Causal graph + top-down funnel tables
# ---------------------------------------------------------------------------
FUNNEL_TABLES = [
    "business_model_profiles",
    "moat_evaluations",
    "regulatory_political_risks",
    "financial_metrics",
    "geographic_exposure",
    "countries",
    "industries",
]


def audit_causal(conn: sqlite3.Connection) -> Dict[str, Any]:
    out: Dict[str, Any] = {"section": "CAUSAL GRAPH / TOP-DOWN LAYERS"}
    out["macro_events"] = _scalar(conn, "SELECT COUNT(*) FROM macro_events") or 0
    out["ripple_effects"] = _scalar(conn, "SELECT COUNT(*) FROM ripple_effects") or 0
    out["ripple_max_order_level"] = _scalar(conn, "SELECT MAX(order_level) FROM ripple_effects") or 0
    out["ripple_second_order"] = (
        _scalar(conn, "SELECT COUNT(*) FROM ripple_effects WHERE order_level >= 2") or 0
    )
    out["graph_nodes"] = _scalar(conn, "SELECT COUNT(*) FROM graph_nodes") or 0
    out["graph_causal_edges"] = _scalar(conn, "SELECT COUNT(*) FROM graph_causal_edges") or 0
    out["seed_countries_demo"] = _scalar(conn, "SELECT COUNT(*) FROM seed_countries_demo") or 0
    out["seed_industries_demo"] = _scalar(conn, "SELECT COUNT(*) FROM seed_industries_demo") or 0

    missing: List[str] = []
    present_demo: List[str] = []
    for t in FUNNEL_TABLES:
        if _table_exists(conn, t):
            n = _scalar(conn, f"SELECT COUNT(*) FROM {t}") or 0
            out[f"table_{t}"] = n
            if n == 0:
                missing.append(t)
        else:
            demo = f"{t}_demo"
            if _table_exists(conn, demo):
                n = _scalar(conn, f"SELECT COUNT(*) FROM {demo}") or 0
                out[f"table_{t}"] = f"MISSING (only {demo}={n})"
                present_demo.append(t)
            else:
                out[f"table_{t}"] = "MISSING"
                missing.append(t)

    out["funnel_tables_missing"] = missing
    out["funnel_tables_demo_only"] = present_demo

    # Multi-hop DAG is what makes the ripple math meaningful
    ok = out["ripple_second_order"] > 0 and not missing
    degraded = out["macro_events"] > 0
    out["status"] = _status(ok, degraded=degraded)
    return out


# ---------------------------------------------------------------------------
# 6. On-disk cache
# ---------------------------------------------------------------------------
def audit_cache() -> Dict[str, Any]:
    out: Dict[str, Any] = {"section": "ON-DISK CACHE"}
    bhav = DATA_DIR / "bhavcopy"
    files = sorted(bhav.glob("*.csv")) if bhav.exists() else []
    out["bhavcopy_files"] = len(files)
    if files:
        out["bhavcopy_first"] = files[0].name
        out["bhavcopy_last"] = files[-1].name
    out["reports_files"] = len(list((DATA_DIR / "reports").glob("*"))) if (DATA_DIR / "reports").exists() else 0
    out["inbox_files"] = (
        len(list((DATA_DIR / "inbox").rglob("*"))) if (DATA_DIR / "inbox").exists() else 0
    )
    lancedb = DATA_DIR / "lancedb"
    out["lancedb_present"] = lancedb.exists() and any(lancedb.iterdir()) if lancedb.exists() else False
    db_path = DATA_DIR / "equity_intelligence.db"
    out["db_size_mb"] = round(db_path.stat().st_size / 1e6, 1) if db_path.exists() else 0
    out["status"] = _status(len(files) > 0, degraded=True)
    return out


# ---------------------------------------------------------------------------
# 7. Network reachability (optional)
# ---------------------------------------------------------------------------
def audit_network() -> Dict[str, Any]:
    out: Dict[str, Any] = {"section": "INGESTION REACHABILITY"}
    try:
        import requests  # type: ignore
    except ImportError:
        out["status"] = "SKIPPED (requests not installed)"
        return out

    probes = {
        "NSE archives (bhavcopy)": "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv",
        "NSE indices": "https://nsearchives.nseindia.com/content/indices/ind_close_all_20260827.csv",
        "BSE API": "https://api.bseindia.com/BseIndiaAPI/api/ListofScripData/w?Group=&Scripcode=&industry=&segment=Equity&status=Active",
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "*/*",
    }
    results = {}
    for label, url in probes.items():
        try:
            r = requests.get(url, headers=headers, timeout=8)
            results[label] = f"HTTP {r.status_code} ({len(r.content)} bytes)"
        except Exception as exc:  # noqa: BLE001
            results[label] = f"UNREACHABLE: {type(exc).__name__}"
    out.update(results)
    out["status"] = "INFO"
    return out


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------
def _render(sections: List[Dict[str, Any]]) -> None:
    print("=" * 78)
    print("  REALITY ENGINE - DATA PIPELINE READINESS AUDIT")
    print(f"  {dt.datetime.now().isoformat(timespec='seconds')}")
    print("=" * 78)
    for s in sections:
        print(f"\n--- {s.get('section', 'SECTION')}  [{s.get('status', '?')}] ---")
        for k, v in s.items():
            if k in ("section", "status"):
                continue
            if isinstance(v, (dict, list)):
                v = json.dumps(v, default=str)
            print(f"  {k:42s} {v}")

    print("\n" + "=" * 78)
    print("  SUMMARY")
    print("=" * 78)
    crit, degr = [], []
    for s in sections:
        st = s.get("status")
        name = s.get("section", "?")
        if st == "CRITICAL":
            crit.append(name)
        elif st == "DEGRADED":
            degr.append(name)
    print(f"  CRITICAL : {', '.join(crit) if crit else 'none'}")
    print(f"  DEGRADED : {', '.join(degr) if degr else 'none'}")
    if crit:
        print("\n  >>> Pipeline is NOT ready: resolve CRITICAL sections first.")
    else:
        print("\n  >>> Pipeline is operational for the legacy bottom-up path.")
    print("=" * 78)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Reality Engine data pipeline readiness audit")
    ap.add_argument("--db", type=str, default=str(DEFAULT_DB), help="Path to SQLite DB")
    ap.add_argument("--net", action="store_true", help="Also probe NSE/BSE network reachability")
    ap.add_argument("--json", action="store_true", dest="as_json", help="Emit JSON instead of text")
    args = ap.parse_args(argv)

    if not Path(args.db).exists():
        print(f"ERROR: database not found at {args.db}")
        return 1

    conn = sqlite3.connect(args.db)
    conn.execute("PRAGMA query_only = ON;")
    today = dt.date.today()
    universe_n = _scalar(conn, "SELECT COUNT(*) FROM master_companies WHERE is_nifty200=1") or 200

    sections = [
        audit_price(conn, today),
        audit_universe(conn),
        audit_fundamentals(conn, universe_n),
        audit_documents(conn, universe_n),
        audit_causal(conn),
        audit_cache(),
    ]
    if args.net:
        sections.append(audit_network())
    conn.close()

    if args.as_json:
        print(json.dumps(sections, indent=2, default=str))
    else:
        _render(sections)

    return 1 if any(s.get("status") == "CRITICAL" for s in sections) else 0


if __name__ == "__main__":
    sys.exit(main())
