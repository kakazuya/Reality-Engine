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
    assert periods("as on 31 March 2026")[0] == ("Q4FY26", "2026-03-31")
    assert periods("net debt in June '26")[0][0] == "Q1FY27"
    assert periods("quarter ended December 31, 2023")[0] == ("Q3FY24", "2023-12-31")
    assert periods("on 15 May 2025") == []          # not a quarter end


def test_value_units():
    vals = kpi.find_values("order book of Rs. 38,000 crore and 5% and $880", "money", "inr_cr", 0, 60, [])
    assert [(v.value, v.unit) for v in vals] == [(38000.0, "inr_cr")]
    pct = kpi.find_values("NIM 10.2% and 37 bps", "pct", "pct", 0, 60, [])
    assert [(v.value, v.unit) for v in pct] == [(10.2, "pct")]
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
    assert c.execute("SELECT count(*) FROM transcript_statement").fetchone()[0] >= 3
    # re-running replaces the company's rows, never duplicates
    n = c.execute("SELECT count(*) FROM kpi_series").fetchone()[0]
    kpi.main(["--out", str(out), "--symbols", "KEC", "--sandbox-root", str(tmp_path / "sb"), "--raw-root", ""])
    assert c.execute("SELECT count(*) FROM kpi_series").fetchone()[0] == n
