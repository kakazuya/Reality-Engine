"""The ticket tracker: one cheap card per session, linted at commit and at worker start.

Rows live in ``tasks/TASKS.md`` (open work, one row per line, kept in its section) and
``tasks/TASKS_DONE.md`` (closed work).  The id is the maximum across both files plus one,
allocated under a file lock so two accounts sharing the checkout cannot collide.
Shivam approved this design on 2026-11-01.

    python -m reality_engine.scripts.task_board add --section Data --title ... --accept "..."
    python -m reality_engine.scripts.task_board set T-014 DOING Wolf
    python -m reality_engine.scripts.task_board done T-014
    python -m reality_engine.scripts.task_board drop T-014 "merged into T-012"
    python -m reality_engine.scripts.task_board list [--section S] [--status DOING]
    python -m reality_engine.scripts.task_board card
    python -m reality_engine.scripts.task_board export tasks.xlsx
    python -m reality_engine.scripts.task_board lint
"""

from __future__ import annotations

import argparse
import contextlib
import datetime
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LIVE_RELATIVE = Path("tasks") / "TASKS.md"
DONE_RELATIVE = Path("tasks") / "TASKS_DONE.md"
LOCK_RELATIVE = Path(".tmp") / "task_board.lock"
SECTIONS = (
    "Workspace",
    "Data",
    "OCR and extraction",
    "Schema and question map",
    "Bank",
    "Research",
    "Machines",
)
PRIORITIES = ("P1", "P2", "P3")
OPEN_STATUSES = ("OPEN", "LOOKING", "DOING", "WAITING")
CARD_LIMIT = 600
STALE_DAYS = 3
ROW_ID = re.compile(r"^T-\d+$")
OPENED = re.compile(r"^opened (\d{4}-\d{2}-\d{2})$")
DONE_MARK = re.compile(r"^done ([0-9a-f]{7,}) (\d{4}-\d{2}-\d{2})$")
DROPPED_MARK = re.compile(r"^dropped \d{4}-\d{2}-\d{2}$")
TICKET_IN_MESSAGE = re.compile(r"\bT-\d+\b")
NO_TICKET_IN_MESSAGE = re.compile(r"(?im)^\s*No-ticket:\s*\S")


class BoardError(Exception):
    """A refused board operation; the message is printed and the exit code is 1."""


@dataclass
class Row:
    id: str
    status: str
    priority: str
    title: str
    accept: str
    source: str
    opened: str
    tail: str = ""
    section: str = ""

    @property
    def word(self) -> str:
        return self.status.split(" ", 1)[0].upper()

    @property
    def owner(self) -> str:
        return self.status.split(" ", 1)[1].strip() if " " in self.status else ""

    def line(self) -> str:
        return (f"- {self.id} | {self.status} | {self.priority} | {self.title} | "
                f"accept: {self.accept} | from: {self.source} | opened {self.opened}"
                + (f" | {self.tail}" if self.tail else ""))


def _today() -> str:
    return datetime.date.today().isoformat()


def _path(root: Path | None, relative: Path) -> Path:
    return Path(root) / relative if root is not None else ROOT / relative


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise BoardError(f"{path} cannot be read: {exc}") from exc


def _plain(value: str, name: str) -> str:
    """A field value must fit on one row: no pipe, no newline, not empty."""
    text = (value or "").strip()
    if not text:
        raise BoardError(f"{name} must not be empty")
    if "|" in text:
        raise BoardError(f"{name} must not contain '|': pipes separate the row fields")
    if "\n" in text or "\r" in text:
        raise BoardError(f"{name} must be one line")
    return text


def parse_row(line: str, *, done_file: bool = False) -> Row:
    """Parse one row, raising BoardError with the reason when it is malformed."""
    body = line[2:] if line.startswith("- ") else line
    parts = [part.strip() for part in body.split(" | ")]
    if len(parts) not in (7, 8):
        raise BoardError(f"expected 7 fields, found {len(parts)}")
    for part in parts:
        if "|" in part:
            raise BoardError(f"field contains '|': {part[:60]}")
    row_id, status, priority, title, accept, source, opened = parts[:7]
    if not ROW_ID.match(row_id):
        raise BoardError(f"id {row_id!r} is not T-<digits>")
    if priority not in PRIORITIES:
        raise BoardError(f"priority {priority!r} is not one of {', '.join(PRIORITIES)}")
    if not title:
        raise BoardError("title is empty")
    if not accept.startswith("accept: ") or not accept[8:].strip():
        raise BoardError("accept field must be 'accept: <command or Shivam>'")
    if not source.startswith("from: ") or not source[6:].strip():
        raise BoardError("from field must be 'from: <source>'")
    if not OPENED.match(opened):
        raise BoardError("opened field must be 'opened YYYY-MM-DD'")
    word, _, owner = status.partition(" ")
    if done_file:
        # A reason-less DROPPED row parses here so lint can name the defect.
        if word not in ("DONE", "DROPPED"):
            raise BoardError("a done-file row must be DONE or DROPPED <reason>")
    elif word in ("OPEN", "LOOKING") and not owner:
        pass
    elif word in ("DOING", "WAITING") and owner:
        pass
    elif (word == "DONE" and not owner) or (word == "DROPPED" and owner):
        # Parses so lint can say "move it to TASKS_DONE.md"; the commit gate refuses it.
        pass
    else:
        raise BoardError("status must be OPEN, LOOKING, DOING <owner> or WAITING <who>")
    tail = parts[7] if len(parts) == 8 else ""
    if tail and not (DONE_MARK.match(tail) or DROPPED_MARK.match(tail)):
        raise BoardError(f"trailing field {tail!r} is not 'done <hash> <date>' or 'dropped <date>'")
    return Row(row_id, status, priority, title, accept[8:].strip(), source[6:].strip(),
               OPENED.match(opened).group(1), tail)


def load_rows(root: Path | None = None) -> tuple[list[Row], list[Row]]:
    """Every parsed row: (live rows with their section, done-file rows)."""
    live: list[Row] = []
    section = ""
    for number, line in enumerate(_read(_path(root, LIVE_RELATIVE)).splitlines(), 1):
        if line.startswith("## "):
            section = line[3:].strip()
            continue
        if line.startswith("- "):
            try:
                row = parse_row(line)
            except BoardError as exc:
                raise BoardError(f"{LIVE_RELATIVE}:{number}: malformed row ({exc}): {line[:80]}") from exc
            if not section:
                raise BoardError(f"{LIVE_RELATIVE}:{number}: row outside a '## ' section")
            row.section = section
            live.append(row)
    done: list[Row] = []
    done_path = _path(root, DONE_RELATIVE)
    if done_path.exists():
        for number, line in enumerate(_read(done_path).splitlines(), 1):
            if line.startswith("- "):
                try:
                    done.append(parse_row(line, done_file=True))
                except BoardError as exc:
                    raise BoardError(f"{DONE_RELATIVE}:{number}: malformed row ({exc}): {line[:80]}") from exc
    return live, done


def lint_problems(root: Path | None = None) -> list[str]:
    """Every defect in the two tracker files, in the order the commit gate prints them."""
    problems: list[str] = []
    try:
        live, done = load_rows(root)
    except BoardError as exc:
        return [str(exc)]
    seen: dict[str, str] = {}
    for row, where in [(row, LIVE_RELATIVE.as_posix()) for row in live] + [
        (row, DONE_RELATIVE.as_posix()) for row in done
    ]:
        if row.id in seen:
            problems.append(f"{row.id} appears in both {seen[row.id]} and {where}")
        else:
            seen[row.id] = where
    for row in live:
        if row.word in ("DONE", "DROPPED"):
            problems.append(f"{row.id} is {row.word} in {LIVE_RELATIVE}; move it to {DONE_RELATIVE}")
    for row in done:
        if row.word == "DONE" and not DONE_MARK.match(row.tail):
            problems.append(f"{row.id} is DONE with no commit hash ('done <hash> <date>')")
        if row.word == "DROPPED" and not row.owner:
            problems.append(f"{row.id} is DROPPED with no reason")
    return problems


@contextlib.contextmanager
def file_lock(root: Path | None = None):
    """Exclusive cross-process lock for one id allocation / row move."""
    path = _path(root, LOCK_RELATIVE)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a+b") as handle:
        if os.name == "nt":
            import msvcrt

            if handle.seek(0, os.SEEK_END) == 0:
                handle.write(b"x")
                handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _next_id(live: list[Row], done: list[Row]) -> str:
    highest = max((int(row.id[2:]) for row in live + done), default=0)
    return f"T-{highest + 1:03d}"


def _insert(text: str, section: str, line: str) -> str:
    lines = text.splitlines()
    start = next((i for i, item in enumerate(lines) if item.strip() == f"## {section}"), None)
    if start is None:
        raise BoardError(f"{LIVE_RELATIVE} has no '## {section}' section; the sections are: "
                         + ", ".join(SECTIONS))
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    last_row = max((i for i in range(start + 1, end) if lines[i].startswith("- ")), default=start)
    lines.insert(last_row + 1, line)
    return "\n".join(lines).rstrip("\n") + "\n"


def _remove(text: str, row: Row) -> str:
    needle = row.line()
    lines = text.splitlines()
    if needle not in lines:
        raise BoardError(f"row changed while it was being closed: {needle[:80]}")
    lines.remove(needle)
    return "\n".join(lines).rstrip("\n") + "\n"


def _append_done(row: Row, root: Path | None) -> None:
    path = _path(root, DONE_RELATIVE)
    text = _read(path)
    path.write_text(text.rstrip("\n") + "\n" + row.line() + "\n", encoding="utf-8")


def add(*, section: str, title: str, accept: str, source: str = "manual",
        priority: str = "P2", status: str = "OPEN", root: Path | None = None) -> str:
    """Append one open row to its section and return the new id."""
    section = _plain(section, "section")
    title = _plain(title, "title")
    accept = _plain(accept, "accept")
    source = _plain(source, "from")
    priority = _plain(priority, "priority")
    if priority not in PRIORITIES:
        raise BoardError(f"priority must be one of {', '.join(PRIORITIES)}")
    status = " ".join(_plain(status, "status").split())
    word, _, owner = status.partition(" ")
    if word.upper() not in OPEN_STATUSES or (word.upper() in ("DOING", "WAITING") and not owner):
        raise BoardError("status must be OPEN, LOOKING, DOING <owner> or WAITING <who>")
    status = word.upper() + (f" {owner}" if owner else "")
    with file_lock(root):
        live, done = load_rows(root)
        row = Row(_next_id(live, done), status, priority, title, accept, source, _today(), section=section)
        live_path = _path(root, LIVE_RELATIVE)
        live_path.write_text(_insert(_read(live_path), section, row.line()), encoding="utf-8")
    return row.id


def _find(live: list[Row], row_id: str) -> Row:
    for row in live:
        if row.id == row_id:
            return row
    raise BoardError(f"{row_id} is not an open row in {LIVE_RELATIVE}")


def set_status(row_id: str, status: str, owner: str | None = None,
               root: Path | None = None) -> None:
    """Change a live row's status, keeping it in its section."""
    word = status.strip().upper()
    if word not in OPEN_STATUSES:
        raise BoardError(f"status must be one of {', '.join(OPEN_STATUSES)}")
    if word in ("DOING", "WAITING") and not (owner or "").strip():
        raise BoardError(f"{word} needs an owner or who is waited on")
    if word not in ("DOING", "WAITING") and (owner or "").strip():
        raise BoardError(f"{word} takes no owner")
    new = word + (f" {_plain(owner, 'owner')}" if (owner or "").strip() else "")
    with file_lock(root):
        live, _done = load_rows(root)
        row = _find(live, row_id)
        live_path = _path(root, LIVE_RELATIVE)
        text = _read(live_path)
        updated = row.line().replace(f"| {row.status} |", f"| {new} |", 1)
        live_path.write_text(text.replace(row.line(), updated), encoding="utf-8")


def _head(root: Path | None) -> str:
    out = _git(root, "rev-parse", "--short", "HEAD")
    # ponytail: a copy of the tracker outside git (tests, an export dir) records 0000000
    return out.strip() or "0000000"


def done(row_id: str, *, shivam: bool = False, timeout: float = 900.0,
         root: Path | None = None) -> str:
    """Run the row's accept command; on success move it to TASKS_DONE.md with HEAD's hash."""
    live, _done_rows = load_rows(root)
    row = _find(live, row_id)
    if row.accept.strip().lower() == "shivam":
        if not shivam:
            raise BoardError(f"{row_id} closes only with 'done {row_id} --shivam' (accept: Shivam)")
    else:
        try:
            result = subprocess.run(row.accept, shell=True, cwd=str(root or ROOT),
                                    capture_output=True, text=True, encoding="utf-8",
                                    errors="replace", timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            raise BoardError(f"{row_id} accept command timed out after {timeout:g}s: {row.accept}") from exc
        except OSError as exc:
            raise BoardError(f"{row_id} accept command could not run: {exc}") from exc
        if result.returncode != 0:
            tail = (result.stdout + result.stderr).strip().splitlines()[-20:]
            raise BoardError(f"{row_id} accept command exited {result.returncode}; last 20 lines:\n"
                             + "\n".join(tail))
    with file_lock(root):
        live, _done_rows = load_rows(root)
        row = _find(live, row_id)
        live_path = _path(root, LIVE_RELATIVE)
        live_path.write_text(_remove(_read(live_path), row), encoding="utf-8")
        _append_done(Row(row.id, "DONE", row.priority, row.title, row.accept, row.source,
                         row.opened, f"done {_head(root)} {_today()}"), root)
    return row_id


def drop(row_id: str, reason: str, root: Path | None = None) -> None:
    """Close a row without running anything; the reason is required."""
    reason = _plain(reason, "reason")
    with file_lock(root):
        live, _done_rows = load_rows(root)
        row = _find(live, row_id)
        live_path = _path(root, LIVE_RELATIVE)
        live_path.write_text(_remove(_read(live_path), row), encoding="utf-8")
        _append_done(Row(row.id, f"DROPPED {reason}", row.priority, row.title, row.accept,
                         row.source, row.opened, f"dropped {_today()}"), root)


def _git(root: Path | None, *args: str) -> str:
    try:
        completed = subprocess.run(["git", "-C", str(root or ROOT), *args], capture_output=True,
                                   text=True, encoding="utf-8", errors="replace", timeout=10)
    except (OSError, subprocess.SubprocessError):
        return ""
    return completed.stdout if completed.returncode == 0 else ""


def _untracked_commits(root: Path | None) -> int:
    last = _git(root, "log", "-1", "--format=%H", "--", LIVE_RELATIVE.as_posix(),
                DONE_RELATIVE.as_posix()).strip()
    if not last:
        return 0
    messages = [m for m in _git(root, "log", "--format=%B%x00", f"{last}..HEAD").split("\x00") if m.strip()]
    return sum(1 for message in messages
               if not TICKET_IN_MESSAGE.search(message) and not NO_TICKET_IN_MESSAGE.search(message))


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 3] + "..."


def card(root: Path | None = None) -> str:
    """At most 600 characters: what is open, moving, blocked and stale. Never raises."""
    try:
        live, _done_rows = load_rows(root)
        counts = ", ".join(
            f"{name} {sum(1 for row in live if row.section == name)}" for name in SECTIONS
        )
        lines = [_clip(f"OPEN {len(live)}: {counts}", 150)]
        doing = [row for row in live if row.word == "DOING"]
        if doing:
            lines.append(_clip("DOING: " + ", ".join(f"{row.id} {row.title}" for row in doing), 90))
        waiting = [row for row in live if row.word == "WAITING" and row.owner.lower() == "shivam"]
        if waiting:
            lines.append(_clip("WAITING Shivam: " + ", ".join(row.id for row in waiting), 90))
    except BoardError as exc:
        return _clip(f"task card unavailable: {exc}", CARD_LIMIT)
    today = datetime.date.today()
    stale = []
    for row in live:
        try:
            age = (today - datetime.date.fromisoformat(row.opened)).days
        except ValueError:
            continue
        if age > STALE_DAYS:
            stale.append(row.id)
    if stale:
        lines.append(_clip("Stale >3d: " + ", ".join(stale), 90))
    untracked = _untracked_commits(root)
    if untracked:
        lines.append(_clip(f"Commits with no ticket since tracker change: {untracked}", 90))
    lines.append("More: python -m reality_engine.scripts.task_board list")
    return "\n".join(lines)[:CARD_LIMIT]


def export(path: str, root: Path | None = None) -> int:
    """Write both files' rows to one sheet with openpyxl and return the row count."""
    from openpyxl import Workbook

    live, done = load_rows(root)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Tickets"
    sheet.append(["id", "status", "priority", "title", "accept", "from", "opened",
                  "closing", "section", "file"])
    for row in live:
        sheet.append([row.id, row.status, row.priority, row.title, row.accept, row.source,
                      row.opened, row.tail, row.section, LIVE_RELATIVE.as_posix()])
    for row in done:
        sheet.append([row.id, row.status, row.priority, row.title, row.accept, row.source,
                      row.opened, row.tail, row.section, DONE_RELATIVE.as_posix()])
    workbook.save(path)
    return len(live) + len(done)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m reality_engine.scripts.task_board")
    commands = parser.add_subparsers(dest="command", required=True)
    add_cmd = commands.add_parser("add", help="append an open row and print its id")
    add_cmd.add_argument("--section", required=True, choices=SECTIONS)
    add_cmd.add_argument("--title", required=True)
    add_cmd.add_argument("--accept", required=True)
    add_cmd.add_argument("--from", dest="source", default="manual")
    add_cmd.add_argument("--priority", default="P2", choices=PRIORITIES)
    add_cmd.add_argument("--status", default="OPEN")
    set_cmd = commands.add_parser("set", help="change a row's status")
    set_cmd.add_argument("id")
    set_cmd.add_argument("status")
    set_cmd.add_argument("owner", nargs="?")
    done_cmd = commands.add_parser("done", help="run the accept check and close the row")
    done_cmd.add_argument("id")
    done_cmd.add_argument("--shivam", action="store_true", help="Shivam confirms an accept: Shivam row")
    done_cmd.add_argument("--timeout", type=float, default=900.0)
    drop_cmd = commands.add_parser("drop", help="close a row with a reason")
    drop_cmd.add_argument("id")
    drop_cmd.add_argument("reason")
    list_cmd = commands.add_parser("list", help="print rows")
    list_cmd.add_argument("--section", choices=SECTIONS)
    list_cmd.add_argument("--status")
    commands.add_parser("card", help="print the at-most-600-character session card")
    export_cmd = commands.add_parser("export", help="write both files' rows to one .xlsx sheet")
    export_cmd.add_argument("path")
    commands.add_parser("lint", help="print every tracker defect")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "add":
            print(add(section=args.section, title=args.title, accept=args.accept,
                      source=args.source, priority=args.priority, status=args.status))
        elif args.command == "set":
            set_status(args.id, args.status, args.owner)
        elif args.command == "done":
            done(args.id, shivam=args.shivam, timeout=args.timeout)
        elif args.command == "drop":
            drop(args.id, args.reason)
        elif args.command == "list":
            live, done_rows = load_rows()
            for row in live + done_rows:
                if args.section and row.section != args.section:
                    continue
                if args.status and row.word != args.status.upper():
                    continue
                print(row.line())
        elif args.command == "card":
            print(card())
        elif args.command == "export":
            print(f"wrote {export(args.path)} rows to {args.path}")
        elif args.command == "lint":
            problems = lint_problems()
            for problem in problems:
                print(problem)
            print(f"tracker lint: {len(problems)} problem(s)")
            return 1 if problems else 0
    except BoardError as exc:
        print(f"task_board: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
