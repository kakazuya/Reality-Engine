"""The model-written lookup plan for the evidence pack (T-205 round 4).

The answering model is short of routing, not of data: word matching cannot connect a question's words to the names a
store uses.  ``write_plan`` shows a free model the per-company menu (``reality_engine.answer.menu``) and asks ONE
question for JSON: the question's ``parts`` and the ``lookups`` that answer them.  ``validate`` checks every route and
name against the same menu; a rejected entry gets ONE repair call and then lands in the plan's ``rejected`` list.  A
reply that is not valid JSON even after the repair call falls back to the script planner (``planner`` =
``script_fallback``), never to a guessed plan.

Free model only (``beam-free`` by default); a paid model name is refused before any call is made, while an
``agy:<id>`` name (T-205 round 13, ``--plan-model agy:gemini-4-hydrogen-high``) routes through ``agy_call``.  The
session id is the stable ``go_session.session_id`` the rest of the repo uses, so a rerun keeps the provider's prompt
cache.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Callable

import requests

from reality_engine.answer import agy_call
from reality_engine.scripts.go_session import session_id

URL = "https://opencode.ai/zen/go/v1/chat/completions"
MODEL = "beam-free"
KEY_ENVS = ("OPENCODE_GO_API_KEY", "OPENCODE_GO_API_KEY_2")   # the _2 account has no Go subscription (403)
JOB = "answer_plan"
CALLER = "answer_plan"
REASONING_EFFORT = "low"
MAX_TOKENS = 4000
MAX_LOOKUPS = 25
RATE_WAITS = (30, 60, 120, 240)  # a 429 waits these seconds before the plan falls back to the script planner
CACHE_VERSION = "t205r6.1"     # bump when the prompt or the validation rules change: old cached plans must not return

# the document-type words a lookup accepts -> the value the store files (the same map lookups_pilot3._DOC_TYPES uses)
DOC_TYPE_ALIAS = {
    "decks": "deck", "presentation": "deck", "investor presentation": "deck", "investor_presentation": "deck",
    "transcripts": "transcript", "concall": "transcript", "call": "transcript", "concall_transcript": "transcript",
    "ar": "annual_report", "annual report": "annual_report", "annual_report": "annual_report",
    "announcements": "announcement", "filing": "announcement", "result": "results",
    "press release": "press_release", "press_release": "press_release",
}

# argument names each route accepts besides the ``symbol`` / ``as_of`` the runner injects
ROUTE_ARGS: dict[str, set[str]] = {
    "fact": {"metric", "period", "basis"},
    "fin": {"measure", "period", "basis"},
    "kpi": {"kpi", "period", "dimension", "basis"},
    "ratio": {"ratio", "period", "basis"},
    "cells": {"terms", "period"},
    "guidance": {"metric", "period"},
    "page": {"doc_key", "page", "to_page"},
    "price_rows": {"dates", "start", "end", "event_doc", "event_time"},
    "tech": {"kind", "start", "end", "doc_type", "sessions", "threshold", "window", "limit"},
    "holding": {"category", "quarters", "quarter_end"},
    "statements": {"topic", "terms", "period", "role", "latest", "date_from", "date_to"},
    "docs": {"doc_type", "date_from", "date_to"},
    "search": {"query", "doc_type", "period", "date_from", "date_to"},
    "topic": {"topic"},
    "semantic": {"query"},
}
ROUTE_REQUIRED = {"fact": ("metric",), "fin": ("measure",), "kpi": ("kpi",), "ratio": ("ratio",),
                  "cells": ("terms",), "page": ("doc_key", "page"), "tech": ("kind",),
                  "search": ("query",), "topic": ("topic",), "semantic": ("query",)}
TECH_KINDS = ("reaction", "gaps", "rsi", "ma", "volume_spikes", "range")
NAME_ARG = {"fact": "fact", "fin": "fin", "kpi": "kpi", "ratio": "ratio", "guidance": "guidance"}


def _allowed_routes() -> set[str]:
    """The routes ``routes.yaml`` lets a plan use (the one list the pack also reads)."""
    try:
        import yaml
        data = yaml.safe_load(Path(__file__).with_name("routes.yaml").read_text(encoding="utf-8")) or {}
        allowed = set(data.get("plan_routes") or [])
        return allowed or set(ROUTE_ARGS)
    except Exception:
        return set(ROUTE_ARGS)


ALLOWED_ROUTES = _allowed_routes()

_PERIOD_RE = re.compile(r"^(?:(Q[1-4])|(H[12])|(9M))?\s*FY\s*(\d{2,4})$", re.I)
_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

SYSTEM = """You plan the evidence for ONE question about an Indian listed company. You get the question and a MENU of \
what the store holds for that company. You do not answer the question: you write the lookups a script will run, so a \
reader can answer from their replies.

Reply with ONE JSON object and nothing else:
{"parts": [{"id": "p1", "text": "..."}],
 "lookups": [{"part": "p1", "route": "fin", "args": {"measure": "revenue_from_operations", "period": "Q2FY27"}}]}

parts: every separate thing the question asks, in order. A comparison of two periods is TWO parts (one per period); \
a figure and its year-on-year change is two parts; a list of several figures is one part per figure.

lookups: at most 25, each answers one part. Rules the measurements show:
- A comparison needs EVERY period named. "Q2FY27 against Q2FY26" is two lookups (or one lookup with period "Q2FY27" \
and one with period "Q2FY26"), never one.
- "prior close", "previous session", "previous quarter", "a quarter earlier", "year ago", "at the start of the \
window" is its own lookup with that period or date named.
- A question across two calls/quarters needs EACH call document named: a `page` lookup on its doc_key and page (the \
menu lists calls with doc_key, date and page count) and/or `statements` with date_from=date_to=<call date>.
- A figure the filing does not state (a ratio, a growth, a share of a total, a cumulative) needs a lookup for EACH \
input, not only the computed route.
- A cash-flow, balance-sheet or annual line often lives only in the annual table: ask `fin` with an annual period \
(FY26), or `fact`/`cells`, rather than a quarter.
- When the question refers to a figure printed in a statement or a table (a write-back, a provision, a segment \
result, capex, revenue, PAT), the plan MUST include a `cells` or `fin` lookup for the FIGURE itself with its \
period, beside the commentary lookups that explain it. Commentary alone does not answer a figure question.
- The question's basis matters: when it says standalone, pass basis="standalone"; consolidated is the default.
- doc_type is one of the exact words the menu prints (transcript, deck, results, announcement, annual_report); the \
folder name in a doc_key is not a doc_type.
- SQL LIKE: a `cells` or `search` term must be SHORT -- one word or a two-word label the table likely prints. A \
long phrase returns zero rows; the script retries single words only as a fallback, so ask the short form first.
- A prior close, "previous session", or a return over several years is a `price_rows` lookup (dates or start/end); \
its rows carry the previous session's close and the adjusted close, and a start/end pair also carries the \
first-to-last adjusted return. `tech range` is only a 52-week high/low and does not answer a multi-year return.
- A question about the market reaction to a FILING (results, announcement, deck) is a `price_rows` lookup with \
event_doc=<that filing's doc key>; never hand-pick the session dates. The script takes the filing's dissemination \
timestamp and applies the 15:30 IST rule itself; the menu lists results filings with their timestamps.
- EVERY part needs at least one lookup. A part with no lookup is rejected and costs the one repair round.
- If the language of the question does not match a menu name, choose the menu name that means the same thing.
- The same route twice is fine: two periods, two metrics, two calls.

Routes and their args (use ONLY these argument names; never symbol or as_of):
fact: metric, period, basis            -> one answer-ready figure for a (metric, period)
fin: measure, period, basis            -> reported/derived financial lines from the results tables
kpi: kpi, period, dimension, basis     -> a company-stated KPI (order book, AUM, NIM, margin ...)
ratio: ratio, period, as a date        -> a derived ratio / valuation (PE, PB, ROE, margin ...)
cells: terms, period                   -> figures read from table and chart pages
guidance: metric, period               -> forward guidance rows
page: doc_key, page, to_page           -> the text of a page of a named document
price_rows: dates, start, end, event_doc, event_time -> price sessions; event_doc gives the sessions around a filing
tech: kind, start, end                 -> price reaction/gaps/rsi/ma/volume_spikes/range
holding: category, quarters, quarter_end -> shareholding pattern and share count
statements: topic, terms, period, role, latest, date_from, date_to -> management quotes from calls
docs: doc_type, date_from, date_to     -> the document list
search: query, doc_type, period, date_from, date_to -> full-text search of the held pages
topic: topic                           -> everything held on one theme across calls
semantic: query                        -> pages closest in meaning to the query

Every name (metric, measure, kpi, ratio, category, doc_key, period) must be copied from the MENU. A name the menu does \
not print is rejected and costs a repair round. Keep periods in the store's spelling (Q2FY27, FY26, 2026-09-30)."""


class BillingError(RuntimeError):
    """The provider refused on billing/quota: stop the run, never absorb it."""


class RateLimited(RuntimeError):
    """HTTP 429: the caller waits and retries within its attempt budget."""


# --- model call ---------------------------------------------------------------------------------------
def resolve_key() -> str:
    try:
        from reality_engine.scripts.resource_watchdog import user_env
        env = user_env()
    except Exception:                    # a non-Windows shell has no registry to read
        env = dict(os.environ)
    return next((env[name] for name in KEY_ENVS if env.get(name)), "")


def call_model(system: str, user: str, key: str, *, model: str = MODEL, timeout: int = 240) -> dict:
    """One request; raises RateLimited / BillingError, retries a transport error or 5xx twice."""
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
            if attempt < len(RATE_WAITS):
                time.sleep(RATE_WAITS[attempt])
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


# --- the menu index the script checks against ---------------------------------------------------------
def _norm(name: Any) -> str:
    return re.sub(r"[\s\-/%]+", "_", str(name or "").strip().lower())


def _known(value: Any, names: list[str]) -> bool:
    """The name (or a word of it) is one the menu prints, matching ``lookups_pilot3._pick``'s contains rule."""
    n = _norm(value)
    if not n:
        return False
    return n in names or any(n in name for name in names)


def _period_key(label: str) -> tuple[int, int]:
    m = _PERIOD_RE.match(str(label or "").replace(" ", ""))
    if not m:
        return (9999, 9)
    year = int(m.group(4))
    if year < 100:
        year += 2000
    head = (m.group(1) or m.group(2) or m.group(3) or "FY").upper()
    return (year, {"Q1": 1, "Q2": 2, "Q3": 3, "Q4": 4, "H1": 0, "H2": 5, "9M": 3, "FY": 9}.get(head, 7))


def _index(menu: dict | None) -> dict:
    if not menu:
        return {}
    return menu.get("index") or {}


def _period_ok(value: Any, menu: dict | None) -> bool:
    label = str(value or "").strip()
    periods = _index(menu).get("periods") or []
    if _ISO_RE.match(label):
        sell = (menu or {}).get("price") or {}
        return bool(sell) and (not sell.get("start") or sell["start"] <= label <= (sell.get("end") or label))
    if not _PERIOD_RE.match(label.replace(" ", "")):
        return False
    if not periods:
        return True
    key = _period_key(label)
    return min(_period_key(p) for p in periods) <= key <= max(_period_key(p) for p in periods)


def _doc_key_ok(value: Any, menu: dict | None) -> bool:
    docs = _index(menu).get("doc_keys") or []
    if not docs:
        return True
    key = str(value or "")
    prefix = (menu or {}).get("doc_prefix") or ""
    expanded = prefix + key if prefix and not key.startswith(prefix) else key
    return expanded in docs or key in docs


def _check_one(lookup: Any, part_ids: list[str], menu: dict | None) -> tuple[dict | None, dict | None]:
    """``(ok_lookup, rejected)`` for one planned lookup."""
    if not isinstance(lookup, dict):
        return None, {"part": "", "route": "", "args": {}, "reason": "a lookup must be a JSON object"}
    route = str(lookup.get("route") or "").strip().lower()
    args = lookup.get("args")
    if route not in ALLOWED_ROUTES or route not in ROUTE_ARGS:
        return None, {"part": str(lookup.get("part") or ""), "route": route, "args": args if isinstance(args, dict) else {},
                      "reason": f"unknown route {route!r}; routes are {', '.join(sorted(ALLOWED_ROUTES))}"}
    if not isinstance(args, dict):
        return None, {"part": str(lookup.get("part") or ""), "route": route, "args": {},
                      "reason": "args must be a JSON object"}
    part = lookup.get("part")
    if isinstance(part, int):
        part = part_ids[part - 1] if 0 < part <= len(part_ids) else ""
    part = str(part or "").strip() or (part_ids[0] if part_ids else "p1")
    if part_ids and part not in part_ids:
        return None, {"part": part, "route": route, "args": args,
                      "reason": f"part {part!r} is not one of the plan's parts {part_ids}"}
    extra = set(args) - ROUTE_ARGS[route]
    if extra:
        return None, {"part": part, "route": route, "args": args,
                      "reason": f"args {sorted(extra)} are not accepted by route {route!r}"}
    for required in ROUTE_REQUIRED.get(route, ()):
        if args.get(required) in (None, ""):
            return None, {"part": part, "route": route, "args": args,
                          "reason": f"route {route!r} needs {required!r}"}
    for key, value in args.items():
        if isinstance(value, (dict, list)):
            if key == "dates" and isinstance(value, list) and all(not isinstance(x, (dict, list)) for x in value):
                continue                                  # price_rows takes a list of dates
            return None, {"part": part, "route": route, "args": args,
                          "reason": f"arg {key!r} must be a single value, not {type(value).__name__}"}
    family = NAME_ARG.get(route)
    if family:
        name = args.get("metric") if route in ("fact", "guidance") else (
            args.get("measure") if route == "fin" else args.get("kpi") if route == "kpi" else args.get("ratio"))
        names = _index(menu).get(family) or []
        if route == "ratio" and menu:
            names = names + list((menu.get("valuation") or {}).get("fields") or [])
        if names and not _known(name, names):
            return None, {"part": part, "route": route, "args": args,
                          "reason": f"{name!r} is not a name the menu lists for {route}; copy one exactly"}
    if route == "page":
        key = str(args.get("doc_key") or "")
        prefix = (menu or {}).get("doc_prefix") or ""
        expanded = prefix + key if prefix and not key.startswith(prefix) else key
        if not _doc_key_ok(args.get("doc_key"), menu):
            return None, {"part": part, "route": route, "args": args,
                          "reason": f"doc_key {args.get('doc_key')!r} is not in the menu"}
        args["doc_key"] = expanded          # the menu prints keys relative to its prefix; the lookup needs the key
        page = args.get("page")
        try:
            args["page"] = int(page)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return None, {"part": part, "route": route, "args": args, "reason": "page must be an integer"}
        if args["page"] < 1:
            return None, {"part": part, "route": route, "args": args, "reason": "page must be >= 1"}
        if args.get("to_page") is not None:
            try:
                args["to_page"] = int(args["to_page"])  # type: ignore[arg-type]
            except (TypeError, ValueError):
                return None, {"part": part, "route": route, "args": args, "reason": "to_page must be an integer"}
    if route == "tech":
        kind = str(args.get("kind") or "").strip().lower().replace("-", "_")
        if kind not in TECH_KINDS:
            return None, {"part": part, "route": route, "args": args,
                          "reason": f"tech kind {kind!r} is not one of {', '.join(TECH_KINDS)}"}
        args["kind"] = kind
        for key in ("start", "end"):
            if args.get(key) and not _ISO_RE.match(str(args[key])):
                return None, {"part": part, "route": route, "args": args,
                              "reason": f"{key} must be YYYY-MM-DD"}
    if route == "price_rows":
        dates = args.get("dates")
        if dates is not None:
            if not isinstance(dates, list) or not dates:
                return None, {"part": part, "route": route, "args": args,
                              "reason": "dates must be a non-empty list of YYYY-MM-DD"}
            for value in dates:
                if not _ISO_RE.match(str(value or "")):
                    return None, {"part": part, "route": route, "args": args,
                                  "reason": f"date {value!r} is not YYYY-MM-DD"}
        for key in ("start", "end"):
            if args.get(key) and not _ISO_RE.match(str(args[key])):
                return None, {"part": part, "route": route, "args": args,
                              "reason": f"{key} must be YYYY-MM-DD"}
        if args.get("event_doc"):
            key = str(args["event_doc"])
            prefix = (menu or {}).get("doc_prefix") or ""
            expanded = prefix + key if prefix and not key.startswith(prefix) else key
            if not _doc_key_ok(args["event_doc"], menu):
                return None, {"part": part, "route": route, "args": args,
                              "reason": f"event_doc {args['event_doc']!r} is not a document in the menu"}
            args["event_doc"] = expanded
        if args.get("event_time") and not _ISO_RE.match(str(args["event_time"])):
            return None, {"part": part, "route": route, "args": args,
                          "reason": "event_time must be YYYY-MM-DD or an ISO timestamp"}
        if not dates and not args.get("start") and not args.get("end") \
                and not args.get("event_doc") and not args.get("event_time"):
            return None, {"part": part, "route": route, "args": args,
                          "reason": "price_rows needs dates/start/end or event_doc/event_time"}
    if route == "holding" and args.get("category"):
        cats = _index(menu).get("categories") or []
        if cats and _norm(args["category"]) not in {_norm(c) for c in cats}:
            return None, {"part": part, "route": route, "args": args,
                          "reason": f"category {args['category']!r} is not a holding category the menu lists"}
    if args.get("doc_type"):
        typed = DOC_TYPE_ALIAS.get(str(args["doc_type"]).strip().lower(), str(args["doc_type"]).strip().lower())
        types = _index(menu).get("doc_types") or []
        if types and typed not in types:
            return None, {"part": part, "route": route, "args": args,
                          "reason": f"doc_type {args['doc_type']!r} is not a document type the menu prints "
                                    f"({', '.join(types)})"}
        args["doc_type"] = typed
    period = args.get("period")
    if period and route in ("fact", "fin", "kpi", "ratio", "cells", "statements") and not _period_ok(period, menu):
        return None, {"part": part, "route": route, "args": args,
                      "reason": f"period {period!r} is not a period the menu holds"}
    quarter = args.get("quarter_end")
    if quarter and not _ISO_RE.match(str(quarter)):
        return None, {"part": part, "route": route, "args": args, "reason": "quarter_end must be YYYY-MM-DD"}
    if "quarters" in args:
        try:
            args["quarters"] = int(args["quarters"])
        except (TypeError, ValueError):
            return None, {"part": part, "route": route, "args": args, "reason": "quarters must be an integer"}
        if not 1 <= args["quarters"] <= 12:
            return None, {"part": part, "route": route, "args": args, "reason": "quarters must be 1..12"}
    return {"part": part, "route": route, "args": dict(args)}, None


def validate(plan: dict, menu: dict | None = None) -> tuple[list[dict], list[dict]]:
    """``(ok_lookups, rejected)``: every route, part, argument name and menu name checked by the script."""
    if not isinstance(plan, dict):
        return [], [{"part": "", "route": "", "args": {}, "reason": "the plan is not a JSON object"}]
    raw_parts = plan.get("parts")
    part_ids: list[str] = []
    if isinstance(raw_parts, list):
        for i, part in enumerate(raw_parts):
            if isinstance(part, dict):
                part_ids.append(str(part.get("id") or f"p{i + 1}"))
            elif str(part or "").strip():
                part_ids.append(f"p{i + 1}")
    lookups = plan.get("lookups")
    if not isinstance(lookups, list):
        return [], [{"part": "", "route": "", "args": {}, "reason": "the plan has no lookups list"}]
    if not part_ids:
        part_ids = []
        for lookup in lookups:
            if isinstance(lookup, dict):
                part = str(lookup.get("part") or "").strip()
                if part and part not in part_ids:
                    part_ids.append(part)
        part_ids = part_ids or ["p1"]
    ok: list[dict] = []
    rejected: list[dict] = []
    for i, lookup in enumerate(lookups):
        if i >= MAX_LOOKUPS:
            rejected.append({"part": str((lookup or {}).get("part") or "") if isinstance(lookup, dict) else "",
                             "route": str((lookup or {}).get("route") or "") if isinstance(lookup, dict) else "",
                             "args": {}, "reason": f"more than {MAX_LOOKUPS} lookups"})
            continue
        good, bad = _check_one(lookup, part_ids, menu)
        if good:
            ok.append(good)
        if bad:
            rejected.append(bad)
    covered = {lookup["part"] for lookup in ok}
    for pid in part_ids:
        if pid not in covered:
            rejected.append({"part": pid, "route": "", "args": {},
                             "reason": "no lookup planned for this part: every part needs at least one lookup"})
    return ok, rejected


# --- the writer ---------------------------------------------------------------------------------------
def parse_plan(text: str) -> dict | None:
    """The first JSON object in the reply; ``None`` when the reply is not a usable object."""
    if not text:
        return None
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or not isinstance(data.get("lookups"), list):
        return None
    return data


def _parts(plan: dict) -> list[dict]:
    raw = plan.get("parts")
    parts: list[dict] = []
    if isinstance(raw, list):
        for i, part in enumerate(raw):
            if isinstance(part, dict):
                parts.append({"id": str(part.get("id") or f"p{i + 1}"),
                              "text": " ".join(str(part.get("text") or "").split())})
            elif str(part or "").strip():
                parts.append({"id": f"p{i + 1}", "text": " ".join(str(part).split())})
    if not parts:
        for lookup in plan.get("lookups") or []:
            if isinstance(lookup, dict) and str(lookup.get("part") or "").strip():
                pid = str(lookup["part"])
                if not any(p["id"] == pid for p in parts):
                    parts.append({"id": pid, "text": ""})
    return parts or [{"id": "p1", "text": ""}]


def _user(question: str, as_of: str, menu_text: str) -> str:
    return (f"QUESTION (asked as of {as_of or '-'}):\n{question}\n\nMENU:\n{menu_text}\n\n"
            "Write the plan as ONE JSON object and nothing else.")


def _repair_user(question: str, as_of: str, menu_text: str, problem: str, previous: str) -> str:
    return (f"QUESTION (asked as of {as_of or '-'}):\n{question}\n\nMENU:\n{menu_text}\n\n"
            f"YOUR PREVIOUS REPLY WAS NOT USABLE:\n{previous[:6000]}\n\nWHY IT WAS REJECTED:\n{problem}\n\n"
            "Return the CORRECTED plan as ONE JSON object and nothing else. Every route and name must come from the "
            "menu; drop a lookup whose name the menu does not print.")


def _cache_path(cache_dir, question: str, as_of: str, menu_text: str, model: str) -> Path:
    digest = hashlib.sha256(f"{CACHE_VERSION}\n{model}\n{as_of}\n{question}\n{menu_text}".encode("utf-8")).hexdigest()
    return Path(cache_dir) / f"plan_{digest[:32]}.json"


def write_plan(question: str, as_of: str, menu_text: str, model: str = MODEL, *,
               menu: dict | None = None, client: Callable[..., dict] | None = None,
               cache_dir: str | Path | None = None, key: str = "") -> dict:
    """ONE question, one model call (plus at most one repair), a validated plan.

    The result carries ``planner`` (``model`` or ``script_fallback``), ``parts``, ``lookups``, ``rejected``,
    ``model_calls``, ``raw_replies`` and ``seconds``.  Cached by (question, as_of, menu text, model) when
    ``cache_dir`` is given, so a rerun costs no model call.
    """
    agy_route = agy_call.is_agy_model(model)
    if not agy_route and "free" not in str(model).lower():
        raise ValueError(f"{model!r} is not a free model: this planner never calls a paid one")
    t0 = time.time()
    cache = _cache_path(cache_dir, question, as_of, menu_text, model) if cache_dir else None
    if cache is not None and cache.is_file():
        try:
            cached = json.loads(cache.read_text(encoding="utf-8"))
            cached["cached"] = True
            cached["model_calls"] = 0
            cached["seconds"] = round(time.time() - t0, 3)
            return cached
        except (OSError, json.JSONDecodeError):
            pass

    call = client or (agy_call.client_for(model, log_dir=Path(cache_dir) / "agy" if cache_dir else None)
                      if agy_route else call_model)
    api_key = key or ("" if (client or agy_route) else resolve_key())
    raw: list[str] = []
    calls = 0

    def ask(user: str) -> str | None:
        """One model call; ``None`` when the transport failed after its retries (the caller falls back)."""
        nonlocal calls
        calls += 1
        try:
            reply = call(SYSTEM, user, api_key)
        except RateLimited:
            raw.append("rate_limited")
            return None                     # one wait cycle exhausted: fall back to the script planner
        except RuntimeError as exc:
            raw.append(f"model_error: {exc}"[:4000])
            return None
        content = str(reply.get("content") or "")
        raw.append(content)
        return content

    def finish(result: dict) -> dict:
        result.update({"model": model, "model_calls": calls, "raw_replies": raw,
                       "seconds": round(time.time() - t0, 3), "cached": False})
        if cache is not None:
            try:
                cache.parent.mkdir(parents=True, exist_ok=True)
                cache.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
            except OSError:
                pass
        return result

    def fallback(reason: str) -> dict:
        return finish({"planner": "script_fallback", "reason": reason, "parts": [], "lookups": [],
                       "rejected": []})

    content = ask(_user(question, as_of, menu_text))
    if content is None:
        return fallback("the model call failed after its retries")
    plan = parse_plan(content)
    rejected: list[dict] = []
    if plan is not None:
        ok, rejected = validate(plan, menu)
        if not rejected:
            return finish({"planner": "model", "parts": _parts(plan), "lookups": ok, "rejected": []})
        problem = json.dumps(rejected, ensure_ascii=False)[:6000]
        content = ask(_repair_user(question, as_of, menu_text, problem, content))
        if content is None:
            return fallback("the repair model call failed after its retries")
        plan = parse_plan(content)
        if plan is None:
            return fallback("the repair reply was not valid JSON")
        ok, rejected = validate(plan, menu)
        return finish({"planner": "model", "parts": _parts(plan), "lookups": ok, "rejected": rejected})
    content = ask(_repair_user(question, as_of, menu_text, "the reply is not a JSON plan object", content))
    if content is None:
        return fallback("the repair model call failed after its retries")
    plan = parse_plan(content)
    if plan is None:
        return fallback("the reply was not valid JSON even after the repair call")
    ok, rejected = validate(plan, menu)
    return finish({"planner": "model", "parts": _parts(plan), "lookups": ok, "rejected": rejected})
