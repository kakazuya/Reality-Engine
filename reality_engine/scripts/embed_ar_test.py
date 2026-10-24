"""Annual-report embedding pilot on DeepInfra (2026-10-24, Shivam: pick the AR embedder on cost-to-value, as the
51-question transcript test picked Nemotron-3-Embed-8B; total test spend under $0.25).

Inputs (data/embed_test_ar/): corpus.json (every chunk of 6 annual reports already embedded by Qwen3-8B on Nebius:
PAGEIND FY24+FY23, OFSS FY25, NMDC FY22, OBEROIRLTY FY18, PATANJALI FY22; 1,701 chunks), gold_chunks.json and
questions.json (48 analyst questions, one target chunk each, paraphrased by Claude). Text embedded = the same
fresh-header text as the production indexes (reembed_gemma.texts_for).

Scoring as embed_model_test (hit@1/5/10, MRR; global and within the asked company), except that a chunk whose text is
a near-copy of the gold (5-word shingle Jaccard >= 0.5, e.g. boilerplate repeated in Page's FY23 and FY24 reports)
also counts as the answer. "qwen8b-nebius-stored" reuses the stored Nebius document vectors (no document cost) with
questions embedded by DeepInfra's Qwen3-8B; "qwen8b-di" re-embeds the corpus on DeepInfra, and the stored-vs-DeepInfra
cosine is reported as a parity check.

Spend guard: before each model the cost is estimated at 3.0 chars/token (AR measured 3.49) and the model is skipped
if it would take recorded spend past --max-usd; actual billed tokens come from the API's usage field.

    python -m reality_engine.scripts.embed_ar_test [--models ...] [--max-usd 0.22]
"""
import argparse
import json
import re
import sys
import time
import types
from pathlib import Path

import numpy as np

# API-only run: embed_model_test imports the local ONNX stack at module level, which this Python may not have
for _mod in ("onnxruntime", "tokenizers"):
    if _mod not in sys.modules:
        try:
            __import__(_mod)
        except ImportError:
            sys.modules[_mod] = types.SimpleNamespace(Tokenizer=None)
from reality_engine.scripts.embed_model_test import OpenAIEmbed  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "reality_engine/data/embed_test_ar"
QWEN_AR = ROOT / "reality_engine/data/vector_index_qwen8b_ar"
DI = "https://api.deepinfra.com/v1/openai"
QWEN_INSTRUCT_AR = ("Instruct: Given an analyst's question about an Indian listed company, retrieve the annual-report "
                    "passage that answers it\nQuery:")
# name: (repo, $/M, doc prefix, query prefix) -- DeepInfra list prices read 2026-10-24
MODELS = {
    "nemotron3-8b-di": ("nvidia/Nemotron-3-Embed-8B", 0.035, "passage: ", "query: "),
    "nemotron35-8b-di": ("nvidia/Nemotron-3.5-Embed-8B-BF16", 0.035, "passage: ", "query: "),
    "nemotron35-1b-di": ("nvidia/Nemotron-3.5-Embed-1B-BF16", 0.015, "passage: ", "query: "),
    "nemotron3-1b-di": ("nvidia/Nemotron-3-Embed-1B-BF16", 0.015, "passage: ", "query: "),
    "nemotron3-1b-fp4-di": ("nvidia/Nemotron-3-Embed-1B-NVFP4", 0.01, "passage: ", "query: "),
    "qwen8b-di": ("Qwen/Qwen3-Embedding-8B", 0.01, "", QWEN_INSTRUCT_AR),
    "bge-m3-di": ("BAAI/bge-m3", 0.01, "", ""),
}
for _n, (_repo, _usd, _d, _q) in MODELS.items():
    OpenAIEmbed.API[_n] = ("DEEPINFRA_API_KEY", _repo, [DI])
    OpenAIEmbed.PROMPTS[_n] = (_d, _q)
    OpenAIEmbed.PRICE[_n] = _usd


def shingles(text, n=5):
    w = re.findall(r"\w+", text.lower())
    return {" ".join(w[i:i + n]) for i in range(max(len(w) - n + 1, 1))}


def stored_qwen(ids):
    allids = np.load(QWEN_AR / "chunk_ids.npy")
    done = np.load(QWEN_AR / "done.npy").astype(bool)
    pos = {int(c): i for i, c in enumerate(allids)}
    rows = [pos[c] for c in ids]
    assert done[rows].all(), "a corpus chunk has no stored Qwen vector"
    v = np.load(QWEN_AR / "chunk_vectors.npy", mmap_mode="r")[rows].astype(np.float32)
    return v / np.linalg.norm(v, axis=1, keepdims=True)


def main(names, max_usd):
    corpus = json.load(open(OUT / "corpus.json", encoding="utf-8"))
    qs = json.load(open(OUT / "questions.json", encoding="utf-8"))
    ids = [c["chunk_id"] for c in corpus]; pos = {c: i for i, c in enumerate(ids)}
    syms = np.array([c["symbol"] for c in corpus])
    sh = [shingles(c["text"]) for c in corpus]
    answers = []
    for q in qs:
        g = sh[pos[q["chunk_id"]]]
        answers.append([i for i, s in enumerate(sh) if len(g & s) / max(len(g | s), 1) >= 0.5])
    chars = sum(len(c["text"]) for c in corpus)
    ledger = OUT / "spend.json"
    spent = json.load(open(ledger))["usd"] if ledger.exists() else 0.0
    results = json.load(open(OUT / "results.json")) if (OUT / "results.json").exists() else []
    done_models = {r["model"] for r in results}
    for name in names:
        if name in done_models:
            print(f"{name}: already scored, skipped", flush=True); continue
        doc_model = None if name == "qwen8b-nebius-stored" else name
        qmodel = "qwen8b-di" if name == "qwen8b-nebius-stored" else name
        est = (0 if doc_model is None else chars / 3.0 / 1e6 * MODELS[name][1]) + 0.001
        if spent + est > max_usd:
            print(f"{name}: skipped, est ${est:.3f} would pass cap (spent ${spent:.3f} of ${max_usd})", flush=True)
            continue
        m = OpenAIEmbed(qmodel)
        t0 = time.time()
        cache = OUT / f"emb_{name}.npy"
        try:
            if doc_model is None:
                E = stored_qwen(ids)
            elif cache.exists():
                E = np.load(cache)
            else:
                E = m.embed([c["text"] for c in corpus]); np.save(cache, E)
            rate = len(corpus) / (time.time() - t0)
            Q = m.embed([q["question"] for q in qs], query=True)
        except Exception as e:   # tokens already billed still count against the cap
            spent += m.tokens * MODELS[qmodel][1] / 1e6
            json.dump({"usd": spent}, open(ledger, "w"))
            print(f"{name}: FAILED {e!r}; spent ${spent:.4f}", flush=True)
            continue
        cost = m.tokens * MODELS[qmodel][1] / 1e6
        spent += cost
        json.dump({"usd": spent}, open(ledger, "w"))
        res = {"global": [], "company": []}
        for qi, (q, qv) in enumerate(zip(qs, Q)):
            s = E @ qv
            for scope in res:
                sc = s if scope == "global" else np.where(syms == syms[pos[q["chunk_id"]]], s, -9)
                best = max(sc[a] for a in answers[qi])
                res[scope].append(int((sc > best).sum()) + 1)
        r = {"model": name, "repo": MODELS[qmodel][0], "usd_per_m": MODELS[qmodel][1], "dim": int(E.shape[1]),
             "chunks_per_s": round(rate, 1) if doc_model else None, "tokens": m.tokens, "cost_usd": round(cost, 4),
             "api_429": m.r429}
        for scope, ranks in res.items():
            a = np.array(ranks)
            r[scope] = {"hit@1": round(float((a <= 1).mean()), 3), "hit@5": round(float((a <= 5).mean()), 3),
                        "hit@10": round(float((a <= 10).mean()), 3), "mrr": round(float((1 / a).mean()), 3)}
        r["ranks_global"] = res["global"]
        if name == "qwen8b-di":
            S = stored_qwen(ids)
            cs = (S * E).sum(1)
            r["parity_vs_nebius"] = {"median": round(float(np.median(cs)), 5), "min": round(float(cs.min()), 5)}
        results.append(r)
        json.dump(results, open(OUT / "results.json", "w"), indent=1)
        print(json.dumps({k: v for k, v in r.items() if k != "ranks_global"}), f"spent ${spent:.4f}", flush=True)
    print(f"TOTAL spent ${spent:.4f}", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default="qwen8b-nebius-stored,qwen8b-di,nemotron3-8b-di,nemotron35-8b-di,"
                                        "nemotron35-1b-di,nemotron3-1b-di,nemotron3-1b-fp4-di,bge-m3-di")
    ap.add_argument("--max-usd", type=float, default=0.22)
    a = ap.parse_args()
    main(a.models.split(","), a.max_usd)
