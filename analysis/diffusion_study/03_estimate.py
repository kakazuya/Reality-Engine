"""Stratum-level estimation for the price-side information-diffusion study (numpy/pandas only).

Per stratum (announcement family x timing x sample) it reports
  car01      mean abnormal return over the reaction window (0,+1), bp
  drift_sc   sign-conditioned drift  s*CAR(2,20), s=sign(CAR(0,1)): >0 = under-reaction, <0 = over-reaction/reversal
  lv01       abnormal log turnover, mean of tau=0,1 (net of the pre-event level)
  vr01       excess variance ratio, mean(AR^2/sigma^2) - 1 over tau=0,1
  dp01       delivery-% shift, tau=0,1 (pp, net of the pre-event level)
with firm x date two-way clustered t-stats (Cameron, Gelbach & Miller 2011), the Boehmer-Musumeci-Poulsen (1991)
standardised z for event-induced variance, placebo-calibrated drift, Benjamini-Hochberg FDR across all primary tests
(Benjamini & Hochberg 1995), and cluster-bootstrap (by firm) estimates of the attention half-life
(LV(tau)=B*exp(-lam*tau)) and the drift saturation curve S(e)=A*(1-exp(-k*e)), t50=ln2/k."""
import math
import numpy as np
import pandas as pd
from common import *

MIN_N, N_BOOT = 500, 300
rng = np.random.default_rng(11)
meta = pd.read_parquet(OUT / "panel_meta.parquet"); Z = np.load(OUT / "panel_arrays.npz")
pmeta = pd.read_parquet(OUT / "placebo_meta.parquet"); PZ = np.load(OUT / "placebo_arrays.npz")
ti = lambda t: t - TAU[0]                       # column index of event time t


def nsum(X, lo, hi, tol):
    seg = X[:, ti(lo):ti(hi) + 1]; n = np.isfinite(seg).sum(1)
    return np.where(n >= (hi - lo + 1) - tol, np.nansum(seg, 1), np.nan)


def prep(meta, Z):
    AR, LV, DP = Z["AR"].astype(np.float64), Z["LV"].astype(np.float64), Z["DP"].astype(np.float64)
    sg = meta.sigma.values
    d = {"car01": nsum(AR, 0, 1, 0), "car220": nsum(AR, 2, 20, 3)}
    pre = lambda X: np.nanmean(X[:, ti(-5):ti(-1) + 1], 1)
    d["lv01"] = np.nanmean(LV[:, ti(0):ti(1) + 1], 1) - pre(LV)
    d["vr01"] = np.nanmean((AR[:, ti(0):ti(1) + 1] / sg[:, None]) ** 2, 1) - 1
    d["dp01"] = np.nanmean(DP[:, ti(0):ti(1) + 1], 1) - pre(DP)
    d["z_car01"] = d["car01"] / (sg * math.sqrt(2))
    return d, AR, LV


D, AR, LV = prep(meta, Z)
PD, PAR, PLV = prep(pmeta, PZ)

MATS = set(MATERIAL)
fam = meta.families.str.split("|")
meta["mat_set"] = fam.map(lambda f: frozenset(x for x in f if x in MATS))
meta["fset"] = fam.map(frozenset)
meta["timing"] = np.where(meta.bucket == "intraday", "intraday", "full")      # 'full' = news arrived outside the session
meta["liquid"] = meta.bucket_liq >= 2
fcode = pd.factorize(meta.symbol)[0]; dcode = meta.t0.values


def cl_mean(x, f, d):
    """mean and two-way (firm x date) cluster-robust SE of a sample mean; units are unique firm-date cells."""
    ok = np.isfinite(x); x, f, d = x[ok], f[ok], d[ok]; n = len(x)
    if n < 30: return np.nan, np.nan, n
    mu = x.mean(); e = x - mu
    vf = (np.bincount(f, e) ** 2).sum(); vd = (np.bincount(d, e) ** 2).sum(); v = (vf + vd - (e ** 2).sum()) / n ** 2
    if v <= 0: v = max(vf, vd) / n ** 2
    return mu, math.sqrt(v), n


def pval(t): return math.erfc(abs(t) / math.sqrt(2)) if np.isfinite(t) else np.nan


def bmp(z):
    z = z[np.isfinite(z)]
    return (z.mean() * math.sqrt(len(z)) / z.std(ddof=1)) if len(z) > 30 else np.nan


TX = np.arange(0, 21).astype(float); GR = np.linspace(0.02, 3.0, 150)


def fit_exp(y, x, kind):
    best = (np.inf, np.nan, np.nan)
    for g in GR:
        b = np.exp(-g * x) if kind == "decay" else 1 - np.exp(-g * x)
        a = (b * y).sum() / (b * b).sum(); sse = ((y - a * b) ** 2).sum()
        if sse < best[0]: best = (sse, a, g)
    return best[1], best[2]


def path_boot(sel, kind, sgn=None):
    """firm-cluster bootstrap of an exponential fit to a mean path (the path is linear in unit data)."""
    f = fcode[sel]; uf, inv = np.unique(f, return_inverse=True); K = len(uf)
    if kind == "decay":      # excess log turnover tau=0..20 net of its pre-event level
        L = LV[sel]; P = L[:, ti(0):ti(20) + 1] - np.nanmean(L[:, ti(-5):ti(-1) + 1], 1)[:, None]; x = TX
    else:                    # sign-conditioned CAR(2,tau), tau=2..20, elapsed e = tau-1
        c = np.cumsum(np.nan_to_num(AR[sel][:, ti(2):ti(20) + 1]), 1)
        P = sgn[:, None] * (c - c[sgn != 0].mean(0)); x = np.arange(1, 20).astype(float)
        P[sgn == 0] = np.nan
    ok = np.isfinite(P).all(1); P, inv2 = P[ok], inv[ok]
    S = np.zeros((K, P.shape[1])); np.add.at(S, inv2, P); C = np.bincount(inv2, minlength=K).astype(float)
    est = fit_exp(S.sum(0) / C.sum(), x, kind); bs = []
    for _ in range(N_BOOT):
        w = np.bincount(rng.integers(0, K, K), minlength=K); den = (w * C).sum()
        if den == 0: continue
        bs.append(fit_exp((w[:, None] * S).sum(0) / den, x, kind))
    bs = np.array(bs)
    return est[0], est[1], np.percentile(bs[:, 0], [2.5, 97.5]), np.percentile(bs[:, 1], [2.5, 97.5])


# placebo reference: mean CAR(2,20) on random no-news windows (benchmark-bias diagnostic, liquidity-bucket weighted)
pl_c220 = {b: np.nanmean(PD["car220"][(pmeta.bucket_liq == b).values]) for b in range(6)}


def placebo_car220(buckets):
    w = np.bincount(buckets, minlength=6) / len(buckets)
    return sum(w[b] * pl_c220[b] for b in range(6))


def spread_drift(sel):
    """Mean-shift-proof drift: x_i = s_i * (CAR(2,20)_i - stratum mean), s_i = sign(CAR(0,1)_i - stratum median).
    mean(x) = (E[CAR2-20 | reaction above median] - E[... | below median]) / 2: >0 under-reaction, <0 reversal."""
    c1, c2, sg = D["car01"][sel], D["car220"][sel], meta.sigma.values[sel]
    s_ = np.sign(c1 - np.nanmedian(c1)); x = s_ * (c2 - np.nanmean(c2))
    x[s_ == 0] = np.nan
    return x, s_, x / (sg * math.sqrt(19))


RESULTS = {"Financial Results", "Outcome of Board Meeting", "Integrated Filing (Financial)", "Earnings Call Transcript",
           "Analyst / Investor Meet", "Investor Presentation", "Press Release / Media Release", "Board Meeting"}
# administrative filings expected to carry no price information: negative controls for the whole testing machinery
CONTROLS = {"Closure of Trading Window", "Newspaper Publication", "Shareholding", "AGM", "Postal Ballot", "EGM",
            "Certificate under Reg. 74 (5) of SEBI (DP) Regulations, 2018", "Reg. 13(3) - Statement of Investor Complaints",
            "Reg.24(A)-Annual Secretarial Compliance", "Business Responsibility and Sustainability Reporting (BRSR)",
            "Reg. 40 (10) - PCS Certificate for Transfer / Transmission / Transposition",
            "Reg. 39 (3) - Details of Loss of Certificate / Duplicate Certificate", "Book Closure", "Record Date",
            "Declaration of NAV", "Reg. 34 (1) Annual Report", "General"}
allu = pd.read_parquet(OUT / "units.parquet")
allu["mat_set"] = allu.families.str.split("|").map(lambda f: frozenset(x for x in f if x in MATS))
iso_code = {k: i for i, k in enumerate(pd.unique(pd.concat([allu["isin"], meta["isin"]])))}
allu["ic"] = allu["isin"].map(iso_code); meta["ic"] = meta["isin"].map(iso_code)
_iso_cache = {}


def isolated_for(cluster):
    """True where NO material event-day outside `cluster` sits in [t0-2, t0+10] for the same stock."""
    key = frozenset(cluster)
    if key not in _iso_cache:
        oth = allu[(allu.n_mat > 0) & allu.mat_set.map(lambda s_: not s_.issubset(key))]
        keys = np.sort(oth.ic.values.astype(np.int64) * 10000 + oth.t0.values)
        mk = meta.ic.values.astype(np.int64) * 10000 + meta.t0.values
        c = np.searchsorted(keys, mk + ISO_POST, "right") - np.searchsorted(keys, mk - ISO_PRE, "left")
        _iso_cache[key] = c == 0
    return _iso_cache[key]


def mask_for(family, iso, liq):
    if family in MATS:
        cl = RESULTS if family in RESULTS else {family}
        m = meta.mat_set.map(lambda s_: family in s_ and s_.issubset(cl)).values
        if iso: m = m & isolated_for(cl)
    else:
        m = ((meta.n_mat == 0) & meta.fset.map(lambda s_: family in s_)).values
        if iso: m = m & isolated_for(set())
    if liq: m = m & meta.liquid.values
    return m


rows = []
cand = pd.Series([x for s in meta.fset for x in s]).value_counts()
fams = [f for f, n in cand.items() if n >= MIN_N * 2]
print("families considered:", len(fams))
for family in fams:
    for iso, liq in [(True, True), (False, True), (True, False)]:
        base = mask_for(family, iso, liq)
        for tm in ("full", "intraday"):
            sel = base & (meta.timing == tm).values
            if sel.sum() < MIN_N: continue
            r = {"family": family, "timing": tm, "isolated": iso, "liquid_only": liq, "n": int(sel.sum()),
                 "n_firms": int(pd.Series(fcode[sel]).nunique()), "control": family in CONTROLS}
            f, d = fcode[sel], dcode[sel]
            xd, s_loc, zd = spread_drift(sel)
            for k, sc in (("car01", 1e4), ("car220", 1e4), ("drift_sc", 1e4), ("lv01", 1), ("vr01", 1), ("dp01", 1)):
                v = xd if k == "drift_sc" else D[k][sel]
                mu, se, n = cl_mean(v, f, d)
                r[k] = mu * sc; r[k + "_se"] = se * sc; r[k + "_t"] = mu / se if se > 0 else np.nan; r[k + "_p"] = pval(r[k + "_t"])
            r["car01_bmp"], r["drift_bmp"] = bmp(D["z_car01"][sel]), bmp(zd)
            r["placebo_car220"] = placebo_car220(meta.bucket_liq.values[sel]) * 1e4
            r["frac_continue"] = float((xd[np.isfinite(xd)] > 0).mean())
            if iso and liq and sel.sum() >= 1500:
                B, lam, Bc, lc = path_boot(sel, "decay")
                r.update(att_B=B, att_lam=lam, att_halflife=math.log(2) / lam, att_hl_lo=math.log(2) / lc[1], att_hl_hi=math.log(2) / lc[0])
                A, k, Ac, kc = path_boot(sel, "sat", s_loc)
                r.update(sat_A=A * 1e4, sat_k=k, sat_t50=math.log(2) / k, sat_A_lo=Ac[0] * 1e4, sat_A_hi=Ac[1] * 1e4,
                         sat_t50_lo=math.log(2) / kc[1], sat_t50_hi=math.log(2) / kc[0])
            rows.append(r)
res = pd.DataFrame(rows)


def bh(p):
    p = np.asarray(p, float); out = np.full(len(p), np.nan); ok = np.isfinite(p); q = p[ok]
    o = np.argsort(q); r = q[o] * len(q) / (np.arange(len(q)) + 1); r = np.minimum.accumulate(r[::-1])[::-1]
    t = np.empty(len(q)); t[o] = np.minimum(r, 1); out[ok] = t; return out


primary = (res.isolated & res.liquid_only).values
for k in ("car01", "drift_sc", "lv01", "vr01", "dp01"):
    res[k + "_q"] = np.nan
    res.loc[primary, k + "_q"] = bh(res.loc[primary, k + ("_p")].values)
res.to_csv(OUT / "results_strata.csv", index=False)
for k in ("car01", "drift_sc", "lv01", "vr01", "dp01"):
    c_ = res[primary & res.control.values]
    print("NEGATIVE CONTROLS  %-9s share with q<0.05: %.2f  (n strata %d)" % (k, (c_[k + "_q"] < 0.05).mean(), len(c_)))
print("strata:", len(res), "| primary (isolated, liquid):", int(primary.sum()))
pd.set_option("display.width", 230, "display.max_columns", 30, "display.max_rows", 200)
show = res[primary].sort_values("n", ascending=False)
cols = ["family", "timing", "control", "n", "car01", "car01_q", "drift_sc", "drift_sc_t", "drift_sc_q", "lv01", "lv01_q", "vr01", "vr01_q"]
print(show[cols].round(3).head(45).to_string(index=False))
