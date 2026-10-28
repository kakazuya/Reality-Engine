"""Query-time embeddings for the 4096-d vector indexes.

The stored document vectors were produced by cloud embedding models; querying
them requires the same model on the query side.  This module owns that call,
with the exact prompts/endpoints used by ``reembed_qwen_nebius.py`` and
``embed_model_test.py`` so query vectors land in the same space as the stored
documents.

Indexes
-------
* ``vector_index_nemotron8b`` — ``nvidia/Nemotron-3-Embed-8B`` on DeepInfra,
  query prefix ``"query: "``, tiers 0-2 (concall/presentation/announcement/
  news/macro).
* ``vector_index_qwen8b_ar`` — ``Qwen/Qwen3-Embedding-8B`` on Nebius, query
  prefix ``embed_model_test.QWEN_INSTRUCT``, tier 3 annual reports.  Only rows
  whose ``done.npy`` flag is true are searchable (61,440 / 1,367,706).

Keys are read from the User environment (registry included) under
``DEEPINFRA_API_KEY`` / ``NEBIUS_API_KEY`` and are never printed or logged.
A missing key raises :class:`MissingAPIKeyError` so callers can fall back to FTS.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

import numpy as np

ROOT = Path(os.environ.get("REALITY_DATA_REPO_ROOT") or Path(__file__).resolve().parents[3])
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

# Copied verbatim from reality_engine/scripts/embed_model_test.py: Qwen3 puts
# the instruction on queries only, and the question follows "Query:" directly.
QWEN_INSTRUCT = (
    "Instruct: Given an analyst's question about an Indian listed company, retrieve the earnings-call "
    "transcript passage that answers it\nQuery:"
)

DEFAULT_DATA_DIR = ROOT / "reality_engine" / "data"
CACHE_SIZE = 256
TIMEOUT_SECONDS = 10.0
RETRY_DELAY_SECONDS = 0.25
SEARCH_BLOCK_ROWS = 8192

INDEXES: dict[str, dict[str, Any]] = {
    "nemotron8b": {
        "dir": "vector_index_nemotron8b",
        "model": "nvidia/Nemotron-3-Embed-8B",
        "urls": ["https://api.deepinfra.com/v1/openai/embeddings"],
        "key_env": "DEEPINFRA_API_KEY",
        "provider": "deepinfra",
        "query_prefix": "query: ",
        "dim": 4096,
        "tiers": [0, 1, 2],
        "description": "Nemotron-3-Embed-8B, tiers 0-2 (concall, presentation, announcement, news, macro).",
    },
    "qwen8b_ar": {
        "dir": "vector_index_qwen8b_ar",
        "model": "Qwen/Qwen3-Embedding-8B",
        "urls": [
            "https://api.tokenfactory.nebius.com/v1/embeddings",
            "https://api.studio.nebius.com/v1/embeddings",
        ],
        "key_env": "NEBIUS_API_KEY",
        "provider": "nebius",
        "query_prefix": QWEN_INSTRUCT,
        "dim": 4096,
        "tiers": [3],
        "description": "Qwen3-Embedding-8B, tier 3 annual reports.",
    },
}
ALIASES = {
    "nemotron": "nemotron8b", "nemotron8b": "nemotron8b",
    "vector_index_nemotron8b": "nemotron8b", "nemotron-8b": "nemotron8b",
    "qwen8b_ar": "qwen8b_ar", "qwen_ar": "qwen8b_ar", "qwen8b-ar": "qwen8b_ar",
    "vector_index_qwen8b_ar": "qwen8b_ar", "qwen8b": "qwen8b_ar",
}


class EmbeddingError(RuntimeError):
    """A query embedding could not be produced; callers should fall back to FTS."""


class MissingAPIKeyError(EmbeddingError):
    """The provider key is not configured."""


class UnknownIndexError(EmbeddingError):
    """The requested index is not one of the 4096-d indexes."""


_lock = threading.RLock()
_index_cache: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}


# ---------------------------------------------------------------------------
# Keys and config
# ---------------------------------------------------------------------------
def _env() -> dict[str, str]:
    """Environment plus the Windows User/Machine variables (same as the harness)."""
    try:
        from reality_engine.scripts.resource_watchdog import user_env
        return user_env()
    except Exception:
        return dict(os.environ)


def _data_dir() -> Path:
    return Path(os.environ.get("REALITY_DATA_ROOT") or DEFAULT_DATA_DIR)


PAID_EMBED_FLAG = "REALITY_DATA_ALLOW_PAID_EMBED"


def _key_for(cfg: dict[str, Any]) -> str:
    # Query embedding spends the provider allowance (DeepInfra). Shivam,
    # 2026-10-24: never without his explicit permission, so it is off unless the
    # flag is set; search_docs then falls back to FTS.
    env = _env()
    if str(env.get(PAID_EMBED_FLAG, "")).strip() != "1":
        raise MissingAPIKeyError(
            f"paid query embedding disabled ({PAID_EMBED_FLAG} != 1); falling back to FTS"
        )
    value = env.get(cfg["key_env"])
    if not value or not str(value).strip():
        raise MissingAPIKeyError(
            f"{cfg['key_env']} is not configured; falling back to FTS"
        )
    return str(value).strip()


def normalise_index(index: str) -> str:
    name = Path(str(index or "").strip()).name.strip().lower()
    if name.endswith(".npy"):
        name = name.rsplit(".", 1)[0]
    name = name.replace("vector_index_", "")
    name = ALIASES.get(name, name)
    if name not in INDEXES:
        raise UnknownIndexError(
            f"unknown index {index!r}; choose from {sorted(INDEXES)}"
        )
    return name


def index_path(index: str) -> Path:
    name = normalise_index(index)
    return _data_dir() / INDEXES[name]["dir"]


def _meta(index: str) -> dict[str, Any]:
    try:
        return json.loads((index_path(index) / "chunk_index_meta.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return {}


def index_info(index: str) -> dict[str, Any]:
    """Read-only metadata/coverage; never calls a provider."""
    name = normalise_index(index)
    cfg = INDEXES[name]
    path = index_path(name)
    meta = _meta(name)
    rows = int(meta.get("rows") or 0)
    done_available = (path / "done.npy").exists()
    done_rows = rows
    if done_available:
        try:
            done = np.load(path / "done.npy", mmap_mode="r")
            done_rows = int(np.asarray(done, dtype=bool).sum())
        except (OSError, ValueError):
            done_rows = int(meta.get("done") or 0)
    coverage = round((done_rows / rows * 100.0), 3) if rows else 0.0
    description = (
        f"{cfg['description']} {cfg['model']}, {cfg['dim']}-d; "
        f"{done_rows:,}/{rows:,} rows done ({coverage:.2f}%) — search uses done rows only."
    )
    if name == "qwen8b_ar" and done_rows < rows:
        description += " The rest of the AR index is not safe to search yet."
    return {
        "name": cfg["dir"],
        "key": name,
        "path": str(path),
        "model": cfg["model"],
        "provider": cfg["provider"],
        "dim": cfg["dim"],
        "rows": rows,
        "done_rows": done_rows,
        "coverage_pct": coverage,
        "dtype": meta.get("dtype") or "float16",
        "tiers": cfg["tiers"],
        "available": (path / "chunk_ids.npy").exists() and (path / "chunk_vectors.npy").exists(),
        "search_mode": (
            "compact512-candidates + exact-4096-rerank" if name == "nemotron8b"
            else "compact512-done-candidates + exact-4096-rerank"
        ),
        "description": description,
    }


# ---------------------------------------------------------------------------
# Provider call
# ---------------------------------------------------------------------------
def _prompt(index: str, text: str) -> str:
    return INDEXES[index]["query_prefix"] + text


def _normalise_vector(values: Sequence[float], dim: int) -> np.ndarray:
    vec = np.asarray(values, dtype=np.float32).reshape(-1)
    if vec.shape[0] != dim:
        raise EmbeddingError(f"provider returned {vec.shape[0]} dims, expected {dim}")
    norm = float(np.linalg.norm(vec))
    if not np.isfinite(norm) or norm <= 0:
        raise EmbeddingError("provider returned a zero/invalid embedding")
    return (vec / norm).astype(np.float32)


def _post_once(url: str, key: str, model: str, text: str, dim: int) -> np.ndarray:
    try:
        import requests
    except ImportError as exc:  # pragma: no cover - pinned interpreter has requests
        raise EmbeddingError(f"requests is not installed: {exc}") from exc
    try:
        response = requests.post(
            url,
            headers={"Authorization": f"Bearer {key}"},
            json={"model": model, "input": [text]},
            timeout=TIMEOUT_SECONDS,
        )
    except Exception as exc:
        raise EmbeddingError(f"{type(exc).__name__}: provider request failed") from exc
    if response.status_code != 200:
        if response.status_code in (401, 403):
            raise EmbeddingError(f"provider rejected the key (HTTP {response.status_code})")
        if response.status_code == 429:
            raise EmbeddingError("provider rate-limited the query (HTTP 429)")
        raise EmbeddingError(f"provider HTTP {response.status_code}: {response.text[:160]}")
    try:
        payload = response.json()
        rows = payload.get("data") or []
        if not rows:
            raise ValueError("empty data")
        row = sorted(rows, key=lambda item: item.get("index", 0))[0]
        return _normalise_vector(row["embedding"], dim)
    except (ValueError, KeyError, TypeError, IndexError) as exc:
        raise EmbeddingError(f"malformed provider response: {type(exc).__name__}") from exc


def _call(index: str, text: str) -> np.ndarray:
    cfg = INDEXES[index]
    key = _key_for(cfg)
    body = _prompt(index, text)
    last: Exception | None = None
    urls = list(cfg["urls"])
    for attempt in range(2):
        url = urls[attempt % len(urls)]
        try:
            return _post_once(url, key, cfg["model"], body, cfg["dim"])
        except EmbeddingError as exc:
            last = exc
            if "rejected the key" in str(exc):
                break
            if attempt == 0:
                time.sleep(RETRY_DELAY_SECONDS)
    raise last or EmbeddingError("query embedding failed")


@lru_cache(maxsize=CACHE_SIZE)
def _embed_cached(index: str, text: str) -> np.ndarray:
    return _call(index, text)


def embed_query(text: str, index: str) -> np.ndarray:
    """Return a unit-normalised float32 query vector for ``index``.

    LRU-cached; 10 s timeout; one retry.  Raises ``MissingAPIKeyError`` when the
    provider key is absent and ``EmbeddingError`` on any other failure.
    """
    if not text or not str(text).strip():
        raise ValueError("embed_query needs non-empty text")
    name = normalise_index(index)
    vector = _embed_cached(name, str(text))
    return vector.copy()


def clear_cache() -> None:
    _embed_cached.cache_clear()


# ---------------------------------------------------------------------------
# Local index search (cosine over done rows)
# ---------------------------------------------------------------------------
# A full 340,887 x 4,096 float32 scan does not fit comfortably in this box's
# free RAM and the mmap read is ~10 s.  The search path therefore uses a
# 512-dim Matryoshka prefix for candidate generation (float32, ~0.7 GB), then
# an exact 4,096-dim cosine rerank of the top candidates.  The qwen8b_ar done
# set is small enough (61,440 rows) to score exactly.
CACHE_DIR = Path(__file__).with_name(".cache")
COMPACT_DIM = 512
RERANK_MIN = 200
RERANK_FACTOR = 20
_search_cache: dict[str, dict[str, Any]] = {}


def _arrays(index: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    name = normalise_index(index)
    with _lock:
        cached = _index_cache.get(name)
        if cached is not None:
            return cached
        path = index_path(name)
        try:
            vectors = np.load(path / "chunk_vectors.npy", mmap_mode="r")
            ids = np.load(path / "chunk_ids.npy")
        except (OSError, ValueError) as exc:
            raise EmbeddingError(f"index {name} is not loadable: {exc}") from exc
        done_path = path / "done.npy"
        if done_path.exists():
            done = np.asarray(np.load(done_path, mmap_mode="r"), dtype=bool)
        else:
            done = np.ones(ids.shape[0], dtype=bool)
        if done.shape[0] != ids.shape[0]:
            raise EmbeddingError(f"index {name} done mask length mismatch")
        _index_cache[name] = (vectors, ids, done)
        return vectors, ids, done


def _build_compact(name: str, full: np.ndarray) -> np.ndarray:
    # 2026-10-29: loaded mmap read-only, so every reality-data server (one per dsh worker) shares one
    # page-cache copy instead of each holding ~1.2 GB private.
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / f"{name}_compact{COMPACT_DIM}_f32.npy"
    rows = int(full.shape[0])
    if path.exists():
        try:
            cached = np.load(path, mmap_mode="r")
            if cached.shape == (rows, COMPACT_DIM) and cached.dtype == np.float32:
                return cached
        except (OSError, ValueError):
            pass
    tmp = path.with_suffix(".npy.tmp")
    out = np.lib.format.open_memmap(tmp, mode="w+", dtype=np.float32,
                                    shape=(rows, COMPACT_DIM))
    for start in range(0, rows, SEARCH_BLOCK_ROWS):
        end = min(start + SEARCH_BLOCK_ROWS, rows)
        out[start:end] = np.asarray(full[start:end, :COMPACT_DIM], dtype=np.float32)
    out.flush()
    del out
    os.replace(tmp, path)
    return np.load(path, mmap_mode="r")


def _build_done_compact(name: str, full: np.ndarray, done_rows: np.ndarray) -> np.ndarray:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / f"{name}_done{len(done_rows)}_compact{COMPACT_DIM}_f32.npy"
    if path.exists():
        try:
            cached = np.load(path, mmap_mode="r")
            if cached.shape == (len(done_rows), COMPACT_DIM) and cached.dtype == np.float32:
                return cached
        except (OSError, ValueError):
            pass
    tmp = path.with_suffix(".npy.tmp")
    out = np.lib.format.open_memmap(tmp, mode="w+", dtype=np.float32,
                                    shape=(len(done_rows), COMPACT_DIM))
    for start in range(0, len(done_rows), 2048):
        end = min(start + 2048, len(done_rows))
        out[start:end] = np.asarray(full[done_rows[start:end], :COMPACT_DIM], dtype=np.float32)
    out.flush()
    del out
    os.replace(tmp, path)
    return np.load(path, mmap_mode="r")


def _search_data(name: str) -> dict[str, Any]:
    with _lock:
        cached = _search_cache.get(name)
        if cached is not None:
            return cached
        full, ids, done = _arrays(name)
        done_rows = np.flatnonzero(done)
        data: dict[str, Any] = {
            "full": full, "ids": ids, "done": done, "done_rows": done_rows,
            "compact": None, "done_compact": None, "done_ids": None,
        }
        try:
            if name == "nemotron8b":
                data["compact"] = _build_compact(name, full)
            elif name == "qwen8b_ar":
                data["done_compact"] = _build_done_compact(name, full, done_rows)
                data["done_ids"] = ids[done_rows]
        except (MemoryError, OSError, ValueError) as exc:
            # Functionality survives as a slower full mmap scan.
            data["cache_note"] = f"{type(exc).__name__}: {exc}"
        _search_cache[name] = data
        return data


def _top_indices(scores: np.ndarray, k: int) -> np.ndarray:
    if k >= scores.size:
        return np.argsort(-scores)
    return np.argpartition(-scores, k - 1)[:k]


def warm(index: str | None = None) -> dict[str, Any]:
    """Load/build local search caches; no provider call."""
    names = [normalise_index(index)] if index else list(INDEXES)
    out = {}
    for name in names:
        try:
            _search_data(name)
            out[name] = index_info(name)
        except EmbeddingError as exc:
            out[name] = {"key": name, "available": False, "error": str(exc)}
    return out


def search_index(query_vec: Sequence[float], index: str, top_k: int = 10,
                 allow_ids: Optional[Iterable[int]] = None) -> list[dict[str, Any]]:
    """Cosine top-k over the index's **done** rows only.

    ``nemotron8b`` scores a 512-d prefix for candidates and reranks them with the
    exact 4,096-d vectors; ``qwen8b_ar`` scores its 61,440 done rows exactly.
    """
    name = normalise_index(index)
    q = np.asarray(query_vec, dtype=np.float32).reshape(-1)
    dim = INDEXES[name]["dim"]
    if q.shape[0] != dim:
        raise EmbeddingError(f"query dim {q.shape[0]} != index dim {dim}")
    norm = float(np.linalg.norm(q))
    if not np.isfinite(norm) or norm <= 0:
        raise EmbeddingError("query vector is zero/invalid")
    q = q / norm
    data = _search_data(name)
    ids, done = data["ids"], data["done"]
    rows = data["done_rows"]
    allowed: Optional[np.ndarray] = None
    if allow_ids is not None:
        allowed = np.fromiter((int(x) for x in allow_ids), dtype=np.int64)
        if allowed.size == 0:
            return []
        rows = rows[np.isin(ids[rows], allowed)]
    if rows.size == 0:
        return []
    k = max(1, min(int(top_k), rows.size))

    if name == "nemotron8b" and data.get("compact") is not None:
        compact = data["compact"]
        qc = q[:COMPACT_DIM]
        qc = qc / (float(np.linalg.norm(qc)) or 1.0)
        cand_n = min(max(RERANK_MIN, k * RERANK_FACTOR), rows.size)
        if rows.size == ids.shape[0]:
            prefix_scores = compact @ qc
        else:
            prefix_scores = compact[rows] @ qc
        cand_pos = _top_indices(prefix_scores, cand_n)
        cand_rows = rows[cand_pos]
        exact = np.asarray(data["full"][cand_rows], dtype=np.float32) @ q
        order = np.argsort(-exact)[:k]
        return [
            {"chunk_id": int(ids[cand_rows[i]]), "score": float(exact[i])}
            for i in order
        ]

    if name == "qwen8b_ar" and data.get("done_compact") is not None:
        compact = data["done_compact"]
        done_rows = data["done_rows"]
        done_ids = data["done_ids"]
        qc = q[:COMPACT_DIM]
        qc = qc / (float(np.linalg.norm(qc)) or 1.0)
        if allowed is not None:
            keep = np.isin(done_ids, allowed)
            positions = np.flatnonzero(keep)
        else:
            positions = np.arange(done_ids.shape[0])
        if positions.size == 0:
            return []
        cand_n = min(max(RERANK_MIN, k * RERANK_FACTOR), positions.size)
        prefix_scores = compact[positions] @ qc
        cand = positions[_top_indices(prefix_scores, cand_n)]
        exact = np.asarray(data["full"][done_rows[cand]], dtype=np.float32) @ q
        order = np.argsort(-exact)[:k]
        return [
            {"chunk_id": int(done_ids[cand[i]]), "score": float(exact[i])}
            for i in order
        ]

    # Slow, exact fallback: full mmap scan over done rows.
    best_scores = np.empty(0, dtype=np.float32)
    best_ids = np.empty(0, dtype=np.int64)
    for start in range(0, rows.size, SEARCH_BLOCK_ROWS):
        block_rows = rows[start:start + SEARCH_BLOCK_ROWS]
        block = np.asarray(data["full"][block_rows], dtype=np.float32)
        scores = block @ q
        sel = _top_indices(scores, min(k, scores.size))
        best_scores = np.concatenate([best_scores, scores[sel]])
        best_ids = np.concatenate([best_ids, ids[block_rows][sel]])
        if best_scores.size > k:
            keep = _top_indices(best_scores, k)
            best_scores, best_ids = best_scores[keep], best_ids[keep]
    order = np.argsort(-best_scores)[:k]
    return [
        {"chunk_id": int(best_ids[i]), "score": float(best_scores[i])}
        for i in order
    ]


def close() -> None:
    with _lock:
        _index_cache.clear()
        _search_cache.clear()
