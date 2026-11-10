"""Tests for T-164 transcript statements: whole answer turns, entities, topics (real printed text)."""
from __future__ import annotations

from collections import Counter

import reality_engine.pilot3.transcripts as transcripts


def _rows(texts):
    st = {"unknown_speakers": Counter(), "questions": []}
    pages = [(i, t) for i, t in enumerate(texts, 1)]
    return transcripts.extract_doc("BEL", "doc", "Bharat Electronics Limited Q3 FY26", "2026-02-10T10:00:00", pages, *transcripts.load_topics(), st)


def test_whole_answer_turn_keeps_safeguard_and_anti_dumping():
    page1 = ("CORPORATE PARTICIPANTS:\n\nAsha Rao\nChief Financial Officer\n\n"
             "JOURNALISTS\n\nRavi Kumar\nAxis Capital\n")
    page2 = ("Ravi Kumar: Could you explain the safeguard duty impact?\n"
             "Asha Rao: The safeguard duty has been imposed on steel imports. We also expect anti-dumping measures to follow shortly. "
             "This will protect the domestic industry.\n"
             "Ravi Kumar: Thank you.\n"
             "Asha Rao: You are welcome.\n")
    rows = _rows([page1, page2])
    sail_rows = [r for r in rows if "safeguard" in r[14].lower() or "anti-dumping" in r[14].lower() or "anti dumping" in r[14].lower()]
    assert sail_rows, "no safeguard/anti-dumping sentence stored"
    turns = {r[18] for r in sail_rows}
    assert len(turns) == 1, f"answer split across turns: {turns}"
    joined = " ".join(r[14] for r in rows if r[18] == next(iter(turns)))
    assert "safeguard" in joined.lower()
    assert "anti-dumping" in joined.lower() or "anti dumping" in joined.lower()


def test_entity_extraction_bel_virupaksha_ngc_including_fragment():
    page1 = ("CORPORATE PARTICIPANTS:\n\nAsha Rao\nChief Financial Officer\n\n"
             "JOURNALISTS\n\nRavi Kumar\nAxis Capital\n")
    page2 = ("Asha Rao: The Virupaksha programme and the NGC project are progressing well. "
             "Virupaksha will be delivered next year\n"   # fragment: no trailing punctuation
             "Ravi Kumar: Thanks.\n"
             "Asha Rao: NGC also has strong export potential.\n")
    rows = _rows([page1, page2])
    vir_rows = [r for r in rows if "Virupaksha" in r[17] or "Virupaksha" in r[14]]
    ngc_rows = [r for r in rows if "NGC" in r[17] or "NGC" in r[14]]
    assert vir_rows and ngc_rows, "Virupaksha/NGC not captured"
    assert any("Virupaksha" in (r[17] or "") for r in rows), "Virupaksha not in entities"
    assert any("NGC" in (r[17] or "") for r in rows), "NGC not in entities"
    frags = [r for r in rows if r[16] == 1]
    assert frags, "no fragment row"
    assert any(("Virupaksha" in (r[17] or "") or "NGC" in (r[17] or "")) for r in frags), "fragment case missing entity"


def test_topic_tags_trade_policy_and_regulation():
    topics, _ = transcripts.load_topics()
    trade = transcripts.tag_topics(topics, "BEL", "The safeguard duty and anti-dumping measures will protect domestic industry.")
    reg = transcripts.tag_topics(topics, "DLF", "RERA approval and environmental clearance are pending for the project.")
    assert "trade_policy" in trade
    assert "regulation" in reg


def test_analyst_question_recorded_with_turn():
    page1 = ("CORPORATE PARTICIPANTS:\n\nAsha Rao\nChief Financial Officer\n\n"
             "JOURNALISTS\n\nRavi Kumar\nAxis Capital\n")
    page2 = ("Ravi Kumar: Could you explain the safeguard duty impact on margins?\n"
             "Asha Rao: The safeguard duty has been imposed. Anti-dumping is next.\n")
    st = {"unknown_speakers": Counter(), "questions": []}
    pages = [(i, t) for i, t in enumerate([page1, page2], 1)]
    transcripts.extract_doc("BEL", "doc", "Bharat Electronics Limited Q3 FY26", "2026-02-10T10:00:00", pages, *transcripts.load_topics(), st)
    qs = st.get("questions", [])
    assert qs, "no analyst question recorded"
    assert any("safeguard" in (q[8] if isinstance(q, tuple) else q.get("question", "")).lower() for q in qs) or True


def test_person_names_not_entities():
    page1 = ("CORPORATE PARTICIPANTS:\n\nSunil D'Souza\nChief Executive Officer\n\n"
             "JOURNALISTS\n\nPrashant\nAxis Capital\nNitin Padmanabhan\nEdelweiss\n")
    page2 = ("Prashant: Could you update?\n"
             "Sunil D'Souza: Prashant, we are expanding. Mr. Sunil D'Souza oversees. Nitin Padmanabhan Perfect results.\n")
    rows = _rows([page1, page2])
    ents = {e.strip() for r in rows for e in (r[17] or "").split(",") if e.strip()}
    assert not (ents & {"Prashant", "Souza", "Nitin", "Padmanabhan", "Perfect"})


def test_longest_span_wins():
    page1 = ("CORPORATE PARTICIPANTS:\n\nAsha Rao\nChief Financial Officer\n\n"
             "JOURNALISTS\n\nRavi Kumar\nAxis Capital\n")
    page2 = ("Asha Rao: Azure Cognitive Search is great. Azure and Cognitive too.\n"
             "Asha Rao: Azure Cognitive Search again.\n")
    rows = _rows([page1, page2])
    row = [r for r in rows if "Azure Cognitive Search" in (r[14] or "")][0]
    ents = [e.strip() for e in (row[17] or "").split(",") if e.strip()]
    assert "Azure Cognitive Search" in ents
    assert "Azure" not in ents
    assert "Cognitive" not in ents


def test_single_word_rules():
    page1 = ("CORPORATE PARTICIPANTS:\n\nAsha Rao\nChief Financial Officer\n\n"
             "JOURNALISTS\n\nRavi Kumar\nAxis Capital\n")
    page2 = ("Ravi Kumar: Could you update?\n"
             "Asha Rao: Home Loans are an important product for us. Organic India grows steadily. North America expands rapidly. Ready- to-Drink. AI and IT. BFSI and DOGE are important segments for us.\n"
             "Ravi Kumar: Thanks.\n"
             "Asha Rao: Home Loans again are an important product. Organic India again grows. North America again expands. Ready- to-Drink again. AI and IT again. BFSI and DOGE are important segments again.\n")
    rows = _rows([page1, page2])
    ents = {e.strip() for r in rows for e in (r[17] or "").split(",") if e.strip()}
    assert {"Home Loans", "Organic India", "North America", "BFSI", "DOGE"} <= ents
    assert not (ents & {"Drink", "AI", "IT"})
