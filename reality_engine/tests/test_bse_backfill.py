"""BSE Bhavcopy backfill tests.

Runs against a fresh temp-file SQLite DB (never the live equity_intelligence.db)
with injected fetchers and a fake HTTP session, so no network and no production
writes. Verifies the UDiFF parse, change_pct math, blank/float tolerance,
FK-safe unknown-ISIN handling, NSE-row preservation, idempotency, dry-run and
per-date isolation — plus the content guard (a BSE soft-fail body is never
parsed, never cached, and never reaches the DB), the legacy EQ<DDMMYY>.CSV ZIP
path with its SC_CODE join, and the unified ``backfill_bse`` entry point.
"""

import contextlib
import io
import json
import shutil
import tempfile
import unittest
import zipfile
from datetime import datetime
from importlib import import_module
from pathlib import Path
from unittest import mock

import pandas as pd

# NOTE: `import reality_engine.ingestion.bse_client as bse` would bind the
# *singleton client instance*, because reality_engine.ingestion.__init__ exports
# the same name (package attributes shadow submodule attributes for `import x.y
# as z`). Resolve the real module through sys.modules instead.
bse = import_module("reality_engine.ingestion.bse_client")
from reality_engine.db.database import DatabaseManager
from reality_engine.pipeline import bse_backfill
from reality_engine.pipeline.bse_backfill import (
    _norm_code,
    backfill_bse,
    backfill_bse_range,
    backfill_legacy_range,
    fetch_legacy_zip,
    parse_bhavcopy_frame,
    parse_legacy_frame,
)

# UDiFF CM header as published by BSE (trailing comma included on purpose).
_HEADER = (
    "TradDt,BizDt,Sgmt,Src,FinInstrmTp,FinInstrmId,ISIN,TckrSymb,SctySrs,XpryDt,"
    "FininstrmActlXpryDt,StrkPric,OptnTp,FinInstrmNm,OpnPric,HghPric,LwPric,ClsPric,"
    "LastPric,PrvsClsgPric,UndrlygPric,SttlmPric,OpnIntrst,ChngInOpnIntrst,TtlTradgVol,"
    "TtlTrfVal,TtlNbOfTxsExctd,SsnId,NewBrdLotQty,Rmks,"
)

# Row 1: known ISIN, valid prices.
_ROW_KNOWN = (
    "2026-09-18,2026-09-18,CM,BSE,STK,544516,INE0XBS01012,AIRFLOA,M,,,,,"
    "AIRFLOA RAIL TECHNOLOGY LIMITE,555.00,587.90,551.00,584.20,585.05,547.30,,584.20,,,"
    "120000,6888000.00,688,,,"
)
# Row 2: ISIN absent from master_companies -> counted, never inserted.
_ROW_UNKNOWN = (
    "2026-09-18,2026-09-18,CM,BSE,STK,999999,INE0UNKNOWN01,ZZZUNK,A,,,,,"
    "ZZZ UNKNOWN LTD,10.00,12.00,9.50,11.00,11.10,10.50,,11.00,,,5000,55000,50,,,"
)
# Row 3: known ISIN but blank/'-' close -> no price history, dropped.
_ROW_BLANK = (
    "2026-09-18,2026-09-18,CM,BSE,STK,111111,INE000000002,BLANKCO,B,,,,,"
    "BLANK CO LTD,100.00,101.00,99.00,-,-,100.50,,,0,0,0,,,"
)

_FIXTURE_CSV = "\n".join([_HEADER, _ROW_KNOWN, _ROW_UNKNOWN, _ROW_BLANK]) + "\n"

_KNOWN_ISIN = "INE0XBS01012"
_KNOWN_SYMBOL = "AIRFLOA"
_BLANK_ISIN = "INE000000002"
_SESSION = datetime(2026, 9, 18)

# BSE bodies that come back with HTTP 200 but are NOT the requested data.
_SPA_SHELL = (
    "<!DOCTYPE html><html lang=\"en\" data-critters-container=\"\"><head>"
    "<title>LIVE Stock/Share Market | Indian Stock/Share Market LIVE | BSE SENSEX</title>"
    "</head><body><app-root></app-root></body></html>"
)
_SOFT_404 = "<html><body><%= Response.StatusCode=404 %></body></html>"

# Legacy archive fixture: EQ<DDMMYY>.CSV, no ISIN column.
_LEGACY_HEADER = (
    "SC_CODE,SC_NAME,SC_GROUP,SC_TYPE,OPEN,HIGH,LOW,CLOSE,LAST,PREVCLOSE,"
    "NO_TRADES,NO_OF_SHRS,NET_TURNOV,TDCLOINDI"
)
# 500002 is in master (bse_code), 999999 is not.
_LEGACY_MAPPED = "500002,ABB INDIA LTD,A,,1000.00,1050.00,995.00,1040.00,1040.00,1020.00,1500,12000,12480000.00,"
_LEGACY_UNMAPPED = "999999,NOT IN MASTER LTD,X,,10.00,11.00,9.00,10.50,10.50,10.00,20,300,3150.00,"
_LEGACY_CSV = "\n".join([_LEGACY_HEADER, _LEGACY_MAPPED, _LEGACY_UNMAPPED]) + "\n"

_LEGACY_SESSION = datetime(2024, 4, 18)
_LEGACY_ISIN = "INE117A01022"
_LEGACY_SYMBOL = "ABB"
_LEGACY_CODE = "500002"


class _FakeResponse:
    """Minimal stand-in for a requests/curl_cffi response."""

    def __init__(self, status_code=200, text="", content=None, json_data=None):
        self.status_code = status_code
        self.text = text
        self.content = content if content is not None else text.encode("utf-8")
        self._json_data = json_data

    def json(self):
        if self._json_data is None:
            raise ValueError("no JSON body")
        return self._json_data


class _FakeSession:
    """Records calls; returns a canned response per URL (or one for all URLs)."""

    def __init__(self, response=None, responses=None):
        self.calls = []
        self._response = response
        self._responses = responses or {}

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append({"url": url, "params": params, "headers": headers})
        resp = self._responses.get(url, self._response)
        if resp is None:
            raise AssertionError(f"unexpected BSE URL: {url}")
        return resp


def _legacy_zip_bytes(target: datetime = _LEGACY_SESSION) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"EQ{target.strftime('%d%m%y')}.CSV", _LEGACY_CSV)
    return buf.getvalue()


def _fixture_frame() -> pd.DataFrame:
    df = pd.read_csv(io.StringIO(_FIXTURE_CSV))
    df.columns = df.columns.str.strip()
    return df


def _legacy_frame() -> pd.DataFrame:
    df = pd.read_csv(io.StringIO(_LEGACY_CSV))
    df.columns = df.columns.str.strip()
    return df


class TestBseBackfill(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="bse_backfill_"))
        self.mgr = DatabaseManager(db_path=self.tmp / "test.db")
        self.bhav = self.tmp / "bhavcopy"
        self.bhav.mkdir()
        with self.mgr.session() as conn:
            conn.execute(
                "INSERT INTO master_companies (isin, nse_symbol, bse_code, company_name, is_active) "
                "VALUES (?, ?, ?, ?, 1)",
                (_KNOWN_ISIN, _KNOWN_SYMBOL, "544516", "Airfloa Rail Technology Ltd"),
            )
            conn.execute(
                "INSERT INTO master_companies (isin, nse_symbol, bse_code, company_name, is_active) "
                "VALUES (?, ?, NULL, ?, 1)",
                (_BLANK_ISIN, "BLANKCO", "Blank Co Ltd"),
            )
            conn.execute(
                "INSERT INTO master_companies (isin, nse_symbol, bse_code, company_name, is_active) "
                "VALUES (?, ?, ?, ?, 1)",
                (_LEGACY_ISIN, _LEGACY_SYMBOL, _LEGACY_CODE, "ABB India Ltd"),
            )

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ------------------------------------------------------------------
    def _count(self, where: str = "1=1", params=()):
        with self.mgr.session() as conn:
            return conn.execute(
                f"SELECT COUNT(*) FROM daily_price_delivery WHERE {where}", params
            ).fetchone()[0]

    def _fetcher(self, frame=None):
        frame = _fixture_frame() if frame is None else frame

        def fetch(_date):
            return frame

        return fetch

    def _guarded(self, session):
        """Offline BSE context: fake session, no pacing, temp cache dir.

        ``_warmed_up`` is forced True so the shared client never fires its real
        warm-up GET, and ``BHAVCOPY_DIR`` points at the temp dir so the cache
        assertions never touch the production bhavcopy folder.
        """
        stack = contextlib.ExitStack()
        stack.enter_context(mock.patch.object(bse, "_pace", lambda: None))
        stack.enter_context(mock.patch.object(bse, "BHAVCOPY_DIR", self.bhav))
        stack.enter_context(mock.patch.object(bse.bse_client, "session", session))
        stack.enter_context(mock.patch.object(bse.bse_client, "_warmed_up", True))
        return stack

    # ------------------------------------------------------------------
    # UDiFF parse / math
    # ------------------------------------------------------------------
    def test_01_parse_change_pct_and_row_shape(self):
        records = parse_bhavcopy_frame(_fixture_frame(), _SESSION)
        # Blank-close row is dropped; the two priced rows survive.
        self.assertEqual(len(records), 2)

        known = next(r for r in records if r["isin"] == _KNOWN_ISIN)
        # (584.20 - 547.30) / 547.30 * 100 = 6.7439... -> 6.74
        self.assertEqual(known["change_pct"], 6.74)
        self.assertEqual(known["open"], 555.0)
        self.assertEqual(known["high"], 587.9)
        self.assertEqual(known["low"], 551.0)
        self.assertEqual(known["close"], 584.2)
        self.assertEqual(known["prev_close"], 547.3)
        self.assertEqual(known["series"], "M")
        self.assertEqual(known["total_volume"], 120000)
        self.assertEqual(known["num_trades"], 688)
        # TtlTrfVal (rupees) -> lacs
        self.assertEqual(known["turnover_lacs"], 68.88)
        self.assertEqual(known["date"], "2026-09-18")

        unknown = next(r for r in records if r["isin"] == "INE0UNKNOWN01")
        self.assertEqual(unknown["symbol"], "ZZZUNK")

    def test_02_blank_and_float_tolerance(self):
        frame = pd.DataFrame([{
            "TradDt": "2026-09-18", "ISIN": "INE0XBS01012", "TckrSymb": "AIRFLOA",
            "SctySrs": "B", "OpnPric": "-", "HghPric": "", "LwPric": "  ",
            "ClsPric": "123.45", "PrvsClsgPric": "", "TtlTradgVol": "-",
            "TtlTrfVal": "", "TtlNbOfTxsExctd": None,
        }])
        records = parse_bhavcopy_frame(frame, _SESSION)
        self.assertEqual(len(records), 1)
        rec = records[0]
        self.assertEqual(rec["close"], 123.45)
        self.assertEqual(rec["open"], 0.0)
        self.assertEqual(rec["high"], 0.0)
        self.assertEqual(rec["low"], 0.0)
        self.assertEqual(rec["prev_close"], 0.0)
        self.assertEqual(rec["total_volume"], 0)
        self.assertEqual(rec["turnover_lacs"], 0.0)
        self.assertEqual(rec["num_trades"], 0)
        # prev_close == 0 -> change_pct guard
        self.assertEqual(rec["change_pct"], 0.0)

    # ------------------------------------------------------------------
    # UDiFF write path
    # ------------------------------------------------------------------
    def test_03_dry_run_inserts_nothing(self):
        res = backfill_bse_range(
            days=1, end_date=_SESSION, db=self.mgr, dry_run=True, fetcher=self._fetcher()
        )
        self.assertEqual(res["rows_seen"], 3)
        self.assertEqual(res["rows_inserted"], 1)          # would-insert
        self.assertEqual(res["rows_skipped_unknown_isin"], 1)
        self.assertEqual(self._count(), 0)                  # nothing written

    def test_04_real_run_writes_once_and_is_idempotent(self):
        res = backfill_bse_range(
            days=1, end_date=_SESSION, db=self.mgr, dry_run=False, fetcher=self._fetcher()
        )
        self.assertEqual(res["dates_requested"], 1)
        self.assertEqual(res["dates_fetched"], 1)
        self.assertEqual(res["rows_seen"], 3)
        self.assertEqual(res["rows_inserted"], 1)
        self.assertEqual(res["rows_skipped_unknown_isin"], 1)
        self.assertEqual(res["rows_skipped_existing"], 0)
        self.assertEqual(res["errors"], [])
        self.assertEqual(self._count(), 1)
        # The blank-price row must never reach the table.
        self.assertEqual(self._count("symbol = ?", ("BLANKCO",)), 0)
        self.assertEqual(self._count("isin = ?", ("INE0UNKNOWN01",)), 0)

        with self.mgr.session() as conn:
            row = conn.execute(
                "SELECT * FROM daily_price_delivery WHERE symbol = ?", (_KNOWN_SYMBOL,)
            ).fetchone()
        self.assertEqual(row["close"], 584.2)
        self.assertEqual(row["change_pct"], 6.74)
        self.assertEqual(row["num_trades"], 688)
        self.assertEqual(row["turnover_lacs"], 68.88)
        self.assertEqual(row["deliverable_volume"], 0)
        self.assertEqual(row["delivery_pct"], 0.0)
        self.assertIsNone(row["delivery_spike_ratio"])
        self.assertIsNone(row["rsi_14"])

        # Second run inserts nothing new.
        res2 = backfill_bse_range(
            days=1, end_date=_SESSION, db=self.mgr, dry_run=False, fetcher=self._fetcher()
        )
        self.assertEqual(res2["rows_inserted"], 0)
        self.assertEqual(res2["rows_skipped_existing"], 1)
        self.assertEqual(self._count(), 1)

    def test_05_existing_row_preserved_with_delivery_columns(self):
        with self.mgr.session() as conn:
            conn.execute(
                "INSERT INTO daily_price_delivery "
                "(date, symbol, isin, series, open, high, low, close, prev_close, change_pct, "
                " total_volume, turnover_lacs, num_trades, deliverable_volume, delivery_pct, "
                " delivery_spike_ratio, rsi_14) "
                "VALUES (?, ?, ?, 'EQ', 1, 2, 3, 4, 5, 6, 7, 8, 9, 111, 42.5, 1.75, 61.0)",
                ("2026-09-18", _KNOWN_SYMBOL, _KNOWN_ISIN),
            )

        res = backfill_bse_range(
            days=1, end_date=_SESSION, db=self.mgr, dry_run=False, fetcher=self._fetcher()
        )
        self.assertEqual(res["rows_inserted"], 0)
        self.assertEqual(res["rows_skipped_existing"], 1)

        with self.mgr.session() as conn:
            row = conn.execute(
                "SELECT * FROM daily_price_delivery WHERE date = ? AND symbol = ?",
                ("2026-09-18", _KNOWN_SYMBOL),
            ).fetchone()
        # NSE-sourced delivery data survives untouched.
        self.assertEqual(row["close"], 4)
        self.assertEqual(row["deliverable_volume"], 111)
        self.assertEqual(row["delivery_pct"], 42.5)
        self.assertEqual(row["delivery_spike_ratio"], 1.75)
        self.assertEqual(row["rsi_14"], 61.0)

    def test_06_per_date_fetch_failure_is_isolated(self):
        good = _fixture_frame()

        def fetch(target_date):
            if target_date.strftime("%Y-%m-%d") == "2026-09-17":
                raise RuntimeError("boom")
            if target_date.strftime("%Y-%m-%d") == "2026-09-18":
                return good
            return None

        res = backfill_bse_range(
            days=2, end_date=_SESSION, db=self.mgr, dry_run=False, fetcher=fetch
        )
        self.assertEqual(res["dates_fetched"], 1)
        self.assertEqual(len(res["errors"]), 1)
        self.assertEqual(res["errors"][0]["date"], "2026-09-17")
        # The healthy session still landed.
        self.assertEqual(res["rows_inserted"], 1)
        self.assertEqual(self._count(), 1)

    def test_06b_weekend_and_known_holiday_are_not_probed(self):
        probed = []

        def fetch(target_date):
            probed.append(target_date.strftime("%Y-%m-%d"))
            return _fixture_frame() if target_date.strftime("%Y-%m-%d") == "2026-09-18" else None

        # 2026-09-20 is a Sunday; 2026-09-17 is declared a holiday here.
        res = backfill_bse_range(
            days=1, end_date=datetime(2026, 9, 20), db=self.mgr, dry_run=True,
            fetcher=fetch, holidays={"2026-09-17"},
        )
        self.assertEqual(res["dates_fetched"], 1)
        self.assertEqual(res["dates_requested"], 1)
        self.assertEqual(probed, ["2026-09-18"])

    # ------------------------------------------------------------------
    # Content guard
    # ------------------------------------------------------------------
    def test_07_bse_json_soft_fail_forms_return_none(self):
        url = "AnnSubCategoryGetData/w"
        # 1. Angular SPA shell served with HTTP 200.
        with self._guarded(_FakeSession(_FakeResponse(200, text=_SPA_SHELL))):
            self.assertIsNone(bse.bse_json(url, params={"strType": "C"}))
        # 2. ASP.NET soft-404 template (contains Response.StatusCode=404).
        with self._guarded(_FakeSession(_FakeResponse(200, text=_SOFT_404))):
            self.assertIsNone(bse.bse_json(url))
        # 3. {"Status": false} error envelope (the 12-month window cap).
        envelope = {"Status": False, "Message": "Date range cannot exceed 12 months."}
        with self._guarded(_FakeSession(
                _FakeResponse(200, text=json.dumps(envelope), json_data=envelope))):
            self.assertIsNone(bse.bse_json(url))
        # Non-200, empty body, unparseable body.
        with self._guarded(_FakeSession(_FakeResponse(404, text="nope"))):
            self.assertIsNone(bse.bse_json(url))
        with self._guarded(_FakeSession(_FakeResponse(200, text=""))):
            self.assertIsNone(bse.bse_json(url))
        with self._guarded(_FakeSession(_FakeResponse(200, text="<not json>"))):
            self.assertIsNone(bse.bse_json(url))

    def test_07b_bse_json_unwraps_double_encoded_payload(self):
        payload = {"Status": True, "Table": [{"ATTACHMENTNAME": "x.pdf"}]}
        # BSE returns the payload as a JSON *string* inside a JSON body.
        resp = _FakeResponse(200, text=json.dumps(payload), json_data=json.dumps(payload))
        with self._guarded(_FakeSession(resp)):
            data = bse.bse_json("AnnSubCategoryGetData/w")
        self.assertEqual(data["Table"], [{"ATTACHMENTNAME": "x.pdf"}])

    def test_08_bse_csv_content_guard(self):
        url = "https://www.bseindia.com/download/BhavCopy/Equity/BhavCopy_BSE_CM_0_0_0_20260918_F_0000.CSV"
        with self._guarded(_FakeSession(_FakeResponse(200, text=_FIXTURE_CSV))):
            self.assertEqual(bse.bse_csv(url), _FIXTURE_CSV)
        # A shell for a non-trading date must not be returned as data.
        with self._guarded(_FakeSession(_FakeResponse(200, text=_SPA_SHELL))):
            self.assertIsNone(bse.bse_csv(url))
        # A different CSV needs its own prefix (parameterised guard).
        legacy_body = _LEGACY_HEADER + "\n" + _LEGACY_MAPPED + "\n"
        with self._guarded(_FakeSession(_FakeResponse(200, text=legacy_body))):
            self.assertIsNone(bse.bse_csv(url))
            self.assertEqual(bse.bse_csv(url, "SC_CODE,"), legacy_body)

    def test_09_nontrading_date_yields_no_frame_and_no_poison_cache(self):
        target = datetime(2026, 9, 14)  # BSE answered this date with the SPA shell
        url = bse.BSE_BHAVCOPY_URL_TEMPLATE.format(date_str=target.strftime("%Y%m%d"))
        session = _FakeSession(_FakeResponse(200, text=_SPA_SHELL))
        with self._guarded(session):
            self.assertIsNone(bse.bse_client.fetch_bhavcopy(target))
            self.assertEqual(session.calls[-1]["url"], url)
        # Nothing was cached — the 14 KB shell never becomes a "CSV".
        self.assertEqual(list(self.bhav.glob("*.csv")), [])

    def test_09b_poison_cache_file_is_ignored_and_refetched(self):
        target = datetime(2026, 9, 18)
        poison = self.bhav / f"BhavCopy_BSE_{target.strftime('%Y%m%d')}.csv"
        poison.write_text(_SPA_SHELL, encoding="utf-8")
        session = _FakeSession(_FakeResponse(200, text=_FIXTURE_CSV))
        with self._guarded(session):
            df = bse.bse_client.fetch_bhavcopy(target)
        self.assertEqual(list(df.columns)[0], "TradDt")
        self.assertEqual(len(session.calls), 1)          # re-fetched, not parsed
        self.assertTrue(poison.read_text(encoding="utf-8").startswith("TradDt,"))

    def test_09c_soft_fail_body_never_reaches_the_db(self):
        session = _FakeSession(_FakeResponse(200, text=_SPA_SHELL))
        with self._guarded(session):
            res = backfill_bse_range(
                days=1, end_date=_SESSION, db=self.mgr, dry_run=False,
                fetcher=bse.bse_client.fetch_bhavcopy,
            )
        self.assertEqual(res["dates_fetched"], 0)
        self.assertEqual(res["rows_seen"], 0)
        self.assertEqual(res["rows_inserted"], 0)
        self.assertEqual(self._count(), 0)
        self.assertEqual(list(self.bhav.glob("*.csv")), [])

    # ------------------------------------------------------------------
    # Legacy ZIP path
    # ------------------------------------------------------------------
    def test_10_legacy_zip_fetch_parse_and_join(self):
        self.assertEqual(_norm_code("0500002"), "500002")
        self.assertEqual(_norm_code("500002.0"), "500002")
        self.assertEqual(_norm_code(" 500002 "), "500002")

        zip_bytes = _legacy_zip_bytes()
        session = _FakeSession(_FakeResponse(200, content=zip_bytes))
        frame = fetch_legacy_zip(_LEGACY_SESSION, session=session)
        self.assertEqual(session.calls[0]["url"], "https://www.bseindia.com/download/"
                                                  "BhavCopy/Equity/EQ180424_CSV.ZIP")
        self.assertEqual(list(frame["SC_CODE"]), [500002, 999999])

        records = parse_legacy_frame(frame, _LEGACY_SESSION)
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["bse_code"], _LEGACY_CODE)
        self.assertEqual(records[0]["date"], "2024-04-18")
        self.assertEqual(records[0]["series"], "A")
        self.assertEqual(records[0]["close"], 1040.0)
        self.assertEqual(records[0]["prev_close"], 1020.0)
        self.assertEqual(records[0]["change_pct"], 1.96)
        self.assertEqual(records[0]["total_volume"], 12000)
        self.assertEqual(records[0]["num_trades"], 1500)
        self.assertEqual(records[0]["turnover_lacs"], 124.8)
        self.assertNotIn("isin", records[0])

        # A shell body is not a ZIP -> no frame at all.
        shell_session = _FakeSession(_FakeResponse(200, text=_SPA_SHELL))
        self.assertIsNone(fetch_legacy_zip(_LEGACY_SESSION, session=shell_session))

    def test_11_legacy_range_inserts_mapped_and_counts_unmapped(self):
        frame = _legacy_frame()

        def fetch(target_date):
            return frame if target_date.strftime("%Y-%m-%d") == "2024-04-18" else None

        res = backfill_legacy_range(
            years=1, end_date=_LEGACY_SESSION, db=self.mgr, dry_run=False, fetcher=fetch
        )
        self.assertEqual(res["dates_fetched"], 1)
        self.assertGreater(res["dates_requested"], 200)   # ~one year of weekdays
        self.assertEqual(res["rows_seen"], 2)
        self.assertEqual(res["rows_inserted"], 1)
        self.assertEqual(res["rows_skipped_unknown_code"], 1)
        self.assertEqual(res["rows_skipped_existing"], 0)
        self.assertEqual(res["errors"], [])
        self.assertEqual(self._count(), 1)
        self.assertEqual(self._count("isin = ?", ("INE0UNKNOWN01",)), 0)

        with self.mgr.session() as conn:
            row = conn.execute(
                "SELECT * FROM daily_price_delivery WHERE date = ? AND symbol = ?",
                ("2024-04-18", _LEGACY_SYMBOL),
            ).fetchone()
        self.assertEqual(row["isin"], _LEGACY_ISIN)
        self.assertEqual(row["close"], 1040.0)
        self.assertEqual(row["turnover_lacs"], 124.8)
        self.assertEqual(row["num_trades"], 1500)
        self.assertEqual(row["deliverable_volume"], 0)

        # Re-runnable: nothing new on the second pass.
        res2 = backfill_legacy_range(
            years=1, end_date=_LEGACY_SESSION, db=self.mgr, dry_run=False, fetcher=fetch
        )
        self.assertEqual(res2["rows_inserted"], 0)
        self.assertEqual(res2["rows_skipped_existing"], 1)
        self.assertEqual(self._count(), 1)

    def test_11b_legacy_dry_run_writes_nothing(self):
        frame = _legacy_frame()
        res = backfill_legacy_range(
            years=1, end_date=_LEGACY_SESSION, db=self.mgr, dry_run=True,
            fetcher=lambda d: frame if d.strftime("%Y-%m-%d") == "2024-04-18" else None,
        )
        self.assertEqual(res["rows_inserted"], 1)   # would-insert
        self.assertEqual(self._count(), 0)

    # ------------------------------------------------------------------
    # Unified entry point
    # ------------------------------------------------------------------
    def test_12_backfill_bse_merges_both_phases(self):
        udiff = _fixture_frame()
        legacy = _legacy_frame()

        def legacy_fetch(target_date):
            return legacy if target_date.strftime("%Y-%m-%d") == "2024-04-18" else None

        res = backfill_bse(
            days=1, legacy_years=1, end_date=_SESSION, db=self.mgr, dry_run=False,
            fetcher=self._fetcher(udiff), legacy_fetcher=legacy_fetch,
        )
        self.assertEqual(res["rows_seen"], 5)
        self.assertEqual(res["rows_inserted"], 2)
        self.assertEqual(res["rows_skipped_unknown_isin"], 1)
        self.assertEqual(res["rows_skipped_unknown_code"], 1)
        self.assertEqual(res["rows_skipped_existing"], 0)
        self.assertEqual(res["errors"], [])
        self.assertEqual(res["udiff"]["rows_inserted"], 1)
        self.assertEqual(res["legacy"]["rows_inserted"], 1)
        self.assertEqual(res["per_date_inserted"], {"2026-09-18": 1, "2024-04-18": 1})
        self.assertEqual(self._count(), 2)

        # Dry run of the same range inserts nothing and reports the same shape.
        dry = backfill_bse(
            days=1, legacy_years=1, end_date=_SESSION, db=self.mgr, dry_run=True,
            fetcher=self._fetcher(udiff), legacy_fetcher=legacy_fetch,
        )
        self.assertTrue(dry["dry_run"])
        self.assertEqual(dry["rows_inserted"], 0)
        self.assertEqual(dry["rows_skipped_existing"], 2)
        self.assertEqual(self._count(), 2)

    def test_12b_backfill_bse_without_legacy_skips_that_phase(self):
        res = backfill_bse(
            days=1, end_date=_SESSION, db=self.mgr, dry_run=True, fetcher=self._fetcher()
        )
        self.assertEqual(res["legacy"]["dates_requested"], 0)
        self.assertEqual(res["rows_inserted"], 1)

    def test_13_batched_flushes_match_single_pass_counts(self):
        """A tiny flush threshold must not change what lands (both phases)."""
        udiff = _fixture_frame()
        legacy = _legacy_frame()

        with mock.patch.object(bse_backfill, "_FLUSH_RECORDS", 1):
            res = backfill_bse(
                days=1, legacy_years=1, end_date=_SESSION, db=self.mgr, dry_run=False,
                fetcher=self._fetcher(udiff),
                legacy_fetcher=lambda d: legacy if d.strftime("%Y-%m-%d") == "2024-04-18" else None,
            )
            repeat = backfill_bse(
                days=1, legacy_years=1, end_date=_SESSION, db=self.mgr, dry_run=False,
                fetcher=self._fetcher(udiff),
                legacy_fetcher=lambda d: legacy if d.strftime("%Y-%m-%d") == "2024-04-18" else None,
            )
        self.assertEqual(res["rows_inserted"], 2)
        self.assertEqual(res["per_date_inserted"], {"2026-09-18": 1, "2024-04-18": 1})
        self.assertEqual(res["errors"], [])
        self.assertEqual(self._count(), 2)
        # Every batch is still skip-aware, so the rerun adds nothing.
        self.assertEqual(repeat["rows_inserted"], 0)
        self.assertEqual(repeat["rows_skipped_existing"], 2)
        self.assertEqual(self._count(), 2)

    def test_12c_backfill_bse_never_raises_on_a_broken_db(self):
        class _Boom:
            @property
            def db(self):
                raise RuntimeError("no db")

        res = backfill_bse(days=1, legacy_years=1, end_date=_SESSION, db=_Boom(), dry_run=True,
                           fetcher=lambda _d: None, legacy_fetcher=lambda _d: None)
        self.assertEqual(res["rows_inserted"], 0)
        self.assertEqual(len(res["errors"]), 2)
        self.assertEqual({e["source"] for e in res["errors"]}, {"udiff", "legacy"})

    def test_12d_backfill_bse_range_never_raises_on_master_failure(self):
        res = backfill_bse_range(days=1, end_date=_SESSION, db=object(), dry_run=True,
                                 fetcher=self._fetcher())
        self.assertEqual(res["rows_inserted"], 0)
        self.assertTrue(res["errors"])
        self.assertIn("master lookup failed", res["errors"][0]["error"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
