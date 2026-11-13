"""Retrieval-only evidence pack builder (no model calls).

plan(question, as_of) -> dict  (script only)
gather(db, symbol, plan, as_of, ...) -> dict (pack)
"""
from __future__ import annotations

import concurrent.futures
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVER_DIR = REPO_ROOT / "plugins" / "reality-data" / "server"
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

STOP_WORDS = {
    "what", "was", "were", "the", "a", "an", "of", "in", "for", "and", "to", "did", "do",
    "how", "much", "many", "is", "are", "it", "its", "this", "that", "these", "those",
    "at", "as", "by", "on", "with", "from", "or", "be", "been", "being", "have", "has",
    "had", "blue", "star", "aurobindo", "pharma", "consolidated", "standalone", "quarter",
    "year", "ended", "fy", "q1", "q2", "q3", "q4", "h1", "h2",
}

ROUTES_YAML = Path(__file__).with_name("routes.yaml")


def _load_routes():
    try:
        import yaml
        return yaml.safe_load(ROUTES_YAML.read_text(encoding="utf-8"))
    except Exception:
        return {"quotas": {}}


_ROUTES = _load_routes()


def _tokenize(s: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9]+", (s or "").lower())


def _metric_vocab() -> list[str]:
    names: set[str] = set()
    # kpi lexicon
    try:
        from reality_engine.pilot3 import kpi as _kpi
        entries, _ = _kpi.load_lexicon()
        for e in entries:
            names.add(e.metric)
    except Exception:
        pass
    try:
        from reality_engine.pilot3 import ratios as _ratios
        for f in getattr(_ratios, "FORMULAS", []):
            names.add(f[1])
    except Exception:
        pass
    try:
        from reality_engine.pilot3 import row_checks as _rc
        v = _rc.load_vocab()
        names.update(v.metrics.keys())
        names.update(v.alias.keys())
    except Exception:
        pass
    return sorted(names)


def _metric_tokens(m: str) -> set[str]:
    return set(_tokenize(m.replace("_", " ")))


def _extract_metrics(question: str) -> list[str]:
    toks = set(_tokenize(question))
    out = []
    for m in _metric_vocab():
        mt = _metric_tokens(m)
        if mt and mt.issubset(toks):
            out.append(m)
            continue
        ql = question.lower()
        phrase = m.lower().replace("_", " ")
        if re.search(r"\b" + re.escape(phrase) + r"\b", ql):
            out.append(m)
    # de-dupe
    seen = set()
    res = []
    for m in out:
        if m not in seen:
            seen.add(m)
            res.append(m)
    return res


def _current_quarter(as_of: str) -> str:
    try:
        y, m, _ = (as_of or "")[:10].split("-")
        yi, mi = int(y), int(m)
    except Exception:
        return "Q1FY26"
    if mi in (4, 5, 6):
        q, fy = 1, yi + 1
    elif mi in (7, 8, 9):
        q, fy = 2, yi + 1
    elif mi in (10, 11, 12):
        q, fy = 3, yi + 1
    else:
        q, fy = 4, yi
    return f"Q{q}FY{fy % 100:02d}"


def _current_fy(as_of: str) -> str:
    try:
        y, m, _ = (as_of or "")[:10].split("-")
        yi, mi = int(y), int(m)
    except Exception:
        return "FY26"
    fy = yi + 1 if mi > 3 else yi
    return f"FY{fy % 100:02d}"


def _normalize_period(p: str) -> str:
    return re.sub(r"\s+", "", p).upper()


_MONTHS = {"jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
           "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
           "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "oct": 10,
           "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12}


def _periods_from_date(iso: str) -> list[str]:
    out = []
    try:
        import datetime as _dt
        from reality_engine.pilot3 import row_checks as _rc
        d = _dt.date.fromisoformat(iso)
    except Exception:
        return out
    for fy in (d.year - 1, d.year, d.year + 1):
        two = fy % 100
        for label in (f"Q1FY{two:02d}", f"Q2FY{two:02d}", f"Q3FY{two:02d}", f"Q4FY{two:02d}",
                      f"H1FY{two:02d}", f"H2FY{two:02d}", f"9MFY{two:02d}", f"FY{two:02d}"):
            try:
                if _rc.period_end(label) == iso:
                    out.append(_normalize_period(label))
            except Exception:
                pass
    return out


def _extract_periods(question: str, as_of: str) -> list[str]:
    periods: set[str] = set()
    ql = question.lower()
    # explicit periods
    for pat in (r"Q[1-4]\s*FY\s*\d{2,4}", r"H[12]\s*FY\s*\d{2,4}", r"9M\s*FY\s*\d{2,4}",
                r"\bFY\s*\d{2,4}\b"):
        for m in re.finditer(pat, question, re.I):
            periods.add(_normalize_period(m.group(0)))
    # dates -> periods via row_checks calendar
    for m in re.finditer(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)\s+(\d{4})\b", question):
        day, mon, year = m.group(1), m.group(2).lower()[:3], m.group(3)
        # handle full month names too
        full = m.group(2).lower()
        mi = _MONTHS.get(full) or _MONTHS.get(mon)
        if mi:
            iso = f"{year}-{mi:02d}-{int(day):02d}"
            for p in _periods_from_date(iso):
                periods.add(p)
    for m in re.finditer(r"\b(\d{4})-(\d{2})-(\d{2})\b", question):
        iso = m.group(0)
        for p in _periods_from_date(iso):
            periods.add(p)
    # latest/last/this quarter
    if any(p in ql for p in ("latest quarter", "last quarter", "this quarter", "current quarter", "latest q")):
        periods.add(_current_quarter(as_of))
    if any(p in ql for p in ("latest year", "this year", "current year", "latest fy", "this fy")):
        periods.add(_current_fy(as_of))
    if not periods:
        periods.add(_current_quarter(as_of))
    return sorted(periods)


def _classify(question: str) -> str:
    ql = (question or "").lower()
    cats = []
    if any(w in ql for w in ("holding", "shareholding", "promoter", "fpi", "mutual fund", "insurance", "government")):
        cats.append("holding")
    if any(w in ql for w in ("price", "rsi", "gap", "volume", "moving average", "technical", "reaction", "52-week", "high", "low")):
        cats.append("price")
    if any(w in ql for w in ("guidance", "outlook", "target", "corridor")):
        cats.append("guidance")
    if any(w in ql for w in ("compute", "calculate", "ratio", "margin", " roe", " roce", " pe ", " pb ", "ev/ebitda", "growth", "days")):
        cats.append("compute")
    if any(w in ql for w in ("statement", "said", "management", "comment", "concall", "transcript", "what did")):
        cats.append("statement")
    if any(w in ql for w in ("list", "document", "filing", "which")):
        cats.append("list")
    if len(cats) >= 2:
        return "all"
    if cats:
        return cats[0]
    return "fact"


def plan(question: str, as_of: str = "", symbol: str = "") -> dict:
    metrics = _extract_metrics(question)
    periods = _extract_periods(question, as_of or "")
    # ratios subset
    ratio_names = set()
    try:
        import ratios as _ratios
        ratio_names = {f[1] for f in getattr(_ratios, "FORMULAS", [])}
    except Exception:
        pass
    ratios = [m for m in metrics if m in ratio_names]
    # topic words
    stop = set(STOP_WORDS)
    if symbol:
        for w in _tokenize(symbol):
            stop.add(w)
    topic_words = [w for w in _tokenize(question) if w not in stop]
    # remove company-ish capitalized? already lower
    kind = _classify(question)
    extra_stop = {"percentage", "percent", "change", "versus", "compared", "compare", "share", "how",
                  "much", "many", "what", "which", "when", "where", "move", "moved", "over", "preceding"}
    def _period_like(w):
        return bool(re.match(r"^(q[1-4]|h[12]|9m)fy\d{2,4}$", w)) or bool(re.match(r"^fy\d{2,4}$", w)) or w.isdigit()
    cells_words = [w for w in topic_words if (not _period_like(w)) and w not in extra_stop and len(w) >= 3]
    # de-dupe
    seen = set()
    uniq = []
    for w in cells_words:
        if w in seen:
            continue
        seen.add(w)
        uniq.append(w)
    cells_words = uniq
    cells_terms = " ".join(cells_words)
    return {
        "question": question,
        "as_of": as_of,
        "symbol": symbol,
        "kind": kind,
        "metrics": metrics,
        "periods": periods,
        "topic_words": topic_words,
        "noun_phrases": list(cells_words),
        "cells_terms": cells_terms,
        "cells_words": cells_words,
        "ratios": ratios,
    }


# ---- gather helpers ----

def _setup(db):
    os.environ["REALITY_PILOT3_DB"] = str(db)
    if str(SERVER_DIR) not in sys.path:
        sys.path.insert(0, str(SERVER_DIR))


def _asof_ok(known_at, as_of):
    if not known_at:
        return True
    ka = str(known_at)[:10]
    if not as_of:
        return True
    return ka <= str(as_of)[:10]


_ITEM_CAPS = (_ROUTES.get("per_item_caps") or {}) if isinstance(_ROUTES, dict) else {}


def _item_cap(route):
    return int(_ITEM_CAPS.get(route, _ITEM_CAPS.get("default", 6000)))


def _truncate_to_cap(text, route):
    cap = _item_cap(route)
    t = text or ""
    return t[:cap]

def _best_window(text, words, cap):
    t = text or ""
    if len(t) <= cap:
        return t
    low = t.lower()
    pos = 0
    for w in (words or []):
        i = low.find(str(w).lower())
        if i >= 0:
            pos = i
            break
    start = max(0, pos - cap // 2)
    if start + cap > len(t):
        start = max(0, len(t) - cap)
    return t[start:start + cap]


def _page_score(text, topic_words, phrase):
    low = (text or "").lower()
    score = 0
    for w in (topic_words or []):
        if w:
            score += low.count(str(w).lower())
    if phrase and str(phrase).lower() in low:
        score += 5
    return score

def _item(route, idx, doc_key="", doc_type="", page=None, known_at=None, text="", row=None, lookup=None):
    item = {
        "id": f"{route}-{idx}",
        "route": route,
        "doc_key": doc_key or "",
        "doc_type": doc_type or "",
        "page": page,
        "known_at": known_at,
        "text": _truncate_to_cap(text, route),
        "row": row,
    }
    if lookup is not None:
        item["lookup"] = lookup       # which planned lookup produced it (the coverage list reports its ids)
    return item


def _rows_of(reply):
    if isinstance(reply, list):
        return reply
    if isinstance(reply, dict):
        for k in ("rows", "items", "results", "data"):
            if isinstance(reply.get(k), list):
                return reply[k]
    return []


def _doc_key_of(r, reply=None):
    for key in ("doc_key", "document", "doc", "source"):
        if isinstance(r, dict) and r.get(key):
            return r.get(key)
    if isinstance(r, dict):
        prov = r.get("provenance")
        if isinstance(prov, dict):
            src = prov.get("source") or prov.get("doc_key")
            if src:
                src = re.sub(r"\s+p\d+\s*$", "", str(src))
                return src
    return ""


def _known_at_of(r):
    if isinstance(r, dict):
        for key in ("known_at", "known_at_utc", "filing_date", "date"):
            if r.get(key):
                return r.get(key)
        prov = r.get("provenance")
        if isinstance(prov, dict) and prov.get("known_at"):
            return prov.get("known_at")
    return None


def _page_of(r):
    if isinstance(r, dict):
        if r.get("page") is not None:
            return r.get("page")
        prov = r.get("provenance")
        if isinstance(prov, dict) and prov.get("page") is not None:
            return prov.get("page")
    return None


def _text_of(r):
    """An item's text: a typed row leads with its own value / unit / period, so the figure is readable, never
    only the raw quote it was extracted from (the raw XBRL value is in rupees, the row's value is in its unit)."""
    if isinstance(r, dict):
        head = ""
        value = r.get("value")
        if isinstance(value, (int, float, str)) and str(value).strip():
            head = " ".join(str(x) for x in (value, r.get("unit"), r.get("period")) if x not in (None, ""))
            if str(r.get("unit") or "").lower() == "inr" and isinstance(value, (int, float)) \
                    and abs(float(value)) >= 100000:
                head += f" (~{float(value) / 1e7:,.2f} crore)"   # the rupee row in the unit the filings quote
            if r.get("basis"):
                head += f" {r['basis']}"
            if r.get("formula"):
                head += f" | formula: {r['formula']}"
            head += " | "
        for key in ("text", "snippet", "quote", "content", "row"):
            if r.get(key):
                return head + str(r[key])
        return head + json.dumps(r, ensure_ascii=False, default=str)
    return str(r)


def _doc_type_of(r):
    if isinstance(r, dict):
        return r.get("doc_type") or r.get("type") or ""
    return ""


def _reply_to_items(route, reply, start=0, lookup=None):
    items = []
    if isinstance(reply, dict) and "error" in reply:
        return items
    rows = _rows_of(reply)
    if rows:
        for r in rows:
            items.append(_item(route, start + len(items) + 1,
                               doc_key=str(_doc_key_of(r, reply) or ""),
                               doc_type=_doc_type_of(r),
                               page=_page_of(r),
                               known_at=_known_at_of(r),
                               text=_text_of(r),
                               row=r if isinstance(r, dict) else None,
                               lookup=lookup))
    else:
        # single reply -> one item
        items.append(_item(route, start + 1,
                           doc_key=str(_doc_key_of(reply)) if isinstance(reply, dict) else "",
                           doc_type=_doc_type_of(reply) if isinstance(reply, dict) else "",
                           page=_page_of(reply) if isinstance(reply, dict) else None,
                           known_at=_known_at_of(reply) if isinstance(reply, dict) else None,
                           text=json.dumps(reply, ensure_ascii=False, default=str),
                           row=reply if isinstance(reply, dict) else None,
                           lookup=lookup))
    return items


def _dedupe(items):
    seen = set()
    out = []
    for it in items:
        key = (it.get("doc_key"), it.get("page"), (it.get("text") or "")[:120])
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out


def _apply_quota(items, quota):
    # group by route, cap
    by_route = {}
    for it in items:
        by_route.setdefault(it["route"], []).append(it)
    out = []
    for route, qs in by_route.items():
        cap = quota.get(route, len(qs))
        out.extend(qs[:cap])
    return out


def gather(db, symbol, plan, as_of, max_chars: int = 120000, quota: dict = None,  # type: ignore[assignment]
           lookups: list | None = None, parts: list | None = None):
    _setup(db)
    import lookups_pilot3 as p3
    import lookups_semantic
    import lookups_tech

    if not str(symbol or "").strip():
        raise ValueError("gather needs the company symbol: an empty symbol silently disables every lookup")
    if not quota:
        quota = _ROUTES.get("quotas", {}) or {}

    t0 = time.time()
    tasks = []  # (route, fn)
    route_errors = []

    topic_words = plan.get("topic_words") or []
    phrase = " ".join(topic_words) if topic_words else (plan.get("question") or "")
    cells_words = plan.get("cells_words") or []
    if not cells_words:
        cells_words = [w for w in (plan.get("topic_words") or []) if len(w) >= 3]
    # variants: strip common prefixes so "unallocable" also tries "allocable"
    variants = set(cells_words)
    for w in list(cells_words):
        for pref in ("un", "non", "in", "dis", "im"):
            if w.startswith(pref) and len(w) > len(pref) + 3:
                variants.add(w[len(pref):])
    cells_words = list(variants)
    cells_phrase = " ".join(cells_words)
    tasks.append(("semantic", lambda: lookups_semantic.semantic(symbol=symbol, query=phrase, limit=8, as_of=as_of)))
    tasks.append(("search", lambda: p3.search(symbol=symbol, query=phrase, as_of=as_of)))
    for w in cells_words:
        ww = w
        tasks.append(("search", lambda ww=ww: p3.search(symbol=symbol, query=ww, as_of=as_of)))
    tasks.append(("topic", lambda: p3.topic(symbol=symbol, topic=phrase, limit=25, as_of=as_of)))

    kind = plan.get("kind", "fact")
    kinds = [kind] if kind != "all" else ["fact", "statement", "list", "guidance", "compute", "price", "holding"]
    metrics = [m for m in (plan.get("metrics") or []) if m]
    periods = plan.get("periods") or [None]
    if not periods:
        periods = [None]
    ratios = plan.get("ratios") or []

    exact_metrics = metrics

    if "fact" in kinds or kind == "all":
        # exact metric routes
        for m in (exact_metrics if exact_metrics else []):
            for p in periods:
                mm, pp = m, p
                tasks.append(("fact", lambda mm=mm, pp=pp: p3.fact(symbol=symbol, metric=mm, period=pp, as_of=as_of)))
                tasks.append(("fin", lambda mm=mm, pp=pp: p3.fin(symbol=symbol, measure=mm, period=pp, as_of=as_of)))
                tasks.append(("cells", lambda mm=mm, pp=pp: p3.cells(symbol=symbol, terms=mm, period=pp, as_of=as_of)))
        for m in (exact_metrics if exact_metrics else []):
            for p in periods:
                mm, pp = m, p
                tasks.append(("kpi", lambda mm=mm, pp=pp: p3.kpi(symbol=symbol, kpi=mm, period=pp, as_of=as_of)))
        # cells for each noun word (label search needs all words; single words maximise recall)
        for w in cells_words:
            for p in periods:
                ww, pp = w, p
                tasks.append(("cells", lambda ww=ww, pp=pp: p3.cells(symbol=symbol, terms=ww, period=pp, as_of=as_of)))
        # fin with the joined phrase only when no exact metric (avoid noisy not_found otherwise)
        if (not exact_metrics) and cells_phrase:
            for p in periods:
                cp, pp = cells_phrase, p
                tasks.append(("fin", lambda cp=cp, pp=pp: p3.fin(symbol=symbol, measure=cp, period=pp, as_of=as_of)))
    if "guidance" in kinds:
        tasks.append(("guidance", lambda: p3.guidance(symbol=symbol, as_of=as_of)))
    if "compute" in kinds:
        rlist = ratios if ratios else exact_metrics
        for r in (rlist if rlist else []):
            rr = r
            tasks.append(("ratio", lambda rr=rr: p3.ratio(symbol=symbol, ratio=rr, as_of=as_of)))
        # cells/fin for inputs
        for m in (exact_metrics if exact_metrics else []):
            for p in periods:
                mm, pp = m, p
                tasks.append(("cells", lambda mm=mm, pp=pp: p3.cells(symbol=symbol, terms=mm, period=pp, as_of=as_of)))
                tasks.append(("fin", lambda mm=mm, pp=pp: p3.fin(symbol=symbol, measure=mm, period=pp, as_of=as_of)))
        for w in cells_words:
            for p in periods:
                ww, pp = w, p
                tasks.append(("cells", lambda ww=ww, pp=pp: p3.cells(symbol=symbol, terms=ww, period=pp, as_of=as_of)))
        if cells_phrase and not exact_metrics:
            for p in periods:
                cp, pp = cells_phrase, p
                tasks.append(("fin", lambda cp=cp, pp=pp: p3.fin(symbol=symbol, measure=cp, period=pp, as_of=as_of)))
    if "price" in kinds:
        tasks.append(("tech", lambda: lookups_tech.tech(symbol=symbol, kind="range", as_of=as_of)))
        tasks.append(("tech", lambda: lookups_tech.tech(symbol=symbol, kind="reaction", as_of=as_of, doc_type="results")))
    if "holding" in kinds:
        tasks.append(("holding", lambda: p3.holding(symbol=symbol, as_of=as_of)))

    # Union (T-205 round 5): the round-3 script routes run exactly as before, at full quota, AND the model's plan
    # lookups run on top.  A plan lookup never replaces a script route; the script keeps its own quota net.
    lookup_meta = {}
    extra_meta = {}
    if lookups is not None:
        plan_tasks = []
        for i, lookup in enumerate(lookups):
            route = str(lookup.get("route") or "")
            args = {k: v for k, v in (lookup.get("args") or {}).items() if k not in ("symbol", "as_of")}
            lookup_meta[i] = {"part": str(lookup.get("part") or ""), "route": route, "args": dict(args)}
            plan_tasks.append((i, route, lambda route=route, args=args: _run_lookup(
                p3, lookups_semantic, lookups_tech, route, symbol, args, as_of)))
        tasks = [(None, route, fn) for route, fn in tasks] + plan_tasks
    else:
        tasks = [(None, route, fn) for route, fn in tasks]

    def run_tasks(batch):
        replies = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            futmap = {ex.submit(fn): (idx, route) for idx, route, fn in batch}
            for fut in concurrent.futures.as_completed(futmap):
                idx, route = futmap[fut]
                try:
                    rep = fut.result()
                except Exception as exc:
                    rep = {"error": str(exc)}
                replies.setdefault((idx, route), []).append(rep)
        return replies

    route_replies = run_tasks(tasks)

    # Round 2, deterministic script retries beside the plan:
    #  * an empty planned lookup is retried without its period, then with each significant word of terms/query alone;
    #  * a fin/fact metric+period also fetches the printed cells for that metric and period;
    #  * a search/statement hit in a call or deck reads the full page of its top 3 hits.
    if lookups is not None:
        next_id = 100000
        round2 = []
        seen_derived: set[tuple] = set()
        for i, meta in lookup_meta.items():
            replies = route_replies.get((i, meta["route"])) or []
            empty = all(isinstance(rep, dict) and ("error" in rep or rep.get("found") is False
                                                   or not _rows_of(rep)) for rep in replies)
            if empty:
                for retry in retry_args(meta["route"], meta["args"]):
                    rid = next_id
                    next_id += 1
                    extra_meta[rid] = {"part": meta["part"], "route": meta["route"], "args": retry,
                                       "kind": "retry", "of": i}
                    round2.append((rid, meta["route"],
                                   lambda route=meta["route"], retry=retry: _run_lookup(
                                       p3, lookups_semantic, lookups_tech, route, symbol, retry, as_of)))
            printed = cells_for(meta["route"], meta["args"])
            if printed:
                key = ("cells", json.dumps(printed, sort_keys=True))
                if key not in seen_derived:
                    seen_derived.add(key)
                    rid = next_id
                    next_id += 1
                    extra_meta[rid] = {"part": meta["part"], "route": "cells", "args": printed,
                                       "kind": "derived", "of": i}
                    round2.append((rid, "cells", lambda a=printed: _run_lookup(
                        p3, lookups_semantic, lookups_tech, "cells", symbol, a, as_of)))
            if meta["route"] in ("search", "statements"):
                for doc_key, page, doc_type in page_hits(replies, limit=3):
                    key = ("page", doc_key, page)
                    if key in seen_derived:
                        continue
                    seen_derived.add(key)
                    rid = next_id
                    next_id += 1
                    page_args = {"doc_key": doc_key, "page": page, "doc_type": doc_type}
                    extra_meta[rid] = {"part": meta["part"], "route": "page", "args": page_args,
                                       "kind": "derived", "of": i}
                    round2.append((rid, "page", lambda a=page_args: _run_lookup(
                        p3, lookups_semantic, lookups_tech, "page", symbol, a, as_of)))
        if round2:
            for key, reps in run_tasks(round2).items():
                route_replies.setdefault(key, []).extend(reps)

    # convert to items
    all_items = []
    route_stats = {}
    lookup_found = {}
    route_counter = {}
    for (idx, route), replies in route_replies.items():
        ritems = []
        meta = lookup_meta.get(idx) or extra_meta.get(idx) or {}
        for rep in replies:
            if isinstance(rep, dict):
                if "error" in rep:
                    route_errors.append({"route": route, "args": meta.get("args"),
                                         "error": rep.get("error")})
                    if idx is not None:
                        lookup_found[idx] = {"found": False, "error": str(rep.get("error") or "")}
                    continue
                if rep.get("found") is False:
                    route_errors.append({"route": route, "args": meta.get("args"), "found": False,
                                         "hint": rep.get("hint"),
                                         "available": (rep.get("available") or rep.get("metrics_matched"))})
                    if idx is not None:
                        lookup_found[idx] = {"found": False, "hint": rep.get("hint"),
                                             "available": (rep.get("available") or rep.get("metrics_matched"))}
                    continue
            start = route_counter.get(route, 0)
            new_items = _reply_to_items(route, rep, start=start, lookup=idx)
            route_counter[route] = start + len(new_items)
            ritems.extend(new_items)
        # as_of drop
        ritems = [it for it in ritems if _asof_ok(it.get("known_at"), as_of)]
        # dedupe within route
        ritems = _dedupe(ritems)
        route_stats[route] = {"returned": len(ritems), "kept": 0, "cut": 0}
        all_items.extend((route, it) for it in ritems)
        if idx is not None and idx not in lookup_found:
            lookup_found[idx] = {"found": bool(ritems)}

    # flatten
    flat_items = [it for (_, it) in all_items]

    # page reads for statement/list/guidance kinds (round-3 behaviour, kept in the union too)
    if any(k in kinds for k in ("statement", "list", "guidance")) or kind == "all":
        p3mod = p3
        _p3ask = None
        try:
            import p3ask as _p3ask
        except Exception:
            try:
                from reality_engine.scripts import p3ask as _p3ask
            except Exception:
                _p3ask = None

        def _fetch_page(dk, pg):
            if _p3ask is None:
                return None
            try:
                return _p3ask._page(p3mod, str(dk), int(pg), as_of=as_of, max_chars=6000)
            except Exception:
                return None

        def _fetch_next(dk, pg):
            if _p3ask is None:
                return None
            try:
                return _p3ask._page(p3mod, str(dk), int(pg) + 1, as_of=as_of, max_chars=6000)
            except Exception:
                return None

        def _best_window_local(txt):
            return _best_window(txt or "", topic_words, _item_cap("page"))

        def _emit_page(dk, pg, doc_type, ka_fallback):
            rep = _fetch_page(dk, pg)
            if not (isinstance(rep, dict) and rep.get("rows")):
                return []
            out = []
            for row in rep["rows"]:
                txt = row.get("text") if isinstance(row, dict) else str(row)
                page_no = row.get("page") if isinstance(row, dict) else pg
                ka = row.get("known_at") if isinstance(row, dict) else ka_fallback
                if not _asof_ok(ka, as_of):
                    continue
                txt = _best_window_local(txt)
                out.append(_item("page", len(flat_items) + len(out) + 1,
                                 doc_key=dk, doc_type=doc_type or "",
                                 page=page_no, known_at=ka, text=txt))
            try:
                nrep = _fetch_next(dk, pg)
                if isinstance(nrep, dict) and nrep.get("rows"):
                    for row in nrep["rows"]:
                        txt = row.get("text") if isinstance(row, dict) else str(row)
                        page_no = row.get("page") if isinstance(row, dict) else (pg + 1)
                        ka = row.get("known_at") if isinstance(row, dict) else ka_fallback
                        if not _asof_ok(ka, as_of):
                            continue
                        txt = _best_window_local(txt)
                        out.append(_item("page", len(flat_items) + len(out) + 1,
                                         doc_key=dk, doc_type=doc_type or "",
                                         page=page_no, known_at=ka, text=txt))
            except Exception:
                pass
            return out

        def _best_page_for_doc(dk):
            try:
                q = "SELECT page, text, known_at FROM doc_page WHERE doc_key = '%s'" % str(dk).replace(chr(39), "")
                rep = p3mod.sql(q, limit=200, max_chars=8000, as_of=as_of)
            except Exception:
                rep = None
            pages = _rows_of(rep) if rep else []
            if not pages:
                return None
            best = None
            best_score = -1
            for pgrow in pages:
                if isinstance(pgrow, dict):
                    pgno = pgrow.get("page")
                    txt = pgrow.get("text")
                    ka = pgrow.get("known_at")
                elif isinstance(pgrow, (list, tuple)):
                    pgno = pgrow[0] if len(pgrow) > 0 else None
                    txt = pgrow[1] if len(pgrow) > 1 else ""
                    ka = pgrow[2] if len(pgrow) > 2 else None
                else:
                    pgno = None
                    txt = str(pgrow)
                    ka = None
                if not _asof_ok(ka, as_of):
                    continue
                sc = _page_score(txt or "", topic_words, " ".join(topic_words))
                if sc > best_score:
                    best_score = sc
                    best = (pgno, ka)
            if best is None and pages:
                first = pages[0]
                if isinstance(first, dict):
                    best = (first.get("page"), first.get("known_at"))
                elif isinstance(first, (list, tuple)):
                    best = (first[0] if len(first)>0 else None, first[2] if len(first)>2 else None)
                else:
                    best = (None, None)
            return best

        # semantic best page per transcript doc
        sem_page_by_doc = {}
        for it in flat_items:
            if it.get("route") == "semantic":
                dk = it.get("doc_key")
                pg = it.get("page")
                if dk and pg is not None and dk not in sem_page_by_doc:
                    sem_page_by_doc[dk] = pg

        transcript_docs = []
        try:
            drep = p3mod.docs(symbol=symbol, doc_type="transcript", as_of=as_of, limit=50)
            for r in _rows_of(drep):
                dk = _doc_key_of(r, drep)
                if dk:
                    transcript_docs.append((str(dk), _doc_type_of(r) or "transcript", _known_at_of(r)))
        except Exception:
            transcript_docs = []

        # semantic query vector for per-page ranking (cached; may be unavailable)
        _qv = None
        _matrix = None
        _rowmap = None
        try:
            import lookups_semantic as _ls
            _qv, _ = _ls._query_vector(phrase or (plan.get("question") or ""), "8b")
            _matrix, _rowmap = _ls._vectors("8b")
        except Exception:
            _qv = None

        def _best_pages_for_doc(dk, n=2):
            try:
                q = "SELECT page, text, known_at FROM doc_page WHERE doc_key = '%s'" % str(dk).replace(chr(39), "")
                rep = p3mod.sql(q, limit=500, max_chars=8000, as_of=as_of)
            except Exception:
                rep = None
            pages = _rows_of(rep) if rep else []
            if not pages:
                return []
            scored = []
            for pgrow in pages:
                if isinstance(pgrow, dict):
                    pgno = pgrow.get("page")
                    txt = pgrow.get("text")
                    ka = pgrow.get("known_at")
                elif isinstance(pgrow, (list, tuple)):
                    pgno = pgrow[0] if len(pgrow) > 0 else None
                    txt = pgrow[1] if len(pgrow) > 1 else ""
                    ka = pgrow[2] if len(pgrow) > 2 else None
                else:
                    pgno = None
                    txt = str(pgrow)
                    ka = None
                if not _asof_ok(ka, as_of):
                    continue
                if pgno is None:
                    continue
                sc = _page_score(txt or "", topic_words, " ".join(topic_words))
                if _qv is not None and _matrix is not None and _rowmap is not None:
                    try:
                        idx = _rowmap.get((str(dk), int(pgno)))
                        if idx is not None:
                            sc = sc + float((_matrix[idx] @ _qv)) * 10.0
                    except Exception:
                        pass
                scored.append((sc, pgno, ka))
            if not scored:
                return []
            scored.sort(key=lambda x: x[0], reverse=True)
            out = []
            seen_pg = set()
            for sc, pgno, ka in scored:
                if pgno in seen_pg:
                    continue
                seen_pg.add(pgno)
                out.append((pgno, ka))
                if len(out) >= n:
                    break
            return out

        transcript_docs.sort(key=lambda x: (x[2] or ""), reverse=True)
        for dk, dt, ka in transcript_docs[:8]:
            for bp_pg, bp_ka in _best_pages_for_doc(dk, 2):
                if bp_pg is None:
                    continue
                flat_items.extend(_emit_page(dk, int(bp_pg), dt, bp_ka or ka))

        sem_items = [it for it in flat_items if it["route"] == "semantic"]
        deckres = []
        seen_docs = set()
        for it in sem_items:
            dt = (it.get("doc_type") or "").lower()
            if dt not in ("deck", "results", "result", "presentation"):
                continue
            key = it.get("doc_key")
            if key in seen_docs:
                continue
            seen_docs.add(key)
            deckres.append(it)
            if len(deckres) >= 3:
                break
        for it in deckres:
            dk = it.get("doc_key")
            pg = it.get("page")
            if not dk or pg is None:
                continue
            flat_items.extend(_emit_page(dk, int(pg), it.get("doc_type", ""), it.get("known_at")))

    # as_of drop (plan items are deduped after the split, so a plan item always wins its duplicate text)
    flat_items = [it for it in flat_items if _asof_ok(it.get("known_at"), as_of)]

    # Union order and quota: the plan gets its own quota and the round-3 script net keeps its full one, so a plan
    # lookup can never eat a script item of the same route.
    plan_items = _dedupe([it for it in flat_items if it.get("lookup") is not None])
    plan_keys = {_item_key(it) for it in plan_items}
    script_items = [it for it in _dedupe([it for it in flat_items if it.get("lookup") is None])
                    if _item_key(it) not in plan_keys]
    plan_items = _apply_quota(plan_items, quota)
    script_items = _apply_quota(script_items, quota)

    periods = set(plan.get("periods") or [])
    def _period_match(it):
        txt = (it.get("text") or "")
        for p in periods:
            if p and p.lower() in txt.lower():
                return 0
        return 1

    # plan items: by part, then the order the plan wrote its lookups (a retry/derived item follows its lookup)
    part_order = {str(p.get("id") if isinstance(p, dict) else p): n for n, p in enumerate(parts or [])}
    lookup_part = {i: str(m.get("part") or "") for i, m in lookup_meta.items()}
    lookup_seq = {i: i for i in lookup_meta}

    def _plan_key(it):
        i = it.get("lookup")
        seq = lookup_seq.get(i, i if isinstance(i, int) else 0)
        return (part_order.get(lookup_part.get(i, ""), len(part_order)), seq)

    plan_items.sort(key=_plan_key)

    # script items: round-3 round-robin across routes (period match, then known_at)
    by_route = {}
    for it in script_items:
        by_route.setdefault(it["route"], []).append(it)
    for r in by_route:
        by_route[r].sort(key=lambda it: (_period_match(it),))
        by_route[r].sort(key=lambda it: (it.get("known_at") or ""), reverse=True)
        by_route[r].sort(key=lambda it: (_period_match(it),))
    merged = []
    routes = list(by_route.keys())
    idx = {r: 0 for r in routes}
    while True:
        progressed = False
        for r in routes:
            if idx[r] < len(by_route[r]):
                merged.append(by_route[r][idx[r]])
                idx[r] += 1
                progressed = True
        if not progressed:
            break
    script_items = merged
    flat_items = plan_items + script_items

    # total cap: a plan item is never dropped; script items are dropped from the end once the cap is reached
    kept = []
    dropped = []
    total = 0
    for it in flat_items:
        tlen = len(it.get("text") or "")
        sep = 2 if kept else 0
        if it.get("lookup") is not None or total + sep + tlen <= max_chars:
            kept.append(it)
            total += sep + tlen
        else:
            dropped.append(it)
    plan_over_cap = total > max_chars
    # log what was cut
    try:
        import sys as _sys
        for it in dropped:
            _sys.stderr.write("cut: %s %s p%s (%d chars)\n" % (it.get("route"), it.get("doc_key"), it.get("page"), len(it.get("text") or "")))
    except Exception:
        pass
    cut_log = ["%s %s p%s (%d chars)" % (it.get("route"), it.get("doc_key"), it.get("page"), len(it.get("text") or "")) for it in dropped]

    # route stats final
    for route in set(it["route"] for it in flat_items):
        route_stats.setdefault(route, {"returned": 0, "kept": 0, "cut": 0})
    for route in route_stats:
        r_all = [it for it in flat_items if it["route"] == route]
        r_kept = [it for it in kept if it["route"] == route]
        route_stats[route]["returned"] = len(r_all)
        route_stats[route]["kept"] = len(r_kept)
        route_stats[route]["cut"] = len(r_all) - len(r_kept)

    text = "\n\n".join(it.get("text") or "" for it in kept)
    routes_nonempty = sorted({it["route"] for it in kept})

    coverage = []
    if lookups is not None:
        kept_by_lookup: dict[int, list[str]] = {}
        for it in kept:
            if it.get("lookup") is not None:
                kept_by_lookup.setdefault(it["lookup"], []).append(it["id"])
        for part in (parts or []):
            pid = str(part.get("id") if isinstance(part, dict) else part)
            ptext = str(part.get("text") if isinstance(part, dict) else "")
            entries = []
            for i, meta in lookup_meta.items():
                if str(meta["part"]) != pid:
                    continue
                info = lookup_found.get(i) or {"found": False}
                retries = []
                derived = []
                for rid, em in extra_meta.items():
                    if em.get("of") != i:
                        continue
                    items = kept_by_lookup.get(rid, [])
                    record = {"route": em["route"], "args": em["args"],
                              "found": bool(items),          # zero items is not found (T-205 round 6)
                              "items": items}
                    (retries if em["kind"] == "retry" else derived).append(record)
                base_items = kept_by_lookup.get(i, [])
                base_found = bool(base_items)          # a reply with rows that all dedupe away has 0 items
                found = base_found or any(r["found"] for r in retries) or any(d["found"] for d in derived)
                entries.append({"route": meta["route"], "args": meta["args"], "found": found,
                                "base_found": base_found, "items": base_items,
                                "retries": retries, "derived": derived,
                                "error": str(info.get("error") or ""), "hint": info.get("hint")})
            status = part_status(entries)
            coverage_entry = {"part": pid, "text": ptext, "lookups": entries,
                              "found": status == "found", "status": status}
            if not entries:
                coverage_entry["reason"] = "no lookup planned"
            coverage.append(coverage_entry)

    pack = {
        "symbol": symbol,
        "as_of": as_of,
        "plan": plan,
        "planner": "model" if lookups is not None else "script",
        "parts": parts or [],
        "coverage": coverage,
        "items": kept,
        "text": text,
        "chars": len(text),
        "pack_chars": len(text),
        "items_count": len(kept),
        "plan_items": sum(1 for it in kept if it.get("lookup") is not None),
        "script_items": sum(1 for it in kept if it.get("lookup") is None),
        "plan_over_cap": plan_over_cap,
        "routes_nonempty": routes_nonempty,
        "route_stats": route_stats,
        "route_errors": route_errors,
        "cut_log": cut_log,
        "seconds": round(time.time() - t0, 3),
    }
    return pack


def part_status(entries: list[dict]) -> str:
    """``found`` (every lookup for the part returned items), ``none`` (no lookup did), else ``some``."""
    if not entries:
        return "none"
    hits = sum(1 for e in entries if e.get("found"))
    if hits == len(entries):
        return "found"
    return "some" if hits else "none"


def _item_key(it: dict) -> tuple:
    return (it.get("doc_key"), it.get("page"), (it.get("text") or "")[:120])


def retry_args(route: str, args: dict) -> list[dict]:
    """The deterministic script retries for a planned lookup that returned nothing (T-205 round 5).

    Round 3's word sweep: the same lookup without its period, then once per significant word of ``terms``/``query``
    alone.  A page or price lookup is not retried (it either exists or does not).
    """
    if route in ("page", "price_rows"):
        return []
    base = {k: v for k, v in args.items() if k != "period"}
    out: list[dict] = []
    if base != args:
        out.append(dict(base))
    key = "terms" if "terms" in args else "query" if "query" in args else None
    if key:
        words = [w for w in _tokenize(str(args.get(key) or "")) if len(w) >= 3 and w not in STOP_WORDS]
        for word in words[:6]:
            forms = [word]
            for pref in ("un", "non", "in", "dis", "im"):     # round 3's variants: unallocable -> allocable
                if word.startswith(pref) and len(word) > len(pref) + 3:
                    forms.append(word[len(pref):])
            for form in forms:
                retry = {k: v for k, v in base.items() if k != key}
                retry[key] = form
                out.append(retry)
    return out[:8]


def cells_for(route: str, args: dict) -> dict | None:
    """The printed `cells` lookup that must accompany a planned fin/fact metric+period (T-205 round 5)."""
    period = args.get("period")
    if not period:
        return None
    metric = args.get("measure") if route == "fin" else args.get("metric") if route == "fact" else None
    if not metric:
        return None
    return {"terms": str(metric), "period": str(period)}


def page_hits(replies: list, limit: int = 3) -> list[tuple[str, int, str]]:
    """The first ``limit`` distinct (doc_key, page, doc_type) hits in a call or deck, for a full-page read."""
    out: list[tuple[str, int, str]] = []
    seen: set[tuple[str, int]] = set()
    for rep in replies:
        for row in _rows_of(rep):
            if not isinstance(row, dict):
                continue
            doc_type = str(_doc_type_of(row) or ((row.get("provenance") or {}) if isinstance(row.get("provenance"), dict) else {}).get("doc_type") or "").lower()
            if doc_type not in ("transcript", "deck"):
                continue
            doc_key, page = row.get("doc_key"), row.get("page")
            if not doc_key or page is None:
                continue
            try:
                page = int(page)
            except (TypeError, ValueError):
                continue
            key = (str(doc_key), page)
            if key in seen:
                continue
            seen.add(key)
            out.append((key[0], page, doc_type))
            if len(out) >= limit:
                return out
    return out


def _run_lookup(p3, lookups_semantic, lookups_tech, route, symbol, args, as_of):
    """Run one validated planned lookup; the symbol and the as_of are injected here, never taken from the plan."""
    if route == "semantic":
        return lookups_semantic.semantic(symbol=symbol, query=str(args.get("query") or ""), limit=8, as_of=as_of)
    if route == "tech":
        return lookups_tech.tech(symbol=symbol, as_of=as_of, **args)
    if route == "price_rows":
        from reality_engine.answer import lookups_extra
        return lookups_extra.price_rows(p3, symbol, as_of, **args)
    if route == "holding":
        from reality_engine.answer import lookups_extra
        reply = p3.holding(symbol=symbol, as_of=as_of, **args)
        if isinstance(reply, dict) and reply.get("found"):
            try:
                extra = lookups_extra.holding_share_rows(p3, str(reply.get("symbol") or symbol), args, reply)
            except Exception as exc:                     # a share-count join must never fail the holding lookup
                extra = []
                reply = dict(reply)
                reply["share_count_error"] = str(exc)
            if extra:
                reply = dict(reply)
                reply["rows"] = list(reply.get("rows") or []) + extra
        return reply
    if route == "page":
        try:
            import p3ask as _p3ask
        except Exception:
            from reality_engine.scripts import p3ask as _p3ask
        return _p3ask._page(p3, str(args.get("doc_key") or ""), int(args.get("page") or 1),
                            to_page=args.get("to_page"), as_of=as_of, max_chars=6000)
    if route not in ("fact", "fin", "kpi", "ratio", "cells", "guidance", "holding",
                     "statements", "docs", "search", "topic"):
        return {"error": f"unknown planned route {route!r}"}
    return getattr(p3, route)(symbol=symbol, as_of=as_of, **args)



_PATH_RE = re.compile(r"[A-Za-z]:[/\\][^\s\"',]+")


def _clean_value(value):
    """Drop a row's provenance blob, absolute file paths and null/empty fields; keep every figure and quote."""
    if isinstance(value, dict):
        return {k: _clean_value(v) for k, v in value.items()
                if k != "provenance" and v not in (None, "", [], {})}
    if isinstance(value, list):
        return [_clean_value(v) for v in value]
    if isinstance(value, str):
        return _PATH_RE.sub("", value)
    return value


def _row_text(it: dict) -> str:
    body = str(it.get("text") or "")
    if body[:1] in ("{", "["):
        try:
            return json.dumps(_clean_value(json.loads(body)), ensure_ascii=False, default=str)
        except (ValueError, TypeError):
            pass
    if not body and it.get("row") is not None:
        return json.dumps(_clean_value(it["row"]), ensure_ascii=False, default=str)
    return body


def _reading_block(index: int, it: dict) -> str:
    head = f"[{index}] {it.get('route')} doc={it.get('doc_key') or '-'} p{it.get('page')}"
    if it.get("known_at"):
        head += f" known={it.get('known_at')}"
    return f"{head}\n{_row_text(it)}"

_TYPED_ROUTES = frozenset({"cells", "fin", "fact", "kpi", "holding", "price", "price_rows", "ratio", "guidance"})
_NUM_RE = re.compile(r"\d[\d,]*\.?\d*")


def _carries_number(text: str) -> bool:
    for m in _NUM_RE.finditer(text or ""):
        raw = m.group(0)
        if "." in raw or len(raw.replace(",", "")) >= 3:
            return True
    return False


def _query_terms(pack: dict) -> list[str]:
    plan = pack.get("plan") or {}
    terms = [str(w) for w in (plan.get("topic_words") or []) if w]
    terms += [w for w in _tokenize(str(plan.get("question") or "")) if len(w) >= 3 and w not in STOP_WORDS]
    return list(dict.fromkeys(terms))


def reading_text(pack: dict, max_chars: int = 150000) -> str:
    """The reading copy: question, parts, coverage, then each item as round 6 printed it -- a lead line plus the row
    content (quote and every numeric field) or the whole page/statement text.

    Only allowed trimming: a row's provenance blob, absolute file paths and null/empty fields are removed, and an
    identical item prints once.  Over ``max_chars`` script page/rest items are dropped from the lowest rank up and
    logged in ``reading_cut``; typed rows and plan items are never dropped.
    """
    head = [f"QUESTION (as of {pack.get('as_of') or '-'}):", str((pack.get("plan") or {}).get("question") or ""), ""]
    parts = pack.get("parts") or []
    if parts:
        head.append("PARTS:")
        for part in parts:
            head.append(f"  {part.get('id')}: {part.get('text') or ''}")
        head.append("")
    if pack.get("coverage"):
        head.append("COVERAGE (part-level status, then every lookup):")
        for part in pack["coverage"]:
            pid = part.get("part") or part.get("id") or ""
            head.append(f"  {pid} [{part.get('status') or 'none'}] {part.get('text') or ''}"
                        + (f" -- {part['reason']}" if part.get("reason") else ""))
            for entry in part.get("lookups") or []:
                args = json.dumps(entry.get("args") or {}, ensure_ascii=False)
                marker = "found" if entry.get("base_found") else "NOT FOUND"
                head.append(f"    {entry.get('route')} {args} -> {marker}, "
                            f"{len(entry.get('items') or [])} items")
                for retry in entry.get("retries") or []:
                    head.append(f"      retry {retry.get('route')} "
                                f"{json.dumps(retry.get('args') or {}, ensure_ascii=False)} -> "
                                f"{'found' if retry.get('found') else 'NOT FOUND'}, "
                                f"{len(retry.get('items') or [])} items")
                for derived in entry.get("derived") or []:
                    head.append(f"      derived {derived.get('route')} "
                                f"{json.dumps(derived.get('args') or {}, ensure_ascii=False)} -> "
                                f"{'found' if derived.get('found') else 'NOT FOUND'}, "
                                f"{len(derived.get('items') or [])} items")
        head.append("")
    prefix = "\n".join(head)
    items = pack.get("items") or []
    part_ids = [str(p.get("id") if isinstance(p, dict) else p) for p in parts] or ["p1"]
    item_part = {}
    for cov in pack.get("coverage") or []:
        pid = cov.get("part") or "p1"
        for entry in cov.get("lookups") or []:
            for sub in [entry] + list(entry.get("retries") or []) + list(entry.get("derived") or []):
                for iid in sub.get("items") or []:
                    item_part[str(iid)] = pid
    part_order = {pid: n for n, pid in enumerate(part_ids)}

    def _group(it: dict) -> int:
        text = it.get("text") or ""
        periods = [str(p) for p in (pack.get("plan") or {}).get("periods") or [] if p]
        if _carries_number(text) and any(p.lower() in text.lower() for p in periods):
            return 0
        if it.get("route") in _TYPED_ROUTES:
            return 1
        if it.get("route") == "page":
            return 2
        return 3

    plan_items = [it for it in items if it.get("lookup") is not None]
    plan_items.sort(key=lambda it: part_order.get(item_part.get(str(it.get("id")), part_ids[0]), 99))
    script_items = sorted([it for it in items if it.get("lookup") is None], key=_group)
    ordered = plan_items + script_items
    entries, seen = [], set()
    for index, it in enumerate(ordered, 1):
        block = _reading_block(index, it)
        if block in seen:                      # an identical item prints once
            continue
        seen.add(block)
        entries.append({"it": it, "plan": it.get("lookup") is not None, "text": block})

    budget = max_chars - 400
    chosen, total, cut = [], len(prefix) + 2, []
    for entry in entries:
        if entry["plan"]:
            chosen.append(entry)
            total += len(entry["text"]) + 2
    for entry in entries:
        if entry["plan"]:
            continue
        typed = entry["it"].get("route") in _TYPED_ROUTES
        if typed or total + len(entry["text"]) + 2 <= budget:
            chosen.append(entry)
            total += len(entry["text"]) + 2
        else:
            cut.append({"id": str(entry["it"].get("id") or ""), "route": entry["it"].get("route"),
                        "doc_key": entry["it"].get("doc_key"), "page": entry["it"].get("page")})
    label = (f"ITEMS ({len(items)}: {sum(1 for e in chosen if e['plan'])} plan-lookup items, "
             f"{sum(1 for e in chosen if not e['plan'])} script items; whole items, no windows)")
    if cut:
        label += f"; {len(cut)} script page/rest items cut for the {max_chars}-char cap: " + ", ".join(
            f"{c['route']} {str(c['doc_key'] or '').rsplit('/', 1)[-1]} p{c['page']}" for c in cut[:8])
        if len(cut) > 8:
            label += f" (+{len(cut) - 8} more)"
    pack["reading_cut"] = cut
    pack["reading_cut_count"] = len(cut)
    pack["reading_plan_items"] = sum(1 for e in chosen if e["plan"])
    pack["reading_script_items"] = sum(1 for e in chosen if not e["plan"])
    pack["reading_over_cap"] = max(0, total - max_chars)
    out = prefix + "\n" + label + "\n"
    out += "\n".join(e["text"] for e in chosen)
    return out.strip() + "\n"

def write_reading(pack: dict, path, max_chars: int = 60000) -> int:
    """Write the reading copy beside the pack; returns its character count and records what the cap cut."""
    text = reading_text(pack, max_chars=max_chars)
    Path(path).write_text(text, encoding="utf-8")
    pack["reading_chars"] = len(text)
    return len(text)


# aliases for tests
def normalize_number(tok):
    try:
        from reality_engine.answer import pack_recall as _pr
        return _pr.normalize_number(tok)
    except Exception:
        t = (tok or "").strip().replace(",", "")
        if "." in t:
            t = t.rstrip("0").rstrip(".")
        return t

def normalize_numbers(text):
    return re.findall(r"\d[\d,]*\.?\d*", text or "")
