"""T-241: maker-checker-verifier gate for bulk hy4 reading."""
from __future__ import annotations

import json

import pytest

from reality_engine.v2 import observations as obs
from reality_engine.v2 import read_gate as rg


@pytest.fixture(autouse=True)
def _strict(request, monkeypatch):
    """The tests below check the blocking gate, which since Shivam's 26 Nov ruling runs only when strict is on."""
    if "default" not in request.node.name:
        monkeypatch.setenv("REALITY_READ_GATE_STRICT", "1")
    else:
        monkeypatch.delenv("REALITY_READ_GATE_STRICT", raising=False)


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
    rg.save([_entry(verdict="override", by="Shivam", reason="read while the A/B runs", quote="q")])
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
    assert rg.main(["override", "--doc-type", "transcript", "--by", "Eagle", "--reason", "x", "--quote", "q"]) == 2
    assert rg.main(["override", "--doc-type", "transcript", "--by", "Shivam", "--reason", "x", "--quote", "q"]) == 0
    assert json.loads(gates.read_text(encoding="utf-8"))["gates"][0]["verdict"] == "override"


def test_override_scope_limits_it_to_one_output(gates, tmp_path):
    rg.save([_entry(verdict="override", by="Shivam", reason="x", quote="q", scope="obs_transcripts_fy27")])
    rg.check(["transcript"], 5000, tmp_path / "obs_transcripts_fy27.db")
    with pytest.raises(rg.GateError):
        rg.check(["transcript"], 5000, tmp_path / "obs_transcripts_394.db")


def test_chunked_runs_cannot_dodge_the_pilot_allowance(gates, tmp_path):
    """Eagle review: pages already in the output's ledger count toward the 200-page pilot allowance."""
    out = tmp_path / "o.db"
    con = obs.create_db(out)
    con.executemany("INSERT INTO page_read VALUES (?,?,?,?,?)", [("d", n, "rows", 1, "t") for n in range(150)])
    con.commit()
    con.close()
    rg.check(["transcript"], 50, out)
    with pytest.raises(rg.GateError):
        rg.check(["transcript"], 51, out)


def test_override_without_quote_does_not_count(gates, tmp_path):
    rg.save([_entry(verdict="override", by="Shivam", reason="x")])
    with pytest.raises(rg.GateError):
        rg.check(["transcript"], 5000, tmp_path / "o.db")


def test_checkpoint_stops_the_running_read(gates, tmp_path, monkeypatch):
    """Eagle review: a checkpoint stops the run itself, so an ungraded audit never lets 30k pages through."""
    monkeypatch.setattr(rg, "CHECKPOINT_PAGES", 2)
    out = tmp_path / "o.db"
    pages = [{"store": "s", "doc_key": "d", "page": n} for n in range(1, 11)]
    monkeypatch.setattr(obs, "pages_from_store", lambda *a, **k: list(pages))
    monkeypatch.setattr(obs, "company_index", lambda dbs: {})
    seen = []
    monkeypatch.setattr(obs, "process_page", lambda store, key, page, comp, text_only: seen.append(page) or
                        {"store": store, "doc_key": key, "page": page, "rows": [], "raw": "x", "parsed": 1})
    monkeypatch.setattr(obs, "propose_measures", lambda *a, **k: {})
    monkeypatch.setattr(obs, "index_new_measures", lambda con: 0)
    monkeypatch.setattr(obs, "write_new_merges", lambda con, path: 0)
    stats = obs.run(["s"], limit=10, workers=1, out=out, doc_types=("deck",), resume=True)
    assert "audit checkpoint" in stats["stopped"]
    import sqlite3 as _sq
    con = _sq.connect(out)
    assert con.execute("SELECT COUNT(*) FROM page_read").fetchone()[0] == 2   # nothing recorded after the stop
    replies = con.execute("SELECT raw, fingerprint FROM page_reply").fetchall()
    assert len(replies) == 2 and replies[0][0] == "x" and replies[0][1].startswith("deck:")   # raw kept for re-parse
    con.close()
    with pytest.raises(rg.GateError, match="not graded"):
        rg.check(["deck"], 1, out)


def test_override_scope_is_the_exact_output_name(gates, tmp_path):
    rg.save([_entry(verdict="override", by="Shivam", reason="x", quote="q", scope="obs_transcripts_fy27")])
    with pytest.raises(rg.GateError):
        rg.check(["transcript"], 5000, tmp_path / "obs_transcripts_fy27_v2.db")


def test_cli_prompt_choice_reaches_the_gate():
    """python -m runs observations as __main__ (a second module object); the gate must still see v2."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("__obs_as_main__", obs.__file__)
    main_copy = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(main_copy)
    try:
        main_copy.apply_prompt_choice("v2")
        assert obs.TRANSCRIPT_PROMPT == "v2"
        assert rg.fingerprint("transcript") == "e95108f16e65"
    finally:
        obs.TRANSCRIPT_PROMPT = "v1"


def test_default_never_blocks_reading_on_missing_or_failed_grades(tmp_path, gates, capsys):
    """Shivam 26 Nov 2026: readings are never blocked; pending reviews are printed."""
    out = tmp_path / "o.db"
    d = rg.audit_dir(out)
    d.mkdir()
    (d / "ckpt_0001.jsonl").write_text("{}", encoding="utf-8")
    (d / "ckpt_0002.jsonl").write_text("{}", encoding="utf-8")
    (d / "ckpt_0002.grade.json").write_text(json.dumps({"verdict": "fail", "counts": "37/11/12/0"}), encoding="utf-8")
    rg.check(["transcript"], 50_000, out)          # no GateError
    assert "not blocking" in capsys.readouterr().err


def test_default_verified_allowed_only_at_or_under_ten_percent(tmp_path):
    out = tmp_path / "o.db"
    d = rg.audit_dir(out)
    d.mkdir()
    assert rg.verified_allowed(out)                                   # never graded
    (d / "ckpt_0001.grade.json").write_text(json.dumps({"verdict": "pass", "counts": "54/3/2/1"}), encoding="utf-8")
    assert rg.latest_grade_share(out) == 0.05 and rg.verified_allowed(out)
    (d / "ckpt_0002.grade.json").write_text(json.dumps({"verdict": "fail", "counts": "50/3/6/1"}), encoding="utf-8")
    assert not rg.verified_allowed(out)                               # 7/60 = 11.7% > 10%


def test_default_steady_output_graded_every_fifth_checkpoint(tmp_path):
    """Shivam 27 Nov 2026: a type that keeps passing is graded every 5th checkpoint; a fail restores every one."""
    out = tmp_path / "o.db"
    d = rg.audit_dir(out)
    d.mkdir()
    for k in range(1, 8):
        (d / f"ckpt_{k:04d}.jsonl").write_text("{}", encoding="utf-8")

    def grade(k, verdict):
        (d / f"ckpt_{k:04d}.grade.json").write_text(json.dumps({"verdict": verdict}), encoding="utf-8")

    assert rg.grade_needed(out, 1) and rg.grade_needed(out, 2)        # fewer than 2 grades: every checkpoint
    grade(1, "pass")
    grade(2, "pass")
    assert not rg.grade_needed(out, 3) and not rg.grade_needed(out, 4)
    assert rg.grade_needed(out, 5)                                    # every 5th is always graded
    assert rg.pending_checkpoints(out) == ["ckpt_0005.jsonl: not graded"]
    grade(5, "fail")
    assert rg.grade_needed(out, 6) and rg.grade_needed(out, 7)        # a fail: every checkpoint again
    assert "ckpt_0006.jsonl: not graded" in rg.pending_checkpoints(out)
    grade(6, "pass")
    assert rg.grade_needed(out, 7)                                    # one pass after a fail is not steady yet
