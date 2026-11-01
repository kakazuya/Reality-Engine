"""Generate tasks/DATA_INVENTORY.md from what is really on disk: every database table and raw folder.

Written docs drifted from the stores, so this file is generated, never hand-edited. Check it before
saying any data is not held:  python -m reality_engine.scripts.data_inventory
"""
from __future__ import annotations

import datetime as dt
import glob
import os
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "reality_engine" / "data"
RAW = Path("D:/RealityEngine/raw")
OUT = ROOT / "tasks" / "DATA_INVENTORY.md"
DOCS = ["AGENTS.md", "tasks/STATE.md", "plugins/reality-data/catalog_descriptions.yaml", "tasks/SCHEMA_FINAL_2026-10-29.md"]
SKIP = ("_fts_", "sqlite_")


def tables(path: str) -> list[tuple[str, int]]:
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=2)
    try:
        out = []
        for (name,) in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
            if any(s in name for s in SKIP) or name.endswith("_fts"):
                continue
            try:  # MAX(rowid) is instant and close enough to size a table
                out.append((name, con.execute(f'SELECT COALESCE(MAX(rowid),0) FROM "{name}"').fetchone()[0]))
            except sqlite3.Error:
                out.append((name, con.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]))
        return out
    finally:
        con.close()


def report_cells(path: str) -> list[str]:
    """Report tables are held cell by cell, so their contents are invisible from the table name."""
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
    try:
        lines = []
        for src, n in con.execute("SELECT source, COUNT(DISTINCT file) FROM mkt_report_cells GROUP BY 1").fetchall():
            files = sorted(f for (f,) in con.execute("SELECT DISTINCT file FROM mkt_report_cells WHERE source=?", (src,)))
            lines.append(f"- `{src}`: {n} files, for example `{files[0]}`, `{files[-1]}`")
        return lines
    finally:
        con.close()


def raw_folder(path: Path) -> tuple[int, float, str]:
    n, size, newest, name = 0, 0, 0.0, ""
    for base, _, files in os.walk(path):
        for f in files:
            st = os.stat(os.path.join(base, f))
            n, size = n + 1, size + st.st_size
            if st.st_mtime > newest:
                newest, name = st.st_mtime, f
    day = dt.date.fromtimestamp(newest).isoformat() if newest else "-"
    return n, size / 1e9, f"{day} `{name[:50]}`" if name else "-"


def main() -> None:
    known = "".join((ROOT / d).read_text(encoding="utf-8", errors="ignore") for d in DOCS)
    lines = ["# Data inventory: generated, do not edit", "",
             f"Generated {dt.datetime.now():%Y-%m-%d %H:%M} IST by `reality_engine/scripts/data_inventory.py`. "
             "Check here before saying data is not held. 'Undocumented' means no main doc names it.", ""]
    lines += ["## Report tables held cell by cell (`equity_intelligence.mkt_report_cells`)", ""]
    lines += report_cells(str(DATA / "equity_intelligence.db")) + [""]
    undoc_t = undoc_r = 0
    lines += ["## Databases", "", "| Database | Table | Rows (about) | Named in docs |", "|---|---|---:|---|"]
    for db in sorted(glob.glob(str(DATA / "*.db")) + glob.glob(str(DATA / "pilot" / "*.db")) + glob.glob(str(DATA / "pilot" / "*" / "*.db"))):
        rel = os.path.relpath(db, DATA).replace("\\", "/")
        try:
            for name, rows in sorted(tables(db)):
                doc = name in known
                undoc_t += not doc
                lines.append(f"| {rel} | `{name}` | {rows:,} | {'yes' if doc else '**undocumented**'} |")
        except sqlite3.Error as e:
            lines.append(f"| {rel} | unreadable: {e} | | |")
    lines += ["", "## Raw folders on D", "", "| Folder | Files | GB | Newest file | Named in docs |", "|---|---:|---:|---|---|"]
    folders = [d for d in RAW.iterdir() if d.is_dir() and d.name != "raw_market"] + [d for d in (RAW / "raw_market").iterdir() if d.is_dir()]
    for d in sorted(folders):
        n, gb, newest = raw_folder(d)
        doc = d.name in known
        undoc_r += not doc
        lines.append(f"| {d.relative_to(RAW).as_posix()} | {n:,} | {gb:.2f} | {newest} | {'yes' if doc else '**undocumented**'} |")
    lines.insert(3, f"Undocumented: {undoc_t} tables and {undoc_r} of {len(folders)} raw folders.")
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print(OUT, "undocumented tables", undoc_t, "raw folders", undoc_r, "of", len(folders))


if __name__ == "__main__":
    main()
