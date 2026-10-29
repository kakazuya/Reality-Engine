"""T2 chunks_v3 for the pilot-60 universe + the 30 bank-regression ISINs.

    python tasks/pilot60/build_chunks60.py [--limit N]

Reuses the reviewed T2 builder (``tasks/pilot_t2/build_chunks_v3.py``) unchanged:
same chunker_v3, same registries (ar_docs / corporate_documents / deck_sources /
BSE+NSE announcement manifests), same FY25+ cutoff (2024-04-01), same known_at
rule (the filing record, never the crawl date).  Only three module globals are
pointed at this pilot: the ISIN list, the store path and the report directory.

Writes ``.tmp/pilot60/chunks_v3_pilot.db`` (override with REALITY_CHUNKS_V3) and
``tasks/pilot60/coverage.json`` (per ISIN x doc type, with every missing original).
Read-only on D: and every DB.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
T2_BASE = REPO / "tasks" / "pilot_t2" / "build_chunks_v3.py"
ISIN_FILE = Path(os.environ.get("REALITY_T2_ISINS_FILE") or (REPO / "tasks" / "pilot60" / "T2_ISINS.txt"))
OUT_DIR = Path(os.environ.get("REALITY_PILOT60_OUT") or (REPO / "tasks" / "pilot60"))
DB_PATH = Path(os.environ.get("REALITY_CHUNKS_V3") or (REPO / ".tmp" / "pilot60" / "chunks_v3_pilot.db"))


def load_builder():
    spec = importlib.util.spec_from_file_location("build_chunks_v3", T2_BASE)
    module = importlib.util.module_from_spec(spec)
    sys.modules["build_chunks_v3"] = module  # dataclasses resolve annotations via sys.modules
    spec.loader.exec_module(module)
    return module


def isins60() -> list[str]:
    if not ISIN_FILE.is_file():
        raise SystemExit(f"missing {ISIN_FILE}: run python -m reality_engine.pilot.universe60")
    return [line.strip() for line in ISIN_FILE.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def cap_loaders(b, spec: str) -> None:
    """Keep the latest N registry rows per company and doc type (``type=N,...``).

    The full FY25+ set is ~2,800 documents on one disk (annual reports parse at
    ~10 s each); the pilot needs the latest documents of every type per company.
    The uncropped registry is still what ``coverage.json`` lists as missing.
    """
    from collections import defaultdict
    limits = {}
    for part in spec.split(","):
        if "=" in part:
            key, value = part.split("=", 1)
            limits[key.strip()] = int(value)
    loaders = {"annual_report": ("load_annual_reports",),
               "concall": ("load_concalls",),
               "deck": ("load_decks",),
               "results_notes": ("load_results_notes",),
               "announcement": ("load_bse_announcements", "load_nse_attachments")}
    for doc_type, names in loaders.items():
        if doc_type not in limits:
            continue
        for name in names:
            original = getattr(b, name)

            def wrapped(isins, index, _fn=original, _n=limits[doc_type]):
                grouped: dict[str, list] = defaultdict(list)
                for draft in _fn(isins, index):
                    grouped[draft.meta.isin].append(draft)
                out = []
                for drafts in grouped.values():
                    drafts.sort(key=lambda d: d.meta.known_at or "")
                    out += drafts[-_n:]
                return out

            setattr(b, name, wrapped)
    print(f"per-company doc-type caps: {limits}")


def isin_alias(b, isins: list[str]) -> dict[str, str]:
    """Old ISIN -> T2 ISIN for the same symbol (split/face-value rekeys), by symbol.

    The base builder derives this from the PILOT_SPEC text, which only names the
    original 30.  Here the same rule runs over every T2 symbol: when a symbol
    traded under two ISINs and exactly one of them is in this pilot, the other one
    is remapped, so an old call is not invisible to a filter on today's ISIN.
    """
    from collections import defaultdict
    con = b.ro(b.DATA / "equity_intelligence.db")
    q = ",".join("?" * len(isins))
    by_sym: dict[str, set[str]] = defaultdict(set)
    try:
        for r in con.execute(f"SELECT DISTINCT symbol, isin FROM corporate_documents "
                             f"WHERE isin IN ({q})", isins):
            if r["symbol"]:
                by_sym[r["symbol"]].add(r["isin"])
        for r in con.execute(f"SELECT DISTINCT symbol, isin FROM symbol_isin_history "
                             f"WHERE isin IN ({q})", isins):
            if r["symbol"]:
                by_sym[r["symbol"]].add(r["isin"])
    finally:
        con.close()
    target = set(isins)
    alias = {}
    for sym, found in by_sym.items():
        keep = found & target
        if len(keep) == 1:
            for old in found - keep:
                alias[old] = next(iter(keep))
    return alias


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int)
    ap.add_argument("--only", choices=("annual_report", "concall", "deck", "results_notes",
                                       "announcement"),
                    help="build one doc type only, e.g. results_notes into its own store")
    ap.add_argument("--out-db", help="chunk store (default: .tmp/pilot60/chunks_v3_pilot.db)")
    ap.add_argument("--out-dir", help="report dir (default: the store's dir with --only)")
    args = ap.parse_args(argv)
    b = load_builder()
    isins = isins60()
    db_path = Path(args.out_db) if args.out_db else DB_PATH
    out_dir = Path(args.out_dir) if args.out_dir else (db_path.parent if args.only else OUT_DIR)
    b.DB_PATH = db_path
    b.OUT_DIR = out_dir
    b.pilot_isins = lambda: isins
    b.isin_alias = lambda given: isin_alias(b, given)
    if args.only:
        loaders = {"annual_report": ("load_annual_reports",), "concall": ("load_concalls",),
                   "deck": ("load_decks",), "results_notes": ("load_results_notes",),
                   "announcement": ("load_bse_announcements", "load_nse_attachments")}
        for doc_type, names in loaders.items():
            if doc_type != args.only:
                for name in names:
                    setattr(b, name, lambda *_a, **_k: [])
        if args.only == "results_notes":
            # its resolver reads the results raw root, not the D: PDF tree walk
            b.FileIndex = b._NoIndex
    cap = os.environ.get("REALITY_T2_MAX_PER_TYPE")
    if cap:
        cap_loaders(b, cap)
    print(f"T2 ISINs: {len(isins)} -> {db_path}")
    stats = b.build(args.limit)
    out_dir.mkdir(parents=True, exist_ok=True)
    known = stats.get("known_at_checks") or []
    bad = [c for c in known if c["known_at"] != c["record_known_at"]]
    stats["known_at_mismatches"] = len(bad)
    (out_dir / "chunks_build.json").write_text(json.dumps(
        {k: v for k, v in stats.items() if k != "known_at_checks"}, indent=1), encoding="utf-8")
    lines = ["# known_at check — first rows vs the filing record", "",
             "| doc_id | type | source ref | chunk known_at | record known_at | match |",
             "|---|---|---|---|---|---|"]
    for c in known:
        lines.append(f"| {c['doc_id'][:40]} | {c['doc_type']} | {c['source_ref']} | "
                     f"{c['known_at']} | {c['record_known_at']} | "
                     f"{'OK' if c['known_at'] == c['record_known_at'] else 'MISMATCH'} |")
    lines += ["", f"mismatches: {len(bad)} / {len(known)}"]
    (out_dir / "known_at_check.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"known_at: {len(bad)} mismatch / {len(known)} rows")
    print(json.dumps({k: v for k, v in stats.items() if k != "known_at_checks"}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
