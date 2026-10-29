"""Entity / ask / period gate for the answer contract (2026-10-29).

The pilot-60 hand check found 55 of 60 ANSWERED rows substantively wrong: every
hop returned rows, but the rows were about another metric, another period or a
document that never addressed the ask.  This module is the deterministic gate
the answer contract needs:

* ``entity`` -- an entity-scoped row must name the asked ISIN/symbol;
* ``ask``    -- the run's rows must carry the asked concept (alias table below),
               or, when the ask names no known concept, a key term of the ask;
* ``period``-- a row used for a dated/quarter/fiscal-year ask must sit in that
               period (named document +/-3d, quarter, month, fiscal year).

No model, no network, no I/O: every check reads the hop rows and the routed
slots, so the same functions run inside the answerer (``answer.py``) and inside
the strict grader (``tasks/answer_bench/grade_v1.py``), which recomputes the
flags from the returned rows instead of trusting them.

``METRIC_SYNONYMS`` moved here from ``answer.py`` (it is the same alias table the
ask gate needs); ``answer`` re-exports the name for its callers.
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

# canonical metric -> (include phrases, exclude phrases).  Phrases are matched
# as substrings of the normalised row text; the excludes stop the trap the v0
# bench hit ("Net Promoter Score" is not promoter holding, a "sales volume drop"
# is not revenue).
METRIC_SYNONYMS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "revenue": (("revenue", "turnover", "sales", "income from operations", "topline"),
                ("sales volume", "volume drop", "growth in volume")),
    "pat": (("pat", "profit after tax", "net profit", "net income", "profit", "bottom line"),
            ("margin", "operating profit", "profit before tax")),
    "ebitda": (("ebitda", "operating profit"), ("margin",)),
    "margin": (("margin", "opm"), ()),
    "eps": (("eps", "earnings per share"), ()),
    "net_npa": (("npa", "non performing", "non-performing"), ("net worth",)),
    "promoter": (("promoter", "shareholding", "stake", "holding pattern", "pledge",
                  "promoter holding", "public holding", "holding %"),
                 ("net promoter", "nps", "promoter score", "total shareholding pattern",
                  "shares outstanding", "paid-up", "paid up", "share capital")),
    "facilities": (("facilit", "plant", "factory", "factories", "manufacturing unit"),
                   ("capacity", "capex", "installation")),
    "capacity": (("capacity", "capacities", "utilisation", "utilization", "mtpa", "tpa"),
                 ("capacity utilisation of the plant",)),
    "order_book": (("order book", "orderbook", "order intake", "orders"), ()),
    "dso": (("receivable", "debtor", "collection", "dso"), ()),
    "cfo": (("cash flow", "cfo", "operating cash"), ()),
    "segment": (("segment", "business mix", "vertical", "division"), ()),
    "return": (("return", "close", "rose", "fell", "gained", "dropped", "moved",
                "performance", "cagr", "excess"), ("dividend", "total return")),
    "cagr": (("cagr", "annualised", "annualized"), ()),
    "range": (("high", "low", "range", "support", "resistance", "52-week", "52 week", "ytd"), ()),
    # A "gap" ask is a price gap, not the "data gaps" a question asks the answerer to name.
    "gap": (("gap up", "gap down", "gapped", "opening gap", "gap open"), ("data gap",)),
    "rsi": (("rsi", "oversold", "overbought"), ()),
    "delivery": (("delivery", "delivered"), ()),
    # A valuation ask names a ratio (P/E, P/B, EV/EBITDA, book value, market cap).
    # Bare "premium" / "discount" / "multiple" are about products, spot-vs-futures
    # and "multiple plants": demanding a valuation row for those is a wrong ask.
    "valuation": (("valuation", "pe", "p/e", "pe ratio", "price to earnings", "p/b", "pb",
                   "price to book", "pb ratio", "book value", "ev/ebitda", "ev/sales",
                   "market cap", "market capitalisation", "market capitalization"), ()),
    "guidance": (("guidance", "guided", "outlook", "expects", "target"), ()),
    "audit": (("audit", "auditor", "opinion", "qualified", "qualification"), ()),
}

#: Concepts the master bank asks for that the router's metric list does not name.
#: (include phrases, exclude phrases) -- same substring rule as METRIC_SYNONYMS.
ASK_CONCEPTS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "products": (("product", "offerings", "portfolio of"), ("production capacity",)),
    "volume": (("volume", "volumes", "traded quantity"), ()),
    "band": (("price band", "band", "circuit", "base price"), ("bandwidth",)),
    "open_interest": (("open interest", "rollover", "short covering", "short-covering",
                       "futures basis", "oi addition", "oi added", "cost of carry"), ()),
    "roic": (("roic", "return on invested capital", "return on capital", "incremental return",
              "cost of capital", "cost of equity", "wacc", "spread over"), ()),
    "capex": (("capex", "capital expenditure", "capital spending"), ()),
    "public_holding": (("public shareholding", "public holding", "public stake",
                        "non-promoter", "free float"), ()),
    "fii": (("fii", "fpi", "foreign institutional", "foreign portfolio"), ()),
    "dii": (("dii", "domestic institutional", "mutual fund"), ()),
    "share_count": (("shares outstanding", "paid-up", "paid up", "share capital"), ()),
    "dividend": (("dividend", "payout"),
                 # "split- and dividend-adjusted closes" names the CAGR's adjustment
                 # basis, not a dividend ask: the ask is the CAGR.
                 ("dividend adjusted", "dividends and splits", "adjusting for dividend",
                  "dividend and split")),
    "rating": (("rating", "rated", "downgrade", "upgrade", "credit watch",
                "outlook revision"), ()),
    "working_capital": (("receivable", "debtor", "inventory", "working capital",
                         "cash conversion"), ()),
    # An ISIN in the ask is an entity reference ("ISIN INE864I01014 said..."), not an
    # identity-change ask; only the change/rename/mapping wording is the concept.
    "isin_identity": (("isin change", "renam", "name change", "symbol change", "mapping"), ()),
    "acquisition": (("acquisition", "acquire", "stake sale", "stake purchase", "demerger",
                     "amalgamat", "scheme of arrangement"), ()),
    "index_inclusion": (("index inclusion", "index entry", "passive buying", "passive flow",
                         "index-driven", "rebalance"), ()),
    "futures": (("futures", "premium to spot", "basis widening", "rollover",
                 "open interest", "short covering", "short-covering", "cost of carry",
                 "oi addition", "oi added"), ("on the basis",)),
    # "manufacturing licence" is not a spectrum licence: the spectrum word is the ask.
    "spectrum": (("spectrum", "spectrum-liability"), ()),
    "listing": (("listing date", "listed on", "listing"), ()),
    "pledge": (("pledge",), ()),
    # The event/relation asks the pilot-60 hand check found answered with an
    # adjacent passage ("auditor fees" for "auditor resigned", a close for a
    # chart pattern): the phrase, not the topic word, is the ask.
    "control_change": (("change in control", "control change", "change of control",
                        "takeover", "management change", "promoter change",
                        "change in management"), ()),
    "auditor_resignation": (("secretarial auditor", "statutory auditor resign",
                             "auditor resigned", "auditor resignation",
                             "auditor's resignation", "resignation of the auditor"), ()),
    "chart_pattern": (("cup and handle", "cup-and-handle", "head and shoulders",
                       "chart pattern", "technical pattern", "double bottom",
                       "double top", "flag pattern", "breakout", "fade"), ()),
    "nim": (("nim", "net interest margin"), ()),
    "loan_growth": (("loan growth", "credit growth", "advances growth", "aum growth",
                     "book growth", "loan book"), ()),
    "lag": (("lag", "lagged", "quarters before", "months before"), ()),
    "credit_cost": (("provision", "provisioning", "credit cost", "write-back", "write back",
                     "stressed book", "slippage"), ()),
    "options": (("max pain", "call oi", "put oi", "open interest", "strike", "expiry",
                 "option"), ()),
}

#: A row that carries a narrower concept also answers the broader one.
RELATED: dict[str, set[str]] = {
    "return": {"cagr", "range", "rsi", "gap", "delivery", "volume", "band", "open_interest",
               "futures", "valuation", "spread"},
    "promoter": {"public_holding", "fii", "dii", "share_count", "pledge"},
    "acquisition": {"listing", "index_inclusion"},
}
#: Narrower price asks a plain "close" row must not satisfy.
SPECIFIC_RETURN = {"cagr", "range", "rsi", "gap", "delivery", "volume", "band",
                   "open_interest", "futures", "valuation", "spread"}

#: Row keys that carry the entity identity, in order of preference.
ENTITY_KEYS = ("isin", "symbol", "nse_symbol", "bse_code")
#: Tokens in a ``ref`` that name a store or a placeholder, never a company.
STORE_TOKENS = {"SERIES", "FACTS", "EVIDENCE", "EVENT", "SCREEN", "COMPARE", "RIPPLE",
                "RESOLVE", "EXPECTATIONS", "DOCS", "CHUNKS_V3", "BSE_ANN", "EVENTS",
                "DAILY_PRICE_DELIVERY", "SHP_INDEX", "RESULTS_XBRL", "AR_FACTS",
                "DECK_FIGURES", "CONCALL_FACTS", "DOCUMENT_CHUNKS", "INTELLIGENCE_FTS",
                "POLICY_EVENTS", "COMPUTED", "MKT_NSE_FULL_DAILY",
                "NONE", "NULL", "NAN", "TRUE", "FALSE", "UNKNOWN", "TBD"}
#: Keys whose text the ask check reads.
ROW_TEXT_KEYS = ("item", "metric", "quote", "text", "context", "section", "header",
                 "period", "unit", "ref", "symbol", "isin", "name", "title")
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
QTR_RE = re.compile(r"Q([1-4])\s*FY\s*(\d{2,4})", re.I)
FY_RE = re.compile(r"FY\s*(\d{2,4})", re.I)
MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}


def norm(text: Any) -> str:
    return re.sub(r"[^a-z0-9%./ ]+", " ", str(text or "").lower())


def metric_matches(metric: str | None, text: Any) -> bool:
    """Does ``text`` belong to the asked metric family?  Unknown metric -> True.

    Look-alike phrases are stripped first, not used as a veto: a slide that says
    "Manufacturing Facilities ... Washing Capacity" is a facilities passage, a
    transcript that says "margins ... ebitda margins" is an EBITDA passage, and
    "Net Promoter Score (NPS)" stops being a promoter-holding row once "net
    promoter" and "nps" are removed.
    """
    if not metric or metric not in METRIC_SYNONYMS:
        return True
    include, exclude = METRIC_SYNONYMS[metric]
    low = norm(text)
    for word in exclude:
        low = low.replace(word, " ")
    return any(_phrase_hit(low, word) for word in include)


def evidence_matches(metric: str | None, text: Any) -> bool:
    """Same family test for EVIDENCE quotes (long text, same stripping rule)."""
    return metric_matches(metric, text)


#: Endings a short alias may carry and still be the same word ("high" -> "higher",
#: "margin" -> "margins").  The near-misses the v0 table let through ("pe" inside
#: "per"/"complete", "pat" inside "patterns", "rsi" inside "diversification",
#: "eps" inside "steps") are not among them.
_WORD_ENDINGS = ("", "s", "es", "er", "ers", "ed", "ing", "est", "ion", "ions", "ity")


def _phrase_hit(low: str, phrase: str) -> bool:
    """A phrase is a substring; a short alias is a word (with a plural/degree ending).

    Whole-word matching alone lost the real asks ("higher highs", "margins"), and
    open substring matching invented asks ("per" -> "pe"), so short aliases match
    the word plus an inflection and nothing else.
    """
    if len(phrase) > 6 or " " in phrase or "/" in phrase:
        return phrase in low
    for ending in _WORD_ENDINGS:
        if re.search(r"(?<![a-z0-9])" + re.escape(phrase + ending) + r"(?![a-z0-9])", low):
            return True
    return False


def _concept_hit(text: str, concept: str) -> bool:
    low = norm(text)
    include, exclude = ASK_CONCEPTS.get(concept) or METRIC_SYNONYMS.get(
        concept, ((), ()))
    if not include:
        return False
    for word in exclude:
        low = low.replace(word, " ")
    return any(_phrase_hit(low, word) for word in include)


# --------------------------------------------------------------------------
# entity
# --------------------------------------------------------------------------
def _ref_tokens(ref: Any) -> list[str]:
    out = []
    for part in re.split(r"[#:/]", str(ref or "")):
        token = part.strip().upper()
        if not token or token in STORE_TOKENS or DATE_RE.fullmatch(token):
            continue
        if not re.search(r"[A-Z]", token):  # a numeric row/page id is not an entity
            continue
        if re.fullmatch(r"IN[A-Z0-9]{9,11}", token) or re.fullmatch(r"[A-Z0-9&\-]{2,20}", token):
            out.append(token)
    return out


def row_entities(row: Any) -> set[str]:
    if not isinstance(row, dict):
        return set()
    out = set()
    for key in ENTITY_KEYS:
        value = row.get(key)
        if value not in (None, ""):
            out.add(str(value).strip().upper())
    out.update(_ref_tokens(row.get("ref")))
    return {value for value in out if value}


def asked_entities(slots: dict[str, Any]) -> set[str]:
    out = set()
    for key in ("isin", "symbol"):
        value = slots.get(key)
        if value:
            out.add(str(value).strip().upper())
    for value in slots.get("symbols") or []:
        if value:
            out.add(str(value).strip().upper())
    return out


def entity_match(hop: dict[str, Any], slots: dict[str, Any]) -> bool | None:
    """Rows name the asked entity?  ``None`` when the rows carry no identity.

    SCREEN/COMPARE rank a peer set, so a single entity is not the subject: the
    check only fails when the asked entity is itself one of the rows it should
    have matched (a follow-up priced on the wrong pick).
    """
    asked = asked_entities(slots)
    if not asked:
        return None
    found: set[str] = set()
    for row in hop.get("rows") or []:
        found |= row_entities(row)
    if not found:
        return None
    if hop.get("hop") in ("SCREEN", "COMPARE", "RIPPLE"):
        return True if found & asked else None
    return bool(found & asked)


# --------------------------------------------------------------------------
# ask
# --------------------------------------------------------------------------
def row_text(row: Any) -> str:
    """Only the fields the answer shows: a hidden numeric key ("high": 1710.0)
    is not evidence that the answer reported a high."""
    if not isinstance(row, dict):
        return str(row or "")
    return " ".join(str(row.get(key) or "") for key in ROW_TEXT_KEYS
                    if row.get(key) not in (None, ""))


def asked_concepts(question: str) -> list[str]:
    """The concepts the question names, most specific first.

    Overlapping splits are resolved explicitly: "public shareholding" is the
    public-holding concept, not promoter holding; "return on capital" is ROIC,
    not a price return; "price band" is the band, not a range.
    """
    low = norm(question)
    found: list[str] = []
    for concept in ASK_CONCEPTS:
        if _concept_hit(low, concept):
            found.append(concept)
    for concept in METRIC_SYNONYMS:
        if metric_matches(concept, low):
            found.append(concept)
    if "roic" in found and "return" in found:
        found.remove("return")  # "return on capital" is not a price return
    if "public_holding" in found and "promoter" in found:
        found.remove("promoter")  # the public split IS the ask
    if "band" in found and "range" in found:
        found.remove("range")  # "price band" is a circuit band, not a 52-week range
    if "futures" in found:
        found = [c for c in found if c not in ("valuation", "return", "open_interest")]
    # "price CAGR", "52-week high", "delivery" are the ask; a plain close row
    # must not satisfy them, so the general price concept drops out.
    if "return" in found and any(c in SPECIFIC_RETURN for c in found):
        found.remove("return")
    return found


def key_terms(question: str) -> list[str]:
    from .router import key_terms as router_terms
    return router_terms(question)


def _row_covers(row: Any, concept: str) -> bool:
    text = row_text(row)
    targets = {concept} | set(RELATED.get(concept) or ())
    return any(_concept_hit(text, target) or
               (target in METRIC_SYNONYMS and metric_matches(target, text))
               for target in targets)


def ask_match(hop: dict[str, Any], concepts: list[str], terms: list[str]) -> bool | None:
    """Do this hop's rows carry at least one asked concept (or key term)?

    ``None`` when the ask names no concept and no key term: nothing to check.
    The run-level ``ask_coverage`` below is what requires every concept.
    """
    rows = hop.get("rows") or []
    if not rows or not (concepts or terms):
        return None
    if concepts:
        return any(_row_covers(row, concept) for row in rows for concept in concepts)
    low = norm(" ".join(row_text(row) for row in rows) + " " + str(hop.get("detail") or ""))
    hit = [term for term in terms
           if re.search(r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])", low)]
    return len(hit) >= min(2, len(terms))


def ask_coverage(hops: list[dict[str, Any]], concepts: list[str],
                 terms: list[str]) -> tuple[bool | None, list[str]]:
    """Every asked concept must be carried by some row of the run.

    A hop's ``detail`` is a rendering of its own rows (the SERIES arithmetic
    lives there), so it counts as evidence for the concept the row carries.
    """
    if not concepts:
        if not terms:
            return None, []
        low = norm(" ".join(row_text(row) for hop in hops for row in hop.get("rows") or [])
                   + " " + " ".join(str(hop.get("detail") or "") for hop in hops))
        hit = [term for term in terms
               if re.search(r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])", low)]
        # One generic word ("control") in boilerplate is not evidence: a fallback
        # ask needs at least two of its terms (or its only term).
        if len(hit) >= min(2, len(terms)):
            return True, []
        return False, ["ask_match: too few key terms of the ask "
                       f"({', '.join(terms[:4])}) in the rows; hit "
                       f"{', '.join(hit) or 'none'}"]
    missing = []
    for concept in concepts:
        if not any(_row_covers(row, concept) or
                   _concept_hit(str(hop.get("detail") or ""), concept)
                   for hop in hops for row in hop.get("rows") or []):
            missing.append(concept)
    if not missing:
        return True, []
    return False, [f"ask_match: no row carries the asked concept ({', '.join(missing)})"]


# --------------------------------------------------------------------------
# period
# --------------------------------------------------------------------------
def _day(value: Any) -> str | None:
    match = DATE_RE.search(str(value or ""))
    return match.group(0) if match else None


def _shift(day: str, days: int) -> str:
    return (date.fromisoformat(day) + timedelta(days=days)).isoformat()


def row_day(row: dict[str, Any]) -> str | None:
    """The date the row is *about* first (period), then when it became known."""
    return _day(row.get("period")) or _day(row.get("known_at")) or _day(row.get("date"))


def period_window(slots: dict[str, Any],
                  named: dict[str, Any] | None) -> tuple[str | None, str | None, int]:
    """(low, high, tolerance days) the rows must fall in; ``(None,None,0)`` = no check."""
    if named and named.get("date"):
        anchor = _day(named["date"])
        return anchor, anchor, 3
    basis = str(slots.get("period_basis") or "")
    low, high = slots.get("date_from"), slots.get("date_to")
    if not low or not high:
        return None, None, 0
    if basis in ("named date", "named dates"):
        return low, high, 3
    if basis in ("quarter end", "fiscal year end"):
        # a fact about the period is filed after it closes (results ~60-90d,
        # annual report ~6 months): judge the row's own period label first.
        return low, _shift(high, 180 if basis == "quarter end" else 300), 0
    if basis in ("month", "month span"):
        return low, high, 3
    # "as_of", "lookback ...", "year to date", "52 weeks": the window is the
    # planner's own lookback and PIT already caps it at as_of.
    return None, None, 0


def _label(question: str, period: str) -> tuple[str | None, str | None]:
    """The quarter/fiscal-year label an ask or a row names (``Q1FY27``, ``FY26``)."""
    text = f"{period} {question}"
    match = re.search(r"Q([1-4])\s*FY\s*(\d{4})\s*[-/]\s*(\d{2,4})", text, re.I)
    if match:
        return "Q", f"Q{match.group(1)}FY{match.group(3)[-2:]}"
    match = re.search(r"FY\s*(\d{4})\s*[-/]\s*(\d{2,4})", text, re.I)
    if match:
        return "FY", f"FY{match.group(2)[-2:]}"
    qtr = QTR_RE.search(text)
    if qtr:
        year = int(qtr.group(2))
        year = 2000 + year if year < 100 else year
        return "Q", f"Q{qtr.group(1)}FY{year % 100:02d}"
    fy = FY_RE.search(text)
    if fy:
        year = int(fy.group(1))
        year = 2000 + year if year < 100 else year
        return "FY", f"FY{year % 100:02d}"
    return None, None


AS_OF_RE = re.compile(
    r"as of\s+(?:(?P<day>\d{4}-\d{2}-\d{2})|(?P<dmy>\d{1,2})\s+(?P<mon>[a-z]{3})[a-z]*\s+"
    r"(?P<y1>\d{4})|(?P<mon2>[a-z]{3})[a-z]*[\s\-]+(?P<y2>\d{4}))", re.I)


def _asof_anchor(question: str) -> tuple[str, str, int] | None:
    """"as of Sep 2026" / "as of 31 July 2026" -> (low, high, tolerance)."""
    match = AS_OF_RE.search(str(question or ""))
    if not match:
        return None
    if match.group("day"):
        day = match.group("day")
        return day, day, 3
    month = MONTHS.get((match.group("mon") or match.group("mon2") or "").lower()[:3])
    year = match.group("y1") or match.group("y2")
    if not month or not year:
        return None
    last = {1: 31, 2: 29, 3: 31, 4: 30, 5: 31, 6: 30, 7: 31, 8: 31, 9: 30, 10: 31,
            11: 30, 12: 31}[month]
    return f"{int(year)}-{month:02d}-01", f"{int(year)}-{month:02d}-{last}", 0


def period_match(hop: dict[str, Any], slots: dict[str, Any],
                 named: dict[str, Any] | None) -> bool | None:
    """Do the rows sit in the asked period?  ``None`` when no period is asked."""
    low, high, tol = period_window(slots, named)
    anchors = False
    if not low or not high:
        # An explicit "as of <month/year>" snapshot ask: a FACTS row older than
        # that month is a stale snapshot, not the holding asked for.  EVIDENCE
        # is exempt ("last said as of X" legitimately returns an older call).
        anchor = _asof_anchor(str(slots.get("question") or ""))
        if anchor and hop.get("hop") in ("FACTS", "SCREEN"):
            low, high, tol = anchor
            anchors = True
        else:
            return None
    rows = hop.get("rows") or []
    if not rows:
        return None
    kind, want = _label(str(slots.get("question") or ""), str(slots.get("period") or ""))
    lo, hi = low, high
    if tol:
        lo, hi = _shift(low, -tol), _shift(high, tol)
    for row in rows:
        if not isinstance(row, dict):
            continue
        row_period = str(row.get("period") or "")
        got_kind, got = _label("", row_period)
        if want and got:
            # The row states its own period: that label decides (a Q1FY27 deck
            # published in August is still the June quarter).
            if got != want:
                return False
            continue
        day = row_day(row)
        if day is None:
            continue
        if anchors:
            # the snapshot's own month: the row's period (or filing) must fall
            # in it, not before it
            if not (lo <= day <= _shift(hi, 90)):
                return False
        elif not (lo <= day <= hi):
            return False
    return True


# --------------------------------------------------------------------------
# one hop / one run
# --------------------------------------------------------------------------
def gate_hop(hop: dict[str, Any], slots: dict[str, Any],
             concepts: list[str], terms: list[str],
             named: dict[str, Any] | None = None) -> dict[str, Any]:
    """Annotate one hop with the three flags (``None`` = not checkable).

    The flags are annotations: ``gate_run`` decides the run, because the ask
    check is about the run's rows as a set (a two-part ask may be split over
    two hops and still be answered).
    """
    if hop.get("na") or not hop.get("ok"):
        return hop
    period = period_match(hop, slots, named)
    unit = unit_match(hop, str(slots.get("question") or ""))
    if unit is False and period is not False:
        period = False  # "absolute ... crore" answered with a unit-less row
    return dict(hop,
                entity_match=entity_match(hop, slots),
                ask_match=ask_match(hop, concepts, terms),
                period_match=period,
                unit_match=unit)


MONEY_ASK = re.compile(r"\b(absolute|in rs\.? crore|rs\.? crore|in crore|crore|inr|"
                       r"in rupees|rupees)\b", re.I)
MONEY_UNITS = ("crore", "rs", "inr", "lakh", "million", "billion", "thousand")


def unit_match(hop: dict[str, Any], question: str) -> bool | None:
    """An "absolute number in Rs crore" ask must be answered by a money row."""
    if hop.get("hop") != "FACTS" or not MONEY_ASK.search(question or ""):
        return None
    rows = hop.get("rows") or []
    if not rows:
        return None
    for row in rows:
        unit = str(row.get("unit") or "").strip().lower()
        if any(word in unit for word in MONEY_UNITS):
            return True
    return False


def gate_run(hops: list[dict[str, Any]], sub: dict[str, Any],
             concepts: list[str], terms: list[str]) -> str | None:
    """None when the run's rows pass all three checks, else the failing check."""
    checked = [hop for hop in hops if not hop.get("na") and hop.get("hop") != "resolve"]
    if not checked:
        return None
    for hop in checked:
        if hop.get("entity_match") is False:
            named = sorted({token for row in hop.get("rows") or []
                            for token in row_entities(row)})[:3]
            return (f"GATE entity_match: the {hop['hop']} rows are about "
                    f"{', '.join(named) or 'another entity'}, not the asked entity")
        if hop.get("unit_match") is False:
            return (f"GATE unit_match: the {hop['hop']} rows state no rupee unit for an "
                    f"absolute-value ask")
        if hop.get("period_match") is False:
            return (f"GATE period_match: the {hop['hop']} rows are outside the asked "
                    f"period ({sub.get('text') or ''} | {str(sub.get('period') or '')[:40]})")
    ok, missing = ask_coverage(checked, concepts, terms)
    if ok is False:
        return "GATE " + missing[0]
    return None
