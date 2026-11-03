"""MARUTI, HINDUNILVR, ETERNAL: sector (library AO/FM/CI) and company questions."""
from common import A, Co, D, F, G, K, N, P, R, many, q

Q4 = ["Q3FY26", "Q4FY26", "Q1FY27", "Q2FY27"]

MAR = Co("MARUTI", "Maruti Suzuki", "Maruti", "532500", "auto_oem", "ind", Q4, "Q2 FY27", promoter="Suzuki Motor Corporation",
         rating_note="What rating did Maruti Suzuki disclose in the November 2025 credit rating filing, and on what instruments?")


def maruti():
    L = "Q2FY27"
    return [
        q("orders", 1, "What were Maruti Suzuki's total, domestic and export sales volumes in {lq} and in {ytd}?", [K("volumes", L), K("domestic_volumes", L), K("export_volumes", L), K("volumes", "H1FY27")], ["volumes", "domestic_volumes", "export_volumes"], "AO01"),
        q("orders", 1, "What were Maruti Suzuki's total sales in October 2026, domestic and export?", [D("announcement", "sales", period=None)], ["volumes"], "AO01"),
        q("orders", 2, "How did Maruti Suzuki's export volumes move in {lq} (108,119 units, down 2.1%), and why did they fall when the domestic market surged?", [K("export_volumes", L), D("transcript", "export")], ["export_volumes"], "AO01", "comparison"),
        q("orders", 2, "How did Maruti Suzuki's small cars, utility vehicles and vans move in {lq}, and how much of domestic growth was each?", [D("press_release", "small car"), D("deck", "Sales Volumes", period=L)], ["product_mix", "domestic_volumes"], "AO01", "comparison"),
        q("orders", 1, "What is Maruti Suzuki's pending booking count, and how long is the wait?", [D("transcript", "pending"), K("order_backlog", L)], ["order_backlog"], why="sector metric; management said sales are limited by capacity", kind="number"),
        q("orders", 1, "What are Maruti Suzuki's dealer inventory days at the end of {lq}?", [K("dealer_inventory_days", L), D("transcript", "inventory")], ["dealer_inventory_days"], "AO05"),
        q("orders", 2, "How have Maruti Suzuki's discounts per vehicle moved over the last four quarters?", [*many(K, "discounts", Q4), D("transcript", "discount")], ["discounts"], "AO05", "number_series"),
        q("orders", 1, "Which new models did Maruti Suzuki launch since November 2025 (e VITARA, Victoris), and what volumes are they doing?", [D("press_release", "e VITARA"), D("transcript", "Victoris")], ["new_launches", "ev_volumes"], "AO04", "list"),
        q("orders", 3, "How would the GST rate cut on small cars change Maruti Suzuki's mix and pricing next year as it fades from the comparison?", [D("press_release", "GST"), D("transcript", "GST")], ["product_mix", "domestic_volumes"], why="named driver of its surge", kind="text"),
        q("orders", 3, "How would a wider West Asia conflict reach Maruti Suzuki's exports to the Middle East and Africa?", [D("deck", "West Asia"), D("transcript", "Middle East")], ["export_volumes"], "U47", "text"),
        q("segments", 1, "How do Maruti Suzuki's exports split by region (Africa, Middle East, Latin America, Oceania, Europe, Japan)?", [D("press_release", "Africa"), D("transcript", "Africa")], ["export_volumes"], "U01", "list"),
        q("segments", 1, "What is Maruti Suzuki's domestic market share in {lq}, per its press release?", [K("market_share", L), D("press_release", "market share", period=L)], ["market_share"], "AO02"),
        q("segments", 2, "How has Maruti Suzuki's market share moved in passenger vehicles over the last four quarters, and what does it say by segment?", [*many(K, "market_share", Q4), D("transcript", "market share")], ["market_share"], "AO02", "number_series"),
        q("segments", 1, "What share of Maruti Suzuki's volumes are CNG and strong hybrid, and how fast is each growing?", [D("transcript", "CNG"), D("annual_report", "CNG")], ["product_mix"], "AO04", "number"),
        q("segments", 2, "How much do Maruti Suzuki's EVs sell in India and abroad, and how many countries has e VITARA reached?", [K("ev_volumes", L), D("press_release", "e VITARA")], ["ev_share", "ev_volumes"], "AO04", "number"),
        q("segments", 2, "Why do standalone and consolidated figures now match at Maruti Suzuki after the Suzuki Motor Gujarat merger, and what does it change in cost and depreciation?", [D("results", "Suzuki Motor Gujarat"), D("annual_report", "Suzuki Motor Gujarat")], ["capacity"], why="named merger", kind="text"),
        q("segments", 3, "How would tighter CAFE rules on small cars and carbon credits affect Maruti Suzuki's product plans?", [D("transcript", "CAFE"), D("annual_report", "CAFE")], ["product_mix", "ev_share"], "AO04", "text"),
        q("results", 1, "What were Maruti Suzuki's net sales, operating EBITDA and operating EBIT in {lq} in its presentation?", [K("revenue", L), K("ebitda", L), D("deck", "Op. EBITDA", period=L)], ["revenue", "ebitda"], "U04"),
        q("results", 2, "What did Maruti Suzuki's realisation per vehicle do in the last four quarters, given net sales and volumes?", [*many(K, "revenue", Q4), *many(K, "volumes", Q4)], ["realisation_per_vehicle"], "AO03", "computed"),
        q("results", 2, "Which factors did Maruti Suzuki list as moving its margin in {lq}: commodity, foreign exchange, Kharkhoda costs, mix, cost reduction?", [D("deck", "Key reasons for margin movement", period=L)], ["raw_material_cost", "commodity_basket"], "AO03", "list"),
        q("results", 2, "How much did material cost as a share of net sales rise at Maruti Suzuki, from 75.7% a year ago to 79.9%, and what caused it?", [D("deck", "Material Cost", period=L), F("cost_of_materials", L)], ["raw_material_cost"], "AO03", "comparison"),
        q("results", 2, "How much did Maruti Suzuki's rare earth supply issue and new labour code provision cost it, and in which quarter?", [D("deck", "Rare Earth"), D("deck", "Labour Codes")], ["exceptional_items", "raw_material_cost"], why="named one-offs", kind="number"),
        q("results", 3, "How would a further 5% rise in steel, precious metal or copper cost reach Maruti Suzuki's margin, given its past pass-through?", [D("transcript", "commodity"), R("ebit_margin_pct", L)], ["commodity_basket", "raw_material_cost"], "U40", "text"),
        q("results", 3, "How would a further fall of the rupee against the yen change Maruti Suzuki's royalty and import costs?", [D("transcript", "exchange"), D("deck", "foreign exchange")], ["raw_material_cost"], "U39", "text"),
        q("guidance", 1, "What sales volume, market share and export targets has Maruti Suzuki set for FY27 on the {call} call?", [G("volumes", "FY27"), D("transcript", "expect", period=L)], ["volumes", "export_volumes"], "U21"),
        q("guidance", 2, "Has Maruti Suzuki hit its FY26 and FY27 export targets so far?", [G("export_volumes", "FY27"), K("export_volumes", "H1FY27")], ["export_volumes"], "U22", "comparison"),
        q("guidance", 2, "When does Maruti Suzuki say capacity will catch up with demand, and how much more will Kharkhoda add, by when?", [D("transcript", "capacity"), D("press_release", "capacity")], ["capacity", "utilisation"], "U18", "text"),
        q("guidance", 1, "What did Maruti Suzuki say about long-term volume and EV plans, including the 2030-31 targets?", [D("annual_report", "2030"), D("transcript", "2030")], ["volumes", "ev_share"], "U21", "text"),
        q("balance_sheet", 1, "What cash and investments does Maruti Suzuki hold, and what is its debt, at 30 September 2026?", [D("results", "investments", period=L), A("cash_and_equivalents", "FY26")], ["net_debt"], "U13"),
        q("capital_allocation", 1, "What has Maruti Suzuki announced about capex and capacity at Kharkhoda, Gujarat and any new plant, and what is the FY27 capex?", [D("transcript", "capex"), D("annual_report", "Kharkhoda"), K("capex", "FY26")], ["capex", "capacity"], "U18", "list"),
        q("capital_allocation", 2, "How high is Maruti Suzuki's dividend of Rs 140 against its past payout, and does the company have a stated policy?", [D("press_release", "dividend"), R("dividend_payout_pct", "FY26")], ["payout_ratio", "dividend_per_share"], "U19", "comparison"),
        q("capital_allocation", 3, "If demand slows just as new capacity comes on, how would Maruti Suzuki's utilisation and depreciation burden hit margins?", [D("transcript", "utilisation"), F("depreciation", L)], ["utilisation", "capacity"], "U43", "text"),
        q("governance", 1, "How much royalty does Maruti Suzuki pay Suzuki Motor Corporation, against net sales, in FY26?", [D("annual_report", "royalty")], ["related_party_transactions"], "U28"),
        q("governance", 2, "How much does Maruti Suzuki buy from Suzuki-group or related suppliers, and has minority shareholder voting ever changed that?", [D("annual_report", "related party"), D("announcement", "related party")], ["related_party_transactions"], "U28", "text"),
        q("valuation", 2, "What market value does Maruti Suzuki have per unit of annualised sales volume today?", [P("close"), K("volumes", L)], ["market_cap", "volumes"], why="sector asset measure", kind="computed"),
        q("valuation", 2, "How much of Maruti Suzuki's market cap is its cash and investments today?", [P("close"), A("cash_and_equivalents", "FY26"), A("investments", "FY26")], ["market_cap"], why="cash-rich company", kind="computed"),
    ]


HUL = Co("HINDUNILVR", "Hindustan Unilever", "HUL", "500696", "fmcg", "ind", Q4, "Q1 FY27", promoter="Unilever PLC and group entities",
         rating_note="What rating does Hindustan Unilever disclose in its annual report, given it has no real debt?")


def hul():
    L = "Q2FY27"
    return [
        q("orders", 1, "What were Hindustan Unilever's underlying sales growth (USG) and underlying volume growth (UVG) in {lq}?", [K("underlying_volume_growth", L), K("value_growth", L), D("press_release", "Underlying Volume Growth")], ["underlying_volume_growth", "value_growth"], "FM01"),
        q("orders", 2, "How have Hindustan Unilever's USG, UVG and implied price growth moved across the last four quarters?", [*many(K, "underlying_volume_growth", Q4), *many(K, "value_growth", Q4), *many(K, "price_growth", Q4)], ["underlying_volume_growth", "value_growth", "price_growth"], "FM01", "number_series"),
        q("orders", 1, "What share of Hindustan Unilever's turnover has the #1 market position, and in what categories?", [D("deck", "market position")], ["market_share", "category_mix"], "U01", "number"),
        q("orders", 1, "What new launches did Hindustan Unilever make since November 2025 (Horlicks protein, Dove, Vaseline, Liquids)?", [D("deck", "Horlicks"), D("press_release", "Horlicks")], ["new_launches"], "FM05", "list"),
        q("orders", 2, "How much has the laundry liquids category grown for Hindustan Unilever, and what penetration does it state?", [D("deck", "Laundry liquids"), D("transcript", "Liquids")], ["category_mix", "premiumisation"], why="its stated market-making case", kind="number"),
        q("orders", 1, "What share of Hindustan Unilever's sales comes through quick commerce, e-commerce and modern trade?", [K("quick_commerce_share", L), K("ecommerce_share", L), K("modern_trade_share", L), D("transcript", "quick commerce")], ["quick_commerce_share", "ecommerce_share", "modern_trade_share"], "FM05"),
        q("orders", 2, "How has Hindustan Unilever's direct reach and distribution moved, and what did it say about general trade?", [K("direct_reach", "FY26"), D("press_release", "GT"), D("annual_report", "distribution")], ["distribution_reach", "direct_reach"], "FM05", "number"),
        q("orders", 2, "How did rural and urban demand differ for Hindustan Unilever in the last two quarters, per management?", [D("transcript", "rural"), D("deck", "Rural")], ["rural_urban_mix"], "FM02", "text"),
        q("orders", 3, "How would a weak monsoon reach Hindustan Unilever's rural volumes, given its rural share?", [D("transcript", "monsoon"), D("annual_report", "rural")], ["rural_urban_mix", "volume_growth"], "FM06", "text"),
        q("orders", 3, "How long will the GST rate cuts from 18% to 5% lift Hindustan Unilever's volumes, and what happens to pricing when the effect passes?", [D("transcript", "GST")], ["value_growth", "price_growth"], "FM06", "text"),
        q("segments", 1, "What were Hindustan Unilever's revenue and margin in Home Care, Beauty & Wellbeing, Personal Care and Foods in {lq}?", [K("segment_revenue", L), K("segment_ebit", L), D("deck", "Home Care", period=L)], ["segment_revenue", "segment_ebit"], "U01", "list"),
        q("segments", 2, "How did each Hindustan Unilever segment's USG and UVG look in {lq}, and which led?", [D("deck", "USG", period=L), D("press_release", "Home Care")], ["category_mix", "underlying_volume_growth"], "FM02", "comparison"),
        q("segments", 1, "What is the state of Hindustan Unilever's Foods business (tea, Horlicks, Kissan, Knorr) in {lq}?", [D("deck", "Foods", period=L)], ["category_mix"], "FM02", "text"),
        q("segments", 2, "How are Hindustan Unilever's acquired brands Minimalist and OZiva doing, against what was said when they were bought?", [D("press_release", "OZiva"), D("transcript", "Minimalist")], ["category_mix"], why="named acquisitions", kind="text"),
        q("segments", 1, "What is the effect of the Kwality Wall's ice cream demerger on Hindustan Unilever's reported figures, and how does it report them now?", [D("deck", "Ice Cream"), D("results", "Kwality"), D("annual_report", "Ice Cream")], ["revenue"], why="named demerger", kind="text"),
        q("segments", 3, "How would moves in palm oil and crude derivatives reach Hindustan Unilever's Home Care and Personal Care margins?", [D("transcript", "palm"), D("deck", "commodity")], ["palm_oil", "crude_derivatives", "input_cost"], "FM03", "text"),
        q("results", 1, "What was Hindustan Unilever's gross margin in {lq}, and what were its advertising and promotion spends as a share of sales?", [K("gross_margin", L), K("a_and_p_spend", L), D("deck", "Margin", period=L)], ["gross_margin", "a_and_p_spend"], "FM04"),
        q("results", 2, "How did Hindustan Unilever's EBITDA margin (22.6% in {lq}) move over the last four quarters against its guided range?", [*many(K, "ebitda_margin_pct", Q4), G("ebitda_margin_guidance", "FY27")], ["ebitda_margin"], "FM03", "number_series"),
        q("results", 2, "How did input costs move Hindustan Unilever's gross margin in the last four quarters, and did it raise prices to cover them?", [*many(K, "gross_margin", Q4), D("transcript", "commodit"), D("transcript", "pricing")], ["gross_margin", "input_cost", "price_growth"], "FM03", "comparison"),
        q("results", 2, "How has Hindustan Unilever's advertising and promotion spend moved as a share of sales over the last four quarters?", [*many(K, "a_and_p_spend", Q4), D("deck", "A&P")], ["a_and_p_spend"], "FM04", "number_series"),
        q("results", 3, "How would elevated commodity prices from the geopolitical situation hit Hindustan Unilever's H2 FY27 margin, per its outlook?", [D("deck", "Mid-term outlook"), D("transcript", "commodity")], ["input_cost", "gross_margin"], "FM03", "text"),
        q("guidance", 1, "What mid-term outlook did Hindustan Unilever state in October 2026, and what EBITDA margin range has it guided?", [D("deck", "Mid-term outlook", period=L), G("ebitda_margin_guidance", "FY27")], ["ebitda_margin", "volume_growth"], "U21"),
        q("guidance", 2, "Has Hindustan Unilever's EBITDA margin stayed inside its guided range in each quarter so far?", [G("ebitda_margin_guidance", "FY27"), *many(K, "ebitda_margin_pct", Q4)], ["ebitda_margin"], "U22", "comparison"),
        q("guidance", 2, "What did Priya Nair say she would change at Hindustan Unilever, and how much of it has shown up in UVG?", [D("transcript", "Priya"), K("underlying_volume_growth", L)], ["underlying_volume_growth"], "U22", "comparison"),
        q("guidance", 3, "With USG at 15% and UVG at 7%, how sustainable is the price-led part if input costs fall and GST base effects fade?", [K("underlying_volume_growth", L), D("transcript", "pricing")], ["price_growth", "underlying_volume_growth"], "FM01", "text"),
        q("balance_sheet", 1, "What are Hindustan Unilever's cash and lease liabilities, given it has almost no borrowings, at 30 September 2026?", [D("results", "lease", period=L), A("cash_and_equivalents", "FY26")], ["net_debt"], "U13"),
        q("capital_allocation", 1, "How much capex does Hindustan Unilever now plan as a share of turnover, and on what?", [D("deck", "capex"), K("capex", "FY26")], ["capex"], "U18"),
        q("capital_allocation", 1, "What interim and special dividends has Hindustan Unilever paid since November 2025?", [D("results", "dividend"), D("press_release", "dividend")], ["dividend_per_share"], "U19", "list"),
        q("capital_allocation", 3, "If bolt-on acquisitions take more of Hindustan Unilever's cash, what would that do to its payout and return on capital?", [D("deck", "bolt-on"), R("dividend_payout_pct", "FY26")], ["payout_ratio", "roce"], "U20", "text"),
        q("governance", 1, "How much royalty and central services fee does Hindustan Unilever pay Unilever, against turnover, in FY26?", [D("annual_report", "royalty")], ["related_party_transactions"], "U28"),
        q("governance", 2, "What tax or GST demands does Hindustan Unilever disclose, and how large are they against profit?", [D("announcement", "tax"), D("annual_report", "contingent")], ["contingent_liabilities"], "U48", "text"),
        q("valuation", 2, "How does Hindustan Unilever's PE compare with its UVG and profit growth now, against a year ago?", [P("close"), K("underlying_volume_growth", L), R("pe", L)], ["pe", "volume_growth"], "U33", "comparison"),
        q("valuation", 3, "What do investors pay today for each point of Hindustan Unilever's volume growth, and did the stock rerate after the UVG jump?", [P("close"), P("close", "2026-07-28"), K("underlying_volume_growth", L)], ["pe", "underlying_volume_growth"], "U45", "computed"),
        q("segments", 2, "How large is Hindustan Unilever's premium portfolio, and how much of the growth is premiumisation?", [D("deck", "Premium"), D("press_release", "Premium")], ["premiumisation"], "FM02", "text"),
        q("segments", 2, "How do Hindustan Unilever's segment margins for Home Care (16%), Beauty & Wellbeing (29%), Personal Care (17%) and Foods (22%) compare with the previous quarter?", [K("segment_ebit", L), K("segment_ebit", "Q1FY27")], ["segment_ebit"], "U02", "comparison"),
    ]


ETE = Co("ETERNAL", "Eternal", "Eternal", "543320", "consumer_internet", "ind", Q4, "Q2 FY27",
         rating_note="Eternal holds large cash and little debt: does it disclose any credit rating, or only ESG ratings?")


def eternal():
    L = "Q2FY27"
    return [
        q("orders", 1, "What were Eternal's net order value and growth at Blinkit in {lq}?", [K("gov", L), D("transcript", "NOV", period=L)], ["gov", "gmv"], "CI01"),
        q("orders", 1, "What was Eternal's food delivery net order value and growth in {lq}?", [D("transcript", "food delivery", period=L), K("gov", L)], ["gov"], "CI01"),
        q("orders", 2, "How did Blinkit's NOV growth and food delivery's NOV growth move across the last four quarters?", [*many(K, "gov", Q4), D("transcript", "NOV")], ["gov"], "CI01", "number_series"),
        q("orders", 1, "How many Blinkit stores were there at the end of {lq}, how many were added, and what is the target?", [K("dark_stores", L), D("transcript", "stores", period=L)], ["dark_stores"], "CI05"),
        q("orders", 1, "What are Eternal's monthly transacting customers at Blinkit and food delivery, and how fast are they growing?", [K("monthly_transacting_users", L), D("transcript", "monthly transacting")], ["monthly_transacting_users"], "CI03"),
        q("orders", 1, "What are the average order values and orders at Blinkit and food delivery?", [K("aov", L), K("orders", L)], ["aov", "orders"], "CI03"),
        q("orders", 2, "What did Eternal's filing mean by moving Blinkit to a mix of marketplace and inventory-led models, and what did it do to reported revenue?", [D("results", "inventory-led"), D("transcript", "inventory")], ["adjusted_revenue", "take_rate"], why="the main reporting change", kind="text"),
        q("orders", 2, "What share of Blinkit's sales is now inventory-led, and how far along is the shift?", [D("transcript", "inventory")], ["adjusted_revenue"], why="same shift, in numbers", kind="number"),
        q("orders", 3, "How would tougher quick-commerce competition from Amazon, Flipkart, Swiggy or Zepto reach Blinkit's store growth and contribution margin, per management?", [D("transcript", "competition")], ["contribution_margin", "dark_stores"], why="main debate on the stock", kind="text"),
        q("orders", 3, "How would a slowdown in restaurant ordering and rain or heat events reach food delivery's growth, from what Eternal has said?", [D("transcript", "food delivery")], ["gov", "order_frequency"], why="seasonal demand comment", kind="text"),
        q("segments", 1, "What revenue did Eternal report by segment (Food delivery, Quick commerce, Hyperpure, Going out) in {lq}?", [K("segment_revenue", L), D("results", "segment", period=L)], ["segment_revenue"], "CI01", "list"),
        q("segments", 2, "How did Eternal's segment revenue and segment results move across the last four quarters?", [*many(K, "segment_revenue", Q4), *many(K, "segment_ebit", Q4)], ["segment_revenue", "segment_ebit"], "CI01", "number_series"),
        q("segments", 1, "What is Blinkit's adjusted EBITDA margin as a share of NOV in {lq}?", [K("adjusted_ebitda_margin_of_gov", L), D("transcript", "Adjusted EBITDA", period=L)], ["adjusted_ebitda_margin_of_gov"], "CI02"),
        q("segments", 2, "How have Blinkit's contribution margin and adjusted EBITDA margin moved over the last four quarters, and why?", [*many(K, "contribution_margin", Q4), *many(K, "adjusted_ebitda_margin_of_gov", Q4)], ["contribution_margin", "adjusted_ebitda_margin_of_gov"], "CI02", "number_series"),
        q("segments", 2, "What is food delivery's take rate and adjusted EBITDA margin of NOV, and how is it trending?", [K("take_rate", L), D("transcript", "food delivery")], ["take_rate", "adjusted_ebitda_margin_of_gov"], "CI02", "comparison"),
        q("segments", 1, "What is the state of District (going out), its growth and its losses?", [D("transcript", "District")], ["segment_revenue"], why="named business", kind="text"),
        q("segments", 1, "What is the Hyperpure business in {lq}, and how much of it is non-Zomato restaurants?", [D("transcript", "Hyperpure"), D("results", "Hyperpure", period=L)], ["segment_revenue"], why="named business", kind="text"),
        q("segments", 2, "What is dark.ai, and how does it fit with Eternal's other businesses?", [D("transcript", "dark.ai")], ["esop_cost"], why="asked on the latest call", kind="text"),
        q("results", 1, "What was Eternal's consolidated adjusted EBITDA in {lq}, by business?", [K("ebitda", L), D("transcript", "Adjusted EBITDA", period=L)], ["ebitda"], "CI02"),
        q("results", 2, "How much do Eternal's share-based payments take from its profit, and how did they move in the last four quarters?", [*many(K, "esop_cost", Q4), D("results", "share")], ["esop_cost"], "U07", "number_series"),
        q("results", 3, "How would the Labour Codes and state gig worker laws raise Eternal's delivery cost per order?", [D("results", "Labour Codes"), D("results", "Gig Workers"), D("transcript", "gig")], ["delivery_cost_per_order"], why="named in its notes", kind="text"),
        q("results", 3, "What would an adverse GST ruling on delivery charges cost Eternal?", [D("results", "GST on delivery"), D("announcement", "GST")], ["contingent_liabilities"], why="named contingent item", kind="text"),
        q("guidance", 1, "What growth did Eternal guide for Blinkit's NOV, and what did it say about store additions on the {call} call?", [G("gov", "FY27"), D("transcript", "guiding", period=L)], ["gov", "dark_stores"], "CI06"),
        q("guidance", 2, "What long-term adjusted EBITDA margin has Eternal guided for food delivery and Blinkit, and when will Blinkit reach that?", [G("adjusted_ebitda_margin_of_gov", "FY27"), D("transcript", "steady state")], ["adjusted_ebitda_margin_of_gov"], "CI06", "text"),
        q("guidance", 2, "Has Blinkit's adjusted EBITDA break-even timeline held across the last four calls?", [D("transcript", "break-even"), D("transcript", "breakeven")], ["adjusted_ebitda_margin_of_gov"], "CI06", "comparison"),
        q("guidance", 1, "What did Eternal's management say about the quarter-to-come in its shareholder letter and call for {lq}?", [D("transcript", "shareholder letter")], ["guidance"], "U21", "text"),
        q("guidance", 3, "What must Blinkit's margin be for Eternal's consolidated profit to double from today, given its store growth?", [K("adjusted_ebitda_margin_of_gov", L), K("gov", L), F("pat", L)], ["adjusted_ebitda_margin_of_gov", "gov"], "U45", "computed"),
        q("balance_sheet", 1, "What cash balance does Eternal hold at 30 September 2026, as the company states it?", [K("cash_balance", L), D("transcript", "cash balance")], ["cash_balance"], "CI04"),
        q("balance_sheet", 2, "How has Eternal's cash balance moved over the last four quarters, and what used it (inventory, stores, QIP inflow)?", [*many(K, "cash_balance", Q4)], ["cash_balance", "cash_burn"], "CI04", "number_series"),
        q("balance_sheet", 2, "How much inventory now sits on Eternal's balance sheet from the inventory-led shift, and how many days is that?", [A("inventories", "FY26"), D("results", "Inventories", period=L)], ["inventory_days"], why="consequence of the shift", kind="computed"),
        q("capital_allocation", 1, "How much did Eternal raise in its QIP, and what does the Monitoring Agency Report say about how the money is being used?", [D("announcement", "Monitoring Agency")], ["cash_balance"], why="named filing", kind="text"),
        q("capital_allocation", 2, "How much did Eternal spend on stores and warehouses in {ytd}, against what it expects for the year?", [D("results", "purchase"), D("transcript", "capex")], ["capex", "dark_stores"], "U18", "computed"),
        q("capital_allocation", 3, "If Blinkit's store additions slowed, how quickly would Eternal's cash use reverse, given its inventory build?", [K("cash_balance", L), K("dark_stores", L), D("transcript", "stores")], ["cash_burn", "dark_stores"], "CI04", "text"),
        q("governance", 1, "Why did Deepinder Goyal step down as Eternal's CEO, what is his role now, and who runs the company?", [D("results", "Deepinder"), D("announcement", "resignation"), D("transcript", "Albinder")], ["esop_cost"], why="named succession", kind="text"),
        q("governance", 1, "What GST or tax orders did Eternal disclose since November 2025 (Uttar Pradesh, West Bengal), with amounts and its response?", [D("announcement", "order received")], ["contingent_liabilities"], "U48", "list"),
        q("governance", 2, "What stake does Deepinder Goyal hold in Eternal after stepping down as CEO, and has he sold or pledged any of it?", [D("annual_report", "Deepinder"), D("announcement", "SAST")], ["fii_holding"], why="founder's position after the CEO change", kind="text"),
        q("valuation", 2, "What is Eternal's market cap against annualised Blinkit plus food delivery NOV today?", [P("close"), K("gov", L)], ["market_cap", "gov"], why="sector measure", kind="computed"),
        q("valuation", 2, "How does Eternal's trailing PE look given its share-based payments, cash and low current profit?", [P("close"), *many(F, "pat", Q4)], ["pe", "esop_cost"], "U33", "computed"),
        q("valuation", 3, "How much of Eternal's price today can be explained by food delivery alone at a steady-state margin, leaving what for Blinkit?", [P("close"), K("gov", L), K("adjusted_ebitda_margin_of_gov", L)], ["market_cap", "adjusted_ebitda_margin_of_gov"], "U45", "computed"),
    ]
