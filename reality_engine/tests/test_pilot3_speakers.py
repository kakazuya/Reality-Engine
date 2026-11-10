"""Tests for the speaker rules of the statement extractor (``reality_engine/pilot3/transcripts.py``, T-056).

Run from the repo root:
    python -m pytest reality_engine/tests/test_pilot3_speakers.py -q

The rules: a participants block names management (with titles) and the analysts/journalists; a bare name line is a
speaker mark only in a document with almost no colon marks, and only when a participant or a name repeated 3+ times
precedes real speech; and in the Q&A a name that answers after an analyst 3+ times is management.  Analysts and
journalists are never stored.
"""
from __future__ import annotations

from collections import Counter

import reality_engine.pilot3.transcripts as transcripts


def rows_of(texts: list[str]) -> list[tuple]:
    st = {"unknown_speakers": Counter()}
    pages = [(i, t) for i, t in enumerate(texts, 1)]
    return transcripts.extract_doc("INFY", "doc", "Enclosed", "2026-10-28T10:00:00", pages, [], {}, st)


def test_participants_block_names_management_and_analysts():
    page = ("Eternal Limited has filed the transcript of the call.\n"
            "Management representatives:\n\n"
            "1. Albinder Singh Dhindsa – Chief Executive Officer, Eternal Limited\n"
            "2. Akshant Goyal – Chief Financial Officer, Eternal Limited\n"
            "3. Kunal Swarup – Head, Corporate Development, Eternal Limited\n\n"
            "JOURNALISTS\n\nVijit Jain\nGoldman Sachs\n")
    mgmt, analysts, names = transcripts.participants([page])
    assert mgmt["Albinder Singh Dhindsa"] == "md"
    assert mgmt["Akshant Goyal"] == "cfo"
    assert mgmt["Kunal Swarup"] == "mgmt"
    assert "Vijit Jain" in analysts
    assert "Albinder Singh Dhindsa" in names


def test_a_document_label_in_the_block_is_not_a_participant():
    page = ("Management:\n\nAsha Rao\nChief Financial Officer\n\nInvestor Call Transcript\n\n"
            "JOURNALISTS\n\nNeha Shah\nCNBC TV18\n")
    mgmt, analysts, _names = transcripts.participants([page])
    assert "Asha Rao" in mgmt
    assert "Investor Call Transcript" not in mgmt
    assert "Neha Shah" in analysts


def test_a_legal_company_name_in_the_block_is_not_a_participant():
    """Step 3 (T-164 r8): the TATACONSUM block prints the company itself; its words must not become person
    tokens, or "Tata" would be refused as part of the real name "Tata Copper Plus"."""
    page = ("CORPORATE PARTICIPANTS:\n\nTata Consumer Products Limited\n\nSunil D'Souza\n"
            "Managing Director\n\nJOURNALISTS\n\nTata Consumer Products Limited\n\nNeha Shah\nCNBC TV18\n")
    mgmt, analysts, names = transcripts.participants([page])
    assert "Tata Consumer Products Limited" not in mgmt
    assert "Tata Consumer Products Limited" not in analysts
    assert "Sunil D'Souza" in mgmt
    assert all("Limited" not in n for n in names)


def test_a_doi_block_with_an_alone_heading_is_read():
    """Step 1 (T-164 r8): the ANANDRATHI 13.04.2022 block prints "MANAGEMENT:" alone and then "Mr. Name – Title"
    entries; the entries are management (before, only the company name line made the speaker match)."""
    page = ("MANAGEMENT: \n\n"
            "Mr. Anand Rathi - Founder & Chairman, Anand Rathi Wealth Limited \n"
            "Mr. Rakesh Rawal \u2013 Chief Executive Officer, Anand Rathi Wealth Limited\n\n"
            "MODERATOR:\nMr. Rutuja Joshi \u2013 ICICI Securities Limited\n")
    st = {"unknown_speakers": Counter(), "questions": []}
    page2 = ("Moderator: Good afternoon and welcome to the call. We will take questions now.\n"
             "Anand Rathi: Thank you, Rutuja, and very good afternoon, ladies and gentlemen.\n")
    rows = transcripts.extract_doc("ANANDRATHI", "doc", "Anand Rathi Wealth Q4 FY22", "2026-02-10T10:00:00",
                                   [(1, page), (2, page2)], [], {}, st)
    assert rows and all(r[8] in ("md", "ceo", "cfo", "coo", "chairman", "mgmt") for r in rows), \
        f"DOI-alone block not read: {[(r[7], r[8]) for r in rows]}"


def test_moderator_introduces_the_management_team():
    text = ("Ladies and gentlemen, welcome. From Eternal's management team, we have with us today "
            "Albinder Singh Dhindsa, Akshant Goyal and Kunal Swarup.")
    assert transcripts.moderator_names(text) == ["Albinder Singh Dhindsa", "Akshant Goyal", "Kunal Swarup"]


def test_doi_layout_participant_block_keeps_management_out_of_the_questions():
    """Step 3 (T-164 r7): the BEL 30.07.2025 block puts the heading on the entry's own line; the MD answers
    after a moderator interruption and must stay management, never become an analyst question."""
    page1 = ("MANAGEMENT: MR. MANOJ JAIN– CHAIRMAN AND MANAGING\n"
             "DIRECTOR – BHARAT ELECTRONICS LIMITED\n\n"
             "MR. DAMODAR BHATTAD S – DIRECTOR FINANCE AND\nCHIEF FINANCIAL OFFICER – BHARAT ELECTRONICS LIMITED\n\n"
             "MODERATOR:\nMR. HARSHIT KAPADIA – ELARA SECURITIES PRIVATE LIMITED\n")
    mgmt, _analysts, _names = transcripts.participants([page1])
    assert any(transcripts._same_person(k, "Manoj Jain") for k in mgmt), f"DOI block not read: {mgmt}"
    st = {"unknown_speakers": Counter(), "questions": []}
    page2 = ("Moderator: Ladies and gentlemen, welcome. We will take the Q&A session now.\n"
             "Management: We are ready for the questions.\n"
             "Manoj Jain: Good afternoon. The Virupaksha radar prototype is under development with DRDO.\n"
             "Moderator: Sorry to interrupt you, sir. Please check your line.\n"
             "Manoj Jain: Yes, the line is clear now.\n")
    pages = [(1, page1), (2, page2)]
    rows = transcripts.extract_doc("BEL", "doc", "Bharat Electronics Limited Q1 FY26", "2026-02-10T10:00:00",
                                   pages, [], {}, st)
    manoj = [r for r in rows if "Manoj" in r[7]]
    assert manoj and all(r[8] == "mgmt" for r in manoj), f"Manoj not management: {[(r[7], r[8]) for r in rows]}"
    assert not any("Manoj" in (q[6] or "") for q in st["questions"]), "management answer stored as a question"


def test_name_only_speaker_lines_are_read_and_analysts_are_not_stored():
    pages = [
        ("External Document © 2026 Infosys Limited 1\n\nCORPORATE PARTICIPANTS:\n\nAsha Rao\n"
         "Chief Financial Officer\n\nRavi Menon\nManaging Director\n\nJOURNALISTS\n\nNeha Shah\nCNBC TV18\n"),
        ("Asha Rao\nGood evening, everyone, and thank you for joining the call today. Our revenue grew 10%.\n\n"
         "Neha Shah\nThank you. My first question is about margins.\n\n"
         "Asha Rao\nWe expect margins of 20% for the year and we are confident about the demand.\n"),
    ]
    rows = rows_of(pages)
    assert rows, "the bare name lines of a colon-less transcript were not read"
    assert {r[7] for r in rows} == {"Asha Rao"}        # speaker
    assert {r[8] for r in rows} == {"cfo"}             # role
    assert all("question" not in r[14].lower() for r in rows)


def test_a_name_answering_after_analysts_is_management():
    page = ("Moderator: Ladies and gentlemen, welcome. We will now take questions. The first question is from "
            "the line of Ravi Kumar.\n"
            "Ravi Kumar: Thanks. My first question is about demand.\n"
            "Anil Gupta: Demand is strong and we expect 10% growth next year.\n"
            "Ravi Kumar: A second question, this time on margins.\n"
            "Anil Gupta: We expect margins of 18% for the year.\n"
            "Ravi Kumar: One more question before the end.\n"
            "Anil Gupta: We expect capital expenditure of INR500 crores.\n")
    rows = rows_of([page])
    assert {r[7] for r in rows} == {"Anil Gupta"}
    assert {r[8] for r in rows} == {"mgmt"}


def test_an_unplaceable_speaker_is_counted_and_not_stored():
    page = ("Moderator: Welcome to the call. We now take questions.\n"
            "Ravi Kumar: My question is about demand this year.\n"
            "Someone Unk: Demand is fine and we expect 10% growth next year.\n")
    st = {"unknown_speakers": Counter()}
    rows = transcripts.extract_doc("INFY", "doc", "Enclosed", "", [(1, page)], [], {}, st)
    assert not rows
    assert "Someone Unk" in st["unknown_speakers"]


# --- T-056 review, 4 Nov 2026: a page-numbered footer, and a media call with no moderator -------------------
def test_a_running_footer_with_a_changing_page_number_is_boilerplate():
    """An INFY footer prints its page number ("… Infosys Limited 3"), so the block was never boilerplate and the
    footer sat in a quote.  Digits are normalised before the repeat count."""
    head = "External Document © 2026 Infosys Limited {}"
    pages = [head.format(1) + "\n\nCORPORATE PARTICIPANTS:\n\nAsha Rao\nChief Financial Officer\n"]
    pages += [head.format(n) + "\n\nAsha Rao\nGood evening, everyone, and thank you for joining the call today. "
                                "Our revenue grew 10% this quarter.\n" for n in (2, 3, 4)]
    boiler = transcripts.boilerplate_lines(pages)
    assert "External Document © # Infosys Limited #" in boiler
    assert "Infosys Limited" not in transcripts.mask_noise(pages[1], boiler)
    rows = rows_of(pages)
    assert rows, "the colon-less caller was not read"
    assert all("Infosys Limited" not in r[15] for r in rows), "a running footer is still inside a quote"
    assert {r[7] for r in rows} == {"Asha Rao"}


def test_a_media_call_with_no_moderator_starts_the_qa_at_the_first_journalist():
    """QA_START_RX keys on the moderator, so a media call (none) stayed 'prepared' end to end; the first
    journalists/analysts participant line opens the Q&A instead."""
    page1 = ("CORPORATE PARTICIPANTS:\n\nAsha Rao\nChief Financial Officer\n\nJOURNALISTS\n\nNeha Shah\nCNBC TV18\n")
    page2 = ("Asha Rao: Good evening, everyone, and thank you for joining this media call today.\n"
             "Neha Shah: Thank you. Could you talk about the demand outlook for the year?\n"
             "Asha Rao: Demand is strong and we expect 10% growth next year.\n")
    rows = rows_of([page1, page2])
    assert {r[7] for r in rows} == {"Asha Rao"}            # the journalist's words are never stored
    assert {r[8] for r in rows} == {"cfo"}
    greeting = [r for r in rows if r[14].startswith("Good evening")]
    answer = [r for r in rows if r[14].startswith("Demand is strong")]
    assert greeting and answer
    assert greeting[0][9] == "prepared" and answer[0][9] == "qa"


# --- T-164 round 8: IR is never promoted, and an initial-led label starts a new turn ------------------------
def test_ir_title_wrapped_in_the_block_is_ir_and_its_lines_are_not_statements():
    """Step 1 (T-164 r8): the real INDIGO block prints "Ms. RICHA CHHABRA – DIRECTOR, INVESTOR \nRELATIONS".
    The wrapped title is still Investor Relations, so the speaker stays ir and the welcome/disclaimer lines
    are not management statements."""
    page1 = ("MANAGEMENT: MR. PIETER ELBERS \u2013 CHIEF EXECUTIVE OFFICER \n\n"
             "MR. GAURAV NEGI \u2013 CHIEF FINANCIAL OFFICER \n"
             "Ms. RICHA CHHABRA \u2013 DIRECTOR, INVESTOR \nRELATIONS\n\n"
             "MODERATOR:\nMR. DORWIN \u2013 INDIGO LIMITED\n")
    assert transcripts._title_role("DIRECTOR, INVESTOR") == "ir"
    mgmt, _analysts, _names = transcripts.participants([page1])
    richa = next((v for k, v in mgmt.items() if "RICHA" in k.upper()), None)
    assert richa == "ir", f"IR listed as {richa}: {mgmt}"
    st = {"unknown_speakers": Counter(), "questions": []}
    page2 = ("Operator: Good evening, ladies and gentlemen. I now turn the call over to your moderator, "
             "Ms. Richa Chhabra from the Investor Relations team of IndiGo.\n"
             "Richa Chhabra: Good evening, everyone, and thank you for joining us for the first quarter of "
             "fiscal year 2025 earnings call.\n"
             "Pieter Elbers: Our capacity grew 10% this quarter and demand is strong.\n")
    rows = transcripts.extract_doc("INDIGO", "doc", "InterGlobe Aviation Q1 FY25", "2026-02-10T10:00:00",
                                   [(1, page1), (2, page2)], [], {}, st)
    assert rows and all(r[8] in ("md", "ceo", "cfo", "coo", "chairman", "mgmt") for r in rows), \
        f"non-management statement stored: {[(r[7], r[8]) for r in rows]}"
    assert not any("Richa" in r[7] for r in rows), "IR welcome stored as a management statement"
    assert not any("Richa" in (q[6] or "") for q in st["questions"]), "IR welcome stored as a question"


def test_initial_led_speaker_label_starts_the_analyst_turn():
    """Step 1 (T-164 r8): the real EDELWEISS label "G Vivek:" begins the analyst's turn; the management answer
    that follows is separate, and the analyst's question is never stored as management's words."""
    page1 = ("CORPORATE PARTICIPANTS:\n\nAsha Rao\nChief Financial Officer\n\n"
             "JOURNALISTS\n\nG Vivek\nGS Investment\n")
    page2 = ("Moderator: Thank you. The next question is from the line of G Vivek from GS Investment. "
             "Please go ahead.\n"
             "Rashesh Shah: Our ARC business grew 20% this quarter.\n"
             "G Vivek: My query is about this new legislation which has come into the place, solvency law "
             "and other things, and will these legislation meet the fate of DRT?\n"
             "Rashesh Shah: They are starting to happen and cases will be heard from 1st April onwards.\n")
    st = {"unknown_speakers": Counter(), "questions": []}
    rows = transcripts.extract_doc("EDELWEISS", "doc", "Edelweiss Q2 FY17", "2026-02-10T10:00:00",
                                   [(1, page1), (2, page2)], [], {}, st)
    assert not any("solvency law" in (r[14] or "") for r in rows), "the analyst question continues as management"
    assert any("solvency law" in (q[8] or "") for q in st["questions"]), "the analyst question was not recorded"
    assert all(r[8] in ("md", "ceo", "cfo", "coo", "chairman", "mgmt") for r in rows)
