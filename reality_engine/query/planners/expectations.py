"""EXPECTATIONS gate: judgement asks have no held store, and must say so.

The bank's opinion templates ask for a recommendation ("enter now or wait",
"what would break the thesis", "does the multiple imply").  No consensus,
target-price or valuation-advice store is held (the company's own guidance is,
but that is not advice).  This gate keeps those cases honest: the numeric part
may be answered, the judgement is reported missing.
"""
from __future__ import annotations

import re
from typing import Any

from ..router import OPINION_ASK, OPINION_TEMPLATES
from . import envelope

CHECKED = ["(no consensus / target-price / valuation-advice store is held)"]


def plan(slots: dict[str, Any], as_of: str, ctx: Any) -> dict[str, Any]:
    template = str(slots.get("template") or "")
    question = str(slots.get("question") or "")
    if template not in OPINION_TEMPLATES and not OPINION_ASK.search(question):
        return envelope("EXPECTATIONS", ok=True, na=True, checked=CHECKED,
                        detail="factual ask; no judgement gate")
    detail = ("the held numbers may answer the factual part, but no consensus / target-price / "
              "valuation-advice store exists, so the judgement this ask wants is not in data")
    return envelope("EXPECTATIONS", ok=False, why="schema", checked=CHECKED,
                    gap="consensus_estimates", detail=detail, nid_reason=detail)
