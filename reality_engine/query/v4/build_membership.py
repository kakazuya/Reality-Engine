"""Build the v4 fact table and the entity-set ``membership`` table from the pilot stores.

Two artifacts, one build (QUERY_V4_DESIGN §B.1, §B.2, §H.2):

* ``fact_view.sql`` applies the long-format ``fact`` table - one row per
  (entity, atom, dims, period) for every held atom the pilot carries.
* ``membership`` is rebuilt from ``market_state.company_membership_pit``: index
  membership with factual windows, ``known_at`` and ``pit_known``.

Point in time, never backcast: a window a dated NSE notice bounds keeps its
start and ``pit_known=1``; a ``snapshot_backcast`` window keeps only the part the
data attests (the snapshot date for an open stint, the day before a known
exclusion for a closed one), carries ``known_at`` = the first date it is knowable
and ``pit_known=0``.  Sector rows are left to the §B.6 PIT sector build; the
held ``sector_pit.db`` is the 2019 backcast and is not reused.

Pilot only: reads ``pilot/pilot60/*.db`` read-only (``immutable=1``) and writes one
build DB.  Usage::

    python -m reality_engine.query.v4.build_membership --out .tmp/fact_v4_pilot.db
"""
from __future__ import annotations

import argparse
import csv
import os
import sqlite3
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
DEFAULT_ROOT = Path(os.environ.get("REALITY_DATA_ROOT") or REPO / "reality_engine" / "data")
PILOT_DIR = Path("pilot") / "pilot60"
UNIVERSE_CSV = REPO / "tasks" / "pilot60" / "UNIVERSE.csv"
SQL_FILE = Path(__file__).with_name("fact_view.sql")
HOLDINGS_SQL = Path(__file__).with_name("fact_view_holdings_isin.sql")
#: the held identity store: shp_index filings + the symbol -> ISIN history that maps a
#: pre-split shareholding ISIN back to the pilot ISIN (fact_view_holdings_isin.sql).
IDENTITY_DB = "equity_intelligence.db"

#: attach alias -> pilot file (the aliases fact_view.sql reads)
STORES = {
    "market_state": "market_state_pilot.db",
    "facts_pilot": "facts_pilot.db",
    "market_state_b": "market_state_b.db",
    "metric_state": "extract_pilot60.db",
    "chunks_v3": "chunks_v3_pilot.db",
}

#: The 43 held atoms of tasks/arch_v4/concept_registry.json (coverage == "held").
HELD_ATOMS = [
    "price.close", "price.open", "price.high", "price.low", "price.volume",
    "price.delivery_qty", "price.delivery_pct", "price.traded_value", "price.mcap",
    "price.shares_out", "price.band", "price.rsi", "price.sma",
    "fin.revenue", "fin.ebitda", "fin.pat", "fin.eps", "fin.book_equity",
    "fin.total_debt", "fin.cash", "fin.receivables", "fin.inventory", "fin.payables",
    "fin.capex", "fin.interest_expense", "fin.capacity_utilisation", "fin.order_book",
    "fin.order_intake", "fin.segment_value",
    "hold.pct", "hold.pledge_pct", "hold.fpi_limit_utilised", "flows.net_inr",
    "claim.claim", "text.passage",
    "macro.policy", "macro.claim", "macro.commodity_close", "macro.index_close",
    "macro.flow", "macro.oi", "macro.etf_premium", "macro.series",
]

#: Held atoms the pilot holds no source for, with the reason.  Each is a ticket, not
#: a silent gap: the full-scale store does have the column; the pilot build does not.
NOT_BUILT = {
    "price.rsi": "pilot price panel (company_state_daily) has no rsi_14 column; the live "
                 "daily_price_delivery does - the full build reads it",
    "price.sma": "pilot price panel has no sma_20 column (same as rsi); a computed SMA "
                 "would be a formula, not the stored atom (§A.3)",
    "fin.capex": "company_metric_series holds no 'capex' key in this build; extract60's "
                 "capex_project rows are project announcements, not the period capex line",
    "hold.fpi_limit_utilised": "company_ownership_pit has no fpi_limit_utilised_pct column",
    "claim.claim": "no claim table in the pilot; built by the WP2b worker (build_claim.py)",
    "macro.policy": "no policy_events table in the pilot; the live equity_intelligence.db "
                    "carries it and the full build reads it",
    "macro.claim": "macro_pilot.db (pilot/macro_claims.py) is not in this data root",
    "macro.index_close": "no mkt_nse_index_daily table in the pilot (index_list is "
                         "membership metadata, not a level series)",
    "macro.flow": "no mkt_fii_dii_cash table in the pilot",
    "macro.etf_premium": "no etf_inav table in the pilot",
}
#: atoms whose branch exists but legitimately returns no pilot row
EMPTY_OK = {"hold.pledge_pct", "flows.net_inr"}

BUILT = [atom for atom in HELD_ATOMS if atom not in NOT_BUILT]


# --------------------------------------------------------------------------- build
def _uri(path: Path) -> str:
    return "file:" + path.resolve().as_posix() + "?mode=ro&immutable=1"


def attach(con: sqlite3.Connection, root: Path | str | None = None) -> Path:
    """Attach the five pilot stores under the aliases ``fact_view.sql`` reads."""
    pilot = Path(root or DEFAULT_ROOT) / PILOT_DIR
    missing = [name for name in STORES.values() if not (pilot / name).is_file()]
    if missing:
        raise FileNotFoundError(f"pilot store(s) missing under {pilot}: {missing}")
    for alias, name in STORES.items():
        con.execute(f"ATTACH DATABASE ? AS {alias}", (_uri(pilot / name),))
    return pilot


def read_universe(csv_path: Path | str | None = None) -> list[tuple[str, str]]:
    """(isin, symbol) for the pilot-60 universe; a blank symbol is kept as ''."""
    rows = []
    with Path(csv_path or UNIVERSE_CSV).open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            isin = (row.get("isin") or "").strip()
            if isin.startswith("INE") and len(isin) == 12:
                rows.append((isin, (row.get("symbol") or "").strip()))
    if not rows:
        raise ValueError(f"no ISINs read from {csv_path or UNIVERSE_CSV}")
    return rows


def seed_universe(con: sqlite3.Connection, rows: list[tuple[str, str]]) -> int:
    con.execute("DROP TABLE IF EXISTS pilot_universe")
    con.execute("CREATE TABLE pilot_universe(isin TEXT PRIMARY KEY, symbol TEXT NOT NULL)")
    con.executemany("INSERT OR REPLACE INTO pilot_universe(isin, symbol) VALUES (?, ?)", rows)
    con.execute("CREATE INDEX ix_pilot_universe_symbol ON pilot_universe(symbol)")
    return len(rows)


def attach_identity(con: sqlite3.Connection, root: Path | str | None = None) -> bool:
    """Attach the held identity store read-only; False when this root does not have it."""
    path = Path(root or DEFAULT_ROOT) / IDENTITY_DB
    if not path.is_file():
        return False
    con.execute("ATTACH DATABASE ? AS equity_intelligence", (_uri(path),))
    return True


def build_holdings_isin(con: sqlite3.Connection) -> int:
    """Copy the shareholding filings whose ISIN predates the pilot ISIN (see the SQL)."""
    con.executescript(HOLDINGS_SQL.read_text(encoding="utf-8"))
    return con.execute(
        "SELECT COUNT(*) FROM fact WHERE atom = 'hold.pct' "
        "AND source_ref LIKE 'equity_intelligence.shp_index%'").fetchone()[0]


def build_fact(con: sqlite3.Connection, sql_path: Path | str | None = None) -> int:
    con.executescript(Path(sql_path or SQL_FILE).read_text(encoding="utf-8"))
    return con.execute("SELECT COUNT(*) FROM fact").fetchone()[0]


MEMBERSHIP_DDL = """
DROP TABLE IF EXISTS membership;
CREATE TABLE membership(
    entity_id  TEXT NOT NULL,
    set_kind   TEXT NOT NULL,          -- index | sector | ... (§B.2)
    set_value  TEXT NOT NULL,
    valid_from TEXT NOT NULL,
    valid_to   TEXT,                   -- half-open [valid_from, valid_to); NULL = open
    weight     REAL,
    source     TEXT,
    known_at   TEXT NOT NULL,
    pit_known  INTEGER NOT NULL,       -- 1 = window a dated notice bounds; 0 = see docstring
    PRIMARY KEY (set_kind, set_value, entity_id, valid_from)
) WITHOUT ROWID;
"""

#: `snapshot_backcast` windows: the start is not evidenced, so keep only the attested
#: part (open stint -> snapshot date; closed stint -> the day before the exclusion)
#: and stamp known_at with the first date the row is knowable.  Never backcast.
MEMBERSHIP_INSERT = """
INSERT OR REPLACE INTO membership
    (entity_id, set_kind, set_value, valid_from, valid_to, weight, source, known_at, pit_known)
SELECT m.isin, 'index', m.index_code,
       CASE WHEN m.source = 'snapshot_backcast'
            THEN CASE WHEN m.removed_on IS NOT NULL THEN date(m.removed_on, '-1 day')
                      ELSE COALESCE(i.snapshot_date, m.added_on) END
            ELSE m.added_on END,
       m.removed_on,
       NULL,
       m.source,
       CASE WHEN m.source = 'snapshot_backcast'
            THEN COALESCE(m.removed_on, i.snapshot_date, m.added_on)
            ELSE m.added_on END || 'T23:59:59',
       CASE WHEN m.source = 'snapshot_backcast' THEN 0 ELSE 1 END
FROM market_state.company_membership_pit m
LEFT JOIN market_state.index_list i ON i.index_code = m.index_code
WHERE m.added_on IS NOT NULL
  AND (m.removed_on IS NULL OR m.removed_on > m.added_on);
"""


def build_membership(con: sqlite3.Connection) -> dict:
    """Rebuild ``membership`` from the held PIT membership rows (index sets only)."""
    con.executescript(MEMBERSHIP_DDL)
    con.execute(MEMBERSHIP_INSERT)
    con.execute("CREATE INDEX ix_membership_set_window "
                "ON membership(set_kind, set_value, valid_from, valid_to)")
    row = con.execute(
        "SELECT COUNT(*), COUNT(DISTINCT entity_id), COUNT(DISTINCT set_value), "
        "SUM(pit_known = 0) FROM membership WHERE set_kind = 'index'").fetchone()
    held = con.execute("SELECT COUNT(*) FROM market_state.company_membership_pit").fetchone()[0]
    sectors = con.execute(
        "SELECT COUNT(*) FROM membership WHERE set_kind = 'sector'").fetchone()[0]
    return {"rows": row[0], "source_rows": held, "entities": row[1], "index_sets": row[2],
            "pit_known_0": row[3] or 0, "sector_rows": sectors}


def build(out: Path | str, root: Path | str | None = None,
          universe_csv: Path | str | None = None) -> Path:
    """Build one DB with ``fact`` + ``membership`` from the pilot stores."""
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    for stale in (out, Path(str(out) + "-journal"), Path(str(out) + "-wal"),
                  Path(str(out) + "-shm")):
        if stale.exists():
            stale.unlink()
    con = sqlite3.connect(str(out), uri=True)
    try:
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA journal_mode=OFF")
        con.execute("PRAGMA synchronous=OFF")
        attach(con, root)
        seed_universe(con, read_universe(universe_csv))
        build_fact(con)
        if attach_identity(con, root):
            build_holdings_isin(con)
        build_membership(con)
        con.commit()
    finally:
        con.close()
    return out


def apply_holdings(out: Path | str, root: Path | str | None = None,
                   universe_csv: Path | str | None = None) -> int:
    """Install the holdings-ISIN step on an existing fact DB (the reviewer's path).

    Additive: only rows whose key is absent are inserted, so every atom the installed
    build already carries stays untouched.  Usage::

        python -m reality_engine.query.v4.build_membership \
            --holdings-only --out .tmp/fact_v4_pilot.db
    """
    out = Path(out)
    if not out.is_file():
        raise FileNotFoundError(f"{out} does not exist")
    con = sqlite3.connect(str(out), uri=True)
    con.row_factory = sqlite3.Row
    try:
        if not attach_identity(con, root):
            raise FileNotFoundError(f"{IDENTITY_DB} missing under {Path(root or DEFAULT_ROOT)}")
        seed_universe(con, read_universe(universe_csv))
        rows = build_holdings_isin(con)
        con.commit()
        return rows
    finally:
        con.close()


# ----------------------------------------------------------------------- coverage
def coverage(con: sqlite3.Connection) -> dict:
    """Per-atom row/entity counts, the unbuilt atoms, and the membership numbers."""
    facts = {r[0]: (r[1], r[2]) for r in con.execute(
        "SELECT atom, COUNT(*), COUNT(DISTINCT entity_id) FROM fact GROUP BY atom")}
    mem = con.execute(
        "SELECT COUNT(*), COUNT(DISTINCT entity_id), COUNT(DISTINCT set_value), "
        "SUM(pit_known = 0) FROM membership WHERE set_kind = 'index'").fetchone()
    sector = con.execute("SELECT COUNT(*) FROM membership WHERE set_kind = 'sector'").fetchone()
    try:
        source_rows = con.execute(
            "SELECT COUNT(*) FROM market_state.company_membership_pit").fetchone()[0]
    except sqlite3.Error:                       # coverage on a build DB without attaches
        source_rows = None
    return {
        "facts": {atom: {"rows": n, "entities": e} for atom, (n, e) in sorted(facts.items())},
        "missing": [a for a in BUILT if a not in facts],
        "not_built": dict(NOT_BUILT),
        "membership": {"rows": mem[0], "entities": mem[1], "index_sets": mem[2],
                       "pit_known_0": mem[3] or 0, "sector_rows": sector[0],
                       "source_rows": source_rows},
    }


# ----------------------------------------------------------------------- checks
def _dims(row: sqlite3.Row | dict) -> dict:
    out = {}
    for part in (row["dims"] or "").split(";"):
        if "=" in part:
            key, val = part.split("=", 1)
            out[key] = val
    return out


_HOLDER_COL = {"promoter": "promoter_pct", "fii": "fii_pct", "dii": "dii_pct",
               "mf": "mf_pct", "public": "public_pct"}
_BHAV_COL = {"price.open": "open", "price.high": "high", "price.low": "low",
             "price.volume": "volume", "price.delivery_qty": "deliverable_qty",
             "price.delivery_pct": "delivery_pct", "price.traded_value": "turnover_lacs"}


def _source_value(con: sqlite3.Connection, row: sqlite3.Row) -> tuple | None:
    """(value, known_at) re-read from the source table, for the hand check."""
    atom, isin, end = row["atom"], row["entity_id"], row["period_end"]
    d = _dims(row)
    if atom == "price.close":
        return con.execute("SELECT close, known_at FROM market_state.company_state_daily "
                           "WHERE isin=? AND date=?", (isin, end)).fetchone()
    if atom == "price.mcap":
        return con.execute("SELECT mcap_cr, known_at FROM market_state.company_state_daily "
                           "WHERE isin=? AND date=?", (isin, end)).fetchone()
    if atom == "price.shares_out":
        return con.execute("SELECT shares_out, known_at FROM market_state.company_state_daily "
                           "WHERE isin=? AND date=?", (isin, end)).fetchone()
    if atom in _BHAV_COL:
        col = _BHAV_COL[atom]
        return con.execute(
            f"SELECT b.{col}, b.date || 'T23:59:59' FROM market_state_b.mkt_nse_full_daily b "
            "JOIN pilot_universe u ON u.symbol = b.symbol WHERE u.isin=? AND b.date=?",
            (isin, end)).fetchone()
    if atom == "price.band":
        return con.execute("SELECT band, date || 'T23:59:59' FROM market_state.price_band_daily "
                           "WHERE isin=? AND date=?", (isin, end)).fetchone()
    if atom in ("fin.revenue", "fin.pat", "fin.eps", "fin.book_equity", "fin.cash",
                "fin.receivables", "fin.inventory", "fin.payables", "fin.interest_expense"):
        key = {"fin.book_equity": "net_worth", "fin.interest_expense": "finance_costs"}.get(
            atom, atom.split(".", 1)[1])
        return con.execute(
            "SELECT value, known_at FROM facts_pilot.company_metric_series WHERE isin=? "
            "AND metric_key=? AND period_end=? AND COALESCE(basis,'')=? "
            "AND COALESCE(period_kind,'')=?",
            (isin, key, end, d.get("basis", ""), d.get("period_kind", ""))).fetchone()
    if atom in ("fin.ebitda", "fin.total_debt"):
        keys = (("pbt", "finance_costs", "depreciation") if atom == "fin.ebitda"
                else ("borrowings_current", "borrowings_noncurrent"))
        got = con.execute(
            "SELECT COUNT(DISTINCT metric_key), SUM(value), MAX(known_at) "
            "FROM facts_pilot.company_metric_series WHERE isin=? AND period_end=? "
            "AND COALESCE(basis,'')=? AND COALESCE(period_kind,'')=? "
            f"AND metric_key IN ({','.join('?' * len(keys))}) AND value IS NOT NULL",
            (isin, end, d.get("basis", ""), d.get("period_kind", ""), *keys)).fetchone()
        return (None, None) if got[0] != len(keys) else (got[1], got[2])
    if atom == "fin.segment_value":
        return con.execute(
            "SELECT value_cr, known_at FROM facts_pilot.company_segment_pnl WHERE isin=? "
            "AND period_end=? AND COALESCE(segment,'')=? AND COALESCE(metric,'')=? "
            "AND COALESCE(basis,'')=?",
            (isin, end, d.get("segment", ""), d.get("metric", ""), d.get("basis", ""))).fetchone()
    if atom == "fin.capacity_utilisation":
        return con.execute(
            "SELECT utilisation_pct, known_at FROM metric_state.company_capacity_utilisation "
            "WHERE isin=? AND period_end=? AND COALESCE(product,'')=? "
            "ORDER BY known_at DESC LIMIT 1",
            (isin, end, d.get("product", ""))).fetchone()
    if atom in ("fin.order_book", "fin.order_intake"):
        col = "order_book_cr" if atom == "fin.order_book" else "intake_cr"
        return con.execute(f"SELECT {col}, known_at FROM metric_state.order_intake "
                           "WHERE isin=? AND period_end=?", (isin, end)).fetchone()
    if atom == "hold.pct":
        col = _HOLDER_COL[d.get("holder_class", "")]
        got = con.execute(f"SELECT {col}, known_at FROM market_state.company_ownership_pit "
                          "WHERE isin=? AND quarter_end=?", (isin, end)).fetchone()
        if got is None or got[0] is None:
            # a pre-split ISIN: re-read the filing through the symbol -> ISIN history
            try:
                got = con.execute(
                    f"SELECT s.{col}, COALESCE(s.broadcast_at, s.submission_date) "
                    "FROM equity_intelligence.shp_index s "
                    "JOIN equity_intelligence.symbol_isin_history h "
                    "ON h.exchange = 'NSE' AND upper(h.symbol) = upper(s.symbol) "
                    "JOIN pilot_universe u ON u.isin = h.isin "
                    "WHERE u.isin = ? AND s.quarter_end = ? "
                    "ORDER BY COALESCE(s.broadcast_at, s.submission_date) DESC LIMIT 1",
                    (isin, end)).fetchone()
            except sqlite3.OperationalError:      # identity store not attached (fixture)
                pass
        return got
    if atom == "hold.pledge_pct":
        return con.execute("SELECT pledge_pct, known_at FROM market_state.company_ownership_pit "
                           "WHERE isin=? AND quarter_end=?", (isin, end)).fetchone()
    if atom == "flows.net_inr":
        return con.execute("SELECT insider_net_inr, known_at FROM market_state.event_leakage_window "
                           "WHERE isin=? AND date=? AND offset=?", (isin, end, 0)).fetchone()
    if atom == "text.passage":
        return con.execute("SELECT body, known_at FROM chunks_v3.chunk WHERE chunk_id=?",
                           (d.get("chunk"),)).fetchone()
    if atom == "macro.commodity_close":
        return con.execute("SELECT close, known_at FROM market_state_b.commodity_price_daily "
                           "WHERE series_code=? AND date=?", (isin, end)).fetchone()
    if atom == "macro.series":
        return con.execute("SELECT value, known_at FROM market_state_b.series_observation "
                           "WHERE series_code=? AND period_start=?", (isin, end)).fetchone()
    if atom == "macro.oi":
        return con.execute(
            "SELECT oi, date || 'T23:59:59' FROM market_state_b.fno_oi_daily WHERE isin=? "
            "AND date=? AND expiry=? AND strike=? AND option_type=?",
            (isin, end, d.get("expiry", ""), float(d.get("strike") or 0),
             d.get("option_type", ""))).fetchone()
    return None          # a source this checker does not read (another builder's atom)


def _same(a, b) -> bool:
    if a is None or b is None:
        return a == b
    if isinstance(a, str) or isinstance(b, str):
        return str(a) == str(b)
    return abs(float(a) - float(b)) <= 1e-9 * max(1.0, abs(float(b)))


def handcheck(con: sqlite3.Connection, per_atom: int = 1) -> list[dict]:
    """Re-read one row of every atom from its source table and compare.

    Deterministic (the first entity of each atom, then the first row of that entity),
    so a re-run prints the same rows.  A row is OK only when both value and known_at
    match the source exactly.  Every probe is a primary-key seek, never an atom scan:
    the pilot's ``macro.oi`` alone is 6.9 M rows.
    """
    out = []
    atoms = [r[0] for r in con.execute("SELECT DISTINCT atom FROM fact ORDER BY atom")]
    for atom in atoms:
        entities = []
        for row in con.execute("SELECT entity_id FROM fact WHERE atom=? LIMIT 1", (atom,)):
            entities.append(row[0])
        if per_atom > 1 and entities:
            for row in con.execute("SELECT entity_id FROM fact WHERE atom=? AND entity_id<>? "
                                   "LIMIT ?", (atom, entities[0], per_atom - 1)):
                entities.append(row[0])
        for entity in entities:
            row = con.execute("SELECT * FROM fact WHERE entity_id=? AND atom=? LIMIT 1",
                              (entity, atom)).fetchone()
            if row is None:
                continue
            src = _source_value(con, row)
            if src is None:
                # a row another builder wrote (a derived quarter, a flow table this
                # checker does not read): report it unchecked rather than crash
                out.append({"atom": atom, "entity": row["entity_id"], "period": row["period_end"],
                            "value": row["value"], "unit": row["unit"],
                            "known_at": row["known_at"], "source_ref": row["source_ref"],
                            "source_value": None, "source_known_at": None, "ok": None})
                continue
            src_value, src_known = src
            out.append({"atom": atom, "entity": row["entity_id"], "period": row["period_end"],
                        "value": row["value"], "unit": row["unit"],
                        "known_at": row["known_at"], "source_ref": row["source_ref"],
                        "source_value": src_value, "source_known_at": src_known,
                        "ok": _same(row["value"], src_value) and row["known_at"] == src_known})
    return out


def bench(con: sqlite3.Connection, n: int = 200) -> dict:
    """Time ``value_at``-shaped lookups (entity + atom + as_of + known_at<=as_of).

    One entity per atom, its latest periods; every query is a primary-key seek.
    """
    atoms = [r[0] for r in con.execute("SELECT DISTINCT atom FROM fact ORDER BY atom")]
    per = max(1, n // max(1, len(atoms)))
    sql = ("SELECT value, unit, period_end, known_at FROM fact WHERE entity_id=? AND atom=? "
           "AND period_end<=? AND known_at<=? ORDER BY period_end DESC LIMIT 1")
    times = []
    for atom in atoms:
        found = con.execute("SELECT entity_id FROM fact WHERE atom=? LIMIT 1", (atom,)).fetchone()
        if not found:
            continue
        entity = found[0]
        periods = [r[0] for r in con.execute(
            "SELECT DISTINCT period_end FROM fact WHERE entity_id=? AND atom=? "
            "ORDER BY period_end DESC LIMIT ?", (entity, atom, per))]
        for period in periods:
            # ask as of the end of that period's own day, the usual answer date
            params = (entity, atom, period, period + "T23:59:59")
            con.execute(sql, params).fetchall()                 # warm
            t0 = time.perf_counter()
            con.execute(sql, params).fetchall()
            times.append((time.perf_counter() - t0) * 1000.0)
    times.sort()
    median = times[len(times) // 2] if times else 0.0
    p90 = times[int(len(times) * 0.9)] if times else 0.0
    return {"n": len(times), "median_ms": median, "p90_ms": p90}


# ------------------------------------------------------------------------- main
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Build the v4 fact + membership pilot DB")
    ap.add_argument("--out", default=str(REPO / ".tmp" / "fact_v4_pilot.db"))
    ap.add_argument("--root", default=None, help="data root (default REALITY_DATA_ROOT)")
    ap.add_argument("--universe", default=None, help="pilot universe CSV")
    ap.add_argument("--bench-n", type=int, default=200)
    ap.add_argument("--report", action="store_true",
                    help="report/check the existing --out instead of rebuilding it")
    ap.add_argument("--holdings-only", action="store_true",
                    help="apply the holdings-ISIN step to the existing --out DB and exit")
    args = ap.parse_args(argv)

    if args.holdings_only:
        rows = apply_holdings(args.out, args.root, args.universe)
        print(f"holdings step: {rows:,} rows carry the shp_index#symbol_isin_history source")
        return 0
    if args.report:
        out, elapsed = Path(args.out), None
        if not out.is_file():
            print(f"{out} does not exist; drop --report to build it", file=sys.stderr)
            return 2
    else:
        t0 = time.perf_counter()
        out = build(args.out, args.root, args.universe)
        elapsed = time.perf_counter() - t0
    con = sqlite3.connect(str(out), uri=True)
    con.row_factory = sqlite3.Row
    try:
        attach(con, args.root)
        seed_universe(con, read_universe(args.universe))
        attach_identity(con, args.root)
        cov = coverage(con)
        built = f" in {elapsed:.1f}s" if elapsed is not None else ""
        print(f"{out}{built}  ({out.stat().st_size / 1e6:.0f} MB)")
        print(f"\nfacts: {sum(v['rows'] for v in cov['facts'].values()):,} rows, "
              f"{len(cov['facts'])} atoms")
        for atom, v in cov["facts"].items():
            print(f"  {atom:<26} {v['rows']:>9,} rows  {v['entities']:>5} entities")
        for atom, why in cov["not_built"].items():
            print(f"  {atom:<26} NOT BUILT: {why}")
        empty = [a for a in BUILT if a not in cov["facts"]]
        if empty:
            print(f"  branches with no pilot row: {empty}")
        m = cov["membership"]
        print(f"\nmembership: {m['rows']:,} index rows (source {m['source_rows']:,}), "
              f"{m['entities']:,} ISINs, {m['index_sets']} index sets, "
              f"pit_known=0 on {m['pit_known_0']:,}, sector rows {m['sector_rows']}")
        rows = handcheck(con)
        bad = [r for r in rows if r["ok"] is False]
        checked = sum(1 for r in rows if r["ok"])
        print(f"\nhand check: {checked}/{sum(1 for r in rows if r['ok'] is not None)} rows match "
              f"their source ({len(rows) - checked - len(bad)} unchecked)")
        for r in rows:
            mark = "ok " if r["ok"] else ("BAD" if r["ok"] is False else "n/a")
            print(f"  {mark} {r['atom']:<24} {r['entity']} {r['period']} "
                  f"value={r['value']!r} known_at={r['known_at']}")
        timing = bench(con, args.bench_n)
        print(f"\nlookup: n={timing['n']} median {timing['median_ms']:.2f} ms, "
              f"p90 {timing['p90_ms']:.2f} ms")
        return 0 if not bad else 1
    finally:
        con.close()


if __name__ == "__main__":
    sys.exit(main())
