#!/usr/bin/env python
"""Merge every question bank into ONE deduplicated master bank, then roll up the gaps.

Sources (step 2 of the golden rule):
  - Shivam's 30 fixed regressions (texts from QUERY_TEMPLATES §5, QA10_BRIEF, EVAL25);
  - tasks/QUESTION_BANK_300_2026-10-27.jsonl   (10 variations x 30 originals);
  - tasks/QUESTION_BANK_OPEN_2026-10-27.jsonl  (300 open questions, A01-A20);
  - tasks/QUESTION_BANK_RIPPLE_2026-10-28.jsonl (200 ripple questions, R01-R10);
  - tasks/reddit_mining/QUESTION_BANK_REDDIT_2026-10-28.jsonl (243 mined rows:
    the original 200 plus 43 pattern-gap rows, added 2026-10-28).

Read-only over REALITY_DATA_ROOT; writes only under tasks/master_bank/ and .tmp/.
No network, no commits.

    python tasks/master_bank/build_master_bank.py          # build the three outputs
    python tasks/master_bank/build_master_bank.py --check  # build + acceptance checks
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sys
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TASKS = ROOT / "tasks"
OUT = Path(__file__).resolve().parent

DATA_DEFAULT = Path(r"C:\Users\warri\Downloads\Info_Diffusion_Model\reality_engine\data")
os.environ.setdefault("REALITY_DATA_ROOT", str(DATA_DEFAULT))
sys.path.insert(0, str(ROOT))

BANK_FILES = {
    "variations300": TASKS / "QUESTION_BANK_300_2026-10-27.jsonl",
    "open300": TASKS / "QUESTION_BANK_OPEN_2026-10-27.jsonl",
    "ripple200": TASKS / "QUESTION_BANK_RIPPLE_2026-10-28.jsonl",
}
REDDIT_DEFAULT = TASKS / "reddit_mining" / "QUESTION_BANK_REDDIT_2026-10-28.jsonl"
S5_DOC = TASKS / "QUERY_TEMPLATES_2026-10-27.md"
QA10_DOC = TASKS / "optimizations" / "measure" / "QA10_BRIEF.md"
AUDIT_DOC = TASKS / "BACKWARD_REQUIREMENTS_AUDIT_2026-10-27_REPORT.md"
RIPPLE_LIB = TASKS / "ripple_bank" / "_lib.py"
OPEN_BUILDER = TASKS / "build_question_bank_open_300.py"
BANK300_BUILDER = TASKS / "build_question_bank_300.py"

LEVELS = ["stock", "industry", "sector", "theme", "index", "market-cap bucket",
          "price band", "policy", "macro", "market-wide"]
STYLES = ("terse", "natural", "Hinglish", "point-in-time")
FAMILIES = list(range(1, 21))
FAMILY_NAMES = {
    1: "Lookup", 2: "Number", 3: "Change over time", 4: "Screen", 5: "Cross-document",
    6: "Policy -> companies", 7: "Company -> policy", 8: "Peers", 9: "Event window",
    10: "Opinion vs truth", 11: "Point in time", 12: "When / timeline",
    13: "Inverse screen", 14: "Governance and audit", 15: "Market move -> why",
    16: "Input-cost / commodity transmission", 17: "Business economics",
    18: "Forward policy impact", 19: "Second-order / supply chain",
    20: "Out-of-scope and bizarre",
}
SOURCE_PRIO = {"shivam30": 0, "variations300": 1, "open300": 2, "ripple200": 3, "reddit200": 4}
ORIG_IDS = ([f"DBQ{i}" for i in range(1, 6)] + [f"QA{i}" for i in range(1, 11)]
            + [f"Q{i}" for i in range(11, 26)])

# Ripple archetypes carry no family in their bank. The mapping below is the
# declared rule (reviewer, 2026-10-28), recorded on every row as
# family_source="archetype". R04 spans the input-cost and supply-chain families.
RIPPLE_FAMILY = {"R01": [16], "R02": [18], "R03": [16], "R04": [16, 19],
                 "R05": [19], "R06": [3], "R07": [12], "R08": [16],
                 "R09": [11], "R10": [9]}
# The Reddit bank declares a template family ("3", "14") for most rows, but 85
# rows carry a NEW:* family because no template family fits (their own report:
# "NEW:* means no template family fits; the name is the gap we would have to
# add"). Map each NEW:* archetype to the closest template family, the same way
# RIPPLE_FAMILY maps R01-R10; every mapped row records
# family_source="pattern". entry_timing and hold_sell are retail *opinion*
# questions ("is this a good level", "should I hold or sell") -> family 10,
# opinion vs truth. The technical quarter is split between price history
# (family 3, change over time) and a dated event window (family 9): a breakout,
# gap, OI build-up or delivery spike is asked around one session, support /
# moving average / RSI / 52-week / relative strength / PCR are asked across
# sessions.
REDDIT_FAMILY = {
    "ta_support_resistance": [3], "ta_breakout_volume": [9], "ta_ma_cross": [3],
    "ta_rsi_setup": [3], "ta_52week": [3], "ta_gap": [9],
    "ta_relative_strength": [3], "ta_oi_buildup": [9], "ta_pcr_maxpain": [3],
    "ta_delivery_spike": [9],
    "entry_timing": [10], "hold_sell": [10],
    "group_basket": [8], "ipo_grey_listing": [9],
    "corporate_action_aftermath": [12], "sebi_rule": [6], "circuit_band": [12],
}
# A NEW:* family whose archetype is not in the table has no template family at
# all by definition -> family 20 (out-of-scope and bizarre), never empty.
REDDIT_FAMILY_DEFAULT = 20
# A declared V3/V4/V5/V9 row is a deliberate naming (old symbol / ISIN) or
# style (terse / long-Hinglish / as-of) variant: the brief keeps those as
# separate cases, because they are the robustness tests, not duplicates.
VARIANT_DIMS = {"V3", "V4", "V5", "V9"}
# The previous (scalar, first-family-only) mapping and stock default, kept only
# for the before/after table in the build output.
OLD_RIPPLE_FAMILY = {"R01": 16, "R02": 18, "R03": 16, "R04": 18, "R05": 17,
                     "R06": 17, "R07": 12, "R08": 20, "R09": 11, "R10": 9}

# Explicit identity clusters: ids that are the same underlying gap, not merely
# related. Anything not listed is its own cluster. Sources are the audit (G*),
# the open bank (NG*), and tasks/ripple_bank/_lib.py (proposal keys).
GAP_GROUPS = [
    ("G1", ["G1", "mcap_state"]),
    ("G5", ["G5", "NG20"]),
    ("G6", ["G6", "NG29"]),
    ("G10", ["G10", "policy_target"]),
    ("G12", ["G12", "NG11", "commodity_series", "freight_series", "rainfall", "rural_wage"]),
    ("NG10", ["NG10", "cost_structure", "import_content", "fx_exposure", "cost_geo"]),
    ("NG12", ["NG12", "capacity_util", "capex_project"]),
    ("NG14", ["NG14", "capacity_pipeline"]),
    ("NG15", ["NG15", "order_intake"]),
    ("NG25", ["NG25", "order_contract"]),
    ("NG22", ["NG22", "supply_link"]),
    ("NG08", ["NG08", "rating_action"]),
    ("NG07", ["NG07", "pledge_event"]),
    ("NG09", ["NG09", "fund_raise", "fund_use"]),
    ("NG18", ["NG18", "sector_flow"]),
    ("NG21", ["NG21", "event_calendar"]),
    ("NG24", ["NG24", "guidance_actual"]),
    ("NG26", ["NG26", "subsidy_register"]),
    ("NG27", ["NG27", "day0_session"]),
    ("NG28", ["NG28", "leakage_window"]),
]

# Ripple rows occasionally use the doc's proposal name instead of the _lib key.
GAP_ALIASES = {"fund_utilisation": "fund_use"}

# Open-bank gap ids that are a data-coverage fact rather than a schema gap.
U_HELD = {
    "U-DOC": ("no", "no document exists for that entity/period in any held store",
              "NOT IN DATA"),
    "U-STORE": ("no", "the entity has no rows in the store the template needs",
                "new fetch (entity-level coverage)"),
    "U-REFURB": ("no", "no refurbished / second-hand electronics sales series is held",
                 "new fetch"),
    "U-OTHER": ("no", "unclassified coverage gap", "new fetch"),
}

# Open-bank (NG01-NG29) held-data judgement, grounded in the stores named by the
# audit §2 and by the probes printed in GAP_ROLLUP.md.
NG_HELD = {
    "NG01": ("partial", "bse_announcements.ann (1.9M rows) holds attachment names; "
                        "announcement PDFs are not text-extracted into document_chunks"),
    "NG02": ("partial", "results_xbrl.filings.opinion carries the NSE declaration only; "
                        "opinion type / EOM / KAM need a reader over held AR + results text"),
    "NG03": ("no", "no entity table for audit firms or parent/subsidiary layers; names sit "
                   "in ar_facts quotes and announcements", "new fetch / curation"),
    "NG04": ("partial", "board/KMP names sit in AR text and announcements; no person table",
             "build from held text"),
    "NG05": ("no", "equity_intelligence.shareholding is a 40-row stub; shp_index is the live "
                   "PIT store", "new fetch (NSE/BSE shareholding filings)"),
    "NG06": ("yes", "insider_trades_v2 holds the NSE/BSE/SAST trade tape (333k rows per "
                    "STATE 2026-10-24); the 'empty store' claim is stale", "build from held"),
    "NG07": ("partial", "shareholding carries pledged % per quarter; the event-level "
                        "quantity/percentage sits in announcement text", "build from held text"),
    "NG08": ("partial", "enforcement / tax / rating items sit in bse_announcements headlines; "
                        "no structured event table with amounts", "build from held text"),
    "NG09": ("partial", "QIP/IPO objects and utilisation are in announcements and AR notes, "
                        "not structured", "build from held text"),
    "NG10": ("partial", "ar_facts raw-material notes + geographic_exposure (3,568 rows, "
                        "undated) hold the inputs; no cost-share table", "build from held"),
    "NG11": ("partial", "mkt_commodity_daily holds 13 series to 2026-10-06 (no known_at); "
                        "freight, rainfall and rural wage are not held", "new fetch + extend held"),
    "NG12": ("partial", "capacity/utilisation statements sit in concall, deck and AR text",
             "build from held text"),
    "NG13": ("partial", "stores/orders/volumes/LTV statements sit in concall and deck text",
             "build from held text"),
    "NG14": ("partial", "licence/commissioning/JV events sit in announcements and call text",
             "build from held text"),
    "NG15": ("partial", "tender/award pipeline sits in announcements and order-book commentary",
             "build from held text"),
    "NG16": ("no", "no analyst consensus or target-price store; the source is paid",
             "new fetch (paid)"),
    "NG17": ("no", "no Vahan / EV-registration feed is held", "new fetch"),
    "NG18": ("partial", "mkt_fii_dii_cash is market-wide only; the deal tape exists, "
                        "the sector split does not", "build from held"),
    "NG19": ("no", "investor-level holdings are not published for Indian listed stocks",
             "NOT IN DATA"),
    "NG20": ("yes", "theme membership can be curated from master_companies + company_industry "
                    "(sector/basic industry held)", "build from held"),
    "NG21": ("partial", "macro_events holds 30 rows (23 with doc_id); policy_events holds "
                        "21,552 rows (20,970 quote_ok)", "build from held"),
    "NG22": ("no", "no map from unlisted/private layers to listed suppliers; DRHP and "
                   "announcement text would have to be curated", "new fetch / curation"),
    "NG23": ("partial", "dividend/buyback rows sit in corporate_actions and announcements; "
                        "ordinary vs special is not tagged", "build from held text"),
    "NG24": ("partial", "concall_facts.cc_items guidance and results_xbrl actuals are both "
                        "held; the link is missing", "build from held"),
    "NG25": ("partial", "contract/customer/order-to-revenue linkage sits in announcement and "
                        "call text", "build from held text"),
    "NG26": ("partial", "policy_events holds dates/amounts as text; incentive expiry is not "
                        "a tagged event", "build from held"),
    "NG27": ("no", "no intraday bars are held; intraday-filing windows cannot be measured",
             "new fetch"),
    "NG28": ("yes", "prices, delivery and filing timestamps are all held; only the "
                    "event-study harness is missing", "build from held"),
    "NG29": ("partial", "demand commentary sits in concall/deck text; the cause tag does not",
             "build from held (chunk tagger)"),
}

# Free-text gap strings (300 bank, Shivam's originals) -> registry id, or None
# when the string is a method note rather than a gap.
TEXT_GAP_RULES = [
    (r"stored ratios mix price dates|no quarterly net worth", "G1"),
    (r"XBRL share capital is rounded", "G1"),
    (r"transcripts marked processed", "G6"),
    (r'no cross-source "latest"', "G6"),
    (r"segment context", "G11"),
    (r"banking taxonomy|banking-taxonomy", "G11"),
    (r"results notes", "G9"),
    (r"gold stocks|theme map", "G5"),
    (r"no HFC universe|peer table", "G4"),
    (r"commodity series end dates|coal price series|coal.*series|"
     r"rolling-correlation|dated tariff series", "G12"),
    (r"provenance across sources|thin sources|PIB provenance|policy record|"
     r"data-centre tax holiday", "G10"),
    (r"dairy universe", "G4"),
    (r"ETF", "G0"),
    (r"concall transcript held but not chunked|concall transcript.*not chunked", "G6"),
    (r"filing/document inside the requested period", "U-DOC"),
    (r"required store missing", "U-STORE"),
    (r"refurbished|second-hand", "U-REFURB"),
    (r"other coverage gap", "U-OTHER"),
    (r"index membership exists only as one .*snapshot|no history, no other indices|"
     r"index membership history", "G2"),
    (r"must use adjusted prices", None),
]

STORE_PATTERNS = [
    (r"ar_facts|ar_docs|annual report", "ar"),
    (r"deck_figures|deck_sources|investor presentation|slide", "deck"),
    (r"concall|cc_items|transcript|\bcall\b", "concall"),
    (r"results_xbrl|results_facts|XBRL|results filing", "xbrl"),
    (r"px_nse|px_bse|px_daily|adjusted price|price series|\bprice\b", "price"),
    (r"daily_price_delivery|delivery", "delivery"),
    (r"annual_financials|quarterly_financials|company_forensic_health|\bfinancials\b", "financials"),
    (r"shp_index|shareholding|promoter|\bholding\b", "holdings"),
    (r"pib_releases|\bPIB\b|policy_events|budget|RBI", "policy"),
    (r"macro_events", "macro"),
    (r"document_chunks|chunk", "chunks"),
    (r"etf_|\bETF\b|NAV", "etf"),
    (r"index_membership|\bindex\b", "index"),
    (r"bse_announcements|announcement", "announcements"),
    (r"mkt_commodity_daily|commodity", "commodity"),
]

HINDI_MARKERS = set("""kya kitna kaunsa kaun kab kyu kyun batao bataiye bataye hai hain
mein ka ke ki ko ne nahi wala wale karein hoga hua saath aur ya sirf kaafi padta""".split())

# --------------------------------------------------------------------------- #
# deterministic entity-level derivation
#
# Order matters and is auditable through entity_level_source:
#   given     the source bank declares entity_level (variations V1-V6/V9/V10,
#             the 30 originals, the Reddit bank)
#   variation V7 -> industry/sector scope, V8 -> index/theme screen
#   keywords  the entity types + question scope (index, market-cap, sector,
#             market-wide, policy, industry, theme, stock)
#   entities  no scope keyword matched; the entity type decides
#   fallback  no signal at all; stock (counted in --check, must stay under 10%
#             of the open + ripple rows)
# --------------------------------------------------------------------------- #
LEVEL_SOURCES = ("given", "entities", "variation", "keywords", "fallback")

INDEX_RE = re.compile(
    r"\bnifty[^.]{0,80}\b(?:constituents?|members?)\b|"
    r"\bindex (?:inclusion|included|members?|constituents?|removal|provider)\b|"
    r"\bnext nifty 50\b|\betf universe\b|\bgold etfs?\b|\bindex provider\b", re.I)
MCAP_RE = re.compile(
    r"\b(?:large|mid|small|micro)[- ]?caps?\b|"
    r"\bmarket[- ]?cap(?:italisation)? bucket\b", re.I)
MARKET_RE = re.compile(
    r"\bmarket (?:fell|rose|move|sell-?off|wide)\b|"
    r"(?:^|[.]\s+|:\s+)(?:on\s+[^.]{0,40})?(?:the\s+)?nifty[^.]{0,40}"
    r"\b(?:fell|rose|fall|rise|move|do|did)\b|"
    r"\bnifty\b[^.]{0,80}\b(?:ka\s+move|move that day|do on the first|"
    r"did the nifty)\b|"
    r"\btop losers\b|\bwhich stocks\b|\bdelivery-spike ratio leaders\b|"
    r"\bhow many sessions\b|\bretail investors lose\b|\bwho absorbed\b|"
    r"\bfii or dii\b|\bfii and dii\b|"
    r"\bfiis?\b[^.]{0,60}\bdiis?\b|\bdiis?\b[^.]{0,60}\bfiis?\b|"
    r"\bfii net flow\b|\bfii/dii\b|\bdii/fii\b|\bmarket-wide\b", re.I)
SECTOR_RE = re.compile(
    r"\bwhich (?:listed )?sectors?\b|\bwhich sectors?\b|"
    r"\bkaunse (?:listed )?sectors?\b|\bkaun sa sector\b|"
    r"\ball listed PSU banks\b|\bPSU (?:banks|financials)\b|"
    r"\bwhich listed exporters\b|\bwhich exporters\b|"
    r"\bwhich listed (?:lenders|financials|insurers|banks)\b|"
    r"\bamong listed companies\b|"
    r"\bsectors? (?:gain|lose|win|are most exposed|re-rate)\b", re.I)
POLICY_RE = re.compile(
    r"\b(?:rbi|mpc)\b[^.]{0,80}\b(?:hiked|cut|cuts?|raised|raises?|held|holds?|"
    r"moved|extended|injected|changes?|announced|imposed|revised|opened)\b|"
    r"^(?:the\s+)?(?:union budget|budget|government|finance minister|sebi)\b|"
    r"\b(?:us|eu)\b[^.]{0,60}\b(?:announced|imposed|raises?|raised|legislated|"
    r"bans?|opens?|tariffs?|duty|brings?\s+in)\b|"
    r"\b(?:union budget|budget|tariffs?\s+(?:on|of|goes|go|is|was|raised|"
    r"imposed|cut)|customs duty|duty|pli|gst|sebi|subsidy|incentive scheme|"
    r"schemes?|mission|\bact\b|finance commission|fdi|anti-dumping|"
    r"safeguard duty|policy|reforms?|allocation|outlay|exemption|tcs|fta|"
    r"free trade|caqm|tdb|dst|pmay|public capex|incentives?|"
    r"rbi governor|mpc statement|carbon border adjustment)\b|"
    r"\brepo\b[^.]{0,50}\b(?:cut|hike|hiked|raised|held|moved|change|goes|up)\b|"
    r"\b(?:rate cuts?|rate hike|easing cycle)\b|"
    r"\bcentral bank\b[^.]{0,50}\b(?:changes|injects|injected|raises|cuts|"
    r"holds?)\b|"
    r"\bcrr\b|\bliquidity\b[^.]{0,40}\binjected\b|"
    r"\b(?:framework|limits?|restrictions?|guidelines?|period)\b[^.]{0,50}"
    r"\b(?:liberalised|removed|extended|restored|revised|eased|raised|"
    r"offered)\b|"
    r"\b(?:is|are)\s+offered\b", re.I)
THEME_RE = re.compile(
    r"\btheme\b|\bgold[- ]jewell?ery\b|\bdata[- ]cent(?:re|er)\b|"
    r"\b(?:ev|electric vehicles?)\b|\bchina\s*\+\s*1\b|"
    r"\bdefence indigenisation\b|\bsemiconductor mission\b|"
    r"\bgreen hydrogen\b|\benergy transition\b|\bquick[- ]commerce\b", re.I)
INDUSTRY_RE = re.compile(
    r"\b(?:cables?|tubes?|pipes?|tyres?|tires?|wagons?|epcs?|"
    r"auto[- ]ancillar(?:y|ies)|specialty[- ]chemicals?|paints?|airlines?|"
    r"airports?|hfcs?|nbfcs?|banks?|lenders?|exporters?|importers?|oems?|"
    r"two[- ]wheelers?|tractors?|hospitals?|jewell?ers?|jewell?ery|solar|"
    r"modules?|semiconductors?|steels?|cements?|papers?|glass|chemicals?|"
    r"textiles?|garments?|spinners?|fabricators?|distributors?|suppliers?|"
    r"manufacturers?|assemblers?|developers?|generators?|discoms?|refiners?|"
    r"marketers?|smelters?|miners?|mills?|contractors?|shipping lines?|"
    r"insurers?|asset managers?|brokers?|qsrs?|restaurants?|dair(?:y|ies)|"
    r"fertilisers?|urea|pharmas?|power|railways?|rail|defence|electronics|"
    r"oil marketing|consumer durables|fmcg|packaged[- ]food|quick[- ]commerce|"
    r"food[- ]delivery|gold[- ]loan|life insurers?|mutual funds?|realty|"
    r"real estate|optical fibre|telecom|coal|aluminium|aluminum|shipping|"
    r"hotels?|retailers?|ports?|it services|software|technology)\b", re.I)
SCREEN_RE = re.compile(
    r"\bwhich (?:companies|managements?|company|promoters?|stocks)\b|"
    r"\bwhich (?:second-layer )?listed (?:companies|suppliers|names|company)\b|"
    r"\bwhich\b[^.]{0,40}\b(?:results notes|segments?|filings|statements)\b|"
    r"\blisted companies\b|\bfilings\b|"
    r"\blist the\b|\bcluster of\b|\bany company\b|\bany auditor\b|"
    r"\bkisi company\b|\bkaunsi companies\b|\bkaun si companies\b|"
    r"\bkonsi companies\b|\bkaunsi company\b|\bkaun si company\b|"
    r"\bacross the twelve\b|\bpromoter selling before results\b|"
    r"\bhow many\b(?!\s+(?:quarters?|years?|days?|steps?))", re.I)
PRICE_BAND_RE = re.compile(r"\bprice band\b|\b\d+% or lower band\b", re.I)
GENERIC_STOCK_RE = re.compile(
    r"\b(?:a|an|the|one)\s+(?:company|stock|mid-cap|small-cap|promoter|"
    r"conglomerate|rating|qip|buyback|capacity|demerger|listed company)\b|"
    r"\blisted company\b|\bthe company'?s\b", re.I)
STOP_TOKENS = {"the", "india", "indian", "state", "bank", "life", "power",
               "steel", "cement", "oil", "gas", "sun", "tata", "bajaj",
               "adani", "jsw", "reliance", "bharat", "national", "general",
               "larsen", "jindal"}

# 30 rows hand-read against their question text (2026-10-28). The expected
# level is the scope the question asks about, not the source bank's default.
# Two rows are deliberately included where the rule lands on stock but the
# question is about an industry group (A09-07, A13-08); they are the misses.
HAND_CHECK = [
    ("shivam30", "Q17", "industry"),
    ("shivam30", "Q21", "policy"),
    ("variations300", "DBQ1-V1", "stock"),
    ("variations300", "DBQ1-V7", "industry"),
    ("variations300", "QA6-V8", "index"),
    ("variations300", "Q16-V8", "theme"),
    ("variations300", "Q19-V7", "index"),
    ("variations300", "QA4-V7", "industry"),
    ("open300", "A01-06", "stock"),
    ("open300", "A07-01", "market-wide"),
    ("open300", "A09-02", "industry"),
    ("open300", "A09-07", "industry"),
    ("open300", "A10-07", "stock"),
    ("open300", "A11-02", "theme"),
    ("open300", "A12-01", "policy"),
    ("open300", "A13-02", "industry"),
    ("open300", "A13-08", "industry"),
    ("open300", "A17-08", "market-cap bucket"),
    ("open300", "A19-01", "sector"),
    ("open300", "A20-04", "index"),
    ("ripple200", "R01-01", "industry"),
    ("ripple200", "R02-01", "policy"),
    ("ripple200", "R03-01", "policy"),
    ("ripple200", "R04-02", "policy"),
    ("ripple200", "R05-04", "industry"),
    ("ripple200", "R06-01", "market-wide"),
    ("ripple200", "R07-01", "industry"),
    ("ripple200", "R08-01", "industry"),
    ("ripple200", "R09-01", "macro"),
    ("ripple200", "R10-01", "stock"),
]



# --------------------------------------------------------------------------- #
# small helpers
# --------------------------------------------------------------------------- #
def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def norm_words(text: str) -> list[str]:
    text = (text or "").lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\d+", " # ", text)
    return text.split()


def jaccard(a: list[str], b: list[str]) -> float:
    sa, sb = set(a), set(b)
    if len(sa) < 4 or len(sb) < 4:
        return 1.0 if sa == sb else 0.0
    return len(sa & sb) / len(sa | sb)


def natkey(value: str):
    return [int(p) if p.isdigit() else p for p in re.split(r"(\d+)", value or "")]


def families_of(value) -> list[int]:
    if value is None:
        return []
    if isinstance(value, int):
        return [value] if 1 <= value <= 20 else []
    if isinstance(value, (list, tuple)):
        out = []
        for v in value:
            for f in families_of(v):
                if f not in out:
                    out.append(f)
        return out
    out = []
    for m in re.findall(r"\d+", str(value)):
        f = int(m)
        if 1 <= f <= 20 and f not in out:
            out.append(f)
    return out


def primary_family(rec: dict):
    fams = rec.get("family") or []
    return fams[0] if fams else None


def _name_variants(entity: dict) -> set[str]:
    out = set()
    sym = str(entity.get("symbol") or "").strip()
    if len(sym) >= 3:
        out.add(sym.lower())
    name = str(entity.get("name") or "").strip()
    if not name:
        return out
    out.add(name.lower())
    base = re.sub(r"\b(?:Limited|Ltd|Inc|Corporation|Corp|Company|Industries|"
                  r"India)\b\.?", "", name, flags=re.I)
    base = re.sub(r"\s+", " ", base).strip(" ,.")
    if len(base) >= 4:
        out.add(base.lower())
    words = base.split()
    if len(words) >= 2:
        out.add(" ".join(words[:2]).lower())
    if words and len(words[0]) >= 5 and words[0].lower() not in STOP_TOKENS:
        out.add(words[0].lower())
    return out


def _stock_entities(rec: dict) -> list[dict]:
    return [e for e in (rec.get("entities") or [])
            if isinstance(e, dict)
            and str(e.get("type") or "stock").lower() not in
            ("commodity", "index", "policy", "industry")]


def named_variants(rec: dict) -> list[str]:
    q = (rec.get("question") or "").lower()
    found = []
    for entity in _stock_entities(rec):
        for variant in _name_variants(entity):
            if variant and variant in q:
                found.append(variant)
    return found


def strong_named(rec: dict) -> str | None:
    """A named company is the grammatical subject/possessor of the question."""
    q = (rec.get("question") or "").lower()
    for entity in _stock_entities(rec):
        for variant in _name_variants(entity):
            if not variant or variant not in q:
                continue
            patterns = [
                r"(?:^|\.\s+|:\s+)" + re.escape(variant),
                re.escape(variant) + r"'s\b",
                re.escape(variant) + r"\s+(?:ka|ke|ki|ne)\b",
                r"\bfor\s+" + re.escape(variant) + r"\b",
                r"\bat\s+" + re.escape(variant) + r"\b",
                re.escape(variant) + r"\s+(?:filed|fell|rose|said|says|"
                r"reports?|reported|guides?|guided|discloses?|disclosed|"
                r"announced|has|had|is|was|will|would|delivered|deliver|"
                r"bought|buy|sold|sell|cut|cuts|raises?|lends?|earns?|pays?|"
                r"holds?|owns?|funds?|faces?|sees?|disclose|guide|report|"
                r"say|put|ne)\b",
            ]
            if any(re.search(p, q) for p in patterns):
                return variant
    return None


def derive_entity_level(rec: dict) -> tuple[str, str]:
    """(entity_level, entity_level_source) - deterministic, first match wins."""
    bank = rec.get("source_bank")
    q = rec.get("question") or ""
    entities = [e for e in (rec.get("entities") or []) if isinstance(e, dict)]
    types = {str(e.get("type") or "").lower() for e in entities if e.get("type")}

    if bank == "variations300":
        variation = rec.get("variation")
        scope = str(rec.get("_scope") or rec.get("scope") or "").lower()
        if variation == "V7":
            if "etf" in scope:
                return "index", "variation"
            if "theme" in scope:
                return "theme", "variation"
            return "industry", "variation"
        if variation == "V8":
            if "theme" in scope:
                return "theme", "variation"
            if "constituent" in scope or "nifty" in scope:
                return "index", "variation"
            if MCAP_RE.search(scope):
                return "market-cap bucket", "variation"
            return "index", "variation"
        return rec.get("entity_level") or "stock", "given"
    if bank == "shivam30":
        return rec.get("entity_level") or "stock", "given"

    if bank == "ripple200":
        archetype = rec.get("archetype")
        # These three archetypes fix the scope by construction: R02 is a policy
        # cascade, R06 is a capital-markets loop, R09 asks which leading series
        # turns first (so the subject is the macro series, not a company).
        if archetype == "R02":
            return "policy", "keywords"
        if archetype == "R06":
            return "market-wide", "keywords"
        if archetype == "R09":
            return "macro", "keywords"
        if archetype == "R10":
            return "stock", "entities"

    if INDEX_RE.search(q):
        return "index", "keywords"
    if MCAP_RE.search(q):
        return "market-cap bucket", "keywords"
    if MARKET_RE.search(q):
        return "market-wide", "keywords"
    if strong_named(rec):
        return "stock", "keywords"

    policy_match = POLICY_RE.search(q)
    screen_match = SCREEN_RE.search(q)
    if policy_match and policy_match.start() <= 40 and (
            not screen_match or policy_match.start() <= screen_match.start()):
        return "policy", "keywords"
    if SECTOR_RE.search(q):
        return "sector", "keywords"
    if INDUSTRY_RE.search(q):
        return "industry", "keywords"
    if THEME_RE.search(q):
        return "theme", "keywords"
    if PRICE_BAND_RE.search(q):
        return "price band", "keywords"
    if screen_match:
        return "market-wide", "keywords"
    if policy_match:
        return "policy", "keywords"
    if named_variants(rec):
        return "stock", "keywords"
    if GENERIC_STOCK_RE.search(q):
        return "stock", "keywords"
    if "policy" in types:
        return "policy", "entities"
    if "index" in types:
        return "index", "entities"
    if "industry" in types:
        return "industry", "entities"
    if "commodity" in types:
        return "macro", "entities"
    if "stock" in types:
        return "stock", "entities"
    return "stock", "fallback"



def is_hinglish(text: str, flag=False) -> bool:
    if flag:
        return True
    low = text.lower()
    if "(hinglish)" in low:
        return True
    hits = {w for w in re.findall(r"[a-z]+", low) if w in HINDI_MARKERS}
    return len(hits) >= 2


def classify_style(question: str, hinglish=False, variation=None) -> str:
    if is_hinglish(question, hinglish):
        return "Hinglish"
    low = question.lower()
    if variation == "V9" or re.search(r"\bas of\b|point[- ]in[- ]time|known by|"
                                       r"only evidence known", low):
        return "point-in-time"
    if variation == "V4" or len(question.split()) <= 10:
        return "terse"
    return "natural"


def naming_flag(question: str, variation=None, identity_changed=False) -> bool:
    if variation == "V3" or identity_changed:
        return True
    return bool(re.search(r"\bINE[A-Z0-9]{9}\b|\b\d{6}\b|old symbol|formerly|renamed|"
                          r"previously traded as", question or "", re.I))


def edge_flag(question: str) -> bool:
    return bool(re.search(r"NOT IN DATA|answer NOT IN DATA|if no\b|"
                          r"if the .{0,40}(is not|is not held|lacks)|empty case",
                          question or "", re.I))


def norm_entities(raw) -> list[dict]:
    out = []
    for e in raw or []:
        if isinstance(e, dict):
            out.append(dict(e))
        elif isinstance(e, str):
            out.append({"symbol": e})
    return out


def norm_rubric(raw) -> dict | None:
    if not isinstance(raw, dict):
        return None
    return {
        "required_evidence": raw.get("required_evidence") or raw.get("evidence"),
        "required_steps": raw.get("required_steps") or raw.get("steps"),
        "forbidden": raw.get("forbidden"),
        "ground_truth": raw.get("ground_truth"),
    }


def norm_coverage(verdict, note, gap) -> dict:
    if isinstance(verdict, dict):
        raw = verdict
        return {"verdict": raw.get("verdict") or raw.get("status") or raw.get("coverage"),
                "note": raw.get("note") or note or None,
                "gap": raw.get("gap") or raw.get("gap_id") or gap}
    return {"verdict": verdict, "note": note or None, "gap": gap}


def store_tag(name: str) -> str:
    low = (name or "").lower()
    for pat, tag in STORE_PATTERNS:
        if re.search(pat, low):
            return tag
    return low.split(".")[0]


def evidence_shape(rec: dict) -> str:
    if rec.get("chain"):
        keys = sorted({h.get("gap_key") for h in rec["chain"] if h.get("gap_key")})
        return "chain:" + "|".join(keys)
    tags = {store_tag(n) for n in (rec.get("_needs") or [])}
    ev = (rec.get("rubric") or {}).get("required_evidence")
    if ev:
        text = " ".join(ev) if isinstance(ev, list) else str(ev)
        for pat, tag in STORE_PATTERNS:
            if re.search(pat, text, re.I):
                tags.add(tag)
    return "|".join(sorted(tags))


def subject_key(rec: dict) -> str:
    level = rec.get("entity_level") or "stock"
    entities = rec.get("entities") or []
    if level == "stock":
        keys = sorted({str(e.get("isin") or e.get("symbol") or "").upper()
                       for e in entities if isinstance(e, dict)
                       and (e.get("isin") or e.get("symbol"))})
        if keys:
            return "S:" + "|".join(keys)
    scope = re.sub(r"^(all listed companies in|the)\s+", "",
                   str(rec.get("_scope") or "").strip().lower())
    scope = re.sub(r"\s+constituents$", "", scope)
    title = str(rec.get("_policy_title") or "").strip().lower()
    name = ""
    if entities and isinstance(entities[0], dict):
        name = str(entities[0].get("name") or "").strip().lower()
    basis = scope or title or name or str(rec.get("_subject") or "").lower()
    return level[:1].upper() + ":" + basis


def period_key(rec: dict) -> str:
    return f"{str(rec.get('period') or '').strip().lower()}|" \
           f"{str(rec.get('as_of') or '').strip().lower()}"


def text_gap_ids(gap_text) -> list[str]:
    if not gap_text:
        return []
    if isinstance(gap_text, (list, tuple)):
        out = []
        for g in gap_text:
            out += text_gap_ids(g)
        return out
    text = str(gap_text)
    m = re.match(r"\s*(G\d+|NG\d{2})\b", text)
    if m:
        return [m.group(1)]
    for pat, target in TEXT_GAP_RULES:
        if re.search(pat, text, re.I):
            if target is None:
                return []
            return [target]
    return []


# --------------------------------------------------------------------------- #
# source loaders -> common record schema
# --------------------------------------------------------------------------- #
def _s5_table() -> dict:
    rows = {}
    for line in S5_DOC.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\|\s*(DBQ\d+|QA\d+|Q\d+)\s*\|", line)
        if not m:
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 5:
            rows[m.group(1)] = {"short": cells[1], "family": cells[2],
                                "template": cells[3], "gap": cells[4]}
    return rows


def _qa10_questions() -> dict:
    text = QA10_DOC.read_text(encoding="utf-8")
    section = text.split("## Questions", 1)[1].split("## Steps", 1)[0]
    out = {}
    for line in section.splitlines():
        m = re.match(r"^\s*(\d+)\.\s+(.+?)\s*$", line)
        if m:
            out[f"QA{m.group(1)}"] = re.sub(r"\*\*", "", m.group(2))
    return out


def load_originals() -> list[dict]:
    s5 = _s5_table()
    qa = _qa10_questions()
    sys.path.insert(0, str(TASKS))
    import build_question_bank_300 as b300  # constants only; main() is guarded
    specs = {s["oid"]: s for s in b300.SPECS}
    recs = []
    for oid in ORIG_IDS:
        row = s5.get(oid) or {}
        spec = specs.get(oid) or {}
        question = qa.get(oid) or row.get("short") or ""
        level = spec.get("level") or spec.get("kind") or "stock"
        entities = [{"symbol": spec["base"]}] if spec.get("base") else []
        subject = spec.get("theme_label") or spec.get("theme") or spec.get("base") or ""
        gap = row.get("gap")
        gap = None if not gap or gap.strip() in ("\u2014", "-", "") else gap
        families = families_of(row.get("family"))
        rec = {
            "source_bank": "shivam30", "source_qid": oid, "question": question,
            "entities": entities, "entity_level": level,
            "entity_level_source": "given",
            "family": families, "family_source": "bank", "variation": None,
            "archetype": None, "template": oid, "period": spec.get("period"),
            "as_of": spec.get("as_of"), "answer_kind": b300.EXPECTED.get(oid),
            "rubric": norm_rubric({"required_evidence": spec.get("needs")}),
            "coverage": norm_coverage(None, None, gap), "chain": None,
            "style": classify_style(question),
            "naming": naming_flag(question), "edge": edge_flag(question),
            "regression": True,
            "_needs": spec.get("needs"), "_scope": "", "_policy_title": None,
            "_subject": subject, "_template_explicit": True,
            "_gaps": text_gap_ids(gap),
            "text_source": "full text (QA10_BRIEF)" if oid in qa
                           else "documented short form (QUERY_TEMPLATES §5)",
        }
        recs.append(rec)
    return recs


def load_variations300() -> list[dict]:
    recs = []
    for r in read_jsonl(BANK_FILES["variations300"]):
        families = families_of(r.get("family"))
        question = r.get("question") or ""
        gap = r.get("gap")
        cov = norm_coverage(r.get("coverage"), r.get("coverage_note"), gap)
        rec = {
            "source_bank": "variations300", "source_qid": r["qid"], "question": question,
            "entities": norm_entities(r.get("entities")),
            "entity_level": r.get("entity_level") or "stock",
            "entity_level_source": "given",
            "family": families, "family_source": "bank",
            "variation": r.get("variation"),
            "archetype": None, "template": r.get("orig_qid"),
            "period": r.get("period"), "as_of": r.get("as_of"),
            "answer_kind": r.get("expected_answer_type"),
            "rubric": norm_rubric({"required_evidence": r.get("needs")}),
            "coverage": cov,
            "chain": None,
            "style": classify_style(question, bool(r.get("hinglish")), r.get("variation")),
            "naming": naming_flag(question, r.get("variation"), bool(r.get("identity_changed"))),
            "edge": edge_flag(question),
            "regression": False,
            "_needs": r.get("needs"), "_scope": r.get("scope"),
            "_policy_title": (r.get("policy") or {}).get("title")
                             if isinstance(r.get("policy"), dict) else None,
            "_subject": "", "_template_explicit": True,
            "_gaps": sorted(set(text_gap_ids(gap) + text_gap_ids(cov.get("note")))),
            "text_source": "bank",
        }
        recs.append(rec)
    return recs


def load_open300() -> list[dict]:
    recs = []
    for r in read_jsonl(BANK_FILES["open300"]):
        families = families_of(r.get("family"))
        entities = norm_entities(r.get("entities"))
        question = r.get("question") or ""
        cov = r.get("coverage") or {}
        gap = cov.get("gap_id")
        archetype = str(r.get("archetype") or "").split(" ", 1)[0] or None
        rec = {
            "source_bank": "open300", "source_qid": r["qid"], "question": question,
            "entities": entities, "entity_level": None,
            "entity_level_source": None,
            "family": families, "family_source": "bank", "variation": None,
            "archetype": archetype, "template": archetype,
            "period": r.get("period"), "as_of": r.get("as_of"),
            "answer_kind": r.get("answer_kind"),
            "rubric": norm_rubric(r.get("rubric")),
            "coverage": norm_coverage(cov.get("verdict"), cov.get("note") or None, gap),
            "chain": None,
            "style": classify_style(question),
            "naming": naming_flag(question), "edge": edge_flag(question),
            "regression": False,
            "_needs": None, "_scope": "", "_policy_title": None,
            "_subject": "", "_template_explicit": False,
            "_gaps": sorted(set(text_gap_ids(gap) + text_gap_ids(cov.get("note")))),
            "text_source": "bank",
        }
        recs.append(rec)
    return recs


def load_ripple200() -> list[dict]:
    recs = []
    for r in read_jsonl(BANK_FILES["ripple200"]):
        question = r.get("question") or ""
        chain = r.get("chain") or []
        trigger = r.get("trigger") or {}
        trig = trigger.get("ref") if isinstance(trigger, dict) else None
        archetype = r.get("archetype")
        fams = list(RIPPLE_FAMILY.get(str(archetype), []))
        cov = r.get("coverage") or {}
        gaps = sorted({GAP_ALIASES.get(h.get("gap_key"), h.get("gap_key"))
                       for h in chain if h.get("gap_key")})
        rec = {
            "source_bank": "ripple200", "source_qid": r["qid"], "question": question,
            "entities": norm_entities(r.get("entities")),
            "entity_level": None, "entity_level_source": None,
            "family": fams, "family_source": "archetype", "variation": None,
            "archetype": archetype,
            "template": f"{archetype}:{trig}" if trig else archetype,
            "period": r.get("period"), "as_of": r.get("as_of"),
            "answer_kind": None,
            "rubric": norm_rubric(r.get("rubric")),
            "coverage": norm_coverage(cov.get("verdict"), cov.get("note") or None, gaps),
            "chain": chain,
            "style": classify_style(question),
            "naming": naming_flag(question), "edge": edge_flag(question),
            "regression": False,
            "_needs": None, "_scope": "", "_policy_title": None, "_subject": "",
            "_template_explicit": False,
            "_gaps": gaps, "text_source": "bank",
        }
        recs.append(rec)
    return recs


def load_reddit(path: Path) -> list[dict]:
    """Load the mined Reddit bank; `family` may be a number or a NEW:* name."""
    recs = []
    for idx, r in enumerate(read_jsonl(path), 1):
        question = (r.get("question") or r.get("prompt") or r.get("text")
                    or r.get("query") or "")
        qid = str(r.get("qid") or r.get("id") or r.get("source_qid") or f"RDD{idx:03d}")
        declared = r.get("family")
        families = families_of(declared)
        entities = norm_entities(r.get("entities"))
        level = r.get("entity_level") or r.get("level")
        archetype = r.get("archetype") or r.get("topic") or r.get("category")
        archetype = str(archetype).split(" ", 1)[0] if archetype else None
        family_source = "bank"
        if not families:
            families = list(REDDIT_FAMILY.get(str(archetype), [REDDIT_FAMILY_DEFAULT]))
            family_source = "pattern"
        rubric = norm_rubric(r.get("rubric"))
        if rubric is None and isinstance(r.get("rubric"), str):
            rubric = norm_rubric({"required_evidence": r["rubric"]})
        coverage = r.get("coverage")
        if isinstance(coverage, dict):
            cov = norm_coverage(coverage.get("verdict"), coverage.get("note"),
                                coverage.get("gap") or coverage.get("gap_id"))
        else:
            cov = norm_coverage(coverage if isinstance(coverage, str) else None,
                                r.get("coverage_note"), r.get("gap"))
        style = r.get("style")
        if style not in STYLES:
            style = classify_style(question, bool(r.get("hinglish")))
        rec = {
            "source_bank": "reddit200", "source_qid": qid, "question": question,
            "entities": entities,
            "entity_level": level or None,
            "entity_level_source": "given" if level else None,
            "family": families, "family_source": family_source, "variation": None,
            "archetype": archetype, "template": archetype or "reddit",
            "period": r.get("period"), "as_of": r.get("as_of"),
            "answer_kind": r.get("answer_kind") or r.get("kind"),
            "rubric": rubric, "coverage": cov,
            "chain": r.get("chain"),
            "style": style,
            "naming": naming_flag(question), "edge": edge_flag(question),
            "regression": False,
            "_needs": None, "_scope": r.get("scope") or "", "_policy_title": None,
            "_subject": "", "_template_explicit": False,
            "_family_declared": declared,
            "_gaps": sorted(set(text_gap_ids(cov.get("gap")) + [
                GAP_ALIASES.get(h.get("gap_key"), h.get("gap_key"))
                for h in (r.get("chain") or [])
                if isinstance(h, dict) and h.get("gap_key")])),
            "text_source": "bank",
        }
        recs.append(rec)
    return recs


# --------------------------------------------------------------------------- #
# dedupe
# --------------------------------------------------------------------------- #
class DSU:
    def __init__(self, n):
        self.p = list(range(n))

    def find(self, i):
        while self.p[i] != i:
            self.p[i] = self.p[self.p[i]]
            i = self.p[i]
        return i

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[rb] = ra


def case_key(rec: dict) -> tuple:
    return (rec.get("template") or "", rec.get("entity_level") or "",
            subject_key(rec), period_key(rec), rec.get("style") or "",
            bool(rec.get("naming")), bool(rec.get("edge")), evidence_shape(rec))


def cross_bank_case_key(rec: dict) -> tuple:
    """Case identity minus the subject label, which banks fill from different fields."""
    return (rec.get("template") or "", rec.get("entity_level"), period_key(rec),
            rec.get("style"), bool(rec.get("naming")), bool(rec.get("edge")),
            evidence_shape(rec))


def _subject_tokens(rec: dict) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", subject_key(rec).split(":", 1)[-1].lower()))


def subjects_compatible(a: dict, b: dict) -> bool:
    """The same subject written at different lengths; unknown labels never block."""
    ta, tb = _subject_tokens(a), _subject_tokens(b)
    return not ta or not tb or ta <= tb or tb <= ta


def cross_bank_same_case(a: dict, b: dict) -> bool:
    if cross_bank_case_key(a) != cross_bank_case_key(b):
        return False
    if a.get("entity_level") == "stock":
        return subject_key(a) == subject_key(b)
    return subjects_compatible(a, b)


def is_wording_variant(rec: dict) -> bool:
    return rec.get("variation") in VARIANT_DIMS


def rubric_score(rec: dict) -> tuple:
    rub = rec.get("rubric") or {}
    filled = sum(1 for k in ("required_evidence", "required_steps", "forbidden",
                             "ground_truth") if rub.get(k))
    return (bool(rec.get("regression")), bool(rub.get("ground_truth")), filled,
            len(rec.get("question") or ""), -SOURCE_PRIO.get(rec["source_bank"], 9))


def dedupe(records: list[dict]) -> list[dict]:
    n = len(records)
    dsu = DSU(n)
    toks = [norm_words(r["question"]) for r in records]

    # layer 1: near-duplicate text, restricted to the same case dimensions so a
    # templated question on another company is never merged.
    buckets = defaultdict(list)
    for i, r in enumerate(records):
        buckets[(r.get("entity_level"), subject_key(r), period_key(r), r.get("style"),
                 bool(r.get("naming")), bool(r.get("edge")), primary_family(r))
                ].append(i)
    for idxs in buckets.values():
        for a in range(len(idxs)):
            for b in range(a + 1, len(idxs)):
                if jaccard(toks[idxs[a]], toks[idxs[b]]) >= 0.80:
                    dsu.union(idxs[a], idxs[b])

    # layer 1b: the same near-duplicate layer across banks. Layer 1 includes the
    # subject in its bucket, so it can never merge the same case written with a
    # different subject label: the originals take the theme label, the
    # variations take the policy title, and the Reddit/open banks carry no
    # scope at all. Compare only pairs from different banks, with the same
    # template, level, period label, style, naming/edge dimension and evidence
    # shape; a stock-level pair must still share the entity key, and a
    # non-stock pair must name the same subject. A declared naming/style variant
    # stays separate (the brief's robustness exemption), and inside one bank
    # such a pair is a deliberate variation, not a duplicate.
    cross = defaultdict(list)
    for i, r in enumerate(records):
        cross[cross_bank_case_key(r)].append(i)
    for idxs in cross.values():
        for a in range(len(idxs)):
            for b in range(a + 1, len(idxs)):
                ra, rb = records[idxs[a]], records[idxs[b]]
                if ra["source_bank"] == rb["source_bank"]:
                    continue
                if is_wording_variant(ra) or is_wording_variant(rb):
                    continue
                if not cross_bank_same_case(ra, rb):
                    continue
                if jaccard(toks[idxs[a]], toks[idxs[b]]) >= 0.80:
                    dsu.union(idxs[a], idxs[b])

    # layer 2: same case (template + level + subject + period + style + naming +
    # edge + evidence shape). For banks with no explicit template id (open,
    # ripple, reddit) a wording check confirms it is the same case.
    groups = defaultdict(list)
    for i, r in enumerate(records):
        groups[case_key(r)].append(i)
    for idxs in groups.values():
        if len(idxs) < 2:
            continue
        for a in range(len(idxs)):
            for b in range(a + 1, len(idxs)):
                explicit = (records[idxs[a]].get("_template_explicit")
                            or records[idxs[b]].get("_template_explicit"))
                if explicit or jaccard(toks[idxs[a]], toks[idxs[b]]) >= 0.50:
                    dsu.union(idxs[a], idxs[b])

    members = defaultdict(list)
    for i in range(n):
        members[dsu.find(i)].append(i)

    cases = []
    for idxs in members.values():
        rep = max(idxs, key=lambda i: (rubric_score(records[i]), -i))
        dups = sorted(({"source_bank": records[i]["source_bank"],
                        "source_qid": records[i]["source_qid"]}
                       for i in idxs if i != rep),
                      key=lambda d: (SOURCE_PRIO.get(d["source_bank"], 9),
                                     natkey(d["source_qid"])))
        base = records[rep]
        gaps = sorted({g for i in idxs for g in (records[i].get("_gaps") or [])})
        banks = sorted({records[i]["source_bank"] for i in idxs},
                       key=lambda b: SOURCE_PRIO.get(b, 9))
        case = {}
        for k, v in base.items():
            if k.startswith("_"):
                continue
            case[{"naming": "naming_variant", "edge": "edge_case"}.get(k, k)] = v
        case["duplicates"] = dups
        case["source_banks"] = banks
        case["_gaps"] = gaps
        case["_members"] = len(idxs)
        cases.append(case)

    cases.sort(key=lambda c: (SOURCE_PRIO.get(c["source_bank"], 9),
                              natkey(c["source_qid"])))
    for i, c in enumerate(cases, 1):
        c["mid"] = f"MB{i:04d}"
    return cases


# --------------------------------------------------------------------------- #
# coverage matrix
# --------------------------------------------------------------------------- #
def coverage_matrix(cases: list[dict]) -> dict:
    """Each (case, family) pair is counted exactly once; 6c proves no case is empty."""
    cells = Counter()
    styles = Counter()
    style_cells = Counter()
    for c in cases:
        level = c.get("entity_level") or "unknown"
        style = c.get("style")
        for fam in (c.get("family") or []):
            cells[(fam, level)] += 1
            styles[(fam, style)] += 1
            style_cells[(fam, level, style)] += 1
    return {"cells": cells, "styles": styles, "style_cells": style_cells}


# --------------------------------------------------------------------------- #
# gap registry
# --------------------------------------------------------------------------- #
def _effort_days(cell: str):
    """Only numbers that are followed by 'day(s)' count; '41.6k filings' is not effort."""
    pairs = re.findall(r"(\d+(?:\.\d+)?)(?:\s*[-\u2013]\s*(\d+(?:\.\d+)?))?\s*days?",
                       cell or "", re.I)
    vals = [float(x) for pair in pairs for x in pair if x]
    return max(vals) if vals else None


def parse_audit_gaps() -> dict:
    gaps = {}
    for line in AUDIT_DOC.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\|\s*\*\*(G\d+)\*\*\s*\|", line)
        if not m:
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        gaps[m.group(1)] = {
            "id": m.group(1), "desc": cells[1], "close_by": cells[2],
            "effort": _effort_days(cells[3]), "source": cells[4],
            "fetch": cells[5], "unblocks": cells[6],
        }
    return gaps


def parse_ng_gaps(open_rows: list[dict]) -> dict:
    descs = {}
    for r in open_rows:
        gid = (r.get("coverage") or {}).get("gap_id") or ""
        m = re.match(r"(NG\d{2})\s+(.+)", gid)
        if m:
            descs.setdefault(m.group(1), m.group(2).strip())
    src = OPEN_BUILDER.read_text(encoding="utf-8")
    for m in re.finditer(r'"(NG\d{2})\s+([^"]+)"', src):
        descs.setdefault(m.group(1), m.group(2).strip())
    return descs


def parse_ripple_proposals() -> dict:
    tree = ast.parse(RIPPLE_LIB.read_text(encoding="utf-8"))
    gap = None
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "GAP"
                                                for t in node.targets):
            gap = ast.literal_eval(node.value)
    if gap is None:
        raise RuntimeError("GAP registry not found in tasks/ripple_bank/_lib.py")
    out = {}
    for key, value in gap.items():
        ddl, source, fetched, filler, effort, overlap, note = value
        out[key] = {"id": key, "table": ddl.split("(")[0], "desc": note,
                    "source": source, "fetched": fetched, "effort": float(effort),
                    "overlap": overlap}
    return out


HELD_SOURCE = re.compile(
    r"pib|budget|rbi|\bar\b|annual report|concall|deck|filing|announcement|xbrl|"
    r"results|policy_events|delivery|insider|bulk|block|disclosure|other income|"
    r"board outcome|egm|placement|company's own|both companies|rationale", re.I)
EXTERNAL_SOURCE = re.compile(
    r"external|imd|lme|mcx|customs|cbic|paid|consensus|vahan|association|"
    r"industry body|agency|single-window|scrip master", re.I)


def held_of(item_id: str, audit: dict, proposals: dict) -> tuple:
    """(closable, evidence, path) for one registry id."""
    if item_id.startswith("G") and item_id in audit:
        g = audit[item_id]
        fetch = (g["fetch"] or "").lower()
        if "41%" in fetch or "probably" in fetch or "small" in fetch or "paid" in fetch \
                or "coverage holed" in fetch:
            closable = "partial"
        elif fetch.startswith("no"):
            closable = "yes"
        elif fetch.startswith("yes") or "not measured" in fetch:
            closable = "no"
        else:
            closable = "partial"
        path = ("new fetch" if ("yes" in fetch or "small" in fetch or "probably" in fetch)
                else "build from held data")
        evidence = re.sub(r"\*\*", "", g["source"]).strip()
        return closable, evidence, path
    if item_id in proposals:
        p = proposals[item_id]
        held_source = (bool(HELD_SOURCE.search(p["source"] or ""))
                       and not bool(EXTERNAL_SOURCE.search(p["source"] or "")))
        closable = {"yes": "yes", "partial": "partial"}.get(p["fetched"], "no")
        if closable == "no" and held_source:
            closable = "partial"  # the source text is held; only the table is missing
        path = "new fetch" if closable == "no" else "build from held data"
        return closable, f"{p['source']} -> {p['table']}", path
    if item_id in NG_HELD:
        value = NG_HELD[item_id]
        closable, evidence = value[0], value[1]
        path = value[2] if len(value) > 2 else (
            "build from held data" if closable != "no" else "new fetch")
        return closable, evidence, path
    if item_id in U_HELD:
        closable, evidence, path = U_HELD[item_id]
        return closable, evidence, path
    return "no", "unclassified", "new fetch"


def build_gap_clusters(audit: dict, ngs: dict, proposals: dict, cases: list[dict]) -> list[dict]:
    # registry: id -> description
    registry = {}
    for gid, g in audit.items():
        registry[gid] = g["desc"]
    for gid, desc in ngs.items():
        registry[gid] = desc
    for key, p in proposals.items():
        registry[key] = p["desc"] or p["table"]
    for uid, (_verdict, desc, _path) in U_HELD.items():
        registry[uid] = desc

    member_of = {}
    clusters = []
    groups = {canon: members for canon, members in GAP_GROUPS}
    for canon, members in groups.items():
        for m in members:
            member_of[m] = canon
        clusters.append(canon)
    for item in registry:
        if item not in member_of:
            member_of[item] = item
            clusters.append(item)
    missing_members = sorted({m for members in groups.values() for m in members
                              if m not in registry})
    if missing_members:
        raise RuntimeError(f"GAP_GROUPS names unknown gaps: {missing_members}")

    # canonical label = first sentence of the canonical member's description
    def label(cid):
        desc = registry.get(cid) or ""
        desc = re.sub(r"\*\*", "", desc)
        desc = re.split(r"(?<=[.!?])\s+", desc.strip())[0]
        if len(desc) > 110:
            desc = desc[:110].rsplit(" ", 1)[0] + "..."
        return desc

    cases_by_cluster = defaultdict(list)
    for c in cases:
        for g in c.get("_gaps") or []:
            canon = member_of.get(g)
            if canon:
                cases_by_cluster[canon].append(c["mid"])

    rows = []
    for cid in sorted(set(clusters)):
        members = groups.get(cid, [cid])
        statuses = [held_of(m, audit, proposals) for m in members]
        order = {"yes": 0, "partial": 1, "no": 2}
        closable = max(statuses, key=lambda s: order[s[0]])[0] if statuses else "no"
        paths = [s[2] for s in statuses]
        if closable == "yes" or all("build" in p for p in paths):
            path = "build from held data"
        elif any(p.startswith("NOT IN DATA") for p in paths) and not any(
                "fetch" in p for p in paths):
            path = "NOT IN DATA"
        else:
            path = "new fetch"
        evidence = "; ".join(dict.fromkeys(re.sub(r"\s+", " ", s[1]).strip()
                                           for s in statuses if s[1]))[:400]
        efforts = [proposals[m]["effort"] for m in members if m in proposals]
        g_efforts = [audit[m]["effort"] for m in members
                     if m in audit and audit[m]["effort"] is not None]
        if efforts or g_efforts:
            effort = max(sum(efforts) if efforts else 0.0,
                         max(g_efforts) if g_efforts else 0.0)
        else:
            effort = None
        mids = sorted(set(cases_by_cluster.get(cid, [])))
        rows.append({
            "id": cid, "title": label(cid), "members": members,
            "cases": mids, "n_cases": len(mids), "effort": effort,
            "ratio": (len(mids) / effort) if effort else None,
            "closable": closable, "path": path, "evidence": evidence,
            "spec": next((p["table"] for p in [proposals.get(m) for m in members]
                          if p), None),
        })

    rows.sort(key=lambda r: (r["ratio"] is None, -(r["ratio"] or 0),
                             -r["n_cases"], r["id"]))
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    return rows


# --------------------------------------------------------------------------- #
# bounded held-data probes (read-only)
# --------------------------------------------------------------------------- #
def run_probes() -> dict:
    out = {}
    try:
        from reality_engine.db.readonly import connect_ro
        data = Path(os.environ.get("REALITY_DATA_ROOT") or DATA_DEFAULT)
        db = data / "equity_intelligence.db"
        if not db.exists():
            return {"_error": f"missing {db}"}
        con = connect_ro(db, timeout_s=30)

        def one(key, sql, fmt):
            try:
                row = con.execute(sql).fetchone()
                out[key] = fmt(row)
            except Exception as exc:  # a probe failure must never fail the build
                out[key] = f"probe failed: {exc}"

        one("commodity", "select count(*), count(distinct commodity), min(date), max(date) "
                         "from mkt_commodity_daily",
            lambda r: f"mkt_commodity_daily: {r[0]:,} rows / {r[1]} commodity series / "
                      f"{r[2]}..{r[3]}")
        try:
            cols = [x[1] for x in con.execute("pragma table_info(mkt_commodity_daily)")]
            out["commodity"] += (", known_at column: " + ("yes" if "known_at" in cols
                                                         else "no"))
        except Exception:
            pass
        one("shareholding", "select count(*), count(distinct quarter_end) from shareholding",
            lambda r: f"shareholding: {r[0]:,} rows / {r[1]} quarter-ends (stub)")
        one("index_membership", "select count(*), count(distinct as_of) from index_membership",
            lambda r: f"index_membership: {r[0]:,} rows / {r[1]} distinct as_of")
        one("geographic", "select count(*) from geographic_exposure",
            lambda r: f"geographic_exposure: {r[0]:,} rows (undated, company_id-keyed)")
        one("policy_events", "select count(*), sum(quote_ok) from policy_events",
            lambda r: f"policy_events: {r[0]:,} rows / {r[1]:,} quote_ok")
        one("annual_fy26", "select count(*), sum(case when interest_coverage is null "
                           "then 1 else 0 end) from annual_financials where fiscal_year='FY26'",
            lambda r: f"annual_financials FY26: {r[0]:,} rows / {r[1]:,} with null "
                      f"interest_coverage")
        one("concall_docs", "select count(*) from corporate_documents where is_processed=1 "
                            "and doc_type like '%CONCALL%'",
            lambda r: f"corporate_documents: {r[0]:,} processed concall docs")
        one("etf_master", "select count(*) from etf_master",
            lambda r: f"etf_master: {r[0]:,} rows")
        one("etf_px", "select count(*) from etf_px", lambda r: f"etf_px: {r[0]:,} rows")
        one("non_ine", "select count(*) from master_companies where isin not like 'INE%'",
            lambda r: f"master_companies: {r[0]:,} non-INE rows (ETFs/other)")
        one("insider", "select count(*) from insider_trades_v2",
            lambda r: f"insider_trades_v2: {r[0]:,} rows")
        one("fii_dii", "select count(*), min(date), max(date) from mkt_fii_dii_cash",
            lambda r: f"mkt_fii_dii_cash: {r[0]:,} rows / {r[1]}..{r[2]}")
        one("delivery_tape", "select max(date) from daily_price_delivery",
            lambda r: f"daily_price_delivery max date: {r[0]}")
        one("macro", "select count(*), sum(doc_id is not null) from macro_events",
            lambda r: f"macro_events: {r[0]:,} rows / {r[1]:,} with doc_id")
        one("price_bands", "select count(*), min(date), max(date), count(distinct date) "
                           "from price_bands",
            lambda r: f"price_bands: {r[0]:,} rows / {r[3]:,} distinct dates / "
                      f"{r[1]}..{r[2]}")
        try:
            rx = connect_ro(data / "results_xbrl.db", timeout_s=30)
            rows = rx.execute("select taxonomy, count(*) from filings "
                              "group by 1 order by 2 desc limit 4").fetchall()
            out["taxonomies"] = "results_xbrl.filings taxonomies: " + ", ".join(
                f"{t}={n:,}" for t, n in rows)
        except Exception as exc:
            out["taxonomies"] = f"probe failed: {exc}"
        return out
    except Exception as exc:
        return {"_error": str(exc), **out}


PROBE_FOR = {
    "G0": ["etf_master", "etf_px", "non_ine"],
    "G1": ["taxonomies"],
    "G2": ["index_membership"],
    "G6": ["concall_docs"],
    "G8": ["price_bands"],
    "G10": ["policy_events", "macro"],
    "G11": ["taxonomies"],
    "G12": ["commodity"],
    "NG05": ["shareholding"],
    "NG06": ["insider"],
    "NG07": ["shareholding"],
    "NG18": ["fii_dii"],
    "NG21": ["macro"],
    "NG28": ["delivery_tape"],
    "revenue_geo_period": ["geographic"],
    "interest_cover": ["annual_fy26"],
    "day0_session": ["delivery_tape"],
    "leakage_window": ["delivery_tape"],
}


# --------------------------------------------------------------------------- #
# writers
# --------------------------------------------------------------------------- #
CTRL = dict.fromkeys(map(ord, "|\r\n"), " ")


def _cell(value, limit=180) -> str:
    s = "" if value is None else str(value)
    s = re.sub(r"\s+", " ", s).strip().translate(CTRL)
    return (s[:limit] + "...") if len(s) > limit else s


def _row(cells) -> str:
    return "| " + " | ".join(str(c) for c in cells) + " |"


def write_master_jsonl(cases: list[dict], path: Path) -> None:
    lines = [json.dumps({k: v for k, v in c.items() if not k.startswith("_")},
                        ensure_ascii=False) for c in cases]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _family_rows(cases: list[dict], matrix: dict):
    cells, _styles = matrix["cells"], matrix["styles"]
    fams = FAMILIES + ([None] if any(not c.get("family") for c in cases) else [])
    totals = Counter()
    for (fam, _lvl), n in cells.items():
        totals[fam] += n
    out = []
    for fam in fams:
        out.append((fam, [cells.get((fam, lvl), 0) for lvl in LEVELS], totals[fam]))
    return fams, out, totals


def write_master_md(cases, matrix, stats, path):
    fams, rows, totals = _family_rows(cases, matrix)
    levels = LEVELS
    cells = matrix["cells"]
    level_totals = [sum(cells.get((fam, lvl), 0) for fam in fams) for lvl in levels]
    lines = [
        "# Master question bank - one deduplicated bank from every source",
        "",
        "Built by `tasks/master_bank/build_master_bank.py`. Re-run: "
        "`python tasks/master_bank/build_master_bank.py --check`.",
        "",
        "Sources: Shivam's 30 fixed regressions (kept as written, `regression: true`), "
        "the 300 variations, the 300 open questions, the 200 ripple questions"
        + (", and the Reddit bank" if stats["reddit_present"] else
           " (the Reddit bank is not present yet; the loader is ready for it)") + ".",
        "",
        "## 1. Counts per source bank",
        "",
        _row(["bank", "rows in", "representatives", "merged as duplicate",
              "cases with >=1 row from the bank"]),
        _row(["---"] * 5),
    ]
    for b in stats["banks"]:
        lines.append(_row([b["name"], b["rows"], b["representatives"], b["duplicates"],
                           b["cases"]]))
    lines.append(_row(["**total**", stats["total_rows"], len(cases),
                       stats["total_rows"] - len(cases), len(cases)]))
    lines += [
        "",
        f"Unique cases: **{len(cases)}**. Originals kept: "
        f"**{stats['total_regression']}**. Duplicate rows merged: "
        f"**{stats['total_rows'] - len(cases)}**."
        + (" No two rows merge in the current banks: every case below is distinct "
           "once the naming / style / edge / period-label separations are applied. "
           "The near-duplicate layers still run on every build (`--check` §10 prints "
           "the closest cross-bank pairs and the exemption decisions); the fake "
           "Reddit check proves they merge when a real duplicate appears."
           if stats["total_rows"] == len(cases) else ""),
        "",
        "## 2. How the merge works",
        "",
        "- One common schema: `mid`, `source_bank`, `source_qid`, `question`, `entities`, "
        "`entity_level`, `entity_level_source`, `family` (list of 1-20, primary first), "
        "`family_source`, `variation`, `archetype`, `template`, `period`, `as_of`, "
        "`answer_kind`, `rubric` (evidence / steps / forbidden / ground truth), "
        "`coverage` (verdict / note / gap), `chain` (ripple only), `style`, "
        "`naming_variant`, `edge_case`, `regression`, `duplicates`.",
        "- Missing fields stay null. Shivam's 30 originals keep their text as written: "
        "QA1-QA10 from `QA10_BRIEF.md`; DBQ1-DBQ5 and Q11-Q25 use the documented short "
        "form in `QUERY_TEMPLATES` §5 because no fuller copy exists in the repo "
        "(`eval25_key.md` is absent).",
        "- `family` is a list. A source row that declares `\"2,11\"` counts in family 2 "
        "and family 11 in the matrix; its first entry is the primary family. The "
        "per-family tables in §4 list each case once, under its primary family, with "
        "the other families cross-referenced.",
        "- `entity_level` is derived deterministically (`derive_entity_level`) and its "
        "source is recorded: `given` (the bank declared it), `variation` (V7 scope -> "
        "industry/sector, V8 screen -> index/theme), `keywords` (entity type + question "
        "scope), `entities` (entity type only) or `fallback` (no signal; counted in "
        "`--check`, must stay under 10% of the open + ripple rows).",
        "- Layer 1, near-duplicate text: case-folding, punctuation and numbers removed, "
        "token Jaccard >= 0.80, and only between rows with the same entity, period, "
        "primary family, style and naming/edge dimension. A templated question on a "
        "different company is a different case and is never merged.",
        "- Layer 1b, the same near-duplicate text across banks: each bank fills the "
        "free-text subject from a different field (the originals use the theme label, "
        "the variations the policy title, the Reddit/open banks nothing), so the same "
        "case can carry two subject strings. Pairs from different banks merge at "
        "Jaccard >= 0.80 when the template, level, period label, style, naming/edge "
        "dimension and evidence shape agree; a stock-level pair must still share the "
        "entity key, and a non-stock pair must name the same subject (one bank's label "
        "may just be a longer form of the other's). A row that declares a V3/V4/V5/V9 "
        "naming or style variant stays its own case even then (the brief's robustness "
        "exemption); inside one bank such a pair is a deliberate variation, not a "
        "duplicate.",
        "- Layer 2, same case: same template + entity level + evidence shape + entity + "
        "period, even with different wording. Banks without an explicit template id "
        "(open, ripple) also need 0.50 wording similarity to confirm it is the same "
        "case; the archetype alone (A01, R01) is a family, not a template.",
        "- Kept separate by design: naming variants (ISIN / BSE code / old symbol), "
        "style variants (terse / Hinglish / as-of), edge cases that ask for a refusal "
        "(`NOT IN DATA`), and period-label variants (V6), because each tests a "
        "different robustness dimension. One representative per case, chosen as the "
        "richest rubric with a ground truth, with originals first.",
        "- `style` is classified by rule: bank Hinglish flag or >=2 Hindi function "
        "words -> Hinglish; `as of` / point-in-time wording or a V9 variation -> "
        "point-in-time; <=10 words or a V4 variation -> terse; else natural.",
        "- Ripple rows carry no family in their bank; the family is mapped from the "
        "archetype (R01->16, R02->18, R03->16, R04->16+19, R05->19, R06->3, R07->12, "
        "R08->16, R09->11, R10->9) and recorded as `family_source=\"archetype\"`. "
        "The ripple entity level is derived from the question and the chain's "
        "entities; R02/R06/R09 fix the scope by construction (policy cascade, "
        "capital-markets loop, leading-indicator series), and R10 is the specific "
        "company event.",
        "- Reddit rows declare a template family directly for 158 rows (the 115 "
        "originals plus the 43 pattern-gap rows added on 2026-10-28); the other 85 "
        "carry a `NEW:*` family because no template family fits (the bank's own "
        "report says so). Each `NEW:*` row is mapped from its archetype - the same "
        "rule the ripple map uses - and recorded as `family_source=\"pattern\"`: "
        "technical price state -> 3 (change over time), a breakout / gap / OI "
        "build-up / delivery spike -> 9 (event window), `group_basket` -> 8 "
        "(peers), `ipo_grey_listing` -> 9, `sebi_rule` -> 6 (policy -> companies), "
        "`corporate_action_aftermath` / `circuit_band` -> 12 (when / timeline), "
        "`entry_timing` / `hold_sell` -> 10 (opinion vs truth). An unknown "
        f"`NEW:*` archetype falls back to family {REDDIT_FAMILY_DEFAULT} "
        "(out-of-scope); no case is left without a family.",
        "",
        "## 3. Coverage matrix",
        "",
        "### 3.1 family x entity level x style",
        "",
        "Each cell is `cases (terse/natural/Hinglish/point-in-time)`.",
        "",
        _row(["family"] + levels + ["total"]),
        _row(["---"] * (len(levels) + 2)),
    ]
    style_cells = matrix["style_cells"]
    for fam, counts, total in rows:
        label = str(fam) if fam is not None else "none"
        rendered = []
        for lvl, n in zip(levels, counts):
            if not n:
                rendered.append(".")
            else:
                parts = [style_cells.get((fam, lvl, s), 0) for s in STYLES]
                rendered.append(f"{n} ({'/'.join(str(p) for p in parts)})")
        lines.append(_row([label] + rendered + [total]))
    lines.append(_row(["**total (case x family)**"] + level_totals
                      + [sum(level_totals)]))
    lines += [
        "",
        "A case with more than one family counts in every family it lists, so the "
        "totals are (case x family) pairs and exceed the number of cases "
        f"({len(cases)}). Family 10 (opinion vs truth) is "
        + (f"non-empty: {totals.get(10, 0)} case x family pairs, mapped from the "
           "Reddit `entry_timing` and `hold_sell` archetypes." if totals.get(10)
           else "empty in every source bank, so the per-family table in §4 shows "
                "the empty family explicitly."),
        "",
        "### 3.2 family x style",
        "",
        _row(["family"] + list(STYLES) + ["total"]),
        _row(["---"] * (len(STYLES) + 2)),
    ]
    style_totals = Counter()
    for fam, _counts, total in rows:
        vals = [matrix["styles"].get((fam, s), 0) for s in STYLES]
        for s, v in zip(STYLES, vals):
            style_totals[s] += v
        label = str(fam) if fam is not None else "none"
        lines.append(_row([label] + [v if v else "." for v in vals] + [total]))
    lines.append(_row(["**total**"] + [style_totals.get(s, 0) for s in STYLES]
                      + [sum(style_totals.values())]))
    lines += ["", "### 3.3 Empty and thin cells (fewer than 3 cases)", ""]
    thin = []
    for fam, counts, total in rows:
        for lvl, n in zip(levels, counts):
            if n < 3:
                thin.append((fam, total, lvl, n))
    thin.sort(key=lambda t: (-(t[1] or 0), t[3], LEVELS.index(t[2])))
    lines += [_row(["family", "level", "cases", "status"]), _row(["---"] * 4)]
    for fam, total, lvl, n in thin:
        lines.append(_row([str(fam) if fam is not None else "none", lvl, n,
                           "empty" if n == 0 else "thin"]))
    n_total3 = len(fams) * len(levels) * len(STYLES)
    n_empty3 = sum(1 for fam in fams for lvl in levels for s in STYLES
                   if not style_cells.get((fam, lvl, s)))
    n_thin3 = sum(1 for fam in fams for lvl in levels for s in STYLES
                  if 0 < style_cells.get((fam, lvl, s), 0) < 3)
    lines += [
        "### 3.4 The full 3D grid",
        "",
        f"The full 3D grid has **{n_total3}** cells ({len(fams)} families x "
        f"{len(levels)} levels x {len(STYLES)} styles): **{n_empty3}** empty, "
        f"**{n_thin3}** thin (1-2 cases), "
        f"**{n_total3 - n_empty3 - n_thin3}** with 3 or more cases.",
        "",
        "### 3.5 Style gaps inside a family",
        "",
    ]
    lines += [_row(["family", "missing style"]), _row(["---"] * 2)]
    for fam, _counts, total in rows:
        if not total:
            continue
        missing = [s for s in STYLES if matrix["styles"].get((fam, s), 0) == 0]
        if missing:
            lines.append(_row([str(fam) if fam is not None else "none",
                               ", ".join(missing)]))
    lines += ["", "## 4. One table per family", "",
              "Each case appears once, under its primary family; `also` lists its "
              "other families. §3 counts a multi-family case in every family it "
              "lists.", ""]
    family_tables = FAMILIES + ([None] if any(not c.get("family") for c in cases)
                                else [])
    for fam in family_tables:
        selected = [c for c in cases if primary_family(c) == fam]
        cross_cases = [c for c in cases if fam is not None
                       and fam in (c.get("family") or [])[1:]]
        label = f"Family {fam} - {FAMILY_NAMES.get(fam, '')}" if fam else \
            "Family not declared"
        suffix = (f"; {len(cross_cases)} cross-referenced" if cross_cases else "")
        lines += [f"### {label} ({len(selected)} primary cases{suffix})", ""]
        if not selected and not cross_cases:
            lines += ["No case declares this family in any source bank.", ""]
            continue
        if not selected:
            lines += [f"No case has this as its primary family; the "
                      f"{len(cross_cases)} cases below cross-reference it.", ""]
        lines += [_row(["mid", "source", "level", "style", "coverage", "also",
                        "question"]),
                  _row(["---"] * 7)]
        for c in selected:
            src = f"{c['source_bank']}:{c['source_qid']}"
            if c["duplicates"]:
                src += f" (+{len(c['duplicates'])} dup)"
            verdict = (c.get("coverage") or {}).get("verdict")
            also = [str(f) for f in (c.get("family") or [])[1:] if f != fam]
            lines.append(_row([c["mid"], src, c.get("entity_level"),
                               c.get("style"), verdict or "-",
                               ", ".join(also) or "-",
                               _cell(c.get("question"), 170)]))
        for c in cross_cases:
            src = f"{c['source_bank']}:{c['source_qid']}"
            if c["duplicates"]:
                src += f" (+{len(c['duplicates'])} dup)"
            verdict = (c.get("coverage") or {}).get("verdict")
            primary = primary_family(c)
            lines.append(_row([c["mid"], src, c.get("entity_level"),
                               c.get("style"), verdict or "-",
                               f"primary {primary}",
                               _cell(c.get("question"), 170)]))
        lines.append("")
    lines += [
        "## 5. Files",
        "",
        "- `MASTER_BANK.jsonl` - one JSON object per unique case (the representative), "
        "with `duplicates` listing every merged source row.",
        "- `MASTER_BANK.md` - this file.",
        "- `GAP_ROLLUP.md` - every named gap, deduplicated and ranked by unique cases "
        "blocked per unit of effort, with the held-data verdict.",
        "",
    ]
    by_key = {(c["source_bank"], c["source_qid"]): c for c in cases}
    hand_rows = []
    for bank, qid, expected in HAND_CHECK:
        case = by_key.get((bank, qid))
        got = case.get("entity_level") if case else None
        hand_rows.append((case["mid"] if case else "-", f"{bank}:{qid}",
                          expected, got))
    hand_ok = sum(1 for row in hand_rows if row[2] == row[3])
    lines += [
        "## 6. Hand check (30 rows across the banks)",
        "",
        "The expected level is the scope the question asks about, read from the "
        "question text (not copied from the derived value). Two deliberately "
        "ambiguous rows are counted as misses: A09-07 (OMC industry read as the "
        "stock IOC/BPCL pair) and A13-08 (supplier industry read as the named JV "
        "parent).",
        "",
        f"**{hand_ok}/{len(hand_rows)} = {hand_ok / len(hand_rows):.1%}** correct.",
        "",
        _row(["mid", "source", "expected", "derived", "result"]),
        _row(["---"] * 5),
    ]
    for mid, src, expected, got in hand_rows:
        lines.append(_row([mid, src, expected, got or "-",
                           "ok" if expected == got else "MISS"]))
    lines.append("")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_gap_md(gaps, cases, stats, probes, path):
    no_gap = [c["mid"] for c in cases if not c.get("_gaps")]
    lines = [
        "# Gap roll-up - every named gap, deduplicated and ranked",
        "",
        "Built by `tasks/master_bank/build_master_bank.py` from the three registries: "
        "G0-G12 (`BACKWARD_REQUIREMENTS_AUDIT_2026-10-27_REPORT.md` §10), NG01-NG29 "
        "(`QUESTION_BANK_OPEN_2026-10-27.jsonl` + the open-bank builder) and the 41 "
        "schema proposals (`tasks/ripple_bank/_lib.py`). Identity clusters are listed "
        "per gap; overlap that is only a dependency (for example G11's XBRL concept "
        "map feeding several derived tables) is not treated as a duplicate.",
        "",
        "Ranking: unique master cases blocked per build day. `closable from held data` "
        "is **yes** (only parsing/mapping of held rows), **partial** (some held, some "
        "missing) or **no**; the `path` column then says `new fetch` or `NOT IN DATA`. "
        "Effort is the larger of the proposal-table sum and the audit estimate, so a "
        "cluster of four series tables is not ranked as one.",
        "",
        "A ripple proposal whose source is held filing/text (AR, concall, deck, XBRL, "
        "PIB, insider/deal tape) counts as partial / build-from-held even when its "
        "derived table was never fetched; external-only series (LME, IMD, customs, "
        "Vahan, agency releases, paid consensus) stay `new fetch`.",
        "",
        "## 1. Summary",
        "",
        f"- named gaps in the registries: **{stats['n_named']}** "
        f"(13 G + 29 NG + 41 proposals)",
        f"- identity clusters after the merge: **{len(gaps)}**",
        f"- cases blocked by at least one gap: **{len(cases) - len(no_gap)}** of "
        f"{len(cases)}; cases with no gap named: **{len(no_gap)}**",
        "",
        "## 2. Held-data probes (read-only, bounded)",
        "",
    ]
    if probes.get("_error"):
        lines.append(f"Probes could not run: {probes['_error']}")
    else:
        lines += [_row(["probe", "result"]), _row(["---"] * 2)]
        for key in sorted(probes):
            if not key.startswith("_"):
                lines.append(_row([key, _cell(probes[key], 200)]))
    lines += [
        "",
        "## 3. Ranked gaps",
        "",
        _row(["#", "gap", "cases", "effort d", "cases/day", "closable", "path",
              "members"]),
        _row(["---"] * 8),
    ]
    for g in gaps:
        members = ", ".join(g["members"][:5])
        if len(g["members"]) > 5:
            members += f" (+{len(g['members']) - 5})"
        lines.append(_row([
            g["rank"], g["id"], g["n_cases"],
            f"{g['effort']:.1f}" if g["effort"] else "-",
            f"{g['ratio']:.1f}" if g["ratio"] else "-",
            g["closable"], g["path"], _cell(members, 90),
        ]))
    lines += ["", "## 4. Every gap: the cases it blocks and what would close it", ""]
    for g in gaps:
        probe_keys = PROBE_FOR.get(g["id"], [])
        probe = " | ".join(probes[k] for k in probe_keys if k in probes)
        lines += [
            f"### {g['rank']}. {g['id']} - {g['title']}",
            "",
            f"- members: {', '.join(g['members'])}",
            f"- cases blocked: **{g['n_cases']}**"
            + (f" - {', '.join(g['cases'])}" if g["cases"] else " (none in the banks yet)"),
            f"- closable from held data: **{g['closable']}**; path: {g['path']}",
            f"- held evidence: {g['evidence'] or 'not established'}",
            f"- effort: {g['effort']:.1f} days" if g["effort"] else "- effort: not estimated",
        ]
        if probe:
            lines.append(f"- probe: {probe}")
        lines.append("")
    lines += [
        "## 5. Cases with no gap named",
        "",
        ", ".join(no_gap) if no_gap else "none",
        "",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------- #
# build
# --------------------------------------------------------------------------- #
def build(reddit_path: Path | None = None, write: bool = True) -> dict:
    records = []
    records += load_originals()
    records += load_variations300()
    records += load_open300()
    records += load_ripple200()
    reddit_present = False
    reddit_file = reddit_path or REDDIT_DEFAULT
    if reddit_file and Path(reddit_file).exists():
        records += load_reddit(Path(reddit_file))
        reddit_present = True

    for rec in records:
        level, source = derive_entity_level(rec)
        rec["entity_level"] = level
        rec["entity_level_source"] = source

    cases = dedupe(records)

    banks = []
    total_reg = sum(1 for c in cases if c.get("regression"))
    for name in ("shivam30", "variations300", "open300", "ripple200", "reddit200"):
        rows = sum(1 for r in records if r["source_bank"] == name)
        reps = sum(1 for c in cases if c["source_bank"] == name)
        with_bank = sum(1 for c in cases if name in c["source_banks"])
        banks.append({"name": name, "rows": rows, "representatives": reps,
                      "duplicates": rows - reps, "cases": with_bank})
    stats = {
        "banks": banks, "total_rows": len(records), "total_regression": total_reg,
        "reddit_present": reddit_present,
    }

    matrix = coverage_matrix(cases)
    audit = parse_audit_gaps()
    ngs = parse_ng_gaps(read_jsonl(BANK_FILES["open300"]))
    proposals = parse_ripple_proposals()
    stats["n_g"], stats["n_ng"], stats["n_prop"] = len(audit), len(ngs), len(proposals)
    stats["n_named"] = len(audit) + len(ngs) + len(proposals)
    gaps = build_gap_clusters(audit, ngs, proposals, cases)
    probes = run_probes()
    before_cells = _before_cells(records)

    result = {"cases": cases, "records": records, "stats": stats, "matrix": matrix,
              "gaps": gaps, "probes": probes, "registry": {"audit": audit, "ng": ngs,
                                                           "proposals": proposals},
              "before_cells": before_cells}
    if write:
        OUT.mkdir(parents=True, exist_ok=True)
        write_master_jsonl(cases, OUT / "MASTER_BANK.jsonl")
        write_master_md(cases, matrix, stats, OUT / "MASTER_BANK.md")
        write_gap_md(gaps, cases, stats, probes, OUT / "GAP_ROLLUP.md")
    return result


# --------------------------------------------------------------------------- #
# before/after reporting
# --------------------------------------------------------------------------- #
LEVEL_CODES = {
    "stock": "stk", "industry": "ind", "sector": "sec", "theme": "thm",
    "index": "idx", "market-cap bucket": "mcap", "price band": "band",
    "policy": "pol", "macro": "mac", "market-wide": "mkt",
}


def _before_cells(records: list[dict]) -> Counter:
    """The pre-fix matrix: first family only, ripple inferred, open stock default."""
    cells = Counter()
    for row in records:
        if row["source_bank"] == "ripple200":
            fam = OLD_RIPPLE_FAMILY.get(str(row.get("archetype")))
            level = "stock"
        else:
            fam = primary_family(row)
            if row["source_bank"] == "open300":
                entities = row.get("entities") or []
                level = ((entities[0].get("type") if entities
                          and isinstance(entities[0], dict) else None) or "stock")
            else:
                level = row.get("entity_level") or "stock"
        cells[(fam, level)] += 1
    return cells


def _matrix_totals(cells: Counter) -> Counter:
    totals = Counter()
    for (fam, _level), n in cells.items():
        totals[fam] += n
    return totals


def _print_matrix(title: str, cells: Counter) -> None:
    totals = _matrix_totals(cells)
    fams = FAMILIES + ([None] if None in totals else [])
    print(title)
    print("  " + " ".join(f"{LEVEL_CODES[lvl]:>5}" for lvl in LEVELS)
          + "  total")
    for fam in fams:
        label = f"{fam:>2}" if fam is not None else " -"
        vals = [cells.get((fam, lvl), 0) for lvl in LEVELS]
        print("  " + label + " " + " ".join(f"{v:>5}" for v in vals)
              + f"  {totals.get(fam, 0):>5}")
    print("  " + " " * 2 + " " + " ".join(f"{sum(cells.get((f, lvl), 0) for f in fams):>5}"
                                          for lvl in LEVELS)
          + f"  {sum(cells.values()):>5}")
    print("  level key: " + ", ".join(f"{LEVEL_CODES[l]}=l" for l in LEVELS))
    print()


def _thin_after(cells: Counter, limit=10):
    totals = _matrix_totals(cells)
    rows = []
    for fam in FAMILIES:
        total = totals.get(fam, 0)
        for lvl in LEVELS:
            n = cells.get((fam, lvl), 0)
            if n < 3:
                rows.append((fam, lvl, n, total))
    rows.sort(key=lambda t: (-t[3], t[2], t[0], LEVELS.index(t[1])))
    return rows[:limit], len(rows)


def _family_10_evidence(records: list[dict], cases: list[dict]) -> str:
    declared = [r for r in records if 10 in (r.get("family") or [])]
    in_cases = [c["mid"] for c in cases if 10 in (c.get("family") or [])]
    per_bank = {}
    for bank in ("shivam30", "variations300", "open300", "ripple200", "reddit200"):
        fams = sorted({f for r in records if r["source_bank"] == bank
                       for f in (r.get("family") or [])})
        per_bank[bank] = fams
    return ("family 10: declared by "
            f"{len(declared)} source rows and {len(in_cases)} cases; "
            "families present per bank: "
            + "; ".join(f"{k}={v}" for k, v in per_bank.items() if v))
# --------------------------------------------------------------------------- #
# acceptance checks
# --------------------------------------------------------------------------- #
def _fake_reddit(path: Path) -> Path:
    rows = [
        {"qid": "REDD-001",
         "question": "What did KEI say about the Sanand phase-1 commissioning date in "
                     "the Q1FY27 call, and how late was it?",
         "entities": [{"symbol": "KEI", "isin": "INE878B01027"}],
         "entity_level": "stock", "family": "12", "answer_kind": "date",
         "period": "Q1FY27", "as_of": "2026-08-15",
         "rubric": {"required_evidence": "concall_facts.cc_items",
                    "required_steps": "date the promise, then the commission",
                    "forbidden": "quoting only the later line", "ground_truth": None},
         "coverage": {"verdict": "partial", "note": "", "gap": "G6"},
         "style": "natural"},
        {"qid": "REDD-002",
         "prompt": "copper cable margin pass-through - who eats the gap?",
         "entities": ["POLYCAB", "KEI"], "level": "industry",
         "family": [16], "kind": "text+quote", "period": "FY27",
         "chain": [{"hop": 1, "gap_key": "cost_structure"},
                   {"hop": 2, "gap_key": "pass_through"}],
         "coverage": "partial"},
        {"qid": "REDD-003",
         "text": "Is the data-centre tax holiday in the policy record, and since when?",
         "entities": [], "answer_kind": "text"},
        {"qid": "REDD-004",
         "question": "Laptop resale prices doubled - kya ye structural hai, aur kaun "
                     "jeetta hai? (Hinglish)",
         "entities": [{"name": "refurbished electronics market"}],
         "entity_level": "theme", "family": "20", "style": "Hinglish"},
        {"id": "REDD-005",
         "question": "KEI's Sanand phase-1 commissioning date in the Q1FY27 call: what "
                     "did the company say, and how late was it?",
         "entities": [{"symbol": "KEI", "isin": "INE878B01027"}],
         "entity_level": "stock", "family": "12", "answer_kind": "date",
         "period": "Q1FY27", "as_of": "2026-08-15",
         "rubric": {"required_evidence": "concall_facts.cc_items"},
         "coverage": {"verdict": "partial", "note": "", "gap": "G6"},
         "style": "natural"},
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
                    encoding="utf-8")
    return path


def check(result: dict, fake_reddit: Path) -> bool:
    cases, records = result["cases"], result["records"]
    stats, gaps = result["stats"], result["gaps"]
    ok = True

    def req(cond, label, detail=""):
        nonlocal ok
        mark = "PASS" if cond else "FAIL"
        if not cond:
            ok = False
        print(f"{mark}  {label}" + (f" - {detail}" if detail else ""))

    # 1. every source row maps to exactly one master case
    mapped = defaultdict(list)
    for c in cases:
        mapped[(c["source_bank"], c["source_qid"])].append(c["mid"])
        for d in c["duplicates"]:
            mapped[(d["source_bank"], d["source_qid"])].append(c["mid"])
    dups = {k: v for k, v in mapped.items() if len(v) != 1}
    req(not dups, "1. every source row maps to exactly one case",
        f"{len(records)} rows -> {len(cases)} cases; "
        f"{sum(stats['banks'][i]['duplicates'] for i in range(len(stats['banks'])))} "
        f"merged as duplicates" + (f"; broken: {list(dups)[:3]}" if dups else ""))
    missing = [r["source_qid"] for r in records
               if (r["source_bank"], r["source_qid"]) not in mapped]
    req(not missing, "1b. no source row is silently dropped",
        f"missing: {missing[:5]}" if missing else "all rows represented")
    for b in stats["banks"]:
        print(f"      {b['name']:<14} rows {b['rows']:>4}  reps {b['representatives']:>4}  "
              f"dups {b['duplicates']:>3}  cases {b['cases']:>4}")

    # 2. the 30 originals
    reg = sorted(c["source_qid"] for c in cases if c.get("regression"))
    req(reg == sorted(ORIG_IDS), "2. all 30 originals present as regressions",
        f"{len(reg)}/30" if reg == sorted(ORIG_IDS) else f"got {len(reg)}: {reg[:6]}")
    merged_away = [d["source_qid"] for c in cases for d in c["duplicates"]
                   if d["source_bank"] == "shivam30"]
    req(not merged_away, "2b. originals are representatives, never merged away",
        f"merged away: {merged_away}" if merged_away
        else "all 30 originals are representatives (none listed as a duplicate)")

    # 3. outputs
    for name, marker in (("MASTER_BANK.jsonl", '"mid"'),
                         ("MASTER_BANK.md", "## 3. Coverage matrix"),
                         ("GAP_ROLLUP.md", "## 3. Ranked gaps")):
        p = OUT / name
        req(p.exists() and p.stat().st_size > 0 and marker in p.read_text(
            encoding="utf-8")[:400000], f"3. {name} written", f"{p}")
    jsonl_rows = read_jsonl(OUT / "MASTER_BANK.jsonl")
    req(len(jsonl_rows) == len(cases), "3b. JSONL has one line per unique case",
        f"{len(jsonl_rows)} lines / {len(cases)} cases")

    # 4. re-running with the Reddit bank present
    fake = _fake_reddit(fake_reddit)
    fake_res = build(reddit_path=fake, write=False)
    fake_map = defaultdict(list)
    for c in fake_res["cases"]:
        fake_map[(c["source_bank"], c["source_qid"])].append(c["mid"])
        for d in c["duplicates"]:
            fake_map[(d["source_bank"], d["source_qid"])].append(c["mid"])
    fake_rows = [r for r in fake_res["records"] if r["source_bank"] == "reddit200"]
    reddit_cases = [c for c in fake_res["cases"] if c["source_bank"] == "reddit200"]
    req(len(reddit_cases) == 4 and
        sum(len(c["duplicates"]) for c in reddit_cases) == 1,
        "4. 5-row fake Reddit bank loads and dedupes",
        f"{len(reddit_cases)} cases, "
        f"{sum(len(c['duplicates']) for c in reddit_cases)} duplicate merged")
    req(len(fake_rows) == 5 and all(
        fake_map.get((r["source_bank"], r["source_qid"])) for r in fake_rows),
        "4b. every fake Reddit row is mapped", f"{len(fake_rows)} rows")
    fake_qids = {r["source_qid"] for r in fake_rows}
    real_qids = {r["source_qid"] for r in records if r["source_bank"] == "reddit200"}
    leaked = sorted(fake_qids & real_qids)
    under_tmp = ".tmp" in fake_reddit.parts
    req(under_tmp and stats["reddit_present"] and bool(real_qids) and not leaked,
        "4c. the real build loads the real Reddit file, never the fake rows",
        f"fake bank under .tmp={under_tmp}; real Reddit rows {len(real_qids)}; "
        f"fake qids {sorted(fake_qids)}; leaked {leaked or 0}")

    # 5. registries
    req(stats["n_g"] == 13, "5. G0-G12 parsed", f"{stats['n_g']} gaps")
    req(stats["n_ng"] == 29, "5b. NG01-NG29 parsed", f"{stats['n_ng']} gaps "
        f"(NG20 comes from the open-bank builder)")
    req(stats["n_prop"] == 41, "5c. 41 ripple proposals parsed",
        f"{stats['n_prop']}")
    known_gaps = set(result["registry"]["audit"]) | set(result["registry"]["ng"]) \
        | set(result["registry"]["proposals"]) | set(U_HELD)
    unknown = sorted({g for c in cases for g in (c.get("_gaps") or [])
                      if g not in known_gaps})
    req(not unknown, "5d. every gap id on a case is in a registry",
        f"unknown: {unknown[:5]}" if unknown else "all known")
    gapped = sum(1 for c in cases if c.get("_gaps"))
    req(gapped > 0 and len(gaps) > 0, "5e. gap roll-up populated",
        f"{gapped} cases carry a gap; {len(gaps)} clusters")

    # 6. schema sanity
    mids = [c["mid"] for c in cases]
    req(len(set(mids)) == len(mids), "6. mids are unique")
    req(all(c["question"].strip() for c in cases), "6b. every case has question text")
    req(all(isinstance(c.get("family"), list) and c["family"]
            and all(f in FAMILIES for f in c["family"]) for c in cases),
        "6c. every case declares a non-empty list of families 1-20",
        f"{sum(1 for c in cases if not c.get('family'))} empty")
    req(all(c.get("style") in STYLES for c in cases), "6d. style values are allowed")
    pair_count = sum(len(c["family"]) for c in cases)
    matrix_count = sum(result["matrix"]["cells"].values())
    req(pair_count == matrix_count, "6e. multi-family rows counted in every family",
        f"{pair_count} case x family pairs = matrix total {matrix_count}")
    bad_levels = [c["mid"] for c in cases
                  if c.get("entity_level") not in LEVELS
                  or c.get("entity_level_source") not in LEVEL_SOURCES]
    req(not bad_levels, "6f. every case has a derived entity level and a source",
        f"bad: {bad_levels[:5]}" if bad_levels else
        f"sources: {dict(Counter(c['entity_level_source'] for c in cases))}")
    or_rows = [c for c in cases if c["source_bank"] in ("open300", "ripple200")]
    fallback = [c for c in or_rows if c["entity_level"] == "stock"
                and c["entity_level_source"] == "fallback"]
    rate = len(fallback) / len(or_rows) if or_rows else 0.0
    req(rate < 0.10, "6g. open + ripple fall back to stock under 10%",
        f"{len(fallback)}/{len(or_rows)} = {rate:.1%} (stock rows derived from a "
        f"named company/keyword: "
        f"{sum(1 for c in or_rows if c['entity_level'] == 'stock') - len(fallback)})")

    # 7. the families the reviewer named
    fam_totals = _matrix_totals(result["matrix"]["cells"])
    missing = [f for f in (5, 7, 8) if not fam_totals.get(f)]
    req(not missing, "7. families 5, 7 and 8 are non-zero",
        ", ".join(f"{f}={fam_totals.get(f, 0)}" for f in (5, 7, 8)))
    declares10 = any(10 in (r.get("family") or []) for r in records)
    if declares10:
        req(fam_totals.get(10, 0) > 0, "7b. family 10 is present in a source and "
            "non-zero in the matrix", _family_10_evidence(records, cases))
    else:
        req(fam_totals.get(10, 0) == 0, "7b. family 10 is truly absent from every "
            "source", _family_10_evidence(records, cases))

    # 8. ripple family mapping
    bad_ripple = [c["mid"] for c in cases if c["source_bank"] == "ripple200"
                  and c.get("family") != RIPPLE_FAMILY.get(c.get("archetype"))]
    req(not bad_ripple, "8. every ripple row carries its archetype family",
        f"bad: {bad_ripple[:5]}" if bad_ripple else f"mapping: {RIPPLE_FAMILY}")

    # 8b. Reddit NEW:* families (no template family in the source bank)
    new_rows = [r for r in records if r["source_bank"] == "reddit200"
                and str(r.get("_family_declared") or "").upper().startswith("NEW:")]
    req(new_rows and all(r.get("family") and r.get("family_source") == "pattern"
                         for r in new_rows),
        "8b. every Reddit NEW:* family maps to a template family",
        f"{len(new_rows)} rows; mapping: {REDDIT_FAMILY} "
        f"(default {REDDIT_FAMILY_DEFAULT})")

    # 9. 30-row hand check
    by_key = {(c["source_bank"], c["source_qid"]): c for c in cases}
    checked = []
    for bank, qid, expected in HAND_CHECK:
        case = by_key.get((bank, qid))
        got = case.get("entity_level") if case else None
        checked.append((bank, qid, expected, got, case.get("mid") if case else "-"))
    correct = sum(1 for row in checked if row[2] == row[3])
    print(f"      hand check: {len(checked)} rows, {correct} correct "
          f"({correct / len(checked):.1%})")
    for bank, qid, expected, got, mid in checked:
        mark = "ok  " if expected == got else "MISS"
        print(f"      {mark} {mid} {bank}:{qid:<8} expected {expected:<18} got {got}")
    req(len(checked) == 30, "9. hand check covers 30 rows across the banks",
        f"{len(checked)} rows")
    req(correct / len(checked) >= 0.90, "9b. hand check at least 90% accurate",
        f"{correct}/{len(checked)} = {correct / len(checked):.1%}")

    # 10. the near-duplicate and same-case layers run across banks
    toks = [norm_words(r["question"]) for r in records]
    pairs = sorted(((jaccard(toks[i], toks[j]), i, j)
                    for i, j in combinations(range(len(records)), 2)
                    if records[i]["source_bank"] != records[j]["source_bank"]),
                   reverse=True)
    mid_of = {key: c["mid"] for c in cases
              for key in [(c["source_bank"], c["source_qid"])]
              + [(d["source_bank"], d["source_qid"]) for d in c["duplicates"]]}
    near = [(s, a, b) for s, a, b in pairs
            if s >= 0.80 and cross_bank_same_case(records[a], records[b])]
    exempt = [(s, a, b) for s, a, b in near
              if is_wording_variant(records[a]) or is_wording_variant(records[b])]
    exempt_ids = {(a, b) for _s, a, b in exempt}
    unmerged = [(s, a, b) for s, a, b in near if (a, b) not in exempt_ids
                and mid_of[(records[a]["source_bank"], records[a]["source_qid"])]
                != mid_of[(records[b]["source_bank"], records[b]["source_qid"])]]
    merged = [c for c in cases if len(c["source_banks"]) > 1]
    req(not unmerged,
        "10. near-duplicate layer merges every genuine cross-bank duplicate",
        f"{len(pairs)} cross-bank pairs; {len(near)} same-case at Jaccard >= 0.80; "
        f"{len(exempt)} exempt as a declared naming/style variant; "
        f"{len(merged)} merged case(s)")
    for score, a, b in exempt:
        print(f"      exempt naming/style variant: {score:.3f}  "
              f"{records[a]['source_bank']}:{records[a]['source_qid']} "
              f"({records[a]['variation']}) vs {records[b]['source_bank']}:"
              f"{records[b]['source_qid']}")
    print("      top 10 closest cross-bank pairs (token Jaccard):")
    for score, i, j in pairs[:10]:
        a, b = records[i], records[j]
        print(f"      {score:.3f}  {a['source_bank']}:{a['source_qid']} vs "
              f"{b['source_bank']}:{b['source_qid']}")
    grp = defaultdict(list)
    for i, r in enumerate(records):
        grp[case_key(r)].append(i)
    cross_case = [v for v in grp.values()
                  if len({records[i]["source_bank"] for i in v}) > 1]
    reddit_pairs = [(s, a, b) for s, a, b in pairs
                    if "reddit200" in (records[a]["source_bank"],
                                       records[b]["source_bank"])]
    print(f"      same-case groups spanning more than one bank (layer 2): "
          f"{len(cross_case)}")
    if reddit_pairs:
        score, a, b = reddit_pairs[0]
        print(f"      closest Reddit vs another bank: {score:.3f}  "
              f"{records[a]['source_bank']}:{records[a]['source_qid']} vs "
              f"{records[b]['source_bank']}:{records[b]['source_qid']}")

    print()
    print(f"{'OK' if ok else 'FAILED'}: {len(records)} source rows -> {len(cases)} "
          f"master cases, {stats['total_regression']} regressions, "
          f"{stats['n_named']} named gaps -> {len(gaps)} clusters")
    return ok


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="build, then run the acceptance checks")
    ap.add_argument("--reddit", default=None, help="path to a Reddit bank jsonl")
    args = ap.parse_args(argv)
    result = build(reddit_path=Path(args.reddit) if args.reddit else None, write=True)
    stats = result["stats"]
    print(f"rows {stats['total_rows']} -> cases {len(result['cases'])}; "
          f"regressions {stats['total_regression']}; gaps {stats['n_named']} -> "
          f"{len(result['gaps'])} clusters")
    for b in stats["banks"]:
        print(f"  {b['name']:<14} rows {b['rows']:>4}  reps {b['representatives']:>4}  "
              f"dups {b['duplicates']:>3}")
    print(f"wrote {OUT / 'MASTER_BANK.jsonl'}")
    print(f"wrote {OUT / 'MASTER_BANK.md'}")
    print(f"wrote {OUT / 'GAP_ROLLUP.md'}")
    if result.get("before_cells") is not None:
        _print_matrix("BEFORE (primary family only; Reddit NEW:* already mapped; "
                      "ripple inferred level):", result["before_cells"])
    _print_matrix("AFTER (family list; a row counts in every family it lists):",
                  result["matrix"]["cells"])
    thin, n_thin = _thin_after(result["matrix"]["cells"])
    print(f"THIN / EMPTY family x level cells after: {n_thin} (fewer than 3 cases); "
          f"top 10 by family size:")
    print("  family level          cases  family-total")
    for fam, lvl, n, total in thin:
        print(f"  {fam:>6} {lvl:<15} {n:>4}  {total:>12}")
    print()
    print(_family_10_evidence(result["records"], result["cases"]))
    print()
    if args.check:
        return 0 if check(result, ROOT / ".tmp" / "reddit_fake_5row.jsonl") else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
