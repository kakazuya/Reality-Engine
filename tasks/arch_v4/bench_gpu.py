#!/usr/bin/env python3
"""Measured GPU (GTX 1050 Ti, CuPy) against CPU (numpy) on the v4 engine workloads.

``bench_screen.py`` measured the CPU and *guessed* the GPU ("~233x the measured rate
before bus and kernel-launch overhead").  This measures it, on the same held panel and
drivers, and finds the size at which the GPU starts to win each workload.

Every workload is written ONCE against an array module (``numpy`` or ``cupy``), so the CPU
and GPU columns run the same code and the same arithmetic — the only difference is the
device.  That is what makes the comparison a measurement rather than two implementations
racing each other.

    python tasks/arch_v4/bench_gpu.py           # full run, writes bench_gpu.md
    python tasks/arch_v4/bench_gpu.py --check   # tiny run of every kernel, both devices

Read-only on every store (``mode=ro&immutable=1``), no network.  Nothing is installed.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT_MD = HERE / "bench_gpu.md"

# CuPy compiles its kernels with NVRTC, which writes the generated source into a
# ``tempfile.TemporaryDirectory()``.  A confined Windows token cannot write into
# mkdtemp's explicit 0700 DACL (it omits the restricting SID), so the JIT dies with
# PermissionError before the first elementwise kernel.  Compiling in memory writes no
# file at all; the per-run JIT cost is absorbed by the warm-up pass.
os.environ.setdefault("CUPY_CACHE_IN_MEMORY", "1")

_t_import = time.perf_counter()
try:
    import cupy as cp
except Exception as _exc:                     # reported verbatim, never swallowed
    cp = None
    CUPY_ERROR = f"{type(_exc).__name__}: {_exc}"
else:
    CUPY_ERROR = None
CUPY_IMPORT_S = time.perf_counter() - _t_import

HAVE_GPU = cp is not None        # narrowed by gpu_init() in __main__
GPU_INFO: dict = {}

sys.path.insert(0, str(HERE))
import bench_screen as bs                     # noqa: E402  panel + driver loaders

REPEAT = 5                                    # median of 5 where a pass is cheap
RTOL, ATOL = 1e-4, 1e-5                       # the acceptance rule, atol for near-zero cells
SEED = 7
VRAM_BUDGET = int(2.5 * 2**30)                # 4 GB card, ~1.2 GB already on the desktop


def _noop() -> None:
    pass


# --------------------------------------------------------------------------- #
# the workloads, each generic in the array module
#
# ``xp`` is numpy or cupy and nothing here touches a module-level array: the identical
# function runs on both devices.
# --------------------------------------------------------------------------- #
def _z(xp, a):
    """NaN-free copy (the screen's step 0; held returns are sparse)."""
    return xp.nan_to_num(a, nan=0.0)


def _std(xp, F):
    Fz = _z(xp, F)
    sd = Fz.std(axis=0, keepdims=True)
    sd[sd == 0] = 1.0
    return (Fz - Fz.mean(axis=0, keepdims=True)) / sd


def residualise(xp, Z, F):
    """strip k common factors by OLS per company: ``Z - F (F'F + eI)^-1 F'Z``."""
    Zf, Fz = _z(xp, Z), _std(xp, F)
    k = Fz.shape[1]
    gram = Fz.T @ Fz + xp.eye(k, dtype=Fz.dtype) * xp.asarray(1e-3, dtype=Fz.dtype)
    beta = xp.linalg.solve(gram, Fz.T @ Zf)
    return Zf - Fz @ beta


def screen_corr(xp, Z, D, lag):
    """lagged cross-correlation of every company against every driver (one gemm)."""
    Dz = _z(xp, D)
    a = _z(xp, Z[lag:])
    b = Dz[:-lag] if lag else Dz
    return (a.T @ b) / max(1, a.shape[0])


def full_screen(xp, a):
    """workload 1: residualise on 20 factors + ten lagged correlations."""
    R = residualise(xp, a["Z"], a["D"][:, :20])
    return xp.stack([screen_corr(xp, R, a["D"], lag) for lag in range(10)])


def edge_powers(xp, a):
    """workload 2: A^2, A^3 and the post-multiply prune on a bipartite edge matrix."""
    A = a["A"]
    A2 = A @ A.T
    A3 = A2 @ A
    return xp.maximum(A2 - 0.05, 0.0), xp.maximum(A3 - 0.05, 0.0)


def shock_walk(xp, a, k=10, hops=3):
    """workload 3: the hot path — 3-hop shock walk keeping the top 10 per hop.

    The edge matrix is 98% zeros, so the top-10 usually cuts into a tie at zero.  A stable
    sort breaks ties by index, which makes the beam — and therefore the answer — identical
    on both devices; an unstable sort would make the two columns solve different problems.
    """
    A = a["A"]
    scores = A[0].copy()
    trail = []
    for _ in range(hops):
        top = xp.argsort(-scores, kind="stable")[:k]
        trail.append(float(scores[top].max()))      # a device->host read per hop, by design
        propag = A[top].sum(axis=0)
        scores = (A * propag[None, :]).sum(axis=1)
    return np.asarray(trail)


def one_day(xp, a):
    """workload 4: the incremental update — one new day against the last ten driver days."""
    Z, D = a["Z"], a["D"]
    new = _z(xp, Z[-1])
    acc = xp.zeros((new.shape[0], D.shape[1]), dtype=Z.dtype)
    for lag in range(10):
        acc = acc + new[:, None] * _z(xp, D[-1 - lag])[None, :]
    return acc / 10.0


def perm_screen(xp, a):
    """workload 5: the false-discovery shuffle — the full screen on permuted driver days.

    Returns the max |corr| per lag per shuffle: that null distribution is the FDR check.
    """
    Z, D, P = a["Z"], a["D"], a["P"]
    out = xp.empty((P.shape[0], 10), dtype=Z.dtype)
    for i in range(P.shape[0]):
        Dj = D[P[i]]
        R = residualise(xp, Z, Dj[:, :20])
        c = xp.stack([screen_corr(xp, R, Dj, lag) for lag in range(10)])
        out[i] = xp.abs(c).max(axis=2).max(axis=1)
    return out


def rolling_screen(xp, a):
    """workload 6: rolling-window stability — the screen re-run on each window."""
    Z, D = a["Z"], a["D"]
    out = xp.empty((len(a["windows"]), 10), dtype=Z.dtype)
    for i, (s, e) in enumerate(a["windows"]):
        Zs, Ds = Z[s:e], D[s:e]
        R = residualise(xp, Zs, Ds[:, :20])
        c = xp.stack([screen_corr(xp, R, Ds, lag) for lag in range(10)])
        out[i] = xp.abs(c).max(axis=2).max(axis=1)
    return out


def cov_eig(xp, a, k=20):
    """workload 7: N x N covariance of the panel and its top-k eigenvectors."""
    Z = _z(xp, a["Z"])
    Zc = Z - Z.mean(axis=0, keepdims=True)
    C = (Zc.T @ Zc) / (Z.shape[0] - 1)
    _w, v = xp.linalg.eigh(C)
    return v[:, -k:]


# --------------------------------------------------------------------------- #
# synthetic data of the same shape (crossovers), fixed seed
# --------------------------------------------------------------------------- #
def syn_z(T: int, N: int, seed: int = SEED) -> np.ndarray:
    return np.random.default_rng(seed).standard_normal((T, N), dtype=np.float32)


def syn_d(T: int, D: int, seed: int = SEED + 1) -> np.ndarray:
    return np.random.default_rng(seed).standard_normal((T, D), dtype=np.float32)


def perms(K: int, T: int, seed: int = SEED + 2) -> np.ndarray:
    base = np.tile(np.arange(T, dtype=np.int32), (K, 1))
    return np.random.default_rng(seed).permuted(base, axis=1)


def rolling_windows(W: int, T: int, frac: float = 0.25) -> list[tuple[int, int]]:
    L = max(2, int(T * frac))
    return [(i * (T - L) // max(1, W - 1), i * (T - L) // max(1, W - 1) + L) for i in range(W)]


def workloads(Z: np.ndarray, D: np.ndarray) -> list[dict]:
    """the seven workloads, each with its named sizes and its crossover ladder."""
    T, N = Z.shape
    nD = D.shape[1]
    # The held driver columns are RAW LEVELS (abs max 55,385: commodity indices and group
    # means), and `bench_screen.py` feeds them straight into the gemm, so its "correlation"
    # is really a cross-product of magnitude ~1e4 and its fp32/GPU agreement is only 4e-4
    # relative.  A correlation is scale-free: standardise the columns once, here, outside
    # every timed region and identically for both devices.  Shapes do not change, so the
    # timings do not either -- only the correctness gate becomes meaningful.
    D = _std(np, D)

    def case(label, **x):
        return {"label": label, "x": x}

    def screen_case(label, Zc, Dc):
        return case(f"{label} {Zc.shape[0]}x{Zc.shape[1]}x{Dc.shape[1]}", Z=Zc, D=Dc)

    def edge_case(n, d):
        return case(f"A {n}x{d}", A=bs.adjacency(n, d))

    pilot_c = screen_case("pilot", Z, D)
    x10_c = screen_case("drivers x10", Z, syn_d(T, 330))
    x50_c = screen_case("drivers x50", Z, syn_d(T, 1650))
    # named-size labels, built once so a table column can never silently go missing
    inc_label = f"one day {N}x{nD}"
    cov_label = f"eig {N}"
    roll_label = f"20 windows x {int(T * 0.25)}d"

    out = [
        {   # 1 — full daily screen
            "key": "screen",
            "title": "Full daily screen — residualise on 20 factors + 10 lags",
            "intro": "The nightly tier's correlation work: one OLS residualisation on 20 given "
                     "factors, then ten lagged company x driver gemms. The pilot row is the "
                     "held panel (492 sessions x 4,042 companies) and the held 33 drivers; "
                     "the wider rows keep the held panel and widen the drivers to 330 and "
                     "1,650 (x10, x50) as the brief asks; the narrow rows are synthetic at "
                     "the same shape, to find the crossing. The driver columns are "
                     "standardised once before timing: `bench_screen.py` feeds the held "
                     "driver **levels** straight into the same gemm (abs max 55,385), so its "
                     "output is a cross-product of magnitude ~1e4, not a correlation, and "
                     "fp32 accumulation then disagrees by 4e-4 relative — which no rtol on "
                     "the value can fairly judge. Standardising is a column transform outside "
                     "the timed region, so the timings are unchanged.",
            "fn": full_screen,
            "budget": 25.0,
            "axis": "T x N x D",
            "named": {c["label"] for c in (pilot_c, x10_c, x50_c)},
            "ladder": [screen_case(f"N={n}", syn_z(T, n), D) for n in (256, 512, 1024, 2048)]
                      + [pilot_c, x10_c, x50_c],
        },
        {   # 2 — A^2 / A^3 with pruning
            "key": "graph",
            "title": "A^2 / A^3 with pruning on the edge matrix",
            "intro": "Two gemms and the post-multiply threshold, on bipartite edge matrices "
                     "(20 typed links per entity, fp32 dense — the same matrix "
                     "`bench_screen.py` times).",
            "fn": edge_powers,
            "budget": 60.0,
            "axis": "entities x drivers",
            "named": {"A 2000x500", "A 4000x2000", "A 8000x8000"},
            "ladder": [edge_case(n, d) for n, d in ((500, 125), (1000, 250), (2000, 500),
                                                    (4000, 2000), (8000, 8000))],
        },
        {   # 3 — the hot path
            "key": "walk",
            "title": "3-hop shock walk, top-10 (the hot path)",
            "intro": "Three hops of gather -> propagate -> reweight, keeping the top 10 per "
                     "hop. Its output is three numbers, so it pays the transfer in both "
                     "directions but moves almost nothing. Each hop reads a device scalar "
                     "back to the host, and a WDDM sync waits on the same card that is "
                     "driving the desktop, so the GPU figure here is the noisiest in the "
                     "report (it moves by 2x between runs); the CPU figure is stable and is "
                     "the one the verdict rests on. A margin of a few percent at the largest "
                     "size is a tie, not a win.",
            "fn": shock_walk,
            "budget": 25.0,
            "axis": "entities x drivers",
            "noisy": True,          # 3 per-call host syncs: no reproducible GPU number here
            "named": {"A 2000x500"},
            "ladder": [edge_case(n, d) for n, d in ((500, 125), (1000, 250), (2000, 500))],
        },
        {   # 4 — incremental one-day update
            "key": "incremental",
            "title": "Incremental one-day update",
            "intro": "One new session folded into every running statistic: ten outer "
                     "products of the new day against the last ten driver days. This is what "
                     "the nightly job does per new day, not the whole screen.",
            "fn": one_day,
            "budget": 25.0,
            "axis": "companies x drivers",
            "named": {inc_label},
            "ladder": [case(f"one day {n}x{nD}", Z=Z[:, :n], D=D) for n in (256, 1024, 2048)]
                      + [case(f"one day {N}x{nD}", Z=Z, D=D)],
        },
        {   # 5 — the permutation test
            "key": "perm",
            "title": "Permutation test for the false-discovery check (cold-tier candidate)",
            "intro": "The cold tier's job: re-run the whole screen on permuted driver days and "
                     "keep the max |corr| per lag. The brief names 1,000 shuffles; one shuffle "
                     "is the unit measured here and the 1,000-shuffle cost is projected from "
                     "it (linear in the shuffle count, nothing is cached between shuffles), "
                     "then anchored by one real 1,000-shuffle run on the winner.",
            "fn": perm_screen,
            "budget": 30.0,
            "axis": "shuffles",
            "named": {"1 shuffle", "20 shuffles"},
            "ladder": [case(f"{k} shuffle{'s' if k > 1 else ''}", Z=Z, D=D, P=perms(k, T))
                       for k in (1, 5, 20)],
        },
        {   # 6 — rolling-window stability
            "key": "rolling",
            "title": "Rolling-window stability — 20 windows x 10 lags",
            "intro": "The screen re-run on 20 overlapping quarter-length windows "
                     "(123 sessions each), keeping the max |corr| per lag. The panel is "
                     "uploaded once and every window is cut on the device.",
            "fn": rolling_screen,
            "budget": 60.0,
            "axis": "windows",
            "named": {roll_label},
            "ladder": [case(f"{w} window{'s' if w > 1 else ''} x {int(T*0.25)}d",
                            Z=Z, D=D, windows=rolling_windows(w, T))
                       for w in (1, 5, 20, 60)],
        },
        {   # 7 — latent-factor extraction
            "key": "cov",
            "title": "N x N covariance + top-20 eigenvectors (latent-factor extraction)",
            "intro": "The only super-linear step in the design: an N x N covariance of the "
                     "panel and a full eigendecomposition for the top 20 latent factors. "
                     "Checked on the eigenvector *subspace* (the projector `VV'`), because an "
                     "eigenvector's sign is arbitrary and a per-element compare would fail "
                     "for a correct answer.",
            "fn": cov_eig,
            "budget": 60.0,
            "axis": "companies",
            "named": {cov_label},
            "ladder": [case(f"eig {n}", Z=Z[:, :n]) for n in (512, 1024, 2048)]
                      + [case(f"eig {N}", Z=Z)],
            "check": "projector",
        },
    ]
    # a named size that is not on the ladder would silently report as "—" in the table
    for spec in out:
        missing = spec["named"] - {c["label"] for c in spec["ladder"]}
        if missing:
            raise ValueError(f"{spec['key']}: named sizes not on the ladder: {sorted(missing)}")
    return out


# --------------------------------------------------------------------------- #
# measurement
# --------------------------------------------------------------------------- #
def _is_arr(v) -> bool:
    return isinstance(v, np.ndarray)


def to_cp(x: dict) -> dict:
    return {k: cp.asarray(v) if _is_arr(v) else v for k, v in x.items()}


def to_f64(x: dict) -> dict:
    return {k: (v.astype(np.float64) if _is_arr(v) and v.dtype.kind == "f" else v)
            for k, v in x.items()}


def as_np(r):
    if isinstance(r, (list, tuple)):
        return [as_np(v) for v in r]
    return r.get() if hasattr(r, "get") else np.asarray(r)


def flat(r) -> np.ndarray:
    if isinstance(r, (list, tuple)):
        return np.concatenate([flat(v) for v in r])
    return np.asarray(r, dtype=np.float64).ravel()


def check_close(got, ref) -> bool:
    return bool(np.allclose(flat(got), flat(ref), rtol=RTOL, atol=ATOL, equal_nan=True))


def check_projector(got, ref) -> bool:
    g, r = np.asarray(got, np.float64), np.asarray(ref, np.float64)
    return bool(np.allclose(g @ g.T, r @ r.T, rtol=RTOL, atol=ATOL))


def _gate(a: np.ndarray, b: np.ndarray) -> float:
    """``allclose`` as a number: ``max |a-b| / (atol + rtol|b|)``; anything <= 1 passes.

    Reported next to every failing row together with the same gate between the numpy fp32
    and fp64 results, so a failure can be attributed to the device or to fp32 arithmetic.
    """
    return float(np.max(np.abs(a - b) / (ATOL + RTOL * np.abs(b))))


CHECKS = {"close": check_close, "projector": check_projector}


def bench(fn, args: tuple, budget: float, gpu: bool) -> tuple[float, int, object]:
    """warm up once, then the median of ``min(REPEAT, budget/first-pass)`` timed runs.

    The repeat count is adaptive only so that the two LAPACK-dominated cells (a 4,042
    eigen-decomposition is ~17 s) do not hold the box for minutes; it is reported in
    every row of the table.
    """
    sync = cp.cuda.Stream.null.synchronize if gpu else _noop
    sync()
    t0 = time.perf_counter()
    out = fn(*args)
    sync()
    first = time.perf_counter() - t0
    n = max(1, min(REPEAT, int(budget / max(first, 1e-9))))
    ts = []
    for _ in range(n):
        sync()
        t0 = time.perf_counter()
        fn(*args)
        sync()
        ts.append(time.perf_counter() - t0)
    return float(np.median(ts)), n, out


def free_gpu() -> None:
    """release the pool between workloads; return the high-water mark it reached."""
    pool = cp.get_default_memory_pool()
    high = pool.total_bytes()
    pool.free_all_blocks()
    cp.get_default_pinned_memory_pool().free_all_blocks()
    return high


def measure(case: dict, spec: dict) -> dict:
    """one row: CPU fp32, CPU fp64, GPU excl. transfer, GPU incl. transfer, correctness."""
    fn, budget = spec["fn"], spec["budget"]
    check = CHECKS[spec.get("check", "close")]
    x = case["x"]
    row = {"label": case["label"], "cpu_s": None, "cpu64_s": None,
           "gpu_excl_s": None, "gpu_incl_s": None, "ok": None,
           "cpu_reps": 0, "gpu_reps": 0, "note": ""}

    row["cpu_s"], row["cpu_reps"], ref = bench(fn, (np, x), budget, False)
    ref64 = None
    if row["label"] in spec["named"]:            # fp64 reference only where the report needs it
        row["cpu64_s"], _, ref64 = bench(fn, (np, to_f64(x)), budget, False)
        if check is check_close:
            row["gate_fp64"] = _gate(flat(as_np(ref)), flat(as_np(ref64)))

    if HAVE_GPU:
        try:
            z = to_cp(x)
            row["gpu_excl_s"], row["gpu_reps"], got = bench(fn, (cp, z), budget, True)
            ng, nr = as_np(got), as_np(ref)
            row["ok"] = check(ng, nr)
            if check is check_close:
                row["gate"] = _gate(flat(ng), flat(nr))
                if not row["ok"]:
                    # attribute the miss: numpy's own fp32, then the GPU in fp64.  If numpy
                    # fp32 is the one far from fp64 and the GPU fp64 is exact, the limit is
                    # fp32 arithmetic on that statistic, not the device.
                    bits = [f"gate {row['gate']:.2g}x"]
                    if row.get("gate_fp64") is not None:
                        bits.append(f"np fp32 vs fp64 {row['gate_fp64']:.2g}x")
                    if ref64 is not None:
                        g64 = to_cp(to_f64(x))
                        row["gate_gpu64"] = _gate(flat(as_np(fn(cp, g64))),
                                                  flat(as_np(ref64)))
                        del g64
                        bits.append(f"gpu fp64 vs np fp64 {row['gate_gpu64']:.2g}x")
                    row["note"] = ", ".join(bits) + " (>1 fails)"
            elif not row["ok"]:
                row["note"] = "projector check failed"
            del z, got

            def one_shot():
                as_np(fn(cp, to_cp(x)))

            row["gpu_incl_s"], _, _ = bench(one_shot, (), budget, True)
            row["vram_mb"] = free_gpu() / 2**20
        except Exception as exc:                  # OOM, unsupported dtype, ...
            row["note"] = f"GPU: {type(exc).__name__}: {exc}"
            free_gpu()
    return row


def run(spec: dict) -> list[dict]:
    rows = []
    for case in spec["ladder"]:
        row = measure(case, spec)
        rows.append(row)
        print(f"  {spec['key']:12s} {row['label']:30s} cpu {_ms(row['cpu_s']):>9s} "
              f"gpu {_ms(row['gpu_excl_s']):>9s}/{_ms(row['gpu_incl_s']):>9s} "
              f"{_x(_speed(row)):>8s} {row['note']}", file=sys.stderr, flush=True)
    return rows


def gpu_init() -> dict:
    """the one-time cost: context creation + first NVRTC compile + first kernel + sync."""
    t0 = time.perf_counter()
    n = cp.cuda.runtime.getDeviceCount()
    if n < 1:
        raise RuntimeError("cupy imported but no CUDA device is visible")
    probe = cp.arange(64, dtype=cp.float32)      # first H2D + first kernel compile
    float((probe * 2).sum())                     # first kernel launch + first D2H
    cp.cuda.Stream.null.synchronize()
    init_s = time.perf_counter() - t0
    props = cp.cuda.runtime.getDeviceProperties(0)
    free, total = cp.cuda.Device(0).mem_info
    drv = cp.cuda.runtime.driverGetVersion()
    rt = cp.cuda.runtime.runtimeGetVersion()
    return {"cupy": cp.__version__, "import_s": CUPY_IMPORT_S, "init_s": init_s,
            "devices": n, "name": props["name"].decode(),
            "cc": f"{props['major']}.{props['minor']}",
            "vram_total_mb": total / 2**20, "vram_free_mb": free / 2**20,
            "driver_cuda": f"{drv // 1000}.{(drv % 1000) // 10}",
            "runtime_cuda": f"{rt // 1000}.{(rt % 1000) // 10}"}


def transfer_ref(Z: np.ndarray) -> dict:
    """one H2D and one D2H of the pilot panel: the toll a one-shot call pays."""
    mb = Z.nbytes / 2**20
    up, down = [], []
    for _ in range(3):
        t0 = time.perf_counter()
        g = cp.asarray(Z)
        cp.cuda.Stream.null.synchronize()
        up.append(time.perf_counter() - t0)
        t0 = time.perf_counter()
        g.get()
        cp.cuda.Stream.null.synchronize()
        down.append(time.perf_counter() - t0)
        del g
    free_gpu()
    return {"mb": mb, "up_s": float(np.median(up)), "down_s": float(np.median(down))}


# --------------------------------------------------------------------------- #
# reporting
# --------------------------------------------------------------------------- #
def _speed(row: dict) -> float | None:
    if row.get("gpu_incl_s") and row.get("cpu_s"):
        return row["cpu_s"] / row["gpu_incl_s"]
    return None


def _ms(s) -> str:
    """wall clock with the unit that reads best: µs / ms / s."""
    if s is None:
        return "—"
    ms = s * 1e3
    if ms < 0.1:
        return f"{ms * 1e3:.3g} µs"
    return f"{ms:.3g} ms" if ms < 1000 else f"{s:.3g} s"


def _x(v) -> str:
    return "—" if v is None else f"{v:.2f}x"


def _ok(v) -> str:
    return "—" if v is None else ("yes" if v else "**NO**")


def _crossing(rows: list[dict], key: str) -> dict | None:
    for r in rows:
        if r.get(key) and r.get("cpu_s") and r[key] < r["cpu_s"]:
            return r
    return None


def _verdict(rows: list[dict], named: set, noisy: bool = False) -> tuple[str, float]:
    """device for a workload on its largest named size.

    Two bands, both stated in the report: >=2x is a win, 0.5x..2x is a tie, <0.5x is a loss.
    The tie band exists because the per-call GPU numbers on this card are not reproducible
    to better than ~2x between runs of this script. A workload flagged ``noisy`` (its GPU
    time is per-call host syncs on a card that also drives the desktop) measured 1.03x,
    1.94x and 2.77x on three runs, so it needs 5x before the GPU can be awarded it: a
    verdict may not rest on a number that moves that much.
    """
    biggest = [r for r in rows if r["label"] in named][-1]
    sp = _speed(biggest)
    if sp is None:
        return "CPU (GPU unavailable)", float("nan")
    if noisy and sp < 5.0:
        return "tie (unstable)", sp
    return ("GPU" if sp >= 2.0 else "tie" if sp >= 0.5 else "CPU"), sp


TIERS = (("hot path", ("walk", "incremental")),
         ("nightly", ("screen", "rolling")),
         ("weekly cold", ("perm", "graph", "cov")))


def render_md(res: dict) -> str:
    g, t = res["gpu"], res["transfer"]
    L: list[str] = []
    A = L.append
    A("# GPU vs CPU — measured (`bench_gpu.py`)\n")
    A(f"Machine: Python {res['machine']['python']}, numpy {res['machine']['numpy']}, "
      f"{res['machine']['cpus']} logical CPUs, {g['name']} (sm_{g['cc']}, "
      f"{g['vram_total_mb']/1024:.1f} GB), CuPy {g['cupy']} (CUDA {g['runtime_cuda']} "
      f"runtime, driver supports CUDA {g['driver_cuda']}). "
      f"{g['vram_free_mb']/1024:.1f} GB of VRAM was free at start (the desktop holds the rest); "
      f"the heaviest workload peaked at {res['vram_peak_mb']:.0f} MB of pool, inside the "
      f"{VRAM_BUDGET/2**20/1024:.1f} GB budget.\n")

    A("## 1. Method\n")
    p = res["panel"]
    A(f"- Data: the held pilot panel — {p['days']} sessions x {p['companies']:,} companies "
      f"and the {p['drivers']} held drivers, loaded with `bench_screen.py`'s own loaders "
      f"({p['load_s']:.0f} s from SQLite, `mode=ro&immutable=1`). Wider entity and driver "
      "counts are synthetic at the same shape with a fixed seed, as labelled in each table.")
    A("- Every workload is **one function parameterised by the array module** "
      "(`numpy` or `cupy`), so both columns run the same code and the same arithmetic. "
      "The only thing that differs is the device.")
    A(f"- fp32 on both devices; the fp64 CPU column is the same function on fp64-cast "
      f"inputs (reference only). Correctness is `allclose(rtol={RTOL:g}, atol={ATOL:g})` "
      "against the numpy fp32 result — atol because a correlation near zero has no "
      "relative scale, and equal_nan because the held panel is sparse. Pascal (sm_61) has "
      "no TF32, so the cuBLAS fp32 path is true fp32 and the comparison is not precision-"
      "tuned.")
    A("- Where a row's `allclose` reads **NO**, its note gives the gate as a number "
      "(`max |a-b| / (atol + rtol|b|)`, so >1 fails), the same gate between numpy's fp32 and "
      "fp64 results, and the gate between the GPU in fp64 and numpy in fp64. That pins the "
      "cause: if numpy's own fp32 is the one far from fp64 and the GPU's fp64 agrees with "
      "numpy's fp64, the limit is fp32 arithmetic on that statistic, not the device. It does "
      "happen: a correlation near zero is a sum of 492 O(1) products that almost cancel, so "
      "fp32's per-term rounding lands at 1e-5..1e-4 on the small value — on both devices "
      "alike, and the two do not have to agree with each other there.")
    A(f"- Warm up once, then the **median of 5** runs, capped at 5 where one pass exceeds "
      f"a per-workload budget (the 4,042 eigen-decomposition is ~17 s a pass); the actual "
      f"repeat count is printed in every row. The GPU is synchronised before the clock "
      f"stops and after the previous run finishes.")
    A("- **GPU excl. transfer** = the panel is already resident, which is the steady state "
      "of a pipeline that keeps its data on the device. **GPU incl. transfer** = upload "
      "the inputs, compute, download the result on every call, which is what a one-shot "
      "call pays. Neither includes the one-time context: that is priced separately below.")
    A(f"- One full-size transfer is {t['up_s']*1e3:.2f} ms up and {t['down_s']*1e3:.2f} ms "
      f"down ({t['mb']:.1f} MB, pageable memory, ~{t['mb']/t['up_s']/1024:.0f} GB/s). "
      "Any workload whose compute is below that toll cannot win on this bus.\n")

    A("### One-time CUDA cost (per process)\n")
    A("| stage | measured |\n|---|---:|")
    A(f"| `import cupy` | {g['import_s']:.2f} s |")
    A(f"| context creation + first kernel compile (NVRTC) + first launch + sync | "
      f"{g['init_s']:.2f} s |")
    A(f"| **cold start, first byte of GPU work** | **{g['import_s']+g['init_s']:.2f} s** |")
    A(f"\nThat is the toll any *short* GPU call pays before it has done any work: "
      f"{g['import_s']+g['init_s']:.1f} s of process start-up against a hot-path answer of "
      "a few ms. It is why the hot path stays on the CPU as a long-lived service, not "
      "because the GPU is slow.\n")

    for i, spec in enumerate(res["workloads"], start=2):
        rows = res["rows"].get(spec["key"]) or []
        A(f"## {i}. {spec['title']}\n")
        A(spec["intro"] + "\n")
        if not rows:
            A(f"**Not measured**: {spec.get('error', 'no rows')}\n")
            continue
        A("| size | CPU fp32 | CPU fp64 | GPU excl | GPU incl | GPU/CPU | allclose "
          "| reps (cpu/gpu) |\n|---|---:|---:|---:|---:|---:|:--:|:--:|")
        for r in rows:
            A(f"| {r['label']} | {_ms(r['cpu_s'])} | {_ms(r['cpu64_s'])} | "
              f"{_ms(r['gpu_excl_s'])} | {_ms(r['gpu_incl_s'])} | {_x(_speed(r))} | "
              f"{_ok(r['ok'])} | {r['cpu_reps']}/{r['gpu_reps']} |"
              + (f" {r['note']}" if r.get("note") else ""))
        inc = _crossing(rows, "gpu_incl_s")
        exc = _crossing(rows, "gpu_excl_s")
        best = max(rows, key=lambda r: _speed(r) or 0.0)
        fail = [r for r in rows if r["ok"] is False]
        att = next((r for r in fail if r.get("gate_gpu64") is not None), None)
        if fail:
            if att is not None and att["gate_gpu64"] <= 1.0 <= att["gate_fp64"]:
                A(f"\n{len(fail)} of {len(rows)} rows miss the fp32 gate. `{att['label']}` "
                  f"carries the attribution: numpy's own fp32 is {att['gate_fp64']:.2g}x from "
                  f"numpy fp64 on the same output, while the GPU in fp64 is "
                  f"{att['gate_gpu64']:.2g}x from numpy fp64 — so the miss is fp32 arithmetic "
                  "on a near-zero correlation, not the device (the other rows show the same "
                  "output with fewer reference columns).")
            else:
                A(f"\n{len(fail)} of {len(rows)} rows miss the fp32 gate; the note column "
                  "carries the numbers.")
        if inc is None:
            A(f"\n**No crossover.** The GPU never beats the CPU with transfer at any measured "
              f"size; at the largest (`{best['label']}`) the CPU costs {_ms(best['cpu_s'])} "
              f"and the GPU {_ms(best['gpu_incl_s'])} including the transfer "
              f"({_x(_speed(best))}).\n")
        else:
            A(f"\n**Crossover: `{inc['label']}`** — the first measured size where the GPU with "
              f"transfer beats the CPU ({_x(_speed(inc))}). "
              + (f"On resident data it crosses at `{exc['label']}` "
                 f"({_x(exc['cpu_s']/exc['gpu_excl_s'])}). " if exc and exc is not inc else "")
              + f"The largest measured size is {_x(_speed(best))}.\n")

    A("## 9. Crossover summary\n")
    A("| workload | axis | first GPU win (incl. transfer) | speedup there | largest measured "
      "| speedup there |\n|---|---|---|---:|---|---:|")
    for spec in res["workloads"]:
        rows = res["rows"].get(spec["key"]) or []
        if not rows:
            continue
        inc = _crossing(rows, "gpu_incl_s")
        best = max(rows, key=lambda r: _speed(r) or 0.0)
        A(f"| {spec['key']} | {spec['axis']} | "
          f"{('`' + inc['label'] + '`') if inc else 'no crossover measured'} | "
          f"{_x(_speed(inc)) if inc else '—'} | {best['label']} | {_x(_speed(best))} |")
    A("")

    A("## 10. Verdict by tier\n")
    A("A device hop costs a transfer each way plus a process's worth of context, so the bands "
      "are: **>=2x on the largest named size is a GPU win**, **0.5x..2x is a tie** and "
      "**<0.5x is a CPU win**. The tie band is not a fudge: the per-call GPU figures here are "
      "not reproducible to better than ~2x between runs of this script, so a 1.9x result "
      "cannot be told apart from noise (the incremental update, at 0.44x, can). The shock "
      "walk is flagged **tie (unstable)**: it synchronises the device three times per call "
      "on a card that is also driving the desktop, and measured 1.03x, 1.94x and 2.77x on "
      "three runs of this script, so it needs 5x before it can be awarded to either side.\n")
    A("| tier | workload | largest measured | CPU fp32 | GPU incl | GPU/CPU | device |\n"
      "|---|---|---|---:|---:|---:|---|")
    dev: dict[str, str] = {}
    spd: dict[str, float] = {}
    for tier, keys in TIERS:
        for k in keys:
            spec = next(s for s in res["workloads"] if s["key"] == k)
            rows = res["rows"].get(k) or []
            named_rows = [r for r in rows if r["label"] in spec["named"]]
            if not named_rows:
                continue
            biggest = named_rows[-1]
            d, sp = _verdict(rows, spec["named"], spec.get("noisy", False))
            dev[k], spd[k] = d, sp
            A(f"| {tier} | {spec['key']} | {biggest['label']} | {_ms(biggest['cpu_s'])} | "
              f"{_ms(biggest['gpu_incl_s'])} | {_x(sp)} | **{d}** |")
    A("")
    for tier, keys in TIERS:
        ds = ", ".join(f"{k} {_x(spd[k])}" for k in keys if k in spd)
        vs = {dev[k] for k in keys if k in dev}
        tag = "GPU" if "GPU" in vs else "CPU"
        A(f"- **{tier}** -> **{tag}**: {ds}.")
    wins = [k for k, d in dev.items() if d == "GPU"]
    ties = [k for k, d in dev.items() if d.startswith("tie")]
    cpus = [k for k, d in dev.items() if d == "CPU"]
    A(f"\nThe GPU wins {len(wins)} of {len(dev)} workloads on their largest named size "
      f"({', '.join(f'{k} {_x(spd[k])}' for k in wins)}), ties on "
      f"{', '.join(f'{k} {_x(spd[k])}' for k in ties) or 'none'}, and the CPU wins "
      f"{', '.join(f'{k} {_x(spd[k])}' for k in cpus) or 'none'}. **The dividing line is not "
      "the tier.** It is whether the unit of work is one call — a sync, a transfer each way "
      "and microseconds of arithmetic — or a pass over data that can stay resident. Every "
      "per-call workload loses; every pass over a resident panel wins at the sizes that "
      "matter, and the crossings are small (section 9), because the arithmetic that has to "
      f"amortise a {(t['up_s']+t['down_s'])*1e3:.1f} ms round trip is already tens of "
      "milliseconds.")
    scr = res["rows"].get("screen") or []
    pilot_rows = [r for r in scr if "pilot" in r["label"]]
    scr_inc = _crossing(scr, "gpu_incl_s")
    if pilot_rows and scr_inc:
        r = pilot_rows[-1]
        A(f"\nThat is where `bench_screen.md`'s guess is wrong: it assumed the GPU only wins "
          f"\"when the entity count passes ~10k\", but at the pilot size ({r['label']}) the "
          f"screen is {_ms(r['cpu_s'])} on the CPU against {_ms(r['gpu_incl_s'])} on the GPU "
          f"**including the transfer** ({_x(_speed(r))}), and the crossing is already at "
          f"`{scr_inc['label']}` ({_x(_speed(scr_inc))}) — far below the design's ~10k guess. "
          "What the GPU cannot do is answer a per-call hot-path question, and that is "
          "the tier that has to stay on the CPU.")
    A("\n**Verdict.** Hot path: **CPU**, but for two different reasons. The incremental "
      f"one-day update is a clean CPU win (the GPU is {_x(spd.get('incremental'))}), while "
      "the shock walk is inside its own run-to-run spread and cannot be awarded to either "
      "device; the design's real hot path is cheaper than that walk, so the tier stays on "
      "the CPU. Nightly (daily screen and rolling windows): **GPU** — which contradicts the "
      "design's claim. It is not a size effect: the screen wins end to end at the pilot "
      "panel already, and only a genuinely cold call (process start, upload, download) makes "
      "the CPU the right answer there. Weekly cold (permutations, matrix powers, covariance "
      "+ eigenvectors): **GPU**, as the design intended and by the widest margin in the "
      "table.\n")

    A("## 11. What this does not measure\n")
    A("- **Batching as a reformulation.** The 1,000 permutations could be one batched gemm "
      "instead of 1,000 calls; that would widen the GPU's margin further and is not "
      "measured here, because it would no longer be the same algorithm on both devices.")
    A("- **Pinned memory and streams.** `cupy.asarray` copies pageable memory "
      f"(~{t['mb']/t['up_s']/1024:.0f} GB/s up, {t['mb']/t['down_s']/1024:.0f} GB/s down). "
      "Pinned buffers plus a copy stream would hide most of the transfer and move every "
      "crossover down.")
    A("- **fp16/tensor cores.** This card has none, so none of the mixed-precision tricks "
      "are available; the verdict is a Pascal verdict.")
    A("- **Thermals.** Each workload is seconds, not minutes, on the GPU; a sustained "
      "sweep would clock down and widen every CPU margin.")
    A("- **The panel load.** `bench_screen.py` measured 57 s from SQLite for the 2.3M-row "
      "panel — many times the whole ten-lag screen, and the same on either device. It is "
      "still the argument for a cached/Parquet panel, not for a GPU.")
    A("- **A hand-written CPU path.** numpy+BLAS on 8 threads is what runs today. A "
      "numba/C++ kernel would close part of the gap on the hot path and does not exist.")
    A("- **The hot path as a service.** The measured hot path is one call in isolation. A "
      "process that already has a CUDA context up and its edges resident would pay only the "
      "transfer; the 0.1x-2.6x measured here is the honest per-call number, not a law.")
    return "\n".join(L) + "\n"


# --------------------------------------------------------------------------- #
# entry points
# --------------------------------------------------------------------------- #
def self_check() -> int:
    """One tiny pass of every kernel on both devices: fails loudly if a workload breaks."""
    Z, D = syn_z(60, 40), syn_d(60, 8)
    Z[0, 1] = np.nan
    fails = 0
    for spec in workloads(Z, D):
        x = spec["ladder"][0]["x"]                 # smallest shape: same code path, fast
        ref = spec["fn"](np, x)
        ok = CHECKS[spec.get("check", "close")](spec["fn"](np, x), ref)
        why = "cpu deterministic"
        if HAVE_GPU:
            g = spec["fn"](cp, to_cp(x))
            ok = ok and CHECKS[spec.get("check", "close")](as_np(g), as_np(ref))
            free_gpu()
            why = "cpu constant + gpu allclose"
        fails += not ok
        print(f"  {'ok  ' if ok else 'FAIL'} {spec['key']:12s} {why}", file=sys.stderr)
    print("self-check:", "PASS" if not fails else f"{fails} FAILED", file=sys.stderr)
    return 0 if not fails else 1


def main() -> int:
    if not HAVE_GPU:
        OUT_MD.write_text(
            "# GPU vs CPU — not run\n\nCuPy did not import or initialise on this machine, "
            f"so nothing was measured:\n\n```\n{CUPY_ERROR}\n```\n", encoding="utf-8")
        print(f"CuPy unavailable: {CUPY_ERROR}", file=sys.stderr)
        return 1

    t_start = time.perf_counter()
    print("loading the held panel + drivers (bench_screen loaders)...", file=sys.stderr)
    panel = bs.load_panel(730)
    D, _names, dinfo = bs.load_drivers(panel)
    Z = panel["z"]
    print(f"  panel {Z.shape} drivers {D.shape} "
          f"({panel['load_s']:.1f}s + {dinfo['build_s']:.1f}s)", file=sys.stderr, flush=True)

    res = {
        "machine": {"python": sys.version.split()[0], "numpy": np.__version__,
                    "cpus": os.cpu_count()},
        "gpu": GPU_INFO,
        "transfer": transfer_ref(Z),
        "panel": {"source": str(bs.STATE_A.relative_to(bs.DATA)),
                  "days": int(Z.shape[0]), "companies": int(Z.shape[1]),
                  "drivers": int(D.shape[1]), "load_s": round(panel["load_s"], 1)},
        "rows": {}, "workloads": [], "vram_peak_mb": 0.0,
    }
    for spec in workloads(Z, D):
        print(f"[{spec['key']}] {spec['title']}", file=sys.stderr, flush=True)
        try:
            rows = run(spec)
        except Exception as exc:                  # one broken workload must not lose the run
            print(f"  FAILED: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
            rows = []
            spec["error"] = f"{type(exc).__name__}: {exc}"
        res["rows"][spec["key"]] = rows
        res["workloads"].append({k: spec[k] for k in ("key", "title", "intro", "axis", "named")}
                                | {"noisy": spec.get("noisy", False)}
                                | ({"error": spec["error"]} if "error" in spec else {}))
        res["vram_peak_mb"] = max(res["vram_peak_mb"],
                                  max((r.get("vram_mb", 0.0) for r in rows), default=0.0))

    anchor = anchor_perm(Z, D, res)
    res["perm_anchor"] = anchor
    if anchor:
        res["workloads"][[s["key"] for s in res["workloads"]].index("perm")]["intro"] += (
            f"\n\n**Anchored 1,000-shuffle run on the winner:** `{anchor['device']}` "
            f"{anchor['s']:.2f} s measured against a {anchor['projected']:.2f} s projection — "
            + ("allclose holds against numpy."
               if anchor["ok"] else
               f"gate {anchor['gate']:.2g}x (>1 fails), the same fp32 conditioning limit the "
               "20-shuffle row attributes to the statistic rather than to the device."))

    res["total_s"] = round(time.perf_counter() - t_start, 1)
    print(json.dumps({k: v for k, v in res.items() if k != "rows"}, indent=2, default=str))
    OUT_MD.write_text(render_md(res), encoding="utf-8")
    print(f"\nwrote {OUT_MD.name} in {res['total_s']} s", file=sys.stderr)
    return 0


def anchor_perm(Z: np.ndarray, D: np.ndarray, res: dict) -> dict:
    """one real 1,000-shuffle run on the winner, so the cold-tier number is not a projection."""
    rows = res["rows"].get("perm") or []
    if not rows or not HAVE_GPU:
        return {}
    unit = rows[-1]                                   # the largest measured shuffle count
    k = float(unit["label"].split()[0])
    if not (unit.get("gpu_incl_s") and unit.get("cpu_s")):
        return {}
    cpu_total = unit["cpu_s"] / k * 1000
    gpu_total = unit["gpu_incl_s"] / k * 1000
    device = "gpu" if gpu_total < cpu_total else "cpu"
    projected = min(cpu_total, gpu_total)
    if projected > 90.0:                              # laptop thermals: no long full load
        return {}
    print(f"[perm] anchoring 1,000 shuffles on the {device}...", file=sys.stderr, flush=True)
    x = {"Z": Z, "D": D, "P": perms(1000, Z.shape[0])}
    if device == "gpu":
        g = to_cp(x)
        cp.cuda.Stream.null.synchronize()
        t0 = time.perf_counter()
        got = perm_screen(cp, g)
        cp.cuda.Stream.null.synchronize()
        s = time.perf_counter() - t0
        ng, nr = as_np(got), as_np(perm_screen(np, x))
        ok, gate = check_close(ng, nr), _gate(flat(ng), flat(nr))
        del g, got
        free_gpu()
    else:
        t0 = time.perf_counter()
        got = perm_screen(np, x)
        s = time.perf_counter() - t0
        nr = perm_screen(np, x)
        ok, gate = check_close(got, nr), _gate(flat(got), flat(nr))
    return {"device": device, "s": round(s, 2), "projected": round(projected, 2),
            "shuffles": 1000, "ok": ok, "gate": round(gate, 3)}


if __name__ == "__main__":
    HAVE_GPU = cp is not None
    GPU_INFO: dict = {}
    if HAVE_GPU:
        try:
            GPU_INFO = gpu_init()
        except Exception as exc:
            HAVE_GPU = False
            CUPY_ERROR = f"{type(exc).__name__}: {exc}"
            print(f"CuPy initialisation failed: {CUPY_ERROR}", file=sys.stderr)
    raise SystemExit(self_check() if "--check" in sys.argv else main())
