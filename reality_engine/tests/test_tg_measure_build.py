"""T-214: the measure runner's peak-RSS sampler, its kill flags and its CSV row, on fake parts only.

These tests never run a build: a fake part is ``python -c`` that allocates a block or prints lines, so the sampler,
the RAM stop, the timeout and the ``parts.csv`` row are pinned without touching any store.

    python -m pytest reality_engine/tests/test_tg_measure_build.py -q
"""
from __future__ import annotations

import csv
import shutil
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
