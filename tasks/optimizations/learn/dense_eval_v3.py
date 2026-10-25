"""Round-3 paid dense eval (within Shivam's $0.35 test OK). Inputs: worker's dense_input/*.jsonl + quality_set_v3.
Corpus: all non-AR docs + the 9 ARs that have layout chunks, so every variant searches the same docs.
Embeddings cached by sha1(text) in the round-2 cache, so unchanged chunks are not paid again."""
import hashlib, json, sys, types
from pathlib import Path
import numpy as np
W = Path(sys.argv[1]); R2 = Path(sys.argv[2]); DRY = "--dry" in sys.argv; CAP = 0.20
sys.path[:0] = [str(W)]
for _m in ("onnxruntime", "tokenizers"):
    try: __import__(_m)
    except ImportError: sys.modules[_m] = types.SimpleNamespace(Tokenizer=None)
from reality_engine.scripts import eval_retrieval as ev
D = W / ".tmp/c1/dense_input"
rd = lambda f: [json.loads(l) for l in open(D / f, encoding="utf-8")]
lay = rd("v2layout.jsonl")
ar9 = {c["doc_id"] for c in lay if c["doc_type"] == "annual_report"}
keep = lambda c: c["doc_type"] != "annual_report" or c["doc_id"] in ar9
import sqlite3
db = sqlite3.connect(f"file:{W / '.tmp/c1/chunks_v3_pilot.db'}?mode=ro", uri=True)
TAB = {"old": "chunks_old", "v2": "chunks_v2", "v2cap": "chunks_v2_cap"}
def withhdr(n):
    out = []
    for cid, did, dt, h, b, s0, s1 in db.execute(f"select chunk_id, doc_id, doc_type, coalesce(header,''), body, norm_start, norm_end from {TAB[n]}"):
        c = {"chunk_id": str(cid), "doc_id": did, "doc_type": dt, "norm_start": s0, "norm_end": s1,
             "text": (h + chr(10) + b).strip() if h else b}
        if keep(c): out.append(c)
    return out
V = {n: withhdr(n) for n in TAB}
qs = [r for r in ev.load_quality_set(W / "tasks/optimizations/learn/quality_set_v3.jsonl") if keep(r)]
cf = R2 / ".tmp/c1/dense/cache.npz"; cache = dict(np.load(cf))
key = lambda t, q: hashlib.sha1((("Q:" if q else "D:") + t).encode()).hexdigest()
td = {key(c["text"], False): c["text"] for v in V.values() for c in v}; td = {k: t for k, t in td.items() if k not in cache}
tq = {key(r["question"], True): r["question"] for r in qs}; tq = {k: t for k, t in tq.items() if k not in cache}
est = (sum(map(len, td.values())) + sum(map(len, tq.values()))) / 3.0 / 1e6 * 0.035
print(f"ar9 {len(ar9)} qs {len(qs)} chunks " + " ".join(f"{n}={len(v)}" for n, v in V.items()) + f" new {len(td)}+{len(tq)}q est ${est:.3f}", flush=True)
if DRY: sys.exit()
if est > CAP: sys.exit("over cap")
from reality_engine.scripts.embed_model_test import OpenAIEmbed
m = OpenAIEmbed("nemotron3-8b-di")
for todo, isq in ((td, False), (tq, True)):
    if todo:
        ks = list(todo); cache.update(zip(ks, m.embed([todo[k] for k in ks], query=isq, bs=16, workers=6))); np.savez(cf, **cache)
print(f"tokens {m.tokens:,} cost ${m.tokens * 0.035 / 1e6:.4f}", flush=True)
Q = np.stack([cache[key(r["question"], True)] for r in qs]); res = {"cost_usd": m.tokens * 0.035 / 1e6, "n": len(qs)}
for n, ch in V.items():
    S = Q @ np.stack([cache[key(c["text"], False)] for c in ch]).T
    ranks = [ev.first_hit_rank([ch[j] for j in np.argsort(-S[i])[:10]], r) for i, r in enumerate(qs)]
    o = {"overall": ev.score(qs, ranks)}
    for t in sorted({r["doc_type"] for r in qs}) + ["H"]:
        idx = [i for i, r in enumerate(qs) if (r.get("difficulty") == "H" if t == "H" else r["doc_type"] == t)]
        o[t] = ev.score([qs[i] for i in idx], [ranks[i] for i in idx])
    res[n] = o; print(n, json.dumps({k: (v["n"], v["recall@1"], v["recall@5"], v["mrr"]) for k, v in o.items()}), flush=True)
json.dump(res, open(W / ".tmp/c1/dense_results_v3_hdr.json", "w"), indent=1)
