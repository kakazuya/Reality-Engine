"""Synthetic unit and CLI tests for reality_engine.v2.obs_speaker (T-241)."""
from __future__ import annotations

import csv
import sqlite3
from pathlib import Path
from typing import Any

from reality_engine.v2 import obs_speaker as ospeaker

DK = "D:/RealityEngine/raw/pilot60_history/SYNTH/concall_transcript/call1.pdf"
NON_TRANSCRIPT_DK = "D:/RealityEngine/raw/pilot60_history/SYNTH/investor_presentation/deck1.pdf"


def _make_obs_db(path: Path, rows: list[dict[str, object]]) -> None:
    con = sqlite3.connect(str(path))
    con.execute(
        """
        CREATE TABLE observation (
            observation_id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            doc_key TEXT NOT NULL,
            page INTEGER NOT NULL,
            known_at TEXT NOT NULL DEFAULT '2026-11-01',
            measure TEXT NOT NULL DEFAULT 'revenue',
            printed_label TEXT NOT NULL DEFAULT '',
            value REAL,
            value_text TEXT NOT NULL DEFAULT '',
            record_type TEXT NOT NULL DEFAULT 'number',
            statement TEXT NOT NULL DEFAULT '',
            speaker TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'verified'
        )
        """
    )
    for r in rows:
        con.execute(
            """
            INSERT INTO observation
                (symbol, doc_key, page, printed_label, value, value_text, record_type, statement, speaker)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                r.get("symbol", "SYNTH"),
                r.get("doc_key", DK),
                r["page"],
                r.get("printed_label", ""),
                r.get("value"),
                r.get("value_text", ""),
                r.get("record_type", "number"),
                r.get("statement", ""),
                r.get("speaker", ""),
            ),
        )
    con.commit()
    con.close()


def _make_store_db(path: Path, pages: list[tuple[int, str]], doc_key: str = DK) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path))
    con.execute(
        "CREATE TABLE doc_page (doc_key TEXT, page INTEGER, text TEXT, PRIMARY KEY (doc_key, page))"
    )
    for pg, txt in pages:
        con.execute("INSERT INTO doc_page (doc_key, page, text) VALUES (?, ?, ?)", (doc_key, pg, txt))
    con.commit()
    con.close()


def _make_universe(path: Path, symbols: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["isin", "symbol"])
        for i, sym in enumerate(symbols, start=1):
            w.writerow([f"INE0000000{i:02d}", sym])


def test_same_page_carry_and_not_found(tmp_path: Path):
    pages = [
        (
            1,
            "Synth Corp Limited\n"
            "MANAGEMENT: MR. RAMESH IYER - MANAGING DIRECTOR\n"
            "MODERATOR: MS. ANITA RAO - ALPHA BROKING\n",
        ),
        (
            2,
            "Synth Corp Limited\nPage 2 of 6\n"
            "Moderator: Ladies and gentlemen, welcome to Synth Corp Q2 call.\n"
            "Ramesh Iyer: Revenue in Q2 grew to INR 500 crores.\n",
        ),
        (
            3,
            "Synth Corp Limited\nPage 3 of 6\n"
            "Continuing from the previous point, EBITDA margin stood at 18.5%.\n"
            "Moderator: Thank you. The next question is from the line of Pritesh Chheda from Lucky Investment.\n"
            "Pritesh Chheda: Sir, for that INR 1,500 crores revenue, what capex is planned?\n"
            "Ramesh Iyer: We plan INR 200 crores of capex.\n",
        ),
    ]
    obs_db = tmp_path / "obs.db"
    out_db = tmp_path / "out" / "obs_copy.db"
    stores_root = tmp_path / "stores"
    uni = tmp_path / "universe.csv"

    _make_universe(uni, ["SYNTH"])
    _make_store_db(stores_root / "c01" / "c01.db", pages)
    _make_obs_db(
        obs_db,
        [
            {"page": 2, "printed_label": "Revenue in Q2 grew to", "value": 500.0, "value_text": "INR 500 crores"},
            {"page": 3, "printed_label": "EBITDA margin stood at", "value": 18.5, "value_text": "18.5%"},
            {"page": 3, "printed_label": "for that", "value": 1500.0, "value_text": "INR 1,500 crores"},
            {"page": 3, "printed_label": "We plan", "value": 200.0, "value_text": "INR 200 crores"},
            {"page": 3, "printed_label": "nonexistent", "value": 999.0, "value_text": "INR 999 crores"},
            {"page": 2, "printed_label": "welcome", "value": None, "value_text": "", "record_type": "statement", "statement": "Ladies and gentlemen, welcome to Synth Corp Q2 call."},
        ],
    )

    stats = ospeaker.run(obs_db, stores_root, uni, out_db)
    assert stats["transcript_number_total"] == 5
    assert stats["transcript_number_with_speaker"] == 4

    # Original obs_db must be untouched (no speaker_role column, speakers still empty)
    orig = sqlite3.connect(str(obs_db))
    orig_cols = {r[1] for r in orig.execute("PRAGMA table_info(observation)")}
    assert "speaker_role" not in orig_cols
    assert orig.execute("SELECT COUNT(*) FROM observation WHERE speaker != ''").fetchone()[0] == 0
    orig.close()

    con = sqlite3.connect(str(out_db))
    got = con.execute(
        "SELECT observation_id, value_text, speaker, speaker_role FROM observation ORDER BY observation_id"
    ).fetchall()
    con.close()

    assert got[0][2:] == ("Ramesh Iyer", "management")
    # Carried from page 2's last turn
    assert got[1][2:] == ("Ramesh Iyer", "management")
    # Introduced by moderator as analyst
    assert got[2][2:] == ("Pritesh Chheda", "analyst")
    # Same-page management answer
    assert got[3][2:] == ("Ramesh Iyer", "management")
    # Text not found -> left empty
    assert got[4][2:] == ("", "")
    # Moderator turn
    assert got[5][2:] == ("Moderator", "moderator")


def test_ignores_headers_greetings_and_sentence_end_turns(tmp_path: Path):
    pages = [
        (
            1,
            "Acme Industries Ltd.\nPage 1 of 4\n"
            "Corporate Participants:\n"
            "V. S. Rao - CFO\n",
        ),
        (
            2,
            "Acme Industries Ltd.\nPage 2 of 4\n"
            "Moderator: Thank you. The next question is from Rohit Jain from Alpha Capital.\n"
            "Rohit Jain: Sir, thank you for taking my question.\n"
            "Thank you. Can you clarify the 2% margin drop? "
            "V. S. Rao: Yes, raw material cost rose 2%.\n",
        ),
    ]
    obs_db = tmp_path / "obs.db"
    out_db = tmp_path / "obs_copy.db"
    stores_root = tmp_path / "stores"
    uni = tmp_path / "universe.csv"

    _make_universe(uni, ["SYNTH"])
    _make_store_db(stores_root / "c01" / "c01.db", pages)
    _make_obs_db(
        obs_db,
        [
            {"page": 2, "printed_label": "clarify the", "value": 2.0, "value_text": "2%"},
            {"page": 2, "printed_label": "raw material cost rose", "value": 2.0, "value_text": "2%"},
            # Non-transcript row should be ignored
            {"doc_key": NON_TRANSCRIPT_DK, "page": 2, "printed_label": "margin", "value": 2.0, "value_text": "2%"},
        ],
    )

    ospeaker.run(obs_db, stores_root, uni, out_db)
    con = sqlite3.connect(str(out_db))
    got = con.execute("SELECT observation_id, speaker, speaker_role FROM observation ORDER BY observation_id").fetchall()
    con.close()

    # Inline "V. S. Rao:" after sentence end splits Rohit Jain's 2% from V. S. Rao's 2%
    assert got[0][1:] == ("Rohit Jain", "analyst")
    assert got[1][1:] == ("V. S. Rao", "management")
    assert got[2][1:] == ("", "")


def test_role_fallback_question_vs_answer_without_participant_list():
    pages = [
        (1, "Cover letter without participant list."),
        (
            2,
            "Kiran Mehta: What is your capacity utilization for FY26?\n"
            "Suresh Nair: Capacity utilization is at 78%.\n"
            "Unknown Person: Just joining the call.\n",
        ),
    ]
    rows = [
        (1, 2, "78%", "Capacity utilization is at", "", ""),
        (2, 2, "FY26", "capacity utilization for", "", ""),
        (3, 2, "joining", "", "Just joining the call.", ""),
    ]
    res = ospeaker.attribute_document(pages, rows)
    assert res[1] == ("Suresh Nair", "management")
    assert res[2] == ("Kiran Mehta", "analyst")
    assert res[3] == ("Unknown Person", "unknown")


def test_limit_and_existing_speaker_role_classification(tmp_path: Path):
    pages = [
        (1, "MANAGEMENT:\nDr. Neha Kulkarni - CEO\n"),
        (
            2,
            "Neha Kulkarni: Revenue reached INR 100 crores and PAT was INR 20 crores.\n",
        ),
    ]
    obs_db = tmp_path / "obs.db"
    out_db = tmp_path / "obs_copy.db"
    stores_root = tmp_path / "stores"
    uni = tmp_path / "universe.csv"
    _make_universe(uni, ["SYNTH"])
    _make_store_db(stores_root / "c01" / "c01.db", pages)
    _make_obs_db(
        obs_db,
        [
            {"page": 2, "printed_label": "Revenue reached", "value": 100.0, "value_text": "INR 100 crores"},
            {"page": 2, "printed_label": "PAT was", "value": 20.0, "value_text": "INR 20 crores"},
            {"page": 2, "record_type": "statement", "statement": "Revenue reached INR 100 crores.", "speaker": "Neha Kulkarni"},
        ],
    )

    ospeaker.run(obs_db, stores_root, uni, out_db, limit=1)
    con = sqlite3.connect(str(out_db))
    got = con.execute("SELECT observation_id, speaker, speaker_role FROM observation ORDER BY observation_id").fetchall()
    con.close()

    assert got[0][1:] == ("Neha Kulkarni", "management")
    assert got[1][1:] == ("", "")
    assert got[2][1:] == ("Neha Kulkarni", "management")


def test_roster_edge_cases_and_non_speaker_labels():
    pages = [
        (
            1,
            "Dear Sir/Madam,\nScrip Code: 500001\nSymbol: SYNTH\nSeries:EQ\n"
            "New Delhi - 110044. Tel.: +91-11-40617777\nE-mail : mail@synth.com\n",
        ),        (
            2,
            "Synth Q2 FY 25-26 Conference Call\n"
            "Management Team\n"
            "Mr. Vijay Sanghvi - Managing Director\n"
            "HOST: MR. AKHIL PAREKH - 360 ONE CAPITAL\n"
            "ACTIVE Q&A PARTICIPENTS:\n"
            "o Aman Sonthalia - A K Securities\n",
        ),
        (
            3,
            "Moderator:\n"
            "Ladies and gentlemen, welcome. Meeting Audio: clear.\n"
            "Vijay Sanghavi:\n"
            "Agriculture: solar segment grew 30%.\n"
            "Moderator: Thank you. We will take the next question from the line of Akhil Parekh from 360 ONE Capital.\n"
            "Akhil Parekh: Margin guidance is 12%?\n"
            "Aman Sonthalia: Capex is INR 50 crores?\n",
        ),
    ]
    rows = [
        (1, 3, "30%", "solar segment grew", "", ""),
        (2, 3, "12%", "Margin guidance is", "", ""),
        (3, 3, "INR 50 crores", "Capex is", "", ""),
        (4, 2, "25-26", "FY", "", ""),
    ]
    res = ospeaker.attribute_document(pages, rows)
    # Agriculture: ignored -> Vijay Sanghavi; spelled Sanghavi vs p2 Sanghvi still stays management (not moderator)
    assert res[1] == ("Vijay Sanghavi", "management")
    # Host on p2 who asks a question via Moderator intro -> analyst
    assert res[2] == ("Akhil Parekh", "analyst")
    # Active Q&A participant -> analyst (never management)
    assert res[3] == ("Aman Sonthalia", "analyst")
    # Cover-letter address on p1 must not carry onto p2 title
    assert 4 not in res


# --------------------------------------------------------------------------- T-242 statement speaker fixes


def _statement(page: int, text: str, speaker: str = "", status: str = "verified") -> dict[str, Any]:
    return {"record_type": "statement", "page": page, "statement": text, "speaker": speaker,
            "status": status, "status_reason": "", "question_context": ""}


def test_statement_speaker_carries_across_a_page_break():
    pages = [
        (1, "Satin Creditcare Network Limited\nPage 1 of 6\n"
            "MANAGEMENT: DR. HP SINGH - CHAIRMAN AND MANAGING DIRECTOR\n"
            "HP Singh: Over the last six years our RoA stayed strong.\n"),
        (2, "Satin Creditcare Network Limited\nPage 2 of 6\n"
            "Our asset quality has seen a temporary transitory increase in delinquency.\n"     # opens mid-answer
            "HP Singh: We carry provisions of INR273 crores.\n"),
    ]
    rows = [_statement(2, "Our asset quality has seen a temporary transitory increase in delinquency."),
            _statement(2, "We carry provisions of INR273 crores.")]
    stats = ospeaker.attach_statement_speakers(rows, pages, "SATIN", ["Satin Creditcare Network Limited"])
    assert rows[0]["speaker"] == "HP Singh" and rows[0]["status"] == "verified"
    assert rows[1]["speaker"] == "HP Singh" and rows[1]["status"] == "verified"
    assert stats["carried"] == 2 and stats["unverified"] == 0


def test_statement_company_name_is_kept_and_marked_unresolved():
    pages = [
        (1, "Ashoka Buildcon Limited\nPage 1 of 3\n"
            "MANAGEMENT: MR. PARESH MEHTA - CHIEF FINANCIAL OFFICER\n"
            "Paresh Mehta: PAT stood at INR620 crores, growth of 269%.\n"),
        (2, "Ashoka Buildcon Limited\nPage 2 of 3\nPAT stood at INR620 crores, growth of 269%.\n"),
        (3, "Moderator: Thank you.\nOperator: Please proceed.\nAnil Kumar: We will begin.\n"),
    ]
    rows = [_statement(1, "PAT stood at INR620 crores, growth of 269%.", speaker="Ashoka Buildcon Limited"),
            _statement(2, "PAT stood at INR620 crores, growth of 269%.", speaker="ASHOKA")]
    stats = ospeaker.attach_statement_speakers(rows, pages, "ASHOKA", ["Ashoka Buildcon Limited"])
    # a company name is not a person: never re-attributed to a nearby label, the row loses verified status
    assert rows[0]["speaker"] == "Ashoka Buildcon Limited" and rows[0]["status"] == "unverified"
    assert rows[1]["speaker"] == "ASHOKA" and rows[1]["status"] == "unverified"
    assert all(r["status_reason"].startswith("speaker_unresolved:") for r in rows)
    assert stats["carried"] == 0


def test_statement_company_name_without_any_label_is_marked_unresolved():
    pages = [(1, "Ashoka Buildcon Limited\nPage 1 of 2\nPAT stood at INR620 crores, growth of 269%.\n"),
             (2, "Moderator: Thank you.\nOperator: Please proceed.\nAnil Kumar: We will begin.\n")]
    rows = [_statement(1, "PAT stood at INR620 crores, growth of 269%.", speaker="Ashoka Buildcon Limited")]
    ospeaker.attach_statement_speakers(rows, pages, "ASHOKA", ["Ashoka Buildcon Limited"])
    assert rows[0]["speaker"] == "Ashoka Buildcon Limited" and rows[0]["status"] == "unverified"
    assert rows[0]["status_reason"].startswith("speaker_unresolved:")


def test_statement_first_name_and_initials_resolve_to_one_management_name():
    pages = [
        (1, "Synth Corp Limited\nMANAGEMENT:\n"
            "Mr. Gopal Agrawal - Chief Financial Officer\n"
            "Mr. Amit Kumar - Managing Director\n"
            "Mr. Amit Shah - Director\n"),
        (2, "Synth Corp Limited\nGopal Agrawal: Revenue grew.\nAmit Kumar: Margin held.\n"),
    ]
    rows = [_statement(2, "Revenue grew.", speaker="Gopal"),
            _statement(2, "Margin held.", speaker="AK"),
            _statement(2, "Margin held.", speaker="Amit"),
            _statement(2, "Margin held.", speaker="Management")]
    stats = ospeaker.attach_statement_speakers(rows, pages, "SYNTH", ["Synth Corp Limited"])
    assert rows[0]["speaker"] == "Gopal Agrawal" and rows[0]["status"] == "verified"
    assert rows[1]["speaker"] == "Amit Kumar" and rows[1]["status"] == "verified"
    # two management names share the first name: keep it, never guess
    assert rows[2]["speaker"] == "Amit" and rows[2]["status"] == "unverified"
    assert rows[2]["status_reason"].startswith("speaker_unresolved:")
    # generic role words ('Management', 'Company', 'Moderator') and bare designations are unverified
    assert rows[3]["speaker"] == "Management" and rows[3]["status"] == "unverified"
    assert rows[3]["status_reason"].startswith("speaker_generic:")
    assert stats["resolved"] == 2


def test_statement_short_yes_no_reply_needs_its_question():
    pages = [(2, "Moderator: Welcome.\nOperator: Please proceed.\nRavi Viswanathan: Yes, the model is similar.")]
    rows = [_statement(2, "Yes, the model is similar.", speaker="Ravi Viswanathan"),
            _statement(2, "Yes, the model is similar and we will keep it so across the year.",
                       speaker="Ravi Viswanathan")]
    ospeaker.attach_statement_speakers(rows, pages, "TVSSCS", ["TVS Supply Chain Solutions Limited"])
    assert rows[0]["status"] == "unverified"
    assert rows[0]["status_reason"].startswith("no_referent:")
    assert rows[1]["status"] == "verified"


def test_statement_without_any_label_is_marked_unverified():
    pages = [(1, "Hindustan Zinc Limited\nPage 1 of 2\nSensitivity: Public (C4)\n"),
             (2, "Hindustan Zinc Limited\nPage 2 of 2\n"
                 "Profitability was strengthened by a lower cost of production.\n"),
             (3, "Moderator: Thank you.\nOperator: Please proceed.\nAnil Kumar: We will begin.\n")]
    rows = [_statement(2, "Profitability was strengthened by a lower cost of production.")]
    ospeaker.attach_statement_speakers(rows, pages, "HINDZINC", ["Hindustan Zinc Limited"])
    assert rows[0]["speaker"] == "" and rows[0]["status"] == "unverified"
    assert rows[0]["status_reason"].startswith("speaker_unresolved: no speaker label")


def test_statement_carried_analyst_label_is_refused():
    pages = [
        (1, "Synth Corp Limited\nMANAGEMENT: MR. RAMESH IYER - MANAGING DIRECTOR\n"
            "Moderator: Thank you. The next question is from the line of Pritesh Chheda from Lucky Investment.\n"
            "Pritesh Chheda: Sir, for that INR1,500 crores revenue, what capex is planned?\n"),
        (2, "Synth Corp Limited\nPage 2 of 2\nThe capex stays at INR200 crores for the year.\n"),
    ]
    rows = [_statement(2, "The capex stays at INR200 crores for the year.")]
    ospeaker.attach_statement_speakers(rows, pages, "SYNTH", ["Synth Corp Limited"])
    assert rows[0]["speaker"] == "" and rows[0]["status"] == "unverified"



def test_question_ending_statement_is_unverified_and_rhetorical_kept():
    from reality_engine.v2 import obs_speaker as osp
    pages = [(1, "Ravi Kumar: Why? Because demand was strong. Is margin 20%?"),
             (2, "Moderator: Thank you.\nOperator: Please proceed.\nAnil Kumar: We will begin.\n")]
    rows = [{"record_type": "statement", "doc_key": "d", "page": 1, "speaker": "Ravi Kumar", "status": "verified",
             "statement": "Why? Because demand was strong."},
            {"record_type": "statement", "doc_key": "d", "page": 1, "speaker": "Ravi Kumar", "status": "verified",
             "statement": "So is the margin going to be 20%, right?"}]
    osp.attach_statement_speakers(rows, pages)
    assert "question_end" not in (rows[0].get("status_reason") or "")
    assert rows[1]["status"] == "unverified" and "question_end" in rows[1]["status_reason"]


def test_duplicate_statements_on_one_page_are_dropped():
    from reality_engine.v2 import obs_speaker as osp
    pages = [(1, "Ravi Kumar: We added two plants."),
             (2, "Moderator: Thank you.\nOperator: Please proceed.\nAnil Kumar: We will begin.\n")]
    row = {"record_type": "statement", "doc_key": "d", "page": 1, "speaker": "Ravi Kumar", "status": "verified",
           "statement": "We added two plants."}
    rows = [dict(row), dict(row, statement="We  added two plants."), {"record_type": "number", "page": 1}]
    stats = osp.attach_statement_speakers(rows, pages)
    assert len(rows) == 2 and stats["duplicates"] == 1 and rows[1]["record_type"] == "number"


def test_statement_by_an_analyst_on_the_roster_is_unverified():
    from reality_engine.v2 import obs_speaker as osp
    pages = [(1, "Synth Corp Limited\nMANAGEMENT:\nMr. Gopal Agrawal - Chief Financial Officer\n"),
             (2, "Moderator: The next question is from Keshav Garg from Alpha PMS.\n"
                 "Keshav Garg: Will the plant scale up?\nGopal Agrawal: Yes, it will scale up next year.\n")]
    rows = [{"record_type": "statement", "doc_key": "d", "page": 2, "speaker": "Keshav Garg", "status": "verified",
             "statement": "Yes, it will scale up next year."},
            {"record_type": "statement", "doc_key": "d", "page": 2, "speaker": "Gopal Agrawal", "status": "verified",
             "statement": "Yes, it will scale up next year, we said."}]
    osp.attach_statement_speakers(rows, pages)
    assert rows[0]["status"] == "unverified" and "speaker_is_analyst" in rows[0]["status_reason"]
    assert rows[1]["status"] == "verified"


def test_filing_letter_line_on_page_one_is_dropped_but_secretary_remarks_stay():
    from reality_engine.v2 import obs_speaker as osp
    pages = [(1, "Company Secretary & Compliance Officer: This is for your information and record."),
             (2, "Moderator: Thank you.\nOperator: Please proceed.\nAnil Kumar: We will begin.\n")]
    letter = {"record_type": "statement", "doc_key": "d", "page": 1, "status": "verified",
              "speaker": "Company Secretary & Compliance Officer",
              "statement": "This is for your information and record."}
    remarks = dict(letter, statement="Revenue for the quarter grew 12% and margins held at 18%.")
    late = dict(letter, page=9)
    rows = [letter, remarks, late]
    stats = osp.attach_statement_speakers(rows, pages)
    assert stats["filing_lines"] == 1 and len(rows) == 2
    assert rows[0]["statement"].startswith("Revenue") and rows[1]["page"] == 9


def test_handover_label_corrects_a_carried_manager_and_greetings_are_dropped():
    from reality_engine.v2 import obs_speaker as osp
    pages = [(1, "Synth Corp Limited\nMANAGEMENT:\nMr. Gopal Agrawal - Chief Financial Officer\n"
                 "Mr. Amit Kumar - Managing Director\n"),
             (2, "Gopal Agrawal: Good evening, everyone. Over to you, Amit.\n"
                 "Amit Kumar: Thank you, Gopal. Our order book stands at INR 5,000 crores.\n")]
    carried = {"record_type": "statement", "doc_key": "d", "page": 2, "speaker": "Gopal Agrawal",
               "status": "verified", "statement": "Our order book stands at INR 5,000 crores."}
    greeting = {"record_type": "statement", "doc_key": "d", "page": 2, "speaker": "Amit Kumar",
                "status": "verified", "statement": "Thank you, Gopal. Good evening, everyone."}
    rows = [carried, greeting]
    stats = osp.attach_statement_speakers(rows, pages)
    assert len(rows) == 1 and stats["filing_lines"] == 1
    assert rows[0]["speaker"] == "Amit Kumar" and rows[0]["speaker_model"] == "Gopal Agrawal"
    assert rows[0]["status"] == "verified"


def test_handover_to_another_person_unverifies_without_a_roster():
    from reality_engine.v2 import obs_speaker as osp
    pages = [(5, "Thank you for all your support. Over to you, Shashi.\nRevenue for FY27 will grow 20%."),
             (6, "Moderator: Thank you.\nOperator: Please proceed.\nAnil Kumar: We will begin.\n")]
    row = {"record_type": "statement", "doc_key": "d", "page": 5, "speaker": "Sampath Ravinarayanan",
           "status": "verified", "statement": "Revenue for FY27 will grow 20%."}
    nick = dict(row, speaker="Shashidhar Kumar", statement="Revenue for FY27 will grow 20%.")
    rows = [row]
    osp.attach_statement_speakers(rows, pages)
    assert rows[0]["status"] == "unverified" and "speaker_handover" in rows[0]["status_reason"]
    rows = [nick]
    osp.attach_statement_speakers(rows, pages)
    assert rows[0]["status"] == "verified"                    # "Shashi" is a nickname of the stored speaker


def test_call_logistics_passage_is_dropped():
    from reality_engine.v2.obs_speaker import greeting_only
    assert greeting_only("Thank you. I will come back into the queue.")
    assert greeting_only("That is all from my side. All the best for the coming quarters.")
    assert not greeting_only("Thank you. We will come back with capex guidance in the next quarter.")
    assert not greeting_only("I will come back into the queue. What is the order book?")


def test_thanks_before_an_answer_is_kept():
    from reality_engine.v2.obs_speaker import greeting_only
    assert not greeting_only("Thank you, Vaibhav, it is approximately INR5,400 crores for as an EPC cost of the project.")
    assert not greeting_only("Thank you very much for the support, and we see that the future is good as far as the upcoming quarters are concerned.")
    assert greeting_only("Thank you for your continued trust and support.")


def test_ckpt_0003_housekeeping_and_welcome_passages_are_dropped():
    """fy27_v3 ckpt_0003: hand-over after 'Now', closing logistics, 'good night', long welcome + uploads."""
    from reality_engine.v2.obs_speaker import greeting_only
    assert greeting_only("Now I hand it over to Mr. Nikhil Sohoni for his remarks.")
    assert greeting_only(
        "Thank you, everyone, for taking your valuable time for attending our earnings conference call. "
        "We will keep you all posted for any further updates. I request you all to kindly send in your further "
        "questions that may remain unanswered. Audio recording and the transcripts of this call will be uploaded "
        "on our website in the due course. Looking forward to host you all in the next quarter. "
        "Till then, stay healthy, stay safe.")
    assert greeting_only("Thank you, Yashashree, and thank you, everyone, for joining the call. Good night.")
    assert greeting_only(
        "Good evening, everyone, and a very warm welcome to all participants joining us today to discuss the "
        "financial and operating performance of Aavas Financiers Limited for Q2FY27 and H1FY27, along with our "
        "outlook for the business. The results and the investor presentation have been uploaded to the stock "
        "exchanges and are also available on our company website. I hope you’ve had a chance to review them. "
        "We have also uploaded an Excel fact sheet containing historical data on our website for your easy reference.")


def test_welcome_or_housekeeping_with_a_number_is_kept():
    from reality_engine.v2.obs_speaker import greeting_only
    assert not greeting_only("Thank you. Our revenue grew 12% this quarter.")
    assert not greeting_only("Now let me take you through the financial performance: revenue was Rs 450 crore")
    assert not greeting_only("Good evening, everyone. Revenue for Q2FY27 grew 12%.")
    assert not greeting_only("Audio recording of the call is available; our margin was 18%.")


def test_question_passage_keeps_answers_with_courtesy_or_tag_and_flags_questions():
    from reality_engine.v2.obs_speaker import question_passage

    # Four real management answers (multi-sentence ending with a tag/courtesy question) must stay verified.
    assert not question_passage(
        "Keep in mind that Q3 is also a pretty strong quarter from a seasonality perspective. "
        "So again, these are BAU items from a business standpoint. "
        "So I would kind of just keep stable as your sort of base case, right?"
    )
    assert not question_passage(
        "What Aravind was clarifying was, the nature of work is precision manufacturing. "
        "So, that is the common platform we are building. "
        "Industries that are served are aerospace, consumer electronics, and so on. Is that helpful?"
    )
    assert not question_passage(
        "So in our case, what we are pursuing is a larger share of the customers' wallet that how many new project wins we are having. "
        "And with those project wins with us, we are fairly confident that we'll sustain the volumes. "
        "Am I able to answer your question?"
    )
    assert not question_passage(
        "One is low-margin deals. The others are also non-strategic deals where we didn't see any further opportunity to grow. "
        "Now exact numbers, we can't obviously give, but it is around that figure. What was your second question, Dipesh?"
    )
    # Tag/courtesy last sentence must not count towards (b) even when an earlier sentence also asks a question.
    assert not question_passage(
        "Why did margins move? We saw seasonal mix benefits. And cost savings helped too. Does that answer your question?"
    )
    assert not question_passage(
        "Why did margins move? Because volume grew. Everything else stayed flat, isn't it?"
    )
    assert not question_passage(
        "Why did margins move? Because volume grew. Everything else stayed flat, no?"
    )

    # Real questions must stay unverified: <=2 sentences ending in '?', and >= half of >=3 sentences ending in '?'.
    assert question_passage("But how do we mitigate the risk?")
    assert question_passage("Gopal, you want to take up, saying high ROCE?")
    assert question_passage("Sir, on margins. What is the outlook? And will capex rise?")


def test_confirmation_question_and_good_night():
    from reality_engine.v2.obs_speaker import greeting_only, question_passage
    assert question_passage("Sir, the order book is 5,000 crores. And margin guidance stays 18%. Is that correct?")
    assert not question_passage("So margins stay at 18%. Capex is 500 crores. Does that answer your question?")
    assert greeting_only("Thank you, everyone. Have a good night.")
    assert not greeting_only("Have a good night. Our order book is 5,000 crores.")


def test_r2_regrade_tag_tails_and_question_context():
    """fy27_v3 r2 re-grade (25 Nov): 6 wrong demotions of 40 (3 question_end tag tails, 3 no_referent)."""
    from reality_engine.v2.obs_speaker import question_passage
    assert not question_passage("The order book stands at around INR610 crores as of the quarter end, right?")
    assert not question_passage("Okay? So the CAPEX for the new plant will be largely funded from internal accruals, right?")
    assert question_passage("So margins are 18%, right?")                         # short: still a question
    assert question_passage("We understand the plant runs at 70% utilisation now. Is that correct?")
    assert question_passage("What is the capex plan for FY27?")


# --------------------------------------- T-242 question_context fill from the printed analyst question

_ROSTER = "Synth Corp Limited\nPage 1 of 3\nMANAGEMENT: MR. RAMESH IYER - MANAGING DIRECTOR\n"
_ANNOUNCE = ("Moderator: Thank you. The next question is from the line of Pritesh Chheda from Lucky Investment.\n")
_QUESTION = "Sir, for that INR1,500 crores revenue, what capex is planned?"
_ANSWER = "We plan INR200 crores of capex for the year."


def test_question_context_filled_from_the_analyst_turn_on_the_same_page():
    pages = [
        (1, _ROSTER),
        (2, "Synth Corp Limited\nPage 2 of 3\n" + _ANNOUNCE
            + f"Pritesh Chheda: {_QUESTION}\n{_ANSWER}\n"),          # unlabelled answer, as mid-call prose
    ]
    rows = [dict(_statement(2, _ANSWER), speaker="Ramesh Iyer")]
    stats = ospeaker.attach_statement_speakers(rows, pages, "SYNTH", ["Synth Corp Limited"])
    assert rows[0]["question_context"] == f"Q (Pritesh Chheda): {_QUESTION}"
    assert stats["question_filled"] == 1


def test_question_context_filled_from_the_analyst_turn_on_the_previous_page():
    pages = [
        (1, _ROSTER),
        (2, "Synth Corp Limited\nPage 2 of 3\n" + _ANNOUNCE
            + "Pritesh Chheda: How much capex is planned for FY27?"),
        (3, "Synth Corp Limited\nPage 3 of 3\nThe capex stays at INR200 crores for the year.\n"),
    ]
    rows = [dict(_statement(3, "The capex stays at INR200 crores for the year."), speaker="Ramesh Iyer")]
    stats = ospeaker.attach_statement_speakers(rows, pages, "SYNTH", ["Synth Corp Limited"])
    assert rows[0]["question_context"] == "Q (Pritesh Chheda): How much capex is planned for FY27?"
    assert stats["question_filled"] == 1


def test_question_context_empty_in_opening_remarks():
    # An unlisted speaker's opening remarks carry a question cue but no analyst has been given the floor yet.
    pages = [(1, "Synth Corp Limited\nPage 1 of 3\n"
                 "Mr. Anil Kumar: Can everyone hear me? This is our founder speaking. We had a good year."),
             (2, "Moderator: Thank you.\nOperator: Please proceed.\n")]
    rows = [dict(_statement(1, "We had a good year."), speaker="Anil Kumar")]
    stats = ospeaker.attach_statement_speakers(rows, pages, "SYNTH", ["Synth Corp Limited"])
    assert rows[0]["question_context"] == ""
    assert stats["question_filled"] == 0


def test_question_context_empty_when_a_management_label_intervenes():
    # The passage sits in the CFO's turn; the turn before his is another manager's answer, not a question.
    pages = [
        (1, "Synth Corp Limited\nPage 1 of 3\nMANAGEMENT:\n"
            "Mr. Ramesh Iyer - Managing Director\nMr. Anil Kumar - Chief Financial Officer\n"),
        (2, "Synth Corp Limited\nPage 2 of 3\n" + _ANNOUNCE
            + f"Pritesh Chheda: {_QUESTION}\nRamesh Iyer: {_ANSWER}\n"
            + "Anil Kumar: The balance is spread over the next two quarters.\n"),
    ]
    rows = [dict(_statement(2, "The balance is spread over the next two quarters."), speaker="Anil Kumar")]
    stats = ospeaker.attach_statement_speakers(rows, pages, "SYNTH", ["Synth Corp Limited"])
    assert rows[0]["question_context"] == ""
    assert stats["question_filled"] == 0


def test_question_context_never_replaces_the_models_question():
    pages = [
        (1, _ROSTER),
        (2, "Synth Corp Limited\nPage 2 of 3\n" + _ANNOUNCE
            + f"Pritesh Chheda: {_QUESTION}\n{_ANSWER}\n"),
    ]
    rows = [dict(_statement(2, _ANSWER), speaker="Ramesh Iyer", question_context="capex plan for FY27")]
    stats = ospeaker.attach_statement_speakers(rows, pages, "SYNTH", ["Synth Corp Limited"])
    assert rows[0]["question_context"] == "capex plan for FY27"
    assert stats["question_filled"] == 0


# --------------------------------------- T-242 pleasantries, praise, defer/hand-over and generic speakers


def test_thanks_welcome_praise_and_defer_are_dropped_with_ligature_normalisation():
    from reality_engine.v2.obs_speaker import greeting_only

    assert greeting_only("Thank you, Surajit and welcome to all the participants for the Q2 earnings call.")
    assert greeting_only("Very \ufb01ne ques\u019fon, Ashok.")
    assert greeting_only("That is a pertinent question.")
    assert greeting_only("Yes, I think that's a really great question, sir.")
    assert greeting_only(
        "On the second part, maybe I'll defer to Sandhya or Anesh on that, insurance sitting inside a listed company."
    )
    assert greeting_only("Let me hand over to our CFO for the financial highlights.")
    assert greeting_only("Sandhya will answer that.")
    assert greeting_only("Arjun will take that question.")
    assert greeting_only("On the ROE question, I'll request Nilesh to respond.")

    # Counter-tests: substantive clauses or figures stay
    assert not greeting_only("Thank you. Our revenue grew 12% to Rs 500 crore")
    assert not greeting_only("I'll defer to Sandhya; but on margins, we expect 14% next year")
    assert not greeting_only("Good question, but margins fell this quarter.")
    assert not greeting_only("Our balance sheet is strong enough to take that forward.")
    assert not greeting_only("We will take this call as and when it appears.")
    assert not greeting_only("We have pre-poned the date of handing over to the client.")


def test_closing_remarks_and_deferrals_are_dropped():
    """T-242 (25 Nov): figure-free closing remarks and after-call deferrals carry no statement."""
    from reality_engine.v2.obs_speaker import greeting_only

    # KTKBANK closing remarks (regrade_tx394_r4 #56): a recovery list, then confidence/team/assurance platitudes.
    assert greeting_only(
        "liabilities, assets, guidance I had already given, continuous efforts for recovery, continuous effort "
        "for slippage improvement, continuous effort for recovery under NPA as well as technically written off "
        "account and improving the other income through third-party products, all these products, through all "
        "these sources, bank is quite confident. With my team, I am able to drive this business forward. That "
        "is an assurance from my side. Thank you very much. Thank you one and all.")
    # ANTHEM closing remarks (audit_txfy27 #10): a closing thank-you plus generic governance platitudes.
    assert greeting_only(
        "Thank you everybody. Once again, it was very nice talking to all of you. As we have said before, Anthem "
        "endeavors to be totally transparent, be accurate, and continues to be well-governed. This is something "
        "that we are very mindful of and we will continue to do that.")
    # ELLEN (tx394_ckpt7 #17): a pure after-call deferral.
    assert greeting_only("Regarding your question on FY23, maybe we'll be able to get back to you post this call.")
    assert greeting_only("We wish you all a good evening.")
    assert greeting_only("We look forward to interacting again next quarter.")
    assert greeting_only("Please reach out to our investor relations team for any further queries.")
    assert greeting_only("We can take this offline.")


def test_closing_or_deferral_with_a_figure_or_substance_is_kept():
    from reality_engine.v2.obs_speaker import greeting_only

    assert not greeting_only("We will get back to growth of 15%.")
    assert not greeting_only("Thank you. Our order book is strong.")
    assert not greeting_only("Thank you. Guidance for the year is unchanged.")
    assert not greeting_only("Thank you. We expect margins to expand next year.")
    assert not greeting_only("Thank you. We will continue to invest in capacity.")
    assert not greeting_only("Thank you for the question, Mr. Jehan. Yes, that could be the ballpark where you "
                             "could see about Rs. 80 Crores this year and Rs. 80 Crores next year.")
    # ICICIGI (audit_txfy27 #17): closing pleasantries wrapping an outlook; the "But ..." clause keeps it.
    assert not greeting_only(
        "Thank you so much for joining in. We look forward to the new financials with renewed hope. We have "
        "definitely as a team been excited as to how we have been able to close H2 over H1 and more so Q4 over "
        "the rest of it. We are positive in terms of how things can work out for General Insurance industry at "
        "large and with the reforms that the regulator has put in place. But at the same time, we hope that the "
        "world moves in a much more peaceful manner in times to come.")


def test_closing_deferral_row_is_dropped_by_attach_statement_speakers():
    deferral = "Regarding your question on FY23, maybe we'll be able to get back to you post this call."
    pages = [(2, "Synth Corp Limited\nRamesh Iyer: " + deferral + "\n"),
             (3, "Moderator: Thank you.\nOperator: Please proceed.\nAnil Kumar: We will begin.\n")]
    rows = [_statement(2, deferral, speaker="Ramesh Iyer")]
    ospeaker.attach_statement_speakers(rows, pages, "SYNTH", ["Synth Corp Limited"])
    assert rows == []


def test_ligature_normalisation_never_mutates_stored_statement():
    raw_kept = "Our revenue o\u01afset cost \ufb02uctua\u019fons by 12%."
    pages = [(2, f"Synth Corp Limited\nRamesh Iyer: Very \ufb01ne ques\u019fon, Ashok.\n{raw_kept}\n"),
             (3, "Moderator: Thank you.\nOperator: Please proceed.\nAnil Kumar: We will begin.\n")]
    rows = [
        _statement(2, "Very \ufb01ne ques\u019fon, Ashok.", speaker="Ramesh Iyer"),
        _statement(2, raw_kept, speaker="Ramesh Iyer"),
    ]
    ospeaker.attach_statement_speakers(rows, pages, "SYNTH", ["Synth Corp Limited"])
    assert len(rows) == 1
    assert rows[0]["statement"] == raw_kept
    assert rows[0]["status"] == "verified"


def test_generic_empty_and_bare_designation_speakers_are_unverified():
    pages = [
        (1, "Synth Corp Limited\nMANAGEMENT:\nMr. Ramesh Iyer - Chief Financial Officer\n"),
        (2, "Synth Corp Limited\nNo turn label on this page.\n"),
        (3, "Moderator: Thank you.\nOperator: Please proceed.\nAnil Kumar: We will begin.\n"),
    ]
    rows = [
        _statement(2, "Revenue grew strongly in the core segment.", speaker=""),
        _statement(2, "Margins expanded across export geographies.", speaker="Management"),
        _statement(2, "Demand remains healthy across urban markets.", speaker="Company"),
        _statement(2, "We are opening the floor for questions.", speaker="Moderator"),
        _statement(2, "Capex will be funded via internal accruals.", speaker="CFO"),
        _statement(2, "Working capital days improved sequentially.", speaker="ED (Finance)"),
        _statement(2, "Collection efficiency remained stable.", speaker="VP. Nandakumar"),
        _statement(2, "Order inflow was healthy in the quarter.", speaker="Ramesh"),
    ]
    ospeaker.attach_statement_speakers(rows, pages, "SYNTH", ["Synth Corp Limited"])
    for idx in range(6):
        assert rows[idx]["status"] == "unverified", (idx, rows[idx])
        assert "speaker_generic" in rows[idx]["status_reason"], (idx, rows[idx])
    # Full management name (printed or resolved) stays verified
    assert rows[6]["status"] == "verified"
    assert rows[7]["speaker"] == "Ramesh Iyer" and rows[7]["status"] == "verified"


# --------------------------------------- T-242 surprise audit (25 Nov): non-call docs, headings, moderator, short remarks

_CALL_HEAD = "Synth Corp Limited\nModerator: Welcome to the call.\nOperator: Please proceed.\n"
_CALL_TAIL = "Anil Kumar: We will begin.\n"


def test_a_document_without_call_turns_is_not_a_call_and_its_statements_are_unverified():
    agm = [
        (1, "PROCEEDINGS OF THE 32ND ANNUAL GENERAL MEETING OF BRILLIANT PORTFOLIOS LIMITED\n"
            "The Company Secretary welcomed the members and informed them that the Company had taken all possible steps."),
        (2, "The Shareholders were informed that the Company has appointed Mr. Ravi Jain as Chairperson."),
    ]
    assert not ospeaker.is_call_document(agm)
    statement = "The Shareholders were informed that the Company has appointed Mr. Ravi Jain as Chairperson."
    rows = [_statement(2, statement, speaker="Company Secretary")]
    stats = ospeaker.attach_statement_speakers(rows, agm, "BRIPORT", ["Brilliant Portfolios Limited"])
    assert rows[0]["status"] == "unverified"
    assert "not_a_call" in rows[0]["status_reason"]
    assert stats["not_a_call"] == 1


def test_a_real_call_with_labels_on_only_some_pages_stays_a_call():
    pages = [
        (1, _CALL_HEAD),
        (2, "Ramesh Iyer: Revenue grew 12%.\n" + _CALL_TAIL),
        (3, "Continuing from the previous page, capex is INR200 crores.\n"),
    ]
    assert ospeaker.is_call_document(pages)
    rows = [_statement(3, "Continuing from the previous page, capex is INR200 crores.", speaker="Anil Kumar")]
    ospeaker.attach_statement_speakers(rows, pages, "SYNTH", ["Synth Corp Limited"])
    assert rows[0]["status"] == "verified"
    assert "not_a_call" not in rows[0]["status_reason"]


def test_call_detection_reads_bullet_designation_and_no_colon_label_styles():
    # Canara Bank: a PDF font bullet (U+F02D) before "Mr. X - MD, Bank:" labels.
    canara = [(2, "\uf02d Moderator: \nGood afternoon, everyone.\n"
                  "\uf02d Mr. K Satyanarayana Raju – MD, Canara Bank: \nOur advances grew 10%.\n"
                  "\uf02d Moderator: \nThe next question is from the line of Anil.\n"
                  "\uf02d Mr. K Satyanarayana Raju – MD, Canara Bank: \nYes, 14%.\n")]
    assert ospeaker.is_call_document(canara)
    # Bharti Airtel: standalone names, the designation on the same line after a dash.
    bharti = [(3, "Mr. Gopal Vittal\nExecutive Vice Chairman, Bharti Airtel Limited\n"
                  "Vaidehi Sharma – Moderator\nGood afternoon, ladies and gentlemen.\n"
                  "Gopal Vittal – Executive Vice Chairman, Bharti Airtel Limited\nThank you, Vaidehi.\n")]
    assert ospeaker.is_call_document(bharti)
    # A deck typed as a transcript has only unique slide headings and financial labels, never 3 call turns.
    deck = [(1, "KEY HIGHLIGHTS\n"), (2, "Profit After Tax:\nRs 697 Lakhs\n"),
            (3, "Revenue from Operations:\nRs 11,767 Lakhs\n")]
    assert not ospeaker.is_call_document(deck)


def test_a_slide_or_table_heading_is_never_a_speaker():
    assert not ospeaker.is_person_speaker("Profit After Tax")
    assert not ospeaker.is_person_speaker("Revenue from Operations")
    assert not ospeaker.is_person_speaker("Segment 1")
    assert ospeaker.is_person_speaker("Ramesh Iyer") and ospeaker.is_person_speaker("Pat Cummings")
    pages = [(1, _CALL_HEAD), (2, "Profit After Tax: New customer acquisition - order book of Rs.12,716 Lakhs.\n" + _CALL_TAIL)]
    rows = [_statement(2, "New customer acquisition - order book of Rs.12,716 Lakhs.", speaker="Profit After Tax")]
    stats = ospeaker.attach_statement_speakers(rows, pages, "AFFORDABLE", ["Affordable Robotic Limited"])
    assert rows[0]["speaker"] == "" and rows[0]["status"] == "unverified"
    assert "speaker_not_a_person" in rows[0]["status_reason"]
    assert stats["not_a_person"] == 1


def test_a_moderator_speaker_is_never_a_management_statement():
    pages = [(1, _CALL_HEAD), (2, "Moderator: This company was incorporated in 2001 and makes biopharmaceutical products.\n"
                                  + _CALL_TAIL)]
    statement = "This company was incorporated in 2001 and makes biopharmaceutical products."
    rows = [_statement(2, statement, speaker="Moderator")]
    stats = ospeaker.attach_statement_speakers(rows, pages, "BIOCON", ["Biocon Limited"])
    assert rows[0]["status"] == "unverified" and "speaker_moderator" in rows[0]["status_reason"]
    assert stats["moderator"] == 1
    # A named moderator from the roster is the moderator too.
    named = [(1, "Synth Corp Limited\nModerator: Ms. Anita Rao - Alpha Broking\nMANAGEMENT:\n"
                 "Mr. Ramesh Iyer - Managing Director\n"),
             (2, "Anita Rao: Biocon makes biopharmaceutical products and insulins.\n")] + [(3, _CALL_TAIL)]
    rows = [_statement(2, "Biocon makes biopharmaceutical products and insulins.", speaker="Anita Rao")]
    ospeaker.attach_statement_speakers(rows, named, "SYNTH", ["Synth Corp Limited"])
    assert rows[0]["status"] == "unverified" and "speaker_moderator" in rows[0]["status_reason"]


def test_short_content_free_remarks_are_dropped():
    for remark in ("We have done well.", "That's a good point.", "Kedar, I think his question was on products.",
                   "So that's a meaningful swing.", "That is the reason."):
        pages = [(1, _CALL_HEAD + _CALL_TAIL), (2, "Ramesh Iyer: " + remark)]
        rows = [_statement(2, remark, speaker="Ramesh Iyer")]
        stats = ospeaker.attach_statement_speakers(rows, pages, "SYNTH", ["Synth Corp Limited"])
        assert rows == [], (remark, rows)
        assert stats["short_remarks"] == 1


def test_short_answer_with_a_figure_product_or_referent_stays():
    # The short-remark rule never touches a figure, a named product or a stored referent.
    assert ospeaker.short_remark_reason("Yes, 14% for the year.", "") == ""
    assert ospeaker.short_remark_reason("The new Servotech inverter is selling well.", "") == ""
    assert ospeaker.short_remark_reason(
        "That is the reason.", "Q (Rahul): What is the reason for the margin drop?") == ""
    pages = [(1, _CALL_HEAD + _CALL_TAIL), (2, "Ramesh Iyer: Yes, 14% for the year.")]
    rows = [_statement(2, "Yes, 14% for the year.", speaker="Ramesh Iyer")]
    rows[0]["question_context"] = "What was the FY27 growth?"
    ospeaker.attach_statement_speakers(rows, pages, "SYNTH", ["Synth Corp Limited"])
    assert rows and rows[0]["status"] == "verified"
