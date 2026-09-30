"""Prototype: bge-small-en-v1.5 (incumbent, 384d) vs bge-base-en-v1.5 (challenger, 768d).

Explore/exploit BEFORE any migration decision: score both models on concall /
annual-report Q/A recall over the two fresh annual-report docs already in-DB
(doc 6490 SAIL with 443 chunks, doc 6491 with 329 chunks).

What it does:
  (a) fetches bge-base-en-v1.5 ONNX + tokenizer into
      ``data/models/bge-base-en-v1.5/`` (a SEPARATE dir; the live bge-small
      dir is never touched) via the same huggingface_hub flow as
      ``OnnxEmbedder.ensure_downloaded``;
  (b) samples at most --limit chunks per doc deterministically (evenly-spaced
      every-Nth over chunk_index order);
  (c) embeds the sample with the incumbent (live ``onnx_embedder`` singleton)
      and the challenger (a second ``OnnxEmbedder`` pointed at the base dir),
      both forced to the ONNX DirectML path in small batches;
  (d) builds a 20-question Q/A set (10/doc) FROM the sampled chunks themselves
      — one anchor disclosure per question, with the known-answer chunk id —
      and writes it to ``data/logs/embed_prototype_qa_2026-09-23.json``;
  (e) scores recall@1 / recall@5 for both models with the same cosine code
      path (the ``ChunkVectorIndex.search`` pattern: L2-normalise, dot,
      argpartition);
  (f) prints ``{incumbent: {r1, r5}, challenger: {r1, r5}, delta, sample_n,
      ms_per_embed_each}`` JSON to stdout.

Constraints honoured: read-only against the live DB (``mode=ro``, connection
closed promptly); NO DB writes; the detached annual_n200 drain is undisturbed
(ONNX DirectML only — the Vulkan embedding server is never probed — and small
batches keep GPU contention low).

    python -m reality_engine.scripts.embed_prototype_compare
    python -m reality_engine.scripts.embed_prototype_compare --limit 50 --qa-per-doc 4
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from reality_engine import config as cfg  # noqa: E402
from reality_engine.ingestion import onnx_embedder as oe  # noqa: E402
from reality_engine.ingestion.onnx_embedder import OnnxEmbedder  # noqa: E402

logger = logging.getLogger("reality_engine.embed_prototype_compare")

DOC_IDS: Tuple[int, int] = (6490, 6491)
CHALLENGER_MODEL_ID = "Xenova/bge-base-en-v1.5"
CHALLENGER_DIRNAME = "bge-base-en-v1.5"
QA_ARTIFACT_NAME = "embed_prototype_qa_2026-09-23.json"
REQUIRED_QA_KEYS = ("question", "answer_chunk_id", "doc_id")

_META_LINE_RE = re.compile(r"^\s*\[Metadata:[^\]]*\]\s*")
_SENT_SPLIT_RE = re.compile(r"(?<=[.!?;:])\s+")
_WS_RE = re.compile(r"\s+")


# --------------------------------------------------------------------------
# Pure helpers (import-safe, hermetic — unit-tested without models or the DB).
# --------------------------------------------------------------------------
def deterministic_sample(
    rows: Sequence[Dict[str, Any]], limit: int
) -> List[Dict[str, Any]]:
    """Evenly-spaced every-Nth subsample, order-preserving and deterministic.

    ``rows`` must already be in chunk_index order. When ``len(rows) <= limit``
    the whole list is returned; otherwise ``limit`` rows spread from the first
    to the last row (endpoints always included).
    """
    rows = list(rows)
    if limit <= 0:
        return []
    if len(rows) <= limit:
        return rows
    if limit == 1:
        return [rows[0]]
    idx = [round(i * (len(rows) - 1) / (limit - 1)) for i in range(limit)]
    return [rows[i] for i in idx]


def clean_text(text: str) -> str:
    """Drop the boilerplate ``[Metadata: ...]`` header shared by every chunk."""
    text = _META_LINE_RE.sub("", text or "")
    return _WS_RE.sub(" ", text).strip()


def pick_anchor_sentence(text: str, max_chars: int = 400) -> str:
    """Pick one distinctive disclosure sentence from a chunk.

    Prefers sentences carrying digits (figures, guidance, ratios, risks — the
    substance finance Q/A asks about); falls back to the longest sentence,
    then to a raw head-truncate when the OCR text has no sentence structure.
    """
    cleaned = clean_text(text)
    sents = [s.strip() for s in _SENT_SPLIT_RE.split(cleaned) if len(s.strip()) >= 40]
    if not sents:
        return cleaned[:max_chars].strip()
    pool = [s for s in sents if re.search(r"\d", s)] or sents
    return max(pool, key=len)[:max_chars].strip()


def build_qa_set(
    sampled: Sequence[Dict[str, Any]], per_doc: int = 10
) -> List[Dict[str, Any]]:
    """Build ``{question, answer_chunk_id, doc_id}`` entries from sampled chunks.

    ``sampled`` rows carry ``chunk_id`` / ``doc_id`` / ``chunk_index`` /
    ``content``. Per doc, ``per_doc`` chunks spread across chunk_index order
    become questions quoting one anchor disclosure each.
    """
    by_doc: Dict[int, List[Dict[str, Any]]] = {}
    for row in sampled:
        by_doc.setdefault(int(row["doc_id"]), []).append(row)
    questions: List[Dict[str, Any]] = []
    for doc_id in sorted(by_doc):
        rows = sorted(by_doc[doc_id], key=lambda r: int(r["chunk_index"]))
        for row in deterministic_sample(rows, per_doc):
            anchor = pick_anchor_sentence(str(row["content"]))
            questions.append(
                {
                    "question": (
                        f"SAIL annual report (doc {doc_id}): which passage "
                        f'discloses the following — "{anchor}"?'
                    ),
                    "answer_chunk_id": int(row["chunk_id"]),
                    "doc_id": int(doc_id),
                    "chunk_index": int(row["chunk_index"]),
                    "anchor": anchor,
                }
            )
    return questions


def validate_qa_artifact(
    obj: Any, per_doc: int = 10, doc_ids: Sequence[int] = DOC_IDS
) -> List[str]:
    """Return a list of schema violations (empty == valid)."""
    errors: List[str] = []
    if not isinstance(obj, dict):
        return ["artifact root must be a JSON object"]
    questions = obj.get("questions")
    if not isinstance(questions, list):
        return ["artifact must contain a 'questions' list"]
    if len(questions) != per_doc * len(doc_ids):
        errors.append(
            f"expected {per_doc * len(doc_ids)} questions, got {len(questions)}"
        )
    seen_ids: set = set()
    per_doc_counts: Dict[int, int] = {}
    for i, q in enumerate(questions):
        if not isinstance(q, dict):
            errors.append(f"questions[{i}] must be an object")
            continue
        for key in REQUIRED_QA_KEYS:
            if key not in q:
                errors.append(f"questions[{i}] missing key '{key}'")
        if not isinstance(q.get("question"), str) or not q.get("question", "").strip():
            errors.append(f"questions[{i}].question must be a non-empty string")
        cid = q.get("answer_chunk_id")
        if not isinstance(cid, int):
            errors.append(f"questions[{i}].answer_chunk_id must be an int")
        elif cid in seen_ids:
            errors.append(f"questions[{i}].answer_chunk_id {cid} duplicated")
        else:
            seen_ids.add(cid)
        doc = q.get("doc_id")
        if doc not in set(doc_ids):
            errors.append(f"questions[{i}].doc_id must be one of {list(doc_ids)}")
        else:
            per_doc_counts[int(doc)] = per_doc_counts.get(int(doc), 0) + 1
    for doc_id in doc_ids:
        if per_doc_counts.get(int(doc_id), 0) != per_doc:
            errors.append(f"doc {doc_id}: expected {per_doc} questions")
    return errors


def rank_passages(query_vec: Sequence[float], passage_mat: Any) -> Any:
    """Full passage ranking for one query (the ChunkVectorIndex.search pattern).

    L2-normalise, dot-product cosine, stable descending argsort. Shared by both
    models so recall numbers are directly comparable.
    """
    import numpy as np  # local import: keeps module import light for tests

    q = np.asarray(query_vec, dtype=np.float32)
    mat = np.asarray(passage_mat, dtype=np.float32)
    qn = float(np.linalg.norm(q)) or 1.0
    denom = (np.linalg.norm(mat, axis=1) * qn) + 1e-12
    scores = (mat @ q) / denom
    return np.argsort(-scores, kind="stable")


def recall_at_ks(
    query_vecs: Sequence[Sequence[float]],
    passage_mat: Any,
    passage_ids: Sequence[int],
    qa: Sequence[Dict[str, Any]],
    ks: Sequence[int] = (1, 5),
) -> Dict[str, float]:
    """Fraction of questions whose answer chunk ranks within each k.

    Both models share this path: ``rank_passages`` cosine per query, then
    rank of the known-answer chunk id. ``query_vecs[i]`` must correspond to
    ``qa[i]``.
    """
    import numpy as np  # local import: keeps module import light for tests

    pos = {int(cid): i for i, cid in enumerate(passage_ids)}
    hits = {int(k): 0 for k in ks}
    for qv, entry in zip(query_vecs, qa):
        order = rank_passages(qv, passage_mat)
        answer_pos = pos[int(entry["answer_chunk_id"])]
        rank = int(np.where(order == answer_pos)[0][0]) + 1
        for k in ks:
            if rank <= int(k):
                hits[int(k)] += 1
    n = max(1, len(qa))
    return {f"r{k}": hits[int(k)] / n for k in ks}


def score_model(
    query_vecs: Sequence[Sequence[float]],
    passage_mat: Any,
    passage_ids: Sequence[int],
    qa: Sequence[Dict[str, Any]],
    ks: Sequence[int] = (1, 5),
) -> Dict[str, float]:
    """Score one model: rank each query against its own passage matrix."""
    return recall_at_ks(query_vecs, passage_mat, passage_ids, qa, ks=ks)



# --------------------------------------------------------------------------
# I/O + model wiring (live run only — never exercised in unit tests).
# --------------------------------------------------------------------------
def ensure_model_downloaded(model_dir: Path, repo_id: str) -> bool:
    """Mirror of ``OnnxEmbedder.ensure_downloaded`` for a non-default repo.

    ``ensure_downloaded`` always pulls ``MODEL_ID`` (bge-small), so the
    challenger needs the same huggingface_hub flow parametrised by repo:
    short-circuit when ``onnx/model.onnx`` + ``tokenizer.json`` are already
    present, else ``hf_hub_download`` each file into the SEPARATE model dir.
    """
    try:
        from huggingface_hub import hf_hub_download  # type: ignore
    except ImportError:
        logger.warning("huggingface_hub missing — pip install huggingface_hub")
        return False
    try:
        model_dir.mkdir(parents=True, exist_ok=True)
        for remote, local in (
            ("onnx/model.onnx", model_dir / "onnx" / "model.onnx"),
            ("tokenizer.json", model_dir / "tokenizer.json"),
        ):
            if local.exists():
                continue
            local.parent.mkdir(parents=True, exist_ok=True)
            got = hf_hub_download(
                repo_id=repo_id, filename=remote, local_dir=str(model_dir)
            )
            # hf_hub_download mirrors the repo layout (local_dir/onnx/...);
            # move into place when it lands elsewhere.
            if Path(got) != local and Path(got).exists():
                Path(got).replace(local)
        onnx_ok = (model_dir / "onnx" / "model.onnx").exists() or (
            model_dir / "onnx" / "model_quantized.onnx"
        ).exists()
        return bool(onnx_ok and (model_dir / "tokenizer.json").exists())
    except Exception as exc:
        logger.warning("challenger download miss: %s", exc)
        return False


def load_samples(
    db_path: Path, doc_ids: Sequence[int] = DOC_IDS, limit: int = 200
) -> List[Dict[str, Any]]:
    """Read-only ``mode=ro`` sample of ``content`` chunks for the given docs."""
    sampled: List[Dict[str, Any]] = []
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        for doc_id in doc_ids:
            rows = con.execute(
                "select chunk_id, doc_id, chunk_index, content from document_chunks "
                "where doc_id = ? order by chunk_index",
                (int(doc_id),),
            ).fetchall()
            logger.info("doc %s: %d chunks in DB", doc_id, len(rows))
            dicts = [
                {
                    "chunk_id": int(cid),
                    "doc_id": int(did),
                    "chunk_index": int(cix),
                    "content": str(content),
                }
                for cid, did, cix, content in rows
            ]
            sampled.extend(deterministic_sample(dicts, limit))
    finally:
        con.close()
    return sampled


def embed_texts(
    embedder: OnnxEmbedder,
    texts: List[str],
    is_query: bool = False,
    batch: int = 8,
    label: str = "model",
) -> Tuple[Optional[List[List[float]]], float]:
    """Embed in small batches; returns (vectors or None, elapsed seconds)."""
    out: List[List[float]] = []
    started = time.perf_counter()
    for i in range(0, len(texts), batch):
        vecs = embedder.embed_many(texts[i : i + batch], is_query=is_query)
        if vecs is None:
            return None, time.perf_counter() - started
        out.extend(vecs)
        done = min(i + batch, len(texts))
        if done % (batch * 5) == 0 or done == len(texts):
            logger.info("%s: embedded %d/%d", label, done, len(texts))
    return out, time.perf_counter() - started


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Prototype bge-small vs bge-base recall on annual-report chunks."
    )
    ap.add_argument("--db", default=None, help="override DB path (read-only)")
    ap.add_argument("--limit", type=int, default=200, help="max chunks per doc")
    ap.add_argument("--qa-per-doc", type=int, default=10, help="questions per doc")
    ap.add_argument("--batch", type=int, default=8, help="embed batch size")
    ap.add_argument(
        "--qa-out", default=None, help="override Q/A artifact path"
    )
    args = ap.parse_args(argv)

    db_path = Path(args.db) if args.db else cfg.DB_PATH
    challenger_dir = Path(cfg.DATA_DIR) / "models" / CHALLENGER_DIRNAME
    qa_path = (
        Path(args.qa_out)
        if args.qa_out
        else Path(cfg.DATA_DIR) / "logs" / QA_ARTIFACT_NAME
    )

    # (a) challenger weights into their own dir — the live bge-small dir is
    # never written by this script.
    logger.info("ensuring challenger weights in %s", challenger_dir)
    if not ensure_model_downloaded(challenger_dir, CHALLENGER_MODEL_ID):
        print(json.dumps({"error": "challenger download failed"}, indent=2))
        return 2

    # (b) deterministic read-only sample.
    sampled = load_samples(db_path, DOC_IDS, args.limit)
    if not sampled:
        print(json.dumps({"error": "no chunks sampled"}, indent=2))
        return 2
    passage_ids = [r["chunk_id"] for r in sampled]
    passage_texts = [r["content"] for r in sampled]

    # (c) incumbent = live singleton, challenger = second instance. Both
    # forced onto the ONNX DirectML path: the Vulkan embedding server (and
    # with it the drain's GPU territory) is never probed. Attribute sets are
    # process-local to this prototype run.
    incumbent = oe.onnx_embedder
    incumbent.backend = "onnx"
    challenger = OnnxEmbedder(
        model_dir=challenger_dir, prefer_gpu=True, backend="onnx", batch_size=8
    )
    if not incumbent.available:
        print(json.dumps({"error": "incumbent embedder unavailable"}, indent=2))
        return 2
    if not challenger.available:
        print(json.dumps({"error": "challenger embedder unavailable"}, indent=2))
        return 2

    import numpy as np

    # (c, cont.) passage embeddings + per-embed latency per model.
    inc_vecs, inc_t = embed_texts(
        incumbent, passage_texts, is_query=False, batch=args.batch, label="incumbent"
    )
    ch_vecs, ch_t = embed_texts(
        challenger, passage_texts, is_query=False, batch=args.batch, label="challenger"
    )
    if inc_vecs is None or ch_vecs is None:
        print(json.dumps({"error": "passage embedding failed"}, indent=2))
        return 2
    inc_mat = np.asarray(inc_vecs, dtype=np.float32)
    ch_mat = np.asarray(ch_vecs, dtype=np.float32)

    # (d) Q/A set from the sampled chunks themselves; artifact to data/logs.
    qa = build_qa_set(sampled, per_doc=args.qa_per_doc)
    artifact = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "doc_ids": list(DOC_IDS),
        "sampled_chunk_ids": passage_ids,
        "incumbent_model": oe.MODEL_ID,
        "challenger_model": CHALLENGER_MODEL_ID,
        "questions": qa,
    }
    violations = validate_qa_artifact(artifact, per_doc=args.qa_per_doc)
    if violations:
        print(json.dumps({"error": "qa validation failed", "details": violations},
                         indent=2))
        return 2
    qa_path.parent.mkdir(parents=True, exist_ok=True)
    qa_path.write_text(json.dumps(artifact, indent=2), encoding="utf-8")
    logger.info("wrote %d questions to %s", len(qa), qa_path)

    # (e) same cosine code path for both models; queries carry the bge
    # retrieval instruction (is_query=True), passages do not.
    q_texts = [q["question"] for q in qa]
    inc_q, inc_qt = embed_texts(
        incumbent, q_texts, is_query=True, batch=args.batch, label="incumbent-q"
    )
    ch_q, ch_qt = embed_texts(
        challenger, q_texts, is_query=True, batch=args.batch, label="challenger-q"
    )
    if inc_q is None or ch_q is None:
        print(json.dumps({"error": "query embedding failed"}, indent=2))
        return 2
    inc_recall = score_model(inc_q, inc_mat, passage_ids, qa)
    ch_recall = score_model(ch_q, ch_mat, passage_ids, qa)

    # (f) per-embed latency covers every embed call per model, in milliseconds.
    n_texts = len(passage_texts) + len(q_texts)
    inc_ms = 1000.0 * (inc_t + inc_qt) / n_texts
    ch_ms = 1000.0 * (ch_t + ch_qt) / n_texts
    result = {
        "incumbent": {"r1": inc_recall["r1"], "r5": inc_recall["r5"]},
        "challenger": {"r1": ch_recall["r1"], "r5": ch_recall["r5"]},
        "delta": {
            "r1": ch_recall["r1"] - inc_recall["r1"],
            "r5": ch_recall["r5"] - inc_recall["r5"],
        },
        "sample_n": len(sampled),
        "ms_per_embed_each": {"incumbent": inc_ms, "challenger": ch_ms},
        "dims": {"incumbent": int(inc_mat.shape[1]), "challenger": int(ch_mat.shape[1])},
        "qa_artifact": str(qa_path),
    }
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
