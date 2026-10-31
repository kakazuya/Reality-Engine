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

WP2c additions (31 Oct 2026):

* ``fact_view_extras.sql`` fills the atoms whose source is outside the five pilot
  files: true single-quarter ``fin.*`` values (``build_quarters``, replacing the
  pilot store's context-blind quarter rows), ``fin.capex``, ``macro.policy``,
  ``macro.claim``, ``macro.index_close``, ``macro.flow``, ``macro.etf_premium``,
  ``hold.fpi_limit_utilised`` and ``flows.net_inr``.
* ``price.sma`` / ``price.rsi`` are computed here from the pilot close panel with
  trailing windows only (no look-ahead), matching the live ``sma_20`` / ``rsi_14``
  definitions in ``technical_engine``.
* Blank or renamed pilot symbols are resolved from ``security_master`` before the
  bhavcopy join, so the 11 names the universe CSV/prices leave without a symbol (9
  blank, 2 renamed) get their price atoms; the one BSE-only name is filled from the
  BSE bhavcopy.
* ``macro.oi`` (16.2 M rows, ~2 GB) is written to the separate side file
  ``fact_oi.sql`` -> ``<out>_oi.db``; the core store carries every other atom.
* ``atom_status`` stores one row per held atom (43): status, rows, ISIN coverage.

Pilot only: reads ``pilot/pilot60/*.db`` read-only (``immutable=1``) plus the held
``results_xbrl.db`` / ``equity_intelligence.db`` / ``pilot/macro_all.db`` slices the
brief names, and writes one build DB (plus the OI side file).  Usage::

    python -m reality_engine.query.v4.build_membership --out .tmp/fact_v4_pilot.db

``build_quarters`` is run automatically when ``--quarters`` is missing.
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
EXTRAS_FILE = Path(__file__).with_name("fact_view_extras.sql")
OI_FILE = Path(__file__).with_name("fact_oi.sql")
HOLDINGS_SQL = Path(__file__).with_name("fact_view_holdings_isin.sql")
#: the held identity store: shp_index filings + the symbol -> ISIN history that maps a
#: pre-split shareholding ISIN back to the pilot ISIN (fact_view_holdings_isin.sql).
IDENTITY_DB = "equity_intelligence.db"
#: the parsed shareholding XBRL store, beside the fact DB (scripts/fetch_shp_xbrl_pilot.py).
SHP_XBRL_DB = "shp_xbrl_pilot.db"

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

#: Held atoms this build cannot fill, with the exact source a fetch/parse needs.
#: A ticket, not a silent gap.  Everything else in HELD_ATOMS is built.
NOT_BUILT = {
    "claim.claim": "no claim table in the pilot; built by the WP2b worker (build_claim.py)",
}
#: atoms whose branch exists but legitimately returns no pilot row (documented)
EMPTY_OK = {"hold.pledge_pct", "hold.fpi_limit_utilised", "fin.segment_value"}

BUILT = [atom for atom in HELD_ATOMS if atom not in NOT_BUILT]

#: atoms served from the attached OI side file, not the core store
SIDE_ATOMS = {"macro.oi"}

#: why an atom is thin/empty, printed next to its row count
ATOM_NOTES = {
    "hold.pct": "promoter and public only: dii_pct / fii_pct / mf_pct are NULL in all "
                "49,126 pilot ownership rows; ticket: download+parse the pilot SHP XBRL",
    "hold.pledge_pct": "pledge_pct is NULL in all 49,126 pilot ownership rows; only 40 "
                       "shareholding XBRL files are parsed market-wide (0 pilot ISINs). "
                       "Ticket: fetch+parse the pilot names' SHP XBRL (shp_index lists them)",
    "hold.fpi_limit_utilised": "equity_intelligence.shareholding.fpi_limit_utilised_pct is "
                               "parsed for 40 files market-wide and 0 of the 60 pilot ISINs; "
                               "ticket: same SHP parse as pledge_pct",
    "fin.receivables": "22 rows over 3 pilot ISINs: the held XBRL carries only 14 "
                       "TradeReceivables facts for these names (most filers use another "
                       "taxonomy line); ticket: AR balance-sheet lines",
    "fin.capacity_utilisation": "4 rows over 4 pilot ISINs: extract60 holds 70 capacity "
                                "rows but only these 4 carry a utilisation_pct",
    "fin.segment_value": "extract60 company_segment_pnl carries no pilot ISIN row",
    "macro.policy": "not ISIN-keyed: entity is the policy; only events with an amount are rows",
    "macro.claim": "not ISIN-keyed: entity is the claim id",
    "macro.index_close": "not ISIN-keyed: entity is the index name",
    "macro.flow": "not ISIN-keyed: one entity (fii_dii_cash), measure is a dim",
    "macro.etf_premium": "market-wide ETF panel; the 60-company pilot holds no ETF",
    "macro.oi": "served from the attached side file (fact_oi.sql), not the core store",
    "price.rsi": "computed from the pilot close panel (trailing 14 periods, no look-ahead)",
    "price.sma": "computed from the pilot close panel (trailing 20 closes, no look-ahead)",
    "price.band": "59 ISINs: INE374E01021 (BSE-only) has no NSE band row in the pilot",
    "flows.net_inr": "insider net INR per ISIN/day (ei.insider_trades_v2); the pilot "
                     "event_leakage_window is empty",
}


# --------------------------------------------------------------------------- build
def _uri(path: Path) -> str:
    return "file:" + path.resolve().as_posix() + "?mode=ro&immutable=1"


def attached(con: sqlite3.Connection) -> set[str]:
    """Aliases of the databases currently attached to ``con``."""
    return {row[1] for row in con.execute("PRAGMA database_list")}


def attach(con: sqlite3.Connection, root: Path | str | None = None,
           quarters: Path | str | None = None, ei: Path | str | None = None,
           macro: Path | str | None = None) -> dict:
    """Attach the five pilot stores plus whichever extra stores exist.

    ``quarters`` (build_quarters), ``ei`` (equity_intelligence) and ``macro``
    (pilot/macro_all.db) are attached when their file exists; ``extras`` in the
    returned dict is True only when all three are attached (fact_view_extras.sql
    reads all three and is skipped otherwise, which is how the fixture tests run).
    """
    root = Path(root or DEFAULT_ROOT)
    pilot = root / PILOT_DIR
    missing = [name for name in STORES.values() if not (pilot / name).is_file()]
    if missing:
        raise FileNotFoundError(f"pilot store(s) missing under {pilot}: {missing}")
    for alias, name in STORES.items():
        con.execute(f"ATTACH DATABASE ? AS {alias}", (_uri(pilot / name),))
    paths = {"pilot": pilot, "quarters": None, "ei": None, "macro": None}
    for alias, path in (("quarters", quarters), ("ei", ei), ("macro", macro)):
        if path is None:
            continue
        path = Path(path)
        if path.is_file():
            con.execute(f"ATTACH DATABASE ? AS {alias}", (_uri(path),))
            paths[alias] = path
    paths["extras"] = all(paths[k] is not None for k in ("quarters", "ei", "macro"))
    return paths


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
    """Seed ``pilot_universe``; resolve a blank or renamed CSV symbol from the registry.

    11 pilot names carry no NSE bhavcopy row: 9 leave the CSV symbol blank and 2 carry
    a symbol the exchange no longer uses (AGVENTURES is OCCL, BMW has no NSE line at
    all).  ``security_master`` resolves 10 of the 11 by ISIN, before any branch reads
    the symbol-keyed bhavcopy, so those price atoms fill.  BMW stays as it is and its
    price atoms are served from the BSE bhavcopy by ``fact_view_extras.sql``.
    """
    con.execute("DROP TABLE IF EXISTS pilot_universe")
    con.execute("CREATE TABLE pilot_universe(isin TEXT PRIMARY KEY, symbol TEXT NOT NULL)")
    con.executemany("INSERT OR REPLACE INTO pilot_universe(isin, symbol) VALUES (?, ?)", rows)
    if "ei" in attached(con):
        resolve = ("UPDATE pilot_universe SET symbol = COALESCE(NULLIF(("
                   "  SELECT sm.nse_symbol FROM ei.security_master sm "
                   "  WHERE sm.isin = pilot_universe.isin), ''), symbol) WHERE ")
        for cond in ("symbol = ''",
                     # renamed since the CSV was cut: the old symbol has no bhavcopy row
                     "NOT EXISTS (SELECT 1 FROM market_state_b.mkt_nse_full_daily b "
                     "WHERE b.symbol = pilot_universe.symbol)"):
            try:
                con.execute(resolve + cond)
            except sqlite3.Error:             # fixture EI without the table / no bhavcopy
                pass
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


def build_fact(con: sqlite3.Connection, extras: bool = False,
               sql_path: Path | str | None = None,
               extras_path: Path | str | None = None) -> int:
    con.executescript(Path(sql_path or SQL_FILE).read_text(encoding="utf-8"))
    if extras:
        con.executescript(Path(extras_path or EXTRAS_FILE).read_text(encoding="utf-8"))
    return con.execute("SELECT COUNT(*) FROM fact").fetchone()[0]


# ------------------------------------------------------------------ price indicators
RSI_PERIOD = 14
SMA_WINDOW = 20


def _ewm_mean(values: list[float], com: int) -> list[float | None]:
    """pandas ``ewm(com=com, adjust=True, min_periods=com+1).mean()`` semantics."""
    alpha = 1.0 / (1.0 + com)
    beta = 1.0 - alpha
    num = den = 0.0
    out: list[float | None] = []
    for i, value in enumerate(values):
        num = value + beta * num
        den = 1.0 + beta * den
        out.append(num / den if i >= com else None)
    return out


def price_series(closes: list[float]) -> tuple[list[float | None], list[float | None]]:
    """(sma_20, rsi_14) aligned to ``closes``; None until the window is full.

    Only trailing closes enter each value, which is what makes the atoms PIT-safe.
    The RSI is the same Wilder smoothing ``technical_engine.compute_rsi`` uses (an
    EWM with alpha = 1/14); the SMA is the arithmetic mean of the last 20 closes.
    """
    sma: list[float | None] = [
        (sum(closes[i - SMA_WINDOW + 1:i + 1]) / SMA_WINDOW) if i >= SMA_WINDOW - 1 else None
        for i in range(len(closes))]
    # one delta per close after the first, so the 14th RSI needs the 15th close
    gains = [max(closes[i] - closes[i - 1], 0.0) for i in range(1, len(closes))]
    losses = [max(closes[i - 1] - closes[i], 0.0) for i in range(1, len(closes))]
    avg_gain = _ewm_mean(gains, RSI_PERIOD - 1)
    avg_loss = _ewm_mean(losses, RSI_PERIOD - 1)
    rsi: list[float | None] = [None]
    for gain, loss in zip(avg_gain, avg_loss):
        if gain is None or loss is None:
            rsi.append(None)
        elif loss == 0:
            rsi.append(100.0)
        else:
            rsi.append(100.0 - 100.0 / (1.0 + gain / loss))
    return sma, rsi


def augment_price_indicators(con: sqlite3.Connection) -> dict:
    """Insert price.sma / price.rsi from the pilot close panel (trailing windows)."""
    rows = list(con.execute(
        "SELECT s.isin, s.date, s.close, s.known_at FROM market_state.company_state_daily s "
        "JOIN pilot_universe u ON u.isin = s.isin WHERE s.close IS NOT NULL "
        "ORDER BY s.isin, s.date"))
    by_isin: dict[str, list[tuple[str, float, str]]] = {}
    for isin, date, close, known in rows:
        by_isin.setdefault(isin, []).append((date, float(close), known))
    out = []
    for isin, series in by_isin.items():
        sma, rsi = price_series([c for _d, c, _k in series])
        for (date, _close, known), s, r in zip(series, sma, rsi):
            if s is not None:
                out.append((isin, "price.sma", date, round(s, 6), "INR", known,
                            "derived:market_state.company_state_daily:close(20)"))
            if r is not None:
                out.append((isin, "price.rsi", date, round(r, 6), "%", known,
                            "derived:market_state.company_state_daily:close(14)"))
    con.executemany(
        "INSERT OR IGNORE INTO fact(entity_id, atom, dims, period_start, period_end, value, "
        "unit, known_at, source_ref) VALUES (?, ?, '', ?, ?, ?, ?, ?, ?)",
        [(isin, atom, date, date, value, unit, known, ref)
         for isin, atom, date, value, unit, known, ref in out])
    return {"price.sma": sum(1 for r in out if r[1] == "price.sma"),
            "price.rsi": sum(1 for r in out if r[1] == "price.rsi")}


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


# ------------------------------------------------------------------- atom status
ATOM_STATUS_DDL = """
DROP TABLE IF EXISTS atom_status;
CREATE TABLE atom_status(
    atom_id            TEXT PRIMARY KEY,
    status             TEXT NOT NULL,   -- filled | empty | not_built
    rows               INTEGER NOT NULL DEFAULT 0,
    entities           INTEGER NOT NULL DEFAULT 0,
    isin_entities      INTEGER NOT NULL DEFAULT 0,
    isin_coverage_pct  REAL NOT NULL DEFAULT 0.0,
    store              TEXT NOT NULL,   -- fact | oi | -
    source             TEXT,
    note               TEXT
) WITHOUT ROWID;
"""


def _fact_counts(con: sqlite3.Connection, table: str) -> dict[str, tuple[int, int, int]]:
    sql = ("SELECT atom, COUNT(*), COUNT(DISTINCT entity_id), "
           "COUNT(DISTINCT CASE WHEN length(entity_id) = 12 AND entity_id LIKE 'INE%' "
           "THEN entity_id END) FROM " + table + " GROUP BY atom")
    return {atom: (n, entities, isin_entities) for atom, n, entities, isin_entities in con.execute(sql)}


def atom_status(con: sqlite3.Connection, universe: int = 60,
                side_counts: dict | None = None) -> list[dict]:
    """One row per held atom: status, row count and ISIN coverage."""
    counts = _fact_counts(con, "fact")
    if "oi" in attached(con):
        side = _fact_counts(con, "oi.fact")
    else:
        side = side_counts or {}
    rows = []
    for atom in HELD_ATOMS:
        n, entities, isin_entities = side.get(atom) or counts.get(atom) or (0, 0, 0)
        if atom in NOT_BUILT:
            status, store = "not_built", "-"
        elif n:
            status, store = "filled", ("oi" if atom in side else "fact")
        else:
            status, store = "empty", "fact"
        rows.append({
            "atom_id": atom, "status": status, "rows": n, "entities": entities,
            "isin_entities": isin_entities,
            "isin_coverage_pct": round(100.0 * isin_entities / max(1, universe), 1),
            "store": store,
            "source": NOT_BUILT.get(atom, "") if status == "not_built" else ATOM_NOTES.get(atom, ""),
            "note": NOT_BUILT.get(atom, "") if status == "not_built" else ATOM_NOTES.get(atom, ""),
        })
    return rows


def write_atom_status(con: sqlite3.Connection, universe: int = 60,
                      side_counts: dict | None = None) -> list[dict]:
    rows = atom_status(con, universe, side_counts)
    con.executescript(ATOM_STATUS_DDL)
    con.executemany(
        "INSERT INTO atom_status (atom_id, status, rows, entities, isin_entities, "
        "isin_coverage_pct, store, source, note) VALUES (:atom_id,:status,:rows,:entities,"
        ":isin_entities,:isin_coverage_pct,:store,:source,:note)", rows)
    return rows


def _build_oi(out: Path, root: Path | str | None,
              universe_csv: Path | str | None) -> dict:
    """Write the macro.oi side file (same fact shape, one atom); return its counts."""
    out = Path(out)
    for stale in (out, Path(str(out) + "-journal"), Path(str(out) + "-wal"),
                  Path(str(out) + "-shm")):
        stale.unlink(missing_ok=True)
    con = sqlite3.connect(str(out), uri=True)
    try:
        con.execute("PRAGMA journal_mode=OFF")
        con.execute("PRAGMA synchronous=OFF")
        attach(con, root)
        seed_universe(con, read_universe(universe_csv))
        con.executescript(OI_FILE.read_text(encoding="utf-8"))
        con.commit()
        return _fact_counts(con, "fact")
    finally:
        con.close()


def build(out: Path | str, root: Path | str | None = None,
          universe_csv: Path | str | None = None, *,
          quarters: Path | str | None = None, ei: Path | str | None = None,
          macro: Path | str | None = None, oi_out: Path | str | None = None) -> Path:
    """Build the core DB (``fact`` + ``membership`` + ``atom_status``) + the OI side file."""
    out = Path(out)
    root = Path(root or DEFAULT_ROOT)
    quarters = Path(quarters) if quarters else out.parent / "quarters_pilot60.db"
    ei = Path(ei) if ei else root / "equity_intelligence.db"
    macro = Path(macro) if macro else root / "pilot" / "macro_all.db"
    oi_out = Path(oi_out) if oi_out else out.parent / (out.stem + "_oi.db")
    out.parent.mkdir(parents=True, exist_ok=True)
    for stale in (out, Path(str(out) + "-journal"), Path(str(out) + "-wal"),
                  Path(str(out) + "-shm")):
        stale.unlink(missing_ok=True)
    side = _build_oi(oi_out, root, universe_csv)     # the ~2 GB atom, own file
    con = sqlite3.connect(str(out), uri=True)
    try:
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA journal_mode=OFF")
        con.execute("PRAGMA synchronous=OFF")
        paths = attach(con, root, quarters=quarters, ei=ei, macro=macro)
        universe = read_universe(universe_csv)
        seed_universe(con, universe)
        build_fact(con, extras=paths["extras"])
        augment_price_indicators(con)
        if attach_identity(con, root):
            build_holdings_isin(con)
        if attach_shp_xbrl(con, out.parent / SHP_XBRL_DB):
            build_shp_xbrl(con)
        build_membership(con)
        write_atom_status(con, len(universe), side)
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


def attach_shp_xbrl(con: sqlite3.Connection, path: Path | str) -> bool:
    """Attach the parsed shareholding XBRL store read-only; False when it is not there."""
    path = Path(path)
    if not path.is_file():
        return False
    con.execute("ATTACH DATABASE ? AS shp_xbrl", (_uri(path),))
    return True


def build_shp_xbrl(con: sqlite3.Connection) -> int:
    """Copy FII, DII, MF, insurance and pledge rows from the attached XBRL store.

    Rerunnable: earlier copies are replaced.  Promoter and public stay with shp_index.
    """
    con.execute("DELETE FROM fact WHERE source_ref LIKE 'shp_xbrl:%'")
    con.execute(
        "INSERT INTO fact (entity_id, atom, dims, period_start, period_end, value, unit, "
        "known_at, source_ref) SELECT entity_id, atom, dims, period_start, period_end, value, "
        "unit, known_at, source_ref FROM shp_xbrl.fact")
    return con.execute("SELECT COUNT(*) FROM fact WHERE source_ref LIKE 'shp_xbrl:%'").fetchone()[0]


def apply_shp_xbrl(out: Path | str, shp_db: Path | str) -> int:
    """Install the XBRL rows on an existing fact DB and refresh those atoms' status."""
    con = sqlite3.connect(str(out), uri=True)
    con.row_factory = sqlite3.Row
    try:
        if not attach_shp_xbrl(con, shp_db):
            raise FileNotFoundError(f"{shp_db} does not exist")
        rows = build_shp_xbrl(con)
        con.commit()
        con.execute("DETACH DATABASE shp_xbrl")
        for atom in ("hold.pct", "hold.pledge_pct"):
            count, entities = con.execute(
                "SELECT COUNT(*), COUNT(DISTINCT entity_id) FROM fact WHERE atom=?",
                (atom,)).fetchone()
            con.execute(
                "UPDATE atom_status SET status='filled', rows=?, entities=?, isin_entities=?, "
                "isin_coverage_pct=?, source=?, note=? WHERE atom_id=?",
                (count, entities, entities, round(100.0 * entities / 60, 1),
                 "shp_index + pilot shareholding XBRL", "see fetch_shp_xbrl_pilot", atom))
        con.commit()
        return rows
    finally:
        con.close()


# ----------------------------------------------------------------------- coverage
def _all_atoms(con: sqlite3.Connection) -> list[str]:
    atoms = {r[0] for r in con.execute("SELECT DISTINCT atom FROM fact")}
    if "oi" in attached(con):
        atoms |= {r[0] for r in con.execute("SELECT DISTINCT atom FROM oi.fact")}
    return sorted(atoms)


def coverage(con: sqlite3.Connection) -> dict:
    """Per-atom row/entity counts, the unbuilt atoms, atom status and membership."""
    facts = {atom: {"rows": n, "entities": e}
             for atom, (n, e, _i) in _fact_counts(con, "fact").items()}
    side = {atom: {"rows": n, "entities": e}
            for atom, (n, e, _i) in (_fact_counts(con, "oi.fact") if "oi" in attached(con)
                                     else {}).items()}
    merged = dict(facts)
    merged.update(side)
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
        "facts": {atom: merged[atom] for atom in sorted(merged)},
        "side": side,
        "missing": [a for a in BUILT if a not in merged],
        "not_built": dict(NOT_BUILT),
        "atom_status": atom_status(con),
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
_QUARTER_METRIC = {"fin.revenue": "revenue", "fin.pat": "pat", "fin.eps": "eps",
                   "fin.interest_expense": "finance_costs", "fin.capex": "capex"}
_QMAP = {"fin.revenue": "revenue", "fin.pat": "pat", "fin.eps": "eps",
         "fin.book_equity": "net_worth", "fin.cash": "cash", "fin.receivables": "receivables",
         "fin.inventory": "inventory", "fin.payables": "payables",
         "fin.interest_expense": "finance_costs"}


def _price_indicator(con: sqlite3.Connection, isin: str, date: str, kind: str):
    """Recompute sma_20 / rsi_14 from the closes up to ``date`` (trailing only)."""
    closes = [r[0] for r in con.execute(
        "SELECT close FROM market_state.company_state_daily WHERE isin=? AND date<=? "
        "AND close IS NOT NULL ORDER BY date DESC LIMIT 250", (isin, date))][::-1]
    sma, rsi = price_series(closes)
    value = (sma if kind == "sma" else rsi)[-1] if closes else None
    if value is None:
        return (None, None)
    known = con.execute("SELECT known_at FROM market_state.company_state_daily "
                        "WHERE isin=? AND date=?", (isin, date)).fetchone()
    return (round(value, 6), known[0] if known else None)


_BSE_EQ_COL = {"price.open": "open", "price.high": "high", "price.low": "low",
               "price.volume": "volume", "price.traded_value": "turnover_inr"}


def _bse_price(con: sqlite3.Connection, atom: str, isin: str, date: str):
    """(value, known_at) from the BSE bhavcopy for a name the NSE panel does not carry."""
    if atom in ("price.delivery_qty", "price.delivery_pct"):
        col = "deliverable_qty" if atom == "price.delivery_qty" else "delivery_pct"
        return con.execute(
            f"SELECT dv.{col}, e.date || 'T23:59:59' FROM ei.mkt_bse_eq_daily e "
            "JOIN ei.mkt_bse_delivery_daily dv ON dv.sc_code = e.sc_code AND dv.date = e.date "
            "WHERE e.isin=? AND e.date=?", (isin, date)).fetchone()
    return con.execute(
        f"SELECT e.{_BSE_EQ_COL[atom]}, e.date || 'T23:59:59' FROM ei.mkt_bse_eq_daily e "
        "WHERE e.isin=? AND e.date=?", (isin, date)).fetchone()


def _source_value(con: sqlite3.Connection, row: sqlite3.Row) -> tuple | None:
    """(value, known_at) re-read from the source table, for the hand check."""
    atom, isin, end = row["atom"], row["entity_id"], row["period_end"]
    d = _dims(row)
    if str(row["source_ref"]).startswith("shp_xbrl:"):
        if "shp_xbrl" not in attached(con):
            return None
        return con.execute("SELECT value, known_at FROM shp_xbrl.fact WHERE entity_id=? AND "
                           "atom=? AND dims=? AND period_end=?",
                           (isin, atom, row["dims"], end)).fetchone()
    if atom == "price.close":
        # fact_view.sql loads the TRADED close (raw_close); company_state_daily.close is
        # the build's adjusted series and is not what the fact row holds.
        return con.execute("SELECT raw_close, known_at FROM market_state.company_state_daily "
                           "WHERE isin=? AND date=?", (isin, end)).fetchone()
    if atom == "price.mcap":
        return con.execute("SELECT mcap_cr, known_at FROM market_state.company_state_daily "
                           "WHERE isin=? AND date=?", (isin, end)).fetchone()
    if atom == "price.shares_out":
        return con.execute("SELECT shares_out, known_at FROM market_state.company_state_daily "
                           "WHERE isin=? AND date=?", (isin, end)).fetchone()
    if atom in ("price.sma", "price.rsi"):
        return _price_indicator(con, isin, end, "sma" if atom == "price.sma" else "rsi")
    if atom in _BHAV_COL:
        if d.get("exchange") == "BSE":            # filled by fact_view_extras.sql
            return _bse_price(con, atom, isin, end)
        col = _BHAV_COL[atom]
        return con.execute(
            f"SELECT b.{col}, b.date || 'T23:59:59' FROM market_state_b.mkt_nse_full_daily b "
            "JOIN pilot_universe u ON u.symbol = b.symbol WHERE u.isin=? AND b.date=?",
            (isin, end)).fetchone()
    if atom == "price.band":
        return con.execute("SELECT band, date || 'T23:59:59' FROM market_state.price_band_daily "
                           "WHERE isin=? AND date=?", (isin, end)).fetchone()
    if atom in _QUARTER_METRIC and d.get("period_kind") == "quarter" \
            and "quarters" in attached(con):
        return con.execute(
            "SELECT value, known_at FROM quarters.company_quarter_series WHERE isin=? "
            "AND metric_key=? AND period_end=? AND basis=?",
            (isin, _QUARTER_METRIC[atom], end, d.get("basis", ""))).fetchone()
    if atom in _QMAP:
        key = _QMAP[atom]
        return con.execute(
            "SELECT value, known_at FROM facts_pilot.company_metric_series WHERE isin=? "
            "AND metric_key=? AND period_end=? AND COALESCE(basis,'')=? "
            "AND COALESCE(period_kind,'')=?",
            (isin, key, end, d.get("basis", ""), d.get("period_kind", ""))).fetchone()
    if atom in ("fin.ebitda", "fin.total_debt"):
        if atom == "fin.ebitda" and d.get("period_kind") == "quarter" \
                and "quarters" in attached(con):
            keys = ("pbt", "finance_costs", "depreciation")
            got = con.execute(
                "SELECT COUNT(DISTINCT metric_key), SUM(value), MAX(known_at) "
                "FROM quarters.company_quarter_series WHERE isin=? AND period_end=? "
                "AND basis=? AND metric_key IN (?,?,?) AND value IS NOT NULL",
                (isin, end, d.get("basis", ""), *keys)).fetchone()
            return (None, None) if got[0] != len(keys) else (got[1], got[2])
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
    if atom == "hold.fpi_limit_utilised":
        return con.execute(
            "SELECT fpi_limit_utilised_pct, COALESCE(broadcast_at, quarter_end || 'T23:59:59') "
            "FROM ei.shareholding WHERE isin=? AND quarter_end=?", (isin, end)).fetchone()
    if atom == "flows.net_inr":
        if "ei" not in attached(con):               # core-only fixture: the pilot branch
            return con.execute("SELECT insider_net_inr, known_at FROM "
                               "market_state.event_leakage_window WHERE isin=? AND date=? "
                               "AND offset=0", (isin, end)).fetchone()
        return con.execute(
            "SELECT SUM(CASE WHEN lower(COALESCE(transaction_type,'')) LIKE '%acq%' "
            "OR lower(COALESCE(transaction_type,'')) LIKE '%buy%' "
            "OR lower(COALESCE(transaction_type,'')) LIKE '%purchase%' "
            "THEN value_inr ELSE -value_inr END), MAX(known_at) "
            "FROM ei.insider_trades_v2 WHERE isin=? AND substr(known_at,1,10)=? "
            "AND value_inr IS NOT NULL AND COALESCE(is_superseded,0)=0",
            (isin, end)).fetchone()
    if atom == "text.passage":
        return con.execute("SELECT body, known_at FROM chunks_v3.chunk WHERE chunk_id=?",
                           (d.get("chunk"),)).fetchone()
    if atom == "macro.commodity_close":
        return con.execute("SELECT value, known_at FROM market_state_b.series_observation "
                           "WHERE series_code=? AND period_start=? AND kind='commodity'",
                           (isin, end)).fetchone()
    if atom == "macro.series":
        return con.execute("SELECT value, known_at FROM market_state_b.series_observation "
                           "WHERE series_code=? AND period_start=?", (isin, end)).fetchone()
    if atom == "macro.policy":
        return con.execute("SELECT amount_inr_crore, published_at FROM ei.policy_events "
                           "WHERE id=?", (d.get("event_id"),)).fetchone()
    if atom == "macro.claim":
        return con.execute(
            "SELECT c.direction, COALESCE(c.known_at, d.known_at) FROM macro.macro_claim c "
            "LEFT JOIN macro.macro_doc d ON d.doc_id=c.doc_id WHERE c.claim_id=?",
            (isin.split(":", 1)[-1],)).fetchone()
    if atom == "macro.index_close":
        return con.execute("SELECT close, date || 'T23:59:59' FROM ei.mkt_nse_index_daily "
                           "WHERE index_name=? AND date=?", (isin, end)).fetchone()
    if atom == "macro.flow":
        col = "fii_net_cr" if d.get("measure") == "fii_net" else "dii_net_cr"
        return con.execute(f"SELECT {col}, date || 'T23:59:59' FROM ei.mkt_fii_dii_cash "
                           "WHERE date=?", (end,)).fetchone()
    if atom == "macro.etf_premium":
        return con.execute("SELECT premium_vs_inav_pct, date || 'T23:59:59' FROM ei.etf_inav "
                           "WHERE isin=? AND date=?", (isin, end)).fetchone()
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
    # derived atoms are stored rounded to 6 dp, so compare at 1e-6 relative
    return abs(float(a) - float(b)) <= 1e-6 * max(1.0, abs(float(b)))


def handcheck(con: sqlite3.Connection, per_atom: int = 1) -> list[dict]:
    """Re-read one row of every atom from its source table and compare.

    Deterministic (the first entity of each atom, then the first row of that entity),
    so a re-run prints the same rows.  A row is OK only when both value and known_at
    match the source exactly.  Every probe is a primary-key seek, never an atom scan:
    the pilot's ``macro.oi`` alone is 16.2 M rows.
    """
    out = []
    for atom in _all_atoms(con):
        table = "oi.fact" if ("oi" in attached(con) and atom in SIDE_ATOMS) else "fact"
        entities = []
        for row in con.execute(f"SELECT entity_id FROM {table} WHERE atom=? LIMIT 1", (atom,)):
            entities.append(row[0])
        if per_atom > 1 and entities:
            for row in con.execute(f"SELECT entity_id FROM {table} WHERE atom=? AND entity_id<>? "
                                   "LIMIT ?", (atom, entities[0], per_atom - 1)):
                entities.append(row[0])
        for entity in entities:
            row = con.execute(f"SELECT * FROM {table} WHERE entity_id=? AND atom=? LIMIT 1",
                              (entity, atom)).fetchone()
            if row is None:
                continue
            src = _source_value(con, row)
            # a probe that misses (dims/period not in the attached source) is a BAD row,
            # not a crash: the hand check exists to surface exactly that
            src_value, src_known = src if src is not None else (None, None)
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
    atoms = _all_atoms(con)
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
    ap.add_argument("--oi-out", default=None, help="macro.oi side file (default <out>_oi.db)")
    ap.add_argument("--root", default=None, help="data root (default REALITY_DATA_ROOT)")
    ap.add_argument("--universe", default=None, help="pilot universe CSV")
    ap.add_argument("--quarters", default=None,
                    help="single-quarter store (default <out dir>/quarters_pilot60.db)")
    ap.add_argument("--ei", default=None, help="equity_intelligence.db path")
    ap.add_argument("--macro", default=None, help="pilot/macro_all.db path")
    ap.add_argument("--bench-n", type=int, default=200)
    ap.add_argument("--report", action="store_true",
                    help="report/check the existing --out instead of rebuilding it")
    ap.add_argument("--shp-xbrl-only", action="store_true",
                    help="install the shareholding XBRL rows on the existing --out DB and exit")
    ap.add_argument("--holdings-only", action="store_true",
                    help="apply the holdings-ISIN step to the existing --out DB and exit")
    args = ap.parse_args(argv)

    out = Path(args.out)
    root = Path(args.root or DEFAULT_ROOT)
    quarters = Path(args.quarters) if args.quarters else out.parent / "quarters_pilot60.db"
    oi_out = Path(args.oi_out) if args.oi_out else out.parent / (out.stem + "_oi.db")
    ei = Path(args.ei) if args.ei else root / "equity_intelligence.db"
    macro = Path(args.macro) if args.macro else root / "pilot" / "macro_all.db"
    if args.shp_xbrl_only:
        rows = apply_shp_xbrl(args.out, Path(args.out).parent / SHP_XBRL_DB)
        print(f"shareholding XBRL step: {rows:,} rows")
        return 0
    if args.holdings_only:
        rows = apply_holdings(args.out, args.root, args.universe)
        print(f"holdings step: {rows:,} rows carry the shp_index#symbol_isin_history source")
        return 0
    if args.report:
        if not out.is_file():
            print(f"{out} does not exist; drop --report to build it", file=sys.stderr)
            return 2
        elapsed = None
    else:
        if not quarters.is_file():
            from reality_engine.query.v4.build_quarters import build as build_quarters
            print(f"quarters store {quarters} missing: deriving it from results_xbrl.db")
            build_quarters(quarters, root)
        t0 = time.perf_counter()
        build(out, root, args.universe, quarters=quarters, ei=ei, macro=macro,
              oi_out=oi_out)
        elapsed = time.perf_counter() - t0
    con = sqlite3.connect(str(out), uri=True)
    con.row_factory = sqlite3.Row
    try:
        attach(con, root, quarters=quarters, ei=ei, macro=macro)
        if "oi" not in attached(con) and oi_out.is_file():
            con.execute("ATTACH DATABASE ? AS oi", (_uri(oi_out),))
        seed_universe(con, read_universe(args.universe))
        attach_identity(con, args.root)
        attach_shp_xbrl(con, out.parent / SHP_XBRL_DB)
        cov = coverage(con)
        built = f" in {elapsed:.1f}s" if elapsed is not None else ""
        print(f"{out}{built}  ({out.stat().st_size / 1e6:.0f} MB)")
        if oi_out.is_file():
            print(f"{oi_out}  ({oi_out.stat().st_size / 1e6:.0f} MB)  macro.oi side file")
        print(f"\nfacts: {sum(v['rows'] for v in cov['facts'].values()):,} rows, "
              f"{len(cov['facts'])} atoms")
        print(f"\natom status ({len(cov['atom_status'])} held atoms):")
        for row in cov["atom_status"]:
            print(f"  {row['atom_id']:<26} {row['status']:<9} {row['rows']:>9,} rows "
                  f"{row['isin_entities']:>3}/60 ISINs {row['isin_coverage_pct']:>5.1f}%"
                  + (f"  [{row['store']}]" if row["store"] != "-" else ""))
        for atom, why in cov["not_built"].items():
            print(f"  {atom:<26} NOT BUILT: {why}")
        empty = [a for a in BUILT if a not in cov["facts"]]
        if empty:
            print(f"  branches with no row: {empty}")
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
