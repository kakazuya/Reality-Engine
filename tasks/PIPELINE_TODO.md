# Pipeline to-do (phase-wise) — set by Shivam 2026-10-19

Authority stays `tasks/FRAMEWORK.md`; live status in `tasks/STATE.md`. Each item lists what to build, where it lands,
and the check that says it is done. Tick an item only when its check passes. Point-in-time rule for every item:
store the time the information became public (exchange / publication / posting time), never a crawl date.

**Shivam's order (2026-10-19 03:20): fix DATA gaps, QUERY gaps and LATENCY first. No backtests until Shivam says so
(his first one is extensive).** Every change must be implemented carefully without breaking running jobs or existing
tables: work on new tables / new files, verify with a check on real rows (dates vs source, counts, sample by hand), only
then switch readers over. Never assume; measure.

## Phase Q — query layer and latency (do first, alongside Phase A)

### Q1. Query speed checks (small; do first) - BUILT 2026-10-19, all 15 under limit warm + first run; cold-after-reboot pending
- `reality_engine/scripts/query_speed_check.py`: a fixed list of the queries backtests and analysis run, each with a
  time limit; results appended to `data/logs/query_speed.jsonl` and any over-limit query reported in the watchdog
  report. Run nightly (add a step to run_eod_market) and after every index/schema change.
- Queries + limits: one stock's full price history NSE and BSE (< 0.1 s); whole market one day (< 0.5 s); 20-day
  traded value all stocks (< 2 s); one company all quarterly results (< 0.1 s); whole market one quarter (< 2 s);
  one company AR category (< 0.5 s); market-wide AR item search via ar_facts_fts (< 1 s); one company deck KPIs
  (< 0.5 s); market-wide deck metric search (< 1 s, needs Q3); FTS keyword over chunks (< 0.5 s); vector search
  top-20 (< 1 s); concall facts one company (< 0.1 s); state(isin, t) (< 1 s, after Q4).
- Already fixed 2026-10-19 (keep in the check list): results one company 32 s -> 0.018 s (index facts(file, concept,
  context) + ANALYZE in results_xbrl.db); NSE one stock -> 0.013 s (idx_mkt_nse_full_symbol); AR item search 49 s ->
  0.39 s (FTS5 ar_facts_fts, external content on ar_facts; rebuild/insert-sync it when ar_facts gets new rows).
- Check: all queries under limit on a cold start (first run after reboot) and warm.

### Q2. Nightly DuckDB analysis snapshot (the backtest data layer) - DONE 2026-10-19 (counts match, scans < 1 s)
- SQLite stays the write store; backtests and heavy analysis read a columnar DuckDB snapshot rebuilt nightly
  (extend `build_truth_snapshot.py`, which already makes `data/snapshots/truth_<date>.duckdb` with adjusted and
  total-return prices). Add: security_master + symbol_isin_history, results XBRL (filings + key facts pivoted),
  ar_facts, deck facts (+ deck_sources known_at), concall facts + cc_item_checks, tg_orders/schedule, exchange
  announcements (events), insider/SAST/deals, FII/DII, policy_events, pib_releases (metadata), corporate actions.
- Every table carries its point-in-time column (known_at / filed_at / dissem / posted_at) in UTC-normalised form plus
  the original local string (fixes the IST-vs-UTC mixing risk).
- Keep the last 7 snapshots; backtests record the snapshot date they used (framework: research runs on dated snapshots).
- Check: market-wide scans over ar_facts (32M) and deck facts (13.6M) < 1 s; row counts equal the SQLite sources.

### Q3. Missing indexes / text indexes - DONE 2026-10-19 (`build_query_indexes.py`; Q1 queries all under limit)
- deck_figures: FTS5 on facts(metric) (1.48M distinct strings) and index on deck_sources(isin, known_at).
- concall_facts: FTS5 over cc_items(metric, statement, quote).
- policy_events: indexes on published_at, instrument, stage; FTS over policy_name + quote.
- Check: each listed query in Q1 under limit.

### Q4. One query entry point - v1 2026-10-19: state() leak 0 / 300, p95 0.16 s; 20 hand checks + search() pending
- `reality_engine/query/state.py`: `state(isin, t)` = everything known about a company at time t across all stores
  (latest results, guidance + computed direction, orders schedule, deck KPIs, AR facts, policy events touching its
  sectors, ownership, prices up to t) - reading only rows public before t. `search(text, isin=None, t=None)` =
  hybrid FTS + EmbeddingGemma vectors over all text with the same point-in-time filter.
- Needs the metric ontology (Phase C) for clean cross-source metrics; ship a first version on raw metrics.
- Check: leak test (nothing filed after t returned), latency under limit, 20 hand-checked company snapshots.

## Phase A — policy pillar (core; do first)

### A1. Tax-rule table for the backtest harness - DONE 2026-10-19 (check passes; holding-period pre-2026 source pending)
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

### B1. ETF NAV and premium - DONE 2026-10-19 (MONQ50 check passes; circuit days + overseas-limit policy rows pending)
- Security master: add INF ETF ISINs as `instrument_type='ETF'` (symbol_isin_history already sees them in UDiFF).
- AMFI NAV history 2019→ (portal.amfiindia.com NAV history download, by scheme and date range; has ISIN) →
  `fund_nav (isin, date, nav)`; daily via run_eod_market.
- `etf_premium (isin, date, close, nav, premium_pct, inav_est, premium_vs_inav_pct)`: for international ETFs an
  indicative NAV = underlying index (Nasdaq-100, Nasdaq Q50, Hang Seng, S&P 500 …; fetch daily closes) × USDINR,
  because the official NAV is a day stale. Also record the ETF's lower/upper circuit days.
- Policy link: RBI / SEBI overseas-investment limits into policy_events (supply caps drive premiums).
- Check: MONQ50 shows ~+235% premium on 21 Sep 2026 and the unwind after; MON100 premium series sane.

### B2. Total-return indices (benchmark rule) - DONE 2026-10-19 (NSE official; BSE derived, error measured)
- Fetch TRI history for Nifty Smallcap 250, Nifty Midcap 150 (niftyindices.com historical TRI) and BSE 250
  SmallCap, Sensex, BSE IPO (BSE TR / total-return series) → `index_tri (index_name, date, tri)`; daily via EOD job.
- Benchmark selector uses trailing-12-month TRI return, chosen before each month.
- Check: TRI − price-index return over a year ≈ the index dividend yield (1–1.5%).

### B3. Shareholding pattern and promoter pledge - backfill RUNNING 2026-10-19
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
