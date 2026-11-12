"""T-124: the shell CLI runs the same pilot3 lookups as the MCP, against the database it is given."""
import json

from reality_engine.scripts import p3ask


def test_unknown_tool_and_bad_args_are_data_not_crashes():
    assert "error" in p3ask.run("nonexistent.db", "nope", {})
    assert p3ask.main(["--db", "x.db", "kpi", "noequals"]) == 2


def test_calc_runs_without_a_database():
    out = p3ask.run("nonexistent.db", "pilot3_calc", {"expression": "a/b", "inputs": {"a": 10, "b": 4}})
    assert out["value"] == 2.5


def test_call_log_line_shape(tmp_path):
    log = tmp_path / "calls.jsonl"
    args = ["--db", "x.db", "--qid", "q2", "--log", str(log), "calc", "expression=a/b", 'inputs={"a":10,"b":4}']
    assert p3ask.main(args) == 0
    assert p3ask.main(["--db", "x.db", "--qid", "q2", "--log", str(log), "nope"]) == 0
    lines = [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines()]
    assert len(lines) == 2
    assert set(lines[0]) == {"ts_start", "ts_end", "seconds", "qid", "tool", "args", "ok", "rows_returned",
                             "reply_bytes"}
    assert lines[0]["qid"] == "q2" and lines[0]["tool"] == "calc" and lines[0]["ok"] is True
    assert lines[1]["ok"] is False


def test_log_failure_never_changes_the_reply(tmp_path):
    out = p3ask.run("x.db", "calc", {"expression": "a/b", "inputs": {"a": 10, "b": 4}}, log=str(tmp_path))
    assert out["value"] == 2.5


def test_no_sql_arm_refuses_sql(monkeypatch):
    monkeypatch.setenv("P3ASK_NO_SQL", "1")
    out = p3ask.run("x.db", "sql", {"query": "SELECT 1"})
    assert out == {"error": "sql tool is not available in this run; use the typed tools"}
    assert "sql" not in p3ask.tools()
    assert "sql" not in p3ask.run("x.db", "nope", {})["error"].split("choose from")[1]
    monkeypatch.delenv("P3ASK_NO_SQL")
    assert "sql" in p3ask.tools()


def test_page_tool_rejects_a_quoted_key_and_survives_the_no_sql_arm(monkeypatch):
    monkeypatch.setenv("P3ASK_NO_SQL", "1")
    assert "page" in p3ask.tools()
    assert "doc_key" in p3ask.run("nonexistent.db", "page", {"doc_key": "a' OR 1=1 --", "page": 1})["error"]


def test_no_semantic_arm_drops_only_semantic(monkeypatch):
    """T-191: arm A of the semantic A/B refuses `semantic` and keeps every other tool."""
    monkeypatch.setenv("P3ASK_NO_SEMANTIC", "1")
    assert "semantic" not in p3ask.tools()
    assert "unknown tool" in p3ask.run("x.db", "semantic", {"symbol": "X", "query": "q"})["error"]
    assert set(p3ask.TOOLS) - set(p3ask.tools()) == {"semantic"}
    monkeypatch.delenv("P3ASK_NO_SEMANTIC")
    assert "semantic" in p3ask.tools()
