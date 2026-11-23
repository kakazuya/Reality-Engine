"""T-241: prestage_raw moves a company's raw bucket folders to the SSD and junctions them back."""
from __future__ import annotations

import os
import sys

import pytest

from reality_engine.scripts import prestage_raw as ps

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="junctions and robocopy are Windows-only")


def test_bucket_moves_and_old_path_still_reads(tmp_path):
    raw, stage = tmp_path / "raw", tmp_path / "stage"
    (raw / "ABC" / "annual_report").mkdir(parents=True)
    (raw / "ABC" / "annual_report" / "1.pdf").write_bytes(b"%PDF one")
    assert ps.stage_symbol("ABC", raw=raw, stage=stage, min_free_gb=0) == 1
    assert os.path.isjunction(raw / "ABC" / "annual_report")
    assert (raw / "ABC" / "annual_report" / "1.pdf").read_bytes() == b"%PDF one"
    assert (stage / "ABC" / "annual_report" / "1.pdf").is_file()
    assert ps.stage_symbol("ABC", raw=raw, stage=stage, min_free_gb=0) == 0      # junction: skipped


def test_next_positions_follow_each_busy_company(tmp_path):
    for name, built in (("c01", True), ("c02", False), ("c05", False), ("c06", True)):
        (tmp_path / name).mkdir()
        if built:
            (tmp_path / name / f"{name}_measure.json").write_text("{}")
    assert ps.next_positions(tmp_path, 8, 2) == [3, 4, 7, 8]
