"""Acceptance checks for the pilot-60 artifacts (golden-rule step 4).

    python -m unittest reality_engine.tests.test_pilot60

Skips when the generated artifacts are not present (they are built by the job).
"""
from __future__ import annotations

import csv
import importlib.util
import json
import shutil
import sqlite3
import sys
import unittest
import uuid
from collections import Counter
from contextlib import contextmanager
from pathlib import Path

import pymupdf

from reality_engine.scripts import fetch_results_notes_text

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "tasks" / "pilot60"
BANK = REPO / "tasks" / "master_bank" / "MASTER_BANK.jsonl"
BASE = REPO / ".tmp" / "pilot60-tests"


@contextmanager
def _tempdir(name: str):
    """Workspace temp dir (the OS temp dir is not writable under the DSH sandbox)."""
    path = BASE / f"{name}-{uuid.uuid4().hex[:8]}"
    path.mkdir(parents=True, exist_ok=True)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def _pdf(path: Path, pages: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open()
    for text in pages:
        page = doc.new_page()
        if text:
            page.insert_text((72, 72), text)
    doc.save(path)
    doc.close()


class Pilot60Test(unittest.TestCase):
    def test_universe(self):
        path = OUT / "UNIVERSE.csv"
        if not path.is_file():
            self.skipTest("UNIVERSE.csv not built")
        rows = list(csv.DictReader(path.open(encoding="utf-8")))
        self.assertEqual(len(rows), 60)
        self.assertEqual(len({r["isin"] for r in rows}), 60)
        buckets = Counter(r["bucket"] for r in rows)
        self.assertEqual(buckets, {"LARGE": 10, "MID-SMALL": 20, "MICRO": 30})
        self.assertGreaterEqual(len({r["sector"] for r in rows}), 15)

    def test_instances_cover_the_bank(self):
        path = OUT / "INSTANCES.jsonl"
        if not path.is_file():
            self.skipTest("INSTANCES.jsonl not built")
        rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
        bank = {json.loads(x)["mid"] for x in BANK.read_text(encoding="utf-8").splitlines()
                if x.strip()}
        covered = {r["parent_mid"] for r in rows}
        self.assertGreaterEqual(len(covered & bank) / len(bank), 0.90)
        stack = Counter((r["kind"], r.get("bucket")) for r in rows)
        self.assertEqual(stack[("stock", "LARGE")], stack[("stock", "MID-SMALL")])
        self.assertEqual(stack[("stock", "LARGE")], stack[("stock", "MICRO")])
        for row in rows:
            for key in ("mid", "parent_mid", "kind", "entities", "shift"):
                self.assertIn(key, row)

    def test_report_breakdowns(self):
        path = OUT / "REPORT.md"
        if not path.is_file():
            self.skipTest("REPORT.md not built")
        text = path.read_text(encoding="utf-8")
        for heading in ("By sector", "By family", "By entity level", "Bucket x family",
                        "PIT", "Latency", "Hand check"):
            self.assertIn(heading, text)


class ResultsNotesResolutionTest(unittest.TestCase):
    """The T2 results-notes resolver and the fetch script's ISIN filter / out-db."""

    ISIN_A = "INE002A01018"
    ISIN_B = "INE009A01021"

    @staticmethod
    def _builder():
        spec = importlib.util.spec_from_file_location(
            f"build_chunks_v3_{uuid.uuid4().hex[:8]}",
            REPO / "tasks" / "pilot_t2" / "build_chunks_v3.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module  # dataclasses resolve annotations via sys.modules
        spec.loader.exec_module(module)
        return module

    def test_resolves_stored_pages_then_pname_pdf(self):
        with _tempdir("results-resolve") as tmp:
            b = self._builder()
            pname_a = "aaaaaaaa-1111-1111-1111-111111111111.pdf"
            pname_b = "bbbbbbbb-2222-2222-2222-222222222222.pdf"
            con = sqlite3.connect(tmp / "equity_intelligence.db")
            con.execute("""CREATE TABLE corporate_documents (id INTEGER PRIMARY KEY, isin TEXT,
                           symbol TEXT, title TEXT, publication_date TEXT, bse_dissem_ts TEXT,
                           sha256_hash TEXT, source_url TEXT, fiscal_period_end TEXT, doc_type TEXT)""")
            for doc_id, (pname, ts) in enumerate(((pname_a, "2026-08-01T17:23:15.117"),
                                                  (pname_b, "2026-07-24T13:42:22.61")), start=1):
                con.execute("INSERT INTO corporate_documents VALUES (?,?,?,?,?,?,?,?,?,?)",
                            (doc_id, self.ISIN_A, "TEST", f"Results {doc_id}", None, ts, None,
                             f"https://www.bseindia.com/stockinfo/AnnPdfOpen.aspx?Pname={pname}",
                             None, "FINANCIAL_RESULT"))
            con.commit()
            con.close()
            con = sqlite3.connect(tmp / "bse_announcements.db")
            con.execute("CREATE TABLE ann (NEWSID TEXT, SCRIP_CD TEXT, ATTACHMENTNAME TEXT, "
                        "CATEGORYNAME TEXT, DissemDT TEXT)")
            con.execute("INSERT INTO ann VALUES (?,?,?,?,?)",
                        ("news-a", "500001", pname_a, "Result", "2026-08-01T17:23:15.117"))
            con.execute("INSERT INTO ann VALUES (?,?,?,?,?)",
                        ("news-b", "500001", pname_b, "Result", "2026-07-24T13:42:22.61"))
            con.commit()
            con.close()
            store = tmp / "results_notes.db"
            con = sqlite3.connect(store)
            con.execute("""CREATE TABLE results_notes (isin TEXT NOT NULL, period_end TEXT NOT NULL,
                           source_newsid TEXT NOT NULL, page_no INTEGER NOT NULL, text TEXT NOT NULL,
                           known_at TEXT, has_note_word INTEGER NOT NULL DEFAULT 0,
                           PRIMARY KEY (isin, period_end, source_newsid, page_no))""")
            con.executemany("INSERT INTO results_notes VALUES (?,?,?,?,?,?,?)", [
                (self.ISIN_A, "2026-06-30", "news-a", 1,
                 "Notes to the results: segment information.", "2026-08-01T17:23:15.117", 1),
                (self.ISIN_A, "2026-06-30", "news-a", 2,
                 "Auditor qualification follows.", "2026-08-01T17:23:15.117", 0)])
            con.commit()
            con.close()
            raw = tmp / "raw"
            (raw / "results_notes_text").mkdir(parents=True)
            (raw / "results_notes_text" / pname_b).write_bytes(b"%PDF-1.4")  # Pname fallback only

            b.DATA = tmp
            b.RESULTS_NOTES_DB = store
            b.RESULTS_RAW = raw
            b.CUTOFF = "2024-04-01"
            drafts = {d.source_ref: d for d in b.load_results_notes([self.ISIN_A], b._NoIndex())}

            self.assertEqual(set(drafts), {"1", "2"})
            stored = drafts["1"]
            self.assertEqual(stored.pages, ["Notes to the results: segment information.",
                                            "Auditor qualification follows."])
            self.assertEqual(stored.meta.known_at, "2026-08-01T17:23:15")
            self.assertEqual(stored.meta.known_at_src, "bse_dissem")
            self.assertEqual(stored.meta.fiscal_period, "Q1FY27")
            fallback = drafts["2"]
            self.assertIsNone(fallback.pages)
            self.assertEqual(fallback.path.name, pname_b)
            self.assertEqual(fallback.meta.known_at, "2026-07-24T13:42:22")

    def test_isin_filter_writes_only_requested_isin_to_out_db(self):
        with _tempdir("results-isin") as tmp:
            db = tmp / "results_xbrl.db"
            con = sqlite3.connect(db)
            con.execute("""CREATE TABLE filings (file TEXT, isin TEXT, scrip_code TEXT,
                           period_end TEXT, broadcast_ts TEXT, filing_ts TEXT, status TEXT)""")
            for isin, code in ((self.ISIN_A, "500001"), (self.ISIN_B, "500002")):
                con.execute("INSERT INTO filings VALUES (?,?,?,?,?,?,?)",
                            (f"{isin}.xml", isin, code, "2026-06-30",
                             "2026-08-01T17:39:05", "2026-08-01T17:39:05", "ok"))
            con.commit()
            con.close()
            ann_db = tmp / "bse_announcements.db"
            con = sqlite3.connect(ann_db)
            con.execute("CREATE TABLE ann (NEWSID TEXT, SCRIP_CD TEXT, ATTACHMENTNAME TEXT, "
                        "CATEGORYNAME TEXT, DissemDT TEXT)")
            con.execute("INSERT INTO ann VALUES (?,?,?,?,?)",
                        ("n1", "500001", "x.pdf", "Result", "2026-08-01T17:23:15.117"))
            con.execute("INSERT INTO ann VALUES (?,?,?,?,?)",
                        ("n2", "500002", "y.pdf", "Result", "2026-08-01T17:23:15.117"))
            con.commit()
            con.close()
            raw = tmp / "raw"
            _pdf(raw / "results_notes_text" / "n1.pdf", ["Notes to accounts: page one."])
            _pdf(raw / "results_notes_text" / "n2.pdf", ["Other company page."])
            isin_file = tmp / "isins.txt"
            isin_file.write_text(f"{self.ISIN_A}\n", encoding="utf-8")
            out = tmp / "out" / "results_notes.db"

            rc = fetch_results_notes_text.main([
                "--db", str(db), "--ann-db", str(ann_db), "--raw-root", str(raw),
                "--out-db", str(out), "--isins-file", str(isin_file), "--offline"])

            self.assertEqual(rc, 0)
            con = sqlite3.connect(out)
            self.assertEqual([r[0] for r in con.execute(
                "SELECT DISTINCT isin FROM results_notes")], [self.ISIN_A])
            hits = con.execute("SELECT COUNT(*) FROM results_notes_fts "
                               "WHERE results_notes_fts MATCH 'accounts'").fetchone()[0]
            self.assertEqual(hits, 1)
            con.close()
            con = sqlite3.connect(db)
            self.assertEqual(con.execute("SELECT COUNT(*) FROM sqlite_master "
                                         "WHERE name='results_notes'").fetchone()[0], 0,
                             "the source database is never written")
            con.close()


if __name__ == "__main__":
    unittest.main()
