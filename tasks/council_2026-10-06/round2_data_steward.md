# Round 2 — Data Steward

## New read-only checks (to settle disputed facts)
1. `analysis/bse_announcements.db` (not live-written): seconds between `News_submission_dt` (company uploads to BSE) and `DissemDT` (BSE publishes) for all 139,802 "Financial Results" filings. Median 1 s, 90th percentile 13 s, 99th 61 s; 40 over an hour; 503 negative (clock noise).
2. Same file: "Financial Results" count by hour of `DissemDT` (peak 16:00–18:00; 6,311 after 21:00).
3. Same file: sub-categories under "Insider Trading / SAST" and sample headlines.
4. Live DB (`mode=ro`): table names for insider/pledge/band/ASM/GSM/F&O/suspension; row count of `insider_trades`.

## 1. Answers to questions put to me

**CRO — is `DissemDT` the real first public release?** Partly verified. BSE publishes within about a minute of the company uploading in 99% of results filings (check 1), so it is not a late re-stamp. **Unverified:** whether the company posted on NSE, or its own website, or held a press call earlier. We hold no NSE announcement timestamps. The after-21:00 gradient is therefore probably real late filing, not misdating, but an NSE cross-check on a sample of 200 is the honest test.

**CRO — cost of adding delisted stocks?** The price table already has 5,710 ISINs, and 574 stop trading before 2026-06. But I can't yet tell real delistings from ISIN changes after splits, because past rows carry today's ISIN. Fix: (a) an ISIN-history map, (b) NSE/BSE delisted lists, (c) price history for the missing names from the exchanges' archived daily price files, which list every stock traded that day. My guess is a few days of work (uncertain). **CRO — quote event-study numbers meanwhile?** Yes, but only labelled "provisional: unadjusted prices, survivors only". Don't quote CAR levels at all; the sign-free drift statistic can be quoted as provisional.

**Quant — how many delisted are missing?** Unknown until the ISIN map exists; upper bound about 574 ISINs inside our table, plus names never loaded. **Quant/Macro — results filing dates, weeks or months?** Days for the *dates*: 139,802 results filings with exact BSE timestamps are already in hand. They need mapping to a quarter, using the headline and filing month. The *numbers* as filed (BSE XBRL, the machine-readable results file for 2021–26, including the missing 2023 quarters) are a separate job: weeks (my estimate).

**Macro — do insider/SAST disclosures carry direction and size?** **No.** BSE headlines only name the filer ("received the disclosure under Regulation 29(2) ... for S D Shibulal"). Direction and size are inside the PDF. The live `insider_trades` table exists but has **0 rows** (check 4). Also, 104,090 of the category's rows are just "Closure of Trading Window". NSE's PIT insider-trading feed (buy/sell, quantity, value, acquisition and intimation dates) is the right source. It has not been loaded.

**Trading — open price, price bands, suspensions, ASM/GSM, F&O history?** Open, high and low: yes (`daily_price_delivery`), unadjusted. Price band, suspension, ASM/GSM and F&O eligibility: **no table exists**. Band hits can be approximated from high = low = close and the daily % move. Suspensions show up as missing days. ASM/GSM and F&O history need exchange archives.

## 2. Where I change position
- **Q17/Q15 holdout:** from "in-sample 2022–24, hold out 2025–26" to **siding with CRO: forward paper trading is the main holdout**. The drift has already been examined by year for 2025–26. I accept Quant's sealed 2025-10→2026-09 only for hypotheses nobody has touched, and only if the shared data loader enforces it: it cuts dates off unless a logged "unseal" flag is set. A promise is not a seal.
- **Q14 order:** I now oppose promoter buying as #2 *on data grounds* (insider table empty, SAST has no direction). It becomes #2 only after the NSE insider feed is loaded and timestamped. That is cheap, but not done.
- **Q10:** I add CRO's point: pause the writers (or confirm no python process is running) **while each snapshot is cut**. Any writer whose output no hypothesis card or the paper book needs should be paused. That is a scope call for Shivam, not a data-truth one.
- **Q9:** "DissemDT = public time" moves from unverified to **partly verified (BSE-side)**.

## 3. Where I still disagree
- **CRO on Q10 (pause the drains as the reproducibility fix).** Pausing writers does not make a result reproducible. A live file under a paused task is still mutable: someone re-enables a task, or runs a script by hand. Only a dated, checksummed copy plus the code commit makes a result re-runnable. Freezing also stops the EOD prices the forward holdout (which CRO wants) depends on. So: snapshots are mandatory, pausing is optional.
- **Trading on Q7 (spreads from daily high/low).** I agree with the method, but it needs **adjusted** high/low/close first. The Corwin–Schultz estimator (a way to infer the bid-ask spread from two consecutive days' highs and lows) uses consecutive days. On a split or bonus ex-date, unadjusted prices produce a huge fake spread exactly in the small caps where bonuses cluster. So adjustment goes first.
- **Macro PM/Quant on Q9 "corporate action partly done via `prev_close`".** Verified wrong in round 1: `prev_close` is not adjusted (BLUESTARCO −48%, GULPOLY 1:5 bonus −11.9% slips through the ±30% guard). It is a failure, not "partly done".
- **Quant on a 2025-10→2026-09 seal "now".** Shivam's DB copy on Drive and the parquet already contain it, and agents read the parquet freely. Without loader enforcement the seal will leak.

## 4. Final one-line stance, Q1–Q22
- **Q1** North star plus "on data the market actually had", plus drawdown and capacity.
- **Q2** Two books; only the event book is testable now; the fundamental book waits for filing-dated results.
- **Q3** Liquidity-floor universe as of each date (not today's Nifty 200); small caps after adjustment and delistings are fixed.
- **Q4** Long-only with avoid lists; any short-leg test needs a dated F&O list we don't hold.
- **Q5** Promotion also requires "result holds on the corrected, pinned snapshot".
- **Q6** Any benchmark must be built from the same adjusted, survivorship-aware panel.
- **Q7** Fixed, tiered, dated cost stack; spread estimates only from adjusted prices.
- **Q8** Test ledger records snapshot ID and data version; a re-run after a data fix is a new test.
- **Q9** Gate: PIT timestamps (partly, 30% undated docs excluded), adjustment (fails), ISIN map (fails), delistings (fails), dated fundamentals (fails), quarantine (passes), pinned snapshot, plus Trading's tradability checks once data exists.
- **Q10** Research only on dated, checksummed snapshots; ingestion continues; pause writers while cutting a snapshot.
- **Q11** Two dates per row (period and first public); version first adjusted prices plus ISIN map, then results filing dates, insider feed, membership/F&O, sector.
- **Q12** Set aside as undated priors; revive only rebuilt as-of-date and through a card.
- **Q13** Card also freezes data snapshot, timing field, exclusion rules and price-adjustment version.
- **Q14** Earnings-surprise post-results drift first, after filing dates and adjustment; insider buying after the NSE feed loads; concall guidance last.
- **Q15** Exploration is free but logged; confirmation on forward data, or on a loader-enforced seal.
- **Q16** Shared harness with one data loader enforcing the Q9 checks; delete per-script ±30% patches.
- **Q17** All 2021–26 history is in-sample; forward paper is the holdout; corporate actions for 2021–22 need backfill.
- **Q18** No ensemble before versioned features exist; equal-weight is enough.
- **Q19** LLM for extraction only, stamped with document time, model and prompt version; it can know what happened after an old document (look-ahead).
- **Q20** Forward paper is the cleanest PIT test; log each decision's input snapshot.
- **Q21** Freeze new feeds and lenses, except truth repairs (adjustment, ISIN map, delistings, filing dates, NSE insider feed).
- **Q22** One authority file with a maintained "data state" table; retire stale claims like "`prev_close` adjusts splits".
