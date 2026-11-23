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
