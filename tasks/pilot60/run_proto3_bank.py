"""Run the three-company bank rows through the v4 engine: no model calls, no grading.

Every question comes from ``tasks/pilot60/PILOT_BANK_2026-10-31.jsonl`` whose entities are
only the three prototype companies (BAJFINANCE, HINDALCO, KEC), plus every row the prior
answer file carried, so both runs cover the same questions.

    python tasks/pilot60/run_proto3_bank.py            # every row
    python tasks/pilot60/run_proto3_bank.py --limit 5  # a smoke run

Writes ``tasks/pilot60/PROTOTYPE3_ENGINE_ANSWERS_2026-11-02.jsonl``, one row per question:
``mid``, ``question``, ``answer``, ``rows_used``, ``store``, ``status`` (+ the per-part typed
outcome and the refusal reasons).  Prints one summary: rows, answered, refused by reason.
It prints no score and grades nothing: the grade on this run is a separate, hand read.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from reality_engine.pilot.proto3 import BANK, PROTO_ISINS, SYMBOLS  # noqa: E402
from reality_engine.query.v4 import execute, run  # noqa: E402

PRIOR = REPO / "tasks" / "pilot60" / "PROTOTYPE3_ANSWERS_2026-11-01.jsonl"
OUT = REPO / "tasks" / "pilot60" / "PROTOTYPE3_ENGINE_ANSWERS_2026-11-02.jsonl"
AS_OF = "2026-10-19"   # Shivam's ruling: a question with no date uses this snapshot date


def in_scope(case: dict) -> bool:
    """Every entity the row names is one of the three prototype ISINs, and it names one."""
    entities = case.get("entities") or []
    if not entities:
        return False
    for item in entities:
        isin = str(item.get("isin") or "") if isinstance(item, dict) else ""
        symbol = str(item.get("symbol") or "") if isinstance(item, dict) else str(item)
        if isin not in PROTO_ISINS and ISIN_BY_SYMBOL.get(symbol.upper()) not in PROTO_ISINS:
            return False
    return True


ISIN_BY_SYMBOL = {symbol.upper(): isin for isin, symbol in SYMBOLS.items()}


def cases() -> list[dict]:
    """The bank rows in scope, then any prior-answer row the bank no longer carries."""
    chosen: dict[str, dict] = {}
    for line in BANK.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        case = json.loads(line)
        if in_scope(case):
            chosen[str(case["mid"])] = case
    added = 0
    if PRIOR.is_file():
        for line in PRIOR.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            prior = json.loads(line)
            mid = str(prior.get("mid") or "")
            if not mid or mid in chosen:
                continue
            entities = [{"symbol": symbol, "isin": ISIN_BY_SYMBOL.get(str(symbol).upper())}
                        for symbol in prior.get("entities") or []]
            if not any(item["isin"] in PROTO_ISINS for item in entities):
                continue
            chosen[mid] = {"mid": mid, "question": prior.get("question") or "",
                           "as_of": prior.get("as_of") or AS_OF, "entities": entities}
            added += 1
    print(f"bank rows in scope {len(chosen) - added}, prior-answer rows added {added}",
          flush=True)
    return list(chosen.values())


def reason_key(reason: str) -> str:
    """A short bucket for a typed refusal, from its own wording (never a guessed cause)."""
    for marker, label in (
            ("rules", "excluded reading named in the question"),
            ("split (", "split of a total the store holds whole"),
            ("names no topic", "narrative ask with no topic dim"),
            ("names no single entity", "entity not resolved to one company"),
            ("the ask names no", "unnamed reading: the unit of the answer is ambiguous"),
            ("is not held", "measure not held for the entity"),
            ("no ", "no row in the store"),
            ("not held", "measure not held for the entity"),
            ("stale", "latest row past the staleness limit"),
            ("executor error", "executor error")):
        if marker in reason:
            return label
    return " ".join(reason.split())[:70] or "unspecified"


def parts_of(row: dict) -> list[dict]:
    """One entry per part: its typed outcome and the rows it used (period + value)."""
    out = []
    for result in row["results"]:
        item = {key: result.get(key) for key in
                ("atom", "formula", "answer_type", "value", "period", "source_ref",
                 "nid_reason")}
        rows = [{"period": value.get("period"), "value": value.get("value")}
                for value in (result.get("values") or [])[:8]]
        if rows:
            item["rows"] = rows
        out.append(item)
    return out


def stores_of(row: dict) -> list[str]:
    """The store each answered part came from (a derived formula names its own atoms)."""
    out = set()
    for result in row["results"]:
        ref = str(result.get("source_ref") or "")
        if ref:
            out.add(ref.split(":", 1)[0])
    return sorted(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--limit", type=int, help="run at most N rows (a smoke run)")
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args(argv)

    rows = cases()
    if args.limit:
        rows = rows[:args.limit]
    written: list[dict] = []
    answered = 0
    reasons: Counter = Counter()
    with run.Stores() as stores:
        resolver = run.Resolver(run.universe(), run.identities(), run.universe_isins())
        for index, case in enumerate(rows, 1):
            if not str(case.get("question") or "").strip():
                continue
            case.setdefault("as_of", AS_OF)
            try:
                row = run.run_case(case, stores, resolver, run.execute_registry())
            except Exception as exc:  # noqa: BLE001 - one bad row must not stop the run
                written.append({"mid": case.get("mid"), "question": case.get("question"),
                                "answer": "", "rows_used": 0, "store": [],
                                "status": "refused",
                                "reasons": [f"run error: {type(exc).__name__}: {exc}"],
                                "parts": []})
                reasons["run error"] += 1
                continue
            nid = [result.get("nid_reason") or "" for result in row["results"]
                   if result.get("answer_type") == "not_in_data"]
            status = "answered" if row["case_answered"] else "refused"
            if status == "answered":
                answered += 1
            for reason in nid:
                reasons[reason_key(reason)] += 1
            written.append({
                "mid": row["mid"], "question": row["question"], "answer": row["answer"],
                "rows_used": sum(len(result.get("values") or [])
                                 for result in row["results"]),
                "store": stores_of(row), "status": status,
                "as_of": row["as_of"], "entity": row.get("entity"),
                "reasons": nid, "parts": parts_of(row)})
            if index % 25 == 0:
                print(f"  {index}/{len(rows)} rows", flush=True)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as handle:
        for row in written:
            handle.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    print(f"wrote {out}")
    print(f"rows {len(written)}")
    print(f"answered {answered}")
    print(f"refused {len(written) - answered}")
    for reason, count in reasons.most_common():
        print(f"  {count:4d}  {reason}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
