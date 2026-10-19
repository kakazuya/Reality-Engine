"""Colab side of the embedding retrieval test (2026-10-19, Shivam: is Qwen3-Embedding-8B worth it vs gemini-embedding-001).

Runs INSIDE a Colab GPU runtime (L4 / A100: the 8B in bf16 needs ~16 GB). Inputs are the same files as
embed_model_test.py (data/embed_test/corpus.json, questions.json), placed in the runtime's working directory.
Writes emb_<name>.npy (corpus, row order = corpus.json) and qemb_<name>.npy (questions) for scoring back home:
    python -m reality_engine.scripts.embed_model_test --models <name>   (with both .npy files in data/embed_test/)

Model-card usage (Qwen/Qwen3-Embedding-8B): last-token pooling, left padding, instruction prefix on queries only,
L2-normalised. Same instruction as the local 0.6B test (embed_model_test.QWEN_INSTRUCT).
"""
import json
import sys
import time

import numpy as np
import torch
import torch.nn.functional as F
from transformers import AutoModel, AutoTokenizer

NAME = sys.argv[1] if len(sys.argv) > 1 else "qwen3-8b"
REPO = {"qwen3-8b": "Qwen/Qwen3-Embedding-8B", "qwen3-4b": "Qwen/Qwen3-Embedding-4B",
        "embeddinggemma-colab": "google/embeddinggemma-300m"}[NAME]
MAX_LEN = 2048
QWEN_INSTRUCT = ("Instruct: Given an analyst's question about an Indian listed company, retrieve the earnings-call "
                 "transcript passage that answers it\nQuery:")


def main():
    corpus = json.load(open("corpus.json", encoding="utf-8"))
    qs = json.load(open("questions.json", encoding="utf-8"))
    print(torch.cuda.get_device_name(0), f"{torch.cuda.get_device_properties(0).total_memory / 2**30:.0f} GB", flush=True)
    if NAME == "embeddinggemma-colab":
        from sentence_transformers import SentenceTransformer
        m = SentenceTransformer(REPO, device="cuda")
        t0 = time.time()
        E = m.encode([c["text"] for c in corpus], prompt="title: none | text: ", batch_size=32,
                     normalize_embeddings=True, show_progress_bar=True)
        rate = len(corpus) / (time.time() - t0)
        Q = m.encode([q["question"] for q in qs], prompt="task: search result | query: ", normalize_embeddings=True)
    else:
        tok = AutoTokenizer.from_pretrained(REPO, padding_side="left")
        model = AutoModel.from_pretrained(REPO, torch_dtype=torch.bfloat16, attn_implementation="sdpa").cuda().eval()

        @torch.no_grad()
        def embed(texts, bs):
            order = np.argsort([-len(t) for t in texts])           # longest first: OOM shows at once, not at the end
            out = [None] * len(texts)
            for s in range(0, len(texts), bs):
                idx = order[s:s + bs]
                b = tok([texts[i] for i in idx], padding=True, truncation=True, max_length=MAX_LEN, return_tensors="pt").to("cuda")
                h = model(**b).last_hidden_state[:, -1]               # left padding: last position = last real token
                v = F.normalize(h.float(), p=2, dim=1).cpu().numpy()
                for i, x in zip(idx, v):
                    out[i] = x
                if s // bs % 20 == 0:
                    print(f"{s + len(idx)}/{len(texts)}", flush=True)
            return np.vstack(out).astype(np.float32)

        t0 = time.time()
        E = embed([c["text"] for c in corpus], bs=8)
        rate = len(corpus) / (time.time() - t0)
        Q = embed([QWEN_INSTRUCT + q["question"] for q in qs], bs=16)
    np.save(f"emb_{NAME}.npy", E)
    np.save(f"qemb_{NAME}.npy", Q)
    json.dump({"model": NAME, "repo": REPO, "chunks_per_s": round(rate, 2), "dim": int(E.shape[1]),
               "gpu": torch.cuda.get_device_name(0)}, open(f"meta_{NAME}.json", "w"))
    print(f"done: {len(corpus)} chunks at {rate:.1f}/s, dim {E.shape[1]}", flush=True)


if __name__ == "__main__":
    main()
