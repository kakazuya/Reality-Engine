"""T-223 (2, 3): annual-report notes reader (``pilot3.ar_notes``): headings, blocks, totals, names."""
from __future__ import annotations

from reality_engine.pilot3 import ar_notes as N
from reality_engine.pilot3.ar_statements import Line


def _ln(label, cur=None, prior=None, dec=2):
    vals = [cur, prior]
    return Line(label, vals, dec if cur is not None or prior is not None else 0, label, 1)


def test_headings_and_date_lines():
    assert N.note_of("27 Finance costs") == "finance_costs"
    assert N.note_of("Note 11(b) - Financial Liabilities - Borrowings (Current)") == "borrowings_current"
    assert N.note_of("16 Long term borrowings") == "borrowings_noncurrent"
    assert N.note_of("Note 19: Revenue from Operations") == "revenue_from_operations"
    assert N.note_of("22. Short-Term Borrowings (Contd..)") is None      # a continued half never stands for the note
    assert N.note_of("12 Contract liabilities") is None
    # a column-header date line is not a heading, so it never closes the note above its figures
    assert not N.is_heading("31st March 2026 31st March 2025")
    assert N.note_of("28 Depreciation and amortisation expenses") is None


def test_items_add_up_to_total_and_less_is_subtracted():
    lines = [_ln("Interest expense", 914.04, 756.27), _ln("Other borrowing costs", 18.38, 74.29),
             _ln("Less: capitalised", 10.00, 0.00), _ln("", 922.42, 830.56)]
    got = N.blocks(lines, 0)
    assert len(got) == 1 and got[0][3] == "block" and len(got[0][1]) == 3
    bad = [_ln("Interest expense", 914.04, 756.27), _ln("Other", 18.38, 74.29), _ln("Total", 950.00, 830.56)]
    assert N.blocks(bad, 0) == []                      # does not add up: nothing
    assert len(N.blocks(bad, 1)) == 1                  # the other column does


def test_sub_blocks_and_grand_total():
    # Polyplex-style: (A) secured, (B) unsecured, (A)+(B) grand total
    lines = [_ln("Secured"), _ln("Working capital demand loan from bank"),
             _ln("In foreign currency", 2225.38, 8640.46), _ln("(A)", 2225.38, 8640.46),
             _ln("Unsecured"), _ln("Term loan from bank"), _ln("In rupees", 4100.00, 2200.00),
             _ln("(B)", 4100.00, 2200.00), _ln("(A)+(B)", 6325.38, 10840.46)]
    got = N.blocks(lines, 0)
    assert [b[3] for b in got] == ["block", "block", "grand"] and [b[5] for b in got] == [True, False, False]
    assert [b[4] for b in got[:2]] == ["Secured", "Unsecured"]
    assert got[0][1][0][0] == "Working capital demand loan from bank"   # the caption the item is printed under


def test_noncurrent_current_split_in_one_note():
    lines = [_ln("Non-current"), _ln("Term loans from banks", 500.0, 400.0), _ln("Total", 500.0, 400.0),
             _ln("Current"), _ln("Cash credit", 120.0, 90.0), _ln("Total", 120.0, 90.0)]
    got = N.blocks(lines, 0)
    assert [b[0] for b in got] == ["noncurrent", "current"]


def test_slug_and_caption_tail():
    assert N._slug("Interest on term loan & working capital (Refer note i)") == "interest_on_term_loan_working_capital_refer_note_i"
    assert N._CONT.match("In rupees [refer note (i) below]") and not N._CONT.match("Interest expense")


# --- review round 1 (17 Nov): note totals, sub-tables, basis, pick key ---

def test_block_then_loose_items_then_grand_total():
    # NRAIL / ALICON: 'Total sale of products' is a sub-total; the note total comes after loose items
    lines = [_ln("Domestic sale", 100.0, 90.0), _ln("Export sale", 28.0, 20.0), _ln("Total Sale of Products", 128.0, 110.0),
             _ln("Scrap sales", 2.0, 1.0), _ln("Export incentives", 1.0, 1.0), _ln("Total", 131.0, 112.0)]
    got = N.blocks(lines, 0)
    assert [b[3] for b in got] == ["block", "grand"]
    assert got[0][5] is True and got[1][5] is False          # the first block is followed: never the note total
    # no grand total that adds up: the lone block is followed by figures, so it is a sub-total
    lines[-1] = _ln("Total", 140.0, 112.0)
    got = N.blocks(lines, 0)
    assert [b[3] for b in got] == ["block"] and got[0][5] is True


def test_sub_tables_end_the_note_and_contd_closes():
    from reality_engine.pilot3.ar_notes import _SUBTABLE
    assert _SUBTABLE.search("Disaggregation of revenue by sales channel")
    assert _SUBTABLE.search("Reconciliation of revenue with contract price")
    assert _SUBTABLE.search("Revenue as per Geography") and not _SUBTABLE.search("Sale of products")


def test_basis_from_title_phrases_never_prose():
    assert N.title_basis("Notes to the Consolidated Financial Statements for the year") == "consolidated"
    assert N.title_basis("NOTES FORMING PART OF STANDALONE FINANCIAL STATEMENTS") == "standalone"
    assert N.title_basis("The order book is tracked at consolidated level by the Board") is None
    assert N.title_basis("Standalone Balance Sheet ... Consolidated Balance Sheet") is None


def test_pick_key_and_caption_prose():
    assert N.note_of_row("borrowings_current_subtotal:secured_a") == "borrowings_current"
    assert N.note_of_row("finance_costs_total") == "finance_costs"
    assert N.note_of_row("revenue_from_operations:sale_of_products") == "revenue_from_operations"
    lines = [_ln("reportable segment of the Group."), _ln("Sale of goods", 10.0, 9.0), _ln("Total", 10.0, 9.0)]
    assert N.blocks(lines, 0)[0][1][0][0] == ""                # a sentence is never a caption


# --- review round 2 (17 Nov): Non - current, four columns, joined total, zero columns, Less caption ---

def test_non_current_with_spaces_and_four_columns():
    assert N.note_of("19. Non - current financial liabilities - Borrowings") == "borrowings_noncurrent"
    assert N.note_of("14 Borrowings") == "borrowings_unclassified"
    assert N.four_columns("Particulars Current Non-Current Current Non-Current")
    assert not N.four_columns("Non-current borrowings")


def test_total_joined_to_the_next_sub_block_caption():
    lines = [_ln("(i) Non-current"), _ln("Secured term loans", 176.95, 100.0), _ln("Total (ii) Current", 176.95, 100.0),
             _ln("Working capital loans", 756.09, 500.0), _ln("Total", 756.09, 500.0)]
    assert [b[0] for b in N.blocks(lines, 0)] == ["noncurrent", "current"]


def test_less_caption_and_all_zero_column():
    lines = [_ln("Rupee term loan", 3000.0, 0.0), _ln("Less: Current portion"), _ln("Rupee term loan", 1000.0, 0.0),
             _ln("Total", 2000.0, 0.0)]
    got = N.blocks(lines, 0)
    assert len(got) == 1 and got[0][1][1][1].label.startswith("Less:")
    assert N.blocks(lines, 1) == []                          # 0 - 0 = 0 proves nothing


# --- T-223 review defects (D1, D2, D3, D5) ---

def _wline(y: float, *cells: tuple[float, str]) -> list[tuple[float, float, float, float, str]]:
    """Synthetic word boxes for one printed line: (x, text) pairs."""
    out = []
    for x, text in cells:
        for word in text.split(" "):
            out.append((x, y, x + 6 * len(word), y + 8, word))
            x += 6 * len(word) + 4
    return out


def test_d1_two_up_page_crops_to_own_block(monkeypatch):
    # Left half: trade payables ageing table; right half: Note 19 Borrowings closed by Note 20 on a shared y-line
    words = (
        _wline(20, (40, "Notes to Consolidated Financial Statements"))
        + _wline(40, (40, "NOTE 17 : TRADE PAYABLES"), (640, "NOTE 19 : BORROWINGS"))
        + _wline(54, (40, "Ageing schedule of trade payable"), (1080, "in Lakhs"))
        + _wline(68, (200, "Not due"), (350, "Total"), (640, "Particulars"), (960, "March 31, 2026"), (1080, "March 31, 2025"))
        + _wline(82, (40, "Undisputed Dues MSME"), (200, "10.00"), (350, "10.00"), (640, "Cash credit"), (980, "100.00"), (1100, "50.00"))
        + _wline(96, (40, "Undisputed Dues Others"), (200, "20.00"), (350, "20.00"), (640, "Term loans"), (980, "200.00"), (1100, "150.00"))
        + _wline(110, (40, "Current Trade Payables"), (200, "30.00"), (350, "30.00"), (640, "Total"), (980, "300.00"), (1100, "200.00"))
        + _wline(124, (40, "Payables other"), (350, "999.00"), (640, "NOTE 20 : OTHER FINANCIAL LIABILITIES"))
        + _wline(138, (640, "Deferred income"), (980, "500.00"), (1100, "400.00"))
        + _wline(152, (640, "Total"), (980, "500.00"), (1100, "400.00"))
    )
    monkeypatch.setattr(N, "words_for", lambda *a, **k: type("P", (), {"words": words})())
    rows, _log = N.read_page("x.db", "doc", 1, "2026-06-01", None)
    items = {(r.fiscal_year, r.line_item): r.value for r in rows}
    assert items[("FY26", "borrowings_unclassified:cash_credit")] == 100.0
    assert items[("FY26", "borrowings_unclassified:term_loans")] == 200.0
    assert items[("FY26", "borrowings_unclassified_total")] == 300.0
    assert not any("trade" in r.line_item or "undisputed" in r.line_item or "deferred" in r.line_item for r in rows)

    # Also when the target note sits on the LEFT half and another table sits on the RIGHT half
    left_words = (
        _wline(20, (40, "Notes to Standalone Financial Statements"))
        + _wline(40, (40, "19. Borrowings (Current)"), (640, "20. Trade Payables"))
        + _wline(54, (440, "in Lakhs"), (1080, "in Lakhs"))
        + _wline(68, (40, "Particulars"), (340, "March 31, 2026"), (450, "March 31, 2025"),
                 (640, "Particulars"), (960, "March 31, 2026"), (1080, "March 31, 2025"))
        + _wline(82, (40, "Cash credit"), (360, "120.00"), (470, "80.00"), (640, "MSME dues"), (980, "50.00"), (1100, "40.00"))
        + _wline(96, (40, "Total"), (360, "120.00"), (470, "80.00"), (640, "Total"), (980, "50.00"), (1100, "40.00"))
    )
    monkeypatch.setattr(N, "words_for", lambda *a, **k: type("P", (), {"words": left_words})())
    lrows, _ = N.read_page("x.db", "doc", 1, "2026-06-01", None)
    assert {(r.fiscal_year, r.line_item): r.value for r in lrows}[("FY26", "borrowings_current_total")] == 120.0


def test_d2_unit_from_above_first_figure_never_footnote(monkeypatch):
    words = (
        _wline(20, (40, "Notes to Standalone Financial Statements"))
        + _wline(40, (40, "13. Borrowings (non-current)"))
        + _wline(54, (420, "(Rs. in million)"))
        + _wline(68, (40, "Particulars"), (320, "December 31, 2025"), (440, "December 31, 2024"))
        + _wline(82, (40, "Motor vehicle loan"), (350, "27.26"), (470, "24.47"))
        + _wline(96, (40, "Total"), (350, "27.26"), (470, "24.47"))
        + _wline(110, (40, "Notes: Issued debentures of face value of Rs. 1 Lakh each."))
    )
    monkeypatch.setattr(N, "words_for", lambda *a, **k: type("P", (), {"words": words})())
    rows, _ = N.read_page("x.db", "doc", 1, "2026-03-01", None)
    assert rows and all(r.unit == "inr_million" for r in rows)


def test_d3_marker_combination_grand_total_stays_total_when_followed():
    lines = [
        _ln("Secured"), _ln("Working capital loan", 2225.38, 8640.46), _ln("(A)", 2225.38, 8640.46),
        _ln("Unsecured"), _ln("Term loan", 4100.00, 2200.00), _ln("(B)", 4100.00, 2200.00),
        _ln("Current maturities", 650.00, 0.0), _ln("(C)", 650.00, 0.0),
        _ln("(A)+(B)+(C)", 6975.38, 10840.46),
        _ln("Interest rate footnote", 180.00, 180.00),
    ]
    got = N.blocks(lines, 0)
    assert got[-1][3] == "grand" and got[-1][5] is False
    # Same for 'Total (a+b)' and 'Total borrowing (A+B)'
    lines2 = [
        _ln("Loan 1", 15.84, 13.01), _ln("Total - Secured (A)", 15.84, 13.01),
        _ln("Loan 2", 2675.91, 0.0), _ln("Total - Unsecured (B)", 2675.91, 0.0),
        _ln("Total borrowing (A+B)", 2691.75, 13.01),
        _ln("Footnote number", 36.0, 36.0),
    ]
    got2 = N.blocks(lines2, 0)
    assert got2[-1][3] == "grand" and got2[-1][5] is False
    # A plain 'Total' (not a marker combination) followed by figures still gets followed=True
    lines3 = [_ln("Loan 1", 10.0, 10.0), _ln("(A)", 10.0, 10.0), _ln("Total", 10.0, 10.0), _ln("Extra", 5.0, 5.0)]
    assert N.blocks(lines3, 0)[-1][5] is True


def test_d5_prose_lines_never_open_a_note():
    assert N.note_of("19. Non - current financial liabilities - Borrowings") == "borrowings_noncurrent"
    assert N.note_of("Note 11(b) - Financial Liabilities - Borrowings (Current)") == "borrowings_current"
    assert N.note_of("2. Debt-Equity Ratio: Debt (includes Borrowings and Current & Non-Current Lease Liabilities)") is None
    assert N.note_of("2. Debt-Equity Ratio: Debt (includes Borrowings)") is None
    assert N.note_of("31 Amount of total borrowings (long-term and short-term) of the related party") is None
    assert N.note_of("31 Amount of total borrowings") is None
    assert N.note_of("21.1 Details of the secured long-term borrowings:") is None
    assert N.note_of("19. " + "Non-current financial liabilities - Borrowings " * 2) is None


# --- T-223 review defects L1 & L2 (abbreviated date headers, figures-only totals) ---

def test_l1_abbreviated_date_headers_not_headings_and_read_as_columns(monkeypatch):
    for hdr in ("31-Mar-2025 31-Mar-2024", "31–Mar–2025 31–Mar–2024", "31-Mar-25 31-Mar-24", "Mar-25 Mar-24"):
        assert not N.is_heading(hdr)
        w = _wline(20, (40, "Particulars"), (340, hdr.split()[0]), (440, hdr.split()[1]))
        cols = N._columns(w, N.lines_of(w))
        assert cols and cols[1] == ["2025-03-31", "2024-03-31"]

    words = (
        _wline(20, (40, "Notes to the Consolidated Financial Statements"))
        + _wline(40, (40, "24 REVENUE FROM OPERATIONS"))
        + _wline(54, (420, "(Rs in Crores)"))
        + _wline(68, (340, "31-Mar-2025"), (440, "31-Mar-2024"))
        + _wline(82, (40, "a) Sale of Products"), (350, "493.14"), (450, "437.77"))
        + _wline(96, (40, "b) Other Operating Revenues"), (350, "4.69"), (450, "13.61"))
        + _wline(110, (40, "TOTAL"), (350, "497.83"), (450, "451.38"))
    )
    monkeypatch.setattr(N, "words_for", lambda *a, **k: type("P", (), {"words": words})())
    rows, _ = N.read_page("x.db", "doc", 1, "2025-08-20", None)
    by = {(r.fiscal_year, r.line_item): r.value for r in rows}
    assert by[("FY25", "revenue_from_operations:a_sale_of_products")] == 493.14
    assert by[("FY24", "revenue_from_operations:b_other_operating_revenues")] == 13.61
    assert by[("FY25", "revenue_from_operations_total")] == 497.83
    assert all(r.unit == "inr_crore" and r.basis == "consolidated" for r in rows)

    # Also when heading and abbreviated dates sit on the same line, or 2-digit year columns
    same_line = (
        _wline(20, (40, "Notes to Standalone Financial Statements"))
        + _wline(40, (40, "24 REVENUE FROM OPERATIONS"), (340, "31-Mar-24"), (440, "31-Mar-23"))
        + _wline(54, (420, "(Rs in Lakhs)"))
        + _wline(68, (40, "a) Sale of Products"), (350, "100.00"), (450, "80.00"))
        + _wline(82, (40, "TOTAL"), (350, "100.00"), (450, "80.00"))
    )
    monkeypatch.setattr(N, "words_for", lambda *a, **k: type("P", (), {"words": same_line})())
    srows, _ = N.read_page("x.db", "doc", 1, "2024-07-13", None)
    assert {(r.fiscal_year, r.line_item): r.value for r in srows}[("FY24", "revenue_from_operations_total")] == 100.0


def test_l2_figures_only_total_line_kept_as_total_candidate(monkeypatch):
    words = (
        _wline(20, (40, "Notes to Consolidated Financial Statements"))
        + _wline(40, (40, "13. Borrowings (non-current)"))
        + _wline(54, (420, "(H in million)"))
        + _wline(68, (40, "Particulars"), (320, "December 31, 2023"), (440, "December 31, 2022"))
        + _wline(82, (40, "Term loans"))
        + _wline(96, (40, "- Motor vehicle loan"), (350, "27.58"), (470, "20.44"))
        + _wline(110, (40, "Less:"))
        + _wline(124, (40, "Current maturities of term loans"), (350, "10.64"), (470, "7.21"))
        + _wline(138, (350, "16.94"), (470, "13.23"))
        + _wline(152, (40, "Notes: Repayable in monthly instalments."))
        + _wline(180, (470, "227"))
    )
    monkeypatch.setattr(N, "words_for", lambda *a, **k: type("P", (), {"words": words})())
    rows, _ = N.read_page("x.db", "doc", 1, "2024-05-17", None)
    by = {(r.fiscal_year, r.line_item): r.value for r in rows}
    assert by[("FY23", "borrowings_noncurrent:term_loans_motor_vehicle_loan")] == 27.58
    assert by[("FY23", "borrowings_noncurrent:less_current_maturities_of_term_loans")] == -10.64
    assert by[("FY23", "borrowings_noncurrent_total")] == 16.94
    assert by[("FY22", "borrowings_noncurrent_total")] == 13.23
    assert not any("227" in r.caption or r.value == 227.0 for r in rows)


# --- T-223 review round 5 defects (D1: transacted-price subtable, D2: two-section grand total, D3: prose followed) ---

def test_d1_breakup_and_transacted_price_subtable_ends_note(monkeypatch):
    words = (
        _wline(20, (40, "Notes to Standalone Financial Statements"))
        + _wline(40, (40, "24 REVENUE FROM OPERATIONS"))
        + _wline(54, (320, "Year ended 31-03-2024"), (440, "Year ended 31-03-2023"))
        + _wline(68, (350, "` crores"), (470, "` crores"))
        + _wline(82, (40, "A) REVENUE FROM SALE OF PRODUCTS"))
        + _wline(96, (40, "Paper and Paper Boards"))
        + _wline(110, (40, "India"), (350, "1535.96"), (470, "1642.90"))
        + _wline(124, (40, "Rest of the World"), (350, "216.80"), (470, "379.84"))
        + _wline(138, (350, "1752.76"), (470, "2022.74"))
        + _wline(152, (40, "Stock in Trade"))
        + _wline(166, (40, "India"), (350, "27.31"), (470, "28.78"))
        + _wline(180, (350, "1780.07"), (470, "2051.52"))
        + _wline(194, (40, "Break-up of Revenue from Sale of Products -"))
        + _wline(208, (40, "Transacted Price and adjustments"))
        + _wline(222, (40, "Sales Value at Transacted price"), (350, "1885.11"), (470, "2161.75"))
        + _wline(236, (40, "Less : Adjustments:"))
        + _wline(250, (40, "Cash Discount"), (350, "38.79"), (470, "47.97"))
        + _wline(264, (40, "Other Discounts / Incentives"), (350, "66.25"), (470, "62.26"))
        + _wline(278, (350, "105.04"), (470, "110.23"))
        + _wline(292, (350, "1780.07"), (470, "2051.52"))
    )
    monkeypatch.setattr(N, "words_for", lambda *a, **k: type("P", (), {"words": words})())
    rows, _ = N.read_page("x.db", "doc", 1, "2024-08-01", None)
    assert N._SUBTABLE.search("Break-up of Revenue from Sale of Products -")
    assert N._SUBTABLE.search("Contract price adjustments")
    assert not any("transacted" in r.line_item or "discount" in r.line_item for r in rows)
    fy24_items = [r for r in rows if r.fiscal_year == "FY24" and "_total" not in r.line_item and "_subtotal" not in r.line_item]
    fy24_tot = [r for r in rows if r.fiscal_year == "FY24" and r.line_item == "revenue_from_operations_total"]
    assert len(fy24_tot) == 1 and abs(sum(r.value for r in fy24_items) - fy24_tot[0].value) < 1e-6


def test_d2_two_section_borrowings_without_note_total_writes_no_grand_total(monkeypatch):
    # c53 KABRAEXTRU style: Long term (1107.39 - 544.90 = 562.49) then Current (4449.39 + 3000 + 544.90 = 7994.29),
    # with no overall note total: neither section total may become borrowings_unclassified_total.
    words = (
        _wline(20, (40, "Notes to Standalone Financial Statements"))
        + _wline(40, (40, "17 Borrowings"))
        + _wline(54, (420, "(Amount in Lakhs)"))
        + _wline(68, (340, "31 March 2024"), (460, "31 March 2023"))
        + _wline(82, (40, "Long term borrowing"))
        + _wline(96, (40, "Secured"), (350, "1,107.39"), (470, "1,689.95"))
        + _wline(110, (350, "1,107.39"), (470, "1,689.95"))
        + _wline(124, (40, "Less - Current maturity of long term borrowing"), (350, "544.90"), (470, "574.45"))
        + _wline(138, (350, "562.49"), (470, "1,115.49"))
        + _wline(152, (40, "Loans repayable on demand"))
        + _wline(166, (40, "Secured (ii)"), (350, "4,449.39"), (470, "2,712.23"))
        + _wline(180, (40, "Unsecured"), (350, "3,000.00"), (470, "2,996.01"))
        + _wline(194, (350, "7,449.39"), (470, "5,708.24"))
        + _wline(208, (40, "Add - Current maturity of long term borrowing"), (350, "544.90"), (470, "574.45"))
        + _wline(222, (350, "7,994.29"), (470, "6,282.69"))
    )
    monkeypatch.setattr(N, "words_for", lambda *a, **k: type("P", (), {"words": words})())
    rows, _ = N.read_page("x.db", "doc", 1, "2024-08-01", None)
    assert rows and not any(r.line_item == "borrowings_unclassified_total" for r in rows)


def test_d3_prose_footnote_number_never_sets_followed(monkeypatch):
    words = (
        _wline(20, (40, "Notes to Consolidated Financial Statements"))
        + _wline(40, (40, "13. Borrowings (non-current)"))
        + _wline(54, (420, "(H in million)"))
        + _wline(68, (40, "Particulars"), (320, "December 31, 2023"), (440, "December 31, 2022"))
        + _wline(82, (40, "Term loans"))
        + _wline(96, (40, "- Motor vehicle loan"), (350, "27.58"), (470, "20.44"))
        + _wline(110, (40, "Less: Current maturities of term loans"), (350, "10.64"), (470, "7.21"))
        + _wline(124, (350, "16.94"), (470, "13.23"))
        + _wline(138, (40, "per annum. The term loans are repayable in equated monthly instalments ranging from"),
                 (350, "36"), (400, "to 60 months from the date of loan."))
    )
    monkeypatch.setattr(N, "words_for", lambda *a, **k: type("P", (), {"words": words})())
    rows, _ = N.read_page("x.db", "doc", 1, "2024-05-17", None)
    by = {(r.fiscal_year, r.line_item): r.value for r in rows}
    assert by[("FY23", "borrowings_noncurrent_total")] == 16.94
    assert by[("FY22", "borrowings_noncurrent_total")] == 13.23
    assert not any("227" in r.caption or r.value == 227.0 for r in rows)


# --- T-223 review round 6 (tie-out gate, B1 two-up/figure heading, B2 breakups, B3 subtable skip, B4 header days, B5 section) ---

def test_tie_out_gate_disagree_rejects_and_no_face_marks_definition(monkeypatch):
    words = (
        _wline(20, (40, "Notes to Consolidated Financial Statements"))
        + _wline(40, (40, "24. Revenue from operations"))
        + _wline(54, (420, "(H in Lakhs)"))
        + _wline(68, (320, "31 March 2025"), (440, "31 March 2024"))
        + _wline(82, (40, "Sale of products"), (350, "400.00"), (470, "300.00"))
        + _wline(96, (40, "Other operating revenue"), (350, "100.00"), (470, "50.00"))
        + _wline(110, (40, "Total"), (350, "500.00"), (470, "350.00"))
    )
    monkeypatch.setattr(N, "words_for", lambda *a, **k: type("P", (), {"words": words})())
    # FY25 tied (500 lakh == 5.0e7 INR); FY24 disagrees (350 lakh vs 900 lakh); no face -> definition annotated
    face = {("FY25", "consolidated", "revenue_from_operations"): (50000000.0, 1.0, "inr"),
            ("FY24", "consolidated", "revenue_from_operations"): (90000000.0, 1.0, "inr")}
    rows, log = N.read_page("x.db", "doc", 1, "2025-05-20", None, face_targets=face)
    assert {r.fiscal_year for r in rows} == {"FY25"}
    assert all(r.tie_status == "tied" and "not tied to a statement figure" not in r.definition for r in rows)
    assert any(l["why"] == "total does not tie to the statement" for l in log)

    rows_nf, _ = N.read_page("x.db", "doc", 1, "2025-05-20", None, face_targets={})
    assert len({r.fiscal_year for r in rows_nf}) == 2
    assert all(r.tie_status == "no_face" and "not tied to a statement figure" in r.definition for r in rows_nf)


def test_b1_twoup_figure_statement_line_is_not_heading(monkeypatch):
    # c17 p82 pattern: two-up BS (left) | P&L (right), same y-line merges '1. Non Current Assets' + 'Revenue from Operations 31 59,461.09 49,433.28'.
    # Neither the merged line nor the right statement chunk may open a revenue note; parenthetical '(Refer Note 3, 4 and 5.2)' remains valid heading.
    assert not N.is_heading("1. Non Current Assets Revenue from Operations 31 59,461.09 49,433.28")
    assert not N.is_heading("Revenue from Operations 31 59,461.09 49,433.28")
    assert N.is_heading("23. Depreciation / Amortization (Refer Note 3, 4 and 5.2)")
    words = (
        _wline(20, (40, "CONSOLIDATED BALANCE SHEET"), (320, "CONSOLIDATED STATEMENT OF PROFIT AND LOSS"))
        + _wline(40, (40, "Particulars"), (200, "31 March 2025"), (260, "31 March 2024"),
                 (320, "Particulars"), (500, "31 March 2025"), (580, "31 March 2024"))
        + _wline(54, (40, "1. Non Current Assets"), (320, "Revenue from Operations"), (470, "31"), (510, "59,461.09"), (590, "49,433.28"))
        + _wline(68, (40, "Property Plant"), (200, "10,000.00"), (260, "9,000.00"))
        + _wline(82, (40, "Total"), (200, "10,000.00"), (260, "9,000.00"))
    )
    monkeypatch.setattr(N, "words_for", lambda *a, **k: type("P", (), {"words": words})())
    rows, _ = N.read_page("x.db", "doc", 82, "2025-05-20", "consolidated", face_targets={})
    assert rows == []


def test_b2_comprises_details_of_sales_and_duplicate_total_block_dropped(monkeypatch):
    # Trailing 'Details of Sales' / 'Sale of products comprises' / 'Products-wise Sales' must be dropped after main total,
    # and a duplicate-total alternative break-up (c19 style) must stop without doubling items.
    words_rev = (
        _wline(20, (40, "Notes to Standalone Financial Statements"))
        + _wline(40, (40, "20 Revenue from Operations :"))
        + _wline(54, (420, "(Rs in Lakhs)"))
        + _wline(68, (320, "31 March 2025"), (440, "31 March 2024"))
        + _wline(82, (40, "a) Export"), (350, "360.60"), (470, "-"))
        + _wline(96, (40, "b) Domestic"), (350, "444.14"), (470, "82.67"))
        + _wline(110, (40, "Total"), (350, "804.74"), (470, "82.67"))
        + _wline(124, (40, "Details of Sales"))
        + _wline(138, (40, "IT Related Services"), (350, "804.74"), (470, "82.17"))
        + _wline(152, (40, "IT Related Goods"), (350, "-"), (470, "0.50"))
        + _wline(166, (40, "Total"), (350, "804.74"), (470, "82.67"))
    )
    monkeypatch.setattr(N, "words_for", lambda *a, **k: type("P", (), {"words": words_rev})())
    r_rev, _ = N.read_page("x.db", "doc", 91, "2025-05-20", None, face_targets={})
    fy25 = [r for r in r_rev if r.fiscal_year == "FY25"]
    assert not any("it_related" in r.line_item for r in fy25)
    assert sum(r.value for r in fy25 if "_total" not in r.line_item) == 804.74

    words_dup = (
        _wline(20, (40, "Notes to Standalone Financial Statements"))
        + _wline(40, (40, "22. BORROWINGS (CURRENT)"))
        + _wline(54, (420, "(Rs in Million)"))
        + _wline(68, (320, "31st March, 2024"), (440, "31st March, 2023"))
        + _wline(82, (40, "Working Capital Loans"), (350, "3000.00"), (470, "2500.00"))
        + _wline(96, (40, "Bill Discounted"), (350, "500.00"), (470, "400.00"))
        + _wline(110, (40, "Total"), (350, "3500.00"), (470, "2900.00"))
        + _wline(124, (40, "Borrowings - Bill Discounted"), (350, "500.00"), (470, "400.00"))
        + _wline(138, (40, "Borrowings - Others"), (350, "3000.00"), (470, "2500.00"))
        + _wline(152, (40, "Total"), (350, "3500.00"), (470, "2900.00"))
    )
    monkeypatch.setattr(N, "words_for", lambda *a, **k: type("P", (), {"words": words_dup})())
    r_dup, _ = N.read_page("x.db", "doc", 139, "2024-05-20", None, face_targets={})
    fy24 = [r for r in r_dup if r.fiscal_year == "FY24"]
    assert any(r.line_item == "borrowings_current_total" and r.value == 3500.0 for r in fy24)
    assert abs(sum(r.value for r in fy24 if r.line_item != "borrowings_current_total") - 3500.0) < 1e-6


def test_b3_internal_subtable_skipped_to_outer_section_b(monkeypatch):
    # c83 p205: A) 1780.07 -> Break-up / Transacted Price sub-table -> B) OTHER OPERATING INCOME 21.49 -> Total 1801.56
    words = (
        _wline(20, (40, "Notes to Standalone Financial Statements"))
        + _wline(40, (40, "24 REVENUE FROM OPERATIONS"))
        + _wline(54, (320, "Year ended 31-03-2024"), (440, "Year ended 31-03-2023"))
        + _wline(68, (350, "` crores"), (470, "` crores"))
        + _wline(82, (40, "A) REVENUE FROM SALE OF PRODUCTS"))
        + _wline(96, (40, "Paper India"), (350, "1752.76"), (470, "2022.74"))
        + _wline(110, (40, "Stock in Trade"), (350, "27.31"), (470, "28.78"))
        + _wline(124, (350, "1780.07"), (470, "2051.52"))
        + _wline(138, (40, "Break-up of Revenue from Sale of Products -"))
        + _wline(152, (40, "Transacted Price and adjustments"))
        + _wline(166, (40, "Sales Value at Transacted price"), (350, "1885.11"), (470, "2161.75"))
        + _wline(180, (40, "Less: Cash Discount"), (350, "105.04"), (470, "110.23"))
        + _wline(194, (350, "1780.07"), (470, "2051.52"))
        + _wline(208, (40, "B) OTHER OPERATING INCOME"))
        + _wline(222, (40, "Export Benefits"), (350, "4.68"), (470, "8.22"))
        + _wline(236, (40, "Sale of Scrap"), (350, "16.81"), (470, "22.79"))
        + _wline(250, (350, "21.49"), (470, "31.01"))
        + _wline(264, (350, "1801.56"), (470, "2082.53"))
    )
    monkeypatch.setattr(N, "words_for", lambda *a, **k: type("P", (), {"words": words})())
    rows, _ = N.read_page("x.db", "doc", 205, "2024-08-01", None, face_targets={})
    fy24 = {r.line_item: r.value for r in rows if r.fiscal_year == "FY24"}
    assert fy24["revenue_from_operations_total"] == 1801.56
    assert fy24["revenue_from_operations:export_benefits"] == 4.68
    assert not any("transacted" in k or "discount" in k for k in fy24)


def test_b4_header_lines_with_day_numbers_dropped(monkeypatch):
    # c01 p158: wrapped date header leaves 'Particulars March March' + [31.0, 31.0] (and split '2025 2024')
    words = (
        _wline(20, (40, "Notes to Consolidated Financial Statements"))
        + _wline(40, (40, "Note 24 Finance costs"))
        + _wline(54, (420, "(Rs. in lakhs)"))
        + _wline(68, (340, "As at"), (460, "As at"))
        + _wline(82, (40, "Particulars"), (150, "March"), (210, "March"), (350, "31"), (470, "31"))
        + _wline(96, (340, "2025"), (460, "2024"))
        + _wline(110, (40, "Banks"), (350, "3,078.00"), (470, "2,500.00"))
        + _wline(124, (40, "Other bank charges"), (350, "1,670.37"), (470, "1,500.00"))
        + _wline(138, (40, "Total"), (350, "4,748.37"), (470, "4,000.00"))
    )
    monkeypatch.setattr(N, "words_for", lambda *a, **k: type("P", (), {"words": words})())
    rows, _ = N.read_page("x.db", "doc", 158, "2025-05-30", None, face_targets={})
    fy25 = {r.line_item: r.value for r in rows if r.fiscal_year == "FY25"}
    assert fy25["finance_costs_total"] == 4748.37
    assert not any("march" in k or "particulars" in k for k in fy25)


def test_b5_bs_section_heading_classifies_generic_borrowings(monkeypatch):
    # c91 p139: CURRENT LIABILITIES above NOTE 23 : BORROWINGS classifies it as borrowings_current (not unclassified)
    words = (
        _wline(20, (40, "Notes to Consolidated Financial Statements"))
        + _wline(40, (40, "CURRENT LIABILITIES"))
        + _wline(54, (40, "FINANCIAL LIABILITIES"))
        + _wline(68, (40, "NOTE 23 : BORROWINGS"))
        + _wline(82, (420, "(Rs. in Lakhs)"))
        + _wline(96, (320, "31 March 2024"), (440, "31 March 2023"))
        + _wline(110, (40, "Working capital loans from banks"), (350, "21,449.13"), (470, "19,047.48"))
        + _wline(124, (40, "Total"), (350, "21,449.13"), (470, "19,047.48"))
    )
    monkeypatch.setattr(N, "words_for", lambda *a, **k: type("P", (), {"words": words})())
    rows, _ = N.read_page("x.db", "doc", 139, "2024-05-20", None, face_targets={})
    assert {r.line_item for r in rows} == {"borrowings_current:working_capital_loans_from_banks", "borrowings_current_total"}

