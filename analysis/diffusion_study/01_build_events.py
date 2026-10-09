"""Build the event table: BSE announcements (exact DissemDT, IST) -> (isin, t0 session, timing bucket, family).
Read-only. Output: out/events.parquet (one row per announcement) and out/units.parquet (one row per isin x t0)."""
import sqlite3
import numpy as np
import pandas as pd
from common import *

p = pd.read_parquet(PRICES, columns=["date", "symbol", "isin", "series"])
p = p[p.series == "EQ"]
cal = np.array(sorted(p["date"].astype(str).unique()))
sym2isin = p.groupby("symbol")["isin"].agg(lambda s: s.mode().iat[0])
print("sessions", len(cal), cal[0], cal[-1], "| EQ symbols", len(sym2isin))

c = sqlite3.connect(f"file:{FEED}?mode=ro", uri=True)
a = pd.read_sql("select NEWSID, symbol, CATEGORYNAME cat, SUBCATNAME sub, DissemDT ts from ann "
                "where DissemDT is not null and symbol is not null", c)
print("announcements", len(a))
a["isin"] = a.symbol.map(sym2isin)
print("mapped to a price-table ISIN: %.1f%%" % (100 * a["isin"].notna().mean()))
a = a[a["isin"].notna()].copy()
a["date"] = a.ts.str[:10]
a["minute"] = a.ts.str[11:13].astype(int) * 60 + a.ts.str[14:16].astype(int)
i = np.searchsorted(cal, a.date.values, side="left")          # first session on/after the date
i_ok = i < len(cal)
trading = np.zeros(len(a), bool)
trading[i_ok] = cal[i[i_ok]] == a.date.values[i_ok]
bucket = np.where(~trading, "non_trading", np.where(a.minute < OPEN_MIN, "pre_open",
                  np.where(a.minute <= CLOSE_MIN, "intraday", "after_close")))
t0 = np.where(bucket == "after_close", i + 1, i)               # after-close news first hits the NEXT session
a["bucket"], a["t0"] = bucket, t0
a = a[a.t0 < len(cal)].copy()
a["family"] = a["sub"].fillna(a["cat"]).str.strip()
a["is_material"] = a.family.isin(MATERIAL)
print(a.bucket.value_counts(normalize=True).round(3).to_dict())
a[["NEWSID", "symbol", "isin", "ts", "bucket", "t0", "cat", "family", "is_material"]].to_parquet(OUT / "events.parquet")

# unit = (isin, t0): everything that hits the same session for the same stock; isolation flag from material units
g = a.groupby(["isin", "t0"])
u = g.agg(symbol=("symbol", "first"), n_ann=("NEWSID", "size"), n_mat=("is_material", "sum"),
          first_ts=("ts", "min"), bucket=("bucket", "first"),
          families=("family", lambda s: "|".join(sorted(set(s))))).reset_index()
mat = u[u.n_mat > 0][["isin", "t0"]].sort_values(["isin", "t0"])
iso = np.ones(len(u), bool)
mkey = {k: v.t0.values for k, v in mat.groupby("isin")}
for k, idx in u.groupby("isin").indices.items():
    mt = mkey.get(k)
    if mt is None: continue
    tt = u.t0.values[idx]
    # count material units in [t-PRE, t+POST], excluding the unit itself if it is material
    lo = np.searchsorted(mt, tt - ISO_PRE, "left"); hi = np.searchsorted(mt, tt + ISO_POST, "right")
    iso[idx] = (hi - lo - (u.n_mat.values[idx] > 0)) == 0
u["isolated"] = iso
u.to_parquet(OUT / "units.parquet")
print("units", len(u), "| isolated %.1f%%" % (100 * u.isolated.mean()))
print(u.groupby("bucket").size().to_dict())
(OUT / "calendar.txt").write_text("\n".join(cal))
