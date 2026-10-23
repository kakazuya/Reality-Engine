"""H01 x H02 combination rules, fixed before Stage 2 is run.

The deal must be in the declared session window around the H01 decision and
must be known before the combined entry.  Entry is the later of the two
t+1 opens, never the earlier one.  No weight, window or horizon search.
"""
from __future__ import annotations

import math

import numpy as np

CONFIRM_WINDOW = (-20, 5)
H01_HORIZON = 180
C1_HORIZON = 180
C6_HORIZON = 60


def window_mask(h01_signal, deal_signal, window=CONFIRM_WINDOW):
    """True when the deal session is inside [h01-20, h01+5]."""
    low, high = window
    return (np.asarray(deal_signal) >= np.asarray(h01_signal) + low) & \
           (np.asarray(deal_signal) <= np.asarray(h01_signal) + high)


def combined_entry(h01_entry, deal_entry):
    """Later of the two t+1 opens; a post-H01 deal delays the entry."""
    return np.maximum(np.asarray(h01_entry), np.asarray(deal_entry))


def zscore(values):
    values = np.asarray(values, dtype=float)
    if len(values) == 0:
        return values
    sd = np.nanstd(values, ddof=1)
    if not np.isfinite(sd) or sd == 0:
        return np.zeros_like(values)
    return (values - np.nanmean(values)) / sd


def tercile_labels(scores):
    """Deterministic equal-count bottom/middle/top terciles (0/1/2)."""
    scores = np.asarray(scores, dtype=float)
    n = len(scores)
    labels = np.full(n, -1, dtype=int)
    if n == 0:
        return labels
    order = np.argsort(scores, kind="mergesort")
    labels[order] = np.minimum(2, (np.arange(n) * 3) // n)
    return labels


def _cluster_mean_var(values, entries, days):
    values = np.asarray(values, dtype=float)
    n = len(values)
    if n < 2:
        return float(np.mean(values)) if n else None, None, 0
    mu = float(np.mean(values))
    months = np.asarray(days)[np.asarray(entries)].astype("datetime64[M]").astype(int)
    _, inverse = np.unique(months, return_inverse=True)
    g = int(inverse.max()) + 1
    if g < 2:
        return mu, None, g
    sums = np.bincount(inverse, weights=values - mu)
    var = g / (g - 1) * float(np.sum(sums * sums)) / (n * n)
    return mu, var, g


def cluster_diff(values_a, entries_a, values_b, entries_b, days, student_p=None):
    """Difference in means with month-clustered sandwich variance."""
    a = np.asarray(values_a, dtype=float)
    b = np.asarray(values_b, dtype=float)
    mu_a, var_a, g_a = _cluster_mean_var(a, entries_a, days)
    mu_b, var_b, g_b = _cluster_mean_var(b, entries_b, days)
    out = {"n_a": int(len(a)), "n_b": int(len(b)),
           "mean_a": mu_a, "mean_b": mu_b,
           "diff": (mu_a - mu_b) if mu_a is not None and mu_b is not None else None,
           "t_stat": None, "p": 1.0,
           "clusters_a": g_a, "clusters_b": g_b}
    if out["diff"] is None or var_a is None or var_b is None:
        return out
    var = var_a + var_b
    if var <= 0:
        return out
    t = out["diff"] / math.sqrt(var)
    out["t_stat"] = t
    if student_p is not None:
        out["p"] = student_p(t, max(1, min(g_a, g_b) - 1))
    return out
