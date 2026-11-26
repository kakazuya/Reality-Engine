"""Run ledger: tool categories, answer ingest with workaround reasons, reader ingest, incremental transcript reads."""
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


def _claude_lines(n, start=0):
    """A tool_use and its result per call, the shape a session transcript has."""
    out = []
    for i in range(start, start + n):
        ts = f"2026-11-24T10:00:{i:02d}+00:00"
        out.append(json.dumps({"timestamp": ts, "message": {
            "model": "m", "usage": {"input_tokens": 10, "output_tokens": 2},
            "content": [{"type": "tool_use", "id": f"t{i}", "name": "read", "input": {"file": f"f{i}"}}]}}))
        out.append(json.dumps({"timestamp": ts, "message": {
            "content": [{"type": "tool_result", "tool_use_id": f"t{i}"}]}}))
    return out


def _event(kind, **kw):
    return json.dumps({"type": kind, **kw})


def _dump(con):
    """Every row an ingest writes, minus the ingest timestamp (which moves between two ingests)."""
    cur = con.execute("SELECT * FROM run")
    cols = [d[0] for d in cur.description or []]
    runs = [dict(zip(cols, r)) for r in cur]
    for r in runs:
        r.pop("ingested_at")
    calls = con.execute("SELECT run_id, seq, tool, category, status, arg FROM tool_call ORDER BY run_id, seq").fetchall()
    return runs, calls


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


def test_ingest_claude_reads_only_appended_lines(monkeypatch, tmp_path):
    con = _fresh(monkeypatch, "claude_tail")
    transcript = tmp_path / "s1.jsonl"
    first = _claude_lines(2)
    transcript.write_text("\n".join(first) + "\n", encoding="utf-8")
    assert rl.ingest_claude(con, transcript) == 2

    transcript.write_text("\n".join(first + _claude_lines(1, 2)) + "\n", encoding="utf-8")
    decoded = []
    loads = rl.json.loads
    monkeypatch.setattr(rl.json, "loads", lambda s, *a, **k: decoded.append(s) or loads(s, *a, **k))
    assert rl.ingest_claude(con, transcript) == 3
    # the appended call was decoded, the two already-ingested calls were not
    assert sum(s.count('"type": "tool_use"') for s in decoded) == 1
    assert con.execute("SELECT tool_calls, in_tok, out_tok, started_at FROM run").fetchone() == (
        3, 30, 6, "2026-11-24T10:00:00+00:00")
    assert con.execute("SELECT status FROM tool_call ORDER BY seq").fetchall() == [("completed",)] * 3


def test_ingest_claude_incremental_matches_a_full_ingest(monkeypatch, tmp_path):
    transcript = tmp_path / "s2.jsonl"
    lines = _claude_lines(3)
    transcript.write_text("\n".join(lines[:3]) + "\n", encoding="utf-8")   # stop after a tool_use, before its result
    con = _fresh(monkeypatch, "claude_inc")
    rl.ingest_claude(con, transcript)
    assert con.execute("SELECT status FROM tool_call ORDER BY seq").fetchall() == [("completed",), ("",)]

    transcript.write_text("\n".join(lines) + "\n", encoding="utf-8")
    rl.ingest_claude(con, transcript)

    full = _fresh(monkeypatch, "claude_full")
    rl.ingest_claude(full, transcript)
    assert _dump(full) == _dump(con)
    assert con.execute("SELECT status FROM tool_call ORDER BY seq").fetchall() == [("completed",)] * 3


def test_ingest_claude_resets_when_the_transcript_is_replaced(monkeypatch, tmp_path):
    con = _fresh(monkeypatch, "claude_reset")
    transcript = tmp_path / "s3.jsonl"
    transcript.write_text("\n".join(_claude_lines(3)) + "\n", encoding="utf-8")
    assert rl.ingest_claude(con, transcript) == 3

    transcript.write_text("\n".join(_claude_lines(1)) + "\n", encoding="utf-8")   # shorter: a replacement, not an append
    assert rl.ingest_claude(con, transcript) == 1
    assert con.execute("SELECT COUNT(*) FROM tool_call").fetchone()[0] == 1
    assert con.execute("SELECT tool_calls, in_tok FROM run").fetchone() == (1, 10)


def test_ingest_dsh_reads_appended_events(monkeypatch, tmp_path):
    con = _fresh(monkeypatch, "dsh_tail")
    jobs = tmp_path / "jobs"
    jdir = jobs / "job_1"
    jdir.mkdir(parents=True)
    status = {"job_id": "job_1", "outcome": "running", "started_at": "2026-11-24T10:00:00+00:00"}
    (jdir / "status.json").write_text(json.dumps(status), encoding="utf-8")
    (jdir / "brief.md").write_text("Goal: worker job\n", encoding="utf-8")
    events = jdir / "result.md.events.jsonl"
    lines = [_event("tool_call", callId="c1", tool="read", input="a"),
             _event("tool_result", callId="c1", status="completed"), _event("thinking")]
    events.write_text("\n".join(lines) + "\n", encoding="utf-8")
    monkeypatch.setattr(rl, "JOBS", jobs)
    assert rl.ingest_dsh(con) == 1

    lines.append(_event("tool_call", callId="c2", tool="Edit", input="b"))   # its result arrives after this stop
    events.write_text("\n".join(lines) + "\n", encoding="utf-8")
    rl.ingest_dsh(con)
    lines += [_event("tool_result", callId="c2", status="error"), _event("thinking")]
    events.write_text("\n".join(lines) + "\n", encoding="utf-8")
    status.update(outcome="completed", finished_at="2026-11-24T10:02:00+00:00")
    (jdir / "status.json").write_text(json.dumps(status), encoding="utf-8")
    rl.ingest_dsh(con)

    assert con.execute("SELECT tool, status FROM tool_call ORDER BY seq").fetchall() == [
        ("read", "completed"), ("Edit", "error")]
    assert con.execute("SELECT tool_calls, model_steps, outcome FROM run").fetchone() == (2, 2, "completed")

    full = _fresh(monkeypatch, "dsh_tail_full")
    rl.ingest_dsh(full)
    assert _dump(full) == _dump(con)

