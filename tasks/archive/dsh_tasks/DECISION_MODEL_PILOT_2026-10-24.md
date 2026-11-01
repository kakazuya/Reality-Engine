# Pilot: DeepInfra decision models on our data (budget hard cap $0.45; Shivam approved ≤ $0.50)

Design: Claude. Execution (data prep, calls, scoring): DeepSeek worker. Claude reviews against the markers below.

## Question

Can the "decision" models (Cloudflare **clef-flash** 9B, $0.038/M; nace-ai **drex-v2.0** 35B-MoE/3B-active, $0.06/M;
**drex-max** 27B, $0.12/M only as a small reference arm) give us (A) accurate, cheap typed extraction and
(B) calibrated probabilities, on OUR documents? Each model takes a state (text/JSON) + typed questions (yes/no,
multiple choice, ordinal) and returns calibrated probabilities. Read each model's DeepInfra API page first for the
exact request/response schema; probe each with one tiny call before any batch.

## Arms (objective labels only — no LLM-made labels as ground truth)

**A1 — Announcement classification (multiple choice).** 200 BSE announcements from `bse_announcements.db`
(2026-09..10, stratified across the 8–10 most common exchange categories, ≤ 30 per category), state = headline +
first ~1,500 chars of the attachment text if we have it, else headline + subject. Question: which category
(choices = those categories + "other"). Label = the exchange's own category. Before scoring, sample 30 and check the
label is actually right (exchange categories are sometimes wrong); report the label-noise rate and score on both all
items and the audited-clean subset.

**A2 — Passage relevance (yes/no) on the AR pilot set.** The 48 questions in `reality_engine/data/embed_test_ar/`
(corpus.json, questions.json, gold_chunks.json; gold + near-duplicate rule as in `embed_ar_test.py`). For each
question take NVFP4's top 6 candidates (cached `emb_nemotron3-1b-fp4-di.npy`, re-embed the 48 questions, ~$0.00003).
Question per (q, passage): "Does this passage answer the question?" yes/no. Metrics: AUC over all pairs; used as a
reranker of the top 6: hit@1 and hit@3 — compare with today's results (NVFP4 alone 56.3/79.2, + Nemotron-3.5-Rerank-8B
81.2/95.8, 8B embedding 62.5/91.7; note the 2 answers ranked 30 and 69 are outside top 6 for all arms).

**B — Calibrated event outcome (probability).** 100 events, strictly point-in-time: insider BUY trades
(`insider_trades_v2`, market purchases, value ≥ ₹50 lakh, `known_at` in 2026-08-01..2026-09-10) and NSE bulk-deal
buys of the same window. State = only fields known at `known_at` (company, sector, trade size vs market cap, person
category, 20-day prior return, delivery %), no future prices, no company name of the counterparty beyond the filing.
Question: "Will the stock beat the Nifty 50 TRI over the next 20 trading days?" Label from `daily_price_delivery` /
index TRI. Metrics: Brier vs base-rate Brier, log-loss, ECE (10 bins), reliability slope, AUC.

## Success markers (decide before seeing results)

| Arm | Pass | Strong |
|---|---|---|
| A1 | accuracy ≥ 90% on clean subset, macro-F1 ≥ 0.85, ECE ≤ 0.05, format errors ≤ 1% | ≥ 95% |
| A2 | AUC ≥ 0.90 and reranked hit@3 ≥ 91.7% (beats the 8B embedding alone) | hit@1 ≥ 81% (matches Nemotron rerank) at lower cost per query |
| B  | Brier at least 0.01 below base-rate Brier AND reliability slope 0.7–1.3 | AUC ≥ 0.60 |

A model "fails" an arm if it misses Pass. Expectation stated up front: B will most likely fail (n=100, short
horizon, noisy target) — a fail there means "not a forecaster yet", not "useless".

## Failure points to watch and report

1. Schema/format: refusals, missing probabilities, probabilities not summing to 1 → count them; > 2% = fail.
2. Degenerate calibration: everything ~0.5 or everything 0/1 (report the probability histogram).
3. Context limits: clef-flash 24k — truncate states to fit and report truncation counts.
4. Label noise (A1) and near-duplicate golds (A2) — handled as above.
5. Look-ahead (B): verify every state field's timestamp ≤ known_at; models' training cutoff may include 2026 news —
   note the risk; prefer events after the model's release date if any qualify.
6. Rate limits / latency: record p50/p95 latency and 429s.
7. Cost: use the API's reported cost/usage per call; ledger in `tasks/research/decision_pilot/spend.json`; stop all
   calls when cumulative spend reaches $0.45.

## Budget estimate

A1 200 × ~600 tok × 2 models ≈ 0.24M tok ≈ $0.012 · A2 288 pairs × ~900 tok × 2 ≈ 0.52M ≈ $0.026, + drex-max on A2
≈ $0.031 · B 100 × ~800 tok × 2 ≈ 0.16M ≈ $0.008 · probes/retries ≈ $0.01. Total ≈ $0.09; cap $0.45.

## Output

`tasks/research/decision_pilot/` — `run_pilot.py` (resumable, caches responses), `results.json`, and
`REPORT.md`: one table per arm (model × metrics vs markers, pass/fail), probability histograms/reliability tables,
cost per 1,000 items per model, the failure-point log, and a one-paragraph recommendation. Final answer = the tables,
spend, and the recommendation.
