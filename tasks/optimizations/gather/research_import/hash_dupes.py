"""sha256 duplicate finder (dry run). Usage: hash_dupes.py ROOT [ROOT...] OUT.csv"""
import collections
import csv
import hashlib
import os
import sys

LP = "\\\\?\\"  # Windows long-path prefix
roots = [LP + os.path.abspath(a) for a in sys.argv[1:-1]]
out = sys.argv[-1]
errs, rows = [], []
for r in roots:
    for d, _, fs in os.walk(r, onerror=errs.append):
        for f in fs:
            if f.startswith("_") and d == r:
                continue  # logs/listings at a root
            p = os.path.join(d, f)
            h = hashlib.sha256()
            try:
                with open(p, "rb") as fh:
                    for b in iter(lambda: fh.read(1 << 20), b""):
                        h.update(b)
            except OSError as e:
                errs.append(e)
                continue
            rows.append((h.hexdigest(), os.path.getsize(p), p[len(LP):]))

g = collections.defaultdict(list)
for h, s, p in rows:
    g[h].append((s, p))
dup = {h: v for h, v in g.items() if len(v) > 1}
with open(out, "w", newline="", encoding="utf-8") as fh:
    w = csv.writer(fh)
    w.writerow(["sha256", "size", "keep", "path"])
    for h, v in sorted(dup.items(), key=lambda x: -x[1][0][0]):
        v.sort(key=lambda x: (len(x[1]), x[1]))  # keep the shortest path
        for i, (s, p) in enumerate(v):
            w.writerow([h, s, "KEEP" if i == 0 else "dup", p])
extra = sum(s for v in dup.values() for s, _ in v[1:])
print("errors", len(errs), [str(e)[:120] for e in errs[:3]])
print(f"files {len(rows)} unique {len(g)} dup_groups {len(dup)} "
      f"extra_copies {sum(len(v) - 1 for v in dup.values())} reclaim_GB {extra / 1e9:.2f}")
