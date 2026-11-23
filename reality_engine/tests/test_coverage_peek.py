"""Tests for ``coverage_peek`` (in-memory fixtures only; no live database access)."""
from __future__ import annotations

import contextlib
import io
import json
import sqlite3
import unittest

from reality_engine.toolbelt import coverage_peek

DEEDEV = "INE841L01016"
OLD_ISIN = "INE000000002"   # superseded ISIN still present in history tables
OTHER = "INE999999999"


def _db(script: str) -> sqlite3.Connection:
    con = sqlite3.connect(":memory:")
    con.executescript(script)
    return con


class CoveragePeekTest(unittest.TestCase):
    def setUp(self) -> None:
        self.stores = {
            "equity_intelligence": _db("""
                CREATE TABLE master_companies (isin TEXT PRIMARY KEY, nse_symbol TEXT, bse_code TEXT);
                CREATE TABLE symbol_isin_history (exchange TEXT, symbol TEXT, isin TEXT);
                CREATE TABLE corporate_documents (isin TEXT, symbol TEXT, doc_type TEXT,
                    bse_dissem_ts TEXT, publication_date TEXT, call_date TEXT, doc_date TEXT);
                CREATE TABLE daily_price_delivery (date TEXT, symbol TEXT, isin TEXT);
            """),
            "bse_announcements": _db("""
                CREATE TABLE ann (NEWSID TEXT, DT_TM TEXT, symbol TEXT);
            """),
            "concall_facts": _db("""
                CREATE TABLE cc_docs (doc_id INTEGER, isin TEXT, symbol TEXT, filed_at TEXT);
                CREATE TABLE cc_items (doc_id INTEGER, isin TEXT, filed_at TEXT);
            """),
            "ar_facts": _db("""
                CREATE TABLE ar_docs (doc_id INTEGER, isin TEXT, symbol TEXT, filed_at TEXT);
                CREATE TABLE ar_facts (doc_id INTEGER, isin TEXT, filed_at TEXT);
            """),
            "deck_figures": _db("""
                CREATE TABLE deck_sources (source_id TEXT, isin TEXT, known_at TEXT);
                CREATE TABLE pages (sha256 TEXT, page_no INTEGER, prompt_version TEXT,
                    isin TEXT, known_at TEXT);
                CREATE TABLE facts (sha256 TEXT, page_no INTEGER, prompt_version TEXT, metric TEXT);
            """),
            "results_xbrl": _db("""
                CREATE TABLE filings (file TEXT, isin TEXT, period_end TEXT);
                CREATE TABLE facts (file TEXT, period_end TEXT, concept TEXT);
            """),
        }
        self._equity()
        self._announcements()
        self._concalls()
        self._annual_reports()
        self._decks()
        self._results()

    def tearDown(self) -> None:
        for con in self.stores.values():
            con.close()

    def _equity(self) -> None:
        con = self.stores["equity_intelligence"]
        con.executemany("INSERT INTO master_companies VALUES (?,?,?)", [
            (DEEDEV, "DEEDEV", "544198"),
            (OTHER, "OTHER", "999999"),
            ("INEEMPTY0001", "EMPTY", "000000"),
        ])
        con.executemany("INSERT INTO symbol_isin_history VALUES (?,?,?)", [
            ("NSE", "DEEDEV", DEEDEV), ("NSE", "DEEDEV", OLD_ISIN), ("NSE", "OTHER", OTHER),
        ])
        con.executemany("INSERT INTO corporate_documents VALUES (?,?,?,?,?,?,?)", [
            (DEEDEV, "DEEDEV", "ANNOUNCEMENT", None, "2025-08-12", None, "2025-08-11"),
            (DEEDEV, "DEEDEV", "CONCALL_TRANSCRIPT", "2026-08-11T23:38:08", None, None,
             "2026-08-12"),
            (DEEDEV, "DEEDEV", "OTHER_FILING", None, None, None, None),
            (OTHER, "OTHER", "ANNOUNCEMENT", None, "2020-01-01", None, "2020-01-01"),
        ])
        con.executemany("INSERT INTO daily_price_delivery VALUES (?,?,?)", [
            ("2024-06-26", "DEEDEV", DEEDEV), ("2026-10-23", "DEEDEV", DEEDEV),
            ("2024-06-25", "OTHER", OTHER),
        ])

    def _announcements(self) -> None:
        self.stores["bse_announcements"].executemany("INSERT INTO ann VALUES (?,?,?)", [
            ("n1", "2024-06-26T08:01:57.293", "DEEDEV"),
            ("n2", "2026-09-26T12:41:34.727", "DEEDEV"),
            ("n3", "2024-01-01T00:00:00", "OTHER"),
        ])

    def _concalls(self) -> None:
        con = self.stores["concall_facts"]
        con.executemany("INSERT INTO cc_docs VALUES (?,?,?,?)", [
            (1, DEEDEV, "DEEDEV", "2024-11-19T14:18:03.527"),
            (2, None, "DEEDEV", "2026-08-11T23:38:08.44"),  # no ISIN: symbol still matches
            (3, OTHER, "OTHER", "2025-01-01"),
        ])
        con.executemany("INSERT INTO cc_items VALUES (?,?,?)", [
            (1, DEEDEV, "2024-11-19T14:18:03.527"),
            (2, OLD_ISIN, "2026-08-11T23:38:08.44"),
            (2, DEEDEV, "2026-08-11T23:38:08.44"),
            (3, OTHER, "2025-01-01"),
        ])

    def _annual_reports(self) -> None:
        con = self.stores["ar_facts"]
        con.executemany("INSERT INTO ar_docs VALUES (?,?,?,?)", [
            (7, DEEDEV, "DEEDEV", "2024-09-03T20:53:16"),
            (8, OLD_ISIN, None, "2026-08-27T18:37:47"),
            (9, OTHER, "OTHER", "2023-01-01"),
        ])
        con.executemany("INSERT INTO ar_facts VALUES (?,?,?)", [
            (7, DEEDEV, "2024-09-03T20:53:16"),
            (7, OLD_ISIN, "2024-09-03T20:53:16"),
            (8, OLD_ISIN, "2026-08-27T18:37:47"),
            (9, OTHER, "2023-01-01"),
        ])

    def _decks(self) -> None:
        con = self.stores["deck_figures"]
        con.executemany("INSERT INTO deck_sources VALUES (?,?,?)", [
            ("d1", DEEDEV, "2024-08-16T15:01:56"),
            ("d2", OTHER, "2020-01-01"),
        ])
        con.executemany("INSERT INTO pages VALUES (?,?,?,?,?)", [
            ("sha1", 1, "v1", DEEDEV, "2024-08-16T15:01:56.177"),
            ("sha1", 1, "v2", DEEDEV, "2024-08-16T15:01:56.177"),
            ("sha2", 1, "v1", DEEDEV, "2026-08-05T14:43:57.457"),
            ("sha9", 1, "v1", OTHER, "2020-01-01"),
        ])
        con.executemany("INSERT INTO facts VALUES (?,?,?,?)", [
            ("sha1", 1, "v1", "revenue"),
            ("sha1", 1, "v2", "revenue"),  # same page read by two prompts: counted once
            ("sha2", 1, "v1", "ebitda"),
            ("sha9", 1, "v1", "revenue"),
        ])

    def _results(self) -> None:
        con = self.stores["results_xbrl"]
        con.executemany("INSERT INTO filings VALUES (?,?,?)", [
            ("f1", DEEDEV, "2024-03-31"),
            ("f2", OLD_ISIN, "2026-06-30"),
            ("f9", OTHER, "2020-03-31"),
        ])
        con.executemany("INSERT INTO facts VALUES (?,?,?)", [
            ("f1", "2024-03-31", "Revenue"), ("f1", "2024-03-31", "PAT"),
            ("f2", "2026-06-30", "Revenue"), ("f2", "2026-06-30", "PAT"),
            ("f9", "2020-03-31", "Revenue"),
        ])

    def test_counts_and_date_ranges(self) -> None:
        result = coverage_peek.coverage("deedev", stores=self.stores)
        self.assertTrue(result["found"])
        self.assertEqual(result["symbol"], "DEEDEV")
        self.assertEqual(result["isins"], [OLD_ISIN, DEEDEV])
        self.assertEqual(len(result["stores"]), 11)
        by_store = {row["store"]: row for row in result["stores"]}
        expected = {
            "equity_intelligence.corporate_documents":
                (3, "2025-08-12", "2026-08-11T23:38:08"),
            "bse_announcements.ann":
                (2, "2024-06-26T08:01:57.293", "2026-09-26T12:41:34.727"),
            "concall_facts.cc_docs":
                (2, "2024-11-19T14:18:03.527", "2026-08-11T23:38:08.44"),
            "concall_facts.cc_items":
                (3, "2024-11-19T14:18:03.527", "2026-08-11T23:38:08.44"),
            "ar_facts.ar_docs":
                (2, "2024-09-03T20:53:16", "2026-08-27T18:37:47"),
            "ar_facts.ar_facts":
                (3, "2024-09-03T20:53:16", "2026-08-27T18:37:47"),
            "deck_figures.deck_sources":
                (1, "2024-08-16T15:01:56", "2024-08-16T15:01:56"),
            "deck_figures.facts":
                (3, "2024-08-16T15:01:56.177", "2026-08-05T14:43:57.457"),
            "results_xbrl.filings":
                (2, "2024-03-31", "2026-06-30"),
            "results_xbrl.facts":
                (4, "2024-03-31", "2026-06-30"),
            "equity_intelligence.daily_price_delivery":
                (2, "2024-06-26", "2026-10-23"),
        }
        self.assertEqual(set(by_store), set(expected))
        for store, (rows, first, last) in expected.items():
            self.assertEqual(by_store[store]["rows"], rows, store)
            self.assertEqual((by_store[store]["first_date"], by_store[store]["last_date"]),
                             (first, last), store)
        self.assertEqual(result["stores_with_data"], 11)
        self.assertEqual(result["total_rows"], sum(value[0] for value in expected.values()))

    def test_known_symbol_with_no_data_is_not_found(self) -> None:
        result = coverage_peek.coverage("EMPTY", stores=self.stores)
        self.assertTrue(result["found"])
        self.assertEqual(result["stores_with_data"], 0)
        self.assertEqual(result["total_rows"], 0)
        self.assertTrue(all(row["first_date"] is None for row in result["stores"]))

    def test_json_output(self) -> None:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = coverage_peek.main(["--symbol", "DEEDEV", "--json"], stores=self.stores)
        self.assertEqual(rc, 0)
        data = json.loads(out.getvalue())
        self.assertEqual(data["symbol"], "DEEDEV")
        self.assertEqual(len(data["stores"]), 11)
        self.assertEqual(data["stores"][1]["dataset"], "announcements")

    def test_table_output(self) -> None:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = coverage_peek.main(["--symbol", "DEEDEV"], stores=self.stores)
        self.assertEqual(rc, 0)
        text = out.getvalue()
        self.assertIn("bse_announcements.ann", text)
        self.assertIn("11/11 stores hold data", text)

    def test_unknown_symbol_exits_2(self) -> None:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = coverage_peek.main(["--symbol", "nope"], stores=self.stores)
        self.assertEqual(rc, 2)
        self.assertIn("symbol not found: NOPE", out.getvalue())
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(coverage_peek.main(["--symbol", "nope", "--json"],
                                                stores=self.stores), 2)


if __name__ == "__main__":
    unittest.main()
