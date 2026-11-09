"""T-154 embedding bake-off on the pilot20 store: free local models, same corpus on the MSI GTX 1050 Ti and the HP.

Eval set: every graded p20 answer number whose quote (>= 25 normalised chars) is found verbatim in a page of the
same company known on or before the question's as_of -> (question, gold pages).
Corpus (fixed, shared by both machines): for each eval company, every page of a document that holds a gold page
plus 800 other pages drawn at random (seed 7); one window per page = its first 2,000 characters.  A question ranks
only its company's pages known by its as_of (point-in-time).  Metric: recall@5 / @20 and embedding speed.

    python tasks/v2/T-154_bakeoff.py eval                 # eval.json
    python tasks/v2/T-154_bakeoff.py corpus               # corpus.jsonl
    python tasks/v2/T-154_bakeoff.py torch <model>        # MSI: torch FP32 on CUDA (Pascal FP16 runs at 1:64)
    python tasks/v2/T-154_bakeoff.py export <model>       # MSI: ONNX file for the HP (dynamic batch/seq)
    python tasks/v2/T-154_bakeoff.py onnx <model> <ep>    # HP: onnxruntime, ep = cpu | qnn-htp | qnn-gpu
Models: bge-small | finbert | finmodernbert | bge-m3 | nemotron-1b (T154_FP16=1 on the 4 GB card).  Set T154_DIR to move the work folder.
"""
import glob
import json
import os
import random
import re
import sqlite3
import sys
import time
from pathlib import Path

DB = "D:/RealityEngine/p20/p20new.db"
OUT = Path(os.environ.get("T154_DIR", "D:/RealityEngine/p20/t154"))
MAXLEN = 512
MODELS = {  # name: (hf id, pooling, query prefix)
    "bge-small": ("BAAI/bge-small-en-v1.5", "cls", "Represent this sentence for searching relevant passages: "),
    "finbert": ("ProsusAI/finbert", "mean", ""),
    "finmodernbert": ("BatuhanECB/FinModernBERT-embed-large-v1", "mean", ""),
    "bge-m3": ("BAAI/bge-m3", "cls", ""),
    "nemotron-1b": ("nvidia/Nemotron-3-Embed-1B-BF16", "mean", "query: "),   # needs transformers>=5.2
}
DOC_PREFIX = {"nemotron-1b": "passage: "}


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def build_eval() -> None:
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    qs = {}
    for f in glob.glob("D:/RealityEngine/p20/answers/questions_*.json"):
        qs.update({q["qid"]: q for q in json.load(open(f, encoding="utf-8"))})
    pages = {}
    for sym, key, page, text, known in con.execute("SELECT symbol, doc_key, page, text, known_at FROM doc_page"):
        pages.setdefault(sym, []).append((key, page, norm(text), known or ""))
    items = []
    for f in glob.glob("D:/RealityEngine/p20/answers/[PQ]/*_answers.jsonl"):
        for line in open(f, encoding="utf-8"):
            a = json.loads(line)
            q = qs[a["qid"]]
            sym, as_of = a["qid"].rsplit("-", 1)[0], q["as_of"]
            gold = set()
            for n in a.get("numbers", []):
                qt = norm(n.get("quote", ""))
                if len(qt) < 25:
                    continue
                gold |= {f"{k}#{p}" for k, p, t, kn in pages.get(sym, []) if kn[:10] <= as_of and qt in t}
            if gold and len(gold) <= 20:
                items.append({"qid": a["qid"], "symbol": sym, "as_of": as_of, "question": q["question"],
                              "gold": sorted(gold)})
    OUT.mkdir(parents=True, exist_ok=True)
    json.dump(items, open(OUT / "eval.json", "w", encoding="utf-8"), indent=1)
    print(len(items), "questions with gold pages of", len(qs))


def build_corpus() -> None:
    items = json.load(open(OUT / "eval.json", encoding="utf-8"))
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    rng = random.Random(7)
    n = 0
    with open(OUT / "corpus.jsonl", "w", encoding="utf-8") as fh:
        for sym in sorted({i["symbol"] for i in items}):
            gold_docs = {g.split("#")[0] for i in items if i["symbol"] == sym for g in i["gold"]}
            rows = con.execute("SELECT doc_key, page, substr(text, 1, 2000), known_at FROM doc_page WHERE symbol=? "
                               "ORDER BY doc_key, page", (sym,)).fetchall()
            keep = [r for r in rows if r[0] in gold_docs]
            others = [r for r in rows if r[0] not in gold_docs]
            keep += rng.sample(others, min(800, len(others)))
            for k, p, t, kn in keep:
                fh.write(json.dumps({"sym": sym, "id": f"{k}#{p}", "known": (kn or "")[:10], "text": t or ""},
                                    ensure_ascii=False) + "\n")
            n += len(keep)
            print(sym, len(keep), "pages")
    print(n, "corpus pages")


def load_corpus():
    return [json.loads(line) for line in open(OUT / "corpus.jsonl", encoding="utf-8")]


def score(name: str, backend: str, embed, batch: int) -> None:
    import numpy as np
    _hf, _pool, qprefix = MODELS[name]
    items = json.load(open(OUT / "eval.json", encoding="utf-8"))
    corpus = load_corpus()
    t0 = time.time()
    dp = DOC_PREFIX.get(name, "")
    mat = np.concatenate([embed([dp + c["text"] for c in corpus[i:i + batch]])
                          for i in range(0, len(corpus), batch)])
    secs = time.time() - t0
    qv = np.concatenate([embed([qprefix + i["question"] for i in items[j:j + batch]])
                         for j in range(0, len(items), batch)])
    by_sym = {}
    for idx, c in enumerate(corpus):
        by_sym.setdefault(c["sym"], []).append(idx)
    hit5 = hit20 = 0
    rows = []
    for it, v in zip(items, qv):
        idxs = [i for i in by_sym[it["symbol"]] if corpus[i]["known"] <= it["as_of"]]
        sc = mat[idxs] @ v
        ranked = [corpus[idxs[i]]["id"] for i in np.argsort(-sc)]
        gold = set(it["gold"])
        r5, r20 = bool(gold & set(ranked[:5])), bool(gold & set(ranked[:20]))
        hit5 += r5
        hit20 += r20
        rows.append({"qid": it["qid"], "r5": r5, "r20": r20, "top5": ranked[:5]})
    res = {"model": name, "backend": backend, "questions": len(items), "pages": len(corpus),
           "embed_seconds": round(secs, 1), "pages_per_second": round(len(corpus) / secs, 1),
           "recall@5": round(hit5 / len(items), 3), "recall@20": round(hit20 / len(items), 3)}
    json.dump({"summary": res, "rows": rows}, open(OUT / f"run_{name}_{backend}.json", "w", encoding="utf-8"),
              indent=1)
    print(json.dumps(res), flush=True)


def pool_np(h, mask, pool):
    import numpy as np
    if pool == "cls":
        v = h[:, 0]
    else:
        m = mask[..., None].astype(h.dtype)
        v = (h * m).sum(1) / np.maximum(m.sum(1), 1e-9)
    return v / np.linalg.norm(v, axis=1, keepdims=True)


def run_torch(name: str) -> None:
    import torch
    from transformers import AutoModel, AutoTokenizer
    hf, pool, _ = MODELS[name]
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    tok = AutoTokenizer.from_pretrained(hf)
    dtype = torch.float16 if os.environ.get("T154_FP16") else torch.float32   # 1B does not fit 4 GB in FP32
    model = AutoModel.from_pretrained(hf, dtype=dtype).to(dev).eval()

    @torch.no_grad()
    def embed(texts):
        b = tok(texts, padding=True, truncation=True, max_length=MAXLEN, return_tensors="pt").to(dev)
        h = model(**b).last_hidden_state.float().cpu().numpy()
        return pool_np(h, b["attention_mask"].cpu().numpy(), pool)

    score(name, f"torch-{dev}-{'fp16' if dtype == torch.float16 else 'fp32'}", embed, 16)


def export(name: str) -> None:
    import torch
    from transformers import AutoModel, AutoTokenizer
    hf, _pool, _ = MODELS[name]
    tok = AutoTokenizer.from_pretrained(hf)
    model = AutoModel.from_pretrained(hf, dtype=torch.float32).eval()
    d = OUT / "onnx" / name
    d.mkdir(parents=True, exist_ok=True)
    tok.save_pretrained(d)
    b = tok(["a sample passage"] * 2, padding="max_length", max_length=MAXLEN, return_tensors="pt")
    names = ["input_ids", "attention_mask"] + (["token_type_ids"] if "token_type_ids" in b else [])

    class Wrap(torch.nn.Module):
        def __init__(self, m):
            super().__init__()
            self.m = m

        def forward(self, *args):
            return self.m(**dict(zip(names, args))).last_hidden_state

    axes = {n: {0: "batch", 1: "seq"} for n in names}
    axes["last_hidden_state"] = {0: "batch", 1: "seq"}
    torch.onnx.export(Wrap(model), tuple(b[n] for n in names), str(d / "model.onnx"), input_names=names,
                      output_names=["last_hidden_state"], dynamic_axes=axes, opset_version=17, dynamo=False)
    json.dump({"inputs": names}, open(d / "inputs.json", "w"))
    print(d)


def run_onnx(name: str, ep: str) -> None:
    import numpy as np
    import onnxruntime as ort
    from tokenizers import Tokenizer
    _hf, pool, _ = MODELS[name]
    d = OUT / "onnx" / name
    names = json.load(open(d / "inputs.json"))["inputs"]
    tok = Tokenizer.from_file(str(d / "tokenizer.json"))
    tok.enable_truncation(MAXLEN)
    static = ep.startswith("qnn")             # the NPU wants one fixed shape: pad every batch to 8 x 512
    tok.enable_padding(length=MAXLEN if static else None)
    so = ort.SessionOptions()
    if ep == "cpu":
        sess = ort.InferenceSession(str(d / "model.onnx"), so, providers=["CPUExecutionProvider"])
    else:   # onnxruntime-qnn 2.x is a plugin EP: register its library, then pick the NPU or GPU device
        import onnxruntime_qnn
        ort.register_execution_provider_library("QNNExecutionProvider", onnxruntime_qnn.get_library_path())
        want = "NPU" if ep == "qnn-htp" else "GPU"
        devs = [x for x in ort.get_ep_devices() if x.ep_name == "QNNExecutionProvider" and want in str(x.device.type)]
        print("qnn devices:", [str(x.device.type) for x in ort.get_ep_devices() if x.ep_name == "QNNExecutionProvider"],
              flush=True)
        opts = {"htp_performance_mode": "burst", "enable_htp_fp16_precision": "1"} if want == "NPU" else {}
        so.add_provider_for_devices(devs, opts)
        # the NPU needs a fixed-shape graph (T-154_npu_prep.py fixed / qdq); T154_ONNX_FILE picks which one
        sess = ort.InferenceSession(str(d / os.environ.get("T154_ONNX_FILE", "model.onnx")), so)
    print("providers in use:", sess.get_providers(), flush=True)
    batch = 8

    def embed(texts):
        n = len(texts)
        if static and n < batch:
            texts = texts + [""] * (batch - n)
        enc = tok.encode_batch(texts)
        feed = {"input_ids": np.array([e.ids for e in enc], dtype=np.int64),
                "attention_mask": np.array([e.attention_mask for e in enc], dtype=np.int64)}
        if "token_type_ids" in names:
            feed["token_type_ids"] = np.array([e.type_ids for e in enc], dtype=np.int64)
        h = sess.run(["last_hidden_state"], feed)[0]
        return pool_np(h, feed["attention_mask"], pool)[:n]

    score(name, f"onnx-{ep}" + os.environ.get("T154_TAG", ""), embed, batch)


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "eval":
        build_eval()
    elif cmd == "corpus":
        build_corpus()
    elif cmd == "torch":
        run_torch(sys.argv[2])
    elif cmd == "export":
        export(sys.argv[2])
    elif cmd == "onnx":
        run_onnx(sys.argv[2], sys.argv[3])
