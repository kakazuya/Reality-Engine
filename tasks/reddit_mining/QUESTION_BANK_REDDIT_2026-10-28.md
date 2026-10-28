# Reddit-mined question bank — 243 questions (2026-10-28)

Mined from 15 Indian-market subreddits (since 2024-04-01), 15 international
value/fundamentals subreddits and 10 trading subreddits (last year).
Every question is original wording modelled on a pattern, not a copied post.
Every company entity resolves to an active ISIN in `master_companies`; the
pattern-gap rows may name an index, sector, theme, commodity or policy instead.

## Summary

- Rows by group: indian 75, international 75, technical 50, gap 43.
- Coverage: no 10, partial 191, yes 42.
- Each row carries `reddit_pattern`, the pattern it was modelled on.
- No `ground_truth` is asserted here; `ground_truth_query` names the first table to compute from.

| qid range | group | rows | patterns |
|---|---|---|---|
| RD-I-001…RD-I-075 | indian | 75 | 14 |
| RD-N-001…RD-N-075 | international | 75 | 12 |
| RD-T-001…RD-T-050 | technical | 50 | 9 |
| RD-G-001…RD-G-043 | gap | 43 | 11 |

---

## Indian-market patterns

### RD-I-001 · entry_timing · family NEW:entry_timing · `entry_timing_good_time`

**Q.** Reliance has just reported Q2FY26. Is this a good level to start a position, or should I wait for a retest of the pre-result range?

- Entities: RELIANCE (INE002A01018)
- Period: Q2FY26 · as-of: 2026-10-19 · answer: explanation
- Evidence: px_nse daily close/volume for the 60 sessions around the result; daily_price_delivery SMA20/50/200 and RSI14; results_xbrl for the print; concall_facts for guidance
- Steps: mark the pre-result range -> measure the post-result gap and whether it held -> compare price with SMA50/200 and 1-year percentile -> state entry conditions, not a single verdict
- Forbidden: calling a level cheap without any valuation basis; timing a purchase off one day's move
- Coverage: **partial** — price and indicator state are computable per date but no served table answers 'is now a good entry'; no valuation percentile history
- Why: the single most common retail phrasing ('good time to enter') has no family in the templates

### RD-I-002 · entry_timing · family NEW:entry_timing · `entry_timing_good_time`

**Q.** DMart is well below its 52-week high but still expensive on PE. For someone starting fresh, enter now or wait for a lower level?

- Entities: DMART (INE192R01011)
- Period: latest · as-of: 2026-10-19 · answer: explanation
- Evidence: px_nse close, 52-week high/low and drawdown; annual_financials/quarterly_financials for PE inputs; master_companies market cap
- Steps: compute drawdown from 52w high -> compute trailing PE from verified EPS -> show the 3-year PE range if derivable -> list what would have to change for the entry case
- Forbidden: answering only from the chart when the question explicitly asks about valuation; inventing a 'fair PE'
- Coverage: **partial** — 52-week math is held; a historical PE percentile table is not
- Why: retail asks entry timing as a joint price+valuation question

### RD-I-003 · entry_timing · family NEW:entry_timing · `entry_timing_good_time`

**Q.** Paytm has come off its lows. Is the risk-reward good enough to enter before the next results, or is waiting safer?

- Entities: PAYTM (INE982J01020)
- Period: next quarter · as-of: 2026-10-19 · answer: explanation
- Evidence: px_nse price path and realised volatility; results_xbrl revenue/PAT trend; concall_facts on profitability guidance
- Steps: show the earnings trend and the cash position -> show the drawdown from listing -> name the event risk before the next print
- Forbidden: treating a recovery in price as proof the business turned; ignoring the regulatory history
- Coverage: **partial** — the business facts exist; the risk-reward framing does not
- Why: asks the market to weigh a beaten-down stock's recovery against event risk

### RD-I-004 · entry_timing · family NEW:entry_timing · `entry_timing_good_time`

**Q.** IREDA ran up a lot after listing. Is it too late to enter now, or does the loan-book growth still justify a fresh position?

- Entities: IREDA (INE202E01016)
- Period: FY26 · as-of: 2026-10-19 · answer: explanation
- Evidence: px_nse since listing; quarterly_financials loan growth/NIM; annual_financials ROE; valuation inputs from verified EPS and book value
- Steps: compute the run-up since listing -> show growth and ROE trend -> compare price with book-derived valuation -> state what growth is already priced in
- Forbidden: calling a stock 'too late' from price alone; using unverified book value
- Coverage: **partial** — no P/B history table; book value and EPS are held
- Why: 'too late to enter' is a distinct phrasing from 'good time to buy'

### RD-I-005 · entry_timing · family NEW:entry_timing · `entry_timing_good_time`

**Q.** Titagarh Rail had a strong order-book run and then a sharp pullback. Kya abhi entry sahi hai, ya result ke baad dekhna chahiye?

- Entities: TITAGARH (INE615H01020)
- Period: Q2FY26 · as-of: 2026-10-19 · answer: explanation
- Evidence: px_nse/px_nse_adj post-run-up drawdown; concall_facts order book and execution guidance; results_xbrl revenue/PAT
- Steps: separate the order-book story from the delivered revenue -> show the drawdown and volume on the fall -> name the next dated catalyst
- Forbidden: assuming an order book converts to revenue on schedule; reading Hinglish as a request for a tip
- Coverage: **partial** — order-book statements are held; no execution-slippage table
- Why: Hinglish entry-timing phrasing with a fundamentals hook

### RD-I-006 · group_basket · family NEW:group_basket · `group_basket_entity`

**Q.** Adani group has several listed arms. Which one carries the least balance-sheet risk relative to its cash generation right now?

- Entities: ADANIENT (INE423A01024), ADANIPOWER (INE814H01029), ADANIGREEN (INE364U01010), ADANIPORTS (INE742F01042), ADANIENSOL (INE931S01010)
- Period: FY26 · as-of: 2026-10-19 · answer: ranking
- Evidence: annual_financials/quarterly_financials net debt, EBITDA, interest cover; ar_facts debt notes; px_nse market cap
- Steps: build the same leverage and coverage ratio for every member -> rank -> name the one where the ratio is least dependent on refinancing
- Forbidden: reading one group company's cash as another's; summing group market cap as if it were one entity
- Coverage: **partial** — member ISINs resolve, but there is no entity_group table or group-level consolidation
- Why: group/basket entities are absent from all three existing banks

### RD-I-007 · group_basket · family NEW:group_basket · `group_basket_entity`

**Q.** Within the Tata group, which listed company is the cleanest proxy for the group's own capex plans, and which is mostly a holding-company discount story?

- Entities: TMPV (INE155A01022), TATASTEEL (INE081A01020), TATAPOWER (INE245A01021), TITAN (INE280A01028), TCS (INE467B01029)
- Period: FY26 · as-of: 2026-10-19 · answer: list
- Evidence: annual_financials capex proxy; concall_facts capex guidance; shareholding for cross-holdings; px_nse for market cap
- Steps: find each member's capex line and guidance -> mark which ones sell to group companies -> flag the ones whose valuation is a holdco discount
- Forbidden: listing group companies from memory without an ownership map
- Coverage: **partial** — no entity_group / ownership-edge table; annual report related-party notes are the only path
- Why: 'Tata stocks' is asked as a basket, not as five unrelated lookups

### RD-I-008 · group_basket · family NEW:group_basket · `group_basket_entity`

**Q.** PSU banks: which of the large ones has the best combination of NIM and credit cost this quarter, and which is most exposed to a slippage cycle?

- Entities: SBIN (INE062A01020), BANKBARODA (INE028A01039), PNB (INE160A01022), CANBK (INE476A01022), UNIONBANK (INE692A01016)
- Period: Q2FY26 · as-of: 2026-10-19 · answer: ranking
- Evidence: results_xbrl interest income/expense, provisions; concall_facts NIM and credit-cost commentary; annual_financials ROA
- Steps: compute NIM and credit cost per bank from verified facts -> rank -> show which one's provision coverage is thinnest
- Forbidden: using the headline PAT without provisioning; comparing banks at different consolidation bases
- Coverage: **partial** — XBRL facts are held; a normalised bank-metrics table is not
- Why: PSU banks are always asked as a basket

### RD-I-009 · group_basket · family NEW:group_basket · `group_basket_entity`

**Q.** Defence pack: HAL, BEL, Mazagon Dock and BDL. Which has the order book to revenue cover that best protects it if capex slows?

- Entities: HAL (INE066F01020), BEL (INE263A01024), MAZDOCK (INE249Z01020), BDL (INE171Z01026)
- Period: FY26 · as-of: 2026-10-19 · answer: ranking
- Evidence: concall_facts order book; results_xbrl revenue; annual_financials; px_nse market cap
- Steps: take each order book and divide by trailing revenue -> rank cover -> note execution timelines where disclosed
- Forbidden: comparing order books stated on different dates without saying so
- Coverage: **partial** — order-book numbers are text facts, not a structured backlog table
- Why: the defence basket is asked constantly and has no basket object

### RD-I-010 · group_basket · family NEW:group_basket · `group_basket_entity`

**Q.** Railway names RVNL, IRFC, IRCON and RITES all move with rail capex. Which one actually earns a spread on the capex, and which just holds the paper?

- Entities: RVNL (INE415G01027), IRFC (INE053F01010), IRCON (INE962Y01021), RITES (INE320J01015)
- Period: FY26 · as-of: 2026-10-19 · answer: explanation
- Evidence: annual_financials revenue/margin; concall_facts order book; ar_facts business model; px_nse
- Steps: classify each by revenue model (EPC, lender, consultant) -> show margin and leverage per model -> map to the capex cycle
- Forbidden: treating IRFC's lending book as construction revenue; ranking by stock return
- Coverage: **partial** — business model text exists; no structured revenue-model tag
- Why: retail groups four very different business models under one 'railway' label

### RD-I-011 · ipo_grey_listing · family NEW:ipo_grey_market · `ipo_grey_listing_day`

**Q.** Swiggy listed at a discount to the grey-market talk. What did the grey premium imply before listing, and how did the first-day close compare?

- Entities: SWIGGY (INE00H001014)
- Period: listing · as-of: 2026-10-19 · answer: fact
- Evidence: px_nse first trade and first-day OHLC; corporate_documents for the prospectus/issue details; no grey-market series
- Steps: state the issue price -> show the first-day open/close and return -> say the grey premium is NOT IN DATA rather than quoting a forum number
- Forbidden: presenting a grey-market premium as an official price; using the first-week close as the listing-day return
- Coverage: **no** — listing-day prices are held; no GMP/grey-market table exists
- Why: IPO grey-market and listing-day questions are a large retail class with no table

### RD-I-012 · ipo_grey_listing · family NEW:ipo_grey_market · `ipo_grey_listing_day`

**Q.** Ola Electric's listing pop faded quickly. What was the listing-day return, and how much of it was gone within a month?

- Entities: OLAELEC (INE0LXG01040)
- Period: listing+1M · as-of: 2026-10-19 · answer: fact
- Evidence: px_nse from first trade; corporate_documents issue price; symbol_isin_history for the listing date
- Steps: identify the first trading date -> compute listing-day and 1-month return from issue price -> separate issue-price return from first-close return
- Forbidden: using the pre-listing grey premium as the issue price
- Coverage: **yes** — issue price + daily prices give the whole answer
- Why: tests listing-day return against a stated anchor

### RD-I-013 · ipo_grey_listing · family NEW:ipo_grey_market · `ipo_grey_listing_day`

**Q.** Waaree Energies: was the listing-day move justified by the order book disclosed in the prospectus, or was it mostly scarcity?

- Entities: WAAREEENER (INE377N01017)
- Period: listing · as-of: 2026-10-19 · answer: explanation
- Evidence: corporate_documents prospectus/DRHP; concall_facts order book; px_nse listing-day move; results_xbrl first quarters
- Steps: pull the disclosed order book and capacity -> compare with the first reported quarter -> separate fundamentals from float scarcity
- Forbidden: explaining the pop with post-listing news
- Coverage: **partial** — prospectus is a document, not structured facts; order book extraction is partial
- Why: asks for the fundamental justification of an IPO pop

### RD-I-014 · ipo_grey_listing · family NEW:ipo_grey_market · `ipo_grey_listing_day`

**Q.** Premier Energies versus the older solar names: did the IPO price already capture the order book that peers took years to build?

- Entities: PREMIERENE (INE0BS701011), WAAREEENER (INE377N01017), SOLARINDS (INE343H01029)
- Period: listing · as-of: 2026-10-19 · answer: explanation
- Evidence: corporate_documents prospectus; concall_facts order book/capacity; results_xbrl revenue; px_nse
- Steps: line up order book and capacity at issue -> compare with listed peers on revenue and margin -> state what the issue price implied
- Forbidden: comparing an issue-date order book with a peer's later disclosure
- Coverage: **partial** — no issue-date peer valuation table
- Why: 'IPO priced versus listed peer' is a recurring retail comparison

### RD-I-015 · ipo_grey_listing · family NEW:ipo_grey_market · `ipo_grey_listing_day`

**Q.** NTPC Green and the renewable IPP pack: after the listing, which one trades at the biggest premium to book, and what does the market expect from it?

- Entities: NTPCGREEN (INE0ONG01011), ADANIGREEN (INE364U01010), JSWENERGY (INE121E01018), TATAPOWER (INE245A01021)
- Period: latest · as-of: 2026-10-19 · answer: ranking
- Evidence: px_nse market cap; annual_financials book equity; capacity facts from concall/deck
- Steps: compute P/B for each -> rank -> state the capacity/revenue growth needed to justify the top multiple
- Forbidden: using pre-IPO book value; mixing standalone and consolidated equity
- Coverage: **partial** — P/B computable from verified equity; no sector valuation table
- Why: post-IPO renewable comparison is asked as a basket

### RD-I-016 · corporate_action_aftermath · family NEW:corporate_action · `corporate_action_aftermath`

**Q.** After the Tata Motors demerger into TMPV and TMCV, which entity carries the auto-finance exposure, and how should the cost basis split?

- Entities: TMPV (INE155A01022), TMCV (INE1TAE01010)
- Period: demerger · as-of: 2026-10-19 · answer: explanation
- Evidence: events for the scheme record date; corporate_documents scheme/announcement; px_nse_adj adjustment factors; shareholding
- Steps: find the record date -> state the entitlement ratio -> explain the price adjustment on the ex-date -> point to the official cost-basis circular
- Forbidden: inventing a cost-basis split; applying the demerger ratio to the wrong ISIN
- Coverage: **partial** — record dates and adjustment factors exist; the shareholder cost-basis rule is not stored
- Why: demerger aftermath is one of the highest-frequency retail questions

### RD-I-017 · corporate_action_aftermath · family NEW:corporate_action · `corporate_action_aftermath`

**Q.** Zomato is now Eternal. Does my old Zomato holding map to the same ISIN, and how does the price history handle the name change?

- Entities: ETERNAL (INE758T01015)
- Period: 2025 · as-of: 2026-10-19 · answer: fact
- Evidence: symbol_isin_history (NSE ZOMATO -> ETERNAL); security_master ISIN; px_nse_adj
- Steps: show the symbol change window -> confirm the ISIN is unchanged -> explain that no adjustment factor applies for a rename
- Forbidden: treating a rename as a corporate action with a price adjustment
- Coverage: **yes** — symbol history + ISIN map answers it exactly
- Why: old-name/rename alias resolution is a real retail need

### RD-I-018 · corporate_action_aftermath · family NEW:corporate_action · `corporate_action_aftermath`

**Q.** Vedanta's demerger: which listed entity will hold the aluminium business, and what happens to my shares between the record date and listing?

- Entities: VEDL (INE205A01025)
- Period: demerger · as-of: 2026-10-19 · answer: date
- Evidence: events/corporate_documents for the scheme; shareholding; symbol_isin_history for any new listing
- Steps: state the scheme stage -> name the record date if disclosed -> say the unlisted period is NOT IN DATA if the new entity has no ISIN
- Forbidden: naming a listing date that has not been announced; assuming the demerged entity is listed
- Coverage: **partial** — scheme documents are held; the new entities may have no ISIN yet
- Why: the gap between record date and listing is exactly what retail asks

### RD-I-019 · corporate_action_aftermath · family NEW:corporate_action · `corporate_action_aftermath`

**Q.** If a company announces a 1:1 bonus, what price should the stock open at on the ex-date, and does my average cost change?

- Entities: WIPRO (INE075A01022)
- Period: mechanics · as-of: 2026-10-19 · answer: explanation
- Evidence: corporate_documents for a past bonus of the same company; px_nse_adj cumulative factor; events
- Steps: use a past instance where both pre- and post-ex prices are held -> show the adjusted open -> explain that average cost per share falls proportionally
- Forbidden: confusing a bonus with a split when the accounting differs; quoting a rule without an example
- Coverage: **yes** — past bonus examples with adjustment factors answer the mechanics
- Why: corporate-action mechanics questions are asked as 'what happens to my shares'

### RD-I-020 · corporate_action_aftermath · family NEW:corporate_action · `corporate_action_aftermath`

**Q.** Government OFS in IREDA: how is the floor price set, and does the stock usually trade at a discount to it before the issue closes?

- Entities: IREDA (INE202E01016)
- Period: OFS · as-of: 2026-10-19 · answer: explanation
- Evidence: corporate_documents/announcements for OFS terms; px_nse around the OFS window; shareholding for promoter stake
- Steps: state the OFS mechanism -> show the floor price and the market price around it -> measure the discount window from held prices
- Forbidden: treating the floor price as the issue price for retail; ignoring the T+1 allotment
- Coverage: **partial** — OFS terms appear in announcements; no structured OFS table
- Why: OFS questions are frequent and mechanical

### RD-I-021 · sebi_rule · family NEW:sebi_rule · `sebi_rule_question`

**Q.** Which regulator action hit Paytm Payments Bank, when was it disclosed, and how did the listed company's price react on the first trading day after?

- Entities: PAYTM (INE982J01020)
- Period: 2024-01/2024-02 · as-of: 2024-03-31 · answer: date
- Evidence: bse_announcements/corporate_documents with dissemination timestamps; px_nse around the event; event timeline in events
- Steps: find the disclosure timestamp -> take the first session after it -> compute the move -> separate the bank action from the listed-company action
- Forbidden: mixing RBI and SEBI jurisdiction; using a later news article as the disclosure time
- Coverage: **partial** — announcements and prices are held; the rule text is not
- Why: retail conflates RBI/SEBI actions and asks 'which rule applied'

### RD-I-022 · sebi_rule · family NEW:sebi_rule · `sebi_rule_question`

**Q.** Adani Enterprises: what has SEBI actually concluded, what is still open, and which disclosures since 2023 changed the risk?

- Entities: ADANIENT (INE423A01024)
- Period: 2023-2026 · as-of: 2026-10-19 · answer: list
- Evidence: bse_announcements/corporate_documents for SEBI orders and company replies; events for the timeline
- Steps: list dated regulator actions -> separate allegation, order and appeal -> mark unresolved items NOT IN DATA
- Forbidden: asserting guilt or exoneration; summarising court/regulator positions without a dated source
- Coverage: **partial** — filings carry the documents; no structured regulatory-case table
- Why: regulatory-status questions need a case timeline, not a search hit

### RD-I-023 · sebi_rule · family NEW:sebi_rule · `sebi_rule_question`

**Q.** Yes Bank's reconstruction scheme locked in shareholder shares. What is still subject to lock-in, and when does the restriction end?

- Entities: YESBANK (INE528G01035)
- Period: scheme · as-of: 2026-10-19 · answer: date
- Evidence: corporate_documents/announcements for the scheme; bse_announcements; shareholding
- Steps: state the scheme date and the lock-in terms -> show the promoter holding after the scheme -> say what has expired
- Forbidden: quoting the original scheme as current without checking amendments
- Coverage: **partial** — documents are held; lock-in expiry is buried in text
- Why: scheme lock-in expiry is a common 'when can I sell' question

### RD-I-024 · sebi_rule · family NEW:sebi_rule · `sebi_rule_question`

**Q.** Vodafone Idea's preferential allotment: which SEBI pricing rule set the floor, and did the issue dilute more than the announcement implied?

- Entities: IDEA (INE669E01016)
- Period: 2024-2025 · as-of: 2026-10-19 · answer: fact
- Evidence: corporate_documents for the preferential issue notice; shareholding changes; px_nse for the pricing window
- Steps: find the relevant date under the ICDR pricing rule -> compute the floor from held prices -> compare shares issued with the stated dilution
- Forbidden: using the announcement date instead of the relevant date; ignoring the conversion of partly paid shares
- Coverage: **partial** — the rule is known but not stored with a version/effective date
- Why: preferential-issue pricing is asked as a rule application

### RD-I-025 · sebi_rule · family NEW:sebi_rule · `sebi_rule_question`

**Q.** For a small-cap like Titagarh, what does SEBI's LODR require to be disclosed within 24 hours, and which recent filings met or missed that clock?

- Entities: TITAGARH (INE615H01020)
- Period: 2025-2026 · as-of: 2026-10-19 · answer: list
- Evidence: bse_announcements dissemination timestamps vs event times; corporate_documents
- Steps: list material events -> compare dissemination time with the event time -> flag gaps over 24 hours
- Forbidden: assuming the filing timestamp is the event time; quoting a rule without the current version
- Coverage: **partial** — timestamps are held; no LODR rule table or automated clock check
- Why: retail asks 'why was this not disclosed earlier' as a rule question

### RD-I-026 · circuit_band · family NEW:circuit_band · `circuit_band_behaviour`

**Q.** Suzlon has been hitting upper circuits repeatedly. Which band applies now, what was the last base-price reset, and when did it last open normally?

- Entities: SUZLON (INE040H01021)
- Period: 2024-2026 · as-of: 2026-10-19 · answer: fact
- Evidence: price_bands (date, symbol, series, band_pct); px_nse OHLC and volume; daily_price_delivery
- Steps: read the band history -> find the last base-price reset -> show the circuit-locked days and the first day volume returned
- Forbidden: treating a locked close as a tradable price; assuming the band never changes
- Coverage: **yes** — price_bands + OHLC answer it; circuit_event is a cheap derived view
- Why: circuit behaviour is a very common small-cap question

### RD-I-027 · circuit_band · family NEW:circuit_band · `circuit_band_behaviour`

**Q.** Vodafone Idea trades in a narrow band. Is the 5% limit still on, and how does delivery behave on the days it touches the band?

- Entities: IDEA (INE669E01016)
- Period: 2025-2026 · as-of: 2026-10-19 · answer: fact
- Evidence: price_bands; px_nse delivery quantity/percent; daily_price_delivery
- Steps: show the current band -> list band-touch days -> compute delivery % on those days vs the 60-day median
- Forbidden: comparing delivery % across exchanges without saying which
- Coverage: **yes** — band + delivery are held per exchange
- Why: retail links circuit hits to delivery, the data can settle it

### RD-I-028 · circuit_band · family NEW:circuit_band · `circuit_band_behaviour`

**Q.** Jaiprakash Power: did the band change after the last base-price reset, and did the change coincide with the volume spike?

- Entities: JPPOWER (INE351F01018)
- Period: 2025-2026 · as-of: 2026-10-19 · answer: fact
- Evidence: price_bands band changes; px_nse volume; daily_price_delivery
- Steps: align band-change dates with volume z-scores -> report whether the spike came before or after the change
- Forbidden: claiming causation from date alignment alone
- Coverage: **yes** — both series are dated and PIT
- Why: band resets are a known small-cap trigger

### RD-I-029 · circuit_band · family NEW:circuit_band · `circuit_band_behaviour`

**Q.** Reliance Power has had long lower-circuit streaks. How many sessions did it stay locked, and what finally broke the streak?

- Entities: RPOWER (INE614G01033)
- Period: 2024-2026 · as-of: 2026-10-19 · answer: date
- Evidence: px_nse high/low/close; price_bands; events for a disclosure on the break day
- Steps: detect consecutive band-locked closes -> count sessions -> find the first volume day and any disclosure that day
- Forbidden: attributing the break to news without a timestamp
- Coverage: **partial** — streaks are derivable; the 'why' needs an event match
- Why: 'when will the circuit open' is asked over and over

### RD-I-030 · circuit_band · family NEW:circuit_band · `circuit_band_behaviour`

**Q.** Ola Electric after listing: did the price band widen, and how did the delivery percentage change when it did?

- Entities: OLAELEC (INE0LXG01040)
- Period: 2024-2026 · as-of: 2026-10-19 · answer: fact
- Evidence: price_bands for the band schedule; px_nse delivery; symbol_isin_history for the listing date
- Steps: show the band schedule from listing -> mark the widening -> compare delivery % before and after
- Forbidden: assuming all newly listed stocks get the same band schedule
- Coverage: **yes** — band and delivery are dated; the exchange rule itself is not stored
- Why: new-listing band mechanics are asked constantly

### RD-I-031 · why_moved · family 15 · `why_stock_moved`

**Q.** Why did Reliance fall on 4 June 2024, and which of that morning's inputs were actually known before the open?

- Entities: RELIANCE (INE002A01018)
- Period: 2024-06-04 · as-of: 2024-06-04 · answer: explanation
- Evidence: px_nse open/high/low/close that day; fii_dii_cash; events dated on or before the open; index move for context
- Steps: state the overnight cue -> show the stock's open gap and close -> list only evidence with known_at before 09:15 IST
- Forbidden: using a same-evening article as an intraday explanation; picking one cause without comparing the sector move
- Coverage: **partial** — prices, flows and events are held; no served move-attribution table
- Why: move->why is family 15 but real posts ask about a specific session, not a window

### RD-I-032 · why_moved · family 15 · `why_stock_moved`

**Q.** HDFC Bank jumped after its Q2FY26 result. Was the move in the numbers, the guidance, or the pre-result positioning?

- Entities: HDFCBANK (INE040A01034)
- Period: Q2FY26 · as-of: 2026-10-19 · answer: explanation
- Evidence: results_xbrl facts for the quarter; concall_facts guidance; px_nse pre/post result; fii_dii_cash
- Steps: show the surprise versus the prior quarter -> show the pre-result drift and post-result gap -> separate fact from positioning
- Forbidden: calling a move 'inline with results' without computing a surprise
- Coverage: **partial** — surprise needs a consensus series, which is not held; prior-quarter comparison is
- Why: retail confuses a good quarter with a good surprise

### RD-I-033 · why_moved · family 15 · `why_stock_moved`

**Q.** Why did Adani Power move 8% on a day when the power index was flat?

- Entities: ADANIPOWER (INE814H01029)
- Period: 2025-2026 · as-of: 2026-10-19 · answer: explanation
- Evidence: px_nse single-day return and volume; sector peers' returns; events that day
- Steps: compute the excess return versus peers -> list dated disclosures -> state NOT IN DATA if none
- Forbidden: inventing a news reason; ignoring that a stock-specific move can be flow-driven
- Coverage: **partial** — excess return is computable; the attribution layer is not served
- Why: single-stock idiosyncratic moves are the hardest and most asked

### RD-I-034 · why_moved · family 15 · `why_stock_moved`

**Q.** Infosys fell despite a revenue beat. Did the market react to margins, guidance, or the dollar-rupee assumption?

- Entities: INFY (INE009A01021)
- Period: Q2FY26 · as-of: 2026-10-19 · answer: explanation
- Evidence: results_xbrl revenue/margin; concall_facts guidance and FX assumption; px_nse; INR series if held
- Steps: compare revenue and margin surprises -> quote the guidance change -> check whether the FX assumption moved
- Forbidden: assuming the headline beat is what the market trades on
- Coverage: **partial** — no analyst consensus; guidance and margins are available
- Why: 'beat but fell' is a standard retail confusion

### RD-I-035 · why_moved · family 15 · `why_stock_moved`

**Q.** Tata Motors moved sharply around the demerger record date. How much of the move was the mechanical price adjustment?

- Entities: TMPV (INE155A01022)
- Period: demerger · as-of: 2026-10-19 · answer: fact
- Evidence: px_nse_adj cumulative factors; px_nse raw close; corporate_documents record date
- Steps: compare raw and adjusted close around the ex-date -> isolate the factor -> state the residual move
- Forbidden: calling the mechanical adjustment a market move
- Coverage: **yes** — adjustment factors make this arithmetically checkable
- Why: retail often mistakes an ex-date adjustment for a crash

### RD-I-036 · hold_sell · family NEW:position_decision · `hold_or_sell_position`

**Q.** I am holding Paytm at a large loss. Is there a fundamental case to average down, or is averaging just doubling a mistake?

- Entities: PAYTM (INE982J01020)
- Period: latest · as-of: 2026-10-19 · answer: explanation
- Evidence: results_xbrl revenue/PAT/cash; concall_facts guidance; px_nse drawdown; governance events
- Steps: state the current fundamentals vs the thesis at entry -> show what would have to improve -> give conditions, not a recommendation
- Forbidden: giving a personalised buy/sell call; treating average price as evidence about the business
- Coverage: **partial** — the data can frame the decision; position size and risk profile are not held
- Why: 'should I average' is everywhere and none of the banks cover it

### RD-I-037 · hold_sell · family NEW:position_decision · `hold_or_sell_position`

**Q.** Nykaa has been flat for years. What has actually improved in the business, and what would make the wait worth it?

- Entities: NYKAA (INE388Y01029)
- Period: FY24-FY26 · as-of: 2026-10-19 · answer: explanation
- Evidence: results_xbrl revenue/margin trend; annual_financials; concall_facts on contribution margin; px_nse
- Steps: show the multi-year revenue/margin path -> list the dated claims that have or have not been delivered -> state the swing factor
- Forbidden: using price stagnation as proof the business stagnated
- Coverage: **partial** — trends are held; a claim-tracking table is not
- Why: 'flat for years, should I hold' needs a delivery-vs-promise view

### RD-I-038 · hold_sell · family NEW:position_decision · `hold_or_sell_position`

**Q.** Ola Electric keeps making new lows. At what point does the loss of market share show up in the numbers, and is the cash runway the real risk?

- Entities: OLAELEC (INE0LXG01040)
- Period: FY25-FY26 · as-of: 2026-10-19 · answer: explanation
- Evidence: results_xbrl revenue/loss; annual_financials cash and debt; concall_facts market share and capex; px_nse
- Steps: show revenue and loss trend -> compute quarters of runway from held cash -> tie market-share claims to the reported volume
- Forbidden: mixing dispatches with retail registrations; assuming a fundraise is certain
- Coverage: **partial** — Vahan registrations are ingested only partially; company financials are held
- Why: the 'cut losses or wait' version of hold/sell

### RD-I-039 · hold_sell · family NEW:position_decision · `hold_or_sell_position`

**Q.** IRFC has run up a lot. Should I book profit, or is the lender's spread still improving?

- Entities: IRFC (INE053F01010)
- Period: FY26 · as-of: 2026-10-19 · answer: explanation
- Evidence: quarterly_financials NIM/spread; annual_financials ROE; px_nse valuation inputs; shareholding
- Steps: show the spread and ROE trend -> compare price with book -> state the two conditions that would change the answer
- Forbidden: calling a PSU lender expensive on PE without noting the book-value model
- Coverage: **partial** — spread and book are held; no valuation history
- Why: profit-booking questions on PSU lenders are constant

### RD-I-040 · hold_sell · family NEW:position_decision · `hold_or_sell_position`

**Q.** Swiggy's lock-in expiry is behind us. Did the supply actually hit the price, and what does the delivery business need to show next?

- Entities: SWIGGY (INE00H001014)
- Period: lock-in · as-of: 2026-10-19 · answer: fact
- Evidence: px_nse volume around the expiry; shareholding changes; results_xbrl contribution margin; concall_facts
- Steps: mark the expiry date -> compare volume and price before/after -> state the next operating metric that matters
- Forbidden: assuming all pre-IPO shareholders sold on one day
- Coverage: **partial** — volume and price are held; shareholder-level sales need SAST/bulk-deal data
- Why: lock-in expiry is a recurring IPO-adjacent question

### RD-I-041 · fii_dii_flow · family 4 · `fii_dii_flow_link`

**Q.** HDFC Bank fell through a month of heavy FII selling. How much of the fall lines up with market-wide FII outflow, and how much is stock-specific?

- Entities: HDFCBANK (INE040A01034)
- Period: 2025-2026 · as-of: 2026-10-19 · answer: explanation
- Evidence: fii_dii_cash daily market flows; px_nse returns; shareholding quarterly FII %; bank index return
- Steps: regress or compare monthly stock return with market FII flow -> subtract the bank-index move -> report the residual
- Forbidden: treating market-level FII flow as stock-level flow
- Coverage: **partial** — market flows daily + quarterly shareholding; no daily stock-level FII flow
- Why: retail links FII/DII flows to one stock, the data only supports a market-level read

### RD-I-042 · fii_dii_flow · family 4 · `fii_dii_flow_link`

**Q.** Reliance: did DII buying offset FII selling last quarter, and what did the shareholding pattern show?

- Entities: RELIANCE (INE002A01018)
- Period: last quarter · as-of: 2026-10-19 · answer: fact
- Evidence: shp_index/shareholding quarter ends; fii_dii_cash; px_nse
- Steps: compare FII and DII % across the last two quarters -> show the price path -> separate flow from ownership change
- Forbidden: adding FII and DII percentages as if they were the same holder
- Coverage: **yes** — quarterly ownership plus daily market flows answer it
- Why: the specific 'did DII absorb FII' question

### RD-I-043 · fii_dii_flow · family 4 · `fii_dii_flow_link`

**Q.** SBI: is the recent DII accumulation visible in the shareholding pattern, or only in the daily flow prints?

- Entities: SBIN (INE062A01020)
- Period: 2026 · as-of: 2026-10-19 · answer: fact
- Evidence: shareholding quarter-over-quarter; fii_dii_cash; px_nse
- Steps: compare DII % at the last two quarter ends -> check daily flow direction in the interim -> reconcile timing
- Forbidden: inferring a single stock's DII buy from the market aggregate
- Coverage: **partial** — daily flows are market-wide; ownership is quarterly and lagged
- Why: tests the resolution limit of flow data

### RD-I-044 · fii_dii_flow · family 4 · `fii_dii_flow_link`

**Q.** Larsen & Toubro: did the order inflow announcements or the institutional flows better explain the last two quarters of returns?

- Entities: LT (INE018A01030)
- Period: Q4FY26-Q2FY27 · as-of: 2026-10-19 · answer: explanation
- Evidence: concall_facts order inflow; corporate_documents order wins; fii_dii_cash; px_nse returns
- Steps: line up dated order wins and flows against monthly returns -> say which one has the tighter timing
- Forbidden: claiming attribution from two coincident time series
- Coverage: **partial** — event dates and flows exist; no event-study table for this stock
- Why: tests whether flows or fundamentals explain a large-cap's path

### RD-I-045 · fii_dii_flow · family 4 · `fii_dii_flow_link`

**Q.** ICICI Bank versus HDFC Bank: which one saw the bigger FII ownership change last year, and did the price gap follow it?

- Entities: ICICIBANK (INE090A01021), HDFCBANK (INE040A01034)
- Period: 1 year · as-of: 2026-10-19 · answer: ranking
- Evidence: shareholding quarter ends; px_nse relative return; fii_dii_cash
- Steps: compute FII % change for both -> compute relative return -> say whether ownership change led or followed price
- Forbidden: using today's weights on historical returns
- Coverage: **partial** — ownership is quarterly; no daily stock-level FII series
- Why: peer flow comparison in one question

### RD-I-046 · policy_impact · family 18 · `policy_impact_by_company`

**Q.** If the budget raises tobacco duty again, how much of ITC's revenue and profit is actually exposed, and what did the last duty hike do to volumes?

- Entities: ITC (INE154A01025)
- Period: last 3 budgets · as-of: 2026-10-19 · answer: explanation
- Evidence: policy_events with amount and effective date; annual_financials segment revenue; concall_facts volume commentary; px_nse event windows
- Steps: show the last duty changes with dates -> show cigarette revenue share -> measure the volume/price response around each
- Forbidden: assuming full pass-through; using a pre-budget rumour as policy
- Coverage: **partial** — policy events are held; no segment-level tax incidence table
- Why: budget-to-stock transmission is asked every February

### RD-I-047 · policy_impact · family 18 · `policy_impact_by_company`

**Q.** The defence budget line grew again. Which of HAL, BEL and Mazagon Dock has the revenue visibility that matches its valuation?

- Entities: HAL (INE066F01020), BEL (INE263A01024), MAZDOCK (INE249Z01020)
- Period: FY27 budget · as-of: 2026-10-19 · answer: ranking
- Evidence: policy_events defence allocations; concall_facts order book; results_xbrl revenue; px_nse
- Steps: map the budget line to the order pipeline disclosed by each -> compute backlog cover -> rank
- Forbidden: treating a budget allocation as a company order; ignoring multi-year execution
- Coverage: **partial** — budget events and order-book text are held; no structured pipeline table
- Why: budget headline -> defence stock is a top retail pattern

### RD-I-048 · policy_impact · family 18 · `policy_impact_by_company`

**Q.** Rail capex was front-loaded this year. Does that show up first in RVNL's revenue or in IRFC's loan book, and with what lag?

- Entities: RVNL (INE415G01027), IRFC (INE053F01010)
- Period: FY26-FY27 · as-of: 2026-10-19 · answer: explanation
- Evidence: policy_events rail allocation; results_xbrl revenue and loan growth; concall_facts execution timeline; px_nse
- Steps: state the capex number -> show each company's quarterly response -> compute the lag between allocation and revenue/loan growth
- Forbidden: assuming capex is spent in the year it is budgeted
- Coverage: **partial** — no capex-to-company exposure map; the lag is derivable for a few names
- Why: the railway capex chain is asked as a two-company question

### RD-I-049 · policy_impact · family 18 · `policy_impact_by_company`

**Q.** A higher import duty on solar modules: who benefits between Waaree and Premier Energies, and what happens to the project developers' cost?

- Entities: WAAREEENER (INE377N01017), PREMIERENE (INE0BS701011), NTPCGREEN (INE0ONG01011)
- Period: duty change · as-of: 2026-10-19 · answer: explanation
- Evidence: policy_events duty/tariff with dates; concall_facts capacity and module vs cell mix; annual_financials margin
- Steps: state the duty and effective date -> map each company's module/cell mix -> trace the cost into a developer's capex
- Forbidden: assuming a duty protects everyone equally; ignoring the ALMM list
- Coverage: **partial** — policy events and product mix text exist; no duty-exposure table
- Why: one policy, winners and losers in the same chain

### RD-I-050 · policy_impact · family 18 · `policy_impact_by_company`

**Q.** Rubber prices and an import-duty change hit tyre makers differently. Which of Apollo, MRF and CEAT has the best pass-through history?

- Entities: APOLLOTYRE (INE438A01022), MRF (INE883A01011), CEATLTD (INE482A01020)
- Period: FY24-FY26 · as-of: 2026-10-19 · answer: ranking
- Evidence: concall_facts price hikes and raw-material commentary; annual_financials gross margin; policy_events duty; commodity series if held
- Steps: list dated price hikes -> align with rubber cost moves -> compare margin recovery per company
- Forbidden: comparing margins across different accounting periods; assuming a hike sticks
- Coverage: **partial** — no commodity series in store; commentary and margins are held
- Why: input-cost plus policy in one question, a real retail habit

### RD-I-051 · promoter_pledge · family 14 · `promoter_pledge_sale`

**Q.** Vedanta: how has promoter pledge moved over the last four quarters, and does the dividend policy depend on it?

- Entities: VEDL (INE205A01025)
- Period: last 4 quarters · as-of: 2026-10-19 · answer: fact
- Evidence: shp_index/shareholding pledge and encumbered %; corporate_documents dividend announcements; annual_financials cash
- Steps: show the pledge trend -> show dividend outflows -> state whether the parent's servicing needs are disclosed
- Forbidden: reading a pledge release as a promoter purchase
- Coverage: **partial** — quarterly pledge is held where shareholding filings are; coverage is thin
- Why: pledge + dividend linkage is a standard governance ask

### RD-I-052 · promoter_pledge · family 14 · `promoter_pledge_sale`

**Q.** Jaiprakash Power: is the promoter pledge rising alongside the debt, and what did the auditor say about going concern?

- Entities: JPPOWER (INE351F01018)
- Period: FY24-FY26 · as-of: 2026-10-19 · answer: fact
- Evidence: shareholding pledge; annual_financials debt; ar_facts auditor opinion/going concern; bse_announcements
- Steps: show pledge and net debt together -> quote the auditor's opinion with the year -> say which one moved first
- Forbidden: treating a qualified opinion as a fraud finding
- Coverage: **partial** — auditor opinion is in ar_facts; a structured governance table is not
- Why: pledge + going concern is what retail means by 'red flag'

### RD-I-053 · promoter_pledge · family 14 · `promoter_pledge_sale`

**Q.** Vodafone Idea: did the promoter group raise its stake through the preferential issue, and what did that do to the free float?

- Entities: IDEA (INE669E01016)
- Period: 2024-2026 · as-of: 2026-10-19 · answer: fact
- Evidence: shareholding quarter ends; corporate_documents preferential issue; px_nse
- Steps: show promoter % before and after -> compute the free-float change -> flag any conversion of partly paid shares
- Forbidden: treating a conversion as a fresh purchase
- Coverage: **yes** — quarterly ownership plus issue filings answer it
- Why: dilution and float questions are frequent

### RD-I-054 · promoter_pledge · family 14 · `promoter_pledge_sale`

**Q.** IRB Infrastructure: has promoter pledge fallen with the asset monetisation, and how much of the debt is now at the holdco?

- Entities: IRB (INE821I01022)
- Period: FY24-FY26 · as-of: 2026-10-19 · answer: fact
- Evidence: shareholding pledge; annual_financials debt; concall_facts asset sales; corporate_documents
- Steps: show pledge and debt trend -> list monetisation events -> separate project debt from holdco debt if disclosed
- Forbidden: netting project debt against the parent without saying so
- Coverage: **partial** — consolidated debt is held; the holdco split is text-only
- Why: infra pledge release is a common 'is it clean now' question

### RD-I-055 · promoter_pledge · family 14 · `promoter_pledge_sale`

**Q.** Which large-cap had the biggest promoter stake sale in the last year, and did the stock absorb it?

- Entities: TITAN (INE280A01028), DMART (INE192R01011), TRENT (INE849A01020), PIDILITIND (INE318A01026)
- Period: last 1 year · as-of: 2026-10-19 · answer: ranking
- Evidence: shareholding changes; SAST/bulk-block deals if present in announcements; px_nse volume around the dates
- Steps: compute promoter % change per name -> find the deal date -> show the price/volume response
- Forbidden: ranking by rumour; conflating an inter-se transfer with a sale
- Coverage: **partial** — quarterly ownership is held; deal-level prints are incomplete
- Why: stake-sale absorption is asked as a cross-stock ranking

### RD-I-056 · results_day · family 9 · `earnings_reaction_drift`

**Q.** Infosys Q2FY26: what should I watch in the print, and which line item explained the market's reaction?

- Entities: INFY (INE009A01021)
- Period: Q2FY26 · as-of: 2026-10-19 · answer: list
- Evidence: results_xbrl revenue/margin/EPS; concall_facts guidance; deck_figures; px_nse reaction
- Steps: list the three lines that moved -> compare with guidance -> map to the post-result move
- Forbidden: using the headline PAT without the margin and guidance
- Coverage: **yes** — XBRL + concall + deck + price cover it
- Why: 'what to watch in results' is a recurring pre-earnings post

### RD-I-057 · results_day · family 9 · `earnings_reaction_drift`

**Q.** TCS: did the deal-win total convert into revenue this quarter, or is the book still growing faster than billing?

- Entities: TCS (INE467B01029)
- Period: Q2FY26 · as-of: 2026-10-19 · answer: explanation
- Evidence: concall_facts deal wins/Tcv; results_xbrl revenue; deck_figures; prior quarters
- Steps: show TCV and revenue growth side by side over four quarters -> compute the conversion lag
- Forbidden: comparing TCV with revenue one-to-one
- Coverage: **yes** — both are extracted; the lag is arithmetic
- Why: deal-book conversion is a real investor question we do not template

### RD-I-058 · results_day · family 9 · `earnings_reaction_drift`

**Q.** HDFC Bank Q2FY26: was the NIM expansion real or a one-off treasury gain, and what did management guide?

- Entities: HDFCBANK (INE040A01034)
- Period: Q2FY26 · as-of: 2026-10-19 · answer: explanation
- Evidence: results_xbrl interest income/expense, other income; concall_facts NIM guidance; deck
- Steps: separate other income from core NIM -> compare with the prior quarter -> quote the guidance
- Forbidden: reading total income growth as NIM expansion
- Coverage: **partial** — XBRL gives the lines; a bank-specific NIM table is not built
- Why: bank result decomposition is asked every quarter

### RD-I-059 · results_day · family 9 · `earnings_reaction_drift`

**Q.** Maruti: did the quarter's volume growth come from mix or discounts, and what does that say about the margin?

- Entities: MARUTI (INE585B01010)
- Period: Q2FY26 · as-of: 2026-10-19 · answer: explanation
- Evidence: results_xbrl revenue/EBITDA; concall_facts discounts and mix; monthly volume disclosures if held
- Steps: separate volume, price and mix -> compute realisation per unit -> tie to margin
- Forbidden: using revenue growth as volume growth
- Coverage: **partial** — no monthly volume table; quarterly revenue and commentary exist
- Why: auto result decomposition with a mix question

### RD-I-060 · results_day · family 9 · `earnings_reaction_drift`

**Q.** Reliance: which segment actually drove the quarter, and did the market react to the consolidated or the segment story?

- Entities: RELIANCE (INE002A01018)
- Period: Q2FY26 · as-of: 2026-10-19 · answer: explanation
- Evidence: results_xbrl segment facts; concall_facts segment commentary; px_nse reaction
- Steps: show segment EBITDA change -> identify the largest contributor -> compare with the post-result move
- Forbidden: using consolidated PAT when the question is segment-level
- Coverage: **partial** — segment facts are extracted unevenly; consolidated XBRL is solid
- Why: conglomerate segment attribution is a standard ask

### RD-I-061 · peer_compare · family 8 · `valuation_vs_peers`

**Q.** Tata Motors PV versus Mahindra: which has the better EV mix and margin, and does the market already pay for it?

- Entities: TMPV (INE155A01022), M&M (INE101A01026)
- Period: Q2FY26 · as-of: 2026-10-19 · answer: ranking
- Evidence: results_xbrl revenue/EBITDA; concall_facts EV volumes; px_nse market cap; annual_financials
- Steps: line up EV share and margin -> compute the valuation gap -> say which part is mix and which is execution
- Forbidden: comparing a demerged entity's numbers with its pre-demerger history without adjustment
- Coverage: **partial** — no EV-volume structured table; commentary and revenue are held
- Why: the demerged PV entity makes peer comparison newly hard

### RD-I-062 · peer_compare · family 8 · `valuation_vs_peers`

**Q.** HDFC Bank versus ICICI Bank on NIM, ROA and credit cost: which is the cleaner compounder from here?

- Entities: HDFCBANK (INE040A01034), ICICIBANK (INE090A01021)
- Period: Q2FY26 · as-of: 2026-10-19 · answer: ranking
- Evidence: results_xbrl; concall_facts; annual_financials ROA; px_nse valuation
- Steps: compute the three ratios for both -> show the trend over four quarters -> rank with reasons
- Forbidden: comparing at different consolidation bases; ignoring the merger distortion in HDFC Bank's history
- Coverage: **partial** — raw lines are held; a normalised bank-metrics view is not
- Why: the most-asked bank pair in Indian retail

### RD-I-063 · peer_compare · family 8 · `valuation_vs_peers`

**Q.** DMart versus Trent: which is growing revenue per store faster, and is the data even comparable?

- Entities: DMART (INE192R01011), TRENT (INE849A01020)
- Period: FY24-FY26 · as-of: 2026-10-19 · answer: explanation
- Evidence: annual_financials revenue; concall_facts store additions; deck_figures if store counts are printed
- Steps: extract store counts by year -> compute revenue per store -> flag where the disclosure basis differs
- Forbidden: dividing total revenue by a store count from a different date
- Coverage: **partial** — store counts are text/print facts, not a table
- Why: retail loves revenue-per-store comparisons we cannot serve cleanly

### RD-I-064 · peer_compare · family 8 · `valuation_vs_peers`

**Q.** Polycab versus KEI: which has the better working-capital cycle, and does the margin gap justify the valuation gap?

- Entities: POLYCAB (INE455K01017), KEI (INE878B01027)
- Period: FY26 · as-of: 2026-10-19 · answer: ranking
- Evidence: annual_financials receivables/inventory/payables; results_xbrl margin; px_nse
- Steps: compute the cash-conversion cycle for both -> compare margin -> show the multiple gap
- Forbidden: comparing a standalone with a consolidated entity
- Coverage: **partial** — balance-sheet lines are in annual_financials; the cycle is derivable
- Why: cable peers are a favourite comparison

### RD-I-065 · peer_compare · family 8 · `valuation_vs_peers`

**Q.** Sun Pharma versus Cipla: how much of the revenue is US, and which one is more exposed to a price-erosion shock?

- Entities: SUNPHARMA (INE044A01036), CIPLA (INE059A01026)
- Period: FY26 · as-of: 2026-10-19 · answer: ranking
- Evidence: ar_facts segment/geography; annual_financials; concall_facts US commentary; deck
- Steps: extract the US revenue share for both -> compare the product mix -> rank the exposure
- Forbidden: using total exports as US revenue
- Coverage: **partial** — geographic splits are extracted unevenly across years
- Why: pharma geographic exposure is a standard fundamental question

### RD-I-066 · valuation · family 2 · `valuation_vs_peers`

**Q.** DMart still trades at a high PE. What growth rate is the market assuming, and what has the company actually delivered?

- Entities: DMART (INE192R01011)
- Period: FY24-FY26 · as-of: 2026-10-19 · answer: explanation
- Evidence: px_nse market cap; annual_financials EPS/revenue growth; results_xbrl recent quarters
- Steps: compute trailing PE -> show realised revenue/EPS growth -> state the gap between assumed and delivered
- Forbidden: using a forward PE that is not in the data; comparing PE across sectors
- Coverage: **partial** — PE and growth are computable; no implied-growth model is served
- Why: 'why is it so expensive' is a top retail question

### RD-I-067 · valuation · family 2 · `valuation_vs_peers`

**Q.** Trent at this multiple: is the store-add run-rate enough to grow into it, or does the market need margin expansion too?

- Entities: TRENT (INE849A01020)
- Period: FY26 · as-of: 2026-10-19 · answer: explanation
- Evidence: px_nse; annual_financials revenue/margin; concall_facts store additions; deck
- Steps: show the growth needed at the current multiple -> split it into store adds and same-store growth -> say which one is behind
- Forbidden: assuming new stores add revenue immediately
- Coverage: **partial** — no same-store-sales series; store adds are text facts
- Why: retail valuation questions are always growth-decomposition questions

### RD-I-068 · valuation · family 2 · `valuation_vs_peers`

**Q.** Eternal (ex-Zomato) on EV/sales: what does the multiple imply about the path to durable profit, and which segment has to carry it?

- Entities: ETERNAL (INE758T01015)
- Period: FY26 · as-of: 2026-10-19 · answer: explanation
- Evidence: px_nse market cap; results_xbrl revenue/EBITDA by segment where disclosed; concall_facts contribution margin
- Steps: compute EV/sales -> show segment revenue mix and margin -> state the margin needed to justify the multiple
- Forbidden: applying a PE to a company whose profit is not yet stable
- Coverage: **partial** — segment disclosures are uneven; market cap and revenue are held
- Why: new-age valuation questions are asked in EV/sales terms

### RD-I-069 · valuation · family 2 · `valuation_vs_peers`

**Q.** IRFC trades on P/B rather than PE. What ROE would justify its current multiple, and how does it compare with REC and PFC?

- Entities: IRFC (INE053F01010), RECLTD (INE020B01018), PFC (INE134E01011)
- Period: FY26 · as-of: 2026-10-19 · answer: ranking
- Evidence: px_nse market cap; annual_financials book equity/ROE; quarterly_financials spread
- Steps: compute P/B and ROE for all three -> show the ROE needed at the current multiple -> rank the gap
- Forbidden: comparing a lender's P/B with a manufacturer's PE
- Coverage: **partial** — P/B and ROE are computable; no sector-relative valuation table
- Why: PSU lender valuation is asked in P/B terms, not PE

### RD-I-070 · valuation · family 2 · `valuation_vs_peers`

**Q.** Paytm after the turnaround: is it still a loss-making story, and what metric should the valuation be judged on now?

- Entities: PAYTM (INE982J01020)
- Period: FY26 · as-of: 2026-10-19 · answer: explanation
- Evidence: results_xbrl revenue/EBITDA/PAT; concall_facts profitability guidance; px_nse
- Steps: show the profit path -> say whether trailing earnings are positive -> pick the metric the data supports
- Forbidden: using trailing PE when earnings are negative; ignoring one-off gains
- Coverage: **partial** — the P&L path is held; no analyst-style metric selection
- Why: retail argues about which metric applies to a turnaround

### RD-I-071 · index_flow · family 4 · `index_inclusion_rebalance`

**Q.** When Eternal entered the Nifty 50, how much passive buying did that imply, and did the stock move before or after the effective date?

- Entities: ETERNAL (INE758T01015)
- Period: 2025 · as-of: 2026-10-19 · answer: fact
- Evidence: master_companies is_nifty50 flag; events/announcements for the index change; px_nse volume and returns around it
- Steps: find the announcement and effective dates -> estimate flow from index weight x AUM if AUM is held -> show the price/volume path
- Forbidden: inventing an AUM number; treating the announcement date as the effective date
- Coverage: **partial** — membership flags are current-only; no index-membership history or AUM table
- Why: index inclusion is a top passive-flow question

### RD-I-072 · index_flow · family 4 · `index_inclusion_rebalance`

**Q.** Jio Financial was added to the Nifty 50 soon after listing. Did the index flow arrive before the stock's first big move?

- Entities: JIOFIN (INE758E01017)
- Period: 2023-2025 · as-of: 2026-10-19 · answer: fact
- Evidence: events index changes; px_nse volume/returns; master_companies flags
- Steps: mark the likely inclusion window -> compare volume and return before/after -> state the identification limit
- Forbidden: asserting causality from one event
- Coverage: **partial** — no membership history table; prices are held
- Why: recent-inclusion questions are common and the data gap is sharp

### RD-I-073 · index_flow · family 4 · `index_inclusion_rebalance`

**Q.** HAL's weight in the Nifty 50 has changed with the stock. How much of the trading volume on rebalance days is index-driven?

- Entities: HAL (INE066F01020)
- Period: 2024-2026 · as-of: 2026-10-19 · answer: explanation
- Evidence: px_nse volume around rebalance dates; events; no weight history
- Steps: list rebalance dates -> compare close-auction volume with the 20-day median -> state the estimate's uncertainty
- Forbidden: presenting a volume spike as proof of passive flow
- Coverage: **partial** — volume is held; weights and AUM are not
- Why: the 'rebalance-day volume' question has no clean answer today

### RD-I-074 · index_flow · family 4 · `index_inclusion_rebalance`

**Q.** If DMart drops out of the Nifty 50, what would the forced selling be, and how has the stock behaved around past exclusion scares?

- Entities: DMART (INE192R01011)
- Period: 2025-2026 · as-of: 2026-10-19 · answer: explanation
- Evidence: master_companies flags; px_nse; events
- Steps: state the current membership status -> show past drawdowns around review dates -> give the flow estimate only if AUM is held
- Forbidden: predicting exclusion; quoting a weight without a date
- Coverage: **partial** — membership is a current flag, not a time series
- Why: exclusion fear is a recurring retail panic

### RD-I-075 · index_flow · family 4 · `index_inclusion_rebalance`

**Q.** Trent versus the Nifty consumption index: did the stock's weight increase come from price or from index reconstitution?

- Entities: TRENT (INE849A01020)
- Period: 2024-2026 · as-of: 2026-10-19 · answer: explanation
- Evidence: px_nse relative return; events; master flags
- Steps: decompose relative return -> check for reconstitution events -> state which part is passive
- Forbidden: assuming weight changes are always reconstitution
- Coverage: **no** — no index weight history at all; only current flags
- Why: the data cannot separate price drift from reconstitution today

## International value patterns, translated

### RD-N-001 · moat_durability · family 17 · `moat_competitive_advantage`

**Q.** Asian Paints: over ten years, has gross margin been stable enough to prove pricing power, or did it just track crude?

- Entities: ASIANPAINT (INE021A01026)
- Period: FY15-FY26 · as-of: 2026-10-19 · answer: explanation
- Evidence: annual_financials revenue/EBITDA/gross margin; ar_facts raw-material note; concall_facts price-hike commentary; px_nse
- Steps: plot gross margin by year -> mark crude moves -> show whether price hikes recovered the margin -> state what the record supports
- Forbidden: calling a margin recovery pricing power without a volume check
- Coverage: **partial** — margins and commentary are held; no input-cost series or volume table
- Why: the 'is the moat real' question is framed as a margin test, not a lookup

### RD-N-002 · moat_durability · family 17 · `moat_competitive_advantage`

**Q.** Pidilite: is the adhesives moat earning a premium through price, or is volume growth doing all the work?

- Entities: PIDILITIND (INE318A01026)
- Period: FY20-FY26 · as-of: 2026-10-19 · answer: explanation
- Evidence: results_xbrl revenue/volume commentary; concall_facts realisation vs volume; annual_financials margin
- Steps: separate realisation from volume each year -> show margin behaviour -> state where the pricing power sits
- Forbidden: treating revenue growth as proof of pricing power
- Coverage: **partial** — volume is discussed in calls, not structured per quarter
- Why: the volume-vs-price decomposition is standard in value forums and absent from our families

### RD-N-003 · moat_durability · family 17 · `moat_competitive_advantage`

**Q.** Nestle India: is the last five years' growth from volume or from price and mix, and does that change the moat case?

- Entities: NESTLEIND (INE239A01024)
- Period: FY20-FY26 · as-of: 2026-10-19 · answer: explanation
- Evidence: annual_financials revenue; concall_facts volume/price commentary; deck_figures if printed
- Steps: extract the stated volume growth by year -> subtract from revenue growth -> show the residual price/mix
- Forbidden: assuming a branded FMCG always grows on volume
- Coverage: **partial** — commentary is qualitative; the deck sometimes prints the split
- Why: volume-price decomposition is a recurring value-investor ask

### RD-N-004 · moat_durability · family 17 · `moat_competitive_advantage`

**Q.** Titan: is the jewellery segment's margin a brand premium or a gold-leasing artefact, and how would a gold spike change it?

- Entities: TITAN (INE280A01028)
- Period: FY24-FY26 · as-of: 2026-10-19 · answer: explanation
- Evidence: results_xbrl segment margin; ar_facts gold-on-lease note; concall_facts studded mix; px_nse
- Steps: separate studded vs plain mix -> show the margin per mix -> explain the leasing effect -> state the gold-price sensitivity
- Forbidden: reading a one-quarter margin as structural; ignoring inventory gains
- Coverage: **partial** — segment and notes are held; no gold series or lease schedule
- Why: quality-of-margin questions are asked in accounting terms

### RD-N-005 · moat_durability · family 17 · `moat_competitive_advantage`

**Q.** Hindustan Unilever: has D2C competition actually taken detergent share, and what does the volume trend say?

- Entities: HINDUNILVR (INE030A01027)
- Period: FY22-FY26 · as-of: 2026-10-19 · answer: explanation
- Evidence: annual_financials revenue; concall_facts market share statements; results_xbrl volume growth
- Steps: show the volume trend -> quote the dated share claims -> compare with revenue growth
- Forbidden: accepting management's 'stable share' line without the volume number
- Coverage: **partial** — no third-party share series; management claims are dated text
- Why: disruption-vs-incumbent is a core value-forum question

### RD-N-006 · roic_wacc · family 17 · `fundamental_health_check`

**Q.** Hindalco: what has ROIC been through the cycle versus cost of capital, and does the aluminium or the copper business carry it?

- Entities: HINDALCO (INE038A01020)
- Period: FY16-FY26 · as-of: 2026-10-19 · answer: fact
- Evidence: annual_financials EBIT/debt/equity; ar_facts segment capital employed; results_xbrl; cost-of-capital inputs are not held
- Steps: compute ROIC per segment -> compare with a stated WACC assumption -> show the spread through the cycle
- Forbidden: using a single-year ROIC as the through-cycle number; inventing a WACC
- Coverage: **partial** — ROIC arithmetic is possible from annual_financials; WACC needs a risk-free series we do not hold
- Why: value investors start every thesis with ROIC-WACC and no family asks it

### RD-N-007 · roic_wacc · family 17 · `fundamental_health_check`

**Q.** JSW Steel: the last capex round was large. What incremental ROIC has it earned so far, and how far is it from the cost of capital?

- Entities: JSWSTEEL (INE019A01038)
- Period: FY22-FY26 · as-of: 2026-10-19 · answer: fact
- Evidence: annual_financials capex/gross block/EBIT; quarterly_financials; concall_facts project returns
- Steps: compute incremental EBIT over incremental capital -> compare with the company's own stated hurdle -> state the gap
- Forbidden: mixing greenfield CWIP with operating assets; annualising a part-year
- Coverage: **partial** — capex and EBIT are held; the segment asset base is uneven
- Why: capex-return scepticism is the single most common value-forum hook

### RD-N-008 · roic_wacc · family 17 · `fundamental_health_check`

**Q.** Polycab: does the ROIC still clear the cost of capital after the working-capital build, and what would a demand slowdown do to it?

- Entities: POLYCAB (INE455K01017)
- Period: FY22-FY26 · as-of: 2026-10-19 · answer: fact
- Evidence: annual_financials receivables/inventory/EBIT; results_xbrl; concall_facts demand
- Steps: compute invested capital including the WC build -> compute ROIC -> stress it with a 10% revenue fall
- Forbidden: excluding working capital from invested capital
- Coverage: **partial** — the components are held; no ready ROIC series
- Why: the working-capital-adjusted ROIC question is absent from our banks

### RD-N-009 · roic_wacc · family 17 · `fundamental_health_check`

**Q.** ABB India: the margin is at a record. Is the ROIC being earned on new capacity or on a cyclical order book?

- Entities: ABB (INE117A01022)
- Period: FY22-FY26 · as-of: 2026-10-19 · answer: fact
- Evidence: annual_financials revenue/margin/capital; concall_facts order book and capacity; results_xbrl
- Steps: split the margin into price, mix and utilisation -> relate to capex -> say what part is cyclical
- Forbidden: treating peak margin as permanent in the ROIC calculation
- Coverage: **partial** — no order-book table or capacity series
- Why: peak-margin quality is a standard international discussion

### RD-N-010 · roic_wacc · family 17 · `fundamental_health_check`

**Q.** Cummins India: after the emission-norm change, did the pricing gain lift ROIC, or did it go into warranty and R&D?

- Entities: CUMMINSIND (INE298A01020)
- Period: FY20-FY26 · as-of: 2026-10-19 · answer: fact
- Evidence: annual_financials EBIT/R&D; results_xbrl; concall_facts price and cost; ar_facts
- Steps: show the margin lift -> trace where it went in the cost lines -> compute ROIC over the period
- Forbidden: attributing the whole margin lift to pricing
- Coverage: **partial** — R&D line is sometimes extracted; not consistently
- Why: regulation-driven pricing gain is a real analytical pattern

### RD-N-011 · capital_allocation · family 17 · `capital_allocation`

**Q.** ITC: between dividends and FMCG reinvestment, which one has earned the better return, and what does the last five years say?

- Entities: ITC (INE154A01025)
- Period: FY20-FY26 · as-of: 2026-10-19 · answer: explanation
- Evidence: annual_financials dividends/capex/segment revenue/EBITDA; ar_facts; concall_facts FMCG margin
- Steps: compute cash returned vs cash retained -> compute FMCG incremental margin -> compare with the cigarette cash engine
- Forbidden: calling a high dividend 'good allocation' without the return on retained capital
- Coverage: **partial** — dividends and segments are held; no capital-allocation ledger
- Why: the dividend-vs-reinvest debate is a staple of dividend/value subs

### RD-N-012 · capital_allocation · family 17 · `capital_allocation`

**Q.** Coal India: is the payout policy starving the business of capex, or is the capex not earning its keep?

- Entities: COALINDIA (INE522F01014)
- Period: FY20-FY26 · as-of: 2026-10-19 · answer: explanation
- Evidence: annual_financials capex/dividends/FCF; results_xbrl; corporate_documents dividend declarations
- Steps: show capex vs depreciation -> show dividend vs FCF -> compute return on the capex programme
- Forbidden: treating a PSU payout as automatically sustainable
- Coverage: **partial** — capex and dividends are held; project-level returns are not
- Why: PSU cash-allocation scepticism is common on both Indian and value forums

### RD-N-013 · capital_allocation · family 17 · `capital_allocation`

**Q.** HDFC Bank has never bought back stock. Is retained capital earning above the cost of equity, and should the payout change?

- Entities: HDFCBANK (INE040A01034)
- Period: FY20-FY26 · as-of: 2026-10-19 · answer: explanation
- Evidence: annual_financials ROE/book equity; results_xbrl; shareholding; no buyback table
- Steps: compute ROE trend -> compare with a stated cost of equity -> show capital consumption per unit of loan growth
- Forbidden: recommending a buyback without the capital-adequacy constraint
- Coverage: **partial** — ROE is held; cost of equity and capital adequacy are not
- Why: bank capital-return questions are frequent in Bogleheads-style threads

### RD-N-014 · capital_allocation · family 17 · `capital_allocation`

**Q.** Bajaj Finance: how much dilution has funded the growth, and is per-share value growing as fast as the loan book?

- Entities: BAJFINANCE (INE296A01032)
- Period: FY20-FY26 · as-of: 2026-10-19 · answer: fact
- Evidence: annual_financials shares/EPS/AUM; corporate_documents QIP/preferential issues; results_xbrl
- Steps: compute share count growth -> compare AUM growth with EPS growth -> state the dilution drag
- Forbidden: using post-dilution EPS with pre-dilution share count
- Coverage: **partial** — share count changes are in filings; a clean dilution series is not
- Why: growth-vs-dilution is a core international value test

### RD-N-015 · capital_allocation · family 17 · `capital_allocation`

**Q.** Tata Motors PV: where exactly is the EV and JLR capex going, and what return has the last cycle produced?

- Entities: TMPV (INE155A01022)
- Period: FY22-FY26 · as-of: 2026-10-19 · answer: explanation
- Evidence: annual_financials capex/gross block/EBIT; concall_facts JLR and EV spend; results_xbrl
- Steps: separate JLR from India PV -> show capex and EBIT by entity if disclosed -> compute the return on the last cycle
- Forbidden: mixing the pre-demerger consolidated numbers with the new PV entity
- Coverage: **partial** — demerger makes history non-comparable; entity-level capex is text
- Why: post-demerger capital allocation is a fresh question nobody can answer yet

### RD-N-016 · accounting_red_flags · family 14 · `accounting_red_flags`

**Q.** Adani Enterprises: do receivables and inventory growth run ahead of revenue, and what does the cash-conversion ratio say?

- Entities: ADANIENT (INE423A01024)
- Period: FY22-FY26 · as-of: 2026-10-19 · answer: fact
- Evidence: annual_financials receivables/inventory/revenue/CFO; ar_facts working-capital notes; results_xbrl
- Steps: compute receivable and inventory days by year -> compute CFO/PAT -> flag the divergence
- Forbidden: calling a divergence fraud; ignoring a deliberate business mix change
- Coverage: **partial** — annual balance-sheet lines are held; a red-flag scoring table is not
- Why: forensic accounting questions are asked as ratio tests

### RD-N-017 · accounting_red_flags · family 14 · `accounting_red_flags`

**Q.** Vedanta: the parent pays dividends while carrying debt. Is the cash actually upstreamed from subsidiaries, and what do the related-party notes say?

- Entities: VEDL (INE205A01025)
- Period: FY22-FY26 · as-of: 2026-10-19 · answer: fact
- Evidence: annual_financials dividends/debt; ar_facts related-party and dividend notes; shareholding
- Steps: show dividends paid vs consolidated FCF -> quote the related-party note -> say how the upstreaming works
- Forbidden: treating consolidated cash as freely available at the parent
- Coverage: **partial** — notes are extracted as facts, not as a structured related-party table
- Why: holdco cash-upstreaming is a repeated governance question

### RD-N-018 · accounting_red_flags · family 14 · `accounting_red_flags`

**Q.** Vodafone Idea: how are the spectrum liabilities accounted for, and do the interest and amortisation assumptions flatter the loss?

- Entities: IDEA (INE669E01016)
- Period: FY24-FY26 · as-of: 2026-10-19 · answer: explanation
- Evidence: annual_financials interest/amortisation; ar_facts spectrum and going-concern notes; results_xbrl
- Steps: show the interest and amortisation lines -> compare with the cash paid -> quote the auditor's going-concern paragraph
- Forbidden: comparing accounting interest with cash interest as if equal
- Coverage: **partial** — the notes exist; the deferred-spectrum schedule is not structured
- Why: accounting-quality questions about leveraged telecom are frequent

### RD-N-019 · accounting_red_flags · family 14 · `accounting_red_flags`

**Q.** Reliance Power: how much of the balance sheet is CWIP and capitalised interest, and when does it start depreciating?

- Entities: RPOWER (INE614G01033)
- Period: FY22-FY26 · as-of: 2026-10-19 · answer: fact
- Evidence: annual_financials CWIP/gross block/interest; ar_facts capitalisation policy; results_xbrl
- Steps: show CWIP as a share of gross block -> quote the capitalisation policy -> state the depreciation step-up risk
- Forbidden: treating CWIP as an earning asset
- Coverage: **partial** — CWIP is in the balance sheet; policy text extraction is patchy
- Why: capitalised-interest questions are a classic value-forum forensic

### RD-N-020 · accounting_red_flags · family 14 · `accounting_red_flags`

**Q.** Yes Bank: are provisions keeping pace with the stressed book, and how much of the recovery is write-back rather than operating profit?

- Entities: YESBANK (INE528G01035)
- Period: FY22-FY26 · as-of: 2026-10-19 · answer: fact
- Evidence: results_xbrl provisions/PAT; annual_financials; concall_facts recovery commentary; bse_announcements
- Steps: separate operating profit from write-backs -> compute provision coverage -> flag where PAT depends on recovery
- Forbidden: presenting a recovery-led PAT as core earnings
- Coverage: **partial** — the P&L lines are held; a bank asset-quality table is not
- Why: recovery-quality questions are central to beaten-down banks

### RD-N-021 · management_credibility · family 3 · `guidance_vs_delivery`

**Q.** Tata Motors: JLR margin guidance has moved every year. What was promised, what was delivered, and what is the current gap?

- Entities: TMPV (INE155A01022)
- Period: FY22-FY26 · as-of: 2026-10-19 · answer: explanation
- Evidence: concall_facts guidance items by quarter; results_xbrl EBIT margin; deck_figures; px_nse
- Steps: list each guidance statement with its call date -> line up the realised margin -> compute the miss or beat
- Forbidden: quoting only the latest promise; using a mid-year revision as the original
- Coverage: **partial** — guidance text is extracted, but there is no guidance-vs-actual table
- Why: guidance-slippage tracking is the heart of management-credibility threads

### RD-N-022 · management_credibility · family 3 · `guidance_vs_delivery`

**Q.** Dixon: the margin guidance has been repeatedly cut. Which call first lowered it, and what did the market do after?

- Entities: DIXON (INE935N01020)
- Period: FY23-FY26 · as-of: 2026-10-19 · answer: date
- Evidence: concall_facts guidance; results_xbrl margin; px_nse post-call returns
- Steps: order the guidance statements -> find the first cut -> measure the return over the next five sessions
- Forbidden: using the final guidance as the original one
- Coverage: **partial** — no post-call event-study table; the two inputs exist
- Why: asks when credibility broke, not just whether it did

### RD-N-023 · management_credibility · family 3 · `guidance_vs_delivery`

**Q.** IREDA: loan-growth guidance versus actual book growth. Has the company consistently beaten its own number?

- Entities: IREDA (INE202E01016)
- Period: FY24-FY26 · as-of: 2026-10-19 · answer: fact
- Evidence: concall_facts guidance; quarterly_financials loan book; results_xbrl
- Steps: extract guidance per call -> compare with the next quarter's book -> compute the hit rate
- Forbidden: comparing annual guidance with a single quarter
- Coverage: **partial** — guidance and book are held; no structured hit-rate
- Why: PSU/NBFC guidance credibility is asked often

### RD-N-024 · management_credibility · family 3 · `guidance_vs_delivery`

**Q.** Vedanta: management has promised deleveraging several times. What was the net-debt target each time, and where is net debt now?

- Entities: VEDL (INE205A01025)
- Period: FY22-FY26 · as-of: 2026-10-19 · answer: explanation
- Evidence: concall_facts deleveraging statements; annual_financials net debt; results_xbrl
- Steps: list the dated targets -> show net debt at each promise and now -> state the cumulative miss
- Forbidden: netting asset sales against operating debt without saying so
- Coverage: **partial** — targets are text facts; no promise ledger
- Why: deleveraging-promise tracking is a standard bear case

### RD-N-025 · management_credibility · family 3 · `guidance_vs_delivery`

**Q.** Paytm: management gave a profitability timeline. Did the company hit it, and what did it cost in revenue growth?

- Entities: PAYTM (INE982J01020)
- Period: FY24-FY26 · as-of: 2026-10-19 · answer: fact
- Evidence: concall_facts profitability guidance; results_xbrl EBITDA/revenue; px_nse
- Steps: quote the original timeline -> show the delivered EBITDA and revenue path -> state the trade-off
- Forbidden: using adjusted EBITDA when the guidance was on reported EBITDA
- Coverage: **partial** — the two series exist; no guidance table
- Why: turnaround-timeline accountability is a real question

### RD-N-026 · unit_economics · family 17 · `unit_economics`

**Q.** Eternal: what is food-delivery contribution margin per order, and how much of the profit comes from the take rate versus ads?

- Entities: ETERNAL (INE758T01015)
- Period: FY25-FY26 · as-of: 2026-10-19 · answer: explanation
- Evidence: results_xbrl segment revenue/EBITDA; concall_facts contribution margin and GOV; deck_figures; ar_facts
- Steps: find GOV and revenue -> compute take rate -> separate ad revenue from commission -> state the per-order margin
- Forbidden: dividing total EBITDA by total orders when segments differ
- Coverage: **partial** — GOV and orders are disclosed in text/prints, not as a table
- Why: unit-economics questions are the core of new-age investing threads

### RD-N-027 · unit_economics · family 17 · `unit_economics`

**Q.** Swiggy: is Instamart's contribution margin improving because of scale or because of a cut in discounts, and what does that mean for growth?

- Entities: SWIGGY (INE00H001014)
- Period: FY25-FY26 · as-of: 2026-10-19 · answer: explanation
- Evidence: results_xbrl segment revenue/EBITDA; concall_facts contribution margin; deck
- Steps: show the margin path -> check whether GOV growth slowed at the same time -> state the trade-off
- Forbidden: calling a discount cut structural margin expansion
- Coverage: **partial** — segment data is disclosed quarterly but not structured
- Why: quick-commerce unit economics are debated endlessly

### RD-N-028 · unit_economics · family 17 · `unit_economics`

**Q.** Nykaa: what does the BPC segment earn per order after fulfilment, and is the fashion segment diluting it?

- Entities: NYKAA (INE388Y01029)
- Period: FY25-FY26 · as-of: 2026-10-19 · answer: explanation
- Evidence: results_xbrl segment revenue/EBITDA; concall_facts AOV and fulfilment cost; deck
- Steps: compute AOV x orders -> subtract fulfilment and marketing -> show the segment split
- Forbidden: using consolidated margin for a segment question
- Coverage: **partial** — AOV is in commentary; a per-order table is not
- Why: segment-level unit economics is asked constantly for consumer tech

### RD-N-029 · unit_economics · family 17 · `unit_economics`

**Q.** DMart: what is revenue per square foot and inventory turns, and how have they moved as the store base aged?

- Entities: DMART (INE192R01011)
- Period: FY20-FY26 · as-of: 2026-10-19 · answer: fact
- Evidence: annual_financials revenue/inventory; concall_facts store count and area; deck_figures
- Steps: extract store count and area by year -> compute revenue per sq ft and turns -> show the trend
- Forbidden: using a store count from a different date than the revenue
- Coverage: **partial** — area is disclosed in text; store count is in commentary
- Why: retail productivity metrics are standard in value forums

### RD-N-030 · unit_economics · family 17 · `unit_economics`

**Q.** Trent: what does a new store earn at maturity, and how long is the payback at the current capex per store?

- Entities: TRENT (INE849A01020)
- Period: FY24-FY26 · as-of: 2026-10-19 · answer: explanation
- Evidence: annual_financials capex/revenue; concall_facts store adds; deck_figures
- Steps: estimate capex per store -> estimate mature-store revenue -> compute payback with the segment margin
- Forbidden: assuming day-one sales equal mature-store sales
- Coverage: **partial** — capex per store is not disclosed as a table; the estimate must be labelled
- Why: store-payback math is a classic small-cap/retail question

### RD-N-031 · cycle_position · family 16 · `cycle_peak_trough`

**Q.** Hindalco: where are we in the aluminium cycle, and what is Novelis's cost position relative to the curve?

- Entities: HINDALCO (INE038A01020)
- Period: FY24-FY26 · as-of: 2026-10-19 · answer: explanation
- Evidence: results_xbrl segment EBITDA; annual_financials; concall_facts cost curve and spreads; no LME series
- Steps: show margin vs the last peak -> state the cost position as claimed -> flag that the commodity series is NOT IN DATA
- Forbidden: calling a cycle turn from one quarter's margin
- Coverage: **no** — no commodity price series in store; the company's own spreads are all we have
- Why: cycle positioning is the most-asked commodity-stock question and we cannot answer it PIT

### RD-N-032 · cycle_position · family 16 · `cycle_peak_trough`

**Q.** JSW Steel: what is capacity utilisation and steel spread now versus the last downcycle, and how fast does margin mean-revert?

- Entities: JSWSTEEL (INE019A01038)
- Period: FY22-FY26 · as-of: 2026-10-19 · answer: explanation
- Evidence: results_xbrl volume/EBITDA; concall_facts utilisation and spreads; annual_financials
- Steps: show utilisation and EBITDA per tonne -> compare with the last trough -> give the mean-reversion range
- Forbidden: using a company-stated spread without a date
- Coverage: **partial** — utilisation is commentary, not a series; no steel price table
- Why: steel-cycle positioning is a recurring macro-value question

### RD-N-033 · cycle_position · family 16 · `cycle_peak_trough`

**Q.** Tata Chemicals: the soda ash cycle has turned. How much of the margin is cycle and how much is the company's cost advantage?

- Entities: TATACHEM (INE092A01019)
- Period: FY22-FY26 · as-of: 2026-10-19 · answer: explanation
- Evidence: results_xbrl segment revenue/EBITDA; concall_facts soda ash realisation; annual_financials
- Steps: split the margin into realisation and cost -> compare with the prior cycle -> state the sustainable band
- Forbidden: treating peak soda ash prices as the new normal
- Coverage: **partial** — no soda ash price series; realisation commentary is dated
- Why: chemical-cycle decomposition is asked in value and small-cap forums

### RD-N-034 · cycle_position · family 16 · `cycle_peak_trough`

**Q.** Deepak Nitrite: is the destocking over, and what do inventory days and realisation say about the next two quarters?

- Entities: DEEPAKNTR (INE288B01029)
- Period: FY24-FY26 · as-of: 2026-10-19 · answer: explanation
- Evidence: results_xbrl revenue/margin; annual_financials inventory; concall_facts destocking commentary
- Steps: show inventory days and realisation -> quote the dated destocking claim -> say what would confirm the turn
- Forbidden: calling the bottom from a single quarter
- Coverage: **partial** — inventory is held; no channel inventory series
- Why: destocking calls are central to chemical investors

### RD-N-035 · cycle_position · family 16 · `cycle_peak_trough`

**Q.** Ambuja Cements: is the cement cycle in a price war or a volume recovery, and what does cost per tonne say?

- Entities: AMBUJACEM (INE079A01024)
- Period: FY24-FY26 · as-of: 2026-10-19 · answer: explanation
- Evidence: results_xbrl revenue/volume/EBITDA; concall_facts price and cost per tonne; annual_financials
- Steps: compute realisation and cost per tonne -> show the spread trend -> state the cycle read
- Forbidden: using consolidated revenue without volume
- Coverage: **partial** — volume is disclosed but not structured; no regional price data
- Why: cement cycle questions need per-tonne economics we do not table

### RD-N-036 · second_order_macro · family 16 · `second_order_macro`

**Q.** If the RBI cuts rates, what happens to HDFC Bank's NIM first and loan growth second, and how long is the lag?

- Entities: HDFCBANK (INE040A01034)
- Period: rate cycle · as-of: 2026-10-19 · answer: explanation
- Evidence: fii_dii_cash has Nifty only; policy_events for rate actions; results_xbrl NIM; concall_facts rate sensitivity
- Steps: state the rate action -> trace to deposit repricing then lending -> give the lag management has stated
- Forbidden: assuming a rate cut is immediately margin-positive for a bank
- Coverage: **partial** — policy events are held; no deposit/loan repricing schedule
- Why: second-order rate transmission is the most common macro-value question

### RD-N-037 · second_order_macro · family 16 · `second_order_macro`

**Q.** Bajaj Finance: does a rate cut help or hurt the cost of funds before it helps AUM, and what does history say?

- Entities: BAJFINANCE (INE296A01032)
- Period: rate cycle · as-of: 2026-10-19 · answer: explanation
- Evidence: results_xbrl cost of funds; concall_facts borrowing mix; policy_events; annual_financials
- Steps: show the borrowing mix -> trace the repricing -> compare past rate cycles with AUM growth
- Forbidden: treating a cut as a pure positive for an NBFC
- Coverage: **partial** — cost of funds is derivable; no repricing calendar
- Why: NBFC rate sensitivity is a standard thread

### RD-N-038 · second_order_macro · family 16 · `second_order_macro`

**Q.** Crude fell sharply. How long before Asian Paints' raw-material cost falls, and what did it do last time?

- Entities: ASIANPAINT (INE021A01026)
- Period: last cycle · as-of: 2026-10-19 · answer: explanation
- Evidence: annual_financials gross margin; concall_facts RM commentary; no crude series
- Steps: mark past crude moves -> measure the margin response lag -> state the pass-through
- Forbidden: assuming an immediate cost fall; ignoring inventory holding
- Coverage: **partial** — no commodity series; the lag can only be told from commentary
- Why: input-cost transmission is family 16 but asks for the lag, not just the link

### RD-N-039 · second_order_macro · family 16 · `second_order_macro`

**Q.** The rupee weakened. How much of Infosys's margin gain is translation versus hedging, and when does it show?

- Entities: INFY (INE009A01021)
- Period: last 2 quarters · as-of: 2026-10-19 · answer: explanation
- Evidence: results_xbrl margin; concall_facts FX assumption and hedging; annual_financials
- Steps: show the realised rate vs the assumed rate -> separate translation from hedging -> give the quarter it lands in
- Forbidden: multiplying revenue by the rate change and calling it margin
- Coverage: **partial** — no INR series in store; company FX assumption is in the call
- Why: rupee-sensitivity math is asked every quarter

### RD-N-040 · second_order_macro · family 16 · `second_order_macro`

**Q.** Rubber and crude rose together. Which tyre maker has the fastest price pass-through, and how did the last spike play out?

- Entities: APOLLOTYRE (INE438A01022), MRF (INE883A01011), CEATLTD (INE482A01020)
- Period: FY24-FY26 · as-of: 2026-10-19 · answer: ranking
- Evidence: concall_facts price hikes; annual_financials gross margin; no commodity series
- Steps: line up dated hikes -> align margin troughs -> rank the recovery speed
- Forbidden: assuming a hike sticks without a volume check
- Coverage: **partial** — no commodity series; commentary is the only timing source
- Why: pass-through speed is what the market actually trades

### RD-N-041 · reinvestment_runway · family 17 · `fundamental_health_check`

**Q.** CG Power: how much can it reinvest in transformer capacity, and what returns has the last expansion earned?

- Entities: CGPOWER (INE067A01029)
- Period: FY23-FY26 · as-of: 2026-10-19 · answer: explanation
- Evidence: annual_financials capex/EBIT; concall_facts capacity expansion; results_xbrl; deck
- Steps: show capacity and capex by year -> compute incremental EBIT -> state the runway in years
- Forbidden: treating an order book as capacity
- Coverage: **partial** — capacity is disclosed in text, not as a series
- Why: reinvestment runway is the core compounder question

### RD-N-042 · reinvestment_runway · family 17 · `fundamental_health_check`

**Q.** Polycab: the cable demand is strong. How much capex is left, and is the incremental ROIC above the last cycle?

- Entities: POLYCAB (INE455K01017)
- Period: FY23-FY26 · as-of: 2026-10-19 · answer: explanation
- Evidence: annual_financials capex/EBIT; concall_facts expansion; results_xbrl
- Steps: show the capex programme -> compute incremental return -> compare with the prior expansion
- Forbidden: counting announced capex as commissioned
- Coverage: **partial** — capex is in the cash-flow statement; project status is text
- Why: capex-runway questions are common in small/mid-cap threads

### RD-N-043 · reinvestment_runway · family 17 · `fundamental_health_check`

**Q.** Dixon: with PLI and new categories, what is the reinvestment need per rupee of new revenue, and does the return clear the hurdle?

- Entities: DIXON (INE935N01020)
- Period: FY24-FY26 · as-of: 2026-10-19 · answer: explanation
- Evidence: annual_financials capex/working capital/EBIT; concall_facts category additions
- Steps: compute capital employed per rupee of revenue -> compute the incremental return -> state the funding need
- Forbidden: ignoring working capital in the reinvestment need
- Coverage: **partial** — the inputs are held; a segment capital table is not
- Why: asset-light vs working-capital-heavy growth is a value-forum staple

### RD-N-044 · reinvestment_runway · family 17 · `fundamental_health_check`

**Q.** Kaynes: what is the semiconductor/OSAT runway, and how much of the current order book depends on the new plant?

- Entities: KAYNES (INE918Z01012)
- Period: FY25-FY27 · as-of: 2026-10-19 · answer: explanation
- Evidence: concall_facts order book and plant timeline; annual_financials capex; results_xbrl
- Steps: separate existing-plant order book from new-plant -> give the commissioning date -> state the revenue it must add
- Forbidden: booking a plant's revenue before commissioning
- Coverage: **partial** — the timeline is text; no project tracker
- Why: new-capacity optionality is asked in every small-cap thread

### RD-N-045 · reinvestment_runway · family 17 · `fundamental_health_check`

**Q.** Astral: does the piping capacity addition still make sense if housing starts slow, and what is the utilisation today?

- Entities: ASTRAL (INE006I01046)
- Period: FY24-FY26 · as-of: 2026-10-19 · answer: explanation
- Evidence: annual_financials capex/revenue; concall_facts utilisation; results_xbrl
- Steps: show utilisation -> map the capacity add to demand -> state the downside case
- Forbidden: assuming housing demand is stable because the order book is
- Coverage: **partial** — utilisation is commentary; no housing-start series
- Why: capex-vs-demand timing is a classic value question

### RD-N-046 · balance_sheet_stress · family 14 · `fundamental_health_check`

**Q.** Vedanta: how much debt matures in the next two years, and can dividends plus cash cover it without asset sales?

- Entities: VEDL (INE205A01025)
- Period: FY26-FY28 · as-of: 2026-10-19 · answer: fact
- Evidence: annual_financials debt/interest/FCF; ar_facts maturity note; corporate_documents
- Steps: show the maturity profile -> show FCF and dividends -> compute the funding gap
- Forbidden: using consolidated cash for parent maturities; assuming a refinance
- Coverage: **partial** — total debt is held; the maturity schedule is not structured
- Why: maturity-wall questions are a value-forum staple and we cannot answer them fully

### RD-N-047 · balance_sheet_stress · family 14 · `fundamental_health_check`

**Q.** Vodafone Idea: can operating cash flow cover interest and spectrum instalments, or is another capital raise certain?

- Entities: IDEA (INE669E01016)
- Period: FY26-FY28 · as-of: 2026-10-19 · answer: fact
- Evidence: annual_financials OCF/interest/debt; results_xbrl; concall_facts AGR/spectrum
- Steps: show OCF vs interest -> add spectrum instalments -> state the gap and the funding options disclosed
- Forbidden: assuming a government moratorium is permanent
- Coverage: **partial** — cash-flow lines are held; the instalment schedule is text
- Why: solvency math is the central question on the stock

### RD-N-048 · balance_sheet_stress · family 14 · `fundamental_health_check`

**Q.** Jaiprakash Power: has the debt actually fallen, or has it been moved into CWIP and JVs?

- Entities: JPPOWER (INE351F01018)
- Period: FY22-FY26 · as-of: 2026-10-19 · answer: fact
- Evidence: annual_financials debt/CWIP/investments; ar_facts notes; results_xbrl
- Steps: show gross debt and CWIP together -> trace the reduction -> state where it went
- Forbidden: treating a debt transfer to a JV as repayment
- Coverage: **partial** — balance-sheet lines are held; note-level detail is patchy
- Why: debt-reduction quality is asked on every distressed name

### RD-N-049 · balance_sheet_stress · family 14 · `fundamental_health_check`

**Q.** Adani Green: what is net debt to EBITDA, and how is the capex funded if the refinancing window narrows?

- Entities: ADANIGREEN (INE364U01010)
- Period: FY26 · as-of: 2026-10-19 · answer: fact
- Evidence: annual_financials net debt/EBITDA/capex; concall_facts funding plan; results_xbrl
- Steps: compute net debt/EBITDA -> show capex vs CFO -> state the funding mix
- Forbidden: netting project debt against a parent guarantee
- Coverage: **partial** — consolidated debt is held; the project-finance schedule is not
- Why: growth-funded-by-debt questions are frequent

### RD-N-050 · balance_sheet_stress · family 14 · `fundamental_health_check`

**Q.** IRB Infrastructure: how much of the leverage sits at the holdco, and what did asset monetisation actually repay?

- Entities: IRB (INE821I01022)
- Period: FY23-FY26 · as-of: 2026-10-19 · answer: fact
- Evidence: annual_financials debt; concall_facts monetisation proceeds; corporate_documents
- Steps: show consolidated debt -> trace proceeds to repayment -> state the holdco residual
- Forbidden: assuming all proceeds repay debt
- Coverage: **partial** — no holdco/opco split table
- Why: infra leverage quality is a standard credit-style question

### RD-N-051 · earnings_quality · family 2 · `fundamental_health_check`

**Q.** TCS: does CFO track PAT, and are receivables days creeping as deal terms lengthen?

- Entities: TCS (INE467B01029)
- Period: FY20-FY26 · as-of: 2026-10-19 · answer: fact
- Evidence: annual_financials CFO/PAT/receivables; results_xbrl; concall_facts DSO
- Steps: compute CFO/PAT and DSO by year -> flag the trend break -> state the cause if disclosed
- Forbidden: treating a working-capital release as operating improvement
- Coverage: **yes** — cash-flow and balance-sheet lines are held
- Why: accrual-quality checks are standard in SecurityAnalysis-style threads

### RD-N-052 · earnings_quality · family 2 · `fundamental_health_check`

**Q.** Infosys: has unbilled revenue grown faster than revenue, and what does that say about revenue recognition?

- Entities: INFY (INE009A01021)
- Period: FY22-FY26 · as-of: 2026-10-19 · answer: fact
- Evidence: ar_facts unbilled revenue note; annual_financials receivables/CFO; results_xbrl
- Steps: show unbilled as a share of revenue -> compare with CFO -> quote the accounting policy
- Forbidden: calling an accounting-policy change a red flag without the disclosure
- Coverage: **partial** — notes are extracted but inconsistent across years
- Why: unbilled-revenue questions are common for IT services

### RD-N-053 · earnings_quality · family 2 · `fundamental_health_check`

**Q.** Mphasis: direct-client mix has risen. Did DSO and CFO/PAT improve with it, or did the mix just move revenue?

- Entities: MPHASIS (INE356A01018)
- Period: FY22-FY26 · as-of: 2026-10-19 · answer: fact
- Evidence: results_xbrl revenue/margin; annual_financials receivables/CFO; concall_facts mix
- Steps: show mix and DSO together -> compute CFO/PAT -> state whether the mix improved cash
- Forbidden: assuming a mix shift is automatically cash-accretive
- Coverage: **partial** — mix is commentary; DSO is derivable
- Why: mix-versus-cash questions are a real value pattern

### RD-N-054 · earnings_quality · family 2 · `fundamental_health_check`

**Q.** Coforge: how much of the growth is acquisition versus organic, and what did the acquisitions do to goodwill and cash conversion?

- Entities: COFORGE (INE591G01025)
- Period: FY22-FY26 · as-of: 2026-10-19 · answer: explanation
- Evidence: annual_financials revenue/goodwill/CFO; corporate_documents acquisitions; concall_facts organic growth
- Steps: separate acquired revenue -> show goodwill and CFO/PAT -> state the organic growth
- Forbidden: treating acquired growth as organic
- Coverage: **partial** — acquisition dates are in filings; a clean organic series is not
- Why: inorganic-growth quality is a classic international question

### RD-N-055 · earnings_quality · family 2 · `fundamental_health_check`

**Q.** Persistent: is the margin expansion real, or is it capitalised development cost catching up with revenue?

- Entities: PERSISTENT (INE262H01021)
- Period: FY22-FY26 · as-of: 2026-10-19 · answer: fact
- Evidence: annual_financials margin/CFO; ar_facts capitalised software note; results_xbrl
- Steps: show capitalised cost as a share of revenue -> compare with EBITDA -> quote the policy
- Forbidden: ignoring capitalisation when comparing margins across peers
- Coverage: **partial** — the note exists; the series is not structured
- Why: capitalisation questions separate analysts from headline readers

### RD-N-056 · sum_of_parts · family 2 · `sum_of_parts_holdco`

**Q.** Bajaj Holdings: what is the holdco discount to the sum of its listed stakes, and has it widened over five years?

- Entities: BAJAJHLDNG (INE118A01012), BAJFINANCE (INE296A01032), BAJAJFINSV (INE918I01026)
- Period: FY22-FY26 · as-of: 2026-10-19 · answer: fact
- Evidence: shareholding for stake sizes; px_nse for market caps; annual_financials for the holdco's own book
- Steps: value each listed stake at a date -> add net cash -> compare with holdco market cap -> compute the discount
- Forbidden: using today's stake with a historical price; ignoring the unlisted stake
- Coverage: **partial** — stakes and prices are held, but no ownership-edge table
- Why: holdco discounts are a favourite value question and we have no SOTP table

### RD-N-057 · sum_of_parts · family 2 · `sum_of_parts_holdco`

**Q.** Tata Investment: is the market cap above or below the value of its listed portfolio, and how has that gap behaved?

- Entities: TATAINVEST (INE672A01026)
- Period: FY22-FY26 · as-of: 2026-10-19 · answer: fact
- Evidence: ar_facts investments note; shareholding; px_nse
- Steps: pull the portfolio value from the annual report -> compare with market cap -> show the gap by year
- Forbidden: valuing the portfolio at cost instead of market
- Coverage: **partial** — portfolio holdings are in the AR notes, not a table
- Why: the 'trades below its portfolio' question is classic

### RD-N-058 · sum_of_parts · family 2 · `sum_of_parts_holdco`

**Q.** Godrej Industries holds several listed companies. What is the per-share value of the stakes versus the market price?

- Entities: GODREJIND (INE233A01035), GODREJCP (INE102D01028), GODREJPROP (INE484J01027)
- Period: FY26 · as-of: 2026-10-19 · answer: fact
- Evidence: shareholding stakes; px_nse; annual_financials net debt
- Steps: map each stake -> value it -> subtract holdco net debt -> compare with market cap
- Forbidden: double-counting cross-holdings
- Coverage: **partial** — no ownership graph; must be assembled from filings
- Why: multi-stake holdcos are a recurring Indian value theme

### RD-N-059 · sum_of_parts · family 2 · `sum_of_parts_holdco`

**Q.** Bajaj Finserv: what are the insurance and lending pieces worth separately, and how much of the value is the holding company?

- Entities: BAJAJFINSV (INE918I01026), BAJFINANCE (INE296A01032)
- Period: FY26 · as-of: 2026-10-19 · answer: explanation
- Evidence: annual_financials segment; shareholding; px_nse; concall_facts insurance
- Steps: value the listed lending stake -> value the insurance book on embedded value if disclosed -> compare with the market cap
- Forbidden: using an embedded-value number without a date
- Coverage: **partial** — EV disclosures are in decks, not a table
- Why: SOTP is asked for every financial holdco

### RD-N-060 · sum_of_parts · family 2 · `sum_of_parts_holdco`

**Q.** Tata Power: do the subsidiaries and the renewables book justify a market cap above the standalone utility?

- Entities: TATAPOWER (INE245A01021)
- Period: FY26 · as-of: 2026-10-19 · answer: explanation
- Evidence: annual_financials segment; shareholding; px_nse; concall_facts capacity
- Steps: split regulated utility from the growth businesses -> value each on the disclosure -> state the implied premium
- Forbidden: valuing an under-construction plant as operating
- Coverage: **partial** — segment data is partial; no SOTP table
- Why: utility-plus-growth SOTP is a common Indian value question

### RD-N-061 · dividend_sustainability · family 2 · `dividend_sustainability`

**Q.** Coal India: is the dividend covered by free cash flow after the capex plan, or is it borrowing from the future?

- Entities: COALINDIA (INE522F01014)
- Period: FY22-FY26 · as-of: 2026-10-19 · answer: fact
- Evidence: annual_financials FCF/capex/dividends; corporate_documents dividend declarations; results_xbrl
- Steps: compute FCF -> compare with dividends -> show the payout cover by year
- Forbidden: using PAT instead of FCF for a capital-intensive miner
- Coverage: **yes** — cash flow, capex and dividends are held
- Why: dividend-cover math is a staple of dividend subs

### RD-N-062 · dividend_sustainability · family 2 · `dividend_sustainability`

**Q.** Power Grid: the regulated return sets the dividend. What happens to the payout if the capex cycle slows?

- Entities: POWERGRID (INE752E01010)
- Period: FY24-FY27 · as-of: 2026-10-19 · answer: explanation
- Evidence: annual_financials capex/regulatory equity; concall_facts capex guidance; results_xbrl
- Steps: show regulated equity growth -> map to earnings -> show dividend cover under a slower capex case
- Forbidden: treating a regulated return as a guaranteed dividend
- Coverage: **partial** — capex and earnings are held; the regulatory asset base is text
- Why: utility dividend durability is asked in both value and dividend forums

### RD-N-063 · dividend_sustainability · family 2 · `dividend_sustainability`

**Q.** ITC: how much of the dividend is covered by the cigarette cash flow once the FMCG reinvestment is funded?

- Entities: ITC (INE154A01025)
- Period: FY22-FY26 · as-of: 2026-10-19 · answer: fact
- Evidence: annual_financials segment EBITDA/capex/dividends; results_xbrl
- Steps: compute segment cash generation -> subtract FMCG capex -> compare with the dividend
- Forbidden: using consolidated PAT without the segment mix
- Coverage: **partial** — segments are held; a segment cash-flow split is not
- Why: dividend cover by segment is a real question

### RD-N-064 · dividend_sustainability · family 2 · `dividend_sustainability`

**Q.** Hindustan Zinc: the payout is very high. Is it sustainable at current metal prices, and what does the capex plan need?

- Entities: HINDZINC (INE267A01025)
- Period: FY24-FY26 · as-of: 2026-10-19 · answer: fact
- Evidence: annual_financials FCF/capex/dividends; results_xbrl; concall_facts cost
- Steps: show FCF at spot-ish realisations -> subtract maintenance capex -> state the covered payout
- Forbidden: assuming the current metal price is the through-cycle price
- Coverage: **partial** — no metal series; the company's realisations are in the P&L
- Why: high-yield sustainability is the #1 dividend question

### RD-N-065 · dividend_sustainability · family 2 · `dividend_sustainability`

**Q.** NMDC: at the bottom of the iron-ore cycle, would the dividend be cut, and what did the last downturn show?

- Entities: NMDC (INE584A01023)
- Period: FY22-FY26 · as-of: 2026-10-19 · answer: fact
- Evidence: annual_financials FCF/dividends; results_xbrl; corporate_documents
- Steps: show dividend vs FCF through the last downcycle -> state the cut pattern -> stress the current payout
- Forbidden: extrapolating a peak payout
- Coverage: **partial** — no iron-ore price series; company realisations are held
- Why: cyclical dividend durability is a standard test

### RD-N-066 · customer_concentration · family 19 · `customer_supplier_concentration`

**Q.** Dixon: how concentrated is the customer base, and what would losing the top account do to revenue and margin?

- Entities: DIXON (INE935N01020)
- Period: FY26 · as-of: 2026-10-19 · answer: fact
- Evidence: ar_facts customer concentration note; results_xbrl revenue; concall_facts client mix
- Steps: quote the top-customer share -> compute revenue at risk -> state the margin effect
- Forbidden: assuming a customer is locked in by the PLI scheme
- Coverage: **partial** — the note exists but extraction is inconsistent
- Why: customer-concentration risk is a core international value question

### RD-N-067 · customer_concentration · family 19 · `customer_supplier_concentration`

**Q.** Kaynes: what share of revenue comes from the top five customers, and how does that compare with the order-book claims?

- Entities: KAYNES (INE918Z01012)
- Period: FY26 · as-of: 2026-10-19 · answer: fact
- Evidence: ar_facts concentration note; concall_facts order book; results_xbrl
- Steps: quote the top-five share -> compare with the order book -> state the dependence
- Forbidden: treating a diversified order book as a diversified customer base
- Coverage: **partial** — concentration note is text; no customer table
- Why: EMS customer concentration is a favourite bear case

### RD-N-068 · customer_concentration · family 19 · `customer_supplier_concentration`

**Q.** Syrma: how much revenue depends on the top client, and has that dependence fallen since the IPO?

- Entities: SYRMA (INE0DYJ01015)
- Period: FY22-FY26 · as-of: 2026-10-19 · answer: fact
- Evidence: ar_facts concentration note; corporate_documents prospectus; results_xbrl
- Steps: show the top-client share by year -> state the trend -> compare with the prospectus claim
- Forbidden: treating a prospectus claim as current without the later annual report
- Coverage: **partial** — the note is text; the trend needs manual extraction
- Why: tests whether a listed-at-IPO claim still holds

### RD-N-069 · customer_concentration · family 19 · `customer_supplier_concentration`

**Q.** Amber: the air-conditioner business is seasonal and concentrated. What does that do to quarterly revenue and working capital?

- Entities: AMBER (INE371P01015)
- Period: FY24-FY26 · as-of: 2026-10-19 · answer: explanation
- Evidence: results_xbrl quarterly revenue; annual_financials inventory/receivables; concall_facts seasonality
- Steps: show the quarterly pattern -> compute WC peak -> state the seasonality risk
- Forbidden: annualising a peak quarter
- Coverage: **partial** — quarterly revenue is held; no seasonality table
- Why: seasonality plus concentration is a real risk question

### RD-N-070 · customer_concentration · family 19 · `customer_supplier_concentration`

**Q.** Sona Comstar: how much of the order book is EV, and how dependent is it on two customers?

- Entities: SONACOMS (INE073K01018)
- Period: FY26 · as-of: 2026-10-19 · answer: fact
- Evidence: concall_facts EV order book/client mix; ar_facts concentration note; results_xbrl
- Steps: quote EV share and client share -> state the overlap -> quantify the risk
- Forbidden: treating an EV order book as a customer-diversified one
- Coverage: **partial** — both shares are text facts, not a table
- Why: concentration plus EV exposure in one question

### RD-N-071 · thesis_break · family 20 · `thesis_break_sell`

**Q.** For Asian Paints, what would actually break the moat thesis: a new entrant's share, a dealer shift, or a gross-margin floor?

- Entities: ASIANPAINT (INE021A01026)
- Period: forward 2 years · as-of: 2026-10-19 · answer: explanation
- Evidence: margin history; concall_facts competitor commentary; market-share claims; px_nse
- Steps: name the three falsifiers -> state the current value of each -> say which is closest to breaking
- Forbidden: giving a price target instead of a falsifier
- Coverage: **partial** — the data can track margin and claims; no share series
- Why: 'what would make you sell' is explicit on value forums and absent from our banks

### RD-N-072 · thesis_break · family 20 · `thesis_break_sell`

**Q.** For DMart, what evidence would prove quick commerce has permanently damaged the growth runway?

- Entities: DMART (INE192R01011)
- Period: forward 2 years · as-of: 2026-10-19 · answer: explanation
- Evidence: revenue per store; store adds; concall_facts competition commentary; px_nse
- Steps: state the falsifier (e.g. falling revenue per store for N quarters) -> show the current trend -> name the threshold
- Forbidden: asserting disruption from a single weak quarter
- Coverage: **partial** — store productivity needs manual extraction
- Why: disruption falsifiers are the standard value-forum exercise

### RD-N-073 · thesis_break · family 20 · `thesis_break_sell`

**Q.** For Eternal, what would prove the profitability path is broken rather than delayed?

- Entities: ETERNAL (INE758T01015)
- Period: forward 2 years · as-of: 2026-10-19 · answer: explanation
- Evidence: segment contribution margin; GOV growth; concall_facts; results_xbrl
- Steps: name the falsifier -> show the current margin and growth -> state the threshold
- Forbidden: treating a one-quarter margin dip as a broken thesis
- Coverage: **partial** — the series exist but are not tabulated
- Why: thesis-break framing for new-age names

### RD-N-074 · thesis_break · family 20 · `thesis_break_sell`

**Q.** For Polycab, what would prove the power-capex cycle has peaked: order growth, utilisation, or receivable days?

- Entities: POLYCAB (INE455K01017)
- Period: forward 2 years · as-of: 2026-10-19 · answer: explanation
- Evidence: revenue growth; receivables; concall_facts order book; px_nse
- Steps: rank the three leading indicators -> show the current values -> name the threshold for each
- Forbidden: using the stock price as a cycle indicator
- Coverage: **partial** — no order-book or utilisation series
- Why: cycle-peak falsifiers are asked in small/mid-cap value threads

### RD-N-075 · thesis_break · family 20 · `thesis_break_sell`

**Q.** For Titan, what would break the growth thesis: a gold-price spike, lab-grown diamonds, or a same-store slowdown?

- Entities: TITAN (INE280A01028)
- Period: forward 2 years · as-of: 2026-10-19 · answer: explanation
- Evidence: segment growth; concall_facts studded mix; px_nse; no gold or lab-grown series
- Steps: name each falsifier -> show the held evidence -> state which is measurable today
- Forbidden: presenting a macro fear as a tracked metric
- Coverage: **partial** — gold and lab-grown series are NOT IN DATA
- Why: falsifier framing rather than a target price

## Technical / entry-timing patterns

### RD-T-001 · ta_support_resistance · family NEW:technical_setup · `ta_support_resistance`

**Q.** Reliance has retested the same zone three times since August. As of 24 Sep 2026, did the third retest hold on lower volume?

- Entities: RELIANCE (INE002A01018)
- Period: 2026-08/2026-09 · as-of: 2026-09-24 · answer: fact
- Evidence: px_nse daily OHLCV; daily_price_delivery volume and delivery %; swing highs/lows computed from the series
- Steps: find the three touch dates -> fit the level from swing highs -> compare volume and delivery on each touch
- Forbidden: drawing a level after seeing the outcome; using a single wick as the level
- Coverage: **yes** — PIT yes: every row is dated; the level must be derived, not read from a stored column
- Why: support/resistance is the most-asked technical phrasing and no family stores levels

### RD-T-002 · ta_support_resistance · family NEW:technical_setup · `ta_support_resistance`

**Q.** HDFC Bank broke below its 50-day average and then reclaimed it. Which close confirmed the reclaim, and what did delivery do?

- Entities: HDFCBANK (INE040A01034)
- Period: 2026-07/2026-09 · as-of: 2026-09-24 · answer: date
- Evidence: px_nse close; daily_price_delivery SMA50 and delivery %; volume
- Steps: find the break and the reclaim -> require two closes above -> check delivery on the reclaim day
- Forbidden: calling the first intraday cross a reclaim
- Coverage: **yes** — PIT yes: SMA50 is stored per dated row
- Why: break-and-reclaim is asked as a confirmation question

### RD-T-003 · ta_support_resistance · family NEW:technical_setup · `ta_support_resistance`

**Q.** TCS has been range-bound for two months. What are the range edges, and how many times has each been tested on above-average volume?

- Entities: TCS (INE467B01029)
- Period: 2026-07/2026-09 · as-of: 2026-09-24 · answer: fact
- Evidence: px_nse high/low; volume; daily_price_delivery
- Steps: estimate the range from the last 40 sessions -> count tests at each edge -> report volume on the tests
- Forbidden: using the all-time high as the range top
- Coverage: **yes** — PIT yes: the window is explicit
- Why: range trading is a distinct retail pattern from breakout

### RD-T-004 · ta_support_resistance · family NEW:technical_setup · `ta_support_resistance`

**Q.** SBI fell to a level that held in March. Is that level still valid after the June bounce, and how much volume sits at it?

- Entities: SBIN (INE062A01020)
- Period: 2026-03/2026-09 · as-of: 2026-09-24 · answer: explanation
- Evidence: px_nse OHLCV; delivery; swing points
- Steps: mark the March low -> check whether later closes respected it -> measure volume near the level
- Forbidden: assuming a level survives a gap through it
- Coverage: **yes** — PIT yes
- Why: asks whether a level is still valid, not just where it is

### RD-T-005 · ta_support_resistance · family NEW:technical_setup · `ta_support_resistance`

**Q.** Tata Motors PV: the post-demerger base is thin. What is the first real support level, and is there enough history to trust it?

- Entities: TMPV (INE155A01022)
- Period: demerger to 2026-09 · as-of: 2026-09-24 · answer: explanation
- Evidence: px_nse from the first post-demerger session; symbol_isin_history; volume ramp
- Steps: state the first trading date -> fit levels only from post-listing data -> say how few touches exist
- Forbidden: reusing the pre-demerger chart as if it were the same security
- Coverage: **partial** — PIT yes for prices; the short post-listing history limits the level
- Why: new-listing technicals are a real retail problem we cannot fake

### RD-T-006 · ta_breakout_volume · family NEW:technical_setup · `ta_breakout_volume`

**Q.** BEL broke to a new high in September. Was the breakout confirmed by volume and delivery, or was it a thin move?

- Entities: BEL (INE263A01024)
- Period: 2026-09 · as-of: 2026-09-24 · answer: fact
- Evidence: px_nse close/high/volume; daily_price_delivery delivery_qty/delivery_pct; 20-day medians
- Steps: find the breakout close -> compute volume and delivery ratios vs the 20-day median -> state confirmed or not
- Forbidden: calling a breakout from an intraday high; ignoring delivery
- Coverage: **yes** — PIT yes: date, volume and delivery are on the same row
- Why: retail explicitly asks for volume/delivery confirmation

### RD-T-007 · ta_breakout_volume · family NEW:technical_setup · `ta_breakout_volume`

**Q.** HAL cleared its previous swing high on a delivery spike. Did the delivery stay high for the next five sessions?

- Entities: HAL (INE066F01020)
- Period: 2026-08/2026-09 · as-of: 2026-09-24 · answer: fact
- Evidence: px_nse; daily_price_delivery delivery_qty/delivery_pct; volume
- Steps: mark the breakout day -> show delivery for the next five sessions -> say whether it held
- Forbidden: judging follow-through from price alone
- Coverage: **yes** — PIT yes
- Why: follow-through delivery is the question behind 'is the breakout real'

### RD-T-008 · ta_breakout_volume · family NEW:technical_setup · `ta_breakout_volume`

**Q.** RVNL broke out but the volume was below average. How many failed breakouts has it had in the last year on similar volume?

- Entities: RVNL (INE415G01027)
- Period: 2025-09/2026-09 · as-of: 2026-09-24 · answer: fact
- Evidence: px_nse close/high/volume; daily_price_delivery
- Steps: define a breakout -> define failure (close back below within N sessions) -> count prior cases with weak volume
- Forbidden: choosing the failure window after seeing the result
- Coverage: **yes** — PIT yes; the rule must be stated before the count
- Why: failed-breakout base rates are asked but never served

### RD-T-009 · ta_breakout_volume · family NEW:technical_setup · `ta_breakout_volume`

**Q.** IRFC's breakout came with high delivery %. Does high delivery at a breakout predict a better 20-day hold than low delivery?

- Entities: IRFC (INE053F01010)
- Period: 2024-2026 · as-of: 2026-09-24 · answer: explanation
- Evidence: px_nse; daily_price_delivery; all breakout days in the window
- Steps: label every breakout by delivery bucket -> compute forward 20-day return -> compare buckets
- Forbidden: reporting one case as the rule; ignoring survivorship in the window
- Coverage: **partial** — PIT yes for the inputs; small sample means the answer must state n
- Why: tests a retail belief against the data

### RD-T-010 · ta_breakout_volume · family NEW:technical_setup · `ta_breakout_volume`

**Q.** Polycab is near its 52-week high but delivery has fallen. Is the move being driven by intraday traders rather than accumulation?

- Entities: POLYCAB (INE455K01017)
- Period: 2026-06/2026-09 · as-of: 2026-09-24 · answer: explanation
- Evidence: px_nse close; delivery % trend; volume
- Steps: show price vs 52w high -> show delivery trend -> separate volume from delivery
- Forbidden: equating volume with accumulation
- Coverage: **yes** — PIT yes
- Why: the 'delivery is falling' observation is a common retail tell

### RD-T-011 · ta_ma_cross · family NEW:technical_setup · `ta_moving_average`

**Q.** Infosys: did the 50-day cross above the 200-day this year, and how has the stock behaved in the 30 sessions after each cross?

- Entities: INFY (INE009A01021)
- Period: 2025-2026 · as-of: 2026-09-24 · answer: fact
- Evidence: px_nse close; daily_price_delivery SMA50/SMA200
- Steps: find every cross -> take forward 30-session returns -> report the distribution, not one instance
- Forbidden: showing only the winning cross
- Coverage: **yes** — PIT yes: both averages are stored per dated row
- Why: golden-cross questions are constant and answerable

### RD-T-012 · ta_ma_cross · family NEW:technical_setup · `ta_moving_average`

**Q.** HDFC Bank is above its 200-day but below its 50-day. What has that configuration meant for the next month historically?

- Entities: HDFCBANK (INE040A01034)
- Period: 2021-2026 · as-of: 2026-09-24 · answer: explanation
- Evidence: px_nse; daily_price_delivery SMA50/SMA200
- Steps: label every session by configuration -> compute forward 21-day returns -> compare with the base rate
- Forbidden: using the whole sample when the regime differs
- Coverage: **partial** — PIT yes; the regime split is the analyst's job
- Why: the mixed-configuration question is asked far more than a clean cross

### RD-T-013 · ta_ma_cross · family NEW:technical_setup · `ta_moving_average`

**Q.** TCS has been below its 200-day for months. How far below, and when did it last spend this long under the line?

- Entities: TCS (INE467B01029)
- Period: 2021-2026 · as-of: 2026-09-24 · answer: fact
- Evidence: px_nse; SMA200
- Steps: compute distance from SMA200 -> find prior spells below -> give the current rank vs history
- Forbidden: using a percentage band as the only definition
- Coverage: **yes** — PIT yes
- Why: 'how long below the 200-day' is a common timing question

### RD-T-014 · ta_ma_cross · family NEW:technical_setup · `ta_moving_average`

**Q.** ITC's 50-day is flattening into the 200-day. What would a death cross actually change for a long-term holder?

- Entities: ITC (INE154A01025)
- Period: 2026 · as-of: 2026-09-24 · answer: explanation
- Evidence: px_nse; SMA50/SMA200; dividend and earnings history for the non-technical side
- Steps: show the cross state -> show the historical false-positive rate -> state what it does and does not change
- Forbidden: treating a lagging cross as a fundamental signal
- Coverage: **partial** — PIT yes for the cross; base rates need the full history
- Why: retail asks whether a technical signal should override a fundamental hold

### RD-T-015 · ta_ma_cross · family NEW:technical_setup · `ta_moving_average`

**Q.** Larsen & Toubro is near all three averages at once. Which average has acted as the better entry line over the last three years?

- Entities: LT (INE018A01030)
- Period: 2023-2026 · as-of: 2026-09-24 · answer: ranking
- Evidence: px_nse; SMA20/50/200
- Steps: define a touch -> measure forward return per average -> rank with sample sizes
- Forbidden: ranking on one case
- Coverage: **partial** — PIT yes; sample-size caveat required
- Why: asks which average is the useful one, not whether it crossed

### RD-T-016 · ta_rsi_setup · family NEW:technical_setup · `ta_rsi_momentum`

**Q.** Tata Power's RSI dipped below 30 in an uptrend. How did the stock perform over the next 20 sessions the last three times that happened?

- Entities: TATAPOWER (INE245A01021)
- Period: 2021-2026 · as-of: 2026-09-24 · answer: fact
- Evidence: px_nse; daily_price_delivery RSI14; trend filter (close above SMA200)
- Steps: find RSI<30 in an uptrend -> compute forward 20-day returns -> report each case with dates
- Forbidden: mixing downtrend and uptrend samples
- Coverage: **yes** — PIT yes: RSI14 is stored per dated row
- Why: RSI-in-uptrend is the classic retail setup

### RD-T-017 · ta_rsi_setup · family NEW:technical_setup · `ta_rsi_momentum`

**Q.** Adani Power is overbought on RSI but still making higher highs. Does overbought in a strong trend mean sell here?

- Entities: ADANIPOWER (INE814H01029)
- Period: 2024-2026 · as-of: 2026-09-24 · answer: explanation
- Evidence: px_nse; RSI14; forward returns by RSI bucket
- Steps: bucket sessions by RSI >70 -> compute forward 5/20-day returns -> compare with the base rate
- Forbidden: assuming mean reversion without the base rate
- Coverage: **partial** — PIT yes; the answer is a distribution, not a call
- Why: 'overbought, should I sell' is asked daily

### RD-T-018 · ta_rsi_setup · family NEW:technical_setup · `ta_rsi_momentum`

**Q.** Suzlon's RSI stayed above 70 for weeks during the rally. How long can that persist before a 10% drawdown, historically?

- Entities: SUZLON (INE040H01021)
- Period: 2024-2026 · as-of: 2026-09-24 · answer: fact
- Evidence: px_nse; RSI14; drawdown detection
- Steps: find RSI>70 spells -> measure their length and the subsequent drawdown -> report the range
- Forbidden: picking the longest spell as the rule
- Coverage: **yes** — PIT yes
- Why: RSI-persistence questions are common in momentum names

### RD-T-019 · ta_rsi_setup · family NEW:technical_setup · `ta_rsi_momentum`

**Q.** Vodafone Idea is deeply oversold again. Has an oversold RSI ever marked a durable low in this stock?

- Entities: IDEA (INE669E01016)
- Period: 2021-2026 · as-of: 2026-09-24 · answer: explanation
- Evidence: px_nse; RSI14; forward 60-day returns
- Steps: list every RSI<25 date -> compute 60-day forward return -> state the hit rate
- Forbidden: calling a bounce a turn
- Coverage: **yes** — PIT yes
- Why: tests the oversold-bounce belief on a structurally weak stock

### RD-T-020 · ta_rsi_setup · family NEW:technical_setup · `ta_rsi_momentum`

**Q.** Ola Electric's RSI made a higher low while price made a lower low. Is that divergence worth acting on, and how often has it worked?

- Entities: OLAELEC (INE0LXG01040)
- Period: listing to 2026-09 · as-of: 2026-09-24 · answer: explanation
- Evidence: px_nse; RSI14; listing date
- Steps: detect divergence days -> compute forward returns -> state the sample size
- Forbidden: ignoring the short listing history
- Coverage: **partial** — PIT yes; the sample is small after listing
- Why: divergence is widely discussed and rarely tested

### RD-T-021 · ta_52week · family NEW:technical_setup · `ta_52week_extreme`

**Q.** HAL is within 2% of its 52-week high. How many prior sessions this year were this close, and what followed?

- Entities: HAL (INE066F01020)
- Period: 2026 · as-of: 2026-09-24 · answer: fact
- Evidence: px_nse; daily_price_delivery 52-week high/low columns
- Steps: count sessions within 2% of the 52w high -> compute forward 10-day returns -> report
- Forbidden: counting only the successful breakouts
- Coverage: **yes** — PIT yes: the 52w columns are per dated row
- Why: 'near 52-week high, buy or wait' is a top retail question

### RD-T-022 · ta_52week · family NEW:technical_setup · `ta_52week_extreme`

**Q.** Mazagon Dock made a new 52-week high on declining volume. Is that a warning or noise?

- Entities: MAZDOCK (INE249Z01020)
- Period: 2026 · as-of: 2026-09-24 · answer: explanation
- Evidence: px_nse; volume; 52w high
- Steps: mark new-high days -> split by volume vs 20-day median -> compare forward returns
- Forbidden: assuming low-volume highs always fail
- Coverage: **partial** — PIT yes; small samples in a single year
- Why: volume-at-high is a specific retail concern

### RD-T-023 · ta_52week · family NEW:technical_setup · `ta_52week_extreme`

**Q.** Titan is 15% below its 52-week high. How long did the last three drawdowns of that size take to recover?

- Entities: TITAN (INE280A01028)
- Period: 2021-2026 · as-of: 2026-09-24 · answer: fact
- Evidence: px_nse; 52w high; drawdown episodes
- Steps: find 15% drawdowns -> measure recovery time -> report the range
- Forbidden: measuring from the lowest close rather than the peak
- Coverage: **yes** — PIT yes
- Why: time-to-recover is asked whenever a stock is 10-20% down

### RD-T-024 · ta_52week · family NEW:technical_setup · `ta_52week_extreme`

**Q.** Trent at a new high: what share of the last year's trading days were within 5% of the then-current 52-week high?

- Entities: TRENT (INE849A01020)
- Period: 2025-2026 · as-of: 2026-09-24 · answer: fact
- Evidence: px_nse; 52w high per row
- Steps: compute the per-row distance -> share within 5% -> state the persistence
- Forbidden: using today's 52-week high for historical rows
- Coverage: **yes** — PIT yes only if the per-row 52w column is used
- Why: tests whether 'at highs' is a regime or a day

### RD-T-025 · ta_52week · family NEW:technical_setup · `ta_52week_extreme`

**Q.** BEL versus HAL: which has spent more of the last two years within 10% of its 52-week high, and does that predict anything?

- Entities: BEL (INE263A01024), HAL (INE066F01020)
- Period: 2024-2026 · as-of: 2026-09-24 · answer: ranking
- Evidence: px_nse; 52w high per row
- Steps: compute the share of days near the high for both -> compare -> state whether forward returns differ
- Forbidden: treating persistence as predictive without a forward test
- Coverage: **partial** — PIT yes; the forward test is the analyst's
- Why: the relative-strength version of the 52-week question

### RD-T-026 · ta_gap · family NEW:technical_setup · `ta_gap_event`

**Q.** Tata Motors PV gapped up after its first post-demerger result. Has the gap filled, and how many sessions did it take?

- Entities: TMPV (INE155A01022)
- Period: Q1FY27 · as-of: 2026-09-24 · answer: date
- Evidence: px_nse prev_close/open/low; daily_price_delivery
- Steps: identify the result date -> compute the gap -> find the first low that fills it
- Forbidden: calling a partial fill a full fill
- Coverage: **yes** — PIT yes; needs the post-listing window only
- Why: gap-fill after results is asked constantly

### RD-T-027 · ta_gap · family NEW:technical_setup · `ta_gap_event`

**Q.** Infosys gapped down on results and then drifted. Did the gap act as resistance on the next two rallies?

- Entities: INFY (INE009A01021)
- Period: Q2FY26 · as-of: 2026-09-24 · answer: explanation
- Evidence: px_nse high/low; gap edges; volume
- Steps: mark the gap zone -> check each later high against it -> report touches and rejections
- Forbidden: drawing the zone from the wrong session
- Coverage: **yes** — PIT yes
- Why: gap-as-resistance is a standard technical read

### RD-T-028 · ta_gap · family NEW:technical_setup · `ta_gap_event`

**Q.** HDFC Bank opened with a gap after the budget. Was it a breakaway gap or an exhaustion gap, and what did volume say?

- Entities: HDFCBANK (INE040A01034)
- Period: budget 2026 · as-of: 2026-09-24 · answer: explanation
- Evidence: px_nse open/high/low; volume vs median; prior trend
- Steps: measure gap size -> check volume and prior run-up -> give the classification with the rule used
- Forbidden: labelling the gap after seeing the next month
- Coverage: **partial** — PIT yes; breakaway vs exhaustion is a rule the analyst must state
- Why: budget-day gap classification is a real retail habit

### RD-T-029 · ta_gap · family NEW:technical_setup · `ta_gap_event`

**Q.** Eternal gapped up on a big delivery day. How much of the gap held by the close, and did delivery confirm it?

- Entities: ETERNAL (INE758T01015)
- Period: 2026 · as-of: 2026-09-24 · answer: fact
- Evidence: px_nse open/close/low; delivery %
- Steps: measure the gap -> measure the close retention -> compare delivery with the median
- Forbidden: using the intraday high as the gap retention
- Coverage: **yes** — PIT yes
- Why: gap plus delivery is a common combination question

### RD-T-030 · ta_gap · family NEW:technical_setup · `ta_gap_event`

**Q.** Paytm has had several earnings gaps. Which ones filled within a month, and did the unfilled ones share a volume signature?

- Entities: PAYTM (INE982J01020)
- Period: 2022-2026 · as-of: 2026-09-24 · answer: fact
- Evidence: px_nse; earnings dates from results_xbrl; volume; delivery
- Steps: list earnings gaps -> classify fill/no-fill -> compare volume on each
- Forbidden: choosing the fill window per event
- Coverage: **partial** — PIT yes; earnings dates are held, the gap label is derived
- Why: asks for a pattern across events, not one chart

### RD-T-031 · ta_relative_strength · family NEW:technical_setup · `ta_relative_strength`

**Q.** HDFC Bank has underperformed the Nifty for a quarter. Is the relative strength turning, and what would confirm it?

- Entities: HDFCBANK (INE040A01034)
- Period: Q1FY27-Q2FY27 · as-of: 2026-09-24 · answer: explanation
- Evidence: px_nse; fii_dii_cash Nifty close; 1m/3m relative return
- Steps: compute RS ratio -> find the trend break -> name two confirmation conditions
- Forbidden: calling a one-week bounce a turn
- Coverage: **partial** — PIT yes for Nifty close; sector indices are not in store
- Why: relative strength vs index is a top swing-trading question

### RD-T-032 · ta_relative_strength · family NEW:technical_setup · `ta_relative_strength`

**Q.** BEL versus the Nifty: how strong is the relative strength, and has it been led by earnings upgrades or by the defence theme?

- Entities: BEL (INE263A01024)
- Period: 2024-2026 · as-of: 2026-09-24 · answer: explanation
- Evidence: px_nse; Nifty close; earnings dates and EPS trend; sector peers
- Steps: compute RS percentile -> align with earnings dates -> separate theme days from earnings days
- Forbidden: attributing all RS to the theme without the EPS check
- Coverage: **partial** — PIT yes; no sector index to decompose further
- Why: the 'is it strong for a reason' version of RS

### RD-T-033 · ta_relative_strength · family NEW:technical_setup · `ta_relative_strength`

**Q.** ITC has been a relative laggard while defensives rallied. What does the RS line say about rotation into or out of the stock?

- Entities: ITC (INE154A01025)
- Period: 2026 · as-of: 2026-09-24 · answer: explanation
- Evidence: px_nse; Nifty close; peers in FMCG if held
- Steps: plot RS -> identify the rotation window -> compare with peers' RS
- Forbidden: calling rotation from one stock without peers
- Coverage: **partial** — PIT yes; no FMCG index series
- Why: sector-rotation questions arrive as relative strength

### RD-T-034 · ta_relative_strength · family NEW:technical_setup · `ta_relative_strength`

**Q.** Tata Power has outperformed the Nifty for six months. Is the RS at an extreme that historically mean-reverts?

- Entities: TATAPOWER (INE245A01021)
- Period: 2021-2026 · as-of: 2026-09-24 · answer: fact
- Evidence: px_nse; Nifty close; RS percentile history
- Steps: compute the RS percentile -> find prior extremes -> measure forward RS
- Forbidden: using a fixed threshold without checking history
- Coverage: **partial** — PIT yes; the index series is available but sector-less
- Why: RS-extreme mean reversion is a real quant-retail question

### RD-T-035 · ta_relative_strength · family NEW:technical_setup · `ta_relative_strength`

**Q.** DMart versus Trent: which has the better six-month relative strength against the Nifty, and does it match the earnings trend?

- Entities: DMART (INE192R01011), TRENT (INE849A01020)
- Period: 2026 · as-of: 2026-09-24 · answer: ranking
- Evidence: px_nse; Nifty close; results_xbrl revenue growth
- Steps: compute RS for both -> compare with revenue growth -> say whether price leads or lags
- Forbidden: comparing RS without a common window
- Coverage: **partial** — PIT yes; no retail sector index
- Why: pair-relative strength plus fundamentals in one ask

### RD-T-036 · ta_oi_buildup · family NEW:technical_setup · `ta_oi_pcr_maxpain`

**Q.** Reliance futures added open interest while price rose. Is that long build-up or short covering, and what does the rollover say?

- Entities: RELIANCE (INE002A01018)
- Period: 2026-09 expiry · as-of: 2026-09-24 · answer: fact
- Evidence: futures price and open interest by expiry; rollover %; spot-futures basis
- Steps: split OI change into price-up and price-down days -> classify long build-up vs short covering -> report rollover
- Forbidden: calling any OI rise bullish
- Coverage: **no** — NOT IN DATA: no daily OI/rollover table is held
- Why: OI build-up is a top-5 technical ask and we hold none of it

### RD-T-037 · ta_oi_buildup · family NEW:technical_setup · `ta_oi_pcr_maxpain`

**Q.** HDFC Bank futures are at a premium to spot into expiry. Is the basis widening, and what has that meant for the stock after expiry?

- Entities: HDFCBANK (INE040A01034)
- Period: 2026-09 expiry · as-of: 2026-09-24 · answer: fact
- Evidence: spot close; futures close per expiry; basis history
- Steps: compute basis by session -> compare with the prior expiry -> measure post-expiry return
- Forbidden: using a stale futures price
- Coverage: **no** — NOT IN DATA: no futures close series
- Why: basis/rollover questions cannot be answered today

### RD-T-038 · ta_oi_buildup · family NEW:technical_setup · `ta_oi_pcr_maxpain`

**Q.** SBI saw a large OI addition at a strike above spot. Is that a ceiling the market expects, or a hedge?

- Entities: SBIN (INE062A01020)
- Period: 2026-09 expiry · as-of: 2026-09-24 · answer: explanation
- Evidence: option chain OI by strike; put-call ratio; max pain
- Steps: show OI concentration by strike -> compute PCR -> state what the positioning implies
- Forbidden: calling OI at a strike 'resistance' without the flow side
- Coverage: **no** — NOT IN DATA: no option chain or OI table
- Why: strike-OI interpretation is asked constantly

### RD-T-039 · ta_oi_buildup · family NEW:technical_setup · `ta_oi_pcr_maxpain`

**Q.** Bajaj Finance: did shorts cover into the recent rally, and how much OI is left going into results?

- Entities: BAJFINANCE (INE296A01032)
- Period: Q2FY26 results · as-of: 2026-09-24 · answer: fact
- Evidence: futures OI change; price; rollover; event date
- Steps: show OI change into the event -> classify covering vs new longs -> state the residual OI
- Forbidden: inferring short covering from price alone
- Coverage: **no** — NOT IN DATA: no OI series
- Why: pre-result positioning is a real retail question

### RD-T-040 · ta_oi_buildup · family NEW:technical_setup · `ta_oi_pcr_maxpain`

**Q.** ICICI Bank's rollover was lower than last expiry. Does that mean traders are exiting, or just moving to the next series early?

- Entities: ICICIBANK (INE090A01021)
- Period: 2026-09 expiry · as-of: 2026-09-24 · answer: explanation
- Evidence: rollover % by expiry; OI; volume
- Steps: compute rollover -> compare with the prior three expiries -> check whether OI moved to the next series
- Forbidden: reading low rollover as bearish without the next-series OI
- Coverage: **no** — NOT IN DATA: no rollover table
- Why: rollover interpretation is a standard expiry-week ask

### RD-T-041 · ta_pcr_maxpain · family NEW:technical_setup · `ta_oi_pcr_maxpain`

**Q.** What is the Nifty's put-call ratio today, and is it at a level that has marked short-term bottoms?

- Entities: HDFCBANK (INE040A01034), RELIANCE (INE002A01018), ICICIBANK (INE090A01021)
- Period: 2026-09 · as-of: 2026-09-24 · answer: fact
- Evidence: index option OI by strike; PCR history; Nifty close
- Steps: compute PCR -> compare with history -> state the percentile
- Forbidden: mixing OI PCR with volume PCR
- Coverage: **no** — NOT IN DATA: index options and OI are not ingested
- Why: PCR is the single most-asked derivatives question in Indian retail

### RD-T-042 · ta_pcr_maxpain · family NEW:technical_setup · `ta_oi_pcr_maxpain`

**Q.** BANKNIFTY max pain is below spot into expiry. How often does the index actually drift to max pain?

- Entities: HDFCBANK (INE040A01034), ICICIBANK (INE090A01021), SBIN (INE062A01020)
- Period: 2025-2026 · as-of: 2026-09-24 · answer: fact
- Evidence: strike OI; max-pain calculation; expiry closes
- Steps: compute max pain per expiry -> compare expiry close -> report hit rate
- Forbidden: presenting max pain as a forecast
- Coverage: **no** — NOT IN DATA: no option chain, no index history table
- Why: max-pain hit-rate is a real question nobody can answer from our data

### RD-T-043 · ta_pcr_maxpain · family NEW:technical_setup · `ta_oi_pcr_maxpain`

**Q.** Reliance has huge call OI at a round strike. Is that a real ceiling or just a hedge by institutions?

- Entities: RELIANCE (INE002A01018)
- Period: 2026-09 expiry · as-of: 2026-09-24 · answer: explanation
- Evidence: call/put OI by strike; delivery data on the cash side; FII flows
- Steps: show the strike concentration -> check cash-market delivery -> state the two interpretations
- Forbidden: asserting one interpretation without flow evidence
- Coverage: **partial** — cash data is held; option OI is NOT IN DATA, so only the cash half can be shown
- Why: tests whether the cash leg alone can support a derivatives claim

### RD-T-044 · ta_pcr_maxpain · family NEW:technical_setup · `ta_oi_pcr_maxpain`

**Q.** HDFC Bank expiry-day volume spikes every month. How much of the monthly volume is expiry-driven, and does the cash market see it too?

- Entities: HDFCBANK (INE040A01034)
- Period: 2025-2026 · as-of: 2026-09-24 · answer: fact
- Evidence: px_nse volume by date; expiry calendar
- Steps: classify expiry days -> compare volume with non-expiry -> state the share
- Forbidden: using monthly totals without the expiry split
- Coverage: **yes** — PIT yes for cash volume; expiry calendar must be constructed from the last-Thursday rule
- Why: expiry-flow questions can be partly answered from cash volume

### RD-T-045 · ta_pcr_maxpain · family NEW:technical_setup · `ta_oi_pcr_maxpain`

**Q.** ICICI Bank's put-call ratio flipped two days before expiry. Did the cash market's delivery and price confirm the same direction?

- Entities: ICICIBANK (INE090A01021)
- Period: 2026-09 expiry · as-of: 2026-09-24 · answer: explanation
- Evidence: daily_price_delivery delivery %/close; option PCR (not held); expiry calendar
- Steps: state what the cash data shows for those two days -> say explicitly that the PCR half is NOT IN DATA
- Forbidden: claiming the PCR move corroborates the cash move without an OI table
- Coverage: **partial** — only the cash leg can be answered; PCR is NOT IN DATA
- Why: tests whether a derivatives claim can be half-answered honestly

### RD-T-046 · ta_delivery_spike · family NEW:technical_setup · `ta_delivery_spike`

**Q.** Suzlon printed a delivery spike at a 52-week high. Was the spike genuine accumulation or a single block transfer?

- Entities: SUZLON (INE040H01021)
- Period: 2026 · as-of: 2026-09-24 · answer: explanation
- Evidence: daily_price_delivery delivery_qty/delivery_pct; px_nse volume; bulk/block deals in announcements
- Steps: compute delivery z-score -> check the deal prints that day -> separate block from market delivery
- Forbidden: calling every delivery spike accumulation
- Coverage: **partial** — PIT yes; deal prints are incomplete
- Why: delivery-spike interpretation is a top Indian retail tell

### RD-T-047 · ta_delivery_spike · family NEW:technical_setup · `ta_delivery_spike`

**Q.** Yes Bank's delivery % jumped above 60% for two days. What was the volume, and did the price hold the move?

- Entities: YESBANK (INE528G01035)
- Period: 2026 · as-of: 2026-09-24 · answer: fact
- Evidence: daily_price_delivery delivery_pct/volume; px_nse close
- Steps: find the spike days -> compare volume with median -> show the next five closes
- Forbidden: reading high delivery % without the absolute quantity
- Coverage: **yes** — PIT yes
- Why: high delivery % on a low-priced stock is asked constantly

### RD-T-048 · ta_delivery_spike · family NEW:technical_setup · `ta_delivery_spike`

**Q.** Vodafone Idea's delivery percentage has been falling while volume rises. What does that pattern usually precede?

- Entities: IDEA (INE669E01016)
- Period: 2025-2026 · as-of: 2026-09-24 · answer: explanation
- Evidence: delivery %; volume; forward returns
- Steps: define the pattern -> find prior instances -> report forward returns with n
- Forbidden: stating a rule without testing it
- Coverage: **partial** — PIT yes; sample may be small
- Why: the volume-up/delivery-down warning is widely repeated

### RD-T-049 · ta_delivery_spike · family NEW:technical_setup · `ta_delivery_spike`

**Q.** Jaiprakash Power's delivery spike came on a circuit day. Is delivery data even meaningful when the price is locked?

- Entities: JPPOWER (INE351F01018)
- Period: 2025-2026 · as-of: 2026-09-24 · answer: explanation
- Evidence: price_bands; delivery_qty/volume; circuit-locked detection
- Steps: mark locked sessions -> compare delivery on locked vs normal days -> state the limitation
- Forbidden: treating locked-day delivery as a free-market signal
- Coverage: **yes** — PIT yes; the limitation is part of the answer
- Why: combines band and delivery, a real small-cap question

### RD-T-050 · ta_delivery_spike · family NEW:technical_setup · `ta_delivery_spike`

**Q.** RVNL had three delivery spikes in a month with no price progress. Is that distribution or absorption?

- Entities: RVNL (INE415G01027)
- Period: 2026 · as-of: 2026-09-24 · answer: explanation
- Evidence: delivery; volume; close range; shareholding if available
- Steps: show the spikes on the price path -> check whether closes clustered -> state the two readings and the missing evidence
- Forbidden: calling distribution without the seller side
- Coverage: **partial** — PIT yes; no participant-level flow
- Why: distribution-vs-absorption is a real swing-trading question

## Pattern-gap questions (11 mined patterns with no rows)

### RD-G-001 · fno_vs_cash_flow · family 9 · `fno_vs_cash_flow`

**Q.** BHEL: did delivery strengthen in expiry week?

- Entities: BHEL (INE257A01026)
- Period: 2026-10 expiry · as-of: 2026-10-23 · answer: fact
- Evidence: px_nse close/volume for the expiry week and the four weeks before; daily_price_delivery deliverable_volume, delivery_pct and delivery_spike_ratio; bulk_block_deals for the same sessions
- Steps: fix the expiry week -> compare delivery % with its own four-week base -> check block and bulk prints -> state what the cash tape can and cannot show
- Forbidden: reading a delivery uptick as proof of futures unwinding; quoting OI that no held store carries
- Coverage: **partial** — cash tape is held and dated; futures OI, rollover and IV are not in any held table
- Why: expiry-week delivery is the cash-market stand-in retail uses for positioning

### RD-G-002 · fno_vs_cash_flow · family 15 · `fno_vs_cash_flow`

**Q.** Market-wide, does cash volume really pick up in expiry week or is that a story retail keeps repeating?

- Entities: index:NIFTY50
- Period: 2024-2026 · as-of: 2026-10-23 · answer: explanation
- Evidence: px_nse turnover by session; daily_price_delivery total_volume; nse_index_breadth for the same dates
- Steps: split sessions into expiry and non-expiry -> compare median turnover -> give the ratio and the sample size
- Forbidden: using one expiry week as the answer; implying a derivatives comparison the store cannot support
- Coverage: **partial** — cash volume is held point-in-time; there is no derivatives volume to compare against
- Why: the expiry-week volume claim is repeated as fact but never tested on our tape

### RD-G-003 · fno_vs_cash_flow · family 9 · `fno_vs_cash_flow`

**Q.** Which Nifty 50 constituents kept their cash-market delivery above average through the September expiry?

- Entities: index:NIFTY50
- Period: 2026-09 expiry · as-of: 2026-10-23 · answer: list
- Evidence: daily_price_delivery delivery_pct per constituent; index_membership as_of 2026-09-30; px_nse
- Steps: take the index list for the expiry month -> compute each name's delivery against its own base -> rank the names that held
- Forbidden: using today's constituent list for a past expiry
- Coverage: **partial** — membership is a dated snapshot; only the cash leg can be scored without an F&O store
- Why: index-level positioning is asked, but only the cash side is answerable

### RD-G-004 · fno_vs_cash_flow · family 10 · `fno_vs_cash_flow`

**Q.** Idea ka futures premium dekh kar cash mein lena theek hai kya, ya rollover cost kha jayega?

- Entities: IDEA (INE669E01016)
- Period: 2026-10 expiry · as-of: 2026-10-23 · answer: explanation
- Evidence: px_nse close and daily_price_delivery for the last two expiries; announcement text on the capital raise
- Steps: say the futures premium is not in the store -> answer from cash price and delivery -> name the cost the asker is guessing at
- Forbidden: giving a yes/no entry call; inventing a rollover percentage
- Coverage: **partial** — cash price and delivery are held; premium, rollover and cost of carry are not
- Why: the 'premium means buy the cash stock' shortcut is a frequent retail leap

### RD-G-005 · fno_vs_cash_flow · family 11,9 · `fno_vs_cash_flow`

**Q.** As of 23 Oct 2026, was Reliance's delivery percentage higher on expiry sessions than on ordinary ones this month?

- Entities: RELIANCE (INE002A01018)
- Period: 2026-10 · as-of: 2026-10-23 · answer: fact
- Evidence: daily_price_delivery delivery_pct and delivery_spike_ratio; px_nse volume; session calendar
- Steps: mark the expiry sessions -> compare delivery % with the month's other sessions -> report the difference, not a verdict
- Forbidden: mixing this month's sessions with a longer window
- Coverage: **partial** — the cash leg is dated; no F&O store can explain why delivery moved
- Why: point-in-time expiry questions test the tape and our refusal to guess the derivative side

### RD-G-006 · global_cue_overnight · family 15,9 · `global_cue_overnight`

**Q.** Market-wide, which sessions opened with the widest gap after a US sell-off, and how much of it survived to the close?

- Entities: index:NIFTY50
- Period: 2024-2026 · as-of: 2026-10-23 · answer: ranking
- Evidence: px_nse open/prev_close per session; mkt_nse_index_daily open/close; nse_index_breadth
- Steps: define the overnight proxy (no US series is held) -> rank the domestic open gaps -> measure how much closed
- Forbidden: claiming a US link without a held US series; picking the gap threshold after the result
- Coverage: **partial** — domestic gaps are computable; the overseas cue series behind them is not held
- Why: the overnight-gap question is the most common macro framing retail uses

### RD-G-007 · global_cue_overnight · family 11,9 · `global_cue_overnight`

**Q.** As of 30 Sep 2026, which index constituents had gapped more than 2% after a positive US close, and did delivery confirm the gap?

- Entities: index:NIFTY50
- Period: 2026-09 · as-of: 2026-09-30 · answer: list
- Evidence: px_nse open/prev_close; daily_price_delivery delivery_pct; index_membership 2026-09-30
- Steps: state the gap rule -> find the gap-up sessions -> check delivery on the same rows -> name what cannot be attributed
- Forbidden: attributing every gap to the US session; using an intraday print
- Coverage: **partial** — gap and delivery are dated; no US close series, so the cause stays unproven
- Why: tests whether the gap-and-delivery story can be told without inventing the overseas cause

### RD-G-008 · global_cue_overnight · family 15 · `global_cue_overnight`

**Q.** TCS ka ADR raat ko gir gaya, to cash market mein kal gap-down kitna hoga — iska koi pattern hai kya?

- Entities: TCS (INE467B01029)
- Period: 2024-2026 · as-of: 2026-10-23 · answer: explanation
- Evidence: px_nse open/prev_close for two years; daily_price_delivery; no ADR series in any store
- Steps: say the ADR series is not held -> measure TCS's own historical gap distribution -> answer what the tape supports
- Forbidden: promising a gap size from an overseas move that is not stored
- Coverage: **partial** — ADR/GDR quotes are not held; only the domestic gap history is
- Why: retail asks the overnight-ADR question as if a stored link exists

### RD-G-009 · global_cue_overnight · family 16,19 · `global_cue_overnight`

**Q.** Brent rose 6% on Friday. How much of that reached the Nifty open on Monday, and which input-cost lines felt it first?

- Entities: commodity:BRENT
- Period: 2026-10 · as-of: 2026-10-23 · answer: explanation
- Evidence: mkt_commodity_daily Brent (ends 2026-10-06, no known_at); mkt_nse_index_daily open; policy_events for duty changes
- Steps: state the commodity series' end date -> show the index open around it -> list who bears the input cost before claiming transmission
- Forbidden: using a commodity series that stops before the date asked; assuming pass-through
- Coverage: **partial** — commodity series are held without a point-in-time stamp and stop at 2026-10-06
- Why: crude-to-market transmission is the second-order question retail actually asks

### RD-G-010 · global_cue_overnight · family 19,15 · `global_cue_overnight`

**Q.** Which listed sectors usually follow the US tech tape the next morning, and does the link still hold in 2026?

- Entities: sector:NIFTY_IT
- Period: 2024-2026 · as-of: 2026-10-23 · answer: ranking
- Evidence: mkt_nse_index_daily sector indices; px_nse; no US index series held
- Steps: state the proxy for the overseas tape -> compare next-session sector moves by year -> report the sample and what is missing
- Forbidden: claiming a stable link from a few sessions; naming a US series we do not hold
- Coverage: **partial** — sector indices are dated; the overseas cue series is absent
- Why: the 'IT follows Nasdaq' belief is repeated constantly and can only be half-tested

### RD-G-011 · dividend_record_date · family 12,9 · `dividend_record_date`

**Q.** IRFC declared a Re 1.15 interim dividend with an ex-date of 23 Oct 2026 — who was on the register, and how did the stock trade into it?

- Entities: IRFC (INE053F01010)
- Period: 2026-10 · as-of: 2026-10-23 · answer: date
- Evidence: corporate_actions ex_date/rec_date/subject; px_nse close around the date; daily_price_delivery
- Steps: read the ex and record dates -> state the register rule -> show the price path into the ex-date
- Forbidden: confusing the announcement date with the record date
- Coverage: **yes** — both dates are stored; the payout sits in the action subject text
- Why: ex-date versus record-date confusion dominates the dividend threads

### RD-G-012 · dividend_record_date · family 4 · `dividend_record_date`

**Q.** List the listed companies that went ex-dividend in the week of 19 Oct 2026, with the amount each declared.

- Entities: market:NSE_EQ
- Period: 2026-10-19/2026-10-23 · as-of: 2026-10-18 · answer: list
- Evidence: corporate_actions action_type and ex_date; the subject text carries amount per share
- Steps: filter the week's ex-dates -> read the amount from the subject -> flag any row where the text has no amount
- Forbidden: assuming every corporate action is a dividend
- Coverage: **yes** — dates are structured; amount per share is only in the subject text
- Why: the weekly ex-dividend list is a repeated community post

### RD-G-013 · dividend_record_date · family 12,10 · `dividend_record_date`

**Q.** Oberoi Realty ka dividend kal ex ho raha hai — record date aur ex-date mein difference kyu hai, aur mujhe kya dekhna chahiye?

- Entities: OBEROIRLTY (INE093I01010)
- Period: 2026-10 · as-of: 2026-10-21 · answer: explanation
- Evidence: corporate_actions ex_date/rec_date; px_nse close; announcement text
- Steps: list both dates -> explain the settlement gap -> show what the price did on the previous ex-dates
- Forbidden: turning a date question into a buy call
- Coverage: **partial** — dates and prices are held; the settlement rule is market practice, not a stored field
- Why: Hinglish date questions are common and often hide a settlement or tax worry

### RD-G-014 · dividend_record_date · family 11,12 · `dividend_record_date`

**Q.** As of 20 Oct 2026, what had 360 ONE announced about its interim payout, and when did it go ex?

- Entities: 360ONE (INE466L01038)
- Period: FY27 · as-of: 2026-10-20 · answer: fact
- Evidence: corporate_actions subject/ex_date/rec_date; bse_announcements for the declaration; px_nse
- Steps: order the declaration before the answer date -> read the payout -> give the ex-date
- Forbidden: using a declaration filed after the as-of date
- Coverage: **yes** — declaration, amount and ex-date are all dated
- Why: tests point-in-time discipline on an event asked about the same week

### RD-G-015 · dividend_record_date · family 2,4 · `dividend_record_date`

**Q.** Among listed PSU banks, which paid an interim dividend in the September quarter, and how much per share?

- Entities: sector:PSU_BANKS
- Period: Q2FY27 · as-of: 2026-10-23 · answer: list
- Evidence: corporate_actions dividend rows; master_companies sector/industry for the PSU set
- Steps: fix the PSU bank list -> pull the quarter's dividend actions -> show amount per share from the subject
- Forbidden: treating a special dividend as ordinary; guessing the PSU tag
- Coverage: **partial** — the payout text is held; there is no amount_per_share column
- Why: dividend screening inside a sector is a repeated ask

### RD-G-016 · penny_low_price_stock · family 4,9 · `penny_low_price_stock`

**Q.** On 23 Oct 2026, which names were still stuck in a 5% or lower price band on heavy volume?

- Entities: market:NSE_EQ
- Period: 2026-10 · as-of: 2026-10-23 · answer: list
- Evidence: price_bands band/date; daily_price_delivery total_volume and delivery_pct; master_companies market_cap_tier
- Steps: filter bands to 5% or lower on the date -> keep names with above-median volume -> report band and turnover
- Forbidden: calling a band stock cheap; ignoring that a band caps the move
- Coverage: **yes** — band and turnover are dated rows
- Why: band-stuck names are the raw material of penny threads

### RD-G-017 · penny_low_price_stock · family 10 · `penny_low_price_stock`

**Q.** Penny stocks: is a 5% or lower band a trap?

- Entities: market:NSE_EQ
- Period: 2024-2026 · as-of: 2026-10-23 · answer: explanation
- Evidence: price_bands band history; px_nse one-year path; annual_financials for survival
- Steps: measure how often band names stayed there -> show the one-year return distribution -> answer with a base rate, not a view
- Forbidden: a one-line yes or no; quoting a single name as the case
- Coverage: **partial** — band history and prices are held; 'trap' needs a rule the answer must state
- Why: the opinion question that precedes most penny-stock buying

### RD-G-018 · penny_low_price_stock · family 10,13 · `penny_low_price_stock`

**Q.** Micro-cap names under Rs 20 look cheap — is that value, or just a float too small to trust?

- Entities: market-cap bucket:MICRO
- Period: 2024-2026 · as-of: 2026-10-23 · answer: explanation
- Evidence: px_nse close; daily_price_delivery turnover_lacs; master_companies market_cap_tier; annual_financials
- Steps: define the micro-cap set by tier -> split by turnover -> compare returns and survival -> state the rule used
- Forbidden: equating a low price with a cheap valuation
- Coverage: **partial** — price and turnover are held; free float is not a stored column
- Why: price-per-share confusion is the core penny-stock misunderstanding

### RD-G-019 · penny_low_price_stock · family 11,3 · `penny_low_price_stock`

**Q.** As of 23 Oct 2026, GTL Infra had closed at its upper price band on how many of the last 20 sessions?

- Entities: GTLINFRA (INE221H01019)
- Period: 2026-09/2026-10 · as-of: 2026-10-23 · answer: fact
- Evidence: price_bands band per session; daily_price_delivery close and volume
- Steps: take the 20 sessions before the as-of date -> count upper-band closes -> show the path
- Forbidden: reading a band cap as demand without volume
- Coverage: **yes** — per-session bands are stored and dated
- Why: counts of band hits are asked as a proxy for stuck demand

### RD-G-020 · penny_low_price_stock · family 10 · `penny_low_price_stock`

**Q.** Yes Bank 15 rupaye par hai — sasta lag raha hai ya bas sasta dikh raha hai, aur delivery se kya samajhna?

- Entities: YESBANK (INE528G01035)
- Period: FY26/FY27 · as-of: 2026-10-23 · answer: explanation
- Evidence: px_nse close history; daily_price_delivery delivery_pct; annual_financials book value and P/B inputs
- Steps: separate price per share from valuation -> show book value and P/B -> read delivery as participation, not value
- Forbidden: calling a Rs 15 stock cheap without a valuation basis
- Coverage: **partial** — price and delivery are held; the valuation percentile history is not
- Why: the most common penny-stock phrasing, with delivery bolted on

### RD-G-021 · macro_event_what_if · family 18,6 · `macro_event_what_if`

**Q.** If the RBI cuts the repo rate by 25bp in December, which listed lenders reprice deposits first and by how much?

- Entities: policy:RBI_REPO
- Period: 2026-12 · as-of: 2026-10-28 · answer: explanation
- Evidence: policy_events for the rate action; results_xbrl NIM and interest income; concall_facts for repricing commentary
- Steps: state the assumed cut -> trace deposit then lending repricing -> give the lag the filings state, not a guess
- Forbidden: assuming a cut is immediately margin-positive; inventing a repricing beta
- Coverage: **partial** — rate actions and filed NIM are held; there is no deposit-repricing schedule
- Why: forward rate questions are asked as if a rate table exists

### RD-G-022 · macro_event_what_if · family 19,16 · `macro_event_what_if`

**Q.** If crude holds above $90 for a quarter, how does that reach second-round input costs down the listed chain?

- Entities: commodity:BRENT
- Period: FY27 · as-of: 2026-10-28 · answer: explanation
- Evidence: mkt_commodity_daily Brent; ar_facts raw-material notes; policy_events for duty; concall_facts cost commentary
- Steps: anchor the assumption -> separate direct fuel cost from second-round freight and packaging -> say where the chain breaks
- Forbidden: assuming every manufacturer is equally exposed; using a series without known_at as if it were point-in-time
- Coverage: **partial** — the commodity series has no known_at and stops at 2026-10-06; no cost-share table
- Why: the 'if crude stays high' question is the most common what-if in macro threads

### RD-G-023 · macro_event_what_if · family 18,6 · `macro_event_what_if`

**Q.** Which listed sectors re-price fastest if the government raises the PLI outlay again?

- Entities: sector:PLI_SECTORS
- Period: FY27 · as-of: 2026-10-28 · answer: ranking
- Evidence: policy_events amount/sectors/effective dates; ripple_effects; master_companies industry
- Steps: read the last PLI actions and their sectors -> list who actually booked incentives -> separate announcement from accrual
- Forbidden: naming a sector from the press release alone; ignoring the incentive-to-revenue lag
- Coverage: **partial** — policy events are held; incentive accrual by company is only in filing text
- Why: policy-forward questions invite a sector ranking that the data can only partly support

### RD-G-024 · macro_event_what_if · family 11,19 · `macro_event_what_if`

**Q.** As of 28 Oct 2026, what would a 10% copper price rise do to third-round costs of the average listed user?

- Entities: commodity:COPPER
- Period: FY27 · as-of: 2026-10-28 · answer: explanation
- Evidence: mkt_commodity_daily copper; ar_facts cost notes; ripple_effects for the chain
- Steps: state the copper assumption -> map the first layer of users -> name the third layer and say no cost table exists for it
- Forbidden: inventing an elasticity; mixing a dated assumption with older commodity rows
- Coverage: **partial** — copper series ends 2026-10-06; the chain beyond the first layer has no held cost map
- Why: third-order what-ifs are exactly where a bank should refuse to improvise

### RD-G-025 · macro_event_what_if · family 19,18 · `macro_event_what_if`

**Q.** Which listed sectors gain most if the 10-year yield falls 50bp, and which lose on the second round?

- Entities: sector:RATE_SENSITIVES
- Period: 2024-2026 · as-of: 2026-10-28 · answer: ranking
- Evidence: mkt_nse_index_daily sector indices; mkt_fii_dii_cash; px_nse for the rate-sensitive set
- Steps: list the rate-sensitive sectors -> show their response to past rate moves in the tape -> state the second-round loser logic
- Forbidden: assuming a yield fall is uniformly good for banks; quoting a gilt series we do not hold
- Coverage: **partial** — index prices and FII/DII flows are held; no gilt yield series exists
- Why: yield-led sector rotation is asked as if yields were in the store

### RD-G-026 · ta_chart_pattern · family 10,3 · `ta_chart_pattern`

**Q.** Polycab looks like a cup-and-handle on the weekly chart — did the same shape in the last year lead to a breakout or a fade?

- Entities: POLYCAB (INE455K01017)
- Period: 2025-10/2026-10 · as-of: 2026-10-23 · answer: explanation
- Evidence: px_nse weekly resample; daily_price_delivery volume; no pattern_match table
- Steps: define the shape before looking -> label past windows with the same rule -> report follow-through
- Forbidden: naming the pattern after the breakout; treating one past case as the base rate
- Coverage: **partial** — OHLCV is held; no labelled chart-pattern store exists
- Why: the named-pattern question has no family and cannot be answered from a stored label

### RD-G-027 · ta_chart_pattern · family 3,11 · `ta_chart_pattern`

**Q.** As of 23 Oct 2026, had BHEL built a higher-highs base or a lower-highs distribution over the last 60 sessions?

- Entities: BHEL (INE257A01026)
- Period: 2026-07/2026-10 · as-of: 2026-10-23 · answer: explanation
- Evidence: px_nse highs/lows; daily_price_delivery volume; sma_50 stored on the delivery tape
- Steps: fix the 60-session window before the as-of date -> compare swing highs -> report the shape and the volume behind it
- Forbidden: choosing the window after seeing the chart; calling a pullback a distribution
- Coverage: **partial** — price shape is derivable and dated; pattern labels are not stored
- Why: asks for structure rather than a pattern name, which the tape can support

### RD-G-028 · ta_chart_pattern · family 3,10 · `ta_chart_pattern`

**Q.** PSU banks ke chart par higher-highs base ban raha hai kya, ya sirf ek bounce hai?

- Entities: sector:PSU_BANKS
- Period: 2025-10/2026-10 · as-of: 2026-10-23 · answer: explanation
- Evidence: px_nse for the PSU bank set; mkt_nse_index_daily; daily_price_delivery
- Steps: resample monthly -> compare the last two swing highs -> show volume and delivery behind each
- Forbidden: counting one green month as a base
- Coverage: **partial** — prices are held; the pattern label and the sector membership history are partial
- Why: the Hinglish chart read is common and can be answered with a stated rule

### RD-G-029 · theme_proxy_play · family 8,19 · `theme_proxy_play`

**Q.** In the data-centre theme, which listed cooling and cabling names give the cleanest proxy without owning the hyperscaler risk?

- Entities: theme:DATA_CENTRES
- Period: FY26/FY27 · as-of: 2026-10-28 · answer: ranking
- Evidence: theme universe members; annual_financials segment revenue; concall_facts order commentary
- Steps: list the held theme members -> separate direct suppliers from second-order -> rank by disclosed revenue share
- Forbidden: treating a company mention in a call as theme revenue
- Coverage: **partial** — nine themes are curated and dated; revenue attribution is still from segment text
- Why: theme-proxy questions are the most common way retail asks for a basket

### RD-G-030 · theme_proxy_play · family 19,8 · `theme_proxy_play`

**Q.** Green hydrogen theme mein doosre-teesre layer ke listed plays kaun hain, aur unka revenue is theme se kitna aata hai?

- Entities: theme:GREEN_HYDROGEN
- Period: FY27 · as-of: 2026-10-28 · answer: explanation
- Evidence: theme universe members; ar_facts segment notes; concall_facts order wins; ripple_effects
- Steps: name the first layer -> name the second and third layers -> show any disclosed revenue share and flag where none exists
- Forbidden: calling any engineering company a green-hydrogen play; inventing a revenue share
- Coverage: **partial** — theme membership is curated; third-layer revenue is rarely disclosed, so the answer must say so
- Why: Hinglish layered-theme questions are the retail version of supply-chain mapping

### RD-G-031 · theme_proxy_play · family 10,8 · `theme_proxy_play`

**Q.** Gold ETFs or jewellers: which is the better proxy?

- Entities: index:GOLD_ETFS
- Period: 2024-2026 · as-of: 2026-10-23 · answer: ranking
- Evidence: etf_master/etf_px/etf_inav; px_nse for jeweller names; annual_financials
- Steps: compare total return with the metal -> compare drawdowns -> state that 'better' needs a horizon
- Forbidden: answering without a horizon; treating an ETF NAV as a stock price
- Coverage: **partial** — ETF NAV and premium are held; a 'better' ranking needs a stated horizon
- Why: the gold-exposure choice is a repeated retail question phrased as a proxy play

### RD-G-032 · merger_arbitrage · family 12,9 · `merger_arbitrage`

**Q.** The Tata Motors demerger left two listed lines — which approvals were still pending at the record date, and how did the pair trade into it?

- Entities: TMPV (INE155A01022), TMCV (INE1TAE01010)
- Period: 2025-10/2026-10 · as-of: 2026-10-23 · answer: date
- Evidence: corporate_documents and announcements for the scheme; px_nse for both lines; symbol_isin_history
- Steps: date the scheme documents -> list the approvals in order -> show both lines from listing to the record date
- Forbidden: using pre-demerger prices as if the same security; guessing an approval date
- Coverage: **partial** — scheme text and prices are held; there is no structured deal or swap table
- Why: demerger spillover questions mix process and price and no table joins them

### RD-G-033 · merger_arbitrage · family 10,12 · `merger_arbitrage`

**Q.** IDBI Bank stake sale: is the spread worth it?

- Entities: IDBI (INE008A01015)
- Period: 2026 · as-of: 2026-10-23 · answer: explanation
- Evidence: px_nse price; announcements for the process stage; the offer price only in filing text
- Steps: state the reference price -> read the process stage from filings -> say that no structured spread exists
- Forbidden: quoting a spread from a stale or invented offer price
- Coverage: **partial** — price tape is held; offer terms are text-only, so the spread must be built by hand
- Why: the deal-spread question is asked with no deal table behind it

### RD-G-034 · merger_arbitrage · family 4,12 · `merger_arbitrage`

**Q.** Among listed cement makers, which announced schemes still need an NCLT order, and what is the expected completion window?

- Entities: industry:CEMENT
- Period: 2025-2026 · as-of: 2026-10-28 · answer: list
- Evidence: bse_announcements text; corporate_documents; px_nse for the named pair
- Steps: collect the announced schemes -> read each stage -> show the next approval and the stated window
- Forbidden: assuming a board approval completes a merger; inventing a completion date
- Coverage: **partial** — schemes sit in announcement text; no deal table and no approval tracker
- Why: sector merger trackers are asked weekly in cement threads

### RD-G-035 · ipo_vs_listed_peer · family 8,2 · `ipo_vs_listed_peer`

**Q.** Swiggy listed while Eternal was already public — which multiple did the issue ask, and how did that compare with the listed peer that week?

- Entities: SWIGGY (INE00H001014), ETERNAL (INE758T01015)
- Period: 2024-11 · as-of: 2026-10-23 · answer: ranking
- Evidence: SEBI offer documents; px_nse for both; annual_financials and quarterly_financials
- Steps: read the issue price from the offer document -> compute the peer multiple on the issue date -> show both
- Forbidden: using today's multiple for the issue week; treating grey-market talk as the issue price
- Coverage: **partial** — offer documents are fetched; there is no structured ipo_issue table
- Why: the new-listing-versus-peer comparison is the standard anchor retail uses

### RD-G-036 · ipo_vs_listed_peer · family 8,13 · `ipo_vs_listed_peer`

**Q.** Which recently listed specialty-chemical names still trade below their issue valuation against the listed peer set?

- Entities: industry:SPECIALTY_CHEMICALS
- Period: 2024-2026 · as-of: 2026-10-23 · answer: ranking
- Evidence: px_nse; quarterly_financials; offer documents; peers from master_companies industry
- Steps: fix the listing window -> compute the peer multiple at issue and today -> list the names below issue valuation
- Forbidden: comparing a new listing with a large-cap peer on different accounting
- Coverage: **partial** — prices and filings are held; issue valuation is text-only and the peer table must be built
- Why: post-IPO disappointment screens are a recurring specialty-chemical thread

### RD-G-037 · ipo_vs_listed_peer · family 2,8 · `ipo_vs_listed_peer`

**Q.** Hyundai listing ke baad Maruti se valuation comparison kaunse multiple par sahi hai, aur P/E ka gap issue price mein tha kya?

- Entities: HYUNDAI (INE0V6F01027), MARUTI (INE585B01010)
- Period: 2024-10 · as-of: 2026-10-23 · answer: ranking
- Evidence: px_nse both names; quarterly_financials EPS; the offer document for the issue price
- Steps: compute the peer multiple on consistent periods -> compare with the issue multiple -> show the gap
- Forbidden: mixing standalone and consolidated earnings; using a stale EPS
- Coverage: **partial** — prices and XBRL earnings are held; the issue multiple is in the offer document text
- Why: the 'was the IPO expensive versus the incumbent' ask is a Hinglish staple

### RD-G-038 · second_order_beneficiary · family 19,8 · `second_order_beneficiary`

**Q.** If the data-centre build-out doubles, is KEI's cable order book the second-order winner or does the wiring spend land elsewhere first?

- Entities: KEI (INE878B01027)
- Period: FY26/FY27 · as-of: 2026-10-28 · answer: explanation
- Evidence: concall_facts order commentary; ar_facts segment revenue; announcements for order wins; ripple_effects
- Steps: define the assumed build-out -> place KEI on the chain -> show disclosed order wins -> name the layer that takes spend first
- Forbidden: assuming every cable order is data-centre demand
- Coverage: **partial** — order wins sit in call and announcement text; no supply_link table exists
- Why: second-order questions need the chain, not just the beneficiary

### RD-G-039 · second_order_beneficiary · family 19 · `second_order_beneficiary`

**Q.** Which listed cable makers feel a doubling of data-centre capex third, after the cooling and connector layers have taken their share?

- Entities: industry:CABLES
- Period: FY27 · as-of: 2026-10-28 · answer: ranking
- Evidence: ar_facts and concall segment text; px_nse; announcements order wins; ripple_effects
- Steps: draw three layers -> place each listed name -> state which layer has disclosed revenue
- Forbidden: calling a third-layer name a direct beneficiary; ranking without disclosed revenue
- Coverage: **partial** — the chain is in text and ripple rows; no share-of-cogs map
- Why: the third-layer question is where retail over-reaches, and the bank should test it

### RD-G-040 · second_order_beneficiary · family 11,19 · `second_order_beneficiary`

**Q.** As of 23 Oct 2026, which listed names had disclosed order wins inside the green hydrogen theme's second layer?

- Entities: theme:GREEN_HYDROGEN
- Period: FY27 · as-of: 2026-10-23 · answer: list
- Evidence: bse_announcements and concall_facts within the as-of date; ar_facts; theme universe members
- Steps: filter disclosures to the as-of date -> keep order wins -> place them on the theme's second layer
- Forbidden: using a disclosure filed after the as-of date; counting an MoU as an order
- Coverage: **partial** — announcement text is dated; the second-layer map is curated, not stored
- Why: tests point-in-time discipline on second-order evidence

### RD-G-041 · results_calendar · family 12 · `results_calendar`

**Q.** IRFC Q2 results date: when, and was it pre-intimated?

- Entities: IRFC (INE053F01010)
- Period: Q2FY27 · as-of: 2026-10-28 · answer: date
- Evidence: board_meetings meeting_date/purpose/intimated_at; results_filings for the actual filing
- Steps: read the meeting purpose -> compare intimation with the meeting date -> show both dates
- Forbidden: confusing the intimation date with the results date
- Coverage: **yes** — board_meetings holds the meeting and the intimation timestamp
- Why: the results-date-and-notice question is asked every quarter

### RD-G-042 · results_calendar · family 4,12 · `results_calendar`

**Q.** Which listed companies report Q2FY27 results in the first week of November, and how many intimated late?

- Entities: market:NSE_EQ
- Period: Q2FY27 · as-of: 2026-10-28 · answer: list
- Evidence: board_meetings meeting_date/purpose/intimated_at; results_filings
- Steps: filter the week's financial-results meetings -> compute the intimation lag -> list the late ones
- Forbidden: counting a board meeting with another purpose as a results date
- Coverage: **partial** — 120k board-meeting rows are held, but small-cap coverage is uneven
- Why: the quarterly results calendar is a repeated community post

### RD-G-043 · results_calendar · family 11,12 · `results_calendar`

**Q.** As of 20 Oct 2026, how many large-caps had still not intimated a results date for the September quarter?

- Entities: market-cap bucket:LARGE
- Period: Q2FY27 · as-of: 2026-10-20 · answer: fact
- Evidence: board_meetings within the as-of date; master_companies market_cap_tier; results_filings
- Steps: fix the large-cap list -> count those with no results meeting by the as-of date -> say what absence can and cannot prove
- Forbidden: reading a missing row as 'no results'; using intimations filed after the as-of date
- Coverage: **partial** — absence inference depends on board-meeting coverage, which is uneven
- Why: tests the calendar from the negative side, where a bank must be careful
