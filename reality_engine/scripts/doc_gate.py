"""Pre-commit gate for the documentation rule (Shivam, 2026-10-31): no undocumented work on main.

A merge on ``main`` must stage ``tasks/STATE.md``.  A code commit on ``main`` must stage a doc.
Worker branches are checked when they merge.  Install with ``python <this file> --install``.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

STATE = "tasks/STATE.md"
CODE_SUFFIXES = (".py", ".sql")
#: briefs say what to do, not what is true, so they do not count as documentation
NOT_DOCS = ("tasks/dsh_tasks/", "tasks/archive/")
#: a worker worktree may predate this file, so the hook only calls it on main
HOOK = """#!/bin/sh
[ "$(git rev-parse --abbrev-ref HEAD)" = main ] || exit 0
exec python "$(git rev-parse --show-toplevel)/reality_engine/scripts/doc_gate.py"
"""


def check(staged: list[str], *, branch: str, merging: bool) -> str | None:
    """The refusal message for this commit, or None when it may go ahead."""
    if branch != "main":
        return None
    if merging:
        if STATE not in staged:
            return f"merge on main without {STATE}: put the current state in it"
        return None
    has_code = any(name.endswith(CODE_SUFFIXES) for name in staged)
    has_doc = any(name.endswith(".md") and not name.startswith(NOT_DOCS) for name in staged)
    if has_code and not has_doc:
        return "code commit on main with no doc: update the docs that describe this work"
    return None


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=False).stdout.strip()


def main(argv: list[str]) -> int:
    if "--install" in argv:
        hooks = Path(_git("rev-parse", "--git-common-dir")) / "hooks"
        hooks.mkdir(exist_ok=True)
        (hooks / "pre-commit").write_text(HOOK, encoding="utf-8", newline="\n")
        print(f"installed {hooks / 'pre-commit'}")
        return 0
    message = check(_git("diff", "--cached", "--name-only").splitlines(),
                    branch=_git("rev-parse", "--abbrev-ref", "HEAD"),
                    merging=Path(_git("rev-parse", "--git-path", "MERGE_HEAD")).exists())
    if message:
        print(f"doc_gate: {message}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
