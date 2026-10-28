"""Read-only Reddit miner: question filter, family/level/alias/time/data-hop counts.

Raw posts stay in D:\\RealityEngine\\raw\\reddit. This script writes aggregated
counts only (no post text) to tasks/reddit_mining/work/.

Usage:
    python tasks/reddit_mining/mine.py            # aggregate + write stats
    python tasks/reddit_mining/mine.py --samples  # also print up to 3 titles/pattern
"""
from __future__ import annotations

import argparse
import collections
import csv
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path

RAW = Path(os.environ.get("REDDIT_RAW_ROOT", r"D:\RealityEngine\raw\reddit"))
HERE = Path(__file__).resolve().parent
WORK = HERE / "work"
REPO = HERE.parent.parent

SKIP_EMPTY = set()  # filled from file sizes

SUBREDDIT_GROUP = {}
INDIAN = """IndianStockMarket IndiaInvestments DalalStreetTalks StockMarketIndia
IndianStreetBets NSEbets mutualfunds IndianEconomy personalfinanceindia FIREIndia
IndiaBusiness indianstocks ShareMarketIndia IndiaTax IPOIndia""".split()
INTL = """ValueInvesting SecurityAnalysis investing stocks StockMarket dividends
Economics economy Bogleheads UKInvesting CanadianInvestor ausstocks EuropeanStocks
smallcapstocks FluentInFinance""".split()
TECH = """technicalanalysis swingtrading Daytrading trading algotrading options
StockMarketChat Trading_India IndianOptionTraders chartpatterns""".split()
for s in INDIAN:
    SUBREDDIT_GROUP[s] = "indian"
for s in INTL:
    SUBREDDIT_GROUP[s] = "international"
for s in TECH:
    SUBREDDIT_GROUP[s] = "technical"

# ---------------------------------------------------------------- filters
# Personal-finance-only / broker-process signals. A post is dropped when it
# carries one of these and no market-entity / market-data signal.
PF_ONLY = re.compile(
    r"\b(itr|income tax return|tax filing|file (my|the) tax|80c|80d|deduction|"
    r"term insurance|health insurance|insurance premium|lic |policy premium|"
    r"home loan|personal loan|car loan|education loan|loan against|credit card|"
    r"cibil|credit score|ppf|nps|epf|provident fund|emergency fund|"
    r"salary|appraisal|hike|rent vs buy|kyc|demat account|broker app|"
    r"zerodha|groww|upstox|angel one|dhan app|indmoney|kuvera|coin app)\b",
    re.I,
)
MARKET = re.compile(
    r"\b(stock|stocks|share|shares|equity|market|nifty|sensex|bank ?nifty|"
    r"sector|index|ipo|listing|results|earnings|revenue|profit|pat|ebitda|"
    r"valuation|pe |p/e|eps|dividend|buyback|demerger|ofs|rights|bonus|split|"
    r"circuit|breakout|support|resistance|volume|delivery|fii|dii|promoter|"
    r"sebi|rbi|budget|tariff|policy|inflation|crude|rupee|earnings|guidance|"
    r"order book|capex|margin|debt|roe|roce|moat|balance sheet|cash flow|"
    r"mutual fund|etf|sip|portfolio|brokerage|target price|analyst)\b",
    re.I,
)
QUESTION = re.compile(
    r"\?|^\s*(why|what|how|when|where|which|who|should|is|are|can|could|will|"
    r"would|does|do|did|anyone|does anyone|has|have|worth|best|good|bad|"
    r"kaun|kyun|kya|kab|kaise|kitna|kahan|konsa|konsi|hai kya|batao|suggest|"
    r"recommend|thoughts|views|opinion|explain|help|advice|need help|"
    r"looking for|confused|doubt)\b",
    re.I,
)
MEME = re.compile(r"\b(meme|shitpost|funny|meme|rocket|to the moon|lol|lmao)\b", re.I)
PORTFOLIO_RATE = re.compile(
    r"\b(rate my portfolio|portfolio review|review my portfolio|"
    r"roast my portfolio|portfolio rating)\b", re.I
)
HINGLISH = re.compile(
    r"\b(kya|kaun|kyun|kab|kaise|kitna|kahan|konsa|konsi|hai|hoga|hogi|"
    r"kare|karna|karu|karun|chahiye|batao|bhai|yaar|acha|theek|matlab|"
    r"paisa|paise|bhav|bhaav|sahi|galat|abhi|kal|aaj|mujhe|mera|meri)\b", re.I
)

# ---------------------------------------------------------------- families
FAMILIES = {
    1: "Lookup (what did the entity say/report)",
    2: "Number (metric for entity/period)",
    3: "Change over time",
    4: "Screen (which stocks meet condition)",
    5: "Cross-document agreement",
    6: "Policy -> companies",
    7: "Company -> policy",
    8: "Peers",
    9: "Event window",
    10: "Opinion vs truth",
    11: "Point in time",
    12: "When / timeline",
    13: "Inverse screen (topic -> companies)",
    14: "Governance and audit",
    15: "Market move -> why",
    16: "Input-cost / commodity transmission",
    17: "Business economics",
    18: "Forward policy impact",
    19: "Second-order / supply chain",
    20: "Out-of-scope / bizarre",
}
FAMILY_RULES = [
    (15, re.compile(r"\b(why (did|is|has|are)|what happened|reason (for|behind)|"
                    r"kyun (gira|gir|badh|up|down)|why.*(fall|drop|rise|jump|surge|crash))\b", re.I)),
    (14, re.compile(r"\b(auditor|audit|red flag|forensic|pledge|promoter (selling|sold|stake)|"
                    r"related party|corporate governance|resign|kmp|insider|bulk deal|block deal)\b", re.I)),
    (12, re.compile(r"\b(when (will|is|does|should)|by when|timeline|deadline|"
                    r"commission|go live|launch date|kab (aayega|hoga|tak))\b", re.I)),
    (13, re.compile(r"\b(which (companies|stocks|sectors)|who (benefits|supplies|buys)|"
                    r"kaun (benefit|faida)|beneficiar)\b", re.I)),
    (18, re.compile(r"\b(impact of|effect of|benefit from|due to .*(budget|tariff|policy|rbi|pli)|"
                    r"(budget|tariff|policy|pli|subsidy) .*(impact|affect|benefit))\b", re.I)),
    (16, re.compile(r"\b(crude|copper|steel|aluminium|rubber|cement|coal|natural gas|"
                    r"rupee|dollar|inr|forex|commodity|input cost|raw material)\b", re.I)),
    (19, re.compile(r"\b(supply chain|downstream|upstream|second.order|ancillar|"
                    r"vendor|supplier|contract manufacturer)\b", re.I)),
    (9, re.compile(r"\b(after (the )?(result|earnings|budget|election|rbi|fed)|"
                    r"post (result|earnings|budget)|before (result|earnings|budget)|"
                    r"event (window|day)|on (budget|election) day)\b", re.I)),
    (10, re.compile(r"\b(analyst|brokerage|target price|research report|motilal|"
                    r"kotak (securities|institutional)|antique|iifl|hdfc sec)\b", re.I)),
    (8, re.compile(r"\b(vs\.?|versus|compare|comparison|better than|peer|competitor|"
                    r"tulna|compared to)\b", re.I)),
    (5, re.compile(r"\b(concall|transcript|annual report|investor (deck|presentation)|"
                    r"deck|management said|management commentary)\b", re.I)),
    (11, re.compile(r"\b(as of|back then|at that time|point in time|then vs now)\b", re.I)),
    (3, re.compile(r"\b(growth|yoy|qoq|since|over the (years|months)|"
                    r"change(d)? (from|since)|last (year|quarter) vs|trend)\b", re.I)),
    (4, re.compile(r"\b(best (stocks|sector)|which (stock|sector)|screener|screen|"
                    r"list of stocks|top picks|multibagger|smallcap pick)\b", re.I)),
    (6, re.compile(r"\b(which (sectors|industries|companies) .*(affect|benefit|hit)|"
                    r"(budget|policy|pli|tariff).*(which|sector|industry))\b", re.I)),
    (7, re.compile(r"\b(which (policy|policies|scheme|regulation)s? (touch|affect|apply)|"
                    r"govt (scheme|policy).*(stock|company))\b", re.I)),
    (2, re.compile(r"\b(revenue|pat|ebitda|margin|eps|turnover|net profit|"
                    r"operating profit|topline|bottomline|market cap)\b", re.I)),
    (17, re.compile(r"\b(unit economics|breakeven|business model|pricing power|"
                    r"operating leverage|roce|roic|wacc|moat)\b", re.I)),
    (1, re.compile(r"\b(said|says|stated|mentioned|guidance|commentary|order book|"
                    r"management (said|says|guided))\b", re.I)),
]
EMPTY_FAMILY = re.compile(r".*")

# When no template family fits, name the gap the way the report counts it.
NEW_FAMILY_RULES = [
    ("NEW:technical_setup", re.compile(
        r"\b(support|resistance|breakout|breakdown|moving average|sma|ema|dma|"
        r"rsi|52.week|gap|open interest|pcr|max pain|delivery|circuit|"
        r"chart pattern|relative strength|volume)\b", re.I)),
    ("NEW:entry_timing", re.compile(
        r"\b(good time|right time|should i (buy|enter|add)|when to buy|"
        r"too late|buy now|enter now)\b", re.I)),
    ("NEW:position_decision", re.compile(
        r"\b(hold|sell|book profit|exit|averag|avg price|at loss|down \d+%)\b", re.I)),
    ("NEW:group_basket", re.compile(
        r"\b(adani|tata|bajaj|psu|public sector|group|basket|pack)\b", re.I)),
    ("NEW:ipo_grey_market", re.compile(
        r"\b(ipo|grey market|gmp|listing|allotment|anchor)\b", re.I)),
    ("NEW:corporate_action", re.compile(
        r"\b(demerger|buyback|ofs|rights issue|bonus|split|record date|ex.date)\b", re.I)),
    ("NEW:sebi_rule", re.compile(
        r"\b(sebi|insider|sast|lodr|circular|regulation)\b", re.I)),
    ("NEW:flows", re.compile(r"\b(fii|dii|foreign investor|block deal|bulk deal)\b", re.I)),
    ("NEW:macro_event", re.compile(
        r"\b(budget|rbi|repo|rate cut|inflation|cpi|gdp|election|tariff|gst|fed)\b", re.I)),
]

# ---------------------------------------------------------------- entity level
LEVEL_RULES = [
    ("ipo", re.compile(r"\b(ipo|listing|allotment|grey market|gmp|drhp|"
                       r"anchor investor|mainboard|sme)\b", re.I)),
    ("policy", re.compile(r"\b(sebi|rbi|budget|tariff|gst|pli|subsidy|"
                          r"regulation|circular|sast|lodr|duty|cess|tax)\b", re.I)),
    ("macro", re.compile(r"\b(inflation|cpi|wpi|gdp|fed|fomc|crude|rupee|"
                         r"yield|bond|repo rate|interest rate|recession|"
                         r"current account|fiscal deficit)\b", re.I)),
    ("index", re.compile(r"\b(nifty|sensex|bank ?nifty|midcap 100|smallcap 250|"
                         r"nifty ?50|nifty ?500|index)\b", re.I)),
    ("market-wide", re.compile(r"\b(market|breadth|fii|dii|advance decline|"
                               r"volatility|vix)\b", re.I)),
]
SECTOR_WORDS = """banking bank pharma pharma it auto auto ancillary fmcg cement steel
metal metals oil gas energy power realty real estate infra infrastructure defence
railway railways telecom media chemical chemicals textile textiles sugar hotel
airline aviation insurance amc exchange capital goods consumer durables""".split()
THEME_WORDS = """defence railway railways ev electric vehicle green hydrogen solar
renewable semiconductor data centre datacenter quick commerce qcommerce qsr
hospital tourism water amc mutual fund etf psu""".split()
SECTOR_RE = re.compile(r"\b(" + "|".join(re.escape(w) for w in SECTOR_WORDS) + r")\b", re.I)
THEME_RE = re.compile(r"\b(" + "|".join(re.escape(w) for w in THEME_WORDS) + r")\b", re.I)
TICKER_RE = re.compile(r"(?<![A-Za-z])([A-Z]{2,12})(?![A-Za-z])")

# ---------------------------------------------------------------- time phrases
TIME_PHRASES = [
    ("today", re.compile(r"\b(today|aaj|intraday)\b", re.I)),
    ("tomorrow", re.compile(r"\b(tomorrow|kal|next session)\b", re.I)),
    ("yesterday", re.compile(r"\b(yesterday|kal)\b", re.I)),
    ("this week", re.compile(r"\bthis week\b", re.I)),
    ("last week", re.compile(r"\blast week\b", re.I)),
    ("next week", re.compile(r"\bnext week\b", re.I)),
    ("this month", re.compile(r"\bthis month\b", re.I)),
    ("this quarter", re.compile(r"\b(this|current) quarter\b", re.I)),
    ("QnFYxx", re.compile(r"\bQ[1-4]\s?FY\s?\d{2}\b", re.I)),
    ("after budget", re.compile(r"\b(post|after) (the )?budget\b", re.I)),
    ("before budget", re.compile(r"\b(pre|before) (the )?budget\b", re.I)),
    ("after election", re.compile(r"\b(after|since|post) (the )?election", re.I)),
    ("after results", re.compile(r"\b(after|post) (the )?(result|earnings)", re.I)),
    ("this year", re.compile(r"\b(this|current) year\b", re.I)),
    ("last year", re.compile(r"\b(last|past) year\b", re.I)),
    ("YTD", re.compile(r"\b(ytd|year to date)\b", re.I)),
    ("52-week", re.compile(r"\b52.week\b", re.I)),
    ("expiry", re.compile(r"\b(expiry|expiration)\b", re.I)),
    ("long term", re.compile(r"\b(long.term|5 years|10 years|decade)\b", re.I)),
    ("since listing", re.compile(r"\bsince (ipo|listing)\b", re.I)),
    ("next quarter", re.compile(r"\bnext (quarter|q[1-4])\b", re.I)),
    ("since 2024", re.compile(r"\bsince 2024\b", re.I)),
    ("after rate cut", re.compile(r"\b(after|since) (the )?(rate cut|rbi decision|fed)\b", re.I)),
    ("at open", re.compile(r"\b(at|on) (market )?open\b", re.I)),
]

# ---------------------------------------------------------------- data points asked for
DATAPOINTS = [
    ("price", re.compile(r"\b(price|close|high|low|cmp|ltp|level|fall|rise|"
                         r"target|rally|correction|drawdown)\b", re.I)),
    ("volume", re.compile(r"\bvolume|turnover|traded value\b", re.I)),
    ("delivery", re.compile(r"\bdelivery\b", re.I)),
    ("oi", re.compile(r"\b(open interest|oi|pcr|max pain|rollover|futures|"
                      r"option chain|strike)\b", re.I)),
    ("flows", re.compile(r"\b(fii|dii|foreign|institutional|bulk deal|block deal|"
                         r"promoter (buy|sell|stake)|insider)\b", re.I)),
    ("results", re.compile(r"\b(result|earnings|revenue|pat|ebitda|margin|eps|"
                           r"quarterly)\b", re.I)),
    ("guidance", re.compile(r"\b(guidance|management said|commentary|outlook|"
                            r"order book|capex plan)\b", re.I)),
    ("valuation", re.compile(r"\b(pe|p/e|valuation|expensive|cheap|undervalued|"
                             r"overvalued|price to book|ev/ebitda)\b", re.I)),
    ("holding", re.compile(r"\b(promoter|pledge|shareholding|holding|fii stake|"
                           r"dii stake)\b", re.I)),
    ("policy", re.compile(r"\b(policy|sebi|rbi|budget|tariff|gst|pli|subsidy|"
                          r"regulation|duty)\b", re.I)),
    ("macro", re.compile(r"\b(inflation|cpi|gdp|crude|rupee|dollar|fed|yield|"
                         r"interest rate|recession)\b", re.I)),
    ("index", re.compile(r"\b(nifty|sensex|index|breadth)\b", re.I)),
    ("technical", re.compile(r"\b(support|resistance|breakout|breakdown|moving average|"
                             r"ema|dma|rsi|52.week|gap|circuit|chart pattern|"
                             r"relative strength)\b", re.I)),
    ("dividend", re.compile(r"\b(dividend|yield|buyback|bonus|split|record date)\b", re.I)),
    ("ipo", re.compile(r"\b(ipo|listing|gmp|allotment|anchor)\b", re.I)),
]
PAIRWISE_LIMIT = 15


def _combine(rules, prefix):
    parts, names = [], {}
    for i, (name, rx) in enumerate(rules):
        key = f"{prefix}{i}"
        parts.append(f"(?P<{key}>{rx.pattern})")
        names[key] = name
    return re.compile("|".join(parts), re.I), names


T_RX, T_NAMES = _combine(TIME_PHRASES, "t")
D_RX, D_NAMES = _combine(DATAPOINTS, "d")

# ---------------------------------------------------------------- missing patterns
# name -> (regex, entity focus, schema proposal, answerable)
MISSING_PATTERNS = [
    ("group_basket_entity", r"\b(adani|tata|bajaj|mahindra|jsw|vedanta|psu|public sector|"
     r"defence stocks|railway stocks|psu banks|group|basket|pack of)\b",
     "group/basket",
     "entity_group(group_id, name, kind, parent_isin NULL, valid_from, valid_to); "
     "entity_group_member(group_id, isin, weight, valid_from, valid_to)", "partial"),
    ("ipo_grey_listing_day", r"\b(grey market|gmp|listing gain|listing day|listing price|"
     r"allotment|ipo|mainboard|sme ipo|anchor investor)\b",
     "ipo",
     "ipo_issue(isin, issue_open, issue_close, price_band_low, price_band_high, lot, "
     "issue_size_cr, subscription_json); ipo_grey_market(isin, date, gmp_inr, source); "
     "ipo_listing(isin, listing_date, open, high, low, close, first_day_return)", "partial"),
    ("entry_timing_good_time", r"\b(good time to (buy|enter|invest)|right time|"
     r"should i (buy|enter|add|invest)|when to (buy|enter)|worth buying now|"
     r"enter now|buy now|too late to buy)\b",
     "stock",
     "valuation_asof(isin, date, pe, pb, ev_ebitda, percentile_5y); "
     "technical_state(isin, date, sma50, sma200, rsi14, pct_from_52w_high, atr)", "partial"),
    ("corporate_action_aftermath", r"\b(demerger|buyback|ofs|offer for sale|rights issue|"
     r"bonus|split|record date|ex.date|entitlement|cost of acquisition)\b",
     "stock",
     "corporate_action(isin, ex_date, record_date, kind, ratio_num, ratio_den, "
     "price_inr, size_cr, source_ref); corporate_action_effect(isin, action_id, "
     "pre_price, post_price, adjustment_factor)", "yes"),
    ("sebi_rule_question", r"\b(sebi|insider trading|sast|takeover code|lodr|"
     r"disclosure|circular|regulation)\b",
     "policy",
     "sebi_rule(rule_id, title, instrument, stage, effective_date, summary, url); "
     "sebi_rule_company(rule_id, isin, direction, materiality)", "partial"),
    ("fno_vs_cash_flow", r"\b(f&o|futures|options|rollover|expiry|premium|lot size|"
     r"cash market|delivery vs)\b",
     "stock/derivative",
     "fno_contract(isin, trade_date, expiry, strike, option_type, oi, volume, iv, "
     "settle); fno_rollover(isin, expiry_from, expiry_to, roll_pct); "
     "futures_basis(isin, date, futures_close, spot_close)", "yes"),
    ("global_cue_overnight", r"\b(us market|nasdaq|dow|s&p|fed |fomc|gift nifty|"
     r"global cues|overnight|dollar index|us 10.year|crude overnight)\b",
     "macro/market-wide",
     "global_cue(date_ist, series, value, pct_change, source); "
     "market_open_gap(index_code, date, prev_close, open, gap_pct)", "partial"),
    ("fii_dii_flow_link", r"\b(fii|dii|foreign investor|institutional flow|"
     r"fii selling|dii buying)\b",
     "market-wide/stock",
     "fii_dii_cash exists daily; missing fii_dii_stock(isin, date, fii_net_inr, "
     "dii_net_inr) and flow_attribution(isin, date, flow_inr, price_effect)", "partial"),
    ("index_inclusion_rebalance", r"\b(index inclusion|index exclusion|rebalanc|"
     r"nifty (add|remove)|index fund|etf|passive flow)\b",
     "index",
     "index_membership(index_code, isin, valid_from, valid_to); "
     "index_rebalance_event(index_code, announce_date, effective_date, "
     "add_isin, del_isin, est_flow_inr)", "partial"),
    ("circuit_band_behaviour", r"\b(upper circuit|lower circuit|circuit limit|"
     r"price band|5% band|20% band|no band)\b",
     "stock",
     "price_bands exists daily (date, symbol, series, band_pct); missing "
     "circuit_event(isin, date, direction, band_pct, open, close, volume_multiple)", "yes"),
    ("merger_arbitrage", r"\b(merger|amalgamation|scheme of arrangement|swap ratio|"
     r"open offer|delisting|nclt)\b",
     "stock",
     "deal(scheme_id, acquirer_isin, target_isin, kind, swap_ratio, open_offer_price, "
     "approval_date, expected_close, status); deal_spread(date, scheme_id, "
     "target_price, acquirer_price, spread_pct)", "partial"),
    ("dividend_record_date", r"\b(dividend|ex.dividend|record date|dividend yield|"
     r"payout)\b",
     "stock",
     "corporate_action covers ex/record dates; missing dividend_detail(isin, "
     "announce_date, ex_date, amount_per_share, type, fy)", "yes"),
    ("results_calendar", r"\b(when .*result|result date|earnings date|board meeting|"
     r"results calendar)\b",
     "stock",
     "board_meeting(isin, meeting_date, purpose, intimation_date); "
     "results_filings has actual filing dates, not the forward calendar", "partial"),
    ("guidance_vs_delivery", r"\b(guidance|promised|management said|they said|"
     r"target.*(met|missed)|overpromis)\b",
     "stock",
     "guidance_item(isin, doc_id, metric, period, value_low, value_high, unit, "
     "statement_date); guidance_delivery(guidance_id, actual_fact_id, surprise_pct)", "partial"),
    ("promoter_pledge_sale", r"\b(promoter|pledge|insider|bulk deal|block deal|"
     r"stake sale|promoter selling)\b",
     "stock",
     "shareholding exists; missing pledge_history(isin, quarter_end, pledged_pct, "
     "encumbered_pct) and deal_print(isin, date, side, qty, price, client_type)", "partial"),
    ("valuation_vs_peers", r"\b(pe ratio|p/e|valuation|overvalued|undervalued|"
     r"cheaper than|expensive|price to book|ev/ebitda)\b",
     "stock/peers",
     "valuation_asof(isin, date, mcap, pe, pb, ev_ebitda, dividend_yield); "
     "peer_set(isin, peer_isin, basis, valid_from, valid_to)", "partial"),
    ("theme_proxy_play", r"\b(best way to play|theme|thematic|proxy|"
     r"indirect play|beneficiary of)\b",
     "theme",
     "theme(theme_id, name, definition); theme_member(theme_id, isin, weight, "
     "evidence_id, valid_from, valid_to) - universe() covers 9 themes only", "partial"),
    ("mf_etf_vs_stock", r"\b(mutual fund|sip|index fund|etf|nav|expense ratio)\b",
     "fund",
     "fund_master(amfi_code, name, category, benchmark); fund_nav(amfi_code, date, "
     "nav); fund_holding(amfi_code, isin, weight, as_of); not held today", "no"),
    ("hold_or_sell_position", r"\b(hold|sell|book profit|exit|averag|avg price|"
     r"at loss|down \d+%|recover)\b",
     "stock",
     "needs a position-aware layer: position(user_id, isin, qty, avg_price, "
     "opened_at) is out of scope; answerable only generically from price/valuation", "partial"),
    ("why_stock_moved", r"\b(why (did|is|has).*(fall|rise|down|up|drop|surge)|"
     r"reason.*(fall|drop|jump)|what happened (to|with))\b",
     "stock/index",
     "move_attributor exists in processing; no served table. Needed: "
     "move_attribution(isin, date, return_pct, attributed_kind, evidence_id, "
     "known_at, confidence)", "partial"),
    ("macro_event_what_if", r"\b(budget|rbi|repo|rate cut|rate hike|inflation|cpi|"
     r"gdp|election|tariff|gst|fed)\b.*\b(if|impact|affect|what|should|benefit)\b",
     "macro/policy",
     "macro_event + ripple_effects exist; missing scenario table(scenario_id, "
     "assumption_json, asof, affected_isin, delta_revenue_pct, delta_margin_bps)", "partial"),
    ("earnings_reaction_drift", r"\b(after (result|earnings)|post result|"
     r"result reaction|gap (up|down) after)\b",
     "stock",
     "event_study(event_id, isin, t0, car_1d, car_5d, car_20d, benchmark) with "
     "known_at; price/event data held, the drift table is not", "partial"),
    ("penny_low_price_stock", r"\b(penny stock|under ₹?\d+|below \d+ rupees|"
     r"multibagger|small cap|micro cap)\b",
     "stock",
     "price + master_companies market_cap_tier cover the universe; "
     "missing liquidity_floor(isin, date, median_turnover_20d, impact_cost_bps)", "partial"),
    ("fundamental_health_check", r"\b(fundamentals|balance sheet|debt|roe|roce|"
     r"cash flow|profit|revenue|quality of earnings)\b",
     "stock",
     "annual_financials + quarterly_financials + ar_facts cover most; missing "
     "derived_quality(isin, period, roic, wacc, accrual_ratio, debt_equity, "
     "interest_coverage, formula_version)", "partial"),
    ("moat_competitive_advantage", r"\b(moat|competitive advantage|pricing power|"
     r"market share|switching cost|network effect)\b",
     "stock",
     "moat_evaluations(substrate) exists; no served per-company moat table with "
     "evidence. Needed: moat_score(isin, asof, width, trajectory, sc, ne, ca, ia, "
     "es, evidence_ids)", "partial"),
    ("capital_allocation", r"\b(capital allocation|buyback|dividend policy|"
     r"reinvestment|roic|incremental return|debt reduction)\b",
     "stock",
     "needs capital_allocation(isin, period, cfo, capex, dividends, buyback, "
     "net_debt_change, incremental_roic) plus a decision log", "partial"),
    ("accounting_red_flags", r"\b(accounting|red flag|forensic|receivable|inventory|"
     r"related party|auditor|qualified opinion|going concern)\b",
     "stock",
     "ar_facts has the notes; missing red_flag(isin, period, flag_code, severity, "
     "value, benchmark, evidence_id) with extraction provenance", "partial"),
    ("unit_economics", r"\b(unit economics|breakeven|cac|ltv|gross margin|"
     r"contribution margin|per order|per unit)\b",
     "stock",
     "deck_figures/concall_facts hold fragments; missing unit_economics(isin, "
     "period, driver, numerator, denominator, unit, evidence_id)", "partial"),
    ("cycle_peak_trough", r"\b(cycle|cyclical|peak|trough|downturn|upcycle|"
     r"commodity cycle)\b",
     "sector/stock",
     "needs cycle_state(sector_id, month, phase, spread_pct, inventory_days, "
     "capacity_utilisation) derived from prices + filings", "no"),
    ("second_order_beneficiary", r"\b(second.order|downstream|upstream|supply chain|"
     r"who benefits|beneficiary|ancillar)\b",
     "stock/sector",
     "ripple_effects(substrate DAG) exists; missing supply_link(supplier_isin, "
     "buyer_isin, share_of_cogs, valid_from, valid_to, evidence_id)", "partial"),
    ("policy_impact_by_company", r"\b(impact of|benefit from|policy|scheme|pli|"
     r"subsidy|tariff)\b.*\b(stock|sector|company|industry)\b",
     "policy/sector",
     "policy_events + ripple_effects; missing policy_exposure(policy_id, isin, "
     "channel, direction, materiality_pct, evidence_id)", "partial"),
    ("ipo_vs_listed_peer", r"\b(ipo).*(vs|compare|valuation|cheaper|expensive|"
     r"better than)\b",
     "ipo/stock",
     "needs ipo_issue + peer valuation at issue date (valuation_asof); "
     "no issue-date peer comparison table", "partial"),
    ("broker_platform_process", r"\b(zerodha|groww|upstox|angel one|dhan|indmoney|"
     r"app|platform|charges|brokerage)\b",
     "process",
     "out of scope for market data; answer from a help/FAQ corpus only", "no"),
    ("ta_support_resistance", r"\b(support|resistance|demand zone|supply zone|"
     r"retest|level)\b",
     "stock/technical",
     "px_nse/px_bse daily OHLCV + delivery held daily_price_delivery; needed "
     "technical_level(isin, date, kind, price_low, price_high, touches, method, "
     "valid_from, valid_to)", "partial"),
    ("ta_breakout_volume", r"\b(breakout|breakdown|volume spike|volume confirm|"
     r"52.week high breakout|all.time high)\b",
     "stock/technical",
     "price, volume and delivery are held; needed breakout_event(isin, date, "
     "level, close_vs_level_pct, volume_ratio_20d, delivery_ratio_20d)", "yes"),
    ("ta_moving_average", r"\b(moving average|sma|ema|dma|200.dma|50.dma|"
     r"golden cross|death cross)\b",
     "stock/technical",
     "daily_price_delivery already derives SMA; needed ma_state(isin, date, "
     "sma20, sma50, sma200, cross_kind, days_since_cross) served point-in-time", "yes"),
    ("ta_rsi_momentum", r"\b(rsi|oversold|overbought|momentum|divergence)\b",
     "stock/technical",
     "RSI14 derived today; needed indicator_state(isin, date, rsi14, rsi_zone, "
     "divergence_kind) with the exact formula/version", "yes"),
    ("ta_52week_extreme", r"\b(52.week|all.time high|all.time low|near high|"
     r"near low|breakout above)\b",
     "stock/technical",
     "daily_price_delivery has 52w high/low; needed pct_from_52w_high, "
     "days_since_52w_extreme, and index-relative version", "yes"),
    ("ta_gap_event", r"\b(gap up|gap down|gap fill|opening gap|gap)\b",
     "stock/technical",
     "needs gap_event(isin, date, prev_close, open, gap_pct, filled, fill_date)", "yes"),
    ("ta_relative_strength", r"\b(relative strength|outperform|underperform|"
     r"vs nifty|vs index|rs rating)\b",
     "stock/technical",
     "needs relative_strength(isin, benchmark, date, rs_1m, rs_3m, rs_6m, "
     "rs_12m, percentile)", "yes"),
    ("ta_oi_pcr_maxpain", r"\b(open interest|oi|pcr|max pain|option chain|"
     r"strike|futures build|short covering)\b",
     "stock/derivative",
     "no daily OI/PCR table; needed fno_oi(isin, date, expiry, strike, "
     "option_type, oi, oi_change, volume, iv); pcr_daily(index_code, date, pcr_oi, "
     "pcr_volume); max_pain(index_code, expiry, date, strike)", "no"),
    ("ta_delivery_spike", r"\b(delivery|delivery percentage|delivery spike|"
     r"high delivery)\b",
     "stock/technical",
     "delivery_qty/delivery_pct held per exchange; needed delivery_spike(isin, "
     "date, delivery_pct, zscore_60d, value_inr) and a cash-vs-F&O split", "yes"),
    ("ta_chart_pattern", r"\b(chart pattern|flag|triangle|head and shoulders|"
     r"double top|double bottom|cup and handle|wedge)\b",
     "stock/technical",
     "not stored; pattern detection would need labelled window features "
     "pattern_match(isin, date, pattern, window_start, window_end, confidence)", "no"),
    ("second_order_macro", r"\b(second.order|follow.?on|ripple|knock.on|cascad|"
     r"indirect (impact|effect)|spill.?over|read.?across)\b",
     "macro/sector",
     "macro_transmission(macro_id, target_isin, order_no, sign, sensitivity_beta, "
     "lag_days, evidence_ref); the causal graph has first-order edges only", "partial"),
    ("sum_of_parts_holdco", r"\b(sum of (the )?parts|sotp|holding company|holdco|"
     r"listed subsidiary|unlisted subsidiary|stake in |discount to nav)\b",
     "stock",
     "holdco_stake(holdco_isin, listed_isin, stake_pct, stake_value_inr, as_of); "
     "sotp_valuation(holdco_isin, date, core_ev, stakes_value, net_debt, "
     "sotp_per_share, discount_pct)", "partial"),
    ("dividend_sustainability", r"\b(dividend (sustain|cover|payout|safety|growth)|"
     r"payout ratio|fcf cover|dividend yield|dividend history)\b",
     "stock",
     "dividend_history(isin, ex_date, dps_inr, kind); dividend_cover(isin, fy, "
     "fcf_inr, maintenance_capex_inr, dividends_paid_inr, payout_ratio, fcf_cover_x)", "partial"),
    ("customer_supplier_concentration", r"\b(customer concentration|client concentration|"
     r"top (customer|client)|single customer|largest customer|top 5 clients|"
     r"supplier concentration)\b",
     "stock",
     "revenue_concentration(isin, period, customer_label, share_pct, source_quote); "
     "supplier_concentration(isin, period, supplier_label, share_pct); only AR "
     "narrative holds this today", "partial"),
    ("thesis_break_sell", r"\b(thesis (break|broken|invalid|wrong)|conviction|"
     r"falsif|sell trigger|what would make me sell)\b",
     "stock",
     "thesis(isin, opened_at, claim, falsifier_text, horizon); "
     "thesis_check(isin, thesis_id, checked_at, status, evidence_ref)", "no"),
]

# ---------------------------------------------------------------- aliases
# (alias, symbol or group, kind, note)
ALIASES = [
    ("Zomato", "ETERNAL", "old_name", "renamed Eternal in 2025"),
    ("Eternal", "ETERNAL", "current", ""),
    ("Paytm", "PAYTM", "nickname", "One97 Communications"),
    ("One97", "PAYTM", "old_name", ""),
    ("Reliance", "RELIANCE", "nickname", ""),
    ("RIL", "RELIANCE", "abbreviation", ""),
    ("HDFC", "HDFCBANK", "old_name", "HDFC Ltd merged into HDFC Bank 2023"),
    ("HDFC Bank", "HDFCBANK", "current", ""),
    ("ICICI", "ICICIBANK", "abbreviation", ""),
    ("SBI", "SBIN", "abbreviation", ""),
    ("L&T", "LT", "abbreviation", ""),
    ("M&M", "M&M", "abbreviation", "Mahindra & Mahindra"),
    ("Infy", "INFY", "nickname", ""),
    ("TCS", "TCS", "ticker", ""),
    ("DMart", "DMART", "nickname", "Avenue Supermarts"),
    ("Avenue Supermarts", "DMART", "current", ""),
    ("Nykaa", "NYKAA", "nickname", "FSN E-Commerce"),
    ("Ola Electric", "OLAELEC", "current", ""),
    ("Mamaearth", "HONASA", "nickname", "Honasa Consumer"),
    ("Policybazaar", "POLICYBZR", "nickname", "PB Fintech"),
    ("Adani group", "ADANI_GROUP", "group", "basket, not one ISIN"),
    ("Adani stocks", "ADANI_GROUP", "group", "basket"),
    ("Tata stocks", "TATA_GROUP", "group", "basket"),
    ("Tata group", "TATA_GROUP", "group", "basket"),
    ("Bajaj twins", "BAJAJ_GROUP", "group", "basket"),
    ("PSU stocks", "PSU_BASKET", "group", "theme, not one ISIN"),
    ("PSU banks", "PSU_BANKS", "group", "theme"),
    ("defence stocks", "DEFENCE_THEME", "group", "theme"),
    ("railway stocks", "RAILWAY_THEME", "group", "theme"),
    ("Nifty", "NIFTY50_INDEX", "index", "index, not a company"),
    ("Bank Nifty", "BANKNIFTY_INDEX", "index", "index"),
    ("Sensex", "SENSEX_INDEX", "index", "index"),
    ("IREDA", "IREDA", "ticker", ""),
    ("IRFC", "IRFC", "ticker", ""),
    ("RVNL", "RVNL", "ticker", ""),
    ("HAL", "HAL", "ticker", ""),
    ("BEL", "BEL", "ticker", ""),
    ("BHEL", "BHEL", "ticker", ""),
    ("Suzlon", "SUZLON", "nickname", ""),
    ("Vedanta", "VEDL", "nickname", ""),
    ("Yes Bank", "YESBANK", "current", ""),
    ("IndusInd", "INDUSINDBK", "abbreviation", ""),
    ("Kotak", "KOTAKBANK", "abbreviation", ""),
    ("Axis", "AXISBANK", "abbreviation", ""),
    ("Coal India", "COALINDIA", "current", ""),
    ("Tata Motors", "TATAMOTORS", "current", ""),
    ("Tata Steel", "TATASTEEL", "current", ""),
    ("JSW Steel", "JSWSTEEL", "current", ""),
    ("Hindalco", "HINDALCO", "current", ""),
    ("Swiggy", "SWIGGY", "current", ""),
    ("Delhivery", "DELHIVERY", "current", ""),
    ("Zerodha", "ZERODHA", "broker", "unlisted broker, cannot resolve"),
    ("Groww", "GROWW", "broker", "unlisted broker, cannot resolve"),
    ("Nifty 50", "NIFTY50_INDEX", "index", ""),
]
MISSPELLINGS = [
    ("relaince", "RELIANCE"), ("reliance", "RELIANCE"), ("infosis", "INFY"),
    ("infosys", "INFY"), ("niffty", "NIFTY50_INDEX"), ("niftyy", "NIFTY50_INDEX"),
    ("senseks", "SENSEX_INDEX"), ("adnai", "ADANI_GROUP"), ("zomatoo", "ETERNAL"),
]
# One alternation beats 60 re.search calls per post.
_ALIAS_MAP = {a.lower(): (a, s, k) for a, s, k, _n in ALIASES}
_ALIAS_RX = re.compile(
    r"(?<![A-Za-z])(" + "|".join(sorted((re.escape(a) for a, _s, _k, _n in ALIASES),
                                        key=len, reverse=True)) + r")(?![A-Za-z])",
    re.I,
)
_MISS_MAP = {a.lower(): (a, s) for a, s in MISSPELLINGS}
_MISS_RX = re.compile(
    r"(?<![A-Za-z])(" + "|".join(sorted((re.escape(a) for a, _s in MISSPELLINGS),
                                        key=len, reverse=True)) + r")(?![A-Za-z])",
    re.I,
)
_MISS_COMPILED = [(re.compile(r"(?<![A-Za-z])" + re.escape(b) + r"(?![A-Za-z])", re.I), s)
                  for b, s in MISSPELLINGS]
_PATTERNS_COMPILED = [(name, re.compile(rx, re.I), focus, schema, ans)
                      for name, rx, focus, schema, ans in MISSING_PATTERNS]
_HOP_SECOND = re.compile(
    r"\b(impact|affect|because|due to|after|then|downstream|supply|"
    r"benefit|second.order|chain|if .* then|ripple|spill)\b", re.I)
_HOP_MACRO = re.compile(
    r"\b(policy|budget|rbi|fed|tariff|inflation|crude|rupee|global|"
    r"election|rate cut|recession|commodity)\b", re.I)

# ---------------------------------------------------------------- helpers
def load_posts(path: Path):
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            yield d


def month_of(ts) -> str:
    try:
        return dt.datetime.fromtimestamp(int(ts), dt.timezone.utc).strftime("%Y-%m")
    except (ValueError, OverflowError, OSError, TypeError):
        return "unknown"


def classify_family(text: str) -> tuple[int | None, str | None]:
    for fam, rx in FAMILY_RULES:
        if rx.search(text):
            return fam, None
    for name, rx in NEW_FAMILY_RULES:
        if rx.search(text):
            return None, name
    return None, "NEW:uncategorised"


def classify_level(text: str, group: str) -> str:
    for name, rx in LEVEL_RULES:
        if rx.search(text):
            return name
    if SECTOR_RE.search(text):
        return "sector"
    if THEME_RE.search(text):
        return "theme"
    if TICKER_RE.search(text):
        return "stock"
    if group == "international":
        return "stock"
    return "market-wide"


def naming_styles(text: str) -> list[str]:
    styles = []
    if HINGLISH.search(text):
        styles.append("hinglish")
    for m in _ALIAS_RX.finditer(text):
        kind = _ALIAS_MAP[m.group(1).lower()][2]
        if kind in {"old_name", "nickname", "abbreviation", "group", "index", "broker"}:
            styles.append(kind)
    if _MISS_RX.search(text):
        styles.append("misspelling")
    tick = TICKER_RE.findall(text)
    if any(len(t) >= 3 and t not in {"THE", "AND", "FOR", "NOT", "BUT", "YOU", "IPO",
                                     "NSE", "BSE", "FII", "DII", "RSI", "SIP", "ETF",
                                     "GDP", "CPI", "RBI", "SEBI", "FNO", "PE", "EPS",
                                     "PAT", "CMP", "LTP", "YOY", "QOQ", "ALL", "NEW",
                                     "WHY", "WHAT", "HOW", "CAN", "WILL", "BUY", "SELL",
                                     "HOLD", "TAX", "AMC"} for t in tick):
        styles.append("ticker")
    return sorted(set(styles))


def entity_mentions(text: str) -> set[tuple[str, str]]:
    out = set()
    for m in _ALIAS_RX.finditer(text):
        a, s, _k = _ALIAS_MAP[m.group(1).lower()]
        out.add((a, s))
    for m in _MISS_RX.finditer(text):
        a, s = _MISS_MAP[m.group(1).lower()]
        out.add((a, s))
    return out


def _post_aliases(text: str):
    seen = set()
    for m in _ALIAS_RX.finditer(text):
        a, s, k = _ALIAS_MAP[m.group(1).lower()]
        if (a, s, k) not in seen:
            seen.add((a, s, k))
            yield a, s, k, ""


def hop_depth(text: str) -> int:
    hops = 1
    if _HOP_SECOND.search(text):
        hops += 1
    if _HOP_MACRO.search(text):
        hops += 1
    return min(hops, 3)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", action="store_true")
    args = ap.parse_args()
    WORK.mkdir(parents=True, exist_ok=True)

    total = collections.Counter()
    kept = collections.Counter()
    kept_by_month = collections.Counter()
    kept_by_sub_month = collections.Counter()
    drop_reasons = collections.Counter()
    family_counts = collections.Counter()
    level_counts = collections.Counter()
    style_counts = collections.Counter()
    hop_counts = collections.Counter()
    time_counts = collections.Counter()
    datapoint_counts = collections.Counter()
    pair_counts = collections.Counter()
    pattern_counts = collections.Counter()
    pattern_samples = collections.defaultdict(list)
    alias_counts = collections.Counter()
    alias_posts = collections.defaultdict(set)
    post_id = 0

    files = sorted(RAW.glob("*.jsonl"))
    for path in files:
        sub = path.stem
        group = SUBREDDIT_GROUP.get(sub, "other")
        for d in load_posts(path):
            post_id += 1
            total[sub] += 1
            title = str(d.get("title") or "")
            body = str(d.get("selftext") or "")
            # ---- filter (title-first: the question lives in the title)
            if not title.strip():
                drop_reasons["no_title"] += 1
                continue
            if MEME.search(title) or PORTFOLIO_RATE.search(title):
                drop_reasons["meme_or_portfolio_rating"] += 1
                continue
            if not QUESTION.search(title):
                drop_reasons["no_question_marker"] += 1
                continue
            market_hits = len(MARKET.findall(title))
            pf_hits = len(PF_ONLY.findall(title))
            if pf_hits and market_hits < 2:
                if not MARKET.search(body[:250]):
                    drop_reasons["personal_finance_or_broker"] += 1
                    continue
            if market_hits == 0 and not entity_mentions(title):
                if not MARKET.search(body[:250]):
                    drop_reasons["no_market_subject"] += 1
                    continue
            # ---- kept: body sniff only now
            text = title + "\n" + body[:500]
            kept[sub] += 1
            mon = month_of(d.get("created_utc"))
            kept_by_month[mon] += 1
            kept_by_sub_month[(sub, mon)] += 1
            fam, newfam = classify_family(text)
            family_counts[fam if fam else newfam] += 1
            level_counts[classify_level(text, group)] += 1
            for s in naming_styles(title):
                style_counts[s] += 1
            hop_counts[hop_depth(text)] += 1
            t_hits = {T_NAMES[k] for m in T_RX.finditer(text)
                      for k, v in m.groupdict().items() if v}
            for name in t_hits:
                time_counts[name] += 1
            present = sorted({D_NAMES[k] for m in D_RX.finditer(text)
                              for k, v in m.groupdict().items() if v})
            for name in present:
                datapoint_counts[name] += 1
            for i, a in enumerate(present):
                for b in present[i + 1:]:
                    pair_counts[(a, b)] += 1
            for alias, sym, kind, _note in _post_aliases(text):
                alias_counts[(alias, sym, kind)] += 1
            for pname, prx, _focus, _schema, _ans in _PATTERNS_COMPILED:
                if prx.search(text):
                    pattern_counts[pname] += 1
                    if args.samples and len(pattern_samples[pname]) < 3:
                        pattern_samples[pname].append(title[:110])
        print(f"[mine] {sub}: {total[sub]} read, {kept[sub]} kept", file=sys.stderr, flush=True)

    stats = {
        "total_posts": sum(total.values()),
        "kept_posts": sum(kept.values()),
        "files": {s: total[s] for s in sorted(total)},
        "kept_by_subreddit": {s: kept[s] for s in sorted(total)},
        "subreddit_group": {s: SUBREDDIT_GROUP.get(s, "other") for s in sorted(total)},
        "kept_by_month": dict(sorted(kept_by_month.items())),
        "drop_reasons": dict(drop_reasons),
        "families": {str(k): v for k, v in sorted(family_counts.items(), key=lambda kv: -kv[1])},
        "levels": dict(level_counts.most_common()),
        "styles": dict(style_counts.most_common()),
        "hops": {str(k): v for k, v in sorted(hop_counts.items())},
        "time_phrases": dict(time_counts.most_common()),
        "datapoints": dict(datapoint_counts.most_common()),
        "pairs": [{"a": a, "b": b, "n": n} for (a, b), n in pair_counts.most_common(30)],
        "patterns": [{"name": n, "n": c} for n, c in pattern_counts.most_common()],
        "aliases": [
            {"alias": a, "symbol": s, "kind": k, "n": c}
            for (a, s, k), c in alias_counts.most_common()
        ],
    }
    (WORK / "mine_stats.json").write_text(json.dumps(stats, indent=1), encoding="utf-8")

    # patterns.csv
    with (HERE / "patterns.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["pattern", "posts", "share_of_kept_pct", "entity_focus",
                    "answerable", "schema_proposal"])
        denom = max(1, stats["kept_posts"])
        lookup = {p[0]: p for p in MISSING_PATTERNS}
        for p in stats["patterns"]:
            _, _rx, focus, schema, ans = lookup[p["name"]]
            w.writerow([p["name"], p["n"], f"{100*p['n']/denom:.1f}", focus,
                        ans, schema])

    # subreddit x month matrix
    months = sorted({m for (_s, m) in kept_by_sub_month})
    with (WORK / "subreddit_month.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["subreddit", "group"] + months + ["total"])
        for s in sorted(total):
            row = [kept_by_sub_month.get((s, m), 0) for m in months]
            w.writerow([s, SUBREDDIT_GROUP.get(s, "other")] + row + [kept[s]])

    print(json.dumps({k: stats[k] for k in
                      ("total_posts", "kept_posts", "drop_reasons")}, indent=1))
    print("kept per subreddit:", stats["kept_by_subreddit"])
    print("top families:", list(stats["families"].items())[:8])
    print("levels:", stats["levels"])
    print("top patterns:", stats["patterns"][:12])
    print("stdout samples are NOT written to the repo; read them, then author paraphrases.")
    if args.samples:
        for p in stats["patterns"][:30]:
            print("\n##", p["name"], p["n"])
            for t in pattern_samples.get(p["name"], []):
                print("  -", t)
    return 0


if __name__ == "__main__":
    sys.exit(main())
