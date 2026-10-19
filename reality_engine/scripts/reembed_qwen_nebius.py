"""Qwen3-Embedding-8B over Nebius Token Factory for the priority tiers (Shivam, 2026-10-20: pay ~$2 so transcripts,
macro / policy (PIB, Budget, RBI, Economic Survey ...) and decks are searchable now; the GPU EmbeddingGemma index and the
free Gemini quota are slower).

Retrieval test (embed_model_test, 51 analyst questions, 8,452 transcript chunks): hit@5 84.3% (Gemini-001 88.2%,
EmbeddingGemma 80.4%, bge-small 51.0%); 5.03M tokens for 8,452 chunks = $0.05; 47 chunks/s at 6 requests in flight.

Writes a NEW index in data/vector_index_qwen8b/ (layout as search/chunk_vector_index.py, but float16 to keep 4,096 dims
at ~3 GB): chunk_vectors.npy (N, 4096) float16, chunk_ids.npy sorted, chunk_index_meta.json, done.npy (resumable).
Rows = the chunks of tiers 0-2 in the Gemma plan (data/vector_index_gemma/chunk_ids.npy + tiers.npy, same tier rules).
Text embedded = the same fresh-header text as reembed_gemma (no instruction: Qwen3 puts the instruction on queries only;
the query side must prefix embed_model_test.QWEN_INSTRUCT). Spend guard: stops before --max-usd (tokens counted from
the API's usage field at $0.01/M).

    python -m reality_engine.scripts.reembed_qwen_nebius [--workers 6] [--max-usd 2.3] [--limit N]
    python -m reality_engine.scripts.reembed_qwen_nebius --status
"""
import argparse
import concurrent.futures as cf
import json
import sqlite3
import threading
import time
from pathlib import Path

import numpy as np
import requests

from reality_engine.scripts.reembed_gemma import DB, texts_for
from reality_engine.scripts.resource_watchdog import user_env

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "reality_engine" / "data"
PLAN = DATA / "vector_index_gemma"
OUT = DATA / "vector_index_qwen8b"
LOG = DATA / "logs" / "reembed_qwen_nebius.log"
URL = "https://api.tokenfactory.nebius.com/v1/embeddings"
MODEL, DIM, USD_PER_M = "Qwen/Qwen3-Embedding-8B", 4096, 0.01
TIERS = (0, 1, 2)
MAX_CHARS, BATCH_CHARS = 20_000, 100_000   # per text / per request (~25k tokens, under the 40,960 limit)
lock = threading.Lock()
RATE = {"429": 0}


def log(msg):
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}"
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def paths():
    return OUT / "chunk_vectors.npy", OUT / "chunk_ids.npy", OUT / "chunk_index_meta.json", OUT / "done.npy", \
        OUT / "state.json"


def make_plan():
    OUT.mkdir(parents=True, exist_ok=True)
    vp, ip, mp, dp, sp = paths()
    ids, tiers = np.load(PLAN / "chunk_ids.npy"), np.load(PLAN / "tiers.npy")
    keep = ids[np.isin(tiers, TIERS)]
    np.save(ip, keep)
    np.save(dp, np.zeros(len(keep), dtype=bool))
    v = np.lib.format.open_memmap(vp, mode="w+", dtype=np.float16, shape=(len(keep), DIM))
    del v
    sp.write_text(json.dumps({"tokens": 0}), encoding="utf-8")
    write_meta(len(keep), 0)
    log(f"plan: {len(keep):,} chunks (tiers {TIERS}) of {len(ids):,}")


def write_meta(rows, done, extra=None):
    _, _, mp, _, _ = paths()
    meta = {"rows": int(rows), "dim": DIM, "dtype": "float16", "model": MODEL, "provider": "nebius",
            "doc_prompt": "<fresh header>\\n<body> (no instruction)",
            "query_prompt": "embed_model_test.QWEN_INSTRUCT + question", "tiers": list(TIERS), "db_path": str(DB),
            "done": int(done), "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"), **(extra or {})}
    tmp = mp.with_suffix(".tmp")
    tmp.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    tmp.replace(mp)


def post(key, texts):
    last = ""
    for attempt in range(6):
        try:
            r = requests.post(URL, headers={"Authorization": f"Bearer {key}"},
                              json={"model": MODEL, "input": texts}, timeout=300)
        except requests.RequestException as e:
            time.sleep(10 * (attempt + 1)); last = str(e); continue
        if r.status_code == 200:
            j = r.json()
            vec = [e["embedding"] for e in sorted(j["data"], key=lambda e: e["index"])]
            return vec, (j.get("usage") or {}).get("prompt_tokens", 0) or 0
        last = f"HTTP {r.status_code} {r.text[:200]}"
        if r.status_code in (402, 403):           # out of credit / key refused: stop, do not retry
            raise RuntimeError(last)
        if r.status_code == 429:
            # tokens-per-minute quota (600k default; Nebius raises it after sustained use above 80%): wait, retry,
            # never give up (2026-10-20: 24 in flight crashed the run after 6 tries)
            with lock:
                RATE["429"] += 1
            time.sleep(20)
            return post(key, texts)
        if r.status_code == 400 and "context length" in r.text:
            # over 40,960 tokens in one request (number-heavy chunks run ~1-2 chars/token): split the batch in
            # halves; a single text that is still too long is cut to half its length and retried
            if len(texts) > 1:
                h = len(texts) // 2
                (a, ta), (b, tb) = post(key, texts[:h]), post(key, texts[h:])
                return a + b, ta + tb
            return post(key, [texts[0][:len(texts[0]) // 2]])
        time.sleep(10 * (attempt + 1))
    raise RuntimeError(last)


def run(workers, max_usd, limit, bs=32, block=1920):
    vp, ip, mp, dp, sp = paths()
    ids, done = np.load(ip), np.load(dp)
    vecs = np.load(vp, mmap_mode="r+")
    state = json.loads(sp.read_text(encoding="utf-8"))
    key = user_env()["NEBIUS_API_KEY"]
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=60)
    todo = np.flatnonzero(~done)
    if limit:
        todo = todo[:limit]
    log(f"start: done {int(done.sum()):,}/{len(ids):,}, todo {len(todo):,}, spent ${state['tokens'] * USD_PER_M / 1e6:.3f}")
    t0, n = time.time(), 0
    with cf.ThreadPoolExecutor(workers) as ex:
        for s in range(0, len(todo), block):
            if state["tokens"] * USD_PER_M / 1e6 >= max_usd:
                log(f"STOP: spend guard ${max_usd} reached"); break
            pos = todo[s:s + block]
            texts = texts_for(con, ids[pos])
            # 2026-10-20: a request over 40,960 tokens is refused (400): cap each text at MAX_CHARS (~5k tokens; most
            # chunks are ~2.4k chars) and pack batches by characters instead of a fixed count
            texts = [t[:MAX_CHARS] for t in texts]
            keep = [i for i, t in enumerate(texts) if t.strip()]
            parts, cur, size = [], [], 0
            for i in keep:
                if cur and (len(cur) >= bs or size + len(texts[i]) > BATCH_CHARS):
                    parts.append(cur); cur, size = [], 0
                cur.append(i); size += len(texts[i])
            if cur:
                parts.append(cur)
            futs = {ex.submit(post, key, [texts[i] for i in p]): p for p in parts}
            for f in cf.as_completed(futs):
                v, tok = f.result()
                p = futs[f]
                vecs[pos[p]] = np.asarray(v, dtype=np.float32).astype(np.float16)
                state["tokens"] += tok
            vecs.flush()
            done[pos] = True
            np.save(dp, done)                       # after the vectors are flushed
            sp.write_text(json.dumps(state), encoding="utf-8")
            n += len(pos)
            rate = n / (time.time() - t0)
            left = int((~done).sum())
            write_meta(len(ids), int(done.sum()), {"rate_per_s": round(rate, 1), "tokens": state["tokens"]})
            log(f"{n:,}/{len(todo):,} this run, {rate:.1f}/s; done {int(done.sum()):,}, left {left:,} "
                f"(~{left / max(rate, 0.1) / 60:.0f} min); spent ${state['tokens'] * USD_PER_M / 1e6:.3f}; 429s {RATE['429']}")
    log(f"RUN_END done {int(done.sum()):,}/{len(ids):,}, tokens {state['tokens']:,}")


def status():
    vp, ip, mp, dp, sp = paths()
    print(json.loads(mp.read_text(encoding="utf-8")))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--block", type=int, default=1920, help="chunks read and flushed per step; bigger keeps more requests in flight")
    ap.add_argument("--max-usd", type=float, default=2.3)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--status", action="store_true")
    a = ap.parse_args()
    if not paths()[1].exists():
        make_plan()
    if a.status:
        return status()
    run(a.workers, a.max_usd, a.limit, block=a.block)


if __name__ == "__main__":
    main()
