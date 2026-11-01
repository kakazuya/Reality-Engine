"""Shivam's review of the removed questions, 1 Nov 2026. Each replaces the earlier rule for that question."""
import json
from pathlib import Path

import build
from build import K, M, X


def redo(*mids):
    for m in mids:
        mid = "MB" + m
        del build.RULES[mid]
        build.ORDER.remove(mid)


redo("0222", "0579")

# Scope ruling, 1 Nov: the system computes what filings do not state. Held tax-reconciliation notes give the inputs.
M("0222", "The tax holiday for affordable housing projects was extended to March 2022. For {cohort}, compute the tax each paid against tax at the normal rate for FY21 to FY23, and say how much of any gap the filings attribute to it.",
  None, "CDAN", fit="realty")

# Removed in error: NSDL's fortnightly sector file is held, loaded in mkt_report_cells.
K("0579", "Which sectors did FIIs sell most in September 2026? Use NSDL's fortnightly sector flows.",
  chk=(("cells", "nsdl_fpi_fortnight", "FIIInvestSector_Sep152026.html"), ("cells", "nsdl_fpi_fortnight", "FIIInvestSector_Sep302026.html")))

# His rulings bind: a question he dropped or parked stays out, whatever a later read finds.
for x in json.load(open(Path(__file__).parents[1] / "PILOT_BANK_REMOVED_RULINGS_2026-11-01.json", encoding="utf-8")):
    if x["action"] != "Restored to the bank":
        redo(x["mid"][2:])
        X(x["mid"][2:], x["why"])
