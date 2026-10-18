"""Tax-rule table for the backtest harness (PIPELINE_TODO A1, 2026-10-19). Table `tax_rules` in equity_intelligence.db.

Every row carries the enacted source (Gazette PDF kept in data/tax_sources/, URL, page) and a verbatim quote; the
builder refuses to write a row whose quote is not found in its PDF's text (whitespace / quote marks normalised).
Effective dates come from the Acts, never from the Budget speech: the speech (policy_events) gives announced_at only.

Rules (listed equity, resident individual; rates are fractions):
  stcg_rate, ltcg_rate            by transfer (sell) date
  ltcg_exemption_inr              per financial year (basis 'fy'): FY 2024-25 is ₹1.25 lakh for the whole year,
                                  gains before 23-Jul-2024 included (Finance (No. 2) Act 2024 s.31)
  ltcg_holding_months             listed equity is long-term when held more than 12 months
  stt_delivery_buy / _sell, stt_intraday_sell
  cess_rate, surcharge_cap_cg     only years whose Finance Act text is in data/tax_sources (gaps listed in --check)
Not modelled: surcharge slabs by income, F&O STT (long only), buy-back taxation (shareholder side; see policy_events).

    python -m reality_engine.scripts.build_tax_rules [--check]
    from reality_engine.scripts.build_tax_rules import tax_rule; tax_rule("stcg_rate", "2024-07-24")  -> 0.2
"""
import argparse
import re
import sqlite3
from functools import lru_cache
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "data"
DB = DATA / "equity_intelligence.db"
SRC = DATA / "tax_sources"
FA2024 = ("finance_no2_act_2024_act15_egazette_256436.pdf", "https://egazette.gov.in/WriteReadData/2024/256436.pdf",
          "Finance (No. 2) Act, 2024 (No. 15 of 2024), assent 16-Aug-2024")
ITA2025 = ("income_tax_act_2025_act30_egazette_265620.pdf", "https://egazette.gov.in/WriteReadData/2025/265620.pdf",
           "Income-tax Act, 2025 (No. 30 of 2025), assent 21-Aug-2025, in force 1-Apr-2026")
FA2026 = ("finance_act_2026_act4_egazette_271439.pdf", "https://egazette.gov.in/WriteReadData/2026/271439.pdf",
          "Finance Act, 2026 (No. 4 of 2026), assent 30-Mar-2026")
NSE_STT = ("nse_circular_FATAX56235_stt_2023.pdf", "https://archives.nseindia.com/content/circulars/FATAX56235.pdf",
           "NSE circular NSE/FATAX/56235 (1-Apr-2023): STT rate table")
FA2018 = ("finance_act_2018_act13_egazette_184302.pdf", "https://egazette.gov.in/writereaddata/2018/184302.pdf",
          "Finance Act, 2018 (No. 13 of 2018), assent 28-Mar-2018")
OPEN, END = "1900-01-01", "9999-12-31"

# rule, value, effective_from, effective_to, basis, announced_at, policy_event_ids, source, quote, note
ROWS = [
    ("stcg_rate", 0.15, OPEN, "2024-07-22", "sell_date", None, None, FA2024,
     "at the rate of fifteen per cent. for any transfer which takes place before the 23rd day of July, 2024",
     "s.111A; rate in force before the 2024 change (in force since 2008)"),
    ("stcg_rate", 0.20, "2024-07-23", "2026-03-31", "sell_date", "2024-07-23", "802,8261,8299", FA2024,
     "at the rate of twenty per cent. for any transfer which takes place on or after the 23rd day of July, 2024",
     "s.111A as substituted by s.29"),
    ("stcg_rate", 0.20, "2026-04-01", END, "sell_date", "2025-08-21", None, ITA2025,
     "income-tax calculated on such short-term capital gains at the rate of 20%", "Income-tax Act 2025 s.196"),
    ("ltcg_rate", 0.10, OPEN, "2024-07-22", "sell_date", None, None, FA2024,
     "on long-term capital gains at the rate of ten per cent. for any transfer which takes place before the 23rd day "
     "of July, 2024", "s.112A; in force since 1-Apr-2018 (Finance Act 2018)"),
    ("ltcg_rate", 0.125, "2024-07-23", "2026-03-31", "sell_date", "2024-07-23", "803,8262,8297", FA2024,
     "on long-term capital gains, at the rate of twelve and one-half per cent. for any transfer which takes place on "
     "or after the 23rd day of July, 2024", "s.112A(2)(i) as substituted by s.31"),
    ("ltcg_rate", 0.125, "2026-04-01", END, "sell_date", "2025-08-21", None, ITA2025,
     "income-tax calculated on such long-term capital gains exceeding ₹ 125000 at the rate of 12.5%",
     "Income-tax Act 2025 s.198(2)(a)"),
    ("ltcg_exemption_inr", 100000, "2018-04-01", "2024-03-31", "fy", "2018-02-01", None, FA2018,
     "the amount of income-tax calculated on such long-term capital gains exceeding one lakh rupees at the rate of ten "
     "per cent.", "s.112A inserted by s.33 w.e.f. 1-Apr-2019 (assessment year) = FY 2018-19 transfers onward"),
    ("ltcg_exemption_inr", 125000, "2024-04-01", "2026-03-31", "fy", "2024-07-23", "804,8262", FA2024,
     "the amount of income-tax calculated on such long-term capital gains exceeding one lakh twenty-five thousand "
     "rupees", "s.112A(2)(i) as substituted by s.31: one limit over both rate periods of FY 2024-25"),
    ("ltcg_exemption_inr", 125000, "2026-04-01", END, "fy", "2025-08-21", None, ITA2025,
     "long-term capital gains exceeding ₹ 125000", "Income-tax Act 2025 s.198(2)(a)"),
    ("ltcg_holding_months", 12, "2026-04-01", END, "buy_date", "2025-08-21", None, ITA2025,
     "the words “twelve months” had been substituted", "Income-tax Act 2025 holding-period rule for listed shares"),
    ("stt_delivery_buy", 0.001, "2023-04-01", END, "trade_date", None, None, NSE_STT,
     "Purchase of an equity share in a company or a unit of a business trust",
     "0.1 per cent, purchaser; unchanged by Finance (No. 2) Act 2024 s.162 and Finance Act 2026 (F&O only)"),
    ("stt_delivery_sell", 0.001, "2023-04-01", END, "trade_date", None, None, NSE_STT,
     "Sale of an equity share in a company or a unit of a business trust",
     "0.1 per cent, seller; same note"),
    ("stt_intraday_sell", 0.00025, "2023-04-01", END, "trade_date", None, None, NSE_STT,
     "is settled otherwise than by the actual delivery", "0.025 per cent, seller"),
    ("cess_rate", 0.04, "2024-04-01", "2025-03-31", "fy", None, None, FA2024,
     "“Health and Education Cess on income-tax”, calculated at the rate of four per cent. of such income-tax and "
     "surcharge", "FY 2024-25; FY 2019-20..2023-24 and 2025-26 Finance Acts not stored yet (4% since FY 2018-19)"),
    ("cess_rate", 0.04, "2026-04-01", "2027-03-31", "fy", None, None, FA2026,
     "“Health and Education Cess on income-tax”, calculated at the rate of four per cent. of such income-tax and "
     "surcharge", "tax year 2026-27"),
    ("surcharge_cap_cg", 0.15, "2024-04-01", "2025-03-31", "fy", None, None, FA2024,
     "the rate of surcharge on the income-tax in respect of that part of income shall not exceed fifteen per cent",
     "surcharge on income under ss.111A/112/112A capped at 15%"),
]
# Rows the NSE table proves for earlier years too: the 2023 circular lists 0.1% as 'No Change' (rate upto 31-Mar-2023)
ROWS += [("stt_delivery_buy", 0.001, OPEN, "2023-03-31", "trade_date", None, None, NSE_STT, "(No Change)",
          "rate upto 31-Mar-2023 column: 0.1 per cent"),
         ("stt_delivery_sell", 0.001, OPEN, "2023-03-31", "trade_date", None, None, NSE_STT, "(No Change)",
          "rate upto 31-Mar-2023 column: 0.1 per cent"),
         ("stt_intraday_sell", 0.00025, OPEN, "2023-03-31", "trade_date", None, None, NSE_STT, "(No Change)",
          "rate upto 31-Mar-2023 column: 0.025 per cent")]
# holding period before 2026: 12 months for listed equity under the 1961 Act (s.2(42A)); source text not stored yet
ROWS += [("ltcg_holding_months", 12, OPEN, "2026-03-31", "buy_date", None, None, None, None,
          "s.2(42A) Income-tax Act 1961: listed equity long-term after 12 months; source text not stored yet")]

DDL = """CREATE TABLE IF NOT EXISTS tax_rules (rule TEXT, value REAL, effective_from TEXT, effective_to TEXT, basis TEXT,
    announced_at TEXT, policy_event_ids TEXT, source_title TEXT, source_url TEXT, source_file TEXT, source_page INTEGER,
    quote TEXT, quote_verified INTEGER, note TEXT, built_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (rule, effective_from))"""


def norm(s):
    s = s.replace("“", '"').replace("”", '"').replace("’", "'").replace("‘", "'").replace("—", "-").replace("–", "-")
    return re.sub(r"\s+", " ", s).strip()


@lru_cache(maxsize=None)
def pages(fname):
    import pymupdf
    return [norm(p.get_text()) for p in pymupdf.open(SRC / fname)]


def locate(src, quote):
    """Page (1-based) whose text contains the quote, allowing a quote to run across a page break."""
    ps, q = pages(src[0]), norm(quote)
    for i, p in enumerate(ps):
        if q in p or (i + 1 < len(ps) and q in p + " " + ps[i + 1]):
            return i + 1
    return None


def build(check_only=False):
    out, bad = [], []
    for rule, val, a, b, basis, ann, pe, src, quote, note in ROWS:
        page = locate(src, quote) if src else None
        if src and page is None:
            bad.append((rule, a, quote[:60]))
        out.append((rule, val, a, b, basis, ann, pe, src[2] if src else None, src[1] if src else None,
                    src[0] if src else None, page, quote, int(page is not None) if src else 0, note))
    print(f"{len(out)} rows; quote not found: {bad or 'none'}; rows without stored source: "
          f"{[(r[0], r[2]) for r in out if r[7] is None]}")
    if bad:
        raise SystemExit("refusing to write: quotes not found in their source")
    if check_only:
        return
    con = sqlite3.connect(DB, timeout=600)
    con.execute(DDL)
    con.execute("DELETE FROM tax_rules")
    con.executemany("INSERT INTO tax_rules (rule, value, effective_from, effective_to, basis, announced_at, "
                    "policy_event_ids, source_title, source_url, source_file, source_page, quote, quote_verified, "
                    "note) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", out)
    con.commit()
    print("tax_rules written:", con.execute("SELECT COUNT(*) FROM tax_rules").fetchone()[0])


def tax_rule(rule, date, con=None):
    """Value of `rule` in force on `date` (sell date for rates; for basis 'fy' pass any date in the financial year)."""
    con = con or sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    r = con.execute("SELECT value FROM tax_rules WHERE rule = ? AND effective_from <= ? AND effective_to >= ? "
                    "ORDER BY effective_from DESC LIMIT 1", (rule, str(date)[:10], str(date)[:10])).fetchone()
    return r[0] if r else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="verify quotes only, write nothing")
    a = ap.parse_args()
    build(a.check)
    if a.check:
        return
    tests = [("stcg_rate", "2024-07-22", 0.15), ("stcg_rate", "2024-07-24", 0.20), ("ltcg_rate", "2024-07-22", 0.10),
             ("ltcg_rate", "2024-07-23", 0.125), ("ltcg_exemption_inr", "2024-05-10", 125000),
             ("ltcg_exemption_inr", "2023-05-10", 100000), ("stcg_rate", "2026-06-01", 0.20),
             ("stt_delivery_sell", "2021-03-01", 0.001), ("ltcg_holding_months", "2022-01-01", 12)]
    fails = [(r, d, exp, tax_rule(r, d)) for r, d, exp in tests if tax_rule(r, d) != exp]
    print("ALL CHECKS PASSED" if not fails else f"FAILED: {fails}")


if __name__ == "__main__":
    main()
