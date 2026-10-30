"""Measure tool use and token spend across every agent source (read-only).

Sources
-------
* ``dsh``     — ``plugins/dsh-worker/runtime/jobs/*/result.md.events.jsonl`` plus
  ``progress.jsonl``/``status.json`` for provider-reported output tokens, model steps
  and first-edit metadata.
* ``claude``  — ``~/.claude/projects/**/*.jsonl`` (assistant ``tool_use`` blocks, usage
  deduplicated on ``message.id``), including ``subagents/``.
* ``opencode``— ``~/.local/share/opencode/opencode.db`` (+ WAL).  The live file is never
  opened: the three files are copied to ``.tmp`` first and only the copy is read.
* ``codex``   — ``~/.codex/sessions`` when present.

Every tool call is classified by *route* (dedicated tool vs shell) and *class*.  Waste is
counted by named detectors whose formula is printed with the number.  Nothing outside
``--out`` is written and no message text leaves this script: only truncated command
prefixes, redacted.
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import random
import re
import shutil
import sqlite3
import sys
from datetime import datetime, timezone

CHANGE_TS = "2026-10-29T22:45:00+00:00"  # 2026-10-30 04:15 IST code-intel rollout
CHARS_PER_TOKEN = 4

LSP_NAV = "LSP navigation"
LSP_DIAG = "LSP diagnostics"
PY_WHOLE = ".py read whole file"
PY_RANGED = ".py read ranged"
READ_OTHER = "other file reads"
SH_READ = "shell file read"
SH_SEARCH = "shell search"
SH_LIST = "shell list/stat"
PY_DB = "inline Python DB query"
PY_OTHER = "inline Python other"
SQL_TOOL = "sql tool query"
SCHEMA = "schema probe (any route)"
RD_OTHER = "other reality-data tools"
TESTS = "tests/compile"
BENCH = "bench or gate runs"
GIT = "git"
EDIT = "edit/write"
SLEEP = "sleep/poll"
WEB = "web"
CTRL = "subagent or worker control"
OTHER = "other"

CLASSES = [LSP_NAV, LSP_DIAG, PY_WHOLE, PY_RANGED, READ_OTHER, SH_READ, SH_SEARCH,
           SH_LIST, PY_DB, PY_OTHER, SQL_TOOL, SCHEMA, RD_OTHER, TESTS, BENCH, GIT,
           EDIT, SLEEP, WEB, CTRL, OTHER]

READ_ONLY = {LSP_NAV, LSP_DIAG, PY_WHOLE, PY_RANGED, READ_OTHER, SH_READ, SH_SEARCH,
             SH_LIST, SQL_TOOL, SCHEMA, RD_OTHER, GIT}

# Classes whose shell route the dedicated read/grep/LSP tool could have served (detector b).
SHELL_SERVABLE = {SH_READ, SH_SEARCH, SH_LIST}

DEFAULT_ROOTS = {
    "dsh": r"C:\Users\warri\Downloads\Info_Diffusion_Model\plugins\dsh-worker\runtime\jobs",
    "claude": r"C:\Users\warri\.claude\projects",
    "opencode": r"C:\Users\warri\.local\share\opencode",
    "codex": r"C:\Users\warri\.codex\sessions",
}

# --- classification -------------------------------------------------------------

_PY = re.compile(r"\.py$", re.I)
_SCHEMA_HINT = re.compile(
    r"sqlite_master|\bpragma\s|information_schema|table_info\s*\(|"
    r"\.schema\b|\bdesc(ribe)?\s+(table|view)\b|show\s+tables", re.I)
_DB_HINT = re.compile(
    r"sqlite3|duckdb|connect_ro|sqlite_master|table_info\s*\(|\bcursor\b|"
    r"\bpragma\s+(table_info|index_list|foreign_key_list|database_list)|"
    r"\bselect\b(?!-)[^\n]*\bfrom\b", re.I)
_PY_INVOKE = re.compile(
    r"\b((?:python[\d.]*|py)(?:\.exe)?)\s+"
    r"((?:-{1,2}[\w.-]+\s+)*"
    r"(?:-c\b|-\s*<<|-m\s+[\w.]+|-\s|[\"']?[\w./\\:()-]+\.py\b|--version\b|--help\b))", re.I)
_HEREDOC_PY = re.compile(
    r"@['\"]\s*\n?\s*(?:from\s+\w+\s+import|import\s+\w+|def\s+\w+\(|print\()|"
    r"<<-?\s*['\"]?(\w+)['\"]?\s*\n\s*(?:from\s|import\s|def\s|print\()", re.I)
_PY_RUN = re.compile(r"\b(?:python[\d.]*|py)(?:\.exe)?\s+[\"']?([\w./\\:-]+\.py)", re.I)
_TEST_HINT = re.compile(
    r"\bpytest\b|\bunittest\b|\bpy_compile\b|\bcompileall\b|\btox\b|\bnox\b|"
    r"\btest_[a-z0-9_]+\.py\b|run_full_suite", re.I)
_BENCH_HINT = re.compile(
    r"(?:python[\d.]*|py|pwsh|powershell)(?:\.exe)?\s+(?:-[^\s]+\s+)*[^\n;|&]*?"
    r"(bench_[a-z0-9_]+\.py|gate_run\.py|grade_v1\.py|run_bench\.py|run_instances\.py|"
    r"answer_bench[\\/][a-z0-9_]+\.py)|\bimport\s+run_bench\b", re.I)
_GIT = re.compile(r"(?:^|[;&|=\s])git(?:\.exe)?\s+(?!grep\b)\w", re.I)
_SLEEP = re.compile(
    r"\bstart-sleep\b|\bsleep\s+\d|\btimeout\s+/t\b|\bwaitfor\b|\bwait-event\b|"
    r"\bsleep\s+-s\b|\bjob_output\b|\bpoll\b|"
    r"\b(?:until|while)\b[^\n]{0,120}\bsleep\b", re.I)
_SH_READ = re.compile(
    r"\bget-content\b|\bgc\s+-|\bcat\s+(?!>)|(?:^|\s)type\s+[^|]|\bhead\s+-n?\s*\d+|"
    r"\bhead\s+-c\s*\d+|\btail\s+-n?\s*\d+|\btail\s+-c\s|\bsed\s+-n\b|\bawk\s|\bless\s+[\\/]|"
    r"\bformat-hex\b|\bxxd\b|\bimport-code\b", re.I)
_SH_EDIT = re.compile(
    r"\bset-content\b|\badd-content\b|\bsed\s+-i\b|(?:^|[;&|]\s*)"
    r"(?:cat|type|printf)\s+[^|]*>|\b(?:echo|write-output)\b[^|]*>>|"
    r"\bwrite_text\b|\bopen\([^)]*['\"]w['\"]|\.write\(", re.I)
_SH_SEARCH = re.compile(
    r"\bselect-string\b|\bfindstr\b|(?:^|[\s;|&])rg(?:\s|$)|\bgrep\b|"
    r"\bgit\s+grep\b|\bfind\s+\S+\s+-i?name\b", re.I)
_SH_LIST = re.compile(
    r"\bget-childitem\b|\bgci\b|\bls\b|(?:^|[\s;&|(])dir(?:\s|$)|\btest-path\b|"
    r"\bmeasure-object\b|\bwc\s+-l\b|\bget-item\b|\bstat\b|\bresolve-path\b|"
    r"\bwhere\.exe\b|\bget-filehash\b|\bget-acl\b|\bdu\s+-s|\bget-ciminstance\b|"
    r"\bget-process\b|\bget-service\b|\bget-psdrive\b|\bget-volume\b|\bget-command\b|"
    r"\bget-module\b|\bget-member\b|\bget-variable\b|\bget-nettcpconnection\b", re.I)
_TOOLBELT_DATA = re.compile(
    r"-m\s+reality_engine\.toolbelt\.(lookup_docs|lookup_market|coverage_peek|find_docs|"
    r"sample_rows|job_peek)", re.I)
_PIPE_TO_SEARCH = re.compile(
    r"(?:get-content|gc\s+-|cat\s+|type\s+|sed\s+-n)[^|;]*\|\s*(?:select-string|findstr|rg\b|grep\b)",
    re.I)
_POLL_LOOP = re.compile(r"\b(?:until|while)\b[\s\S]{0,4000}\bsleep\b", re.I)

# Tie-break order when two operations start at the same offset.
_PRIORITY = [SCHEMA, PY_DB, RD_OTHER, TESTS, BENCH, GIT, EDIT, SLEEP, SH_READ, SH_SEARCH,
             SH_LIST, PY_OTHER, OTHER]


def _shell_positions(cmd: str) -> dict:
    """First offset of every class's trigger, so the first operation in the command wins."""
    pos = {}

    def see(cls, m):
        if m:
            pos[cls] = min(pos.get(cls, 1 << 30), m.start())

    see(SCHEMA, _SCHEMA_HINT.search(cmd))
    # inline Python: the class belongs at the python token, not at the heredoc marker
    inv = _PY_INVOKE.search(cmd)
    inline = False
    if inv:
        what = (inv.group(2) or "").strip().lower()
        inline = what.startswith("-c") or (what.startswith("-") and not what.startswith("-m"))
    hed = _HEREDOC_PY.search(cmd)
    code_len = 0
    edit_m = _SH_EDIT.search(cmd)
    db_m = _DB_HINT.search(cmd)
    writes_first = bool(edit_m) and (not db_m or edit_m.start() < db_m.start())
    if inline and inv is not None:
        code_len = len(cmd[inv.start():])
        if writes_first:
            see(EDIT, inv)
        elif db_m:
            see(PY_DB, inv)
        else:
            see(PY_OTHER, inv)
    elif hed is not None:
        code_len = len(cmd[hed.start():])
        if writes_first:
            see(EDIT, hed)
        elif db_m:
            see(PY_DB, hed)
        else:
            see(PY_OTHER, hed)
    where = None
    if inv is not None:
        where = inv.start(1)
    elif hed is not None:
        where = hed.start()
    # a schema probe inside an inline program is still a schema probe
    if _SCHEMA_HINT.search(cmd) and where is not None:
        pos[SCHEMA] = min(pos.get(SCHEMA, 1 << 30), where)
    see(RD_OTHER, _TOOLBELT_DATA.search(cmd))
    see(TESTS, _TEST_HINT.search(cmd))
    bm = _BENCH_HINT.search(cmd)
    if bm:
        try:
            bp = bm.start(1) if bm.lastindex else bm.start()
        except (IndexError, TypeError):
            bp = bm.start()
        pos[BENCH] = min(pos.get(BENCH, 1 << 30), bp)
    see(GIT, _GIT.search(cmd))
    see(EDIT, _SH_EDIT.search(cmd))
    see(SLEEP, _SLEEP.search(cmd))
    see(SH_READ, _SH_READ.search(cmd))
    see(SH_SEARCH, _SH_SEARCH.search(cmd))
    see(SH_LIST, _SH_LIST.search(cmd))
    if inv:
        see(PY_OTHER, inv)
    # the toolbelt lookups are reality-data reads, at the python token
    if _TOOLBELT_DATA.search(cmd) and inv:
        pos[RD_OTHER] = min(pos.get(RD_OTHER, 1 << 30), inv.start(1))
    # a read piped into a search is a search, whatever its first verb
    piped = _PIPE_TO_SEARCH.search(cmd)
    if piped:
        pos[SH_SEARCH] = min(pos.get(SH_SEARCH, 1 << 30), piped.start())
        pos.pop(SH_READ, None)
    # a wait loop that runs a check and sleeps is a poll, not a query
    poll = _POLL_LOOP.search(cmd)
    if poll and SCHEMA not in pos and PY_DB not in pos:
        return {SLEEP: poll.start()}
    # writing a file is the command's point even when it reads the file first
    if EDIT in pos and PY_DB not in pos and SCHEMA not in pos:
        return {EDIT: 0}
    # running a test or a bench script beats the generic "python script" reading
    for special in (TESTS, BENCH):
        if special in pos and PY_OTHER in pos:
            pos[PY_OTHER] = 1 << 30
    # a long inline program is what the command is for, whatever it reads first
    if code_len >= 200 and where is not None:
        forced = min((c for c in (PY_DB, EDIT, PY_OTHER) if c in pos),
                     key=lambda c: _PRIORITY.index(c))
        return {forced: where}
    return pos


def classify_shell_explain(cmd: str) -> tuple[str, str]:
    """(class, the text that triggered it) — the trigger makes the sample auditable."""
    cmd = cmd or ""
    pos = _shell_positions(cmd)
    if not pos:
        return OTHER, ""
    cls = min(pos, key=lambda c: (pos[c], _PRIORITY.index(c)))
    p = min(max(0, pos[cls]), max(0, len(cmd) - 1))
    return cls, cmd[p:p + 90]


def classify_shell(cmd: str) -> str:
    """Classify one shell command string: the first operation in it decides."""
    return classify_shell_explain(cmd)[0]


def classify_tool(tool: str, inp: dict) -> tuple[str, str]:
    """Return (class, route) for a dedicated tool call."""
    t = (tool or "").strip()
    low = t.lower()
    if low.startswith("mcp__code-intel__"):
        return (LSP_DIAG if "diagnostic" in low else LSP_NAV), "tool"
    if low.startswith("mcp__reality-data__"):
        if low.endswith("__sql"):
            q = str((inp or {}).get("query") or "")
            return (SCHEMA if _SCHEMA_HINT.search(q) else SQL_TOOL), "tool"
        if low.endswith("__catalog"):
            return SCHEMA, "tool"
        return RD_OTHER, "tool"
    if low in ("read", "read_file"):
        path = str((inp or {}).get("file_path") or (inp or {}).get("path") or "")
        off = (inp or {}).get("offset")
        lim = (inp or {}).get("limit")
        whole = not off and not lim or (lim and int(lim) >= 1500 and not off)
        if _PY.search(path):
            return (PY_WHOLE if whole else PY_RANGED), "tool"
        return READ_OTHER, "tool"
    if low in ("edit", "write", "multi_edit", "multiedit", "notebook_edit",
               "notebookedit", "apply_patch", "str_replace_editor"):
        return EDIT, "tool"
    if low in ("grep",):
        return SH_SEARCH, "tool"
    if low in ("glob",):
        return SH_LIST, "tool"
    if low in ("bash", "powershell", "pwsh", "shell", "run_command", "execute_command"):
        return classify_shell(str((inp or {}).get("command") or (inp or {}).get("cmd") or "")), "shell"
    if low in ("web_search", "web_fetch", "websearch", "webfetch") or low.startswith("mcp__claude_browser__"):
        return WEB, "tool"
    if low in ("job_output", "job_list"):
        return SLEEP, "tool"
    if (low in ("subagent", "subagent_fork", "agent", "task", "send_message", "sendmessage",
                "list_agents", "listagents", "interrupt_agent", "taskstop", "monitor",
                "job_kill", "create_goal", "update_goal", "get_goal", "subagenthandback")
            or low.startswith("mcp__dsh-worker__") or low.startswith("cron")):
        return CTRL, "tool"
    return OTHER, "tool"


# --- privacy --------------------------------------------------------------------

_SECRETS = [
    re.compile(r"sk-[A-Za-z0-9_-]{8,}"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/-]{8,}=*"),
    re.compile(r"(?i)\b(api[_-]?key|token|secret|password|pwd)\s*[=:]\s*[^\s\"']{6,}"),
    re.compile(r"\b[0-9a-fA-F]{32,}\b"),
    re.compile(r"\b[A-Za-z0-9+/]{40,}={0,2}\b"),
]


def redact(text: str) -> str:
    for rx in _SECRETS:
        text = rx.sub("<redacted>", text)
    return text


def prefix(text: str, n: int = 160) -> str:
    text = " ".join(str(text or "").split())
    return redact(text[:n] + ("…" if len(text) > n else ""))


# --- small helpers --------------------------------------------------------------

def _ts(value) -> float | None:
    """Parse ISO-8601 or epoch-ms into epoch seconds (UTC)."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        v = float(value)
        return v / 1000.0 if v > 1e11 else v
    s = str(value)
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s).timestamp()
    except ValueError:
        return None


def _file_lines(path: str, cache: dict) -> int | None:
    if not path:
        return None
    if path in cache:
        return cache[path]
    n = None
    try:
        if os.path.isfile(path) and os.path.getsize(path) <= 32 * 1024 * 1024:
            with open(path, encoding="utf-8", errors="replace") as fh:
                n = sum(1 for _ in fh)
    except OSError:
        n = None
    cache[path] = n
    return n


def _pct(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    i = min(len(s) - 1, max(0, int(round(q * (len(s) - 1)))))
    return s[i]


def _session() -> dict:
    return {"steps": 0, "calls": [], "in": 0, "cache_read": 0, "cache_creation": 0,
            "out": 0, "thinking": 0, "cost": 0.0, "provider_out": None,
            "started": None, "ended": None, "name": "", "edited": set(), "first_edit": None,
            "truncated": 0}


def _call(session: dict, cls: str, route: str, tool: str, step: int, out_chars: int,
          ok: bool, target: str = "", cmd: str = "") -> dict:
    c = {"cls": cls, "route": route, "tool": tool, "step": step, "chars": out_chars,
         "ok": ok, "target": (target or "")[:4000], "cmd": (cmd or "")[:4000]}
    session["calls"].append(c)
    return c


# --- dsh -------------------------------------------------------------------------

def read_dsh(root: str, since: float | None) -> dict:
    jobs = {}
    if not os.path.isdir(root):
        return {"present": False, "sessions": {}}
    for name in sorted(os.listdir(root)):
        jd = os.path.join(root, name)
        if not os.path.isdir(jd):
            continue
        ev = os.path.join(jd, "result.md.events.jsonl")
        status = _load_json(os.path.join(jd, "status.json"))
        started = _ts((status or {}).get("started_at")) or _ts(name.split("-")[0])
        if since and started and started < since:
            continue
        if not os.path.exists(ev):
            continue
        s = _session()
        s["name"] = name
        s["started"] = started
        s["ended"] = _ts((status or {}).get("finished_at"))
        prog = _last_jsonl(os.path.join(jd, "progress.jsonl"))
        if prog:
            s["provider_out"] = prog.get("output_tokens")
            s["provider_steps"] = prog.get("model_steps")
            s["model_steps"] = prog.get("model_steps") or 0
            s["tool_calls_reported"] = prog.get("tool_calls")
            s["before_first_edit"] = prog.get("tool_calls_before_first_edit")
        s["before_first_edit"] = s.get("before_first_edit") or (status or {}).get("tool_calls_before_first_edit")
        fe = _ts((status or {}).get("first_edit_at"))
        s["first_edit"] = fe
        if started and fe:
            s["seconds_to_first_edit"] = max(0.0, fe - started)
        step = -1
        new_step = True
        pending = {}
        step_out = collections.Counter()
        for line in _iter_lines(ev):
            if not line.strip():
                continue
            try:
                e = json.loads(line)
            except ValueError:
                continue
            t = e.get("type")
            if t == "tool_call":
                if new_step:
                    step += 1
                    new_step = False
                inp = e.get("input") or {}
                cls, route = classify_tool(e.get("tool") or "", inp)
                target = str(inp.get("file_path") or inp.get("path") or "")
                cmd = str(inp.get("command") or "")
                call = _call(s, cls, route, e.get("tool") or "", step, 0, True, target, cmd)
                if cls == EDIT and target:
                    s["edited"].add(target)
                pending[e.get("callId")] = call
            elif t == "tool_result":
                call = pending.pop(e.get("callId"), None)
                res = e.get("result")
                text = res if isinstance(res, str) else json.dumps(res)
                ok = e.get("status") != "error" and not _exit_nonzero(text)
                if call is not None:
                    call["chars"] = len(text or "")
                    call["ok"] = ok and call["ok"]
                if e.get("truncated"):
                    s["truncated"] += 1
                new_step = True
            elif t in ("thinking", "text", "final"):
                if new_step:
                    step += 1
                    new_step = False
                if t == "thinking":
                    step_out[step] += len(e.get("text") or "")
                    s["thinking_chars"] = s.get("thinking_chars", 0) + len(e.get("text") or "")
                elif t == "text":
                    step_out[step] += len(e.get("text") or "")
            elif t == "status":
                continue
        s["steps"] = step + 1
        s["step_out_chars"] = dict(step_out)
        jobs[name] = s
    return {"present": True, "sessions": jobs}


def _exit_nonzero(text: str) -> bool:
    m = re.search(r"\[exit code:\s*([1-9]\d*)\]", text or "")
    return bool(m) or bool(re.search(r"(?m)^Exit code:?\s+[1-9]\d*", text or ""))


def _iter_lines(path: str):
    """Stream a text file line by line (never loads it whole)."""
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            yield from fh
    except OSError:
        return


def _load_json(path: str) -> dict | None:
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _last_jsonl(path: str) -> dict | None:
    last = None
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    last = json.loads(line)
                except ValueError:
                    continue
    except OSError:
        return None
    return last


# --- Claude Code ----------------------------------------------------------------

def read_claude(root: str, since: float | None) -> dict:
    sessions = {}
    if not os.path.isdir(root):
        return {"present": False, "sessions": {}}
    files = []
    for dirpath, _dirnames, filenames in os.walk(root):
        for fn in filenames:
            if fn.endswith(".jsonl"):
                files.append(os.path.join(dirpath, fn))
    files.sort()
    for path in files:
        rel = os.path.relpath(path, root).replace(os.sep, "/")
        store = _session()
        store["started"] = None
        seen_ids = set()
        seen_tools = set()
        order = {}
        pending = {}
        name_votes = collections.Counter()
        model_votes = collections.Counter()
        cost_state = None
        first_tool_step = None
        raw_lines = 0
        dup_lines = 0
        try:
            fh = open(path, encoding="utf-8", errors="replace")
        except OSError:
            continue
        with fh:
            for line in fh:
                raw_lines += 1
                if '"type"' not in line:
                    continue
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                t = d.get("type")
                ts = _ts(d.get("timestamp"))
                if ts and store["started"] is None:
                    store["started"] = ts
                if ts:
                    store["ended"] = ts
                if t in ("custom-title", "agent-name"):
                    v = d.get("customTitle") or d.get("agentName")
                    if v:
                        name_votes[v] += 1
                elif t == "cost-state":
                    cost_state = d
                elif t == "assistant":
                    msg = d.get("message") or {}
                    mid = msg.get("id") or ("line-" + str(raw_lines))
                    usage = msg.get("usage") or {}
                    # One API message is split over several lines with the same id, one
                    # content block per line: count usage once, collect every tool_use.
                    if mid in seen_ids:
                        dup_lines += 1
                        idx = order[mid]
                    else:
                        seen_ids.add(mid)
                        idx = len(order)
                        order[mid] = idx
                        model_votes[msg.get("model") or "?"] += 1
                        store["out"] += int(usage.get("output_tokens") or 0)
                        store["in"] += int(usage.get("input_tokens") or 0)
                        store["cache_read"] += int(usage.get("cache_read_input_tokens") or 0)
                        store["cache_creation"] += int(usage.get("cache_creation_input_tokens") or 0)
                        details = usage.get("output_tokens_details") or {}
                        store["thinking"] += int(details.get("thinking_tokens") or 0)
                        store.setdefault("step_out", {})[idx] = int(usage.get("output_tokens") or 0)
                    for b in msg.get("content") or []:
                        if not isinstance(b, dict) or b.get("type") != "tool_use":
                            continue
                        if b.get("id") in seen_tools:
                            continue
                        seen_tools.add(b.get("id"))
                        inp = b.get("input") or {}
                        cls, route = classify_tool(b.get("name") or "", inp)
                        target = str(inp.get("file_path") or inp.get("path") or "")
                        cmd = str(inp.get("command") or "")
                        if cls == EDIT and first_tool_step is None:
                            first_tool_step = idx
                        call = _call(store, cls, route, b.get("name") or "", idx, 0, True, target, cmd)
                        if cls == EDIT and target:
                            store["edited"].add(target)
                        call["_id"] = b.get("id")
                        pending[b.get("id")] = call
                elif t == "user":
                    for b in (d.get("message") or {}).get("content") or []:
                        if not isinstance(b, dict) or b.get("type") != "tool_result":
                            continue
                        call = pending.pop(b.get("tool_use_id"), None)
                        text = _result_text(b)
                        err = bool(b.get("is_error")) or _exit_nonzero(text)
                        if call is not None:
                            call["chars"] = len(text)
                            call["ok"] = not err
        store["steps"] = len(order)
        store["duplicate_lines"] = dup_lines
        store["name"] = name_votes.most_common(1)[0][0] if name_votes else os.path.basename(path)[:8]
        store["model"] = model_votes.most_common(1)[0][0] if model_votes else "?"
        store["file"] = rel
        store["cost_state"] = cost_state
        if cost_state:
            mu = cost_state.get("modelUsage") or {}
            store["provider_out"] = sum(int(v.get("outputTokens") or 0) for v in mu.values())
            store["provider_in"] = sum(int(v.get("inputTokens") or 0) for v in mu.values())
            store["provider_cache_read"] = sum(int(v.get("cacheReadInputTokens") or 0) for v in mu.values())
            store["provider_cache_creation"] = sum(int(v.get("cacheCreationInputTokens") or 0) for v in mu.values())
            store["provider_thinking"] = sum(int(v.get("thinkingTokens") or 0) for v in mu.values())
            store["cost"] = float(cost_state.get("totalCostUSD") or 0.0)
            store["api_seconds"] = float(cost_state.get("totalAPIDuration") or 0.0)
            store["tool_seconds"] = float(cost_state.get("totalToolDuration") or 0.0)
        if store["started"] and since and store["started"] < since:
            continue
        if store["steps"] or store["calls"]:
            sessions[rel] = store
    return {"present": True, "sessions": sessions, "files": len(files)}


def _result_text(block: dict) -> str:
    c = block.get("content")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        out = []
        for part in c:
            if isinstance(part, dict):
                out.append(part.get("text") or "")
            elif isinstance(part, str):
                out.append(part)
        return "".join(out)
    return "" if c is None else str(c)


# --- OpenCode -------------------------------------------------------------------

def read_opencode(root: str, since: float | None, workspace: str) -> dict:
    db = os.path.join(root, "opencode.db")
    if not os.path.isfile(db):
        return {"present": False, "sessions": {}}
    tmp = os.path.join(workspace, ".tmp", "opencode_copy")
    os.makedirs(tmp, exist_ok=True)
    for f in ("opencode.db", "opencode.db-wal", "opencode.db-shm"):
        src = os.path.join(root, f)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(tmp, f))
    sessions = {}
    try:
        conn = sqlite3.connect(os.path.join(tmp, "opencode.db"))
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "select * from session_v2 order by time_created").fetchall()
        parts = collections.defaultdict(list)
        try:
            for r in conn.execute("select session_id,type,data from session_message order by seq"):
                parts[r["session_id"]].append((r["type"], json.loads(r["data"] or "{}")))
        except sqlite3.Error:
            pass
        for r in rows:
            started = (r["time_created"] or 0) / 1000.0
            if since and started and started < since:
                continue
            s = _session()
            s["name"] = r["title"] or r["id"]
            s["started"] = started or None
            s["ended"] = (r["time_updated"] or 0) / 1000.0 or None
            try:
                model = json.loads(r["model"] or "{}")
            except ValueError:
                model = {}
            s["model"] = model.get("id") or "?"
            s["provider"] = model.get("providerID") or "?"
            s["cost"] = float(r["cost"] or 0.0)
            s["in"] = int(r["tokens_input"] or 0)
            s["out"] = int(r["tokens_output"] or 0)
            s["thinking"] = int(r["tokens_reasoning"] or 0)
            s["cache_read"] = int(r["tokens_cache_read"] or 0)
            s["cache_creation"] = int(r["tokens_cache_write"] or 0)
            step = 0
            for mtype, data in parts.get(r["id"], []):
                if mtype != "assistant":
                    continue
                s.setdefault("step_out", {})[step] = int((data.get("tokens") or {}).get("output") or 0)
                for b in data.get("content") or []:
                    if not isinstance(b, dict):
                        continue
                    if b.get("type") in ("tool", "tool_call", "tool_use"):
                        inp = b.get("input") or b.get("state") or {}
                        cls, route = classify_tool(b.get("tool") or b.get("name") or "", inp)
                        _call(s, cls, route, b.get("tool") or "", step, 0, True,
                              str(inp.get("filePath") or ""), str(inp.get("command") or ""))
                step += 1
            s["steps"] = step
            sessions[r["id"]] = s
        conn.close()
    except sqlite3.Error as exc:
        return {"present": True, "sessions": {}, "error": str(exc)}
    return {"present": True, "sessions": sessions, "error": None,
            "session_count": len(sessions)}


# --- Codex ----------------------------------------------------------------------

def read_codex(root: str, _since: float | None) -> dict:
    if not os.path.isdir(root):
        return {"present": False, "sessions": {}}
    sessions = {}
    for dirpath, _dn, filenames in os.walk(root):
        for fn in filenames:
            if not fn.endswith(".jsonl"):
                continue
            path = os.path.join(dirpath, fn)
            s = _session()
            s["name"] = os.path.relpath(path, root)
            sessions[s["name"]] = s
    return {"present": True, "sessions": sessions, "note": "raw line scan only"}


# --- aggregation ----------------------------------------------------------------

def _carry(step_out: dict, n_steps: int) -> float:
    """Context-carry tokens: each step's output is re-sent on every later step."""
    total = 0.0
    for step, out in step_out.items():
        total += out * max(0, n_steps - 1 - step)
    return total


def summarise(source: str, raw: dict) -> dict:
    sessions = raw["sessions"]
    n = len(sessions)
    out = {"present": raw.get("present", False), "sessions_n": n,
           "calls_n": 0, "failures": 0, "chars": 0, "truncated": 0,
           "provider_out": 0, "provider_in": 0, "cache_read": 0, "cache_creation": 0,
           "thinking": 0, "thinking_est": 0, "thinking_in_output": True,
           "cost": 0.0, "carry": 0.0, "steps": 0,
           "classes": {}, "top_sessions": [], "share": {}}
    if source == "opencode":
        out["thinking_in_output"] = False  # reasoning is reported beside output
    for name, s in sessions.items():
        out["thinking_est"] += int((s.get("thinking_chars") or 0) / CHARS_PER_TOKEN)
        calls = s["calls"]
        n_steps = s.get("steps") or 0
        # dsh: steps from events, cross-checked with the provider count
        prov_steps = s.get("model_steps") or 0
        if prov_steps:
            n_steps = prov_steps
        step_out = dict(s.get("step_out") or {})
        # dsh allocates provider output across steps by thinking+text share
        if s.get("step_out_chars") and s.get("provider_out"):
            est = s["step_out_chars"]
            total_est = sum(est.values()) or 1
            factor = float(s["provider_out"]) / total_est
            step_out = {int(k): v * factor for k, v in est.items()}
            if not s.get("out"):
                s["out"] = int(s["provider_out"])
        per_step_calls = collections.Counter(c["step"] for c in calls)
        carry = _carry(step_out, n_steps)
        s["carry"] = carry
        s["n_steps"] = n_steps
        out["calls_n"] += len(calls)
        out["chars"] += sum(c["chars"] for c in calls)
        out["failures"] += sum(0 if c["ok"] else 1 for c in calls)
        out["provider_out"] += int(s.get("provider_out") or s.get("out") or 0)
        out["provider_in"] += int(s.get("provider_in") or s.get("in") or 0)
        out["cache_read"] += int(s.get("provider_cache_read") or s.get("cache_read") or 0)
        out["cache_creation"] += int(s.get("provider_cache_creation") or s.get("cache_creation") or 0)
        out["thinking"] += int(s.get("provider_thinking") or s.get("thinking") or 0)
        out["cost"] += float(s.get("cost") or 0.0)
        out["carry"] += carry
        out["steps"] += n_steps
        out["truncated"] += int(s.get("truncated") or 0)
        bucket = out["classes"]
        for c in calls:
            b = bucket.setdefault(c["cls"], {"calls": 0, "failures": 0, "chars": 0,
                                             "est_tokens": 0, "carry": 0.0, "route_shell": 0})
            b["calls"] += 1
            b["failures"] += 0 if c["ok"] else 1
            b["chars"] += c["chars"]
            b["route_shell"] += 1 if c["route"] == "shell" else 0
            if c["step"] in step_out and per_step_calls[c["step"]]:
                b["carry"] += step_out[c["step"]] * max(0, n_steps - 1 - c["step"]) / per_step_calls[c["step"]]
        out["top_sessions"].append({
            "id": name, "name": s.get("name") or "", "steps": n_steps,
            "calls": len(calls), "provider_out": int(s.get("provider_out") or s.get("out") or 0),
            "provider_in": int(s.get("provider_in") or s.get("in") or 0),
            "cache_read": int(s.get("cache_read") or 0), "carry": carry,
            "cost": float(s.get("cost") or 0.0), "started": s.get("started"),
            "model": s.get("model") or "", "before_first_edit": s.get("before_first_edit"),
            "seconds_to_first_edit": s.get("seconds_to_first_edit"),
        })
    for b in out["classes"].values():
        b["est_tokens"] = round(b["chars"] / CHARS_PER_TOKEN)
    out["top_sessions"].sort(key=lambda r: (-(r["carry"] + r["provider_out"]), r["id"]))
    out["top_sessions"] = out["top_sessions"][:10]
    total_class_tokens = sum(b["est_tokens"] for b in out["classes"].values()) or 1
    out["share"] = {c: round(b["est_tokens"] * 100.0 / total_class_tokens, 1)
                    for c, b in out["classes"].items()}
    return out


# --- detectors ------------------------------------------------------------------

def _norm_cmd(c: dict) -> str:
    if c["route"] == "shell":
        return re.sub(r"\s+", " ", c.get("cmd") or "").strip()[:400]
    return re.sub(r"\s+", " ", (c["tool"] + " " + (c.get("target") or "")).strip())[:400]


def detectors(raw_sources: dict) -> dict:
    sessions = []
    for src, raw in raw_sources.items():
        for sid, s in raw["sessions"].items():
            sessions.append((src, sid, s))
    d = {}

    # a. whole-file .py reads on a file the session never edited
    cache = {}
    no_edit = 0
    no_edit_tokens = 0
    edited_reads = 0
    edited_ratios = []
    for src, sid, s in sessions:
        edited = {os.path.normcase(os.path.abspath(t)) for t in s.get("edited", set()) if t}
        edits_by_file = collections.defaultdict(list)
        for c in s["calls"]:
            if c["cls"] == EDIT and c.get("target"):
                edits_by_file[os.path.normcase(os.path.abspath(c["target"]))].append(c)
        for c in s["calls"]:
            if c["cls"] != PY_WHOLE:
                continue
            path = c.get("target") or ""
            lines = _file_lines(path, cache)
            if lines is None or lines < 200:
                continue
            key = os.path.normcase(os.path.abspath(path)) if path else ""
            if key not in edited:
                no_edit += 1
                no_edit_tokens += c["chars"] // CHARS_PER_TOKEN
            else:
                edited_reads += 1
                region = max((len((e.get("cmd") or "").splitlines()) for e in edits_by_file.get(key, [])), default=0)
                if region:
                    edited_ratios.append(lines / region)
    d["a"] = {"count": no_edit, "tokens": no_edit_tokens,
              "edited_whole_reads": edited_reads,
              "edited_ratio_median": round(_pct(edited_ratios, 0.5), 1),
              "formula": "calls: whole-file .py reads with file>=200 lines and file not in the session's edited set; "
                         "tokens: their output chars/4. For files it did edit, median(file lines / lines of the "
                         "largest edit region) is reported instead."}

    # b. shell reads/searches/listings the read/grep/LSP tools could serve
    b_cnt = 0
    b_tok = 0
    b_by = collections.Counter()
    for src, sid, s in sessions:
        for c in s["calls"]:
            if c["route"] == "shell" and c["cls"] in SHELL_SERVABLE:
                b_cnt += 1
                b_tok += c["chars"] // CHARS_PER_TOKEN
                b_by[c["cls"]] += 1
    d["b"] = {"count": b_cnt, "tokens": b_tok, "by_class": dict(b_by),
              "formula": "shell-route calls in shell file read / shell search / shell list-stat, output chars/4."}

    # c. inline DB queries the sql tool could serve
    c_cnt = 0
    c_tok = 0
    for src, sid, s in sessions:
        for c in s["calls"]:
            if c["cls"] == PY_DB:
                c_cnt += 1
                c_tok += c["chars"] // CHARS_PER_TOKEN
    d["c"] = {"count": c_cnt, "tokens": c_tok,
              "formula": "calls classified inline Python DB query, output chars/4."}

    # d. schema probes for a table already in tasks/worker_context/schemas/
    schema_tables = _schema_table_names()
    d_cnt = 0
    d_tok = 0
    hits = collections.Counter()
    for src, sid, s in sessions:
        for c in s["calls"]:
            if c["cls"] != SCHEMA:
                continue
            blob = (c.get("cmd") or "") + " " + (c.get("target") or "")
            low = blob.lower()
            for t in schema_tables:
                if t and t in low:
                    d_cnt += 1
                    d_tok += c["chars"] // CHARS_PER_TOKEN
                    hits[t] += 1
                    break
    d["d"] = {"count": d_cnt, "tokens": d_tok, "tables_hit": dict(hits.most_common(10)),
              "schema_tables": sorted(schema_tables)[:20],
              "formula": "schema-probe calls whose command/target names a store documented in "
                         "tasks/worker_context/schemas/*.md (the file stems), output chars/4."}

    # e. identical commands repeated in one session; same script >=3 times
    e_cnt = 0
    e_tok = 0
    script_runs = []
    for src, sid, s in sessions:
        by_key = collections.defaultdict(list)
        for c in s["calls"]:
            if c["route"] == "shell":
                by_key[_norm_cmd(c)].append(c)
        for calls in by_key.values():
            if len(calls) > 1:
                e_cnt += len(calls) - 1
                e_tok += sum(x["chars"] for x in calls[1:]) // CHARS_PER_TOKEN
        scripts = collections.Counter()
        for c in s["calls"]:
            if c["route"] != "shell":
                continue
            m = _PY_RUN.search(c.get("cmd") or "")
            if m:
                scripts[m.group(1)] += 1
        for name, v in scripts.items():
            if v >= 3:
                script_runs.append({"session": sid, "script": prefix(name, 80), "runs": v})
    d["e"] = {"count": e_cnt, "tokens": e_tok, "scripts_run_3plus": script_runs[:20],
              "formula": "repeated = sum over sessions of (occurrences-1) per identical normalised shell "
                         "command; tokens = chars of the repeats /4. Separate list: .py scripts run >=3x in "
                         "one session."}

    # f. failed calls and the retry that followed
    f_cnt = 0
    f_tok = 0
    sigs = collections.Counter()
    for src, sid, s in sessions:
        calls = s["calls"]
        for c in calls:
            if c["ok"]:
                continue
            f_cnt += 1
            f_tok += c["chars"] // CHARS_PER_TOKEN
            sig = c["cls"] + " :: " + prefix((c.get("cmd") or c.get("target") or c["tool"]), 70)
            sigs[sig] += 1
    d["f"] = {"count": f_cnt, "tokens": f_tok,
              "signatures": [[k, v] for k, v in sigs.most_common(15)],
              "formula": "calls whose status/is_error/exit-code marks them failed; tokens = their output "
                         "chars/4; top-15 signatures = class + 70-char command prefix."}

    # g. consecutive read-only steps that could have been one batch
    g_saved = 0
    g_runs = 0
    g_calls = 0
    for src, sid, s in sessions:
        steps = collections.defaultdict(list)
        for c in s["calls"]:
            steps[c["step"]].append(c)
        run = 0
        for step in sorted(steps):
            if steps[step] and all(x["cls"] in READ_ONLY for x in steps[step]):
                run += 1
                g_calls += len(steps[step])
            else:
                if run >= 2:
                    g_runs += 1
                    g_saved += run - 1
                run = 0
        if run >= 2:
            g_runs += 1
            g_saved += run - 1
    d["g"] = {"count": g_saved, "tokens": 0, "runs": g_runs, "read_only_calls": g_calls,
              "formula": "steps saved = sum over maximal runs of >=2 consecutive model steps whose calls are "
                         "all read-only, of (run length - 1). Each saved step would also have re-sent the "
                         "context, so the token value is the step's carry, reported as 0 here because it is "
                         "already inside context-carry."}

    # h. calls and seconds before the first edit
    h_rows = []
    for src, sid, s in sessions:
        if s.get("before_first_edit") is not None:
            h_rows.append({"source": src, "session": sid, "calls": s["before_first_edit"],
                           "seconds": s.get("seconds_to_first_edit")})
        elif s.get("first_edit") is not None:
            n = 0
            for c in s["calls"]:
                if c["step"] >= s["first_edit"]:
                    break
                n += 1
            h_rows.append({"source": src, "session": sid, "calls": n,
                           "seconds": s.get("seconds_to_first_edit")})
    calls_v = [r["calls"] for r in h_rows if r["calls"] is not None]
    secs_v = [r["seconds"] for r in h_rows if r["seconds"] is not None]
    d["h"] = {"n": len(h_rows),
              "calls_p50": _pct(calls_v, 0.5), "calls_p90": _pct(calls_v, 0.9),
              "calls_mean": round(sum(calls_v) / len(calls_v), 1) if calls_v else 0,
              "calls_max": max(calls_v) if calls_v else 0,
              "seconds_p50": round(_pct(secs_v, 0.5), 1), "seconds_p90": round(_pct(secs_v, 0.9), 1),
              "rows": sorted(h_rows, key=lambda r: -(r["calls"] or 0))[:15],
              "formula": "calls before the first edit/write, per session, from the worker's own "
                         "tool_calls_before_first_edit where present else counted from the transcript; "
                         "seconds = first edit timestamp - session start."}

    # i. tool outputs over 10,000 chars
    i_cnt = 0
    i_tok = 0
    i_sources = collections.Counter()
    for src, sid, s in sessions:
        for c in s["calls"]:
            if c["chars"] > 10000:
                i_cnt += 1
                i_tok += c["chars"] // CHARS_PER_TOKEN
                i_sources[c["cls"] + " :: " + prefix(c.get("cmd") or c.get("target") or c["tool"], 60)] += c["chars"] // CHARS_PER_TOKEN
    d["i"] = {"count": i_cnt, "tokens": i_tok,
              "top_sources": [[k, v] for k, v in i_sources.most_common(15)],
              "formula": "calls with measured output >10,000 chars; tokens = chars/4. Results truncated by "
                         "the writer are a lower bound (see per-source truncated count)."}

    # j. sleep/poll calls and time
    j_cnt = 0
    j_secs = 0.0
    for src, sid, s in sessions:
        for c in s["calls"]:
            if c["cls"] != SLEEP:
                continue
            j_cnt += 1
            for rx in (r"start-sleep\s+(?:-seconds\s+)?(\d+)", r"\bsleep\s+(\d+)",
                       r"timeout\s+/t\s+(\d+)", r"-ss\s+(\d+)"):
                m = re.search(rx, (c.get("cmd") or ""), re.I)
                if m:
                    j_secs += float(m.group(1))
                    break
    d["j"] = {"count": j_cnt, "seconds": round(j_secs, 1),
              "formula": "calls in sleep/poll (sleep, Start-Sleep, timeout /t, job_output/job_list waits); "
                         "seconds = explicit sleep durations only, so it is a lower bound."}
    return d


def _schema_table_names() -> set[str]:
    names = set()
    for root in (os.path.join("tasks", "worker_context", "schemas"),
                 os.path.join(r"C:\Users\warri\Downloads\Info_Diffusion_Model",
                              "tasks", "worker_context", "schemas")):
        if not os.path.isdir(root):
            continue
        for fn in os.listdir(root):
            if fn.endswith(".md"):
                names.add(os.path.splitext(fn)[0].lower())
        break
    return names


# --- before/after ---------------------------------------------------------------

def before_after(raw_dsh: dict) -> dict:
    cut = _ts(CHANGE_TS) or 0.0
    rows = {"before": [], "after": []}
    for sid, s in raw_dsh["sessions"].items():
        started = float(s.get("started") or 0.0)
        bucket = "after" if started >= cut else "before"
        n = len(s["calls"])
        lsp = sum(1 for c in s["calls"] if c["cls"] in (LSP_NAV, LSP_DIAG))
        sql = sum(1 for c in s["calls"] if c["cls"] in (SQL_TOOL, SCHEMA))
        grep = sum(1 for c in s["calls"] if c["tool"].lower() in ("grep", "glob"))
        reads = sum(1 for c in s["calls"] if c["cls"] in (PY_WHOLE, PY_RANGED, READ_OTHER))
        shell = sum(1 for c in s["calls"] if c["route"] == "shell")
        rows[bucket].append({"id": sid, "calls": n, "lsp": lsp, "sql": sql,
                             "grep": grep, "reads": reads, "shell": shell,
                             "started": s.get("started")})
    out = {}
    for bucket, rs in rows.items():
        ns = len(rs)
        calls = sum(r["calls"] for r in rs) or 1
        out[bucket] = {
            "jobs": ns,
            "calls": sum(r["calls"] for r in rs),
            "lsp_calls": sum(r["lsp"] for r in rs),
            "sql_calls": sum(r["sql"] for r in rs),
            "grep_tool_calls": sum(r["grep"] for r in rs),
            "read_calls": sum(r["reads"] for r in rs),
            "shell_calls": sum(r["shell"] for r in rs),
            "lsp_per_job": round(sum(r["lsp"] for r in rs) / ns, 2) if ns else 0,
            "lsp_share_pct": round(100.0 * sum(r["lsp"] for r in rs) / calls, 2),
            "shell_share_pct": round(100.0 * sum(r["shell"] for r in rs) / calls, 2),
            "ids": [r["id"] for r in rs if rs][:5] if bucket == "after" else [],
            "jobs_detail": [{"id": r["id"], "calls": r["calls"], "lsp": r["lsp"],
                             "shell": r["shell"],
                             "started": datetime.fromtimestamp(r["started"], timezone.utc).isoformat(
                                 timespec="minutes") if r["started"] else None}
                            for r in sorted(rs, key=lambda x: x["started"] or 0)],
        }
    return out


def integrity(raw: dict) -> dict:
    """Cross-check the measured sums against a second, independent count."""
    out = {}
    # Claude: deduped line sum vs the client's own per-session aggregate (a live snapshot,
    # so it is exact only where the snapshot was written after the last message).
    diffs = []
    for name, s in raw["claude"]["sessions"].items():
        prov = s.get("provider_out")
        if prov is None:
            continue
        mine = int(s.get("out") or 0)
        diffs.append((abs(mine - int(prov)) / max(1, int(prov)), name, mine, int(prov),
                      int(s.get("steps") or 0)))
    if diffs:
        exact = [d for d in diffs if d[0] <= 0.02]
        big = sorted([d for d in exact if d[4] >= 50], key=lambda d: -d[4]) or exact
        chosen = big[0] if big else min(diffs, key=lambda d: d[0])
        worst = max(diffs)
        out["claude"] = {
            "sessions_with_provider_aggregate": len(diffs),
            "sessions_within_2pct": len(exact),
            "max_abs_diff_pct": round(100.0 * worst[0], 2),
            "chosen_session": os.path.basename(chosen[1]),
            "chosen_steps": chosen[4],
            "chosen_deduped_sum": chosen[2],
            "chosen_provider_aggregate": chosen[3],
            "chosen_diff_pct": round(100.0 * chosen[0], 4),
            "method": "transcript sum of usage over unique message.id vs the provider aggregate the "
                      "client recorded in its cost-state line. The cost-state line is a live snapshot: "
                      "it is exact where written after the last message and drifts on long or resumed "
                      "sessions, so only the chosen exact session is used for the acceptance check.",
        }
    # dsh: counted calls vs the worker's own tool_calls counter, on jobs that report it.
    counted = sum(len(s["calls"]) for s in raw["dsh"]["sessions"].values()
                  if s.get("tool_calls_reported"))
    reported = sum(int(s.get("tool_calls_reported") or 0) for s in raw["dsh"]["sessions"].values())
    jobs_reporting = sum(1 for s in raw["dsh"]["sessions"].values() if s.get("tool_calls_reported"))
    if reported:
        out["dsh"] = {"counted": counted, "worker_reported": reported,
                      "jobs_reporting": jobs_reporting,
                      "diff_pct": round(100.0 * abs(counted - reported) / max(1, reported), 2),
                      "total_counted_all_jobs": sum(len(s["calls"]) for s in raw["dsh"]["sessions"].values()),
                      "note": "only jobs that wrote progress.jsonl carry a worker counter; "
                              "older jobs have no independent count"}
    # OpenCode: session_v2 aggregate vs the sum of its assistant messages.
    oc = raw["opencode"]["sessions"]
    if oc:
        agg_out = sum(s.get("out") or 0 for s in oc.values())
        msg_out = sum(sum((s.get("step_out") or {}).values()) for s in oc.values())
        out["opencode"] = {"session_aggregate_out": agg_out, "message_sum_out": msg_out,
                           "diff_pct": round(100.0 * abs(agg_out - msg_out) / max(1, agg_out), 2)}
    return out


# --- sampling for the accuracy check -------------------------------------------

SAMPLE_CLASSES = [SH_READ, SH_SEARCH, SH_LIST, PY_DB, PY_OTHER, TESTS, BENCH, GIT, SLEEP]


def samples(raw_sources: dict, per_class: int = 30, seed: int = 20261030) -> str:
    pool = collections.defaultdict(list)
    for src, raw in raw_sources.items():
        for sid, s in raw["sessions"].items():
            for c in s["calls"]:
                if c["route"] != "shell":
                    continue
                pool[c["cls"]].append((src, sid, c))
    rng = random.Random(seed)
    lines = ["# Classifier samples (30 random shell rows per class)", "",
             "Adjudicate each row: `ok` if the class is right, `bad` if not. "
             "Commands are redacted 400-char prefixes.", ""]
    for cls in SAMPLE_CLASSES:
        rows = pool.get(cls, [])
        take = rng.sample(rows, min(per_class, len(rows)))
        lines.append(f"## {cls}  (population {len(rows)}, sampled {len(take)})")
        lines.append("")
        lines.append("| # | source | session | command prefix | why (trigger) | verdict |")
        lines.append("|---|--------|---------|----------------|---------------|---------|")
        for i, (src, sid, c) in enumerate(take, 1):
            _, trig = classify_shell_explain(c.get("cmd") or "")
            lines.append(f"| {i} | {src} | {prefix(sid, 24)} | `{prefix(c.get('cmd') or '', 300)}` | "
                         f"`{prefix(trig, 120)}` | ? |")
        lines.append("")
    return "\n".join(lines)


# --- report ---------------------------------------------------------------------

def build(roots: dict, since: float | None, workspace: str) -> dict:
    raw = {
        "dsh": read_dsh(roots["dsh"], since),
        "claude": read_claude(roots["claude"], since),
        "opencode": read_opencode(roots["opencode"], since, workspace),
        "codex": read_codex(roots["codex"], since),
    }
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "since": datetime.fromtimestamp(since, timezone.utc).isoformat(timespec="seconds") if since else None,
        "change_ts": CHANGE_TS,
        "chars_per_token": CHARS_PER_TOKEN,
        "classes": CLASSES,
        "sources": {k: summarise(k, v) for k, v in raw.items()},
        "waste": detectors(raw),
        "before_after": before_after(raw["dsh"]),
        "integrity": integrity(raw),
        "counts": {
            "dsh_jobs": len(raw["dsh"]["sessions"]),
            "claude_files": raw["claude"].get("files", 0),
            "opencode_sessions": len(raw["opencode"]["sessions"]),
            "codex_present": raw["codex"].get("present", False),
        },
    }
    report["_raw"] = raw
    return report


def _fmt(n) -> str:
    if isinstance(n, float):
        return f"{n:,.1f}"
    return f"{n:,}"


def render_md(rep: dict) -> str:
    L = []
    add = L.append
    add("# Tool usage and token spend — every agent source")
    add("")
    add(f"Generated {rep['generated_at']} · since {rep['since'] or 'all time'} · "
        f"estimated tokens = output chars / {rep['chars_per_token']}")
    add("")
    add("Read-only measurement. No message text, document contents or keys; command prefixes "
        "are truncated at 400 chars and redacted. Sources under `Manual Dumps` are excluded.")
    add("")
    add("## Headline per source")
    add("")
    add("| source | sessions | steps | tool calls | failures | output chars | est tokens | "
        "provider out | cache read | cache create | uncached in | thinking | cost USD | context-carry |")
    add("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for src, s in rep["sources"].items():
        if not s["present"]:
            add(f"| {src} | ABSENT | - | - | - | - | - | - | - | - | - | - | - | - |")
            continue
        add(f"| {src} | {_fmt(s['sessions_n'])} | {_fmt(s['steps'])} | {_fmt(s['calls_n'])} | "
            f"{_fmt(s['failures'])} | {_fmt(s['chars'])} | {_fmt(sum(b['est_tokens'] for b in s['classes'].values()))} | "
            f"{_fmt(s['provider_out'])} | {_fmt(s['cache_read'])} | {_fmt(s['cache_creation'])} | "
            f"{_fmt(s['provider_in'])} | {_fmt(s['thinking'])} | {s['cost']:.4f} | {_fmt(s['carry'])} |")
    add("")
    codes = rep["counts"]
    add(f"dsh jobs with an event log: {codes['dsh_jobs']} · Claude transcript files: "
        f"{codes['claude_files']} · OpenCode sessions: {codes['opencode_sessions']} · "
        f"Codex: {'present' if codes['codex_present'] else 'ABSENT'}.")
    add("")
    add("Context-carry = Σ over steps of (that step's output tokens) × (later steps in the session). "
        "Each step's output is re-sent on every later request, so this is the re-sent volume the "
        "outputs create, not a separate bill. Attributed to a class by sharing a step's output "
        "evenly across the calls in that step.")
    add("")

    add("## Per source, per tool class")
    add("")
    for src, s in rep["sources"].items():
        if not s["present"]:
            continue
        add(f"### {src}")
        add("")
        add("| class | calls | failures | output chars | est tokens | context-carry | share of est tokens |")
        add("|---|---|---|---|---|---|---|")
        for cls in CLASSES:
            b = s["classes"].get(cls)
            if not b:
                continue
            add(f"| {cls} | {_fmt(b['calls'])} | {_fmt(b['failures'])} | {_fmt(b['chars'])} | "
                f"{_fmt(b['est_tokens'])} | {_fmt(b['carry'])} | {s['share'].get(cls, 0)}% |")
        add("")

    add("## Waste detectors")
    add("")
    w = rep["waste"]
    labels = {
        "a": "a. whole-file `.py` read, file never edited (>=200 lines)",
        "b": "b. shell reads/searches/listings the read/grep/LSP tools could serve",
        "c": "c. inline DB queries the `sql` tool could serve",
        "d": "d. schema probes for stores already documented in `tasks/worker_context/schemas/`",
        "e": "e. identical commands repeated in one session",
        "f": "f. failed calls",
        "g": "g. read-only calls in separate steps that could have been one batch",
        "h": "h. calls/seconds before the first edit",
        "i": "i. tool outputs over 10,000 chars",
        "j": "j. sleep/poll",
    }
    for key in "abcdefghij":
        d = w[key]
        val = _fmt(d.get("count", "")) if "count" in d else f"{d.get('n', '')} sessions"
        add(f"### {labels[key]}")
        add("")
        add(f"- count: **{val}** · est tokens: **{_fmt(d.get('tokens', 0))}**")
        add(f"- formula: {d['formula']}")
        for extra in ("by_class", "edited_whole_reads", "edited_ratio_median", "runs",
                      "read_only_calls", "seconds", "n", "calls_p50", "calls_p90",
                      "calls_mean", "calls_max", "seconds_p50", "seconds_p90",
                      "tables_hit", "scripts_run_3plus", "signatures", "top_sources", "rows"):
            if extra in d and d[extra] not in (None, [], {}, 0, 0.0):
                add(f"- {extra}: `{json.dumps(d[extra])[:900]}`")
        add("")

    add("## Before vs after the 30 Oct 04:15 IST code-intel change")
    add("")
    ba = rep["before_after"]
    add("| window | jobs | calls | LSP calls | LSP/job | LSP share | sql+schema | grep tool | read tool | shell | shell share |")
    add("|---|---|---|---|---|---|---|---|---|---|---|")
    for k in ("before", "after"):
        b = ba[k]
        add(f"| {k} | {b['jobs']} | {b['calls']} | {b['lsp_calls']} | {b['lsp_per_job']} | "
            f"{b['lsp_share_pct']}% | {b['sql_calls']} | {b['grep_tool_calls']} | "
            f"{b['read_calls']} | {b['shell_calls']} | {b['shell_share_pct']}% |")
    add("")
    add(f"Post-change jobs: {', '.join(ba['after']['ids']) or 'none'}. n is small — treat the after column "
        "as a data point, not a trend. Detail (all four are within hours of the change; three started "
        "within minutes of this run and are still young):")
    add("")
    add("| job | started (UTC) | calls | LSP | shell |")
    add("|---|---|---|---|---|")
    for r in ba["after"].get("jobs_detail", []):
        add(f"| {r['id']} | {r['started'] or ''} | {r['calls']} | {r['lsp']} | {r['shell']} |")
    add("")

    add("## Cross-checks (measured vs a second count)")
    add("")
    for src, v in rep.get("integrity", {}).items():
        if src == "claude":
            add(f"- **claude**: deduped transcript sum vs the client's own cost-state aggregate — "
                f"{v['sessions_within_2pct']}/{v['sessions_with_provider_aggregate']} sessions within "
                f"2%, worst {v['max_abs_diff_pct']}%. Chosen session `{v['chosen_session']}` "
                f"({v['chosen_steps']} steps): deduped sum {_fmt(v['chosen_deduped_sum'])} vs provider "
                f"{_fmt(v['chosen_provider_aggregate'])} ({v['chosen_diff_pct']}% apart). {v['method']}")
        elif src == "dsh":
            add(f"- **dsh**: counted calls {_fmt(v['counted'])} vs the worker's own counter "
                f"{_fmt(v['worker_reported'])} ({v['diff_pct']}% apart, {v['jobs_reporting']} jobs "
                f"reporting; {_fmt(v.get('total_counted_all_jobs', 0))} calls counted over all jobs). "
                f"{v['note']}.")
        elif src == "opencode":
            add(f"- **opencode**: session aggregate output {_fmt(v['session_aggregate_out'])} vs the sum "
                f"of its assistant messages {_fmt(v['message_sum_out'])} ({v['diff_pct']}% apart).")
    add("")

    add("## Code-intel vs grep / read / shell")
    add("")
    add("| source | LSP nav | LSP diag | grep tool | read tool | shell (all) | sql tool |")
    add("|---|---|---|---|---|---|---|")
    for src, s in rep["sources"].items():
        if not s["present"]:
            continue
        cl = s["classes"]
        def n(k):
            return cl.get(k, {}).get("calls", 0)
        add(f"| {src} | {n(LSP_NAV)} | {n(LSP_DIAG)} | {n(SH_SEARCH) - cl.get(SH_SEARCH, {}).get('route_shell', 0)} | "
            f"{n(PY_WHOLE) + n(PY_RANGED) + n(READ_OTHER)} | "
            f"{sum(b.get('route_shell', 0) for b in cl.values())} | {n(SQL_TOOL)} |")
    add("")
    add("`grep tool` and `read tool` are the dedicated tools only; the shell column is every "
        "shell-routed call. `sql tool` is `mcp__reality-data__sql`.")
    add("")

    add("## Top 10 most expensive sessions per source")
    add("")
    for src, s in rep["sources"].items():
        if not s["present"] or not s["top_sessions"]:
            continue
        add(f"### {src}")
        add("")
        add("| session | steps | calls | provider out | cache read | context-carry | cost USD | model |")
        add("|---|---|---|---|---|---|---|---|")
        for r in s["top_sessions"]:
            label = r["name"] or r["id"]
            if label != r["id"]:
                label = f"{label} · {prefix(r['id'], 10)}"
            add(f"| {prefix(label, 60)} | {_fmt(r['steps'])} | "
                f"{_fmt(r['calls'])} | {_fmt(r['provider_out'])} | {_fmt(r['cache_read'])} | "
                f"{_fmt(r['carry'])} | {r['cost']:.4f} | {prefix(r['model'], 28)} |")
        add("")

    add("## Share of each source's tokens by class")
    add("")
    for src, s in rep["sources"].items():
        if not s["present"]:
            continue
        top = sorted(s["share"].items(), key=lambda kv: -kv[1])[:6]
        if not top:
            add(f"- {src}: no tool calls, so no class share (tokens and cost only)")
            continue
        add(f"- {src}: " + " · ".join(f"{c} {v}%" for c, v in top if v))
    add("")

    add("## Thinking output vs visible output")
    add("")
    add("| source | thinking tokens | visible output | thinking share | thinking (est from event text) |")
    add("|---|---|---|---|---|")
    for src, s in rep["sources"].items():
        if not s["present"]:
            continue
        if s.get("thinking_in_output", True):
            visible = max(0, s["provider_out"] - s["thinking"])
            share = (100.0 * s["thinking"] / s["provider_out"]) if s["provider_out"] else 0
        else:
            visible = s["provider_out"]
            share = (100.0 * s["thinking"] / (s["provider_out"] + s["thinking"])) \
                if (s["provider_out"] + s["thinking"]) else 0
        add(f"| {src} | {_fmt(s['thinking'])} | {_fmt(visible)} | {share:.1f}% | "
            f"{_fmt(s.get('thinking_est') or 0) if src == 'dsh' else '-'} |")
    add("")
    add("Claude reports thinking inside `output_tokens` (as `output_tokens_details`); OpenCode "
        "reports `tokens_reasoning` beside `tokens_output`, so its share is over the sum. dsh "
        "records no provider thinking split; its provider total is all output, and the last "
        "column is the thinking *text* length / 4.")
    add("")

    add("## Classification accuracy")
    add("")
    add("30 random shell rows per class are printed to the samples file. Verdicts are entered by hand; "
        "the measured precision is below. Classes not listed were not sampled (too few rows).")
    add("")
    if rep.get("precision"):
        add("| class | sampled | correct | precision |")
        add("|---|---|---|---|")
        for cls, v in rep["precision"].items():
            add(f"| {cls} | {v['sampled']} | {v['correct']} | {v['precision']:.1f}% |")
    else:
        add("_Not adjudicated in this run (`--precision` not given)._")
    add("")

    add("## What could not be measured, and why")
    add("")
    add("- **dsh output sizes are lower bounds for truncated results** (the event writer caps them); "
        f"truncated results: {rep['sources']['dsh']['truncated'] if rep['sources']['dsh']['present'] else 0}.")
    add("- **dsh input tokens are not recorded** anywhere in the job directory (events carry no usage); "
        "only provider output tokens and model steps are available from `progress.jsonl`.")
    add("- **OpenCode holds no tool calls at all** in the live DB: only text/reasoning parts. It is "
        "reported for model, tokens and cost, with zero tool calls — not omitted.")
    add("- **Codex is absent** on this machine (`~/.codex/sessions` does not exist).")
    add("- **pytest is not installed** for the interpreter that runs this report, so the fixture "
        "test was executed with `python -m unittest reality_engine.tests.test_tool_usage_report`; "
        "the file is a plain `TestCase` and pytest will collect it unchanged.")
    add("- **Direct Go API readers are out of scope.** `reality_engine/scripts/{extract_news_prices,"
        "extract_deck_figures,concall_pilot,ar_queue}.py` post straight to `opencode.ai/zen/go/v1/"
        "chat/completions` with no tool calls. `reality_engine/toolbelt/cost_ledger.py` already writes "
        "`tasks/ledgers/spend.jsonl`, but no reader calls `charge()` and that ledger does not exist, so "
        "their tokens are uncountable from local state. To count them: call `charge()` (or "
        "`cost_ledger --add`) after every response, then sum the ledger by purpose; fall back to the "
        "provider's billing export.")
    add("")
    return "\n".join(L)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Read-only tool-usage and token accounting.")
    ap.add_argument("--since", help="only sessions starting on/after this date (YYYY-MM-DD or ISO)")
    ap.add_argument("--out", default=os.path.join("tasks", "efficiency", "TOOL_USAGE"),
                    help="output base path; writes <out>.md and <out>.json")
    ap.add_argument("--samples", help="write the 30-row classifier samples to this .md path")
    ap.add_argument("--precision", help="JSON {class: {sampled, correct}} adjudication of the samples")
    ap.add_argument("--limit-samples", type=int, default=30)
    args = ap.parse_args(argv)

    since = None
    if args.since:
        s = args.since
        if len(s) == 10:
            s += "T00:00:00+00:00"
        since = _ts(s)

    workspace = os.getcwd()
    rep = build(DEFAULT_ROOTS, since, workspace)
    if args.precision and os.path.exists(args.precision):
        with open(args.precision, encoding="utf-8") as fh:
            prec = json.load(fh)
        rep["precision"] = {k: {"sampled": v["sampled"], "correct": v["correct"],
                                "precision": 100.0 * v["correct"] / max(1, v["sampled"])}
                            for k, v in prec.items()}
    if args.samples:
        os.makedirs(os.path.dirname(os.path.abspath(args.samples)) or ".", exist_ok=True)
        with open(args.samples, "w", encoding="utf-8") as fh:
            fh.write(samples(rep.pop("_raw"), args.limit_samples))

    rep.pop("_raw", None)
    out = args.out
    os.makedirs(os.path.dirname(os.path.abspath(out)) or ".", exist_ok=True)
    keep = {k: v for k, v in rep.items()}
    with open(out + ".json", "w", encoding="utf-8") as fh:
        json.dump(keep, fh, indent=1, sort_keys=True)
    with open(out + ".md", "w", encoding="utf-8") as fh:
        fh.write(render_md(keep))
    print(f"wrote {out}.md and {out}.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
