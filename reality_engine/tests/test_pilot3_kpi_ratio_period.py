"""T-107: a ratio row carries the period its page prints (quarter, half, year).

The BAJFINANCE Q4 FY26 release prints "ROE 20.0%" in the Q4 FY26 column of its highlights table.  The row was
stored FY26 (the document's default), so "Bajaj Finance ROE for FY26" answered 20.0% -- the quarter's annualised
rate -- instead of the year's 18.1%.  A ratio printed without a period is the quarter's on a quarterly document;
a year named beside the label ("for FY2026", "for the year") keeps the year, and a column header decides each
column.  Synthetic input only: no sandbox, no network, no model.
"""
from reality_engine.pilot3 import kpi

ENTRIES, DIMS = kpi.load_lexicon()
FILED = "2026-04-29T16:49:27"


def _roe(text, default, **kw):
    rows = kpi.sentence_rows(text, 1, "BAJFINANCE", ENTRIES, DIMS, default, FILED, "consolidated", **kw)
    return [(r.fiscal_period, r.value) for r in rows if r.metric == "roe_pct"]


def _q4_document():
    """The default a Q4 document states: the year, not the quarter (a level printed without a period is the year)."""
    default = kpi.doc_default_period(["Bajaj Finance Q4 FY26 results"])
    assert [p.canon for p in default] == ["FY26"]
    return default


# the real page 27 block: the highlights table's header over its rows (the OCR prints "Q4 FY26" as "04 FV26")
BLOCK = ("► Before impact of one-time actions and presentation change: \n"
         "Particulars \n04 FV26 \n04 FV25 \nQoQ \nFV26 \nFV25 \n"
         "New loans booked (No. in million) \n12.89 \n10.70 \n20% \n52.45 \n43.42 \n"
         "Annualised ROE \n20.0% \n18.7% \n19.2% \n19.1% \n")


def test_a_quarter_documents_tile_is_the_quarter_never_the_year():
    """(a) "ROE 20.0%" under a Q4 FY26 highlights table is the quarter's annualised rate, not the year's."""
    got = _roe(BLOCK, _q4_document(), ratio_quarter=True)
    assert got == [("Q4FY26", 20.0)]


def test_annualised_without_a_year_word_is_the_quarter():
    """(e) "Annualised ROE 19.2%" (the deck's performance tile) has no year word: it is the quarter's rate."""
    got = _roe("Annualised ROE \n19.2%", _q4_document(), ratio_quarter=True)
    assert got == [("Q4FY26", 19.2)]


def test_a_year_beside_the_label_keeps_the_year():
    """(c) a year named beside the ratio is the ratio's own span, however the document defaults."""
    for text in ("Return on average equity ('ROAE') for FY2026 was 18.1%.",
                 "Return on equity for the year ended 31 March 2026 was 18.1%.",
                 "ROE for the year \n18.1%"):
        assert _roe(text, _q4_document(), ratio_quarter=True) == [("FY26", 18.1)], text


def test_the_current_quarter_is_the_quarter():
    """(d) "in the current quarter" is the quarter the call reports."""
    got = _roe("Return on equity came in at 20% in the current quarter.", _q4_document(), ratio_quarter=True)
    assert got == [("Q4FY26", 20.0)]


def test_a_column_header_decides_each_ratios_period():
    """(b) "Annualised Return on Average Equity 20.03% 18.74% 19.22%" under Q4FY26 | Q4FY25 | FY26 is three rows."""
    def words(rows):
        out = []
        for y, toks in rows:
            for x, t in toks:
                out.append((x, y - 4, x + 6 * len(t), y + 4, t, 0, 0, 0))
        return out

    w = words([(20, [(280, "Particulars"), (560, "Q4FY26"), (700, "Q4FY25"), (850, "FY26")]),
               (60, [(280, "Annualised"), (360, "Return"), (400, "on"), (420, "Average"), (470, "Equity")]),
               (63, [(560, "20.03%"), (700, "18.74%"), (850, "19.22%")])])
    text = ("Particulars Q4FY26 Q4FY25 FY26\n"
            "Annualised Return on Average Equity 20.03% 18.74% 19.22%\n")
    rows = kpi.table_and_chart_rows(w, text, 1, "BAJFINANCE", ENTRIES, DIMS, [])
    assert {(r.fiscal_period, r.value) for r in rows if r.metric == "roe_pct"} == {
        ("Q4FY26", 20.03), ("Q4FY25", 18.74), ("FY26", 19.22)}
    assert all(r.quote in text for r in rows)
