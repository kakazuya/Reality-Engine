"""Vectorised market-model event study over every event-day (read-only on inputs).

Benchmark model per event: y_t = b*m_t + e_t (no intercept) on sessions [t0-250, t0-31] via prefix sums (exact OLS, no loops
over events). m_t = equal-weighted mean return of stocks passing a lagged liquidity screen (the event stock
is one of ~1000 constituents; its own weight is negligible).
Outputs per event-day, tau=-5..+20: AR (abnormal return), LV (log turnover minus its estimation-window mean),
DP (delivery% minus its estimation-window mean). A placebo panel (random no-news sessions, same stocks) is
produced with the identical code path so every real statistic can be calibrated against it."""
import numpy as np
import pandas as pd
from common import *

rng = np.random.default_rng(20261003)
p = pd.read_parquet(PRICES, columns=["date", "isin", "series", "close", "prev_close", "turnover_lacs", "delivery_pct"])
p = p[p.series == "EQ"].drop_duplicates(["date", "isin"], keep="last")
cal = (OUT / "calendar.txt").read_text().split("\n")
p["date"] = p["date"].astype(str)
isins = sorted(p["isin"].unique()); col = {k: i for i, k in enumerate(isins)}
T, S = len(cal), len(isins)
ti = pd.Index(cal).get_indexer(p["date"]); sj = p["isin"].map(col).values
def mat(v, dtype=np.float64):
    M = np.full((T, S), np.nan, dtype); M[ti, sj] = v; return M
R = mat((p.close / p.prev_close - 1).values); R[np.abs(R) > 0.30] = np.nan      # data-error / action guard
TURN = mat(p.turnover_lacs.values); DLV = mat(p.delivery_pct.values)
LT = np.where(TURN > 0, np.log(TURN), np.nan)
liq = pd.DataFrame(TURN).rolling(60, min_periods=40).median().shift(1).values   # information known before day t
BINS = np.array([0, 10, 50, 250, 1000, 5000, np.inf])         # lagged trailing-60d median turnover, INR lakh
NB = len(BINS) - 1
lbin = np.where(np.isnan(liq), -1, np.digitize(liq, BINS) - 1)     # bucket of each stock-day, known before the day
def bucket_market(b):
    """Equal-weighted return of all stocks in liquidity bucket b on each day (liquidity-matched benchmark)."""
    mk = (lbin == b) & ~np.isnan(R); c = mk.sum(1)
    return np.where(c >= 15, np.where(mk, R, 0).sum(1) / np.maximum(c, 1), np.nan)
print("sessions with a valid bucket market:", [int(np.isfinite(bucket_market(b)).sum()) for b in range(NB)], "of", T)

def pref(X):
    P = np.zeros((T + 1, S)); np.cumsum(X, axis=0, out=P[1:]); return P
tau = np.array(TAU)

def compute(j, t0):
    ok = (t0 - EST_LO >= 0) & (t0 + tau[-1] < T) & (t0 >= 1)
    j, t0 = j[ok], t0[ok]
    bk = lbin[t0 - 1, j]; ok = bk >= 0; j, t0, bk = j[ok], t0[ok], bk[ok]
    N = len(j); out_meta = [None] * N
    beta = np.full(N, np.nan); sig = np.full(N, np.nan); n = np.zeros(N)
    AR = np.full((N, len(tau)), np.nan); idx = t0[:, None] + tau[None, :]
    LV = np.full((N, len(tau)), np.nan); DP = np.full((N, len(tau)), np.nan); nl = np.zeros(N)
    for b in range(NB):
        e = np.where(bk == b)[0]
        if not len(e): continue
        m = bucket_market(b); mz = np.nan_to_num(m)
        v = (~np.isnan(R) & np.isfinite(m)[:, None]); y = np.where(v, R, 0.0); mm = np.where(v, mz[:, None], 0.0)
        Pv, Py, Pyy, Pm, Pmm, Pmy = pref(v.astype(float)), pref(y), pref(y * y), pref(mm), pref(mm * mm), pref(mm * y)
        ja, aa, bb = j[e], t0[e] - EST_LO, t0[e] - EST_HI
        d = lambda P: P[bb + 1, ja] - P[aa, ja]
        nn, Sy, Syy, Sm, Smm, Smy = d(Pv), d(Py), d(Pyy), d(Pm), d(Pmm), d(Pmy)
        with np.errstate(all="ignore"):
            # beta-only (through the origin): a fitted intercept extrapolated out of sample builds in a spurious
            # drift for stocks selected on past performance (Brown & Warner 1985: simple benchmarks do well)
            be = Smy / Smm; al = np.zeros_like(be)
            sse = Syy - 2 * be * Smy + be ** 2 * Smm
            sg = np.sqrt(np.maximum(sse, 0) / (nn - 1))
        beta[e], sig[e], n[e] = be, sg, nn
        AR[e] = R[idx[e], ja[:, None]] - al[:, None] - be[:, None] * m[idx[e]]
        del Pv, Py, Pyy, Pm, Pmm, Pmy

        # volume / delivery relative to the same-day mean of the same liquidity bucket, then to the stock's own
        # estimation-window baseline: removes market-wide volume seasonality (month-end, expiry, results season)
        mkb = (lbin == b)
        for X, tgt in ((LT, "LV"), (DLV, "DP")):
            okx = mkb & ~np.isnan(X); cx = okx.sum(1)
            mx = np.where(cx >= 15, np.where(okx, X, 0).sum(1) / np.maximum(cx, 1), np.nan)
            Xc = X - mx[:, None]; vx = ~np.isnan(Xc)
            Pn, Ps = pref(vx.astype(float)), pref(np.where(vx, Xc, 0.0))
            cnt_ = Pn[bb + 1, ja] - Pn[aa, ja]
            with np.errstate(all="ignore"):
                base = (Ps[bb + 1, ja] - Ps[aa, ja]) / cnt_
            out_ = Xc[idx[e], ja[:, None]] - base[:, None]
            if tgt == "LV": LV[e] = out_; nl[e] = cnt_
            else: DP[e] = out_
            del Pn, Ps
    keep = (n >= MIN_EST_OBS) & (sig > 0) & (nl >= 100)
    meta = pd.DataFrame({"j": j, "t0": t0, "bucket_liq": bk, "beta": beta, "sigma": sig, "n_est": n,
                         "liq": liq[t0 - 1, j]})[keep]
    return meta, AR[keep].astype(np.float32), LV[keep].astype(np.float32), DP[keep].astype(np.float32)

u = pd.read_parquet(OUT / "units.parquet"); u = u[u["isin"].isin(col)].reset_index(drop=True)
u["j"] = u["isin"].map(col)
meta, AR, LV, DP = compute(u.j.values, u.t0.values)
meta = meta.merge(u[["j", "t0", "isin", "symbol", "n_ann", "n_mat", "first_ts", "bucket", "families", "isolated"]],
                  on=["j", "t0"], how="left")
meta["date"] = np.array(cal)[meta.t0.values]
print("real event-days with a valid model:", len(meta), "of", len(u))
meta.to_parquet(OUT / "panel_meta.parquet"); np.savez_compressed(OUT / "panel_arrays.npz", AR=AR, LV=LV, DP=DP)

# placebo: one random session per real event-day for the same stock, with NO material event-day in [t-2, t+10]
# (the same isolation rule as the isolated real events), so the pseudo-date is independent of news.
real = {k: np.sort(g.t0.values) for k, g in u[u.n_mat > 0].groupby("j")}
pj = meta.j.values.copy(); pt = np.full(len(meta), -1)
lo_, hi_ = EST_LO, T - tau[-1] - 1
todo = np.arange(len(meta))
for _ in range(40):
    cand = rng.integers(lo_, hi_, size=len(todo))
    okm = np.ones(len(todo), bool)
    for jj in np.unique(pj[todo]):
        sel = np.where(pj[todo] == jj)[0]; rt = real.get(jj)
        if rt is None: continue
        okm[sel] = np.searchsorted(rt, cand[sel] + ISO_POST, "right") == np.searchsorted(rt, cand[sel] - ISO_PRE, "left")
    pt[todo[okm]] = cand[okm]; todo = todo[~okm]
    if not len(todo): break
print("placebo unplaced after rejection sampling:", len(todo))
sel = pt >= 0
pm, pAR, pLV, pDP = compute(pj[sel], pt[sel])
pm["date"] = np.array(cal)[pm.t0.values]; pm = pm.merge(meta[["j"]].drop_duplicates().assign(_x=1), on="j", how="left")
pm["symbol"] = pm.j.map(dict(zip(meta.j, meta.symbol)))
pm.to_parquet(OUT / "placebo_meta.parquet"); np.savez_compressed(OUT / "placebo_arrays.npz", AR=pAR, LV=pLV, DP=pDP)
print("placebo event-days:", len(pm))
