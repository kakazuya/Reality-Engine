"""T-214/T-232: the measure runner's peak-RSS sampler, kill flags, CSV rows, deck manifest and part/doc-type
filters, on fake parts and a synthetic deck index only.

These tests never run a build or touch the network: a fake part is ``python -c`` that allocates a block or prints
lines, so the sampler, the RAM stop, the timeout and the ``parts.csv`` row are pinned without touching any store.
The deck manifest is built from a two-row ``deck_figures.db`` the test writes itself.

    python -m pytest reality_engine/tests/test_tg_measure_build.py -q
"""
from __future__ import annotations

import csv
import shutil
import sqlite3
import sys
from pathlib import Path

import pytest

from reality_engine.scripts import tg_measure_build as tg

ROOT = Path(__file__).resolve().parents[2]
TMP = ROOT / ".tmp" / "test_tg_measure_build"


@pytest.fixture()
def tmpdir():
    """A plain folder under ``.tmp/`` (pytest's own temp root is denied in the dsh sandbox)."""
    if TMP.exists():
        shutil.rmtree(TMP)
    TMP.mkdir(parents=True)
    yield TMP
    shutil.rmtree(TMP, ignore_errors=True)


def _fake(code: str) -> list[str]:
    return [sys.executable, "-c", code]


def test_peak_rss_sampler_sees_the_child_allocation(tmpdir):
    row = tg.run_step("fake", _fake("import time\nx = bytearray(60 * 1024 * 1024)\ntime.sleep(0.6)"),
                      tmpdir / "b_fake.log", interval_s=0.02, ram_gb=4.0, timeout_s=30)
    assert row["rc"] == 0
    assert row["seconds"] >= 0.5
    assert row["peak_rss_mb"] >= 40, row            # 60 MB on top of the interpreter
    assert row["ram_stop"] is False and row["timed_out"] is False
    assert row["tail5"] == ""


def test_ram_stop_kills_the_tree_and_sets_the_flag(tmpdir):
    row = tg.run_step("stores", _fake("import time\nx = bytearray(200 * 1024 * 1024)\ntime.sleep(10)"),
                      tmpdir / "b_stores.log", interval_s=0.02, ram_gb=0.05, timeout_s=30)
    assert row["ram_stop"] is True
    assert row["rc"] != 0
    assert row["seconds"] < 10


def test_timeout_kills_the_tree_and_sets_the_flag(tmpdir):
    row = tg.run_step("notes", _fake("import time\ntime.sleep(10)"), tmpdir / "b_notes.log",
                      interval_s=0.02, ram_gb=4.0, timeout_s=0.2)
    assert row["timed_out"] is True
    assert row["rc"] != 0
    assert row["seconds"] < 5


def test_parts_csv_row_on_a_fake_part(tmpdir):
    row = tg.run_step("registry", _fake("print('registry ok')"), tmpdir / "b_registry.log",
                      interval_s=0.02, ram_gb=4.0, timeout_s=30)
    row.update({"company": "c01", "symbol": "FAKE"})
    path = tmpdir / "parts.csv"
    tg.write_parts_csv([row], path)
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    assert len(rows) == 1
    assert tuple(rows[0]) == tg.PART_FIELDS
    assert rows[0]["company"] == "c01" and rows[0]["part"] == "registry" and rows[0]["rc"] == "0"
    assert float(rows[0]["seconds"]) > 0 and float(rows[0]["peak_rss_mb"]) > 0


def test_failed_part_keeps_the_last_five_log_lines(tmpdir):
    code = "print('\\n'.join('line%d' % i for i in range(1, 9)))\nraise SystemExit(3)"
    row = tg.run_step("checks", _fake(code), tmpdir / "b_checks.log",
                      interval_s=0.02, ram_gb=4.0, timeout_s=30)
    assert row["rc"] == 3
    assert row["tail5"].split(" | ") == ["line4", "line5", "line6", "line7", "line8"]


def test_measure_csv_writes_a_company_row(tmpdir):
    row: dict[str, object] = {field: "" for field in tg.MEASURE_FIELDS}
    row.update({"company": "c01", "symbol": "FAKE", "docs": 3, "pages": 9, "store_mb": 1.5})
    path = tmpdir / "pilot10_measure.csv"
    tg.write_measure_csv([row], path)
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    assert len(rows) == 1
    assert tuple(rows[0]) == tg.MEASURE_FIELDS
    assert rows[0]["company"] == "c01" and rows[0]["pages"] == "9"


# ---------------------------------------------------------------------------- T-232: parts and doc types
def test_parts_default_is_the_t214_recipe_and_a_subset_keeps_build_order():
    assert tg.selected_parts(None) == tg.PARTS and len(tg.PARTS) == 13
    assert tg.selected_parts("pages,registry") == ("registry", "pages")
    with pytest.raises(ValueError):
        tg.selected_parts("pages,bogus")
    assert tg.company_name(3, None) == "c03"        # the T-214 folder names
    assert tg.company_name(3, "deck") == "d003"     # the deck build's


def test_doc_type_filter_picks_only_the_named_manifest_buckets():
    from reality_engine.pilot3 import docs_collect as dc

    rows = [{"bucket": bucket} for bucket in ("investor_presentation", "annual_report", "concall_audio_link", "skip")]
    assert [row["bucket"] for row in dc.candidate_rows(rows, {"deck"})] == ["investor_presentation"]
    assert [row["bucket"] for row in dc.candidate_rows(rows, {"transcript"})] == ["concall_audio_link"]
    assert len(dc.candidate_rows(rows, None)) == 4
    # a deck-only build never downloads an audio-link PDF just to learn it is not a deck
    assert dc.candidate_rows([{"bucket": "concall_audio_link"}], {"deck"}) == []


def test_deck_manifest_skips_intimation_and_keeps_one_row_per_file(tmpdir):
    data = tmpdir / "data"
    data.mkdir()
    sha = "a" * 64
    con = sqlite3.connect(data / "deck_figures.db")
    con.execute("CREATE TABLE deck_sources (source TEXT, source_id TEXT, symbol TEXT, isin TEXT, exch_code TEXT, "
                "known_at TEXT, title TEXT, url TEXT, local_path TEXT, sha256 TEXT, size_bytes INTEGER, "
                "status TEXT, error TEXT, fetched_at TEXT)")
    con.executemany("INSERT INTO deck_sources VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", [
        ("bse", "1", "OLD", "INE000000001", "500001", "2024-05-01T10:00:00", "Investor Presentation Q4 FY24",
         "https://bse/1.pdf", r"D:\RealityEngine\data\decks\bse\500001\a.pdf", sha, 1000, "ok", "", ""),
        ("bse", "2", "OLD", "INE000000001", "500001", "2024-06-01T10:00:00", "Investor Presentation (re-filed)",
         "https://bse/2.pdf", r"D:\RealityEngine\data\decks\bse\500001\b.pdf", sha, 1000, "ok", "", ""),
        ("bse", "3", "OLD", "INE000000001", "500001", "2024-07-01T10:00:00",
         "Announcement under Regulation 30 (LODR)-Analyst / Investor Meet - Intimation",
         "https://bse/3.pdf", r"D:\RealityEngine\data\decks\bse\500001\c.pdf", "b" * 64, 1000, "ok", "", ""),
    ])
    con.commit()
    con.close()

    profile_json = {"companies": [{"symbol": "NEW", "isins": ["INE000000001"]}]}
    rows, skipped = tg.deck_manifest_rows(profile_json, data, "2024-04-01")
    assert skipped == 1, "the intimation letter is counted, not written"
    assert len(rows) == 1, "one file filed twice is one deck, dated by its earliest filing"
    assert tuple(rows[0]) == tg.MANIFEST_FIELDS
    assert rows[0]["symbol_at_time"] == "NEW" and rows[0]["bucket"] == "investor_presentation"
    assert rows[0]["dissem_ts"] == "2024-05-01T10:00:00" and rows[0]["status"] == "ok"
    assert rows[0]["local_path"].replace("\\", "/").endswith("/raw/decks/bse/500001/a.pdf")
    assert tg._ok_counts(rows) == (1, 1000)
