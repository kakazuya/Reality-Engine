Completed. **H01 remains provisional. No variant is promoted.**

Created:
- [Harness package](C:/Users/warri/Downloads/Info_Diffusion_Model/reality_engine/harness/) with adapter, B5, runner and ledger.
- [Tests](C:/Users/warri/Downloads/Info_Diffusion_Model/reality_engine/tests/test_harness_h01.py).
- [Report](C:/Users/warri/Downloads/Info_Diffusion_Model/tasks/backtests/H01_report.md), [results JSON](C:/Users/warri/Downloads/Info_Diffusion_Model/tasks/backtests/H01_results.json), event/monthly CSVs and verification artifacts.
- `reality_engine/data/backtests/ledger.duckdb`: **16 rows**, preserving both runs.

**Tests: 80 passed** — 43 harness + 37 existing horizon tests. Independent artifact checks also passed.

| Measure | Sign | Days | Events | Mean net excess | BH q | Placebo p |
|---|---|---:|---:|---:|---:|---:|
| PAT | Positive | 20 | 3,757 | −1.36% | .304 | .002 |
| PAT | Negative | 20 | 2,328 | −1.57% | .304 | .994 |
| Revenue | Positive | 20 | 4,500 | −1.30% | .304 | .002 |
| Revenue | Negative | 20 | 1,601 | −1.83% | .304 | .952 |
| PAT | Positive | 60 | 3,297 | +0.24% | .794 | 1.000 |
| PAT | Negative | 60 | 2,040 | −1.38% | .318 | 1.000 |
| Revenue | Positive | 60 | 3,943 | +0.22% | .794 | .998 |
| Revenue | Negative | 60 | 1,402 | −2.20% | .304 | .856 |

All four long books hit the kill on **2 May 2022**. Sleeve CAGR: −1.48% PAT / −1.65% revenue. Maximum drawdown: 8.67% / 8.41%.

Deviations: incomplete coverage; B5 previous-close proxy; late-XBRL exclusions; flagged missing-exit loss bounds; base capital-gains tax only. Banks lack the card’s exact PAT field. A bank-label correction required the second run; both runs remain in BH.

Runtime: **37.8 seconds corrected run**, 80.7 seconds across both runs; approximately 24 minutes total work. Snapshot unchanged. No commits.