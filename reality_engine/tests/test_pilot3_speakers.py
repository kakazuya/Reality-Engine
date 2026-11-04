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


def test_moderator_introduces_the_management_team():
    text = ("Ladies and gentlemen, welcome. From Eternal's management team, we have with us today "
            "Albinder Singh Dhindsa, Akshant Goyal and Kunal Swarup.")
    assert transcripts.moderator_names(text) == ["Albinder Singh Dhindsa", "Akshant Goyal", "Kunal Swarup"]


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
