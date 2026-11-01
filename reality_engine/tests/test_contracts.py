"""Acceptance checks for the typed write contracts (T-016).

    python -m pytest reality_engine/tests/test_contracts.py -q

The false rows are Claude's real grade of the prototype-3 run
(``tasks/pilot60/PROTOTYPE3_CLAUDE_GRADE_2026-11-01.md``); each one has a correct
row beside it, taken from the same real wording.  The write-path test drives one
bad row through ``extract60._write`` for each of the 16 measure tables, so no
path can store a row the contract rejects.
"""
from __future__ import annotations

import inspect
import re
import sqlite3
import unittest
import unittest.mock
from collections import Counter
from pathlib import Path

from reality_engine import contracts
from reality_engine.pilot import extract60 as x

KNOWN = "2026-05-01T18:00:00"
PERIOD = "2026-03-31"


class FalseRowTest(unittest.TestCase):
    """The real false rows, each rejected next to a correct row that is accepted."""

    def test_nim_90_from_digital_contribution_is_rejected(self):
        bad = {"period_end": PERIOD, "metric": "nim_pct", "value": 90.0, "unit": "pct",
               "page": 9, "known_at": KNOWN,
               "quote": "30% digital contribution with 100MM loans this quarter"}
        ok, reason = contracts.check("lender_metrics", bad)
        self.assertFalse(ok)
        self.assertIn("value_above_range", reason)
        good = {**bad, "value": 9.5, "quote": "NIM of 9.5% for the quarter"}
        ok, reason = contracts.check("lender_metrics", good)
        self.assertTrue(ok, reason)

    def test_capacity_in_megawatts_with_inr_cr_unit_is_rejected(self):
        bad = {"period_end": PERIOD, "product": "Hybrid (with storage)", "capacity": 125.0,
               "capacity_unit": "inr_cr", "utilisation_pct": None, "production": None,
               "page": 12, "known_at": KNOWN,
               "quote": "100 MW Hybrid (with storage), to be commissioned in Q3 FY25"}
        ok, reason = contracts.check("company_capacity_utilisation", bad)
        self.assertFalse(ok)
        self.assertIn("unit:inr_cr", reason)
        good = {**bad, "capacity": 100.0, "capacity_unit": "mw"}
        ok, reason = contracts.check("company_capacity_utilisation", good)
        self.assertTrue(ok, reason)

    def test_eps_stored_as_zero_is_rejected(self):
        bad = {"period_end": PERIOD, "metric": "eps", "value": 0.0, "unit": "inr_cr",
               "page": 21, "known_at": KNOWN,
               "quote": "Basic EPS was Rs 10.00 for the quarter"}
        ok, reason = contracts.check("company_operating_metrics", bad)
        self.assertFalse(ok)
        self.assertIn("zero_value", reason)
        good = {**bad, "value": 10.0, "unit": "inr_per_unit"}
        ok, reason = contracts.check("company_operating_metrics", good)
        self.assertTrue(ok, reason)

    def test_order_book_value_written_as_intake_is_rejected(self):
        bad = {"period_end": "2026-08-10", "intake_cr": 37697.0, "order_book_cr": None,
               "book_to_bill": None, "page": 3, "known_at": KNOWN,
               "quote": "Order Book Rs 37,697 Cr."}
        ok, reason = contracts.check("order_intake", bad)
        self.assertFalse(ok)
        self.assertIn("measure_term_absent", reason)
        good = {"period_end": "2025-03-31", "intake_cr": 24689.0, "order_book_cr": None,
                "book_to_bill": None, "page": 3, "known_at": KNOWN,
                "quote": "Order Intake Rs 24,689 Cr."}
        ok, reason = contracts.check("order_intake", good)
        self.assertTrue(ok, reason)
        # The same number IS the order book when the quote says so.
        book = {**bad, "intake_cr": None, "order_book_cr": 37697.0}
        ok, reason = contracts.check("order_intake", book)
        self.assertTrue(ok, reason)

    def test_a_digit_lifted_from_a_label_is_rejected(self):
        bad = {"period_end": PERIOD, "metric": "new_stores", "value": 4.0, "unit": "count",
               "page": 3, "known_at": KNOWN, "quote": "Q4 FY26: added new stores"}
        ok, reason = contracts.check("company_operating_metrics", bad)
        self.assertFalse(ok)
        self.assertIn("digit_from_label", reason)
        good = {**bad, "value": 12.0, "quote": "Added 12 new stores in Q4 FY26"}
        ok, reason = contracts.check("company_operating_metrics", good)
        self.assertTrue(ok, reason)


class ContractCoverageTest(unittest.TestCase):
    def test_contracts_cover_the_sixteen_measure_tables(self):
        self.assertEqual(len(x.TABLES), 16)
        self.assertEqual(set(contracts.CONTRACTS), set(x.TABLES))

    def test_evidence_is_typed(self):
        row = {"period_end": PERIOD, "metric": "nim_pct", "value": 9.5, "unit": "pct",
               "known_at": KNOWN, "quote": "NIM of 9.5%"}
        ok, reason = contracts.check("lender_metrics", row)
        self.assertFalse(ok)
        self.assertIn("page_missing", reason)
        # An XBRL filing and a BSE headline are the other two legal evidence kinds.
        xbrl = {"period_end": PERIOD, "basis": "consolidated", "line_item": "total_assets",
                "value_cr": 252264.0, "source": "results_xbrl", "page": None,
                "known_at": KNOWN, "doc_id": "x.xml",
                "quote": "Assets[OneI]=2522640000000 INR @2026-03-31"}
        self.assertEqual(contracts.check("balance_sheet_lines", xbrl), (True, None))
        self.assertEqual(contracts.check("rating_action", {
            "action_date": PERIOD, "direction": "upgrade", "amount_cr": None,
            "known_at": KNOWN, "page": None, "source_doc_id": "bse_ann:1",
            "quote": "CRISIL upgraded the rating to AA+/stable"}), (True, None))

    def test_rejects_are_counted_per_measure(self):
        counts = contracts.reject_summary(
            ["contract:nim_pct:value_above_range", "contract:nim_pct:measure_term_absent",
             "contract:intake_cr:measure_term_absent", "insert:not null"])
        self.assertEqual(counts["nim_pct"], 2)
        self.assertEqual(counts["intake_cr"], 1)
        self.assertEqual(contracts.measure_of("contract:nim_pct:value_above_range"), "nim_pct")


class WriteGateTest(unittest.TestCase):
    """Every measure-table write goes through `_write` and its contract."""

    BAD = {"known_at": KNOWN, "quote": "The document printed 10 crore and 5%."}

    def test_each_of_the_sixteen_tables_rejects_a_bad_row_at_write(self):
        con = sqlite3.connect(":memory:")
        con.executescript(x.DDL)
        try:
            for table in x.TABLES:
                inserted, rejected = Counter(), Counter()
                x._write(con, table, [dict(self.BAD)], inserted, rejected)
                self.assertEqual(inserted[table], 0, table)
                self.assertEqual(con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 0,
                                 table)
                reasons = [row[0] for row in con.execute(
                    "SELECT reason FROM extract_reject WHERE table_name = ?", (table,))]
                self.assertTrue(reasons, table)
                self.assertTrue(all(str(r).startswith("contract:") for r in reasons),
                                f"{table}: {reasons}")
        finally:
            con.close()

    def test_write_is_the_only_insert_path(self):
        self.assertIn("contracts.check", inspect.getsource(x._write))
        pattern = re.compile(r"(?i)INSERT\s+(?:OR\s+IGNORE\s+)?INTO\s+("
                             + "|".join(x.TABLES) + r")\b")
        for name, member in vars(x).items():
            if name == "_write" or not inspect.isfunction(member):
                continue
            self.assertIsNone(pattern.search(inspect.getsource(member)), name)
        from reality_engine.pilot import proto3
        source = Path(proto3.__file__).read_text(encoding="utf-8")
        for table in x.TABLES:
            self.assertNotRegex(source, r"(?i)INSERT\s+(?:OR\s+IGNORE\s+)?INTO\s+"
                                + table + r"\b")

    def test_dryrun_command_is_registered(self):
        from reality_engine.pilot import proto3
        self.assertTrue(callable(proto3.cmd_dryrun))


DENSE_BODY = " ".join(f"{i} crore" for i in range(1, 21))   # 20 numbers, 40 words


class WholePageTest(unittest.TestCase):
    """Number-dense pages go to the reader whole, split only at its input limit."""

    DOC = {"doc_id": "sha256:dense", "doc_type": "annual_report", "isin": "INE000000001",
           "symbol_at_time": "DENSE", "event_date": "2026-05-01", "known_at": KNOWN,
           "fiscal_period": "FY26"}

    def test_dense_page_is_selected_whole_without_a_keyword(self):
        chunk = {"chunk_id": 9, "doc_id": self.DOC["doc_id"], "section": "",
                 "body": DENSE_BODY + " with no segment word in it", "page_from": 200,
                 "page_to": 200, "tags": set()}
        passages = x.select_passages(x.SPECS["company_segment_pnl"], self.DOC, [chunk])
        self.assertEqual([p["chunk_id"] for p in passages], [9])
        self.assertTrue(passages[0]["dense"])
        plain = {**chunk, "body": "Revenue was strong this year and grew again."}
        self.assertEqual(x.select_passages(x.SPECS["company_segment_pnl"], self.DOC,
                                           [plain]), [])

    def test_dense_page_is_not_cut_at_the_plain_budget(self):
        body = " ".join(f"{i} crore" for i in range(1, 2000))
        self.assertGreater(len(body), x.MAX_PASSAGE_CHARS)
        text, used = x.passage_block([{"body": body, "page_from": 1, "dense": True}])
        self.assertEqual(used, len(body))
        self.assertGreater(len(text), x.MAX_PASSAGE_CHARS)

    def test_a_block_splits_only_at_the_reader_input_limit(self):
        passages = [{"body": "x" * 60, "page_from": 1, "dense": True},
                    {"body": "y" * 60, "page_from": 2, "dense": True}]
        with unittest.mock.patch.object(x, "READER_INPUT_LIMIT_CHARS", 100):
            self.assertEqual(len(x.split_passages(passages)), 2)
        self.assertEqual(len(x.split_passages(passages)), 1)

    def test_whole_page_estimate_makes_no_model_call(self):
        chunk = {"chunk_id": 9, "doc_id": self.DOC["doc_id"], "section": "",
                 "body": DENSE_BODY, "page_from": 200, "page_to": 200, "tags": set()}
        est = x.whole_page_estimate({self.DOC["doc_id"]: self.DOC},
                                    {self.DOC["doc_id"]: [chunk]},
                                    tables=["company_segment_pnl"])
        self.assertEqual(est["calls"], 1)
        self.assertGreater(est["dense_input_tokens"], 0)
        self.assertGreater(est["cost_usd"], 0.0)
        self.assertEqual(est["cost_usd"],
                         round(est["input_tokens"] / 1e6 * x.PRICE_IN, 4))


class XbrlEvidenceTest(unittest.TestCase):
    def test_xbrl_crore_value_matches_its_rupees_quote(self):
        row = {"period_end": PERIOD, "basis": "consolidated", "line_item": "total_assets",
               "value_cr": 252264.0, "source": "results_xbrl", "page": None,
               "known_at": "2024-10-28T18:00:00", "doc_id": "xbrl.xml",
               "quote": "Assets[OneI]=2522640000000 INR @2024-09-30"}
        self.assertEqual(contracts.check("balance_sheet_lines", row), (True, None))
        bad = {**row, "quote": "Assets[OneI]=9999000000000 INR @2024-09-30"}
        ok, reason = contracts.check("balance_sheet_lines", bad)
        self.assertFalse(ok)
        self.assertIn("value_not_in_quote", reason)


if __name__ == "__main__":
    unittest.main()
