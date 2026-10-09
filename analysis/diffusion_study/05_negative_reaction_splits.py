"""Negative-reaction puzzle, test 3 (closeout 2026-10-05 §3): is the announcer-vs-matched-control gap in CAR(0,1) related to
run-up size, results season vs off-season, or time of day? Reads out/neg_reaction_matched_A_allFR.parquet (04's matched pairs,
all Financial Results event-days, control A), out/units.parquet, out/events.parquet. Diff = x_event - mean x of 20 matched controls (bp).
SEs cluster by date. Read-only."""
import numpy as np, pandas as pd
import statsmodels.api as sm
from common import *

cal = (OUT / "calendar.txt").read_text().split("\n")
d = pd.read_parquet(OUT / "neg_reaction_matched_A_allFR.parquet")
u = pd.read_parquet(OUT / "units.parquet")[["isin", "t0", "symbol", "isolated", "bucket", "families"]]
sym = u.drop_duplicates("symbol")  # j -> symbol via price columns not stored; rebuild j map the same way 04 does
p = pd.read_parquet(PRICES, columns=["isin", "series"]); isins = sorted(p[p.series == "EQ"]["isin"].unique())
d["isin"] = np.array(isins)[d.j.values]
e = pd.read_parquet(OUT / "events.parquet", columns=["isin", "t0", "ts", "family"])
fr = e[e.family == "Financial Results"].groupby(["isin", "t0"]).ts.min().rename("fr_ts").reset_index()
d = d.merge(u[["isin", "t0", "isolated", "bucket"]], on=["isin", "t0"], how="left").merge(fr, on=["isin", "t0"], how="left")
d["diff"] = (d.x_e - d.x_c) * 1e4; d["xe"] = d.x_e * 1e4; d["xc"] = d.x_c * 1e4; d["ru"] = d.ru_e * 1e4
d["minute"] = d.fr_ts.str[11:13].astype(float) * 60 + d.fr_ts.str[14:16].astype(float)
d["month"] = d.date.str[5:7].astype(int)
# date density of FR event-days across all stocks (market-wide results intensity that day)
dens = d.groupby("t0").size().rename("dens"); d = d.merge(dens, on="t0")

def row(lab, g):
    if len(g) < 30: return (lab, len(g)) + (np.nan,) * 6
    v = g["diff"].values; c = g.date.values
    gs = pd.Series(v - v.mean()).groupby(c).sum(); se = np.sqrt((gs ** 2).sum()) / len(v)
    return (lab, len(g), g.ru.mean(), g.xe.mean(), g.xc.mean(), v.mean(), se, v.mean() / se)
def tab(title, groups):
    t = pd.DataFrame([row(l, g) for l, g in groups], columns=["slice", "n", "runup_bp", "car01_ev", "car01_ctl", "diff", "se", "t"])
    print(f"\n=== {title} ===\n" + t.round(1).to_string(index=False))

print("pairs:", len(d), "| isolated:", int(d.isolated.sum()), "| with FR timestamp:", int(d.minute.notna().sum()))
d["ru_q"] = pd.qcut(d.ru, 5, labels=False)
for samp, dd in [("all FR", d), ("isolated FR", d[d.isolated == True])]:
    q = pd.qcut(dd.ru, 5, labels=False)
    tab(f"{samp}: by run-up quintile (events' own run-up)", [(f"Q{k+1}", dd[q == k]) for k in range(5)])
    # slope of announcer-minus-control diff on run-up, date-clustered
    X = sm.add_constant(dd.ru.values / 100.0); m = sm.OLS(dd["diff"].values, X).fit(cov_type="cluster", cov_kwds={"groups": pd.factorize(dd.date)[0]})
    print(f"{samp}: diff = {m.params[0]:.1f} + {m.params[1]:.1f} * (run-up/100bp)   (se slope {m.bse[1]:.1f}, t {m.tvalues[1]:.1f})")
    # results season: by calendar month, and by market-wide FR density that day
    tab(f"{samp}: by calendar month", [(f"{m:02d}", g) for m, g in dd.groupby("month")])
    q = pd.qcut(dd.dens, 3, labels=["low-density days", "mid", "peak-density days"], duplicates="drop")
    tab(f"{samp}: by market-wide FR density on the day (terciles)", [(str(k), dd[q == k]) for k in q.cat.categories])
    h = dd.minute
    bins = [("pre-open (<09:15)", h < 555), ("09:15-11:00", (h >= 555) & (h < 660)), ("11:00-13:00", (h >= 660) & (h < 780)),
            ("13:00-15:30", (h >= 780) & (h <= 930)), ("15:30-18:00", (h > 930) & (h < 1080)), ("18:00-21:00", (h >= 1080) & (h < 1260)),
            ("21:00+", h >= 1260)]
    tab(f"{samp}: by FR dissemination time (IST)", [(l, dd[m]) for l, m in bins])

# joint check: does the time-of-day gradient survive within results-density terciles, and vice versa? (all FR)
d["tod"] = pd.cut(d.minute, [0, 780, 930, 1080, 1260, 1e4], labels=["<13:00", "13:00-15:30", "15:30-18:00", "18:00-21:00", "21:00+"], right=False)
d["dq"] = pd.qcut(d.dens, 3, labels=["low", "mid", "peak"], duplicates="drop")
print("\n=== all FR: diff (bp) by time of day x results-density tercile (n in brackets) ===")
pv = d.pivot_table(index="tod", columns="dq", values="diff", aggfunc=["mean", "size"], observed=True)
print(pd.concat({"diff": pv["mean"].round(1), "n": pv["size"]}, axis=1).to_string())
X = pd.get_dummies(d.tod, drop_first=True).astype(float); X["dens_z"] = (d.dens - d.dens.mean()) / d.dens.std(); X["ru_100"] = d.ru / 100
m = sm.OLS(d["diff"].values, sm.add_constant(X)).fit(cov_type="cluster", cov_kwds={"groups": pd.factorize(d.date)[0]})
print("\nregression of diff on time-of-day dummies (base <13:00), density z, run-up/100bp; date-clustered:")
print(pd.DataFrame({"coef_bp": m.params, "t": m.tvalues}).round(1).to_string())
