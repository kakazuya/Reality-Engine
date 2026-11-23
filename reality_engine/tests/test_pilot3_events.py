"""T-194: the ``event`` table one row per announcement event -- inspection, buyback, dividend, acquisition, merger.

Run from the repo root:
    python -m pytest reality_engine/tests/test_pilot3_events.py -q

The store is built under ``.tmp/`` from the real DDL: no production database, network or model.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from reality_engine.pilot3 import schema
from reality_engine.pilot3.events import build_events, event_dates

TMP = Path(__file__).resolve().parents[2] / ".tmp"
DB = TMP / "pilot3_events_test.db"


def _store() -> sqlite3.Connection:
    TMP.mkdir(exist_ok=True)
    for suffix in ("", "-wal", "-shm"):
        Path(str(DB) + suffix).unlink(missing_ok=True)
    con = sqlite3.connect(DB)
    schema.create(con, ("doc", "doc_page"))
    docs = [
        ("aurobindo:insp.pdf", "AURO", "INE1", "announcement", "announcement",
         "Submission of Press Release on USFDA inspection at Unit VII", "2026-05-20", "2026-05-20T18:00:00"),
        ("aurobindo:div.pdf", "AURO", "INE1", "announcement", "announcement",
         "Intimation of declaration of interim dividend for FY 2026-27", "2026-11-04", "2026-11-04T20:16:01"),
        ("aurobindo:merger.pdf", "AURO", "INE1", "press_release", "press_release",
         "Approved the proposal of Merger of two wholly owned subsidiaries", "2026-11-04", "2026-11-04T20:28:24"),
        ("aurobindo:buyback.pdf", "AURO", "INE1", "announcement", "announcement",
         "Buyback of equity shares", "2026-06-01", "2026-06-01T12:00:00"),
        ("aurobindo:meet.pdf", "AURO", "INE1", "announcement", "announcement",
         "Intimation of investors / analysts meet to be held on 17.11.2026", "2026-11-09", "2026-11-09T14:39:51"),
        ("aurobindo:results.pdf", "AURO", "INE1", "results", "results",
         "Dividend and results update", "2026-11-04", "2026-11-04T19:00:00"),
    ]
    con.executemany("INSERT INTO doc VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    [(*row, 2, None, "sandbox", row[0]) for row in docs])
    con.execute("INSERT INTO doc_page VALUES ('aurobindo:insp.pdf','AURO',1,"
                "'The USFDA inspection of our Unit VII facility from 11th to 15th May 2026 concluded with a Form 483 "
                "containing two observations.','script_text',150,'2026-05-20T18:00:00',NULL)")
    con.execute("INSERT INTO doc_page VALUES ('aurobindo:div.pdf','AURO',1,"
                "'The Board declared an interim dividend of Rs 2 per share for FY 2026-27.','script_text',80,"
                "'2026-11-04T20:16:01',NULL)")
    con.commit()
    return con


def test_one_row_per_event_from_title_and_first_page():
    con = _store()
    stats = build_events(con)
    assert stats["rows"] == 4                                  # the analyst-meet and the results doc are not events
    assert stats["by_kind"] == {"inspection": 1, "dividend": 1, "merger": 1, "buyback": 1}
    got = {row[0]: row for row in con.execute(
        "SELECT kind, event_date, end_date, announced, unit, outcome, known_at, doc_key FROM event")}
    insp = got["inspection"]
    assert insp[1:6] == ("2026-05-11", "2026-05-15", "2026-05-20", "Unit VII", "Form 483")
    assert insp[6] == "2026-05-20T18:00:00" and insp[7] == "aurobindo:insp.pdf"
    assert got["dividend"][1] == "2026-11-04"                  # no date in the text: the filing date
    assert got["merger"][3] == "2026-11-04"                    # title-only announcement still gets its event
    con.close()


def test_the_build_is_idempotent():
    con = _store()
    build_events(con)
    build_events(con)
    assert con.execute("SELECT COUNT(*) FROM event").fetchone()[0] == 4
    con.close()


def test_event_dates_reads_the_range_management_prints():
    assert event_dates("inspection from 11th to 15th May 2026 at Unit VII") == ("2026-05-11", "2026-05-15")
    assert event_dates("inspected during March 3-7, 2026") == ("2026-03-03", "2026-03-07")
    assert event_dates("a single visit on 4 February 2026") == ("2026-02-04", "2026-02-04")
    assert event_dates("no date printed") == (None, None)


def test_an_event_carries_its_document_and_the_sentences_that_answer_it():
    """T-197: an event row names its document type and title and carries the filing sentences that state the
    outcome, observations or amount -- the title alone is not the answer."""
    con = _store()
    build_events(con)
    doc_type, title, body = con.execute(
        "SELECT doc_type, title, body_excerpt FROM event WHERE kind='inspection'").fetchone()
    assert doc_type == "announcement"
    assert "USFDA inspection" in title
    assert "Form 483" in body and "observations" in body
    con.close()


def test_body_excerpt_keeps_the_cue_sentences_not_just_the_first():
    from reality_engine.pilot3.events import body_excerpt

    text = ("The Board of Directors met today. The board approved an interim dividend of Rs 2 per share and fixed "
            "the record date as 18 November 2026.")
    got = body_excerpt(text)
    assert got
    assert "approved an interim dividend" in got and "record date" in got
    assert not got.startswith("The Board of Directors met")
    assert len(body_excerpt("x. " * 2000) or "") <= 600


def test_a_store_built_before_t197_gains_the_body_columns_and_fills_them():
    con = _store()
    con.execute("CREATE TABLE event (symbol TEXT, isin TEXT, kind TEXT, event_date TEXT, end_date TEXT, "
                "announced TEXT, unit TEXT, outcome TEXT, subject TEXT, doc_key TEXT, page INTEGER, quote TEXT, "
                "known_at TEXT, known_at_source TEXT, source TEXT, extractor_rule TEXT)")
    build_events(con)
    columns = {row[1] for row in con.execute("PRAGMA table_info(event)")}
    assert {"doc_type", "title", "body_excerpt"} <= columns
    rows = con.execute("SELECT doc_type, title, body_excerpt FROM event").fetchall()
    assert rows and all(row[0] and row[1] for row in rows)      # every event names its document
    assert any(row[2] for row in rows)                          # and the ones with held page text carry it
    merged = con.execute("SELECT body_excerpt FROM event WHERE kind='merger'").fetchone()[0]
    assert merged is None                                       # no page text held: no invented excerpt
    con.close()
