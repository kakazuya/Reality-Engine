"""Every number in an answer must come from a tool result or a calculator result.

``check_answer`` returns the numbers it saw, the ones a tool result supports, the ones
that appear only in the question (a restated premise, not a new claim) and the ones
with no support at all.  A number that fails the tool/calculator check is listed
against the row and counts against it when graded.
"""
from __future__ import annotations

import json
import math
import re

NUM_RE = re.compile(r"(?<![\w.])[-+]?\d[\d,]*(?:\.\d+)?")


def _norm(token: str) -> str:
    return token.replace(",", "").lstrip("+")


def _values(payloads) -> tuple[set[str], list[float]]:
    strings: set[str] = set()
    floats: list[float] = []
    for payload in payloads:
        text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
        for m in NUM_RE.finditer(text):
            raw = _norm(m.group(0))
            strings.add(raw)
            try:
                floats.append(float(raw))
            except ValueError:
                pass
    return strings, floats


def check_answer(answer: str, tool_payloads, calculator_values, question: str = "") -> dict:
    allowed_s, allowed_f = _values(tool_payloads)
    calc_s, calc_f = _values(calculator_values)
    allowed_s |= calc_s
    allowed_f += calc_f
    q_s, _ = _values([question])

    seen, supported, question_only, unsupported = [], [], [], []
    for m in NUM_RE.finditer(answer or ""):
        raw = _norm(m.group(0))
        if raw in seen:
            continue
        seen.append(raw)
        is_pct = (answer or "")[m.end():m.end() + 1] == "%"
        hit = raw in allowed_s
        if not hit:
            try:
                val = float(raw)
                candidates = [val, val / 100.0, val * 100.0] if is_pct else [val]
                hit = any(math.isclose(cand, other, rel_tol=1e-4, abs_tol=1e-6)
                          for cand in candidates for other in allowed_f)
            except ValueError:
                hit = False
        if hit:
            supported.append(raw)
        elif raw in q_s:
            question_only.append(raw)
        else:
            unsupported.append(raw)
    return {
        "numbers": seen,
        "supported": supported,
        "question_only": question_only,
        "unsupported": unsupported,
        "flagged": question_only + unsupported,
        "ok": not question_only and not unsupported,
        "note": "flagged = not found in any tool result or calculator result "
                "(question_only are restated premises, not new claims)",
    }
