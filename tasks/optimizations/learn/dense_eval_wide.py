"""Wide-test paid dense eval (Shivam: <= $1 of the $2.41 DeepInfra balance, after pre-flight).
Arms: old (production-style, with its [Metadata] header), v2 (header+body), facts_fixed (manager-rebuilt, headers).
Global search over all 588 docs; hit = retrieved unit overlapping the gold span in the gold doc. Slices by doc type,
qtype, chart/table, cross-doc, mcap. Embeddings cached by sha1(text)."""
import hashlib, json, sys, types
from pathlib import Path
import numpy as np
W = Path(sys.argv[1]); DRY = "--dry" in sys.argv; CAP = 0.60   # $1 minus worst-case $0.40 already spent (two interrupted runs)
sys.path[:0] = [str(W)]
for _m in ("onnxruntime", "tokenizers"):
    try: __import__(_m)
    except ImportError: sys.modules[_m] = types.SimpleNamespace(Tokenizer=None)
from reality_engine.scripts import eval_retrieval as ev
D = W / ".tmp/c2w/dense_input"
rd = lambda f: [json.loads(l) for l in open(D / f, encoding="utf-8")]
V = {"old": rd("old.jsonl"), "v2": rd("v2.jsonl"), "facts": rd("facts_fixed.jsonl")}
qs = [json.loads(l) for l in open(W / ".tmp/c2w/quality_set_wide.jsonl", encoding="utf-8")]
SH = W / ".tmp/c2w/dense_shards"; SH.mkdir(exist_ok=True)
cf = W / ".tmp/c2w/dense_cache.npz"; cache = {k: v.astype(np.float16) for k, v in np.load(cf).items()} if cf.exists() else {}
for f in sorted(SH.glob("*.npz")): cache.update(np.load(f))
key = lambda t, q: hashlib.sha1((("Q:" if q else "D:") + t).encode()).hexdigest()
td = {key(c["text"], False): c["text"] for v in V.values() for c in v}; td = {k: t for k, t in td.items() if k not in cache}
tq = {key(r["question"], True): r["question"] for r in qs}; tq = {k: t for k, t in tq.items() if k not in cache}
est = (sum(map(len, td.values())) + sum(map(len, tq.values()))) / 3.5 / 1e6 * 0.035
print(f"qs {len(qs)} units " + " ".join(f"{n}={len(v)}" for n, v in V.items()) + f" new {len(td)}+{len(tq)}q est ${est:.3f}", flush=True)
if DRY: sys.exit()
if est > CAP: sys.exit("over cap")
from reality_engine.scripts.embed_model_test import OpenAIEmbed
m = OpenAIEmbed("nemotron3-8b-di")
for todo, isq in ((td, False), (tq, True)):
    ks = list(todo)
    for i in range(0, len(ks), 1000):          # one float16 shard per 1k texts: a failure loses at most one part
        part = ks[i:i + 1000]
        for attempt in range(4):
            try:
                vec = m.embed([todo[k] for k in part], query=isq, bs=16, workers=6).astype(np.float16)
                np.savez(SH / f"{'q' if isq else 'd'}{__import__('time').time_ns()}.npz", **dict(zip(part, vec))); cache.update(zip(part, vec)); break
            except Exception as exc:  # read timeouts: retry this part only; earlier parts are already saved
                print(f"  part {i} attempt {attempt + 1} failed: {type(exc).__name__}", flush=True)
                if attempt == 3: raise
                import time; time.sleep(30)
        print(f"  saved {i + len(part)}/{len(ks)} tokens {m.tokens:,}", flush=True)
cost = m.tokens * 0.035 / 1e6; print(f"tokens {m.tokens:,} cost ${cost:.4f}", flush=True)
Q = np.stack([cache[key(r["question"], True)] for r in qs]); res = {"cost_usd": cost, "n": len(qs)}
slices = {"deck": lambda r: r["doc_type"] == "deck", "concall": lambda r: r["doc_type"] == "concall",
          "chart_table": lambda r: bool(r.get("chart_or_table")), "cross_doc": lambda r: bool(r.get("cross_document")),
          "hard": lambda r: r.get("difficulty") in ("H", "hard")}
for qt in sorted({r.get("qtype") for r in qs if r.get("qtype")}): slices["q_" + qt] = (lambda t: lambda r: r.get("qtype") == t)(qt)
for mc in sorted({r.get("mcap_bucket") for r in qs if r.get("mcap_bucket")}): slices["m_" + mc] = (lambda t: lambda r: r.get("mcap_bucket") == t)(mc)
for n, ch in V.items():
    E = np.stack([cache[key(c["text"], False)] for c in ch]).astype(np.float32); S = Q.astype(np.float32) @ E.T; del E
    ranks = [ev.first_hit_rank([ch[j] for j in np.argsort(-S[i])[:10]], r) for i, r in enumerate(qs)]
    o = {"overall": ev.score(qs, ranks)}
    for s, f in slices.items():
        idx = [i for i, r in enumerate(qs) if f(r)]; o[s] = ev.score([qs[i] for i in idx], [ranks[i] for i in idx])
    res[n] = o; print(n, json.dumps({k: (v["n"], v["recall@1"], v["recall@5"], v["mrr"]) for k, v in o.items()}), flush=True)
json.dump(res, open(W / ".tmp/c2w/dense_results_wide.json", "w"), indent=1)
