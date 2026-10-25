"""fetch_etf_nav: a trickling server must hit the wall-clock cap, not a 300s per-read timeout."""
import contextlib
import datetime as dt
import io
import sqlite3
import time
import unittest
from pathlib import Path
from unittest import mock

from reality_engine.scripts import fetch_etf_nav as fetch

BASE = Path(__file__).resolve().parents[2] / ".tmp" / "fetch-etf-nav-timeout"
_REAL_SLEEP = time.sleep


class _Trickle:
    """requests.Response stand-in: one small chunk every ``gap`` seconds."""

    status_code = 200

    def __init__(self, gap=0.1, chunks=50):
        self.gap, self.chunks, self.closed = gap, chunks, False

    def iter_content(self, size):
        for _ in range(self.chunks):
            _REAL_SLEEP(self.gap)
            yield b"Scheme Code;NAV Name;Plan;Option;ISIN;Net Asset Value;Date\r\n"

    def close(self):
        self.closed = True


class WallClockCapTest(unittest.TestCase):
    def setUp(self):
        self._raw = fetch.RAW
        (BASE / "raw" / "amfi_nav").mkdir(parents=True, exist_ok=True)
        fetch.RAW = BASE / "raw"

    def tearDown(self):
        fetch.RAW = self._raw
        for p in (BASE / "raw").rglob("*"):
            if p.is_file():
                p.unlink()

    def test_trickle_aborts_at_cap_and_retries(self):
        responses = []

        def fake_get(url, **kwargs):
            responses.append(_Trickle())
            return responses[-1]

        out = io.StringIO()
        with mock.patch.object(fetch.requests, "get", fake_get), \
                mock.patch.object(fetch.time, "sleep") as backoff, \
                contextlib.redirect_stdout(out):
            started = time.monotonic()
            result = fetch.month_file(dt.date(2026, 10, 1), net_timeout=0.35, attempts=3)
            elapsed = time.monotonic() - started

        self.assertIsNone(result)
        self.assertLess(elapsed, 5, "the cap must fire in seconds, not wait out the response")
        self.assertEqual(len(responses), 3, "3 attempts")
        self.assertEqual(backoff.call_count, 2, "backoff between attempts")
        self.assertTrue(all(r.closed for r in responses), "the capped response is closed")
        self.assertEqual(list((BASE / "raw").rglob("*.gz")), [], "no file written from a capped response")
        log = out.getvalue()
        self.assertIn("attempt 1/3 failed", log)
        self.assertIn("DownloadTooSlow", log)
        self.assertIn("download failed after 3 attempts", log)


class DbLockFailFastTest(unittest.TestCase):
    def test_locked_db_fails_fast_with_clear_message(self):
        BASE.mkdir(parents=True, exist_ok=True)
        db_path = BASE / "locked.db"
        db_path.unlink(missing_ok=True)
        setup = sqlite3.connect(db_path)
        setup.executescript(fetch.DDL)
        setup.close()
        holder = sqlite3.connect(db_path, timeout=0)
        holder.execute("BEGIN IMMEDIATE")      # holds the writer lock, writes no rows
        try:
            started = time.monotonic()
            with self.assertRaises(SystemExit) as caught:
                fetch.connect(db_path, timeout=0.5)
            elapsed = time.monotonic() - started
        finally:
            holder.rollback()
            holder.close()
        message = str(caught.exception)
        self.assertLess(elapsed, 5, "a locked DB must fail fast, not wait for the next write")
        self.assertIn("locked (waited", message)
        self.assertIn("ingestion queue lock", message)
        self.assertIn("dsh-worker", message)


if __name__ == "__main__":
    unittest.main()
