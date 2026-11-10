"""Intake for Shivam's rulings: one command records the rule, the sheet and the gate ticket (T-127).

    python -m reality_engine.scripts.ruling add --section "<RULINGS section>" --text "<rule>" \
        [--check "<gate tag>"] [--ticket-title "<gate to build>"]
    python -m reality_engine.scripts.ruling list

``add`` appends ``- <text> [check: <tag>]`` as the last bullet of its section and refuses,
without writing, when the file would go over ``doc_gate``'s limits for it.  A rule with no
``[check: ...]`` tag relies on the model, so ``add`` opens a ticket to build its gate.  The
standing-rules sheet (``D:\\RealityEngine\\reports\\standing_rules.xlsx`` and ``.html``) is
rewritten afterwards; a locked Excel file is a warning, never a failed ruling.

``list`` prints the sections with their bullet count and the characters and lines left.
"""
from __future__ import annotations

import argparse
import datetime
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
RULINGS = Path("tasks") / "RULINGS.md"
NAME = RULINGS.as_posix()
ACCEPT = "Shivam: standing_rules.xlsx shows a code gate for it"
CLOSE_WHEN = "standing_rules.xlsx shows a code gate for it"


def _limits() -> tuple[int, int]:
    """The RULINGS character and line caps, from the one place the hook reads them."""
    from reality_engine.scripts.doc_gate import CHAR_LIMITS, LINE_LIMITS

    return CHAR_LIMITS[NAME], LINE_LIMITS[NAME]


def _insert(text: str, section: str, bullet: str) -> str:
    lines = text.splitlines()
    start = next((i for i, line in enumerate(lines) if line.strip() == f"## {section}"), None)
    if start is None:
        names = [line[3:].strip() for line in lines if line.startswith("## ")]
        raise ValueError(f"{RULINGS} has no '## {section}' section; the sections are: "
                         + ", ".join(names))
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    last = max((i for i in range(start + 1, end) if lines[i].startswith("- ")), default=start)
    lines.insert(last + 1, bullet)
    return "\n".join(lines).rstrip("\n") + "\n"


def add(*, section: str, text: str, check: str | None = None, ticket_title: str | None = None,
        root: Path | None = None) -> dict[str, Any]:
    """Append one ruling; open a gate ticket when it has no ``[check: ...]``; refresh the sheet."""
    root = Path(root) if root is not None else ROOT
    path = root / RULINGS
    try:
        before = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"{path} cannot be read: {exc}") from exc
    rule = " ".join(text.split())
    if not rule:
        raise ValueError("--text is empty")
    tag = (check or "").strip()
    bullet = f"- {rule}" + (f" [check: {tag}]" if tag else "")
    after = _insert(before, section.strip(), bullet)
    char_limit, line_limit = _limits()
    chars, lines = len(after), len(after.splitlines())
    over = []
    if chars > char_limit:
        over.append(f"{chars - char_limit} characters over {char_limit}")
    if lines > line_limit:
        over.append(f"{lines - line_limit} lines over {line_limit}")
    if over:
        raise ValueError(f"{RULINGS} would go over its limit by " + " and ".join(over)
                         + ": shorten the rule or move detail to docs/ or a dated record")
    path.write_text(after, encoding="utf-8")

    ticket = None
    if not tag:
        from reality_engine.scripts import task_board

        title = (ticket_title or f"Gate for ruling: {rule[:120]}").strip()
        why = (f"ruling add on {datetime.date.today().isoformat()}: '{rule[:120]}' was appended "
               "to tasks/RULINGS.md without a [check: ...] tag")
        ticket = task_board.add(section="Workspace", title=title, accept=ACCEPT,
                                why=why, close_when=CLOSE_WHEN, allow_rule_title=True,
                                source="ruling intake", root=root)
    return {"chars_left": char_limit - chars, "lines_left": line_limit - lines,
            "ticket": ticket, "sheet": _regenerate()}


def _regenerate() -> str | None:
    """Rewrite the standing-rules sheet; never fails the ruling on a locked or missing xlsx."""
    try:
        from reality_engine.scripts import standing_rules_report

        out_dir = os.environ.get("REALITY_REPORTS_DIR")
        return standing_rules_report.write(Path(out_dir) if out_dir else None)[0]
    except Exception as exc:  # a locked Excel file, no openpyxl, an unwritable reports dir
        print(f"ruling: warning: the standing-rules sheet was not rewritten: {exc}",
              file=sys.stderr)
        return None


def summary(root: Path | None = None) -> str:
    """Rulings per section, then the characters and lines left under the caps."""
    from reality_engine.scripts import project_context

    path = (Path(root) if root is not None else ROOT) / RULINGS
    text = path.read_text(encoding="utf-8")
    items = project_context.sections(text)
    counts: dict[str, int] = {}
    for item in items:
        counts[item["section"]] = counts.get(item["section"], 0) + 1
    char_limit, line_limit = _limits()
    lines = len(text.splitlines())
    head = (f"{RULINGS}: {len(items)} rulings in {len(counts)} sections; "
            f"{char_limit - len(text):,} characters left (limit {char_limit:,}), "
            f"{line_limit - lines:,} lines left (limit {line_limit:,})")
    return "\n".join([head] + [f"## {name}: {count} bullet{'s' if count != 1 else ''}"
                               for name, count in counts.items()])


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ruling",
                                     description=(__doc__ or "ruling intake").splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    add_cmd = sub.add_parser("add", help="append one ruling and keep the sheet in step")
    add_cmd.add_argument("--section", required=True, help="a '## ' section of tasks/RULINGS.md")
    add_cmd.add_argument("--text", required=True, help="the rule, one sentence")
    add_cmd.add_argument("--check", default=None, help="the gate tag in standing_rules_report.CODE_GATES")
    add_cmd.add_argument("--ticket-title", default=None, help="the gate ticket's title")
    sub.add_parser("list", help="rulings per section and the space left")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "list":
            print(summary())
            return 0
        result = add(section=args.section, text=args.text, check=args.check,
                     ticket_title=args.ticket_title)
    except Exception as exc:
        print(f"ruling: {exc}", file=sys.stderr)
        return 1
    print(f"added to {RULINGS}: {result['chars_left']:,} characters and "
          f"{result['lines_left']} lines left")
    if result["ticket"]:
        print(f"opened {result['ticket']}: build a code gate for this ruling")
    if result["sheet"]:
        print(f"rewrote {result['sheet']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
