"""Where every held document is: local disk, the Drive archive, or nowhere (Shivam, 7 Nov 2026).

Reads the ``corporate_documents`` rows of the main store and a full listing of the Drive archive
(``rclone lsjson -R --files-only --hash`` of each document folder, saved as ``listing_<folder>.json`` in
``--listing-dir``), and writes one row per document (``corporate_documents``, ``raw_documents``, ``deck_figures.db:deck_sources``,
``results_notes.db:docs``) to ``doc_location``, and every
Drive file that no row points to in ``drive_unlinked``, in ``--out`` (a small SQLite file, never
the main store):

    disk_path   the stored path, or a sha-named file in the raw store, exists on this machine
    drive_path  the archive holds it: by the stored path, by the same ``_<hash8>_<rest>`` name with a drifted
                crawl-date prefix, or by a sha256-named file (``results_pdfs``)
    location_kind  disk+drive, disk, drive, not_held (searched, none found) or not_held_no_file_ref (the row
                has neither a path nor a hash: a link that was never downloaded)

Listing only, never a download. Run:

    rclone lsjson -R --files-only --hash --fast-list gdrive:InfoDiffusion_archive/<folder> > listing_<folder>.json
    python -m reality_engine.scripts.doc_locations --listing-dir D:/RealityEngine/drive_index \
        --out D:/RealityEngine/drive_index/doc_locations.db
"""
from __future__ import annotations

import argparse
import json
import os
import posixpath
import re
import sqlite3
import sys
import time
from collections import Counter
from pathlib import Path

from reality_engine.config import DB_PATH, resolve_stored_path
from reality_engine.toolbelt.drive_fetch import local_to_remote, suffix_of

_SHA = re.compile(r"[0-9a-f]{64}")


def load_listing(listing_dir: Path) -> tuple[dict[str, dict], dict[tuple[str, str], str], dict[str, str]]:
    """``(path -> entry, (folder, suffix) -> path, sha256 -> path)`` over every ``listing_<folder>.json``."""
    files: dict[str, dict] = {}
    by_suffix: dict[tuple[str, str], str] = {}
    by_sha: dict[str, str] = {}
    for f in sorted(listing_dir.glob("listing_*.json")):
        top = f.stem[len("listing_"):]
        for item in json.loads(f.read_text(encoding="utf-8")):
            rel = f"{top}/{item['Path']}"
            files[rel.lower()] = {"path": rel, "size": item.get("Size")}
            sfx = suffix_of(rel)
            if sfx:
                key = (posixpath.dirname(rel).lower(), sfx.lower())
                if key not in by_suffix or rel > by_suffix[key]:
                    by_suffix[key] = rel
            stem = posixpath.basename(rel)[:-4].lower() if rel.lower().endswith(".pdf") else ""
            if _SHA.fullmatch(stem):
                by_sha.setdefault(stem, rel)
    return files, by_suffix, by_sha


DISK_PDF_ROOTS = (Path(r"D:/RealityEngine/pdfs"), Path(r"D:/RealityEngine/remaining_pdfs"))


def disk_suffix_index(roots=DISK_PDF_ROOTS) -> dict[tuple[str, str], str]:
    """``(SYM/TYPE, _<hash8>_<rest>) -> path`` over the dated-name PDF folders (names only, no reads)."""
    out: dict[tuple[str, str], str] = {}
    for root in roots:
        if not root.is_dir():
            continue
        for dirpath, _dirs, names in os.walk(root):
            folder = Path(dirpath).relative_to(root).as_posix().lower()
            for name in names:
                sfx = suffix_of(name)
                if sfx:
                    key = (folder, sfx.lower())
                    path = str(Path(dirpath) / name)
                    if key not in out or path > out[key]:
                        out[key] = path
    return out


def find_disk(stored: str | None, sha: str, disk_sha: dict, disk_suffix: dict | None = None) -> str | None:
    if stored:
        p = resolve_stored_path(stored)
        if p.exists():
            return str(p)
    if sha and sha in disk_sha:
        return str(disk_sha[sha])
    if stored and disk_suffix:
        try:
            rel = local_to_remote(stored)
        except ValueError:
            rel = None
        sfx = suffix_of(rel) if rel else None
        if sfx:
            folder = posixpath.dirname(rel).split("/", 1)[-1].lower()
            return disk_suffix.get((folder, sfx.lower()))
    return None


def find_drive(stored: str | None, sha: str, files: dict, by_suffix: dict, by_sha: dict) -> tuple[str | None, str]:
    if stored:
        try:
            rel = local_to_remote(stored)
        except ValueError:
            rel = None
        if rel:
            hit = files.get(rel.lower())
            if hit:
                return hit["path"], "stored_path"
            sfx = suffix_of(rel)
            if sfx:
                alt = by_suffix.get((posixpath.dirname(rel).lower(), sfx.lower()))
                if alt:
                    return alt, "hash_suffix"
    if sha and sha in by_sha:
        return by_sha[sha], "sha_name"
    return None, ""


def locate(stored: str | None, sha: str | None, disk_sha: dict, files: dict, by_suffix: dict,
           by_sha: dict, disk_suffix: dict | None = None) -> tuple[str, str | None, str | None, str]:
    """``(kind, disk_path, drive_path, drive_matched_by)``; kind is disk+drive, disk, drive or not_held."""
    sha = (sha or "").strip().lower()
    disk = find_disk(stored, sha, disk_sha, disk_suffix)
    drive, how = find_drive(stored, sha, files, by_suffix, by_sha)
    if disk and drive:
        kind = "disk+drive"
    elif disk or drive:
        kind = "disk" if disk else "drive"
    else:
        kind = "not_held" if (stored or sha) else "not_held_no_file_ref"
    return kind, disk, drive, how


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", default=str(DB_PATH))
    ap.add_argument("--listing-dir", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--no-disk-sha", action="store_true", help="skip the raw-store sha walk")
    a = ap.parse_args(argv)

    t = time.time()
    files, by_suffix, by_sha = load_listing(Path(a.listing_dir))
    disk_sha: dict = {}
    if not a.no_disk_sha:
        from reality_engine.pilot3.doc_identity import sha_index
        disk_sha = sha_index()
    disk_suffix = {} if a.no_disk_sha else disk_suffix_index()
    print(f"drive files {len(files)}, sha-named {len(by_sha)}; disk sha files {len(disk_sha)}, "
          f"dated-name disk files {len(disk_suffix)} "
          f"({time.time() - t:.0f} s)", flush=True)

    src = sqlite3.connect(f"file:{a.db}?mode=ro", uri=True)
    rows = [("corporate_documents",) + r for r in src.execute(
        "SELECT id, symbol, doc_type, doc_date, local_file_path, sha256_hash FROM corporate_documents")]
    rows += [("raw_documents",) + r for r in src.execute(
        "SELECT doc_id, symbol, source_type, published_date, local_file_path, sha256_hash FROM raw_documents")]
    data = Path(a.db).parent
    for name, table, sql in (
            ("deck_figures.db", "deck_sources",
             "SELECT rowid, symbol, 'INVESTOR_PRESENTATION', substr(known_at, 1, 10), local_path, sha256 "
             "FROM deck_sources WHERE status = 'ok'"),
            ("results_notes.db", "results_notes_docs",
             "SELECT rowid, symbol, 'FINANCIAL_RESULT', substr(known_at, 1, 10), NULL, sha256 FROM docs "
             "WHERE sha256 IS NOT NULL")):
        if (data / name).exists():
            other = sqlite3.connect(f"file:{data / name}?mode=ro", uri=True)
            rows += [(table,) + r for r in other.execute(sql)]
            other.close()
    out = sqlite3.connect(a.out)
    out.execute("DROP TABLE IF EXISTS doc_location")
    out.execute("CREATE TABLE doc_location (source_table TEXT, doc_id INTEGER, symbol TEXT, doc_type TEXT, "
                "doc_date TEXT, location_kind TEXT, disk_path TEXT, drive_path TEXT, drive_matched_by TEXT, "
                "PRIMARY KEY (source_table, doc_id))")
    out.execute("DROP TABLE IF EXISTS drive_unlinked")
    out.execute("CREATE TABLE drive_unlinked (path TEXT PRIMARY KEY, top_folder TEXT, size INTEGER)")
    tally: Counter = Counter()
    batch = []
    for table, doc_id, sym, dtype, ddate, stored, sha in rows:
        where, disk, drive, how = locate(stored, sha, disk_sha, files, by_suffix, by_sha, disk_suffix)
        tally[(f"{table}:{dtype}", where)] += 1
        batch.append((table, doc_id, sym, dtype, ddate, where, disk, drive, how))
    out.executemany("INSERT INTO doc_location VALUES (?,?,?,?,?,?,?,?,?)", batch)
    linked = {b[7].lower() for b in batch if b[7]}
    unlinked = [(e["path"], e["path"].split("/")[0], e["size"]) for k, e in files.items() if k not in linked]
    out.executemany("INSERT OR IGNORE INTO drive_unlinked VALUES (?,?,?)", unlinked)
    print("drive files no row points to: " + str(dict(Counter(u[1] for u in unlinked))))
    out.execute("CREATE INDEX idx_doc_location_kind ON doc_location(location_kind, doc_type)")
    out.commit()
    total = Counter()
    for (dtype, where), n in tally.items():
        total[where] += n
    print(f"rows {len(rows)}: {dict(total)} ({time.time() - t:.0f} s)")
    for dtype in sorted({d for d, _ in tally}):
        print(f"  {dtype}: " + ", ".join(f"{w} {tally[(dtype, w)]}" for w in ("disk+drive", "disk", "drive", "not_held",
                                                                     "not_held_no_file_ref")
                                        if tally[(dtype, w)]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
