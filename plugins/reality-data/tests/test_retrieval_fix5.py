"""T-242 retrieval fix 5: a named call is served from the documents its PRINTED call date puts within 3 days, not
only from the documents a filing-date window catches -- a call held on 2026-11-03 and filed 2026-11-10 keeps its
``obs_fact`` statements and its ``doc_page`` hits when asked by either date, and still serves no other call's row.

    python -m pytest -q plugins/reality-data/tests/test_retrieval_fix5.py

Written as pytest functions on purpose: ``python -m unittest`` does not collect them.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest

ROOT = Path(__file__).resolve().parents[3]
SERVER_DIR = Path(__file__).resolve().parents[1] / "server"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SERVER_DIR))

import lookups_pilot3 as p3  # noqa: E402
from reality_engine.pilot3 import kpi as kpi_mod, schema, transcripts  # noqa: E402

SYM = "TST"
ISIN = "INE000000001"
CALL, FILED = "2026-11-03", "2026-11-10"      # held 3 Nov, filed 10 Nov: 7 days apart, outside the +-3 window
OLD_CALL, OLD_FILED = "2026-08-14", "2026-08-19"
CALL_DOC, OLD_DOC = "calls/nov.pdf", "calls/aug.pdf"
OBS_ONLY = "OBSERVED-ONLY: distribution volumes grew on the new terminal and the margin held at the guided level."
AUGUST_ONLY = "AUGUST-ONLY remark: the margin of the August call held at a different level."
PAGE_ONLY = "PAGE-ONLY: the margin expanded as distribution volumes grew through the September quarter."


@pytest.fixture(scope="module")
def store() -> Iterator[Path]:
    tmp_root = ROOT / ".tmp"
    tmp_root.mkdir(exist_ok=True)
    db = tmp_root / f"t242_fix5_{uuid4().hex}.db"
    c = sqlite3.connect(db)
    schema.create(c, list(schema.TABLES))
    c.executescript(kpi_mod.SCHEMA + transcripts.SCHEMA)
    c.execute(schema.FTS)
    c.execute("CREATE TABLE obs_fact (observation_id INTEGER, symbol TEXT, measure TEXT, record_type TEXT, "
              "status TEXT, period TEXT, period_source TEXT, basis TEXT, basis_source TEXT, printed_label TEXT, "
              "statement TEXT, speaker TEXT, direction TEXT, question_context TEXT, segment TEXT, geography TEXT, "
              "customer TEXT, entity_scope TEXT, series_title TEXT, value REAL, value_high REAL, unit TEXT, "
              "scale REAL, doc_key TEXT, page INTEGER, source TEXT, doc_type TEXT, known_at TEXT, "
              "check_status TEXT, checker TEXT, check_evidence TEXT, check_fields TEXT)")
    c.execute("INSERT INTO company VALUES (?,?,NULL,NULL,'t','532714','Test Company Limited')", (SYM, ISIN))
    c.executemany(f"INSERT INTO doc VALUES ({','.join('?' * 12)})", [
        (CALL_DOC, SYM, ISIN, "transcript", "transcript", "Transcript of call held on 3 November 2026",
         FILED, f"{FILED}T12:00:00", 20, None, "sandbox", "nov"),
        (OLD_DOC, SYM, ISIN, "transcript", "transcript", "Transcript of call held on 14 August 2026",
         OLD_FILED, f"{OLD_FILED}T12:00:00", 15, None, "sandbox", "aug")])

    def add(table: str, **kw) -> None:
        cols = {r[1] for r in c.execute(f"PRAGMA table_info({table})")}
        kept = {k: v for k, v in kw.items() if k in cols}
        c.execute(f"INSERT INTO {table} ({','.join(kept)}) VALUES ({','.join(['?'] * len(kept))})",
                  list(kept.values()))

    # the November call prints its held date (2026-11-03) on transcript_statement rows; it was filed a week later
    for i in range(1, 3):
        add("transcript_statement", symbol=SYM, doc_key=CALL_DOC, call_date=CALL, call_period="Q2FY27",
            page=3, speaker="November Speaker", role="cfo", section="qa", topics="margin",
            quote=f"November remark {i:02d}: the margin held at the guided level.",
            statement=f"November remark {i:02d}: the margin held at the guided level.",
            is_fragment=0, answer_turn=i, seq=i, known_at=f"{FILED}T12:00:00", entities="",
            period_discussed="Q2FY27", numbers_json="[]", extractor_rule="t")
    # the August call: another document, printed and filed 3 months before the call asked about
    add("transcript_statement", symbol=SYM, doc_key=OLD_DOC, call_date=OLD_CALL, call_period="Q1FY27",
        page=2, speaker="August Speaker", role="ceo", section="qa", topics="margin",
        quote=AUGUST_ONLY, statement=AUGUST_ONLY, is_fragment=0, answer_turn=1, seq=1,
        known_at=f"{OLD_FILED}T12:00:00", entities="", period_discussed="Q1FY27", numbers_json="[]",
        extractor_rule="t")
    # the obs_fact statement of each call: the November one is the sentence the ask locates, and it is NOT one of
    # the transcript_statement rows -- before fix 5 the filing-date window dropped it from both named dates.
    add("obs_fact", symbol=SYM, measure="margin", record_type="statement", status="verified", doc_type="transcript",
        doc_key=CALL_DOC, page=3, speaker="November Speaker", statement=OBS_ONLY,
        known_at=f"{FILED}T12:00:00", observation_id=1)
    add("obs_fact", symbol=SYM, measure="margin", record_type="statement", status="verified", doc_type="transcript",
        doc_key=OLD_DOC, page=2, speaker="August Speaker", statement=AUGUST_ONLY,
        known_at=f"{OLD_FILED}T12:00:00", observation_id=2)
    # page text: the call's own page holds the asked words, the other call's page must never be served
    add("doc_page", doc_key=CALL_DOC, symbol=SYM, page=5, text=PAGE_ONLY, method="text", chars=len(PAGE_ONLY),
        known_at=f"{FILED}T12:00:00")
    add("doc_page", doc_key=OLD_DOC, symbol=SYM, page=7, text=f"{AUGUST_ONLY} The margin is discussed here.",
        method="text", chars=120, known_at=f"{OLD_FILED}T12:00:00")
    c.commit()
    c.execute("INSERT INTO doc_page_fts(doc_page_fts) VALUES ('rebuild')")
    c.commit()
    c.close()
    old = os.environ.get("REALITY_PILOT3_DB")
    os.environ["REALITY_PILOT3_DB"] = str(db)
    p3.reset_store()
    yield db
    p3.close()
    p3.reset_store()
    if old is None:
        os.environ.pop("REALITY_PILOT3_DB", None)
    else:
        os.environ["REALITY_PILOT3_DB"] = old
    for suffix in ("", "-wal", "-shm"):
        Path(str(db) + suffix).unlink(missing_ok=True)


def _quotes(reply: dict) -> list[str]:
    return [str(row.get("quote") or "") for row in reply.get("rows") or []]


def _reply_bytes(reply: dict) -> int:
    return len(json.dumps(reply, ensure_ascii=False, default=str).encode("utf-8"))


def test_the_named_call_owns_its_documents_by_printed_call_date(store: Path) -> None:
    docs = p3._named_call_docs(SYM, CALL)
    assert CALL_DOC in docs, docs
    assert OLD_DOC not in docs, docs
    # both dates name the same call: the printed call date and the filing date 7 days later
    assert docs == p3._named_call_docs(SYM, FILED), docs


def test_a_call_filed_7_days_later_keeps_its_obs_statement_by_either_date(store: Path) -> None:
    for named in (CALL, FILED):
        reply = p3.statements(SYM, topic="margin", date_from=named, date_to=named)
        assert reply["found"], (named, reply)
        rows = reply.get("rows") or []
        quotes = _quotes(reply)
        assert any(OBS_ONLY[:40] in quote for quote in quotes), (named, quotes)
        assert any(row.get("match") == "obs" for row in rows), (named, rows)
        # no row of the other call, by statement or by page text
        assert all("AUGUST-ONLY" not in quote for quote in quotes), (named, quotes)
        outside = reply["coverage"].get("outside_date_filter") or []
        assert any(row["date"] == OLD_CALL for row in outside), (named, outside)
        # fix 3/4 stay: at most 25 rows, whole, under the 19 kB reply cap
        assert len(rows) <= 25, (named, len(rows))
        assert reply["coverage"].get("rows_cut") is None, (named, reply["coverage"])
        assert _reply_bytes(reply) < 19_000, (named, _reply_bytes(reply))


def test_a_call_filed_7_days_later_keeps_its_doc_page_hit(store: Path) -> None:
    for named in (CALL, FILED):
        reply = p3.statements(SYM, topic="margin", date_from=named, date_to=named)
        page_rows = [row for row in reply.get("rows") or [] if row.get("match") == "text"]
        assert any("PAGE-ONLY" in str(row.get("quote") or "") for row in page_rows), (named, page_rows)
        assert all("AUGUST-ONLY" not in str(row.get("quote") or "") for row in page_rows), (named, page_rows)
