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
        rid = con.execute("SELECT observation_id FROM observation WHERE value=150.0").fetchone()[0]
        con.close()
        verdicts = d / "verdicts.jsonl"
        verdicts.write_text('{"id": %d, "verdict": "fix", "period": "Q1FY26", "basis": "standalone", '
                            '"evidence": "Revenue 150", "header": "Q1 FY26"}\n' % rid, encoding="utf-8")
        loader.CHECKS = {str(cls.ar_db): [str(verdicts)]}

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
        loader.EVENTS_PRIORITY = []
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

    def test_model_check_is_served_labelled_and_keeps_the_row(self):
        out = p3.obs("TEST", measure="revenue", status="unverified")
        row = next(r for r in out["rows"] if r["value"] == 150.0)
        self.assertEqual(row["status"], "unverified")
        self.assertEqual(row["check"]["status"], "model_checked")
        self.assertEqual(row["check"]["corrected"], {"period": "Q1FY26", "basis": "standalone"})
        others = [r for r in out["rows"] if r["value"] != 150.0]
        self.assertTrue(all("check" not in r for r in others))

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


class SourcePriorityTests(unittest.TestCase):
    """T-242: dbs sharing a source are a priority list; the first db holding the symbol wins, else the next."""

    def test_first_db_with_rows_wins_and_events_fall_back(self):
        d = TMP / "priority"
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True)
        store = _make_store(d)
        new_tr, old_tr, deck = _make_obs_db(d, "new_tr.db"), _make_obs_db(d, "old_tr.db"), _make_obs_db(d, "deck.db")
        for db, text in ((new_tr, "new read"), (old_tr, "old read")):
            con = sqlite3.connect(db)
            _insert_obs(con, symbol="TEST", measure="capex", status="verified", record_type="statement",
                        statement=text, doc_key="t.pdf")
            con.commit()
            con.close()
        con = sqlite3.connect(deck)                    # deck: only the OLD db has this symbol
        _insert_obs(con, symbol="TEST", measure="revenue", status="verified", record_type="number", doc_key="o.pdf")
        con.commit()
        con.close()
        empty_deck = _make_obs_db(d, "deck_new.db")
        old_ev, new_ev = _make_events_db(d), d / "events_new.db"
        con = sqlite3.connect(new_ev)
        _clone_table(REAL_EVENTS, "event", con)
        con.execute("ALTER TABLE event ADD COLUMN customer_desc TEXT")
        _insert_event(con, symbol="TEST", kind="order_win", status="verified", quote="new event",
                      customer_desc="a leading MNC", known_at="2026-01-01T00:00:00", filing_date="2026-01-01")
        con.commit()
        con.close()
        saved = (loader.OBS_SOURCES, loader.EVENTS_DB, loader.EVENTS_PRIORITY)
        try:
            loader.OBS_SOURCES = [("deck_new", str(empty_deck), "deck"), ("deck", str(deck), "deck"),
                                  ("tr_new", str(new_tr), "transcript"), ("tr_old", str(old_tr), "transcript")]
            loader.EVENTS_DB, loader.EVENTS_PRIORITY = str(old_ev), [str(new_ev)]
            stats = loader._load_store(store, "TEST")
        finally:
            loader.OBS_SOURCES, loader.EVENTS_DB, loader.EVENTS_PRIORITY = saved
        con = sqlite3.connect(store)
        texts = [r[0] for r in con.execute("SELECT statement FROM obs_fact WHERE source='transcript'")]
        decks = con.execute("SELECT COUNT(*) FROM obs_fact WHERE source='deck'").fetchone()[0]
        ev = con.execute("SELECT quote, customer_desc FROM filing_event").fetchall()
        con.close()
        self.assertEqual(texts, ["new read"])                 # the newer db replaced the older one
        self.assertEqual(decks, 1)                            # an empty newer db falls back to the older
        self.assertEqual(stats["obs_db"]["deck"], str(deck))
        self.assertEqual(ev, [("new event", "a leading MNC")])  # the newer events db, with its new column


class RetrievalFix1Tests(unittest.TestCase):
    """T-242 retrieval fix 1: verified obs_fact outranks unverified kpi/page_cell, XBRL still wins, measure
    matching & aliases, _nearest number rows, statements merge/dedupe, guidance period & verified ranking."""

    @classmethod
    def setUpClass(cls):
        d = TMP / "rfix1"
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True)
        cls.store = _make_store(d)
        con = sqlite3.connect(cls.store)
        con.execute("INSERT INTO doc (doc_key, symbol, doc_type, title, filing_date, known_at, pages) "
                    "VALUES ('d_deck.pdf','TEST','deck','Q2FY27 Deck','2026-11-05','2026-11-05T10:00:00',10),"
                    "('d_old_call.pdf','TEST','transcript','Q1FY27 Earnings Call','2026-08-05','2026-08-05T10:00:00',10),"
                    "('d_new_call.pdf','TEST','transcript','Q2FY27 Earnings Call','2026-11-10','2026-11-10T10:00:00',10)")
        # 1. kpi_series unverified AUM (46) vs obs_fact verified aum.value (326) for H1FY27
        con.execute("INSERT INTO kpi_series (symbol, metric, dimension, value, unit, scale, period_type, "
                    "fiscal_period, basis, doc_key, page, quote, known_at, is_reported, extractor_rule) "
                    "VALUES ('TEST','aum','total',46.0,'inr_bn',1e9,'H','H1FY27','not_stated','d_deck.pdf',6,"
                    "'AUM Salaried 46 bn','2026-11-05T10:00:00',1,'t')")
        kid = con.execute("SELECT last_insert_rowid()").fetchone()[0]
        con.execute("INSERT INTO row_check (tbl, row_id, symbol, metric, status, checker) "
                    "VALUES ('kpi_series',?,'TEST','aum','unverified','t')", (kid,))
        # unverified page_cell for capacity utilisation
        con.execute("CREATE TABLE IF NOT EXISTS page_cell (doc_key TEXT, page INTEGER, symbol TEXT, known_at TEXT, "
                    "reader TEXT, table_title TEXT, row_label TEXT, col_header TEXT, value_text TEXT, "
                    "unit_text TEXT, status TEXT, conflict TEXT)")
        con.execute("INSERT INTO page_cell (doc_key, page, symbol, known_at, reader, table_title, row_label, "
                    "col_header, value_text, unit_text, status) VALUES "
                    "('d_deck.pdf',6,'TEST','2026-11-05T10:00:00','dots','Ops','Capacity Utilization','Q2FY27','70','%','unverified')")
        # XBRL PAT for Q2FY27 (must still outrank obs_fact verified pat)
        con.execute("INSERT INTO fin_quarter_xbrl (symbol, isin, period_start, period_end, fiscal_period, basis, "
                    "audited, statement, line_item, xbrl_tag, value, unit, scale, source_file, source_db, "
                    "source_table, source_rowid, known_at, known_at_source, is_reported) VALUES "
                    "('TEST','INE000000000','2026-07-01','2026-09-30','Q2FY27','consolidated','u','PL','pat',"
                    "'ProfitLoss',511.53,'inr',1e6,'xbrl.xml','results_xbrl.db','q','1','2026-11-01T10:00:00','x',1)")
        # Legacy transcript_statement: 18 rows (exceeds row_cut 15) + 1 exact duplicate of obs_fact statement
        for i in range(18):
            q = ("Freight costs remained elevated for exports." if i == 0
                 else f"Generic commentary line number {i} on business operations.")
            con.execute("INSERT INTO transcript_statement (symbol, doc_key, call_date, call_period, page, seq, "
                        "speaker, role, section, topics, period_discussed, numbers_json, statement, quote, is_fragment, "
                        "known_at, known_at_source, extractor_rule) VALUES "
                        "('TEST','d_new_call.pdf','2026-11-10','Q2FY27',4,?,'Mgr','md','prepared','margin',"
                        "'Q2FY27','[]',?,?,0,'2026-11-10T10:00:00','x','t')", (i + 1, q, q))
        # Legacy unverified guidance row
        con.execute("INSERT INTO guidance (id, symbol, isin, metric, target_period, low, high, unit, direction, "
                    "said_on, doc_key, page, quote, speaker, known_at, known_at_source, extractor_rule) VALUES "
                    "(1,'TEST','INE000000000','ebitda_margin','FY27',10.0,12.0,'pct','flat','2026-11-05','d_deck.pdf',5,"
                    "'Legacy unverified margin guidance','Mgr','2026-11-05T10:00:00','x','t')")
        con.execute("INSERT INTO row_check (tbl, row_id, symbol, metric, status, checker) "
                    "VALUES ('guidance',1,'TEST','ebitda_margin','unverified','t')")
        # obs_fact table is already cloned empty by _make_store from c01.db
        obs_cols = [r[1] for r in con.execute("PRAGMA table_info(obs_fact)").fetchall()]
        if "source" not in obs_cols:
            con.execute("ALTER TABLE obs_fact ADD COLUMN source TEXT")
        if "doc_type" not in obs_cols:
            con.execute("ALTER TABLE obs_fact ADD COLUMN doc_type TEXT")

        def add_obs(**kw):
            cols = [r[1] for r in con.execute("PRAGMA table_info(obs_fact)").fetchall()]
            notnull = {r[1]: r[3] for r in con.execute("PRAGMA table_info(obs_fact)").fetchall()}
            defaults = {"symbol": "TEST", "doc_key": "d_deck.pdf", "page": 1, "known_at": "2026-11-05T10:00:00",
                        "status": "verified", "record_type": "number", "scale": 1.0, "adjusted": 0, "is_total": 0,
                        "source": "deck", "doc_type": "deck"}
            vals = [kw.get(c, defaults.get(c, "" if notnull.get(c, 0) else None)) for c in cols]
            con.execute(f"INSERT INTO obs_fact ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", vals)

        # Verified obs_fact rows for Step 1 & 2
        add_obs(measure="aum.value", printed_label="AUM of", value=326.0, unit="Bn", scale=1e9, period="H1 FY27", page=15)
        add_obs(measure="profit_before_tax", printed_label="Profit Before Tax (PBT)", value=251.71, unit="₹ Lakhs",
                scale=1e5, period="H1 FY27", page=4)
        add_obs(measure="NEW:gross_written_premium", printed_label="GWP", value=7056.0, unit="crores", scale=1e7,
                period="Q2 FY27", page=4)
        add_obs(measure="capacity.utilisation", printed_label="Capacity Utilization (%)", value=84.0, unit="%",
                period="Q2FY27", segment="Yarn Division", page=6)
        add_obs(measure="revenue.value", printed_label="Revenue", value=103.0, unit="Rs. In Crs", scale=1e7,
                period="Q2FY27", segment="Yarn Division", page=6)
        add_obs(measure="pat", printed_label="PAT", value=999.0, unit="Mn", scale=1e6, period="Q2FY27", page=5)
        add_obs(measure="NEW:special_widget_count", printed_label="Widget output", value=42.0, unit="units",
                period="Q2FY27", page=7, status="verified")
        # Step 4 statements: older call + newer call, verified + unverified + duplicate of transcript_statement
        add_obs(record_type="statement", doc_key="d_old_call.pdf", doc_type="transcript", source="transcript",
                known_at="2026-08-05T10:00:00", measure="margin",
                statement="Q1FY27 call note on Truly Indian outlook.", status="verified", page=3)
        add_obs(record_type="statement", doc_key="d_new_call.pdf", doc_type="transcript", source="transcript",
                known_at="2026-11-10T10:00:00", measure="margin",
                statement="Freight costs remained elevated for exports.", status="verified", page=4)
        add_obs(record_type="statement", doc_key="d_new_call.pdf", doc_type="transcript", source="transcript",
                known_at="2026-11-10T10:00:00", measure="revenue.mix",
                statement="Unverified remark on Truly Indian exports.", status="unverified", page=5)
        # Step 4 guidance: verified FY27 + verified FY28
        add_obs(record_type="guidance", doc_key="d_new_call.pdf", doc_type="transcript", source="transcript",
                known_at="2026-11-10T10:00:00", measure="ebitda_margin", value=15.0, value_high=17.0,
                unit="%", period="FY27", statement="We expect 15% to 17% margin in FY27.", status="verified", page=6)
        add_obs(record_type="guidance", doc_key="d_new_call.pdf", doc_type="transcript", source="transcript",
                known_at="2026-11-10T10:00:00", measure="ebitda_margin", value=18.0, value_high=20.0,
                unit="%", period="FY28", statement="We expect 18% to 20% margin in FY28.", status="verified", page=6)
        con.commit()
        con.close()

    def setUp(self):
        self._prev = os.environ.get("REALITY_PILOT3_DB")
        os.environ["REALITY_PILOT3_DB"] = str(self.store)
        p3.close()

    def tearDown(self):
        p3.close()
        if self._prev is None:
            os.environ.pop("REALITY_PILOT3_DB", None)
        else:
            os.environ["REALITY_PILOT3_DB"] = self._prev

    def test_step1_verified_obs_beats_unverified_kpi_and_cell_while_xbrl_still_wins(self):
        aum = p3.fact("TEST", "AUM", period="H1FY27")
        self.assertTrue(aum["found"])
        self.assertEqual(aum["answer"]["value"], 326.0)
        self.assertEqual(aum["answer"]["source"]["table"], "obs_fact")
        self.assertEqual(aum["answer"]["check_status"], "verified")

        k_aum = p3.kpi("TEST", "AUM", period="H1FY27")
        self.assertEqual(k_aum["rows"][0]["value"], 326.0)
        self.assertEqual(k_aum["rows"][0]["source"], "obs_fact")
        self.assertEqual(k_aum["rows"][0]["status"], "verified")

        cu = p3.fact("TEST", "capacity utilisation", period="Q2FY27")
        self.assertEqual(cu["answer"]["value"], 84.0)
        self.assertEqual(cu["answer"]["source"]["table"], "obs_fact")

        # Counter-test: filed XBRL fin row still outranks verified obs_fact
        pat = p3.fact("TEST", "PAT", period="Q2FY27")
        self.assertEqual(pat["route"], "fin")
        self.assertEqual(pat["answer"]["value"], 511.53)
        self.assertEqual(pat["answer"]["source"]["table"], "fin_quarter_xbrl")

    def test_step2_aliases_and_segment_measure_matching(self):
        pbt = p3.fact("TEST", "PBT", period="H1FY27")
        self.assertEqual(pbt["answer"]["value"], 251.71)
        self.assertEqual(pbt["answer"]["source"]["table"], "obs_fact")

        gwp = p3.fact("TEST", "GWP", period="Q2FY27")
        self.assertEqual(gwp["answer"]["value"], 7056.0)
        self.assertEqual(gwp["answer"]["source"]["table"], "obs_fact")

        yarn = p3.fact("TEST", "Yarn revenue", period="Q2FY27")
        self.assertEqual(yarn["answer"]["value"], 103.0)
        self.assertEqual(yarn["answer"]["source"]["table"], "obs_fact")

    def test_step3_nearest_shows_obs_fact_number_fields(self):
        direct = p3._nearest("TEST", "widget")
        nums_direct = [n for n in direct if n.get("kind") == "number"]
        self.assertTrue(nums_direct)
        self.assertEqual(nums_direct[0]["value"], 42.0)
        self.assertEqual(nums_direct[0]["unit"], "units")
        self.assertEqual(nums_direct[0]["period"], "Q2FY27")
        self.assertEqual(nums_direct[0]["printed_label"], "Widget output")
        self.assertEqual(nums_direct[0]["status"], "verified")

        miss = p3.fact("TEST", "special widget forecast")
        self.assertFalse(miss["found"])
        nums = [n for n in miss["nearest"] if n.get("kind") == "number"]
        self.assertTrue(nums)
        self.assertEqual(nums[0]["value"], 42.0)
        self.assertEqual(nums[0]["unit"], "units")
        self.assertEqual(nums[0]["period"], "Q2FY27")
        self.assertEqual(nums[0]["printed_label"], "Widget output")
        self.assertEqual(nums[0]["status"], "verified")

    def test_step4_statements_merges_ranks_verified_first_and_dedupes(self):
        out = p3.statements("TEST", rank_terms="Freight Truly Indian", latest=True)
        quotes = [r["quote"] for r in out["rows"]]
        # Verified obs_fact statement survived row_cut(15) and ranks ahead of unverified obs and transcript rows
        self.assertEqual(quotes[0], "Freight costs remained elevated for exports.")
        self.assertEqual(out["rows"][0]["source"], "obs_fact")
        self.assertEqual(out["rows"][0]["status"], "verified")
        # Duplicate transcript_statement of the same sentence is dropped
        self.assertEqual(quotes.count("Freight costs remained elevated for exports."), 1)
        # latest=True excluded the Q1FY27 call obs_fact statement
        self.assertFalse(any("Q1FY27 call note" in q for q in quotes))

    def test_step4_guidance_filters_period_and_ranks_verified_first(self):
        out = p3.guidance("TEST", metric="ebitda_margin", period="FY27")
        self.assertTrue(out["found"])
        self.assertEqual(out["rows"][0]["status"], "verified")
        self.assertEqual(out["rows"][0]["source"], "obs_fact")
        self.assertEqual(out["rows"][0]["low"], 15.0)
        self.assertTrue(all(r["period"] == "FY27" for r in out["rows"]))

