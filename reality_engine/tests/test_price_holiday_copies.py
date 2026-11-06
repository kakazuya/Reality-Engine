"""Fixture check for the holiday-copy detector (T-089).

Two symbols, three stored dates: 2026-03-03 repeats 2026-03-02 exactly (a
holiday copy), 2026-03-04 is a real session with new prices.  The NSE index
table holds 03-02 and 03-04 only, so 03-03 reads as a holiday.
"""

import contextlib
import io
import sqlite3
import unittest
import uuid
from pathlib import Path

from reality_engine.scripts import price_holiday_copies as phc

PROJECT_ROOT = Path(__file__).resolve().parents[2]

DDL = """
CREATE TABLE daily_price_delivery (
    date TEXT, symbol TEXT, open REAL, high REAL, low REAL, close REAL,
    prev_close REAL, total_volume INTEGER, num_trades INTEGER, deliverable_volume INTEGER
)
"""

REAL = [
    ("2026-03-02", "INFY", 100.0, 101.0, 99.0, 100.5, 99.5, 1000, 10, 500),
    ("2026-03-02", "TCS", 200.0, 201.0, 199.0, 200.5, 199.5, 2000, 20, 900),
]
COPY = [
    ("2026-03-03", "INFY", 100.0, 101.0, 99.0, 100.5, 99.5, 1000, 10, 500),
    ("2026-03-03", "TCS", 200.0, 201.0, 199.0, 200.5, 199.5, 2000, 20, 900),
]
NEXT = [
    ("2026-03-04", "INFY", 102.0, 103.0, 101.0, 102.5, 100.5, 1200, 12, 600),
    ("2026-03-04", "TCS", 202.0, 203.0, 201.0, 202.5, 200.5, 2200, 22, 950),
]


def make_db(path: Path, with_nse_index: bool) -> None:
    con = sqlite3.connect(path)
    con.execute(DDL)
    con.executemany("INSERT INTO daily_price_delivery VALUES (?,?,?,?,?,?,?,?,?,?)",
                    REAL + COPY + NEXT)
    if with_nse_index:
        con.execute("CREATE TABLE mkt_nse_index_daily (date TEXT, index_name TEXT)")
        con.executemany("INSERT INTO mkt_nse_index_daily VALUES (?, ?)",
                        [("2026-03-02", "NIFTY 50"), ("2026-03-04", "NIFTY 50")])
    con.commit()
    con.close()


def connect_ro(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    con.execute("PRAGMA query_only=1")
    return con


class PriceHolidayCopiesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # A tempfile.mkdtemp directory under .tmp is not writable by SQLite in
        # this sandbox (the subdirectory's ACL denies new entries), so the
        # fixture files live in .tmp itself and are removed in tearDownClass.
        tmp = PROJECT_ROOT / ".tmp"
        tmp.mkdir(exist_ok=True)
        tag = uuid.uuid4().hex[:8]
        cls.db = tmp / f"T089_fixture_{tag}.db"
        cls.plain_db = tmp / f"T089_fixture_plain_{tag}.db"
        make_db(cls.db, with_nse_index=True)
        make_db(cls.plain_db, with_nse_index=False)
        cls.plan = tmp / f"T089_plan_{tag}.csv"

    @classmethod
    def tearDownClass(cls):
        for path in (cls.db, cls.plain_db, cls.plan):
            try:
                path.unlink()
            except OSError:
                pass

    def count_rows(self, db: Path) -> int:
        con = connect_ro(db)
        try:
            return con.execute("SELECT COUNT(*) FROM daily_price_delivery").fetchone()[0]
        finally:
            con.close()

    def test_scan_flags_only_the_copied_date(self):
        con = connect_ro(self.db)
        try:
            copies = phc.scan(con)
        finally:
            con.close()
        self.assertEqual([c["date"] for c in copies], ["2026-03-03"])
        copy = copies[0]
        self.assertEqual(copy["rows"], 2)
        self.assertEqual(copy["identical"], 2)
        self.assertEqual(copy["share"], 1.0)
        self.assertEqual(copy["holiday"], "yes")
        self.assertEqual(copy["prev_date"], "2026-03-02")

    def test_apply_plan_writes_csv_and_deletes_nothing(self):
        before = self.count_rows(self.db)
        with contextlib.redirect_stdout(io.StringIO()):
            rc = phc.main(["--db", str(self.db), "--apply-plan", str(self.plan)])
        self.assertEqual(rc, 0)
        self.assertEqual(self.plan.read_text().splitlines(),
                         ["date,symbol", "2026-03-03,INFY", "2026-03-03,TCS"])
        self.assertEqual(self.count_rows(self.db), before)

    def test_no_nse_table_still_flags_copy_as_unknown_holiday(self):
        con = connect_ro(self.plain_db)
        try:
            copies = phc.scan(con)
        finally:
            con.close()
        self.assertEqual([c["date"] for c in copies], ["2026-03-03"])
        self.assertEqual(copies[0]["holiday"], "unknown")

    def test_connection_refuses_writes(self):
        con = connect_ro(self.db)
        try:
            with self.assertRaises(sqlite3.OperationalError):
                con.execute("INSERT INTO daily_price_delivery (date, symbol) VALUES ('2026-03-05', 'X')")
        finally:
            con.close()


if __name__ == "__main__":
    unittest.main()
