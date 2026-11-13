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

def _item(route, idx, doc_key="", doc_type="", page=None, known_at=None, text="", row=None):
    return {
        "id": f"{route}-{idx}",
        "route": route,
        "doc_key": doc_key or "",
        "doc_type": doc_type or "",
        "page": page,
        "known_at": known_at,
        "text": _truncate_to_cap(text, route),
        "row": row,
    }


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
    if isinstance(r, dict):
        for key in ("text", "snippet", "quote", "content", "row"):
            if r.get(key):
                return str(r.get(key))
        return json.dumps(r, ensure_ascii=False, default=str)
    return str(r)


def _doc_type_of(r):
    if isinstance(r, dict):
        return r.get("doc_type") or r.get("type") or ""
    return ""


def _reply_to_items(route, reply):
    items = []
    if isinstance(reply, dict) and "error" in reply:
        return items
    rows = _rows_of(reply)
    if rows:
        for r in rows:
            items.append(_item(route, len(items) + 1,
                               doc_key=str(_doc_key_of(r, reply) or ""),
                               doc_type=_doc_type_of(r),
                               page=_page_of(r),
                               known_at=_known_at_of(r),
                               text=_text_of(r),
                               row=r if isinstance(r, dict) else None))
    else:
        # single reply -> one item
        items.append(_item(route, 1,
                           doc_key=str(_doc_key_of(reply)) if isinstance(reply, dict) else "",
                           doc_type=_doc_type_of(reply) if isinstance(reply, dict) else "",
                           page=_page_of(reply) if isinstance(reply, dict) else None,
                           known_at=_known_at_of(reply) if isinstance(reply, dict) else None,
                           text=json.dumps(reply, ensure_ascii=False, default=str),
                           row=reply if isinstance(reply, dict) else None))
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


def gather(db, symbol, plan, as_of, max_chars: int = 120000, quota: dict = None):  # type: ignore[assignment]
    _setup(db)
    import lookups_pilot3 as p3
    import lookups_semantic
    import lookups_tech

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

    # run in thread pool
    route_replies = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        futmap = {ex.submit(fn): route for route, fn in tasks}
        for fut in concurrent.futures.as_completed(futmap):
            route = futmap[fut]
            try:
                rep = fut.result()
            except Exception as exc:
                rep = {"error": str(exc)}
            route_replies.setdefault(route, []).append(rep)

    # convert to items
    all_items = []
    route_stats = {}
    for route, replies in route_replies.items():
        ritems = []
        for rep in replies:
            if isinstance(rep, dict):
                if "error" in rep:
                    route_errors.append({"route": route, "error": rep.get("error")})
                    continue
                if rep.get("found") is False:
                    route_errors.append({"route": route, "found": False,
                                        "hint": rep.get("hint"),
                                        "available": (rep.get("available") or rep.get("metrics_matched"))})
                    continue
            ritems.extend(_reply_to_items(route, rep))
        # as_of drop
        ritems = [it for it in ritems if _asof_ok(it.get("known_at"), as_of)]
        # dedupe within route
        ritems = _dedupe(ritems)
        route_stats[route] = {"returned": len(ritems), "kept": 0, "cut": 0}
        all_items.extend((route, it) for it in ritems)

    # flatten
    flat_items = [it for (_, it) in all_items]

    # page reads for statement/list/guidance kinds
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

    # dedupe all
    flat_items = _dedupe(flat_items)

    # as_of drop
    flat_items = [it for it in flat_items if _asof_ok(it.get("known_at"), as_of)]

    # quota per route
    flat_items = _apply_quota(flat_items, quota)

    periods = set(plan.get("periods") or [])
    def _period_match(it):
        txt = (it.get("text") or "")
        for p in periods:
            if p and p.lower() in txt.lower():
                return 0
        return 1
    # round-robin across routes for diversity, each route sorted by period match then known_at desc
    by_route = {}
    for it in flat_items:
        by_route.setdefault(it["route"], []).append(it)
    for r in by_route:
        by_route[r].sort(key=lambda it: (_period_match(it),), )
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
    flat_items = merged

    # total cap: truncate page texts already per-item; drop lowest-ranked items
    # rank best first (reuse _period_match defined above)
    ranked_idx = sorted(range(len(flat_items)),
                        key=lambda i: (_period_match(flat_items[i]),))
    # stable by known_at desc within same period match
    ranked_idx.sort(key=lambda i: (flat_items[i].get("known_at") or ""), reverse=True)
    ranked_idx.sort(key=lambda i: (_period_match(flat_items[i]),))
    kept_idx = set()
    total = 0
    dropped = []
    for i in ranked_idx:
        tlen = len(flat_items[i].get("text") or "")
        sep = 2 if kept_idx else 0
        if total + sep + tlen <= max_chars:
            kept_idx.add(i)
            total += sep + tlen
        else:
            dropped.append(flat_items[i])
    kept = [flat_items[i] for i in range(len(flat_items)) if i in kept_idx]
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
    pack = {
        "symbol": symbol,
        "as_of": as_of,
        "plan": plan,
        "items": kept,
        "text": text,
        "chars": len(text),
        "pack_chars": len(text),
        "items_count": len(kept),
        "routes_nonempty": routes_nonempty,
        "route_stats": route_stats,
        "route_errors": route_errors,
        "cut_log": cut_log,
        "seconds": round(time.time() - t0, 3),
    }
    return pack


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
