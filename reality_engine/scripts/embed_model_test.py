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

    def embed(self, texts, query=False, bs=None):
        # small batches for the big models: a long DirectML call trips Windows TDR (device suspended, 2026-10-18)
        bs = bs or (16 if self.name.startswith("bge") else 4)
        order = np.argsort([len(t) for t in texts])
        out = np.zeros((len(texts), 0), dtype=np.float32)
        res = [None] * len(texts)
        for s in range(0, len(texts), bs):
            idx = order[s:s + bs]
            vs = self._batch([self.fmt(texts[i], query) for i in idx])
            for i, v in zip(idx, vs):
                res[i] = v
        return np.vstack(res).astype(np.float32)


class GeminiAPI:
    """Google AI Studio embedding models over the API (2026-10-19, Shivam: compare against the local GPU EmbeddingGemma).
    batchEmbedContents, 40 texts per request, task type RETRIEVAL_DOCUMENT / RETRIEVAL_QUERY, keys used in turn; a 429
    moves to the next key. Input is truncated by the API at the model's token limit (001: 2,048, 2: 8,192)."""
    API = {"gemini-embedding-001": "gemini-embedding-001", "gemini-embedding-2": "gemini-embedding-2"}

    def __init__(self, name):
        from reality_engine.scripts import ingest_annual_reports as ar
        env = ar.user_env()
        self.name, self.model, self.provider = name, self.API[name], "google-api"
        self.keys = [env[k] for k in ar.gemini_keys(env)]
        self.k = 0
        self.calls, self.r429 = 0, 0

    def embed(self, texts, query=False, bs=40):   # 100 real chunks (~28k+ tokens) get 429 on a fresh key; 50 pass
        import requests
        out = []
        for s in range(0, len(texts), bs):
            reqs = [{"model": f"models/{self.model}", "content": {"parts": [{"text": t}]},
                     "taskType": "RETRIEVAL_QUERY" if query else "RETRIEVAL_DOCUMENT"} for t in texts[s:s + bs]]
            for attempt in range(len(self.keys) * 2):
                key = self.keys[self.k % len(self.keys)]
                r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:batchEmbedContents",
                                  headers={"x-goog-api-key": key}, json={"requests": reqs}, timeout=300)
                self.calls += 1
                if r.status_code == 200:
                    out += [e["values"] for e in r.json()["embeddings"]]
                    self.k += 1
                    break
                if r.status_code == 429:
                    self.r429 += 1; self.k += 1; time.sleep(1); continue
                raise RuntimeError(f"HTTP {r.status_code}: {r.text[:300]}")
            else:
                raise RuntimeError("every key refused (429)")
        v = np.array(out, dtype=np.float32)
        return v / np.linalg.norm(v, axis=1, keepdims=True)


class OpenAIEmbed:
    """OpenAI-compatible /embeddings endpoint (2026-10-19: Qwen3-Embedding-8B on Nebius Token Factory, $0.01/M tokens;
    Shivam's $1 trial). Qwen3 needs the instruction on queries only, as in the local 0.6B test."""
    API = {"qwen3-8b-nebius": ("NEBIUS_API_KEY", "Qwen/Qwen3-Embedding-8B",
                               ["https://api.tokenfactory.nebius.com/v1", "https://api.studio.nebius.com/v1"]),
           # DeepInfra (2026-10-20): the same EmbeddingGemma-300m as the GPU re-embed at $0.002/M, and EmbeddingGemma 2
           # (740M, $0.02/M). Prompts are sent by us (PROMPTS), as in the local test.
           "embeddinggemma-deepinfra": ("DEEPINFRA_API_KEY", "google/embeddinggemma-300m",
                                        ["https://api.deepinfra.com/v1/openai"]),
           "embeddinggemma2-deepinfra": ("DEEPINFRA_API_KEY", "google/embeddinggemma-2",
                                         ["https://api.deepinfra.com/v1/openai"])}
    # (document prefix, query prefix); Qwen: instruction on queries only
    PROMPTS = {"qwen3-8b-nebius": ("", QWEN_INSTRUCT),
               "embeddinggemma-deepinfra": ("title: none | text: ", "task: search result | query: "),
               "embeddinggemma2-deepinfra": ("title: none | text: ", "task: search result | query: ")}
    PRICE = {"qwen3-8b-nebius": 0.01, "embeddinggemma-deepinfra": 0.002, "embeddinggemma2-deepinfra": 0.02}
    # round 2 on DeepInfra (2026-10-20, Shivam: try the other long-context models at similar cost); 512-token models
    # skipped (our chunks average ~600 tokens). name: (repo, $/M, doc prefix, query prefix)
    _DI = "https://api.deepinfra.com/v1/openai"
    _ICL = ("<instruct>Given an analyst's question about an Indian listed company, retrieve the earnings-call "
            "transcript passage that answers it\n<query>")
    for _n, (_repo, _usd, _d, _q) in {
            "nemotron3-8b-di": ("nvidia/Nemotron-3-Embed-8B", 0.035, "passage: ", "query: "),
            "nemotron3-1b-di": ("nvidia/Nemotron-3-Embed-1B-BF16", 0.015, "passage: ", "query: "),
            "nemotron3-1b-fp4-di": ("nvidia/Nemotron-3-Embed-1B-NVFP4", 0.01, "passage: ", "query: "),   # AR candidate
            "nemotron-vl-1b-di": ("nvidia/llama-nemotron-embed-vl-1b-v2", 0.01, "passage: ", "query: "),
            "qwen3-4b-di": ("Qwen/Qwen3-Embedding-4B", 0.02, "", QWEN_INSTRUCT),
            "qwen3-0.6b-di": ("Qwen/Qwen3-Embedding-0.6B", 0.01, "", QWEN_INSTRUCT),
            "bge-m3-di": ("BAAI/bge-m3", 0.01, "", ""),
            "bge-en-icl-di": ("BAAI/bge-en-icl", 0.01, "", _ICL)}.items():
        API[_n] = ("DEEPINFRA_API_KEY", _repo, [_DI])
        PROMPTS[_n] = (_d, _q)
        PRICE[_n] = _usd

    def __init__(self, name):
        from reality_engine.scripts.resource_watchdog import user_env
        kenv, self.model, self.bases = self.API[name]
        self.key = user_env()[kenv]
        self.name, self.provider, self.calls, self.r429, self.tokens = name, "api:" + kenv, 0, 0, 0
        self.base = None

    def _post(self, texts):
        import requests
        for base in ([self.base] if self.base else self.bases):
            r = requests.post(f"{base}/embeddings", headers={"Authorization": f"Bearer {self.key}"},
                              json={"model": self.model, "input": texts}, timeout=300)
            self.calls += 1
            if r.status_code == 200:
                self.base = base
                self.tokens += (r.json().get("usage") or {}).get("prompt_tokens", 0) or 0
                return [e["embedding"] for e in sorted(r.json()["data"], key=lambda e: e["index"])]
            if r.status_code == 429:
                self.r429 += 1; time.sleep(10); return self._post(texts)
            last = f"{base}: HTTP {r.status_code} {r.text[:200]}"
        raise RuntimeError(last)

    def embed(self, texts, query=False, bs=32, workers=6):
        # parallel batches (Nebius default limit 600k tokens/min, 10k req/min; 32 chunks ~ 17.5k tokens, ~12 s each:
        # one at a time was ~90k tokens/min, 6 in flight ~ 500k)
        import concurrent.futures as cf
        texts = [self.PROMPTS[self.name][1 if query else 0] + t for t in texts]
        parts = list(range(0, len(texts), bs))
        res = {}
        with cf.ThreadPoolExecutor(workers) as ex:
            futs = {ex.submit(self._post, texts[s:s + bs]): s for s in parts}
            for n, f in enumerate(cf.as_completed(futs), 1):
                res[futs[f]] = f.result()
                if n % 25 == 0:
                    print(f"  {self.name} {n}/{len(parts)} batches, tokens so far {self.tokens:,}", flush=True)
        out = [v for s in parts for v in res[s]]
        v = np.array(out, dtype=np.float32)
        return v / np.linalg.norm(v, axis=1, keepdims=True)


def evaluate(names):
    corpus = json.load(open(OUT / "corpus.json", encoding="utf-8"))
    qs = json.load(open(OUT / "questions.json", encoding="utf-8"))
    gold = {g["chunk_id"]: g for g in json.load(open(OUT / "gold_chunks.json", encoding="utf-8"))}
    ids = [c["chunk_id"] for c in corpus]; pos = {c: i for i, c in enumerate(ids)}
    syms = np.array([c["symbol"] for c in corpus])
    rows = []
    for name in names:
        cache = OUT / f"emb_{name}.npy"
        qcache = OUT / f"qemb_{name}.npy"
        if qcache.exists():   # computed elsewhere (Colab: colab_embed_test.py writes emb_/qemb_/meta_<name>)
            meta = json.load(open(OUT / f"meta_{name}.json")) if (OUT / f"meta_{name}.json").exists() else {}
            m = type("Precomputed", (), {"provider": "colab:" + meta.get("gpu", "?")})()
            E, Q, rate = np.load(cache), np.load(qcache), meta.get("chunks_per_s")
        else:
            m = (GeminiAPI(name) if name in GeminiAPI.API else OpenAIEmbed(name) if name in OpenAIEmbed.API
                 else Model(name))
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
        if isinstance(m, (GeminiAPI, OpenAIEmbed)):
            r["api_calls"], r["api_429"] = m.calls, m.r429
        if isinstance(m, OpenAIEmbed):
            r["tokens"], r["cost_usd"] = m.tokens, round(m.tokens * OpenAIEmbed.PRICE[name] / 1e6, 4)
        for scope, ranks in res.items():
            a = np.array(ranks)
            r[scope] = {"hit@1": round((a <= 1).mean(), 3), "hit@5": round((a <= 5).mean(), 3),
                        "hit@10": round((a <= 10).mean(), 3), "mrr": round((1 / a).mean(), 3)}
        r["ranks_global"] = res["global"]
        rows.append(r)
        print(json.dumps({k: v for k, v in r.items() if k != "ranks_global"}), flush=True)
        del m
    # merge by model name: a run of some models no longer drops the others' stored results
    old = json.load(open(OUT / "results.json")) if (OUT / "results.json").exists() else []
    keep = {r["model"]: r for r in old}
    keep.update({r["model"]: r for r in rows})
    json.dump(list(keep.values()), open(OUT / "results.json", "w"), indent=1)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default="bge-small,bge-base,embeddinggemma,qwen3-0.6b")
    evaluate(ap.parse_args().models.split(","))
