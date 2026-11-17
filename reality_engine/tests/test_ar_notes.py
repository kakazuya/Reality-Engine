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
