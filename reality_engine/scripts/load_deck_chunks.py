"""Load every real investor deck into ``chunks_v2.db``: Drive fetch, page text, production chunks.

The 26,387 ``ok`` rows of ``deck_figures.db:deck_sources`` are real investor
presentations (the ``INVESTOR_PRESENTATION`` rows in ``raw_documents`` are
mostly one-page cover letters), so search has never been able to read them.
This job downloads each PDF from the Drive ``decks`` folder, extracts the text
layer per page with PyMuPDF, and stores today's production deck chunking --
``DocumentParser.chunk_text`` (512-word windows, 64-word overlap, the "old"
chunker that beat ``chunker_v2`` on decks: R@1 .625 vs .550) -- with a
search header ``company · Investor presentation · title · date``.

One deliberate deviation: the concall section pruner is switched off. Production
``chunk_text`` runs it on every document, and on decks it deletes everything
before a stray "question and answer" heading (53.7% of KARNIKA's text in the
pilot set). The chrome for decks is the window size, not that pruner.

Phases (resumable; rerun any phase and it skips what is already done):

    python -m reality_engine.scripts.load_deck_chunks fetch --limit 0
    python -m reality_engine.scripts.load_deck_chunks parse --workers 7
    python -m reality_engine.scripts.load_deck_chunks stats

``fetch`` copies pilot PDFs already under ``D:\\RealityEngine\\raw\\deck_real_*``
(hard link, same volume) instead of downloading them again, batches 500 sha256
lookups through ``drive_fetch.fetch`` and keeps one JSONL line per miss.
``parse`` chunks and writes: one writer, commit every 500 decks, FTS built at
the end and rebuilt from scratch on every rerun.
"""
from __future__ import annotations

import argparse
import bisect
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path

from reality_engine.db.readonly import connect_ro

DATA_ROOT = Path(os.environ.get("REALITY_DATA_ROOT")
                 or r"C:\Users\warri\Downloads\Info_Diffusion_Model\reality_engine\data")
DECK_DB = DATA_ROOT / "deck_figures.db"
OUT_DB = DATA_ROOT / "chunks_v2.db"
RAW_ROOT = Path(r"D:\RealityEngine\raw")
DECKS_DIR = RAW_ROOT / "decks_full"
STAGING = DECKS_DIR / "_staging"
LOG_DIR = Path(".tmp/p2")
FETCH_LOG = LOG_DIR / "fetch_log.jsonl"
PARSE_LOG = LOG_DIR / "parse_errors.jsonl"

EMPTY_PAGE_CHARS = 40          # an image-only slide: OCR later, not a text chunk
CHUNK_TOKENS = 512             # DocumentParser defaults -- production settings
OVERLAP_TOKENS = 64
BATCH = 500
DOC_HEADER = "{company} · Investor presentation · {title} · {date}"


# ---------------------------------------------------------------------------
# Deck list and local copies
# ---------------------------------------------------------------------------
def load_decks(db: Path = DECK_DB) -> list[dict]:
    """One row per distinct sha256 from the ``ok`` deck sources, newest first."""
    con = connect_ro(db, timeout_s=120)
    rows = con.execute(
        "SELECT sha256, symbol, isin, known_at, title, local_path FROM deck_sources "
        "WHERE status='ok' AND sha256 IS NOT NULL AND length(sha256)=64 "
        "ORDER BY known_at DESC").fetchall()
    seen: dict[str, dict] = {}
    for sha, symbol, isin, known_at, title, local_path in rows:
        sha = sha.lower()
        if sha in seen:
            continue
        seen[sha] = {"sha256": sha, "symbol": symbol or "", "isin": isin or "",
                     "known_at": known_at or "", "title": (title or "").strip(),
                     "local_path": local_path or ""}
    return list(seen.values())


def local_copies(root: Path = RAW_ROOT) -> dict[str, Path]:
    """``sha -> pdf`` for decks already on disk under ``deck_real_*`` manifests."""
    found: dict[str, Path] = {}
    for manifest in sorted(root.glob("deck_real_*/manifest.json")):
        try:
            rows = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for row in rows:
            path, sha = row.get("path"), (row.get("sha256") or "").lower()
            if path and len(sha) == 64 and Path(path).exists():
                found.setdefault(sha, Path(path))
    return found


def deck_path(sha: str) -> Path:
    return DECKS_DIR / sha[:2] / f"{sha}.pdf"


def company_names(db: Path = DATA_ROOT / "equity_intelligence.db") -> dict[str, str]:
    con = connect_ro(db, timeout_s=120)
    return {isin: name for isin, name in con.execute(
        "SELECT isin, name FROM security_master WHERE name IS NOT NULL AND trim(name)<>''")}


# ---------------------------------------------------------------------------
# Phase 1 -- fetch
# ---------------------------------------------------------------------------
def _log(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")


def drive_shas(index_path: Path) -> dict[str, str]:
    """``sha256 -> archive path`` for everything in the Drive ``decks`` folder."""
    from reality_engine.toolbelt import drive_fetch

    index = drive_fetch.load_index(index_path, drive_fetch.DEFAULT_REMOTE)
    listing = drive_fetch.index_folder(index, "decks", timeout=1800)
    drive_fetch.save_index(index_path, index)
    return {str(entry.get("sha256") or "").lower(): rel
            for rel, entry in listing["files"].items() if entry.get("sha256")}


def bulk_folders(decks: list[dict], on_drive: dict[str, str]) -> dict[str, list[dict]]:
    """``Drive folder -> decks`` for every sha still missing on disk."""
    groups: dict[str, list[dict]] = {}
    for deck in decks:
        rel = on_drive.get(deck["sha256"])
        if rel and not deck_path(deck["sha256"]).exists():
            groups.setdefault(rel.rsplit("/", 1)[0], []).append(deck)
    return groups


def fetch_folders(groups: dict[str, list[dict]], on_drive: dict[str, str], *,
                  root: Path = RAW_ROOT, index_path: Path | None = None,
                  transfers: int = 16, limit_folders: int = 0,
                  timeout: float = 3600.0) -> dict:
    """Bulk-download whole Drive folders, one rclone copy each, then rename by sha256.

    ``drive_fetch.fetch`` spawns one ``rclone copyto`` per file, and each of those
    re-resolves the source path with Drive list calls: measured 1.0 MB/s and 30 h
    for the corpus.  One ``rclone copy`` per folder lists the folder once and
    streams the rest: 5.6 MB/s, ~5 h.  Same rclone binary, config and remote as
    ``drive_fetch`` (``_rclone``/``_run``), so Drive stays the only network.
    """
    from reality_engine.toolbelt import drive_fetch

    by_rel = {rel: sha for sha, rel in on_drive.items()}
    folders = sorted(groups, key=lambda f: -len(groups[f]))
    if limit_folders:
        folders = folders[:limit_folders]
    stats = {"folders": len(folders), "decks": 0, "ok": 0, "sha_mismatch": 0,
             "not_downloaded": 0, "bytes": 0}
    t0 = time.time()
    for number, folder in enumerate(folders, start=1):
        staging = STAGING / folder.replace("/", "__")
        staging.mkdir(parents=True, exist_ok=True)
        target = f"{drive_fetch.DEFAULT_REMOTE}/{folder}"
        proc = drive_fetch._run([*drive_fetch._rclone(None), "copy", target, str(staging),
                                 "--transfers", str(transfers), "--stats", "0"],
                                timeout)
        error = drive_fetch._clean_stderr(proc.stderr)
        if proc.returncode != 0:
            _log(FETCH_LOG, {"folder": folder, "status": "folder_error",
                             "reason": error[-400:]})
        for path in staging.glob("*.pdf"):
            rel = f"{folder}/{path.name}"
            sha = by_rel.get(rel, "")
            stats["decks"] += 1
            if not sha:
                stats["not_downloaded"] += 1
                _log(FETCH_LOG, {"file": rel, "status": "unmatched",
                                 "reason": "no deck_sources sha256 for this Drive path"})
                continue
            size = path.stat().st_size
            if _sha256(path) != sha:
                stats["sha_mismatch"] += 1
                _log(FETCH_LOG, {"sha256": sha, "file": rel, "status": "sha_mismatch",
                                 "reason": "downloaded bytes do not match deck_sources sha256"})
                path.unlink()
                continue
            out = deck_path(sha)
            out.parent.mkdir(parents=True, exist_ok=True)
            os.replace(path, out)
            stats["ok"] += 1
            stats["bytes"] += size
        shutil.rmtree(staging, ignore_errors=True)
        if number % 20 == 0 or number == len(folders):
            elapsed = time.time() - t0
            print(f"[bulk] folders {number}/{len(folders)} decks {stats['ok']} "
                  f"{stats['bytes'] / elapsed / 1e6:.2f} MB/s "
                  f"{stats['ok'] / elapsed:.2f} decks/s {elapsed / 60:.1f} min", flush=True)
    for deck in decks_iter(groups):
        if not deck_path(deck["sha256"]).exists():
            stats["not_downloaded"] += 1
            _log(FETCH_LOG, {"sha256": deck["sha256"], "symbol": deck["symbol"],
                             "status": "not_downloaded", "reason": "rclone copy did not land it"})
    stats["seconds"] = round(time.time() - t0, 1)
    return stats


def decks_iter(groups: dict[str, list[dict]]):
    for decks in groups.values():
        yield from decks


def migrate_tree(tree: Path = DECKS_DIR / "_tree", index_path: Path | None = None,
                 dest: Path = DECKS_DIR, known: set[str] | None = None) -> dict:
    """Rename finished files of the bulk ``rclone copy`` tree into ``<sha[:2]>/<sha>.pdf``.

    ``rclone copy`` keeps the Drive tree; this moves every completed PDF to the
    sha256 layout the loader reads.  ``*.partial`` files are still being written
    and are left alone, so the mover can run while the copy is in flight.
    """
    from reality_engine.toolbelt.drive_fetch import DEFAULT_INDEX, DEFAULT_REMOTE, load_index

    if not tree.exists():
        return {"files": 0, "moved": 0, "known": 0, "unmatched": 0}
    listing = load_index(index_path or Path(DEFAULT_INDEX), DEFAULT_REMOTE)
    by_rel = {rel: (str(entry.get("sha256") or "").lower(), entry.get("size"))
              for rel, entry in listing["folders"].get("decks", {}).get("files", {}).items()}
    stats = {"files": 0, "moved": 0, "known": 0, "unmatched": 0, "mismatch": 0}
    for folder, _dirs, names in os.walk(tree):
        for name in names:
            if name.endswith(".partial"):
                continue
            path = Path(folder) / name
            rel = "decks/" + path.relative_to(tree).as_posix()
            entry = by_rel.get(rel)
            sha = entry[0] if entry else ""
            size = path.stat().st_size
            stats["files"] += 1
            if not sha and known:
                digest = _sha256(path)
                sha = digest if digest in known else ""
            if not sha:
                stats["unmatched"] += 1
                _log(FETCH_LOG, {"file": rel, "status": "unmatched",
                                 "reason": "no deck_sources sha256 for this Drive path"})
                path.unlink()
                continue
            stats["known"] += 1
            target = dest / sha[:2] / f"{sha}.pdf"
            if target.exists():
                path.unlink()                          # already have it
                continue
            # The Drive listing already carries the sha256 and the byte size; the
            # full hash is only worth reading when the size disagrees (it does not
            # scale to 117 GB of decks while the download is still writing).
            if entry and entry[1] is not None and int(entry[1]) != size and _sha256(path) != sha:
                stats["mismatch"] += 1
                _log(FETCH_LOG, {"sha256": sha, "file": rel, "status": "sha_mismatch",
                                 "reason": "downloaded bytes do not match deck_sources sha256"})
                path.unlink()
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(path, target)
            stats["moved"] += 1
    return stats


def topup(decks: list[dict], *, transfers: int = 8) -> dict:
    """Fetch by Drive *path* the decks the folder copy could not map by sha256.

    A file uploaded to the archive after the last index listing has no sha256 in
    the index, so the tree mover cannot name it.  The deck's own ``local_path``
    still maps to its archive path; download it, then move it by content hash.
    """
    from reality_engine.toolbelt.drive_fetch import DEFAULT_INDEX, fetch, local_to_remote

    missing = [d for d in decks if not deck_path(d["sha256"]).exists()]
    rels = []
    for deck in missing:
        try:
            rels.append(local_to_remote(deck["local_path"]))
        except ValueError:
            continue
    stats = {"missing": len(missing), "requested": len(rels), "moved": 0, "fetch": {}}
    if not rels:
        return stats
    STAGING.mkdir(parents=True, exist_ok=True)
    result = fetch(rels, dest=STAGING, folder="decks", verify=True, transfers=transfers)
    for item in result["items"]:
        stats["fetch"][item["status"]] = stats["fetch"].get(item["status"], 0) + 1
        if item["status"] != "ok":
            _log(FETCH_LOG, {"file": item.get("remote_path", ""), "sha256": "",
                             "status": item["status"],
                             "reason": item.get("reason", "top-up fetch failed")})
    stats["moved"] = _recover_staging(drive_shas(Path(DEFAULT_INDEX)),
                                     {d["sha256"] for d in decks})
    return stats


def watch(out: Path = OUT_DB, *, workers: int = 7, interval: float = 240.0,
          max_rounds: int = 0, done_flag: Path = DECKS_DIR / "_tree.done") -> dict:
    """Move downloaded decks into place and load them, until the tree copy is done."""
    rounds = 0
    total = {"moved": 0, "ok": 0, "chunks": 0}
    decks = load_decks()
    known = {d["sha256"] for d in decks}
    while True:
        rounds += 1
        try:
            moved = migrate_tree(known=known)
            result = load_phase(decks, workers=workers, out=out)
            total["moved"] += moved["moved"]
            total["ok"] += result["ok"]
            total["chunks"] += result["chunks"]
            print(f"[watch] round {rounds} moved={moved['moved']} parsed={result['parsed']} "
                  f"ok={result['ok']} chunks={result['chunks']} total_ok={total['ok']}",
                  flush=True)
            notes = Path(".tmp/PROGRESS_NOTES.md")
            if notes.parent.exists():
                with notes.open("a", encoding="utf-8") as handle:
                    handle.write(f"- 2026 P2 watch round {rounds}: moved={moved['moved']} "
                                 f"parsed={result['parsed']} chunks={result['chunks']} "
                                 f"total_ok={total['ok']}\n")
            if done_flag.exists() and moved["files"] == 0:
                print("[watch] tree copy finished and empty; stopping", flush=True)
                break
        except Exception as exc:  # noqa: BLE001 - keep watching through a bad round
            print(f"[watch] round {rounds} failed: {type(exc).__name__}: {exc}", flush=True)
        if max_rounds and rounds >= max_rounds:
            break
        time.sleep(interval)
    return total


def _sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(4 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _recover_staging(on_drive: dict[str, str], known: set[str] | None = None) -> int:
    """Move any PDF left loose in staging to its sha256 path (an interrupted run).

    The Drive file name is matched against the index first; when the index is
    stale (a file uploaded after the listing) the file's own sha256 is checked
    against ``known`` instead.
    """
    if not STAGING.exists():
        return 0
    by_name = {rel.rsplit("/", 1)[-1]: sha for sha, rel in on_drive.items()}
    moved = 0
    for path in STAGING.glob("*.pdf"):
        sha = by_name.get(path.name)
        if sha is None and known:
            digest = _sha256(path)
            sha = digest if digest in known else None
        if sha and not deck_path(sha).exists() and _sha256(path) == sha:
            out = deck_path(sha)
            out.parent.mkdir(parents=True, exist_ok=True)
            os.replace(path, out)
            moved += 1
        else:
            path.unlink()
    return moved


def fetch_phase(decks: list[dict], *, batch: int = BATCH, transfers: int = 8,
                limit: int = 0, root: Path = RAW_ROOT, index_path: Path | None = None,
                check_sha: bool = True, bulk: bool = True,
                limit_folders: int = 0) -> dict:
    """Download every missing deck into ``<sha[:2]>/<sha>.pdf``; resumable."""
    from reality_engine.toolbelt.drive_fetch import DEFAULT_INDEX, fetch

    stats = {"sourced": len(decks), "already_present": 0, "local_link": 0,
             "downloaded": 0, "not_on_drive": 0, "fetch": {}}
    have = local_copies(root)
    on_drive = drive_shas(index_path or Path(DEFAULT_INDEX))
    stats["drive_files"] = len(on_drive)
    stats["staging_recovered"] = _recover_staging(on_drive)
    wanted = []
    for deck in decks:
        sha = deck["sha256"]
        if deck_path(sha).exists():
            stats["already_present"] += 1
            continue
        if limit and len(wanted) >= limit:
            break
        src = have.get(sha)
        if src is not None:
            target = deck_path(sha)
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.link(src, target)                   # same volume: no copy
            except OSError:
                shutil.copyfile(src, target)
            stats["local_link"] += 1
        elif sha in on_drive:
            wanted.append(deck)
        else:
            stats["not_on_drive"] += 1
            _log(FETCH_LOG, {"sha256": sha, "symbol": deck["symbol"],
                             "status": "missing", "reason": "not in Drive decks folder"})

    if bulk and wanted:
        groups = bulk_folders(wanted, on_drive)
        stats["bulk"] = fetch_folders(groups, on_drive, transfers=max(16, transfers),
                                      limit_folders=limit_folders)
        stats["downloaded"] += stats["bulk"]["ok"]
        wanted = [d for d in wanted if not deck_path(d["sha256"]).exists()]

    t0 = time.time()
    for start in range(0, len(wanted), batch):
        chunk = wanted[start:start + batch]
        STAGING.mkdir(parents=True, exist_ok=True)
        paths = [on_drive[d["sha256"]] for d in chunk]
        result = fetch(paths, dest=STAGING, folder="decks", verify=True,
                       transfers=transfers)
        by_sha = {d["sha256"]: d for d in chunk}
        for item in result["items"]:
            sha = next((s for s, p in zip(by_sha, paths) if p == item["remote_path"]), "")
            status = item["status"]
            stats["fetch"][status] = stats["fetch"].get(status, 0) + 1
            target = deck_path(sha) if sha else None
            if status == "ok" and target is not None and check_sha:
                got = _sha256(Path(item["dest"]))
                if got != sha:
                    status = "sha_mismatch"
                    stats["fetch"][status] = stats["fetch"].get(status, 0) + 1
            if status == "ok" and target is not None:
                target.parent.mkdir(parents=True, exist_ok=True)
                os.replace(item["dest"], target)
                stats["downloaded"] += 1
            else:
                if item.get("dest") and Path(item["dest"]).exists():
                    os.unlink(item["dest"])
                _log(FETCH_LOG, {"sha256": sha, "symbol": by_sha.get(sha, {}).get("symbol", ""),
                                 "status": status, "reason": item.get("reason", "")})
        elapsed = time.time() - t0
        print(f"[fetch] {start + len(chunk)}/{len(wanted)} this run: "
              f"{stats['downloaded'] / elapsed:.2f} decks/s {stats['fetch']}",
              flush=True)
    stats["seconds"] = round(time.time() - t0, 1)
    stats["decks_per_second"] = round(stats["downloaded"] / max(1e-9, stats["seconds"]), 3)
    return stats


# ---------------------------------------------------------------------------
# Phase 2 -- page text and chunks
# ---------------------------------------------------------------------------
def normalise_pages(pages: list[str]) -> tuple[str, list[int], list[int]]:
    """Collapsed deck text, the page number of each text block, and its end offset.

    Whitespace is collapsed exactly the way ``DocumentParser.chunk_text`` does,
    so a chunk body is a literal substring of the returned text and can be
    mapped back to pages. Pages under ``EMPTY_PAGE_CHARS`` carry no text layer
    (image-only slide) and are left out of the text.
    """
    parts: list[str] = []
    numbers: list[int] = []
    ends: list[int] = []
    offset = 0
    for number, text in enumerate(pages, start=1):
        # NULs come out of some text layers; SQLite's length() stops at one and the
        # FTS tokenizer drops the tail, so a chunk would silently lose its ending.
        body = re.sub(r"\s+", " ", (text or "").replace("\x00", " ")).strip()
        if len(body) < EMPTY_PAGE_CHARS:
            continue
        if parts:
            offset += 1
        numbers.append(number)
        parts.append(body)
        offset += len(body)
        ends.append(offset)
    return " ".join(parts), numbers, ends


def _no_prune(text: str) -> str:                       # decks are not concalls
    return text


def chunk_deck(pages: list[str], header: str) -> list[dict]:
    """Production ``DocumentParser`` windows over the deck, mapped back to pages."""
    from reality_engine.processing.document_parser import DocumentParser

    text, numbers, ends = normalise_pages(pages)
    if not text:
        return []
    parser = DocumentParser(chunk_tokens=CHUNK_TOKENS, overlap_tokens=OVERLAP_TOKENS)
    parser.pruner = type("_NoPrune", (), {"prune": staticmethod(_no_prune)})()
    chunks: list[dict] = []
    cursor = 0
    for index, chunk in enumerate(parser.chunk_text(text, {"doc_type": "INVESTOR_PRESENTATION"})):
        body = chunk.embed_text
        pos = text.find(body, cursor)
        if pos < 0:
            pos = text.find(body)
        if pos < 0:                                    # tokenizer rewrote the slice
            pos, end = cursor, min(len(text), cursor + len(body))
        else:
            end = pos + len(body)
            cursor = pos
        first = bisect.bisect_right(ends, pos)
        last = bisect.bisect_left(ends, end - 1) if end > pos else first
        chunks.append({
            "chunk_index": index,
            "page_from": numbers[min(first, len(numbers) - 1)],
            "page_to": numbers[min(last, len(numbers) - 1)],
            "header": header,
            "body": body,
            "char_len": len(header) + len(body),
        })
    return chunks


def parse_deck(path: str, meta: dict) -> dict:
    """Worker: page texts for one PDF -> chunk rows (or a status with the reason)."""
    import fitz  # PyMuPDF

    out = {"sha256": meta["sha256"], "symbol": meta.get("symbol", ""),
           "isin": meta.get("isin", ""), "known_at": meta.get("known_at", ""),
           "title": meta.get("title", ""), "pages": 0, "empty_pages": 0,
           "status": "ok", "chunks": []}
    try:
        with fitz.open(path) as pdf:
            pages = [page.get_text("text") for page in pdf]
    except Exception as exc:  # noqa: BLE001 - a bad PDF must not stop 26k decks
        out["status"] = f"error:{type(exc).__name__}"
        out["error"] = str(exc)[:200]
        return out
    out["pages"] = len(pages)
    out["empty_pages"] = sum(1 for text in pages if len((text or "").strip()) < EMPTY_PAGE_CHARS)
    header = DOC_HEADER.format(company=meta.get("company") or meta.get("symbol") or "",
                               title=meta.get("title") or "Investor presentation",
                               date=(meta.get("known_at") or "")[:10])
    out["chunks"] = chunk_deck(pages, header)
    if not out["chunks"]:
        out["status"] = "no_text"
    return out


# ---------------------------------------------------------------------------
# Phase 3 -- write
# ---------------------------------------------------------------------------
SCHEMA = """
CREATE TABLE IF NOT EXISTS deck_docs (
  sha256 TEXT PRIMARY KEY, symbol TEXT, isin TEXT, known_at TEXT, title TEXT,
  pages INTEGER, empty_pages INTEGER, status TEXT);
CREATE TABLE IF NOT EXISTS deck_chunks (
  chunk_id INTEGER PRIMARY KEY, sha256 TEXT NOT NULL, symbol TEXT, isin TEXT,
  known_at TEXT, title TEXT, page_from INTEGER, page_to INTEGER,
  header TEXT, body TEXT, char_len INTEGER);
CREATE INDEX IF NOT EXISTS ix_deck_chunks_sha ON deck_chunks(sha256);
CREATE INDEX IF NOT EXISTS ix_deck_chunks_known ON deck_chunks(known_at);
CREATE VIRTUAL TABLE IF NOT EXISTS deck_chunks_fts USING fts5(
  header, body, content='deck_chunks', content_rowid='chunk_id');
"""


def open_out(db: Path = OUT_DB):
    import sqlite3

    db.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    con.executescript(SCHEMA)
    con.commit()
    return con


def done_shas(con) -> set[str]:
    return {row[0] for row in con.execute("SELECT sha256 FROM deck_docs WHERE status='ok'")}


def write_doc(con, doc: dict) -> int:
    con.execute("INSERT OR REPLACE INTO deck_docs VALUES (?,?,?,?,?,?,?,?)",
                (doc["sha256"], doc["symbol"], doc["isin"], doc["known_at"], doc["title"],
                 doc["pages"], doc["empty_pages"], doc["status"]))
    con.execute("DELETE FROM deck_chunks WHERE sha256=?", (doc["sha256"],))
    rows = [(doc["sha256"], doc["symbol"], doc["isin"], doc["known_at"], doc["title"],
             c["page_from"], c["page_to"], c["header"], c["body"], c["char_len"])
            for c in doc["chunks"]]
    con.executemany("INSERT INTO deck_chunks (sha256, symbol, isin, known_at, title, "
                    "page_from, page_to, header, body, char_len) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    rows)
    return len(rows)


def load_phase(decks: list[dict], *, workers: int = 7, out: Path = OUT_DB,
               limit: int = 0) -> dict:
    """Parse every deck not yet loaded and write it; one writer, batch commits."""
    import multiprocessing as mp

    names = company_names()
    wanted = [d for d in decks if deck_path(d["sha256"]).exists()]
    con = open_out(out)
    done = done_shas(con)
    queue = [dict(d, company=names.get(d["isin"], "")) for d in wanted
             if d["sha256"] not in done]
    if limit:
        queue = queue[:limit]
    print(f"[load] {len(wanted)} on disk, {len(done)} already loaded, {len(queue)} to parse",
          flush=True)
    stats = {"parsed": 0, "ok": 0, "no_text": 0, "error": 0, "chunks": 0,
             "pages": 0, "empty_pages": 0}
    started = time.time()
    if queue:
        with mp.Pool(max(1, int(workers))) as pool:
            pending = 0
            for doc in pool.imap_unordered(_parse_one, queue, chunksize=4):
                stats["parsed"] += 1
                stats["pages"] += doc["pages"]
                stats["empty_pages"] += doc["empty_pages"]
                if doc["status"] == "ok":
                    stats["ok"] += 1
                    stats["chunks"] += write_doc(con, doc)
                elif doc["status"] == "no_text":
                    stats["no_text"] += 1
                    write_doc(con, doc)
                else:
                    stats["error"] += 1
                    write_doc(con, doc)
                    _log(PARSE_LOG, {k: doc[k] for k in
                                     ("sha256", "symbol", "status", "pages") if k in doc})
                pending += 1
                if pending % BATCH == 0:
                    con.commit()
                    elapsed = time.time() - started
                    print(f"[load] {stats['parsed']}/{len(queue)} docs "
                          f"{stats['pages'] / elapsed:.0f} pages/s "
                          f"{stats['parsed'] / elapsed:.1f} decks/s", flush=True)
            con.commit()
    stats["fts"] = rebuild_fts(con) if stats["chunks"] else 0
    stats["seconds"] = round(time.time() - started, 1)
    con.close()
    return stats


def _parse_one(deck: dict) -> dict:
    return parse_deck(str(deck_path(deck["sha256"])), deck)


def rebuild_fts(con) -> int:
    con.execute("INSERT INTO deck_chunks_fts(deck_chunks_fts) VALUES('rebuild')")
    con.commit()
    return con.execute("SELECT count(*) FROM deck_chunks_fts").fetchone()[0]


# ---------------------------------------------------------------------------
# Phase 4 -- report
# ---------------------------------------------------------------------------
def _percentile(sorted_values: list[int], q: float) -> int:
    if not sorted_values:
        return 0
    return sorted_values[min(len(sorted_values) - 1, int(q * len(sorted_values)))]


def stats(out: Path = OUT_DB) -> dict:
    import sqlite3

    con = sqlite3.connect(f"file:{out}?mode=ro", uri=True)
    try:
        lens = [row[0] for row in con.execute("SELECT char_len FROM deck_chunks ORDER BY char_len")]
        docs = con.execute("SELECT count(*), sum(pages), sum(empty_pages) FROM deck_docs").fetchone()
        by_status = dict(con.execute("SELECT status, count(*) FROM deck_docs GROUP BY status"))
    finally:
        con.close()
    chunks = len(lens)
    return {
        "decks": docs[0] or 0, "pages": docs[1] or 0, "empty_pages": docs[2] or 0,
        "empty_page_share": round((docs[2] or 0) / docs[1], 4) if docs[1] else 0.0,
        "chunks": chunks,
        "chunks_per_deck": round(chunks / docs[0], 2) if docs[0] else 0.0,
        "p10": _percentile(lens, 0.10), "p50": _percentile(lens, 0.50),
        "p90": _percentile(lens, 0.90),
        "chars": sum(lens), "tokens_est": sum(lens) // 4,
        "status": by_status,
    }


def coverage(decks: list[dict], out: Path = OUT_DB) -> list[dict]:
    """Per filing year: sourced vs on disk vs chunked."""
    import sqlite3

    by_year: dict[str, dict] = {}
    for deck in decks:
        year = (deck["known_at"] or "")[:4]
        row = by_year.setdefault(year, {"year": year, "sources": 0, "on_disk": 0, "chunked": 0})
        row["sources"] += 1
        row["on_disk"] += int(deck_path(deck["sha256"]).exists())
    if out.exists():
        con = sqlite3.connect(f"file:{out}?mode=ro", uri=True)
        for year, count in con.execute(
                "SELECT substr(known_at,1,4), count(*) FROM deck_docs WHERE status='ok' "
                "AND sha256 IN (SELECT DISTINCT sha256 FROM deck_chunks) GROUP BY 1"):
            if year in by_year:
                by_year[year]["chunked"] = count
    return [by_year[y] for y in sorted(by_year)]


def sample_chunks(n: int = 10, out: Path = OUT_DB) -> list[dict]:
    import sqlite3

    con = sqlite3.connect(f"file:{out}?mode=ro", uri=True)
    rows = con.execute(
        "SELECT chunk_id, symbol, page_from, page_to, header, substr(body,1,320) "
        "FROM deck_chunks ORDER BY random() LIMIT ?", (n,)).fetchall()
    return [dict(zip(("chunk_id", "symbol", "page_from", "page_to", "header", "body"), r))
            for r in rows]


def verify(out: Path = OUT_DB) -> dict:
    """Structural invariants of the store; ``ok`` is False (never silent) on any break."""
    import sqlite3

    con = sqlite3.connect(f"file:{out}?mode=ro", uri=True, timeout=60)
    try:
        checks = {}
        checks["bad_chunk_rows"] = con.execute(
            "SELECT count(*) FROM deck_chunks WHERE char_len <> length(header)+length(body) "
            "OR length(body)=0 OR page_from<1 OR page_to<page_from").fetchone()[0]
        checks["pages_out_of_range"] = con.execute(
            "SELECT count(*) FROM deck_chunks c JOIN deck_docs d ON d.sha256=c.sha256 "
            "WHERE c.page_to > d.pages OR c.page_from > d.pages").fetchone()[0]
        checks["ok_docs_without_chunks"] = con.execute(
            "SELECT count(*) FROM deck_docs d WHERE d.status='ok' AND NOT EXISTS "
            "(SELECT 1 FROM deck_chunks c WHERE c.sha256=d.sha256)").fetchone()[0]
        checks["header_missing_label"] = con.execute(
            "SELECT count(*) FROM deck_chunks WHERE header NOT LIKE '%Investor presentation%'"
        ).fetchone()[0]
        checks["duplicate_chunks"] = con.execute(
            "SELECT count(*) FROM (SELECT sha256, page_from, page_to, body FROM deck_chunks "
            "GROUP BY 1,2,3,4 HAVING count(*)>1)").fetchone()[0]
        chunks = con.execute("SELECT count(*) FROM deck_chunks").fetchone()[0]
        checks["fts_rows"] = con.execute("SELECT count(*) FROM deck_chunks_fts").fetchone()[0]
        checks["fts_matches_chunks"] = checks["fts_rows"] == chunks
        checks["chunks"] = chunks
    finally:
        con.close()
    must_be_zero = ("bad_chunk_rows", "pages_out_of_range", "ok_docs_without_chunks",
                    "header_missing_label", "duplicate_chunks")
    failed = [name for name in must_be_zero if checks[name]]
    if not checks["fts_matches_chunks"]:
        failed.append("fts_matches_chunks")
    return {"ok": not failed, "failed": failed, **checks}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m reality_engine.scripts.load_deck_chunks")
    ap.add_argument("phase", choices=["fetch", "topup", "load", "watch", "migrate", "stats",
                                      "coverage", "sample", "verify"])
    ap.add_argument("--db", default=str(OUT_DB))
    ap.add_argument("--batch", type=int, default=BATCH)
    ap.add_argument("--transfers", type=int, default=16)
    ap.add_argument("--workers", type=int, default=7)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--limit-folders", type=int, default=0)
    ap.add_argument("--interval", type=float, default=240.0)
    ap.add_argument("--rounds", type=int, default=0)
    ap.add_argument("--no-bulk", action="store_true", help="per-file drive_fetch instead of folder copies")
    args = ap.parse_args(argv)
    decks = load_decks()
    if args.phase == "fetch":
        result = fetch_phase(decks, batch=args.batch, transfers=args.transfers,
                             limit=args.limit, bulk=not args.no_bulk,
                             limit_folders=args.limit_folders)
    elif args.phase == "topup":
        result = topup(decks, transfers=args.transfers)
    elif args.phase == "load":
        result = load_phase(decks, workers=args.workers, out=Path(args.db), limit=args.limit)
    elif args.phase == "watch":
        result = watch(Path(args.db), workers=args.workers, interval=args.interval,
                       max_rounds=args.rounds)
    elif args.phase == "migrate":
        result = migrate_tree()
    elif args.phase == "coverage":
        result = coverage(decks, Path(args.db))
    elif args.phase == "sample":
        result = sample_chunks(args.limit or 10, Path(args.db))
    elif args.phase == "verify":
        result = verify(Path(args.db))
    else:
        result = stats(Path(args.db))
    print(json.dumps(result, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
