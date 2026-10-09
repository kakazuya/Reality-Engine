"""Negative-reaction puzzle, test 1 (closeout 2026-10-05 §3): do matched NON-announcers with the same prior-week run-up
also fall on days 0..+1? If yes, the negative mean CAR(0,1) on results is short-term reversal / benchmark artifact, not news.

Design: for every Financial Results event-day (stock j, session t0) take x = excess return vs the same-day liquidity-bucket mean
(beta=1, so no estimation window is involved) and the run-up RU = sum x over tau -5..-1. Controls are stock-days on the SAME date t0
and SAME liquidity bucket with no results-cluster filing in [t-5, t+5] (control A) or no material event-day in [t-2, t+10] (control B),
matched to the event's RU by nearest neighbour (k=5, caliper). Outcome: sum x over tau 0,1 (and raw returns as a check).
SEs cluster by date. Read-only; reads only out/units.parquet, calendar.txt and the price parquet."""
import numpy as np
import pandas as pd
from common import *

K, CAL_BP = 20, 50.0
RESULTS = {"Financial Results", "Outcome of Board Meeting", "Investor Presentation", "Press Release / Media Release",
           "Earnings Call Transcript", "Analyst / Investor Meet", "Board Meeting", "Integrated Filing (Financial)"}

p = pd.read_parquet(PRICES, columns=["date", "isin", "series", "close", "prev_close", "turnover_lacs"])
p = p[p.series == "EQ"].drop_duplicates(["date", "isin"], keep="last")
cal = (OUT / "calendar.txt").read_text().split("\n"); p["date"] = p["date"].astype(str)
isins = sorted(p["isin"].unique()); col = {k: i for i, k in enumerate(isins)}
T, S = len(cal), len(isins)
ti = pd.Index(cal).get_indexer(p["date"]); sj = p["isin"].map(col).values
def mat(v):
    M = np.full((T, S), np.nan); M[ti, sj] = v; return M
R = mat((p.close / p.prev_close - 1).values); R[np.abs(R) > 0.30] = np.nan
TURN = mat(p.turnover_lacs.values)
liq = pd.DataFrame(TURN).rolling(60, min_periods=40).median().shift(1).values
BINS = np.array([0, 10, 50, 250, 1000, 5000, np.inf]); NB = len(BINS) - 1
lbin = np.where(np.isnan(liq), -1, np.digitize(liq, BINS) - 1)
X = np.full((T, S), np.nan)                      # excess vs same-day liquidity-bucket mean
for b in range(NB):
    mk = (lbin == b) & ~np.isnan(R); c = mk.sum(1)
    m = np.where(c >= 15, np.where(mk, R, 0).sum(1) / np.maximum(c, 1), np.nan)
    X = np.where(mk, R - m[:, None], X)

# per-stock-day flags from the unit table
u = pd.read_parquet(OUT / "units.parquet"); u = u[u["isin"].isin(col)].copy(); u["j"] = u["isin"].map(col)
fam = u.families.str.split("|")
u["is_res"] = fam.map(lambda f: any(x in RESULTS for x in f))
u["is_fr"] = u.families.str.contains("Financial Results", regex=False)
def near(flag_t0_by_j, lo, hi):
    """bool matrix [T,S]: any flagged unit in [t+lo, t+hi]."""
    F = np.zeros((T + 1, S));
    F[u[flag_t0_by_j].t0.values, u[flag_t0_by_j].j.values] = 1
    P = np.zeros((T + 2, S)); np.cumsum(F[:T], axis=0, out=P[1:T + 1]); P[T + 1:] = P[T]
    t = np.arange(T); a = np.clip(t + lo, 0, T); b = np.clip(t + hi + 1, 0, T)
    return (P[b] - P[a]) > 0
res_near = near(u.is_res.values, -5, 5)                       # control A exclusion: any results-cluster filing +-5
mat_flag = (u.n_mat > 0).values
mat_near = near(mat_flag, -2, 10)                              # control B exclusion: any material filing in [t-2, t+10]

RU = np.full((T, S), np.nan); OUT01 = np.full((T, S), np.nan); RAW01 = np.full((T, S), np.nan); RAWRU = np.full((T, S), np.nan)
for t in range(5, T - 1):
    s = X[t - 5:t].sum(0); o = X[t:t + 2].sum(0)
    ok = np.isfinite(X[t - 5:t]).all(0) & np.isfinite(X[t:t + 2]).all(0)
    RU[t] = np.where(ok, s, np.nan); OUT01[t] = np.where(ok, o, np.nan)
    RAWRU[t] = R[t - 5:t].sum(0); RAW01[t] = R[t:t + 2].sum(0)
good = np.isfinite(RU) & np.isfinite(OUT01) & np.isfinite(RAWRU) & np.isfinite(RAW01) & (liq >= LIQ_MIN_TURNOVER_LACS)
good[:EST_LO] = False; good[T - 21:] = False                  # same sample span as the event panel

def match(ev, ctrl_mask, label):
    """Nearest-RU controls pooled over dates within (liquidity bucket, calendar year). x is already net of the same-day bucket
    mean, so date effects are removed without needing same-date controls (those are scarce in results season)."""
    yr = np.array([int(c[:4]) for c in cal])
    cm = good & ctrl_mask
    tt, jj = np.where(cm); ccb = lbin[tt - 1, jj]; ccy = yr[tt]
    rows = []; n_ev = len(ev)
    for (b, y), g in ev.assign(y=yr[ev.t0.values]).groupby(["b", "y"]):
        sel = (ccb == b) & (ccy == y)
        if sel.sum() < 4 * K: continue
        ct, cj = tt[sel], jj[sel]; cr = RU[ct, cj]; o = np.argsort(cr); ct, cj, cr = ct[o], cj[o], cr[o]
        ru = RU[g.t0.values, g.j.values]; pos = np.searchsorted(cr, ru)
        # take the K nearest from a window of K each side
        off = np.arange(-K, K)[None, :]; ix = np.clip(pos[:, None] + off, 0, len(cr) - 1)
        dist = np.abs(cr[ix] - ru[:, None]); order = np.argsort(dist, axis=1)[:, :K]
        ixk = np.take_along_axis(ix, order, 1); dk = np.take_along_axis(dist, order, 1)
        ok = dk.max(1) <= CAL_BP / 1e4
        for r in np.where(ok)[0]:
            c_t, c_j = ct[ixk[r]], cj[ixk[r]]
            t, j = g.t0.values[r], g.j.values[r]
            rows.append((t, j, RU[t, j], OUT01[t, j], RAW01[t, j], RU[c_t, c_j].mean(), OUT01[c_t, c_j].mean(),
                         RAW01[c_t, c_j].mean(), RAWRU[t, j], RAWRU[c_t, c_j].mean()))
    d = pd.DataFrame(rows, columns=["t0", "j", "ru_e", "x_e", "raw_e", "ru_c", "x_c", "raw_c", "rru_e", "rru_c"])
    d["date"] = np.array(cal)[d.t0.values]; d["year"] = d.date.str[:4].astype(int)
    print(f"[{label}] matched {len(d)} of {n_ev} events | mean run-up matched {d.ru_e.mean()*1e4:.1f} bp "
          f"vs all events {RU[ev.t0.values, ev.j.values].mean()*1e4:.1f} bp")
    return d

def clustered(v, cl):
    """Mean and date-clustered SE of v."""
    v = np.asarray(v); df = pd.DataFrame({"v": v - v.mean(), "c": cl}); g = df.groupby("c").v.sum()
    return v.mean(), np.sqrt((g ** 2).sum()) / len(v)

def report(d, name):
    if d.empty: print(name, "no matches"); return
    out = []
    for lab, sub in [("ALL", d)] + [(str(y), g) for y, g in d.groupby("year")]:
        me, se = clustered(sub.x_e * 1e4, sub.date); mc, sc = clustered(sub.x_c * 1e4, sub.date)
        md, sd = clustered((sub.x_e - sub.x_c) * 1e4, sub.date)
        out.append((lab, len(sub), sub.ru_e.mean() * 1e4, sub.ru_c.mean() * 1e4, me, mc, md, sd, md / sd,
                    (sub.raw_e * 1e4).mean(), (sub.raw_c * 1e4).mean(), (sub.x_e > 0).mean(), (sub.x_c > 0).mean()))
    o = pd.DataFrame(out, columns=["slice", "n", "runup_ev", "runup_ctl", "car01_ev", "car01_ctl", "diff", "se", "t",
                                   "raw01_ev", "raw01_ctl", "pos_ev", "pos_ctl"])
    print(f"\n=== {name} ==="); print(o.round(2).to_string(index=False))

# ---- events: Financial Results event-days, liquidity >= floor ----
ev = u[u.is_fr].copy(); ev["b"] = lbin[ev.t0.values - 1, ev.j.values]
ev = ev[good[ev.t0.values, ev.j.values] & (ev.b >= 0)]
ev["full"] = ev.bucket != "intraday"
print("Financial Results event-days with data and liquidity:", len(ev), "| isolated:", int(ev.isolated.sum()))
for lab, e in [("isolated, all timing", ev[ev.isolated]), ("isolated, full (outside session)", ev[ev.isolated & ev.full]),
               ("isolated, intraday", ev[ev.isolated & ~ev.full]), ("all FR events (not isolated)", ev)]:
    for cl, cm in [("A: no results-cluster in +-5", ~res_near), ("B: no material in [-2,+10]", ~mat_near)]:
        d = match(e, cm, cl); report(d, f"{lab} | control {cl}")
        if lab == "isolated, all timing" and cl.startswith("A"): d.to_parquet(OUT / "neg_reaction_matched_A.parquet")
        if lab.startswith("all FR") and cl.startswith("A"): d.to_parquet(OUT / "neg_reaction_matched_A_allFR.parquet")

# ---- unconditional reversal check among non-announcers: does x(0,1) fall with prior run-up? ----
ctl = good & ~res_near
ru, o = RU[ctl], OUT01[ctl]
q = pd.qcut(ru, 10, labels=False, duplicates="drop")
print("\nNon-announcer (control A) x(0,1) by decile of prior-5-day run-up, bp:")
print(pd.DataFrame({"runup_bp": ru * 1e4, "next2_bp": o * 1e4, "q": q}).groupby("q").mean().round(1).T.to_string())
