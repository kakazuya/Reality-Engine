"""Tests for the one-call market lookups (delivery / price_extreme / holding).

Run from the repo root:
    python -m unittest discover -s plugins/reality-data/tests -p "test_*.py"

The fixture tests patch ``core._run_duck`` / ``core._run_sqlite`` so the routing
and preference logic is exercised without a database; the LiveChecks class pins
the four acceptance answers against the real read-only snapshot.
"""
from __future__ import annotations

import datetime as dt
import sys
import unittest
from pathlib import Path
from unittest import mock

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = PLUGIN_ROOT / "server"
sys.path.insert(0, str(SERVER_DIR))

import core  # noqa: E402
import lookups_market as lm  # noqa: E402

# Ather Energy: NSE ATHERENERG, BSE 544397, ISIN INE0LEZ01016.
IDENTITY = {
    "isin": "INE0LEZ01016",
    "name": "ATHER ENERGY LIMITED",
    "nse_symbol": "ATHERENERG",
    "bse_symbol": "544397",
    "bse_code": "544397",
    "isin_history": [],
}
PROVENANCE_STUB = {"read_only": True, "generated_at": "2026-10-25T00:00:00", "databases": {}}


class FakeDB:
    """Routes the module's SQL to canned ``(columns, rows)`` / dict rows."""

    def __init__(self, duck_routes=(), sqlite_routes=(), identity=IDENTITY, quarantine=()):
        self.duck_routes = list(duck_routes)
        self.sqlite_routes = list(sqlite_routes)
        self.identity = identity
        self.quarantine = set(quarantine)

    @staticmethod
    def _route(routes, sql, params):
        for match, result in routes:
            if (match(sql) if callable(match) else match in sql):
                return result(params) if callable(result) else result
        raise AssertionError(f"fixture has no route for: {sql[:140]}")

    def run_duck(self, sql, params=(), timeout=15.0):
        return self._route(self.duck_routes, sql, params)

    def run_sqlite(self, key, sql, params=(), timeout=15.0):
        return self._route(self.sqlite_routes, sql, params)

    def resolve_one(self, query):
        if self.identity is None:
            raise core.DataError("not_found", f"no listed company matches {query!r}")
        return self.identity

    def __enter__(self):
        self._patches = [
            mock.patch.object(core, "_run_duck", self.run_duck),
            mock.patch.object(core, "_run_sqlite", self.run_sqlite),
            mock.patch.object(core, "resolve_one", self.resolve_one),
            mock.patch.object(core, "quarantined_doc_ids", lambda: set(self.quarantine)),
            mock.patch.object(core, "provenance", lambda *a, **k: dict(PROVENANCE_STUB)),
        ]
        for patch in self._patches:
            patch.start()
        return self

    def __exit__(self, *exc):
        for patch in reversed(self._patches):
            patch.stop()
        return False


def _bars(pairs):
    """``[(date, volume, deliverable_qty)]`` -> (columns, rows)."""
    return ["date", "volume", "deliverable_qty"], [tuple(p) for p in pairs]


class DeliveryFixtureTests(unittest.TestCase):
    def _db(self, nse_rows, bse_rows, trading_days):
        return FakeDB(
            duck_routes=[
                ("SELECT DISTINCT date FROM px_nse", (["date"], [(d,) for d in trading_days])),
                (lambda sql: "FROM px_nse WHERE" in sql, _bars(nse_rows)),
                (lambda sql: "FROM px_bse WHERE" in sql, _bars(bse_rows)),
            ],
        )

    def test_both_exchanges_sum_and_combined_pct(self):
        day = dt.date(2026, 4, 13)
        db = self._db([(day, 1000, 200)], [(day, 500, 100)], [day])
        with db:
            out = lm.delivery("ATHERENERG", ["2026-04-13"])
        self.assertTrue(out["found"])
        row = out["rows"][0]
        self.assertEqual(row["status"], "ok")
        self.assertEqual(row["nse"], {"volume": 1000, "deliverable_qty": 200, "delivery_pct": 20.0})
        self.assertEqual(row["bse"], {"volume": 500, "deliverable_qty": 100, "delivery_pct": 20.0})
        self.assertEqual(row["deliverable_qty_sum"], 300)
        self.assertEqual(row["volume_sum"], 1500)
        self.assertEqual(row["delivery_pct_combined"], 20.0)
        self.assertEqual(out["totals"]["deliverable_qty"], 300)
        self.assertFalse(out["adjusted"])

    def test_no_trading_day_is_not_a_missing_symbol(self):
        trading = dt.date(2026, 4, 13)
        holiday = dt.date(2026, 4, 14)
        db = self._db([(trading, 1000, 200)], [(trading, 500, 100)], [trading])
        with db:
            out = lm.delivery("ATHERENERG", ["2026-04-13", "2026-04-14"])
        self.assertEqual(out["rows"][0]["status"], "ok")
        self.assertEqual(out["rows"][1]["status"], "no_trading")
        self.assertIsNone(out["rows"][1]["deliverable_qty_sum"])

    def test_trading_day_without_the_symbol_names_the_exchanges(self):
        day = dt.date(2026, 4, 15)
        db = self._db([], [], [day])
        with db:
            out = lm.delivery("ATHERENERG", ["2026-04-15"])
        self.assertFalse(out["found"])
        self.assertEqual(out["rows"][0]["status"], "missing_for_symbol")
        self.assertEqual(out["rows"][0]["missing_exchanges"], ["NSE", "BSE"])
        self.assertTrue(out["checked"])
        self.assertTrue(out["hint"])

    def test_one_sided_row_is_partial(self):
        day = dt.date(2026, 4, 13)
        db = self._db([(day, 1000, 200)], [], [day])
        with db:
            out = lm.delivery("ATHERENERG", ["2026-04-13"])
        row = out["rows"][0]
        self.assertEqual(row["status"], "partial")
        self.assertEqual(row["missing_exchanges"], ["BSE"])
        self.assertEqual(row["nse"]["deliverable_qty"], 200)
        self.assertIsNone(row["bse"])

    def test_date_span_and_bad_input(self):
        start, end = dt.date(2026, 4, 13), dt.date(2026, 4, 14)
        db = self._db([(start, 10, 5)], [], [start])
        with db:
            out = lm.delivery("ATHERENERG", "2026-04-13", end="2026-04-14")
        self.assertEqual([r["date"] for r in out["rows"]], ["2026-04-13", "2026-04-14"])
        with db, self.assertRaises(core.DataError) as ctx:
            lm.delivery("ATHERENERG", ["not-a-date"])
        self.assertEqual(ctx.exception.code, "bad_date")
        with db, self.assertRaises(core.DataError) as ctx:
            lm.delivery("ATHERENERG", "2026-04-13", end="2026-01-01")
        self.assertEqual(ctx.exception.code, "bad_range")

    def test_unknown_symbol_says_what_was_checked(self):
        with FakeDB(identity=None):
            out = lm.delivery("NOTACOMPANY", ["2026-04-13"])
        self.assertFalse(out["found"])
        self.assertEqual(out["query"], "NOTACOMPANY")
        self.assertTrue(any("security_master" in item for item in out["checked"]))
        self.assertIn("resolve", out["hint"])


class PriceExtremeFixtureTests(unittest.TestCase):
    def _db(self, nse_high=400.0, bse_high=410.0, nse_low=300.0, bse_low=290.0):
        day = dt.date(2026, 4, 28)
        high = ["date", "value"]
        return FakeDB(duck_routes=[
            ("max(date) AS d", (["d"], [(dt.date(2026, 10, 19),)])),
            (lambda s: "high AS value FROM px_nse WHERE" in s,
             (high, [(day, nse_high)])),
            (lambda s: "high AS value FROM px_bse WHERE" in s,
             (high, [(day, bse_high)])),
            (lambda s: "low AS value FROM px_nse WHERE" in s,
             (high, [(day, nse_low)])),
            (lambda s: "low AS value FROM px_bse WHERE" in s,
             (high, [(day, bse_low)])),
        ])

    def test_default_window_is_snapshot_ytd_and_ranks_exchanges(self):
        with self._db():
            out = lm.price_extreme("ATHERENERG")
        self.assertEqual(out["window"], {"start": "2026-01-01", "end": "2026-10-19",
                                         "default_ytd": True})
        self.assertEqual(out["snapshot_end"], "2026-10-19")
        high = out["extremes"]["high"]
        self.assertEqual(high["overall_exchange"], "BSE")   # 410 > 400
        self.assertEqual(high["exchange"], "BSE")
        self.assertEqual(high["by_exchange"]["NSE"]["value"], 400.0)
        self.assertIn("2026-10-19", out["data_freshness"])

    def test_kind_both_returns_low_too(self):
        with self._db():
            out = lm.price_extreme("ATHERENERG", kind="both")
        self.assertEqual(set(out["extremes"]), {"high", "low"})
        self.assertEqual(out["extremes"]["low"]["value"], 290.0)
        self.assertEqual(out["extremes"]["low"]["overall_exchange"], "BSE")

    def test_adjusted_reads_the_adjusted_tables(self):
        db = FakeDB(duck_routes=[
            ("max(date) AS d", (["d"], [(dt.date(2026, 10, 19),)])),
            (lambda s: "adj_high AS value FROM px_nse_adj WHERE" in s,
             (["date", "value"], [(dt.date(2026, 4, 28), 99.0)])),
            (lambda s: "adj_high AS value FROM px_bse_adj WHERE" in s,
             (["date", "value"], [(dt.date(2026, 4, 28), 98.0)])),
        ])
        with db:
            out = lm.price_extreme("ATHERENERG", adjusted=True)
        self.assertTrue(out["adjusted"])
        self.assertEqual(out["extremes"]["high"]["overall_exchange"], "NSE")

    def test_bad_kind_and_empty_window(self):
        with self._db(), self.assertRaises(core.DataError) as ctx:
            lm.price_extreme("ATHERENERG", kind="widest")
        self.assertEqual(ctx.exception.code, "bad_request")
        db = FakeDB(duck_routes=[("max(date) AS d", (["d"], [(dt.date(2026, 10, 19),)])),
                                 (lambda s: "AS value FROM px_nse WHERE" in s,
                                  (["date", "value"], [])),
                                 (lambda s: "AS value FROM px_bse WHERE" in s,
                                  (["date", "value"], []))])
        with db:
            out = lm.price_extreme("ATHERENERG")
        self.assertFalse(out["found"])
        self.assertIn("window", out)


SHP_ROW = {
    "quarter_end": "2026-09-30", "broadcast_at": "2026-10-15T16:04:51",
    "submission_date": "2026-10-15", "promoter_pct": 55.98, "public_pct": 44.02,
    "revised": "N", "isin": "INE872H01027", "symbol": "LUMAXTECH",
}
AR_ROW = {
    "doc_id": 53803, "page": 121, "item": "Total shares held / total equity shares",
    "value": 68157705.0, "unit": "number", "period": "as on March 31, 2026",
    "fiscal_year": "2026-03-31", "category": "shareholding", "quote": "6,81,57,705 100.00",
}


def _holding_db(shp=True, ar=(), xbrl=(136315000.0, 2.0), quarantine=(),
                xbrl_period="2026-06-30"):
    shp_columns = list(SHP_ROW)
    duck_routes = [("FROM shp_index",
                    (shp_columns, [tuple(SHP_ROW.values())] if shp else []))]
    sqlite_routes = [("FROM ar_facts", list(ar))]
    if xbrl:
        sqlite_routes += [
            ("FROM filings f", [{"file": "f.xml", "period_end": xbrl_period,
                                 "symbol": "LUMAXTECH", "consolidated": "Standalone"}]),
            ("FROM facts", [{"file": "f.xml", "concept": "PaidUpValueOfEquityShareCapital",
                             "context": "OneD", "value": xbrl[0], "unit": "INR"},
                            {"file": "f.xml", "concept": "FaceValueOfEquityShareCapital",
                             "context": "OneD", "value": xbrl[1], "unit": "INRPerShare"}]),
        ]
    else:
        sqlite_routes.append(("FROM filings f", []))
    return FakeDB(duck_routes=duck_routes, sqlite_routes=sqlite_routes,
                  quarantine=quarantine)


class HoldingFixtureTests(unittest.TestCase):
    def test_exact_ar_count_beats_rounded_xbrl(self):
        with _holding_db(shp=True, ar=[AR_ROW]):
            out = lm.holding("LUMAXTECH", "2026-09-30")
        self.assertTrue(out["found"])
        self.assertEqual(out["promoter_pct"], 55.98)
        self.assertEqual(out["public_pct"], 44.02)
        self.assertEqual(out["shareholding"]["quarter_end"], "2026-09-30")
        self.assertEqual(out["best_share_count"], 68157705)
        self.assertEqual(out["best_share_count_source"]["source"], "ar_facts")
        self.assertTrue(out["xbrl_rounded"])
        values = {c["value"] for c in out["share_count_candidates"]}
        self.assertEqual(values, {68157705, 68157500})

    def test_no_exact_candidate_falls_back_to_xbrl_without_claiming_rounding(self):
        with _holding_db(shp=True, ar=[]):
            out = lm.holding("LUMAXTECH")
        self.assertEqual(out["best_share_count"], 68157500)
        self.assertEqual(out["best_share_count_source"]["source"], "results_xbrl")
        self.assertFalse(out["xbrl_rounded"])
        self.assertTrue(any("no exact AR share count" in note for note in out["notes"]))

    def test_bucket_and_promoter_labels_are_not_candidates(self):
        # Values sit next to the XBRL count so the plausibility guard cannot be
        # what rejects them; the label filter must.
        labels = [
            "Shares held by 1,00,001-and-above bucket: 5,81,07,032 shares (85.25% of total shares)",
            "Total number of shares held by Promoters",
            "Total Shares (100001& Above shares)",
            "President of India total shares",
            "Total shares in the range 1-5,000",
            "Total shares held by Other Banks",
            "Total shares as % of turnover",
        ]
        rows = [dict(AR_ROW, item=label, value=68100000.0) for label in labels]
        with _holding_db(shp=True, ar=rows):
            out = lm.holding("LUMAXTECH")
        self.assertEqual([c["value"] for c in out["share_count_candidates"]
                          if c["source"] == "ar_facts"], [])

    def test_quarantined_doc_cannot_contribute_a_count(self):
        with _holding_db(shp=True, ar=[AR_ROW], quarantine=[53803]):
            out = lm.holding("LUMAXTECH")
        self.assertEqual([c for c in out["share_count_candidates"]
                          if c["source"] == "ar_facts"], [])
        self.assertEqual(out["best_share_count"], 68157500)

    def test_number_of_equity_shares_phrasing_is_an_exact_total(self):
        for item in ("Number of equity shares",
                     "Paid-up equity share capital (number of shares)"):
            row = dict(AR_ROW, item=item, doc_id=120077, page=182)
            with _holding_db(shp=True, ar=[row]):
                out = lm.holding("GPIL", "2026-09-30")
            self.assertEqual([c["value"] for c in out["share_count_candidates"]
                              if c["source"] == "ar_facts"], [68157705], item)

    def test_xbrl_prefers_the_standalone_filing(self):
        filings = [
            {"file": "cons.xml", "period_end": "2026-06-30", "symbol": "GPIL",
             "consolidated": "Consolidated"},
            {"file": "stand.xml", "period_end": "2026-06-30", "symbol": "GPIL",
             "consolidated": "Standalone"},
        ]

        def facts(file_params):
            out = []
            for file in file_params:
                paid = 617_000_000.0 if file == "cons.xml" else 650_600_000.0
                out += [
                    {"file": file, "concept": "PaidUpValueOfEquityShareCapital",
                     "context": "OneD", "value": paid, "unit": "INR"},
                    {"file": file, "concept": "FaceValueOfEquityShareCapital",
                     "context": "OneD", "value": 1.0, "unit": "INRPerShare"},
                ]
            return out

        db = FakeDB(
            duck_routes=[("FROM shp_index",
                          (list(SHP_ROW), [tuple(SHP_ROW.values())]))],
            sqlite_routes=[("FROM ar_facts", []), ("FROM filings f", filings),
                           ("FROM facts", facts)],
        )
        with db:
            out = lm.holding("GPIL", "2026-09-30")
        self.assertEqual(out["best_share_count"], 650_600_000)
        self.assertEqual(out["best_share_count_source"]["doc_id"], "stand.xml")

    def test_older_ar_count_warns_instead_of_trusting_it(self):
        # 66.5M vs the XBRL 68.16M is a real gap (a corporate action), not rounding.
        old = dict(AR_ROW, fiscal_year="2025-03-31", period="As on March 31, 2025",
                   value=66_500_000.0)
        with _holding_db(shp=True, ar=[old]):
            out = lm.holding("LUMAXTECH", "2026-09-30")
        self.assertEqual(out["best_share_count"], 66_500_000)
        self.assertEqual(out["warning"],
                         "AR count older than latest XBRL; possible buyback/split/issue")
        self.assertFalse(any("trust the AR figure" in note for note in out["notes"]))

    def test_older_ar_count_within_rounding_is_trusted(self):
        old = dict(AR_ROW, fiscal_year="2025-03-31", period="As on March 31, 2025")
        with _holding_db(shp=True, ar=[old]):
            out = lm.holding("LUMAXTECH", "2026-09-30")
        self.assertEqual(out["best_share_count"], 68157705)
        self.assertIsNone(out["warning"])
        self.assertTrue(any("trust the AR figure" in note for note in out["notes"]))

    def test_ar_not_older_than_xbrl_trusts_the_ar(self):
        with _holding_db(shp=True, ar=[AR_ROW], xbrl_period="2025-12-31"):
            out = lm.holding("LUMAXTECH", "2026-09-30")
        self.assertIsNone(out["warning"])
        self.assertTrue(any("trust the AR figure" in note for note in out["notes"]))

    def test_as_of_filters_newer_ar_and_xbrl_candidates(self):
        old = dict(AR_ROW, doc_id=100, page=10, fiscal_year="2019-03-31",
                   period="As on March 31, 2019", value=66_000_000.0)
        with _holding_db(shp=False, ar=[AR_ROW, old]):
            out = lm.holding("LUMAXTECH", "2020-01-01")
        self.assertTrue(out["found"])
        self.assertEqual(out["best_share_count"], 66_000_000)
        self.assertEqual([c["value"] for c in out["share_count_candidates"]], [66_000_000])

    def test_missing_shareholding_still_answers_with_a_gap_note(self):
        with _holding_db(shp=False, ar=[AR_ROW]):
            out = lm.holding("LUMAXTECH")
        self.assertTrue(out["found"])
        self.assertIsNone(out["promoter_pct"])
        self.assertEqual(out["best_share_count"], 68157705)
        self.assertTrue(any("shp_index has no quarter_end" in note for note in out["notes"]))
        self.assertTrue(any("no share-count column" in note for note in out["notes"]))

    def test_nothing_found(self):
        with _holding_db(shp=False, ar=[], xbrl=None):
            out = lm.holding("NOTACOMPANY")
        self.assertFalse(out["found"])
        self.assertTrue(any("shp_index" in item for item in out["checked"]))
        self.assertIn("facts", out["hint"])


class LiveChecks(unittest.TestCase):
    """The four acceptance answers against the real read-only snapshot."""

    @classmethod
    def setUpClass(cls):
        try:
            snapshot = core.snapshot_path().name
        except core.DataError as exc:
            raise unittest.SkipTest(str(exc))
        if snapshot != "truth_2026-10-19.duckdb":
            raise unittest.SkipTest(
                f"live answers pinned to truth_2026-10-19.duckdb, snapshot is {snapshot}")
        core.warm()

    def test_delivery_ather_energy(self):
        out = lm.delivery("Ather Energy", ["2026-04-13", "2026-04-14"])
        self.assertEqual(out["symbol"], "ATHERENERG")
        self.assertEqual(out["bse_code"], "544397")
        first, second = out["rows"]
        self.assertEqual(first["status"], "ok")
        self.assertEqual(first["nse"]["deliverable_qty"], 3_249_967)
        self.assertEqual(first["nse"]["volume"], 27_333_392)
        self.assertEqual(first["bse"]["deliverable_qty"], 877_968)
        self.assertEqual(first["deliverable_qty_sum"], 4_127_935)
        self.assertEqual(second["status"], "no_trading")   # 2026-04-14 had no session
        self.assertFalse(out["adjusted"])

    def test_price_extreme_pfc_by_bse_code(self):
        out = lm.price_extreme("532810", start="2026-01-01", end="2026-10-19")
        self.assertEqual(out["symbol"], "PFC")
        high = out["extremes"]["high"]
        self.assertEqual(high["value"], 486.5)
        self.assertEqual(high["date"], "2026-04-28")
        self.assertEqual(high["overall_exchange"], "NSE")
        self.assertEqual(high["by_exchange"]["BSE"]["value"], 486.45)
        self.assertEqual(out["snapshot_end"], "2026-10-19")
        ytd = lm.price_extreme("532810")
        self.assertTrue(ytd["window"]["default_ytd"])
        self.assertEqual(ytd["window"]["start"], f"{ytd['snapshot_end'][:4]}-01-01")

    def test_holding_blackbuck_promoter(self):
        out = lm.holding("BLACKBUCK", "2026-09-30")
        self.assertEqual(out["promoter_pct"], 24.99)
        self.assertEqual(out["public_pct"], 75.01)
        self.assertEqual(out["shareholding"]["quarter_end"], "2026-09-30")

    def test_holding_lumaxtech_exact_share_count(self):
        out = lm.holding("LUMAXTECH")
        self.assertEqual(out["best_share_count"], 68_157_705)
        self.assertEqual(out["best_share_count_source"]["doc_id"], 53803)
        self.assertEqual(out["best_share_count_source"]["page"], 121)
        self.assertTrue(out["xbrl_rounded"])
        self.assertIn(68_157_500, {c["value"] for c in out["share_count_candidates"]})

    def test_unknown_symbol_is_not_an_empty_list(self):
        for out in (lm.delivery("ZZZNOTACOMPANY", ["2026-04-13"]),
                    lm.price_extreme("ZZZNOTACOMPANY"),
                    lm.holding("ZZZNOTACOMPANY")):
            self.assertFalse(out["found"])
            self.assertTrue(out["checked"])
            self.assertIsInstance(out["hint"], str)


if __name__ == "__main__":
    unittest.main()
