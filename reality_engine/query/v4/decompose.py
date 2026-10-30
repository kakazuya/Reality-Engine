"""The v4 decomposer: question text -> typed :class:`Ask` (tasks/arch_v4/QUERY_V4_DESIGN.md §C.2).

Algorithmic and closed: no model, no network, no database.  The only input besides the
question is the generated concept registry (``tasks/arch_v4/concept_registry.json``, WP1).
Bank fields (``template``, ``family``, ``chain``, ``period``, ``answer_kind``) are never
read here — they belong to the evaluator.

    text -> clauses -> per-clause surface hits (two passes: CONTENT then MODIFIER)
         -> one part per measure the clause names: atom | formula | claim topic |
            operator/rule default (a clause can name several measures)
         -> dims as *readings*: a clause naming two values of one dim emits two parts
         -> entity from the text (no DB: symbol/ISIN/BSE code/name/scope/theme/default)
         -> window from the existing ``period_bounds()``, question text only

Ambiguity is emitted, not guessed: "promoter and public" is two parts over ``hold.pct``;
"NSE and BSE and the sum" is three ``exchange`` readings of one atom; "raw and adjusted" is
two ``basis`` readings.  A clause that names a measure the lexicon cannot express is
*residue*, and any residue makes the whole ask ``unmapped`` — never a guessed measure.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from reality_engine.query.router import period_bounds
from reality_engine.query.v4.parts import Ask, Entity, Part, Window

__all__ = [
    "Registry",
    "load_registry",
    "split_clauses",
    "decompose",
    "decompose_case",
    "REGISTRY_PATH",
]

REGISTRY_PATH = Path(__file__).resolve().parents[3] / "tasks" / "arch_v4" / "concept_registry.json"

# §C.2: two passes, so a period phrase ("ytd high") cannot shadow the measure ("high").
CONTENT_KINDS = ("atom", "formula", "claim_topic", "rule", "dim")
MODIFIER_KINDS = ("operator", "period", "entity_set")

#: The atom a rule reads when the ask names the judgement but not the measure (§A.4).
#: Rules with no row here fall back to ``claim.claim``: a verdict always has a narrative leg.
RULE_DEFAULT_ATOM = {
    "gap_type": "price.open",
    "breakout": "price.close",
    "distribution_absorption": "price.delivery_pct",
    "margin_bottom": "f.margin",
    "control_change": "hold.pct",
    "solvency": "hold.pledge_pct",
    "valuation_premium": "f.ratio",
    "receivables_quality": "fin.receivables",
    "say_vs_do": "claim.claim",
    "dilution": "price.shares_out",
    "golden_cross": "price.sma",
    "support_resistance": "price.low",
}

#: Operators that qualify the whole ask ("in what order", "the combined total") rather than
#: one reading; on a dim-only clause they must not overwrite the inherited reading's operator.
_CROSS_PART_OPS = {"rank", "compare", "list_distinct", "aggregate", "count", "exists",
                   "join_entity_set", "screen"}

#: Operators that *do* belong to a single reading, so they override on inheritance.
_READING_OPS = {"max_with_date", "min_with_date", "change", "pct_change", "growth",
                "event_window_return", "threshold_cross", "first_visible", "last_visible",
                "zscore", "series", "describe_series", "value_at", "span_days"}

#: A dim is a qualifier *on* an atom (§A.2), so a dim named without its atom still names the
#: measure: "ROE improves" is `f.ratio` with `ratio_kind=roe`, "how much does FII own" is
#: `hold.pct` with `holder_class=fii`.  exchange/basis/consolidation qualify *any* measure and
#: are deliberately absent here.
_DIM_OWNER = {
    "holder_class": "hold.pct",
    "ratio_kind": "f.ratio",
    "npa_kind": "fin.npa",
    "margin_kind": "f.margin",
    "topic": "claim.claim",
    "flow_kind": "macro.flow",
    "page": "text.passage",
    "est_atom": "own.estimate",
    "lookback": "price.sma",
    "direction": "claim.claim",
}

#: A document pointer ("where in the report", "page 41 of the deck") asks for a passage, not
#: for a macro claim that merely happens to use the word "report".
_DOC_POINTER = re.compile(
    r"\b(?:report|deck|presentation|transcript|filing|document|annual report|page|slides?)\b", re.I)
_PAGE_RE = re.compile(r"\bpage\s*(\d{1,4})\b", re.I)
#: A passage ask *locates* the text ("where in the report", "which page", "quote the section").
#: A doctype alone ("results", "concall", "presentation") is a source qualifier, not a passage
#: ask: "the concall remark" is a claim, and "the session after its results" is context.
_LOCATOR = re.compile(
    r"\b(?:where|which\s+page|what\s+page|page|section|slide|quote|quoted|passage|paragraph|para)\b",
    re.I)
#: "how much does FII *own*" is a holding; "how much did FII *sell*" is a flow (§A.2 flow_kind).
_HOLD_VERB = re.compile(r"\b(?:own\w*|hold\w*|stake|shareholding|ownership)\b", re.I)
_FLOW_VERB = re.compile(r"\b(?:bought|buy|bought|sold|sell|net|flow\w*|kharid\w*|bech\w*)\b", re.I)
#: A clause that excludes a reading ("not total traded quantity", "excluding intraday") is an
#: exclusion, not an ask: it must not create a part of its own.
_EXCLUSION = re.compile(r"^\s*(?:not|no|excluding|except|excl\.)\b", re.I)

#: Hinglish particles that the generated lexicon maps to English ratio dims by collision
#: ("date pe" -> pe ratio, "de do" -> D/E).  They are particles, not dim values.
_HINGLISH_STOP = {"pe", "de", "ka", "ki", "ke", "ko", "se", "ne", "mein", "hai", "hain", "tak",
                  "bhi", "aur", "par", "tha", "thi", "gaya", "gayi", "kar", "kya", "kitna",
                  "kitni", "diya", "kiya", "hua", "hui"}

#: A narrative verb alone is not a measure; with a measure dim it defers to that dim's atom
#: ("say which HFC's ROE improves" asks for f.ratio, not for the fact that someone spoke).
_NARRATIVE_VERB = {"say", "says", "said", "tell", "tells", "told", "explain", "explains",
                   "explained", "mention", "mentions", "mentioned", "state", "states", "stated",
                   "disclose", "discloses", "disclosed", "according", "report", "reports",
                   "reported", "reporting", "flag", "flags", "flagged"}

#: A narrative *noun* names the claim atom directly ("the concall remark", "management
#: commentary"): one atom, the topic is a dim (§A.1).
_NARRATIVE_NOUN = {"remark", "remarks", "comment", "comments", "commentary", "disclosure",
                   "disclosures", "statement", "statements", "narrative", "guidance"}

#: §A.4 shapes by operator.
_SHAPE = {
    "series": "series",
    "describe_series": "series",
    "rank": "ranked_list",
    "screen": "ranked_list",
    "list_distinct": "ranked_list",
    "join_entity_set": "ranked_list",
    "walk": "path",
    "rule": "verdict",
}

#: The residue list (§C.3 "unmapped residue | the residue list"): measure nouns the bank uses
#: that a clause can name without resolving.  A clause that carries one of these and resolves
#: to no measure is residue, not filler.
_MEASURE_WORDS = set("""
revenue sales margin ebitda pat profit loss eps debt cash capex inventory receivables payables
cwip investments borrowing borrowings order book orderbook backlog capacity utilisation
utilization segment segments delivery volume turnover mcap close price high low open
promoter public fii dii pledge holding shareholding stake shares outstanding npa nim
credit cost loan loans advances aum roi roe roce roic dso dpo ccc growth return returns
cagr yoy qoq spread premium discount ratio multiple valuation pe pb ev
guidance target targets plan plans demand supply pricing competition
market share commissioning expansion commission
products product facilities facility business model brand technology patent
order intake inflow orders wins win tender tenders bid pipeline
dividend buyback rights issue bonus split demerger merger acquisition
audit opinion qualifications qualification auditor internal control going concern
working capital free float index inclusion weight weights
fpi flow flows inav nav etf oi interest rate rates repo
rainfall monsoon wpi cpi inflation iip gst collections credit growth deposit
tariff tariffs duty duties subsidy subsidies pli budget rbi sebi
volatility beta correlation alpha drawdown peak trough
employee employees headcount attrition wage wages freight throughput
capex credit ratings rating inventory days
""".split())

#: A clause naming a date but no measure is a qualifier on the measure before it ("with the
#: date", "kis date ko"): the operator that carries the date is max/min-with-date (§A example).
_DATE_QUALIFIER = re.compile(
    r"\b(?:the\s+date|which\s+date|what\s+date|kis\s+date|kab|when\s+(?:was|did|were)|on\s+which\s+date)\b",
    re.I)

# --- clause split (same rule as WP1: lower-case "and" splits, a capitalised name does not) ---
_STRONG_SPLIT = re.compile(r"\s*[+;|]\s*|\s*\?\s*|\s+(?:aur|bhi|then|what about)\s+", re.I)
_LOWER_AND_SPLIT = re.compile(
    r"\s+(?:and|plus|vs|versus|compared to|compared with|or)\s+(?=[a-z0-9])")
_COMMA_SPLIT = re.compile(r"\s*,\s*(?:and\s+|aur\s+|then\s+)?(?=[a-z])")
# "Did DSO and CFO/PAT improve": a capitalised *named measure* after "and" is a second ask,
# while "CG Power and Industrial Solutions" stays one clause (§C.2's stated limit).
_AND_CAPITAL = re.compile(r"\s+(?:and|or|plus)\s+([A-Za-z0-9/&%\-]+)")

_PUNCT = re.compile(r"[^a-z0-9%]+")
_WS = re.compile(r"\s+")

#: "M & B Engineering (NSE: MBEL)" names the listing venue, not an exchange reading.
_TICKER_ANNOTATION = re.compile(r"\b(?:NSE|BSE)\s*:\s*[A-Z][A-Z0-9&\-]*")
#: A possessive head ("Tata Steel's", "Coal India's") is an entity name; its words
#: ("steel", "coal", "bank") must not be read as commodity/flow measures.  A colon head is
#: *not* masked: "Bank NIM:" and "Defence pack:" name the measure/scope itself.
_COMPANY_SPAN = re.compile(
    r"\b[A-Z][A-Za-z0-9&.\-]*(?:\s+[A-Z][A-Za-z0-9&.\-]*){0,3}(?='s\b|\u2019s\b)")
#: A capitalised multi-word span whose word is also a commodity surface ("Coal India",
#: "JSW Steel", "Hindustan Copper") is a company name, not a commodity ask.
_NAME_SPAN = re.compile(r"\b[A-Z][A-Za-z0-9&.\-]*(?:\s+[A-Z][A-Za-z0-9&.\-]*){1,3}\b")
_NAME_MASK_IDS = {"macro.commodity_close"}


def _mask_names(text: str, reg: Registry) -> str:
    def repl(m: re.Match) -> str:
        toks = [t.lower() for t in re.split(r"\s+", m.group(0)) if t]
        if any(t in {"etf", "etfs", "fund", "funds"} for t in toks):
            return m.group(0)
        is_commodity = [any(e["id"] in _NAME_MASK_IDS for e in reg.matcher.by_surface.get(t, ()))
                        for t in toks]
        if all(is_commodity):
            return m.group(0)      # "Steel HRC": the whole span is the commodity, not a name
        return " " if any(is_commodity) else m.group(0)

    return _NAME_SPAN.sub(repl, text)

# entity hints, text only (the executor resolves them against security_master, PIT)
_ISIN_RE = re.compile(r"\bINE[0-9A-Z]{9}[0-9]\b")
_NSE_SYMBOL_RE = re.compile(r"\b(?:NSE|BSE)\s*:\s*([A-Z][A-Z0-9&\-]{1,19})\b")
_BSE_CODE_RE = re.compile(r"\b(?:BSE|code)\D{0,12}(\d{5,6})\b", re.I)
_CAPS_RE = re.compile(r"\b[A-Z][A-Z0-9&\-]{2,}\b")
_HEAD_STEM = re.compile(r"^\s*([A-Za-z][A-Za-z0-9&\- ]{2,28}?)\s*(?::|—|–)\s")
_THEME_STEM = re.compile(
    r"\b([a-z][a-z\-]+(?:\s+[a-z][a-z\-]+)?)\s+"
    r"(?:stocks?|companies|makers?|players?|names?|pack|suppliers?|exporters?|importers?|firms?|counters)\b")

#: Tokens that look like a symbol but are market vocabulary, not an entity.
_NOT_A_SYMBOL = set("""
NSE BSE ISIN NIFTY SENSEX SEBI RBI PIB FY Q1 Q2 Q3 Q4 PAT EPS EBITDA EBIT ROE ROCE ROIC
DII DIIs FII FIIs FPI MF NAV INAV ETF OI AUM PE PB EV CAGR YOY QOQ YTD SME IPO ESOP SAST
GST CPI WPI IIP PLI NBFC PSU CDMO CRAMS API US UK EU GSTN TDS
DATA NOT NIFTY100 NIFTY50 SMALLCAP MIDCAP LARGECAP FMCG IT CV OEM QIP OFS
""".split())


def norm(s: str) -> str:
    s = (s or "").lower().replace("ñ", "n").replace("&", " and ")
    return _WS.sub(" ", _PUNCT.sub(" ", s)).strip()


def _split_named_measures(text: str, measures: frozenset[str]) -> list[str]:
    """Split on "and/or <a capitalised named measure>": two asks, not one company name."""
    if not measures:
        return [text]
    out: list[str] = []
    last = 0
    for m in _AND_CAPITAL.finditer(text):
        token = m.group(1).lower()
        # "CFO/PAT" names two measures in one token; either half splits the clause
        if any(t in measures for t in (token, *(token.split("/")), *(token.split("-")))):
            left = re.sub(r"\s+(?:and|or|plus)\s*$", "", text[last:m.start(1)])
            out.append(left)
            last = m.start(1)
    out.append(text[last:])
    return [piece.strip() for piece in out if piece.strip()]


def split_clauses(text: str, measures: frozenset[str] = frozenset()) -> list[str]:
    """Split one question into clauses (§C.2)."""
    out: list[str] = []
    for chunk in _STRONG_SPLIT.split(text or ""):
        for piece in _LOWER_AND_SPLIT.split(chunk):
            for sub in _COMMA_SPLIT.split(piece):
                for sentence in _SENTENCE_SPLIT.split(sub):
                    out.extend(_split_named_measures(sentence, measures))
    return out or [text or ""]


class Matcher:
    """Two-pass surface matcher over one lexicon: CONTENT kinds, then MODIFIER kinds."""

    def __init__(self, lexicon: list[dict]):
        # one surface can be several entries ("fii" is both a flow atom and a holder dim)
        self.by_surface: dict[str, list[dict]] = {}
        for e in lexicon:
            self.by_surface.setdefault(e["surface"], []).append(e)
        self.rx: dict[str, re.Pattern | None] = {}
        for name, kinds in (("content", CONTENT_KINDS), ("modifier", MODIFIER_KINDS)):
            surfaces = sorted((s for s, es in self.by_surface.items()
                               if any(e["kind"] in kinds for e in es)),
                              key=len, reverse=True)
            pattern = "|".join(re.escape(s) for s in surfaces)
            self.rx[name] = re.compile(rf"(?<![a-z0-9])(?:{pattern})(?![a-z0-9])") if surfaces else None

    def hits(self, clause: str) -> list[dict]:
        """Lexicon entries found in one clause, in text order (content pass first)."""
        text = norm(clause)
        out: list[dict] = []
        for name in ("content", "modifier"):
            rx = self.rx[name]
            if not rx:
                continue
            for m in rx.finditer(text):
                for e in self.by_surface.get(m.group(0), ()):
                    hit = {"kind": e["kind"], "id": e["id"], "surface": m.group(0)}
                    if hit not in out:
                        out.append(hit)
        return out


class Registry:
    """The concept registry, loaded once (§A): atoms, dims, formulas, operators, lexicon."""

    def __init__(self, data: dict):
        self.data = data
        self.atoms: dict[str, dict] = {a["atom_id"]: a for a in data["atoms"]}
        self.dims: dict[str, dict] = {d["dim_id"]: d for d in data["dims"]}
        self.formulas: dict[str, dict] = {f["formula_id"]: f for f in data["formulas"]}
        self.operators: dict[str, dict] = {o["op_id"]: o for o in data["operators"]}
        lexicon = list(data["lexicon"])
        # §A.2 declares the dim *values*; each one is a surface in its own right.  A generated
        # lexicon that missed a declared value ("fii", "dii") must not make the dim unreachable.
        lexicon = list(data["lexicon"])
        self.dim_value_words: set[str] = set()
        self.dim_by_word: dict[str, list[tuple[str, str]]] = {}
        for d in data["dims"]:
            dim_id = d["dim_id"]
            values = d.get("values")
            if not isinstance(values, list):
                continue
            for v in values:
                surface = str(v).lower()
                if not surface or surface.isdigit():
                    continue
                self.dim_value_words.add(surface)
                self.dim_by_word.setdefault(surface, []).append((dim_id, str(v)))
                entry = {"surface": surface, "kind": "dim", "id": f"{dim_id}={v}"}
                if not any(e["surface"] == surface and e["kind"] == "dim" and e["id"] == entry["id"]
                           for e in lexicon):
                    lexicon.append(entry)
                # the lexicon's own convention: a plural variant of a single-word value
                if " " not in surface:
                    plural = {"surface": surface + "s", "kind": "dim", "id": f"{dim_id}={v}"}
                    if not any(e["surface"] == plural["surface"] and e["kind"] == "dim"
                               and e["id"] == plural["id"] for e in lexicon):
                        lexicon.append(plural)
        self.lexicon: list[dict] = lexicon
        self.matcher = Matcher(self.lexicon)
        #: tokens a clause can name a measure with, for the "and <CFO>" style split
        self.measure_words: frozenset[str] = frozenset(
            tok for e in self.lexicon if e["kind"] in ("atom", "formula")
            for tok in e["surface"].split() if len(tok) >= 3)
        self.rules: dict[str, dict] = {}
        for e in self.lexicon:
            if e["kind"] == "rule":
                self.rules.setdefault(e["id"], e)

    @classmethod
    def load(cls, path: str | os.PathLike[str] | None = None) -> "Registry":
        p = Path(path or os.environ.get("REALITY_V4_REGISTRY") or REGISTRY_PATH)
        with open(p, encoding="utf-8") as fh:
            return cls(json.load(fh))

    def op_default_atom(self, op_id: str) -> str | None:
        """The atom an operator reads when the ask names the operation, not the measure."""
        row = self.operators.get(op_id) or {}
        atom = row.get("default_atom")
        return atom if atom in self.atoms else None

    def rule_default_atom(self, rule_id: str) -> str:
        atom = RULE_DEFAULT_ATOM.get(rule_id, "claim.claim")
        return atom if atom in self.atoms else "claim.claim"

    def atom_nid_reason(self, atom_id: str) -> str:
        """Why a declared atom cannot be answered yet: gap (build) or absent (nothing holds it)."""
        row = self.atoms.get(atom_id) or {}
        if row.get("coverage") in ("gap", "absent"):
            return row.get("coverage_note") or row.get("coverage") or ""
        return ""

    def dim_value(self, dim_id: str, value: str) -> str:
        """Registry spelling of one dim value (the lexicon carries NSE, questions carry nse)."""
        row = self.dims.get(dim_id) or {}
        values = row.get("values")
        if not isinstance(values, list):
            return value
        for v in values:
            if str(v).lower() == str(value).lower():
                return str(v)
        return value

    def default_value(self, dim_id: str) -> str:
        """The reading a dim takes when the question names none (§A.2 `default`)."""
        return str((self.dims.get(dim_id) or {}).get("default") or "").lower()


_REGISTRY: Registry | None = None


def load_registry(path: str | os.PathLike[str] | None = None) -> Registry:
    """Load the registry once per process (the JSON is ~450 KB; parsing it is the only cost)."""
    global _REGISTRY
    if path is not None:
        return Registry.load(path)
    if _REGISTRY is None:
        _REGISTRY = Registry.load()
    return _REGISTRY


def _dim_readings(reg: Registry, hits: list[dict]) -> dict[str, list[str]]:
    """``{dim: [value, ...]}`` from the lexicon's ``dim_id=value`` ids, first mention first."""
    out: dict[str, list[str]] = {}
    for h in hits:
        if h["kind"] != "dim" or "=" not in h["id"]:
            continue
        if h["surface"] in _HINGLISH_STOP:
            continue   # "date pe", "de do": a ratio dim that is really a Hinglish particle
        dim_id, value = h["id"].split("=", 1)
        values = out.setdefault(dim_id, [])
        value = reg.dim_value(dim_id, value)
        if value not in values:
            values.append(value)
    return out


def _readings(dims: dict[str, list[str]]) -> list[dict[str, str]]:
    """Cartesian product of multi-valued dims: one dim dict per reading of the clause."""
    out: list[dict[str, str]] = [{}]
    for dim_id, values in dims.items():
        out = [{**base, dim_id: v} for base in out for v in values]
    return out


def _shape_for(op: str, concept: str) -> str:
    if op in _SHAPE:
        return _SHAPE[op]
    if concept in ("claim.claim", "text.passage"):
        return "passage"
    if concept == "own.estimate":
        return "estimate"
    return "scalar"


def _entity(text: str, reg: Registry, scope_level: str | None) -> Entity:
    """The entity the question names, text only (the executor resolves it PIT, §C.2)."""
    m = _ISIN_RE.search(text)
    if m:
        return Entity(isin=m.group(0), level="stock", how="isin")
    m = _NSE_SYMBOL_RE.search(text)
    if m:
        return Entity(symbol=m.group(1), level="stock", how="symbol")
    m = _BSE_CODE_RE.search(text)
    if m:
        return Entity(symbol=m.group(1), level="stock", how="bse_code")
    for tok in _CAPS_RE.findall(text):
        if tok not in _NOT_A_SYMBOL and len(tok) >= 4:
            return Entity(symbol=tok, level="stock", how="caps token")
    m = _HEAD_STEM.match(text)
    if m:
        return Entity(symbol=m.group(1).strip(), level="stock", how="name before the colon")
    m = _THEME_STEM.search(text.lower())
    if m:
        return Entity(symbol=m.group(1).strip(), level=scope_level or "theme", how="theme stem")
    if scope_level:
        return Entity(level=scope_level, how="scope word")
    return Entity(level="market_wide", how="default market-wide (no entity named)")


def _lift_date(parts: list[Part], targets: list[Part]) -> list[Part] | None:
    """A date qualifier on a high/low: the operator that carries the date (§A example)."""
    lift_by_atom = {"price.high": "max_with_date", "price.low": "min_with_date"}
    out: list[Part] = []
    changed = False
    for base in targets:
        lift = lift_by_atom.get(base.atom or "")
        if not lift or base.operator in ("max_with_date", "min_with_date"):
            out.append(base)
            continue
        new = Part(atom=base.atom, formula=base.formula, dims=base.dims, window=base.window,
                   operator=lift, shape=_shape_for(lift, base.concept),
                   judgement=base.judgement, declared_default=base.declared_default,
                   clause=base.clause, nid_reason=base.nid_reason)
        for i, p in enumerate(parts):
            if p is base:
                parts[i] = new
                changed = True
        out.append(new)
    return out if changed else None


def _names_a_measure(clause: str) -> bool:
    """True when an unresolved clause names a measure-like noun: residue, not filler (§C.3)."""
    for tok in norm(clause).split():
        if len(tok) <= 2 or tok in _CONNECTIVE:
            continue
        if tok in _MEASURE_WORDS:
            return True
        if len(tok) > 4 and tok.startswith(("deliver", "margi", "capac", "order", "segme", "guidan")):
            return True
    return False


def _merge_dims(a: dict[str, list[str]], b: dict[str, list[str]]) -> dict[str, list[str]]:
    """Union of two dim readings, first mention first (a pending clause precedes its measure)."""
    out = {k: list(v) for k, v in a.items()}
    for dim_id, values in b.items():
        have = out.setdefault(dim_id, [])
        for v in values:
            if v not in have:
                have.append(v)
    return out


def _clean_dims(reg: Registry, dims: dict[str, list[str]],
                named: set[tuple[str, str]] = frozenset()) -> dict[str, list[str]]:  # type: ignore[assignment]
    """Drop ``scope`` (it is the entity set) and a default reading the question did not spell.

    "dono"/"both exchanges" are soft synonyms the generated lexicon maps to ``exchange=each``;
    the question never said *each*, so that is not a reading it named.  A requested default
    the question *does* spell out ("net NPA", "raw close", "promoter pledge") is kept.
    """
    out: dict[str, list[str]] = {}
    for dim_id, values in dims.items():
        if dim_id == "scope":
            continue
        default = reg.default_value(dim_id)
        if len(values) == 1 and str(values[0]).lower() == default:
            if (dim_id, str(values[0]).lower()) not in named:
                continue
        out[dim_id] = values
    return out


def _pick_operator(hits: list[dict]) -> str:
    """The operator of one reading: a reading-level trigger, else an ask-level one (§A.4).

    A meta-op whose surface is *inside* a matched atom surface ("share count" -> the word
    "count") belongs to the measure's name, not to the ask.
    """
    atom_surfaces = [h["surface"] for h in hits if h["kind"] == "atom"]
    reading = [h["id"] for h in hits
               if h["kind"] == "operator" and h["id"] not in _CROSS_PART_OPS]
    meta = [h["id"] for h in hits
            if h["kind"] == "operator" and h["id"] in _CROSS_PART_OPS
            and not any(h["surface"] in surface for surface in atom_surfaces)]
    if reading:
        return reading[0]
    return meta[0] if meta else "value_at"


def _apply_reading_dims(parts: list[Part], targets: list[Part], inherited: str,
                        dims: dict[str, list[str]], ops: list[str]) -> list[Part]:
    """Attach a dim-only clause's readings to the parts it inherits (§C.1).

    Per dim: a part that already carries a value keeps it and gains the *other* named values
    as their own parts; a part that carries none is replaced by one part per named value.  A
    part is never dropped, so no reading the question named can disappear.
    """
    group = [p for p in targets if p.concept == inherited]
    if not group:
        return targets
    op_override = next((o for o in ops if o in _READING_OPS), None)
    out = group
    for dim_id, values in dims.items():
        expanded: list[Part] = []
        for base in out:
            current = base.dim_values(dim_id)
            add = [v for v in values if v not in current] if current else list(values)
            if current:
                expanded.append(base)
            op = op_override or base.operator
            for value in add:
                expanded.append(Part(atom=base.atom, formula=base.formula,
                                     dims={**base.dims, dim_id: value}, window=base.window,
                                     operator=op, shape=_shape_for(op, base.concept),
                                     judgement=base.judgement,
                                     declared_default=base.declared_default,
                                     clause=base.clause, nid_reason=base.nid_reason))
        out = expanded
    if out is group:
        return targets
    parts[:] = [p for p in parts if not any(p is s for s in group)]
    parts.extend(out)
    return out


#: Order in which a named dim picks the measure it qualifies *when* it names one: a ratio or a
#: holder class is a stronger measure cue than a bare direction.
_OWNER_PRIORITY = ("ratio_kind", "npa_kind", "margin_kind", "holder_class", "flow_kind",
                   "topic", "page", "lookback", "est_atom", "doctype", "direction")


def _owner_of(dims: dict[str, list[str]]) -> str | None:
    for dim_id in _OWNER_PRIORITY:
        if dim_id in dims and dim_id in _DIM_OWNER:
            return _DIM_OWNER[dim_id]
    return None


#: A sentence boundary splits clauses: one ask per sentence ("mix has risen. Did DSO improve").
_SENTENCE_SPLIT = re.compile(r"(?<=[a-z0-9%])\.\s+(?=[A-Z0-9])")


def _measures(clause: str, hits: list[dict], reg: Registry,
              amount_ask: bool = False) -> list[tuple[str, dict, bool]]:
    """The measures a clause names (§C.2), one per part; ``(concept, extra_dims, default)``.

    A formula wins over its own input atoms: the ask is the derived measure and the atoms are
    its inputs (§A.3), so "EBITDA margin" is ``f.margin``, not ``fin.ebitda``.  A clause can
    name more than one measure ("a 52-week high on declining volume", "what did it say about
    margins"): each is emitted, because the ask is the union of what it names.  A bare dim
    that names a measure ("ROE", "how much does FII own", "page 10") resolves to the dim's
    owning atom (§A.2).  The ``default`` flag marks the §C.2 declared-default readings (topic,
    operator/rule default), scored separately from measures the text actually names.
    """
    atoms = [h for h in hits if h["kind"] == "atom"]
    if _DECLARATIVE_PRICE.search(clause) and not _ASK.search(clause):
        atoms = [a for a in atoms
                 if not (a["id"] == "price.close" and a["surface"] in _GENERIC_PRICE)]
    formulas = [h for h in hits if h["kind"] == "formula"]
    topics = [h for h in hits if h["kind"] == "claim_topic"]
    rules = [h for h in hits if h["kind"] == "rule"]
    scopes = [h for h in hits if h["kind"] == "entity_set"]
    raw_dims = _dim_readings(reg, hits)
    topic_extra = {"topic": topics[0]["id"]} if topics else {}
    # "gold-jewellery" is a theme scope; the word "gold" inside it is not a commodity ask
    atoms = [a for a in atoms
             if not any(a["surface"] != s["surface"] and a["surface"] in s["surface"].split()
                        for s in scopes)]

    if "page" in raw_dims or _NOTES_LOCATOR.search(clause):
        return [("text.passage", {}, False)]   # "page 41"/"Note 5" asks for the passage
    if formulas:
        fout: list[tuple[str, dict, bool]] = []
        seen: set[str] = set()
        for f in formulas:
            if f["id"] not in seen:
                fout.append((f["id"], {}, False))
                seen.add(f["id"])
        inputs = {atom for f in formulas for atom in (reg.formulas.get(f["id"]) or {}).get("over", [])}
        for h in atoms:
            if h["id"] in seen or h["id"] in inputs:
                continue
            fout.append((h["id"], {}, False))
            seen.add(h["id"])
        if any(row[0] != "macro.claim" for row in fout):
            fout = [row for row in fout if row[0] != "macro.claim"]
        # a corporate action named only as an event is a qualifier, not an amount ask
        if not (amount_ask or _AMOUNT_ASK.search(clause)):
            fout = [row for row in fout if row[0] != "corp.amount_per_share"]
        return fout

    if atoms:
        first = atoms[0]
        surface, atom_id = first["surface"], first["id"]
        if atom_id == "macro.claim" and _DOC_POINTER.search(clause) and _LOCATOR.search(clause):
            return [("text.passage", {}, False)]
        out: list[tuple[str, dict, bool]] = []
        if surface in _NARRATIVE_VERB:
            owner = _owner_of(raw_dims)
            if owner and owner != "text.passage":
                out.append((owner, {}, False))
            else:
                out.append(("claim.claim", topic_extra, False))
        elif (surface in reg.dim_value_words
              or surface.rstrip("s") in reg.dim_value_words) \
                and surface.replace(" ", "_") not in atom_id:
            owner = _owner_of(raw_dims)
            if (owner and owner != "text.passage"
                    and not (owner == "hold.pct" and _FLOW_VERB.search(clause)
                             and not _HOLD_VERB.search(clause))):
                out.append((owner, {}, False))
            elif owner == "text.passage" and topics:
                out.append(("claim.claim", topic_extra, True))
            else:
                out.append((atom_id, {}, False))
        else:
            out.append((atom_id, {}, False))
        seen = {c for c, _e, _d in out}
        for h in atoms[1:]:
            aid = h["id"]
            if aid in seen:
                continue
            out.append((aid, {}, False))
            seen.add(aid)
        # a narrative wrapper beside a named measure: "what did it say about margins"
        if "claim.claim" not in seen and any(a["id"] == "claim.claim" for a in atoms):
            out.append(("claim.claim", topic_extra, False))
            seen.add("claim.claim")
        # a company claim is the measure; "macro.claim" from the word "report" is not
        if "claim.claim" in seen or any(row[0] != "macro.claim" for row in out):
            out = [row for row in out if row[0] != "macro.claim"]
        # a corporate action named only as an event is a qualifier, not an amount ask
        if not (amount_ask or _AMOUNT_ASK.search(clause)):
            out = [row for row in out if row[0] != "corp.amount_per_share"]
        # "which Nifty 50 constituents ...": an index name is the scope, not the measure
        if any(h["kind"] == "operator" and h["id"] in _CROSS_PART_OPS for h in hits):
            out = [row for row in out if row[0] != "macro.index_close"]
        return out
    owner = _owner_of(raw_dims)
    if owner:
        # "which HFC's ROE improves": the dim names its own measure (§A.2)
        return [(owner, {}, False)]
    if topics:
        return [("claim.claim", topic_extra, True)]
    words = set(norm(clause).split())
    if words & _NARRATIVE_NOUN:
        return [("claim.claim", {}, False)]
    if rules:
        return [(reg.rule_default_atom(rules[0]["id"]), {}, True)]
    if _DOC_POINTER.search(clause) and _PAGE_RE.search(clause):
        return [("text.passage", {}, False)]
    if _QUESTION.search(clause):
        for h in hits:
            if h["kind"] == "operator":
                atom = reg.op_default_atom(h["id"])
                if atom:
                    return [(atom, {}, True)]
    return []


#: "split- and dividend-adjusted closes" is one basis reading, not a dividend ask.
_ADJUSTED_PHRASE = re.compile(
    r"\b(?:split|bonus|dividend)(?:[\s\-]+and[\s\-]+(?:split|bonus|dividend))?[\s\-]+adjusted\b",
    re.I)
#: "dividends aur splits adjust karke" / "adjusting for dividends" is the same basis reading.
_CORP_BASIS = re.compile(
    r"\b(?:dividends?|splits?|bonus)(?:\s+(?:and|aur|or|&)\s+(?:dividends?|splits?|bonus))*"
    r"\s+adjust\w*\b|\badjust\w*\s+(?:for\s+)?(?:the\s+)?(?:dividends?|splits?|bonus)\b",
    re.I)
#: A clause that already asks for a corporate action (payout, ex-date, buyback) keeps it.
_CORP_ASK = re.compile(
    r"\b(?:declared|announce\w*|ex[\s\-]?date|record date|payout|per share|buyback|rights issue|"
    r"bonus issue|split ratio|dps)\b", re.I)
#: A unit phrase ("in rupees", "Rs crore") is how a number is told, not a measure of its own.
_UNIT_PHRASE = re.compile(
    r"\b(?:in|into|to)\s+(?:rupees|rs\.?|crore|lakh|million|billion|usd|dollars?|inr)\b|"
    r"\b(?:rs\.?|usd|\$)\s*(?:crore|cr|lakh|million|billion|bn|mn)?\b", re.I)
#: Only a clause that asks something reads an operator's declared default atom; a declarative
#: background sentence ("milk procurement falls") is context, not a price ask.
_QUESTION = re.compile(
    r"\b(?:what|which|how|when|where|who|why|did|does|do|is|are|was|were|has|have|can|could|"
    r"would|should|kya|kitna|kitni|kitne|kaun|kaunsi|kaunse|kaunsa)\b", re.I)
#: The same for the generic "price/move" words: they name a share-price ask only in a question
#: or an imperative ("give the close"), never in a background clause.
_ASK = re.compile(
    _QUESTION.pattern + r"|\b(?:give|tell|state|name|list|show|trace|rank|compare|build|check|"
                       r"say|explain|report|batao|bata|likho)\b", re.I)
_GENERIC_PRICE = {"price", "prices", "move", "moves", "moved", "change", "changed", "changes",
                  "rise", "rises", "rose", "fall", "falls", "fell", "drop", "drops", "dropped"}
#: A background sentence whose subject is a price ("prices fall", "players hold price") is
#: context; a prepositional fragment ("then to the price") still names the reading.
_DECLARATIVE_PRICE = re.compile(
    r"\b(?:prices?|input cost|procurement price|dealer price|menu price|price agreements?)\b"
    r"[^.;?]{0,40}?\b(?:rise|rises|rose|fall|falls|fell|drop|drops|move|moves|moved|change|"
    r"changed|hold|holds|cut|cuts)\b|"
    r"\b(?:hold|holds|cut|cuts)\s+(?:the\s+)?price\b", re.I)
#: A corporate action named only as an event ("bonus had an ex-date") is a qualifier; the
#: amount atom is only read when the clause asks for the amount.
_AMOUNT_ASK = re.compile(
    r"\b(?:how\s+much|amount|per\s+share|dps|payout|declared|dividend\s+yield|dividend|"
    r"dilutive)\b", re.I)
#: A judgement-only ask ("what would prove the path is broken") has no declared rule yet, so it
#: is residue (§A.7: 17 of the measured-unmapped cases are undeclared judgement rules).
_JUDGEMENT = re.compile(
    r"\b(?:what\s+would\s+prove|what\s+evidence\s+would|how\s+(?:do|would)\s+you\s+prove|"
    r"prove\s+that|what\s+would\s+confirm|how\s+would\s+you\s+check)\b", re.I)
#: "food-delivery fees", "direct-client mix": a hyphenated compound whose half is a measure
#: word is a compound noun, not that measure — unless the whole hyphenated token *is* a
#: measure surface once de-hyphenated ("iron-ore", "delivery-spike", "book-to-bill").
_HYPHEN_COMPOUND = re.compile(r"\b[A-Za-z][A-Za-z0-9]*(?:-[A-Za-z][A-Za-z0-9]*)+\b")
#: "Note 5 of the results", "notes to accounts": a passage locator, not a claim word.
_NOTES_LOCATOR = re.compile(r"\bnotes?\s+(?:\d+|to\s+(?:the\s+)?accounts)\b", re.I)


#: Slash-written ratios ("P/B", "EV/EBITDA") normalise to their declared dim value.
_RATIO_SLASH = ((re.compile(r"\bp\s*/\s*b\b", re.I), " pb ratio "),
                (re.compile(r"\bp\s*/\s*e\b", re.I), " pe ratio "),
                (re.compile(r"\bd\s*/\s*e\b", re.I), " de ratio "),
                (re.compile(r"\bdebt\s*(?:/|-)\s*equity\b", re.I), " de ratio "),
                (re.compile(r"\bnet\s+debt\s*(?:/|to)\s*ebitda\b", re.I), " de ratio "),
                (re.compile(r"\bdebt\s*to\s*ebitda\b", re.I), " de ratio "),
                (re.compile(r"\bev\s*/\s*ebit(?:da)?\b", re.I), " ev ebitda "))


def _prepare(clause: str, reg: Registry) -> str:
    """Normalise the shapes that would otherwise be read as a measure they are not."""
    text = _ADJUSTED_PHRASE.sub("adjusted", clause)
    text = _UNIT_PHRASE.sub(" ", text)
    if re.search(r"\badjust\w*", text, re.I) and not _CORP_ASK.search(text):
        text = _CORP_BASIS.sub("adjusted", text)
    for rx, replacement in _RATIO_SLASH:
        text = rx.sub(replacement, text)

    def mask(m: re.Match) -> str:
        token = m.group(0).lower()
        if token in reg.matcher.by_surface:
            return m.group(0)
        joined = token.replace("-", " ")
        if joined in reg.matcher.by_surface:
            return joined          # "delivery-spike", "iron-ore", "book-to-bill": the measure
        parts = token.split("-")
        return " " if any(p in reg.measure_words for p in parts) else m.group(0)

    return _HYPHEN_COMPOUND.sub(mask, text)


def decompose(question: str, as_of: str = "", registry: Registry | None = None) -> Ask:
    """One question -> one :class:`Ask`.  The only inputs are the text and the run date."""
    reg = registry or load_registry()
    text = question or ""
    body = text
    if re.search(r"\badjust\w*", body, re.I) and not _CORP_ASK.search(body):
        body = _CORP_BASIS.sub("adjusted", body)   # before the split: "dividends aur splits adjust"
    amount_ask = bool(_AMOUNT_ASK.search(body))
    residues: list[str] = []
    parts: list[Part] = []
    inherited: str | None = None      # the measure a dim-only clause attaches to
    targets: list[Part] = []          # the parts the previous measure clause produced
    pending: dict[str, list[str]] = {}  # dims named before any measure ("raw and adjusted")
    scope_level: str | None = None
    topic_dims: dict[str, str] = {}   # dims the *first* part of the ask carried (topic etc.)
    judgement_clauses: list[str] = []

    for clause in split_clauses(body, reg.measure_words):
        if _EXCLUSION.match(clause):
            continue                    # "not total traded quantity": an exclusion
        clause = _prepare(clause, reg)
        if _JUDGEMENT.search(clause):
            judgement_clauses.append(clause)
            continue                    # no declared rule -> residue only if nothing else asks
        match_text = _mask_names(_COMPANY_SPAN.sub(" ", _TICKER_ANNOTATION.sub(" ", clause)), reg)
        hits = reg.matcher.hits(match_text)
        raw_dims = {k: v for k, v in _dim_readings(reg, hits).items() if k != "scope"}
        page = _PAGE_RE.search(clause)
        if page:
            raw_dims.setdefault("page", [page.group(1)])
        named = set()
        for h in hits:
            if h["kind"] == "dim" and "=" in h["id"]:
                dim_id, value = h["id"].split("=", 1)
                if value.lower() in h["surface"].split():
                    named.add((dim_id, value.lower()))
            elif h["kind"] in ("atom", "formula"):
                # a dim value inside the measure's own name ("net NPA", "P/B ratio") is a reading
                for word in h["surface"].split():
                    for dim_id, value in reg.dim_by_word.get(word, ()):
                        if _DIM_OWNER.get(dim_id) != h["id"]:
                            continue
                        values = raw_dims.setdefault(dim_id, [])
                        if value not in values:
                            values.append(value)
                        named.add((dim_id, value.lower()))
        rules = [h["id"] for h in hits if h["kind"] == "rule"]
        ops = [h["id"] for h in hits if h["kind"] == "operator"]
        scopes = [h for h in hits if h["kind"] == "entity_set"]
        has_period = any(h["kind"] == "period" for h in hits)
        if scopes and scope_level is None:
            scope_level = scopes[0]["id"] or "sector"

        # ---- the part's measures: one per measure the clause names (§C.1) -----------
        measures = _measures(clause, hits, reg, amount_ask)

        if not measures:
            # ---- no measure: a date qualifier, a dim reading, a meta-op, filler, residue --
            if _DATE_QUALIFIER.search(clause) and targets:
                lifted = _lift_date(parts, targets)
                if lifted is not None:
                    targets = lifted
                    continue
            owner = _owner_of(raw_dims)
            if owner and owner != inherited:
                # "which HFC's ROE improves": the dim names its own measure (§A.2)
                dims_here = _clean_dims(reg, raw_dims, named)
                fresh = []
                for reading in _readings(dims_here) or [{}]:
                    fresh.append(Part(atom=owner if owner in reg.atoms else None,
                                      formula=owner if owner in reg.formulas else None,
                                      dims=reading, window=0,
                                      operator=_pick_operator(hits),
                                      shape=_shape_for(_pick_operator(hits), owner),
                                      clause=clause, nid_reason=reg.atom_nid_reason(owner)))
                parts.extend(fresh)
                targets = fresh
                inherited = owner
                continue
            if not targets and raw_dims:
                pending = _merge_dims(pending, raw_dims)   # "raw [and] adjusted close"
                continue
            if inherited and targets and _clean_dims(reg, raw_dims, named):
                targets = _apply_reading_dims(parts, targets, inherited,
                                              _clean_dims(reg, raw_dims, named), ops)
                continue
            if inherited and has_period:
                continue               # "last five years": the window is ask-level
            if ops and all(o in _CROSS_PART_OPS for o in ops) and not raw_dims:
                continue               # "in what order": an ask-level qualifier
            if _names_a_measure(clause):
                residues.append(clause)
            continue                   # filler ("as of 31 July 2026", "batao")

        # ---- a measure clause: one part per reading of its multi-valued dims ---------
        dims = _clean_dims(reg, _merge_dims(pending, raw_dims), named)
        pending = {}
        op = _pick_operator(hits)
        if rules:
            op = "rule"
        targets = []
        inherited = measures[0][0]
        for concept, extra, is_default in measures:
            if concept not in reg.atoms and concept not in reg.formulas:
                concept = "claim.claim"
            extra = dict(extra)
            if concept == "claim.claim" and "topic" not in extra and topic_dims:
                extra.update(topic_dims)   # a bare "what did they say" inherits the topic
            readings = [{**extra, **r} for r in _readings(dims)] if dims else [dict(extra)]
            for reading in readings:
                part = Part(atom=concept if concept in reg.atoms else None,
                            formula=concept if concept in reg.formulas else None,
                            dims=reading, window=0, operator=op,
                            shape=_shape_for(op, concept), judgement=bool(rules),
                            declared_default=is_default,
                            clause=clause, nid_reason=reg.atom_nid_reason(concept))
                parts.append(part)
                targets.append(part)
            for key in ("topic", "est_atom"):
                if key in extra:
                    topic_dims = {key: extra[key]}

    # ---- dedupe identical readings (a re-stated class must not double a part) ---------
    seen: set[tuple] = set()
    unique: list[Part] = []
    for p in parts:
        key = (p.concept, tuple(sorted((k, str(v)) for k, v in p.dims.items())))
        if key in seen:
            continue
        seen.add(key)
        unique.append(p)
    parts = unique

    if not parts and judgement_clauses:
        residues.extend(judgement_clauses[:2])   # judgement-only ask: a typed unmapped


    # ---- window (§C.2): the existing parser, on the question text only ----------------
    d0, d1, basis = period_bounds({"question": text, "as_of": as_of or "", "period": ""})
    windows = [Window(from_=d0, to=d1, basis=basis)]

    # ---- status ---------------------------------------------------------------------
    nid = sorted({p.nid_reason for p in parts if p.nid_reason})
    if residues or not parts:
        status = "unmapped"
    elif nid:
        status = "not_in_data"
    else:
        status = "mapped"

    entity = _entity(text, reg, scope_level)
    residues = [_WS.sub(" ", r).strip() for r in residues if r.strip()]
    return Ask(parts=parts, entities=[entity], as_of=as_of or "", windows=windows,
               status=status, residues=residues, nid_reasons=nid, question=text)


def decompose_case(case: dict, registry: Registry | None = None) -> Ask:
    """Decompose one master-bank case by its **question text only** (§C.2).

    ``period``, ``template``, ``family``, ``chain`` and ``answer_kind`` are deliberately not
    read: the bank carries them and a real user question does not.
    """
    ask = decompose(case.get("question") or "", case.get("as_of") or "", registry)
    ask.mid = case.get("mid") or ""
    return ask


_CONNECTIVE = set("""
a an the and or of to in on at for from by with without after before during since until while
when where which who whom whose what why how is are was were be been being do does did doing
has have had having will would shall should can could may might must not no nor so than then
there their its it this that these those as if into onto over under about above below between
both each other more most less least very much many few some any all own same such only
also just but however because therefore thus hence per via toward towards across along within
question ask asks asked answer answers give gave get got make made take taken say said says
please tell show report provide list name state mention mentioned according latest now today
done does doing us we our you your they them he she his her one two three four five six seven
eight nine ten first second third next last new old big small large high low up down
value values number numbers percent percentage pp bps crore cr lakh million billion
nse bse isin company companies stock stocks share shares price prices day days year years
month months quarter quarters week weeks time times point points level levels part parts
""".split())
