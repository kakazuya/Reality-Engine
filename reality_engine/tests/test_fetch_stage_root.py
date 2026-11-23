"""T-241: --stage-root writes new <SYM>/<bucket> folders on the stage drive, junctioned into the raw root."""
from __future__ import annotations

import os
import sys

import pytest

from reality_engine.scripts import fetch_pilot60_history as f

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="junctions are Windows-only")


def test_new_bucket_folder_is_a_junction_to_the_stage(tmp_path, monkeypatch):
    root, stage = tmp_path / "raw" / "pilot60_history", tmp_path / "stage" / "pilot60_history"
    monkeypatch.setattr(f, "ROOT", root)
    monkeypatch.setattr(f, "STAGE_ROOT", stage)
    dest = f.target_path("ABC", "material_filing", "123")
    f.stage_dir(dest.parent)
    dest.write_bytes(b"%PDF-1.4 x")
    assert (stage / "ABC" / "material_filing" / "123.pdf").read_bytes() == b"%PDF-1.4 x"
    assert os.path.isjunction(dest.parent)
    os.remove(dest)                      # raw_to_drive deletes through the stored path
    assert not (stage / "ABC" / "material_filing" / "123.pdf").exists()


def test_existing_folder_is_left_on_the_raw_drive(tmp_path, monkeypatch):
    root, stage = tmp_path / "raw" / "pilot60_history", tmp_path / "stage" / "pilot60_history"
    (root / "ABC" / "annual_report").mkdir(parents=True)
    monkeypatch.setattr(f, "ROOT", root)
    monkeypatch.setattr(f, "STAGE_ROOT", stage)
    f.stage_dir(root / "ABC" / "annual_report")
    assert not os.path.isjunction(root / "ABC" / "annual_report")
    assert not stage.exists()


def test_no_stage_root_changes_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(f, "ROOT", tmp_path)
    monkeypatch.setattr(f, "STAGE_ROOT", None)
    f.stage_dir(tmp_path / "X" / "b")
    assert not (tmp_path / "X").exists()
