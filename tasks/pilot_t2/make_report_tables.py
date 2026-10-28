"""Render coverage.json into the markdown tables REPORT.md embeds."""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPORT = json.loads((HERE / "coverage.json").read_text(encoding="utf-8"))
TYPES = ("annual_report", "concall", "deck", "results_notes", "announcement")
SHORT = {"annual_report": "AR", "concall": "concall", "deck": "deck",
         "results_notes": "notes", "announcement": "ann"}


def main() -> None:
    spec = (HERE.parents[1] / "tasks" / "arch_v3" / "PILOT_SPEC.md").read_text(encoding="utf-8")
    names = {}
    for line in spec.splitlines():
        parts = [p.strip() for p in line.strip().strip("|").split("|")]
        if len(parts) > 2 and parts[1].startswith("INE"):
            names[parts[1]] = parts[2]

    lines = ["### Coverage totals (registry vs store)", "",
             "| doc type | expected | found | missing |", "|---|---:|---:|---:|"]
    for doc_type in TYPES:
        total = REPORT["totals"].get(doc_type, {"expected": 0, "found": 0})
        missing = total["expected"] - total["found"]
        lines.append(f"| {SHORT[doc_type]} | {total['expected']} | {total['found']} | {missing} |")
    lines += ["", "### Coverage per ISIN (found / expected)", "",
              "| ISIN | symbol | AR | concall | deck | notes | ann |", "|---|---|---:|---:|---:|---:|---:|"]
    missing_rows = []
    for isin, by_type in REPORT["by_isin"].items():
        cells = []
        for doc_type in TYPES:
            row = by_type.get(doc_type) or {"expected": 0, "found": 0}
            cells.append(f"{row['found']}/{row['expected']}")
            for miss in row.get("missing") or []:
                missing_rows.append((doc_type, isin, names.get(isin, ""), miss))
        lines.append(f"| {isin} | {names.get(isin, '')} | " + " | ".join(cells) + " |")
    lines += ["", f"### Missing originals ({len(missing_rows)})", "",
              "| doc type | ISIN | symbol | date | ref / title |", "|---|---|---|---|---|"]
    for doc_type, isin, symbol, miss in sorted(missing_rows, key=lambda r: (r[0], r[1], r[3].get("date") or "")):
        title = (miss.get("title") or "").replace("|", " ")[:90]
        lines.append(f"| {SHORT[doc_type]} | {isin} | {symbol} | {miss.get('date') or ''} | "
                     f"`{miss.get('ref')}` {title} |")
    (HERE / "coverage_tables.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"coverage_tables.md: {len(missing_rows)} missing originals")


if __name__ == "__main__":
    main()
