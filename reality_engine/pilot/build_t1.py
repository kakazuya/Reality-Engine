"""T1 (deterministic) pilot build — PILOT_SPEC §3 deterministic tier, SCHEMA_V3 §B/§C.

Builds two NEW SQLite files from held data only (no network, no live-DB writes):

  <out>/market_state_pilot.db  company_state_daily (+ mcap_bucket_interval, price_band_daily,
                               price_band, index_membership_interval views), index_list,
                               company_membership_pit, company_sector_pit,
                               company_ownership_pit, event_day0, event_leakage_window
  <out>/facts_pilot.db         xbrl_concept_map, company_metric_series, company_result_pit,
                               company_segment_pnl, company_working_capital,
                               company_interest_cover

    python -m reality_engine.pilot.build_t1 --universe pilot --out .tmp/pilot
    python -m reality_engine.pilot.build_t1 --universe all
    python -m reality_engine.pilot.build_t1 --checks --out .tmp/pilot

Inputs are read-only: the dated DuckDB truth snapshot, equity_intelligence.db,
results_xbrl.db, ar_facts.db and the raw stores D:/RealityEngine/raw/{price_bands,index_history}.
DDL is loaded from tasks/arch_v3/SCHEMA_V3.sql (this file does not restate it), so the pilot
tables cannot drift from the design. Idempotent: each builder deletes its table and reinserts.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sqlite3
import sys
import time
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCHEMA_SQL = REPO / "tasks" / "arch_v3" / "SCHEMA_V3.sql"
CASE_MAP = REPO / "tasks" / "arch_v3" / "CASE_MAP.jsonl"

DATA_ROOT = Path(os.environ.get("REALITY_DATA_ROOT", REPO / "reality_engine" / "data"))
SNAPSHOT = DATA_ROOT / "snapshots" / "truth_2026-10-19.duckdb"
EI = DATA_ROOT / "equity_intelligence.db"
XBRL = DATA_ROOT / "results_xbrl.db"
AR = DATA_ROOT / "ar_facts.db"
RAW_ROOT = Path(os.environ.get("REALITY_RAW_ROOT", r"D:\RealityEngine\raw"))

MARKET_DB = "market_state_pilot.db"
FACTS_DB = "facts_pilot.db"

# PILOT_SPEC §1: 30 ISINs measured for the reader tier; the deterministic tier covers the
# 489-ISIN bank universe (measured from CASE_MAP.jsonl evidence_state.isin when present).
T1_MARKET = {
    "company_state_daily", "mcap_bucket_interval", "price_band_daily", "isin_rekey_map",
    "index_list", "company_membership_pit", "company_sector_pit", "theme_map",
    "company_ownership_pit", "event_day0", "event_leakage_window", "build_run",
}
T1_FACTS = {
    "xbrl_concept_map", "company_metric_series", "company_segment_pnl",
    "company_working_capital", "company_interest_cover", "company_result_pit",
    "build_run",
}
# Build order inside each file matters only for the views (they read the daily table).
T1_VIEWS = {"mcap_bucket_interval", "price_band_daily"}

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
SESSION_CLOSE = dt.time(15, 30)
BACKCAST_START = "2019-01-01"

# ---------------------------------------------------------------------------------------
# DDL from SCHEMA_V3.sql
# ---------------------------------------------------------------------------------------
_CREATE = re.compile(
    r"CREATE\s+(?:VIRTUAL\s+TABLE|TABLE|VIEW|INDEX|UNIQUE\s+INDEX)\s+(?:IF\s+NOT\s+EXISTS\s+)?"
    r"([A-Za-z_][A-Za-z0-9_]*)", re.I)


def schema_statements(sql_text: str):
    """[(object_name, statement)] for every CREATE in the design file, in file order.

    Line comments are stripped first: the design document talks about CREATE statements in
    its comments, and matching those would cut real statements short.
    """
    clean = "\n".join(re.sub(r"--.*$", "", line) for line in sql_text.splitlines())
    out = []
    for stmt in clean.split(";"):
        s = stmt.strip()
        if not re.match(r"CREATE\b", s, re.I):
            continue
        m = _CREATE.search(s)
        if m:
            out.append((m.group(1), s))
    return out


def create_schema(target, keep: set[str], sql_text: str | None = None) -> list[str]:
    """Create the `keep` tables/views/indexes of one row-group in `target` (path or connection).

    Returns the object names created. An index belongs to the group of the table it is on.
    """
    text = sql_text if sql_text is not None else SCHEMA_SQL.read_text(encoding="utf-8")
    own = not isinstance(target, sqlite3.Connection)
    con = sqlite3.connect(":memory:" if str(target) == ":memory:" else target) if own else target
    if own:
        con.execute("PRAGMA journal_mode=WAL")
    made = []
    for name, stmt in schema_statements(text):
        m = re.search(r"\bON\s+([A-Za-z_][A-Za-z0-9_]*)", stmt, re.I) \
            if re.match(r"CREATE\s+(?:UNIQUE\s+)?INDEX", stmt, re.I) else None
        if (m.group(1) if m else name) not in keep:
            continue
        if re.match(r"CREATE\s+VIEW", stmt, re.I):
            con.execute(f"DROP VIEW IF EXISTS {name}")
        con.execute(stmt)
        made.append(name)
    con.commit()
    if own:
        con.close()
    return made


def compatibility_views(con: sqlite3.Connection) -> None:
    """The brief names two objects by their working titles; SCHEMA_V3 names them differently.
    Both names resolve to the same rows (no duplicated values)."""
    con.execute("DROP VIEW IF EXISTS price_band")
    con.execute("CREATE VIEW price_band AS "
                "SELECT isin, date, price_band AS band, "
                "CASE WHEN price_band IS NULL THEN 0 ELSE 1 END AS has_band "
                "FROM company_state_daily")
    con.execute("DROP VIEW IF EXISTS index_membership_interval")
    con.execute("CREATE VIEW index_membership_interval AS "
                "SELECT isin, index_code, added_on AS valid_from, removed_on AS valid_to, "
                "source, pit_conf FROM company_membership_pit")
    con.commit()


# ---------------------------------------------------------------------------------------
# small pure helpers (unit-tested offline)
# ---------------------------------------------------------------------------------------
def to_ist(ts: dt.datetime) -> dt.datetime:
    """UTC (naive or aware) -> naive IST."""
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=dt.timezone.utc)
    return ts.astimezone(IST).replace(tzinfo=None)


def ist_text(value) -> str | None:
    """Any source timestamp -> ISO-8601 IST text (SCHEMA_V3 convention)."""
    if value is None or value == "":
        return None
    if isinstance(value, dt.datetime):
        return to_ist(value).isoformat(timespec="seconds")
    s = str(value).strip().replace(" ", "T", 1)
    try:
        return to_ist(dt.datetime.fromisoformat(s)).isoformat(timespec="seconds")
    except ValueError:
        return None


def day0(known_ist: dt.datetime, sessions: list[str], session_set: set[str]):
    """The 15:30 rule. Returns (session_0, offset, in_session).

    A filing stamped at or before 15:30 on a trading day is tradable that session (offset 0);
    everything else belongs to the next session (offset 1). A filing on a non-session day
    (weekend/holiday) also belongs to the next session.
    """
    d = known_ist.date().isoformat()
    if known_ist.time() <= SESSION_CLOSE and d in session_set:
        return d, 0, 1
    import bisect
    i = bisect.bisect_right(sessions, d)
    if i >= len(sessions):
        return None, None, 0
    return sessions[i], 1, 0


_SEG_A = re.compile(r"^(?P<seg>.{2,70}?)\s+segment\s+(?P<metric>[a-z][a-z ]*?)"
                    r"(?:\s*[\(\[]|\s+FY\s*\d|\s*$)", re.I)
_SEG_B = re.compile(r"^segment\s+(?P<metric>[a-z][a-z ]*?)\s*[-:]\s*"
                    r"(?P<seg>[^\(\[]+?)(?:\s*[\(\[]|\s+FY\s*\d|\s*$)", re.I)
SEGMENT_METRICS = {
    "revenue": "revenue", "sales": "revenue", "income": "revenue",
    "profit before tax": "ebit", "profit before finance and tax": "ebit",
    "profit before finance cost and tax": "ebit", "profit before interest and tax": "ebit",
    "profit before tax and interest": "ebit", "ebit": "ebit", "ebitda": "ebitda",
    "assets": "segment_assets", "liabilities": "segment_liabilities",
    "capital expenditure": "capex", "capex": "capex",
}


def parse_segment_item(item: str | None):
    """'<seg> segment revenue FY26' / 'Segment assets - <seg> FY26' -> (segment, metric)."""
    if not item:
        return None
    text = " ".join(str(item).split())
    m = _SEG_A.match(text) or _SEG_B.match(text)
    if not m:
        return None
    metric = SEGMENT_METRICS.get(m.group("metric").strip().lower())
    seg = m.group("seg").strip(" -:.,")
    low = seg.lower()
    if not metric or len(seg) < 2 or len(seg) > 70:
        return None
    if low.startswith(("total", "all ", "no ", "single", "the ", "these ", "this ")) \
            or "segment" in low or low in ("total", "net sales/income total"):
        return None
    return seg, metric


def unit_to_crore(unit: str | None) -> float | None:
    """'Rs lakh' -> 0.01, 'Rs crore' -> 1, 'Rs million' -> 0.1, 'Rs' -> 1e-7; else None."""
    u = (unit or "").lower().replace(".", "").replace("inr", "rs ").replace("₹", "rs ")
    u = " ".join(u.split())
    if not u or "%" in u or "share" in u or u in ("pure", "number", "nos", "count"):
        return None
    if "crore" in u or u in ("rs cr", "cr"):
        return 1.0
    if "lakh" in u or "lac " in u + " " or u.endswith("lac"):
        return 1e-2
    if "million" in u or u.endswith(" mn") or u == "mn":
        return 1e-1
    if "billion" in u or u.endswith(" bn") or u == "bn":
        return 1e2
    if "thousand" in u or u.endswith("000s"):
        return 1e-4
    if u in ("rs", "rs in", "rs  "):
        return 1e-7
    return None


def fy_end(period: str | None) -> str | None:
    m = re.search(r"FY\s*(\d{2,4})", period or "", re.I)
    if not m:
        return None
    y = int(m.group(1))
    y = 2000 + y if y < 100 else y
    return f"{y:04d}-03-31"


def period_kind_of(start, end, kind) -> str | None:
    """XBRL period_kind -> SCHEMA_V3 period_kind. Durations resolved by length."""
    s = start if isinstance(start, str) and start else None
    e = end if isinstance(end, str) and end else None
    if kind == "instant" or (s is None and e is not None):
        return "instant"
    if s is None or e is None:
        return None
    if str(kind) in ("other", "prior_year_instant"):
        return None
    try:
        days = (dt.date.fromisoformat(e) - dt.date.fromisoformat(s)).days
    except ValueError:
        return None
    if days <= 100:
        return "quarter"
    if days <= 220:
        return "half"
    return "fy"


class Interval:
    __slots__ = ("added_on", "removed_on")

    def __init__(self, added_on=None, removed_on=None):
        self.added_on, self.removed_on = added_on, removed_on


def rebuild_membership(snapshot, notices, history_from=BACKCAST_START):
    """Backcast one index's constituent intervals from the snapshot + dated notices.

    snapshot: {(index_code, isin)}  (members on the snapshot date)
    notices:  [(index_code, isin, effective_date, 'inclusion'|'exclusion')], any order
    -> (intervals, anomalies): [(isin, index_code, added_on, removed_on, source, pit_conf)]
    Intervals are half-open [added_on, removed_on); removed_on None = still a member.
    """
    by_node = defaultdict(list)
    for index_code, isin, eff, kind in notices:
        if eff:
            by_node[(index_code, isin)].append((str(eff), kind))
    out, anomalies = [], 0
    for index_code, isin in sorted(set(snapshot) | set(by_node)):
        events = sorted(by_node.get((index_code, isin), []))
        cur = Interval() if (index_code, isin) in snapshot else None
        emitted = []

        def emit(iv: Interval):
            add = iv.added_on or history_from
            if iv.removed_on is not None and iv.removed_on <= add:
                return
            from_notice = iv.added_on is not None
            emitted.append((isin, index_code, add, iv.removed_on,
                            "nse_notice" if from_notice else "snapshot_backcast",
                            1.0 if from_notice else 0.8))

        for eff, kind in reversed(events):
            if kind == "exclusion":
                if cur is not None:
                    cur.removed_on = eff
                    emit(cur)
                cur = Interval(None, eff)
            else:  # inclusion: membership starts at eff, so it was absent just before
                if cur is None:
                    anomalies += 1   # duplicate inclusion with no exclusion between: skip
                    continue
                cur.added_on = eff
                emit(cur)
                cur = None
        if cur is not None:
            emit(cur)
        out.extend(emitted)
    return out, anomalies


# ---------------------------------------------------------------------------------------
# build helpers
# ---------------------------------------------------------------------------------------
def insert_rows(con: sqlite3.Connection, table: str, cols: list[str], rows, chunk=40000) -> int:
    if not rows:
        return 0
    sql = (f"INSERT OR REPLACE INTO {table} ({', '.join(cols)}) "
           f"VALUES ({', '.join('?' * len(cols))})")
    n = 0
    for i in range(0, len(rows), chunk):
        batch = rows[i:i + chunk]
        con.executemany(sql, batch)
        n += len(batch)
    con.commit()
    return n


def clear(con: sqlite3.Connection, table: str) -> None:
    con.execute(f"DELETE FROM {table}")
    con.commit()


def table_count(con: sqlite3.Connection, table: str) -> int:
    return con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def ro(path: Path) -> sqlite3.Connection:
    """Read-only sqlite connection (never write to a live DB)."""
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    con.execute("PRAGMA query_only=ON")
    return con


def bank_universe() -> list[str]:
    """The 489 ISINs the master bank names (MASTER_BANK entities + CASE_MAP evidence)."""
    token = re.compile(r"\bINE[0-9A-Z]{9}\b")
    seen = set()
    with (REPO / "tasks" / "master_bank" / "MASTER_BANK.jsonl").open(encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            for ent in row.get("entities") or []:
                if isinstance(ent, dict):
                    for key, val in ent.items():
                        if isinstance(val, str) and token.fullmatch(val):
                            seen.add(val)
                    if isinstance(ent.get("isin"), str):
                        seen.add(ent["isin"])
            seen.update(token.findall(json.dumps(row.get("entities"))))
    with CASE_MAP.open(encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            isin = (row.get("evidence_state") or {}).get("isin")
            if isinstance(isin, str) and token.fullmatch(isin):
                seen.add(isin)
            seen.update(token.findall(json.dumps(row.get("hops"))))
    return sorted(i for i in seen if i.startswith("INE"))


def duckdb_snapshot():
    import duckdb
    return duckdb.connect(str(SNAPSHOT), read_only=True)


def _isin_clause(universe) -> str:
    if not universe:
        return ""
    return "WHERE isin IN (%s)" % ",".join("'%s'" % i for i in universe)


# ---------------------------------------------------------------------------------------
# 1. company_state_daily
# ---------------------------------------------------------------------------------------
def build_company_state(mcon: sqlite3.Connection, universe, log) -> dict:
    import pandas as pd
    t0 = time.monotonic()
    dcon = duckdb_snapshot()
    # paid-up value / face value = shares. The facts are stored with period_end (not instant)
    # on the balance-sheet date, so the as-of date is coalesce(instant, period_end).
    shr = dcon.execute("""
        SELECT f.trading_isin AS isin, fa.concept, fa.context,
               CAST(coalesce(fa.instant, fa.period_end) AS VARCHAR) AS as_of,
               fa.value, f.known_at_utc
        FROM results_facts fa JOIN results_filings f USING (file)
        WHERE fa.concept IN ('PaidUpValueOfEquityShareCapital',
                             'FaceValueOfEquityShareCapital')
          AND fa.value IS NOT NULL
          AND coalesce(fa.instant, fa.period_end) IS NOT NULL
          AND f.trading_isin IS NOT NULL
    """).df()
    paid = shr[shr.concept == "PaidUpValueOfEquityShareCapital"]
    face = shr[shr.concept == "FaceValueOfEquityShareCapital"]
    m = paid.merge(face, on=["isin", "context", "as_of"], suffixes=("_paid", "_face"))
    m["shares"] = (m.value_paid / m.value_face.where(m.value_face != 0)).round()
    m = m[(m.shares > 1e4) & (m.shares < 1e12)]
    m["known_date"] = (pd.to_datetime(m.known_at_utc_paid, errors="coerce")
                       + pd.Timedelta(hours=5, minutes=30)).dt.date
    shares = m.dropna(subset=["known_date"]).groupby(
        ["isin", "known_date"], as_index=False)["shares"].max()
    shares["shares"] = shares["shares"].astype("int64")
    log(f"shares_pit: {len(shares):,} (isin, session) steps for "
        f"{shares['isin'].nunique():,} ISINs")
    dcon.register("shares_pit", shares)

    where = _isin_clause(universe)
    state = dcon.execute(f"""
        WITH p AS (
            SELECT isin, date, symbol, segment, exch, adj_close AS close, value_inr,
                   sum(value_inr) OVER (PARTITION BY isin ORDER BY date
                                        ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) AS tv20
            FROM px_daily
        ), j AS (
            SELECT p.*, s.shares
            FROM p ASOF LEFT JOIN shares_pit s ON p.isin = s.isin AND p.date >= s.known_date
        ), r AS (
            SELECT j.*,
                   CASE WHEN shares IS NULL OR shares = 0 THEN NULL
                        ELSE close * shares / 1e7 END AS mcap_cr,
                   row_number() OVER (PARTITION BY date
                                      ORDER BY (CASE WHEN shares IS NULL OR shares = 0
                                                     THEN 1 ELSE 0 END),
                                               close * shares DESC) AS rk
            FROM j
        )
        SELECT isin, CAST(date AS VARCHAR) AS date, symbol, segment, exch, close, tv20,
               shares, mcap_cr, rk
        FROM r {where}
    """).df()
    dcon.close()
    log(f"price rows: {len(state):,} for {state['isin'].nunique():,} ISINs")

    # price band: raw sec_list files (NSE), filtered to the symbols in this frame.
    symbols = set(state.symbol.dropna().astype(str)) if universe else None
    bands, band_dates, band_rows = parse_band_store(symbols, log)
    log(f"price_bands raw: {band_rows:,} rows over {len(band_dates):,} dates")

    ei = ro(EI)
    fno = {r[0]: 1 if r[1] else 0 for r in
           ei.execute("SELECT isin, is_fno_eligible FROM master_companies")}
    ei.close()

    rows = []
    band_hit = band_bse = band_missing = 0
    for r in state.itertuples(index=False):
        key = (r.date, r.symbol, r.segment)
        if key in bands:
            band = bands[key]
            band_hit += 1
        elif (r.date, r.symbol, "*") in bands:
            band = bands[(r.date, r.symbol, "*")]
            band_hit += 1
        else:
            band = None
            # an NSE row with no sec_list entry is a real gap; a BSE-only line has no NSE band
            if r.exch == "NSE" and r.date in band_dates:
                band_missing += 1
            else:
                band_bse += 1
        rk = None if pd.isna(r.rk) else int(r.rk)
        bucket = (None if pd.isna(r.mcap_cr) or rk is None else
                  "LARGE" if rk <= 100 else "MID" if rk <= 250 else
                  "SMALL" if rk <= 500 else "MICRO")
        rows.append((
            r.isin, r.date, None if pd.isna(r.close) else float(r.close),
            None if pd.isna(r.mcap_cr) else float(r.mcap_cr),
            None if pd.isna(r.shares) else int(r.shares), "xbrl_paidup" if not pd.isna(r.shares) else None,
            bucket, band, fno.get(r.isin, 0),
            None if pd.isna(r.tv20) else round(float(r.tv20) / 1e7, 4),
            f"{r.date}T15:30:00",
        ))
    clear(mcon, "company_state_daily")
    n = insert_rows(mcon, "company_state_daily",
                    ["isin", "date", "close", "mcap_cr", "shares_out", "shares_source",
                     "mcap_bucket", "price_band", "is_fno", "traded_value_20d_cr", "known_at"],
                    rows)
    log(f"company_state_daily: {n:,} rows, band resolved {band_hit:,}/{len(rows):,} "
        f"({band_missing:,} NSE rows absent from the file, {band_bse:,} BSE-only rows), "
        f"{time.monotonic() - t0:.1f}s")
    return {"rows": n, "band_hit": band_hit, "band_missing": band_missing,
            "band_bse": band_bse, "band_dates": len(band_dates),
            "seconds": round(time.monotonic() - t0, 1)}


_BAND_FILES = re.compile(r"sec_list_(\d{8})\.csv$")


def parse_band_store(symbols: set | None, log):
    """D:/raw/price_bands/sec_list_*.csv -> {(date, symbol, series|'*'): band_pct}."""
    from reality_engine.scripts.fetch_price_bands import parse_band_csv
    root = RAW_ROOT / "price_bands"
    bands, dates, n = {}, set(), 0
    files = sorted(root.glob("sec_list_*.csv"))
    for path in files:
        m = _BAND_FILES.search(path.name)
        if not m:
            continue
        day = f"{m.group(1)[4:8]}-{m.group(1)[2:4]}-{m.group(1)[0:2]}"
        dates.add(day)
        try:
            text = path.read_text(encoding="utf-8-sig", errors="replace")
        except OSError as exc:
            log(f"band file unreadable {path.name}: {exc}")
            continue
        for row in parse_band_csv(text, day):
            n += 1
            if symbols is not None and row["symbol"] not in symbols:
                continue
            bands.setdefault((day, row["symbol"], row["series"] or "*"), row["band_pct"])
            bands.setdefault((day, row["symbol"], "*"), row["band_pct"])
    log(f"parsed {len(files):,} sec_list files")
    return bands, dates, n


# ---------------------------------------------------------------------------------------
# 2. index membership (backcast from the 2026-09-30 snapshot + 446 dated notices)
# ---------------------------------------------------------------------------------------
INDEX_CODES = {"NIFTY 50": "nifty50", "NIFTY 100": "nifty100",
               "NIFTY MIDCAP 150": "niftymidcap150"}
INDEX_LISTS = {"nifty50": ("NIFTY 50", 50), "nifty100": ("NIFTY 100", 100),
               "niftymidcap150": ("NIFTY MIDCAP 150", 150)}


def build_membership(mcon: sqlite3.Connection, out: Path, universe, log) -> dict:
    t0 = time.monotonic()
    from reality_engine.scripts.fetch_index_history import parse_notice, pdf_text
    ei = ro(EI)
    snap_date = ei.execute("SELECT MAX(as_of) FROM index_membership").fetchone()[0]
    snapshot = {(r[0], r[1]) for r in ei.execute(
        "SELECT index_name, isin FROM index_membership WHERE as_of = ?", (snap_date,))}
    # a notice names a SYMBOL; when that symbol is a current member it must resolve to the
    # snapshot ISIN, so a split re-key cannot mint a second member (G0's false-change trap)
    snap_sym = {(idx, sym): isin for idx, sym, isin in ei.execute(
        "SELECT index_name, symbol, isin FROM index_membership WHERE as_of = ?", (snap_date,))}
    hist = defaultdict(list)
    for sym, isin, first, last in ei.execute(
            "SELECT symbol, isin, first_date, last_date FROM symbol_isin_history "
            "WHERE exchange = 'NSE'"):
        hist[sym].append((first or "", last or "9999-12-31", isin))
    ei.close()

    def resolve(symbol, on_date):
        windows = sorted(hist.get(symbol) or [])
        for first, last, isin in windows:
            if first <= on_date <= last:
                return isin
        return windows[-1][2] if windows else None

    root = RAW_ROOT / "index_history"
    notices_json = json.loads((root / "_notices.json").read_text(encoding="utf-8"))
    notices, parsed_pdfs, missing_pdfs, unmatched = [], 0, 0, defaultdict(int)
    for n in notices_json:
        path = root / n["url"].rsplit("/", 1)[-1]
        if not path.exists():
            missing_pdfs += 1
            continue
        try:
            rows = parse_notice(pdf_text(path), n["published"], n["url"], n["title"])
        except Exception as exc:                       # a broken PDF must not kill the build
            log(f"notice parse failed {path.name}: {exc}")
            continue
        parsed_pdfs += 1
        for r in rows:
            code = INDEX_CODES.get(r["index_name"])
            if not code or not r["effective_date"]:
                continue
            isin = snap_sym.get((code, r["symbol"])) or resolve(r["symbol"], r["effective_date"])
            if not isin:
                unmatched[r["symbol"]] += 1
                continue
            notices.append((code, isin, r["effective_date"], r["change_type"]))
    log(f"index notices: {len(notices_json)} listed, {parsed_pdfs} PDFs parsed, "
        f"{missing_pdfs} missing, {len(notices)} in-scope changes, "
        f"{len(unmatched)} symbols unresolved")

    intervals, anomalies = rebuild_membership(snapshot, notices)
    # audit trail: the in-scope notice rows the intervals were rebuilt from
    with (out / "index_changes.jsonl").open("w", encoding="utf-8") as f:
        for code, isin, eff, kind in sorted(notices, key=lambda r: (r[2], r[0], r[1])):
            f.write(json.dumps({"index_code": code, "isin": isin,
                                "effective_date": eff, "change_type": kind}) + "\n")
    clear(mcon, "index_list")
    insert_rows(mcon, "index_list", ["index_code", "display_name", "broad_or_sector",
                                     "size", "history_from"],
                [(code, name, "broad", size, BACKCAST_START)
                 for code, (name, size) in INDEX_LISTS.items()])
    clear(mcon, "company_membership_pit")
    n = insert_rows(mcon, "company_membership_pit",
                    ["isin", "index_code", "added_on", "removed_on", "source", "pit_conf"],
                    intervals)
    log(f"company_membership_pit: {n:,} intervals from {len(snapshot)} snapshot rows "
        f"({anomalies} order anomalies, {round(time.monotonic() - t0, 1)}s)")
    return {"rows": n, "notices": len(notices), "unmatched": len(unmatched),
            "anomalies": anomalies, "missing_pdfs": missing_pdfs,
            "seconds": round(time.monotonic() - t0, 1)}


# ---------------------------------------------------------------------------------------
# 3. event_day0 + event_leakage_window
# ---------------------------------------------------------------------------------------
MATERIAL_KINDS = ("results", "concall", "deck", "annual_report", "sast", "shareholding")


def trading_calendar(log) -> list[str]:
    ei = ro(EI)
    cal = [r[0] for r in ei.execute(
        "SELECT DISTINCT date FROM mkt_nse_index_daily WHERE date >= ? ORDER BY date",
        (BACKCAST_START,))]
    ei.close()
    log(f"trading calendar: {len(cal):,} sessions {cal[0]}..{cal[-1]}")
    return cal


def build_events(mcon: sqlite3.Connection, universe, log) -> dict:
    t0 = time.monotonic()
    import pandas as pd
    cal = trading_calendar(log)
    cal_set = set(cal)
    dcon = duckdb_snapshot()
    where = _isin_clause(universe)
    ev = dcon.execute(f"""
        SELECT isin, CAST(known_at_utc AS VARCHAR) AS known_at_utc, kind,
               CAST(source_ref AS VARCHAR) AS source_ref
        FROM events {where}
    """).df()
    log(f"events in scope: {len(ev):,}")

    day0_rows, leak_events = [], []
    for r in ev.itertuples(index=False):
        try:
            known = to_ist(pd.Timestamp(r.known_at_utc).to_pydatetime())
        except (ValueError, TypeError):
            continue
        session, offset, in_sess = day0(known, cal, cal_set)
        if session is None:
            continue
        eid = f"{r.kind}:{r.source_ref}"
        day0_rows.append((eid, r.isin, r.kind, known.isoformat(timespec="seconds"),
                          session, offset, in_sess, 1.0))
        if r.kind in MATERIAL_KINDS:
            leak_events.append((eid, r.isin, session, known))

    clear(mcon, "event_day0")
    n0 = insert_rows(mcon, "event_day0",
                     ["event_id", "isin", "event_kind", "known_at", "session_0",
                      "offset", "in_session", "pit_conf"], day0_rows)
    log(f"event_day0: {n0:,} rows")

    # price/delivery panel for the universe
    pwhere = _isin_clause(universe)
    px = dcon.execute(f"""
        SELECT isin, CAST(date AS VARCHAR) AS date, adj_close, delivery_pct
        FROM px_daily {pwhere}
    """).df()
    dcon.close()
    px["date"] = px.date.astype(str)
    px = px.sort_values(["isin", "date"])
    g = px.groupby("isin", sort=False)
    px["ret_pct"] = (g.adj_close.pct_change() * 100.0).round(6)
    mean = g.delivery_pct.transform(lambda s: s.rolling(60, min_periods=20).mean())
    std = g.delivery_pct.transform(lambda s: s.rolling(60, min_periods=20).std())
    px["delivery_z"] = ((px.delivery_pct - mean) / std.where(std > 0)).round(6)
    stats = {(r[0], r[1]): (r[2], r[3]) for r in
             px[["isin", "date", "ret_pct", "delivery_z"]].itertuples(index=False)}

    ei = ro(EI)
    inside = defaultdict(float)
    for isin, d, typ, qty, val in ei.execute(
            "SELECT isin, coalesce(substr(known_at,1,10), intimation_date), "
            "transaction_type, qty, value_inr FROM insider_trades_v2 "
            "WHERE known_at IS NOT NULL AND isin IS NOT NULL AND value_inr IS NOT NULL"):
        if not (isin and d and d >= BACKCAST_START):
            continue
        sign = 1 if re.search(r"acq|buy|purchase", (typ or ""), re.I) else -1
        inside[(isin, d[:10])] += sign * float(val)
    deals = defaultdict(float)
    for isin, d, bs, qty, price in ei.execute(
            "SELECT isin, deal_date, buy_sell, quantity, trade_price FROM bulk_block_deals "
            "WHERE isin IS NOT NULL"):
        if not (isin and d and d >= BACKCAST_START):
            continue
        sign = 1 if re.search(r"buy", (bs or ""), re.I) else -1
        deals[(isin, str(d)[:10])] += sign * float(qty or 0) * float(price or 0)
    ei.close()
    log(f"flow panels: {len(inside):,} insider (isin,date), {len(deals):,} deal (isin,date)")

    idx = {d: i for i, d in enumerate(cal)}
    leak_rows = []
    for eid, isin, session, known in leak_events:
        i = idx.get(session)
        if i is None:
            continue
        kn = known.isoformat(timespec="seconds")
        for k in range(-10, 11):
            j = i + k
            if 0 <= j < len(cal):
                d = cal[j]
                stat = stats.get((isin, d))
                leak_rows.append((
                    eid, isin, k, d,
                    None if stat is None or pd.isna(stat[0]) else float(stat[0]),
                    None if stat is None or pd.isna(stat[1]) else float(stat[1]),
                    round(inside.get((isin, d), 0.0), 2) or None,
                    round(deals.get((isin, d), 0.0), 2) or None,
                    kn,
                ))
    clear(mcon, "event_leakage_window")
    n1 = insert_rows(mcon, "event_leakage_window",
                     ["event_id", "isin", "offset", "date", "ret_pct", "delivery_z",
                      "insider_net_inr", "deal_net_inr", "known_at"], leak_rows)
    log(f"event_leakage_window: {n1:,} rows for {len(leak_events):,} material events "
        f"({round(time.monotonic() - t0, 1)}s)")
    return {"day0": n0, "window": n1, "material": len(leak_events),
            "seconds": round(time.monotonic() - t0, 1)}


# ---------------------------------------------------------------------------------------
# 4. XBRL concept map + metric series (+ result/working-capital/interest-cover tables)
# ---------------------------------------------------------------------------------------
# hand map: concept -> (metric_key, sign, unit_scale, basis_default). Only concepts actually
# measured in results_xbrl are written; anything missing is reported, not invented.
CONCEPT_MAP = {
    "RevenueFromOperations": ("revenue", 1, 1e-7, None),
    "RevenueFromSaleOfProduct": ("revenue_product", 1, 1e-7, None),
    "RevenueFromSaleOfServices": ("revenue_services", 1, 1e-7, None),
    "OtherIncome": ("other_income", 1, 1e-7, None),
    "FinanceCosts": ("finance_costs", 1, 1e-7, None),
    "DepreciationDepletionAndAmortisationExpense": ("depreciation", 1, 1e-7, None),
    "ProfitBeforeTax": ("pbt", 1, 1e-7, None),
    "ProfitLossForPeriod": ("pat", 1, 1e-7, None),
    "ProfitOrLossAttributableToOwnersOfParent": ("pat_owners", 1, 1e-7, None),
    "BasicEarningsLossPerShareFromContinuingOperations": ("eps", 1, 1.0, None),
    "Assets": ("total_assets", 1, 1e-7, None),
    "Equity": ("net_worth", 1, 1e-7, None),
    "BorrowingsCurrent": ("borrowings_current", 1, 1e-7, None),
    "BorrowingsNoncurrent": ("borrowings_noncurrent", 1, 1e-7, None),
    "TradeReceivables": ("receivables", 1, 1e-7, None),
    "Inventories": ("inventory", 1, 1e-7, None),
    "TradePayablesCurrent": ("payables", 1, 1e-7, None),
    "TradePayables": ("payables", 1, 1e-7, None),
    "CostOfMaterialsConsumed": ("cogs", 1, 1e-7, None),
    "CashAndCashEquivalents": ("cash", 1, 1e-7, None),
    "PaidUpValueOfEquityShareCapital": ("paid_up_capital", 1, 1e-7, None),
    "FaceValueOfEquityShareCapital": ("face_value", 1, 1.0, None),
}
_TAXONOMIES = ("INDAS", "INTEGRATED", "NBFC", "BANKING", "NONINDAS")


def build_metrics(mcon: sqlite3.Connection, universe, log) -> dict:
    import pandas as pd
    t0 = time.monotonic()
    dcon = duckdb_snapshot()
    present = {r[0] for r in dcon.execute(
        "SELECT DISTINCT concept FROM results_facts").fetchall()}
    concepts = [c for c in CONCEPT_MAP if c in present]
    missing = sorted(set(CONCEPT_MAP) - present)
    clause = "AND f.trading_isin IN (%s)" % ",".join("'%s'" % i for i in universe) if universe else ""
    cq = ",".join("'%s'" % c for c in concepts)
    facts = dcon.execute(f"""
        SELECT f.trading_isin AS isin, f.taxonomy, f.consolidated, f.known_at_utc,
               fa.file, fa.concept, fa.period_start, fa.period_end, fa.instant,
               fa.value, fa.unit, fa.period_kind
        FROM results_facts fa JOIN results_filings f USING (file)
        WHERE fa.concept IN ({cq}) AND fa.value IS NOT NULL
          AND f.trading_isin IS NOT NULL
          AND coalesce(fa.period_end, fa.instant) >= '2019-01-01'
          {clause}
    """).df()
    dcon.close()
    log(f"xbrl facts mapped: {len(facts):,} rows, {len(concepts)} concepts "
        f"({len(missing)} hand-mapped concepts absent: {', '.join(missing[:6]) or '-'})")

    clear(mcon, "xbrl_concept_map")
    xcm = []
    for taxonomy in sorted({t for t in facts.taxonomy.dropna().unique()}):
        for c in concepts:
            key, sign, scale, basis = CONCEPT_MAP[c]
            xcm.append((taxonomy, c, key, scale, sign, basis, 1))
    n_map = insert_rows(mcon, "xbrl_concept_map",
                        ["taxonomy", "concept", "metric_key", "unit_scale", "sign",
                         "basis_default", "verified"], xcm)

    series, seen, conflicts = [], set(), 0
    for r in facts.itertuples(index=False):
        key, sign, scale, _ = CONCEPT_MAP[r.concept]
        kind = period_kind_of(r.period_start, r.period_end, r.period_kind)
        # an instant fact may carry the date in period_end (often) or instant (sometimes)
        pe = r.period_end if not pd.isna(r.period_end) else r.instant
        if kind is None or pe is None or pd.isna(pe):
            continue
        period_end = str(pe)[:10]
        unit = "INR_CRORE" if r.unit != "INRPerShare" else "INR_PER_SHARE"
        value = float(r.value) * scale * sign
        basis = "consolidated" if str(r.consolidated).lower().startswith("consol") else "standalone"
        known = ist_text(r.known_at_utc)
        if known is None:
            continue
        pk = (r.isin, key, period_end, kind, basis)
        row = (r.isin, key, period_end, kind, basis, round(value, 6), unit, "xbrl",
               str(r.file), known, 1.0)
        # two concepts can implement one metric (TradePayables / TradePayablesCurrent, or the
        # same concept restated in a later filing): the first row wins, and the table, the
        # pivots below and the checks all see that same single row.
        if pk in seen:
            conflicts += 1
            continue
        seen.add(pk)
        series.append(row)
    clear(mcon, "company_metric_series")
    n_series = insert_rows(mcon, "company_metric_series",
                           ["isin", "metric_key", "period_end", "period_kind", "basis",
                            "value", "unit", "source", "doc_id", "known_at", "pit_conf"],
                           series)
    log(f"company_metric_series: {n_series:,} rows, "
        f"{len({s[1] for s in series})} metrics ({conflicts:,} duplicate PK rows dropped)")

    # --- derived tables from the same series ---
    df = pd.DataFrame(series, columns=["isin", "metric_key", "period_end", "period_kind",
                                       "basis", "value", "unit", "source", "doc_id",
                                       "known_at", "pit_conf"])
    result = []
    q = df[df.period_kind == "quarter"]
    piv = q.pivot_table(index=["isin", "period_end", "basis"], columns="metric_key",
                        values="value", aggfunc="first")
    kn = q.groupby(["isin", "period_end", "basis"]).known_at.max()
    rev = q[q.metric_key == "revenue"]
    for (isin, pe, basis), row in piv.iterrows():
        def get(k):
            v = row.get(k)
            return None if v is None or pd.isna(v) else round(float(v), 4)
        revenue, pat = get("revenue"), get("pat")
        ebitda = None
        if all(get(k) is not None for k in ("pbt", "finance_costs", "depreciation")):
            ebitda = round(get("pbt") + get("finance_costs") + get("depreciation"), 4)
        result.append([isin, pe, basis, kn.get((isin, pe, basis)), revenue, ebitda, pat,
                       None if (revenue in (None, 0) or ebitda is None)
                       else round(ebitda / revenue * 100, 4),
                       get("eps"), "xbrl"])
    res = pd.DataFrame(result, columns=["isin", "period_end", "basis", "known_at", "revenue_cr",
                                        "ebitda_cr", "pat_cr", "ebitda_margin", "eps",
                                        "source"])
    res["y0"] = res.period_end.str[4:]
    prev = res.assign(period_end=(res.period_end.str[:4].astype(int) - 1).astype(str)
                      + res.period_end.str[4:])[["isin", "basis", "period_end",
                                                 "revenue_cr", "pat_cr"]]
    res = res.merge(prev, on=["isin", "basis", "period_end"], how="left",
                    suffixes=("", "_prev"))
    res["revenue_yoy"] = ((res.revenue_cr / res.revenue_cr_prev.where(res.revenue_cr_prev != 0)
                           - 1) * 100).round(4)
    res["pat_yoy"] = ((res.pat_cr / res.pat_cr_prev.where(res.pat_cr_prev != 0) - 1) * 100).round(4)
    clear(mcon, "company_result_pit")

    def _n(v):
        return None if v is None or (isinstance(v, float) and pd.isna(v)) else v

    res_rows = []
    for r in res[["isin", "period_end", "basis", "known_at", "revenue_cr", "ebitda_cr",
                  "pat_cr", "ebitda_margin", "revenue_yoy", "pat_yoy", "eps"]] \
            .itertuples(index=False):
        res_rows.append((r.isin, r.period_end, r.basis, r.known_at,
                         _n(r.revenue_cr), _n(r.ebitda_cr), _n(r.pat_cr),
                         _n(r.ebitda_margin), _n(r.revenue_yoy), _n(r.pat_yoy),
                         _n(r.eps), "xbrl"))
    n_res = insert_rows(mcon, "company_result_pit",
                        ["isin", "period_end", "basis", "known_at", "revenue_cr",
                         "ebitda_cr", "pat_cr", "ebitda_margin", "revenue_yoy", "pat_yoy",
                         "eps", "source"], res_rows)
    log(f"company_result_pit: {n_res:,} rows")

    fy = df[df.period_kind == "fy"]
    ins = df[df.period_kind == "instant"]
    fk = pd.concat([fy, ins]).groupby(["isin", "period_end", "basis"]).known_at.max()
    inc = fy.pivot_table(index=["isin", "period_end", "basis"], columns="metric_key",
                         values="value", aggfunc="first")
    bal = ins.pivot_table(index=["isin", "period_end", "basis"], columns="metric_key",
                          values="value", aggfunc="first")
    wc, ic = [], []
    # working capital is annual: a fiscal-year income statement joined to the balance sheet
    # dated the same day. A quarter-end instant has no TTM revenue, so it is not emitted.
    for key in sorted(set(inc.index) & set(bal.index)):
        def g(k, frames=(inc, bal)):
            for frame in frames:
                if key in frame.index and k in frame.columns:
                    v = frame.loc[key, k]
                    if v is not None and not pd.isna(v):
                        return float(v)
            return None
        isin, pe, basis = key
        rev, cogs = g("revenue"), g("cogs")
        # balance-sheet items are instants; a filer that tags one as a duration still has the
        # row in `inc`, so the income pivot is the fallback, not the first choice.
        inv, recv, pay = (g("inventory", (bal, inc)), g("receivables", (bal, inc)),
                          g("payables", (bal, inc)))
        known = fk.get(key)
        if not (isinstance(known, str) and any(v is not None for v in (recv, inv, pay))):
            continue
        dso = round(recv / rev * 365, 4) if rev and recv is not None else None
        dio = round(inv / cogs * 365, 4) if cogs and inv is not None else None
        dpo = round(pay / cogs * 365, 4) if cogs and pay is not None else None
        ccc = (round(dso + dio - dpo, 4) if None not in (dso, dio, dpo) else None)
        wc.append((isin, pe, basis, recv, inv, pay, rev, cogs, dso, dio, dpo, ccc,
                   "xbrl", known))
    for key in sorted(inc.index):
        isin, pe, basis = key
        row = inc.loc[key]
        pbt = row.get("pbt")
        fin = row.get("finance_costs")
        known = fk.get(key)
        if not (isinstance(known, str) and pbt is not None and not pd.isna(pbt)
                and fin is not None and not pd.isna(fin) and fin):
            continue
        ebit = float(pbt) + float(fin)
        ic.append((isin, pe, basis, round(ebit, 4), round(float(fin), 4),
                   round(ebit / float(fin), 4), "xbrl", known))
    clear(mcon, "company_working_capital")
    n_wc = insert_rows(mcon, "company_working_capital",
                       ["isin", "period_end", "basis", "receivables_cr", "inventory_cr",
                        "payables_cr", "revenue_cr", "cogs_cr", "dso", "dio", "dpo", "ccc",
                        "source", "known_at"], wc)
    clear(mcon, "company_interest_cover")
    n_ic = insert_rows(mcon, "company_interest_cover",
                       ["isin", "period_end", "basis", "ebit_cr", "finance_cost_cr",
                        "cover_x", "source", "known_at"], ic)
    log(f"company_working_capital: {n_wc:,} rows; company_interest_cover: {n_ic:,} rows")
    return {"map": n_map, "series": n_series, "result": n_res, "wc": n_wc, "ic": n_ic,
            "concepts": len(concepts), "concepts_missing": missing,
            "seconds": round(time.monotonic() - t0, 1)}


# ---------------------------------------------------------------------------------------
# 5. AR segment note -> company_segment_pnl
# ---------------------------------------------------------------------------------------
def build_segments(mcon: sqlite3.Connection, universe, log) -> dict:
    t0 = time.monotonic()
    con = ro(AR)
    clause = "AND isin IN (%s)" % ",".join("'%s'" % i for i in universe) if universe else ""
    rows = con.execute(f"""
        SELECT isin, doc_id, category, item, value, unit, period, basis, page, filed_at
        FROM ar_facts
        WHERE category IN ('segment','segment_revenue','segment_assets',
                           'segment_liabilities')
          AND value IS NOT NULL AND isin IS NOT NULL {clause}
    """).fetchall()
    con.close()
    log(f"segment facts in scope: {len(rows):,}")
    kept, dropped = [], defaultdict(int)
    for isin, doc_id, category, item, value, unit, period, basis, page, filed_at in rows:
        parsed = parse_segment_item(item)
        scale = unit_to_crore(unit)
        pe = fy_end(period)
        if not parsed:
            dropped["item shape"] += 1
            continue
        if scale is None:
            dropped["unit"] += 1
            continue
        if pe is None:
            dropped["period"] += 1
            continue
        b = (basis or "").lower()
        if b not in ("standalone", "consolidated"):
            dropped["basis"] += 1
            continue
        known = ist_text(filed_at)
        if not known:
            dropped["known_at"] += 1
            continue
        seg, metric = parsed
        kept.append((isin, seg, pe, metric, b, round(float(value) * scale, 6),
                     "ar_segment_note", doc_id, page, known))
    total = defaultdict(float)
    for isin, seg, pe, metric, b, value, *_ in kept:
        if metric == "revenue":
            total[(isin, pe, b)] += value
    rows_out = []
    for isin, seg, pe, metric, b, value, src, doc_id, page, known in kept:
        share = None
        if metric == "revenue" and total[(isin, pe, b)] > 0:
            share = round(value / total[(isin, pe, b)] * 100, 4)
        rows_out.append((isin, seg, pe, metric, b, value, share, src, doc_id, page, known, 1.0))
    clear(mcon, "company_segment_pnl")
    n = insert_rows(mcon, "company_segment_pnl",
                    ["isin", "segment", "period_end", "metric", "basis", "value_cr",
                     "share_of_total_pct", "source", "doc_id", "page", "known_at", "pit_conf"],
                    rows_out)
    log(f"company_segment_pnl: {n:,} rows from {len(rows):,} segment facts "
        f"(dropped: {dict(dropped)}, {round(time.monotonic() - t0, 1)}s)")
    return {"rows": n, "facts": len(rows), "dropped": dict(dropped),
            "seconds": round(time.monotonic() - t0, 1)}


# ---------------------------------------------------------------------------------------
# 6. ownership + sector (cheap PIT snapshots)
# ---------------------------------------------------------------------------------------
def build_ownership_sector(mcon: sqlite3.Connection, universe, log) -> dict:
    ei = ro(EI)
    clause = "AND isin IN (%s)" % ",".join("'%s'" % i for i in universe) if universe else ""
    own = []
    for isin, qe, broadcast, promoter, public in ei.execute(f"""
            SELECT isin, quarter_end, broadcast_at, promoter_pct, public_pct
            FROM shp_index
            WHERE isin IS NOT NULL AND quarter_end IS NOT NULL {clause}"""):
        own.append((isin, qe, ist_text(broadcast) or f"{qe}T23:59:59", promoter, None, None,
                    None, None, public, "shp_index"))
    sec = []
    for isin, macro, sector, industry, basic in ei.execute(f"""
            SELECT isin, macro, sector, industry, basic_industry FROM company_industry
            WHERE isin IS NOT NULL {clause}"""):
        sec.append((isin, macro, sector, industry, basic, BACKCAST_START, None,
                    "nse_classification"))
    ei.close()
    clear(mcon, "company_ownership_pit")
    n_own = insert_rows(mcon, "company_ownership_pit",
                        ["isin", "quarter_end", "known_at", "promoter_pct", "pledge_pct",
                         "fii_pct", "dii_pct", "mf_pct", "public_pct", "source"], own)
    clear(mcon, "company_sector_pit")
    n_sec = insert_rows(mcon, "company_sector_pit",
                        ["isin", "macro", "sector", "industry", "basic_industry",
                         "valid_from", "valid_to", "source"], sec)
    log(f"company_ownership_pit: {n_own:,} rows; company_sector_pit: {n_sec:,} rows")
    return {"ownership": n_own, "sector": n_sec}


# ---------------------------------------------------------------------------------------
# driver
# ---------------------------------------------------------------------------------------
def now() -> str:
    return dt.datetime.now(IST).isoformat(timespec="seconds")


def build(out: Path, universe_mode: str, log=print) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    universe = bank_universe() if universe_mode == "pilot" else None
    log(f"universe={universe_mode}: {len(universe) if universe else 'all'} ISINs")
    market_path, facts_path = out / MARKET_DB, out / FACTS_DB
    created_m = create_schema(market_path, T1_MARKET)
    created_f = create_schema(facts_path, T1_FACTS)
    log(f"schema: {len(created_m)} market objects, {len(created_f)} facts objects")
    market = sqlite3.connect(market_path)
    market.execute("PRAGMA journal_mode=WAL")
    facts = sqlite3.connect(facts_path)
    facts.execute("PRAGMA journal_mode=WAL")
    run_id = dt.datetime.now(IST).strftime("%Y%m%dT%H%M%S") + f"-{universe_mode}"
    result = {"run_id": run_id, "universe": universe_mode,
              "isins": len(universe) if universe else None, "started_at": now()}
    steps = [
        ("company_state_daily", lambda: build_company_state(market, universe, log)),
        ("index_membership", lambda: build_membership(market, out, universe, log)),
        ("events", lambda: build_events(market, universe, log)),
        ("ownership_sector", lambda: build_ownership_sector(market, universe, log)),
        ("metrics", lambda: build_metrics(facts, universe, log)),
        ("segments", lambda: build_segments(facts, universe, log)),
    ]
    for name, fn in steps:
        t0 = time.monotonic()
        try:
            result[name] = fn()
        except Exception as exc:                     # keep going: one gap is not the build
            log(f"STEP FAILED {name}: {type(exc).__name__}: {exc}")
            result[name] = {"error": f"{type(exc).__name__}: {exc}"}
        log(f"[{time.monotonic() - t0:.1f}s] {name}")
    compatibility_views(market)
    result["ended_at"] = now()
    for con, tables in ((market, ("company_state_daily", "company_membership_pit",
                                 "company_ownership_pit", "company_sector_pit",
                                 "event_day0", "event_leakage_window", "index_list")),
                        (facts, ("xbrl_concept_map", "company_metric_series",
                                 "company_result_pit", "company_segment_pnl",
                                 "company_working_capital", "company_interest_cover"))):
        counts = {}
        for t in tables:
            try:
                counts[t] = table_count(con, t)
            except sqlite3.OperationalError as exc:
                counts[t] = f"MISSING ({exc})"
        result.setdefault("counts", {}).update(counts)
        clear(con, "build_run")
        insert_rows(con, "build_run", ["run_id", "started_at", "ended_at", "doc_type",
                                       "docs_in", "docs_ok", "docs_failed", "chunks_out",
                                       "tags_out", "notes"],
                    [(run_id, result["started_at"], result["ended_at"], "t1",
                      result["isins"], sum(counts.values()), 0, 0, 0,
                      json.dumps(counts, sort_keys=True))])
        con.commit()
        con.close()
    (out / "build_result.json").write_text(json.dumps(result, indent=1, default=str),
                                           encoding="utf-8")
    log("counts: " + json.dumps(result["counts"], sort_keys=True))
    return result


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--universe", choices=("pilot", "all"), default="pilot")
    ap.add_argument("--out", default=str(REPO / ".tmp" / "pilot"))
    ap.add_argument("--checks", action="store_true",
                    help="do not build: print the CHECKS.md measurement blocks for --out")
    a = ap.parse_args(argv)
    out = Path(a.out)
    if a.checks:
        from reality_engine.pilot.checks_t1 import main as checks_main
        return checks_main(out)
    result = build(out, a.universe)
    failed = [k for k, v in result.items() if isinstance(v, dict) and "error" in v]
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
