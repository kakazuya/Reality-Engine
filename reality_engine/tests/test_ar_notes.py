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


# --- T-223 review round 8 (face ranking / last_fy / quote check, unit prose guard, XBRL differs, slug/subtotal style) ---

def test_r8_face_loader_priority_last_fy_malformed_and_quote_filter(tmp_path):
    import sqlite3
    db = tmp_path / "store.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE fin_annual_line (fiscal_year TEXT, basis TEXT, statement TEXT, line_item TEXT, caption TEXT, quote TEXT, value REAL, unit TEXT, scale REAL, source_table TEXT, doc_key TEXT, known_at TEXT, period_type TEXT)")
    conn.execute("CREATE TABLE fin_quarter_printed (fiscal_period TEXT, period_type TEXT, column_role TEXT, basis TEXT, statement TEXT, line_item TEXT, caption TEXT, quote TEXT, value REAL, unit TEXT, scale REAL, raw_token TEXT, check_status TEXT, doc_key TEXT, known_at TEXT)")
    # 1. Own filing (ytd, earlier known_at) beats later prior_ytd even when both unchecked (c46)
    conn.execute("INSERT INTO fin_quarter_printed VALUES ('FY24','fy','ytd','consolidated','P&L','finance_cost','Finance costs','',406872000,'inr',1.0,'4,068.72','unchecked','q4_24','2024-05-16')")
    conn.execute("INSERT INTO fin_quarter_printed VALUES ('FY24','fy','prior_ytd','consolidated','P&L','finance_cost','Finance costs','',405272000,'inr',1.0,'405272','unchecked','q4_25','2025-05-12')")
    # 2. last_fy is loaded (c01 FY24), unchecked malformed token '2,55039.9' is dropped (c74)
    conn.execute("INSERT INTO fin_quarter_printed VALUES ('FY24','fy','last_fy','standalone','P&L','finance_cost','Finance cost','',488319000,'inr',1.0,'4,883.19','repeat_ok','q2_25','2024-11-11')")
    conn.execute("INSERT INTO fin_quarter_printed VALUES ('FY23','fy','prior_ytd','standalone','P&L','revenue_from_operations','Revenue from operations','',2550399000,'inr',1.0,'2,55039.9','unchecked','q4_24','2024-05-30')")
    # 3. 'Total Revenue' / 'Total Income from operations' skipped for revenue_from_operations (c41, c44)
    conn.execute("INSERT INTO fin_annual_line VALUES ('FY25','standalone','P&L','revenue_from_operations','Total Revenue','Total Revenue 15215.46',15215.46,'inr_lakh',100000.0,'ar_facts','ar25','2025-08-18','FY')")
    conn.execute("INSERT INTO fin_quarter_printed VALUES ('FY24','fy','ytd','standalone','P&L','revenue_from_operations','(a) Revenue from operations','Total Income from operations (a+b) 2,384.88',23848800000,'inr',1.0,'2,384.88','repeat_ok','q4_24','2024-04-24')")
    conn.commit()
    conn.close()

    ft = N.load_face_targets(str(db))
    assert ft[("FY24", "consolidated", "finance_costs")][0].inr == 406872000.0
    assert ft[("FY24", "standalone", "finance_costs")][0].inr == 488319000.0
    assert ("FY23", "standalone", "revenue_from_operations") not in ft
    assert ("FY25", "standalone", "revenue_from_operations") not in ft
    assert ("FY24", "standalone", "revenue_from_operations") not in ft


def test_r8_unit_ignores_prose_with_amount_c18_p172(monkeypatch):
    # c18 p172: page unit is '(All amounts are in ₹ Lakhs ...)', sentence above note 18 has 'Rs. 3.70 Crores'
    words = (
        _wline(20, (40, "Notes on Financial Statements for the year ended 31st March, 2026"))
        + _wline(34, (40, "(All amounts are in ₹ Lakhs except unless otherwise stated)"))
        + _wline(54, (40, "-Pledge of FDR of Rs. 3.70 Crores in the name of SVG Fashions Pvt. Ltd."))
        + _wline(74, (40, "18 Short Term Borrowings"))
        + _wline(88, (320, "As at 31st March, 2026"), (460, "As at 31st March, 2025"))
        + _wline(102, (40, "Working Capital Loans"), (350, "258.31"), (470, "2,496.65"))
        + _wline(116, (40, "Inter-Corporate Loans"), (350, "3,121.52"), (470, "3,275.08"))
        + _wline(130, (40, "Total"), (350, "3,379.83"), (470, "5,771.73"))
    )
    monkeypatch.setattr(N, "words_for", lambda *a, **k: type("P", (), {"words": words})())
    rows, _ = N.read_page("x.db", "doc", 172, "2026-05-20", "standalone", face_targets={})
    assert rows and all(r.unit == "inr_lakh" for r in rows)


def test_r8_xbrl_other_filing_differs_keeps_rows_when_items_add(monkeypatch):
    # c18 FY25 noncurrent: note prints 16,061.25 (18,101.25 - 2,040.00); XBRL of another filing says 15,971.87 (0.56%)
    words = (
        _wline(20, (40, "Notes to Standalone Financial Statements"))
        + _wline(34, (40, "(All amounts are in Rs. Lakhs)"))
        + _wline(50, (40, "16 LONG TERM BORROWINGS"))
        + _wline(64, (320, "31st March, 2026"), (460, "31st March, 2025"))
        + _wline(78, (40, "Term Loans From Bank"), (350, "18,869.44"), (470, "18,101.25"))
        + _wline(92, (40, "Less : Current Maturities"), (350, "(3,791.07)"), (470, "(2,040.00)"))
        + _wline(106, (40, "Total"), (350, "15,078.37"), (470, "16,061.25"))
    )
    monkeypatch.setattr(N, "words_for", lambda *a, **k: type("P", (), {"words": words})())
    face = {
        ("FY26", "standalone", "borrowings_noncurrent"): [
            N.FaceCand(1507837000.0, 1.0, "inr", True, True, 4, "2026-05-14", "facts", "XBRL_26.xml", True)
        ],
        ("FY25", "standalone", "borrowings_noncurrent"): [
            N.FaceCand(1597187000.0, 1.0, "inr", True, True, 4, "2025-05-29", "facts", "XBRL_25.xml", True)
        ],
    }
    rows, _ = N.read_page("x.db", "ar26.pdf", 172, "2026-08-01", "standalone", face_targets=face)
    fy26 = [r for r in rows if r.fiscal_year == "FY26"]
    fy25 = [r for r in rows if r.fiscal_year == "FY25"]
    assert all(r.tie_status == "tied" for r in fy26)
    assert fy25 and all(r.tie_status == "differs" and "face figure differs: 15971.87 XBRL_25.xml" in r.definition for r in fy25)


def test_r8_slug_no_midword_truncation_and_no_subtotal_subtotal():
    long_lbl = "Total outstanding dues of micro enterprises and small enterprises payable"
    s = N._slug(long_lbl)
    assert s == "total_outstanding_dues_of_micro_enterprises_and_small_enterprises_payable"
    assert N._slug("a " * 60, limit=30).endswith("a")
    # c83 demoted subtotal names caption ('stock_in_trade' / 'a_revenue...'), never 'subtotal:subtotal'
    lines = [
        N.A.Line("A) REVENUE FROM SALE OF PRODUCTS", None, 2, "A)", 205),
        N.A.Line("India", [1535.96, 1642.90], 2, "India 1535.96", 205),
        N.A.Line("Rest of the World", [216.80, 379.84], 2, "RoW 216.80", 205),
        N.A.Line("", [1752.76, 2022.74], 2, "1752.76", 205),
        N.A.Line("Stock in Trade", None, 2, "Stock in Trade", 205),
        N.A.Line("India", [27.31, 28.78], 2, "India 27.31", 205),
        N.A.Line("", [1780.07, 2051.52], 2, "1780.07", 205),
        N.A.Line("B) OTHER OPERATING INCOME", None, 2, "B)", 205),
        N.A.Line("Export Benefits", [4.68, 8.22], 2, "Export 4.68", 205),
        N.A.Line("Sale of Scrap", [16.81, 22.79], 2, "Scrap 16.81", 205),
        N.A.Line("", [21.49, 31.01], 2, "21.49", 205),
        N.A.Line("", [1801.56, 2082.53], 2, "1801.56", 205),
    ]
    blks = N.blocks(lines, 0)
    demoted = [b for b in blks if b[3] == "block" and b[2].values[0] == 1780.07][0]
    assert demoted[4] and "subtotal" not in demoted[4].lower()


# --- T-223 review round 9 (D1 subtotal promotion, D2/D4 long two-col item followed, D3 <=1% & last-fig/no-contd, D5 label merge, D6 doc_unit) ---

def test_r9_d1_subtotal_caption_not_promoted_and_disagree_rejected(monkeypatch):
    # c84 p246: page ends at 'Sub-total 142,809.06' (face XBRL 148,166.29 is 3.6% higher): never becomes _total or 'differs'
    words = (
        _wline(20, (40, "Notes to Consolidated Financial Statements"))
        + _wline(40, (40, "21.0 Revenue from operations"), (480, "(Rs. in Lakh)"))
        + _wline(54, (320, "March 31, 2026"), (440, "March 31, 2025"))
        + _wline(68, (40, "Sale of products"))
        + _wline(82, (40, "Finished goods"), (350, "1,41,680.38"), (470, "1,40,905.52"))
        + _wline(96, (40, "Stock-in-trade"), (350, "1,128.68"), (470, "1,234.53"))
        + _wline(110, (240, "Sub-total"), (350, "1,42,809.06"), (470, "1,42,140.05"))
    )
    monkeypatch.setattr(N, "words_for", lambda *a, **k: type("P", (), {"words": words})())
    face = {
        ("FY26", "consolidated", "revenue_from_operations"): [
            N.FaceCand(14816629000.0, 1.0, "inr", True, True, 4, "2026-05-21", "facts", "XBRL_26.xml", True)
        ],
    }
    rows, log = N.read_page("x.db", "ar26.pdf", 246, "2026-08-01", "consolidated", face_targets=face)
    assert [r for r in rows if r.fiscal_year == "FY26"] == []
    assert any(l["why"] == "total does not tie to the statement" for l in log)


def test_r9_d2_d4_long_two_col_deduction_sets_followed_and_closes_net_total(monkeypatch):
    # c85 p188: 'Current portion of Non-current borrowings disclosed in current borrowings stated below' (>8 words, 2 cols)
    # must set followed on 38,518.72 and subtract to 29,648.12 (= face)
    words = (
        _wline(20, (40, "Notes to Financial Statements"))
        + _wline(40, (40, "19. Borrowings"), (480, "(Rs. in Lakhs)"))
        + _wline(54, (320, "As at 31 March 2025"), (440, "As at 31 March 2024"))
        + _wline(66, (40, "Non-current Borrowings"))
        + _wline(78, (40, "Term loans"), (350, "37,332.36"), (470, "33,692.88"))
        + _wline(92, (40, "Under financial assistance scheme"), (350, "1,186.36"), (470, "3,548.70"))
        + _wline(106, (350, "38,518.72"), (470, "37,241.58"))
        + _wline(120, (40, "Current portion of Non-current borrowings disclosed in current borrowings"),
                 (350, "8,870.60"), (470, "11,090.83"))
        + _wline(134, (40, "stated below"))
        + _wline(148, (350, "29,648.12"), (470, "26,150.75"))
    )
    monkeypatch.setattr(N, "words_for", lambda *a, **k: type("P", (), {"words": words})())
    face = {
        ("FY25", "standalone", "borrowings_noncurrent"): [
            N.FaceCand(2964812000.0, 1.0, "inr", True, True, 4, "2025-05-12", "facts", "XBRL_25.xml", True)
        ],
    }
    rows, _ = N.read_page("x.db", "ar25.pdf", 188, "2025-08-01", "standalone", face_targets=face)
    fy25 = {r.line_item: (r.value, r.tie_status) for r in rows if r.fiscal_year == "FY25"}
    assert fy25["borrowings_noncurrent_total"] == (29648.12, "tied")
    assert any(v == -8870.60 for v, _ in fy25.values())


def test_r9_d3_differs_requires_1pct_and_no_contd_continuation(monkeypatch):
    # <=1% XBRL differs is kept only when not followed by a '(Contd.)' continuation on the next page
    words = (
        _wline(20, (40, "Notes to Standalone Financial Statements"))
        + _wline(34, (40, "(All amounts are in Rs. Lakhs)"))
        + _wline(50, (40, "16 LONG TERM BORROWINGS"))
        + _wline(64, (320, "31st March, 2026"), (460, "31st March, 2025"))
        + _wline(78, (40, "Term Loans From Bank"), (350, "18,869.44"), (470, "18,101.25"))
        + _wline(92, (40, "Less : Current Maturities"), (350, "(3,791.07)"), (470, "(2,040.00)"))
        + _wline(106, (40, "Total"), (350, "15,078.37"), (470, "16,061.25"))
    )
    monkeypatch.setattr(N, "words_for", lambda *a, **k: type("P", (), {"words": words})())
    face = {
        ("FY26", "standalone", "borrowings_noncurrent"): [
            N.FaceCand(1507837000.0, 1.0, "inr", True, True, 4, "2026-05-14", "facts", "XBRL_26.xml", True)
        ],
        ("FY25", "standalone", "borrowings_noncurrent"): [
            N.FaceCand(1597187000.0, 1.0, "inr", True, True, 4, "2025-05-29", "facts", "XBRL_25.xml", True)
        ],
    }
    contd = N._contd_notes_in("16 LONG TERM BORROWINGS (Contd.)\nParticulars")
    assert "borrowings_noncurrent" in contd
    rows_contd, log = N.read_page("x.db", "ar26.pdf", 172, "2026-08-01", "standalone",
                                  face_targets=face, contd_notes=contd)
    assert [r for r in rows_contd if r.fiscal_year == "FY25"] == []
    assert any(l["why"] == "total does not tie to the statement" for l in log)


def test_r9_d5_no_merge_of_marker_unit_or_footnote_sentence(monkeypatch):
    # c11 two-col 'Rs. In Lacs Rs. In Lacs', c74 'ii. Liability...', c56 footnote '...in previous year.' must stay unmerged
    words = (
        _wline(20, (40, "Notes to Standalone Financial Statements"))
        + _wline(40, (40, "15(a) Long Term Borrowings"), (320, "31-Mar-2025"), (440, "31-Mar-2024"))
        + _wline(54, (320, "Rs. In"), (360, "Lacs"), (440, "Rs. In"), (480, "Lacs"))
        + _wline(68, (40, "a) Non Convertible Debenture"), (350, "100.00"), (470, "200.00"))
        + _wline(82, (40, "Less: Current Maturities"), (350, "40.00"), (470, "50.00"))
        + _wline(96, (350, "60.00"), (470, "150.00"))
        + _wline(110, (40, "ii. Liability Component of Debenture"))
        + _wline(124, (40, "Optionally Convertible"), (350, "10.00"), (470, "20.00"))
        + _wline(138, (40, "Total"), (350, "70.00"), (470, "170.00"))
        + _wline(152, (40, "Revenues from customer A represent Rs. 100 lakhs which was 10% of the Company's"))
        + _wline(166, (40, "total sale of finished goods in previous year."))
    )
    monkeypatch.setattr(N, "words_for", lambda *a, **k: type("P", (), {"words": words})())
    rows, _ = N.read_page("x.db", "ar25.pdf", 115, "2025-08-01", "standalone", face_targets={})
    items = {r.line_item for r in rows if r.fiscal_year == "FY25"}
    assert "borrowings_noncurrent:a_non_convertible_debenture" in items
    assert "borrowings_noncurrent:less_current_maturities" in items
    assert not any("rs_in_lacs" in x or "liability_component" in x or "previous_year" in x for x in items)


def test_r9_d6_doc_unit_fallback_only_when_page_has_no_unit(monkeypatch):
    words = (
        _wline(20, (40, "Notes to Standalone Financial Statements"))
        + _wline(40, (40, "18. Short Term Borrowings"))
        + _wline(54, (320, "As at 31 March 2024"), (440, "As at 31 March 2023"))
        + _wline(68, (40, "- Lien on FDR for Rs. 3.38 millions in the name of company."))
        + _wline(82, (40, "Cash credit"), (350, "132.42"), (470, "100.00"))
        + _wline(96, (40, "Total"), (350, "132.42"), (470, "100.00"))
    )
    monkeypatch.setattr(N, "words_for", lambda *a, **k: type("P", (), {"words": words})())
    rows, _ = N.read_page("x.db", "ar24.pdf", 129, "2024-08-01", "standalone",
                          face_targets={}, doc_unit=("inr_million", 1e6))
    assert rows and all(r.unit == "inr_million" for r in rows)
    # _page_declared_unit detects initial notes unit header cleanly
    assert N._page_declared_unit("Notes to Standalone Financial Statements\n(All amount in INR Millions unless otherwise stated)") == ("inr_million", 1e6)


def test_r9_followed_ignores_footnote_head_and_two_col_prose(monkeypatch):
    # c36 '* Includes' breakdown and c52/c70 two-column prose sentences below Total never demote <note>_total
    words = (
        _wline(20, (40, "Notes to Standalone Financial Statements"))
        + _wline(40, (40, "Note 29 : Finance costs"), (320, "(Rs in Crore)"))
        + _wline(54, (320, "31st March, 2026"), (440, "31st March, 2025"))
        + _wline(68, (40, "On Loans"), (350, "14.00"), (470, "18.83"))
        + _wline(82, (40, "Other borrowing costs *"), (350, "0.16"), (470, "0.15"))
        + _wline(96, (40, "Total"), (350, "14.16"), (470, "18.98"))
        + _wline(110, (40, "* Includes"))
        + _wline(124, (40, "i) Interest on Tax Deducted at Source"), (350, "0.01"), (470, "0.02"))
        + _wline(138, (40, "All loans repayable on demand carry rate from"), (350, "9.50"), (470, "10.75"))
    )
    monkeypatch.setattr(N, "words_for", lambda *a, **k: type("P", (), {"words": words})())
    rows, _ = N.read_page("x.db", "ar26.pdf", 280, "2026-08-01", "standalone", face_targets={})
    tots = {r.fiscal_year: (r.line_item, r.value) for r in rows if r.line_item == "finance_costs_total"}
    assert tots == {"FY26": ("finance_costs_total", 14.16), "FY25": ("finance_costs_total", 18.98)}


# --- T-223 (R-015 follow-up): as-filed + restated sources, PIT serving ---

def _row(fy, basis, item, val, doc, page, ka, own, tie="no_face", unit="inr_lakh", scale=1e5, dec=2, reg=0, col=0):
    return N.Row(
        fy, "2024-03-31", basis, item, item, val, unit, scale, doc, page, f"{item} {val}", ka,
        f"ar_note_reader: {N.note_of_row(item)}", own, f"{doc}#p{page}#r{reg}#{col}", tie_status=tie, decimals=dec,
    )


def test_t223_as_filed_and_restated_kept_when_values_differ(tmp_path, monkeypatch):
    import importlib.util
    import sqlite3
    import sys
    from pathlib import Path
    from reality_engine.pilot3 import schema

    # Synthetic store with FY24 AR (as-filed 318.35) + FY25 AR (restated FY24 323.81) + Q4 FY25 prior_ytd face 323.81
    db = tmp_path / "store.db"
    conn = sqlite3.connect(db)
    schema.create(conn, ["company", "doc", "doc_page", "fin_annual_line", "fin_quarter_printed", "fin_quarter_xbrl"])
    conn.execute("INSERT INTO company (symbol, isin, name) VALUES ('TESTCO', 'INE000000001', 'Test Co Ltd')")
    conn.execute("INSERT INTO doc (doc_key, doc_type, filing_date, known_at, title) VALUES ('ar24.pdf', 'annual_report', '2024-08-30', '2024-08-30T20:00:00', 'AR 2023-24')")
    conn.execute("INSERT INTO doc (doc_key, doc_type, filing_date, known_at, title) VALUES ('ar25.pdf', 'annual_report', '2025-09-03', '2025-09-03T20:00:00', 'AR 2024-25')")
    conn.execute("INSERT INTO doc_page (doc_key, page, text) VALUES ('ar24.pdf', 254, 'Consolidated Statement of Profit and Loss\n23 Finance costs')")
    conn.execute("INSERT INTO doc_page (doc_key, page, text) VALUES ('ar25.pdf', 250, 'Consolidated Statement of Profit and Loss\n23 Finance costs')")
    # Later Q4 FY25 filing restated FY24 prior_ytd to 323.81 lakh: must NOT reject ar24.pdf (318.35)
    conn.execute(
        "INSERT INTO fin_quarter_printed (symbol, isin, period_end, fiscal_period, period_type, column_role, basis, "
        "statement, line_item, caption, value, unit, scale, raw_token, check_status, doc_key, page, known_at) "
        "VALUES ('TESTCO','INE000000001','2024-03-31','FY24','fy','prior_ytd','consolidated','P&L','finance_cost',"
        "'Finance costs',32381000.0,'inr',1.0,'323.81','unchecked','q4_25.pdf',1,'2025-05-12T13:00:00')"
    )
    conn.commit()
    conn.close()

    pages = {
        ("ar24.pdf", 254): (
            _wline(20, (40, "Notes to Consolidated Financial Statements"))
            + _wline(40, (40, "23 Finance costs"), (440, "(Rs. in lakhs)"))
            + _wline(54, (320, "31 March 2024"), (440, "31 March 2023"))
            + _wline(68, (40, "Interest on borrowings"), (350, "164.20"), (470, "206.58"))
            + _wline(82, (40, "Bank Processing Charges"), (350, "154.15"), (470, "157.46"))
            + _wline(96, (40, "Total"), (350, "318.35"), (470, "364.04"))
        ),
        ("ar25.pdf", 250): (
            _wline(20, (40, "Notes to Consolidated Financial Statements"))
            + _wline(40, (40, "23 Finance costs"), (440, "(Rs. in lakhs)"))
            + _wline(54, (320, "31 March 2025"), (440, "31 March 2024"))
            + _wline(68, (40, "Interest on borrowings"), (350, "165.87"), (470, "163.30"))
            + _wline(82, (40, "Interest expense on lease liabilities"), (350, "9.45"), (470, "6.36"))
            + _wline(96, (40, "Bank Processing Charges"), (350, "72.64"), (470, "154.15"))
            + _wline(110, (40, "Total"), (350, "247.96"), (470, "323.81"))
        ),
    }
    monkeypatch.setattr(N, "words_for", lambda _db, dk, pg: type("P", (), {"words": pages[(dk, pg)]})())
    res = N.run_store(db, "t00")
    fy24 = [r for r in res["row_list"] if r.fiscal_year == "FY24"]
    as_filed = [r for r in fy24 if r.doc_key == "ar24.pdf"]
    restated = [r for r in fy24 if r.doc_key == "ar25.pdf"]
    assert {r.line_item: r.value for r in as_filed} == {
        "finance_costs:interest_on_borrowings": 164.20,
        "finance_costs:bank_processing_charges": 154.15,
        "finance_costs_total": 318.35,
    }
    assert all("restated in" not in r.definition for r in as_filed)
    assert {r.line_item: r.value for r in restated} == {
        "finance_costs:interest_on_borrowings": 163.30,
        "finance_costs:interest_expense_on_lease_liabilities": 6.36,
        "finance_costs:bank_processing_charges": 154.15,
        "finance_costs_total": 323.81,
    }
    tot_r = [r for r in restated if r.line_item == "finance_costs_total"][0]
    assert "restated in ar25.pdf p250 (2025-09-03) (as-filed 318.35 in ar24.pdf p254 (2024-08-30))" in tot_r.definition
    lease_r = [r for r in restated if "lease" in r.line_item][0]
    assert "restated in ar25.pdf p250 (2025-09-03) (as-filed absent in ar24.pdf p254 (2024-08-30))" in lease_r.definition

    # Serving check: as_of 2024-12-31 returns as-filed (318.35); 2025-12-31 and today return restated (323.81)
    server = Path(__file__).resolve().parents[2] / "plugins" / "reality-data" / "server"
    monkeypatch.setenv("REALITY_PILOT3_DB", str(db))
    if str(server) not in sys.path:
        sys.path.insert(0, str(server))
    spec = importlib.util.spec_from_file_location("lookups_pilot3_test", server / "lookups_pilot3.py")
    assert spec is not None and spec.loader is not None
    lp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lp)
    try:
        r_2024 = lp.fin("TESTCO", "finance_costs_total", period="FY24", basis="consolidated", as_of="2024-12-31")["rows"]
        assert len(r_2024) == 1 and r_2024[0]["value"] == 318.35 and r_2024[0]["restated"] is False
        r_2025 = lp.fin("TESTCO", "finance_costs_total", period="FY24", basis="consolidated", as_of="2025-12-31")["rows"]
        assert len(r_2025) == 1 and r_2025[0]["value"] == 323.81 and r_2025[0]["restated"] is True
        assert r_2025[0]["alternatives"][0]["value"] == 318.35
        r_now = lp.fin("TESTCO", "finance_costs_total", period="FY24", basis="consolidated")["rows"]
        assert len(r_now) == 1 and r_now[0]["value"] == 323.81 and r_now[0]["restated"] is True
    finally:
        lp.close()


def test_t223_restated_dropped_when_equal_and_kept_on_line_shift():
    # 1. Identical values (even when later AR is tied and earlier is no_face) -> as-filed only
    cand_eq = [
        _row("FY24", "standalone", "finance_costs:interest", 100.0, "ar24.pdf", 10, "2024-08-15", True, tie="no_face"),
        _row("FY24", "standalone", "finance_costs_total", 100.0, "ar24.pdf", 10, "2024-08-15", True, tie="no_face"),
        _row("FY24", "standalone", "finance_costs:interest", 100.0, "ar25.pdf", 12, "2025-08-15", False, tie="tied"),
        _row("FY24", "standalone", "finance_costs_total", 100.0, "ar25.pdf", 12, "2025-08-15", False, tie="tied"),
    ]
    got_eq = N._select_sources(cand_eq)
    assert [r.doc_key for r in got_eq] == ["ar24.pdf", "ar24.pdf"]

    # 2. Extra 0.0 line omitted in later report, plus lakh vs crore rounding -> dropped
    cand_zero = [
        _row("FY24", "standalone", "finance_costs:interest", 164.20, "ar24.pdf", 10, "2024-08-15", True),
        _row("FY24", "standalone", "finance_costs:fx", 0.00, "ar24.pdf", 10, "2024-08-15", True),
        _row("FY24", "standalone", "finance_costs_total", 164.20, "ar24.pdf", 10, "2024-08-15", True),
        _row("FY24", "standalone", "finance_costs:interest", 1.64, "ar25.pdf", 12, "2025-08-15", False, unit="inr_crore", scale=1e7),
        _row("FY24", "standalone", "finance_costs_total", 1.64, "ar25.pdf", 12, "2025-08-15", False, unit="inr_crore", scale=1e7),
    ]
    assert [r.doc_key for r in N._select_sources(cand_zero)] == ["ar24.pdf"] * 3

    # 3. Same total, but two item lines shifted beyond tolerance -> restated kept
    cand_shift = [
        _row("FY24", "consolidated", "revenue_from_operations:finished_goods", 1000.0, "ar24.pdf", 20, "2024-09-01", True),
        _row("FY24", "consolidated", "revenue_from_operations:traded_goods", 200.0, "ar24.pdf", 20, "2024-09-01", True),
        _row("FY24", "consolidated", "revenue_from_operations_total", 1200.0, "ar24.pdf", 20, "2024-09-01", True),
        _row("FY24", "consolidated", "revenue_from_operations:finished_goods", 1100.0, "ar25.pdf", 22, "2025-09-01", False),
        _row("FY24", "consolidated", "revenue_from_operations:traded_goods", 100.0, "ar25.pdf", 22, "2025-09-01", False),
        _row("FY24", "consolidated", "revenue_from_operations_total", 1200.0, "ar25.pdf", 22, "2025-09-01", False),
    ]
    got_shift = N._select_sources(cand_shift)
    assert len(got_shift) == 6
    assert {r.doc_key for r in got_shift} == {"ar24.pdf", "ar25.pdf"}
    assert all("restated in ar25.pdf" in r.definition for r in got_shift if r.doc_key == "ar25.pdf")
    assert all("restated in" not in r.definition for r in got_shift if r.doc_key == "ar24.pdf")


def test_t223_no_own_year_report_uses_later_report():
    cand = [
        _row("FY25", "standalone", "borrowings_current:term_loan", 500.0, "ar26.pdf", 172, "2026-09-01", False, tie="tied"),
        _row("FY25", "standalone", "borrowings_current_total", 500.0, "ar26.pdf", 172, "2026-09-01", False, tie="tied"),
        _row("FY25", "standalone", "borrowings_current:term_loan", 490.0, "ar26_old.pdf", 170, "2026-08-01", False, tie="no_face"),
        _row("FY25", "standalone", "borrowings_current_total", 490.0, "ar26_old.pdf", 170, "2026-08-01", False, tie="no_face"),
    ]
    got = N._select_sources(cand)
    assert len(got) == 2
    assert all(r.doc_key == "ar26.pdf" and "restated in" not in r.definition for r in got)


def test_t223_own_note_ties_via_later_checked_comparative_when_contemp_ytd_disagrees(tmp_path, monkeypatch):
    import sqlite3
    from reality_engine.pilot3 import schema

    # Pattern (c72): Q4 FY24 printed ytd has a mis-aligned column figure (contemp non-empty), while later Q2 FY25
    # last_fy (129,312.86; 1,054.19) and Q4 FY25 prior_ytd (129,337.80; 1,054.19) hold checked full-year figures.
    # Own-year FY24 AR must tie via the checked comparative candidates; revenue keeps both as-filed + restated,
    # finance_costs keeps as-filed and drops the equal restated note.
    db = tmp_path / "store.db"
    conn = sqlite3.connect(db)
    schema.create(conn, ["company", "doc", "doc_page", "fin_annual_line", "fin_quarter_printed", "fin_quarter_xbrl"])
    conn.execute("INSERT INTO company (symbol, isin, name) VALUES ('TESTCO', 'INE000000002', 'Test Co Two')")
    conn.execute("INSERT INTO doc (doc_key, doc_type, filing_date, known_at, title) VALUES ('ar24.pdf', 'annual_report', '2024-07-15', '2024-07-15T14:39:20', 'AR 2023-24')")
    conn.execute("INSERT INTO doc (doc_key, doc_type, filing_date, known_at, title) VALUES ('ar25.pdf', 'annual_report', '2025-08-30', '2025-08-30T11:45:34', 'AR 2024-25')")
    conn.execute("INSERT INTO doc_page (doc_key, page, text) VALUES ('ar24.pdf', 128, '28 Revenue from operations')")
    conn.execute("INSERT INTO doc_page (doc_key, page, text) VALUES ('ar24.pdf', 130, '30 Finance costs')")
    conn.execute("INSERT INTO doc_page (doc_key, page, text) VALUES ('ar25.pdf', 146, '28 Revenue from operations')")
    conn.execute("INSERT INTO doc_page (doc_key, page, text) VALUES ('ar25.pdf', 147, '30 Finance costs')")
    fqp_rows = [
        ("FY24", "ytd", "revenue_from_operations", "(a) Revenue from Operations", 3864155000.0, "38,641.55", "sum_ok", "q4_24.pdf", "2024-05-27T16:47:23"),
        ("FY24", "last_fy", "revenue_from_operations", "(a) Revenue from Operations", 12931286000.0, "129,312.86", "sum_ok", "q2_25.pdf", "2024-11-08T17:53:52"),
        ("FY24", "prior_ytd", "revenue_from_operations", "(a) Revenue from Operations", 12933780000.0, "129,337.80", "sum_ok", "q4_25.pdf", "2025-05-28T17:09:09"),
        ("FY24", "ytd", "finance_cost", "(d) Finance costs", 30963000.0, "309.63", "unchecked", "q4_24.pdf", "2024-05-27T16:47:23"),
        ("FY24", "last_fy", "finance_cost", "(d) Finance costs", 105419000.0, "1,054.19", "repeat_ok", "q2_25.pdf", "2024-11-08T17:53:52"),
        ("FY24", "prior_ytd", "finance_cost", "(d) Finance costs", 105419000.0, "1,054.19", "repeat_ok", "q4_25.pdf", "2025-05-28T17:09:09"),
    ]
    for fp, role, li, cap, val, rtok, cs, dk, ka in fqp_rows:
        conn.execute(
            "INSERT INTO fin_quarter_printed (symbol, isin, period_end, fiscal_period, period_type, column_role, basis, "
            "statement, line_item, caption, value, unit, scale, raw_token, check_status, doc_key, page, known_at) "
            "VALUES ('TESTCO','INE000000002','2024-03-31',?,'fy',?,'standalone','P&L',?,?,?,'inr',1.0,?,?,?,1,?)",
            (fp, role, li, cap, val, rtok, cs, dk, ka),
        )
    conn.commit()
    conn.close()

    pages = {
        ("ar24.pdf", 128): (
            _wline(20, (40, "Notes to Financial Statements"))
            + _wline(40, (40, "28 Revenue from operations"), (440, "(Rs. in lakhs)"))
            + _wline(54, (320, "31 March 2024"), (440, "31 March 2023"))
            + _wline(68, (40, "Domestic sale"), (350, "1,14,047.28"), (470, "1,50,000.00"))
            + _wline(82, (40, "Export sale"), (350, "15,265.58"), (470, "26,245.55"))
            + _wline(96, (40, "Total"), (350, "1,29,312.86"), (470, "1,76,245.55"))
        ),
        ("ar24.pdf", 130): (
            _wline(20, (40, "Notes to Financial Statements"))
            + _wline(40, (40, "30 Finance costs"), (440, "(Rs. in lakhs)"))
            + _wline(54, (320, "31 March 2024"), (440, "31 March 2023"))
            + _wline(68, (40, "Interest expenses"), (350, "880.28"), (470, "700.00"))
            + _wline(82, (40, "Interest on lease liability"), (350, "173.91"), (470, "150.00"))
            + _wline(96, (40, "Total"), (350, "1,054.19"), (470, "850.00"))
        ),
        ("ar25.pdf", 146): (
            _wline(20, (40, "Notes to Financial Statements"))
            + _wline(40, (40, "28 Revenue from operations"), (440, "(Rs. in lakhs)"))
            + _wline(54, (320, "31 March 2025"), (440, "31 March 2024"))
            + _wline(68, (40, "Domestic sale"), (350, "1,40,000.00"), (470, "1,14,047.28"))
            + _wline(82, (40, "Export sale"), (350, "25,000.00"), (470, "15,265.58"))
            + _wline(96, (40, "Profit on sale of raw material"), (350, "903.17"), (470, "24.94"))
            + _wline(110, (40, "Total"), (350, "1,65,903.17"), (470, "1,29,337.80"))
        ),
        ("ar25.pdf", 147): (
            _wline(20, (40, "Notes to Financial Statements"))
            + _wline(40, (40, "30 Finance costs"), (440, "(Rs. in lakhs)"))
            + _wline(54, (320, "31 March 2025"), (440, "31 March 2024"))
            + _wline(68, (40, "Interest expenses"), (350, "5,900.00"), (470, "880.28"))
            + _wline(82, (40, "Lease liabilities"), (350, "191.19"), (470, "173.91"))
            + _wline(96, (40, "Total"), (350, "6,091.19"), (470, "1,054.19"))
        ),
    }
    monkeypatch.setattr(N, "words_for", lambda _db, dk, pg: type("P", (), {"words": pages[(dk, pg)]})())
    res = N.run_store(db, "t72")
    fy24 = [r for r in res["row_list"] if r.fiscal_year == "FY24"]
    rev_24 = [(r.doc_key, r.line_item, r.value, r.tie_status) for r in fy24 if N.note_of_row(r.line_item) == "revenue_from_operations"]
    assert ("ar24.pdf", "revenue_from_operations_total", 129312.86, "tied") in rev_24
    assert ("ar25.pdf", "revenue_from_operations_total", 129337.80, "tied") in rev_24
    restated_rev_tot = [r for r in fy24 if r.doc_key == "ar25.pdf" and r.line_item == "revenue_from_operations_total"][0]
    assert "restated in ar25.pdf p146 (2025-08-30) (as-filed 129312.86 in ar24.pdf p128 (2024-07-15))" in restated_rev_tot.definition

    fc_24 = [(r.doc_key, r.line_item, r.value, r.tie_status) for r in fy24 if N.note_of_row(r.line_item) == "finance_costs"]
    assert fc_24 == [
        ("ar24.pdf", "finance_costs:interest_expenses", 880.28, "tied"),
        ("ar24.pdf", "finance_costs:interest_on_lease_liability", 173.91, "tied"),
        ("ar24.pdf", "finance_costs_total", 1054.19, "tied"),
    ]




