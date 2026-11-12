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


# --- T-192 3: a table's current column, not the comparative, and a call's quarter from the filing record --------
def test_a_month_word_inside_a_label_is_not_a_period():
    """T-192: "Margin\\n21.0%" was read as March 2021.  The bogus span swallowed the current quarter's EBITDA margin,
    so the comparative column (20.4%) became the row for Q1FY27 (the deck prints 21.0%)."""
    assert kpi.parse_periods("EBITDA Margin\n21.0%\n20.4%\n60 bps\n20.3%") == []


def test_a_results_block_takes_its_own_column_not_the_comparative():
    """The deck's P&L table: EBITDA Margin 21.0% (Q1FY27) | 20.4% (Q1FY26) | 60 bps.  The row is the current
    quarter's 21.0%, never the comparative 20.4%."""
    block = ("₹ Cr.\nQ1FY27\nQ1FY26\nY-o-Y Chg. (%)\nQ4FY26\nQ-o-Q Chg. (%)\n"
             "EBITDA Margin\n21.0%\n20.4%\n60 bps\n20.3%\n69 bps\n")
    default = [p for p in kpi.parse_periods("Q1FY27") if p.canon == "Q1FY27"]
    rows = kpi.sentence_rows(block, 1, "T", ENTRIES, DIMS, default, "2026-08-05T19:55:37", "consolidated",
                             False, True)
    got = [(r.fiscal_period, r.value) for r in rows if r.metric == "ebitda_margin_pct"]
    assert got and got[0] == ("Q1FY27", 21.0), got


def test_a_calls_period_comes_from_its_filing_record():
    """T-192 4: a transcript filed 8 Aug 2025 reports Q1 FY26.  A year the text mentions (a target year) never
    becomes the call's period, and a stored Q1FY31 label is impossible."""
    from reality_engine.pilot3 import transcripts

    assert transcripts.call_period_ok("Q1FY31", "2025-08-08T12:07:00") == "Q1FY26"
    assert transcripts.call_period_ok("Q4FY26", "2026-05-27T18:14:02") == "Q4FY26"   # a plausible label stands
    assert transcripts.call_period_ok(None, "2026-02-16T11:17:34") == "Q3FY26"


# --- T-192 round 4 H4: only a real month name is a month ------------------------------------------------------
def test_a_word_that_only_starts_with_a_month_is_not_a_period():
    """H4: every one of these matched a month-year span before the fix."""
    for text in ("Margin\n21%", "Margin 24", "Marketing 22", "Junk 23"):
        assert kpi.parse_periods(text) == [], text
    assert [p.canon for p in kpi.parse_periods("March 2024")] == ["FY24"]
    assert [p.canon for p in kpi.parse_periods("September 2025")] == ["Q2FY26"]


# --- T-192 round 4 H3: a row's own full-year / year-to-date span is never replaced by the call's quarter -------
def _pers(canon: str, ptype: str):
    return kpi.Period(0, 0, canon, ptype, kpi.period_end(ptype, canon))


def test_a_row_that_names_its_own_span_keeps_it_over_the_calls_quarter():
    """H3: the call's quarter comes from the filing record only as a default.  "for the full year", "H1 FY27" and
    "nine months" are the figure's own span and keep it (SUNPHARMA full-year sales, SBILIFE VNB H1, 9MFY26)."""
    fy, h1, nine = _pers("FY26", "FY"), _pers("H1FY27", "H"), _pers("9MFY26", "9M")
    q4, q2, q3 = _pers("Q4FY26", "Q"), _pers("Q2FY27", "Q"), _pers("Q3FY26", "Q")
    assert kpi._stated_period("India formulation sales for the full year were 192,904 crore", 0, 80, [fy]).canon == "FY26"
    assert kpi._stated_period("VNB was 32.7 bn for the H1 FY27", 0, 40, [h1]).canon == "H1FY27"
    assert kpi._stated_period("premium grew 12% in the nine months", 0, 43, [nine]).canon == "9MFY26"
    assert kpi._stated_period("order book stood at 10,000 crore", 0, 37, [fy]) is None

    text = "EBITDA margin for the full year was 20.8%"
    rows = kpi.sentence_rows(text, 1, "T", ENTRIES, DIMS, [q4], "2026-05-05T10:00:00", "consolidated",
                             False, True, fallback_pers=[fy])
    assert [(r.fiscal_period, r.value) for r in rows if r.metric == "ebitda_margin_pct"] == [("FY26", 20.8)]

    # no cue: the call's quarter stands, and a stock figure is the quarter-end's (H3)
    text = "Order book stood at 10,000 crore"
    rows = kpi.sentence_rows(text, 1, "T", ENTRIES, DIMS, [q2], "2026-10-20T10:00:00", "consolidated",
                             False, True, fallback_pers=[fy])
    assert [(r.fiscal_period, r.value) for r in rows if r.metric == "order_book"] == [("Q2FY27", 10000.0)]

    # a document that itself declares a year-to-date span keeps it for an unlabelled flow (SBILIFE's VNB class):
    # "revenue stood at 1,000 crore" in an H1 call is H1, never the call's Q2
    h1 = _pers("H1FY27", "H")
    rows = kpi.sentence_rows("Revenue from operations stood at INR 1,000 crore", 1, "T", ENTRIES, DIMS,
                             [q2], "2026-10-28T10:00:00", "consolidated", False, True, fallback_pers=[h1])
    assert [(r.fiscal_period, r.value) for r in rows if r.metric == "revenue"] == [("H1FY27", 1000.0)]


# --- T-192 round 4 H5: a year in the previous sentence is not this figure's span ---------------------------------
def test_a_year_in_the_previous_sentence_is_not_this_figures_span(monkeypatch):
    """AUROPHARMA Q1 FY25 call p4: "on track to achieve €880 million plus for FY25. Our EBITDA margin remained at
    21.4%" was stored FY25 by the forecast year of the sentence before it; the margin is the call's quarter's."""
    monkeypatch.setattr(kpi.profile, "under_profile", lambda: True)
    text = ("Europe market demonstrated a strong performance and is on track to achieve €880 million plus for FY25. "
            "Further overall growth market performance has been good during the quarter. Our EBITDA margin "
            "remained at 21.4% and is lined with our expectation.")
    q1 = _pers("Q1FY25", "Q")
    assert kpi._frame_period(text, text.find("EBITDA margin"), text.find("21.4%"), q1) is None
    rows = kpi.sentence_rows(text, 4, "T", ENTRIES, DIMS, [q1], "2024-08-16T15:13:46", "not_stated", False, True)
    assert [(r.fiscal_period, r.value) for r in rows if r.metric == "ebitda_margin_pct"] == [("Q1FY25", 21.4)]
    # a year in the label's own sentence still names the span
    text2 = "For FY25, our EBITDA margin remained at 21.4%."
    rows2 = kpi.sentence_rows(text2, 4, "T", ENTRIES, DIMS, [q1], "2024-08-16T15:13:46", "not_stated", False, True)
    assert [(r.fiscal_period, r.value) for r in rows2 if r.metric == "ebitda_margin_pct"] == [("FY25", 21.4)]


# --- T-192 round 4 H5: a table row cut by a change column is never paired with the wrong columns ----------------
def test_a_table_row_cut_by_a_non_numeric_cell_is_not_stored_under_the_year_column():
    """AUROPHARMA's Q4 FY25 deck p16: 'EBITDA Margin 21.4% 22.3% -88 bps 20.4% 98 bps 20.8% 20.1% 67 bps'.  The
    reader stopped at '-88 bps' and paired 21.4%/22.3% (Q4FY25/Q4FY24) with the FY25/FY24 header pair, storing the
    quarter's margin as the year's."""
    from reality_engine.pilot3 import statements

    block = ("Q4FY25\nQ4FY24\nYoY (%)\nQ3FY25\nQoQ (%)\nFY25\nFY24\nYoY (%)\n"
             "Revenue from Operations\n8,382\n7,580\n10.6%\n7,979\n5.1%\n31,724\n29,002\n9.4%\n"
             "EBITDA Margin\n21.4%\n22.3%\n-88 bps\n20.4%\n98 bps\n20.8%\n20.1%\n67 bps\n"
             "Fx Gain/(Loss)\n12\n-14\nn/a\n-50\nn/a\n-23\n39\nn/a")
    assert [r for r in statements.table_rows(block) if r[0] == "ebitda_margin_pct"] == []


# --- T-192 round 4 H7: only a results/earnings call takes the filing quarter ----------------------------------
def test_an_acquisition_call_keeps_no_call_period():
    """H7: SUNPHARMA's "Organon Acquisition Investor Call" is not a results call: no quarter of the company is
    what it reports, so it keeps ``call_period`` NULL instead of borrowing Q4FY26 from the filing date."""
    from reality_engine.pilot3 import transcripts

    assert transcripts.call_period_ok(None, "2026-05-05T10:00:00", "Organon Acquisition Investor Call") is None
    assert transcripts.call_period_ok(None, "2026-05-05T10:00:00", "Q4 FY26 Earnings Call") == "Q4FY26"
    assert transcripts.call_period_ok(None, "2026-05-05T10:00:00", "Deck") == "Q4FY26"   # unknown title: old rule
    assert transcripts.call_period_ok(None, "2025-08-08T12:07:00",
                                      "Submission of transcript of earnings call on the unaudited financial "
                                      "results for the first quarter ended June 30, 2025") == "Q1FY26"
