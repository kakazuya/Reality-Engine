"""Build A2: NVFP4 top-6 candidates for the 48 AR questions and the 288 yes/no pairs."""
import json
import os
import subprocess
from pathlib import Path

import numpy as np
import requests

ROOT = Path(r"C:\Users\warri\Downloads\IDM-worktrees\20261024T172743Z-a480564b")
DATA = Path(r"C:\Users\warri\Downloads\Info_Diffusion_Model\reality_engine\data\embed_test_ar")
OUT = ROOT / "tasks/research/decision_pilot"
MODEL = "nvidia/Nemotron-3-Embed-1B-NVFP4"
PRICE = 0.01
BASE = "https://api.deepinfra.com/v1/openai"


def key():
    k = os.environ.get("DEEPINFRA_API_KEY")
    if not k:
        k = subprocess.run(["powershell", "-NoProfile", "-c",
                            "[Environment]::GetEnvironmentVariable('DEEPINFRA_API_KEY','User')"],
                           capture_output=True, text=True).stdout
    return k.strip()


def shingles(text, n=5):
    import re
    w = re.findall(r"\w+", text.lower())
    return {" ".join(w[i:i + n]) for i in range(max(len(w) - n + 1, 1))}


def main():
    corpus = json.load(open(DATA / "corpus.json", encoding="utf-8"))
    qs = json.load(open(DATA / "questions.json", encoding="utf-8"))
    ids = [c["chunk_id"] for c in corpus]
    pos = {c: i for i, c in enumerate(ids)}
    E = np.load(DATA / "emb_nemotron3-1b-fp4-di.npy").astype(np.float32)
    E /= np.linalg.norm(E, axis=1, keepdims=True)
    r = requests.post(f"{BASE}/embeddings", headers={"Authorization": "Bearer " + key()},
                      json={"model": MODEL, "input": ["query: " + q["question"] for q in qs]}, timeout=120)
    r.raise_for_status()
    j = r.json()
    Q = np.array([e["embedding"] for e in sorted(j["data"], key=lambda e: e["index"])], dtype=np.float32)
    Q /= np.linalg.norm(Q, axis=1, keepdims=True)
    tokens = j.get("usage", {}).get("prompt_tokens", 0)
    cost = tokens * PRICE / 1e6
    np.save(OUT / "cache/a2_qemb.npy", Q)
    ledger = OUT / "spend.json"
    spend = json.load(open(ledger)) if ledger.exists() else {"usd": 0.0, "entries": []}
    spend["usd"] += cost
    spend["entries"].append({"arm": "A2", "model": MODEL, "kind": "question_embedding",
                             "tokens": tokens, "usd": cost})
    json.dump(spend, open(ledger, "w"), indent=1)

    sh = [shingles(c["text"]) for c in corpus]
    gold = {g["chunk_id"]: g for g in json.load(open(DATA / "gold_chunks.json", encoding="utf-8"))}
    pairs, ranks = [], []
    for qi, q in enumerate(qs):
        g = sh[pos[q["chunk_id"]]]
        answers = {i for i, s in enumerate(sh) if len(g & s) / max(len(g | s), 1) >= 0.5}
        s = E @ Q[qi]
        order = np.argsort(-s, kind="stable")
        rank = next(n for n, i in enumerate(order, 1) if i in answers)
        ranks.append(rank)
        top = list(order[:6])
        for cr, i in enumerate(top, 1):
            pairs.append({"arm": "A2", "id": f"q{qi:02d}_c{cr}", "qid": qi, "question": q["question"],
                          "chunk_id": int(ids[i]), "symbol": corpus[i]["symbol"], "cand_rank": cr,
                          "label": int(i in answers), "state": corpus[i]["text"]})
    out = {"model": MODEL, "tokens": tokens, "cost_usd": cost, "ranks": ranks,
           "hit@1": float(np.mean(np.array(ranks) <= 1)), "hit@3": float(np.mean(np.array(ranks) <= 3)),
           "pairs": pairs}
    json.dump(out, open(OUT / "data/a2_pairs.json", "w", encoding="utf-8"), indent=1)
    print(f"tokens={tokens} cost=${cost:.6f} hit@1={out['hit@1']:.3f} hit@3={out['hit@3']:.3f}")
    print("ranks:", ranks)


if __name__ == "__main__":
    (OUT / "cache").mkdir(parents=True, exist_ok=True)
    main()
