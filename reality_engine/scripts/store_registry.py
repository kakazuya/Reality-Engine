"""T-203: build the pilot3 store registry the reality-data ``pilot3_*`` tools route by.

The tools used to serve one store per server start (``REALITY_PILOT3_DB``).  A test company in its own store
therefore needed a new pin in the committed ``.mcp.json`` and a reconnect.  Now ``REALITY_PILOT3_STORES`` names
this small JSON file: every call resolves its symbol against the registered stores, in the file's order, and opens
the first store that holds it (all read-only).  ``REALITY_PILOT3_DB`` still pins one store for tests and A/B runs.

Generate it (the stores are registered freshest-build first, so a symbol held in two of them is answered by the
newer build; the repo's own ``reality_engine/data/pilot3/pilot3.db`` is the last fallback):

    python -m reality_engine.scripts.store_registry --scan D:/RealityEngine --out D:/RealityEngine/stores.json

A directory level under ``--scan`` holds one store per folder (``p20/p20new.db``); backups and scratch files are
skipped (``*_before_*``, ``*_ab*``, ``*copy*``, ``pages.db``, ``*_ocr.db``), and so is any ``*.db`` without a
``company`` table (the proof it is a pilot3 build).  The ``--out`` default is ``D:/RealityEngine/stores.json``,
the default the tools read when the environment names nothing.  Read-only: it opens every candidate with
``mode=ro`` and never writes a store.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import time
from pathlib import Path
from typing import Any

ENV = "REALITY_PILOT3_STORES"
DEFAULT_SCAN = Path("D:/RealityEngine")
DEFAULT_OUT = DEFAULT_SCAN / "stores.json"
REPO_ROOT = Path(__file__).resolve().parents[2]

# A pilot3 store is proved by its ``company`` table: a pages.db, an OCR scratch file, a copy or a backup also
# carries pilot3 tables, and none of them may enter the registry.
SKIP = re.compile(r"(_before_|_ab|copy|^pages\.db$|_ocr\.db$)", re.IGNORECASE)
SKIP_DIRS = {"backups", "backup", ".tmp", "history"}


def default_store() -> Path:
    """The repo's own pilot3 build (``REALITY_DATA_ROOT`` or the checkout's ``reality_engine/data``)."""
    data = Path(os.environ.get("REALITY_DATA_ROOT") or REPO_ROOT / "reality_engine" / "data")
    return data / "pilot3" / "pilot3.db"


def _connect(path: Path) -> sqlite3.Connection | None:
    """Read-only open; a finished store whose WAL side files are gone needs ``immutable=1`` (as in the tools).

    SQLite can defer the failure to the first read, so every candidate is proved with one bounded statement.  A
    store that still HAS a WAL file is never read immutably (that would drop its latest commits): such a store is
    reported as skipped instead of entering the registry as a stale read.
    """
    wal = Path(str(path) + "-wal")
    wal_gone = not wal.exists() or wal.stat().st_size == 0
    for extra in ("", "&immutable=1"):
        if extra and not wal_gone:
            break
        con: sqlite3.Connection | None = None
        try:
            con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro{extra}", uri=True, timeout=5)
            con.execute("SELECT 1 FROM sqlite_master LIMIT 1").fetchone()
            return con
        except sqlite3.Error:
            if con is not None:
                try:
                    con.close()
                except sqlite3.Error:
                    pass
    return None


def company_symbols(path: Path) -> list[str] | None:
    """Distinct company symbols, or ``None`` when the file is not a readable pilot3 store."""
    con = _connect(path)
    if con is None:
        return None
    try:
        if not con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='company'").fetchone():
            return None
        rows = con.execute("SELECT DISTINCT symbol FROM company WHERE symbol IS NOT NULL AND symbol<>''")
        return sorted({str(row[0]) for row in rows})
    except sqlite3.Error:
        return None
    finally:
        con.close()


def entry(path: Path, symbols: list[str] | None = None) -> dict[str, Any] | None:
    """One registry row: name, path, build date and the companies it holds (``None`` for a non-store)."""
    symbols = company_symbols(path) if symbols is None else symbols
    if symbols is None:
        return None
    return {"name": path.parent.name or path.stem, "path": path.as_posix(),
            "built": time.strftime("%Y-%m-%d", time.localtime(path.stat().st_mtime)), "symbols": symbols}


def scan(root: Path, skipped: list[tuple[Path, str]] | None = None) -> list[dict[str, Any]]:
    """Every pilot3 store one directory level under ``root`` (``root/*.db`` and ``root/*/*.db``), path order.

    ``skipped`` optionally collects the ``*.db`` files that were not a readable pilot3 store, so a run says what
    it left out instead of hiding it.
    """
    root = root.expanduser()
    candidates = [root] if root.is_file() else [*root.glob("*.db"), *root.glob("*/*.db")]
    out: list[dict[str, Any]] = []
    seen: set[Path] = set()
    for path in sorted(candidates, key=lambda p: str(p).lower()):
        if not path.is_file() or path in seen:
            continue
        relative = path.relative_to(root) if path != root else path
        if SKIP.search(path.name) or SKIP.search(str(relative)):
            continue
        if any(part.lower() in SKIP_DIRS for part in relative.parts):
            continue
        seen.add(path)
        row = entry(path)
        if row is None:
            if skipped is not None:
                skipped.append((path, "no readable company table"))
            continue
        out.append(row)
    return out


def build(root: Path = DEFAULT_SCAN, include_default: bool = True,
          skipped: list[tuple[Path, str]] | None = None) -> list[dict[str, Any]]:
    """The registry in priority order: the FRESHEST build first (a symbol held in two stores is answered by the
    newer one, whose rows the current code can read), the repo's own ``pilot3.db`` last as the fallback."""
    stores = sorted(scan(root, skipped), key=lambda row: str(row["built"] or ""), reverse=True)
    held = {Path(row["path"]) for row in stores}
    if include_default:
        store = default_store()
        if store.is_file() and store not in held:
            row = entry(store)
            if row is not None:
                stores.append(row)
    return stores


def registry_path() -> Path | None:
    """The registry file this process reads: ``REALITY_PILOT3_STORES`` else the generated default."""
    named = os.environ.get(ENV)
    if named:
        return Path(named)
    return DEFAULT_OUT if DEFAULT_OUT.is_file() else None


def load_registry(path: str | Path | None = None) -> list[dict[str, Any]]:
    """Registered stores in priority order, as ``{name, path: Path, built, symbols: tuple}``; [] when none.

    An entry whose file has gone is dropped (a stale registry must not break routing); one that exists is kept
    even if it cannot be read, so the not-found reply can name it.
    """
    selected = Path(path) if path else registry_path()
    if selected is None or not selected.is_file():
        return []
    data = json.loads(selected.read_text(encoding="utf-8"))
    rows = data.get("stores") if isinstance(data, dict) else data
    out: list[dict[str, Any]] = []
    seen: set[Path] = set()
    for item in rows or []:
        if isinstance(item, str):
            item = {"path": item}
        if not isinstance(item, dict) or not item.get("path"):
            continue
        store = Path(str(item["path"])).expanduser()
        if not store.is_file() or store in seen:
            continue
        seen.add(store)
        out.append({"name": str(item.get("name") or store.parent.name or store.stem), "path": store,
                    "built": item.get("built"), "symbols": tuple(item.get("symbols") or ())})
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the pilot3 store registry (T-203).")
    parser.add_argument("--scan", default=str(DEFAULT_SCAN), help="folder holding the store folders")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="registry JSON to write")
    parser.add_argument("--no-default", action="store_true", help="leave the repo's own pilot3.db out")
    parser.add_argument("--print", action="store_true", help="print the JSON after writing it")
    args = parser.parse_args(argv)
    skipped: list[tuple[Path, str]] = []
    stores = build(Path(args.scan), include_default=not args.no_default, skipped=skipped)
    payload = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "scan": str(Path(args.scan)),
               "stores": stores, "skipped": [{"path": str(path), "why": why} for path, why in skipped]}
    text = json.dumps(payload, indent=1, ensure_ascii=False)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text + "\n", encoding="utf-8")
    print(f"wrote {out}: {len(stores)} stores, {sum(len(s['symbols']) for s in stores)} companies")
    for row in stores:
        print(f"  {row['name']:<12} {len(row['symbols']):>4} companies  built {row['built']}  {row['path']}")
    for path, why in skipped:
        print(f"  skipped      {path}: {why}")
    if args.print:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
