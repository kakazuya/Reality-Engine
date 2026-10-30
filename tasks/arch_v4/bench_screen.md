# Screen benchmark — measured (`bench_screen.py`)

Machine: Python 3.14.7, numpy 2.5.4, 8 logical CPUs. numpy only; every store read with `mode=ro&immutable=1`; no GPU, no network.

## 1. What was measured

| input | source | size | build |
|---|---|---|---|
| standardised daily returns (T x N) | `pilot\pilot60\market_state_pilot.db` | 492 sessions x 4042 companies (2296201 rows, last date 2026-10-19) | 50.76 s |
| driver matrix (T x D) | `pilot\pilot60\market_state_b.db` | 33 drivers (22 commodity series + equal-weight market + 10 index-membership groups) | 0.061 s |

The drivers are held series, not synthetic: World Bank commodity monthlies forward-filled onto the trading calendar, the equal-weight market return, and index-membership group means (the pilot has no populated sector map, so membership stands in for it). Every driver column is standardised once, before the clock starts — without that the gemm multiplies standardised returns by raw levels (a commodity level reaches 55,385 here) and the output is a cross-product, not a correlation.

## 2. Timings

| step | measured | note |
|---|---:|---|
| one lag, full screen (N x D) | 18.8 ms | 65,625,912 multiply-adds in one BLAS gemm |
| ten lags | 183.7 ms | ten gemms, the nightly per-driver sweep |
| factor residualisation (11 declared factors: market + index groups, OLS) | 14.3 ms | OLS per company, `(F'F)^-1 F'Z`, linear in T x N x F |
| declared factors used | market:equal_weight_z, index:nifty500, index:niftymidsmallcap400, index:niftysmallcap250, index:niftymicrocap250, index:niftytotalmarket, index:niftylargemidcap250, index:niftymidcap150, index:niftyalpha50, index:nifty200, index:niftysmeemerge | see §F.1 — the leading commodity columns are drivers, not factors |
| **residualise + ten lags (full daily screen)** | **252.6 ms** | what the nightly tier actually does |
| A^2 (2,000 x 500 bipartite -> 2,000 x 2,000) | 18.39 ms | 20,000 typed edges, fp32 dense |
| A^3 | 36.57 ms | two gemms |
| prune below threshold after a multiply | 8.93 ms | elementwise threshold on the 2,000 x 2,000 result |
| shock walk, 3 hops, top-10 | 5.810 ms | synthetic edge matrix |
| one new day, ten lags (incremental) | 1.794 ms | 133,386 cross-product terms, no recompute |

RAM peak (process RSS): **591.7 MB** (panel 7.6 MB + drivers 102 KB; the rest is the row loader). Under the 2 GB guard threshold, so `ram_guard.ps1` was not needed.

Throughput: 3.50e+09 multiply-adds/s.

## 3. Extrapolation to the full universe

The screen is one gemm per lag, so cost is linear in `days x entities x drivers`. The numbers below scale the measured rate to the design's full-universe size (`2000` entities, `500` drivers); they are arithmetic on a measured rate, not a second measurement.

| entities | drivers | days | one screen | ten lags |
|---:|---:|---:|---:|---:|
| 2,000 | 500 | 492 | 0.1407 s | 1.4071 s |
| 4,042 | 500 | 492 | 0.2844 s | 2.8438 s |

## 4. Acceptance targets — confirmed or corrected

| target | budget | measured | verdict |
|---|---:|---:|---|
| full daily screen < 5 min | 300 s | 252.6 ms | met, loose by 1188x |
| nightly incremental < 10 min | 600 s | 1.8 ms | met, loose by 334448x |
| shock walk < 2 s | 2 s | 5.8 ms | met, loose by 344x |

**The proposed targets are far too loose for the correlation work.** The full daily screen is 253 ms, not five minutes, and the incremental update is 1794 microseconds. The 5-minute "screen" budget is really spent on the feature build (panel assembly, point-in-time stamping, factor refresh) and on disk, not on the linear algebra — so §F's budget should be re-stated as: **hot path < 2 s, warm tier = feature build + stale-edge refresh, and the correlation itself is free**.

Both steps are linear in `days x entities x factors`, which is why the numbers stay this small. The only quadratic term in the design is *extracting* the factors from the panel itself (build an `N x N` covariance, then factorise it: `O(N^2)` memory, `O(N^3)` work, ~70 MB and seconds at 4,000 companies). That path belongs to the weekly cold tier; the nightly tier regresses on the 20 declared factors, as measured here.

The RAM peak (591.7 MB) is the **loader**, not the maths: the panel is only 7.6 MB once built, and the peak comes from materialising 2,296,201 `(date, isin, close)` tuples before filling the array. Stream into a pre-allocated array and the working set is the panel size.

## 5. False-discovery null — which permutation gives an honest max |corr|

An FDR pass needs the distribution of the **maximum** screen value when nothing is related. Three nulls were measured on the residualised pilot panel, because the wrong one inflates the threshold and hides every real link.

- **observed** max |corr| = **0.411** over 133,386 pairs. With the 4,206 mechanical self-membership pairs excluded (a company and its own index-group mean) it is **0.411**.
  On those 4,206 mechanical pairs alone the max is **0.003** with the market and index-group factors stripped, and **0.501** with the leading commodity columns used as factors — which is the defect: a company and its own group mean are near-collinear unless the group mean is residualised out, and then the max-statistic null is set by that arithmetic rather than by chance.
- **per-pair permutation** — each pair gets its own shuffle of one series, the textbook null: max |corr| = **0.209** on 2,000 sampled pairs x 10 shuffles; over all 133,386 pairs the expected maximum is **0.205** (median of 200 draws from the t(492-2) null).
- **block permutation** — one circular shift of every driver row, all drivers together, so the cross-driver structure and each driver's own autocorrelation survive and only the time alignment breaks: max |corr| = **0.393** median / 0.499 max over 20 shuffles on all pairs, and **0.393** median / 0.499 max once the mechanical pairs are dropped.

The design adopts the **block-permutation null on the pair set with the mechanical self-membership pairs removed**. It is the only one of the three that keeps a driver's own autocorrelation — which is what a false discovery on a forward-filled monthly commodity series actually looks like — and the self-membership pairs are not tested at all: that link is arithmetic, not evidence, and testing it would spend a false-discovery slot on a definition.

Factors used for the residualisation: ['market:equal_weight_z', 'index:nifty500', 'index:niftymidsmallcap400', 'index:niftysmallcap250', 'index:niftymicrocap250', 'index:niftytotalmarket', 'index:niftylargemidcap250', 'index:niftymidcap150', 'index:niftyalpha50', 'index:nifty200', 'index:niftysmeemerge'].

## 6. GPU (GTX 1050 Ti, 4 GB) — measured separately, in `bench_gpu.md`

The measured CPU throughput is 3.5 G multiply-adds/s (~7.0 GFLOP/s). The device question is no longer a guess: `bench_gpu.py` / `bench_gpu.md` ran 7 workloads as one function parameterised by the array module (median of 5, `np.allclose` before timing).

- **Where the GPU wins**: the nightly screen (4.32x at 4,042 companies x 1,650 drivers), rolling windows (4.63x), and the weekly cold tier — permutations 14.51x, A^k 3.95x, covariance + eigenvectors 5.22x. The crossings are far below the ~10k-entity guess this section used to make: the screen is already 13.32x at the pilot size and 3.54x at 1,024 companies.
- **Where it does not**: any per-call workload. The incremental one-day update is 0.45x (1.47 ms CPU vs 3.25 ms GPU including transfer) and a cold CUDA context costs 0.80 s. The hot path stays on the CPU because it is latency-shaped, not because the card is slow.

- **Install (named, not required by the query path)**: `cupy-cuda12x` on the GTX 1050 Ti, 4 GB — a stated ceiling, so tiling is part of the test. Set `CUPY_CACHE_IN_MEMORY=1` in sandboxed or read-only runs: the default kernel cache writes to `~/.cupy` and fails where the home directory is not writable. The numpy path here stays the reference, checked against any GPU result with `np.allclose` on one window before it is timed.

## 7. What this does not measure

- Point-in-time stamping and `known_at` filtering cost (indexed SQL, measured separately in `tasks/arch_v3/SPEED_PLAN.md`: 0.01-9.6 ms per lookup).
- The per-entity coverage check that decides NOT IN DATA for a claim topic (a lookup, not a scan).
- Cold-cache disk reads: the panel came off the C: SSD with the page cache warm.

- **Panel assembly is the real cost.** The SQLite read of 2,296,201 rows took 51 s at ~45k rows/s, i.e. ~20x the whole ten-lag screen. That is the argument for the Parquet/partitioned fact store in §F: the screen must never rebuild its panel from SQLite. A real run reads one atom-partition plus a cached returns panel.

