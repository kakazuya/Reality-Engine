"""Contract for reality_engine.db.readonly.connect_ro (in-memory/temp only)."""
import sqlite3
import unittest
import uuid
from pathlib import Path

from reality_engine.db.readonly import QueryTimeout, connect_ro


class ConnectRoTests(unittest.TestCase):
    def setUp(self):
        # A file next to the test: the system temp dir is denied by some CI
        # sandboxes (same convention as test_insider_trades).
        self.path = (Path(__file__).resolve().parent /
                     f".readonly_{uuid.uuid4().hex}.db")
        con = sqlite3.connect(self.path)
        con.execute("CREATE TABLE t (x INTEGER)")
        con.executemany("INSERT INTO t VALUES (?)", [(i,) for i in range(2000)])
        con.commit()
        con.close()
        self.con = connect_ro(self.path, timeout_s=0.2)

    def tearDown(self):
        self.con.close()
        for suffix in ("", "-wal", "-shm"):
            Path(str(self.path) + suffix).unlink(missing_ok=True)

    def test_temp_store_is_memory_and_connection_is_query_only(self):
        self.assertEqual(self.con.execute("PRAGMA temp_store").fetchone()[0], 2)
        self.assertEqual(self.con.execute("PRAGMA query_only").fetchone()[0], 1)
        with self.assertRaises(sqlite3.OperationalError):
            self.con.execute("INSERT INTO t VALUES (99999)")

    def test_query_needing_a_temp_btree_runs(self):
        # ORDER BY over more rows than this tiny cache holds needs a temp
        # b-tree; the MEMORY setting keeps mode=ro off the unwritable temp dir.
        self.con.execute("PRAGMA cache_size=-8")
        row = self.con.execute(
            "SELECT count(*) FROM (SELECT x FROM t ORDER BY x DESC)").fetchone()
        self.assertEqual(row[0], 2000)

    def test_timeout_fires_during_fetchall(self):
        with self.assertRaises(QueryTimeout):
            cur = self.con.execute(
                "WITH RECURSIVE c(x) AS ("
                "SELECT 1 UNION ALL SELECT x + 1 FROM c WHERE x < 100000000"
                ") SELECT x FROM c")
            cur.fetchall()

    def test_timeout_fires_during_execute_and_later_queries_still_work(self):
        self.con.set_timeout(0.05)
        with self.assertRaises(QueryTimeout):
            self.con.execute(
                "WITH RECURSIVE c(x) AS ("
                "SELECT 1 UNION ALL SELECT x + 1 FROM c WHERE x < 200000000"
                ") SELECT count(*) FROM c").fetchone()
        self.con.set_timeout(5)
        self.assertEqual(self.con.execute("SELECT count(*) FROM t").fetchone()[0], 2000)

    def test_sql_tool_style_short_budget_translates_clear_error(self):
        self.con.set_timeout(0.01)
        with self.assertRaises(QueryTimeout) as ctx:
            self.con.execute(
                "WITH RECURSIVE c(x) AS ("
                "SELECT 1 UNION ALL SELECT x + 1 FROM c WHERE x < 200000000"
                ") SELECT count(*) FROM c").fetchone()
        self.assertIn("read-only connection", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
