"""Retrieval quality harness (C2): score a chunking x retriever on recall@k / MRR.

The labelled set is ``tasks/optimizations/learn/quality_set_v1.jsonl``.  Gold is
a character span in the document's *normalised* text (whitespace collapsed),
never a chunk id, so the old chunking and chunker-v2 chunks are scored on the
same passages: a hit is any retrieved chunk whose span overlaps the gold span
inside the same document.

Corpus scope: both chunkings are read from one pilot database (``--db``) that
holds the old chunks of the pilot documents and the v2 chunks of the same
documents.  Retrievers therefore search the same document set, which is what
makes "old vs v2" a like-for-like comparison.

Usage::

    python -m reality_engine.scripts.eval_retrieval --chunks old --retriever fts
    python -m reality_engine.scripts.eval_retrieval --chunks v2  --retriever fts
    python -m reality_engine.scripts.eval_retrieval --chunks old --retriever seed_dense
    python -m reality_engine.scripts.eval_retrieval --chunks old --retriever local:<index-dir>

``seed_dense`` is the free G4 path (``plugins/reality-data/server/dense_free.py``):
the stored Nemotron vectors of the top FTS seeds are averaged into the query
vector and used for a cosine scan.  It only exists for old chunks, which have
vectors; on v2 it prints the token count and the cost formula instead, because
new vectors are a paid call and nothing here calls a paid API.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for extra in (ROOT, ROOT / "plugins" / "reality-data" / "server"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

DEFAULT_DB = ROOT / ".tmp" / "c1" / "chunks_v2_pilot.db"
DEFAULT_SET = ROOT / "tasks" / "optimizations" / "learn" / "quality_set_v2.jsonl"
STOPWORDS = set("""a an and are as at be been but by can could did do does for from had has have how in
into is it its may might more most no not of on or our over said say said's than that the their them then
there these they this those to under was were what when where which while who why will with would you your
me my we us i he she his her""".split())
TOPK = 10


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------

def load_quality_set(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def open_db(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def fts_query(question: str) -> str:
    """OR of the question's content terms, each quoted (never a syntax error)."""
    terms = [t for t in re.findall(r"[A-Za-z][A-Za-z0-9]+", question.lower())
             if t not in STOPWORDS and len(t) > 2]
    seen: list[str] = []
    for term in terms:
        if term not in seen:
            seen.append(term)
    return " OR ".join(f'"{t}"' for t in seen) or '""'


# ---------------------------------------------------------------------------
# Chunk stores
# ---------------------------------------------------------------------------

class Store:
    """One chunking's chunks, with their span in normalised document space."""

    def __init__(self, conn: sqlite3.Connection, which: str):
        self.which = which
        if which == "old":
            self.table, self.fts = "chunks_old", "chunks_old_fts"
        else:
            self.table, self.fts = "chunks_v2", "chunks_v2_fts"
        self.conn = conn
        self.by_chunk: dict[str, dict] = {}
        self.doc_ids: set[int] = set()
        self.docs_per_type: dict[str, set[int]] = {}
        self.tokens = 0
        self.header_tokens = 0
        self.per_type: dict[str, dict] = {}
        columns = {row[1] for row in conn.execute(f"pragma table_info({self.table})")}
        source = "source_chunk_id" if "source_chunk_id" in columns else "-1 as source_chunk_id"
        for row in conn.execute(
                f"select chunk_id, doc_id, doc_type, char_len, norm_start, norm_end, "
                f"       length(header) as header_len, {source} from {self.table} c"):
            key = str(row["chunk_id"])
            self.by_chunk[key] = {"chunk_id": key, "doc_id": row["doc_id"],
                                  "doc_type": row["doc_type"],
                                  "norm_start": row["norm_start"],
                                  "norm_end": row["norm_end"],
                                  "source_chunk_id": row["source_chunk_id"]}
            self.doc_ids.add(row["doc_id"])
            self.docs_per_type.setdefault(row["doc_type"], set()).add(row["doc_id"])
            self.tokens += int(row["char_len"] or 0) / 4.0
            self.header_tokens += int(row["header_len"] or 0) / 4.0
            bucket = self.per_type.setdefault(row["doc_type"], {"chunks": 0, "chars": 0,
                                                                "header_chars": 0})
            bucket["chunks"] += 1
            bucket["chars"] += int(row["char_len"] or 0)
            bucket["header_chars"] += int(row["header_len"] or 0)
        for bucket in self.per_type.values():
            bucket["tokens"] = bucket["chars"] / 4.0
            bucket["header_tokens"] = bucket["header_chars"] / 4.0


def chunk_ids_for(store: Store) -> set[int]:
    return {int(c["source_chunk_id"]) for c in store.by_chunk.values()
            if int(c["source_chunk_id"]) >= 0}


# ---------------------------------------------------------------------------
# Retrievers
# ---------------------------------------------------------------------------

def retrieve_fts(store: Store, question: str, doc_ids: set[int], k: int = TOPK,
                 variant: str = "header") -> list[dict]:
    """FTS5 bm25 over the chunking's own FTS table.

    ``variant='body'`` searches a body-only FTS table when one exists, which
    isolates the header's contribution from the chunk boundaries'.
    """
    match = fts_query(question)
    if not match:
        return []
    table = "chunks_v2_fts"
    if store.which != "old" and variant == "body":
        present = {row[0] for row in store.conn.execute(
            "select name from sqlite_master where type='table'")}
        table = "chunks_v2_body_fts" if "chunks_v2_body_fts" in present else table
    try:
        if store.which == "old":
            rows = store.conn.execute(
                "select cast(f.chunk_id as integer) as chunk_id, c.doc_id, c.norm_start, c.norm_end "
                "from chunks_old_fts f join chunks_old c "
                "  on c.chunk_id = cast(f.chunk_id as integer) "
                "where chunks_old_fts match ? order by bm25(chunks_old_fts) limit ?",
                (match, k * 5)).fetchall()
        else:
            rows = store.conn.execute(
                f"select cast(f.chunk_id as integer) as chunk_id, c.doc_id, c.norm_start, c.norm_end "
                f"from {table} f join chunks_v2 c on c.chunk_id = f.chunk_id "
                f"where {table} match ? order by bm25({table}) limit ?",
                (match, k * 5)).fetchall()
    except sqlite3.OperationalError:
        return []
    hits = [dict(row) for row in rows if row["doc_id"] in doc_ids]
    return hits[:k]


def retrieve_seed_dense(store: Store, question: str, k: int = TOPK) -> list[dict]:
    """G4 free path: average the stored vectors of the FTS seeds, cosine scan.

    The seed vector needs the *production* ``document_chunks.chunk_id`` values
    (the only ids the paid index was built over), not the pilot DB's own ids.
    """
    import dense_free

    seeds = []
    for hit in retrieve_fts(store, question, store.doc_ids, k=5):
        chunk = store.by_chunk.get(str(hit["chunk_id"]))
        if chunk and int(chunk["source_chunk_id"]) >= 0:
            seeds.append(int(chunk["source_chunk_id"]))
    if not seeds:
        return []
    allowed = sorted(chunk_ids_for(store))
    hits = dense_free.seed_search(question, "vector_index_nemotron8b", seeds,
                                  top_k=k, allow_ids=allowed)
    by_source = {int(c["source_chunk_id"]): c for c in store.by_chunk.values()
                 if int(c["source_chunk_id"]) >= 0}
    out = []
    for hit in hits:
        chunk = by_source.get(int(hit["chunk_id"]))
        if chunk is not None:
            out.append({"chunk_id": chunk["chunk_id"], "doc_id": chunk["doc_id"],
                        "norm_start": chunk["norm_start"], "norm_end": chunk["norm_end"]})
    return out[:k]


def retrieve_local(store: Store, question: str, index_dir: Path, k: int = TOPK) -> list[dict]:
    """Local ONNX embedder against ``<index-dir>`` (bge-small prior art path)."""
    import numpy as np

    import dense_free
    from reality_engine.ingestion.onnx_embedder import onnx_embedder

    vector = dense_free.local_query_vector(onnx_embedder, question)
    if vector is None:
        return []
    ids = np.load(index_dir / "chunk_ids.npy")
    vectors = np.load(index_dir / "chunk_vectors.npy", mmap_mode="r")
    allowed = chunk_ids_for(store)
    wanted = [i for i, cid in enumerate(ids) if int(cid) in allowed]
    if not wanted:
        return []
    matrix = np.asarray(vectors[wanted], dtype=np.float32)
    scores = matrix @ np.asarray(vector, dtype=np.float32).reshape(-1)
    order = np.argsort(-scores)[:k]
    by_source = {int(c["source_chunk_id"]): c for c in store.by_chunk.values()
                 if int(c["source_chunk_id"]) >= 0}
    out = []
    for row in order:
        chunk = by_source.get(int(ids[wanted[int(row)]]))
        if chunk is not None:
            out.append({"chunk_id": chunk["chunk_id"], "doc_id": chunk["doc_id"],
                        "norm_start": chunk["norm_start"], "norm_end": chunk["norm_end"]})
    return out


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def first_hit_rank(hits: list[dict], gold: dict) -> int | None:
    for rank, hit in enumerate(hits, start=1):
        if int(hit["doc_id"]) != int(gold["doc_id"]):
            continue
        start, end = int(hit["norm_start"]), int(hit["norm_end"])
        if start < 0:
            continue
        if start < gold["span_end"] and gold["span_start"] < end:
            return rank
    return None


def score(rows: list[dict], ranks: list[int | None]) -> dict:
    out = {"n": len(rows),
           "recall@1": _rate(ranks, 1), "recall@5": _rate(ranks, 5),
           "recall@10": _rate(ranks, 10),
           "mrr": round(sum(1.0 / r for r in ranks if r) / len(ranks), 4) if ranks else 0.0}
    return out


def _rate(ranks: list[int | None], k: int) -> float:
    if not ranks:
        return 0.0
    return round(sum(1 for r in ranks if r and r <= k) / len(ranks), 4)


def verify_spans(conn: sqlite3.Connection, rows: list[dict]) -> tuple[int, list[str]]:
    """Check every gold span really holds its ``answer_text``."""
    cache: dict[int, str] = {}
    bad: list[str] = []
    for row in rows:
        doc_id = int(row["doc_id"])
        if doc_id not in cache:
            got = conn.execute("select body from docs where doc_id = ?", (doc_id,)).fetchone()
            text = re.sub(r"\s+", " ", got["body"]).strip() if got else ""
            cache[doc_id] = text
        text = cache[doc_id]
        span = text[row["span_start"]:row["span_end"]]
        if span != row["answer_text"]:
            bad.append(row["qid"])
    return len(rows) - len(bad), bad


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--chunks", choices=("old", "v2"), default="v2")
    ap.add_argument("--retriever", default="fts")
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument("--set", dest="set_path", default=str(DEFAULT_SET))
    ap.add_argument("--out", default="")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--price-per-m", type=float, default=0.035,
                    help="USD per million tokens for the v2 cost estimate")
    ap.add_argument("--fts-variant", choices=("header", "body"), default="header",
                    help="v2 only: index the header with the body, or the body alone")
    ap.add_argument("--scope", choices=("corpus", "all"), default="corpus",
                    help="score only questions whose gold document is in this corpus")
    ap.add_argument("--project-full", action="store_true",
                    help="project pilot tokens to the full corpus (C0 cost input)")
    args = ap.parse_args()

    rows = load_quality_set(Path(args.set_path))
    if args.limit:
        rows = rows[: args.limit]
    conn = open_db(Path(args.db))
    store = Store(conn, args.chunks)

    skipped = 0
    if args.scope == "corpus":
        kept = [row for row in rows if int(row["doc_id"]) in store.doc_ids]
        skipped = len(rows) - len(kept)
        rows = kept

    if args.retriever == "fts":
        retriever = lambda q: retrieve_fts(store, q, store.doc_ids,  # noqa: E731
                                           variant=args.fts_variant)
    elif args.retriever == "seed_dense":
        if args.chunks != "old":
            print(json.dumps({
                "chunks": args.chunks,
                "retriever": args.retriever,
                "applicable": False,
                "why": "seed_dense needs stored vectors; v2 chunks have none "
                       "(new vectors are a paid call, so nothing was spent).",
                "v2_tokens": round(store.tokens),
                "cost_formula": "tokens * price_per_million / 1e6",
                "price_per_m": args.price_per_m,
                "cost_usd": round(store.tokens * args.price_per_m / 1e6, 4),
                "per_type": {k: {"chunks": v["chunks"], "tokens": round(v["tokens"]),}
                             for k, v in store.per_type.items()},
            }, indent=2))
            return
        retriever = lambda q: retrieve_seed_dense(store, q)  # noqa: E731
    elif args.retriever.startswith("local:"):
        index_dir = Path(args.retriever.split(":", 1)[1])
        retriever = lambda q: retrieve_local(store, q, index_dir)  # noqa: E731
    else:
        raise SystemExit(f"unknown --retriever {args.retriever!r}")

    good, bad = verify_spans(conn, rows)
    cross_rows = [row for row in rows if str(row.get("why", "")).startswith("cross-document")]
    single_rows = [row for row in rows
                   if not str(row.get("why", "")).startswith("cross-document")]
    rank_of: dict[str, int | None] = {}
    details = []
    for row in rows:
        hits = retriever(row["question"])
        rank = first_hit_rank(hits, row)
        rank_of[row["qid"]] = rank
        details.append({"qid": row["qid"], "rank": rank,
                        "cross": row in cross_rows,
                        "top": hits[0]["chunk_id"] if hits else None})

    def _ranks(subset: list[dict]) -> list[int | None]:
        return [rank_of[row["qid"]] for row in subset]

    by_type: dict[str, list[dict]] = {}
    for row in single_rows:
        by_type.setdefault(row["doc_type"], []).append(row)
    hard_rows = [row for row in rows if row.get("difficulty") == "H"]

    result = {
        "chunks": args.chunks,
        "retriever": args.retriever,
        "db": str(args.db),
        "set": str(args.set_path),
        "n": len(rows),
        "skipped_not_in_corpus": skipped,
        "span_checks_ok": good,
        "span_checks_bad": bad,
        "overall": score(rows, _ranks(rows)),
        "single_document": score(single_rows, _ranks(single_rows)),
        "cross_document": score(cross_rows, _ranks(cross_rows)),
        "per_type": {k: score(v, _ranks(v)) for k, v in sorted(by_type.items())},
        "hard_negatives": score(hard_rows, _ranks(hard_rows)),
        "corpus": {"chunks": len(store.by_chunk), "tokens": round(store.tokens),
                   "header_tokens": round(store.header_tokens),
                   "total_tokens": round(store.tokens + store.header_tokens),
                   "per_type": {k: {"chunks": v["chunks"], "tokens": round(v["tokens"]),
                                    "header_tokens": round(v["header_tokens"]),
                                    "docs": len(store.docs_per_type.get(k, ()))}
                                for k, v in sorted(store.per_type.items())}},
        "details": details,
    }

    if args.project_full:
        from reality_engine.db.readonly import connect_ro
        from reality_engine.toolbelt._common import data_root
        src = Path(data_root()) / "equity_intelligence.db"
        src_conn = connect_ro(src)
        counts = dict(src_conn.execute(
            "select r.source_type, count(*) from raw_documents r "
            "where exists (select 1 from document_chunks c where c.doc_id = r.doc_id) "
            "group by r.source_type").fetchall())
        type_sources = {
            "concall": ("CONCALL_TRANSCRIPT",),
            "deck": ("INVESTOR_PRESENTATION",),
            "annual_report": ("ANNUAL_REPORT",),
            "circular": ("PIB_Press_Release", "RBI_Monetary_Policy"),
        }
        projected: dict[str, dict] = {}
        total = 0
        for doc_type, bucket in sorted(store.per_type.items()):
            pilot_docs = len(store.docs_per_type.get(doc_type, ()))
            full_docs = sum(counts.get(source, 0) for source in type_sources.get(doc_type, ()))
            per_doc = (bucket["tokens"] + bucket["header_tokens"]) / max(1, pilot_docs)
            estimate = round(per_doc * full_docs)
            projected[doc_type] = {
                "pilot_docs": pilot_docs,
                "pilot_tokens": round(bucket["tokens"] + bucket["header_tokens"]),
                "full_docs": full_docs, "projected_tokens": estimate}
            total += estimate
        result["token_projection"] = {
            "per_type": projected, "total_tokens": total,
            "price_per_m": args.price_per_m,
            "cost_usd": round(total * args.price_per_m / 1e6, 2),
            "note": "pilot body+header tokens per document, times documents with "
                    "chunks in the live corpus",
        }
    if args.out:
        Path(args.out).write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "details"}, indent=2))


if __name__ == "__main__":
    main()

