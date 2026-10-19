"""Re-embed every document chunk with EmbeddingGemma-300M (Shivam approved 2026-10-19).

Why: on 51 paraphrased analyst questions over our own transcript chunks EmbeddingGemma found the right chunk in the
top 5 for 80% vs bge-small 51% (scripts/embed_model_test.py, 2026-10-18); production chunks (~550 tokens) also overflow
bge's 512-token window, and the old vectors embed the crawl date written in the chunk header (dates since repaired).

Writes a NEW index in data/vector_index_gemma/, same file layout as search/chunk_vector_index.py (chunk_vectors.npy
(N, 768) float32, chunk_ids.npy sorted, chunk_index_meta.json) so ChunkVectorIndex can load it with index_dir=...;
the live bge index (data/vector_index/) and document_chunks are never touched. Readers switch only after the retrieval
check (--check) beats bge-small.

Order of work (priority tiers, then chunk_id): concall transcripts, macro / policy (Budget, RBI, PIB, Economic Survey,
PRS ...), decks, then annual reports, offer documents, everything else. Row positions follow sorted chunk_id, so the
index is usable at any point (rows not yet embedded are zero and score 0); done.npy marks finished rows (resumable).

Text embedded: 'title: none | text: ' + a fresh header built from the current (repaired) metadata + the chunk body
with its stored '[Metadata: ...]' header removed. Same prompt format as the 80% test run.

GPU: DirectML, batches packed to TOKEN_BUDGET padded tokens (~1.6 s per call; batch 16 tripped a Windows GPU reset
on 2026-10-18). Do not run next to another GPU embedder.

    python -m reality_engine.scripts.reembed_gemma [--limit N] [--tiers 0,1,2]   # embed (resumable)
    python -m reality_engine.scripts.reembed_gemma --status
    python -m reality_engine.scripts.reembed_gemma --plan-new     # append chunks created after the plan
"""
import argparse
import json
import re
import sqlite3
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "reality_engine" / "data"
DB = DATA / "equity_intelligence.db"
OUT = DATA / "vector_index_gemma"
DIM = 768
HEADER = re.compile(r"^\s*\[Metadata:[^\]]*\]\s*")
LOG = DATA / "logs" / "reembed_gemma.log"


def tier(source_type):
    s = (source_type or "").upper()
    if "CONCALL" in s or "TRANSCRIPT" in s:
        return 0
    if any(k in s for k in ("BUDGET", "RBI", "PIB", "ECONOMIC_SURVEY", "PRS", "MACRO", "POLICY", "SEBI", "MPC")):
        return 1
    if "PRESENTATION" in s or "DECK" in s or "INVESTOR" in s:
        return 2
    if "ANNUAL" in s:
        return 3
    if "OFFER" in s or "DRHP" in s or "RHP" in s:
        return 4
    return 5


def log(msg):
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}"
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def paths():
    return OUT / "chunk_vectors.npy", OUT / "chunk_ids.npy", OUT / "chunk_index_meta.json", OUT / "done.npy", \
        OUT / "tiers.npy"


def make_plan():
    """Sorted chunk_ids + their tier, and empty vector / done files. Only when no plan exists."""
    OUT.mkdir(parents=True, exist_ok=True)
    vp, ip, mp, dp, tp = paths()
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    st = dict(con.execute("SELECT doc_id, source_type FROM raw_documents"))
    ids, tiers = [], []
    for cid, did in con.execute("SELECT chunk_id, doc_id FROM document_chunks ORDER BY chunk_id"):
        ids.append(cid)
        tiers.append(tier(st.get(did)))
    ids = np.asarray(ids, dtype=np.int64)
    np.save(ip, ids)
    np.save(tp, np.asarray(tiers, dtype=np.int8))
    np.save(dp, np.zeros(len(ids), dtype=bool))
    v = np.lib.format.open_memmap(vp, mode="w+", dtype=np.float32, shape=(len(ids), DIM))
    del v
    write_meta(len(ids), 0)
    log(f"plan: {len(ids):,} chunks; per tier {np.bincount(np.asarray(tiers), minlength=6).tolist()}")


def write_meta(rows, done, extra=None):
    _, _, mp, _, _ = paths()
    meta = {"rows": int(rows), "dim": DIM, "dtype": "float32", "model": "embeddinggemma-300m",
            "prompt": "title: none | text: <fresh header>\\n<body>", "db_path": str(DB), "done": int(done),
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"), **(extra or {})}
    tmp = mp.with_suffix(".tmp")
    tmp.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    tmp.replace(mp)


def extend_plan():
    """Append chunks created after the plan (chunk_id is AUTOINCREMENT, so appending keeps the ids sorted)."""
    vp, ip, mp, dp, tp = paths()
    ids, tiers, done = np.load(ip), np.load(tp), np.load(dp)
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    new = con.execute("SELECT dc.chunk_id, rd.source_type FROM document_chunks dc LEFT JOIN raw_documents rd "
                      "ON rd.doc_id = dc.doc_id WHERE dc.chunk_id > ? ORDER BY dc.chunk_id", (int(ids[-1]),)).fetchall()
    if not new:
        log("plan-new: nothing to add")
        return
    old = np.load(vp, mmap_mode="r")
    tmp = OUT / "chunk_vectors.grow.npy"
    v = np.lib.format.open_memmap(tmp, mode="w+", dtype=np.float32, shape=(len(ids) + len(new), DIM))
    for s in range(0, len(ids), 200_000):
        e = min(s + 200_000, len(ids))
        v[s:e] = old[s:e]
    v.flush()
    del v, old
    tmp.replace(vp)
    np.save(ip, np.concatenate([ids, np.asarray([r[0] for r in new], dtype=np.int64)]))
    np.save(tp, np.concatenate([tiers, np.asarray([tier(r[1]) for r in new], dtype=np.int8)]))
    np.save(dp, np.concatenate([done, np.zeros(len(new), dtype=bool)]))
    write_meta(len(ids) + len(new), int(done.sum()))
    log(f"plan-new: added {len(new):,} chunks")


def texts_for(con, cids):
    q = ("SELECT dc.chunk_id, dc.content, dc.symbol, dc.fiscal_period, COALESCE(rd.published_date, dc.published_date), "
         "rd.source_type FROM document_chunks dc LEFT JOIN raw_documents rd ON rd.doc_id = dc.doc_id "
         f"WHERE dc.chunk_id IN ({','.join('?' * len(cids))})")
    by = {}
    for cid, content, sym, fy, d, st in con.execute(q, [int(c) for c in cids]):
        body = HEADER.sub("", content or "", count=1)
        by[cid] = f"[Metadata: Symbol: {sym or ''} | FY: {fy or ''} | Doc: {st or ''} | Date: {(d or '')[:10]}]\n{body}"
    return [by.get(int(c), "") for c in cids]


TOKEN_BUDGET = 5600   # padded tokens per DirectML call: batch 8 x ~700 tokens = ~1.6 s; batch 12 took 2.2 s (Windows
                      # resets the GPU on calls over ~2 s). Measured 2026-10-19: 3.8/s at batch 4 -> 5.1/s at this budget.


DUTY = 1.0   # fraction of wall time the GPU computes (--duty). 2026-10-19: two power cuts ~30 min after full-load
             # re-embed starts (05:27 -> 05:58, 14:48 -> ~15:25); the UPS trips on sustained GPU draw.


def embed_budget(model, texts):
    """Embed with batches packed to TOKEN_BUDGET padded tokens (long chunks get smaller batches). Same vectors as
    Model.embed (max |diff| 2e-7 between batch sizes)."""
    import numpy as np
    lens = [min(len(model.tok.encode(model.fmt(t, False)).ids), model.max_len) for t in texts]
    order = sorted(range(len(texts)), key=lambda i: lens[i])
    res, batch = [None] * len(texts), []
    for i in order + [None]:
        if i is not None and (not batch or (len(batch) + 1) * lens[i] <= TOKEN_BUDGET):
            batch.append(i)
            continue
        if batch:
            t0 = time.perf_counter()
            for j, v in zip(batch, model._batch([model.fmt(texts[k], False) for k in batch])):
                res[j] = v
            if DUTY < 1.0:
                time.sleep((time.perf_counter() - t0) * (1 / DUTY - 1))
        batch = [i] if i is not None else []
    return np.vstack(res).astype(np.float32)


def run(limit, tiers_wanted, chunk=256):
    from reality_engine.scripts.embed_model_test import Model
    vp, ip, mp, dp, tp = paths()
    ids, tiers = np.load(ip), np.load(tp)
    done = np.load(dp)
    vecs = np.load(vp, mmap_mode="r+")
    model = Model("embeddinggemma")
    log(f"model on {model.provider}; done {int(done.sum()):,}/{len(ids):,}")
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=60)
    todo = [p for t in tiers_wanted for p in np.flatnonzero((tiers == t) & ~done)]
    if limit:
        todo = todo[:limit]
    t0, n = time.time(), 0
    for s in range(0, len(todo), chunk):
        pos = np.asarray(todo[s:s + chunk])
        texts = texts_for(con, ids[pos])
        keep = [i for i, t in enumerate(texts) if t.strip()]
        if keep:
            v = embed_budget(model, [texts[i] for i in keep])
            vecs[pos[keep]] = v
        vecs.flush()
        done[pos] = True
        np.save(dp, done)          # after the vectors are flushed: a kill never marks unwritten rows done
        n += len(pos)
        if (s // chunk) % 20 == 0 or s + chunk >= len(todo):
            rate = n / (time.time() - t0)
            left = int((~done).sum())
            write_meta(len(ids), int(done.sum()), {"rate_per_s": round(rate, 2)})
            log(f"{n:,}/{len(todo):,} this run, {rate:.1f}/s; total done {int(done.sum()):,}, left {left:,} "
                f"(~{left / max(rate, 0.1) / 3600:.1f} h)")
    write_meta(len(ids), int(done.sum()))
    log(f"RUN_COMPLETE embedded {n:,}")


def status():
    vp, ip, mp, dp, tp = paths()
    ids, tiers, done = np.load(ip), np.load(tp), np.load(dp)
    for t in range(6):
        m = tiers == t
        print(f"tier {t}: {int((done & m).sum()):,}/{int(m.sum()):,}")
    print(json.loads(mp.read_text(encoding="utf-8")))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--tiers", default="0,1,2,3,4,5")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--plan-new", action="store_true", dest="plan_new")
    ap.add_argument("--duty", type=float, default=1.0, help="GPU duty cycle 0.1-1.0 (rest between calls)")
    a = ap.parse_args()
    if not paths()[1].exists():
        make_plan()
    if a.status:
        return status()
    if a.plan_new:
        return extend_plan()
    global DUTY
    DUTY = max(0.1, min(1.0, a.duty))
    run(a.limit, [int(t) for t in a.tiers.split(",")])


if __name__ == "__main__":
    main()
