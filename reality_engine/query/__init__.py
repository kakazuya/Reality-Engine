"""Query layer v1 — sub-question decomposition + router + planners + answer assembly.

Entry point: ``answer(case)`` for one master-bank case; ``route(case)`` for the
deterministic planner chain and its slots; ``decompose(case)`` for the
sub-question split the answer and the strict grader both use.
"""
from __future__ import annotations

from .answer import METRIC_SYNONYMS, answer, assemble, hop_results, metric_matches, pit_audit
from .ctx import Ctx, QueryUnavailable
from .decompose import decompose
from .planners import envelope, load_planners
from .router import CANONICAL_ORDER, named_document, route

__all__ = ["answer", "assemble", "hop_results", "pit_audit", "Ctx", "QueryUnavailable",
           "envelope", "load_planners", "route", "CANONICAL_ORDER", "decompose",
           "METRIC_SYNONYMS", "metric_matches", "named_document"]
