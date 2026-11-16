"""T-217: the question bank's queue, validation, freezing, loading and one injected harvest run.

Fixtures only: every page fetch and every model run is injected, so no network and no agy call happens here.
Tiny sqlite files and CSV/JSON files live under ``.tmp/pytest`` (the local ``tmp_path`` fixture of
``test_store_repair.py``: pytest's own cannot be listed in this sandbox).
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from reality_engine.scripts import tg_questions


@pytest.fixture()
def tmp_path():
    path = Path(".tmp") / "pytest" / uuid.uuid4().hex[:8]
    path.mkdir(parents=True, exist_ok=False)
    return path


def _fetcher(pages: dict[str, tuple[int, str]]):
    def fetch(url: str):
        return pages.get(url, (0, ""))

    return fetch


def _ok_page(url: str):
    return 200, "Acme Steel Industries Ltd reported results and an order book."


def _entry() -> dict:
    return {"isin": "INE000A01001", "symbol": "ACME", "company": "Acme Steel Industries Ltd"}


def _payload(found: int = 5, created: int = 15) -> dict:
    questions = [{"question": f"What do investors ask about Acme Steel number {i}?", "kind": "found",
                  "theme": tg_questions.THEMES[i % len(tg_questions.THEMES)],
                  "source_url": f"https://acme.example/page{i}", "data_needed": "concall: demand"}
                 for i in range(found)]
    questions += [{"question": f"How should an analyst read Acme Steel measure {i}?", "kind": "created",
                   "theme": "accounting", "grounding_fact": "Makes steel",
                   "data_needed": "results: line item"} for i in range(created)]
    return {"business_facts": [{"fact": "Makes steel", "source_url": "https://acme.example/about"}],
            "questions": questions}


def test_read_queue_skips_demo_isins_and_gives_one_based_positions(tmp_path):
    path = tmp_path / "build_queue.csv"
    path.write_text("company,symbol,isin\nAcme Steel Ltd,ACME,INE000A01001\n"
                    "Demo One,DEMO1,INE_AUTO_1\nBeta Ltd,BETA,INE000A01002\n", encoding="utf-8")
    rows = tg_questions.read_queue(path)
    assert [r["isin"] for r in rows] == ["INE000A01001", "INE000A01002"]
    assert [r["position"] for r in rows] == [1, 2]


def test_name_tokens_drops_stop_words_and_keeps_three_words_plus_symbol():
    assert tg_questions.name_tokens("Acme Steel and Wire Industries Limited", "ACME") == \
        ["acme", "steel", "wire", "acme"]
    assert tg_questions.name_tokens("Acme Alpha Beta Gamma Ltd", "") == ["acme", "alpha", "beta"]


def test_clean_rows_verifies_found_questions_and_drops_bad_created_ones():
    pages = {
        "https://acme.example/about": (200, "Acme Steel Industries Ltd makes steel."),
        "https://acme.example/missing": (404, ""),
        "https://other.example/post": (200, "A generic market page."),
        "https://www.acme.example/files/annual.pdf": (200, "%PDF-1.4 ..."),
    }
    payload = {"questions": [
        {"question": "What drives Acme Steel's volume growth?", "kind": "found", "theme": "segments",
         "source_url": "https://acme.example/about", "source_title": "About"},
        {"question": "How did Acme Steel's order book end the quarter?", "kind": "found",
         "theme": "next_two_quarters", "source_url": "https://acme.example/missing"},
        {"question": "Why is Acme Steel's margin lower than peers?", "kind": "found", "theme": "transcript",
         "source_url": "https://other.example/post"},
        {"question": "What does Acme Steel's annual report say on capex?", "kind": "found", "theme": "accounting",
         "source_url": "https://www.acme.example/files/annual.pdf"},
        {"question": "How much of revenue comes from repeat customers?", "kind": "created",
         "theme": "revenue_sources", "grounding_fact": "Makes steel", "data_needed": "results: revenue"},
        {"question": "How much working capital does the business need?", "kind": "created",
         "theme": "made_up_theme", "grounding_fact": "Makes steel", "data_needed": "annual report: working capital"},
        {"question": "What is the question with no grounding fact?", "kind": "created", "theme": "other",
         "data_needed": "results: revenue"},
        {"question": "What drives Acme Steel's volume growth?", "kind": "found", "theme": "segments",
         "source_url": "https://acme.example/about"},
        {"question": "short", "kind": "created", "grounding_fact": "x", "data_needed": "y"},
    ]}
    rows, stats = tg_questions.clean_rows(payload, "Acme Steel Industries Ltd", "ACME",
                                          _fetcher(pages))
    assert stats == {"found": 2, "found_unverified": 2, "created": 2, "dropped_ungrounded": 1,
                     "dropped_empty": 1, "dropped_duplicate": 1}
    by_question = {r["question"]: r for r in rows}
    assert by_question["What drives Acme Steel's volume growth?"]["kind"] == "found"
    assert by_question["Why is Acme Steel's margin lower than peers?"]["kind"] == "found_unverified"
    assert by_question["How did Acme Steel's order book end the quarter?"]["http_status"] == 404
    pdf = by_question["What does Acme Steel's annual report say on capex?"]
    assert pdf["kind"] == "found" and pdf["http_status"] == 200
    assert by_question["How much working capital does the business need?"]["theme"] == "other"
    assert len(rows) == 6


def test_freeze_half_freezes_every_second_row_of_each_kind_by_hash():
    rows = ([{"kind": "found", "qhash": f"f{i}"} for i in range(4)]
            + [{"kind": "created", "qhash": f"c{i}"} for i in range(3)])
    rows = [rows[5], rows[1], rows[3], rows[0], rows[6], rows[2], rows[4]]
    tg_questions.freeze_half(rows)
    found = sorted((r for r in rows if r["kind"] == "found"), key=lambda r: r["qhash"])
    created = sorted((r for r in rows if r["kind"] == "created"), key=lambda r: r["qhash"])
    assert [r["frozen"] for r in found] == [0, 1, 0, 1]
    assert [r["frozen"] for r in created] == [0, 1, 0]
    first = [(r["kind"], r["qhash"], r["frozen"]) for r in rows]
    tg_questions.freeze_half(rows)
    assert [(r["kind"], r["qhash"], r["frozen"]) for r in rows] == first


def test_load_company_then_summarise_on_a_temp_db(tmp_path):
    conn = tg_questions.connect(tmp_path / "questions.db")
    stats = tg_questions.load_company(conn, _entry(), _payload(), "test-model", _ok_page)
    assert stats["found"] == 5 and stats["found_unverified"] == 0 and stats["created"] == 15
    rows = tg_questions.summarise(conn)
    assert rows == [{"isin": "INE000A01001", "total": 20, "found": 5, "found_unverified": 0, "created": 15,
                     "frozen": 9, "themes": 6, "no_data_needed": 0, "ok": True}]
    frozen = dict(conn.execute("SELECT kind, SUM(frozen) FROM question GROUP BY kind").fetchall())
    assert frozen == {"created": 7, "found": 2}
    assert conn.execute("SELECT COUNT(*) FROM business_fact").fetchone()[0] == 1
    conn.close()


def test_read_payload_accepts_a_fenced_json_file_and_refuses_a_list(tmp_path):
    path = tmp_path / "INE000A01001.json"
    path.write_text('```json\n{"company": "Acme", "questions": []}\n```\n', encoding="utf-8")
    assert tg_questions.read_payload(path) == {"company": "Acme", "questions": []}
    path.write_text("[1, 2]", encoding="utf-8")
    assert tg_questions.read_payload(path) is None


def test_harvest_one_reads_the_json_the_runner_writes(tmp_path):
    raw = tmp_path / "questions_raw"
    raw.mkdir()
    seen = {}

    def runner(prompt, model, cwd, timeout, log_path):
        seen.update(model=model, cwd=cwd, prompt=prompt, log_path=log_path)
        (Path(cwd) / "INE000A01001.json").write_text(
            json.dumps({"company": "Acme", "questions": [{"question": "What drives volume?", "kind": "created",
                                                          "theme": "segments", "grounding_fact": "steel",
                                                          "data_needed": "results: volume"}]}), encoding="utf-8")
        return {"seconds": 1.0, "tool_calls": 2, "tokens": {"input": 10}, "log": str(log_path)}

    result = tg_questions.harvest_one(_entry(), raw, "test-model", 30, runner=runner)
    assert result["payload"]["questions"][0]["question"] == "What drives volume?"
    assert result["out_path"] == str(raw / "INE000A01001.json")
    assert result["reply"]["tool_calls"] == 2 and result["symbol"] == "ACME"
    work = raw / "work" / "INE000A01001"                    # each run has a folder of its own, removed afterwards
    assert seen["cwd"] == work and seen["model"] == "test-model" and not work.exists()
    assert seen["log_path"].parent == tmp_path / "questions_logs"   # logs sit outside anything a run can tidy
    assert (work / "INE000A01001.json").as_posix() in seen["prompt"] and "Acme Steel Industries" in seen["prompt"]
    assert (raw / "INE000A01001.json").is_file()
