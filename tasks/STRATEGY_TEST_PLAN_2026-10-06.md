# Strategies to Test Once Data Is Corrected (2026-10-06)

**Status:** draft for Shivam's review. Follows the council verdicts in `tasks/FRAMEWORK_OPEN_QUESTIONS.md` (Q14 backlog, Q5 bar, proposed order of work). Nothing here is frozen until Shivam commits a card. High level only: what we test, why it might work, what data it needs, and what kills it.

**Rules every card follows (from the verdicts):** long-only book; scored against matched peer stocks; modelled costs (~80 bp round trip) until real fills exist; gross edge ≥ 2× cost; information ratio ≥ 0.5; t ≥ 3; ≥ 30 independent date clusters over ≥ 4 results seasons; placebo ≈ 0; every year shown; results family confirmed on **forward data only**; every run logged in the test ledger, including failures.

---

## 1. Data inventory: what we have vs what must be fetched

Checked read-only on the live DB, 2026-10-06.

| Data | In the DB today | Gaps | Fetch needed? |
|---|---|---|---|
| **Splits, bonuses, dividends** (`corporate_actions`) | 8,535 actions, ex-dates **2023-01-02 → 2026-08-28**: dividends 5,625, splits 197, bonuses 189, rights 169, buybacks 107, mergers 47 | (1) **Oct 2021 – Dec 2022 missing** (prices start Oct 2021). (2) Sep–Oct 2026 not refreshed. (3) Prices carry today's ISIN, so 289 of 386 split/bonus actions don't join to price rows. (4) Rights/merger ratios sit in free text and need parsing. | **Mostly no new code.** `corporate_actions_client.py` already takes a date range (defaults to 2023-01-01); re-run it from 2021-10-01. The ISIN-history map (old ISIN → new ISIN) has to be built. Adjustment factors are then computed locally. |
| **Insider trades** (`insider_trades`, SEBI PIT disclosures) | **0 rows** | Everything. BSE takeover (SAST) headlines we hold name the filer but give no buy/sell or size. | **Yes.** `nse_client.fetch_insider_trades()` only pulls the latest NSE PIT feed; history needs a date-range fetch (small new code). How far back NSE serves it is unverified. |
| **Bulk / block deals** (`bulk_block_deals`) | **228 rows, one day only (2026-09-18)** | Everything before that. | **Yes.** `deals_client.py` reads NSE's daily `bulk.csv` / `block.csv`, which only holds the latest day. History needs a different NSE source; depth back to 2021 is unverified. |
| Surveillance (ASM/GSM), price bands, F&O eligibility | `corporate_status_flags` **0 rows**; no history | Everything | Yes, new feed (frozen until after Card B). |
| Results filing time | BSE `DissemDT` on results filings: published within ~1 minute of upload in 99% of 139,802 cases | Not cross-checked against NSE (which may publish first) | No for BSE; NSE check optional. |
| Quarterly results figures (for earnings surprise) | `quarterly_financials` exists, but council found no filing dates and 2023 quarters missing | Dated figures | Yes: XBRL results figures mapped to filing dates (order-of-work step 6). |

### 1a. Exchange coverage: BSE-only and SME stocks (checked 2026-10-06)

All prices sit in one table, `daily_price_delivery` (2021-10-27 → 2026-09-24). NSE is the main feed. `pipeline/bse_backfill.py` fills gaps with BSE prices for names that have no NSE row.

| Segment | Price coverage | Delivery data |
|---|---|---|
| **NSE main board** (series EQ) | Full: 2021-10 → 2026-09, ~2,700 stocks/day | Yes |
| **NSE trade-to-trade** (series BE) | Full | **Stored as 0, which is wrong.** BE trades are compulsorily delivered, so delivery is ~100%, not 0. Treat as missing until fixed. |
| **BSE-only stocks** (groups A/B/X/XT/T/Z…) | **Two patches only:** Apr 2023 → Apr 2024 (~2,000 stocks/day), and Jun 2026 → mid-Sep 2026 (~2,300/day). **Nothing for Oct 2021 – Mar 2023 or May 2024 – May 2026.** | **None.** Neither BSE file the backfill uses carries delivery; rows are written with delivery = 0, which reads as "no delivery" rather than "unknown". |
| **BSE SME** (groups M/MT) | Same two patches (~120–350 stocks/day) | None |
| **NSE SME / Emerge** (series SM/ST) | **None at all** | None |

**What this means:**
- Any test touching BSE-only or SME stocks has holes of up to two years. Today, effectively, every study is an NSE-main-board study.
- Delivery-based signals (delivery spike, delivery-weighted CMF) are valid **only on NSE EQ rows**. The zeros on BE and BSE rows must be treated as missing, not as zero delivery.
- **Fetch options (probed live 2026-10-06, sources from Shivam):**
  - **BSE prices: the whole window is available, no permanent gap.** Holidays return a ~14 KB error page instead of a file.
    - The legacy daily file (`EQ<DDMMYY>_CSV.ZIP`) is served for 2022-06-15, 2024-03-14 and through **2024-07-01**.
    - The newer UDiFF file (`BhavCopy_BSE_CM_0_0_0_<YYYYMMDD>_F_0000.CSV`) is served from at least **2024-01-03 to 2026-09-23**, but not for 2022-06-15. It is ISIN-keyed with OHLC, volume, turnover and group/series; 2025-06-17 had 4,478 rows.
    - The code's notes are wrong on two points: UDiFF is **not** limited to the last ~250 sessions, and legacy did not stop at 2024-04-18. The DB gaps exist simply because the backfill was never run for those windows.
    - Plan: legacy file for 2021-10 → 2023-12, UDiFF from 2024-01 onward.
  - **BSE delivery data: available for the full window.** The "Historical Gross Deliverables" page (`beta.bseindia.com/markets/equity/EQReports/GrossDeliverables.aspx`, "All Securities" + date) returns a zip with `SCBSEALL<DDMM>.TXT`, giving per scrip code: delivery qty, delivery value, day's volume, day's turnover and delivery %. Tested for 2021-11-01 (3,785 scrips), 2022-06-15, 2025-06-17 (4,478 scrips, matching the bhavcopy row count) and 2026-09-23 (5,059 scrips).
    - It is keyed by BSE scrip code, not ISIN, so it joins via `master_companies.bse_code`.
    - It is an ASP.NET form post, so expect one request per date with pacing. Samples are saved in the session scratchpad.
  - **NSE SME / Emerge:** separate NSE file, not fetched; history depth unverified.
- **Should we bother?** BSE-only and SME stocks are where information spreads slowest (good for edge), but most fail any sensible liquidity floor for a real book (council Q3). Recommendation: backfill BSE prices and delivery as a truth repair, so studies can measure the effect there, but keep the tradable universe set by liquidity.

**Freeze note:** split/bonus/dividend repair is on the council's exempt "truth repair" list. Insider, bulk/block and surveillance feeds are **new feeds**, so under the verdicts they wait until after Card B, unless Shivam overrides.

---

## 2. Order of testing

| Step | Card | Type | Needs data fix | Earliest start |
|---|---|---|---|---|
| 0 | Re-run the results-day puzzle on adjusted prices | Re-check, not a strategy | Corporate actions + ISIN map | After price adjustment |
| A | Pre-results timing overlay | Forward-only, freeze **this week** | No (scored on forward prices) | Now |
| B | Earnings-surprise conditioning | Main research study | Adjusted prices + dated results figures | After step 0 |
| C | Promoter open-market buying | Strategy | Insider history feed | After B |
| D | Guidance raises in concalls | Add-on to B | Dated concalls (done) + B's surprise signal | After B |
| E | Forced flows (index changes, surveillance moves) | Strategy | New feeds | After freeze lifts |
| F | Bulk/block deal accumulation | Strategy (new proposal, not voted by council) | Bulk/block history | After freeze lifts |
| G | Avoid list (forensic / solvency) | Scored as its own cohort, never traded | Adjusted prices, dated fundamentals | Alongside B |

---

## 3. The cards

### Step 0. Re-run the results-day puzzle on clean prices
- **Question:** do the −85 bp results-day gap and the late-filer gradient (−15 bp before 13:00 → −84 bp after 21:00) survive once split, bonus and ex-dividend days are adjusted or removed?
- **Why first:** dividend and bonus ex-dates often fall 2–4 weeks after a board meeting, inside the drift window. Every diffusion number is provisional until this is done.
- **Also tests** Macro's decay explanation D1 (the drift's fall from +96 bp in 2023 to −41 bp in 2026 is a bonus-day artefact).
- **Outcome:** each diffusion number is relabelled "holds" / "changed" / "gone". No promotion possible here.

### Card A. Pre-results timing overlay (forward only)
- **Idea:** on trades we already plan, don't buy in the days before a known board-meeting date, and pull planned sells/trims ahead of it. Strongest when the company is *predicted* to file late.
- **Who's on the other side:** holders who don't price in that late filings tend to carry bad news (leading explanation, ~65/35 per Macro PM).
- **Signal:** pre-announced board-meeting date + predicted late-filer flag from the company's own past filing times (never the actual filing time, which isn't known in advance).
- **Scored as:** timing benefit versus executing the same planned trades without the rule, net of the return given up while out of the stock. Report how much of the move sits in the overnight gap nobody can trade.
- **Kill bar (CRO proposal, Shivam to confirm):** after-15:30 filers fail to trail matched non-announcers by ≥ 30 bp on the results day + next day (t < −2), on adjusted prices, over Oct–Nov 2026 and Jan–Feb 2027.
- **Time-sensitive:** must be frozen by git commit before mid-October, or a season of forward evidence is lost.

### Card B. Earnings-surprise conditioning (main study)
- **Idea:** the results reaction and any follow-on drift depend on how surprising the numbers were. Positive surprises in low-attention stocks may still drift up enough to trade long.
- **Who's on the other side:** investors slow to update on numbers in less-followed stocks.
- **Signal:** year-on-year growth in profit (or revenue) scaled by the company's own past variability, known at filing time. Not built from the price reaction.
- **First diagnostic:** does the late-filer gradient disappear once surprise is controlled for? If yes, "late = bad news" is confirmed and Card A's mechanism is understood.
- **Must state before running:** break-even ≈ 160 bp gross (2 × 80 bp costs); "conditioned drift ≤ 0 in 2025–26 ⇒ killed", with no regime excuse afterwards.
- **Also tests** Macro's D2 (drift follows small-cap vs large-cap momentum) and D3 (decay concentrated in high-attention stocks), both written down before testing.

### Card C. Promoter open-market buying
- **Idea:** promoters buying their own stock in the open market know the business best; they tend to buy before good news.
- **Who's on the other side:** sellers without inside knowledge of the business's near-term path.
- **Signal:** open-market purchases by promoter/promoter group from SEBI PIT disclosures, dated by disclosure time, excluding transfers, ESOPs, pledges and inter-se moves.
- **Blocked on:** insider history (0 rows today). Eligible for the sealed 2025-10 → 2026-09 holdout, since nobody has examined it yet.

### Card D. Guidance raises in concalls
- **Idea:** management raising guidance versus the previous call carries information the market absorbs slowly (the 100-hour study's question).
- **Signal:** explicit guidance raise versus the prior comparable call, dated by the transcript's first public release, extracted by the LLM with citations to the source text.
- **Condition:** tested only for what it adds **beyond** Card B's surprise signal, since concalls come days after results. Eligible for the sealed holdout.

### Card E. Forced flows
- **Idea:** index inclusions/exclusions and surveillance-list moves (ASM/GSM) force funds and traders to buy or sell regardless of value.
- **Who's on the other side:** index funds and leveraged traders who have no choice.
- **Blocked on:** index-change history and surveillance history (no data today). First in line for a new feed when the freeze lifts.

### Card F. Bulk/block deal accumulation *(new proposal, not voted on by the council)*
- **Idea:** large disclosed purchases by known institutions in less-followed stocks precede further buying.
- **Signal:** net bulk/block buying by marquee institutions (the table already has an `is_marquee_institution` flag), dated by deal date.
- **Blocked on:** history (one day of data today). Needs a council look before it joins the backlog.
- **Extra check: Chaikin Money Flow (CMF), daily.** Tests whether accumulation shows up in ordinary trading as well as in disclosed deals.
  - **What standard CMF measures:** each day, where the close sits inside the day's high–low range (near the high = +1, near the low = −1), multiplied by **total traded volume**, summed over 20 days and divided by 20-day volume. It reads buying vs selling pressure from price position. It does **not** use delivery volume.
  - **Delivery-weighted variant (Shivam's idea):** the same calculation with **delivery volume** in place of total volume, so intraday churn is excluded and only shares actually taken into demat count. Test both versions side by side.
  - **Questions:** does high or rising CMF (either version) precede excess returns on its own? Does it strengthen a bulk/block buying signal when both agree?
  - **Data:** no fetch needed for NSE main-board stocks. Daily OHLC, total volume and NSE deliverable volume are already in the DB, so this sub-check can run before bulk/block history exists. The delivery-weighted version is **not** valid on BSE-only, SME or BE-series rows until delivery data is fixed (see §1a).
  - **Caveat:** on split/bonus days share counts jump, which distorts the 20-day volume weights. Run it only on adjusted prices and volumes (after step 0).

### Card G. Avoid list (never traded)
- **Idea:** stocks failing solvency or forensic checks (pledge > 15%, interest cover < 2.5×, D/E > 1.5×, accrual red flags) underperform.
- **Scored as:** its own cohort, so the long-only book gets credit only if "not owning" these names would have helped.
- **Blocked on:** dated fundamentals (same fix as Card B).

---

## 4. Research only (not strategies)
- **Post-results drift as a standalone trade:** 55–75 bp gross per side against ~80 bp costs, half of it on the short side. Kept only as a question inside Card B.
- **Macro decay explanations D1–D3:** tested inside steps 0 and B, as written down before testing.

## 5. Buried — not re-tested without new evidence
From `tasks/strategy_tracker.md`: T1 (unexplained-weakness BUY, 1 win in 44), T4/T5 (SELL "46/46 wins" — framing bug, revoked), T10 (next-day confirmation, hit-rate 0.03), T11 (trend-continuation entry), and the F1/F2 kills from the 2026-09-25 desk meeting.

## 6. Shivam decides
1. Freeze Card A this week (and its kill bar)?
2. Approve fetching 2021-10 → 2022-12 corporate actions and building the ISIN-history map (truth repair, freeze-exempt)?
3. Insider and bulk/block history: wait until after Card B (verdict default), or fetch now as an exception?
4. Add Card F to the backlog for council review?
5. Backfill BSE-only/SME prices (Oct 2021 – Mar 2023, and try May 2024 – May 2026) and fetch BSE delivery + NSE SME files as truth repairs? Fix the BE-series delivery zeros?
