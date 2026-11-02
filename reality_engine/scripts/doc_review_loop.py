"""T-045 outer loop: fresh Haiku sessions read and correct the docs, one small batch at a time.

The queue comes from ``git ls-files`` minus ``tasks/handoff/DOC_REVIEW_PROGRESS.csv``, so a killed
run resumes where it stopped.  Each batch is one ``claude -p`` process with no shell tool, killed
if its context passes ``CONTEXT_LIMIT``.  The loop, not the model, decides what is kept:
anything outside the batch is restored, a large cut is reverted, protected files are never sent,
and a whole-file deletion is only proposed in the CSV.  Work stays on the review branch.

    python reality_engine/scripts/doc_review_loop.py --root <worktree> --log <file>
    python reality_engine/scripts/doc_review_loop.py --root <worktree> --dry-run
    python reality_engine/scripts/doc_review_loop.py --root <worktree> --archive --log <file>

``--archive`` reviews only ``tasks/archive/``, read-only: Shivam lifted its read rule for T-045
on 2 Nov.  The rule is lifted in the review worktree only, and put back when the run ends.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

CLAUDE = r"C:\Users\warri\.local\bin\claude.exe"
CONFIG_DIR = r"C:\Users\warri\.claude-neo"
MODEL = "claude-haiku-5-5"
CONTEXT_LIMIT = 95_000  # Shivam's limit is 100k; the process is killed before it.
BATCH_CHARS = 90_000  # about 30k tokens of text on top of about 32k of starting context
BATCH_FILES = 12
RUN_SECONDS = 30 * 60
MAX_TURNS = 60
BUDGET_USD = 25.0  # list-price estimate from the CLI; the loop stops here
MAX_FAILURES = 3
LIMIT_SLEEP = 15 * 60
LARGE_CUT = 0.40
PROGRESS = "tasks/handoff/DOC_REVIEW_PROGRESS.csv"
FIELDS = ["file", "lines", "lines_read", "outcome", "reason", "commit"]
DOC_SUFFIXES = (".md", ".txt", ".rst")

# Never sent to the model: Shivam's rulings and records, or a read rule he has not lifted.
PROTECTED = re.compile(
    r"^(tasks/RULINGS\.md|tasks/TASKS(_DONE)?\.md|tasks/STATE\.md|AGENTS\.md|tasks/master_bank/|tasks/pilot60/pilot_bank"
    r"|tasks/pilot60/PILOT_BANK|tasks/archive/|tasks/handoff/DOC_REVIEW|tasks/QUESTION_BANK_|tasks/reddit_mining/QUESTION_BANK_)"
)
ARCHIVE = re.compile(r"^tasks/archive/")
ARCHIVE_RULE = "Read(tasks/archive/**)"
SETTINGS = ".claude/settings.json"
# Annual-report text extracts, not documentation: deleting the folder is Shivam's call.
GENERATED = re.compile(r"^tasks/ar_study/text/")

PROMPT = """You are reviewing project documentation for staleness. Task T-045. Work only on the listed files.

Read every listed line yourself, with exactly the offset and limit given. Then, for each file:
- Delete an entry that is stale. Correct a claim that is wrong so it says what the code does now.
- Before keeping a doubtful claim or changing one, check it with Grep or Read: does the named file, function, flag or path exist and do what the doc says? Cite what you checked.
- You run in a worktree with no gitignored files, and `tasks/archive/`, `.tmp/` and the dsh runtime folder are hidden from you. A path you cannot find there may still exist: never write that a file is gone or not in the repo, and leave the reference. Report it in your reason.
- Do not rewrite for style. Small, exact edits only.

Do not change:
- A measured result or the only record of a result: grade, score, count, benchmark. Dated reports keep their numbers; only a stale surrounding claim may go.
- A number about data you cannot check from this repository. Leave it.
- Anything outside the listed files, or any line outside the given range.
- Never read D:\\Shivam_Private or any key, and never copy a key into a file.

If the whole file is stale, do not delete it: report outcome "delete-proposed". If it is generated data and not documentation, stop reading it and report "pending-generated".

Files:
{files}

End with one fenced json block and nothing after it, one row per file:
```json
[{{"file": "path", "outcome": "kept|changed|delete-proposed|pending-generated", "reason": "one short line, naming what you checked"}}]
```
"""


ARCHIVE_PROMPT = """You are reviewing archived project records for staleness. Task T-045. Work only on the listed files.

Files in `tasks/archive/` are history. Do not edit them, even where they disagree with the code now.
Read every listed line yourself, with exactly the offset and limit given. Then decide each file:
- kept: it is still the record of a decision, result or measurement, or a file outside `tasks/archive/` names it.
- delete-proposed: it is superseded, holds no result recorded nowhere else, and nothing outside `tasks/archive/` names it.
Before proposing a delete, Grep for the file's name across the repository and cite what you found.
You run in a worktree with no gitignored files, and `.tmp/` and the dsh runtime folder are hidden from you: never write that a file is gone.
Never read D:\\Shivam_Private or any key.

Files:
{files}

End with one fenced json block and nothing after it, one row per file:
```json
[{{"file": "path", "outcome": "kept|delete-proposed", "reason": "one short line, naming what you checked"}}]
```
"""


def is_protected(name: str, archive: bool = False) -> bool:
    return bool(PROTECTED.match(name)) and not (archive and ARCHIVE.match(name))


def lift_archive_rule(root: Path) -> bool:
    """Drop the archive read rule from the worktree's settings, hidden from git so no commit carries it."""
    path = root / SETTINGS
    if not path.exists():
        return False
    data = json.loads(path.read_text(encoding="utf-8"))
    deny = data.get("permissions", {}).get("deny", [])
    if ARCHIVE_RULE not in deny:
        return False
    deny.remove(ARCHIVE_RULE)
    git(root, "update-index", "--skip-worktree", SETTINGS)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return True


def restore_archive_rule(root: Path) -> None:
    git(root, "update-index", "--no-skip-worktree", SETTINGS)
    git(root, "restore", "--", SETTINGS)


@dataclass
class Item:
    file: str
    lines: int
    start: int  # 1-based first line to read
    end: int

    @property
    def complete(self) -> bool:
        return self.end >= self.lines


@dataclass
class Result:
    ok: bool = False
    rows: list[dict] = field(default_factory=list)
    cost: float = 0.0
    peak: int = 0
    limited: bool = False
    over_limit: bool = False
    error: str = ""


def log(path: Path | None, text: str) -> None:
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S} {text}"
    print(line, flush=True)
    if path:
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")


def git(root: Path, *args: str, check: bool = True) -> str:
    done = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if check and done.returncode:
        raise RuntimeError(f"git {' '.join(args)}: {done.stderr[:400]}")
    return done.stdout


def read_progress(root: Path) -> list[dict]:
    with (root / PROGRESS).open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def write_progress(root: Path, rows: list[dict]) -> None:
    with (root / PROGRESS).open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def upsert(rows: list[dict], row: dict) -> None:
    for existing in rows:
        if existing["file"] == row["file"]:
            existing.update(row)
            return
    rows.append(row)


def doc_files(root: Path) -> list[str]:
    return [f for f in git(root, "ls-files").splitlines() if f.lower().endswith(DOC_SUFFIXES)]


def settle_unsent(root: Path, rows: list[dict], archive: bool = False) -> int:
    """Record protected and generated files without any model call."""
    seen = {r["file"] for r in rows}
    added = 0
    for name in doc_files(root):
        if name in seen:
            continue
        if is_protected(name, archive):
            outcome, reason = "skipped-protected", "Not sent to the model: ruling, record or blocked folder"
        elif GENERATED.match(name):
            outcome, reason = "pending-generated", "Annual-report text extract, not read; deleting is Shivam's call"
        else:
            continue
        count = line_count(root / name)
        rows.append({"file": name, "lines": count, "lines_read": 0, "outcome": outcome, "reason": reason, "commit": ""})
        added += 1
    return added


def line_count(path: Path) -> int:
    with path.open(encoding="utf-8", errors="replace") as fh:
        return sum(1 for _ in fh)


def build_queue(root: Path, rows: list[dict], archive: bool = False) -> list[Item]:
    state = {r["file"]: r for r in rows}
    queue: list[Item] = []
    for name in doc_files(root):
        if archive and not ARCHIVE.match(name):
            continue
        row = state.get(name)
        if archive and row and row["outcome"] == "skipped-protected":
            row = None
        path = root / name
        if not path.exists():
            continue
        lines = line_count(path)
        start = 1
        if row:
            if not str(row["outcome"]).endswith("-partial"):
                continue
            start = int(row["lines_read"] or 0) + 1
        if lines and start <= lines:
            queue.append(Item(name, lines, start, lines))
    queue.sort(key=lambda i: (i.lines, i.file))
    return queue


def next_batch(root: Path, queue: list[Item], max_chars: int = BATCH_CHARS) -> list[Item]:
    """Take files until the character budget is spent, cutting a large file at a line boundary."""
    batch: list[Item] = []
    used = 0
    for item in queue:
        if len(batch) >= BATCH_FILES:
            break
        with (root / item.file).open(encoding="utf-8", errors="replace") as fh:
            text = fh.readlines()[item.start - 1:]
        taken = 0
        size = 0
        for line in text:
            if size + len(line) + 8 > max_chars - used and (taken or batch):
                break
            size += len(line) + 8
            taken += 1
        if not taken:
            break
        batch.append(Item(item.file, item.lines, item.start, item.start + taken - 1))
        used += size
        if taken < len(text):
            break
    return batch


def child_env() -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE_CODE", "CLAUDE_PID", "CLAUDE_EFFORT")) and k != "CLAUDECODE"}
    env.update(CLAUDE_CONFIG_DIR=CONFIG_DIR, DOC_REVIEW_LOOP="1", PYTHONUTF8="1")
    env.update(GIT_AUTHOR_NAME="kakazuya (Wolf)", GIT_COMMITTER_NAME="kakazuya (Wolf)")
    return env


def context_of(usage: dict) -> int:
    return sum(int(usage.get(k) or 0) for k in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))


def parse_rows(text: str) -> list[dict]:
    blocks = re.findall(r"```json\s*(.*?)```", text, re.S)
    if not blocks:
        return []
    try:
        data = json.loads(blocks[-1])
    except ValueError:
        return []
    return [r for r in data if isinstance(r, dict) and r.get("file") and r.get("outcome")] if isinstance(data, list) else []


def run_batch(root: Path, batch: list[Item], logfile: Path | None, archive: bool = False) -> Result:
    listing = "\n".join(f"- {i.file}: offset {i.start}, limit {i.end - i.start + 1} (file has {i.lines} lines)" for i in batch)
    cmd = [
        CLAUDE, "-p", (ARCHIVE_PROMPT if archive else PROMPT).format(files=listing), "--model", MODEL, "--effort", "medium",
        "--output-format", "stream-json", "--verbose", "--max-turns", str(MAX_TURNS),
        "--allowedTools", "Read,Grep,Glob" if archive else "Read,Grep,Glob,Edit",
        "--disallowedTools", "Bash,PowerShell,Write,NotebookEdit,Agent,WebFetch,WebSearch,Skill" + (",Edit" if archive else ""),
        "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}', "--no-session-persistence",
    ]
    proc = subprocess.Popen(
        cmd, cwd=root, env=child_env(), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    timer = threading.Timer(RUN_SECONDS, proc.kill)
    timer.start()
    result = Result()
    final = ""
    tail = ""
    try:
        for raw in proc.stdout:  # type: ignore[union-attr]
            tail = raw[:400]
            try:
                event = json.loads(raw)
            except ValueError:
                continue
            if event.get("type") == "assistant":
                usage = (event.get("message") or {}).get("usage") or {}
                result.peak = max(result.peak, context_of(usage))
                if result.peak >= CONTEXT_LIMIT:
                    result.over_limit = True
                    proc.kill()
                    break
            elif event.get("type") == "result":
                result.cost = float(event.get("total_cost_usd") or 0)
                final = str(event.get("result") or "")
                result.error = "" if not event.get("is_error") else final[:300]
    finally:
        timer.cancel()
        proc.wait()
    joined = (final + tail).lower()
    result.limited = any(w in joined for w in ("usage limit", "rate limit", "limit reached", "hit your limit", "429", "overloaded"))
    result.rows = parse_rows(final)
    result.ok = bool(result.rows) and not result.over_limit and not result.error
    if not result.ok and not result.error:
        result.error = "over context limit" if result.over_limit else f"no report rows: {(final or tail)[:200]}"
    log(logfile, f"batch files={len(batch)} peak={result.peak:,} cost=${result.cost:.3f} ok={result.ok} {result.error[:160]}")
    return result


def guard_changes(root: Path, batch: list[Item], logfile: Path | None, archive: bool = False) -> dict[str, str]:
    """Restore what the model must not have touched. Returns reverted file -> reason."""
    allowed = {i.file for i in batch}
    reverted: dict[str, str] = {}
    for row in git(root, "status", "--porcelain", "--no-renames").splitlines():
        status, name = row[:2], row[3:].strip().strip('"')
        if name == PROGRESS:
            continue
        bad = None
        if name not in allowed or is_protected(name, archive):
            bad = "outside the batch"
        elif archive:
            bad = "archive is read-only"
        elif "D" in status:
            bad = "deleted by the model"
        elif "?" in status:
            bad = "new file"
        if bad:
            restore(root, name, status)
            reverted[name] = bad
            log(logfile, f"reverted {name}: {bad}")
    numstat = git(root, "diff", "--numstat", "--", *allowed) if allowed else ""
    for line in numstat.splitlines():
        added, removed, name = line.split("\t", 2)
        if removed == "-":
            continue
        old = len(git(root, "show", f"HEAD:{name}").splitlines())
        if old >= 20 and int(removed) - int(added) > LARGE_CUT * old:
            restore(root, name, " M")
            reverted[name] = f"cut {removed} of {old} lines: review by hand"
            log(logfile, f"reverted {name}: {reverted[name]}")
    return reverted


def restore(root: Path, name: str, status: str) -> None:
    if "?" in status:
        target = root / name
        if target.is_file():
            target.unlink()
    else:
        git(root, "restore", "--staged", "--worktree", "--", name)


def record(rows: list[dict], batch: list[Item], result: Result, reverted: dict[str, str]) -> None:
    reported = {r["file"].replace("\\", "/"): r for r in result.rows}
    for item in batch:
        row = reported.get(item.file)
        outcome = str(row["outcome"]) if row else "kept-unreported"
        reason = str(row.get("reason", "")) if row else "The model read it but gave no row"
        if item.file in reverted:
            outcome, reason = "needs-review", f"Edit reverted: {reverted[item.file]}"
        if outcome == "pending-generated":
            lines_read = item.end
        else:
            lines_read = item.end
            if not item.complete:
                outcome = f"{outcome.removesuffix('-partial')}-partial"
        upsert(rows, {"file": item.file, "lines": item.lines, "lines_read": lines_read, "outcome": outcome, "reason": reason[:300], "commit": ""})


def commit(root: Path, batch: list[Item], logfile: Path | None, archive: bool = False) -> None:
    names = [i.file for i in batch if (root / i.file).exists()]
    git(root, "add", "--", PROGRESS, *names)
    message = (
        f"T-045 Haiku {'archive ' if archive else ''}review: {len(batch)} files, first {batch[0].file}\n\n"
        "Co-Authored-By: Claude Haiku 5.5 <noreply@anthropic.com>\n"
    )
    done = subprocess.run(
        ["git", "-C", str(root), "commit", "-q", "-m", message], capture_output=True, text=True,
        encoding="utf-8", errors="replace", env=child_env(),
    )
    if done.returncode:
        raise RuntimeError(f"commit failed: {(done.stdout + done.stderr)[:400]}")


def heartbeat(path: Path | None, stop: threading.Event) -> None:
    while path and not stop.wait(60):
        path.with_suffix(".beat").write_text(f"{time.time():.0f}", encoding="utf-8")


def loop(root: Path, logfile: Path | None, dry_run: bool, max_batches: int | None, archive: bool = False) -> int:
    if git(root, "rev-parse", "--abbrev-ref", "HEAD").strip() == "main":
        log(logfile, "STOPPED refusing to run on main")
        return 2
    lifted = archive and not dry_run and lift_archive_rule(root)
    try:
        return run_loop(root, logfile, dry_run, max_batches, archive)
    finally:
        if lifted:
            restore_archive_rule(root)


def run_loop(root: Path, logfile: Path | None, dry_run: bool, max_batches: int | None, archive: bool) -> int:
    stop = threading.Event()
    threading.Thread(target=heartbeat, args=(logfile, stop), daemon=True).start()
    spent = 0.0
    failures = 0
    batches = 0
    chars = BATCH_CHARS
    rows = read_progress(root)
    if settle_unsent(root, rows, archive) and not dry_run:
        write_progress(root, rows)
        git(root, "add", "--", PROGRESS)
        subprocess.run(["git", "-C", str(root), "commit", "-q", "-m", "T-045 protected and generated files recorded, not read"], env=child_env(), check=True)
    queue = build_queue(root, rows, archive)
    log(logfile, f"queue {len(queue)} files, {sum(i.end - i.start + 1 for i in queue):,} lines")
    if dry_run:
        for item in queue[:15]:
            print(item.lines, item.file)
        return 0
    while queue:
        if spent >= BUDGET_USD:
            log(logfile, f"STOPPED budget ${spent:.2f} reached, {len(queue)} files left")
            return 3
        if max_batches is not None and batches >= max_batches:
            log(logfile, f"PAUSED after {batches} batches, {len(queue)} files left")
            return 0
        batch = next_batch(root, queue, chars)
        if not batch:
            log(logfile, f"STOPPED cannot fit {queue[0].file} in a batch")
            return 4
        result = run_batch(root, batch, logfile, archive)
        spent += result.cost
        batches += 1
        if result.limited and not result.ok:
            for row in git(root, "status", "--porcelain", "--no-renames").splitlines():
                restore(root, row[3:].strip().strip('"'), row[:2])
            log(logfile, f"usage limit: sleeping {LIMIT_SLEEP // 60} min")
            time.sleep(LIMIT_SLEEP)
            continue
        if not result.ok:
            for row in git(root, "status", "--porcelain", "--no-renames").splitlines():
                restore(root, row[3:].strip().strip('"'), row[:2])
            failures += 1
            chars = max(15_000, chars // 2)
            if failures >= MAX_FAILURES:
                log(logfile, f"STOPPED {failures} failures in a row, {len(queue)} files left: {result.error[:200]}")
                return 5
            continue
        failures = 0
        chars = BATCH_CHARS
        reverted = guard_changes(root, batch, logfile, archive)
        record(rows, batch, result, reverted)
        write_progress(root, rows)
        commit(root, batch, logfile, archive)
        queue = build_queue(root, rows, archive)
        log(logfile, f"committed; {len(queue)} files left, estimated ${spent:.2f}")
    log(logfile, f"DONE estimated ${spent:.2f}")
    stop.set()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--log", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--max-batches", type=int)
    parser.add_argument("--archive", action="store_true", help="review tasks/archive/ only, read-only")
    args = parser.parse_args(argv)
    try:
        return loop(args.root.resolve(), args.log, args.dry_run, args.max_batches, args.archive)
    except Exception as exc:  # the watcher needs a terminal line whatever went wrong
        log(args.log, f"STOPPED {type(exc).__name__}: {str(exc)[:300]}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
