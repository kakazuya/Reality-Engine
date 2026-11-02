"""T-048 one-company gap loop: 100 questions, gaps, fix units, re-answer, ledger, reports.

    python -m reality_engine.gap_loop --sandbox D:\\RealityEngine\\sandbox\\kec_loop --dry-run
    python -m reality_engine.gap_loop --sandbox D:\\RealityEngine\\sandbox\\kec_loop --prepare-only
    python -m reality_engine.gap_loop --sandbox D:\\RealityEngine\\sandbox\\kec_loop
    python -m reality_engine.gap_loop --sandbox D:\\RealityEngine\\sandbox\\kec_loop --ledger-summary \\
        --opus-transcript <managing session .jsonl> --since <ISO time>

The loop, not the model, decides what is stored: a malformed report is a failed attempt, a number
that fails its check leaves its row ``unverified``, two failed Haiku attempts go to Sonnet, and a
Sonnet failure writes one escalation line per question to ``escalations.jsonl``.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import threading
import time
from collections import Counter, deque
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path

from reality_engine.gap_loop import checks, ledger, prepare, store, tiers
from reality_engine.scripts.session_runner import LIMIT_SLEEP, MODEL

REPO_ROOT = Path(__file__).resolve().parents[2]
QUESTIONS = "questions/KEC_QUESTIONS.jsonl"
AS_OF = "2026-10-19"
BATCH = 5
FIX_UNIT_MAX = 10
MAX_ATTEMPTS = 2  # Haiku attempts before tier 2 (Shivam, 2 Nov: twice in a row, then Sonnet)
MAX_ROUNDS = 5
BUDGET_USD = 15.0
FIXED_REGRESSION = 10
LOG = "logs/loop.log"
APPROVED_BY = "Shivam, 2 Nov: full permissions inside the T-048 sandbox"

FIX_INSTRUCTIONS = {
    "unverified": (
        "The answer's number failed a check. If the cited page is not in kec.db doc_text, put that "
        "page's text there with its filing date, keyed so an answer can cite it. If the number comes "
        "from a prepared store, say in your summary which kec.db table and rowid hold it, and quote "
        "the value exactly as that row has it: the loop re-reads the row when the answer cites it."
    ),
    "text_missing": (
        "Extract the text of the KEC documents the failed answers cite but cannot read, page by "
        "page, into kec.db doc_text; use fitz in a Python script and OCR only a page with no text "
        "layer. known_at comes from the filing record (kec.db docs, bse_announcements/"
        "corporate_documents), never the crawl date."
    ),
    "not_extracted": (
        "Extract the numbers the failed answers need from the held documents (results tables first, "
        "then decks, transcripts and annual reports) into state/proposals/ as facts rows with an exact "
        "quote, page, unit, period and known_at. The loop checks and stores them."
    ),
    "needs_formula": (
        "Define each missing measure as a formula over numbers already stored in kec.db facts or in a "
        "prepared store table, write it to state/proposals/<unit>.formulas.json, and say which "
        "inputs it uses. Do not invent an input that is not stored."
    ),
    "wrong_store": (
        "The data is held but the query did not reach it: find the kec.db table that has it (see "
        "`sources` for what each copy is, `docs` for the documents) and record the retrieval path in "
        "state/proposals/ as facts rows the loop can check."
    ),
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Unit:
    id: str
    stage: str  # answer | fix | reanswer
    sandbox: Path
    items: list = field(default_factory=list)
    instruction: str = ""
    gap: str = ""

    @property
    def size(self) -> int:
        return len(self.items)

    def halved(self) -> tuple["Unit", "Unit | None"]:
        half = max(1, len(self.items) // 2)
        first = replace(self, id=f"{self.id}a", items=self.items[:half])
        rest = self.items[half:]
        return first, (replace(self, id=f"{self.id}b", items=rest) if rest else None)


def log(path: Path | None, text: str) -> None:
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S} {text}"
    print(line, flush=True)
    if path is not None:
        with Path(path).open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")


def ensure_sandbox(path: Path) -> Path:
    """An existing directory outside the repository, holding the question bank."""
    root = Path(path).expanduser().resolve()
    if not root.is_dir():
        raise SystemExit(f"STOPPED sandbox is not a directory: {root}")
    repo = os.path.normcase(str(REPO_ROOT.resolve()) + os.sep)
    if os.path.normcase(str(root) + os.sep).startswith(repo):
        raise SystemExit(f"STOPPED sandbox must be outside the repository: {root}")
    question_file = store.inside(root, QUESTIONS)
    if not question_file.is_file():
        raise SystemExit(f"STOPPED question bank missing: {question_file}")
    return root


def load_questions(sandbox: Path) -> list[dict]:
    """Read-only: the bank is never edited or reworded."""
    file = store.inside(sandbox, QUESTIONS)
    questions = []
    for line in file.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            row.setdefault("as_of", AS_OF)
            questions.append(row)
    return questions


def answer_units(questions: list[dict], sandbox: Path, stage: str = "answer") -> list[Unit]:
    units = []
    for index in range(0, len(questions), BATCH):
        chunk = questions[index:index + BATCH]
        units.append(Unit(id=f"{stage}-{index // BATCH + 1:02d}", stage=stage, sandbox=sandbox, items=chunk))
    return units


def gap_groups(statuses: dict[str, dict]) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {}
    for qid, row in statuses.items():
        if row.get("status") == "answered":
            continue
        gap = row.get("gap_type") or "not_extracted"
        groups.setdefault(gap, []).append(qid)
    return groups


def fix_units(statuses: dict[str, dict], sandbox: Path) -> list[Unit]:
    """At most ``FIX_UNIT_MAX`` questions per unit: a gap group of 25 is three units, not one."""
    units = []
    for gap, qids in sorted(gap_groups(statuses).items()):
        if gap == "absent":
            continue  # not in any document held: recorded, not fixed
        instruction = FIX_INSTRUCTIONS.get(gap, FIX_INSTRUCTIONS["not_extracted"])
        ordered = sorted(qids)
        for index in range(0, len(ordered), FIX_UNIT_MAX):
            units.append(Unit(id=f"fix-{gap}-{index // FIX_UNIT_MAX + 1:02d}", stage="fix",
                              sandbox=sandbox, items=ordered[index:index + FIX_UNIT_MAX],
                              instruction=instruction, gap=gap))
    return units


def reanswer_units(questions: list[dict], statuses: dict[str, dict], sandbox: Path,
                   exclude: set[str] | None = None) -> list[Unit]:
    exclude = exclude or set()
    pending = [q for q in questions if q["id"] not in exclude
               and (statuses.get(q["id"], {}) or {}).get("status") != "answered"]
    answered = [q for q in questions if q["id"] not in exclude
                and (statuses.get(q["id"], {}) or {}).get("status") == "answered"]
    chosen = {q["id"] for q in pending + answered[:FIXED_REGRESSION]}
    return answer_units([q for q in questions if q["id"] in chosen], sandbox, stage="reanswer")


def accept_answers(unit: Unit, payload, lookup, as_of: str, row_lookup=None, tier: int = 1):
    """Accept one answer report.  A malformed report fails the unit; a failed number only its row.

    The rows are rewritten here: a row whose number fails a check keeps the model's answer text but
    is stored as ``unverified`` with the check's reason and gap type ``unverified``, so it is not
    counted as answered and the next round re-answers or fixes it.
    """
    if not isinstance(payload, list):
        reason = "payload is not a JSON list"
        return False, reason, {"invalid": {q["id"]: f"{q['id']}: {reason}" for q in unit.items}}
    rows = {row.get("qid"): row for row in payload if isinstance(row, dict)}
    invalid: dict[str, str] = {}
    unverified: dict[str, str] = {}
    answered = 0
    for question in unit.items:
        qid = question["id"]
        row = rows.get(qid)
        if row is None:
            invalid[qid] = f"{qid}: no row in the report"
            continue
        malformed, reasons = checks.check_answer_row(row, lookup, question.get("as_of") or as_of,
                                                     row_lookup)
        if malformed:
            invalid[qid] = f"{qid}: {malformed}"
            continue
        if reasons:
            row["status"] = "unverified"
            row["gap_type"] = "unverified"
            row["reason"] = "; ".join(reasons)
            unverified[qid] = f"{qid}: {'; '.join(reasons)}"
        if row.get("status") == "answered":
            answered += 1
    if invalid:
        return False, "; ".join(invalid.values()), {"invalid": invalid, "unverified": unverified}
    return True, None, {"answers": answered, "unverified": unverified, "invalid": invalid}


def accept_fix(unit: Unit, payload, sandbox: Path, conn, as_of: str, tier: int = 1):
    if not isinstance(payload, dict):
        return False, "payload is not a JSON object", {}
    outcome = str(payload.get("outcome") or "")
    if outcome not in ("fixed", "no_change"):
        return False, f"fix outcome {outcome!r} is not fixed/no_change", {}
    lookup = store.page_lookup(conn)
    facts: list[dict] = []
    proposals = store.inside(sandbox, "state", "proposals", f"{unit.id}.jsonl")
    if proposals.exists():
        for number, line in enumerate(proposals.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except ValueError:
                return False, f"proposal line {number} is not JSON", {}
            page = lookup(row.get("doc_key"), row.get("page"))
            if page is None:
                return False, f"proposal line {number}: source: page not in doc_text", {}
            ok, reason = checks.check_fact(row, page[0], page[1], as_of)
            if not ok:
                return False, f"proposal line {number}: {reason}", {}
            facts.append(row)
    formulas: list[dict] = []
    formula_file = store.inside(sandbox, "state", "proposals", f"{unit.id}.formulas.json")
    if formula_file.exists():
        try:
            raw = json.loads(formula_file.read_text(encoding="utf-8"))
        except ValueError as exc:
            return False, f"formulas file is not JSON: {exc}", {}
        for row in raw if isinstance(raw, list) else [raw]:
            if not isinstance(row, dict) or not row.get("name") or not row.get("expression"):
                return False, "a formula needs a name and an expression", {}
            formulas.append(row)
    for row in facts:
        store.add_fact(conn, {**row, "tier": tier})
    for row in formulas:
        store.add_formula(conn, row)
    conn.commit()
    return True, None, {"facts": len(facts), "formulas": len(formulas),
                        "answers": 0}


def _tokens(session) -> dict[str, int] | None:
    if session is None:
        return None
    usage = session.usage or {}
    return {
        "input": int(usage.get("input_tokens") or 0),
        "cache_read": int(usage.get("cache_read_input_tokens") or 0),
        "cache_creation": int(usage.get("cache_creation_input_tokens") or 0),
        "output": int(usage.get("output_tokens") or 0),
        "thinking": int(usage.get("thinking_tokens") or 0),
    }


def method_tags(unit: Unit, result: dict, rows_added: dict) -> list[str]:
    """Tags the loop can prove from the stream and the store, never from the model's own words."""
    session = result.get("session")
    commands = " ".join(session.bash_commands if session else []).lower()
    tags: list[str] = []
    if re.search(r"\bsqlite3?\b|\bselect\b", commands):
        tags.append("sql")
    if rows_added.get("doc_text"):
        tags.append("script_text")
    if re.search(r"\bocr\b|pytesseract|rapidocr", commands):
        tags.append("ocr")
    if session is not None and session.reads:
        tags.append("model_read")
    if rows_added.get("formulas") or (unit.stage == "fix" and unit.gap == "needs_formula"):
        tags.append("formula")
    if rows_added.get("labels") or (unit.stage == "fix" and "label" in unit.instruction.lower()):
        tags.append("labelling")
    return list(dict.fromkeys(tags))


def attempt_row(unit: Unit, result: dict, attempt: int, rows_added: dict) -> dict:
    session = result.get("session")
    tokens = result.get("tokens") if result.get("tokens") is not None else _tokens(session)
    files_written = []
    for relative in (f"state/proposals/{unit.id}.jsonl", f"state/proposals/{unit.id}.formulas.json"):
        try:
            if store.inside(unit.sandbox, relative).is_file():
                files_written.append(relative)
        except store.SandboxViolation:
            continue
    row = {
        "ts_start": result.get("started"), "ts_end": result.get("ended"),
        "stage": unit.stage, "unit": unit.id, "size": unit.size, "attempt": attempt,
        "tier": result.get("tier"), "model": result.get("model"),
        "outcome": "ok" if result.get("ok") else ("queued" if result.get("queued") else "failed"),
        "error": (result.get("error") or "")[:300],
        "tokens": tokens,
        "cost_usd": round(float(getattr(session, "cost", 0.0) if session else 0.0), 6),
        "tool_calls": dict(session.tool_calls) if session else (result.get("tool_calls") or {}),
        "bash": [str(cmd)[:200] for cmd in (session.bash_commands if session else [])],
        "methods": method_tags(unit, result, rows_added),
        "pages_model": session.pages_read if session else None,
        "pages_model_reads": session.reads if session else None,
        "pages_model_unknown": session.pages_unknown if session else None,
        "pages_code": int(rows_added.get("doc_text") or 0),
        "rows_added": rows_added,
        "files_written": files_written,
        "job_id": result.get("job_id"),
    }
    if session is not None and getattr(session, "cost_estimated", False):
        row["cost_estimated"] = True
    if result.get("tokens_note"):
        row["tokens_note"] = result["tokens_note"]
    if result.get("over_limit"):
        row["over_limit"] = True
    return row


def _remember(reasons: dict[str, str], added: dict) -> None:
    """Keep the last check reason per question, from one ``accept`` result."""
    for group in ("invalid", "unverified"):
        for qid, reason in (added.get(group) or {}).items():
            reasons[str(qid)] = str(reason)


def run_unit(unit: Unit, accept, sandbox: Path, conn, logfile: Path | None, *, round_no: int,
             tier1=None, tier2=None, sleep=time.sleep) -> dict:
    """Up to two Haiku attempts (halving after an over-limit kill), then Sonnet, then escalation."""
    tier1 = tier1 or tiers.run_tier1
    tier2 = tier2 or tiers.run_tier2_sonnet
    attempts: list[dict] = []
    leftovers: list[Unit] = []
    reasons: dict[str, str] = {}
    current = unit
    number = 0
    while number < MAX_ATTEMPTS:
        before = store.counts(conn)
        result = tier1(current, logfile)
        number += 1
        if result.get("limited") and not result.get("ok") and not result.get("over_limit"):
            log(logfile, f"usage limit: sleeping {LIMIT_SLEEP // 60} min")
            sleep(LIMIT_SLEEP)
            number -= 1
            attempts.append(attempt_row(current, result, number + 1, {}))
            continue
        applied = {"ok": False, "error": result.get("error"), "added": {}}
        if result.get("payload") is not None and not result.get("over_limit"):
            ok, reason, added = accept(result["payload"], 1, u=current)
            applied = {"ok": ok, "error": reason, "added": added}
            _remember(reasons, added)
            result["ok"], result["error"] = ok, reason
        else:
            result["ok"] = False
        after = store.counts(conn)
        added = dict(applied["added"])
        for table in after:
            if table == "answers":  # other threads write answers in parallel; accept() counts its own
                continue
            delta = after[table] - before[table]
            if delta:
                added[table] = added.get(table, 0) + delta
        attempts.append(attempt_row(current, result, number, added))
        if result.get("ok"):
            return {"ok": True, "tier": 1, "payload": result.get("payload"), "attempts": attempts,
                    "leftovers": leftovers, "rows": added, "unit": current}
        if result.get("over_limit") and len(current.items) > 1:
            current, rest = current.halved()
            if rest:
                leftovers.append(rest)
    result = tier2(current, logfile)
    if result.get("queued"):
        tiers.wait_offpeak(sleep=sleep)
        result = tier2(current, logfile)
    before = store.counts(conn)
    applied = {"ok": False, "error": result.get("error"), "added": {}}
    if result.get("payload") is not None:
        ok, reason, added = accept(result["payload"], 2, u=current)
        applied = {"ok": ok, "error": reason, "added": added}
        _remember(reasons, added)
        result["ok"], result["error"] = ok, reason
    else:
        result["ok"] = False
    after = store.counts(conn)
    added = dict(applied["added"])
    for table in after:
        if table == "answers":
            continue
        delta = after[table] - before[table]
        if delta:
            added[table] = added.get(table, 0) + delta
    attempts.append(attempt_row(current, result, 1, added))
    if result.get("ok"):
        return {"ok": True, "tier": 2, "payload": result.get("payload"), "attempts": attempts,
                "leftovers": leftovers, "rows": added, "unit": current}
    last_error = result.get("error") or "the unit produced no valid report"
    escalated = [str(q["id"] if isinstance(q, dict) else q) for q in current.items]
    for qid in escalated:  # one line per question, so the escalation names the question and its reason
        ledger.escalate(sandbox, {
            "at": _now_iso(), "stage": unit.stage, "unit": current.id, "gap": unit.gap,
            "question": qid, "reason": reasons.get(qid) or last_error,
            "instruction": unit.instruction, "tried": attempts,
            "detail": f"{MAX_ATTEMPTS} Haiku attempts and one tier-2 attempt failed; Opus should review",
        })
    row = attempt_row(current, {**result, "tier": 3, "model": "opus-pending", "ok": False}, 1, {})
    row["outcome"] = "escalated"
    attempts.append(row)
    return {"ok": False, "tier": 3, "payload": None, "attempts": attempts, "leftovers": leftovers,
            "rows": {}, "unit": current, "escalated": True, "escalated_qids": escalated}


# Sessions at once (Shivam, 2 Nov: run in parallel).  Answer units only read kec.db, so 4 run together;
# fix units write doc_text, and run one at a time so each ledger row's added rows are its own.
PARALLEL = {"answer": 4, "reanswer": 4, "fix": 1}


def _thread_conn(sandbox: Path, conn):
    """A connection for a worker thread (sqlite connections are per thread); tests pass ``conn`` through."""
    if getattr(conn, "_gap_loop_shared", False):
        return conn
    local = store.connect(sandbox)
    local.execute("PRAGMA busy_timeout = 30000")
    return local


def drain(queue: deque, round_no: int, sandbox: Path, conn, logfile: Path | None, state: dict,
          *, tier1=None, tier2=None, sleep=time.sleep, workers: int | None = None) -> list[dict]:
    rows: list[dict] = []
    if not queue:
        return rows
    stage = queue[0].stage
    count = workers or PARALLEL.get(stage, 1)
    try:
        conn.commit()  # an open write on this connection would lock the worker threads out
        conn.execute("PRAGMA journal_mode = WAL")  # readers and one writer at a time, no lock errors
    except Exception:  # noqa: BLE001
        pass
    lock = threading.Lock()

    def work() -> None:
        local = conn if count == 1 else _thread_conn(sandbox, conn)
        lookup = store.page_lookup(local)
        row_lookup = store.row_lookup(local)
        while True:
            with lock:
                if not queue:
                    return
                if state["spent"] >= state["budget"]:
                    if not state.get("budget_logged"):
                        state["budget_logged"] = True
                        log(logfile, f"STOPPED budget ${state['spent']:.2f} reached")
                    return
                unit = queue.popleft()
            if unit.stage == "fix":
                accept = lambda payload, tier=1, u=unit: accept_fix(
                    u, payload, sandbox, local, state["as_of"], tier)
            else:
                accept = lambda payload, tier=1, u=unit: accept_answers(
                    u, payload, lookup, state["as_of"], row_lookup, tier)
            outcome = run_unit(unit, accept, sandbox, local, logfile, round_no=round_no,
                               tier1=tier1, tier2=tier2, sleep=sleep)
            with lock:
                for row in outcome["attempts"]:
                    rows.append(row)
                    ledger.append(sandbox, row)
                    state["spent"] += float(row.get("cost_usd") or 0.0)
                for leftover in outcome["leftovers"]:
                    queue.appendleft(leftover)
                if outcome.get("escalated") and unit.stage != "fix":
                    state.setdefault("escalated", set()).update(outcome.get("escalated_qids") or [])
                if outcome["ok"] and unit.stage in ("answer", "reanswer"):
                    for answer in outcome["payload"]:
                        store.put_answer(local, round_no, {**answer, "tier": outcome["tier"]})
                    local.commit()
                log(logfile, f"unit {unit.id} stage={unit.stage} size={unit.size} "
                             f"tier={outcome['tier']} ok={outcome['ok']}")

    if count == 1:
        work()
        return rows
    threads = [threading.Thread(target=work, name=f"gap-loop-{n}", daemon=True) for n in range(count)]
    for thread in threads:
        thread.start()
        sleep(2)  # stagger starts so four sessions do not hit the CLI at the same instant
    for thread in threads:
        thread.join()
    return rows


def _round_line(round_no: int, statuses: dict[str, dict], closed: int, rows: list[dict],
                state: dict) -> str:
    counts = Counter(row.get("status") for row in statuses.values())
    units_seen: dict[int, set[str]] = {}
    for row in rows:
        units_seen.setdefault(int(row.get("tier") or 0), set()).add(str(row.get("unit") or ""))
    units_by_tier = {tier: len(names) for tier, names in units_seen.items()}
    haiku = sum(sum((row.get("tokens") or {}).values()) for row in rows if row.get("tier") == 1)
    deepseek = sum(1 for row in rows if row.get("tier") == 2 and row.get("job_id"))
    escalations = sum(1 for row in rows if row.get("tier") == 3)
    return (f"ROUND {round_no} answered={counts.get('answered', 0)} partial={counts.get('partial', 0)} "
            f"not_found={counts.get('not_found', 0)} unverified={counts.get('unverified', 0)} "
            f"gaps_closed={closed} "
            f"units_by_tier={{1:{units_by_tier.get(1, 0)},2:{units_by_tier.get(2, 0)},3:{units_by_tier.get(3, 0)}}} "
            f"haiku_tokens={haiku:,} deepseek_jobs={deepseek} escalations={escalations} "
            f"spent=${state['spent']:.2f}")


def write_report(sandbox: Path, round_no: int, questions: list[dict], statuses: dict[str, dict],
                 rows: list[dict]) -> Path:
    from openpyxl import Workbook

    book = Workbook()
    sheet = book.worksheets[0] if book.worksheets else book.create_sheet()
    sheet.title = f"round_{round_no}"
    sheet.append(["qid", "status", "answer", "sources", "gap", "tier"])
    for question in questions:
        stored = statuses.get(question["id"]) or {}
        payload = stored.get("answer") or {}
        sheet.append([
            question["id"], stored.get("status") or "unanswered", payload.get("answer") or "",
            json.dumps(payload.get("sources") or [], ensure_ascii=False),
            stored.get("gap_type") or "", stored.get("tier"),
        ])
    sheet2 = book.create_sheet("ledger")
    headers = ["unit", "stage", "size", "attempt", "tier", "model", "outcome", "ts_start", "ts_end",
               "tokens_in", "cache_read", "cache_creation", "tokens_out", "thinking", "cost_usd",
               "cost_estimated", "tool_calls", "bash", "methods", "pages_model", "pages_code",
               "rows_added", "files_written", "error"]
    sheet2.append(headers)
    for row in rows:
        tokens = row.get("tokens") or {}
        sheet2.append([
            row.get("unit"), row.get("stage"), row.get("size"), row.get("attempt"), row.get("tier"),
            row.get("model"), row.get("outcome"), row.get("ts_start"), row.get("ts_end"),
            tokens.get("input"), tokens.get("cache_read"), tokens.get("cache_creation"),
            tokens.get("output"), tokens.get("thinking"), row.get("cost_usd"),
            bool(row.get("cost_estimated")),
            json.dumps(row.get("tool_calls") or {}), json.dumps(row.get("bash") or []),
            ", ".join(row.get("methods") or []), row.get("pages_model"), row.get("pages_code"),
            json.dumps(row.get("rows_added") or {}), json.dumps(row.get("files_written") or []),
            row.get("error"),
        ])
    path = store.inside(sandbox, "reports", f"round_{round_no}.xlsx")
    path.parent.mkdir(parents=True, exist_ok=True)
    book.save(path)
    return path


def run_loop(sandbox: Path, *, max_rounds: int = MAX_ROUNDS, budget: float = BUDGET_USD,
             as_of: str = AS_OF, tier1=None, tier2=None, sleep=time.sleep) -> int:
    conn = store.connect(sandbox)
    logfile = store.inside(sandbox, LOG)
    logfile.parent.mkdir(parents=True, exist_ok=True)
    try:  # the Opus session sees the loop in job_watch; a failure here never stops the run
        from reality_engine.scripts import job_watch
        job_watch.add("kec_gap_loop", str(logfile), pid=os.getpid())
    except Exception as exc:  # noqa: BLE001
        log(logfile, f"job_watch not registered: {type(exc).__name__}: {exc}")
    questions = load_questions(sandbox)
    state = {"spent": 0.0, "budget": budget, "as_of": as_of, "escalated": set()}
    statuses: dict[str, dict] = {}
    previous: dict[str, str | None] = {}
    no_close = 0
    log(logfile, f"T-048 gap loop start: {len(questions)} questions, budget ${budget:.2f}, as_of {as_of}")
    counts = prepare.prepare(sandbox, as_of=as_of)
    log(logfile, prepare.summary(counts))
    stop = prepare.blocked(counts)
    if stop:
        log(logfile, f"STOPPED prepare: {stop}")
        return 4
    for round_no in range(1, max_rounds + 1):
        rows: list[dict] = []
        if round_no == 1:
            # Resume: a restart does not answer again what round 1 already answered.
            done = set(store.latest_answers(conn))
            todo = [q for q in questions if q["id"] not in done]
            if done:
                log(logfile, f"resume: {len(done)} questions already answered in round 1, {len(todo)} to go")
            queue = deque(answer_units(todo, sandbox))
        else:
            queue = deque(fix_units(statuses, sandbox))
            rows += drain(queue, round_no, sandbox, conn, logfile, state,
                          tier1=tier1, tier2=tier2, sleep=sleep)
            queue = deque(reanswer_units(questions, statuses, sandbox, exclude=state.get("escalated")))
        rows += drain(queue, round_no, sandbox, conn, logfile, state,
                      tier1=tier1, tier2=tier2, sleep=sleep)
        statuses = store.latest_answers(conn)
        closed = sum(1 for qid, row in statuses.items()
                     if row.get("status") == "answered" and previous.get(qid) != "answered")
        no_close = no_close + 1 if closed == 0 else 0
        write_report(sandbox, round_no, questions, statuses, rows)
        log(logfile, _round_line(round_no, statuses, closed, rows, state))
        if state["spent"] >= budget:
            log(logfile, f"STOPPED budget ${budget:.2f} reached after round {round_no}")
            return 3
        if no_close >= 2:
            log(logfile, "DONE two rounds closed no gap")
            return 0
        previous = {qid: row.get("status") for qid, row in statuses.items()}
    log(logfile, f"DONE {max_rounds} rounds")
    return 0


def plan(sandbox: Path) -> list[str]:
    questions = load_questions(sandbox)
    units = answer_units(questions, sandbox)
    lines = [f"round 1 plan: {len(questions)} questions in {len(units)} answer units "
             f"(at most {BATCH} questions each), tier 1, model {MODEL}"]
    for unit in units:
        lines.append(f"  {unit.id}: {unit.size} questions, tier 1, {MODEL}")
    lines += [
        "prepare (code only, no model): every PDF under raw into kec.db doc_text page by page, an FTS5 "
        "index over it, a docs row per file with its type and filing date, and KEC's rows copied out "
        "of the read-only stores with their source table in `sources`; idempotent, logged as a "
        "tier-0 `prepare` unit; the run stops before answering when more than a third of the history "
        "PDFs cannot be dated",
        "tier 1 reads kec.db only: the strict MCP config has no servers, so no reality-data reply can "
        "fill the context; SQL with LIMIT and FTS queries are run by Bash/Python",
        "checks: a malformed report (not JSON, a qid missing, a bad status or gap type) fails the unit; "
        "a number that fails a check is stored as unverified with its reason and is not counted as answered",
        f"tier 2: a unit failing {MAX_ATTEMPTS} tier-1 attempts goes to one Sonnet 5.5 session at medium "
        "effort; an over-limit kill halves the unit first",
        "tier 3: a unit that also fails on Sonnet writes one escalation line per question, with its "
        "last check reason, and the loop moves on",
        f"round 1 fixes: at most {FIX_UNIT_MAX} questions per fix unit, one group of units per gap type "
        "(text_missing, not_extracted, needs_formula, wrong_store, unverified); absent is recorded, not fixed",
        f"rounds: fix + re-answer for at most {MAX_ROUNDS}, stop when two rounds close no gap",
        f"guards: as_of {AS_OF}, budget ${BUDGET_USD:.0f} Haiku list price, kill at 95,000 context "
        "tokens, usage-limit sleep 15 min, writes only inside the sandbox",
    ]
    return lines


def ledger_summary(sandbox: Path, opus_path: Path | None = None, since: str | None = None,
                   answered: int | None = None) -> str:
    rows = ledger.read(sandbox)
    db = store.inside(sandbox, store.DB_NAME)
    if answered is None:
        answered = 0
        if db.exists():
            conn = store.connect(sandbox)
            answered = sum(1 for row in store.latest_answers(conn).values()
                           if row.get("status") == "answered")
            conn.close()
    opus = ledger.opus_usage(opus_path, since) if opus_path and since else None
    return ledger.format_summary(ledger.summary(rows, answered, opus))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sandbox", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true", help="print the round-1 plan; no model call")
    parser.add_argument("--prepare-only", action="store_true",
                        help="run the prepare stage (code only, no model) and print its counts")
    parser.add_argument("--ledger-summary", action="store_true", help="print totals per tier and method")
    parser.add_argument("--opus-transcript", type=Path, help="managing Claude session transcript .jsonl")
    parser.add_argument("--since", help="ISO time; sum the transcript's usage from here on")
    parser.add_argument("--max-rounds", type=int, default=MAX_ROUNDS)
    parser.add_argument("--budget", type=float, default=BUDGET_USD)
    parser.add_argument("--as-of", default=AS_OF)
    args = parser.parse_args(argv)
    try:
        sandbox = ensure_sandbox(args.sandbox)
        if (args.opus_transcript is None) != (args.since is None):
            print("STOPPED --opus-transcript and --since go together", file=sys.stderr)
            return 4
        if args.dry_run:
            print("\n".join(plan(sandbox)))
            return 0
        if args.prepare_only:
            counts = prepare.prepare(sandbox, as_of=args.as_of)
            print(prepare.summary(counts))
            stop = prepare.blocked(counts)
            if stop:
                print(f"STOPPED prepare: {stop}")
                return 4
            return 0
        if args.ledger_summary:
            print(ledger_summary(sandbox, args.opus_transcript, args.since))
            return 0
        return run_loop(sandbox, max_rounds=args.max_rounds, budget=args.budget, as_of=args.as_of)
    except SystemExit as exc:
        print(str(exc), file=sys.stderr)
        return 4
    except Exception as exc:  # a terminal line whatever went wrong
        print(f"STOPPED {type(exc).__name__}: {str(exc)[:300]}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
