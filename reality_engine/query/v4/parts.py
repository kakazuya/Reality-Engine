"""The typed Ask contract for query layer v4 (tasks/arch_v4/QUERY_V4_DESIGN.md §C.1, §D.1).

WP4's executor imports this module and nothing else from the decomposer: one ``Part`` in,
exactly one ``Result`` out, per part.  No DB, no model, no I/O — importable anywhere.

    Ask  = entities[] + as_of + windows[] + parts[] + status
    Part = atom | formula, dims, window (index into windows), operator, shape, judgement
    Result = part_index, the part's concept, one value/list/series/path/verdict, answer_type

Ambiguity is emitted, never guessed: "promoter and public" is two Parts over one atom with
two ``holder_class`` readings; "NSE and BSE and sum" is three readings of ``exchange``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "OPERATORS",
    "SHAPES",
    "ANSWER_TYPES",
    "STATUSES",
    "ENTITY_LEVELS",
    "Window",
    "Entity",
    "Part",
    "Ask",
    "Result",
]

# §A.4: one closed set of 26 operators.  tests/test_v4_decompose.py asserts this tuple equals
# the registry's operator ids, so a new operator is a deliberate edit in both places.
OPERATORS = (
    "value_at",
    "series",
    "max_with_date",
    "min_with_date",
    "change",
    "pct_change",
    "growth",
    "rank",
    "screen",
    "compare",
    "lag_between",
    "event_window_return",
    "first_visible",
    "last_visible",
    "zscore",
    "count",
    "correlate",
    "aggregate",
    "walk",
    "rule",
    "exists",
    "join_entity_set",
    "threshold_cross",
    "span_days",
    "list_distinct",
    "describe_series",
)

# §C.1 shapes, plus "estimate" for the `own.estimate` atom (§A.8).
SHAPES = ("scalar", "series", "ranked_list", "path", "verdict", "passage", "estimate")

# §D.1 answer types.  A typed NOT IN DATA is not an answer to the gate.
ANSWER_TYPES = ("measured", "estimate", "proxy", "not_in_data")

# §C.3 / §A.6: the three outcomes a whole question has.
STATUSES = ("mapped", "not_in_data", "unmapped")

ENTITY_LEVELS = (
    "stock",
    "index",
    "sector",
    "theme",
    "mcap_bucket",
    "price_band",
    "fno",
    "market_wide",
    "driver",
    "policy",
)


@dataclass(frozen=True)
class Window:
    """One dated range a part reads (§C.1 `windows[]`).

    ``basis`` is how the text named it.  ``from_``/``to`` may be None when the text carries no
    usable date; the executor then reads the latest visible value and says so.
    """

    from_: str | None = None
    to: str | None = None
    basis: str = "as_of"  # named date|month|quarter end|YTD|since|as_of|event|span

    def to_dict(self) -> dict[str, Any]:
        return {"from": self.from_, "to": self.to, "basis": self.basis}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Window":
        return cls(from_=d.get("from"), to=d.get("to"), basis=d.get("basis") or "as_of")


@dataclass(frozen=True)
class Entity:
    """One entity of the ask: an ISIN (or a scope placeholder) plus its level (§C.1)."""

    isin: str | None = None
    level: str = "market_wide"
    symbol: str | None = None
    how: str = ""  # how the text named it: symbol|isin|bse_code|name|scope|theme|default

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"isin": self.isin, "level": self.level}
        if self.symbol:
            d["symbol"] = self.symbol
        if self.how:
            d["how"] = self.how
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Entity":
        return cls(isin=d.get("isin"), level=d.get("level") or "market_wide",
                   symbol=d.get("symbol"), how=d.get("how") or "")


@dataclass(frozen=True)
class Part:
    """Exactly one measure per part: ``atom`` XOR ``formula`` (§C.1)."""

    atom: str | None = None
    formula: str | None = None
    dims: dict[str, Any] = field(default_factory=dict)
    window: int = 0
    operator: str = "value_at"
    shape: str = "scalar"
    judgement: bool = False
    # provenance the decomposer emits; the executor may ignore it.
    clause: str = ""
    nid_reason: str = ""

    def __post_init__(self) -> None:
        if bool(self.atom) == bool(self.formula):
            raise ValueError(f"a part has exactly one of atom|formula, got {self.atom!r}/{self.formula!r}")
        if self.operator not in OPERATORS:
            raise ValueError(f"unknown operator {self.operator!r}")
        if self.shape not in SHAPES:
            raise ValueError(f"unknown shape {self.shape!r}")
        if not isinstance(self.dims, dict):
            raise ValueError("dims must be a dict")
        if not isinstance(self.window, int) or self.window < 0:
            raise ValueError(f"window is an index into Ask.windows, got {self.window!r}")

    @property
    def concept(self) -> str:
        """The measure id: the atom, or the formula id."""
        return self.atom or self.formula or ""

    def dim_values(self, dim: str) -> list[Any]:
        """Every reading of one dim on this part, as a list (dims hold scalars or lists)."""
        v = self.dims.get(dim)
        if v is None:
            return []
        return list(v) if isinstance(v, (list, tuple)) else [v]

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"dims": dict(self.dims), "window": self.window,
                             "operator": self.operator, "shape": self.shape}
        if self.atom:
            d["atom"] = self.atom
        if self.formula:
            d["formula"] = self.formula
        if self.judgement:
            d["judgement"] = True
        if self.clause:
            d["clause"] = self.clause
        if self.nid_reason:
            d["nid_reason"] = self.nid_reason
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Part":
        return cls(atom=d.get("atom"), formula=d.get("formula"), dims=dict(d.get("dims") or {}),
                   window=int(d.get("window") or 0), operator=d.get("operator") or "value_at",
                   shape=d.get("shape") or "scalar", judgement=bool(d.get("judgement")),
                   clause=d.get("clause") or "", nid_reason=d.get("nid_reason") or "")


@dataclass
class Ask:
    """One question, decomposed (§C.1).  ``status`` is ``mapped|not_in_data|unmapped``."""

    parts: list[Part] = field(default_factory=list)
    entities: list[Entity] = field(default_factory=list)
    as_of: str = ""
    windows: list[Window] = field(default_factory=list)
    status: str = "unmapped"
    residues: list[str] = field(default_factory=list)  # clause text the lexicon cannot express
    nid_reasons: list[str] = field(default_factory=list)
    mid: str = ""
    question: str = ""

    def __post_init__(self) -> None:
        if self.status not in STATUSES:
            raise ValueError(f"unknown status {self.status!r}")
        if not self.windows:
            self.windows = [Window()]
        for p in self.parts:
            if p.window >= len(self.windows):
                raise ValueError(f"part window {p.window} outside Ask.windows ({len(self.windows)})")

    @property
    def measures(self) -> list[str]:
        return [p.concept for p in self.parts]

    def to_dict(self) -> dict[str, Any]:
        return {
            "mid": self.mid,
            "question": self.question,
            "as_of": self.as_of,
            "status": self.status,
            "entities": [e.to_dict() for e in self.entities],
            "windows": [w.to_dict() for w in self.windows],
            "parts": [p.to_dict() for p in self.parts],
            "residues": list(self.residues),
            "nid_reasons": list(self.nid_reasons),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Ask":
        return cls(
            parts=[Part.from_dict(p) for p in d.get("parts") or []],
            entities=[Entity.from_dict(e) for e in d.get("entities") or []],
            as_of=d.get("as_of") or "",
            windows=[Window.from_dict(w) for w in d.get("windows") or []] or [Window()],
            status=d.get("status") or "unmapped",
            residues=list(d.get("residues") or []),
            nid_reasons=list(d.get("nid_reasons") or []),
            mid=d.get("mid") or "",
            question=d.get("question") or "",
        )


@dataclass
class Result:
    """One result per part, always (§D.1).  Produced by the executor, consumed by the renderer."""

    part_index: int
    atom: str = ""
    dims: dict[str, Any] = field(default_factory=dict)
    window: int = 0
    shape: str = "scalar"
    answer_type: str = "not_in_data"
    unit: str = ""
    value: Any = None                 # scalar, list, or dict for ranked_list/path/verdict
    period: str = ""
    isin: str = ""
    source_ref: str = ""
    known_at: str = ""
    method: str = ""                  # estimate/proxy
    inputs: dict[str, Any] = field(default_factory=dict)
    confidence: float | None = None
    rule_used: str = ""               # verdict
    verdict: str = ""
    nid_reason: str = ""
    tried: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.answer_type not in ANSWER_TYPES:
            raise ValueError(f"unknown answer_type {self.answer_type!r}")
        if self.shape not in SHAPES:
            raise ValueError(f"unknown shape {self.shape!r}")

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in vars(self).items() if v not in ("", None, {}, [])}
