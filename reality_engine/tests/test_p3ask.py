"""T-124: the shell CLI runs the same pilot3 lookups as the MCP, against the database it is given."""
from reality_engine.scripts import p3ask


def test_unknown_tool_and_bad_args_are_data_not_crashes():
    assert "error" in p3ask.run("nonexistent.db", "nope", {})
    assert p3ask.main(["--db", "x.db", "kpi", "noequals"]) == 2


def test_calc_runs_without_a_database():
    out = p3ask.run("nonexistent.db", "pilot3_calc", {"expression": "a/b", "inputs": {"a": 10, "b": 4}})
    assert out["value"] == 2.5


def test_logging_line_shape():
    log = __import__("pathlib").Path("calls_t179.jsonl")
    if log.exists():
        log.unlink()
    rc = p3ask.main(["--db", "x.db", "kpi", "--qid", "q1", "--log", str(log)])
    # unknown tool still logs? run returns error but main rc 0 (prints json). Actually main returns 0.
    assert rc == 0
    # trigger a successful calc log
    p3ask.main(["--db", "x.db", "calc", "expression=a/b", "inputs={\"a\":10,\"b\":4}", "--qid", "q2", "--log", str(log)])
    lines = [l for l in log.read_text().splitlines() if l.strip()]
    assert len(lines) >= 2
    rec = __import__("json").loads(lines[-1])
    for k in ("ts_start", "ts_end", "seconds", "qid", "tool", "args", "ok"):
        assert k in rec
    assert "reply bytes" in rec or "reply_bytes" in rec


def test_no_sql_refusal(monkeypatch):
    monkeypatch.setenv("P3ASK_NO_SQL", "1")
    # recompute tools
    assert "sql" not in p3ask._tools()
    out = p3ask.run("x.db", "sql", {"query": "select 1"})
    assert "error" in out
    assert "not available" in out["error"]
