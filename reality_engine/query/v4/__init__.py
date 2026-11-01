"""Query layer v4 (tasks/arch_v4/QUERY_V4_DESIGN.md).

The typed Ask contract lives in :mod:`reality_engine.query.v4.parts`; the algorithm that
fills it lives in :mod:`reality_engine.query.v4.decompose`.  No DB, no model.
"""
from __future__ import annotations

from .decompose import REGISTRY_PATH, Registry, decompose, decompose_case, load_registry
from .formulas import (
    FormulaEngine,
    FormulaRefusal,
    FormulaResult,
    Refusal,
    compute_formula,
    extraction_formulas,
)
from .parts import ANSWER_TYPES, OPERATORS, SHAPES, STATUSES, Ask, Entity, Part, Result, Window

__all__ = [
    "ANSWER_TYPES",
    "OPERATORS",
    "REGISTRY_PATH",
    "SHAPES",
    "STATUSES",
    "Ask",
    "Entity",
    "FormulaEngine",
    "FormulaRefusal",
    "FormulaResult",
    "Part",
    "Refusal",
    "Registry",
    "Result",
    "Window",
    "compute_formula",
    "decompose",
    "decompose_case",
    "extraction_formulas",
    "load_registry",
]
