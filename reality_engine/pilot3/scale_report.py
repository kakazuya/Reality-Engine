"""Seconds and MB per build part per company, and the projection to the universe (T-094).

CLI: ``python -m reality_engine.pilot3.scale_report --log <build.json> --db <built.db> [--pages-db <pages.db>] [--companies N]``

``--log`` is the JSON that ``pilot3.build`` prints, one or several objects, so parts built apart can be added up.  A part
whose seconds grow with companies scales by division; a part with a fixed cost per run does not, and straight division
hides it: T-094 measures which is which by building the same part on different counts (``--fixed part=seconds``).
Projection is a measured figure multiplied, so it is only as good as how alike the companies are; the report says how
many companies it rests on.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
from pathlib import Path

UNIVERSE = 6940
PROCESSES = 6


def parts_from_log(text: str) -> dict[str, float]:
    """``seconds_<part>`` from the printed build log(s), added across runs."""
    out: dict[str, float] = {}
    for name, value in re.findall(r'"seconds_([a-z_]+)":\s*([\d.]+)', text):
        out[name] = out.get(name, 0.0) + float(value)
    return out


def companies_in(db: Path) -> int:
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return conn.execute("SELECT COUNT(DISTINCT symbol) FROM company").fetchone()[0]
    finally:
        conn.close()


def report(seconds: dict[str, float], companies: int, db_mb: float, pages_mb: float, universe: int = UNIVERSE,
           processes: int = PROCESSES, fixed: dict[str, float] | None = None) -> str:
    fixed = fixed or {}
    lines = [f"Measured on {companies} companies. Projection to {universe}: one process and {processes}.", "",
             "| part | seconds | fixed per run | seconds per company | projected hours, 1 process |",
             "|---|---:|---:|---:|---:|"]
    total = 0.0
    for part, value in sorted(seconds.items(), key=lambda kv: -kv[1]):
        once = fixed.get(part, 0.0)
        each = max(0.0, value - once) / companies
        hours = (once + each * universe) / 3600
        total += hours
        lines.append(f"| {part} | {value:.1f} | {once:.1f} | {each:.2f} | {hours:.1f} |")
    per_mb = (db_mb + pages_mb) / companies
    lines += ["", f"Total hours: {total:.1f} on one process, {total / processes:.1f} on {processes} if every part divides.",
              f"Size: {db_mb:.1f} MB build + {pages_mb:.1f} MB pages = {per_mb:.1f} MB per company, "
              f"{per_mb * universe / 1024:.0f} GB for {universe}."]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--log", required=True, type=Path)
    ap.add_argument("--db", required=True, type=Path)
    ap.add_argument("--pages-db", type=Path, default=None)
    ap.add_argument("--companies", type=int, default=None)
    ap.add_argument("--fixed", action="append", default=[], help="part=seconds of fixed cost per run, measured")
    args = ap.parse_args(argv)
    fixed = {part: float(value) for part, value in (item.split("=") for item in args.fixed)}
    seconds = parts_from_log(args.log.read_text(encoding="utf-8"))
    companies = args.companies or companies_in(args.db)
    pages_mb = args.pages_db.stat().st_size / 1e6 if args.pages_db else 0.0
    print(report(seconds, companies, args.db.stat().st_size / 1e6, pages_mb, fixed=fixed))


if __name__ == "__main__":
    main()
