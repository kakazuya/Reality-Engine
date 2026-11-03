"""HDFCBANK, SBILIFE, INFY, SUNPHARMA: sector (library BK/LI/IT/PH) and company questions."""
from common import A, Co, D, F, G, K, N, P, R, many, q

Q4 = ["Q3FY26", "Q4FY26", "Q1FY27", "Q2FY27"]

HDFC = Co("HDFCBANK", "HDFC Bank", "HDFC Bank", "500180", "bank", "bank", Q4, "Q2 FY27", basis="standalone",
          rating_note="What international ratings (Moody's, S&P) does HDFC Bank hold, and how do they compare with its domestic rating?")


def hdfc():
    L = "Q2FY27"
    b = "standalone"
    return [
        q("orders", 1, "What were HDFC Bank's gross advances and deposits at 30 September 2026, and their YoY growth?", [K("advances", L), K("deposits", L)], ["advances", "deposits", "loan_growth", "deposit_growth"], "BK01"),
        q("orders", 1, "How did HDFC Bank's advances split between retail mortgages, other retail, CRB and corporate at the end of {lq}?", [D("press_release", "advances"), D("results", "advances", period=L)], ["advances", "sector_exposure"], "BK01", "list"),
        q("orders", 2, "How did HDFC Bank's loan growth and deposit growth compare across the last four quarters, and which grew faster?", [*many(K, "loan_growth", Q4), *many(K, "deposit_growth", Q4)], ["loan_growth", "deposit_growth"], "BK08", "number_series"),
        q("orders", 1, "What was HDFC Bank's average deposit base and the retail deposit share at the end of {lq}?", [K("deposits", L), D("transcript", "retail deposits")], ["deposits"], "BK01"),
        q("orders", 2, "What loan growth did HDFC Bank's management say it wants relative to the system, and is it above or below that now?", [G("loan_growth", "FY27"), K("loan_growth", L), D("transcript", "system")], ["loan_growth"], "BK10", "comparison"),
        q("orders", 1, "How much did HDFC Bank's unsecured loans (personal, cards) contribute to advances at the latest quarter?", [K("unsecured_share", L), D("transcript", "unsecured")], ["unsecured_share"], "BK05"),
        q("orders", 2, "How much of the merged HDFC Ltd's mortgage book and high-cost borrowings has HDFC Bank repaid or repriced so far, and how many years are left?", [D("transcript", "borrowings"), D("annual_report", "amalgamation")], ["cd_ratio", "cost_of_deposits"], why="merger after-effects, named in the loop brief", kind="text"),
        q("orders", 2, "How fast did HDFC Bank's corporate book grow, and did management say it is staying away from low-priced loans?", [D("transcript", "corporate"), K("advances", L)], ["advances", "sector_exposure"], "BK01", "text"),
        q("orders", 3, "What would an RBI repo cut do to HDFC Bank's loan repricing and NIM, given its share of floating-rate loans?", [D("transcript", "repo"), R("nim_pct", L, b)], ["nim", "yield_on_advances"], "BK11", "text"),
        q("orders", 3, "How would a change in risk weights on unsecured loans affect HDFC Bank's growth and capital?", [D("transcript", "risk weight"), K("cet1", L)], ["rwa_density", "cet1"], "BK11", "text"),
        q("segments", 1, "What are HDFC Bank's segment results for Treasury, Corporate/Wholesale, Retail and Other Banking in {lq}?", [K("segment_revenue", L, b), K("segment_ebit", L, b), D("results", "Segment information", period=L)], ["segment_revenue", "segment_ebit"], "U01", "list"),
        q("segments", 2, "How do HDFC Bank's subsidiaries HDB Financial, HDFC Life and HDFC AMC add to consolidated profit, against standalone?", [F("pat", L, "consolidated"), F("pat", L, "standalone"), D("results", "HDB Financial")], ["pat"], why="consolidated vs standalone gap", kind="computed"),
        q("segments", 1, "What share of HDB Financial does HDFC Bank hold after the IPO, and what did the IPO bring in?", [D("results", "HDB Financial"), D("annual_report", "HDB Financial")], ["pat"], why="named subsidiary event", kind="text"),
        q("segments", 2, "How much of HDFC Bank's advances are in agriculture, and what happened to slippages there?", [D("transcript", "agri"), D("annual_report", "priority sector")], ["slippages", "sector_exposure"], "BK05", "text"),
        q("segments", 2, "What is the state of HDFC Bank's retail branch expansion and what did it do to costs?", [D("annual_report", "branches"), R("cost_to_income", L, b)], ["cost_to_income"], "BK07", "comparison"),
        q("segments", 3, "How much did the FCNR deposits raised under the RBI window lift HDFC Bank's CD ratio and LCR, and what happens when those deposits mature?", [D("transcript", "FCNR")], ["cd_ratio", "lcr"], why="named on the latest call", kind="text"),
        q("results", 2, "How have HDFC Bank's NIM and cost of deposits moved over the last four quarters, and how much is repricing explained by repo cuts?", [*many(R, "nim_pct", Q4, b), *many(K, "cost_of_deposits", Q4), D("transcript", "NIM")], ["nim", "cost_of_deposits"], "BK03", "number_series"),
        q("results", 1, "What were HDFC Bank's gross NPA, net NPA and provision coverage in {lq}?", [K("gnpa_pct", L), K("nnpa_pct", L), K("provision_coverage_pct", L)], ["gnpa", "nnpa", "pcr"], "BK04"),
        q("results", 2, "How have HDFC Bank's slippages and credit cost moved over the last four quarters, and which segments drove them?", [*many(K, "slippages", Q4), *many(K, "credit_cost", Q4), D("transcript", "slippage")], ["slippages", "credit_cost"], "BK05", "number_series"),
        q("results", 1, "What floating and contingent provisions does HDFC Bank hold at the latest quarter?", [D("results", "floating provision", period=L)], ["pcr"], why="a large buffer named in its notes", kind="number"),
        q("results", 2, "What are HDFC Bank's fee income and treasury gains by quarter, and how did they change its core income?", [*many(K, "fee_income", Q4), D("press_release", "fees")], ["fee_income"], "U07", "number_series"),
        q("results", 3, "How would a rise in NPAs in microfinance, cards or agriculture hit HDFC Bank's credit cost next year, given its exposure?", [D("transcript", "credit cost"), K("unsecured_share", L)], ["credit_cost", "unsecured_share"], "BK11", "text"),
        q("guidance", 1, "What did HDFC Bank's management say on the {call} call about FY27 loan growth and when its CD ratio would normalise?", [D("transcript", "CD ratio", period=L), G("loan_growth", "FY27")], ["loan_growth", "cd_ratio"], "BK10", "text"),
        q("guidance", 2, "Did HDFC Bank deliver the loan growth it talked about at the start of FY26?", [G("loan_growth", "FY26"), K("loan_growth", "FY26")], ["loan_growth"], "BK10", "comparison"),
        q("guidance", 1, "What has HDFC Bank said about the expected NIM path after deposit repricing, and when does it expect the bottom?", [D("transcript", "margin"), G("nim", "FY27")], ["nim"], "BK10", "text"),
        q("guidance", 3, "What would the planned RBI liquidity and LCR rule changes do to HDFC Bank's deposit strategy, per management?", [D("transcript", "LCR")], ["lcr", "deposits"], "BK11", "text"),
        q("balance_sheet", 1, "What are HDFC Bank's CAR, CET1 and LCR at the end of {lq}, and how much headroom do they leave?", [K("car", L), K("cet1", L), K("lcr", L)], ["car", "cet1", "lcr"], "BK06"),
        q("balance_sheet", 2, "What is HDFC Bank's credit-deposit ratio at the end of {lq}, how has it moved through the last four quarters, and does it limit growth?", [*many(K, "cd_ratio", Q4), K("advances", L), K("deposits", L)], ["cd_ratio"], "BK08", "computed"),
        q("balance_sheet", 2, "How have HDFC Bank's CASA ratio and retail CASA growth moved over the last four quarters?", [*many(K, "casa_ratio", Q4), D("transcript", "CASA")], ["casa_ratio"], "BK02", "number_series"),
        q("balance_sheet", 1, "How much AT1 did HDFC Bank call in August 2026, and what did that do to its capital and interest cost?", [D("transcript", "AT1")], ["car", "finance_cost"], why="named on the latest call", kind="text"),
        q("balance_sheet", 2, "How much has HDFC Bank's standalone net worth grown, and what is its book value per share at the latest quarter?", [K("book_value_per_share", L), A("net_worth", "FY26", b)], ["book_value_per_share"], "BK09", "computed"),
        q("capital_allocation", 1, "What did HDFC Bank disclose about RBI approval for investing in IndusInd Bank and its stake in HDFC Life?", [D("announcement", "IndusInd"), D("announcement", "HDFC Life")], ["sector_exposure"], why="named announcements", kind="text"),
        q("capital_allocation", 3, "If HDFC Bank keeps buying HDFC Life shares to hold its stake above the level it disclosed in April 2026, what does that take from its capital?", [D("announcement", "HDFC Life"), K("cet1", "Q2FY27")], ["cet1"], why="named purchase in its filings", kind="text"),
        q("governance", 1, "Why did Atanu Chakraborty resign as HDFC Bank's Chairman, and what did the board and management say to investors about it?", [D("transcript", "Chakraborty"), D("announcement", "Resignation")], ["roa"], why="named governance event", kind="text"),
        q("governance", 1, "Who is Anup Bagchi, when does he take over as HDFC Bank's Managing Director & CEO, and on what term?", [D("announcement", "Anup Bagchi")], ["roa"], why="named CEO succession", kind="text"),
        q("governance", 1, "What was the RBI penalty on HDFC Bank in November 2025, and for what?", [D("announcement", "RBI Penalty")], ["roa"], "U48", "text"),
        q("governance", 2, "What is the current position on HDFC Bank's dealings tied to the Dubai branch or other regulatory orders, and did management say the business is affected?", [D("transcript", "Dubai"), D("announcement", "order")], ["roa"], "U48", "text"),
        q("valuation", 1, "What is HDFC Bank's adjusted book value per share and price to adjusted book today?", [K("abv", L), P("close")], ["abv", "p_abv"], "BK09", "computed"),
        q("valuation", 2, "How does HDFC Bank's price to adjusted book compare with its RoA now and a year ago?", [K("abv", L), K("roa_pct", L), P("close", "2025-11-03")], ["p_abv", "roa"], "BK09", "computed"),
        q("valuation", 2, "How much of HDFC Bank's market value is its stakes in listed subsidiaries, at today's prices?", [D("annual_report", "subsidiaries"), P("close")], ["market_cap"], why="sum-of-parts view", kind="computed"),
        q("valuation", 3, "What RoA and loan growth must HDFC Bank reach by FY28 for today's price to adjusted book to look cheap?", [K("roa_pct", L), K("abv", L), P("close")], ["roa", "loan_growth", "p_abv"], "U45", "computed"),
        q("balance_sheet", 3, "What would rising deposit competition from mutual funds and small banks do to HDFC Bank's cost of deposits and CASA, given management's comments?", [D("transcript", "deposit")], ["cost_of_deposits", "casa_ratio"], "BK03", "text"),
    ]


SBI = Co("SBILIFE", "SBI Life Insurance", "SBI Life", "540719", "insurance_life", "ins", Q4, "Q2 FY27", basis="standalone", promoter="State Bank of India",
         rating_note="Does SBI Life hold a claims-paying or issuer rating, and does it disclose one in its annual report?")


def sbi():
    L = "Q2FY27"
    return [
        q("orders", 1, "What were SBI Life's annualised premium equivalent (APE) and value of new business in {ytd}, and the YoY growth?", [K("ape", "H1FY27"), K("vnb", "H1FY27")], ["ape", "vnb"], "LI01"),
        q("orders", 1, "What were SBI Life's new business premium and gross written premium for {ytd}?", [K("new_business_premium", "H1FY27"), K("gwp", "H1FY27")], ["new_business_premium", "gwp"], "LI01"),
        q("orders", 1, "What is SBI Life's private market share in Individual Rated Premium in {ytd}?", [D("press_release", "Individual Rated Premium"), K("market_share", "H1FY27")], ["ape"], why="named headline figure", kind="number"),
        q("orders", 2, "How did SBI Life's APE and VNB move across the last four quarters?", [*many(K, "ape", Q4), *many(K, "vnb", Q4)], ["ape", "vnb"], "LI01", "number_series"),
        q("orders", 1, "How much group new business premium did SBI Life write in {ytd}, and what share of new business was it?", [D("transcript", "Group new business premium")], ["new_business_premium"], "LI02"),
        q("orders", 1, "How much guaranteed non-par savings and annuity and pension new business did SBI Life write in {ytd}?", [D("transcript", "non-par"), D("transcript", "annuity")], ["product_mix"], "LI02"),
        q("orders", 2, "What growth did SBI Life's credit life business have, and how did changing bank lending affect it?", [D("transcript", "credit life")], ["product_mix"], "LI02", "text"),
        q("orders", 2, "How many offices and agents does SBI Life have, and what is the productivity per agent?", [D("deck", "Offices", period=L), D("transcript", "agent")], ["channel_mix"], "LI02", "number"),
        q("orders", 3, "How would slower loan growth at State Bank of India change SBI Life's credit-life sales and bancassurance APE?", [D("transcript", "credit life"), D("transcript", "banca")], ["banca_share", "ape"], "LI02", "text"),
        q("orders", 3, "How has the GST exemption on individual premiums changed SBI Life's demand, and does it hurt margins through lost input credit?", [D("transcript", "GST"), K("vnb_margin", L)], ["vnb_margin", "ape"], "LI06", "text"),
        q("segments", 1, "What is SBI Life's product mix (ULIP, non-par, par, protection, annuity, group) in {ytd} on an APE basis?", [K("product_mix", "H1FY27"), D("deck", "Product Portfolio Mix", period=L)], ["product_mix"], "LI02", "list"),
        q("segments", 1, "What is SBI Life's channel mix (SBI and RRB bancassurance, other banca, agency, direct) on APE in {ytd}?", [K("channel_mix", "H1FY27"), K("banca_share", "H1FY27")], ["channel_mix", "banca_share"], "LI02", "list"),
        q("segments", 2, "How have SBI Life's product and channel mix shifted over the last four quarters, and what did that do to VNB margin?", [*many(K, "product_mix", Q4), *many(K, "vnb_margin", Q4)], ["product_mix", "channel_mix", "vnb_margin"], "LI02", "number_series"),
        q("segments", 2, "What VNB walk did SBI Life show from H1 FY26 to H1 FY27: business volume, mix and profile, assumption changes?", [D("deck", "Impact of Business Volume", period=L)], ["vnb"], "LI02", "computed"),
        q("segments", 2, "How does the agency channel's APE growth at SBI Life compare with the banca channel's in {ytd}?", [D("transcript", "agency"), D("transcript", "banca")], ["channel_mix"], "LI02", "comparison"),
        q("segments", 3, "What would a cut in SBI's share of branches selling third-party insurance, or an open-architecture rule, do to SBI Life's channel mix?", [D("transcript", "open architecture"), K("banca_share", L)], ["banca_share"], "LI06", "text"),
        q("results", 1, "What were SBI Life's VNB margin and PAT for {ytd}?", [K("vnb_margin", "H1FY27"), K("pat", "H1FY27")], ["vnb_margin", "pat"], "LI01"),
        q("results", 1, "What are SBI Life's operating expense ratio and commission ratio for {ytd}?", [K("opex_ratio", "H1FY27"), K("commission_ratio", "H1FY27")], ["opex_ratio", "commission_ratio"], why="reported in its news release", kind="number"),
        q("results", 2, "How has SBI Life's VoNB per share moved, and why does it differ from VNB growth?", [D("press_release", "VoNB per Share")], ["vnb"], why="reported ratio", kind="computed"),
        q("results", 3, "How would a further change in commission caps or expense-of-management rules hit SBI Life's VNB margin?", [D("transcript", "commission")], ["commission_ratio", "vnb_margin"], "LI06", "text"),
        q("guidance", 1, "What APE growth and VNB margin has SBI Life said it expects for FY27?", [G("ape", "FY27"), G("vnb_margin", "FY27"), D("transcript", "margin")], ["ape", "vnb_margin"], "U21"),
        q("guidance", 2, "Did SBI Life's FY26 APE growth and VNB margin match what it guided a year ago?", [G("ape", "FY26"), K("ape", "FY26"), K("vnb_margin", "FY26")], ["ape", "vnb_margin"], "U22", "comparison"),
        q("guidance", 2, "How does SBI Life expect the new surrender value rules to feed through into persistency and margin, and what has it already seen?", [D("transcript", "surrender"), K("persistency_13m", L)], ["persistency_13m", "vnb_margin"], "LI06", "text"),
        q("guidance", 1, "What did SBI Life say about RoEV expectations going forward?", [D("transcript", "ROEV")], ["roev"], "LI04", "text"),
        q("guidance", 3, "How would a fall in bond yields change SBI Life's non-par margin and embedded value, given its hedges?", [D("transcript", "yield"), D("deck", "Economic Assumption")], ["embedded_value", "vnb_margin"], "LI06", "text"),
        q("balance_sheet", 1, "What is SBI Life's solvency ratio at 30 September 2026 against the 150% requirement?", [K("solvency_ratio", L)], ["solvency_ratio"], "LI05"),
        q("balance_sheet", 1, "What are SBI Life's assets under management at 30 September 2026, and how are they split across government securities, equity, debentures and others?", [K("aum", L), D("deck", "Composition of Assets Under Management", period=L)], ["aum"], "LI04", "list"),
        q("balance_sheet", 1, "What is SBI Life's embedded value at 30 September 2026, and its operating return on embedded value?", [K("embedded_value", L), K("roev", L)], ["embedded_value", "roev"], "LI04"),
        q("balance_sheet", 2, "What IEV walk did SBI Life show from March 2026 to September 2026: VNB, unwinding, experience variance, economic changes and capital?", [D("deck", "IEV as on", period=L)], ["embedded_value", "roev"], "LI04", "computed"),
        q("balance_sheet", 1, "What are SBI Life's 13th and 61st month persistency ratios for the latest period, on regular premium?", [K("persistency_13m", L), K("persistency_61m", L)], ["persistency_13m", "persistency_61m"], "LI03"),
        q("balance_sheet", 2, "How have SBI Life's 13th, 25th, 49th and 61st month persistency ratios moved over the last year?", [*many(K, "persistency_13m", Q4), *many(K, "persistency_61m", Q4), D("deck", "Persistency")], ["persistency_13m", "persistency_61m"], "LI03", "number_series"),
        q("balance_sheet", 1, "What is SBI Life's claims settlement ratio in its annual report?", [D("annual_report", "claims")], ["claims_settlement_ratio"], "LI03"),
        q("balance_sheet", 3, "How would a 10% fall in equity markets change SBI Life's embedded value and ULIP sales, from what it discloses?", [D("deck", "Economic Assumption"), D("annual_report", "sensitivity")], ["embedded_value", "product_mix"], "LI06", "text"),
        q("capital_allocation", 1, "Did SBI Life raise any subordinated debt or capital in the window, and what is the amount outstanding?", [D("announcement", "debentures"), D("annual_report", "debentures")], ["solvency_ratio"], why="capital instrument for an insurer", kind="text"),
        q("capital_allocation", 3, "If SBI Life grew APE at its current rate for three years, how far would its solvency fall?", [K("solvency_ratio", L), K("ape", "H1FY27")], ["solvency_ratio", "ape"], why="capital check investors do", kind="computed"),
        q("governance", 1, "Who took over or left SBI Life's board or top management since November 2025 (SBI nominee, MD & CEO)?", [D("announcement", "Change in Directorate")], ["ape"], "U29", "list"),
        q("governance", 2, "How large are SBI Life's commissions and dealings with State Bank of India in FY26, against its total commission?", [D("annual_report", "State Bank of India")], ["related_party_transactions", "banca_share"], "U28", "computed"),
        q("valuation", 1, "What is SBI Life's price to embedded value today?", [K("embedded_value", L), P("close")], ["p_ev"], "LI04", "computed"),
        q("valuation", 2, "How has SBI Life's price to embedded value moved against a year ago?", [K("embedded_value", L), P("close"), P("close", "2025-11-03")], ["p_ev"], "LI04", "comparison"),
        q("valuation", 2, "What is SBI Life's implied value of future new business (market cap minus embedded value), divided by annualised VNB?", [K("embedded_value", L), K("vnb", "H1FY27"), P("close")], ["p_ev", "vnb"], why="standard insurer multiple", kind="computed"),
        q("valuation", 3, "What RoEV and VNB growth must SBI Life keep for today's price to embedded value to hold?", [K("roev", L), K("embedded_value", L), P("close")], ["p_ev", "roev"], "U45", "computed"),
        q("segments", 2, "How is SBI Life's protection business split between individual and group, and what is the sum-assured growth?", [D("transcript", "protection")], ["product_mix"], "LI02", "number"),
    ]


INFY = Co("INFY", "Infosys", "Infosys", "500209", "it_services", "ind", Q4, "Q2 FY27", promoter="the Narayana Murthy and Nilekani families",
          rating_note="Infosys has almost no debt: does it disclose any credit rating at all, and from whom?")


def infy():
    L = "Q2FY27"
    return [
        q("orders", 1, "What large deal TCV did Infosys sign in {lq}, how many deals, and what share was net new?", [K("deal_tcv", L), D("transcript", "Large deals", period=L)], ["deal_tcv", "large_deals"], "IT02"),
        q("orders", 2, "How did Infosys's large deal TCV move across the last four quarters?", [*many(K, "deal_tcv", Q4)], ["deal_tcv"], "IT02", "number_series"),
        q("orders", 1, "What were the two mega deals in Infosys's {lq} TCV, and which clients or industries were they in?", [D("transcript", "mega deals", period=L)], ["large_deals"], why="named on the latest call", kind="text"),
        q("orders", 1, "Which client wins does Infosys name in its {lq} press release?", [D("results", "Client Wins", period=L)], ["large_deals"], "IT02", "list"),
        q("orders", 1, "How many clients does Infosys have above $1 million, $50 million and $100 million per year?", [K("client_buckets", L), D("results", "Fact Sheet", period=L)], ["client_buckets"], "IT05"),
        q("orders", 2, "What has happened to Infosys's top 5, top 10 and top 25 client share over the last four quarters?", [*many(K, "top_client_share", Q4)], ["top_client_share"], "IT05", "number_series"),
        q("orders", 2, "How much of Infosys's revenue is now AI, and how fast is that growing?", [D("transcript", "AI revenue")], ["revenue_usd"], why="headline new measure on the call", kind="number"),
        q("orders", 2, "What does the book-to-bill look like for Infosys, comparing large deal TCV with quarterly revenue?", [K("deal_tcv", L), K("revenue_usd", L)], ["book_to_bill", "deal_tcv"], "IT02", "computed"),
        q("orders", 3, "How much does Topaz and agentic AI cut prices on renewal deals at Infosys, and has management said net deflation is shrinking revenue?", [D("transcript", "deflation"), D("transcript", "Topaz")], ["revenue_usd", "cc_growth"], why="main debate on the sector", kind="text"),
        q("orders", 3, "How would a fall in US bank and retail tech budgets reach Infosys's large deal wins, by its vertical exposure?", [D("transcript", "discretionary"), K("vertical_mix", L)], ["vertical_mix", "deal_tcv"], "IT07", "text"),
        q("segments", 1, "What was Infosys's revenue in dollars in {lq}, with constant-currency growth QoQ and YoY?", [K("revenue_usd", L), K("cc_growth", L)], ["revenue_usd", "cc_growth"], "IT01"),
        q("segments", 1, "How did Infosys's revenue split across Financial Services, Manufacturing, Retail, Communication, Energy, Hi-Tech, Life Sciences in {lq}?", [K("vertical_mix", L), D("results", "Fact Sheet", period=L)], ["vertical_mix"], "IT05", "list"),
        q("segments", 2, "Which of Infosys's verticals are slowing and which are strong, and how did management describe them in the last two calls?", [*many(K, "vertical_mix", Q4), D("transcript", "Financial Services")], ["vertical_mix"], "IT05", "comparison"),
        q("segments", 1, "How did Infosys's revenue split across North America, Europe, India and rest of world in {lq}?", [K("geography_mix", L)], ["geography_mix"], "IT05", "list"),
        q("segments", 2, "How have Infosys's segment margins moved by vertical over the last four quarters?", [*many(K, "segment_ebit", Q4)], ["segment_ebit", "vertical_mix"], "IT05", "number_series"),
        q("segments", 1, "What share of Infosys's revenue is onsite against offshore effort, and fixed-price against time-and-material?", [K("offshore_mix", L), K("fixed_price_share", L)], ["offshore_mix", "fixed_price_share"], "IT03"),
        q("segments", 3, "How would H-1B rule changes reach Infosys's onsite costs and margin, from what management has said?", [D("transcript", "H-1B"), K("offshore_mix", L)], ["offshore_mix", "ebit_margin"], "IT07", "text"),
        q("segments", 3, "How does a 1% rupee move change Infosys's margin, and how much of the recent depreciation was retained?", [D("transcript", "rupee"), R("ebit_margin_pct", L)], ["rupee_sensitivity", "ebit_margin"], "IT07", "text"),
        q("results", 1, "What was Infosys's operating margin in {lq}, and its free cash flow in dollars?", [R("ebit_margin_pct", L), D("transcript", "Free cash flow", period=L)], ["ebit_margin", "fcf"], "IT03"),
        q("results", 2, "What moved Infosys's operating margin over the last four quarters: wage hikes, utilisation, rupee, subcontracting?", [*many(R, "ebit_margin_pct", Q4), D("transcript", "wage"), K("subcontracting_cost", L)], ["ebit_margin", "wage_hike", "utilisation", "subcontracting_cost"], "IT03", "number_series"),
        q("results", 1, "What are Infosys's headcount, net additions, utilisation and attrition in {lq}?", [K("headcount", L), K("net_adds", L), K("utilisation", L), K("attrition", L)], ["headcount", "net_adds", "utilisation", "attrition"], "IT04"),
        q("results", 2, "How have Infosys's headcount and utilisation moved across the last four quarters?", [*many(K, "headcount", Q4), *many(K, "utilisation", Q4)], ["headcount", "utilisation"], "IT04", "number_series"),
        q("results", 3, "If wage hikes come earlier than planned, how would that change Infosys's margin against its 20%-22% band?", [D("transcript", "wage"), G("margin_band", "FY27")], ["wage_hike", "margin_band"], "IT03", "text"),
        q("guidance", 1, "What revenue growth guidance in constant currency and operating margin guidance has Infosys given for FY27 on the {call} call?", [G("cc_growth", "FY27"), G("margin_band", "FY27")], ["cc_growth", "margin_band"], "IT06"),
        q("guidance", 2, "How did Infosys revise its FY27 revenue guidance from the April 2026 call to July and October 2026?", [G("cc_growth", "FY27"), D("transcript", "guidance")], ["cc_growth"], "IT06", "comparison"),
        q("guidance", 2, "Where did Infosys's FY26 finish against the guidance it set in April 2025?", [G("cc_growth", "FY26"), K("cc_growth", "FY26")], ["cc_growth"], "IT06", "comparison"),
        q("guidance", 2, "At H1 FY27 growth, what must H2 FY27 deliver for Infosys to hit the top and bottom of its guidance?", [G("cc_growth", "FY27"), K("revenue_usd", L), K("revenue_usd", "Q1FY27")], ["cc_growth", "revenue_usd"], "IT06", "computed"),
        q("guidance", 3, "What does the softness in volume and pricing pressure Infosys described mean for its FY27 guidance if it continues?", [D("transcript", "pricing pressure")], ["cc_growth"], "IT07", "text"),
        q("balance_sheet", 1, "What is Infosys's cash and investments at 30 September 2026, and its DSO?", [K("dso", L), A("cash_and_equivalents", "FY26"), D("results", "cash and investments", period=L)], ["dso", "net_debt"], "U13"),
        q("balance_sheet", 2, "Why did Infosys's DSO fall to 64 days from a year ago, and is it sustainable?", [K("dso", L), D("transcript", "DSO")], ["dso"], "U11", "text"),
        q("capital_allocation", 1, "What was the size, price and acceptance of Infosys's buyback in November 2025?", [D("announcement", "Buyback")], ["payout_ratio"], "U19", "number"),
        q("capital_allocation", 2, "How much of Infosys's free cash flow has gone back to shareholders under its five-year capital allocation policy, and is it on track?", [D("transcript", "capital allocation"), D("results", "dividend")], ["fcf", "payout_ratio"], "U19", "computed"),
        q("capital_allocation", 1, "What dividend did Infosys declare in its {lq} results, with the record date?", [D("results", "dividend", period=L)], ["dividend_per_share"], "U19", "number"),
        q("capital_allocation", 1, "Which acquisitions has Infosys completed or announced since November 2025, and for how much?", [D("results", "acquired"), D("announcement", "Acquisition")], ["capex"], "U20", "list"),
        q("governance", 1, "How does Infosys's dual listing change what it files: is its US (IFRS) reporting the same as its Indian filing?", [D("results", "IFRS")], ["ebit_margin"], why="a NYSE-listed filer", kind="text"),
        q("governance", 2, "What has Infosys said about the status of its GST or tax demand from Indian authorities?", [D("annual_report", "GST"), D("announcement", "GST")], ["contingent_liabilities"], "U48", "text"),
        q("valuation", 2, "How does Infosys's dividend plus buyback yield compare with its earnings yield today?", [P("close"), R("eps_basic_fy", "FY26"), D("results", "dividend")], ["dividend_yield", "pe"], "U33", "computed"),
        q("valuation", 2, "What is Infosys's cash per share against its price today?", [P("close"), A("cash_and_equivalents", "FY26"), {"kind": "row", "table": "share_capital", "metric": None, "period": "2026-09-30", "basis": None}], ["market_cap"], why="cash-rich company measure", kind="computed"),
    ]


SUN = Co("SUNPHARMA", "Sun Pharmaceutical", "Sun Pharma", "524715", "pharma", "ind", Q4, "Q1 FY27", promoter="Dilip Shanghvi and family",
         rating_note="What international ratings did Sun Pharma disclose in September 2026, and did the Organon deal change them?")


def sun():
    L = "Q2FY27"
    return [
        q("orders", 1, "How many ANDAs and NDAs has Sun Pharma filed and had approved in the US, and how many are pending?", [K("anda_filed", "Q1FY27"), K("anda_approved", "Q1FY27"), K("pending_andas", "Q1FY27"), D("deck", "ANDA")], ["anda_filed", "anda_approved", "pending_andas"], "PH03"),
        q("orders", 1, "What is in Sun Pharma's Innovative Medicines pipeline by candidate and phase?", [D("deck", "Candidate")], ["launches"], "PH03", "list"),
        q("orders", 1, "What new launches has Sun Pharma made since November 2025 in the US and India?", [D("announcement", "launches"), D("transcript", "launch")], ["launches"], "PH03", "list"),
        q("orders", 1, "What were Global Innovative Medicines sales in {lq}, and their share of Sun Pharma's sales?", [D("press_release", "Innovative Medicines", period=L), D("results", "Innovative Medicines", period=L)], ["launches"], why="headline figure", kind="number"),
        q("orders", 2, "How did Sun Pharma's Innovative Medicines sales move across the last four quarters, and which products drove them (Ilumya, Leqselvi, Unloxcyt, Cequa, Odomzo, Winlevi)?", [D("transcript", "Innovative Medicines")], ["launches"], "PH03", "number_series"),
        q("orders", 1, "What is the status of Sun Pharma's semaglutide launch in India, and where does it rank?", [D("transcript", "semaglutide"), D("announcement", "semaglutide")], ["launches"], why="named launch", kind="text"),
        q("orders", 1, "What did Sun Pharma's lerodalcibep licensing deal give it, in which markets, and on what terms?", [D("announcement", "lerodalcibep"), D("transcript", "lerodalcibep")], ["launches"], why="named licensing deal", kind="text"),
        q("orders", 2, "What approvals has Ilumya won or still needs (psoriatic arthritis), and what is the revenue opportunity management sees?", [D("transcript", "Ilumya"), D("announcement", "ILUMYA")], ["launches"], why="named product", kind="text"),
        q("orders", 3, "How would generic competition for gRevlimid's end and later product losses reshape Sun Pharma's US generics revenue?", [D("transcript", "Revlimid")], ["us_generics", "price_erosion"], "PH06", "text"),
        q("orders", 3, "How would generic semaglutide entry and pricing in India change Sun Pharma's chronic share and India growth?", [D("transcript", "semaglutide"), K("chronic_share", "FY26")], ["chronic_share", "domestic_formulations"], "PH05", "text"),
        q("segments", 1, "What were Sun Pharma's revenues from India formulations, US formulations, emerging markets, rest of world and API in {lq}?", [K("domestic_formulations", L), K("us_generics", L), K("emerging_markets", L), K("api_revenue", L)], ["domestic_formulations", "us_generics", "emerging_markets", "api_revenue"], "PH01", "list"),
        q("segments", 2, "How have Sun Pharma's revenue shares across India, US, emerging markets and rest of world moved in the last four quarters?", [*many(K, "domestic_formulations", Q4), *many(K, "us_generics", Q4), *many(K, "emerging_markets", Q4)], ["domestic_formulations", "us_generics", "emerging_markets"], "PH01", "number_series"),
        q("segments", 1, "What is Sun Pharma's market share in India per the AIOCD or Pharmarack report in the latest filing?", [D("press_release", "market share"), K("market_share", L)], ["domestic_formulations"], "PH05"),
        q("segments", 2, "Is Sun Pharma's India business growing faster than the market, and what share is chronic?", [D("transcript", "market"), D("deck", "chronic"), K("chronic_share", "FY26")], ["domestic_formulations", "chronic_share"], "PH05", "comparison"),
        q("segments", 1, "What are Sun Pharma's field force and productivity per representative in India?", [K("field_force", "FY26"), K("mr_productivity", "FY26"), D("deck", "field force")], ["field_force", "mr_productivity"], "PH05"),
        q("segments", 2, "What US sales in dollars did Sun Pharma report in {lq}, and how did Taro add to that?", [K("us_revenue_usd", L), D("transcript", "Taro")], ["us_revenue_usd"], "PH01", "number"),
        q("segments", 3, "How would the US Section 232 tariffs on pharma imports reach Sun Pharma, given what it makes in the US and its specialty sales?", [D("transcript", "tariff"), D("transcript", "Section 232")], ["us_generics", "gross_margin"], "PH06", "text"),
        q("segments", 3, "How would the US most-favoured-nation drug pricing proposals affect Sun Pharma's specialty products?", [D("transcript", "most favored nation")], ["us_revenue_usd", "price_erosion"], "PH06", "text"),
        q("results", 1, "What were Sun Pharma's gross margin and R&D spend as a share of sales in {lq}?", [K("gross_margin", L), K("r_and_d_pct", L), D("press_release", "R&D", period=L)], ["gross_margin", "r_and_d_pct"], "PH04"),
        q("results", 2, "How have Sun Pharma's gross margin and R&D share of sales moved across the last four quarters?", [*many(K, "gross_margin", Q4), *many(K, "r_and_d_pct", Q4)], ["gross_margin", "r_and_d_pct"], "PH04", "number_series"),
        q("results", 1, "What one-off items (Lipitor antitrust settlement, Japan restructuring, acquisition costs) did Sun Pharma exclude from adjusted profit in FY26 and {lq}?", [D("press_release", "Lipitor"), D("results", "exceptional", period=L)], ["exceptional_items"], "U07", "list"),
        q("results", 3, "How would price cuts on drugs in India's NLEM reach Sun Pharma's domestic margin?", [D("annual_report", "NLEM"), D("transcript", "NLEM")], ["nlem_exposure", "domestic_formulations"], "PH06", "text"),
        q("guidance", 1, "What growth or R&D spend has Sun Pharma guided for FY27?", [G("r_and_d_pct", "FY27"), G("revenue_guidance", "FY27"), D("transcript", "R&D")], ["r_and_d_pct"], "U21"),
        q("guidance", 2, "What timeline has Sun Pharma given for closing the Organon deal and regulatory approvals, and has it slipped?", [D("announcement", "Organon"), D("transcript", "Organon")], ["us_generics"], why="largest deal in its history", kind="text"),
        q("guidance", 1, "What has Sun Pharma said about the Halol and Baska plants' readiness for the next USFDA inspection?", [D("transcript", "Baska")], ["usfda_status"], "PH02", "text"),
        q("guidance", 3, "If Organon closes as planned, what would it do to Sun Pharma's revenue mix, margin and innovative share?", [D("transcript", "Organon"), D("deck", "Organon")], ["us_revenue_usd", "gross_margin"], why="reshapes the company", kind="text"),
        q("balance_sheet", 1, "What is Sun Pharma's net cash at the latest quarter, and how does the Organon funding change it?", [K("net_debt", L), D("transcript", "net cash"), D("announcement", "Organon")], ["net_debt"], "U13"),
        q("balance_sheet", 2, "How large is the Organon purchase price and how much debt would Sun Pharma take on, against its EBITDA?", [D("announcement", "Organon"), R("ebitda", "FY26")], ["net_debt", "net_debt_to_ebitda"], why="funding of the deal", kind="computed"),
        q("capital_allocation", 1, "What did Sun Pharma sign to pay for Organon, per share and in total, and when did Organon's shareholders approve?", [D("announcement", "Organon")], ["capex"], why="named acquisition", kind="number"),
        q("capital_allocation", 1, "What did Sun Pharma pay for Innovcare Lifesciences, and what is it buying?", [D("announcement", "Innovcare")], ["capex"], why="named acquisition", kind="number"),
        q("capital_allocation", 2, "How do Sun Pharma's dividends compare with its past payout now that it needs cash for Organon?", [D("results", "dividend"), R("dividend_payout_pct", "FY26")], ["payout_ratio", "net_debt"], "U19", "comparison"),
        q("governance", 1, "What is the USFDA status of Sun Pharma's Baska and Halol plants and others: OAI, warning letter, Form 483, import alert?", [D("announcement", "US FDA"), D("annual_report", "USFDA")], ["usfda_status", "oai", "form_483", "warning_letter"], "PH02", "list"),
        q("governance", 2, "What does Sun Pharma's OAI at Baska in December 2025 mean for products already made there and for new approvals?", [D("announcement", "Baska"), D("transcript", "Baska")], ["usfda_status", "oai"], "PH02", "text"),
        q("governance", 1, "Where do the Lipitor antitrust and other US generic-price litigations stand at Sun Pharma, with amounts?", [D("announcement", "Lipitor"), D("annual_report", "antitrust")], ["contingent_liabilities"], "U48", "text"),
        q("governance", 2, "How has the promoter's role changed at Sun Pharma, and who is now the Managing Director, after Aalok Shanghvi and Kirti Ganorkar's moves?", [D("announcement", "Managing Director")], ["related_party_transactions"], "U29", "text"),
        q("valuation", 2, "What is Sun Pharma's EV after adding the Organon debt, against combined EBITDA?", [P("close"), D("announcement", "Organon"), R("ebitda", "FY26")], ["ev_ebitda"], "U45", "computed"),
        q("valuation", 3, "How much of Sun Pharma's price today depends on Innovative Medicines growth, against its generic business?", [P("close"), D("press_release", "Innovative Medicines")], ["pe", "launches"], "U45", "computed"),
        q("results", 2, "How much did Sun Pharma's FY26 Revlimid drop-off hurt US sales and how is it reported for {lq}?", [D("transcript", "Revlimid"), K("us_generics", L)], ["us_generics"], "PH06", "text"),
    ]
