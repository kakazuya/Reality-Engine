"""v4 WP2b — the document vocabulary: exhaustive surface layer, few labels (§A.9, §H.2).

Reads the three extractions that already run, filtered to the 60-company pilot
(``tasks/pilot60/UNIVERSE.csv``), read-only:

    concall_facts.cc_items.metric      ar_facts.ar_facts.category      deck_figures.facts.metric

and writes (file attached as ``vocab``):

    vocab.surface        one row per verbatim phrase (148,652 measured pilot surfaces)
    vocab.label          the declared label layer: 9 level-1 families + level-2 topics
    vocab.map            100% of surfaces -> a label id, or ``other:<raw>``
    vocab.other_cluster  the promotion queue (>=20 occurrences, >=3 companies, >=2 doc types)

    python -m reality_engine.query.v4.build_vocab --out .tmp/v4_vocab.db
    python -m reality_engine.query.v4.build_vocab --check      # numbers only, writes nothing
    python -m reality_engine.query.v4.build_vocab --dump-unmapped .tmp/unmapped_head.json

Deterministic pass only: no model, no network, no embeddings.  A surface the
declared vocabulary cannot name is stored ``other:<raw>`` and counted — never
guessed.  The release gate (≥95% of the head surfaces labelled at ≥95% hand-checked
precision) is *measured* here and printed; it is not asserted.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

from reality_engine.db.readonly import connect_ro

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
UNIVERSE = ROOT / "tasks" / "pilot60" / "UNIVERSE.csv"
REGISTRY = ROOT / "tasks" / "arch_v4" / "concept_registry.json"

# The measured numbers this build must reproduce (VOCAB_PASS1.md §1). If the
# store has drifted the build says so and exits non-zero; it never re-scales them.
# Occurrences are the sum over the three stores (21,606 + 1,021,844 + 772,131);
# VOCAB_PASS1 printed 1,691,352 for the union because its per-source Counters
# overwrote a shared phrase instead of adding it -- that figure is reported
# alongside as the published number, it is not the build's own measure.
EXPECTED_SURFACES = 148_652
EXPECTED_OCCURRENCES = 1_815_581
VOCAB_PASS1_UNION_OCCURRENCES = 1_691_352
HEAD_PCT = 0.95
PROMOTE_MIN_N = 20
PROMOTE_MIN_COMPANIES = 3
PROMOTE_MIN_DOCTYPES = 2

# --- level 1: the eight families plus the honest residue (§A.9). -------------
FAMILIES: dict[str, str] = {
    "financial_performance": "revenue, profit, margin, growth and the result itself",
    "costs_balance_sheet": "costs, debt, cash, working capital, assets, tax, capex",
    "segments_business": "segments, products, divisions, customers, entities in the group",
    "demand_orders": "orders, demand, volume, capacity, utilisation, market share",
    "guidance_risk": "guidance, outlook, expectations, risks and delays",
    "people_governance": "board, promoters, management, remuneration, CSR, RPT, auditor",
    "ownership_market": "shareholding, pledge, institutions, float, price, delivery",
    "policy_macro": "policy, tariff, GST, budget, RBI, inflation, commodity",
    "operations_other": "anything the eight families do not name (bucket, not a topic)",
}

# --- level 2: topic id -> (parent family, declared synonyms, definition). ------
# A synonym is either one token (matched against the normalised surface) or a
# phrase (all its tokens must be present; the longest phrase wins).  Topic ids are
# the label ids a claim carries; they are plain words so they read in an answer.
TOPICS: dict[str, tuple[str, str, str]] = {
    # financial_performance
    "revenue": ("financial_performance", "revenue sales turnover arr", "revenue or sales of the period"),
    "pat": ("financial_performance", "pat np profit profitability earnings", "profit after tax"),
    "pbt": ("financial_performance", "pbt", "profit before tax"),
    "ebit": ("financial_performance", "ebit", "earnings before interest and tax"),
    "ebitda": ("financial_performance", "ebitda opbida", "EBITDA"),
    "ebitda_margin": ("financial_performance", "margin", "margin (any level: gross/EBITDA/net)"),
    "eps": ("financial_performance", "eps", "earnings per share"),
    # Short ratio surfaces (ROE, ROCE, ROCE %) normalise to one token and were
    # therefore unmapped: no declared synonym held the acronym, and `%` is a stop
    # token.  Declaring the acronym and its phrase form is the deterministic fix
    # (hand-check: 935 ROE, 869 ROCE and 37 `ROCE %` occurrences in the pilot store).
    "roe": ("financial_performance", "roe", "return on equity"),
    "roce": ("financial_performance", "roce", "return on capital employed"),
    "roa": ("financial_performance", "roa", "return on assets"),
    "ronw": ("financial_performance", "ronw", "return on net worth"),
    "growth": ("financial_performance", "growth cagr yoy qoq", "growth of a metric"),
    "income": ("financial_performance", "income", "income of any kind"),
    "loss": ("financial_performance", "loss", "a loss"),
    "result": ("financial_performance", "result results", "the reported result"),
    "financials": ("financial_performance", "financial", "the financial statements as a set"),
    # costs_balance_sheet
    "cost": ("costs_balance_sheet", "cost opex expenditure expense", "a cost line"),
    "debt": ("costs_balance_sheet", "debt borrowing borrowings", "debt / borrowings"),
    "net_debt": ("costs_balance_sheet", "netdebt", "net debt"),
    "cash": ("costs_balance_sheet", "cash bank", "cash and bank balances"),
    "cash_flow": ("costs_balance_sheet", "cashflow", "cash flow"),
    "cfo": ("costs_balance_sheet", "cfo", "cash flow from operations"),
    "fcf": ("costs_balance_sheet", "fcf", "free cash flow"),
    "receivable": ("costs_balance_sheet", "receivable debtor receivable_days", "trade receivables"),
    "inventory": ("costs_balance_sheet", "inventory", "inventory"),
    "payable": ("costs_balance_sheet", "payable creditor", "trade payables"),
    "working_capital": ("costs_balance_sheet", "workingcapital", "working capital"),
    "capex": ("costs_balance_sheet", "capex capital_expenditure", "capital expenditure"),
    "cwip": ("costs_balance_sheet", "cwip", "capital work in progress"),
    "asset": ("costs_balance_sheet", "asset grossblock fixedasset", "an asset"),
    "liability": ("costs_balance_sheet", "liability liabilities", "a liability"),
    "equity": ("costs_balance_sheet", "equity networth", "shareholders' equity / net worth"),
    "tax": ("costs_balance_sheet", "tax taxation", "tax"),
    "dividend": ("costs_balance_sheet", "dividend dps", "dividend"),
    "interest": ("costs_balance_sheet", "interest financecost", "finance cost / interest"),
    "depreciation": ("costs_balance_sheet", "depreciation amortisation amortization", "depreciation and amortisation"),
    "investment": ("costs_balance_sheet", "investment", "investments held"),
    "impairment": ("costs_balance_sheet", "impairment writedown", "impairment"),
    "provision": ("costs_balance_sheet", "provision", "a provision"),
    "lease": ("costs_balance_sheet", "lease rental", "leases / lease liabilities"),
    # segments_business
    "segment": ("segments_business", "segment division vertical", "a reporting segment"),
    "business": ("segments_business", "business", "a line of business"),
    "product": ("segments_business", "product", "a product"),
    "category": ("segments_business", "category", "a category"),
    "portfolio": ("segments_business", "portfolio", "the portfolio"),
    "brand": ("segments_business", "brand", "a brand"),
    "customer": ("segments_business", "customer client", "a customer"),
    "subsidiary": ("segments_business", "subsidiary sub", "a subsidiary"),
    "associate": ("segments_business", "associate", "an associate company"),
    "jv": ("segments_business", "jv jointventure", "a joint venture"),
    "acquisition": ("segments_business", "acquisition acquired", "an acquisition"),
    "merger": ("segments_business", "merger amalgamation", "a merger"),
    "geography": ("segments_business", "geography", "a geography (also a dim on the claim)"),
    "commissioning": ("segments_business", "commissioning commissioned", "commissioning of a project"),
    # demand_orders
    "order": ("demand_orders", "order", "an order"),
    "order_book": ("demand_orders", "orderbook backlog", "the order book / backlog"),
    "order_intake": ("demand_orders", "orderintake orderinflow", "order inflow"),
    "order_value": ("demand_orders", "ordervalue", "value of an order"),
    "demand": ("demand_orders", "demand", "demand"),
    "supply": ("demand_orders", "supply", "supply"),
    "competition": ("demand_orders", "competition competitive", "competition"),
    "market_share": ("demand_orders", "marketshare", "market share"),
    "capacity": ("demand_orders", "capacity", "installed capacity"),
    "capacity_utilisation": ("demand_orders", "utilisation utilization", "capacity utilisation"),
    "volume": ("demand_orders", "volume volume_despatch despatch dispatch shipment", "unit volume / despatch"),
    "production": ("demand_orders", "production output generation", "production"),
    "expansion": ("demand_orders", "expansion", "capacity expansion"),
    "pipeline": ("demand_orders", "pipeline", "the pipeline"),
    "realisation": ("demand_orders", "realisation realization asp", "realisation / price per unit"),
    # guidance_risk
    "guidance": ("guidance_risk", "guidance guided outlook target", "guidance / outlook"),
    "expect": ("guidance_risk", "expect expected expectation", "an expectation (not a fact)"),
    "risk": ("guidance_risk", "risk concern", "a risk or concern"),
    "delay": ("guidance_risk", "delay delayed", "a delay"),
    "headwind": ("guidance_risk", "headwind", "a headwind"),
    "tailwind": ("guidance_risk", "tailwind", "a tailwind"),
    "vision": ("guidance_risk", "vision ambition", "an aspiration"),
    # people_governance
    "board": ("people_governance", "board director directorship", "the board / a director"),
    "promoter": ("people_governance", "promoter", "the promoter"),
    "management": ("people_governance", "management managerial", "management"),
    "remuneration": ("people_governance", "remuneration salary compensation", "remuneration"),
    "governance": ("people_governance", "governance", "governance"),
    "csr": ("people_governance", "csr", "corporate social responsibility"),
    "employee": ("people_governance", "employee staff people", "employees"),
    "employee_benefits": ("people_governance", "benefit gratuity provident superannuation", "employee benefit obligations"),
    "esop": ("people_governance", "esop options", "employee stock options"),
    "kpi": ("people_governance", "kpi", "a KPI"),
    "auditor": ("people_governance", "auditor audit", "auditor / audit"),
    "rpt": ("people_governance", "rpt relatedparty", "a related-party transaction"),
    "succession": ("people_governance", "succession", "management succession"),
    "control": ("people_governance", "control controlling", "control of the company"),
    # ownership_market
    "shareholding": ("ownership_market", "shareholding shareholder", "the shareholding pattern"),
    "pledge": ("ownership_market", "pledge pledged encumbrance encumbered", "shares pledged"),
    "fii": ("ownership_market", "fii fpi", "foreign institutional holding"),
    "dii": ("ownership_market", "dii", "domestic institutional holding"),
    "mf": ("ownership_market", "mf mutualfund", "mutual fund holding"),
    "public": ("ownership_market", "public", "public shareholding"),
    "float": ("ownership_market", "float freefloat", "free float"),
    "holding": ("ownership_market", "holding holdings", "a holding"),
    "price": ("ownership_market", "price ltp close", "the share price"),
    "delivery": ("ownership_market", "delivery", "delivery quantity/percentage"),
    "rsi": ("ownership_market", "rsi", "RSI"),
    "sma": ("ownership_market", "sma", "a moving average"),
    "mcap": ("ownership_market", "mcap marketcap", "market capitalisation"),
    "volume_traded": ("ownership_market", "tradedvolume", "traded volume"),
    # policy_macro
    "policy": ("policy_macro", "policy regulation regulatory", "a policy or regulation"),
    "tariff": ("policy_macro", "tariff duty", "a tariff / duty"),
    "gst": ("policy_macro", "gst", "GST"),
    "budget": ("policy_macro", "budget", "the budget"),
    "rbi": ("policy_macro", "rbi", "the RBI"),
    "repo": ("policy_macro", "repo", "the repo rate"),
    "inflation": ("policy_macro", "inflation cpi wpi", "inflation"),
    "monsoon": ("policy_macro", "monsoon rain rainfall", "monsoon / rainfall"),
    "commodity": ("policy_macro", "commodity", "a commodity"),
    "subsidy": ("policy_macro", "subsidy incentive", "a subsidy / incentive"),
    "scheme": ("policy_macro", "scheme pli", "a scheme"),
    # operations_other (declared level 2 topics that still need a family row)
    "material": ("costs_balance_sheet", "material rawmaterial", "materials"),
    "packaging": ("costs_balance_sheet", "packaging", "packaging"),
    "churn": ("demand_orders", "churn attrition", "churn"),
    "supply_chain": ("demand_orders", "supplychain logistics", "the supply chain"),
    "restructuring": ("costs_balance_sheet", "restructuring", "restructuring"),
    "gross_npa": ("financial_performance", "grossnpa", "gross NPA"),
    "net_npa": ("financial_performance", "netnpa", "net NPA"),
    "nim": ("financial_performance", "nim", "net interest margin"),
    "spread": ("financial_performance", "spread", "a spread"),
    "yield": ("financial_performance", "yield", "a yield"),
    "advance": ("financial_performance", "advance advances", "advances / loans"),
    "deposit": ("financial_performance", "deposit", "deposits"),
    "loan": ("financial_performance", "loan", "a loan"),
    "collection": ("financial_performance", "collection", "collections"),
    "npa": ("financial_performance", "npa", "a non-performing asset"),
    "payment": ("financial_performance", "payment", "a payment"),
    "receipt": ("financial_performance", "receipt", "a receipt"),
    "slippage": ("financial_performance", "slippage", "slippage"),
    "other": ("operations_other", "", "declared catch-all: the surface could not be named"),
}

# Declared multi-word synonyms that must beat the single-token fallback.
PHRASE_TOPICS: list[tuple[tuple[str, ...], str]] = [
    (("order", "book"), "order_book"),
    (("order", "intake"), "order_intake"),
    (("order", "inflow"), "order_intake"),
    (("order", "value"), "order_value"),
    (("cash", "flow"), "cash_flow"),
    (("free", "cash", "flow"), "fcf"),
    (("working", "capital"), "working_capital"),
    (("net", "debt"), "net_debt"),
    (("market", "share"), "market_share"),
    (("capacity", "utilisation"), "capacity_utilisation"),
    (("related", "party"), "rpt"),
    (("employee", "benefit"), "employee_benefits"),
    (("joint", "venture"), "jv"),
    (("gross", "npa"), "gross_npa"),
    (("net", "npa"), "net_npa"),
    (("book", "value"), "equity"),
    (("profit", "after", "tax"), "pat"),
    (("profit", "before", "tax"), "pbt"),
    (("operating", "profit"), "ebitda"),
    (("operating", "margin"), "ebitda_margin"),
    (("ebitda", "margin"), "ebitda_margin"),
    (("gross", "margin"), "ebitda_margin"),
    (("net", "margin"), "ebitda_margin"),
    (("unit", "volume"), "volume"),
    (("earnings", "per", "share"), "eps"),
    # Long spellings of the short return ratios, so the fix is not acronym-only.
    # `return capital` alone is deliberately absent: "capital returns" (a
    # distribution) normalises to the same two tokens and must not become ROCE.
    (("return", "equity"), "roe"),
    (("return", "capital", "employed"), "roce"),
    (("return", "asset"), "roa"),
    (("return", "worth"), "ronw"),
    # balance-sheet lines whose qualifier word ("financial") would otherwise win
    (("financial", "asset"), "asset"),
    (("financial", "liability"), "liability"),
]

# Declared alias map reused verbatim from VOCAB_PASS1.md §1 (reproducibility).
PHRASE_ALIASES: list[tuple[str, str]] = [
    ("profit after tax", "pat"), ("profit before tax", "pbt"),
    ("net profit", "pat"), ("profit for the period", "pat"),
    ("revenue from operations", "revenue"), ("total revenue", "revenue"),
    ("net sales", "revenue"), ("net revenue", "revenue"), ("sales", "revenue"),
    ("operating profit", "ebitda"), ("operating margin", "ebitda_margin"),
    ("order book", "order_book"), ("order inflow", "order_intake"),
    ("order intake", "order_intake"), ("order value", "order_value"),
    ("net debt", "net_debt"), ("working capital", "working_capital"),
    ("cash flow from operations", "cfo"), ("free cash flow", "fcf"),
    ("earnings per share", "eps"), ("book value", "book_value"),
    ("total debt", "debt"), ("gross npa", "gross_npa"), ("net npa", "net_npa"),
    ("capacity utilisation", "capacity_utilisation"), ("capacity utilization", "capacity_utilisation"),
    ("market share", "market_share"), ("unit volume", "volume"),
    ("research and development", "rnd"), ("related party transaction", "rpt"),
    ("related party transactions", "rpt"), ("related party", "rpt"),
    ("cash flow", "cash_flow"), ("cash flows", "cash_flow"),
    # VOCAB_PASS1.md §3 found this alias gap in the hand check:
    ("joint venture", "jv"), ("joint ventures", "jv"),
]
_ALIASES_LONGEST_FIRST = sorted(PHRASE_ALIASES, key=lambda p: -len(p[0]))

STOP = set("a an the of and or in for to from on by with as at is are was were be "
           "been its it this that these those versus vs per pct percent rs cr crore "
           "crores lakh lakhs million billion mn bn inr usd no not than then".split())
# Declared period words dropped from a surface before mapping. `target` and
# `guidance` are NOT here: the label layer names them (VOCAB_PASS1 stripped them
# because it only had token topics), so they must survive normalisation.
GEO_PERIOD = set("india indian asia asia pacific europe us usa uk america africa "
                 "middle east global domestic overseas international north south east west "
                 "fy fys yoy qoq year years quarter quarters h1 h2 q1 q2 q3 q4 "
                 "january february march april may june july august september october november december "
                 "projected projection estimate estimated".split())
# Declared non-topics: bucket words that carry no claim on their own.
NON_TOPIC = set("total net other value area gross new change increase decrease "
                "current previous period year quarter rate share unit data signal ratio".split())


# --- normalisation (byte-identical to tasks/arch_v4/vocab_pass1.py) -----------
def singular(t: str) -> str:
    if len(t) > 4 and t.endswith("ies"):
        return t[:-3] + "y"
    if len(t) > 3 and t.endswith("s") and not t.endswith("ss"):
        return t[:-1]
    return t


# Declared spelling variants that must reach the same normalised token set.
# Applied before punctuation is expanded, because `p&l`, `p_and_l` and `p/l` are
# only recognisable in their raw form (`&` -> "and" and `_` -> space would leave
# the bare letters `p`, `l`).  This is a merge of spellings, not a guess at a
# label: the merged words still go through the declared phrase/token layer.
SPELLING_VARIANTS: tuple[tuple[re.Pattern[str], str], ...] = (
    # Alnum lookarounds, not `\b`: the variants occur inside extractor keys such
    # as `consolidated_p_and_l`, where `_` is a word character and `\b` fails.
    (re.compile(r"(?<![a-z0-9])p\s*&\s*l(?![a-z0-9])"), "profit and loss"),
    (re.compile(r"(?<![a-z0-9])p\s+and\s+l(?![a-z0-9])"), "profit and loss"),
    (re.compile(r"(?<![a-z0-9])p_and_l(?![a-z0-9])"), "profit and loss"),
    (re.compile(r"(?<![a-z0-9])p\s*/\s*l(?![a-z0-9])"), "profit and loss"),
    (re.compile(r"(?<![a-z0-9])pnl(?![a-z0-9])"), "profit and loss"),
    (re.compile(r"(?<![a-z0-9])balancesheet(?![a-z0-9])"), "balance sheet"),
    (re.compile(r"(?<![a-z0-9])balance[-_]sheet(?![a-z0-9])"), "balance sheet"),
)
# A footnote marker glued to a ratio is not part of the ratio: ROCE1 / ROE2 /
# ROCE4 are the same surface as ROCE.  Kept separate because the replacement is
# a backreference, not a literal phrase.
FOOTNOTE_RATIO = re.compile(r"(?<![a-z0-9])(roe|roce|roa|ronw)\d+(?![a-z0-9])", re.I)


def words_of(phrase: str, ent_tokens: frozenset[str] = frozenset()) -> frozenset[str]:
    """The declared normalisation: the reproducibility contract of VOCAB_PASS1."""
    s = " " + phrase.lower() + " "
    for pattern, replacement in SPELLING_VARIANTS:
        s = pattern.sub(" " + replacement + " ", s)
    s = FOOTNOTE_RATIO.sub(lambda m: m.group(1).lower(), s)
    s = (s.replace("&", " and ").replace("%", " pct ").replace("/", " ")
          .replace("_", " ").replace("-", " "))
    for long, short in _ALIASES_LONGEST_FIRST:
        s = s.replace(" " + long + " ", " " + short + " ")
    out = []
    for t in re.findall(r"[a-z][a-z0-9]*", s):
        if t in STOP or t in GEO_PERIOD or t in ent_tokens or t.isdigit():
            continue
        out.append(singular(t))
    return frozenset(out)


def label_table() -> dict[str, tuple[str, str, str]]:
    """Topic id -> (family, definition, synonyms) with the declared extras merged."""
    return {tid: (fam, defn, syn) for tid, (fam, syn, defn) in TOPICS.items()}


def token_map() -> dict[str, str]:
    """Single-token synonym -> topic id; first declaration wins, non-topics are refused."""
    out: dict[str, str] = {}
    for tid, (_fam, syn, _defn) in TOPICS.items():
        for tok in syn.split():
            tok = singular(tok.lower())
            if tok in NON_TOPIC or tok in out or not tok:
                continue
            out[tok] = tid
    return out


TOKEN_TO_TOPIC = token_map()
PHRASE_MATCH = sorted(
    ((tuple(singular(t) for t in toks), tid) for toks, tid in PHRASE_TOPICS),
    key=lambda p: -len(p[0]),
)
# A statement heading (`p&l`, `balance sheet`) is only the statement when no
# specific topic is named beside it.  `Consolidated P&L - Depreciation` must stay
# `depreciation`, not collapse into `financials`; `P&L extract` has no topic token
# and does become `financials`.
STATEMENT_TOPICS: tuple[tuple[frozenset[str], str, frozenset[str]], ...] = (
    # "loss versus prior profit" is a comparison, not the statement: block the
    # statement reading when a comparison/qualifier word rides along.
    (frozenset({"profit", "loss"}), "financials",
     frozenset({"versus", "vs", "prior", "previous", "growth", "improvement",
                "decline", "increase", "decrease", "drop", "rise", "fall"})),
    (frozenset({"balance", "sheet"}), "financials", frozenset()),
)
TOPIC_TOKENS = frozenset(TOKEN_TO_TOPIC)


def label_for(words: frozenset[str], weight: dict[str, float] | None = None) -> tuple[str, str]:
    """Map a normalised surface to ``(label_id, method)``; ``other`` when unnamed.

    Longest declared phrase wins, then the most specific single token: the one
    that covers the fewest corpus occurrences (VOCAB_PASS1 §2's "pick the head,
    not the first broad word it sees").
    """
    for statement, tid, blockers in STATEMENT_TOPICS:
        extra = words - statement
        if statement <= words and not (extra & TOPIC_TOKENS) and not (extra & blockers):
            return tid, "phrase"
    for toks, tid in PHRASE_MATCH:
        if set(toks) <= words:
            return tid, "phrase"
    hits = [TOKEN_TO_TOPIC[t] for t in words if t in TOKEN_TO_TOPIC]
    if not hits:
        return "other", "other"
    if not weight:
        return sorted(hits)[0], "token"
    return min(hits, key=lambda tid: (min(weight.get(t, 0) for t in words
                                          if TOKEN_TO_TOPIC.get(t) == tid), tid)), "token"


def map_surface(phrase: str, ent_tokens: frozenset[str] = frozenset(),
                weight: dict[str, float] | None = None) -> str:
    """The value stored in ``vocab.map``: a label id, or ``other:<raw>``."""
    lab, _method = label_for(words_of(phrase, ent_tokens), weight)
    return lab if lab != "other" else f"other:{phrase}"


# --- source reads (read-only, bounded) ---------------------------------------
def pilot_isins() -> list[str]:
    with open(UNIVERSE, encoding="utf-8") as f:
        return [r["isin"] for r in csv.DictReader(f) if r.get("isin")]


def entity_tokens(isins: list[str], ee_db: Path) -> frozenset[str]:
    """Company-name and symbol tokens: a phrase already attached to the entity."""
    out: set[str] = set()
    if not ee_db.exists():
        return frozenset()
    con = connect_ro(ee_db, timeout_s=60, immutable=True)
    try:
        q = ",".join("?" * len(isins))
        for row in con.execute(
                f"SELECT company_name, nse_symbol FROM master_companies WHERE isin IN ({q})", isins):
            for v in row:
                if v:
                    out.update(re.findall(r"[a-z][a-z0-9]*", str(v).lower()))
    except sqlite3.Error as exc:          # never fail the build on an optional read
        print(f"entity-token read skipped: {exc}", file=sys.stderr)
    finally:
        con.close()
    out -= {"ltd", "limited", "company", "co", "industries", "india", "indian", "and", "of", "the"}
    # A word that names a label is never an entity token: the pilot holds a bank
    # and a name with `financial`, and stripping those words from every surface
    # unmapped `bank balance` / `financial` (2,503 occurrences) for nothing.
    out -= set(TOKEN_TO_TOPIC)
    return frozenset(out)


def _merge(out: dict, phrase: str | None, n: int, n_docs: int, isins: int,
           known_at: str | None, source: str) -> None:
    if phrase is None:
        return
    phrase = str(phrase)
    d = out.setdefault(phrase, {"n": 0, "n_docs": 0, "n_isins": 0, "sources": [],
                                "known_at": None})
    d["n"] += n
    d["n_docs"] += n_docs
    d["n_isins"] = max(d["n_isins"], isins)   # conservative union (never over-counts)
    d["sources"].append(source)
    if known_at and (d["known_at"] is None or known_at < d["known_at"]):
        d["known_at"] = known_at


def collect_surfaces(data_root: Path, isins: list[str]) -> dict[str, dict]:
    """Every pilot phrase verbatim, with occurrences and provenance per store."""
    q = ",".join("?" * len(isins))
    out: dict[str, dict] = {}

    con = connect_ro(data_root / "concall_facts.db", timeout_s=180, immutable=True)
    try:
        for phrase, n, nd, ni, ka in con.execute(
                f"SELECT metric, count(*), count(DISTINCT doc_id), count(DISTINCT isin), "
                f"min(filed_at) FROM cc_items WHERE isin IN ({q}) AND metric IS NOT NULL "
                f"GROUP BY 1", isins):
            _merge(out, phrase, n, nd, ni, ka, "concall")
    finally:
        con.close()

    con = connect_ro(data_root / "ar_facts.db", timeout_s=600, immutable=True)
    try:
        for phrase, n, nd, ni, ka in con.execute(
                f"SELECT category, count(*), count(DISTINCT doc_id), count(DISTINCT isin), "
                f"min(filed_at) FROM ar_facts WHERE isin IN ({q}) AND category IS NOT NULL "
                f"GROUP BY 1", isins):
            _merge(out, phrase, n, nd, ni, ka, "annual_report")
    finally:
        con.close()

    deck = connect_ro(data_root / "deck_figures.db", timeout_s=600, immutable=True)
    try:
        sha_isin: dict[str, str] = {}
        sha_known: dict[str, str] = {}
        for sha, isin, ka in deck.execute(
                f"SELECT sha256, isin, min(known_at) FROM pages WHERE isin IN ({q}) "
                f"GROUP BY sha256", isins):
            sha_isin[sha] = isin
            if ka:
                sha_known[sha] = ka
        idx = {isin: i for i, isin in enumerate(isins)}
        masks: dict[str, int] = {}
        hashes = list(sha_isin)
        for i in range(0, len(hashes), 400):
            chunk = hashes[i:i + 400]
            hq = ",".join("?" * len(chunk))
            for phrase, sha, n in deck.execute(
                    f"SELECT metric, sha256, count(*) FROM facts WHERE sha256 IN ({hq}) "
                    f"AND metric IS NOT NULL GROUP BY 1, 2", chunk):
                masks[phrase] = masks.get(phrase, 0) | (1 << idx.get(sha_isin.get(sha, ""), 0))
                _merge(out, phrase, n, 1, 1, sha_known.get(sha), "deck")
        for phrase, mask in masks.items():
            out[phrase]["n_isins"] = max(out[phrase]["n_isins"], bin(mask).count("1"))
    finally:
        deck.close()
    return out


# --- build -------------------------------------------------------------------
SCHEMA = """
CREATE TABLE IF NOT EXISTS label(
  label_id TEXT PRIMARY KEY, parent_id TEXT, level INTEGER NOT NULL,
  label TEXT NOT NULL, definition TEXT, registry_atoms TEXT,
  created_at TEXT NOT NULL, promoted_from TEXT);
CREATE TABLE IF NOT EXISTS surface(
  surface_id INTEGER PRIMARY KEY, surface_verbatim TEXT NOT NULL UNIQUE,
  norm_key TEXT NOT NULL, source_kind TEXT NOT NULL, n_occurrences INTEGER NOT NULL,
  n_docs INTEGER NOT NULL, n_isins INTEGER NOT NULL, first_known_at TEXT);
CREATE TABLE IF NOT EXISTS map(
  surface_id INTEGER PRIMARY KEY REFERENCES surface(surface_id),
  label_id TEXT, map_value TEXT NOT NULL, method TEXT NOT NULL, confidence REAL,
  reviewed_by TEXT, reviewed_at TEXT);
CREATE TABLE IF NOT EXISTS other_cluster(
  cluster_id INTEGER PRIMARY KEY, tokens TEXT NOT NULL, sample_surfaces TEXT NOT NULL,
  n_occurrences INTEGER NOT NULL, n_isins INTEGER NOT NULL, n_doctypes INTEGER NOT NULL,
  first_seen TEXT, status TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_surface_n ON surface(n_occurrences);
CREATE INDEX IF NOT EXISTS ix_map_value ON map(map_value);
"""


def _clusters(other: list[dict], jacc: float = 0.6) -> list[dict]:
    """Token-set Jaccard clustering of unmapped surfaces (VOCAB_PASS1 method B)."""
    agg: dict[frozenset[str], dict] = {}
    for row in other:
        d = agg.setdefault(row["words"], {"n": 0, "n_isins": 0, "n_doctypes": 0,
                                          "examples": [], "known_at": None})
        d["n"] += row["n"]
        d["n_isins"] = max(d["n_isins"], row["n_isins"])
        d["n_doctypes"] = max(d["n_doctypes"], len(row["sources"]))
        if len(d["examples"]) < 3:
            d["examples"].append(row["surface"])
        if row["known_at"] and (d["known_at"] is None or row["known_at"] < d["known_at"]):
            d["known_at"] = row["known_at"]
    order = sorted(agg.items(), key=lambda kv: (-kv[1]["n"], sorted(kv[0])))
    idx: dict[str, list[int]] = {}
    reps: list[frozenset[str]] = []
    clusters: list[dict] = []
    for tset, d in order:
        if not tset:
            continue
        cand: set[int] = set()
        for t in tset:
            cand.update(idx.get(t, [])[-300:])
        best, best_j = -1, 0.0
        for ci in cand:
            rep = reps[ci]
            inter, union = len(tset & rep), len(tset | rep)
            j = inter / union if union else 0.0
            if j >= jacc and j > best_j:
                best, best_j = ci, j
        if best < 0:
            reps.append(tset)
            clusters.append({"tokens": tset, "n": 0, "n_isins": 0, "n_doctypes": 0,
                             "examples": [], "known_at": None})
            best = len(clusters) - 1
            for t in tset:
                idx.setdefault(t, []).append(best)
        c = clusters[best]
        c["n"] += d["n"]
        c["n_isins"] = max(c["n_isins"], d["n_isins"])
        c["n_doctypes"] = max(c["n_doctypes"], d["n_doctypes"])
        if len(c["examples"]) < 3:
            c["examples"] += d["examples"][:3 - len(c["examples"])]
        if d["known_at"] and (c["known_at"] is None or d["known_at"] < c["known_at"]):
            c["known_at"] = d["known_at"]
    return clusters


def build(out: Path | None, data_root: Path, *, strict: bool = True, jacc: float = 0.6,
          mark_head_unmapped: Path | None = None,
          isins: list[str] | None = None) -> dict:
    """Measure the pilot surfaces, write the four vocab tables (when ``out``), return the report."""
    isins = list(isins) if isins is not None else pilot_isins()
    ents = entity_tokens(isins, data_root / "equity_intelligence.db")
    surfaces = collect_surfaces(data_root, isins)
    total = sum(d["n"] for d in surfaces.values())
    report: dict = {
        "pilot_isins": len(isins),
        "surfaces": len(surfaces),
        "occurrences": total,
        "occurrences_vocab_pass1_published": VOCAB_PASS1_UNION_OCCURRENCES,
        "expected_surfaces": EXPECTED_SURFACES,
        "expected_occurrences": EXPECTED_OCCURRENCES,
    }
    if strict and (len(surfaces) != EXPECTED_SURFACES or total != EXPECTED_OCCURRENCES):
        report["ok"] = False
        report["error"] = (f"source drift: {len(surfaces)} surfaces / {total} occurrences, "
                           f"VOCAB_PASS1 measured {EXPECTED_SURFACES} / {EXPECTED_OCCURRENCES}")
        return report

    rows = []
    for phrase, d in surfaces.items():
        words = words_of(phrase, ents)
        rows.append({"surface": phrase, "words": words, "n": d["n"], "n_docs": d["n_docs"],
                     "n_isins": d["n_isins"], "sources": sorted(set(d["sources"])),
                     "known_at": d["known_at"]})
    weight: Counter = Counter()
    for r in rows:
        for t in r["words"]:
            weight[t] += r["n"]
    for r in rows:
        lab, method = label_for(r["words"], dict(weight))
        r["label"], r["method"] = lab, method
        r["map_value"] = lab if lab != "other" else f"other:{r['surface']}"

    # head = the smallest set of surfaces carrying >= 95% of occurrences
    by_n = sorted(rows, key=lambda r: -r["n"])
    cum, head_n = 0, 0
    for i, r in enumerate(by_n, 1):
        cum += r["n"]
        if cum >= HEAD_PCT * total:
            head_n = i
            break
    head = by_n[:head_n]
    head_labelled = [r for r in head if r["label"] != "other"]
    other = [r for r in rows if r["label"] == "other"]

    clusters = _clusters(other, jacc)
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(out)
        try:
            con.executescript(SCHEMA)
            con.execute("DELETE FROM map")
            con.execute("DELETE FROM surface")
            con.execute("DELETE FROM label")
            con.execute("DELETE FROM other_cluster")
            now = "2026-10-31T00:00:00"
            atoms = _registry_atoms()
            for fam, defn in FAMILIES.items():
                con.execute("INSERT OR REPLACE INTO label VALUES (?,?,?,?,?,?,?,?)",
                            (fam, None, 1, fam, defn, None, now, None))
            for tid, (fam, defn, _syn) in TOPICS.items():
                con.execute("INSERT OR REPLACE INTO label VALUES (?,?,?,?,?,?,?,?)",
                            (tid, fam, 2, tid, defn, atoms.get(tid), now, None))
            for sid, r in enumerate(rows, 1):
                r["surface_id"] = sid
                con.execute(
                    "INSERT INTO surface VALUES (?,?,?,?,?,?,?,?)",
                    (sid, r["surface"], " ".join(sorted(r["words"])), r["sources"][0],
                     r["n"], r["n_docs"], r["n_isins"], r["known_at"]))
                con.execute("INSERT INTO map VALUES (?,?,?,?,?,?,?)",
                            (sid, None if r["label"] == "other" else r["label"],
                             r["map_value"], r["method"],
                             0.0 if r["label"] == "other" else 1.0, None, None))
            for cid, c in enumerate(sorted(clusters, key=lambda c: -c["n"]), 1):
                status = ("queued" if c["n"] >= PROMOTE_MIN_N
                          and c["n_isins"] >= PROMOTE_MIN_COMPANIES
                          and c["n_doctypes"] >= PROMOTE_MIN_DOCTYPES else "pending")
                con.execute(
                    "INSERT INTO other_cluster VALUES (?,?,?,?,?,?,?,?)",
                    (cid, " ".join(sorted(c["tokens"])), json.dumps(c["examples"]),
                     c["n"], c["n_isins"], c["n_doctypes"], c["known_at"], status))
            con.commit()
        finally:
            con.close()

    report.update({
        "ok": True,
        "out": str(out),
        "labels": len(FAMILIES) + len(TOPICS),
        "head_surfaces": head_n,
        "head_labelled": len(head_labelled),
        "head_labelled_pct": round(100.0 * len(head_labelled) / max(1, head_n), 2),
        "labelled_surfaces": len(rows) - len(other),
        "labelled_pct": round(100.0 * (len(rows) - len(other)) / max(1, len(rows)), 2),
        "other_surfaces": len(other),
        "other_occurrences_pct": round(
            100.0 * sum(r["n"] for r in other) / max(1, total), 2),
        "gate_met": len(head_labelled) / max(1, head_n) >= 0.95,
        "other_clusters": len(clusters),
        "queued_clusters": sum(
            1 for c in clusters if c["n"] >= PROMOTE_MIN_N
            and c["n_isins"] >= PROMOTE_MIN_COMPANIES
            and c["n_doctypes"] >= PROMOTE_MIN_DOCTYPES),
        "by_source_other_pct": _other_share_per_source(other, surfaces, total),
    })
    if mark_head_unmapped is not None:
        remaining = [{"surface": r["surface"], "occurrences": r["n"], "words": " ".join(
            sorted(r["words"]))} for r in head if r["label"] == "other"]
        mark_head_unmapped.parent.mkdir(parents=True, exist_ok=True)
        mark_head_unmapped.write_text(json.dumps(remaining, indent=1), encoding="utf-8")
        report["unmapped_head_file"] = str(mark_head_unmapped)
    return report


def _other_share_per_source(other: list[dict], surfaces: dict[str, dict],
                           total: int) -> dict[str, float]:
    out = {}
    for src in ("concall", "annual_report", "deck"):
        n = sum(surfaces[r["surface"]]["n"] for r in other
                if src in surfaces[r["surface"]]["sources"])
        tot = sum(d["n"] for d in surfaces.values() if src in d["sources"])
        out[src] = round(100.0 * n / max(1, tot), 2)
    return out


def _registry_atoms() -> dict[str, str]:
    """Label -> registry atom ids (the id a claim and its number share)."""
    if not REGISTRY.exists():
        return {}
    try:
        data = json.loads(REGISTRY.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    out: dict[str, list[str]] = {}
    for atom in data.get("atoms", []):
        aid = str(atom.get("atom_id") or "")
        label = str(atom.get("label") or "").lower()
        tid = TOKEN_TO_TOPIC.get(singular(label)) or (label if label in TOPICS else None)
        if aid and tid:
            out.setdefault(tid, []).append(aid)
    return {k: ",".join(sorted(set(v))) for k, v in out.items()}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--out", type=Path, default=Path(".tmp/v4_vocab.db"))
    ap.add_argument("--data-root", type=Path,
                    default=Path(os.environ.get("REALITY_DATA_ROOT", ROOT / "reality_engine" / "data")))
    ap.add_argument("--check", action="store_true", help="measure and print; write nothing")
    ap.add_argument("--dump-unmapped", type=Path, default=None,
                    help="write the unmapped head surfaces (the later mapper job's input)")
    ap.add_argument("--jacc", type=float, default=0.6)
    args = ap.parse_args(argv)

    if args.check:
        report = build(None, args.data_root, strict=True,
                       mark_head_unmapped=args.dump_unmapped)
    else:
        report = build(args.out, args.data_root, strict=True,
                       jacc=args.jacc, mark_head_unmapped=args.dump_unmapped)
    print(json.dumps(report, indent=1))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
