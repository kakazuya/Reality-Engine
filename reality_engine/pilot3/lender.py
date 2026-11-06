"""The lender test, one home for the build and the MCP lookups (T-094).

A bank, NBFC or insurer reports interest / premium income where an operating company reports revenue, so EV/EBITDA
and the EBITDA lines have no meaning for it.  ``filed_lender`` is the evidence from the filings: a company whose
``fin_quarter_xbrl`` carries one of ``LENDER_LINES`` is a lender.  It reads a built pilot3 database, so a profile
(the JSON written before that database exists) takes its flag from the exchange taxonomy in ``sector_map.yaml`` and
``make_profile --check-db`` compares the two after the build.  ``plugins/reality-data/server/lookups_pilot3.py``
uses the same test for its EV/EBITDA refusal.
"""
from __future__ import annotations

import sqlite3

LENDER_LINES = ("interest_income", "interest_earned", "gross_premium", "net_premium")


def filed_lender(conn: sqlite3.Connection, symbol: str) -> bool:
    """True when the company filed an interest / premium income line (a bank, NBFC or insurer)."""
    marks = ",".join("?" * len(LENDER_LINES))
    return bool(conn.execute(f"SELECT 1 FROM fin_quarter_xbrl WHERE symbol=? AND line_item IN ({marks}) LIMIT 1",
                             (symbol, *LENDER_LINES)).fetchone())
