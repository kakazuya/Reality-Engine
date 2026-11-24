"""Run ledger: tool categories, answer ingest with workaround reasons, reader ingest."""
import json
from pathlib import Path

from reality_engine.scripts import run_ledger as rl

TMP = Path(".tmp/test_run_ledger")


def _fresh(monkeypatch, name):
    TMP.mkdir(parents=True, exist_ok=True)
    db = TMP / f"{name}.db"
    for p in (db, Path(str(db) + "-wal"), Path(str(db) + "-shm")):
        if p.exists():
            p.unlink()
    monkeypatch.setattr(rl, "LEDGER", db)
    return rl.connect()


def test_categories():
    assert rl.categorise("mcp__reality-data__pilot3_fin") == "mcp"
    assert rl.categorise("mcp__reality-data__pilot3_sql") == "sql"
    assert rl.categorise("pwsh", "python -m reality_engine.scripts.p3ask --db x fin symbol=BEL") == "mcp"
    assert rl.categorise("pwsh", "python -m reality_engine.scripts.p3ask --db x sql query=select") == "sql"
    assert rl.categorise("pwsh", "python -c \"import sqlite3; sqlite3.connect('x.db')\"") == "workaround"
    assert rl.categorise("Edit") == "write"


def test_answers_keep_workaround_reason_and_gap(monkeypatch):
    con = _fresh(monkeypatch, "answers")
    run = TMP / "answers"
    run.mkdir(exist_ok=True)
    rows = [{"event": "start", "qid": "BEL-001", "at": "2026-11-11T10:00:00+00:00"},
            {"event": "answer", "qid": "BEL-001", "at": "2026-11-11T10:00:40+00:00", "answer": "x", "status": "answered",
             "tools": ["fin", "sql"], "workaround_reason": "pilot3_fin has no segment rows",
             "gap_class": "not_extracted", "gap_note": "segment revenue"}]
    (run / "BEL_answers.jsonl").write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    assert rl.ingest_answers(con, run, "r1", "s", "m") == 1
    row = con.execute("SELECT used_sql, seconds, workaround_reason, gap_class FROM answer").fetchone()
    assert row == (1, 40.0, "pilot3_fin has no segment rows", "not_extracted")


def test_reader_run(monkeypatch):
    con = _fresh(monkeypatch, "reader")
    run = TMP / "reader"
    run.mkdir(exist_ok=True)
    (run / "transcribe_log.csv").write_text(
        "page_id,reader,input,seconds,in_tok,out_tok,error,n_rows\np001,r,layout,10,100,50,,7\np002,r,layout,20,100,50,boom,0\n",
        encoding="utf-8")
    assert rl.ingest_reader(con, run) == 2
    assert con.execute("SELECT items, seconds, outcome FROM run").fetchone() == (2, 30.0, "1 errors")


def test_ingest_dsh_classifies_grader_without_review(monkeypatch, tmp_path):
    con = _fresh(monkeypatch, "dsh_kind")
    jobs = tmp_path / "jobs"
    cases = [
        ("job_grader", "Goal: Grader for T-241 prompt check\n", "dsh_grader"),
        ("job_grading", "Goal: Independent grading pass\n", "dsh_grader"),
        ("job_worker", "Goal: Upgrade schema and run worker\n", "dsh_worker"),
    ]
    for job_id, brief, _expected in cases:
        jdir = jobs / job_id
        jdir.mkdir(parents=True)
        (jdir / "status.json").write_text(json.dumps({"job_id": job_id, "outcome": "completed"}), encoding="utf-8")
        (jdir / "brief.md").write_text(brief, encoding="utf-8")

    monkeypatch.setattr(rl, "JOBS", jobs)
    assert rl.ingest_dsh(con) == len(cases)
    got = dict(con.execute("SELECT run_id, kind FROM run").fetchall())
    for job_id, _brief, expected in cases:
        assert got[job_id] == expected

