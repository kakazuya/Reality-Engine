"""Shivam's ticket board: ``D:\\RealityEngine\\reports\\ticket_board.xlsx`` and ``.html``, always in sync.

Shivam, 8 Nov 2026: the Excel board is his source of truth and must always match the tracker
(``tasks/TASKS.md`` + ``tasks/TASKS_DONE.md``).  So the board is rewritten

* after every ``task_board`` add / set / done / drop (``task_board.main``), and
* by the ``post-commit`` hook whenever a commit touches either tracker file (hand edits, worker merges).

Groups: Open, In progress (DOING), Pending a bottleneck (WAITING on someone, LOOKING = needs a check),
Closed (resolved: DONE, or DROPPED as merged/done/fixed), Sidelined (other DROPPED).  One sheet per group
plus a summary; the sync time and the tracker's git HEAD are on the summary.  Sync is one way: an edit
made in the Excel file is overwritten at the next sync.  A board open in Excel cannot be replaced on
Windows: the write is retried at the next sync and the failure is printed, never raised.

    python -m reality_engine.scripts.ticket_board_report [--out-dir DIR]
"""
from __future__ import annotations

import argparse
import html
import os
import re
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OUT_DIR = Path(os.environ.get("REALITY_REPORTS_DIR", r"D:\RealityEngine\reports"))
NAME = "ticket_board"
ORDER = ["Open", "In progress", "Pending a bottleneck", "Closed (resolved)", "Sidelined"]
RESOLVED = re.compile(r"\b(merged|done|fixed|built)\b", re.I)
COLS = ["id", "status", "priority", "section", "title", "note", "accept", "from", "opened", "closing", "file"]
WIDTHS = [8, 22, 8, 22, 80, 50, 50, 18, 12, 24, 18]


def group(status: str) -> str:
    word = status.split()[0] if status else ""
    if word == "DOING":
        return "In progress"
    if word in ("WAITING", "LOOKING"):
        return "Pending a bottleneck"
    if word == "DONE":
        return "Closed (resolved)"
    if word == "DROPPED":
        return "Closed (resolved)" if RESOLVED.search(status) else "Sidelined"
    return "Open"


def note(status: str, tail: str = "") -> str:
    word, _, rest = status.partition(" ")
    if word == "WAITING":
        return f"waiting for {rest or 'someone'}"
    if word == "LOOKING":
        return "needs a check whether it is still open"
    if word == "DOING":
        return f"owner: {rest}" if rest else ""
    if word == "DROPPED":
        return rest
    if word == "DONE":
        return tail
    return ""


def rows(root: Path | None = None) -> list[dict]:
    from reality_engine.scripts import task_board

    live, done = task_board.load_rows(root)
    out = []
    for r, f in [(r, task_board.LIVE_RELATIVE) for r in live] + [(r, task_board.DONE_RELATIVE) for r in done]:
        out.append({"id": r.id, "status": r.status, "priority": r.priority, "section": r.section or "",
                    "title": r.title, "note": note(r.status, r.tail), "accept": r.accept, "from": r.source,
                    "opened": r.opened, "closing": r.tail, "file": f.as_posix(), "group": group(r.status)})
    return out


def _num(ticket: str) -> int:
    digits = re.sub(r"\D", "", ticket)
    return int(digits) if digits else 0


def _head(root: Path) -> str:
    try:
        return subprocess.run(["git", "-C", str(root), "rev-parse", "--short", "HEAD"], capture_output=True,
                              text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def _xlsx(data: dict[str, list[dict]], path: Path, stamp: str) -> None:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    wb = Workbook()
    ws = wb.active
    ws.title = "Summary"
    ws.append(["Group", "Tickets", "P1", "P2", "P3"])
    for g in ORDER:
        c = Counter(r["priority"] for r in data[g])
        ws.append([g, len(data[g]), c.get("P1", 0), c.get("P2", 0), c.get("P3", 0)])
    ws.append(["Total", sum(len(v) for v in data.values())])
    ws.append([])
    ws.append([f"Synced {stamp} from tasks/TASKS.md + tasks/TASKS_DONE.md. One-way: edits here are overwritten."])
    for c in ws[1]:
        c.font = Font(bold=True)
    ws.column_dimensions["A"].width = 26
    for g in ORDER:
        s = wb.create_sheet(g.replace("(", "").replace(")", ""))
        s.append(COLS)
        for c in s[1]:
            c.font = Font(bold=True, color="FFFFFF")
            c.fill = PatternFill("solid", fgColor="334155")
        for r in data[g]:
            s.append([r[k] for k in COLS])
        for i, w in enumerate(WIDTHS):
            s.column_dimensions[chr(65 + i)].width = w
        for row in s.iter_rows(min_row=2):
            for c in row:
                c.alignment = Alignment(wrap_text=True, vertical="top")
        s.freeze_panes = "A2"
        s.auto_filter.ref = s.dimensions
    wb.save(path)


def _html(data: dict[str, list[dict]], path: Path, stamp: str) -> None:
    esc = lambda v: html.escape("" if v is None else str(v))  # noqa: E731
    out = [f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Ticket Board</title><style>
:root{{--bg:#fafaf9;--fg:#1c1917;--mut:#57534e;--line:#e7e5e4;--card:#fff;--p1:#b91c1c}}
@media (prefers-color-scheme:dark){{:root{{--bg:#1c1917;--fg:#f5f5f4;--mut:#a8a29e;--line:#44403c;--card:#292524;--p1:#f87171}}}}
body{{background:var(--bg);color:var(--fg);font:14px/1.45 system-ui,Segoe UI,sans-serif;margin:0 auto;padding:24px 16px;max-width:1200px}}
h1{{font-size:22px;margin:0 0 4px}} .mut{{color:var(--mut)}} h2{{font-size:17px;margin:28px 0 8px;border-bottom:1px solid var(--line);padding-bottom:4px}}
.sum{{display:flex;flex-wrap:wrap;gap:10px;margin:16px 0}} .tile{{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:10px 14px;min-width:120px}}
.tile b{{font-size:22px;display:block}} .wrap{{overflow-x:auto}} table{{border-collapse:collapse;width:100%;background:var(--card)}}
th,td{{border-bottom:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top}} th{{color:var(--mut);font-weight:600;font-size:12px}}
td.id{{white-space:nowrap;font-weight:600}} .P1{{color:var(--p1);font-weight:600}}
</style></head><body><h1>Ticket board</h1><div class="mut">Synced {esc(stamp)} from tasks/TASKS.md and tasks/TASKS_DONE.md; same content as ticket_board.xlsx.</div><div class="sum">"""]
    out += [f'<div class="tile"><b>{len(data[g])}</b>{esc(g)}</div>' for g in ORDER]
    out.append("</div>")
    for g in ORDER:
        out.append(f'<h2>{esc(g)} ({len(data[g])})</h2><div class="wrap"><table><tr><th>Ticket</th><th>Status</th>'
                   '<th>Pri</th><th>Title</th><th>Note</th><th>Accept</th><th>Opened</th></tr>')
        for r in data[g]:
            out.append(f'<tr><td class="id">{esc(r["id"])}</td><td>{esc(r["status"].split(" ")[0])}</td>'
                       f'<td class="{esc(r["priority"])}">{esc(r["priority"])}</td><td>{esc(r["title"])}</td>'
                       f'<td class="mut">{esc(r["note"])}</td><td class="mut">{esc(r["accept"])}</td><td>{esc(r["opened"])}</td></tr>')
        out.append("</table></div>")
    out.append("</body></html>")
    path.write_text("".join(out), encoding="utf-8")


def write(root: Path | None = None, out_dir: Path | None = None) -> dict:
    """Rewrite both files; a file Excel holds open is reported, not raised."""
    root = root or ROOT
    out_dir = Path(out_dir or OUT_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    data: dict[str, list[dict]] = {g: [] for g in ORDER}
    for r in rows(root):
        data[r["group"]].append(r)
    for g in data:
        data[g].sort(key=lambda r: (r["priority"] or "P9", _num(r["id"])))
    stamp = time.strftime("%Y-%m-%d %H:%M IST") + (f", git {_head(root)}" if _head(root) else "")
    result = {"groups": {g: len(v) for g, v in data.items()}, "written": [], "failed": []}
    for ext, fn in (("xlsx", _xlsx), ("html", _html)):
        final = out_dir / f"{NAME}.{ext}"
        tmp = out_dir / f".{NAME}.{os.getpid()}.{ext}"
        try:
            fn(data, tmp, stamp)
            os.replace(tmp, final)
            result["written"].append(str(final))
        except OSError as exc:
            result["failed"].append(f"{final}: {exc} (close it in Excel; the next sync retries)")
            tmp.unlink(missing_ok=True)
    return result


def sync_quietly(root: Path | None = None) -> None:
    """The call ``task_board`` and the post-commit hook make: never fails the caller.
    ``REALITY_TICKET_BOARD_SYNC=0`` turns it off (tests, worker worktrees)."""
    if os.environ.get("REALITY_TICKET_BOARD_SYNC", "1").strip().lower() in ("0", "false", "off", "no"):
        return
    try:
        res = write(root)
        for failure in res["failed"]:
            print(f"ticket board not synced: {failure}", file=sys.stderr)
    except Exception as exc:  # the tracker change itself must never fail on the report
        print(f"ticket board not synced: {type(exc).__name__}: {exc}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="write ticket_board.xlsx/.html from the tracker")
    ap.add_argument("--out-dir", type=Path, default=None)
    args = ap.parse_args(argv)
    res = write(out_dir=args.out_dir)
    print(res)
    return 1 if res["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
