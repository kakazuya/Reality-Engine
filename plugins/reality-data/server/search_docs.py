"""Hybrid document search over the Reality Engine data root.

Index choice (2026-10-24, updated)
---------------------------------
The current dense indexes are the 4,096-dim cloud-model indexes:
``vector_index_nemotron8b`` (340,887 chunks, tiers 0-2: concall, presentation,
announcement, news, macro) and ``vector_index_qwen8b_ar`` (1,367,706 rows,
tier 3 annual reports; only 61,440 rows have ``done=True`` and only those are
searchable).  Query vectors come from :mod:`query_embed` (DeepInfra
Nemotron-3-Embed-8B / Nebius Qwen3-Embedding-8B).  The old bge-small
``vector_index`` (384-dim) is kept as an optional local leg for when its ONNX
embedder exists, but it is not the primary path.

Search is FTS5 lexical (``intelligence_fts``) + annual-report fact quotes
(``ar_facts.db``) + dense retrieval, fused with reciprocal rank fusion.  When a
provider key or call fails, the dense leg silently degrades and every hit stays
honestly labelled ``fts``.  ``ar_facts`` is queried only for a
``symbol``/ISIN-scoped request: annual reports are stored there (quote + page)
while ``document_chunks`` keeps the other document types, and a symbol-less
scan of the 20 GB AR DB is too slow to sit in the general path.  This is also
the only source that carries a page number and the Prakash Pipes annual-report
passages.

Set ``REALITY_DATA_ROOT`` to point at another data directory (default:
``C:\\Users\\warri\\Downloads\\Info_Diffusion_Model\\reality_engine\\data``).
Every database is opened read-only.  ``warm()`` loads connections, the FTS
indexes and the dense index once; later calls reuse them.  If the dense index
or its query embedder is unavailable, search degrades to lexical only and each
result reports ``source='fts'``.
"""

from __future__ import annotations

import calendar
import json
import logging
import os
import re
import sqlite3
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple
from urllib.request import urlopen

try:
    from reality_engine.db.readonly import connect_ro
except ModuleNotFoundError:  # a script launch may not have the checkout root on sys.path
    sys.path.append(str(Path(__file__).resolve().parents[3]))
    from reality_engine.db.readonly import connect_ro

logger = logging.getLogger("reality_engine.plugins.search_docs")

DEFAULT_DATA_ROOT = Path(
    r"C:\Users\warri\Downloads\Info_Diffusion_Model\reality_engine\data"
)
DB_NAME = "equity_intelligence.db"
AR_DB_NAME = "ar_facts.db"
RRF_K = 60
MAX_QUERY_TOKENS = 12

# Official policy corpus gets a small fusion boost for policy-intent queries so
# "repo rate decision" ranks RBI/MPC statements above company filings that
# merely quote the RBI.  The boost is only applied when the query carries a
# policy term; it never changes a company-document query.
OFFICIAL_TYPES = frozenset({"rbi", "budget", "pib", "economic_survey"})
POLICY_TERMS = frozenset(
    {
        "rbi",
        "mpc",
        "repo",
        "monetary",
        "policy",
        "budget",
        "fiscal",
        "inflation",
        "survey",
        "pib",
        "gdp",
    }
)
POLICY_BOOST = 0.015

_TYPE_ALIASES = {
    "annual": "annual_report",
    "ar": "annual_report",
    "annual_report": "annual_report",
    "concall": "concall",
    "concall_transcript": "concall",
    "transcript": "concall",
    "earnings_call": "concall",
    "presentation": "presentation",
    "investor_presentation": "presentation",
    "deck": "presentation",
    "announcement": "announcement",
    "filing": "announcement",
    "financial_result": "announcement",
    "rbi": "rbi",
    "monetary_policy": "rbi",
    "mpc": "rbi",
    "budget": "budget",
    "union_budget": "budget",
    "state_budget": "budget",
    "pib": "pib",
    "press_release": "pib",
    "economic_survey": "economic_survey",
    "survey": "economic_survey",
    "offer": "offer_document",
    "offer_document": "offer_document",
    "drhp": "offer_document",
    "rhp": "offer_document",
    "news": "news",
    "telegram": "telegram",
    "youtube": "youtube",
}


# ---------------------------------------------------------------------------
# State / warm-up
# ---------------------------------------------------------------------------
class _State:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.db: Optional[sqlite3.Connection] = None
        self.ar: Optional[sqlite3.Connection] = None
        self.vector = None                  # ChunkVectorIndex
        self.embedder = None                # OnnxEmbedder
        self.quarantined: Dict[str, Set[str]] = {
            "master_companies": set(),
            "document_chunks": set(),
            "raw_documents": set(),
            "ar_facts": set(),
        }
        self.status: Dict[str, Any] = {}
        self.lock = threading.RLock()
        self._url_cache: Dict[int, Optional[str]] = {}
        self._ar_docs_cache: Dict[Tuple[Tuple[str, ...], Tuple[str, ...]], List[int]] = {}

    def corporate_url(self, doc_id: int) -> Optional[str]:
        if doc_id in self._url_cache:
            return self._url_cache[doc_id]
        url = None
        if self.db is not None and _has_table(self.db, "corporate_documents"):
            try:
                row = self.db.execute(
                    "SELECT source_url FROM corporate_documents WHERE id = ?",
                    (int(doc_id),),
                ).fetchone()
                url = row[0] if row and row[0] else None
            except sqlite3.Error:
                url = None
        self._url_cache[doc_id] = url
        return url

    def close(self) -> None:
        for con in (self.ar, self.db):
            if con is not None:
                try:
                    con.close()
                except sqlite3.Error:
                    pass
        self.ar = self.db = None
        self.vector = self.embedder = None


_STATE: Optional[_State] = None
_WARM_LOCK = threading.RLock()


def _data_root() -> Path:
    return Path(os.environ.get("REALITY_DATA_ROOT", str(DEFAULT_DATA_ROOT))).expanduser().resolve()


def _open_db(path: Path) -> Optional[sqlite3.Connection]:
    if not path.exists():
        return None
    try:
        con = connect_ro(
            path,
            timeout_s=30,
            check_same_thread=False,
            cache_size_kib=-262144,   # 256 MB page cache
        )
        con.execute("PRAGMA mmap_size = 1073741824")
        return con
    except sqlite3.Error as exc:
        logger.warning("search_docs: cannot open %s: %s", path, exc)
        return None


def _has_table(con: sqlite3.Connection, name: str) -> bool:
    try:
        return (
            con.execute(
                "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name = ?",
                (name,),
            ).fetchone()
            is not None
        )
    except sqlite3.Error:
        return False


def _load_quarantine(con: sqlite3.Connection) -> Dict[str, Set[str]]:
    out: Dict[str, Set[str]] = {
        "master_companies": set(),
        "document_chunks": set(),
        "raw_documents": set(),
        "ar_facts": set(),
    }
    if not _has_table(con, "substrate_quarantine"):
        return out
    try:
        for table, key in con.execute("SELECT table_name, row_key FROM substrate_quarantine"):
            if table in out:
                out[table].add(str(key))
    except sqlite3.Error as exc:
        logger.warning("search_docs: quarantine read failed: %s", exc)
    return out


def _model_dir(root: Path) -> Path:
    return Path(
        os.environ.get("REALITY_EMBED_MODEL_DIR", str(root / "models" / "bge-small-en-v1.5"))
    )


def _server_reachable() -> bool:
    server = os.environ.get("REALITY_ENGINE_EMBED_SERVER", "http://127.0.0.1:8099").rstrip("/")
    try:
        with urlopen(f"{server}/health", timeout=0.5) as response:
            return response.status == 200
    except Exception:
        return False


def _embedder_hint(root: Path) -> bool:
    """Cheap check before importing the heavy ``ingestion`` package."""
    model_dir = _model_dir(root)
    has_files = (model_dir / "tokenizer.json").exists() and any(
        (model_dir / "onnx" / name).exists() for name in ("model.onnx", "model_quantized.onnx")
    )
    if has_files:
        return True
    backend = os.environ.get("REALITY_ENGINE_EMBED_BACKEND", "auto").strip().lower()
    if backend == "onnx":
        return True
    return _server_reachable()


def _load_embedder(root: Path):
    """bge-small ONNX embedder used by the live chunk index (query side only)."""
    from reality_engine.ingestion.onnx_embedder import OnnxEmbedder

    return OnnxEmbedder(model_dir=_model_dir(root))


def _index_meta_rows(index_dir: Path) -> int:
    try:
        return int(json.loads((index_dir / "chunk_index_meta.json").read_text(encoding="utf-8")).get("rows", 0))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return 0


def _load_vector(root: Path):
    """Return (index, embedder, rows, reason); index/embedder None when unavailable."""
    index_dir = root / os.environ.get("REALITY_VECTOR_INDEX", "vector_index")
    if not (index_dir / "chunk_ids.npy").exists():
        return None, None, 0, f"no index at {index_dir}"
    rows = _index_meta_rows(index_dir)
    if not _embedder_hint(root):
        return None, None, rows, "no local embedder model and no embedding server"
    try:
        from reality_engine.search.chunk_vector_index import ChunkVectorIndex

        index = ChunkVectorIndex(index_dir).load()
        embedder = _load_embedder(root)
        probe = embedder.embed("warm up", is_query=True)
        matrix = getattr(index, "_vecs", None)
        if matrix is None or not probe or len(probe) != int(matrix.shape[1]):
            return None, None, rows, "embedder unavailable"
        rows = int(getattr(index, "_meta", {}).get("rows", matrix.shape[0]))
        return index, embedder, rows, None
    except Exception as exc:  # missing onnxruntime/tokenizer/model, corrupt index, ...
        return None, None, rows, f"{type(exc).__name__}: {exc}"


def _warm_fts(state: _State) -> None:
    """Score a few common phrases so the first user query is not a cold FTS read."""
    # AR facts are reached through the company-scoped ar_facts_doc scan; the
    # 20 GB ar_facts FTS is deliberately not in the hot path, so do not pay its
    # cold-page cost at startup.
    warm = {
        "intelligence_fts": ('"revenue"', '"repo rate"', '"order book"'),
    }
    for table, terms in warm.items():
        con = state.db if table == "intelligence_fts" else state.ar
        if con is None or not _has_table(con, table):
            continue
        for expr in terms:
            try:
                con.execute(
                    f"SELECT rowid FROM {table} WHERE {table} MATCH ? "
                    f"ORDER BY bm25({table}) LIMIT 1",
                    (expr,),
                ).fetchall()
            except sqlite3.Error as exc:
                logger.debug("search_docs: FTS warm miss on %s (%s): %s", table, expr, exc)


def warm(force: bool = False) -> Dict[str, Any]:
    """Load connections, FTS indexes and the dense index once; return a status dict."""
    global _STATE
    started = time.perf_counter()
    root = _data_root()
    with _WARM_LOCK:
        if (
            _STATE is not None
            and _STATE.root == root
            and not force
            and _STATE.status
        ):
            return dict(_STATE.status)

        if _STATE is not None:
            _STATE.close()
        state = _State(root)
        _STATE = state

        state.db = _open_db(root / DB_NAME)
        state.ar = _open_db(root / AR_DB_NAME)
        if state.ar is not None and not (
            _has_table(state.ar, "ar_facts") and _has_table(state.ar, "ar_docs")
        ):
            state.ar.close()
            state.ar = None
        if state.db is not None:
            state.quarantined = _load_quarantine(state.db)

        index, embedder, index_rows, reason = _load_vector(root)
        state.vector, state.embedder = index, embedder
        _warm_fts(state)

        dense: Dict[str, Any] = {}
        try:
            import query_embed
            dense = {
                name: query_embed.index_info(name)
                for name in ("nemotron8b", "qwen8b_ar")
            }
            query_embed.warm()  # maps headers/done masks; no provider call
        except Exception as exc:  # query_embed missing/broken: FTS fallback
            logger.debug("search_docs: query_embed status unavailable: %s", exc)
        dense_available = any(
            info.get("available") and info.get("done_rows", 0) > 0 for info in dense.values()
        )
        bge_available = index is not None and embedder is not None

        state.status = {
            "root": str(root),
            "db": str(root / DB_NAME),
            "db_ok": state.db is not None,
            "ar_facts": state.ar is not None,
            "vector_index": str(root / os.environ.get("REALITY_VECTOR_INDEX", "vector_index")),
            "vector_index_rows": index_rows,
            "embedder": "bge-small-en-v1.5" if embedder is not None else None,
            "vector": bge_available,
            "dense": dense,
            "dense_available": dense_available,
            "fallback": None if (bge_available or dense_available) else "fts-only",
            "vector_note": reason,
            "warm_seconds": round(time.perf_counter() - started, 3),
        }
        logger.info("search_docs warm: %s", state.status)
        return dict(state.status)


def status() -> Dict[str, Any]:
    """Last warm-up status (does not trigger a load)."""
    state = _STATE
    if state is None or not state.status:
        return {"warm": False, "root": str(_data_root())}
    return dict(state.status)


def close() -> None:
    """Release the warm connections (useful for tests / server shutdown)."""
    global _STATE
    with _WARM_LOCK:
        if _STATE is not None:
            _STATE.close()
            _STATE = None


def _state() -> Optional[_State]:
    warm()
    return _STATE


# ---------------------------------------------------------------------------
# Filters and ranking
# ---------------------------------------------------------------------------
def _canonical_type(source_type: Optional[str]) -> str:
    s = (source_type or "").strip().upper()
    if not s:
        return "other"
    if s.startswith("RBI") or "MONETARY_POLICY" in s or "MPC" in s:
        return "rbi"
    if "BUDGET" in s:
        return "budget"
    if "PIB" in s:
        return "pib"
    if "ECONOMIC_SURVEY" in s:
        return "economic_survey"
    if "ANNUAL" in s and "REPORT" in s:
        return "annual_report"
    if "CONCALL" in s or "TRANSCRIPT" in s:
        return "concall"
    if "PRESENTATION" in s or "DECK" in s or "INVESTOR" in s:
        return "presentation"
    if "ANNOUNCEMENT" in s or "FILING" in s or "FINANCIAL_RESULT" in s:
        return "announcement"
    if "OFFER" in s or "DRHP" in s or "RHP" in s:
        return "offer_document"
    if "TELEGRAM" in s:
        return "telegram"
    if "YOUTUBE" in s:
        return "youtube"
    if "NEWS" in s:
        return "news"
    return s.lower()


def _requested_types(doc_types) -> Optional[Set[str]]:
    if doc_types is None:
        return None
    if isinstance(doc_types, str):
        doc_types = [doc_types]
    out: Set[str] = set()
    for raw in doc_types:
        key = re.sub(r"[^a-z0-9]+", "_", str(raw or "").lower()).strip("_")
        if key:
            out.add(_TYPE_ALIASES.get(key, key))
    return out or None


def _date_bound(value, end: bool) -> Optional[str]:
    if value is None or str(value).strip() == "":
        return None
    s = str(value).strip()
    match = re.fullmatch(r"(\d{4})(?:-(\d{1,2}))?(?:-(\d{1,2}))?", s)
    if not match:
        raise ValueError(f"invalid date {value!r}; use YYYY, YYYY-MM or YYYY-MM-DD")
    year = int(match.group(1))
    month = int(match.group(2) or (12 if end else 1))
    if not 1 <= month <= 12:
        raise ValueError(f"invalid date {value!r}")
    last_day = calendar.monthrange(year, month)[1]
    if match.group(3):
        day = int(match.group(3))
    elif end:
        day = last_day
    else:
        day = 1
    if not 1 <= day <= last_day:
        raise ValueError(f"invalid date {value!r}")
    return f"{year:04d}-{month:02d}-{day:02d}"


def _query_tokens(query: str) -> List[str]:
    return [t.lower() for t in re.findall(r"[A-Za-z0-9]+", query or "")][:MAX_QUERY_TOKENS]


def _fts_exprs(
    query: str,
    aliases: Optional[Iterable[str]] = None,
    isins: Optional[Iterable[str]] = None,
) -> List[str]:
    """FTS5 expressions: exact phrase first, then all-terms (implicit AND).

    No OR fallback: on the 2.26M-row FTS table an OR of common terms costs
    5-15 s cold, and the caller still gets phrase/AND hits in milliseconds.
    """
    tokens = _query_tokens(query)
    if not tokens:
        return []
    quoted = [f'"{t}"' for t in tokens]
    if len(tokens) == 1:
        cores = [quoted[0]]
    else:
        cores = [
            '"' + " ".join(tokens) + '"',   # phrase
            " ".join(quoted),               # implicit AND
        ]
    cols: List[str] = []
    for alias in sorted(aliases or ()):
        alias = re.sub(r"[^A-Za-z0-9_-]", "", str(alias))
        if alias:
            cols.append(f'symbol:"{alias}"')
    for isin in sorted(isins or ()):
        isin = re.sub(r"[^A-Za-z0-9]", "", str(isin))
        if isin:
            cols.append(f'isin:"{isin}"')
    if not cols:
        return cores
    col_expr = " OR ".join(cols)
    return [f"({core}) AND ({col_expr})" for core in cores]


def _passes(
    doc_type: str,
    date: str,
    isin: str,
    types: Optional[Set[str]],
    date_from: Optional[str],
    date_to: Optional[str],
) -> bool:
    if types is not None and doc_type not in types:
        return False
    if isin and str(isin).upper().startswith("INE_AUTO"):
        return False
    if date_from or date_to:
        d = (date or "")[:10]
        if not d:
            return False
        if date_from and d < date_from:
            return False
        if date_to and d > date_to:
            return False
    return True


def _resolve_symbol(state: _State, symbol: Optional[str]) -> Tuple[Set[str], Set[str]]:
    aliases: Set[str] = set()
    isins: Set[str] = set()
    if not symbol or not str(symbol).strip():
        return aliases, isins
    raw = str(symbol).strip()
    aliases.add(raw.upper())
    if len(raw) == 12 and raw.upper().startswith(("INE", "INF")):
        isins.add(raw.upper())
    if state.db is not None and _has_table(state.db, "master_companies"):
        try:
            row = state.db.execute(
                "SELECT isin, nse_symbol, bse_code FROM master_companies "
                "WHERE upper(nse_symbol) = ? OR isin = ? OR bse_code = ? LIMIT 1",
                (raw.upper(), raw.upper(), raw),
            ).fetchone()
        except sqlite3.Error:
            row = None
        if row:
            for value in row:
                if not value:
                    continue
                value = str(value).strip()
                if len(value) == 12 and value.upper().startswith(("INE", "INF")):
                    isins.add(value.upper())
                else:
                    aliases.add(value.upper())
    return aliases, isins


# ---------------------------------------------------------------------------
# Equity chunks: FTS5 and dense
# ---------------------------------------------------------------------------
_FTS_SQL = """
SELECT intelligence_fts.chunk_id, intelligence_fts.symbol, intelligence_fts.isin,
       intelligence_fts.source_type, intelligence_fts.document_date,
       intelligence_fts.document_text,
       dc.doc_id AS dc_doc_id, dc.published_date AS chunk_date,
       rd.doc_id AS raw_doc_id, rd.source_url, rd.published_date AS raw_date,
       rd.source_type AS raw_type
FROM intelligence_fts
LEFT JOIN document_chunks dc ON dc.chunk_id = intelligence_fts.chunk_id
LEFT JOIN raw_documents rd ON rd.doc_id = dc.doc_id
WHERE intelligence_fts MATCH ?
ORDER BY bm25(intelligence_fts)
LIMIT ?
"""


def _run_fts(con: sqlite3.Connection, exprs: Sequence[str], limit: int) -> List[Sequence[Any]]:
    best: List[Sequence[Any]] = []
    for expr in exprs:
        try:
            rows = con.execute(_FTS_SQL, (expr, int(limit))).fetchall()
        except sqlite3.Error as exc:
            logger.debug("search_docs: FTS expression failed (%s): %s", expr, exc)
            continue
        if rows:
            best = rows
            if len(rows) >= min(3, limit):
                break
    return best


def _equity_fts_rows(
    state: _State,
    query: str,
    aliases: Set[str],
    isins: Set[str],
    limit: int,
) -> List[Dict[str, Any]]:
    if state.db is None or not _has_table(state.db, "intelligence_fts"):
        return []
    exprs = _fts_exprs(query, aliases, isins)
    if not exprs:
        return []
    out: List[Dict[str, Any]] = []
    for row in _run_fts(state.db, exprs, limit):
        cid, sym, isin, source_type, f_date, text, dc_id, chunk_date, raw_id, url, raw_date, raw_type = row
        text = text or ""
        if not text.strip():
            continue
        doc_id = raw_id if raw_id is not None else cid
        date = (f_date or chunk_date or raw_date or "")[:10]
        doc_type = _canonical_type(source_type or raw_type)
        out.append(
            {
                "text": text,
                "doc_id": doc_id,
                "doc_type": doc_type,
                "symbol": sym or "",
                "isin": isin or "",
                "date": date,
                "page": None,
                "url": url or None,
                "key": f"chunk:{cid}",
                "_cid": cid,
                "_doc_id": dc_id if dc_id is not None else raw_id,
                "_isin": isin or "",
            }
        )
    return out


def _allowed_chunk_ids(state: _State, aliases: Set[str], isins: Set[str]) -> Optional[Set[int]]:
    """Chunk ids for a symbol/ISIN-scoped request; None means no scope."""
    if not (aliases or isins):
        return None
    if state.db is None or not _has_table(state.db, "document_chunks"):
        return set()
    clauses, params = [], []
    if aliases:
        clauses.append(f"symbol IN ({','.join('?' * len(aliases))})")
        params.extend(sorted(aliases))
    if isins:
        clauses.append(f"isin IN ({','.join('?' * len(isins))})")
        params.extend(sorted(isins))
    try:
        return {
            int(r[0])
            for r in state.db.execute(
                f"SELECT chunk_id FROM document_chunks WHERE {' OR '.join(clauses)}",
                params,
            )
        }
    except sqlite3.Error:
        return set()


def _rows_from_hits(state: _State, hits: Sequence[Dict[str, Any]],
                    limit: int) -> List[Dict[str, Any]]:
    if not hits or state.db is None:
        return []
    ids = [int(h["chunk_id"]) for h in hits]
    placeholders = ",".join("?" * len(ids))
    try:
        rows = state.db.execute(
            f"""SELECT dc.chunk_id, dc.doc_id, dc.symbol, dc.isin, dc.content,
                       dc.published_date, rd.source_type, rd.source_url, rd.published_date
                FROM document_chunks dc
                LEFT JOIN raw_documents rd ON rd.doc_id = dc.doc_id
                WHERE dc.chunk_id IN ({placeholders})""",
            ids,
        ).fetchall()
    except sqlite3.Error:
        return []
    by_id = {int(r[0]): r for r in rows}
    out: List[Dict[str, Any]] = []
    for hit in hits:
        row = by_id.get(int(hit["chunk_id"]))
        if row is None:
            continue
        cid, doc_id, sym, isin, text, chunk_date, source_type, url, raw_date = row
        text = text or ""
        if not text.strip():
            continue
        out.append(
            {
                "text": text,
                "doc_id": doc_id if doc_id is not None else cid,
                "doc_type": _canonical_type(source_type),
                "symbol": sym or "",
                "isin": isin or "",
                "date": (chunk_date or raw_date or "")[:10],
                "page": None,
                "url": url or None,
                "key": f"chunk:{cid}",
                "_cid": cid,
                "_doc_id": doc_id,
                "_isin": isin or "",
            }
        )
        if len(out) >= limit:
            break
    return out


def _vector_rows(
    state: _State,
    query_vec: Sequence[float],
    aliases: Set[str],
    isins: Set[str],
    limit: int,
) -> List[Dict[str, Any]]:
    if state.vector is None or state.db is None:
        return []
    allowed = _allowed_chunk_ids(state, aliases, isins)
    if allowed is not None and not allowed:
        return []
    try:
        hits = state.vector.search(query_vec, top_k=max(limit, 1), allow_ids=allowed)
    except Exception as exc:  # index/embedder mismatch, corrupt rows
        logger.debug("search_docs: vector search miss: %s", exc)
        return []
    return _rows_from_hits(state, hits, limit)


def _dense_rows(
    state: _State,
    query: str,
    index_name: str,
    aliases: Set[str],
    isins: Set[str],
    limit: int,
) -> List[Dict[str, Any]]:
    """4096-d cloud-index dense leg; returns [] on any key/provider failure."""
    if state.db is None:
        return []
    try:
        import query_embed
    except Exception as exc:  # pragma: no cover - import error
        logger.debug("search_docs: query_embed unavailable: %s", exc)
        return []
    allowed = _allowed_chunk_ids(state, aliases, isins)
    if allowed is not None and not allowed:
        return []
    try:
        info = query_embed.index_info(index_name)
        if not info.get("available") or not info.get("done_rows"):
            return []
    except Exception:
        return []
    try:
        query_vec = query_embed.embed_query(query, index_name)
        hits = query_embed.search_index(
            query_vec, index_name, top_k=max(limit, 1), allow_ids=allowed
        )
    except Exception as exc:
        logger.debug("search_docs: dense %s miss: %s", index_name, exc)
        return []
    return _rows_from_hits(state, hits, limit)


# ---------------------------------------------------------------------------
# Annual-report facts (quote + page; the annual-report corpus lives here)
# ---------------------------------------------------------------------------
def _ar_text(item: str, value_raw: str, quote: str) -> str:
    item = (item or "").strip()
    quote = (quote or "").strip()
    if quote and item and item.lower() not in quote.lower():
        return f"{item} — {quote}"
    return quote or (f"{item}: {value_raw}" if item else "")


def _ar_dict(state: _State, row: Sequence[Any]) -> Optional[Dict[str, Any]]:
    rowid, doc_id, isin, symbol, page, filed_at, category, item, value_raw, quote, doc_filed = row
    if doc_id is not None and str(doc_id) in state.quarantined["ar_facts"]:
        return None
    if isin and str(isin).upper().startswith("INE_AUTO"):
        return None
    text = _ar_text(item, value_raw, quote)
    if not text:
        return None
    return {
        "text": text,
        "doc_id": int(doc_id) if doc_id is not None else rowid,
        "doc_type": "annual_report",
        "symbol": symbol or "",
        "isin": isin or "",
        "date": (filed_at or doc_filed or "")[:10],
        "page": int(page) if page is not None else None,
        "url": state.corporate_url(int(doc_id)) if doc_id is not None else None,
        "key": f"ar:{rowid}",
        "_cid": None,
        "_doc_id": doc_id,
        "_isin": isin or "",
        "_category": category or "",
    }


def _ar_rows_scoped(
    state: _State,
    query: str,
    aliases: Set[str],
    isins: Set[str],
    limit: int,
) -> List[Dict[str, Any]]:
    """Company-scoped annual-report scan.

    The ``ar_facts`` table is ~20 GB: fetching a handful of scattered quote
    rows cold can take seconds.  A symbol query touches only that company's
    facts through ``ar_facts_doc`` (a few thousand rows) and filters the query
    terms in Python.
    """
    tokens = _query_tokens(query)
    if not tokens:
        return []
    cache_key = (tuple(sorted(aliases)), tuple(sorted(isins)))
    doc_ids = state._ar_docs_cache.get(cache_key)
    if doc_ids is None:
        clauses, params = [], []
        if aliases:
            clauses.append(f"symbol IN ({','.join('?' * len(aliases))})")
            params.extend(sorted(aliases))
        if isins:
            clauses.append(f"isin IN ({','.join('?' * len(isins))})")
            params.extend(sorted(isins))
        try:
            doc_ids = [
                int(r[0])
                for r in state.ar.execute(
                    f"SELECT doc_id FROM ar_docs WHERE {' OR '.join(clauses)}", params
                )
            ]
        except sqlite3.Error:
            return []
        state._ar_docs_cache[cache_key] = doc_ids
    if not doc_ids:
        return []

    # ponytail: reads every fact for the company (~4k rows for PPL); switch to
    # an indexed token lookup if a company ever exceeds ~100k facts.
    placeholders = ",".join("?" * len(doc_ids))
    try:
        rows = state.ar.execute(
            f"""SELECT f.rowid, f.doc_id, f.isin, f.symbol, f.page, f.filed_at,
                       f.category, f.item, f.value_raw, f.quote, d.filed_at
                FROM ar_facts f
                LEFT JOIN ar_docs d ON d.doc_id = f.doc_id
                WHERE f.doc_id IN ({placeholders})""",
            doc_ids,
        ).fetchall()
    except sqlite3.Error:
        return []

    phrase = " ".join(tokens)
    scored: List[Tuple[int, Sequence[Any]]] = []
    for row in rows:
        item = (row[7] or "").lower()
        quote = (row[9] or "").lower()
        blob = f"{item} {quote} {(row[6] or '').lower()} {(row[8] or '').lower()}"
        matched = sum(1 for token in tokens if token in blob)
        if not matched:
            continue
        score = matched
        if phrase and phrase in blob:
            score += 3
        if all(token in item for token in tokens):
            score += 2
        scored.append((score, row))
    scored.sort(key=lambda item: (-item[0], item[1][0]))

    out: List[Dict[str, Any]] = []
    seen: Set[Tuple[Any, Any, str]] = set()
    for _, row in scored:
        record = _ar_dict(state, row)
        if record is None:
            continue
        dedup = (record["doc_id"], record["page"], record["text"][:200])
        if dedup in seen:
            continue
        seen.add(dedup)
        out.append(record)
        if len(out) >= limit:
            break
    return out


def _ar_rows(
    state: _State,
    query: str,
    aliases: Set[str],
    isins: Set[str],
    limit: int,
) -> List[Dict[str, Any]]:
    """AR fact quotes, only when the caller names a company.

    A symbol-less ``ar_facts_fts`` query over the 20 GB AR database costs
    10-15 s cold (the equity FTS already covers the general document corpus);
    symbol/ISIN-scoped queries read a few thousand rows through
    ``ar_facts_doc`` and stay under the latency budget.
    """
    if state.ar is None or not (aliases or isins):
        return []
    return _ar_rows_scoped(state, query, aliases, isins, limit)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def search_docs(
    query: str,
    symbol: Optional[str] = None,
    doc_types: Optional[Sequence[str]] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    top_k: int = 10,
) -> List[Dict[str, Any]]:
    """Hybrid document search.

    Returns up to ``top_k`` passages with keys ``text``, ``doc_id``,
    ``doc_type``, ``symbol``, ``isin``, ``date``, ``page``, ``url``,
    ``score`` and ``source``.  ``source`` is ``vector``, ``fts`` or ``both``;
    when the dense index/embedder is unavailable every hit is ``fts`` (the
    fallback is reported by :func:`warm`/:func:`status`).
    """
    if not query or not str(query).strip():
        return []
    try:
        top_k = int(top_k)
    except (TypeError, ValueError):
        return []
    if top_k <= 0:
        return []

    types = _requested_types(doc_types)
    date_lo = _date_bound(date_from, end=False)
    date_hi = _date_bound(date_to, end=True)
    if date_lo and date_hi and date_lo > date_hi:
        raise ValueError("date_from is after date_to")

    state = _state()
    if state is None or (state.db is None and state.ar is None):
        return []

    with state.lock:
        aliases, isins = _resolve_symbol(state, symbol)
        pool = min(max(top_k * 6, 40), 240)

        fts_rows = [
            row
            for row in _equity_fts_rows(state, query, aliases, isins, pool)
            if _passes(row["doc_type"], row["date"], row["isin"], types, date_lo, date_hi)
            and str(row["_isin"]).upper() not in state.quarantined["master_companies"]
            and str(row["_cid"]) not in state.quarantined["document_chunks"]
            and str(row["_doc_id"]) not in state.quarantined["raw_documents"]
        ]
        ar_rows = [
            row
            for row in _ar_rows(state, query, aliases, isins, pool)
            if _passes(row["doc_type"], row["date"], row["isin"], types, date_lo, date_hi)
        ]

        vector_rows: List[Dict[str, Any]] = []
        if state.vector is not None and state.embedder is not None:
            try:
                query_vec = state.embedder.embed(query, is_query=True)
            except Exception as exc:
                logger.debug("search_docs: query embed miss: %s", exc)
                query_vec = None
            if query_vec:
                vector_rows = [
                    row
                    for row in _vector_rows(state, query_vec, aliases, isins, pool)
                    if _passes(row["doc_type"], row["date"], row["isin"], types, date_lo, date_hi)
                    and str(row["_isin"]).upper() not in state.quarantined["master_companies"]
                    and str(row["_cid"]) not in state.quarantined["document_chunks"]
                    and str(row["_doc_id"]) not in state.quarantined["raw_documents"]
                ]

        def _add_dense(index_name: str) -> None:
            rows = _dense_rows(state, query, index_name, aliases, isins, pool)
            for row in rows:
                if not _passes(row["doc_type"], row["date"], row["isin"], types, date_lo, date_hi):
                    continue
                if str(row["_isin"]).upper() in state.quarantined["master_companies"]:
                    continue
                if str(row["_cid"]) in state.quarantined["document_chunks"]:
                    continue
                if str(row["_doc_id"]) in state.quarantined["raw_documents"]:
                    continue
                vector_rows.append(row)

        # Tier split: qwen8b_ar carries annual reports (tier 3); nemotron8b
        # carries concall/presentation/announcement/news/macro (tiers 0-2).
        if types is None or "annual_report" in types:
            _add_dense("qwen8b_ar")
        if types is None or bool(types - {"annual_report"}):
            _add_dense("nemotron8b")
        # A chunk can be returned by both the optional bge leg and a 4096-d leg.
        seen_vec = set()
        vector_rows = [
            row for row in vector_rows
            if not (row["key"] in seen_vec or seen_vec.add(row["key"]))
        ]

        # Reciprocal rank fusion.  Equity FTS first (it carries the richest
        # metadata), then AR facts, then the dense list.
        merged: Dict[str, Dict[str, Any]] = {}

        def add(rows: List[Dict[str, Any]], source: str) -> None:
            for rank, row in enumerate(rows, 1):
                entry = merged.setdefault(
                    row["key"], {"row": row, "score": 0.0, "sources": set()}
                )
                entry["score"] += 1.0 / (RRF_K + rank)
                entry["sources"].add(source)

        add(fts_rows, "fts")
        add(ar_rows, "fts")
        add(vector_rows, "vector")

        tokens = set(_query_tokens(query))
        policy_query = bool(tokens & POLICY_TERMS)
        ranked: List[Tuple[float, Dict[str, Any]]] = []
        for entry in merged.values():
            score = entry["score"]
            row = entry["row"]
            if policy_query and row["doc_type"] in OFFICIAL_TYPES:
                score += POLICY_BOOST
            ranked.append((score, entry))
        ranked.sort(key=lambda item: item[0], reverse=True)

        out: List[Dict[str, Any]] = []
        for score, entry in ranked[:top_k]:
            row = entry["row"]
            sources = entry["sources"]
            source = "both" if len(sources) > 1 else next(iter(sources))
            out.append(
                {
                    "text": row["text"],
                    "doc_id": row["doc_id"],
                    "doc_type": row["doc_type"],
                    "symbol": row["symbol"],
                    "isin": row["isin"],
                    "date": row["date"],
                    "page": row["page"],
                    "url": row["url"],
                    "score": round(float(score), 6),
                    "source": source,
                }
            )
        return out


__all__ = ["search_docs", "warm", "status", "close"]
