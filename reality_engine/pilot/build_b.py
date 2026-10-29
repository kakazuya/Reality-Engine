"""Pilot (b) build — the (b) tables whose source is already held. No network, no live writes.

The master bank has 435 class-(b) cases: answerable once a designed table exists. This module
builds the ones whose source is already on disk or in a live store, using the EXACT DDL of
``tasks/SCHEMA_FINAL_2026-10-29.sql`` (the schema prefix is stripped because each pilot file is
its own database):

  <out>/market_state_b.db
      index_list, company_membership_pit   from 6 held constituent CSVs + 444 NSE notice PDFs
                                           (reuses build_t1.build_membership; same rebuild)
      series_meta, series_observation      from D:/RealityEngine/raw/commodity_series/
      commodity_price_daily + 5 views      defined by the final DDL over series_observation
      fno_oi_daily                         from 1,930 F&O bhavcopy zips (2019-01..2026-10)
      mkt_nse_full_daily                   from truth_duckdb.px_nse (2019-01-01..2026-10-19)

  <out>/metric_state_b.db                  NOT created: every metric_state table still needs
                                           a document reader (capex_project etc.), so the
                                           (b) metric work is skipped and reported.

PIT rules
    * no timestamp is ever the crawl date; every table either carries the source's own
      publication stamp (series_observation.known_at = the WB sheet's "Updated on" date at
      23:59:59 IST, so it can never leak into an earlier decision) or is keyed by the
      source's session/effective date (fno/bhavcopy `date`, membership `added_on`);
    * the 15:30 IST day-0 rule is applied through ``build_t1.day0`` (unchanged);
    * a date-only stamp becomes end-of-day, i.e. usable from the NEXT session (offset 1).

Usage:
    python -m reality_engine.pilot.build_b                 # build every held table
    python -m reality_engine.pilot.build_b --only fno      # one builder
    python -m reality_engine.pilot.build_b --verify        # checks + hand check + reclassify
"""
from __future__ import annotations

import argparse
import bisect
import csv
import datetime as dt
import glob
import io
import json
import os
import re
import sqlite3
import time
import zipfile
from collections import defaultdict
from pathlib import Path

from reality_engine.pilot import build_t1

REPO = Path(__file__).resolve().parents[2]
SCHEMA_SQL = REPO / "tasks" / "SCHEMA_FINAL_2026-10-29.sql"
CASES = REPO / "tasks" / "SCHEMA_FINAL_CASES_2026-10-29.jsonl"
MASTER_BANK = REPO / "tasks" / "master_bank" / "MASTER_BANK.jsonl"
T2_ISINS = REPO / "tasks" / "pilot60" / "T2_ISINS.txt"
PILOT_DIR = REPO / "tasks" / "pilot_b"

DATA_ROOT = Path(os.environ.get("REALITY_DATA_ROOT", REPO / "reality_engine" / "data"))
EI = DATA_ROOT / "equity_intelligence.db"
SNAPSHOT = DATA_ROOT / "snapshots" / "truth_2026-10-19.duckdb"
RAW_ROOT = Path(os.environ.get("REALITY_RAW_ROOT", r"D:\RealityEngine\raw"))
FO_DIR = RAW_ROOT / "fo_bhavcopy"
COMMODITY_CSV = RAW_ROOT / "commodity_series" / "commodity_series.csv"
INDEX_HISTORY = RAW_ROOT / "index_history"
BHAVCOPY_RAW = RAW_ROOT / "bhavcopy"

OUT = REPO / ".tmp" / "pilot_b"
MARKET_DB = OUT / "market_state_b.db"
METRIC_DB = OUT / "metric_state_b.db"

MARKET_KEEP = {
    "build_run", "index_list", "company_membership_pit", "series_meta", "series_observation",
    "commodity_price_daily", "freight_rate_daily", "rainfall_daily", "rural_wage_series",
    "shipment_transit", "rate_series_daily", "fno_oi_daily",
}
BHAVCOPY_KEEP = {"mkt_nse_full_daily"}
BUILD_DATE = "2026-10-29"

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
SESSION_CLOSE = dt.time(15, 30)


def now() -> str:
    return dt.datetime.now(IST).strftime("%Y-%m-%dT%H:%M:%S")


def log(msg: str) -> None:
    print(msg, flush=True)


# ---------------------------------------------------------------------------------------
# final DDL -> one file per domain (prefix stripped, table set filtered)
# ---------------------------------------------------------------------------------------
_CREATE = re.compile(
    r"CREATE\s+(?:VIRTUAL\s+TABLE|TABLE|VIEW|(?:UNIQUE\s+)?INDEX)\s+(?:IF\s+NOT\s+EXISTS\s+)?"
    r"(?:([A-Za-z_][A-Za-z0-9_]*)\.)?([A-Za-z_][A-Za-z0-9_]*)", re.I)
_ON_TABLE = re.compile(r"\bON\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", re.I)
_QUALIFIER = re.compile(
    r"\b(?:market_state|metric_state|equity_intelligence|truth_duckdb|results_xbrl|ar_facts|"
    r"deck_figures|concall_facts|bse_announcements|chunks_v3)\.", re.I)


def schema_statements(sql_text: str):
    """[(domain, object_name, statement)] for every CREATE in the final design file."""
    clean = "\n".join(re.sub(r"--.*$", "", line) for line in sql_text.splitlines())
    out = []
    for stmt in clean.split(";"):
        s = stmt.strip()
        if not re.match(r"CREATE\b", s, re.I):
            continue
        m = _CREATE.search(s)
        if m:
            out.append(((m.group(1) or "").lower(), m.group(2), s))
    return out


def dequalify(stmt: str) -> str:
    """``market_state.series_observation`` -> ``series_observation`` (one file per domain)."""
    return _QUALIFIER.sub("", stmt)


def create_schema(target, domain: str, keep=None, sql_text: str | None = None) -> list[str]:
    """Create the kept tables/views/indexes of one domain from the FINAL DDL."""
    text = sql_text if sql_text is not None else SCHEMA_SQL.read_text(encoding="utf-8")
    own = not isinstance(target, sqlite3.Connection)
    con = sqlite3.connect(str(target)) if own else target
    if own and str(target) != ":memory:":
        con.execute("PRAGMA journal_mode=WAL")
    made = []
    for dom, name, stmt in schema_statements(text):
        if dom != domain:
            continue
        index_on = None
        if re.match(r"\s*CREATE\s+(?:UNIQUE\s+)?INDEX", stmt, re.I):
            m = _ON_TABLE.search(stmt)
            index_on = m.group(1) if m else None
            if keep is not None and index_on not in keep and name not in keep:
                continue
        elif keep is not None and name not in keep:
            continue
        if re.match(r"\s*CREATE\s+VIEW", stmt, re.I):
            con.execute(f"DROP VIEW IF EXISTS {name}")
        con.execute(dequalify(stmt))
        made.append(name)
    con.commit()
    if own:
        con.close()
    return made


def _split_top_level(body: str) -> list[str]:
    parts, depth, cur = [], 0, []
    for ch in body:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    if "".join(cur).strip():
        parts.append("".join(cur))
    return parts


def expected_columns(sql_text: str, domain: str, table: str):
    """[(name, type)] and the PRIMARY KEY column order, parsed from the FINAL DDL text.

    Used by the schema-match test: the pilot table must carry exactly these columns.
    """
    tname = table.rsplit(".", 1)[-1]
    for dom, name, stmt in schema_statements(sql_text):
        if dom != domain or name.lower() != tname.lower():
            continue
        if not re.match(r"\s*CREATE\s+TABLE", stmt, re.I):
            continue
        body = stmt[stmt.index("(") + 1: stmt.rindex(")")]
        cols, pk = [], []
        for part in _split_top_level(body):
            t = part.strip()
            if not t or re.match(r"(?i)^(PRIMARY|UNIQUE|CHECK|FOREIGN|CONSTRAINT)\b", t):
                continue
            words = t.split()
            name = words[0].strip('"`[]')
            cols.append((name, words[1].upper() if len(words) > 1 else ""))
            if re.search(r"\bPRIMARY\s+KEY\b", t, re.I):
                pk.append(name)
        m = re.search(r"PRIMARY\s+KEY\s*\(([^)]*)\)", body, re.I)
        if m:                                        # table-level PRIMARY KEY (a, b, c)
            pk = [c.strip().strip('"`[]') for c in m.group(1).split(",")]
        return cols, pk
    raise KeyError(f"{domain}.{table} is not in {SCHEMA_SQL.name}")


# ---------------------------------------------------------------------------------------
# PIT helpers
# ---------------------------------------------------------------------------------------
def series_known_at(value) -> str:
    """A monthly series' publication stamp -> ISO-8601 IST text.

    A date-only stamp (the World Bank sheet's own "Updated on" cell) becomes 23:59:59, i.e.
    it is usable from the NEXT session under the 15:30 rule — never earlier. Refusing an
    empty stamp rather than stamping the build date is the rule the fetcher already follows.
    """
    s = str(value or "").strip()
    if not s:
        raise ValueError("series row has no publication stamp")
    if len(s) == 10 and s[4] == "-" and s[7] == "-":
        return f"{s}T23:59:59"
    stamp = build_t1.ist_text(s)
    if not stamp:
        raise ValueError(f"unparseable publication stamp {value!r}")
    return stamp


def session_known_at(session: str) -> str:
    """A bhavcopy/F&O row for session D is knowable at the 15:30 IST close of D."""
    return f"{session}T15:30:00"


# ---------------------------------------------------------------------------------------
# series (commodity + the six views)
# ---------------------------------------------------------------------------------------
def _num(value):
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def build_series(con, csv_path: Path = COMMODITY_CSV, log=log) -> dict:
    """D:/raw/commodity_series/commodity_series.csv -> series_meta + series_observation."""
    meta, obs, seen = {}, [], set()
    with csv_path.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            code = row["series_code"].strip()
            day = row["date"].strip()
            if (code, day) in seen:
                raise ValueError(f"duplicate observation {code} {day}")
            seen.add((code, day))
            value = _num(row["close"])
            if value is None:
                continue
            obs.append((code, code, "commodity", day, None, value, row["unit"].strip(),
                        None, row["source"].strip(), series_known_at(row["known_at"]), 0.8))
            meta.setdefault(code, row)
    build_t1.clear(con, "series_observation")
    build_t1.clear(con, "series_meta")
    build_t1.insert_rows(con, "series_meta",
                         ["series_code", "display_name", "kind", "source", "unit", "cadence",
                          "fetched_to", "pit_note"],
                         [(c, c.replace("wb_", "World Bank ").replace("_", " ").title(),
                           "commodity", r["source"].strip(), r["unit"].strip(), "monthly",
                           max(o[3] for o in obs if o[0] == c),
                           "WB Pink Sheet 'Updated on' vintage; every historical row carries "
                           "the held vintage stamp because the sheet is refetched, not "
                           "as-first-published. Date-only -> 23:59:59 IST (pit_conf 0.8).")
                          for c, r in sorted(meta.items())])
    build_t1.insert_rows(con, "series_observation",
                         ["series_code", "dim_id", "kind", "period_start", "period_end", "value",
                          "unit", "departure_pct", "source", "known_at", "pit_conf"], obs)
    n = build_t1.table_count(con, "series_observation")
    log(f"series: {len(meta)} series, {n:,} observations "
        f"({min(o[3] for o in obs)}..{max(o[3] for o in obs)})")
    return {"series": len(meta), "rows": n}


# ---------------------------------------------------------------------------------------
# F&O bhavcopy (two file formats) -> fno_oi_daily
# ---------------------------------------------------------------------------------------
_OLD = {"INSTRUMENT", "SYMBOL", "EXPIRY_DT", "STRIKE_PR", "OPTION_TYP", "SETTLE_PR",
        "CONTRACTS", "OPEN_INT", "CHG_IN_OI"}
_NEW = {"TradDt", "TckrSymb", "XpryDt", "StrkPric", "OptnTp", "SttlmPric", "TtlTradgVol",
        "OpnIntrst", "ChngInOpnIntrst"}
_MON = {m: i for i, m in enumerate(
    ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"), 1)}


def fo_format(header) -> str:
    names = {h.strip() for h in header}
    if _NEW <= names:
        return "new"
    if _OLD <= names:
        return "old"
    raise ValueError(f"unknown F&O bhavcopy header: {sorted(names)[:6]}")


def fo_date_from_name(filename: str) -> str | None:
    """Both archive naming schemes -> ISO date (fallback only; the row's own date wins)."""
    m = re.search(r"BhavCopy_NSE_FO_\d+_\d+_\d+_(\d{8})_", filename)
    if m:
        s = m.group(1)
        return f"{s[:4]}-{s[4:6]}-{s[6:]}"
    m = re.search(r"^fo(\d{2})([A-Z]{3})(\d{4})bhav", filename)
    if m:
        return f"{m.group(3)}-{_MON[m.group(2)]:02d}-{m.group(1)}"
    return None


def _old_date(value: str) -> str | None:
    """'02-Mar-2021' (the old bhavcopy's EXPIRY_DT and TIMESTAMP) -> ISO date."""
    s = (value or "").strip().upper()
    m = re.match(r"^(\d{1,2})-([A-Z]{3})-(\d{4})$", s)
    if not m:
        return None
    return f"{m.group(3)}-{_MON[m.group(2)]:02d}-{int(m.group(1)):02d}"


def fo_normalize(kind: str, header, row):
    """One bhavcopy row -> (date, underlying, expiry, strike, type, oi, oi_chg, vol, settle, isin).

    Returns None for a malformed or non-derivative row. Futures are kept for every
    underlying; options only for the pilot symbols (see ``build_fno``).
    """
    h = {name.strip(): i for i, name in enumerate(header)}

    def cell(key):
        i = h.get(key)
        return (row[i] if i is not None and i < len(row) else "").strip()

    if kind == "new":
        date = cell("BizDt") or cell("TradDt")
        underlying, expiry = cell("TckrSymb"), cell("XpryDt")
        opt = cell("OptnTp").upper() or "FUT"
        strike, oi, chg = _num(cell("StrkPric")), _num(cell("OpnIntrst")), \
            _num(cell("ChngInOpnIntrst"))
        vol, settle, isin = _num(cell("TtlTradgVol")), _num(cell("SttlmPric")), cell("ISIN")
    else:
        inst = cell("INSTRUMENT").upper()
        if not inst.startswith(("FUT", "OPT")):
            return None
        date = _old_date(cell("TIMESTAMP"))
        underlying, expiry = cell("SYMBOL"), _old_date(cell("EXPIRY_DT"))
        opt = cell("OPTION_TYP").upper()
        if not opt or opt in ("XX", "-"):
            opt = "FUT" if inst.startswith("FUT") else ""
        strike, oi, chg = _num(cell("STRIKE_PR")), _num(cell("OPEN_INT")), \
            _num(cell("CHG_IN_OI"))
        vol, settle, isin = _num(cell("CONTRACTS")), _num(cell("SETTLE_PR")), ""
    if opt not in ("CE", "PE", "FUT") or not underlying or not expiry:
        return None
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
        return None
    if strike is None or (opt == "FUT" and strike <= 0):
        strike = 0.0 if opt == "FUT" else strike
    if strike is None:
        return None
    return (date, underlying, expiry, strike, opt, oi, chg, vol, settle, isin or None)


def symbol_windows(ei: Path = EI) -> dict[str, list[tuple[str, str, str]]]:
    """{NSE symbol: [(first_date, last_date, isin)]} for point-in-time ISIN resolution."""
    con = sqlite3.connect(f"file:{ei}?mode=ro", uri=True)
    con.execute("PRAGMA query_only=ON")
    out = defaultdict(list)
    for sym, isin, first, last in con.execute(
            "SELECT symbol, isin, first_date, last_date FROM symbol_isin_history "
            "WHERE exchange = 'NSE' AND symbol IS NOT NULL"):
        out[sym].append((first or "", last or "9999-12-31", isin))
    con.close()
    for windows in out.values():
        windows.sort()
    return out


def resolve_isin(windows, symbol: str, on_date: str) -> str | None:
    rows = windows.get(symbol) or []
    for first, last, isin in rows:
        if first <= on_date <= last:
            return isin
    return None


def fno_universe(case_path: Path = CASES, mb_path: Path = MASTER_BANK,
                 t2_path: Path = T2_ISINS) -> set[str]:
    """Symbols whose OPTION rows the pilot keeps: the 60 pilot + 30 regression ISINs
    (resolved through the symbol history, so re-keyed symbols are included) and every
    entity named by an (b) F&O case. Futures are kept market-wide (ban list, rollover)."""
    isins = {line.strip() for line in t2_path.read_text(encoding="utf-8").splitlines()
             if line.strip()}
    fno_cases = set()
    with case_path.open(encoding="utf-8") as f:
        for line in f:
            case = json.loads(line)
            if case["status"].startswith("needs_new_fetch:nse_fno"):
                fno_cases.add(case["case_id"])
    symbols = set()
    with mb_path.open(encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            for ent in row.get("entities") or []:
                if isinstance(ent, dict) and row.get("mid") in fno_cases and ent.get("symbol"):
                    symbols.add(ent["symbol"].strip())
    con = sqlite3.connect(f"file:{EI}?mode=ro", uri=True)
    con.execute("PRAGMA query_only=ON")
    q = ",".join("?" * len(isins))
    symbols.update(sym for (sym,) in con.execute(
        "SELECT DISTINCT symbol FROM symbol_isin_history WHERE exchange = 'NSE' "
        f"AND isin IN ({q}) AND symbol IS NOT NULL", tuple(sorted(isins))))
    con.close()
    return symbols


def build_fno(con, fo_dir: Path = FO_DIR, keep_symbols=None, log=log) -> dict:
    """Stream every F&O bhavcopy zip once -> fno_oi_daily (futures all, options pilot-only)."""
    keep = keep_symbols if keep_symbols is not None else fno_universe()
    windows = symbol_windows()
    files = sorted(glob.glob(str(fo_dir / "*.zip")))
    if not files:
        raise FileNotFoundError(f"no F&O bhavcopy zips under {fo_dir}")
    build_t1.clear(con, "fno_oi_daily")
    cols = ["date", "underlying", "expiry", "strike", "option_type", "oi", "oi_change",
            "volume", "settle", "isin"]
    batch, inserted, skipped = [], 0, 0
    t0 = time.monotonic()
    for n, path in enumerate(files, 1):
        with zipfile.ZipFile(path) as z:
            member = z.namelist()[0]
            with z.open(member) as raw:
                reader = csv.reader(io.TextIOWrapper(raw, encoding="utf-8-sig", errors="replace",
                                                     newline=""))
                header = next(reader)
                kind = fo_format(header)
                for row in reader:
                    try:
                        rec = fo_normalize(kind, header, row)
                    except (IndexError, ValueError):
                        rec = None
                    if rec is None:
                        skipped += 1
                        continue
                    if rec[4] != "FUT" and rec[1] not in keep:
                        continue
                    date, underlying, expiry, strike, opt, oi, chg, vol, settle, isin = rec
                    batch.append((date, underlying, expiry, strike, opt, oi, chg, vol, settle,
                                  isin or resolve_isin(windows, underlying, date)))
        if len(batch) >= 20000:
            build_t1.insert_rows(con, "fno_oi_daily", cols, batch)
            inserted += len(batch)
            batch = []
        if n % 200 == 0:
            log(f"  fno {n}/{len(files)} files, {inserted + len(batch):,} rows "
                f"[{time.monotonic() - t0:.0f}s]")
    if batch:
        build_t1.insert_rows(con, "fno_oi_daily", cols, batch)
        inserted += len(batch)
    n_rows = build_t1.table_count(con, "fno_oi_daily")
    span = con.execute("SELECT MIN(date), MAX(date), COUNT(DISTINCT date) "
                       "FROM fno_oi_daily").fetchone()
    log(f"fno_oi_daily: {n_rows:,} rows, {span[2]:,} sessions {span[0]}..{span[1]} "
        f"({inserted - n_rows} key collisions, {skipped} malformed rows skipped) "
        f"[{time.monotonic() - t0:.0f}s]")
    return {"rows": n_rows, "sessions": span[2], "from": span[0], "to": span[1],
            "files": len(files), "keep_symbols": len(keep)}


# ---------------------------------------------------------------------------------------
# NSE full bhavcopy -> mkt_nse_full_daily (from the dated truth snapshot)
# ---------------------------------------------------------------------------------------
def build_bhavcopy(con, snapshot: Path = SNAPSHOT, log=log) -> dict:
    """truth_duckdb.px_nse (bhavcopy-derived, 2019-01-01..2026-10-19) -> the full table.

    The D: raw store holds only 38 recent sec_bhavdata_full files, not the 2019+ archive;
    px_nse is the held, bhavcopy-derived store that covers the missing delisted/SME names.
    """
    import duckdb
    con.execute("DROP TABLE IF EXISTS mkt_nse_full_daily")
    create_schema(con, "equity_intelligence", BHAVCOPY_KEEP)
    build_t1.clear(con, "mkt_nse_full_daily")
    d = duckdb.connect(str(snapshot), read_only=True)
    cur = d.execute(
        "SELECT date, symbol, series, prev_close, open, high, low, close, volume, "
        "value_inr, num_trades, deliverable_qty, delivery_pct FROM px_nse "
        "ORDER BY date, symbol, series")
    cols = ["date", "symbol", "series", "prev_close", "open", "high", "low", "last", "close",
            "avg_price", "volume", "turnover_lacs", "num_trades", "deliverable_qty",
            "delivery_pct"]
    inserted, t0 = 0, time.monotonic()
    while True:
        rows = cur.fetchmany(50000)
        if not rows:
            break
        batch = []
        for (day, symbol, series, prev_close, op, hi, lo, close, volume, value_inr,
             trades, deliv, deliv_pct) in rows:
            batch.append((day.isoformat() if hasattr(day, "isoformat") else str(day),
                          symbol, series, prev_close, op, hi, lo,
                          None,                          # last: not carried by px_nse
                          close,
                          (value_inr / volume if value_inr and volume else None),
                          volume,
                          (value_inr / 1e5 if value_inr is not None else None),
                          trades, deliv, deliv_pct))
        build_t1.insert_rows(con, "mkt_nse_full_daily", cols, batch)
        inserted += len(batch)
    d.close()
    n_rows = build_t1.table_count(con, "mkt_nse_full_daily")
    span = con.execute("SELECT MIN(date), MAX(date), COUNT(DISTINCT date) "
                       "FROM mkt_nse_full_daily").fetchone()
    log(f"mkt_nse_full_daily: {n_rows:,} rows, {span[2]:,} sessions {span[0]}..{span[1]} "
        f"[{time.monotonic() - t0:.0f}s]")
    return {"rows": n_rows, "sessions": span[2], "from": span[0], "to": span[1]}


# ---------------------------------------------------------------------------------------
# membership (reuses the T1 rebuild; held CSVs + notice PDFs)
# ---------------------------------------------------------------------------------------
def build_membership(con, out: Path = OUT, log=log) -> dict:
    return build_t1.build_membership(con, out, None, log)


# ---------------------------------------------------------------------------------------
# case re-classification (b -> a only when the built field is verified)
# ---------------------------------------------------------------------------------------
_MONTH = {m: i for i, m in enumerate(
    ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"), 1)}


def period_end(text) -> str | None:
    """Best-effort END date of a free-text bank period; None when the text is not a window.

    Conservative by design: None means "cannot verify", never "covers everything".
    """
    s = " ".join(str(text or "").upper().split())
    if not s:
        return None
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return s
    quarters = re.findall(r"Q([1-4])\s*FY(\d{2})", s)
    if quarters:                                     # Q1FY27 = Apr-Jun 2026, Q4FY27 = Jan-Mar 2027
        q, fy = int(quarters[-1][0]), 2000 + int(quarters[-1][1])
        return ("%d-%s" % (fy - (q < 4), ("06-30", "09-30", "12-31", "03-31")[q - 1]))
    m = re.search(r"FY(\d{2})\s*[-/]\s*FY(\d{2})", s)
    if m:
        return f"{2000 + int(m.group(2))}-03-31"
    m = re.search(r"(\d{4})\s*[-/]\s*(\d{4})", s)
    if m:
        return f"{m.group(2)}-12-31"
    m = re.search(r"FY(\d{2})", s)
    if m:
        return f"{2000 + int(m.group(1))}-03-31"
    m = re.search(r"(\d{1,2})\s*-\s*(\d{1,2})\s+([A-Z]{3})[A-Z]*\s+(\d{4})", s)
    if m:
        return f"{m.group(4)}-{_MONTH[m.group(3)]:02d}-{int(m.group(2)):02d}"
    m = re.search(r"(\d{4})-(\d{2})\s*/\s*(\d{4})-(\d{2})", s)
    if m:
        y, mo = int(m.group(3)), int(m.group(4))
        day = (dt.date(y + (mo == 12), mo % 12 + 1, 1) - dt.timedelta(days=1)).isoformat()
        return day
    m = re.search(r"(?:AS OF\s+)?(\d{1,2})\s+([A-Z]{3})[A-Z]*\s+(\d{4})", s)
    if m:
        return f"{m.group(3)}-{_MONTH[m.group(2)]:02d}-{int(m.group(1)):02d}"
    m = re.fullmatch(r"(\d{4})", s)
    if m:
        return f"{s}-12-31"
    return None


_INDEX_Q = re.compile(r"NIFTY[\sA-Z0-9&.\-:]*")


def question_index(text, con) -> tuple[str, str] | None:
    """(index_code, display_name) of the index a case question names, longest hit wins.

    Matching is on the space-stripped text so 'NIFTY MIDSMALLCAP400 50:50' resolves to
    'NIFTY MIDSMALLCAP 400'; the longest display name wins so 'NIFTY 500' beats 'NIFTY 50'.
    """
    raw = str(text or "").upper()
    best = None
    for code, name in con.execute("SELECT index_code, display_name FROM index_list"):
        if re.sub(r"\s+", "", name) in re.sub(r"\s+", "", raw):
            if best is None or len(name) > len(best[1]):
                best = (code, name)
    if best:
        return best
    m = _INDEX_Q.search(raw)
    if not m:
        return None
    name = build_t1.clean_index_name(m.group(0))
    return (build_t1.index_code(name), name) if name else None


def _case_entities(mb_row) -> list[dict]:
    return [e for e in (mb_row.get("entities") or []) if isinstance(e, dict)]


#: question keyword -> the series the case needs. ``wb_aluminium`` is deliberately listed
#: even though it is NOT held, so an aluminium case is refused instead of being answered
#: with a different commodity.
COMMODITY_ALIASES = (
    (r"ALUMINI?UM", "wb_aluminium"),
    (r"CRUDE|BRENT|WTI", "wb_crude_brent"),
    (r"NAT(?:URAL)?\s*GAS|LNG", "wb_natgas_us"),
    (r"\bCOAL\b", "wb_coal_aus"),
    (r"\bCOPPER\b", "wb_copper"),
    (r"\bZINC\b", "wb_zinc"),
    (r"\bLEAD\b", "wb_lead"),
    (r"\bNICKEL\b", "wb_nickel"),
    (r"\bTIN\b", "wb_tin"),
    (r"\bGOLD\b", "wb_gold"),
    (r"\bSILVER\b", "wb_silver"),
    (r"\bPLATINUM\b", "wb_platinum"),
    (r"IRON\s*ORE", "wb_iron_ore"),
    (r"\bUREA\b", "wb_urea"),
    (r"\bDAP\b", "wb_dap"),
    (r"\bCOTTON\b", "wb_cotton_a"),
    (r"\bRUBBER\b", "wb_rubber"),
    (r"PALM\s*OIL", "wb_palm_oil"),
    (r"SOY(?:BEAN)?\s*OIL", "wb_soybean_oil"),
)


def named_series(question) -> list[str]:
    """Series codes a case question names (may be empty)."""
    q = str(question or "").upper()
    return [code for pattern, code in COMMODITY_ALIASES if re.search(pattern, q)]


def verify_case(case, mb_row, dbs) -> tuple[bool, str]:
    """(verified, note) for one (b) case whose blocker is one of the built tables."""
    status = case.get("status", "")
    ents = _case_entities(mb_row)
    question = str(mb_row.get("question") or "")
    if re.search(r"\bWILL\b|\bNEXT\b|EXPECT|FORECAST|PREDICT|LIKELY|GUESS", question.upper()):
        return False, "judgement/prediction ask: no held store answers it (EXPECTATIONS gate)"
    as_of = (mb_row.get("as_of") or "")[:10] or BUILD_DATE
    per_end = period_end(mb_row.get("period"))
    market, fno = dbs["market"], dbs["fno"]

    if status.endswith("commodity_price_daily"):
        end = per_end or as_of
        held = {r[0] for r in market.execute("SELECT series_code FROM series_meta")}
        want = named_series(question)
        missing = [c for c in want if c not in held]
        if missing:
            return False, (f"commodity {', '.join(sorted(set(missing)))} is not among the "
                           f"{len(held)} held World Bank series")
        if want:
            row = market.execute(
                "SELECT series_code, MIN(period_start), MAX(period_start) "
                "FROM series_observation WHERE series_code IN (%s) AND period_start <= ? "
                "AND known_at <= ? GROUP BY series_code HAVING MAX(period_start) >= ? "
                "ORDER BY series_code LIMIT 1" % ",".join("?" * len(want)),
                (*want, end, f"{as_of}T23:59:59", per_end or "2000-01-01")).fetchone()
        else:
            row = market.execute(
                "SELECT series_code, MIN(period_start), MAX(period_start) "
                "FROM series_observation WHERE period_start <= ? AND known_at <= ? "
                "GROUP BY series_code HAVING MAX(period_start) >= ? "
                "ORDER BY series_code LIMIT 1",
                (end, f"{as_of}T23:59:59", per_end or "2000-01-01")).fetchone()
        if row:
            label = want[0] if want else f"a held series ({len(held)} of the 40 asked for)"
            return True, (f"{label} covers {row[1]}..{row[2]} for the case window "
                          f"(period end {end})")
        return False, (f"no held commodity observation covers period end {end} "
                       f"as known by {as_of}")

    if status.endswith(("nse_fno_bhavcopy", "nse_fno_history")):
        symbols = [e.get("symbol") for e in ents if e.get("symbol")]
        if not symbols:
            return False, "case names no listed entity"
        ok = fno.execute(
            "SELECT COUNT(DISTINCT underlying) FROM fno_oi_daily "
            "WHERE underlying IN (%s) AND date <= ?" % ",".join("?" * len(symbols)),
            (*symbols, as_of)).fetchone()[0]
        if ok == len(set(symbols)):
            return True, f"fno_oi_daily has rows for {', '.join(sorted(set(symbols)))} <= {as_of}"
        return False, f"no F&O contract for {', '.join(sorted(symbols))} (not F&O eligible)"

    if status.endswith("bhavcopy_backfill"):
        symbols = [e.get("symbol") for e in ents if e.get("symbol")]
        if not symbols:
            return False, "case names no listed entity"
        ok = market.execute(
            "SELECT COUNT(DISTINCT symbol) FROM mkt_nse_full_daily "
            "WHERE symbol IN (%s) AND date <= ?" % ",".join("?" * len(symbols)),
            (*symbols, as_of)).fetchone()[0]
        if ok == len(set(symbols)):
            return True, (f"mkt_nse_full_daily has {ok}/{len(set(symbols))} entity symbols "
                          f"<= {as_of}")
        return False, f"mkt_nse_full_daily is missing {', '.join(sorted(symbols))}"

    if status.endswith("nse_index_circulars"):
        named = question_index(mb_row.get("question"), market)
        if not named:
            return False, "case names no Nifty index"
        code, name = named
        row = market.execute(
            "SELECT coverage, members_at_snapshot, changes_parsed FROM index_list "
            "WHERE index_code = ?", (code,)).fetchone()
        if not row:
            return False, f"{name} is not in index_list"
        coverage, members, changes = row
        changes_q = re.search(r"\b(?:ENTER|ENTERED|ENTRY|ENTERING|EXIT|EXITED|EXCLUSION|"
                              r"INCLUSION|INCLUDED|EXCLUDED|ADDED|REMOVED|REPLACED|"
                              r"REPLACEMENT)\b", str(mb_row.get("question") or "").upper())
        if coverage != "changes_only" or changes_q:
            n = market.execute(
                "SELECT COUNT(*) FROM company_membership_pit WHERE index_code = ? "
                "AND added_on <= ?", (code, as_of)).fetchone()[0]
            if n:
                return True, f"{name}: {n} dated intervals <= {as_of} (coverage {coverage})"
        return False, (f"{name}: only {changes} notice-dated changes held "
                       f"(coverage {coverage}); the full constituent list is not held")
    return False, f"blocker {status} is not one of the built tables"


def readonly(path: Path) -> sqlite3.Connection:
    """Read-only connection to a finished pilot file (WAL absent -> immutable is safe)."""
    uri = f"file:{path}?mode=ro" + ("" if Path(f"{path}-wal").exists() else "&immutable=1")
    con = sqlite3.connect(uri, uri=True)
    con.execute("PRAGMA query_only=ON")
    return con


def reclassify(log=log) -> dict:
    """Copy the cases JSONL into tasks/pilot_b; flip verified (b) cases to a; write counts."""
    blocker_table = {
        "commodity_price_daily": "commodity_price_daily",
        "nse_index_circulars": "company_membership_pit",
        "bhavcopy_backfill": "mkt_nse_full_daily",
        "nse_fno_bhavcopy": "fno_oi_daily",
        "nse_fno_history": "fno_oi_daily",
    }
    mb = {}
    with MASTER_BANK.open(encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            mb[row["mid"]] = row
    market = readonly(MARKET_DB)
    dbs = {"market": market, "fno": market}
    rows, moved, kept = [], [], []
    with CASES.open(encoding="utf-8") as f:
        for line in f:
            case = json.loads(line)
            table = blocker_table.get(case["status"].split(":")[-1], "")
            if case["class"] == "b" and table:
                ok, note = verify_case(case, mb.get(case["case_id"]) or {}, dbs)
                if ok:
                    case["class"] = "a"
                    case["reason"] = f"pilot_b verified: {note}"
                    case["status"] = "answerable_now"
                    moved.append((case["case_id"], table, note))
                else:
                    case["reason"] = note
                    kept.append((case["case_id"], table, note))
            rows.append(case)
    market.close()
    PILOT_DIR.mkdir(parents=True, exist_ok=True)
    with (PILOT_DIR / "cases_pilot_b.jsonl").open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    counts = defaultdict(int)
    for r in rows:
        counts[r["class"]] += 1
    result = {"counts": dict(sorted(counts.items())), "moved": len(moved),
              "kept_b": len(kept), "moved_cases": moved, "kept_cases": kept}
    (PILOT_DIR / "reclass.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
    log(f"reclassify: a {counts.get('a', 0)} / b {counts.get('b', 0)} / c {counts.get('c', 0)} "
        f"({len(moved)} moved b -> a, {len(kept)} still b)")
    return result


# ---------------------------------------------------------------------------------------
# build + verify
# ---------------------------------------------------------------------------------------
def build(out: Path = OUT, only: set[str] | None = None) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    steps = [("series", lambda con: build_series(con)),
             ("membership", lambda con: build_membership(con, out)),
             ("fno", lambda con: build_fno(con)),
             ("bhavcopy", lambda con: build_bhavcopy(con))]
    result, run_id, started = {}, f"pilot_b_{now().replace(':', '')}", now()
    con = sqlite3.connect(str(MARKET_DB))
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    create_schema(con, "market_state", MARKET_KEEP)
    create_schema(con, "equity_intelligence", BHAVCOPY_KEEP)
    for name, fn in steps:
        if only and name not in only:
            continue
        t0 = time.monotonic()
        try:
            result[name] = fn(con)
        except Exception as exc:
            log(f"STEP FAILED {name}: {type(exc).__name__}: {exc}")
            result[name] = {"error": f"{type(exc).__name__}: {exc}"}
        log(f"[{name}] {time.monotonic() - t0:.1f}s")
    counts = {}
    for table in ("index_list", "company_membership_pit", "series_meta", "series_observation",
                  "commodity_price_daily", "fno_oi_daily", "mkt_nse_full_daily"):
        try:
            counts[table] = build_t1.table_count(con, table)
        except sqlite3.OperationalError as exc:
            counts[table] = f"MISSING ({exc})"
    build_t1.clear(con, "build_run")
    build_t1.insert_rows(con, "build_run",
                         ["run_id", "started_at", "ended_at", "doc_type", "docs_in", "docs_ok",
                          "docs_failed", "chunks_out", "tags_out", "notes"],
                         [(run_id, started, now(), "pilot_b", len(result),
                           sum(1 for v in result.values() if isinstance(v, dict)
                               and "error" not in v), 0, 0, 0,
                           json.dumps(counts, sort_keys=True))])
    result["counts"], result["started_at"], result["ended_at"] = counts, started, now()
    con.close()
    (out / "build_result.json").write_text(json.dumps(result, indent=1, default=str),
                                           encoding="utf-8")
    log("counts: " + json.dumps(counts, sort_keys=True))
    return result


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", default="", help="comma list of series,membership,fno,bhavcopy")
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--verify", action="store_true",
                    help="do not build: print table checks and reclassify the cases")
    a = ap.parse_args(argv)
    out = Path(a.out)
    if a.verify:
        from reality_engine.pilot.checks_b import main as checks_main
        return checks_main(out)
    result = build(out, {s for s in a.only.split(",") if s} or None)
    return 1 if any(isinstance(v, dict) and "error" in v for v in result.values()) else 0


if __name__ == "__main__":
    raise SystemExit(main())
