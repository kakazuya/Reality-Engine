"""Offline tests for the data-gather MCP server.

No test starts a real feed, touches the network, or opens a live database: each
one writes a throwaway SQLite database and runs a fake job through the real
dsh-worker supervisor (spawn, status records, resource locks) in a temp repo.
"""
from __future__ import annotations

import os
import sqlite3
import sys
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[3]
PLUGIN = REPO / "plugins" / "data-gather"
SERVER_DIR = PLUGIN / "server"
WORKER_SERVER = REPO / "plugins" / "dsh-worker" / "server"
FIXTURES = REPO / "reality_engine" / "tests" / "fixtures"
for _path in (SERVER_DIR, WORKER_SERVER, FIXTURES, REPO):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import core  # noqa: E402
import gather  # noqa: E402
import jobs  # noqa: E402
import store  # noqa: E402
from dsh_worker_testenv import make_temp_dir, remove_tree  # noqa: E402

IST = timezone(timedelta(hours=5, minutes=30))
# 2026-10-21 is a Wednesday: 03:00 and 16:00 are outside peak, 07:00 is inside.
OFF_PEAK = datetime(2026, 10, 21, 3, 0, tzinfo=IST)
PEAK = datetime(2026, 10, 21, 7, 0, tzinfo=IST)
POST_CLOSE = datetime(2026, 10, 21, 16, 0, tzinfo=IST)
SATURDAY = datetime(2026, 10, 17, 12, 0, tzinfo=IST)
TEST_TMP = REPO / ".tmp" / "data-gather-tests"
TABLE = "mkt_feed_rows"


class DataGatherTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = make_temp_dir(TEST_TMP, "gather-")
        self.data_root = self.root / "reality_engine" / "data"
        self.data_root.mkdir(parents=True)
        self.raw_root = self.root / "raw"
        self.runtime = self.root / "gather-runtime"
        self.approved_path = self.root / "approved.yaml"
        self.env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith(("REALITY_", "DSH_"))
        }
        self.env.update(
            {
                "DSH_WORKER_REPO_ROOT": str(self.root),
                "DSH_WORKER_RUNTIME_DIR": str(self.root / "runtime"),
                "DSH_WORKTREES_ROOT": str(self.root / "worktrees"),
                "PYTHONUTF8": "1",
            }
        )
        self.manager = core.Manager(core.load_config(self.env))
        self.started: list[str] = []

    def tearDown(self) -> None:
        for run_id in self.started:
            try:
                self.manager.cancel_worker(run_id, confirm=True)
            except Exception:  # noqa: BLE001 - cleanup never fails a test
                pass
        remove_tree(self.root)

    # ------------------------------------------------------------- fixtures
    def _write_db(self, rows: list[tuple[str, str]], db_name: str = "feeds.db") -> Path:
        path = self.data_root / db_name
        connection = sqlite3.connect(path)
        try:
            connection.execute(
                f"CREATE TABLE IF NOT EXISTS {TABLE} (date TEXT, known_at TEXT)"
            )
            connection.executemany(f"INSERT INTO {TABLE} VALUES (?, ?)", rows)
            connection.commit()
        finally:
            connection.close()
        return path

    def _registry(self, entries: list[dict]) -> None:
        path = self.root / "jobs.yaml"
        path.write_text(
            yaml.safe_dump(
                {"schema": "dsh-worker-jobs/1", "jobs": entries}, sort_keys=False
            ),
            encoding="utf-8",
        )
        self.env["DSH_WORKER_JOBS_FILE"] = str(path)
        self.manager = core.Manager(core.load_config(self.env))

    def _command(
        self,
        new_date: str = "2026-10-20",
        known_at: str | None = None,
        *,
        raw: bool = True,
        lines: int = 0,
        sleep: float = 0.0,
    ) -> str:
        db_path = (self.data_root / "feeds.db").as_posix()
        raw_dir = (self.raw_root / "etf").as_posix()
        code = [
            "import sqlite3, pathlib, time",
            f"p = pathlib.Path({db_path!r})",
        ]
        if sleep:
            code.append(f"time.sleep({sleep})")
        code += [
            "c = sqlite3.connect(p)",
            f"c.execute('CREATE TABLE IF NOT EXISTS {TABLE} (date TEXT, known_at TEXT)')",
            f"c.execute('INSERT INTO {TABLE} VALUES (?, ?)', "
            f"({new_date!r}, {(known_at or new_date)!r}))",
            "c.commit(); c.close()",
        ]
        if raw:
            code += [
                f"r = pathlib.Path({raw_dir!r})",
                "r.mkdir(parents=True, exist_ok=True)",
                "(r / 'snapshot.csv').write_text('a,b\\n1,2\\n')",
            ]
        code.append("print('feed job wrote rows')")
        code += [f"print('line {index}')" for index in range(lines)]
        return "\n".join(code)

    def _entry(
        self,
        name: str,
        command: str,
        *,
        locks: list[str] | None = None,
        success_check: dict | None = None,
        enabled: bool = True,
    ) -> dict:
        return {
            "name": name,
            "description": f"offline fake feed {name}",
            "argv": ["python", "-c", command],
            "cwd": ".",
            "env": {},
            "writes": [f"feeds.db:{TABLE}"],
            "resource_locks": locks or ["db:feeds.db"],
            "cadence": "daily",
            "success_check": success_check,
            "off_peak_only": False,
            "market_hours": "any",
            "needs_paid_api": False,
            "needs_gpu": False,
            "enabled": enabled,
        }

    def _approve(self, feeds: dict | None) -> None:
        self.approved_path.write_text(
            yaml.safe_dump(
                {"schema": "data-gather-approved/1", "feeds": feeds or {}},
                sort_keys=False,
            ),
            encoding="utf-8",
        )

    def _service(self, *, now=OFF_PEAK, calendar=None) -> gather.GatherService:
        kwargs = {"calendar": calendar} if calendar else {}
        return gather.GatherService(
            self.manager,
            now=now,
            approved_path=self.approved_path,
            raw_root=self.raw_root,
            runtime_dir=self.runtime,
            **kwargs,
        )

    def _start(self, service: gather.GatherService, *args, **kwargs) -> dict:
        result = service.run_feed(*args, **kwargs)
        self.started.append(result["run_id"])
        return result

    def _wait_final(self, run_id: str, timeout: float = 90.0) -> dict:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            status = self.manager.get_status(run_id)
            if status.get("final"):
                return status
            time.sleep(0.25)
        self.fail(f"run {run_id} did not reach a final phase")

    # ----------------------------------------------------------- list_feeds
    def test_list_feeds_matches_list_jobs_freshness(self) -> None:
        self._write_db([("2026-10-20", "2026-10-20")])
        self._registry(
            [
                self._entry(
                    "feed_maxdate",
                    "print('x')",
                    success_check={
                        "db": "feeds.db",
                        "sql": f"SELECT max(date) AS value FROM {TABLE}",
                        "expect": {"kind": "max_date", "max_age_days": 400},
                    },
                ),
                self._entry(
                    "feed_count",
                    "print('x')",
                    success_check={
                        "db": "feeds.db",
                        "sql": f"SELECT count(*) AS value FROM {TABLE}",
                        "expect": {"kind": "min_count", "min_count": 1},
                    },
                ),
                self._entry("feed_nocheck", "print('x')"),
            ]
        )
        self._approve({"feed_maxdate": {"max_days": 5}})
        service = self._service()
        listed = service.list_feeds()
        self.assertTrue(listed["ok"], listed)
        self.assertEqual(listed["count"], 3)
        by_name = {row["name"]: row for row in listed["feeds"]}
        from_jobs = {item["name"]: item["freshness"] for item in self.manager.list_jobs()["jobs"]}
        for name in ("feed_maxdate", "feed_count", "feed_nocheck"):
            self.assertEqual(by_name[name]["freshness"], from_jobs[name])
        self.assertTrue(by_name["feed_maxdate"]["approved"])
        self.assertFalse(by_name["feed_count"]["approved"])
        self.assertEqual(by_name["feed_maxdate"]["max_days"], 5)
        self.assertEqual(by_name["feed_maxdate"]["age_vs_cadence"]["cadence_days"], 2.0)
        self.assertIsNone(by_name["feed_nocheck"]["freshness"])

    # ----------------------------------------------------------- gap_report
    def test_gap_report_uses_trading_days(self) -> None:
        calendar = self.data_root / "calendar.db"
        connection = sqlite3.connect(calendar)
        try:
            connection.execute(
                "CREATE TABLE mkt_nse_index_daily (date TEXT NOT NULL, index_name TEXT NOT NULL,"
                " PRIMARY KEY (date, index_name))"
            )
            connection.executemany(
                "INSERT INTO mkt_nse_index_daily VALUES (?, 'NIFTY 50')",
                [
                    ("2026-10-12",),
                    ("2026-10-13",),
                    ("2026-10-14",),
                    ("2026-10-15",),
                    ("2026-10-16",),
                ],
            )
            connection.commit()
        finally:
            connection.close()
        self._write_db(
            [("2026-10-12", "2026-10-12"), ("2026-10-13", "2026-10-13"),
             ("2026-10-15", "2026-10-15")]
        )
        self._registry([self._entry("feed_gap", "print('x')")])
        service = self._service(now=SATURDAY, calendar=("calendar.db", "mkt_nse_index_daily"))
        report = service.gap_report(["feed_gap"])
        self.assertTrue(report["ok"], report)
        row = report["feeds"][0]
        self.assertTrue(row["market"], row)
        self.assertEqual(row["expected"], 5)
        self.assertEqual(row["present"], 3)
        self.assertEqual(
            [item["start"] for item in row["missing_ranges"]],
            ["2026-10-14", "2026-10-16"],
        )
        self.assertEqual(row["missing_days"], 2)
        other = service.gap_report(["feed_gap"])["feeds"][0]["window"]
        self.assertEqual(other["end"], "2026-10-17")

    def test_gap_report_skips_non_market_feed(self) -> None:
        entry = self._entry("feed_docs", "print('x')")
        entry["writes"] = ["docs.db:raw_documents"]
        self._registry([entry])
        service = self._service()
        row = service.gap_report(["feed_docs"])["feeds"][0]
        self.assertFalse(row["market"])
        self.assertEqual(row["skipped"], "not_a_market_feed")

    # ------------------------------------------------------------ run_feed
    def test_run_feed_refuses_unapproved_feed(self) -> None:
        self._write_db([])
        self._registry([self._entry("feed_unapproved", "print('x')")])
        self._approve({"another_feed": None})
        with self.assertRaises(core.PluginError) as ctx:
            self._service().run_feed("feed_unapproved")
        self.assertEqual(ctx.exception.code, "feed_not_approved")
        self.assertFalse((self.root / "runtime" / "jobs").exists())

    def test_run_feed_refuses_peak_for_net_heavy_feed(self) -> None:
        self._write_db([])
        self._registry(
            [
                self._entry(
                    "feed_net",
                    "print('x')",
                    locks=["db:feeds.db", "net:www.nseindia.com"],
                )
            ]
        )
        self._approve({"feed_net": None})
        with self.assertRaises(core.PluginError) as ctx:
            self._service(now=PEAK).run_feed("feed_net")
        self.assertEqual(ctx.exception.code, "peak_hours")
        self.assertTrue(ctx.exception.details.get("net_heavy"))
        self.assertFalse((self.root / "runtime" / "jobs").exists())

    def test_run_feed_refuses_window_over_max_days(self) -> None:
        self._write_db([])
        self._registry([self._entry("feed_small", "print('x')")])
        self._approve({"feed_small": {"max_days": 3}})
        with self.assertRaises(core.PluginError) as ctx:
            self._service().run_feed(
                "feed_small", start="2026-10-01", end="2026-10-10"
            )
        self.assertEqual(ctx.exception.code, "window_too_large")

    def test_run_feed_and_verify(self) -> None:
        self._write_db([("2026-10-19", "2026-10-19")])
        self._registry([self._entry("feed_ok", self._command(), enabled=False)])
        self._approve({"feed_ok": {"max_days": 3}})
        service = self._service()
        started = self._start(service, "feed_ok")
        self.assertTrue(started["ok"], started)
        self.assertTrue(core.valid_job_id(started["run_id"]), started["run_id"])
        final = self._wait_final(started["run_id"])
        self.assertEqual(final["phase"], "finished", final)
        verified = service.verify_feed("feed_ok", started["run_id"])
        self.assertTrue(verified["ok"], verified)
        self.assertEqual(verified["failed"], 0)
        checks = {
            (check["check"], check.get("table")): check for check in verified["checks"]
        }
        rows = checks[("row_count", TABLE)]
        self.assertEqual((rows["before"], rows["after"], rows["delta"]), (1, 2, 1))
        max_date = checks[("max_date", TABLE)]
        self.assertEqual((max_date["before"], max_date["after"]), ("2026-10-19", "2026-10-20"))
        new_rows = checks[("new_rows_source_date", TABLE)]
        self.assertTrue(new_rows["ok"], new_rows)
        self.assertEqual(new_rows["source_column"], "known_at")
        self.assertTrue(new_rows["rows"][0]["match"])
        raw = next(check for check in verified["checks"] if check["check"] == "raw_files")
        self.assertTrue(raw["ok"], raw)
        self.assertIn("etf/snapshot.csv", raw["files"])
        misplaced = next(
            check for check in verified["checks"] if check["check"] == "raw_not_in_data_root"
        )
        self.assertTrue(misplaced["ok"], misplaced)
        status = service.feed_status(started["run_id"])
        self.assertTrue(status["final"])
        self.assertIn("feed job wrote rows", "\n".join(status["stdout"]))

    def test_verify_flags_stored_date_versus_source_date(self) -> None:
        self._write_db([("2026-10-19", "2026-10-19")])
        self._registry(
            [self._entry("feed_misdated", self._command(known_at="2026-10-17"))]
        )
        self._approve({"feed_misdated": None})
        service = self._service()
        started = self._start(service, "feed_misdated")
        self._wait_final(started["run_id"])
        verified = service.verify_feed("feed_misdated", started["run_id"])
        self.assertFalse(verified["ok"], verified)
        failed = [check for check in verified["checks"] if check["ok"] is False]
        self.assertEqual([check["check"] for check in failed], ["new_rows_source_date"])
        self.assertEqual(failed[0]["rows"][0]["stored"], "2026-10-20")
        self.assertEqual(failed[0]["rows"][0]["source"], "2026-10-17")
        self.assertEqual(failed[0]["rows"][0]["lag_days"], 3)

    def test_verify_refuses_before_the_run_finishes(self) -> None:
        self._write_db([])
        self._registry([self._entry("feed_slow", self._command(sleep=6.0))])
        self._approve({"feed_slow": None})
        service = self._service()
        started = self._start(service, "feed_slow")
        with self.assertRaises(core.PluginError) as ctx:
            service.verify_feed("feed_slow", started["run_id"])
        self.assertEqual(ctx.exception.code, "run_not_finished")

    def test_run_feed_resource_busy(self) -> None:
        self._write_db([])
        self._registry([self._entry("feed_hold", self._command(sleep=10.0))])
        self._approve({"feed_hold": None})
        service = self._service()
        started = self._start(service, "feed_hold")
        with self.assertRaises(core.PluginError) as ctx:
            service.run_feed("feed_hold")
        self.assertEqual(ctx.exception.code, "resource_busy")
        self.assertIn("db:feeds.db", ctx.exception.details.get("resource_locks", []))
        self.assertTrue(self.manager.cancel_worker(started["run_id"], confirm=True)["ok"])

    def test_feed_status_tail_is_bounded(self) -> None:
        self._write_db([])
        self._registry([self._entry("feed_chatty", self._command(lines=60))])
        self._approve({"feed_chatty": None})
        service = self._service()
        started = self._start(service, "feed_chatty")
        self._wait_final(started["run_id"])
        status = service.feed_status(started["run_id"])
        self.assertEqual(len(status["stdout"]), gather.TAIL_LINES)
        self.assertEqual(status["stdout"][-1], "line 59")
        self.assertLessEqual(len(status["stderr"]), gather.TAIL_LINES)

    def test_verify_requires_a_snapshot(self) -> None:
        self._write_db([])
        self._registry([self._entry("feed_ok", "print('x')")])
        self._approve({"feed_ok": None})
        service = self._service()
        with self.assertRaises(core.PluginError) as ctx:
            service.verify_feed("feed_ok", store.new_job_id())
        self.assertEqual(ctx.exception.code, "no_snapshot")

    # ----------------------------------------------------- shipped approvals
    def test_shipped_approved_feeds_exist_in_the_live_registry(self) -> None:
        import feeds

        approved = feeds.load_approved(PLUGIN / "approved.yaml")
        self.assertTrue(approved, "plugins/data-gather/approved.yaml approves nothing")
        registry = jobs.load_registry(REPO / "plugins" / "dsh-worker" / "jobs.yaml")
        missing = sorted(set(approved) - set(registry["jobs"]))
        self.assertEqual(missing, [])
        for name, approval in approved.items():
            self.assertIsNotNone(approval.get("max_days"), name)


if __name__ == "__main__":
    unittest.main()
