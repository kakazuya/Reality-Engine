"""T-219: one view over every tracked item -- tickets, ideas, rulings and store defects.

Shivam 16 Nov 2026: four trackers in four shapes become patchwork, and Claude must keep a persistent memory of the
work and its direction; trackers stay local, on Drive or in git/GitHub, never a cloud service.  Each source keeps
its own writer (``task_board`` for tickets, ``store_repair note`` for defects, the idea box and ``ruling add`` for
rules); this script reads all four into one item shape and writes the views:

    type      ticket | idea | ruling | defect
    id        T-219 | I-006 | RUL-<section>-<n> | R-005
    status    open | doing | parked | done | dropped | active | fixed ...
    title, why, tags, links (ids this item names), source (file it came from), opened, review_by

    python -m reality_engine.scripts.items list [--type idea] [--open]
    python -m reality_engine.scripts.items render     # tasks/ITEMS.md + reports/items.xlsx
    python -m reality_engine.scripts.items due        # ideas whose review date has passed, open defects
    python -m reality_engine.scripts.items github [--apply]   # mirror open tickets/defects to GitHub Issues

Links are any T-NNN / I-NNN / R-NNN / H-NN the item's text names, so a defect that names its ticket, or a ticket
that names an idea, shows up on both.  Read-only over the sources; the views are generated, never hand-edited.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
TICKETS = REPO / "tasks" / "tickets.jsonl"
IDEAS = REPO / "tasks" / "IDEA_BOX.md"
RULINGS = REPO / "tasks" / "RULINGS.md"
DEFECTS = REPO / "tasks" / "store_repair" / "notes.jsonl"
ITEMS_MD = REPO / "tasks" / "ITEMS.md"
ITEMS_XLSX = REPO / "reports" / "items.xlsx"
LINK = re.compile(r"\b(?:T-\d{3}|I-\d{3}|R-\d{3}|H-\d{2,3})\b")
OPEN = {"open", "doing", "parked", "next", "fix_written", "active"}
MIRRORED = {"ticket", "defect"}
MARKER = "<!-- item:{id} -->"
MARKER_RE = re.compile(r"<!-- item:(\S+) -->")
GH_LIST = ["gh", "issue", "list", "--state", "all", "--limit", "1000",
           "--json", "number,title,body,state,labels"]
Run = Callable[..., Any]


@dataclass
class Item:
    type: str
    id: str
    status: str
    title: str
    why: str = ""
    tags: list[str] = field(default_factory=list)
    links: list[str] = field(default_factory=list)
    source: str = ""
    opened: str = ""
    review_by: str = ""

    @property
    def is_open(self) -> bool:
        return self.status.split()[0].lower() in OPEN if self.status else True


def _links(own: str, *texts: str) -> list[str]:
    return sorted({m for t in texts for m in LINK.findall(t or "")} - {own})


def tickets(path: Path = TICKETS) -> list[Item]:
    out = []
    for line in path.read_text(encoding="utf-8").splitlines() if path.is_file() else []:
        if not line.strip():
            continue
        t = json.loads(line)
        status = str(t.get("status") or "")
        text = " ".join(str(t.get(k) or "") for k in ("title", "why", "close_when", "status", "tail"))
        out.append(Item("ticket", t["id"], status.split()[0].lower() if status else "", t.get("title") or "",
                        t.get("why") or "", [t.get("section") or "", t.get("priority") or ""],
                        sorted(set(_links(t["id"], text)) | set(t.get("links") or [])), "tasks/tickets.jsonl",
                        t.get("opened") or ""))
    return out


def ideas(path: Path = IDEAS) -> list[Item]:
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    out = []
    for block in re.split(r"\n(?=## I-\d{3}:)", text):
        m = re.match(r"## (I-\d{3}): (.+)", block)
        if not m:
            continue

        def field_(name: str) -> str:
            f = re.search(rf"^- {name}[^:]*: (.+)$", block, re.M)
            return f.group(1).strip() if f else ""

        status = field_("Status")
        review = re.search(r"review by (\d{4}-\d{2}-\d{2})", field_("Review trigger"))
        stage = re.search(r"stage `([^`]+)`", field_("Review trigger"))
        created = re.match(r"(\d{4}-\d{2}-\d{2})", field_("Created"))
        out.append(Item("idea", m.group(1), (status.split(":")[0].split()[0].lower() if status else "parked"),
                        m.group(2).strip(), field_("Purpose"), [stage.group(1)] if stage else [],
                        _links(m.group(1), block), "tasks/IDEA_BOX.md", created.group(1) if created else "",
                        review.group(1) if review else ""))
    return out


def rulings(path: Path = RULINGS) -> list[Item]:
    out, section, n = [], "", 0
    for line in (path.read_text(encoding="utf-8").splitlines() if path.is_file() else []):
        if line.startswith("## "):
            section, n = line[3:].strip(), 0
        elif line.startswith("- ") and section:
            n += 1
            key = re.sub(r"[^a-z]+", "-", section.lower()).strip("-")
            dated = re.search(r"\((\d{1,2} \w{3})\)", line)
            out.append(Item("ruling", f"RUL-{key}-{n}", "active", line[2:].strip(), "", [section],
                            _links("", line), "tasks/RULINGS.md", dated.group(1) if dated else ""))
    return out


def defects(path: Path = DEFECTS) -> list[Item]:
    out = []
    for line in path.read_text(encoding="utf-8").splitlines() if path.is_file() else []:
        if not line.strip():
            continue
        n = json.loads(line)
        text = " ".join(str(n.get(k) or "") for k in ("symptom", "cause", "fix", "question"))
        out.append(Item("defect", n["id"], n.get("status") or "", n.get("symptom") or "", n.get("cause") or "",
                        [*(n.get("tags") or []), n.get("part") or "", n.get("scope") or ""], _links(n["id"], text),
                        "tasks/store_repair/notes.jsonl", n.get("opened") or ""))
    return out


def load() -> list[Item]:
    return [*tickets(), *ideas(), *rulings(), *defects()]


def due(items: list[Item], today: str | None = None) -> list[Item]:
    """Ideas whose review date has passed while still parked, and every open store defect."""
    today = today or date.today().isoformat()
    return [i for i in items if (i.type == "idea" and i.is_open and i.review_by and i.review_by <= today)
            or (i.type == "defect" and i.is_open)]


def render(items: list[Item], md: Path = ITEMS_MD, xlsx: Path = ITEMS_XLSX) -> tuple[Path, Path]:
    by_id = {i.id: i for i in items}
    lines = ["# Items (generated by `python -m reality_engine.scripts.items render`; do not edit by hand)", "",
             "Tickets, ideas, rulings and store defects in one place. Each source keeps its own writer; "
             "this file and `reports/items.xlsx` are views.", ""]
    counts = {}
    for i in items:
        counts.setdefault(i.type, [0, 0])[0 if i.is_open else 1] += 1
    lines += ["| type | open | closed |", "|---|---|---|"]
    lines += [f"| {t} | {o} | {c} |" for t, (o, c) in sorted(counts.items())]
    for kind in ("defect", "ticket", "idea"):
        lines += ["", f"## Open {kind}s", ""]
        for i in items:
            if i.type == kind and i.is_open:
                linked = ", ".join(f"{l} ({by_id[l].status})" if l in by_id else l for l in i.links)
                lines.append(f"- **{i.id}** [{i.status}] {i.title[:160]}" + (f" — links: {linked}" if linked else "")
                             + (f" — review by {i.review_by}" if i.review_by else ""))
    md.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    from openpyxl import Workbook
    from openpyxl.styles import Font
    wb = Workbook()
    ws = wb.active
    ws.title = "items"
    cols = ["type", "id", "status", "open", "title", "why", "tags", "links", "opened", "review_by", "source"]
    ws.append(cols)
    for i in items:
        d = asdict(i)
        ws.append([", ".join(x for x in d[c] if x) if isinstance(d.get(c), list) else
                   (i.is_open if c == "open" else d.get(c)) for c in cols])
    for cell in ws[1]:
        cell.font = Font(bold=True)
    ws.auto_filter.ref = ws.dimensions
    for col, width in zip("ABCDEFGHIJK", (8, 18, 12, 6, 80, 50, 26, 26, 11, 11, 30)):
        ws.column_dimensions[col].width = width
    xlsx.parent.mkdir(parents=True, exist_ok=True)
    wb.save(xlsx)
    return md, xlsx


def issue_body(item: Item) -> str:
    """The GitHub issue body for one item: marker line first, then why, tags, links, source and opened."""
    lines = [MARKER.format(id=item.id)]
    if item.why:
        lines += ["", item.why.strip()]
    for label, value in (("Tags", ", ".join(t for t in item.tags if t)), ("Links", ", ".join(item.links)),
                         ("Source", item.source), ("Opened", item.opened)):
        if value:
            lines.append(f"- {label}: {value}")
    return "\n".join(lines) + "\n"


def github_plan(items: list[Item], existing: list[dict]) -> list[dict]:
    """The gh actions that make GitHub mirror the open tickets and defects (pure; no subprocess).

    ``existing`` is the parsed ``gh issue list --state all --json number,title,body,state,labels`` output.
    """
    known: dict[str, dict] = {}  # ponytail: first issue per marker wins; a duplicate marker needs a manual close
    for issue in existing:
        marker = MARKER_RE.search(str(issue.get("body") or ""))
        if marker:
            known.setdefault(marker.group(1), issue)
    actions: list[dict] = []
    open_ids = set()
    for i in items:
        if i.type not in MIRRORED or not i.is_open:
            continue
        open_ids.add(i.id)
        title, body = f"{i.id}: {i.title}"[:200], issue_body(i)
        issue = known.get(i.id)
        if issue is None:
            actions.append({"action": "create", "id": i.id, "title": title, "body": body,
                            "labels": [f"item:{i.type}"]})
            continue
        closed = str(issue.get("state") or "").lower() == "closed"
        if closed or str(issue.get("title") or "") != title \
                or str(issue.get("body") or "").strip() != body.strip():
            edit = {"action": "edit", "id": i.id, "number": issue.get("number"),
                    "title": title, "body": body}
            if closed:
                edit["reopen"] = True
            actions.append(edit)
    for issue in existing:
        marker = MARKER_RE.search(str(issue.get("body") or ""))
        if marker and marker.group(1) not in open_ids \
                and str(issue.get("state") or "").lower() != "closed":
            actions.append({"action": "close", "id": marker.group(1), "number": issue.get("number")})
    return actions


def _gh(args: list[str], run: Run) -> None:
    proc = run(["gh", *args], capture_output=True, text=True)
    code = getattr(proc, "returncode", 0)
    if code:
        print(f"gh {' '.join(args[:2])} exited {code}: "
              f"{(getattr(proc, 'stderr', None) or '').strip()}", file=sys.stderr)


def github_apply(actions: list[dict], run: Run = subprocess.run) -> None:
    """Run the planned gh commands, both labels first.  ``run`` is injectable so tests never touch gh."""
    for label in ("item:ticket", "item:defect"):
        _gh(["label", "create", label, "--force"], run)
    for action in actions:
        number = str(action.get("number"))
        if action["action"] == "create":
            _gh(["issue", "create", "--title", action["title"], "--body", action["body"],
                 "--label", ",".join(action["labels"])], run)
        elif action["action"] == "close":
            _gh(["issue", "close", number], run)
        elif action["action"] == "edit":
            if action.get("reopen"):
                _gh(["issue", "reopen", number], run)
            _gh(["issue", "edit", number, "--title", action["title"], "--body", action["body"]], run)


def github_existing(run: Run = subprocess.run) -> list[dict]:
    """The repo's issues, through the same injectable gh runner the apply step uses."""
    proc = run(GH_LIST, capture_output=True, text=True)
    if getattr(proc, "returncode", 0):
        raise SystemExit(f"gh issue list failed: {(getattr(proc, 'stderr', None) or '').strip()}")
    return json.loads(getattr(proc, "stdout", None) or "[]")


def github(items: list[Item], apply: bool = False, run: Run = subprocess.run) -> int:
    """Print the mirror plan; with ``apply`` also run it.  Dry run by default, never a token read."""
    actions = github_plan(items, github_existing(run))
    for action in actions:
        if action["action"] == "create":
            print(f"create  {action['id']}  {action['title'][:100]}")
        elif action["action"] == "edit":
            verb = "reopen+" if action.get("reopen") else "edit"
            print(f"{verb:<8} #{action['number']}  {action['title'][:100]}")
        else:
            print(f"close   #{action['number']}  {action['id']}")
    if not actions:
        print("GitHub already mirrors every open ticket and defect")
    elif apply:
        github_apply(actions, run)
        print(f"{len(actions)} action(s) applied")
    else:
        print(f"{len(actions)} action(s) pending; dry run, pass --apply to run them")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    ls = sub.add_parser("list")
    ls.add_argument("--type", choices=("ticket", "idea", "ruling", "defect"))
    ls.add_argument("--open", action="store_true")
    sub.add_parser("render")
    sub.add_parser("due")
    gh_cmd = sub.add_parser("github")
    gh_cmd.add_argument("--apply", action="store_true", help="run the gh commands; default is a dry run")
    args = ap.parse_args(argv)
    items = load()
    if args.cmd == "render":
        for p in render(items):
            print(p)
    elif args.cmd == "due":
        for i in due(items):
            print(f"{i.id:<14} {i.type:<7} {i.status:<12} {i.review_by or '-':<11} {i.title[:100]}")
    elif args.cmd == "github":
        return github(items, apply=args.apply)
    else:
        for i in items:
            if (args.type is None or i.type == args.type) and (not args.open or i.is_open):
                print(f"{i.id:<14} {i.type:<7} {i.status:<12} {i.title[:110]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
