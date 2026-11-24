"""T-241: maker-checker-verifier gate for bulk hy4 reading."""
from __future__ import annotations

import json

import pytest

from reality_engine.v2 import observations as obs
from reality_engine.v2 import read_gate as rg


@pytest.fixture()
def gates(tmp_path, monkeypatch):
    path = tmp_path / "gates.json"
    monkeypatch.setattr(rg, "GATE_FILE", path)
    return path


def _entry(**kw):
    base = {"doc_type": "transcript", "fingerprint": rg.fingerprint("transcript"), "verdict": "pass",
            "reviewer": "Eagle", "author": "Wolf", "rows": 60}
    base.update(kw)
    return base


def test_bulk_run_without_audit_is_refused_pilot_is_not(gates, tmp_path):
    with pytest.raises(rg.GateError, match="no passing independent audit"):
        rg.check(["transcript"], rg.PILOT_PAGES + 1, tmp_path / "o.db")
    rg.check(["transcript"], rg.PILOT_PAGES, tmp_path / "o.db")       # a pilot needs no gate


def test_pass_by_independent_reviewer_allows(gates, tmp_path):
    rg.save([_entry()])
    rg.check(["transcript"], 5000, tmp_path / "o.db")


def test_reviewer_who_is_author_does_not_count(gates, tmp_path):
    rg.save([_entry(reviewer="Wolf", author="Wolf")])
    with pytest.raises(rg.GateError):
        rg.check(["transcript"], 5000, tmp_path / "o.db")


def test_prompt_change_invalidates_the_pass(gates, tmp_path, monkeypatch):
    rg.save([_entry()])
    monkeypatch.setattr(obs, "PROMPT_TRANSCRIPT", obs.PROMPT_TRANSCRIPT + "\nnew rule")
    with pytest.raises(rg.GateError):
        rg.check(["transcript"], 5000, tmp_path / "o.db")


def test_later_fail_withdraws_and_override_needs_shivam(gates, tmp_path):
    rg.save([_entry(), _entry(verdict="fail")])
    with pytest.raises(rg.GateError):
        rg.check(["transcript"], 5000, tmp_path / "o.db")
    rg.save([_entry(verdict="override", by="Wolf", reason="x")])
    with pytest.raises(rg.GateError):
        rg.check(["transcript"], 5000, tmp_path / "o.db")
    rg.save([_entry(verdict="override", by="Shivam", reason="read while the A/B runs")])
    rg.check(["transcript"], 5000, tmp_path / "o.db")


def test_checkpoint_written_and_blocks_until_graded_pass(gates, tmp_path, monkeypatch):
    monkeypatch.setattr(rg, "CHECKPOINT_PAGES", 3)
    out = tmp_path / "o.db"
    con = obs.create_db(out)
    for page in range(1, 4):
        con.execute("INSERT INTO page_read VALUES (?,?,?,?,?)", ("d", page, "rows", 1, f"t{page}"))
        con.execute("INSERT INTO observation (symbol, doc_key, page, known_at, measure, status) VALUES (?,?,?,?,?,?)",
                    ("S", "d", page, "2026-01-01", "m", "verified"))
    con.commit()
    sample = rg.maybe_checkpoint(con, out)
    con.close()
    assert sample is not None and len(sample.read_text(encoding="utf-8").splitlines()) == 3
    with pytest.raises(rg.GateError, match="not graded"):
        rg.check(["transcript"], 10, out)
    assert rg.main(["grade", "--ckpt", str(sample), "--verdict", "fail", "--reviewer", "Eagle"]) == 0
    with pytest.raises(rg.GateError, match="fail"):
        rg.check(["transcript"], 10, out)
    assert rg.main(["grade", "--ckpt", str(sample), "--verdict", "pass", "--reviewer", "Eagle"]) == 0
    rg.check(["transcript"], 10, out)


def test_cli_refuses_self_review_and_non_shivam_override(gates):
    assert rg.main(["record", "--doc-type", "transcript", "--verdict", "pass", "--reviewer", "Wolf",
                    "--author", "Wolf", "--evidence", "x", "--rows", "60"]) == 2
    assert rg.main(["record", "--doc-type", "transcript", "--verdict", "pass", "--reviewer", "Eagle",
                    "--author", "Wolf", "--evidence", "x", "--rows", "59"]) == 2
    assert rg.main(["override", "--doc-type", "transcript", "--by", "Eagle", "--reason", "x"]) == 2
    assert rg.main(["override", "--doc-type", "transcript", "--by", "Shivam", "--reason", "x"]) == 0
    assert json.loads(gates.read_text(encoding="utf-8"))["gates"][0]["verdict"] == "override"


def test_override_scope_limits_it_to_one_output(gates, tmp_path):
    rg.save([_entry(verdict="override", by="Shivam", reason="x", scope="obs_transcripts_fy27")])
    rg.check(["transcript"], 5000, tmp_path / "obs_transcripts_fy27.db")
    with pytest.raises(rg.GateError):
        rg.check(["transcript"], 5000, tmp_path / "obs_transcripts_394.db")
