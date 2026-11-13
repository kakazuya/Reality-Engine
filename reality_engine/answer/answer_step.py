"""The answer step (T-205 round 11): one model reads one reading copy and answers it.

`write_answer(question, as_of, reading_text, coverage, model)` makes ONE model call (plus at most one repair)
returning a JSON answer: one entry per plan part with ``status`` (answered / not_found), prose, ``figures`` (value,
unit, period, item_id, quote), ``calcs`` (name, expression, inputs) and a ``final_answer`` with ``{{name}}``
placeholders.  The model never computes: `compute` evaluates each expression with an AST arithmetic evaluator, fills
the placeholders and keeps the formula with its inputs beside the answer.  `check_answer` verifies every figure inside
the text of the item it cites, and every number of the final answer against the checked figures and computed results;
failures go back in ONE repair call, and whatever still fails is removed and listed under ``unverified``.

Round 11 fixes the round-10 citation check: the reading copy now prints each item's PACK id (`[fin-3] ...`) and the
check resolves exactly that id (tolerant of brackets, case and surrounding spaces), so ids the model copies resolve.
A quote that does not match after whitespace/line-break normalisation falls back to the value appearing in the cited
item; such a figure is kept as ``verified_value_only``.  Dates, fiscal-period labels, page numbers, ordinals and
counts restating the question are not figures.  The prompt names no company, question or figure: it is a general
protocol over "the reading copy".
"""
from __future__ import annotations

import ast
import hashlib
import json
import math
import os
import re
import time
from pathlib import Path
from typing import Any, Callable

import requests

from reality_engine.answer import evidence_pack as ep
from reality_engine.scripts.go_session import session_id

API_BASE = "https://opencode.ai/zen/go/v1/chat/completions"
MODEL = "deepseek-v4.1-flash"      # Shivam 13 Nov: paid DeepSeek approved while Beam is rate limited; beam-free selectable
URL = API_BASE
KEY_ENVS = ("OPENCODE_GO_API_KEY", "OPENCODE_GO_API_KEY_2")
JOB = "answer_step"
CALLER = "answer_step"
REASONING_EFFORT = "low"
MAX_TOKENS = 8000               # round 11: longest valid round-10 reply was 2,034 output tokens; 8,000 is ~4x that
ATTEMPTS = 2                    # the first answer plus exactly one repair call
PROMPT_VERSION = "answer-r12.1"
RATE_WAITS = (30, 60, 120, 240)  # a 429 waits these seconds, in order, before the question is marked rate_limited
_RATE = {"429": 0, "wait_s": 0.0}

SYSTEM = """You answer an investor's question from ONE evidence pack (the reading copy). You have no tools and you do \
no arithmetic: the script computes every calculation and checks every figure.

Reply with ONE JSON object and nothing else:
{"parts": [{"part": "p1", "status": "answered", "text": "...", "figures": [], "calcs": []}],
 "final_answer": "..."}

For every plan part (p1, p2, ...) write one entry, in order.
- status "answered": the reading copy holds what the part asks; status "not_found": it does not.
- text: one short paragraph answering that part. Use only figures you have listed in figures or calcs. Never do \
arithmetic in the text (no "growth of", no "total of", no percentage you worked out): define a calc instead.
- figures: every figure you state, as {"value": <number as printed>, "unit": "<unit>", "period": "<period>", \
"item_id": "<the item id, exactly as printed in square brackets at the start of the item, e.g. fin-3>", \
"quote": "<the exact sentence from that item>"}.
  * value is the number as printed (2,930.95), not a converted one; unit is the printed unit (crore, %, x, shares).
  * item_id must be an item id shown in the reading copy; quote must be copied character for character from THAT \
item's text. A figure whose quote cannot be found in its item falls back to the value appearing in that item.
- calcs: every computed figure (growth, margin, ratio, difference, sum, share of total), as \
{"name": "growth", "expression": "(a - b) / b * 100", "inputs": {"a": <figure index>, "b": <figure index>}}.
  * figure index is the figure's position in YOUR figures list, starting at 0. Only + - * / ** ( ) and input names.
  * every calc input must be a figure you ALREADY listed in figures (list the value as a figure first); an index \
that is not one of your figures fails the check and the result is not computed.
  * write the expression, never the result; the script computes and prints it.
- final_answer: the answer prose for the user, with {{name}} where each calc's result belongs (for example \
"revenue grew {{growth}}"). Do not put a computed number there yourself.
- not_found: only when the reading copy cannot answer the part. Say "data not found", name what you looked for, and \
if the copy has a related item mention it as the nearest supporting material, clearly not the answer.

Rules: every number in text and final_answer must be a listed figure or a calc placeholder; a number that cannot be \
traced to an item is removed. Dates, fiscal-period labels (Q2FY27, H1, FY26), page references, ordinals and counts \
that restate the question are not figures. Copy item ids and quotes exactly. No outside knowledge."""


class BillingError(RuntimeError):
    """The provider refused on billing/quota: stop the run, never absorb it."""


class RateLimited(RuntimeError):
    """HTTP 429: the caller waits and retries within its attempt budget."""


# --- model call ---------------------------------------------------------------------------------------
def resolve_key() -> str:
    try:
        from reality_engine.scripts.resource_watchdog import user_env
        env = user_env()
    except Exception:
        env = dict(os.environ)
    return next((env[name] for name in KEY_ENVS if env.get(name)), "")


def call_model(system: str, user: str, key: str, *, model: str = MODEL, timeout: int = 300) -> dict:
    key = key or ""
    last = ""
    body: dict[str, Any] = {"model": model, "max_tokens": MAX_TOKENS,
                            "messages": [{"role": "system", "content": system},
                                         {"role": "user", "content": user}]}
    if REASONING_EFFORT:
        body["reasoning_effort"] = REASONING_EFFORT
    for attempt in range(5):
        try:
            response = requests.post(URL, timeout=timeout,
                                     headers={"Authorization": f"Bearer {key}",
                                              "x-opencode-session": session_id(JOB, model, key)},
                                     json=body)
        except requests.RequestException as exc:
            last = repr(exc)[:200]
            time.sleep(3 * (attempt + 1))
            continue
        text = response.text or ""
        if response.status_code == 429:
            _RATE["429"] += 1
            if attempt < len(RATE_WAITS):
                wait = RATE_WAITS[attempt]
                _RATE["wait_s"] += wait
                time.sleep(wait)
                continue
            raise RateLimited(text[:120])
        if response.status_code == 200:
            data = response.json()
            choice = (data.get("choices") or [{}])[0]
            usage = data.get("usage") or {}
            try:
                from reality_engine.toolbelt.cost_ledger import record_usage
                record_usage(model, usage, CALLER)
            except Exception:
                pass
            return {"content": (choice.get("message") or {}).get("content") or "",
                    "finish": choice.get("finish_reason"),
                    "in_tok": int(usage.get("prompt_tokens") or 0),
                    "out_tok": int(usage.get("completion_tokens") or 0)}
        if response.status_code == 402 or re.search(r"billing|quota|insufficient|credit", text, re.I):
            raise BillingError(f"HTTP {response.status_code}: {text[:200]}")
        last = f"HTTP {response.status_code}: {text[:160]}"
        time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"{model} failed after 3 tries: {last}")


# --- arithmetic (the model never computes) -------------------------------------------------------------
_ALLOWED_BINOPS = {ast.Add: lambda a, b: a + b, ast.Sub: lambda a, b: a - b,
                   ast.Mult: lambda a, b: a * b, ast.Div: lambda a, b: a / b,
                   ast.Pow: lambda a, b: a ** b, ast.Mod: lambda a, b: a % b,
                   ast.FloorDiv: lambda a, b: a // b}
_ALLOWED_UNARY = {ast.USub: lambda a: -a, ast.UAdd: lambda a: a}


def _eval_node(node: ast.AST, env: dict[str, float]) -> float:
    if isinstance(node, ast.Expression):
        return _eval_node(node.body, env)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise ValueError(f"only numbers are allowed, not {node.value!r}")
        return float(node.value)
    if isinstance(node, ast.Name):
        if node.id not in env:
            raise ValueError(f"unknown input {node.id!r}")
        return env[node.id]
    if isinstance(node, ast.BinOp) and type(node.op) in _ALLOWED_BINOPS:
        return _ALLOWED_BINOPS[type(node.op)](_eval_node(node.left, env), _eval_node(node.right, env))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _ALLOWED_UNARY:
        return _ALLOWED_UNARY[type(node.op)](_eval_node(node.operand, env))
    raise ValueError(f"{type(node).__name__} is not arithmetic")


def evaluate_expression(expression: str, inputs: dict[str, float]) -> float:
    """Arithmetic only: names are the calc's inputs, never builtins, functions or attributes."""
    try:
        tree = ast.parse(str(expression), mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"expression is not valid arithmetic: {exc}") from exc
    value = _eval_node(tree, {str(k): float(v) for k, v in (inputs or {}).items()})
    if isinstance(value, complex) or not math.isfinite(value):
        raise ValueError("expression did not produce a finite number")
    return value


# --- figures and calcs ---------------------------------------------------------------------------------
def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "").replace("%", "")
    try:
        return float(text)
    except ValueError:
        return None


def _decimals(value: Any) -> int:
    text = str(value).replace(",", "").strip()
    return len(text.split(".")[1]) if "." in text else 0


def _unit_of(expression: str, inputs_units: list[str]) -> str:
    if re.search(r"\*\s*100(?:\.0+)?\s*$", expression):
        return "%"
    if "/" in expression:
        return "x"
    return next((unit for unit in inputs_units if unit), "")


def _figures_hint(figures: list[dict]) -> str:
    """The exact repair message: which figures exist, with their indexes, for a calc that cannot resolve."""
    hints = []
    for index, figure in enumerate(figures[:15]):
        hints.append(f"{index}={figure.get('value')!r} {figure.get('unit') or ''} "
                     f"({figure.get('item_id') or '-'})")
    if len(figures) > 15:
        hints.append(f"... {len(figures)} figures in total")
    return "; ".join(hints) or "no figures listed"


def compute(calcs: list[dict], figures: list[dict],
            valid_indices: set[int] | None = None) -> tuple[list[dict], list[dict]]:
    """``(calculations, failures)``: each expression over figure indices, never a model-written result.

    ``valid_indices`` (when given) is the set of figures that passed the citation check; a calc whose input is not
    one of them fails, so a removed figure can never leak into the answer through a computed result.  A failure names
    the calc, the input and the figures that do exist, so the single repair call can fix it.
    """
    done: list[dict] = []
    failures: list[dict] = []
    for calc in calcs:
        name = str(calc.get("name") or "")
        expression = str(calc.get("expression") or "")
        raw_inputs = calc.get("inputs") or {}
        env, units, bad = {}, [], ""
        bad_symbol: Any = None
        bad_index: Any = None
        for symbol, index in raw_inputs.items():
            try:
                idx = int(index)
            except (TypeError, ValueError):
                bad = f"input {symbol!r} is not a figure index"
                bad_symbol, bad_index = symbol, index
                break
            if not 0 <= idx < len(figures):
                bad = f"input {symbol!r} points at figure {idx}, outside the figures list"
                bad_symbol, bad_index = symbol, idx
                break
            if valid_indices is not None and idx not in valid_indices:
                bad = f"input {symbol!r} points at figure {idx}, which did not pass the check"
                bad_symbol, bad_index = symbol, idx
                break
            figure = figures[idx]
            value = _number(figure.get("value"))
            if value is None:
                bad = f"figure {idx} has no numeric value"
                bad_symbol, bad_index = symbol, idx
                break
            env[str(symbol)] = value
            units.append(str(figure.get("unit") or ""))
        if bad:
            failures.append({"name": name, "input": str(bad_symbol), "index": str(bad_index),
                             "reason": f"calc {name!r}: {bad}; figures that exist: {_figures_hint(figures)}"})
            continue
        try:
            result = evaluate_expression(expression, env)
        except ValueError as exc:
            failures.append({"name": name, "input": "", "index": "",
                             "reason": f"calc {name!r}: {exc}; figures that exist: {_figures_hint(figures)}"})
            continue
        done.append({"name": name, "expression": expression, "inputs": raw_inputs,
                     "inputs_values": {k: env[k] for k in env},
                     "result": result, "unit": _unit_of(expression, units)})
    return done, failures


def _fmt_plain(value: float) -> str:
    if float(value).is_integer():
        return f"{int(value):,}"
    return f"{value:,.2f}".rstrip("0").rstrip(".")


def _fmt_result(value: float, unit: str) -> str:
    """Round-12 script formatting: integers without .0, thousands separators, crore for >= 1 crore, % at 2dp."""
    u = str(unit or "").strip().lower()
    if u in ("%", "pct", "percent", "percentage"):
        return f"{value:.2f}%"
    if u in ("inr_cr", "crore", "cr"):
        return f"{value:,.2f} crore"
    if u in ("inr", "rs", "rupee", "rupees"):
        if abs(value) >= 1e7:
            return f"{value / 1e7:,.2f} crore"
        return _fmt_plain(value)
    text = _fmt_plain(value)
    return f"{text} {unit}".strip() if unit else text


def _tidy_points(text: str) -> str:
    """A difference of two percentages is labelled ``percentage points`` once, never ``% percentage points``."""
    return re.sub(r"(\d[\d,.]*)\s*%\s+(percentage points)", r"\1 \2", str(text or ""), flags=re.I)


def _fill(text: str, calculations: list[dict]) -> str:
    out = str(text or "")
    for calc in calculations:
        token = "{{" + calc["name"] + "}}"
        unit = str(calc["unit"] or "")
        u = unit.lower()
        formatted = _fmt_result(calc["result"], unit)
        at = out.find(token)
        if at >= 0 and unit:
            low = out[at + len(token):at + len(token) + 24].lstrip().lower()
            if u in ("%", "pct", "percent") and (low.startswith("%") or low.startswith("percentage points")):
                formatted = f"{calc['result']:.2f}"
            elif u in ("inr", "inr_cr", "crore", "cr", "rs", "rupee") and re.match(r"(crore|cr)\b", low):
                formatted = _fmt_result(calc["result"], unit).replace(" crore", "")
        out = out.replace(token, formatted)
    return _tidy_points(out)


_FIGURE_UNITS_PCT = ("%", "pct", "percent", "percentage")
_FIGURE_UNITS_INR = ("inr", "rs", "rupee", "rupees", "inr_cr", "crore", "cr")


def _format_figures(text: str, figures: list[dict]) -> str:
    """Rewrite only the figure tokens the model placed: 75049043.0 -> 75,049,043; 36.5% -> 36.50%;
    1538100000 inr -> 153.81 crore (the stored figure record is untouched)."""
    source = str(text or "")
    spans = []
    for figure in figures:
        value = _number(figure.get("value"))
        if value is None:
            continue
        unit = str(figure.get("unit") or "").strip().lower()
        for match in _NUM_RE.finditer(source):
            try:
                token_value = float(match.group(0).replace(",", ""))
            except ValueError:
                continue
            if abs(token_value - value) <= max(0.005, abs(value) * 1e-9):
                spans.append((match.start(), match.end(), value, unit))
    spans.sort()
    pieces, last, seen = [], 0, set()
    for start, end, value, unit in spans:
        if start < last or start in seen:
            continue
        seen.add(start)
        if unit in _FIGURE_UNITS_PCT:
            percent = re.match(r"\s*%", source[end:end + 8])
            rest = source[end + percent.end():end + percent.end() + 24] if percent else source[end:end + 24]
            if re.match(r"\s*percentage points", rest, re.I):
                replacement = f"{value:.2f}"
                if percent:
                    end += percent.end()
            else:
                replacement = f"{value:.2f}%"
                if percent:
                    end += percent.end()
        elif unit in _FIGURE_UNITS_INR:
            replacement = _fmt_result(value, unit)
            crore = re.match(r"\s*(crore|cr)\b", source[end:end + 12], re.I)
            if crore:
                end += crore.end()
            else:
                money = re.match(r"\s*(inr|rs\.?|rupees?)\b", source[end:end + 12], re.I)
                if money and replacement.endswith(" crore"):
                    end += money.end()
        else:
            replacement = _fmt_plain(value)
        pieces.append(source[last:start])
        pieces.append(replacement)
        last = end
    pieces.append(source[last:])
    return _tidy_points("".join(pieces))


# --- the check -----------------------------------------------------------------------------------------
_MONTH = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"
_PERIOD_RE = re.compile(
    r"\b(?:Q[1-4](?:\s*FY\s*'?\s*\d{2,4}(?:\s*[-–]\s*\d{2,4})?)?"
    r"|H[12](?:\s*FY\s*'?\s*\d{2,4}(?:\s*[-–]\s*\d{2,4})?)?"
    r"|9M\s*FY\s*'?\s*\d{2,4}|FY\s*'?\s*\d{2,4}(?:\s*[-–]\s*\d{2,4})?|CY\s*'?\s*\d{2,4}"
    r"|\d+[- ](?:week|month|year)s?)\b", re.I)
_DATE_RE = re.compile(
    r"\b\d{4}-\d{2}-\d{2}(?:T[\d:.]+| \d{1,2}:\d{2}(?::\d{2})?)?\b"
    r"|\b\d{1,2}(?:st|nd|rd|th)?\s+" + _MONTH + r"\.?,?\s*\d{2,4}\b"
    r"|\b" + _MONTH + r"\s+\d{1,2}(?:st|nd|rd|th)?,?\s*\d{2,4}\b"
    r"|\b\d{1,2}[./-]\d{1,2}[./-]\d{2,4}\b"
    r"|\b" + _MONTH + r"\s+\d{4}\b", re.I)
_PAGE_RE = re.compile(r"\b(?:pp?|pages?)\.?\s*\d+(?:\s*[-–]\s*\d+)?", re.I)
_ORDINAL_RE = re.compile(r"\b\d{1,2}(?:st|nd|rd|th)\b", re.I)
_RATIO_RE = re.compile(r"\b\d{1,2}\s*:\s*\d{1,2}\b")     # a bonus/split ratio label ("1:1"), never a figure
# a labelled ordinal ("Segment 1", "Table 2", "Tier-3") is a reference, not a figure; a comma-grouped number
# right after the word ("segment 2,930.95") is not stripped because the lookahead rejects the group separator.
_LABEL_RE = re.compile(r"\b(?:segment|table|note|chart|annexure|appendix|part|section|item|step|phase|tier|option)"
                        r"\s*[-#]?\s*\d{1,2}(?!\d|[.,]\d)", re.I)
_NONFIGURE_RES = (_DATE_RE, _PERIOD_RE, _PAGE_RE, _ORDINAL_RE, _LABEL_RE, _RATIO_RE)
_NUM_RE = re.compile(r"-?\d[\d,]*\.?\d*(?:[eE][+-]?\d+)?")


def _boundary_ok(text: str, match: re.Match) -> bool:
    """A digit glued to a letter/underscore is an identifier (Q2, H1, a UUID fragment), not a figure."""
    before = text[match.start() - 1] if match.start() else ""
    after = text[match.end()] if match.end() < len(text) else ""
    return not (before and (before.isalnum() or before == "_")) \
        and not (after and (after.isalnum() or after == "_"))


def _nonfigure_spans(text: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    for pattern in _NONFIGURE_RES:
        spans.extend(m.span() for m in pattern.finditer(text))
    return spans


def _question_counts(question: str) -> set[int]:
    """Integers 0-99 the question itself states: a count that restates the question is not a figure."""
    text = str(question or "")
    for pattern in _NONFIGURE_RES:
        text = pattern.sub(" ", text)
    return {int(m.group(0)) for m in _NUM_RE.finditer(text)
            if _boundary_ok(text, m) and 0 <= int(m.group(0)) <= 99}


def _figure_numbers(text: str, question: str = "", include_years: bool = False):
    """Yield ``(start, end, value)`` for the number tokens that are figures.

    Dates (30 September 2026, 31.03.2026, 2026-09-30), fiscal-period labels (Q2FY27, H1, FY2025-26, 52-week),
    page references (p. 9, page 12), ordinals (1st), labelled ordinals (Segment 1, Table 2, Tier-3), years,
    digit-glued identifiers, and integers the question itself states are not figures and are never checked or
    scrubbed.  ``include_years`` is for value matching only: a figure of 2,000 crore must be findable in an item
    even though a bare 2000 in prose is a year.
    """
    text = str(text or "")
    spans = _nonfigure_spans(text)
    counts = _question_counts(question)
    for match in _NUM_RE.finditer(text):
        if not _boundary_ok(text, match):
            continue
        if any(start <= match.start() < end for start, end in spans):
            continue
        try:
            value = float(match.group(0).replace(",", ""))
        except ValueError:
            continue
        if not include_years and 1900 <= value <= 2100 and float(value).is_integer():
            continue                                         # a year, not a figure (1935.99 is a figure)
        if float(value).is_integer() and int(value) in counts:
            continue
        yield match.start(), match.end(), value


def _nums(text: str, question: str = "") -> set[float]:
    return {value for _, _, value in _figure_numbers(text, question)}


def _norm(text: str) -> str:
    return " ".join(str(text or "").split()).lower()


def _value_in(value: Any, text: str, unit: str = "") -> bool:
    target = _number(value)
    if target is None:
        return False
    decimals = _decimals(value)
    candidates = [target]
    if str(unit).lower() in ("inr", "rs", "rupee", "rupees", ""):
        candidates += [target / 1e7, target * 1e7]
    text_nums = {value for _start, _end, value in _figure_numbers(text, include_years=True)}
    for candidate in candidates:
        for number in text_nums:
            if abs(number - candidate) <= max(0.005, abs(candidate) * 1e-4):
                return True
            if decimals and round(number, decimals) == round(candidate, decimals):
                return True
    return False


def _clean_id(raw: Any) -> str:
    return " ".join(str(raw or "").strip().strip("[]").split()).lower()


def _item_map(pack: dict) -> dict[str, dict]:
    return {_clean_id(it.get("id")): it for it in pack.get("items") or [] if it.get("id") not in (None, "")}


def _resolve_item_id(raw: Any, items: dict[str, dict]) -> tuple[dict | None, str]:
    """The one id form the copy prints: tolerant of brackets, case and surrounding spaces only."""
    key = _clean_id(raw)
    return (items.get(key), key) if key in items else (None, key)


def _check_figures(answer: dict, pack: dict) -> list[dict]:
    """Every figure's value inside its cited item; flags ``verified_value_only`` where only the value matched."""
    failures: list[dict] = []
    items = _item_map(pack)
    figures = answer.get("_figures_flat") or []
    for index, figure in enumerate(figures):
        cited = str(figure.get("item_id") or "")
        item, resolved = _resolve_item_id(cited, items)
        if item is None:
            failures.append({"kind": "figure", "index": index, "code": "item",
                             "reason": f"item {cited!r} is not in the reading copy (ids print like [fin-3])"})
            continue
        item_text = str(item.get("text") or "")
        quote = _norm(figure.get("quote") or "")
        if quote and quote in _norm(item_text):
            if not _value_in(figure.get("value"), item_text, str(figure.get("unit") or "")):
                failures.append({"kind": "figure", "index": index, "code": "value",
                                 "reason": f"value {figure.get('value')!r} is not in item {resolved}"})
            continue
        if quote and _value_in(figure.get("value"), item_text, str(figure.get("unit") or "")):
            figure["verified_value_only"] = True
            continue
        failures.append({"kind": "figure", "index": index, "code": "quote_value",
                         "reason": f"the quote is not in item {resolved} and value {figure.get('value')!r} "
                                   "is not in its text"})
    return failures


def _check_numbers(answer: dict, pack: dict) -> list[dict]:
    """Every number of the final answer is a checked figure or a computed result."""
    failures: list[dict] = []
    question = str((pack.get("plan") or {}).get("question") or "")
    allowed = set()
    for figure in answer.get("_figures_flat") or []:
        value = _number(figure.get("value"))
        if value is not None:
            allowed.update({value, value / 1e7, value * 1e7})
    for calc in answer.get("calculations") or []:
        allowed.add(calc["result"])
    for number in sorted(_nums(answer.get("final_answer") or "", question)):
        if not any(abs(number - candidate) <= max(0.005, abs(candidate) * 1e-4) for candidate in allowed):
            failures.append({"kind": "number", "value": number,
                             "reason": "the number in final_answer is not a checked figure or a computed result"})
    return failures


def check_answer(answer: dict, pack: dict) -> list[dict]:
    """Every figure's value inside its cited item; every number of the final answer is a checked figure or calc.

    A figure whose quote matches the cited item after whitespace/line-break normalisation is ``verified``.  A quote
    that still differs falls back to the value appearing in that item (``verified_value_only``, kept and flagged),
    and a value that is not there is a failure and is removed.  Dates, fiscal-period labels, page numbers, ordinals
    and counts restating the question are not figures (see ``_figure_numbers``); nothing else is exempt.
    """
    return _check_figures(answer, pack) + _check_numbers(answer, pack)


def _scrub(text: str, allowed: set[float], question: str = "") -> tuple[str, list[float]]:
    """Replace any figure token not in ``allowed``; dates, periods, pages, ordinals and question counts stay."""
    removed: list[float] = []
    pieces, last = [], 0
    source = str(text or "")
    for start, end, value in _figure_numbers(source, question):
        if any(abs(value - candidate) <= max(0.005, abs(candidate) * 1e-4) for candidate in allowed):
            continue
        pieces.append(source[last:start])
        pieces.append("[unverified]")
        removed.append(value)
        last = end
    pieces.append(source[last:])
    return "".join(pieces), removed


# --- prompt and one answer ----------------------------------------------------------------------------
def _parts_of(pack: dict, coverage: list[dict]) -> list[dict]:
    parts = pack.get("parts") or []
    if parts:
        return [{"id": str(p.get("id") if isinstance(p, dict) else p),
                 "text": str(p.get("text") if isinstance(p, dict) else "")} for p in parts]
    return [{"id": str(c.get("part") or c.get("id") or ""), "text": str(c.get("text") or "")}
            for c in coverage or []]


def _coverage_lines(coverage: list[dict]) -> str:
    lines = []
    for part in coverage or []:
        pid = part.get("part") or part.get("id") or ""
        lines.append(f"- {pid} [{part.get('status') or 'none'}] " + (part.get("text") or ""))
        for entry in part.get("lookups") or []:
            found = "found" if entry.get("found") else "not found"
            lines.append(f"    {entry.get('route')} {json.dumps(entry.get('args') or {}, ensure_ascii=False)} "
                         f"-> {found}, {len(entry.get('items') or [])} items")
    return "\n".join(lines) or "- (no coverage)"


def build_prompt(question: str, as_of: str, reading_text: str, coverage: list[dict],
                 parts: list[dict]) -> str:
    part_lines = "\n".join(f"- {p['id']}: {p['text']}" for p in parts)
    return (f"QUESTION (asked as of {as_of or '-'}):\n{question}\n\n"
            f"PARTS to answer (one entry each, in order):\n{part_lines}\n\n"
            f"COVERAGE (what was searched; status none means nothing was found for that part):\n"
            f"{_coverage_lines(coverage)}\n\n"
            f"READING COPY (the only evidence you have):\n{reading_text}\n\n"
            "Reply with the JSON answer object and nothing else.")


def parse_reply(text: str) -> dict | None:
    if not text:
        return None
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) and isinstance(data.get("parts"), list) else None


def _flat_figures(parts: list[dict]) -> list[dict]:
    return [f for part in parts for f in (part.get("figures") or []) if isinstance(f, dict)]


def _apply_coverage(answer: dict, coverage: list[dict], parts: list[dict]) -> None:
    by_part = {str(c.get("part") or c.get("id") or ""): c for c in coverage or []}
    for part in answer.get("parts") or []:
        pid = str(part.get("part") or "")
        cov = by_part.get(pid) or {}
        status = cov.get("status") or "none"
        searches = [f"{e.get('route')} {json.dumps(e.get('args') or {}, ensure_ascii=False)}"
                    for e in cov.get("lookups") or []]
        part["coverage_status"] = status
        part["searched"] = searches
        if part.get("status") == "not_found":
            part["abstained_with_evidence"] = status in ("found", "some")
            nearest = []
            for entry in cov.get("lookups") or []:
                nearest.extend(entry.get("items") or [])
            part["nearest_items"] = nearest[:2]
            part["text"] = (str(part.get("text") or "") +
                            " | searched: " + ("; ".join(searches) or "nothing") +
                            (" | nearest supporting item (not the answer): " + ", ".join(nearest[:2])
                             if nearest else ""))


def _evaluate_reply(raw: dict, parts_plan: list[dict], pack: dict):
    """Normalise one parsed reply, check its figures, compute its calcs, fill placeholders and check numbers."""
    answer = _normalise(raw, parts_plan)
    figures = _flat_figures(answer["parts"])
    answer["_figures_flat"] = figures
    figure_failures = _check_figures(answer, pack)
    failed = {f["index"] for f in figure_failures if f.get("kind") == "figure"}
    calculations, calc_failures = compute(answer.get("calcs") or [], figures, set(range(len(figures))) - failed)
    answer["calculations"] = calculations
    answer["final_answer"] = _fill(answer.get("final_answer") or "", calculations)
    for part in answer["parts"]:
        part["text"] = _fill(part.get("text") or "", calculations)
    failures = figure_failures + [{"kind": "calc", **f} for f in calc_failures] + _check_numbers(answer, pack)
    return answer, figures, calculations, failures


def _finalise(answer: dict, figures: list[dict], calculations: list[dict], failures: list[dict],
              pack: dict, coverage: list[dict], parts_plan: list[dict]) -> dict:
    """Remove failed figures/calcs, scrub non-figure numbers, flag leftovers and attach the coverage note."""
    answer["figures_cited"] = len(figures)
    if failures:
        figures = _remove_failed(answer, figures, calculations, failures)
    answer["figures_removed"] = answer["figures_cited"] - len(figures)
    answer["verified_value_only"] = sum(1 for figure in figures if figure.get("verified_value_only"))
    question_text = str((pack.get("plan") or {}).get("question") or "")
    allowed = set()
    for figure in figures:
        value = _number(figure.get("value"))
        if value is not None:
            allowed.update({value, value / 1e7, value * 1e7})
    for calc in answer.get("calculations") or []:
        allowed.add(calc["result"])
    answer["final_answer"], removed_answer = _scrub(answer.get("final_answer") or "", allowed, question_text)
    for part in answer["parts"]:
        part["text"], part_removed = _scrub(part.get("text") or "", allowed, question_text)
        removed_answer.extend(part_removed)
    answer["final_answer"] = _format_figures(answer["final_answer"], figures)
    for part in answer["parts"]:
        part["text"] = _format_figures(part["text"], figures)
    texts = [answer["final_answer"]] + [part["text"] for part in answer["parts"]]
    leftover = sorted({m for text in texts for m in re.findall(r"\{\{([^{}]+)\}\}", text)})
    if leftover:
        failed_calcs = {f.get("name") for f in failures if f.get("kind") == "calc"}
        for name in leftover:
            failures.append({"kind": "placeholder", "name": name,
                             "reason": ("the calc for this placeholder did not resolve its input"
                                        if name in failed_calcs else
                                        "no computed calculation fills this placeholder")})
        marker = lambda name: f"not computed (input missing: {name})"   # noqa: E731
        answer["final_answer"] = re.sub(r"\{\{([^{}]+)\}\}", lambda m: marker(m.group(1)),
                                        answer["final_answer"])
        calc_part = {str(calc.get("name")): calc.get("_part")
                     for calc in answer.get("calcs") or [] if isinstance(calc, dict)}
        for name in leftover:
            pid = calc_part.get(name)
            parts = [p for p in answer["parts"] if str(p.get("part")) == str(pid)] or answer["parts"][:1]
            for part in parts:
                part["calc_unresolved"] = True
        for part in answer["parts"]:
            replaced = re.sub(r"\{\{([^{}]+)\}\}", lambda m: marker(m.group(1)), part["text"])
            if replaced != part["text"]:
                part["calc_unresolved"] = True
                part["text"] = replaced
    answer["unverified"] = [dict(f) for f in failures]
    answer["check_failures"] = failures
    answer["_removed_numbers"] = removed_answer
    _apply_coverage(answer, coverage, parts_plan)
    return answer


def _remove_failed(answer: dict, figures: list[dict], calculations: list[dict],
                   failures: list[dict]) -> list[dict]:
    """Drop the failed figures and failed calcs (never kept silently); return the kept figures."""
    failed_index = {f.get("index") for f in failures if f.get("kind") == "figure"}
    failed_calcs = {f.get("name") for f in failures if f.get("kind") == "calc"}
    for part in answer["parts"]:
        kept = []
        for figure in part.get("figures") or []:
            try:
                idx = figures.index(figure)
            except ValueError:
                idx = -1
            if idx in failed_index:
                continue
            kept.append(figure)
        part["figures"] = kept
    answer["calculations"] = [c for c in calculations if c["name"] not in failed_calcs]
    kept_figures = _flat_figures(answer["parts"])
    answer["_figures_flat"] = kept_figures
    return kept_figures


def write_answer(question: str, as_of: str, reading_text: str, coverage: list[dict], model: str = MODEL, *,
                 pack: dict | None = None, client: Callable[..., dict] | None = None,
                 cache_dir: str | Path | None = None, key: str = "", save_dir: str | Path | None = None) -> dict:
    """One model call (plus at most one repair), computed calcs, checked figures, a final answer."""
    pack = pack or {}
    parts_plan = _parts_of(pack, coverage)
    t0 = time.time()
    digest = hashlib.sha256(f"{PROMPT_VERSION}\n{model}\n{question}\n{as_of}\n{reading_text}".encode("utf-8")).hexdigest()
    cache_path = Path(cache_dir) / f"answer_{digest[:32]}.json" if cache_dir else None
    if cache_path is not None and cache_path.is_file():
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            cached["cached"] = True
            cached["model_calls"] = 0
            cached["seconds"] = round(time.time() - t0, 3)
            return cached
        except (OSError, json.JSONDecodeError):
            pass

    call = client or call_model
    api_key = key or ("" if client else resolve_key())
    raw: list[str] = []
    raw_finish: list[str] = []
    calls = 0
    rate_hit = False
    tokens = {"in": 0, "out": 0}

    def ask(user: str) -> str | None:
        nonlocal calls, rate_hit
        calls += 1
        try:
            reply = call(SYSTEM, user, api_key)
        except RateLimited:
            rate_hit = True
            raw.append("rate_limited")
            return None
        except RuntimeError as exc:
            raw.append(f"model_error: {exc}"[:2000])
            return None
        tokens["in"] += int(reply.get("in_tok") or 0)
        tokens["out"] += int(reply.get("out_tok") or 0)
        content = str(reply.get("content") or "")
        raw.append(content)
        raw_finish.append(str(reply.get("finish") or ""))
        return content

    def finish(result: dict) -> dict:
        result.update({"model": model, "model_calls": calls, "raw_replies": raw,
                       "finish_reasons": raw_finish,
                       "in_tok": tokens["in"], "out_tok": tokens["out"],
                       "seconds": round(time.time() - t0, 3), "cached": False,
                       "prompt_version": PROMPT_VERSION, "input_chars": len(reading_text)})
        if save_dir:
            try:
                Path(save_dir).mkdir(parents=True, exist_ok=True)
                (Path(save_dir) / "prompt.txt").write_text(user_prompt, encoding="utf-8")
            except OSError:
                pass
        if cache_path is not None:
            try:
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                cache_path.write_text(json.dumps(result, ensure_ascii=False, default=str), encoding="utf-8")
            except OSError:
                pass
        return result

    user_prompt = build_prompt(question, as_of, reading_text, coverage, parts_plan)
    content = ask(user_prompt)
    if content is None:
        return finish({"status": "rate_limited" if rate_hit else "model_error", "parts": [],
                       "final_answer": "", "unverified": [], "check_failures": [], "calculations": [],
                       "repair_used": False})
    answer = parse_reply(content)
    if answer is None:
        cut = (not content) or (raw_finish and raw_finish[-1] == "length")
        note = ("Your previous reply was empty or cut off before the JSON object was complete. Reply with the "
                "complete JSON object only; keep every text short."
                if cut else
                "Your previous reply was not a JSON answer object. Reply with the JSON object only.")
        content = ask(user_prompt + "\n\n" + note)
        if content is None and rate_hit:
            return finish({"status": "rate_limited", "parts": [], "final_answer": "", "unverified": [],
                           "check_failures": [], "calculations": [], "repair_used": True})
        answer = parse_reply(content or "")
        if answer is None:
            return finish({"status": "unparseable", "parts": [], "final_answer": "", "unverified": [],
                           "check_failures": [], "calculations": [], "repair_used": True,
                           "retried_unparseable": True})
    answer, figures, calculations, failures = _evaluate_reply(answer, parts_plan, pack)
    initial_failures = list(failures)
    repair_used = False
    if failures:
        repair_used = True
        problem = json.dumps(failures, ensure_ascii=False)[:6000]
        content = ask(build_prompt(question, as_of, reading_text, coverage, parts_plan) +
                      "\n\nYOUR PREVIOUS ANSWER FAILED THESE CHECKS:\n" + problem +
                      "\n\nFix them. Copy quotes from the cited item, use only listed figures or calc placeholders, "
                      "and reply with the corrected JSON object only.")
        repaired = parse_reply(content or "")
        if repaired is not None:
            answer, figures, calculations, failures = _evaluate_reply(repaired, parts_plan, pack)
    # whatever still fails is removed and listed, never kept silently
    _finalise(answer, figures, calculations, failures, pack, coverage, parts_plan)
    answer["initial_failures"] = len(initial_failures)
    answer["initial_failure_kinds"] = [f.get("kind") for f in initial_failures]
    answer["repair_used"] = repair_used
    return finish(answer)


def _normalise(answer: dict, parts_plan: list[dict]) -> dict:
    """Keep the plan's parts in order. A calc written inside a part indexes THAT part's figures, so its input
    indices are remapped onto the flattened figure list here (the round-10 code dropped per-part calcs entirely)."""
    out = {"parts": [], "final_answer": str(answer.get("final_answer") or ""), "calcs": []}
    if isinstance(answer.get("calcs"), list):
        out["calcs"].extend(answer["calcs"])
    by_part = {}
    for part in answer.get("parts") or []:
        if not isinstance(part, dict):
            continue
        pid = str(part.get("part") or "")
        by_part[pid] = part
    offset = 0
    for plan in parts_plan:
        pid = str(plan.get("id") or "")
        part = by_part.get(pid) or {}
        figures = [f for f in (part.get("figures") or []) if isinstance(f, dict)]
        for calc in part.get("calcs") or []:
            if not isinstance(calc, dict):
                continue
            remapped = dict(calc)
            fixed = {}
            for symbol, index in (calc.get("inputs") or {}).items():
                try:
                    fixed[symbol] = int(index) + offset
                except (TypeError, ValueError):
                    fixed[symbol] = index
            remapped["inputs"] = fixed
            remapped["_part"] = pid
            out["calcs"].append(remapped)
        out["parts"].append({
            "part": pid,
            "status": "answered" if str(part.get("status") or "answered") == "answered" else "not_found",
            "text": str(part.get("text") or ""),
            "figures": figures,
            "calcs": [],
        })
        offset += len(figures)
    return out


def _map_old_item_id(cited: Any, order: list[str], items: dict[str, dict]) -> tuple[str, str]:
    """Map a round-9/10 positional id to a pack id: exact id first, then ``[n]``/``n`` by printed position,
    then ``route-n`` (the nth printed item if its route matches, else the nth item of that route)."""
    resolved, key = _resolve_item_id(cited, items)
    if resolved is not None:
        return key, "exact"
    if key.isdigit():
        position = int(key)
        return (order[position - 1], "position") if 0 < position <= len(order) else ("", "out_of_range")
    match = re.fullmatch(r"([a-z][a-z_]*)-(\d+)", key)
    if match:
        route, position = match.group(1), int(match.group(2))
        if 0 < position <= len(order) and str(items.get(order[position - 1], {}).get("route")) == route:
            return order[position - 1], "route_position"
        same_route = [iid for iid in order if str(items.get(iid, {}).get("route")) == route]
        if 0 < position <= len(same_route):
            return same_route[position - 1], "route_ordinal"
    return "", "unmapped"


def _mapped_reply(saved: dict, pack: dict, old_pack: dict, parts_plan: list[dict]):
    """Replay a saved reply offline with its old positional ids mapped to this pack's ids.

    Returns ``(answer, figures, failures, mapping)`` or None when no reply parses; ``mapping`` is one
    ``(old_id, new_id, how)`` per flattened figure.
    """
    raw = None
    for text in reversed([str(r) for r in saved.get("raw_replies") or []]):
        raw = parse_reply(text)
        if raw is not None:
            break
    if raw is None:
        return None
    order = ep.reading_order(old_pack, max_chars=150000)
    items = _item_map(pack)
    prepared = _normalise(raw, parts_plan)
    mapping = []
    for part in prepared["parts"]:
        for figure in part["figures"]:
            old_id = figure.get("item_id")
            new_id, how = _map_old_item_id(old_id, order, items)
            mapping.append((str(old_id), new_id, how))
            figure["item_id"] = new_id
    answer, figures, _calculations, failures = _evaluate_reply(prepared, parts_plan, pack)
    return answer, figures, failures, mapping


def recheck_set(packs_dir: str | Path, answers_dir: str | Path) -> dict:
    """Step 2: re-run compute + check on the saved replies, no model call and no truth file.

    Old positional ids (``12``, ``[21]``, ``fin-1``) map through the old reading copy's printed order; figures whose
    id cannot be mapped are reported and counted as removed.  Per set: figures cited, verified, verified_value_only,
    removed by reason, number failures, and how many figures the id contract alone had been rejecting.
    """
    packs_dir, answers_dir = Path(packs_dir), Path(answers_dir)
    cited = verified = value_only = removed = saved_by_contract = exact_raw = 0
    reasons: dict[str, int] = {}
    unmapped: list[str] = []
    number_failures = 0
    answers = unparseable = zero_removed = 0
    examples: list[dict] = []
    for path in sorted(answers_dir.glob("answer_*.json")):
        pack_path = packs_dir / f"pack_{path.stem[len('answer_'):]}.json"
        if not pack_path.is_file():
            continue
        saved = json.loads(path.read_text(encoding="utf-8"))
        pack = json.loads(pack_path.read_text(encoding="utf-8"))
        answers += 1
        parts_plan = _parts_of(pack, pack.get("coverage") or [])
        replayed = _mapped_reply(saved, pack, pack, parts_plan)
        if replayed is None:
            unparseable += 1
            continue
        answer, figures, failures, mapping = replayed
        removed_index = {f["index"] for f in failures if f.get("kind") == "figure"}
        value_index = {i for i, figure in enumerate(figures) if figure.get("verified_value_only")}
        cited += len(figures)
        value_only += len(value_index)
        removed += len(removed_index)
        verified += len(figures) - len(removed_index) - len(value_index)
        if not removed_index:
            zero_removed += 1
        number_failures += sum(1 for f in failures if f.get("kind") == "number")
        items = _item_map(pack)
        for failure in failures:
            if failure.get("kind") == "figure":
                code = failure.get("code") or "item"
                reasons[code] = reasons.get(code, 0) + 1
        for index, (old_id, new_id, how) in enumerate(mapping):
            if _resolve_item_id(old_id, items)[0] is not None:
                exact_raw += 1
            if not new_id:
                unmapped.append(old_id)
            elif _resolve_item_id(old_id, items)[0] is None and index not in removed_index:
                saved_by_contract += 1
        if len(examples) < 10:
            for index in sorted(removed_index)[:2]:
                failure = next(f for f in failures if f.get("kind") == "figure" and f.get("index") == index)
                examples.append({"qid": path.stem[len("answer_"):], "old_id": mapping[index][0],
                                 "mapped": mapping[index][1], "code": failure.get("code"),
                                 "reason": failure.get("reason")})
    return {"answers": answers, "parseable": answers - unparseable, "unparseable": unparseable,
            "figures_cited": cited, "verified": verified, "verified_value_only": value_only,
            "removed": removed, "removed_by_reason": reasons,
            "id_exact_before": exact_raw, "id_unmapped": len(unmapped), "unmapped_ids": sorted(set(unmapped))[:25],
            "saved_by_id_contract": saved_by_contract, "number_failures": number_failures,
            "answers_with_zero_removed": zero_removed, "removed_examples": examples}


def reuse_answer(saved: dict, pack: dict, old_pack: dict, reading: str) -> dict | None:
    """A saved reply that passes the current check offline may stand in for a model call; else re-ask."""
    parts_plan = _parts_of(pack, pack.get("coverage") or [])
    replayed = _mapped_reply(saved, pack, old_pack, parts_plan)
    if replayed is None:
        return None
    answer, figures, failures, mapping = replayed
    calculations = answer.get("calculations") or []
    if failures or any(not new_id for _old, new_id, _how in mapping):
        return None
    _finalise(answer, figures, calculations, failures, pack, pack.get("coverage") or [], parts_plan)
    answer.update({"model": saved.get("model"), "model_calls": 0,
                   "raw_replies": saved.get("raw_replies") or [], "finish_reasons": saved.get("finish_reasons") or [],
                   "in_tok": 0, "out_tok": 0, "seconds": 0, "cached": False, "reused": True,
                   "prompt_version": PROMPT_VERSION, "input_chars": len(reading),
                   "initial_failures": 0, "initial_failure_kinds": [], "repair_used": False})
    return answer


def refill_set(packs_dir: str | Path, answers_dir: str | Path) -> dict:
    """Rewrite the saved answers from their raw replies (a check/prompt fix), with no model call.

    Used after the round-11 per-part-calc fix: round-10/11 replies put ``calcs`` inside each part, which the old
    normaliser dropped, so 16 answers still printed ``{{name}}``.  This replays every reply, computes the calcs,
    fills the placeholders and re-checks the same rules.
    """
    packs_dir, answers_dir = Path(packs_dir), Path(answers_dir)
    summary = {"answers": 0, "refilled": 0, "unparseable": 0, "figures_cited": 0, "figures_removed": 0,
               "value_only": 0, "calcs": 0, "placeholders": 0}
    keep = ("model", "model_calls", "raw_replies", "finish_reasons", "in_tok", "out_tok", "seconds",
            "cached", "reused", "prompt_version", "input_chars", "initial_failures",
            "initial_failure_kinds", "repair_used", "status", "retried_unparseable")
    for path in sorted(answers_dir.glob("answer_*.json")):
        pack_path = packs_dir / f"pack_{path.stem[len('answer_'):]}.json"
        if not pack_path.is_file():
            continue
        saved = json.loads(path.read_text(encoding="utf-8"))
        pack = json.loads(pack_path.read_text(encoding="utf-8"))
        summary["answers"] += 1
        parts_plan = _parts_of(pack, pack.get("coverage") or [])
        replayed = _mapped_reply(saved, pack, pack, parts_plan)
        if replayed is None:
            summary["unparseable"] += 1
            continue
        answer, figures, failures, _mapping = replayed
        calculations = answer.get("calculations") or []
        _finalise(answer, figures, calculations, failures, pack, pack.get("coverage") or [], parts_plan)
        for key in keep:
            if key in saved:
                answer[key] = saved[key]
        answer["refilled"] = True
        summary["refilled"] += 1
        summary["figures_cited"] += answer["figures_cited"]
        summary["figures_removed"] += answer["figures_removed"]
        summary["value_only"] += answer["verified_value_only"]
        summary["calcs"] += len(answer.get("calculations") or [])
        summary["placeholders"] += sum(1 for f in failures if f.get("kind") == "placeholder")
        path.write_text(json.dumps(answer, ensure_ascii=False, default=str), encoding="utf-8")
    return summary


def _resume_state(saved: dict, retry_unparseable: bool) -> str:
    """A finished answer is kept; a rate-limited one is always retried, an unparseable one when asked."""
    status = str(saved.get("status") or "")
    if status == "rate_limited" or (status == "unparseable" and retry_unparseable):
        return "retry"
    return "keep"


def first_ten_gate(rows: list[dict]) -> dict:
    """Step 6 stop rule: over the first ten answers of a run, stop when >20% of cited figures were removed."""
    first = rows[:10]
    cited = sum(int(row.get("figures_cited") or 0) for row in first)
    removed = sum(int(row.get("figures_removed") or 0) for row in first)
    ratio = (removed / cited) if cited else 0.0
    return {"answers": len(first), "figures_cited": cited, "figures_removed": removed,
            "unverified_ratio": round(ratio, 3),
            "tripped": len(first) >= 10 and cited > 0 and ratio > 0.20}


def main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(prog="python -m reality_engine.answer.answer_step")
    parser.add_argument("--set", choices=["bluestar", "aurobindo"], required=True)
    parser.add_argument("--packs", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--answer-model", default=MODEL)
    parser.add_argument("--questions", default="")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--workspace", default=".")
    parser.add_argument("--recheck", action="store_true",
                        help="offline: re-run compute + check on the saved replies in --out; no model call")
    parser.add_argument("--refill", action="store_true",
                        help="offline: rewrite the saved answers from their raw replies (compute calcs, fill "
                             "placeholders, re-check); no model call")
    parser.add_argument("--retry-unparseable", action="store_true",
                        help="on resume, re-ask the questions whose saved answer is unparseable")
    parser.add_argument("--reuse", default="", help="a round-10 answers dir whose saved replies may be reused")
    parser.add_argument("--reuse-packs", default="", help="the old packs dir those replies cited (default pack_r9)")
    args = parser.parse_args(argv)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    if args.recheck:
        report = recheck_set(args.packs, out_dir)
        report["set"] = args.set
        (out_dir / "recheck.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
        print(json.dumps(report, indent=1))
        return 0
    if args.refill:
        report = refill_set(args.packs, out_dir)
        report["set"] = args.set
        (out_dir / "refill.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
        print(json.dumps(report, indent=1))
        return 0
    questions_path = args.questions or (f"D:/RealityEngine/{args.set}/answers/questions_in.json")
    qs = json.loads(Path(questions_path).read_text(encoding="utf-8"))
    if args.limit:
        qs = qs[:args.limit]
    cache_dir = Path(args.workspace) / ".tmp" / "answer_cache"
    reuse_dir = Path(args.reuse) if args.reuse else None
    reuse_packs = Path(args.reuse_packs) if args.reuse_packs else Path(args.workspace) / ".tmp" / "pack_r9" / args.set
    import csv
    rows, counts = [], {"answered": 0, "not_found": 0, "abstained_with_evidence": 0,
                        "figures": 0, "figures_cited": 0, "figures_removed": 0, "verified_value_only": 0,
                        "calcs": 0, "check_failures": 0, "unverified": 0,
                        "initial_failures": 0, "repair_used": 0, "unparseable": 0, "model_error": 0,
                        "rate_limited": 0, "calls": 0, "in_tok": 0, "out_tok": 0, "reused": 0}
    rate_stop, gate_stop, gate = False, False, {}
    seconds = []
    for q in qs:
        qid, question, as_of = q["qid"], q["question"], q["as_of"]
        answer_path = out_dir / f"answer_{qid}.json"
        answer = None
        if answer_path.is_file():
            existing = json.loads(answer_path.read_text(encoding="utf-8"))
            if _resume_state(existing, args.retry_unparseable) == "keep":   # resumable: a finished question is skipped
                answer = existing
        if answer is None:
            pack = json.loads((Path(args.packs) / f"pack_{qid}.json").read_text(encoding="utf-8"))
            reading_path = Path(args.packs) / f"pack_{qid}.txt"
            reading = reading_path.read_text(encoding="utf-8") if reading_path.is_file() else pack.get("text", "")
            if reuse_dir is not None:
                saved_path = reuse_dir / f"answer_{qid}.json"
                old_pack_path = reuse_packs / f"pack_{qid}.json"
                if saved_path.is_file() and old_pack_path.is_file():
                    reused = reuse_answer(json.loads(saved_path.read_text(encoding="utf-8")), pack,
                                          json.loads(old_pack_path.read_text(encoding="utf-8")), reading)
                    if reused is not None:
                        answer = reused
            if answer is None:
                answer = write_answer(question, as_of, reading, pack.get("coverage") or [], args.answer_model,
                                      pack=pack, cache_dir=cache_dir)
                time.sleep(2)                                 # one question at a time, never in parallel
            answer_path.write_text(json.dumps(answer, ensure_ascii=False, default=str), encoding="utf-8")
        parts = answer.get("parts") or []
        reasons = sorted({str(f.get("reason") or "") for f in answer.get("check_failures") or []
                          if f.get("kind") in ("figure", "number")})
        rows.append({
            "qid": qid, "question": question, "final_answer": answer.get("final_answer", ""),
            "parts": len(parts),
            "not_found_parts": sum(1 for p in parts if p.get("status") == "not_found"),
            "abstained_with_evidence": sum(1 for p in parts if p.get("abstained_with_evidence")),
            "figures": len(answer.get("_figures_flat") or []),
            "figures_cited": int(answer.get("figures_cited") or 0),
            "figures_removed": int(answer.get("figures_removed") or 0),
            "verified_value_only": int(answer.get("verified_value_only") or 0),
            "calcs": len(answer.get("calculations") or []),
            "check_failures": len(answer.get("check_failures") or []),
            "initial_failures": int(answer.get("initial_failures") or 0),
            "repair_used": bool(answer.get("repair_used")),
            "reused": bool(answer.get("reused")),
            "unverified": len(answer.get("unverified") or []),
            "unverified_reasons": " | ".join(reasons),
            "seconds": answer.get("seconds", 0),
            "input_chars": answer.get("input_chars", 0),
            "model": answer.get("model"),
            "in_tok": int(answer.get("in_tok") or 0),
            "out_tok": int(answer.get("out_tok") or 0),
        })
        counts["answered"] += sum(1 for p in parts if p.get("status") == "answered")
        counts["not_found"] += sum(1 for p in parts if p.get("status") == "not_found")
        counts["abstained_with_evidence"] += sum(1 for p in parts if p.get("abstained_with_evidence"))
        counts["figures"] += len(answer.get("_figures_flat") or [])
        counts["figures_cited"] += int(answer.get("figures_cited") or 0)
        counts["figures_removed"] += int(answer.get("figures_removed") or 0)
        counts["verified_value_only"] += int(answer.get("verified_value_only") or 0)
        counts["calcs"] += len(answer.get("calculations") or [])
        counts["check_failures"] += len(answer.get("check_failures") or [])
        counts["initial_failures"] += int(answer.get("initial_failures") or 0)
        counts["unverified"] += len(answer.get("unverified") or [])
        counts["repair_used"] += 1 if answer.get("repair_used") else 0
        counts["reused"] += 1 if answer.get("reused") else 0
        if answer.get("status") == "unparseable":
            counts["unparseable"] += 1
        elif answer.get("status") == "model_error":
            counts["model_error"] += 1
        counts["calls"] += int(answer.get("model_calls") or 0)
        counts["in_tok"] += int(answer.get("in_tok") or 0)
        counts["out_tok"] += int(answer.get("out_tok") or 0)
        if answer.get("status") == "rate_limited":
            counts["rate_limited"] += 1
            if counts["rate_limited"] > 10:                   # stop, keep what is written (T-205 round 10 note)
                rate_stop = True
                seconds.append(float(answer.get("seconds") or 0))
                break
        if not gate and len(rows) >= 10:
            gate = first_ten_gate(rows)
            if gate["tripped"]:
                gate["reasons"] = []
                for row in rows[:10]:
                    for reason in str(row.get("unverified_reasons") or "").split(" | "):
                        if reason and reason not in gate["reasons"]:
                            gate["reasons"].append(reason)
                gate["reasons"] = gate["reasons"][:8]
                gate_stop = True
                seconds.append(float(answer.get("seconds") or 0))
                break
        seconds.append(float(answer.get("seconds") or 0))
    with open(out_dir / "answers.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ["qid"])
        writer.writeheader()
        writer.writerows(rows)
    import statistics
    summary = {"set": args.set, "questions": len(rows), **counts,
               "rate_limit": dict(_RATE), "stopped_on_rate_limit": rate_stop,
               "stopped_on_gate": gate_stop, "first_ten_gate": gate,
               "seconds": {"median": round(statistics.median(seconds), 2) if seconds else 0,
                           "max": round(max(seconds), 2) if seconds else 0}}
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print(json.dumps(summary, indent=1))
    return 2 if gate_stop else 0


if __name__ == "__main__":
    raise SystemExit(main())
