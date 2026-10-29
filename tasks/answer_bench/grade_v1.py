"""Strict grader for the 150-case answer bench (query-layer v1 rules).

The bench's own grader (``run_bench.finish``) marks a case ANSWERED when every
hop it planned returned rows.  That over-reports: MB0885 answered the ranking
half and appended an unrelated deck row; MB0023 answered from 2021 decks while
the question named the Aug-2026 deck.  This grader applies the v1 contract:

1. ANSWERED only if **every sub-question** has evidence-backed content
   (``reality_engine.query.decompose`` is the same split the answerer ran).
2. An answer row for the wrong metric family or the wrong entity -> WRONG.
3. Evidence from a document other than the one the question named (date ±3d,
   doc type) when that document exists -> WRONG.
4. Stale data (older than the latest held as of the as_of) without a reason
   -> PARTIAL.
5. Unrelated rows in the answer reduce the grade.

It grades both result files, so the before/after is honest:

    python tasks/answer_bench/grade_v1.py

Reads RESULTS_v0.jsonl and RESULTS_v1.jsonl, writes RESULTS_v0_strict.jsonl,
RESULTS_v1_strict.jsonl and REPORT_v1.md.  Databases are read-only; if the
snapshot/doc stores are unavailable the freshness/existence checks degrade to
the row's own evidence text instead of failing.
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(REPO))

from reality_engine.query.answer import (  # noqa: E402
    METRIC_SYNONYMS, evidence_matches, metric_matches)
from reality_engine.query.decompose import decompose, sub_case  # noqa: E402
from reality_engine.query.gate import (  # noqa: E402
    asked_concepts, ask_coverage, gate_hop, gate_run, key_terms, unrelated_rows)
from reality_engine.query.router import named_document, period_bounds, route  # noqa: E402

WINDOW_DAYS = 3
BLOCKED = {"BLOCKED_SCHEMA", "BLOCKED_TOOL", "NOT_IN_DATA"}
DOC_TABLES = {
    "deck": ("deck_pages", "symbol", "known_at"),
    "ar": ("ar_docs", "symbol", "filed_at"),
    "transcript": ("cc_docs", "symbol", "known_at_utc"),
    "announcement": ("bse_ann", "symbol", "known_at_utc"),
}
STORE_DOC = {"deck_figures": "deck", "ar_facts": "ar", "concall_facts": "transcript",
             "bse_announcements": "announcement"}
CLAIM = re.compile(
    r"(?P<item>[^=|]+?)\s*=\s*(?P<value>-?[\d,.]+)\s*(?P<unit>[^;(]*?)\s*"
    r"\((?P<store>results_xbrl|ar_facts|deck_figures|concall_facts|computed|shp_index),"
    r"\s*known\s*(?P<day>\d{4}-\d{2}-\d{2})\)")
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
STOPWORDS = set("""the and for with that this from have has had was were are been its their
there about would could should what which when where how why did does all any show list
compute state note flag map classify measure identify compare mark per into over under
between within during also then than as at of on in to a an it stock stocks company
companies name names""" .split())


# --------------------------------------------------------------------------
# document index (read-only)
# --------------------------------------------------------------------------
class DocIndex:
    """Latest / exists lookups for the named document and staleness rules."""

    def __init__(self) -> None:
        self.ctx = None
        self.ok = False
        # 1,073 cases reduce to a few hundred distinct (symbol, doc type, date)
        # lookups; the snapshot scan behind each one is the whole run time.
        self._latest: dict[Any, str | None] = {}
        self._exists: dict[Any, bool] = {}
        try:
            from reality_engine.query.ctx import Ctx
            self.ctx = Ctx()
            self.ctx.duck()
            self.ok = True
        except Exception:
            self.ok = False

    def _rows(self, sql: str, params: list[Any]) -> list[dict[str, Any]]:
        if not self.ok or self.ctx is None:
            return []
        try:
            return self.ctx.duck_rows(sql, params)
        except Exception:
            return []

    def latest(self, symbol: str | None, doc_type: str | None, as_of: str) -> str | None:
        key = (symbol, doc_type, as_of)
        if key not in self._latest:
            self._latest[key] = self._latest_of(symbol, doc_type, as_of)
        return self._latest[key]

    def _latest_of(self, symbol: str | None, doc_type: str | None,
                   as_of: str) -> str | None:
        if not symbol or not doc_type or doc_type not in DOC_TABLES or not self.ok:
            return None
        table, key, day_col = DOC_TABLES[doc_type]
        rows = self._rows(
            f"SELECT max(substr({day_col},1,10)) AS day FROM {table} "
            f"WHERE upper({key}) = upper(?) AND substr({day_col},1,10) <= ?", [symbol, as_of])
        return str((rows[0] if rows else {}).get("day") or "")[:10] or None

    def exists(self, symbol: str | None, doc_type: str | None, day: str,
               tol: int = WINDOW_DAYS) -> bool:
        key = (symbol, doc_type, day, tol)
        if key not in self._exists:
            self._exists[key] = self._exists_at(symbol, doc_type, day, tol)
        return self._exists[key]

    def _exists_at(self, symbol: str | None, doc_type: str | None, day: str,
                   tol: int = WINDOW_DAYS) -> bool:
        if not symbol or not doc_type or doc_type not in DOC_TABLES or not self.ok:
            return False
        from datetime import date, timedelta
        anchor = date.fromisoformat(day[:10])
        lo = (anchor - timedelta(days=tol)).isoformat()
        hi = (anchor + timedelta(days=tol)).isoformat()
        table, key, day_col = DOC_TABLES[doc_type]
        rows = self._rows(
            f"SELECT count(*) AS n FROM {table} WHERE upper({key}) = upper(?) "
            f"AND substr({day_col},1,10) BETWEEN ? AND ?", [symbol, lo, hi])
        return bool((rows[0] if rows else {}).get("n"))


# --------------------------------------------------------------------------
# row facts
# --------------------------------------------------------------------------
def _text(row: dict[str, Any]) -> str:
    for key in ("v1", "v0"):
        blob = row.get(key) or {}
        if blob.get("answer"):
            return str(blob["answer"])
    return str(row.get("answer") or "")


def _evidence(row: dict[str, Any]) -> list[str]:
    return [str(item) for item in (row.get("evidence") or [])]


def _gate_of(case: dict, row: dict[str, Any]) -> tuple[list[str], int]:
    """Recompute the entity/ask/period gate from the returned rows.

    The stored ``gate`` block carries the rows the planner actually returned
    (capped at 8 per hop) and the slots the run was routed with.  The flags the
    planner wrote are *not* read: ``gate_hop``/``gate_run`` recompute them, and a
    disagreement is counted so the report can show the planner is not trusted.
    """
    runs = row.get("gate") or []
    if not runs:
        return [], 0
    reasons: list[str] = []
    mismatches = 0
    for run in runs:
        slots = dict(run.get("slots") or {})
        slots.setdefault("question", case.get("question"))
        text = str(run.get("text") or "")
        sub = {"text": text, "period": case.get("period"),
               "named_document": named_document({"question": text})}
        concepts = asked_concepts(f"{text} {slots.get('question') or ''}")
        terms = [] if concepts else key_terms(text)
        hops = []
        for hop in run.get("hops") or []:
            stored = {key: hop.get(key) for key in
                      ("entity_match", "ask_match", "period_match")}
            recomputed = (gate_hop(hop, slots, concepts, terms, sub["named_document"])
                          if hop.get("ok") and not hop.get("na") else dict(hop))
            if any(recomputed.get(key) != stored.get(key) for key in stored):
                mismatches += 1
            hops.append(recomputed)
        reason = gate_run(hops, sub, concepts, terms)
        if reason:
            reasons.append(reason)
        if (run.get("gate") or None) != reason:
            mismatches += 1
    return reasons, mismatches


def _claims(row: dict[str, Any]) -> list[dict[str, Any]]:
    """Numeric answer rows: item / value / unit / store / day.

    An item can itself contain a semicolon ("State-of-the-art facilities ...
    strategi cally ..."), so chunks without a claim are merged into the next
    one before parsing.
    """
    out: list[dict[str, Any]] = []
    merged: list[str] = []
    buffer = ""
    for chunk in re.split(r";\s*", _text(row)):
        buffer = f"{buffer}; {chunk}" if buffer else chunk
        if CLAIM.search(buffer):
            merged.append(buffer)
            buffer = ""
    if buffer:
        merged.append(buffer)
    for chunk in merged:
        match = CLAIM.search(chunk)
        if not match:
            continue
        out.append({"item": match.group("item").strip(), "value": match.group("value"),
                    "unit": match.group("unit").strip(), "store": match.group("store"),
                    "day": match.group("day")})
    for run in row.get("subs") or []:
        for hop in run.get("hops") or []:
            if hop.get("hop") != "FACTS":
                continue
            for fact in hop.get("rows") or []:
                if fact.get("value") is None:
                    continue
                out.append({"item": str(fact.get("item") or ""), "value": fact.get("value"),
                            "unit": str(fact.get("unit") or ""), "store": str(fact.get("store")),
                            "day": str(fact.get("known_at") or "")[:10]})
    for run in row.get("gate") or []:
        for hop in run.get("hops") or []:
            if hop.get("hop") != "FACTS":
                continue
            for fact in hop.get("rows") or []:
                if fact.get("value") is None:
                    continue
                out.append({"item": str(fact.get("item") or ""), "value": fact.get("value"),
                            "unit": str(fact.get("unit") or ""),
                            "store": str(fact.get("store") or ""),
                            "day": str(fact.get("known_at") or "")[:10]})
    seen = set()
    unique = []
    for claim in out:
        key = (claim["item"], str(claim["value"]), claim["store"], claim["day"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(claim)
    return unique


def _day(value: Any) -> str | None:
    match = DATE.search(str(value or ""))
    return match.group(0) if match else None


def _window(day: str, tol: int = WINDOW_DAYS) -> tuple[str, str]:
    from datetime import date, timedelta
    anchor = date.fromisoformat(day)
    return ((anchor - timedelta(days=tol)).isoformat(),
            (anchor + timedelta(days=tol)).isoformat())


def _in_window(day: str | None, anchor: str | None, tol: int = WINDOW_DAYS) -> bool:
    if not day or not anchor:
        return False
    try:
        a, b = _window(anchor, tol)
    except ValueError:
        return False
    return a <= day <= b


def _anchor_words(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9][a-z0-9\-/]{3,}", text.lower())
            if w not in STOPWORDS]


def _sub_chain(case: dict, sub: dict[str, Any]) -> list[str]:
    variant = sub_case(case, sub)
    try:
        return [hop for hop in route(variant)["chain"] if hop != "resolve"]
    except Exception:  # noqa: BLE001 - routing a synthetic sub-case must never crash grading
        return []


def _pick_from_answer(text: str) -> str | None:
    """The ranking winner the answer itself named (v0 row without sub structure)."""
    match = re.search(
        r"(?:holding change \(pp\)|window return %|delivery % change|return %|ranked|ranking)"
        r"[^;|]*?,\s*([A-Z][A-Z0-9&\-]{2,15})\s", text or "")
    return match.group(1) if match else None


def _return_entities(text: str) -> list[str]:
    return [m.group(1) for m in re.finditer(
        r"\b([A-Z][A-Z0-9&\-]{2,15}):\s*\d{4}-\d{2}-\d{2}\s+close", text or "")]


# --------------------------------------------------------------------------
# rules
# --------------------------------------------------------------------------
def _runs_of(row: dict[str, Any]) -> list[dict[str, Any]]:
    """The per-sub runs of a result row (old ``subs`` or the gate record)."""
    runs = row.get("subs") or []
    if runs:
        return runs
    out = []
    for run in row.get("gate") or []:
        text = str(run.get("text") or "")
        out.append({"index": run.get("index"), "text": text,
                    "answered": not run.get("gate"), "hops": run.get("hops") or [],
                    "slots": run.get("slots") or {},
                    "concepts": asked_concepts(text),
                    "metric": None, "entities": []})
    return out


def _subs_for(case: dict, row: dict[str, Any]) -> list[dict[str, Any]]:
    """The decomposition the row was produced with (v1 runs), else recompute."""
    runs = _runs_of(row)
    if runs:
        return [{"index": run["index"], "text": run.get("text") or "",
                 "metric": run.get("metric"),
                 "concepts": run.get("concepts") or asked_concepts(run.get("text") or ""),
                 "slots": run.get("slots") or {},
                 "named_document": named_document({"question": run.get("text") or ""}),
                 "entity_from": None, "universe": False, "routing_text": run.get("text") or "",
                 "steps": []} for run in runs]
    return [dict(sub, concepts=asked_concepts(sub["text"]), slots={})
            for sub in decompose(case)]


def _coverage(case: dict, row: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    """Per sub-question: covered? evidence-backed?  Returns (subs, reasons)."""
    subs = _subs_for(case, row)
    text = _text(row)
    low = text.lower()
    runs = _runs_of(row)
    hops_ok = set(row.get("hops_ok") or [])
    reasons: list[str] = []
    covered: list[dict[str, Any]] = []
    for sub in subs:
        chain = _sub_chain(case, sub) if not runs else []
        chain_hit = bool(set(chain) & hops_ok) if hops_ok and chain else False
        missing_parts: list[str] = []
        if runs and sub["index"] < len(runs):
            run = runs[sub["index"]]
            evidence = any(hop.get("ok") and not hop.get("na") and
                           (hop.get("evidence") or hop.get("rows"))
                           for hop in run.get("hops") or []
                           if hop.get("hop") != "resolve")
            ok = bool(run.get("answered")) and evidence
            how = "sub-hop"
            # Every part of a multi-part ask must be carried by the run's rows:
            # "share count AND promoter holding", "promoter AND public", "raw AND
            # adjusted", "business AND segments".  One part is PARTIAL.
            if ok:
                checked = [hop for hop in run.get("hops") or []
                           if hop.get("hop") != "resolve" and not hop.get("na")]
                parts_ok, why = ask_coverage(checked, sub.get("concepts") or [], [])
                if parts_ok is False:
                    ok = False
                    missing_parts = why
        else:
            anchors = _anchor_words(sub["text"])
            hits = sum(1 for word in anchors if word in low)
            metric = sub.get("metric")
            metric_hit = bool(metric and metric in METRIC_SYNONYMS and any(
                word in low for word in METRIC_SYNONYMS[metric][0]))
            ok = bool(chain_hit and (hits >= max(1, len(anchors) // 2) or metric_hit))
            how = "answer-text"
        if not ok:
            reasons.append(f"sub-question {sub['index'] + 1} not addressed: "
                           f"'{sub['text'][:90]}'")
            reasons.extend(missing_parts)
        covered.append({"index": sub["index"], "text": sub["text"], "covered": ok,
                        "chain": chain, "how": how, "metric": sub.get("metric")})
    return covered, reasons


def _wrong_metric(subs: list[dict[str, Any]], claims: list[dict[str, Any]]) -> str | None:
    wanted = [sub["metric"] for sub in subs if sub.get("metric")]
    if not wanted or not claims:
        return None
    related = [claim for claim in claims
               if any(metric_matches(metric, claim["item"]) for metric in wanted)]
    if related:
        return None
    sample = "; ".join(claim["item"][:60] for claim in claims[:2])
    return (f"the numeric answer rows are for a different metric ({sample}) than the "
            f"asked {', '.join(sorted(set(wanted)))}")


def _wrong_entity(case: dict, subs: list[dict[str, Any]], row: dict[str, Any]) -> str | None:
    runs = row.get("subs") or []
    if runs:
        for i in range(1, len(runs)):
            run, previous = runs[i], runs[i - 1]
            if not re.search(r"\b(the stocks?|the shares?|the counter)\b",
                             run.get("text") or "", re.I):
                continue
            pick = next((hop["rows"][0].get("symbol") for hop in previous.get("hops") or []
                         if hop.get("hop") in ("SCREEN", "COMPARE") and hop.get("ok")
                         and hop.get("rows")), None)
            entities = [str(e.get("symbol")) for e in run.get("entities") or []
                        if isinstance(e, dict) and e.get("symbol")]
            if pick and entities and pick not in entities:
                return (f"the follow-up was answered for {entities[0]} but the ranking "
                        f"picked {pick}")
        return None
    text = _text(row)
    dependent = [sub for sub in subs if sub.get("entity_from") is not None]
    if not dependent:
        return None
    pick = _pick_from_answer(text)
    if not pick:
        return None
    priced = _return_entities(text)
    if priced and pick not in priced and any(entity != pick for entity in priced):
        return f"the follow-up was priced on {', '.join(priced[:2])} but the ranking picked {pick}"
    return None


def _named_document_rule(case: dict, row: dict[str, Any], index: DocIndex,
                         claims: list[dict[str, Any]]) -> tuple[str | None, str | None]:
    """(WRONG reason, PARTIAL reason) for the named-document preference.

    Only the sub-question that names the document is judged on it: rows that
    answer another sub-question are not "evidence for the named document".
    """
    subs = _subs_for(case, row)
    named_subs = [sub for sub in subs if sub.get("named_document")]
    if not named_subs:
        return None, None
    named = named_subs[0]["named_document"]
    symbol = next((str(e.get("symbol")) for e in case.get("entities") or []
                   if isinstance(e, dict) and e.get("symbol")), None)
    exists = index.exists(symbol, named["doc_type"], named["date"])
    runs = row.get("subs") or []
    used: list[str] = []
    if runs:
        for run in runs:
            if run.get("index") != named_subs[0]["index"]:
                continue
            for hop in run.get("hops") or []:
                if hop.get("hop") == "resolve":
                    continue  # identity is known at as_of, not the named document
                for fact in hop.get("rows") or []:
                    day = _day(fact.get("known_at") or fact.get("date"))
                    if day:
                        used.append(day)
                used += [day for item in hop.get("evidence") or [] for day in DATE.findall(item)]
    else:
        used = [claim["day"] for claim in claims if claim.get("day")]
        used += [day for item in _evidence(row) for day in DATE.findall(item)]
    if not exists:
        # Fall back to the row's own evidence: the named document's date in the
        # evidence text is proof it was found.
        blob = " ".join(_evidence(row)) + " " + _text(row)
        exists = any(_in_window(day, named["date"]) for day in DATE.findall(blob))
    if not exists or not used:
        return None, None
    inside = [day for day in used if _in_window(day, named["date"])]
    outside = [day for day in used if not _in_window(day, named["date"])]
    if inside and not outside:
        return None, None
    if outside and not inside:
        return (f"the {named['doc_type']} of {named['date']} exists, but the answer rows "
                f"come from {', '.join(sorted(set(outside))[:3])}"), None
    return None, (f"{len(outside)} row(s) come from outside the named {named['doc_type']} of "
                  f"{named['date']}: {', '.join(sorted(set(outside))[:3])}")


def _stale(case: dict, row: dict[str, Any], index: DocIndex,
           claims: list[dict[str, Any]], subs: list[dict[str, Any]]) -> str | None:
    if named_document(case):
        return None
    symbol = next((str(e.get("symbol")) for e in case.get("entities") or []
                   if isinstance(e, dict) and e.get("symbol")), None)
    as_of = str(case.get("as_of") or "")[:10]
    if not symbol or not as_of:
        return None
    stores = {claim["store"] for claim in claims if claim.get("store")}
    doc_types = [STORE_DOC[store] for store in stores if store in STORE_DOC]
    doc_types += [sub["named_document"]["doc_type"] for sub in subs
                  if sub.get("named_document")]
    if not doc_types:
        return None
    used = [claim["day"] for claim in claims if claim.get("day")]
    used += [day for item in _evidence(row) for day in DATE.findall(item)]
    used = [day for day in used if day]
    if not used:
        return None
    newest = max(used)
    latest = max((index.latest(symbol, doc_type, as_of) or "") for doc_type in set(doc_types))
    if len(latest) != 10 or newest >= latest:
        return None
    try:
        from datetime import date
        lag = (date.fromisoformat(latest) - date.fromisoformat(newest)).days
    except ValueError:
        return None
    if lag <= WINDOW_DAYS:
        return None
    # A reason: the answer says it is answering a named period and the data is
    # inside that period.
    text = _text(row).lower()
    period = str(case.get("period") or "")
    low_from, low_to, basis = period_bounds(case)
    if basis in ("quarter end", "fiscal year end", "month", "named date", "named dates",
                 "month span") and low_from and low_to and low_from <= newest <= low_to:
        return None
    if period and period.lower() in text and _day(newest):
        return None
    return (f"stale: newest row is {newest} but {latest} is held as of {as_of} "
            f"({lag} days older) with no stated reason")


def _unrelated(claims: list[dict[str, Any]], subs: list[dict[str, Any]]) -> list[str]:
    wanted = [sub["metric"] for sub in subs if sub.get("metric")]
    if not wanted:
        return []
    keep = []
    for claim in claims:
        text = f"{claim['item']} {claim['unit']}"
        if any(metric_matches(metric, text) or evidence_matches(metric, text)
               for metric in wanted):
            continue
        keep.append(f"{claim['item'][:60]} = {claim['value']} {claim['unit']} "
                    f"({claim['store']}, {claim['day']})")
    return keep


def _page_gap(subs: list[dict[str, Any]], row: dict[str, Any]) -> str | None:
    """A page ask answered with the page's title alone is not what the page says."""
    if not any(re.search(r"\bpage\s+\d+", str(sub.get("text") or ""), re.I)
               for sub in subs):
        return None
    quotes = [str(item.get("quote") or item.get("text") or "")
              for run in _runs_of(row) for hop in run.get("hops") or []
              for item in hop.get("rows") or []]
    content = " ".join(quote for quote in quotes if quote).strip()
    if not content or not content.lstrip().upper().startswith("TITLE |"):
        return None
    body = re.sub(r"(?i)^\s*TITLE\s*\|", "", content).strip()
    if len(body) < 60:
        return (f"the page is answered with its title only ('{body[:50]}'), not with "
                f"what the page says")
    return None


def _unrelated(case: dict, row: dict[str, Any],
               subs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rows whose entity or concept matches no part of the ask.

    Two sources, both of which must be clean:
    * the hops of each sub-run, judged against that sub-question's own ask (a price
      row is not "unrelated" to the half that asked for the price);
    * the numeric rows the answer prints (``item = value (store, known day)``), which
      are what a reader sees -- the Novelis EBITDA bridge is appended text, the
      revenue row is an appended row.

    A hop's rendered ``detail`` is the hop's own arithmetic, so a computed "5 daily
    closes within 1% of an edge" is the high it reports.
    """
    runs = _runs_of(row)
    out: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(items: list[dict[str, Any]], hop: str) -> None:
        for item in items:
            key = str(item.get("text") or "")[:60]
            if key in seen:
                continue
            seen.add(key)
            out.append(dict(item, hop=hop))

    for index, run in enumerate(runs):
        sub = subs[index] if index < len(subs) else {}
        concepts = sub.get("concepts") or []
        terms = [] if concepts else key_terms(str(run.get("text") or ""))
        for hop in run.get("hops") or []:
            if hop.get("hop") == "resolve" or hop.get("na") or not hop.get("ok"):
                continue
            add(unrelated_rows(hop.get("rows") or [], concepts, terms, hop.get("detail")),
                str(hop.get("hop")))
    concepts: list[str] = []
    for sub in subs:
        for concept in sub.get("concepts") or []:
            if concept not in concepts:
                concepts.append(concept)
    terms = [] if concepts else key_terms(str(case.get("question") or ""))
    for claim in _claims(row):
        text = f"{claim.get('item') or ''} {claim.get('unit') or ''}".strip()
        add(unrelated_rows([text], concepts, terms), "claim")
    return out


def grade_row(case: dict, row: dict[str, Any], index: DocIndex | None = None,
              source: str = "v1") -> dict[str, Any]:
    """Apply the strict rules to one bench row (never upgrades a bench grade)."""
    graded = dict(row)
    index = index or DocIndex()
    bench = str(row.get("grade") or "PARTIAL")
    graded["bench_grade"] = bench
    graded["unrelated_rows"] = 0
    subs = _subs_for(case, row)
    graded["strict_subs"] = [{"index": sub["index"], "text": sub["text"],
                              "metric": sub.get("metric"),
                              "concepts": sub.get("concepts")} for sub in subs]
    reasons: list[str] = []
    if bench in BLOCKED:
        graded["strict_grade"] = bench
        graded["strict_reasons"] = ["blocked: the declared fix is a new table/fetch"]
        return graded
    claims = _claims(row)
    covered, coverage_reasons = _coverage(case, row)
    graded["strict_coverage"] = covered
    wrong = _wrong_metric(subs, claims)
    if wrong:
        reasons.append(wrong)
        graded["strict_grade"] = "WRONG"
        graded["strict_reasons"] = reasons
        return graded
    entity = _wrong_entity(case, subs, row)
    if entity:
        reasons.append(entity)
        graded["strict_grade"] = "WRONG"
        graded["strict_reasons"] = reasons
        return graded
    named_wrong, named_partial = _named_document_rule(case, row, index, claims)
    if named_wrong:
        reasons.append(named_wrong)
        graded["strict_grade"] = "WRONG"
        graded["strict_reasons"] = reasons
        return graded
    gate_reasons, gate_mismatch = _gate_of(case, row)
    graded["gate_recomputed"] = gate_reasons
    graded["gate_flag_mismatches"] = gate_mismatch
    if gate_reasons:
        reasons.extend(gate_reasons)
    grade = "ANSWERED" if bench == "ANSWERED" else "PARTIAL"
    if named_partial:
        reasons.append(named_partial)
    if coverage_reasons:
        reasons.extend(coverage_reasons)
    stale = _stale(case, row, index, claims, subs)
    if stale:
        reasons.append(stale)
    page = _page_gap(subs, row)
    if page:
        reasons.append(page)
    unrelated = _unrelated(case, row, subs)
    graded["unrelated_rows"] = len(unrelated)
    # Two unrelated rows, or one that carries a number, is not an answer with
    # decoration: it is an answer that appended something the ask never wanted.
    if len(unrelated) > 1 or any(item.get("numeric") for item in unrelated):
        reasons.append(f"{len(unrelated)} unrelated row(s): " +
                       "; ".join(str(item.get("text"))[:60] for item in unrelated[:2]))
    if grade == "ANSWERED" and reasons:
        grade = "PARTIAL"
    graded["strict_grade"] = grade
    graded["strict_reasons"] = reasons
    return graded


# --------------------------------------------------------------------------
# report
# --------------------------------------------------------------------------
def _table(header: list[str], body: list[list[Any]]) -> str:
    out = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    out += ["| " + " | ".join(str(cell) for cell in line) + " |" for line in body]
    return "\n".join(out)


def _counts(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    return dict(Counter(str(row.get(key)) for row in rows))


def _by(rows: list[dict[str, Any]], value_of) -> dict[Any, list[dict[str, Any]]]:
    out: dict[Any, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        out[value_of(row)].append(row)
    return out


def build_report(v0: list[dict[str, Any]], v1: list[dict[str, Any]],
                 cases: dict[str, dict]) -> str:
    grades = ["ANSWERED", "PARTIAL", "WRONG", "BLOCKED_SCHEMA", "BLOCKED_TOOL", "NOT_IN_DATA"]
    lines = [
        "# Query layer v1 — strict bench report",
        "",
        "Same 150-case sample (`SAMPLE.jsonl`, 30 regressions) and the same held "
        "databases, read-only. `RESULTS_v0.jsonl` is the merged v0 run; "
        "`RESULTS_v1.jsonl` is v1 (sub-question decomposition + named-document "
        "preference + relevance filter + EVIDENCE rerank). Both are re-graded "
        "here by `grade_v1.py`, which is stricter than `run_bench.finish`.",
        "",
        "Strict rules: every sub-question must be evidence-backed; wrong metric "
        "family or wrong entity -> WRONG; evidence from a document other than "
        "the one named (when it exists) -> WRONG; stale evidence without a "
        "reason -> PARTIAL; unrelated rows reduce the grade.",
        "",
        "## 1. Grade, strict",
        "",
    ]
    body = []
    for grade in grades:
        b = sum(1 for row in v0 if row["strict_grade"] == grade)
        a = sum(1 for row in v1 if row["strict_grade"] == grade)
        bb = sum(1 for row in v0 if row.get("bench_grade") == grade)
        ab = sum(1 for row in v1 if row.get("bench_grade") == grade)
        if b or a or bb or ab:
            body.append([grade, b, a, a - b, bb, ab])
    lines.append(_table(["grade", "v0 strict", "v1 strict", "delta", "v0 bench", "v1 bench"],
                        body))
    lines.append("")
    reg0 = [row for row in v0 if row.get("regression")]
    reg1 = [row for row in v1 if row.get("regression")]
    lines.append(
        f"**Regressions (30):** strict ANSWERED "
        f"{sum(1 for r in reg0 if r['strict_grade'] == 'ANSWERED')} -> "
        f"{sum(1 for r in reg1 if r['strict_grade'] == 'ANSWERED')}; PARTIAL "
        f"{sum(1 for r in reg0 if r['strict_grade'] == 'PARTIAL')} -> "
        f"{sum(1 for r in reg1 if r['strict_grade'] == 'PARTIAL')}; WRONG "
        f"{sum(1 for r in reg0 if r['strict_grade'] == 'WRONG')} -> "
        f"{sum(1 for r in reg1 if r['strict_grade'] == 'WRONG')}; BLOCKED "
        f"{sum(1 for r in reg0 if r['strict_grade'].startswith('BLOCKED'))} -> "
        f"{sum(1 for r in reg1 if r['strict_grade'].startswith('BLOCKED'))}.")
    lines += ["", "### By family (first family in the case)", ""]
    body = []
    families = sorted({_family(row) for row in v0 + v1}, key=lambda value: str(value))
    for family in families:
        b = [row for row in v0 if _family(row) == family]
        a = [row for row in v1 if _family(row) == family]
        body.append([family, len(b),
                     sum(1 for r in b if r["strict_grade"] == "ANSWERED"),
                     sum(1 for r in a if r["strict_grade"] == "ANSWERED"),
                     sum(1 for r in b if r["strict_grade"] == "PARTIAL"),
                     sum(1 for r in a if r["strict_grade"] == "PARTIAL"),
                     sum(1 for r in b if r["strict_grade"] == "WRONG"),
                     sum(1 for r in a if r["strict_grade"] == "WRONG")])
    lines.append(_table(["family", "cases", "v0 ANSWERED", "v1 ANSWERED", "v0 PARTIAL",
                         "v1 PARTIAL", "v0 WRONG", "v1 WRONG"], body))
    lines += ["", "### By source bank", ""]
    body = []
    banks = sorted({str(row.get("source_bank")) for row in v0 + v1})
    for bank in banks:
        b = [row for row in v0 if str(row.get("source_bank")) == bank]
        a = [row for row in v1 if str(row.get("source_bank")) == bank]
        body.append([bank, len(b),
                     sum(1 for r in b if r["strict_grade"] == "ANSWERED"),
                     sum(1 for r in a if r["strict_grade"] == "ANSWERED"),
                     sum(1 for r in b if r["strict_grade"] == "PARTIAL"),
                     sum(1 for r in a if r["strict_grade"] == "PARTIAL"),
                     sum(1 for r in b if r["strict_grade"] == "WRONG"),
                     sum(1 for r in a if r["strict_grade"] == "WRONG")])
    lines.append(_table(["bank", "cases", "v0 ANSWERED", "v1 ANSWERED", "v0 PARTIAL",
                         "v1 PARTIAL", "v0 WRONG", "v1 WRONG"], body))
    lines += ["", "## 2. The 30 regressions", ""]
    v0_by = {row["mid"]: row for row in v0}
    v1_by = {row["mid"]: row for row in v1}
    body = []
    for mid, row in sorted(v1_by.items()):
        if not row.get("regression"):
            continue
        old = v0_by.get(mid, {})
        body.append([mid, old.get("strict_grade", ""), row.get("strict_grade", ""),
                     (row.get("question") or "")[:60],
                     (row.get("strict_reasons") or [""])[0][:80]])
    lines.append(_table(["mid", "v0 strict", "v1 strict", "question", "first strict reason"],
                        body))
    lines += ["", "## 3. Fixed cases (strict v0 not ANSWERED -> strict v1 ANSWERED)", ""]
    fixed = [mid for mid in sorted(v1_by)
             if v1_by[mid]["strict_grade"] == "ANSWERED"
             and v0_by.get(mid, {}).get("strict_grade") != "ANSWERED"]
    body = []
    for mid in fixed[:10]:
        row = v1_by[mid]
        body.append([mid, v0_by.get(mid, {}).get("strict_grade", ""),
                     (row.get("question") or "")[:80],
                     " | ".join(row.get("strict_reasons") or []) or "clean under the strict rules",
                     (row.get("answer") or "")[:120].replace("\n", " ")])
    if body:
        lines.append(_table(["mid", "v0 strict", "question", "why v1 is clean", "answer lead"],
                            body))
    else:
        lines.append("None.")
    lines += ["", f"All fixed cases ({len(fixed)}): {', '.join(fixed) or 'none'}", ""]
    regressed = [mid for mid in sorted(v1_by)
                 if v1_by[mid]["strict_grade"] not in ("ANSWERED", "PARTIAL")
                 and v0_by.get(mid, {}).get("strict_grade") in ("ANSWERED", "PARTIAL")]
    lines.append(f"Cases that got a worse strict grade under v1 ({len(regressed)}): "
                 f"{', '.join(regressed) or 'none'}")
    lines += ["", "## 4. Remaining top blockers", ""]
    groups: dict[str, list[str]] = defaultdict(list)
    for mid, row in v1_by.items():
        if row["strict_grade"] == "ANSWERED":
            continue
        if row["strict_reasons"]:
            reason = row["strict_reasons"][0]
        else:
            # No strict violation: the bench hop/plan itself failed.
            failed = "+".join(row.get("hops_failed") or []) or "no hop"
            reason = f"hop did not answer: {failed}: {(row.get('blocker') or '')[:70]}"
        reason = re.sub(r"\(.*\)", "", reason)[:90]
        groups[reason].append(mid)
    body = [[reason, len(mids), ", ".join(mids[:5])]
            for reason, mids in sorted(groups.items(), key=lambda item: -len(item[1]))[:12]]
    lines.append(_table(["blocker", "cases", "examples"], body))
    lines += ["", "## 5. Rule audit (strict rows touched)", ""]
    counts = Counter()
    for row in v0 + v1:
        for reason in row.get("strict_reasons") or []:
            for key in ("sub-question", "different metric", "follow-up was",
                        "exists, but", "stale:", "unrelated row", "GATE"):
                if key in reason:
                    counts[key] += 1
                    break
        row["gate_flag_mismatches"] = row.get("gate_flag_mismatches") or 0
    body = [[key, value] for key, value in counts.most_common()]
    lines.append(_table(["rule", "rows"], body or [["none", 0]]))
    mismatched = sum(1 for row in v1 if row.get("gate_flag_mismatches"))
    lines.append(f"\nGate rows recomputed by this grader: {len(v1)}; rows where the "
                 f"planner's own flag disagreed with the recomputation: {mismatched}.")
    lines.append("\nA row with no strict reason but a PARTIAL grade is the bench's own hop "
                 "failure (the strict rules added nothing); the blocker column names it.")
    return "\n".join(lines) + "\n"


def _family(row: dict[str, Any]) -> Any:
    family = row.get("family") or []
    return family[0] if isinstance(family, list) and family else None


def _load(name: str) -> list[dict[str, Any]]:
    path = HERE / name
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def main(argv: list[str]) -> int:
    v0 = _load("RESULTS_v0.jsonl")
    v1 = _load("RESULTS_v1.jsonl")
    cases = {row["mid"]: row for row in _load("SAMPLE.jsonl")}
    index = DocIndex()
    print(f"doc index: {'snapshot' if index.ok else 'row-text fallback'}")
    for name, rows, source in (("RESULTS_v0_strict.jsonl", v0, "v0"),
                               ("RESULTS_v1_strict.jsonl", v1, "v1")):
        graded = []
        for row in rows:
            case = cases.get(row["mid"], {})
            graded.append(grade_row(case, row, index, source))
        (HERE / name).write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in graded),
            encoding="utf-8")
        counts = Counter(row["strict_grade"] for row in graded)
        print(f"{name}: {len(graded)} rows, {dict(counts)}")
    report = build_report(_load("RESULTS_v0_strict.jsonl"), _load("RESULTS_v1_strict.jsonl"),
                          cases)
    (HERE / "REPORT_v1.md").write_text(report, encoding="utf-8")
    print("wrote RESULTS_v0_strict.jsonl, RESULTS_v1_strict.jsonl, REPORT_v1.md")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
