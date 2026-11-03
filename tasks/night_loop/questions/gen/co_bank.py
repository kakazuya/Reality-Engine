"""Questions rewritten from master-bank ideas found by the hand read of the bank diff (from_mids = the bank row), dated to the window."""
from common import A, D, F, G, K, N, P, R, q, many


def mb(mid, *a, **k):
    spec = q(*a, **k)
    spec["mids"] = [mid]
    return spec


Q4 = ["Q3FY26", "Q4FY26", "Q1FY27", "Q2FY27"]
BANK = {
    "KEC": [
        mb("MB0465", "results", 3, "If copper rises 20% in a quarter, who bears it in KEC International's chain of cable makers, its EPC contracts and its fixed-price orders, and what contract terms protect it?", [D("transcript", "copper"), D("annual_report", "fixed price")], ["commodity_pass_through", "fixed_price_share"]),
        mb("MB0549", "orders", 2, "What is KEC International's T&D book-to-bill for {ytd}, order intake against revenue?", [K("order_intake", "H1FY27"), K("revenue", "H1FY27")], ["book_to_bill"], kind="computed"),
        mb("MB0794", "orders", 3, "For KEC International's margin, which turned first in the last year: the order book, steel prices or the award pipeline?", [*many(K, "order_book", Q4), *many(K, "ebitda_margin_pct", Q4), D("transcript", "steel")], ["order_book", "ebitda_margin"], kind="comparison"),
        mb("MB0666", "orders", 3, "How did the Budget's roads and railway outlay reach KEC International's Civil and Transportation order intake, and with what lag?", [D("transcript", "Budget"), K("order_intake", "Q2FY27")], ["order_inflow", "government_share"], kind="text"),
    ],
    "BAJFINANCE": [
        mb("MB0962", "capital_allocation", 2, "How much share issuance has funded Bajaj Finance's growth since 2025, and is book value per share growing as fast as AUM?", [R("book_value_per_share", "Q2FY27"), K("aum", "Q2FY27"), D("announcement", "allotment")], ["book_value_per_share", "aum_growth"], kind="comparison"),
        mb("MB0985", "guidance", 2, "After the RBI's rate moves, did Bajaj Finance's cost of funds change before its AUM growth, and what lag does the last year show?", [*many(K, "cost_of_funds_pct", Q4), *many(K, "aum", Q4)], ["cost_of_funds", "aum_growth"], kind="comparison"),
        mb("MB0664", "orders", 3, "The collateral-free loan limit for small enterprises rose from April 2026. How would that reach Bajaj Finance's MSME lending?", [D("transcript", "MSME")], ["product_mix"], kind="text"),
    ],
    "HINDALCO": [
        mb("MB0345", "capital_allocation", 1, "How much renewable-energy capacity does Hindalco have, of what mix, and what did management say it does to cost?", [D("annual_report", "renewable"), D("transcript", "renewable")], ["captive_power_share", "power_cost"], kind="number"),
        mb("MB0702", "results", 3, "When seaborne coal spikes and power demand peaks, how does that reach Hindalco's aluminium margin, given it buys some power and coal from outside?", [D("transcript", "coal"), K("cost_of_production", "Q1FY27")], ["coal_cost", "power_cost"], kind="text"),
        mb("MB0771", "results", 3, "When the rupee weakens, Hindalco gains on dollar-priced metal and loses on imported inputs. What is the net effect on its India business?", [D("transcript", "rupee"), D("annual_report", "foreign currency")], ["fx_hedge", "lme_price"], kind="computed"),
        mb("MB0954", "valuation", 2, "What is Hindalco's ROCE for FY26 against its cost of capital, and does aluminium or copper carry it?", [R("roce", "FY26"), D("annual_report", "segment")], ["roce", "upstream_ebitda"], kind="computed"),
        mb("MB0979", "segments", 2, "Where does Hindalco's management place its aluminium cost on the global cost curve, and what does it say about Novelis's position?", [D("transcript", "cost curve"), D("annual_report", "quartile")], ["cost_of_production"], kind="text"),
    ],
    "HDFCBANK": [
        mb("MB0385", "governance", 1, "What key audit matters did HDFC Bank's auditors report in the FY26 annual report?", [D("annual_report", "Key Audit Matter")], ["roa"], kind="list"),
        mb("MB0931", "results", 2, "Was HDFC Bank's {lq} NIM move real, or a one-off from treasury or interest on tax refund, and what did management say to expect?", [D("transcript", "NIM", period="Q2FY27"), R("nim_pct", "Q2FY27", "standalone")], ["nim"], kind="comparison"),
        mb("MB0961", "capital_allocation", 2, "HDFC Bank has never bought back stock. Is retained capital earning above its cost of equity, and should the payout change?", [R("roe", "FY26", "standalone"), R("dividend_payout_pct", "FY26", "standalone")], ["roe", "payout_ratio"], kind="comparison"),
        mb("MB0662", "balance_sheet", 3, "How did the RBI's hedging-cost support for fresh FCNR(B) deposits change HDFC Bank's funding cost and swap book?", [D("transcript", "FCNR")], ["cost_of_deposits"], kind="text"),
        mb("MB0671", "results", 3, "If the repo rose 25 bps, how would HDFC Bank's loans split between EBLR, MCLR and fixed, and its deposits between savings and term, move NIM?", [D("annual_report", "EBLR"), D("transcript", "repo")], ["nim", "yield_on_advances"], kind="computed"),
        mb("MB1025", "technical", 2, "When did HDFC Bank last close below and then reclaim its 50-day average, and what did delivery do on that close?", [P("close"), P("delivery_pct")], ["dma_50", "delivery_pct"], kind="date"),
        mb("MB1054", "technical", 2, "Has HDFC Bank underperformed the Nifty over the last quarter, and has its relative strength turned?", [P("close"), N("index_price", "relative_return", "2026-11-03")], ["relative_return"], kind="computed"),
    ],
    "SBILIFE": [
        mb("MB0809", "segments", 2, "Which of SBI Life's commission paid, APE and SBI's reported insurance fee income moves first, and which is dated in a filing?", [K("commission_ratio", "Q2FY27"), K("ape", "Q2FY27"), D("transcript", "commission")], ["commission_ratio", "ape"], kind="comparison"),
        mb("MB0658", "orders", 3, "If insurance opens to 100% FDI and foreign groups announce Indian ventures, how would that reach SBI Life's bancassurance, commission and margins?", [D("transcript", "FDI"), D("annual_report", "FDI")], ["banca_share", "commission_ratio"], kind="text"),
    ],
    "INFY": [
        mb("MB0907", "technical", 2, "When Infosys fell after a results beat in the last year, did it react to margins, guidance or the rupee assumption?", [P("close"), D("transcript", "guidance"), R("ebit_margin_pct", "Q2FY27")], ["close", "ebit_margin"], kind="comparison"),
        mb("MB0987", "results", 2, "How much of Infosys's margin gain from the weaker rupee was translation, against hedging, and in which quarter did it show?", [D("transcript", "hedg"), D("transcript", "rupee")], ["rupee_sensitivity", "ebit_margin"], kind="computed"),
        mb("MB1000", "balance_sheet", 2, "Has Infosys's unbilled revenue grown faster than revenue, and what does that say about its revenue recognition?", [D("results", "Unbilled"), A("revenue_from_operations", "FY26")], ["dso"], kind="comparison"),
    ],
    "SUNPHARMA": [
        mb("MB0497", "segments", 3, "If the US put a 100% tariff on generic imports from 2028, how exposed would Sun Pharma's US generics be, given where it makes them?", [D("transcript", "tariff"), K("us_generics", "Q2FY27")], ["us_generics"], kind="text"),
        mb("MB0467", "results", 3, "A weaker rupee helps Sun Pharma's exports and raises its imported input costs. What are the two channels, and which is larger?", [D("annual_report", "foreign currency"), D("transcript", "currency")], ["gross_margin"], kind="text"),
    ],
    "MARUTI": [
        mb("MB0932", "results", 2, "Did Maruti Suzuki's {lq} volume growth come from mix or discounts, and what does that say about margin?", [K("volumes", "Q2FY27"), K("discounts", "Q2FY27"), D("transcript", "mix")], ["discounts", "product_mix"], kind="comparison"),
        mb("MB0682", "orders", 3, "If the repo goes up and car loans get dearer, what does that do to the monthly payment on an entry-level car and to Maruti Suzuki's small-car demand?", [D("transcript", "interest"), D("press_release", "small car")], ["domestic_volumes"], kind="text"),
    ],
    "HINDUNILVR": [
        mb("MB0637", "results", 3, "If edible oil and crude-linked packaging costs rise into a weak rural quarter, what does Hindustan Unilever do first: price, grammage or advertising?", [D("transcript", "pricing"), D("transcript", "rural")], ["input_cost", "a_and_p_spend"], kind="text"),
        mb("MB0953", "segments", 2, "Have direct-to-consumer brands taken Hindustan Unilever's share in home and personal care, and what does the volume trend say?", [D("transcript", "D2C"), D("transcript", "market share")], ["market_share", "underlying_volume_growth"], kind="text"),
    ],
    "ETERNAL": [
        mb("MB0974", "segments", 2, "What is food delivery's contribution per order at Eternal, and how much of it is take rate against advertising?", [K("contribution_margin", "Q2FY27"), D("transcript", "advertising")], ["contribution_margin", "take_rate"], kind="computed"),
        mb("MB0941", "valuation", 2, "On Eternal's EV to sales today, what does the multiple imply about the path to durable profit, and which segment has to carry it?", [P("close"), *many(F, "revenue_from_operations", Q4)], ["market_cap", "segment_revenue"], kind="computed"),
        mb("MB1021", "guidance", 2, "For Eternal, what would prove the profitability path is broken rather than delayed, from what management has committed to?", [D("transcript", "margin")], ["adjusted_ebitda_margin_of_gov"], kind="text"),
        mb("MB1052", "technical", 2, "When Eternal last gapped up on a big delivery day, how much of the gap held by the close?", [P("open"), P("close"), P("delivery_pct")], ["gap", "delivery_pct"], kind="date"),
    ],
}
