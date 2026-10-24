"""Unit tests for ``reality_engine.toolbelt`` (fixtures only; no live DB writes)."""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from reality_engine.toolbelt import cost_ledger, drive_fetch, find_docs, job_peek, mod_test, render_pages, sample_rows

ROOT = Path(__file__).resolve().parents[2]
TMP = ROOT / ".tmp" / "test_toolbelt"
TOOLS = ("sample_rows", "find_docs", "drive_fetch", "render_pages",
         "cost_ledger", "mod_test", "job_peek")


class ToolbeltTestCase(unittest.TestCase):
    def setUp(self) -> None:
        TMP.mkdir(parents=True, exist_ok=True)
        self.dir = TMP / self._testMethodName
        shutil.rmtree(self.dir, ignore_errors=True)
        self.dir.mkdir(parents=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.dir, ignore_errors=True)


class TestSampleRows(ToolbeltTestCase):
    def _db(self) -> Path:
        path = self.dir / "fixture.db"
        con = sqlite3.connect(path)
        con.executescript("""
            CREATE TABLE t (id INTEGER PRIMARY KEY, sym TEXT, val INTEGER);
            CREATE INDEX ix_t_sym ON t(sym);
        """)
        con.executemany("INSERT INTO t(sym, val) VALUES (?, ?)",
                        [("A" if i % 2 else "B", i) for i in range(100)])
        con.execute("ANALYZE")
        con.commit()
        con.close()
        return path

    def test_sample_is_deterministic_and_unique(self) -> None:
        db = self._db()
        first = sample_rows.sample(str(db), "t", n=5, seed=7)
        second = sample_rows.sample(str(db), "t", n=5, seed=7)
        self.assertEqual(first["rows"], second["rows"])
        self.assertEqual(first["n"], 5)
        self.assertEqual(len({r["id"] for r in first["rows"]}), 5)

    def test_where_and_stratify(self) -> None:
        db = self._db()
        only_a = sample_rows.sample(str(db), "t", where="sym='A'", n=7)
        self.assertEqual({r["sym"] for r in only_a["rows"]}, {"A"})
        mixed = sample_rows.sample(str(db), "t", stratify="sym", n=4)
        self.assertEqual({r["sym"] for r in mixed["rows"]}, {"A", "B"})

    def test_schema_reports_columns_indexes_and_estimate(self) -> None:
        info = sample_rows.schema(str(self._db()), "t")
        self.assertEqual([c["name"] for c in info["columns"]], ["id", "sym", "val"])
        self.assertIn("ix_t_sym", [i["name"] for i in info["indexes"]])
        self.assertEqual(info["row_estimate"], 100)
        self.assertEqual(info["row_estimate_source"], "sqlite_stat1")
        self.assertTrue(info["rowid"])

    def test_unknown_column_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            sample_rows.sample(str(self._db()), "t", cols="nope")


class TestFindDocs(ToolbeltTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.data = self.dir / "data"
        self.data.mkdir()
        self.env = mock.patch.dict(os.environ, {"REALITY_DATA_ROOT": str(self.data)})
        self.env.start()
        self.addCleanup(self.env.stop)
        self._equity()
        self._ar()
        self._deck()
        self._cc()

    def _equity(self) -> None:
        con = sqlite3.connect(self.data / "equity_intelligence.db")
        con.executescript("""
            CREATE TABLE corporate_documents (
                id INTEGER PRIMARY KEY, isin TEXT, symbol TEXT, doc_type TEXT, title TEXT,
                bse_dissem_ts TEXT, publication_date TEXT, call_date TEXT,
                local_file_path TEXT, is_processed INTEGER);
            CREATE TABLE raw_documents (
                doc_id INTEGER PRIMARY KEY, symbol TEXT, isin TEXT, source_type TEXT,
                title TEXT, published_date TEXT, local_file_path TEXT);
            CREATE TABLE document_chunks (chunk_id INTEGER PRIMARY KEY, doc_id INTEGER);
            CREATE INDEX ix_chunks_doc ON document_chunks(doc_id);
        """)
        on_disk = self.dir / "present.pdf"
        on_disk.write_bytes(b"%PDF-1.4")
        con.executemany(
            "INSERT INTO corporate_documents VALUES (?,?,?,?,?,?,?,?,?,?)",
            [(1, "INE050001010", "DEEDEV", "CONCALL_TRANSCRIPT", "Q1 FY27 call",
              "2026-08-11T23:38:08", None, "2026-08-06", str(on_disk), 1),
             (2, "INE050001010", "DEEDEV", "CONCALL_TRANSCRIPT", "Q4 FY25 call",
              None, None, "2025-08-12", None, 0),
             (3, "INE050001010", "DEEDEV", "CONCALL_TRANSCRIPT", "Undated call",
              None, None, None, None, 0)])
        con.executemany("INSERT INTO document_chunks(doc_id) VALUES (?)", [(1,), (1,), (2,)])
        con.execute("INSERT INTO raw_documents VALUES (?,?,?,?,?,?,?)",
                    (10, "DEEDEV", "INE050001010", "CONCALL_TRANSCRIPT", "raw copy",
                     "2026-08-11", "reality_engine\\data\\pdfs\\DEEDEV\\x.pdf"))
        con.commit()
        con.close()

    def _ar(self) -> None:
        con = sqlite3.connect(self.data / "ar_facts.db")
        con.executescript("""
            CREATE TABLE ar_docs (doc_id INTEGER PRIMARY KEY, isin TEXT, symbol TEXT, company TEXT,
                fiscal_year TEXT, fiscal_year_source TEXT, filed_at TEXT, filed_at_source TEXT,
                sha256 TEXT, path TEXT, n_pages INTEGER, n_text_pages INTEGER, n_pieces INTEGER,
                status TEXT, error TEXT, ts TEXT);
        """)
        con.execute("INSERT INTO ar_docs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (7, "INE050001010", "DEEDEV", "Deedee Labs", "2026-03-31", "filing_month_rule",
                     "2026-07-09T14:35:01", "bse_feed", "sha", "C:\\data\\pdfs\\DEEDEV\\AR.pdf",
                     100, 99, 10, "done", None, "2026-10-16"))
        con.commit()
        con.close()

    def _deck(self) -> None:
        con = sqlite3.connect(self.data / "deck_figures.db")
        con.executescript("""
            CREATE TABLE deck_sources (source TEXT, source_id TEXT, symbol TEXT, isin TEXT,
                exch_code TEXT, known_at TEXT, title TEXT, url TEXT, local_path TEXT,
                sha256 TEXT, size_bytes INTEGER, status TEXT, error TEXT, fetched_at TEXT,
                PRIMARY KEY (source, source_id));
        """)
        con.execute("INSERT INTO deck_sources VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    ("bse", "deck-1", "DEEDEV", "INE050001010", "540145", "2026-08-01",
                     "Investor presentation", "https://example", "C:\\data\\decks\\bse\\1\\d.pdf",
                     "sha", 10, "ok", None, "2026-10-09"))
        con.commit()
        con.close()

    def _cc(self) -> None:
        con = sqlite3.connect(self.data / "concall_facts.db")
        con.executescript("""
            CREATE TABLE cc_docs (doc_id INTEGER PRIMARY KEY, isin TEXT, symbol TEXT, filed_at TEXT,
                status TEXT, model TEXT, key_name TEXT, chars INTEGER, in_tok INTEGER, out_tok INTEGER,
                cost_usd REAL, seconds REAL, checks_json TEXT, raw_json TEXT, error TEXT, run_at TEXT,
                priority INTEGER, period_discussed TEXT, period_q INTEGER, period_fy INTEGER,
                date_source TEXT);
        """)
        con.execute("INSERT INTO cc_docs (doc_id, isin, symbol, filed_at, status, date_source) "
                    "VALUES (?,?,?,?,?,?)",
                    (1, "INE050001010", "DEEDEV", "2026-08-11T23:38:08", "ok", "bse_dissem_ts"))
        con.commit()
        con.close()

    def test_filing_date_precedence_and_undated(self) -> None:
        result = find_docs.find(symbol="DEEDEV", doc_type="CONCALL_TRANSCRIPT")
        rows = {(r["store"], r["id"]): r for r in result["documents"]}
        first = rows[("corporate_documents", 1)]
        self.assertEqual(first["filing_date"], "2026-08-11T23:38:08")
        self.assertEqual(first["date_source"], "bse_dissem_ts")
        self.assertEqual(first["chunk_count"], 2)
        self.assertEqual(first["read_status"], "processed")
        self.assertTrue(first["path_exists"])
        self.assertEqual(rows[("corporate_documents", 2)]["date_source"], "call_date")
        self.assertTrue(rows[("corporate_documents", 3)]["undated"])
        self.assertEqual(rows[("raw_documents", 10)]["chunk_count"], 0)
        self.assertEqual(rows[("raw_documents", 10)]["read_status"], "not_indexed")
        self.assertEqual(rows[("cc_docs", 1)]["filing_date"], "2026-08-11T23:38:08")

    def test_doc_type_routes_to_the_right_stores(self) -> None:
        annual = find_docs.find(symbol="DEEDEV", doc_type="ANNUAL_REPORT")
        self.assertEqual([r["store"] for r in annual["documents"]], ["ar_docs"])
        deck = find_docs.find(symbol="DEEDEV", doc_type="DECK")
        self.assertEqual([r["store"] for r in deck["documents"]], ["deck_sources"])

    def test_date_window_filters(self) -> None:
        result = find_docs.find(symbol="DEEDEV", since="2026-01-01", until="2026-12-31")
        self.assertTrue(result["documents"])
        self.assertTrue(all((r["filing_date"] or "") >= "2026-01-01" for r in result["documents"]))


class TestRenderPages(ToolbeltTestCase):
    def _pdf(self) -> Path:
        import pymupdf
        path = self.dir / "tiny.pdf"
        doc = pymupdf.open()
        page = doc.new_page()
        page.insert_text((72, 72), "Revenue 2026 123 456 and the annual report discusses growth plans.")
        doc.new_page()
        doc.save(path)
        doc.close()
        return path

    def test_render_png_and_text_coverage(self) -> None:
        pdf = self._pdf()
        out = render_pages.render(pdf, pages="1", dpi=72, out_dir=self.dir / "png")
        page = out["pages"][0]
        self.assertEqual(page["page"], 1)
        self.assertTrue(Path(page["png"]).exists())
        self.assertGreater(page["width"], 0)
        text = render_pages.render(pdf, pages="all", text=True)
        first, second = text["pages"]
        self.assertGreater(first["chars"], 0)
        self.assertGreater(first["text_coverage"], 0)
        self.assertFalse(first["low_text"])
        self.assertEqual(first["deck_route"], "vision")
        self.assertTrue(second["low_text"])
        self.assertEqual(second["deck_route"], "skip")

    def test_max_side_matches_deck_cap(self) -> None:
        out = render_pages.render(self._pdf(), pages="1", max_side=1600, out_dir=self.dir / "png")
        self.assertEqual(max(out["pages"][0]["width"], out["pages"][0]["height"]), 1600)


class TestDriveFetch(ToolbeltTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.stub = self.dir / "fake_rclone.py"
        payload = b"hello"
        self.md5 = hashlib.md5(payload).hexdigest()
        self.sha = hashlib.sha256(payload).hexdigest()
        lines = [
            "import json, sys",
            "args = sys.argv[1:]",
            "if args[0] == 'lsjson':",
            "    target = args[-1]",
            "    if 'MISSING' in target:",
            "        print('[]')",
            "    else:",
            f"        print(json.dumps([{{'Path': 'x.pdf', 'Size': 5, "
            f"'Hashes': {{'md5': '{self.md5}', 'sha256': '{self.sha}'}}}}]))",
            "elif args[0] == 'copyto':",
            "    open(args[2], 'wb').write(b'hello')",
            "else:",
            "    sys.exit(3)",
        ]
        self.stub.write_text("\n".join(lines), encoding="utf-8")
        self.rclone = [sys.executable, str(self.stub)]
        self.index = self.dir / "drive_index.json"

    def _fetch(self, items, **kwargs):
        kwargs.setdefault("index_path", self.index)
        kwargs.setdefault("rclone", self.rclone)
        kwargs.setdefault("timeout", 30)
        return drive_fetch.fetch(items, **kwargs)

    def test_path_mapping(self) -> None:
        self.assertEqual(
            drive_fetch.local_to_remote(r"C:\x\reality_engine\data\pdfs\A\B.pdf"), "pdfs/A/B.pdf")
        self.assertEqual(
            drive_fetch.local_to_remote(r"D:\RealityEngine\pdfs\A\B.pdf"), "D_pdfs/A/B.pdf")
        self.assertEqual(
            drive_fetch.local_to_remote(r"D:\RealityEngine\remaining_pdfs\A\B.pdf"), "D_pdfs/A/B.pdf")
        self.assertEqual(
            drive_fetch.local_to_remote(r"reality_engine\data\decks\bse\1\d.pdf"), "decks/bse/1/d.pdf")
        self.assertEqual(drive_fetch.classify("a" * 64), ("sha256", "a" * 64))
        self.assertEqual(drive_fetch.classify(r"C:\x.pdf")[0], "local")
        self.assertEqual(drive_fetch.classify("pdfs/A/B.pdf")[0], "remote")

    def test_dry_run_present_missing_and_index_cache(self) -> None:
        present = self._fetch(["pdfs/DEEDEV/ANNUAL_REPORT/x.pdf"], dest=self.dir / "out", dry_run=True)
        self.assertEqual(present["items"][0]["status"], "present")
        self.assertTrue(self.index.exists())
        missing = self._fetch(["pdfs/MISSING/ANNUAL_REPORT/y.pdf"], dest=self.dir / "out", dry_run=True)
        self.assertEqual(missing["items"][0]["status"], "missing")

    def test_download_verify_and_sha_lookup(self) -> None:
        out = self.dir / "out"
        downloaded = self._fetch(["pdfs/DEEDEV/ANNUAL_REPORT/x.pdf"], dest=out, verify=True)
        self.assertEqual(downloaded["items"][0]["status"], "ok")
        self.assertTrue(downloaded["items"][0]["verified"])
        self.assertEqual((out / "x.pdf").read_bytes(), b"hello")
        by_sha = self._fetch([self.sha], dest=out)
        self.assertEqual(by_sha["items"][0]["remote_path"],
                         "pdfs/DEEDEV/ANNUAL_REPORT/x.pdf")
        self.assertEqual(by_sha["items"][0]["status"], "ok")

    def test_dest_required_in_sandbox(self) -> None:
        with mock.patch.dict(os.environ, {"DSH_WORKER_JOB_ID": "job"}, clear=False):
            with self.assertRaises(ValueError):
                self._fetch(["pdfs/DEEDEV/ANNUAL_REPORT/x.pdf"], dry_run=True)


class TestCostLedger(ToolbeltTestCase):
    def test_charge_cap_and_report(self) -> None:
        ledger = self.dir / "spend.jsonl"
        first = cost_ledger.charge("p", "m", 1000, 100, usd=0.5, purpose="x", job_id="j1",
                                   ledger=ledger)
        self.assertEqual(first["usd"], 0.5)
        with self.assertRaises(cost_ledger.BudgetExceeded):
            cost_ledger.charge("p", "m", 0, 0, usd=0.2, purpose="x", job_id="j1",
                               ledger=ledger, cap_usd=0.6, cap_scope="x")
        self.assertEqual(len(cost_ledger.read_entries(ledger)), 1)
        priced = cost_ledger.charge("p", "deepseek-v4.1-flash", 1_000_000, 0, usd=None,
                                    purpose="y", job_id="j2", ledger=ledger)
        self.assertAlmostEqual(priced["usd"], 0.15)
        report = cost_ledger.report(ledger)
        self.assertEqual(report["entries"], 2)
        self.assertAlmostEqual(report["total_usd"], 0.65)
        self.assertIn("x", report["by_purpose"])

    def test_cli_cap_exits_nonzero(self) -> None:
        ledger = self.dir / "spend.jsonl"
        with contextlib.redirect_stdout(io.StringIO()):
            rc = cost_ledger.main(["--ledger", str(ledger), "--cap", "0.1", "--scope", "y",
                                   "--add", "p", "m", "0", "0", "0.5", "y", "j3"])
        self.assertEqual(rc, 2)
        self.assertFalse(ledger.exists())

    def test_unknown_price_is_an_error(self) -> None:
        with self.assertRaises(ValueError):
            cost_ledger.charge("p", "no-such-model", 1, 1, usd=None,
                               ledger=self.dir / "spend.jsonl")


class TestModTest(ToolbeltTestCase):
    def test_report_aggregation(self) -> None:
        lines = [
            "noise",
            'claude-plugin-test-report {"file":"a.test.ts","results":['
            '{"title":"t1","ms":1,"failure":null},{"title":"t2","ms":2,"failure":"boom"}]}',
            'claude-plugin-test-report {"file":"b.test.ts","results":['
            '{"title":"t3","ms":3,"failure":null}]}',
            "claude-plugin-test-report not-json",
        ]
        reports = mod_test.parse_report_lines(lines)
        summary = mod_test.aggregate_reports(reports)
        self.assertEqual(summary["files"], 2)
        self.assertEqual(summary["tests"], 3)
        self.assertEqual(summary["failures"], 1)
        self.assertEqual(summary["ms"], 6.0)
        self.assertEqual(summary["failed"][0]["title"], "t2")

    def test_run_skips_cleanly_without_cli(self) -> None:
        mod = self.dir / "mod"
        (mod / "hooks").mkdir(parents=True)
        result = mod_test.run(mod, skip_validate=True, skip_tsc=True, claude=str(self.dir / "nope"))
        self.assertIsNone(result["validate"]["ok"])
        self.assertEqual(result["tests"]["skipped"], "claude CLI not found")


class TestJobPeek(ToolbeltTestCase):
    def _job(self, with_progress: bool = True) -> Path:
        job = self.dir / ("job_progress" if with_progress else "job_events")
        job.mkdir()
        now = datetime.now(timezone.utc)
        start = (now - timedelta(seconds=120)).isoformat(timespec="seconds")
        status = {
            "job_id": "job-1", "phase": "running", "started_at": start,
            "updated_at": now.isoformat(timespec="seconds"),
        }
        if with_progress:
            status["heartbeat_live"] = {
                "events": [{"at": now.isoformat(timespec="seconds"), "kind": "tool_call"}
                           for _ in range(12)]}
        (job / "status.json").write_text(json.dumps(status), encoding="utf-8")
        (job / "result.md").write_text("# Result\nEverything so far.\n", encoding="utf-8")
        events = [
            {"type": "tool_call", "tool": "read", "input": {"file_path": "a.py"}},
            {"type": "tool_call", "tool": "pwsh", "input": {"description": "run tests"}},
            {"type": "tool_result", "tool": "pwsh"},
        ]
        (job / "result.md.events.jsonl").write_text(
            "\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")
        if with_progress:
            (job / "progress.jsonl").write_text(json.dumps({
                "at": now.isoformat(timespec="seconds"), "tool_calls": 12,
                "tool_calls_by_tool": {"read": 7, "pwsh": 5}, "last_tool": "read",
            }) + "\n", encoding="utf-8")
        return job

    def test_progress_digest_view(self) -> None:
        view = job_peek.peek(self._job(True))
        self.assertEqual(view["phase"], "running")
        self.assertEqual(view["tool_calls"], 12)
        self.assertEqual(view["tool_calls_by_tool"]["read"], 7)
        self.assertFalse(view["tool_calls_window"])
        self.assertEqual(len(view["activity"]), 10)
        self.assertIsNotNone(view["progress"])
        self.assertTrue(view["result_head"].startswith("# Result"))
        self.assertIsNotNone(view["elapsed_seconds"])

    def test_event_tail_fallback(self) -> None:
        view = job_peek.peek(self._job(False))
        self.assertTrue(view["tool_calls_window"])
        self.assertEqual(view["tool_calls_by_tool"]["read"], 1)
        self.assertEqual(view["tool_calls_by_tool"]["pwsh"], 1)
        self.assertEqual(view["activity"][-1]["kind"], "tool_result")


class TestCliHelp(unittest.TestCase):
    def test_every_tool_help_exits_zero(self) -> None:
        for tool in TOOLS:
            proc = subprocess.run([sys.executable, "-m", f"reality_engine.toolbelt.{tool}", "--help"],
                                  cwd=ROOT, capture_output=True, text=True, timeout=120)
            self.assertEqual(proc.returncode, 0, f"{tool}: {proc.stderr}")


if __name__ == "__main__":
    unittest.main()
