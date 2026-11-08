"""T-124: the shell CLI runs the same pilot3 lookups as the MCP, against the database it is given."""
from reality_engine.scripts import p3ask


def test_unknown_tool_and_bad_args_are_data_not_crashes():
    assert "error" in p3ask.run("nonexistent.db", "nope", {})
    assert p3ask.main(["--db", "x.db", "kpi", "noequals"]) == 2


def test_calc_runs_without_a_database():
    out = p3ask.run("nonexistent.db", "pilot3_calc", {"expression": "a/b", "inputs": {"a": 10, "b": 4}})
    assert out["value"] == 2.5
