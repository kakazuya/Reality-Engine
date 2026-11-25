"""Build a self-contained 60-row checkpoint grading pack (T-242).

Every verified row of ``--record-type`` named by the checkpoint comes first; the
rest is a seeded fill from the observation DB (a new symbol first, at most two
rows per document). Each row carries the printed page text and the page before
it, read from the store DB that holds its ``doc_key``; the pack is also written
as 30-row halves (``<out>_part00.jsonl``, ``<out>_part01.jsonl``) for two graders.

    python -m reality_engine.scripts.grade_pack --db <observation db> \
        --ckpt <ckpt.jsonl> --stores-glob "<stores>/*/*.db" \
        --record-type statement --seed 7 --out <pack>.jsonl

Every database is opened read-only.
"""
from __future__ import annotations

import argparse
import glob
import json
import random
import sqlite3
from pathlib import Path
from typing import Any, cast

from reality_engine.db.readonly import connect_ro

Row = dict[str, Any]

RECORD_TYPES = ("number", "statement", "guidance")
FIELDS = (
    "observation_id", "symbol", "doc_key", "page", "record_type", "measure",
    "printed_label", "value_text", "value", "unit", "scale", "period", "basis",
    "segment", "speaker", "statement", "question_context", "entity_scope",
    "status", "read_at",
)
PER_DOC = 2


def checkpoint_ids(path: str | Path) -> list[int]:
    """Observation ids from a checkpoint jsonl, in file order (``observation_id`` or ``id``)."""
    ids: list[int] = []
    text = Path(path).read_text(encoding="utf-8")
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        obj = json.loads(line)
        oid = obj.get("observation_id")
        if oid is None:
            oid = obj.get("id")
        if oid is not None and int(oid) not in ids:
            ids.append(int(oid))
    return ids


def open_observation(db: str | Path) -> tuple[sqlite3.Connection, list[str]]:
    """Read-only observation DB and the columns it actually has."""
    con = cast(sqlite3.Connection, connect_ro(db, timeout_s=60))
    con.row_factory = sqlite3.Row
    cols = {str(r[1]) for r in con.execute("PRAGMA table_info(observation)")}
    return con, [c for c in FIELDS if c in cols]


def checkpoint_rows(con: sqlite3.Connection, cols: list[str], ids: list[int],
                    record_type: str) -> list[Row]:
    """The checkpoint's own verified rows, in checkpoint order."""
    if not cols:
        raise SystemExit("observation table has none of the expected columns")
    query = f"select {', '.join(cols)} from observation where observation_id=?"
    rows: list[Row] = []
    for oid in ids:
        found = con.execute(query, (oid,)).fetchone()
        if found is None:
            continue
        row = dict(found)
        if row.get("status") == "verified" and row.get("record_type") == record_type:
            rows.append(row)
    return rows


def verified_pool(con: sqlite3.Connection, cols: list[str], record_type: str) -> list[Row]:
    """Every verified row of the type, oldest id first (the fill pool)."""
    query = (f"select {', '.join(cols)} from observation "
             "where status='verified' and record_type=? order by observation_id")
    return [dict(r) for r in con.execute(query, (record_type,))]


def select_rows(checkpoint: list[Row], pool: list[Row], *, size: int = 60,
                seed: int = 0) -> list[Row]:
    """Checkpoint rows first, then a seeded fill: a new symbol first, at most two rows per doc."""
    rows = list(checkpoint[:size])
    taken = {r["observation_id"] for r in rows}
    per_doc: dict[str, int] = {}
    for r in rows:
        per_doc[r["doc_key"]] = per_doc.get(r["doc_key"], 0) + 1
    syms = {r["symbol"] for r in rows}
    shuffled = list(pool)
    random.Random(seed).shuffle(shuffled)
    for new_symbols_only in (True, False):
        for r in shuffled:
            if len(rows) >= size:
                return rows
            if r["observation_id"] in taken or per_doc.get(r["doc_key"], 0) >= PER_DOC:
                continue
            if new_symbols_only and r["symbol"] in syms:
                continue
            rows.append(r)
            taken.add(r["observation_id"])
            syms.add(r["symbol"])
            per_doc[r["doc_key"]] = per_doc.get(r["doc_key"], 0) + 1
    return rows


def store_index(stores_glob: str) -> dict[str, str]:
    """``doc_key -> first store DB`` (sorted glob) that prints a page for it."""
    index: dict[str, str] = {}
    if not stores_glob:
        return index
    for path in sorted(glob.glob(stores_glob)):
        if path.endswith(("pages.db", "_ocr.db")):
            continue
        try:
            con = cast(sqlite3.Connection, connect_ro(path, timeout_s=10))
        except sqlite3.Error:
            continue
        try:
            for (doc_key,) in con.execute("select distinct doc_key from doc_page"):
                index.setdefault(str(doc_key), path)
        except sqlite3.Error:
            pass
        finally:
            con.close()
    return index


def page_pair(con: sqlite3.Connection, doc_key: str, page: int) -> tuple[str, str]:
    """The row's printed page text and the page before it (empty when absent)."""
    def get(number: int) -> str:
        if number < 1:
            return ""
        found = con.execute("select text from doc_page where doc_key=? and page=?",
                            (doc_key, number)).fetchone()
        return str(found[0] or "") if found else ""

    return get(page), get(page - 1)


def read_pages(index: dict[str, str], rows: list[Row]) -> dict[tuple[str, int], tuple[str, str]]:
    """``(doc_key, page) -> (page_text, previous_page_text)`` for every row."""
    pages: dict[tuple[str, int], tuple[str, str]] = {}
    conns: dict[str, sqlite3.Connection] = {}
    try:
        for r in rows:
            key = (r["doc_key"], int(r["page"]))
            if key in pages:
                continue
            path = index.get(key[0])
            if not path:
                pages[key] = ("", "")
                continue
            con = conns.get(path)
            if con is None:
                con = conns[path] = connect_ro(path, timeout_s=30)
            pages[key] = page_pair(con, key[0], key[1])
    finally:
        for con in conns.values():
            con.close()
    return pages


def build_pack(rows: list[Row], pages: dict[tuple[str, int], tuple[str, str]],
               checkpoint_ids_seen: set[int]) -> list[Row]:
    """The written rows: number, checkpoint flag, page text; ``read_at`` is dropped."""
    pack: list[Row] = []
    for n, r in enumerate(rows, 1):
        row = {k: v for k, v in r.items() if k != "read_at"}
        row["n"] = n
        row["in_checkpoint"] = r["observation_id"] in checkpoint_ids_seen
        page_text, previous = pages.get((r["doc_key"], int(r["page"])), ("", ""))
        row["page_text"] = page_text
        row["previous_page_text"] = previous
        pack.append(row)
    return pack


def _write_jsonl(path: Path, rows: list[Row]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_pack(rows: list[Row], out: str | Path, *, split: int = 30) -> list[Path]:
    """Write the pack and its 30-row halves; returns the part files (empty when split=0)."""
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    for stale in out.parent.glob(f"{out.stem}_part*.jsonl"):
        stale.unlink()
    _write_jsonl(out, rows)
    parts: list[Path] = []
    if split > 0:
        for part_no, start in enumerate(range(0, len(rows), split)):
            part = out.with_name(f"{out.stem}_part{part_no:02d}.jsonl")
            _write_jsonl(part, rows[start:start + split])
            parts.append(part)
    return parts


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Build a 60-row checkpoint grading pack (T-242)")
    ap.add_argument("--db", required=True, help="observation SQLite DB (read-only)")
    ap.add_argument("--ckpt", required=True, help="checkpoint jsonl (observation_id or id per line)")
    ap.add_argument("--stores-glob", default="", help="glob of store DBs holding doc_page")
    ap.add_argument("--record-type", default="number", choices=RECORD_TYPES)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--size", type=int, default=60)
    ap.add_argument("--split", type=int, default=30, help="rows per part file (0 = no parts)")
    ap.add_argument("--out", required=True, help="pack jsonl (parts are <out>_partNN.jsonl)")
    args = ap.parse_args(argv)

    con, cols = open_observation(args.db)
    try:
        ids = checkpoint_ids(args.ckpt)
        own = checkpoint_rows(con, cols, ids, args.record_type)
        pool = verified_pool(con, cols, args.record_type)
    finally:
        con.close()

    rows = select_rows(own, pool, size=args.size, seed=args.seed)
    index = store_index(args.stores_glob)
    pack = build_pack(rows, read_pages(index, rows), set(ids))
    write_pack(pack, args.out, split=args.split)
    from_checkpoint = sum(1 for r in pack if r["in_checkpoint"])
    missing = sum(1 for r in pack if not r["page_text"])
    print(f"{len(pack)} rows ({from_checkpoint} from checkpoint), missing pages: {missing}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
