"""T-205 round 13 arm S: the seeded tool run, with the agy call faked (no network, no real agy)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from reality_engine.answer import seeded_run  # noqa: E402

QUESTIONS = [
    {"qid": "BS-001", "question": "What was revenue in Q2FY27?", "as_of": "2026-11-11"},
    {"qid": "BS-002", "question": "What did management say about pricing?", "as_of": "2026-11-11"},
]


def _packs(tmp_path: Path) -> Path:
    packs = tmp_path / "packs"
    packs.mkdir()
    (packs / "pack_BS-001.txt").write_text("PACK EVIDENCE: revenue 2,930.95 crore", encoding="utf-8")
    (packs / "pack_BS-002.txt").write_text("PACK EVIDENCE: nothing about pricing", encoding="utf-8")
    return packs


def _run(question, model, **kwargs):
    assert "EVIDENCE ALREADY GATHERED" in question
    if "pricing" in question:
        return {"ok": True, "text": '{"answer": "Management said pricing discipline broke down.", '
                                    '"sources": [{"doc_key": "call.pdf", "doc_type": "transcript", "page": 4}], '
                                    '"confidence": "high"}',
                "tools": {"pilot3_statements": 2, "pilot3_fact": 1, "view_file": 1}, "data_tool_calls": 3,
                "tool_calls": 4, "tool_calls_by_tool": {"mcp_reality-data_pilot3_statements": 2,
                                                       "mcp_reality-data_pilot3_fact": 1, "view_file": 1},
                "tokens": {"input_tokens": 900, "output_tokens": 60}, "seconds": 12.5, "attempts": 1,
                "error": "", "log": "log.jsonl"}
    return {"ok": True, "text": "Revenue was 2,930.95 crore in Q2FY27.", "tools": {}, "data_tool_calls": 0,
            "tool_calls": 1, "tool_calls_by_tool": {"view_file": 1}, "tokens": {}, "seconds": 5.0,
            "attempts": 1, "error": "", "log": "log.jsonl"}


def test_run_set_writes_dsa_shape_and_resumes(tmp_path):
    questions = tmp_path / "questions_in.json"
    questions.write_text(json.dumps(QUESTIONS), encoding="utf-8")
    packs = _packs(tmp_path)
    out = tmp_path / "out"
    summary = seeded_run.run_set(questions, packs, out, model="gemini-4-hydrogen-high", symbol="BLUESTARCO",
                                 workspace=tmp_path, run=_run)
    assert summary["answered"] == 2 and summary["failed"] == 0 and summary["with_tools"] == 1
    rows = [json.loads(line) for line in (out / "answers.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [r["qid"] for r in rows] == ["BS-001", "BS-002"]
    first = rows[0]
    assert set(first) >= {"qid", "question", "as_of", "answer", "tools", "sources", "sql_reason", "confidence"}
    assert first["answer"].startswith("Revenue was") and first["parsed"] is False   # whole prose kept
    second = rows[1]
    assert second["tools"] == ["fact", "statements"] and second["sources"][0]["page"] == 4
    assert second["confidence"] == "high" and second["parsed"] is True
    calls = [json.loads(line) for line in (out / "calls.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(calls) == 2 and calls[1]["tool_calls_by_tool"]["mcp_reality-data_pilot3_statements"] == 2

    again = seeded_run.run_set(questions, packs, out, symbol="BLUESTARCO", workspace=tmp_path, run=_run)
    assert again["skipped"] == 2 and again["answered"] == 2
    assert len((out / "answers.jsonl").read_text(encoding="utf-8").splitlines()) == 2


def test_blank_pack_is_labelled_not_crashed(tmp_path):
    questions = tmp_path / "q.json"
    questions.write_text(json.dumps(QUESTIONS[:1]), encoding="utf-8")
    prompt = seeded_run.build_prompt("q?", "2026-11-11", "BLUESTARCO", "")
    assert "pack is empty for this question" in prompt and "asked as of 2026-11-11" in prompt


def test_cli_routes_the_model_and_reports(tmp_path, monkeypatch):
    seen = {}

    def fake(questions, packs, out, **kwargs):
        seen.update(kwargs)
        return {"failed": 2}

    monkeypatch.setattr(seeded_run, "run_set", fake)
    rc = seeded_run.main(["--set", "bluestar", "--packs", "P", "--out", "O",
                          "--model", "agy:gemini-4-hydrogen-high"])
    assert rc == 1                                  # a failed question is a non-zero run
    assert seen["model"] == "gemini-4-hydrogen-high" and seen["symbol"] == "BLUESTARCO"
