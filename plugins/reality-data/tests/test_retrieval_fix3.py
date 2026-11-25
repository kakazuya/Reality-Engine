"""T-242 retrieval fix 3: within-call statement ranking, the 25-statement window on one named call, and a printed
label that is a token subset of its ``NEW:`` measure code, on a tiny pilot3 store built in a temp directory.

    python -m unittest plugins/reality-data/tests/test_retrieval_fix3.py
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
CALL = "calls/may.pdf"
CALL_DAY = "2026-05-27"
ASKED = "Our ebitda margin expanded by 120 bps on a better mix this quarter, and we expect it to hold."


class RetrievalFix3Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        tmp_root = ROOT / ".tmp"
        tmp_root.mkdir(exist_ok=True)
        cls.db = tmp_root / f"t242_fix3_{uuid4().hex}.db"
        c = sqlite3.connect(cls.db)
        schema.create(c, list(schema.TABLES))
        c.executescript(kpi_mod.SCHEMA + transcripts.SCHEMA)
        c.execute(schema.FTS)
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
        c.execute(f"INSERT INTO doc VALUES ({','.join('?' * 12)})",
                  (CALL, SYM, ISIN, "transcript", "transcript", "Transcript of call held on 27 May 2026",
                   CALL_DAY, f"{CALL_DAY}T12:00:00", 1, None, "sandbox", "may"))
        c.commit()

        def add(table: str, **kw) -> None:
            cols = {r[1] for r in c.execute(f"PRAGMA table_info({table})")}
            kept = {k: v for k, v in kw.items() if k in cols}
            c.execute(f"INSERT INTO {table} ({','.join(kept)}) VALUES ({','.join(['?', ] * len(kept))})",
                      list(kept.values()))

        # 12 remarks in ONE call (the window and ranking tests); the asked remark is the OLDEST row, so before
        # fix 3 it arrived last and, past the 10-statement window, sometimes not at all.
        for i in range(1, 13):
            asked = f"{i:02d}" == "07"
            add("obs_fact", symbol=SYM, record_type="statement", status="verified", doc_type="transcript",
                measure="ebitda_margin" if asked else "margin_comment", doc_key=CALL, page=4, speaker="Speaker",
                statement=ASKED if asked else f"Remark {i:02d}: the margin held at the guided level this quarter.",
                known_at=f"{CALL_DAY}T09:00:00" if asked else f"{CALL_DAY}T12:00:00", observation_id=100 + i)
        # ADFFOODS-style printed labels whose measures append movement tokens (T-242 fix 3 step 3)
        add("obs_fact", symbol=SYM, measure="NEW:water_withdrawal_reduction_yoy", record_type="number",
            status="verified", period="FY26", printed_label="Water withdrawal", value=7.17, unit="%", scale=1,
            doc_type="deck", doc_key="decks/esg.pdf", page=46, known_at="2026-06-30T12:00:00", observation_id=1)
        add("obs_fact", symbol=SYM, measure="NEW:third_party_water_dependence_reduction_yoy", record_type="number",
            status="verified", period="FY26", printed_label="Dependence on third-party water", value=67.0, unit="%",
            scale=1, doc_type="deck", doc_key="decks/esg.pdf", page=46, known_at="2026-06-30T12:00:00",
            observation_id=2)
        c.commit()
        c.close()
        import os
        cls._old = os.environ.get("REALITY_PILOT3_DB")
        os.environ["REALITY_PILOT3_DB"] = str(cls.db)
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

    def test_the_asked_remark_of_the_named_call_comes_first(self) -> None:
        out = p3.statements(SYM, topic="ebitda margin", date_from=CALL_DAY, date_to=CALL_DAY)
        self.assertTrue(out["found"], out)
        self.assertEqual(out["rows"][0]["quote"], ASKED)
        # nothing worse when the words arrive in rank_terms only
        via_rank = p3.statements(SYM, rank_terms="ebitda margin", date_from=CALL_DAY, date_to=CALL_DAY)
        self.assertEqual(via_rank["rows"][0]["quote"], ASKED)

    def test_one_named_call_serves_25_remarks_and_other_questions_keep_10(self) -> None:
        named = p3.statements(SYM, topic="margin", date_from=CALL_DAY, date_to=CALL_DAY)
        self.assertEqual(named["n"], 12)
        self.assertEqual(named["coverage"]["cut"], 0)
        other = p3.statements(SYM, topic="margin")
        self.assertEqual(other["n"], 10)

    def test_printed_label_reaches_a_movement_measure(self) -> None:
        water = p3.fact(SYM, "Water withdrawal", period="FY26")
        self.assertTrue(water["found"], water)
        self.assertEqual(water["answer"]["value"], 7.17)
        dependence = p3.fact(SYM, "Dependence on third-party water", period="FY26")
        self.assertTrue(dependence["found"], dependence)
        self.assertEqual(dependence["answer"]["value"], 67.0)

    def test_the_one_named_call_sentence_is_in_the_tool_description(self) -> None:
        doc = " ".join((p3.statements.__doc__ or "").split())
        self.assertIn("pass that call's date as ``date_from`` and ``date_to`` (both YYYY-MM-DD)", doc)


if __name__ == "__main__":
    unittest.main()
