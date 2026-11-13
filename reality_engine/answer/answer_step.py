"""The answer step (T-205 round 10): one model reads one round-9 reading copy and answers it.

`write_answer(question, as_of, reading_text, coverage, model)` makes ONE free-model call (plus at most one repair)
returning a JSON answer: one entry per plan part with ``status`` (answered / not_found), prose, ``figures`` (value,
unit, period, item_id, quote), ``calcs`` (name, expression, inputs) and a ``final_answer`` with ``{{name}}``
placeholders.  The model never computes: `compute` evaluates each expression with an AST arithmetic evaluator, fills
the placeholders and keeps the formula with its inputs beside the answer.  `check_answer` verifies every figure inside
the text of the item it cites, and every number of the final answer against the checked figures and computed results;
failures go back in ONE repair call, and whatever still fails is removed and listed under ``unverified``.

The prompt names no company, question or figure: it is a general protocol over "the reading copy".
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

from reality_engine.scripts.go_session import session_id

API_BASE = "https://opencode.ai/zen/go/v1/chat/completions"
MODEL = "deepseek-v4.1-flash"      # Shivam 13 Nov: paid DeepSeek approved while Beam is rate limited; beam-free selectable
URL = API_BASE
KEY_ENVS = ("OPENCODE_GO_API_KEY", "OPENCODE_GO_API_KEY_2")
JOB = "answer_step"
CALLER = "answer_step"
REASONING_EFFORT = "low"
MAX_TOKENS = 4000
ATTEMPTS = 2                    # the first answer plus exactly one repair call
PROMPT_VERSION = "answer-r10.1"
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
"item_id": "<the item id in the copy, e.g. fin-3>", "quote": "<the exact sentence from that item>"}.
  * value is the number as printed (2,930.95), not a converted one; unit is the printed unit (crore, %, x, shares).
  * item_id must be an item id shown in the reading copy; quote must be copied character for character from THAT \
item's text. A figure whose quote cannot be found in its item is rejected.
- calcs: every computed figure (growth, margin, ratio, difference, sum, share of total), as \
{"name": "growth", "expression": "(a - b) / b * 100", "inputs": {"a": <figure index>, "b": <figure index>}}.
  * figure index is the figure's position in YOUR figures list, starting at 0. Only + - * / ** ( ) and input names.
  * write the expression, never the result; the script computes and prints it.
- final_answer: the answer prose for the user, with {{name}} where each calc's result belongs (for example \
"revenue grew {{growth}}"). Do not put a computed number there yourself.
- not_found: only when the reading copy cannot answer the part. Say "data not found", name what you looked for, and \
if the copy has a related item mention it as the nearest supporting material, clearly not the answer.

Rules: every number in text and final_answer must be a listed figure or a calc placeholder; a number that cannot be \
traced to an item is removed. Copy item ids and quotes exactly. No outside knowledge."""


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


def compute(calcs: list[dict], figures: list[dict]) -> tuple[list[dict], list[dict]]:
    """``(calculations, failures)``: each expression over figure indices, never a model-written result."""
    done: list[dict] = []
    failures: list[dict] = []
    for calc in calcs:
        name = str(calc.get("name") or "")
        expression = str(calc.get("expression") or "")
        raw_inputs = calc.get("inputs") or {}
        env, units, bad = {}, [], ""
        for symbol, index in raw_inputs.items():
            try:
                idx = int(index)
            except (TypeError, ValueError):
                bad = f"input {symbol!r} is not a figure index"
                break
            if not 0 <= idx < len(figures):
                bad = f"input {symbol!r} points at figure {idx}, outside the figures list"
                break
            figure = figures[idx]
            value = _number(figure.get("value"))
            if value is None:
                bad = f"figure {idx} has no numeric value"
                break
            env[str(symbol)] = value
            units.append(str(figure.get("unit") or ""))
        if bad:
            failures.append({"name": name, "reason": bad})
            continue
        try:
            result = evaluate_expression(expression, env)
        except ValueError as exc:
            failures.append({"name": name, "reason": str(exc)})
            continue
        done.append({"name": name, "expression": expression, "inputs": raw_inputs,
                     "inputs_values": {k: env[k] for k in env},
                     "result": result, "unit": _unit_of(expression, units)})
    return done, failures


def _fmt_result(value: float, unit: str) -> str:
    text = f"{value:,.2f}".rstrip("0").rstrip(".")
    return f"{text} {unit}".strip()


def _fill(text: str, calculations: list[dict]) -> str:
    out = str(text or "")
    for calc in calculations:
        out = out.replace("{{" + calc["name"] + "}}", _fmt_result(calc["result"], calc["unit"]))
    return out


# --- the check -----------------------------------------------------------------------------------------
_PERIOD_RE = re.compile(r"(?:Q[1-4]|H[12]|9M)\s*FY\s*\d{2,4}|FY\s*\d{2,4}", re.I)
_DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}(?:[T ][\d:]+)?\b")
_NUM_RE = re.compile(r"-?\d[\d,]*\.?\d*(?:[eE][+-]?\d+)?")


def _nums(text: str) -> set[float]:
    found = set()
    cleaned = _DATE_RE.sub(" ", _PERIOD_RE.sub(" ", str(text or "")))
    for m in _NUM_RE.finditer(cleaned):
        token = m.group(0).replace(",", "")
        try:
            value = float(token)
        except ValueError:
            continue
        if 1900 <= value <= 2100:            # a year, not a figure
            continue
        found.add(value)
    return found


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
    text_nums = _nums(text)
    for candidate in candidates:
        for number in text_nums:
            if abs(number - candidate) <= max(0.005, abs(candidate) * 1e-4):
                return True
            if decimals and round(number, decimals) == round(candidate, decimals):
                return True
    return False


def check_answer(answer: dict, pack: dict) -> list[dict]:
    """Every figure inside its cited item; every number of the final answer is a checked figure or a calc result."""
    failures: list[dict] = []
    items = {str(it.get("id")): it for it in pack.get("items") or []}
    figures = answer.get("_figures_flat") or []
    for index, figure in enumerate(figures):
        item_id = str(figure.get("item_id") or "")
        item = items.get(item_id)
        if item is None:
            failures.append({"kind": "figure", "index": index, "reason": f"item {item_id!r} is not in the pack"})
            continue
        item_text = str(item.get("text") or "")
        quote = _norm(figure.get("quote") or "")
        if not quote or quote not in _norm(item_text):
            failures.append({"kind": "figure", "index": index,
                             "reason": f"the quote is not in the text of item {item_id}"})
            continue
        if not _value_in(figure.get("value"), item_text, str(figure.get("unit") or "")):
            failures.append({"kind": "figure", "index": index,
                             "reason": f"value {figure.get('value')!r} is not in item {item_id}"})
    allowed = set()
    for figure in figures:
        value = _number(figure.get("value"))
        if value is not None:
            allowed.update({value, value / 1e7, value * 1e7})
    for calc in answer.get("calculations") or []:
        allowed.add(calc["result"])
    text = answer.get("final_answer") or ""
    for number in sorted(_nums(text)):
        if not any(abs(number - candidate) <= max(0.005, abs(candidate) * 1e-4) for candidate in allowed):
            failures.append({"kind": "number", "value": number,
                             "reason": "the number in final_answer is not a checked figure or a computed result"})
    return failures


def _scrub(text: str, allowed: set[float]) -> tuple[str, list[float]]:
    """Replace any number of the text that is not an allowed figure/result; return the numbers removed."""
    removed: list[float] = []
    cleaned = _PERIOD_RE.sub(lambda m: m.group(0), text or "")

    def replace(m: re.Match) -> str:
        token = m.group(0)
        value = float(token.replace(",", ""))
        if 1900 <= value <= 2100:
            return token
        if any(abs(value - candidate) <= max(0.005, abs(candidate) * 1e-4) for candidate in allowed):
            return token
        removed.append(value)
        return "[unverified]"

    out = re.sub(r"(?<![\w./-])-?\d[\d,]*\.?\d*(?:[eE][+-]?\d+)?(?![\w./-])", replace, cleaned)
    return out, removed


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
        return content

    def finish(result: dict) -> dict:
        result.update({"model": model, "model_calls": calls, "raw_replies": raw,
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
        content = ask(user_prompt + "\n\nYour previous reply was not a JSON answer object. Reply with the JSON object "
                                     "only.")
        if content is None and rate_hit:
            return finish({"status": "rate_limited", "parts": [], "final_answer": "", "unverified": [],
                           "check_failures": [], "calculations": [], "repair_used": True})
        answer = parse_reply(content or "")
        if answer is None:
            return finish({"status": "unparseable", "parts": [], "final_answer": "", "unverified": [],
                           "check_failures": [], "calculations": [], "repair_used": True})
    answer = _normalise(answer, parts_plan)
    figures = _flat_figures(answer["parts"])
    answer["_figures_flat"] = figures
    calculations, calc_failures = compute(answer.get("calcs") or [], figures)
    answer["calculations"] = calculations
    answer["final_answer"] = _fill(answer.get("final_answer") or "", calculations)
    for part in answer["parts"]:
        part["text"] = _fill(part.get("text") or "", calculations)
    failures = check_answer(answer, pack) + [{"kind": "calc", **f} for f in calc_failures]
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
            answer = _normalise(repaired, parts_plan)
            figures = _flat_figures(answer["parts"])
            answer["_figures_flat"] = figures
            calculations, calc_failures = compute(answer.get("calcs") or [], figures)
            answer["calculations"] = calculations
            answer["final_answer"] = _fill(answer.get("final_answer") or "", calculations)
            for part in answer["parts"]:
                part["text"] = _fill(part.get("text") or "", calculations)
            failures = check_answer(answer, pack) + [{"kind": "calc", **f} for f in calc_failures]
    # whatever still fails is removed and listed, never kept silently
    allowed = set()
    verified_figures = []
    if failures:
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
        figures = _flat_figures(answer["parts"])
        answer["_figures_flat"] = figures
    for figure in figures:
        value = _number(figure.get("value"))
        if value is not None:
            allowed.update({value, value / 1e7, value * 1e7})
    for calc in answer.get("calculations") or []:
        allowed.add(calc["result"])
    answer["final_answer"], removed_answer = _scrub(answer.get("final_answer") or "", allowed)
    for part in answer["parts"]:
        part["text"], part_removed = _scrub(part.get("text") or "", allowed)
        removed_answer.extend(part_removed)
    answer["unverified"] = [dict(f) for f in failures]
    answer["check_failures"] = failures
    answer["initial_failures"] = len(initial_failures)
    answer["initial_failure_kinds"] = [f.get("kind") for f in initial_failures]
    answer["repair_used"] = repair_used
    answer["_removed_numbers"] = removed_answer
    _apply_coverage(answer, coverage, parts_plan)
    return finish(answer)


def _normalise(answer: dict, parts_plan: list[dict]) -> dict:
    out = {"parts": [], "final_answer": str(answer.get("final_answer") or ""),
           "calcs": answer.get("calcs") if isinstance(answer.get("calcs"), list) else []}
    by_part = {}
    for part in answer.get("parts") or []:
        if not isinstance(part, dict):
            continue
        pid = str(part.get("part") or "")
        by_part[pid] = part
    for plan in parts_plan:
        pid = str(plan.get("id") or "")
        part = by_part.get(pid) or {}
        out["parts"].append({
            "part": pid,
            "status": "answered" if str(part.get("status") or "answered") == "answered" else "not_found",
            "text": str(part.get("text") or ""),
            "figures": [f for f in (part.get("figures") or []) if isinstance(f, dict)],
            "calcs": [],
        })
    return out


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
    args = parser.parse_args(argv)
    questions_path = args.questions or (f"D:/RealityEngine/{args.set}/answers/questions_in.json")
    qs = json.loads(Path(questions_path).read_text(encoding="utf-8"))
    if args.limit:
        qs = qs[:args.limit]
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    cache_dir = Path(args.workspace) / ".tmp" / "answer_cache"
    import csv
    rows, counts = [], {"answered": 0, "not_found": 0, "abstained_with_evidence": 0,
                        "figures": 0, "calcs": 0, "check_failures": 0, "unverified": 0,
                        "initial_failures": 0, "repair_used": 0, "unparseable": 0, "model_error": 0,
                        "rate_limited": 0, "calls": 0, "in_tok": 0, "out_tok": 0}
    rate_stop = False
    seconds = []
    for q in qs:
        qid, question, as_of = q["qid"], q["question"], q["as_of"]
        answer_path = out_dir / f"answer_{qid}.json"
        answer = None
        if answer_path.is_file():
            existing = json.loads(answer_path.read_text(encoding="utf-8"))
            if existing.get("status") != "rate_limited":      # resumable: a finished question is skipped
                answer = existing
        if answer is None:
            pack = json.loads((Path(args.packs) / f"pack_{qid}.json").read_text(encoding="utf-8"))
            reading_path = Path(args.packs) / f"pack_{qid}.txt"
            reading = reading_path.read_text(encoding="utf-8") if reading_path.is_file() else pack.get("text", "")
            answer = write_answer(question, as_of, reading, pack.get("coverage") or [], args.answer_model,
                                  pack=pack, cache_dir=cache_dir)
            answer_path.write_text(json.dumps(answer, ensure_ascii=False, default=str), encoding="utf-8")
            time.sleep(2)                                     # one question at a time, never in parallel
        parts = answer.get("parts") or []
        rows.append({
            "qid": qid, "question": question, "final_answer": answer.get("final_answer", ""),
            "parts": len(parts),
            "not_found_parts": sum(1 for p in parts if p.get("status") == "not_found"),
            "abstained_with_evidence": sum(1 for p in parts if p.get("abstained_with_evidence")),
            "figures": len(answer.get("_figures_flat") or []),
            "calcs": len(answer.get("calculations") or []),
            "check_failures": len(answer.get("check_failures") or []),
            "initial_failures": int(answer.get("initial_failures") or 0),
            "repair_used": bool(answer.get("repair_used")),
            "unverified": len(answer.get("unverified") or []),
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
        counts["calcs"] += len(answer.get("calculations") or [])
        counts["check_failures"] += len(answer.get("check_failures") or [])
        counts["initial_failures"] += int(answer.get("initial_failures") or 0)
        counts["unverified"] += len(answer.get("unverified") or [])
        counts["repair_used"] += 1 if answer.get("repair_used") else 0
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
        seconds.append(float(answer.get("seconds") or 0))
    with open(out_dir / "answers.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ["qid"])
        writer.writeheader()
        writer.writerows(rows)
    import statistics
    summary = {"set": args.set, "questions": len(rows), **counts,
               "rate_limit": dict(_RATE), "stopped_on_rate_limit": rate_stop,
               "seconds": {"median": round(statistics.median(seconds), 2) if seconds else 0,
                           "max": round(max(seconds), 2) if seconds else 0}}
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
