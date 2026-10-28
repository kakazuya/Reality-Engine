"""Offline tests for the one original downloader (no network, no DB, temp dirs only).

The DSH sandbox cannot clean ``tempfile.TemporaryDirectory`` up (ACL), so every
case gets a private directory under the repo's writable ``.tmp/``.
"""

import csv
import shutil
import unittest
from pathlib import Path

from reality_engine.scripts.fetch_originals import (
    FLOOR,
    OriginalFetcher,
    exchange_of,
    is_pdf,
    load_rows,
)

PDF = b"%PDF-1.7\n" + b"x" * 32
HTML = b"<html>blocked</html>"
TMPROOT = Path(__file__).resolve().parents[2] / ".tmp" / "tests"


class FakeResponse:
    def __init__(self, status_code, content=b""):
        self.status_code = status_code
        self.content = content


class FakeSession:
    """Queued responses per URL; records every call. The last response repeats."""

    def __init__(self, responses):
        self.responses = {u: list(r) for u, r in responses.items()}
        self.calls = []

    def get(self, url, timeout=None):
        self.calls.append(url)
        queue = self.responses.get(url) or [FakeResponse(404)]
        return queue.pop(0) if len(queue) > 1 else queue[0]


class Case(unittest.TestCase):
    def setUp(self):
        # tempfile.mkdtemp would set a 0700 DACL the sandbox token cannot write through,
        # so the case directory is a plain mkdir under the workspace-owned .tmp/.
        TMPROOT.mkdir(parents=True, exist_ok=True)
        name = self.id().rsplit(".", 1)[-1]
        self.tmp = TMPROOT / name
        shutil.rmtree(self.tmp, ignore_errors=True)
        self.tmp.mkdir(parents=True)
        self.sleeps = []

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def fetcher(self, rows, **kw):
        kw.setdefault("sleep", lambda s: self.sleeps.append(s))
        return OriginalFetcher(rows, self.tmp / "manifest.csv", **kw)

    def list_csv(self, rows, header=("url", "key", "kind", "symbol")):
        path = self.tmp / "list.csv"
        with path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(header))
            w.writeheader()
            w.writerows(rows)
        return path


class TestListAndPacing(Case):
    def test_exchange_of(self):
        self.assertEqual(exchange_of("https://nsearchives.nseindia.com/corporate/x.pdf"), "nse")
        self.assertEqual(
            exchange_of("https://www.bseindia.com/xml-data/corpfiling/AttachHis/x.pdf"), "bse")
        self.assertEqual(exchange_of("https://rbidocs.rbi.org.in/x.pdf"), "")

    def test_load_rows_defaults_and_dest(self):
        path = self.list_csv([
            {"url": "https://www.bseindia.com/a.pdf", "key": "k1", "kind": "deck",
             "symbol": "RAIN"},
            {"url": "https://www.bseindia.com/b.pdf", "key": "k2", "kind": "", "symbol": ""},
        ])
        rows = load_rows(path, self.tmp)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["exchange"], "bse")
        self.assertEqual(rows[0]["dest"], self.tmp / "deck" / "RAIN" / "k1.pdf")
        self.assertEqual(rows[1]["kind"], "misc")
        self.assertEqual(rows[1]["dest"], self.tmp / "misc" / "_all" / "k2.pdf")

    def test_load_rows_accepts_source_url_and_dest(self):
        path = self.list_csv([
            {"source_url": "https://nsearchives.nseindia.com/c.pdf", "key": "k3",
             "kind": "annual_report", "symbol": "X", "dest": "custom/here.pdf"},
        ], header=("source_url", "key", "kind", "symbol", "dest"))
        rows = load_rows(path, self.tmp)
        self.assertEqual(rows[0]["url"], "https://nsearchives.nseindia.com/c.pdf")
        self.assertEqual(rows[0]["dest"], Path("custom/here.pdf"))
        self.assertEqual(rows[0]["exchange"], "nse")

    def test_interval_floors(self):
        f = self.fetcher([], exchange="nse", interval=0.1, sleep=lambda s: None)
        self.assertEqual(f.interval, FLOOR["nse"])
        f = self.fetcher([], exchange="bse", interval=1.0, sleep=lambda s: None)
        self.assertEqual(f.interval, FLOOR["bse"])
        f = self.fetcher([], exchange="any", interval=9.0, sleep=lambda s: None)
        self.assertEqual(f.interval, 9.0)

    def test_non_d_root_refused_without_force(self):
        from reality_engine.scripts import fetch_originals as fo
        path = self.list_csv([])
        with self.assertRaises(SystemExit):
            fo.main([str(path), "--dest-root", str(self.tmp / "x")])


class TestResume(Case):
    def test_pdf_skipped_damaged_refetched(self):
        good = self.tmp / "good.pdf"
        good.write_bytes(PDF)
        bad = self.tmp / "bad.pdf"
        bad.write_bytes(b"<html>error page</html>")
        missing = self.tmp / "missing.pdf"
        rows = [
            {"key": "good", "kind": "k", "symbol": "S", "exchange": "bse",
             "url": "https://www.bseindia.com/g.pdf", "dest": good},
            {"key": "bad", "kind": "k", "symbol": "S", "exchange": "bse",
             "url": "https://www.bseindia.com/b.pdf", "dest": bad},
            {"key": "new", "kind": "k", "symbol": "S", "exchange": "bse",
             "url": "https://www.bseindia.com/n.pdf", "dest": missing},
        ]
        session = FakeSession({
            "https://www.bseindia.com/b.pdf": [FakeResponse(200, PDF + b"2")],
            "https://www.bseindia.com/n.pdf": [FakeResponse(200, PDF + b"3")],
        })
        stats = self.fetcher(rows, exchange="bse", fetch=session,
                             sleep=lambda s: None).run()
        self.assertEqual(stats["skipped"], 1)
        self.assertEqual(stats["ok"], 2)
        self.assertEqual(session.calls, ["https://www.bseindia.com/b.pdf",
                                         "https://www.bseindia.com/n.pdf"])
        self.assertTrue(is_pdf(good) and is_pdf(bad) and is_pdf(missing))


class TestBackoffAndErrors(Case):
    def test_403_retried_then_ok_with_penalty(self):
        dest = self.tmp / "a.pdf"
        row = [{"key": "a", "kind": "k", "symbol": "S", "exchange": "bse",
                "url": "https://www.bseindia.com/a.pdf", "dest": dest}]
        session = FakeSession({"https://www.bseindia.com/a.pdf": [
            FakeResponse(403), FakeResponse(503), FakeResponse(200, PDF)]})
        stats = self.fetcher(row, exchange="bse", fetch=session, penalty=600.0).run()
        self.assertEqual(stats["ok"], 1)
        self.assertEqual(stats["blocked"], 2)
        self.assertTrue(dest.read_bytes().startswith(b"%PDF"))
        # a 403 gets the penalty box; the following 503 backs off exponentially
        self.assertAlmostEqual(self.sleeps[0], 600.0, delta=1.0)
        self.assertAlmostEqual(self.sleeps[1], 6.0)

    def test_404_is_final_and_manifest_says_error(self):
        dest = self.tmp / "missing.pdf"
        row = [{"key": "m", "kind": "deck", "symbol": "S", "exchange": "bse",
                "url": "https://www.bseindia.com/m.pdf", "dest": dest}]
        session = FakeSession({"https://www.bseindia.com/m.pdf": [FakeResponse(404)]})
        stats = self.fetcher(row, exchange="bse", fetch=session,
                             sleep=lambda s: None).run()
        self.assertEqual(stats["error"], 1)
        self.assertEqual(session.calls, ["https://www.bseindia.com/m.pdf"])
        self.assertFalse(dest.exists())
        rows = list(csv.DictReader(open(self.tmp / "manifest.csv", encoding="utf-8")))
        self.assertEqual(rows[0]["status"], "error")
        self.assertEqual(rows[0]["http_status"], "404")

    def test_html_body_is_error_not_saved(self):
        dest = self.tmp / "x.pdf"
        row = [{"key": "x", "kind": "k", "symbol": "S", "exchange": "nse",
                "url": "https://nsearchives.nseindia.com/x.pdf", "dest": dest}]
        session = FakeSession({"https://nsearchives.nseindia.com/x.pdf":
                               [FakeResponse(200, HTML)]})
        stats = self.fetcher(row, exchange="nse", fetch=session,
                             sleep=lambda s: None).run()
        self.assertEqual(stats["error"], 1)
        self.assertFalse(dest.exists())


class TestStreamSelection(Case):
    def test_exchange_filter_leaves_other_rows_alone(self):
        rows = [
            {"key": "n", "kind": "k", "symbol": "S", "exchange": "nse",
             "url": "https://nsearchives.nseindia.com/n.pdf", "dest": self.tmp / "n.pdf"},
            {"key": "b", "kind": "k", "symbol": "S", "exchange": "bse",
             "url": "https://www.bseindia.com/b.pdf", "dest": self.tmp / "b.pdf"},
            {"key": "r", "kind": "k", "symbol": "S", "exchange": "",
             "url": "https://rbidocs.rbi.org.in/r.pdf", "dest": self.tmp / "r.pdf"},
        ]
        session = FakeSession({u: [FakeResponse(200, PDF)]
                               for u in ("https://www.bseindia.com/b.pdf",)})
        stats = self.fetcher(rows, exchange="bse", fetch=session,
                             sleep=lambda s: None).run()
        self.assertEqual(stats["skipped_exchange"], 2)
        self.assertEqual(stats["ok"], 1)
        self.assertEqual(session.calls, ["https://www.bseindia.com/b.pdf"])

    def test_manifest_header_written_once(self):
        row = [{"key": "a", "kind": "k", "symbol": "S", "exchange": "bse",
                "url": "https://www.bseindia.com/a.pdf", "dest": self.tmp / "a.pdf"}]
        session = FakeSession({"https://www.bseindia.com/a.pdf": [FakeResponse(200, PDF)]})
        for _ in range(2):
            self.fetcher(row, exchange="bse", fetch=session, sleep=lambda s: None).run()
        text = (self.tmp / "manifest.csv").read_text(encoding="utf-8")
        self.assertEqual(text.count("key,kind,symbol,exchange"), 1)


if __name__ == "__main__":
    unittest.main()
