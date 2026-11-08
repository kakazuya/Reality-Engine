"""Arithmetic for the ``pilot3_calc`` tool: an expression walked from its AST, never ``eval`` (T-072).

A worker's head sum and its ten-times unit slip were 31 of the 120 answer misses in the 600-answer run.  The
tool takes one expression over ``+ - * / **`` and parentheses (plus ``sum``, ``avg``, ``min``, ``max``,
``round``) and optional named inputs with their units, normalises every value to its base unit ONCE (rupees,
count, or a fraction for a percent) and computes exactly with ``Fraction``.  A unit mistake is therefore an
error with a message, never a wrong number: subtracting a count from rupees, or multiplying two rupees, fails.

A money or count result is also printed in crore, lakh crore and Indian digit grouping -- the 32.20 lakh crore
for 3.22 lakh crore and the 3.18 crore for 31.8 crore slips the run made.

    >>> evaluate("pat / revenue * 100", {"pat": "493 crore", "revenue": "23506 crore"})["value"]
    2.0973...
"""
from __future__ import annotations

import ast
import re
from fractions import Fraction
from typing import Any

# A power is an exact integer loop; anything bigger is a typo, not a calculation.
MAX_EXPONENT = 64
MAX_LENGTH = 2000
FUNCS = ("sum", "avg", "min", "max", "round")

# Rupees per unit word.  A scale word must be its own token, so "mn" in a sentence is not read here: the input
# unit is a short label ("crore"), not prose.
_SCALE = {"thousand": 10 ** 3, "k": 10 ** 3, "lakh": 10 ** 5, "lac": 10 ** 5, "million": 10 ** 6,
          "mn": 10 ** 6, "mio": 10 ** 6, "crore": 10 ** 7, "cr": 10 ** 7, "billion": 10 ** 9, "bn": 10 ** 9,
          "trillion": 10 ** 12, "lakh_crore": 10 ** 12, "lakh_cr": 10 ** 12}
_COUNT = ("share", "shares", "count", "unit", "units", "number", "nos", "no", "person", "persons", "holder",
          "holders", "day", "days", "month", "months", "year", "years", "session", "sessions", "customer",
          "customers", "employee", "employees", "branch", "branches", "order", "orders", "tonne", "tonnes")
_PCT = ("percent", "percentage", "pct", "%")
_RATIO = ("x", "times", "ratio")
_INPUT = re.compile(
    r"^\s*(?P<cur>INR|Rs\.?|₹)?\s*(?P<num>[-+]?\d[\d,]*(?:\.\d+)?)\s*(?P<unit>[A-Za-z%][A-Za-z% _]*)?$", re.I)


class CalcError(ValueError):
    """Bad input: the message says what, and the caller returns it, never a guessed number."""


def _words(unit: str) -> list[str]:
    """``["lakh", "crore"]`` for "lakh crore"; ``["crore"]`` for "INR crore"; ``[]`` for a bare rupee sign."""
    text = re.sub(r"\b(?:inr|rs|₹)\b", " ", unit.lower()).strip()
    return [w for w in re.split(r"[^a-z%]+", text) if w]


def parse_input(spec: Any) -> tuple[Fraction, str]:
    """``"23506 crore"`` -> (235060000000 rupees, "rupees"); ``5 percent`` -> (1/20, "percent").

    A bare number is a plain quantity (a ratio once divided), which is what a worker means by ``2`` or ``0.9``.
    """
    if isinstance(spec, bool) or spec is None:
        raise CalcError(f"input value {spec!r} is not a number")
    if isinstance(spec, (int, float)):
        return Fraction(str(spec)), ""
    text = str(spec).strip()
    match = _INPUT.match(text)
    if not match:
        raise CalcError(f"input {text!r} is not a number with an optional unit, e.g. '23506 crore'")
    value = Fraction(match.group("num").replace(",", ""))
    words = _words(match.group("unit") or "")
    if not words:
        # "Rs 349.45" is rupees: the prefix is the only unit it carries.  "Rs 5 crore" keeps its crore below.
        return value, "rupees" if match.group("cur") else ""
    if words[:2] == ["lakh", "crore"] or words[:2] == ["lakh", "cr"]:
        return value * _SCALE["lakh_crore"], "rupees"
    if any(w in _PCT for w in words):
        return value / 100, "percent"
    if any(w in _RATIO for w in words):
        return value, "ratio"
    # A scale word applies to a count as well as to rupees: "3.18 crore shares" is 31,800,000 shares.
    factor = next((_SCALE[w] for w in words if w in _SCALE), 1)
    if any(w in _COUNT for w in words):
        return value * factor, "count"
    if any(w in ("rupees", "rupee") for w in words) or factor > 1:
        return value * factor, "rupees"
    raise CalcError(f"unknown unit in {text!r}; use rupees, crore, lakh, lakh crore, million, billion, shares "
                    f"or percent")


def _unit_error(left: str, right: str, op: str) -> CalcError:
    return CalcError(f"cannot {op} {left or 'a plain number'} and {right or 'a plain number'}: give the inputs "
                     f"one unit family, or convert before the expression")


def _add(left: tuple[Fraction, str], right: tuple[Fraction, str], minus: bool) -> tuple[Fraction, str]:
    (lv, lu), (rv, ru) = left, right
    if lu and ru and lu != ru:
        raise _unit_error(lu, ru, "add" if not minus else "subtract")
    return (lv - rv if minus else lv + rv), (lu or ru)


_MUL_PAIRS: dict[frozenset[str], str] = {
    frozenset(("rupees", "count")): "rupees",          # price x shares
    frozenset(("rupees_per_share", "count")): "rupees",
    frozenset(("rupees", "ratio")): "rupees",
    frozenset(("count", "ratio")): "count",
    frozenset(("percent", "rupees")): "rupees",
    frozenset(("percent", "count")): "count",
    frozenset(("percent", "ratio")): "ratio",
}


def _mul(left: tuple[Fraction, str], right: tuple[Fraction, str]) -> tuple[Fraction, str]:
    (lv, lu), (rv, ru) = left, right
    lv = lv * rv
    if not lu:
        return lv, ru
    if not ru:
        return lv, lu
    unit = _MUL_PAIRS.get(frozenset((lu, ru)))
    if unit is None:
        raise CalcError(f"cannot multiply {lu} by {ru}; a product of two quantities has no unit here")
    return lv, unit


def _div(left: tuple[Fraction, str], right: tuple[Fraction, str]) -> tuple[Fraction, str]:
    (lv, lu), (rv, ru) = left, right
    if rv == 0:
        raise CalcError("division by zero")
    if not ru:
        return lv / rv, lu
    if not lu:
        raise CalcError(f"cannot divide a plain number by {ru}")
    if lu == ru:
        return lv / rv, "ratio"
    if lu in ("rupees", "rupees_per_share") and ru == "count":
        return lv / rv, "rupees_per_share"
    if lu == "ratio" and ru in ("rupees", "count"):
        raise CalcError(f"cannot divide {lu} by {ru}")
    raise CalcError(f"cannot divide {lu} by {ru}")


def _pow(base: tuple[Fraction, str], exponent: tuple[Fraction, str]) -> tuple[Fraction, str]:
    if exponent[1]:
        raise CalcError("the exponent must be a plain number, not a quantity")
    power = exponent[0]
    if base[1] and power != 1:
        raise CalcError(f"cannot raise {base[1]} to a power")
    if power.denominator != 1:
        # A root, as in a CAGR: "(647.1/30)^(1/5)-1".  Not exact, so it is computed in floating point and
        # returned as the decimal it prints.
        return Fraction(str(float(base[0]) ** float(power))), ""
    if abs(power) > MAX_EXPONENT:
        raise CalcError(f"exponent {float(power):g} is outside +-{MAX_EXPONENT}")
    return base[0] ** int(power), base[1] if power == 1 else ""


def _same_unit(values: list[tuple[Fraction, str]], name: str) -> str:
    units = {unit for _v, unit in values if unit}
    if len(units) > 1:
        raise CalcError(f"{name}() mixes units: {sorted(units)}")
    return units.pop() if units else ""


def _call(node: ast.Call, env: dict[str, tuple[Fraction, str]]) -> tuple[Fraction, str]:
    if not isinstance(node.func, ast.Name) or node.func.id not in FUNCS:
        raise CalcError(f"only {', '.join(FUNCS)} may be called, not {ast.unparse(node.func)}")
    if node.keywords:
        raise CalcError(f"{node.func.id}() takes positional arguments only")
    name = node.func.id
    args = [_eval(arg, env) for arg in node.args]
    if not args:
        raise CalcError(f"{name}() needs at least one argument")
    if name == "round":
        if len(args) not in (1, 2):
            raise CalcError("round() takes a number and an optional number of decimals")
        places = 0
        if len(args) == 2:
            if args[1][1] or args[1][0].denominator != 1 or abs(args[1][0]) > 12:
                raise CalcError("round() decimals must be a plain integer between -12 and 12")
            places = int(args[1][0])
        step = Fraction(10) ** places
        return Fraction(round(args[0][0] * step), 1) / step, args[0][1]
    unit = _same_unit(args, name)
    values = [v for v, _u in args]
    if name == "sum":
        return sum(values, Fraction(0)), unit
    if name == "avg":
        return sum(values, Fraction(0)) / len(values), unit
    if name == "min":
        return min(values), unit
    return max(values), unit


def _eval(node: ast.AST, env: dict[str, tuple[Fraction, str]]) -> tuple[Fraction, str]:
    if isinstance(node, ast.Expression):
        return _eval(node.body, env)
    if isinstance(node, ast.Constant):
        # bool is an int subclass and "True * 5" is not an arithmetic input.
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise CalcError(f"{node.value!r} is not a number")
        return Fraction(str(node.value)), ""
    if isinstance(node, ast.Name):
        if node.id not in env:
            raise CalcError(f"unknown input {node.id!r}; the inputs given are {sorted(env) or 'none'}")
        return env[node.id]
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        value, unit = _eval(node.operand, env)
        return (-value if isinstance(node.op, ast.USub) else value), unit
    if isinstance(node, ast.BinOp):
        left, right = _eval(node.left, env), _eval(node.right, env)
        if isinstance(node.op, ast.Add):
            return _add(left, right, minus=False)
        if isinstance(node.op, ast.Sub):
            return _add(left, right, minus=True)
        if isinstance(node.op, ast.Mult):
            return _mul(left, right)
        if isinstance(node.op, ast.Div):
            return _div(left, right)
        if isinstance(node.op, ast.Pow):
            return _pow(left, right)
    if isinstance(node, ast.Call):
        return _call(node, env)
    raise CalcError(f"{type(node).__name__} is not allowed; use + - * / **, parentheses, sum, avg, min, max, "
                    f"round")


def indian_grouping(value: Fraction | float | int, places: int = 2) -> str:
    """``1234567.5`` -> ``12,34,567.50``: the last three digits, then twos (never 1,234,567)."""
    number = Fraction(value) if not isinstance(value, Fraction) else value
    step = Fraction(10) ** places
    scaled = round(number * step)
    sign = "-" if scaled < 0 else ""
    whole, frac = divmod(abs(scaled), step)
    digits = str(whole)
    head = digits[:-3] if len(digits) > 3 else ""
    tail = digits[-3:] if len(digits) > 3 else digits
    groups: list[str] = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    text = (",".join(groups) + "," if groups else "") + tail
    if places:
        text += "." + str(frac).rjust(places, "0")
    return sign + text


def _number(value: Fraction, places: int = 6) -> float | int:
    """A JSON number: an integer when exact, else a float at ``places`` significant digits."""
    if value.denominator == 1:
        return int(value)
    return round(float(value), places)


def evaluate(expression: str, inputs: Any = None) -> dict[str, Any]:
    """``{"ok": true, "value": ..., "unit": ..., "rupees"/"crore"/"lakh_crore"/"indian", ...}`` or an error."""
    try:
        if not isinstance(expression, str) or not expression.strip():
            raise CalcError("expression is empty")
        if len(expression) > MAX_LENGTH:
            raise CalcError(f"expression is longer than {MAX_LENGTH} characters")
        env: dict[str, tuple[Fraction, str]] = {}
        for name, spec in (inputs or {}).items():
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", str(name)):
                raise CalcError(f"input name {name!r} must be a letter or underscore, then letters or digits")
            env[str(name)] = parse_input(spec)
        try:
            tree = ast.parse(expression, mode="eval")
        except SyntaxError as exc:
            raise CalcError(f"expression does not parse: {exc.msg} (at character {exc.offset})") from exc
        value, unit = _eval(tree, env)
        # T-109: a difference of two percentages is a move in percentage points, and a reader also needs the
        # relative change (27.09% -> 27.44% is +0.35 pp, +1.29%); saying "0.35%" for it is a unit error
        points = None
        body = tree.body
        if unit == "percent" and isinstance(body, ast.BinOp) and isinstance(body.op, ast.Sub):
            new, old = _eval(body.left, env), _eval(body.right, env)
            if new[1] == "percent" and old[1] == "percent":
                points = (new[0], old[0])
    except CalcError as exc:
        return {"ok": False, "error": str(exc), "expression": expression}
    except ZeroDivisionError:
        return {"ok": False, "error": "division by zero", "expression": expression}
    out: dict[str, Any] = {"ok": True, "expression": expression.strip(), "unit": unit or "ratio",
                           "value": _number(value), "exact": str(value.numerator) if value.denominator == 1
                           else f"{value.numerator}/{value.denominator}"}
    if unit in ("rupees", "rupees_per_share"):
        out.update(rupees=_number(value), crore=_number(value / 10 ** 7), lakh_crore=_number(value / 10 ** 12),
                   indian=indian_grouping(value), display=f"Rs {indian_grouping(value)}")
    elif unit == "count":
        out.update(count=_number(value), indian=indian_grouping(Fraction(value), 0),
                   display=indian_grouping(Fraction(value), 0))
    elif unit == "percent" and points:
        new, old = points
        out.update(unit="percentage_points", percentage_points=_number(value * 100), bps=_number(value * 10 ** 4),
                   display=f"{float(value * 100):+g} percentage points (pp)",
                   note="a change between two percentages: say percentage points, not percent")
        if old:
            rel = (new - old) / old
            out.update(relative_change_pct=_number(rel * 100), relative_display=f"{float(rel * 100):+.4g}% relative")
    elif unit == "percent":
        out.update(percent=_number(value * 100), bps=_number(value * 10 ** 4),
                   display=f"{float(value * 100):g}%")
    else:
        out.update(ratio=_number(value), display=f"{float(value):g}x" if unit == "ratio" else f"{float(value):g}")
    return out
