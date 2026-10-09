# Reality Engine — Framework (authority file)

**Status:** the single authority for objectives, rules and order of work, set by Shivam on 2026-10-08. It overrides `AGENTS.md`, `FUNDAMENTAL_REALITY_ENGINE_OBJECTIVES.md`, the council verdicts and every older plan wherever they disagree. Only Shivam changes it.
**Sources:** Shivam's answers A1–A22 in `tasks/FRAMEWORK_OPEN_QUESTIONS.md` and the follow-up answers of 2026-10-08. Council working notes are in `tasks/council_2026-10-06/` (record only, not authority).
**Live state** (what is running, what is next) lives in `tasks/STATE.md`, which is overwritten, never appended to.

---

## 1. North star

**Keep winning and cut losses.** Like Medallion, the engine does not need to be right every time; it wins through position sizing, drawdown control and riding winners. Opportunities come in pockets and are competed away fast, so the engine must notice and act first. Everything else (*desh, kaal, sthiti*: place, time, situation) stays dynamic.

## 2. Trading rules

| Rule | Decision |
|---|---|
| Instruments | **Cash equities only, long only.** No F&O, no overnight shorts. |
| Hedging | Through sectors or stocks with strong negative correlation. Every such pair records why the correlation appeared, how long it lasted and why it broke. |
| Capital | ₹1 cr actual. ₹10 cr is a hypothetical used only for capacity curves. |
| Universe | All NSE and BSE stocks, SME included. Liquidity cap: **a position never exceeds 10% of the stock's average daily traded value.** |
| Penny stocks | Stocks under **₹10** (raw price on the signal date) are **excluded by default**. A penny stock is eligible only when there is a **structural shift in fundamentals** (e.g. a post-earnings-drift / earnings-surprise trigger) **and** its technicals confirm. Penny-stock trades are also flagged in the truth report's data-quality checks (tick-size noise, unexplained jumps) before entry. (Shivam, 2026-10-08) |
| Trade thesis | A trade is triggered by **either** a fundamental or a technical reason; the other must **confirm or veto** it. Fundamental and technical signals keep separate scoreboards inside one book. |
| Costs | Fixed **0.30% per round trip** (STT, brokerage, stamp duty, exchange charges, small slippage allowance). No measured-slippage model at this scale. |
| Tax | **Results are scored after tax** (short-term vs long-term capital-gains rates; rates to be verified against the current Finance Act before use). |
| Execution | The engine produces the order list (stock, size, entry, stop). Shivam places the trades. |

## 3. Benchmark

Each period the strategy is compared with **one index chosen in advance**: the best performer over the trailing window among Nifty Smallcap 250, BSE 250 SmallCap, Nifty Midcap 150, BSE Sensex and BSE IPO. The choice is made before the period starts (no hindsight). Default: trailing 12-month total return, re-chosen monthly; the harness may test other windows but must log which one it used.

## 4. Risk and money management

| Limit | Value |
|---|---|
| New strategy allocation | **10% of capital** |
| Strategy kill | Drawdown **> 8%** on its allocation → killed |
| Portfolio drawdown limit | **5%**, widened to **8%** only when the whole market (the benchmark) is also falling |
| Position size | Sized by the engine within the 10%-of-daily-value cap |

## 5. How a strategy is proven

- **No holdout period, no forward paper trading.** A strategy is created, tested and confirmed on historical data, then deployed with real money under the risk limits in §4. Live results keep feeding back so the engine fine-tunes itself (self-recursive learning).
- **Fluke control is mandatory.** Many stocks and many periods give many independent tests. Every test ever run is logged in one ledger (passes and failures), and promotion must survive statistics that correct for the number of tests tried (false-discovery control, a deflated or reality-check test across variants, placebo / shuffled-date tests, stability across periods and market regimes).
- **Promotion bar:** set by the engine (risk-adjusted, after tax, against the §3 benchmark). The old "+500 bps" bar is reference only.
- **Evidence window (Shivam, 2026-10-08):** strategies are built and proven on **2021-01-01 → 2025-12-31**. **All of 2026 is treated as live**: strategies chosen with data up to 2025-12-31 are run through 2026 day by day as if trading for real (10% allocation, drawdown kills, self-correction), and that run is their live record. 2019–2020 data is used only as warm-up for lookbacks and features.

## 6. Layers and who owns what

| Layer | Rule |
|---|---|
| 1. Truth (data) | Research runs on **dated snapshots**; ingestion keeps running and keeps improving (test coverage, label quality, knowledge retention, retrieval speed). The engine decides and maintains the data-truth checks: point-in-time dates, split/bonus/dividend adjustment, ISIN history, survivorship (delisted names kept), quarantine, exchange quirks (e.g. holiday copies of the previous day's file). |
| 2. Signals | Every feature must be readable "as of date t". The engine owns which features get versioned first. **Moat, ENI, ripple and business-profile seeds are set aside**; new strategies should beat them after continuous refinement. |
| 3. Hypotheses | One registry. Each card is clear and concise, and **no two cards test the same thing reframed**. The engine ranks, promotes and demotes. |
| 4. Evaluation | **One shared test harness** for every idea: same data loading, costs, tax, benchmark and statistics. Built starting from the diffusion-study code. |
| 5. Decisions | Ensemble explaining power is stored per layer: stock, industry, the indices a stock belongs to, and the whole free-float market. A combined model replaces the incumbent only after beating the best single strategy in **four separate test periods**. The incumbent stays until a challenger beats it (keep the local maximum until a higher one appears). |
| 6. Learning | Hypotheses are generated, tested, killed or promoted continuously (24×7). Live outcomes feed back into the rankings. |

## 7. Role of the LLM (Claude)

Claude is the backbone at every stage: it turns raw data into engines that run consistently and produce decisions independently, building algorithms that take over the day-to-day work from the bottom up. Over time Claude acts as CEO and brings only big decisions to Shivam.

## 8. Operating model

- **Automation:** scheduled jobs on this PC (end-of-day data update, correction run, overnight research run) are set up alongside the existing jobs; the existing annual-report drain and CapacityLoop keep running.
- **Tools:** no new tools unless Claude recommends them (plugins and skills are welcome where useful).
- **Files:** this file is the authority. `tasks/STATE.md` is the one live hand-off file. Old plans, closeouts and desk files that do not match this framework are to be deleted (Shivam approved 2026-10-08; the command is in `tasks/STATE.md`). Until then they are historical record only.
- **DII data:** DII daily cash history may come from a third-party archive.

## 9. Decisions that overrode the council (2026-10-06)

| Topic | Council | Shivam |
|---|---|---|
| Confirmation | Forward-only, paper first | History only, then live with risk limits |
| Books | Event book only | One book, technical + fundamental scoreboards |
| Benchmark | Matched peers / factor model | Best of 5 indices, chosen in advance |
| Capital | ₹10 cr assumption, ₹2–5 cr/day floors | ₹1 cr, position ≤ 10% of daily traded value |
| Kill switch | 2026-12-31 review | Strategy and portfolio drawdown limits (§4) |
| Freeze | Freeze new feeds until first promotion | Fetch all data first; continuous research |
