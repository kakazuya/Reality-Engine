"""T-239 wiring tests: hy4 observations + T-231 events served from a store (synthetic fixtures)."""
from __future__ import annotations

import os
import shutil
import sqlite3
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SERVER_DIR = ROOT / "plugins" / "reality-data" / "server"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SERVER_DIR))

import lookups_pilot3 as p3
import reality_engine.scripts.load_observations as loader

REAL_OBS = Path("D:/RealityEngine/t230/obs_91_j.db")
REAL_EVENTS = Path("D:/RealityEngine/t231/events.db")
REAL_STORE = Path("D:/RealityEngine/tg_build/measure10/c01/c01.db")
TMP = ROOT / ".tmp" / "obs_wiring_fixtures"


def _clone_table(src_path: Path, table: str, dst: sqlite3.Connection) -> None:
    src = sqlite3.connect(f"file:{src_path}?mode=ro", uri=True)
    sql = src.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()[0]
    dst.executescript(sql)
    src.close()


import shutil as _shutil

def _make_store(d: Path) -> Path:
    db = d / "store.db"
    _shutil.copyfile(REAL_STORE, db)
    con = sqlite3.connect(db)
    # wipe all tables
    tables = [r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()]
    for t in tables:
        con.execute(f"DELETE FROM {t}")
    con.execute("INSERT INTO company (symbol, isin, bse_code, name) VALUES ('TEST','INE000000000','123456','Test Co')")
    try:
        con.execute("INSERT INTO doc_page_fts(doc_page_fts) VALUES ('rebuild')")
    except Exception:
        pass
    con.commit()
    con.close()
    return db


def _make_obs_db(d: Path, name: str) -> Path:
    db = d / name
    con = sqlite3.connect(db)
    _clone_table(REAL_OBS, "observation", con)
    _clone_table(REAL_OBS, "measure_new", con)
    con.commit()
    con.close()
    return db


def _make_events_db(d: Path) -> Path:
    db = d / "events.db"
    con = sqlite3.connect(db)
    _clone_table(REAL_EVENTS, "event", con)
    con.commit()
    con.close()
    return db


def _insert_obs(con, **kw):
    cols = [r[1] for r in con.execute("PRAGMA table_info(observation)").fetchall()]
    notnull = {r[1]: r[3] for r in con.execute("PRAGMA table_info(observation)").fetchall()}
    vals = [kw.get(c, None) for c in cols]
    for i, c in enumerate(cols):
        if vals[i] is None:
            if c == "symbol":
                vals[i] = "TEST"
            elif c == "doc_key":
                vals[i] = "d.pdf"
            elif c == "page":
                vals[i] = 1
            elif c == "known_at":
                vals[i] = "2026-01-01T00:00:00"
            elif c == "measure":
                vals[i] = "revenue"
            elif c == "status":
                vals[i] = "verified"
            elif c == "record_type":
                vals[i] = "number"
            elif c == "scale":
                vals[i] = 1.0
            elif c == "adjusted" or c == "is_total":
                vals[i] = 0
            else:
                vals[i] = "" if notnull.get(c, 0) else None
    for k, v in kw.items():
        if k in cols:
            vals[cols.index(k)] = v
    con.execute(f"INSERT INTO observation ({','.join(cols)}) VALUES ({','.join('?'*len(cols))})", vals)


def _insert_event(con, **kw):
    cols = [r[1] for r in con.execute("PRAGMA table_info(event)").fetchall()]
    vals = [kw.get(c, None) for c in cols]
    for i, c in enumerate(cols):
        if vals[i] is None:
            if c == "doc_key":
                vals[i] = "d.pdf"
            elif c == "kind":
                vals[i] = "order_win"
            elif c == "method":
                vals[i] = "script"
            elif c == "status":
                vals[i] = "verified"
            elif c == "seq":
                vals[i] = 1
            elif c == "symbol":
                vals[i] = "TEST"
            elif c == "entity_scope":
                vals[i] = "company"
            else:
                vals[i] = None
    for k, v in kw.items():
        if k in cols:
            vals[cols.index(k)] = v
    con.execute(f"INSERT INTO event ({','.join(cols)}) VALUES ({','.join('?'*len(cols))})", vals)


class ObsWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if TMP.exists():
            shutil.rmtree(TMP)
        TMP.mkdir(parents=True)
        d = TMP
        cls.store = _make_store(d)
        cls.deck_db = _make_obs_db(d, "deck.db")
        cls.ar_db = _make_obs_db(d, "ar.db")
        cls.tr_db = _make_obs_db(d, "tr.db")
        cls.ev_db = _make_events_db(d)

        con = sqlite3.connect(cls.deck_db)
        _insert_obs(con, symbol="TEST", measure="revenue", status="verified", record_type="number",
                    value=100.0, period="Q1FY26", known_at="2026-01-01T00:00:00")
        _insert_obs(con, symbol="TEST", measure="revenue", status="quarantined", record_type="number",
                    value=999.0, period="Q1FY26", known_at="2026-01-02T00:00:00")
        for i in range(50):
            _insert_obs(con, symbol="TEST", measure="revenue", status="verified", record_type="number",
                        value=10.0 + i, period="Q1FY26",
                        known_at=f"2026-02-{(i % 28) + 1:02d}T00:00:00")
        _insert_obs(con, symbol="TEST", measure="revenue_growth_yoy", status="verified", record_type="number",
                    value=200.0, period="Q1FY26", known_at="2026-03-01T00:00:00")
        _insert_obs(con, symbol="TEST", measure="x", status="verified", record_type="statement",
                    statement="old needle statement", known_at="2025-01-01T00:00:00")
        _insert_obs(con, symbol="TEST", measure="revenue", status="verified", record_type="number",
                    value=777.0, period="Q1FY26", known_at="2027-01-01T00:00:00")
        con.commit()
        con.close()

        con = sqlite3.connect(cls.ar_db)
        _insert_obs(con, symbol="TEST", measure="revenue", status="unverified", record_type="number",
                    value=150.0, period="Q1FY26", known_at="2026-01-03T00:00:00")
        con.commit()
        con.close()

        con = sqlite3.connect(cls.ev_db)
        _insert_event(con, symbol="TEST", kind="order_win", status="verified",
                      quote="won an order", known_at="2026-01-01T00:00:00", filing_date="2026-01-01")
        _insert_event(con, symbol="TEST", kind="capex_approval", status="verified",
                      quote="capex approved", known_at="2026-01-02T00:00:00", filing_date="2026-01-02")
        con.commit()
        con.close()

        loader.OBS_SOURCES = [
            ("deck", str(cls.deck_db), "deck"),
            ("annual_report", str(cls.ar_db), "annual_report"),
            ("transcript", str(cls.tr_db), "transcript"),
        ]
        loader.EVENTS_DB = str(cls.ev_db)
        loader._load_store(cls.store, "TEST")

        os.environ["REALITY_PILOT3_DB"] = str(cls.store)
        p3.close()

    @classmethod
    def tearDownClass(cls):
        p3.close()
        os.environ.pop("REALITY_PILOT3_DB", None)
        if TMP.exists():
            shutil.rmtree(TMP, ignore_errors=True)

    def test_idempotent(self):
        con = sqlite3.connect(self.store)
        before = con.execute("SELECT COUNT(*) FROM obs_fact").fetchone()[0]
        ev_before = con.execute("SELECT COUNT(*) FROM filing_event").fetchone()[0]
        con.close()
        loader._load_store(self.store, "TEST")
        con = sqlite3.connect(self.store)
        after = con.execute("SELECT COUNT(*) FROM obs_fact").fetchone()[0]
        ev_after = con.execute("SELECT COUNT(*) FROM filing_event").fetchone()[0]
        con.close()
        self.assertEqual(before, after)
        self.assertEqual(ev_before, ev_after)

    def test_quarantined_excluded(self):
        con = sqlite3.connect(self.store)
        vals = [r[0] for r in con.execute("SELECT value FROM obs_fact WHERE measure='revenue'").fetchall()]
        con.close()
        self.assertNotIn(999.0, vals)

    def test_as_of_cut(self):
        out = p3.obs("TEST", measure="revenue", as_of="2026-06-01")
        vals = [r["value"] for r in out["rows"]]
        self.assertNotIn(777.0, vals)

    def test_fin_fallback_exact_and_source(self):
        out = p3.fin("TEST", "revenue", "Q1FY26", as_of="2026-01-02")
        self.assertTrue(out["found"])
        vals = [r["value"] for r in out["rows"]]
        self.assertIn(100.0, vals)
        self.assertNotIn(200.0, vals)
        self.assertNotIn(200.0, vals)
        row = next(r for r in out["rows"] if r["value"] == 100.0)
        self.assertEqual(row["status"], "verified")
        self.assertEqual(row["source"], "obs_fact")

    def test_statements_topic_filter(self):
        out = p3.statements("TEST", topic="needle")
        quotes = [r.get("quote") for r in out["rows"]]
        self.assertTrue(any("old needle statement" in (q or "") for q in quotes))
        out2 = p3.statements("TEST", topic="revenue")
        quotes2 = [r.get("quote") for r in out2["rows"]]
        self.assertFalse(any("old needle statement" in (q or "") for q in quotes2))

    def test_terms_finds_old_row_beyond_limit(self):
        out = p3.obs("TEST", terms="needle", limit=5)
        self.assertTrue(out["found"])
        self.assertTrue(any("needle" in (r.get("statement") or "") for r in out["rows"]))

    def test_pilot3_obs_partial_labelled(self):
        out = p3.obs("TEST", measure="revenue")
        self.assertTrue(any(r.get("match") == "partial" for r in out["rows"]))

    def test_pilot3_events_kind_filter(self):
        out = p3.events("TEST", kind="order_win")
        self.assertTrue(out["found"])
        self.assertTrue(all(r["kind"] == "order_win" for r in out["rows"]))
        out2 = p3.events("TEST", kind="capex_approval")
        self.assertTrue(any(r["kind"] == "capex_approval" for r in out2["rows"]))


if __name__ == "__main__":
    unittest.main()


def test_exact_mode_drops_derived_names(tmp_path, monkeypatch):
    """Wolf review: fin('revenue') must not return revenue_growth_yoy rows."""
    import sqlite3, sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "plugins" / "reality-data" / "server"))
    import lookups_pilot3 as L
    db = tmp_path / "s.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE company(symbol TEXT)")
    con.execute("INSERT INTO company VALUES('ABC')")
    con.execute("CREATE TABLE obs_fact(observation_id INTEGER, symbol TEXT, measure TEXT, record_type TEXT, status TEXT,"
                " period TEXT, known_at TEXT, value REAL, unit TEXT, scale REAL, doc_key TEXT, page INTEGER,"
                " source TEXT, doc_type TEXT, statement TEXT)")
    con.executemany("INSERT INTO obs_fact VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", [
        (1, "ABC", "revenue_from_operations", "number", "verified", "FY25", "2025-05-01", 100, "INR", 1e7, "d", 1, "deck", "deck", None),
        (2, "ABC", "revenue_growth_yoy", "number", "verified", "FY25", "2025-05-01", 12, "%", 1, "d", 1, "deck", "deck", None)])
    con.commit(); con.close()
    monkeypatch.setenv("REALITY_PILOT3_DB", str(db))
    L.select_store(str(db)) if hasattr(L, "select_store") else None
    names = [r["measure"] for r in L._obs_rows("ABC", measure="revenue", record_type="number", measure_exact=True)]
    assert "revenue_growth_yoy" not in names
