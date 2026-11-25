"""T-242 retrieval fix 2: named-call ranking, natural-date periods, printed-label election, guidance election and
the shareholding route, on a tiny pilot3 store built in a temp directory from the real DDL.

    python -m unittest plugins/reality-data/tests/test_retrieval_fix2.py
"""
from __future__ import annotations

import sqlite3
import sys
import unittest
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[3]
SERVER_DIR = Path(__file__).resolve().parents[1] / "server"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SERVER_DIR))

import lookups_pilot3 as p3  # noqa: E402
from reality_engine.pilot3 import kpi as kpi_mod, schema, transcripts  # noqa: E402

SYM = "TST"
ISIN = "INE000000001"


class RetrievalFix2Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        tmp_root = ROOT / ".tmp"
        tmp_root.mkdir(exist_ok=True)
        cls.db = tmp_root / f"t242_fixture_{uuid4().hex}.db"
        c = sqlite3.connect(cls.db)
        schema.create(c, list(schema.TABLES))
        c.executescript(kpi_mod.SCHEMA + transcripts.SCHEMA)
        c.execute(schema.FTS)
        # obs_fact is built by the loader from the store's own columns; the fixture declares the ones the lookups use
        c.execute("CREATE TABLE obs_fact (observation_id INTEGER, symbol TEXT, measure TEXT, record_type TEXT, "
                  "status TEXT, period TEXT, period_source TEXT, basis TEXT, basis_source TEXT, printed_label TEXT, "
                  "statement TEXT, speaker TEXT, direction TEXT, question_context TEXT, segment TEXT, geography TEXT, "
                  "customer TEXT, entity_scope TEXT, series_title TEXT, value REAL, value_high REAL, unit TEXT, "
                  "scale REAL, doc_key TEXT, page INTEGER, source TEXT, doc_type TEXT, known_at TEXT, "
                  "check_status TEXT, checker TEXT, check_evidence TEXT, check_fields TEXT)")
        c.execute("CREATE TABLE row_check (tbl TEXT, row_id INTEGER, symbol TEXT, metric TEXT, canon TEXT, "
                  "sector TEXT, doc_type TEXT, rule TEXT, status TEXT, corroborated INTEGER, checker TEXT)")
        c.execute("CREATE TABLE row_check_fail (tbl TEXT, row_id INTEGER, check_name TEXT, hard INTEGER, why TEXT)")
        c.execute("INSERT INTO company VALUES (?,?,NULL,NULL,'t','532714','Test Company Limited')", (SYM, ISIN))
        c.executemany(f"INSERT INTO doc VALUES ({','.join('?' * 12)})", [
            ("calls/may.pdf", SYM, ISIN, "transcript", "transcript", "Transcript of call held on 19 May 2026",
             "2026-05-27", "2026-05-27T12:00:00", 1, None, "sandbox", "may"),
            ("calls/nov.pdf", SYM, ISIN, "transcript", "transcript", "Transcript of call held on 6 November 2026",
             "2026-11-14", "2026-11-14T12:00:00", 1, None, "sandbox", "nov"),
            ("decks/q2.pdf", SYM, ISIN, "deck", "deck", "Investor Presentation", "2026-10-29",
             "2026-10-29T17:00:00", 1, None, "pages.db", "q2"),
        ])
        c.executemany(f"INSERT INTO doc_page VALUES ({','.join('?' * 8)})", [
            ("calls/may.pdf", SYM, 1, "Cash and cash equivalents were discussed on the call.", "script_text", 54,
             "2026-05-27T12:00:00", None),
            ("calls/nov.pdf", SYM, 1, "Cash position was discussed on the November call.", "script_text", 54,
             "2026-11-14T12:00:00", None)])
        c.execute("INSERT INTO doc_page_fts(rowid, text) SELECT rowid, text FROM doc_page")

        def add(table: str, **kw) -> None:
            cols = {r[1] for r in c.execute(f"PRAGMA table_info({table})")}
            kept = {k: v for k, v in kw.items() if k in cols}
            c.execute(f"INSERT INTO {table} ({','.join(kept)}) VALUES ({','.join(['?'] * len(kept))})",
                      list(kept.values()))

        # two verifiable numbers carrying the same printed label 'liquid cash' and its NEW: code (T-242 step 2/3)
        add("obs_fact", symbol=SYM, measure="NEW:net_liquid_cash", record_type="number", status="verified",
            period="September 30, 2026", printed_label="net liquid cash", value=630.0, unit="INR million", scale=1,
            doc_type="deck", doc_key="decks/q2.pdf", page=8, known_at="2026-10-29T17:00:00", observation_id=1)
        add("obs_fact", symbol=SYM, measure="cash_and_cash_equivalents", record_type="number", status="verified",
            period="September 30, 2026", printed_label="liquid cash", value=1190.0, unit="INR million", scale=1,
            doc_type="deck", doc_key="decks/q2.pdf", page=8, known_at="2026-10-29T17:00:00", observation_id=2)
        # two calls: the newer one is held 2026-11-14, the named one 2026-05-27 (T-242 step 1)
        add("obs_fact", symbol=SYM, measure="cash", record_type="statement", status="verified",
            statement="So the cash and cash equivalents stood at INR 1,200 crores at the end of May.",
            speaker="May Speaker", doc_type="transcript", doc_key="calls/may.pdf", page=1,
            known_at="2026-05-27T12:00:00", observation_id=3)
        add("obs_fact", symbol=SYM, measure="cash", record_type="statement", status="verified",
            statement="In November we discussed cash and treasury planning for the year ahead.",
            speaker="November Speaker", doc_type="transcript", doc_key="calls/nov.pdf", page=1,
            known_at="2026-11-14T12:00:00", observation_id=4)
        # the same sentence in transcript_statement holds the speaker; the obs row above has none for that quote
        add("transcript_statement", symbol=SYM, doc_key="calls/may.pdf", call_date="2026-05-19", call_period="Q4FY26",
            page=1, speaker="May Speaker", role="cfo", section="", topics="cash",
            quote="So the cash and cash equivalents stood at INR 1,200 crores at the end of May.",
            statement="So the cash and cash equivalents stood at INR 1,200 crores at the end of May.",
            is_fragment=0,
            answer_turn=1, seq=1, known_at="2026-05-27T12:00:00", entities="", period_discussed="",
            numbers_json="[]", extractor_rule="t")
        # one full-year capex target and its balance-of-year restatement, from the same call (T-242 step 4)
        c.executemany(
            "INSERT INTO guidance(symbol,isin,metric,target_period,low,high,unit,direction,said_on,doc_key,page,"
            "quote,speaker,known_at,known_at_source,revision_of,extractor_rule) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", [
                (SYM, ISIN, "capex", "FY27", 80.0, 80.0, "inr_cr", "flat", "2026-09-11", "calls/nov.pdf", 3,
                 "So, what we are targeting is that we will spend around INR80 crores in capex in the current year.",
                 "May Speaker", "2026-09-11T13:38:03", "doc.known_at", None, "t"),
                (SYM, ISIN, "capex", "FY27", 75.0, 75.0, "inr_cr", "flat", "2026-09-11", "calls/nov.pdf", 3,
                 "Out of the INR80 crores, INR5 crores was spent in the first quarter and the balance INR75 crores, "
                 "we are targeting the next three quarters.",
                 "May Speaker", "2026-09-11T13:38:03", "doc.known_at", None, "t")])
        c.commit()
        c.close()
        cls._old = p3.db_path.__module__ and __import__("os").environ.get("REALITY_PILOT3_DB")
        __import__("os").environ["REALITY_PILOT3_DB"] = str(cls.db)
        p3.reset_store()

    @classmethod
    def tearDownClass(cls) -> None:
        import os
        if cls._old is None:
            os.environ.pop("REALITY_PILOT3_DB", None)
        else:
            os.environ["REALITY_PILOT3_DB"] = cls._old
        p3.close()
        p3.reset_store()
        for suffix in ("", "-wal", "-shm"):
            Path(str(cls.db) + suffix).unlink(missing_ok=True)

    def test_named_call_ranks_first(self) -> None:
        asked = "In the 2026-05-27 call, what did management say about cash and cash equivalents?"
        named = p3.statements(SYM, topic="cash and cash equivalents", rank_terms=asked)
        self.assertTrue(named["found"])
        self.assertEqual(named["rows"][0]["call_date"], "2026-05-27")
        # no date asked: the newest call stays first
        newest = p3.statements(SYM, topic="cash and cash equivalents")
        self.assertEqual(newest["rows"][0]["call_date"], "2026-11-14")
        dated = p3.statements(SYM, topic="cash", date_from="2026-05-27", date_to="2026-05-27")
        self.assertEqual(dated["rows"][0]["call_date"], "2026-05-27")

    def test_speaker_filled_from_the_transcript_row(self) -> None:
        named = p3.statements(SYM, topic="cash and cash equivalents", rank_terms="In the 2026-05-27 call")
        self.assertEqual(named["rows"][0]["speaker"], "May Speaker")

    def test_natural_date_period_and_label(self) -> None:
        reply = p3.fact(SYM, "liquid cash", period="September 30, 2026")
        self.assertTrue(reply["found"], reply)
        self.assertEqual(reply["answer"]["value"], 1190.0)
        self.assertEqual(reply["answer"]["unit"], "INR million")
        self.assertEqual(reply["answer"]["period"], "September 30, 2026")

    def test_guidance_elects_the_full_year_target(self) -> None:
        reply = p3.guidance(SYM, metric="capex", period="FY27")
        self.assertTrue(reply["found"])
        self.assertEqual(reply["rows"][0]["low"], 80.0)
        self.assertEqual([a["low"] for a in reply["alternatives"]], [75.0])

    def test_retail_deposits_is_not_a_shareholding_question(self) -> None:
        self.assertNotEqual(p3._fact_route("retail_deposits", SYM)[0], "holding")
        self.assertEqual(p3._fact_route("promoter_holding", SYM)[0], "holding")
        self.assertEqual(p3._fact_route("retail_shareholders", SYM)[0], "holding")


if __name__ == "__main__":
    unittest.main()
