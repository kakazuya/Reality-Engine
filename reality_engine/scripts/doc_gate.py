"""Gates for the documentation and ticket rules (Shivam, 2026-10-31 and 2026-11-01).

A merge on ``main`` must stage ``tasks/STATE.md``.  A code commit on ``main`` must stage a doc
naming it.  A commit that stages a tracker file is linted like ``task_board lint``.  A commit
message on ``main`` must name a ticket (``T-<digits>``) or say why it has none
(``No-ticket: <reason>``).  Worker branches are checked when they merge: a merge of a
``dsh/<job_id>`` branch needs a review row for that job, and a merge that adds code with a new
top-level ``def`` needs a staged test (T-127).

Every pre-commit and commit-msg pass or block is appended to the rule ledger
(``tasks/efficiency/rule_events.jsonl``, see ``rule_ledger.py``); logging never changes a
gate result.  Install with ``python <this file> --install``.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

STATE = "tasks/STATE.md"
TRACKERS = ("tasks/TASKS.md", "tasks/TASKS_DONE.md")
# Start files stay short so every session begins small (Shivam, 2026-11-01).
LINE_LIMITS = {STATE: 40, "AGENTS.md": 150, "tasks/RULINGS.md": 40, "tasks/TASKS.md": 150}
# The two files the session-start hook prints also have a character budget (T-125): a 40-line
# STATE.md is still 33k characters when each line is a paragraph.
CHAR_LIMITS = {STATE: 4000, "tasks/RULINGS.md": 8000}
CODE_SUFFIXES = (".py", ".sql")
#: one JSON object per line; ``id`` is the job id of a reviewed worker (T-127)
REVIEWS = "tasks/efficiency/worker_reviews.jsonl"
DSH_BRANCH = "dsh/"
#: briefs say what to do, not what is true, so they do not count as documentation
NOT_DOCS = ("tasks/dsh_tasks/", "tasks/archive/")
TICKET = re.compile(r"\bT-\d+\b")
NO_TICKET = re.compile(r"(?im)^\s*No-ticket:\s*\S")
#: a worker worktree may predate this file, so the hook only calls it on main
HOOK = """#!/bin/sh
[ "$(git rev-parse --abbrev-ref HEAD)" = main ] || exit 0
exec python "$(git rev-parse --show-toplevel)/reality_engine/scripts/doc_gate.py"
"""
#: Shivam, 8 Nov: his Excel ticket board and standing-rules sheet follow every main commit that changes their source
HOOK_POST = """#!/bin/sh
[ "$(git rev-parse --abbrev-ref HEAD)" = main ] || exit 0
changed=$(git diff-tree --no-commit-id --name-only -r HEAD)
top=$(git rev-parse --show-toplevel)
echo "$changed" | grep -q '^tasks/TASKS' && python "$top/reality_engine/scripts/ticket_board_report.py" >/dev/null
echo "$changed" | grep -q '^tasks/RULINGS.md' && python "$top/reality_engine/scripts/standing_rules_report.py" >/dev/null
exit 0
"""
HOOK_MESSAGE = """#!/bin/sh
[ "$(git rev-parse --abbrev-ref HEAD)" = main ] || exit 0
exec python "$(git rev-parse --show-toplevel)/reality_engine/scripts/doc_gate.py" --commit-msg "$1"
"""


def _needs_doc(name: str) -> bool:
    """Code a doc must name. Tests and package markers describe themselves."""
    return (name.endswith(CODE_SUFFIXES) and not name.startswith(NOT_DOCS) and "/tests/" not in name
            and not Path(name).name.startswith("test_") and Path(name).name != "__init__.py")


def undocumented(code: list[str], doc_text: str) -> list[str]:
    """Code files whose file name appears in none of the given doc text."""
    return [c for c in code if _needs_doc(c) and Path(c).stem not in doc_text]


def tracker_problem(staged: list[str], root: Path | None = None) -> str | None:
    """The tracker lint refusal for this commit, or None when neither tracker is staged."""
    if not any(name in staged for name in TRACKERS):
        return None
    root = root or Path(__file__).resolve().parents[2]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from reality_engine.scripts import task_board

    problems = task_board.lint_problems(root, include_advisory=False)
    return "tracker lint failed: " + "; ".join(problems[:10]) if problems else None


def _review_ids(text: str) -> set[str]:
    """Every job id in a reviews file; a bad line is skipped, never raised."""
    ids: set[str] = set()
    for line in text.splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and isinstance(row.get("id"), str):
            ids.add(row["id"].strip())
    return ids


def worker_review_problem(merge_branch: str | None, staged: list[str], read,
                          root: Path | None = None) -> str | None:
    """A merge of ``dsh/<job_id>`` needs that job's review row (T-127); other merges pass."""
    if not merge_branch or not merge_branch.startswith(DSH_BRANCH):
        return None
    job_id = merge_branch[len(DSH_BRANCH):].strip()
    if not job_id:
        return None
    text = read(REVIEWS) if REVIEWS in staged else ""
    if not text.strip():
        root = root or Path(__file__).resolve().parents[2]
        try:
            text = (root / REVIEWS).read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return (f"merge of {merge_branch} without a worker review row in {REVIEWS} "
                    f"(the file cannot be read: {exc})")
    if job_id in _review_ids(text):
        return None
    return f"merge of {merge_branch} without a worker review row in {REVIEWS}"


def _is_test_file(name: str) -> bool:
    return name.endswith(".py") and ("/tests/" in name.replace("\\", "/")
                                    or Path(name).name.startswith("test_"))


def merge_tests_problem(staged: list[str], added: str | None) -> str | None:
    """A merge that adds code and a top-level ``def`` needs a staged test (T-127).

    ``added`` is the staged diff's added lines; ``None`` means the diff was not supplied, so a
    pure fix cannot be proven and the merge is refused.
    """
    code = [n for n in staged if n.endswith(".py") and not _is_test_file(n)]
    if not code or any(_is_test_file(n) for n in staged):
        return None
    if added is not None and not re.search(r"(?m)^\+(async\s+)?def\s", added):
        return None
    return ("merge adds code without a test: " + ", ".join(code[:15])
            + " (a pure fix that adds no top-level `def` needs none)")


def check(staged: list[str], *, branch: str, merging: bool, read=lambda name: "",
          root: Path | None = None, merge_branch: str | None = None,
          added: str | None = None) -> str | None:
    """The refusal message for this commit, or None when it may go ahead.

    Shivam, 2026-11-01: no merge without docs. Every changed code file must be named in a doc
    changed by the same commit, and tasks/STATE.md alone does not count on a merge.
    T-127: a merge of a ``dsh/<job_id>`` branch needs that job's worker review row, and a merge
    that adds code with a new top-level ``def`` needs a staged test.
    """
    if branch != "main":
        return None
    for name, limit in LINE_LIMITS.items():
        if name in staged:
            lines = len(read(name).splitlines())
            if lines > limit:
                return f"{name} has {lines} lines, limit {limit}: move detail to docs/ or a dated record"
    for name, limit in CHAR_LIMITS.items():
        if name in staged:
            chars = len(read(name))
            if chars > limit:
                return f"{name} has {chars} characters, limit {limit}: move detail to docs/ or a dated record"
    problem = tracker_problem(staged, root)
    if problem:
        return problem
    if merging:
        problem = worker_review_problem(merge_branch, staged, read, root) or merge_tests_problem(staged, added)
        if problem:
            return problem
    if merging and STATE not in staged:
        return f"merge on main without {STATE}: put the current state in it"
    docs = [n for n in staged if n.endswith(".md") and not n.startswith(NOT_DOCS) and not (merging and n == STATE)]
    missing = undocumented(staged, "\n".join(read(n) for n in docs))
    if missing:
        return "code not named in any doc in this commit, update the doc that describes it: " + ", ".join(missing[:15])
    return None


def known_tickets(root: Path | None = None) -> set[str] | None:
    """Every id in the two tracker files, or None when they cannot be read."""
    root = root or Path(__file__).resolve().parents[2]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    try:
        from reality_engine.scripts import task_board

        live, done = task_board.load_rows(root)
    except Exception:
        return None
    return {row.id for row in live + done}


def check_message(message: str, *, branch: str, known: set[str] | None = None) -> str | None:
    """A commit on main names a real ticket, or says why it has none. Branches are not checked."""
    if branch != "main" or NO_TICKET.search(message):
        return None
    named = set(TICKET.findall(message))
    if not named:
        return ("commit message on main needs a ticket: name its T-<digits> or add a line "
                "'No-ticket: <reason>'")
    if known is not None and not named & known:
        return f"commit message names {', '.join(sorted(named))}, which is not in tasks/TASKS.md or tasks/TASKS_DONE.md"
    return None


def gate_rule(problem: str | None) -> str:
    """The RULINGS rule a pre-commit result belongs to: the block message names it."""
    if problem:
        for name in tuple(LINE_LIMITS) + tuple(CHAR_LIMITS):
            if problem.startswith(f"{name} has "):
                return "start_files"
        if problem.startswith("tracker lint"):
            return "tracker_lint"
        if problem.startswith(f"merge of {DSH_BRANCH}"):
            return "worker_review"
        if problem.startswith("merge adds code without a test"):
            return "merge_tests"
    return "doc_gate"


def log_gate(rule: str, problem: str | None, *, subject: str = "", detail: str = "",
             path: Path | None = None) -> bool:
    """Record one gate result in the rule ledger; never raises and never changes the answer."""
    try:
        root = Path(__file__).resolve().parents[2]
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        from reality_engine.scripts.rule_ledger import log_event

        payload = json.dumps({"subject": subject[:300], "problem": (problem or "")[:300],
                              "detail": detail[:300]}, ensure_ascii=False)
        return log_event(rule, "block" if problem else "pass", "doc_gate", payload, path=path)
    except Exception:
        return False


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=False, encoding="utf-8", errors="replace").stdout.strip()


def dsh_merge_branch() -> str | None:
    """The ``refs/heads/dsh/<job_id>`` branch at MERGE_HEAD, or None (T-127).

    Opus merges by hand with ``--no-ff --no-commit`` and a custom message, so the branch name is
    not in MERGE_MSG; the commit MERGE_HEAD points at is what names the reviewed worker.
    """
    heads = _git("rev-parse", "MERGE_HEAD").split()
    if not heads:
        return None
    branches = _git("for-each-ref", "--format=%(refname:short)", "--points-at", heads[0],
                    f"refs/heads/{DSH_BRANCH}").splitlines()
    return branches[0].strip() if branches else None


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
    if argv[:1] == ["--commit-msg"]:
        message = ""
        if len(argv) > 1:
            try:
                message = Path(argv[1]).read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                print(f"doc_gate: cannot read the commit message: {exc}", file=sys.stderr)
                return 1
        branch = _git("rev-parse", "--abbrev-ref", "HEAD")
        problem = check_message(message, branch=branch, known=known_tickets())
        if branch == "main":
            subject = next((line.strip() for line in message.splitlines() if line.strip()), "")
            log_gate("ticket", problem, subject=subject, detail="commit-msg")
        if problem:
            print(f"doc_gate: {problem}", file=sys.stderr)
            return 1
        return 0
    if "--sweep" in argv:
        return sweep(Path(_git("rev-parse", "--show-toplevel")))
    if "--install" in argv:
        hooks = Path(_git("rev-parse", "--git-common-dir")) / "hooks"
        hooks.mkdir(exist_ok=True)
        for name, body in (("pre-commit", HOOK), ("commit-msg", HOOK_MESSAGE), ("post-commit", HOOK_POST)):
            (hooks / name).write_text(body, encoding="utf-8", newline="\n")
            print(f"installed {hooks / name}")
        return 0
    staged = _git("diff", "--cached", "--name-only").splitlines()
    branch = _git("rev-parse", "--abbrev-ref", "HEAD")
    merging = Path(_git("rev-parse", "--git-path", "MERGE_HEAD")).exists()
    message = check(staged, branch=branch, merging=merging,
                    merge_branch=dsh_merge_branch() if merging else None,
                    added=_git("diff", "--cached", "-U0", "--", "*.py"),
                    read=lambda name: _git("show", f":{name}"))
    if branch == "main":
        log_gate(gate_rule(message), message, detail="pre-commit: " + ", ".join(staged[:30]))
        if message is None and any(name in LINE_LIMITS or name in CHAR_LIMITS for name in staged):
            log_gate("start_files", None, detail="line and character limits passed")
    if message:
        print(f"doc_gate: {message}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
