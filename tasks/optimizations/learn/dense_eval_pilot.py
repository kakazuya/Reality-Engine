"""Paid dense eval (Shivam OK'd ~$0.35, 2026-10-26): Nemotron-3-Embed-8B on old vs v2 vs v2+layout pilot chunks.

Corpus = every non-AR pilot doc + the AR docs that went through GPU layout, so all three variants search the
same documents. Embeddings are cached by sha1(text) so identical chunks are paid once.
Usage: python dense_eval.py <worktree> [--max-usd 0.35] [--dry]
"""
import hashlib, json, sqlite3, sys, types
from pathlib import Path
import numpy as np

W = Path(sys.argv[1]); DRY = "--dry" in sys.argv
MAX_USD = float(sys.argv[sys.argv.index("--max-usd") + 1]) if "--max-usd" in sys.argv else 0.35
sys.path[:0] = [str(W), str(W / "plugins/reality-data/server")]
for _m in ("onnxruntime", "tokenizers"):
    try: __import__(_m)
    except ImportError: sys.modules[_m] = types.SimpleNamespace(Tokenizer=None)
from reality_engine.scripts import eval_retrieval as ev  # noqa: E402

OUT = W / ".tmp" / "c1" / "dense"; OUT.mkdir(parents=True, exist_ok=True)
PRICE = 0.035
pilot = ev.open_db(W / ".tmp/c1/chunks_v2_pilot.db")
lay = ev.open_db(W / ".tmp/c1/chunks_v2_layout_pilot.db")
layout_docs = {r[0] for r in lay.execute("select distinct doc_id from chunks_v2 where doc_type='annual_report'")}
lay_types = {r[0] for r in lay.execute("select distinct doc_type from chunks_v2")}


def keep(doc_type, doc_id):
    return doc_type != "annual_report" or doc_id in layout_docs


def load(conn, table, only_types=None):
    out = []
    for r in conn.execute(f"select chunk_id, doc_id, doc_type, coalesce(header,'') h, body, norm_start, norm_end from {table}"):
        if not keep(r["doc_type"], r["doc_id"]) or (only_types and r["doc_type"] not in only_types):
            continue
        text = (r["h"] + "\n" + r["body"]).strip() if r["h"] else r["body"]
        out.append({"chunk_id": str(r["chunk_id"]), "doc_id": r["doc_id"], "doc_type": r["doc_type"], "text": text,
                    "norm_start": r["norm_start"], "norm_end": r["norm_end"]})
    return out


old = load(pilot, "chunks_old")
v2 = load(pilot, "chunks_v2")
# layout replaces the doc types the layout DB holds (ARs, decks if present); other types come from plain v2
v2l = [c for c in v2 if c["doc_type"] not in lay_types] + load(lay, "chunks_v2", lay_types)
variants = {"old": old, "v2": v2, "v2_layout": v2l}

qs = [r for r in ev.load_quality_set(W / "tasks/optimizations/learn/quality_set_v2.jsonl")
      if keep(r["doc_type"], r["doc_id"])]

cache_f = OUT / "cache.npz"
cache = dict(np.load(cache_f, allow_pickle=False)) if cache_f.exists() else {}
key = lambda t, q: hashlib.sha1((("Q:" if q else "D:") + t).encode()).hexdigest()
todo_d = {key(c["text"], False): c["text"] for v in variants.values() for c in v}
todo_d = {k: t for k, t in todo_d.items() if k not in cache}
todo_q = {key(r["question"], True): r["question"] for r in qs}
todo_q = {k: t for k, t in todo_q.items() if k not in cache}
est = (sum(map(len, todo_d.values())) + sum(map(len, todo_q.values()))) / 3.0 / 1e6 * PRICE
print(f"layout AR docs {len(layout_docs)} types {sorted(lay_types)}; questions {len(qs)}; "
      f"chunks old {len(old)} v2 {len(v2)} v2_layout {len(v2l)}; new texts {len(todo_d)}+{len(todo_q)}q; est ${est:.3f}")
if DRY:
    sys.exit(0)
if est > MAX_USD:
    sys.exit(f"estimate ${est:.3f} > cap ${MAX_USD}")

from reality_engine.scripts.embed_model_test import OpenAIEmbed  # noqa: E402
m = OpenAIEmbed("nemotron3-8b-di")
for todo, isq in ((todo_d, False), (todo_q, True)):
    if todo:
        ks = list(todo)
        E = m.embed([todo[k] for k in ks], query=isq, bs=16, workers=6)
        cache.update(zip(ks, E))
        np.savez(cache_f, **cache)
cost = m.tokens * PRICE / 1e6
print(f"tokens {m.tokens:,} cost ${cost:.4f}")

Q = np.stack([cache[key(r["question"], True)] for r in qs])
res = {"cost_usd": round(cost, 4), "tokens": m.tokens, "layout_docs": sorted(layout_docs), "n_questions": len(qs)}
for name, chunks in variants.items():
    D = np.stack([cache[key(c["text"], False)] for c in chunks])
    S = Q @ D.T
    ranks = []
    for i, r in enumerate(qs):
        top = np.argsort(-S[i])[:ev.TOPK]
        ranks.append(ev.first_hit_rank([chunks[j] for j in top], r))
    out = {"overall": ev.score(qs, ranks), "chunks": len(chunks)}
    for t in sorted({r["doc_type"] for r in qs}):
        idx = [i for i, r in enumerate(qs) if r["doc_type"] == t]
        out[t] = ev.score([qs[i] for i in idx], [ranks[i] for i in idx])
    idx = [i for i, r in enumerate(qs) if r.get("difficulty") in ("hard", "H")]
    out["hard"] = ev.score([qs[i] for i in idx], [ranks[i] for i in idx])
    res[name] = out
    print(name, json.dumps(out))
json.dump(res, open(OUT / "dense_results.json", "w"), indent=1)
