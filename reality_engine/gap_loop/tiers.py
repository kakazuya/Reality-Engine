"""The three tiers of the T-048 gap loop: Haiku session, DeepSeek dsh worker, escalation file.

Tier 1 is one ``claude -p`` session (the shared runner from ``doc_review_loop``).  Tier 2 is the
same dsh-worker start function the MCP ``start_worker`` tool calls, imported from
``plugins/dsh-worker/server/core.py`` with that folder on ``sys.path`` -- no MCP round trip.
Tier 3 is a JSON line in the sandbox's ``escalations.jsonl``; the loop moves on.
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from reality_engine.gap_loop import store
from reality_engine.scripts.session_runner import (
    MAX_TURNS, MODEL, build_cmd, child_env, parse_json_block, run_session,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKER_SERVER = REPO_ROOT / "plugins" / "dsh-worker" / "server"
MCP_NAME = "reality-data"
ALLOWED_TOOLS = ("Read", "Grep", "Glob", "Write", "Edit", "Bash", "mcp__reality-data")
DISALLOWED_TOOLS = ("WebFetch", "WebSearch", "Agent", "Skill", "NotebookEdit")
TIER1_MAX_ATTEMPTS = 3
DEEPSEEK_TIMEOUT = 3600
DEEPSEEK_POLL = 30
APPROVED_BY = "Shivam, 2 Nov: full permissions inside the T-048 sandbox"


def _iso(moment: datetime | None = None) -> str:
    return (moment or datetime.now(timezone.utc)).isoformat()


def mcp_config(sandbox: Path) -> str:
    """A strict MCP config holding only the reality-data server from the repo's ``.mcp.json``."""
    source = json.loads((REPO_ROOT / ".mcp.json").read_text(encoding="utf-8"))
    server = (source.get("mcpServers") or {}).get(MCP_NAME)
    if not server:
        raise RuntimeError(".mcp.json has no reality-data server")
    entry = json.loads(json.dumps(server))
    env = entry.setdefault("env", {})
    env.pop("REALITY_DATA_ALLOW_PAID_EMBED", None)  # never a paid embedding path
    config = {"mcpServers": {MCP_NAME: entry}}
    return str(store.write_text_inside(sandbox, "state/mcp.json", json.dumps(config, indent=2)))


def answer_prompt(unit) -> str:
    questions = json.dumps([{"qid": q["id"], "question": q["question"], "as_of": q.get("as_of")}
                            for q in unit.items], ensure_ascii=False, indent=1)
    return f"""You answer questions about KEC Ltd from stored data and held documents. Task T-048.

Sandbox: {unit.sandbox} (the only place you may write). Questions, with their as-of date:
{questions}

Read-only evidence:
- the `reality-data` MCP tools (`mcp__reality-data__*`) for KEC's stored facts, documents and prices;
- `{unit.sandbox}\\kec.db`: tables doc_text(doc_key,page,text,method,known_at), facts(measure,value,unit,period,basis,doc_key,page,quote,known_at), formulas(name,expression,inputs,description);
- `{unit.sandbox}\\raw\\` and `text\\`: KEC's own PDFs and their extracted text. File names under raw\\history are BSE attachment ids; map one to its date and title through `bse_announcements` / `corporate_documents`.

Rules:
- Nothing published after a question's as-of date may be used. A question with no date is as of 2026-10-19.
- Read pages yourself only where you must. Scripted work (PDF text with fitz, OCR only on a page with no text layer) belongs in a Python script you write under `{unit.sandbox}\\state\\` and run with Bash.
- Never edit `questions\\`, never write outside the sandbox, never fetch the network, never use paid embeddings, never read D:\\Shivam_Private or any key file.
- A gap is one of: text_missing (the document is not readable as text), not_extracted (text is there, the number is in no store), needs_formula (computable from stored numbers), wrong_store (the data is held but the tools did not reach it), absent (not in any KEC document held).

Output: end with one fenced json block and nothing after it, one row per question:
```json
[{{"qid": "KEC001", "status": "answered|partial|not_found", "answer": "one plain sentence",
  "numbers": [{{"measure": "revenue", "value": 1234.5, "unit": "inr_cr", "period": "FY26",
               "basis": "consolidated", "doc_key": "doc_key used in doc_text", "page": 12,
               "known_at": "YYYY-MM-DD, from the filing record",
               "quote": "the exact sentence on that page carrying the number"}}],
  "sources": [{{"doc_key": "...", "page": 12, "note": ""}}],
  "gap_type": null, "gap_detail": ""}}]
```
A number has one of two sources.
- A page in `kec.db` `doc_text`: give its `doc_key` and `page`, its `known_at` (the filing date) and `quote`, the exact sentence on that page that carries the value.
- A `reality-data` tool: give `tool` and `args` (the exact arguments you called it with) instead of `doc_key`/`page`, e.g. {{"measure": "promoter holding", "value": 50.1, "unit": "pct", "period": "Q2FY26", "tool": "holding", "args": {{"symbol": "KEC", "as_of": "2026-10-19"}}, "known_at": "2026-10-16"}}. The loop re-runs that call in Python and keeps the number only if the value appears in the record it returns; `quote` is optional for a tool source, and when you give one it must appear in the record too. The record's own date must not be after the as-of date, so pass the as-of date in `args` where the tool takes one (`facts`, `holding` and `docs` do).
Every number needs its unit, its period and a source. A margin is a percentage; an order book is money. If you cannot answer, set status not_found and the gap_type; do not invent a number or a quote.
"""


def unit_task(unit) -> str:
    """What the unit must do, in the form a DeepSeek brief or a fix prompt can carry."""
    if unit.stage == "fix":
        return (f"{unit.instruction}\nQuestions in this unit: {', '.join(unit.items)}. Read their latest "
                "answers rows in kec.db to see what failed.")
    questions = json.dumps([{"qid": q["id"], "question": q["question"], "as_of": q.get("as_of")}
                            for q in unit.items], ensure_ascii=False)
    return (f"Answer these questions: {questions}\n"
            "The final json is a list of answer rows, one per qid, with status, answer, numbers, "
            "sources, gap_type. Every number is sourced either by doc_key and page (with known_at and "
            "quote, the exact sentence on that page) or by tool and args, a reality-data call the loop "
            "re-runs, whose record must carry the value (and the quote when you give one) and be dated "
            "on or before the as-of date.")


def fix_prompt(unit) -> str:
    return f"""You close one group of data gaps for KEC Ltd. Task T-048, fix unit {unit.id}.

Sandbox: {unit.sandbox} (the only place you may write).
Gap type: {unit.gap}
Instruction: {unit.instruction}
Questions in this unit: {', '.join(unit.items)}. Read their latest `answers` rows in kec.db to see what failed.

Evidence and stores:
- read-only `reality-data` MCP tools, `{unit.sandbox}\\kec.db` and `{unit.sandbox}\\raw\\` / `text\\`;
- write extracted page text into `kec.db` `doc_text(doc_key, page, text, method, known_at)` yourself, keyed so an answer can cite it;
- do NOT insert into `facts`, `formulas` or `answers`. For every number or formula you would store, append one JSON object per line to `{unit.sandbox}\\state\\proposals\\{unit.id}.jsonl`:
  {{"measure": "...", "value": 1234.5, "unit": "inr_cr", "period": "FY26", "basis": "consolidated", "doc_key": "...", "page": 12, "quote": "exact quote on that page", "known_at": "YYYY-MM-DD"}}
  A formula proposal is {{"name": "...", "expression": "...", "inputs": ["fact measure"], "description": "..."}} and goes to `{unit.sandbox}\\state\\proposals\\{unit.id}.formulas.json`.
- The loop, not you, checks and stores those rows.

Scripted work is Python you write under `{unit.sandbox}\\state\\` and run with Bash (fitz for text; OCR only where a page has no text layer). Do not read a whole PDF into your own context when code can extract it. Never edit `questions\\`, never write outside the sandbox, no network fetches, no paid embeddings, never read D:\\Shivam_Private or any key file.

Output: end with one fenced json block and nothing after it:
```json
{{"outcome": "fixed|no_change|failed", "summary": "one line", "pages": 0, "notes": ""}}
```
"""


def deepseek_brief(unit, result_path: Path) -> str:
    return f"""Goal: Close one KEC data-gap unit (T-048, {unit.stage} {unit.id}, gap {unit.gap or 'answer'}) in the sandbox {unit.sandbox}, writing only there.
Files: read {unit.sandbox}\\kec.db, {unit.sandbox}\\raw\\, {unit.sandbox}\\text\\; write {unit.sandbox}\\kec.db doc_text and {result_path}.
Accept: {result_path} exists and parses as the JSON object this brief's task block describes; no write outside {unit.sandbox}.
Stop if: the unit needs the network, a paid embedding, a key file, or a write outside {unit.sandbox}.
Budget: one unit, one hour, cheap-model work.
Ticket: T-048

{unit_task(unit)}

Do not start other workers. Do not insert into facts, formulas or answers yourself; put proposals under {unit.sandbox}\\state\\proposals\\.
Write your final JSON to {result_path} (and end with the same fenced json block):
```json
{{"outcome": "fixed|no_change|failed", "summary": "one line", "pages": 0}}
```
"""


def run_tier1(unit, logfile: Path | None) -> dict:
    """One fresh Haiku session for this unit; the caller applies the payload and counts attempts."""
    prompt = fix_prompt(unit) if unit.stage == "fix" else answer_prompt(unit)
    started = _iso()
    cmd = build_cmd(prompt, model=MODEL, allowed_tools=ALLOWED_TOOLS, disallowed_tools=DISALLOWED_TOOLS,
                    mcp_config=mcp_config(unit.sandbox), max_turns=MAX_TURNS)
    env = child_env({"KEC_GAP_LOOP": "1"})
    env.pop("REALITY_DATA_ALLOW_PAID_EMBED", None)
    session = run_session(cmd, unit.sandbox, env=env, model=MODEL)
    payload = parse_json_block(session.final)
    error = session.error
    if payload is None and not error:
        error = "no valid JSON block" if not session.over_limit else "over context limit"
    return {
        "tier": 1, "model": MODEL, "started": started, "ended": _iso(),
        "ok": payload is not None and not session.over_limit and not error,
        "payload": payload, "error": error, "over_limit": session.over_limit,
        "limited": session.limited, "session": session, "job_id": None,
    }


def worker_core():
    """The dsh-worker ``core`` module, imported directly; no MCP server in the path."""
    if str(WORKER_SERVER) not in sys.path:
        sys.path.insert(0, str(WORKER_SERVER))
    import core  # noqa: PLC0415 -- the folder is not a package and is only needed for tier 2

    return core


def wait_offpeak(sleep=time.sleep, core=None) -> None:
    core = core or worker_core()
    while core.is_peak():
        sleep(300)


def run_tier2(unit, logfile: Path | None, *, manager_factory=None, sleep=time.sleep,
              timeout=DEEPSEEK_TIMEOUT) -> dict:
    """One DeepSeek unit through ``Manager.start_worker``; peak refusal queues, it never bypasses."""
    core = worker_core()
    started = _iso()
    if core.is_peak():
        return {"tier": 2, "model": "deepseek", "ok": False, "queued": True, "payload": None,
                "error": "peak hours: queued", "started": started, "ended": _iso(), "session": None}
    result_path = store.inside(unit.sandbox, "state", "units", f"{unit.id}.json")
    result_path.parent.mkdir(parents=True, exist_ok=True)
    if result_path.exists():
        result_path.unlink()
    manager = (manager_factory or (lambda: core.Manager(core.load_config())))()
    try:
        start = manager.start_worker(
            brief=deepseek_brief(unit, result_path),
            workspace=".",
            permission="danger-full-access",
            write_scope="data", confirm_data_write=True, writes=["kec_gap_loop.db"],
            approved_by=APPROVED_BY,
            context_pack=False, use_worktree=False, hard_timeout_seconds=timeout,
        )
    except core.PluginError as exc:
        code = getattr(exc, "code", "") or ""
        if code.startswith("peak_hours"):
            return {"tier": 2, "model": "deepseek", "ok": False, "queued": True, "payload": None,
                    "error": f"peak hours: {code}", "started": started, "ended": _iso(), "session": None}
        return {"tier": 2, "model": "deepseek", "ok": False, "payload": None,
                "error": f"start refused: {code or exc}", "started": started, "ended": _iso(), "session": None}
    job_id = str(start.get("job_id") or "")
    deadline = time.time() + timeout
    status: dict = {}
    while job_id and time.time() < deadline:
        status = manager.get_status(job_id)
        if status.get("done"):
            break
        sleep(DEEPSEEK_POLL)
    payload = None
    error = ""
    if result_path.exists():
        try:
            payload = json.loads(result_path.read_text(encoding="utf-8"))
        except ValueError as exc:
            error = f"unit result is not JSON: {exc}"
    else:
        error = "unit result file missing"
    progress = status.get("progress") or {}
    tool_calls = (progress.get("events") or {}).get("tool_calls")
    return {
        "tier": 2, "model": "deepseek", "ok": payload is not None and not error, "payload": payload,
        "error": error, "started": started, "ended": _iso(), "session": None, "job_id": job_id,
        "tokens": None, "tokens_note": "dsh job record has no token counts",
        "tool_calls": {"total": tool_calls} if isinstance(tool_calls, int) else None,
    }
