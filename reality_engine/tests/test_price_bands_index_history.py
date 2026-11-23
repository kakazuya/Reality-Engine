"""Offline tests for the price-band and index-history fetchers (no network, no DB)."""
import datetime as dt
import unittest

from reality_engine.scripts.fetch_index_history import (clean_index, even_sample, heading_index,
                                                        is_heading, parse_media_page, parse_notice,
                                                        project, select_notices)
from reality_engine.scripts.fetch_price_bands import (URL, band_pct, even_sample as band_sample,
                                                      parse_band_csv, project as band_project,
                                                      weekdays)

BAND_CSV = (
    '\ufeffSymbol,Series,Security Name,Band,Remarks\r\n'
    '21STCENMGM,EQ,21st Century Management Services Limited,2,-\r\n'
    'BKMINDST,BZ,BKM Industries Limited,2,"GSM STAGE - 0"\r\n'
    'RELIANCE,EQ,Reliance Industries Limited,No Band,-\r\n'
    '5PAISA,BE,5Paisa Capital Limited,5,GSM STAGE - II\r\n'
)

MEDIA_HTML = """
<ul>
<li data-publishdate="August 2024">
    <span>August 23, 2024</span>
    <p><a href="/Press_Release/ind_prs23082024.pdf" target="_blank">
        Replacements in indices and revision in criteria
    </a></p>
</li>
<li data-publishdate="August 2024">
    <span>August 30, 2024</span>
    <p><a href="/Press_Release/ind_prs30082024.pdf" target="_blank">
        Changes in Nifty Fixed Income indices w.e.f. September 04, 2024
    </a></p>
</li>
<li data-publishdate="May 2024">
    <span>May 01, 2024</span>
    <p><a href="/Press_Release/ind_prs01052024.pdf" target="_blank">
        NSE Indices launches Nifty Something Index
    </a></p>
</li>
<li data-publishdate="August 2024">
    <span>August 27, 2024</span>
    <p><a href="/Press_Release/ind_prs27082024_1.pdf" target="_blank">
        Inclusion in Nifty India Defence w.e.f. September 03, 2024
    </a></p>
</li>
<li data-publishdate="December 2018">
    <span>December 31, 2018</span>
    <p><a href="/Press_Release/ind_prs31122018.pdf" target="_blank">
        Replacements in indices
    </a></p>
</li>
<li><p>no date, must be skipped</p></li>
</ul>
"""

NOTICE_2024 = """
PRESS RELEASE 
Mumbai, August 23, 2024 
Replacements in indices and revision in criteria 
The Index Maintenance Sub-Committee (Equity) of NSE Indices Limited has decided to make the 
following changes in various Nifty equity indices as listed hereunder. These changes shall become 
effective from September 30, 2024 (close of September 27, 2024). 
A. Replacements in indices: 
1) Replacements on account of semi-annual review of broad market indices: 
a) Nifty 50 
The following companies are being excluded: 
Sr. No. 
Company Name 
Symbol 
1 
Divi's Laboratories Ltd. 
DIVISLAB 
2 
LTIMindtree Ltd. 
LTIM 
The following companies are being included: 
Sr. No. 
Company Name 
Symbol 
1 
Bharat Electronics Ltd. 
BEL 
2 
Trent Ltd. 
TRENT 
Trent Ltd. has been included in Nifty 50 index as it has highest 6 month average free-float market 
capitalization within eligible universe as a replacement to an excluded constituent. 
The above replacement will also be applicable to Nifty50 Equal Weight index. 
Note:  
1. Trent Ltd. was included in Nifty 50 index as the 6-month average free-float market capitalization 
of these companies within eligible universe is at least 1.5 times the 6-month average free-float 
market capitalization of the smallest constituents. 
b) Nifty Next 50 
The following companies are being excluded: 
Sr. No. 
Company Name 
Symbol 
1 
Berger Paints India Ltd. 
BERGEPAINT 
2 
Colgate Palmolive (India) Ltd. 
COLPAL 
The following company is being included: 
Sr. No. 
Company Name 
Symbol 
1 
Macrotech Developers Ltd. 
LODHA 
"""

NOTICE_2019 = """
Press Release 
September 17, 2019 
Replacements in Indices 
The Index Maintenance Sub-Committee (IMSC) of NSE Indices Limited has decided to make 
replacements in various indices on account of shifting of security to Z category. 
These changes shall become effective from September 24, 2019 (close of September 23, 2019). 
A. Replacement on account of shifting of security to Z category: 
1) 
NIFTY 500 
The following company is being excluded: 
Sr. No. 
Company Name 
Symbol 
1 
Jet Airways (India) Ltd. 
JETAIRWAYS 
The following company is being included: 
Sr. No. 
Company Name 
Symbol 
1 
Vaibhav Global Ltd. 
VAIBHAVGBL 
2) 
NIFTY Smallcap 250 
The following company is being excluded: 
Sr. No. 
Company Name 
Symbol 
1 
Jet Airways (India) Ltd. 
JETAIRWAYS 
B. Exclusion of a security from NIFTY SME EMERGE Index: 
The following exclusion shall be made from NIFTY SME EMERGE index on account of proposed 
shifting of the company to the Capital market segment (Main Board) from NSE EMERGE platform. 
The following company is being excluded: 
Sr. No. 
Company Name 
Symbol 
1 
Akash Infra Projects Ltd. 
AKASH 
No inclusion is being made in the index. 
"""


class BandParserTests(unittest.TestCase):
    def test_band_pct(self):
        self.assertEqual(band_pct("2"), 2)
        self.assertEqual(band_pct(" 5.0 "), 5)
        self.assertIsNone(band_pct("No Band"))
        self.assertIsNone(band_pct(""))
        self.assertIsNone(band_pct("-"))

    def test_parse_band_csv(self):
        rows = parse_band_csv(BAND_CSV, "2024-04-01")
        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[0], {"date": "2024-04-01", "symbol": "21STCENMGM", "series": "EQ",
                                   "isin": None, "band_pct": 2, "remarks": None})
        self.assertEqual(rows[1]["remarks"], "GSM STAGE - 0")
        self.assertIsNone(rows[2]["band_pct"])  # F&O name: No Band
        self.assertEqual(rows[3]["band_pct"], 5)

    def test_parse_band_csv_skips_blank_symbol(self):
        rows = parse_band_csv("Symbol,Series,Security Name,Band,Remarks\n,,,\n", "2024-04-01")
        self.assertEqual(rows, [])

    def test_url_and_weekdays(self):
        self.assertEqual(URL.format(d=dt.date(2019, 12, 30)),
                         "https://nsearchives.nseindia.com/content/equities/sec_list_30122019.csv")
        days = list(weekdays(dt.date(2024, 4, 1), dt.date(2024, 4, 7)))
        self.assertEqual([d.isoformat() for d in days],
                         ["2024-04-01", "2024-04-02", "2024-04-03", "2024-04-04", "2024-04-05"])

    def test_even_sample_and_projection(self):
        days = list(weekdays(dt.date(2024, 1, 1), dt.date(2024, 1, 31)))
        self.assertEqual(len(band_sample(days, 5)), 5)
        self.assertEqual(band_sample(days, 500), days)
        mean, seconds = band_project(100, 3.0, [0.2] * 10)
        self.assertAlmostEqual(mean, 0.2)
        self.assertAlmostEqual(seconds, 320.0)


class IndexNoticeTests(unittest.TestCase):
    def test_clean_and_heading(self):
        self.assertEqual(clean_index("a) Nifty 50"), "NIFTY 50")
        self.assertEqual(clean_index("NIFTY50 Equal Weight Index"), "NIFTY 50 EQUAL WEIGHT")
        self.assertEqual(clean_index("NIFTY Midcap 150"), "NIFTY MIDCAP 150")
        self.assertEqual(heading_index("B. Exclusion of a security from NIFTY SME EMERGE Index:"),
                         "NIFTY SME EMERGE")
        self.assertTrue(is_heading("Nifty India Defence"))
        self.assertFalse(is_heading("The following companies are being excluded:"))
        self.assertFalse(is_heading("Note: Trent Ltd. was included in Nifty 50 index"))
        self.assertFalse(is_heading("The above replacement will also be applicable to Nifty50 Equal Weight index."))

    def test_parse_media_page(self):
        entries = parse_media_page(MEDIA_HTML)
        self.assertEqual(len(entries), 5)  # the li without a date is skipped
        self.assertEqual(entries[0], {"published": "2024-08-23",
                                      "title": "Replacements in indices and revision in criteria",
                                      "url": "/Press_Release/ind_prs23082024.pdf"})
        self.assertTrue(entries[1]["title"].startswith("Changes in Nifty Fixed Income"))

    def test_select_notices(self):
        entries = parse_media_page(MEDIA_HTML)
        start, end = dt.date(2019, 1, 1), dt.date(2024, 12, 31)
        picked = select_notices(entries, start, end)
        self.assertEqual([e["url"].rsplit("/", 1)[-1] for e in picked],
                         ["ind_prs23082024.pdf", "ind_prs27082024_1.pdf"])
        self.assertEqual(len(select_notices(entries, start, end, include_fixed=True)), 3)
        # 2018 is out of range even with fixed income included
        self.assertNotIn("/Press_Release/ind_prs31122018.pdf", [e["url"] for e in picked])

    def test_parse_notice_2024(self):
        rows = parse_notice(NOTICE_2024, "2024-08-23")
        self.assertEqual(len(rows), 7)
        row = rows[0]
        self.assertEqual(row["index_name"], "NIFTY 50")
        self.assertEqual(row["symbol"], "DIVISLAB")
        self.assertEqual(row["company_name"], "Divi's Laboratories Ltd.")
        self.assertEqual(row["change_type"], "exclusion")
        self.assertEqual(row["effective_date"], "2024-09-30")
        self.assertEqual(row["announced_date"], "2024-08-23")
        self.assertEqual([r["symbol"] for r in rows if r["change_type"] == "inclusion"],
                         ["BEL", "TRENT", "LODHA"])
        self.assertEqual({r["index_name"] for r in rows}, {"NIFTY 50", "NIFTY NEXT 50"})
        # "The above replacement ... Nifty50 Equal Weight" is a sentence, not a table
        self.assertNotIn("NIFTY 50 EQUAL WEIGHT", {r["index_name"] for r in rows})

    def test_parse_notice_2019_embedded_heading(self):
        rows = parse_notice(NOTICE_2019, "2019-09-17")
        by_index = {}
        for r in rows:
            by_index.setdefault(r["index_name"], []).append((r["symbol"], r["change_type"]))
        self.assertEqual(by_index["NIFTY 500"],
                         [("JETAIRWAYS", "exclusion"), ("VAIBHAVGBL", "inclusion")])
        self.assertEqual(by_index["NIFTY SMALLCAP 250"], [("JETAIRWAYS", "exclusion")])
        self.assertEqual(by_index["NIFTY SME EMERGE"], [("AKASH", "exclusion")])
        self.assertEqual({r["effective_date"] for r in rows}, {"2019-09-24"})

    def test_effective_date_falls_back_to_title(self):
        rows = parse_notice("NIFTY 50\nThe following company is being excluded:\nSr. No.\n"
                            "Company Name\nSymbol\n1\nFoo Ltd.\nFOO\n", "2026-09-15",
                            title="Replacements in indices w.e.f. September 30, 2026")
        self.assertEqual(rows[0]["effective_date"], "2026-09-30")

    def test_methodology_notice_has_no_rows(self):
        text = ("Revision in eligibility criteria for inclusion of stocks in NIFTY indices\n"
                "The eligibility criteria for inclusion in Nifty indices have been revised.\n")
        self.assertEqual(parse_notice(text, "2019-08-20"), [])

    def test_index_even_sample_and_projection(self):
        notices = [{"published": f"20{y}-01-01", "title": "x", "url": f"/{y}.pdf"} for y in range(10, 20)]
        self.assertEqual(len(even_sample(notices, 4)), 4)
        mean, seconds = project(448, 3.0, [2.0] * 10)  # a slow PDF page
        self.assertAlmostEqual(mean, 2.0)
        self.assertAlmostEqual(seconds, 2240.0)


if __name__ == "__main__":
    unittest.main()
