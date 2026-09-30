"""Tariff event study per tasks/tariff_event_card_2026-09-29.md. Read-only on the DB."""
import sqlite3, hashlib, numpy as np, pandas as pd

DB = 'reality_engine/data/equity_intelligence.db'
G = {
 'TARIFFED': 'WELSPUNLIV GOKEX ICIL TRIDENT KPRMILL ARVIND HIMATSEIDE AVANTIFEED APEX VAIBHAVGBL SONACOMS BHARATFORG SANSERA SUPRAJIT SUNDRMFAST CRAFTSMAN WAAREEENER'.split(),
 'PHARMA': 'SUNPHARMA DRREDDY LUPIN ZYDUSLIFE AUROPHARMA GLENMARK GRANULES TORNTPHARM ALKEM CIPLA BIOCON'.split(),
 'ITSERV': 'INFY TCS WIPRO HCLTECH TECHM LTIM COFORGE PERSISTENT MPHASIS'.split(),
 'EMS': ['DIXON']}
EV = {'E1': ('2025-04-03', -1), 'E2': ('2025-04-10', +1), 'E3': ('2025-07-31', -1), 'E4': ('2025-08-06', -1),
      'E5': ('2025-08-07', 0), 'E6': ('2025-08-27', 0), 'E7': ('2026-02-03', +1)}
PRIMARY = ['E1', 'E2', 'E3', 'E4', 'E7']
rng = np.random.default_rng(7)

c = sqlite3.connect(f'file:{DB}?mode=ro', uri=True); c.execute('pragma query_only=1')
df = pd.read_sql("select date,symbol,close,prev_close,turnover_lacs from daily_price_delivery "
                 "where date>='2021-10-01' and series='EQ'", c)
df['r'] = df.close / df.prev_close - 1
df.loc[df.r.abs() > .30, 'r'] = np.nan
R = df.pivot(index='date', columns='symbol', values='r').sort_index()
T = df.pivot(index='date', columns='symbol', values='turnover_lacs').reindex(R.index)
dates = list(R.index); grp_syms = {s for v in G.values() for s in v}
tag = {s: k for k, v in G.items() for s in v}

def run(t0, need_ctrl=True):
    """abnormal-return frame (rows -250..+19 rel. to t0 session index) for GROUP names + CONTROL count."""
    if t0 - 250 < 0 or t0 + 19 >= len(dates): return None
    pre = slice(t0 - 60, t0)
    ok = (T.iloc[pre].median() >= 50) & (T.iloc[pre].notna().mean() >= .9)
    ctrl = [s for s in R.columns[ok.values] if s not in grp_syms and R.iloc[t0 - 250:t0 + 20][s].notna().mean() > .9]
    m = R.iloc[t0 - 250:t0 + 20][ctrl].mean(axis=1).values
    est = np.arange(0, 230)  # rel -250..-21
    out = {}
    for s in list(grp_syms) + (ctrl if need_ctrl else []):
        y = R.iloc[t0 - 250:t0 + 20][s].values
        e = ~np.isnan(y[est])
        if e.sum() < 150: continue
        b, a = np.polyfit(m[est][e], y[est][e], 1)
        out[s] = y - (a + b * m)
    return pd.DataFrame(out), ctrl

def cars(ar):  # ar rows: idx 250 = day0
    z = lambda lo, hi: ar.iloc[250 + lo:250 + hi + 1].sum()
    return {'c0': z(0, 0), 'c01': z(0, 1), 'c04': z(0, 4), 'drift': z(2, 19), 'pre': z(-5, -1)}

def group_stat(ar, names, k='c01'):
    v = cars(ar[[n for n in names if n in ar]])[k]
    return v.mean(), v.notna().sum()

rows = []; sig = {}
for e, (d, sg) in EV.items():
    t0 = next(i for i, x in enumerate(dates) if x >= d)
    ar, ctrl = run(t0)
    sig[e] = (ar, ctrl, t0)
    for g, names in G.items():
        r = {'ev': e, 'date': dates[t0], 'grp': g, 'n': f"{sum(n in ar for n in names)}/{len(names)}"}
        for k in ['c0', 'c01', 'c04', 'drift', 'pre']:
            r[k] = round(group_stat(ar, names, k)[0] * 1e4)  # bps
        rows.append(r)
tab = pd.DataFrame(rows)
print('CAR in bps vs control-market model (c0=day0, c01=days0-1, drift=days2-19, pre=days-5..-1)')
print(tab.to_string(index=False))

# stock-level dispersion + permutation on E-primary for TARIFFED
print('\nPermutation (random same-size CONTROL groups), one-sided vs predicted sign, CAR[0,1]:')
for e in EV:
    ar, ctrl, _ = sig[e]; cc = cars(ar[[s for s in ctrl if s in ar]])['c01'].dropna().values
    n = sum(s in ar for s in G['TARIFFED']); real = group_stat(ar, G['TARIFFED'])[0]
    null = np.array([rng.choice(cc, n, replace=False).mean() for _ in range(5000)])
    sg = EV[e][1]
    p = (null * sg >= real * sg).mean() if sg else (np.abs(null) >= abs(real)).mean()
    print(f'{e} real={real*1e4:7.0f}bps p={p:.3f} (control cross-section sd={cc.std()*1e4:.0f}bps)')

# placebo dates
excl = set()
for e, (_, _, t0) in sig.items(): excl |= set(range(t0 - 25, t0 + 26))
cand = [t for t in range(260, len(dates) - 25) if t not in excl]
pl = rng.choice(cand, 400, replace=False)
P = {g: [] for g in G}
for t in pl:
    o = run(t, False)
    if o is None: continue
    ar = o[0]
    for g, names in G.items(): P[g].append(group_stat(ar, names)[0])
P = {g: np.array(v) for g, v in P.items()}
print(f'\nPlacebo dates used: {len(P["TARIFFED"])}; placebo CAR[0,1] sd bps: ' + ', '.join(f'{g}={v.std()*1e4:.0f}' for g, v in P.items()))

def pooled(g):
    s = np.mean([EV[e][1] * group_stat(sig[e][0], G[g])[0] for e in PRIMARY])
    sgn = np.array([EV[e][1] for e in PRIMARY])
    null = np.array([(sgn * rng.choice(P[g], 5)).mean() for _ in range(5000)])
    return s, (null >= s).mean()
print('\nPRIMARY pooled signed CAR[0,1] (positive = predicted direction):')
for g in G:
    s, p = pooled(g); print(f'  {g:9s} {s*1e4:7.0f}bps  one-sided placebo p={p:.4f}')

print('\nE5/E6 incremental (efficiency null), two-sided vs placebo |CAR[0,1]|:')
for e in ['E5', 'E6']:
    for g in ['TARIFFED', 'PHARMA', 'ITSERV']:
        v = group_stat(sig[e][0], G[g])[0]; print(f'  {e} {g:9s} {v*1e4:6.0f}bps p={(np.abs(P[g])>=abs(v)).mean():.3f}')

print('\nDrift CAR[2,19] signed by event direction (positive = continued in day-0 direction), TARIFFED/PHARMA/ITSERV:')
for g in ['TARIFFED', 'PHARMA', 'ITSERV']:
    d = [EV[e][1] * group_stat(sig[e][0], G[g], 'drift')[0] * 1e4 for e in PRIMARY]
    print(f'  {g:9s} ' + ' '.join(f'{x:7.0f}' for x in d) + f'  mean={np.mean(d):.0f}')
print('\ncard sha256:', hashlib.sha256(open('tasks/tariff_event_card_2026-09-29.md', 'rb').read()).hexdigest()[:16])
