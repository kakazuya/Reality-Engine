"""T-242 v3: a transcript read in windows of pages, one reader call per window."""
from __future__ import annotations

import json
import sqlite3

import pytest

from reality_engine.v2 import observations as obs


def _store(tmp_path, pages: dict[int, str]):
    db = tmp_path / "c01" / "c01.db"
    db.parent.mkdir()
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE doc (doc_key TEXT, symbol TEXT, isin TEXT, doc_type TEXT, title TEXT, filing_date TEXT, "
                "known_at TEXT, pages INTEGER)")
    con.execute("CREATE TABLE doc_page (doc_key TEXT, page INTEGER, text TEXT)")
    con.execute("CREATE TABLE company (symbol TEXT, name TEXT)")
    con.execute("INSERT INTO company VALUES ('ABC', 'Abc Industries Limited')")
    con.execute("INSERT INTO doc VALUES ('D:/x/ABC/concall_transcript/a.pdf','ABC','INE0','transcript','call',"
                "'2026-08-10','2026-08-10',?)", (len(pages),))
    for pg, text in pages.items():
        con.execute("INSERT INTO doc_page VALUES (?,?,?)", ("D:/x/ABC/concall_transcript/a.pdf", pg, text))
    con.commit()
    con.close()
    return str(db)


DK = "D:/x/ABC/concall_transcript/a.pdf"


def test_window_prompt_and_fingerprint(monkeypatch):
    monkeypatch.setattr(obs, "TRANSCRIPT_PROMPT", "v3")
    assert obs.template_for("transcript") is obs.PROMPT_TRANSCRIPT_V3
    assert obs.transcript_v2_mode()
    assert obs.quarters_around("Q1 FY27") == ("Q1 FY26", "Q4 FY26", "27")
    assert obs.quarters_around("Q3 FY26") == ("Q3 FY25", "Q2 FY26", "26")
    text = obs.PROMPT_TRANSCRIPT_V3.format(first=6, last=10, name="N", symbol="S", known_at="2026-08-10",
                                           call_quarter="Q1 FY27", year_ago="Q1 FY26", prev_quarter="Q4 FY26",
                                           fy="27", context_rule="", dictionary="D", text="T")
    assert '"page": <the === PAGE n === number>' in text and "year-ago quarter is\nQ1 FY26" in text


def test_expand_windows_blocks_and_context(tmp_path):
    store = _store(tmp_path, {pg: f"text {pg}" for pg in range(1, 13)})
    items = obs.expand_transcript_windows([{"store": store, "doc_key": DK, "page": 7},
                                           {"store": store, "doc_key": DK, "page": 9}], 5)
    assert len(items) == 1                                  # pages 7 and 9 share block 6-10
    assert [p["page"] for p in items[0]] == [6, 7, 8, 9, 10] and items[0][0]["context"] == [5]
    items = obs.expand_transcript_windows([{"store": store, "doc_key": DK, "page": 2},
                                           {"store": store, "doc_key": DK, "page": 12}], 5)
    assert [[p["page"] for p in it] for it in items] == [[1, 2, 3, 4, 5], [11, 12]]
    assert items[0][0]["context"] == [] and items[1][0]["context"] == [10]


def test_process_window_splits_rows_by_page(tmp_path, monkeypatch):
    pages = {5: "Ravi Kumar: margins were 18% in the quarter.",
             6: "Continuing, revenue grew 12% this quarter.",
             7: "Anita Rao: we expect capex of INR 500 crores in FY27."}
    store = _store(tmp_path, pages)
    monkeypatch.setattr(obs, "TRANSCRIPT_PROMPT", "v3")
    seen = {}
    reply = "\n".join(json.dumps(r) for r in [
        {"type": "number", "page": 5, "measure": "ebitda_margin", "printed_label": "margins were",
         "value_text": "18%", "unit": "%", "speaker": "Ravi Kumar"},                      # a context page: dropped
        {"type": "number", "page": 6, "measure": "revenue_growth_yoy", "printed_label": "revenue grew",
         "value_text": "12%", "unit": "%", "period": "Q1 FY27", "speaker": "Ravi Kumar",
         "claim_type": "company_actual"},
        {"type": "number", "page": 6, "measure": "revenue_growth_yoy", "printed_label": "revenue grew",
         "value_text": "12%", "unit": "%", "period": "Q1 FY27", "speaker": "Ravi Kumar",
         "claim_type": "company_actual"},                                                # a duplicate: dropped
        {"type": "statement", "page": 7, "measure": "capex",
         "text": "we expect capex of INR 500 crores in FY27.", "speaker": "Anita Rao"},
        {"type": "statement", "measure": "capex", "text": "no page", "speaker": "Anita Rao"}])  # no page: dropped

    def fake(prompt, image, doc_key, page):
        seen["prompt"] = prompt
        return {"output": reply, "seconds": 3.0, "in_tok": 900, "out_tok": 300}
    monkeypatch.setattr(obs, "call_reader", fake)
    monkeypatch.setattr(obs, "quota_seconds", lambda: 0)
    out = obs.process_window(store, DK, [6, 7], [5])
    assert [r["page"] for r in out] == [6, 7]
    assert "=== PAGE 5 (CONTEXT ONLY" in seen["prompt"] and "Abc Industries Limited (ABC)" in seen["prompt"]
    assert "year-ago quarter is\nQ1 FY26" in seen["prompt"]
    assert out[0]["parsed"] == 1 and out[1]["parsed"] == 1 and out[0]["unplaced"] == 2
    assert out[0]["in_tok"] == 900 and out[1]["in_tok"] == 0          # the call's cost sits on the first page
    assert json.loads(out[0]["raw"])["page"] == 6 and json.loads(out[1]["raw"])["page"] == 7
    assert all(r["page"] == 6 for r in out[0]["rows"]) and all(r["page"] == 7 for r in out[1]["rows"])


def test_process_window_error_marks_every_page(tmp_path, monkeypatch):
    store = _store(tmp_path, {1: "a", 2: "b"})
    monkeypatch.setattr(obs, "TRANSCRIPT_PROMPT", "v3")
    monkeypatch.setattr(obs, "quota_seconds", lambda: 0)
    monkeypatch.setattr(obs, "call_reader", lambda *a: {"output": "", "error": "HTTP 500"})
    out = obs.process_window(store, DK, [1, 2], [])
    assert [r["error"] for r in out] == ["HTTP 500", "HTTP 500"] and all(r["rows"] == [] for r in out)


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
