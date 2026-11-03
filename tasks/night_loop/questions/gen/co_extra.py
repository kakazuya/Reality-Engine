"""Extra questions: third-order ripples every company gets, and one or two per company where a lens or order fell short."""
from common import A, D, F, G, K, N, P, R, S, V, q, many


def ripple_all(c):
    d = "2026-06-30" if c.sym == "HINDALCO" else "2026-09-30"
    return [
        q("ownership", 3, "If foreign investors sold Indian equities hard, how many days of normal traded value would {co}'s FPI holding represent?",
          [S("fpi_total", d), P("value_inr"), P("close")], ["fii_holding", "traded_value"], "U42", "computed"),
        q("technical", 3, "On the five worst days for the Nifty 50 in the last year, how did {co} move against the index, and did it recover faster or slower?",
          [P("close"), N("index_price", "relative_return", "2026-11-03")], ["relative_return", "close"], "U42", "comparison"),
        q("valuation", 3, "If {co}'s profit over the next year came in 10% below the trailing level, what would its PE be at today's price, and where does that sit in its one-year range?",
          [V("pe"), V("pe", "2025-11-03"), F("pat", c.lq, c.basis)], ["pe", "pat"], "U45", "computed"),
    ]


EXTRA = {
    "BAJFINANCE": [
        q("capital_allocation", 1, "What dividend did Bajaj Finance declare for FY26, and what bonus or split has it done since 2025?", [D("announcement", "dividend"), D("announcement", "bonus")], ["dividend_per_share"], "U19", "list"),
        q("capital_allocation", 2, "How much new capital would Bajaj Finance need per year at its AUM growth and retained profit, against its capital ratio?", [K("aum", "Q2FY27"), F("pat", "Q2FY27"), K("crar_pct", "Q2FY27")], ["car", "aum_growth"], "NB09", "computed"),
    ],
    "HDFCBANK": [
        q("guidance", 2, "What did HDFC Bank say a year ago about bringing its CD ratio down, and how close has it come?", [D("transcript", "CD ratio"), K("cd_ratio", "Q2FY27")], ["cd_ratio"], "BK08", "comparison"),
        q("capital_allocation", 1, "How much did HDFC Bank's board declare as dividend for FY26, and what special or interim dividend came with the HDB Financial IPO?", [D("announcement", "dividend"), D("results", "dividend")], ["dividend_per_share"], "U19", "list"),
        q("capital_allocation", 2, "How much capital does HDFC Bank keep after dividends each year, against the capital its loan growth uses?", [K("cet1", "Q2FY27"), K("advances", "Q2FY27"), F("pat", "Q2FY27", "standalone")], ["cet1", "advances"], "BK06", "computed"),
        q("capital_allocation", 1, "What bonus issue or stock split has HDFC Bank done since 2025, and what is the face value now?", [D("announcement", "bonus")], ["book_value_per_share"], "U20", "text"),
        q("guidance", 3, "If deposits keep growing slower than the system, what would HDFC Bank have to do with loan growth, given its CD ratio?", [K("cd_ratio", "Q2FY27"), K("deposit_growth", "Q2FY27"), D("transcript", "deposit")], ["cd_ratio", "deposit_growth", "loan_growth"], "BK08", "text"),
    ],
    "SBILIFE": [
        q("capital_allocation", 1, "What interim dividend did SBI Life declare in March 2026, per share?", [D("announcement", "dividend")], ["solvency_ratio"], "U19", "number"),
        q("capital_allocation", 2, "How much profit does SBI Life keep against the capital new business uses (new business strain)?", [D("deck", "VoNB"), D("transcript", "capital")], ["solvency_ratio", "vnb"], "LI05", "computed"),
        q("capital_allocation", 1, "How much does SBI Life's shareholder fund hold in investments, and what income did it earn in FY26?", [D("annual_report", "shareholders")], ["aum"], "LI04", "number"),
    ],
    "INFY": [
        q("results", 3, "How would a sharp US dollar move change Infosys's reported revenue growth between dollars and rupees?", [K("revenue_usd", "Q2FY27"), F("revenue_from_operations", "Q2FY27"), D("transcript", "currency")], ["rupee_sensitivity", "revenue_usd"], "IT07", "computed"),
        q("balance_sheet", 3, "If tech budgets freeze, how long could Infosys keep its dividends and buybacks from its cash and free cash flow?", [A("cash_and_equivalents", "FY26"), D("transcript", "Free cash flow"), D("results", "dividend")], ["fcf", "payout_ratio"], "U38", "computed"),
    ],
    "SUNPHARMA": [
        q("guidance", 2, "Did Sun Pharma's H1 FY27 growth match the outlook it gave at the start of FY27?", [D("transcript", "growth"), K("revenue", "Q2FY27")], ["revenue"], "U22", "comparison"),
        q("results", 3, "How much US specialty sales would Sun Pharma lose if tariffs passed through at the announced rate on imports only?", [D("transcript", "tariff"), K("us_revenue_usd", "Q2FY27")], ["us_revenue_usd"], "PH06", "computed"),
    ],
    "MARUTI": [
        q("guidance", 2, "How did Maruti Suzuki's FY26 volume and margin come in against what management had said in early FY26?", [G("volumes", "FY26"), K("volumes", "FY26"), D("transcript", "FY26")], ["volumes"], "U22", "comparison"),
        q("balance_sheet", 2, "How large are Maruti Suzuki's mark-to-market losses on its investments, and why did non-operating income fall?", [D("deck", "mark-to-market"), F("other_income", "Q2FY27")], ["other_income"], "U07", "comparison"),
        q("balance_sheet", 3, "If interest rates fell 100 bps, how much would Maruti Suzuki's treasury income change on its investment book?", [A("investments", "FY26"), F("other_income", "Q2FY27")], ["other_income"], "U38", "computed"),
        q("segments", 3, "How would new small-car competition or a rural slowdown change Maruti Suzuki's share in entry cars, given its small-car growth of 35.9%?", [D("press_release", "small car"), D("transcript", "small car")], ["market_share", "product_mix"], "AO02", "text"),
    ],
    "HINDUNILVR": [
        q("guidance", 1, "What did Hindustan Unilever's CFO say about pricing and margin for the December 2026 quarter?", [D("transcript", "Niranjan"), D("deck", "Mid-term outlook")], ["gross_margin", "price_growth"], "U21", "text"),
        q("balance_sheet", 2, "What is Hindustan Unilever's negative working capital, and how did it move in the latest half?", [A("trade_receivables", "FY26"), A("inventories", "FY26"), D("results", "trade payables")], ["nwc_days"], "U11", "computed"),
        q("balance_sheet", 3, "How would rising input cost tighten Hindustan Unilever's cash conversion, given its negative working capital?", [A("cash_flow_from_operations", "FY26"), D("transcript", "commodity")], ["ocf", "input_cost"], "U40", "text"),
    ],
    "ETERNAL": [
        q("balance_sheet", 3, "If Blinkit's inventory-led share doubled, how much more working capital would Eternal need, against its cash balance?", [D("results", "Inventories"), K("cash_balance", "Q2FY27")], ["cash_balance", "inventory_days"], "CI04", "computed"),
    ],
}
