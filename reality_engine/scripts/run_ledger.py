"""Run ledger (Shivam, 11 Nov 2026): one place that records every run of every model, so that when progress stalls
we can see where it went wrong instead of guessing.

What is recorded, per run: who ran (model, host, ticket), when and for how long, every tool call by tool, how many
went through the reality-data MCP tools, how many were raw SQL or other workarounds (direct sqlite/duckdb from a
shell, raw PDF reads), errors, and the outcome.  Answer runs add one row per question (tools used, SQL used, seconds,
grade, why a workaround was needed, the gap it exposed).  Reader runs add one row per page (seconds, tokens, rows,
verified cells, unread numbers).  Gaps and disclosures (a test set seen by a fix, a number fitted to its own
questions) are rows too, with the fix and the ticket.

    python -m reality_engine.scripts.run_ledger ingest-dsh                 # every dsh/Beam worker job
    python -m reality_engine.scripts.run_ledger ingest-claude <session.jsonl> [--run-id <id>]
    python -m reality_engine.scripts.run_ledger ingest-answers <dir> --run-id <id> --set <name> [--model <m>]
    python -m reality_engine.scripts.run_ledger ingest-reader <run dir> [--run-id <id>]
    python -m reality_engine.scripts.run_ledger ingest-reviews             # tasks/efficiency/worker_reviews.jsonl
    python -m reality_engine.scripts.run_ledger note --kind disclosure|gap|decision --text "..." [--refs ...]
    python -m reality_engine.scripts.run_ledger gap --cls <class> --what "..." --fix "..." [--ticket T-nnn] [--run-id ..]
    python -m reality_engine.scripts.run_ledger report [--out <xlsx>]

Ledger: ``D:/RealityEngine/ledger/ledger.db`` (``RUN_LEDGER_DB`` overrides).  Every ingest is idempotent.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
LEDGER = Path(os.environ.get("RUN_LEDGER_DB", "D:/RealityEngine/ledger/ledger.db"))
JOBS = ROOT / "plugins" / "dsh-worker" / "runtime" / "jobs"
REVIEWS = ROOT / "tasks" / "efficiency" / "worker_reviews.jsonl"

SCHEMA = """
CREATE TABLE IF NOT EXISTS run (
  run_id TEXT PRIMARY KEY, kind TEXT, ticket TEXT, title TEXT, model TEXT, host TEXT,
  started_at TEXT, ended_at TEXT, seconds REAL, outcome TEXT,
  tool_calls INTEGER, tool_calls_by_tool TEXT, model_steps INTEGER, tool_errors INTEGER,
  mcp_calls INTEGER, sql_calls INTEGER, workaround_calls INTEGER, file_writes INTEGER,
  in_tok INTEGER, out_tok INTEGER, items INTEGER, source TEXT, review TEXT, ingested_at TEXT);
CREATE TABLE IF NOT EXISTS tool_call (
  run_id TEXT, seq INTEGER, tool TEXT, category TEXT, status TEXT, arg TEXT, PRIMARY KEY (run_id, seq));
CREATE TABLE IF NOT EXISTS answer (
  run_id TEXT, qid TEXT, set_name TEXT, company TEXT, status TEXT, tools TEXT, n_calls INTEGER,
  used_sql INTEGER, seconds REAL, answer TEXT, grade TEXT, grader TEXT, workaround_reason TEXT,
  gap_class TEXT, gap_note TEXT, PRIMARY KEY (run_id, qid));
CREATE TABLE IF NOT EXISTS reader_page (
  run_id TEXT, page_id TEXT, reader TEXT, input TEXT, seconds REAL, in_tok INTEGER, out_tok INTEGER,
  rows INTEGER, error TEXT, PRIMARY KEY (run_id, page_id));
CREATE TABLE IF NOT EXISTS gap (
  gap_id INTEGER PRIMARY KEY AUTOINCREMENT, opened_at TEXT, run_id TEXT, scope TEXT, cls TEXT, what TEXT,
  evidence TEXT, fix TEXT, ticket TEXT, status TEXT DEFAULT 'open');
CREATE TABLE IF NOT EXISTS note (
  note_id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT, author TEXT, kind TEXT, text TEXT, refs TEXT);
"""

# Tool categories.  "mcp" = a reality-data tool (the intended path); "sql" = SQL typed by the model (pilot3_sql or
# sql()); "workaround" = the data reached some other way (sqlite/duckdb from a shell, a raw PDF read, a hand script).
_SQL_TOOLS = re.compile(r"(^|_)(sql|pilot3_sql)$")
_SHELL = {"bash", "pwsh", "powershell", "shell", "Bash", "PowerShell"}
_WORKAROUND = re.compile(r"sqlite3|duckdb|connect_ro\(|\.db['\"]?\s|pymupdf|fitz\.open|pdftotext", re.I)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(LEDGER, timeout=60)
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(SCHEMA)
    return con


def categorise(tool: str, arg: str = "") -> str:
    t = tool.split("__")[-1]
    if _SQL_TOOLS.search(t):
        return "sql"
    if tool.startswith("mcp__reality-data") or t.startswith("pilot3_") or "reality-data" in tool:
        return "mcp"
    if tool in _SHELL or t in _SHELL:
        if "p3ask" in arg:
            return "sql" if re.search(r"p3ask\b.*?\s(?:pilot3_)?sql(?=\s|$|['\"])", arg) else "mcp"
        return "workaround" if _WORKAROUND.search(arg) else "shell"
    if t in ("read", "Read", "glob", "Glob", "grep", "Grep", "list"):
        return "read"
    if t in ("write", "Write", "edit", "Edit", "patch", "apply_patch", "NotebookEdit"):
        return "write"
    return "other"


def _store_run(con: sqlite3.Connection, row: dict[str, Any], calls: list[tuple[str, str, str]]) -> None:
    cats = Counter(categorise(t, a) for t, _s, a in calls)
    by_tool = Counter(t for t, _s, _a in calls)
    row.update({"tool_calls": len(calls), "tool_calls_by_tool": json.dumps(dict(by_tool.most_common())),
                "mcp_calls": cats["mcp"], "sql_calls": cats["sql"], "workaround_calls": cats["workaround"],
                "file_writes": cats["write"], "tool_errors": sum(1 for _t, s, _a in calls if s not in ("", "completed", "ok", "success")),
                "ingested_at": _now()})
    cols = [r[1] for r in con.execute("PRAGMA table_info(run)")]
    old = con.execute("SELECT review FROM run WHERE run_id=?", (row["run_id"],)).fetchone()
    if old and old[0] and not row.get("review"):
        row["review"] = old[0]
    con.execute(f"INSERT OR REPLACE INTO run ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                [row.get(c) for c in cols])
    con.execute("DELETE FROM tool_call WHERE run_id=?", (row["run_id"],))
    con.executemany("INSERT INTO tool_call VALUES (?,?,?,?,?,?)",
                    [(row["run_id"], n, t, categorise(t, a), s, a[:300]) for n, (t, s, a) in enumerate(calls)])


def _seconds(a: str | None, b: str | None) -> float | None:
    try:
        return (datetime.fromisoformat(str(b)) - datetime.fromisoformat(str(a))).total_seconds()
    except (TypeError, ValueError):
        return None


def ingest_dsh(con: sqlite3.Connection) -> int:
    """Every worker job folder: status.json (outcome, times) and result.md.events.jsonl (tool calls)."""
    n = 0
    for status_path in sorted(JOBS.glob("*/status.json")):
        job = status_path.parent
        try:
            st = json.loads(status_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        calls: list[tuple[str, str, str]] = []
        pending: dict[str, int] = {}
        steps = 0
        events = job / "result.md.events.jsonl"
        if events.exists():
            for line in events.read_text(encoding="utf-8", errors="replace").splitlines():
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                if e.get("type") == "tool_call":
                    pending[str(e.get("callId"))] = len(calls)
                    calls.append((str(e.get("tool") or "?"), "", str(e.get("input") or "")))
                elif e.get("type") == "tool_result" and str(e.get("callId")) in pending:
                    i = pending[str(e.get("callId"))]
                    calls[i] = (calls[i][0], str(e.get("status") or ""), calls[i][2])
                elif e.get("type") == "thinking":
                    steps += 1
        brief = (job / "brief.md").read_text(encoding="utf-8", errors="replace") if (job / "brief.md").exists() else ""
        ticket = re.search(r"\bT-\d{3}\b", brief)
        model = st.get("model") or (re.search(r"model[\"']?\s*[:=]\s*[\"']?([\w./:-]+)", brief) or [None, None])[1]
        prog = st.get("progress") or {}
        goal = (re.search(r"^Goal:.*$", brief, re.M) or re.search(r".*", brief))
        kind = "grader" if re.search(r"grad(e|er|ing)|review", goal.group(0) if goal else "", re.I) else "worker"
        _store_run(con, {
            "run_id": st.get("job_id") or job.name, "kind": f"dsh_{kind}", "ticket": ticket.group(0) if ticket else None,
            "title": (st.get("title") or brief[:160]).replace("\n", " ")[:300], "model": model, "host": st.get("host"),
            "started_at": st.get("started_at"), "ended_at": st.get("finished_at"),
            "seconds": st.get("elapsed_seconds") or _seconds(st.get("started_at"), st.get("finished_at")),
            "outcome": st.get("outcome") or st.get("phase"),
            "model_steps": steps or (prog.get("events") or {}).get("model_steps"),
            "source": str(job)}, calls)
        n += 1
    con.commit()
    return n


def ingest_claude(con: sqlite3.Connection, transcript: Path, run_id: str | None = None) -> int:
    """A Claude Code session transcript (.jsonl): every tool_use, its result status, tokens."""
    calls: list[tuple[str, str, str]] = []
    idx: dict[str, int] = {}
    tin = tout = 0
    first = last = None
    model = None
    for line in transcript.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        ts = e.get("timestamp")
        first = first or ts
        last = ts or last
        msg = e.get("message") or {}
        if isinstance(msg, dict):
            model = msg.get("model") or model
            u = msg.get("usage") or {}
            tin += int(u.get("input_tokens") or 0) + int(u.get("cache_read_input_tokens") or 0)
            tout += int(u.get("output_tokens") or 0)
            for part in msg.get("content") or []:
                if not isinstance(part, dict):
                    continue
                if part.get("type") == "tool_use":
                    idx[str(part.get("id"))] = len(calls)
                    calls.append((str(part.get("name")), "", json.dumps(part.get("input"))[:600]))
                elif part.get("type") == "tool_result" and str(part.get("tool_use_id")) in idx:
                    i = idx[str(part.get("tool_use_id"))]
                    calls[i] = (calls[i][0], "error" if part.get("is_error") else "completed", calls[i][2])
    _store_run(con, {"run_id": run_id or f"claude-{transcript.stem}", "kind": "claude_session", "title": transcript.name,
                     "model": model, "host": "msi", "started_at": first, "ended_at": last,
                     "seconds": _seconds(first, last), "outcome": "session", "in_tok": tin, "out_tok": tout,
                     "source": str(transcript)}, calls)
    con.commit()
    return len(calls)


def ingest_answers(con: sqlite3.Connection, folder: Path, run_id: str, set_name: str, model: str | None,
                   grades: Path | None = None) -> int:
    """Answer-run folder of <company>_answers.jsonl (start/answer events, p3ask's format) plus optional grades csv
    (qid, grade, grader, gap_class, gap_note, workaround_reason)."""
    graded: dict[str, dict[str, str]] = {}
    if grades and grades.exists():
        with grades.open(encoding="utf-8", newline="") as fh:
            graded = {r["qid"]: r for r in csv.DictReader(fh)}
    n = 0
    starts: dict[str, str] = {}
    calls_all: list[tuple[str, str, str]] = []
    for f in sorted(folder.glob("*.jsonl")):
        for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                e = json.loads(line)
            except ValueError:
                continue
            qid = str(e.get("qid") or "")
            if e.get("event") == "start":
                starts[qid] = e.get("at")
            elif e.get("event") == "call":
                calls_all.append((str(e.get("tool") or "?"), "completed", qid))
            elif e.get("event") == "answer":
                tools = e.get("tools")
                tools = tools if isinstance(tools, list) else re.findall(r"'([^']+)'", str(tools or ""))
                g = graded.get(qid, {})
                con.execute("INSERT OR REPLACE INTO answer VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                    run_id, qid, set_name, qid.split("-")[0], e.get("status"), json.dumps(tools), len(tools),
                    int(any(t in ("sql", "pilot3_sql") for t in tools)), _seconds(starts.get(qid), e.get("at")),
                    str(e.get("answer") or "")[:2000], g.get("grade"), g.get("grader"),
                    e.get("workaround_reason") or g.get("workaround_reason"),
                    e.get("gap_class") or g.get("gap_class"), e.get("gap_note") or g.get("gap_note")))
                n += 1
    secs = [r[0] for r in con.execute("SELECT seconds FROM answer WHERE run_id=? AND seconds IS NOT NULL", (run_id,))]
    _store_run(con, {"run_id": run_id, "kind": "answer_run", "title": f"{set_name} answers", "model": model,
                     "items": n, "seconds": sum(secs) if secs else None, "outcome": "answered", "source": str(folder)},
               calls_all)
    con.commit()
    return n


def ingest_reader(con: sqlite3.Connection, folder: Path, run_id: str | None = None) -> int:
    """A transcription run folder (transcribe_log.csv: page_id, reader, input, seconds, in_tok, out_tok, error, n_rows)."""
    log = folder / "transcribe_log.csv"
    if not log.exists():
        return 0
    rid = run_id or f"reader-{folder.name}"
    rows = list(csv.DictReader(log.open(encoding="utf-8", newline="")))
    for r in rows:
        con.execute("INSERT OR REPLACE INTO reader_page VALUES (?,?,?,?,?,?,?,?,?)", (
            rid, r["page_id"], r.get("reader"), r.get("input"), float(r.get("seconds") or 0), int(r.get("in_tok") or 0),
            int(r.get("out_tok") or 0), int(r.get("n_rows") or 0), r.get("error") or ""))
    _store_run(con, {"run_id": rid, "kind": "reader_run", "title": folder.name, "model": rows[0].get("reader") if rows else None,
                     "items": len(rows), "seconds": sum(float(r.get("seconds") or 0) for r in rows),
                     "in_tok": sum(int(r.get("in_tok") or 0) for r in rows), "out_tok": sum(int(r.get("out_tok") or 0) for r in rows),
                     "outcome": f"{sum(1 for r in rows if r.get('error'))} errors", "source": str(folder)}, [])
    con.commit()
    return len(rows)


def ingest_reviews(con: sqlite3.Connection) -> int:
    n = 0
    for line in REVIEWS.read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(line)
        except ValueError:
            continue
        cur = con.execute("UPDATE run SET review=? WHERE run_id=?", (json.dumps(r, ensure_ascii=False), r.get("id")))
        n += cur.rowcount
    con.commit()
    return n


def report(con: sqlite3.Connection, out: Path) -> None:
    from openpyxl import Workbook

    wb = Workbook()
    assert wb.active is not None
    sheets = {
        "runs": "SELECT run_id, kind, ticket, model, host, started_at, seconds, outcome, tool_calls, mcp_calls, sql_calls, "
                "workaround_calls, tool_errors, file_writes, model_steps, items, in_tok, out_tok, title FROM run "
                "ORDER BY started_at DESC",
        "by_kind_model": "SELECT kind, model, COUNT(*) runs, SUM(tool_calls) calls, SUM(mcp_calls) mcp, SUM(sql_calls) sql, "
                         "SUM(workaround_calls) workaround, SUM(tool_errors) errors, ROUND(AVG(seconds)) avg_s "
                         "FROM run GROUP BY 1, 2 ORDER BY runs DESC",
        "answers": "SELECT run_id, set_name, COUNT(*) n, SUM(grade='right') right_, SUM(used_sql) used_sql, "
                   "ROUND(AVG(n_calls),1) calls, ROUND(AVG(seconds)) avg_s, SUM(workaround_reason IS NOT NULL AND "
                   "workaround_reason<>'') workarounds FROM answer GROUP BY 1, 2",
        "workaround_reasons": "SELECT workaround_reason, COUNT(*) n FROM answer WHERE workaround_reason<>'' GROUP BY 1 ORDER BY n DESC",
        "gaps": "SELECT gap_id, opened_at, cls, what, evidence, fix, ticket, status, run_id FROM gap ORDER BY gap_id",
        "gaps_by_class": "SELECT cls, status, COUNT(*) n FROM gap GROUP BY 1, 2 ORDER BY n DESC",
        "reader_pages": "SELECT run_id, reader, input, COUNT(*) pages, ROUND(AVG(seconds),1) s_page, SUM(out_tok) out_tok, "
                        "SUM(rows) rows_, SUM(error<>'') errors FROM reader_page GROUP BY 1, 2, 3",
        "notes": "SELECT note_id, at, author, kind, text, refs FROM note ORDER BY note_id",
    }
    first = True
    for name, sql in sheets.items():
        ws: Any = wb.active if first else wb.create_sheet()
        first = False
        ws.title = name
        cur = con.execute(sql)
        ws.append([d[0] for d in cur.description])
        for row in cur:
            ws.append(list(row))
    out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="run ledger: every run, every tool call, every gap")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("ingest-dsh")
    p = sub.add_parser("ingest-hook", help="what the Stop hook runs: every worker job, then the transcript if given")
    p.add_argument("transcript", nargs="?", type=Path)
    p = sub.add_parser("ingest-claude")
    p.add_argument("transcript", type=Path)
    p.add_argument("--run-id")
    p = sub.add_parser("ingest-answers")
    p.add_argument("folder", type=Path)
    p.add_argument("--run-id", required=True)
    p.add_argument("--set", required=True)
    p.add_argument("--model")
    p.add_argument("--grades", type=Path)
    p = sub.add_parser("ingest-reader")
    p.add_argument("folder", type=Path)
    p.add_argument("--run-id")
    sub.add_parser("ingest-reviews")
    p = sub.add_parser("note")
    p.add_argument("--kind", required=True)
    p.add_argument("--text", required=True)
    p.add_argument("--refs", default="")
    p.add_argument("--author", default="Eagle")
    p = sub.add_parser("gap")
    p.add_argument("--cls", required=True)
    p.add_argument("--what", required=True)
    p.add_argument("--evidence", default="")
    p.add_argument("--fix", default="")
    p.add_argument("--ticket", default="")
    p.add_argument("--run-id", default="")
    p.add_argument("--scope", default="")
    p = sub.add_parser("report")
    p.add_argument("--out", type=Path, default=Path(f"D:/RealityEngine/reports/{datetime.now():%Y-%m-%d}_run_ledger.xlsx"))
    a = ap.parse_args(argv)
    con = connect()
    if a.cmd == "ingest-hook":
        print(f"dsh jobs: {ingest_dsh(con)}")
        if a.transcript:
            print(f"tool calls: {ingest_claude(con, a.transcript)}")
    elif a.cmd == "ingest-dsh":
        print(f"dsh jobs: {ingest_dsh(con)}")
    elif a.cmd == "ingest-claude":
        print(f"tool calls: {ingest_claude(con, a.transcript, a.run_id)}")
    elif a.cmd == "ingest-answers":
        print(f"answers: {ingest_answers(con, a.folder, a.run_id, a.set, a.model, a.grades)}")
    elif a.cmd == "ingest-reader":
        print(f"pages: {ingest_reader(con, a.folder, a.run_id)}")
    elif a.cmd == "ingest-reviews":
        print(f"runs with a review: {ingest_reviews(con)}")
    elif a.cmd == "note":
        con.execute("INSERT INTO note (at, author, kind, text, refs) VALUES (?,?,?,?,?)", (_now(), a.author, a.kind, a.text, a.refs))
        con.commit()
    elif a.cmd == "gap":
        con.execute("INSERT INTO gap (opened_at, run_id, scope, cls, what, evidence, fix, ticket) VALUES (?,?,?,?,?,?,?,?)",
                    (_now(), a.run_id, a.scope, a.cls, a.what, a.evidence, a.fix, a.ticket))
        con.commit()
    elif a.cmd == "report":
        report(con, a.out)
        print(a.out)
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
