"""BSE fundamentals client tests.

Every test runs against a temp-file SQLite DB (never the live
``equity_intelligence.db``) with an injected fetcher, so there is no network and
no production write.  The fake fetcher reproduces the published contract of
``bse_client.bse_json`` (content guard, double-decode, ``Status:false`` -> None)
and the fixtures are the payload shapes BSE really serves (captured live
2026-09-20 for UNIFIED 544406, AFCOM 544224, YASHHV 544310 and SPEEDEX 544925):
the double-encoded ``TabResults_PAR`` table, a blank-``col2`` quarterly filer,
the 323-byte placeholder body, the ``Table1``/``Fld_*`` shareholding tables, the
never-filed ``TabResults_SHP`` template and a ``Status:false`` 12-month-cap
envelope.
"""

import json
import shutil
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

from reality_engine.db.database import DatabaseManager
from reality_engine.ingestion import bse_fundamentals_client as bfc

# --------------------------------------------------------------------------
# Raw BSE bodies
# --------------------------------------------------------------------------
# The 323-byte SPA-shell placeholder BSE serves instead of JSON for a scrip it
# has nothing for (the same non-answer form the shared guard rejects).
_BODY_323_BASE = ("<!DOCTYPE html><html><head><title>BSE</title></head><body>"
                  "<app-root></app-root></body></html>")
BODY_323 = _BODY_323_BASE + " " * (323 - len(_BODY_323_BASE))
assert len(BODY_323) == 323, len(BODY_323)

# UNIFIED 544406, half-yearly SME filer whose halves tie out.  ``resultinM`` is
# the same statement in MILLIONS of rupees (138.97 Cr == 1,389.74 M).
UNIFIED_RESULTS = {
    "col1": "(in Cr.)", "col2": "Mar-26", "col3": "Sep-25", "col4": "FY25-26",
    "resultinCr": [
        {"title": "Revenue", "v1": "138.97", "v2": "149.03", "v3": "288.00"},
        {"title": "Net Profit", "v1": "23.48", "v2": "17.27", "v3": "40.75"},
        {"title": "EPS", "v1": "11.69", "v2": "8.60", "v3": "20.28"},
        {"title": "Cash EPS", "v1": "11.85", "v2": "8.72", "v3": "20.57"},
        {"title": "OPM %", "v1": "22.23", "v2": "15.56", "v3": "18.78"},
        {"title": "NPM %", "v1": "16.89", "v2": "11.59", "v3": "14.15"},
    ],
    "resultinM": [
        {"title": "Revenue", "v1": "1,389.74", "v2": "1,490.28", "v3": "2,880.03"},
        {"title": "Net Profit", "v1": "234.76", "v2": "172.71", "v3": "407.47"},
        {"title": "EPS", "v1": "11.69", "v2": "8.60", "v3": "20.28"},
        {"title": "Cash EPS", "v1": "11.85", "v2": "8.72", "v3": "20.57"},
        {"title": "OPM %", "v1": "22.23", "v2": "15.56", "v3": "18.78"},
        {"title": "NPM %", "v1": "16.89", "v2": "11.59", "v3": "14.15"},
    ],
    "resultinS": [{"FY": "FY25-26", "LQ": None, "SQ": None,
                   "LFY": "https://www.bseindia.com/corporates/results.aspx?Code=544406",
                   "LLQ": None, "LSQ": None}],
}

# AFCOM 544224 crore table only: the halves miss the FY total by 8.6% and there
# is no rupee table to fall back on, so the mismatch must be recorded.
AFCOM_RESULTS = {
    "col1": "(in Cr.)", "col2": "", "col3": "Sep-25", "col4": "FY25-26",
    "resultinCr": [
        {"title": "Revenue", "v1": "392.86", "v2": "240.28", "v3": "583.11"},
        {"title": "Net Profit", "v1": "93.48", "v2": "54.99", "v3": "121.90"},
        {"title": "EPS", "v1": "13.20", "v2": "22.12", "v3": "48.73"},
        {"title": "NPM %", "v1": "23.79", "v2": "22.89", "v3": "20.91"},
    ],
    "resultinS": [{"FY": "FY25-26", "LQ": "Jun-26", "SQ": "Mar-26",
                   "LFY": None, "LLQ": None, "LSQ": None}],
}

# The same scrip with both tables: the crore table still shows the 8.6% revenue
# hole while the rupee table agrees to 0.0055%.
AFCOM_REAL_RESULTS = {
    **AFCOM_RESULTS,
    "resultinM": [
        {"title": "Revenue", "v1": "3,928.62", "v2": "2,402.78", "v3": "5,831.08"},
        {"title": "Net Profit", "v1": "934.79", "v2": "549.94", "v3": "1,219.04"},
        {"title": "EPS", "v1": "13.20", "v2": "22.12", "v3": "48.73"},
        {"title": "NPM %", "v1": "23.79", "v2": "22.89", "v3": "20.91"},
    ],
}

# YASHHV 544310: a real 0.24% drift that neither table resolves.
YASHHV_RESULTS = {
    "col1": "(in Cr.)", "col2": "Mar-26", "col3": "Sep-25", "col4": "FY25-26",
    "resultinCr": [
        {"title": "Revenue", "v1": "135.57", "v2": "100.15", "v3": "235.16"},
        {"title": "Net Profit", "v1": "23.72", "v2": "14.02", "v3": "37.34"},
        {"title": "EPS", "v1": "8.31", "v2": "4.91", "v3": "13.08"},
    ],
    "resultinM": [
        {"title": "Revenue", "v1": "1,355.70", "v2": "1,001.45", "v3": "2,351.61"},
        {"title": "Net Profit", "v1": "237.16", "v2": "140.24", "v3": "373.40"},
        {"title": "EPS", "v1": "8.31", "v2": "4.91", "v3": "13.08"},
    ],
}

# ABB 500002, a QUARTERLY filer: col2/col3 are two consecutive quarters (~half
# the FY) and BSE serves a malformed FY label ("FY25-25").
ABB_QUARTERLY_RESULTS = {
    "col1": "(in Cr.)", "col2": "Jun-26", "col3": "Mar-26", "col4": "FY25-25",
    "resultinCr": [
        {"title": "Revenue", "v1": "3558.87", "v2": "3184.06", "v3": "13202.73"},
        {"title": "Net Profit", "v1": "362.30", "v2": "1783.65", "v3": "1668.26"},
        {"title": "EPS", "v1": "17.46", "v2": "16.14", "v3": "78.78"},
        {"title": "NPM %", "v1": "10.18", "v2": "56.02", "v3": "12.64"},
    ],
    "resultinS": [{"FY": "FY25-25", "LQ": "Jun-26", "SQ": "Mar-26",
                   "LFY": None, "LLQ": None, "LSQ": None}],
}

# A quarterly filer with a BLANK col2: the quarterly cadence shows only in the
# dated columns three months apart.
QUARTERLY_RESULTS = {
    "col1": "(in Cr.)", "col2": "", "col3": "Jun-26", "col4": "Sep-26",
    "resultinCr": [
        {"title": "Revenue", "v1": "", "v2": "118.25", "v3": "120.50"},
        {"title": "Net Profit", "v1": "", "v2": "6.10", "v3": "6.44"},
        {"title": "EPS", "v1": "", "v2": "2.20", "v3": "2.31"},
        {"title": "NPM %", "v1": "", "v2": "5.16", "v3": "5.34"},
    ],
}

# SPEEDEX 544925 files nothing at all: no labels and a bare template.
EMPTY_RESULTS = {
    "col1": "(in Cr.)", "col2": "", "col3": "", "col4": "",
    "resultinCr": [{"title": "", "v1": "--", "v2": "--", "v3": "--"}],
    "resultinM": [{"title": "", "v1": "--", "v2": "--", "v3": "--"}],
    "resultinS": [{"FY": None, "LQ": None, "SQ": None, "LFY": None, "LLQ": None, "LSQ": None}],
}

UNIFIED_HEADER = {
    "SecurityId": "UNIFIED", "Grp_Index": "M", "FaceVal": "10.00", "SecurityCode": "544406",
    "ISIN": "INE1ABX01018", "Industry": "IT Enabled Services", "Group": "M", "Index": "",
    "PAIDUP_VALUE": "", "EPS": "20.28", "CEPS": "20.57", "PE": "19.76", "OPM": "-", "NPM": "-",
    "PB": "-", "ROE": "-", "Sector": "Information Technology",
    "IndustryNew": "Information Technology", "IGroup": "IT - Services",
    "ISubGroup": "IT Enabled Services", "IShow": "1", "SetlType": "T+1", "COName": "",
    "ConEPS": "-", "ConCEPS": "-", "ConPE": "-", "ConOPM": "-", "ConNPM": "-",
    "ConPB": None, "ConROE": None,
}

# ``CorporatesSHPSecuritybeta`` filing index (Table) and aggregate (Table1).
SHP_INDEX = {"Table": [{"Fld_TransactionId": 214039, "Qtr_Id": 129.0,
                        "Fld_qtrname": "March 2026",
                        "slongname": "Unified Data Tech Solutions Ltd"}]}
SHP_AGGREGATE = {
    "Table": [{"Fld_TransactionId": 354406, "Qtr_Id": 129.0, "Fld_qtrname": "Mar-26"}],
    "Table1": [
        {"Fld_Code": "STA1A2", "Fld_ShortCatg": "Promoter and Promoter Group",
         "Fld_TotalPercentageOf_A_B_C2": 60.39, "Fld_TotalVotingRightsPercent": 60.39},
        {"Fld_Code": "STB1B2B3", "Fld_ShortCatg": "Public shareholder",
         "Fld_TotalPercentageOf_A_B_C2": 39.61, "Fld_TotalVotingRightsPercent": 39.61},
        {"Fld_Code": "STABC", "Fld_ShortCatg": "GRAND TOTAL  (A+B+C )",
         "Fld_TotalPercentageOf_A_B_C2": 100.0, "Fld_TotalVotingRightsPercent": 100.0},
    ],
}
# The newest quarter is a PLACEHOLDER even though Sep-25 was filed.
SHP_TAB = [
    {"Quarter": "Mar-26", "Col": None, "Promoter": "0.00", "Public": "0.00",
     "Others": "0.00", "Total": "100.00"},
    {"Quarter": "Sep-25", "Col": None, "Promoter": "60.39", "Public": "39.61",
     "Others": "0.00", "Total": "100.00"},
    {"Quarter": "27-May-25", "Col": None, "Promoter": "60.39", "Public": "39.61",
     "Others": "0.00", "Total": "100.00"},
]
# SPEEDEX 544925: the never-filed template.
SHP_TAB_NEVER_FILED = [
    {"Quarter": " ", "Col": None, "Promoter": "0.00", "Public": "0.00",
     "Others": "0.00", "Total": "0.00"},
    {"Quarter": " 1", "Col": None, "Promoter": "0.00", "Public": "0.00",
     "Others": "0.00", "Total": "0.00"},
]
SHP_PUBLIC = {
    "Table": [{"Fld_TransactionID": 354406}],
    "Table1": [
        {"Fld_Code": "B1", "Fld_ShortCatg": "Public shareholder",
         "Fld_SubCategory": "Institutions", "Fld_Level": None,
         "Fld_ShareHolderName": None, "Fld_TotalPercentageOf_A_B_C2": 0.0},
        {"Fld_Code": "", "Fld_ShortCatg": "Public shareholder",
         "Fld_SubCategory": "Institutions (Domestic)", "Fld_Level": None,
         "Fld_ShareHolderName": None, "Fld_TotalPercentageOf_A_B_C2": 0.0},
        {"Fld_Code": "B1c", "Fld_ShortCatg": "Public shareholder",
         "Fld_SubCategory": "Institutions", "Fld_Level": "Alternate Investment Funds",
         "Fld_ShareHolderName": "INDIA-AHEAD VENTURE FUND",
         "Fld_TotalPercentageOf_A_B_C2": 2.1},
        {"Fld_Code": "", "Fld_ShortCatg": "Public shareholder",
         "Fld_SubCategory": "Institutions (Domestic)", "Fld_Level": "Sub Total B1",
         "Fld_ShareHolderName": None, "Fld_TotalPercentageOf_A_B_C2": 5.89},
        {"Fld_Code": "", "Fld_ShortCatg": "Public shareholder",
         "Fld_SubCategory": "Institutions (Foreign)", "Fld_Level": "Sub Total B2",
         "Fld_ShareHolderName": None, "Fld_TotalPercentageOf_A_B_C2": 0.57},
        {"Fld_Code": "B3", "Fld_ShortCatg": "Public shareholder",
         "Fld_SubCategory": "Non-Institutions", "Fld_Level": None,
         "Fld_ShareHolderName": None, "Fld_TotalPercentageOf_A_B_C2": 0.0},
        {"Fld_Code": "", "Fld_ShortCatg": "Public shareholder",
         "Fld_SubCategory": "Non-Institutions",
         "Fld_Level": "Resident Individuals holding nominal share capital up to Rs. 2 lakhs",
         "Fld_ShareHolderName": None, "Fld_TotalPercentageOf_A_B_C2": 12.36},
        {"Fld_Code": "", "Fld_ShortCatg": "Public shareholder",
         "Fld_SubCategory": "Non-Institutions",
         "Fld_Level": "Resident Individuals holding nominal share capital in excess of Rs. 2 lakhs",
         "Fld_ShareHolderName": "MUKUL MAHAVIR AGRAWAL",
         "Fld_TotalPercentageOf_A_B_C2": 5.25},
        {"Fld_Code": "STB3", "Fld_ShortCatg": "Public shareholder",
         "Fld_SubCategory": "Non-Institutions", "Fld_Level": "Sub Total B4",
         "Fld_ShareHolderName": None, "Fld_TotalPercentageOf_A_B_C2": 33.15},
        {"Fld_Code": "STB1B2B3", "Fld_ShortCatg": "Public shareholder",
         "Fld_SubCategory": None, "Fld_Level": "B=B1+B2+B3+B4",
         "Fld_ShareHolderName": None, "Fld_TotalPercentageOf_A_B_C2": 39.61},
    ],
}
SHP_PROMOTERS = {
    "Table": [{"Fld_TransactionId": 354406}],
    "Table1": [
        {"Fld_Code": "A1", "Fld_ShortCatg": "Promoter and Promoter Group",
         "Fld_SubCategory": "Indian", "Fld_Level": None, "Fld_ShareHolderName": None,
         "Fld_TotalPercentageOf_A_B_C2": 0.0},
        {"Fld_Code": "A1a", "Fld_ShortCatg": "Promoter and Promoter Group",
         "Fld_SubCategory": "Indian", "Fld_Level": "Individuals/Hindu undivided Family",
         "Fld_ShareHolderName": None, "Fld_TotalPercentageOf_A_B_C2": 60.39},
        {"Fld_Code": "A1a", "Fld_ShortCatg": None, "Fld_SubCategory": "Indian",
         "Fld_Level": "Individuals/Hindu undivided Family",
         "Fld_ShareHolderName": "HIREN RAJENDRA MEHTA",
         "Fld_TotalPercentageOf_A_B_C2": 60.19},
        {"Fld_Code": "A1a", "Fld_ShortCatg": None, "Fld_SubCategory": "Indian",
         "Fld_Level": "Individuals/Hindu undivided Family",
         "Fld_ShareHolderName": "HARSHABEN MEHTA", "Fld_TotalPercentageOf_A_B_C2": 0.1},
        {"Fld_Code": "A1a", "Fld_ShortCatg": None, "Fld_SubCategory": "Indian",
         "Fld_Level": "Individuals/Hindu undivided Family",
         "Fld_ShareHolderName": "DEEPA PINAK MEHTA", "Fld_TotalPercentageOf_A_B_C2": 0.0},
        {"Fld_Code": "STA1", "Fld_ShortCatg": "Promoter and Promoter Group",
         "Fld_SubCategory": "Indian", "Fld_Level": "Sub Total A1", "Fld_ShareHolderName": None,
         "Fld_TotalPercentageOf_A_B_C2": 60.39},
        {"Fld_Code": "STA1A2", "Fld_ShortCatg": "Promoter and Promoter Group",
         "Fld_SubCategory": None, "Fld_Level": "A=A1+A2", "Fld_ShareHolderName": None,
         "Fld_TotalPercentageOf_A_B_C2": 60.39},
    ],
}

ISIN_UNIFIED = "INE1ABX01018"
SYMBOL_UNIFIED = "UNIFIED"
CODE_UNIFIED = "544406"

_SOFT_FAIL_MARKERS = ("<app-root>", "Response.StatusCode=404", "<!DOCTYPE html>")


def _as_bse_json(body, status_guard=True):
    """The published ``bse_json`` contract over a raw or pre-parsed body."""
    if body is None:
        return None
    if isinstance(body, (dict, list)):
        data = body
    else:
        text = body.decode("utf-8", "replace") if isinstance(body, bytes) else str(body)
        if not text.strip():
            return None
        if any(marker in text[:8192] for marker in _SOFT_FAIL_MARKERS):
            return None
        try:
            data = json.loads(text)
        except ValueError:
            return None
        if isinstance(data, str):  # double-encoded body
            try:
                data = json.loads(data)
            except ValueError:
                return None
    if not isinstance(data, (dict, list)) or not data:
        return None
    if status_guard and isinstance(data, dict) and str(data.get("Status")).lower() == "false":
        return None
    return data


class FakeBse:
    """Injected fetcher: routes by URL substring, records every call."""

    def __init__(self, routes=None, default=None, status_guard=True):
        self.routes = routes or {}
        self.default = BODY_323 if default is None else default
        self.status_guard = status_guard
        self.calls = []

    def __call__(self, url, params=None):
        params = dict(params or {})
        self.calls.append((url, params))
        body = self.default
        for needle, value in self.routes.items():
            if needle in url:
                body = value(url, params) if callable(value) else value
                break
        return _as_bse_json(body, self.status_guard)

    def params_for(self, needle):
        return [params for url, params in self.calls if needle in url]


def _announcement_row(index, day):
    return {
        "NEWSID": f"ann-{index}",
        "NEWS_DT": f"2026-09-{day:02d}T10:30:00",
        "CATEGORYNAME": "Company Update",
        "SUBCATNAME": "General",
        "HEADLINE": f"Announcement {index}",
        "ATTACHMENTNAME": f"file{index}.pdf",
    }


def _ann_page(count, start=1, total=None, day_offset=0):
    rows = [_announcement_row(i, ((i + day_offset - 1) % 28) + 1) for i in range(start, start + count)]
    return {"Table": rows, "Table1": [{"ROWCNT": str(total if total is not None else count)}]}


def _unified_fetcher(results=UNIFIED_RESULTS, tab=SHP_TAB, aggregate=SHP_AGGREGATE,
                     index=SHP_INDEX, announcements=None):
    """The full UNIFIED 544406 route set, every endpoint answering."""
    return FakeBse({
        "ComHeadernew": UNIFIED_HEADER,
        "TabResults_PAR": json.dumps(results),
        "CorporatesSHPSecuritybeta": lambda url, params: aggregate if "qtrid" in params else index,
        "TabResults_SHP": {"Table": tab},
        "SHPPubShold": SHP_PUBLIC,
        "PromoterNGroup": SHP_PROMOTERS,
        "AnnSubCategoryGetData": announcements if announcements is not None
        else _ann_page(1, total=1),
    })


# --------------------------------------------------------------------------
# Label reading
# --------------------------------------------------------------------------
class TestPeriodLabels(unittest.TestCase):
    def test_period_end_from_label(self):
        self.assertEqual(bfc.parse_period_label("Mar-26"), "2026-03-31")
        self.assertEqual(bfc.parse_period_label("Sep-25"), "2025-09-30")
        self.assertEqual(bfc.parse_period_label("Jun-26"), "2026-06-30")
        self.assertEqual(bfc.parse_period_label("Dec-25"), "2025-12-31")
        self.assertEqual(bfc.parse_period_label("Mar 2026"), "2026-03-31")
        self.assertEqual(bfc.parse_period_label("27-May-25"), "2025-05-27")
        self.assertEqual(bfc.parse_period_label("31-Mar-2026"), "2026-03-31")
        self.assertEqual(bfc.parse_period_label("2026-03-31"), "2026-03-31")

    def test_unreadable_labels_are_never_guessed(self):
        self.assertIsNone(bfc.parse_period_label("FY25-26"))
        self.assertIsNone(bfc.parse_period_label(" "))
        self.assertIsNone(bfc.parse_period_label(""))
        self.assertIsNone(bfc.parse_period_label(None))
        self.assertIsNone(bfc.parse_period_label("TOTAL"))
        self.assertIsNone(bfc.fiscal_year_label("Mar-26"))

    def test_fiscal_year_label(self):
        self.assertEqual(bfc.fiscal_year_label("FY25-26"), "FY26")
        self.assertEqual(bfc.fiscal_year_label("FY 2025-2026"), "FY26")
        self.assertEqual(bfc.fiscal_year_label("FY26"), "FY26")

    def test_cadence_inferred_from_label_spacing(self):
        self.assertEqual(bfc._infer_kind(["Mar-26", "Sep-25", "FY25-26"]), bfc.KIND_HALF_YEARLY)
        self.assertEqual(bfc._infer_kind(["", "Jun-26", "Sep-26"]), bfc.KIND_QUARTERLY)
        # Quarterly quarters in the supplementary table decide a blank col2.
        self.assertEqual(
            bfc._infer_kind(["", "Sep-25", "FY25-26", "Jun-26", "Mar-26"]), bfc.KIND_QUARTERLY)


# --------------------------------------------------------------------------
# Sector identity
# --------------------------------------------------------------------------
class TestHeader(unittest.TestCase):
    def test_identity_and_sector(self):
        fetcher = FakeBse({"ComHeadernew": UNIFIED_HEADER})
        header = bfc.fetch_header(CODE_UNIFIED, fetcher=fetcher)

        self.assertEqual(header["bse_code"], CODE_UNIFIED)
        self.assertEqual(header["symbol"], SYMBOL_UNIFIED)
        self.assertEqual(header["isin"], ISIN_UNIFIED)
        self.assertEqual(header["industry"], "IT Enabled Services")
        self.assertEqual(header["industry_new"], "Information Technology")
        self.assertEqual(header["sector"], "Information Technology")
        self.assertEqual(header["igroup"], "IT - Services")
        self.assertEqual(header["isubgroup"], "IT Enabled Services")
        self.assertEqual(header["group"], "M")
        self.assertEqual(header["face_value"], 10.0)
        self.assertEqual(header["eps"], 20.28)
        self.assertEqual(header["pe"], 19.76)
        self.assertIsNone(header["opm_pct"])  # BSE serves "-"
        self.assertIsNone(header["name"])     # COName is empty
        self.assertEqual(fetcher.params_for("ComHeadernew")[0]["scripcode"], CODE_UNIFIED)

    def test_placeholder_body_yields_none(self):
        self.assertIsNone(bfc.fetch_header(CODE_UNIFIED, fetcher=FakeBse(default=BODY_323)))


# --------------------------------------------------------------------------
# Financial results
# --------------------------------------------------------------------------
class TestResults(unittest.TestCase):
    def test_halfyearly_periods_labels_and_rupee_precision(self):
        fetcher = FakeBse({"TabResults_PAR": json.dumps(UNIFIED_RESULTS)})
        result = bfc.fetch_results(CODE_UNIFIED, fetcher=fetcher)

        self.assertEqual(result["value_table"], "resultinM")
        self.assertEqual(result["value_scale"], 0.1)
        self.assertEqual(result["reconciled"], True)
        self.assertEqual(result["mismatches"], [])
        self.assertEqual(result["cr_reconciled"], True)
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["kind"], bfc.KIND_HALF_YEARLY)
        self.assertEqual(len(result["periods"]), 3)

        mar, sep, fy = result["periods"]
        self.assertEqual((mar["label"], mar["kind"], mar["period_end"]),
                         ("Mar-26", bfc.KIND_HALF_YEARLY, "2026-03-31"))
        self.assertEqual((sep["label"], sep["kind"], sep["period_end"]),
                         ("Sep-25", bfc.KIND_HALF_YEARLY, "2025-09-30"))
        self.assertEqual((fy["label"], fy["kind"], fy["period_end"]),
                         ("FY25-26", bfc.KIND_FY, None))
        # Rupee-table precision survives the conversion back to crore.
        self.assertEqual(mar["revenue"], 138.974)
        self.assertEqual(sep["revenue"], 149.028)
        self.assertEqual(fy["revenue"], 288.003)
        self.assertEqual(mar["net_profit"], 23.476)
        self.assertEqual(mar["eps"], 11.69)
        self.assertEqual(mar["cash_eps"], 11.85)
        self.assertEqual(mar["opm_pct"], 22.23)
        self.assertEqual(mar["npm_pct"], 16.89)

        # tabtype is required: without it BSE answers an empty body.
        self.assertEqual(fetcher.params_for("TabResults_PAR")[0]["tabtype"], "RESULTS")

    def test_double_encoded_body_is_read(self):
        payload = FakeBse({"TabResults_PAR": json.dumps(json.dumps(UNIFIED_RESULTS))})
        self.assertEqual(len(bfc.fetch_results(CODE_UNIFIED, fetcher=payload)["periods"]), 3)

    def test_blank_col2_quarterly_labels_are_read_not_assumed(self):
        fetcher = FakeBse({"TabResults_PAR": json.dumps(QUARTERLY_RESULTS)})
        result = bfc.fetch_results("544320", fetcher=fetcher)

        self.assertEqual(result["kind"], bfc.KIND_QUARTERLY)
        self.assertEqual([p["label"] for p in result["periods"]], ["Jun-26", "Sep-26"])
        self.assertEqual([p["kind"] for p in result["periods"]],
                         [bfc.KIND_QUARTERLY, bfc.KIND_QUARTERLY])
        self.assertEqual(result["periods"][0]["period_end"], "2026-06-30")
        self.assertEqual(result["periods"][0]["revenue"], 118.25)
        self.assertEqual(result["periods"][1]["revenue"], 120.5)
        # No FY column, so there is nothing to reconcile against.
        self.assertEqual(result["mismatches"], [])
        self.assertEqual(result["reconciled"], True)

    def test_afcom_quarterly_cadence_comes_from_the_supplementary_table(self):
        fetcher = FakeBse({"TabResults_PAR": json.dumps(AFCOM_RESULTS)})
        result = bfc.fetch_results("544224", fetcher=fetcher)

        # col2 is blank and col4 is the FY total, so only resultinS proves the
        # scrip files quarterly (LQ Jun-26, SQ Mar-26).
        self.assertEqual(result["kind"], bfc.KIND_QUARTERLY)
        self.assertEqual([(p["label"], p["kind"]) for p in result["periods"]],
                         [("Sep-25", bfc.KIND_QUARTERLY), ("FY25-26", bfc.KIND_FY)])
        self.assertEqual(result["periods"][0]["period_end"], "2025-09-30")

    def test_unreconciled_halves_are_flagged_not_silent(self):
        fetcher = FakeBse({"TabResults_PAR": json.dumps(AFCOM_RESULTS)})
        result = bfc.fetch_results("544224", fetcher=fetcher)

        self.assertEqual(result["reconciled"], False)
        mismatch = next(m for m in result["mismatches"] if m["field"] == "revenue")
        self.assertEqual(mismatch["sum_v1_v2"], 633.14)
        self.assertEqual(mismatch["total_v3"], 583.11)
        self.assertEqual(mismatch["delta"], 50.03)
        self.assertAlmostEqual(mismatch["delta_pct"], 8.5798, places=3)
        # The figures are still delivered; only the flag records the doubt.
        self.assertEqual(result["periods"][1]["revenue"], 583.11)

    def test_crore_mismatch_is_reported_while_the_rupee_table_is_used(self):
        fetcher = FakeBse({"TabResults_PAR": json.dumps(AFCOM_REAL_RESULTS)})
        result = bfc.fetch_results("544224", fetcher=fetcher)

        # The rupee table is the value source (finer precision)...
        self.assertEqual(result["value_table"], "resultinM")
        self.assertEqual(result["value_scale"], 0.1)
        self.assertEqual(result["periods"][0]["revenue"], 240.278)
        self.assertEqual(result["periods"][1]["revenue"], 583.108)
        # ...but it does not hide the crore table's 8.6% revenue hole.
        self.assertEqual(result["cr_reconciled"], False)
        self.assertEqual(result["reconciled"], False)
        crore_revenue = next(m for m in result["cr_mismatches"] if m["field"] == "revenue")
        self.assertEqual((crore_revenue["sum_v1_v2"], crore_revenue["total_v3"]),
                         (633.14, 583.11))
        self.assertEqual(crore_revenue["delta"], 50.03)

    def test_real_drift_is_flagged_in_both_tables(self):
        fetcher = FakeBse({"TabResults_PAR": json.dumps(YASHHV_RESULTS)})
        result = bfc.fetch_results("544310", fetcher=fetcher)

        self.assertEqual(result["value_table"], "resultinM")
        self.assertEqual(result["reconciled"], False)
        self.assertEqual(result["cr_reconciled"], False)
        revenue = next(m for m in result["mismatches"] if m["field"] == "revenue")
        self.assertAlmostEqual(revenue["delta_pct"], 0.2356, places=3)
        # 1,001.45 M == 100.145 crore: the rupee table carries the extra digit.
        self.assertEqual(result["periods"][1]["revenue"], 100.145)

    def test_two_quarters_are_not_reconciled_against_the_fy_total(self):
        fetcher = FakeBse({"TabResults_PAR": json.dumps(ABB_QUARTERLY_RESULTS)})
        result = bfc.fetch_results("500002", fetcher=fetcher)

        # Two consecutive quarters cover ~half the FY: summing them against the
        # FY total would flag a non-anomaly on every quarterly filer.
        self.assertAlmostEqual(result["fy_coverage"], 0.5106, places=3)
        self.assertEqual(result["mismatches"], [])
        self.assertEqual(result["reconciled"], True)
        self.assertEqual(result["kind"], bfc.KIND_QUARTERLY)
        self.assertEqual([p["kind"] for p in result["periods"]],
                         [bfc.KIND_QUARTERLY, bfc.KIND_QUARTERLY, bfc.KIND_FY])

    def test_malformed_fy_label_is_flagged_and_never_stored_as_a_year(self):
        fetcher = FakeBse({"TabResults_PAR": json.dumps(ABB_QUARTERLY_RESULTS)})
        result = bfc.fetch_results("500002", fetcher=fetcher)

        fy_period = next(p for p in result["periods"] if p["kind"] == bfc.KIND_FY)
        self.assertEqual(fy_period["label"], "FY25-25")
        self.assertEqual(fy_period["label_consistent"], False)
        self.assertIn({"endpoint": "TabResults_PAR",
                       "error": "fy_label_precedes_period:FY25-25"}, result["errors"])

    def test_quarterly_filer_with_a_valid_fy_label_is_not_flagged(self):
        # The quarterly column legitimately sits after the FY total's year, so a
        # valid label must not be mistaken for a contradiction.
        results = json.loads(json.dumps(ABB_QUARTERLY_RESULTS))
        results["col4"] = "FY25-26"
        fetcher = FakeBse({"TabResults_PAR": json.dumps(results)})
        result = bfc.fetch_results("500012", fetcher=fetcher)

        fy_period = next(p for p in result["periods"] if p["kind"] == bfc.KIND_FY)
        self.assertEqual(fy_period["label_consistent"], True)
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["reconciled"], True)

    def test_never_filed_scrip_has_no_periods_and_an_error(self):
        fetcher = FakeBse({"TabResults_PAR": json.dumps(EMPTY_RESULTS)})
        result = bfc.fetch_results("544925", fetcher=fetcher)

        self.assertEqual(result["periods"], [])
        self.assertEqual(result["value_table"], None)
        self.assertEqual(result["errors"], [{"endpoint": "TabResults_PAR",
                                             "error": "no_result_rows"}])

    def test_placeholder_body_yields_no_periods_and_an_error(self):
        self.assertEqual(len(BODY_323), 323)
        result = bfc.fetch_results(CODE_UNIFIED, fetcher=FakeBse(default=BODY_323))

        self.assertEqual(result["periods"], [])
        self.assertTrue(result["errors"])
        self.assertEqual(result["errors"][0]["endpoint"], "TabResults_PAR")


# --------------------------------------------------------------------------
# Shareholding
# --------------------------------------------------------------------------
class TestShareholding(unittest.TestCase):
    def test_index_public_split_and_promoter_names(self):
        fetcher = _unified_fetcher()
        shp = bfc.fetch_shp(CODE_UNIFIED, fetcher=fetcher)

        self.assertTrue(shp["filed"])
        self.assertEqual(shp["quarter"], "March 2026")
        self.assertEqual(shp["qtr_id"], 129)
        self.assertEqual(shp["promoter_pct"], 60.39)
        self.assertEqual(shp["public_pct"], 39.61)
        self.assertEqual(shp["fii_pct"], 0.57)
        self.assertEqual(shp["dii_pct"], 5.89)
        self.assertEqual(shp["retail_pct"], 33.15)
        self.assertEqual(shp["holders"],
                         [{"name": "INDIA-AHEAD VENTURE FUND", "pct": 2.1},
                          {"name": "MUKUL MAHAVIR AGRAWAL", "pct": 5.25}])
        self.assertEqual(shp["promoters"],
                         [{"name": "HIREN RAJENDRA MEHTA", "pct": 60.19},
                          {"name": "HARSHABEN MEHTA", "pct": 0.1},
                          {"name": "DEEPA PINAK MEHTA", "pct": 0.0}])
        self.assertEqual(shp["errors"], [])

        # The split endpoint silently answers an all-zero template in lowercase.
        split_params = fetcher.params_for("SHPPubShold")[0]
        self.assertEqual(split_params["SCRIPCODE"], CODE_UNIFIED)
        self.assertEqual(split_params["QtrCode"], 129)
        self.assertNotIn("scripcode", split_params)
        self.assertEqual(fetcher.params_for("PromoterNGroup")[0]["SCRIPCODE"], CODE_UNIFIED)
        index_calls = fetcher.params_for("CorporatesSHPSecuritybeta")
        self.assertEqual(len(index_calls), 2)
        self.assertNotIn("qtrid", index_calls[0])
        self.assertEqual(index_calls[1]["qtrid"], 129)

    def test_empty_aggregate_falls_back_to_the_newest_filed_row(self):
        def index(url, params):
            if "qtrid" in params:
                return {}  # BSE answers {} for the aggregate on some scrips
            return SHP_INDEX

        fetcher = FakeBse({
            "CorporatesSHPSecuritybeta": index,
            "TabResults_SHP": {"Table": SHP_TAB},
            "SHPPubShold": {"Table1": []},
            "PromoterNGroup": {"Table1": []},
        })
        shp = bfc.fetch_shp(CODE_UNIFIED, fetcher=fetcher)

        # Mar-26 is the placeholder; Sep-25 is the newest filed row.
        self.assertTrue(shp["filed"])
        self.assertEqual(shp["quarter"], "Sep-25")
        self.assertEqual(shp["promoter_pct"], 60.39)
        self.assertEqual(shp["public_pct"], 39.61)
        self.assertIsNone(shp["fii_pct"])
        self.assertIsNone(shp["dii_pct"])
        self.assertIsNone(shp["retail_pct"])

    def test_never_filed_placeholder_is_not_zero_percent_data(self):
        fetcher = FakeBse({
            "CorporatesSHPSecuritybeta": {"Table": []},
            "TabResults_SHP": {"Table": SHP_TAB_NEVER_FILED},
        })
        shp = bfc.fetch_shp("544925", fetcher=fetcher)

        self.assertFalse(shp["filed"])
        self.assertIsNone(shp["quarter"])
        self.assertIsNone(shp["promoter_pct"])
        self.assertIsNone(shp["public_pct"])
        self.assertIsNone(shp["fii_pct"])
        self.assertIsNone(shp["dii_pct"])
        self.assertIsNone(shp["retail_pct"])
        self.assertEqual(shp["holders"], [])
        self.assertEqual(shp["promoters"], [])
        # A never-filed scrip costs two calls, not four.
        self.assertEqual(fetcher.params_for("SHPPubShold"), [])
        self.assertEqual(fetcher.params_for("PromoterNGroup"), [])

    def test_missing_filings_are_none_never_zero(self):
        shp = bfc.fetch_shp("544925", fetcher=FakeBse(default=BODY_323))

        self.assertFalse(shp["filed"])
        self.assertIsNone(shp["promoter_pct"])
        self.assertIsNone(shp["public_pct"])
        self.assertTrue(shp["errors"])


# --------------------------------------------------------------------------
# Announcements
# --------------------------------------------------------------------------
class TestAnnouncements(unittest.TestCase):
    def test_pagination_follows_rowcnt(self):
        def route(url, params):
            page = int(params.get("pageno"))
            if page == 1:
                return _ann_page(50, total=60)
            if page == 2:
                return _ann_page(10, start=51, total=60, day_offset=50)
            return _ann_page(0, total=60)

        fetcher = FakeBse({"AnnSubCategoryGetData": route})
        rows = bfc.fetch_announcements(CODE_UNIFIED, months=12, fetcher=fetcher)

        self.assertEqual(len(rows), 60)
        self.assertEqual([params["pageno"] for params in fetcher.params_for("AnnSubCategoryGetData")],
                         [1, 2])
        self.assertEqual(rows[0]["news_id"], "ann-1")
        self.assertEqual(rows[0]["date"], "2026-09-01")
        self.assertEqual(rows[0]["category"], "Company Update")
        self.assertEqual(rows[0]["subcategory"], "General")
        self.assertEqual(rows[0]["attachment"], "file1.pdf")
        self.assertIn("AnnPdfOpen.aspx?Pname=file1.pdf", rows[0]["pdf_url"])

        first = fetcher.params_for("AnnSubCategoryGetData")[0]
        self.assertEqual(first["strscrip"], CODE_UNIFIED)
        self.assertEqual(first["strCat"], -1)
        self.assertEqual(first["subcategory"], -1)
        self.assertEqual(first["strSearch"], "P")
        self.assertEqual(first["strType"], "C")

    def test_windows_are_capped_at_the_endpoint_limit(self):
        fetcher = FakeBse({"AnnSubCategoryGetData": _ann_page(0, total=0)})
        bfc.fetch_announcements(CODE_UNIFIED, months=24, fetcher=fetcher)

        windows = []
        for params in fetcher.params_for("AnnSubCategoryGetData"):
            start = datetime.strptime(params["strPrevDate"], "%Y%m%d").date()
            end = datetime.strptime(params["strToDate"], "%Y%m%d").date()
            windows.append((start, end))
        self.assertGreaterEqual(len(windows), 2)
        windows.sort()
        for start, end in windows:
            self.assertLessEqual((end - start).days + 1, bfc.MAX_ANNOUNCEMENT_WINDOW_DAYS)
        # Contiguous, no gap and no overlap, and the newest window reaches today.
        for (_, end), (next_start, _) in zip(windows, windows[1:]):
            self.assertEqual(next_start, end + timedelta(days=1))
        self.assertEqual(windows[-1][1], date.today())
        self.assertGreaterEqual(sum((end - start).days + 1 for start, end in windows), 730)

    def test_range_cap_envelope_shrinks_the_window_instead_of_failing(self):
        def route(url, params):
            start = datetime.strptime(params["strPrevDate"], "%Y%m%d").date()
            end = datetime.strptime(params["strToDate"], "%Y%m%d").date()
            if (end - start).days >= 300:
                return {"Status": False, "Message": "Date range cannot exceed 12 months."}
            return {"Table": [{"NEWSID": f"cap-{start.isoformat()}",
                               "NEWS_DT": "2026-09-10T00:00:00",
                               "HEADLINE": f"Window {start.isoformat()}",
                               "ATTACHMENTNAME": "a.pdf"}],
                    "Table1": [{"ROWCNT": "1"}]}

        fetcher = FakeBse({"AnnSubCategoryGetData": route}, status_guard=False)
        rows = bfc.fetch_announcements(CODE_UNIFIED, months=12, fetcher=fetcher)

        calls = fetcher.params_for("AnnSubCategoryGetData")
        self.assertEqual(len(calls), 3)  # one rejected, then both halves
        spans = []
        for params in calls:
            start = datetime.strptime(params["strPrevDate"], "%Y%m%d").date()
            end = datetime.strptime(params["strToDate"], "%Y%m%d").date()
            spans.append((end - start).days + 1)
        self.assertGreaterEqual(spans[0], 300)
        self.assertTrue(all(span < 300 for span in spans[1:]))
        self.assertEqual(len(rows), 2)

    def test_soft_fail_body_yields_no_announcements(self):
        fetcher = FakeBse(default=BODY_323)
        self.assertEqual(bfc.fetch_announcements(CODE_UNIFIED, months=12, fetcher=fetcher), [])


# --------------------------------------------------------------------------
# One scrip, end to end
# --------------------------------------------------------------------------
class TestFetchCompany(unittest.TestCase):
    def test_null_subcalls_are_recorded_and_the_scrip_still_completes(self):
        result = bfc.fetch_company(CODE_UNIFIED, symbol=SYMBOL_UNIFIED, isin=ISIN_UNIFIED,
                                   fetcher=FakeBse(default=BODY_323))

        self.assertEqual(result["bse_code"], CODE_UNIFIED)
        self.assertEqual(result["symbol"], SYMBOL_UNIFIED)
        self.assertEqual(result["isin"], ISIN_UNIFIED)
        self.assertIsNone(result["header"])
        self.assertEqual(result["results"]["periods"], [])
        self.assertFalse(result["shp"]["filed"])
        self.assertEqual(result["announcements_count"], 0)
        endpoints = {entry["endpoint"] for entry in result["errors"]}
        self.assertIn("ComHeadernew", endpoints)
        self.assertIn("TabResults_PAR", endpoints)
        self.assertIn("TabResults_SHP", endpoints)

    def test_header_supplies_symbol_and_isin(self):
        result = bfc.fetch_company(CODE_UNIFIED, fetcher=_unified_fetcher())

        self.assertEqual(result["isin"], ISIN_UNIFIED)
        self.assertEqual(result["symbol"], SYMBOL_UNIFIED)
        self.assertEqual(result["header"]["industry"], "IT Enabled Services")
        self.assertEqual(result["header"]["face_value"], 10.0)
        self.assertEqual(result["header"]["pe"], 19.76)
        self.assertEqual(len(result["results"]["periods"]), 3)
        self.assertTrue(result["shp"]["filed"])
        self.assertEqual(result["announcements_count"], 1)
        self.assertEqual(result["errors"], [])


# --------------------------------------------------------------------------
# Persistence
# --------------------------------------------------------------------------
class TestPersistence(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="bse_fundamentals_"))
        self.mgr = DatabaseManager(db_path=self.tmp / "test.db")
        with self.mgr.session() as conn:
            conn.execute(
                "INSERT INTO master_companies (isin, nse_symbol, bse_code, company_name, is_active) "
                "VALUES (?, ?, ?, ?, 1)",
                (ISIN_UNIFIED, SYMBOL_UNIFIED, CODE_UNIFIED, "Unified Data Tech Solutions Ltd"))
            # Pre-existing forensic row carrying a solvency verdict and metrics
            # this client knows nothing about (BSE has no pledge/ICR/D-E).
            conn.execute(
                "INSERT INTO company_forensic_health (isin, symbol, fiscal_year, "
                " promoter_holding_pct, promoter_pledge_pct, interest_coverage_ratio, "
                " debt_to_equity_ratio, is_solvency_approved, last_evaluated_date) "
                "VALUES (?, ?, 'FY25', 58.00, 7.50, 3.20, 1.10, 0, '2026-08-01')",
                (ISIN_UNIFIED, SYMBOL_UNIFIED))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _fetch_and_persist(self, fetcher=None):
        return bfc.fetch_company(CODE_UNIFIED, symbol=SYMBOL_UNIFIED, isin=ISIN_UNIFIED,
                                 db=self.mgr, persist=True,
                                 fetcher=fetcher if fetcher is not None else _unified_fetcher())

    def _query(self, sql, params=()):
        with self.mgr.session() as conn:
            return conn.execute(sql, params).fetchall()

    def test_persist_writes_financials_and_ownership(self):
        result = self._fetch_and_persist()
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["persisted"], {"quarterly": 2, "annual": 1, "ownership": 1})

        quarters = self._query(
            "SELECT quarter_end_date, financial_year, revenue_inr_cr, net_profit_inr_cr, "
            "eps_inr, pat_margin_pct, source FROM quarterly_financials WHERE isin = ? "
            "ORDER BY quarter_end_date DESC", (ISIN_UNIFIED,))
        self.assertEqual(len(quarters), 2)
        self.assertEqual(tuple(quarters[0])[:4], ("2026-03-31", "FY26-Q4", 138.974, 23.476))
        self.assertEqual(quarters[0]["eps_inr"], 11.69)
        self.assertEqual(quarters[0]["pat_margin_pct"], 16.89)
        self.assertEqual(quarters[0]["source"], "bse_halfyearly")
        self.assertEqual(tuple(quarters[1])[:2], ("2025-09-30", "FY26-Q2"))
        self.assertEqual(quarters[1]["revenue_inr_cr"], 149.028)

        annual = self._query(
            "SELECT fiscal_year, revenue_inr_cr, net_profit_inr_cr, eps_inr, opm_pct, npm_pct, "
            "source FROM annual_financials WHERE isin = ?", (ISIN_UNIFIED,))
        self.assertEqual(len(annual), 1)
        self.assertEqual(annual[0]["fiscal_year"], "FY26")
        self.assertEqual(annual[0]["revenue_inr_cr"], 288.003)
        self.assertEqual(annual[0]["net_profit_inr_cr"], 40.747)
        self.assertEqual(annual[0]["opm_pct"], 18.78)
        self.assertEqual(annual[0]["npm_pct"], 14.15)
        self.assertEqual(annual[0]["source"], "bse_halfyearly")

        forensic = self._query(
            "SELECT promoter_holding_pct, fii_holding_pct, dii_holding_pct, public_holding_pct, "
            "fiscal_year, last_evaluated_date FROM company_forensic_health WHERE isin = ?",
            (ISIN_UNIFIED,))
        self.assertEqual(len(forensic), 1)
        self.assertEqual(forensic[0]["promoter_holding_pct"], 60.39)
        self.assertEqual(forensic[0]["fii_holding_pct"], 0.57)
        self.assertEqual(forensic[0]["dii_holding_pct"], 5.89)
        self.assertEqual(forensic[0]["public_holding_pct"], 39.61)
        self.assertEqual(forensic[0]["fiscal_year"], "FY26")
        self.assertEqual(forensic[0]["last_evaluated_date"], date.today().isoformat())

    def test_second_run_is_idempotent(self):
        self._fetch_and_persist()
        counts = {table: self._query(f"SELECT COUNT(*) FROM {table}")[0][0]
                  for table in ("quarterly_financials", "annual_financials",
                                "company_forensic_health")}
        self.assertEqual(counts, {"quarterly_financials": 2, "annual_financials": 1,
                                  "company_forensic_health": 1})

        second = self._fetch_and_persist()
        self.assertEqual(second["errors"], [])
        for table, expected in counts.items():
            self.assertEqual(self._query(f"SELECT COUNT(*) FROM {table}")[0][0], expected, table)
        row = self._query("SELECT revenue_inr_cr, source FROM quarterly_financials "
                          "WHERE isin = ? AND quarter_end_date = '2026-03-31'", (ISIN_UNIFIED,))[0]
        self.assertEqual(row["revenue_inr_cr"], 138.974)
        self.assertEqual(row["source"], "bse_halfyearly")

    def test_solvency_gate_and_absent_metrics_are_never_touched(self):
        self._fetch_and_persist()
        row = self._query(
            "SELECT is_solvency_approved, promoter_pledge_pct, interest_coverage_ratio, "
            "debt_to_equity_ratio, solvency_disqualification_reasons "
            "FROM company_forensic_health WHERE isin = ?", (ISIN_UNIFIED,))[0]
        # The pre-existing verdict and its metrics survive untouched: BSE carries
        # no pledge / interest coverage / debt-to-equity, so they stay unknown.
        self.assertEqual(row["is_solvency_approved"], 0)
        self.assertEqual(row["promoter_pledge_pct"], 7.5)
        self.assertEqual(row["interest_coverage_ratio"], 3.2)
        self.assertEqual(row["debt_to_equity_ratio"], 1.1)
        self.assertIsNone(row["solvency_disqualification_reasons"])

    def test_fresh_row_leaves_the_solvency_default_alone(self):
        with self.mgr.session() as conn:
            conn.execute(
                "INSERT INTO master_companies (isin, nse_symbol, bse_code, company_name, is_active) "
                "VALUES (?, ?, ?, ?, 1)",
                ("INE0AIRFL01", "AIRFLOA", "544516", "Airfloa Rail Technology Ltd"))
        fetcher = _unified_fetcher()
        result = bfc.fetch_company("544516", symbol="AIRFLOA", isin="INE0AIRFL01",
                                   db=self.mgr, persist=True, fetcher=fetcher)
        self.assertEqual(result["persisted"]["ownership"], 1)
        row = self._query("SELECT is_solvency_approved, promoter_pledge_pct, "
                          "interest_coverage_ratio, debt_to_equity_ratio "
                          "FROM company_forensic_health WHERE isin = ?", ("INE0AIRFL01",))[0]
        # The schema defaults, untouched by this client — not values it wrote.
        self.assertEqual(row["is_solvency_approved"], 1)
        self.assertEqual(row["promoter_pledge_pct"], 0.0)
        self.assertEqual(row["interest_coverage_ratio"], 0.0)
        self.assertEqual(row["debt_to_equity_ratio"], 0.0)

    def test_not_filed_scrip_writes_no_ownership_row(self):
        with self.mgr.session() as conn:
            conn.execute(
                "INSERT INTO master_companies (isin, nse_symbol, bse_code, company_name, is_active) "
                "VALUES (?, ?, ?, ?, 1)",
                ("INE0SPEEDX01", "SPEEDEX", "544925", "Speedex Ltd"))
        fetcher = FakeBse({
            "ComHeadernew": {"SecurityId": "SPEEDEX", "SecurityCode": "544925",
                             "ISIN": "INE0SPEEDX01"},
            "TabResults_PAR": json.dumps(EMPTY_RESULTS),
            "CorporatesSHPSecuritybeta": {"Table": []},
            "TabResults_SHP": {"Table": SHP_TAB_NEVER_FILED},
            "AnnSubCategoryGetData": _ann_page(0, total=0),
        })
        result = bfc.fetch_company("544925", symbol="SPEEDEX", isin="INE0SPEEDX01",
                                   db=self.mgr, persist=True, fetcher=fetcher)

        self.assertEqual(result["persisted"], {"quarterly": 0, "annual": 0, "ownership": 0})
        self.assertEqual(self._query("SELECT COUNT(*) FROM company_forensic_health "
                                     "WHERE isin = ?", ("INE0SPEEDX01",))[0][0], 0)

    def test_quarterly_labels_persist_with_the_quarterly_source(self):
        with self.mgr.session() as conn:
            conn.execute(
                "INSERT INTO master_companies (isin, nse_symbol, bse_code, company_name, is_active) "
                "VALUES (?, ?, ?, ?, 1)",
                ("INE0QTR01011", "QTRCO", "544320", "Quarterly Co Ltd"))
        fetcher = _unified_fetcher(results=QUARTERLY_RESULTS)
        result = bfc.fetch_company("544320", symbol="QTRCO", isin="INE0QTR01011",
                                   db=self.mgr, persist=True, fetcher=fetcher)

        self.assertEqual(result["persisted"], {"quarterly": 2, "annual": 0, "ownership": 1})
        quarters = self._query(
            "SELECT quarter_end_date, financial_year, source FROM quarterly_financials "
            "WHERE isin = ? ORDER BY quarter_end_date", ("INE0QTR01011",))
        self.assertEqual([tuple(row) for row in quarters],
                         [("2026-06-30", "FY27-Q1", "bse_quarterly"),
                          ("2026-09-30", "FY27-Q2", "bse_quarterly")])
        self.assertEqual(self._query("SELECT COUNT(*) FROM annual_financials "
                                     "WHERE isin = ?", ("INE0QTR01011",))[0][0], 0)

    def test_contradictory_fy_label_is_not_persisted_as_an_annual_row(self):
        with self.mgr.session() as conn:
            conn.execute(
                "INSERT INTO master_companies (isin, nse_symbol, bse_code, company_name, is_active) "
                "VALUES (?, ?, ?, ?, 1)",
                ("INE0ABB01011", "ABB", "500002", "ABB India Ltd"))
        fetcher = _unified_fetcher(results=ABB_QUARTERLY_RESULTS)
        result = bfc.fetch_company("500002", symbol="ABB", isin="INE0ABB01011",
                                   db=self.mgr, persist=True, fetcher=fetcher)

        # The two quarters are real, the "FY25-25" total is not a year this data
        # can be filed under, so the quarters land and the annual row does not.
        self.assertEqual(result["persisted"], {"quarterly": 2, "annual": 0, "ownership": 1})
        self.assertIn({"endpoint": "persist",
                       "error": "fy_label_contradicts_periods:FY25-25"}, result["errors"])
        quarters = self._query("SELECT quarter_end_date, financial_year, source "
                               "FROM quarterly_financials WHERE isin = ? "
                               "ORDER BY quarter_end_date", ("INE0ABB01011",))
        self.assertEqual([tuple(row) for row in quarters],
                         [("2026-03-31", "FY26-Q4", "bse_quarterly"),
                          ("2026-06-30", "FY27-Q1", "bse_quarterly")])
        self.assertEqual(self._query("SELECT COUNT(*) FROM annual_financials WHERE isin = ?",
                                     ("INE0ABB01011",))[0][0], 0)

    def test_quarterly_annual_total_lands_on_its_own_fiscal_year(self):
        with self.mgr.session() as conn:
            conn.execute(
                "INSERT INTO master_companies (isin, nse_symbol, bse_code, company_name, is_active) "
                "VALUES (?, ?, ?, ?, 1)",
                ("INE0ANDP01011", "ANDHRAPET", "500012", "Andhra Petrochemicals Ltd"))
        results = json.loads(json.dumps(ABB_QUARTERLY_RESULTS))
        results["col4"] = "FY25-26"
        result = bfc.fetch_company("500012", symbol="ANDHRAPET", isin="INE0ANDP01011",
                                   db=self.mgr, persist=True,
                                   fetcher=_unified_fetcher(results=results))

        self.assertEqual(result["persisted"], {"quarterly": 2, "annual": 1, "ownership": 1})
        annual = self._query("SELECT fiscal_year, revenue_inr_cr, source FROM annual_financials "
                             "WHERE isin = ?", ("INE0ANDP01011",))
        self.assertEqual([tuple(row) for row in annual], [("FY26", 13202.73, "bse_quarterly")])

    def test_ownership_columns_never_include_the_solvency_gate(self):
        result = bfc.fetch_company(CODE_UNIFIED, symbol=SYMBOL_UNIFIED, isin=ISIN_UNIFIED,
                                   fetcher=_unified_fetcher())
        row = bfc._ownership_row(result)
        self.assertEqual(set(row), {"isin", "symbol", "fiscal_year", "promoter_holding_pct",
                                    "fii_holding_pct", "dii_holding_pct", "public_holding_pct",
                                    "last_evaluated_date"})
        self.assertNotIn("is_solvency_approved", row)


# --------------------------------------------------------------------------
# Universe run
# --------------------------------------------------------------------------
class TestUniverse(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="bse_universe_"))
        self.mgr = DatabaseManager(db_path=self.tmp / "test.db")
        self.checkpoint = self.tmp / "checkpoint.jsonl"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _seed(self, count, start=500001):
        with self.mgr.session() as conn:
            for offset in range(count):
                code = str(start + offset)
                conn.execute(
                    "INSERT INTO master_companies (isin, nse_symbol, bse_code, company_name, "
                    " is_active) VALUES (?, ?, ?, ?, 1)",
                    (f"INE{code}0101", f"SYM{offset}", code, f"Company {offset}"))

    def test_dry_run_reports_per_endpoint_success_and_writes_nothing(self):
        self._seed(3)
        summary = bfc.fetch_universe(db=self.mgr, limit=0, dry_run=True, workers=2, pace=0,
                                     fetcher=_unified_fetcher())

        self.assertEqual(summary["universe_size"], 3)
        self.assertEqual(summary["scrips_processed"], 3)
        self.assertEqual(summary["scrips_with_results"], 3)
        self.assertEqual(summary["scrips_with_shp"], 3)
        self.assertEqual(summary["scrips_no_filing"], 0)
        self.assertEqual(summary["scrips_reconciled"], 3)
        self.assertEqual(summary["scrips_unreconciled"], 0)
        self.assertEqual(summary["scrips_cr_unreconciled"], 0)
        self.assertEqual(summary["scrips_fy_label_flagged"], 0)
        self.assertEqual(summary["error_count"], 0)
        self.assertEqual(summary["endpoint_success"],
                         {"announcements": 3, "header": 3, "results": 3, "shp": 15})
        self.assertEqual(summary["announcements_total"], 3)
        self.assertEqual(summary["periods_total"], 9)
        self.assertEqual(summary["rows_written"], {"quarterly": 0, "annual": 0, "ownership": 0})
        self.assertGreaterEqual(summary["elapsed_sec"], 0.0)
        for table in ("quarterly_financials", "annual_financials", "company_forensic_health"):
            self.assertEqual(self._query_count(table), 0)
        self.assertFalse(self.checkpoint.exists())

    def _query_count(self, table):
        with self.mgr.session() as conn:
            return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]

    def test_checkpoint_resumes_and_persists_when_not_dry(self):
        self._seed(3)
        first = bfc.fetch_universe(db=self.mgr, dry_run=False, workers=1, pace=0,
                                   checkpoint_path=self.checkpoint,
                                   fetcher=_unified_fetcher())
        self.assertEqual(first["scrips_processed"], 3)
        self.assertEqual(first["scrips_skipped_checkpoint"], 0)
        self.assertEqual(first["rows_written"], {"quarterly": 6, "annual": 3, "ownership": 3})
        lines = [line for line in self.checkpoint.read_text(encoding="utf-8").splitlines() if line]
        self.assertEqual(len(lines), 3)
        self.assertEqual(json.loads(lines[0])["bse_code"], "500001")

        second = bfc.fetch_universe(db=self.mgr, dry_run=False, workers=1, pace=0,
                                    checkpoint_path=self.checkpoint,
                                    fetcher=_unified_fetcher())
        self.assertEqual(second["scrips_processed"], 0)
        self.assertEqual(second["scrips_skipped_checkpoint"], 3)
        self.assertEqual(self._query_count("quarterly_financials"), 6)
        self.assertEqual(self._query_count("company_forensic_health"), 3)

    def test_limit_and_selector(self):
        self._seed(5)
        summary = bfc.fetch_universe(db=self.mgr, limit=2, dry_run=True, workers=1, pace=0,
                                     fetcher=_unified_fetcher())
        self.assertEqual(summary["universe_size"], 2)
        self.assertEqual(summary["scrips_processed"], 2)
        self.assertIn("listing_source", summary["universe_selector"])

    def test_errors_are_bounded_and_every_scrip_still_completes(self):
        self._seed(60)
        summary = bfc.fetch_universe(db=self.mgr, dry_run=True, workers=2, pace=0,
                                     fetcher=FakeBse(default=BODY_323))

        self.assertEqual(summary["scrips_processed"], 60)
        self.assertEqual(summary["scrips_no_filing"], 60)
        self.assertEqual(summary["scrips_with_results"], 0)
        self.assertEqual(summary["scrips_with_shp"], 0)
        self.assertGreater(summary["error_count"], 50)
        self.assertEqual(len(summary["errors"]), 50)
        self.assertEqual(summary["endpoint_success"],
                         {"announcements": 0, "header": 0, "results": 0, "shp": 0})

    def test_fetcher_errors_do_not_abort_the_run(self):
        self._seed(2)

        def explode(url, params=None):
            raise RuntimeError("connection reset")

        with self.assertLogs("reality_engine.bse_fundamentals_client", level="WARNING"):
            summary = bfc.fetch_universe(db=self.mgr, dry_run=True, workers=1, pace=0,
                                         fetcher=FakeBse({"ComHeadernew": explode},
                                                         default=json.dumps(UNIFIED_RESULTS)))
        self.assertEqual(summary["scrips_processed"], 2)
        self.assertEqual(summary["scrips_with_results"], 2)
        self.assertGreater(summary["error_count"], 0)
        self.assertTrue(all("ComHeadernew" in str(entry.get("endpoint"))
                            for entry in summary["errors"][:2]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
