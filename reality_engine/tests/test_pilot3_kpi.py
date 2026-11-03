"""Tests for the T-049 B extractors (kpi.py, transcripts.py). Synthetic input only: no sandbox, no network, no model."""
import json
import sqlite3
from pathlib import Path

import pytest

from reality_engine.pilot3 import kpi, transcripts

ENTRIES, DIMS = kpi.load_lexicon()


def periods(s):
    return [(p.canon, p.as_of) for p in kpi.parse_periods(s)]


def test_period_forms():
    assert periods("Q3 FY24 and Q2FY25") == [("Q3FY24", None), ("Q2FY25", None)]
    assert periods("EBITDA in FY '26 and 9M FY25") == [("FY26", None), ("9MFY25", None)]
    assert periods("FY2023-24 results")[0][0] == "FY24"
    assert periods("as on 31 March 2026")[0] == ("FY26", "2026-03-31")      # March closes the year: FY26, not Q4FY26
    assert periods("net debt in June '26")[0][0] == "Q1FY27"
    assert periods("quarter ended December 31, 2023")[0] == ("Q3FY24", "2023-12-31")
    assert periods("on 15 May 2025") == []          # not a quarter end
    assert periods("Quarter ended 30.06.2025 and 31-03-2026") == [("Q1FY26", "2025-06-30"), ("FY26", "2026-03-31")]
    assert periods("ratio 12.50.2019 and 1.5.2020") == []     # not quarter-end dates
    assert periods("Q4 FY26 and FY26")[0][0] == "Q4FY26"      # an explicit quarter label is kept


def test_value_units():
    vals = kpi.find_values("order book of Rs. 38,000 crore and 5% and $880", "money", "inr_cr", 0, 60, [])
    assert [(v.value, v.unit) for v in vals] == [(38000.0, "inr_cr")]
    pct = kpi.find_values("NIM 10.2% and 37 bps", "pct", "pct", 0, 60, [])
    assert [(v.value, v.unit) for v in pct] == [(10.2, "pct")]
    assert [(v.value, v.unit) for v in kpi.find_values("Customer franchise stood at 119.33 MM", "count", "count_mn", 0, 60, [])] \
        == [(119.33, "count_mn")]                       # the decks' "MM" is the same million as "mn"
    assert kpi.finalize_unit("usd_bn", 4.2, "usd_mn")[:2] == (4200.0, "usd_mn")
    assert kpi.finalize_unit("pct_as_bps", 1.79, "bps")[:2] == pytest.approx((179.0, "bps"))


def test_lexicon_loads_every_family():
    metrics = {e.metric for e in ENTRIES}
    for m in ("order_book", "order_intake", "aum", "gnpa_pct", "nim_pct", "ebitda_per_tonne", "shipments_kt", "net_debt"):
        assert m in metrics
    hit = kpi.label_matches(ENTRIES, "KEC", "Order Book + L1 position")
    assert hit and hit[0][0].metric == "order_book_l1"
    assert kpi.label_matches(ENTRIES, "KEC", "Order Book of Rs 36,000")[0][0].metric == "order_book"


def test_sentence_rule_pair_and_quote_is_literal():
    text = ("Mumbai: EBITDA per ton at $880 in Q3 FY24 vs $576 in Q3 FY23, up 53% YoY.\n"
            "Record Order Book + L1 of over Rs. 38,000 crore as at 31 December 2023.\n")
    rows = kpi.sentence_rows(text, 1, "HINDALCO", ENTRIES, DIMS, [])
    got = {(r.metric, r.fiscal_period, r.value) for r in rows}
    assert ("ebitda_per_tonne", "Q3FY24", 880.0) in got and ("ebitda_per_tonne", "Q3FY23", 576.0) in got
    assert ("order_book_l1", "Q3FY24", 38000.0) in got
    assert all(r.quote in text for r in rows)


def test_sentence_rule_drops_value_without_period():
    assert kpi.sentence_rows("Order book stood at Rs 9,999 crore.", 1, "KEC", ENTRIES, DIMS, []) == []


def _words(rows):
    """rows = [(y, [(x0, text), ...])] -> PyMuPDF-style word tuples."""
    out = []
    for y, toks in rows:
        for x, t in toks:
            out.append((x, y - 4, x + 6 * len(t), y + 4, t, 0, 0, 0))
    return out


def test_table_rule_pairs_columns_and_dimension_heading():
    words = _words([
        (20, [(300, "Particulars"), (460, "UOM"), (560, "Q3"), (580, "FY23"), (700, "Q3"), (720, "FY24")]),
        (60, [(280, "Shipments"), (470, "Kt")]), (63, [(590, "336"), (740, "333")]),
        (84, [(280, "EBITDA/t"), (460, "$/ton")]), (87, [(590, "576"), (740, "880")]),
        (80, [(70, "Aluminium"), (150, "Upstream")]),
    ])
    text = "Particulars\nUOM\nQ3 FY23\nQ3 FY24\nShipments\nKt\n336 \n333 \nEBITDA/t\n$/ton \n576 \n880 \nAluminium Upstream\n"
    rows = kpi.table_and_chart_rows(words, text, 1, "HINDALCO", ENTRIES, DIMS, [])
    got = {(r.metric, r.fiscal_period, r.value, r.dimension) for r in rows}
    assert ("shipments_kt", "Q3FY23", 336.0, "aluminium_upstream") in got
    assert ("ebitda_per_tonne", "Q3FY24", 880.0, "aluminium_upstream") in got
    assert all(r.rule == "table_v1" and r.quote in text for r in rows)


def test_chart_rule_skips_ambiguous_multi_series():
    hdr = [(100, "Q3"), (120, "FY23"), (200, "Q3"), (220, "FY24")]
    one = _words([(10, [(90, "Revenue"), (140, "(₹"), (160, "Crore)")]), (60, [(105, "8,046"), (205, "7,971")]), (80, hdr)])
    text = "Revenue (₹ Crore)\n8,046 \n7,971 \nQ3 FY23\nQ3 FY24\n"
    rows = kpi.table_and_chart_rows(one, text, 1, "HINDALCO", ENTRIES, DIMS, [])
    assert {(r.fiscal_period, r.value) for r in rows} == {("Q3FY23", 8046.0), ("Q3FY24", 7971.0)}
    two = _words([(10, [(90, "Revenue"), (140, "(₹"), (160, "Crore)")]), (50, [(105, "81"), (205, "79")]),
                  (60, [(105, "8,046"), (205, "7,971")]), (80, hdr)])
    assert kpi.table_and_chart_rows(two, text, 1, "HINDALCO", ENTRIES, DIMS, []) == []


def test_unit_and_quote_helpers():
    assert kpi.span_quote("a  b\nc 12", ["b", "12"]) == "b\nc 12"
    assert kpi.span_quote("aaa", ["zz"]) is None
    assert kpi.page_basis("Consolidated results") == "consolidated"
    assert kpi.page_basis("Consolidated and standalone") == "not_stated"


# ----------------------------------------------------------------------------- transcripts
CALL_P1 = """KEC International Limited
August 11, 2026
Page 1 of 2
Moderator:
Ladies and gentlemen, we will now begin the question-and-answer session. The first question comes from the line of Renu Baid Pugalia from IIFL Securities. Please go ahead.
Renu Baid Pugalia: What is the order book outlook for railways?
Vimal Kejriwal:
Thank you. We have a strong order book of INR37,697 crores as on date. Net debt fell to INR6,568 crores in June '26 from March '26. The labor situation in the
"""
CALL_P2 = """KEC International Limited
August 11, 2026
Page 2 of 2
Middle East is improving, Mr. Gupta said. Railways remain a focus.
Rajeev Aggarwal:
Working capital was 112 days in Q1 FY27 versus 120 days in Q4 FY26.
"""


def _call(tmp: Path):
    topics, people = transcripts.load_topics()
    st = {"unknown_speakers": __import__("collections").Counter()}
    rows = transcripts.extract_doc("KEC", "d1.pdf", "Conference Call Q1 FY27", "2026-08-14T15:30:33",
                                   [(1, CALL_P1), (2, CALL_P2)], topics, people, st)
    return rows, st


def test_transcript_roles_sections_quotes(tmp_path):
    rows, st = _call(tmp_path)
    by = {}
    for r in rows:
        d = dict(zip(transcripts.COLS, r))
        by.setdefault(d["speaker"], []).append(d)
    assert "Renu Baid Pugalia" not in by and "Moderator" not in by          # analyst / moderator are not stored
    assert {d["role"] for d in by["Vimal Kejriwal"]} == {"ceo"}
    assert {d["role"] for d in by["Rajeev Aggarwal"]} == {"cfo"}
    pages = {1: CALL_P1, 2: CALL_P2}
    for rs in by.values():
        for d in rs:
            assert d["section"] == "qa"
            assert d["quote"] in pages[d["page"]]                           # literal slice of the page
            assert d["call_date"] == "2026-08-11" and d["call_period"] == "Q1FY27"


def test_transcript_numbers_topics_fragments(tmp_path):
    rows, _ = _call(tmp_path)
    ds = [dict(zip(transcripts.COLS, r)) for r in rows]
    ob = next(d for d in ds if "order book of INR37,697" in d["statement"])
    nums = json.loads(ob["numbers_json"])
    assert nums[0]["value"] == 37697.0 and nums[0]["unit"] == "inr_cr" and "order_book" in ob["topics"].split(",")
    nd = next(d for d in ds if "Net debt fell" in d["statement"])
    assert json.loads(nd["numbers_json"])[0]["period"] == "Q1FY27"
    frag = next(d for d in ds if d["statement"].startswith("The labor situation"))
    assert frag["is_fragment"] == 1                                         # cut by the page break
    wc = next(d for d in ds if "Working capital was" in d["statement"])
    assert "working_capital" in wc["topics"].split(",")
    assert [n["period"] for n in json.loads(wc["numbers_json"])][:2] == ["Q1FY27", "Q4FY26"]


def test_sentence_split_keeps_abbreviations_and_decimals():
    seg = "Mr. Gupta said Rs. 5.5 crore came in. Next, Q3 FY24 grew 2.5% over Dr. Rao's plan. Done?"
    spans = transcripts.split_sentences(seg, 0)
    assert [seg[a:b] for a, b in spans] == ["Mr. Gupta said Rs. 5.5 crore came in.",
                                           "Next, Q3 FY24 grew 2.5% over Dr. Rao's plan.", "Done?"]


def test_call_period_from_the_calls_own_words():
    """Older zero-padded forms ("FY 2026 fourth quarter") used to raise KeyError: the groups were swapped."""
    assert transcripts.call_period_of("", ["Fourth quarter of FY 2026"]) == "Q4FY26"
    assert transcripts.call_period_of("", ["FY 2026 fourth quarter results"]) == "Q4FY26"
    assert transcripts.call_period_of("Conference Call Q1 FY27", []) == "Q1FY27"


def test_management_intro_accepts_a_composite_title():
    text = ("Mr. Rajeev Jain, Vice Chairman and Managing Director; and Mr. Sandeep Jain, COO and CFO;"
            " Mr. Subir Sen, Head of Investor Relations")
    mgmt = {m.group(1): transcripts._title_role(m.group(2)) for m in transcripts.MGMT_INTRO_RX.finditer(text)}
    assert mgmt == {"Rajeev Jain": "md", "Sandeep Jain": "mgmt", "Subir Sen": "ir"}


def test_known_names_survive_an_ocr_slip():
    topics, people = transcripts.load_topics()
    assert transcripts._same_person("Stish Pai", "Satish Pai")           # OCR dropped the "a"
    assert transcripts._same_person("Dev Ahuja", "Devinder Ahuja")      # short form of the same person
    assert not transcripts._same_person("Manish Jain", "Sandeep Jain")  # different people, shared surname
    assert transcripts.role_of("Stish Pai", "HINDALCO", people, [], {}) == "md"
    assert transcripts.role_of("Devinder Ahuja", "HINDALCO", people, [], {"DEV AHUJA": "cfo"}) == "cfo"


# ----------------------------------------------------------------------------- end to end on a fake sandbox
PRESS_TEXT = ("FINANCIAL PERFORMANCE FOR QUARTER ENDED 31 DECEMBER 2023\nRecord Order Book + L1 of over Rs. 38,000 crore\n"
              "Order intake of Rs. 6,000 crore in Q3 FY24\n")


def _fake_sandbox(root: Path):
    d = root / "kec_loop"
    d.mkdir(parents=True)
    con = sqlite3.connect(d / "kec.db")
    con.executescript("""
      CREATE TABLE docs(doc_key TEXT, doc_type TEXT, title TEXT, filing_date TEXT, known_at TEXT, pages INT, source TEXT, source_key TEXT);
      CREATE TABLE doc_text(doc_key TEXT, page INT, text TEXT, method TEXT, known_at TEXT);
      CREATE TABLE deck_figures(sha256 TEXT, known_at TEXT);
    """)
    con.execute("INSERT INTO docs VALUES('p.pdf','press_release','Press Release','2024-01-30','2024-01-30T19:00:00',1,'s','k1')")
    con.execute("INSERT INTO doc_text VALUES('p.pdf',1,?,'script_text','2024-01-30')",
                (PRESS_TEXT,))
    con.execute("INSERT INTO docs VALUES('t.pdf','transcript','Conference Call Q3 FY24','2024-02-05','2024-02-05T18:00:00',2,'s','k2')")
    con.execute("INSERT INTO doc_text VALUES('t.pdf',1,?,'script_text','2024-02-05')", (CALL_P1,))
    con.execute("INSERT INTO doc_text VALUES('t.pdf',2,?,'needs_ocr','2024-02-05')", ("",))
    con.commit()
    con.close()


def test_cli_end_to_end_no_network(tmp_path, monkeypatch):
    import socket

    def no_net(*a, **k):
        raise AssertionError("network used")
    monkeypatch.setattr(socket.socket, "connect", no_net)
    _fake_sandbox(tmp_path / "sb")
    out = tmp_path / "o.db"
    assert kpi.main(["--out", str(out), "--symbols", "KEC", "--sandbox-root", str(tmp_path / "sb"), "--raw-root", ""]) == 0
    assert transcripts.main(["--out", str(out), "--symbols", "KEC", "--sandbox-root", str(tmp_path / "sb")]) == 0
    c = sqlite3.connect(out)
    k = {(m, p, v) for m, p, v in c.execute("SELECT metric, fiscal_period, value FROM kpi_series")}
    assert ("order_book_l1", "Q3FY24", 38000.0) in k and ("order_intake", "Q3FY24", 6000.0) in k
    pages = {CALL_P1, PRESS_TEXT}
    for (q,) in c.execute("SELECT quote FROM kpi_series"):
        assert any(q in p for p in pages)
    # every row says which kind of document it came from, and a call's number sits below any document row
    assert {d for (d,) in c.execute("SELECT DISTINCT source_type FROM kpi_series")} == {"press_release", "transcript"}
    assert c.execute("SELECT max(conf_rank) FROM kpi_series WHERE doc_key='p.pdf'").fetchone()[0] > \
        c.execute("SELECT max(conf_rank) FROM kpi_series WHERE doc_key='t.pdf'").fetchone()[0]
    assert c.execute("SELECT count(*) FROM transcript_statement").fetchone()[0] >= 3
    # re-running replaces the company's rows, never duplicates
    n = c.execute("SELECT count(*) FROM kpi_series").fetchone()[0]
    kpi.main(["--out", str(out), "--symbols", "KEC", "--sandbox-root", str(tmp_path / "sb"), "--raw-root", ""])
    assert c.execute("SELECT count(*) FROM kpi_series").fetchone()[0] == n


def test_transcripts_read_the_pilot3_page_text(tmp_path):
    """The extractor reads the pilot3 db's own doc_page (pages.db documents + RapidOCR text), not only the loop's
    old sandbox transcripts: a modern call stored there yields statements."""
    out = tmp_path / "p3.db"
    c = sqlite3.connect(out)
    c.executescript("CREATE TABLE doc(doc_key TEXT, symbol TEXT, doc_type TEXT, title TEXT, known_at TEXT);"
                    "CREATE TABLE doc_page(doc_key TEXT, page INT, text TEXT);")
    c.execute("INSERT INTO doc VALUES('concall_pdfs/9b/x.pdf','KEC','transcript','Analyst / Investor Meet',"
              "'2026-08-14T15:30:33')")
    c.execute("INSERT INTO doc_page VALUES('concall_pdfs/9b/x.pdf',1,?)", (CALL_P1,))
    c.commit()
    c.close()
    assert transcripts.main(["--out", str(out), "--symbols", "KEC",
                             "--sandbox-root", str(tmp_path / "no_sandbox")]) == 0
    c = sqlite3.connect(out)
    rows = c.execute("SELECT doc_key, quote FROM transcript_statement").fetchall()
    assert rows and rows[0][0] == "concall_pdfs/9b/x.pdf"            # the pilot3 key, joined by doc directly
    assert any("order book of INR37,697" in quote for _key, quote in rows)


# ----------------------------------------------------------------------------- T-049: FY25-FY27 documents
KEC_Q4_TITLE = "“KEC International Limited\nQ4 FY '26 Results Conference Call”\nMay 18, 2026\n"
KEC_Q4_P3 = ("In addition, certain equipment and steel suppliers are facing operational disruptions.\n"
             "There is a provision of INR59 crores made in FY '26 towards the new labor code and a one-time charge "
             "of INR53 crores from an arbitration award recognized last year in FY '25. In Q4, we delivered revenues "
             "of INR6,390 crores with EBITDA margin of 7%.\n")
KEC_Q4_P4 = ("Our order book remains robust at INR36,267 crores. We are happy that the order intake trend "
             "continues in FY '27 with new orders of over INR1,000 crores announced till date.\n")


def test_q4_call_defaults_to_its_own_year_not_a_prior_year_comparison():
    """The KEC 36,267 crore order book was stored FY25: the call's page 3 mentions "last year in FY '25" and that
    became the document's default period. The Q4 (annual-results) document defaults to its fiscal year."""
    assert [p.canon for p in kpi.doc_default_period([KEC_Q4_TITLE])] == ["FY26"]
    assert [p.canon for p in kpi.doc_default_period([KEC_Q4_P3])] == ["FY26"]      # "last year in FY '25" dropped
    default = kpi.doc_default_period([KEC_Q4_TITLE, KEC_Q4_P3])
    rows = kpi.sentence_rows(KEC_Q4_P4, 4, "KEC", ENTRIES, DIMS, default)
    ob = next(r for r in rows if r.metric == "order_book")
    assert (ob.fiscal_period, ob.value, ob.rule) == ("FY26", 36267.0, "sentence_default_v1")


def _fake_pages_db(path: Path) -> str:
    c = sqlite3.connect(path)
    c.executescript("""
      CREATE TABLE doc(doc_key TEXT, symbol TEXT, doc_type TEXT, title TEXT, filing_date TEXT, known_at TEXT,
                       source_path TEXT, sha256 TEXT, pages INT, source_record TEXT, known_at_source TEXT);
      CREATE TABLE doc_page(doc_key TEXT, page INT, text TEXT, method TEXT, known_at TEXT);
    """)
    text = ("FINANCIAL PERFORMANCE FOR QUARTER ENDED 31 MARCH 2026\n"
            "Order Book as on 31 March 2026 of Rs. 36,267 crore.\n")
    c.execute("INSERT INTO doc VALUES('history/results/fy26.pdf','KEC','results','FY26 results',NULL,"
              "'2026-05-16T22:00:00',NULL,NULL,1,'','')")
    c.execute("INSERT INTO doc_page VALUES('history/results/fy26.pdf',1,?,'script_text','2026-05-16')", (text,))
    c.commit()
    c.close()
    return text


def test_pages_db_documents_are_read_with_their_source_type(tmp_path):
    """--pages-db: the FY25-FY27 documents the sandbox does not hold are read, labelled by their document type."""
    sb = tmp_path / "sb"
    _fake_sandbox(sb)
    pages = tmp_path / "pages.db"
    text = _fake_pages_db(pages)
    out = tmp_path / "o.db"
    assert kpi.main(["--out", str(out), "--symbols", "KEC", "--sandbox-root", str(sb), "--raw-root", "",
                     "--pages-db", str(pages)]) == 0
    c = sqlite3.connect(out)
    rows = c.execute("SELECT fiscal_period, value, source_type, known_at_source, quote FROM kpi_series "
                     "WHERE doc_key='history/results/fy26.pdf'").fetchall()
    assert ("FY26", 36267.0, "results", "pages.db.doc.known_at") in [r[:4] for r in rows]
    assert all(r[4] in text for r in rows)                     # quote is a literal slice of the pages.db page
    # the sandbox documents pages.db does not hold are still read, with their own source type
    assert c.execute("SELECT count(*) FROM kpi_series WHERE doc_key='p.pdf' AND source_type='press_release'").fetchone()[0] > 0


# ----------------------------------------------------------------------------- T-049 E: precision, formulas, OCR
def test_generic_label_needs_period_and_unit_in_its_sentence():
    default = kpi.parse_periods("quarter ended 30 June 2026")
    assert kpi.sentence_rows("Margin stood at 6.5% for the company.", 1, "KEC", ENTRIES, DIMS, default) == []   # default period only
    rows = kpi.sentence_rows("Margin of 6.5% in Q1 FY27.", 1, "KEC", ENTRIES, DIMS, [])
    assert [(r.metric, r.value, r.fiscal_period, r.rule) for r in rows] == [("ebitda_margin_pct", 6.5, "Q1FY27", "sentence_v1")]
    named = kpi.sentence_rows("EBITDA margin at 7.1%.", 1, "KEC", ENTRIES, DIMS, default)
    assert named and named[0].rule == "sentence_default_v1"        # a specific label may use the document period
    assert kpi.sentence_rows("PBT Margins of 6.4% in Q1 FY27", 1, "KEC", ENTRIES, DIMS, []) == []     # not an EBITDA margin
    assert kpi.sentence_rows("net cash flows amounting to ` 23 Crore in Q1 FY27", 1, "KEC", ENTRIES, DIMS, []) == []


def test_confidence_tiers_order():
    rc = kpi.RULE_CONF
    assert rc["table_v1"][1] > rc["chart_v1"][1] > rc["sentence_v1"][1] > rc["sentence_default_v1"][1]
    assert rc["sentence_pair_v1"][0] == "sentence"


def test_stacked_axis_becomes_periods_and_sentence_is_not_a_header():
    words = _words([(10, [(90, "Shipments"), (150, "(KT)")]), (60, [(105, "328"), (205, "325"), (305, "341")]),
                    (80, [(100, "Q2"), (200, "Q1"), (300, "Q2")]), (92, [(100, "FY25"), (200, "FY26"), (300, "FY26")])])
    text = "Shipments (KT)\n328 \n325 \n341 \nQ2\nQ1\nQ2\nFY25\nFY26\nFY26\n"
    rows = kpi.table_and_chart_rows(words, text, 1, "HINDALCO", ENTRIES, DIMS, [])
    assert {(r.fiscal_period, r.value) for r in rows} == {("Q2FY25", 328.0), ("Q1FY26", 325.0), ("Q2FY26", 341.0)}
    # a sentence naming two periods is not an axis: no rows
    sent = _words([(10, [(90, "Shipments"), (150, "(KT)")]), (60, [(105, "328"), (205, "325")]),
                   (80, [(90, "In"), (110, "Q2"), (125, "FY26"), (160, "sales"), (200, "mix"), (230, "was"), (250, "higher"),
                         (290, "than"), (320, "Q1"), (335, "FY26"), (370, "in"), (390, "the"), (410, "prior"), (440, "period")])])
    assert kpi.table_and_chart_rows(sent, "Shipments (KT)\n328 \n325 \n", 1, "HINDALCO", ENTRIES, DIMS, []) == []


def test_one_value_per_column_and_percent_never_borrows_label_unit():
    import re
    cols = [(100.0, "pA"), (200.0, "pB")]
    nums = [(98.0, re.search("1", "1")), (110.0, re.search("2", "2")), (201.0, re.search("3", "3"))]
    got = kpi._assign_columns(nums, cols, 28)
    assert [(x, p) for x, _, p in got] == [(98.0, "pA"), (201.0, "pB")]       # 110 lost column A to the nearer 98
    hdr = [(300, "Q3"), (320, "FY23"), (500, "Q3"), (520, "FY24")]
    words = _words([(20, hdr), (60, [(80, "Shipments"), (150, "(KT)")]), (62, [(310, "23%"), (510, "25%")])])
    text = "Q3 FY23\nQ3 FY24\nShipments (KT)\n23% \n25% \n"
    assert kpi.table_and_chart_rows(words, text, 1, "HINDALCO", ENTRIES, DIMS, []) == []


def test_segment_taken_from_column_heading():
    words = _words([
        (10, [(300, "Aluminium"), (330, "Upstream"), (560, "Copper")]),
        (30, [(300, "Q3"), (320, "FY23"), (400, "Q3"), (420, "FY24"), (500, "Q3"), (520, "FY23"), (600, "Q3"), (620, "FY24")]),
        (60, [(80, "Shipments"), (150, "Kt")]), (62, [(310, "336"), (410, "333"), (510, "487"), (610, "480")]),
    ])
    text = "Aluminium Upstream\nCopper\nQ3 FY23\nQ3 FY24\nQ3 FY23\nQ3 FY24\nShipments\nKt\n336 \n333 \n487 \n480 \n"
    rows = kpi.table_and_chart_rows(words, text, 1, "HINDALCO", ENTRIES, DIMS, [])
    assert {(r.dimension, r.value) for r in rows} == {("aluminium_upstream", 336.0), ("aluminium_upstream", 333.0),
                                                     ("copper", 487.0), ("copper", 480.0)}


def test_new_lexicon_labels():
    assert kpi.label_matches(ENTRIES, "KEC", "order book (excluding L1)")[0][0].metric == "order_book"
    assert kpi.label_matches(ENTRIES, "BAJFINANCE", "return on average assets after one-time actions")[0][0].metric == "roa_pct"
    assert kpi.label_matches(ENTRIES, "BAJFINANCE", "loan loss provisions")[0][0].metric == "loan_loss_provisions"
    assert kpi.label_matches(ENTRIES, "HINDALCO", "aluminium upstream segment revenue")[0][0].metric == "revenue"
    assert kpi.label_matches(ENTRIES, "HINDALCO", "Copper CC Rods (Kt)")[0][0].metric == "copper_rods_volume_kt"
    assert kpi.label_matches(ENTRIES, "HINDALCO", "copper cathode volume")[0][0].metric == "copper_cathode_volume_kt"


def _kpi_db():
    c = sqlite3.connect(":memory:")
    c.executescript(kpi.SCHEMA)
    c.executescript("""CREATE TABLE ratio_panel(symbol TEXT, isin TEXT, fiscal_period TEXT, period_type TEXT, period_start TEXT,
        period_end TEXT, basis TEXT, metric TEXT, value REAL, unit TEXT, scale REAL, formula_id TEXT, input_refs TEXT,
        known_at TEXT, known_at_source TEXT, is_derived INTEGER);""")

    def put(metric, dim, per, val, rank, known="2026-08-01", unit="inr_cr"):
        c.execute("INSERT INTO kpi_series(symbol,metric,dimension,value,unit,scale,period_type,fiscal_period,doc_key,page,quote,known_at,"
                  "extractor_rule,confidence,conf_rank) VALUES('KEC',?,?,?,?,1e7,'Q',?,'d.pdf',?,'q',?,'table_v1','x',?)",
                  (metric, dim, val, unit, per, int(val) % 90 + 1, known, rank))
    put("order_book", "T&D", "Q1FY27", 600.0, 4)
    put("order_book", "civil", "Q1FY27", 300.0, 4)
    put("order_book", "T&D", "Q1FY27", 111.0, 1)                 # a noisy default-tier row must lose
    put("order_book", "total", "Q1FY27", 1000.0, 4)
    put("order_book", "total", "Q1FY26", 800.0, 4)
    put("order_book", "total", "Q4FY26", 950.0, 4)
    put("order_intake", "total", "Q1FY27", 400.0, 4)
    for per, rev in (("Q1FY27", 100.0), ("Q4FY26", 110.0), ("Q3FY26", 90.0), ("Q2FY26", 95.0)):
        c.execute("INSERT INTO ratio_panel VALUES('KEC','I',?,'Q','a','b','consolidated','revenue_from_operations',?,'inr',1.0,NULL,'','2026-08-01',NULL,0)",
                  (per, rev * 1e7))
    c.commit()
    return c


def test_growth_share_mix_book_to_bill_coverage_formulas():
    from reality_engine.pilot3 import queries as q
    c = _kpi_db()
    assert q.prior_period("Q1FY27") == "Q1FY26" and q.prior_period("Q1FY27", "qoq") == "Q4FY26"
    assert q.prior_period("Q3FY26", "qoq") == "Q2FY26" and q.prior_period("FY26") == "FY25" and q.prior_period("FY26", "qoq") is None
    assert q.kpi_value(c, "KEC", "order_book", "Q1FY27", "T&D")[0][0] == 600.0           # best tier, not the 111 default row
    assert q.kpi_growth(c, "KEC", "order_book", "Q1FY27")[0][0] == pytest.approx(25.0)    # 1000 / 800
    assert q.kpi_growth(c, "KEC", "order_book", "Q1FY27", kind="qoq")[0][0] == pytest.approx(100 * (1000 / 950 - 1))
    assert q.kpi_growth(c, "KEC", "order_book", "Q1FY30") == []
    assert q.kpi_share(c, "KEC", "order_book", "Q1FY27", "T&D")[0][0] == pytest.approx(60.0)
    mix = dict(q.kpi_mix(c, "KEC", "order_book", "Q1FY27"))
    assert mix == pytest.approx({"T&D": 100 * 600 / 900, "civil": 100 * 300 / 900}) and sum(mix.values()) == pytest.approx(100)
    assert q.book_to_bill(c, "KEC", "Q1FY27")[0][0] == pytest.approx(4.0)                 # 400 / 100
    assert q.coverage_years(c, "KEC", "Q1FY27")[0][0] == pytest.approx(1000 / (100 + 110 + 90 + 95))
    for i, per in enumerate(("Q1FY26", "Q2FY26", "Q3FY26", "Q4FY26")):
        c.execute("INSERT INTO kpi_series(symbol,metric,dimension,value,unit,scale,period_type,fiscal_period,doc_key,page,quote,known_at,"
                  "extractor_rule,confidence,conf_rank) VALUES('KEC','order_intake','civil',?,'inr_cr',1e7,'Q',?,'d.pdf',1,'q','2026-08-01','table_v1','x',4)",
                  (10.0 * (i + 1), per))
    assert q.kpi_fy_sum(c, "KEC", "order_intake", "FY26", "civil")[0][0] == 100.0 and q.kpi_fy_sum(c, "KEC", "order_intake", "FY27", "civil") == []
    assert q.book_to_bill(c, "KEC", "Q2FY27") == [] and q.kpi_value(c, "KEC", "order_book", "Q1FY27", "T&D", as_of="2026-07-01") == []


def test_formulas_registered():
    from reality_engine.pilot3 import ratios
    ids = {f[0] for f in ratios.FORMULAS}
    assert {"F_KPI_YOY", "F_KPI_QOQ", "F_SHARE", "F_MIX", "F_B2B", "F_COVER"} <= ids
    assert all(len(f) == 6 for f in ratios.FORMULAS)


def test_ocr_helpers_and_ocr_pages_feed_the_extractors(tmp_path):
    from reality_engine.pilot3 import ocr
    boxes = [[[10, 100], [310, 100], [310, 130], [10, 130]], [[400, 102], [700, 102], [700, 132], [400, 132]]]
    words = ocr.boxes_to_words(boxes, ["Order book", "37,697 crore"], [0.99, 0.95], 300)
    assert [w[4] for w in words] == ["Order", "book", "37,697", "crore"]
    assert 0 < words[0][0] < words[0][2] <= words[1][0] + 1e-6 and words[0][3] == pytest.approx(130 * 72 / 300)
    assert ocr.words_to_text(words) == "Order book 37,697 crore"
    sb = tmp_path / "sb"
    _fake_sandbox(sb)
    con = sqlite3.connect(sb / "kec_loop" / "kec.db")
    con.execute("INSERT INTO docs VALUES('scan.pdf','deck','Deck','2024-02-05','2024-02-05T18:00:00',1,'s','k3')")
    con.execute("INSERT INTO doc_text VALUES('scan.pdf',1,'','needs_ocr','2024-02-05')")
    con.commit()
    con.close()
    odb = tmp_path / "ocr.db"
    oc = sqlite3.connect(odb)
    oc.executescript(ocr.SCHEMA)
    text = "Order book of Rs. 37,697 crore in Q1 FY27"
    oc.execute("INSERT INTO ocr_page VALUES('KEC','scan.pdf',1,'deck','2024-02-05',?,?,0.97,9,300,1.0,'ocr_rapid')",
               (text, json.dumps([[0, 0, 10, 10, "x", 0.9]])))
    oc.commit()
    oc.close()
    out = tmp_path / "o.db"
    assert kpi.main(["--out", str(out), "--symbols", "KEC", "--sandbox-root", str(sb), "--raw-root", "", "--ocr-db", str(odb)]) == 0
    c = sqlite3.connect(out)
    r = c.execute("SELECT value, method, ocr_conf, confidence, quote FROM kpi_series WHERE doc_key='scan.pdf'").fetchall()
    assert r and r[0][:3] == (37697.0, "ocr_rapid", 0.97) and r[0][3] == "sentence" and r[0][4] in text
    assert c.execute("SELECT count(*) FROM kpi_series WHERE doc_key='p.pdf' AND method='text_layer'").fetchone()[0] > 0


def test_change_by_is_not_the_level_and_respectively_pairs_labels():
    t1 = "Net debt, including acceptances, have been reduced by over INR150 crores to INR6,568 crores in June '26"
    assert {r.value for r in kpi.sentence_rows(t1, 1, "KEC", ENTRIES, DIMS, [])} == {6568.0}
    assert kpi.sentence_rows("Net debt was reduced by INR150 crores in June '26", 1, "KEC", ENTRIES, DIMS, []) == []
    t2 = "GNPA and NNPA improving to 0.96% and 0.39%, respectively, as of 30 June 2026"
    got = {r.metric: r.value for r in kpi.sentence_rows(t2, 1, "BAJFINANCE", ENTRIES, DIMS, [])}
    assert got == {"gnpa_pct": 0.96, "nnpa_pct": 0.39}
