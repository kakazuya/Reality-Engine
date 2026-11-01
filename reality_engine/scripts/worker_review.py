"""Build the worker-review log over every dsh worker job and Claude session (read-only).

Every number comes from a record on disk: the job directory
(``plugins/dsh-worker/runtime/jobs/*/``) contributes ``result.md.events.jsonl``,
``progress.jsonl``, ``status.json``, ``job.json`` and ``brief.md``; a Claude session
contributes its transcript under ``~/.claude/projects/`` (``~/.claude-neo/projects`` is
the same junction and is read once); Claude's own review of a job or session comes from
``tasks/efficiency/worker_reviews.jsonl``.  The job type is taken from a review row only,
never guessed, and thinking tokens are provider-reported when a record has them and
otherwise estimated from ``thinking`` event characters at 4 characters per token (the
estimate lives in a column whose name ends in ``_est``).

No model call, no network call, no write outside ``--out``; safe to rerun::

    python -m reality_engine.scripts.worker_review build --out tasks/efficiency/WORKER_REVIEW_LOG.xlsx
    python -m reality_engine.scripts.worker_review last --n 5
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone

from reality_engine.scripts import tool_usage_report as TUR

CHARS_PER_TOKEN = 4
JOB_ID = re.compile(r"(\d{8}T\d{6}Z-[0-9a-f]+)")

#: Tool mix classes.  ``code-intel`` is any ``mcp__code-intel__*`` tool; everything
#: unnamed in the list (glob, task, web, …) counts as ``other`` and is still shown.
MIX = ["read", "grep", "edit", "write", "shell", "code-intel", "other"]

WORKER_COLUMNS = [
    ("job_id", "job_id"), ("host", "host"), ("ticket", "ticket"), ("model", "model"),
    ("effort", "effort"), ("permission", "permission"), ("write_scope", "write_scope"),
    ("outcome", "outcome"), ("started", "started"), ("finished", "finished"),
    ("minutes", "minutes"), ("orientation_seconds", "orientation_seconds"),
    ("seconds_finish_to_merge", "seconds_finish_to_merge"), ("job_type", "job_type"),
    ("tool_calls_actual", "tool_calls_actual"),
    ("calls_before_first_edit_events", "calls_before_first_edit_events"),
    ("calls_before_first_edit_status", "calls_before_first_edit_status"),
    ("budget_total", "budget_total"), ("budget_before_first_edit", "budget_before_first_edit"),
    ("over_budget_total", "over_budget_total"),
    ("over_budget_before_first_edit", "over_budget_before_first_edit"),
    ("self_reported_tool_calls", "self_reported_tool_calls"),
    ("self_report_gap", "self_report_gap"),
    ("calls_read", "calls_read"), ("calls_grep", "calls_grep"), ("calls_edit", "calls_edit"),
    ("calls_write", "calls_write"), ("calls_shell", "calls_shell"),
    ("calls_code_intel", "calls_code_intel"), ("calls_other", "calls_other"),
    ("failed_tool_results", "failed_tool_results"), ("repeated_reads", "repeated_reads"),
    ("input_tokens", "input_tokens"), ("cache_read_tokens", "cache_read_tokens"),
    ("output_tokens", "output_tokens"), ("model_steps", "model_steps"),
    ("thinking_tokens", "thinking_tokens"), ("thinking_tokens_est", "thinking_tokens_est"),
    ("output_tokens_excl_thinking_est", "output_tokens_excl_thinking_est"),
    ("result_chars", "result_chars"), ("brief_chars", "brief_chars"),
    ("changed_files", "changed_files"), ("lines_added", "lines_added"),
    ("lines_removed", "lines_removed"),
]

CLAUDE_COLUMNS = [
    ("session_id", "session_id"), ("account", "account"), ("started", "started"),
    ("finished", "finished"), ("minutes", "minutes"), ("steps", "steps"),
    ("tool_calls_total", "tool_calls_total"),
    ("calls_read", "calls_read"), ("calls_grep", "calls_grep"), ("calls_edit", "calls_edit"),
    ("calls_write", "calls_write"), ("calls_shell", "calls_shell"),
    ("calls_code_intel", "calls_code_intel"), ("calls_other", "calls_other"),
    ("input_tokens", "input_tokens"), ("cache_read_tokens", "cache_read_tokens"),
    ("cache_creation_tokens", "cache_creation_tokens"),
    ("output_tokens", "output_tokens"), ("thinking_tokens", "thinking_tokens"),
    ("code_edits", "code_edits"), ("files_edited", "files_edited"), ("file", "file"),
]

REVIEW_KEYS = ["job_type", "what_went_well", "waste", "claude_would_have_done",
               "claude_estimate", "prompt_change", "permission_change", "scope_change",
               "applied_in"]

REVIEW_COLUMNS = [
    ("id", "id"), ("kind", "kind"), ("review_status", "review_status"),
    ("job_type", "job_type"), ("model", "model"), ("outcome", "outcome"),
    ("tool_calls_actual", "tool_calls_actual"),
    ("calls_before_first_edit", "calls_before_first_edit"),
    ("output_tokens", "output_tokens"), ("minutes", "minutes"),
    ("changed_files", "changed_files"),
] + [(k, k) for k in REVIEW_KEYS]

TREND_COLUMNS = [
    ("group", "group"), ("key", "key"), ("jobs", "jobs"),
    ("median_tool_calls", "median_tool_calls"),
    ("median_calls_before_first_edit", "median_calls_before_first_edit"),
    ("median_output_tokens", "median_output_tokens"), ("median_minutes", "median_minutes"),
    ("median_tokens_per_changed_line", "median_tokens_per_changed_line"),
    ("share_over_budget", "share_over_budget"),
]

_BUDGET_TOTAL = re.compile(r"(\d+)\s+tool[- ]calls?", re.I)
_BUDGET_BEFORE = re.compile(r"(\d+)\s+before\s+(?:the\s+)?first\s+edit", re.I)
_TICKET = re.compile(r"(?m)^\s*Ticket:\s*(\S+)")
_SELF_TOTAL = [
    re.compile(r"(?:≈|~|about\s+)?(\d{1,5})\s+tool[- ]calls?\s+(?:in\s+)?total", re.I),
    re.compile(r"total[^\n]{0,20}?(?:≈|~|:)?\s*(\d{1,5})\s+tool[- ]calls", re.I),
]


# --- parsing --------------------------------------------------------------------

def parse_budget(text: str) -> tuple[int | None, int | None]:
    """``(total, before_first_edit)`` from the brief's ``Budget:`` line.

    The auto-attached context-pack line (``Budget: reach your first useful edit within
    <= N tool calls``) is a generic target, not this job's budget, so it is skipped; a
    brief with no job budget line yields ``(None, None)`` rather than an invented one.
    """
    total = before = None
    for line in (text or "").splitlines():
        if not line.lstrip().lower().startswith("budget:"):
            continue
        low = line.lower()
        if "useful edit" in low:
            continue
        m = _BUDGET_TOTAL.search(low)
        if m and total is None:
            total = int(m.group(1))
        b = _BUDGET_BEFORE.search(low)
        if b and before is None:
            before = int(b.group(1))
    return total, before


def parse_ticket(text: str) -> str:
    """The value of the brief's ``Ticket:`` line, else ``""``."""
    m = _TICKET.search(text or "")
    return m.group(1).strip() if m else ""


def parse_self_report(text: str) -> int | None:
    """The worker's own total tool-call count from its final text, where it states one."""
    for rx in _SELF_TOTAL:
        m = rx.search(text or "")
        if m:
            return int(m.group(1))
    return None


def tool_class(name: str) -> str:
    """One of :data:`MIX` for a tool name, so workers and Claude sessions compare."""
    n = (name or "").strip().lower()
    if n.startswith("mcp__code-intel__"):
        return "code-intel"
    if n in ("read", "read_file", "view"):
        return "read"
    if n in ("grep", "search", "grep_search"):
        return "grep"
    if n == "edit":
        return "edit"
    if n == "write":
        return "write"
    if n in ("pwsh", "powershell", "bash", "shell", "exec", "run_shell"):
        return "shell"
    return "other"


def _int(value) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _read_text(path: str) -> str:
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return ""


def _iso(ts: float | None) -> str:
    if ts is None:
        return ""
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds")


# --- one dsh job ----------------------------------------------------------------

def read_events(path: str) -> dict:
    """Tool calls, the pre-first-edit count, mix, failures, repeated reads, thinking chars."""
    out = {"present": os.path.isfile(path), "tool_calls": 0,
           "calls_before_first_edit": None, "by_tool": collections.Counter(),
           "failed": 0, "thinking_chars": 0, "repeated_reads": 0}
    if not out["present"]:
        return out
    pending: dict[str, str] = {}
    reads: collections.Counter = collections.Counter()
    first_edit = None
    for line in TUR._iter_lines(path):
        line = line.strip()
        if not line:
            continue
        try:
            e = json.loads(line)
        except ValueError:
            continue
        t = e.get("type")
        if t == "tool_call":
            out["tool_calls"] += 1
            name = e.get("tool") or ""
            cls = tool_class(name)
            out["by_tool"][cls] += 1
            inp = e.get("input") or {}
            if cls in ("edit", "write") and first_edit is None:
                first_edit = out["tool_calls"] - 1
            if cls == "read":
                target = str(inp.get("file_path") or inp.get("path") or "")
                if target:
                    reads[target] += 1
            pending[str(e.get("callId"))] = cls
        elif t == "tool_result":
            pending.pop(str(e.get("callId")), None)
            text = e.get("result")
            text = text if isinstance(text, str) else json.dumps(text)
            if e.get("status") == "error" or TUR._exit_nonzero(text):
                out["failed"] += 1
        elif t == "thinking":
            out["thinking_chars"] += len(e.get("text") or "")
    out["calls_before_first_edit"] = first_edit if first_edit is not None else out["tool_calls"]
    out["repeated_reads"] = sum(n - 1 for n in reads.values() if n > 1)
    return out


def _git_numstat(repo_root: str, head: str, cache: dict) -> tuple[int | None, int | None]:
    if not repo_root or not head:
        return None, None
    if head in cache:
        return cache[head]
    added = removed = 0
    ok = False
    try:
        res = subprocess.run(["git", "-C", repo_root, "show", "--numstat", "--format=", head],
                             capture_output=True, text=True, timeout=30)
        if res.returncode == 0:
            ok = True
            for row in res.stdout.splitlines():
                parts = row.split("\t")
                if len(parts) >= 2:
                    added += _int(parts[0]) or 0
                    removed += _int(parts[1]) or 0
    except (OSError, subprocess.SubprocessError):
        ok = False
    result = (added, removed) if ok else (None, None)
    cache[head] = result
    return result


def read_job(job_dir: str, repo_root: str | None = None, merge_times: dict | None = None,
             numstat_cache: dict | None = None) -> dict:
    """One measured worker row for one job directory."""
    name = os.path.basename(job_dir.rstrip("\\/"))
    status = TUR._load_json(os.path.join(job_dir, "status.json")) or {}
    job = TUR._load_json(os.path.join(job_dir, "job.json")) or {}
    prog = TUR._last_jsonl(os.path.join(job_dir, "progress.jsonl")) or {}
    brief = _read_text(os.path.join(job_dir, "brief.md"))
    result = _read_text(os.path.join(job_dir, "result.md"))
    events = read_events(os.path.join(job_dir, "result.md.events.jsonl"))

    started = TUR._ts(status.get("started_at"))
    finished = TUR._ts(status.get("finished_at"))
    minutes = round((finished - started) / 60.0, 2) if started and finished else None
    merge_times = merge_times or {}
    merged = merge_times.get(name)
    finish_to_merge = round(merged - finished, 1) if merged and finished else None

    budget_total, budget_before = parse_budget(brief)
    actual = events["tool_calls"] if events["present"] else _int(prog.get("tool_calls"))
    before_events = events["calls_before_first_edit"] if events["present"] else None
    before_status = _int(status.get("tool_calls_before_first_edit"))
    if before_status is None:
        before_status = _int(prog.get("tool_calls_before_first_edit"))
    self_reported = parse_self_report(result)
    gap = actual - self_reported if actual is not None and self_reported is not None else None

    input_tokens = _int(prog.get("input_tokens"))
    cache_read = _int(prog.get("cache_read_tokens"))
    output_tokens = _int(prog.get("output_tokens"))
    model_steps = _int(prog.get("model_steps"))
    provider_thinking = _int(prog.get("reasoning_tokens"))
    if provider_thinking is None:
        provider_thinking = _int(prog.get("thinking_tokens"))
    est = int(round(events["thinking_chars"] / CHARS_PER_TOKEN)) if events["thinking_chars"] else None
    deducted = provider_thinking if provider_thinking is not None else est
    output_excl = (max(0, output_tokens - deducted)
                   if output_tokens is not None and deducted is not None else None)

    commit = status.get("worktree_commit") or {}
    head = commit.get("head")
    changed_files = _int(commit.get("files_changed"))
    added, removed = _git_numstat(repo_root or "", head or "",
                                  numstat_cache if numstat_cache is not None else {})

    row = {
        "job_id": name,
        "host": job.get("host") or status.get("host") or "",
        "ticket": parse_ticket(brief),
        "model": job.get("model") or "",
        "effort": job.get("effort") or "",
        "permission": job.get("permission") or "",
        "write_scope": job.get("write_scope") or "",
        "outcome": status.get("outcome") or "",
        "started": _iso(started),
        "finished": _iso(finished),
        "minutes": minutes,
        "orientation_seconds": status.get("orientation_seconds", prog.get("orientation_seconds")),
        "seconds_finish_to_merge": finish_to_merge,
        "job_type": "",  # filled from a review row only
        "tool_calls_actual": actual,
        "calls_before_first_edit_events": before_events,
        "calls_before_first_edit_status": before_status,
        "budget_total": budget_total,
        "budget_before_first_edit": budget_before,
        "over_budget_total": (actual > budget_total
                              if actual is not None and budget_total is not None else None),
        "over_budget_before_first_edit": (before_events > budget_before
                                          if before_events is not None and budget_before is not None
                                          else None),
        "self_reported_tool_calls": self_reported,
        "self_report_gap": gap,
        "failed_tool_results": events["failed"] if events["present"] else None,
        "repeated_reads": events["repeated_reads"] if events["present"] else None,
        "input_tokens": input_tokens,
        "cache_read_tokens": cache_read,
        "output_tokens": output_tokens,
        "model_steps": model_steps,
        "thinking_tokens": provider_thinking,
        "thinking_tokens_est": None if provider_thinking is not None else est,
        "output_tokens_excl_thinking_est": output_excl,
        "result_chars": len(result) if os.path.isfile(os.path.join(job_dir, "result.md")) else None,
        "brief_chars": len(brief) if os.path.isfile(os.path.join(job_dir, "brief.md")) else None,
        "changed_files": changed_files,
        "lines_added": added,
        "lines_removed": removed,
        "repo_root": job.get("repo_root") or "",
    }
    for cls in MIX:
        row["calls_" + cls.replace("-", "_")] = (events["by_tool"].get(cls, 0)
                                                 if events["present"] else None)
    return row


def discover_repo_root(jobs_root: str) -> str:
    """The main checkout named by the job records (a worktree names the same repo)."""
    votes: collections.Counter = collections.Counter()
    try:
        names = sorted(os.listdir(jobs_root))
    except OSError:
        return ""
    for name in names:
        record = TUR._load_json(os.path.join(jobs_root, name, "job.json")) or {}
        root = record.get("repo_root")
        if root:
            votes[root] += 1
    return votes.most_common(1)[0][0] if votes else ""


def read_merge_times(repo_root: str) -> dict[str, float]:
    """Job id -> committer time of its ``merge: dsh/<job id>`` commit, when recorded."""
    out: dict[str, float] = {}
    if not repo_root:
        return out
    try:
        res = subprocess.run(
            ["git", "-C", repo_root, "log", "--merges", "--format=%ct%x09%s", "-n", "3000"],
            capture_output=True, text=True, timeout=180)
    except (OSError, subprocess.SubprocessError):
        return out
    if res.returncode != 0:
        return out
    for line in res.stdout.splitlines():
        stamp, _, subject = line.partition("\t")
        m = JOB_ID.search(subject)
        if m and stamp.strip().isdigit():
            out.setdefault(m.group(1), float(stamp.strip()))
    return out


# --- Claude sessions ------------------------------------------------------------

def _encode_project(path: str) -> str:
    """Claude's project directory name for a checkout path."""
    return re.sub(r"[^A-Za-z0-9]", "-", str(path).rstrip("\\/"))


def _project_dirs(root: str, repo_root: str) -> set[str]:
    """Project directories under ``root`` that belong to this repo (and its worktrees)."""
    enc = _encode_project(repo_root)
    parent = os.path.dirname(str(repo_root).rstrip("\\/"))
    worktrees = _encode_project(os.path.join(parent, "IDM-worktrees"))
    keep = set()
    try:
        names = os.listdir(root)
    except OSError:
        return keep
    for name in names:
        if os.path.isdir(os.path.join(root, name)) and (
                name == enc or name.startswith(enc + "-") or name.startswith(worktrees)):
            keep.add(name)
    return keep


def _account(name: str, repo_root: str) -> str:
    """The account prefix of a launcher title such as ``neo-Info_Diffusion_Model``."""
    n = (name or "").strip()
    repo = os.path.basename(str(repo_root).rstrip("\\/"))
    for tail in {repo, repo.replace("_", "-"), repo.replace("-", "_")}:
        if n == tail:
            return ""
        if n.endswith("-" + tail):
            return n[:-(len(tail) + 1)]
    return ""


def read_claude_sessions(roots: list[str], repo_root: str) -> list[dict]:
    """One row per transcript for this repo, usage counted once per message id.

    ``~/.claude/projects`` and ``~/.claude-neo/projects`` are the same junction; the
    roots are deduplicated on their resolved path so no transcript is counted twice.
    """
    unique: dict[str, str] = {}
    for root in roots:
        if root and os.path.isdir(root):
            unique.setdefault(os.path.realpath(root), root)
    rows: list[dict] = []
    for root in unique.values():
        allowed = _project_dirs(root, repo_root)
        data = TUR.read_claude(root, None)
        for rel, store in sorted((data.get("sessions") or {}).items()):
            if rel.split("/")[0] not in allowed:
                continue
            calls = store.get("calls") or []
            mix = collections.Counter(tool_class(c.get("tool")) for c in calls)
            first_edit = next((i for i, c in enumerate(calls) if c.get("cls") == TUR.EDIT),
                              None)
            started, ended = store.get("started"), store.get("ended")
            row = {
                "session_id": os.path.basename(rel).replace(".jsonl", ""),
                "account": _account(store.get("name"), repo_root),
                "started": _iso(started),
                "finished": _iso(ended),
                "minutes": round((ended - started) / 60.0, 2) if started and ended else None,
                "steps": store.get("steps") or 0,
                "tool_calls_total": len(calls),
                "calls_before_first_edit": first_edit,
                "input_tokens": store.get("in"),
                "cache_read_tokens": store.get("cache_read"),
                "cache_creation_tokens": store.get("cache_creation"),
                "output_tokens": store.get("out"),
                "thinking_tokens": store.get("thinking"),
                "code_edits": sum(1 for c in calls if c.get("cls") == TUR.EDIT),
                "files_edited": len(store.get("edited") or ()),
                "file": rel,
            }
            for cls in MIX:
                row["calls_" + cls.replace("-", "_")] = mix.get(cls, 0)
            rows.append(row)
    rows.sort(key=lambda r: r.get("started") or "")
    return rows


# --- reviews, trends and the workbook -------------------------------------------

def load_reviews(path: str) -> dict[str, dict]:
    """Review objects from ``worker_reviews.jsonl`` keyed by ``id`` (later line wins)."""
    reviews: dict[str, dict] = {}
    for line in TUR._iter_lines(path):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if isinstance(obj, dict) and obj.get("id"):
            reviews[str(obj["id"])] = obj
    return reviews


def attach_job_types(workers: list[dict], reviews: dict[str, dict]) -> None:
    """The only place a worker's job type is set: from Claude's review row."""
    for row in workers:
        row["job_type"] = str((reviews.get(row["job_id"]) or {}).get("job_type") or "")


def review_rows(workers: list[dict], sessions: list[dict], reviews: dict[str, dict]) -> list[dict]:
    """Workers, sessions and review-only ids, with ``review due`` where no review exists."""
    measured: dict[str, tuple[str, dict]] = {}
    for row in workers:
        measured[row["job_id"]] = ("worker", row)
    for row in sessions:
        measured[row["session_id"]] = ("session", row)
    rows = []
    for ident, (kind, src) in measured.items():
        # Claude writes a session review id as ``session-<uuid>``; the transcript carries
        # the bare uuid, so accept either spelling as the join key.
        rev = reviews.get(ident) or reviews.get("session-" + ident) or {}
        row = {
            "id": ident, "kind": kind,
            "review_status": "reviewed" if rev else "review due",
            "model": src.get("model", ""),
            "outcome": src.get("outcome", ""),
            "tool_calls_actual": src.get("tool_calls_actual"),
            "calls_before_first_edit": (src.get("calls_before_first_edit_events")
                                        if kind == "worker" else src.get("calls_before_first_edit")),
            "output_tokens": src.get("output_tokens"),
            "minutes": src.get("minutes"),
            "changed_files": src.get("changed_files"),
        }
        for key in REVIEW_KEYS:
            row[key] = rev.get(key, "")
        rows.append(row)
    for ident, rev in reviews.items():
        if ident in measured or (ident.startswith("session-") and ident[8:] in measured):
            continue
        row = {"id": ident, "kind": "", "review_status": "reviewed"}
        for key in REVIEW_KEYS:
            row[key] = rev.get(key, "")
        rows.append(row)
    return rows


def trend_rows(workers: list[dict]) -> list[dict]:
    """Medians by day and by job type (job type is reviewed jobs only)."""
    def med(rows, key):
        values = [r[key] for r in rows if isinstance(r.get(key), (int, float))]
        return TUR._pct(values, 0.5) if values else None

    def share_over(rows):
        known = [r["over_budget_total"] for r in rows
                 if isinstance(r.get("over_budget_total"), bool)]
        return round(sum(1 for v in known if v) / len(known), 3) if known else None

    def per_line(rows):
        values = []
        for r in rows:
            tokens = r.get("output_tokens")
            lines = (r.get("lines_added") or 0) + (r.get("lines_removed") or 0)
            if isinstance(tokens, (int, float)) and lines > 0:
                values.append(tokens / lines)
        return TUR._pct(values, 0.5) if values else None

    groups: list[tuple[str, str, list[dict]]] = []
    by_day: dict[str, list[dict]] = collections.defaultdict(list)
    by_type: dict[str, list[dict]] = collections.defaultdict(list)
    for row in workers:
        if row.get("started"):
            by_day[row["started"][:10]].append(row)
        by_type[row.get("job_type") or "(unreviewed)"].append(row)
    for day in sorted(by_day):
        groups.append(("day", day, by_day[day]))
    for jt in sorted(by_type):
        groups.append(("job_type", jt, by_type[jt]))
    return [{
        "group": group, "key": key, "jobs": len(rows),
        "median_tool_calls": med(rows, "tool_calls_actual"),
        "median_calls_before_first_edit": med(rows, "calls_before_first_edit_events"),
        "median_output_tokens": med(rows, "output_tokens"),
        "median_minutes": med(rows, "minutes"),
        "median_tokens_per_changed_line": per_line(rows),
        "share_over_budget": share_over(rows),
    } for group, key, rows in groups]


def build(args) -> dict:
    jobs_root = args.jobs_root or TUR.DEFAULT_ROOTS["dsh"]
    repo_root = args.repo_root or discover_repo_root(jobs_root) or os.getcwd()
    reviews_path = _reviews_path(args)
    merge_times = read_merge_times(repo_root)
    numstat_cache: dict = {}
    workers = []
    try:
        names = sorted(os.listdir(jobs_root))
    except OSError:
        names = []
    for name in names:
        job_dir = os.path.join(jobs_root, name)
        if os.path.isdir(job_dir):
            workers.append(read_job(job_dir, repo_root, merge_times, numstat_cache))
    reviews = load_reviews(reviews_path)
    attach_job_types(workers, reviews)
    sessions = read_claude_sessions(args.claude_roots, repo_root)
    sheets = [
        ("Workers", WORKER_COLUMNS, workers),
        ("Claude", CLAUDE_COLUMNS, sessions),
        ("Reviews", REVIEW_COLUMNS, review_rows(workers, sessions, reviews)),
        ("Trends", TREND_COLUMNS, trend_rows(workers)),
    ]
    if args.out:
        write_xlsx(args.out, sheets)
    return {"workers": workers, "sessions": sessions, "reviews": reviews,
            "sheets": sheets, "repo_root": repo_root}


def _cell(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return value
    if isinstance(value, float):
        return round(value, 3)
    return value


def write_xlsx(path: str, sheets: list[tuple[str, list[tuple[str, str]], list[dict]]]) -> None:
    """Write one sheet per source, header row frozen, column widths fitted."""
    from openpyxl import Workbook
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter

    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    book = Workbook()
    book.remove(book.worksheets[0])
    for title, columns, rows in sheets:
        sheet = book.create_sheet(title)
        sheet.append([header for header, _ in columns])
        for row in rows:
            sheet.append([_cell(row.get(key)) for _, key in columns])
        sheet.freeze_panes = "A2"
        for cell in sheet[1]:
            cell.font = Font(bold=True)
        for idx, (header, _) in enumerate(columns, start=1):
            width = len(str(header))
            for row in rows[:300]:
                width = max(width, len(str(_cell(row.get(columns[idx - 1][1])))))
            sheet.column_dimensions[get_column_letter(idx)].width = min(width + 2, 60)
    book.save(path)


def _reviews_path(args) -> str:
    """Explicit path, else the main checkout's review file, else this checkout's."""
    if args.reviews:
        return args.reviews
    repo = args.repo_root or discover_repo_root(getattr(args, "jobs_root", "") or TUR.DEFAULT_ROOTS["dsh"])
    candidates = []
    if repo:
        candidates.append(os.path.join(repo, "tasks", "efficiency", "worker_reviews.jsonl"))
    candidates.append(os.path.join(os.getcwd(), "tasks", "efficiency", "worker_reviews.jsonl"))
    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate
    return candidates[0]


def last(args) -> int:
    reviews_path = _reviews_path(args)
    reviews = list(load_reviews(reviews_path).values())
    if not reviews:
        print(f"no reviews at {reviews_path}")
        return 0
    for rev in reviews[-max(1, args.n):]:
        print(f"{rev.get('id')}  [{rev.get('job_type') or 'no job type'}]")
        for key in ("prompt_change", "permission_change", "scope_change"):
            value = rev.get(key)
            if value is None or value == "":
                value = "(none)"
            elif not isinstance(value, str):
                value = json.dumps(value, ensure_ascii=False)
            print(f"  {key}: {value}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "worker review").splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    build_cmd = sub.add_parser("build", help="measure every job and session into one xlsx")
    build_cmd.add_argument("--out", default="tasks/efficiency/WORKER_REVIEW_LOG.xlsx")
    build_cmd.add_argument("--jobs-root", default="")
    build_cmd.add_argument("--reviews", default="")
    build_cmd.add_argument("--repo-root", default="")
    build_cmd.add_argument("--claude-root", action="append", dest="claude_roots", default=[])
    build_cmd.set_defaults(func=_build_command)

    last_cmd = sub.add_parser("last", help="print the last N reviews' changes")
    last_cmd.add_argument("--n", type=int, default=5)
    last_cmd.add_argument("--reviews", default="")
    last_cmd.add_argument("--repo-root", default="")
    last_cmd.set_defaults(func=last)

    args = parser.parse_args(argv)
    if args.command == "build" and not args.claude_roots:
        home = os.path.expanduser("~")
        args.claude_roots = [os.path.join(home, ".claude", "projects"),
                             os.path.join(home, ".claude-neo", "projects")]
    return args.func(args)


def _build_command(args) -> int:
    result = build(args)
    workers = result["workers"]
    reviewed = sum(1 for row in workers if row["job_type"])
    due = sum(1 for row in workers if not row["job_type"])
    print(f"jobs {len(workers)} ({reviewed} typed by a review, {due} blank) · "
          f"claude sessions {len(result['sessions'])} · reviews {len(result['reviews'])}")
    print(f"repo {result['repo_root']}")
    if args.out:
        print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
