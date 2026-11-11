"""T-181: the document-integrity report and gate on a tiny fixture (no network, no real store)."""
from __future__ import annotations

import csv
import sqlite3
import tempfile
from pathlib import Path

import pytest

from reality_engine.pilot3 import doc_integrity as di
from reality_engine.pilot3 import schema

# (doc_key, symbol, doc_type, filing_date, known_at, pages, sha256, [page texts])
DOCS = [
    # link_notice: a 1-page transcript that is a covering letter, not the call.
    ("LN", "AAA", "transcript", "2026-01-10", "2026-01-10T10:00:00", 1, "sha-ln",
     ["Sub: Transcript of Earnings Call\nPlease find enclosed the transcript at https://example.test/call.pdf"]),
    # duplicate_sha256: the same sha256 under another company (near_duplicate needs the same symbol).
    ("DUP1", "AAA", "announcement", "2026-01-01", "2026-01-01T10:00:00", 1, "sha-dup", ["notice one"]),
    ("DUP2", "BBB", "announcement", "2026-01-02", "2026-01-02T10:00:00", 1, "sha-dup", ["notice two"]),
    # near_duplicate: same symbol, type, page count and first page under a different sha256.
    ("NEAR1", "AAA", "announcement", "2026-02-01", "2026-02-01T10:00:00", 1, "sha-near1",
     ["This is the same covering letter text repeated verbatim for the near-duplicate fixture."]),
    ("NEAR2", "AAA", "announcement", "2026-02-01", "2026-02-02T10:00:00", 1, "sha-near2",
     ["This is the same covering letter text repeated verbatim for the near-duplicate fixture."]),
    # misdated: a 2018 call stored as filed in 2026 (the 9m rule: latest printed year more than a year before).
    ("MIS", "AAA", "transcript", "2026-08-29", "2026-08-29T10:00:00", 3, "sha-mis",
     ["Transcript of the earnings conference call held on July 27, 2018", "Moderator: good morning", "Q&A"]),
    # mistyped: a call transcript (moderator line) typed announcement.
    ("MISTYPED", "AAA", "announcement", "2026-06-01", "2026-06-01T10:00:00", 3, "sha-typed",
     ["Earnings call transcript", "Moderator: Ladies and gentlemen, good day", "Q&A"]),
    # truncated: an annual report held as 2 pages.
    ("TRUNC", "AAA", "annual_report", "2026-07-01", "2026-07-01T10:00:00", 2, "sha-trunc",
     ["Annual Report 2025-26", "Contents"]),
    # no_text: neither page has a text layer (filed before RESULTS_FROM so no missing-call row).
    ("NOTEXT", "AAA", "results", "2023-01-05", "2023-01-05T10:00:00", 2, "sha-notext", ["", ""]),
    # known_at_after_period: reloaded 61 days after the filing.
    ("LATE", "AAA", "press_release", "2026-03-01", "2026-05-01T10:00:00", 1, "sha-late",
     ["Press release: the company announces its results."]),
    # missing_period_call: a results filing with no transcript of the symbol within 45 days.
    ("MC", "ZZZ", "results", "2026-05-01", "2026-05-01T10:00:00", 2, "sha-mc",
     ["Financial results for the quarter ended March 31, 2026", "Balance sheet"]),
]


@pytest.fixture()
def store_dir() -> Path:
    """A writable folder for the fixture and the report output.

    A fresh ``mkdtemp`` is used when it is writable; under a file sandbox that denies writes into a new
    subfolder the session's own ``.tmp`` is used instead.  No test writes outside this folder.
    """
    candidate = Path(tempfile.mkdtemp(prefix="t181-"))
    try:
        (candidate / "probe").write_text("x", encoding="utf-8")
        return candidate
    except OSError:
        fallback = Path.cwd() / ".tmp"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


def _fixture(path: Path) -> Path:
    con = sqlite3.connect(path)
    try:
        schema.create(con, ("doc", "doc_page"))
        for doc_key, symbol, doc_type, filing, known, pages, sha, texts in DOCS:
            con.execute("INSERT INTO doc (doc_key, symbol, doc_type, filing_date, known_at, pages, sha256) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)", (doc_key, symbol, doc_type, filing, known, pages, sha))
            for page, text in enumerate(texts, 1):
                con.execute("INSERT INTO doc_page (doc_key, symbol, page, text, chars, known_at) "
                            "VALUES (?, ?, ?, ?, ?, ?)", (doc_key, symbol, page, text, len(text), known))
        con.commit()
    finally:
        con.close()
    return path


def _counts(store: Path) -> dict[str, int]:
    con = di.connect_ro(store)
    try:
        return {row["defect"]: row["documents"] for row in di.summarize(di.scan(con))}
    finally:
        con.close()


def test_every_defect_class_is_counted_once(store_dir):
    store = _fixture(store_dir / "fixture.db")
    assert _counts(store) == {defect: 1 for defect in di.DEFECTS}


def test_report_writes_both_csvs(store_dir):
    store = _fixture(store_dir / "fixture.db")
    assert di.main(["report", "--store", str(store), "--out", str(store_dir)]) == 0
    rows = list(csv.DictReader((store_dir / "doc_defects.csv").open(encoding="utf-8")))
    assert {row["defect"] for row in rows} == set(di.DEFECTS)
    assert all(row["doc_key"] and row["detail"] for row in rows)
    summary = list(csv.DictReader((store_dir / "summary.csv").open(encoding="utf-8")))
    assert [row["defect"] for row in summary] == list(di.DEFECTS)


def test_gate_prev_exits_1_on_a_rise_and_0_on_a_match(store_dir):
    store = _fixture(store_dir / "fixture.db")
    assert di.main(["report", "--store", str(store), "--out", str(store_dir)]) == 0
    current = di.read_summary(store_dir / "summary.csv")
    assert current["link_notice"] == 1
    previous = store_dir / "previous.csv"
    with previous.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=di.SUMMARY_COLUMNS)
        writer.writeheader()
        writer.writerows({"defect": defect, "documents": 0 if defect == "link_notice" else current[defect],
                          "companies": 0} for defect in di.DEFECTS)
    assert di.main(["gate", "--prev", str(previous), "--new", str(store_dir / "summary.csv")]) == 1
    assert di.main(["gate", "--prev", str(store_dir / "summary.csv"),
                    "--new", str(store_dir / "summary.csv")]) == 0


def test_gate_store_exits_1_over_a_limit_and_0_within_it(store_dir):
    store = _fixture(store_dir / "fixture.db")
    assert di.main(["gate", "--store", str(store), "--max", "link_notice=0"]) == 1
    assert di.main(["gate", "--store", str(store), "--max", "link_notice=1,misdated=1"]) == 0
