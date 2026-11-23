"""The fast extractor check (T-049): fixed pages re-extracted from the stored text, found / missing in seconds.

The checked-in fixture is written by ``python -m reality_engine.pilot3.checkpages make`` from the graded
answers; its ``baseline`` is what the current code found when the fixture was generated.  The baseline test is
skipped where the live database or the raw PDFs it reads are not on the machine."""
from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path

import pytest

from reality_engine.pilot3 import REAL_DB, checkpages, kpi

HERE = Path(__file__).resolve().parent
FIXTURE = HERE / "fixtures" / "pilot3_checkpages.json"
WORK = HERE.parents[1] / ".tmp"          # pytest's tmp_path (mode 0o700) is unusable in the DSH sandbox


def _work(name: str) -> Path:
    folder = WORK / f"checkpages_{name}_{uuid.uuid4().hex[:8]}"
    folder.mkdir(parents=True)
    return folder


def test_a_quote_maps_to_every_page_that_holds_it_and_nowhere_else():
    folder = _work("map")
    db = folder / "pages.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE doc_page(symbol TEXT, doc_key TEXT, page INTEGER, text TEXT)")
    con.executemany("INSERT INTO doc_page VALUES (?,?,?,?)", [
        ("KEC", "a.pdf", 1, "with EBITDA increasing 10% to ` 1,659 Crore"),
        ("KEC", "a.pdf", 2, "Revenue 23,506 crore"),
        ("KEC", "b.pdf", 7, "EBITDA increasing 10% to ` 1,659 Crores"),
    ])
    con.commit()
    con.close()
    con = sqlite3.connect(db)
    blob, where, starts = checkpages.pages_blob(con, "KEC")
    assert checkpages.quote_pages("EBITDA increasing 10% to ` 1,659 Crore", blob, where, starts) == \
        {("a.pdf", 1), ("b.pdf", 7)}
    assert checkpages.quote_pages("not on any page", blob, where, starts) == set()
    con.close()


def test_value_found_checks_the_unit_and_allows_a_guidance_range():
    entry = {"value": 6722.0, "unit": "INR crore"}
    assert checkpages.value_found(entry, [(6722.0, 6722.0, "inr_cr")])
    assert checkpages.value_found({"value": 7.06, "unit": "percent"}, [(7.056, 7.056, "pct")])
    assert not checkpages.value_found(entry, [(6722.0, 6722.0, "pct")])           # right number, wrong unit
    assert not checkpages.value_found(entry, [(6700.0, 6700.0, "inr_cr")])        # outside 0.1%
    assert checkpages.value_found({"value": 12.5, "unit": "percent"}, [(11.0, 13.0, "pct")])


def test_run_finds_the_expected_number_on_a_synthetic_page():
    """End to end through ``run``: one stored page, one expected KPI, no live database."""
    folder = _work("run")
    db = folder / "tiny.db"
    con = sqlite3.connect(db)
    con.executescript(
        "CREATE TABLE doc(doc_key TEXT, symbol TEXT, doc_type TEXT, isin TEXT, title TEXT, filing_date TEXT,"
        " known_at TEXT, source_key TEXT, sha256 TEXT);"
        "CREATE TABLE doc_page(doc_key TEXT, page INTEGER, text TEXT, method TEXT);")
    con.execute("INSERT INTO doc VALUES ('deck/x.pdf','KEC','deck',NULL,'Q4 FY26','2026-05-16','2026-05-16',NULL,NULL)")
    con.executemany("INSERT INTO doc_page VALUES (?,?,?,?)", [
        ("deck/x.pdf", 1, "KEC International\nQ4 FY26 Results Presentation\n", "script_text"),
        ("deck/x.pdf", 2, "Net debt, including acceptances, stood at Rs 6,722 Crore\n", "script_text"),
    ])
    con.commit()
    con.close()
    fixture = folder / "fixture.json"
    fixture.write_text(json.dumps({"pages": [dict(
        symbol="KEC", qid="T1", doc_key="deck/x.pdf", page=2, value=6722.0, unit="INR crore",
        period="FY26", quote="Net debt, including acceptances, stood at", doc_type="deck")]}))
    result = checkpages.run(fixture=fixture, db=db, work=folder / "work", symbols=("KEC",))
    assert result["KEC"]["checked"] == 1 and result["KEC"]["found"] == 1, result["KEC"]["missing"]


@pytest.mark.skipif(not (FIXTURE.is_file() and REAL_DB.is_file() and kpi.RAW_ROOT.is_dir()),
                    reason="live pilot3 db, fixture or raw PDFs not on this machine")
def test_run_finds_at_least_the_recorded_baseline():
    baseline = json.loads(FIXTURE.read_text(encoding="utf-8"))["baseline"]
    result = checkpages.run(work=_work("baseline"))
    for symbol in ("KEC", "BAJFINANCE", "HINDALCO"):
        assert result[symbol]["checked"] == baseline[symbol]["checked"], symbol
        assert result[symbol]["found"] >= baseline[symbol]["found"], (symbol, result[symbol]["missing"])
    assert sum(r["found"] for r in result.values()) >= baseline["total"]["found"]
