"""T-228: turn verbatim management text into quantified claims on the driver tree.

Shivam 20 Nov 2026; stage 1a-fix 21 Nov (Wolf's review): claims now carry the two statements before them and
the analyst question, carry script checks on unit/period/sign, and pass a second, independent judge
(``beam-free``) before they may be called ``verified``.

Stage 2a (21 Nov, brief T-228 stage 2): the sources widen past the call transcript.  ``doc_page`` paragraphs
from annual reports, press releases and exchange announcements are added to the item builder (``doc_items``),
with a paragraph-level forward-cue and number-with-unit filter.  Announcements also get a deterministic
pre-parse (``announcement_claims``) for the three shapes exchanges print in full: an order win with its
execution period (``revenue.order_book``), a board-approved capex amount (``capex.amount``) and a
QIP/warrant/rights size with its issue price (``equity.shares``).  A row the script parses fully becomes a
claim with ``method='script'``; every other row goes to the model.  Each claim now carries ``source_kind``
(transcript, guidance, annual_report, press_release, announcement).

Stage 2b (21 Nov, Wolf's hand read of the 2a pilot): a level claim whose own paragraph names a unit, plant,
product or new line is that unit's increment, not a company-wide level (prompt rule plus a judge-confirmed
``scope_ok``); a printed range ("at least 20% to 25%") keeps both ends instead of becoming a target on the
high end; "including/excluding GST" is copied into ``base``; a rating-agency rationale (CRISIL, ICRA, CARE,
India Ratings, Acuite, Brickwork) is tagged ``speaker_scope='rating_agency'`` and never verified as the
company's claim; the same fact from two sources is folded into the earliest row with the others' ids in
``dup_of``; a debt repayment is sign ``-`` and a declared dividend ``+``; and the judge is given the claim's
own ``known_at`` so a stale target period is judged against the document date.

A statement that ends in no tree node (revenue, operating cost, capex, debt, equity, working capital) is
show, not data: it is dropped.  The output is one SQLite DB of claims, each carrying the exact quote it came
from, its context and the source row's own ``known_at``.

Three producers, three layers of check:
* **script**: a ``guidance`` row whose metric already names a node maps straight to a claim (no model call);
  the mapping table is ``GUIDANCE_MAP``.  An announcement paragraph whose order win, capex approval or fund
  raise the deterministic parser reads in full is also a script claim.  Unmapped guidance rows and
  forward-looking ``transcript_statement`` / ``doc_page`` rows go to ``hy4-flash-free`` on OpenCode Go,
  <= 10 per request, JSON out.
* **independent check 1 (script)**: ``quote_span`` must be a (whitespace-normalised) substring of the stored
  statement; every value must be a printed number inside the span; the unit word in the span must agree with
  the unit; a range stated as "plus or minus"/"+/-"/"±" forces sign 0; a claim needs an ``effective_period``
  or a forward horizon in its span.
* **independent check 2 (judge)**: ``beam-free`` (free on Go, same endpoint, stable session id) reads the
  claim, its statement and its context and answers ``node_ok``, ``sign_ok``, ``unit_ok``, ``period_ok``,
  ``forward_ok``.  ``verified`` means the script check passed AND all five judge fields are true; otherwise
  the claim is ``unverified`` with the failing field stored.  A claim whose quote is not in the statement is
  ``quarantined`` and never judged.

Claims are deduplicated by ``(symbol, normalised quote_span, node)``.

Reads: the pilot3 stores ``D:/RealityEngine/tg_build/measure10/cNN/cNN.db`` (``mode=ro``, never written).
Writes: only ``--out`` (default ``.tmp/t228/claims.db``) and, when not under pytest, one run row in the run
ledger.  No store, no page_reader DB, no spend DB is touched; both models are free.

    python -m reality_engine.research.driver_claims --stores c09 c11 c17 c61 c88 --pick 2 --pick-seed 7
    python -m reality_engine.research.driver_claims --stores ... --dry-run
    python -m reality_engine.research.driver_claims --unleashed            # stage 1b, not this stage
    python -m reality_engine.research.driver_claims --stores ... --doc-types annual_report press_release
    python -m reality_engine.research.driver_claims --report --out .tmp/t228/claims.db --seed 29

Tables: ``claim`` (one row per claim), ``read_log`` (one row per HTTP request, extract and judge),
``quota_event`` (every 429/5xx/timeout with UTC and IST time, in-flight count, body head).
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import re
import sqlite3
import threading
import time
from collections import Counter, defaultdict, deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

MODEL = "hy4-flash-free"
JUDGE_MODEL = "beam-free"
BASE = "https://opencode.ai/zen/go/v1"
# reasoning_effort "none" is REQUIRED for hy4: with "low" it spends its whole budget thinking and returns
# nothing (T-225, 18 Nov; same lesson as scripts/extract_deck_figures.py).
MODEL_BODY: dict[str, Any] = {"temperature": 0, "max_tokens": 8000, "reasoning_effort": "none"}
JUDGE_BODY: dict[str, Any] = {"temperature": 0, "max_tokens": 16000}   # beam reasons; 3k left content empty
STORE_ROOT = Path(os.environ.get("T228_STORE_ROOT", "D:/RealityEngine/tg_build/measure10"))
DEFAULT_OUT = Path(".tmp/t228/claims.db")
BATCH = 10
JUDGE_BATCH = 5
WINDOW_S = 300.0          # the limiter judges the error rate over the last 5 minutes
FAIL_STOP_S = 1800.0      # stop after 30 consecutive minutes of failures
MAX_TRANSPORT_TRIES = 4
MAX_JUDGE_TRIES = 3        # the judge: first attempt + two retries with backoff (Wolf, round 3)
JUDGE_BACKOFF_S = (2.0, 4.0)
EMPTY_STOP_SHARE = 0.20   # stage 1a stop condition: >20% empty answers
MAX_TEXT = 3000           # characters of a statement sent to the model (and verified against)
MAX_CONTEXT = 1500        # characters of the 2 preceding statements + question

# Stage 2a sources.  `doc`/`doc_page` are read-only store tables; a page whose text is empty in the main DB is
# read from `<store>_ocr.db.ocr_page` (the OCR run writes there, never into the store).
DOC_TYPES = ("annual_report", "press_release", "announcement")
PARA_CHARS = 700          # a document paragraph is packed to about this many characters
MAX_QUOTE = 160           # characters of context kept on each side of a script-parsed number

NODES = (
    "revenue.volume", "revenue.price", "revenue.total", "revenue.order_book", "revenue.mix",
    "cost.raw_material", "cost.employee", "cost.power_fuel", "cost.other",
    "margin.ebitda", "margin.gross",
    "capex.amount", "capacity.add",
    "debt.level", "debt.cost",
    "equity.shares", "equity.dividend",
    "working_capital.days",
)
JUDGE_FIELDS = ("node_ok", "sign_ok", "unit_ok", "period_ok", "forward_ok", "company_ok")

# Node/unit compatibility: a node may not carry a unit it cannot mean.  capacity.add is a size, not a
# waiting time; working_capital.days is days; margin is a rate; debt.cost is a rate or a finance-cost
# amount (the tree says "interest rate, finance cost").  "named" = any unit outside the canonical table
# (spindles, bales, sft, orders...), which is allowed where a physical quantity makes sense.
_MONEY_UNITS = ("inr", "inr_cr", "inr_lakh", "usd", "usd_mn", "mn")
NODE_UNITS: dict[str, set[str]] = {
    "revenue.volume": {"pct", "mw", "tonnes", "mt", "units", "named"},
    "revenue.price": {*_MONEY_UNITS, "pct"},
    "revenue.total": {*_MONEY_UNITS, "pct"},
    "revenue.order_book": {*_MONEY_UNITS, "months"},
    "revenue.mix": {*_MONEY_UNITS, "pct"},
    "cost.raw_material": {*_MONEY_UNITS, "pct"},
    "cost.employee": {*_MONEY_UNITS, "pct"},
    "cost.power_fuel": {*_MONEY_UNITS, "pct"},
    "cost.other": {*_MONEY_UNITS, "pct"},
    "margin.ebitda": {"pct", "bp"},
    "margin.gross": {"pct", "bp"},
    "capex.amount": {*_MONEY_UNITS},
    "capacity.add": {"pct", "mw", "tonnes", "mt", "units", "named"},
    "debt.level": {*_MONEY_UNITS},
    "debt.cost": {"pct", "bp", *_MONEY_UNITS},
    "equity.shares": {"pct", *_MONEY_UNITS, "units", "named"},
    "equity.dividend": {"pct", "inr", "inr_cr", "inr_lakh"},
    "working_capital.days": {"days"},
}

# A script-built company brief (no model): name, inferred sector, what it sells and what it buys, from the
# company's own text.  What makes an input price a cost rather than revenue (Wolf, round 3: SPORTKING's
# cotton candy price is an input, not the company's selling price).
RAW_MATERIALS: dict[str, str] = {
    "cotton": r"\bcotton\b", "yarn": r"\byarn\b", "polyester": r"\bpolyester\b|\bpsf\b",
    "viscose": r"\bviscose\b", "acrylic": r"\bacrylic\b", "wool": r"\bwool\b",
    "caustic soda": r"\bcaustic soda\b|\bcaustic\b", "chlorine": r"\bchlorine\b",
    "benzene": r"\bbenzene\b", "toluene": r"\btoluene\b", "methanol": r"\bmethanol\b",
    "acid": r"\bacids?\b|\bacidity\b", "sulphur": r"\bsulphurs?\b|\bsulfurs?\b|\bsulphuric\b",
    "ammonia": r"\bammonia\b", "urea": r"\burea\b", "coal": r"\bcoal\b", "coke": r"\bcoke\b",
    "crude": r"\bcrude\b", "natural gas": r"\bnatural gas\b|\blng\b", "power": r"\bpower\b|\belectricity\b",
    "steel": r"\bsteel\b", "iron ore": r"\biron ore\b", "aluminium": r"\baluminium\b|\baluminum\b",
    "copper": r"\bcopper\b", "zinc": r"\bzinc\b", "pulp": r"\bpulp\b", "timber": r"\btimber\b|\bwood\b",
    "palm oil": r"\bpalm oil\b|\bedible oil\b", "wheat": r"\bwheat\b", "sugar": r"\bsugar\b|\bsugarcane\b",
    "molasses": r"\bmolasses\b", "milk": r"\bmilk\b", "maize": r"\bmaize\b|\bcorn\b",
    "soybean": r"\bsoy\w*\b", "rice": r"\brice\b|\bpaddy\b", "clinker": r"\bclinker\b",
    "limestone": r"\blimestone\b", "rubber": r"\brubber\b", "resin": r"\bresin\b",
    "solvent": r"\bsolvents?\b", "gold": r"\bgold\b", "silver": r"\bsilver\b",
    "diamond": r"\bdiamonds?\b", "glass": r"\bglass\b",
}
PRODUCTS: dict[str, str] = {
    "cotton yarn": r"\bcotton yarn\b|\byarn\b", "fabric and knitwear": r"\bfabric\b|\bknitwear\b|\bknitted\b|\bdenim\b",
    "caustic soda": r"\bcaustic soda\b|\bcaustic\b", "chlorine": r"\bchlorine\b",
    "chlorinated products": r"\bTCCA\b|\bchlorinated\b", "benzene derivatives": r"\bbenzene\b",
    "hydrogen peroxide": r"\bhydrogen peroxide\b|\bH2O2\b", "refractories": r"\brefractor\w+\b",
    "power": r"\bsolar\b|\bwind\b|\bmegawatt\b|\bmw\b",
    "sugar": r"\bsugar\b", "cement": r"\bcement\b", "steel": r"\bsteel\b",
    "paints": r"\bpaints?\b", "jewellery": r"\bjewell?ery\b",
    "pharmaceuticals": r"\bpharmaceutical\w+\b|\bformulations?\b",
    "granite and quartz": r"\bgranite\b|\bquartz\b|\bstone\b",
    "chemicals": r"\bchemicals?\b|\bspecialty\b", "textiles": r"\btextiles?\b",
}
SECTORS: dict[str, tuple[str, ...]] = {
    "textiles": ("cotton", "yarn", "polyester", "viscose", "fabric and knitwear", "textiles"),
    "chemicals": ("caustic soda", "chlorine", "benzene", "acid", "sulphur", "hydrogen peroxide",
                  "chlorinated products", "chemicals"),
    "power and renewables": ("power", "crude", "natural gas"),
    "metals and mining": ("steel", "iron ore", "aluminium", "copper", "zinc"),
    "pharmaceuticals": ("pharmaceuticals", "solvent"),
    "food and agri": ("sugar", "palm oil", "wheat", "milk", "maize", "soybean", "rice", "molasses"),
    "cement": ("cement", "clinker", "limestone"),
    "packaging and paper": ("pulp", "timber", "resin"),
    "jewellery": ("gold", "silver", "diamond", "jewellery"),
    "paints": ("paints", "resin", "solvent"),
    "granite and stone": ("granite and quartz", "resin"),
}

# guidance metric -> (node, segment).  Only metrics that unambiguously name a node are mapped; anything
# else (``other``, ``project_capital_spent``) goes to the model, which can read the quote and decide.
GUIDANCE_MAP: dict[str, tuple[str, str]] = {
    "revenue_growth": ("revenue.total", "total"),
    "ebitda_margin": ("margin.ebitda", "total"),
    "capex": ("capex.amount", "total"),
    "order_intake": ("revenue.order_book", "total"),
    "aum_growth": ("revenue.volume", "aum"),
    "nim": ("margin.ebitda", "net_interest_margin"),
    "credit_cost": ("cost.other", "credit_cost"),
    "cost_of_production": ("cost.other", "cost_of_production"),
    "opex_to_nti": ("cost.other", "opex"),
    "interest_cost": ("debt.cost", "total"),
}

# Forward-looking cue words.  Loose on purpose: the model classifies a past-tense statement as ``past``;
# this filter only keeps the run from paying for the bulk of the transcript that has no future in it.
CUE = re.compile(
    r"\b(?:expect(?:s|ed|ing)?|will|would|should|intend(?:s|ed|ing)?|plan(?:s|ned|ning)?|aim(?:s|ing)?"
    r"|anticipat\w+|outlook|guidance|guid(?:e|ed|ing)|target(?:s|ed|ing)?|going forward"
    r"|next (?:year|quarter|fiscal|two|three)|FY2[6-9]|H[12]\s?FY2[6-9]|Q[1-4]\s?FY2[6-9]"
    r"|commission\w*|capacity|expand\w*|growth|increas\w+|moderat\w+|steady.state)\b",
    re.I,
)

# A forward horizon: what lets a claim stand when the model left ``effective_period`` empty.
HORIZON = re.compile(
    r"\b(?:next|coming|going forward|forward|near[\s-]term|medium[\s-]term|long[\s-]term"
    r"|annual(?:ly)?|per annum|this (?:year|quarter|fiscal)|full year|steady[\s-]state"
    r"|once (?:fully )?(?:operational|commissioned)|by (?:the )?(?:year[\s-]end|end of)"
    r"|FY\s?2[5-9]|H[12]\s?FY2[5-9]|Q[1-4]\s?FY2[5-9]|months?|quarters?|years?)\b",
    re.I,
)

# "10%-15% plus or minus" is a range around an unknown base: not a signed claim.  Wolf, 21 Nov.
AMBIG_SIGN = re.compile(r"plus\s*or\s*minus|\+/-|±", re.I)

# Stage 2a: the brief's document cue list (expect, target, plan, will, guidance, outlook, order, awarded,
# commission, approve, capex, capacity, raise, allot).  It is deliberately NOT the transcript CUE: a results
# table says "increase/(decrease)" and "growth" on every line, which is a past number, not a forward cue.
DOC_CUE = re.compile(
    r"\b(?:expect(?:s|ed|ing)?|target(?:s|ed|ing)?|plan(?:s|ned|ning)?|will|guidance|guid(?:e|ed|ing)"
    r"|outlook|order(?:s|ed|ing)?|award(?:s|ed|ing)?|commission(?:s|ed|ing)?|approv\w+|capex"
    r"|capital expenditure|capacity|raise|raising|allot\w*|intend(?:s|ed|ing)?|aim(?:s|ing)?"
    r"|going forward)\b",
    re.I,
)

# A number a claim can be built on: a currency amount, a per cent, or a named physical unit.
DOC_NUMBER = re.compile(
    r"(?<![A-Za-z])(?:Rs\.?|INR|₹|\$|USD)\s*\d[\d,]*(?:\.\d+)?"
    r"|\d[\d,]*(?:\.\d+)?\s*(?:%|per\s?cent|percent|crores?|cr\.?|lakhs?|million|mn|billion|bn|bps?"
    r"|basis points?|tonnes?|tons?|mt|mw|gw|gwh|mwh|kw|units?|kl|tpa|tpd|acres?|sq\.?\s?ft|sft|shares?)",
    re.I,
)

# Section boilerplate an annual report repeats (CSR, BRSR, risk/governance lists, director bios).  The cue
# filter would keep some of it (a CSR paragraph says "will spend Rs X crore"); this drops the paragraph and
# counts the drop.
BOILERPLATE = re.compile(
    r"corporate social responsibility|\bCSR\b|business responsibility and sustainability|\bBRSR\b"
    r"|principle\s+\d+\s*:?\s*businesses should|familiarisation programme|familiarization programme"
    r"|secretarial audit|secretarial standards|annual return|dividend distribution policy"
    r"|whistle ?blower|vigil mechanism|nomination and remuneration|stakeholder relationship"
    r"|material subsidiary|related party transaction|risk management committee|internal financial control"
    r"|code of conduct|code of ethics|listing fees|registrar and share transfer agent|board diversity",
    re.I,
)

# A sentence boundary is a full stop followed by a capital: "Rs. 215" and "No. 5" are not sentence ends.
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")

# Filings the store puts under `announcement` that are not an announcement of a driver event: an annual report
# or AGM notice re-filed, an offering document, a voting/scrutinizer report, a BRSR, a creditor list.  Their
# annual-report content is read from the `annual_report` doc type instead (one copy, no double counting).
FILING_SKIP = re.compile(
    r"annual report|annual general meeting|extra[-\s]?ordinary general meeting|postal ballot"
    r"|letter of offer|prospectus|placement document|information memorandum"
    r"|business responsibility|\bBRSR\b|voting result|scrutinizer|list of creditors"
    r"|shareholding pattern|reconciliation of share capital|compliance certificate|certificate under"
    r"|newspaper publication|share certificate|transmission of shares|demateriali[sz]ation",
    re.I,
)


# Announcement script parse (deterministic).  The three shapes exchanges print in full, with the value word
# the letter uses; anything the parser cannot fill completely falls through to the model.
_ORDER_WORD = re.compile(r"\b(?:orders?|work orders?|contracts?|LOA|LOI|letter of award)\b", re.I)
_ORDER_AWARD = re.compile(r"\b(?:secured|awarded|bagged|won|received|receipt of)\b", re.I)
# A GST demand, a penalty, a court order or a notice is an "order" in the same word and is not revenue.
_ORDER_BAD = re.compile(
    r"\b(?:demand|penalty|fine|fines|gst|goods and services tax|customs|excise|income tax|tribunal|court"
    r"|appeal|show[\s-]cause|notice|insolvency|nclt|arbitration)\b", re.I)
_ORDER_VALUE = re.compile(
    r"(?:orders?|work orders?|contracts?|LOA|LOI)[^.;]{0,120}?"
    r"(?:worth|valued(?:\s+at)?|value|amounting\s+to|aggregating\s+to|of)\s*"
    r"(?:Rs\.?|INR|₹)\s*(?P<v>[\d,]+(?:\.\d+)?)\s*(?P<u>crores?|cr\.?|lakhs?|million|mn|billion|bn)",
    re.I,
)
_EXECUTION_PERIOD = re.compile(
    r"(?:execut\w*|complet\w*|completion|time period|period of|duration of|within|delivery|delivered)"
    r"[^.;]{0,60}?(?P<n>\d{1,2})\s*(?P<u>months?|years?)", re.I)
_CAPEX_WORD = re.compile(r"\b(?:capital expenditure|capex)\b", re.I)
_CAPEX_APPROVE = re.compile(r"\b(?:approved|approves|approval|sanctioned|sanction)\b", re.I)
_CAPEX_FROM_TO = re.compile(
    r"(?:capital expenditure|capex)[^.;]{0,120}?from\s*(?:Rs\.?|INR|₹)?\s*(?P<a>[\d,]+(?:\.\d+)?)\s*"
    r"(?P<au>crores?|cr\.?|lakhs?|million|mn)[^.;]{0,40}?to\s*(?:Rs\.?|INR|₹)?\s*"
    r"(?P<b>[\d,]+(?:\.\d+)?)\s*(?P<bu>crores?|cr\.?|lakhs?|million|mn)", re.I)
_CAPEX_AMOUNT = re.compile(
    r"(?:approved|approves|approval of|sanctioned|capital expenditure|capex)[^.;]{0,100}?"
    r"(?:Rs\.?|INR|₹)\s*(?P<v>[\d,]+(?:\.\d+)?)\s*(?P<u>crores?|cr\.?|lakhs?|million|mn|billion|bn)", re.I)
_RAISE_CUE = re.compile(
    r"\b(?:QIP|qualified institutions? placement|rights issue|preferential (?:issue|allotment)|warrants?"
    r"|equity shares)\b", re.I)
# A completed allotment is a past event: only a proposed or approved raise is a forward claim.  "for conversion
# of loan" is consideration, not a completed share conversion, so it is not in this list.
_RAISE_DONE = re.compile(
    r"\b(?:allotted|allotment of|converted into|conversion of warrants?|exercised|exercise of rights"
    r"|forfeited|subscribed)\b", re.I)
_RAISE_SIZE = re.compile(
    r"(?:aggregat\w*|amount\w*|raising|raise|up\s*to|upto|of)(?:\s+up\s*to)?\s*(?:Rs\.?|INR|₹)\s*"
    r"(?P<v>[\d,]+(?:\.\d+)?)\s*(?P<u>crores?|cr\.?|lakhs?|million|mn|billion|bn)", re.I)
_RAISE_PRICE = re.compile(
    r"(?:issue price|price of|at\s+an?\s+price\s+of|at\s+price\s+of)\s*(?:Rs\.?|INR|₹)\s*"
    r"(?P<v>[\d,]+(?:\.\d+)?)\s*(?:/-)?\s*(?:per|each)", re.I)
# "come down from INR450 crores to INR100 crores": a target B with base A, not a range.  A plain
# "INR 2,700 to 2,800 crores" (an aspiration/range, no from, no change verb) stays a range.  Wolf, round 4.
_PRICE_PREFIX = r"(?:INR|Rs\.?|₹|\$|USD)?\s*"
_UNIT_AFTER = r"(?P<aunit>\s*(?:%|percent|bp|bps|crores?|cr|lakhs?|million|mn|bn)?)"
_FROM_TO_RE = re.compile(
    r"\bfrom\s+(?P<a>" + _PRICE_PREFIX + r"\d[\d,]*(?:\.\d+)?)" + _UNIT_AFTER + r"\s+"
    r"(?:down\s+|up\s+)?to\s+(?P<b>" + _PRICE_PREFIX + r"\d[\d,]*(?:\.\d+)?)", re.I)
_A_TO_B_RE = re.compile(
    r"(?<!\d)(?P<a>" + _PRICE_PREFIX + r"\d[\d,]*(?:\.\d+)?)" + _UNIT_AFTER + r"\s+to\s+"
    r"(?P<b>" + _PRICE_PREFIX + r"\d[\d,]*(?:\.\d+)?)", re.I)
CHANGE_VERB = re.compile(
    r"\b(?:cut|cuts|reduc\w*|declin\w*|fall\w*|drop\w*|decreas\w*|come down|comes down|coming down|go down"
    r"|bring\w* down|increase\w*|rise|rises|rising|grow\w*|expand\w*|go up|improv\w*|target\w*|reach\w*"
    r"|touch\w*|moderat\w*|down to|up to|higher|lower)\b", re.I)


def _plain_number(token: str) -> float:
    return float(re.sub(r"[^\d.]", "", token))


def _claim_text(claim: dict[str, Any]) -> str:
    """The quote, its statement and the paragraph around it: where a scope word or a GST basis may live."""
    return " ".join(norm_ws(claim.get(key)) for key in ("quote_span", "statement", "context"))


def gst_basis(claim: dict[str, Any]) -> str | None:
    """The printed GST basis ("including GST" / "excluding GST"), else None."""
    match = GST_BASIS.search(_claim_text(claim))
    if match is None:
        return None
    phrase = norm_ws(match.group(0)).lower()
    return "excluding GST" if phrase.startswith(("excluding", "exclusive", "plus", "net")) else "including GST"


def _fill_gst_base(claim: dict[str, Any]) -> None:
    basis = gst_basis(claim)
    if basis is None:
        return
    base = norm_ws(claim.get("base"))
    if not base:
        claim["base"] = basis
    elif "gst" not in base.lower():
        claim["base"] = f"{base}; {basis}"


def scope_flagged(claim: dict[str, Any]) -> bool:
    """A level claim on the whole company whose own paragraph names a unit, plant, product or new line.

    The script cannot decide which unit the model meant, so such a claim is only verified when the judge
    confirms it with ``scope_ok`` (``apply_judge``); otherwise it stays unverified (``judge:scope_ok``).
    """
    node = norm_ws(claim.get("node")).lower()
    if node not in ("revenue.total", "revenue.volume"):
        return False
    if norm_ws(claim.get("segment")).lower() not in ("", "total"):
        return False
    if norm_ws(claim.get("sign")) != "0":
        return False
    text = _claim_text(claim)
    return bool(SCOPE_WORD.search(text) or INCREMENT_WORD.search(text))


def speaker_scope(statement: Any, context: Any = "") -> str:
    """company / rating_agency: a rating rationale page carries a third party's estimate, not the company's."""
    text = f"{norm_ws(statement)} {norm_ws(context)}"
    if RATING_AGENCY.search(text) and RATING_ESTIMATE.search(text):
        return "rating_agency"
    return "company"


def sign_from_verbs(claim: dict[str, Any]) -> None:
    """Fill sign 0 from the node and the verbs: debt repaid is -, a declared dividend is +."""
    if norm_ws(claim.get("sign")) != "0":
        return
    node = norm_ws(claim.get("node")).lower()
    text = _claim_text(claim)
    if node == "debt.level":
        if REPAY_VERB.search(text):
            claim["sign"] = "-"
        elif BORROW_VERB.search(text):
            claim["sign"] = "+"
    elif node == "equity.dividend" and DIVIDEND_VERB.search(text):
        claim["sign"] = "+"


# "at least 20% to 25%" / "up 20%-25%" / "20% to 25%" is a range: both printed ends belong in the claim.
# A "from A to B" statement stays a target (from_to_target).  Wolf, stage 2b (1342).
_AT_LEAST_RANGE = re.compile(r"\b(?:at\s+least|at\s+most|between)\s*$", re.I)
_BY_CHANGE = re.compile(
    r"\b(?:increas\w*|grow\w*|ris(?:e|es|ing)|up|higher|decreas\w*|declin\w*|f(?:a|e)ll\w*|drop\w*"
    r"|reduc\w*|lower|down)\b[^.;]{0,25}?\bby\s*$", re.I)
_NEG_CHANGE = re.compile(r"\b(?:decreas\w*|declin\w*|f(?:a|e)ll\w*|drop\w*|reduc\w*|lower|down|cut\w*)\b", re.I)
_POS_CHANGE = re.compile(r"\b(?:increas\w*|grow\w*|ris(?:e|es|ing)|up|higher|expand\w*|improv\w*)\b",
                         re.I)


def range_from_span(claim: dict[str, Any]) -> bool:
    """Keep both ends of a printed range where the model collapsed it to one.  True when it rewrote."""
    span = norm_ws(claim.get("quote_span"))
    if not span or _FROM_TO_RE.search(span):
        return False
    match = _A_TO_B_RE.search(span)
    if match is None:
        return False
    before = span[max(0, match.start() - 40):match.start()]
    percent_pair = bool(re.search(r"%|percent|per\s?cent", match.group("aunit") or "", re.I))
    if not (percent_pair or _AT_LEAST_RANGE.search(before) or _BY_CHANGE.search(before)):
        return False
    try:
        a = _plain_number(match.group("a"))
        b = _plain_number(match.group("b"))
    except ValueError:
        return False
    if a == b:
        return False
    claim["value_low"], claim["value_high"] = min(a, b), max(a, b)
    polarity = "-" if _NEG_CHANGE.search(before or span) else ("+" if _POS_CHANGE.search(span) else "0")
    if polarity != "0":
        claim["sign"] = polarity
    base = norm_ws(claim.get("base"))
    if not base or any(re.search(rf"(?<!\d){re.escape(token.strip())}(?!\d)", base) for token in
                       (match.group("a"), match.group("b"))):
        claim["base"] = None
    return True


def from_to_target(claim: dict[str, Any]) -> bool:
    """Rewrite a change statement 'from A to B' to target B (sign by B-A, base A).  True when it did."""
    span = str(claim.get("quote_span") or "")
    match = _FROM_TO_RE.search(span)
    if match is None:
        alt = _A_TO_B_RE.search(span)
        if alt is None or not CHANGE_VERB.search(span):
            return False
        match = alt
    assert match is not None
    try:
        a = _plain_number(match.group("a"))
        b = _plain_number(match.group("b"))
    except ValueError:
        return False
    if a == b:
        return False
    claim["value_low"] = b
    claim["value_high"] = b
    claim["base"] = norm_ws(f"{match.group('a')}{match.group('aunit')}")
    claim["sign"] = "+" if b > a else "-"
    return True


# A share, mix or contribution is its own node (Wolf, round 5), but only when the number's own clause really
# is a share: a margin clause ("EBIT margin of 30%-35%") and a change clause ("25% better", "20% growth")
# are not, unless the clause itself says "% of ..." or "share of".  Wolf, round 6.
MIX_TRIGGER = re.compile(
    r"\bcontribut\w*|\bshare\s+of\b|\bmix\b|%\s*of\s+(?:the\s+)?(?:total|revenue|income|sales|turnover)",
    re.I)
STRONG_SHARE = re.compile(
    r"%\s*of\s+(?:the\s+)?(?:total|revenue|income|sales|turnover)|\bshare\s+of\b", re.I)
MARGIN_WORD = re.compile(r"\b(?:margins?|EBIT|EBITDA|PAT|gross)\b", re.I)
CHANGE_WORD = re.compile(r"\b(?:better|growth|grow|grows|growing|increases?|increased|increasing|higher|up)\b",
                         re.I)
MIX_SEGMENTS = ("exports", "export", "domestic", "imports", "retail", "wholesale", "institutional")

# Stage 2b scope words: a level claim whose paragraph names one of these is a unit/plant/product increment,
# not a company-wide level.  Wolf's hand read, 21 Nov: 577 (new unit's Rs 250 crore), 573 (new unit's ramp),
# 1130/735 (greenfield spindle utilisation), 437 (new product line).
SCOPE_WORD = re.compile(
    r"\b(?:plants?|units?|production\s+lines?|assembly\s+lines?|new\s+lines?|lines?\s+of\s+business"
    r"|facilit(?:y|ies)|factor(?:y|ies)|mills?|works|subsidiar(?:y|ies)|greenfield|brownfield"
    r"|verticals?|divisions?|solar\s+park|speciali[sz]ed\s+unit|products?)\b", re.I)
# An increment phrased without naming the unit ("the full impact", "additional revenue").
INCREMENT_WORD = re.compile(
    r"\b(?:full\s+impact|incremental|additional|ramp(?:[\s-]?up)?|new\s+capacity|start(?:s|ing)?\s+coming)\b",
    re.I)

# GST basis: an order value in an exchange letter is sometimes incl. GST and sometimes excl., so the phrase
# belongs in `base` (Wolf: 247 "Rs. 117.74 Crores including GST" while other orders are ex-GST).
GST_BASIS = re.compile(
    r"\b(?:including|inclusive\s+of|excluding|exclusive\s+of|plus|net\s+of)\s+(?:applicable\s+)?GST\b", re.I)

# Rating-agency rationales are a third party's estimate, never the company's own claim (Wolf: 982, 1126).
RATING_AGENCY = re.compile(
    r"\b(?:CRISIL|ICRA|CARE\s+(?:Ratings|Ltd|Limited)|India\s+Ratings|Acuit[eé]|Brickwork|Infomerics"
    r"|SMERA|BWR)\b", re.I)
RATING_ESTIMATE = re.compile(
    r"\b(?:estimat\w*|expect\w*|forecast\w*|project\w*|outlook|rating\w*|rationale)\b", re.I)

# Sign from the node and its verbs (Wolf: 522 OTS repayment sign 0; dividends sign 0).
REPAY_VERB = re.compile(
    r"\b(?:pay(?:s|ing|ment)?|repay\w*|prepay\w*|settle\w*|settlement|clear\w*|retire\w*"
    r"|reduc\w*|reduction|discharg\w*)\b", re.I)
BORROW_VERB = re.compile(
    r"\b(?:raise\s+(?:debt|funds|money)|draw(?:n|ing)?\s+down|avail\w*|additional\s+borrowing"
    r"|increase\s+(?:in\s+)?(?:debt|borrowings?))\b", re.I)
DIVIDEND_VERB = re.compile(r"\b(?:declar\w*|recommend\w*|approv\w*|propos\w*|payable|paid)\b", re.I)



def number_clause(claim: dict[str, Any]) -> str:
    """Every sentence/clause the claim's quote_span touches (the number's own clauses)."""
    statement = norm_ws(claim.get("statement"))
    span = norm_ws(claim.get("quote_span"))
    position = statement.find(span) if span else -1
    if position < 0:
        return span
    end = position + len(span)
    parts = [match.group(0).strip() for match in re.finditer(r"[^.;,]+", statement)
             if match.start() < end and match.end() > position]
    return " ".join(part for part in parts if part)


def mix_segment(text: str) -> str | None:
    for word in MIX_SEGMENTS:
        if re.search(rf"\b{word}\b", text, re.I):
            return word
    for term, pattern in PRODUCTS.items():
        if re.search(pattern, text, re.I):
            return term
    return None


def mix_should_fire(claim: dict[str, Any]) -> bool:
    """A pct claim with a share/mix/% of trigger whose own clause is not a margin or a change."""
    if canon_unit(claim.get("unit")) != "pct":
        return False
    text = f"{claim.get('quote_span') or ''} {claim.get('statement') or ''}"
    if not MIX_TRIGGER.search(text):
        return False
    clause = number_clause(claim)
    if STRONG_SHARE.search(clause):
        return True
    return not (MARGIN_WORD.search(clause) or CHANGE_WORD.search(clause))


def mix_node(claim: dict[str, Any]) -> bool:
    """A pct share/mix/contribution belongs on revenue.mix with the segment named.  True when moved."""
    if claim.get("node") == "revenue.mix" or not mix_should_fire(claim):
        return False
    claim["node"] = "revenue.mix"
    if norm_ws(claim.get("segment")).lower() in ("", "total"):
        segment = mix_segment(f"{claim.get('quote_span') or ''} {claim.get('statement') or ''}")
        if segment:
            claim["segment"] = segment
    return True


# A list read as one value (Wolf, round 5): "8%, 10% increase" must not become 8-8.
_LIST_SEPARATOR = re.compile(
    r"^\s*(?:(?:,|;|to|or|and|-|–|—|%|percent|bps?|basis points?|rupees?|rs\.?|inr|crores?|cr|lakhs?"
    r"|million|mn|bn|billion|usd|\$)\s*)+$", re.I)


def _numbers_with_cues(text: str, unit: str) -> list[tuple[int, int, float]]:
    clean = _PERIOD_RE.sub(" ", text)
    cues = UNIT_CUES.get(canon_unit(unit))
    out: list[tuple[int, int, float]] = []
    for match in _NUM_RE.finditer(clean):
        try:
            value = float(match.group(1).replace(",", ""))
        except ValueError:
            continue
        if cues is not None:
            window = clean[max(0, match.start() - 12): match.end() + 12]
            if not any(re.search(cue, window, re.I) for cue in cues):
                continue
        out.append((match.start(), match.end(), value))
    return out


def range_truncated(claim: dict[str, Any]) -> bool:
    """True when the span lists 2+ numbers of the claim's unit and the claim does not span them."""
    span = str(claim.get("quote_span") or "")
    numbers = _numbers_with_cues(span, str(claim.get("unit") or ""))
    if len(numbers) < 2:
        return False
    clean = _PERIOD_RE.sub(" ", span)
    joined: list[float] = []
    for (_, end1, value1), (start2, _, value2) in zip(numbers, numbers[1:]):
        if _LIST_SEPARATOR.match(clean[end1:start2]):
            joined.extend((value1, value2))
    if len(set(joined)) < 2:
        return False
    low, high = claim.get("value_low"), claim.get("value_high")
    if low is None:
        return False
    high = low if high is None else high
    return not (float(low) <= min(joined) and float(high) >= max(joined))

# Period labels (FY26, Q2FY26, H1FY26, 9MFY26, CY2024) are stripped before numbers are read, so a claim
# value of 26 cannot be satisfied by the "26" in "FY26".  Everything else is left alone: a digit glued to
# its unit or currency ("INR40", "1.25x", "20%") is a number and must be readable.
_PERIOD_RE = re.compile(
    r"\b(?:[QH]\s?\d{1,2}(?:\s?FY\s?['’]?\d{2,4})?|FY\s?['’]?\d{2,4}|\d{1,2}M(?:\s?FY\s?['’]?\d{2,4})?"
    r"|CY\s?['’]?\d{2,4}|TTM)\b",
    re.I,
)
_NUM_RE = re.compile(r"(?<![\d,])(\d[\d,]*(?:\.\d+)?)")

_UNIT_ALIASES = {
    "%": "pct", "percent": "pct", "per cent": "pct", "percentage": "pct",
    "bps": "bp", "basis point": "bp", "basis points": "bp", "b.p.": "bp",
    "rs crore": "inr_cr", "rs. crore": "inr_cr", "rs cr": "inr_cr", "inr crore": "inr_cr",
    "inr cr": "inr_cr", "crore": "inr_cr", "cr": "inr_cr", "₹ crore": "inr_cr", "crores": "inr_cr",
    "rs lakh": "inr_lakh", "rs. lakh": "inr_lakh", "lakh": "inr_lakh", "lakhs": "inr_lakh",
    "rs": "inr", "rs.": "inr", "₹": "inr", "rupees": "inr", "rupee": "inr",
    "month": "months", "month(s)": "months", "day": "days", "year": "years",
}

# The unit word that must be present in the quote for the claim's unit.  A scaled or period unit without
# its word is a unit mismatch: "30 days" answered in months fails, "Rs 240" answered in crore fails.
UNIT_CUES: dict[str, tuple[str, ...]] = {
    "days": (r"\bdays?\b",),
    "months": (r"\bmonths?\b",),
    "years": (r"\byears?\b",),
    "pct": (r"%", r"\bper\s?cent\b", r"\bpercent\b"),
    "bp": (r"\bbps?\b", r"\bbasis points?\b"),
    "inr_cr": (r"\bcrores?\b", r"\bcr\.?\b"),
    "inr_lakh": (r"\blakhs?\b",),
    "inr": (r"\brs\.?", r"₹", r"\binr", r"\brupees?\b"),
    "usd": (r"\busd\b", r"\$", r"\bdollars?\b"),
    "usd_mn": (r"\bmillion\b", r"\bmn\b"),
    "mn": (r"\bmillion\b", r"\bmn\b"),
    "mw": (r"\bmw\b", r"\bmegawatts?\b"),
    "tonnes": (r"\btonnes?\b", r"\btons?\b", r"\bmt\b"),
    "mt": (r"\btonnes?\b", r"\btons?\b", r"\bmt\b"),
    "units": (r"\bunits?\b",),
}

IST = timezone(timedelta(hours=5, minutes=30))


# ------------------------------------------------------------------ text + number normaliser
def norm_ws(text: Any) -> str:
    """Collapse every whitespace run to one space: PDF line-wrapping is not part of the quote."""
    return " ".join(str(text or "").split())


def canon_unit(unit: Any) -> str:
    u = norm_ws(unit).lower()
    return _UNIT_ALIASES.get(u, u)


def find_numbers(text: str) -> list[float]:
    """Every number printed in ``text``, after period labels and Indian/western digit grouping are handled."""
    out: list[float] = []
    for raw in _NUM_RE.findall(_PERIOD_RE.sub(" ", text or "")):
        try:
            out.append(float(raw.replace(",", "")))
        except ValueError:
            continue
    return out


def matches_value(value: float, numbers: list[float], unit: str) -> bool:
    """Is ``value`` one of the printed numbers?  A pct claim may be written 0.2 for 20%."""
    candidates = [value]
    if canon_unit(unit) == "pct":
        candidates.append(value * 100.0)
    for cand in candidates:
        for n in numbers:
            if math.isclose(cand, n, rel_tol=1e-9, abs_tol=1e-9):
                return True
    return False


def sign_of(direction: Any) -> str:
    d = norm_ws(direction).lower()
    if d in ("up", "increase", "positive", "+", "higher"):
        return "+"
    if d in ("down", "decrease", "negative", "-", "lower"):
        return "-"
    return "0"


def _num(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = norm_ws(value).replace(",", "").replace("₹", "").replace("Rs.", "").replace("Rs", "")
    m = re.search(r"-?\d+(?:\.\d+)?", s)
    return float(m.group(0)) if m else None


def _clean(value: Any, limit: int) -> str | None:
    if value is None:
        return None
    s = norm_ws(value)
    return s[:limit] or None


# ------------------------------------------------------------------ the checks
def unit_agrees(claim: dict[str, Any]) -> tuple[bool, str]:
    """The unit word printed next to the number must agree with the claim's unit."""
    unit = canon_unit(claim.get("unit"))
    span = claim.get("quote_span") or ""
    cues = UNIT_CUES.get(unit)
    if cues is None:                      # a named unit (kl, tpa, orders...): its own word must appear
        token = re.sub(r"[^a-z]", "", unit)
        if len(token) >= 3 and not re.search(rf"\b{re.escape(token)}", span, re.I):
            return False, "unit_mismatch"
        return True, ""
    if any(re.search(cue, span, re.I) for cue in cues):
        return True, ""
    return False, "unit_mismatch"


def unit_allowed(node: Any, unit: Any) -> bool:
    """Can this node carry this unit at all?  (capacity.add * months* is a timing, not a capacity.)"""
    allowed = NODE_UNITS.get(str(node or ""))
    if allowed is None:
        return True
    u = canon_unit(unit)
    if u in allowed:
        return True
    return "named" in allowed and u not in UNIT_CUES


def has_period(claim: dict[str, Any]) -> bool:
    """A verified claim needs an effective period, or a forward horizon printed in its own quote."""
    if norm_ws(claim.get("effective_period")):
        return True
    return bool(HORIZON.search(claim.get("quote_span") or ""))


def verify_claim(claim: dict[str, Any]) -> tuple[str, str]:
    """Script check: verified / unverified / quarantined, with the reason; forces sign 0 on an ambiguous range."""
    span = norm_ws(claim.get("quote_span"))
    if not span:
        return "quarantined", "no_quote_span"
    _fill_gst_base(claim)
    sign_from_verbs(claim)
    if AMBIG_SIGN.search(span):
        claim["sign"] = "0"
    rewritten = range_from_span(claim)
    if not rewritten:
        rewritten = from_to_target(claim)
    if rewritten:
        span = norm_ws(claim.get("quote_span"))
    if span not in norm_ws(claim.get("statement")):
        return "quarantined", "quote_span_not_in_statement"
    if norm_ws(claim.get("speaker_scope")) == "rating_agency":
        return "unverified", "third_party"
    numbers = find_numbers(span)
    low, high = claim.get("value_low"), claim.get("value_high")
    if low is None and high is None:
        return "unverified", "no_value"
    if low is not None and not matches_value(float(low), numbers, claim.get("unit") or ""):
        return "unverified", "value_low_not_in_quote"
    if high is not None and not matches_value(float(high), numbers, claim.get("unit") or ""):
        return "unverified", "value_high_not_in_quote"
    mix_node(claim)
    if not rewritten and range_truncated(claim):
        return "unverified", "range_truncated"
    ok, reason = unit_agrees(claim)
    if not ok:
        return "unverified", reason
    if not unit_allowed(claim.get("node"), claim.get("unit")):
        return "unverified", "unit_not_for_node"
    if not has_period(claim):
        return "unverified", "no_period"
    return "verified", ""


def _finish(claim: dict[str, Any]) -> dict[str, Any]:
    claim["status"], claim["status_reason"] = verify_claim(claim)
    claim["created_at"] = utc_now()
    claim["conditional"] = 1 if claim.get("conditional") else 0
    claim["judge_ok"] = None
    return claim


# ------------------------------------------------------------------ time
def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def ist_now() -> str:
    return datetime.now(IST).isoformat(timespec="seconds")


# ------------------------------------------------------------------ stores (read-only)
def store_path(store: str) -> Path:
    return STORE_ROOT / store / f"{store}.db"


def list_stores() -> list[str]:
    return sorted(p.name for p in STORE_ROOT.glob("c*") if (p / f"{p.name}.db").exists())


def _row_dict(row: Any, columns: list[str]) -> dict[str, Any]:
    return {c: row[c] for c in columns}


def open_store(store: str) -> sqlite3.Connection:
    from reality_engine.db.readonly import connect_ro

    con = connect_ro(store_path(store), timeout_s=60)
    con.row_factory = sqlite3.Row
    return con


GUIDANCE_COLS = ("id", "symbol", "metric", "target_period", "low", "high", "unit", "direction", "quote",
                 "doc_key", "page", "known_at", "said_on")
STATEMENT_COLS = ("id", "symbol", "doc_key", "page", "call_date", "known_at", "is_fragment", "seq",
                  "answer_turn", "text", "numbers_json")


def guidance_rows(store: str) -> list[dict[str, Any]]:
    con = open_store(store)
    try:
        rows = con.execute(f"SELECT {','.join(GUIDANCE_COLS)} FROM guidance").fetchall()
    finally:
        con.close()
    return [_row_dict(r, list(GUIDANCE_COLS)) for r in rows]


def statement_rows(store: str) -> list[dict[str, Any]]:
    """Every statement of the store, in call reading order, so the 2 before a candidate are real context."""
    sql = ("SELECT id, symbol, doc_key, page, call_date, known_at, is_fragment, seq, answer_turn, "
           "COALESCE(NULLIF(statement, ''), quote) AS text, numbers_json FROM transcript_statement "
           "ORDER BY doc_key, COALESCE(seq, 1000000), id")
    con = open_store(store)
    try:
        rows = con.execute(sql).fetchall()
    finally:
        con.close()
    return [_row_dict(r, list(STATEMENT_COLS)) for r in rows]


def question_rows(store: str) -> dict[tuple[str, int], str]:
    """(doc_key, answer_turn) -> analyst question: what the answer was answering."""
    con = open_store(store)
    try:
        rows = con.execute("SELECT doc_key, answer_turn, question FROM transcript_question").fetchall()
    finally:
        con.close()
    out: dict[tuple[str, int], str] = {}
    for r in rows:
        try:
            turn = int(r["answer_turn"])
        except (TypeError, ValueError):
            continue
        key = (str(r["doc_key"]), turn)
        q = norm_ws(r["question"])
        if q and key not in out:
            out[key] = q
    return out


def count_statements(store: str) -> int:
    con = open_store(store)
    try:
        return int(con.execute("SELECT COUNT(*) FROM transcript_statement").fetchone()[0])
    finally:
        con.close()


def stores_with_statements() -> list[str]:
    out = []
    for store in list_stores():
        try:
            if count_statements(store):
                out.append(store)
        except sqlite3.Error:
            continue
    return out


def active_stores() -> list[str]:
    """Stores that hold at least one statement or guidance row (the rest are skipped, stage 1b)."""
    out = []
    for store in list_stores():
        try:
            con = open_store(store)
            try:
                n = int(con.execute(
                    "SELECT (SELECT COUNT(*) FROM transcript_statement) + (SELECT COUNT(*) FROM guidance)"
                ).fetchone()[0])
            finally:
                con.close()
        except sqlite3.Error:
            continue
        if n:
            out.append(store)
    return out


def pick_stores(candidates: list[str], n: int, seed: int = 7) -> list[str]:
    """The brief's random extra stores: seeded, never hand-picked."""
    pool = sorted(set(candidates))
    if n >= len(pool):
        return pool
    return sorted(random.Random(seed).sample(pool, n))


def brief_from_text(name: str, corpus: str) -> str:
    """A company brief built only by counting the company's own words (no model call)."""
    mat = Counter({term: len(re.findall(pat, corpus, re.I)) for term, pat in RAW_MATERIALS.items()})
    prod = Counter({term: len(re.findall(pat, corpus, re.I)) for term, pat in PRODUCTS.items()})
    sells = [t for t, n in prod.most_common() if n >= 2][:3]
    buys = [t for t, n in mat.most_common() if n >= 2][:3]
    ranked = sorted(((sum(mat.get(t, 0) + prod.get(t, 0) for t in terms), name)
                     for name, terms in SECTORS.items()), reverse=True)
    sector = None
    if ranked and ranked[0][0] >= 5 and (len(ranked) == 1 or ranked[0][0] >= 1.5 * ranked[1][0]):
        sector = ranked[0][1]
    if sector != "power and renewables":     # for every other sector power is an input, not a product
        sells = [t for t in sells if t != "power"]
    parts = [f"Company: {name}."]
    if sector:
        parts.append(f"Sector (inferred): {sector}.")
    if sells:
        parts.append("It sells: " + ", ".join(sells) + ".")
    if buys:
        parts.append("It buys or uses: " + ", ".join(buys) + ".")
    parts.append("A price or number about an input it buys is a COST node (cost.raw_material, "
                 "cost.power_fuel); a price it charges for its own output is a revenue node (revenue.price). "
                 "Where a term appears on both sides (cotton, power, caustic), decide from the sentence "
                 "whether the company buys or sells it.")
    return " ".join(parts)[:700]


def company_brief(store: str) -> str:
    con = open_store(store)
    try:
        row = con.execute("SELECT name FROM company LIMIT 1").fetchone()
        name = norm_ws(row["name"]) if row and row["name"] else store
        corpus = " ".join(
            [str(r[0] or "") for r in con.execute("SELECT quote FROM guidance")]
            + [str(r[0] or "") for r in con.execute(
                "SELECT COALESCE(NULLIF(statement,''), quote) FROM transcript_statement")]
            + [str(r[0] or "") for r in con.execute(
                "SELECT raw_label FROM kpi_series WHERE raw_label IS NOT NULL")])
    finally:
        con.close()
    return brief_from_text(name, corpus[:2_000_000])


# ------------------------------------------------------------------ document items (stage 2a)
DOC_PAGE_SQL = (
    "SELECT d.doc_key, d.symbol, d.doc_type, d.title, d.filing_date, d.known_at, p.page, p.text"
    " FROM doc d JOIN doc_page p ON p.doc_key = d.doc_key WHERE d.doc_type IN ({marks})"
    " ORDER BY d.doc_type, d.doc_key, p.page")


def split_paragraphs(text: Any, limit: int = PARA_CHARS) -> list[str]:
    """Page text -> paragraph-sized chunks: real paragraphs where the PDF has them, else packed sentences."""
    blocks = [block for block in re.split(r"\n\s*\n", str(text or "").replace("\r", "\n")) if block.strip()]
    out: list[str] = []
    for block in blocks:
        out.extend(_pack_sentences(_SENTENCE_SPLIT.split(norm_ws(block)), limit))
    return out


def _pack_sentences(pieces: list[str], limit: int) -> list[str]:
    out: list[str] = []
    buf = ""
    for piece in (norm_ws(p) for p in pieces):
        if not piece:
            continue
        while len(piece) > limit:                 # a table row or a run-on cell: cut on a word boundary
            cut = piece.rfind(" ", 0, limit)
            cut = limit if cut <= 0 else cut
            if buf:
                out.append(buf)
                buf = ""
            out.append(piece[:cut].strip())
            piece = piece[cut:].strip()
        if not buf:
            buf = piece
        elif len(buf) + 1 + len(piece) <= limit:
            buf = f"{buf} {piece}"
        else:
            out.append(buf)
            buf = piece
    if buf:
        out.append(buf)
    return [item for item in out if item]


def doc_page_rows(store: str, doc_types: tuple[str, ...]) -> dict[str, dict[str, Any]]:
    """One store's selected documents with their pages: {doc_key: {doc fields..., 'pages': {page: text}}}."""
    types = [str(t) for t in doc_types]
    marks = ",".join("?" * len(types))
    con = open_store(store)
    try:
        rows = con.execute(DOC_PAGE_SQL.format(marks=marks), types).fetchall()
    finally:
        con.close()
    docs: dict[str, dict[str, Any]] = {}
    for r in rows:
        doc = docs.setdefault(str(r["doc_key"]), {
            "doc_key": r["doc_key"], "symbol": r["symbol"], "doc_type": r["doc_type"], "title": r["title"],
            "filing_date": r["filing_date"], "known_at": r["known_at"], "pages": {}})
        doc["pages"][int(r["page"])] = str(r["text"] or "")
    return docs


def ocr_page_texts(store: str, doc_types: tuple[str, ...]) -> dict[tuple[str, int], str]:
    """The pages the OCR run stored in ``<store>_ocr.db.ocr_page`` (read-only; {} when the file is absent)."""
    path = STORE_ROOT / store / f"{store}_ocr.db"
    if not path.exists():
        return {}
    from reality_engine.db.readonly import connect_ro

    try:
        con = connect_ro(path, timeout_s=60)
    except (OSError, sqlite3.Error):
        return {}
    try:
        marks = ",".join("?" * len(doc_types))
        cursor = con.cursor()
        cursor.execute(f"SELECT doc_key, page, text FROM ocr_page WHERE doc_type IN ({marks})",
                       [str(t) for t in doc_types])
        rows = cursor.fetchall() or []
    except sqlite3.Error:
        return {}
    finally:
        con.close()
    return {(str(r[0]), int(r[1])): str(r[2] or "") for r in rows}


def doc_items_from_pages(store: str, docs: dict[str, dict[str, Any]],
                         ocr: dict[tuple[str, int], str] | None = None) -> tuple[
                             list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
    """Filter document pages into model items, and parse the announcement shapes into script claims.

    A page is cut into paragraphs and only a paragraph with a forward cue and a number with a unit is kept.
    A short announcement or press-release page is sent whole (the exchange letter is one item).  An
    announcement paragraph the deterministic parser reads completely becomes a claim and leaves the queue.
    """
    items: list[dict[str, Any]] = []
    claims: list[dict[str, Any]] = []
    counters: Counter[str] = Counter()
    ocr = ocr or {}
    for key in sorted(docs, key=lambda k: (str(docs[k].get("known_at") or ""), k)):
        doc = docs[key]
        dt = str(doc.get("doc_type") or "")
        counters[f"doc_{dt}_docs"] += 1
        title = norm_ws(doc.get("title"))[:300]
        if dt == "announcement" and title and FILING_SKIP.search(title):
            counters[f"doc_{dt}_drop_filing_type"] += 1
            counters[f"doc_{dt}_pages_skipped_filing_type"] += len(doc.get("pages") or {})
            continue
        for page in sorted(doc.get("pages") or {}):
            text = str(doc["pages"][page] or "")
            if len(norm_ws(text)) < 40 and (key, int(page)) in ocr:
                text = ocr[(key, int(page))]
                counters[f"doc_{dt}_pages_ocr"] += 1
            clean = norm_ws(text)
            if len(clean) < 25:               # an empty page or a bare "Page 3" / signature strip
                counters[f"doc_{dt}_drop_short"] += 1
                continue
            counters[f"doc_{dt}_pages"] += 1
            if not DOC_CUE.search(clean):
                counters[f"doc_{dt}_drop_no_cue"] += 1
                continue
            if not DOC_NUMBER.search(clean):
                counters[f"doc_{dt}_drop_no_number"] += 1
                continue
            if dt == "annual_report":
                chunks = split_paragraphs(text)
            else:
                chunks = [clean] if len(clean) <= MAX_TEXT else split_paragraphs(text)
            for index, chunk in enumerate(chunks):
                para = norm_ws(chunk)
                if not para:
                    continue
                counters[f"doc_{dt}_paragraphs"] += 1
                if dt == "annual_report" and BOILERPLATE.search(para):
                    # an announcement mentions related-party or CSR boilerplate inside the real letter, so
                    # the boilerplate drop is for the annual report only
                    counters[f"doc_{dt}_para_boilerplate"] += 1
                    continue
                if not DOC_CUE.search(para):
                    counters[f"doc_{dt}_para_no_cue"] += 1
                    continue
                if not DOC_NUMBER.search(para):
                    counters[f"doc_{dt}_para_no_number"] += 1
                    continue
                context = f"DOC: {title}" if title else ""
                if index and chunks[index - 1].strip():
                    context = f"{context}\nP{index}: {norm_ws(chunks[index - 1])[:400]}".strip()
                item: dict[str, Any] = {
                    "key": f"{store}|doc_page|{key}|{page}|{index}", "store": store,
                    "source_table": "doc_page", "source_id": None, "symbol": doc.get("symbol"),
                    "doc_key": key, "page": page, "paragraph": index,
                    "known_at": doc.get("known_at"), "event_date": doc.get("filing_date"),
                    "source_kind": dt, "text": para[:MAX_TEXT], "context": context[:MAX_CONTEXT],
                    "speaker_scope": speaker_scope(para, context),
                }
                if dt == "announcement":
                    parsed = announcement_claims(item)
                    if parsed:
                        claims.extend(parsed)
                        counters[f"doc_{dt}_script"] += len(parsed)
                        continue
                items.append(item)
                counters[f"doc_{dt}_kept"] += 1
    return items, claims, dict(counters)


def doc_items(store: str, doc_types: tuple[str, ...]) -> tuple[
        list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
    """Read one store's document pages (main DB plus the OCR fallback) and build the stage-2a items."""
    return doc_items_from_pages(store, doc_page_rows(store, doc_types), ocr_page_texts(store, doc_types))


def stores_without_transcripts() -> list[str]:
    """Stores with no transcript document and no transcript statement row (the stage-2a pilot pool)."""
    out = []
    for store in list_stores():
        try:
            con = open_store(store)
            try:
                n = int(con.execute(
                    "SELECT (SELECT COUNT(*) FROM doc WHERE doc_type='transcript')"
                    " + (SELECT COUNT(*) FROM transcript_statement)").fetchone()[0])
            finally:
                con.close()
        except sqlite3.Error:
            continue
        if not n:
            out.append(store)
    return out


# ------------------------------------------------------------------ announcement script parse
def _money_parts(raw_value: Any, raw_unit: Any) -> tuple[float, str] | None:
    unit = canon_unit(str(raw_unit or "").strip().rstrip("."))
    if unit == "million":
        unit = "mn"
    if unit not in ("inr_cr", "inr_lakh", "mn"):
        return None
    try:
        return float(str(raw_value or "").replace(",", "")), unit
    except ValueError:
        return None


def _money_value(match: re.Match[str]) -> tuple[float, str] | None:
    return _money_parts(match.group("v"), match.group("u"))


def _span_around(text: str, match: re.Match[str], before: int = MAX_QUOTE,
                 after: int = MAX_QUOTE) -> str:
    """The shortest readable span carrying the matched number (always a substring of ``text``)."""
    start = max(0, match.start() - before)
    end = min(len(text), match.end() + after)
    if start > 0:
        cut = text.find(" ", start)
        if 0 <= cut < match.start():
            start = cut
    if end < len(text):
        cut = text.rfind(" ", end, min(len(text), end + 40))
        if cut > match.end():
            end = cut
    return text[start:end].strip()


def execution_period(text: str) -> str | None:
    """The printed execution window of an order ('25 months', '2 years'), else None."""
    match = _EXECUTION_PERIOD.search(norm_ws(text))
    if match is None:
        return None
    unit = "months" if str(match.group("u") or "").lower().startswith("month") else "years"
    return f"{int(match.group('n'))} {unit}"


def horizon_period(text: str) -> str | None:
    """A printed horizon ('next 2 years', 'per annum') for a capex or fund-raise claim, else None."""
    match = HORIZON.search(norm_ws(text))
    return norm_ws(match.group(0)) if match else None


def _script_claim(item: dict[str, Any], node: str, value: float, unit: str, sign: str,
                  period: str | None, base: str | None, span: str, extractor: str) -> dict[str, Any]:
    claim: dict[str, Any] = {
        "store": item["store"], "symbol": item.get("symbol"), "source_table": item["source_table"],
        "source_id": None, "doc_key": item.get("doc_key"), "page": item.get("page"),
        "known_at": item.get("known_at"), "event_date": item.get("event_date"),
        "source_kind": item.get("source_kind"), "paragraph": item.get("paragraph"),
        "node": node, "segment": "total", "sign": sign, "value_low": value, "value_high": None,
        "unit": unit, "base": base, "effective_period": period, "conditional": 0,
        "quote_span": span, "statement": item["text"], "context": item.get("context") or "",
        "method": "script", "extractor": extractor,
        "speaker_scope": item.get("speaker_scope")
        or speaker_scope(item.get("text"), item.get("context") or ""),
    }
    return _finish(claim)


def order_claim(sentence: str, item: dict[str, Any]) -> dict[str, Any] | None:
    """'order worth Rs X crore ... to be executed over N months' -> revenue.order_book (script).

    The exchange letter prints the value in the opening sentence and the execution period in a table row
    further down, so the period falls back to the whole announcement (one letter, one order batch).
    """
    if not (_ORDER_WORD.search(sentence) and _ORDER_AWARD.search(sentence)) or _ORDER_BAD.search(sentence):
        return None
    match = _ORDER_VALUE.search(sentence)
    if match is None:
        return None
    period = execution_period(sentence) or execution_period(str(item.get("text") or ""))
    money = _money_value(match)
    if period is None or money is None:
        return None
    value, unit = money
    return _script_claim(item, "revenue.order_book", value, unit, "0", period, None,
                         _span_around(sentence, match), "announcement:order")


def capex_claim(sentence: str, item: dict[str, Any]) -> dict[str, Any] | None:
    """'board approved capex of Rs X crore' / 'from Rs A crore to Rs B crore' -> capex.amount (script)."""
    if not (_CAPEX_WORD.search(sentence) and _CAPEX_APPROVE.search(sentence)):
        return None
    base = None
    sign = "0"
    match: re.Match[str] | None = _CAPEX_FROM_TO.search(sentence)
    if match is not None:
        old = _money_parts(match.group("a"), match.group("au"))
        new = _money_parts(match.group("b"), match.group("bu"))
        if old is None or new is None or old[1] != new[1]:
            return None
        value, unit = new
        base = norm_ws(f"{match.group('a')} {match.group('au')}")
        sign = "+" if value > old[0] else "-"
    else:
        match = _CAPEX_AMOUNT.search(sentence)
        if match is None:
            return None
        money = _money_value(match)
        if money is None:
            return None
        value, unit = money
    return _script_claim(item, "capex.amount", value, unit, sign, horizon_period(sentence), base,
                         _span_around(sentence, match), "announcement:capex")


def raise_claim(sentence: str, item: dict[str, Any]) -> dict[str, Any] | None:
    """'QIP/warrant/rights of Rs X crore at an issue price of Rs Y' -> equity.shares (script)."""
    if not _RAISE_CUE.search(sentence) or _RAISE_DONE.search(sentence):
        return None
    size = _RAISE_SIZE.search(sentence)
    price = _RAISE_PRICE.search(sentence)
    if size is None or price is None:
        return None
    money = _money_value(size)
    if money is None:
        return None
    value, unit = money
    base = norm_ws(price.group(0))[:200]
    return _script_claim(item, "equity.shares", value, unit, "0", horizon_period(sentence), base,
                         _span_around(sentence, size), "announcement:raise")


def announcement_claims(item: dict[str, Any]) -> list[dict[str, Any]]:
    """Script-parse one announcement paragraph: every shape the letter prints in full, no model call."""
    text = norm_ws(item.get("text"))
    if not text:
        return []
    claims: list[dict[str, Any]] = []
    for sentence in _SENTENCE_SPLIT.split(text):
        for parser in (order_claim, capex_claim, raise_claim):
            claim = parser(sentence, item)
            if claim is not None:
                claims.append(claim)
    return claims


# ------------------------------------------------------------------ the script mapping
def guidance_claim(store: str, row: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
    """One guidance row -> one claim, or (None, reason) when it cannot be a quantified tree claim."""
    metric = norm_ws(row.get("metric")).lower()
    spec = GUIDANCE_MAP.get(metric)
    if spec is None:
        return None, "unmapped"
    low, high = _num(row.get("low")), _num(row.get("high"))
    if low is None and high is None:
        return None, "no_value"
    if low is not None and high is not None and high < low:
        low, high = high, low
    node, segment = spec
    quote = str(row.get("quote") or row.get("statement") or "")
    claim = {
        "store": store, "symbol": row.get("symbol"), "source_table": "guidance", "source_id": row.get("id"),
        "source_kind": "guidance", "paragraph": None,
        "doc_key": row.get("doc_key"), "page": row.get("page"), "known_at": row.get("known_at"),
        "event_date": row.get("said_on"), "node": node, "segment": segment,
        "sign": sign_of(row.get("direction")), "value_low": low, "value_high": high,
        "unit": canon_unit(row.get("unit")) or "units", "base": None,
        "effective_period": _clean(row.get("target_period"), 60), "conditional": 0,
        "quote_span": quote, "statement": quote, "context": "", "method": "script",
        "extractor": f"guidance:{metric}", "speaker_scope": speaker_scope(quote),
    }
    return _finish(claim), "mapped"


def item_from_guidance(store: str, row: dict[str, Any]) -> dict[str, Any]:
    quote = str(row.get("quote") or "")
    return {
        "key": f"{store}|guidance|{row.get('id')}", "store": store, "source_table": "guidance",
        "source_id": row.get("id"), "source_kind": "guidance", "paragraph": None,
        "symbol": row.get("symbol"), "doc_key": row.get("doc_key"),
        "page": row.get("page"), "known_at": row.get("known_at"), "event_date": row.get("said_on"),
        "text": quote[:MAX_TEXT], "context": "", "metric": row.get("metric"),
        "target_period": row.get("target_period"), "speaker_scope": speaker_scope(quote),
    }


def attach_context(rows: list[dict[str, Any]], questions: dict[tuple[str, int], str]) -> tuple[list[dict[str, Any]], Counter]:
    """Candidates from the statement rows, each with the 2 statements before it and its question.

    The quote check still runs against the target statement only; the context is for the model and the
    judge, never a place to find a number.
    """
    items: list[dict[str, Any]] = []
    counters: Counter[str] = Counter()
    prev: dict[str, deque[str]] = {}
    for row in rows:
        doc = str(row.get("doc_key") or "")
        earlier = list(prev.get(doc, deque()))[-2:]
        text = str(row.get("text") or "")
        with_numbers = str(row.get("numbers_json") or "") not in ("", "[]", "null")
        if with_numbers:
            counters["statements_with_numbers"] += 1
        if int(row.get("is_fragment") or 0):
            counters["statements_fragment"] += 1
        elif not with_numbers:
            counters["statements_no_numbers"] += 1
        elif not CUE.search(text):
            counters["statements_no_cue"] += 1
        else:
            lines = [f"S{i + 1}: {norm_ws(t)}" for i, t in enumerate(earlier)]
            turn_value = row.get("answer_turn")
            try:
                turn = int(turn_value) if turn_value is not None else None
            except (TypeError, ValueError):
                turn = None
            question = questions.get((doc, turn)) if turn is not None else None
            if question:
                lines.append(f"Q: {question}")
            items.append({
                "key": f"{row['_store']}|transcript_statement|{row.get('id')}", "store": row["_store"],
                "source_table": "transcript_statement", "source_id": row.get("id"),
                "source_kind": "transcript", "paragraph": None,
                "symbol": row.get("symbol"), "doc_key": row.get("doc_key"), "page": row.get("page"),
                "known_at": row.get("known_at"), "event_date": row.get("call_date"),
                "text": text[:MAX_TEXT], "context": "\n".join(lines)[:MAX_CONTEXT],
                "speaker_scope": speaker_scope(text, "\n".join(lines)),
            })
            counters["statements_sent"] += 1
        prev.setdefault(doc, deque(maxlen=2)).append(norm_ws(text))
    return items, counters


# ------------------------------------------------------------------ the model contract
SYSTEM = """You extract forward-looking, quantified claims about the financial drivers of Indian listed companies from management text (concall statements, guidance quotes, annual-report pages, press releases, exchange announcements).

Reply with JSON only, no markdown fences, no commentary.

The driver tree has exactly these nodes; nothing else exists:
revenue.volume | revenue.price | revenue.total | revenue.order_book | revenue.mix | cost.raw_material | cost.employee | cost.power_fuel | cost.other | margin.ebitda | margin.gross | capex.amount | capacity.add | debt.level | debt.cost | equity.shares | equity.dividend | working_capital.days

A share, mix or contribution ("exports contributed 17% of total income", "exports are 20%-25% of sales") fills revenue.mix with the segment named (exports, domestic, a product), not revenue.total. A share of one unit's own potential or utilisation ("30% to 40% of the revenues of the total potential", "97% utilisation of the new unit") is that unit's ramp, not a company mix: revenue.total (pct) or revenue.volume, segment = the unit.

Source rules:
- An annual report is published months after the fiscal year it covers. Its own-year figures and growth rates ("FY25 revenue grew 20%", "the Company achieved revenue of Rs 679 crore in FY24") are past results, not claims, even on the MD&A or the directors' report page. Only an explicit outlook, target or plan for a later period is a claim.
- An exchange announcement or press release that reports a completed event (an allotment made, a plant shut down, a meeting held) is not a claim. An order won today is forward-looking when execution lies ahead: its value fills revenue.order_book with the execution period as effective_period, never revenue.total. A board-approved capex fills capex.amount; a proposed or approved QIP, rights issue or preferential issue fills equity.shares, with the issue price in base.
- A press release that only repeats the quarter just reported is past.

Rules for every statement:
- Output every forward-looking claim that fills one node. A statement may carry two claims; output both.
- The statement is the target; the context lines before it are only there to make it readable (and the question the statement answers). Never take a number, period or quote from the context.
- A statement about what already happened ("revenue grew 18% last quarter", "we spent Rs 85 crore in Q1") is not a claim: set drop to "past".
- If a statement changes no node (a rating action, an award, praise, a policy aside), set drop to "no_driver".
- Never add, subtract, convert, round, annualise or total a number. Copy the number exactly as printed, in the unit it is printed in. A number you computed is not allowed.
- quote_span must be copied character for character from the target statement: the shortest span that carries the number(s). value_low and value_high must be numbers printed inside quote_span.
- value_low/value_high: the printed numbers, low first. If one number, set value_high to null. A range such as "20%-22%" is 20 and 22. A growth stated "at least 20% to 25%" or "up 20%-25%" is a range (20 and 25), not a single target.
- unit: inr_cr, inr_lakh, inr, usd, usd_mn, pct, bp, months, days, or the printed unit word (tonnes, mt, mw, units, kl, tpa). Use the unit printed next to the number: "30 days" is days, "Rs 240 crore" is inr_cr, "20%" is pct.
- base: what the number is measured against (e.g. "FY25 revenue", "annual revenue"), else null. When the text says "including GST", "inclusive of GST" or "excluding GST", copy that phrase into base.
- effective_period: the period the claim applies to, exactly as printed when present (FY26, Q3FY26, "next 24 months"), else null.
- conditional: true only when the claim depends on an event that may not happen (approval, order win, commissioning).
- sign: use "0" for an absolute level or range the company expects (revenue of Rs. 1,900 crore, utilisation of 60%-65%, margins around 30%) and for an ambiguous range; use "+" or "-" only when the statement states a change from the current level (up 20%, down 5%, expands by 200 basis points, cuts cost by Rs 10 crore). A debt repayment, OTS settlement or loan reduction is "-"; a dividend declared or recommended is "+".
- A change from one number to another ("from INR450 crores to INR100 crores", "reduce to 8%") is a target: value_low = value_high = the destination number, base = the starting number, and the sign follows the destination against the start. A plain range with no change ("INR 2,700 to 2,800 crores") is a range: value_low and value_high as printed.
- When the context or the analyst's question names the measure the statement is answering (gross margin, EBITDA margin, utilisation, realisation), the node follows that measure: gross margin -> margin.gross, EBITDA margin -> margin.ebitda, utilisation -> revenue.volume.
- The claim must be about this company's own figures, not the industry, the country or a customer.
- A price or number about an input the company buys (raw material, power, fuel) fills a cost node; a price it charges for its own output fills a revenue node. When a product and a raw material share a name (cotton, caustic soda), the company's purchase is the cost and its sale is the revenue.
- segment: the segment, product, geography or unit the claim belongs to, else "total". When the quote or any line around it names a unit, plant, product, subsidiary or new line (including "that unit", "the new line", "full impact", "incremental revenue", "additional capacity"), the number is that unit's increment, never a company-wide level: set segment to it ("new unit" when it is not named), sign "+", and base "new unit".

Example statement: "With the plant already operating at about 95% utilization, the incremental capacity is expected to generate Rs. 50-Rs. 75 crores additional annual revenue at present price, once fully operational."
Example answer: {"id":1,"drop":null,"claims":[{"node":"revenue.volume","segment":"total","sign":"+","value_low":50,"value_high":75,"unit":"inr_cr","base":"annual revenue","effective_period":"once fully operational","conditional":true,"quote_span":"Rs. 50-Rs. 75 crores additional annual revenue"}]}

Example statement: "Total income for Q2 FY '26 stood at Rs. 26.02 crores, registering a 55.6% year-on-year growth."
Example answer: {"id":2,"drop":"past","claims":[]}

Example statement: "During the quarter, CARE Rating of the company's long-term and short-term facilities at a stable A1 for a total amount of Rs. 21 crores."
Example answer: {"id":3,"drop":"no_driver","claims":[]}

Example announcement: "The Company has secured an order worth Rs. 200.02 Crores, to be executed over 25 months."
Example answer: {"id":4,"drop":null,"claims":[{"node":"revenue.order_book","segment":"total","sign":"0","value_low":200.02,"value_high":null,"unit":"inr_cr","base":null,"effective_period":"25 months","conditional":false,"quote_span":"secured an order worth Rs. 200.02 Crores, to be executed over 25 months"}]}

Example statement: "But in Q4, we expect almost 30% to 40% of the revenues of the total potential to kick in."
Example answer: {"id":5,"drop":null,"claims":[{"node":"revenue.total","segment":"new unit","sign":"+","value_low":30,"value_high":40,"unit":"pct","base":"new unit","effective_period":"Q4","conditional":false,"quote_span":"almost 30% to 40% of the revenues of the total potential"}]}

Example statement: "But going ahead, we see a healthy increase in revenue by at least 20% to 25% in this financial year."
Example answer: {"id":6,"drop":null,"claims":[{"node":"revenue.total","segment":"total","sign":"+","value_low":20,"value_high":25,"unit":"pct","base":null,"effective_period":"this financial year","conditional":false,"quote_span":"increase in revenue by at least 20% to 25% in this financial year"}]}

Output exactly:
{"items":[{"id":1,"drop":null,"claims":[...]},{"id":2,"drop":"past","claims":[]}]}
Every statement id must appear exactly once. Use "drop":"past" or "drop":"no_driver" with an empty claims array when nothing qualifies.
"""

JUDGE_SYSTEM = """You audit machine-extracted claims about a company's financial drivers against the management text they came from.

Reply with JSON only, no markdown fences, no commentary.

Each block starts with CLAIM <id>, where <id> is the claim's own id, then the target STATEMENT, its SOURCE (transcript, guidance, annual_report, press_release or announcement), its FILED date (the day the document became known), its CONTEXT (the statements before it in the call, or the document title and the paragraph before it, and when the statement answers an analyst, the question), and the extracted claim. A block whose paragraph names a unit, plant, product, new line or subsidiary for a whole-company level carries a SCOPE line.

Decide six booleans, plus scope_ok only on a block that carries SCOPE:
- node_ok: the STATEMENT itself really supports this driver node (a receivables sentence is not revenue.volume; a credit-rating sentence is no driver at all; a geographic mix is not an order book; a price the company PAYS for an input is a cost, not revenue.price; a price it CHARGES for its own output is revenue.price; an EBITDA amount is not a margin). An order won fills revenue.order_book, never revenue.total; a board-approved capex fills capex.amount; a QIP/warrants/rights size fills equity.shares. A single unit's own ramp or utilisation ("30%-40% of its potential", "97% utilisation of the new unit") is not revenue.mix and not a company-wide level.
- sign_ok: "0" is right for an absolute level or range the company expects (revenue of Rs. 1,900 crore, utilisation of 60%-65%, margins around 30%) and for an ambiguous range; "+" or "-" is right only when the statement states a change from the current level (up 20%, down 5%, expands by 200 bp, cuts cost). A level target marked +/- fails, except a revenue amount the CLAIM labels segment/base "new unit" (the full impact or incremental revenue of a new unit, plant or line): that is an increment, so "+" is right. A debt repayment, OTS settlement or loan reduction on debt.level must be "-"; a dividend declared or recommended on equity.dividend must be "+".
- unit_ok: the unit and magnitude agree with the words attached to the number in quote_span (days vs months vs years, % vs basis points, crore vs lakh vs million, MW vs tonnes vs units), and the unit can belong to the node at all (capacity.add is a size, never a waiting time; working_capital.days is days; a margin is % or bp).
- period_ok: effective_period is a real period or horizon the claim applies to (FY26, Q3FY26, next 24 months, once fully operational). Null with no horizon in the statement fails; "post that" with no referent fails. Judge it against FILED: a target period that had already ended on the FILED date is not a live claim.
- forward_ok: the claim is forward-looking (guidance, expectation, plan, target) on the FILED date, not a past result ("we spent", "grew last quarter"). "FY25" in a document filed in 2025-05 is the year just gone (past), while the same words in a document filed in 2024-08 can still be forward. An annual report's own-year figures are past even in the MD&A or the directors' report; an announcement of a completed allotment or a completed event with no forward amount is past; an order won with execution still ahead, a board-approved capex, and a proposed or approved QIP/rights/preferential issue ARE forward.
- company_ok: the claim is about this company's own figures, not the industry, the country, a customer, a supplier or a competitor (an industry acreage forecast, a customer's price, a sector number fails). A rating agency's estimate or outlook (CRISIL, ICRA, CARE, India Ratings, Acuite, Brickwork) is that agency's view, not the company's own claim.
- scope_ok: asked only when the block carries SCOPE. True only when the value really is the whole company's figure and the paragraph's plant, unit, product, new line or subsidiary is mere background. False when the paragraph names that unit and the value is its increment, ramp, utilisation or share of its own potential.

Also return node_suggest: when node_ok is false, the tree node the claim really belongs to (node_ok against that one must be true) or null when no node fits. When the context or the analyst's question names the measure (gross margin, EBITDA margin, utilisation), the node follows it: gross margin -> margin.gross, EBITDA margin -> margin.ebitda, utilisation -> revenue.volume.

Judge the claim only against its statement, its context and the company paragraph. Then answer exactly, with the claim's id copied from CLAIM <id>, and nothing else:
{"items":[{"id":123,"node_ok":true,"sign_ok":true,"unit_ok":true,"period_ok":true,"forward_ok":true,"company_ok":true,"node_suggest":null}]}
Every claim id must appear exactly once.
"""


def build_prompt(items: list[dict[str, Any]], brief: str = "") -> str:
    lines = [SYSTEM]
    if brief:
        lines.append("COMPANY:")
        lines.append(brief)
    lines.append("STATEMENTS")
    for item in items:
        if item.get("context"):
            lines.append(f"{item['id']}. CONTEXT (reading order, before the statement):")
            lines.extend(f"   {line}" for line in item["context"].splitlines())
            lines.append(f"   TARGET STATEMENT: {norm_ws(item['text'])}")
        else:
            lines.append(f"{item['id']}. {norm_ws(item['text'])}")
    return "\n".join(lines) + "\n"


def parse_reply(text: str) -> list[dict[str, Any]]:
    body = (text or "").strip()
    if body.startswith("```"):
        body = "\n".join(line for line in body.splitlines() if not line.strip().startswith("```"))
    i, j = body.find("{"), body.rfind("}")
    if i < 0 or j <= i:
        raise ValueError("no JSON object in reply")
    obj = json.loads(body[i:j + 1])
    items = obj.get("items") if isinstance(obj, dict) else None
    if not isinstance(items, list):
        raise ValueError("reply has no items list")
    return [it for it in items if isinstance(it, dict)]


def claim_from_reply(raw: dict[str, Any], item: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
    """Validate one model claim against its item.  (claim, reason) -- claim None when dropped."""
    node = norm_ws(raw.get("node")).lower()
    if node not in NODES:
        return None, "bad_node"
    low, high = _num(raw.get("value_low")), _num(raw.get("value_high"))
    if low is None and high is None:
        return None, "no_value"
    if low is not None and high is not None and high < low:
        low, high = high, low
    sign = norm_ws(raw.get("sign"))
    if sign in ("+1", "up", "increase"):
        sign = "+"
    elif sign in ("-1", "down", "decrease"):
        sign = "-"
    if sign not in ("+", "-", "0"):
        sign = "0"
    claim = {
        "store": item["store"], "symbol": item.get("symbol"), "source_table": item["source_table"],
        "source_id": item.get("source_id"), "source_kind": item.get("source_kind"),
        "paragraph": item.get("paragraph"), "doc_key": item.get("doc_key"), "page": item.get("page"),
        "known_at": item.get("known_at"), "event_date": item.get("event_date"),
        "node": node, "segment": _clean(raw.get("segment"), 80) or "total", "sign": sign,
        "value_low": low, "value_high": high, "unit": canon_unit(raw.get("unit")) or "units",
        "base": _clean(raw.get("base"), 200), "effective_period": _clean(raw.get("effective_period"), 60),
        "conditional": bool(raw.get("conditional")), "quote_span": str(raw.get("quote_span") or ""),
        "statement": item["text"], "context": item.get("context") or "", "method": "model",
        "extractor": MODEL,
        "speaker_scope": item.get("speaker_scope")
        or speaker_scope(item.get("text"), item.get("context") or ""),
    }
    return _finish(claim), "claim"


def _drop_of(raw: dict[str, Any]) -> str:
    drop = norm_ws(raw.get("drop")).lower()
    return "past" if drop == "past" else "no_driver"


# ------------------------------------------------------------------ the judge contract
def judge_prompt(claims: list[dict[str, Any]], brief: str = "") -> str:
    lines = [JUDGE_SYSTEM]
    if brief:
        lines.append("COMPANY:")
        lines.append(brief)
    needs_scope = any(scope_flagged(claim) for claim in claims)
    for claim in claims:
        low = "?" if claim["value_low"] is None else f"{float(claim['value_low']):g}"
        high = "" if claim["value_high"] is None else f"-{float(claim['value_high']):g}"
        lines.append(f"\nCLAIM {claim['id']}")
        lines.append(f"STATEMENT: {norm_ws(claim['statement'])}")
        lines.append(f"SOURCE: {claim.get('source_kind') or 'transcript'}")
        lines.append(f"FILED: {norm_ws(claim.get('known_at'))[:10] or 'unknown'}")
        if claim.get("context"):
            lines.append("CONTEXT:")
            lines.extend(f"  {line}" for line in str(claim["context"]).splitlines())
        lines.append(f"CLAIM: node={claim['node']} segment={claim['segment']} sign={claim['sign']} "
                     f"value={low}{high} unit={claim['unit']} period={claim['effective_period'] or 'null'} "
                     f"base={claim['base'] or 'null'}")
        lines.append(f"quote_span: {norm_ws(claim['quote_span'])}")
        if scope_flagged(claim):
            lines.append("SCOPE: the paragraph names a unit, plant, product, new line or subsidiary for a "
                         "whole-company level claim. Answer scope_ok: is this value really the whole "
                         "company's figure, not that unit's increment or ramp?")
    scope_field = ',"scope_ok":true' if needs_scope else ""
    lines.append('\nOutput exactly: {"items":[{"id":<same id>,"node_ok":true,"sign_ok":true,"unit_ok":true,'
                 f'"period_ok":true,"forward_ok":true,"company_ok":true,"node_suggest":null{scope_field}}}]}}')
    lines.append('Every claim id must appear exactly once. Add "scope_ok" only to a block that carries a SCOPE '
                 "line, and never to a block without one.")
    return "\n".join(lines) + "\n"


def parse_judge_reply(text: str) -> list[dict[str, Any]]:
    """Strict JSON first; if that fails, read the booleans item by item from the raw text."""
    try:
        items = parse_reply(text)
    except (ValueError, TypeError):
        return _parse_judge_tolerant(text)
    out = []
    for it in items:
        verdict: dict[str, Any] = {}
        for field in JUDGE_FIELDS:
            value = it.get(field)
            verdict[field] = bool(value) if isinstance(value, bool) else str(value).lower() in ("true", "yes", "1")
        if "scope_ok" in it:
            value = it.get("scope_ok")
            verdict["scope_ok"] = bool(value) if isinstance(value, bool) else str(value).lower() in (
                "true", "yes", "1")
        verdict["node_suggest"] = _clean(it.get("node_suggest"), 60)
        verdict["why"] = _clean(it.get("why"), 300) or ""
        out.append({"id": it.get("id"), **verdict})
    return out


def _parse_judge_tolerant(text: str) -> list[dict[str, Any]]:
    """Recover `{"id": N, ...booleans}` items from a reply whose JSON braces/quotes are broken."""
    out: list[dict[str, Any]] = []
    matches = list(re.finditer(r'["\']?id["\']?\s*:\s*(\d+)', text or ""))
    for i, match in enumerate(matches):
        chunk = text[match.end(): matches[i + 1].start() if i + 1 < len(matches) else match.end() + 600]
        verdict: dict[str, Any] = {"id": int(match.group(1))}
        ok = True
        for field in JUDGE_FIELDS:
            found = re.search(rf'["\']?{field}["\']?\s*:\s*(true|false)', chunk, re.I)
            if not found:
                ok = False
                break
            verdict[field] = found.group(1).lower() == "true"
        if ok:
            suggested = re.search(r'["\']?node_suggest["\']?\s*:\s*"([^"]{2,40})"', chunk, re.I)
            verdict["node_suggest"] = _clean(suggested.group(1), 60) if suggested else None
            verdict["why"] = ""
            out.append(verdict)
    return out


# ------------------------------------------------------------------ limiter
class Stopped(Exception):
    """The limiter or the empty-answer guard ended the run."""


class Adaptive:
    """In-flight gate that grows and shrinks with the observed error rate.

    ``--unleashed``: every 5 minutes raise the limit by 10 while the error rate of the last 5 minutes is
    under 2% (no upper cap).  A 429 halves it (floor 1) and is logged by the caller.  The run stops only
    after 30 consecutive minutes of failures.  The clock is injectable for tests.
    """

    def __init__(self, start: int = 30, unleashed: bool = False, clock=time.monotonic) -> None:
        self.clock = clock
        self.unleashed = unleashed
        self.limit = max(1, int(start))
        self.active = 0
        self.stopped = threading.Event()
        self._cond = threading.Condition()
        self._window: deque[tuple[float, bool]] = deque()
        self._failure_since: float | None = None
        self._last_raise = clock()
        self._monitor_done = threading.Event()
        self._thread: threading.Thread | None = None

    def acquire(self) -> None:
        with self._cond:
            while self.active >= self.limit:
                if self.stopped.is_set():
                    raise Stopped("limiter stopped")
                self._cond.wait(timeout=0.5)
            if self.stopped.is_set():
                raise Stopped("limiter stopped")
            self.active += 1

    def release(self) -> None:
        with self._cond:
            self.active = max(0, self.active - 1)
            self._cond.notify_all()

    def saw(self, ok: bool) -> None:
        now = self.clock()
        with self._cond:
            self._window.append((now, ok))
            while self._window and now - self._window[0][0] > WINDOW_S:
                self._window.popleft()
            self._failure_since = None if ok else (self._failure_since or now)

    def tick(self, now: float | None = None) -> None:
        now = self.clock() if now is None else now
        with self._cond:
            recent = [ok for t, ok in self._window if now - t <= WINDOW_S]
            if (self.unleashed and len(recent) >= 5 and now - self._last_raise >= WINDOW_S
                    and sum(1 for ok in recent if not ok) / len(recent) < 0.02):
                self.limit += 10
                self._last_raise = now
                self._cond.notify_all()
            if self._failure_since is not None and now - self._failure_since >= FAIL_STOP_S:
                self.stopped.set()
                self._cond.notify_all()

    def halve(self) -> int:
        with self._cond:
            self.limit = max(1, self.limit // 2)
            self._cond.notify_all()
        return self.limit

    def start_monitor(self) -> None:
        def loop() -> None:
            while not self._monitor_done.wait(30):
                self.tick()

        self._thread = threading.Thread(target=loop, daemon=True, name="t228-limiter")
        self._thread.start()

    def stop_monitor(self) -> None:
        self._monitor_done.set()


# ------------------------------------------------------------------ output DB
SCHEMA = """
CREATE TABLE IF NOT EXISTS claim (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT, store TEXT, symbol TEXT, source_table TEXT, source_id INTEGER,
  source_kind TEXT, paragraph INTEGER,
  speaker_scope TEXT, dup_of TEXT,
  doc_key TEXT, page INTEGER, known_at TEXT, event_date TEXT,
  node TEXT, segment TEXT, sign TEXT, value_low REAL, value_high REAL, unit TEXT,
  base TEXT, effective_period TEXT, conditional INTEGER,
  quote_span TEXT, statement TEXT, context TEXT,
  method TEXT, extractor TEXT, status TEXT, status_reason TEXT, created_at TEXT,
  judge_ok INTEGER, judge_node INTEGER, judge_sign INTEGER, judge_unit INTEGER,
  judge_period INTEGER, judge_forward INTEGER, judge_company INTEGER, judge_fail TEXT, judge_why TEXT,
  judge_suggest TEXT
);
CREATE INDEX IF NOT EXISTS ix_claim_node ON claim (node, status);
CREATE INDEX IF NOT EXISTS ix_claim_src ON claim (store, source_table, source_id);
CREATE TABLE IF NOT EXISTS read_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT, role TEXT, store TEXT, attempt INTEGER,
  start_at TEXT, end_at TEXT, seconds REAL,
  http_status INTEGER, in_tok INTEGER, out_tok INTEGER,
  items INTEGER, claims INTEGER, outcomes TEXT, items_done TEXT,
  in_flight INTEGER, error TEXT
);
CREATE TABLE IF NOT EXISTS quota_event (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT, store TEXT, at_utc TEXT, at_ist TEXT, http_status INTEGER,
  in_flight INTEGER, body TEXT
);
"""

CLAIM_COLS = ("run_id", "store", "symbol", "source_table", "source_id", "source_kind", "paragraph",
              "doc_key", "page", "known_at", "event_date", "node", "segment", "sign", "value_low",
              "value_high", "unit", "base", "effective_period", "conditional", "quote_span", "statement",
              "context", "method", "extractor", "status", "status_reason", "created_at", "judge_ok",
              "judge_node", "judge_sign", "judge_unit", "judge_period", "judge_forward", "judge_fail",
              "judge_why", "judge_suggest", "speaker_scope", "dup_of")



class Writer:
    """Thread-safe writer for the claims DB (one connection, one lock: writes are small and rare)."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.con = sqlite3.connect(str(path), check_same_thread=False, timeout=60)
        self.con.row_factory = sqlite3.Row
        self.con.execute("PRAGMA journal_mode=WAL")
        self.con.executescript(SCHEMA)
        # additive migration: a DB written before stage 2a keeps its rows and gains the new columns
        have = {str(r[1]) for r in self.con.execute("PRAGMA table_info(claim)")}
        for column, kind in (("source_kind", "TEXT"), ("paragraph", "INTEGER"),
                             ("speaker_scope", "TEXT"), ("dup_of", "TEXT")):
            if column not in have:
                self.con.execute(f"ALTER TABLE claim ADD COLUMN {column} {kind}")
        self.con.commit()

    def insert_claims(self, run_id: str, claims: list[dict[str, Any]]) -> None:
        if not claims:
            return
        with self.lock:
            for c in claims:
                # IS, not =: a document claim has no source_id row number and must still replace itself
                self.con.execute(
                    "DELETE FROM claim WHERE store=? AND source_table=? AND source_id IS ?"
                    " AND doc_key IS ? AND page IS ? AND paragraph IS ?",
                    (c["store"], c["source_table"], c.get("source_id"), c.get("doc_key"), c.get("page"),
                     c.get("paragraph")))
            self.con.executemany(
                f"INSERT INTO claim ({','.join(CLAIM_COLS)}) VALUES ({','.join('?' * len(CLAIM_COLS))})",
                [[run_id, *(c.get(col) for col in CLAIM_COLS[1:])] for c in claims])
            self.con.commit()


    def clear_script(self, stores: list[str]) -> None:
        with self.lock:
            self.con.executemany("DELETE FROM claim WHERE method='script' AND store=?", [(s,) for s in stores])
            self.con.commit()

    def read_log(self, run_id: str, store: str, attempt: int, started: str, ended: str, seconds: float,
                 http_status: int, in_tok: int, out_tok: int, items: int, claims: int,
                 outcomes: dict[str, int] | None, items_done: list[str] | None, in_flight: int,
                 error: str = "", role: str = "extract") -> None:
        with self.lock:
            self.con.execute(
                "INSERT INTO read_log (run_id, role, store, attempt, start_at, end_at, seconds, http_status,"
                " in_tok, out_tok, items, claims, outcomes, items_done, in_flight, error)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (run_id, role, store, attempt, started, ended, seconds, http_status, in_tok, out_tok, items,
                 claims, json.dumps(outcomes) if outcomes is not None else None,
                 json.dumps(items_done) if items_done is not None else None, in_flight, error))
            self.con.commit()

    def quota_event(self, run_id: str, store: str, http_status: int, in_flight: int, body: str) -> None:
        with self.lock:
            self.con.execute(
                "INSERT INTO quota_event (run_id, store, at_utc, at_ist, http_status, in_flight, body)"
                " VALUES (?,?,?,?,?,?,?)",
                (run_id, store, utc_now(), ist_now(), http_status, in_flight, (body or "")[:300]))
            self.con.commit()

    def done_keys(self) -> set[str]:
        with self.lock:
            rows = self.con.execute("SELECT items_done FROM read_log WHERE items_done IS NOT NULL").fetchall()
        done: set[str] = set()
        for (raw,) in rows:
            try:
                done.update(json.loads(raw))
            except (TypeError, ValueError):
                continue
        return done

    def claims_to_judge(self) -> list[dict[str, Any]]:
        with self.lock:
            rows = self.con.execute(
                "SELECT id, store, symbol, source_kind, node, segment, sign, value_low, value_high, unit,"
                " base, effective_period, quote_span, statement, context, known_at FROM claim"
                " WHERE judge_ok IS NULL AND status='verified' ORDER BY store, id").fetchall()
        return [dict(r) for r in rows]

    def apply_judge(self, claim_id: int, verdict: dict[str, Any]) -> None:
        """Apply the six booleans; on a node_ok failure with a valid suggestion, keep the claim under
        the suggested tree node as unverified (`judge_renode`) instead of losing it.  Never verified.

        A level claim on the whole company whose paragraph names a unit/plant/product/new line needs the
        judge's explicit ``scope_ok``: without it the claim stays unverified even when all six pass.
        """
        fails = [f for f in JUDGE_FIELDS if not verdict.get(f)]
        with self.lock:
            row = self.con.execute(
                "SELECT node, segment, sign, statement, context, quote_span FROM claim WHERE id=?",
                (claim_id,)).fetchone()
            old_node = str(row["node"]) if row is not None else ""
            if row is not None and scope_flagged(dict(row)) and verdict.get("scope_ok") is not True:
                fails.append("scope_ok")
            status, reason = ("unverified", "judge:" + ",".join(fails)) if fails else ("verified", "")
            suggestion = norm_ws(verdict.get("node_suggest")).lower() or None
            if suggestion not in NODES:
                suggestion = None
            renode = bool("node_ok" in fails and suggestion and suggestion != old_node)
            if renode:
                reason = "judge_renode"
            self.con.execute(
                "UPDATE claim SET node=?, judge_ok=?, judge_node=?, judge_sign=?, judge_unit=?,"
                " judge_period=?, judge_forward=?, judge_company=?, judge_suggest=?, judge_fail=?,"
                " judge_why=?, status=?, status_reason=? WHERE id=?",
                (suggestion if renode else old_node, 0 if fails else 1,
                 *(1 if verdict.get(f) else 0 for f in JUDGE_FIELDS), suggestion,
                 ",".join(fails), verdict.get("why") or "", status, reason, claim_id))
            self.con.commit()

    def mark_judge_failed(self, claim_ids: list[int]) -> None:
        with self.lock:
            self.con.executemany(
                "UPDATE claim SET judge_ok=0, judge_fail='judge_error', status='unverified',"
                " status_reason='judge_error' WHERE id=?", [(i,) for i in claim_ids])
            self.con.commit()

    def reset_judge_errors(self) -> int:
        """Put judge_error claims back in the queue (for a --judge-only pass after a judge outage)."""
        with self.lock:
            cur = self.con.execute(
                "UPDATE claim SET judge_ok=NULL, judge_fail=NULL, judge_suggest=NULL, status='verified',"
                " status_reason='' WHERE judge_fail='judge_error'")
            self.con.commit()
            return cur.rowcount

    def dedupe(self) -> int:
        """One row per (symbol, normalised quote_span, node): best verdict, script over model, then oldest."""
        with self.lock:
            rows = self.con.execute(
                "SELECT id, symbol, quote_span, node, status, method, judge_ok FROM claim").fetchall()
            groups: dict[tuple[str, str, str], list[sqlite3.Row]] = defaultdict(list)
            for r in rows:
                groups[(r["symbol"] or "", norm_ws(r["quote_span"]), r["node"] or "")].append(r)
            losers: list[int] = []
            for group in groups.values():
                if len(group) < 2:
                    continue
                winner = max(group, key=lambda r: (r["judge_ok"] == 1, r["status"] == "verified",
                                                   r["method"] == "script", -int(r["id"])))
                losers.extend(int(r["id"]) for r in group if int(r["id"]) != int(winner["id"]))
            self.con.executemany("DELETE FROM claim WHERE id=?", [(i,) for i in losers])
            self.con.commit()
        return len(losers)

    def dedupe_cross_source(self) -> tuple[int, int]:
        """Fold the same fact from two *different sources* into the earliest ``known_at`` row.

        Two equivalences: the exact same statement (a guidance row and the transcript statement it came
        from) and the brief's key (symbol, node, segment, value_low, value_high, unit, effective_period),
        where a period that starts with the same words is the same period ("6 months" and "6 months from
        commissioning").  Only a pair of *different* source kinds can join two rows: a same-kind group is
        folded only when another source carries the same fact (then its earliest copy survives); two
        announcements that print the same share count with no third source are two rows, not one fact.
        Quarantined rows are never folded.  Returns (folded claims, winners).
        """
        def period_key(value: Any) -> str:
            return re.sub(r"[^a-z0-9]", "", norm_ws(value).lower())

        def same_period(a: str, b: str) -> bool:
            if a == b:
                return True
            shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
            return bool(shorter) and len(shorter) >= 6 and longer.startswith(shorter)

        with self.lock:
            rows = [dict(r) for r in self.con.execute(
                "SELECT id, symbol, statement, node, segment, value_low, value_high, unit,"
                " effective_period, known_at, status, method, context, source_kind FROM claim"
                " WHERE status <> 'quarantined'").fetchall()]
            if not rows:
                return 0, 0
            parent = {int(r["id"]): int(r["id"]) for r in rows}
            kind = {int(r["id"]): norm_ws(r["source_kind"]) for r in rows}

            def find(i: int) -> int:
                while parent[i] != i:
                    parent[i] = parent[parent[i]]
                    i = parent[i]
                return i

            def union(a: int, b: int) -> None:
                ra, rb = find(a), find(b)
                if ra != rb:
                    parent[rb] = ra

            def union_cross(ids: list[int]) -> None:
                """Fold only across source kinds: a cross-source fact, not a repeated same-source number."""
                for i in range(len(ids)):
                    for j in range(i + 1, len(ids)):
                        if kind[ids[i]] != kind[ids[j]]:
                            union(ids[i], ids[j])

            # pass 1: the same text (a guidance row and its transcript statement)
            stmt_keys = [((r["symbol"] or ""), norm_ws(r["statement"]), norm_ws(r["node"]),
                          r["value_low"], r["value_high"], canon_unit(r["unit"])) for r in rows]
            buckets: dict[tuple[Any, ...], list[int]] = defaultdict(list)
            for key, row in zip(stmt_keys, rows):
                buckets[key].append(int(row["id"]))
            for ids in buckets.values():
                union_cross(ids)
            # pass 2: the brief's fact key, with the period prefix match
            value_of = [((r["symbol"] or ""), r["node"] or "", norm_ws(r["segment"]).lower(),
                         r["value_low"], r["value_high"], canon_unit(r["unit"])) for r in rows]
            buckets = defaultdict(list)
            for key, row in zip(value_of, rows):
                buckets[key].append(int(row["id"]))
            by_id = {int(r["id"]): r for r in rows}
            for ids in buckets.values():
                clusters: list[list[int]] = []
                for cid in ids:
                    pk = period_key(by_id[cid]["effective_period"])
                    for cluster in clusters:
                        if same_period(period_key(by_id[cluster[0]]["effective_period"]), pk):
                            cluster.append(cid)
                            break
                    else:
                        clusters.append([cid])
                for cluster in clusters:
                    union_cross(cluster)

            components: dict[int, list[int]] = defaultdict(list)
            for i in parent:
                components[find(i)].append(i)
            losers: list[int] = []
            winners: dict[int, list[int]] = {}
            for ids in components.values():
                if len(ids) < 2:
                    continue
                ranked = sorted(ids, key=lambda i: (
                    str(by_id[i]["known_at"] or "9999"),
                    0 if by_id[i]["status"] == "verified" else 1,
                    -len(str(by_id[i]["context"] or "")),
                    0 if by_id[i]["method"] == "script" else 1,
                    i))
                keep, folded = ranked[0], sorted(ranked[1:])
                winners[keep] = folded
                losers.extend(folded)
            if losers:
                self.con.executemany("DELETE FROM claim WHERE id=?", [(i,) for i in losers])
            for keep, folded in winners.items():
                current = str(self.con.execute("SELECT dup_of FROM claim WHERE id=?", (keep,)).fetchone()[0]
                              or "")
                merged = sorted({int(x) for x in current.split(",") if x.strip().isdigit()} | set(folded))
                self.con.execute("UPDATE claim SET dup_of=? WHERE id=?",
                                 (",".join(str(i) for i in merged), keep))
            self.con.commit()
        return len(losers), len(winners)

    def close(self) -> None:
        with self.lock:
            self.con.commit()
            self.con.close()


# ------------------------------------------------------------------ the model client
class Client:
    """One OpenCode Go chat client.  Extraction and judging use the same shape, different model/body/session."""

    def __init__(self, model: str, body: dict[str, Any], job: str, timeout: float = 300.0) -> None:
        import requests
        from requests.adapters import HTTPAdapter

        from reality_engine.scripts.go_session import session_id

        from reality_engine.scripts.resource_watchdog import user_env  # key lives in the registry (never printed)

        key = user_env().get("OPENCODE_GO_API_KEY", "")
        if not key:
            raise SystemExit("OPENCODE_GO_API_KEY is not set in the environment")
        self.model, self.body = model, body
        self.session_id = session_id(job, model, key)
        self.http = requests.Session()
        self.http.mount("https://", HTTPAdapter(pool_connections=8, pool_maxsize=512))
        self.key = key
        self.timeout = timeout

    def chat(self, prompt: str) -> tuple[int, str, tuple[int, int]]:
        body = {"model": self.model, **self.body, "messages": [{"role": "user", "content": prompt}]}
        headers = {"Authorization": f"Bearer {self.key}", "Content-Type": "application/json",
                   "x-opencode-session": self.session_id, "User-Agent": "reality-engine-t228/1.0"}
        try:
            r = self.http.post(f"{BASE}/chat/completions", headers=headers, json=body, timeout=self.timeout)
        except Exception as e:  # requests.RequestException, but a socket error must not kill the batch
            return -1, f"{type(e).__name__}: {e}"[:300], (0, 0)
        if r.status_code != 200:
            return r.status_code, r.text[:600], (0, 0)
        try:
            j = r.json()
        except ValueError:
            return 502, r.text[:600], (0, 0)
        if not j.get("choices"):
            return 502, r.text[:600], (0, 0)
        usage = j.get("usage") or {}
        text = j["choices"][0].get("message", {}).get("content") or ""
        return 200, text, (int(usage.get("prompt_tokens") or 0), int(usage.get("completion_tokens") or 0))


# ------------------------------------------------------------------ one extraction batch
class Stats:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.requests = 0
        self.empty = 0
        self.errors = 0
        self.claims = 0
        self.items_ok = 0
        self.in_tok = 0
        self.out_tok = 0
        self.seconds = 0.0
        self.judge_requests = 0
        self.judged = 0
        self.judged_ok = 0
        self.judge_errors = 0
        self.judge_in_tok = 0
        self.judge_out_tok = 0
        self.judge_seconds = 0.0
        self.drops: Counter[str] = Counter()
        self.by_node: Counter[str] = Counter()
        self.by_status: Counter[str] = Counter()
        self.by_kind: Counter[str] = Counter()
        self.by_field: Counter[str] = Counter()
        self.judge_http_codes: Counter[str] = Counter()
        self.empty_samples: list[str] = []

    def add(self, sample: str | None = None, **kw: Any) -> None:
        with self.lock:
            for k, v in kw.items():
                if isinstance(v, Counter):
                    getattr(self, k).update(v)
                else:
                    setattr(self, k, getattr(self, k) + v)
            if sample is not None:
                self.empty_samples.append(sample)

    def merge(self, other: "Stats") -> None:
        with self.lock:
            for k in ("requests", "empty", "errors", "claims", "items_ok", "in_tok", "out_tok", "seconds",
                      "judge_requests", "judged", "judged_ok", "judge_errors", "judge_in_tok",
                      "judge_out_tok", "judge_seconds"):
                setattr(self, k, getattr(self, k) + getattr(other, k))
            for k in ("drops", "by_node", "by_status", "by_kind", "by_field", "judge_http_codes"):
                getattr(self, k).update(getattr(other, k))
            self.empty_samples.extend(other.empty_samples)


def _record_http(writer: Writer, run_id: str, role: str, store: str, started: str, ended: str,
                 seconds: float, status: int, usage: tuple[int, int], items: int, claims: int,
                 outcomes: dict[str, int] | None, items_done: list[str] | None, in_flight: int,
                 attempt: int, error: str = "") -> None:
    writer.read_log(run_id, store, attempt, started, ended, seconds, status, usage[0], usage[1], items,
                    claims, outcomes, items_done, in_flight, error=error, role=role)


def process_batch(batch: list[dict[str, Any]], client: Any, writer: Writer, limiter: Adaptive,
                  run_id: str, brief: str = "") -> Stats:
    """One extraction batch: one successful request (plus retries).  Never raises on a bad reply."""
    stats = Stats()
    store = batch[0]["store"]
    prompt = build_prompt(batch, brief)
    ids = {it["id"]: it for it in batch}
    transport = 0
    json_tries = 0
    while True:
        started = utc_now()
        t0 = time.monotonic()
        try:
            limiter.acquire()
        except Stopped:
            stats.add(errors=1)
            return stats
        in_flight = limiter.active
        try:
            status, text, usage = client.chat(prompt)
        finally:
            limiter.release()
        seconds = time.monotonic() - t0
        ended = utc_now()
        ok = status == 200 and bool(text.strip())
        stats.add(requests=1, seconds=seconds, in_tok=usage[0], out_tok=usage[1])
        if status == 200 and not text.strip():
            stats.add(empty=1, sample=text[:600] or "<empty body>")

        items: list[dict[str, Any]] = []
        parse_err = ""
        if status == 200 and text.strip():
            try:
                items = parse_reply(text)
            except (ValueError, TypeError) as e:
                parse_err = f"{type(e).__name__}: {e}"[:300]

        if status == 429:
            writer.quota_event(run_id, store, status, in_flight, text)
            limiter.halve()
        elif status == -1 or status >= 500:
            writer.quota_event(run_id, store, status, in_flight, text)

        if not ok:
            limiter.saw(False)
            transport += 1
            _record_http(writer, run_id, "extract", store, started, ended, seconds, status, usage,
                         len(batch), 0, None, None, in_flight, transport, error=text[:300])
            if status == 429:
                time.sleep(5.0)
            if transport >= MAX_TRANSPORT_TRIES:
                stats.add(errors=1)
                return stats
            if status != 429:
                time.sleep(min(2.0 ** transport, 30.0))
            continue

        limiter.saw(True)
        if parse_err:
            json_tries += 1
            _record_http(writer, run_id, "extract", store, started, ended, seconds, status, usage,
                         len(batch), 0, None, None, in_flight, transport + json_tries, error=parse_err)
            if json_tries >= 2:
                stats.add(errors=1)
                return stats
            continue

        # parsed: turn each item into claims and store them
        claims: list[dict[str, Any]] = []
        outcomes: Counter[str] = Counter()
        by_node: Counter[str] = Counter()
        by_status: Counter[str] = Counter()
        by_kind: Counter[str] = Counter()
        for raw in items:
            try:
                rid = int(raw["id"]) if raw.get("id") is not None else -1
            except (TypeError, ValueError):
                outcomes["bad_id"] += 1
                continue
            item = ids.get(rid)
            if item is None:
                outcomes["unknown_id"] += 1
                continue
            raws = raw.get("claims") or []
            if not isinstance(raws, list):
                raws = []
            got = 0
            for rc in raws:
                if not isinstance(rc, dict):
                    outcomes["bad_claim"] += 1
                    continue
                claim, reason = claim_from_reply(rc, item)
                if claim is None:
                    outcomes[reason] += 1
                    continue
                if claim["effective_period"] is None and item.get("target_period"):
                    # a guidance row's own target period is part of the source row, not a computed number
                    claim["effective_period"] = _clean(item["target_period"], 60)
                claims.append(claim)
                by_node[claim["node"]] += 1
                by_status[claim["status"]] += 1
                by_kind[str(claim.get("source_kind") or "")] += 1
                got += 1
            outcomes["claims" if got else _drop_of(raw)] += 1
        done = sorted(it["key"] for it in batch)
        writer.insert_claims(run_id, claims)
        _record_http(writer, run_id, "extract", store, started, ended, seconds, status, usage,
                     len(batch), len(claims), dict(outcomes), done, in_flight, transport + json_tries)
        stats.add(claims=len(claims), items_ok=len(batch), drops=outcomes, by_node=by_node,
                  by_status=by_status, by_kind=by_kind)
        return stats


# ------------------------------------------------------------------ the judge phase
def judge_batch(batch: list[dict[str, Any]], client: Any, writer: Writer, limiter: Adaptive,
                run_id: str, brief: str = "") -> Stats:
    """Judge one group of claims (same store): all six fields true or the claim is unverified.

    Up to MAX_JUDGE_TRIES attempts (two retries) with backoff; the HTTP code of every attempt is counted.
    A reply whose JSON is broken is first read item by item (tolerant parse), then retried.
    """
    stats = Stats()
    store = batch[0]["store"]
    prompt = judge_prompt(batch, brief)
    ids = {int(c["id"]): c for c in batch}
    attempt = 0
    while True:
        attempt += 1
        started = utc_now()
        t0 = time.monotonic()
        try:
            limiter.acquire()
        except Stopped:
            writer.mark_judge_failed(list(ids))
            stats.add(judge_errors=len(ids), judged=len(ids))
            return stats
        in_flight = limiter.active
        try:
            status, text, usage = client.chat(prompt)
        finally:
            limiter.release()
        seconds = time.monotonic() - t0
        ended = utc_now()
        ok = status == 200 and bool(text.strip())
        stats.add(judge_requests=1, judge_seconds=seconds, judge_in_tok=usage[0], judge_out_tok=usage[1],
                  judge_http_codes=Counter({str(status): 1}))

        verdicts: list[dict[str, Any]] = []
        exhausted = False
        if ok:
            verdicts = parse_judge_reply(text)
            if not verdicts:
                exhausted = True
                text = "no judge verdicts in reply: " + text[:280]

        if status == 429:
            writer.quota_event(run_id, store, status, in_flight, text)
            limiter.halve()
        elif status == -1 or status >= 500:
            writer.quota_event(run_id, store, status, in_flight, text)

        if not ok or exhausted:
            limiter.saw(False)
            _record_http(writer, run_id, "judge", store, started, ended, seconds, status, usage,
                         len(batch), 0, None, None, in_flight, attempt, error=text[:300])
            if attempt >= MAX_JUDGE_TRIES:
                writer.mark_judge_failed(list(ids))
                stats.add(judge_errors=len(ids), judged=len(ids), by_field=Counter({"judge_error": len(ids)}))
                return stats
            time.sleep(5.0 if status == 429
                       else JUDGE_BACKOFF_S[min(attempt - 1, len(JUDGE_BACKOFF_S) - 1)])
            continue

        limiter.saw(True)
        by_field: Counter[str] = Counter()
        seen = 0
        ok_count = 0
        seen_ids: set[int] = set()
        ordered_ids = [int(c["id"]) for c in batch]
        for pos, verdict in enumerate(verdicts):
            cid_value = verdict.get("id")
            if cid_value is None:
                continue
            try:
                cid = int(cid_value)
            except (TypeError, ValueError):
                continue
            if cid not in ids:
                # the judge sometimes numbers the blocks 1..n instead of echoing the id: fall back to the
                # block position, which is the order judge_prompt wrote them in
                cid = ordered_ids[pos] if pos < len(ordered_ids) else -1
            if cid not in ids or cid in seen_ids:
                continue
            seen_ids.add(cid)
            fails = [f for f in JUDGE_FIELDS if not verdict.get(f)]
            writer.apply_judge(cid, verdict)
            seen += 1
            by_field.update(fails)
            ok_count += 0 if fails else 1
        for cid in set(ids) - seen_ids:
            writer.mark_judge_failed([cid])
            by_field["judge_error"] += 1
            seen += 1
        _record_http(writer, run_id, "judge", store, started, ended, seconds, status, usage,
                     len(batch), seen, {"judged_ok": ok_count}, None, in_flight, attempt)
        stats.add(judged=seen, judged_ok=ok_count, judge_errors=len(set(ids) - seen_ids),
                  by_field=by_field)
        return stats


def dedupe_db(writer: Writer) -> int:
    return writer.dedupe()


# ------------------------------------------------------------------ run
def build_items(stores: list[str], doc_types: tuple[str, ...] = ()) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Every candidate item across ``stores``: guidance rows (unmapped only) + forward transcript statements
    + ``doc_page`` paragraphs of ``doc_types`` (stage 2a).  Fully script-parsed announcements become claims."""
    items: list[dict[str, Any]] = []
    counters: Counter[str] = Counter()
    guidance_claims: list[dict[str, Any]] = []
    script_claims: list[dict[str, Any]] = []
    per_store: list[dict[str, Any]] = []
    for store in stores:
        if not store_path(store).exists():
            counters["store_missing"] += 1
            continue
        g_rows = guidance_rows(store)
        mapped = unmapped = novalue = 0
        for row in g_rows:
            claim, reason = guidance_claim(store, row)
            counters[f"guidance_{reason}"] += 1
            if claim is not None:
                guidance_claims.append(claim)
                mapped += 1
                continue
            if reason == "unmapped":
                unmapped += 1
                items.append(item_from_guidance(store, row))
            elif reason == "no_value":
                novalue += 1
        rows = [{**row, "_store": store} for row in statement_rows(store)]
        statement_items, sc = attach_context(rows, question_rows(store))
        items.extend(statement_items)
        pers = {"store": store, "guidance": len(g_rows), "guidance_mapped": mapped,
                "guidance_unmapped": unmapped, "guidance_no_value": novalue}
        for key in ("statements_with_numbers", "statements_fragment", "statements_no_numbers",
                    "statements_no_cue", "statements_sent"):
            pers[key] = sc.get(key, 0)
        counters.update(sc)
        if doc_types:
            doc_it, doc_claims, doc_counts = doc_items(store, tuple(doc_types))
            items.extend(doc_it)
            script_claims.extend(doc_claims)
            counters.update(doc_counts)
            pers.update(doc_counts)
        per_store.append(pers)
    script_claims.extend(guidance_claims)
    for n, item in enumerate(items, 1):
        item["id"] = n
    return items, {"counters": dict(counters), "guidance_claims": guidance_claims,
                   "script_claims": script_claims, "per_store": per_store}



def batch_items(items: list[dict[str, Any]], size: int) -> list[list[dict[str, Any]]]:
    return [items[i:i + size] for i in range(0, len(items), size)]


def pending_items(items: list[dict[str, Any]], done: set[str]) -> list[dict[str, Any]]:
    """Resume: skip every item whose request already succeeded (its key is in ``read_log.items_done``)."""
    return [it for it in items if it["key"] not in done]


def _ledger(stores: list[str], stats: Stats, started: str, outcome: str) -> None:
    """One ledger run row, same shape as page_reader._ledger; never fatal."""
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return
    try:
        from reality_engine.scripts import run_ledger

        led = run_ledger.connect()
        run_ledger._store_run(led, {
            "run_id": f"driver_claims-{datetime.now():%Y%m%dT%H%M%S}", "kind": "driver_claims",
            "ticket": "T-228", "title": f"driver claims {len(stores)} stores, {stats.items_ok} items",
            "model": f"{MODEL}+{JUDGE_MODEL}", "host": "msi", "started_at": started, "ended_at": utc_now(),
            "seconds": stats.seconds + stats.judge_seconds, "in_tok": stats.in_tok + stats.judge_in_tok,
            "out_tok": stats.out_tok + stats.judge_out_tok, "items": stats.items_ok, "outcome": outcome,
            "source": str(STORE_ROOT),
        }, [])
        led.commit()
        led.close()
    except Exception as e:  # the ledger is a report hook, never the work
        print(f"run ledger not written: {type(e).__name__}: {e}")


def run_judge(writer: Writer, briefs: dict[str, str], args: argparse.Namespace, run_id: str) -> Stats:
    """The judge phase: every claim that passed the script check is read again by the independent model."""
    stats = Stats()
    todo = writer.claims_to_judge()
    if not todo:
        return stats
    jl = Adaptive(args.judge_start)
    jclient = Client(JUDGE_MODEL, JUDGE_BODY, "t228-judge")
    by_store: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for claim in todo:
        by_store[str(claim["store"])].append(claim)
    jbatches = [b for store_claims in by_store.values()
                for b in batch_items(store_claims, max(1, args.judge_batch))]
    workers = min(len(jbatches), max(1, args.judge_start))
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="t228j") as ex:
        futures = [ex.submit(judge_batch, b, jclient, writer, jl, run_id,
                             briefs.get(str(b[0]["store"]), "")) for b in jbatches]
        for f in futures:
            try:
                stats.merge(f.result())
            except Stopped:
                continue
    return stats


def run(args: argparse.Namespace) -> int:
    started = utc_now()
    stores = list(args.stores or [])
    if getattr(args, "all_stores", False):
        stores = list_stores()
    if args.pick:
        extra = pick_stores([s for s in stores_with_statements() if s not in stores], args.pick, args.pick_seed)
        print(f"picked by seed {args.pick_seed}: {' '.join(extra)}")
        stores += extra
    if args.pick_no_transcript:
        extra = pick_stores([s for s in stores_without_transcripts() if s not in stores],
                            args.pick_no_transcript, args.pick_seed)
        print(f"picked without transcripts by seed {args.pick_seed}: {' '.join(extra)}")
        stores += extra
    if not stores:
        stores = active_stores()
    out = Path(args.out)
    if args.judge_only:
        briefs = {store: company_brief(store) for store in stores if store_path(store).exists()}
        writer = Writer(out)
        reset = writer.reset_judge_errors()
        judge_stats = run_judge(writer, briefs, args, f"t228-judge-{datetime.now():%Y%m%dT%H%M%S}")
        final = {str(r[0]): int(r[1]) for r in
                 writer.con.execute("SELECT status, COUNT(*) FROM claim GROUP BY 1").fetchall()}
        print(f"judge-only: reset {reset} judge_error claims; {judge_stats.judge_requests} requests, "
              f"{judge_stats.judge_seconds:.0f} s, {judge_stats.judged} judged, {judge_stats.judged_ok} passed, "
              f"errors {judge_stats.judge_errors}, http {dict(judge_stats.judge_http_codes)}, "
              f"fail fields {dict(judge_stats.by_field)}")
        print(f"claims after judge: {sum(final.values())}  by status {final}")
        _ledger(stores, judge_stats, started, f"judge-only: {dict(final)}")
        writer.close()
        return 0
    items, built = build_items(stores, tuple(args.doc_types or ()))
    counters = built["counters"]
    script_claims: list[dict[str, Any]] = built["script_claims"]
    briefs = {store: company_brief(store) for store in stores if store_path(store).exists()}

    out = Path(args.out)
    writer = Writer(out)
    run_id = f"t228-{datetime.now():%Y%m%dT%H%M%S}"
    writer.clear_script(stores)
    writer.insert_claims(run_id, script_claims)
    done = writer.done_keys()
    pending = pending_items(items, done)
    if args.max_items:
        pending = pending[:args.max_items]
    by_store_pending: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in pending:
        by_store_pending[str(item["store"])].append(item)
    batches = [b for store in sorted(by_store_pending)
               for b in batch_items(by_store_pending[store], max(1, args.batch))]

    build_file = out.with_suffix(".build.json")
    build_file.parent.mkdir(parents=True, exist_ok=True)
    build_file.write_text(json.dumps({"counters": counters, "per_store": built["per_store"],
                                      "stores": stores, "model_items": len(pending)},
                                     indent=1)[:4_000_000], encoding="utf-8")

    print(f"stores: {len(stores)}  script claims: {len(script_claims)}  model items: {len(pending)}"
          f" ({len(done)} already done)  batches: {len(batches)}  docs: {','.join(args.doc_types or ()) or 'none'}")
    print(f"build counts: {build_file}")
    for store in sorted(briefs):
        print(f"  brief {store}: {briefs[store]}")
    for p in built["per_store"]:
        print(f"  {p['store']}: guidance {p['guidance']} (mapped {p['guidance_mapped']}, unmapped "
              f"{p['guidance_unmapped']}, no value {p['guidance_no_value']}); statements with numbers "
              f"{p['statements_with_numbers']} -> sent {p['statements_sent']} (fragment "
              f"{p['statements_fragment']}, no numbers {p['statements_no_numbers']}, "
              f"no cue {p['statements_no_cue']})")
        doc_bits = [f"{dt} docs {p.get(f'doc_{dt}_docs', 0)} pages {p.get(f'doc_{dt}_pages', 0)} "
                    f"kept {p.get(f'doc_{dt}_kept', 0)} script {p.get(f'doc_{dt}_script', 0)}"
                    for dt in (args.doc_types or ())]
        if doc_bits:
            print(f"    docs {p['store']}: " + "; ".join(doc_bits))
    if args.dry_run:   # the filter counts with no model call (and the script claims still land in --out)
        print("dry run: no request sent")
        writer.close()
        return 0

    limiter = Adaptive(args.start, args.unleashed)
    if args.unleashed:
        limiter.start_monitor()
    stats = Stats()
    guard_reason = ""

    if batches:
        client = Client(MODEL, MODEL_BODY, "t228-driver-claims")
        workers = min(len(batches), max(1, args.max_workers))
        try:
            with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="t228") as ex:
                futures = [ex.submit(process_batch, b, client, writer, limiter, run_id,
                                     briefs.get(str(b[0]["store"]), "")) for b in batches]
                for f in futures:
                    try:
                        stats.merge(f.result())
                    except Stopped:
                        continue
                    if stats.requests >= 10 and stats.empty / max(stats.requests, 1) > EMPTY_STOP_SHARE:
                        guard_reason = (f"empty answers {stats.empty}/{stats.requests} "
                                        f"> {EMPTY_STOP_SHARE:.0%}: stopped")
                        limiter.stopped.set()
        finally:
            limiter.stop_monitor()

    # judge: every claim that passed the script check is read again by an independent model
    judge_stats = run_judge(writer, briefs, args, run_id)
    removed = dedupe_db(writer)
    folded, dup_rows = writer.dedupe_cross_source()
    final_rows = writer.con.execute("SELECT status, COUNT(*) FROM claim GROUP BY 1").fetchall()
    final_status = {str(r[0]): int(r[1]) for r in final_rows}

    # Empty answers are a known hy4 failure; keep 5 raw responses for the report.
    if guard_reason:
        sample = out.parent / "empty_samples.json"
        sample.write_text(json.dumps(stats.empty_samples[:5], indent=1)[:8000], encoding="utf-8")

    script_status = Counter(c["status"] for c in script_claims)
    total_claims = len(script_claims) + stats.claims - removed - folded
    statuses = Counter(script_status)
    statuses.update(stats.by_status)
    nodes = Counter(c["node"] for c in script_claims)
    nodes.update(stats.by_node)
    kinds = Counter(str(c.get("source_kind") or "guidance") for c in script_claims)
    kinds.update(stats.by_kind)
    sent_items = len(pending)
    dropped = sum(stats.drops[k] for k in ("past", "no_driver"))
    outcome = (f"claims {total_claims} ({statuses.get('verified', 0)} pre-judge verified, "
               f"{statuses.get('unverified', 0)} pre-judge unverified, "
               f"{statuses.get('quarantined', 0)} quarantined); judged {judge_stats.judged} "
               f"({judge_stats.judged_ok} passed); deduped {removed}; cross-source folded {folded}; "
               f"model items {stats.items_ok}/{sent_items}; drops {dict(stats.drops)}"
               + (f"; {guard_reason}" if guard_reason else ""))
    print(f"\nextract: {stats.requests} requests, {stats.seconds:.0f} s, {stats.in_tok} in / "
          f"{stats.out_tok} out tokens, {stats.errors} errors, {stats.empty} empty")
    print(f"judge: {judge_stats.judge_requests} requests, {judge_stats.judge_seconds:.0f} s, "
          f"{judge_stats.judge_in_tok} in / {judge_stats.judge_out_tok} out tokens, "
          f"{judge_stats.judged} claims judged, {judge_stats.judged_ok} passed, "
          f"errors {judge_stats.judge_errors}, http {dict(judge_stats.judge_http_codes)}, "
          f"fail fields {dict(judge_stats.by_field)}")
    print(f"claims pre-judge: {len(script_claims) + stats.claims}  by status {dict(statuses)}  "
          f"by node {dict(nodes)}  by source {dict(kinds)}  deduped {removed}  "
          f"cross-source folded {folded} ({dup_rows} rows carry dup_of)")
    print(f"claims after judge+dedupe: {sum(final_status.values())}  by status {final_status}")
    print(f"drops (model items): {dict(stats.drops)}  no_driver+past share "
          f"{(dropped / max(stats.items_ok, 1)):.1%} of {stats.items_ok} items")
    print(f"filter: {dict(counters)}")
    if guard_reason:
        print(f"STOPPED: {guard_reason}")
    _ledger(stores, stats, started, outcome)
    writer.close()
    return 0


# ------------------------------------------------------------------ report
def _restore_moved_claim(claim: dict[str, Any], row: sqlite3.Row) -> tuple[str, str]:
    """Node and status for a revenue.mix claim the clause rule does not support, back as before the move."""
    clause = number_clause(claim)
    if row["judge_suggest"] and row["judge_suggest"] != "revenue.mix":
        node = str(row["judge_suggest"])
        claim["node"] = node
        status, reason = "unverified", "judge_renode"
    elif MARGIN_WORD.search(clause):
        node = "margin.gross" if re.search(r"\bgross\b", clause, re.I) else "margin.ebitda"
        claim["node"] = node
        status, reason = _status_before_retag(claim, row)
    else:
        node = "revenue.total"
        claim["node"] = node
        status, reason = _status_before_retag(claim, row)
    if status == "verified" and range_truncated(claim):
        status, reason = "unverified", "range_truncated"
    return status, reason


def _status_before_retag(claim: dict[str, Any], row: sqlite3.Row) -> tuple[str, str]:
    if row["judge_ok"] == 1:
        return "verified", ""
    if row["judge_ok"] == 0:
        fail = str(row["judge_fail"] or "")
        return "unverified", ("judge_error" if fail == "judge_error" else "judge:" + fail)
    return verify_claim(claim)


def retag_existing(path: Path) -> int:
    """Round-5/6 re-tag of an existing claims DB.

    First put back every claim the earlier mix re-tag moved without the clause rule supporting it (a
    margin or change clause is not a mix), then apply ``revenue.mix`` and the list/range rule afresh.
    A claim moved by the rule keeps its status only when the judge's ``node_suggest`` named revenue.mix;
    a truncated list always becomes unverified (``range_truncated``).  Quarantined claims are untouched.
    """
    con = sqlite3.connect(str(path))
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT id, node, segment, unit, value_low, value_high, quote_span, statement, status,"
        " status_reason, judge_suggest, judge_ok, judge_fail, store, sign FROM claim").fetchall()
    restored = restored_status = moved = truncated = downgraded = 0
    for r in rows:
        if r["status"] == "quarantined":
            continue
        claim: dict[str, Any] = {k: r[k] for k in ("node", "segment", "unit", "value_low", "value_high",
                                                   "quote_span", "statement")}
        status, reason = str(r["status"]), str(r["status_reason"] or "")
        changed = False
        already_truncated = reason == "range_truncated"
        was_verified = status == "verified"
        if (r["node"] == "revenue.mix" and reason in ("mix_retag", "range_truncated")
                and not mix_should_fire(claim)):
            new_status, new_reason = _restore_moved_claim(claim, r)
            restored += 1
            restored_status += 0 if new_status == status else 1
            status, reason = new_status, new_reason
            changed = True
        elif mix_node(claim):
            moved += 1
            changed = True
            if r["judge_suggest"] != "revenue.mix":
                status, reason = "unverified", "mix_retag"
        if range_truncated(claim):
            if not already_truncated:
                truncated += 1
            status, reason = "unverified", "range_truncated"
            changed = True
        if not changed:
            continue
        if was_verified and status != "verified":
            downgraded += 1
        con.execute("UPDATE claim SET node=?, segment=?, status=?, status_reason=? WHERE id=?",
                    (claim["node"], claim["segment"], status, reason, r["id"]))
    con.commit()
    statuses = {str(a): int(b) for a, b in con.execute("SELECT status, COUNT(*) FROM claim GROUP BY 1")}
    nodes = {str(a): int(b) for a, b in
             con.execute("SELECT node, COUNT(*) FROM claim GROUP BY 1 ORDER BY 1")}
    con.close()
    print(f"retag: restored from revenue.mix {restored} (status changed {restored_status}), "
          f"moved {moved}, range_truncated {truncated}, downgraded {downgraded}")
    print(f"status after: {statuses}")
    print(f"nodes after: {nodes}")
    return 0


def _row_col(row: sqlite3.Row, name: str, default: Any = None) -> Any:
    """A column that an older claims DB may not have yet (stage-2a additive columns)."""
    try:
        return row[name]
    except (IndexError, KeyError):
        return default


def _coverage(rows: list[sqlite3.Row]) -> tuple[set[str], set[str], set[tuple[str, str]]]:
    """Verified-claim coverage: companies, distinct calendar months and (company, month) pairs."""
    symbols: set[str] = set()
    months: set[str] = set()
    pairs: set[tuple[str, str]] = set()
    for r in rows:
        if str(r["status"]) != "verified":
            continue
        symbol = str(r["symbol"] or "")
        known = str(r["known_at"] or "")[:7]
        symbols.add(symbol)
        if known:
            months.add(known)
            pairs.add((symbol, known))
    return symbols, months, pairs


def open_readonly_db(path: Path) -> sqlite3.Connection:
    """Open a finished claims DB read-only; a file the sandbox will not lock is opened with ``immutable=1``."""
    uri = f"file:{Path(path).as_posix()}?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    try:
        con.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()
    except sqlite3.OperationalError:
        con.close()
        con = sqlite3.connect(uri + "&immutable=1", uri=True)
    con.row_factory = sqlite3.Row
    return con


def report(path: Path, seed: int = 53, n: int = 40, rejected_n: int = 10, renode_n: int = 15,
           baseline: str = "", build_json: str = "") -> list[str]:
    """The full report as text lines: counts, judge agreement, seeded samples, then detail.

    ``baseline`` (another claims DB) adds the stage-2a coverage gain: companies and months with a verified
    claim here that the baseline lacks.  ``build_json`` (written by ``run``) adds the item-builder counts.
    """
    con = open_readonly_db(Path(path))
    rows = con.execute("SELECT * FROM claim").fetchall()
    logs = con.execute("SELECT role, http_status, COUNT(*) n, SUM(error<>'') errs FROM read_log "
                       "GROUP BY 1,2 ORDER BY 1,2").fetchall()
    per_store = con.execute("SELECT store, status, COUNT(*) n FROM claim GROUP BY 1,2 ORDER BY 1,2").fetchall()
    quota = con.execute("SELECT at_ist, http_status, in_flight, substr(body, 1, 140) body "
                        "FROM quota_event ORDER BY id").fetchall()
    peak = int(con.execute("SELECT COALESCE(MAX(in_flight), 0) FROM read_log").fetchone()[0])
    con.close()
    statuses = Counter(r["status"] for r in rows)
    nodes = Counter(r["node"] for r in rows)
    methods = Counter(r["method"] for r in rows)
    kinds = Counter(str(_row_col(r, "source_kind") or "") for r in rows)
    scopes = Counter(str(_row_col(r, "speaker_scope") or "company") for r in rows)
    third_party = sum(1 for r in rows if r["status_reason"] == "third_party")
    folded = sum(len([part for part in str(_row_col(r, "dup_of") or "").split(",") if part.strip()])
                 for r in rows)
    scope_failed = sum(1 for r in rows if "scope_ok" in str(r["judge_fail"] or ""))
    judged = [r for r in rows if r["judge_ok"] is not None]
    agreed = [r for r in judged if r["judge_ok"] == 1]
    fails = Counter()
    for r in judged:
        for field in (r["judge_fail"] or "").split(","):
            if field:
                fails[field] += 1
    store_counts: dict[str, dict[str, int]] = {}
    for r in per_store:
        store_counts.setdefault(str(r["store"]), {})[str(r["status"])] = int(r["n"])
    out: list[str] = [
        f"claims: {len(rows)}  status {dict(statuses)}  method {dict(methods)}",
        f"source kinds: {dict(kinds)}",
        f"speaker scope: {dict(scopes)}  third-party (unverified, never the company's claim): {third_party}",
        f"cross-source folded: {folded} claims (earliest known_at row kept, others' ids in dup_of); "
        f"scope_ok failures: {scope_failed}",
        f"unjudged (script check only, the judge did not run): {sum(1 for r in rows if r['judge_ok'] is None)}",
        f"judged {len(judged)}  judge agreed {len(agreed)} ({len(agreed) / max(len(judged), 1):.0%})  "
        f"judge fail fields {dict(fails)}",
        "read requests by role/status: " + "; ".join(
            f"{r['role']} {r['http_status']} x{r['n']} (errors {r['errs']})" for r in logs),
        f"judge-error claims: {sum(1 for r in rows if r['judge_fail'] == 'judge_error')}  "
        f"judge-renoded: {sum(1 for r in rows if r['status_reason'] == 'judge_renode')}  "
        f"peak in-flight: {peak}",
        "per store: " + "; ".join(
            f"{store} " + ",".join(f"{status[:4]}{n}" for status, n in sorted(counts.items()))
            for store, counts in sorted(store_counts.items())),
        f"quota events: {len(quota)} (HTTP 429: "
        f"{sum(1 for q in quota if int(q['http_status'] or 0) == 429)})",
    ]
    out += [f"  quota {q['at_ist']} HTTP {q['http_status']} in_flight {q['in_flight']} body {q['body']}"
            for q in quota]

    if build_json and Path(build_json).exists():
        try:
            build = json.loads(Path(build_json).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            build = {}
        counters = build.get("counters") or {}
        out.append("\nitems per doc type (from the builder; model item = a paragraph sent to the model):")
        out.append(f"  transcript: statements sent {counters.get('statements_sent', 0)}")
        out.append(f"  guidance: {counters.get('guidance_mapped', 0)} mapped script claims, "
                   f"{counters.get('guidance_unmapped', 0)} unmapped -> model, "
                   f"{counters.get('guidance_no_value', 0)} no value")
        for dt in DOC_TYPES:
            out.append(
                f"  {dt}: docs {counters.get(f'doc_{dt}_docs', 0)}, pages {counters.get(f'doc_{dt}_pages', 0)} "
                f"(ocr {counters.get(f'doc_{dt}_pages_ocr', 0)}), paragraphs {counters.get(f'doc_{dt}_paragraphs', 0)}, "
                f"model items {counters.get(f'doc_{dt}_kept', 0)}, script claims {counters.get(f'doc_{dt}_script', 0)}; "
                f"drops pages no-cue {counters.get(f'doc_{dt}_drop_no_cue', 0)} no-number "
                f"{counters.get(f'doc_{dt}_drop_no_number', 0)} short {counters.get(f'doc_{dt}_drop_short', 0)}; "
                f"paragraphs boilerplate {counters.get(f'doc_{dt}_para_boilerplate', 0)} no-cue "
                f"{counters.get(f'doc_{dt}_para_no_cue', 0)} no-number {counters.get(f'doc_{dt}_para_no_number', 0)}")

    pilot_symbols, pilot_months, pilot_pairs = _coverage(rows)
    if baseline and Path(baseline).exists():
        bcon = open_readonly_db(Path(baseline))
        brows = bcon.execute("SELECT symbol, known_at, status FROM claim").fetchall()
        bcon.close()
        base_symbols, base_months, base_pairs = _coverage(brows)
        gained = sorted(pilot_symbols - base_symbols)
        per_symbol = Counter(str(r["symbol"] or "") for r in rows if r["status"] == "verified")
        out.append(f"\ncoverage gain vs baseline {Path(baseline).name}:")
        out.append(f"  companies with a verified claim: baseline {len(base_symbols)} -> pilot "
                   f"{len(pilot_symbols)}; gained {len(gained)}")
        out.append(f"  months gained: {len(pilot_months - base_months)} "
                   f"({', '.join(sorted(pilot_months - base_months)) or 'none'})")
        out.append(f"  company-months gained: {len(pilot_pairs - base_pairs)}")
        out.append("  companies gained: " + (", ".join(f"{s} ({per_symbol[s]})" for s in gained) or "none"))
    else:
        out.append(f"\ncoverage: {len(pilot_symbols)} companies, {len(pilot_months)} months "
                   f"({', '.join(sorted(pilot_months))}) with a verified claim")

    rng = random.Random(seed)
    by_node: dict[str, list[sqlite3.Row]] = {}
    for r in rows:
        if r["status"] == "verified":
            by_node.setdefault(r["node"], []).append(r)
    order = sorted(by_node)
    rng.shuffle(order)
    for group in by_node.values():
        rng.shuffle(group)
    sample: list[sqlite3.Row] = []
    while len(sample) < n and any(by_node[k] for k in order):
        for node in order:
            if by_node[node] and len(sample) < n:
                sample.append(by_node[node].pop())
    out.append(f"\n{len(sample)} random VERIFIED claims, seed {seed} (round-robin across nodes; full paragraph; "
               f"pre-judge where the judge did not run):")
    for r in sample:
        lo = f"{r['value_low']:g}" if r["value_low"] is not None else "?"
        hi = f"-{r['value_high']:g}" if r["value_high"] is not None else ""
        ctx = (" | CTX: " + " || ".join(str(r["context"]).splitlines())) if r["context"] else ""
        source = _row_col(r, "source_kind") or "?"
        where = f" | {Path(str(r['doc_key'] or '')).name} p{r['page']}" if r["doc_key"] else ""
        out.append(f"[{r['store']}] {r['node']} {r['sign']} {lo}{hi} {r['unit']} | source={source} "
                   f"| period={r['effective_period']}{where} | STATEMENT: {norm_ws(r['statement'])}{ctx}")

    rej = [r for r in rows if r["judge_ok"] == 0 and (r["judge_fail"] or "")]
    rng.shuffle(rej)
    out.append(f"\n{rejected_n} random JUDGE-REJECTED claims (first {min(rejected_n, len(rej))} of {len(rej)}):")
    for r in rej[:rejected_n]:
        lo = f"{r['value_low']:g}" if r["value_low"] is not None else "?"
        hi = f"-{r['value_high']:g}" if r["value_high"] is not None else ""
        why = f" | why: {r['judge_why']}" if r["judge_why"] else ""
        out.append(f"[{r['store']}] {r['node']} {r['sign']} {lo}{hi} {r['unit']} "
                   f"| period={r['effective_period']} | FAIL: {r['judge_fail']}{why} "
                   f"| STATEMENT: {norm_ws(r['statement'])}")

    ren = [r for r in rows if r["status_reason"] == "judge_renode"]
    rng.shuffle(ren)
    out.append(f"\n{renode_n} random JUDGE-RENODED claims (first {min(renode_n, len(ren))} of {len(ren)}):")
    for r in ren[:renode_n]:
        lo = f"{r['value_low']:g}" if r["value_low"] is not None else "?"
        hi = f"-{r['value_high']:g}" if r["value_high"] is not None else ""
        out.append(f"[{r['store']}] node={r['node']} (renoded, judge said {r['judge_fail']}) {r['sign']} "
                   f"{lo}{hi} {r['unit']} | period={r['effective_period']} "
                   f"| STATEMENT: {norm_ws(r['statement'])}")

    out.append(f"\nby node: {dict(sorted(nodes.items()))}")
    out.append("script-check failures: " + str(dict(Counter(
        r["status_reason"] for r in rows if r["status"] != "verified"
        and not (r["status_reason"] or "").startswith("judge:")))))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="T-228: driver-tree claims from management text")
    ap.add_argument("--stores", nargs="*", help="store names (default: every cNN store under the store root)")
    ap.add_argument("--all-stores", action="store_true",
                    help="every cNN store, including stores with no transcript and no guidance row (stage 2b)")
    ap.add_argument("--pick", type=int, default=0, help="add N stores with statements, seeded (default seed 7)")
    ap.add_argument("--pick-no-transcript", type=int, default=0,
                    help="add N stores without transcripts (stage 2a pilot pool), same --pick-seed")
    ap.add_argument("--pick-seed", type=int, default=7)
    ap.add_argument("--doc-types", nargs="*", default=list(DOC_TYPES),
                    help="doc_page types to read (default: annual_report press_release announcement; "
                         "give the flag with no value to read none, i.e. stage 1)")
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--start", type=int, default=30, help="requests in flight (default 30)")
    ap.add_argument("--judge-start", type=int, default=5, help="judge requests in flight (default 5)")
    ap.add_argument("--judge-batch", type=int, default=JUDGE_BATCH)
    ap.add_argument("--unleashed", action="store_true",
                    help="raise in-flight by 10 every 5 min while the error rate is under 2%%")
    ap.add_argument("--batch", type=int, default=BATCH, help="statements per request (default 10)")
    ap.add_argument("--max-workers", type=int, default=256)
    ap.add_argument("--max-items", type=int, default=0, help="cap model items (0 = no cap)")
    ap.add_argument("--dry-run", action="store_true", help="build items and print the filter counts, no model call")
    ap.add_argument("--judge-only", action="store_true",
                    help="re-run only the judge phase on the existing DB (also re-queues judge_error claims)")
    ap.add_argument("--report", action="store_true", help="build the DB report and the seeded samples")
    ap.add_argument("--retag", action="store_true", help="re-apply the revenue.mix and range rules to the existing DB")
    ap.add_argument("--report-file", default="", help="write the report here and print only its first two lines")
    ap.add_argument("--baseline", default="", help="another claims DB: report the companies/months gained")
    ap.add_argument("--build-json", default="", help="the builder counts file run wrote beside --out")
    ap.add_argument("--seed", type=int, default=53)
    args = ap.parse_args(argv)
    if args.retag:
        return retag_existing(Path(args.out))
    if args.report:
        lines = report(Path(args.out), args.seed, baseline=args.baseline, build_json=args.build_json)
        if args.report_file:
            Path(args.report_file).parent.mkdir(parents=True, exist_ok=True)
            Path(args.report_file).write_text("\n".join(lines) + "\n", encoding="utf-8")
            print("\n".join(lines[:2]))
            print(f"report written: {args.report_file} ({len(lines)} lines)")
        else:
            print("\n".join(lines))
        return 0
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
