"""Idea 3: back-test a small gate against the 6 full gate runs in git history. Read-only."""
import collections, json, random, re, statistics as st, subprocess

COMMITS = ["cf3fcb7", "a40adc4", "3489a87", "80db60b", "4199be2", "c7b1010"]
FILES = ["tasks/answer_bench/GATE_RESULTS_originals_strict.jsonl", "tasks/answer_bench/GATE_RESULTS_instances_strict.jsonl", "tasks/pilot60/RESULTS_HAND60_strict.jsonl"]


def load(c):
    out = {}
    for f in FILES:
        p = subprocess.run(["git", "show", f"{c}:{f}"], capture_output=True)
        if p.returncode:
            continue
        for i, line in enumerate(p.stdout.decode("utf-8", "replace").splitlines()):
            try:
                r = json.loads(line)
            except ValueError:
                continue
            key = f"{f[-25:-13]}|{r.get('mid')}"
            b = str(r.get("blocker") or "")
            m = re.search(r"GATE ([a-z_]+)|hop failed: ([A-Z]+)|^([A-Z_]+)", b)
            blk = next((g for g in m.groups() if g), "other") if m else ("none" if not b else "other")
            out[key] = dict(g=r.get("strict_grade"), blk=blk, s=float(r.get("seconds") or 0), fam=str(r.get("family")), bank=r.get("source_bank"))
    return out


runs = {c: load(c) for c in COMMITS}
for c, r in runs.items():
    gr = collections.Counter(x["g"] for x in r.values())
    print(c, "cases", len(r), "ANSWERED", gr["ANSWERED"], "seconds", round(sum(x["s"] for x in r.values())), "top", gr.most_common(4))

ANS = "ANSWERED"


def stratified(base, per_blocker=6, per_family=2, seed=1):
    rng = random.Random(seed)
    pick = {k for k, v in base.items() if v["g"] == ANS}
    by = collections.defaultdict(list)
    for k, v in base.items():
        if v["g"] != ANS:
            by[v["blk"]].append(k)
    weights = {}
    for b, ks in by.items():
        n = min(per_blocker, len(ks))
        s = rng.sample(ks, n)
        pick.update(s)
        for k in s:
            weights[k] = len(ks) / n
    fam = collections.defaultdict(list)
    for k, v in base.items():
        if k not in pick:
            fam[v["fam"]].append(k)
    return pick, weights


def est_gain(pick, w, base, nxt):
    """Weighted estimate of total gained ANSWERED, from the non-answered stratum."""
    g = 0.0
    for k in pick:
        if k in nxt and base[k]["g"] != ANS and nxt[k]["g"] == ANS:
            g += w.get(k, 1)
    return g


print("\npair: full change | stratified estimate over seeds | random-100 estimate over seeds | regressions seen")
rows = []
for a, b in zip(COMMITS, COMMITS[1:]):
    A, B = runs[a], runs[b]
    common = [k for k in A if k in B]
    if len(common) < 100:
        print(a, b, "keys do not match, common", len(common))
        continue
    gained = sum(A[k]["g"] != ANS and B[k]["g"] == ANS for k in common)
    lost = sum(A[k]["g"] == ANS and B[k]["g"] != ANS for k in common)
    full_s = sum(B[k]["s"] for k in common)
    strat, rand, sizes, secs, reg_r, gain_seen_s, gain_seen_r = [], [], [], [], [], [], []
    for seed in range(200):
        pick, w = stratified({k: A[k] for k in common}, seed=seed)
        strat.append(est_gain(pick, w, A, B))
        sizes.append(len(pick))
        secs.append(sum(B[k]["s"] for k in pick))
        gain_seen_s.append(sum(k in pick and A[k]["g"] != ANS and B[k]["g"] == ANS for k in common))
        rng = random.Random(seed)
        rp = rng.sample(common, 100)
        rand.append(sum(A[k]["g"] != ANS and B[k]["g"] == ANS for k in rp) * len(common) / 100)
        reg_r.append(sum(A[k]["g"] == ANS and B[k]["g"] != ANS for k in rp))
        gain_seen_r.append(sum(A[k]["g"] != ANS and B[k]["g"] == ANS for k in rp))
    q = lambda x: (round(st.quantiles(x, n=20)[0]), round(st.median(x)), round(st.quantiles(x, n=20)[-1]))
    print(f"{a}->{b}: gained {gained} lost {lost} of {len(common)}; full {full_s/60:.0f} min")
    print(f"   stratified n~{st.median(sizes):.0f} {st.median(secs)/60:.1f} min: est gain p5/med/p95 {q(strat)}; gains seen in sample median {st.median(gain_seen_s)}; regressions seen {lost}/{lost} (all answered cases included)")
    print(f"   random-100 {full_s/len(common)*100/60:.1f} min: est gain {q(rand)}; gains seen median {st.median(gain_seen_r)}; regressions seen median {st.median(reg_r)}/{lost}")
    rows.append(dict(a=a, b=b, gained=gained, lost=lost))
blk = collections.Counter(v["blk"] for v in runs[COMMITS[-1]].values() if v["g"] != ANS)
print("\nblocker strata now:", blk.most_common(20))
base = runs[COMMITS[-1]]
pick, _ = stratified(base)
print("sample for current main:", len(pick), "cases, est minutes", round(sum(base[k]["s"] for k in pick) / 60, 1), "of full", round(sum(v["s"] for v in base.values()) / 60))
json.dump(sorted(pick), open(r"C:\Users\warri\AppData\Local\Temp\claude\C--Users-warri-Downloads-Info-Diffusion-Model\86cf8135-8a1c-42ad-9bb8-a82bc4f3fd44\scratchpad\gate_sample_keys.json", "w"))
