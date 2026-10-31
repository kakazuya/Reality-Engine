"""Free-model judge for the truth panel (optional, brief item 4).

The panel is the authority.  A free-model judge may grade the whole bank **only** if it
agrees with the panel at 90% or better on rows it has not seen; this module exists to
measure that agreement, never to produce the reported number.  Nothing here is used by
``gate_run.py v4truth`` unless :func:`available` is true, and the truth table never
carries a judge figure.

    python tasks/answer_bench/truth_judge.py --panel fresh40

Free Beam through OpenCode Go, stable session id, usage recorded in the paid-call ledger
(``cost_ledger.record_usage``), ``reasoning_effort=low``.  No key -> it refuses, it does
not fall back to a paid model.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

REPO = Path(__file__).resolve().parents[2]
BENCH = REPO / "tasks" / "answer_bench"
PANEL = REPO / "tasks" / "arch_v4" / "TRUTH_PANEL_2026-10-31.jsonl"
BANK = REPO / "tasks" / "master_bank" / "MASTER_BANK.jsonl"
URL = "https://opencode.ai/zen/go/v1/chat/completions"
MODEL = "beam-free"

PROMPT = """You grade one answer to a question about an Indian listed company or market.

QUESTION: {question}
{as_of}
RUBRIC (the question bank's own method for this question; may be empty):
{rubric}

ANSWER RETURNED BY OUR SYSTEM:
{answer}

Decide using ONLY the answer and the question, not outside knowledge.
- RIGHT: the answer answers the question as posed, with the right reading and the period
  or company the question names.
- PARTIAL: a real value or passage for one reading of the ask, but a second reading
  (a judgement, a comparison side, a second period) is missing.
- WRONG: the value may be real, but the answer answers a different question, another
  company, or the wrong period; or a judgement/forecast ask got a raw number.

Reply with JSON only: {{"verdict":"RIGHT|PARTIAL|WRONG","reason":"<one line, max 20 words>"}}"""


def key() -> str:
    return os.environ.get("OPENCODE_GO_API_KEY_2") or os.environ.get("OPENCODE_GO_API_KEY") or ""


def available() -> bool:
    return bool(key())


def _rubric(parent_mid: str, bank: Mapping[str, Mapping[str, Any]]) -> str:
    rubric = (bank.get(parent_mid) or {}).get("rubric") or {}
    parts = []
    for name in ("required_steps", "forbidden", "ground_truth"):
        value = rubric.get(name)
        if value:
            parts.append(f"{name}: " + (value if isinstance(value, str)
                                        else "; ".join(map(str, value))))
    return "\n".join(parts) or "(the bank has no rubric for this question)"


def judge(row: Mapping[str, Any], api_key: str | None = None,
          bank: Mapping[str, Mapping[str, Any]] | None = None,
          model: str = MODEL) -> dict[str, Any]:
    """One panel row -> the judge's verdict and its one-line reason."""
    import requests

    from reality_engine.scripts.go_session import session_id
    from reality_engine.toolbelt.cost_ledger import record_usage

    api_key = api_key or key()
    if not api_key:
        raise RuntimeError("no OPENCODE_GO_API_KEY / OPENCODE_GO_API_KEY_2 in this environment")
    prompt = PROMPT.format(
        question=row.get("question") or "",
        as_of=f"AS OF: {row.get('as_of')}\n" if row.get("as_of") else "",
        rubric=_rubric(str(row.get("parent_mid") or ""), bank or {}),
        answer=row.get("answer") or "(no answer text)")
    headers = {"Authorization": f"Bearer {api_key}",
               "x-opencode-session": session_id("truth_judge", model, api_key)}
    payload = {"model": model, "reasoning_effort": "low", "max_tokens": 400,
               "messages": [{"role": "user", "content": prompt}]}
    last = ""
    for attempt in range(4):
        try:
            response = requests.post(URL, timeout=240, headers=headers, json=payload)
            if response.status_code != 200:
                last = f"HTTP {response.status_code}: {response.text[:120]}"
                time.sleep(5 * (attempt + 1))
                continue
            body = response.json()
            record_usage(model, body.get("usage"), "truth_judge")
            content = body["choices"][0]["message"].get("content") or ""
            parsed = json.loads(re.search(r"\{.*\}", content, re.S).group(0))
            return {"mid": row.get("mid"), "verdict": parsed.get("verdict"),
                    "reason": str(parsed.get("reason") or "")[:160]}
        except Exception as exc:  # noqa: BLE001 - one judge call cannot stop the panel
            last = repr(exc)[:150]
            time.sleep(3)
    return {"mid": row.get("mid"), "verdict": "ERROR", "reason": last}


def _bank() -> dict[str, dict]:
    out = {}
    if BANK.exists():
        for line in BANK.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                out[str(row.get("mid"))] = row
    return out


def agreement(panel_path: Path = PANEL, which: str = "fresh40", limit: int | None = None,
              api_key: str | None = None) -> dict[str, Any]:
    """Judge one panel block and compare with the panel's own verdicts."""
    rows = [json.loads(line) for line in Path(panel_path).read_text(encoding="utf-8").splitlines()
            if line.strip()]
    rows = [row for row in rows if row.get("panel") == which]
    if limit:
        rows = rows[:limit]
    bank = _bank()
    judged = [judge(row, api_key, bank) for row in rows]
    by_mid = {str(row.get("mid")): row for row in rows}
    exact = right_only = errors = 0
    confusion: dict[tuple[str, str], int] = {}
    for got in judged:
        panel = str(by_mid[str(got["mid"])]["verdict"])
        if got["verdict"] == "ERROR":
            errors += 1
            continue
        exact += int(got["verdict"] == panel)
        right_only += int((got["verdict"] == "RIGHT") == (panel == "RIGHT"))
        key_ = (panel, str(got["verdict"]))
        confusion[key_] = confusion.get(key_, 0) + 1
    called = len(judged) - errors
    return {"panel": which, "rows": len(rows), "called": called, "errors": errors,
            "agreement_exact": exact, "agreement_right_only": right_only,
            "right_only_pct": round(100.0 * right_only / max(1, called), 1),
            "meets_90": called > 0 and right_only / called >= 0.90,
            "confusion": {f"{a}->{b}": n for (a, b), n in sorted(confusion.items())},
            "judged": judged}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--panel", default="fresh40", choices=("fresh40", "fixed", "all"))
    parser.add_argument("--limit", type=int)
    parser.add_argument("--panel-file", type=Path, default=PANEL)
    args = parser.parse_args(list(argv) if argv is not None else None)
    if not available():
        print("no OPENCODE_GO_API_KEY / OPENCODE_GO_API_KEY_2: the free judge cannot run",
              file=sys.stderr)
        return 2
    rows = [json.loads(line) for line in args.panel_file.read_text(encoding="utf-8").splitlines()
            if line.strip()]
    which = args.panel if args.panel != "all" else "fixed"
    result = agreement(args.panel_file, which, args.limit)
    print(json.dumps({k: v for k, v in result.items() if k != "judged"}, indent=1))
    if which == "fixed" and args.panel == "all":
        print("(the fresh block is the held-out set; run --panel fresh40 for the agreement "
              "that counts)")
    return 0 if result["meets_90"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
