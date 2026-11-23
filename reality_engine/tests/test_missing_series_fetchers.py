"""Offline tests for the missing-series fetchers (F&O bhavcopy, equity gaps, commodities).

Every parser is exercised against a fixture file in
``reality_engine/tests/fixtures/missing_series/``. No test makes a network
call, opens a live database, or writes outside ``tempfile``.

    python -m unittest reality_engine.tests.test_missing_series_fetchers
"""

import csv
import io
import sqlite3
import unittest
import uuid
import zipfile
from contextlib import redirect_stdout
from datetime import date, timedelta
from pathlib import Path

from reality_engine.db.readonly import connect_ro
from reality_engine.processing import factor_loaders
from reality_engine.scripts import fetch_commodity_series as commodity
from reality_engine.scripts import fetch_eq_bhavcopy_gaps as gaps
from reality_engine.scripts import fetch_fo_bhavcopy as fo

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "missing_series"

#: Scratch space for the tests. ``tempfile.TemporaryDirectory`` is not used:
#: the DSH workspace sandbox grants writes but denies the recursive delete, so
#: its finaliser raises PermissionError on Windows (SANDBOX.md), and a dir
#: created by ``mkdtemp`` does not inherit the write ACL for its children.
#: Names are made unique instead of deleted, so a re-run never reads stale rows.
TMP_ROOT = Path.cwd() / ".tmp" / "missing_series_tests"


def _tmpdir(name: str) -> Path:
    d = TMP_ROOT / f"{name}_{uuid.uuid4().hex[:8]}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _zip_bytes(name: str, payload: bytes) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(name, payload)
    return buf.getvalue()


def _legacy_zip() -> bytes:
    return _zip_bytes("fo01JAN2019bhav.csv",
                      (FIXTURES / "fo_bhavcopy_legacy.csv").read_bytes())


def _udiff_zip() -> bytes:
    # Real UDiFF downloads start with a UTF-8 BOM; the parser must strip it.
    return _zip_bytes("BhavCopy_NSE_FO_0_0_0_20261023_F_0000.csv",
                      b"\xef\xbb\xbf" + (FIXTURES / "fo_bhavcopy_udiff.csv").read_bytes())


def _weekday_on_or_after(d: date, weekday: int) -> date:
    while d.weekday() != weekday:
        d += timedelta(days=1)
    return d


# ---------------------------------------------------------------------------
# F&O bhavcopy
# ---------------------------------------------------------------------------
class TestFoBhavcopyParser(unittest.TestCase):
    def test_legacy_rows(self):
        rows = fo.parse_fo_bhavcopy(_legacy_zip(), "2019-01-01")
        self.assertEqual(len(rows), 3)
        fut, call, put = rows
        self.assertEqual(list(fut), list(fo.TIDY_COLUMNS))
        self.assertEqual((fut["symbol"], fut["instrument"]), ("NIFTY", "FUTIDX"))
        self.assertEqual(fut["option_type"], "FUT")          # XX -> FUT
        self.assertEqual(fut["expiry"], "2019-01-31")        # DD-MMM-YYYY -> ISO
        self.assertAlmostEqual(fut["strike"], 0.0)
        self.assertAlmostEqual(fut["close"], 10900.0)
        self.assertAlmostEqual(fut["settle"], 10920.35)
        self.assertAlmostEqual(fut["oi"], 12345678.0)
        self.assertAlmostEqual(fut["oi_change"], 345678.0)
        self.assertAlmostEqual(fut["contracts"], 145230.0)
        # VAL_INLAKH is lakhs; the tidy column is rupees.
        self.assertAlmostEqual(fut["value_inr"], 1584320.5 * 100_000.0)
        self.assertIsNone(fut["isin"])                       # legacy files carry no ISIN
        self.assertEqual(fut["date"], "2019-01-01")          # caller's session date
        self.assertEqual(call["option_type"], "CE")
        self.assertEqual(put["option_type"], "PE")           # PA -> PE

    def test_udiff_rows(self):
        rows = fo.parse_fo_bhavcopy(_udiff_zip())
        self.assertEqual(len(rows), 2)
        fut, opt = rows
        self.assertEqual(fut["date"], "2026-10-23")          # from TradDt
        self.assertEqual(fut["symbol"], "RELIANCE")
        self.assertEqual(fut["instrument"], "STF")
        self.assertEqual(fut["option_type"], "FUT")          # blank -> FUT
        self.assertIsNone(fut["strike"])
        self.assertEqual(fut["expiry"], "2026-10-29")
        self.assertEqual(fut["isin"], "INE002A01018")
        self.assertAlmostEqual(fut["value_inr"], 13920000000.5)
        self.assertAlmostEqual(opt["strike"], 1400.0)
        self.assertEqual(opt["option_type"], "CE")
        self.assertAlmostEqual(opt["oi"], 456789.0)

    def test_unknown_layout_yields_no_rows(self):
        payload = _zip_bytes("x.csv", b"DATE,FOO\n2026-10-23,1\n")
        self.assertEqual(fo.parse_fo_bhavcopy(payload), [])

    def test_html_error_page_is_not_a_file(self):
        self.assertFalse(fo._valid_fo_zip(b"<!DOCTYPE html><html>blocked</html>"))


class TestFoUrls(unittest.TestCase):
    def test_legacy_url(self):
        d = date(2019, 1, 1)
        self.assertEqual(fo.fo_filename(d), "fo01JAN2019bhav.csv.zip")
        self.assertIn("/content/historical/DERIVATIVES/2019/JAN/", fo.fo_url(d))

    def test_udiff_url(self):
        d = date(2026, 10, 23)
        self.assertEqual(fo.fo_filename(d), "BhavCopy_NSE_FO_0_0_0_20261023_F_0000.csv.zip")
        self.assertEqual(fo.fo_url(d),
                         "https://nsearchives.nseindia.com/content/fo/"
                         "BhavCopy_NSE_FO_0_0_0_20261023_F_0000.csv.zip")


class TestFoPlan(unittest.TestCase):
    def test_plan_counts_and_dry_run_touches_nothing(self):
        out = TMP_ROOT / "fo_plan_absent"
        stats = fo.plan(date(2024, 7, 1), date(2024, 7, 31), out, 0.4)
        self.assertEqual(stats["sessions"], 23)          # July 2024 weekdays
        self.assertEqual(stats["requests"], 23)
        self.assertEqual(stats["already_ok"], 0)
        self.assertEqual(stats["legacy_files"], 5)       # 1-5 Jul, old columns
        self.assertEqual(stats["udiff_files"], 18)       # 8-31 Jul, UDiFF
        self.assertGreater(stats["est_minutes_p50"], 0)
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.assertEqual(fo.main(["--dry-run", "--out", str(out),
                                      "--from", "2024-07-01", "--to", "2024-07-31"]), 0)
        self.assertIn("dry-run: no request made", buf.getvalue())
        self.assertFalse(out.exists())                   # plan wrote nothing


# ---------------------------------------------------------------------------
# Equity bhavcopy gaps
# ---------------------------------------------------------------------------
def _make_price_db(path: Path) -> dict:
    """A trimmed equity_intelligence.db: calendar + bhavcopy tables + symbol history."""
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE mkt_nse_index_daily(date TEXT, index_name TEXT);
        CREATE TABLE mkt_nse_eq_daily(date TEXT, symbol TEXT, series TEXT);
        CREATE TABLE mkt_nse_full_daily(date TEXT, symbol TEXT, series TEXT);
        CREATE TABLE mkt_bse_eq_daily(date TEXT, sc_code TEXT);
        CREATE TABLE mkt_nse_sme_daily(date TEXT, symbol TEXT, series TEXT);
        CREATE TABLE symbol_isin_history(exchange TEXT, symbol TEXT, isin TEXT,
                                         first_date TEXT, last_date TEXT);
    """)
    mon = _weekday_on_or_after(date(2026, 10, 19), 0)
    tue, wed = mon + timedelta(days=1), mon + timedelta(days=2)
    sat = _weekday_on_or_after(mon, 5)
    sun = sat + timedelta(days=1)
    for d in (mon, tue, wed, sat, sun):                       # index bhavcopy every "session"
        con.execute("INSERT INTO mkt_nse_index_daily VALUES (?,?)", (d.isoformat(), "NIFTY 50"))
    for d in (mon, wed):                                      # Tuesday is the gap
        con.execute("INSERT INTO mkt_nse_full_daily VALUES (?,?,?)", (d.isoformat(), "HELDCO", "EQ"))
    con.execute("INSERT INTO symbol_isin_history VALUES ('NSE','HELDCO','INE00','2019-01-01','2026-10-19')")
    con.execute("INSERT INTO symbol_isin_history VALUES ('NSE','GONECO','INE01','2019-01-01','2021-10-31')")
    con.execute("INSERT INTO symbol_isin_history VALUES ('BSE','BSEONLY','INE02','2019-01-01','2026-10-19')")
    con.commit()
    con.close()
    return {"mon": mon, "tue": tue, "wed": wed, "sat": sat, "sun": sun}


class TestEquityBhavcopyGaps(unittest.TestCase):
    def setUp(self):
        self.db = _tmpdir("eq_gaps") / "equity_intelligence.db"
        self.days = _make_price_db(self.db)
        self.con = connect_ro(self.db, timeout_s=10)

    def tearDown(self):
        self.con.close()

    def test_gap_dates_splits_weekday_sessions_from_weekend_calendar_rows(self):
        real, suspect = gaps.gap_dates(self.con)
        self.assertEqual(real, [self.days["tue"].isoformat()])
        self.assertEqual(suspect, [self.days["sat"].isoformat(),
                                   self.days["sun"].isoformat()])

    def test_held_tables_are_unioned(self):
        with sqlite3.connect(self.db) as writer:            # the connection under test is ro
            writer.execute("INSERT INTO mkt_bse_eq_daily VALUES (?,?)",
                           (self.days["tue"].isoformat(), "500001"))
        real, _suspect = gaps.gap_dates(self.con)
        self.assertEqual(real, [])

    def test_name_gaps_are_bounded_to_nse_symbols_without_bhavcopy(self):
        names = gaps.name_gaps(self.con)
        self.assertEqual([n["symbol"] for n in names], ["GONECO"])

    def test_name_gap_dates_clipped_to_window(self):
        dates = gaps.name_gap_dates(
            [{"symbol": "GONECO", "first_date": "2021-10-28", "last_date": "2021-11-02"}])
        self.assertEqual([d.isoformat() for d in dates],
                         ["2021-10-28", "2021-10-29", "2021-11-01", "2021-11-02"])

    def test_dry_run_plans_without_fetching(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = gaps.main(["--dry-run", "--db", str(self.db)])
        out = buf.getvalue()
        self.assertEqual(rc, 0)
        self.assertIn("date gaps (weekday sessions)   1", out)
        self.assertIn("calendar rows not sessions     2", out)
        self.assertIn("dry-run: no request made", out)


# ---------------------------------------------------------------------------
# Commodity series
# ---------------------------------------------------------------------------
class TestPinkSheetMatchers(unittest.TestCase):
    #: The Pink Sheet's own label -> the normalised form our matcher must equal.
    LABELS = {
        "Crude oil, average": "crude_oil_average",
        "Crude oil, Brent": "crude_oil_brent",
        "Crude oil, WTI": "crude_oil_wti",
        "Natural gas, US": "natural_gas_us",
        "Natural gas, Europe": "natural_gas_europe",
        "Coal, Australian": "coal_australian",
        "Coal, South African": "coal_south_african",
        "Aluminium": "aluminium",
        "Copper": "copper",
        "Lead": "lead",
        "Nickel": "nickel",
        "Tin": "tin",
        "Zinc": "zinc",
        "Iron ore, cfr spot": "iron_ore_cfr_spot",
        "Gold": "gold",
        "Silver": "silver",
        "Platinum": "platinum",
        "Cotton, A Index": "cotton_a_index",
        "Rubber, RSS3": "rubber_rss3",
        "Palm oil": "palm_oil",
        "Soybean oil": "soybean_oil",
        "Urea": "urea",
        "DAP": "dap",
        "Steel": "steel",
    }

    def test_every_matcher_names_a_real_column(self):
        wanted = {h for _code, h in commodity.PINK_MATCHERS}
        self.assertEqual(wanted, set(self.LABELS.values()))

    def test_normalised_labels_match_the_matchers(self):
        for label, expected in self.LABELS.items():
            self.assertEqual(factor_loaders._normalise_header(label), expected, label)


class TestPinkRows(unittest.TestCase):
    def _parsed(self, **over):
        base = {
            "status": "ok",
            "as_of_date": "2026-09-02",
            "units": {"wb_copper": "$/mt", "wb_gold": "$/toz"},
            "rows": [
                {"period": "2026M07", "period_start": "2026-07-01",
                 "period_end": "2026-07-31", "values": {"wb_copper": 9750.5, "wb_gold": None}},
                {"period": "2026M08", "period_start": "2026-08-01",
                 "period_end": "2026-08-31", "values": {"wb_copper": 9910.0, "wb_gold": 2450.25}},
            ],
        }
        base.update(over)
        return base

    def test_known_at_is_the_workbook_date(self):
        rows = commodity.pink_rows(self._parsed())
        self.assertEqual(len(rows), 3)                       # None values are dropped
        self.assertEqual({r["known_at"] for r in rows}, {"2026-09-02"})
        self.assertEqual({r["pit_conf"] for r in rows}, {1.0})
        copper = [r for r in rows if r["series_code"] == "wb_copper"]
        self.assertEqual([r["date"] for r in copper], ["2026-07-31", "2026-08-31"])
        self.assertEqual(copper[0]["unit"], "$/mt")

    def test_no_workbook_date_is_refused_not_dated_today(self):
        self.assertEqual(commodity.pink_rows(self._parsed(as_of_date=None)), [])
        self.assertEqual(commodity.pink_rows(self._parsed(status="refused")), [])


class TestFredParser(unittest.TestCase):
    def test_parse_and_skip_missing(self):
        payload = (FIXTURES / "fred_DCOILBRENTEU.csv").read_bytes()
        self.assertEqual(commodity.parse_fred_csv(payload, "DCOILBRENTEU"),
                         [("2026-10-21", 61.25), ("2026-10-23", 62.40)])

    def test_known_at_rolls_forward_over_the_weekend(self):
        rows = commodity.fred_rows((FIXTURES / "fred_DCOILBRENTEU.csv").read_bytes(),
                                   "DCOILBRENTEU")
        by_date = {r["date"]: r["known_at"] for r in rows}
        # Wednesday + 1 day = Thursday; Friday + 1 day = Saturday -> Monday.
        self.assertEqual(by_date["2026-10-21"], "2026-10-22")
        self.assertEqual(by_date["2026-10-23"], "2026-10-26")
        self.assertEqual({r["series_code"] for r in rows}, {"fred_crude_brent_d"})
        self.assertEqual({r["pit_conf"] for r in rows}, {0.85})


class TestRbiParser(unittest.TestCase):
    def test_rows_from_the_archive_table(self):
        html = (FIXTURES / "rbi_reference_rate_2026-10.html").read_text()
        self.assertEqual(commodity.parse_rbi_reference_rate(html),
                         [("2026-10-01", 88.1234), ("2026-10-04", 88.2)])

    def test_layout_drift_yields_nothing(self):
        self.assertEqual(commodity.parse_rbi_reference_rate("<html><body>maintenance</body></html>"), [])
        self.assertEqual(commodity.parse_rbi_reference_rate(""), [])

    def test_known_at_is_daily_publication_time(self):
        rows = commodity.rbi_rows((FIXTURES / "rbi_reference_rate_2026-10.html").read_bytes())
        self.assertEqual(rows[0]["known_at"], "2026-10-01T13:00:00+05:30")
        self.assertEqual(rows[0]["unit"], "inr_per_usd")

    def test_month_loop_covers_the_range(self):
        spans = list(commodity.month_starts(date(2026, 1, 15), date(2026, 3, 2)))
        self.assertEqual([(a.isoformat(), b.isoformat()) for a, b in spans],
                         [("2026-01-15", "2026-01-31"), ("2026-02-01", "2026-02-28"),
                          ("2026-03-01", "2026-03-02")])

    def test_form_carries_the_aspnet_state(self):
        html = (FIXTURES / "rbi_reference_rate_2026-10.html").read_text()
        form = commodity.rbi_month_form(html, date(2026, 10, 1), date(2026, 10, 31))
        self.assertEqual(form["__VIEWSTATE"], "/wEPDwUKMTY1NDU2MTA1MmRk")
        self.assertEqual(form["txtFromDate"], "01/10/2026")
        self.assertEqual(form["txtToDate"], "31/10/2026")


class TestSeriesWriter(unittest.TestCase):
    ROWS = [
        {"series_code": "b", "date": "2026-02-01", "close": 2.0, "unit": "$/mt",
         "known_at": "2026-03-02", "pit_conf": 1.0, "source": "worldbank_pink_sheet"},
        {"series_code": "a", "date": "2026-01-31", "close": 1.0, "unit": "$/mt",
         "known_at": "2026-03-02", "pit_conf": 1.0, "source": "worldbank_pink_sheet"},
        {"series_code": "a", "date": "2026-05-31", "close": 3.0, "unit": "$/mt",
         "known_at": "2026-06-02", "pit_conf": 1.0, "source": "worldbank_pink_sheet"},
    ]

    def test_writes_sorted_range_filtered_csv_and_manifest(self):
        out = _tmpdir("writer")
        n = commodity.write_series(out, self.ROWS, "2026-01-01", "2026-03-31")
        self.assertEqual(n, 2)
        with (out / "commodity_series.csv").open(newline="") as f:
            got = list(csv.DictReader(f))
        self.assertEqual([(r["series_code"], r["date"]) for r in got],
                         [("a", "2026-01-31"), ("b", "2026-02-01")])
        with (out / "_manifest.csv").open(newline="") as f:
            manifest = {r["series_code"]: r for r in csv.DictReader(f)}
        self.assertEqual(manifest["a"]["rows"], "1")
        self.assertEqual(manifest["b"]["max_date"], "2026-02-01")

    def test_dry_run_makes_no_request(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.assertEqual(commodity.main(["--dry-run"]), 0)
        out = buf.getvalue()
        self.assertIn("requests", out)
        self.assertIn("dry-run: no request made", out)


if __name__ == "__main__":
    unittest.main()
