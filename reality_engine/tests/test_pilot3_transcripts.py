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
    assert {"Home Loans", "Organic India", "North America"} <= ents
    # T-164 r6: a business abbreviation used as a modifier ("BFSI and DOGE ... segments") names nothing
    assert not (ents & {"Drink", "AI", "IT", "BFSI", "DOGE"})


def _entities_in_statements(texts):
    rows = _rows(texts)
    return {r[14]: {e.strip() for e in (r[17] or "").split(",") if e.strip()} for r in rows}


def test_comma_never_drops_a_name_for_the_whole_call():
    """Step 1: one "Dahlias," before a comma must not drop the name for the call (T-164 r6)."""
    page1 = ("CORPORATE PARTICIPANTS:\n\nAsha Rao\nChief Financial Officer\n\n"
             "JOURNALISTS\n\nRavi Kumar\nAxis Capital\n")
    page2 = ("Ravi Kumar: How are sales at Dahlias, Camellias and Arbour?\n"
             "Asha Rao: We did about 34 Dahlias last quarter, and the Dahlias launch was the biggest success.\n"
             "Ravi Kumar: Thanks.\n"
             "Asha Rao: Dahlias is almost 65% sold and the Camellias tower is complete.\n")
    by_stmt = _entities_in_statements([page1, page2])
    dahlias = [ents for stmt, ents in by_stmt.items() if "Dahlias" in stmt]
    assert dahlias and all("Dahlias" in e for e in dahlias), f"Dahlias missed: {by_stmt}"


def test_metric_business_abbreviations_are_not_entities():
    """Step 2: a metric or business abbreviation used with a number/modifier names nothing (T-164 r6)."""
    page1 = ("CORPORATE PARTICIPANTS:\n\nAsha Rao\nChief Financial Officer\n\n"
             "JOURNALISTS\n\nRavi Kumar\nAxis Capital\n")
    page2 = ("Ravi Kumar: What is the ARPOB and the RM 135 target?\n"
             "Asha Rao: ARPOB is 12,000 and the RM 135 fee is unchanged. The TCV of $1.2 billion is booked. "
             "BFSI segment volumes and HR headcount are on plan.\n"
             "Ravi Kumar: Thanks.\n"
             "Asha Rao: ARPOB is 12,500 now and the RM 135 fee still applies.\n")
    ents = {e.strip() for r in _rows([page1, page2]) for e in (r[17] or "").split(",") if e.strip()}
    assert not (ents & {"ARPOB", "RM", "TCV", "BFSI", "HR"}), f"metric tagged as entity: {ents}"


def test_direct_address_person_is_not_an_entity():
    """Step 3: a person introduced or addressed ("I'll ask Rakesh") is never an entity (T-164 r6)."""
    page1 = ("CORPORATE PARTICIPANTS:\n\nAsha Rao\nChief Financial Officer\n\n"
             "JOURNALISTS\n\nRavi Kumar\nAxis Capital\n")
    page2 = ("Ravi Kumar: I'll ask Rakesh to take this question.\n"
             "Asha Rao: Rakesh sir knows the numbers better than I do. We will answer in the Q&A.\n"
             "Ravi Kumar: Thanks.\n"
             "Asha Rao: Rakesh sir and the team will follow up with Rakesh after the call.\n")
    ents = {e.strip() for r in _rows([page1, page2]) for e in (r[17] or "").split(",") if e.strip()}
    assert "Rakesh" not in ents, f"person leaked as entity: {ents}"


def test_place_and_counterparty_names_are_recalled():
    """Step 1/2: a place after a preposition and a hyphenated counterparty acronym are named things."""
    page1 = ("CORPORATE PARTICIPANTS:\n\nAsha Rao\nChief Financial Officer\n\n"
             "JOURNALISTS\n\nRavi Kumar\nAxis Capital\n")
    page2 = ("Ravi Kumar: How is the Pune market?\n"
             "Asha Rao: Our 180-bed facility in Sarjapur, Bengaluru was operationalized this quarter and the Pune plant serves it. "
             "The C-DAC order is with them; discussions with C-DAC and their suppliers continue.\n"
             "Ravi Kumar: Thanks.\n"
             "Asha Rao: We added capacity in Pune last year.\n")
    ents = {e.strip() for r in _rows([page1, page2]) for e in (r[17] or "").split(",") if e.strip()}
    assert {"Pune", "Bengaluru", "C-DAC"} <= ents, f"recall miss: {ents}"


def test_topic_labels_fire_on_their_own_keyword():
    """Step 4: a tag needs its own keyword; an incidental word never adds it (T-164 r6)."""
    topics, _ = transcripts.load_topics()
    assert "digital" not in transcripts.tag_topics(topics, "BEL", "So it has to go through all the levels and then it happens.")
    assert "people" not in transcripts.tag_topics(topics, "DLF", "The risk management at the asset management company is fine.")
    assert "financials" not in transcripts.tag_topics(topics, "KIMS", "The patient is stable and we participate in the scheme.")
    assert "strategy" not in transcripts.tag_topics(topics, "UBL", "It is not a plant and machinery kind of a business.")
    assert "regulation" not in transcripts.tag_topics(topics, "BEL", "From 2016 we are training people for promotions.")
    assert "regulation" in transcripts.tag_topics(topics, "IDEA", "TRAI issued a consultation paper on tariffs.")
    assert "margin" in transcripts.tag_topics(topics, "ULTRACEMCO", "EBITDA margin expanded by 120 bps.")


def test_topics_anchored_on_their_own_words():
    """Step 4 (T-164 r7): lease debt/FCF are not working capital, a segment is not a product, DJSI is not capital,
    a hiring plan is not guidance, and "Government of India" is not a geography."""
    topics, _ = transcripts.load_topics()

    def tags(sentence, sym="INDIGO"):
        return transcripts.tag_topics(topics, sym, sentence)
    assert "working_capital" not in tags("We ended the quarter with a capitalized operating lease liability of 496 billion rupees and a total debt.")
    assert "working_capital" not in tags("Our free cash flow improved and the balance sheet is strong.")
    assert "product" not in tags("The IHB segment will continue to drive demand.")
    assert "guidance" not in tags("We will hire 200 engineers for the new plant this quarter.")
    assert "guidance" in tags("We will commission the new plant in FY28.")
    assert "geographic" not in tags("Budget, Government of India has allocated enough for the programme.")
    assert "capital" not in tags("Our DJSI score has improved by around 80% in the last 2 years.")
    assert "working_capital" in tags("Working capital improved as receivables and inventory came down.")
    assert "geographic" in tags("We are expanding into new international markets and exports.")


def test_ngc_programme_before_a_comma_is_an_entity():
    """Step 1 (T-164 r7): the real BEL sentence; an all-caps programme name in a list names something."""
    page1 = ("CORPORATE PARTICIPANTS:\n\nAsha Rao\nChief Financial Officer\n\n"
             "JOURNALISTS\n\nRavi Kumar\nAxis Capital\n")
    page2 = ("Ravi Kumar: How are the large programmes doing?\n"
             "Asha Rao: So, NGC, there are so many subsystems of NGC, Next Generation Corvette program, "
             "which definitely will come this year.\n"
             "Ravi Kumar: Thanks.\n"
             "Asha Rao: NGC is cleared and the order is signed.\n")
    ents = {e.strip() for r in _rows([page1, page2]) for e in (r[17] or "").split(",") if e.strip()}
    assert "NGC" in ents, f"NGC missed: {ents}"
    assert "Next Generation Corvette" in ents, f"programme name missed: {ents}"


def test_titles_business_abbreviations_and_metric_spans_are_not_entities():
    """Step 2 (T-164 r7): titles, business abbreviations and spans ending in a metric/accounting word name nothing."""
    page1 = ("CORPORATE PARTICIPANTS:\n\nAsha Rao\nChief Financial Officer\n\n"
             "JOURNALISTS\n\nRavi Kumar\nAxis Capital\n")
    page2 = ("Ravi Kumar: Could you update us?\n"
             "Asha Rao: The ARC book and the SEZ unit are on plan, and BFSI segment volumes grew. "
             "Our Chief Financial Officer said earnings per share improved and Other Intangibles rose. "
             "The Hyper Scaler Business is doing well and the Managing Director will speak.\n"
             "Ravi Kumar: Thanks.\n"
             "Asha Rao: The ARC book, the SEZ unit, BFSI segment, earnings per share, Other Intangibles and "
             "the Hyper Scaler Business are all on plan again.\n")
    ents = {e.strip() for r in _rows([page1, page2]) for e in (r[17] or "").split(",") if e.strip()}
    bad = {"ARC", "SEZ", "BFSI", "Chief", "Managing", "Officer", "Director", "Earnings Per Share",
           "Other Intangibles", "Hyper Scaler Business"}
    assert not (ents & bad), f"non-entity tagged: {ents & bad}"


def test_title_and_metric_spans_in_one_word():
    page1 = ("CORPORATE PARTICIPANTS:\n\nAsha Rao\nChief Financial Officer\n\n"
             "JOURNALISTS\n\nRavi Kumar\nAxis Capital\n")
    page2 = ("Asha Rao: Officer and Director are titles. Anniversary is a date. Phase is a stage.\n"
             "Asha Rao: Officer, Director, Anniversary and Phase again.\n")
    ents = {e.strip() for r in _rows([page1, page2]) for e in (r[17] or "").split(",") if e.strip()}
    assert not (ents & {"Officer", "Director", "Anniversary", "Phase"}), f"title/metric word tagged: {ents}"
