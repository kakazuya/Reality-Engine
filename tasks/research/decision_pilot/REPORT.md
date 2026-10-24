# Decision-model pilot — DeepInfra clef-flash / drex-v2.0 / drex-max

**Date:** 2026-10-24 · **Data:** our BSE announcements, annual-report chunks, insider/bulk-deal events
**Endpoint:** `POST https://api.deepinfra.com/v1/decisions` (typed `noul` / `choice` questions, probabilities not prose)
**Prices used:** clef-flash $0.038/M input, drex-v2.0 $0.06/M, drex-max $0.12/M; output free.

## Verdict at a glance

| Arm | Model | Pass | Strong | Headline |
|---|---|---|---|---|
| A1 | Cloudflare/clef-flash | **FAIL** | no | clean acc 85.2%, macro-F1 0.772, ECE 0.101 |
| A1 | nace-ai/drex-v2.0 | **FAIL** | no | clean acc 88.9%, macro-F1 0.836, ECE 0.057 |
| A2 | Cloudflare/clef-flash | **FAIL** | no | AUC 0.868, hit@3 89.6% |
| A2 | nace-ai/drex-v2.0 | **PASS** | no | AUC 0.922, hit@3 93.8% (45/48 = ceiling); hit@1 72.9% |
| A2 | nace-ai/drex-max | **FAIL** | hit@1 clause only | AUC 0.934, hit@1 81.3%, hit@3 89.6% |
| B | Cloudflare/clef-flash | **FAIL** | no | Brier 0.269 vs base 0.250; slope 0.10 |
| B | nace-ai/drex-v2.0 | **FAIL** | no | Brier 0.253 vs base 0.250; slope 0.62 |

Only **drex-v2.0 on A2** clears its Pass marker. The A2 ranking result is real; its probabilities are
badly overconfident (ECE 0.38), so it is a reranker, not a calibrated probability source. A1 is close
for drex-v2.0 but misses all three accuracy/calibration thresholds; B has no measurable skill for
either model.

## Setup and spend

| Item | Value |
|---|---|
| Models probed | clef-flash (OK, 1.9 s), drex-v2.0 (first probe 429, retry OK, 1.4 s), drex-max (OK, 1.0 s) |
| Scored calls | 1,464 (A1 400, A2 864, B 200); 0 API/format failures |
| Max observed input | 1,609 tokens (clef, A2); clef context is 24,576 → 0 truncations |
| Ledger | `spend.json`; **$0.061313** of the **$0.45** cap (13.6%) |
| DeepInfra billing endpoint | 6 cents for the three decision models this month (whole-cent rounding; ledger is the conservative list-price figure) |
| Budget estimate | $0.09; actual came in at 68% of estimate |

Cost per arm/model is in the cost table below. Responses are cached per item under
`cache/responses/<model>/<arm>/`; `run_pilot.py` is resumable and checks the ledger before every call.

### Data

| Arm | Construction | Size |
|---|---|---|
| A1 | BSE announcements 2026-09-01..10-19, normalized categories, 25 per category, attachment PDF text downloaded where available | 200 items, 114 with attachment text (57%), 8 labels + `Other / not listed` |
| A2 | 48 AR questions; cached NVFP4 corpus vectors; re-embed questions with `nvidia/Nemotron-3-Embed-1B-NVFP4` ($0.000011); top 6 candidates per question | 288 (question, passage) pairs, 50 positive pairs (gold + 5-word-shingle Jaccard ≥ 0.5) |
| B | 46 largest insider BUY/MARKET_PURCHASE ≥ ₹50 lakh per company, 54 NSE bulk-deal BUYs per company; 100 unique symbols; state uses data strictly before `known_at` | 100 events, base rate 52%, 2026-08-03..09-10 |

## A1 — BSE announcement classification (multiple choice)

**Pass:** accuracy ≥ 90% (clean), macro-F1 ≥ 0.85 (clean), ECE ≤ 0.05 (clean), format errors ≤ 1%.
**Strong:** clean accuracy ≥ 95%.

| Model | Acc all (n=200) | Acc clean (n=27) | Macro-F1 all | Macro-F1 clean | ECE all | ECE clean | Format err | Pass | Strong |
|---|---|---|---|---|---|---|---|---|---|
| clef-flash | 80.5% | 85.2% | 0.757 | 0.772 | 0.0985 | 0.1007 | 0/200 | **FAIL** | no |
| drex-v2.0 | 77.0% | 88.9% | 0.754 | 0.836 | 0.0955 | 0.0574 | 0/200 | **FAIL** | no |

Neither model reaches 90% / 0.85 / 0.05 on the audited-clean subset. drex-v2.0 is close on
accuracy and macro-F1 and misses ECE by 0.007; with only 27 clean items the confidence interval is
wide (23/27 or 24/27; Wilson 95% roughly 67–96%), so this is a "near miss", not a demonstrated pass.

### Label audit (30 items, before scoring)

| Category | Audited | Wrong | Noise |
|---|---|---|---|
| Company Update | 4 | 1 | 25% |
| AGM/EGM | 4 | 0 | 0% |
| Insider Trading / SAST | 4 | 0 | 0% |
| Others | 4 | 2 | **50%** |
| Board Meeting | 4 | 0 | 0% |
| Corp. Action | 4 | 0 | 0% |
| Mutual Fund | 3 | 0 | 0% |
| Result | 3 | 0 | 0% |
| **Total** | **30** | **3** | **10%** |

Wrong labels: one PIT Reg 7(2) disclosure filed as *Company Update* (should be *Insider Trading /
SAST*) and two board-meeting outcomes filed as *Others*. The *Others* bucket is the main noise
source: both models never predict it, and clef maps 15/25 *Others* items to *AGM/EGM* plus 6/25 to
*Board Meeting*; drex-v2.0 maps 5/25 to *AGM/EGM*, 6/25 to *Board Meeting* and 13/25 to
*Other / not listed*. Many of those look like board outcomes or annual reports that the exchange
dumped into *Others*. A1 accuracy against exchange labels is therefore a **lower bound**; a full
audit of *Others* is needed before judging the last few points.

**Taxonomy sensitivity.** Because the choice set contains both the exchange category *Others* and
the escape hatch *Other / not listed*, drex-v2.0 used the escape hatch 20 times (13 true *Others*,
5 *Company Update*, 2 *Corp. Action*). Merging the two choices raises drex-v2.0's clean accuracy to
96.3% and macro-F1 to 0.961 (strong accuracy), but full-set accuracy only to 83.5% because 7
non-*Others* items get absorbed; clean ECE rises to 0.124. clef is unchanged (it never picks the
escape hatch). The primary table keeps the pre-declared, strict choices. Under either scoring,
**A1 Pass fails on calibration**; under strict scoring it also fails accuracy and macro-F1.

### Probability histogram (top-label confidence) and reliability

| Bin | 0.0–0.3 | 0.3–0.4 | 0.4–0.5 | 0.5–0.6 | 0.6–0.7 | 0.7–0.8 | 0.8–0.9 | 0.9–1.0 |
|---|---|---|---|---|---|---|---|---|
| clef n | 0 | 4 | 8 | 8 | 9 | 11 | 11 | 149 |
| drex n | 0 | 3 | 12 | 14 | 16 | 14 | 12 | 129 |

| Bin | clef n | clef mean p | clef obs | drex n | drex mean p | drex obs |
|---|---|---|---|---|---|---|
| 0.3–0.4 | 4 | 0.363 | 0.250 | 3 | 0.389 | 0.000 |
| 0.4–0.5 | 8 | 0.443 | 0.000 | 12 | 0.462 | 0.417 |
| 0.5–0.6 | 8 | 0.535 | 0.500 | 14 | 0.554 | 0.429 |
| 0.6–0.7 | 9 | 0.652 | 0.556 | 16 | 0.657 | 0.438 |
| 0.7–0.8 | 11 | 0.753 | 0.909 | 14 | 0.749 | 0.714 |
| 0.8–0.9 | 11 | 0.860 | 0.909 | 12 | 0.858 | 0.917 |
| 0.9–1.0 | 149 | 0.962 | 0.879 | 129 | 0.976 | 0.892 |

Both models put most mass at 0.9–1.0 and are right ~88–89% of the time there: the distributions are
sharp but not calibrated. The low-confidence bins are small and noisy.

### Latency, rate limits, cost

| Model | p50 | p95 | 429s | Retries | Cost / 200 | Cost / 1,000 |
|---|---|---|---|---|---|---|
| clef-flash | 1,027 ms | 1,933 ms | 0 | 0 | $0.00510 | $0.026 |
| drex-v2.0 | 1,128 ms | 1,720 ms | 11 | 11 | $0.00582 | $0.029 |

## A2 — AR passage relevance / reranking (yes/no)

**Pass:** AUC ≥ 0.90 and reranked hit@3 ≥ 91.7%. **Strong:** hit@1 ≥ 81% at lower cost per query
than Nemotron-3.5-Rerank-8B (its measured cost was $0.0345 for 48 queries = $0.00072/query).

| Ranker | AUC | hit@1 | hit@3 | ECE | $/query | Pass | Strong |
|---|---|---|---|---|---|---|---|
| NVFP4 embedding alone (baseline) | 0.734 | 56.3% | 79.2% | — | ~$0 | — | — |
| Nemotron-3-Embed-8B (baseline) | — | 62.5% | 91.7% | — | — | — | — |
| Nemotron-3.5-Rerank-8B (baseline) | — | 81.2% | 95.8% | — | $0.00072 | — | — |
| clef-flash | 0.868 | 62.5% | 89.6% | 0.215 | $0.00019 | **FAIL** | no |
| **drex-v2.0** | **0.922** | 72.9% | **93.8%** | 0.383 | $0.00026 | **PASS** | no |
| drex-max | 0.934 | **81.3%** | 89.6% | 0.292 | $0.00057 | **FAIL** | hit@1 clause met, but Pass fails |

Three questions have no positive candidate in the NVFP4 top 6 (ranks 30, 10 and 69; the brief
said two, the data says three), so the maximum achievable hit@3 for the top-6 arms is
45/48 = 93.75%; all three models are scored against that ceiling. drex-v2.0 gets 45/48 — the
ceiling, i.e. every answerable question. drex-max gets 43/48 despite the best AUC and hit@1: it is
more top-heavy but drops two golds to rank 4–5. clef also gets 43/48. The baselines see more than
the top 6 (the reranker used top 20), so their 95.8% is not capped by the same ceiling. The
48-question cluster means the AUC interval is wider than a 288-pair bootstrap suggests
(drex-v2.0 95% CI [0.886, 0.952]); the point estimate passes, the lower bound does not.

**Calibration is the weak point.** All three are overconfident: 71–84 of 288 pairs land in
0.9–1.0 while only 49–58% of that bin is positive. drex-v2.0's ECE (0.383) is the worst of the
three even though its ranking is the best value. If these scores are used as probabilities, apply
isotonic/Platt calibration on a held-out set; if used as a ranker, the ordering is what matters.

### Probability histogram and reliability

| Bin | clef n | clef obs | drex-v2 n | drex-v2 obs | drex-max n | drex-max obs |
|---|---|---|---|---|---|---|
| 0.0–0.1 | 141 | 0.021 | 19 | 0.000 | 71 | 0.000 |
| 0.1–0.2 | 22 | 0.045 | 46 | 0.000 | 48 | 0.000 |
| 0.2–0.3 | 8 | 0.000 | 32 | 0.000 | 21 | 0.000 |
| 0.3–0.4 | 7 | 0.000 | 23 | 0.000 | 13 | 0.000 |
| 0.4–0.5 | 3 | 0.000 | 17 | 0.000 | 8 | 0.000 |
| 0.5–0.6 | 2 | 0.000 | 13 | 0.000 | 12 | 0.000 |
| 0.6–0.7 | 3 | 0.333 | 12 | 0.000 | 6 | 0.000 |
| 0.7–0.8 | 10 | 0.300 | 18 | 0.111 | 11 | 0.091 |
| 0.8–0.9 | 21 | 0.333 | 24 | 0.167 | 19 | 0.158 |
| 0.9–1.0 | 71 | 0.493 | 84 | 0.524 | 79 | 0.582 |

Mean p in the top bin: clef 0.941, drex-v2.0 0.942, drex-max 0.966. The models separate positives
somewhat at the top, but the probability scale is not usable as-is.

### Latency, rate limits, cost

| Model | p50 | p95 | 429s | Retries | Cost / 288 pairs | Cost / 1,000 pairs | Cost / 1,000 queries |
|---|---|---|---|---|---|---|---|
| clef-flash | 1,067 ms | 1,476 ms | 0 | 0 | $0.00922 | $0.032 | $0.192 |
| drex-v2.0 | 1,093 ms | 1,813 ms | 26 | 26 | $0.01233 | $0.043 | $0.257 |
| drex-max | 1,087 ms | 1,905 ms | 0 | 0 | $0.02718 | $0.094 | $0.566 |

## B — Calibrated event outcome (insider / bulk-deal buys)

**Pass:** Brier at least 0.01 below base-rate Brier **and** reliability slope 0.7–1.3.
**Strong:** AUC ≥ 0.60.

Target: beat Nifty 50 TRI over the next 20 trading days. Base rate 52%; base Brier 0.2496.
134 insider rows / 48 companies cleared the ₹50 lakh threshold; we kept the largest trade per
company and 46 had full price/filing coverage, with 54 bulk-deal buys filling the rest — 100 unique
symbols. 99/100 PIT checks are fully clean (one bulk event has no delivery %; the state carries
`null`), max state 286 chars. Labels use the snapshot's total-return closes (`px_nse_adj.tr_close`)
and the official `index_tri` Nifty 50 TRI.

| Model | Brier | Base Brier | Δ Brier | Log-loss | ECE | Slope | AUC | Mean p | Pass | Strong |
|---|---|---|---|---|---|---|---|---|---|---|
| clef-flash | 0.2691 | 0.2496 | +0.0195 | 0.741 | 0.110 | 0.104 | 0.536 | 0.445 | **FAIL** | no |
| drex-v2.0 | 0.2525 | 0.2496 | +0.0029 | 0.698 | 0.064 | 0.622 | 0.512 | 0.465 | **FAIL** | no |

Both are indistinguishable from the base rate and slightly worse on Brier. Bootstrap 95% CIs
(1,000 resamples) confirm the uncertainty: clef Δ Brier [−0.0097, +0.0566], AUC [0.418, 0.653];
drex-v2.0 Δ Brier [−0.0046, +0.0223], AUC [0.399, 0.626]. There is no evidence of skill, and no
evidence of reliable harm either at n=100.

### Probability histogram and reliability

| Bin | clef n | clef mean p | clef obs | drex n | drex mean p | drex obs |
|---|---|---|---|---|---|---|
| 0.1–0.2 | 4 | 0.183 | 0.750 | 0 | — | — |
| 0.2–0.3 | 17 | 0.252 | 0.647 | 0 | — | — |
| 0.3–0.4 | 16 | 0.352 | 0.250 | 1 | 0.399 | 0.000 |
| 0.4–0.5 | 24 | 0.454 | 0.458 | **84** | 0.458 | 0.524 |
| 0.5–0.6 | 25 | 0.555 | 0.560 | 15 | 0.508 | 0.533 |
| 0.6–0.7 | 14 | 0.651 | 0.643 | 0 | — | — |

clef-flash never goes above 0.7; drex-v2.0 puts **99/100** probabilities in 0.4–0.6. This is the
degenerate-calibration failure the brief asked us to watch for. The Brier numbers near 0.25 are
mostly the base rate talking, not the model.

### Look-ahead audit

- Every state field is timestamped at or before `known_at`: prior close, 20-day return, delivery %,
  market cap (latest results filing with `known_at_utc ≤ event`) and trade value. The one exception
  is sector, taken from the NSE classification snapshot (2026-10-19); classification is stable but
  not time-versioned. The one missing delivery % is a bulk event on 2026-09-09.
- Event window is 2026-08-03..09-10; model release dates are 2026-10-08..10-16, so the events
  predate the releases. The models could still have seen 2026 news in pretraining; this is a
  **contamination risk**, and B should be read as an upper bound, not a clean out-of-sample test.
  No qualifying post-release events exist in the requested window.

### Latency, rate limits, cost

| Model | p50 | p95 | 429s | Retries | Cost / 100 | Cost / 1,000 |
|---|---|---|---|---|---|---|
| clef-flash | 1,077 ms | 2,045 ms | 0 | 0 | $0.00092 | $0.009 |
| drex-v2.0 | 1,067 ms | 1,504 ms | 11 | 11 | $0.00070 | $0.007 |

## Cost summary

| Arm | Items | clef-flash | drex-v2.0 | drex-max |
|---|---|---|---|---|
| A1 | 200 announcements | $0.00510 / $0.026 per 1k | $0.00582 / $0.029 per 1k | — |
| A2 | 288 pairs (48 queries) | $0.00922 / $0.032 per 1k pairs / $0.192 per 1k queries | $0.01233 / $0.043 / $0.257 | $0.02718 / $0.094 / $0.566 |
| B | 100 events | $0.00092 / $0.009 per 1k | $0.00070 / $0.007 per 1k | — |
| **Total** | 1,464 scored calls + probes + query embedding | | **$0.061313** | |

The budget estimate was ~$0.09; actual list-price spend is $0.0613 (68% of estimate, 13.6% of the
$0.45 cap). No call was skipped by the cap.

## Failure-point log

1. **Schema/format.** 0 refusals, 0 missing probabilities, 0 malformed choices across 1,464 scored
   calls; all A1 probability vectors sum to 1 within 0.02. Format-error rate 0% (fail threshold 2%).
   The typed endpoint does what it promises. One drex-v2.0 probe hit `429 Model busy`; the retry
   succeeded.
2. **Degenerate calibration.** B: drex-v2.0 has 99/100 probabilities in 0.4–0.6 (84 in 0.4–0.5);
   clef-flash never exceeds 0.7. A2: all models put 71–84/288 pairs at 0.9–1.0 with 49–58% observed
   hit rates. A1: 129–149/200 at 0.9–1.0 with 88–89% observed accuracy. The probabilities are
   sharp but not calibrated; B is the extreme case.
3. **Context limits.** 0 truncations. Max observed input was 1,609 tokens (clef, A2) against a
   24,576-token window; A1 max state 1,959 chars, A2 max passage 3,511 chars, B max state 286
   chars. Truncation was never needed.
4. **Label noise (A1).** 3/30 wrong = 10% overall, but 2/4 wrong in *Others* (50%) and 1/4 in
   *Company Update* (25%). The audited-clean subset is 27 items. The extra *Other / not listed*
   choice collides semantically with *Others*; merging them changes drex-v2.0's clean accuracy from
   88.9% to 96.3% but raises ECE, so calibration still fails. Full *Others* audit is the next
   data-quality step.
5. **Look-ahead (B).** 99/100 PIT checks clean; the exception is one missing delivery %. Sector is
   a current snapshot, not time-versioned. Events are 2026-08-03..09-10, before the models' release
   dates, but a 2026 pretraining cutoff cannot be ruled out; B is an upper bound.
6. **Rate limits / latency.** 48 total 429s, all on drex-v2.0 (A1 11, A2 26, B 11); clef-flash and
   drex-max had none. All retries recovered. p50 1.03–1.13 s, p95 1.48–2.04 s across arms.
7. **Cost.** $0.061313 list-price ledger; DeepInfra's billing endpoint shows 6 cents for the three
   decision models this month (whole-cent rounding; clef's billed rate came out below list). The cap
   was never approached; the run can be repeated for about 6 cents.

## Recommendation

**Use drex-v2.0 as a cheap A2 reranker, not as a probability source.** It is the only model/arm
that clears a Pass marker (A2: AUC 0.922, hit@3 93.8%) and it does so at $0.00026/query, about 2.8×
cheaper than Nemotron-3.5-Rerank-8B, though its hit@1 (72.9%) is below the 8B reranker's 81.2% and
its ECE (0.38) says the scores must be calibrated (isotonic on a held-out set) before any threshold
is trusted. clef-flash is cheaper still but does not beat the current A2 baseline; drex-max buys
hit@1 (81.3%) at 2.2× drex-v2.0's cost but loses hit@3, so the pass marker fails. For A1, neither
model is deployable yet: drex-v2.0 is close (88.9% clean accuracy, 0.836 macro-F1, 0.057 ECE) and
the exchange's *Others* bucket is demonstrably noisy, so the honest next step is a full *Others*
audit and a larger clean set, not another model. For B, both models are "not a forecaster yet":
Brier is at or slightly worse than the 52% base rate, the calibration slope is 0.10–0.62, AUC is
0.51–0.54, and drex-v2.0 collapses to ~0.5. With n=100 and a 20-day target, that is expected; a
proper test needs n≥500, a held-out calibration split, and events after the models' release dates
to remove the contamination risk. Overall: the typed decision API is operationally excellent
(zero format errors, ~1 s p50, trivial cost); the current small decision models are useful for
ranking, not yet for calibrated decisions on our documents.
