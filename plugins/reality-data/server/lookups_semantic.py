"""T-154: ``pilot3_semantic`` — dense (embedding) page search over one pilot store, point-in-time.

Reads the page vectors ``reality_engine.pilot3.embed_test embed`` wrote (``<model>_text.npy`` + ``.index.json``,
rows already L2-normalised) from ``REALITY_PILOT3_EMBED_DIR`` (default: ``embed/`` next to the store).  The pool is
the question's company only, pages known by ``as_of`` (``COALESCE(page.known_at, doc.known_at)``), optionally one
document type and a filing window; pages without a vector are counted and reported, never guessed.

The query vector is paid (DeepInfra, Nemotron 8B): it is computed only with ``REALITY_DATA_ALLOW_PAID_EMBED=1`` and
``DEEPINFRA_API_KEY`` in the environment (the key is never printed), cached by text hash in
``query_cache_<model>.json`` so a re-ask costs nothing, and every paid call's tokens are appended to
``query_spend.jsonl``.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import numpy as np

import lookups_pilot3 as p3
from lookups_pilot3 import DataError

PAID_EMBED_FLAG = "REALITY_DATA_ALLOW_PAID_EMBED"
API_URL = "https://api.deepinfra.com/v1/openai/embeddings"
MODELS = {"8b": "nvidia/Nemotron-3.5-Embed-8B-BF16"}
DEFAULT_MODEL = "8b"
PAGE_CHARS = 1500          # page text returned per hit by default
MAX_PAGE_CHARS = 6000

_lock = threading.Lock()
_cache: dict[str, Any] = {}     # model -> {"stamp", "matrix", "rows"}


def embed_dir() -> Path:
    env = os.environ.get("REALITY_PILOT3_EMBED_DIR")
    return Path(env) if env else p3.db_path().parent / "embed"


def _vectors(model: str) -> tuple[np.ndarray, dict[tuple[str, int], int]]:
    """The page matrix and (doc_key, page) -> row; reloaded when the files change (an embed run may still add)."""
    base = embed_dir()
    npy, index = base / f"{model}_text.npy", base / f"{model}_text.index.json"
    if not (npy.is_file() and index.is_file()):
        raise DataError("no_vectors", f"no page vectors at {base} for model {model}; build them with "
                        "python -m reality_engine.pilot3.embed_test embed")
    stamp = (npy.stat().st_mtime_ns, index.stat().st_mtime_ns)
    with _lock:
        held = _cache.get(model)
        if held and held["stamp"] == stamp:
            return held["matrix"], held["rows"]
        matrix = np.load(npy, allow_pickle=False, mmap_mode="r")
        keys = json.loads(index.read_text(encoding="utf-8"))
        n = min(len(matrix), len(keys))
        rows = {(str(k["doc_key"]), int(k["page"])): i for i, k in enumerate(keys[:n])}
        _cache[model] = {"stamp": stamp, "matrix": matrix[:n], "rows": rows}
        return matrix[:n], rows


def _query_vector(text: str, model: str) -> tuple[np.ndarray, bool]:
    """(unit vector, paid?) — from the hash cache, else one DeepInfra call when the paid gate is open."""
    base = embed_dir()
    path = base / f"query_cache_{model}.json"
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    with _lock:
        try:
            held = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        except (OSError, ValueError):
            held = {}
    if digest in held:
        return np.asarray(held[digest], dtype=np.float32), False
    if os.environ.get(PAID_EMBED_FLAG, "").strip() != "1":
        raise DataError("paid_embed_off", f"semantic search needs a paid query embedding ({PAID_EMBED_FLAG}=1 is "
                        "not set); use pilot3_search instead")
    key = os.environ.get("DEEPINFRA_API_KEY", "")
    if not key:
        raise DataError("no_key", "DEEPINFRA_API_KEY is not in this machine's environment; use pilot3_search")
    body = json.dumps({"model": MODELS[model], "input": [text], "input_type": "query",
                       "encoding_format": "float"}).encode("utf-8")
    payload: dict[str, Any] = {}
    for attempt in range(4):
        request = urllib.request.Request(API_URL, data=body, headers={
            "Authorization": f"Bearer {key}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                payload = json.loads(response.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as exc:
            if exc.code not in (429, 500, 502, 503, 504) or attempt == 3:
                raise DataError("embed_failed", f"DeepInfra returned HTTP {exc.code}") from exc
        except urllib.error.URLError as exc:
            if attempt == 3:
                raise DataError("embed_failed", f"DeepInfra unreachable: {exc.reason}") from exc
        time.sleep(2 ** attempt)
    data = payload.get("data") or []
    if not data:
        raise DataError("embed_failed", "DeepInfra returned no vector")
    vector = np.asarray(data[0]["embedding"], dtype=np.float32)
    norm = float(np.linalg.norm(vector))
    vector = vector / norm if norm else vector
    tokens = int((payload.get("usage") or {}).get("prompt_tokens") or 0)
    with _lock:
        try:
            held = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        except (OSError, ValueError):
            held = {}
        held[digest] = [round(float(v), 6) for v in vector]
        base.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(".json.tmp")
        temp.write_text(json.dumps(held), encoding="utf-8")
        temp.replace(path)
        with (base / "query_spend.jsonl").open("a", encoding="utf-8") as log:
            log.write(json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "model": model, "tokens": tokens,
                                  "chars": len(text)}) + "\n")
    return vector, True


def semantic(symbol: str, query: str, as_of: str | None = None, limit: int = 8, doc_type: str | None = None,
             date_from: str | None = None, date_to: str | None = None, chars: int = PAGE_CHARS,
             model: str = DEFAULT_MODEL) -> dict[str, Any]:
    """Pages of one company whose meaning is closest to ``query`` (cosine, best first), known by ``as_of``."""
    if not str(query or "").strip():
        raise DataError("bad_query", "query needs text")
    if model not in MODELS:
        raise DataError("bad_model", f"model must be one of {sorted(MODELS)}")
    sym = p3.resolve_symbol(symbol)
    cap = p3._cap(limit, 8)
    width = max(200, min(int(chars or PAGE_CHARS), MAX_PAGE_CHARS))
    where, args = ["p.symbol=?"], [sym]
    extra, eargs = p3._asof(as_of, "COALESCE(p.known_at, d.known_at)")
    dtype = p3._DOC_TYPES.get(doc_type.strip().lower(), doc_type.strip().lower()) if doc_type else None
    if dtype:
        where.append("d.doc_type=?")
        args.append(dtype)
    for field, value, op in (("date_from", date_from, ">="), ("date_to", date_to, "<=")):
        day = p3._day(value, field)
        if day:
            where.append(f"substr(COALESCE(d.filing_date, d.known_at, ''),1,10) {op} ?")
            args.append(day)
    pool = p3._q("SELECT p.doc_key, p.page, d.doc_type, d.title, d.filing_date, "
                 "COALESCE(p.known_at, d.known_at) known FROM doc_page p JOIN doc d ON d.doc_key=p.doc_key "
                 f"WHERE {' AND '.join(where)}{extra}", (*args, *eargs))
    matrix, rows = _vectors(model)
    covered = [(rows[(r["doc_key"], int(r["page"]))], r) for r in pool if (r["doc_key"], int(r["page"])) in rows]
    coverage = {"pool_pages": len(pool), "pages_with_vectors": len(covered),
                "note": "only pages with a vector are ranked; the index holds transcripts, decks, results, press "
                        "releases and annual reports known from 2025-04-01, text only"}
    if not covered:
        return p3._reply(sym, [], "pilot3_semantic", coverage=coverage)
    vector, paid = _query_vector(str(query).strip(), model)
    index = np.fromiter((i for i, _r in covered), dtype=np.int64, count=len(covered))
    scores = np.asarray(matrix[index], dtype=np.float32) @ vector
    order = np.argsort(-scores, kind="stable")[:cap]
    hits = []
    for position in order:
        _i, r = covered[int(position)]
        text = p3._q("SELECT text FROM doc_page WHERE doc_key=? AND page=?", (r["doc_key"], r["page"]))
        hits.append({"doc_type": r["doc_type"], "title": p3._trim(r["title"], 120), "filing_date": r["filing_date"],
                     "page": r["page"], "score": round(float(scores[int(position)]), 4),
                     "text": p3._trim(text[0]["text"] if text else "", width),
                     "provenance": p3._prov("doc_page", f"{r['doc_key']} p{r['page']}", r["known"])})
    return p3._reply(sym, hits, "pilot3_semantic", coverage=coverage, model=MODELS[model], paid_query=paid)
