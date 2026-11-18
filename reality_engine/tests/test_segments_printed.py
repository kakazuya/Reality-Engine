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


def test_ensure_unique_with_basis_rebuilds_once_and_allows_both_bases():
    from reality_engine.pilot3 import kpi

    old_ddl = """
    CREATE TABLE kpi_series (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      symbol TEXT NOT NULL, isin TEXT, metric TEXT NOT NULL, dimension TEXT NOT NULL DEFAULT 'total',
      value REAL NOT NULL, unit TEXT NOT NULL, scale REAL NOT NULL DEFAULT 1,
      period_type TEXT NOT NULL, fiscal_period TEXT NOT NULL, as_of_date TEXT,
      basis TEXT NOT NULL DEFAULT 'not_stated', doc_key TEXT NOT NULL, page INTEGER NOT NULL,
      quote TEXT NOT NULL, known_at TEXT, known_at_source TEXT, is_reported INTEGER NOT NULL DEFAULT 1,
      raw_label TEXT, raw_value TEXT, extractor_rule TEXT NOT NULL,
      confidence TEXT NOT NULL DEFAULT 'sentence', conf_rank INTEGER NOT NULL DEFAULT 2,
      method TEXT NOT NULL DEFAULT 'text_layer', ocr_conf REAL,
      source_type TEXT NOT NULL DEFAULT '',
      entity TEXT NOT NULL DEFAULT '',
      UNIQUE(symbol, metric, dimension, fiscal_period, value, unit, doc_key, page)
    );
    CREATE INDEX ix_kpi_sym_metric ON kpi_series(symbol, metric, fiscal_period);
    """
    con = sqlite3.connect(":memory:")
    con.executescript(old_ddl)
    row_vals = (
        "NILKAMAL", "segment_revenue", "lifestyle_furniture_furnishings",
        2273213000.0, "inr", 1.0, "FY", "FY23", "2023-03-31",
        "standalone", "bec16b21.pdf", 13, "Lifestyle Furniture 2,27,32.13",
        "2023-05-20T18:00:00", "doc.known_at", 1, "Lifestyle Furniture", "2,27,32.13",
        "printed_segment_v1", "printed_sum_checked", 4, "table", None, "printed_segment", "NILKAMAL",
    )
    ins = f"INSERT INTO kpi_series(id, {','.join(kpi.COLS)}) VALUES(?, {','.join('?' * len(kpi.COLS))})"
    con.execute(ins, (10, *row_vals))
    row_vals_2 = (*row_vals[:2], "plastics", 900000000.0, *row_vals[4:])
    con.execute(ins, (25, *row_vals_2))
    con.commit()

    before_rows = con.execute("SELECT * FROM kpi_series ORDER BY id").fetchall()
    assert kpi.ensure_unique_with_basis(con) is True
    after_rows = con.execute("SELECT * FROM kpi_series ORDER BY id").fetchall()
    assert after_rows == before_rows
    assert [r[0] for r in after_rows] == [10, 25]
    assert con.execute("SELECT name FROM sqlite_master WHERE type='index' AND name='ix_kpi_sym_metric'").fetchone()

    # same figure, period, doc, and page with the other basis now inserts cleanly
    consol_vals = (*row_vals[:9], "consolidated", *row_vals[10:])
    con.execute(f"INSERT INTO kpi_series({','.join(kpi.COLS)}) VALUES({','.join('?' * len(kpi.COLS))})", consol_vals)
    assert con.execute("SELECT count(*) FROM kpi_series").fetchone()[0] == 3

    # second call is a no-op
    assert kpi.ensure_unique_with_basis(con) is False
    assert con.execute("SELECT id FROM kpi_series ORDER BY id").fetchall() == [(10,), (25,), (26,)]


def test_swap_ocr_ignores_rarer_typo_variant_and_resolves_chain():
    """RSWM: 'yam' (11 blocks) and 'a_yam' (4 blocks) both resolve to 'yarn' (27 blocks)."""
    by_block = {}
    for i in range(27):
        by_block[("doc1", 7, "standalone", "rev", f"P{i}")] = {"fabric", "yarn"}
    for i in range(11):
        by_block[("doc2", 6, "standalone", "rev", f"Q{i}")] = {"fabric", "yam"}
    for i in range(4):
        by_block[("doc3", 11, "standalone", "liab", f"R{i}")] = {"fabric", "a_yam"}
    mapping = {n: n for n in ("fabric", "yarn", "yam", "a_yam")}
    out = S._swap_ocr(by_block, mapping)
    assert out == {"fabric": "fabric", "yarn": "yarn", "yam": "yarn", "a_yam": "yarn"}


def test_choose_columns_accepts_segment_revenue_between_pl_revenue_and_total_income():
    """MICEL: segment revenue including non-interest other income sits within [revenue_from_operations, total_income]."""
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE fin_quarter_printed (symbol TEXT, basis TEXT, period_end TEXT, "
                "period_type TEXT, line_item TEXT, value REAL, scale REAL, doc_key TEXT, page INTEGER)")
    pl_rows = [
        ("MICEL", "standalone", "2026-03-31", "quarter", "revenue_from_operations", 507949000.0, 1.0, "d1", 2),
        ("MICEL", "standalone", "2026-03-31", "quarter", "total_income", 511418000.0, 1.0, "d1", 2),
        ("MICEL", "standalone", "2025-12-31", "quarter", "revenue_from_operations", 126305000.0, 1.0, "d1", 2),
        ("MICEL", "standalone", "2025-12-31", "quarter", "total_income", 127772000.0, 1.0, "d1", 2),
        ("MICEL", "standalone", "2025-03-31", "quarter", "revenue_from_operations", 280672000.0, 1.0, "d1", 2),
        ("MICEL", "standalone", "2025-03-31", "quarter", "total_income", 283737000.0, 1.0, "d1", 2),
        ("MICEL", "standalone", "2026-03-31", "fy", "revenue_from_operations", 872783000.0, 1.0, "d1", 2),
        ("MICEL", "standalone", "2026-03-31", "fy", "total_income", 884402000.0, 1.0, "d1", 2),
        ("MICEL", "standalone", "2025-03-31", "fy", "revenue_from_operations", 617285000.0, 1.0, "d1", 2),
        ("MICEL", "standalone", "2025-03-31", "fy", "total_income", 629469000.0, 1.0, "d1", 2),
    ]
    con.executemany("INSERT INTO fin_quarter_printed VALUES (?,?,?,?,?,?,?,?,?)", pl_rows)
    table = {
        "end": "2026-03-31",
        "decimals": 2,
        "scale": 1e5,
        "anchors": [100.0, 200.0, 300.0, 400.0, 500.0],
        "dates": [(3, 2026), (12, 2025), (3, 2025), (3, 2026), (3, 2025)],
        "cells": [
            S.Cell(metric="_revenue_line", name="", column=0, value=5092.31, raw="5092.31", quote="", repaired=False),
            S.Cell(metric="_revenue_line", name="", column=1, value=1263.20, raw="1263.20", quote="", repaired=False),
            S.Cell(metric="_revenue_line", name="", column=2, value=2810.84, raw="2810.84", quote="", repaired=False),
            S.Cell(metric="_revenue_line", name="", column=3, value=8780.26, raw="8780.26", quote="", repaired=False),
            S.Cell(metric="_revenue_line", name="", column=4, value=6211.04, raw="6211.04", quote="", repaired=False),
        ],
    }
    periods, sc, how = S.choose_columns(con, "MICEL", table, [0, 1, 2, 3, 4], "standalone", 1e5, "d1", 4)
    assert sc == 1e5 and periods is not None
    assert periods[0][1] == "Q4FY26" and periods[3][1] == "FY26"
    assert "total_income" in how


def test_t223_ocr_prefix_and_dominant_target_swap():
    assert S.segment_name("(al Domestic") == "Domestic"
    assert S.segment_name("{bl Overseas") == "Overseas"
    assert S.segment_name("! bl Overseas") == "Overseas"
    assert S.segment_name("l(a) Domestic") == "Domestic"

    by_block = {}
    for i in range(11):
        by_block[(f"d{i}", 7, "consolidated", "segment_ebit", f"FY{i}")] = {"domestic", "overseas"}
    for i in range(4):
        by_block[(f"e{i}", 11, "consolidated", "segment_ebit", f"FY{20+i}")] = {"al_oornesllc", "overseas"}
    by_block[("e99", 11, "consolidated", "segment_ebit", "FY24")] = {"al_domestic", "overseas"}
    mapping = {n: n for n in ("domestic", "overseas", "al_oornesllc", "al_domestic")}
    out = S._swap_ocr(by_block, mapping)
    assert out["al_domestic"] == "domestic"
    assert out["al_oornesllc"] == "domestic"


def test_t223_disaggregates_others_and_preserves_reorg(tmp_path, monkeypatch):
    from reality_engine.pilot3 import kpi

    dim_of = lambda r: S.normalise(r[1])
    own_reorg = [
        ("segment_revenue", "Furniture", "FY24", "FY", "2024-03-31", "standalone", 500e7, "500.00", "", "d1", 1, "2024", True, False),
        ("segment_revenue", "Plastics", "FY24", "FY", "2024-03-31", "standalone", 300e7, "300.00", "", "d1", 1, "2024", True, False),
    ]
    comp_reorg = [
        ("segment_revenue", "B2B Division", "FY24", "FY", "2024-03-31", "standalone", 450e7, "450.00", "", "d2", 1, "2025", False, False),
        ("segment_revenue", "Retail Division", "FY24", "FY", "2024-03-31", "standalone", 350e7, "350.00", "", "d2", 1, "2025", False, False),
    ]
    assert not S._disaggregates_others(own_reorg, comp_reorg, dim_of)

    db = tmp_path / "t_seg.db"
    con = sqlite3.connect(db)
    con.executescript(f"""
    CREATE TABLE company (symbol TEXT, isin TEXT);
    CREATE TABLE doc (doc_key TEXT, doc_type TEXT, filing_date TEXT, known_at TEXT);
    CREATE TABLE doc_page (doc_key TEXT, page INTEGER, text TEXT);
    CREATE TABLE fin_quarter_printed (
        symbol TEXT, doc_key TEXT, basis TEXT, period_end TEXT, period_type TEXT,
        column_role TEXT, line_item TEXT, value REAL, scale REAL, page INTEGER
    );
    CREATE TABLE kpi_series (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        {','.join(f'{c} TEXT' if c in ('symbol','isin','metric','dimension','unit','period_type','fiscal_period','as_of_date','basis','doc_key','quote','known_at','known_at_source','raw_label','raw_value','extractor_rule','confidence','method','source_type','entity') else f'{c} REAL' if c in ('value','scale','ocr_conf') else f'{c} INTEGER' for c in kpi.COLS)},
        UNIQUE(symbol, metric, dimension, fiscal_period, basis, value, unit, doc_key, page)
    );
    """)
    con.execute("INSERT INTO company VALUES ('TESTSEG', 'INE000000099')")
    con.execute("INSERT INTO doc VALUES ('q1_26.pdf', 'results', '2025-09-10', '2025-09-10T10:00:00')")
    con.execute("INSERT INTO doc VALUES ('q1_27.pdf', 'results', '2026-08-06', '2026-08-06T10:00:00')")
    seg_txt = "Consolidated Segment wise Revenue, Results, Assets and Liabilities (Rs. in Crores)"
    doc_txt = f"{seg_txt}\n1. Segment Revenue\n3. Segment Assets"
    con.execute("INSERT INTO doc_page VALUES ('q1_26.pdf', 6, ?)", (doc_txt,))
    con.execute("INSERT INTO doc_page VALUES ('q1_27.pdf', 6, ?)", (doc_txt,))
    con.executemany(
        "INSERT INTO fin_quarter_printed VALUES (?,?,?,?,?,?,?,?,?,?)",
        [
            ("TESTSEG", "q1_26.pdf", "consolidated", "2025-06-30", "quarter", "current", "revenue_from_operations", 125.72e7, 1.0, 2),
            ("TESTSEG", "q1_26.pdf", "consolidated", "2025-03-31", "quarter", "preceding", "revenue_from_operations", 120.00e7, 1.0, 2),
            ("TESTSEG", "q1_26.pdf", "consolidated", "2024-06-30", "quarter", "year_ago", "revenue_from_operations", 115.00e7, 1.0, 2),
            ("TESTSEG", "q1_27.pdf", "consolidated", "2026-06-30", "quarter", "current", "revenue_from_operations", 139.50e7, 1.0, 2),
            ("TESTSEG", "q1_27.pdf", "consolidated", "2026-03-31", "quarter", "preceding", "revenue_from_operations", 132.40e7, 1.0, 2),
            ("TESTSEG", "q1_27.pdf", "consolidated", "2025-06-30", "quarter", "year_ago", "revenue_from_operations", 125.72e7, 1.0, 2),
        ],
    )
    con.commit()
    con.close()

    qcols = (300, 380, 460)
    def _qnum(y, label, *vals):
        return _row(y, (30, label), *[(x + 50 - 6 * len(v), v) for x, v in zip(qcols, vals)])

    p_26 = [
        _row(10, (30, seg_txt)),
        _row(20, (30, "Particulars"), (300, "30.06.2025"), (380, "31.03.2025"), (460, "30.06.2024")),
        _row(36, (30, "1. Segment Revenue")),
        _qnum(48, "a) Packaging Films", "100.00", "96.00", "92.00"),
        _qnum(60, "b) Others", "25.72", "24.00", "23.00"),
        _qnum(72, "Total", "125.72", "120.00", "115.00"),
        _qnum(84, "Net Sales / Income from Operations", "125.72", "120.00", "115.00"),
        _row(100, (30, "3. Segment Assets")),
        _qnum(112, "a) Packaging Films", "500.00", "490.00", "480.00"),
        _qnum(124, "b) Others", "287.82", "280.00", "270.00"),
        _qnum(136, "Total", "787.82", "770.00", "750.00"),
    ]
    p_27 = [
        _row(10, (30, seg_txt)),
        _row(20, (30, "Particulars"), (300, "30.06.2026"), (380, "31.03.2026"), (460, "30.06.2025")),
        _row(36, (30, "1. Segment Revenue")),
        _qnum(48, "a) Packaging Films", "110.00", "105.00", "100.00"),
        _qnum(60, "b) Consumer Care", "4.00", "3.00", "2.48"),
        _qnum(72, "c) Polymer Films", "25.00", "24.00", "22.86"),
        _qnum(84, "d) Others", "0.50", "0.40", "0.38"),
        _qnum(96, "Total", "139.50", "132.40", "125.72"),
        _qnum(108, "Net Sales / Income from Operations", "139.50", "132.40", "125.72"),
        _row(124, (30, "3. Segment Assets")),
        _qnum(136, "a) Packaging Films", "520.00", "510.00", "500.00"),
        _qnum(148, "b) Consumer Care", "120.00", "119.00", "118.52"),
        _qnum(160, "c) Polymer Films", "170.00", "169.50", "169.30"),
        _qnum(172, "Total", "810.00", "798.50", "787.82"),
    ]
    word_map = {
        ("q1_26.pdf", 6): [w for r in p_26 for w in r],
        ("q1_27.pdf", 6): [w for r in p_27 for w in r],
    }
    monkeypatch.setattr(S, "words_for", lambda _db, dk, pg: type("P", (), {"words": word_map[(dk, pg)]})())
    res = S.run_store(db, "tseg", dry=True)
    q1_26 = {(r[1], r[2]): r[3] for r in res["row_list"] if r[7] == "Q1FY26"}
    assert q1_26[("segment_revenue", "consumer_care")] == 2.48e7
    assert q1_26[("segment_revenue", "polymer_films")] == 22.86e7
    assert q1_26[("segment_revenue", "others")] == 0.38e7
    assert q1_26[("segment_assets", "consumer_care")] == 118.52e7
    assert q1_26[("segment_assets", "polymer_films")] == 169.30e7
