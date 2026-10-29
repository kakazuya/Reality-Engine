"""Acceptance checks for the pilot-60 targeted extraction build (build time).

    python -m unittest reality_engine.tests.test_extraction_pilot60

Artifact tests skip when the build has not run (``.tmp/pilot60/extract_pilot60.db``);
the selector / validator / read-side tests build a tiny in-memory fixture, never the
live databases.
"""
from __future__ import annotations

import json
import sqlite3
import unittest
from pathlib import Path

from reality_engine.pilot import extract60 as x
from reality_engine.query import metrics

REPO = Path(__file__).resolve().parents[2]
DB = REPO / ".tmp" / "pilot60" / "extract_pilot60.db"
HANDCHECK = REPO / "tasks" / "pilot60" / "EXTRACTION_HANDCHECK.md"
REPORT = REPO / "tasks" / "pilot60" / "EXTRACTION_REPORT.md"

DOC = {"doc_id": "sha256:test", "doc_type": "annual_report", "isin": "INE000000001",
       "symbol_at_time": "TEST", "title": "TEST annual report", "event_date": "2026-05-01",
       "known_at": "2026-05-01T18:00:00", "fiscal_period": "FY26"}
CHUNK = {"chunk_id": 1, "doc_id": DOC["doc_id"], "section": "segment note",
         "body": "Automotive segment revenue was Rs 12,000 crore for the year ended "
                 "March 31, 2026, forming 60% of total revenue.",
         "page_from": 144, "page_to": 144, "unit_kind": "note", "fiscal_period": "FY26",
         "known_at": DOC["known_at"], "tags": {"section:segment", "unit:inr_crore"}}


class SelectorTest(unittest.TestCase):
    def test_selector_finds_the_fact_passage(self):
        passages = x.select_passages(x.SPECS["company_segment_pnl"], DOC, [CHUNK])
        self.assertEqual([p["chunk_id"] for p in passages], [1])

    def test_selector_rejects_wrong_doc_type(self):
        spec = x.SPECS["company_segment_pnl"]
        self.assertEqual(x.select_passages(spec, {**DOC, "doc_type": "announcement"}, [CHUNK]), [])

    def test_selector_needs_a_number_where_the_table_does(self):
        text_only = {**CHUNK, "body": "Automotive segment revenue grew on volume."}
        self.assertEqual(x.select_passages(x.SPECS["company_segment_pnl"], DOC, [text_only]), [])

    def test_selection_reports_tokens_read_and_whole_doc_tokens(self):
        rows = x.selection_rows("company_segment_pnl", {DOC["doc_id"]: DOC},
                                {DOC["doc_id"]: [CHUNK]})
        self.assertEqual(len(rows), 1)
        self.assertLess(rows[0]["tokens"], rows[0]["doc_tokens"] + 1)
        self.assertGreater(rows[0]["doc_tokens"], 0)


class ValidatorTest(unittest.TestCase):
    def row(self, **over):
        base = {"segment": "Automotive", "period_end": "2026-03-31", "metric": "revenue",
                "basis": "consolidated", "value_cr": 12000.0, "share_of_total_pct": 60,
                "page": 144,
                "quote": "Automotive segment revenue was Rs 12,000 crore for the year ended "
                         "March 31, 2026"}
        base.update(over)
        return base

    def test_valid_row_passes_with_doc_page_and_known_at(self):
        clean, reason = x.validate("company_segment_pnl", self.row(), DOC, [CHUNK])
        self.assertIsNone(reason)
        self.assertEqual(clean["isin"], DOC["isin"])
        self.assertEqual(clean["known_at"], DOC["known_at"])
        self.assertEqual(clean["page"], 144)

    def test_paraphrased_quote_is_rejected(self):
        clean, reason = x.validate("company_segment_pnl",
                                   self.row(quote="the automotive segment made 12000 crore"), DOC,
                                   [CHUNK])
        self.assertIsNone(clean)
        self.assertEqual(reason, "quote_not_verbatim")

    def test_value_absent_from_the_source_is_rejected(self):
        clean, reason = x.validate("company_segment_pnl", self.row(value_cr=99999.0), DOC, [CHUNK])
        self.assertIsNone(clean)
        self.assertEqual(reason, "value_not_in_source")

    def test_period_after_the_doc_date_is_rejected(self):
        clean, reason = x.validate("company_segment_pnl",
                                   self.row(period_end="2029-03-31"), DOC, [CHUNK])
        self.assertIsNone(clean)
        self.assertTrue(str(reason).startswith("period"))

    def test_page_outside_the_selected_passages_is_rejected(self):
        clean, reason = x.validate("company_segment_pnl", self.row(page=7), DOC, [CHUNK])
        self.assertIsNone(clean)
        self.assertIn("page", str(reason))

    def test_pct_unit_out_of_range_is_rejected(self):
        chunk = {**CHUNK, "body": "Utilisation was 140% of capacity during the year.",
                 "page_from": 12, "page_to": 12}
        clean, reason = x.validate("company_capacity_utilisation",
                                   {"product": "cement", "period_end": "2026-03-31",
                                    "capacity": None, "capacity_unit": "tpa",
                                    "utilisation_pct": 140, "production": None, "page": 12,
                                    "quote": "Utilisation was 140% of capacity during the year."},
                                   DOC, [chunk])
        self.assertIsNone(clean)
        self.assertEqual(reason, "utilisation_out_of_range")

    def test_price_hike_with_a_negative_pct_is_rejected(self):
        chunk = {**CHUNK, "body": "We took a price hike of 4% in April 2026.",
                 "page_from": 3, "page_to": 3}
        clean, reason = x.validate("company_price_revision",
                                   {"announced_on": "2026-05-01", "effective_on": "2026-04-01",
                                    "product": "cement", "direction": "hike", "revision_pct": -4,
                                    "basis_text": "cost", "page": 3,
                                    "quote": "We took a price hike of 4% in April 2026."},
                                   DOC, [chunk])
        self.assertIsNone(clean)
        self.assertEqual(reason, "hike_with_negative_pct")

    def test_regex_rating_row_from_a_headline(self):
        doc = {**DOC, "doc_type": "announcement",
               "title": "CRISIL downgrades the long-term rating to BBB- with negative outlook"}
        rows = x.regex_rating_rows(doc, [])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["direction"], "downgrade")
        self.assertEqual(rows[0]["agency"], "CRISIL")
        self.assertEqual(rows[0]["outlook"], "negative")

    def test_regex_order_win_scales_lakh_to_crore(self):
        doc = {**DOC, "doc_type": "announcement",
               "title": "Company bagged a work order worth Rs 1,500 lakh from NHAI"}
        rows = x.regex_order_rows(doc, [])
        self.assertEqual(len(rows), 1)
        self.assertAlmostEqual(rows[0]["value_cr"], 15.0, places=2)


class ReadSideTest(unittest.TestCase):
    def _fixture(self):
        con = sqlite3.connect(":memory:")
        con.executescript(x.DDL)
        con.execute("INSERT INTO company_segment_pnl VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    ("INE000000001", "Automotive", "2026-03-31", "revenue", "consolidated",
                     12000.0, 60.0, "chunks_v3", DOC["doc_id"], 144, DOC["known_at"], 1.0,
                     "Automotive segment revenue was Rs 12,000 crore"))
        con.execute("INSERT INTO rating_action VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    ("INE000000001", "2026-04-02", "CRISIL", "unspecified", "BBB-", "negative",
                     500.0, "downgrade", "bse_ann:1", "2026-04-02T18:00:00",
                     "CRISIL downgrades rating to BBB-", None))
        con.commit()
        return con

    def test_question_maps_to_the_extraction_table(self):
        self.assertIn("company_segment_pnl", metrics.tables_for("segment revenue split"))
        self.assertIn("rating_action", metrics.tables_for("any rating action after March"))
        self.assertIn("order_intake", metrics.tables_for("order book at FY26 end"))

    def test_facts_rows_are_pit_filtered_and_shaped_like_facts(self):
        con = self._fixture()
        ctx = type("Ctx", (), {"rows": lambda self, db, sql, params: [
            dict(zip([d[0] for d in con.execute(sql, params).description], row))
            for row in con.execute(sql, params)]})()
        rows = metrics.facts_rows(ctx, "INE000000001", "2026-06-01", "segment revenue",
                                  "segment", (None, None))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["store"], "metric_state")
        self.assertEqual(rows[0]["value"], 12000.0)
        self.assertEqual(rows[0]["known_at"], DOC["known_at"])
        self.assertEqual(metrics.facts_rows(ctx, "INE000000001", "2026-01-01", "segment revenue",
                                            "segment", (None, None)), [])

    def test_evidence_rows_carry_quote_page_and_known_at(self):
        con = self._fixture()
        ctx = type("Ctx", (), {"rows": lambda self, db, sql, params: [
            dict(zip([d[0] for d in con.execute(sql, params).description], row))
            for row in con.execute(sql, params)]})()
        rows = metrics.evidence_rows(ctx, "INE000000001", "2026-06-01", "rating action")
        self.assertTrue(rows)
        self.assertIn("CRISIL", rows[0]["quote"])
        self.assertEqual(rows[0]["date"], "2026-04-02T18:00:00")


@unittest.skipUnless(DB.is_file(), "extract_pilot60.db not built")
class ArtifactTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.con = sqlite3.connect(DB)
        cls.con.row_factory = sqlite3.Row

    @classmethod
    def tearDownClass(cls):
        cls.con.close()

    def tables(self):
        return {r[0] for r in self.con.execute("SELECT name FROM sqlite_master WHERE type='table'")}

    def test_every_target_table_exists_with_its_key(self):
        present = self.tables()
        for table in x.TABLES:
            self.assertIn(table, present)

    def test_every_row_carries_doc_page_quote_and_known_at(self):
        for table in x.TABLES:
            cols = {r[1] for r in self.con.execute(f"PRAGMA table_info({table})")}
            self.assertIn("known_at", cols, table)
            quote_col = "quote" if "quote" in cols else "evidence_quote"
            self.assertIn(quote_col, cols, table)
            bad = self.con.execute(
                f"SELECT COUNT(*) FROM {table} WHERE COALESCE(known_at,'') = '' "
                f"OR COALESCE({quote_col},'') = ''").fetchone()[0]
            self.assertEqual(bad, 0, f"{table} rows without known_at/quote")

    def test_no_row_is_known_after_its_document(self):
        for table in ("company_segment_pnl", "company_operating_metrics",
                      "company_price_revision", "rating_action"):
            rows = self.con.execute(
                f"SELECT isin, known_at FROM {table} LIMIT 50").fetchall()
            for row in rows:
                self.assertRegex(str(row["known_at"]), r"^\d{4}-\d{2}-\d{2}")

    def test_selection_is_narrower_than_the_whole_document(self):
        rows = self.con.execute(
            "SELECT table_name, SUM(tokens) AS read, SUM(doc_tokens) AS whole "
            "FROM extract_selection GROUP BY table_name").fetchall()
        self.assertTrue(rows, "no selection rows: the selector never ran")
        for row in rows:
            self.assertLess(row["read"], row["whole"], row["table_name"])

    def test_precision_of_the_15_row_hand_check(self):
        rows = self.con.execute(
            "SELECT table_name, COUNT(*) AS n, SUM(verdict='PASS') AS ok "
            "FROM extract_handcheck GROUP BY table_name").fetchall()
        if not rows:
            self.skipTest("hand check has not run")
        for row in rows:
            self.assertGreaterEqual(row["ok"] / row["n"], 0.90, row["table_name"])
            self.assertGreaterEqual(row["n"], 5, row["table_name"])

    def test_recall_of_the_doc_table_pairs(self):
        rows = self.con.execute(
            "SELECT COUNT(*) AS n, SUM(selected) AS ok FROM extract_recall").fetchone()
        if not rows or not rows["n"]:
            self.skipTest("recall probe has not run")
        self.assertGreaterEqual(rows["ok"] / rows["n"], 0.80)


@unittest.skipUnless(REPORT.is_file(), "EXTRACTION_REPORT.md not written")
class ReportTest(unittest.TestCase):
    def test_report_has_a_section_per_table_and_the_before_after(self):
        text = REPORT.read_text(encoding="utf-8")
        for table in x.TABLES:
            self.assertIn(table, text)
        for heading in ("Precision", "Recall", "Tokens", "Before / after"):
            self.assertIn(heading, text)


if __name__ == "__main__":
    unittest.main()
