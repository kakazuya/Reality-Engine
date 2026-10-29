# GPU vs CPU — measured (`bench_gpu.py`)

Machine: Python 3.14.7, numpy 2.5.4, 8 logical CPUs, NVIDIA GeForce GTX 1050 Ti (sm_6.1, 4.0 GB), CuPy 14.2.0 (CUDA 12.9 runtime, driver supports CUDA 13.0). 3.3 GB of VRAM was free at start (the desktop holds the rest); the heaviest workload peaked at 1953 MB of pool, inside the 2.5 GB budget.

## 1. Method

- Data: the held pilot panel — 492 sessions x 4,042 companies and the 33 held drivers, loaded with `bench_screen.py`'s own loaders (61 s from SQLite, `mode=ro&immutable=1`). Wider entity and driver counts are synthetic at the same shape with a fixed seed, as labelled in each table.
- Every workload is **one function parameterised by the array module** (`numpy` or `cupy`), so both columns run the same code and the same arithmetic. The only thing that differs is the device.
- fp32 on both devices; the fp64 CPU column is the same function on fp64-cast inputs (reference only). Correctness is `allclose(rtol=0.0001, atol=1e-05)` against the numpy fp32 result — atol because a correlation near zero has no relative scale, and equal_nan because the held panel is sparse. Pascal (sm_61) has no TF32, so the cuBLAS fp32 path is true fp32 and the comparison is not precision-tuned.
- Where a row's `allclose` reads **NO**, its note gives the gate as a number (`max |a-b| / (atol + rtol|b|)`, so >1 fails), the same gate between numpy's fp32 and fp64 results, and the gate between the GPU in fp64 and numpy in fp64. That pins the cause: if numpy's own fp32 is the one far from fp64 and the GPU's fp64 agrees with numpy's fp64, the limit is fp32 arithmetic on that statistic, not the device. It does happen: a correlation near zero is a sum of 492 O(1) products that almost cancel, so fp32's per-term rounding lands at 1e-5..1e-4 on the small value — on both devices alike, and the two do not have to agree with each other there.
- Warm up once, then the **median of 5** runs, capped at 5 where one pass exceeds a per-workload budget (the 4,042 eigen-decomposition is ~17 s a pass); the actual repeat count is printed in every row. The GPU is synchronised before the clock stops and after the previous run finishes.
- **GPU excl. transfer** = the panel is already resident, which is the steady state of a pipeline that keeps its data on the device. **GPU incl. transfer** = upload the inputs, compute, download the result on every call, which is what a one-shot call pays. Neither includes the one-time context: that is priced separately below.
- One full-size transfer is 3.29 ms up and 6.81 ms down (7.6 MB, pageable memory, ~2 GB/s). Any workload whose compute is below that toll cannot win on this bus.

### One-time CUDA cost (per process)

| stage | measured |
|---|---:|
| `import cupy` | 0.32 s |
| context creation + first kernel compile (NVRTC) + first launch + sync | 0.48 s |
| **cold start, first byte of GPU work** | **0.80 s** |

That is the toll any *short* GPU call pays before it has done any work: 0.8 s of process start-up against a hot-path answer of a few ms. It is why the hot path stays on the CPU as a long-lived service, not because the GPU is slow.

## 2. Full daily screen — residualise on 20 factors + 10 lags

The nightly tier's correlation work: one OLS residualisation on 20 given factors, then ten lagged company x driver gemms. The pilot row is the held panel (492 sessions x 4,042 companies) and the held 33 drivers; the wider rows keep the held panel and widen the drivers to 330 and 1,650 (x10, x50) as the brief asks; the narrow rows are synthetic at the same shape, to find the crossing. The driver columns are standardised once before timing: `bench_screen.py` feeds the held driver **levels** straight into the same gemm (abs max 55,385), so its output is a cross-product of magnitude ~1e4, not a correlation, and fp32 accumulation then disagrees by 4e-4 relative — which no rtol on the value can fairly judge. Standardising is a column transform outside the timed region, so the timings are unchanged.

| size | CPU fp32 | CPU fp64 | GPU excl | GPU incl | GPU/CPU | allclose | reps (cpu/gpu) |
|---|---:|---:|---:|---:|---:|:--:|:--:|
| N=256 492x256x33 | 5.41 ms | — | 12.2 ms | 11.8 ms | 0.46x | **NO** | 5/5 | gate 3.5x (>1 fails)
| N=512 492x512x33 | 8.14 ms | — | 16.9 ms | 16.2 ms | 0.50x | **NO** | 5/5 | gate 4x (>1 fails)
| N=1024 492x1024x33 | 23.1 ms | — | 5.68 ms | 6.54 ms | 3.54x | **NO** | 5/5 | gate 4.4x (>1 fails)
| N=2048 492x2048x33 | 63 ms | — | 5.39 ms | 6.86 ms | 9.18x | **NO** | 5/5 | gate 5.9x (>1 fails)
| pilot 492x4042x33 | 159 ms | 226 ms | 9.51 ms | 12 ms | 13.32x | **NO** | 5/5 | gate 6.4x, np fp32 vs fp64 8.8x, gpu fp64 vs np fp64 7.5e-08x (>1 fails)
| drivers x10 492x4042x330 | 193 ms | 336 ms | 17.6 ms | 31.3 ms | 6.17x | yes | 5/5 |
| drivers x50 492x4042x1650 | 514 ms | 992 ms | 57.9 ms | 119 ms | 4.32x | yes | 5/5 |

5 of 7 rows miss the fp32 gate. `pilot 492x4042x33` carries the attribution: numpy's own fp32 is 8.8x from numpy fp64 on the same output, while the GPU in fp64 is 7.5e-08x from numpy fp64 — so the miss is fp32 arithmetic on a near-zero correlation, not the device (the other rows show the same output with fewer reference columns).

**Crossover: `N=1024 492x1024x33`** — the first measured size where the GPU with transfer beats the CPU (3.54x). The largest measured size is 13.32x.

## 3. A^2 / A^3 with pruning on the edge matrix

Two gemms and the post-multiply threshold, on bipartite edge matrices (20 typed links per entity, fp32 dense — the same matrix `bench_screen.py` times).

| size | CPU fp32 | CPU fp64 | GPU excl | GPU incl | GPU/CPU | allclose | reps (cpu/gpu) |
|---|---:|---:|---:|---:|---:|:--:|:--:|
| A 500x125 | 7.23 ms | — | 0.211 ms | 0.565 ms | 12.79x | yes | 5/5 |
| A 1000x250 | 6.41 ms | — | 0.946 ms | 2.47 ms | 2.59x | yes | 5/5 |
| A 2000x500 | 41.1 ms | 77.9 ms | 5.18 ms | 10.9 ms | 3.78x | yes | 5/5 |
| A 4000x2000 | 407 ms | 813 ms | 71.1 ms | 98.8 ms | 4.12x | yes | 5/5 |
| A 8000x8000 | 5.37 s | 10.7 s | 1.19 s | 1.36 s | 3.95x | yes | 5/5 |

**Crossover: `A 500x125`** — the first measured size where the GPU with transfer beats the CPU (12.79x). The largest measured size is 12.79x.

## 4. 3-hop shock walk, top-10 (the hot path)

Three hops of gather -> propagate -> reweight, keeping the top 10 per hop. Its output is three numbers, so it pays the transfer in both directions but moves almost nothing. Each hop reads a device scalar back to the host, and a WDDM sync waits on the same card that is driving the desktop, so the GPU figure here is the noisiest in the report (it moves by 2x between runs); the CPU figure is stable and is the one the verdict rests on. A margin of a few percent at the largest size is a tie, not a win.

| size | CPU fp32 | CPU fp64 | GPU excl | GPU incl | GPU/CPU | allclose | reps (cpu/gpu) |
|---|---:|---:|---:|---:|---:|:--:|:--:|
| A 500x125 | 0.192 ms | — | 1.44 ms | 1.56 ms | 0.12x | yes | 5/5 |
| A 1000x250 | 0.523 ms | — | 1.44 ms | 1.6 ms | 0.33x | yes | 5/5 |
| A 2000x500 | 5.29 ms | 8.94 ms | 1.52 ms | 1.93 ms | 2.75x | yes | 5/5 |

**Crossover: `A 2000x500`** — the first measured size where the GPU with transfer beats the CPU (2.75x). The largest measured size is 2.75x.

## 5. Incremental one-day update

One new session folded into every running statistic: ten outer products of the new day against the last ten driver days. This is what the nightly job does per new day, not the whole screen.

| size | CPU fp32 | CPU fp64 | GPU excl | GPU incl | GPU/CPU | allclose | reps (cpu/gpu) |
|---|---:|---:|---:|---:|---:|:--:|:--:|
| one day 256x33 | 0.252 ms | — | 2.52 ms | 4.01 ms | 0.06x | yes | 5/5 |
| one day 1024x33 | 0.519 ms | — | 2.52 ms | 2.81 ms | 0.18x | yes | 5/5 |
| one day 2048x33 | 0.854 ms | — | 2.47 ms | 3.04 ms | 0.28x | yes | 5/5 |
| one day 4042x33 | 1.47 ms | 7.44 ms | 2.47 ms | 3.25 ms | 0.45x | yes | 5/5 |

**No crossover.** The GPU never beats the CPU with transfer at any measured size; at the largest (`one day 4042x33`) the CPU costs 1.47 ms and the GPU 3.25 ms including the transfer (0.45x).

## 6. Permutation test for the false-discovery check (cold-tier candidate)

The cold tier's job: re-run the whole screen on permuted driver days and keep the max |corr| per lag. The brief names 1,000 shuffles; one shuffle is the unit measured here and the 1,000-shuffle cost is projected from it (linear in the shuffle count, nothing is cached between shuffles), then anchored by one real 1,000-shuffle run on the winner.

**Anchored 1,000-shuffle run on the winner:** `gpu` 8.97 s measured against a 9.15 s projection — gate 4.6x (>1 fails), the same fp32 conditioning limit the 20-shuffle row attributes to the statistic rather than to the device.

| size | CPU fp32 | CPU fp64 | GPU excl | GPU incl | GPU/CPU | allclose | reps (cpu/gpu) |
|---|---:|---:|---:|---:|---:|:--:|:--:|
| 1 shuffle | 125 ms | 194 ms | 9.09 ms | 10.3 ms | 12.15x | yes | 5/5 |
| 5 shuffles | 668 ms | — | 45.3 ms | 46.6 ms | 14.32x | **NO** | 5/5 | gate 4.1x (>1 fails)
| 20 shuffles | 2.65 s | 4.05 s | 183 ms | 183 ms | 14.51x | **NO** | 5/5 | gate 4.1x, np fp32 vs fp64 2.5x, gpu fp64 vs np fp64 7.1e-09x (>1 fails)

2 of 3 rows miss the fp32 gate. `20 shuffles` carries the attribution: numpy's own fp32 is 2.5x from numpy fp64 on the same output, while the GPU in fp64 is 7.1e-09x from numpy fp64 — so the miss is fp32 arithmetic on a near-zero correlation, not the device (the other rows show the same output with fewer reference columns).

**Crossover: `1 shuffle`** — the first measured size where the GPU with transfer beats the CPU (12.15x). The largest measured size is 14.51x.

## 7. Rolling-window stability — 20 windows x 10 lags

The screen re-run on 20 overlapping quarter-length windows (123 sessions each), keeping the max |corr| per lag. The panel is uploaded once and every window is cut on the device.

| size | CPU fp32 | CPU fp64 | GPU excl | GPU incl | GPU/CPU | allclose | reps (cpu/gpu) |
|---|---:|---:|---:|---:|---:|:--:|:--:|
| 1 window x 123d | 35.3 ms | — | 6.11 ms | 7.4 ms | 4.77x | yes | 5/5 |
| 5 windows x 123d | 137 ms | — | 29.3 ms | 30.3 ms | 4.54x | yes | 5/5 |
| 20 windows x 123d | 546 ms | 987 ms | 122 ms | 118 ms | 4.63x | yes | 5/5 |
| 60 windows x 123d | 1.63 s | — | 360 ms | 361 ms | 4.53x | yes | 5/5 |

**Crossover: `1 window x 123d`** — the first measured size where the GPU with transfer beats the CPU (4.77x). The largest measured size is 4.77x.

## 8. N x N covariance + top-20 eigenvectors (latent-factor extraction)

The only super-linear step in the design: an N x N covariance of the panel and a full eigendecomposition for the top 20 latent factors. Checked on the eigenvector *subspace* (the projector `VV'`), because an eigenvector's sign is arbitrary and a per-element compare would fail for a correct answer.

| size | CPU fp32 | CPU fp64 | GPU excl | GPU incl | GPU/CPU | allclose | reps (cpu/gpu) |
|---|---:|---:|---:|---:|---:|:--:|:--:|
| eig 512 | 55.1 ms | — | 14.2 ms | 14.4 ms | 3.82x | yes | 5/5 |
| eig 1024 | 212 ms | — | 62.3 ms | 62.6 ms | 3.39x | yes | 5/5 |
| eig 2048 | 1.1 s | — | 304 ms | 304 ms | 3.62x | yes | 5/5 |
| eig 4042 | 7.22 s | 6.79 s | 1.38 s | 1.38 s | 5.22x | yes | 5/5 |

**Crossover: `eig 512`** — the first measured size where the GPU with transfer beats the CPU (3.82x). The largest measured size is 5.22x.

## 9. Crossover summary

| workload | axis | first GPU win (incl. transfer) | speedup there | largest measured | speedup there |
|---|---|---|---:|---|---:|
| screen | T x N x D | `N=1024 492x1024x33` | 3.54x | pilot 492x4042x33 | 13.32x |
| graph | entities x drivers | `A 500x125` | 12.79x | A 500x125 | 12.79x |
| walk | entities x drivers | `A 2000x500` | 2.75x | A 2000x500 | 2.75x |
| incremental | companies x drivers | no crossover measured | — | one day 4042x33 | 0.45x |
| perm | shuffles | `1 shuffle` | 12.15x | 20 shuffles | 14.51x |
| rolling | windows | `1 window x 123d` | 4.77x | 1 window x 123d | 4.77x |
| cov | companies | `eig 512` | 3.82x | eig 4042 | 5.22x |

## 10. Verdict by tier

A device hop costs a transfer each way plus a process's worth of context, so the bands are: **>=2x on the largest named size is a GPU win**, **0.5x..2x is a tie** and **<0.5x is a CPU win**. The tie band is not a fudge: the per-call GPU figures here are not reproducible to better than ~2x between runs of this script, so a 1.9x result cannot be told apart from noise (the incremental update, at 0.44x, can). The shock walk is flagged **tie (unstable)**: it synchronises the device three times per call on a card that is also driving the desktop, and measured 1.03x, 1.94x and 2.77x on three runs of this script, so it needs 5x before it can be awarded to either side.

| tier | workload | largest measured | CPU fp32 | GPU incl | GPU/CPU | device |
|---|---|---|---:|---:|---:|---|
| hot path | walk | A 2000x500 | 5.29 ms | 1.93 ms | 2.75x | **tie (unstable)** |
| hot path | incremental | one day 4042x33 | 1.47 ms | 3.25 ms | 0.45x | **CPU** |
| nightly | screen | drivers x50 492x4042x1650 | 514 ms | 119 ms | 4.32x | **GPU** |
| nightly | rolling | 20 windows x 123d | 546 ms | 118 ms | 4.63x | **GPU** |
| weekly cold | perm | 20 shuffles | 2.65 s | 183 ms | 14.51x | **GPU** |
| weekly cold | graph | A 8000x8000 | 5.37 s | 1.36 s | 3.95x | **GPU** |
| weekly cold | cov | eig 4042 | 7.22 s | 1.38 s | 5.22x | **GPU** |

- **hot path** -> **CPU**: walk 2.75x, incremental 0.45x.
- **nightly** -> **GPU**: screen 4.32x, rolling 4.63x.
- **weekly cold** -> **GPU**: perm 14.51x, graph 3.95x, cov 5.22x.

The GPU wins 5 of 7 workloads on their largest named size (screen 4.32x, rolling 4.63x, perm 14.51x, graph 3.95x, cov 5.22x), ties on walk 2.75x, and the CPU wins incremental 0.45x. **The dividing line is not the tier.** It is whether the unit of work is one call — a sync, a transfer each way and microseconds of arithmetic — or a pass over data that can stay resident. Every per-call workload loses; every pass over a resident panel wins at the sizes that matter, and the crossings are small (section 9), because the arithmetic that has to amortise a 10.1 ms round trip is already tens of milliseconds.

That is where `bench_screen.md`'s guess is wrong: it assumed the GPU only wins "when the entity count passes ~10k", but at the pilot size (pilot 492x4042x33) the screen is 159 ms on the CPU against 12 ms on the GPU **including the transfer** (13.32x), and the crossing is already at `N=1024 492x1024x33` (3.54x) — far below the design's ~10k guess. What the GPU cannot do is answer a per-call hot-path question, and that is the tier that has to stay on the CPU.

**Verdict.** Hot path: **CPU**, but for two different reasons. The incremental one-day update is a clean CPU win (the GPU is 0.45x), while the shock walk is inside its own run-to-run spread and cannot be awarded to either device; the design's real hot path is cheaper than that walk, so the tier stays on the CPU. Nightly (daily screen and rolling windows): **GPU** — which contradicts the design's claim. It is not a size effect: the screen wins end to end at the pilot panel already, and only a genuinely cold call (process start, upload, download) makes the CPU the right answer there. Weekly cold (permutations, matrix powers, covariance + eigenvectors): **GPU**, as the design intended and by the widest margin in the table.

## 11. What this does not measure

- **Batching as a reformulation.** The 1,000 permutations could be one batched gemm instead of 1,000 calls; that would widen the GPU's margin further and is not measured here, because it would no longer be the same algorithm on both devices.
- **Pinned memory and streams.** `cupy.asarray` copies pageable memory (~2 GB/s up, 1 GB/s down). Pinned buffers plus a copy stream would hide most of the transfer and move every crossover down.
- **fp16/tensor cores.** This card has none, so none of the mixed-precision tricks are available; the verdict is a Pascal verdict.
- **Thermals.** Each workload is seconds, not minutes, on the GPU; a sustained sweep would clock down and widen every CPU margin.
- **The panel load.** `bench_screen.py` measured 57 s from SQLite for the 2.3M-row panel — many times the whole ten-lag screen, and the same on either device. It is still the argument for a cached/Parquet panel, not for a GPU.
- **A hand-written CPU path.** numpy+BLAS on 8 threads is what runs today. A numba/C++ kernel would close part of the gap on the hot path and does not exist.
- **The hot path as a service.** The measured hot path is one call in isolation. A process that already has a CUDA context up and its edges resident would pay only the transfer; the 0.1x-2.6x measured here is the honest per-call number, not a law.
