"""T-048: the gap loop takes --company (KEC, BAJFINANCE, HINDALCO): config lookup, the copy SQL
for every ISIN, prompts and paths that name the company, and KEC's unchanged prompts.  No model call."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from reality_engine.gap_loop import company, loop, prepare, remote, tiers


@pytest.fixture(autouse=True)
def _back_to_kec():
    yield
    company.activate("KEC")


def _unit(sandbox: Path, qid: str, stage: str = "answer", gap: str = "") -> loop.Unit:
    items = [{"id": qid, "question": "What was the order book?", "as_of": "2026-10-19"}]
    if stage == "fix":
        return loop.Unit(id="fix-text_missing-01", stage="fix", sandbox=sandbox, items=[qid],
                         instruction=loop.fix_instruction(gap or "text_missing"), gap=gap or "text_missing")
    return loop.Unit(id="answer-01", stage="answer", sandbox=sandbox, items=items)


# --- config lookup -----------------------------------------------------------------------------

def test_config_lookup_and_default():
    assert company.current().symbol == "KEC"
    kec = company.lookup("kec")
    assert (kec.name, kec.isins, kec.bse_code, kec.db_name) == (
        "KEC International Ltd", ("INE389H01022",), "532714", "kec.db")
    assert kec.questions == "questions/KEC_QUESTIONS.jsonl"
    baj = company.lookup("BAJFINANCE")
    assert (baj.name, baj.bse_code, baj.db_name) == ("Bajaj Finance Ltd", "500034", "bajfinance.db")
    assert baj.isins == ("INE296A01032", "INE296A01024")  # both: the ISIN changed at the 2025 split
    assert baj.questions == "questions/BAJFINANCE_QUESTIONS.jsonl"
    hin = company.lookup("HINDALCO")
    assert (hin.name, hin.isins, hin.bse_code, hin.db_name) == (
        "Hindalco Industries Ltd", ("INE038A01020",), "500440", "hindalco.db")
    assert set(company.COMPANIES) == {"KEC", "BAJFINANCE", "HINDALCO"}


def test_unknown_company_stops_with_a_clear_line():
    with pytest.raises(SystemExit, match="unknown company 'NOPE'"):
        company.activate("NOPE")
    assert company.current().symbol == "KEC"  # a refused company does not replace the active one


def test_main_refuses_an_unknown_company(tmp_path, capsys):
    assert loop.main(["--sandbox", str(tmp_path), "--company", "NOPE", "--prepare-only"]) == 4
    assert "unknown company" in capsys.readouterr().err


def test_job_names_and_hp_sandboxes_follow_the_company():
    assert company.lookup("KEC").job_name == "kec_gap_loop"
    assert company.lookup("BAJFINANCE").job_name == "bajfinance_gap_loop"
    assert company.lookup("KEC").hp_sandbox == r"C:\RE\sandbox\kec_loop"
    assert company.lookup("HINDALCO").hp_sandbox == r"C:\RE\sandbox\hindalco_loop"
    company.activate("BAJFINANCE")
    assert remote.hp_sandbox() == r"C:\RE\sandbox\bajfinance_loop"


def test_only_the_question_bank_is_needed_to_answer(tmp_path):
    loop.ensure_sandbox(tmp_path, questions_required=False)  # prepare needs no question file
    with pytest.raises(SystemExit, match="question bank missing"):
        loop.ensure_sandbox(tmp_path)


# --- the copy SQL carries every ISIN -----------------------------------------------------------

def test_bajfinance_copy_sql_carries_both_isins():
    baj = company.COMPANIES["BAJFINANCE"]
    specs = {spec["table"]: spec for spec in prepare.store_copies(baj)}
    assert specs["ar_facts"]["params"] == ("INE296A01032", "INE296A01024")
    assert specs["ar_facts"]["key"] == "isin=INE296A01032,INE296A01024"
    assert specs["announcements"]["params"] == ("BAJFINANCE",)

    # run the real SELECT on a tiny store: rows of both ISINs come back, another company's do not
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE ar_facts (isin TEXT, filed_at TEXT, value REAL)")
    con.executemany("INSERT INTO ar_facts VALUES (?,?,?)", [
        ("INE296A01032", "2025-02-01", 1.0), ("INE296A01024", "2025-08-01", 2.0),
        ("INE389H01022", "2025-02-01", 3.0)])
    rows = con.execute(specs["ar_facts"]["sql"], specs["ar_facts"]["params"]).fetchall()
    assert sorted(row[0] for row in rows) == ["INE296A01024", "INE296A01032"]
    assert "isin IN (?,?)" in specs["ar_facts"]["sql"]

    duck = {spec["table"]: spec for spec in prepare.duck_copies(baj)}
    assert duck["px_bse"]["params"] == ("INE296A01032", "INE296A01024", "500034")
    assert duck["px_bse"]["sql"].count("?") == 3


def test_kec_copy_sql_is_the_same_filter_as_before():
    kec = company.COMPANIES["KEC"]
    specs = {spec["table"]: spec for spec in prepare.store_copies(kec)}
    assert specs["ar_facts"]["params"] == ("INE389H01022",)
    assert specs["ar_facts"]["key"] == "isin=INE389H01022"
    assert specs["results_filings"]["key"] == "isin=INE389H01022"
    duck = {spec["table"]: spec for spec in prepare.duck_copies(kec)}
    assert duck["px_bse"]["key"] == "isin=INE389H01022 sc_code=532714"


def test_kec_site_transcript_manifest_is_read_for_kec_only(tmp_path):
    folder = tmp_path / "raw" / "company_site_transcripts"
    folder.mkdir(parents=True)
    (folder / "_manifest.json").write_text(json.dumps([{"sha256": "abc", "title": "Call"}]), encoding="utf-8")
    company.activate("KEC")
    assert prepare._transcripts(tmp_path) == {"abc": {"sha256": "abc", "title": "Call"}}
    company.activate("BAJFINANCE")
    assert prepare._transcripts(tmp_path) == {}


# --- prompts and paths name the company and its database ----------------------------------------

def test_bajfinance_prompts_name_the_company_and_db(tmp_path):
    company.activate("BAJFINANCE")
    unit = _unit(tmp_path, "BAJFINANCE001")
    prompt = tiers.answer_prompt(unit)
    assert "Bajaj Finance Ltd" in prompt and "bajfinance.db" in prompt
    assert "BAJFINANCE001" in prompt and "kec.db" not in prompt and "KEC" not in prompt

    fix = tiers.fix_prompt(_unit(tmp_path, "BAJFINANCE001", stage="fix", gap="text_missing"))
    assert "Bajaj Finance Ltd" in fix and "bajfinance.db" in fix and "kec.db" not in fix

    brief = tiers.deepseek_brief(_unit(tmp_path, "BAJFINANCE001", stage="fix", gap="text_missing"),
                                 tmp_path / "result.json")
    assert "Close one BAJFINANCE data-gap unit" in brief and "bajfinance.db" in brief and "kec.db" not in brief

    assert "bajfinance.db" in loop.fix_instruction("unverified")
    assert "BAJFINANCE documents" in loop.fix_instruction("text_missing")


def test_hindalco_prompts_name_the_company_and_db(tmp_path):
    company.activate("HINDALCO")
    prompt = tiers.answer_prompt(_unit(tmp_path, "HINDALCO001"))
    assert "Hindalco Industries Ltd" in prompt and "hindalco.db" in prompt and "kec.db" not in prompt


def test_kec_prompts_are_unchanged(tmp_path):
    company.activate("KEC")
    prompt = tiers.answer_prompt(_unit(tmp_path, "KEC001"))
    assert "You answer questions about KEC International Ltd from prepared data." in prompt
    assert "kec.db" in prompt and '{"qid": "KEC001"' in prompt
    assert "kec.db" in loop.fix_instruction("unverified")
    assert loop.fix_instruction("text_missing").startswith("Extract the text of the KEC documents")
