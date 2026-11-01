"""Pre-commit gate for the documentation rule (Shivam, 2026-10-31): no undocumented work on main.

A merge on ``main`` must stage ``tasks/STATE.md``.  A code commit on ``main`` must stage a doc.
Worker branches are checked when they merge.  Install with ``python <this file> --install``.
"""

from __future__ import annotations

import re
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


def _needs_doc(name: str) -> bool:
    """Code a doc must name. Tests and package markers describe themselves."""
    return (name.endswith(CODE_SUFFIXES) and not name.startswith(NOT_DOCS) and "/tests/" not in name
            and not Path(name).name.startswith("test_") and Path(name).name != "__init__.py")


def undocumented(code: list[str], doc_text: str) -> list[str]:
    """Code files whose file name appears in none of the given doc text."""
    return [c for c in code if _needs_doc(c) and Path(c).stem not in doc_text]


def check(staged: list[str], *, branch: str, merging: bool, read=lambda name: "") -> str | None:
    """The refusal message for this commit, or None when it may go ahead.

    Shivam, 2026-11-01: no merge without docs. Every changed code file must be named in a doc
    changed by the same commit, and tasks/STATE.md alone does not count on a merge.
    """
    if branch != "main":
        return None
    if merging and STATE not in staged:
        return f"merge on main without {STATE}: put the current state in it"
    docs = [n for n in staged if n.endswith(".md") and not n.startswith(NOT_DOCS) and not (merging and n == STATE)]
    missing = undocumented(staged, "\n".join(read(n) for n in docs))
    if missing:
        return "code not named in any doc in this commit, update the doc that describes it: " + ", ".join(missing[:15])
    return None


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=False, encoding="utf-8", errors="replace").stdout.strip()


def sweep(root: Path) -> int:
    """Session-close check: code changed since the last sweep with no doc naming it, and doc paths that no longer exist."""
    marker = root / "tasks" / ".doc_sweep_head"
    head = _git("rev-parse", "HEAD")
    since = marker.read_text(encoding="utf-8").strip() if marker.exists() else "HEAD~30"
    changed = _git("diff", "--name-only", since, "HEAD").splitlines() + _git("status", "--porcelain").splitlines()
    changed = sorted({c[3:] if c[:2].strip() and c[2:3] == " " else c for c in changed})
    live = [n for n in _git("ls-files", "*.md").splitlines() if not n.startswith(NOT_DOCS)]
    text = {n: (root / n).read_text(encoding="utf-8", errors="ignore") for n in live if (root / n).exists()}
    missing = undocumented([c for c in changed if (root / c).exists()], "\n".join(text.values()))
    broken = []
    for name, body in text.items():
        for ref in set(re.findall(r"`((?:reality_engine|tasks|plugins)/[\w./-]+\.\w+)`", body)):
            if not (root / ref).exists():
                broken.append(f"{name}: {ref}")
    print(f"code changed since {since[:8]} and named in no doc: {len(missing)}")
    print("\n".join("  " + m for m in missing))
    print(f"doc references to files that do not exist: {len(broken)}")
    print("\n".join("  " + b for b in sorted(broken)[:60]))
    if not missing and not broken:
        marker.write_text(head + "\n", encoding="utf-8")
    return 1 if missing or broken else 0


def main(argv: list[str]) -> int:
    if "--sweep" in argv:
        return sweep(Path(_git("rev-parse", "--show-toplevel")))
    if "--install" in argv:
        hooks = Path(_git("rev-parse", "--git-common-dir")) / "hooks"
        hooks.mkdir(exist_ok=True)
        (hooks / "pre-commit").write_text(HOOK, encoding="utf-8", newline="\n")
        print(f"installed {hooks / 'pre-commit'}")
        return 0
    message = check(_git("diff", "--cached", "--name-only").splitlines(),
                    branch=_git("rev-parse", "--abbrev-ref", "HEAD"),
                    merging=Path(_git("rev-parse", "--git-path", "MERGE_HEAD")).exists(),
                    read=lambda name: _git("show", f":{name}"))
    if message:
        print(f"doc_gate: {message}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
