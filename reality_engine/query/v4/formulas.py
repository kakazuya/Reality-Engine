"""The compute layer: named formulas over the extraction tables (§A.3).

A question becomes a lookup because the number it names is either stated or it is
the arithmetic of stated inputs.  This module executes the formulas declared in
the one registry (``tasks/arch_v4/concept_registry.json`` -> ``formulas``, built
by ``build_concept_registry.py``); it declares no second list of ids, labels,
units or inputs.  ``execute.py`` executes the same formula ids over the fact
view; this module executes them over the extracted statement tables, which is
where the measures the fact view does not carry yet (tax, cash flow, lender
metrics, unit volume) live.

The store contract (all tables read-only, one row per stated value)::

    balance_sheet_lines(isin, period_end, line_item, part, value, unit,
                        source, known_at, period_kind)
    cash_flow_lines   (isin, period_end, line_item, part, value, unit,
                       source, known_at, period_kind)
    lender_metrics    (isin, period_end, metric, part, value, unit,
                       source, known_at, period_kind)
    tax_reconciliation(isin, period_end, item, item_kind, value, unit,
                       source, known_at, period_kind)
    unit_volume       (isin, period_end, metric, part, value, unit,
                       source, known_at, period_kind)
    market_lines      (isin, as_of, metric, value, unit, source, known_at)
    nsdl_fortnight_cells(sector, period_start, period_end, value, unit,
                         source, known_at)

``source`` is the filing/table/page the value came from and ``known_at`` is the
day it became knowable.  ``lender_metrics`` is the reported scalar-metric series
(revenue, PAT, EBITDA, interest, order book, order intake, segment values); the
balance-sheet and cash-flow tables carry the named lines; ``tax_reconciliation``
carries profit before tax, tax expense, the statutory rate and the reconciling
items.  A formula uses only rows whose ``known_at`` is on or before the answer's
``as_of``; a row that exists but is first known later is refused
(``input_after_as_of``), never silently dropped into a missing input.

Every refusal is typed (:data:`REFUSAL_CODES`) and names the atoms it needed.
No formula imputes a zero, an average of one period, or a peer multiple: a
missing input is a refusal, not an estimate.

Nothing here writes to a store: every statement is a ``SELECT``.
"""
from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

#: The extraction tables this layer reads.  A binding naming any other table is
#: refused, so a hand-edited registry cannot turn into an arbitrary query.
EXTRACTION_TABLES = (
    "balance_sheet_lines",
    "cash_flow_lines",
    "lender_metrics",
    "tax_reconciliation",
    "unit_volume",
    "market_lines",
    "nsdl_fortnight_cells",
)

#: A typed refusal is one of these codes.  A code outside the set is a bug.
REFUSAL_CODES = frozenset({
    "input_missing",          # the store holds no row for a required atom
    "input_after_as_of",      # the only row is first known after as_of (look-ahead)
    "period_mismatch",        # inputs do not share one period (or the lag has no row)
    "insufficient_periods",   # a change/CAGR needs two dated observations
    "opening_balance_missing",  # an average balance needs the prior period
    "zero_denominator",
    "negative_base",          # growth/CAGR from a non-positive base
    "unit_mismatch",          # two inputs are not in one unit
    "missing_dim",            # the formula needs a selector the ask did not give
    "unsupported_selector",   # a selector value this executor does not implement
    "ambiguous_input",        # several rows fit and no dim picks one
    "data_mismatch",          # the arithmetic contradicts the data (a share > 100%)
    "stale_fundamentals",     # a valuation input is older than its limit
    "incomplete_month",       # NSDL cells do not cover the month, or cross its edge
    "store_missing",          # the extraction table is absent
    "unknown_formula",        # the id is not in the registry
    "no_executor",            # a registry formula row this module does not execute
})

#: A valuation multiple may use a fundamental that is at most this old (days);
#: the same limit family as ``execute.LATEST_LIMIT_DAYS``.
STALE_DAYS = 400

_MONEY = {
    "inr crore": 1.0, "inr cr": 1.0, "rs crore": 1.0, "crore": 1.0,
    "inr": 1e-7, "inr million": 0.1, "inr mn": 0.1, "inr lakh": 0.01,
}
_PERCENT = {"%", "percent", "per cent", "pct"}
_UNITS = {"unit", "units", "nos", "no", "numbers", "number", "pieces", "quantity"}


def _norm_unit(unit: Any) -> str:
    return " ".join(str(unit or "").strip().lower().replace("₹", "inr").split())


def _unit_kind(unit: Any) -> str:
    key = _norm_unit(unit)
    if key in _MONEY:
        return "money"
    if key in _PERCENT:
        return "percent"
    if key in _UNITS:
        return "units"
    return "other"


def _inr_crore(value: float, unit: Any, formula: str, atom: str) -> float:
    key = _norm_unit(unit)
    if key not in _MONEY:
        raise FormulaRefusal("unit_mismatch", formula,
                             f"{atom} is in {unit!r}, not a money unit", (atom,))
    return value * _MONEY[key]


def _day10(value: Any) -> str:
    """The YYYY-MM-DD prefix of a timestamp, or ``ValueError``."""
    text = str(value or "")[:10]
    datetime.strptime(text, "%Y-%m-%d")
    return text


def _shift_months(day: str, months: int) -> str:
    import calendar

    parsed = date.fromisoformat(day)
    month = parsed.month - 1 + months
    year = parsed.year + month // 12
    month = month % 12 + 1
    # Keep the day, clipped to the target month (a 31st has no 31 February).
    last = calendar.monthrange(year, month)[1]
    return date(year, month, min(parsed.day, last)).isoformat()


def _days_between(start: str, end: str) -> int:
    return (date.fromisoformat(end) - date.fromisoformat(start)).days


def _next_day(day: str) -> str:
    from datetime import timedelta

    return (date.fromisoformat(day) + timedelta(days=1)).isoformat()


@dataclass(frozen=True)
class Refusal:
    """A typed refusal: the formula could not be computed, and why."""

    code: str
    formula: str
    message: str
    atoms: tuple[str, ...] = ()
    as_of: str = ""
    isin: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"status": "refused", "code": self.code, "formula": self.formula,
                "message": self.message, "atoms": list(self.atoms),
                "as_of": self.as_of, "isin": self.isin}


class FormulaRefusal(Exception):
    """Raised inside the engine; :meth:`FormulaEngine.compute` returns the refusal."""

    def __init__(self, code: str, formula: str, message: str,
                 atoms: Iterable[str] = (), as_of: str = "", isin: str = ""):
        if code not in REFUSAL_CODES:
            raise ValueError(f"untyped refusal code {code!r}")
        self.refusal = Refusal(code, formula, message, tuple(atoms), as_of, isin)
        super().__init__(message)


@dataclass(frozen=True)
class Reading:
    """One stated input: the value, its unit, the period, and its provenance."""

    atom: str
    value: float
    unit: str
    period_end: str
    known_at: str
    source: str
    dims: Mapping[str, str] = field(default_factory=dict)
    period_start: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"atom": self.atom, "value": self.value, "unit": self.unit,
                "period_end": self.period_end, "known_at": self.known_at,
                "source": self.source, "dims": dict(self.dims),
                "period_start": self.period_start}


@dataclass(frozen=True)
class FormulaResult:
    """One computed measure, with every input that produced it."""

    formula: str
    label: str
    expr: str
    value: float
    unit: str
    period_rule: str
    period_end: str
    as_of: str
    isin: str
    inputs: tuple[Reading, ...]
    source_ref: str
    dims: Mapping[str, Any] = field(default_factory=dict)
    details: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"status": "computed", "formula": self.formula, "label": self.label,
                "expr": self.expr, "value": self.value, "unit": self.unit,
                "period_rule": self.period_rule, "period_end": self.period_end,
                "as_of": self.as_of, "isin": self.isin,
                "source_ref": self.source_ref, "dims": dict(self.dims),
                "details": dict(self.details),
                "inputs": [reading.to_dict() for reading in self.inputs]}


# ---------------------------------------------------------------------------
# registry
# ---------------------------------------------------------------------------
REGISTRY_PATH = Path(__file__).resolve().parents[3] / "tasks" / "arch_v4" / "concept_registry.json"


def load_registry(path: str | Path | None = None) -> dict[str, Any]:
    """The one concept registry (atoms, dims, formulas, operators)."""
    from .execute import load_registry as _load

    return _load(path)


def registry_formulas(registry: Mapping[str, Any] | None = None) -> dict[str, Mapping[str, Any]]:
    """``formula_id -> registry row`` from the shared registry, in file order."""
    reg = registry if registry is not None else load_registry()
    return {str(row.get("formula_id")): row for row in reg.get("formulas") or []}


def extraction_formulas(registry: Mapping[str, Any] | None = None) -> dict[str, Mapping[str, Any]]:
    """The formula rows the extraction executor owns (``executor == "extraction"``)."""
    return {fid: row for fid, row in registry_formulas(registry).items()
            if row.get("executor") == "extraction"}


# ---------------------------------------------------------------------------
# store + input book
# ---------------------------------------------------------------------------
class FormulaStore:
    """Read-only SELECTs over one extraction database."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.tables = {str(row[0]) for row in
                       conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}

    def rows(self, binding: Mapping[str, Any], isin: str,
             dims: Mapping[str, Any]) -> list[Reading]:
        table = str(binding.get("table") or "")
        key = str(binding.get("key") or "")
        atom = str(binding.get("atom") or "")
        if table not in EXTRACTION_TABLES:
            raise FormulaRefusal("store_missing", "", f"table {table!r} is not an extraction table",
                                 (atom,))
        if table not in self.tables:
            raise FormulaRefusal("store_missing", "",
                                 f"the extraction table {table} is absent", (atom,))
        dim_name = str(binding.get("dim") or "")
        dim_value = str(dims.get(dim_name) or "") if dim_name else ""
        if dim_name and not dim_value:
            raise FormulaRefusal("missing_dim", "",
                                 f"{atom} needs dim {dim_name!r}", (atom,))

        if table in ("balance_sheet_lines", "cash_flow_lines"):
            sql = (f"SELECT period_end, line_item, part, value, unit, source, known_at "
                   f"FROM {table} WHERE isin = ? AND line_item = ?")
            args: list[Any] = [isin, key]
            if dim_name == "segment":
                sql += " AND part = ?"
                args.append(dim_value)
            return self._read(sql, args, atom, table)

        if table in ("lender_metrics", "unit_volume"):
            sql = (f"SELECT period_end, metric, part, value, unit, source, known_at "
                   f"FROM {table} WHERE isin = ? AND metric = ?")
            args = [isin, key]
            if dim_name:
                sql += " AND part = ?"
                args.append(dim_value)
            return self._read(sql, args, atom, table)

        if table == "tax_reconciliation":
            if key == "*":
                kinds = tuple(binding.get("kinds") or ("deduction", "addback"))
                placeholders = ",".join("?" for _ in kinds)
                sql = (f"SELECT period_end, item, item_kind, value, unit, source, known_at "
                       f"FROM tax_reconciliation WHERE isin = ? AND item_kind IN ({placeholders})")
                return self._read(sql, [isin, *kinds], atom, table)
            sql = ("SELECT period_end, item, item_kind, value, unit, source, known_at "
                   "FROM tax_reconciliation WHERE isin = ? AND item = ?")
            return self._read(sql, [isin, key], atom, table)

        if table == "market_lines":
            sql = ("SELECT as_of, metric, value, unit, source, known_at "
                   "FROM market_lines WHERE isin = ? AND metric = ?")
            rows = self.conn.execute(sql, [isin, key]).fetchall()
            return [Reading(atom=atom, value=float(row[2]), unit=str(row[3]),
                            period_end=str(row[0])[:10], known_at=str(row[5])[:10],
                            source=str(row[4]), dims={"metric": str(row[1])})
                    for row in rows]

        if table == "nsdl_fortnight_cells":
            sql = ("SELECT period_start, period_end, value, unit, source, known_at "
                   "FROM nsdl_fortnight_cells WHERE sector = ?")
            rows = self.conn.execute(sql, [dim_value]).fetchall()
            return [Reading(atom=atom, value=float(row[2]), unit=str(row[3]),
                            period_start=str(row[0])[:10], period_end=str(row[1])[:10],
                            known_at=str(row[5])[:10], source=str(row[4]),
                            dims={"sector": dim_value})
                    for row in rows]

        raise FormulaRefusal("store_missing", "", f"no reader for {table!r}", (atom,))

    def _read(self, sql: str, args: Sequence[Any], atom: str, table: str) -> list[Reading]:
        rows = self.conn.execute(sql, list(args)).fetchall()
        out: list[Reading] = []
        for row in rows:
            if table == "tax_reconciliation":
                period_end, item, kind, value, unit, source, known_at = row
                dims = {"item": str(item), "item_kind": str(kind)}
            else:
                period_end, item, part, value, unit, source, known_at = row
                dims = {"part": str(part or ""), "key": str(item)}
            out.append(Reading(atom=atom, value=float(value), unit=str(unit),
                               period_end=str(period_end)[:10],
                               known_at=str(known_at)[:10], source=str(source), dims=dims))
        return out


class InputBook:
    """Every visible reading of a formula's atoms, and the period arithmetic."""

    def __init__(self, store: FormulaStore, spec: Mapping[str, Any], isin: str,
                 as_of: str, dims: Mapping[str, Any]):
        self.formula = str(spec.get("formula_id") or "")
        self.isin = isin
        self.as_of = as_of
        self.dims = dims
        self.bindings = {str(row.get("atom")): row for row in spec.get("inputs") or []}
        self._series: dict[str, list[Reading]] = {}
        for atom, binding in self.bindings.items():
            try:
                self._series[atom] = store.rows(binding, isin, dims)
            except FormulaRefusal as exc:
                exc.refusal = Refusal(exc.refusal.code, self.formula, exc.refusal.message,
                                      exc.refusal.atoms, as_of, isin)
                raise

    # -- raw access --------------------------------------------------------
    def all_rows(self, atom: str) -> list[Reading]:
        if atom not in self._series:
            raise FormulaRefusal("unknown_formula", self.formula,
                                 f"{atom} is not an input of {self.formula}", (atom,),
                                 self.as_of, self.isin)
        return self._series[atom]

    def visible(self, atom: str) -> list[Reading]:
        """Rows knowable at ``as_of`` for a period that had ended by ``as_of``."""
        rows = [row for row in self.all_rows(atom)
                if row.known_at <= self.as_of and row.period_end <= self.as_of]
        return sorted(rows, key=lambda row: (row.period_end, row.known_at))

    def hidden_after(self, atom: str) -> list[Reading]:
        return [row for row in self.all_rows(atom) if row.known_at > self.as_of]

    def at(self, atom: str, period: str) -> Reading:
        rows = [row for row in self.all_rows(atom) if row.period_end == period]
        visible = [row for row in rows
                   if row.known_at <= self.as_of and row.period_end <= self.as_of]
        if not visible:
            later = sorted({row.known_at for row in rows if row.known_at > self.as_of})
            if later:
                raise FormulaRefusal(
                    "input_after_as_of", self.formula,
                    f"{atom} for {period} is first known {later[0]}, after as_of "
                    f"{self.as_of}", (atom,), self.as_of, self.isin)
            raise FormulaRefusal(
                "input_missing", self.formula,
                f"{atom} has no row for {period}", (atom,), self.as_of, self.isin)
        # A restatement is the later known_at for the same period; use it.
        return sorted(visible, key=lambda row: (row.known_at, row.source))[-1]

    def try_at(self, atom: str, period: str) -> Reading | None:
        rows = [row for row in self.all_rows(atom) if row.period_end == period]
        visible = [row for row in rows
                   if row.known_at <= self.as_of and row.period_end <= self.as_of]
        return sorted(visible, key=lambda row: (row.known_at, row.source))[-1] \
            if visible else None

    def readings_at(self, atom: str, period: str) -> list[Reading]:
        """All rows of one period (named parts); absent is empty, look-ahead refuses."""
        rows = [row for row in self.all_rows(atom) if row.period_end == period]
        visible = [row for row in rows
                   if row.known_at <= self.as_of and row.period_end <= self.as_of]
        if not visible:
            later = sorted({row.known_at for row in rows if row.known_at > self.as_of})
            if later:
                raise FormulaRefusal(
                    "input_after_as_of", self.formula,
                    f"{atom} for {period} is first known {later[0]}, after as_of "
                    f"{self.as_of}", (atom,), self.as_of, self.isin)
        return sorted(visible, key=lambda row: (row.period_end, row.known_at))

    def latest(self, atom: str) -> Reading:
        rows = self.visible(atom)
        if not rows:
            if self.hidden_after(atom):
                first = sorted(row.known_at for row in self.hidden_after(atom))[0]
                raise FormulaRefusal(
                    "input_after_as_of", self.formula,
                    f"{atom} is first known {first}, after as_of {self.as_of}",
                    (atom,), self.as_of, self.isin)
            raise FormulaRefusal("input_missing", self.formula,
                                 f"{atom} has no row known by {self.as_of}",
                                 (atom,), self.as_of, self.isin)
        return rows[-1]

    def latest_common(self, atoms: Sequence[str], before: str | None = None) -> str:
        periods: dict[str, set[str]] = {}
        for atom in atoms:
            rows = [row for row in self.visible(atom)
                    if before is None or row.period_end < before]
            if not rows:
                if self.hidden_after(atom):
                    first = sorted(row.known_at for row in self.hidden_after(atom))[0]
                    raise FormulaRefusal(
                        "input_after_as_of", self.formula,
                        f"{atom} is first known {first}, after as_of {self.as_of}",
                        (atom,), self.as_of, self.isin)
                raise FormulaRefusal(
                    "input_missing", self.formula,
                    f"{atom} has no period{' before ' + before if before else ''} "
                    f"known by {self.as_of}", (atom,), self.as_of, self.isin)
            periods[atom] = {row.period_end for row in rows}
        common = set.intersection(*periods.values())
        if not common:
            latest = {atom: max(found) for atom, found in periods.items()}
            raise FormulaRefusal(
                "period_mismatch", self.formula,
                "no single period carries every input: "
                + ", ".join(f"{atom}={period}" for atom, period in sorted(latest.items())),
                tuple(atoms), self.as_of, self.isin)
        return max(common)

    def prior_period(self, atom: str, period: str) -> str | None:
        earlier = [row.period_end for row in self.visible(atom)
                   if row.period_end < period]
        return max(earlier) if earlier else None


# ---------------------------------------------------------------------------
# arithmetic helpers
# ---------------------------------------------------------------------------
def _pair_values(book: InputBook, first: Reading, second: Reading) -> tuple[float, float]:
    """Two values in one unit: money -> INR crore, otherwise the same unit."""
    if _unit_kind(first.unit) == "money" and _unit_kind(second.unit) == "money":
        return (_inr_crore(first.value, first.unit, book.formula, first.atom),
                _inr_crore(second.value, second.unit, book.formula, second.atom))
    if _norm_unit(first.unit) == _norm_unit(second.unit):
        return first.value, second.value
    raise FormulaRefusal(
        "unit_mismatch", book.formula,
        f"{first.atom} is in {first.unit!r} but {second.atom} is in {second.unit!r}",
        (first.atom, second.atom), book.as_of, book.isin)


def _ratio(book: InputBook, numerator: float, denominator: float, *,
           percent: bool = False, atoms: Sequence[str] = ()) -> float:
    if denominator == 0:
        raise FormulaRefusal("zero_denominator", book.formula,
                             f"denominator is zero: {', '.join(atoms)}",
                             tuple(atoms), book.as_of, book.isin)
    value = numerator / denominator
    return value * 100.0 if percent else value


def _same(book: InputBook, atoms: Sequence[str]) -> tuple[str, list[Reading]]:
    period = book.latest_common(atoms)
    return period, [book.at(atom, period) for atom in atoms]


def _money(book: InputBook, reading: Reading) -> float:
    return _inr_crore(reading.value, reading.unit, book.formula, reading.atom)


def _selector(dims: Mapping[str, Any], name: str, allowed: Sequence[str],
              book: InputBook, default: str | None = None) -> str:
    value = str(dims.get(name) or default or "").strip().lower()
    if not value:
        raise FormulaRefusal("missing_dim", book.formula,
                             f"formula needs dim {name!r}"
                             + (f" (one of {', '.join(allowed)})" if allowed else ""),
                             (), book.as_of, book.isin)
    if allowed and value not in allowed:
        raise FormulaRefusal("unsupported_selector", book.formula,
                             f"{name}={value!r} is not one of {', '.join(allowed)}",
                             (), book.as_of, book.isin)
    return value


# ---------------------------------------------------------------------------
# the formulas that read the extraction tables
# ---------------------------------------------------------------------------
def _f_effective_tax_rate(book, dims):
    period, (tax, profit) = _same(book, ["fin.tax_expense", "fin.pretax_profit"])
    tax_value, profit_value = _pair_values(book, tax, profit)
    value = _ratio(book, tax_value, profit_value, percent=True,
                   atoms=("fin.tax_expense", "fin.pretax_profit"))
    return value, "%", period, [tax, profit], {}, "same_period"


def _f_tax_gap(book, dims):
    period, (tax, profit, rate) = _same(
        book, ["fin.tax_expense", "fin.pretax_profit", "fin.statutory_rate"])
    if _unit_kind(rate.unit) != "percent":
        raise FormulaRefusal("unit_mismatch", book.formula,
                             f"fin.statutory_rate is in {rate.unit!r}, not percent",
                             ("fin.statutory_rate",), book.as_of, book.isin)
    tax_at_statutory = _money(book, profit) * rate.value / 100.0
    tax_expense = _money(book, tax)
    gap = tax_at_statutory - tax_expense

    # The named reconciling items bridge the gap.  Each deduction reduces the tax
    # by value * statutory rate; an addback increases it.  The residual is stated,
    # never spread over the items.
    items = book.readings_at("fin.tax_reconciliation_item", period)
    attributions: list[dict[str, Any]] = []
    attributed = 0.0
    for item in items:
        kind = str(item.dims.get("item_kind") or "")
        effect = _money(book, item) * rate.value / 100.0
        if kind == "addback":
            effect = -effect
        attributed += effect
        attributions.append({"item": item.dims.get("item"), "kind": kind,
                             "value": _money(book, item), "tax_effect": effect,
                             "unit": "INR crore", "source": item.source,
                             "known_at": item.known_at})
    details = {
        "tax_at_statutory": tax_at_statutory,
        "tax_expense": tax_expense,
        "statutory_rate": rate.value,
        "attributions": attributions,
        "attributed": attributed,
        "unattributed": gap - attributed,
        "unit": "INR crore",
    }
    used = [tax, profit, rate, *items]
    return gap, "INR crore", period, used, details, "same_period"


def _f_cfo_to_profit(book, dims):
    period, (cfo, profit) = _same(book, ["fin.cfo", "fin.pat"])
    a, b = _pair_values(book, cfo, profit)
    value = _ratio(book, a, b, atoms=("fin.cfo", "fin.pat"))
    return value, "x", period, [cfo, profit], {}, "same_period"


def _days(book, atom):
    period, (line, revenue) = _same(book, [atom, "fin.revenue"])
    line_value, revenue_value = _pair_values(book, line, revenue)
    value = _ratio(book, line_value, revenue_value, atoms=(atom, "fin.revenue")) * 365.0
    return value, "days", period, [line, revenue], {}, "same_period"


def _f_dso(book, dims):
    return _days(book, "fin.receivables")


def _f_dio(book, dims):
    return _days(book, "fin.inventory")


def _f_dpo(book, dims):
    return _days(book, "fin.payables")


def _f_working_capital_cycle(book, dims):
    atoms = ["fin.receivables", "fin.inventory", "fin.payables", "fin.revenue"]
    period, (receivables, inventory, payables, revenue) = _same(book, atoms)
    rec, inv = _money(book, receivables), _money(book, inventory)
    pay, rev = _money(book, payables), _money(book, revenue)
    value = _ratio(book, rec + inv - pay, rev, atoms=atoms) * 365.0
    return (value, "days", period, [receivables, inventory, payables, revenue], {},
            "same_period")


def _f_net_debt(book, dims):
    period, (debt, cash) = _same(book, ["fin.total_debt", "fin.cash"])
    value = _money(book, debt) - _money(book, cash)
    return value, "INR crore", period, [debt, cash], {}, "same_period"


def _f_net_debt_to_ebitda(book, dims):
    period, (debt, cash, ebitda) = _same(
        book, ["fin.total_debt", "fin.cash", "fin.ebitda"])
    net = _money(book, debt) - _money(book, cash)
    value = _ratio(book, net, _money(book, ebitda),
                   atoms=("fin.total_debt", "fin.cash", "fin.ebitda"))
    return (value, "x", period, [debt, cash, ebitda],
            {"net_debt": net, "ebitda": _money(book, ebitda)}, "same_period")


def _f_capex_to_sales(book, dims):
    period, (capex, revenue) = _same(book, ["fin.capex", "fin.revenue"])
    capex_value, revenue_value = _pair_values(book, capex, revenue)
    value = _ratio(book, capex_value, revenue_value, percent=True,
                   atoms=("fin.capex", "fin.revenue"))
    return value, "%", period, [capex, revenue], {}, "same_period"


def _f_asset_turnover(book, dims):
    period = book.latest_common(["fin.revenue", "fin.total_assets"])
    revenue = book.at("fin.revenue", period)
    current = book.at("fin.total_assets", period)
    prior_period = book.prior_period("fin.total_assets", period)
    if prior_period is None:
        raise FormulaRefusal(
            "opening_balance_missing", book.formula,
            f"average total assets needs the period before {period}; none is held",
            ("fin.total_assets",), book.as_of, book.isin)
    opening = book.at("fin.total_assets", prior_period)
    current_value, opening_value = _money(book, current), _money(book, opening)
    average = (current_value + opening_value) / 2.0
    value = _ratio(book, _money(book, revenue), average,
                   atoms=("fin.revenue", "fin.total_assets"))
    return (value, "x", period, [revenue, current, opening],
            {"average_total_assets": average, "opening_period": prior_period},
            "average_balance")


def _f_order_book_to_revenue(book, dims):
    period, (book_value, revenue) = _same(book, ["fin.order_book", "fin.revenue"])
    a, b = _pair_values(book, book_value, revenue)
    value = _ratio(book, a, b, atoms=("fin.order_book", "fin.revenue"))
    return value, "x", period, [book_value, revenue], {}, "same_period"


def _f_book_to_bill(book, dims):
    period, (orders, revenue) = _same(book, ["fin.order_intake", "fin.revenue"])
    a, b = _pair_values(book, orders, revenue)
    value = _ratio(book, a, b, atoms=("fin.order_intake", "fin.revenue"))
    return value, "x", period, [orders, revenue], {}, "same_period"


def _f_sotp_gap(book, dims):
    parts_latest = book.latest("fin.investments")
    period = parts_latest.period_end
    parts = book.readings_at("fin.investments", period)
    if not parts:
        raise FormulaRefusal(
            "input_missing", book.formula,
            f"no stated part values (fin.investments) at {period}",
            ("fin.investments",), book.as_of, book.isin)
    market_cap = book.latest("price.mcap")
    _stale(book, period)
    total = sum(_money(book, part) for part in parts)
    gap = total - _money(book, market_cap)
    details = {
        "parts_value": total,
        "market_cap": _money(book, market_cap),
        "valuation_date": market_cap.period_end,
        "gap_pct": (gap / _money(book, market_cap) * 100.0) if _money(book, market_cap) else None,
        "parts": [{"part": part.dims.get("part") or part.dims.get("key"),
                   "value": _money(book, part), "source": part.source,
                   "known_at": part.known_at} for part in parts],
        "unit": "INR crore",
    }
    return gap, "INR crore", period, [*parts, market_cap], details, "market_at_date"


def _f_revenue_per_unit(book, dims):
    period, (revenue, volume) = _same(book, ["fin.revenue", "fin.unit_volume"])
    volumes = book.readings_at("fin.unit_volume", period)
    if len(volumes) > 1:
        raise FormulaRefusal(
            "ambiguous_input", book.formula,
            f"{len(volumes)} unit-volume rows are held for {period} and no dim picks one",
            ("fin.unit_volume",), book.as_of, book.isin)
    if _unit_kind(volume.unit) in ("money", "percent"):
        raise FormulaRefusal("unit_mismatch", book.formula,
                             f"fin.unit_volume is in {volume.unit!r}, not a unit count",
                             ("fin.unit_volume",), book.as_of, book.isin)
    if volume.value <= 0:
        raise FormulaRefusal("zero_denominator", book.formula,
                             "unit volume is zero or negative",
                             ("fin.unit_volume",), book.as_of, book.isin)
    inr = _inr_crore(revenue.value, revenue.unit, book.formula, "fin.revenue") * 1e7
    value = inr / volume.value
    return (value, "INR/unit", period, [revenue, volume],
            {"revenue_inr": inr, "unit_volume": volume.value}, "same_period")


def _f_share_of(book, dims):
    _selector(dims, "segment", (), book)  # the binding filters on this dim
    period, (part, whole) = _same(book, ["fin.segment_value", "fin.revenue"])
    a, b = _pair_values(book, part, whole)
    value = _ratio(book, a, b, percent=True,
                   atoms=("fin.segment_value", "fin.revenue"))
    if value > 100.0 + 1e-9:
        raise FormulaRefusal(
            "data_mismatch", book.formula,
            f"the part ({a:,.2f}) exceeds the whole ({b:,.2f}); they are not one whole",
            ("fin.segment_value", "fin.revenue"), book.as_of, book.isin)
    return (value, "%", period, [part, whole],
            {"segment": str(dims.get("segment")), "part": a, "total": b}, "same_period")


def _f_change(book, dims):
    atom = str(dims.get("atom") or "fin.revenue")
    lag = _selector(dims, "lag", ("yoy", "qoq"), book, default="yoy")
    if atom not in book.bindings:
        raise FormulaRefusal("unsupported_selector", book.formula,
                             f"{atom} is not a series this formula reads; use one of "
                             f"{', '.join(book.bindings)}", (atom,), book.as_of, book.isin)
    series = book.visible(atom)
    if not series:
        book.latest(atom)  # raises the typed missing/look-ahead refusal
        raise FormulaRefusal("input_missing", book.formula, f"{atom} has no series",
                             (atom,), book.as_of, book.isin)
    current = series[-1]
    earlier = [row for row in series if row.period_end < current.period_end]
    if lag == "qoq":
        # The immediately preceding period, provided it is about a quarter back.
        # (Date arithmetic alone breaks on a 30th against a 31st quarter-end.)
        prior = earlier[-1] if earlier else None
        if prior is not None and not 45 <= _days_between(
                prior.period_end, current.period_end) <= 120:
            prior = None
        wanted = "the quarter before " + current.period_end
    else:
        target = _shift_months(current.period_end, -12)
        prior = (min(earlier, key=lambda row: abs(_days_between(
            target, row.period_end))) if earlier else None)
        if prior is not None and abs(_days_between(target, prior.period_end)) > 45:
            prior = None
        wanted = target
    if prior is None:
        raise FormulaRefusal(
            "period_mismatch", book.formula,
            f"{lag} needs {atom} at {wanted}; the store does not hold it",
            (atom,), book.as_of, book.isin)
    if _norm_unit(prior.unit) != _norm_unit(current.unit):
        raise FormulaRefusal("unit_mismatch", book.formula,
                             f"{atom} changes unit from {prior.unit!r} to {current.unit!r}",
                             (atom,), book.as_of, book.isin)
    if prior.value == 0:
        raise FormulaRefusal("zero_denominator", book.formula,
                             f"{atom} at {prior.period_end} is zero", (atom,),
                             book.as_of, book.isin)
    if prior.value < 0:
        raise FormulaRefusal("negative_base", book.formula,
                             f"{atom} at {prior.period_end} is negative", (atom,),
                             book.as_of, book.isin)
    value = (current.value - prior.value) / abs(prior.value) * 100.0
    details = {"atom": atom, "lag": lag, "prior_period": prior.period_end,
               "current": current.value, "prior": prior.value}
    return value, "%", current.period_end, [prior, current], details, "growth_pair"


def _f_cagr(book, dims):
    atom = str(dims.get("atom") or "fin.revenue")
    if atom not in book.bindings:
        raise FormulaRefusal("unsupported_selector", book.formula,
                             f"{atom} is not a series this formula reads; use one of "
                             f"{', '.join(book.bindings)}", (atom,), book.as_of, book.isin)
    series = book.visible(atom)
    if len(series) < 2:
        raise FormulaRefusal(
            "insufficient_periods", book.formula,
            f"CAGR needs two dated {atom} observations; {len(series)} is held by "
            f"{book.as_of}", (atom,), book.as_of, book.isin)
    first, last = series[0], series[-1]
    years = _days_between(first.period_end, last.period_end) / 365.25
    if years <= 0:
        raise FormulaRefusal("insufficient_periods", book.formula,
                             f"the two observations are {years:.3f} years apart",
                             (atom,), book.as_of, book.isin)
    if first.value <= 0 or last.value < 0:
        raise FormulaRefusal(
            "negative_base", book.formula,
            f"CAGR from {first.value} ({first.period_end}) to {last.value} "
            f"({last.period_end}) has no real base", (atom,), book.as_of, book.isin)
    value = ((last.value / first.value) ** (1.0 / years) - 1.0) * 100.0
    return (value, "%", last.period_end, [first, last],
            {"atom": atom, "start_period": first.period_end,
             "end_period": last.period_end, "years": years}, "cagr_pair")


def _stale(book: InputBook, period: str) -> None:
    age = _days_between(period, book.as_of)
    if age > STALE_DAYS:
        raise FormulaRefusal(
            "stale_fundamentals", book.formula,
            f"the latest fundamental period {period} is {age} days before as_of "
            f"{book.as_of} (limit {STALE_DAYS})", (), book.as_of, book.isin)


def _valuation(book: InputBook, atom: str) -> tuple[Reading, Reading]:
    """Market cap at the valuation date and the latest fundamental <= as_of."""
    market_cap = book.latest("price.mcap")
    fundamental = book.latest(atom)
    _stale(book, fundamental.period_end)
    return market_cap, fundamental


def _f_ratio(book, dims):
    kind = _selector(dims, "ratio_kind",
                     ("de", "pb", "pe", "roe", "roce", "icr"), book, default="de")
    if kind == "de":
        period, (debt, equity) = _same(book, ["fin.total_debt", "fin.book_equity"])
        value = _ratio(book, _money(book, debt), _money(book, equity),
                       atoms=("fin.total_debt", "fin.book_equity"))
        return value, "x", period, [debt, equity], {}, "same_period"
    if kind == "icr":
        period, (ebitda, interest) = _same(book, ["fin.ebitda", "fin.interest_expense"])
        value = _ratio(book, _money(book, ebitda), _money(book, interest),
                       atoms=("fin.ebitda", "fin.interest_expense"))
        return value, "x", period, [ebitda, interest], {}, "same_period"
    if kind == "roe":
        period, (profit, equity) = _same(book, ["fin.pat", "fin.book_equity"])
        prior_period = book.prior_period("fin.book_equity", period)
        if prior_period is None:
            raise FormulaRefusal(
                "opening_balance_missing", book.formula,
                f"average book equity needs the period before {period}; none is held",
                ("fin.book_equity",), book.as_of, book.isin)
        opening = book.at("fin.book_equity", prior_period)
        average = (_money(book, equity) + _money(book, opening)) / 2.0
        value = _ratio(book, _money(book, profit), average, percent=True,
                       atoms=("fin.pat", "fin.book_equity"))
        return (value, "%", period, [profit, equity, opening],
                {"average_book_equity": average, "opening_period": prior_period},
                "average_balance")
    if kind == "roce":
        atoms = ["fin.ebitda", "fin.book_equity", "fin.total_debt", "fin.cash"]
        period, (ebitda, equity, debt, cash) = _same(book, atoms)
        prior_period = book.prior_period("fin.book_equity", period)
        if prior_period is None:
            raise FormulaRefusal(
                "opening_balance_missing", book.formula,
                f"average capital employed needs the period before {period}; none is held",
                ("fin.book_equity",), book.as_of, book.isin)
        opening = [book.try_at(atom, prior_period) for atom in
                   ("fin.book_equity", "fin.total_debt", "fin.cash")]
        if any(row is None for row in opening):
            raise FormulaRefusal(
                "opening_balance_missing", book.formula,
                f"capital employed at {prior_period} is not held for every input",
                ("fin.book_equity", "fin.total_debt", "fin.cash"),
                book.as_of, book.isin)
        opening = [row for row in opening if row is not None]
        capital = _money(book, equity) + _money(book, debt) - _money(book, cash)
        opening_capital = (_money(book, opening[0]) + _money(book, opening[1])
                           - _money(book, opening[2]))
        average = (capital + opening_capital) / 2.0
        value = _ratio(book, _money(book, ebitda), average, percent=True, atoms=atoms)
        return (value, "%", period, [ebitda, equity, debt, cash, *opening],
                {"average_capital_employed": average,
                 "opening_period": prior_period}, "average_balance")
    if kind == "pb":
        market_cap, equity = _valuation(book, "fin.book_equity")
        value = _ratio(book, _money(book, market_cap), _money(book, equity),
                       atoms=("price.mcap", "fin.book_equity"))
        return (value, "x", equity.period_end, [market_cap, equity],
                {"valuation_date": market_cap.period_end,
                 "market_cap": _money(book, market_cap)}, "market_at_date")
    # pe
    market_cap, profit = _valuation(book, "fin.pat")
    value = _ratio(book, _money(book, market_cap), _money(book, profit),
                   atoms=("price.mcap", "fin.pat"))
    return (value, "x", profit.period_end, [market_cap, profit],
            {"valuation_date": market_cap.period_end,
             "market_cap": _money(book, market_cap)}, "market_at_date")


def _f_nsdl_fortnight_net_flow(book, dims):
    _selector(dims, "sector", (), book)  # the binding filters on this dim
    rows = book.visible("macro.fii_sector_net")
    if not rows:
        book.latest("macro.fii_sector_net")
        raise FormulaRefusal("input_missing", book.formula,
                             "no NSDL fortnight cells", ("macro.fii_sector_net",),
                             book.as_of, book.isin)
    period = max(row.period_end for row in rows)
    cells = [row for row in rows if row.period_end == period]
    value = sum(_money(book, cell) for cell in cells)
    details = {"sector": str(dims.get("sector")),
               "cells": [{"period_start": cell.period_start,
                          "period_end": cell.period_end,
                          "value": _money(book, cell), "source": cell.source}
                         for cell in cells],
               "unit": "INR crore"}
    return value, "INR crore", period, cells, details, "fortnight_cell"


def _f_nsdl_month_net_flow(book, dims):
    _selector(dims, "sector", (), book)
    month = str(dims.get("month") or "").strip()
    if not month:
        raise FormulaRefusal("missing_dim", book.formula,
                             "formula needs dim 'month' (YYYY-MM)", (),
                             book.as_of, book.isin)
    try:
        first = date.fromisoformat(month + "-01")
        next_month = date.fromisoformat(_shift_months(first.isoformat(), 1))
    except ValueError:
        raise FormulaRefusal("missing_dim", book.formula,
                             f"month={month!r} is not YYYY-MM", (), book.as_of,
                             book.isin) from None
    month_start, month_end = first.isoformat(), next_month.isoformat()
    rows = [row for row in book.visible("macro.fii_sector_net")
            if row.period_end < month_end and row.period_start < month_end
            and row.period_end >= month_start]
    if not rows:
        if book.hidden_after("macro.fii_sector_net"):
            first_known = sorted(row.known_at for row in
                                 book.hidden_after("macro.fii_sector_net"))[0]
            raise FormulaRefusal(
                "input_after_as_of", book.formula,
                f"macro.fii_sector_net is first known {first_known}, after as_of "
                f"{book.as_of}", ("macro.fii_sector_net",), book.as_of, book.isin)
        raise FormulaRefusal("input_missing", book.formula,
                             f"no NSDL fortnight cell covers {month}",
                             ("macro.fii_sector_net",), book.as_of, book.isin)
    for cell in rows:
        if cell.period_start < month_start or cell.period_end >= month_end:
            raise FormulaRefusal(
                "incomplete_month", book.formula,
                f"cell {cell.period_start}..{cell.period_end} crosses the edge of "
                f"{month} and cannot be apportioned without daily cells",
                ("macro.fii_sector_net",), book.as_of, book.isin)
    spans = sorted((cell.period_start, cell.period_end) for cell in rows)
    covered_to = spans[0][0]
    for start, end in spans:
        if start > _next_day(covered_to):
            raise FormulaRefusal(
                "incomplete_month", book.formula,
                f"NSDL cells leave {covered_to}..{start} uncovered in {month}",
                ("macro.fii_sector_net",), book.as_of, book.isin)
        covered_to = max(covered_to, end)
    if spans[0][0] > month_start or covered_to < _last_day(month_end):
        raise FormulaRefusal(
            "incomplete_month", book.formula,
            f"NSDL cells do not cover all of {month}",
            ("macro.fii_sector_net",), book.as_of, book.isin)
    value = sum(_money(book, cell) for cell in rows)
    details = {"sector": str(dims.get("sector")), "month": month,
               "cells": [{"period_start": cell.period_start,
                          "period_end": cell.period_end,
                          "value": _money(book, cell), "source": cell.source}
                         for cell in rows],
               "unit": "INR crore"}
    return value, "INR crore", _last_day(month_end), rows, details, "month_cells"


def _last_day(day: str) -> str:
    """The day before ``day`` (which is the first day of the next month)."""
    from datetime import timedelta

    return (date.fromisoformat(day) - timedelta(days=1)).isoformat()


_COMPUTE = {
    "f.ratio": _f_ratio,
    "f.dso": _f_dso,
    "f.dio": _f_dio,
    "f.dpo": _f_dpo,
    "f.working_capital_cycle": _f_working_capital_cycle,
    "f.share_of": _f_share_of,
    "f.cagr": _f_cagr,
    "f.change": _f_change,
    "f.effective_tax_rate": _f_effective_tax_rate,
    "f.tax_gap": _f_tax_gap,
    "f.cfo_to_profit": _f_cfo_to_profit,
    "f.net_debt": _f_net_debt,
    "f.net_debt_to_ebitda": _f_net_debt_to_ebitda,
    "f.capex_to_sales": _f_capex_to_sales,
    "f.asset_turnover": _f_asset_turnover,
    "f.order_book_to_revenue": _f_order_book_to_revenue,
    "f.book_to_bill": _f_book_to_bill,
    "f.sotp_gap": _f_sotp_gap,
    "f.revenue_per_unit": _f_revenue_per_unit,
    "f.nsdl_fortnight_net_flow": _f_nsdl_fortnight_net_flow,
    "f.nsdl_month_net_flow": _f_nsdl_month_net_flow,
}

#: The formulas whose result is a percentage, for callers that read units alone.
PERCENT_FORMULAS = frozenset({
    "f.effective_tax_rate", "f.capex_to_sales", "f.change", "f.cagr",
})


class FormulaEngine:
    """One executor over one extraction database, at one ``as_of`` per answer."""

    def __init__(self, conn: sqlite3.Connection, registry: Mapping[str, Any] | None = None):
        self.registry = dict(registry) if registry is not None else load_registry()
        self.store = FormulaStore(conn)
        self.specs = registry_formulas(self.registry)

    def spec(self, formula_id: str) -> Mapping[str, Any]:
        row = self.specs.get(formula_id)
        if row is None:
            raise FormulaRefusal("unknown_formula", formula_id,
                                 f"{formula_id} is not in {REGISTRY_PATH.name}", ())
        return row

    def compute(self, formula_id: str, isin: str, as_of: str | date,
                dims: Mapping[str, Any] | None = None) -> FormulaResult | Refusal:
        """The computed measure, or a typed refusal.

        A missing or look-ahead input never raises: it becomes a :class:`Refusal`.
        A malformed ``as_of``/``isin`` is a caller bug and raises ``ValueError``.
        """
        try:
            return self.evaluate(formula_id, isin, as_of, dims)
        except FormulaRefusal as exc:
            refusal = exc.refusal
            return Refusal(refusal.code, refusal.formula, refusal.message,
                           refusal.atoms, refusal.as_of, isin)

    def evaluate(self, formula_id: str, isin: str, as_of: str | date,
                 dims: Mapping[str, Any] | None = None) -> FormulaResult:
        as_of_text = _day10(as_of.isoformat() if isinstance(as_of, date) else as_of)
        spec = self.spec(formula_id)
        fn = _COMPUTE.get(formula_id)
        if fn is None:
            raise FormulaRefusal("no_executor", formula_id,
                                 f"{formula_id} has no extraction executor", (),
                                 as_of_text, isin)
        if not spec.get("inputs"):
            raise FormulaRefusal("no_executor", formula_id,
                                 f"registry formula {formula_id} declares no inputs", (),
                                 as_of_text, isin)
        chosen = dict(dims or {})
        book = InputBook(self.store, spec, isin, as_of_text, chosen)
        try:
            value, unit, period_end, used, details, rule = fn(book, chosen)
        except FormulaRefusal as exc:
            refusal = exc.refusal
            if refusal.as_of and refusal.isin:
                raise
            # Arithmetic helpers raise without the ask; attach it once, here.
            raise FormulaRefusal(refusal.code, formula_id, refusal.message,
                                 refusal.atoms, as_of_text, isin) from None
        if not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            raise FormulaRefusal("data_mismatch", formula_id,
                                 f"{formula_id} produced a non-finite value",
                                 tuple(reading.atom for reading in used), as_of_text, isin)
        selector = ""
        if formula_id == "f.ratio":
            selector = f"({chosen.get('ratio_kind') or 'de'})"
        elif formula_id in ("f.change", "f.cagr"):
            selector = f"({chosen.get('atom') or 'fin.revenue'})"
        atoms = list(dict.fromkeys(reading.atom for reading in used))
        known = max((reading.known_at for reading in used), default="")
        return FormulaResult(
            formula=formula_id,
            label=str(spec.get("label") or ""),
            expr=str(spec.get("expr") or ""),
            value=float(value),
            unit=unit,
            period_rule=rule,
            period_end=period_end,
            as_of=as_of_text,
            isin=isin,
            inputs=tuple(used),
            source_ref=f"derived:{formula_id}{selector}:{'+'.join(atoms)}",
            dims=chosen,
            details=dict(details, known_at=known),
        )


def compute_formula(conn: sqlite3.Connection, formula_id: str, isin: str,
                    as_of: str | date, dims: Mapping[str, Any] | None = None,
                    registry: Mapping[str, Any] | None = None) -> FormulaResult | Refusal:
    """One call for a caller that does not want to hold an engine."""
    return FormulaEngine(conn, registry).compute(formula_id, isin, as_of, dims)


__all__ = [
    "EXTRACTION_TABLES",
    "PERCENT_FORMULAS",
    "REFUSAL_CODES",
    "STALE_DAYS",
    "FormulaEngine",
    "FormulaRefusal",
    "FormulaResult",
    "FormulaStore",
    "InputBook",
    "Reading",
    "Refusal",
    "compute_formula",
    "extraction_formulas",
    "load_registry",
    "registry_formulas",
]
