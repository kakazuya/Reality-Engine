"""Full, never-trimmed ledgers of the size-limited start files (Shivam, 26 Nov 2026).

The files every session loads (``tasks/RULINGS.md``, ``tasks/STATE.md``, ``AGENTS.md``, ``tasks/TASKS.md``) have
line/character caps (``doc_gate.LINE_LIMITS`` / ``CHAR_LIMITS``), so their wording gets condensed and lines get
dropped.  Shivam: keep two copies - the short one sessions read, and a full one where the exact earlier wording is
always at hand.  Each limited file gets ``docs/ledgers/<NAME>_LEDGER.md``: every line ever added to or removed from
it, with the date, branch and author, appended in order and never edited.

* ``python reality_engine/scripts/doc_ledger.py staged`` (the pre-commit hook on main): appends the staged change of
  each limited file to its ledger and stages the ledger in the same commit.
* ``python -m reality_engine.scripts.doc_ledger backfill``: rebuilds every ledger from git history (oldest first).
"""
from __future__ import annotations

import datetime as dt
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LEDGER_DIR = Path("docs") / "ledgers"
LIMITED = ("tasks/RULINGS.md", "tasks/STATE.md", "AGENTS.md", "tasks/TASKS.md")
HEADER = ("# Full ledger of `{name}` (never trimmed)\n\n"
          "`{name}` is the short copy every session loads; it is condensed to fit its size cap. This file keeps every "
          "line ever added (`+`) or removed (`-`) there, with date, branch and author, oldest first (Shivam, "
          "26 Nov 2026). Earlier full wording of the rulings: `docs/rulings/RULINGS_full_2026-11-08.md`.\n")


def _git(*args: str, root: Path = ROOT) -> str:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", check=False).stdout


def ledger_path(name: str, root: Path = ROOT) -> Path:
    return root / LEDGER_DIR / f"{Path(name).stem}_LEDGER.md"


def _changes(diff: str) -> list[str]:
    out = []
    for line in diff.splitlines():
        if line.startswith(("+++", "---")):
            continue
        if line.startswith(("+", "-")) and line[1:].strip():
            out.append(line)
    return out


def _entry(when: str, who: str, ref: str, lines: list[str]) -> str:
    body = "\n".join(lines)
    return f"\n## {when} | {who} | {ref}\n```diff\n{body}\n```\n"


def _append(name: str, entry: str, root: Path = ROOT) -> Path:
    path = ledger_path(name, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.is_file():
        path.write_text(HEADER.format(name=name), encoding="utf-8")
    with path.open("a", encoding="utf-8") as fh:
        fh.write(entry)
    return path


def staged(root: Path = ROOT) -> list[Path]:
    """Append each limited file's staged change to its ledger and stage the ledger (pre-commit)."""
    names = set(_git("diff", "--cached", "--name-only", root=root).split())
    who = os.environ.get("GIT_AUTHOR_NAME") or _git("config", "user.name", root=root).strip()
    branch = _git("rev-parse", "--abbrev-ref", "HEAD", root=root).strip()
    when = dt.datetime.now().isoformat(timespec="seconds")
    written = []
    for name in LIMITED:
        if name not in names:
            continue
        lines = _changes(_git("diff", "--cached", "-U0", "--", name, root=root))
        if not lines:
            continue
        path = _append(name, _entry(when, who, f"branch {branch}", lines), root)
        _git("add", str(path.relative_to(root)), root=root)
        written.append(path)
    if "tasks/RULINGS.md" in names:      # the readable full copy follows every rulings change
        _git("add", str(full_rulings(root).relative_to(root)), root=root)
    return written


def backfill(root: Path = ROOT) -> dict[str, int]:
    """Rebuild every ledger from git history, oldest commit first."""
    counts = {}
    for name in LIMITED:
        path = ledger_path(name, root)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(HEADER.format(name=name), encoding="utf-8")
        log = _git("log", "--reverse", "--format=%H|%ad|%an|%s", "--date=iso-strict", "--", name, root=root)
        n = 0
        for row in log.splitlines():
            sha, when, who, subject = (row.split("|", 3) + ["", "", "", ""])[:4]
            lines = _changes(_git("show", "--format=", "-U0", sha, "--", name, root=root))
            if lines:
                _append(name, _entry(when, who, f"{sha[:8]} {subject[:100]}", lines), root)
                n += 1
        counts[name] = n
    return counts


FULL_RULINGS = Path("docs") / "rulings" / "RULINGS_FULL.md"
VERBATIM = Path("docs") / "rulings" / "RULINGS_VERBATIM.md"


def full_rulings(root: Path = ROOT) -> Path:
    """docs/rulings/RULINGS_FULL.md: every rule now in force (tasks/RULINGS.md) plus every wording ever removed from
    it that is not in the live file word for word, newest first with the date it was removed."""
    live = (root / "tasks" / "RULINGS.md").read_text(encoding="utf-8")
    live_lines = {l.strip() for l in live.splitlines()}
    removed: list[tuple[str, str]] = []
    seen: set[str] = set()
    log = _git("log", "--format=%H|%ad", "--date=short", "--", "tasks/RULINGS.md", root=root)
    for row in log.splitlines():
        sha, when = (row.split("|", 1) + [""])[:2]
        for line in _changes(_git("show", "--format=", "-U0", sha, "--", "tasks/RULINGS.md", root=root)):
            text = line[1:].strip()
            if line.startswith("-") and text.startswith("- ") and text not in live_lines and text not in seen:
                seen.add(text)
                removed.append((when, text))
    out = ["# Rulings, full wording (never trimmed)", "",
           "`tasks/RULINGS.md` is the short copy loaded into every session (capped at 8,000 characters). This file "
           "holds the same rules in full plus every earlier wording that was condensed or replaced, so the exact "
           "rule as set is always at hand (Shivam, 26 Nov 2026). Shivam's own words: `docs/rulings/RULINGS_VERBATIM.md`."
           " Line-by-line history: `docs/ledgers/RULINGS_LEDGER.md`. Before 8 Nov: `docs/rulings/RULINGS_full_2026-11-08.md`.",
           "", "## In force (as in tasks/RULINGS.md)", "", live.strip(), "",
           "## Earlier wording, condensed or replaced (newest first; check the live rule before applying)", ""]
    out += [f"- [{when}] {text[2:]}" for when, text in removed]
    path = root / FULL_RULINGS
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    cmd = argv[0] if argv else "staged"
    if cmd == "backfill":
        print(backfill())
        print(full_rulings())
    elif cmd == "full-rulings":
        print(full_rulings())
    else:
        staged()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
