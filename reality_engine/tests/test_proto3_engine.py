"""The v4 engine on the three prototype companies (T-033): routing and typed refusals.

Every question is a real row of `tasks/pilot60/PILOT_BANK_2026-10-31.jsonl` for BAJFINANCE
(INE296A01032), HINDALCO (INE038A01020) or KEC (INE389H01022).  The fixture has the live
stores' shape -- `fact` (WP2a), `claim` (WP2b) and the printed market panel
(`daily_price_delivery`, `mkt_bse_eq_daily`, `mkt_bse_delivery_daily`) -- and every expected
value is read back from that fixture, never typed into the assertion.

The rows check the four measurements the ticket names: the YTD high and its date; the
traded close and its basis; the delivered quantity per exchange and combined, never the
traded volume the question rules out; and a split of the order book, never its total.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

import pytest

from reality_engine.query.v4 import run

REPO = Path(__file__).resolve().parents[2]
BANK = REPO / "tasks" / "pilot60" / "PILOT_BANK_2026-10-31.jsonl"

BAJ, HIND, KEC = "INE296A01032", "INE038A01020", "INE389H01022"
BAJ_BSE, HIND_BSE, KEC_BSE = "500034", "500440", "500489"
SYMBOLS = {"BAJFINANCE": BAJ, "HINDALCO": HIND, "KEC": KEC}

#: The fixture's printed rows.  The assertions read them back from the store: these dicts
#: are the store's contents, not expectations copied into the test.
FACT_ROWS = [
    # the YTD high: three NSE sessions, one of which is the maximum
    (BAJ, "price.high", "exchange=NSE", "2026-01-02", "2026-01-02", 1_020.0, "INR",
     "2026-01-02", "market_state_b.mkt_nse_full_daily"),
    (BAJ, "price.high", "exchange=NSE", "2026-08-03", "2026-08-03", 1_176.4, "INR",
     "2026-08-03", "market_state_b.mkt_nse_full_daily"),
    (BAJ, "price.high", "exchange=NSE", "2026-09-30", "2026-09-30", 1_100.0, "INR",
     "2026-09-30", "market_state_b.mkt_nse_full_daily"),
    # the close the fact store holds is the build's adjusted series, not the traded close
    (BAJ, "price.close", "", "2026-10-16", "2026-10-16", 950.0, "INR",
     "2026-10-16", "market_state.company_state_daily"),
    (HIND, "price.close", "", "2026-10-16", "2026-10-16", 895.0, "INR",
     "2026-10-16", "market_state.company_state_daily"),
    # the excluded reading and the NSE-only delivery the fact view holds for both names
    (BAJ, "price.volume", "", "2026-09-21", "2026-09-21", 4_170_558.0, "shares",
     "2026-09-21", "market_state_b.mkt_nse_full_daily"),
    (BAJ, "price.delivery_qty", "exchange=NSE", "2026-09-21", "2026-09-21",
     2_905_882.0, "shares", "2026-09-21", "market_state_b.mkt_nse_full_daily"),
    (BAJ, "price.delivery_qty", "exchange=NSE", "2026-09-22", "2026-09-22",
     2_905_378.0, "shares", "2026-09-22", "market_state_b.mkt_nse_full_daily"),
    (HIND, "price.volume", "", "2026-09-21", "2026-09-21", 3_348_127.0, "shares",
     "2026-09-21", "market_state_b.mkt_nse_full_daily"),
    (HIND, "price.delivery_qty", "exchange=NSE", "2026-09-21", "2026-09-21",
     2_246_548.0, "shares", "2026-09-21", "market_state_b.mkt_nse_full_daily"),
    (HIND, "price.delivery_qty", "exchange=NSE", "2026-09-22", "2026-09-22",
     2_195_051.0, "shares", "2026-09-22", "market_state_b.mkt_nse_full_daily"),
    # a general order-book total for KEC: answering "EPC vs HAM" from this is the defect
    (KEC, "fin.order_book", "", "2026-06-30", "2026-06-30", 38_000.0, "INR_CRORE",
     "2026-08-10T18:52:29", "metric_state.order_intake"),
]

#: the NSE printed panel: traded close, delivered quantity and delivery percent per session
NSE_PANEL = [
    # (date, isin, symbol, close, deliverable_volume, delivery_pct)
    ("2026-09-21", BAJ, "BAJFINANCE", 1_021.3, 2_905_882, 69.68),
    ("2026-09-22", BAJ, "BAJFINANCE", 1_008.8, 2_905_378, 63.41),
    ("2026-10-16", BAJ, "BAJFINANCE", 982.1, 5_082_772, 65.07),
    ("2026-09-21", HIND, "HINDALCO", 985.0, 2_246_548, 60.10),
    ("2026-09-22", HIND, "HINDALCO", 975.0, 2_195_051, 63.42),
    ("2026-10-16", HIND, "HINDALCO", 908.0, 2_124_619, 62.44),
]

#: the BSE printed panel: the same measures on the second exchange
BSE_PANEL = [
    # (date, sc_code, isin, close, deliverable_qty, delivery_pct)
    ("2026-09-21", BAJ_BSE, BAJ, 1_024.0, 36_476, 60.32),
    ("2026-09-22", BAJ_BSE, BAJ, 1_009.0, 97_727, 63.87),
    ("2026-10-16", BAJ_BSE, BAJ, 981.9, 162_717, 59.47),
    ("2026-09-21", HIND_BSE, HIND, 985.0, 28_223, 42.72),
    ("2026-09-22", HIND_BSE, HIND, 975.0, 85_471, 68.29),
    ("2026-10-16", HIND_BSE, HIND, 910.0, 58_962, 50.86),
]


def _connect(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    return con


def _build(root: Path) -> None:
    v4 = root / "v4"
    v4.mkdir(parents=True, exist_ok=True)
    fact = _connect(v4 / "fact_v4_pilot.db")
    fact.executescript(
        """
        CREATE TABLE fact(entity_id TEXT, atom TEXT, dims TEXT, period_start TEXT,
                          period_end TEXT, value REAL, unit TEXT, known_at TEXT,
                          source_ref TEXT);
        """
    )
    fact.executemany("INSERT INTO fact VALUES (?,?,?,?,?,?,?,?,?)", FACT_ROWS)
    fact.commit()
    fact.close()

    claims = _connect(v4 / "v4.db")
    claims.executescript(
        """
        CREATE TABLE claim(claim_id INTEGER, entity_id TEXT, topic TEXT, direction TEXT,
                           magnitude REAL, unit TEXT, horizon TEXT, certainty TEXT,
                           quote TEXT, page_no INT, doc_id TEXT, doctype TEXT,
                           known_at TEXT);
        """
    )
    claims.commit()
    claims.close()

    market = _connect(root / "market.db")
    market.executescript(
        """
        CREATE TABLE daily_price_delivery(date TEXT, symbol TEXT, isin TEXT, series TEXT,
                                          close REAL, deliverable_volume INTEGER,
                                          delivery_pct REAL);
        CREATE TABLE mkt_bse_eq_daily(date TEXT, sc_code TEXT, isin TEXT, symbol TEXT,
                                      close REAL);
        CREATE TABLE mkt_bse_delivery_daily(date TEXT, sc_code TEXT,
                                            deliverable_qty INTEGER, delivery_pct REAL);
        """
    )
    market.executemany(
        "INSERT INTO daily_price_delivery(date, isin, symbol, series, close, "
        "deliverable_volume, delivery_pct) VALUES (?,?,?,'EQ',?,?,?)", NSE_PANEL)
    market.executemany(
        "INSERT INTO mkt_bse_eq_daily VALUES (?,?,?,NULL,?)",
        [(date, code, isin, close) for date, code, isin, close, _, _ in BSE_PANEL])
    market.executemany(
        "INSERT INTO mkt_bse_delivery_daily VALUES (?,?,?,?)",
        [(date, code, qty, pct) for date, code, _, _, qty, pct in BSE_PANEL])
    market.commit()
    market.close()


@pytest.fixture()
def engine() -> Iterator[SimpleNamespace]:
    # `.tmp/` in the checkout is writable under the worker sandbox; tmp_path's root may not
    # be listable (same reason as test_v4_run.py).
    root = REPO / ".tmp" / f"proto3-{uuid.uuid4().hex[:10]}"
    _build(root)
    stores = run.Stores(root / "v4", market=root / "market.db")
    resolver = run.Resolver(SYMBOLS, {"Bajaj Finance Limited": BAJ,
                                      "Hindalco Industries Limited": HIND,
                                      "KEC International Limited": KEC},
                            {BAJ, HIND, KEC})
    yield SimpleNamespace(stores=stores, resolver=resolver, root=root)
    stores.close()


def bank_case(mid: str) -> dict:
    """The real bank row, never a reworded question."""
    for line in BANK.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            if row.get("mid") == mid:
                return row
    raise AssertionError(f"{mid} is not in {BANK.name}")


def run_mid(engine: SimpleNamespace, mid: str) -> dict:
    return run.run_case(bank_case(mid), engine.stores, engine.resolver)


def result_for(row: dict, atom: str, **dims) -> dict:
    """The one result of ``atom`` whose dims hold every named value (and only those)."""
    found = []
    for result in row["results"]:
        if result.get("atom") != atom:
            continue
        got = {key: str(value) for key, value in (result.get("dims") or {}).items()}
        if all(str(got.get(key)) == str(value) for key, value in dims.items()):
            found.append(result)
    assert len(found) == 1, [r.get("dims") for r in row["results"]]
    return found[0]


# --- the YTD high: value, date, exchange ------------------------------------
@pytest.mark.parametrize("mid", ["MB0028#L", "MB0301#L"])
def test_ytd_high_is_the_stores_extreme(engine, mid):
    row = run_mid(engine, mid)
    result = result_for(row, "price.high")
    assert result["answer_type"] == "measured", result.get("nid_reason")
    con = _connect(engine.root / "v4" / "fact_v4_pilot.db")
    expected = con.execute(
        "SELECT value, period_end, dims FROM fact WHERE atom = 'price.high' "
        "AND entity_id = ? AND period_end BETWEEN '2026-01-01' AND '2026-10-19' "
        "ORDER BY value DESC LIMIT 1", (BAJ,)).fetchone()
    con.close()
    assert expected is not None and expected["value"] == pytest.approx(1_176.4)
    assert result["value"] == pytest.approx(expected["value"])
    assert result["period"] == expected["period_end"] == "2026-08-03"
    # MB0301 asks which exchange: the extreme names the row it came from.
    exchange = str(expected["dims"]).split("=", 1)[1]
    assert result["numbers"]["exchange"] == exchange
    assert f"exchange of the extreme: {exchange}" in row["answer"]


# --- the traded close and its basis -----------------------------------------
@pytest.mark.parametrize("mid,isin", [("MB0032#L", HIND), ("MB0040#L", BAJ)])
def test_close_level_is_the_traded_close_with_its_basis(engine, mid, isin):
    row = run_mid(engine, mid)
    result = result_for(row, "price.close")
    assert result["answer_type"] == "measured", result.get("nid_reason")
    assert result["period"] == "2026-10-16"
    con = _connect(engine.root / "market.db")
    traded = con.execute("SELECT close FROM daily_price_delivery WHERE isin = ? AND "
                         "date = '2026-10-16'", (isin,)).fetchone()
    con.close()
    fact = _connect(engine.root / "v4" / "fact_v4_pilot.db")
    stored = fact.execute(
        "SELECT value FROM fact WHERE atom = 'price.close' AND entity_id = ? AND "
        "period_end = '2026-10-16'", (isin,)).fetchone()
    fact.close()
    assert traded is not None and stored is not None
    assert result["value"] == pytest.approx(traded["close"])
    assert result["numbers"]["close_basis"] == "raw"
    assert "traded NSE close" in (result.get("assumption") or "")
    # the fact store's level is the adjusted series: reported beside the traded close
    assert result["numbers"]["store_close"] == pytest.approx(stored["value"])
    assert result["numbers"]["store_close_basis"] == "adjusted"
    assert result["source_ref"].endswith("daily_price_delivery")


# --- delivered quantity: per exchange and combined, never the traded volume --
@pytest.mark.parametrize("mid,isin", [("MB0231#L", BAJ), ("MB0232#L", HIND)])
def test_delivery_reads_both_exchanges_never_the_traded_volume(engine, mid, isin):
    row = run_mid(engine, mid)
    market = _connect(engine.root / "market.db")
    nse = {r["date"]: r["deliverable_volume"] for r in market.execute(
        "SELECT date, deliverable_volume FROM daily_price_delivery WHERE isin = ? "
        "AND date BETWEEN '2026-09-21' AND '2026-09-22'", (isin,))}
    bse_rows = {r["date"]: r["deliverable_qty"] for r in market.execute(
        "SELECT e.date AS date, dv.deliverable_qty FROM mkt_bse_eq_daily e JOIN "
        "mkt_bse_delivery_daily dv ON dv.sc_code = e.sc_code AND dv.date = e.date "
        "WHERE e.isin = ? AND e.date BETWEEN '2026-09-21' AND '2026-09-22'", (isin,))}
    market.close()
    assert nse and bse_rows

    nse_result = result_for(row, "price.delivery_qty", exchange="NSE")
    bse_result = result_for(row, "price.delivery_qty", exchange="BSE")
    total_result = result_for(row, "price.delivery_qty", exchange="sum")
    for result in (nse_result, bse_result, total_result):
        assert result["answer_type"] == "measured", result.get("nid_reason")
        # both named dates are answered, not only the last session of the window
        assert result["shape"] == "series", result["shape"]
    # each reading is read back from the panel, per session
    assert {row["period"]: row["value"] for row in nse_result["values"]} == {
        day: pytest.approx(value) for day, value in nse.items()}
    assert {row["period"]: row["value"] for row in bse_result["values"]} == {
        day: pytest.approx(value) for day, value in bse_rows.items()}
    assert {row["period"]: row["value"] for row in total_result["values"]} == {
        day: pytest.approx(nse[day] + bse_rows[day]) for day in nse}
    # the rendered answer names both sessions, not only the last one
    assert "2026-09-21=" in row["answer"] and "2026-09-22=" in row["answer"]

    # the question rules the traded volume out: that reading must not be answered
    volume = [result for result in row["results"] if result.get("atom") == "price.volume"]
    assert volume
    for result in volume:
        assert result["answer_type"] == "not_in_data"
        assert "rules" in (result.get("nid_reason") or "")
    # no part of this row answers with a passage about something else
    assert not [result for result in row["results"]
                if result.get("shape") == "passage" and result["answer_type"] == "measured"]


# --- a split of the order book is not its total ------------------------------
@pytest.mark.parametrize("mid", ["MB0550#MS", "MB0544#MS"])
def test_order_book_split_is_refused_not_answered_by_the_total(engine, mid):
    row = run_mid(engine, mid)
    result = result_for(row, "fin.order_book")
    assert result["answer_type"] == "not_in_data", result
    assert result["value"] is None
    reason = result.get("nid_reason") or ""
    assert "fin.order_book" in reason and "split" in reason
    # the fixture holds a KEC order-book total; the refusal must not be a hidden read of it
    assert "38,000" not in row["answer"] and "38000" not in row["answer"]
    assert result["numbers"] == {}
