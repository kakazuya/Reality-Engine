"""Record one answer with the number check in front of it (T-072).

Same CLI as the run-tooling ``record.py`` it replaces:

    python -m reality_engine.pilot3.answer_record <SYM> start <qid>
    python -m reality_engine.pilot3.answer_record <SYM> answer <answer.json>

``start`` stamps when work on a question begins.  ``answer`` reads
``{"qid", "answer", "numbers": [{"value","unit","period","source","quote", "formula", "inputs"}],
"status": "answered|partial|not_found", "tools": [...], "workaround_reason", "gap_class", "gap_note"}``
(the last three for the run ledger; ``workaround_reason`` is required when ``tools`` holds raw SQL), runs
``reality_engine.pilot3.number_check`` and appends it with ``finished_at`` -- but only if every number passes.
A failing answer is NOT recorded: each failure is printed and the process exits 1, so the worker fixes it.
A second attempt on the same qid carrying ``"check_override": "<reason>"`` is recorded with its failures
attached (``check_failures``), so no question gets stuck and every override is readable in the answer file.

Rows go to ``.tmp/<SYM>_answers.jsonl`` under the current directory, as before.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from reality_engine.pilot3 import number_check

STATUSES = ("answered", "partial", "not_found")


def answers_path(symbol: str) -> Path:
    return Path.cwd() / ".tmp" / f"{symbol.upper()}_answers.jsonl"


def _append(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _print_failures(report: dict) -> None:
    for finding in report["findings"]:
        if finding["severity"] == "fail":
            print(f"  FAIL {finding['code']}: {finding['detail']}", file=sys.stderr)


def record(symbol: str, kind: str, argument: str, out_dir: Path | None = None) -> int:
    """``start`` or ``answer``; returns the process exit code (0 recorded, 1 refused, 2 bad usage)."""
    now = datetime.now(timezone.utc).isoformat()
    path = (out_dir or Path.cwd() / ".tmp") / f"{symbol.upper()}_answers.jsonl"
    if kind == "start":
        _append(path, {"event": "start", "qid": argument, "at": now})
        print(f"recorded start {argument} at {now}")
        return 0
    if kind != "answer":
        print("kind must be start or answer", file=sys.stderr)
        return 2
    try:
        payload: Any = json.loads(Path(argument).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"cannot read the answer {argument}: {exc}", file=sys.stderr)
        return 2
    if not isinstance(payload, dict) or not payload.get("qid"):
        print("the answer must be an object with a qid", file=sys.stderr)
        return 2
    if payload.get("status") and payload["status"] not in STATUSES:
        print(f"status must be one of {STATUSES}", file=sys.stderr)
        return 2
    tools = [str(t) for t in (payload.get("tools") or [])]
    if any(t in ("sql", "pilot3_sql") for t in tools) and not str(payload.get("workaround_reason") or "").strip():
        # Run ledger (Shivam 11 Nov): raw SQL is a workaround; the answer says which typed tool could not give it.
        print("NOT recorded: the answer used raw SQL; add \"workaround_reason\" (what the typed tools could not "
              "return) and, if a data gap caused it, \"gap_class\" and \"gap_note\".", file=sys.stderr)
        return 1
    report = number_check.check_answer(payload)
    failures = [f for f in report["findings"] if f["severity"] == "fail"]
    override = str(payload.pop("check_override", "") or "").strip()
    if failures and not override:
        # Keep the failed attempt visible in the file, so a retry and an override can be read back.
        _append(path, {"event": "check_failed", "qid": payload["qid"], "at": now,
                       "findings": failures})
        print(f"NOT recorded: {payload['qid']} fails its number check. Fix the answer, or record a second "
              f"attempt with \"check_override\": \"<reason>\" in the answer file.", file=sys.stderr)
        _print_failures(report)
        return 1
    row = {"event": "answer", "at": now, **payload, "finished_at": datetime.now(timezone.utc).isoformat()}
    if failures:
        row["check_failures"] = failures
        row["check_override"] = override
        print(f"recorded {payload['qid']} WITH AN OVERRIDE ({len(failures)} failing checks): {override}")
        _print_failures(report)
    else:
        print(f"recorded answer {payload['qid']} at {row['at']} ({len(report['findings'])} warnings)")
    _append(path, row)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m reality_engine.pilot3.answer_record",
                                     description="Record an answer only if its numbers recompute.")
    parser.add_argument("symbol", help="the company symbol, e.g. KEC")
    parser.add_argument("kind", choices=("start", "answer"), help="what to stamp")
    parser.add_argument("argument", help="a qid for start, a path to the answer JSON for answer")
    parser.add_argument("--dir", help="write .tmp/<SYM>_answers.jsonl beside this directory instead of the cwd")
    args = parser.parse_args(argv)
    return record(args.symbol, args.kind, args.argument, Path(args.dir) if args.dir else None)


if __name__ == "__main__":
    raise SystemExit(main())
