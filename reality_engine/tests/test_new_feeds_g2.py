"""Tests for the three G2 feeds: deck page text, results notes, ETF premium.

Everything runs on temporary SQLite files and temporary raw roots; no live
database is opened and no network call is made (``--offline`` + cached PDFs, or a
patched ``urlopen`` where the download itself is under test).
"""
from __future__ import annotations

import shutil
import sqlite3
import unittest
import uuid
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

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

    def test_since_newest_first_and_limit_progress(self):
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
            args = ["--db", str(db), "--raw-root", str(tmp / "raw"), "--offline",
                    "--since", "2026-02-01", "--limit", "1"]

            build_deck_page_text.main(args)
            con = sqlite3.connect(db)
            self.assertEqual([r[0] for r in con.execute("SELECT DISTINCT sha256 FROM deck_page_text")],
                             ["2" * 64], "newest eligible deck must be the one processed")
            con.close()

            # Second run with the same limit moves on to the next deck instead of stalling.
            build_deck_page_text.main(args)
            con = sqlite3.connect(db)
            stored = sorted(r[0] for r in con.execute("SELECT DISTINCT sha256 FROM deck_page_text"))
            self.assertEqual(stored, sorted(["1" * 64, "2" * 64]))
            con.close()


class ResultsNotesTest(unittest.TestCase):
    @staticmethod
    def _databases(tmp: Path) -> tuple[Path, Path]:
        db = tmp / "results_xbrl.db"
        con = sqlite3.connect(db)
        con.execute("""CREATE TABLE filings (file TEXT, isin TEXT, scrip_code TEXT, period_end TEXT,
                       broadcast_ts TEXT, filing_ts TEXT, status TEXT)""")
        con.commit()
        con.close()
        ann_db = tmp / "bse_announcements.db"
        con = sqlite3.connect(ann_db)
        con.execute("CREATE TABLE ann (NEWSID TEXT, SCRIP_CD TEXT, ATTACHMENTNAME TEXT, "
                    "CATEGORYNAME TEXT, DissemDT TEXT)")
        con.commit()
        con.close()
        return db, ann_db

    @staticmethod
    def _filing(db: Path, period_end: str = "2026-06-30", broadcast: str = "2026-08-01T17:39:05") -> None:
        con = sqlite3.connect(db)
        con.execute("INSERT INTO filings VALUES (?,?,?,?,?,?,?)",
                    ("f.xml", "INE270I01022", "516072", period_end, broadcast, broadcast, "ok"))
        con.commit()
        con.close()

    @staticmethod
    def _announcement(ann_db: Path, newsid: str, dissem: str = "2026-08-01T17:23:15.117",
                      category: str = "Result") -> None:
        con = sqlite3.connect(ann_db)
        con.execute("INSERT INTO ann VALUES (?,?,?,?,?)", (newsid, "516072", "x.pdf", category, dissem))
        con.commit()
        con.close()

    def _run(self, db: Path, ann_db: Path, raw: Path, *extra: str) -> int:
        return fetch_results_notes_text.main(["--db", str(db), "--ann-db", str(ann_db),
                                              "--raw-root", str(raw), "--offline", *extra])

    def test_stores_every_page_and_flags_note_pages(self):
        with _tempdir("notes") as tmp:
            db, ann_db = self._databases(tmp)
            raw = tmp / "raw"
            newsid = "11111111-1111-1111-1111-111111111111"
            _pdf(raw / "results_notes_text" / f"{newsid}.pdf",
                 ["Balance sheet and cash flow statement without the keyword.",
                  "Notes to the financial results. Note 5: segment information by geography.",
                  ""])
            self._filing(db)
            self._announcement(ann_db, newsid)

            self.assertEqual(self._run(db, ann_db, raw), 0)
            con = sqlite3.connect(db)
            rows = con.execute("SELECT page_no, has_note_word, length(text) > 0 "
                               "FROM results_notes ORDER BY page_no").fetchall()
            self.assertEqual(rows, [(1, 0, 1), (2, 1, 1), (3, 0, 0)])
            hits = con.execute("SELECT COUNT(*) FROM results_notes_fts "
                               "WHERE results_notes_fts MATCH 'note'").fetchone()[0]
            self.assertEqual(hits, 1)
            con.close()

            # A complete store is a no-op on the next run.
            self._run(db, ann_db, raw)
            con = sqlite3.connect(db)
            self.assertEqual(con.execute("SELECT COUNT(*) FROM results_notes").fetchone()[0], 3)
            con.close()

    def test_each_matching_announcement_is_kept(self):
        with _tempdir("notes") as tmp:
            db, ann_db = self._databases(tmp)
            raw = tmp / "raw"
            standalone = "aaaaaaaa-1111-1111-1111-111111111111"
            consolidated = "bbbbbbbb-2222-2222-2222-222222222222"
            _pdf(raw / "results_notes_text" / f"{standalone}.pdf", ["Standalone results page."])
            _pdf(raw / "results_notes_text" / f"{consolidated}.pdf", ["Consolidated results page."])
            self._filing(db)  # one NSE filing at 17:39:05
            self._announcement(ann_db, standalone, dissem="2026-08-01T17:23:15.117")
            self._announcement(ann_db, consolidated, dissem="2026-08-01T17:41:00.000")

            self.assertEqual(self._run(db, ann_db, raw), 0)
            con = sqlite3.connect(db)
            stored = con.execute("SELECT source_newsid, COUNT(*) FROM results_notes "
                                 "GROUP BY source_newsid ORDER BY source_newsid").fetchall()
            self.assertEqual(stored, [(standalone, 1), (consolidated, 1)],
                             "both bases must be stored, not only the nearest announcement")
            con.close()

    def test_limit_progresses_across_runs(self):
        with _tempdir("notes") as tmp:
            db, ann_db = self._databases(tmp)
            raw = tmp / "raw"
            newest = "aaaaaaaa-1111-1111-1111-111111111111"
            older = "bbbbbbbb-2222-2222-2222-222222222222"
            _pdf(raw / "results_notes_text" / f"{newest}.pdf", ["latest quarter page"])
            _pdf(raw / "results_notes_text" / f"{older}.pdf", ["older quarter page"])
            self._filing(db, period_end="2026-06-30", broadcast="2026-08-01T17:39:05")
            self._filing(db, period_end="2026-09-30", broadcast="2026-11-10T17:39:05")
            self._announcement(ann_db, newest, dissem="2026-11-10T17:23:15.117")
            self._announcement(ann_db, older, dissem="2026-08-01T17:23:15.117")
            args = ("--limit", "1")

            self.assertEqual(self._run(db, ann_db, raw, *args), 0)
            con = sqlite3.connect(db)
            self.assertEqual([r[0] for r in con.execute("SELECT DISTINCT source_newsid FROM results_notes")],
                             [newest], "the first run must process the newest announcement")
            con.close()

            # Old defect: the limit was applied before the done-check, so run two re-picked
            # the same (now skipped) filing and stored nothing.
            self.assertEqual(self._run(db, ann_db, raw, *args), 0)
            con = sqlite3.connect(db)
            self.assertEqual(sorted(r[0] for r in con.execute("SELECT DISTINCT source_newsid FROM results_notes")),
                             sorted([newest, older]))
            con.close()


class DownloadTest(unittest.TestCase):
    def test_part_file_validated_and_retried(self):
        with _tempdir("download") as tmp:
            root = tmp / "raw"
            dest = root / "results_notes_text" / "news.pdf"
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(b"%PDF-1.7 truncated garbage")  # old code trusted any size > 0
            good = tmp / "good.pdf"
            _pdf(good, ["download payload"])
            payload = good.read_bytes()

            class _Response:
                def __init__(self, data: bytes):
                    self.data = data

                def read(self) -> bytes:
                    return self.data

                def __enter__(self):
                    return self

                def __exit__(self, *exc):
                    return False

            calls: list[str] = []
            sleeps: list[float] = []

            def fake_urlopen(request, timeout=0):
                calls.append(request.full_url)
                if len(calls) < 3:
                    raise OSError("connection reset")
                return _Response(payload)

            with mock.patch.object(fetch_results_notes_text.urllib.request, "urlopen", fake_urlopen), \
                    mock.patch.object(fetch_results_notes_text.time, "sleep", sleeps.append):
                path = fetch_results_notes_text.download("news", "x.pdf", root, offline=False)

            self.assertEqual(path, dest)
            self.assertEqual(dest.read_bytes(), payload)
            self.assertEqual(sleeps, [0.5, 1.0], "backoff between the failed attempts")
            self.assertFalse(dest.with_name(dest.name + ".part").exists(), "no .part left behind")

            # The validated cache is reused without another request.
            self.assertEqual(fetch_results_notes_text.download("news", "x.pdf", root, offline=False), dest)
            self.assertEqual(len(calls), 3)


class EtfPremiumTest(unittest.TestCase):
    def test_single_owner_leaves_etf_premium_view_untouched(self):
        with _tempdir("etf") as tmp:
            db = tmp / "equity_intelligence.db"
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
            view_sql = con.execute("SELECT sql FROM sqlite_master WHERE name = 'etf_premium'").fetchone()[0]
            view_rows = con.execute("SELECT COUNT(*) FROM etf_premium").fetchone()[0]
            con.close()

            rc = build_etf_premium.main(["--db", str(db)])
            self.assertEqual(rc, 0)
            con = sqlite3.connect(db)
            self.assertEqual(con.execute("SELECT sql FROM sqlite_master WHERE name = 'etf_premium'").fetchone()[0],
                             view_sql, "the etf_premium view belongs to fetch_etf_nav")
            self.assertEqual(con.execute("SELECT COUNT(*) FROM etf_premium").fetchone()[0], view_rows)

            rows = con.execute("SELECT date, isin, symbol, close, nav, premium_pct, inav, inav_gap_pct, built_at "
                               "FROM etf_premium_daily ORDER BY date").fetchall()
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0][:2], ("2026-09-10", "INF247L01AU3"))
            self.assertEqual(rows[0][2], "MONQ50")
            self.assertAlmostEqual(rows[0][5], 100.0)
            self.assertAlmostEqual(rows[0][6], 105.0)
            self.assertAlmostEqual(rows[0][7], 90.0)
            self.assertIsNone(rows[1][6])
            self.assertIsNone(rows[1][7])
            self.assertTrue(all(row[8] for row in rows), "built_at is stamped")
            con.close()

            # Idempotent re-run: still two rows, not four.
            build_etf_premium.main(["--db", str(db)])
            con = sqlite3.connect(db)
            self.assertEqual(con.execute("SELECT COUNT(*) FROM etf_premium_daily").fetchone()[0], 2)
            con.close()


class JobsYamlTest(unittest.TestCase):
    def _jobs(self) -> dict[str, dict]:
        registry = yaml.safe_load((REPO / "plugins/dsh-worker/jobs.yaml").read_text(encoding="utf-8"))
        return {job["name"]: job for job in registry["jobs"]}

    def test_max_age_tolerates_quiet_quarters(self):
        jobs = self._jobs()
        for name in ("results_notes_text", "deck_page_text"):
            self.assertGreaterEqual(jobs[name]["success_check"]["expect"]["max_age_days"], 120,
                                    f"{name} must not go stale between quarters / quiet months")

    def test_new_entries_are_disabled_and_locked(self):
        jobs = self._jobs()
        expected = {
            "deck_page_text": ("reality_engine.scripts.build_deck_page_text", "deck_figures.db:deck_page_text"),
            "results_notes_text": ("reality_engine.scripts.fetch_results_notes_text",
                                   "results_xbrl.db:results_notes"),
            "etf_premium": ("reality_engine.scripts.build_etf_premium",
                            "equity_intelligence.db:etf_premium_daily"),
        }
        for name, (module, write) in expected.items():
            job = jobs[name]
            self.assertFalse(job["enabled"])
            self.assertIn(module, job["argv"])
            self.assertIn(write, job["writes"])
            self.assertTrue(all(lock.startswith(("db:", "net:", "gpu")) for lock in job["resource_locks"]))
            self.assertIsInstance(job["success_check"], dict)
        self.assertNotIn("equity_intelligence.db:etf_premium", jobs["etf_premium"]["writes"],
                         "etf_premium stays owned by fetch_etf_nav")
        self.assertIn("etf_premium_daily", jobs["etf_premium"]["success_check"]["sql"])


if __name__ == "__main__":
    unittest.main()
