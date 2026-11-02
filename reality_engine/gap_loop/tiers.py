"""The three tiers of the T-048 gap loop: Haiku session, DeepSeek dsh worker, escalation file.

Tier 1 is one ``claude -p`` session (the shared runner from ``doc_review_loop``) that reads the
sandbox's prepared ``kec.db`` only: a strict MCP config with no servers is passed, so none of the
``reality-data`` tools is reachable and no raw reply can blow the context.  Tier 2 is the same
dsh-worker start function the MCP ``start_worker`` tool calls, imported from
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
ALLOWED_TOOLS = ("Read", "Grep", "Glob", "Write", "Edit", "Bash")
DISALLOWED_TOOLS = ("WebFetch", "WebSearch", "Agent", "Skill", "NotebookEdit")
TIER1_MAX_ATTEMPTS = 3
DEEPSEEK_TIMEOUT = 3600
DEEPSEEK_POLL = 30
APPROVED_BY = "Shivam, 2 Nov: full permissions inside the T-048 sandbox"


def _iso(moment: datetime | None = None) -> str:
    return (moment or datetime.now(timezone.utc)).isoformat()


def mcp_config(sandbox: Path) -> str:
    """A strict MCP config with no servers at all: the prepared store is the only evidence."""
    config = {"mcpServers": {}}
    return str(store.write_text_inside(sandbox, "state/mcp.json", json.dumps(config, indent=2)))



def answer_prompt(unit) -> str:
    questions = json.dumps([{"qid": q["id"], "question": q["question"], "as_of": q.get("as_of")}
                            for q in unit.items], ensure_ascii=False, indent=1)
    return f"""You answer questions about KEC Ltd from prepared data. Task T-048.

Sandbox: {unit.sandbox} (the only place you may write). Questions, with their as-of date:
{questions}

All the evidence is in `{unit.sandbox}\\kec.db`, which the prepare stage filled from KEC's documents
and the stores. Query it with small SQL through Bash/Python; never read a whole PDF into your
context and never `SELECT *` a big table without LIMIT.
- `doc_text(doc_key, page, text, method, known_at)`: every page of every held PDF. `docs(doc_key,
  doc_type, title, filing_date, known_at, pages)` says what each file is. A page with `method`
  `needs_ocr` has no text.
- Search the text with the FTS5 index, then fetch the page:
  `SELECT d.doc_key, d.page FROM doc_text_fts JOIN doc_text d ON d.rowid = doc_text_fts.rowid
   WHERE doc_text_fts MATCH 'order book' LIMIT 20` (MATCH names the index table, never an alias)
- Copied stores, every row carrying `known_at`: `ar_facts` (annual-report facts: category, item,
  value, unit, period, basis, quote, page, doc_id, filed_at), `deck_figures` (sha256, page_no,
  metric, period, value, unit), `results_filings` and `results_quarterly` (NSE XBRL, period_end,
  RevenueFromOperations, ProfitLossForPeriod, ...), `concall_items`, `px_nse` and `px_bse` (date,
  open, high, low, close, volume, deliverable_qty, delivery_pct), `shp_index` (quarter_end,
  promoter_pct, public_pct), `announcements` (BSE: NEWSID, HEADLINE, SUBCATNAME, DissemDT).
- `sources(table_name, source_db, source_table, key, rows)` says where each copy came from;
  `facts`, `formulas` and `answers` are the loop's own store.

Rules:
- Nothing known after a question's as-of date may be used: filter on `known_at` or the row's date.
- Scripted work belongs in a Python file under `{unit.sandbox}\\state\\` and runs with Bash.
- Never edit `questions\\`, never write outside the sandbox, no network, never read
  D:\\Shivam_Private or any key file.
- A gap is one of: text_missing (the document is not readable as text), not_extracted (text is
  there, the number is in no store), needs_formula (computable from stored numbers), wrong_store
  (the data is held but not reached), absent (not in any KEC document held).

Output: end with one fenced json block and nothing after it, one row per question:
```json
[{{"qid": "KEC001", "status": "answered|partial|not_found", "answer": "one plain sentence",
  "numbers": [{{"measure": "revenue", "value": 1234.5, "unit": "inr_cr", "period": "FY26",
               "basis": "consolidated", "doc_key": "history/quarterly_results/x.pdf", "page": 12,
               "known_at": "2026-05-15", "quote": "the exact sentence on that page carrying the number"}}],
  "sources": [{{"doc_key": "...", "page": 12, "note": ""}}],
  "gap_type": null, "gap_detail": ""}}]
```
A number has one of two sources.
- A page in `doc_text`: give its `doc_key`, `page`, its `known_at` (the filing date from `docs`) and
  `quote`, the exact sentence on that page that carries the value.
- A row of `kec.db`: give `table` and `rowid`, the row you read the value from, e.g.
  {{"measure": "promoter holding", "value": 51.7, "unit": "pct", "period": "Q2FY26",
    "table": "shp_index", "rowid": 42, "known_at": "2026-07-15"}}. The loop reads that row and keeps
  the number only if the value is in it, and the quote too when you give one; `known_at` must be the
  row's own date.
Every number needs its unit, its period and a source. A margin is a percentage; an order book is
money. If you cannot answer, set status not_found and the gap_type; never invent a number, a quote
or a rowid.
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
            "quote, the exact sentence on that page) or by table and rowid, a kec.db row whose value "
            "must carry the number (and the quote when you give one) and whose known_at is on or "
            "before the as-of date.")


def fix_prompt(unit) -> str:
    return f"""You close one group of data gaps for KEC Ltd. Task T-048, fix unit {unit.id}.

Sandbox: {unit.sandbox} (the only place you may write).
Gap type: {unit.gap}
Instruction: {unit.instruction}
Questions in this unit: {', '.join(unit.items)}. Read their latest `answers` rows in kec.db to see what failed.

Evidence and stores:
- `{unit.sandbox}\\kec.db` and `{unit.sandbox}\\raw\\`: kec.db is already prepared (doc_text, docs and
  the copied stores listed in `sources`); raw\\ holds the PDFs themselves;
- write extracted page text into `kec.db` `doc_text(doc_key, page, text, method, known_at)` yourself,
  keyed so an answer can cite it; the FTS index follows it automatically;
- do NOT insert into `facts`, `formulas` or `answers`. For every number or formula you would store, append one JSON object per line to `{unit.sandbox}\\state\\proposals\\{unit.id}.jsonl`:
  {{"measure": "...", "value": 1234.5, "unit": "inr_cr", "period": "FY26", "basis": "consolidated", "doc_key": "...", "page": 12, "quote": "exact quote on that page", "known_at": "YYYY-MM-DD"}}
  A formula proposal is {{"name": "...", "expression": "...", "inputs": ["fact measure"], "description": "..."}} and goes to `{unit.sandbox}\\state\\proposals\\{unit.id}.formulas.json`.
- The loop, not you, checks and stores those rows.

Scripted work is Python you write under `{unit.sandbox}\\state\\` and run with Bash (fitz for text; OCR only where a page has no text layer). Do not read a whole PDF into your own context when code can extract it. Never edit `questions\\`, never write outside the sandbox, no network fetches, never read D:\\Shivam_Private or any key file.

Output: end with one fenced json block and nothing after it:
```json
{{"outcome": "fixed|no_change|failed", "summary": "one line", "pages": 0, "notes": ""}}
```
"""


def deepseek_brief(unit, result_path: Path) -> str:
    return f"""Goal: Close one KEC data-gap unit (T-048, {unit.stage} {unit.id}, gap {unit.gap or 'answer'}) in the sandbox {unit.sandbox}, writing only there.
Files: read {unit.sandbox}\\kec.db and {unit.sandbox}\\raw\\; write {unit.sandbox}\\kec.db doc_text and {result_path}.
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
            confirm_repo_root_write=True,
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
