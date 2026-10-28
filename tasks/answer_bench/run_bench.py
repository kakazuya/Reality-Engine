"""Answer the 150-case sample through the reality-data tool functions and grade it.

Read-only.  The tools are called through the SAME modules the `reality-data` MCP
server exposes (`plugins/reality-data/server/{core,lookups_market,lookups_docs,
search_docs,universe}.py`) -- the documented toolbelt pattern
(`reality_engine/toolbelt/lookup_*.py`, "same functions as the MCP tools"), so a
per-case wall-clock and call count can be measured.  No network, no paid
embeddings, no DB writes.

Grading is hop-based: every case declares the hops its answer needs (from the
case's own `rubric.required_evidence`, else from its family); each hop is
actually executed against the held data.  All hops ok -> ANSWERED, some ok ->
PARTIAL, none ok -> BLOCKED_SCHEMA / BLOCKED_TOOL / NOT_IN_DATA depending on why
the hop failed.  A case with `as_of` whose only usable evidence is published
after that date cannot be ANSWERED.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(REPO / "plugins" / "reality-data" / "server"))

assert not os.environ.get("REALITY_DATA_ALLOW_PAID_EMBED"), "paid embeddings must stay off"

import core  # noqa: E402
import lookups_docs  # noqa: E402
import lookups_market  # noqa: E402
import search_docs  # noqa: E402
import universe as universe_mod  # noqa: E402

MAX_CALLS = 8
SLOW_S = 20.0
MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
COMMODITY = [("crude palm", "crude_palm"), ("brent", "crude_brent"), ("crude", "crude_brent"),
             ("copper", "copper"), ("usdinr", "usdinr"), ("rupee", "usdinr"), ("inr", "usdinr"),
             ("gold", "gold"), ("silver", "silver"), ("zinc", "zinc"), ("alumin", "aluminium"),
             ("coal", "coal_newcastle"), ("natural gas", "natural_gas"), ("steel", "steel_hrc_us"),
             ("iron ore", "iron_ore_62"), ("platinum", "platinum")]
INDEXES = ["Nifty 50", "Nifty Bank", "Nifty IT", "Nifty Energy", "Nifty Metal", "Nifty Auto",
           "Nifty FMCG", "Nifty Pharma", "Nifty Realty", "Nifty PSU Bank", "Nifty Private Bank",
           "Nifty Financial Services", "Nifty Midcap 100", "Nifty Smallcap 100", "Nifty 500",
           "Nifty 200", "Nifty Next 50", "Nifty India Defence", "Nifty Infrastructure",
           "Nifty Consumer Durables", "Nifty Oil & Gas", "India VIX"]
THEMES = {"gold": "gold_jewellery_finance", "jewell": "gold_jewellery_finance",
          "housing finance": "housing_finance", "hfc": "housing_finance",
          "home loan": "housing_finance", "dairy": "dairy", "milk": "dairy",
          "data centre": "data_centres", "data center": "data_centres",
          "defence": "defence", "defense": "defence", "specialty chem": "specialty_chemicals",
          "textile export": "textiles_exporters", "garment": "textiles_exporters",
          "omc": "omc_refining", "refin": "omc_refining", "oil marketing": "omc_refining"}
TECH = re.compile(r"\b(rsi|breakouts?|open interest|max pain|pcr|supports?|resistances?|"
                  r"oi buildup|relative strength|gaps? up|gaps? down|gaps? fill(?:ed)?|earnings gaps?|\bgaps?\b)\b")
SYM_HOPS = {"price", "qfin", "afin", "ar", "deck", "concall", "docs", "holding", "opinion",
            "corp_action", "bands", "deals", "insider", "segment", "etf", "search", "page",
            "delivery", "extreme"}


# ----------------------------------------------------------------- static maps
def load_cases() -> list[dict]:
    return [json.loads(x) for x in (HERE / "SAMPLE.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]


def gap_map() -> tuple[dict[str, dict], dict[str, str]]:
    """mid -> gap section; gap id -> {closable,path,effort,title,members}."""
    text = (HERE.parent / "master_bank" / "GAP_ROLLUP.md").read_text(encoding="utf-8")
    sec = text[text.find("## 4."):]
    gaps: dict[str, dict] = {}
    mid_gap: dict[str, str] = {}
    for block in re.split(r"\n### ", sec)[1:]:
        head = block.splitlines()[0]
        m = re.match(r"\d+\.\s+([\w\-]+)\s+-\s+(.*)", head)
        if not m:
            continue
        gid, title = m.group(1), m.group(2).strip()
        cases = re.search(r"cases blocked:\s*\*\*(\d+)\*\*\s*-\s*([^\n]+)", block)
        closable = re.search(r"closable from held data:\*\*\s*(\w+)\*\*", block)
        path = re.search(r"path:\s*([^\n]+)", block)
        effort = re.search(r"effort:\s*([\d.]+)", block)
        members = re.search(r"members:\s*([^\n]+)", block)
        gaps[gid] = {"title": title, "closable": (closable.group(1) if closable else None),
                     "path": (path.group(1).strip() if path else None),
                     "effort": float(effort.group(1)) if effort else None,
                     "members": [x.strip() for x in members.group(1).split(",")] if members else []}
        if cases:
            for mid in re.findall(r"MB\d{4}", cases.group(2)):
                mid_gap.setdefault(mid, gid)
    return gaps, mid_gap


# ------------------------------------------------------------------ case syntax
def rub(case: dict) -> dict:
    return case.get("rubric") or {}


def evidence_tokens(case: dict) -> list[str]:
    ev = rub(case).get("required_evidence")
    if isinstance(ev, str):
        ev = re.split(r"[;,]\s*", ev)
    if not isinstance(ev, list):
        return []
    return [str(e) for e in ev if e and str(e).strip()]


HOP_RULES = [
    ("segment", ("segment",)),
    ("opinion", ("auditor", "opinion", "audit")),
    ("commodity", ("commodit", "usdinr", "copper", "crude", "brent", "steel_hrc", "gold", "lme")),
    ("index", ("index_daily", "index_", "nifty", "sector index", "mkt_nse_index")),
    ("flows", ("fii", "dii", "fpi", "flow")),
    ("corp_action", ("corp_action", "corporate_action", "demerger", "split", "bonus")),
    ("bands", ("price_band", "band")),
    ("deals", ("bulk_block", "deal", "block")),
    ("insider", ("insider", "sast", "promoter_pledge", "pledge")),
    ("holding", ("shareholding", "holder", "own", "shp")),
    ("etf", ("etf", "nav", "inav")),
    ("qfin", ("quarterly_financials", "xbrl", "results_xbrl", "quarter", "margin", "revenue")),
    ("afin", ("annual_financials", "financial_metrics", "interest_cover", "roic", "debt")),
    ("ar", ("ar_facts", "ar_docs", "annual report", "raw_documents", "document_chunks")),
    ("deck", ("deck_", "presentation", "ppt")),
    ("concall", ("concall", "cc_items", "cc_docs", "transcript", "guidance")),
    ("docs", ("docs", "doc_", "filing", "announcement", "bse_ann")),
    ("search", ("search", "fts", "text")),
    ("policy", ("policy_events", "policy", "pib", "budget", "rbi", "tariff", "pli")),
    ("universe", ("universe", "theme", "membership", "peer")),
    ("price", ("px_", "price", "delivery", "ohlcv", "turnover", "close", "mkt_")),
]

FAMILY_HOPS = {
    1: ["ar", "docs"], 2: ["qfin", "afin", "price"], 3: ["concall", "qfin"],
    4: ["qfin", "holding", "universe"], 5: ["docs"], 6: ["policy", "search"],
    7: ["policy", "docs"], 8: ["qfin", "afin"], 9: ["price", "docs"], 10: ["search"],
    11: ["commodity", "policy"], 12: ["docs", "search"], 13: ["concall", "search"],
    14: ["opinion", "holding"], 15: ["index", "price"], 16: ["commodity", "qfin"],
    17: ["afin", "concall"], 18: ["policy", "search"], 19: ["docs", "policy"], 20: [],
}


def family_of(case: dict) -> int | None:
    fams = case.get("family") or []
    return fams[0] if fams else None


def classify_evidence(tokens: list[str]) -> list[str]:
    hops = []
    for tok in tokens:
        low = tok.lower()
        for hop, keys in HOP_RULES:
            if any(k in low for k in keys):
                if hop not in hops:
                    hops.append(hop)
                break
    return hops


LEVEL_SYM = {"stock", "theme", "index", "industry", "sector", "market-cap bucket"}


def probe_symbol(case: dict) -> str | None:
    syms = symbols(case)
    return syms[0] if syms and case.get("entity_level") in LEVEL_SYM else None


OPINION_TEMPLATES = {"entry_timing", "hold_sell", "group_basket", "ipo_grey_listing",
                     "thesis_break"}


def plan_hops(case: dict) -> list[str]:
    hops = classify_evidence(evidence_tokens(case))
    q = (case.get("question") or "").lower()
    if str(case.get("answer_kind") or "").strip().upper() == "NOT IN DATA":
        hops = ["nodata"]
    if str(case.get("template") or "") in OPINION_TEMPLATES and "expectations" not in hops:
        hops = ["expectations"] + [h for h in hops if h in ("price", "holding")]
    if "page " in q and re.search(r"page\s+\d+", q, re.I):
        hops = ["page"]
    if re.search(r"\b(52[- ]week|ytd|all[- ]time|year[- ]to[- ]date|highest|lowest|high|low)\b",
                 q) and probe_symbol(case) and re.search(
                     r"high|low|52[- ]week|ytd|all[- ]time", q):
        if not any(h in hops for h in ("extreme", "tech")):
            hops = ["extreme"] + [h for h in hops if h != "price"]
    if re.search(r"delivered quantity|delivery volume|delivery qty|deliverable", q):
        hops = ["delivery"] + [h for h in hops if h not in ("price", "tech", "delivery")]
    if re.search(r"\b(audit|auditor|qualified|qualification|declaration|unmodified pass(?:ed)?|"
                 r"audit opinion)\b", q, re.I) and "opinion" not in hops:
        hops.append("opinion")
    if TECH.search(q) and (not hops or case.get("template") in ("ta_gap", "ta_rsi_setup",
                                                               "ta_support_resistance",
                                                               "ta_breakout_volume",
                                                               "ta_relative_strength",
                                                               "ta_oi_buildup",
                                                               "ta_pcr_maxpain",
                                                               "ta_delivery_spike")):
        hops = ["tech"]
        if probe_symbol(case):
            hops = ["price", "tech"]
            if "delivery" in q:
                hops.insert(1, "deals")
    if not hops:
        hops = list(FAMILY_HOPS.get(family_of(case), ["search"]))
    # a question that names its document type pins the doc hop
    doctype = None
    for key, hop in (("transcript", "concall"), ("presentation", "deck"),
                     ("annual report", "ar"), ("investor ppt", "deck")):
        if key in q:
            doctype = hop
            break
    if doctype:
        drop = {"ar", "deck", "concall", "docs"} - {doctype}
        hops = [h for h in hops if h not in drop]
        if doctype not in hops:
            hops.append(doctype)
    # a text answer needs a passage, not only a stored number
    if case.get("answer_kind") in ("text+quote", "explanation") and not (
            {"docs", "ar", "deck", "concall", "search"} & set(hops)):
        hops.append("docs")
    sym = probe_symbol(case)
    if not sym and "etf" in hops:
        hops.remove("etf")
    if not sym and any(h in hops for h in ("qfin", "afin")):
        hops = [h for h in hops if h not in ("qfin", "afin")]
        if "screen" not in hops:
            hops.append("screen")
    if not sym and any(h in hops for h in ("concall", "ar", "deck", "docs")):
        hops = [h for h in hops if h not in ("concall", "ar", "deck", "docs")]
        if "search" not in hops:
            hops.append("search")

    if family_of(case) == 2 and "qfin" in hops and "price" not in hops and sym:
        hops.append("price")
    # a leader/peer ask needs the comparison set, not only the seed company
    if re.search(r"\bscreen\b|rank them", (case.get("question") or ""), re.I):
        if "screen" not in hops:
            hops.append("screen")
    if (case.get("answer_kind") in ("ranking", "list") and sym
            and family_of(case) in (4, 8, 13, 17) and "screen" not in hops):
        hops.append("screen")
    return [h for i, h in enumerate(hops) if h not in hops[:i]]


def entities(case: dict) -> list[dict]:
    return [e for e in (case.get("entities") or []) if isinstance(e, dict)]


def symbols(case: dict) -> list[str]:
    out = []
    for e in entities(case):
        s = e.get("symbol") or e.get("nse_symbol")
        if isinstance(s, str) and s.strip():
            out.append(s.strip().upper())
    if not out:
        stop = {"NSE", "BSE", "FY", "INR", "US", "EU", "FII", "DII", "RBI", "PLI", "ETF", "IPO",
                "JV", "AR", "NIFTY", "Q1", "Q2", "Q3", "Q4", "HFC", "OMC", "NPA", "ROIC", "WACC",
                "EV", "LTV", "INDIAS", "MISSION"}
        for m in re.findall(r"\b([A-Z][A-Z0-9&\-]{2,15})\b", case.get("question") or ""):
            if m.upper() not in stop and not re.match(r"^(FY|Q[1-4])", m):
                out.append(m.upper())
            if len(out) >= 2:
                break
    if not out:
        for m in re.findall(r"\b(5\d{5}|6\d{5}|9\d{5})\b", case.get("question") or ""):
            out.append(m)
            break
    return out


def parse_date(text: str) -> list[str]:
    out = []
    for m in re.finditer(r"(\d{4})-(\d{2})-(\d{2})", text):
        out.append(m.group(0))
    for m in re.finditer(r"\b(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+(\d{4})\b",
                         text, re.I):
        out.append(f"{m.group(3)}-{MONTHS[m.group(2).lower()[:3]]:02d}-{int(m.group(1)):02d}")
    return out


def period_range(case: dict) -> tuple[str | None, str | None]:
    for txt in (case.get("period") or "", case.get("question") or ""):
        ds = parse_date(str(txt))
        if len(ds) >= 2:
            return min(ds), max(ds)
        if len(ds) == 1:
            return ds[0], ds[0]
    per = str(case.get("period") or "")
    m = re.search(r"Q([1-4])\s*FY(\d{2})", per, re.I)
    if m:
        q, fy = int(m.group(1)), 2000 + int(m.group(2))
        # FY27 starts 2026-04-01, so Q1FY27 ends 2026-06-30
        d = {1: f"{fy - 1}-06-30", 2: f"{fy - 1}-09-30", 3: f"{fy - 1}-12-31",
             4: f"{fy}-03-31"}[q]
        return d, d
    m = re.search(r"FY(\d{2,4})", per, re.I)
    if m:
        y = m.group(1)
        y = (2000 + int(y)) if len(y) == 2 else int(y)
        return f"{y}-03-31", f"{y}-03-31"
    m = re.search(r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+(\d{4})", per, re.I)
    if m:
        y, mo = int(m.group(2)), MONTHS[m.group(1).lower()[:3]]
        last = {1: 31, 2: 28, 3: 31, 4: 30, 5: 31, 6: 30, 7: 31, 8: 31, 9: 30,
                10: 31, 11: 30, 12: 31}[mo]
        return f"{y}-{mo:02d}-01", f"{y}-{mo:02d}-{last}"
    asof = str(case.get("as_of") or "")
    return (asof, asof) if asof else (None, None)


def asof(case: dict) -> str:
    return str(case.get("as_of") or "")[:10] or "2099-12-31"


GENERIC = {"close", "date", "latest", "last", "quarter", "quarters", "company", "companies",
           "results", "result", "report", "annual", "hold", "held", "stored", "market", "stock",
           "stocks", "listed", "which", "what", "does", "management", "management's"}


STOPWORDS = {"what", "which", "does", "from", "with", "that", "have", "this", "they", "there",
             "their", "about", "would", "could", "should", "been", "were", "when", "where",
             "than", "then", "also", "into", "over", "after", "before", "still", "actually",
             "give", "name", "compare", "build", "show", "much", "many", "same", "kind",
             "share", "says", "said"}


VERBS = {"guided", "expects", "expected", "reported", "reports", "says", "said", "give",
         "gives", "makes", "made", "takes", "took", "falls", "fell", "rises", "rose", "grow",
         "grew", "know", "mean", "means", "happen", "happened", "did", "say", "just", "the",
         "and", "for", "its", "was", "are", "has", "had", "how", "why", "per", "any", "all",
         "now", "use", "get", "got", "put", "see", "saw", "make", "take", "keep", "kept",
         "there", "here", "tell", "told", "ask", "asked", "look", "looks", "seem", "seems"}


def key_terms(case: dict) -> str:
    low_syms = {s.lower() for s in symbols(case)}
    drop_isin = re.compile(r"^[A-Z]{2}[A-Z0-9]{6,}$")
    names = set()
    for s in symbols(case):
        for w in SYM_NAMES.get(s, "").lower().split():
            names.add(w)
    for e in entities(case):
        for k in ("name",):
            v = str(e.get(k) or "").lower()
            if v:
                names.add(v)
                names.update(v.split())
    words = [w for w in re.findall(r"[A-Za-z][A-Za-z\-]{2,}", case.get("question") or "")
             if w.lower() not in STOPWORDS and w.lower() not in GENERIC
             and w.lower() not in VERBS and w.lower() not in low_syms
             and not drop_isin.match(w.upper())
             and not any(w.lower() in n for n in names if n)]
    metric = [w for w in words if w.lower() in METRIC_WORDS]
    rest = [w for w in words if w.lower() not in METRIC_WORDS]
    return " ".join((metric[:2] + rest)[:4])


def case_terms(case: dict) -> str:
    stop = {"what", "which", "does", "from", "with", "that", "have", "this", "they", "there",
            "their", "about", "would", "could", "should", "been", "were", "when", "where",
            "than", "then", "also", "into", "over", "after", "before", "still", "actually",
            "give", "name", "compare", "build", "show", "much", "many", "same", "kind"}
    words = [w for w in re.findall(r"[A-Za-z][A-Za-z\-]{3,}", case.get("question") or "")
             if w.lower() not in stop]
    return " ".join(words[:4])


def commodity_of(case: dict) -> str | None:
    low = ((case.get("period") or "") + " " + (case.get("question") or "")).lower()
    for key, name in COMMODITY:
        if key in low:
            return name
    return None


def index_of(case: dict) -> str | None:
    txt = (case.get("question") or "") + " " + json.dumps(entities(case))
    for name in INDEXES:
        if name.lower() in txt.lower():
            return name
    return "Nifty 50" if "nifty" in txt.lower() else None


def theme_of(case: dict) -> str | None:
    low = ((case.get("question") or "") + " " + json.dumps(entities(case))).lower()
    for key, theme in THEMES.items():
        if key in low:
            return theme
    return None


# ------------------------------------------------------------------- tool calls
class Budget:
    def __init__(self, mid: str):
        self.mid, self.n, self.rows, self.spent = mid, 0, [], 0.0

    def call(self, tool: str, fn, *a, **kw):
        if self.n >= MAX_CALLS:
            raise RuntimeError(f"budget {MAX_CALLS} reached")
        t0 = time.perf_counter()
        try:
            out, err = fn(*a, **kw), None
        except Exception as exc:  # noqa: BLE001 - recorded, never raised
            out, err = None, f"{type(exc).__name__}: {exc}"[:200]
        dt = time.perf_counter() - t0
        self.n += 1
        self.spent += dt
        self.rows.append({"tool": tool, "args": {k: v for k, v in kw.items()} or list(a)[:3],
                          "s": round(dt, 2), "ok": err is None})
        return {"_error": err} if err else out


RESOLVE_CACHE: dict[str, str] = {}
SYM_NAMES: dict[str, str] = {}
TIMEOUTS: dict[str, int] = {}


def breaker_open(key: str) -> bool:
    return TIMEOUTS.get(key, 0) >= 3


def note_timeout(key: str) -> None:
    TIMEOUTS[key] = TIMEOUTS.get(key, 0) + 1


def resolve_symbol(b: Budget, sym: str) -> str:
    if sym in RESOLVE_CACHE:
        return RESOLVE_CACHE[sym]
    r = b.call("resolve", core.resolve, sym)
    isin, name = "", ""
    if isinstance(r, dict):
        for m in r.get("matches") or []:
            if sym in (m.get("nse_symbol"), m.get("bse_symbol")):
                isin = m.get("isin") or ""
                name = str(m.get("issuer") or m.get("name") or "")
                break
        if not isin and (r.get("matches") or []):
            isin = r["matches"][0].get("isin") or ""
            name = str(r["matches"][0].get("issuer") or r["matches"][0].get("name") or "")
    RESOLVE_CACHE[sym] = isin
    if name:
        SYM_NAMES[sym] = name
    return isin


def _num(v) -> float | None:
    try:
        return float(v)
    except Exception:  # noqa: BLE001
        return None


def is_timeout(r) -> bool:
    e = str((r or {}).get("_error") or "").lower()
    return "timeout" in e or "exceeded 15" in e or "budget" in e and "query" in e


METRIC_WORDS = {"npa", "margin", "margins", "revenue", "ebitda", "pat", "profit", "profits",
                "nii", "nim", "roe", "roce", "debt", "capex", "order", "orders", "guidance",
                "segment", "segments", "promoter", "pledge", "dividend", "ltv", "tax", "tariff",
                "approval", "launch", "commission", "commissioned", "capacity", "utilisation",
                "utilization", "spread", "cost", "costs", "sales", "volume", "volumes",
                "realisation", "realization", "growth", "backlog", "book", "receivable",
                "payable", "cash", "interest", "cover", "coverage", "premium", "nav",
                "tracking", "exposure", "holding", "stake", "acquisition", "plant", "facility",
                "facilities", "products", "product", "price", "prices", "rupee", "copper",
                "gold", "crude", "brent", "steel", "aluminium", "zinc", "coal", "inflation",
                "repo", "subsidy", "pli", "securitisation", "npa", "disbursement", "jv"}


def gates_of(kt: list[str]) -> list[str]:
    return [k for k in kt if k in METRIC_WORDS]


def term_hits(text: str, kt: list[str]) -> int:
    low = (text or "").lower()
    return sum(1 for k in kt if re.search(r"\b" + re.escape(k), low))


def relevant(text: str, kt: list[str]) -> bool:
    """Does the evidence carry the metric the question asks for?

    A chatty question ("is this a good level?") has no metric term, so the gate
    does not apply; a metric question must surface that metric, otherwise the tool
    returned a neighbouring fact rather than the answer.
    """
    low = (text or "").lower()
    g = gates_of(kt)
    if g:
        return sum(1 for k in g if re.search(r"\b" + re.escape(k), low)) >= 1
    if not kt:
        return True
    # a word asked for must appear as that word ("control" is not "controls")
    return sum(1 for k in kt if re.search(r"\b" + re.escape(k) + r"\b", low)) >= 1


def pick_fact(facts: list[dict], kt: list[str], need: int | None = None) -> dict | None:
    """The first fact row whose own text carries the ask (not just the symbol)."""
    need = min(2, len(kt)) if need is None else need
    for f in facts:
        blob = " ".join(str(f.get(k) or "") for k in
                        ("item", "metric", "statement", "textual_value", "quote", "category"))
        if not kt or term_hits(blob, kt) >= need:
            return f
    return None


def snippet(text: str, kt: list[str], width: int = 200) -> str:
    """A window around the first key term, so the quote shown is the one that matched."""
    low = text.lower()
    pos = [low.find(k) for k in kt if k and k in low]
    i = min(pos) if pos else 0
    lo = max(0, i - width // 3)
    out = " ".join(text[lo:lo + width].split())
    return ("..." if lo else "") + out


def detail_of(f: dict) -> str:
    """Readable one-line answer from a facts row of any store."""
    for key in ("item", "metric", "statement", "textual_value", "value_raw"):
        if f.get(key):
            return f"{key}: {str(f.get(key))[:110]}"
    return f"value {f.get('value')} {f.get('unit') or ''} ({f.get('period')})"


def hop_price(b: Budget, case: dict, sym: str | None) -> dict:
    start, end = period_range(case)
    if not sym:
        if not start:
            return {"ok": False, "why": "no_doc", "detail": "no date in the case"}
        order = "asc" if re.search(r"loser|fell|fall|drop|down", (case.get("question") or ""), re.I) else "desc"
        q = ("select symbol,date,close,prev_close,delivery_pct,value_inr from px_nse "
             f"where date='{start}' and series='EQ' and value_inr >= 50000000 "
             f"order by (close/prev_close) {order} limit 8")
        r = b.call("sql", core.sql, q, "truth", 8, 8.0)
        rows = (r or {}).get("rows") or []
        if not rows:
            return {"ok": False, "why": "no_doc",
                    "detail": f"no px_nse movers on {start} (market shut or no rows)"}
        bits = []
        for row in rows[:5]:
            chg = round((row[2] / row[3] - 1) * 100, 2) if row[3] else None
            bits.append(f"{row[0]} {row[2]} ({chg}%)")
        return {"ok": True,
                "detail": f"{'bottom' if order == 'asc' else 'top'} movers {start} "
                          f"(turnover >= 5 cr): " + ", ".join(bits),
                "evidence": [f"{start}:px_nse:movers"]}
    asof = case.get("as_of")
    if asof and end and end > str(asof)[:10]:
        end = str(asof)[:10]
    if not start:
        return {"ok": False, "why": "no_doc", "detail": "no date in the case to pin the price to"}
    r = b.call("price", core.price, sym, start, end)
    rows = (r or {}).get("rows") or []
    widened = False
    if not rows and start == end:
        import datetime as _dt
        lo = (_dt.date.fromisoformat(start) - _dt.timedelta(days=10)).isoformat()
        r = b.call("price", core.price, sym, lo, end)
        rows = (r or {}).get("rows") or []
        widened = bool(rows)
    if not rows:
        return {"ok": False, "why": "no_doc", "detail": f"price(): no {sym} row {start}..{end}"}
    row = rows[-1]
    close, prev = _num(row.get("close")), _num(row.get("prev_close"))
    chg = None
    if close is not None and prev:
        chg = round((close / prev - 1) * 100, 2)
    parts = [f"{sym} {row.get('date')} close {close}"]
    if chg is not None:
        parts.append(f"chg {chg}%")
    if row.get("delivery_pct") is not None:
        parts.append(f"delivery {row.get('delivery_pct')}%")
    if widened:
        parts.append(f"(no {start} session; last close on/before it)")
    return {"ok": True, "detail": ", ".join(parts) + f" [{len(rows)} rows]",
            "evidence": [f"{row.get('date')}:px:{row.get('exchange') or 'NSE'}"], "value": row}


def hop_extreme(b: Budget, case: dict, sym: str | None) -> dict:
    if not sym:
        return {"ok": False, "why": "no_doc", "detail": "no company in the case", "na": True}
    q = (case.get("question") or "").lower()
    kind = "low" if re.search(r"\b(low|lowest|bottom)\b", q) else "high"
    start, end = period_range(case)
    if "ytd" in q or "year to date" in q:
        start = f"{asof(case)[:4]}-01-01"
    r = b.call("price_extreme", lookups_market.price_extreme, sym, start, end, kind, False)
    if not (r or {}).get("found"):
        return {"ok": False, "why": "no_doc",
                "detail": f"price_extreme({kind}) found nothing for {sym} "
                          f"{(r or {}).get('hint') or (r or {}).get('status') or ''}"}
    ext = ((r or {}).get("extremes") or {}).get(kind) or {}
    if ext.get("value") is None:
        return {"ok": False, "why": "no_doc",
                "detail": f"price_extreme({kind}) returned no {kind} for {sym}"}
    return {"ok": True,
            "detail": f"{sym} {kind} {ext.get('date')}: {ext.get('value')} "
                      f"({ext.get('exchange')}) over {start}..{end or asof(case)}",
            "evidence": [f"{ext.get('date')}:price_extreme:{sym}"],
            "known_at": None}


def hop_delivery(b: Budget, case: dict, sym: str | None) -> dict:
    if not sym:
        return {"ok": False, "why": "no_doc", "detail": "no company in the case", "na": True}
    start, end = period_range(case)
    qdates = parse_date(case.get("question") or "")
    if qdates:
        start = qdates[0]
    if not start:
        return {"ok": False, "why": "no_doc", "detail": "no date in the case"}
    r = b.call("delivery", lookups_market.delivery, sym, [start[:10]], None)
    if not (r or {}).get("found"):
        return {"ok": False, "why": "no_doc",
                "detail": f"delivery(): {(r or {}).get('status') or 'no row'} for {sym} {start}"}
    rows = (r or {}).get("rows") or []
    totals = (r or {}).get("totals") or {}
    nse = (rows[0] or {}).get("nse") or {}
    bse = (rows[0] or {}).get("bse") or {}
    return {"ok": True,
            "detail": f"{sym} {start}: deliverable qty {totals.get('deliverable_qty')} on volume "
                      f"{totals.get('volume')} = {totals.get('delivery_pct')}% "
                      f"(NSE {nse.get('deliverable_qty')} qty / {nse.get('delivery_pct')}%, "
                      f"BSE {bse.get('deliverable_qty')} qty / {bse.get('delivery_pct')}%)",
            "evidence": [f"{start}:px_nse+px_bse:delivery:{sym}"]}


def hop_index(b: Budget, case: dict) -> dict:
    name = index_of(case)
    start, end = period_range(case)
    if not name or not start:
        return {"ok": False, "why": "no_doc", "detail": "no index/date in the case"}
    q = ("select date,index_name,close,pct_change from mkt_nse_index_daily "
         f"where index_name='{name}' and date between '{start}' and '{end or start}' "
         f"and date <= '{asof(case)}' order by date")
    r = b.call("sql", core.sql, q, "equity_intelligence", 20, 8.0)
    rows = (r or {}).get("rows") or []
    if not rows:
        return {"ok": False, "why": "schema", "detail": f"index {name} not held {start}..{end}",
                "gap": "G12"}
    last = rows[-1]
    detail = f"{last[1]} {last[0]} close {last[2]} ({last[3]}%)"
    if "dispersion" in (case.get("question") or "").lower() or "sector" in (case.get("question") or "").lower():
        q2 = ("select index_name,pct_change from mkt_nse_index_daily "
              f"where date='{last[0]}' and index_name like 'Nifty %' order by pct_change")
        r2 = b.call("sql", core.sql, q2, "equity_intelligence", 40, 8.0)
        spr = (r2 or {}).get("rows") or []
        if spr:
            detail += (f"; sector dispersion {spr[0][0]} {spr[0][1]}% .. "
                       f"{spr[-1][0]} {spr[-1][1]}% over {len(spr)} Nifty indices")
    return {"ok": True, "detail": detail, "evidence": [f"{last[0]}:index:{last[1]}"]}


def hop_commodity(b: Budget, case: dict) -> dict:
    name = commodity_of(case)
    start, end = period_range(case)
    if not name:
        return {"ok": False, "why": "schema", "detail": "no commodity named in the case", "gap": "G12"}
    lo = start or "2019-01-01"
    q = (f"select date,commodity,close from mkt_commodity_daily where commodity='{name}' "
         f"and date between '{lo}' and '{end or '2026-10-31'}' and date <= '{asof(case)}' "
         f"order by date")
    r = b.call("sql", core.sql, q, "equity_intelligence", 40, 8.0)
    rows = (r or {}).get("rows") or []
    if not rows:
        return {"ok": False, "why": "schema", "detail": f"no {name} row {lo}..{end}", "gap": "G12"}
    last = rows[-1]
    return {"ok": True, "detail": f"{name} {last[0]} close {last[2]} [{len(rows)} rows]",
            "evidence": [f"{last[0]}:commodity:{name}"]}


def hop_flows(b: Budget, case: dict) -> dict:
    start, end = period_range(case)
    lo = start or "2019-01-01"
    q = (f"select count(*),sum(fii_net_cr),sum(dii_net_cr),min(date),max(date) "
         f"from fii_dii_cash where date between '{lo}' and '{end or '2026-10-31'}' "
         f"and date <= '{asof(case)}'")
    r = b.call("sql", core.sql, q, "truth", 5, 8.0)
    rows = (r or {}).get("rows") or []
    if not rows or not rows[0][0]:
        return {"ok": False, "why": "schema", "detail": "no FII/DII rows in window", "gap": "NG18"}
    n, fii, dii, a, z = rows[0]
    return {"ok": True,
            "detail": f"FII net {round(fii or 0, 2)} cr, DII net {round(dii or 0, 2)} cr over "
                      f"{n} sessions {a}..{z}",
            "evidence": [f"{a}..{z}:fii_dii_cash"]}


def hop_qfin(b: Budget, case: dict, sym: str | None) -> dict:
    per = case.get("period") or ""
    start, end = period_range(case)
    kt = [k for k in (key_terms(case) or case_terms(case)).lower().split() if len(k) >= 3]
    r = b.call("facts", core.facts, sym, "results", per or None, 12) if sym else None
    facts = (r or {}).get("facts") or []
    f0 = pick_fact(facts, kt) if facts else None
    if facts and f0 is None:
        return {"ok": False, "why": "schema",
                "detail": f"results facts exist for {sym} but none carries the asked metric "
                          f"({', '.join(kt)}); the concept map does not expose it", "gap": "G11"}
    if f0 is not None:
        return {"ok": True,
                "detail": f"results fact {f0.get('period')}: {f0.get('item')} = "
                          f"{f0.get('value_cr') or f0.get('value')} {f0.get('unit') or ''}",
                "evidence": [f"{str(f0.get('date'))[:10]}:results_xbrl:{f0.get('doc_id')}"],
                "known_at": str(f0.get("date"))[:10] if f0.get("date") else None}
    if sym:
        q = (f"select quarter_end_date,revenue_inr_cr,ebitda_margin_pct,net_profit_inr_cr "
             f"from quarterly_financials where symbol='{sym}' order by quarter_end_date desc limit 4")
        r2 = b.call("sql", core.sql, q, "equity_intelligence", 4, 8.0)
        rows = (r2 or {}).get("rows") or []
        if rows:
            return {"ok": True,
                    "detail": f"quarterly_financials {rows[0][0]}: revenue {rows[0][1]} cr, "
                              f"EBITDA margin {rows[0][2]}%, PAT {rows[0][3]} cr",
                    "evidence": [f"{rows[0][0]}:quarterly_financials:{sym}"],
                    "partial_note": "stored series stops 2026-06-30; XBRL concept map unmapped"}
    return {"ok": False, "why": "schema", "detail": "no quarterly financial fact for the symbol/period",
            "gap": "G11"}


def hop_afin(b: Budget, case: dict, sym: str | None) -> dict:
    if not sym:
        return {"ok": False, "why": "no_doc", "detail": "no single company in the case", "na": True}
    q = (f"select fiscal_year,revenue_inr_cr,ebitda_inr_cr,net_profit_inr_cr,debt_to_equity,"
         f"interest_coverage,roce_pct from annual_financials where symbol='{sym}' "
         f"and fiscal_year <= 'FY{int(asof(case)[:4]) - (0 if int(asof(case)[5:7]) > 6 else 1)}' "
         f"order by fiscal_year desc limit 3")
    r = b.call("sql", core.sql, q, "equity_intelligence", 3, 8.0)
    rows = (r or {}).get("rows") or []
    if not rows:
        return {"ok": False, "why": "schema", "detail": f"annual_financials has no {sym}", "gap": "G11"}
    y, rev, ebitda, pat, de, ic, roce = rows[0]
    return {"ok": True,
            "detail": f"annual_financials {y}: revenue {rev} cr, EBITDA {ebitda} cr, PAT {pat} cr, "
                      f"D/E {de}, interest cover {ic}, ROCE {roce}%",
            "evidence": [f"{y}:annual_financials:{sym}"]}


def hop_ar(b: Budget, case: dict, sym: str | None) -> dict:
    if not sym:
        return {"ok": False, "why": "no_doc", "detail": "no single company in the case", "na": True}
    terms = key_terms(case) or case_terms(case)
    kt = [k for k in terms.lower().split() if len(k) >= 3]
    if case.get("answer_kind") in ("text+quote", "explanation", "list"):
        r = b.call("doc_find", lookups_docs.doc_find, sym, terms, "ar", None, 5)
        passages = (r or {}).get("passages") or (r or {}).get("hits") or []
        passages = [p for p in passages
                    if relevant(str(p.get("quote") or p.get("text") or ""), kt)]
        if passages:
            p0 = passages[0]
            return {"ok": True,
                    "detail": f"AR passage: {snippet(str(p0.get('quote') or p0.get('text') or ''), kt)}",
                    "evidence": [f"{p0.get('date')}:ar_chunk:{sym}"],
                    "known_at": str(p0.get("date"))[:10] if p0.get("date") else None}
    if breaker_open("facts_ar"):
        return {"ok": False, "why": "tool",
                "detail": "facts(kind='ar') timed out at the 15 s read-only budget on 3 attempts; "
                          "circuit opened", "gap": "G6"}
    r = b.call("facts", core.facts, sym, "ar", case.get("period") or None, 8)
    if is_timeout(r):
        note_timeout("facts_ar")
        r2 = b.call("doc_find", lookups_docs.doc_find, sym, terms, "ar", None, 5)
        passages = (r2 or {}).get("passages") or (r2 or {}).get("hits") or []
        passages = [p for p in passages
                    if relevant(str(p.get("quote") or p.get("text") or ""), kt)]
        if passages:
            p0 = passages[0]
            return {"ok": True,
                    "detail": f"AR passage (doc_find fallback): "
                              f"{snippet(str(p0.get('quote') or p0.get('text') or ''), kt)}",
                    "evidence": [f"{p0.get('date')}:ar_chunk:{sym}"],
                    "known_at": str(p0.get("date"))[:10] if p0.get("date") else None}
        return {"ok": False, "why": "tool",
                "detail": "facts(kind='ar') hit the 15 s read-only budget on the 32M-row AR fact "
                          "store, and doc_find found no passage; the AR text is held but not "
                          "reachable in time", "gap": "G6"}
    facts = (r or {}).get("facts") or []
    f0 = pick_fact(facts, kt) if facts else None
    if f0 is None:
        r = b.call("docs", lookups_docs.docs, sym, "ar", None, None, 3)
        entries = (r or {}).get("documents") or []
        if entries:
            return {"ok": False, "why": "tool",
                    "detail": f"AR is held ({str(entries[0].get('title'))[:60]}, "
                              f"{entries[0].get('date')}) but no fact/passage carries the ask "
                              f"({', '.join(kt)})", "evidence": [f"{entries[0].get('date')}:ar:{sym}"],
                    "gap": "G6"}
        return {"ok": False, "why": "no_doc", "detail": f"no annual report held for {sym}", "gap": "U-DOC"}
    return {"ok": True,
            "detail": f"AR fact {f0.get('period')}: {detail_of(f0)} ({f0.get('doc_id')})",
            "evidence": [f"{str(f0.get('date'))[:10]}:ar_facts:{f0.get('doc_id')}"],
            "known_at": str(f0.get("date"))[:10] if f0.get("date") else None}


def hop_deck(b: Budget, case: dict, sym: str | None) -> dict:
    if not sym:
        return {"ok": False, "why": "no_doc", "detail": "no company in the case", "na": True}
    kt = [k for k in (key_terms(case) or case_terms(case)).lower().split() if len(k) >= 3]
    if case.get("answer_kind") in ("text+quote", "explanation", "list"):
        r = b.call("doc_find", lookups_docs.doc_find, sym, key_terms(case) or case_terms(case),
                   "deck", None, 5)
        passages = (r or {}).get("passages") or (r or {}).get("hits") or []
        passages = [p for p in passages
                    if relevant(str(p.get("quote") or p.get("text") or ""), kt)]
        if passages:
            p0 = passages[0]
            return {"ok": True,
                    "detail": f"deck passage: {snippet(str(p0.get('quote') or p0.get('text') or ''), kt)}",
                    "evidence": [f"{p0.get('date')}:deck:{sym}"],
                    "known_at": str(p0.get("date"))[:10] if p0.get("date") else None}
    r = b.call("facts", core.facts, sym, "deck", case.get("period") or None, 8)
    facts = (r or {}).get("facts") or []
    f0 = pick_fact(facts, kt)
    if not facts:
        return {"ok": False, "why": "no_doc", "detail": "no deck figure for the symbol/period",
                "gap": "NG13"}
    if f0 is None:
        return {"ok": False, "why": "schema",
                "detail": f"deck facts exist for {sym} but none carries the ask "
                          f"({', '.join(kt)}); the metric is not extracted from the slide",
                "gap": "NG13"}
    return {"ok": True, "detail": f"deck fact: {f0.get('item')} = {f0.get('value')} "
                                  f"{f0.get('unit') or ''}",
            "evidence": [f"{str(f0.get('date'))[:10]}:deck:{f0.get('doc_id')}"],
            "known_at": str(f0.get("date"))[:10] if f0.get("date") else None}


def hop_concall(b: Budget, case: dict, sym: str | None) -> dict:
    if not sym:
        return {"ok": False, "why": "no_doc", "detail": "no company in the case"}
    if breaker_open("facts_concall"):
        return {"ok": False, "why": "tool",
                "detail": "facts(kind='guidance'/'concall') timed out at the 15 s read-only budget "
                          "on 3 attempts; circuit opened", "gap": "G6"}
    for kind, period in (("guidance", None), ("concall", case.get("period") or None)):
        r = b.call("facts", core.facts, sym, kind, period, 8)
        if is_timeout(r):
            note_timeout("facts_concall")
            return {"ok": False, "why": "tool",
                    "detail": f"facts(kind='{kind}') hit the 15 s read-only budget; the concall "
                              f"store is held but the fact tool cannot serve it in time", "gap": "G6"}
        facts = (r or {}).get("facts") or []
        kt = [k for k in (key_terms(case) or case_terms(case)).lower().split() if len(k) >= 3]
        f0 = pick_fact(facts, kt) if facts else None
        if f0 is not None:
            return {"ok": True,
                    "detail": f"{kind} {f0.get('period')}: {detail_of(f0)}",
                    "evidence": [f"{str(f0.get('date'))[:10]}:{kind}:{f0.get('doc_id')}"],
                    "known_at": str(f0.get("date"))[:10] if f0.get("date") else None}
    r = b.call("doc_find", lookups_docs.doc_find, sym,
               key_terms(case) or case_terms(case), "transcript", None, 5)
    passages = (r or {}).get("passages") or (r or {}).get("hits") or []
    passages = [p for p in passages
                if relevant(str(p.get("quote") or p.get("text") or ""),
                            [k for k in (key_terms(case) or case_terms(case)).lower().split()
                             if len(k) >= 3])]
    if passages:
        p0 = passages[0]
        return {"ok": True,
                "detail": f"transcript passage: "
                          f"{snippet(str(p0.get('quote') or p0.get('text') or ''), [])}",
                "evidence": [f"{p0.get('date')}:transcript:{sym}"],
                "known_at": str(p0.get("date"))[:10] if p0.get("date") else None}
    r = b.call("docs", lookups_docs.docs, sym, "transcript", None, None, 3)
    entries = (r or {}).get("documents") or []
    if entries:
        return {"ok": False, "why": "tool",
                "detail": f"{len(entries)} transcript(s) held (latest {entries[0].get('date')}) "
                          f"but doc_find found no passage carrying the ask "
                          f"({', '.join(key_terms(case).split()[:3])})", "gap": "G6"}
    return {"ok": False, "why": "no_doc",
            "detail": "no concall/guidance item or transcript held for the symbol/period",
            "gap": "U-DOC"}


def hop_docs(b: Budget, case: dict, sym: str | None) -> dict:
    terms = key_terms(case) or case_terms(case)
    kt = [k for k in terms.lower().split() if len(k) >= 3]
    if sym:
        r = b.call("doc_find", lookups_docs.doc_find, sym, terms, None, None, 5)
        passages = (r or {}).get("passages") or (r or {}).get("hits") or []
        if not passages:
            r = b.call("docs", lookups_docs.docs, sym, None, None, None, 5)
            entries = (r or {}).get("documents") or []
            if entries:
                return {"ok": False, "why": "tool",
                        "detail": f"doc_find('{terms}') returned no passage; docs() lists "
                                  f"{len(entries)} documents with no reachable text for the ask",
                        "evidence": [f"docs:{sym}:{len(entries)}"]}
            return {"ok": False, "why": "no_doc", "detail": f"no document held for {sym}", "gap": "U-DOC"}
        ranked = [p for p in passages
                  if relevant(str(p.get("quote") or p.get("text") or ""), kt)]
        if not ranked:
            return {"ok": False, "why": "tool",
                    "detail": f"doc_find('{terms}') matched documents but no passage mentions "
                              f"any of: {', '.join(kt) or 'the ask'}", "gap": "G6"}
        p0 = ranked[0]
        quote = str(p0.get("quote") or p0.get("text") or "")
        return {"ok": True, "detail": snippet(quote, kt),
                "evidence": [f"{p0.get('date')}:{p0.get('doc_type')}:{p0.get('doc_id')}:p{p0.get('page')}"],
                "known_at": str(p0.get("date"))[:10] if p0.get("date") else None}
    r = b.call("search_docs", search_docs.search_docs, terms, None, None, None, None, 5,
               case.get("as_of"))
    hits = r if isinstance(r, list) else ((r or {}).get("results") or (r or {}).get("hits") or [])
    if not hits:
        return {"ok": False, "why": "no_doc", "detail": f"search_docs('{terms}') returned nothing",
                "gap": "U-OTHER"}
    ranked = [h for h in hits if relevant(str(h.get("text") or ""), kt)]
    if not ranked:
        return {"ok": False, "why": "tool",
                "detail": f"search_docs('{terms}') returned {len(hits)} passages, none naming "
                          f"the ask ({', '.join(kt)})", "gap": "G6"}
    h0 = ranked[0]
    return {"ok": True, "detail": snippet(str(h0.get("text") or ""), kt),
            "evidence": [f"{h0.get('date')}:{h0.get('doc_type')}:{h0.get('doc_id')}"],
            "known_at": str(h0.get("date"))[:10] if h0.get("date") else None}


def hop_search(b: Budget, case: dict, sym: str | None = None) -> dict:
    if breaker_open("search_docs_slow"):
        return {"ok": False, "why": "tool",
                "detail": "search_docs exceeded 20 s on 3 attempts (FTS fallback, dense path "
                          "unavailable); circuit opened for the rest of the run", "gap": "G6"}
    return hop_docs(b, case, sym)


def hop_policy(b: Budget, case: dict) -> dict:
    q = case.get("question") or ""
    tmpl = str(case.get("template") or "")
    ids = [a or c for a, c in re.findall(r"id=(\d+)|policy_events\.id=(\d+)", q + " " + tmpl)]
    if ids:
        cond = "id in (" + ",".join(ids[:4]) + ")"
    else:
        stop = {"what", "which", "does", "with", "from", "this", "that", "they", "have",
                "announced", "listed", "companies", "company", "reaches", "sectors", "channel",
                "policy", "impact"}
        words = [w for w in re.findall(r"[A-Za-z]{4,}", q) if w.lower() not in stop][:3]
        cond = ("(" + " or ".join(f"lower(title) like '%{w.lower()}%'" for w in words) + ")") if words else "1=1"
    q2 = ("select id, published_at, policy_name, title, direction_for_industry, amount_inr_crore, "
          f"sectors, quote_ok from policy_events where {cond} "
          f"and published_at <= '{asof(case)}' order by published_at desc limit 5")
    r = b.call("sql", core.sql, q2, "truth", 5, 8.0)
    rows = (r or {}).get("rows") or []
    if not rows:
        return {"ok": False, "why": "schema", "detail": "no policy_events row matched the question",
                "gap": "G10"}
    kt = [k for k in (key_terms(case) or case_terms(case)).lower().split() if len(k) >= 3]
    ranked = []
    for row in rows:
        blob = f"{row[2] or ''} {row[3] or ''} {row[6] or ''}".lower()
        ranked.append((sum(1 for k in kt if re.search(r"\b" + re.escape(k), blob)), row))
    ranked.sort(key=lambda x: -x[0])
    if kt and (not ranked or ranked[0][0] == 0):
        return {"ok": False, "why": "schema",
                "detail": f"policy_events matched '{', '.join(kt)}' loosely but no row carries "
                          f"the ask (nearest: {str(rows[0][3] or rows[0][2])[:70]})", "gap": "G10"}
    row = ranked[0][1] if ranked else rows[0]
    return {"ok": True,
            "detail": f"policy_events id={row[0]} {str(row[1])[:10]}: {str(row[2] or row[3] or '')[:60]} "
                      f"({row[4]}, Rs {row[5]} cr, sectors {str(row[6])[:40]}, quote_ok={row[7]})",
            "evidence": [f"{str(row[1])[:10]}:policy_events:{row[0]}"]}


def hop_universe(b: Budget, case: dict) -> dict:
    theme = theme_of(case)
    if not theme:
        return {"ok": False, "why": "schema", "detail": "no theme named in the case", "gap": "G5"}
    r = b.call("universe", universe_mod.universe, theme, case.get("as_of"), 0.01)
    members = (r or {}).get("members") or []
    if not members:
        err = (r or {}).get("error") or {}
        return {"ok": False, "why": "schema",
                "detail": f"theme '{theme}' is defined but has no membership rows "
                          f"({err.get('message') or 'not built'})", "gap": "G5"}
    return {"ok": True, "detail": f"theme {theme}: {len(members)} members", "evidence": [f"theme:{theme}"]}


def hop_holding(b: Budget, case: dict, sym: str | None) -> dict:
    if not sym:
        return {"ok": False, "why": "no_doc", "detail": "no company in the case", "na": True}
    r = b.call("holding", lookups_market.holding, sym, case.get("as_of"))
    if not (r or {}).get("found"):
        return {"ok": False, "why": "schema",
                "detail": (r or {}).get("hint") or "no shareholding row", "gap": "NG05"}
    return {"ok": True,
            "detail": f"promoter {r.get('promoter_pct')}%, public {r.get('public_pct')}%, "
                      f"quarter {(r.get('shareholding') or {}).get('quarter_end')}",
            "evidence": [f"{(r.get('shareholding') or {}).get('quarter_end')}:shp_index:{r.get('isin')}"]}


def hop_opinion(b: Budget, case: dict, sym: str | None) -> dict:
    if not sym:
        q = ("select audit_opinion,count(*) from results_filings where audit_opinion is not null "
             f"and period_end <= '{asof(case)}' group by 1 order by 2 desc limit 6")
        r = b.call("sql", core.sql, q, "truth", 6, 8.0)
        rows = (r or {}).get("rows") or []
        if not rows:
            return {"ok": False, "why": "schema",
                    "detail": "results_filings.audit_opinion is empty across all filings; audit "
                              "opinion detail is not extracted", "gap": "NG02"}
        return {"ok": True, "detail": "audit_opinion counts: " +
                ", ".join(f"{a or 'blank'}={n}" for a, n in rows),
                "evidence": [f"results_filings.audit_opinion:market"]}
    q = (f"select symbol,period_end,dissem_ts,audit_opinion from results_filings "
         f"where symbol='{sym}' order by period_end desc limit 3")
    r = b.call("sql", core.sql, q, "truth", 3, 8.0)
    rows = (r or {}).get("rows") or []
    if not rows:
        return {"ok": False, "why": "schema", "detail": f"no results filing for {sym}", "gap": "NG02"}
    row = rows[0]
    if row[3] in (None, ""):
        return {"ok": False, "why": "schema",
                "detail": f"results_filings.audit_opinion is empty for {sym} ({row[1]})", "gap": "NG02"}
    return {"ok": True, "detail": f"audit_opinion {row[1]}: '{row[3]}' (dissem {row[2]})",
            "evidence": [f"{str(row[2])[:10]}:results_filings:{sym}"]}


def hop_corp_action(b: Budget, case: dict, sym: str | None) -> dict:
    start, end = period_range(case)
    q = "select symbol,ex_date,action_type,subject from corporate_actions where 1=1"
    if sym:
        q += f" and symbol='{sym}'"
    if start:
        q += f" and ex_date between '{start}' and '{end or start}'"
    q += f" and ex_date <= '{asof(case)}'"
    r = b.call("sql", core.sql, q + " limit 5", "truth", 5, 8.0)
    rows = (r or {}).get("rows") or []
    if not rows and sym:
        r = b.call("sql", core.sql,
                   f"select symbol,ex_date,action_type,subject from corporate_actions where "
                   f"symbol='{sym}' order by ex_date desc limit 3", "truth", 3, 8.0)
        rows = (r or {}).get("rows") or []
    if not rows:
        return {"ok": False, "why": "no_doc", "detail": "no corporate action row", "gap": "U-OTHER"}
    row = rows[0]
    return {"ok": True, "detail": f"corp action {row[0]} {row[1]}: {row[3]} ({row[2]})",
            "evidence": [f"{row[1]}:corporate_actions:{row[0]}"]}


def hop_bands(b: Budget, case: dict, sym: str | None) -> dict:
    start, end = period_range(case)
    if not sym:
        q = ("select band,count(*) from price_bands where 1=1"
             + (f" and date between '{start}' and '{end or start}'" if start else "")
             + f" and date <= '{asof(case)}' group by band order by 2 desc")
        r = b.call("sql", core.sql, q, "truth", 12, 8.0)
        rows = (r or {}).get("rows") or []
        if not rows:
            return {"ok": False, "why": "schema",
                    "detail": "no price_bands rows for the date window", "gap": "G8"}
        return {"ok": True,
                "detail": f"price band distribution {start}: " + ", ".join(f"{a}={n}" for a, n in rows[:6]),
                "evidence": [f"{start}:price_bands:distribution"]}
    q = "select date,symbol,series,band,remarks from price_bands"
    if sym:
        q += f" where symbol='{sym}'"
    elif start:
        q += f" where date between '{start}' and '{end or start}'"
    else:
        q += " where 1=1"
    q += f" and date <= '{asof(case)}'"
    r = b.call("sql", core.sql, q + " order by date desc limit 5", "truth", 5, 8.0)
    rows = (r or {}).get("rows") or []
    if not rows:
        return {"ok": False, "why": "schema", "detail": "price_bands empty for the ask", "gap": "G8"}
    row = rows[0]
    return {"ok": True, "detail": f"price band {row[1]} {row[0]}: {row[3]} ({row[4]})",
            "evidence": [f"{row[0]}:price_bands:{row[1]}"]}


def hop_deals(b: Budget, case: dict, sym: str | None) -> dict:
    start, end = period_range(case)
    q = "select count(*),sum(quantity),min(deal_date),max(deal_date) from bulk_block_deals where 1=1"
    if sym:
        q += f" and symbol='{sym}'"
    if start:
        q += f" and deal_date between '{start}' and '{end or start}'"
    q += f" and deal_date <= '{asof(case)}'"
    r = b.call("sql", core.sql, q, "equity_intelligence", 5, 8.0)
    rows = (r or {}).get("rows") or []
    if not rows or not rows[0][0]:
        return {"ok": False, "why": "no_doc", "detail": "no bulk/block deal in the window",
                "gap": "U-STORE"}
    n, qty, a, z = rows[0]
    return {"ok": True, "detail": f"bulk/block deals {n} rows, qty {qty}, {a}..{z}",
            "evidence": [f"{a}..{z}:bulk_block_deals"]}


def hop_insider(b: Budget, case: dict, sym: str | None) -> dict:
    q = "select count(*),min(trade_from),max(trade_to) from insider_trades_v2"
    if sym:
        q += f" where symbol='{sym}'"
    else:
        q += " where 1=1"
    q += f" and trade_to <= '{asof(case)}'"
    r = b.call("sql", core.sql, q, "equity_intelligence", 5, 8.0)
    rows = (r or {}).get("rows") or []
    if not rows or not rows[0][0]:
        return {"ok": False, "why": "schema", "detail": "insider store empty for the entity", "gap": "NG06"}
    return {"ok": True, "detail": f"insider_trades_v2 {rows[0][0]} rows {rows[0][1]}..{rows[0][2]}",
            "evidence": [f"{rows[0][2]}:insider_trades_v2:{sym or 'all'}"]}


def hop_etf(b: Budget, case: dict, sym: str | None) -> dict:
    start, end = period_range(case)
    q = "select date,symbol,close,nav,premium_pct from etf_premium_daily where 1=1"
    if sym:
        q += f" and symbol='{sym}'"
    if start:
        q += f" and date between '{start}' and '{end or start}'"
    r = b.call("sql", core.sql, q + " order by date desc limit 6", "equity_intelligence", 6, 8.0)
    rows = (r or {}).get("rows") or []
    if not rows:
        return {"ok": False, "why": "schema", "detail": "no ETF premium row for the ETF/date", "gap": "G0"}
    row = rows[0]
    prem = None
    try:
        prem = abs(float(row[4]))
    except (TypeError, ValueError):
        pass
    out = {"ok": True, "detail": f"ETF {row[1]} {row[0]} close {row[2]}, nav {row[3]}, "
                                 f"premium {row[4]}%",
           "evidence": [f"{row[0]}:etf_premium_daily:{row[1]}"]}
    if prem is not None and prem > 25:
        out["warn"] = (f"premium {row[4]}% is implausible (MONQ50 series runs -7%..235%, "
                       f"NIFTYBEES -90%..7%); the NAV join is broken for some rows")
    return out


SCREEN_COLS = [("interest cover", "interest_coverage"), ("ebitda margin", "ebitda_margin_pct"),
               ("operating margin", "ebitda_margin_pct"), ("margin", "ebitda_margin_pct"),
               ("pat margin", "pat_margin_pct"), ("roe", "roe_pct"), ("roce", "roce_pct"),
               ("debt", "debt_to_equity"), ("revenue", "revenue_inr_cr"),
               ("profit", "net_profit_inr_cr"), ("ebitda", "ebitda_inr_cr")]


def hop_screen(b: Budget, case: dict) -> dict:
    q = (case.get("question") or "").lower()
    col, table, datecol, named = "ebitda_margin_pct", "quarterly_financials", "quarter_end_date", False
    for key, c in SCREEN_COLS:
        if key in q:
            col, named = c, True
            if c in ("roe_pct", "roce_pct", "debt_to_equity", "interest_coverage"):
                table, datecol = "annual_financials", "fiscal_year"
            break
    if not named:
        return {"ok": False, "why": "schema",
                "detail": f"no stored column answers a screen for "
                          f"'{key_terms(case) or case_terms(case)}'; the metric is not in any "
                          f"table (only revenue/margin/PAT/ROE/ROCE/debt are)", "gap": "metric_series"}
    order = "desc" if not re.search(r"weakest|lowest|worst|thin|least|fail", q) else "asc"
    bucket = ""
    if "mid-cap" in q or "mid cap" in q or "midcap" in q:
        bucket = " and symbol in (select nse_symbol from master_companies where upper(market_cap_tier)='MID')"
    elif "small-cap" in q or "small cap" in q or "smallcap" in q:
        bucket = " and symbol in (select nse_symbol from master_companies where upper(market_cap_tier)='SMALL')"
    elif "large-cap" in q or "large cap" in q or "largecap" in q:
        bucket = " and symbol in (select nse_symbol from master_companies where upper(market_cap_tier)='LARGE')"
    if table == "annual_financials":
        fy = f"FY{int(asof(case)[:4]) - (0 if int(asof(case)[5:7]) > 6 else 1)}"
        where = f"fiscal_year <= '{fy}'"
    else:
        where = (f"quarter_end_date = (select max(quarter_end_date) from quarterly_financials "
                 f"where quarter_end_date <= '{asof(case)}')")
    sane = f" and {col} between -100 and 100" if col.endswith("_pct") else ""
    q2 = (f"select symbol,{datecol},{col} from {table} where {where} and {col} is not null{sane}"
          f"{bucket} order by {col} {order} limit 8")
    r = b.call("sql", core.sql, q2, "equity_intelligence", 8, 8.0)
    rows = (r or {}).get("rows") or []
    if not rows:
        return {"ok": False, "why": "schema",
                "detail": f"{table} has no usable {col} rows for a market-wide screen", "gap": "metric_series"}
    bits = [f"{a[0]} {a[2]}" for a in rows[:5]]
    return {"ok": True,
            "detail": f"screen {col} {order} ({rows[0][1]}): " + ", ".join(bits),
            "evidence": [f"{rows[0][1]}:{table}:screen"],
            "partial_note": "single stored metric; no joined peer/universe table"}


def hop_page(b: Budget, case: dict, sym: str | None) -> dict:
    if not sym:
        return {"ok": False, "why": "no_doc", "detail": "no company in the case", "na": True}
    q = case.get("question") or ""
    m = re.search(r"page\s+(\d+)", q, re.I)
    dates = parse_date(str(case.get("period") or "") + " " + q)
    if not m or not dates:
        return {"ok": False, "why": "no_doc", "detail": "no page number and date in the ask"}
    r = b.call("doc_page", lookups_docs.doc_page, sym, dates[0], int(m.group(1)), None)
    text = str((r or {}).get("text") or "")
    if not (r or {}).get("found") and not text:
        return {"ok": False, "why": "no_doc",
                "detail": f"doc_page: {(r or {}).get('hint') or 'no page text'}", "gap": "U-DOC"}
    doc = (r or {}).get("document") or {}
    return {"ok": True,
            "detail": f"page {m.group(1)} of {doc.get('title') or dates[0]}: "
                      f"{' '.join(text.split())[:180]}",
            "evidence": [f"{doc.get('date') or dates[0]}:doc_page:{sym}:p{m.group(1)}"]}


def hop_nodata(b: Budget, case: dict) -> dict:
    return {"ok": False, "why": "no_doc",
            "detail": "the bank marks this ask NOT IN DATA (forecast/consensus/hindsight); no "
                      "store holds it, and nothing we fetch would answer it either", "gap": "NG16"}


def hop_expectations(b: Budget, case: dict) -> dict:
    return {"ok": False, "why": "schema",
            "detail": "no consensus / target-price / valuation-advice store; the price, "
                      "ownership and commentary exist but the judgement this ask wants "
                      "is not in the data", "gap": "NG16"}


def hop_tech(b: Budget, case: dict) -> dict:
    q = (case.get("question") or "").lower()
    if any(k in q for k in ("open interest", "max pain", "pcr", "oi buildup")):
        return {"ok": False, "why": "schema",
                "detail": "no derivatives/OI store (no F&O bhavcopy, no participant-level OI); "
                          "only cash-market OHLCV and delivery are held", "gap": "G3"}
    return {"ok": False, "why": "schema",
            "detail": "no intraday bars and no technical-feature table; daily OHLCV + delivery "
                      "exist but a gap/RSI/support level cannot be computed from them alone",
            "gap": "G3"}


def hop_segment(b: Budget, case: dict, sym: str | None) -> dict:
    r = b.call("sql", core.sql,
               "select name from sqlite_master where type in ('table','view') "
               "and name like '%segment%'", "equity_intelligence", 10, 8.0)
    rows = (r or {}).get("rows") or []
    if rows:
        return {"ok": False, "why": "tool",
                "detail": f"segment table {rows[0][0]} exists but no tool/field maps XBRL contexts",
                "gap": "segment_pnl"}
    return {"ok": False, "why": "schema",
            "detail": "no segment P&L table or field in any store; XBRL segment contexts unmapped",
            "gap": "segment_pnl"}


HOPS = {"price": hop_price, "index": hop_index, "commodity": hop_commodity, "flows": hop_flows,
        "qfin": hop_qfin, "afin": hop_afin, "ar": hop_ar, "deck": hop_deck,
        "concall": hop_concall, "docs": hop_docs, "search": hop_search, "policy": hop_policy,
        "universe": hop_universe, "holding": hop_holding, "opinion": hop_opinion,
        "corp_action": hop_corp_action, "bands": hop_bands, "deals": hop_deals,
        "insider": hop_insider, "etf": hop_etf, "segment": hop_segment,
        "screen": hop_screen, "tech": hop_tech, "page": hop_page, "delivery": hop_delivery, "extreme": hop_extreme, "nodata": hop_nodata,
        "expectations": hop_expectations}


# ---------------------------------------------------------------------- grading
def words_of(text: str) -> list[str]:
    return re.findall(r"[A-Za-z]{4,}", text.lower())


def gt_verdict(case: dict, answer: str) -> tuple[str | None, str | None]:
    """Return (verdict, note); verdict in {match, unverified, contradict}.

    WRONG needs the same context: the ground truth and the answer must share a
    date and a named subject, and then their numbers must disagree.  A number the
    answer never claimed (a different window, a different metric) is not a
    contradiction, it is an unverified answer.
    """
    gt = rub(case).get("ground_truth")
    if not gt:
        return None, None
    gt = gt if isinstance(gt, str) else json.dumps(gt)

    def nums(text: str) -> list[float]:
        t2 = re.sub(r"\d{4}-\d{2}-\d{2}", " ", text)
        out = []
        for x in re.findall(r"(?<![A-Za-z0-9])-?\d[\d,]*(?:\.\d+)?(?![A-Za-z0-9])", t2):
            try:
                out.append(float(x.replace(",", "")))
            except ValueError:
                continue
        return out

    gv, av = nums(gt), nums(answer)
    if gv:
        av_any = [x for x in av if abs(x) >= 0.01]
        for g in gv:
            if any(abs(g - a) <= max(0.02, abs(g) * 0.02) for a in av_any):
                return "match", None
    else:
        gtw = set(words_of(gt)) - {"that", "with", "from", "this", "have", "were", "been", "will"}
        hit = gtw & set(words_of(answer))
        if len(hit) >= 3 and len(hit) / max(1, len(gtw)) > 0.35:
            return "match", None

    dates = set(re.findall(r"\d{4}-\d{2}-\d{2}", gt))
    gtw_all = set(words_of(gt)) - {"that", "with", "from", "this", "have", "were", "been", "will",
                                   "closed", "close", "rows", "null", "none", "holds"}
    same_date = bool(dates and any(d in answer for d in dates))
    overlap = gtw_all & set(words_of(answer))
    if gv and av and same_date and len(overlap) >= 2:
        return "contradict", (f"same date and subject, different value from the rubric ground "
                              f"truth ({gt[:90]})")
    if gv:
        return "unverified", f"answer does not carry the ground-truth value yet ({gt[:90]})"
    return "unverified", f"answer not verified against the rubric ground truth ({gt[:90]})"


def finish(case: dict, b: Budget, results: list[dict]) -> dict:
    ok = [r for r in results if r.get("ok")]
    bad = [r for r in results if not r.get("ok") and not r.get("na")]
    na = [r for r in results if r.get("na")]
    answer = "; ".join(str(r.get("detail") or "") for r in ok) if ok else ""
    if bad and ok:
        answer += " | MISSING: " + "; ".join(f"{r['hop']}: {r.get('detail')}" for r in bad)

    if not results:
        grade, blocker = "NOT_IN_DATA", "no source in the bank, and no tool serves this ask"
    elif not bad:
        grade, blocker = "ANSWERED", None
    elif ok:
        grade, blocker = "PARTIAL", f"hop failed: {bad[0]['hop']} ({bad[0].get('detail')})"
    else:
        why = bad[0].get("why")
        if why == "tool":
            grade, blocker = "BLOCKED_TOOL", bad[0].get("detail")
        elif why == "budget":
            grade, blocker = "PARTIAL", "tool-call budget hit"
        elif why == "schema":
            grade, blocker = "BLOCKED_SCHEMA", bad[0].get("detail")
        elif why == "no_doc":
            grade, blocker = "NOT_IN_DATA", bad[0].get("detail")
        else:
            grade, blocker = "PARTIAL", bad[0].get("detail")

    # PIT: a case with as_of may not be answered from evidence published after it
    asof = str(case.get("as_of") or "")[:10]
    pit = []
    if asof:
        for r in ok:
            for e in (r.get("evidence") or []):
                m = re.match(r"(\d{4}-\d{2}-\d{2})", str(e))
                if m and m.group(1) > asof:
                    pit.append(f"{r['hop']} evidence {m.group(1)} > as_of {asof}")
            if r.get("pit_note"):
                pit.append(f"{r['hop']}: {r['pit_note']}")
    if pit and grade == "ANSWERED":
        grade = "PARTIAL"
        blocker = (blocker + "; " if blocker else "") + "PIT: " + "; ".join(pit[:2])

    warn = [r.get("warn") for r in ok if r.get("warn")]
    if warn and grade == "ANSWERED":
        grade = "PARTIAL"
        blocker = f"implausible measurement: {warn[0]}"

    if grade == "ANSWERED" and case.get("answer_kind") in ("list", "ranking"):
        names = {n for n in re.findall(r"\b[A-Z][A-Z0-9&\-]{2,}\b", answer)} - {
            "AND", "NOT", "THE", "FY", "NSE", "BSE"}
        if len(names) < 2:
            grade = "PARTIAL"
            blocker = "one entity's evidence cannot answer a list/ranking ask"

    gt, gt_note = gt_verdict(case, answer)
    if gt == "contradict":
        grade = "WRONG"
        blocker = gt_note
    elif gt == "unverified" and grade == "ANSWERED":
        grade = "PARTIAL"
        blocker = gt_note

    slow = [c for c in b.rows if c["s"] > SLOW_S]
    return {
        "mid": case["mid"],
        "grade": grade,
        "answer": (answer or "no held answer")[:420],
        "evidence": [str(e) for r in ok for e in (r.get("evidence") or [])][:6],
        "tools": [c["tool"] for c in b.rows],
        "tool_calls": b.n,
        "seconds": round(b.spent, 2),
        "blocker": (blocker or "")[:400] or None,
        "gap": bad[0].get("gap") if bad else None,
        "hops_ok": [r["hop"] for r in ok],
        "hops_failed": [r["hop"] for r in bad],
        "hops_na": [r["hop"] for r in na],
        "pit": pit[:3],
        "gt": gt,
        "slow": slow,
        "family": case.get("family"),
        "entity_level": case.get("entity_level"),
        "source_bank": case.get("source_bank"),
        "regression": bool(case.get("regression")),
        "question": case.get("question"),
        "as_of": case.get("as_of"),
        "period": case.get("period"),
        "answer_kind": case.get("answer_kind"),
        "template": case.get("template"),
        "calls": b.rows,
    }


def run_case(case: dict) -> dict:
    b = Budget(case["mid"])
    hops = plan_hops(case)
    sym = probe_symbol(case)
    if sym:
        resolve_symbol(b, sym)
    results = []
    for hop in hops:
        fn = HOPS.get(hop)
        if fn is None:
            results.append({"hop": hop, "ok": False, "why": "schema",
                            "detail": "no probe for hop"})
            continue
        try:
            res = fn(b, case, sym) if hop in SYM_HOPS else fn(b, case)
        except RuntimeError as exc:
            results.append({"hop": hop, "ok": False, "why": "budget", "detail": str(exc)})
            break
        res["hop"] = hop
        results.append(res)
    return finish(case, b, results)


def main(argv: list[str]) -> int:
    cases = load_cases()
    gaps, mid_gap = gap_map()
    only = {a for a in argv[1:] if re.match(r"MB\d{4}", a)}
    t0 = time.perf_counter()
    core.warm()
    out = []
    for i, case in enumerate(cases, 1):
        if only and case["mid"] not in only:
            continue
        try:
            res = run_case(case)
        except Exception as exc:  # noqa: BLE001 - a probe bug is data, not a crash
            res = {"mid": case["mid"], "grade": "PARTIAL", "answer": "",
                   "evidence": [], "tools": [], "tool_calls": 0, "seconds": 0.0,
                   "blocker": f"probe error: {type(exc).__name__}: {exc}"[:300],
                   "gap": "U-OTHER", "hops_ok": [], "hops_failed": [], "pit": [],
                   "gt": None, "slow": [], "family": case.get("family"),
                   "entity_level": case.get("entity_level"),
                   "source_bank": case.get("source_bank"),
                   "regression": bool(case.get("regression")),
                   "question": case.get("question"), "as_of": case.get("as_of"),
                   "period": case.get("period"), "answer_kind": case.get("answer_kind"),
                   "template": case.get("template"), "calls": []}
        res["gap"] = res.get("gap") or mid_gap.get(case["mid"])
        res["gap_from_rollup"] = mid_gap.get(case["mid"])
        res["gap_info"] = gaps.get(res["gap"]) if res.get("gap") else None
        out.append(res)
        print(f"{i:3d} {case['mid']} {res['grade']:14s} {res['tool_calls']}c "
              f"{res['seconds']:5.2f}s  {(case.get('question') or '')[:70]}", flush=True)
    if not only:
        (HERE / "RESULTS.jsonl").write_text(
            "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in out), encoding="utf-8")
    else:
        (HERE / "RESULTS_smoke.jsonl").write_text(
            "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in out), encoding="utf-8")
    print(f"\n{len(out)} rows in {time.perf_counter() - t0:.1f}s  "
          f"{dict(Counter(x['grade'] for x in out))}")
    print("total tool calls", sum(x["tool_calls"] for x in out),
          "max/case", max((x["tool_calls"] for x in out), default=0))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
