"""Rule and chain-of-command ledger (T-042).

One JSON line per gate pass or block is appended to ``tasks/efficiency/rule_events.jsonl``
(gitignored, created on demand) by :func:`log_event`, called from the doc gate and the
dsh-worker start gate.  The daily report reads those records plus the dsh job records and
git history; it makes no model call and no network call::

    python -m reality_engine.scripts.rule_ledger report --since 2026-11-01 --out .tmp/rule_ledger.xlsx

A rule with no record is reported ``not measured``; compliance is never inferred.  The
Rules sheet has one row per bullet in ``tasks/RULINGS.md``, and its four states are:

* ``enforced``          a ``[check: ...]`` in RULINGS.md names code that exists;
* ``followed unenforced`` no check, but a measurement in this report shows compliance;
* ``sidelined``         a measurement shows the rule was bypassed or violated;
* ``not measured``      neither a check nor a measurement.

A commit on ``main`` dated after the first logged event with no matching commit-msg gate
event is counted as a *possible* ``--no-verify`` bypass (possible, because a missing hook
is indistinguishable from a bypass in the records).  Gate logging never raises into the
caller, so no gate result can change because of it.
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import re
import subprocess
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVENTS = ROOT / "tasks" / "efficiency" / "rule_events.jsonl"
ENV_EVENTS = "DSH_RULE_EVENTS"
ENV_JOBS = "DSH_WORKER_JOBS"
CODE_SUFFIXES = (".py", ".sql")
#: [check: ...] names that actually write events to this ledger
WIRED_CHECKS = {"doc_gate", "start gate", "commit-msg"}

#: RULINGS.md phrase -> (rule key in the event log, extra text about how it is enforced)
RULE_MAP = (
    ("No docs, no merge", "doc_gate", "doc_gate pre-commit"),
    ("Start files stay short", "start_files", "doc_gate line limits"),
    ("becomes a ticket in `tasks/TASKS.md`", "ticket", "start gate refuses unknown tickets"),
    ("Every worker start names `permission`", "start_gate_permission", ""),
    ("HP work runs headless", "hp_headless", ""),
    ("Claude reviews, workers build", "worker_builds", "direct code commits on main"),
)

#: Facts measured on 2 Nov 2026 that every report run re-checks.
KNOWN_BUDGETS = {
    "20261101T210210Z-521b20a9": (90, 20),
    "20261101T205730Z-172d7dec": (45, 12),
}

SHEETS = {
    "Rules": ["rule", "line", "how_enforced", "passed", "blocked", "sidelined",
              "examples", "state"],
    "Workers": ["job", "started", "ticket", "budget_total", "budget_before_edit",
                "actual_total_calls", "actual_before_edit", "reported_total_calls",
                "reported_before_edit", "over_total", "over_before_edit",
                "code_intel_calls", "outcome", "merged", "merged_at", "finish_to_merge_h"],
    "Chain of command": ["day", "worker_merges", "worker_merge_py_lines",
                         "worker_merge_other_lines", "direct_commits", "direct_py_lines",
                         "direct_other_lines", "direct_code_commits",
                         "direct_code_examples", "gate_bypasses"],
    "Efficiency": ["metric", "label", "unit", "value"],
    "Notes": ["note"],
}

NOTES = [
    "State definitions: enforced = a [check: ...] name in tasks/RULINGS.md is wired to this "
    "ledger (doc_gate, start gate, commit-msg) and exists in code; followed unenforced = no "
    "check, a measurement here shows compliance; sidelined = a measurement shows a bypass "
    "or violation; not measured = no wired check and no measurement, including a [check] "
    "whose named code writes no events. Compliance is never inferred.",
    "Sidelined for doc_gate, start_files and ticket = commits on main dated after the first "
    "logged event with no matching commit-msg gate event (a possible --no-verify bypass; a "
    "missing hook looks the same in the records). Before the log began nothing is claimed.",
    "Sidelined for 'Claude reviews, workers build' = direct commits on main that changed "
    ".py or .sql files; a merge of a dsh/ worker branch is not counted as direct.",
    "Gate events: doc_gate logs one pass or block per pre-commit and commit-msg run on main; "
    "the start gate logs every permission_required, brief_incomplete, ticket_unknown and "
    "peak-hour refusal. Logging never raises, so no gate result changes because of it.",
    "Worker budget comes from the brief's 'Budget: N tool calls in total, M before the first "
    "edit'; actual calls are counted from result.md.events.jsonl, reported calls are parsed "
    "from the worker's own result.md.",
    "Merge time is the first main-line merge whose subject names the job's dsh/<job-id> "
    "branch; a job that was removed instead of merged shows merged=no and no time.",
]


# --- event log ------------------------------------------------------------------

def events_path(path: str | Path | None = None) -> Path:
    """The log to append to: explicit path, then $DSH_RULE_EVENTS, then the repo default."""
    if path:
        return Path(path)
    env = os.environ.get(ENV_EVENTS)
    return Path(env) if env else DEFAULT_EVENTS


def log_event(rule: str, outcome: str, actor: str, detail: str = "", *,
              path: str | Path | None = None) -> bool:
    """Append one event; never raises into the caller. True when the line was written."""
    try:
        target = events_path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
            "rule": str(rule),
            "outcome": str(outcome),
            "actor": str(actor),
            "detail": str(detail)[:500],
        }
        with target.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        return True
    except Exception:  # logging must not become a failure path, whatever the disk says
        return False


def read_events(path: str | Path | None = None) -> list[dict]:
    """Every well-formed event; malformed lines and a missing file are skipped."""
    out = []
    try:
        with events_path(path).open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if isinstance(event, dict) and event.get("ts"):
                    out.append(event)
    except OSError:
        return []
    return out


def event_date(event: dict) -> str:
    return str(event.get("ts") or "")[:10]


# --- git ------------------------------------------------------------------------

def _git(repo: Path, *args: str) -> str:
    try:
        proc = subprocess.run(["git", "-C", str(repo), *args], capture_output=True,
                              text=True, check=False, encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return proc.stdout if proc.returncode == 0 else ""


def main_worktree(repo: Path) -> Path:
    """The main checkout of this repository (a worktree's jobs and log live there)."""
    for line in _git(repo, "worktree", "list", "--porcelain").splitlines():
        if line.startswith("worktree "):
            return Path(line[len("worktree "):].strip())
    return repo


def default_events(repo: Path) -> Path:
    env = os.environ.get(ENV_EVENTS)
    if env:
        return Path(env)
    return main_worktree(repo) / "tasks" / "efficiency" / "rule_events.jsonl"


def default_jobs_root(repo: Path) -> Path:
    env = os.environ.get(ENV_JOBS)
    if env:
        return Path(env)
    return main_worktree(repo) / "plugins" / "dsh-worker" / "runtime" / "jobs"


def parse_commits(repo: Path, since: str | None = None) -> list[dict]:
    """Commits on main since a date, with their numstat file changes.

    ``--first-parent -m`` shows a merge as its diff against the first parent, so a worker
    merge carries the branch's line counts and side-branch commits are not listed twice.
    """
    args = ["log", "main", "--first-parent", "-m", "--numstat",
            "--format=C%x09%H%x09%P%x09%ct%x09%s"]
    if since:
        args.append(f"--since={since} 00:00:00")
    commits: list[dict] = []
    current: dict | None = None
    for line in _git(repo, *args).splitlines():
        if line.startswith("C\t"):
            parts = line.split("\t")
            if len(parts) < 5:
                current = None
                continue
            try:
                stamp = int(parts[3] or 0)
            except ValueError:
                stamp = 0
            current = {"hash": parts[1], "parents": parts[2].split(), "ct": stamp,
                       "subject": "\t".join(parts[4:]), "files": []}
            commits.append(current)
            continue
        if current is None or not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) == 3:
            current["files"].append(
                (parts[2], int(parts[0]) if parts[0].isdigit() else 0,
                 int(parts[1]) if parts[1].isdigit() else 0))
    return commits


def merge_times(repo: Path) -> dict[str, float]:
    """Branch -> epoch seconds of the first main-line merge naming it."""
    out = _git(repo, "log", "main", "--first-parent", "--merges", "-n", "2000",
               "--format=%ct%x09%s")
    times: dict[str, float] = {}
    for line in out.splitlines():
        stamp, _, subject = line.partition("\t")
        try:
            value = float(stamp)
        except ValueError:
            continue
        for branch in re.findall(r"dsh/[\w.-]+", subject):
            times[branch] = min(value, times.get(branch, value))
    return times


# --- small helpers --------------------------------------------------------------

def _json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _last_jsonl(path: Path) -> dict:
    last: dict = {}
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    value = json.loads(line)
                except ValueError:
                    continue
                if isinstance(value, dict):
                    last = value
    except OSError:
        return {}
    return last


def _dt(value) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


# --- budgets and reported counts -------------------------------------------------

def parse_budget(brief: str) -> tuple[int | None, int | None]:
    """(total, before first edit) from the brief's ``Budget:`` line; (None, None) without it.

    A brief opened by the auto-attached context pack carries two ``Budget:`` lines (the
    pack's first-edit hint and the brief contract's own); the line naming the first edit is
    the budget, so it wins over the hint, and the last line wins when neither names it.
    """
    lines = re.findall(r"(?im)^\s*Budget:\s*([^\n]*)$", brief or "")
    line = next((item for item in lines if "before the first edit" in item.lower()), "")
    if not line:
        return None, None
    total = re.search(r"(?i)(\d+)\s+tool calls\b", line)
    before = re.search(r"(?i)(\d+)\s+before the first edit", line)
    return (int(total.group(1)) if total else None,
            int(before.group(1)) if before else None)


def parse_reported(result_text: str) -> tuple[int | None, int | None]:
    """(total, before first edit) as the worker's own result states them, else (None, None)."""
    text = result_text or ""
    section = re.search(r"(?ims)^#+\s*\d*\)?\s*tool calls.*?(?=^#+\s|\Z)", text)
    body = section.group(0) if section else text
    before = re.search(r"(?i)(\d+)\s+(?:tool calls\s+|calls\s+)?before (?:the )?first edit",
                       body)
    total = re.search(r"(?i)[~≈]?\s*(\d+)\s+(?:tool calls\s+)?total\b", body)
    return (int(total.group(1)) if total else None,
            int(before.group(1)) if before else None)


def count_calls(events_file: Path) -> tuple[int | None, int | None]:
    """(tool calls, code-intel calls) counted from a job's event log; (None, None) if absent."""
    total = 0
    code_intel = 0
    try:
        with events_file.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(event, dict) or event.get("type") != "tool_call":
                    continue
                total += 1
                if str(event.get("tool") or "").startswith("mcp__code-intel__"):
                    code_intel += 1
    except OSError:
        return None, None
    return total, code_intel


# --- Workers sheet --------------------------------------------------------------

def worker_rows(jobs: Path, merges: dict[str, float], since: str | None = None) -> list[dict]:
    """One row per job directory that has a status.json."""
    rows: list[dict] = []
    if not jobs.is_dir():
        return rows
    for job_dir in sorted(path for path in jobs.iterdir() if path.is_dir()):
        status = _json(job_dir / "status.json")
        if not status:
            continue
        job = str(status.get("job_id") or job_dir.name)
        started = str(status.get("started_at") or "")
        if since and started[:10] and started[:10] < since:
            continue
        brief = _text(job_dir / "brief.md")
        budget_total, budget_before = parse_budget(brief)
        ticket = re.search(r"(?m)^\s*Ticket:\s*(T-\d+)", brief)
        actual_total, code_intel = count_calls(job_dir / "result.md.events.jsonl")
        if actual_total is None:
            progress = _last_jsonl(job_dir / "progress.jsonl")
            actual_total = progress.get("tool_calls")
            by_tool = progress.get("tool_calls_by_tool") or {}
            code_intel = sum(int(v or 0) for key, v in by_tool.items()
                             if str(key).startswith("mcp__code-intel__"))
        actual_before = status.get("tool_calls_before_first_edit")
        reported_total, reported_before = parse_reported(_text(job_dir / "result.md"))
        worktree = status.get("worktree_commit") or {}
        branch = str(worktree.get("branch") or f"dsh/{job}")
        merge_at = merges.get(branch)
        finished_dt = _dt(status.get("finished_at")) if status.get("finished_at") else None
        finish_to_merge = None
        if merge_at and finished_dt:
            finish_to_merge = round((merge_at - finished_dt.timestamp()) / 3600.0, 1)
        rows.append({
            "job": job,
            "started": started,
            "ticket": ticket.group(1) if ticket else "",
            "budget_total": budget_total,
            "budget_before_edit": budget_before,
            "actual_total_calls": actual_total,
            "actual_before_edit": actual_before,
            "reported_total_calls": reported_total,
            "reported_before_edit": reported_before,
            "over_total": ((actual_total > budget_total)
                           if isinstance(actual_total, int) and isinstance(budget_total, int)
                           else None),
            "over_before_edit": ((actual_before > budget_before)
                                 if isinstance(actual_before, int)
                                 and isinstance(budget_before, int) else None),
            "code_intel_calls": code_intel,
            "outcome": str(status.get("outcome") or ""),
            "merged": bool(merge_at),
            "merged_at": (datetime.fromtimestamp(merge_at).isoformat(timespec="seconds")
                          if merge_at else ""),
            "finish_to_merge_h": finish_to_merge,
        })
    return rows


def known_fact_checks(rows: list[dict]) -> list[tuple[str, bool, str]]:
    """Re-check the two measured budgets from 2 Nov 2026 against the parsed rows."""
    by_job = {row["job"]: row for row in rows}
    out = []
    for job, (total, before) in KNOWN_BUDGETS.items():
        row = by_job.get(job)
        seen = (None, None) if row is None else (row["budget_total"], row["budget_before_edit"])
        out.append((job, seen == (total, before),
                    f"budget parsed {seen[0]}/{seen[1]}, expected {total}/{before}"))
    return out


# --- Chain of command sheet -----------------------------------------------------

def chain_rows(commits: list[dict], events: list[dict],
               log_start: str | None = None) -> tuple[list[dict], dict]:
    """Per-day split of main commits into worker merges and direct work, plus summaries."""
    gated: set[str] = set()
    for event in events:
        if event.get("rule") != "ticket":
            continue
        try:
            detail = json.loads(str(event.get("detail") or "{}"))
        except ValueError:
            detail = {}
        subject = str((detail or {}).get("subject") or "").strip()[:300]
        if subject:
            gated.add(subject)
    by_day: dict[str, dict] = {}
    direct_code: list[str] = []
    bypasses: list[str] = []
    for commit in commits:
        day = datetime.fromtimestamp(int(commit["ct"])).strftime("%Y-%m-%d")
        row = by_day.setdefault(day, {
            "day": day, "worker_merges": 0, "worker_merge_py_lines": 0,
            "worker_merge_other_lines": 0, "direct_commits": 0, "direct_py_lines": 0,
            "direct_other_lines": 0, "direct_code_commits": 0,
            "direct_code_examples": "", "gate_bypasses": 0,
        })
        py_lines = sum(a + d for path, a, d in commit["files"] if path.endswith(".py"))
        other_lines = sum(a + d for path, a, d in commit["files"]
                          if not path.endswith(".py"))
        worker_merge = len(commit["parents"]) > 1 and "dsh/" in commit["subject"].lower()
        if worker_merge:
            row["worker_merges"] += 1
            row["worker_merge_py_lines"] += py_lines
            row["worker_merge_other_lines"] += other_lines
        else:
            row["direct_commits"] += 1
            row["direct_py_lines"] += py_lines
            row["direct_other_lines"] += other_lines
            if any(path.endswith(CODE_SUFFIXES) for path, _, _ in commit["files"]):
                row["direct_code_commits"] += 1
                direct_code.append(f"{day} {commit['subject'][:100]}")
        subject = commit["subject"].strip()[:300]
        if log_start and day > log_start and not any(
                subject.startswith(gate) or gate.startswith(subject) for gate in gated):
            row["gate_bypasses"] += 1
            bypasses.append(f"{day} {subject[:100]}")
    rows = [by_day[day] for day in sorted(by_day)]
    for row in rows:
        examples = [item for item in direct_code if item.startswith(row["day"] + " ")]
        row["direct_code_examples"] = "; ".join(item[11:] for item in examples[:3])
    return rows, {"direct_code": direct_code, "bypasses": bypasses}


# --- Rules sheet ----------------------------------------------------------------

def rules_rows(rulings: Path, events: list[dict], *, direct_code=(),
               bypasses=(), measured_days: int = 0) -> list[dict]:
    """One row per bullet in RULINGS.md; counts only come from records, never from a guess."""
    counts: dict[str, dict[str, int]] = collections.defaultdict(
        lambda: {"passed": 0, "blocked": 0})
    for event in events:
        bucket = counts[str(event.get("rule") or "")]
        if event.get("outcome") == "pass":
            bucket["passed"] += 1
        elif event.get("outcome") in ("block", "sidelined"):
            bucket["blocked"] += 1
    try:
        lines = rulings.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        lines = []
    rows = []
    for number, line in enumerate(lines, 1):
        if not line.startswith("- "):
            continue
        text = line[2:].strip()
        key, extra = "", ""
        for phrase, rule_key, rule_extra in RULE_MAP:
            if phrase.lower() in text.lower():
                key, extra = rule_key, rule_extra
                break
        marker = re.search(r"\[check:\s*([^\]]+)\]", text)
        check_name = marker.group(1).strip() if marker else ""
        wired = check_name.lower() in WIRED_CHECKS
        if wired:
            how = "code: " + check_name
            if extra and extra.lower() not in check_name.lower() \
                    and check_name.lower() not in extra.lower():
                how += " (" + extra + ")"
        elif marker:
            how = "code named: " + check_name + "; not wired to the ledger"
        elif extra:
            how = "measured: " + extra
        else:
            how = "text only"
        bucket = counts.get(key or "", {"passed": 0, "blocked": 0})
        sidelined: list[str] = []
        if key in ("doc_gate", "start_files", "ticket"):
            sidelined = list(bypasses)
        elif key == "worker_builds":
            sidelined = list(direct_code)
        if key == "worker_builds":
            if not measured_days:
                state = "not measured"
            elif direct_code:
                state = "sidelined"
            else:
                state = "followed unenforced"
        elif key:
            if marker and not wired:
                state = "not measured"
            else:
                state = "sidelined" if sidelined else "enforced"
        else:
            state = "enforced" if wired else "not measured"
        rows.append({
            "rule": text[:200],
            "line": number,
            "how_enforced": how,
            "passed": bucket["passed"],
            "blocked": bucket["blocked"],
            "sidelined": len(sidelined),
            "examples": "; ".join(item[:120] for item in sidelined[:3]),
            "state": state,
        })
    return rows


# --- Efficiency sheet -----------------------------------------------------------

def efficiency_rows(since: str | None) -> list[dict]:
    """The FIX_TRACKER rates, computed by tool_usage_report.metrics (never recomputed here)."""
    try:
        from reality_engine.scripts import tool_usage_report as usage

        since_ts = usage._ts(f"{since}T00:00:00+00:00") if since else None
        report = usage.build(usage.DEFAULT_ROOTS, since_ts, str(Path.cwd()))
        values = usage.metrics(report)
        labels = {key: (label, unit) for key, label, unit in usage.COMPARISON_METRICS}
        return [{"metric": key,
                 "label": labels.get(key, (key, ""))[0],
                 "unit": labels.get(key, ("", ""))[1],
                 "value": value} for key, value in values.items()]
    except Exception as exc:  # a broken scan is reported, not silently dropped
        return [{"metric": "not measured", "label": "tool_usage_report failed",
                 "unit": "", "value": str(exc)[:300]}]


# --- report ---------------------------------------------------------------------

def _write_xlsx(path: Path, data: dict[str, list[dict]]) -> None:
    from openpyxl import Workbook

    workbook = Workbook()
    default = workbook.active
    if default is not None:
        workbook.remove(default)
    for name, rows in data.items():
        sheet = workbook.create_sheet(name[:31])
        headers = SHEETS[name]
        sheet.append(headers)
        for row in rows:
            sheet.append([_cell(row.get(header)) for header in headers])
        for index in range(1, len(headers) + 1):
            sheet.column_dimensions[sheet.cell(row=1, column=index).column_letter].width = 26
    path.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(path)


def _cell(value):
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return str(value)


def report(repo: Path, out: str | Path, since: str | None = None,
           events_file: str | Path | None = None) -> dict[str, int]:
    """Build the four-sheet workbook from existing records and print the row counts."""
    all_events = read_events(events_file or default_events(repo))
    dated = [event for event in all_events if event_date(event)]
    log_start = min(event_date(event) for event in dated) if dated else None
    window = [event for event in dated if not since or event_date(event) >= since]
    merges = merge_times(repo)
    workers = worker_rows(default_jobs_root(repo), merges, since)
    commits = parse_commits(repo, since)
    chain, summary = chain_rows(commits, window, log_start)
    rules = rules_rows(repo / "tasks" / "RULINGS.md", window,
                       direct_code=summary["direct_code"], bypasses=summary["bypasses"],
                       measured_days=len(chain))
    data = {
        "Rules": rules,
        "Workers": workers,
        "Chain of command": chain,
        "Efficiency": efficiency_rows(since),
        "Notes": [{"note": note} for note in NOTES],
    }
    _write_xlsx(Path(out), data)
    print(f"events: {len(window)} in window; log began {log_start or 'never'}")
    counts = {}
    for name, rows in data.items():
        counts[name] = len(rows)
        print(f"{name}: {len(rows)} row(s)")
    checks = known_fact_checks(workers)
    for job, ok, detail in checks:
        print(f"known fact {job}: {'PASS' if ok else 'FAIL'} ({detail})")
    print(f"known-fact checks: {sum(1 for _, ok, _ in checks if ok)}/{len(checks)}")
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Rule and chain-of-command ledger.")
    sub = parser.add_subparsers(dest="command", required=True)
    report_parser = sub.add_parser("report", help="write the Excel report from existing records")
    report_parser.add_argument("--since", help="only records dated on/after this day (YYYY-MM-DD)")
    report_parser.add_argument("--out", required=True, help="destination .xlsx path")
    report_parser.add_argument("--events", help="event log (default $DSH_RULE_EVENTS or "
                                                "tasks/efficiency/rule_events.jsonl)")
    args = parser.parse_args(argv)
    if args.command == "report":
        report(Path.cwd(), args.out, args.since, args.events)
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
