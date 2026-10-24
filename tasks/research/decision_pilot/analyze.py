"""Post-run analysis for REPORT.md: spend breakdown, audit-by-category, bootstrap CIs, B label cuts."""
import json
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(r"C:\Users\warri\Downloads\IDM-worktrees\20261024T172743Z-a480564b\tasks\research\decision_pilot")
R = json.load(open(ROOT / "results.json"))
B = json.load(open(ROOT / "data/b_events.json", encoding="utf-8"))
A1 = json.load(open(ROOT / "data/a1_items.json", encoding="utf-8"))
S = json.load(open(ROOT / "spend.json"))


def boot_ci(x, fn, n=2000, seed=1):
    rng = np.random.default_rng(seed)
    vals = [fn(rng.choice(x, len(x), replace=True)) for _ in range(n)]
    return np.percentile(vals, [2.5, 97.5]).round(4).tolist()


def main():
    print("SPEND")
    by = defaultdict(float)
    for e in S["entries"]:
        by[(e["arm"], e["model"])] += e["usd"]
    for k, v in sorted(by.items()):
        print(" ", k, round(v, 6))
    print("  total", round(S["usd"], 6), "entries", len(S["entries"]))

    print("\nA1 AUDIT BY CATEGORY")
    aud = R["A1"]["label_audit"]["verdicts"]
    for c in R["A1"]["dataset"]["categories"][:-1]:
        rows = [a for a in aud if a["label"] == c]
        if rows:
            print(f"  {c}: n={len(rows)} wrong={sum(a['label_ok'] == 0 for a in rows)}")

    print("\nA1 PER-CLASS ACCURACY")
    for m, r in R["A1"]["models"].items():
        print(" ", m, r["per_class_accuracy"])

    print("\nA1 TOP CONFUSIONS")
    for m, r in R["A1"]["models"].items():
        pairs = []
        for true, row in r["confusion"].items():
            for pred, n in row.items():
                if pred != true and n:
                    pairs.append((n, true, pred))
        print(" ", m, sorted(pairs, reverse=True)[:6])

    print("\nB BY EVENT TYPE")
    for et in ("insider_buy", "bulk_deal_buy"):
        rows = [x for x in B if x["state"]["event_type"] == et]
        print(f"  {et}: n={len(rows)} base={np.mean([x['label'] for x in rows]):.3f} "
              f"stock_ret_med={np.median([x['stock_ret'] for x in rows]):.3f} "
              f"vs_nifty_med={np.median([x['stock_ret'] - x['nifty_ret'] for x in rows]):.3f}")

    print("\nB BOOTSTRAP CI (1000 resamples)")
    # rebuild p from cached responses
    ys, ps = {}, {}
    for m in R["B"]["models"]:
        slug = m.replace("/", "__")
        p, y = [], []
        for ev in B:
            f = ROOT / "cache/responses" / slug / "B" / (ev["id"] + ".json")
            r = json.load(open(f))
            p.append(r["answers"]["beat"]["noul"])
            y.append(ev["label"])
        ps[m], ys[m] = np.array(p), np.array(y)
        brier = np.mean((ps[m] - ys[m]) ** 2)
        base = np.mean((ys[m].mean() - ys[m]) ** 2)
        def auc(p, y):
            pos, neg = p[y == 1], p[y == 0]
            return (np.sum(pos[:, None] > neg[None, :]) + 0.5 * np.sum(pos[:, None] == neg[None, :])) / (len(pos) * len(neg))
        print(f"  {m}: brier={brier:.4f} base={base:.4f} diff={brier-base:+.4f} "
              f"auc={auc(ps[m], ys[m]):.3f}")
        idx = np.arange(len(y))
        rng = np.random.default_rng(2)
        diffs, aucs = [], []
        for _ in range(1000):
            ii = rng.choice(idx, len(idx), replace=True)
            yy = ys[m][ii]
            if yy.min() == yy.max():
                continue
            diffs.append(np.mean((ps[m][ii] - yy) ** 2) - np.mean((yy.mean() - yy) ** 2))
            aucs.append(auc(ps[m][ii], yy))
        print(f"    brier_diff 95% CI {np.percentile(diffs, [2.5, 97.5]).round(4).tolist()}")
        print(f"    auc 95% CI {np.percentile(aucs, [2.5, 97.5]).round(3).tolist()}")

    print("\nA1 BOOTSTRAP ACCURACY CI")
    for m, r in R["A1"]["models"].items():
        # recompute predictions from cached responses
        slug = m.replace("/", "__")
        y, pred = [], []
        for it in A1:
            f = ROOT / "cache/responses" / slug / "A1" / (it["id"] + ".json")
            resp = json.load(open(f))
            y.append(it["label"]); pred.append(resp["answers"]["category"]["choice"])
        y, pred = np.array(y), np.array(pred)
        acc = (y == pred).mean()
        rng = np.random.default_rng(3)
        vals = [((y[ii] == pred[ii]).mean()) for ii in (rng.choice(len(y), len(y), replace=True) for _ in range(1000))]
        print(f"  {m}: acc={acc:.3f} 95% CI {np.percentile(vals, [2.5, 97.5]).round(3).tolist()}")

    print("\nA2 BOOTSTRAP AUC CI")
    pairs = json.load(open(ROOT / "data/a2_pairs.json", encoding="utf-8"))["pairs"]
    for m in R["A2"]["models"]:
        slug = m.replace("/", "__")
        p = []
        for pr in pairs:
            f = ROOT / "cache/responses" / slug / "A2" / (pr["id"] + ".json")
            p.append(json.load(open(f))["answers"]["answers"]["noul"])
        p = np.array(p); y = np.array([pr["label"] for pr in pairs])
        def auc(p, y):
            pos, neg = p[y == 1], p[y == 0]
            return (np.sum(pos[:, None] > neg[None, :]) + 0.5 * np.sum(pos[:, None] == neg[None, :])) / (len(pos) * len(neg))
        rng = np.random.default_rng(4)
        vals = [auc(p[ii], y[ii]) for ii in (rng.choice(len(y), len(y), replace=True) for _ in range(1000)) if y[ii].min() != y[ii].max()]
        print(f"  {m}: auc={auc(p,y):.3f} 95% CI {np.percentile(vals, [2.5, 97.5]).round(3).tolist()}")


if __name__ == "__main__":
    main()
