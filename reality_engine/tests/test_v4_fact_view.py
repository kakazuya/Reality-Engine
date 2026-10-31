"""Fixture tests for the v4 fact view and the membership table (§B.1/§B.2, §H.2).

The fixture is a temp data root under ``.tmp`` (the worker sandbox cannot open
``tempfile.mkdtemp``'s restrictive DACL with sqlite): the same table names and
columns the pilot stores carry, two companies and one index with a dated notice,
a snapshot-backcast slot and an open slot.  No live database is touched.

The last test is the pilot hand check: it runs only when the built pilot DB exists
(``python -m reality_engine.query.v4.build_membership``), so a fresh checkout still
passes on the fixtures alone.
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
from pathlib import Path

import pytest

from reality_engine.query.v4 import build_membership as bm
from reality_engine.query.v4 import build_quarters as bq

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / ".tmp" / f"v4fact_{os.getpid()}"
ISIN_A = "INE000A01001"
ISIN_B = "INE000B01002"


def _oi_path(out: Path) -> Path:
    """The macro.oi side file build() writes next to the core store."""
    return out.parent / (out.stem + "_oi.db")

SCHEMA = {
    "market_state": [
        "CREATE TABLE company_state_daily(isin TEXT, date TEXT, close REAL, mcap_cr REAL, "
        "shares_out INTEGER, known_at TEXT)",
        "CREATE TABLE price_band_daily(isin TEXT, date TEXT, band INTEGER, has_band INTEGER)",
        "CREATE TABLE company_ownership_pit(isin TEXT, quarter_end TEXT, known_at TEXT, "
        "promoter_pct REAL, pledge_pct REAL, fii_pct REAL, dii_pct REAL, mf_pct REAL, "
        "public_pct REAL, source TEXT)",
        "CREATE TABLE event_leakage_window(event_id TEXT, isin TEXT, offset INTEGER, date TEXT, "
        "insider_net_inr REAL, known_at TEXT)",
        "CREATE TABLE company_membership_pit(isin TEXT, index_code TEXT, added_on TEXT, "
        "removed_on TEXT, source TEXT, pit_conf REAL)",
        "CREATE TABLE index_list(index_code TEXT, display_name TEXT, snapshot_date TEXT)",
    ],
    "facts_pilot": [
        "CREATE TABLE company_metric_series(isin TEXT, metric_key TEXT, period_end TEXT, "
        "period_kind TEXT, basis TEXT, value REAL, unit TEXT, source TEXT, doc_id TEXT, "
        "known_at TEXT, pit_conf REAL)",
        "CREATE TABLE company_segment_pnl(isin TEXT, segment TEXT, period_end TEXT, metric TEXT, "
        "basis TEXT, value_cr REAL, known_at TEXT)",
    ],
    "market_state_b": [
        "CREATE TABLE mkt_nse_full_daily(date TEXT, symbol TEXT, series TEXT, open REAL, "
        "high REAL, low REAL, close REAL, volume INTEGER, turnover_lacs REAL, "
        "deliverable_qty INTEGER, delivery_pct REAL)",
        "CREATE TABLE commodity_price_daily(series_code TEXT, commodity TEXT, date TEXT, "
        "close REAL, unit TEXT, known_at TEXT)",
        "CREATE TABLE series_observation(series_code TEXT, dim_id TEXT, kind TEXT, "
        "period_start TEXT, period_end TEXT, value REAL, unit TEXT, known_at TEXT)",
        "CREATE TABLE fno_oi_daily(date TEXT, underlying TEXT, expiry TEXT, strike REAL, "
        "option_type TEXT, oi REAL, isin TEXT)",
    ],
    "metric_state": [
        "CREATE TABLE order_intake(isin TEXT, period_end TEXT, intake_cr REAL, "
        "order_book_cr REAL, known_at TEXT)",
        "CREATE TABLE company_capacity_utilisation(isin TEXT, period_end TEXT, product TEXT, "
        "utilisation_pct REAL, known_at TEXT)",
    ],
    "chunks_v3": [
        "CREATE TABLE chunk(chunk_id INTEGER, isin TEXT, body TEXT, doc_type TEXT, "
        "page_from INTEGER, event_date TEXT, known_at TEXT)",
    ],
}

ROWS = {
    "market_state": [
        "INSERT INTO company_state_daily VALUES "
        f"('{ISIN_A}','2024-06-28',101.5,70000.0,1000,'2024-06-28T15:30:00'),"
        f"('{ISIN_B}','2024-06-28',52.0,9000.0,500,'2024-06-28T15:30:00')",
        "INSERT INTO price_band_daily VALUES "
        f"('{ISIN_A}','2024-06-28',20,1),('{ISIN_B}','2024-06-28',NULL,0)",
        "INSERT INTO company_ownership_pit VALUES "
        f"('{ISIN_A}','2024-06-30','2024-07-10T09:00:00',55.0,NULL,12.0,NULL,NULL,45.0,'shp')",
        f"INSERT INTO event_leakage_window VALUES ('e1','{ISIN_A}',0,'2024-06-28',5.0,"
        "'2024-06-28T20:00:00')",
        "INSERT INTO company_membership_pit VALUES "
        f"('{ISIN_A}','nifty50','2024-03-29','2025-06-27','nse_notice',1.0),"
        f"('{ISIN_B}','nifty50','2019-01-01',NULL,'snapshot_backcast',0.8),"
        f"('{ISIN_A}','nifty100','2023-07-12','2023-07-13','snapshot_backcast',0.8)",
        "INSERT INTO index_list VALUES ('nifty50','NIFTY 50','2026-09-30'),"
        "('nifty100','NIFTY 100','2026-09-30')",
    ],
    "facts_pilot": [
        "INSERT INTO company_metric_series VALUES "
        f"('{ISIN_A}','revenue','2024-06-30','quarter','consolidated',1000.0,'INR_CRORE',"
        "'xbrl','d1','2024-07-15T18:00:00',1.0),"
        f"('{ISIN_A}','pat','2024-06-30','quarter','consolidated',100.0,'INR_CRORE',"
        "'xbrl','d1','2024-07-15T18:00:00',1.0),"
        f"('{ISIN_A}','pbt','2024-06-30','quarter','consolidated',150.0,'INR_CRORE',"
        "'xbrl','d1','2024-07-15T18:00:00',1.0),"
        f"('{ISIN_A}','finance_costs','2024-06-30','quarter','consolidated',30.0,'INR_CRORE',"
        "'xbrl','d1','2024-07-15T18:00:00',1.0),"
        f"('{ISIN_A}','depreciation','2024-06-30','quarter','consolidated',20.0,'INR_CRORE',"
        "'xbrl','d1','2024-07-15T18:00:00',1.0),"
        f"('{ISIN_A}','borrowings_current','2024-06-30','instant','consolidated',40.0,"
        "'INR_CRORE','xbrl','d1','2024-07-15T18:00:00',1.0),"
        f"('{ISIN_A}','borrowings_noncurrent','2024-06-30','instant','consolidated',60.0,"
        "'INR_CRORE','xbrl','d1','2024-07-15T18:00:00',1.0)",
        "INSERT INTO company_segment_pnl VALUES "
        f"('{ISIN_A}','Chemicals','2024-06-30','revenue','consolidated',700.0,"
        "'2024-07-15T18:00:00')",
    ],
    "market_state_b": [
        "INSERT INTO mkt_nse_full_daily VALUES "
        "('2024-06-28','AAA','EQ',100.0,103.0,99.0,101.5,12000,61.0,4000,33.3)",
        "INSERT INTO commodity_price_daily VALUES "
        "('wb_copper','wb_copper','2024-06-30',9500.0,'($/mt)','2026-10-02T23:59:59')",
        "INSERT INTO series_observation VALUES "
        "('wb_copper','wb_copper','commodity','2024-06-30','2024-06-30',9500.0,'($/mt)',"
        "'2026-10-02T23:59:59')",
        "INSERT INTO fno_oi_daily VALUES "
        f"('2024-06-28','AAA','2024-07-25',100.0,'FUT',5000.0,'{ISIN_A}')",
    ],
    "metric_state": [
        f"INSERT INTO order_intake VALUES ('{ISIN_A}','2024-06-30',250.0,900.0,"
        "'2024-07-20T12:00:00')",
        f"INSERT INTO company_capacity_utilisation VALUES ('{ISIN_A}','2024-06-30','caustic',"
        "82.5,'2024-07-20T12:00:00')",
    ],
    "chunks_v3": [
        f"INSERT INTO chunk VALUES (7,'{ISIN_A}','demand stayed strong','concall',3,"
        "'2024-07-18','2024-07-18T21:00:00')",
    ],
}


def _make_fixture() -> Path:
    """Write the five pilot DBs and the universe CSV under ``.tmp``."""
    shutil.rmtree(FIXTURE, ignore_errors=True)
    pilot = FIXTURE / "pilot" / "pilot60"
    pilot.mkdir(parents=True, exist_ok=True)
    for alias, name in bm.STORES.items():
        con = sqlite3.connect(pilot / name)
        for ddl in SCHEMA[alias]:
            con.execute(ddl)
        for sql in ROWS[alias]:
            con.execute(sql)
        con.commit()
        con.close()
    (FIXTURE / "UNIVERSE.csv").write_text(
        "isin,symbol\n" f"{ISIN_A},AAA\n" f"{ISIN_B},BBB\n", encoding="utf-8")
    return pilot


@pytest.fixture(scope="module")
def built() -> Path:
    """Build the fixture DB once and hand back its path."""
    _make_fixture()
    out = FIXTURE / "fact.db"
    bm.build(out, root=FIXTURE, universe_csv=FIXTURE / "UNIVERSE.csv")
    yield out
    shutil.rmtree(FIXTURE, ignore_errors=True)


def _con(path: Path) -> sqlite3.Connection:
    # uri=True so the ATTACH of the pilot stores (a file: URI, mode=ro) is honoured
    con = sqlite3.connect(str(path), uri=True)
    con.row_factory = sqlite3.Row
    return con


def _facts(con: sqlite3.Connection, atom: str) -> list[sqlite3.Row]:
    return con.execute("SELECT * FROM fact WHERE atom=? ORDER BY entity_id, dims",
                       (atom,)).fetchall()


# ------------------------------------------------------------------ fact table
def test_every_held_atom_is_declared_and_the_registry_agrees():
    assert len(bm.HELD_ATOMS) == 43
    assert set(bm.HELD_ATOMS) == set(bm.BUILT) | set(bm.NOT_BUILT)
    assert not set(bm.BUILT) & set(bm.NOT_BUILT)
    registry = ROOT / "tasks" / "arch_v4" / "concept_registry.json"
    if registry.is_file():                       # guard against registry drift
        atoms = json.loads(registry.read_text(encoding="utf-8"))["atoms"]
        held = {a["atom_id"] for a in atoms if a["coverage"] == "held"}
        assert held == set(bm.HELD_ATOMS)


def test_market_atoms_carry_the_source_value_and_known_at(built):
    con = _con(built)
    try:
        close = {r["entity_id"]: r for r in _facts(con, "price.close")}
        assert close[ISIN_A]["value"] == 101.5
        assert close[ISIN_A]["known_at"] == "2024-06-28T15:30:00"
        assert close[ISIN_A]["unit"] == "INR"
        # the bhavcopy is symbol-keyed; the pilot universe supplies the ISIN
        high = _facts(con, "price.high")
        assert [(r["entity_id"], r["value"], r["dims"]) for r in high] == [
            (ISIN_A, 103.0, "exchange=NSE")]
        assert high[0]["known_at"] == "2024-06-28T23:59:59"
        # band NULL = no band held, so no row
        assert [r["value"] for r in _facts(con, "price.band")] == [20.0]
    finally:
        con.close()


def test_fundamental_atoms_and_the_two_declared_aggregates(built):
    con = _con(built)
    try:
        rev = _facts(con, "fin.revenue")[0]
        assert (rev["value"], rev["unit"]) == (1000.0, "INR_CRORE")
        assert rev["dims"] == "basis=consolidated;period_kind=quarter"
        assert rev["known_at"] == "2024-07-15T18:00:00"
        ebitda = _facts(con, "fin.ebitda")[0]
        assert ebitda["value"] == pytest.approx(150.0 + 30.0 + 20.0)
        assert ebitda["source_ref"].startswith("derived:")
        debt = _facts(con, "fin.total_debt")[0]
        assert debt["value"] == pytest.approx(40.0 + 60.0)
        seg = _facts(con, "fin.segment_value")[0]
        assert seg["dims"] == "basis=consolidated;metric=revenue;segment=Chemicals"
        assert _facts(con, "fin.capacity_utilisation")[0]["value"] == 82.5
        assert _facts(con, "fin.order_book")[0]["value"] == 900.0
        assert _facts(con, "fin.order_intake")[0]["value"] == 250.0
    finally:
        con.close()


def test_ownership_narrative_and_macro_atoms(built):
    con = _con(built)
    try:
        hold = {r["dims"]: r["value"] for r in _facts(con, "hold.pct")}
        assert hold == {"holder_class=promoter": 55.0, "holder_class=fii": 12.0,
                        "holder_class=public": 45.0}
        assert _facts(con, "hold.pledge_pct") == []          # NULL in every pilot row
        flows = _facts(con, "flows.net_inr")[0]
        assert (flows["value"], flows["known_at"]) == (5.0, "2024-06-28T20:00:00")
        text = _facts(con, "text.passage")[0]
        assert text["value"] == "demand stayed strong"
        assert text["dims"] == "doctype=concall;page=3;chunk=7"
        assert text["source_ref"] == "chunks_v3.chunk#7"
        assert _facts(con, "macro.commodity_close")[0]["entity_id"] == "wb_copper"
        assert _facts(con, "macro.series")[0]["value"] == 9500.0
        # macro.oi lives in the side file, not the core store (§F.6 size split)
        assert _facts(con, "macro.oi") == []
        oi = sqlite3.connect(str(_oi_path(FIXTURE / "fact.db")))
        try:
            oi_oi = oi.execute("SELECT * FROM fact WHERE atom='macro.oi'").fetchall()
            assert len(oi_oi) == 1
            assert oi_oi[0][2] == "expiry=2024-07-25;option_type=FUT;strike=100.0"
            assert oi_oi[0][5] == 5000.0
        finally:
            oi.close()
    finally:
        con.close()


def test_one_row_per_entity_atom_dims_period(built):
    con = _con(built)
    try:
        total, keys = con.execute(
            "SELECT (SELECT COUNT(*) FROM fact), "
            "(SELECT COUNT(*) FROM (SELECT entity_id, atom, dims, period_start, period_end "
            " FROM fact GROUP BY 1, 2, 3, 4, 5))").fetchone()
        assert total == keys and total > 0
    finally:
        con.close()


def test_pit_filter_is_a_sql_condition(built):
    con = _con(built)
    sql = ("SELECT known_at FROM fact WHERE entity_id=? AND atom='fin.revenue' "
           "AND known_at <= ?")
    try:
        assert con.execute(sql, (ISIN_A, "2024-07-14")).fetchall() == []
        assert con.execute(sql, (ISIN_A, "2024-07-15")).fetchall() == []   # 18:00 > date
        assert con.execute(sql, (ISIN_A, "2024-07-16")).fetchall() != []
    finally:
        con.close()


def test_attached_sources_are_read_only(built):
    con = sqlite3.connect(str(built), uri=True)
    try:
        bm.attach(con, FIXTURE)
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            con.execute("UPDATE market_state.company_state_daily SET close=1")
    finally:
        con.close()


# ----------------------------------------------------------------- membership
def test_membership_windows_known_at_and_pit_known(built):
    con = _con(built)
    try:
        rows = {r["valid_from"]: r for r in con.execute(
            "SELECT * FROM membership WHERE entity_id=? ORDER BY valid_from", (ISIN_A,))}
        notice = rows["2024-03-29"]
        assert (notice["set_kind"], notice["set_value"]) == ("index", "nifty50")
        assert (notice["valid_to"], notice["pit_known"]) == ("2025-06-27", 1)
        assert notice["known_at"] == "2024-03-29T23:59:59"
        # a snapshot-backcast stint keeps only the attested day and is never PIT-clean
        past = rows["2023-07-12"]
        assert (past["valid_to"], past["pit_known"]) == ("2023-07-13", 0)
        assert past["known_at"] == "2023-07-13T23:59:59"
        # an open backcast stint starts at the first snapshot, not at 2019
        open_row = con.execute(
            "SELECT * FROM membership WHERE entity_id=? AND set_value='nifty50'",
            (ISIN_B,)).fetchone()
        assert (open_row["valid_from"], open_row["valid_to"]) == ("2026-09-30", None)
        assert (open_row["pit_known"], open_row["known_at"]) == (0, "2026-09-30T23:59:59")
        assert con.execute("SELECT COUNT(*) FROM membership WHERE set_kind='sector'"
                           ).fetchone()[0] == 0
    finally:
        con.close()


def test_membership_as_of_join(built):
    """The query the executor runs: one set, one date, PIT-filtered."""
    con = _con(built)
    try:
        def members(day: str) -> list[str]:
            return [r[0] for r in con.execute(
                "SELECT entity_id FROM membership WHERE set_kind='index' AND set_value='nifty50' "
                "AND valid_from<=? AND (valid_to IS NULL OR valid_to>?) AND known_at<=? "
                "ORDER BY entity_id", (day, day, day))]
        assert members("2024-06-28") == [ISIN_A]          # the notice-dated window
        assert members("2026-10-19") == [ISIN_B]          # B starts at the held snapshot
    finally:
        con.close()


# --------------------------------------------------------------------- checks
def test_handcheck_and_lookup_timing(built):
    con = _con(built)
    try:
        bm.attach(con, FIXTURE)
        bm.seed_universe(con, bm.read_universe(FIXTURE / "UNIVERSE.csv"))
        rows = bm.handcheck(con)
        assert rows and all(r["ok"] for r in rows), [r for r in rows if not r["ok"]]
        assert len({r["atom"] for r in rows}) >= 15
        timing = bm.bench(con, n=50)
        print(f"\nlookup n={timing['n']} median {timing['median_ms']:.2f} ms "
              f"p90 {timing['p90_ms']:.2f} ms")
        assert timing["median_ms"] < 50.0
    finally:
        con.close()


def test_pilot_handcheck_when_the_build_exists(built):
    """The 30-row acceptance check, only where the pilot build was produced."""
    pilot_db = ROOT / ".tmp" / "fact_v4_pilot.db"
    if not pilot_db.is_file():
        pytest.skip("pilot build absent (run build_membership)")
    data = Path(os.environ.get("REALITY_DATA_ROOT") or (ROOT / "reality_engine" / "data"))
    con = sqlite3.connect(str(pilot_db), uri=True)
    con.row_factory = sqlite3.Row
    try:
        bm.attach(con, quarters=ROOT / ".tmp" / "quarters_pilot60.db",
                  ei=data / "equity_intelligence.db", macro=data / "pilot" / "macro_all.db")
        oi_db = _oi_path(pilot_db)
        if oi_db.is_file():
            con.execute("ATTACH DATABASE ? AS oi",
                        (f"file:{oi_db.as_posix()}?mode=ro&immutable=1",))
        bm.seed_universe(con, bm.read_universe())
        cov = bm.coverage(con)
        assert cov["membership"]["entities"] >= 1888
        assert cov["membership"]["index_sets"] >= 124
        assert cov["missing"] == [] or set(cov["missing"]) <= bm.EMPTY_OK
        assert len(cov["atom_status"]) == 43
        assert {r["atom_id"] for r in cov["atom_status"]} == set(bm.HELD_ATOMS)
        by = {r["atom_id"]: r for r in cov["atom_status"]}
        assert by["price.open"]["isin_entities"] == 60        # 9 blank + 2 renamed resolved
        assert by["price.rsi"]["isin_entities"] == 60
        assert con.execute("SELECT COUNT(*) FROM fact WHERE atom='price.open' "
                           "AND dims='exchange=BSE'").fetchone()[0] > 0
        rows = bm.handcheck(con)
        assert len(rows) >= 30
        assert all(r["ok"] for r in rows), [r for r in rows if not r["ok"]]
        timing = bm.bench(con)
        print(f"\npilot lookup n={timing['n']} median {timing['median_ms']:.2f} ms "
              f"p90 {timing['p90_ms']:.2f} ms")
        assert timing["median_ms"] < 50.0
    finally:
        con.close()


# ------------------------------------------------------- quarters / WP2c additions
def test_seed_universe_resolves_blank_and_renamed_symbols():
    """A blank CSV symbol and a renamed one both come from the registry; a live symbol stays."""
    tmp = ROOT / ".tmp" / f"v4seed_{os.getpid()}"      # .tmp: tempfile DACL is unusable here
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    try:
        ei, bhav = tmp / "ei.db", tmp / "b.db"
        con = sqlite3.connect(str(ei))
        con.execute("CREATE TABLE security_master(isin TEXT, nse_symbol TEXT)")
        con.executemany("INSERT INTO security_master VALUES (?,?)",
                        [(ISIN_A, "NEWSYM"), (ISIN_B, "KEEPSYM")])
        con.commit()
        con.close()
        con = sqlite3.connect(str(bhav))
        con.execute("CREATE TABLE mkt_nse_full_daily(date TEXT, symbol TEXT)")
        con.execute("INSERT INTO mkt_nse_full_daily VALUES ('2024-06-28','KEEPSYM')")
        con.commit()
        con.close()
        mem = sqlite3.connect(":memory:", uri=True)
        mem.execute("ATTACH DATABASE ? AS ei", (f"file:{ei.as_posix()}?mode=ro",))
        mem.execute("ATTACH DATABASE ? AS market_state_b",
                    (f"file:{bhav.as_posix()}?mode=ro",))
        bm.seed_universe(mem, [(ISIN_A, ""), (ISIN_B, "OLDSYM"), ("INE000C01003", "LIVE")])
        got = dict(mem.execute("SELECT isin, symbol FROM pilot_universe"))
        assert got == {ISIN_A: "NEWSYM", ISIN_B: "KEEPSYM", "INE000C01003": "LIVE"}
        mem.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


CRORE = 1e7


def _filing(file: str, period_end: str, period_start: str, known: str) -> dict:
    return {"file": file, "isin": ISIN_A, "period_end": period_end,
            "period_start": period_start, "consolidated": "Consolidated", "known_at": known}


def _fact(file: str, context: str, value_cr: float, start: str, end: str) -> dict:
    return {"file": file, "concept": "RevenueFromOperations", "context": context,
            "period_start": start, "period_end": end, "value": value_cr * CRORE}


def test_quarter_derivation_reported_and_ytd_difference():
    """OneD is the quarter; Q2-Q4 without OneD is FourD minus the prior-quarter YTD."""
    filings = [
        _filing("f1", "2025-06-30", "2025-04-01", "2025-07-15T18:00:00"),
        _filing("f2", "2025-09-30", "2025-07-01", "2025-10-15T18:00:00"),
        _filing("f3", "2025-12-31", "2025-10-01", "2026-01-15T18:00:00"),
        _filing("f4", "2026-03-31", "2026-01-01", "2026-04-15T18:00:00"),
    ]
    # FourD dates are the quarter's dates: the defect, and context must win over them
    facts = [
        _fact("f1", "OneD", 100, "2025-04-01", "2025-06-30"),
        _fact("f2", "OneD", 120, "2025-07-01", "2025-09-30"),
        _fact("f2", "FourD", 220, "2025-07-01", "2025-09-30"),
        _fact("f3", "FourD", 300, "2025-10-01", "2025-12-31"),
        _fact("f4", "FourD", 400, "2026-01-01", "2026-03-31"),
    ]
    rows, counts, checks = bq.derive_quarters(filings, facts)
    got = {(r["period_end"], r["derived"]): r["value"] for r in rows}
    assert got == {("2025-06-30", "reported"): pytest.approx(100.0),
                   ("2025-09-30", "reported"): pytest.approx(120.0),
                   ("2025-12-31", "ytd_difference"): pytest.approx(80.0),
                   ("2026-03-31", "ytd_difference"): pytest.approx(100.0)}
    assert all(r["derived"] in ("reported", "ytd_q1", "ytd_difference") for r in rows)
    # known_at is the filing's own stamp, never the period end
    assert {r["period_end"]: r["known_at"] for r in rows}["2025-12-31"] == "2026-01-15T18:00:00"
    # the YTD difference is checked against the filing's own quarter column (Q2)
    assert checks and all(c["ok"] for c in checks)
    assert counts["ytd_difference"] == 2


def test_quarter_derivation_never_invents_a_missing_or_restated_quarter():
    filings = [
        _filing("f1", "2025-06-30", "2025-04-01", "2025-07-15T18:00:00"),
        _filing("f2a", "2025-09-30", "2025-07-01", "2025-10-15T18:00:00"),
        _filing("f2b", "2025-09-30", "2025-07-01", "2025-10-20T18:00:00"),
        _filing("f3", "2025-12-31", "2025-10-01", "2026-01-15T18:00:00"),
        _filing("f7", "2026-12-31", "2026-10-01", "2027-01-15T18:00:00"),  # no Sep YTD
    ]
    facts = [
        _fact("f1", "OneD", 100, "2025-04-01", "2025-06-30"),
        _fact("f2a", "FourD", 220, "2025-07-01", "2025-09-30"),
        _fact("f2b", "FourD", 230, "2025-07-01", "2025-09-30"),   # restatement
        _fact("f3", "FourD", 300, "2025-10-01", "2025-12-31"),
        _fact("f7", "FourD", 500, "2026-10-01", "2026-12-31"),
    ]
    rows, counts, _checks = bq.derive_quarters(filings, facts)
    periods = [r["period_end"] for r in rows]
    assert "2025-06-30" in periods                    # the reported quarter stands
    assert "2025-12-31" not in periods                # restated prior YTD -> empty
    assert counts.get("restated_prior_ytd", 0) >= 1
    assert counts.get("missing_prior_ytd", 0) >= 1    # f7 has no Sep YTD


def test_price_series_uses_trailing_windows_only():
    closes = [float(i) for i in range(1, 26)]
    sma, rsi = bm.price_series(closes)
    assert sma[:19] == [None] * 19
    assert sma[19] == pytest.approx(sum(closes[:20]) / 20.0)
    assert rsi[:14] == [None] * 14
    assert rsi[14] == pytest.approx(100.0)            # rising: no losses
    short_sma, short_rsi = bm.price_series(closes[:20])
    assert short_sma == sma[:20] and short_rsi == rsi[:20]   # appending never rewrites


def test_atom_status_has_all_43_held_atoms(built):
    con = _con(built)
    try:
        con.execute("ATTACH DATABASE ? AS oi",
                    (f"file:{_oi_path(built).as_posix()}?mode=ro&immutable=1",))
        rows = bm.atom_status(con)
        assert len(rows) == 43
        assert {r["atom_id"] for r in rows} == set(bm.HELD_ATOMS)
        by = {r["atom_id"]: r for r in rows}
        assert by["macro.oi"]["status"] == "filled" and by["macro.oi"]["store"] == "oi"
        assert by["claim.claim"]["status"] == "not_built"
        assert all(r["status"] in ("filled", "empty", "not_built") for r in rows)
        assert all(0.0 <= r["isin_coverage_pct"] <= 100.0 for r in rows)
        assert con.execute("SELECT COUNT(*) FROM atom_status").fetchone()[0] == 43
    finally:
        con.close()
