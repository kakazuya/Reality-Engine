"""T-223 (1): segment tables printed in quarterly results (``pilot3.segments_printed``), on synthetic word rows."""
from __future__ import annotations

import sqlite3

from reality_engine.pilot3 import segments_printed as S


def _row(y, *cells):
    out = []
    for x, text in cells:
        for word in text.split(" "):
            out.append((x, y, x + 6 * len(word), y + 8, word))
            x += 6 * len(word) + 4
    return out


COLS = (300, 380, 460, 540, 620)   # Q4 table: current, preceding, year-ago, FY, prior FY


def _num(y, label, *vals):
    """Figures right-aligned on the column edges, as printed."""
    return _row(y, (30, label), *[(x + 50 - 6 * len(v), v) for x, v in zip(COLS, vals)])


def q4_page(fabric_q="258.80", total_q="1,242.08", title="Standalone segment information (Rs. in crore)"):
    rows = [_row(10, (30, title)),
            _row(20, (30, "Particulars"), (300, "31.03.2025"), (380, "31.12.2024"), (460, "31.03.2024"),
                 (540, "31.03.2025"), (620, "31.03.2024")),
            _row(40, (30, "1 Segment Revenue")),
            _num(52, "a) Yarn", "983.28", "978.60", "989.19", "4,112.36", "3,900.00"),
            _num(64, "b) Fabric", fabric_q, "287.81", "275.76", "1,131.17", "1,000.00"),
            _num(76, "Total", total_q, "1,266.41", "1,264.95", "5,243.53", "4,900.00"),
            _num(88, "Less: Inter Segment Revenue", "92.13", "97.22", "99.04", "418.24", "400.00"),
            _num(100, "Net Sales / Income from Operations", "1,149.95", "1,169.19", "1,165.91", "4,825.29", "4,500.00"),
            _row(112, (30, "2 Segment Results")),
            _num(124, "a) Yarn", "30.03", "26.51", "(6.98)", "31.57", "20.00"),
            _num(136, "b) Fabric", "12.47", "15.90", "6.78", "31.78", "30.00"),
            _num(148, "Total", "42.50", "42.41", "(0.20)", "63.35", "50.00"),
            _row(160, (30, "3 Segment Assets")),
            _num(172, "a) Yarn", "2,313.40", "2,426.47", "2,441.81", "2,313.40", "2,441.81"),
            _num(184, "b) Fabric", "595.81", "586.29", "562.84", "595.81", "562.84"),
            _num(196, "Unallocated", "431.74", "428.21", "409.49", "431.74", "409.49"),
            _num(208, "Total", "3,340.95", "3,440.97", "3,414.14", "3,340.95", "3,414.14")]
    return [sorted(r) for r in rows]


def test_block_headings_tolerate_ocr():
    assert S.block_of("Segment Revenue") == "segment_revenue"
    assert S.block_of("S,i,ment Result") is None or S.block_of("Segment Result") == "segment_ebit"
    assert S.block_of("Seen,ent Assets") == "segment_assets"
    assert S.block_of("Segment Liabilities") == "segment_liabilities"   # a heading too garbled to read opens nothing (rows lost, never misfiled)
    assert S.block_of("Capital Employed") == "segment_capital_employed"
    assert S.block_of("Revenue from operations") is None


def test_names_and_unallocated():
    assert S.segment_name("a) Yarn") == "Yarn"
    assert S.segment_name("(b) Retail Banking") == "Retail Banking"
    assert S.segment_name("al Yarn") == "Yarn"
    assert S.segment_name("b) Fabric 275_76") == "Fabric"
    assert S.segment_name("(c) Segment- IT Services") == "IT Services"
    assert S.is_unallocated("Unalloca1ed") and S.is_unallocated("Un-allocated") and not S.is_unallocated("Treasury")
    assert not S.readable("l ll j l fr l f fr w f h iil") and S.readable("Distillery") and S.readable("Co-generation")


def test_blocks_add_up_with_unallocated_and_bad_sum_refused():
    t = S.read_table(q4_page(), "2025-05-20T18:00:00")
    assert t["end"] == "2025-03-31" and t["scale"] == 1e7
    good = {(m, c): [x.name for x in segs] for m, c, segs in S.checked_blocks(t, [0, 1, 2, 3, 4])}
    assert good[("segment_revenue", 0)] == ["Yarn", "Fabric"]
    assert good[("segment_assets", 0)] == ["Yarn", "Fabric", "Unallocated"]   # the total includes unallocated
    bad = S.read_table(q4_page(fabric_q="268.80"), "2025-05-20T18:00:00")    # misread: Yarn+Fabric != Total
    assert ("segment_revenue", 0) not in {(m, c) for m, c, _ in S.checked_blocks(bad, [0, 1, 2, 3, 4])}


def _store(tmp_path, pl_revenue: float | None):
    db = tmp_path / "c99.db"
    con = sqlite3.connect(db)
    con.executescript("""
    CREATE TABLE fin_quarter_printed(symbol TEXT, doc_key TEXT, basis TEXT, period_end TEXT, period_type TEXT,
      column_role TEXT, line_item TEXT, value REAL, scale REAL, page INTEGER);
    """)
    if pl_revenue is not None:
        con.execute("INSERT INTO fin_quarter_printed VALUES ('X','d','standalone','2025-03-31','quarter','current',"
                    "'revenue_from_operations',?,1,NULL)", (pl_revenue,))
    con.commit()
    return con


def test_columns_and_unit_fixed_by_the_pl_revenue(tmp_path):
    t = S.read_table(q4_page(title="Standalone segment information"), "2025-05-20T18:00:00")   # no unit printed
    con = _store(tmp_path, 1149.95e7)
    periods, scale, how = S.choose_columns(con, "X", t, [0, 1, 2, 3, 4], "standalone", t["scale"])
    assert scale == 1e7 and how.startswith("revenue line")
    assert periods[0][1] == "Q4FY25" and periods[3][1] == "FY25" and periods[2][1] == "Q4FY24"


def test_no_unit_and_no_pl_is_refused(tmp_path):
    t = S.read_table(q4_page(title="Standalone segment information"), "2025-05-20T18:00:00")
    con = _store(tmp_path, None)
    periods, scale, how = S.choose_columns(con, "X", t, [0, 1, 2, 3, 4], "standalone", None)
    assert periods is None


def test_revenue_line_disagreeing_with_pl_is_refused(tmp_path):
    t = S.read_table(q4_page(), "2025-05-20T18:00:00")
    con = _store(tmp_path, 999.0e7)
    periods, _scale, how = S.choose_columns(con, "X", t, [0, 1, 2, 3, 4], "standalone", t["scale"])
    assert periods is None and "disagrees" in how


def test_side_by_side_halves_named_by_words_above_columns():
    head = [_row(10, (300, "Standalone"), (650, "Consolidated"))]
    anchors = [300, 340, 380, 420, 460, 500, 650, 690, 730, 770, 810, 850]
    groups = S._halves(head, anchors, "Standalone ... Consolidated")
    assert groups[0][1] == "standalone" and groups[1][1] == "consolidated"
    title_only = [_row(10, (30, "Consolidated and Standalone segment results"))]
    assert all(b is None for _g, b in S._halves(title_only, anchors, "x"))


# --- review round 1 (17 Nov): defects 1-5 ---

def test_results_heading_with_income_is_the_results_block():
    assert S.block_of("Segment Results (Profit before interest income and tax)") == "segment_ebit"
    assert S.block_of("Segment Revenue / Income") == "segment_revenue"


def test_two_columns_naming_one_period_or_june_ytd_are_refused():
    # a Q4 page read with the six-column set: prior_ytd and last_fy both name FY(y-1)
    assert S.periods_for(["current", "preceding", "year_ago", "ytd", "prior_ytd", "last_fy"],
                         [0, 1, 2, 3, 4, 5], "2025-03-31") is None
    # a June end: the 'year to date' is the quarter itself (or a year that does not end in March)
    assert S.periods_for(["current", "year_ago", "ytd", "prior_ytd"], [0, 1, 2, 3], "2025-06-30") is None
    p = S.periods_for(["current", "year_ago", "ytd", "prior_ytd"], [0, 1, 2, 3], "2025-09-30")
    assert p[2][1] == "H1FY26" and p[2][4] is True and p[3][4] is False    # the filing's own H1 is 'own'


def test_header_date_contradicting_its_role_refuses_the_page():
    # a calendar-year company: the third column prints 31.12.2023 where a March year-ago quarter is expected
    t = S.read_table(q4_page(), "2025-05-20T18:00:00")
    t["dates"] = [(3, 2025), (12, 2024), (12, 2023), (3, 2025), (3, 2024)]
    assert S.role_candidates(t, [0, 1, 2, 3, 4]) == []


def test_one_matching_column_never_outweighs_a_mismatch(tmp_path):
    # no 'Net sales' line (segment total used): the FY column matches the P&L but the quarter does not
    t = S.read_table(q4_page(), "2025-05-20T18:00:00")
    t["cells"] = [c for c in t["cells"] if c.metric != "_revenue_line"]
    con = _store(tmp_path, None)
    con.execute("INSERT INTO fin_quarter_printed VALUES ('X','d','standalone','2025-03-31','fy','ytd',"
                "'revenue_from_operations',?,1,NULL)", (5243.53e7,))
    con.execute("INSERT INTO fin_quarter_printed VALUES ('X','d','standalone','2025-03-31','quarter','current',"
                "'revenue_from_operations',?,1,NULL)", (999.0e7,))
    periods, _scale, how = S.choose_columns(con, "X", t, [0, 1, 2, 3, 4], "standalone", t["scale"])
    assert periods is None and "disagrees" in how


# --- review round 2 (17 Nov): same-page P&L, scan-damaged names ---

def test_scan_damaged_names_are_repaired_and_flagged():
    assert S.segment_name("8rokerage & Other Services") == "Brokerage & Other Services"
    assert S.name_damaged("8rokerage & Other Services") and not S.name_damaged("Brokerage & Other Services")
    assert S.name_damaged("l'oundit") and S.segment_name("l'oundit") == "oundit"
    assert S.segment_name("b) Fabric 275_76") == "Fabric"                    # a number left in the label still drops
    assert S.segment_name("Smart Infra, Energy and Engineering (refer note 5)") == "Smart Infra, Energy and Engineering"


def test_pl_read_from_the_same_page_never_confirms_it(tmp_path):
    t = S.read_table(q4_page(title="Standalone segment information"), "2025-05-20T18:00:00")   # no unit printed
    con = _store(tmp_path, None)
    con.execute("INSERT INTO fin_quarter_printed VALUES ('X','d','standalone','2025-03-31','quarter','current',"
                "'revenue_from_operations',?,1,7)", (1149.95e7,))
    periods, _scale, _how = S.choose_columns(con, "X", t, [0, 1, 2, 3, 4], "standalone", None, "d", 7)
    assert periods is None                                        # only the same page's P&L: nothing confirms it
    periods, scale, _how = S.choose_columns(con, "X", t, [0, 1, 2, 3, 4], "standalone", None, "d", 9)
    assert scale == 1e7 and periods[0][1] == "Q4FY25"


# --- review round 3 (17 Nov): reconciling lines, inter-segment heading, OCR letter swaps ---

def test_reconciling_lines_and_inter_segment_heading():
    assert S._NOT_SEGMENT.search("Capital & Reserves") and S._NOT_SEGMENT.search("Discontinued operations")
    assert S.block_of("Less: Inter Segment Revenue") is None
    assert S._TOTAL.search("Sub total") and S._TOTAL.search("Sub-Total")


def test_period_from_column_refuses_the_page():
    rows = q4_page()
    rows[1] = sorted(rows[1] + [(700, 20, 736, 28, "period"), (740, 20, 752, 28, "11"), (756, 20, 804, 28, "February"),
                                (808, 20, 832, 28, "2024"), (836, 20, 848, 28, "to"), (852, 20, 912, 28, "31.03.2025")])
    assert S.read_table(rows, "2025-05-20T18:00:00") is None


def test_letter_swap_takes_the_missing_usual_name():
    blocks = {("d1", 1, "standalone", "segment_revenue", "Q1"): {"yarn", "fabric"},
              ("d2", 1, "standalone", "segment_revenue", "Q2"): {"yarn", "fabric"},
              ("d3", 1, "standalone", "segment_revenue", "Q3"): {"yarn", "fabric"},
              ("d4", 1, "standalone", "segment_revenue", "Q4"): {"yam", "fabric"}}
    m = S._swap_ocr(blocks, {"yarn": "yarn", "fabric": "fabric", "yam": "yam"})
    assert m["yam"] == "yarn" and m["fabric"] == "fabric"
    # a genuinely new segment unlike the missing one keeps its name
    blocks[("d4", 1, "standalone", "segment_revenue", "Q4")] = {"textiles", "fabric"}
    assert S._swap_ocr(blocks, {"yarn": "yarn", "fabric": "fabric", "textiles": "textiles"})["textiles"] == "textiles"
