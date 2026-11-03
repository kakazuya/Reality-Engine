"""pilot3 ratio_panel: the lender's annual opex / net total income row (T-049, 4 Nov 2026).

Fixture only: the rows are Bajaj Finance's FY26 consolidated XBRL annual lines, in an in-memory sqlite built
from the real DDL. No store, no network, no model.
"""
from __future__ import annotations

import json
import sqlite3

from reality_engine.pilot3 import ratios, schema

ISIN = "INE296A01024"
FY26 = {  # xbrl_reported, consolidated, INR
    "employee_cost": 89_785_300_000.0,
    "fee_commission_expense": 36_581_000_000.0,
    "other_expenses": 41_306_800_000.0,
    "depreciation": 10_089_800_000.0,
    "total_income": 819_895_000_000.0,
    "finance_cost": 286_659_500_000.0,
}
ROW = ("BAJFINANCE", ISIN, "FY26", "2026-03-31", "consolidated", "PL", None, None, None, "inr", 1.0, None, None,
       None, "results_xbrl.db", "facts", "x", "2026-05-22T18:50:00", "t", 1, 0, "xbrl_reported", "FY")


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    schema.create(conn, list(schema.TABLES))
    conn.execute("INSERT INTO company VALUES ('BAJFINANCE',?,NULL,NULL,'t','500034','Bajaj Finance Limited')", (ISIN,))
    conn.executemany("INSERT INTO fin_annual_line VALUES (" + ",".join("?" * 23) + ")", [
        (*ROW[:6], item, item, value, *ROW[9:]) for item, value in FY26.items()])
    conn.commit()
    return conn


def test_bajfinance_fy26_opex_to_net_total_income_is_annual_and_shows_inputs():
    conn = _conn()
    ratios.build_ratios(conn)
    row = conn.execute(
        "SELECT basis, value, unit, formula_id, input_refs FROM ratio_panel WHERE symbol='BAJFINANCE' "
        "AND metric='opex_to_net_total_income_pct' AND fiscal_period='FY26'").fetchone()
    assert row is not None, "no FY26 opex/NTI row in ratio_panel"
    basis, value, unit, formula_id, refs = row
    assert (basis, unit) == ("consolidated", "pct")
    # opex 17,776.29 cr over NTI 53,323.55 cr (total income - finance cost)
    assert round(value, 2) == 33.34
    expression = conn.execute("SELECT expression FROM formula WHERE formula_id=?", (formula_id,)).fetchone()[0]
    assert "total_income - finance_cost" in expression
    inputs = json.loads(refs)
    assert len(inputs) == 6 and all(ref.startswith("fa:BAJFINANCE:FY26:consolidated:") for ref in inputs), inputs


def test_quarterly_only_lines_make_no_annual_row():
    """The row needs all six annual inputs: a company without them gets nothing, never a partial ratio."""
    conn = sqlite3.connect(":memory:")
    schema.create(conn, list(schema.TABLES))
    conn.execute("INSERT INTO company VALUES ('KEC','I',NULL,NULL,'t','532714','KEC International Limited')")
    ratios.build_ratios(conn)
    assert conn.execute("SELECT COUNT(*) FROM ratio_panel WHERE metric='opex_to_net_total_income_pct'").fetchone()[0] == 0
