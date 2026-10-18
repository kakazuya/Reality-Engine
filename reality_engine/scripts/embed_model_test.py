"""Embedding-model retrieval test on our own concall chunks (2026-10-18, Shivam: test before switching from bge-small).

Inputs (data/embed_test/): corpus.json (every transcript chunk of 60 random companies, as stored in document_chunks),
gold_chunks.json + questions.json (51 analyst questions, one target chunk each, paraphrased by a Sonnet helper).
For each model: embed corpus + questions on DirectML (CPU fallback), then rank (a) the whole corpus, (b) only the asked
company's chunks. Reports hit@1/5/10, MRR, chunks/s. Embeddings cached in data/embed_test/emb_<model>.npy.

    python -m reality_engine.scripts.embed_model_test [--models bge-small,bge-base,qwen3-0.6b,embeddinggemma]
"""
import argparse
import json
import time
from pathlib import Path

import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer

ROOT = Path(__file__).resolve().parents[2]
MODELS = ROOT / "reality_engine/data/models"
OUT = ROOT / "reality_engine/data/embed_test"
QWEN_INSTRUCT = ("Instruct: Given an analyst's question about an Indian listed company, retrieve the earnings-call "
                 "transcript passage that answers it\nQuery:")


class Model:
    def __init__(self, name):
        self.name = name
        d = {"bge-small": "bge-small-en-v1.5", "bge-base": "bge-base-en-v1.5", "qwen3-0.6b": "qwen3-embedding-0.6b",
             "embeddinggemma": "embeddinggemma-300m"}[name]
        self.dir = MODELS / d
        self.tok = Tokenizer.from_file(str(self.dir / "tokenizer.json"))
        self.max_len = {"bge-small": 512, "bge-base": 512, "qwen3-0.6b": 1024, "embeddinggemma": 2048}[name]
        self.tok.no_padding()
        self.tok.enable_truncation(self.max_len - (1 if name == "qwen3-0.6b" else 0))
        so = ort.SessionOptions()
        self.sess = ort.InferenceSession(str(self.dir / "onnx/model.onnx"), so,
                                         providers=["DmlExecutionProvider", "CPUExecutionProvider"])
        self.inputs = [i.name for i in self.sess.get_inputs()]
        self.provider = self.sess.get_providers()[0]

    def fmt(self, text, query):
        if self.name.startswith("bge"):
            return ("Represent this sentence for searching relevant passages: " + text) if query else text
        if self.name == "qwen3-0.6b":
            return f"{QWEN_INSTRUCT}{text}" if query else text
        return f"task: search result | query: {text}" if query else f"title: none | text: {text}"

    def _batch(self, texts):
        enc = [self.tok.encode(t) for t in texts]
        ids = [e.ids for e in enc]
        if self.name == "qwen3-0.6b":
            ids = [x + [151643] for x in ids]   # <|endoftext|>, the token Qwen3-Embedding pools on
        L = max(len(x) for x in ids)
        pad = self.tok.token_to_id("<pad>") or 0
        inp = np.full((len(ids), L), pad, dtype=np.int64); mask = np.zeros((len(ids), L), dtype=np.int64)
        for i, x in enumerate(ids):
            inp[i, :len(x)] = x; mask[i, :len(x)] = 1
        feed = {"input_ids": inp, "attention_mask": mask}
        if "token_type_ids" in self.inputs:
            feed["token_type_ids"] = np.zeros_like(inp)
        if "position_ids" in self.inputs:
            feed["position_ids"] = np.tile(np.arange(L, dtype=np.int64), (len(ids), 1))
        for i in self.sess.get_inputs():
            if i.name.startswith("past_key_values"):
                feed[i.name] = np.zeros((len(ids), i.shape[1], 0, i.shape[3]), dtype=np.float32)
        outs = self.sess.run(None, feed)
        names = [o.name for o in self.sess.get_outputs()]
        if self.name == "embeddinggemma":
            v = outs[names.index("sentence_embedding")]
        else:
            h = outs[names.index("last_hidden_state")]
            if self.name == "qwen3-0.6b":       # last-token pooling (right padding: last real token)
                v = h[np.arange(len(ids)), mask.sum(1) - 1]
            elif self.name == "bge-small":     # production contract: mean pooling (onnx_embedder)
                v = (h * mask[..., None]).sum(1) / mask.sum(1, keepdims=True)
            else:                              # bge-base model card: CLS pooling
                v = h[:, 0]
        return v / np.linalg.norm(v, axis=1, keepdims=True)

    def embed(self, texts, query=False, bs=16):
        order = np.argsort([len(t) for t in texts])
        out = np.zeros((len(texts), 0), dtype=np.float32)
        res = [None] * len(texts)
        for s in range(0, len(texts), bs):
            idx = order[s:s + bs]
            vs = self._batch([self.fmt(texts[i], query) for i in idx])
            for i, v in zip(idx, vs):
                res[i] = v
        return np.vstack(res).astype(np.float32)


def evaluate(names):
    corpus = json.load(open(OUT / "corpus.json", encoding="utf-8"))
    qs = json.load(open(OUT / "questions.json", encoding="utf-8"))
    gold = {g["chunk_id"]: g for g in json.load(open(OUT / "gold_chunks.json", encoding="utf-8"))}
    ids = [c["chunk_id"] for c in corpus]; pos = {c: i for i, c in enumerate(ids)}
    syms = np.array([c["symbol"] for c in corpus])
    rows = []
    for name in names:
        m = Model(name)
        cache = OUT / f"emb_{name}.npy"
        t0 = time.time()
        if cache.exists():
            E = np.load(cache); rate = None
        else:
            E = m.embed([c["text"] for c in corpus]); rate = len(corpus) / (time.time() - t0); np.save(cache, E)
        Q = m.embed([q["question"] for q in qs], query=True)
        res = {"global": [], "company": []}
        for q, qv in zip(qs, Q):
            g = pos[q["chunk_id"]]; s = E @ qv
            for scope in res:
                sc = s if scope == "global" else np.where(syms == gold[q["chunk_id"]]["symbol"], s, -9)
                rank = int((sc > sc[g]).sum()) + 1
                res[scope].append(rank)
        r = {"model": name, "provider": m.provider, "chunks_per_s": round(rate, 1) if rate else None, "dim": E.shape[1]}
        for scope, ranks in res.items():
            a = np.array(ranks)
            r[scope] = {"hit@1": round((a <= 1).mean(), 3), "hit@5": round((a <= 5).mean(), 3),
                        "hit@10": round((a <= 10).mean(), 3), "mrr": round((1 / a).mean(), 3)}
        r["ranks_global"] = res["global"]
        rows.append(r)
        print(json.dumps({k: v for k, v in r.items() if k != "ranks_global"}), flush=True)
        del m
    json.dump(rows, open(OUT / "results.json", "w"), indent=1)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default="bge-small,bge-base,embeddinggemma,qwen3-0.6b")
    evaluate(ap.parse_args().models.split(","))
