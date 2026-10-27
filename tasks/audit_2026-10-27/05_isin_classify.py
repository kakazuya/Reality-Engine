"""A5 - classify ISIN-change candidates: Luhn validity + corporate action near the change."""
import os
import sys
from collections import defaultdict
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from reality_engine.db.readonly import connect_ro  # noqa: E402

DATA = Path(os.environ["REALITY_DATA_ROOT"])
snap = duckdb.connect(str(DATA / "snapshots" / "truth_2026-10-19.duckdb"), read_only=True)
eq = connect_ro(DATA / "equity_intelligence.db", timeout_s=60)


def luhn_isin(isin: str) -> bool:
    if not isin or len(isin) != 12 or not isin[:2].isalpha():
        return False
    digits = []
    for ch in isin:
        if ch.isdigit():
            digits.append(int(ch))
        elif ch.isalpha():
            digits.append(ord(ch) - 55)
        else:
            return False
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


print("== corp_action cols (snapshot)")
print([c[0] for c in snap.execute("DESCRIBE corp_action").fetchall()])
print(snap.execute("SELECT kind, COUNT(*) FROM corp_action GROUP BY 1 ORDER BY 2 DESC LIMIT 10").fetchall())

rows = snap.execute("""
    SELECT entity_id, isin, MIN(date) d0, MAX(date) d1, COUNT(*) n, string_agg(DISTINCT symbol, ',') syms
    FROM px_daily GROUP BY 1,2
""").fetchall()
ent = defaultdict(list)
for r in rows:
    ent[r[0]].append(r)

cases = []
for k, v in ent.items():
    v = sorted(v, key=lambda r: r[2])
    if len(v) == 2 and v[0][3] < v[1][2]:
        cases.append({"entity": k, "old": v[0][1], "new": v[1][1], "switch": v[1][2],
                      "last_old": v[0][3], "syms": v[0][5], "new_syms": v[1][5]})
print(f"\ncases={len(cases)}")

by_switch = defaultdict(int)
for c in cases:
    by_switch[c["switch"].isoformat()] += 1
print("switch dates with >=5 cases:", sorted([(d, n) for d, n in by_switch.items() if n >= 5], key=lambda x: -x[1])[:12])

print("\n== Luhn validity")
print("old valid:", sum(luhn_isin(c["old"]) for c in cases), "/", len(cases))
print("new valid:", sum(luhn_isin(c["new"]) for c in cases), "/", len(cases))

print("\n== corporate action within 90d of switch")
out = []
for c in cases:
    syms = {s.strip() for s in (c["syms"] + "," + c["new_syms"]).split(",") if s.strip()}
    acts = []
    for s in syms:
        for r in eq.execute(
            "SELECT action_type, ex_date, subject, face_value FROM corporate_actions "
            "WHERE symbol=? AND ex_date BETWEEN date(?, '-90 day') AND date(?, '+90 day')",
            (s, c["switch"].isoformat(), c["switch"].isoformat()),
        ):
            acts.append(r)
    c["acts"] = acts
    c["luhn_ok"] = luhn_isin(c["old"]) and luhn_isin(c["new"])
    c["mass_2021"] = c["switch"].isoformat() == "2021-10-27"
    out.append(c)

from collections import Counter
print(Counter("split" if any(a[0] == "SPLIT" for a in c["acts"]) else
              "merger" if any(a[0] == "MERGER" for a in c["acts"]) else
              "bonus" if any(a[0] == "BONUS" for a in c["acts"]) else
              "none" for c in out))

print("\n== candidates with a split/merger/bonus nearby (real-change shortlist)")
for c in out:
    if not c["acts"]:
        continue
    print(f"  {c['syms']}->{c['new_syms']} old={c['old']} new={c['new']} switch={c['switch']} "
          f"luhn={c['luhn_ok']} acts={c['acts'][:3]}")

print("\n== 2021-10-27 mass switch: all same pattern?")
m = [c for c in out if c["mass_2021"]]
print("count", len(m), "old prefix == new prefix:", sum(c["old"][:9] == c["new"][:9] for c in m))
for c in m[:5]:
    print("   ", c["old"], "->", c["new"], c["syms"])

snap.close()
eq.close()
