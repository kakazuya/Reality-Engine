"""Query layer v0 — router + planners + arithmetic + answer assembly.

Entry point: ``answer(case)`` for one master-bank case; ``route(case)`` for the
deterministic planner chain and its slots.
"""
from __future__ import annotations

from .answer import answer, assemble, hop_results, pit_audit
from .ctx import Ctx, QueryUnavailable
from .planners import envelope, load_planners
from .router import CANONICAL_ORDER, route

__all__ = ["answer", "assemble", "hop_results", "pit_audit", "Ctx", "QueryUnavailable",
           "envelope", "load_planners", "route", "CANONICAL_ORDER"]
