"""Tests for the three G2 feeds: deck page text, results notes, ETF premium.

Everything runs on temporary SQLite files and temporary raw roots; no live
database is opened and no network call is made (``--offline`` + cached PDFs).
"""
from __future__ import annotations

import shutil
import sqlite3
import unittest
import uuid
from contextlib import contextmanager
from pathlib import Path

import pymupdf
import yaml

from reality_engine.scripts import build_deck_page_text, build_etf_premium, fetch_results_notes_text

REPO = Path(__file__).resolve().parents[2]
BASE = REPO / ".tmp" / "g2-tests"


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


class DeckPageTextTest(unittest.TestCase):
    def test_extracts_pages_and_resumes(self):
        with _tempdir("deck") as tmp:
            db = tmp / "deck_figures.db"
            raw = tmp / "raw"
            source = tmp / "deck.pdf"
            _pdf(source, ["Revenue from operations grew strongly this quarter.", ""])
            sha = "a" * 64
            con = sqlite3.connect(db)
            con.execute("CREATE TABLE deck_sources (sha256 TEXT, local_path TEXT, known_at TEXT, status TEXT)")
            con.execute("INSERT INTO deck_sources VALUES (?,?,?,?)", (sha, str(source), "2026-09-29T10:00:00", "ok"))
            con.execute("INSERT INTO deck_sources VALUES (?,?,?,?)",
                        ("b" * 64, str(tmp / "missing.pdf"), "2026-09-28T10:00:00", "ok"))
            con.commit()
            con.close()

            rc = build_deck_page_text.main(["--db", str(db), "--raw-root", str(raw), "--offline"])
            self.assertEqual(rc, 0)
            con = sqlite3.connect(db)
            rows = con.execute("SELECT sha256, page_no, chars, method FROM deck_page_text ORDER BY page_no").fetchall()
            self.assertEqual([r[1] for r in rows], [1, 2])
            self.assertTrue(all(r[0] == sha for r in rows))
            self.assertEqual([r[3] for r in rows], ["pymupdf", "empty"])
            self.assertGreaterEqual(rows[0][2], build_deck_page_text.EMPTY_CHARS)
            hits = con.execute("SELECT COUNT(*) FROM deck_page_text_fts WHERE deck_page_text_fts MATCH 'revenue'").fetchone()[0]
            self.assertEqual(hits, 1)
            con.close()

            # Second run is a no-op: same two pages, no duplicates.
            build_deck_page_text.main(["--db", str(db), "--raw-root", str(raw), "--offline"])
            con = sqlite3.connect(db)
            self.assertEqual(con.execute("SELECT COUNT(*) FROM deck_page_text").fetchone()[0], 2)
            con.close()

    def test_since_and_limit(self):
        with _tempdir("deck") as tmp:
            db = tmp / "deck_figures.db"
            con = sqlite3.connect(db)
            con.execute("CREATE TABLE deck_sources (sha256 TEXT, local_path TEXT, known_at TEXT, status TEXT)")
            for index, day in enumerate(("2026-01-01", "2026-02-01", "2026-03-01")):
                _pdf(tmp / f"{index}.pdf", ["Some page text long enough to be real."])
                con.execute("INSERT INTO deck_sources VALUES (?,?,?,?)",
                            (str(index) * 64, str(tmp / f"{index}.pdf"), f"{day}T00:00:00", "ok"))
            con.commit()
            con.close()
            build_deck_page_text.main(["--db", str(db), "--raw-root", str(tmp / "raw"),
                                       "--offline", "--since", "2026-02-01", "--limit", "1"])
            con = sqlite3.connect(db)
            self.assertEqual(con.execute("SELECT COUNT(DISTINCT sha256) FROM deck_page_text").fetchone()[0], 1)
            con.close()


class ResultsNotesTest(unittest.TestCase):
    def test_matches_announcement_and_keeps_note_pages(self):
        with _tempdir("deck") as tmp:
            db = tmp / "results_xbrl.db"
            ann_db = tmp / "bse_announcements.db"
            raw = tmp / "raw"
            newsid = "11111111-1111-1111-1111-111111111111"
            _pdf(raw / "results_notes_text" / f"{newsid}.pdf",
                 ["Balance sheet and cash flow statement without the keyword.",
                  "Notes to the financial results. Note 5: segment information by geography."])

            con = sqlite3.connect(db)
            con.execute("""CREATE TABLE filings (file TEXT, isin TEXT, scrip_code TEXT, period_end TEXT,
                           broadcast_ts TEXT, filing_ts TEXT, status TEXT)""")
            con.execute("INSERT INTO filings VALUES (?,?,?,?,?,?,?)",
                        ("f.xml", "INE270I01022", "516072", "2026-06-30",
                         "2026-08-01T17:39:05", "2026-08-01T17:39:06", "ok"))
            con.commit()
            con.close()

            con = sqlite3.connect(ann_db)
            con.execute("CREATE TABLE ann (NEWSID TEXT, SCRIP_CD TEXT, ATTACHMENTNAME TEXT, "
                        "CATEGORYNAME TEXT, DissemDT TEXT)")
            con.execute("INSERT INTO ann VALUES (?,?,?,?,?)",
                        (newsid, "516072", "x.pdf", "Result", "2026-08-01T17:23:15.117"))
            con.execute("INSERT INTO ann VALUES (?,?,?,?,?)",
                        ("other", "516072", "y.pdf", "Company Update", "2026-08-01T17:30:00.000"))
            con.commit()
            con.close()

            rc = fetch_results_notes_text.main(["--db", str(db), "--ann-db", str(ann_db),
                                                "--raw-root", str(raw), "--offline"])
            self.assertEqual(rc, 0)
            con = sqlite3.connect(db)
            rows = con.execute("SELECT isin, period_end, source_newsid, page_no, known_at "
                               "FROM results_notes").fetchall()
            self.assertEqual(rows, [("INE270I01022", "2026-06-30", newsid, 2, "2026-08-01T17:23:15.117")])
            hits = con.execute("SELECT COUNT(*) FROM results_notes_fts WHERE results_notes_fts MATCH 'note'").fetchone()[0]
            self.assertEqual(hits, 1)
            con.close()

            fetch_results_notes_text.main(["--db", str(db), "--ann-db", str(ann_db),
                                           "--raw-root", str(raw), "--offline"])
            con = sqlite3.connect(db)
            self.assertEqual(con.execute("SELECT COUNT(*) FROM results_notes").fetchone()[0], 1)
            con.close()


class EtfPremiumTest(unittest.TestCase):
    def test_upsert_and_inav_gap(self):
        with _tempdir("etf") as tmp:
            db = Path(tmp) / "equity_intelligence.db"
            con = sqlite3.connect(db)
            con.executescript("""
                CREATE TABLE etf_px (date TEXT, symbol TEXT, isin TEXT, close REAL, volume REAL,
                                     value_inr REAL, source TEXT, PRIMARY KEY (date, symbol));
                CREATE TABLE fund_nav (isin TEXT, date TEXT, nav REAL, scheme_code TEXT, scheme_name TEXT,
                                       PRIMARY KEY (isin, date));
                CREATE TABLE etf_inav (isin TEXT, date TEXT, underlying TEXT, idx_close REAL, idx_date TEXT,
                                       fx REAL, k REAL, inav REAL, close REAL, nav REAL,
                                       premium_vs_inav_pct REAL, PRIMARY KEY (isin, date));
                CREATE VIEW etf_premium AS SELECT p.isin, p.symbol, p.date, p.close, n.nav,
                    100.0 * (p.close / n.nav - 1) AS premium_pct, p.value_inr
                    FROM etf_px p JOIN fund_nav n ON n.isin = p.isin AND n.date = p.date;
            """)
            con.execute("INSERT INTO etf_px VALUES ('2026-09-10','MONQ50','INF247L01AU3',200.0,1,2000.0,'nse')")
            con.execute("INSERT INTO etf_px VALUES ('2026-09-11','MONQ50','INF247L01AU3',220.0,1,2200.0,'nse')")
            con.execute("INSERT INTO fund_nav VALUES ('INF247L01AU3','2026-09-10',100.0,'1','x')")
            con.execute("INSERT INTO fund_nav VALUES ('INF247L01AU3','2026-09-11',110.0,'1','x')")
            con.execute("INSERT INTO etf_inav VALUES ('INF247L01AU3','2026-09-10','^NXTQ',1,1,1,1,105.0,200.0,100.0,90.0)")
            con.commit()
            con.close()

            rc = build_etf_premium.main(["--db", str(db)])
            self.assertEqual(rc, 0)
            con = sqlite3.connect(db)
            kind = con.execute("SELECT type FROM sqlite_master WHERE name='etf_premium'").fetchone()[0]
            self.assertEqual(kind, "view")
            rows = con.execute("SELECT date, close, nav, premium_pct, inav, inav_gap_pct "
                               "FROM etf_premium ORDER BY date").fetchall()
            self.assertEqual(len(rows), 2)
            self.assertAlmostEqual(rows[0][3], 100.0)
            self.assertAlmostEqual(rows[0][5], 90.0)
            self.assertIsNone(rows[1][4])
            self.assertIsNone(rows[1][5])
            con.close()

            # Idempotent re-run: still two rows, not four.
            build_etf_premium.main(["--db", str(db)])
            con = sqlite3.connect(db)
            self.assertEqual(con.execute("SELECT COUNT(*) FROM etf_premium").fetchone()[0], 2)
            con.close()


class JobsYamlTest(unittest.TestCase):
    def test_new_entries_are_disabled_and_locked(self):
        registry = yaml.safe_load((REPO / "plugins/dsh-worker/jobs.yaml").read_text(encoding="utf-8"))
        jobs = {job["name"]: job for job in registry["jobs"]}
        expected = {
            "deck_page_text": ("reality_engine.scripts.build_deck_page_text", "deck_figures.db:deck_page_text"),
            "results_notes_text": ("reality_engine.scripts.fetch_results_notes_text", "results_xbrl.db:results_notes"),
            "etf_premium": ("reality_engine.scripts.build_etf_premium", "equity_intelligence.db:etf_premium"),
        }
        for name, (module, write) in expected.items():
            job = jobs[name]
            self.assertFalse(job["enabled"])
            self.assertIn(module, job["argv"])
            self.assertIn(write, job["writes"])
            self.assertTrue(all(lock.startswith(("db:", "net:", "gpu")) for lock in job["resource_locks"]))
            self.assertIsInstance(job["success_check"], dict)


if __name__ == "__main__":
    unittest.main()
