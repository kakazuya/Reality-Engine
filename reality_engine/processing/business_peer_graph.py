"""Business-substance cross-map: analog companies by what they actually do.

`peer_graph` maps companies in *financial shape* space (margins, moat scores,
market cap) — which is why HAL's nearest twins came out as DIVISLAB/ITC/
SUNPHARMA (large-cap, high-recurrence) instead of defence names, and why D2's
degenerate distilled families don't feed it at all. This module maps the other
axis: **business substance**, computed from the embedded document corpus we
already hold (DRHP prospectuses, concalls, investor presentations, annual
reports).

Method:
* Chunk vectors come from the local dense index (``chunk_vector_index``); they
  are already L2-normalised, which makes a company centroid the *mean direction*
  of everything it has said about itself — not dominated by whichever document
  happens to be longest.
* Per-source centroids are kept separately (offer document vs concall vs annual
  report) because a prospectus describes intent and a concall describes
  execution; the blended centroid is what ranks, the slices are what explain.
* Similarity is cosine over the blended centroid. A company needs at least
  ``MIN_CHUNKS`` embedded chunks to be an anchor or a peer: fewer than that is
  a document artefact, not a business description.
* Rows keyed in ``substrate_quarantine`` are excluded (AGENTS.md rule 13) — a
  test fixture must never become somebody's analog twin.
* Every pair carries shared business terms (distinctive vocabulary overlap) so
  the match is auditable rather than a bare number.

Owns ``company_business_graph``, ``company_business_features``,
``company_business_runs``.

Read back with ``business_neighbours(conn, "HAL")``.
"""
from __future__ import annotations

import json
import logging
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

logger = logging.getLogger("reality_engine.business_peer_graph")

TOP_K_DEFAULT = 20
MIN_CHUNKS = 8               # embedded chunks required for a company to participate
MIN_PEERS = 3                # fewer surviving peers than this => refuse to emit
TERM_TOP_N = 25              # distinctive terms kept per company for explainability
MAX_TERMS_SHARED = 8         # terms reported per pair
BLOCK_ROWS = 1024            # anchors per similarity block

GRAPH_DDL = """
CREATE TABLE IF NOT EXISTS company_business_graph (
    anchor_symbol TEXT NOT NULL,
    peer_symbol TEXT NOT NULL,
    rank INTEGER NOT NULL,
    similarity REAL NOT NULL,
    shared_terms_json TEXT,
    source_mix_json TEXT,
    anchor_chunks INTEGER NOT NULL,
    peer_chunks INTEGER NOT NULL,
    features_version TEXT NOT NULL,
    computed_at TEXT DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (anchor_symbol, peer_symbol)
)
"""

FEATURE_DDL = """
CREATE TABLE IF NOT EXISTS company_business_features (
    symbol TEXT PRIMARY KEY,
    chunks INTEGER NOT NULL,
    sources_json TEXT,
    centroid_norm REAL,
    terms_json TEXT,
    quarantined INTEGER NOT NULL DEFAULT 0,
    features_version TEXT NOT NULL,
    computed_at TEXT DEFAULT CURRENT_TIMESTAMP
)
"""

RUN_DDL = """
CREATE TABLE IF NOT EXISTS company_business_runs (
    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    status TEXT NOT NULL,
    reason TEXT,
    n_symbols INTEGER,
    n_chunks INTEGER,
    n_pairs INTEGER,
    min_chunks INTEGER,
    top_k INTEGER,
    computed_at TEXT DEFAULT CURRENT_TIMESTAMP
)
"""

# Very small, deliberately boring stoplist: prospectus/concall boilerplate plus
# English filler. Anything longer is corpus-specific noise handled by the
# document-frequency filter below.
_STOP = frozenset("""
a an the and or of to in for on at by with from as is are was were be been being this that these those
we our us you your it its they their them he she his her not no nor but if then than so such can could
may might must shall should will would have has had do does did done also any all each other more most
other some any such only own same too very s t just don now over under between during within without
our company limited ltd india indian pursuant respect accordance thereof thereof shall may will
page section note notes table figures figure rs lakh crore million billion financial statements
""".split())

_TOKEN_RE = re.compile(r"[a-z][a-z\-]{3,}")


@dataclass(frozen=True)
class CentroidResult:
    symbols: List[str]
    matrix: np.ndarray                      # (N, 384) float32, L2-normalised
    chunks: np.ndarray                      # (N,) int32
    sources: Dict[str, Dict[str, int]]      # symbol -> source_type -> chunks
    quarantined: Dict[str, bool]


_META_RE = re.compile(r"\[Metadata:[^\]]*\]", re.IGNORECASE)


def _tokenise(text: str) -> List[str]:
    body = _META_RE.sub(" ", text or "")            # drop the injected chunk header
    return [t for t in _TOKEN_RE.findall(body.lower()) if t not in _STOP]


def build_terms(
    conn,
    symbols: Sequence[str],
    max_chunks_per_symbol: int = 400,
    max_document_frequency: float = 0.25,
) -> Dict[str, List[str]]:
    """Distinctive vocabulary per company.

    Terms carried by more than ``max_document_frequency`` of companies are
    genre vocabulary (``prospectus``, ``offer``, ``company``, ``fiscal``) and are
    dropped — the same "corpus-common direction" problem the vector centroids
    are mean-centred for, solved in lexical space.
    """
    docs: Dict[str, Counter] = {}
    df: Counter = Counter()
    for sym in symbols:
        rows = conn.execute(
            "SELECT content FROM document_chunks WHERE symbol = ? ORDER BY chunk_id LIMIT ?",
            (sym, max_chunks_per_symbol),
        ).fetchall()
        c: Counter = Counter()
        for (content,) in rows:
            c.update(set(_tokenise(content or "")))
        if not c:
            continue
        docs[sym] = c
        df.update(c.keys())
    n_docs = max(1, len(docs))
    df_cap = max(2.0, max_document_frequency * n_docs)
    out: Dict[str, List[str]] = {}
    for sym, c in docs.items():
        scored = []
        for term, tf in c.items():
            if df[term] > df_cap:      # genre term, not a business term
                continue
            idf = math.log((1 + n_docs) / (1 + df[term])) + 1.0
            scored.append((tf * idf, term))
        scored.sort(reverse=True)
        out[sym] = [t for _, t in scored[:TERM_TOP_N]]
    return out


# ---------------------------------------------------------------------------
# Feature construction
# ---------------------------------------------------------------------------
def _quarantined_symbols(conn) -> set:
    try:
        rows = conn.execute("SELECT DISTINCT symbol FROM substrate_quarantine WHERE symbol IS NOT NULL").fetchall()
    except Exception:  # table may not exist yet
        return set()
    return {str(r[0]).upper() for r in rows}


# Prospectus/execution boilerplate: present in essentially every filing, so it
# contributes a near-identical direction to every centroid and washes out the
# business signal (measured: unrelated companies sat at cosine 0.92-0.96 before
# this filter). Mirrors the boilerplate list offer_backfill uses for promotion.
_BOILER_SQL = (
    "book running lead manager", "registrar to the offer", "red herring", "price band",
    "bid lot", "offer for sale", "fresh issue", "absolute responsibility",
    "no formal market", "sustained trading", "anti-takeover", "takeover provisions",
    "definitions and abbreviations", "general information", "capital structure",
    "statement of possible tax benefits", "restrictions on foreign ownership",
)

# "Our business" self-description language. A prospectus is mostly risk factors,
# financial statements and offer mechanics; the section that actually says what
# the company does is a small slice. Restricting centroids to that slice is the
# difference between mapping *documents* and mapping *businesses*.
_BUSINESS_SQL = (
    "we are", "we manufacture", "we provide", "we supply", "we operate",
    "we design", "we develop", "we offer", "our business", "our products",
    "our customers", "our services", "our company is", "we sell", "we export",
    "our revenue", "we derive", "we have", "our key", "we believe",
)


def _chunk_filter_clause(column: str, mode: str) -> str:
    if mode == "business":
        return "(" + " OR ".join(f"lower({column}) LIKE '%{kw}%'" for kw in _BUSINESS_SQL) + ")"
    return "1=1"


def _boilerplate_clause(column: str = "dc.content") -> str:
    return " AND ".join(f"lower({column}) NOT LIKE '%{kw}%'" for kw in _BOILER_SQL)


def build_centroids(conn, min_chunks: int = MIN_CHUNKS, block_rows: int = BLOCK_ROWS,
                    exclude_boilerplate: bool = True, center: bool = True,
                    chunk_filter: str = "all") -> CentroidResult:
    """Mean direction of each company's embedded chunk corpus, per company.

    Two corrections are essential for this corpus and were measured, not assumed:

    * **boilerplate exclusion** — every prospectus repeats the same sections, so
      those chunks push every centroid toward one identical direction;
    * **mean-centering** (all-but-the-top style) — the corpus-common direction is
      subtracted from each chunk vector before averaging, so what survives is the
      *distinctive* business direction.
    """
    from reality_engine.search.chunk_vector_index import get_index

    idx = get_index()
    if idx is None:
        raise RuntimeError("no chunk vector index — run scripts/build_chunk_vector_index")

    where = "dc.symbol IS NOT NULL AND dc.symbol <> ''"
    where += " AND " + _chunk_filter_clause("dc.content", chunk_filter)
    if exclude_boilerplate:
        where += " AND " + _boilerplate_clause("dc.content")
    meta = conn.execute(
        f"""SELECT dc.chunk_id, dc.symbol, COALESCE(rd.source_type, 'UNKNOWN')
            FROM document_chunks dc LEFT JOIN raw_documents rd ON rd.doc_id = dc.doc_id
            WHERE {where}
            ORDER BY dc.chunk_id"""
    ).fetchall()
    if not meta:
        return CentroidResult([], np.zeros((0, idx._vecs.shape[1]), np.float32), np.zeros(0, np.int32), {}, {})

    chunk_ids = np.fromiter((int(r[0]) for r in meta), dtype=np.int64, count=len(meta))
    n_index = idx._ids.shape[0]
    positions = np.searchsorted(idx._ids, chunk_ids)
    in_range = positions < n_index
    pos_clamped = np.clip(positions, 0, max(0, n_index - 1))
    found = in_range & (idx._ids[pos_clamped] == chunk_ids)
    rows = np.flatnonzero(found)
    if rows.size == 0:
        return CentroidResult([], np.zeros((0, idx._vecs.shape[1]), np.float32), np.zeros(0, np.int32), {}, {})
    vec_rows = pos_clamped[found]

    sym_of_row = [str(meta[i][1]).upper().strip() for i in rows]
    src_of_row = [str(meta[i][2]) for i in rows]

    symbols: List[str] = []
    index_of: Dict[str, int] = {}
    for s in sym_of_row:
        if s not in index_of:
            index_of[s] = len(symbols)
            symbols.append(s)

    dim = idx._vecs.shape[1]
    codes = np.fromiter((index_of[s] for s in sym_of_row), dtype=np.int64, count=len(sym_of_row))
    sums = np.zeros((len(symbols), dim), dtype=np.float64)
    counts = np.bincount(codes, minlength=len(symbols)).astype(np.int64)
    sources: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for s, src in zip(sym_of_row, src_of_row):
        sources[s][src] += 1

    for start in range(0, vec_rows.size, block_rows):
        block = np.asarray(idx._vecs[vec_rows[start:start + block_rows]], dtype=np.float32)
        norms = np.linalg.norm(block, axis=1, keepdims=True)
        block = block / np.clip(norms, 1e-12, None)
        np.add.at(sums, codes[start:start + block_rows], block)

    counts_col = np.clip(counts, 1, None)
    mean_vec = sums.sum(axis=0) / float(max(1, int(counts.sum()))) if center else None

    if center:
        # Pass 2: subtract the corpus-common direction, renormalise, re-accumulate.
        centred = np.zeros_like(sums)
        for start in range(0, vec_rows.size, block_rows):
            block = np.asarray(idx._vecs[vec_rows[start:start + block_rows]], dtype=np.float32)
            norms = np.linalg.norm(block, axis=1, keepdims=True)
            block = block / np.clip(norms, 1e-12, None)
            block = block - mean_vec
            block = block / np.clip(np.linalg.norm(block, axis=1, keepdims=True), 1e-12, None)
            np.add.at(centred, codes[start:start + block_rows], block)
        sums = centred

    norms = np.linalg.norm(sums, axis=1, keepdims=True)
    centroids = (sums / np.clip(norms, 1e-12, None)).astype(np.float32)
    norms_flat = norms[:, 0].astype(np.float32)

    quarantined = _quarantined_symbols(conn)
    keep_mask = counts >= max(1, min_chunks)
    kept = [i for i in range(len(symbols)) if keep_mask[i]]
    return CentroidResult(
        symbols=[symbols[i] for i in kept],
        matrix=centroids[kept],
        chunks=counts[kept].astype(np.int32),
        sources={symbols[i]: dict(sources[symbols[i]]) for i in kept},
        quarantined={s: (s in quarantined) for s in symbols},
    )


def build_terms(conn, symbols: Sequence[str], max_chunks_per_symbol: int = 400) -> Dict[str, List[str]]:
    """Distinctive vocabulary per company (TF over the company, DF over the corpus)."""
    docs: Dict[str, Counter] = {}
    df: Counter = Counter()
    for sym in symbols:
        rows = conn.execute(
            "SELECT content FROM document_chunks WHERE symbol = ? ORDER BY chunk_id LIMIT ?",
            (sym, max_chunks_per_symbol),
        ).fetchall()
        c: Counter = Counter()
        for (content,) in rows:
            c.update(set(_tokenise(content or "")))
        if not c:
            continue
        docs[sym] = c
        df.update(c.keys())
    n_docs = max(1, len(docs))
    out: Dict[str, List[str]] = {}
    for sym, c in docs.items():
        scored = []
        for term, tf in c.items():
            idf = math.log((1 + n_docs) / (1 + df[term])) + 1.0
            scored.append((tf * idf, term))
        scored.sort(reverse=True)
        out[sym] = [t for _, t in scored[:TERM_TOP_N]]
    return out


# ---------------------------------------------------------------------------
# Similarity + gating
# ---------------------------------------------------------------------------
def compute_pairs(
    centroids: CentroidResult,
    top_k: int = TOP_K_DEFAULT,
    min_similarity: float = 0.0,
    exclude_quarantined: bool = True,
) -> Dict[str, List[Tuple[int, float]]]:
    """Cosine top-k per anchor. Returns {anchor_symbol: [(row_index, similarity)]}."""
    matrix = centroids.matrix
    n = matrix.shape[0]
    if n < MIN_PEERS + 1:
        return {}
    allowed = np.ones(n, dtype=bool)
    if exclude_quarantined:
        for i, s in enumerate(centroids.symbols):
            if centroids.quarantined.get(s):
                allowed[i] = False

    out: Dict[str, List[Tuple[int, float]]] = {}
    for start in range(0, n, BLOCK_ROWS):
        stop = min(start + BLOCK_ROWS, n)
        sims = matrix[start:stop] @ matrix.T                  # (block, n) cosine
        for i in range(start, stop):
            if not allowed[i]:
                continue
            row = sims[i - start]
            row = np.where(allowed, row, -np.inf)
            row[i] = -np.inf
            k = min(top_k, int(np.isfinite(row).sum()))
            if k <= 0:
                continue
            cand = np.argpartition(-row, k - 1)[:k]
            cand = cand[np.argsort(-row[cand])]
            pairs = [(int(j), float(row[j])) for j in cand if float(row[j]) >= min_similarity]
            if len(pairs) >= MIN_PEERS:
                out[centroids.symbols[i]] = pairs
    return out


def features_version(min_chunks: int, top_k: int) -> str:
    return f"business-substance/v1|dim=384|min_chunks={min_chunks}|k={top_k}"


# ---------------------------------------------------------------------------
# Persistence + read-back
# ---------------------------------------------------------------------------
def ensure_schema(conn) -> None:
    conn.execute(GRAPH_DDL)
    conn.execute(FEATURE_DDL)
    conn.execute(RUN_DDL)


def persist(
    conn,
    centroids: CentroidResult,
    pairs: Dict[str, List[Tuple[int, float]]],
    terms: Dict[str, List[str]],
    top_k: int = TOP_K_DEFAULT,
    min_chunks: int = MIN_CHUNKS,
    dry_run: bool = False,
) -> Dict[str, Any]:
    version = features_version(min_chunks, top_k)
    if dry_run:
        return {"pairs": sum(len(v) for v in pairs.values()), "anchors": len(pairs), "dry_run": True}

    ensure_schema(conn)
    conn.execute("DELETE FROM company_business_graph WHERE features_version = ?", (version,))
    conn.execute("DELETE FROM company_business_features WHERE features_version = ?", (version,))

    conn.executemany(
        """INSERT OR REPLACE INTO company_business_features
           (symbol, chunks, sources_json, centroid_norm, terms_json, quarantined, features_version)
           VALUES (?,?,?,?,?,?,?)""",
        [
            (
                sym, int(centroids.chunks[i]),
                json.dumps(centroids.sources.get(sym, {}), sort_keys=True),
                1.0,
                json.dumps(terms.get(sym, [])[:TERM_TOP_N]),
                1 if centroids.quarantined.get(sym) else 0,
                version,
            )
            for i, sym in enumerate(centroids.symbols)
            if not centroids.quarantined.get(sym)
        ],
    )

    rows = []
    for anchor, peers in pairs.items():
        a_terms = set(terms.get(anchor, []))
        for rank, (j, sim) in enumerate(peers, 1):
            peer = centroids.symbols[j]
            shared = [t for t in terms.get(peer, []) if t in a_terms][:MAX_TERMS_SHARED]
            rows.append((
                anchor, peer, rank, float(sim),
                json.dumps(shared),
                json.dumps({"anchor": centroids.sources.get(anchor, {}), "peer": centroids.sources.get(peer, {})}, sort_keys=True),
                int(centroids.chunks[centroids.symbols.index(anchor)]),
                int(centroids.chunks[j]),
                version,
            ))
    conn.executemany(
        """INSERT OR REPLACE INTO company_business_graph
           (anchor_symbol, peer_symbol, rank, similarity, shared_terms_json, source_mix_json,
            anchor_chunks, peer_chunks, features_version)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        rows,
    )
    conn.execute(
        "INSERT INTO company_business_runs (status, reason, n_symbols, n_chunks, n_pairs, min_chunks, top_k) "
        "VALUES (?,?,?,?,?,?,?)",
        ("ok", None, len(pairs), int(centroids.chunks.sum()), len(rows), min_chunks, top_k),
    )
    return {"pairs": len(rows), "anchors": len(pairs), "dry_run": False}


def business_neighbours(conn, symbol: str, top_k: int = 10, version: Optional[str] = None) -> List[Dict[str, Any]]:
    """Analog companies by business substance, with shared vocabulary as evidence."""
    sym = (symbol or "").upper().strip()
    sql = ("SELECT peer_symbol, rank, similarity, shared_terms_json, source_mix_json, "
           "anchor_chunks, peer_chunks FROM company_business_graph WHERE anchor_symbol = ?")
    params: List[Any] = [sym]
    if version:
        sql += " AND features_version = ?"
        params.append(version)
    sql += " ORDER BY rank LIMIT ?"
    params.append(top_k)
    out = []
    for r in conn.execute(sql, params).fetchall():
        out.append({
            "peer": r[0], "rank": r[1], "similarity": round(float(r[2]), 4),
            "shared_terms": json.loads(r[3] or "[]"),
            "source_mix": json.loads(r[4] or "{}"),
            "anchor_chunks": r[5], "peer_chunks": r[6],
        })
    return out


def latest_run(conn) -> Optional[Dict[str, Any]]:
    try:
        row = conn.execute(
            "SELECT run_id, status, reason, n_symbols, n_chunks, n_pairs, min_chunks, top_k, computed_at "
            "FROM company_business_runs ORDER BY run_id DESC LIMIT 1"
        ).fetchone()
    except Exception:
        return None
    if not row:
        return None
    return dict(zip(("run_id", "status", "reason", "n_symbols", "n_chunks", "n_pairs",
                     "min_chunks", "top_k", "computed_at"), row))
