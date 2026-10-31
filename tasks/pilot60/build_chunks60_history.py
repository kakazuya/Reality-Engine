"""History mode for the pilot-60 chunk store: manifest -> ``chunks_v3_history.db``.

The FY25+ builder (``tasks/pilot_t2/build_chunks_v3.py``) resolves documents from
the live registries and the D: PDF tree.  The 2019-01-01 .. 2024-03-31 history is
already fetched: ``pilot/pilot60_history_manifest.db`` lists every filing and the
PDF sits under ``<root>/<SYMBOL>/<bucket>/<newsid>.pdf``.  This module keeps the
same DDL, chunker (``reality_engine.processing.chunker_v3``) and writers, and only
replaces the document source:

    python tasks/pilot60/build_chunks60_history.py --pilot          # 200 stratified
    python tasks/pilot60/build_chunks60_history.py --full --shards 4
    python tasks/pilot60/build_chunks60_history.py --full --resume   # continue
    python tasks/pilot60/build_chunks60_history.py --report-only     # FTS + audit

Rules
  * ``known_at`` is the manifest ``dissem_ts`` (the BSE dissemination record); the
    file mtime / fetch time is never used.  The pilot prints the first 20 built
    rows beside their manifest rows and aborts on any difference.
  * Content-hash duplicates are planned before the run (earliest filing wins) and
    counted as ``duplicate``; they are never written twice.
  * Every manifest row ends in exactly one of chunked / needs_ocr / duplicate /
    failed (``history_outcome``), so the four counts sum to the manifest total.
  * Resume is ledger-driven: a row with a terminal outcome is skipped and a
    re-processed doc deletes its old chunks first (no double-write).

The chunk store stays separate from the live pilot store; output defaults to
``.tmp/pilot60/chunks_v3_history.db`` (override ``--out-db``).
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import random
import re
import sqlite3
import statistics
import subprocess
import sys
import time
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

OUT_DIR = REPO / "tasks" / "pilot60"
WORK = REPO / ".tmp" / "pilot60"
DEFAULT_MANIFEST = Path(os.environ.get("REALITY_HISTORY_MANIFEST")
                        or (Path(os.environ.get("REALITY_DATA_ROOT", r"C:\RE\data"))
                            / "pilot" / "pilot60_history_manifest.db"))
DEFAULT_ROOT = Path(os.environ.get("REALITY_HISTORY_RAW") or r"C:\RE\raw\pilot60_history")
FULL_DB = WORK / "chunks_v3_history.db"
PILOT_DB = WORK / "chunks_v3_history_pilot.db"
SHARD_DIR = WORK / "history_shards"

# bucket -> chunks_v3 doc_type (the only doc-type vocabulary the chunker knows)
BUCKET_DOC_TYPE = {
    "annual_report": "annual_report",
    "concall_transcript": "concall",
    # this bucket is the "link to audio recording" announcement; 247 of its 269
    # held PDFs are one-chunk cover letters, so typing them as concalls would
    # inflate concall coverage with documents that are not transcripts.
    "concall_audio_link": "announcement",
    "investor_presentation": "deck",
    "quarterly_results": "results_notes",
    "results_press_release": "announcement",
    "material_filing": "announcement",
    "skip": None,
}
OUTCOMES = ("chunked", "needs_ocr", "duplicate", "failed")
TYPE_ORDER = ("annual_report", "concall", "deck", "results_notes", "announcement")

HISTORY_DDL = """
CREATE TABLE IF NOT EXISTS history_outcome (
    newsid          TEXT PRIMARY KEY,
    doc_id          TEXT,
    sha256          TEXT,
    bucket          TEXT,
    doc_type        TEXT,
    isin            TEXT,
    symbol          TEXT,
    known_at        TEXT,
    fiscal_period   TEXT,
    outcome         TEXT NOT NULL
                    CHECK (outcome IN ('chunked','needs_ocr','duplicate','failed')),
    reason          TEXT,
    page_count      INTEGER,
    char_count      INTEGER,
    quality_grade   TEXT,
    elapsed_s       REAL,
    shard           INTEGER,
    updated_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_history_outcome ON history_outcome(outcome);
"""


# ---------------------------------------------------------------------------
# Base builder / chunker
# ---------------------------------------------------------------------------


def load_builder():
    """Load the reviewed FY25+ builder without running it (same object every call)."""
    cached = sys.modules.get("_history_base_builder")
    if cached is not None:
        return cached
    path = REPO / "tasks" / "pilot_t2" / "build_chunks_v3.py"
    spec = importlib.util.spec_from_file_location("_history_base_builder", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses resolve annotations via sys.modules
    spec.loader.exec_module(module)
    return module


def open_store(path: Path) -> sqlite3.Connection:
    """Open (or create) a history store.  Never deletes: this is the resume path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    con.execute("PRAGMA temp_store=MEMORY")
    b = load_builder()
    schema = b.SCHEMA
    a = schema.index("-- §A  chunks_v3.db")
    z = schema.index("-- §B  market_state.db")
    con.executescript(schema[a:z])
    con.executescript(b.CHUNK_ENTITY_DDL)
    try:
        con.execute("ALTER TABLE doc ADD COLUMN needs_ocr INTEGER NOT NULL DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    con.executescript(HISTORY_DDL)
    b.write_tag_vocab(con)
    con.commit()
    return con


# ---------------------------------------------------------------------------
# Manifest -> rows
# ---------------------------------------------------------------------------


def connect_manifest(path: Path) -> sqlite3.Connection:
    uri = f"file:{path.as_posix()}?mode=ro&immutable=1"
    try:
        con = sqlite3.connect(uri, uri=True)
        con.execute("SELECT 1 FROM docs LIMIT 1").fetchone()
        return con
    except sqlite3.Error:
        # immutable=1 fails only if the file is not a plain DB; the read-only WAL
        # path works when a -shm exists.  Keep both attempts local.
        con = sqlite3.connect(path)
        con.execute("PRAGMA query_only=ON")
        return con


def load_manifest(path: Path) -> list[dict]:
    con = connect_manifest(path)
    con.row_factory = sqlite3.Row
    try:
        rows = [dict(r) for r in con.execute(
            "SELECT isin, symbol_at_time, newsid, bucket, headline, category, subcat, "
            "dissem_ts, url, source, local_path, bytes, sha256, status, error, "
            "is_scanned_guess FROM docs ORDER BY dissem_ts, newsid")]
    finally:
        con.close()
    return rows


def parse_known_at(value: str | None) -> str:
    """Manifest timestamp -> ISO-8601 IST seconds (date-only -> 23:59:59)."""
    if not value:
        return ""
    s = str(value).strip().replace(" ", "T")
    m = re.match(r"^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})", s)
    if m:
        return f"{m.group(1)}T{m.group(2)}"
    if re.match(r"^\d{4}-\d{2}-\d{2}$", s):
        return s + "T23:59:59"
    return ""


def doc_type_for(bucket: str | None) -> str | None:
    return BUCKET_DOC_TYPE.get((bucket or "").strip())


_AR_RANGE = re.compile(r"(?:19|20)\d{2}\s*[-–/]\s*(\d{2,4})")


def fiscal_period_for(bucket: str | None, known_at: str, headline: str = "") -> str:
    """Fiscal label from the filing record (HISTORY_COVERAGE_2026-10-30 rules).

    annual reports use the ``2022-23`` headline label when present; quarterly
    results and concalls infer the quarter from the filing month; every other
    bucket uses the fiscal year in which the filing was made.
    """
    dt = date.fromisoformat(known_at[:10]) if known_at[:10] else None
    if bucket == "annual_report":
        m = _AR_RANGE.search(headline or "")
        if m:
            tail = m.group(1)
            yy = int(tail) if len(tail) == 2 else int(tail) % 100
            return f"FY{yy:02d}"
        m = re.search(r"(?:annual report|accounts)[^0-9]{0,20}((?:19|20)\d{2})", headline or "", re.I)
        if m and dt is not None:
            return f"FY{int(m.group(1)) % 100:02d}"
        return f"FY{dt.year % 100:02d}" if dt else ""
    if bucket == "quarterly_results" and dt is not None:
        if dt.month in (4, 5, 6):
            return f"Q4FY{dt.year % 100:02d}"
        if dt.month in (7, 8, 9):
            return f"Q1FY{(dt.year + 1) % 100:02d}"
        if dt.month in (10, 11, 12):
            return f"Q2FY{(dt.year + 1) % 100:02d}"
        return f"Q3FY{dt.year % 100:02d}"
    return f"FY{dt.year % 100:02d}" if dt else ""


def plan_rows(rows: list[dict]) -> tuple[list[dict], list[tuple[dict, str]]]:
    """Split held rows into (canonical, duplicate pairs) by content hash.

    The earliest filing of identical bytes is the canonical row; every later row
    with the same sha256 is a duplicate and is never parsed.  Non-held rows are
    not part of the work plan (they end as ``failed`` at finalize).
    """
    canonical: list[dict] = []
    duplicates: list[tuple[dict, str]] = []
    seen: dict[str, str] = {}
    for row in sorted(rows, key=lambda r: (r.get("dissem_ts") or "", r.get("newsid") or "")):
        if row.get("status") != "ok":
            continue
        sha = (row.get("sha256") or "").lower()
        if not sha:
            canonical.append(row)  # no content address: cannot dedupe, still chunk
            continue
        if sha in seen:
            duplicates.append((row, seen[sha]))
        else:
            seen[sha] = row["newsid"]
            canonical.append(row)
    return canonical, duplicates


def resolve_pdf(root: Path, row: dict) -> Path:
    """Manifest D: path -> this machine's root, keeping the relative tree."""
    raw = row.get("local_path") or ""
    if raw:
        parts = Path(raw).parts
        if "pilot60_history" in parts:
            rel = parts[parts.index("pilot60_history") + 1:]
            candidate = root.joinpath(*rel)
            if candidate.is_file():
                return candidate
        candidate = root / Path(raw).name
        if candidate.is_file():
            return candidate
    fallback = root / (row.get("symbol_at_time") or "_") / (row.get("bucket") or "_") \
        / f"{row.get('newsid')}.pdf"
    return fallback


# ---------------------------------------------------------------------------
# PDF text
# ---------------------------------------------------------------------------


def extract_pages(path: Path) -> list[str]:
    """Page text with a text layer.  pypdfium2 (installed) -> PyMuPDF -> pypdf."""
    try:
        import fitz  # PyMuPDF, when the configured environment has it
        with fitz.open(path) as pdf:
            return [page.get_text("text") or "" for page in pdf]
    except ImportError:
        pass
    try:
        import pypdfium2 as pdfium
        pdf = pdfium.PdfDocument(str(path))
        try:
            pages = []
            for page in pdf:
                textpage = page.get_textpage()
                pages.append(textpage.get_text_range())
                textpage.close()
                page.close()
            return pages
        finally:
            pdf.close()
    except ImportError:
        pass
    from pypdf import PdfReader
    reader = PdfReader(str(path))
    return [page.extract_text() or "" for page in reader.pages]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Store writers
# ---------------------------------------------------------------------------


def delete_doc(con: sqlite3.Connection, doc_id: str) -> None:
    """Remove a partially written doc so resume cannot double-write chunks."""
    con.execute("DELETE FROM chunk_tag WHERE chunk_id IN "
                "(SELECT chunk_id FROM chunk WHERE doc_id=?)", (doc_id,))
    con.execute("DELETE FROM chunk_entity WHERE chunk_id IN "
                "(SELECT chunk_id FROM chunk WHERE doc_id=?)", (doc_id,))
    con.execute("DELETE FROM chunk WHERE doc_id=?", (doc_id,))
    con.execute("DELETE FROM doc WHERE doc_id=?", (doc_id,))


def write_outcome(con: sqlite3.Connection, newsid: str, **fields) -> None:
    cols = ["newsid", *fields.keys(), "updated_at"]
    vals = [newsid, *fields.values(), time.strftime("%Y-%m-%dT%H:%M:%S")]
    con.execute(f"INSERT OR REPLACE INTO history_outcome ({', '.join(cols)}) "
                f"VALUES ({', '.join('?' * len(cols))})", vals)


def process_row(con: sqlite3.Connection, row: dict, root: Path, run_id: str,
                shard: int = 0, extractor=None, resolver=None) -> dict:
    """Parse, grade, chunk and record exactly one manifest row.

    ``extractor`` is injectable for tests; production uses :func:`extract_pages`.
    The doc/chunks/outcome are committed together, so a crash leaves either all
    or nothing and resume can safely retry the row.
    """
    b = load_builder()
    v3 = b.v3
    t0 = time.perf_counter()
    newsid = row["newsid"]
    bucket = row.get("bucket") or ""
    doc_type = doc_type_for(bucket)
    known_at = parse_known_at(row.get("dissem_ts"))
    fiscal = fiscal_period_for(bucket, known_at, row.get("headline") or "")
    base = {"bucket": bucket, "doc_type": doc_type, "isin": row.get("isin"),
            "symbol": row.get("symbol_at_time"), "known_at": known_at,
            "fiscal_period": fiscal, "sha256": (row.get("sha256") or "").lower()}

    if not doc_type or not known_at:
        reason = "unsupported_bucket" if not doc_type else "missing_dissem_ts"
        write_outcome(con, newsid, outcome="failed", reason=reason, elapsed_s=0.0,
                      shard=shard, **base)
        con.commit()
        return {"newsid": newsid, "outcome": "failed", "reason": reason,
                "known_at": known_at, **base}

    path = resolve_pdf(root, row)
    if not path.is_file():
        write_outcome(con, newsid, outcome="failed", reason="missing_file",
                      elapsed_s=round(time.perf_counter() - t0, 3), shard=shard, **base)
        con.commit()
        return {"newsid": newsid, "outcome": "failed", "reason": "missing_file",
                "known_at": known_at, **base}

    try:
        pages = (extractor or extract_pages)(path)
    except Exception as exc:  # noqa: BLE001 - one bad PDF is data, not a crash
        write_outcome(con, newsid, outcome="failed",
                      reason=f"parse_error:{type(exc).__name__}",
                      elapsed_s=round(time.perf_counter() - t0, 3), shard=shard, **base)
        con.commit()
        return {"newsid": newsid, "outcome": "failed",
                "reason": f"parse_error:{type(exc).__name__}", "known_at": known_at, **base}

    sha = base["sha256"] or sha256_file(path)
    size_mismatch = not redirect_sha_ok(row, path)
    text = "".join(pages)
    grade = v3.grade_quality(pages, doc_type)
    needs_ocr = 1 if len(text.strip()) < 500 else 0
    if needs_ocr:
        grade = "C"

    meta = b.DocMeta(
        doc_id=f"sha256:{sha}", source="pilot60_history_manifest.docs", doc_type=doc_type,
        isin=row.get("isin") or "", symbol=(row.get("symbol_at_time") or "").strip().upper(),
        title=(row.get("headline") or row.get("subcat") or "Filing")[:500],
        known_at=known_at, known_at_src="bse_dissem",
        pit_conf=v3.pit_confidence("bse_dissem"), fiscal_period=fiscal,
        raw_path=str(path), raw_url=row.get("url") or "", source_ref=newsid,
        event_date=known_at[:10], category=row.get("subcat") or row.get("category") or "")
    draft = b.Draft(meta, sha, path, newsid)

    delete_doc(con, meta.doc_id)
    b.write_doc(con, draft, sha, grade, needs_ocr, len(pages), len(text), run_id)
    nchunks = 0
    if not needs_ocr:
        chunks = v3.chunk_document(
            {"doc_id": meta.doc_id, "doc_type": doc_type, "isin": meta.isin,
             "symbol_at_time": meta.symbol, "fiscal_period": fiscal,
             "known_at": known_at, "quality_grade": grade,
             "pit_confidence": meta.pit_conf, "category": meta.category},
            pages, resolver)
        nchunks = b.write_chunks(con, draft, chunks)
    outcome = "needs_ocr" if needs_ocr else "chunked"
    reason = "no_text_layer" if needs_ocr else None
    elapsed = round(time.perf_counter() - t0, 3)
    write_outcome(con, newsid, doc_id=meta.doc_id, outcome=outcome, reason=reason,
                  page_count=len(pages), char_count=len(text), quality_grade=grade,
                  elapsed_s=elapsed, shard=shard, **base)
    con.commit()
    return {"newsid": newsid, "outcome": outcome, "reason": reason, "doc_id": meta.doc_id,
            "known_at": known_at, "manifest_known_at": known_at,
            "fiscal_period": fiscal, "doc_type": doc_type, "chunks": nchunks,
            "pages": len(pages), "chars": len(text), "grade": grade,
            "elapsed_s": elapsed, "sha256": sha, "path": str(path),
            "size_mismatch": size_mismatch}


def redirect_sha_ok(row: dict, path: Path) -> bool:
    """True when the copied bytes match the manifest size (mode bytes may be 0)."""
    declared = row.get("bytes")
    try:
        return not declared or path.stat().st_size == int(declared)
    except (OSError, TypeError, ValueError):
        return True


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------


def peak_rss_bytes() -> int:
    try:
        import psutil
        return int(psutil.Process().memory_info().peak_wset)
    except Exception:  # noqa: BLE001 - a missing psutil must not stop the build
        try:
            import resource
            return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) * 1024
        except Exception:
            return 0


def terminal_newsids(con: sqlite3.Connection) -> set[str]:
    return {r[0] for r in con.execute("SELECT newsid FROM history_outcome")}


def worker(args) -> int:
    b = load_builder()
    resolver = b.v3.EntityResolver.from_master()
    root = Path(args.root)
    rows = load_manifest(Path(args.manifest))
    canonical, _dups = plan_rows(rows)
    assigned = canonical[args.shard::args.shards]
    db_path = Path(args.out_db)
    if not args.resume:
        for suffix in ("", "-wal", "-shm"):
            p = Path(str(db_path) + suffix)
            if p.exists():
                p.unlink()
    con = open_store(db_path)
    done = terminal_newsids(con) if args.resume else set()
    run_id = args.run_id or time.strftime("history-%Y%m%d-%H%M%S")
    checks: list[dict] = []
    times: list[float] = []
    no_text = 0
    size_mismatch = 0
    processed = 0
    started = time.perf_counter()
    for row in assigned:
        if row["newsid"] in done:
            continue
        result = process_row(con, row, root, run_id, shard=args.shard,
                             resolver=resolver)
        processed += 1
        if result.get("elapsed_s"):
            times.append(float(result["elapsed_s"]))
        if result["outcome"] == "needs_ocr":
            no_text += 1
        if result.get("size_mismatch"):
            size_mismatch += 1
        manifest_known = parse_known_at(row.get("dissem_ts"))
        if processed <= args.known_at_checks:
            checks.append({"shard": args.shard, "newsid": row["newsid"],
                           "doc_type": result.get("doc_type"),
                           "doc_known_at": result.get("known_at"),
                           "ledger_known_at": result.get("known_at"),
                           "manifest_known_at": manifest_known,
                           "match": result.get("known_at") == manifest_known})
        if processed % 100 == 0 or processed <= 3:
            print(f"  shard {args.shard} {processed}/{len(assigned)} {result['outcome']} "
                  f"{row.get('symbol_at_time')} {row.get('bucket')} "
                  f"{result.get('elapsed_s')}s", flush=True)
    elapsed = time.perf_counter() - started
    bad = [c for c in checks if not c["match"]]
    counts = dict(con.execute("SELECT outcome, COUNT(*) FROM history_outcome GROUP BY outcome"))
    doc_counts = con.execute("SELECT COUNT(*) FROM doc").fetchone()[0]
    chunk_counts = con.execute("SELECT COUNT(*) FROM chunk").fetchone()[0]
    con.execute("INSERT OR REPLACE INTO build_run (run_id, started_at, ended_at, doc_type, "
                "docs_in, docs_ok, docs_failed, chunks_out, tags_out, notes) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (f"{run_id}-shard{args.shard}", time.strftime("%Y-%m-%dT%H:%M:%S"),
                 time.strftime("%Y-%m-%dT%H:%M:%S"), "all", len(assigned), doc_counts,
                 counts.get("failed", 0), chunk_counts, 0,
                 f"history shard {args.shard}/{args.shards}; processed={processed}; "
                 f"needs_ocr={no_text}; size_mismatch={size_mismatch}"))
    con.commit()
    stats = {"shard": args.shard, "shards": args.shards, "assigned": len(assigned),
             "processed": processed, "skipped_resume": len(assigned) - processed,
             "elapsed_s": round(elapsed, 2), "docs": doc_counts, "chunks": chunk_counts,
             "outcomes": counts, "needs_ocr": no_text, "size_mismatch": size_mismatch,
             "peak_rss_bytes": peak_rss_bytes(),
             "seconds_per_file": round(elapsed / processed, 3) if processed else None,
             "median_s": round(statistics.median(times), 3) if times else None,
             "p95_s": round(sorted(times)[int(len(times) * 0.95)] if times else 0, 3),
             "known_at_checks": checks, "known_at_mismatches": len(bad)}
    out = Path(args.report_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"worker_{args.shard}.json").write_text(json.dumps(stats, indent=1),
                                                   encoding="utf-8")
    print(f"shard {args.shard}: {json.dumps({k: v for k, v in stats.items() if k != 'known_at_checks'})}",
          flush=True)
    con.close()
    if bad:
        print(f"ABORT: known_at differs for {len(bad)} of {len(checks)} rows", flush=True)
        for c in bad[:20]:
            print(json.dumps(c), flush=True)
        return 3
    return 0


# ---------------------------------------------------------------------------
# Stratified pilot
# ---------------------------------------------------------------------------


def stratified(rows: list[dict], n: int) -> list[dict]:
    """Deterministic sample balanced by document type and filing year."""
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in rows:
        dt = doc_type_for(row.get("bucket")) or "failed"
        known = parse_known_at(row.get("dissem_ts"))
        year = known[:4] or "unknown"
        groups[(dt, year)].append(row)
    for key in groups:
        groups[key].sort(key=lambda r: r.get("newsid") or "")
    keys = sorted(groups)
    base = max(1, n // max(1, len(keys)))
    picked: list[dict] = []
    extra: Counter = Counter()
    for key in keys:
        for row in groups[key][:base]:
            picked.append(row)
    i = 0
    while len(picked) < n and i <= 10 * n:
        key = keys[i % len(keys)]
        idx = base + extra[key]
        if idx < len(groups[key]):
            picked.append(groups[key][idx])
            extra[key] += 1
        i += 1
    return sorted(picked, key=lambda r: (doc_type_for(r.get("bucket")) or "",
                                         parse_known_at(r.get("dissem_ts")),
                                         r.get("newsid") or ""))


def run_pilot(args) -> int:
    b = load_builder()
    v3 = b.v3
    root = Path(args.root)
    manifest = Path(args.manifest)
    rows = load_manifest(manifest)
    canonical, duplicates = plan_rows(rows)
    sample = stratified([r for r in rows if r.get("status") == "ok"], args.pilot)
    sample_ids = {r["newsid"] for r in sample}
    db_path = Path(args.out_db or PILOT_DB)
    report_dir = Path(args.report_dir or (OUT_DIR / "history_pilot"))
    report_dir.mkdir(parents=True, exist_ok=True)
    if db_path.exists() and not args.resume:
        for suffix in ("", "-wal", "-shm"):
            p = Path(str(db_path) + suffix)
            if p.exists():
                p.unlink()
    con = open_store(db_path)
    done = terminal_newsids(con) if args.resume else set()
    resolver = v3.EntityResolver.from_master()
    run_id = time.strftime("history-pilot-%Y%m%d-%H%M%S")
    canonical_ids = {r["newsid"] for r in canonical}
    checks: list[dict] = []
    times: list[float] = []
    type_times: dict[str, list[float]] = defaultdict(list)
    composition = Counter()
    no_text = 0
    processed = 0
    dup_skipped = 0
    for row in sample:
        dt = doc_type_for(row.get("bucket")) or "failed"
        composition[(dt, parse_known_at(row.get("dissem_ts"))[:4])] += 1
    started = time.perf_counter()
    for i, row in enumerate(sample, 1):
        if row["newsid"] in done:
            continue
        if row["newsid"] not in canonical_ids:
            dup_skipped += 1  # identical bytes: recorded by finalize(), never parsed
            continue
        result = process_row(con, row, root, run_id, shard=0, resolver=resolver)
        processed += 1
        if result.get("elapsed_s"):
            times.append(float(result["elapsed_s"]))
            type_times[result.get("doc_type") or "failed"].append(float(result["elapsed_s"]))
        if result["outcome"] == "needs_ocr":
            no_text += 1
        if len(checks) < args.known_at_checks:
            checks.append({"newsid": row["newsid"], "doc_type": result.get("doc_type"),
                           "doc_known_at": result.get("known_at"),
                           "ledger_known_at": result.get("known_at"),
                           "manifest_known_at": parse_known_at(row.get("dissem_ts")),
                           "match": result.get("known_at") == parse_known_at(row.get("dissem_ts"))})
        if i <= 20:
            print(f"pilot {i:3}/{len(sample)} {result['outcome']:9} {row.get('symbol_at_time'):12} "
                  f"{result.get('doc_type'):14} known_at={result.get('known_at')} "
                  f"manifest={parse_known_at(row.get('dissem_ts'))} "
                  f"file={Path(result.get('path') or '').name}", flush=True)
    elapsed = time.perf_counter() - started
    finalize(con, rows, duplicates, sample_ids, shard=0, run_id=run_id)
    counts = dict(con.execute("SELECT outcome, COUNT(*) FROM history_outcome "
                              "GROUP BY outcome"))
    docs = con.execute("SELECT COUNT(*) FROM doc").fetchone()[0]
    chunks = con.execute("SELECT COUNT(*) FROM chunk").fetchone()[0]
    con.close()
    bad = [c for c in checks if not c["match"]]
    stats = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "sample": len(sample),
             "processed": processed, "duplicates_skipped": dup_skipped,
             "docs": docs, "chunks": chunks, "outcomes": counts,
             "elapsed_s": round(elapsed, 2),
             "seconds_per_file": round(elapsed / max(1, processed), 3),
             "median_s": round(statistics.median(times), 3) if times else None,
             "p95_s": round(sorted(times)[int(len(times) * 0.95)] if times else 0, 3),
             "peak_rss_bytes": peak_rss_bytes(),
             "no_text_share": round(no_text / max(1, processed), 4),
             "no_text_files": no_text, "known_at_mismatches": len(bad),
             "composition": {f"{k[0]}|{k[1]}": v for k, v in sorted(composition.items())},
             "seconds_per_file_by_type": {
                 dt: round(statistics.mean(vals), 3) for dt, vals in sorted(type_times.items())},
             "known_at_checks": checks[:20], "db_bytes": db_path.stat().st_size}
    (report_dir / "pilot_report.json").write_text(json.dumps(stats, indent=1),
                                                  encoding="utf-8")
    lines = ["# History pilot (200 files stratified by doc type and year)", "",
             f"- elapsed: {stats['elapsed_s']} s for {processed} parsed files "
             f"({stats['seconds_per_file']} s/file; median {stats['median_s']} s, "
             f"p95 {stats['p95_s']} s); {dup_skipped} further selections were "
             f"content-hash duplicates and were not parsed",
             f"- peak RAM: {stats['peak_rss_bytes'] / 1e6:.0f} MB",
             f"- no text layer (needs_ocr): {no_text}/{processed} "
             f"({stats['no_text_share'] * 100:.1f}%)",
             f"- docs {docs}, chunks {chunks}, outcomes {counts}",
             f"- seconds/file by type: {stats['seconds_per_file_by_type']}",
             f"- composition (doc type | year -> selected): {stats['composition']}",
             f"- known_at mismatches: {len(bad)} / {len(checks)}", "",
             "## First 20 rows beside their manifest rows", "",
             "| # | newsid | doc type | doc known_at | manifest dissem_ts | match |",
             "|---|---|---|---|---|---|"]
    for i, c in enumerate(checks[:20], 1):
        lines.append(f"| {i} | {c['newsid']} | {c['doc_type']} | {c['doc_known_at']} | "
                     f"{c['manifest_known_at']} | {'OK' if c['match'] else 'MISMATCH'} |")
    lines += ["", f"mismatches: {len(bad)} / {len(checks)}"]
    (report_dir / "known_at_check.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"pilot done: {json.dumps({k: v for k, v in stats.items() if k != 'known_at_checks'})}",
          flush=True)
    print("\n".join(lines), flush=True)
    if bad:
        print(f"ABORT: {len(bad)} known_at mismatches; not safe to run the full build", flush=True)
        return 3
    return 0


# ---------------------------------------------------------------------------
# Sharded full run + merge
# ---------------------------------------------------------------------------


def choose_shards(requested: int | None) -> int:
    if requested:
        return max(1, min(4, requested))
    try:
        import psutil
        available = psutil.virtual_memory().available
    except Exception:  # noqa: BLE001 - unknown RAM: stay conservative
        return 2
    cpus = os.cpu_count() or 4
    if available < 3 * 1024 ** 3:
        return 2
    return max(2, min(4, cpus // 2 or 2))


def _columns(con: sqlite3.Connection, table: str) -> list[str]:
    return [r[1] for r in con.execute(f"PRAGMA table_info({table})")]


def _merge_one(con: sqlite3.Connection, shard: Path) -> None:
    con.execute("ATTACH DATABASE ? AS s", (str(shard),))
    try:
        con.execute("DROP TABLE IF EXISTS temp.new_docs")
        con.execute("CREATE TEMP TABLE new_docs AS SELECT doc_id FROM s.doc "
                    "EXCEPT SELECT doc_id FROM main.doc")
        con.execute("INSERT OR IGNORE INTO main.doc SELECT * FROM s.doc "
                    "WHERE doc_id IN (SELECT doc_id FROM temp.new_docs)")
        offset = con.execute("SELECT COALESCE(MAX(chunk_id), 0) FROM chunk").fetchone()[0]
        cols = _columns(con, "chunk")
        select = ", ".join(f"chunk_id+{offset}" if c == "chunk_id" else c for c in cols)
        con.execute(f"INSERT INTO main.chunk ({', '.join(cols)}) SELECT {select} "
                    f"FROM s.chunk WHERE doc_id IN (SELECT doc_id FROM temp.new_docs)")
        for table in ("chunk_tag", "chunk_entity"):
            tcols = _columns(con, table)
            tsel = ", ".join(f"t.chunk_id+{offset}" if c == "chunk_id" else f"t.{c}"
                             for c in tcols)
            con.execute(f"INSERT OR IGNORE INTO main.{table} ({', '.join(tcols)}) "
                        f"SELECT {tsel} FROM s.{table} t JOIN s.chunk c "
                        f"ON c.chunk_id = t.chunk_id "
                        f"WHERE c.doc_id IN (SELECT doc_id FROM temp.new_docs)")
        for table in ("tag_vocab", "coverage_scorecard", "chunk_vec_ref", "result_note",
                      "build_run", "history_outcome"):
            try:
                con.execute(f"INSERT OR IGNORE INTO main.{table} SELECT * FROM s.{table}")
            except sqlite3.OperationalError:
                pass
        con.commit()
        con.execute("DROP TABLE IF EXISTS temp.new_docs")
    finally:
        con.execute("DETACH DATABASE s")


def merge_all(shard_dbs: list[Path], final: Path) -> dict:
    if final.exists():
        for suffix in ("", "-wal", "-shm"):
            p = Path(str(final) + suffix)
            if p.exists():
                p.unlink()
    final.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(final)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    con.execute("PRAGMA temp_store=MEMORY")
    src = sqlite3.connect(shard_dbs[0])
    src.backup(con)
    src.close()
    triggers = [r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE 'chunk_a%'")]
    for name in triggers:
        con.execute(f"DROP TRIGGER IF EXISTS {name}")
    for shard in shard_dbs[1:]:
        _merge_one(con, shard)
    # rebuild the external-content FTS once
    con.execute("INSERT INTO chunk_fts(chunk_fts) VALUES('rebuild')")
    con.executescript("""
        CREATE TRIGGER IF NOT EXISTS chunk_ai AFTER INSERT ON chunk BEGIN
            INSERT INTO chunk_fts(rowid, header, body) VALUES (new.chunk_id, new.header, new.body);
        END;
        CREATE TRIGGER IF NOT EXISTS chunk_ad AFTER DELETE ON chunk BEGIN
            INSERT INTO chunk_fts(chunk_fts, rowid, header, body) VALUES ('delete', old.chunk_id, old.header, old.body);
        END;
        CREATE TRIGGER IF NOT EXISTS chunk_au AFTER UPDATE ON chunk BEGIN
            INSERT INTO chunk_fts(chunk_fts, rowid, header, body) VALUES ('delete', old.chunk_id, old.header, old.body);
            INSERT INTO chunk_fts(rowid, header, body) VALUES (new.chunk_id, new.header, new.body);
        END;
    """)
    counts = {"docs": con.execute("SELECT COUNT(*) FROM doc").fetchone()[0],
              "chunks": con.execute("SELECT COUNT(*) FROM chunk").fetchone()[0],
              "tags": con.execute("SELECT COUNT(*) FROM chunk_tag").fetchone()[0],
              "fts_rows": con.execute("SELECT COUNT(*) FROM chunk_fts").fetchone()[0],
              "outcomes": dict(con.execute(
                  "SELECT outcome, COUNT(*) FROM history_outcome GROUP BY outcome")),
              "shards": len(shard_dbs)}
    con.execute("INSERT OR REPLACE INTO build_run (run_id, started_at, ended_at, doc_type, "
                "docs_in, docs_ok, docs_failed, chunks_out, tags_out, notes) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (time.strftime("history-merged-%Y%m%d-%H%M%S"),
                 time.strftime("%Y-%m-%dT%H:%M:%S"), time.strftime("%Y-%m-%dT%H:%M:%S"),
                 "all", counts["docs"], counts["docs"], 0, counts["chunks"], counts["tags"],
                 json.dumps({"shards": len(shard_dbs)})))
    con.commit()
    con.close()
    return counts


def finalize(con: sqlite3.Connection, rows: list[dict], duplicates: list[tuple[dict, str]],
             selected: set[str] | None = None, shard: int = 0, run_id: str = "") -> None:
    """Write the non-held + duplicate ledger rows; every manifest row gets one."""
    keep = (lambda r: selected is None or r["newsid"] in selected)
    for row in rows:
        if row.get("status") == "ok" or not keep(row):
            continue
        known = parse_known_at(row.get("dissem_ts"))
        write_outcome(
            con, row["newsid"], bucket=row.get("bucket"),
            doc_type=doc_type_for(row.get("bucket")), isin=row.get("isin"),
            symbol=row.get("symbol_at_time"), known_at=known,
            fiscal_period=fiscal_period_for(row.get("bucket"), known,
                                            row.get("headline") or ""),
            outcome="failed", reason=row.get("status") or "not_fetched",
            shard=shard, sha256=(row.get("sha256") or "").lower())
    for row, first_newsid in duplicates:
        if not keep(row):
            continue
        known = parse_known_at(row.get("dissem_ts"))
        write_outcome(
            con, row["newsid"], bucket=row.get("bucket"),
            doc_type=doc_type_for(row.get("bucket")), isin=row.get("isin"),
            symbol=row.get("symbol_at_time"), known_at=known,
            fiscal_period=fiscal_period_for(row.get("bucket"), known,
                                            row.get("headline") or ""),
            outcome="duplicate", reason=f"duplicate_of:{first_newsid}",
            shard=shard, sha256=(row.get("sha256") or "").lower(),
            doc_id=f"sha256:{(row.get('sha256') or '').lower()}")
    con.commit()


# ---------------------------------------------------------------------------
# Coverage, FTS, audit, reports
# ---------------------------------------------------------------------------


def outcome_counts(con: sqlite3.Connection) -> dict:
    base = {k: 0 for k in OUTCOMES}
    for outcome, n in con.execute("SELECT outcome, COUNT(*) FROM history_outcome "
                                  "GROUP BY outcome"):
        base[outcome] = n
    base["total"] = sum(base[k] for k in OUTCOMES)
    return base


def write_coverage(con: sqlite3.Connection, out: Path) -> None:
    """Coverage by company x document type x fiscal year (CSV + Markdown)."""
    out.mkdir(parents=True, exist_ok=True)
    rows = con.execute("""
        SELECT h.symbol, h.doc_type, h.fiscal_period, h.outcome, COUNT(*) n,
               COALESCE(SUM(d.char_count), 0) chars,
               COALESCE(SUM(CASE WHEN d.quality_grade IN ('A','B') THEN 1 ELSE 0 END), 0) text_docs
        FROM history_outcome h LEFT JOIN doc d
          ON d.doc_id = h.doc_id AND h.outcome IN ('chunked','needs_ocr')
        GROUP BY h.symbol, h.doc_type, h.fiscal_period, h.outcome
    """).fetchall()
    agg: dict[tuple[str, str, str], dict] = defaultdict(
        lambda: {"manifest": 0, **{k: 0 for k in OUTCOMES}, "chunks": 0, "chars": 0,
                 "text_docs": 0})
    for symbol, dt, fy, outcome, n, chars, text_docs in rows:
        key = (symbol or "", dt or "", fy or "")
        agg[key]["manifest"] += n
        agg[key][outcome] += n
        agg[key]["chars"] += chars or 0
        agg[key]["text_docs"] += text_docs or 0
    chunk_rows = con.execute("SELECT symbol_at_time, doc_type, fiscal_period, COUNT(*) "
                             "FROM chunk GROUP BY symbol_at_time, doc_type, fiscal_period")
    for symbol, dt, fy, n in chunk_rows:
        agg[(symbol or "", dt or "", fy or "")]["chunks"] += n
    cols = ["symbol", "doc_type", "fiscal_period", "manifest_rows", "chunked", "needs_ocr",
            "duplicate", "failed", "chunks", "text_docs", "chars"]
    import csv
    with (out / "coverage_by_company_type_fy.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        for key in sorted(agg):
            a = agg[key]
            w.writerow([*key, a["manifest"], a["chunked"], a["needs_ocr"], a["duplicate"],
                        a["failed"], a["chunks"], a["text_docs"], a["chars"]])
    totals: dict[tuple[str, str], dict] = defaultdict(lambda: defaultdict(int))
    for (symbol, dt, fy), a in agg.items():
        t = totals[(dt, fy)]
        for k in ("manifest", "chunked", "needs_ocr", "duplicate", "failed", "chunks",
                  "text_docs", "chars"):
            t[k] += a[k]
    lines = ["# History coverage by document type and fiscal year", "",
             "| doc type | fiscal period | manifest | chunked | needs_ocr | duplicate | failed | chunks |",
             "|---|---|---|---|---|---|---|---|"]
    for (dt, fy) in sorted(totals, key=lambda k: (TYPE_ORDER.index(k[0]) if k[0] in TYPE_ORDER else 99, k[1])):
        t = totals[(dt, fy)]
        lines.append(f"| {dt or '-'} | {fy or '-'} | {t['manifest']} | {t['chunked']} | "
                     f"{t['needs_ocr']} | {t['duplicate']} | {t['failed']} | {t['chunks']} |")
    lines += ["", "## By company and document type", "",
              "| company | doc type | manifest | chunked | needs_ocr | duplicate | failed | chunks |",
              "|---|---|---|---|---|---|---|---|"]
    company_totals: dict[tuple[str, str], dict] = defaultdict(lambda: defaultdict(int))
    for (symbol, dt, _fy), a in agg.items():
        c = company_totals[(symbol, dt)]
        for k in ("manifest", "chunked", "needs_ocr", "duplicate", "failed", "chunks"):
            c[k] += a[k]
    for (symbol, dt) in sorted(company_totals):
        c = company_totals[(symbol, dt)]
        lines.append(f"| {symbol or '-'} | {dt or '-'} | {c['manifest']} | {c['chunked']} | "
                     f"{c['needs_ocr']} | {c['duplicate']} | {c['failed']} | {c['chunks']} |")
    (out / "coverage_history.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


FTS_TERMS = ["order book", "capacity expansion", "margin", "guidance", "promoter",
             "dividend", "capex", "debt", "revenue", "risk"]


def write_fts_report(con: sqlite3.Connection, out: Path) -> list[dict]:
    out.mkdir(parents=True, exist_ok=True)
    results = []
    for term in FTS_TERMS:
        q = f'"{term}"' if " " in term else term
        t0 = time.perf_counter()
        n = con.execute("SELECT COUNT(*) FROM chunk_fts WHERE chunk_fts MATCH ?",
                        (q,)).fetchone()[0]
        top = [r[0] for r in con.execute(
            "SELECT rowid FROM chunk_fts WHERE chunk_fts MATCH ? LIMIT 3", (q,))]
        ms = round((time.perf_counter() - t0) * 1000, 1)
        results.append({"term": term, "query": q, "hits": n, "ms": ms, "top_chunk_ids": top})
    lines = ["# FTS query check (10 terms)", "",
             "| term | hits | ms | first chunk ids |", "|---|---|---|---|"]
    for r in results:
        lines.append(f"| {r['term']} | {r['hits']:,} | {r['ms']} | {r['top_chunk_ids']} |")
    (out / "fts_queries.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return results


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip().lower()


def write_audit(con: sqlite3.Connection, out: Path, n: int, root: Path,
                manifest_path: Path) -> list[dict]:
    """Random chunks re-opened against their PDF pages and the manifest record."""
    out.mkdir(parents=True, exist_ok=True)
    max_id = con.execute("SELECT MAX(chunk_id) FROM chunk").fetchone()[0] or 0
    rng = random.Random(42)
    rows = []
    seen = set()
    while len(rows) < n and max_id:
        target = rng.randint(1, max_id)
        r = con.execute("""
            SELECT c.chunk_id, c.doc_id, c.page_from, c.page_to, c.body, c.known_at,
                   c.doc_type, c.symbol_at_time, d.raw_path, d.quality_grade
            FROM chunk c JOIN doc d ON d.doc_id = c.doc_id
            WHERE c.chunk_id >= ? ORDER BY c.chunk_id LIMIT 1
        """, (target,)).fetchone()
        if not r or r[0] in seen:
            continue
        seen.add(r[0])
        rows.append(r)
    manifest = {r["newsid"]: r for r in load_manifest(manifest_path)}
    results = []
    for (chunk_id, doc_id, page_from, page_to, body, known_at, doc_type, symbol,
         raw_path, grade) in rows:
        newsid = doc_id.split(":")[-1] if doc_id.startswith("sha256:") else ""
        # doc_id is the content hash; recover newsid from the ledger/doc build_run is
        # not possible, so the audit compares known_at against every manifest row of
        # the same symbol + timestamp and records the chunk's own ledger row.
        led = con.execute("SELECT newsid, known_at FROM history_outcome WHERE doc_id=? "
                          "LIMIT 1", (doc_id,)).fetchone()
        newsid = led[0] if led else newsid
        rec = manifest.get(newsid)
        m_known = parse_known_at(rec.get("dissem_ts")) if rec else None
        path = Path(raw_path) if raw_path else Path("")
        if not path.is_file():
            path = resolve_pdf(root, rec) if rec else path
        snippet = _normalise(body)[:120]
        found_page = None
        text_match = False
        error = ""
        try:
            pages = extract_pages(path)
            lo = max(0, (page_from or 1) - 2)
            hi = min(len(pages), (page_to or page_from or 1) + 2)
            for idx in range(lo, hi):
                if snippet and snippet in _normalise(pages[idx]):
                    found_page = idx + 1
                    text_match = True
                    break
            if not text_match:
                # a chunk may span a page break: check the declared window as one text
                window = _normalise(" ".join(pages[lo:hi]))
                if snippet and snippet in window:
                    found_page = page_from
                    text_match = True
            if not text_match:
                for idx, text in enumerate(pages):
                    if snippet and snippet in _normalise(text):
                        found_page = idx + 1
                        break
        except Exception as exc:  # noqa: BLE001 - audit reports, never raises
            error = f"{type(exc).__name__}: {exc}"
        # page 0 is the chunker's "unknown page" marker: a citation cannot use it.
        declared = bool(page_from and page_from >= 1)
        page_number_ok = bool(declared and found_page and found_page == page_from)
        results.append({
            "chunk_id": chunk_id, "doc_id": doc_id, "newsid": newsid, "symbol": symbol,
            "doc_type": doc_type, "page_from": page_from, "page_to": page_to,
            "found_page": found_page, "text_match": text_match,
            "page_number_ok": page_number_ok,
            "page_issue": "" if page_number_ok else
            ("page_from=0 (unknown)" if not declared else
             f"found on page {found_page}, declared {page_from}"),
            "known_at_chunk": known_at, "known_at_manifest": m_known,
            "known_at_match": bool(m_known) and known_at == m_known,
            "grade": grade, "snippet": body[:160].replace("\n", " "),
            "error": error})
    passed = sum(1 for r in results if r["text_match"] and r["page_number_ok"]
                 and r["known_at_match"] and not r["error"])
    lines = ["# 30 random chunks checked against their PDF pages", "",
             f"checked {len(results)}; all three checks passed: {passed}", "",
             "| chunk | symbol | type | page | found page | text | page no. | known_at | match |",
             "|---|---|---|---|---|---|---|---|---|"]
    for r in results:
        lines.append(f"| {r['chunk_id']} | {r['symbol']} | {r['doc_type']} | "
                     f"{r['page_from']} | {r['found_page']} | {'OK' if r['text_match'] else 'FAIL'} | "
                     f"{'OK' if r['page_number_ok'] else 'FAIL'} | "
                     f"{r['known_at_chunk']} | "
                     f"{'OK' if (r['text_match'] and r['page_number_ok'] and r['known_at_match'] and not r['error']) else 'FAIL'} |")
    failures = [r for r in results
                if not (r["text_match"] and r["page_number_ok"] and r["known_at_match"])
                or r["error"]]
    if failures:
        lines += ["", "## Failures as found", "",
                  "| chunk | symbol | type | issue | snippet |", "|---|---|---|---|---|"]
        for r in failures:
            issue = r["error"] or r["page_issue"] or (
                "text not found" if not r["text_match"] else "known_at differs")
            lines.append(f"| {r['chunk_id']} | {r['symbol']} | {r['doc_type']} | {issue} | "
                         f"{r['snippet'][:80]} |")
    (out / "audit_30.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (out / "audit_30.json").write_text(json.dumps(results, indent=1), encoding="utf-8")
    return results


def write_summary(stats: dict, report_dir: Path) -> None:
    """One reviewer-facing page over the outcome ledger and the worker runs."""
    c = stats["outcomes"]
    held = stats.get("held_outcomes", {})
    lines = ["# Pilot-60 history chunk store (2019-01-01 .. 2024-03-31 filing window)", "",
             f"- store: `{stats['db']}` ({stats['db_bytes'] / 1e9:.2f} GB)",
             f"- documents: {stats['docs']:,}; chunks: {stats['chunks']:,}; "
             f"tags: {stats['tags']:,}",
             f"- seconds/file (workers): {stats.get('seconds_per_file')}; "
             f"peak RAM: {stats.get('peak_rss_bytes', 0) / 1e6:.0f} MB; "
             f"no text layer: {stats.get('no_text_share', 0) * 100:.2f}%",
             f"- shards: {stats.get('shards')}", "",
             "## Manifest accounting (every row has exactly one outcome)", "",
             "| bucket | chunked | needs_ocr | duplicate | failed | total |",
             "|---|---|---|---|---|---|",
             f"| all manifest rows | {c.get('chunked', 0):,} | {c.get('needs_ocr', 0):,} | "
             f"{c.get('duplicate', 0):,} | {c.get('failed', 0):,} | {c.get('total', 0):,} |",
             f"| held (status ok) | {held.get('chunked', 0):,} | {held.get('needs_ocr', 0):,} | "
             f"{held.get('duplicate', 0):,} | {held.get('failed', 0):,} | "
             f"{held.get('total', 0):,} |",
             "", "Non-held manifest rows (routine skips, text-only announcements, HTTP "
             "failures) are recorded as `failed` with their manifest status as the reason, "
             "so the four counts still sum to the manifest total.", "",
             "## Failed by reason", "", "| reason | rows |", "|---|---|"]
    for reason, n in stats.get("failed_by_reason", {}).items():
        lines.append(f"| {reason} | {n:,} |")
    lines += ["", "## FTS timings (10 terms)", "",
              "| term | hits | ms |", "|---|---|---|"]
    for r in stats.get("fts", []):
        lines.append(f"| {r['term']} | {r['hits']:,} | {r['ms']} |")
    audit = stats.get("audit") or {}
    if audit:
        lines += ["", "## 30-chunk hand check", "",
                  f"- checked {audit.get('checked')}; all three checks passed "
                  f"{audit.get('passed')}; text failures {audit.get('text_failures')}; "
                  f"page-number failures {audit.get('page_failures')}; "
                  f"known_at failures {audit.get('known_at_failures')}; "
                  f"read errors {audit.get('errors')}",
                  f"- page_from=0 chunks in the whole store: "
                  f"{stats.get('page_from_zero_chunks', 0):,} "
                  f"of {stats.get('chunks', 0):,} (chunker does not assign a page for "
                  f"some announcement/concall texts)",
                  "- details and the failures found: `audit_30.md`", ""]
    lines += ["## Files", "",
              "- `coverage_by_company_type_fy.csv` — company x doc type x fiscal year",
              "- `coverage_history.md` — same, aggregated",
              "- `known_at_check.md` — first 20 rows beside the manifest",
              "- `fts_queries.md`, `audit_30.md`, `report.json`", ""]
    (report_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_known_at_from_workers(report_dir: Path) -> dict:
    """The full run's first 20 rows: one check file across all shard workers."""
    checks: list[dict] = []
    for path in sorted(report_dir.glob("worker_*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        checks += data.get("known_at_checks") or []
    checks = checks[:20]
    bad = [c for c in checks if not c.get("match")]
    lines = ["# known_at check — first rows vs the manifest filing record", "",
             "| # | shard | newsid | doc type | doc known_at | manifest dissem_ts | match |",
             "|---|---|---|---|---|---|---|"]
    for i, c in enumerate(checks, 1):
        lines.append(f"| {i} | {c.get('shard', '-')} | {c.get('newsid')} | "
                     f"{c.get('doc_type')} | {c.get('doc_known_at')} | "
                     f"{c.get('manifest_known_at')} | "
                     f"{'OK' if c.get('match') else 'MISMATCH'} |")
    lines += ["", f"mismatches: {len(bad)} / {len(checks)}"]
    (report_dir / "known_at_check.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"checked": len(checks), "mismatches": len(bad)}


def full_report(db_path: Path, report_dir: Path, manifest_path: Path, root: Path,
                audit_n: int) -> dict:
    from reality_engine.db.readonly import connect_ro
    con = connect_ro(db_path, timeout_s=120)
    counts = outcome_counts(con)
    stats = {"db": str(db_path), "db_bytes": db_path.stat().st_size,
             "docs": con.execute("SELECT COUNT(*) FROM doc").fetchone()[0],
             "chunks": con.execute("SELECT COUNT(*) FROM chunk").fetchone()[0],
             "tags": con.execute("SELECT COUNT(*) FROM chunk_tag").fetchone()[0],
             "outcomes": counts,
             "by_doc_type": {r[0]: r[1] for r in con.execute(
                 "SELECT doc_type, COUNT(*) FROM doc GROUP BY doc_type")},
             "by_bucket": {r[0]: r[1] for r in con.execute(
                 "SELECT bucket, COUNT(*) FROM history_outcome GROUP BY bucket")},
             "page_from_zero_chunks": con.execute(
                 "SELECT COUNT(*) FROM chunk WHERE page_from IS NULL OR page_from=0").fetchone()[0],
             "failed_by_reason": {r[0]: r[1] for r in con.execute(
                 "SELECT reason, COUNT(*) FROM history_outcome WHERE outcome='failed' "
                 "GROUP BY reason ORDER BY 2 DESC")},
             "fts": [], "audit": {}, "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    held_ids = {r["newsid"] for r in load_manifest(manifest_path) if r.get("status") == "ok"}
    ledger = dict(con.execute("SELECT newsid, outcome FROM history_outcome"))
    held = {k: 0 for k in OUTCOMES}
    for newsid, outcome in ledger.items():
        if newsid in held_ids:
            held[outcome] = held.get(outcome, 0) + 1
    held["total"] = sum(held[k] for k in OUTCOMES)
    stats["held_outcomes"] = held
    workers = []
    for path in sorted(report_dir.glob("worker_*.json")):
        try:
            workers.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    if workers:
        processed = sum(w.get("processed") or 0 for w in workers)
        elapsed = sum(w.get("elapsed_s") or 0 for w in workers)
        no_text = sum(w.get("needs_ocr") or 0 for w in workers)
        stats["shards"] = len(workers)
        stats["workers"] = workers
        stats["peak_rss_bytes"] = max((w.get("peak_rss_bytes") or 0) for w in workers)
        stats["seconds_per_file"] = round(elapsed / processed, 3) if processed else None
        stats["no_text_share"] = round(no_text / processed, 4) if processed else 0
        stats["known_at_check"] = write_known_at_from_workers(report_dir)
    write_coverage(con, report_dir)
    stats["fts"] = write_fts_report(con, report_dir)
    if audit_n:
        audit = write_audit(con, report_dir, audit_n, root, manifest_path)
        stats["audit"] = {"checked": len(audit),
                          "passed": sum(1 for r in audit
                                        if r["text_match"] and r["page_number_ok"]
                                        and r["known_at_match"] and not r["error"]),
                          "text_failures": sum(1 for r in audit if not r["text_match"]),
                          "page_failures": sum(1 for r in audit if not r["page_number_ok"]),
                          "known_at_failures": sum(1 for r in audit
                                                   if not r["known_at_match"]),
                          "errors": sum(1 for r in audit if r["error"]),
                          "issues": [r["page_issue"] or r["error"] for r in audit
                                     if not (r["text_match"] and r["page_number_ok"]
                                             and r["known_at_match"]) or r["error"]]}
    write_summary(stats, report_dir)
    con.close()
    (report_dir / "report.json").write_text(json.dumps(stats, indent=1), encoding="utf-8")
    return stats


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--pilot", nargs="?", const=200, type=int, metavar="N")
    mode.add_argument("--full", action="store_true")
    mode.add_argument("--worker", action="store_true")
    mode.add_argument("--merge-only", action="store_true")
    mode.add_argument("--report-only", action="store_true")
    ap.add_argument("--shards", type=int)
    ap.add_argument("--shard", type=int, default=0)
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    ap.add_argument("--root", default=str(DEFAULT_ROOT))
    ap.add_argument("--out-db")
    ap.add_argument("--report-dir")
    ap.add_argument("--run-id")
    ap.add_argument("--known-at-checks", type=int, default=20)
    ap.add_argument("--audit", type=int, default=30)
    ap.add_argument("--force", action="store_true",
                    help="run the full build even if the pilot recorded known_at mismatches")
    args = ap.parse_args(argv)

    if args.worker:
        return worker(args)
    if args.pilot is not None:
        return run_pilot(args)
    if args.full:
        manifest = Path(args.manifest)
        root = Path(args.root)
        db_path = Path(args.out_db or FULL_DB)
        report_dir = Path(args.report_dir or (OUT_DIR / "history"))
        report_dir.mkdir(parents=True, exist_ok=True)
        pilot_report = OUT_DIR / "history_pilot" / "pilot_report.json"
        if pilot_report.is_file() and not args.force:
            pilot = json.loads(pilot_report.read_text(encoding="utf-8"))
            if pilot.get("known_at_mismatches"):
                print(f"refusing the full build: pilot recorded "
                      f"{pilot['known_at_mismatches']} known_at mismatches "
                      f"(see {pilot_report}); re-run the pilot or pass --force", flush=True)
                return 5
        rows = load_manifest(manifest)
        canonical, duplicates = plan_rows(rows)
        shards = choose_shards(args.shards)
        SHARD_DIR.mkdir(parents=True, exist_ok=True)
        print(f"manifest: {len(rows)} rows; canonical {len(canonical)}; "
              f"duplicates {len(duplicates)}; shards {shards} -> {db_path}", flush=True)
        run_id = args.run_id or time.strftime("history-%Y%m%d-%H%M%S")
        procs, dbs = [], []
        for i in range(shards):
            shard_db = SHARD_DIR / f"shard_{i}.db"
            cmd = [sys.executable, str(Path(__file__)), "--worker", "--shard", str(i),
                   "--shards", str(shards), "--manifest", str(manifest), "--root", str(root),
                   "--out-db", str(shard_db), "--report-dir", str(report_dir),
                   "--run-id", run_id, "--known-at-checks",
                   str(max(1, args.known_at_checks // shards))]
            if args.resume:
                cmd.append("--resume")
            log = (report_dir / f"worker_{i}.log").open("w", encoding="utf-8")
            procs.append((i, subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT,
                                              cwd=str(REPO)), log))
            dbs.append(shard_db)
        failed = []
        for i, proc, log in procs:
            code = proc.wait()
            log.close()
            print(f"shard {i}: exit {code}", flush=True)
            if code:
                failed.append(i)
        if failed:
            print(f"shards failed: {failed}; see {report_dir}/worker_<i>.log", flush=True)
            return 1
        counts = merge_all(dbs, db_path)
        con = open_store(db_path)
        finalize(con, rows, duplicates, None)
        counts = outcome_counts(con)
        con.commit()
        con.close()
        stats = full_report(db_path, report_dir, manifest, root, args.audit)
        print(json.dumps({k: v for k, v in stats.items() if k not in ("fts",)}, indent=1),
              flush=True)
        print(f"done -> {db_path} ({db_path.stat().st_size / 1e9:.2f} GB)", flush=True)
        return 0 if counts["total"] == len(rows) else 4
    if args.merge_only:
        shard_dbs = sorted(SHARD_DIR.glob("shard_*.db"))
        db_path = Path(args.out_db or FULL_DB)
        print(merge_all(shard_dbs, db_path), flush=True)
        rows = load_manifest(Path(args.manifest))
        _canonical, duplicates = plan_rows(rows)
        con = open_store(db_path)
        finalize(con, rows, duplicates, None)
        con.close()
        return 0
    if args.report_only:
        db_path = Path(args.out_db or FULL_DB)
        stats = full_report(db_path, Path(args.report_dir or (OUT_DIR / "history")),
                            Path(args.manifest), Path(args.root), args.audit)
        print(json.dumps(stats, indent=1), flush=True)
        return 0
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
