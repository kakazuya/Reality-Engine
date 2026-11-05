"""Second reading of a finished answer (T-083): flag claims a careful reader would reject.

``number_check`` recomputes the arithmetic and stays separate.  This module reads the question, the answer's prose and
the answer's own ``numbers`` rows, asks the free ``beam-free`` model for the three kinds of defect a careful reader
sees without the store, and machine-checks every flag before keeping it:

``contradicts_own_numbers``  the prose says what its own figures reject: a wrong direction, a size word the change does
                             not support, a trend word against a series that moves the other way, a count of moves or
                             periods the answer does not show, a superlative another row beats.
``unsourced_cause``          a causal claim ("because", "driven by", "due to") whose cause has no figure, no cited
                             source and no quote in the answer.
``question_misfit``          the answer does not meet the question: a period named and not given, spans of different
                             length compared as like for like, standalone and consolidated mixed, a total where a
                             split or a per-unit figure was asked, a starting point before the window.

It does not fix anything and never edits an answer.  Every ``claim`` must be a contiguous span of the answer prose
after whitespace normalisation; one exception, a ``question_misfit`` about something missing, may leave ``claim``
empty and must name what the question asked.  A flag that fails the check is dropped and counted in
``dropped_flags``, never kept.  A truncated or unparseable reply is retried once and then recorded as a named
failure -- never as "no flags".

    python -m reality_engine.pilot3.second_read --answers-dir D:\\RealityEngine\\pilot10\\answer_a3 \\
        --qids .tmp\\t083_dev_qids.txt --out .tmp\\t083_dev_flags.jsonl [--pass-no 1] [--parallel 4] [--limit N]

Resumable: a ``qid`` + ``pass_no`` already in ``--out`` is skipped, so a restart costs only what is left.  One output
row per answer: ``qid``, ``pass_no``, ``status`` (``ok`` or a named failure), ``flags``, ``dropped_flags``,
``in_tok``, ``out_tok``, ``finish``, ``attempts``, ``error``.

Free model only: HTTP 402, or a body naming billing/quota/credits, stops the run (exit 3) rather than spend.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable, Iterable

import requests

from reality_engine.scripts.go_session import session_id
from reality_engine.toolbelt.cost_ledger import record_usage

URL = "https://opencode.ai/zen/go/v1/chat/completions"
MODEL = "beam-free"
KEY_ENVS = ("OPENCODE_GO_API_KEY_2", "OPENCODE_GO_API_KEY")
JOB = "pilot3_second_read"
CALLER = "pilot3_second_read"
REASONING_EFFORT = "low"
MAX_TOKENS = 4000
ATTEMPTS = 2                    # the first read plus exactly one retry on a truncated / unparseable reply
NUMBER_ROWS = 40                # a long table is cut; the first rows are the answer's headline figures
QUOTE_CHARS = 200
MAX_WHY = 600

KINDS = ("contradicts_own_numbers", "unsourced_cause", "question_misfit")

SYSTEM = """You are the second reader of one answer about an Indian listed company. You receive the question, the \
answer prose, and the answer's own number table (value, unit, period, source, quote). Flag claims a careful reader \
would reject, using only those three things. Never rewrite the answer, never supply the figure you think is right, \
and never judge whether a source existed that the worker did not have.

A flag is a claim you would defend. Ask: reading only this answer, would a careful reader reject these words? If the \
answer's own words can be read consistently with its figures, do not flag. A false flag costs more than a missed one.

Flag only these three kinds.

contradicts_own_numbers
  The prose says something its own figures contradict: a direction that is wrong ("fell from" when the later figure \
is higher); a size word the change does not support ("halved" for a fall of about a third); a superlative another \
figure beats; a level the prose ties to a period when the table prints that value in another period; a count ("two \
straight quarters", "six consecutive quarters") larger than the values the prose itself lists; a series called \
"steady", "stable" or "flat" that rises and falls.
  A trend word describes the whole span: "rose over the period" and "fell over the four quarters" are about the first \
and last figures, and a fall or rise in between does not contradict them. Only "every quarter", "each of", \
"steadily", "consistently" claim every step.

unsourced_cause
  A sentence attributes an observed change in a figure (it rose, fell, stayed flat, widened, narrowed, turned \
negative) to a cause the answer states only in general terms -- "favourable macros", "slower bank lending", "festive \
timing", "input costs" -- with no figure, no quote and no named source. A cause supported by any figure that bears on \
it, or attributed to management, a filing, a letter, a call or any document, even in paraphrase, does not qualify.

question_misfit
  The answer does not meet the question asked: a period the question named is missing, skipped or replaced by another \
with no reason given, or the answer gives only the first and last period when the question asked "each" or "every" \
quarter; spans of different length compared as like for like (a quarter's change set against a year's growth, two \
overlapping spans, an annualised rate set against a half-year figure, a six-month balance-sheet change set against a \
year-on-year rate); standalone and consolidated figures mixed in one series as one basis; two different measures set \
against each other as if one (a total premium against per-unit or APE components, a balance against a flow); a \
breakdown or segment split asked for and a total given; a per-unit figure asked for and a total given; a level where \
the question asked what drove a change; a change whose starting point is dated before the window; a count of items \
asked for and fewer delivered.
  For a flag about something missing, leave "claim" empty and name in "why" the words the question used and what the \
answer gives instead.

Never a flag:
- A value the prose states for several periods while the table prints it once: the table is a selection, so an \
omission is not evidence. Only a different value or period actually printed contradicts the prose.
- A cause the answer attributes to management, a filing, a document or a call; the number table need not carry it.
- Arithmetic the answer's own figures already imply: "the share count is identical, so the change is price"; a \
residual the answer calls a demerger gain; a flat series that supports "did not rise".
- A conditional or hypothetical sentence ("if input costs fall", "in a scenario where"): it proposes a possibility, \
not a claim about what happened.
- Why something matters when no change is being explained ("the buffer matters because agencies weight it").
- An accounting or computation mechanic ("after the model change, revenue includes the full value of goods"), or a \
computation explained as A minus B.
- A balance-sheet change from 31 March to 30 September against H1 revenue growth: that is the same span.
- A single quarter's year-on-year growth against a multi-year CAGR: both are annual rates, a progress check, not a \
like-for-like claim.
- A total, or the sum of its components, when either answers "how much did it hold or spend".
- A rating action, meeting or filing dated one day before or after the document that reports it.
- A rounding difference: 100% for 99.9998%, or a last printed digit.
- A filing covering FY26 (April 2025 to March 2026) as outside a November 2025 window: it covers November 2025 to \
March 2026.
- A session count against a calendar date range, or a market figure one session before the as-of date.
- An absence the question did not ask about, or a plain "not in the data" statement the answer does not contradict.
- Outside knowledge about the company, its sector or the market.

Writing a flag:
- "claim" must be a contiguous span copied character for character from the answer prose: no ellipsis, no paraphrase, \
no brackets, no added words. Use the sentence or clause that carries the defect. Leave it empty only for a \
question_misfit about something missing.
- "why" is one or two sentences: what the figures or the question require, and what the answer did. Name the figures \
you compared and their periods.
- One flag per defect. Do not file the same sentence twice.
- Most answers are sound. An empty list is the right reply for a sound answer.

Reply with one JSON object and nothing else:
{"flags": [{"kind": "...", "claim": "...", "why": "..."}]}"""


class BillingError(RuntimeError):
    """The provider refused on billing/quota: stop the run, never absorb it."""


class RateLimited(RuntimeError):
    """HTTP 429: the caller waits and retries within its attempt budget."""


# --- inputs -------------------------------------------------------------------
def _one_line(value: Any) -> str:
    if value is None:
        return ""
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return " ".join(text.split())


def load_answers(path: Path) -> dict[str, dict]:
    """``{qid: last event=answer row}``; ``start`` and ``check_failed`` rows are ignored."""
    rows: dict[str, dict] = {}
    try:
        handle = path.open(encoding="utf-8")
    except OSError:
        return rows
    with handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict) and row.get("event") == "answer" and row.get("qid"):
                rows[str(row["qid"])] = row          # a qid with two answer rows keeps the last
    return rows


def load_questions(path: Path) -> dict[str, dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, list):
        return {}
    return {str(r["qid"]): r for r in data if isinstance(r, dict) and r.get("qid")}


def load_rows(answers_dir: Path, qids: Iterable[str]) -> tuple[dict[str, tuple[dict, dict]], list[str]]:
    """``({qid: (question row, answer row)}, qids with no answer)``, one file read per symbol."""
    wanted = list(qids)
    by_symbol: dict[str, list[str]] = {}
    for qid in wanted:
        by_symbol.setdefault(qid.rsplit("-", 1)[0], []).append(qid)
    questions: dict[str, dict] = {}
    answers: dict[str, dict] = {}
    for symbol in sorted(by_symbol):
        questions.update(load_questions(answers_dir / f"{symbol}_questions.json"))
        answers.update(load_answers(answers_dir / f"{symbol}_answers.jsonl"))
    found = {qid: (questions.get(qid, {}), answers[qid]) for qid in wanted if qid in answers}
    missing = [qid for qid in wanted if qid not in found]
    return found, missing


def number_lines(numbers: Any) -> str:
    rows = numbers if isinstance(numbers, list) else []
    lines: list[str] = []
    for row in rows[:NUMBER_ROWS]:
        if not isinstance(row, dict):
            continue
        head = " ".join(_one_line(row[key]) for key in ("value", "unit", "period") if row.get(key) not in (None, ""))
        line = (f"- {head} | source: {_one_line(row.get('source')) or '-'} "
                f"| quote: {_one_line(row.get('quote'))[:QUOTE_CHARS] or '-'}")
        if row.get("formula"):
            line += f" | formula: {_one_line(row['formula'])} from {_one_line(row.get('inputs'))}"
        lines.append(line)
    if len(rows) > NUMBER_ROWS:
        lines.append(f"- ... {len(rows) - NUMBER_ROWS} more rows")
    return "\n".join(lines) or "- (the answer carries no number rows)"


def build_prompt(question_row: dict, answer_row: dict) -> tuple[str, str]:
    user = (f"QUESTION (asked as of {question_row.get('as_of') or '-'}):\n{question_row.get('question') or '-'}\n\n"
            f"ANSWER PROSE:\n{answer_row.get('answer') or '-'}\n\n"
            f"THE ANSWER'S OWN NUMBER TABLE:\n{number_lines(answer_row.get('numbers'))}")
    return SYSTEM, user


# --- the script check ---------------------------------------------------------
_WORD = re.compile(r"[a-z0-9]{4,}")
# Function words only: a count ("four") or a noun ("margin") is exactly what names the ask.
STOP = frozenset("""what were when which that this with from have does did give list show tell about over under
between during than then them they their there into within only more less said says please also answer""".split())


def normalise(text: Any) -> str:
    return " ".join(str(text or "").split()).lower()


def _strip_quoting(claim: str) -> str:
    return claim.strip().strip("\"'`\u201c\u201d\u2018\u2019").strip()


def claim_in_answer(claim: str, answer: str) -> bool:
    """The claim occurs in the prose after whitespace normalisation (case-insensitive, quotation marks ignored)."""
    span = normalise(_strip_quoting(claim))
    return bool(span) and span in normalise(answer)


def names_question(question: str, why: str) -> bool:
    asked = {word for word in _WORD.findall(normalise(question)) if word not in STOP}
    return bool(asked & set(_WORD.findall(normalise(why))))


def validate(question: str, answer: str, flags: list) -> tuple[list[dict], int]:
    """``(kept, dropped)``: the verbatim and question-naming checks, applied to every flag."""
    kept: list[dict] = []
    dropped = 0
    for flag in flags:
        if not isinstance(flag, dict):
            dropped += 1
            continue
        kind = str(flag.get("kind") or "").strip()
        why = _one_line(flag.get("why"))
        claim = _one_line(flag.get("claim"))
        if kind not in KINDS or not why:
            dropped += 1
            continue
        if kind == "question_misfit" and not claim:
            if not names_question(question, why):
                dropped += 1
                continue
            kept.append({"kind": kind, "claim": "", "why": why[:MAX_WHY]})
            continue
        if not claim_in_answer(claim, answer):
            dropped += 1
            continue
        kept.append({"kind": kind, "claim": _strip_quoting(claim), "why": why[:MAX_WHY]})
    return kept, dropped


def parse_reply(text: str) -> list | None:
    """The ``flags`` list of the first JSON object in ``text``; None when the reply is not a usable object."""
    if not text:
        return None
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None
    flags = data.get("flags") if isinstance(data, dict) else data if isinstance(data, list) else None
    return flags if isinstance(flags, list) else None


# --- model call ---------------------------------------------------------------
def resolve_key() -> str:
    try:
        from reality_engine.scripts.resource_watchdog import user_env
        env = user_env()
    except Exception:                    # a non-Windows shell has no registry to read
        env = dict(os.environ)
    return next((env[name] for name in KEY_ENVS if env.get(name)), "")


def call_read(system: str, user: str, key: str, *, timeout: int = 240, job: str = JOB,
              caller: str = CALLER) -> dict:
    """One request; raises RateLimited / BillingError, retries a transport error or 5xx twice.

    ``job`` is the stable OpenCode session tag (``go_session.session_id`` hashes job, model and key together), so a
    resumable run keeps one provider session per worker lane.  ``caller`` is the ledger label.
    """
    key = key or ""
    last = ""
    body: dict[str, Any] = {"model": MODEL, "max_tokens": MAX_TOKENS,
                            "messages": [{"role": "system", "content": system},
                                         {"role": "user", "content": user}]}
    if REASONING_EFFORT:
        body["reasoning_effort"] = REASONING_EFFORT
    for attempt in range(3):
        try:
            response = requests.post(
                URL, timeout=timeout,
                headers={"Authorization": f"Bearer {key}",
                         "x-opencode-session": session_id(job, MODEL, key)},
                json=body)
        except requests.RequestException as exc:
            last = repr(exc)[:200]
            time.sleep(3 * (attempt + 1))
            continue
        text = response.text or ""
        if response.status_code == 429:
            raise RateLimited(text[:120])
        if response.status_code == 200:
            data = response.json()
            choice = (data.get("choices") or [{}])[0]
            usage = data.get("usage") or {}
            record_usage(MODEL, usage, caller)
            return {"content": (choice.get("message") or {}).get("content") or "",
                    "finish": choice.get("finish_reason"),
                    "in_tok": int(usage.get("prompt_tokens") or 0),
                    "out_tok": int(usage.get("completion_tokens") or 0)}
        # a non-200 body is where a billing/quota refusal shows up: never on a 200
        if response.status_code == 402 or re.search(r"billing|quota|insufficient|credit", text, re.I):
            raise BillingError(f"HTTP {response.status_code}: {text[:200]}")
        last = f"HTTP {response.status_code}: {text[:160]}"
        time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"{MODEL} failed after 3 tries: {last}")


# --- one answer ---------------------------------------------------------------
def _row(qid: str, pass_no: int, status: str, **fields: Any) -> dict:
    row = {"qid": qid, "pass_no": pass_no, "status": status, "flags": [], "dropped_flags": 0,
           "in_tok": 0, "out_tok": 0, "finish": None, "attempts": 0, "error": ""}
    row.update(fields)
    return row


def read_one(qid: str, question_row: dict, answer_row: dict, *, client: Callable[..., dict], key: str,
             job: str = JOB, pass_no: int = 1) -> dict:
    """One answer read, retried once on truncation/unparseable; a failure is a named status, never "no flags"."""
    system, user = build_prompt(question_row, answer_row)
    question = str(question_row.get("question") or "")
    answer = str(answer_row.get("answer") or "")
    in_tok = out_tok = 0
    finish: Any = None
    failure = ""
    status = "unparseable"
    for attempt in range(ATTEMPTS):
        try:
            reply = client(system, user, key, job=job)
        except RateLimited as exc:
            failure = f"rate_limited: {exc}"[:200]
            status = "rate_limited"
            if attempt + 1 < ATTEMPTS:
                time.sleep(10)
                continue
            break
        except BillingError:
            raise
        except RuntimeError as exc:
            failure = f"api_error: {exc}"[:200]
            status = "api_error"
            continue
        in_tok += int(reply.get("in_tok") or 0)
        out_tok += int(reply.get("out_tok") or 0)
        finish = reply.get("finish")
        content = reply.get("content") or ""
        if finish == "length":
            failure = "reply truncated at the token budget"
            status = "truncated"
            continue
        parsed = parse_reply(content)
        if parsed is None:
            failure = f"reply is not a flags object: {_one_line(content)[:160]}"
            status = "unparseable"
            continue
        kept, dropped = validate(question, answer, parsed)
        return _row(qid, pass_no, "ok", flags=kept, dropped_flags=dropped,
                    in_tok=in_tok, out_tok=out_tok, finish=finish, attempts=attempt + 1)
    return _row(qid, pass_no, status, in_tok=in_tok, out_tok=out_tok, finish=finish,
                attempts=ATTEMPTS, error=failure)


# --- a run --------------------------------------------------------------------
def load_done(path: Path, pass_no: int) -> set[str]:
    done: set[str] = set()
    try:
        handle = path.open(encoding="utf-8")
    except OSError:
        return done
    with handle:
        for line in handle:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict) and row.get("pass_no") == pass_no and row.get("qid"):
                done.add(str(row["qid"]))
    return done


def run(answers_dir: Path | str, qids: Iterable[str], out_path: Path | str, *, pass_no: int = 1,
        parallel: int = 4, limit: int | None = None, client: Callable[..., dict] | None = None,
        key: str = "", job: str = JOB) -> dict:
    answers_dir, out_path = Path(answers_dir), Path(out_path)
    client = client or call_read
    wanted = [str(qid).strip() for qid in qids if str(qid).strip()]
    done = load_done(out_path, pass_no)
    todo = [qid for qid in wanted if qid not in done]
    if limit:
        todo = todo[:limit]
    rows, missing = load_rows(answers_dir, todo)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    counts: Counter[str] = Counter()
    lock = threading.Lock()
    with out_path.open("a", encoding="utf-8") as handle:
        def write(row: dict) -> None:
            row["pass_no"] = pass_no
            with lock:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
                handle.flush()
                counts[row["status"]] += 1

        for qid in missing:
            write(_row(qid, pass_no, "not_found", error="no event=answer row for this qid"))
        with ThreadPoolExecutor(max_workers=max(1, parallel)) as pool:
            futures = {pool.submit(read_one, qid, question_row, answer_row,
                                   client=client, key=key, job=job, pass_no=pass_no): qid
                       for qid, (question_row, answer_row) in rows.items()}
            try:
                for future in as_completed(futures):
                    write(future.result())
            except BillingError:
                for pending in futures:
                    pending.cancel()
                raise
    return {"pass_no": pass_no, "out": str(out_path), "skipped": len(wanted) - len(todo),
            "checked": len(rows) + len(missing), "status": dict(sorted(counts.items()))}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m reality_engine.pilot3.second_read", description=__doc__)
    parser.add_argument("--answers-dir", type=Path, required=True)
    parser.add_argument("--qids", type=Path, required=True, help="one qid per line")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--pass-no", type=int, default=1)
    parser.add_argument("--parallel", type=int, default=4)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args(argv)
    try:
        qids = [line.strip() for line in args.qids.read_text(encoding="utf-8").splitlines() if line.strip()]
    except OSError as exc:
        print(f"cannot read --qids: {exc}", file=sys.stderr)
        return 2
    if not qids:
        print("--qids names no qid", file=sys.stderr)
        return 2
    key = resolve_key()
    if not key:
        print("no API key: set " + " or ".join(KEY_ENVS), file=sys.stderr)
        return 2
    try:
        summary = run(args.answers_dir, qids, args.out, pass_no=args.pass_no, parallel=args.parallel,
                      limit=args.limit or None, key=key)
    except BillingError as exc:
        print(json.dumps({"error": "billing", "detail": str(exc)[:300]}), file=sys.stderr)
        return 3
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
