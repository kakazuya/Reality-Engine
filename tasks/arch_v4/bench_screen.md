# Screen benchmark — measured (`bench_screen.py`)

Machine: Python 3.14.7, numpy 2.5.4, 8 logical CPUs. numpy only; every store read with `mode=ro&immutable=1`; no GPU, no network.

## 1. What was measured

| input | source | size | build |
|---|---|---|---|
| standardised daily returns (T x N) | `pilot\pilot60\market_state_pilot.db` | 492 sessions x 4042 companies (2296201 rows, last date 2026-10-19) | 57.15 s |
| driver matrix (T x D) | `pilot\pilot60\market_state_b.db` | 33 drivers (22 commodity series + equal-weight market + 10 index-membership groups) | 0.195 s |

The drivers are held series, not synthetic: World Bank commodity monthlies forward-filled onto the trading calendar, the equal-weight market return, and index-membership group means (the pilot has no populated sector map, so membership stands in for it).

## 2. Timings

| step | measured | note |
|---|---:|---|
| one lag, full screen (N x D) | 15.3 ms | 65,625,912 multiply-adds in one BLAS gemm |
| ten lags | 141.5 ms | ten gemms, the nightly per-driver sweep |
| factor residualisation, 20 given factors | 70.5 ms | OLS per company, `(F'F)^-1 F'Z`, linear in T x N x F |
| **residualise + ten lags (full daily screen)** | **219.9 ms** | what the nightly tier actually does |
| A^2 (2,000 x 500 bipartite -> 2,000 x 2,000) | 61.87 ms | 20,000 typed edges, fp32 dense |
| A^3 | 57.60 ms | two gemms |
| prune below threshold after a multiply | 14.69 ms | elementwise threshold on the 2,000 x 2,000 result |
| shock walk, 3 hops, top-10 | 8.010 ms | synthetic edge matrix |
| one new day, ten lags (incremental) | 1.901 ms | 133,386 cross-product terms, no recompute |

RAM peak (process RSS): **587.6 MB** (panel 7.6 MB + drivers 102 KB; the rest is the row loader). Under the 2 GB guard threshold, so `ram_guard.ps1` was not needed.

Throughput: 4.29e+09 multiply-adds/s.

## 3. Extrapolation to the full universe

The screen is one gemm per lag, so cost is linear in `days x entities x drivers`. The numbers below scale the measured rate to the design's full-universe size (`2000` entities, `500` drivers); they are arithmetic on a measured rate, not a second measurement.

| entities | drivers | days | one screen | ten lags |
|---:|---:|---:|---:|---:|
| 2,000 | 500 | 492 | 0.1146 s | 1.1456 s |
| 4,042 | 500 | 492 | 0.2315 s | 2.3153 s |

## 4. Acceptance targets — confirmed or corrected

| target | budget | measured | verdict |
|---|---:|---:|---|
| full daily screen < 5 min | 300 s | 219.9 ms | met, loose by 1364x |
| nightly incremental < 10 min | 600 s | 1.9 ms | met, loose by 315623x |
| shock walk < 2 s | 2 s | 8.0 ms | met, loose by 250x |

**The proposed targets are far too loose for the correlation work.** The full daily screen is 220 ms, not five minutes, and the incremental update is 1901 microseconds. The 5-minute "screen" budget is really spent on the feature build (panel assembly, point-in-time stamping, factor refresh) and on disk, not on the linear algebra — so §F's budget should be re-stated as: **hot path < 2 s, warm tier = feature build + stale-edge refresh, and the correlation itself is free**.

Both steps are linear in `days x entities x factors`, which is why the numbers stay this small. The only quadratic term in the design is *extracting* the factors from the panel itself (build an `N x N` covariance, then factorise it: `O(N^2)` memory, `O(N^3)` work, ~70 MB and seconds at 4,000 companies). That path belongs to the weekly cold tier; the nightly tier regresses on the 20 declared factors, as measured here.

The RAM peak (587.6 MB) is the **loader**, not the maths: the panel is only 7.6 MB once built, and the peak comes from materialising 2,296,201 `(date, isin, close)` tuples before filling the array. Stream into a pre-allocated array and the working set is the panel size.

## 5. GPU (GTX 1050 Ti, 4 GB) — what it would and would not change

The measured CPU throughput is 4.3 G multiply-adds/s (~8.6 GFLOP/s). A GTX 1050 Ti is ~2 TFLOP/s fp32 peak, i.e. ~233x the measured rate before bus and kernel-launch overhead.

- **Where the GPU would win**: the weekly cold tier (many lags x many drivers x many windows), A^k powers at full universe, and the dense screen when the entity count passes ~10k. The work is DGEMM/GEMV, so a `cupy` or `torch` port is mechanical.
- **Where it would not**: the hot path (single lookups, stored edges, a 3-hop beam walk) is microseconds on the CPU; a CUDA context costs more than the answer. Same lesson as the OCR experiment on this card: measure first. On this card GPU OCR lost to CPU.

- **VRAM tiling**: the driver matrix is `T x D` (500 days x 500 drivers x fp32 = 1 MB); the panel is `T x N` (500 x 4,000 x fp32 = 8 MB); the `N x N` covariance at 4,000 entities is 64 MB. Tiles are taken over the **row** axis: `rows_per_tile = 0.75 GB / (N * 4 bytes)` = 50,331 days per tile at N=4,000, i.e. the whole window fits in one tile with a 3 GB budget, and only the `N x N` products at >8,000 entities need splitting. Accumulate in fp32, never fp64.

- **Install (named, not done here)**: `cupy-cuda12x` (matches the CUDA 12 driver; a 4 GB card needs no more) or `torch` with the CUDA 12 wheel. CPU fallback is the numpy path above, kept as the reference implementation the GPU result is checked against (`np.allclose`, 1e-5, on one window before every cold run).

## 6. What this does not measure

- Point-in-time stamping and `known_at` filtering cost (indexed SQL, measured separately in `tasks/arch_v3/SPEED_PLAN.md`: 0.01-9.6 ms per lookup).
- The per-entity coverage check that decides NOT IN DATA for a claim topic (a lookup, not a scan).
- Cold-cache disk reads: the panel came off the C: SSD with the page cache warm.

- **Panel assembly is the real cost.** The SQLite read of 2,296,201 rows took 57 s at ~40k rows/s, i.e. ~20x the whole ten-lag screen. That is the argument for the Parquet/partitioned fact store in §F: the screen must never rebuild its panel from SQLite. A real run reads one atom-partition plus a cached returns panel.

