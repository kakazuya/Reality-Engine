"""Embedding retrieval test for pilot3 (T-049; guide O7): does a dense page vector put the answering page
above today's bm25 search?

The corpus is ``doc_page`` text of KEC, BAJFINANCE and HINDALCO: transcripts, decks, results files, press
releases and annual reports first known on or after 2025-04-01 (``doc`` joined on ``doc_key``, read-only
through ``connect_ro``).  A page's item is one header line (company | type | title | filing date | page N)
plus its text truncated to 30,000 characters; a deck page is also a ~110 DPI JPEG of its source PDF.

    python -m reality_engine.pilot3.embed_test plan
    python -m reality_engine.pilot3.embed_test embed --model 1b --max-usd 0.25 --dry-run
    python -m reality_engine.pilot3.embed_test eval --gold <gold.json> --dry-run

``plan`` touches no network.  ``--dry-run`` swaps the paid client for a deterministic fake (random unit
vectors, fake ``usage``), so the whole pipeline runs offline; the paid run reads ``DEEPINFRA_API_KEY`` from
the environment and never prints it.  Prices are the approved DeepInfra ones (1B: $0.015/M text, $0.035/M
image; 8B: $0.035/M text, $0.070/M image).  The spend counter reads ``usage.prompt_tokens`` of every reply
and the run stops before a batch that would cross ``--max-usd``.

Vectors are cached per model and kind (``<model>_text.npy`` / ``<model>_image.npy`` plus an index json of
``doc_key``, ``page``, ``kind`` under ``--out``, default ``D:\\RealityEngine\\pilot3\\embed_test``), so a
run resumes where the last one stopped and the eval needs no second embed.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import os
import random
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np

DOC_TYPES = ("transcript", "deck", "results", "press_release", "annual_report")
SINCE = "2025-04-01"
TEXT_CHARS = 30_000
BATCH = 16                 # items per request
PARALLEL = 4               # requests in flight
RRF_K = 60
IMAGE_DPI = 110
IMAGE_TOKEN_EST = 1_700    # only used to plan/project; the embed run probes the real count
API_URL = "https://api.deepinfra.com/v1/openai/embeddings"

MODELS = {
    "1b": {"id": "nvidia/Nemotron-3.5-Embed-1B-BF16", "text_usd_per_mtok": 0.015, "image_usd_per_mtok": 0.035},
    "8b": {"id": "nvidia/Nemotron-3.5-Embed-8B-BF16", "text_usd_per_mtok": 0.035, "image_usd_per_mtok": 0.070},
}

DOC_TYPE_ALIAS = {"annual report": "annual_report", "ar": "annual_report", "annual_report": "annual_report",
                  "deck": "deck", "presentation": "deck", "transcript": "transcript", "call": "transcript",
                  "results": "results", "press release": "press_release", "press_release": "press_release"}


# --- corpus -----------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Page:
    doc_key: str
    symbol: str
    page: int
    text: str
    known_at: str | None
    doc_type: str
    title: str
    filing_date: str | None
    pdf: str | None

    @property
    def key(self) -> tuple[str, int]:
        return (self.doc_key, self.page)


def db_path(explicit: str | None = None) -> Path:
    if explicit:
        return Path(explicit)
    env = os.environ.get("REALITY_PILOT3_DB")
    if env:
        return Path(env)
    from reality_engine.pilot3 import REAL_DB, data_root

    candidate = Path(data_root()) / "pilot3" / "pilot3.db"
    return candidate if candidate.is_file() else REAL_DB


def load_corpus(db: str | Path | None = None) -> list[Page]:
    """Every ``doc_page`` row of a corpus document, oldest first by filing record."""
    from reality_engine.db.readonly import connect_ro

    path = db_path(str(db) if db else None)
    if not Path(path).is_file():
        raise SystemExit(f"STOPPED: pilot3.db not found at {path}")
    marks = ",".join("?" for _ in DOC_TYPES)
    con = connect_ro(path, timeout_s=60)
    try:
        cursor = con.execute(
            f"SELECT p.doc_key, p.symbol, p.page, COALESCE(p.text,''), "
            f"COALESCE(p.known_at, d.known_at), d.doc_type, COALESCE(d.title,''), d.filing_date, d.source_key "
            f"FROM doc_page p JOIN doc d ON d.doc_key = p.doc_key "
            f"WHERE d.doc_type IN ({marks}) AND COALESCE(d.known_at,'') >= ? "
            f"ORDER BY p.symbol, p.doc_key, p.page", (*DOC_TYPES, SINCE))
        rows = (cursor.fetchall() if cursor is not None else None) or []
    finally:
        con.close()
    return [Page(doc_key=r[0], symbol=r[1], page=int(r[2]), text=r[3], known_at=r[4], doc_type=r[5],
                 title=r[6], filing_date=r[7], pdf=r[8]) for r in rows]


def header(page: Page) -> str:
    filed = (page.filing_date or page.known_at or "unknown")[:10]
    return f"{page.symbol} | {page.doc_type.replace('_', ' ')} | {page.title[:160]} | filed {filed} | page {page.page}"


def text_item(page: Page) -> str:
    """The header line plus the page text, the page text cut at ``TEXT_CHARS``."""
    return f"{header(page)}\n{page.text[:TEXT_CHARS]}"


def image_item(page: Page, jpeg: bytes) -> list[dict[str, Any]]:
    """One image item: the header as text plus the page JPEG as a data URL (brief's content-part shape)."""
    return [{"type": "text", "text": header(page)},
            {"type": "image_url", "image_url": {
                "url": "data:image/jpeg;base64," + base64.b64encode(jpeg).decode("ascii")}}]


def pdf_path(page: Page) -> Path | None:
    """The page's source PDF: ``doc.source_key`` (pages.db's ``source_path``, the path build.py carries),
    else the same relative path under ``REALITY_RAW_ROOT`` (old ``history/...`` keys)."""
    if page.pdf and Path(page.pdf).is_file():
        return Path(page.pdf)
    raw = os.environ.get("REALITY_RAW_ROOT")
    if raw:
        for rel in (page.doc_key, f"raw/{page.doc_key}"):
            candidate = Path(raw) / rel
            if candidate.is_file():
                return candidate
    return None


# --- image rendering --------------------------------------------------------------------------------
def renderer_name() -> str | None:
    import importlib.util

    for module in ("pymupdf", "pypdfium2"):
        if importlib.util.find_spec(module):
            return module
    return None


def render_jpeg(path: str | Path, page_no: int, dpi: int = IMAGE_DPI) -> bytes:
    """One PDF page as JPEG bytes (~110 DPI); PyMuPDF when installed, else pypdfium2."""
    try:
        import pymupdf

        with pymupdf.open(str(path)) as doc:
            pix = doc.load_page(page_no - 1).get_pixmap(dpi=dpi)
            return pix.tobytes("jpeg", jpg_quality=80)
    except ImportError:
        pass
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(str(path))
    try:
        bitmap = pdf[page_no - 1].render(scale=dpi / 72)   # type: ignore[arg-type]  # stub says int
        image = bitmap.to_pil()
        buffer = io.BytesIO()
        image.convert("RGB").save(buffer, "JPEG", quality=80)
        return buffer.getvalue()
    finally:
        pdf.close()


# --- clients ----------------------------------------------------------------------------------------
class FakeClient:
    """Offline stand-in: unit vectors hashed from the item, fake ``usage``.  No network, no key."""

    dim = 64

    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []
        self.active = 0
        self.peak = 0

    def embed(self, items: Sequence[Any], task: str) -> tuple[list[list[float]], int]:
        self.calls.append((task, len(items)))
        self.active += 1
        self.peak = max(self.peak, self.active)
        try:
            time.sleep(0.02)                      # a real request is not instant; keeps the peak honest
            vectors, tokens = [], 0
            for item in items:
                payload = item if isinstance(item, str) else json.dumps(item, sort_keys=True)
                digest = hashlib.sha256(payload.encode("utf-8")).digest()
                rnd = random.Random(int.from_bytes(digest[:8], "big"))
                vectors.append([rnd.uniform(-1.0, 1.0) for _ in range(self.dim)])
                tokens += max(1, len(payload) // 4) if isinstance(item, str) else IMAGE_TOKEN_EST
            return vectors, tokens
        finally:
            self.active -= 1


class DeepInfraClient:
    """OpenAI-compatible DeepInfra embeddings; the key is read from ``DEEPINFRA_API_KEY`` and never printed."""

    def __init__(self, model_id: str, attempts: int = 5, timeout_s: float = 180.0) -> None:
        self.model_id = model_id
        self.attempts = attempts
        self.timeout_s = timeout_s
        self._warned_usage = False
        self.key = os.environ.get("DEEPINFRA_API_KEY", "")
        if not self.key:
            raise SystemExit("STOPPED: DEEPINFRA_API_KEY is not in the environment; the paid run needs it "
                             "(never pass the key on the command line)")

    def embed(self, items: Sequence[Any], task: str) -> tuple[list[list[float]], int]:
        body = json.dumps({"model": self.model_id, "input": list(items), "task": task,
                           "encoding_format": "float"}).encode("utf-8")
        payload: dict[str, Any] = {}
        for attempt in range(self.attempts):
            request = urllib.request.Request(API_URL, data=body, headers={
                "Authorization": f"Bearer {self.key}", "Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                break
            except urllib.error.HTTPError as exc:
                if exc.code not in (429, 500, 502, 503, 504) or attempt == self.attempts - 1:
                    raise SystemExit(f"STOPPED: DeepInfra returned HTTP {exc.code} "
                                     f"({exc.reason}); nothing was written for this batch") from exc
                wait = 2 ** attempt
                print(f"  HTTP {exc.code}: retry {attempt + 1}/{self.attempts} in {wait}s")
                time.sleep(wait)
            except urllib.error.URLError as exc:
                if attempt == self.attempts - 1:
                    raise SystemExit(f"STOPPED: DeepInfra unreachable: {exc.reason}") from exc
                wait = 2 ** attempt
                print(f"  network error: retry {attempt + 1}/{self.attempts} in {wait}s")
                time.sleep(wait)
        rows = sorted(payload.get("data") or [], key=lambda r: r.get("index", 0))
        vectors = [[float(v) for v in row["embedding"]] for row in rows]
        usage = payload.get("usage") or {}
        if not usage and not self._warned_usage:
            self._warned_usage = True
            print("  warning: the reply carries no usage.prompt_tokens; the spend is undercounted")
        return vectors, int(usage.get("prompt_tokens") or 0)


# --- spend ------------------------------------------------------------------------------------------
def cost_usd(model: str, kind: str, tokens: int) -> float:
    price = MODELS[model]["image_usd_per_mtok" if kind == "image" else "text_usd_per_mtok"]
    return tokens / 1_000_000 * price


def _estimate_tokens(pages: Sequence[Page], kind: str, avg: float | None) -> int:
    if kind == "image":
        return int(len(pages) * (avg or IMAGE_TOKEN_EST)) + 1
    estimate = sum(len(text_item(p)) // 4 + 1 for p in pages)
    if avg:
        estimate = max(estimate, int(avg * len(pages)))
    return estimate


# --- vector cache -----------------------------------------------------------------------------------
class VectorCache:
    """``<model>_<kind>.npy`` + ``<model>_<kind>.index.json`` (doc_key, page, kind); resumable."""

    def __init__(self, out_dir: str | Path, model: str, kind: str) -> None:
        self.dir = Path(out_dir)
        self.kind = kind
        self.path = self.dir / f"{model}_{kind}.npy"
        self.index_path = self.dir / f"{model}_{kind}.index.json"
        self.keys: list[tuple[str, int]] = []
        self.matrix: np.ndarray | None = None
        self._rows: dict[tuple[str, int], int] = {}
        self._load()

    def _load(self) -> None:
        if not (self.path.is_file() and self.index_path.is_file()):
            return
        try:
            matrix = np.load(self.path, allow_pickle=False)
            index = json.loads(self.index_path.read_text(encoding="utf-8"))
            n = min(len(matrix), len(index))
            if n != len(matrix) or n != len(index):
                print(f"  cache {self.path.name}: {len(matrix)} vectors vs {len(index)} index rows; using {n}")
            self.matrix = np.asarray(matrix[:n], dtype=np.float32)
            self.keys = [(str(row["doc_key"]), int(row["page"])) for row in index[:n]]
            self._rows = {key: i for i, key in enumerate(self.keys)}
        except (OSError, ValueError, KeyError, TypeError) as exc:
            print(f"  cache {self.path.name}: unreadable ({exc}); re-embedding")
            self.keys, self.matrix, self._rows = [], None, {}

    def rows(self) -> dict[tuple[str, int], int]:
        return self._rows

    def add(self, keys: Sequence[tuple[str, int]], vectors: Sequence[Sequence[float]]) -> None:
        if len(keys) != len(vectors):
            raise SystemExit(f"STOPPED: the API returned {len(vectors)} vectors for {len(keys)} items; "
                             f"the cache would be misaligned and no page was written for this request")
        array = np.asarray(vectors, dtype=np.float32)
        norms = np.linalg.norm(array, axis=1, keepdims=True)
        array = array / np.where(norms == 0, 1.0, norms)
        self.matrix = array if self.matrix is None or not len(self.matrix) else np.vstack([self.matrix, array])
        self.keys.extend(keys)
        self._rows = {key: i for i, key in enumerate(self.keys)}

    def save(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        if self.matrix is not None:
            np.save(self.path, self.matrix)
        index = [{"doc_key": key, "page": page, "kind": self.kind} for key, page in self.keys]
        temp = self.index_path.with_suffix(".json.tmp")
        temp.write_text(json.dumps(index), encoding="utf-8")
        temp.replace(self.index_path)


# --- embedding --------------------------------------------------------------------------------------
def _build_items(pages: Sequence[Page], kind: str, skipped: dict[str, int]) -> tuple[list[Page], list[Any]]:
    """Aligned (pages, items); an image page with no PDF or a render error is dropped and counted."""
    kept, items = [], []
    for page in pages:
        if kind == "text":
            kept.append(page)
            items.append(text_item(page))
            continue
        path = pdf_path(page)
        if path is None:
            skipped["no_pdf"] += 1
            continue
        try:
            jpeg = render_jpeg(path, page.page)
        except Exception as exc:                  # a broken page must not kill the run
            skipped["render_error"] += 1
            if skipped["render_error"] <= 5:
                print(f"  skip {page.doc_key} p{page.page}: {type(exc).__name__}: {exc}")
            continue
        kept.append(page)
        items.append(image_item(page, jpeg))
    return kept, items


def embed_pages(pages: Sequence[Page], kind: str, client: Any, model: str, cache: VectorCache,
                max_usd: float, spend: float) -> float:
    """Embed the pages not already in ``cache``, in batches of 16, 4 requests in flight."""
    todo = [p for p in pages if p.key not in cache.keys]
    print(f"{kind}: {len(pages)} corpus pages, {len(cache.keys)} cached, {len(todo)} to embed")
    if not todo:
        return spend
    skipped = {"no_pdf": 0, "render_error": 0}
    if kind == "image":
        print(f"image renderer: {renderer_name() or 'NONE (install PyMuPDF or pypdfium2)'}")
    seen_tokens = seen_items = 0

    if kind == "image":                            # probe the first five images before the paid run
        probe = todo[:5]
        print(f"image probe: first {len(probe)} page(s)")
        for page in probe:
            if spend >= max_usd:
                print("  STOP: budget used up during the probe")
                break
            kept, items = _build_items([page], kind, skipped)
            if not items:
                continue
            vectors, tokens = client.embed(items, "document")
            spend += cost_usd(model, kind, tokens)
            cache.add([kept[0].key], vectors)
            cache.save()
            print(f"  {page.doc_key} p{page.page}: {tokens} image tokens (~${cost_usd(model, kind, tokens):.4f})")
        probed = {p.key for p in probe}
        todo = [p for p in todo if p.key not in probed and p.key not in cache.keys]
        if not todo:
            return spend

    chunks = [todo[i:i + BATCH] for i in range(0, len(todo), BATCH)]
    done = 0
    with ThreadPoolExecutor(max_workers=PARALLEL) as pool:
        index = 0
        while index < len(chunks):
            # fill up to PARALLEL requests, but never one that would take the spend past --max-usd
            group, estimate_total = [], 0
            while len(group) < PARALLEL and index + len(group) < len(chunks):
                chunk = chunks[index + len(group)]
                estimate = _estimate_tokens(chunk, kind, seen_tokens / seen_items if seen_items else None)
                if spend + cost_usd(model, kind, estimate_total + estimate) > max_usd:
                    break
                group.append(chunk)
                estimate_total += estimate
            if not group:
                first = chunks[index]
                estimate = _estimate_tokens(first, kind, seen_tokens / seen_items if seen_items else None)
                print(f"STOP before the next {len(first)} items: ~{estimate:,} {kind} tokens ~= "
                      f"${cost_usd(model, kind, estimate):.4f}, spent ${spend:.4f} of ${max_usd:g}; "
                      f"re-run with a larger --max-usd to continue")
                break
            built = []
            for chunk in group:
                pages_ok, items = _build_items(chunk, kind, skipped)
                if items:
                    built.append((pages_ok, items))
            replies = list(pool.map(lambda pair: client.embed(pair[1], "document"), built))
            group_tokens = 0
            for (pages_ok, _items), (vectors, tokens) in zip(built, replies):
                cache.add([p.key for p in pages_ok], vectors)
                spend += cost_usd(model, kind, tokens)
                done += len(pages_ok)
                seen_items += len(pages_ok)
                seen_tokens += tokens
                group_tokens += tokens
            cache.save()
            print(f"  {done}/{len(todo)} embedded, {group_tokens:,} tokens this group, "
                  f"${spend:.4f} / ${max_usd:g}")
            index += len(group)
    if kind == "image" and (skipped["no_pdf"] or skipped["render_error"]):
        print(f"image skips: {skipped['no_pdf']} page(s) with no source PDF, {skipped['render_error']} render error(s)")
    return spend


# --- eval -------------------------------------------------------------------------------------------
def fts_query(text: str) -> str:
    """The bm25 query ``pilot3_search`` builds: up to 12 quoted words, OR-joined."""
    words = [w for w in re.findall(r"[\w₹%]+", text or "") if len(w) > 1 or w.isdigit()]
    return " OR ".join(f'"{w}"' for w in words[:12])


def pool_for(pages: Sequence[Page], question: dict[str, Any]) -> list[Page]:
    """A symbol's corpus pages known by ``as_of`` (and inside the window / document type when given)."""
    as_of = str(question.get("as_of") or "")[:10]
    date_from = str(question.get("date_from") or "")[:10]
    date_to = str(question.get("date_to") or "")[:10]
    dtype = question.get("doc_type")
    dtype = DOC_TYPE_ALIAS.get(str(dtype).strip().lower(), dtype) if dtype else None
    out = []
    for page in pages:
        known = (page.known_at or "")[:10]
        if as_of and (not known or known > as_of):
            continue
        filed = (page.filing_date or page.known_at or "")[:10]
        if date_from and (not filed or filed < date_from):
            continue
        if date_to and (not filed or filed > date_to):
            continue
        if dtype and page.doc_type != dtype:
            continue
        out.append(page)
    return out


def bm25_ranking(con: sqlite3.Connection, question: dict[str, Any], pool_keys: Sequence[tuple[str, int]]) -> list:
    """Pool pages FTS5 bm25 returns, best first."""
    match = fts_query(question.get("question") or "")
    if not match or not pool_keys:
        return []
    marks = ",".join("?" for _ in DOC_TYPES)
    where = [f"doc_page_fts MATCH ?", "p.symbol=?", f"d.doc_type IN ({marks})", "COALESCE(d.known_at,'') >= ?"]
    args: list[Any] = [match, str(question.get("symbol") or "").upper(), *DOC_TYPES, SINCE]
    as_of = str(question.get("as_of") or "")[:10]
    if as_of:
        where.append("COALESCE(p.known_at, d.known_at) <= ?")
        args.append(as_of)
    for field, op in (("date_from", ">="), ("date_to", "<=")):
        day = str(question.get(field) or "")[:10]
        if day:
            where.append(f"substr(COALESCE(d.filing_date, d.known_at, ''),1,10) {op} ?")
            args.append(day)
    dtype = question.get("doc_type")
    if dtype:
        where.append("d.doc_type=?")
        args.append(DOC_TYPE_ALIAS.get(str(dtype).strip().lower(), dtype))
    sql = ("SELECT p.doc_key, p.page FROM doc_page_fts f JOIN doc_page p ON p.rowid=f.rowid "
           "JOIN doc d ON d.doc_key=p.doc_key WHERE " + " AND ".join(where) + " ORDER BY rank LIMIT ?")
    allowed = set(pool_keys)
    cursor = con.execute(sql, (*args, max(len(pool_keys), 1)))
    rows = (cursor.fetchall() if cursor is not None else None) or []
    return [(row[0], int(row[1])) for row in rows if (row[0], int(row[1])) in allowed]


def _cosine(cache: VectorCache, rows: dict, key: tuple[str, int], query: np.ndarray) -> float | None:
    index = rows.get(key)
    if index is None or cache.matrix is None:
        return None
    return float(np.dot(cache.matrix[index], query))


def dense_ranking(pool_keys: Sequence[tuple[str, int]], cache: VectorCache, query: np.ndarray,
                  image: VectorCache | None = None, deck_keys: frozenset = frozenset()) -> tuple[list, int]:
    """Pool pages with a vector, best cosine first; a deck page may score on text or image (max).
    Returns the ranking and how many pool pages had a vector."""
    text_rows = cache.rows()
    image_rows = image.rows() if image is not None else {}
    scored, covered = [], 0
    for key in pool_keys:
        best = _cosine(cache, text_rows, key, query)
        if key in deck_keys and image is not None:
            visual = _cosine(image, image_rows, key, query)
            if visual is not None:
                best = visual if best is None else max(best, visual)
        if best is None:
            continue
        scored.append((best, key))
        covered += 1
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [key for _score, key in scored], covered


def rrf(rankings: Iterable[Sequence[tuple[str, int]]], k: int = RRF_K) -> list[tuple[str, int]]:
    """Reciprocal rank fusion; a page's score is the sum of 1/(k + rank) over the lists holding it."""
    scores: dict[tuple[str, int], float] = {}
    for ranking in rankings:
        for position, key in enumerate(ranking, 1):
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + position)
    return sorted(scores, key=lambda key: (-scores[key], key))


def metrics(ranked: Sequence[tuple[str, int]], gold: set, ks: Sequence[int] = (1, 5, 10, 50)) -> dict:
    """Gold rank in one ranking and the hit/MRR figures it implies (rank None = not returned)."""
    rank = next((position for position, key in enumerate(ranked, 1) if key in gold), None)
    out: dict[str, Any] = {f"hit@{k}": 1.0 if rank is not None and rank <= k else 0.0 for k in ks}
    out["mrr"] = 1.0 / rank if rank else 0.0
    out["rank"] = rank
    return out


def evaluate(db: str | Path | None, gold: Sequence[dict[str, Any]], out_dir: str | Path,
             clients: dict[str, Any], write_xlsx: bool = True) -> dict:
    """Rank every question's pool by bm25, each model's dense, RRF hybrid and deck text+image max."""
    path = db_path(str(db) if db else None)
    pages = load_corpus(path)
    by_symbol: dict[str, list[Page]] = {}
    for page in pages:
        by_symbol.setdefault(page.symbol, []).append(page)
    by_key = {page.key: page for page in pages}
    from reality_engine.db.readonly import connect_ro

    con = connect_ro(path, timeout_s=60)
    try:
        caches = {model: (VectorCache(out_dir, model, "text"), VectorCache(out_dir, model, "image"))
                  for model in clients}
        live = {model: pair for model, pair in caches.items() if pair[0].keys}
        for model in clients:
            if model not in live:
                print(f"{model}: no text vectors under {out_dir}; run embed --model {model} first (skipped)")
        if not live:
            raise SystemExit(f"STOPPED: no embedding cache under {out_dir}; run embed first")
        questions = [str(q.get("question") or "") for q in gold]
        methods = ["bm25"]
        for model in live:
            methods += [f"{model}_dense", f"{model}_hybrid"]
            if live[model][1].keys:
                methods.append(f"{model}_deck_max")
        results: dict[str, list[dict]] = {}
        per_question: dict[str, dict[str, Any]] = {}

        first_pass = []
        for position, question in enumerate(gold):
            qid = str(question.get("qid") or position + 1)
            symbol = str(question.get("symbol") or "").upper()
            pool = pool_for(by_symbol.get(symbol, []), question)
            pool_keys = [page.key for page in pool]
            order_bm = bm25_ranking(con, question, pool_keys)
            gold_keys = {(str(doc), int(page)) for doc, page in question.get("gold", []) if doc}
            first_pass.append((qid, question, pool_keys, order_bm, gold_keys))
            per_question[qid] = {"symbol": symbol, "question": question.get("question"),
                                 "pool": len(pool_keys), "gold": gold_keys, "ranks": {"bm25": None}}
            results.setdefault("bm25", []).append(metrics(order_bm, gold_keys))
            per_question[qid]["ranks"]["bm25"] = results["bm25"][-1]["rank"]

        for model, client in clients.items():
            if model not in live:
                continue
            text_cache, image_cache = live[model]
            query_vectors, tokens = client.embed(questions, "search_query")
            if len(query_vectors) != len(questions):
                raise SystemExit(f"STOPPED: {model} returned {len(query_vectors)} query vectors for "
                                 f"{len(questions)} questions")
            dim = int(text_cache.matrix.shape[1]) if text_cache.matrix is not None else 0
            print(f"{model}: {dim}-d vectors, text {len(text_cache.keys)} pages, image {len(image_cache.keys)} pages, "
                  f"query {tokens:,} tokens (~${cost_usd(model, 'text', tokens):.4f})")
            for (qid, question, pool_keys, order_bm, gold_keys), raw in zip(first_pass, query_vectors):
                vector = np.asarray(raw, dtype=np.float32)
                norm = float(np.linalg.norm(vector))
                query = vector / norm if norm else vector
                deck_keys = frozenset(key for key in pool_keys if by_key[key].doc_type == "deck")
                order_dense, covered = dense_ranking(pool_keys, text_cache, query)
                order_max, covered_max = dense_ranking(pool_keys, text_cache, query, image_cache, deck_keys)
                order_hybrid = rrf([order_bm, order_dense])
                rankings = {f"{model}_dense": order_dense, f"{model}_hybrid": order_hybrid}
                if image_cache.keys:
                    rankings[f"{model}_deck_max"] = order_max
                for method, ranking in rankings.items():
                    results.setdefault(method, []).append(metrics(ranking, gold_keys))
                    per_question[qid]["ranks"][method] = results[method][-1]["rank"]
                per_question[qid][f"coverage_{model}"] = f"{covered}/{len(pool_keys)}"
                if image_cache.keys:
                    per_question[qid][f"coverage_max_{model}"] = f"{covered_max}/{len(pool_keys)}"
    finally:
        con.close()

    report = {"corpus": len(pages), "questions": len(gold), "methods": results, "by_question": per_question}
    _print_report(report, list(results))
    if write_xlsx:
        target = Path(out_dir) / "EVAL.xlsx"
        _write_xlsx(target, report, list(results), gold)
        print(f"wrote {target}")
    return report


def _print_report(report: dict, methods: Sequence[str]) -> None:
    print()
    print(f"{'method':<16}{'n':>4}{'hit@1':>8}{'hit@5':>8}{'hit@10':>8}{'hit@50':>8}{'MRR':>8}")
    for method in methods:
        rows = report["methods"].get(method) or []
        if not rows:
            continue
        count = len(rows)
        hits = [sum(row[f"hit@{k}"] for row in rows) / count for k in (1, 5, 10, 50)]
        mrr = sum(row["mrr"] for row in rows) / count
        print(f"{method:<16}{count:>4}" + "".join(f"{value:>8.0%}" for value in hits) + f"{mrr:>8.3f}")
    print()
    for qid, row in report["by_question"].items():
        ranks = "  ".join(f"{method}={row['ranks'].get(method) if row['ranks'].get(method) else '-'}"
                          for method in methods if method in row["ranks"])
        print(f"{qid:<12} pool={row['pool']:<5} {ranks}")
    print()
    print("rank '-' = the method never returned a gold page; pool = pages known at the question's as_of")


def _write_xlsx(target: Path, report: dict, methods: Sequence[str], gold: Sequence[dict]) -> None:
    from openpyxl import Workbook

    target.parent.mkdir(parents=True, exist_ok=True)
    book = Workbook()
    summary = book.active
    assert summary is not None
    summary.title = "summary"
    summary.append(["method", "questions", "hit@1", "hit@5", "hit@10", "hit@50", "MRR"])
    for method in methods:
        rows = report["methods"].get(method)
        if not rows:
            continue
        count = len(rows)
        summary.append([method, count,
                        *[round(sum(row[f"hit@{k}"] for row in rows) / count, 4) for k in (1, 5, 10, 50)],
                        round(sum(row["mrr"] for row in rows) / count, 4)])
    questions = book.create_sheet("questions")
    assert questions is not None
    questions.append(["qid", "symbol", "question", "pool", *[f"{method} rank" for method in methods], "gold"])
    for position, question in enumerate(gold):
        qid = str(question.get("qid") or position + 1)
        row = report["by_question"][qid]
        questions.append([qid, row["symbol"], row["question"], row["pool"],
                          *[row["ranks"].get(method) for method in methods],
                          json.dumps(sorted(row["gold"]))])
    summary.freeze_panes = "A2"
    questions.freeze_panes = "A2"
    book.save(target)


# --- CLI --------------------------------------------------------------------------------------------
def _print_plan(db: Path, pages: Sequence[Page]) -> None:
    by_type: dict[str, dict[str, Any]] = {}
    for page in pages:
        row = by_type.setdefault(page.doc_type, {"docs": set(), "pages": 0, "chars": 0})
        row["docs"].add(page.doc_key)
        row["pages"] += 1
        row["chars"] += len(text_item(page))
    total_chars = sum(row["chars"] for row in by_type.values())
    deck_pages = by_type.get("deck", {}).get("pages", 0)
    print(f"pilot3 embedding corpus: {db}")
    print(f"  {sum(len(row['docs']) for row in by_type.values())} documents, {len(pages)} pages, "
          f"{total_chars:,} characters = {total_chars / 4:,.0f} text tokens (chars/4, header included)")
    print(f"  {'doc type':<16}{'docs':>6}{'pages':>7}{'chars':>14}{'tokens':>12}")
    for doc_type, row in sorted(by_type.items(), key=lambda item: -item[1]["pages"]):
        print(f"  {doc_type:<16}{len(row['docs']):>6}{row['pages']:>7}{row['chars']:>14,}{row['chars'] / 4:>12,.0f}")
    deck_docs = {page.doc_key: page for page in pages if page.doc_type == "deck"}
    found = sum(1 for page in deck_docs.values() if pdf_path(page) is not None)
    print(f"  deck images: {found}/{len(deck_docs)} deck PDFs found, {deck_pages} pages to render at "
          f"{IMAGE_DPI} DPI ({renderer_name() or 'no renderer installed'})")
    print(f"  {'model':<6}{'id':<40}{'text USD':>10}{'image USD':>11}{'total USD':>11}")
    for model, meta in MODELS.items():
        text_cost = cost_usd(model, "text", int(total_chars / 4))
        image_cost = cost_usd(model, "image", deck_pages * IMAGE_TOKEN_EST)
        print(f"  {model:<6}{meta['id']:<40}{text_cost:>10.4f}{image_cost:>11.4f}{text_cost + image_cost:>11.4f}")
    print(f"  image cost assumes {IMAGE_TOKEN_EST:,} tokens/page; the embed run probes the real count")


def cmd_plan(args: argparse.Namespace) -> None:
    db = db_path(args.db)
    _print_plan(db, load_corpus(db))


def cmd_embed(args: argparse.Namespace) -> None:
    db = db_path(args.db)
    out_dir = Path(args.out)
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise SystemExit(f"STOPPED: cannot write {out_dir} ({exc}); pass --out")
    pages = load_corpus(db)
    client = FakeClient() if args.dry_run else DeepInfraClient(MODELS[args.model]["id"])
    print(f"embed: {MODELS[args.model]['id']} on {len(pages)} pages from {db}"
          f"{' [DRY RUN: fake client, no network]' if args.dry_run else ''}")
    print(f"cache: {out_dir}")
    spend = 0.0
    spend = embed_pages(pages, "text", client, args.model, VectorCache(out_dir, args.model, "text"),
                        args.max_usd, spend)
    if args.images:
        decks = [page for page in pages if page.doc_type == "deck"]
        spend = embed_pages(decks, "image", client, args.model, VectorCache(out_dir, args.model, "image"),
                            args.max_usd, spend)
    print(f"spend ${spend:.4f} of ${args.max_usd:.2f}")


def cmd_eval(args: argparse.Namespace) -> None:
    gold = json.loads(Path(args.gold).read_text(encoding="utf-8"))
    if not isinstance(gold, list) or not gold:
        raise SystemExit(f"STOPPED: {args.gold} must be a JSON list of questions")
    models = [model.strip() for model in args.model.split(",") if model.strip()]
    clients = {}
    for model in models:
        if model not in MODELS:
            raise SystemExit(f"STOPPED: --model must be one of {', '.join(MODELS)}, got {model!r}")
        clients[model] = FakeClient() if args.dry_run else DeepInfraClient(MODELS[model]["id"])
    report = evaluate(args.db, gold, args.out, clients)
    print(f"{report['questions']} questions over {report['corpus']} corpus pages")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    plan = sub.add_parser("plan", help="corpus counts, tokens and cost per model; no network")
    plan.add_argument("--db", default=None, help="pilot3.db (default REALITY_DATA_ROOT/pilot3/pilot3.db)")
    plan.set_defaults(func=cmd_plan)

    embed = sub.add_parser("embed", help="embed the corpus, resumable, budget-capped")
    embed.add_argument("--model", default="1b", choices=tuple(MODELS))
    embed.add_argument("--images", action="store_true", help="also render and embed deck page images")
    embed.add_argument("--max-usd", type=float, default=1.0, help="stop before a batch would cross this")
    embed.add_argument("--dry-run", action="store_true", help="fake client: random unit vectors, fake usage")
    embed.add_argument("--db", default=None)
    embed.add_argument("--out", default=os.environ.get("PILOT3_EMBED_DIR") or r"D:\RealityEngine\pilot3\embed_test")
    embed.set_defaults(func=cmd_embed)

    ev = sub.add_parser("eval", help="bm25 vs dense vs RRF on a gold file")
    ev.add_argument("--gold", required=True)
    ev.add_argument("--model", default="1b,8b", help="comma list of models with a cache")
    ev.add_argument("--dry-run", action="store_true", help="fake client for the query vectors")
    ev.add_argument("--db", default=None)
    ev.add_argument("--out", default=os.environ.get("PILOT3_EMBED_DIR") or r"D:\RealityEngine\pilot3\embed_test")
    ev.set_defaults(func=cmd_eval)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main(sys.argv[1:])
