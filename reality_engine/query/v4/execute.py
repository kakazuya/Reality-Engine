"""One executor over the v4 fact view (§D.1): exactly one Result per part, always.

The part is whatever the decomposer (§H.3) emitted.  This module does not import
the decomposer: :func:`as_part` is the thin adapter and accepts a mapping or an
object with the Ask part's fields (``atom`` | ``formula``, ``dims``, ``window``,
``operator``, ``shape``, ``judgement``).  The fact view is the caller's: pass any
connection that answers the §B.1 columns
``entity_id, atom_id, dims, period_start, period_end, value, unit, known_at,
source_ref`` for ``SELECT ... FROM fact``.  Nothing here opens a database.

Answer types are the contract (§D.4): ``measured``, ``estimate``, ``proxy``,
``not_in_data``.  ``measured``/``estimate`` count as ``real_answered``; a
``proxy`` counts only with both a ``search_log`` ref and ``approved_by``; a typed
NOT IN DATA never counts.  Operators are the closed 26-row set of §A.4, and a
part that cannot be answered returns a typed NID with what was tried, before any
proxy is used (§H.5 order: search, then proxy, then NID).

ponytail: dims are matched in Python after a bounded per-part fact fetch (one
atom, one entity/window).  Push the dim predicates into SQL when a part's row
count stops being bounded by the window — the SQL shape is already narrow.
"""
from __future__ import annotations

import json
import statistics
from bisect import bisect_left, bisect_right
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

ANSWER_TYPES = ("measured", "estimate", "proxy", "not_in_data")
REAL = ("measured", "estimate")
COUNTED = REAL + ("proxy",)
MAX_HOPS = 5
REGISTRY_PATH = Path(__file__).resolve().parents[3] / "tasks" / "arch_v4" / "concept_registry.json"


# ---------------------------------------------------------------------------
# the thin part adapter (WP3 owns the real part; this is the only coupling)
# ---------------------------------------------------------------------------
@dataclass
class Part:
    atom: str | None = None
    formula: str | None = None
    dims: dict[str, Any] = field(default_factory=dict)
    window: Any = None
    operator: str = "value_at"
    shape: str = "scalar"
    judgement: bool = False
    index: int = 0
    rule: str | None = None
    entity: str | None = None
    entities: list[str] = field(default_factory=list)

    @property
    def measure(self) -> str:
        return str(self.atom or self.formula or "")


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, Mapping):
        return obj.get(key, default)
    return getattr(obj, key, default)


def as_part(obj: Any, index: int | None = None) -> Part:
    """Normalise a decomposer part (dict or object) into :class:`Part`."""
    dims = dict(_get(obj, "dims") or {})
    raw_entities = _get(obj, "entities") or []
    entities = [str(item.get("isin") or item.get("symbol") or item)
                if isinstance(item, Mapping) else str(item)
                for item in raw_entities]
    atom = _get(obj, "atom")
    formula = _get(obj, "formula")
    if atom is None and formula is None:
        # "measure" is the name WP3 may use for either one.
        measure = _get(obj, "measure") or ""
        atom = measure if measure and not str(measure).startswith("f.") else None
        formula = measure if str(measure).startswith("f.") else formula
    rule = _get(obj, "rule") or dims.get("rule")
    operator = str(_get(obj, "operator") or ("rule" if _get(obj, "judgement") else "value_at"))
    shape = str(_get(obj, "shape") or "scalar")
    ent = _get(obj, "entity")
    if ent is None:
        ent = dims.get("entity_id") or dims.get("isin")
    return Part(atom=atom, formula=formula, dims=dims,
                window=_get(obj, "window"), operator=operator, shape=shape,
                judgement=bool(_get(obj, "judgement")), rule=rule,
                index=int(index if index is not None else (_get(obj, "index", 0) or 0)),
                entity=ent, entities=entities)


# ---------------------------------------------------------------------------
# the result contract
# ---------------------------------------------------------------------------
@dataclass
class Result:
    part_index: int
    atom: str | None = None
    formula: str | None = None
    dims: dict[str, Any] = field(default_factory=dict)
    window: dict[str, Any] = field(default_factory=dict)
    operator: str = "value_at"
    shape: str = "scalar"
    answer_type: str = "not_in_data"
    value: Any = None
    values: list[dict[str, Any]] = field(default_factory=list)
    unit: str | None = None
    period: str | None = None
    isin: str | None = None
    entities: list[dict[str, Any]] = field(default_factory=list)
    source_ref: str | None = None
    known_at: str | None = None
    # estimate / proxy
    method: str | None = None
    inputs: Any = None
    confidence: float | None = None
    # rule / verdict
    rule_used: str | None = None
    verdict: str | None = None
    numbers: dict[str, Any] = field(default_factory=dict)
    # not_in_data
    nid_reason: str | None = None
    tried: list[dict[str, Any]] = field(default_factory=list)
    checked: list[dict[str, Any]] = field(default_factory=list)
    to_close: str | None = None
    # proxy
    proxy: Any = None
    assumption: str | None = None
    sources: list[str] = field(default_factory=list)
    search_log: str | None = None
    approved_by: str | None = None

    @property
    def measure(self) -> str:
        return str(self.atom or self.formula or "")

    def to_dict(self) -> dict[str, Any]:
        return {key: _plain(value) for key, value in self.__dict__.items()}

    @classmethod
    def from_obj(cls, obj: Any) -> "Result":
        if isinstance(obj, cls):
            return obj
        if not isinstance(obj, Mapping):
            obj = getattr(obj, "__dict__", {}) or {}
        known = set(cls.__dataclass_fields__)
        data = {key: value for key, value in dict(obj).items() if key in known}
        data.setdefault("part_index", int((obj or {}).get("index", 0) or 0))
        return cls(**data)


def as_result(obj: Any) -> Result:
    return Result.from_obj(obj)


def approved_proxy(result: Any) -> bool:
    """§D.4: a proxy counts only with a search_log ref and an approval."""
    r = as_result(result)
    return bool(r.answer_type == "proxy" and r.search_log and r.approved_by)


def counts_as_answered(result: Any) -> bool:
    r = as_result(result)
    if r.answer_type in REAL:
        return True
    return approved_proxy(r)


def answer_counts(results: Iterable[Any]) -> dict[str, Any]:
    """The gate's two counters (§D.4), plus the debt an unapproved proxy is."""
    rows = [as_result(r) for r in results]
    real = sum(1 for r in rows if r.answer_type in REAL)
    proxy = sum(1 for r in rows if approved_proxy(r))
    not_answered = len(rows) - real - proxy
    return {"parts": len(rows), "real_answered": real, "proxy_answered": proxy,
            "not_answered": not_answered,
            "unapproved_proxy": sum(1 for r in rows if r.answer_type == "proxy")
            - proxy,
            "case_answered": bool(rows) and real + proxy == len(rows)}


# ---------------------------------------------------------------------------
# registry
# ---------------------------------------------------------------------------
def load_registry(path: str | Path | None = None) -> dict[str, Any]:
    """The concept registry (atoms/formulas) as a plain dict; {} if absent."""
    target = Path(path) if path else REGISTRY_PATH
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _registry(registry: Any) -> dict[str, Any]:
    if isinstance(registry, Mapping):
        return dict(registry)
    return load_registry()


def _atom_row(registry: Mapping[str, Any], atom: str | None) -> dict[str, Any]:
    for row in registry.get("atoms") or []:
        if row.get("atom_id") == atom:
            return row
    return {}


def _formula_row(registry: Mapping[str, Any], formula: str | None) -> dict[str, Any]:
    for row in registry.get("formulas") or []:
        if row.get("formula_id") == formula:
            return row
    return {}


# ---------------------------------------------------------------------------
# small database helpers (no connection is opened here)
# ---------------------------------------------------------------------------
def db_rows(conn: Any, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]] | None:
    """Rows as dicts, or None when the table/view does not exist."""
    try:
        cur = conn.execute(sql, tuple(params))
        columns = [column[0] for column in (cur.description or [])]
        return [dict(zip(columns, row)) for row in cur.fetchall()]
    except Exception:  # noqa: BLE001 - a missing relation is data about the store
        return None


def _has(conn: Any, name: str) -> bool:
    return db_rows(conn, f"SELECT 1 AS ok FROM {name} LIMIT 0") is not None


def _day(value: Any) -> str | None:
    text = str(value or "")[:10]
    return text or None


def parse_dims(value: Any) -> dict[str, str]:
    if isinstance(value, Mapping):
        return {str(k): str(v) for k, v in value.items()}
    out: dict[str, str] = {}
    for chunk in str(value or "").split(";"):
        if "=" in chunk:
            key, item = chunk.split("=", 1)
            out[key.strip()] = item.strip()
    return out


def _num(value: Any) -> float | None:
    try:
        if isinstance(value, Decimal):
            return float(value)
        return float(value)
    except (TypeError, ValueError):
        return None


def _plain(value: Any) -> Any:
    """JSON-safe copy of a result field (DuckDB hands back Decimal/datetime)."""
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_plain(item) for item in value]
    return str(value)


SPECIAL_DIMS = {"each", "sum"}
#: dims that select or parameterise a computation rather than qualify a fact row.
SELECTOR_DIMS = {"entity_id", "isin", "est_atom", "rule", "rule_id", "margin_kind",
                 "ratio_kind", "limit", "n", "agg", "threshold", "direction", "distinct",
                 "max_hops", "event_date", "date", "driver", "atoms", "part_atom",
                 "output_atom", "input_atom", "benchmark", "benchmark_isin", "atom_b",
                 "other_atom", "set_kind", "set_value", "cross", "lag", "lookback",
                 "doctype", "event_kind", "page", "total_return"}
#: dims a row may simply not carry (a daily price row has no period_kind): a named value
#: then filters only the rows that do carry it, and never rejects a whole atom.
SOFT_DIMS = {"period_kind"}
#: an explicit reading the atom cannot serve: the row is not exchange-keyed (price.close is
#: the NSE-first panel), so answering "on BSE" would pass one exchange off as the other.
#: Every other dim the atom's rows do not carry is ignored, never rejected (MB0032#L).
UNSERVED_DIM_VALUES = {("exchange", "BSE")}
CONSOLIDATION = ("consolidated", "standalone")
#: fact-view dims with no §A.2 declaration of their own: the reported figure is the
#: reading, the ``ytd_difference`` row is a derived cumulative difference of the same
#: quantity (results XBRL reports the YTD figure and the build differences it back).
FACT_VIEW_DEFAULTS = {"derived": "reported"}
#: a window this short reads the quarterly reading of a period_kind-carrying atom.
SHORT_WINDOW_DAYS = 120
#: §D.2 latest readings: a part whose window is open on the left reads the most recent
#: period KNOWN by as_of.  These limits are the most the newest held row may lag the asked
#: date before it stops being offered as "latest", in days per atom class, measured from
#: the held filing lags in the v4 pilot store (2026-10-31): fin p50 42 / p90 66 / p99 485,
#: hold 18 / 98 / 333, daily price 0.  Two filing cycles plus grace: a missed quarter is a
#: typed NID, a years-old row is never "latest".
LATEST_LIMIT_DAYS = {"hold": 200, "fin": 400, "price": 10, "flows": 100,
                     "macro": 400, "text": 400}
DEFAULT_LATEST_LIMIT_DAYS = 400
#: the window bases that ask the latest value known by ``as_of`` (window open on the left)
LATEST_BASES = ("as_of", "none", "latest", "latest quarter")
#: bases that NAME the period a row must end in: no fallback to an older period
PERIOD_END_BASES = ("quarter end", "fiscal year end", "year end")


def latest_limit(measure: str, registry: Mapping[str, Any]) -> tuple[int, str]:
    """(days, class) a "latest" reading of this measure may lag as_of (formula -> input)."""
    atom = str(measure or "")
    if atom.startswith("f."):
        over = _formula_row(registry, atom).get("over") or []
        atom = str(over[0]) if over else atom
    klass = atom.split(".", 1)[0]
    return LATEST_LIMIT_DAYS.get(klass, DEFAULT_LATEST_LIMIT_DAYS), klass


def _age_days(period: str | None, asked: str | None) -> int | None:
    """Days from ``period`` to ``asked``; None when either is not a date."""
    if not period or not asked:
        return None
    from datetime import date
    try:
        return (date.fromisoformat(asked) - date.fromisoformat(period)).days
    except ValueError:
        return None


def row_dims(row: Mapping[str, Any]) -> dict[str, str]:
    """The row's dims, with the fact view's consolidation exposed under its real dim name.

    ``fact_view.sql`` writes ``basis=consolidated;period_kind=quarter`` for fundamentals;
    §A.2's dims are ``consolidation`` and ``basis`` (raw|adjusted).  Adapting at the
    reader keeps both vocabularies usable without a rebuild of the read-only store.
    """
    got = parse_dims(row.get("dims"))
    basis = got.pop("basis", None)
    if basis in CONSOLIDATION:
        got.setdefault("consolidation", basis)
    elif basis:
        got["basis"] = basis
    return got


def _window_grain(lo: str | None, hi: str | None, basis: str = "",
                  grain: str = "") -> str:
    """The period_kind a window implies: a latest reading takes the atom's own grain."""
    if basis in LATEST_BASES and lo is None:
        # "latest revenue" is the atom's own reading (quarterly for fin.revenue, FY for
        # fin.book_equity), never "whatever period end happened to sort last".
        return grain if grain in ("quarter", "fy", "half") else "fy"
    if lo and hi:
        from datetime import date
        try:
            if (date.fromisoformat(hi) - date.fromisoformat(lo)).days <= SHORT_WINDOW_DAYS:
                return "quarter"
        except ValueError:
            pass
    return "fy"


def _apply_defaults(rows: Sequence[Mapping[str, Any]], want: Mapping[str, Any],
                    registry: Mapping[str, Any], lo: str | None,
                    hi: str | None, basis: str = "", grain: str = "") -> list[Mapping[str, Any]]:
    """§A.2: a dim the question did not name takes the registry's declared default reading.

    Only a dim the rows actually carry is applied, and only when more than one reading is
    present: an atom that does not use the dim is left alone.
    """
    defaults = {str(row.get("dim_id")): row.get("default")
                for row in registry.get("dims") or [] if row.get("default") is not None}
    defaults = {**FACT_VIEW_DEFAULTS, **defaults}
    defaults["period_kind"] = _window_grain(lo, hi, basis, grain)
    out = list(rows)
    for dim, default in defaults.items():
        if dim in want or default in (None, ""):
            continue
        values = {str(row_dims(row).get(dim, "")).lower() for row in out}
        values.discard("")
        if len(values) > 1 and str(default).lower() in values:
            out = [row for row in out
                   if str(row_dims(row).get(dim, "")).lower() == str(default).lower()]
    return out


def _unnamed_split(rows: Sequence[Mapping[str, Any]],
                   want: Mapping[str, Any]) -> list[str]:
    """Dims the rows split on that the ask never named: one value would be a guess."""
    keys: set[str] = set()
    for row in rows:
        keys.update(row_dims(row).keys())
    out = []
    for key in sorted(keys - set(want) - SELECTOR_DIMS - SPECIAL_DIMS):
        values = {str(row_dims(row).get(key)) for row in rows}
        values.discard("None")
        if len(values) > 1:
            out.append(f"{key} ({len(values)} readings: "
                       f"{', '.join(sorted(values)[:4])})")
    return out


def _dim_match(row: Mapping[str, Any], want: Mapping[str, Any],
               carried: set[str] | None = None) -> bool:
    """True when the row satisfies every named dim the atom's rows actually carry."""
    got = row_dims(row)
    for key, value in want.items():
        if key in SELECTOR_DIMS:
            continue
        if str(value).lower() in SPECIAL_DIMS:
            continue
        if carried is not None and key not in carried:
            continue
        carried_value = str(got.get(key, "")).lower()
        if not carried_value and key in SOFT_DIMS:
            continue
        if carried_value != str(value).lower():
            return False
    return True


def carried_dims(rows: Sequence[Mapping[str, Any]]) -> set[str]:
    """The dims the fetched rows actually carry (a daily close carries none)."""
    keys: set[str] = set()
    for row in rows:
        keys.update(row_dims(row))
    return keys


def _unserved(want: Mapping[str, Any], carried: set[str]) -> tuple[str, Any] | None:
    """The first named dim reading the atom's rows cannot serve and must not fake."""
    for key, value in want.items():
        if key in SELECTOR_DIMS or key in carried:
            continue
        if (key, str(value).upper()) in UNSERVED_DIM_VALUES:
            return key, value
    return None


def _apply_soft(rows: Sequence[Mapping[str, Any]],
                want: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """A named soft dim filters the rows that carry it; rows without it stay (§A.2)."""
    out = list(rows)
    for dim in SOFT_DIMS & set(want):
        wanted = str(want[dim]).lower()
        out = [row for row in out
               if not row_dims(row).get(dim)
               or str(row_dims(row).get(dim)).lower() == wanted]
    return out


def _window_bounds(window: Any, windows: Sequence[Any] | None) -> tuple[str | None, str | None]:
    if window is None:
        return None, None
    if isinstance(window, int) and windows and 0 <= window < len(windows):
        window = windows[window]
    if isinstance(window, Mapping):
        return _day(window.get("from") or window.get("start")), _day(
            window.get("to") or window.get("end"))
    text = _day(window)
    return text, text


def _window_dict(lo: str | None, hi: str | None) -> dict[str, Any]:
    return {"from": lo, "to": hi}


FACT_COLUMNS = ("SELECT entity_id, {atom}, dims, period_start, period_end, value, unit, "
                "known_at, source_ref FROM fact")


def fact_atom_column(conn: Any) -> str:
    """The measure column of the fact view: ``atom_id`` per §B.1, ``atom`` in WP2a's build.

    The design names ``atom_id``; ``fact_view.sql`` wrote ``atom``.  Probe the schema
    per fetch (a prepared statement on a WITHOUT ROWID table costs nothing) so both
    shapes work and neither is silently renamed.
    """
    try:
        conn.execute("SELECT atom_id FROM fact LIMIT 0").fetchall()
        return "atom_id"
    except Exception:  # noqa: BLE001 - the column's absence is data about the store
        return "atom"


def fetch_fact(conn: Any, atom: str, as_of: str, lo: str | None = None,
               hi: str | None = None, entity: str | None = None,
               entities: Sequence[str] | None = None,
               only_values: bool = True) -> list[dict[str, Any]] | None:
    """PIT-filtered fact rows for one atom; None when the view is absent.

    ``known_at`` is cut at ``as_of`` in SQL, never in Python (§B.1: a value is usable
    only from its ``known_at``).  The fetch is bounded when no single entity pins it:

    ponytail: a cross-entity fetch with no window reads the latest 5,000 rows in
    index order (atom, period_end) — the whole ``macro.oi`` atom is 6.9M rows.  Add a
    window-derived bound (or a covering index on (atom, period_end, entity_id)) when a
    screen legitimately needs the full history of a market-wide atom.
    """
    column = fact_atom_column(conn)
    sql = (FACT_COLUMNS.format(atom=column)
           + f" WHERE {column} = ? AND substr(known_at, 1, 10) <= ?")
    params: list[Any] = [atom, as_of]
    if only_values:
        sql += " AND value IS NOT NULL"
    if lo:
        sql += " AND substr(COALESCE(period_end, period_start), 1, 10) >= ?"
        params.append(lo)
    if hi:
        sql += " AND substr(COALESCE(period_end, period_start), 1, 10) <= ?"
        params.append(hi)
    if entity:
        sql += " AND entity_id = ?"
        params.append(entity)
    if entities:
        placeholders = ",".join("?" for _ in entities)
        sql += f" AND entity_id IN ({placeholders})"
        params.extend(entities)
    descending = not entity and not (lo or hi)
    if descending:
        sql += " ORDER BY period_end DESC, known_at DESC LIMIT 5000"
    elif not entity:
        sql += " ORDER BY COALESCE(period_end, period_start), known_at LIMIT 20000"
    else:
        sql += " ORDER BY COALESCE(period_end, period_start), known_at"
    rows = db_rows(conn, sql, params)
    return list(reversed(rows)) if (rows and descending) else rows


def _one_latest(rows: Sequence[Mapping[str, Any]] | None) -> Mapping[str, Any] | None:
    if not rows:
        return None
    return rows[-1]


def _series(rows: Sequence[Mapping[str, Any]], dims: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The part's values, one per period; ``sum`` collapses the sum-named dims."""
    values: list[dict[str, Any]] = []
    if any(str(v).lower() == "sum" for v in dims.values()):
        buckets: dict[tuple[Any, Any], dict[str, Any]] = {}
        for row in rows:
            period = _day(row.get("period_end") or row.get("period_start"))
            key = (period, row.get("unit"))
            slot = buckets.get(key)
            if slot is None:
                slot = {"period": period, "value": 0.0, "unit": row.get("unit"),
                        "dims": dict(dims), "known_at": row.get("known_at"),
                        "source_ref": row.get("source_ref"), "entity_id": row.get("entity_id")}
                buckets[key] = slot
            number = _num(row.get("value"))
            if number is not None:
                slot["value"] += number
        values = list(buckets.values())
    else:
        for row in rows:
            values.append({"period": _day(row.get("period_end") or row.get("period_start")),
                           "value": _num(row.get("value")), "unit": row.get("unit"),
                           "dims": row_dims(row),
                           "known_at": _day(row.get("known_at")),
                           "source_ref": row.get("source_ref"),
                           "entity_id": row.get("entity_id")})
    return values


def _latest(values: Sequence[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    return values[-1] if values else None


def _span_days(values: Sequence[Mapping[str, Any]]) -> int | None:
    first, last = _day(values[0].get("period")), _day(values[-1].get("period"))
    if not first or not last:
        return None
    from datetime import date
    try:
        return (date.fromisoformat(last) - date.fromisoformat(first)).days
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# NID
# ---------------------------------------------------------------------------
def _tried(store: str, detail: str, rows: int | None, as_of: str) -> dict[str, Any]:
    return {"store": store, "query": detail, "rows_after_pit": rows, "at": as_of}


def _nid(part: Part, window: dict[str, Any], why: str,
         tried: Sequence[Mapping[str, Any]], to_close: str,
         checked: Sequence[Mapping[str, Any]] = ()) -> Result:
    return Result(part_index=part.index, atom=part.atom, formula=part.formula,
                  dims=part.dims, window=window, operator=part.operator,
                  shape=part.shape, answer_type="not_in_data", nid_reason=why,
                  tried=[dict(item) for item in tried],
                  checked=[dict(item) for item in checked], to_close=to_close)


def _proxy(part: Part, window: dict[str, Any], proxy: Mapping[str, Any],
           tried: Sequence[Mapping[str, Any]], why: str | None) -> Result:
    result = Result(part_index=part.index, atom=part.atom, formula=part.formula,
                    dims=part.dims, window=window, operator=part.operator,
                    shape=part.shape, answer_type="proxy",
                    value=proxy.get("value"), unit=proxy.get("unit"),
                    period=proxy.get("period"), isin=proxy.get("isin") or part.entity,
                    proxy=proxy.get("value") if proxy.get("value") is not None else proxy,
                    assumption=proxy.get("assumption"),
                    confidence=proxy.get("confidence"),
                    sources=[str(item) for item in proxy.get("sources") or []],
                    search_log=proxy.get("search_log"),
                    approved_by=proxy.get("approved_by"),
                    tried=[dict(item) for item in tried],
                    nid_reason=why, to_close=proxy.get("to_close"))
    return result


# ---------------------------------------------------------------------------
# special engines (§D.2)
# ---------------------------------------------------------------------------
def _execute_estimate(conn: Any, part: Part, as_of: str, lo: str | None,
                      hi: str | None, entity: str | None,
                      window: dict[str, Any]) -> Result:
    est_atom = part.dims.get("est_atom")
    if not est_atom:
        return _nid(part, window, "own.estimate part names no est_atom dim",
                    [_tried("own_estimate", "est_atom dim missing", 0, as_of)],
                    "the decomposer must emit dims.est_atom for an estimate part")
    if conn is None:
        return _nid(part, window, "no database connection was supplied",
                    [_tried("own_estimate", "not queried", None, as_of)],
                    "pass the pilot store connection")
    rows = db_rows(
        conn,
        "SELECT isin, est_atom, period_end, value, unit, method, inputs_json, n_obs, "
        "confidence, known_at, as_of FROM own_estimate "
        "WHERE est_atom = ? AND substr(known_at, 1, 10) <= ?"
        + (" AND isin = ?" if entity else "")
        + " ORDER BY period_end DESC, known_at DESC LIMIT 40",
        [est_atom, as_of] + ([entity] if entity else []))
    if rows is None:
        return _nid(part, window, "the own_estimate table is not built in this store",
                    [_tried("own_estimate", "table absent", None, as_of)],
                    "WP2b build_own_estimate.py (§H.2/§H.7)")
    if lo or hi:
        rows = [row for row in rows
                if (not lo or (_day(row.get("period_end")) or "") >= lo)
                and (not hi or (_day(row.get("period_end")) or "") <= hi)]
    row = rows[0] if rows else None
    if row is None:
        return _nid(part, window,
                    f"no own estimate for {entity or 'the asked entity'}/{est_atom}"
                    f"{' in the asked window' if (lo or hi) else ''} at {as_of}",
                    [_tried("own_estimate", f"est_atom={est_atom}, isin={entity}", 0, as_of)],
                    "WP2b build_own_estimate.py (§H.7)")
    inputs = row.get("inputs_json")
    try:
        inputs = json.loads(inputs) if isinstance(inputs, str) else inputs
    except ValueError:
        pass
    return Result(part_index=part.index, atom=part.atom, formula=part.formula,
                  dims=part.dims, window=window, operator=part.operator,
                  shape="estimate", answer_type="estimate", value=_num(row.get("value")),
                  unit=row.get("unit"), period=_day(row.get("period_end")),
                  isin=row.get("isin") or entity, source_ref="own_estimate",
                  known_at=_day(row.get("known_at")), method=row.get("method"),
                  inputs=inputs, confidence=row.get("confidence"),
                  numbers={"n_obs": row.get("n_obs"), "as_of": _day(row.get("as_of")),
                           "est_atom": est_atom})


def _width_days(lo: str, hi: str) -> int:
    from datetime import date
    try:
        return (date.fromisoformat(hi) - date.fromisoformat(lo)).days
    except ValueError:
        return 10 ** 6


def _topic_stem(topic: str) -> str:
    """The claim store's topic vocabulary is singular ("product", not "products")."""
    text = str(topic).strip().lower()
    for suffix, stem in (("ies", "y"), ("es", ""), ("s", "")):
        if text.endswith(suffix) and len(text) > len(suffix) + 2:
            return text[: -len(suffix)] + stem
    return text


def _execute_claim(conn: Any, part: Part, as_of: str, entity: str | None,
                   window: dict[str, Any]) -> Result:
    if conn is None:
        return _nid(part, window, "no database connection was supplied",
                    [_tried("claim", "not queried", None, as_of)],
                    "pass the pilot store connection")
    topic = part.dims.get("topic")
    doctype = part.dims.get("doctype")
    page = part.dims.get("page")
    base = ("SELECT quote, topic, direction, magnitude, unit, horizon, certainty, "
            "doctype, page_no, doc_id, known_at FROM claim "
            "WHERE substr(known_at, 1, 10) <= ?")
    params: list[Any] = [as_of]
    if entity:
        base += " AND entity_id = ?"
        params.append(entity)
    if doctype and str(doctype).lower() not in ("any", "all"):
        base += " AND lower(doctype) = ?"
        params.append(str(doctype).lower())
    if page is not None:
        base += " AND page_no = ?"
        params.append(int(page))
    # The claim's known_at is its document's filing date.  A named date or a month-wide
    # window ("the 22 May 2026 deck", "the Aug-2026 concall") therefore bounds it; a
    # period range does not (a Q1 document may be filed in July).
    lo, hi = window.get("from"), window.get("to")
    if lo and hi and (lo == hi or _width_days(lo, hi) <= 62):
        base += " AND substr(known_at, 1, 10) >= ?"
        params.append(lo)
        base += " AND substr(known_at, 1, 10) <= ?"
        params.append(hi)
    # An exact topic first; then its singular stem ("products" -> "product") because the
    # question's wording and the claim build's vocabulary need not agree on plurality.
    clauses: list[tuple[str, list[Any]]] = [("", [])]
    if topic and str(topic).lower() not in ("all", "any"):
        clauses = [(" AND topic = ?", [str(topic)])]
        stem = _topic_stem(str(topic))
        if stem != str(topic).lower():
            clauses.append((" AND lower(topic) LIKE ?", [stem + "%"]))
    else:
        # A claim part with no topic or page is the decomposer's fallback for a measure
        # it could not express: the latest claims are not an answer to a named ask.
        topic = None
        if page is None and not doctype:
            return _nid(part, window,
                        "the claim part names no topic, page or document type; the latest "
                        "claims are not an answer to a named measure",
                        [_tried("claim", f"entity={entity}, topic=None, doctype={doctype}",
                                0, as_of)],
                        "the decomposer must emit dims.topic (or page) for a narrative ask "
                        "(§A.1 claim.claim)")
    rows: list[dict[str, Any]] | None = []
    for clause, extra in clauses:
        rows = db_rows(conn, base + clause + " ORDER BY known_at DESC LIMIT 20",
                       params + extra)
        if rows is None:
            return _nid(part, window, "the claim table is not built in this store",
                        [_tried("claim", "table absent", None, as_of),
                         _tried("chunks_v3", "not read by this executor", None, as_of)],
                        "WP2b build_claim.py (§B.3) for the claim table and "
                        "chunks_v3.chunk for raw passages")
        if rows:
            break
    if not rows:
        return _nid(part, window,
                    f"no claim for {entity or 'the asked entity'}"
                    f"{f' on topic {topic}' if topic else ''} at {as_of}",
                    [_tried("claim", f"entity={entity}, topic={topic}, doctype={doctype}", 0,
                            as_of)],
                    "WP2b build_claim.py (§B.3); then search the document text")
    return Result(part_index=part.index, atom=part.atom, formula=part.formula,
                  dims=part.dims, window=window, operator=part.operator,
                  shape="passage", answer_type="measured",
                  values=[dict(row, known_at=_day(row.get("known_at"))) for row in rows],
                  unit=None, period=_day(rows[0].get("known_at")), isin=entity,
                  source_ref="claim", known_at=_day(rows[0].get("known_at")))


def _execute_walk(conn: Any, part: Part, as_of: str, entity: str | None,
                  window: dict[str, Any], entities: Sequence[str]) -> Result:
    start = part.dims.get("driver") or part.dims.get("from_entity") or entity or (
        entities[0] if entities else None)
    if not start:
        return _nid(part, window, "walk part names no starting entity",
                    [_tried("edge", "start entity missing", 0, as_of)],
                    "the decomposer must name the driver entity for a walk")
    if conn is None:
        return _nid(part, window, "no database connection was supplied",
                    [_tried("edge", "not queried", None, as_of)],
                    "pass the pilot store connection")
    hops: list[dict[str, Any]] = []
    frontier = [str(start)]
    seen = {str(start)}
    stop: str | None = None
    max_hops = min(int(part.dims.get("max_hops") or MAX_HOPS), MAX_HOPS)
    for hop in range(1, max_hops + 1):
        sql = ("SELECT driver, target, strength, lag, mechanism, label, known_at, "
               "evidence_ref FROM edge WHERE driver = ? AND substr(known_at,1,10) <= ? "
               "ORDER BY strength DESC LIMIT 20")
        if not hops:
            rows = db_rows(conn, sql, [frontier[0], as_of])
            if rows is None:
                return _nid(part, window, "the edge table is not built in this store",
                            [_tried("edge", "table absent", None, as_of)],
                            "the discovery build writes edge (§B.5 step 6)")
        else:
            rows = []
            for node in frontier:
                found = db_rows(conn, sql, [node, as_of]) or []
                rows.extend(found)
            rows.sort(key=lambda row: -(row.get("strength") or 0))
        rows = [row for row in rows if str(row.get("target")) not in seen]
        if not rows:
            stop = f"hop {hop}: no typed edge from {', '.join(frontier[:3])}"
            break
        next_frontier = []
        for row in rows:
            seen.add(str(row.get("target")))
            next_frontier.append(str(row.get("target")))
            hops.append({"hop": hop, "node": row.get("driver"), "target": row.get("target"),
                         "mechanism": row.get("mechanism"), "strength": row.get("strength"),
                         "lag": row.get("lag"), "label": row.get("label"),
                         "known_at": _day(row.get("known_at")),
                         "evidence_ref": row.get("evidence_ref")})
        frontier = next_frontier
    if not hops:
        return _nid(part, window, stop or f"no typed edge starts at {start}",
                    [_tried("edge", f"driver={start}, max_hops={max_hops}", 0, as_of)],
                    "the discovery build writes edge (§B.5 step 6)")
    return Result(part_index=part.index, atom=part.atom, formula=part.formula,
                  dims=part.dims, window=window, operator=part.operator, shape="path",
                  answer_type="measured", values=hops, isin=str(start),
                  source_ref="edge", known_at=max((h.get("known_at") or "") for h in hops),
                  verdict=stop or f"{len(hops)} typed hop(s) from {start}",
                  numbers={"hops": len(hops), "max_hops": max_hops})


# ---------------------------------------------------------------------------
# the closed operator set (§A.4)
# ---------------------------------------------------------------------------
def _scalar(part: Part, window: dict[str, Any], values: Sequence[Mapping[str, Any]],
            answer_type: str = "measured") -> Result:
    latest = _latest(values)
    if latest is None:
        raise _Empty()
    return Result(part_index=part.index, atom=part.atom, formula=part.formula,
                  dims=part.dims, window=window, operator=part.operator,
                  shape=part.shape, answer_type=answer_type,
                  value=latest.get("value"), values=[dict(row) for row in values],
                  unit=latest.get("unit"), period=_day(latest.get("period")),
                  isin=latest.get("entity_id"), source_ref=latest.get("source_ref"),
                  known_at=_day(latest.get("known_at")))


class _Empty(Exception):
    """No row for the part after PIT and dims."""


class _Missing(Exception):
    """The part or the store cannot run this operator: a typed NID, not a crash."""

    def __init__(self, why: str, to_close: str):
        super().__init__(why)
        self.why = why
        self.to_close = to_close


def _op_value_at(part, values, ctx):
    return _scalar(part, ctx["window"], values)


def _op_first_visible(part, values, ctx):
    first = values[0] if values else None
    if first is None:
        raise _Empty()
    return Result(part_index=part.index, atom=part.atom, formula=part.formula,
                  dims=part.dims, window=ctx["window"], operator=part.operator,
                  shape=part.shape, answer_type="measured", value=first.get("value"),
                  values=[dict(row) for row in values], unit=first.get("unit"),
                  period=_day(first.get("period")), isin=first.get("entity_id"),
                  source_ref=first.get("source_ref"),
                  known_at=_day(first.get("known_at")))


def _op_last_visible(part, values, ctx):
    return _scalar(part, ctx["window"], values)


def _op_series(part, values, ctx):
    if not values:
        raise _Empty()
    return Result(part_index=part.index, atom=part.atom, formula=part.formula,
                  dims=part.dims, window=ctx["window"], operator=part.operator,
                  shape="series", answer_type="measured",
                  values=[dict(row) for row in values], unit=values[0].get("unit"),
                  period=_day(values[-1].get("period")),
                  source_ref=values[-1].get("source_ref"),
                  known_at=max((_day(row.get("known_at")) or "") for row in values),
                  numbers={"n": len(values), "span_days": _span_days(values)})


def _op_describe_series(part, values, ctx):
    numbers = [_num(row.get("value")) for row in values]
    numbers = [number for number in numbers if number is not None]
    if not numbers:
        raise _Empty()
    numbers_dict = {"n": len(numbers), "first": numbers[0], "last": numbers[-1],
                    "min": min(numbers), "max": max(numbers),
                    "mean": round(statistics.fmean(numbers), 4),
                    "span_days": _span_days(values)}
    return Result(part_index=part.index, atom=part.atom, formula=part.formula,
                  dims=part.dims, window=ctx["window"], operator=part.operator,
                  shape="one sentence + the numbers behind it", answer_type="measured",
                  values=[dict(row) for row in values], unit=values[0].get("unit"),
                  period=_day(values[-1].get("period")),
                  source_ref=values[-1].get("source_ref"),
                  known_at=max((_day(row.get("known_at")) or "") for row in values),
                  verdict=(f"{numbers_dict['n']} points from {_day(values[0].get('period'))}"
                           f" to {_day(values[-1].get('period'))}: first {numbers[0]:,.4g}, "
                           f"last {numbers[-1]:,.4g}, min {min(numbers):,.4g}, "
                           f"max {max(numbers):,.4g}, mean {numbers_dict['mean']:,.4g}"),
                  numbers=numbers_dict)


def _op_extreme(part, values, ctx, highest: bool):
    numbered = [(_num(row.get("value")), row) for row in values
                if _num(row.get("value")) is not None]
    if not numbered:
        raise _Empty()
    pick = (max if highest else min)(numbered, key=lambda pair: pair[0])[1]
    return Result(part_index=part.index, atom=part.atom, formula=part.formula,
                  dims=part.dims, window=ctx["window"], operator=part.operator,
                  shape="one value + one date", answer_type="measured",
                  value=_num(pick.get("value")), values=[dict(row) for row in values],
                  unit=pick.get("unit"), period=_day(pick.get("period")),
                  isin=pick.get("entity_id"), source_ref=pick.get("source_ref"),
                  known_at=_day(pick.get("known_at")),
                  numbers={"n": len(numbered)})


def _op_max_with_date(part, values, ctx):
    return _op_extreme(part, values, ctx, True)


def _op_min_with_date(part, values, ctx):
    return _op_extreme(part, values, ctx, False)


def _delta(part, values, ctx) -> tuple[float | None, dict[str, Any], dict[str, Any]]:
    numbered = [row for row in values if _num(row.get("value")) is not None]
    if len(numbered) < 2:
        raise _Empty()
    # A difference over rows of different entities is not a change: a macro series atom
    # read for a company mixes every underlying (MB0634: 2.33 in 2007 to 4,021 in 2026
    # spanning zinc and coal), and a cross-entity close range compares two companies.
    owners = {str(row.get("entity_id")) for row in numbered if row.get("entity_id")}
    if len(owners) > 1:
        shown = sorted(owners)
        raise _Missing(
            f"a {part.operator} over {len(owners)} entities would compare "
            f"{shown[0]} with {shown[-1]} as if they were one series",
            f"resolve one entity/series before a {part.operator} (the ask names "
            f"{ctx.get('entity') or 'none'})")
    first, last = numbered[0], numbered[-1]
    return (_num(last.get("value")) - _num(first.get("value"))), first, last


def _op_change(part, values, ctx):
    delta, first, last = _delta(part, values, ctx)
    return Result(part_index=part.index, atom=part.atom, formula=part.formula,
                  dims=part.dims, window=ctx["window"], operator=part.operator,
                  shape="one signed difference", answer_type="measured", value=delta,
                  values=[dict(row) for row in values], unit=last.get("unit"),
                  period=_day(last.get("period")), isin=last.get("entity_id"),
                  source_ref=last.get("source_ref"), known_at=_day(last.get("known_at")),
                  numbers={"from": _day(first.get("period")), "to": _day(last.get("period")),
                           "first": _num(first.get("value")),
                           "last": _num(last.get("value"))})


def _op_pct_change(part, values, ctx):
    delta, first, last = _delta(part, values, ctx)
    base = _num(first.get("value"))
    pct = None if not base else round(100.0 * delta / abs(base), 4)
    return Result(part_index=part.index, atom=part.atom, formula=part.formula,
                  dims=part.dims, window=ctx["window"], operator=part.operator,
                  shape="one percent", answer_type="measured", value=pct,
                  values=[dict(row) for row in values], unit="%",
                  period=_day(last.get("period")), isin=last.get("entity_id"),
                  source_ref=last.get("source_ref"), known_at=_day(last.get("known_at")),
                  numbers={"basis": str(part.dims.get("lag") or "window"),
                           "from": _day(first.get("period")), "to": _day(last.get("period")),
                           "first": base, "last": _num(last.get("value"))})


def _op_growth(part, values, ctx):
    return _op_pct_change(part, values, ctx)


def _op_lag_between(part, values, ctx):
    dated = [row for row in values if _day(row.get("period"))]
    if len(dated) < 2:
        raise _Empty()
    first, last = dated[0], dated[-1]
    from datetime import date
    days = (date.fromisoformat(_day(last["period"])) -
            date.fromisoformat(_day(first["period"]))).days
    return Result(part_index=part.index, atom=part.atom, formula=part.formula,
                  dims=part.dims, window=ctx["window"], operator=part.operator,
                  shape="one integer number of days", answer_type="measured",
                  value=days, unit="days", period=_day(last["period"]),
                  isin=last.get("entity_id"), source_ref=last.get("source_ref"),
                  known_at=_day(last.get("known_at")),
                  numbers={"from": _day(first["period"]), "to": _day(last["period"])})


def _op_span_days(part, values, ctx):
    days = _span_days(values)
    if days is None:
        raise _Empty()
    latest = _latest(values) or {}
    return Result(part_index=part.index, atom=part.atom, formula=part.formula,
                  dims=part.dims, window=ctx["window"], operator=part.operator,
                  shape="one integer number of days", answer_type="measured",
                  value=days, unit="days", period=_day(latest.get("period")),
                  isin=latest.get("entity_id"), source_ref=latest.get("source_ref"),
                  known_at=_day(latest.get("known_at")),
                  numbers={"n": len(values)})


def _op_aggregate(part, values, ctx):
    numbers = [_num(row.get("value")) for row in values]
    numbers = [number for number in numbers if number is not None]
    if not numbers:
        raise _Empty()
    kind = str(part.dims.get("agg") or "sum").lower()
    if kind == "mean":
        out = statistics.fmean(numbers)
    elif kind == "min":
        out = min(numbers)
    elif kind == "max":
        out = max(numbers)
    elif kind == "count":
        out = len(numbers)
    else:
        out = sum(numbers)
    latest = _latest(values) or {}
    return Result(part_index=part.index, atom=part.atom, formula=part.formula,
                  dims=part.dims, window=ctx["window"], operator=part.operator,
                  shape="one scalar", answer_type="measured", value=out,
                  values=[dict(row) for row in values],
                  unit="count" if kind == "count" else latest.get("unit"),
                  period=_day(latest.get("period")), isin=latest.get("entity_id"),
                  source_ref=latest.get("source_ref"),
                  known_at=_day(latest.get("known_at")),
                  numbers={"agg": kind, "n": len(numbers)})


def _op_count(part, values, ctx):
    entities = {row.get("entity_id") for row in values if row.get("entity_id")}
    distinct = part.dims.get("distinct")
    value = len(entities) if distinct in ("entity", "entities") else len(values)
    latest = _latest(values) or {}
    return Result(part_index=part.index, atom=part.atom, formula=part.formula,
                  dims=part.dims, window=ctx["window"], operator=part.operator,
                  shape="one integer", answer_type="measured", value=value,
                  unit="count", period=_day(latest.get("period")),
                  isin=latest.get("entity_id"), source_ref=latest.get("source_ref"),
                  known_at=_day(latest.get("known_at")),
                  numbers={"n": len(values), "entities": len(entities)})


def _op_exists(part, values, ctx):
    latest = _latest(values) or {}
    return Result(part_index=part.index, atom=part.atom, formula=part.formula,
                  dims=part.dims, window=ctx["window"], operator=part.operator,
                  shape="verdict + the numbers", answer_type="measured",
                  verdict="yes" if values else "no",
                  value=1 if values else 0, unit="count",
                  period=_day(latest.get("period")), isin=latest.get("entity_id"),
                  source_ref=latest.get("source_ref"),
                  known_at=_day(latest.get("known_at")),
                  numbers={"rows_after_pit": len(values)})


#: a list answer must state its items; a series with thousands of distinct values is
#: not a list, and printing one "—" as the value is not a measurement (MB0525).
LIST_DISTINCT_MAX = 50


def _op_list_distinct(part, values, ctx):
    key = str(part.dims.get("distinct") or "value")
    if key in ("entity", "entities", "entity_id"):
        items = sorted({row.get("entity_id") for row in values if row.get("entity_id")})
    elif key == "period":
        items = sorted({_day(row.get("period")) for row in values if row.get("period")})
    elif key == "dims":
        items = sorted({json.dumps(row.get("dims") or {}, sort_keys=True) for row in values})
    else:
        items = sorted({_num(row.get("value")) for row in values
                        if _num(row.get("value")) is not None})
        if len(items) > LIST_DISTINCT_MAX:
            raise _Missing(
                f"list_distinct collected {len(items):,} distinct {key} values over "
                f"{len(values):,} rows: that is a series, not a value that can be stated "
                f"in one answer",
                "ask for the series (operator series) or name a single period/entity so "
                "the distinct set is bounded")
    if not items:
        raise _Empty()
    latest = _latest(values) or {}
    return Result(part_index=part.index, atom=part.atom, formula=part.formula,
                  dims=part.dims, window=ctx["window"], operator=part.operator,
                  shape="matching entity list" if key.startswith("entity") else
                  "deduplicated entity list with the evidence row",
                  answer_type="measured", values=[{"value": item} for item in items],
                  unit=None, period=_day(latest.get("period")),
                  isin=latest.get("entity_id"), source_ref=latest.get("source_ref"),
                  known_at=_day(latest.get("known_at")),
                  numbers={"n": len(items), "distinct": key})


def _per_entity(conn: Any, part: Part, as_of: str, lo: str | None, hi: str | None,
                entities: Sequence[str] | None, limit: int) -> list[dict[str, Any]] | None:
    inner = ("SELECT entity_id, value, unit, period_end, known_at, source_ref, dims, "
             "row_number() OVER (PARTITION BY entity_id ORDER BY "
             "COALESCE(period_end, period_start) DESC, known_at DESC) AS rn "
             "FROM fact WHERE atom_id = ? AND substr(known_at,1,10) <= ?"
             " AND value IS NOT NULL")
    params: list[Any] = [str(part.atom), as_of]
    if lo:
        inner += " AND substr(COALESCE(period_end, period_start),1,10) >= ?"
        params.append(lo)
    if hi:
        inner += " AND substr(COALESCE(period_end, period_start),1,10) <= ?"
        params.append(hi)
    if entities:
        inner += " AND entity_id IN (" + ",".join("?" for _ in entities) + ")"
        params.extend(entities)
    sql = (f"SELECT entity_id, value, unit, period_end, known_at, source_ref, dims "
           f"FROM ({inner}) WHERE rn = 1 ORDER BY value DESC LIMIT {int(limit)}")
    return db_rows(conn, sql, params)


def _op_rank(part, values, ctx):
    limit = int(part.dims.get("limit") or part.dims.get("n") or 10)
    rows = _per_entity(ctx["conn"], part, ctx["as_of"], ctx["lo"], ctx["hi"],
                       ctx["entities"], limit)
    if not rows:
        raise _Empty()
    ranked = []
    carried = carried_dims(rows)
    for position, row in enumerate(rows, 1):
        if not _dim_match(row, part.dims, carried):
            continue
        ranked.append({"rank": position, "entity_id": row.get("entity_id"),
                       "value": _num(row.get("value")), "unit": row.get("unit"),
                       "period": _day(row.get("period_end")),
                       "known_at": _day(row.get("known_at")),
                       "source_ref": row.get("source_ref")})
    if not ranked:
        raise _Empty()
    return Result(part_index=part.index, atom=part.atom, formula=part.formula,
                  dims=part.dims, window=ctx["window"], operator=part.operator,
                  shape="top-n list with values", answer_type="measured",
                  entities=ranked, value=None, unit=ranked[0].get("unit"),
                  period=ranked[0].get("period"),
                  source_ref=ranked[0].get("source_ref"),
                  known_at=max((row.get("known_at") or "") for row in ranked),
                  numbers={"n": len(ranked), "by": "value DESC"})


def _op_screen(part, values, ctx):
    return _op_rank(part, values, ctx)


def _op_compare(part, values, ctx):
    return _op_rank(part, values, ctx)


def _op_join_entity_set(part, values, ctx):
    conn = ctx["conn"]
    if conn is None or not _has(conn, "membership"):
        raise _Missing("the membership table is not built in this store",
                       "WP2a build_membership.py (§B.2)")
    kind = part.dims.get("set_kind") or part.dims.get("scope") or "index"
    value = part.dims.get("set_value") or part.dims.get("index") or part.dims.get("sector")
    if not value:
        raise _Missing("join_entity_set part names no set value (dims.set_value)",
                       "the decomposer must emit dims.set_value for an entity set")
    rows = db_rows(
        conn,
        "SELECT DISTINCT entity_id, set_kind, set_value, weight, source, known_at "
        "FROM membership WHERE set_kind = ? AND set_value = ? "
        "AND substr(valid_from,1,10) <= ? "
        "AND (valid_to IS NULL OR substr(valid_to,1,10) > ?) "
        "AND substr(known_at,1,10) <= ? ORDER BY entity_id",
        [kind, value, ctx["as_of"], ctx["as_of"], ctx["as_of"]])
    if not rows:
        raise _Empty()
    return Result(part_index=part.index, atom=part.atom, formula=part.formula,
                  dims=part.dims, window=ctx["window"], operator=part.operator,
                  shape="entity ids valid at as_of", answer_type="measured",
                  entities=[{"entity_id": row.get("entity_id"), "weight": row.get("weight"),
                             "source": row.get("source"), "known_at": _day(row.get("known_at"))}
                            for row in rows],
                  values=[], source_ref="membership",
                  known_at=max((_day(row.get("known_at")) or "") for row in rows),
                  numbers={"n": len(rows), "set_kind": kind, "set_value": value})


def _op_zscore(part, values, ctx):
    numbers = [_num(row.get("value")) for row in values]
    numbers = [number for number in numbers if number is not None]
    if len(numbers) < 3:
        raise _Empty()
    mean = statistics.fmean(numbers)
    stdev = statistics.pstdev(numbers)
    if not stdev:
        raise _Empty()
    z = (numbers[-1] - mean) / stdev
    latest = _latest(values) or {}
    return Result(part_index=part.index, atom=part.atom, formula=part.formula,
                  dims=part.dims, window=ctx["window"], operator=part.operator,
                  shape="one z", answer_type="measured", value=round(z, 4),
                  unit="z", period=_day(latest.get("period")),
                  isin=latest.get("entity_id"), source_ref=latest.get("source_ref"),
                  known_at=_day(latest.get("known_at")),
                  numbers={"mean": mean, "stdev": stdev, "n": len(numbers),
                           "last": numbers[-1]})


def _op_correlate(part, values, ctx):
    other = part.dims.get("atom_b") or part.dims.get("other_atom")
    if not other or ctx["conn"] is None:
        raise _Missing("correlate part names no second atom (dims.atom_b)",
                       "the decomposer must emit dims.atom_b for a correlate")
    conn = ctx["conn"]
    first = fetch_fact(conn, str(part.atom), ctx["as_of"], ctx["lo"], ctx["hi"],
                       ctx["entity"]) or []
    second = fetch_fact(conn, str(other), ctx["as_of"], ctx["lo"], ctx["hi"],
                        ctx["entity"]) or []
    by_period: dict[str, list[float | None]] = {}
    for row in first:
        day = _day(row.get("period_end") or row.get("period_start"))
        if _num(row.get("value")) is not None and day:
            by_period.setdefault(day, [None, None])[0] = _num(row["value"])
    for row in second:
        day = _day(row.get("period_end") or row.get("period_start"))
        if _num(row.get("value")) is not None and day in by_period:
            by_period[day][1] = _num(row["value"])
    pairs = [(a, b) for a, b in by_period.values() if a is not None and b is not None]
    if len(pairs) < 3:
        raise _Empty()
    xs, ys = [a for a, _ in pairs], [b for _, b in pairs]
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    cov = sum((x - mx) * (y - my) for x, y in pairs)
    sx = sum((x - mx) ** 2 for x in xs) ** 0.5
    sy = sum((y - my) ** 2 for y in ys) ** 0.5
    if not sx or not sy:
        raise _Empty()
    r = cov / (sx * sy)
    latest = _latest(values) or {}
    return Result(part_index=part.index, atom=part.atom, formula=part.formula,
                  dims=part.dims, window=ctx["window"], operator=part.operator,
                  shape="one r + n", answer_type="measured", value=round(r, 4), unit="r",
                  period=_day(latest.get("period")), isin=latest.get("entity_id"),
                  source_ref=latest.get("source_ref"),
                  known_at=_day(latest.get("known_at")),
                  numbers={"n": len(pairs), "against": other})


def _op_threshold_cross(part, values, ctx):
    threshold = _num(part.dims.get("threshold"))
    if threshold is None:
        raise _Missing("threshold_cross part names no threshold (dims.threshold)",
                       "the decomposer must emit dims.threshold for a crossing")
    direction = str(part.dims.get("cross") or part.dims.get("direction") or "up").lower()
    previous = None
    for row in values:
        number = _num(row.get("value"))
        if number is None:
            continue
        crossed = (previous is not None and
                   ((direction == "up" and previous < threshold <= number) or
                    (direction == "down" and previous > threshold >= number)))
        if crossed:
            return Result(part_index=part.index, atom=part.atom, formula=part.formula,
                          dims=part.dims, window=ctx["window"], operator=part.operator,
                          shape="one date + the value at the crossing",
                          answer_type="measured", value=number, unit=row.get("unit"),
                          period=_day(row.get("period")), isin=row.get("entity_id"),
                          source_ref=row.get("source_ref"),
                          known_at=_day(row.get("known_at")),
                          verdict=f"crossed {direction} {threshold}", numbers={
                              "threshold": threshold, "previous": previous, "value": number})
        previous = number
    latest = _latest(values) or {}
    return Result(part_index=part.index, atom=part.atom, formula=part.formula,
                  dims=part.dims, window=ctx["window"], operator=part.operator,
                  shape="one date + the value at the crossing", answer_type="measured",
                  value=None, unit=latest.get("unit"),
                  period=_day(latest.get("period")), isin=latest.get("entity_id"),
                  source_ref=latest.get("source_ref"),
                  known_at=_day(latest.get("known_at")),
                  verdict=f"no {direction} crossing of {threshold}", numbers={
                      "threshold": threshold, "n": len(values)})


def _op_event_window_return(part, values, ctx):
    """Return from the event session to +n sessions, over the fact view's closes.

    §D.2's event-study engine owns the 15:30 session-0 rule; this is the fallback
    the executor can compute from price rows alone, and it says so in rule_used.
    """
    event = _day(part.dims.get("event_date") or part.dims.get("date") or ctx["lo"])
    if not event:
        raise _Missing("event_window_return part names no event date",
                       "the decomposer must emit the event date for the window")
    conn = ctx["conn"]
    if conn is None:
        raise _Missing("no database connection was supplied",
                       "pass the pilot store connection")
    rows = fetch_fact(conn, "price.close", ctx["as_of"], event, None, ctx["entity"]) or []
    offset = int(part.dims.get("n") or 1)
    rows = [row for row in rows if (_day(row.get("period_end")) or "") >= event]
    if len(rows) < 2:
        raise _Empty()
    base = _num(rows[0].get("value"))
    end = _num(rows[min(offset, len(rows) - 1)].get("value"))
    if not base or not rows[0].get("value"):
        raise _Empty()
    pct = round(100.0 * (end - base) / abs(base), 4)
    return Result(part_index=part.index, atom=part.atom, formula=part.formula,
                  dims=part.dims, window=ctx["window"], operator=part.operator,
                  shape="session-0 date, offset, abnormal return, delivery z",
                  answer_type="measured", value=pct, unit="%",
                  period=_day(rows[min(offset, len(rows) - 1)].get("period_end")),
                  isin=rows[0].get("entity_id"),
                  source_ref=rows[0].get("source_ref"),
                  known_at=_day(rows[0].get("known_at")),
                  rule_used="event_window_return over fact-view price sessions; "
                            "the 15:30 session-0 rule needs event_day0, not wired here",
                  numbers={"event_date": event, "offset": offset, "base": base,
                           "end": end})


def _shift_day(day: str, days: int) -> str | None:
    from datetime import date, timedelta
    try:
        return (date.fromisoformat(day[:10]) + timedelta(days=days)).isoformat()
    except ValueError:
        return None


def _daily_series(rows: Sequence[Mapping[str, Any]] | None,
                  prefer: str | None = None) -> dict[str, float]:
    """``{session: value}`` from fact rows; rows are date-ordered, so the last one wins.

    ``prefer`` names the dim reading to take when a session has several rows (the store's
    ``price.high`` carries NSE and BSE): NSE wins, BSE is the fallback.  Without a tie,
    the later ``known_at`` wins as the row order already puts it last.
    """
    out: dict[str, float] = {}
    rank_of: dict[str, int] = {}
    for row in rows or []:
        day = _day(row.get("period_end") or row.get("period_start"))
        number = _num(row.get("value"))
        if not day or number is None:
            continue
        rank = 0 if prefer and prefer in str(row.get("dims") or "") else 1
        if day not in out or rank <= rank_of[day]:
            out[day] = number
            rank_of[day] = rank
    return out


def _execute_near_high(conn: Any, part: Part, as_of: str, lo: str | None, hi: str | None,
                       entity: str | None, window: dict[str, Any]) -> Result:
    """Sessions within N% of their *then-current* 52-week high, and what followed.

    The high for session ``d`` is the maximum of the basis series over the rows dated
    ``d - lookback`` .. ``d`` only: a later row can never change an earlier session, and
    the ``known_at`` cut at ``as_of`` is done in SQL.  The answer is either the count or
    the share of the window's sessions, plus every qualifying session and their forward
    returns — losers included, and an incomplete forward window counted separately and
    named, never dropped.  Raw basis: the store holds no adjusted series, so a share-count
    change (split/bonus) inside the 52-week trail is named in the answer, never compared
    across silently.  A demerger does not change ``price.shares_out`` and is therefore not
    detectable from this store; that is the known gap this cheap test found.
    """
    threshold = _num(part.dims.get("threshold"))
    if threshold is None:
        raise _Missing("near_high part names no threshold (dims.threshold)",
                       "the decomposer must emit the 'within N%' threshold")
    lookback = int(_num(part.dims.get("lookback_days")) or 364)
    kind = str(part.dims.get("measure") or "share").lower()
    forward = int(_num(part.dims.get("forward")) or 0)
    prior_only = bool(part.dims.get("prior_only"))
    if conn is None:
        raise _Missing("no database connection was supplied",
                       "pass the pilot store connection")
    if not entity:
        raise _Missing("the ask names no single entity for the study",
                       "resolve the named company PIT (§C.2) before a study part")
    if not hi:
        raise _Missing("the ask names no window for the study",
                       "the decomposer must emit the study window")
    if not lo:
        lo = _shift_day(hi, -lookback) or hi
    trail_start = _shift_day(lo, -lookback) or lo
    high_rows = fetch_fact(conn, "price.high", as_of, trail_start, as_of, entity)
    close_rows = fetch_fact(conn, "price.close", as_of, trail_start, as_of, entity)
    highs = _daily_series(high_rows, "NSE")
    closes = _daily_series(close_rows)
    if not closes:
        raise _Empty()
    sessions = [day for day in sorted(closes) if lo <= day <= hi]
    if not sessions:
        raise _Empty()
    need_from = _shift_day(sessions[0], -lookback) or sessions[0]
    store_close_basis = close_basis(conn, close_rows)
    adjusted_closes = store_close_basis == "adjusted"
    basis, series, basis_note = "price.high", highs, ""
    if adjusted_closes and highs:
        # price.high is a raw intraday high and the stored close is the build's adjusted
        # series: dividing one by the other mixes bases (POWERGRID 2023-09-11: close
        # 198.375 vs a 265.00 high).  One basis per study: the adjusted close.
        series, basis = closes, "price.close"
        basis_note = ("the stored close is the adjusted series while price.high is raw; "
                      "the study uses one basis (the adjusted close) and its 52-week high "
                      "is the highest adjusted close")
    elif not highs or min(highs) > need_from:
        earliest = min(highs) if highs else "absent entirely"
        series, basis = closes, "price.close"
        basis_note = (f"the NSE intraday-high series has no row before {need_from} "
                      f"(its earliest is {earliest}), so the 52-week high is the max of "
                      f"{RAW_CLOSE if store_close_basis == 'raw' else 'stored'} closes")
        if min(closes) > need_from:
            raise _Missing(
                f"{entity} has no {lookback} days of daily prices before {sessions[0]} "
                f"(a 52-week study needs the full trail): the store's close series "
                f"starts {min(closes)}",
                f"hold {lookback} days of daily sessions before the study window")
    sdates = sorted(series)
    svals = [series[day] for day in sdates]
    # "prior sessions" are the sessions strictly before the as_of session; when as_of is
    # not itself a session, the last trading session is a prior one and stays in.
    evaluated = [day for day in sessions if day < hi] if prior_only else sessions
    if not evaluated:
        raise _Missing("the study window holds no session before the reference session",
                       "widen the window so it holds at least two sessions")
    qualifying: list[dict[str, Any]] = []
    skipped = 0
    for day in evaluated:
        left = bisect_left(sdates, _shift_day(day, -lookback) or day)
        right = bisect_right(sdates, day)
        close = closes.get(day)
        if right <= left or close is None:
            skipped += 1
            continue
        high_52w = max(svals[left:right])
        if not high_52w:
            skipped += 1
            continue
        distance = 100.0 * (high_52w - close) / high_52w
        if distance <= threshold + 1e-9:
            qualifying.append({"period": day, "close": round(close, 4),
                               "high_52w": round(high_52w, 4),
                               "distance_pct": round(distance, 4),
                               "forward_pct": None, "forward_end": None,
                               "forward_status": ""})
    forward_stats: dict[str, Any] = {}
    if forward and qualifying:
        order = sorted(closes)
        positions = {day: index for index, day in enumerate(order)}
        complete: list[float] = []
        incomplete: list[str] = []
        for row in qualifying:
            index = positions[row["period"]] + forward
            base = closes[row["period"]]
            if index < len(order) and base:
                end_day = order[index]
                row["forward_pct"] = round(100.0 * (closes[end_day] - base) / base, 4)
                row["forward_end"] = end_day
                row["forward_status"] = "complete"
                complete.append(row["forward_pct"])
            else:
                row["forward_status"] = f"incomplete: no session +{forward} on or before {as_of}"
                incomplete.append(row["period"])
        forward_stats = {"forward_sessions": forward,
                         "forward_complete": len(complete),
                         "forward_incomplete": len(incomplete),
                         "incomplete_sessions": incomplete,
                         "winners": sum(1 for value in complete if value > 0),
                         "losers": sum(1 for value in complete if value < 0),
                         "flat": sum(1 for value in complete if value == 0)}
        if complete:
            forward_stats.update({"mean_pct": round(statistics.fmean(complete), 4),
                                  "median_pct": round(statistics.median(complete), 4),
                                  "min_pct": min(complete), "max_pct": max(complete)})
    shares = _daily_series(fetch_fact(conn, "price.shares_out", as_of, trail_start, hi, entity))
    share_days = sorted(shares)
    actions = [{"date": later, "shares_from": shares[earlier],
                "shares_to": shares[later],
                "ratio": round(shares[later] / shares[earlier], 6)}
               for earlier, later in zip(share_days, share_days[1:])
               if shares[earlier] and abs(shares[later] / shares[earlier] - 1.0) > 0.002]
    share_of = round(100.0 * len(qualifying) / len(evaluated), 4)
    value, unit = ((len(qualifying), "sessions") if kind != "share"
                   else (share_of, "%"))
    exchange = ("NSE-first high (BSE fallback)" if basis == "price.high"
                else "NSE-first close (BSE fallback)")
    high_kind = "intraday high" if basis == "price.high" else "close"
    if adjusted_closes:
        basis_text = (f"basis: {ADJUSTED_CLOSE}; it is not a traded price: an action "
                      f"after the date is already reflected")
    elif store_close_basis == "raw":
        basis_text = f"basis: {RAW_CLOSE} (price.close); splits/bonuses are not adjusted"
    else:
        basis_text = ("basis: not stated by the store; the close is not labelled raw and "
                      "no adjustment is assumed")
    assumed = (f"{basis_text}; 52-week "
               f"high = the highest {high_kind} in the {lookback} days ending on each "
               f"session, from rows dated on or before it; window {lo}..{hi} "
               f"({len(sessions)} sessions"
               f"{', the latest excluded: a prior-session count' if prior_only else ''})"
               f"; threshold within {threshold:g}% of that high; exchange {exchange}"
               + (f"; {basis_note}" if basis_note else "")
               + (f"; forward return = {forward} sessions from each qualifying close"
                  + (" (declared default: the ask says only what followed)"
                     if part.dims.get("forward_default") else "")
                  if forward else ""))
    if actions:
        assumed += (("; corporate action inside the 52-week trail (already applied to "
                     "the adjusted closes), named: ")
                    if adjusted_closes else
                    ("; corporate action inside the 52-week trail (rows used for the "
                     "high), named: "))
        assumed += (", ".join(f"{row['date']} shares {row['shares_from']:,.0f} -> "
                              f"{row['shares_to']:,.0f}" for row in actions))
        if not adjusted_closes:
            assumed += " (raw prices across it are not adjusted)"
    else:
        assumed += "; no share-count change (split/bonus) inside the 52-week trail"
    known = max([(_day(row.get("known_at")) or "") for row in
                 (high_rows or []) + (close_rows or [])] or [""]) or as_of
    numbers = {"threshold_pct": threshold, "window_from": lo, "window_to": hi,
               "lookback_days": lookback, "basis": basis, "exchange": exchange,
               "close_basis": store_close_basis or "unstated",
               "n_sessions": len(evaluated), "n_qualifying": len(qualifying),
               "share_pct": share_of, "skipped_no_trail": skipped,
               "corporate_actions": actions or "none"}
    numbers.update(forward_stats)
    return Result(part_index=part.index, atom=part.atom, formula=part.formula,
                  dims=part.dims, window=window, operator=part.operator,
                  shape="scalar", answer_type="measured", value=value, unit=unit,
                  values=qualifying, period=hi, isin=entity, source_ref=basis,
                  known_at=known, assumption=assumed, numbers=numbers)


#: one-value operators: with dims value "each" they must show every reading.
SCALAR_ONE = {"value_at", "first_visible", "last_visible", "max_with_date",
              "min_with_date"}
OPERATORS = {
    "value_at": _op_value_at,
    "series": _op_series,
    "describe_series": _op_describe_series,
    "max_with_date": _op_max_with_date,
    "min_with_date": _op_min_with_date,
    "change": _op_change,
    "pct_change": _op_pct_change,
    "growth": _op_growth,
    "lag_between": _op_lag_between,
    "span_days": _op_span_days,
    "aggregate": _op_aggregate,
    "count": _op_count,
    "exists": _op_exists,
    "list_distinct": _op_list_distinct,
    "rank": _op_rank,
    "screen": _op_screen,
    "compare": _op_compare,
    "join_entity_set": _op_join_entity_set,
    "zscore": _op_zscore,
    "correlate": _op_correlate,
    "threshold_cross": _op_threshold_cross,
    "event_window_return": _op_event_window_return,
    "first_visible": _op_first_visible,
    "last_visible": _op_last_visible,
}


# ---------------------------------------------------------------------------
# formulas (§A.3): one arithmetic line per formula, over the atoms of `over`
# ---------------------------------------------------------------------------
def _value_of(v: Mapping[str, float], atom: str, default: float | None = None) -> float:
    if atom in v and v[atom] is not None:
        return v[atom]
    if default is not None:
        return default
    raise KeyError(atom)


def _formula_margin(v, dims):
    numerator = "fin.ebitda" if str(dims.get("margin_kind") or "ebitda") == "ebitda" else "fin.pat"
    return 100.0 * _value_of(v, numerator) / _value_of(v, "fin.revenue")


def _formula_ratio(v, dims):
    kind = str(dims.get("ratio_kind") or "de")
    if kind == "de":
        return _value_of(v, "fin.total_debt") / _value_of(v, "fin.book_equity")
    if kind == "pb":
        return _value_of(v, "price.mcap") / _value_of(v, "fin.book_equity")
    if kind == "pe":
        return _value_of(v, "price.mcap") / _value_of(v, "fin.pat")
    if kind == "icr":
        return _value_of(v, "fin.ebitda") / _value_of(v, "fin.interest_expense")
    raise KeyError(f"ratio_kind {kind} needs a peer/EV store this executor does not read")


def _formula_dso(v, dims):
    return _value_of(v, "fin.receivables") / _value_of(v, "fin.revenue") * 365.0


def _formula_wcc(v, dims):
    revenue = _value_of(v, "fin.revenue")
    return (_value_of(v, "fin.receivables") + _value_of(v, "fin.inventory")
            - _value_of(v, "fin.payables")) / revenue * 365.0


def _formula_share_of(v, dims):
    part_atom = str(dims.get("part_atom") or "fin.segment_value")
    return 100.0 * _value_of(v, part_atom) / _value_of(v, "fin.revenue")


def _formula_net(v, dims):
    atoms = list(dims.get("atoms") or [])
    if not atoms:
        raise KeyError("dims.atoms (the rows whose signs are netted)")
    return sum(_value_of(v, atom) for atom in atoms)


def _formula_per_rupee_revenue(v, dims):
    return _value_of(v, "_delta_capex") / _value_of(v, "_delta_revenue")


def _formula_book_value_per_share(v, dims):
    return _value_of(v, "fin.book_equity") / _value_of(v, "price.shares_out")


def _formula_gap_pct(v, dims):
    previous = _value_of(v, "_prev_close")
    return 100.0 * (_value_of(v, "price.open") - previous) / previous


def _formula_drawdown(v, dims):
    peak = _value_of(v, "_max_close")
    return 100.0 * (_value_of(v, "price.close") / peak - 1.0)


def _formula_cagr(v, dims):
    years = _value_of(v, "_years")
    return 100.0 * ((_value_of(v, "_end") / _value_of(v, "_start")) ** (1.0 / years) - 1.0)


def _formula_excess_return(v, dims):
    return _value_of(v, "_company_return") - _value_of(v, "_benchmark_return")


def _formula_spread(v, dims):
    output = dims.get("output_atom")
    cost = dims.get("input_atom")
    if not output or not cost:
        raise KeyError("dims.output_atom and dims.input_atom")
    return _value_of(v, str(output)) - _value_of(v, str(cost))


FORMULAS = {
    "f.margin": _formula_margin,
    "f.ratio": _formula_ratio,
    "f.dso": _formula_dso,
    "f.working_capital_cycle": _formula_wcc,
    "f.share_of": _formula_share_of,
    "f.net": _formula_net,
    "f.per_rupee_revenue": _formula_per_rupee_revenue,
    "f.book_value_per_share": _formula_book_value_per_share,
    "f.gap_pct": _formula_gap_pct,
    "f.drawdown": _formula_drawdown,
    "f.cagr": _formula_cagr,
    "f.excess_return": _formula_excess_return,
    "f.spread": _formula_spread,
}
FORMULA_UNIT = {"f.margin": "%", "f.dso": "days", "f.working_capital_cycle": "days",
                "f.share_of": "%", "f.book_value_per_share": "INR/share",
                "f.gap_pct": "%", "f.drawdown": "%", "f.cagr": "%",
                "f.excess_return": "%"}


def _ratio_inputs(dims: Mapping[str, Any]) -> list[str]:
    """The two atoms the requested ratio actually divides (never the whole `over`)."""
    kind = str(dims.get("ratio_kind") or "de")
    try:
        return {"de": ["fin.total_debt", "fin.book_equity"],
                "pb": ["price.mcap", "fin.book_equity"],
                "pe": ["price.mcap", "fin.pat"],
                "icr": ["fin.ebitda", "fin.interest_expense"]}[kind]
    except KeyError:
        raise KeyError(f"ratio_kind {kind} needs a peer/EV store this executor does not "
                       f"read") from None


#: The atoms each formula body reads, in the order it reads them.  A derived value
#: must name the inputs it really used: the registry's ``over`` is the union over
#: every selector, not the inputs of one answer (MB0064#L: a P/B must not cite the
#: debt source).  A missing entry here is a typing bug, not a fallback.
FORMULA_INPUTS = {
    "f.margin": lambda d: ["fin.ebitda" if str(d.get("margin_kind") or "ebitda") == "ebitda"
                           else "fin.pat", "fin.revenue"],
    "f.ratio": _ratio_inputs,
    "f.dso": lambda d: ["fin.receivables", "fin.revenue"],
    "f.working_capital_cycle": lambda d: ["fin.receivables", "fin.inventory",
                                          "fin.payables", "fin.revenue"],
    "f.share_of": lambda d: [str(d.get("part_atom") or "fin.segment_value"), "fin.revenue"],
    "f.net": lambda d: [str(atom) for atom in (d.get("atoms") or [])],
    "f.per_rupee_revenue": lambda d: ["fin.capex", "fin.revenue"],
    "f.book_value_per_share": lambda d: ["fin.book_equity", "price.shares_out"],
    "f.gap_pct": lambda d: ["price.open", "price.close"],
    "f.drawdown": lambda d: ["price.close"],
    "f.cagr": lambda d: ["price.close"],
    "f.excess_return": lambda d: ["price.close"],
    "f.spread": lambda d: [str(d.get("output_atom") or ""), str(d.get("input_atom") or "")],
}


def formula_inputs(fid: str, dims: Mapping[str, Any]) -> list[str]:
    """The atoms a formula answer used; a selector the formula cannot run raises."""
    return [atom for atom in FORMULA_INPUTS[fid](dims) if atom]


FORMULA_EXTRA_ATOMS = {"f.ratio": ["fin.interest_expense"], "f.cagr": [], "f.excess_return": []}


# ---------------------------------------------------------------------------
# price basis: a close is not always raw, and a split inside a window is not a return
# ---------------------------------------------------------------------------
RAW_CLOSE = "raw close"
#: fact_view.sql must build price.close from market_state.company_state_daily.raw_close:
#: the traded close.  build_t1.py keeps the split/bonus/consolidation-adjusted series in
#: company_state_daily.close (from px_daily.adj_close, NOT dividend-adjusted); a build
#: that still loads that column says so in the answer instead of calling it raw.
ADJUSTED_CLOSE = "adjusted close (split/bonus/consolidation-adjusted at build)"
#: The basis a close row declares in its dims (fact_view.sql writes basis=raw for
#: price.close).  A store built before that dim carries none and is classified by the
#: panel below, conservatively.
CLOSE_BASIS_DIM = "basis"
#: A one-session fall this large is action-shaped (a bonus/split/consolidation or a
#: corporate restructuring); a smaller move is ordinary price risk.
SPLIT_JUMP_PCT = 30.0
#: the share-count factors a bonus/split writes: 1:3, 1:2, 1:1, 2:1, a 5:1 split, …
CLEAN_SHARE_RATIOS = (1.25, 4 / 3, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0, 20.0)


def _atom_held(conn: Any, atom: str) -> bool:
    """True when the fact store carries at least one row of ``atom``."""
    if conn is None:
        return False
    try:
        column = fact_atom_column(conn)
        return conn.execute(f"SELECT 1 FROM fact WHERE {column} = ? LIMIT 1",
                            (atom,)).fetchone() is not None
    except Exception:  # noqa: BLE001 - an unreadable store is not evidence of a row
        return False


def _close_reading(row: Mapping[str, Any]) -> str:
    return str(row_dims(row).get(CLOSE_BASIS_DIM) or "").lower()


def close_basis(conn: Any, rows: Sequence[Mapping[str, Any]] | None) -> str:
    """How this store's ``price.close`` is adjusted: ``raw``, ``adjusted`` or ``""``.

    A row's own ``basis`` dim wins: fact_view.sql writes ``basis=raw`` for
    price.close and the build re-reads ``company_state_daily.raw_close``.  A store
    built before that dim carries none; a T1 panel there is ``build_t1.py``'s
    ``px_daily.adj_close`` series, so it is classified adjusted, never raw.  A store
    with neither a dim nor a T1 panel states no basis and is never called raw.
    """
    readings = {_close_reading(row) for row in rows or [] if _close_reading(row)}
    if len(readings) == 1:
        return readings.pop()
    if readings:
        return ""                     # a mixed series cannot be named one basis
    if _atom_held(conn, "price.shares_out") and _atom_held(conn, "price.mcap"):
        return "adjusted"
    return ""


def _close_basis_note(basis: str) -> str:
    """The sentence a close level or return carries about its own basis."""
    if basis == "raw":
        return (f"{RAW_CLOSE}: price.close is the traded close, not adjusted for "
                f"corporate actions after the date")
    if basis == "adjusted":
        return (f"{ADJUSTED_CLOSE}; it is not a traded price: an action after the date "
                f"is already reflected, which a level as of that date must not use")
    return ("close basis not stated by the store; the close is not labelled raw and must "
            "not be read as a traded price")


def _with_close_basis(result: Result, conn: Any, rows: Sequence[Mapping[str, Any]]) -> Result:
    """Name a price.close level's basis (a level never passes as a returned number)."""
    if result.answer_type != "measured":
        return result
    basis = close_basis(conn, rows)
    result.numbers = dict(result.numbers or {}, close_basis=basis or "unstated")
    if not result.assumption:
        result.assumption = _close_basis_note(basis)
    return result


@dataclass
class PriceBasis:
    """The close series a return is computed from, and what that series is."""

    series: list[tuple[str, float]]
    rows: list[dict[str, Any]]
    actions: list[dict[str, Any]]
    unresolved: list[dict[str, Any]]
    adjusted: bool
    note: str


def _days_between(left: str | None, right: str | None) -> int:
    from datetime import date
    try:
        return (date.fromisoformat(str(right)) - date.fromisoformat(str(left))).days
    except (TypeError, ValueError):
        return 10 ** 6


def _clean_share_ratio(ratio: float) -> bool:
    # A split/bonus writes an exact factor (2, 4/3, 5, …).  A 1.5% "near 4/3" is a
    # preferential allotment, not a 1:3 bonus, so the tolerance is tight.
    for clean in CLEAN_SHARE_RATIOS:
        if abs(ratio / clean - 1.0) <= 0.005 or abs(ratio * clean - 1.0) <= 0.005:
            return True
    return False


def _share_steps(shares: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Held capital steps from ``price.shares_out``: ex-date, share ratio, known_at.

    The count alone cannot say "bonus" from "split": a 1:1 bonus and a 2:1 split are
    both a share-count x2.  The kind is therefore left as a share-count action, and
    the ratio (the number the arithmetic needs) is the held evidence.  A step that
    reverts within 450 days is a data/unit flip, not a capital action.
    """
    rows = sorted((_day(row.get("period_end")), _num(row.get("value")),
                   _day(row.get("known_at"))) for row in shares or [])
    out: list[dict[str, Any]] = []
    for index, (d0, n0, _) in enumerate(rows[:-1]):
        d1, n1, known = rows[index + 1]
        if not d0 or not d1 or not n0 or not n1 or n0 <= 0 or n1 <= 0:
            continue
        ratio = n1 / n0
        if 1 / 1.2 < ratio < 1.2 or ratio > 50 or ratio < 1 / 50:
            continue
        tail = [number for _, number, _ in rows[index + 2:index + 5]]
        if tail and not all(number and abs(number / n1 - 1.0) <= 0.02 for number in tail):
            continue                      # does not persist: a flip, not a step
        round_trip = any(number and abs(number / n0 - 1.0) <= 0.05
                         for d2, number, _ in rows[index + 2:]
                         if 0 <= _days_between(d1, d2) <= 450)
        if round_trip:
            continue                      # x2 then back to x1: a unit/source flip
        # A step that returns to a count held in the last 450 days is undoing an earlier
        # flip, not a second bonus on top of it.
        recent = [number for d_prev, number, _ in rows[:index]
                  if number and 0 <= _days_between(d_prev, d1) <= 450]
        if any(abs(number / n1 - 1.0) <= 0.05 for number in recent):
            continue
        out.append({"ex_date": d1, "ratio": round(ratio, 6), "known_at": known,
                    "clean": _clean_share_ratio(ratio),
                    "kind": "split/bonus" if ratio > 1 else "consolidation"})
    return out


def _close_break(prices: Sequence[tuple[str, float]], ex_date: str) -> float | None:
    """The close ratio across ``ex_date``: ≈1 when the series is already adjusted."""
    before = [value for day, value in prices if day < ex_date]
    after = [value for day, value in prices if day >= ex_date]
    if not before or not after or not before[-1]:
        return None
    return after[0] / before[-1]


def _price_rows(basis: PriceBasis, entity: str | None) -> list[dict[str, Any]]:
    """The basis series in the fact-row shape the operators already read."""
    source = {_day(row.get("period_end")): row for row in basis.rows}
    out = []
    for day, value in basis.series:
        row = source.get(day) or {}
        out.append({"entity_id": entity, "atom": "price.close", "period_start": day,
                    "period_end": day, "value": value, "unit": "INR",
                    "dims": {}, "known_at": _day(row.get("known_at")),
                    "source_ref": row.get("source_ref") or "price.close"})
    return out


def _close_readings(rows: Sequence[Mapping[str, Any]],
                    want_adjusted: bool) -> list[Mapping[str, Any]]:
    """The close rows of the asked basis; a bare row (no basis dim) serves either.

    The v4 pilot's price.close rows carry no basis dim (there is one panel); a test
    store may carry both ``basis=raw`` and ``basis=adjusted`` rows for one day, and
    mixing them would invent a jump.  The requested reading is preferred; with fewer
    than two of them, the plain rows are used; never both readings on one day.
    """
    wanted = "adjusted" if want_adjusted else "raw"

    def reading(row: Mapping[str, Any]) -> str:
        return str(row_dims(row).get("basis") or "").lower()

    preferred = [row for row in rows if reading(row) == wanted]
    if len(preferred) >= 2:
        return preferred
    plain = [row for row in rows if not reading(row)]
    if len(plain) >= 2:
        return plain
    other = [row for row in rows if reading(row) and reading(row) != wanted]
    if len(other) >= 2:
        return other            # the other reading is the held one; adjust it here
    return preferred or list(rows)


def price_basis(conn: Any, as_of: str, lo: str | None, hi: str | None,
                entity: str | None, *, want_adjusted: bool = False,
                total_return: bool = False) -> PriceBasis | None:
    """The close series for a return, its basis, and any action it cannot settle.

    ``price.close`` is the store's close series; fact_view.sql loads it from
    ``company_state_daily.raw_close`` and states ``basis=raw``, so a return is the one
    place the adjustment belongs.  A store built before that dim is the T1 panel whose
    price.close was ``px_daily.adj_close`` (splits, bonuses and consolidations applied,
    dividends not); it is named adjusted, never raw.  A row's own ``basis`` dim wins.

    ``price.shares_out`` is the held corporate-action evidence: a persisting step
    (x2, x5, …) is the ratio and its date is the ex-date.  A close that breaks by
    1/ratio across that date is raw and is adjusted here at query time; a close
    that does not break is already adjusted.  A large fall with no held step is an
    action we cannot settle, so the caller returns a typed NID naming it.

    No row is read after ``as_of``: the step's own ``known_at`` gates it.
    """
    if conn is None or not entity:
        return None
    close_rows = fetch_fact(conn, "price.close", as_of, lo, hi, entity)
    if close_rows is None:
        return None
    close_rows = _close_readings(close_rows, want_adjusted)
    stated = {_close_reading(row) for row in close_rows if _close_reading(row)}
    explicit = len(stated) == 1      # every chosen row states the same basis
    source = {_day(row.get("period_end")): row for row in close_rows
              if _day(row.get("period_end"))}
    prices = sorted((day, _num(row.get("value"))) for day, row in source.items()
                    if _num(row.get("value")) is not None)
    prices = [(day, number) for day, number in prices if day and number is not None]
    if len(prices) < 2:
        return None
    shares = fetch_fact(conn, "price.shares_out", as_of, None, hi, entity) or []
    mcaps = fetch_fact(conn, "price.mcap", as_of, None, hi, entity) or []

    first, last = prices[0][0], prices[-1][0]
    actions: list[dict[str, Any]] = []
    for step in _share_steps(shares):
        if step["known_at"] and step["known_at"] > as_of:
            continue
        if not ((lo or first) < step["ex_date"] <= (hi or last)):
            continue                      # an action before the window is in both ends
        step = dict(step)
        step["close_ratio"] = _close_break(prices, step["ex_date"])
        ratio, brk = step["ratio"], step["close_ratio"]
        if brk is not None and abs(brk * ratio - 1.0) <= 0.12:
            step["raw_break"] = True      # the stored close still carries the break
        elif (step["clean"] and ratio > 1
              and (brk is None or abs(brk - 1.0) <= 0.20)):
            step["raw_break"] = False     # already adjusted, and the factor is a clean one
        else:
            # A ratio below 1 with no price lift is a share-count/unit correction; a
            # 1.3x-1.7x "near 4/3" step with no break is an issue/rights, not a split.
            continue
        actions.append(step)

    unresolved: list[dict[str, Any]] = []
    for (_, p0), (d1, p1) in zip(prices, prices[1:]):
        if not p0 or not p1 or d1 <= (lo or first):
            continue
        change = 100.0 * (p1 / p0 - 1.0)
        if change > -SPLIT_JUMP_PCT:
            continue
        explained = any(0 <= _days_between(d1, step["ex_date"]) <= 7 for step in actions)
        if not explained:
            unresolved.append({"date": d1, "change_pct": round(change, 2)})

    series = list(prices)
    applied = False
    for step in sorted(actions, key=lambda item: item["ex_date"]):
        if step.get("raw_break"):
            factor = 1.0 / step["ratio"]
            series = [(day, value * factor if day < step["ex_date"] else value)
                      for day, value in series]
            applied = True

    # Evidence order: the row's own basis dim, a held step that did NOT break the
    # close (build-adjusted), a raw break adjusted here, then the T1 panel fallback
    # for a store that predates the basis dim.
    has_panel = bool(shares) and bool(mcaps)
    already_adjusted = any(step.get("raw_break") is False for step in actions)
    adjusted = ((explicit and stated == {"adjusted"}) or already_adjusted or applied
                or (not explicit and has_panel and not actions))
    notes: list[str] = []
    if actions:
        named = "; ".join(
            f"{step['kind']} on {step['ex_date']}, ratio {step['ratio']:g} "
            f"(share count x{step['ratio']:g})" for step in actions)
        notes.append(f"basis: adjusted close; adjusted for {named}")
    elif adjusted:
        notes.append(f"basis: {ADJUSTED_CLOSE}")
        if not explicit:
            notes.append("the store's price.close carries no basis dim for this window "
                         "and the panel's close is build_t1.py's adjusted series")
        notes.append("no split/bonus in the window, so raw equals adjusted for "
                     "splits and bonuses")
    else:
        notes.append(f"basis: {RAW_CLOSE} (price.close)")
        if want_adjusted:
            notes.append("no split/bonus in the window, so raw equals adjusted for "
                         "splits and bonuses")
    notes.append("dividends are not adjusted")
    if total_return:
        notes[-1] = "dividends are not adjusted: this is a price return, not a total return"
    return PriceBasis(series=series, rows=[dict(row) for row in source.values()],
                      actions=actions, unresolved=unresolved, adjusted=adjusted,
                      note="; ".join(notes))


def _price_nid(part: Part, window: dict[str, Any], basis: PriceBasis, as_of: str,
               entity: str | None = None) -> Result:
    jump = basis.unresolved[0]
    why = (f"an unidentified corporate action on {jump['date']} (close "
           f"{jump['change_pct']:+.2f}%) has no held split/bonus ratio, so a return "
           f"across it would be false")
    if basis.actions:
        held = "; ".join(f"{step['kind']} on {step['ex_date']}, ratio {step['ratio']:g}"
                         for step in basis.actions)
        why += f" (the window's held action is adjusted: {held})"
    return _nid(part, window, why,
                [_tried("fact", f"price.close, entity={entity or part.entity or 'asked'}, "
                                f"window={window.get('from')}..{window.get('to')}",
                        len(basis.series), as_of),
                 _tried("fact", "price.shares_out: no persisting step at "
                                f"{jump['date']}, so no ratio is held", 0, as_of)],
                "hold the corporate action (kind, ratio, ex-date) in "
                "corporate_action_class and re-run; do not guess the ratio")


def _with_price_basis(result: Result, basis: PriceBasis) -> Result:
    result.assumption = basis.note
    result.numbers = dict(result.numbers or {}, price_basis=("adjusted" if basis.adjusted
                                                             else "raw"),
                          price_actions=basis.actions)
    return result


def _numeric_series(rows: Iterable[Mapping[str, Any]]) -> list[tuple[str, float]]:
    out: list[tuple[str, float]] = []
    for row in rows:
        number = _num(row.get("value"))
        day = _day(row.get("period_end") or row.get("period_start"))
        if number is not None and day:
            out.append((day, number))
    return sorted(out)


def _period_return(rows: Iterable[Mapping[str, Any]]) -> float | None:
    series = _numeric_series(rows)
    if len(series) < 2 or not series[0][1]:
        return None
    return series[-1][1] / series[0][1] - 1.0


def _execute_formula(conn: Any, part: Part, as_of: str, lo: str | None, hi: str | None,
                     entity: str | None, window: dict[str, Any],
                     registry: Mapping[str, Any]) -> Result:
    fid = str(part.formula)
    spec = _formula_row(registry, fid)
    fn = FORMULAS.get(fid)
    if fn is None:
        return _nid(part, window, f"formula {fid} has no executor implementation",
                    [_tried("registry", f"formula {fid}", 0, as_of)],
                    "add the formula to execute.FORMULAS")
    atoms = [str(atom) for atom in (spec.get("over") or [])]
    atoms += [atom for atom in FORMULA_EXTRA_ATOMS.get(fid, []) if atom not in atoms]
    if not atoms:
        return _nid(part, window, f"formula {fid} declares no input atoms",
                    [_tried("registry", f"formula {fid} over=[]", 0, as_of)],
                    "the registry formula row needs its `over` atoms")
    if not entity:
        # A formula is one company's arithmetic: with no resolved entity every input
        # would come from whichever company's row sorted last (§A.2, §C.2).
        owners: set[str] = set()
        for atom in atoms:
            found = fetch_fact(conn, atom, as_of, lo, hi) or []
            carried_here = carried_dims(found)
            # The close's basis is a request to the price layer, never a row filter.
            wanted = ({key: value for key, value in part.dims.items() if key != "basis"}
                      if atom == "price.close" else part.dims)
            for row in found:
                if _dim_match(row, wanted, carried_here):
                    owners.add(str(row.get("entity_id")))
        if len(owners) > 1:
            return _nid(part, window,
                        f"the ask names no single entity and {len(owners)} entities carry "
                        f"the inputs of {fid} at {as_of}",
                        [_tried("fact", f"formula {fid}, entity=None, window={lo}..{hi}",
                                len(owners), as_of)],
                        "resolve the entity PIT (§C.2) before executing a formula part")
        if len(owners) == 1:
            # Every input row comes from one entity: its ISIN is the formula's owner, and
            # the answer can carry it (a one-entity fixture has no resolver).
            entity = next(iter(owners))
    basis: PriceBasis | None = None
    if "price.close" in atoms and entity and conn is not None:
        basis = price_basis(
            conn, as_of, lo, hi, entity,
            want_adjusted=str(part.dims.get("basis") or "").lower() == "adjusted",
            total_return=str(part.dims.get("total_return") or "").lower()
            in ("yes", "true", "1"))
        if basis is not None and basis.unresolved:
            return _price_nid(part, window, basis, as_of, entity)
    values: dict[str, Any] = {}
    series: dict[str, list[dict[str, Any]]] = {}
    used: list[dict[str, Any]] = []
    missing: list[str] = []
    for atom in atoms:
        if atom == "price.close" and basis is not None:
            rows = _price_rows(basis, entity)
            series[atom] = rows
            latest = rows[-1]
            values[atom] = _num(latest.get("value"))
            used.append({"atom": atom, "value": values[atom],
                         "period": latest.get("period_end"),
                         "known_at": _day(latest.get("known_at")),
                         "source_ref": latest.get("source_ref")})
            continue
        rows = fetch_fact(conn, atom, as_of, lo, hi, entity) if conn is not None else None
        if rows is None:
            return _nid(part, window, "the fact view is absent",
                        [_tried("fact", f"atom {atom}", None, as_of)],
                        "WP2a fact_view.sql (§H.2)")
        carried = carried_dims(rows)
        rows = [row for row in rows if _dim_match(row, part.dims, carried)]
        series[atom] = rows
        latest = _one_latest(rows)
        if latest is None:
            missing.append(atom)
            continue
        values[atom] = _num(latest.get("value"))
        used.append({"atom": atom, "value": values[atom],
                     "period": _day(latest.get("period_end")),
                     "known_at": _day(latest.get("known_at")),
                     "source_ref": latest.get("source_ref")})
    if missing and fid not in ("f.margin", "f.ratio", "f.share_of", "f.cagr",
                               "f.excess_return", "f.net", "f.spread",
                               "f.per_rupee_revenue"):
        return _nid(part, window,
                    f"formula {fid} needs {', '.join(missing)}, not held for "
                    f"{entity or 'the asked entity'} in the window at {as_of}",
                    [_tried("fact", f"atom {atom}", 0, as_of) for atom in missing],
                    f"hold {', '.join(missing)} for this entity (§H.2 fact view)")
    # Series-shaped inputs the price/return formulas need (§A.3).
    closes = _numeric_series(series.get("price.close") or [])
    if closes:
        values["_max_close"] = max(number for _, number in closes)
        if len(closes) >= 2 and closes[0][1]:
            values["_company_return"] = closes[-1][1] / closes[0][1] - 1.0
    if len(closes) >= 2:
        from datetime import date
        values["_start"], values["_end"] = closes[0][1], closes[-1][1]
        days = (date.fromisoformat(closes[-1][0]) - date.fromisoformat(closes[0][0])).days
        values["_years"] = max(days / 365.25, 1.0 / 365.0)
    opens = _numeric_series(series.get("price.open") or [])
    if opens and closes:
        earlier = [number for day, number in closes if day < opens[-1][0]]
        if earlier:
            values["_prev_close"] = earlier[-1]
    if fid == "f.gap_pct" and basis is not None and opens:
        # The gap compares a raw open with a close that is adjusted for capital
        # actions: on the ex-date itself the two are on different bases.
        if any(step["ex_date"] == opens[-1][0] for step in basis.actions):
            return _nid(part, window,
                        f"the open on {opens[-1][0]} is an ex-date for a held "
                        f"{basis.actions[0]['kind']} (ratio "
                        f"{basis.actions[0]['ratio']:g}); a gap against the adjusted "
                        f"previous close would be false",
                        [_tried("fact", f"price.open/price.close on {opens[-1][0]}", 1,
                                as_of)],
                        "compare the raw open with a raw previous close on the ex-date")
    benchmark = part.dims.get("benchmark_isin") or part.dims.get("benchmark")
    if benchmark and conn is not None:
        bench = fetch_fact(conn, "macro.index_close", as_of, lo, hi, str(benchmark)) or []
        bench_return = _period_return(bench)
        if bench_return is not None:
            values["_benchmark_return"] = bench_return
            used.append({"atom": f"benchmark:{benchmark}", "value": bench_return,
                         "period": _day((_latest(bench) or {}).get("period")),
                         "known_at": _day((_latest(bench) or {}).get("known_at")),
                         "source_ref": (_latest(bench) or {}).get("source_ref")})
    capex = _numeric_series(series.get("fin.capex") or [])
    revenue = _numeric_series(series.get("fin.revenue") or [])
    if len(capex) >= 2 and len(revenue) >= 2:
        values["_delta_capex"] = capex[-1][1] - capex[0][1]
        values["_delta_revenue"] = revenue[-1][1] - revenue[0][1]
    try:
        used_atoms = formula_inputs(fid, part.dims)
        number = fn(values, part.dims)
    except KeyError as exc:
        need = str(exc).strip("'\"")
        if need.startswith("_") or need.startswith("dims."):
            why = (f"formula {fid} cannot be computed: {need}; "
                   f"missing: {', '.join(missing) or 'no rows in the window'}")
            to_close = f"hold {', '.join(atoms)} for this entity in the window"
        else:
            why = (f"formula {fid} needs {need}, not held for "
                   f"{entity or 'the asked entity'} in the window at {as_of}")
            to_close = f"hold {need} for this entity (§H.2 fact view)"
        return _nid(part, window, why,
                    [_tried("fact", f"atom {atom}", 1 if atom not in missing else 0, as_of)
                     for atom in atoms], to_close)
    except (ZeroDivisionError, TypeError) as exc:
        return _nid(part, window, f"formula {fid} cannot be computed: {exc}",
                    [_tried("fact", f"atom {atom}", 1, as_of) for atom in atoms],
                    "the formula needs the dim that selects its input "
                    "(margin_kind/ratio_kind/est_atom/atoms/output_atom)")
    if not isinstance(number, (int, float)) or number != number:
        return _nid(part, window, f"formula {fid} produced a non-numeric value",
                    [_tried("fact", f"atom {atom}", 1, as_of) for atom in atoms],
                    "check the formula's declared inputs")
    # A share of a whole cannot exceed the whole: a segment table and a revenue series
    # on different periods or units do produce one (MB0974#MI: 4,357.91%), and that is
    # a data mismatch, not a ratio.
    if fid == "f.share_of" and number > 100.0 + 1e-9:
        part_row = next((row for row in used if row["atom"] == used_atoms[0]), {})
        whole_row = next((row for row in used if row["atom"] == used_atoms[-1]), {})
        return _nid(part, window,
                    f"f.share_of computed {number:,.2f}%: the part "
                    f"({used_atoms[0]} {part_row.get('value')} at {part_row.get('period')}) "
                    f"is not a part of the whole ({used_atoms[-1]} "
                    f"{whole_row.get('value')} at {whole_row.get('period')}): a share of a "
                    f"whole cannot exceed 100%, so the inputs do not form one whole",
                    [_tried("fact", f"atom {atom}", 1, as_of) for atom in used_atoms],
                    f"hold {used_atoms[0]} and {used_atoms[-1]} for the same period and "
                    f"unit before taking a share")
    # Only the inputs this answer used, in the order the formula reads them (so the
    # answer's period is the last input the arithmetic actually touches).
    order = {atom: index for index, atom in enumerate(used_atoms)}
    used = sorted((row for row in used
                   if row["atom"] in used_atoms or str(row["atom"]).startswith("benchmark:")),
                  key=lambda row: order.get(row["atom"], len(order)))
    primary = [row for row in used if row["atom"] in used_atoms]
    known = max((row.get("known_at") or "") for row in used)
    selector = ""
    if fid == "f.ratio":
        selector = f"({part.dims.get('ratio_kind') or 'de'})"
    elif fid == "f.margin":
        selector = f"({part.dims.get('margin_kind') or 'ebitda'})"
    result = Result(part_index=part.index, atom=part.atom, formula=part.formula,
                    dims=part.dims, window=window, operator=part.operator,
                    shape=part.shape, answer_type="measured", value=round(number, 6),
                    unit=FORMULA_UNIT.get(fid) or spec.get("unit"),
                    period=(primary[-1]["period"] if primary else used[-1]["period"]),
                    isin=entity,
                    source_ref=f"derived:{fid}{selector}:{'+'.join(used_atoms)}",
                    known_at=known, inputs=used,
                    numbers={"formula": fid, "expr": spec.get("expr"),
                             "inputs_used": used_atoms,
                             "missing_inputs": missing})
    if fid == "f.ratio":
        result.numbers["ratio_kind"] = str(part.dims.get("ratio_kind") or "de")
    elif fid == "f.margin":
        result.numbers["margin_kind"] = str(part.dims.get("margin_kind") or "ebitda")
    return _with_price_basis(result, basis) if basis is not None else result


# ---------------------------------------------------------------------------
# the three judgement rules with no extra store (§A.4)
# ---------------------------------------------------------------------------
def _rule_gap_type(conn, part, as_of, lo, hi, entity):
    opens = [row for row in (fetch_fact(conn, "price.open", as_of, lo, hi, entity) or [])
             if _dim_match(row, part.dims)]
    closes = [row for row in (fetch_fact(conn, "price.close", as_of, lo, hi, entity) or [])
              if _dim_match(row, part.dims)]
    if not opens or len(closes) < 2:
        raise _Empty()
    open_row = opens[-1]
    day = _day(open_row.get("period_end"))
    previous = [row for row in closes if (_day(row.get("period_end")) or "") < (day or "")]
    if not previous:
        raise _Empty()
    prev = _num(previous[-1].get("value"))
    opn = _num(open_row.get("value"))
    if not prev or opn is None:
        raise _Empty()
    # A gap divides a raw open by a previous close.  When the store's close is the
    # build's adjusted series, the two are on different bases; if a held action has
    # already moved the adjusted close, the gap would be false and is refused.
    basis = close_basis(conn, closes)
    if basis == "adjusted":
        trail = price_basis(conn, as_of, None, day, entity)
        if trail is not None and trail.actions:
            raise _Missing(
                f"the previous close ({prev}) is the {ADJUSTED_CLOSE} and the open "
                f"({opn}) is raw: {len(trail.actions)} held action(s) already adjusted "
                f"the close, so the gap ratio {opn / prev:g} mixes two bases",
                "compare the raw open with a raw previous close: rebuild the fact view "
                "from company_state_daily.raw_close (fact_view.sql)")
    ratio = opn / prev
    verdict = "gap up" if ratio > 1.01 else "gap down" if ratio < 0.99 else "flat"
    return (verdict, {"open": opn, "prev_close": prev, "ratio": round(ratio, 6),
                      "date": day, "thresholds": "1.01 / 0.99",
                      "prev_close_basis": basis or "unstated"},
            "gap up if open > prev_close*1.01; gap down if < *0.99; else flat",
            day, prev, open_row.get("source_ref"))


def _rule_control_change(conn, part, as_of, lo, hi, entity):
    rows = [row for row in (fetch_fact(conn, "hold.pct", as_of, lo, hi, entity) or [])]
    if not rows:
        raise _Empty()
    by_class: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        holder = parse_dims(row.get("dims")).get("holder_class")
        if holder:
            by_class.setdefault(holder, []).append(row)
    moves: dict[str, float] = {}
    for holder, series in by_class.items():
        series.sort(key=lambda row: _day(row.get("period_end")) or "")
        if len(series) < 2:
            continue
        before, after = _num(series[-2].get("value")), _num(series[-1].get("value"))
        if before is not None and after is not None:
            moves[holder] = round(after - before, 4)
    if not moves:
        raise _Empty()
    change = any(abs(delta) >= 5.0 for delta in moves.values())
    promoter_drop = moves.get("promoter", 0.0) <= -5.0
    verdict = ("control change" if change or promoter_drop else "no control change")
    used = (_latest(rows) or {})
    return (verdict, {"moves_pp": moves, "threshold_pp": 5.0}, 
            "control change if any holder class moves >=5pp in one quarter, or "
            "promoter falls >=5pp", _day(used.get("period_end")),
            _num(used.get("value")), used.get("source_ref"))


def _rule_solvency(conn, part, as_of, lo, hi, entity):
    numbers: dict[str, Any] = {}
    missing: list[str] = []

    def latest(atom: str) -> float | None:
        rows = fetch_fact(conn, atom, as_of, lo, hi, entity) or []
        return _num((_latest(rows) or {}).get("value"))

    def ratio(atom: str, base: str) -> float | None:
        top, bottom = latest(atom), latest(base)
        if top is None or not bottom:
            return None
        return top / bottom

    pledge = latest("hold.pledge_pct")
    numbers["pledge"] = pledge
    if pledge is None:
        missing.append("hold.pledge_pct")
    de = ratio("fin.total_debt", "fin.book_equity")
    numbers["de"] = de
    if de is None:
        missing.append("D/E (fin.total_debt, fin.book_equity)")
    icr = ratio("fin.ebitda", "fin.interest_expense")
    numbers["icr"] = icr
    if icr is None:
        missing.append("interest cover (fin.ebitda, fin.interest_expense)")
    breaches = []
    if pledge is not None and pledge > 15.0:
        breaches.append("promoter pledge > 15%")
    if icr is not None and icr < 2.5:
        breaches.append("interest cover < 2.5x")
    if de is not None and de > 1.5:
        breaches.append("D/E > 1.5x")
    if missing and not breaches:
        verdict = "undetermined"
    else:
        verdict = "fail" if breaches else "pass"
    numbers["breaches"] = breaches
    numbers["missing"] = missing
    return (verdict, numbers,
            "fail if pledge > 15% or interest cover < 2.5x or D/E > 1.5x", None, None,
            "fact")


RULES = {"gap_type": _rule_gap_type, "control_change": _rule_control_change,
         "solvency": _rule_solvency}


def _execute_rule(conn: Any, part: Part, as_of: str, lo: str | None, hi: str | None,
                  entity: str | None, window: dict[str, Any]) -> Result:
    rule = str(part.rule or part.dims.get("rule_id") or part.dims.get("rule") or "")
    fn = RULES.get(rule)
    if fn is None:
        why = (f"judgement ask names no declared rule (§A.4 has 14 rule rows)"
               if not rule else f"rule {rule} has no executor implementation")
        return _nid(part, window, why,
                    [_tried("registry", f"rule {rule or '(unnamed)'}", 0, as_of)],
                    "add the rule to the registry and to execute.RULES (§A.4)")
    try:
        verdict, numbers, stated, period, value, source_ref = fn(
            conn, part, as_of, lo, hi, entity)
    except _Empty:
        return _nid(part, window, f"rule {rule} has no rows for "
                    f"{entity or 'the asked entity'} in the window at {as_of}",
                    [_tried("fact", f"rule {rule}", 0, as_of)],
                    "hold the atoms the rule declares (see the registry's rule row)")
    if verdict == "undetermined":
        return _nid(part, window,
                    f"rule {rule} cannot reach a verdict: missing "
                    f"{', '.join(map(str, numbers.get('missing') or []))}",
                    [_tried("fact", f"rule {rule}", 0, as_of)],
                    "hold the missing atoms so the rule's stated test can run")
    return Result(part_index=part.index, atom=part.atom, formula=part.formula,
                  dims=part.dims, window=window, operator="rule", shape="verdict",
                  answer_type="measured", verdict=verdict, value=value,
                  unit=None, period=period, isin=entity, source_ref=source_ref,
                  known_at=as_of, rule_used=stated, numbers=numbers)


# ---------------------------------------------------------------------------
# the one entry point
# ---------------------------------------------------------------------------
def _last_session(conn: Any, day: str) -> str | None:
    """The last trading session on or before ``day``, from the store's session atoms."""
    if conn is None:
        return None
    column = fact_atom_column(conn)
    rows = db_rows(conn,
                   f"SELECT MAX(period_end) AS session FROM fact "
                   f"WHERE {column} IN ('price.high', 'price.open', 'price.close') "
                   f"AND substr(period_end, 1, 10) <= ?", (day,))
    return _day(rows[0].get("session")) if rows and rows[0].get("session") else None


def execute(part: Any, as_of: str, conn: Any = None, *, windows: Sequence[Any] | None = None,
            entity: str | None = None, entities: Sequence[str] | None = None,
            registry: Any = None, proxy: Mapping[str, Any] | None = None,
            part_index: int | None = None) -> Result:
    """Execute one part; always exactly one :class:`Result`, never an exception.

    ``proxy`` is the only way a proxy can enter: it is used only after the held
    stores returned nothing, and it carries its own approval state.
    """
    p = as_part(part, part_index)
    lo, hi = _window_bounds(p.window, windows)
    basis = _window_basis(p.window, windows)
    reg = _registry(registry)
    assumed: list[str] = []
    grain = "" if _passage_like(p) else _grain_of(p, reg)
    if grain == "day" and lo and hi and lo == hi and conn is not None:
        # A named date with no session (a Sunday, a holiday) snaps to the last session
        # that actually traded, and the answer says which one (§D.2).
        session = _last_session(conn, hi)
        if session and session != hi:
            assumed.append(f"{hi} is not a trading session; used the last session {session}")
            lo = hi = session
    if lo and hi and lo == hi and not _passage_like(p):
        opening = _period_start(basis, hi)
        if basis in PERIOD_END_BASES:
            # "Q1FY27"/"FY26": the named date IS the period's end, so the reading is that
            # period only.  An older period is a different period, never a fallback: a
            # named period with no row stays a typed NID.
            lo = opening or hi
        elif grain == "day" and opening:
            # "the Q1 high": a quarter-end reading over a day-grain series is the quarter.
            lo = opening
        elif grain and grain != "day":
            # A one-day window is the document/event date for a quarterly or FY reading: it
            # bounds the value's date (known_at is cut at as_of), not its period_end.
            lo = None
    if str(p.dims.get("lag") or "").lower() == "ytd" and hi and not _passage_like(p):
        # "YTD high": the year of the asked date to that date, never the whole history.
        lo = f"{hi[:4]}-01-01"
        assumed.append(f"YTD window {lo}..{hi}")
        if p.atom == "price.high" and p.operator in ("value_at", "last_visible"):
            p.operator = "max_with_date"
        elif p.atom == "price.low" and p.operator in ("value_at", "last_visible"):
            p.operator = "min_with_date"
    window = _window_dict(lo, hi)
    entity = p.entity or entity or (p.entities[0] if p.entities else None)
    entity_set = list(entities or p.entities or [])
    try:
        result = _dispatch(p, as_of, conn, window, lo, hi, entity, entity_set, reg,
                           basis=basis)
    except _Empty:
        result = _empty_result(p, as_of, conn, window, lo, hi, entity, reg)
    except _Missing as exc:
        result = _nid(p, window, exc.why,
                      [_tried("executor", p.measure or "?", None, as_of)],
                      exc.to_close)
    except Exception as exc:  # noqa: BLE001 - one bug must not cost the whole ask
        result = _nid(p, window, f"executor error: {type(exc).__name__}: {exc}",
                      [_tried("executor", p.measure or "?", None, as_of)],
                      "fix the executor for this part")
    if (result.answer_type == "measured" and basis in LATEST_BASES and lo is None
            and p.operator in ("value_at", "last_visible") and not _passage_like(p)):
        cut = hi or as_of   # an open window's right edge is the run date
        limit, klass = latest_limit(p.measure, reg)
        age = _age_days(result.period, cut)
        if age is not None and age > limit:
            # A years-old row is not "latest": say what the newest row is, how old, and
            # the limit it broke.  (Measured filing lags set the limits; see
            # LATEST_LIMIT_DAYS.)
            result = _nid(
                p, window,
                f"the latest {p.measure} is {result.period}, {age} days before {cut}: past "
                f"the {limit}-day {klass} staleness limit for a latest reading",
                [_tried("fact", f"{p.measure}, latest row {result.period} ({age} days "
                                f"before {cut}); limit {limit}", 1, as_of)],
                f"hold a {p.measure} row for this entity within {limit} days of {cut} "
                f"({klass} staleness limit)")
        else:
            age_text = f", {age} days before {cut}" if age is not None else ""
            assumed.append(
                f"latest {p.measure} known by {cut}: period {result.period}{age_text}, "
                f"filed {result.known_at or '—'}; {klass} staleness limit {limit} days")
    if (result.answer_type == "measured" and result.value is None
            and result.verdict is None and result.operator != "list_distinct"
            and not result.entities
            and result.shape not in ("series", "ranked_list", "passage", "path",
                                     "estimate")):
        # A value that cannot be stated is not a measurement: print a typed failure,
        # never "—" under a measured block (MB0525).
        result = _nid(
            p, window,
            f"{p.measure or p.operator} produced no value that can be stated: the "
            f"operator returned rows but no scalar for this window",
            [_tried("fact", f"atom={p.atom}, formula={p.formula}, window={lo}..{hi}", 0,
                    as_of)],
            "narrow the ask to one value (entity/period) or ask for the series")
    if assumed:
        result.assumption = "; ".join([part for part in [result.assumption, *assumed]
                                       if part])
    if result.answer_type == "not_in_data" and proxy:
        result = _proxy(p, window, proxy, result.tried, result.nid_reason)
    return result


def _window_basis(window: Any, windows: Sequence[Any] | None) -> str:
    if isinstance(window, int) and windows and 0 <= window < len(windows):
        window = windows[window]
    return str(window.get("basis") or "") if isinstance(window, Mapping) else ""


def _period_start(basis: str, end: str) -> str | None:
    """The opening date a "quarter end"/"fiscal year end" reading closes."""
    from datetime import date
    try:
        day = date.fromisoformat(end)
    except ValueError:
        return None
    if basis == "quarter end":
        month = day.month - ((day.month - 1) % 3)
        return date(day.year, month, 1).isoformat()
    if basis in ("fiscal year end", "year end"):
        start_year = day.year if day.month >= 4 else day.year - 1
        return date(start_year, 4, 1).isoformat()
    return None


def _grain_of(part: Part, registry: Mapping[str, Any]) -> str:
    """The grain of the part's atom (or of every formula input when they agree)."""
    atoms = [str(part.atom)] if part.atom else [
        str(atom) for atom in (_formula_row(registry, part.formula).get("over") or [])]
    grains = {str(_atom_row(registry, atom).get("grain") or "") for atom in atoms}
    return grains.pop() if len(grains) == 1 else ""


def _passage_like(part: Part) -> bool:
    return (part.operator in ("walk", "rule") or part.judgement
            or part.atom in ("claim.claim", "text.passage", "own.estimate")
            or part.shape in ("passage", "path", "estimate"))


def _dispatch(p: Part, as_of: str, conn: Any, window: dict[str, Any], lo: str | None,
              hi: str | None, entity: str | None, entities: Sequence[str],
              registry: Mapping[str, Any], basis: str = "") -> Result:
    if p.operator == "walk":
        return _execute_walk(conn, p, as_of, entity, window, entities)
    if p.operator == "rule" or p.judgement:
        return _execute_rule(conn, p, as_of, lo, hi, entity, window)
    if p.atom == "own.estimate":
        return _execute_estimate(conn, p, as_of, lo, hi, entity, window)
    if p.atom in ("claim.claim", "text.passage") or p.shape == "passage":
        return _execute_claim(conn, p, as_of, entity, window)
    if p.operator == "near_high":
        return _execute_near_high(conn, p, as_of, lo, hi, entity, window)
    if p.formula:
        return _execute_formula(conn, p, as_of, lo, hi, entity, window, registry)
    atom = str(p.atom or "")
    if not atom:
        return _nid(p, window, "the part names no atom or formula",
                    [_tried("registry", "empty part", 0, as_of)],
                    "the decomposer must emit one measure per part (§C.1)")
    registry_atom = _atom_row(registry, atom)
    if str(registry_atom.get("entity_key") or "").startswith("series_code"):
        # A macro series is keyed by its series code, not by a company ISIN: a question
        # that names a company still reads the series (its company link is a later hop).
        entity = None
    if atom.startswith("absent.") or (registry_atom.get("coverage") == "absent"):
        return _nid(p, window,
                    registry_atom.get("coverage_note") or "nothing publishes this measure",
                    [_tried("registry", f"atom {atom} is declared absent", 0, as_of)],
                    registry_atom.get("source") or "not fetchable; it is declared absent")
    if conn is None:
        return _nid(p, window, "no database connection was supplied",
                    [_tried("fact", f"atom {atom} not queried", None, as_of)],
                    "pass the pilot store connection")
    rows = fetch_fact(conn, atom, as_of, lo, hi, entity or None,
                      entities if p.operator in ("rank", "screen", "compare") else None)
    if rows is None:
        return _nid(p, window, "the fact view is not built in this store",
                    [_tried("fact", "view absent", None, as_of)],
                    "WP2a fact_view.sql (§H.2)")
    carried = carried_dims(rows)
    unserved = _unserved(p.dims, carried)
    if unserved:
        dim, value = unserved
        return _nid(p, window,
                    f"the ask names {dim}={value}, but the {atom} rows are not "
                    f"{dim}-keyed in this store; answering would pass a different "
                    f"{dim} off as the asked one",
                    [_tried("fact", f"atom={atom}, {dim}={value}, window={lo}..{hi}",
                            len(rows), as_of)],
                    f"hold a {dim}-keyed {atom} source (§H.2 fact view)")
    rows = [row for row in rows if _dim_match(row, p.dims, carried)]
    rows = _apply_soft(rows, p.dims)
    rows = _apply_defaults(rows, p.dims, registry, lo, hi, basis,
                           _grain_of(p, registry))
    split = _unnamed_split(rows, p.dims) if p.operator in SCALAR_ONE else []
    if split:
        # A one-value ask over several readings of a dim it never named would answer
        # with whichever reading sorted last: refuse to pick one silently (§A.2).
        return _nid(p, window,
                    f"the ask names no {split[0]}; the unit of the answer is ambiguous",
                    [_tried("fact", f"atom={atom}, dims={split}, window={lo}..{hi}",
                            len(rows), as_of)],
                    f"name the reading ({split[0]}) or ask for the series (§A.2 default)")
    if entity is None and p.operator in SCALAR_ONE:
        owners = {str(row.get("entity_id")) for row in rows}
        if len(owners) > 1:
            # A one-value operator over many entities would answer with whichever row
            # sorted last: a silent wrong company.  Say the entity is unresolved.
            return _nid(p, window,
                        f"the ask names no single entity and {len(owners)} entities carry "
                        f"{atom} at {as_of}",
                        [_tried("fact", f"atom={atom}, entity=None, window={lo}..{hi}",
                                len(rows), as_of)],
                        "resolve the entity PIT (§C.2) before executing a one-value part")
        if len(owners) == 1:
            entity = next(iter(owners))
    if not rows:
        why = f"no {atom} row for {entity or 'the asked entity'}"
        if lo or hi:
            why += f" in {lo or '…'}..{hi or '…'}"
        why += f" after PIT at {as_of}"
        if registry_atom.get("coverage") in ("gap", "absent"):
            why += f"; {registry_atom.get('coverage_note')}"
        return _nid(p, window, why,
                    [_tried("fact", f"atom={atom}, entity={entity}, window={lo}..{hi}", 0,
                            as_of)],
                    registry_atom.get("source") or
                    f"hold {atom} for this entity (§H.2 fact view)")
    values = _series(rows, p.dims)
    basis: PriceBasis | None = None
    if (atom == "price.close"
            and p.operator in ("change", "pct_change", "growth")):
        owner = entity
        owners = {str(row.get("entity_id")) for row in rows if row.get("entity_id")}
        if owner is None:
            if len(owners) > 1:
                return _nid(p, window,
                            f"the ask names no single entity and {len(owners)} entities "
                            f"carry {atom} at {as_of}; a return across them would be false",
                            [_tried("fact", f"atom={atom}, entity=None, window={lo}..{hi}",
                                    len(rows), as_of)],
                            "resolve the entity PIT (§C.2) before a window return")
            owner = next(iter(owners), None)
        if owner:
            basis = price_basis(
                conn, as_of, lo, hi, owner,
                want_adjusted=str(p.dims.get("basis") or "").lower() == "adjusted",
                total_return=str(p.dims.get("total_return") or "").lower()
                in ("yes", "true", "1"))
            if basis is not None and basis.unresolved:
                return _price_nid(p, window, basis, as_of, owner)
            if basis is not None:
                rows = _price_rows(basis, owner)
                values = _series(rows, p.dims)
    op = OPERATORS.get(str(p.operator or "value_at"))
    if op is None:
        return _nid(p, window, f"operator {p.operator} is outside the closed set (§A.4)",
                    [_tried("fact", f"atom={atom}", len(rows), as_of)],
                    "use one of the 26 registered operators")
    ctx = {"window": window, "conn": conn, "as_of": as_of, "lo": lo, "hi": hi,
           "entity": entity, "entities": entities}
    if (p.operator in SCALAR_ONE
            and any(str(value).lower() == "each" for value in p.dims.values())):
        # "each" is a multi-reading dim (§A.2): never pick one reading silently.
        result = _op_series(p, values, ctx)
        result.numbers = dict(result.numbers or {}, each_readings=True)
        return _with_close_basis(result, conn, values) if atom == "price.close" else result
    result = op(p, values, ctx)
    if result.answer_type == "measured" and result.unit is None:
        result.unit = registry_atom.get("unit")
    if basis is not None:
        return _with_price_basis(result, basis)
    if atom == "price.close":
        return _with_close_basis(result, conn, values)
    return result


def _empty_result(p: Part, as_of: str, conn: Any, window: dict[str, Any], lo: str | None,
                  hi: str | None, entity: str | None,
                  registry: Mapping[str, Any]) -> Result:
    atom = str(p.atom or "")
    registry_atom = _atom_row(registry, atom)
    if registry_atom.get("coverage") in ("gap", "absent"):
        why = (f"no {atom} row for {entity or 'the asked entity'} after PIT at {as_of}; "
               f"{registry_atom.get('coverage_note')}")
    else:
        why = (f"no {atom} row for {entity or 'the asked entity'}"
               f"{f' in {lo or chr(8230)}..{hi or chr(8230)}' if (lo or hi) else ''} "
               f"after PIT at {as_of}")
    return _nid(p, window, why,
                [_tried("fact", f"atom={atom}, entity={entity}, window={lo}..{hi}", 0, as_of)],
                registry_atom.get("source") or
                f"hold {atom} for this entity (§H.2 fact view)")


def execute_ask(ask: Mapping[str, Any], conn: Any = None, *, registry: Any = None,
                proxies: Mapping[int, Mapping[str, Any]] | None = None,
                entity: str | None = None) -> list[Result]:
    """Run every part of a typed Ask (§C.1); thin convenience for the controller."""
    as_of = str(ask.get("as_of") or "")
    windows = ask.get("windows") or []
    parts = ask.get("parts") or []
    if entity is None:
        for item in ask.get("entities") or []:
            if isinstance(item, Mapping) and item.get("isin"):
                entity = str(item["isin"])
                break
    return [execute(part, as_of, conn, windows=windows, entity=entity, registry=registry,
                    proxy=(proxies or {}).get(index), part_index=index)
            for index, part in enumerate(parts)]
