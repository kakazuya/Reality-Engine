"""pilot3_tech (T-128): price reaction to a filing and the technicals, computed in code.

Run from the repo root:
    python -m pytest reality_engine/tests/test_pilot3_tech.py -q

The fixture tests build a tiny pilot3.db under ``.tmp/`` from the real DDL (``reality_engine.pilot3.schema``) and point
``REALITY_PILOT3_DB`` at it: no production database, network or model.  The live tests read the pilot10 build at
``D:/RealityEngine/pilot10/pilot10.db`` read-only and skip when it is absent; they pin the 8 Nov hand checks
(ETERNAL day 0 after a 16:02 filing, ETERNAL 3 Feb gap, KEC 26 Oct gap and fill, BAJFINANCE SMA crosses, KEC volume
spikes and HDFCBANK's Wilder RSI).
"""
from __future__ import annotations

import datetime as dt
import os
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SERVER_DIR = ROOT / "plugins" / "reality-data" / "server"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SERVER_DIR))

import core  # noqa: E402
import lookups_pilot3 as p3  # noqa: E402
import lookups_tech as tech_mod  # noqa: E402
from reality_engine.pilot3 import schema  # noqa: E402

TMP = ROOT / ".tmp"
DB = TMP / "pilot3_tech_fixture.db"
LIVE = Path("D:/RealityEngine/pilot10/pilot10.db")
AS_OF = "2026-11-04"
_BUILT = False


def _weekdays(start: str, n: int) -> list[str]:
    day = dt.date.fromisoformat(start)
    out: list[str] = []
    while len(out) < n:
        if day.weekday() < 5:
            out.append(day.isoformat())
        day += dt.timedelta(days=1)
    return out


def _insert_prices(c: sqlite3.Connection, symbol: str, days: list[str], closes: list[float],
                   volumes: list[float] | None = None, delivery: float = 50.0,
                   opens: list[float] | None = None, lows: list[float] | None = None,
                   highs: list[float] | None = None, adj: list[float] | None = None) -> None:
    cols = ("symbol", "exchange", "date", "open", "high", "low", "close", "prev_close", "volume", "delivery_pct",
            "adj_factor", "adj_close", "known_at")
    rows = []
    prev = closes[0]
    for i, day in enumerate(days):
        close = closes[i]
        open_ = opens[i] if opens else prev
        low = lows[i] if lows else min(open_, close) - 0.5
        high = highs[i] if highs else max(open_, close) + 0.5
        row_adj = adj[i] if adj else close
        rows.append((symbol, "NSE", day, open_, high, low, close, prev, volumes[i] if volumes else 1000.0,
                     delivery, 1.0, row_adj, day))
        prev = close
    c.executemany(f"INSERT INTO price_delivery ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", rows)


def build_fixture() -> None:
    global _BUILT
    if _BUILT:
        return
    TMP.mkdir(exist_ok=True)
    for suffix in ("", "-wal", "-shm"):
        Path(str(DB) + suffix).unlink(missing_ok=True)
    c = sqlite3.connect(DB)
    schema.create(c, list(schema.TABLES))
    for sym in ("FIX", "LONG", "UP", "DIV", "RSIEX"):
        c.execute("INSERT INTO company VALUES (?,?,NULL,NULL,NULL,NULL,?)", (sym, f"INE00000{sym[:1]}00{sym}", sym))
    # FIX: 75 sessions from 5 Jan 2026; close 100+i; index 20000 + 10*i per session.
    days = _weekdays("2026-01-05", 75)
    closes = [100.0 + i for i in range(75)]
    opens = [closes[0]] + closes[:-1]
    lows = [min(o, cl) - 0.5 for o, cl in zip(opens, closes)]
    highs = [max(o, cl) + 0.5 for o, cl in zip(opens, closes)]
    # index 40 = 2026-03-02: a 6% gap up that closes +2%; index 43 dips below the pre-gap close.
    closes[40] = 141.78
    opens[40] = 147.34
    lows[40] = 145.34
    highs[40] = 148.84
    lows[43] = 137.61
    volumes = [1000.0] * 75
    volumes[50] = 5000.0
    delivery = [50.0] * 75
    delivery[40] = 100.0
    _insert_prices(c, "FIX", days, closes, volumes=volumes, delivery=50.0, opens=opens, lows=lows, highs=highs)
    c.executemany("UPDATE price_delivery SET delivery_pct=? WHERE symbol='FIX' AND date=?", [(100.0, days[40])])
    c.executemany("INSERT INTO index_price (symbol, index_name, date, index_close, known_at) VALUES (?,?,?,?,?)",
                  [("FIX", "Nifty 50", day, 20000.0 + 10.0 * i, day) for i, day in enumerate(days)])
    for key, dtype, title, filing, known in [
        ("FIX:results:jan", "results", "Q3 results", "2026-01-21", "2026-01-21T16:02:01"),
        ("FIX:results:feb", "results", "Briefing", "2026-02-10", "2026-02-10T10:00:00"),
        ("FIX:results:sat", "results", "Weekend filing", "2026-02-14", "2026-02-14T11:00:00"),
        ("FIX:results:close", "results", "Filing at the close", "2026-03-02", "2026-03-02T15:30:00"),
        ("FIX:deck:excluded", "deck", "Investor deck", "2026-02-11", "2026-02-11T09:00:00"),
    ]:
        c.execute("INSERT INTO doc (doc_key, symbol, doc_type, title, filing_date, known_at, pages) "
                  "VALUES (?,?,?,?,?,?,1)", (key, "FIX", dtype, title, filing, known))
    # LONG: 240 sessions at 100, 10 at 110, then 10 at 90 -> SMA50/SMA200 cross down on the first 90.
    days = _weekdays("2025-07-01", 260)
    closes = [100.0] * 240 + [110.0] * 10 + [90.0] * 10
    _insert_prices(c, "LONG", days, closes)
    # UP: 40 at 100, 10 at 90, 15 at 110 -> SMA50 crosses up on the first 110; SMA200 has no history.
    days = _weekdays("2026-05-04", 65)
    closes = [100.0] * 40 + [90.0] * 10 + [110.0] * 15
    _insert_prices(c, "UP", days, closes)
    # DIV: a fall, a rise, a dip to 100, a recovery, then a lower low at 95 with a HIGHER RSI: bullish divergence.
    days = _weekdays("2026-05-04", 45)
    closes = ([130.0 - i for i in range(15)] + [118.0 + 2 * i for i in range(6)] + [100.0]
              + [102.0 + 2 * i for i in range(8)] + [95.0] + [105.0 + 2 * i for i in range(14)])
    _insert_prices(c, "DIV", days, closes)
    # RSIEX: 14 gains of 1 then a loss of 2 -> Wilder RSI = 100 - 100/(1+6.5) = 86.67.
    days = _weekdays("2026-05-04", 16)
    closes = [10.0 + i for i in range(15)] + [22.0]
    _insert_prices(c, "RSIEX", days, closes)
    c.commit()
    c.close()
    _BUILT = True


@pytest.fixture(autouse=True)
def fixture_db(monkeypatch):
    build_fixture()
    monkeypatch.setenv("REALITY_PILOT3_DB", str(DB))
    p3.close()
    yield
    p3.close()


@pytest.fixture()
def live(monkeypatch):
    if not LIVE.is_file():
        pytest.skip(f"live build absent: {LIVE}")
    monkeypatch.setenv("REALITY_PILOT3_DB", str(LIVE))
    p3.close()
    yield LIVE
    p3.close()


# --- fixture tests ----------------------------------------------------------------------------------
def test_reaction_day0_is_the_next_session_after_a_late_filing():
    out = tech_mod.tech("FIX", "reaction", as_of="2026-06-02")
    by_known = {f["known_at"]: f for f in out["rows"]}
    late = by_known["2026-01-21T16:02:01"]
    assert late["day0"] == "2026-01-22"
    assert "after the 15:30 close" in late["day0_rule"]
    early = by_known["2026-02-10T10:00:00"]
    assert early["day0"] == "2026-02-10"
    assert "same session" in early["day0_rule"]
    at_close = by_known["2026-03-02T15:30:00"]
    assert at_close["day0"] == "2026-03-02"
    weekend = by_known["2026-02-14T11:00:00"]
    assert weekend["day0"] == "2026-02-16"
    assert "not a trading session" in weekend["day0_rule"]
    assert "2026-02-11" not in {f["filing_date"] for f in out["rows"]}  # doc_type default is results


def test_reaction_rows_and_cumulative():
    out = tech_mod.tech("FIX", "reaction", as_of="2026-06-02", sessions=5)
    late = [f for f in out["rows"] if f["known_at"] == "2026-01-21T16:02:01"][0]
    assert len(late["rows"]) == 6  # day 0 through day 5
    day0 = late["rows"][0]
    assert day0["date"] == "2026-01-22" and day0["day"] == 0
    assert day0["ret_pct"] == pytest.approx(0.89, abs=0.01)   # 113 / 112 - 1
    assert day0["cum_pct"] == pytest.approx(0.89, abs=0.01)
    assert day0["volume_multiple"] == pytest.approx(1.0, abs=0.01)  # 20 sessions before are all 1000
    assert day0["index_pct"] == pytest.approx(0.05, abs=0.01)
    assert day0["provenance"] == {"table": "price_delivery", "source": "NSE 2026-01-22",
                                  "known_at": "2026-01-22"}
    assert late["cum_1d_pct"] == pytest.approx(0.89, abs=0.01)
    assert late["cum_5s_pct"] == pytest.approx(late["rows"][4]["cum_pct"])
    assert late["cum_window_pct"] == pytest.approx(late["rows"][-1]["cum_pct"])


def test_gaps_gap_held_and_fill_are_vs_the_previous_close():
    out = tech_mod.tech("FIX", "gaps", as_of="2026-06-02", threshold=0.03)
    row = [r for r in out["rows"] if r["date"] == "2026-03-02"][0]
    assert row["direction"] == "up"
    assert row["gap_pct"] == pytest.approx(6.0, abs=0.01)            # 147.34 / 139
    assert row["close_ret_pct"] == pytest.approx(2.0, abs=0.01)      # 141.78 / 139, NOT close vs open
    assert row["held"] == pytest.approx(1.0 / 3.0, abs=0.001)        # (141.78-139)/(147.34-139)
    assert row["held_pct"] == pytest.approx(33.33, abs=0.05)
    assert row["fill_date"] == _weekdays("2026-01-05", 75)[43]
    assert row["fill_price"] == pytest.approx(137.61)
    assert row["delivery_pct"] == pytest.approx(100.0)
    assert row["delivery_mean_250"] == pytest.approx(50.0)
    assert row["delivery_ratio"] == pytest.approx(2.0, abs=0.01)
    none = tech_mod.tech("FIX", "gaps", as_of="2026-06-02", threshold=0.20)
    assert none["found"] is True and none["n"] == 0 and "no session gapped" in none["note"]


def test_rsi_is_wilder_14_on_adjusted_close():
    out = tech_mod.tech("RSIEX", "rsi", as_of="2026-06-02")
    assert out["method"] == "Wilder 14 on adjusted close"
    assert out["rsi"] == 86.67  # avg_gain 13/14, avg_loss 2/14 -> 100 - 100/7.5
    assert out["series"][-1]["rsi"] == 86.67
    assert len(out["series"]) == 2  # only two sessions in this series have a 14-change history
    bullish = tech_mod.tech("DIV", "rsi", as_of="2026-07-10", window=30)
    assert bullish["divergence"]["bullish_divergence"] is True
    low_old, low_new = bullish["divergence"]["lows"]
    assert low_new["adj_close"] < low_old["adj_close"] and low_new["rsi"] > low_old["rsi"]


def test_ma_crosses_and_insufficient_history():
    long_out = tech_mod.tech("LONG", "ma", as_of="2026-11-04")
    by_period = {r["period"]: r for r in long_out["rows"]}
    assert by_period[50]["value"] == pytest.approx(100.0)     # last 50: 30 at 100, 10 at 110, 10 at 90
    assert by_period[200]["value"] == pytest.approx(100.0)
    assert by_period[50]["pct_vs_sma"] == pytest.approx(-10.0)
    assert by_period[50]["last_cross"] == _weekdays("2025-07-01", 260)[250]
    assert by_period[50]["last_cross_direction"] == "down"
    assert by_period[200]["last_cross"] == _weekdays("2025-07-01", 260)[250]
    assert by_period[200]["last_cross_direction"] == "down"
    assert by_period[50]["pct_vs_sma"] < 0
    up_out = tech_mod.tech("UP", "ma", as_of="2026-11-04")
    up = {r["period"]: r for r in up_out["rows"]}
    assert up[50]["last_cross"] == _weekdays("2026-05-04", 65)[50]
    assert up[50]["last_cross_direction"] == "up"
    assert up[200]["insufficient_history"] is True


def test_volume_spikes_compare_with_the_prior_20_sessions():
    out = tech_mod.tech("FIX", "volume_spikes", as_of="2026-06-02", threshold=3)
    assert out["n"] == 1
    row = out["rows"][0]
    assert row["date"] == _weekdays("2026-01-05", 75)[50]
    assert row["multiple"] == pytest.approx(5.0)
    assert row["delivery_pct"] == pytest.approx(50.0)
    none = tech_mod.tech("FIX", "volume_spikes", as_of="2026-06-02", threshold=50)
    assert none["found"] is True and none["n"] == 0 and "no session traded" in none["note"]


def test_range_position():
    out = tech_mod.tech("FIX", "range", as_of="2026-06-02")
    row = out["rows"][0]
    days = _weekdays("2026-01-05", 75)
    assert row["high_date"] == days[-1] and row["low_date"] == days[0]
    assert row["high"] == pytest.approx(174.0) and row["low"] == pytest.approx(100.0)
    assert row["position"] == pytest.approx(1.0)
    assert row["pct_above_low"] == pytest.approx(74.0)
    assert row["pct_below_high"] == pytest.approx(0.0)


def test_as_of_drops_later_sessions():
    out = tech_mod.tech("FIX", "gaps", as_of="2026-02-25", threshold=0.03)
    assert all(r["date"] <= "2026-02-25" for r in out["rows"])
    ma = tech_mod.tech("FIX", "ma", as_of="2026-02-25")
    assert ma["close_date"] == "2026-02-25"


def test_unknown_symbol_and_kind_raise_not_found():
    with pytest.raises(core.DataError):
        tech_mod.tech("NO_SUCH_COMPANY", "reaction")
    with pytest.raises(core.DataError):
        tech_mod.tech("FIX", "nonsense")


# --- live checks on the pilot10 build (8 Nov hand checks) -------------------------------------------
def test_live_eternal_results_filed_at_1602_react_next_session(live):
    out = tech_mod.tech("ETERNAL", "reaction", as_of=AS_OF, limit=10)
    jan = [f for f in out["rows"] if f["known_at"].startswith("2026-01-21")][0]
    assert jan["day0"] == "2026-01-22"


def test_live_eternal_gap_3_feb(live):
    out = tech_mod.tech("ETERNAL", "gaps", as_of=AS_OF, start="2026-01-01", end="2026-02-10", threshold=0.02)
    row = [r for r in out["rows"] if r["date"] == "2026-02-03"][0]
    assert row["gap_pct"] == pytest.approx(7.83, abs=0.01)
    assert row["close_ret_pct"] == pytest.approx(2.62, abs=0.01)  # vs the previous close, not vs the open
    assert row["held_pct"] == pytest.approx(33.49, abs=0.05)


def test_live_kec_gap_up_on_26_oct_fills_on_30_oct(live):
    out = tech_mod.tech("KEC", "gaps", as_of=AS_OF)
    row = [r for r in out["rows"] if r["date"] == "2026-10-26"][0]
    assert row["gap_pct"] == pytest.approx(3.43, abs=0.01)
    assert row["fill_date"] == "2026-10-30"
    assert row["fill_price"] == pytest.approx(327.30, abs=0.01)


def test_live_bajfinance_smas_and_last_crosses(live):
    out = tech_mod.tech("BAJFINANCE", "ma", as_of=AS_OF)
    by_period = {r["period"]: r for r in out["rows"]}
    assert out["close"] == pytest.approx(970.0)
    assert round(by_period[50]["value"], 1) == 999.4
    assert round(by_period[200]["value"], 1) == 972.4
    assert by_period[50]["last_cross"] == "2026-08-31"
    assert by_period[50]["last_cross_direction"] == "down"
    assert by_period[200]["last_cross"] == "2026-10-19"
    assert by_period[200]["last_cross_direction"] == "down"


def test_live_kec_volume_spikes(live):
    out = tech_mod.tech("KEC", "volume_spikes", as_of=AS_OF, threshold=3)
    assert out["n"] == 18
    by_date = {r["date"]: r for r in out["rows"]}
    assert min(by_date) >= "2025-11-04"
    assert by_date["2025-11-11"]["multiple"] == pytest.approx(13.01, abs=0.01)
    assert by_date["2026-10-09"]["multiple"] == pytest.approx(13.91, abs=0.01)


def test_live_hdfcbank_rsi(live):
    out = tech_mod.tech("HDFCBANK", "rsi", as_of=AS_OF)
    assert out["rsi_date"] == "2026-11-03"
    assert 55 < out["rsi"] < 62
    assert out["rsi"] == 58.44  # the 5 Nov hand check gave 58.4; 58.44 is the same figure at 2 dp
    assert out["method"] == "Wilder 14 on adjusted close"
