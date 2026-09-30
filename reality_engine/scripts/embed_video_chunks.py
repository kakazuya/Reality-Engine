"""Embed YouTube/Telegram video chunks that have no embedding yet (bge-small-en-v1.5, 384-d, DirectML on the RX 6700 XT,
CPU fallback) and store them in document_chunks.embedding in the same JSON-list format as every other chunk.
The dense index is rebuilt separately (build_chunk_vector_index)."""
import json, sqlite3, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from reality_engine.ingestion.onnx_embedder import OnnxEmbedder

DB = Path(__file__).resolve().parents[2] / "reality_engine/data/equity_intelligence.db"
conn = sqlite3.connect(DB, timeout=600)
rows = conn.execute("select chunk_id, content from document_chunks where doc_id in (select doc_id from raw_documents "
                    "where sha256_hash like 'yt:%') and (embedding is null or embedding='') order by chunk_id").fetchall()
print(f"{len(rows)} chunks to embed", flush=True)
emb = OnnxEmbedder()
print("provider:", emb.provider, flush=True)
t0, done = time.time(), 0
for i in range(0, len(rows), 32):
    batch = rows[i:i + 32]
    vecs = emb.embed_many([r[1][-2000:] for r in batch])
    if not vecs:
        print("embedder unavailable - aborting", flush=True); sys.exit(2)
    with conn:
        conn.executemany("update document_chunks set embedding=? where chunk_id=?",
                         [(json.dumps([float(x) for x in v]), r[0]) for v, r in zip(vecs, batch)])
    done += len(batch)
    if (i // 32) % 20 == 0:
        print(f"{done}/{len(rows)} {time.time()-t0:.0f}s", flush=True)
print("embedded", done, flush=True)
