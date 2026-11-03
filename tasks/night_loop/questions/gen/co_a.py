"""KEC, BAJFINANCE, HINDALCO: sector (library EP/NB/MN) and company questions."""
from common import A, Co, D, F, G, K, N, P, R, many, q

Q4 = ["Q3FY26", "Q4FY26", "Q1FY27", "Q2FY27"]

KEC = Co("KEC", "KEC International", "KEC", "532714", "epc_capital_goods", "ind", Q4, "Q1 FY27",
         promoter="RPG Group entities",
         rating_note="What rating did KEC International's bank facilities carry in the December 2025 rating filing?")


def kec():
    c, L = KEC, "Q2FY27"
    return [
        q("orders", 1, "What was KEC International's order book at the end of {lq}, and how much more was L1 (lowest bidder, not yet signed)?", [K("order_book", L), K("order_book_l1", L), D("deck", "L1", period=L)], ["order_book", "l1_position"], "EP01"),
        q("orders", 1, "What order intake did KEC International report for {ytd}, and what share came from T&D?", [K("order_intake", "H1FY27"), K("order_intake_mix_pct", "H1FY27")], ["order_inflow", "segment_order_mix"], "EP02"),
        q("orders", 2, "What is KEC International's order book to trailing revenue (years of visibility) at the end of {lq}?", [K("order_book", L), *many(F, "revenue_from_operations", Q4)], ["order_book_to_revenue"], "EP03", "computed"),
        q("orders", 2, "How is KEC International's order book split across T&D, Civil, Transportation, Oil & Gas, Renewables and Cables at the end of {lq}, and how did that move from Q4 FY26?", [K("order_book_mix_pct", L), K("order_book_mix_pct", "Q4FY26")], ["segment_order_mix"], "EP04", "comparison"),
        q("orders", 1, "What share of KEC International's order book is international, and which regions lead?", [K("order_book_international_share", L), D("deck", "international")], ["international_share"], "EP04"),
        q("orders", 1, "What tender pipeline does KEC International state in its {lq} presentation, and what share is T&D?", [D("deck", "Tender Pipeline", period=L)], ["tender_pipeline"], "EP09"),
        q("orders", 1, "What are KEC International's largest new orders announced since November 2025, in which businesses, and what size were they?", [D("announcement", "new orders")], ["order_inflow"], "EP10", "list"),
        q("orders", 2, "How many new-order press releases did KEC International file in {lq}, and does their sum agree with the order intake it reported for the quarter?", [D("announcement", "new orders", period=L), K("order_intake", L)], ["order_inflow"], "EP10", "comparison"),
        q("orders", 2, "What order intake did KEC International book in Civil against earlier quarters, and why has that business been slow?", [K("order_intake", L), D("deck", "Civil")], ["order_inflow", "project_delays"], "EP02", "comparison"),
        q("orders", 3, "What would the government's transmission and railway capex plans for the coming year mean for KEC International's order intake and the T&D tender pipeline?", [D("transcript", "transmission"), D("deck", "Tender Pipeline")], ["tender_pipeline", "order_inflow"], "EP12", "text"),
        q("segments", 1, "What revenue did KEC International's T&D business report in {lq}, and how is it split between India and international?", [K("revenue", L), D("deck", "T&D", period=L)], ["segment_revenue"], "EP02"),
        q("segments", 2, "How did KEC International's Civil and Transportation revenue move across the last four quarters, and what caused the slowdown?", [*many(K, "segment_revenue", Q4), D("deck", "Civil")], ["segment_revenue", "execution_rate"], "EP05", "number_series"),
        q("segments", 2, "What is the status of KEC International's SAE Towers (Brazil, Mexico) business: revenue, margin and order book?", [D("deck", "SAE"), D("transcript", "SAE")], ["segment_revenue"], why="named overseas subsidiary an investor tracks", kind="text"),
        q("segments", 1, "What does KEC International's Cables & Conductors business earn, and how much is sold in-house?", [D("deck", "Cables"), D("transcript", "Cables")], ["segment_revenue"], why="the business it reports separately", kind="text"),
        q("segments", 2, "Which projects or regions did KEC International say were delayed in {lq}, and by what (Middle East disruption, right of way, land)?", [D("deck", "disruptions", period=L), D("press_release", "Middle East")], ["project_delays", "execution_rate"], "EP05", "list"),
        q("segments", 3, "How would further Middle East disruption flow into KEC International's execution, revenue and working capital next year?", [D("deck", "Middle East"), D("transcript", "Middle East")], ["execution_rate", "nwc_days"], "U47", "text"),
        q("results", 2, "How did KEC International's EBITDA margin in {lq} (5.0% in its presentation) compare with the year-ago 7.1%, and what explained the fall?", [K("ebitda_margin_pct", L), D("deck", "EBITDA Margins", period=L)], ["ebitda_margin"], "EP07", "comparison"),
        q("results", 3, "How would a rise in steel, aluminium, zinc or copper prices affect KEC International's margins, given its share of fixed-price orders?", [D("transcript", "fixed price"), D("transcript", "commodity")], ["fixed_price_share", "commodity_pass_through"], "EP11", "text"),
        q("results", 3, "How did labour shortages and wage rules feed into KEC International's execution and cost in the last two quarters?", [D("deck", "labour"), D("transcript", "labour")], ["execution_rate", "project_delays"], why="management named labour as the constraint", kind="text"),
        q("guidance", 1, "What revenue growth, EBITDA margin and order intake did KEC International guide for FY27?", [G("revenue_guidance", "FY27"), G("ebitda_margin_guidance", "FY27"), G("order_intake_guidance", "FY27")], ["revenue_guidance", "ebitda_margin_guidance", "order_intake_guidance"], "EP08"),
        q("guidance", 2, "Did KEC International hit the FY26 revenue, margin and order intake guidance it had given?", [G("revenue_guidance", "FY26"), K("revenue", "FY26"), K("order_intake", "FY26")], ["revenue_guidance", "order_inflow"], "EP08", "comparison"),
        q("guidance", 2, "After a 5.0% EBITDA margin in {lq}, what must H2 FY27 margins be for KEC International to reach its FY27 guidance?", [G("ebitda_margin_guidance", "FY27"), K("ebitda_margin_pct", "H1FY27")], ["ebitda_margin_guidance"], "EP08", "computed"),
        q("guidance", 2, "What did KEC International say about net working capital and debt targets for FY27, and how far off are the 155 days and Rs 7,793 crore at September 2026?", [D("deck", "Net Working Capital", period=L), G("nwc_days", "FY27")], ["nwc_days", "net_debt"], "U22", "comparison"),
        q("guidance", 1, "When does KEC International expect margins to return to its medium-term target, and what target has it named?", [D("transcript", "margin")], ["ebitda_margin_guidance"], "EP07", "text"),
        q("balance_sheet", 1, "What are KEC International's net working capital days and net debt including acceptances at 30 September 2026?", [K("working_capital_days", L), K("net_debt", L)], ["nwc_days", "net_debt"], "EP06"),
        q("balance_sheet", 2, "Why did KEC International's net working capital days go from 134 to 155, and what did management say would bring them down?", [K("working_capital_days", L), K("working_capital_days", "Q1FY27"), D("deck", "NWC")], ["nwc_days", "receivables"], "EP06", "comparison"),
        q("balance_sheet", 1, "How much retention money and contract assets does KEC International carry in its FY26 annual report?", [D("annual_report", "retention")], ["retention_money", "unbilled_revenue"], "EP06"),
        q("capital_allocation", 1, "How much did KEC International raise in its QIP, at what price, and how was the money used?", [D("announcement", "QIP"), D("results", "QIP")], ["net_debt"], why="named equity raise in its cash flow", kind="text"),
        q("capital_allocation", 2, "Did the QIP lower KEC International's interest cost as management said it would?", [*many(F, "finance_cost", Q4), D("deck", "interest cost")], ["finance_cost"], why="tests a management claim", kind="comparison"),
        q("capital_allocation", 3, "If interest rates fell 100 bps, how much would KEC International's finance cost fall at its present debt?", [K("net_debt", L), *many(F, "finance_cost", Q4)], ["finance_cost", "net_debt"], "U38", "computed"),
        q("governance", 1, "Who runs KEC International's T&D, Civil and SAE Towers businesses, and has any of these leaders changed since November 2025?", [D("deck", "CEO"), D("announcement", "Senior Management")], ["project_delays"], why="named business heads in the deck", kind="list"),
        q("governance", 2, "How large are KEC International's dealings with RPG Group companies, and are they at arm's length?", [D("annual_report", "RPG")], ["related_party_transactions"], "U28", "text"),
        q("valuation", 2, "How much is KEC International's market value per rupee of order book today?", [P("close"), K("order_book", L)], ["market_cap", "order_book"], why="sector measure for an EPC company", kind="computed"),
        q("valuation", 3, "If KEC International returned to a 7% EBITDA margin on trailing revenue, what would its EV to EBITDA be today?", [*many(F, "revenue_from_operations", Q4), P("close"), K("net_debt", L)], ["ev_ebitda", "ebitda_margin"], "U45", "computed"),
        q("segments", 3, "How exposed is KEC International to rupee depreciation, given its international revenue and foreign currency debt?", [D("annual_report", "foreign currency"), D("transcript", "currency")], ["international_share"], "U39", "text"),
        q("orders", 3, "What would a slowdown in Saudi and Gulf project awards do to KEC International's international order book, given its current share?", [K("order_book_international_share", L), D("transcript", "Saudi")], ["international_share", "order_inflow"], "U47", "text"),
    ]


BAJ = Co("BAJFINANCE", "Bajaj Finance", "Bajaj Finance", "500034", "nbfc", "nbfc", Q4, "Q2 FY27", promoter="Bajaj Finserv",
         rating_note="What rating does Bajaj Finance hold on its long-term debt and fixed deposits, and has S&P or any international agency rated it?")


def baj():
    c, L = BAJ, "Q2FY27"
    return [
        q("orders", 1, "What was Bajaj Finance's AUM at the end of {lq}, its YoY growth, and the split by product?", [K("aum", L), D("deck", "AUM", period=L)], ["aum", "aum_growth", "product_mix"], "NB01"),
        q("orders", 1, "How many new loans did Bajaj Finance book in {lq} and how many new customers did it add?", [K("new_loans", L), K("customers_added", L)], ["new_customers", "disbursements"], "NB02"),
        q("orders", 1, "What was Bajaj Finance's customer franchise at the end of {lq}?", [K("customer_franchise", L)], ["customer_franchise"], "NB02"),
        q("orders", 2, "How did Bajaj Finance's new loans and new customer additions move across the last four quarters?", [*many(K, "new_loans", Q4), *many(K, "customers_added", Q4)], ["disbursements", "new_customers"], "NB02", "number_series"),
        q("orders", 1, "What is the size of Bajaj Finance's gold loan book, and what share of the balance sheet is it?", [D("transcript", "Gold loan"), D("deck", "Gold")], ["product_mix"], why="fast-growing product named on the call", kind="number"),
        q("orders", 1, "What were Bajaj Finance's car loans AUM and new car loan bookings in {lq}?", [D("deck", "Car Loans", period=L)], ["product_mix", "aum"], why="new product line", kind="number"),
        q("orders", 2, "Which of Bajaj Finance's loan products grew fastest and which shrank in {lq}, and what is happening to the captive book?", [D("deck", "AUM", period=L), D("transcript", "captive")], ["product_mix"], "NB01", "list"),
        q("orders", 2, "How has Bajaj Finance's MSME book grown, and when did management say it would pick up?", [D("transcript", "MSME"), D("deck", "MSME")], ["product_mix", "aum_growth"], "NB01", "comparison"),
        q("orders", 3, "How would slower consumer demand after GST changes affect Bajaj Finance's new consumer loan bookings?", [D("transcript", "GST"), K("new_loans", L)], ["disbursements"], "U41", "text"),
        q("orders", 3, "What would an RBI risk-weight change on consumer or NBFC loans do to Bajaj Finance's AUM growth and capital?", [D("transcript", "risk weight"), K("crar_pct", L)], ["car", "aum_growth"], "NB12", "text"),
        q("segments", 1, "What is Bajaj Housing Finance's AUM and PAT in {lq}, and what share of Bajaj Finance's consolidated AUM is it?", [D("deck", "Bajaj Housing", period=L), K("aum", L, "consolidated")], ["aum"], why="listed subsidiary", kind="number"),
        q("segments", 2, "How much of Bajaj Finance's consolidated PAT comes from Bajaj Housing and Bajaj Financial Securities?", [D("deck", "Bajaj Housing"), F("pat", L)], ["pat", "aum"], why="entity split of group profit", kind="computed"),
        q("segments", 1, "What is the split of Bajaj Finance's AUM between urban, rural, SME and mortgage in {lq}?", [D("deck", "Urban", period=L)], ["product_mix"], "NB01", "list"),
        q("segments", 1, "How is Bajaj Finance's borrowing split between banks, debt market, fixed deposits and others?", [D("deck", "borrowing"), K("deposits", L)], ["borrowing_mix"], "NB07", "list"),
        q("segments", 2, "How much do Bajaj Finance's fixed deposits contribute to its funding, and has that share changed through the last four quarters?", [*many(K, "deposits", Q4)], ["borrowing_mix"], "NB07", "number_series"),
        q("segments", 3, "Is the wind-down of Bajaj Finance's captive book changing its product mix enough to move yields?", [D("transcript", "captive"), K("yield", L)], ["yield", "product_mix"], "NB03", "text"),
        q("results", 2, "How have Bajaj Finance's NIM and cost of funds moved over the last four quarters?", [*many(K, "cost_of_funds_pct", Q4), *many(R, "nim_pct", Q4)], ["nim", "cost_of_funds"], "NB03", "number_series"),
        q("results", 2, "What is Bajaj Finance's opex to net total income, and is operating leverage improving?", [*many(R, "opex_to_net_total_income_pct", Q4)], ["opex_to_nti"], "NB06", "number_series"),
        q("results", 1, "What were Bajaj Finance's gross NPA, net NPA, Stage 2 share and provision coverage in {lq}?", [K("gnpa_pct", L), K("nnpa_pct", L), K("provision_coverage_pct", L), D("deck", "Stage 2")], ["gnpa", "nnpa", "stage2", "pcr"], "NB04"),
        q("results", 2, "What is Bajaj Finance's credit cost trend over the last four quarters, and which products drove it?", [*many(K, "credit_cost_bps", Q4), *many(K, "loan_loss_provisions", Q4), D("transcript", "credit cost")], ["credit_cost"], "NB05", "number_series"),
        q("results", 1, "What are Bajaj Finance's reported RoA and RoE for {lq}?", [K("roa_pct", L), K("roe_pct", L)], ["roa", "roe"], "NB10"),
        q("guidance", 1, "What AUM growth, credit cost, NIM and RoA did Bajaj Finance guide for FY27?", [G("aum_growth", "FY27"), G("credit_cost", "FY27"), G("nim", "FY27")], ["aum_growth", "credit_cost", "nim"], "NB11"),
        q("guidance", 2, "How did Bajaj Finance's FY27 AUM growth and credit cost guidance change between its Q4 FY26, Q1 FY27 and Q2 FY27 calls?", [G("aum_growth", "FY27"), G("credit_cost", "FY27"), D("transcript", "guidance")], ["aum_growth", "credit_cost"], "NB11", "comparison"),
        q("guidance", 2, "Did Bajaj Finance reach the FY26 credit cost and AUM growth it guided a year ago?", [G("credit_cost", "FY26"), K("credit_cost_bps", "FY26"), K("aum", "FY26")], ["credit_cost", "aum_growth"], "NB11", "comparison"),
        q("guidance", 1, "What has Bajaj Finance said about its FINAI programme: people, spend, and the savings it expects?", [D("transcript", "FINAI")], ["opex_to_nti"], why="company programme named on calls", kind="text"),
        q("guidance", 3, "If the RBI cut the repo rate again, how quickly would Bajaj Finance's cost of funds fall, and how much of that would it pass on?", [D("transcript", "repo"), K("cost_of_funds_pct", L)], ["cost_of_funds", "nim"], "NB12", "text"),
        q("balance_sheet", 1, "What are Bajaj Finance's capital adequacy and Tier 1 ratios at the end of {lq}?", [K("crar_pct", L), K("tier1_pct", L)], ["car", "tier1"], "NB09"),
        q("balance_sheet", 2, "At its present AUM growth and profit, when would Bajaj Finance's capital adequacy fall to a level needing fresh capital?", [K("crar_pct", L), K("aum", L), F("pat", L)], ["car", "aum_growth"], "NB09", "computed"),
        q("balance_sheet", 1, "What liquidity buffer does Bajaj Finance hold at the end of {lq}?", [D("deck", "liquidity", period=L)], ["liquidity_buffer"], "NB07"),
        q("balance_sheet", 2, "Does Bajaj Finance have a structural mismatch in its short ALM buckets, from the FY26 annual report?", [D("annual_report", "maturity")], ["alm_gap"], "NB08", "text"),
        q("balance_sheet", 1, "What is Bajaj Finance's gross debt, and how much did Stage 2 and Stage 3 assets rise in {lq}?", [K("gross_debt", L), D("transcript", "Stage 3", period=L)], ["stage2", "stage3"], "NB04"),
        q("balance_sheet", 3, "How would higher bank lending rates to NBFCs flow into Bajaj Finance's margins, given its bank share in borrowings?", [D("deck", "borrowing"), D("transcript", "cost of funds")], ["borrowing_mix", "cost_of_funds", "nim"], "NB12", "text"),
        q("capital_allocation", 1, "What is the status of Bajaj Finance's and Bajaj Finserv's stake purchase in the Allianz insurance ventures?", [D("announcement", "Allianz"), D("annual_report", "Allianz")], ["related_party_transactions"], why="named group transaction in its notes", kind="text"),
        q("capital_allocation", 3, "If Bajaj Housing Finance's stake must fall to meet the minimum public shareholding rule, what would a sale do to Bajaj Finance's capital and profit?", [D("transcript", "Bajaj Housing"), D("annual_report", "Bajaj Housing")], ["car", "aum"], why="listing rule with a known deadline", kind="text"),
        q("capital_allocation", 3, "If microfinance or rural unsecured stress rises, how much of Bajaj Finance's book is exposed?", [D("deck", "Rural"), D("transcript", "rural")], ["product_mix", "credit_cost"], "NB05", "text"),
        q("governance", 1, "What is Rajeev Jain's role at Bajaj Finance today, and who has taken over day-to-day leadership?", [D("announcement", "Rajeev Jain"), D("transcript", "Rajeev Jain")], ["roa"], why="leadership change named in filings", kind="text"),
        q("governance", 2, "What does Bajaj Finance disclose on the RBI's earlier action on its lending products and its compliance since?", [D("annual_report", "Reserve Bank"), D("transcript", "regulatory")], ["credit_cost"], "U48", "text"),
        q("valuation", 1, "What is Bajaj Finance's book value per share at the end of {lq}, and its price to book today?", [R("book_value_per_share", L), P("close")], ["book_value_per_share", "p_bv"], "NB10", "computed"),
        q("valuation", 2, "How does Bajaj Finance's price to book compare with its RoE, against a year ago?", [P("close"), R("roe", "FY26"), R("book_value_per_share", L)], ["p_bv", "roe"], "U33", "computed"),
        q("valuation", 3, "What AUM growth and RoA must Bajaj Finance sustain to justify today's price to book?", [P("close"), R("book_value_per_share", L), K("roa_pct", L)], ["p_bv", "roa", "aum_growth"], "U45", "computed"),
        q("valuation", 2, "How has Bajaj Finance's trailing PE moved around each of its last 4 results dates?", [P("close"), *many(F, "pat", Q4)], ["pe"], "U33", "number_series"),
    ]


HIN = Co("HINDALCO", "Hindalco Industries", "Hindalco", "500440", "metals_nonferrous", "ind", ["Q3FY26", "Q4FY26", "Q1FY27"], "Q1 FY27",
         promoter="Aditya Birla Group entities", ytd="Q1FY27",
         rating_note="What domestic and international ratings do Hindalco and its subsidiary Novelis hold?")


def hin():
    c, L, Qs = HIN, "Q1FY27", HIN.quarters
    return [
        q("orders", 1, "What aluminium upstream, downstream and copper shipments did Hindalco report for {lq}?", [K("shipments_kt", L), K("copper_cathode_volume_kt", L)], ["shipments", "rolling_shipments"], "MN01"),
        q("orders", 1, "What share of Novelis's shipments in {lq} went to beverage can, automotive, aerospace and specialties?", [D("deck", "beverage", period=L)], ["beverage_can_share", "rolling_shipments"], "MN05", "list"),
        q("orders", 1, "What is the status of Novelis's Bay Minette plant: capacity, cost, completion date?", [D("transcript", "Bay Minette")], ["capacity_expansion"], "MN07", "text"),
        q("orders", 2, "How have Novelis's shipments moved over the last three reported quarters, and how much did the Oswego fires cut them?", [*many(K, "shipments_kt", Qs), D("transcript", "Oswego")], ["rolling_shipments"], "MN05", "number_series"),
        q("orders", 1, "What aluminium metal and alumina production did Hindalco report for {lq}?", [K("production_kt", L)], ["aluminium_production"], "MN01"),
        q("orders", 1, "What copper cathode and rod volumes did Hindalco report for {lq}?", [K("copper_cathode_volume_kt", L), K("copper_rods_volume_kt", L)], ["copper_production"], "MN01"),
        q("orders", 2, "How much of Hindalco's downstream capacity additions (extrusions at Silvassa, battery foil, BESS enclosures) are running, and when will the rest be?", [D("deck", "Silvassa"), D("transcript", "downstream")], ["capacity_expansion"], "MN07", "text"),
        q("orders", 2, "How did Hindalco's India downstream aluminium volumes and EBITDA per tonne move over the last three reported quarters?", [*many(K, "ebitda_per_tonne", Qs), *many(K, "shipments_kt", Qs)], ["downstream_ebitda", "ebitda_per_tonne"], "MN05", "number_series"),
        q("orders", 3, "How would slower US auto or can demand change Novelis's shipments and EBITDA per tonne, given its product mix?", [D("transcript", "automotive"), K("ebitda_per_tonne", L)], ["novelis_ebitda_per_tonne", "rolling_shipments"], "MN08", "text"),
        q("orders", 3, "What would the Section 232 tariff on aluminium imports do to Novelis's costs, net of what it recovers from customers?", [D("transcript", "tariff")], ["tariff_impact", "novelis_ebitda_per_tonne"], "MN08", "text"),
        q("segments", 1, "What was Hindalco's EBITDA by business (Novelis, Aluminium Upstream, Aluminium Downstream, Copper) in {lq}?", [K("ebitda", L), D("deck", "Upstream", period=L)], ["upstream_ebitda", "downstream_ebitda"], "MN06", "list"),
        q("segments", 2, "How much of Hindalco's EBITDA comes from India against overseas (Novelis), and how did that shift over the last three reported quarters?", [*many(K, "ebitda", Qs), K("ebitda_adjusted_usd", L)], ["upstream_ebitda", "novelis_ebitda_per_tonne"], "MN06", "computed"),
        q("segments", 1, "What was Novelis's adjusted EBITDA per tonne in {lq}, and how much insurance money was in it?", [K("ebitda_per_tonne", L), D("transcript", "insurance proceeds")], ["novelis_ebitda_per_tonne"], "MN05"),
        q("segments", 1, "What was Hindalco's copper business EBITDA in {lq}, and how much came from by-products and treatment charges?", [K("ebitda", L), D("transcript", "copper")], ["copper_production"], "MN01"),
        q("segments", 2, "How has Hindalco's upstream aluminium EBITDA per tonne moved, and how did LME and cost of production drive it?", [*many(K, "ebitda_per_tonne", Qs), D("deck", "cost of production")], ["ebitda_per_tonne", "lme_price", "cost_of_production"], "MN02", "number_series"),
        q("segments", 2, "What did the AluChem acquisition cost Hindalco, and what does it add to its specialty alumina business?", [D("transcript", "AluChem"), D("announcement", "AluChem")], ["capacity_expansion"], why="named acquisition", kind="text"),
        q("results", 2, "How did Hindalco's cost of production change quarter on quarter, and what did management expect next quarter for alumina, coal and power?", [K("cost_of_production", L), D("transcript", "cost of production")], ["cost_of_production", "alumina_cost", "coal_cost", "power_cost"], "MN03", "comparison"),
        q("results", 3, "How would a 10% move in LME aluminium change Hindalco's EBITDA, given its hedges?", [D("transcript", "hedg"), K("ebitda", L)], ["lme_price", "hedging_pct"], "MN08", "computed"),
        q("results", 3, "How would coal and power price moves reach Hindalco's aluminium margin, given its captive power and coal mines?", [D("transcript", "coal"), D("annual_report", "captive")], ["coal_cost", "captive_power_share"], "MN03", "text"),
        q("guidance", 1, "What share of Hindalco's aluminium volume is hedged for the rest of FY27, and at what price?", [D("transcript", "hedging position")], ["hedging_pct", "hedged_price"], "MN04"),
        q("guidance", 2, "What is Hindalco's hedge price against spot LME, and how much profit is locked in or given up?", [D("transcript", "hedging position"), D("deck", "hedge")], ["hedged_price", "lme_price"], "MN04", "computed"),
        q("guidance", 1, "What EBITDA per tonne and cost guidance has Hindalco given for Novelis for the next year?", [G("novelis_ebitda_per_tonne", "FY27"), D("transcript", "Novelis")], ["novelis_ebitda_per_tonne"], "U21"),
        q("guidance", 2, "Did Hindalco's Novelis Oswego recovery run on the timeline it guided, and how much cost and insurance has it booked?", [D("transcript", "Oswego")], ["novelis_ebitda_per_tonne"], "U22", "text"),
        q("guidance", 1, "What did Hindalco say about upstream cost of production for the coming quarter, in rupee or dollar terms?", [D("transcript", "cost of production", period=L)], ["cost_of_production"], "MN03", "text"),
        q("balance_sheet", 1, "What was Hindalco's consolidated net debt to EBITDA at the latest quarter?", [K("net_debt_to_ebitda", L)], ["net_debt_to_ebitda"], "U13"),
        q("balance_sheet", 2, "How did the capex overrun at Novelis's Bay Minette and the Oswego fires change Novelis's net leverage, and what target did it give?", [D("transcript", "net leverage"), K("net_debt_to_ebitda", L)], ["net_debt_to_ebitda", "capacity_expansion"], "U13", "text"),
        q("capital_allocation", 1, "What capex has Hindalco committed for its smelter, refinery, Aditya expansion and copper projects, and when will they run?", [D("deck", "capex"), D("transcript", "capex"), K("capex", "FY26")], ["capex", "capacity_expansion"], "MN07", "list"),
        q("capital_allocation", 2, "Are Hindalco's project timelines holding, and which ones moved since the last call?", [D("transcript", "timeline"), D("deck", "project")], ["capacity_expansion"], "MN07", "comparison"),
        q("capital_allocation", 3, "If LME aluminium fell by a fifth, could Hindalco still fund its committed capex within its 2x net debt to EBITDA limit?", [K("net_debt_to_ebitda", L), K("capex", "FY26"), K("ebitda", L)], ["net_debt_to_ebitda", "capex", "lme_price"], "MN08", "computed"),
        q("capital_allocation", 3, "What would the EU's CBAM do to Hindalco's European exports and Novelis's low-carbon recycled metal?", [D("transcript", "CBAM")], ["tariff_impact"], "U41", "text"),
        q("governance", 1, "How large are Hindalco's transactions with Aditya Birla Group companies in FY26?", [D("annual_report", "related part")], ["related_party_transactions"], "U28", "text"),
        q("governance", 2, "What did the auditors and the board say on the Oswego fires, insurance recovery and how they were treated in results?", [D("results", "Oswego"), D("annual_report", "Oswego")], ["exceptional_items"], why="largest one-off in its accounts", kind="text"),
        q("valuation", 2, "What is Hindalco's EV per tonne of upstream capacity today?", [V_close(), K("net_debt", L), K("capacity", "FY26")], ["ev_ebitda", "aluminium_production"], why="asset measure a metals investor uses", kind="computed"),
        q("valuation", 2, "What does Hindalco's market cap imply about India businesses once Novelis is valued at its own multiple?", [V_close(), K("ebitda", L), K("ebitda_adjusted_usd", L)], ["market_cap", "novelis_ebitda_per_tonne"], why="sum-of-parts view", kind="computed"),
        q("valuation", 3, "At what LME price does Hindalco's EV to EBITDA today look stretched, from its own past sensitivity?", [D("transcript", "LME"), V_close()], ["ev_ebitda", "lme_price"], "U45", "computed"),
    ]


def V_close():
    return P("close")
