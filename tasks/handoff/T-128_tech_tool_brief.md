Goal: Add one read-only tool, pilot3_tech, that computes price reactions and technicals in code, so a model never hand-computes them. In the 8 Nov re-ask, models got these wrong in 9 of 136 answers (day 0 after a late filing, gap held vs previous close, RSI method, last moving-average cross, volume spikes).

Files (only these): new `plugins/reality-data/server/lookups_tech.py`; `plugins/reality-data/server/server.py` (register `pilot3_tech`, one routing line in the PILOT3 instructions text: "price reaction to a filing, gaps, RSI, moving averages, volume spikes, range position -> pilot3_tech"); `reality_engine/scripts/p3ask.py` (add `tech` to TOOLS and dispatch); new `reality_engine/tests/test_pilot3_tech.py`; `docs/PILOT3_BLUEPRINT.md` (new short section 9i: what the tool computes and the rules below).

Data (read-only, sqlite, same connection helper as lookups_pilot3 `connect()` / `_q`, honour `REALITY_PILOT3_DB`):
- `price_delivery(symbol, exchange, date, open, high, low, close, prev_close, volume, delivery_pct, adj_factor, adj_close, known_at)`; use exchange='NSE'. Daily rows from 2025-10-01 in pilot10.
- `index_price(symbol, index_name, date, index_close, ...)` for the index move on the same day.
- `doc(symbol, doc_type, title, known_at)`: filings; results are doc_type='results'. known_at is IST local time 'YYYY-MM-DDTHH:MM:SS'.

Signature: `tech(symbol, kind, as_of=None, start=None, end=None, sessions=5, threshold=None, window=None, doc_type='results', limit=10)`; kinds:
1. `reaction`: for the last `limit` filings of doc_type before as_of (or explicit `start`/`end` range): day 0 = the filing date if known_at time <= 15:30:00 and that date is a trading session, else the NEXT trading session (the market closes 15:30 IST). Return per filing: known_at, day0, rows for day 0..`sessions` with close-to-close % vs prev session close, cumulative %, volume, volume multiple vs the mean of the 20 sessions BEFORE day 0, delivery_pct, index same-day %, and the 5-session cumulative.
2. `gaps`: sessions in [start,end] (default last 365 days to as_of) with |open/prev_close-1| >= threshold (default 0.03): gap %, close vs previous close %, share of the gap held at the close = (close-prev_close)/(open-prev_close) (can be negative), delivery_pct vs its trailing 250-session mean, and fill date = first later session whose low <= prev_close (gap up) or high >= prev_close (gap down), or null.
3. `rsi`: Wilder 14 (first average = simple mean of first 14 changes, then avg=(prev*13+x)/14) on adj_close; return today's RSI, the series for the last `window` (default 30) sessions, and a divergence block: the two lowest closes and two highest closes in the window with the RSI at each, plus `bullish_divergence` (lower price low with higher RSI low) and `bearish_divergence` (higher price high with lower RSI high). State `method: "Wilder 14 on adjusted close"`.
4. `ma`: SMA 50 and 200 on adj_close at as_of: value, % above/below, and the last cross date and direction for each (close crossing its SMA), computed only where the SMA has full history; say `insufficient_history` when it does not.
5. `volume_spikes`: sessions where volume > threshold (default 3) x mean volume of the PRIOR 20 sessions (excluding the day), last 365 days: multiple, close-to-close %, delivery_pct.
6. `range`: 52-week high/low of close with dates, position = (close-low)/(high-low), % above low, % below high.
Every reply: `found`, `symbol`, `tool: "pilot3_tech"`, `method` text, rows carry `provenance` {table:'price_delivery', source:'NSE <date>', known_at}. as_of drops sessions after it. Unknown symbol -> same not-found shape as other pilot3 tools.

Accept (all must pass): `python -m pytest reality_engine/tests/test_pilot3_tech.py -q` and `python -m pytest plugins/reality-data/tests/test_lookups_pilot3.py -q`. The test file has (a) synthetic-fixture tests for every kind and the 15:30 rule, and (b) live checks on `D:/RealityEngine/pilot10/pilot10.db` (skip if absent), all as_of 2026-11-04:
- ETERNAL reaction: Q3FY26 results known_at 2026-01-21T16:02:01 -> day0 2026-01-22.
- ETERNAL gaps threshold 0.02: 2026-02-03 gap 7.83%, close +2.62% vs previous close.
- KEC gaps: the 2026-10-26 gap up (3.43%) has fill date 2026-10-30.
- BAJFINANCE ma: close 970.00, SMA50 999.4, SMA200 972.4 (1 dp); last SMA200 cross 2026-10-19 down; last SMA50 cross 2026-08-31 down.
- KEC volume_spikes threshold 3: 18 sessions from 2025-11-04, including 2025-11-11 at 13.01x and 2026-10-09 at 13.91x.
- HDFCBANK rsi on 2026-11-03: Wilder value printed and between 55 and 62 (the 5 Nov hand check gave 58.4; assert your exact value and explain any gap in the final answer).
Also `python -m reality_engine.scripts.p3ask --db D:/RealityEngine/pilot10/pilot10.db tech symbol=ETERNAL kind=reaction as_of=2026-11-04` prints JSON.

Evidence: hand checks on pilot10.db 8 Nov (Opus): ETERNAL 3 Feb gap 7.83% closed +2.62% (an answer said -4.83%, close vs open); KEC 26 Oct gap filled 30 Oct at low 327.30; BAJFINANCE 200-day crosses 2026-09-29 down, 10-13 up, 10-14 down, 10-16 up, 10-19 down; KEC spikes (prior-20 mean) 18 days. Results filed 16:02 on 21 Jan: market already closed.

Pitfalls: use adj_close for RSI/SMA (Bajaj Finance had a split in 2025) but close/prev_close for daily % and gaps; prior-20 means exclude the day; a session list comes from price_delivery dates, not the calendar; never read raw files or the network; keep functions pure and small; no edits to lookups_pilot3.py beyond importing helpers if needed (prefer duplicating the 3-line connect/_q use through `lookups_pilot3` import).

Stop if: the live checks disagree with the evidence above after two honest attempts (report the numbers you get), or a test outside the two files fails.

Budget: 90 tool calls, 2 hours. Run only the listed test files. Final answer starts with `Docs updated:` and lists each accept result.

Ticket: T-128
