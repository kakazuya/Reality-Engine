"""Move the raw source folders off C onto the D raw root (Task G0, Shivam 2026-10-25).

Dry run by default: prints, per folder, the file count, bytes, how many files the destination
already holds (same size + sha256) and any conflict. ``--apply`` copies each file to
``RAW_ROOT/<folder>/...`` (``pdfs`` reuses the existing ``D:\\RealityEngine\\pdfs`` pile),
verifies size + sha256, then deletes the C copy, and writes
``RAW_ROOT/_migration/<YYYY-MM-DD>.json``. Resumable: a destination that already holds the
same bytes is never copied again, only the C copy is unlinked.

    python -m reality_engine.scripts.migrate_raw_to_d                 # dry run
    python -m reality_engine.scripts.migrate_raw_to_d --apply

Databases and logs stay on C; they are not in FOLDERS.
"""
import argparse
import hashlib
import json
import os
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

from reality_engine import config as cfg

FOLDERS = ("pdfs", "raw_market", "bhavcopy", "tax_sources", "ar_queue",
           "index_constituents", "macro_pdfs", "decks")
CHUNK = 1 << 20


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(CHUNK), b""):
            h.update(block)
    return h.hexdigest()


def _classify(folder: str, src: Path, dest: Path, dup: dict | None = None) -> dict:
    """move = copy then delete; already_on_d = the D pile holds the same bytes;
    conflict = the destination path holds different bytes."""
    size = src.stat().st_size
    row = {"folder": folder, "src": str(src), "dest": str(dest), "bytes": size}
    if dest.exists():
        if dest.stat().st_size != size:
            return {**row, "status": "conflict", "reason": "size"}
        digest = sha256(src)
        if sha256(dest) == digest:
            return {**row, "status": "already_on_d", "sha256": digest}
        return {**row, "status": "conflict", "reason": "sha256"}
    if dup:  # same content already on D under another name (pdfs are uuid-named)
        digest = sha256(src)
        existing = dup.get(digest)
        if existing is not None:
            return {**row, "status": "already_on_d", "sha256": digest, "dup_of": str(existing)}
    return {**row, "status": "move"}


def _sha_index(dest_root: Path, sizes: set) -> dict:
    """sha256 -> already-D path, over destination files whose size matches some source file."""
    index = {}
    if not dest_root.is_dir():
        return index
    for p in dest_root.rglob("*"):
        try:
            if p.is_file() and p.stat().st_size in sizes:
                index.setdefault(sha256(p), p)
        except OSError:
            continue
    return index


def plan(src_root: Path, dest_root: Path, pdfs_root: Path, folders=FOLDERS, workers: int = 4) -> list:
    """Every raw file under ``src_root/<folder>`` with its destination and disposition."""
    roots = {f: (pdfs_root if f == "pdfs" else dest_root / f) for f in folders}
    rows = []
    for folder, dest in roots.items():
        src = src_root / folder
        if not src.is_dir():
            continue
        files = [p for p in src.rglob("*") if p.is_file()]
        dup = None
        if folder == "pdfs":
            # The D pile may already hold the same file under a different (uuid) name: reuse
            # those bytes instead of copying them again.
            dup = _sha_index(dest, {p.stat().st_size for p in files})
        with ThreadPoolExecutor(max_workers=workers) as pool:
            rows.extend(pool.map(lambda p: _classify(folder, p, dest / p.relative_to(src), dup), files))
    return rows


def summarise(rows: list) -> dict:
    """Per-folder file count, bytes, and already-on-D / conflict counts."""
    out = {}
    for r in rows:
        s = out.setdefault(r["folder"], {"files": 0, "bytes": 0, "already_on_d": 0,
                                         "conflict": 0, "to_copy": 0, "to_copy_bytes": 0})
        s["files"] += 1
        s["bytes"] += r["bytes"]
        if r["status"] == "already_on_d":
            s["already_on_d"] += 1
        elif r["status"] == "conflict":
            s["conflict"] += 1
        else:
            s["to_copy"] += 1
            s["to_copy_bytes"] += r["bytes"]
    return out


def _copy_verified(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    shutil.copy2(src, part)
    if part.stat().st_size != src.stat().st_size or sha256(part) != sha256(src):
        part.unlink()
        raise OSError(f"verify failed after copy: {src} -> {dest}")
    os.replace(part, dest)


def _link_or_copy(existing: Path, dest: Path) -> None:
    """One hardlink when both paths are on the same volume (no bytes duplicated), else a copy."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(existing, dest)
    except OSError:
        shutil.copy2(existing, dest)


def apply(rows: list, manifest: Path, src_root: Path, dest_root: Path) -> dict:
    """Copy what is missing, verify, delete the C copy. Safe to re-run."""
    done = {"moved": 0, "already_on_d": 0, "conflict": 0, "gone": 0, "bytes_freed": 0}
    n = 0
    for r in rows:
        src, dest = Path(r["src"]), Path(r["dest"])
        if r["status"] == "conflict":
            done["conflict"] += 1
            continue
        if not src.exists():
            r["status"] = "gone"
            done["gone"] += 1
            continue
        if r["status"] == "move":
            _copy_verified(src, dest)
            r["sha256"] = sha256(dest)
            r["status"] = "moved"
            done["moved"] += 1
        else:
            done["already_on_d"] += 1
            if r.get("dup_of") and not dest.exists():  # keep the canonical path readable
                _link_or_copy(Path(r["dup_of"]), dest)
        src.unlink()
        done["bytes_freed"] += r["bytes"]
        n += 1
        if n % 100 == 0:  # periodic resume state, not a per-file flush
            save(manifest, rows, src_root, dest_root)
    for folder in {r["folder"] for r in rows}:
        _prune_empty(src_root / folder)
    save(manifest, rows, src_root, dest_root)
    return done


def _prune_empty(root: Path) -> None:
    """Remove now-empty folders under ``root`` (deepest first, ``root`` last); failures are ignored."""
    if root is None or not root.is_dir():
        return
    dirs = [root] + sorted((p for p in root.rglob("*") if p.is_dir()),
                           key=lambda p: len(p.parts), reverse=True)
    for d in dirs:
        try:
            d.rmdir()
        except OSError:
            pass


def save(manifest: Path, rows: list, src_root: Path, dest_root: Path) -> None:
    manifest.parent.mkdir(parents=True, exist_ok=True)
    payload = {"date": date.today().isoformat(), "source_root": str(src_root),
               "raw_root": str(dest_root), "folders": summarise(rows), "files": rows}
    tmp = manifest.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    os.replace(tmp, manifest)


def report(s: dict) -> None:
    print(f"{'folder':<20}{'files':>8}{'bytes':>16}{'already_on_d':>14}{'copy':>8}{'conflict':>10}")
    for folder, v in sorted(s.items()):
        print(f"{folder:<20}{v['files']:>8}{v['bytes']:>16,}{v['already_on_d']:>14}"
              f"{v['to_copy']:>8}{v['conflict']:>10}")
    total = {k: sum(v[k] for v in s.values()) for k in ("files", "bytes", "already_on_d", "to_copy", "conflict")}
    print(f"{'TOTAL':<20}{total['files']:>8}{total['bytes']:>16,}{total['already_on_d']:>14}"
          f"{total['to_copy']:>8}{total['conflict']:>10}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Move raw files from the C data dir to RAW_ROOT on D.")
    ap.add_argument("--apply", action="store_true", help="copy + verify + delete (default: dry run)")
    ap.add_argument("--source", type=Path, default=cfg.DATA_DIR, help="C data dir holding the raw folders")
    ap.add_argument("--dest", type=Path, default=cfg.RAW_ROOT, help="D raw root")
    ap.add_argument("--pdfs-dest", type=Path, default=cfg.PDFS_DIR, help="D pdf root (reused pile)")
    ap.add_argument("--folders", default=",".join(FOLDERS))
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args(argv)

    folders = [f.strip() for f in a.folders.split(",") if f.strip()]
    rows = plan(a.source, a.dest, a.pdfs_dest, folders, a.workers)
    s = summarise(rows)
    report(s)
    manifest = a.dest / "_migration" / f"{date.today().isoformat()}.json"
    if not a.apply:
        print(f"\ndry run: nothing copied or deleted. manifest would be {manifest}")
        return 1 if any(v["conflict"] for v in s.values()) else 0
    done = apply(rows, manifest, a.source, a.dest)
    save(manifest, rows, a.source, a.dest)
    print(f"\n{done} \nmanifest: {manifest}")
    return 1 if done["conflict"] else 0


if __name__ == "__main__":
    sys.exit(main())
