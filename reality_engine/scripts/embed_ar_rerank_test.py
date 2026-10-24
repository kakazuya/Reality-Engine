"""Reranker leg of the annual-report embedding pilot (2026-10-24, Shivam: can Nemotron-3-Embed-1B-NVFP4 + a reranker
match Nemotron-3-Embed-8B's ranking for less money? Test spend stays inside the same $0.25 ledger).

Takes the cached NVFP4 corpus vectors from embed_ar_test (data/embed_test_ar/emb_<model>.npy), re-embeds the 48
questions (a few thousand tokens), keeps each question's top --k candidates and reorders them with a DeepInfra
reranker (/v1/inference/<repo>: {"queries": [q], "documents": [...]} -> one score per document). Candidates past k
keep their embedding order. Scoring and the near-duplicate answer rule are the same as embed_ar_test. Spend is the
cost DeepInfra reports per call (inference_status.cost), added to data/embed_test_ar/spend.json; a reranker is
skipped if its estimate would pass --max-usd.

    python -m reality_engine.scripts.embed_ar_rerank_test [--base nemotron3-1b-fp4-di] [--k 20] [--max-usd 0.24]
"""
import argparse
import json
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import requests

from reality_engine.scripts import embed_ar_test as base_test
from reality_engine.scripts.embed_model_test import OpenAIEmbed
from reality_engine.scripts.resource_watchdog import user_env

OUT = base_test.OUT
RERANKERS = {   # name: (repo, $/M) -- DeepInfra list prices read 2026-10-24
    "nemotron35-rerank-8b": ("nvidia/Nemotron-3.5-Rerank-8B-BF16", 0.05),
    "qwen3-rerank-4b": ("Qwen/Qwen3-Reranker-4B", 0.025),
    "qwen3-rerank-0.6b": ("Qwen/Qwen3-Reranker-0.6B", 0.01),
}


def rerank(repo, key, query, docs):
    r = requests.post(f"https://api.deepinfra.com/v1/inference/{repo}", headers={"Authorization": f"bearer {key}"},
                      json={"queries": [query], "documents": docs}, timeout=300)
    r.raise_for_status()
    j = r.json()
    return j["scores"], float((j.get("inference_status") or {}).get("cost") or 0.0)


def main(base, names, k, max_usd):
    corpus = json.load(open(OUT / "corpus.json", encoding="utf-8"))
    qs = json.load(open(OUT / "questions.json", encoding="utf-8"))
    ids = [c["chunk_id"] for c in corpus]; pos = {c: i for i, c in enumerate(ids)}
    texts = [c["text"] for c in corpus]
    sh = [base_test.shingles(t) for t in texts]
    answers = []
    for q in qs:
        g = sh[pos[q["chunk_id"]]]
        answers.append({i for i, s in enumerate(sh) if len(g & s) / max(len(g | s), 1) >= 0.5})
    ledger = OUT / "spend.json"
    spent = json.load(open(ledger))["usd"]
    E = np.load(OUT / f"emb_{base}.npy")
    m = OpenAIEmbed(base)
    Q = m.embed([q["question"] for q in qs], query=True)
    spent += m.tokens * OpenAIEmbed.PRICE[base] / 1e6
    json.dump({"usd": spent}, open(ledger, "w"))
    orders = [list(np.argsort(-(E @ qv), kind="stable")) for qv in Q]
    cand_chars = sum(len(texts[i]) for o in orders for i in o[:k])
    key = user_env()["DEEPINFRA_API_KEY"]
    results = json.load(open(OUT / "rerank_results.json")) if (OUT / "rerank_results.json").exists() else []
    rows = [("none", lambda qi: orders[qi], 0.0)]
    for name in names:
        repo, usd = RERANKERS[name]
        est = cand_chars / 3.0 / 1e6 * usd
        if spent + est > max_usd:
            print(f"{name}: skipped, est ${est:.3f} would pass cap (spent ${spent:.4f} of ${max_usd})", flush=True)
            continue

        def one(qi, repo=repo):
            top = orders[qi][:k]
            scores, cost = rerank(repo, key, qs[qi]["question"], [texts[i] for i in top])
            return [top[j] for j in np.argsort(-np.array(scores), kind="stable")] + orders[qi][k:], cost
        with ThreadPoolExecutor(6) as ex:
            out = list(ex.map(one, range(len(qs))))
        cost = sum(c for _, c in out)
        spent += cost
        json.dump({"usd": spent}, open(ledger, "w"))
        reordered = [o for o, _ in out]
        rows.append((name, lambda qi, r=reordered: r[qi], cost))
    for name, order_of, cost in rows:
        ranks = []
        for qi in range(len(qs)):
            o = order_of(qi)
            ranks.append(next(n for n, i in enumerate(o, 1) if i in answers[qi]))
        a = np.array(ranks)
        r = {"base": base, "reranker": name, "k": k, "cost_usd": round(cost, 4),
             **{f"hit@{n}": round(float((a <= n).mean()), 3) for n in (1, 3, 5, 10)},
             "mrr": round(float((1 / a).mean()), 3), "ranks": ranks}
        results = [x for x in results if not (x["base"] == base and x["reranker"] == name and x["k"] == k)] + [r]
        print(json.dumps({x: v for x, v in r.items() if x != "ranks"}), flush=True)
    json.dump(results, open(OUT / "rerank_results.json", "w"), indent=1)
    print(f"TOTAL spent ${spent:.4f}", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="nemotron3-1b-fp4-di")
    ap.add_argument("--rerankers", default="qwen3-rerank-0.6b,qwen3-rerank-4b,nemotron35-rerank-8b")
    ap.add_argument("--k", type=int, default=20)
    ap.add_argument("--max-usd", type=float, default=0.24)
    a = ap.parse_args()
    main(a.base, a.rerankers.split(","), a.k, a.max_usd)
