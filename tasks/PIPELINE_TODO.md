# Pipeline to-do (phase-wise) — set by Shivam 2026-10-19

Authority stays `tasks/FRAMEWORK.md`; live status in `tasks/STATE.md`. Each item lists what to build, where it lands,
and the check that says it is done. Tick an item only when its check passes. Point-in-time rule for every item:
store the time the information became public (exchange / publication / posting time), never a crawl date.

## Phase A — policy pillar (core; do first)

### A1. Tax-rule table for the backtest harness
- Build `tax_rules` (equity_intelligence.db): `rule` (stcg_rate, ltcg_rate, ltcg_exemption_inr, ltcg_holding_months,
  stt_delivery_rate, ...), `value`, `effective_from`, `effective_to`, `announced_at`, `source` (Finance Act / CBDT
  notification + policy_events row id), `quote`.
- Values from the Budget speeches already in policy_events (e.g. 23 Jul 2024: STCG 15→20%, LTCG 10→12.5%, exemption
  ₹1→1.25 lakh); effective dates from the Finance (No. 2) Act 2024 / CBDT notifications (fetch the notification,
  do not assume the speech date). Cover 2019→now (evidence window 2021-25 + live 2026), plus STT changes.
- Harness reads `tax_rule(rule, trade_date)`; a trade's tax uses the rule in force on its sell date.
- Check: STCG for a sale on 22 Jul 2024 = 15%, on 24 Jul 2024 = 20%; every row has a source document and quote.

### A2. PIB phase 2 — Hindi / Urdu and regional PIB offices
- Extend `pib_feed.py`: languages 2 (Hindi), 3 (Urdu) for PIB Delhi, and every regional office (reg ids in the
  listing's region select: Mumbai 1, Hyderabad 5, Chennai 6, Chandigarh 17, Kolkata 19, ... ) in all languages.
- Drop translations: embed title + first 1,000 chars with EmbeddingGemma (multilingual); a release whose best match
  among English releases of the same / previous day is above a tuned cosine threshold is marked `translation_of`.
- Unique non-English releases: keep the original text; the policy-register reader answers in English and quotes in
  the original language (prompt already allows it).
- Check: on a 20-day sample, hand-verify 30 matched pairs (translations) and 30 unique ones; < 5% wrong either way.

### A3. Policy register at scale
- Run `policy_register.py` over all PIB releases as the backfill fills (`--source pib`), daily for new ones
  (add a step to run_eod_market after the PIB step), and over macro documents (running 2026-10-19: 1,660 sections).
- Add stage tracking: link events about the same policy across documents (signal → consultation → draft →
  announced → notified → effective) into `policy_threads` with first-signal time; this is the "in the pipeline before
  the draft" signal.
- Map events to companies: sectors → industry codes → ISINs (security_master + industry map); named companies → ISIN.
- Check: blind judge (Opus) on 30 documents: precision of events, quote_ok ≥ 98%, stage and effective date correct.

## Phase B — instruments and benchmarks

### B1. ETF NAV and premium
- Security master: add INF ETF ISINs as `instrument_type='ETF'` (symbol_isin_history already sees them in UDiFF).
- AMFI NAV history 2019→ (portal.amfiindia.com NAV history download, by scheme and date range; has ISIN) →
  `fund_nav (isin, date, nav)`; daily via run_eod_market.
- `etf_premium (isin, date, close, nav, premium_pct, inav_est, premium_vs_inav_pct)`: for international ETFs an
  indicative NAV = underlying index (Nasdaq-100, Nasdaq Q50, Hang Seng, S&P 500 …; fetch daily closes) × USDINR,
  because the official NAV is a day stale. Also record the ETF's lower/upper circuit days.
- Policy link: RBI / SEBI overseas-investment limits into policy_events (supply caps drive premiums).
- Check: MONQ50 shows ~+235% premium on 21 Sep 2026 and the unwind after; MON100 premium series sane.

### B2. Total-return indices (benchmark rule)
- Fetch TRI history for Nifty Smallcap 250, Nifty Midcap 150 (niftyindices.com historical TRI) and BSE 250
  SmallCap, Sensex, BSE IPO (BSE TR / total-return series) → `index_tri (index_name, date, tri)`; daily via EOD job.
- Benchmark selector uses trailing-12-month TRI return, chosen before each month.
- Check: TRI − price-index return over a year ≈ the index dividend yield (1–1.5%).

### B3. Shareholding pattern and promoter pledge
- Quarterly shareholding XBRL (NSE / BSE shareholding-pattern filings, same style as results XBRL) →
  `shareholding (isin, quarter_end, filed_at, promoter_pct, promoter_pledged_pct, fii_pct, dii_pct, mf_pct,
  retail_pct, ...)`; SAST / pledge-creation disclosures (Reg 31) for intra-quarter pledge changes.
- Feeds: solvency gate (pledge > 15%), investor-majority rankings (AGENTS rule 6), ownership-change signals.
- Check: 10 companies hand-checked against the exchange website for two quarters.

## Phase C — carried from the order of work (STATE.md)
- Index membership history (inclusion / exclusion events), price bands / circuit hits, ASM/GSM history.
- Forward board-meeting calendar (results dates ahead).
- Exchange order wins: parse value / customer / execution period from the 'Award of Order / Receipt of Order' filings
  in the BSE announcement feed (complete source; Telegram only covers a subset).
- Re-embed search layer with EmbeddingGemma (transcripts + macro + decks first, then ARs).
- Metric ontology + canonical fact ledger; cross-source reconciliation; events table + state(isin, t).
