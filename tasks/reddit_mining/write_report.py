"""Render tasks/reddit_mining/REPORT.md from the mining stats + CSVs."""
from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORK = HERE / "work"

FAMILIES = {
    "1": "Lookup (what did the entity say/report)",
    "2": "Number (metric for entity/period)",
    "3": "Change over time",
    "4": "Screen (which stocks meet condition)",
    "5": "Cross-document agreement",
    "6": "Policy -> companies",
    "7": "Company -> policy",
    "8": "Peers",
    "9": "Event window",
    "10": "Opinion vs truth",
    "11": "Point in time",
    "12": "When / timeline",
    "13": "Inverse screen (topic -> companies)",
    "14": "Governance and audit",
    "15": "Market move -> why",
    "16": "Input-cost / commodity transmission",
    "17": "Business economics",
    "18": "Forward policy impact",
    "19": "Second-order / supply chain",
    "20": "Out-of-scope / bizarre",
}

PARAPHRASES = {
    "mf_etf_vs_stock": ["Should I hold an index fund instead of picking stocks?",
                        "SIP in a Nifty ETF or buy the same names directly?",
                        "Which is cheaper over ten years: fund or direct equity?"],
    "fundamental_health_check": ["Is the balance sheet strong enough to survive a bad year?",
                                 "How do debt, ROE and cash flow look together?",
                                 "Is the reported profit real cash or accounting?"],
    "hold_or_sell_position": ["I am down 30%. Hold, average, or sell?",
                              "Should I book profit after this run-up?",
                              "Is waiting another year for a recovery worth it?"],
    "broker_platform_process": ["Which broker charges less for delivery trades?",
                                "Why did my order get rejected on the app?",
                                "How do I move shares between demat accounts?"],
    "fno_vs_cash_flow": ["Does futures OI tell me where the cash market goes?",
                         "Is the futures premium worth rolling before expiry?",
                         "Do delivery volumes matter when options expire?"],
    "index_inclusion_rebalance": ["How much passive buying comes when a stock enters Nifty?",
                                  "Will exclusion force selling at the next review?",
                                  "Which ETF flow hits my stock on rebalance day?"],
    "ipo_grey_listing_day": ["How did the grey premium compare with the listing price?",
                             "Is the IPO worth applying for a listing-day gain?",
                             "Why did it list below the grey-market talk?"],
    "ta_support_resistance": ["Is this support level still valid after the bounce?",
                              "Where do I put a stop below yesterday's low?",
                              "Has resistance been tested enough to break?"],
    "group_basket_entity": ["Which Adani stock is the safest of the group?",
                            "Best PSU bank to buy for the cycle?",
                            "Which Tata company benefits most from the capex?"],
    "entry_timing_good_time": ["Is now a good time to enter after the fall?",
                               "Should I wait for a retest before buying?",
                               "Too late to buy after this rally?"],
    "valuation_vs_peers": ["Is this stock expensive compared with its peers?",
                           "Why does it trade at a higher PE than the sector?",
                           "Which of the two is cheaper on EV/EBITDA?"],
    "global_cue_overnight": ["US markets fell overnight. How will Nifty open?",
                             "Does a Fed decision move my Indian stock next day?",
                             "Crude spiked overnight. Which sectors get hit at open?"],
    "dividend_record_date": ["Do I get the dividend if I buy before the record date?",
                             "What happens to my shares on the ex-dividend date?",
                             "Is the dividend yield worth holding for?"],
    "penny_low_price_stock": ["Which low-price stocks can double from here?",
                              "Is a ten-rupee stock cheaper than a thousand-rupee stock?",
                              "Are micro-caps with no earnings worth the risk?"],
    "corporate_action_aftermath": ["What happens to my shares after the demerger?",
                                   "How does the buyback affect my cost basis?",
                                   "Should I tender in the OFS or sell in the market?"],
    "ta_breakout_volume": ["Was the breakout confirmed by volume and delivery?",
                           "Is a low-volume breakout likely to fail?",
                           "How much delivery should a real breakout show?"],
    "ta_rsi_momentum": ["RSI is oversold. Is this a buy in an uptrend?",
                        "Can a stock stay overbought for weeks?",
                        "Does RSI divergence actually predict a reversal?"],
    "guidance_vs_delivery": ["Management promised this last year. Did they deliver?",
                             "Which guidance has been cut twice already?",
                             "Is the current guidance credible after the miss?"],
    "sebi_rule_question": ["Which SEBI rule applies to this preferential issue?",
                           "Was this disclosure late under LODR?",
                           "What does the regulator's order actually ban?"],
    "macro_event_what_if": ["If the RBI cuts rates, which stocks benefit first?",
                            "What does a tariff change do to my sector?",
                            "Budget day: buy before or after the speech?"],
    "cycle_peak_trough": ["Where are we in the steel cycle right now?",
                          "Is the cement downcycle over?",
                          "How much of the margin is cycle versus company?"],
    "ta_52week_extreme": ["It is near its 52-week high. Buy or wait?",
                          "How often does a 52-week-high breakout hold?",
                          "How long does a 15% drawdown take to recover?"],
    "ta_gap_event": ["Did the result gap fill, and how long did it take?",
                     "Is an opening gap up a trap?",
                     "Does a gap down act as resistance later?"],
    "why_stock_moved": ["Why did this stock fall 8% today?",
                        "The result beat. Why did the stock still fall?",
                        "Was the move company-specific or the whole sector?"],
    "fii_dii_flow_link": ["Did FII selling cause this stock's fall?",
                          "Are DIIs absorbing the FII selling?",
                          "How do I see FII flow for one stock?"],
    "ta_moving_average": ["Did the 50-day cross the 200-day?",
                          "How long has it been below the 200-day?",
                          "Which moving average is the best entry line?"],
    "ta_relative_strength": ["Is the stock stronger than Nifty over three months?",
                             "Has relative strength turned after the underperformance?",
                             "Is sector rotation showing in the RS line?"],
    "ta_oi_pcr_maxpain": ["What is the PCR, and does it mark a bottom?",
                          "Where is max pain into expiry?",
                          "Is the OI build-up longs or shorts?"],
    "results_calendar": ["When is the next result date?",
                         "Is the board meeting for results or dividend?",
                         "Which results are due this week?"],
    "promoter_pledge_sale": ["Is promoter pledge rising with the debt?",
                             "Did the promoter sell before the bad quarter?",
                             "How much of the float did the block deal absorb?"],
    "ta_delivery_spike": ["Was the delivery spike accumulation or a block deal?",
                          "Why is delivery 60% today?",
                          "Does high delivery at a high mean more upside?"],
    "theme_proxy_play": ["What is the best way to play the defence theme?",
                         "Which stock is a proxy for data-centre capex?",
                         "Is there an Indian play on the AI theme?"],
    "ta_chart_pattern": ["Is this a cup-and-handle or just a bounce?",
                         "Has the head-and-shoulders target played out?",
                         "Is the flag forming before another leg up?"],
    "ipo_vs_listed_peer": ["Is the IPO cheaper than the listed peer?",
                           "Why pay this multiple when the peer trades lower?",
                           "Should I apply or buy the peer instead?"],
    "circuit_band_behaviour": ["Why is it stuck in the upper circuit?",
                               "When will the circuit open so I can sell?",
                               "Did the band change after the base-price reset?"],
    "earnings_reaction_drift": ["Did the stock drift after the result gap?",
                                "How long does post-result momentum last?",
                                "Is the reaction to results usually overdone?"],
    "accounting_red_flags": ["Are receivables growing faster than revenue?",
                             "Is the auditor's opinion clean this year?",
                             "Why is cash flow behind reported profit?"],
    "second_order_beneficiary": ["Who supplies this company, and who benefits second?",
                                 "Which small-cap gains if the parent wins the order?",
                                 "Is the theme already priced into the supplier?"],
    "policy_impact_by_company": ["Which stocks does the new duty help?",
                                 "How much of revenue is exposed to this policy?",
                                 "Is the benefit already in the price?"],
    "moat_competitive_advantage": ["What protects this business from competition?",
                                   "Is the pricing power real or cyclical?",
                                   "Would a new entrant take share in five years?"],
    "capital_allocation": ["Is the buyback better than the dividend?",
                           "Is management reinvesting at a good return?",
                           "Why is the payout so high if capex is needed?"],
    "unit_economics": ["What does the company earn per order?",
                       "When does the quick-commerce business break even?",
                       "Is growth being bought with discounts?"],
    "merger_arbitrage": ["Is the swap ratio fair, and what is the spread?",
                         "How long until the merger closes?",
                         "What happens if the scheme is rejected?"],
    "second_order_macro": ["A rate cut helps banks. Who gains one step later?",
                           "Which supplier benefits after the big order?",
                           "How long does a crude move take to reach margins?"],
    "sum_of_parts_holdco": ["Is the holding company cheaper than the stake it owns?",
                            "What is the discount to the listed subsidiaries?",
                            "Should I buy the holdco or the operating company?"],
    "dividend_sustainability": ["Is the dividend covered by free cash flow?",
                                "Can the payout survive a weak year?",
                                "Why is the yield high if the debt is rising?"],
    "customer_supplier_concentration": ["How much revenue comes from the top client?",
                                        "What happens if the largest customer leaves?",
                                        "Does one supplier control the input cost?"],
    "thesis_break_sell": ["What would make the original thesis wrong?",
                          "Which disclosure should make me exit?",
                          "Is a stale thesis worth holding through a bad quarter?"],
}

TECH_TABLE = [
    ("support / resistance", "daily OHLCV + swing pivots + volume", "yes (dated rows); levels derived, not stored"),
    ("breakout with volume", "close vs level, volume/20d median, delivery %", "yes"),
    ("moving average / cross", "SMA20/50/200 from dated rows", "yes"),
    ("RSI setup", "RSI14 per dated row", "yes"),
    ("52-week high/low", "52w columns per dated row", "yes"),
    ("gap up/down", "prev close, open, low, next sessions", "yes"),
    ("relative strength vs index", "stock return vs Nifty close", "partial: Nifty only, no sector indices"),
    ("F&O OI build-up", "daily OI by strike/expiry, rollover, basis", "no table"),
    ("PCR / max pain", "option chain OI, expiry closes", "no table"),
    ("delivery spike", "delivery qty/%, volume, band state", "yes"),
    ("circuit / band behaviour", "price_bands + OHLCV + delivery", "yes"),
    ("chart patterns", "labelled windows (flag, triangle, H&S)", "no table"),
]

INTL_TABLE = [
    ("moat durability", "margin stability through a crude cycle; volume vs price"),
    ("ROIC vs WACC", "segment capital employed; through-cycle spread"),
    ("capital allocation", "cash returned vs retained; incremental return"),
    ("accounting red flags", "receivables/inventory days, CFO/PAT, notes"),
    ("management credibility", "dated guidance vs delivered number"),
    ("unit economics", "per-order or per-store contribution margin"),
    ("cycle position", "margin vs last peak; cost-curve claim"),
    ("second-order macro", "rate/crude/FX -> margin with a stated lag"),
    ("reinvestment runway", "capex per rupee of new revenue; project dates"),
    ("balance-sheet stress", "maturity wall, coverage, funding gap"),
    ("earnings quality", "accruals, DSO, capitalised cost"),
    ("sum of parts / holdco", "listed stakes at market, net debt, discount"),
    ("dividend sustainability", "FCF cover after maintenance capex"),
    ("customer concentration", "top-client share and revenue at risk"),
    ("thesis break", "explicit falsifier instead of a price target"),
]


def read_csv(name: str):
    with (HERE / name).open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def main() -> int:
    s = json.loads((WORK / "mine_stats.json").read_text(encoding="utf-8"))
    patterns = read_csv("patterns.csv")
    aliases = read_csv("aliases.csv")
    bank = [json.loads(line) for line in
            (HERE / "QUESTION_BANK_REDDIT_2026-10-28.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()]
    total, kept = s["total_posts"], s["kept_posts"]
    files = s["files"]
    kept_sub = s["kept_by_subreddit"]
    groups = s["subreddit_group"]
    L = []
    add = L.append

    add("# Reddit mining — how real investors ask about Indian stocks, sectors and policy")
    add("")
    add("Read-only mining of the Arctic Shift archive on `D:\\RealityEngine\\raw\\reddit` "
        "(posts from 2024-04-01 for Indian subreddits, last year for international and "
        "trading subreddits). Raw text never leaves D: only counts, original paraphrases "
        "under 15 words, and pattern names appear below.")
    add("")
    add("## 0. Drift from the context pack and logs")
    add("")
    add("- `fetch.log` / `fetch_intl.log` print `+0` for many subreddits, but the JSONL "
        "files on disk are populated (the log is a stale earlier run). Files win: "
        "28 subreddits have rows, 4 are empty and skipped (`IPOIndia`, `ShareMarketIndia`, "
        "`Trading_India`, `chartpatterns`).")
    add("- The context pack says `equity_intelligence.shareholding` has 40 rows; the "
        "reality-data `holding`/`shp_index` path is the one that carries quarterly pledge "
        "history for our coverage. The bank marks pledge questions `partial`, not `yes`.")
    add("- `DSH_WORKER_PROGRESS_NOTES` is unset in this worker; progress is logged in "
        "`tasks/reddit_mining/PROGRESS_NOTES.md`.")
    add("")
    add("## 1. Question-post filter and counts")
    add("")
    add("Deterministic rules, then a read of samples per pattern:")
    add("")
    add("1. **Keep** when the title asks something: a `?`, or an interrogative stem "
        "(`why/what/when/how/should/is/are/can/will/worth/best/kaun/kyun/kya/kab/kaise/kitna`) "
        "and the post names a market subject (`MARKET` regex over stock/share/nifty/IPO/"
        "results/valuation/FII/SEBI/budget... or a known alias).")
    add("2. **Drop** personal-finance-only and broker-process posts (tax filing, 80C, "
        "insurance, loans, credit score, KYC, broker app bug) when no market subject follows.")
    add("3. **Drop** memes/shitposts and bare portfolio-rating requests.")
    add("4. Body is read only after the title passes; this keeps the scan at ~30 s/file "
        "and the filter auditable.")
    add("")
    add("| | posts |")
    add("|---|---:|")
    add(f"| Rows read across 28 non-empty subreddits | {total:,} |")
    add(f"| Kept as question posts | **{kept:,}** ({100*kept/total:.1f}%) |")
    for k, v in sorted(s["drop_reasons"].items(), key=lambda kv: -kv[1]):
        add(f"| Dropped: {k} | {v:,} |")
    add("")
    add("### 1.1 Per subreddit")
    add("")
    add("| subreddit | group | rows | kept | keep % |")
    add("|---|---|---:|---:|---:|")
    for sub in sorted(files, key=lambda x: -files[x]):
        add(f"| {sub} | {groups.get(sub,'other')} | {files[sub]:,} | {kept_sub.get(sub,0):,} | "
            f"{100*kept_sub.get(sub,0)/max(1,files[sub]):.1f}% |")
    add("")
    add("### 1.2 Per month (kept)")
    add("")
    add("| month | kept | month | kept |")
    add("|---|---:|---|---:|")
    months = sorted(s["kept_by_month"])
    half = (len(months) + 1) // 2
    for i in range(half):
        left = months[i]
        right = months[i + half] if i + half < len(months) else ""
        rv = f"{s['kept_by_month'][right]:,}" if right else ""
        add(f"| {left} | {s['kept_by_month'][left]:,} | {right} | {rv} |")
    add("")
    add(f"The full subreddit x month matrix is `work/subreddit_month.csv` "
        f"({len(months)} months x {len(files)} subreddits).")
    add("")
    add("## 2. Family and entity-level frequency")
    add("")
    add("Families 1–20 are `tasks/QUERY_TEMPLATES_2026-10-27.md`. `NEW:*` means no "
        "template family fits; the name is the gap we would have to add.")
    add("")
    add("| family | description | posts | share |")
    add("|---|---|---:|---:|")
    fam_items = sorted(s["families"].items(), key=lambda kv: -kv[1])
    for k, v in fam_items:
        desc = FAMILIES.get(k, k.replace("NEW:", "NEW gap: ").replace("_", " "))
        add(f"| {k} | {desc} | {v:,} | {100*v/kept:.1f}% |")
    add("")
    add("Entity level:")
    add("")
    add("| level | posts | share |")
    add("|---|---:|---:|")
    for k, v in s["levels"].items():
        add(f"| {k} | {v:,} | {100*v/kept:.1f}% |")
    add("")
    add("How the entity is named (multi-label, title only):")
    add("")
    add("| naming style | posts | share |")
    add("|---|---:|---:|")
    for k, v in s["styles"].items():
        add(f"| {k} | {v:,} | {100*v/kept:.1f}% |")
    add("")
    add("Hop depth (1 = direct fact; 2 = one driver/peer/macro link; 3 = a chain or "
        "two or more drivers; heuristic documented in `mine.py::hop_depth`):")
    add("")
    add("| hops | posts | share |")
    add("|---|---:|---:|")
    for k, v in s["hops"].items():
        add(f"| {k} | {v:,} | {100*v/kept:.1f}% |")
    add("")
    add("## 3. Data the asker connects")
    add("")
    add("| data point | posts |")
    add("|---|---:|")
    for k, v in s["datapoints"].items():
        add(f"| {k} | {v:,} |")
    add("")
    add("Top co-occurring pairs (both named in the same post):")
    add("")
    add("| pair | posts |")
    add("|---|---:|")
    for p in s["pairs"][:15]:
        add(f"| {p['a']} + {p['b']} | {p['n']:,} |")
    add("")
    add("## 4. The top 30 question patterns we are missing")
    add("")
    add("Frequency is the number of kept posts whose title/opening mentions the pattern "
        "(rules in `mine.py::MISSING_PATTERNS`; patterns overlap, so counts are upper "
        "bounds on distinct asks). Answerability and schema are repeated per row in "
        "`patterns.csv`.")
    add("")
    for i, p in enumerate(patterns[:30], 1):
        name = p["pattern"]
        examples = PARAPHRASES.get(name, ["(no paraphrase recorded)", "", ""])
        add(f"### {i}. `{name}` — {int(p['posts']):,} posts ({p['share_of_kept_pct']}% of kept)")
        add("")
        add(f"- Entity focus: {p['entity_focus']}; answerable today: **{p['answerable']}**.")
        for ex in examples:
            if ex:
                add(f"- e.g. “{ex}”")
        add(f"- Schema: `{p['schema_proposal']}`")
        add("")
    add("## 5. Technical patterns: data needed and point-in-time status")
    add("")
    add("| pattern | price / volume / delivery / OI / band needed | held PIT? |")
    add("|---|---|---|")
    for a, b, c in TECH_TABLE:
        add(f"| {a} | {b} | {c} |")
    add("")
    add("Raw OHLCV, volume, delivery, 52-week and band rows are dated and PIT-safe. "
        "Derived columns (SMA/RSI) are stored per dated row, so an as-of question must "
        "read the row for that date, never today's column. OI, PCR, max pain, rollover "
        "and chart patterns are NOT IN DATA; those questions are in the bank with "
        "`coverage.verdict = no`.")
    add("")
    add("## 6. International value patterns, translated")
    add("")
    add("| pattern from value/fundamentals subs | Indian translation used in the bank |")
    add("|---|---|")
    for a, b in INTL_TABLE:
        add(f"| {a} | {b} |")
    add("")
    add("## 7. Aliases")
    add("")
    add(f"`aliases.csv` lists every alias with frequency >= 20, the resolved symbol/ISIN, "
        f"and whether `reality-data.resolve` returns an active equity today "
        f"({len(aliases)} rows).")
    add("")
    add("| alias | target | resolves | frequency |")
    add("|---|---|---|---:|")
    for r in sorted(aliases, key=lambda x: -int(x["frequency"]))[:15]:
        add(f"| {r['alias']} | {r['target']} | {r['resolves']} | {int(r['frequency']):,} |")
    add("")
    add("Failures today (the trader's word does not land on a live ISIN):")
    add("")
    add("| alias | target | resolves | note | frequency |")
    add("|---|---|---|---|---:|")
    bad = [r for r in aliases if r["resolves"] != "yes"]
    for r in sorted(bad, key=lambda x: -int(x["frequency"]))[:10]:
        add(f"| {r['alias']} | {r['target']} | {r['resolves']} | {r['note'][:70]} | "
            f"{int(r['frequency']):,} |")
    add("")
    add("## 8. Time-phrase dictionary")
    add("")
    add("Phrases are stored verbatim in the raw posts (not reproduced here); this is the "
        "canonical form the miner matches and its frequency.")
    add("")
    add("| canonical | surface forms | posts |")
    add("|---|---|---:|")
    surface = {
        "today": "today / aaj / intraday", "tomorrow": "tomorrow / kal / next session",
        "yesterday": "yesterday / kal", "this week": "this week", "last week": "last week",
        "next week": "next week", "this month": "this month",
        "this quarter": "this quarter / current quarter", "QnFYxx": "Q1FY26 … Q4FY27",
        "after budget": "post-budget / after the budget", "before budget": "pre-budget",
        "after election": "after / since / post election", "after results": "after / post results",
        "this year": "this year / current year", "last year": "last / past year",
        "YTD": "YTD / year to date", "52-week": "52-week", "expiry": "expiry / expiration",
        "long term": "long term / 5-10 years / decade", "since listing": "since IPO / listing",
        "next quarter": "next quarter / next Qn", "since 2024": "since 2024",
        "after rate cut": "after rate cut / RBI decision / Fed", "at open": "at / on market open",
    }
    for k, v in sorted(s["time_phrases"].items(), key=lambda kv: -kv[1]):
        add(f"| {k} | {surface.get(k, k)} | {v:,} |")
    add("")
    add("## 9. The bank")
    add("")
    cnt = Counter(r["group"] for r in bank)
    verd = Counter(r["coverage"]["verdict"] for r in bank)
    add(f"- `QUESTION_BANK_REDDIT_2026-10-28.jsonl`: {len(bank)} rows "
        f"(indian {cnt['indian']}, international {cnt['international']}, "
        f"technical {cnt['technical']}); unique qids; every entity resolves to an active "
        f"ISIN in `master_companies`.")
    add(f"- Coverage verdicts: " + ", ".join(f"{k} {v}" for k, v in sorted(verd.items())) + ".")
    add("- Each row carries the open-bank fields (`family`, `rubric`, `coverage`, `why`) "
        "plus `reddit_pattern` and `group`.")
    add("- New patterns covered by the bank: group/basket, grey-market IPO and listing day, "
        "entry timing, corporate-action aftermath (demerger/buyback/OFS), SEBI rules, "
        "F&O vs cash, overnight global cues, position decisions, plus the 15 translated "
        "value patterns and 10 technical setups.")
    add("")
    add("## 10. Reproduce")
    add("")
    add("```bash")
    add("python tasks/reddit_mining/mine.py --samples   # aggregates -> work/, patterns.csv")
    add("python tasks/reddit_mining/aliases.py          # resolve check -> aliases.csv")
    add("python tasks/reddit_mining/build_bank.py       # validate -> jsonl + md")
    add("python tasks/reddit_mining/check_leak.py       # 10-word overlap check")
    add("python tasks/reddit_mining/write_report.py     # this report")
    add("```")
    add("")
    (HERE / "REPORT.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"wrote REPORT.md ({len(L)} lines); patterns {len(patterns)}; aliases {len(aliases)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
