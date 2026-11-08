"""T-135: a named calc catalog the answering model calls instead of doing arithmetic in its head.

The 8-9 Nov re-asks still lost marks on hand arithmetic: a TTM/fiscal-year growth written 14.12% (right 14.15%),
a TTM compared with the fiscal year it overlaps (KEC-081), a six-month balance change set against a year-on-year
flow (MARUTI-023), a cash-flow figure ten times too large (ETERNAL-020), ROCE given as a level instead of the
incremental return (HINDUNILVR-031), a range position called "upper half" at 41% up it (BAJFINANCE-123), a Gordon
fair P/B done backwards (HDFCBANK-120), a quarter not split out of the cumulative (SBILIFE-081), a half-year
return called unannualised (SBILIFE-105) and margin points added straight onto a PAT target (ETERNAL-113).

Every named formula does its arithmetic once, with units, and refuses a comparison whose spans do not line up,
so an answer quotes ``value`` and cites ``formula`` and ``inputs``.  Reply shape, every formula::

    {"formula_id", "value", "unit", "formula": "<numbers substituted>", "inputs": {...}, "notes": [...]}

or ``{"error": "<reason>", "formula_id"}``.  Percent inputs parse to fractions and percent outputs stay percent
points (14.15, not 0.1415).  Pure functions: no database, no files, no network.  Parsing and unit-aware
``Fraction`` arithmetic come from ``calc``; price maths stays in ``lookups_tech`` and is listed as
``see tech kind=...``.
"""
from __future__ import annotations

import json
import re
from fractions import Fraction
from typing import Any

import calc
import lookups_tech

# --- numbers and replies -----------------------------------------------------------------------------


def _num(value: Fraction | float | int, places: int = 6) -> int | float:
    """A JSON number: an integer when exact, else a float at ``places`` decimals."""
    if isinstance(value, Fraction) and value.denominator == 1:
        return int(value)
    return round(float(value), places)


def _fmt(value: Fraction | float | int, places: int = 2) -> str:
    return f"{float(value):,.{places}f}"


def _pct_text(points: Fraction | float | int, places: int = 2) -> str:
    """``14.147...`` (percent points) -> ``"14.15%"``."""
    return f"{_fmt(points, places)}%"


def _display(value: Fraction, unit: str) -> str:
    if unit == "rupees":
        return f"Rs {calc.indian_grouping(value)}"
    if unit == "count":
        return calc.indian_grouping(value, 0)
    return _fmt(value)


def _money_fields(value: Fraction | float | int) -> dict[str, Any]:
    fraction = value if isinstance(value, Fraction) else Fraction(str(value))
    return {"rupees": _num(fraction), "crore": _num(fraction / 10 ** 7),
            "lakh_crore": _num(fraction / 10 ** 12), "indian": calc.indian_grouping(fraction),
            "display": f"Rs {calc.indian_grouping(fraction)}"}


def _echo(inputs: dict[str, Any]) -> dict[str, Any]:
    """The inputs as parsed: ``{"given": "22,067 crore", "value": 220670000000, "unit": "rupees"}``."""
    out: dict[str, Any] = {}
    for key, raw in inputs.items():
        try:
            value, unit = calc.parse_input(raw)
        except calc.CalcError:
            out[key] = {"given": raw}
            continue
        item: dict[str, Any] = {"given": raw, "value": _num(value), "unit": unit or "plain"}
        if unit == "percent":
            item["percent"] = _num(value * 100)
        out[key] = item
    return out


def _reply(formula_id: str, value: Fraction | float, unit: str, formula: str,
           inputs: dict[str, Any], notes: list[str] | None = None, **extra: Any) -> dict[str, Any]:
    out: dict[str, Any] = {"formula_id": formula_id, "value": _num(value), "unit": unit,
                           "formula": formula, "inputs": _echo(inputs), "notes": notes or []}
    if unit == "rupees":
        out.update(_money_fields(value))
    out.update(extra)
    return out


# --- input access ------------------------------------------------------------------------------------


def _raw(inputs: dict[str, Any], key: str) -> Any:
    value = inputs.get(key)
    if value is None or value == "":
        raise calc.CalcError(f"missing input {key!r}; give a number such as '1,208 crore' or a percent '14.5%'")
    return value


def _parsed(inputs: dict[str, Any], key: str) -> tuple[Any, Fraction, str]:
    raw = _raw(inputs, key)
    try:
        value, unit = calc.parse_input(raw)
    except calc.CalcError as exc:
        raise calc.CalcError(f"{key}: {exc}") from exc
    return raw, value, unit


def _pct(inputs: dict[str, Any], key: str) -> Fraction:
    """A percent input, as the fraction ``calc`` parses ("14.5%" -> 29/200).  A bare 14.5 is refused."""
    raw = _raw(inputs, key)
    value, unit = calc.parse_input(raw)
    if unit != "percent":
        raise calc.CalcError(f"{key} must be a percent such as '14.5%' or '12%', not {raw!r}")
    return value


def _ratio(inputs: dict[str, Any], key: str) -> Fraction:
    raw = _raw(inputs, key)
    value, unit = calc.parse_input(raw)
    if unit not in ("", "ratio"):
        raise calc.CalcError(f"{key} must be a plain number or a multiple such as '1.85x', not {raw!r}")
    return value


def _months(inputs: dict[str, Any], key: str) -> int:
    raw = _raw(inputs, key)
    value, unit = calc.parse_input(raw)
    if unit not in ("", "count") or value.denominator != 1 or value <= 0:
        raise calc.CalcError(f"{key} must be a positive whole number of months, not {raw!r}")
    return int(value)


def _strict_unit(pairs: list[tuple[Fraction, str]], what: str) -> str:
    """One unit family, or refuse: mixing ``"632 crore"`` with ``"366 crore"`` and a bare ``366`` is a slip."""
    units = {unit for _value, unit in pairs if unit}
    bare = sum(1 for _value, unit in pairs if not unit)
    if len(units) > 1:
        raise calc.CalcError(f"{what} mix units {sorted(units)}; give every value one unit family (e.g. all in "
                             f"crore)")
    if units and bare:
        raise calc.CalcError(f"{what}: {bare} value(s) carry no unit while the rest are in "
                             f"{sorted(units)}; give every value the same unit")
    return units.pop() if units else ""


# --- period labels -----------------------------------------------------------------------------------

_ISO = re.compile(r"^(\d{4})-(\d{2})(?:-\d{2})?$")
_QUARTER = re.compile(r"^Q([1-4])FY(\d{2}|\d{4})$")
_FY = re.compile(r"^FY(\d{2}|\d{4})$")
_CUMULATIVE = re.compile(r"^(H1|H2|9M)FY(\d{2}|\d{4})$")
# A fiscal year ends in March; Q1/Q2/Q3 end in the previous calendar year.  (offset, month) per quarter.
_QUARTER_MONTHS = {1: (0, 6), 2: (0, 9), 3: (0, 12), 4: (1, 3)}


def _calendar(tag: str) -> int:
    return 2000 + int(tag) if len(tag) == 2 else int(tag)


def _clean(label: Any) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(label).upper())


def _point(label: Any) -> tuple[int, int]:
    """The (year, month) a period ends: Q2FY27 -> (2026, 9), FY26 -> (2026, 3)."""
    raw = str(label).strip()
    date = _ISO.match(raw)
    if date:
        return int(date.group(1)), int(date.group(2))
    text = _clean(raw)
    quarter = _QUARTER.match(text)
    if quarter:
        end = _calendar(quarter.group(2))
        offset, month = _QUARTER_MONTHS[int(quarter.group(1))]
        return end - 1 + offset, month
    fiscal = _FY.match(text)
    if fiscal:
        return _calendar(fiscal.group(1)), 3
    cumulative = _CUMULATIVE.match(text)
    if cumulative:
        end = _calendar(cumulative.group(2))
        span = cumulative.group(1)
        return (end - 1, 9) if span == "H1" else (end, 3) if span == "H2" else (end - 1, 12)
    raise calc.CalcError(f"period label {label!r} is not one I can read; use Q2FY27, 9MFY26, H1FY26, FY26 or "
                         f"2026-03-31")


def _span_months(before_label: Any, now_label: Any) -> int:
    before, now = _point(before_label), _point(now_label)
    months = 12 * (now[0] - before[0]) + (now[1] - before[1])
    if months <= 0:
        raise calc.CalcError(f"the labels are out of order: {before_label!r} is not before {now_label!r}")
    return months


def _quarter_index(fy_end: int, quarter: int) -> int:
    return fy_end * 4 + quarter - 1


def _quarter_text(index: int) -> str:
    return f"Q{index % 4 + 1}FY{index // 4 % 100:02d}"


def _fy_of(label: Any) -> int:
    match = re.search(r"FY(\d{2}|\d{4})", _clean(label))
    if not match:
        raise calc.CalcError(f"no fiscal year in the period label {label!r}")
    return _calendar(match.group(1))


def _quarter_of(label: Any) -> int:
    match = _QUARTER.match(_clean(label))
    if not match:
        raise calc.CalcError(f"{label!r} is not a quarter label such as Q1FY27")
    return _quarter_index(_calendar(match.group(2)), int(match.group(1)))


def _quarters(label: Any) -> list[int]:
    """The quarter indexes a period covers: FY26 -> four quarters, 9MFY26 -> three, a TTM -> the four it ends on."""
    text = _clean(label)
    ttm = text.startswith("TTM")
    if not ttm:
        fiscal = _FY.match(text)
        if fiscal:
            base = _quarter_index(_calendar(fiscal.group(1)), 4) - 3
            return [base, base + 1, base + 2, base + 3]
        quarter = _QUARTER.match(text)
        if quarter:
            return [_quarter_of(text)]
        cumulative = _CUMULATIVE.match(text)
        if cumulative:
            end = _calendar(cumulative.group(2))
            span = cumulative.group(1)
            if span == "H1":
                return [_quarter_index(end, 1), _quarter_index(end, 2)]
            if span == "H2":
                return [_quarter_index(end, 3), _quarter_index(end, 4)]
            return [_quarter_index(end, 1), _quarter_index(end, 2), _quarter_index(end, 3)]
        raise calc.CalcError(f"period label {label!r} is not one I can read; use TTM Q2FY27, FY26, 9MFY26, H1FY26 "
                             f"or Q2FY27")
    text = text[3:]
    quarter = _QUARTER.match(text)
    if not quarter:
        raise calc.CalcError(f"a TTM label needs its ending quarter, as in 'TTM Q2FY27', not {label!r}")
    end = _quarter_index(_calendar(quarter.group(2)), int(quarter.group(1)))
    return [end - 3, end - 2, end - 1, end]


def _label(inputs: dict[str, Any], *names: str) -> Any:
    for name in names:
        value = inputs.get(name)
        if value is not None and value != "":
            return value
    raise calc.CalcError(f"missing period label; give {' or '.join(names)}")


def _opt_label(inputs: dict[str, Any], *names: str) -> Any:
    for name in names:
        value = inputs.get(name)
        if value is not None and value != "":
            return value
    return None


# --- 1. GROWTH ---------------------------------------------------------------------------------------


def _growth(inputs: dict[str, Any]) -> dict[str, Any]:
    now_raw, now, now_unit = _parsed(inputs, "now")
    before_raw, before, before_unit = _parsed(inputs, "before")
    _strict_unit([(now, now_unit), (before, before_unit)], "now and before")
    if before <= 0:
        raise calc.CalcError(f"cannot compute growth from before={before_raw!r}: the base is zero or negative. "
                             f"Give the absolute change, or state that the base is negative and a percentage is "
                             f"not meaningful")
    points = (now / before - 1) * 100
    return _reply("GROWTH", points, "percent",
                  f"100 * ({now_raw} / {before_raw} - 1) = {_pct_text(points)}", inputs,
                  [f"unrounded {_fmt(points, 4)}%; {_pct_text(points)} is the same figure at 2 decimals"])


# --- 2. TTM_SUM --------------------------------------------------------------------------------------


def _period_labels(inputs: dict[str, Any]) -> list[Any]:
    periods = inputs.get("periods")
    if periods is None:
        periods = [inputs.get(f"p{index}") for index in (1, 2, 3, 4)]
    if isinstance(periods, str):
        parts = [part.strip() for part in periods.split(",")] if "," in periods else [periods]
        periods = parts
    if not isinstance(periods, (list, tuple)) or len(periods) != 4 or any(p is None or p == "" for p in periods):
        raise calc.CalcError("TTM_SUM needs the four quarter labels: periods=[\"Q1FY27\", \"Q2FY27\", \"Q3FY27\", "
                             "\"Q4FY27\"] or p1..p4")
    return list(periods)


def _ttm_sum(inputs: dict[str, Any]) -> dict[str, Any]:
    quarters = [_parsed(inputs, key) for key in ("q1", "q2", "q3", "q4")]
    unit = _strict_unit([(value, value_unit) for _raw_value, value, value_unit in quarters], "the four quarters")
    labels = _period_labels(inputs)
    indexes = [_quarter_of(label) for label in labels]
    if any(second != first + 1 for first, second in zip(indexes, indexes[1:])):
        raise calc.CalcError(f"the periods {', '.join(str(label) for label in labels)} are not four consecutive "
                             f"quarters")
    total = sum((value for _raw_value, value, _value_unit in quarters), Fraction(0))
    text = " + ".join(str(raw_value) for raw_value, _value, _value_unit in quarters)
    return _reply("TTM_SUM", total, unit or "number", f"{text} = {_display(total, unit)}", inputs,
                  [f"trailing twelve months {labels[0]} to {labels[-1]}"],
                  periods=[str(label) for label in labels])


# --- 3. TTM_GROWTH -----------------------------------------------------------------------------------


def _ttm_growth(inputs: dict[str, Any]) -> dict[str, Any]:
    now_raw, now, now_unit = _parsed(inputs, "ttm_now")
    before_raw, before, before_unit = _parsed(inputs, "ttm_year_ago")
    _strict_unit([(now, now_unit), (before, before_unit)], "ttm_now and ttm_year_ago")
    if before <= 0:
        raise calc.CalcError(f"cannot compute TTM growth from ttm_year_ago={before_raw!r}: the base is zero or "
                             f"negative, so no percentage is meaningful")
    label_now = _opt_label(inputs, "period_now", "p_now")
    label_before = _opt_label(inputs, "period_before", "p_before")
    if (label_now is None) != (label_before is None):
        raise calc.CalcError("give both period_now and period_before, or neither")
    extra: dict[str, Any] = {}
    if label_now is not None and label_before is not None:
        span_now, span_before = _quarters(label_now), _quarters(label_before)
        if len(span_now) != len(span_before):
            raise calc.CalcError(f"cannot compare {label_now!r} ({len(span_now)} quarter(s)) with "
                                 f"{label_before!r} ({len(span_before)} quarter(s)): give two periods of the same "
                                 f"length")
        overlap = sorted(set(span_now) & set(span_before))
        if overlap:
            names = ", ".join(_quarter_text(index) for index in overlap)
            raise calc.CalcError(f"{label_now!r} and {label_before!r} overlap in {names}, so this compares a "
                                 f"trailing-twelve-month figure with a fiscal year it over-counts (KEC-081); "
                                 f"compare the TTM with the TTM a year earlier, or the year with the year before")
        extra = {"period_now": label_now, "period_before": label_before}
    points = (now / before - 1) * 100
    return _reply("TTM_GROWTH", points, "percent",
                  f"100 * ({now_raw} / {before_raw} - 1) = {_pct_text(points)}", inputs,
                  [f"unrounded {_fmt(points, 4)}%; {_pct_text(points)} is the same figure at 2 decimals"], **extra)


# --- 4. Q_FROM_CUMULATIVE ----------------------------------------------------------------------------

_CUMULATIVE_PAIRS = {("FY", "9M"): ("Q4", 4), ("9M", "H1"): ("Q3", 3), ("H1", "Q1"): ("Q2", 2)}


def _cumulative_kind(label: Any) -> str:
    text = _clean(label)
    if _FY.match(text):
        return "FY"
    if text.startswith("9MFY"):
        return "9M"
    if text.startswith("H1FY"):
        return "H1"
    quarter = _QUARTER.match(text)
    if quarter:
        if quarter.group(1) != "1":
            raise calc.CalcError(f"{label!r}: only Q1 can be the shorter piece (H1 - Q1 = Q2)")
        return "Q1"
    raise calc.CalcError(f"period label {label!r} is not one I can read; use FY26, 9MFY26, H1FY26 or Q1FY26")


def _q_from_cumulative(inputs: dict[str, Any]) -> dict[str, Any]:
    longer_raw, longer, longer_unit = _parsed(inputs, "longer")
    shorter_raw, shorter, shorter_unit = _parsed(inputs, "shorter")
    _strict_unit([(longer, longer_unit), (shorter, shorter_unit)], "longer and shorter")
    longer_label = _label(inputs, "longer_label", "longer_period")
    shorter_label = _label(inputs, "shorter_label", "shorter_period")
    pair = _CUMULATIVE_PAIRS.get((_cumulative_kind(longer_label), _cumulative_kind(shorter_label)))
    if pair is None:
        raise calc.CalcError(f"cannot split {shorter_label!r} out of {longer_label!r}: FY - 9M = Q4, "
                             f"9M - H1 = Q3 and H1 - Q1 = Q2")
    if _fy_of(longer_label) != _fy_of(shorter_label):
        raise calc.CalcError(f"{longer_label!r} and {shorter_label!r} are in different fiscal years")
    residual = longer - shorter
    quarter, _number = pair
    label = f"{quarter}FY{_fy_of(longer_label) % 100:02d}"
    return _reply("Q_FROM_CUMULATIVE", residual, longer_unit or "number",
                  f"{longer_label} ({_display(longer, longer_unit)}) - {shorter_label} "
                  f"({_display(shorter, shorter_unit)}) = {_display(residual, longer_unit)} ({label})", inputs,
                  [f"the residual period is {label}"], period=label)


# --- 5. SHARE ----------------------------------------------------------------------------------------


def _share(inputs: dict[str, Any]) -> dict[str, Any]:
    part_raw, part, part_unit = _parsed(inputs, "part")
    total_raw, total, total_unit = _parsed(inputs, "total")
    _strict_unit([(part, part_unit), (total, total_unit)], "part and total")
    if total == 0:
        raise calc.CalcError("cannot take a share of zero: total is 0")
    points = part / total * 100
    return _reply("SHARE", points, "percent",
                  f"100 * ({part_raw} / {total_raw}) = {_pct_text(points)}", inputs)


# --- 6. CONTRIBUTION_TO_INCREASE ---------------------------------------------------------------------


def _contribution(inputs: dict[str, Any]) -> dict[str, Any]:
    part_now_raw, part_now, part_now_unit = _parsed(inputs, "part_now")
    part_before_raw, part_before, part_before_unit = _parsed(inputs, "part_before")
    total_now_raw, total_now, total_now_unit = _parsed(inputs, "total_now")
    total_before_raw, total_before, total_before_unit = _parsed(inputs, "total_before")
    part_unit = _strict_unit([(part_now, part_now_unit), (part_before, part_before_unit)],
                             "part_now and part_before")
    total_unit = _strict_unit([(total_now, total_now_unit), (total_before, total_before_unit)],
                              "total_now and total_before")
    if part_unit and total_unit and part_unit != total_unit:
        raise calc.CalcError(f"the part is in {part_unit} and the total in {total_unit}; give both the same unit")
    change = total_now - total_before
    if change == 0:
        raise calc.CalcError("the total did not change (total_now equals total_before), so no part can explain its "
                             "increase")
    points = (part_now - part_before) / change * 100
    return _reply("CONTRIBUTION_TO_INCREASE", points, "percent",
                  f"100 * (({part_now_raw} - {part_before_raw}) / ({total_now_raw} - {total_before_raw})) = "
                  f"{_pct_text(points)}", inputs,
                  [f"the part changed by {_display(part_now - part_before, part_unit)} and the total by "
                   f"{_display(change, total_unit)}"])


# --- 7. CASH_CONVERSION ------------------------------------------------------------------------------


def _cash_conversion(inputs: dict[str, Any]) -> dict[str, Any]:
    ocf_raw, ocf, ocf_unit = _parsed(inputs, "ocf")
    pat_raw, pat, pat_unit = _parsed(inputs, "pat")
    ebitda_raw, ebitda, ebitda_unit = _parsed(inputs, "ebitda")
    _strict_unit([(ocf, ocf_unit), (pat, pat_unit), (ebitda, ebitda_unit)], "ocf, pat and ebitda")
    if pat == 0:
        raise calc.CalcError("pat is zero, so ocf/pat is undefined")
    if ebitda == 0:
        raise calc.CalcError("ebitda is zero, so ocf/ebitda is undefined")
    to_pat = ocf / pat
    to_ebitda = ocf / ebitda
    return _reply("CASH_CONVERSION", to_pat, "x",
                  f"ocf/pat = {ocf_raw} / {pat_raw} = {_fmt(to_pat, 3)}x; ocf/ebitda = {ocf_raw} / {ebitda_raw}"
                  f" = {_fmt(to_ebitda, 3)}x", inputs,
                  [f"operating cash flow is {_fmt(to_pat, 3)}x PAT and {_fmt(to_ebitda, 3)}x EBITDA"],
                  values={"ocf_to_pat": _num(to_pat), "ocf_to_ebitda": _num(to_ebitda)})


# --- 8. INCREMENTAL_ROCE -----------------------------------------------------------------------------


def _incremental_roce(inputs: dict[str, Any]) -> dict[str, Any]:
    ebit_now_raw, ebit_now, ebit_now_unit = _parsed(inputs, "ebit_now")
    ebit_before_raw, ebit_before, ebit_before_unit = _parsed(inputs, "ebit_before")
    capital_now_raw, capital_now, capital_now_unit = _parsed(inputs, "capital_employed_now")
    capital_before_raw, capital_before, capital_before_unit = _parsed(inputs, "capital_employed_before")
    ebit_unit = _strict_unit([(ebit_now, ebit_now_unit), (ebit_before, ebit_before_unit)],
                             "ebit_now and ebit_before")
    capital_unit = _strict_unit([(capital_now, capital_now_unit), (capital_before, capital_before_unit)],
                                "capital_employed_now and capital_employed_before")
    if ebit_unit and capital_unit and ebit_unit != capital_unit:
        raise calc.CalcError(f"EBIT is in {ebit_unit} and capital employed in {capital_unit}; give both the same "
                             f"unit")
    change = capital_now - capital_before
    if change <= 0:
        raise calc.CalcError(f"capital employed did not increase ({capital_before_raw!r} -> {capital_now_raw!r}), "
                             f"so incremental ROCE (change in EBIT over change in capital employed) is undefined; "
                             f"report the level ROCE and the change in capital instead")
    points = (ebit_now - ebit_before) / change * 100
    return _reply("INCREMENTAL_ROCE", points, "percent",
                  f"100 * (({ebit_now_raw} - {ebit_before_raw}) / ({capital_now_raw} - {capital_before_raw})) = "
                  f"{_pct_text(points)}", inputs,
                  [f"the incremental return on the {_display(change, capital_unit)} added, not the level ROCE"])


# --- 9. RANGE_POSITION -------------------------------------------------------------------------------


def _range_position(inputs: dict[str, Any]) -> dict[str, Any]:
    x_raw, x, x_unit = _parsed(inputs, "x")
    low_raw, low, low_unit = _parsed(inputs, "low")
    high_raw, high, high_unit = _parsed(inputs, "high")
    _strict_unit([(x, x_unit), (low, low_unit), (high, high_unit)], "x, low and high")
    if high <= low:
        raise calc.CalcError(f"high {high_raw!r} is not above low {low_raw!r}, so there is no range to position in")
    fraction = (x - low) / (high - low)
    third = ("lower third" if fraction < Fraction(1, 3)
             else "middle third" if fraction < Fraction(2, 3) else "upper third")
    points = fraction * 100
    return _reply("RANGE_POSITION", points, "percent",
                  f"100 * ({x_raw} - {low_raw}) / ({high_raw} - {low_raw}) = {_pct_text(points)}: {third}", inputs,
                  [f"{x_raw} is {_pct_text(points)} up the {low_raw}-{high_raw} range, in the {third}"],
                  third=third)


# --- 10. FAIR_PB / IMPLIED_ROE -----------------------------------------------------------------------


def _fair_pb(inputs: dict[str, Any]) -> dict[str, Any]:
    roe = _pct(inputs, "roe")
    cost = _pct(inputs, "cost_of_equity")
    growth = _pct(inputs, "growth")
    if cost <= growth:
        raise calc.CalcError(f"cost of equity {_pct_text(cost * 100)} must exceed growth {_pct_text(growth * 100)} "
                             f"for the Gordon model; the fair P/B would be negative or infinite")
    if roe < growth:
        raise calc.CalcError(f"roe {_pct_text(roe * 100)} is below growth {_pct_text(growth * 100)}: the Gordon "
                             f"model gives no positive fair P/B")
    fair = (roe - growth) / (cost - growth)
    return _reply("FAIR_PB", fair, "x",
                  f"(roe - g) / (coe - g) = ({_pct_text(roe * 100)} - {_pct_text(growth * 100)}) / "
                  f"({_pct_text(cost * 100)} - {_pct_text(growth * 100)}) = {_fmt(fair)}x", inputs,
                  ["fair P/B = (ROE - g) / (cost of equity - g)"])


def _implied_roe(inputs: dict[str, Any]) -> dict[str, Any]:
    pb = _ratio(inputs, "pb")
    cost = _pct(inputs, "cost_of_equity")
    growth = _pct(inputs, "growth")
    if cost <= growth:
        raise calc.CalcError(f"cost of equity {_pct_text(cost * 100)} must exceed growth {_pct_text(growth * 100)}")
    if pb <= 0:
        raise calc.CalcError(f"pb must be positive, not {inputs.get('pb')!r}")
    roe = pb * (cost - growth) + growth
    return _reply("IMPLIED_ROE", roe * 100, "percent",
                  f"roe = pb * (coe - g) + g = {inputs.get('pb')} * ({_pct_text(cost * 100)} - "
                  f"{_pct_text(growth * 100)}) + {_pct_text(growth * 100)} = {_pct_text(roe * 100)}", inputs,
                  ["implied ROE = P/B * (cost of equity - g) + g"])


# --- 11. IMPLIED_GROWTH_PE ---------------------------------------------------------------------------


def _implied_growth(inputs: dict[str, Any]) -> dict[str, Any]:
    pe = _ratio(inputs, "pe")
    payout = _pct(inputs, "payout")
    cost = _pct(inputs, "cost_of_equity")
    if pe <= 0:
        raise calc.CalcError(f"pe must be positive, not {inputs.get('pe')!r}")
    if payout < 0:
        raise calc.CalcError("payout must not be negative")
    if cost <= 0:
        raise calc.CalcError("cost of equity must be positive")
    growth = (pe * cost - payout) / (pe + payout)
    notes = ["from PE = payout * (1 + g) / (r - g): g = (PE * r - payout) / (PE + payout)"]
    if growth >= cost:
        notes.append(f"implied growth {_pct_text(growth * 100)} is at or above the cost of equity "
                     f"{_pct_text(cost * 100)}; the inputs are inconsistent")
    return _reply("IMPLIED_GROWTH_PE", growth * 100, "percent",
                  f"g = (PE * r - payout) / (PE + payout) = ({inputs.get('pe')} * {_pct_text(cost * 100)} - "
                  f"{_pct_text(payout * 100)}) / ({inputs.get('pe')} + {_pct_text(payout * 100)}) = "
                  f"{_pct_text(growth * 100)}", inputs, notes)


# --- 12. ANNUALISE -----------------------------------------------------------------------------------


def _annualise(inputs: dict[str, Any]) -> dict[str, Any]:
    rate = _pct(inputs, "rate")
    months = _months(inputs, "months")
    method = str(_raw(inputs, "method")).strip().lower()
    if method not in ("simple", "compound"):
        raise calc.CalcError(f"method must be 'simple' or 'compound', not {inputs.get('method')!r}")
    if method == "simple":
        annual = rate * 12 / months
    else:
        annual = Fraction(str((1 + float(rate)) ** (12 / months) - 1))
    points = annual * 100
    return _reply("ANNUALISE", points, "percent",
                  f"{_pct_text(rate * 100)} over {months} months, {method} annualisation: "
                  f"{_pct_text(points)}", inputs,
                  [f"{_pct_text(rate * 100)} over {months} months is {_pct_text(points)} annualised ({method}); "
                   f"the figure is a full-year rate, never a half-year one"],
                  label="annualised")


# --- 13. SAME_SPAN_GROWTH ----------------------------------------------------------------------------


def _same_span_growth(inputs: dict[str, Any]) -> dict[str, Any]:
    balance_now_raw, balance_now, balance_now_unit = _parsed(inputs, "balance_now")
    balance_before_raw, balance_before, balance_before_unit = _parsed(inputs, "balance_before")
    flow_now_raw, flow_now, flow_now_unit = _parsed(inputs, "flow_now")
    flow_before_raw, flow_before, flow_before_unit = _parsed(inputs, "flow_before")
    balance_unit = _strict_unit([(balance_now, balance_now_unit), (balance_before, balance_before_unit)],
                                "balance_now and balance_before")
    flow_unit = _strict_unit([(flow_now, flow_now_unit), (flow_before, flow_before_unit)],
                             "flow_now and flow_before")
    if balance_unit and flow_unit and balance_unit != flow_unit:
        raise calc.CalcError(f"the balance is in {balance_unit} and the flow in {flow_unit}; give both the same unit")
    balance_now_label = _label(inputs, "balance_now_label", "balance_now_period")
    balance_before_label = _label(inputs, "balance_before_label", "balance_before_period")
    flow_now_label = _label(inputs, "flow_now_label", "flow_now_period")
    flow_before_label = _label(inputs, "flow_before_label", "flow_before_period")
    balance_months = _span_months(balance_before_label, balance_now_label)
    flow_months = _span_months(flow_before_label, flow_now_label)
    if balance_months != flow_months:
        raise calc.CalcError(f"the balance change covers {balance_months} months ({balance_before_label!r} -> "
                             f"{balance_now_label!r}) but the flow covers {flow_months} months "
                             f"({flow_before_label!r} -> {flow_now_label!r}); set a balance change against a flow "
                             f"over the same span (MARUTI-023), e.g. both year-on-year")
    if balance_before <= 0:
        raise calc.CalcError(f"cannot compute balance growth from {balance_before_raw!r}: the base is zero or "
                             f"negative")
    if flow_before <= 0:
        raise calc.CalcError(f"cannot compute flow growth from {flow_before_raw!r}: the base is zero or negative")
    balance_growth = (balance_now / balance_before - 1) * 100
    flow_growth = (flow_now / flow_before - 1) * 100
    return _reply("SAME_SPAN_GROWTH", balance_growth, "percent",
                  f"both over {balance_months} months: balance 100 * ({balance_now_raw} / "
                  f"{balance_before_raw} - 1) = {_pct_text(balance_growth)}; flow 100 * ({flow_now_raw} / "
                  f"{flow_before_raw} - 1) = {_pct_text(flow_growth)}", inputs,
                  [f"balance growth {_pct_text(balance_growth)} and flow growth {_pct_text(flow_growth)} over the "
                   f"same {balance_months} months"],
                  values={"balance_growth_pct": _num(balance_growth), "flow_growth_pct": _num(flow_growth)},
                  span_months=balance_months)


# --- 14. PROFIT_BRIDGE_MARGIN ------------------------------------------------------------------------


def _profit_bridge_margin(inputs: dict[str, Any]) -> dict[str, Any]:
    pat_raw, pat, pat_unit = _parsed(inputs, "target_pat")
    revenue_raw, revenue, revenue_unit = _parsed(inputs, "revenue")
    tax = _pct(inputs, "tax_rate")
    depreciation_raw, depreciation, depreciation_unit = _parsed(inputs, "depreciation")
    finance_raw, finance, finance_unit = _parsed(inputs, "finance_cost")
    other_raw, other, other_unit = _parsed(inputs, "other_income")
    unit = _strict_unit([(pat, pat_unit), (revenue, revenue_unit), (depreciation, depreciation_unit),
                         (finance, finance_unit), (other, other_unit)],
                        "target_pat, revenue, depreciation, finance_cost and other_income")
    if tax >= 1:
        raise calc.CalcError(f"tax_rate {_pct_text(tax * 100)} must be below 100%")
    if tax < 0:
        raise calc.CalcError(f"tax_rate {_pct_text(tax * 100)} must not be negative")
    if revenue <= 0:
        raise calc.CalcError(f"revenue {revenue_raw!r} must be positive")
    ebitda = pat / (1 - tax) + depreciation + finance - other
    margin = ebitda / revenue * 100
    extras: dict[str, Any] = {"ebitda": _num(ebitda)}
    if unit == "rupees":
        extras["ebitda_crore"] = _num(ebitda / 10 ** 7)
    return _reply("PROFIT_BRIDGE_MARGIN", margin, "percent",
                  f"EBITDA = {pat_raw} / (1 - {_pct_text(tax * 100)}) + {depreciation_raw} + {finance_raw} - "
                  f"{other_raw} = {_display(ebitda, unit)}; margin = {_display(ebitda, unit)} / {revenue_raw} = "
                  f"{_pct_text(margin)}", inputs,
                  ["EBITDA = target PAT / (1 - tax) + depreciation + finance cost - other income; "
                   "margin = EBITDA / revenue"], **extras)


# --- registry and entry point ------------------------------------------------------------------------

_CATALOG: dict[str, dict[str, Any]] = {
    "GROWTH": {"fn": _growth, "inputs": ("now", "before"), "unit": "percent",
               "summary": "100*(now/before-1); refuses a zero or negative base"},
    "TTM_SUM": {"fn": _ttm_sum, "inputs": ("q1", "q2", "q3", "q4", "periods"), "unit": "rupees",
                "summary": "sum four quarters; refuses labels that are not four consecutive quarters"},
    "TTM_GROWTH": {"fn": _ttm_growth,
                   "inputs": ("ttm_now", "ttm_year_ago", "period_now", "period_before"), "unit": "percent",
                   "summary": "TTM growth; refuses periods that overlap (KEC-081)"},
    "Q_FROM_CUMULATIVE": {"fn": _q_from_cumulative,
                          "inputs": ("longer", "longer_label", "shorter", "shorter_label"), "unit": "rupees",
                          "summary": "FY-9M=Q4, 9M-H1=Q3, H1-Q1=Q2"},
    "SHARE": {"fn": _share, "inputs": ("part", "total"), "unit": "percent", "summary": "100*part/total"},
    "CONTRIBUTION_TO_INCREASE": {"fn": _contribution,
                                 "inputs": ("part_now", "part_before", "total_now", "total_before"),
                                 "unit": "percent", "summary": "share of the total's change the part explains"},
    "CASH_CONVERSION": {"fn": _cash_conversion, "inputs": ("ocf", "pat", "ebitda"), "unit": "x",
                        "summary": "ocf/pat and ocf/ebitda; one unit family for all three"},
    "INCREMENTAL_ROCE": {"fn": _incremental_roce,
                         "inputs": ("ebit_now", "ebit_before", "capital_employed_now",
                                    "capital_employed_before"), "unit": "percent",
                         "summary": "100*change in EBIT / change in capital employed"},
    "RANGE_POSITION": {"fn": _range_position, "inputs": ("x", "low", "high"), "unit": "percent",
                       "summary": "(x-low)/(high-low) and lower/middle/upper third"},
    "FAIR_PB": {"fn": _fair_pb, "inputs": ("roe", "cost_of_equity", "growth"), "unit": "x",
                "summary": "Gordon (roe-g)/(coe-g)"},
    "IMPLIED_ROE": {"fn": _implied_roe, "inputs": ("pb", "cost_of_equity", "growth"), "unit": "percent",
                    "summary": "roe = pb*(coe-g)+g"},
    "IMPLIED_GROWTH_PE": {"fn": _implied_growth, "inputs": ("pe", "payout", "cost_of_equity"), "unit": "percent",
                          "summary": "g = (PE*r - payout)/(PE + payout)"},
    "ANNUALISE": {"fn": _annualise, "inputs": ("rate", "months", "method"), "unit": "percent",
                  "summary": "simple or compound; the reply always says 'annualised'"},
    "SAME_SPAN_GROWTH": {"fn": _same_span_growth,
                         "inputs": ("balance_now", "balance_before", "flow_now", "flow_before",
                                    "balance_now_label", "balance_before_label", "flow_now_label",
                                    "flow_before_label"), "unit": "percent",
                         "summary": "balance and flow growth; refuses different spans (MARUTI-023)"},
    "PROFIT_BRIDGE_MARGIN": {"fn": _profit_bridge_margin,
                             "inputs": ("target_pat", "revenue", "tax_rate", "depreciation", "finance_cost",
                                        "other_income"), "unit": "percent",
                             "summary": "EBITDA margin needed for a target PAT (ETERNAL-113)"},
}


def list_formulas() -> dict[str, Any]:
    """Every formula id with its inputs, plus the price maths that lives in ``lookups_tech``."""
    formulas = [{"formula_id": formula_id, "inputs": list(entry["inputs"]), "unit": entry["unit"],
                 "summary": entry["summary"]} for formula_id, entry in _CATALOG.items()]
    return {"ok": True, "count": len(formulas), "ids": [item["formula_id"] for item in formulas],
            "formulas": formulas, "tech": [f"see tech kind={kind}" for kind in lookups_tech.KINDS],
            "note": "14 numbered entries; FAIR_PB and IMPLIED_ROE are the two directions of the Gordon relation "
                    "and are separate ids.  Price maths is not re-implemented here: call tech with that kind."}


def run(args: dict[str, Any]) -> dict[str, Any]:
    """``{"name": "<id>", "inputs": {...}}`` -> the formula reply, or ``{"error", "formula_id"}``."""
    name = args.get("name")
    if name is None or name == "":
        return {"error": "give name=<formula id>; name=list lists every formula", "formulas": list(_CATALOG)}
    key = str(name).strip().upper()
    if key in ("LIST", "ALL", "CATALOG"):
        return list_formulas()
    entry = _CATALOG.get(key)
    if entry is None:
        return {"error": f"unknown formula {name!r}; choose from {', '.join(_CATALOG)}",
                "formulas": list(_CATALOG)}
    inputs = args.get("inputs")
    if isinstance(inputs, str):
        try:
            inputs = json.loads(inputs)
        except ValueError:
            return {"error": f"inputs is not JSON: {inputs!r}", "formula_id": key}
    if inputs is None:
        inputs = {}
    if not isinstance(inputs, dict):
        return {"error": "inputs must be a JSON object of name: value", "formula_id": key}
    flat = {name: value for name, value in args.items() if name not in ("name", "inputs")}
    merged: dict[str, Any] = {**flat, **inputs}
    try:
        return entry["fn"](merged)
    except calc.CalcError as exc:
        return {"error": str(exc), "formula_id": key}
