"""Deterministic router: a master-bank case -> planner chain + slots.

Routing key order is fixed by ``tasks/arch_v3/QUERY_LAYER.md`` §2:
``(source_bank, archetype/template, family set, entity_level, answer_kind)`` —
``answer_kind`` is a tiebreaker, never the key.  No model, no question-text
routing: the question only fills slots (dates, periods, entity hints, page).
"""
from __future__ import annotations

import re
from typing import Any

CANONICAL_ORDER = ["resolve", "EXPECTATIONS", "SCREEN", "EVENT", "RIPPLE", "COMPARE",
                   "FACTS", "SERIES", "EVIDENCE"]

OPINION_TEMPLATES = {"entry_timing", "hold_sell", "group_basket", "thesis_break",
                     "valuation", "unit_economics", "ta_relative_strength",
                     "ta_support_resistance", "ta_gap", "ta_breakout_volume",
                     "ipo_grey_listing"}
OPINION_ASK = re.compile(
    r"\b(should i|good level|worth buying|worth the wait|enter now|wait for a retest|"
    r"buy or sell|hold or sell|what would (?:prove|break)|would break|"
    r"how would .{0,60}(?:behave|fare|react|respond|move|change|spread)|"
    r"what does .{0,40}(?:disclosure|multiple) (?:show|imply)|"
    r"is it starting to turn|is the .{0,20} starting to turn)\b", re.I)

MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
_MONTH_RE = (r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)")

# required_evidence ref -> planner (first match wins; ordered by specificity)
REF_RULES: list[tuple[tuple[str, ...], str]] = [
    (("segment", "cost_structure", "margin_mix"), "FACTS"),
    (("commodity", "usdinr", "copper", "crude", "brent", "steel_hrc", "gold_price"), "SERIES"),
    (("index_daily", "index_", "nifty", "index_membership", "index_tri"), "SCREEN"),
    (("flow", "fii", "dii", "fpi"), "SCREEN"),
    (("corp_action", "corporate_action", "demerger", "split", "bonus"), "EVENT"),
    (("price_band", "band"), "EVENT"),
    (("bulk_block", "deal", "block"), "EVENT"),
    (("insider", "sast", "pledge"), "EVENT"),
    (("shareholding", "shp", "holder"), "FACTS"),
    (("etf", "nav", "inav"), "SERIES"),
    (("xbrl", "results_xbrl", "quarterly_financials", "annual_financials",
      "financial_metrics", "ar_facts", "ar_docs", "deck_facts", "cc_items",
      "concall", "guidance", "revenue", "margin"), "FACTS"),
    (("policy_events", "pib", "budget", "rbi", "tariff", "pli", "macro_claim"), "RIPPLE"),
    (("universe", "theme", "membership", "peer", "sector_map"), "COMPARE"),
    (("event_day0", "leakage", "day0", "events."), "EVENT"),
    (("document_chunks", "raw_documents", "announcement", "search", "fts",
      "chunks_v3", "bse_ann"), "EVIDENCE"),
    (("px_", "price", "delivery", "ohlcv", "turnover", "close", "mkt_"), "SERIES"),
]

FAMILY_PLANNERS = {
    1: ["FACTS", "EVIDENCE"], 2: ["FACTS", "SERIES"], 3: ["FACTS", "EVIDENCE"],
    4: ["FACTS", "COMPARE"], 5: ["EVIDENCE"], 6: ["RIPPLE"], 7: ["RIPPLE"],
    8: ["COMPARE"], 9: ["EVENT"], 10: ["EVIDENCE"], 11: ["SERIES", "FACTS"],
    12: ["SERIES"], 13: ["COMPARE", "EVIDENCE"], 14: ["FACTS"], 15: ["SERIES", "EVENT"],
    16: ["SERIES", "FACTS"], 17: ["FACTS"], 18: ["RIPPLE"], 19: ["RIPPLE", "EVIDENCE"],
    20: ["SERIES"],
}

METRICS: list[tuple[str, tuple[str, ...]]] = [
    ("segment", ("segment", "segments", "business mix", "vertical")),
    ("net_npa", ("net npa", "gross npa", "npa")),
    ("order_book", ("order book", "orderbook", "order intake", "orders")),
    ("eps", ("eps", "earnings per share")),
    ("ebitda", ("ebitda", "operating profit")),
    ("margin", ("margin", "opm", "ebitda margin", "pat margin")),
    ("pat", ("pat", "profit after tax", "net profit", "net income", "profit")),
    ("revenue", ("revenue", "turnover", "sales", "income from operations", "topline")),
    ("capacity", ("capacity", "utilisation", "utilization")),
    # Capex is held in the fact stores but had no metric key, so a capex ask never
    # reached FACTS and no row could carry the concept.
    ("capex", ("capex", "capital expenditure", "capital spending")),
    ("facilities", ("facilities", "plants", "manufacturing units", "factory", "factories")),
    ("dso", ("dso", "receivable", "debtor", "collection days")),
    ("cfo", ("cfo", "cash flow from operations", "operating cash flow")),
    ("cagr", ("cagr", "annualised", "annualized", "3-year", "three-year", "five-year")),
    ("valuation", ("pe", "p/e", "ev/ebitda", "ev/sales", "valuation", "multiple",
                   "premium", "discount")),
    ("promoter", ("promoter", "stake", "shareholding", "holding")),
    ("return", ("return", "rose", "fell", "gained", "dropped", "move", "moved",
                "performance", "outperform", "underperform")),
    ("range", ("range", "support", "resistance", "high", "low", "breakout", "breakdown")),
    ("gap", ("gap", "gapped")),
    ("rsi", ("rsi", "oversold", "overbought")),
    ("delivery", ("delivery", "delivered", "short covering", "accumulation")),
    ("guidance", ("guidance", "guided", "outlook", "expects", "target")),
    ("audit", ("audit", "auditor", "opinion", "qualified", "qualification")),
]

STOP = set("""what which does from with that have this they there their about would could should
been were when where than then also into over after before still actually give name compare build
show much many same kind share says said the and for its was are has had how why per any all now
use get got put see saw make take keep kept here tell told ask asked look looks seem seems please
over under between within during while company companies stock stocks listed market latest last
quarter quarters results result report annual held stored level start wait good bad first second
third next previous year years month months week weeks day days price close high low return returns
stock today yesterday far long term short term whom whose whether""".split())

GENERIC = set("""close date latest last quarter quarters company companies results result report annual
hold held stored market stock stocks listed which what does management management's
large mid small micro cap caps sector sectors industry industries adjusted adjustment corporate
action actions raw historical percentage percent figure figures number numbers value values growth
change changes fell fall rise rose gain gains loss losses total data point points level levels
basis term terms period periods time times current currently latest recent recently give show
say said tell told think feel like well still even much many more most less least
way ways thing things part parts side sides case cases line lines item items
""".split())

EVENT_WORDS = re.compile(r"\b(announc|after results|on \d|rose|fell|jump|drop|gap|demerger|"
                         r"bonus|split|dividend|deal|block|bulk|insider|pledge|leakage)\w*", re.I)
TECH_WORDS = re.compile(r"\b(rsi|breakout|support|resistance|52[- ]week|ytd|all[- ]time|highest|"
                        r"lowest|range|delivery|accumul|relative strength|oversold|gap)\w*", re.I)
SCREEN_WORDS = re.compile(r"\b(which (?:companies|large|mid|small|stocks|names)|rank|screen|"
                          r"biggest|most|least|top)\b", re.I)
COMPARE_WORDS = re.compile(r"\b(versus|vs\.?|compare|peer|better|worse|against|relative to|"
                           r"which has|which one)\b", re.I)
TEXT_WORDS = re.compile(r"\b(say|said|says|comment|commentary|explain|why|kyun|what did|what does|"
                        r"per its|according to|transcript|presentation|annual report|note|"
                        r"management|discuss|detail|mention|mentioned|talk about|spoke about)\b",
                        re.I)
LIST_ASK = re.compile(r"which (companies|managements|large-caps?|mid-caps?|small-caps?|stocks|"
                      r"names).{0,80}(said|filed|wrote|took|evaluating|reported|declared|"
                      r"announced)", re.I)
RIPPLE_WORDS = re.compile(r"\b(ripple|transmission|pass[- ]through|beneficiar|second[- ]order|"
                          r"scheme|policy|tariff|customs|subsid|pli)\b", re.I)


def _first(value: Any) -> str | None:
    if isinstance(value, list) and value:
        text = str(value[0]).strip()
        return text or None
    text = str(value or "").strip()
    return text or None


def symbols(case: dict) -> list[str]:
    out: list[str] = []
    for entity in case.get("entities") or []:
        if not isinstance(entity, dict):
            continue
        for key in ("isin", "symbol", "nse_symbol"):
            value = str(entity.get(key) or "").strip()
            if value and value.upper() not in out:
                out.append(value.upper())
    if not out:
        for entity in case.get("entities") or []:
            if isinstance(entity, dict) and entity.get("bse_code"):
                out.append(str(entity["bse_code"]).strip())
                break
    if out:
        return out
    if str(case.get("entity_level") or "stock") != "stock":
        return out
    stop = {"NSE", "BSE", "FY", "INR", "US", "EU", "FII", "DII", "RBI", "PIB", "MPC", "SEBI",
            "GST", "CPI", "WPI", "PLI", "ETF", "IPO", "JV", "AR", "NIFTY", "Q1", "Q2", "Q3",
            "Q4", "HFC", "OMC", "NPA", "ROIC", "WACC", "EV", "LTV", "INDIAS", "MISSION",
            "CY2026", "EBITDA", "PAT", "PB", "PE", "ROE", "NIM", "CAGR", "YOY", "QOQ", "AND"}
    for match in re.findall(r"\b([A-Z][A-Z0-9&\-]{2,15})\b", str(case.get("question") or "")):
        if match.upper() not in stop and not re.match(r"^(FY|Q[1-4])", match):
            out.append(match.upper())
        if len(out) >= 2:
            break
    if not out:
        bse = re.search(r"\b(5\d{5}|6\d{5}|9\d{5})\b", str(case.get("question") or ""))
        if bse:
            out.append(bse.group(1))
    return out


def parse_dates(text: str) -> list[str]:
    out: list[str] = []
    for match in re.finditer(r"(\d{4})-(\d{2})-(\d{2})", text):
        out.append(match.group(0))
    for match in re.finditer(rf"\b(\d{{1,2}})\s+{_MONTH_RE}[a-z]*\s+(\d{{4}})\b", text, re.I):
        out.append(f"{match.group(3)}-{MONTHS[match.group(2).lower()[:3]]:02d}-{int(match.group(1)):02d}")
    return out


def _quarter_end(fy: int, quarter: int) -> str:
    return {1: f"{fy - 1}-06-30", 2: f"{fy - 1}-09-30",
            3: f"{fy - 1}-12-31", 4: f"{fy}-03-31"}[quarter]


def period_bounds(case: dict) -> tuple[str | None, str | None, str]:
    """(date_from, date_to, basis). ``basis`` says which slot produced them."""
    as_of = str(case.get("as_of") or "")[:10] or None
    period = str(case.get("period") or "")
    question = str(case.get("question") or "")
    text = f"{period} {question}"
    dates = parse_dates(period) or parse_dates(question)
    if len(dates) >= 2:
        return min(dates), max(dates), "named dates"
    if len(dates) == 1:
        return dates[0], dates[0], "named date"
    month_re = rf"{_MONTH_RE}[a-z]*[\s\-]+(\d{{4}})"
    months = [(int(m.group(2)), MONTHS[m.group(1).lower()[:3]])
              for m in re.finditer(month_re, period, re.I)]
    if not months:
        # The case's own period field wins; a question that merely mentions a
        # comparison month ("Sep-2026 vs Feb-2026") must not widen the window.
        months = [(int(m.group(2)), MONTHS[m.group(1).lower()[:3]])
                  for m in re.finditer(month_re, question, re.I)]
    if len(months) >= 2:
        (y1, m1), (y2, m2) = months[0], months[-1]
        last = {1: 31, 2: 29, 3: 31, 4: 30, 5: 31, 6: 30, 7: 31, 8: 31, 9: 30,
                10: 31, 11: 30, 12: 31}[m2]
        return f"{y1}-{m1:02d}-01", f"{y2}-{m2:02d}-{last}", "month span"
    match = re.search(r"Q([1-4])\s*FY(\d{2,4})", text, re.I)
    if match:
        fy = int(match.group(2))
        fy = 2000 + fy if fy < 100 else fy
        day = _quarter_end(fy, int(match.group(1)))
        return day, day, "quarter end"
    match = re.search(r"FY(\d{2,4})", text, re.I)
    if match:
        year = match.group(1)
        year = 2000 + int(year) if len(year) == 2 else int(year)
        return f"{year}-03-31", f"{year}-03-31", "fiscal year end"
    from datetime import date, timedelta
    if as_of:
        end = date.fromisoformat(as_of)
        low = text.lower()
        if re.search(r"\b(?:last|previous|prior)\s+quarter\b", low):
            # "last quarter" is the most recent quarter that has closed: the ask
            # is a dated quarter, not an open-ended lookback.
            ends = [f"{end.year - 1}-12-31", f"{end.year}-03-31", f"{end.year}-06-30",
                    f"{end.year}-09-30", f"{end.year}-12-31"]
            closed = [day for day in ends if day < as_of]
            if closed:
                return closed[-1], closed[-1], "quarter end"
        if re.search(r"\bytd\b|year[- ]to[- ]date", low):
            return f"{as_of[:4]}-01-01", as_of, "year to date"
        if re.search(r"52[- ]week", low):
            return (end - timedelta(days=365)).isoformat(), as_of, "52 weeks"
        spans = {"3-yr": 3, "3 yr": 3, "three-year": 3, "3 year": 3,
                 "five-year": 5, "5-yr": 5, "5 yr": 5, "two-year": 2, "2-yr": 2, "2 yr": 2,
                 "last year": 1, "past year": 1, "one-year": 1, "one year": 1, "12-month": 1,
                 "six-month": 0.5, "6-month": 0.5, "six month": 0.5, "6 month": 0.5,
                 "two months": 2 / 12, "two month": 2 / 12, "3-month": 0.25, "three month": 0.25,
                 "quarter": 0.25, "one month": 1 / 12}
        for key, span in spans.items():
            if key in low:
                return ((end - timedelta(days=int(round(365.25 * span)))).isoformat(),
                        as_of, f"lookback {key}")
        match = re.search(rf"{_MONTH_RE}[a-z]*\s+(\d{{4}})", period, re.I)
        if match:
            year, month = int(match.group(2)), MONTHS[match.group(1).lower()[:3]]
            last = {1: 31, 2: 29, 3: 31, 4: 30, 5: 31, 6: 30, 7: 31, 8: 31, 9: 30,
                    10: 31, 11: 30, 12: 31}[month]
            return f"{year}-{month:02d}-01", f"{year}-{month:02d}-{last}", "month"
        return as_of, as_of, "as_of"
    return None, None, "none"


def metric_of(question: str) -> tuple[str | None, list[str]]:
    low = question.lower()

    def hit(key: str) -> bool:
        # Short keys ("pe", "pat", "eps") must be whole words: "speciality"
        # contains "pe" and "shareholding pattern" contains "pat".
        if len(key) <= 3:
            return re.search(r"(?<![a-z0-9])" + re.escape(key) + r"(?![a-z0-9])", low) is not None
        return key in low

    for name, keys in METRICS:
        if any(hit(key) for key in keys):
            return name, [k for k in keys if hit(k)] or [name]
    return None, []


def key_terms(question: str) -> list[str]:
    words = re.findall(r"[A-Za-z]{4,}", question.lower())
    out: list[str] = []
    for word in words:
        if word in STOP or word in GENERIC or word in out:
            continue
        out.append(word)
    return out[:8]


def doc_type_of(question: str) -> str | None:
    low = question.lower()
    for key, doc_type in (("transcript", "transcript"), ("concall", "transcript"),
                          ("presentation", "deck"), ("investor ppt", "deck"),
                          ("deck", "deck"), ("annual report", "ar"),
                          ("announcement", "announcement")):
        if key in low:
            return doc_type
    return None


DOC_PHRASE = re.compile(r"\b(presentation|investor ppt|deck|transcript|concall|annual report|"
                        r"announcement)\b", re.I)


def page_of(question: str) -> int | None:
    match = re.search(r"\bpage\s+(\d{1,4})\b", question, re.I)
    return int(match.group(1)) if match else None


def named_document(case: dict) -> dict[str, Any] | None:
    """(doc_type, date) when the question names a document, else None.

    "per its investor presentation of 5 August 2026" -> deck at 2026-08-05;
    "the transcript of 18 September 2026" -> transcript at 2026-09-18.  A date
    with no document phrase is a price/series date, not a document.
    """
    question = str(case.get("question") or "")
    doc_type = doc_type_of(question)
    if not doc_type:
        return None
    dates = [(match.start(), match.group(0)) for match in re.finditer(
        rf"(?:\d{{4}}-\d{{2}}-\d{{2}}|\b\d{{1,2}}\s+{_MONTH_RE}[a-z]*\s+\d{{4}}\b)", question, re.I)]
    if not dates:
        return None
    phrase = DOC_PHRASE.search(question)
    anchor = phrase.start() if phrase else 0
    _, raw = min(dates, key=lambda item: abs(item[0] - anchor))
    parsed = parse_dates(raw)
    if not parsed:
        return None
    return {"doc_type": doc_type, "date": parsed[0]}


def needs_of(case: dict, refs: list[str], metric: str | None) -> dict[str, bool]:
    question = str(case.get("question") or "")
    family = set(case.get("family") or [])
    level = str(case.get("entity_level") or "stock")
    answer_kind = str(case.get("answer_kind") or "").lower()
    text_ask = bool(TEXT_WORDS.search(question)) or answer_kind in ("text+quote", "explanation")
    price_ask = bool(re.search(r"\b(close|price|return|cagr|high|low|rsi|delivery|range|"
                               r"gap|volume|turnover|relative strength|listing|tracking error|"
                               r"max pain|pcr|open interest|inav)\b", question, re.I))
    date_from, date_to, _ = period_bounds(case)
    window = bool(date_from and date_to and date_from != date_to)
    entities = [e for e in (case.get("entities") or []) if isinstance(e, dict)]
    multi = len(entities) > 1 or bool(COMPARE_WORDS.search(question))
    list_ask = bool(LIST_ASK.search(question))
    needs = {
        "price": price_ask or bool(family & {2, 9, 12, 15, 16, 20}) or window
                 or metric in {"return", "cagr", "range", "rsi", "gap", "delivery"},
        "financials": bool(metric) or bool(family & {1, 2, 3, 4, 8, 11, 13, 14, 16, 17}) or
                      any("xbrl" in r or "facts" in r for r in refs),
        "text": text_ask or list_ask or any("document_chunks" in r or "raw_documents" in r or
                                            "announcement" in r for r in refs),
        "event": bool(EVENT_WORDS.search(question)),
        "screen": (level != "stock" or bool(SCREEN_WORDS.search(question))) and not list_ask,
        "compare": (bool(family & {8, 13}) and multi) or bool(COMPARE_WORDS.search(question)),
        "ripple": bool(family & {6, 7, 18, 19}) or bool(RIPPLE_WORDS.search(question)) or
                  str(case.get("source_bank")) == "ripple200",
        "page": page_of(question),
        "technical": bool(TECH_WORDS.search(question)),
        "intraday": bool(re.search(r"\bintraday|number of tests|how many times\b", question, re.I)),
    }
    if list_ask:
        # A corpus-wide list cannot be answered from one proxy company's rows.
        needs.update({"financials": False, "price": False, "event": False,
                      "compare": False, "screen": False})
    return needs


def _planner_for_ref(ref: str) -> str | None:
    low = str(ref or "").lower()
    for keys, planner in REF_RULES:
        if any(key in low for key in keys):
            return planner
    return None


def _status(case: dict) -> tuple[str, str | None]:
    explicit = case.get("case_status") or case.get("status")
    if explicit:
        reason = case.get("status_reason")
        return str(explicit), reason
    coverage = case.get("coverage") or {}
    gap = coverage.get("gap") if isinstance(coverage, dict) else None
    path = str((gap or {}).get("path") or "") if isinstance(gap, dict) else ""
    if path == "never" or coverage.get("verdict") == "never":
        return "NOT_IN_DATA", "no source publishes this fact"
    if "fetch" in path:
        return f"needs_new_fetch:{coverage.get('gap_id') or 'unknown'}", None
    if "table" in path:
        return f"needs_new_table:{coverage.get('gap_id') or 'unknown'}", None
    return "answerable_now", None


def route(case: dict) -> dict[str, Any]:
    """The case's planner chain, slots and declared status. Pure and deterministic."""
    family = [int(f) for f in (case.get("family") or []) if str(f).isdigit()]
    question = str(case.get("question") or "")
    refs = [str(r) for r in ((case.get("rubric") or {}).get("required_evidence") or [])
            if str(r).strip()]
    for hop in case.get("chain") or []:
        if isinstance(hop, dict):
            refs += [str(r) for r in (hop.get("evidence_needed") or [])]
    metric, terms = metric_of(question)
    date_from, date_to, basis = period_bounds(case)
    symbols_found = symbols(case)
    isin = next((s for s in symbols_found if s.startswith("IN")), None)
    symbol = next((s for s in symbols_found if not s.startswith("IN")), None)
    needs = needs_of(case, refs, metric)
    status, status_reason = _status(case)
    table = status.split(":", 1)[-1] if status.startswith("needs_new_table:") else None
    if table in {"company_cost_structure", "company_segment_pnl", "company_price_revision",
                 "macro_claim_target", "company_sector_pit"}:
        # The CASE_MAP names a ripple-stage table: the chain must run RIPPLE so
        # the answer names that table instead of drifting into a price answer.
        needs["ripple"] = True

    chain: list[str] = ["resolve"]
    if str(case.get("template") or "") in OPINION_TEMPLATES or OPINION_ASK.search(question):
        chain.append("EXPECTATIONS")
    if needs["ripple"]:
        chain.append("RIPPLE")
    if needs["screen"]:
        chain.append("SCREEN")
    if needs["event"]:
        chain.append("EVENT")
    if needs["compare"]:
        chain.append("COMPARE")
    if needs["financials"]:
        chain.append("FACTS")
    if needs["price"]:
        chain.append("SERIES")
    if needs["text"]:
        chain.append("EVIDENCE")
    for ref in refs:
        planner = _planner_for_ref(ref)
        if planner:
            chain.append(planner)
    for fam in family:
        chain += FAMILY_PLANNERS.get(fam, [])
    # Evidence refs are the question's own declaration: a text answer needs them.
    if str(case.get("answer_kind") or "").lower() in ("text+quote", "explanation") and "EVIDENCE" not in chain:
        chain.append("EVIDENCE")
    chain = [p for i, p in enumerate(chain) if p in CANONICAL_ORDER and p not in chain[:i]]
    chain.sort(key=CANONICAL_ORDER.index)
    if "resolve" in chain:
        chain.remove("resolve")
    chain = ["resolve"] + chain

    slots = {
        "symbol": symbol, "isin": isin, "symbols": symbols_found,
        "entity_level": str(case.get("entity_level") or "stock"),
        "as_of": str(case.get("as_of") or "")[:10] or None,
        "period": case.get("period"), "date_from": date_from, "date_to": date_to,
        "period_basis": basis, "question": question,
        "terms": key_terms(question), "metric": metric, "metric_terms": terms,
        "doc_type": doc_type_of(question), "page": needs["page"], "needs": needs,
        "source_bank": case.get("source_bank"), "family": family,
        "answer_kind": case.get("answer_kind"), "template": case.get("template"),
        "status": status,
    }
    return {"chain": chain, "slots": slots, "as_of": slots["as_of"] or "2099-12-31",
            "status": status, "status_reason": status_reason, "pit_keys": _pit_keys(chain)}


def _pit_keys(chain: list[str]) -> dict[str, str]:
    return {
        "resolve": "symbol_isin_history first_date/last_date window at as_of",
        "EXPECTATIONS": "none: no consensus/advice store is held",
        "FACTS": "row filing timestamp (dissem_ts|filed_at|known_at) <= as_of",
        "SERIES": "date <= as_of (session close)",
        "SCREEN": "snapshot/membership interval at as_of",
        "EVENT": "known_at_utc <= as_of -> session; windows only backwards",
        "EVIDENCE": "chunk published_date / doc known_at <= as_of",
        "COMPARE": "same clause as the underlying hop per peer",
        "RIPPLE": "claim known_at <= as_of; downstream rows knowable by as_of",
    }
