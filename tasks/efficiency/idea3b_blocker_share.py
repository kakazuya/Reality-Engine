import collections, contextlib, io, json, runpy, re, subprocess

buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    g = runpy.run_path(r"C:\Users\warri\AppData\Local\Temp\claude\C--Users-warri-Downloads-Info-Diffusion-Model\86cf8135-8a1c-42ad-9bb8-a82bc4f3fd44\scratchpad\idea3_gate_sample.py")
runs, C, ANS = g["runs"], g["COMMITS"], g["ANS"]
for a, b in zip(C, C[1:]):
    A, B = runs[a], runs[b]
    gain = collections.Counter(A[k]["blk"] for k in A if k in B and A[k]["g"] != ANS and B[k]["g"] == ANS)
    size = collections.Counter(v["blk"] for v in A.values() if v["g"] != ANS)
    sec = collections.defaultdict(float)
    for k, v in B.items():
        if k in A:
            sec[A[k]["blk"]] += v["s"]
    tot = sum(gain.values())
    if not tot:
        continue
    print(f"{a}->{b}: gains {tot}")
    cum = 0
    for bk, n in gain.most_common(4):
        cum += n
        print(f"   {bk:14s} gained {n:3d} of stratum {size[bk]:4d} ({sec[bk]/60:.1f} min) cumulative {100*cum/tot:.0f}% of gains")
