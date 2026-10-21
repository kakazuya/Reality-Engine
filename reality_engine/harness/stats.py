"""Full-grid FDR, month-cluster inference and reproducible date placebos.

Like diffusion_study/02_event_engine.py, real and placebo events must go
through the same evaluator. No package installation or live data access.
"""
import math
import random
from collections import defaultdict
from statistics import mean, median, stdev


def bh_fdr(pvalues):
    """BH over EVERY registered variant; failed/empty variants count as p=1."""
    ps = [float(p) if p is not None and math.isfinite(p) else 1.0 for p in pvalues]
    if any(not 0 <= p <= 1 for p in ps):
        raise ValueError("p outside [0,1]")
    order = sorted(range(len(ps)), key=lambda i: ps[i])
    out = [1.0] * len(ps)
    running = 1.0
    for rank in range(len(ps), 0, -1):
        i = order[rank - 1]
        running = min(running, ps[i] * len(ps) / rank)
        out[i] = running
    return out


def _beta_fraction(a, b, x):
    """Continued fraction for incomplete beta (Lentz recurrence)."""
    tiny, eps = 1e-300, 3e-14
    qab, qap, qam = a + b, a + 1, a - 1
    c = 1.0
    d = 1 - qab * x / qap
    d = 1 / (d if abs(d) > tiny else tiny)
    h = d
    for m in range(1, 301):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1 + aa * d
        c = 1 + aa / c
        d = 1 / (d if abs(d) > tiny else tiny)
        c = c if abs(c) > tiny else tiny
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1 + aa * d
        c = 1 + aa / c
        d = 1 / (d if abs(d) > tiny else tiny)
        c = c if abs(c) > tiny else tiny
        delta = d * c
        h *= delta
        if abs(delta - 1) < eps:
            return h
    raise ArithmeticError("Incomplete beta did not converge")


def _ibeta(a, b, x):
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    front = math.exp(math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
                     + a * math.log(x) + b * math.log1p(-x))
    if x < (a + 1) / (a + b + 2):
        return front * _beta_fraction(a, b, x) / a
    return 1 - front * _beta_fraction(b, a, 1 - x) / b


def student_p(t, df):
    """Two-sided Student t probability; no scipy dependency."""
    if df < 1:
        return 1.0
    if math.isinf(t):
        return 0.0
    return min(1.0, max(0.0, _ibeta(df / 2, 0.5, df / (df + t * t))))


def summarize(events):
    """Event-weighted mean; sandwich SE clustered by entry calendar month.

    Clustering handles within-month co-movement, but not every dependence
    created by 60-session overlapping horizons. Placebo calibration and book
    drawdowns remain necessary; the reported t is never called iid proof.
    Required fields: net_excess, entry (date), regime ('up'/'down').
    """
    rows = [e for e in events if math.isfinite(e["net_excess"])]
    xs = [e["net_excess"] for e in rows]
    result = {"n_events": len(xs), "mean_net_excess": mean(xs) if xs else None,
              "median_net_excess": median(xs) if xs else None,
              "t_stat": None, "p": 1.0, "n_month_clusters": 0}
    if len(xs) >= 2:
        mu = mean(xs)
        clusters = defaultdict(float)
        for e in rows:
            clusters[str(e["entry"])[:7]] += e["net_excess"] - mu
        g, n = len(clusters), len(xs)
        result["n_month_clusters"] = g
        if g > 1:
            se = math.sqrt(g / (g - 1) * sum(v * v for v in clusters.values())) / n
            # Degenerate fixtures/cohorts must never produce evidence of an edge.
            if se > 0:
                result["t_stat"] = mu / se
                result["p"] = student_p(mu / se, g - 1)
    year_values, regimes = defaultdict(list), defaultdict(list)
    for e in rows:
        year_values[str(e["entry"])[:4]].append(e["net_excess"])
        regimes[e["regime"]].append(e["net_excess"])
    result["per_year"] = {
        str(y): {"n": len(year_values[str(y)]),
                 "mean": mean(year_values[str(y)]) if year_values[str(y)] else None}
        for y in range(2021, 2026)}
    result["per_year_signs"] = {
        y: (None if v["mean"] is None else "+" if v["mean"] > 0 else "-" if v["mean"] < 0 else "0")
        for y, v in result["per_year"].items()}
    result["regimes"] = {k: {"n": len(regimes[k]),
                               "mean": mean(regimes[k]) if regimes[k] else None}
                         for k in ("up", "down")}
    return result


def shuffled_dates(events, rng):
    """Permute trigger timestamps across events within their calendar month.

    Preserves the empirical filing-season pattern, timestamps and cohort
    sizes. The evaluator must recompute all as-of features after shuffling;
    do not attach original surprises to earlier placebo dates.
    """
    groups = defaultdict(list)
    out = [dict(e) for e in events]
    for i, e in enumerate(events):
        groups[str(e["trigger"])[:7]].append(i)
    for indices in groups.values():
        stamps = [events[i]["trigger"] for i in indices]
        rng.shuffle(stamps)
        for i, stamp in zip(indices, stamps):
            out[i]["trigger"] = stamp
    return out


def placebos(events, evaluator, observed, draws=499, seed=20261020):
    """Full-grid null distribution, plus max-absolute-t reality check.

    evaluator(events) must return all variants in the same order, including
    failures. Each output includes mean_net_excess and t_stat.
    Never select a horizon/sign after seeing a placebo draw.
    """
    rng = random.Random(seed)
    means = [[] for _ in observed]
    max_t = []
    counts = [[] for _ in observed]
    for _ in range(draws):
        stats = evaluator(shuffled_dates(events, rng))
        if len(stats) != len(observed):
            raise ValueError("Placebo omitted a registered variant")
        ts = []
        for i, row in enumerate(stats):
            means[i].append(row.get("mean_net_excess"))
            counts[i].append(row.get("n_events", 0))
            if row.get("t_stat") is not None:
                ts.append(abs(row["t_stat"]))
        max_t.append(max(ts, default=0.0))
    result = []
    for i, row in enumerate(observed):
        valid = [x for x in means[i] if x is not None and math.isfinite(x)]
        mu = row.get("mean_net_excess")
        p = ((1 + sum(abs(x) >= abs(mu) for x in valid)) / (1 + len(valid))
             if mu is not None and valid else 1.0)
        t = row.get("t_stat")
        reality_p = ((1 + sum(x >= abs(t) for x in max_t)) / (draws + 1)
                     if t is not None else 1.0)
        result.append({"placebo_p": p, "reality_check_p": reality_p,
                       "draws": draws, "valid_draws": len(valid),
                       "placebo_means": means[i], "placebo_n_events": counts[i],
                       "placebo_mean": mean(valid) if valid else None,
                       "placebo_sd": stdev(valid) if len(valid) > 1 else None})
    return {"variants": result, "max_abs_t_distribution": max_t, "seed": seed}
