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
            "Moderator: Welcome to the Satin Creditcare call.\n"
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


def test_tx394_ckpt_0014_non_content_turns_are_dropped():
    """The four J turns of the 394 v3 ckpt_0014 grade plus the demo filler Wolf quoted."""
    junk = [
        # 5 GOLDIAM: a deferral to e-mail, twice.
        "So I can get back to you -- thank you again, Mr. Ankush for the question. I can get back to you on "
        "e-mail with that. I'll have the exact loss numbers not on my table currently, but I'll be able to get "
        "back on e-mail with that.",
        # 27 DEEDEV: thanks, then the floor.
        "Thank you all for joining the call. With this, I would like to open the floor for questions.",
        # 31 ZENTEC: the demo break.
        "So what I will do is I will just take a few seconds break and then I will just walk down to the products "
        "and try to show you how the products actually look and how they work.",
        "I just did some informal survey and there was a lot of interest in seeing the products in action.",
        # 42 TEXRAIL: a forward-pointer filler.
        "You will see that it does not end here.",
    ]
    for text in junk:
        assert ospeaker.greeting_only(text), text
    pages = [(1, _CALL_HEAD + _CALL_TAIL), (2, "Ramesh Iyer: " + junk[1])]
    rows = [_statement(2, junk[1], speaker="Ramesh Iyer")]
    stats = ospeaker.attach_statement_speakers(rows, pages, "SYNTH", ["Synth Corp Limited"])
    assert rows == [] and stats["content_free"] == 1


def test_a_product_demo_statement_with_substance_stays():
    # The next ZENTEC turn answered a demo by naming the forces and the feedback: content, not logistics.
    assert not ospeaker.greeting_only(
        "We have been talking to the armed forces and one of the products has been demonstrated to them and they "
        "said this is exactly what we want and nobody has been able to give it.")
    assert not ospeaker.greeting_only("Thank you. Our revenue grew 12% this quarter.")


def test_prepared_remark_period_is_anchored_to_the_call():
    """394 v3 ckpt_0014 P: "this quarter"/"the year" read alone on a prepared remark."""
    assert ospeaker.anchored_period("This quarter has been our highest ever presales.", "Q1 FY26") == "Q1 FY26"
    assert ospeaker.anchored_period("Finance costs for the year stood at 562 million.", "Q2 FY27") == "FY27"
    assert ospeaker.anchored_period("Turnover grew 74% year-on-year, half year basis.", "Q2 FY26") == ""
    assert ospeaker.anchored_period("Lower tax in previous year was due to the budget.", "Q2 FY27") == ""
    assert ospeaker.anchored_period("Lower tax in previous year, whereas this year is normal.", "Q2 FY27") == "FY27"
    assert ospeaker.anchored_period("Revenue grew 12% in Q2 FY27.", "Q2 FY27") == "Q2 FY27"
    assert ospeaker.anchored_period("This quarter was strong.", "") == ""
    pages = [(1, _CALL_HEAD + _CALL_TAIL), (2, "Ramesh Iyer: This quarter has been our highest ever presales.")]
    rows = [_statement(2, "This quarter has been our highest ever presales.", speaker="Ramesh Iyer")]
    stats = ospeaker.attach_statement_speakers(rows, pages, "SYNTH", ["Synth Corp Limited"], call_period="Q1 FY26")
    assert stats["period_anchored"] == 1
    assert rows[0]["period"] == "Q1 FY26" and rows[0]["period_kind"] == "actual"
    assert rows[0]["period_source"] == "call_period"
    # a stored question is the row's referent, so it is never a prepared remark to anchor
    rows = [_statement(2, "This quarter has been our highest ever presales.", speaker="Ramesh Iyer")]
    rows[0]["question_context"] = "Q (Rahul): How was this quarter?"
    ospeaker.attach_statement_speakers(rows, pages, "SYNTH", ["Synth Corp Limited"], call_period="Q1 FY26")
    assert not rows[0].get("period")


def test_r3_period_anchoring_explicit_cues_only_and_comparatives_never_anchor():
    """T-242 r3: a figure alone never takes the call quarter; only an explicit own-period cue anchors, a
    comparative's named period never does, and a printed call header still overrides known_at."""
    assert ospeaker.anchored_period("Compared to last year revenue grew 20%.", "Q2 FY26") == ""
    assert ospeaker.anchored_period("Machine price rose to 20 compared to last year 18.", "Q2 FY26") == ""
    assert ospeaker.anchored_period("Margins expanded versus previous year.", "Q2 FY26") == ""
    assert ospeaker.anchored_period("Shortfall in H1 FY '26 will be offset by Q3 FY 26.", "Q3 FY26") == "Q3 FY26"
    assert ospeaker.anchored_period("Execution ramps in the second half of FY26; YTD bookings are Rs 3,464 cr.",
                                    "Q2 FY26") == ""
    assert ospeaker.anchored_period("Turnover grew 74% on a half year basis.", "Q3 FY26") == ""
    assert ospeaker.anchored_period("Half year, actually nine months ended, grew 74%.", "Q3 FY26") == ""
    assert ospeaker.anchored_period("Our CASA grew last year by 10,000 crore on a YoY basis.", "Q4 FY25") == ""
    # r3 W rows: a Y-o-Y comparative's figure never takes the call quarter; a full-year figure takes its own FY.
    assert ospeaker.anchored_period(
        "On a Y-o-Y basis, NII for Q4 FY '26 stood at INR781 crores, recording an 8% Y-o-Y growth.",
        "Q4 FY26") == ""
    assert ospeaker.anchored_period(
        "EBITDA for FY '25 stood at INR437 crores, up by 20% as compared to INR363 crores in FY '24.",
        "Q4 FY25") == "FY25"
    # r3: a figure-bearing prepared remark with no own-period cue stays empty (empty beats wrong).
    assert ospeaker.anchored_period("Capex is INR 200 crore.", "Q3 FY26") == ""
    assert ospeaker.anchored_period("The results of the last quarter are uploaded.", "Q1 FY27") == ""

    # Printed header period beats a stale/later call_quarter(known_at) fallback passed as call_period.
    pages = [
        (1, "Synth Corp Limited\nQ2 & H1 FY26 Post Earnings Conference Call\n" + _CALL_HEAD + _CALL_TAIL),
        (2, "Ramesh Iyer: Compared to last year revenue grew 20%.\n"
            "This quarter our margin was 27.3%.\n"
            "Finance costs for the year stood at 562 million.\n"
            "Exports continue to drive demand.\n"
            "Capex is INR 200 crore.\n"),
    ]
    rows = [
        _statement(2, "Compared to last year revenue grew 20%.", speaker="Ramesh Iyer"),
        _statement(2, "This quarter our margin was 27.3%.", speaker="Ramesh Iyer"),
        _statement(2, "Finance costs for the year stood at 562 million.", speaker="Ramesh Iyer"),
        _statement(2, "Exports continue to drive demand.", speaker="Ramesh Iyer"),
        dict(_statement(2, "Capex is INR 200 crore.", speaker="Ramesh Iyer"),
             question_context="Q (Rahul): What is the FY28 capex?"),
    ]
    stats = ospeaker.attach_statement_speakers(rows, pages, "SYNTH", ["Synth Corp Limited"], call_period="Q3 FY26")
    assert stats["period_anchored"] == 2
    assert not rows[0].get("period")        # a comparative never anchors
    assert rows[1]["period"] == "Q2 FY26" and rows[1]["period_source"] == "call_period"
    assert rows[2]["period"] == "FY26" and rows[2]["period_source"] == "call_period"
    assert not rows[3].get("period")        # a figure alone no longer takes the call quarter
    assert not rows[4].get("period")        # has question_context -> never anchored as prepared remark
    from reality_engine.v2 import observations as obs
    assert obs.call_quarter("2025-07-10", [(1, "Synth Corp Q4 FY25 Earnings Call")]) == "Q4 FY25"


def test_r2_refusals_and_closing_wrapups_are_dropped_while_figure_keeps_them():
    """T-242 r2: figure-free refusals to quantify and closing wrap-ups drop; any figure keeps the statement."""
    for junk in (
        "I don't want to give you any futuristic number without waiting.",
        "Unfortunately, we do not calculate customers that way -- our revenue that way.",
        "We are not in a position to share the breakup.",
        "We don't give guidance on that.",
        "Thank you all for joining. With this I conclude my opening remarks.",
        "Synth Corp is progressing firmly in its version 2.0 growth phase, focusing on operational excellence, "
        "market leadership and enhancing shareholder value.",
    ):
        assert ospeaker.greeting_only(junk), junk

    for kept in (
        "I don't want to give an exact number, but margin is around 18%.",
        "We don't give guidance on that, though revenue should reach INR 500 crore.",
        "In our version 2.0 growth phase we target 20% margin and enhancing shareholder value.",
        "We do not give credit to unrated borrowers.",
    ):
        assert not ospeaker.greeting_only(kept), kept


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
        _statement(2, "Working capital days improved to 45 days.", speaker="Moderator"),
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


def test_agm_minutes_with_date_lines_signatures_and_resolution_words_are_not_a_call():
    # BRIPORT: proceedings print "Sunday, September 27, 2026 at 11:30", "Ordinary"/"Special" resolution words and
    # signature names; none is a call turn.
    minutes = [
        (1, "Sub: Proceedings of 32nd Annual General Meeting\nDate: 27.09.2026\nRef: Brilliant Portfolios Limited\n"
            "The meeting was held on Sunday, September 27, 2026 at 11:30 A.M. through Video Conferencing.\n"
            "Yours faithfully,\nAshish\nASHISH\n"),
        (2, "The Company Secretary welcomed the members and informed them that all possible steps were taken.\n"),
        (3, "Ordinary\nOrdinary\nSpecial\nOrdinary\nSpecial\n"),
        (4, "Place: New Delhi\nDate: September 27, 2026\nAshish\nCompany Secretary\n"),
    ]
    assert not ospeaker.is_call_document(minutes)
    rows = [_statement(2, "The Company Secretary welcomed the members and informed them that all possible steps "
                          "were taken.", speaker="Company Secretary")]
    stats = ospeaker.attach_statement_speakers(rows, minutes, "BRIPORT", ["Brilliant Portfolios Limited"])
    assert rows[0]["status"] == "unverified" and "not_a_call" in rows[0]["status_reason"]
    assert stats["not_a_call"] == 1


def test_auto_transcript_timestamps_count_as_call_labels():
    # Pakka: the transcript prints the timestamp before the name ("0:05 Ved Krishna:", "[1:33] Pranay Pasricha:")
    # or after it ("Sachin Srivastava 0:10"); the timestamp is metadata, the label is still a call turn.
    before = [(2, "0:05 Ved Krishna: Sachin, can you mute everyone?\n"
                  "0:20 Pranay Pasricha: Good morning, everyone.\n"
                  "0:29 Sonia Keswani: (Audio unclear)\n")]
    bracket = [(2, "[1:33] Pranay Pasricha: Good evening everyone.\n"
                   "[2:16] Satish ChamyVelumani: He is the business head.\n"
                   "[5:43] Pranay Pasricha: Thank you for watching.\n")]
    after = [(2, "Sachin Srivastava 0:10\nMove.\nPranay Pasricha 0:14\nGood evening everyone.\n"
                 "Ved Krishna 6:12\nYou're muted.\n")]
    for pages in (before, bracket, after):
        assert ospeaker.is_call_document(pages)
    # A numbered list or a date line is not a timestamp label.
    assert not ospeaker.is_call_document([(1, "1. Revenue from operations\n2. Finance costs\n3. Profit after tax\n")])


def test_role_and_acronym_turn_labels_count_as_a_call():
    # HINDCOPPER: the call prints role labels ("CS:", "CMD:", "Analyst:") rather than full names on every turn.
    hind = [(2, "CS:\nGood evening, everyone, I am the Company Secretary.\n"
                "CMD:\nLet me explain what we have planned.\n"
                "Analyst:\nWhat is the production target?\n"
                "CMD:\nWe target 3 million tons by 2030-31.\n")]
    assert ospeaker.is_call_document(hind)


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


# ------------------------------------------------ T-242 statement window: sentence snap and referent widen
#
# The page text below is quoted from the 26 Nov 394 surprise audit (audit_tx394_2/pack.jsonl, rows 6/20/26/27/29/30/37),
# with only the printed speaker label added so the synthetic page is a call.

_WINDOW_HEAD = ("Sangam (India) Limited\n13th May 2024\nPage 5 of 17\n"
                "Moderator: Welcome to the call.\nDarshil Pandya: What is the export range?\n")


def _window_row(page: int, statement: str, speaker: str = "Anurag Soni", question_context: str = "") -> dict[str, Any]:
    row = _statement(page, statement, speaker=speaker)
    row["question_context"] = question_context
    return row


def _assert_verbatim(statement: str, page_text: str) -> None:
    assert " ".join(statement.split()) in " ".join(page_text.split()), statement


def test_statement_window_widens_it_that_range_to_the_previous_sentence():
    """#27 SANGAMIND: 'It will remain in that range.' opens on 'It' and 'that range' with neither named."""
    page = _WINDOW_HEAD + (
        "Anurag Soni: So export is about 33% to 40% of our business. It will remain in that range. "
        "So whatever growth we do in the company for the coming financial year.\n")
    rows = [_window_row(1, "It will remain in that range.")]
    stats = ospeaker.attach_statement_speakers(rows, [(1, page)], "SANGAMIND", ["Sangam (India) Limited"])
    assert rows[0]["statement"] == "So export is about 33% to 40% of our business. It will remain in that range."
    assert stats["widened"] == 1 and stats["noted"] == 0
    _assert_verbatim(rows[0]["statement"], page)


def test_statement_window_widens_this_materializes_to_the_debt_sentence():
    """#6 LLOYDSME: 'as and when this materializes' - 'this' is the debt renegotiation in the sentence before."""
    page = _WINDOW_HEAD + (
        "Anurag Soni: Our consolidated net debt remains below INR20,000 crores. A significant part of this pertains "
        "to the debt acquired as part of the Chemaf acquisition, which we are actively working to renegotiate on more "
        "favourable terms which would bring our group net debt down meaningfully. We will keep investors informed as "
        "and when this materializes. To summarize, a record first half.\n")
    rows = [_window_row(1, "We will keep investors informed as and when this materializes.")]
    stats = ospeaker.attach_statement_speakers(rows, [(1, page)], "LLOYDSME", ["Lloyds Metals and Energy Limited"])
    assert rows[0]["statement"].startswith("A significant part of this pertains to the debt acquired")
    assert rows[0]["statement"].endswith("We will keep investors informed as and when this materializes.")
    assert stats["widened"] == 1
    _assert_verbatim(rows[0]["statement"], page)


def test_statement_window_widens_both_of_these_to_the_two_product_segments():
    """#20 ZENTEC: 'both of these' refers to the two product segments named in the sentence before."""
    page = _WINDOW_HEAD + (
        "Anurag Soni: We have supplied one hard kill system now to the Indian Army. So when we look at the whole "
        "scenario, the two major product segment that the world is actually really thirsting for, one is the training "
        "to upgrade their skill set, and second is the threat to neutralize the drones. So we are in the sweet "
        "intersection between both of these. And I think the patience of fellow shareholders is paying off now.\n")
    rows = [_window_row(1, "So we are in the sweet intersection between both of these.")]
    stats = ospeaker.attach_statement_speakers(rows, [(1, page)], "ZENTEC", ["Zen Technologies Limited"])
    assert rows[0]["statement"].startswith("So when we look at the whole scenario")
    assert rows[0]["statement"].endswith("So we are in the sweet intersection between both of these.")
    assert stats["widened"] == 1
    _assert_verbatim(rows[0]["statement"], page)


def test_statement_window_widens_this_increase_to_the_price_sentence():
    """#26 CAPACITE: 'this increase' is the wholesale-price increase named in the sentence before."""
    page = _WINDOW_HEAD + (
        "Anurag Soni: While significant increase in price has been witnessed for April 26 in the wholesale price "
        "index, the company, as a prudent measure, has factored INR10 crores in procurement cost in FY26. If the "
        "escalation receivable from the client matches this increase overall over the next 2 quarters, the provisions "
        "so made will be reversed. Considering the current situation, the EBITDA guidance will be in the range of "
        "15.5% to 16.5%.\n")
    rows = [_window_row(1, "If the escalation receivable from the client matches this increase overall over the next "
                           "2 quarters, the provisions so made will be reversed.")]
    stats = ospeaker.attach_statement_speakers(rows, [(1, page)], "CAPACITE", ["Capacit'e Infraprojects Limited"])
    assert rows[0]["statement"].startswith("While significant increase in price has been witnessed")
    assert stats["widened"] == 1
    _assert_verbatim(rows[0]["statement"], page)


def test_statement_window_widens_the_brand_to_the_byd_range_sentence():
    """#29 LANDMARK: 'The brand' is the BYD range named in the sentence before."""
    page = _WINDOW_HEAD + (
        "Anurag Soni: BYD closed calendar year '24 with a retail of nearly 3,500 cars. The Seal, the homologated "
        "Atto 3 and the eMAX 7 have received a strong response. The brand has an ambition to sell upwards of 10,000 "
        "units in the current calendar year. And to achieve this, they have a number of new launches planned. The "
        "first amongst them being the Sealion 7 SUV.\n")
    rows = [_window_row(1, "The brand has an ambition to sell upwards of 10,000 units in the current calendar year. "
                           "And to achieve this, they have a number of new launches planned.")]
    stats = ospeaker.attach_statement_speakers(rows, [(1, page)], "LANDMARK", ["Landmark Cars Limited"])
    assert rows[0]["statement"].startswith("The Seal, the homologated Atto 3")
    assert stats["widened"] == 1
    _assert_verbatim(rows[0]["statement"], page)


def test_statement_window_widens_those_issues_to_the_security_sentence():
    """#30 INFOBEAN: 'those issues' are the difficulty/security concerns named in the sentence before."""
    page = _WINDOW_HEAD + (
        "Anurag Soni: Both of these are technically difficult. I mean one is technically difficult and the other one "
        "is security concerns are there where companies are not willing to share their data to the AI engine because "
        "they are worried that what happens to the data? So we are debating those issues at this point in time. How "
        "much investment we have made in Gen-I? I would say we have 3 or 4 people working on that.\n")
    rows = [_window_row(1, "So we are debating those issues at this point in time. How much investment we have made "
                           "in Gen-I? I would say we have 3 or 4 people working on that.")]
    stats = ospeaker.attach_statement_speakers(rows, [(1, page)], "INFOBEAN", ["Infobeans Technologies Limited"])
    assert rows[0]["statement"].startswith("I mean one is technically difficult")
    assert stats["widened"] == 1
    _assert_verbatim(rows[0]["statement"], page)


def test_statement_window_leaves_a_page_opening_fragment_and_notes_it():
    """#37 POONAWALLA: the sentence starts on the previous page, so it is left alone and noted, never cut."""
    page = ("Poonawalla Fincorp Limited\nJanuary 16, 2026\nPage 20 of 22\n"
            "across the portfolio and you will get a firsthand sense of how individual products will be fairly solid. "
            "Abhijit Tibrewal: Got it, Arvind sir.\nModerator: Thank you.\nArvind Kapil: Yes, that is right.\n")
    statement = "across the portfolio and you will get a firsthand sense of how individual products will be fairly solid."
    rows = [_window_row(1, statement, speaker="Arvind Kapil")]
    stats = ospeaker.attach_statement_speakers(rows, [(1, page)], "POONAWALLA", ["Poonawalla Fincorp Limited"])
    assert rows[0]["statement"] == statement
    assert rows[0]["status"] == "verified"
    assert "referent_outside_window" in rows[0]["status_reason"]
    assert stats["noted"] == 1 and stats["widened"] == 0 and stats["snapped"] == 0


def test_statement_window_snaps_a_mid_sentence_start_back_to_its_sentence():
    """Rule 1: 'across the portfolio ...' cut out of a sentence is moved back to that sentence's start."""
    page = _WINDOW_HEAD + (
        "Anurag Soni: We added two plants in the first half across the portfolio and you will get a firsthand sense "
        "of how individual products will be fairly solid. That was the main driver.\n")
    rows = [_window_row(1, "across the portfolio and you will get a firsthand sense of how individual products will "
                           "be fairly solid.")]
    stats = ospeaker.attach_statement_speakers(rows, [(1, page)], "SYNTH", ["Synth Corp Limited"])
    assert rows[0]["statement"].startswith("We added two plants in the first half across the portfolio")
    assert stats["snapped"] == 1
    _assert_verbatim(rows[0]["statement"], page)


def test_statement_window_keeps_a_sentence_start_with_a_named_subject():
    page = _WINDOW_HEAD + ("Anurag Soni: Our asset quality has seen a temporary transitory increase in delinquency. "
                           "We carry provisions of INR273 crores.\n")
    statement = "Our asset quality has seen a temporary transitory increase in delinquency."
    rows = [_window_row(1, statement)]
    stats = ospeaker.attach_statement_speakers(rows, [(1, page)], "SYNTH", ["Synth Corp Limited"])
    assert rows[0]["statement"] == statement
    assert stats["snapped"] == 0 and stats["widened"] == 0 and stats["noted"] == 0


def test_statement_window_keeps_an_anaphor_resolved_by_question_context():
    page = _WINDOW_HEAD + "Anurag Soni: It will remain at the same margin.\n"
    rows = [_window_row(1, "It will remain at the same margin.",
                        question_context="Q (Rahul): What is the margin guidance for FY27?")]
    stats = ospeaker.attach_statement_speakers(rows, [(1, page)], "SYNTH", ["Synth Corp Limited"])
    assert rows[0]["statement"] == "It will remain at the same margin."
    assert stats["widened"] == 0


def test_statement_window_never_crosses_a_speaker_label():
    page = _WINDOW_HEAD + ("Darshil Pandya: The value added share is 47% of turnover.\n"
                           "Anurag Soni: It will remain in that range.\n")
    rows = [_window_row(1, "It will remain in that range.")]
    stats = ospeaker.attach_statement_speakers(rows, [(1, page)], "SYNTH", ["Synth Corp Limited"])
    assert rows[0]["statement"] == "It will remain in that range."
    assert "The value added share" not in rows[0]["statement"]
    assert stats["widened"] == 0 and stats["noted"] == 1


def test_statement_window_widens_a_connector_fragment_to_the_figure_before_it():
    """r3 #39 NITINSPIN: "So it's a gradual step-by-step increase ..." is a fragment whose 50%/95% ramp sits in
    the previous sentence, even though question_context already names the topic (the r2 window kept it)."""
    page = _WINDOW_HEAD + (
        "Anurag Soni: First of all, it is always slow and steady. So you start with 50% and then you reach the 90%, "
        "95%. So it's a gradual step-by-step increase of the productivity as well as the efficiency. So that is a "
        "step-by-step process, which happens.\n")
    rows = [_window_row(1, "So it's a gradual step-by-step increase of the productivity as well as the efficiency.",
                        question_context="Q (Rina): How does utilization ramp up?")]
    stats = ospeaker.attach_statement_speakers(rows, [(1, page)], "SYNTH", ["Synth Corp Limited"])
    assert rows[0]["statement"] == ("So you start with 50% and then you reach the 90%, 95%. So it's a gradual "
                                    "step-by-step increase of the productivity as well as the efficiency.")
    assert stats["widened"] == 1
    _assert_verbatim(rows[0]["statement"], page)


def test_statement_window_widens_when_that_to_the_full_year_capacity_sentence():
    """r3 #21 HINDZINC: "And that at the full year ..." points at the 28 KT capacity sentence before it."""
    page = _WINDOW_HEAD + (
        "Anurag Soni: So at a full capacity, when we run the next year, the plant capacity is 28 KT and this year, "
        "it was the part operations. And that at the full year, it should be around INR250 crores to INR275 crores "
        "of the EBITDA at a full capacity.\n")
    rows = [_window_row(1, "And that at the full year, it should be around INR250 crores to INR275 crores of the "
                           "EBITDA at a full capacity.",
                        question_context="zinc alloy plant EBITDA for the quarter and PAT")]
    stats = ospeaker.attach_statement_speakers(rows, [(1, page)], "SYNTH", ["Synth Corp Limited"])
    assert rows[0]["statement"].startswith("So at a full capacity, when we run the next year")
    assert stats["widened"] == 1
    _assert_verbatim(rows[0]["statement"], page)


def test_a_copied_speaker_label_is_stripped_from_the_statement_start():
    """r3 #60 BANKINDIA: the model copied "Shri <Name>, MD & CEO" into the passage; a "<Name> - CFO:" label too."""
    label = "Shri Rajneesh Karnatak, MD & CEO"
    speech = "One of the reason is the penal charges also, but otherwise NIM has come down to 2.80%."
    pages = [(1, _CALL_HEAD + _CALL_TAIL), (2, label + " \n \n " + speech + "\n")]
    rows = [dict(_statement(2, label + " \n \n " + speech, speaker=label))]
    stats = ospeaker.attach_statement_speakers(rows, pages, "SYNTH", ["Synth Corp Limited"])
    assert rows[0]["statement"] == speech
    assert stats["labels_stripped"] == 1
    assert ospeaker.strip_leading_speaker_label("Ramesh Iyer - CFO: Revenue grew 12%.", "")[0] \
        == "Revenue grew 12%."
    assert ospeaker.strip_leading_speaker_label("MR. SATISH PARAKH – MANAGING DIRECTOR.\nThe quarter was strong.",
                                                "")[0] == "The quarter was strong."
    assert ospeaker.strip_leading_speaker_label(
        "Muralidharan, Group Chief Financial Officer\nMr. Manish Bhatia, Chief Financial Officer\n"
        "The quarter was strong.", "")[0] == "The quarter was strong."
    # a passage that merely starts with a name-then-comma phrase is not a label
    kept = "Ramesh Iyer said the capex plan is unchanged."
    assert ospeaker.strip_leading_speaker_label(kept, "Ramesh Iyer")[0] == kept
    kept2 = "Yes, we grew 12% in the quarter ended March 2026\nand margins held."
    assert ospeaker.strip_leading_speaker_label(kept2, "")[0] == kept2
    # a snap can pull the printed label line into the passage; it is stripped again after the widen
    pages2 = [(1, _CALL_HEAD + _CALL_TAIL),
              (2, "Anurag Soni: Some intro. " + label + " \n \n " + speech + "\n")]
    rows2 = [dict(_statement(2, speech, speaker=label))]
    stats2 = ospeaker.attach_statement_speakers(rows2, pages2, "SYNTH", ["Synth Corp Limited"])
    assert rows2[0]["statement"] == speech
    assert stats2["labels_stripped"] == 1


# ------------------------------------------------ T-242 r4: own-period cues + heading strip guard


def test_r4_regains_own_period_cues_across_the_five_evidence_cases():
    """T-242 r4: as-on/basis period-end date, quarterly metric/this quarter's, and over-year-ago base."""
    # 1. ASHOKA: "As on 31st December 2024 ..." on a Q3 FY25 call (any printed date form) -> Q3 FY25; other date -> ""
    assert ospeaker.anchored_period(
        "As on 31st December 2024, our balance order book stands at INR16,457 crores.", "Q3 FY25") == "Q3 FY25"
    assert ospeaker.anchored_period(
        "Total debt as at 31.12.2024 stood at INR2,722 crores.", "Q3 FY25") == "Q3 FY25"
    assert ospeaker.anchored_period(
        "Balance order book as of December 31, 2024 was INR16,457 crores.", "Q3 FY25") == "Q3 FY25"
    assert ospeaker.anchored_period(
        "As on 30th September 2024, our balance order book stood at INR15,000 crores.", "Q3 FY25") == ""
    assert ospeaker.anchored_period(
        "As on 15th December 2024, our balance order book stood at INR15,000 crores.", "Q3 FY25") == ""

    # 2. HINDZINC: "lowest quarterly zinc cost ..." (even with "year-on-year" in the same sentence) -> call quarter
    assert ospeaker.anchored_period(
        "On the cost front, despite the volatile geopolitical environment, we achieved the lowest quarterly zinc cost "
        "of production, excluding royalty, since underground transition to USD851 per ton, reflecting a decline of "
        "16% year-on-year.", "Q1 FY27") == "Q1 FY27"

    # 3. POONAWALLA #18: "... basis March 2026 balance sheet" on a Q4 FY26 call -> Q4 FY26
    assert ospeaker.anchored_period(
        "With successful INR2,500 crores of capital raise, the capital adequacy ratio stands at 20.74%. "
        "This is basis the March 2026 balance sheet and the capital raise that we talked about.", "Q4 FY26") == "Q4 FY26"
    assert ospeaker.anchored_period(
        "Our debt equity ratio stood at 4.67x. This is before the capital raise of INR2,500 crores, which we did in "
        "April of 2026 through the QIP route. Post capital raise and basis March 2026 balance sheet, the proforma "
        "debt equity would stand at 3.78x.", "Q4 FY26") == "Q4 FY26"
    assert ospeaker.anchored_period(
        "This is basis December 2025 balance sheet.", "Q4 FY26") == ""

    # 4. UJJIVANSFB: "stood at Rs. 25,274 crores ... growth over December 23" (1 year or 1 quarter before end)
    assert ospeaker.anchored_period(
        "Retail deposits stood at Rs. 25,274 crores accounting for 73% of total deposits and demonstrating a 24% "
        "growth over December 23.", "Q3 FY25") == "Q3 FY25"
    assert ospeaker.anchored_period(
        "Retail deposits stood at Rs. 25,274 crores, up 5% over September 24.", "Q3 FY25") == "Q3 FY25"
    assert ospeaker.anchored_period(
        "Retail deposits stood at Rs. 25,274 crores, up 10% over June 24.", "Q3 FY25") == ""

    # 5. AEROFLEX #22: "quarterly revenue crossing INR200 crores" and "this quarter's" -> call quarter
    assert ospeaker.anchored_period(
        "We are pleased to report that our best ever results with quarterly revenue crossing INR200 crores milestone "
        "for the first time ever.", "Q2 FY27") == "Q2 FY27"
    assert ospeaker.anchored_period("This quarter's revenue crossed INR200 crores.", "Q2 FY27") == "Q2 FY27"
    # Generic or figure-free "quarterly" stays empty
    assert ospeaker.anchored_period("Turnover grew 74% on a quarterly basis.", "Q2 FY27") == ""
    assert ospeaker.anchored_period("These are monthly and quarterly fluctuations.", "Q2 FY27") == ""


def test_r4_stay_empty_cases_and_w47_remain_unchanged():
    """T-242 r4/r5: forward cues, same quarter last year, last quarter, other FY/H/Q, future dates stay empty."""
    # 1. HFCL future quarter
    assert ospeaker.anchored_period(
        "We expect to complete the acquisition during the current quarter.", "Q2 FY27") == ""
    assert ospeaker.anchored_period(
        "Quarterly revenue will cross INR 500 crore next quarter.", "Q2 FY27") == ""
    # 2. IOLCP "same quarter last year" (r6: the bound "for the quarter" figure anchors the call quarter)
    assert ospeaker.anchored_period(
        "EBITDA for the quarter rose by 19.5% year-on-year to Rs. 69.5 crores, up from Rs. 58.2 crores in the "
        "same quarter last year.", "Q1 FY26") == "Q1 FY26"
    # 3. CUB "NIM for FY26" on a Q1 call
    assert ospeaker.anchored_period("Our NIM for FY26 is 3.5%.", "Q1 FY26") == ""
    assert ospeaker.anchored_period("Expecting NIM in the range of 3.5% for FY26.", "Q1 FY26") == ""
    # 4. BPLPHARMA future milestones
    assert ospeaker.anchored_period(
        "Key milestones are commissioning of the facility in September of 2027 and validation by March 2028.",
        "Q4 FY26") == ""
    # r5: a guidance target takes its named period ("by FY28" -> FY28), never the call quarter
    assert ospeaker.anchored_period(
        "We target quarterly milestone revenue of INR 70 crores by FY28.", "Q4 FY26") == "FY28"
    # 5. BOROLTD H1 figure on a Q2 call
    assert ospeaker.anchored_period(
        "In H1 FY'26, the company recorded an operating EBITDA of INR 90.1 crores.", "Q2 FY26") == ""
    assert ospeaker.anchored_period(
        "Quarterly EBITDA in H1 FY26 was INR 45 crores.", "Q2 FY26") == ""
    # 6. KTKBANK #36 Y-o-Y comparative figure
    assert ospeaker.anchored_period(
        "On a Y-o-Y basis, NII for Q4 FY '26 stood at INR781 crores, recording an 8% Y-o-Y growth.",
        "Q4 FY26") == ""
    # 7. EMSLIMITED #43 "results of the last quarter"
    assert ospeaker.anchored_period(
        "As we have already uploaded the results of the last quarter, I am sure you are aware for which our "
        "operating income stood at Rs. 125.72 crores on stand-alone basis, which was a net increase of about 50% "
        "over the last quarter.", "Q1 FY27") == ""
    # W #47 CAPACITE stays FY25
    assert ospeaker.anchored_period(
        "EBITDA for FY '25 stood at INR437 crores, up by 20% as compared to INR363 crores in FY '24.",
        "Q4 FY25") == "FY25"


def test_r5_own_period_cue_beats_sentence_wide_blocks():
    """T-242 r5: an explicit own-period token bound to its figure wins; a comparative names the base only."""
    # ASKAUTOLTD: the comparative names the BASE of 65 crore; 103 crore is bound to "in Q1 FY25"
    assert ospeaker.anchored_period(
        "EBITDA in Q1 FY25 at Rs. 103 crore against Rs. 65 crore in the same quarter last year",
        "Q1 FY25") == "Q1 FY25"
    # TVSSCS: the own figure's Q4 FY26 wins over the sentence's other-Q base
    assert ospeaker.anchored_period(
        "Our revenue for the quarter increased from Rs. 632.8 crores in Q4 FY25 to Rs. 813.3 crores in Q4 FY26",
        "Q4 FY26") == "Q4 FY26"
    # MEDANTA: "during the quarter" is bound to the own figure; "same quarter last year" names the base
    assert ospeaker.anchored_period(
        "During the quarter, revenue grew 12.9% to INR10,513 million compared to INR8,830 million in the same "
        "quarter last year", "Q4 FY25") == "Q4 FY25"
    # AZAD: guidance takes its named target year, never empty
    assert ospeaker.anchored_period("We reaffirm our guidance of 25-30% for FY'25", "Q4 FY25") == "FY25"
    # an "this quarter" own figure after a "last quarter" base
    assert ospeaker.anchored_period("last quarter it was 23, this quarter it is 24 percent", "Q1 FY26") == "Q1 FY26"
    # ACUTAAS: the call's own Q1 FY25 wins over the sentence's other Q4 FY24
    assert ospeaker.anchored_period(
        "The full quarter impact was seen in Q1 FY'25 and Q4 FY'24 was a one-off", "Q1 FY25") == "Q1 FY25"
    # AWFIS: an actual FY24 base does not stop the guidance's own FY25 target
    assert ospeaker.anchored_period(
        "Capex spends for FY24 stood at INR142 crores while for FY25 we expect it around INR200 crores",
        "Q4 FY25") == "FY25"


def test_r5_stay_empty_cases_remain_empty():
    """T-242 r5: the four r3/r4 stay-empty cases never take the call quarter (IOLCP left the set in r6)."""
    # 1. HFCL future quarter
    assert ospeaker.anchored_period(
        "We expect to complete the acquisition during the current quarter.", "Q2 FY27") == ""
    assert ospeaker.anchored_period(
        "Quarterly revenue will cross INR 500 crore next quarter.", "Q2 FY27") == ""
    # 2. CUB "NIM for FY26" on a Q1 call (another period's figure, not the call's)
    assert ospeaker.anchored_period("Our NIM for FY26 is 3.5%.", "Q1 FY26") == ""
    assert ospeaker.anchored_period("Expecting NIM in the range of 3.5% for FY26.", "Q1 FY26") == ""
    # 3. KTKBANK #36 Y-o-Y comparative figure
    assert ospeaker.anchored_period(
        "On a Y-o-Y basis, NII for Q4 FY '26 stood at INR781 crores, recording an 8% Y-o-Y growth.",
        "Q4 FY26") == ""
    # 4. EMSLIMITED #43 "results of the last quarter"
    assert ospeaker.anchored_period(
        "As we have already uploaded the results of the last quarter, I am sure you are aware for which our "
        "operating income stood at Rs. 125.72 crores on stand-alone basis, which was a net increase of about 50% "
        "over the last quarter.", "Q1 FY27") == ""


# ------------------------------------------------ T-242 r6: four narrow period fixes


def test_r6_quarter_bound_figure_beats_same_quarter_last_year():
    """T-242 r6(1): 'for the quarter' bound to its figure beats a same-quarter-last-year comparative."""
    # IOLCP: 69.5 crore grew 19.5% this quarter; 58.2 crore is the base
    assert ospeaker.anchored_period(
        "EBITDA for the quarter rose by 19.5% year-on-year to Rs. 69.5 crores, up from Rs. 58.2 crores in the "
        "same quarter last year.", "Q1 FY26") == "Q1 FY26"
    # BLS: 891 crore is this quarter's revenue; 711 crore is the base
    assert ospeaker.anchored_period(
        "Consolidated Performance The consolidated revenue for the quarter was INR 891 crores, up 25% from "
        "INR 711 crores in the same quarter last year.", "Q1 FY27") == "Q1 FY27"
    # SOLARINDS: the bound figure precedes the guidance aside, which names no other period
    assert ospeaker.anchored_period(
        "The domestic explosives volume for the quarter grew by 16% year-on-year basis, which is in line with "
        "our annual guidance for the year '25.", "Q1 FY25") == "Q1 FY25"
    # a cue only after the forward word still never anchors (HFCL shape)
    assert ospeaker.anchored_period(
        "We expect to complete the acquisition during the current quarter.", "Q2 FY27") == ""


def test_r6_q1_of_fy27_form():
    """T-242 r6(2): 'Q1 of FY27' and 'first quarter of FY27' are named quarters."""
    assert ospeaker.anchored_period(
        "So Q1 of FY27 has been an encouraging start to the year and more importantly, the improvement that we "
        "started seeing during the second half of FY26 has continued into this quarter.", "Q1 FY27") == "Q1 FY27"
    assert ospeaker.anchored_period("Q2 of FY 27 was a strong quarter for us.", "Q2 FY27") == "Q2 FY27"
    assert ospeaker.anchored_period(
        "The first quarter of FY27 marks an encouraging start to the financial year.", "Q1 FY27") == "Q1 FY27"
    # another quarter's form is not the call quarter
    assert ospeaker.anchored_period("Q1 of FY27 was strong.", "Q3 FY27") == ""


def test_r6_named_fy_space_apostrophe_hyphen():
    """T-242 r6(3): an FY written with a space, apostrophe or hyphen is that FY, guidance included."""
    for stmt in (
        "Further, we continue to provide a guidance of 25%-30% for FY25 with improvement in our margins.",
        "Finally, we are pleased to reaffirm our guidance of 25%, 30% revenue growth for FY '25 alongside an "
        "anticipated improvement in our margin profiles.",
    ):
        assert ospeaker.anchored_period(stmt, "Q3 FY25") == "FY25"
    for form in ("FY 27", "FY'27", "FY-27"):
        assert ospeaker.anchored_period(
            f"We reiterate our guidance of 20% growth for {form}.", "Q2 FY27") == "FY27"
    # CUB's guidance-less figure on a Q1 call stays empty (r5 stay-empty kept)
    assert ospeaker.anchored_period("Expecting NIM in the range of 3.5% for FY26.", "Q1 FY26") == ""
    assert ospeaker.anchored_period("Our NIM for FY26 is 3.5%.", "Q1 FY26") == ""


def test_r6_year_and_first_half_never_anchor_the_call_quarter():
    """T-242 r6(4): 'during the year' -> call FY; 'first half of the year' -> H1 of it (empty on a Q1 call)."""
    assert ospeaker.anchored_period(
        "FY '26 was the second consecutive year of meaningful capex for the company. We deployed INR1,434 "
        "million during the year broadly in line with our INR1,450 million that we had spent in FY '25. "
        "Cumulatively, over the last two financial years, we have added approximately INR290 crores of capex, "
        "taking our gross block from INR298 crores as of March '24 to INR558 crores as of 31st March 2026, "
        "which is an 87% increase in 2 years.", "Q4 FY26") == "FY26"
    assert ospeaker.anchored_period(
        "During the first half of the year, our focus has been on profitability, cost optimization, and cash "
        "generation. These actions should start delivering somewhere in Quarter 3 and then in Quarter 4.",
        "Q2 FY26") == "H1 FY26"
    assert ospeaker.anchored_period(
        "During the first half of the year, our focus has been on profitability.", "Q1 FY26") == ""
    assert ospeaker.anchored_period(
        "During the year, the company successfully completed multiple product validations and also developed "
        "the FRP rod manufacturing line in-house, which is expected to strengthen quality control and long-term "
        "product reliability.", "Q2 FY27") == "FY27"


def test_r4_metric_heading_label_not_stripped_while_roster_and_role_strip():
    """T-242 r4: CUB 'Cost-to-income ratio:' is never stripped as a speaker label; roster/role labels still strip."""
    assert ospeaker._is_heading_label("Cost-to-income ratio")
    assert not ospeaker.is_person_speaker("Cost-to-income ratio")

    cub_stmt = "Cost-to-income ratio: Our cost-to-income ratio for FY '25 is at 47.77%."
    assert ospeaker.strip_leading_speaker_label(cub_stmt, "Cost-to-income ratio") == (cub_stmt, False)
    assert ospeaker.strip_leading_speaker_label(cub_stmt, "R. Vijay Anandh") == (cub_stmt, False)
    assert ospeaker.strip_leading_speaker_label(
        cub_stmt, "Cost-to-income ratio", known_names={"r vijay anandh"}) == (cub_stmt, False)

    # Roster speaker and role-word labels still strip
    pages = [
        (1, "City Union Bank Limited\nMANAGEMENT:\nMr. R. Vijay Anandh - Executive Director\n" + _CALL_HEAD + _CALL_TAIL),
        (2, "R. Vijay Anandh: Our NIM was 3.63%.\nAnil Kumar, Head of Treasury: Treasury income rose.\n"
            "Anita Rao, Moderator: Management reported 12% margin.\n"
            "S. Krishnan, Compliance Officer: Trading window stays closed.\n"
            + cub_stmt + "\n"),
    ]
    rows = [
        _statement(2, cub_stmt, speaker="R. Vijay Anandh"),
        _statement(2, "R. Vijay Anandh: Our NIM was 3.63%.", speaker="R. Vijay Anandh"),
        _statement(2, "Anil Kumar, Head of Treasury: Treasury income rose.", speaker="Anil Kumar"),
        _statement(2, "Anita Rao, Moderator: Management reported 12% margin.", speaker="Anita Rao"),
        _statement(2, "S. Krishnan, Compliance Officer: Trading window stays closed.", speaker="S. Krishnan"),
    ]
    stats = ospeaker.attach_statement_speakers(rows, pages, "CUB", ["City Union Bank Limited"])
    assert rows[0]["statement"] == cub_stmt
    assert rows[1]["statement"] == "Our NIM was 3.63%."
    assert rows[2]["statement"] == "Treasury income rose."
    assert rows[3]["statement"] == "Management reported 12% margin."
    assert rows[4]["statement"] == "Trading window stays closed."
    assert stats["labels_stripped"] == 4


# ------------------------------------------------ T-242 r7: explicit own-period cues bound to a figure

# Each fixture is the statement as the closed r3 copy prints it (doc: page), with the printed call
# period read from the transcript header; the r6 output is in the docstring.


def test_r7_yasho_planned_outlay_for_fy27_anchors():
    """YASHO p4, printed call Q2 FY27: r6 emptied r3's FY27; a plan word + "for FY27" names the year."""
    assert ospeaker.anchored_period(
        "On capital expenditure, the planned outlay for FY27 stands at INR250 crores.", "Q2 FY27") == "FY27"
    # the call's own year without a plan/guidance word stays empty (CUB, r5 keep-case)
    assert ospeaker.anchored_period("Our NIM for FY26 is 3.5%.", "Q1 FY26") == ""
    # a target year is anchored even when it is not the call's own FY
    assert ospeaker.anchored_period("We have planned a capex of INR250 crores for FY28.", "Q2 FY27") == "FY28"
    # an annual reporting phrase names the year even when it is the call's own FY
    assert ospeaker.anchored_period(
        "For the full year FY'25 revenue from operations reached Rs. 231.34 crore, a 70.84% increase over FY'24.",
        "Q4 FY25") == "FY25"


def test_r7_psb_this_time_and_for_the_quarter_beat_the_trailing_forward():
    """PSB p4, printed call Q1 FY27: "this time ... Rs.207 crores ... for the quarter ... will be annualised"."""
    assert ospeaker.anchored_period(
        "Slippages are broadly in line with the previous quarters, this time these slippages are at Rs.207 crores "
        "and the slippage ratio is at 0.18% for the quarter, so overall it will be annualised around 0.70%.",
        "Q1 FY27") == "Q1 FY27"


def test_r7_triveni_this_quarter_after_you_will_note_anchors():
    """TRIVENI p6, printed call Q4 FY26: the forward "will note" opens the sentence, the pricing is this quarter's."""
    assert ospeaker.anchored_period(
        "And you will note that with an average sugar pricing of refined at \u20b942.20 and sulphitation at about "
        "\u20b941.50 today, it has broadly been the same in this quarter, it is a stark increase to the overall "
        "average refine that we had at Triveni of \u20b941.32 for all of our sugars for the previous fiscal year.",
        "Q4 FY26") == "Q4 FY26"


def test_r7_hindzinc_guidance_for_the_year_takes_the_guidance_year():
    """HINDZINC p6, printed call Q2 FY26: a guidance "for the year" is the current FY; on a Q4 call, the coming FY."""
    stmt = ("In line with Board approved growth projects, our growth capex guidance for the year would be in the "
            "range of $350 million to $400 million.")
    assert ospeaker.anchored_period(stmt, "Q2 FY26") == "FY26"
    assert ospeaker.anchored_period(stmt, "Q4 FY26") == "FY27"
    # a reported "for the year ended <date>" is not a guidance target
    assert ospeaker.anchored_period(
        "Our growth capex guidance was reviewed and capex for the year ended March 2026 was INR 300 crores.",
        "Q2 FY26") == ""


def test_r7_welent_stood_at_with_only_a_yoy_comparative_is_the_call_period():
    """WELENT p7, printed call Q1 FY26: "stood at INR845 crores, marking a 9% year-on-year decline"."""
    assert ospeaker.anchored_period(
        "Revenue from operations stood at INR845 crores, marking a 9% year-on-year decline.", "Q1 FY26") == "Q1 FY26"
    # a named period in the sentence keeps its own meaning
    assert ospeaker.anchored_period(
        "Revenue stood at INR845 crores in Q4 FY26, marking a 9% year-on-year decline.", "Q1 FY26") == ""
    # only "stood/stands/reached" counts; a generic "was ... Y-o-Y" is not the call period
    assert ospeaker.anchored_period(
        "On YTD basis, revenue was INR8,495 crores, up 12% Y-o-Y.", "Q3 FY26") == ""


def test_r7_tarachand_recap_keeps_its_quarter_and_never_moves_to_fy27():
    """TARACHAND, printed call Q3 FY26: r6 moved a past-tense recap's Q4 FY26 target to the later FY27 sentence."""
    assert ospeaker.anchored_period(
        "I want to address one specific point upfront. On our last earnings call in January, I had shared that the "
        "company was targeting to close Q4 with revenue of INR100 crores plus, which would have been a first ever "
        "for us. We finished the quarter at INR89.5 crores as reported today. The shortfall is largely attributable "
        "to project execution time lines that deferred a portion of our Q4 revenue about INR10 crores into Q1 FY '27. "
        "Also, the revenue from our newly started Dankuni Stockyard did not take off in Q4 as per our earlier "
        "estimates. We expect to realize these revenues in early FY '27 and remain confident in our medium-term "
        "growth trajectory.", "Q3 FY26") == "Q4 FY26"


def test_r7_unominda_completed_action_keeps_the_call_period():
    """UNOMINDA p8, printed call Q2 FY25: r6 moved a production start to the later Q1 FY27 expansion sentence."""
    assert ospeaker.anchored_period(
        "Our another associate company TG Uno Minda has started commercial production from expansion project at "
        "its Neemrana plant, taking its airbag capacity from 1.8 million units to 3 million units. During the "
        "quarter, TG Uno Minda approved further expansion through its subsidiary, TGSIN. It will be setting up a "
        "new plant in Harohalli, Karnataka to manufacture safety systems and interior and exterior products. The "
        "total capital expenditure for this new plant in Harohalli is estimated at INR 283 crores, with operations "
        "expected to commence in Q1 FY '27.", "Q2 FY25") == "Q2 FY25"
    # a "this year" cue in a completed-action sentence keeps the year, never the call quarter
    assert ospeaker.anchored_period(
        "Whatever growth we have achieved in this year, 46% growth in EBITDA was there.", "Q4 FY25") == "FY25"


def test_r7_keep_cases_hold_the_r3_to_r6_periods():
    """The 13 keep-cases from the r3-r6 reviews keep their periods after the r7 rules."""
    cases = [
        ("We expect to complete the acquisition during the current quarter.", "Q2 FY27", ""),      # HFCL
        ("EBITDA for the quarter rose by 19.5% year-on-year to Rs. 69.5 crores, up from Rs. 58.2 crores in the "
         "same quarter last year.", "Q1 FY26", "Q1 FY26"),                                           # IOLCP
        ("Our NIM for FY26 is 3.5%.", "Q1 FY26", ""),                                               # CUB
        ("On a Y-o-Y basis, NII for Q4 FY '26 stood at INR781 crores, recording an 8% Y-o-Y growth.",
         "Q4 FY26", ""),                                                                             # KTKBANK #36
        ("As we have already uploaded the results of the last quarter, I am sure you are aware for which our "
         "operating income stood at Rs. 125.72 crores on stand-alone basis, which was a net increase of about 50% "
         "over the last quarter.", "Q1 FY27", ""),                                                   # EMSLIMITED #43
        ("EBITDA in Q1 FY25 at Rs. 103 crore against Rs. 65 crore in the same quarter last year",
         "Q1 FY25", "Q1 FY25"),                                                                      # ASKAUTOLTD
        ("During the quarter, revenue grew 12.9% to INR10,513 million compared to INR8,830 million in the same "
         "quarter last year", "Q4 FY25", "Q4 FY25"),                                                 # MEDANTA
        ("Consolidated Performance The consolidated revenue for the quarter was INR 891 crores, up 25% from "
         "INR 711 crores in the same quarter last year.", "Q1 FY27", "Q1 FY27"),                     # BLS
        ("The domestic explosives volume for the quarter grew by 16% year-on-year basis, which is in line with "
         "our annual guidance for the year '25.", "Q1 FY25", "Q1 FY25"),                              # SOLARINDS
        ("So Q1 of FY27 has been an encouraging start to the year and more importantly, the improvement that we "
         "started seeing during the second half of FY26 has continued into this quarter.", "Q1 FY27", "Q1 FY27"),  # ARMANFIN
        ("We reaffirm our guidance of 25-30% for FY'25", "Q4 FY25", "FY25"),                          # AZAD
        ("During the first half of the year, our focus has been on profitability, cost optimization, and cash "
         "generation. These actions should start delivering somewhere in Quarter 3 and then in Quarter 4.",
         "Q2 FY26", "H1 FY26"),                                                                      # PDSL
        ("During the year, the company successfully completed multiple product validations and also developed "
         "the FRP rod manufacturing line in-house, which is expected to strengthen quality control and long-term "
         "product reliability.", "Q4 FY26", "FY26"),                                                 # MMP
    ]
    for stmt, call, want in cases:
        assert ospeaker.anchored_period(stmt, call) == want, (call, stmt)




def test_r7_review_recap_keeps_named_fy_and_this_time_last_year_is_comparative():
    """Wolf review of r7: a recap naming its FY keeps it; 'this time last year' is the base, not the call quarter."""
    from reality_engine.v2.obs_speaker import anchored_period
    assert anchored_period("As I mentioned, Q1 FY26 revenue was INR 500 crores, and we have grown since.",
                           "Q2 FY27") == "Q1 FY26"
    assert anchored_period("As I had shared on the last earnings call, Q3 FY26 EBITDA was INR 40 crores.",
                           "Q1 FY27") == "Q3 FY26"
    assert anchored_period("This time last year revenue was INR 500 crores.", "Q2 FY27") != "Q2 FY27"
    assert anchored_period("On our last earnings call in January, I had shared that the company was targeting to "
                           "close Q4 with revenue of INR100 crores plus.", "Q4 FY26") == "Q4 FY26"
