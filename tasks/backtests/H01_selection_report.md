# H01 stock selection versus announcement timing — exploratory

The date-placebo test retained stock identities. This follow-up shuffles earnings labels within entry month, prior200-session trend and lagged-liquidity group. Positive-minus-negative is an association contrast, not a short-book profit.

Run `3ccfe910-8d7c-4e54-8aaa-ac622cb521ca`.10 new tests;216 tests in BH including all206 prior tests.999 coherent label permutations. No2026 outcomes.

| Sessions | Cohort | Matched events | Matched cells | Positive mean excess | Negative mean excess | Difference | Cluster p | HAC p | BH q | Label placebo p | Max-T p | 2021/22/23/24/25 | Top5 positive payoff share |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|
| 90 | any | 7745 | 158 | 2.17% | 0.48% | 1.70% | 0.00714 | 0.32 | 0.636 | 0.002 | 0.111 | NA/-/+/+/+ | 3.69% |
| 90 | abs_ge_1 | 2202 | 77 | 2.91% | 1.38% | 1.53% | 0.171 | 0.508 | 0.93 | 0.074 | 0.704 | NA/-/+/+/+ | 6.79% |
| 120 | any | 7104 | 144 | 4.58% | 2.10% | 2.48% | 0.00177 | 0.0503 | 0.241 | 0.001 | 0.032 | NA/+/+/+/+ | 4.52% |
| 120 | abs_ge_1 | 2004 | 68 | 4.24% | 2.47% | 1.78% | 0.248 | 0.159 | 0.553 | 0.09 | 0.843 | NA/-/+/+/+ | 8.63% |
| 180 | any | 6544 | 132 | 7.95% | 3.46% | 4.49% | 0.00038 | 0.00202 | 0.0335 | 0.001 | 0.009 | NA/+/+/+/+ | 6.06% |
| 180 | abs_ge_1 | 1802 | 61 | 8.26% | 5.00% | 3.25% | 0.164 | 0.247 | 0.553 | 0.064 | 0.691 | NA/+/+/+/+ | 10.83% |
| 252 | any | 5912 | 119 | 15.58% | 9.92% | 5.66% | 0.000372 | 1 | 1 | 0.002 | 0.007 | NA/+/+/+/NA | 7.61% |
| 252 | abs_ge_1 | 1630 | 54 | 14.79% | 13.06% | 1.73% | 0.588 | 1 | 1 | 0.296 | 0.995 | NA/+/-/+/NA | 13.25% |
| 504 | any | 3295 | 73 | 43.20% | 32.39% | 10.81% | 0.00275 | 1 | 1 | 0.023 | 0.023 | NA/+/+/NA/NA | 11.09% |
| 504 | abs_ge_1 | 971 | 35 | 35.33% | 37.09% | -1.76% | 0.782 | 1 | 1 | 0.554 | 1 | NA/-/-/NA/NA | 21.93% |

Strata require at least3 observations of each sign. Cell weight=min(positive n,negative n). Ledger p=max(cluster p,HAC p). Missing/too-short HAC support gives p1. Thresholds and liquidity boundaries were declared before this follow-up.

Master events:9021; strata:299; excluded for incomplete prior20 liquidity:0.

## Limits and deployment

A selection association can be useful in a future challenger without being a proven standalone PEAD strategy. No variant is promoted. The94 constrained positive books from the longer-horizon grid all hit their strategy kill. Sector/size confounding and full coverage still need work.

- no PIT sector/market-cap controls
- long outcomes overlap;504 has too few independent years
- same stocks can recur across quarters
- existing94 positive books all hit the drawdown kill
- exploratory follow-up after prior results; all prior tests remain in BH

Read-only snapshot unchanged:True; runtime9.5s.
Reproduce: `python -m reality_engine.harness.run_h01_selection`. Features, cell statistics, null distributions and source hashes are saved.
