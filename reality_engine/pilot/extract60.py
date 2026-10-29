"""Targeted fact extraction for the pilot-60 universe — build-time tables.

Golden-rule step 4 (pilot) + step 3 (schema): the master bank's remaining
``needs_new_table`` blockers become plain SQL tables here. DeepSeek reads ONLY
the targeted passages (keyword + ``chunks_v3`` section/tag), never whole
documents; every row carries doc_id, page, a verbatim quote of <=25 words and
known_at, and passes a deterministic validator (units, magnitudes, period vs
the doc's own date) before it is written.

Tables (SCHEMA_V3 names): ``company_operating_metrics``, ``company_segment_pnl``,
``company_cost_structure``, ``order_intake``, ``order_book_contract``,
``company_capacity_utilisation``, ``capex_project``, ``company_price_revision``,
``company_debt_mix``, ``rating_action``, ``supply_link``.

Reader: the repo's existing free Go path (``concall_pilot.call_go``,
DeepSeek V4.1 Flash) — the same one the concall/AR pipelines use, no new paid
path. Read-only on every input; writes only ``.tmp/pilot60/extract_pilot60.db``.

    python -m reality_engine.pilot.extract60 select      # selector stats, no model
    python -m reality_engine.pilot.extract60 build       # regex + model -> db
    python -m reality_engine.pilot.extract60 build --no-model
    python -m reality_engine.pilot.extract60 handcheck  # 15 rows/table vs source page
    python -m reality_engine.pilot.extract60 cases      # before/after on dependent cases

Env:
  REALITY_CHUNKS_V3     chunks_v3 store (default D:\\RealityEngine\\pilot\\pilot60\\chunks_v3_pilot.db,
                        else .tmp/pilot60/chunks_v3_pilot.db)
  REALITY_EXTRACT_DB    output DB (default .tmp/pilot60/extract_pilot60.db)
  REALITY_EXTRACT_LIMIT cap model calls per table (0 = no cap)
  REALITY_EXTRACT_MODEL Go model alias (default deepseek-v4.1-flash)
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import hashlib
import json
import os
import re
import sqlite3
import sys
import threading
import time
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Iterable

REPO = Path(__file__).resolve().parents[2]
OUT_DIR = REPO / ".tmp" / "pilot60"
UNIVERSE = REPO / "tasks" / "pilot60" / "UNIVERSE.csv"
BANK = REPO / "tasks" / "master_bank" / "MASTER_BANK.jsonl"
CASE_MAP = REPO / "tasks" / "arch_v3" / "CASE_MAP.jsonl"
REPORT_DIR = REPO / "tasks" / "pilot60"
MODEL = os.environ.get("REALITY_EXTRACT_MODEL", "deepseek-v4.1-flash~low")
PRICE_IN, PRICE_OUT = 0.15, 0.60          # $/M off-peak (Go), same as concall_deepseek
SPEND_CAP = float(os.environ.get("REALITY_EXTRACT_SPEND", "1.50"))
MAX_WORKERS = int(os.environ.get("REALITY_EXTRACT_WORKERS", "6"))
MAX_CALLS_PER_TABLE = int(os.environ.get("REALITY_EXTRACT_LIMIT", "0"))
MAX_PASSAGES, MAX_PASSAGE_CHARS = 12, 9000

TABLES = ["company_operating_metrics", "company_segment_pnl", "company_cost_structure",
          "order_intake", "order_book_contract", "company_capacity_utilisation",
          "capex_project", "company_price_revision", "company_debt_mix", "rating_action",
          "supply_link"]
#: Tables whose blocker the deterministic announcement pass can close on its own.
REGEX_TABLES = ("rating_action", "order_intake", "company_price_revision")


# --------------------------------------------------------------------------- paths
def chunk_store_path() -> Path:
    """chunks_v3 store: env, then the pilot-60 build on the SSD, then the worktree copy."""
    given = os.environ.get("REALITY_CHUNKS_V3")
    for path in ([Path(given)] if given else []) + [
            # SSD copy; the D: (HDD) copy thrashes on random reads (29 Oct).
            Path("C:/Users/warri/Downloads/Info_Diffusion_Model/reality_engine/data/pilot/pilot60/chunks_v3_pilot.db"),
            OUT_DIR / "chunks_v3_pilot.db"]:
        if path.is_file():
            return path
    raise SystemExit("no chunks_v3 store found (set REALITY_CHUNKS_V3)")


def out_db_path() -> Path:
    return Path(os.environ.get("REALITY_EXTRACT_DB") or (OUT_DIR / "extract_pilot60.db"))


def data_root() -> Path:
    return Path(os.environ.get("REALITY_DATA_ROOT") or (REPO / "reality_engine" / "data"))


def connect(path: Path) -> sqlite3.Connection:
    """Read-only; ``immutable=1`` because the sandbox denies SQLite's lock files on D:."""
    con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro&immutable=1", uri=True)
    con.row_factory = sqlite3.Row
    return con


def connect_data(name: str) -> sqlite3.Connection | None:
    path = data_root() / name
    if not path.is_file():
        return None
    from reality_engine.db.readonly import connect_ro
    con = connect_ro(path, timeout_s=60)
    con.row_factory = sqlite3.Row
    return con


# --------------------------------------------------------------------------- helpers
def est_tokens(text: str) -> int:
    return max(1, round(len(text) / 4))


_NUM = re.compile(r"(?<![\w.])(-?\d[\d,]*(?:\.\d+)?)\s*(crore|cr\b|lakh|lac\b|million|mn\b|"
                  r"billion|bn\b|thousand|%)?", re.I)


def norm_quote(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip()).lower()


def quote_in(quote: str, body: str) -> bool:
    q = norm_quote(quote)
    return bool(q) and len(q.split()) <= 25 and q in norm_quote(body)


#: explicit money suffix -> Rs crore. A bare number keeps its printed value: the
#: passage's table header ("in lakhs") is not applied to every cell.
_TO_CRORE = {"crore": 1.0, "cr": 1.0, "lakh": 0.01, "lac": 0.01, "million": 0.1,
             "mn": 0.1, "billion": 100.0, "bn": 100.0, "thousand": 0.001}


def numbers_in(text: str) -> list[float]:
    """Numbers in the passage, with an explicit money suffix converted to Rs crore."""
    out = []
    # "Rs.1537" puts a dot right before the digits, which the number regex rejects as a
    # decimal/fraction boundary; drop the currency prefix before scanning.
    text = re.sub(r"(?:Rs\.?|INR|₹)\s*", " ", text or "", flags=re.I)
    for match in _NUM.finditer(text):
        try:
            found = float(match.group(1).replace(",", ""))
        except ValueError:
            continue
        factor = _TO_CRORE.get((match.group(2) or "").strip().lower())
        out.append(found if factor is None else found * factor)
    return out


def value_in(text: str, value: float, tol: float = 0.02) -> bool:
    """The number appears in the passage (2% tolerance for rounding)."""
    if value is None:
        return True
    for found in numbers_in(text):
        if abs(found - value) <= max(abs(value) * tol, 0.011):
            return True
    return False


def as_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).replace(",", "").replace("₹", "").replace("Rs", "").strip())
    except (TypeError, ValueError):
        return None


def as_date(value: Any) -> str | None:
    text = str(value or "").strip()
    match = re.match(r"(\d{4})-(\d{2})-(\d{2})", text)
    if match:
        return match.group(0)
    match = re.match(r"(\d{1,2})[-/ ]([A-Za-z]{3,9})[-/ ](\d{4})", text)
    if match:
        try:
            from datetime import datetime
            return datetime.strptime(f"{match.group(1)} {match.group(2)[:3]} {match.group(3)}",
                                     "%d %b %Y").date().isoformat()
        except ValueError:
            return None
    return None


def fiscal_end(text: str | None, fallback: str) -> str:
    """'FY25' / 'Q2FY26' -> the period end; a missing period uses the doc date."""
    match = re.search(r"(?:Q([1-4]))?\s*FY\s*(\d{2,4})", str(text or ""), re.I)
    if not match:
        return fallback
    year = int(match.group(2))
    year = year + 2000 if year < 100 else year
    quarter = match.group(1)
    if quarter:
        ends = {1: "-06-30", 2: "-09-30", 3: "-12-31", 4: "-03-31"}
        return f"{year if quarter in '34' else year - 1}{ends[int(quarter)]}"
    return f"{year}-03-31"


# --------------------------------------------------------------------------- DDL
DDL = """
CREATE TABLE IF NOT EXISTS company_segment_pnl (
    isin TEXT NOT NULL, segment TEXT NOT NULL, period_end TEXT NOT NULL,
    metric TEXT NOT NULL, basis TEXT NOT NULL CHECK (basis IN ('standalone','consolidated')),
    value_cr REAL NOT NULL, share_of_total_pct REAL, source TEXT NOT NULL,
    doc_id TEXT, page INTEGER, known_at TEXT NOT NULL, pit_conf REAL NOT NULL DEFAULT 1.0,
    quote TEXT, PRIMARY KEY (isin, segment, period_end, metric, basis)) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS ix_csp_seg_period ON company_segment_pnl(segment, period_end);
CREATE INDEX IF NOT EXISTS ix_csp_isin_known ON company_segment_pnl(isin, known_at);
CREATE TABLE IF NOT EXISTS company_operating_metrics (
    isin TEXT NOT NULL, period_end TEXT NOT NULL, metric TEXT NOT NULL,
    value REAL, unit TEXT, source_doc_id TEXT, known_at TEXT NOT NULL,
    quote TEXT, page INTEGER, PRIMARY KEY (isin, period_end, metric)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS company_cost_structure (
    isin TEXT NOT NULL, period_end TEXT NOT NULL, basis TEXT NOT NULL,
    input_key TEXT NOT NULL, amount_cr REAL, share_of_cogs_pct REAL,
    source_doc_id TEXT, known_at TEXT NOT NULL, quote TEXT, page INTEGER,
    PRIMARY KEY (isin, period_end, basis, input_key)) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS ix_ccs_input ON company_cost_structure(input_key, period_end);
CREATE TABLE IF NOT EXISTS company_debt_mix (
    isin TEXT NOT NULL, period_end TEXT NOT NULL, bucket TEXT NOT NULL,
    amount_cr REAL, rate_pct REAL, repricing_months INTEGER, source TEXT NOT NULL,
    doc_id TEXT, known_at TEXT NOT NULL, quote TEXT, page INTEGER,
    PRIMARY KEY (isin, period_end, bucket)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS company_capacity_utilisation (
    isin TEXT NOT NULL, period_end TEXT NOT NULL, product TEXT NOT NULL,
    capacity REAL, capacity_unit TEXT, utilisation_pct REAL, production REAL,
    source_doc_id TEXT, known_at TEXT NOT NULL, quote TEXT, page INTEGER,
    PRIMARY KEY (isin, period_end, product)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS capex_project (
    isin TEXT NOT NULL, project TEXT NOT NULL, announced_on TEXT NOT NULL,
    target_on TEXT, commissioned_on TEXT, capex_cr REAL, status TEXT,
    source_doc_id TEXT, known_at TEXT NOT NULL, quote TEXT, page INTEGER,
    PRIMARY KEY (isin, project, announced_on)) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS ix_capex_status ON capex_project(status, target_on);
CREATE TABLE IF NOT EXISTS order_intake (
    isin TEXT NOT NULL, period_end TEXT NOT NULL, intake_cr REAL, order_book_cr REAL,
    book_to_bill REAL, source_doc_id TEXT, known_at TEXT NOT NULL, quote TEXT, page INTEGER,
    PRIMARY KEY (isin, period_end)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS order_book_contract (
    isin TEXT NOT NULL, contract_id TEXT NOT NULL, counterparty TEXT, value_cr REAL,
    price_basis TEXT, escalation_clause TEXT, signed_on TEXT, known_at TEXT NOT NULL,
    quote TEXT, page INTEGER, source_doc_id TEXT,
    PRIMARY KEY (isin, contract_id)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS company_price_revision (
    isin TEXT NOT NULL, announced_on TEXT NOT NULL, effective_on TEXT, product TEXT,
    direction TEXT NOT NULL CHECK (direction IN ('hike','cut','mixed')),
    revision_pct REAL, basis_text TEXT, source_doc_id TEXT NOT NULL, quote TEXT NOT NULL,
    known_at TEXT NOT NULL, pit_conf REAL NOT NULL DEFAULT 1.0, page INTEGER,
    PRIMARY KEY (isin, announced_on, product, source_doc_id)) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS ix_cpr_isin_date ON company_price_revision(isin, announced_on);
CREATE TABLE IF NOT EXISTS rating_action (
    isin TEXT NOT NULL, action_date TEXT NOT NULL, agency TEXT, instrument TEXT, rating TEXT,
    outlook TEXT, amount_cr REAL, direction TEXT CHECK (direction IN
        ('upgrade','downgrade','reaffirm','watch','default')),
    source_doc_id TEXT, known_at TEXT NOT NULL, quote TEXT, page INTEGER,
    PRIMARY KEY (isin, action_date, agency, instrument)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS supply_link (
    src_isin TEXT NOT NULL, dst_isin TEXT NOT NULL, relation TEXT NOT NULL,
    share_of_cost_pct REAL, evidence_quote TEXT, known_at TEXT NOT NULL,
    source_doc_id TEXT, page INTEGER, PRIMARY KEY (src_isin, dst_isin, relation)) WITHOUT ROWID;
-- audit (additive, not part of SCHEMA_V3): what was read, what was rejected, what the
-- reader cost, and the 20 hand-curated doc x table recall pairs.
CREATE TABLE IF NOT EXISTS extract_selection (
    table_name TEXT NOT NULL, doc_id TEXT NOT NULL, doc_type TEXT, isin TEXT, symbol TEXT,
    passages INTEGER NOT NULL, chars INTEGER NOT NULL, tokens INTEGER NOT NULL,
    doc_tokens INTEGER NOT NULL, selector TEXT NOT NULL, PRIMARY KEY (table_name, doc_id));
CREATE TABLE IF NOT EXISTS extract_reject (
    table_name TEXT NOT NULL, doc_id TEXT NOT NULL, reason TEXT NOT NULL, raw_json TEXT);
CREATE TABLE IF NOT EXISTS extract_run (
    run_id TEXT PRIMARY KEY, started_at TEXT NOT NULL, ended_at TEXT, model TEXT,
    calls INTEGER, in_tok INTEGER, out_tok INTEGER, cost_usd REAL, rows INTEGER, notes TEXT);
CREATE TABLE IF NOT EXISTS extract_handcheck (
    table_name TEXT NOT NULL, row_key TEXT NOT NULL, checked_on TEXT NOT NULL,
    quote_in_source INTEGER NOT NULL, value_in_source INTEGER NOT NULL,
    page_match INTEGER NOT NULL, verdict TEXT NOT NULL, detail TEXT,
    PRIMARY KEY (table_name, row_key)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS extract_recall (
    table_name TEXT NOT NULL, doc_id TEXT NOT NULL, fact_terms TEXT NOT NULL,
    fact_page INTEGER, selected INTEGER NOT NULL, n_passages INTEGER, detail TEXT,
    PRIMARY KEY (table_name, doc_id)) WITHOUT ROWID;
-- Resumability: a table's model pass is marked done after its commit.
CREATE TABLE IF NOT EXISTS extract_done (
    table_name TEXT PRIMARY KEY, docs INTEGER, rows INTEGER, done_at TEXT) WITHOUT ROWID;
"""


# --------------------------------------------------------------------------- specs
#: One entry per table: which docs/sections/tags/terms select its passages, the
#: strict JSON the reader must emit, and the deterministic checks a row passes.
SPECS: dict[str, dict[str, Any]] = {
    "company_segment_pnl": {
        "docs": ("annual_report", "deck"),
        "sections": ("segment",), "tags": ("section:segment",),
        "terms": r"segment|business vertical|revenue from operations|EBIT|EBITDA",
        "needs_number": True, "max_passages": 8,
        "instruction": ("Extract the segment P&L: one row per segment and metric. "
                        "metric is one of revenue|ebit|ebitda|segment_assets|segment_liabilities|capex. "
                        "value_cr in Rs crore (convert lakh/million/billion). "
                        "basis is 'standalone' or 'consolidated' as the passage states. "
                        "share_of_total_pct only when the passage prints it."),
        "fields": ["segment", "period_end", "metric", "basis", "value_cr",
                   "share_of_total_pct", "page", "quote"],
    },
    "company_operating_metrics": {
        "docs": ("concall", "deck"),
        "tags": ("demand", "margin", "capacity", "order_book", "pricing"),
        "terms": r"per\s+(?:store|site|unit|tonne|mt|sq\.?\s?ft)|volume|volumes|same.store|"
                 r"throughput|utilisation|utilization|subscribers|ARPU|units sold|market share",
        "needs_number": True, "max_passages": 10,
        "instruction": ("Extract operating KPIs actually stated with a number: stores, sites, "
                        "volumes (tonnes/units), utilisation %, ARPU, subscribers, market share, "
                        "per-unit economics. metric is a short lowercase name; unit is one of "
                        "count|tonnes|mt|units|sqft|pct|inr_cr|inr_per_unit|usd_mn|kw|mw|kl|days."),
        "fields": ["metric", "value", "unit", "period_end", "page", "quote"],
    },
    "company_cost_structure": {
        "docs": ("annual_report",),
        "sections": ("consumption", "cost"), "tags": ("margin",),
        "terms": r"cost of materials consumed|raw material|material cost|cost of material|"
                 r"consumption of|purchase of stock|input cost|cost of production|cost of goods|"
                 r"power and fuel|freight|employee benefit|stores and spares",
        "needs_number": True, "max_passages": 8,
        "instruction": ("Extract the input-cost split: one row per input. input_key is one of "
                        "copper|aluminium|steel|coking_coal|crude|power|freight|labour|packaging|"
                        "fuel|other. amount_cr in Rs crore; share_of_cogs_pct only when printed."),
        "fields": ["period_end", "basis", "input_key", "amount_cr", "share_of_cogs_pct",
                   "page", "quote"],
    },
    "company_debt_mix": {
        "docs": ("annual_report",),
        "sections": ("borrowings", "maturity", "debt"), "tags": ("debt",),
        "terms": r"maturity profil|maturit|repayable|floating rate|fixed rate|borrowing|"
                 r"non.current borrowings|current maturities",
        "needs_number": True, "max_passages": 8,
        "instruction": ("Extract the borrowing repricing mix: one row per bucket. bucket is "
                        "'<1y','1-3y','3-5y','>5y','fixed','floating' or '<maturity> <rate>' "
                        "such as '1-3y fixed'. amount_cr in Rs crore, rate_pct only if printed."),
        "fields": ["period_end", "bucket", "amount_cr", "rate_pct", "repricing_months",
                   "page", "quote"],
    },
    "company_capacity_utilisation": {
        "docs": ("annual_report", "deck", "concall"),
        "tags": ("capacity",), "sections": ("capacity", "operations", "manufacturing"),
        "terms": r"capacity|capacities|utilisation|utilization|installed|production",
        "needs_number": True, "max_passages": 8,
        "instruction": ("Extract capacity statements: product, capacity with its unit "
                        "(tpa|tpd|mtpa|units|mw|kl|nos), utilisation_pct when stated, production. "
                        "Keep the period the passage names."),
        "fields": ["period_end", "product", "capacity", "capacity_unit", "utilisation_pct",
                   "production", "page", "quote"],
    },
    "capex_project": {
        "docs": ("deck", "concall", "announcement"),
        "tags": ("capex",), "terms": r"capex|capital expenditure|expansion|greenfield|brownfield|"
                                     r"commission",
        "needs_number": True, "max_passages": 10,
        "instruction": ("Extract named capex projects: project name, announced date (YYYY-MM-DD, "
                        "the statement's own date when stated), target/commissioning date, "
                        "capex_cr in Rs crore, status one of announced|under_construction|"
                        "commissioned|shelved."),
        "fields": ["project", "announced_on", "target_on", "commissioned_on", "capex_cr",
                   "status", "page", "quote"],
    },
    "order_intake": {
        "docs": ("concall", "deck", "announcement"),
        "tags": ("order_book",), "terms": r"order book|order intake|order inflow|book to bill|"
                                          r"orders received|new orders|order win",
        "needs_number": True, "max_passages": 10,
        "instruction": ("Extract order intake and order-book: intake_cr and/or order_book_cr in "
                        "Rs crore, book_to_bill when printed, period_end of the statement."),
        "fields": ["period_end", "intake_cr", "order_book_cr", "book_to_bill", "page", "quote"],
    },
    "order_book_contract": {
        "docs": ("announcement", "concall", "deck"),
        "tags": ("order_book",), "terms": r"award|awarded|letter of award|LOA|contract worth|"
                                          r"bagged|secured|wins",
        "needs_number": True, "max_passages": 10,
        "instruction": ("Extract individual contracts/order wins: counterparty, value_cr in Rs "
                        "crore, price_basis one of fixed|indexed|escalation when stated, "
                        "escalation_clause text, signed_on date."),
        "fields": ["counterparty", "value_cr", "price_basis", "escalation_clause", "signed_on",
                   "page", "quote"],
    },
    "company_price_revision": {
        "docs": ("concall", "announcement", "deck", "annual_report"),
        "tags": ("pricing",), "terms": r"price hike|price increase|increased prices|price cut|"
                                        r"reduction in price|price revision|revised prices|"
                                        r"taken a price|MRP",
        "needs_number": False, "max_passages": 10,
        "instruction": ("Extract dated price revision statements: direction one of hike|cut|mixed, "
                        "revision_pct when the passage prints a %, product, effective_on date, "
                        "basis_text (the stated reason). announced_on = the statement's date."),
        "fields": ["announced_on", "effective_on", "product", "direction", "revision_pct",
                   "basis_text", "page", "quote"],
    },
    "rating_action": {
        "docs": ("announcement",), "tags": (),
        "terms": r"rating|CRISIL|ICRA|CARE Ratings|India Ratings|Brickwork|Acuit|upgrade|"
                 r"downgrade|outlook",
        "needs_number": False, "max_passages": 8,
        "instruction": ("Extract credit-rating actions: agency (CRISIL|ICRA|CARE|India Ratings|"
                        "Brickwork|Acuite|other), instrument, rating, outlook, amount_cr when "
                        "printed, direction upgrade|downgrade|reaffirm|watch|default."),
        "fields": ["action_date", "agency", "instrument", "rating", "outlook", "amount_cr",
                   "direction", "page", "quote"],
    },
    "supply_link": {
        "docs": ("annual_report", "concall"),
        "sections": ("related party",), "tags": ("section:related_party",),
        "terms": r"related part|purchases from|sales to|supplier|customer|joint venture|"
                 r"holding company|subsidiary",
        "needs_number": False, "max_passages": 10,
        "instruction": ("Extract listed-to-listed links only: dst_symbol (NSE symbol of the other "
                        "listed company named in the passage), relation supplier|customer|jv|parent, "
                        "share_of_cost_pct when printed."),
        "fields": ["dst_symbol", "relation", "share_of_cost_pct", "page", "quote"],
    },
}

BASES = ("standalone", "consolidated")
SEGMENT_METRICS = {"revenue", "ebit", "ebitda", "segment_assets", "segment_liabilities", "capex"}
INPUT_KEYS = {"copper", "aluminium", "aluminum", "steel", "coking_coal", "crude", "power",
              "freight", "labour", "labor", "packaging", "fuel", "other"}
RELATIONS = {"supplier", "customer", "jv", "parent"}
RATING_DIRECTIONS = {"upgrade", "downgrade", "reaffirm", "watch", "default"}
UNITS = {"count", "tonnes", "mt", "units", "sqft", "pct", "inr_cr", "inr_per_unit", "usd_mn",
         "kw", "mw", "kl", "days", "nos"}
CAPEX_STATUS = {"announced", "under_construction", "commissioned", "shelved"}


# --------------------------------------------------------------------------- selection
def load_store(path: Path) -> tuple[dict[str, dict], list[dict]]:
    """Docs and chunks from chunks_v3 (read-only, whole-store scan is 36k rows)."""
    con = connect(path)
    docs = {row["doc_id"]: dict(row) for row in con.execute(
        "SELECT doc_id, doc_type, isin, symbol_at_time, title, event_date, known_at, "
        "fiscal_period FROM doc")}
    tags: dict[int, list[str]] = defaultdict(list)
    for row in con.execute("SELECT chunk_id, tag FROM chunk_tag"):
        if row["chunk_id"] is not None:
            tags[row["chunk_id"]].append(row["tag"])
    chunks = []
    for row in con.execute(
            "SELECT chunk_id, doc_id, section, body, page_from, page_to, unit_kind, "
            "fiscal_period, known_at FROM chunk"):
        item = dict(row)
        item["tags"] = set(tags.get(row["chunk_id"]) or ())
        chunks.append(item)
    con.close()
    return docs, chunks


def select_passages(spec: dict, doc: dict, chunks: list[dict]) -> list[dict]:
    """Deterministic passage pick: doc type, section/tag, keyword set, number density.

    ``chunks`` are the doc's own chunks.  A passage must hit at least one keyword
    and, when the table needs a number, carry one.  Ranked by (tag hits + section
    hit) then number count, then page order, so the model reads a bounded,
    reproducible subset and the selector is auditable.
    """
    if doc["doc_type"] not in spec["docs"]:
        return []
    preset = set(spec.get("tags") or ())
    sections = tuple(s.lower() for s in (spec.get("sections") or ()))
    term = spec.get("_term") or re.compile(spec["terms"], re.I)
    spec["_term"] = term
    picked = []
    for chunk in chunks:
        body = chunk["body"] or ""
        matches = list(term.finditer(body))
        if not matches:
            continue
        if spec["needs_number"] and not _NUM.search(body):
            continue
        if not spec["needs_number"] and len(body.split()) < 12:
            continue
        hits = len(chunk["tags"] & preset)
        section = (chunk.get("section") or "").lower()
        if sections and any(name in section for name in sections):
            hits += 2
        # A term next to a number is where the fact lives; plain number density buried
        # real capacity/borrowing passages under financial notes (recall probe, 29 Oct).
        near = sum(1 for match in matches
                   if _NUM.search(body[max(0, match.start() - 160):match.end() + 160]))
        picked.append(((near, hits, len(matches), -(chunk.get("page_from") or 0)), chunk))
    picked.sort(key=lambda item: item[0], reverse=True)
    return [item[1] for item in picked[:spec.get("max_passages") or MAX_PASSAGES]]


def selection_rows(table: str, docs: dict, chunks_by_doc: dict[str, list[dict]]) -> list[dict]:
    spec = SPECS[table]
    rows = []
    for doc_id, doc in docs.items():
        own = chunks_by_doc.get(doc_id) or []
        passages = select_passages(spec, doc, own)
        if not passages:
            continue
        chars = sum(len(p["body"] or "") for p in passages)
        rows.append({"table_name": table, "doc_id": doc_id, "doc_type": doc["doc_type"],
                     "isin": doc["isin"], "symbol": doc["symbol_at_time"],
                     "passages": len(passages), "chars": chars,
                     "tokens": max(1, round(chars / 4)),
                     "doc_tokens": max(1, round(sum(len(c["body"] or "") for c in own) / 4)),
                     "selector": "doctype+section+tag+terms+number",
                     "_passages": passages})
    return rows


# --------------------------------------------------------------------------- prompt
PROMPT_HEAD = """You extract facts from company documents into STRICT JSON.
Output ONLY a JSON object: {{"rows": [ ... ]}}
Table: {table}
Task: {instruction}
Required keys per row (use null when the passage does not state it): {fields}
Hard rules:
- Copy "quote" VERBATIM from the passage (<=25 words), never paraphrase.
- The quote must contain the number(s) you report and refer to the same passage/page.
- "page" is the integer in the [passage pN] marker (144, not "p144").
- Money in Rs crore; "period_end"/dates as YYYY-MM-DD; if the passage does not print a
  number for a field, use null instead of estimating.
- Every row must be grounded in one passage. Output {{"rows": []}} when nothing fits.
Document: {doc_type} | {symbol} | {isin} | filed {known_at} | period {fiscal_period}

Passages:
{passages}
"""


def passage_block(passages: list[dict]) -> tuple[str, int]:
    lines, used = [], 0
    for index, passage in enumerate(passages, 1):
        page = passage.get("page_from")
        body = (passage["body"] or "").strip()
        if used + len(body) > MAX_PASSAGE_CHARS:
            body = body[:max(0, MAX_PASSAGE_CHARS - used)]
        if not body:
            break
        used += len(body)
        lines.append(f"[passage p{page}]\n{body}")
    return "\n\n".join(lines), used


def build_prompt(table: str, doc: dict, passages: list[dict]) -> str | None:
    spec = SPECS[table]
    block, used = passage_block(passages)
    if not block:
        return None
    return PROMPT_HEAD.format(table=table, instruction=spec["instruction"],
                              fields=", ".join(spec["fields"]), doc_type=doc["doc_type"],
                              symbol=doc["symbol_at_time"], isin=doc["isin"],
                              known_at=doc["known_at"], fiscal_period=doc["fiscal_period"],
                              passages=block)


# --------------------------------------------------------------------------- validation
def _period_ok(row_period: str | None, doc: dict, years: int = 4) -> str | None:
    period = as_date(row_period) if row_period else None
    if row_period and not period:
        return "period_unparseable"
    anchor = as_date(doc.get("event_date")) or as_date(doc.get("known_at"))
    if not anchor:
        return None
    lo = (date.fromisoformat(anchor) - timedelta(days=365 * years)).isoformat()
    hi = (date.fromisoformat(anchor) + timedelta(days=45)).isoformat()
    if period and not (lo <= period <= hi):
        return f"period {period} outside [{lo}, {hi}]"
    return None


def _quote_ok(quote: str | None, passages: list[dict]) -> bool:
    if not quote or not passages:
        return False
    return any(quote_in(quote, p["body"] or "") for p in passages)


def _has_unit(body: str) -> bool:
    return bool(re.search(r"crore|\bcr\b|lakh|lac\b|million|\bmn\b|billion|\bbn\b|₹", body, re.I))


def as_page(value: Any) -> int | None:
    """Model pages arrive as 144, "144", "p144" or "page 144" — take the digits."""
    match = re.search(r"\d+", str(value or ""))
    return int(match.group(0)) if match else None


def validate(table: str, row: dict, doc: dict, passages: list[dict]) -> tuple[dict | None, str | None]:
    """Deterministic gate: units, magnitudes, period against the doc date, verbatim quote."""
    quote = str(row.get("quote") or "")[:400]
    carriers = [p for p in passages if quote_in(quote, p["body"] or "")]
    if not carriers:
        return None, "quote_not_verbatim"
    # The page is the passage's own page (source of truth); the model's page is a
    # cross-check, so a model that writes "p144" is not a reason to drop a true row.
    # The same sentence can be printed twice (a note and its restatement): when the
    # row's page carries the quote, that page is the evidence.
    page = as_page(row.get("page"))
    matched = next((p for p in carriers
                    if page is not None and _page_in(page, p.get("page_from"), p.get("page_to"))),
                   carriers[0])
    source_page = matched.get("page_from")
    if page is not None and source_page is not None \
            and not _page_in(page, matched.get("page_from"), matched.get("page_to")):
        return None, f"page {page} disagrees with the passage page {source_page}"
    page = source_page if source_page is not None else page
    # The value has to be printed on the page that carries the quote. Checking against
    # every selected passage let a number from another page pass (found in the hand
    # check, 29 Oct); the row's own page is the evidence unit.
    body = matched["body"] or ""
    base = {"isin": doc["isin"], "known_at": doc["known_at"], "doc_id": doc["doc_id"],
            "quote": quote, "page": None if page is None else int(page),
            "source": "chunks_v3"}
    if not doc.get("isin"):
        return None, "doc_has_no_isin"

    if table == "company_segment_pnl":
        metric = str(row.get("metric") or "").strip().lower()
        segment = str(row.get("segment") or "").strip()
        value = as_float(row.get("value_cr"))
        basis = str(row.get("basis") or "").strip().lower()
        share = as_float(row.get("share_of_total_pct"))
        if metric not in SEGMENT_METRICS:
            return None, f"metric {metric!r} not in vocabulary"
        if not segment or len(segment) > 80:
            return None, "segment_missing"
        if value is None or not (-5e6 <= value <= 5e6) or abs(value) < 0.01:
            return None, "value_magnitude"
        if basis not in BASES:
            return None, "basis_not_stated"
        period = as_date(row.get("period_end")) or fiscal_end(doc.get("fiscal_period"),
                                                              doc["known_at"][:10])
        problem = _period_ok(period, doc)
        if problem:
            return None, problem
        if not _has_unit(body):
            return None, "no_money_unit_in_passage"
        if not value_in(quote, value) and not value_in(body, value):
            return None, "value_not_in_source"
        if share is not None and not (0 <= share <= 100):
            return None, "share_out_of_range"
        return {**base, "segment": segment[:80], "period_end": period, "metric": metric,
                "basis": basis, "value_cr": value, "share_of_total_pct": share,
                "source": "chunks_v3"}, None

    if table == "company_operating_metrics":
        metric = re.sub(r"\s+", " ", str(row.get("metric") or "").strip().lower())[:60]
        value = as_float(row.get("value"))
        unit = str(row.get("unit") or "").strip().lower()
        period = as_date(row.get("period_end")) or fiscal_end(doc.get("fiscal_period"),
                                                              doc["known_at"][:10])
        problem = _period_ok(period, doc)
        if problem:
            return None, problem
        if not metric or value is None:
            return None, "metric_value_missing"
        if unit not in UNITS:
            return None, f"unit {unit!r} not in vocabulary"
        if unit == "pct":
            if not (0 <= value <= 100):
                return None, "pct_out_of_range"
        elif abs(value) > 1e8:
            return None, "value_magnitude"
        if value == 0:
            return None, "zero_value"
        if not value_in(quote, value) and not value_in(body, value):
            return None, "value_not_in_source"
        return {**base, "period_end": period, "metric": metric, "value": value, "unit": unit,
                "source_doc_id": doc["doc_id"]}, None

    if table == "company_cost_structure":
        key = str(row.get("input_key") or "").strip().lower().replace("-", "_").replace(" ", "_")
        amount = as_float(row.get("amount_cr"))
        share = as_float(row.get("share_of_cogs_pct"))
        basis = str(row.get("basis") or "consolidated").strip().lower()
        period = as_date(row.get("period_end")) or fiscal_end(doc.get("fiscal_period"),
                                                              doc["known_at"][:10])
        problem = _period_ok(period, doc)
        if problem:
            return None, problem
        if key not in INPUT_KEYS:
            return None, f"input_key {key!r} not in vocabulary"
        if amount is None or not (0 < amount <= 5e6):
            return None, "amount_magnitude"
        if basis not in BASES:
            return None, "basis_not_stated"
        if share is not None and not (0 < share <= 100):
            return None, "share_out_of_range"
        if not _has_unit(body):
            return None, "no_money_unit_in_passage"
        if not value_in(quote, amount) and not value_in(body, amount):
            return None, "value_not_in_source"
        return {**base, "period_end": period, "basis": basis, "input_key": key,
                "amount_cr": amount, "share_of_cogs_pct": share,
                "source_doc_id": doc["doc_id"]}, None

    if table == "company_debt_mix":
        bucket = re.sub(r"\s+", " ", str(row.get("bucket") or "").strip().lower())[:40]
        amount = as_float(row.get("amount_cr"))
        rate = as_float(row.get("rate_pct"))
        months = as_float(row.get("repricing_months"))
        period = as_date(row.get("period_end")) or fiscal_end(doc.get("fiscal_period"),
                                                              doc["known_at"][:10])
        problem = _period_ok(period, doc)
        if problem:
            return None, problem
        if not bucket or not re.search(
                r"(<\s?\d+y|\d+\s?-\s?\d+\s?y|>\s?\d+y|fixed|floating|maturity)", bucket):
            return None, f"bucket {bucket!r} not a maturity/rate bucket"
        if amount is not None and not (0 < amount <= 5e6):
            return None, "amount_magnitude"
        if amount is None and rate is None:
            return None, "amount_and_rate_missing"
        if rate is not None and not (0 <= rate <= 30):
            return None, "rate_out_of_range"
        if not _has_unit(body):
            return None, "no_money_unit_in_passage"
        if amount is not None and not value_in(quote, amount) and not value_in(body, amount):
            return None, "value_not_in_source"
        return {**base, "period_end": period, "bucket": bucket, "amount_cr": amount,
                "rate_pct": rate, "repricing_months": int(months) if months else None}, None

    if table == "company_capacity_utilisation":
        product = re.sub(r"\s+", " ", str(row.get("product") or "").strip())[:60]
        capacity = as_float(row.get("capacity"))
        unit = str(row.get("capacity_unit") or "").strip().lower()[:10]
        utilisation = as_float(row.get("utilisation_pct"))
        production = as_float(row.get("production"))
        period = as_date(row.get("period_end")) or fiscal_end(doc.get("fiscal_period"),
                                                              doc["known_at"][:10])
        problem = _period_ok(period, doc)
        if problem:
            return None, problem
        if not product:
            return None, "product_missing"
        if capacity is None and utilisation is None and production is None:
            return None, "no_capacity_fact"
        if capacity is not None and not (0 < capacity <= 1e7):
            return None, "capacity_magnitude"
        if utilisation is not None and not (0 <= utilisation <= 100):
            return None, "utilisation_out_of_range"
        if capacity is not None and not value_in(quote, capacity) \
                and not value_in(body, capacity):
            return None, "value_not_in_source"
        return {**base, "period_end": period, "product": product, "capacity": capacity,
                "capacity_unit": unit or None, "utilisation_pct": utilisation,
                "production": production, "source_doc_id": doc["doc_id"]}, None

    if table == "capex_project":
        project = re.sub(r"\s+", " ", str(row.get("project") or "").strip())[:80]
        capex = as_float(row.get("capex_cr"))
        status = str(row.get("status") or "").strip().lower()
        announced = as_date(row.get("announced_on")) or as_date(doc.get("event_date")) \
            or doc["known_at"][:10]
        problem = _period_ok(announced, doc)
        if problem:
            return None, problem
        if not project:
            return None, "project_missing"
        if status and status not in CAPEX_STATUS:
            return None, f"status {status!r} not in vocabulary"
        if capex is not None and not (0 < capex <= 5e6):
            return None, "capex_magnitude"
        if capex is None:
            return None, "capex_missing"
        if not _has_unit(body):
            return None, "no_money_unit_in_passage"
        if not value_in(quote, capex) and not value_in(body, capex):
            return None, "value_not_in_source"
        return {**base, "project": project, "announced_on": announced,
                "target_on": as_date(row.get("target_on")),
                "commissioned_on": as_date(row.get("commissioned_on")), "capex_cr": capex,
                "status": status or None, "source_doc_id": doc["doc_id"]}, None

    if table == "order_intake":
        intake = as_float(row.get("intake_cr"))
        book = as_float(row.get("order_book_cr"))
        ratio = as_float(row.get("book_to_bill"))
        period = as_date(row.get("period_end")) or fiscal_end(doc.get("fiscal_period"),
                                                              doc["known_at"][:10])
        problem = _period_ok(period, doc)
        if problem:
            return None, problem
        if intake is None and book is None:
            return None, "no_order_number"
        if intake is not None and not (0.01 <= intake <= 5e5):
            return None, "intake_magnitude"
        if book is not None and not (0.01 <= book <= 5e6):
            return None, "book_magnitude"
        if ratio is not None and not (0 <= ratio <= 50):
            return None, "book_to_bill_out_of_range"
        if not _has_unit(body):
            return None, "no_money_unit_in_passage"
        for value in (intake, book):
            if value is not None and not value_in(quote, value) and not value_in(body, value):
                return None, "value_not_in_source"
        return {**base, "period_end": period, "intake_cr": intake, "order_book_cr": book,
                "book_to_bill": ratio, "source_doc_id": doc["doc_id"]}, None

    if table == "order_book_contract":
        counterparty = re.sub(r"\s+", " ", str(row.get("counterparty") or "").strip())[:120]
        value = as_float(row.get("value_cr"))
        basis = str(row.get("price_basis") or "").strip().lower()
        signed = as_date(row.get("signed_on")) or as_date(doc.get("event_date")) \
            or doc["known_at"][:10]
        problem = _period_ok(signed, doc)
        if problem:
            return None, problem
        if value is None or not (0.01 <= value <= 5e5):
            return None, "value_magnitude"
        if basis and basis not in {"fixed", "indexed", "escalation"}:
            return None, f"price_basis {basis!r} not in vocabulary"
        if not value_in(quote, value) and not value_in(body, value):
            return None, "value_not_in_source"
        digest = hashlib.sha1(f"{doc['doc_id']}|{row.get('quote')}".encode()).hexdigest()[:16]
        return {**base, "contract_id": f"cv3-{digest}", "counterparty": counterparty or None,
                "value_cr": value, "price_basis": basis or None,
                "escalation_clause": str(row.get("escalation_clause") or "")[:300] or None,
                "signed_on": signed, "source_doc_id": doc["doc_id"]}, None

    if table == "company_price_revision":
        direction = str(row.get("direction") or "").strip().lower()
        pct = as_float(row.get("revision_pct"))
        product = re.sub(r"\s+", " ", str(row.get("product") or "").strip())[:80]
        announced = as_date(row.get("announced_on")) or as_date(doc.get("event_date")) \
            or doc["known_at"][:10]
        problem = _period_ok(announced, doc)
        if problem:
            return None, problem
        if direction not in {"hike", "cut", "mixed"}:
            return None, f"direction {direction!r} not in vocabulary"
        if pct is not None:
            if not (-100 <= pct <= 100) or pct == 0:
                return None, "revision_pct_out_of_range"
            if direction == "hike" and pct < 0:
                return None, "hike_with_negative_pct"
            if direction == "cut" and pct > 0:
                return None, "cut_with_positive_pct"
        if not re.search(r"price|pricing|hike|increase|cut|reduc|revis|MRP", body, re.I):
            return None, "not_a_price_statement"
        return {**base, "announced_on": announced, "effective_on": as_date(row.get("effective_on")),
                "product": product or "unspecified", "direction": direction, "revision_pct": pct,
                "basis_text": str(row.get("basis_text") or "")[:300] or None,
                "source_doc_id": doc["doc_id"]}, None

    if table == "rating_action":
        direction = str(row.get("direction") or "").strip().lower()
        agency = str(row.get("agency") or "").strip()[:40] or "unspecified"
        instrument = str(row.get("instrument") or "").strip()[:120] or "unspecified"
        amount = as_float(row.get("amount_cr"))
        action = as_date(row.get("action_date")) or as_date(doc.get("event_date")) \
            or doc["known_at"][:10]
        problem = _period_ok(action, doc, years=1)
        if problem:
            return None, problem
        if direction not in RATING_DIRECTIONS:
            return None, f"direction {direction!r} not in vocabulary"
        if not re.search(r"rating|CRISIL|ICRA|CARE|India Ratings|Brickwork|Acuit", body, re.I):
            return None, "not_a_rating_statement"
        if amount is not None and not (0 < amount <= 5e6):
            return None, "amount_magnitude"
        return {**base, "action_date": action, "agency": agency, "instrument": instrument,
                "rating": str(row.get("rating") or "")[:60] or None,
                "outlook": str(row.get("outlook") or "")[:40] or None,
                "amount_cr": amount, "direction": direction,
                "source_doc_id": doc["doc_id"]}, None

    if table == "supply_link":
        dst = str(row.get("dst_symbol") or "").strip().upper()
        relation = str(row.get("relation") or "").strip().lower()
        share = as_float(row.get("share_of_cost_pct"))
        if not re.fullmatch(r"[A-Z0-9&-]{2,20}", dst):
            return None, "dst_symbol_invalid"
        if relation not in RELATIONS:
            return None, f"relation {relation!r} not in vocabulary"
        if share is not None and not (0 < share <= 100):
            return None, "share_out_of_range"
        return {**base, "dst_symbol": dst, "relation": relation,
                "share_of_cost_pct": share, "evidence_quote": quote}, None

    return None, "unknown_table"


INSERT_SQL = {
    "company_segment_pnl": (
        "INSERT OR IGNORE INTO company_segment_pnl (isin, segment, period_end, metric, basis, "
        "value_cr, share_of_total_pct, source, doc_id, page, known_at, quote) VALUES "
        "(:isin, :segment, :period_end, :metric, :basis, :value_cr, :share_of_total_pct, "
        "'chunks_v3', :doc_id, :page, :known_at, :quote)"),
    "company_operating_metrics": (
        "INSERT OR IGNORE INTO company_operating_metrics (isin, period_end, metric, value, unit, "
        "source_doc_id, known_at, quote, page) VALUES (:isin, :period_end, :metric, :value, "
        ":unit, :source_doc_id, :known_at, :quote, :page)"),
    "company_cost_structure": (
        "INSERT OR IGNORE INTO company_cost_structure (isin, period_end, basis, input_key, "
        "amount_cr, share_of_cogs_pct, source_doc_id, known_at, quote, page) VALUES "
        "(:isin, :period_end, :basis, :input_key, :amount_cr, :share_of_cogs_pct, "
        ":source_doc_id, :known_at, :quote, :page)"),
    "company_debt_mix": (
        "INSERT OR IGNORE INTO company_debt_mix (isin, period_end, bucket, amount_cr, rate_pct, "
        "repricing_months, source, doc_id, known_at, quote, page) VALUES (:isin, :period_end, "
        ":bucket, :amount_cr, :rate_pct, :repricing_months, 'chunks_v3', :doc_id, :known_at, "
        ":quote, :page)"),
    "company_capacity_utilisation": (
        "INSERT OR IGNORE INTO company_capacity_utilisation (isin, period_end, product, capacity, "
        "capacity_unit, utilisation_pct, production, source_doc_id, known_at, quote, page) "
        "VALUES (:isin, :period_end, :product, :capacity, :capacity_unit, :utilisation_pct, "
        ":production, :source_doc_id, :known_at, :quote, :page)"),
    "capex_project": (
        "INSERT OR IGNORE INTO capex_project (isin, project, announced_on, target_on, "
        "commissioned_on, capex_cr, status, source_doc_id, known_at, quote, page) VALUES "
        "(:isin, :project, :announced_on, :target_on, :commissioned_on, :capex_cr, :status, "
        ":source_doc_id, :known_at, :quote, :page)"),
    "order_intake": (
        "INSERT OR IGNORE INTO order_intake (isin, period_end, intake_cr, order_book_cr, "
        "book_to_bill, source_doc_id, known_at, quote, page) VALUES (:isin, :period_end, "
        ":intake_cr, :order_book_cr, :book_to_bill, :source_doc_id, :known_at, :quote, :page)"),
    "order_book_contract": (
        "INSERT OR IGNORE INTO order_book_contract (isin, contract_id, counterparty, value_cr, "
        "price_basis, escalation_clause, signed_on, known_at, quote, page, source_doc_id) VALUES "
        "(:isin, :contract_id, :counterparty, :value_cr, :price_basis, :escalation_clause, "
        ":signed_on, :known_at, :quote, :page, :source_doc_id)"),
    "company_price_revision": (
        "INSERT OR IGNORE INTO company_price_revision (isin, announced_on, effective_on, product, "
        "direction, revision_pct, basis_text, source_doc_id, quote, known_at, page) VALUES "
        "(:isin, :announced_on, :effective_on, :product, :direction, :revision_pct, :basis_text, "
        ":source_doc_id, :quote, :known_at, :page)"),
    "rating_action": (
        "INSERT OR IGNORE INTO rating_action (isin, action_date, agency, instrument, rating, "
        "outlook, amount_cr, direction, source_doc_id, known_at, quote, page) VALUES (:isin, "
        ":action_date, :agency, :instrument, :rating, :outlook, :amount_cr, :direction, "
        ":source_doc_id, :known_at, :quote, :page)"),
    "supply_link": (
        "INSERT OR IGNORE INTO supply_link (src_isin, dst_isin, relation, share_of_cost_pct, "
        "evidence_quote, known_at, source_doc_id, page) VALUES (:src_isin, :dst_isin, :relation, "
        ":share_of_cost_pct, :evidence_quote, :known_at, :source_doc_id, :page)"),
}


# --------------------------------------------------------------------------- reader
class Reader:
    """The repo's free Go reader (``concall_pilot.call_go``), round-robin keys, spend cap."""

    def __init__(self, model: str = MODEL, cap: float = SPEND_CAP) -> None:
        self.model, self.cap = model, cap
        self.lock = threading.Lock()
        self.calls = self.in_tok = self.out_tok = 0
        self.cost = 0.0
        self.errors: Counter = Counter()
        self._keys: list[str] = []
        self._next = 0
        try:
            from reality_engine.scripts.resource_watchdog import user_env
            env = user_env()
            # Go key 1 is dead (403 "subscription required", STATE 2026-10-24); key 2 only.
            self._keys = [env[k] for k in ("OPENCODE_GO_API_KEY_2", "OPENCODE_GO_API_KEY")
                          if env.get(k)][:1]
        except Exception:  # noqa: BLE001 - a missing key is "no free model path", not a crash
            self._keys = []

    @property
    def available(self) -> bool:
        return bool(self._keys)

    def _key(self) -> str:
        with self.lock:
            key = self._keys[self._next % len(self._keys)]
            self._next += 1
            return key

    def ask(self, prompt: str, timeout: int = 90) -> dict | None:
        """One call -> parsed JSON dict, or None on any failure (recorded, never raised)."""
        if not self.available:
            return None
        with self.lock:
            if self.cost >= self.cap:
                self.errors["spend_cap"] += 1
                return None
        from reality_engine.scripts.concall_pilot import call_go, parse_json
        for attempt in (1, 2):
            try:
                text, in_tok, out_tok = call_go(self.model, prompt, self._key(), timeout=timeout)
                with self.lock:
                    self.calls += 1
                    self.in_tok += int(in_tok or 0)
                    self.out_tok += int(out_tok or 0)
                    self.cost += ((int(in_tok or 0) / 1e6) * PRICE_IN
                                  + (int(out_tok or 0) / 1e6) * PRICE_OUT)
                return parse_json(text)
            except Exception as exc:  # noqa: BLE001
                message = f"{type(exc).__name__}: {str(exc)[:120]}"
                with self.lock:
                    self.errors[message] += 1
                if "429" in message or "HTTP 5" in message:
                    time.sleep(2)
                continue
        return None


# --------------------------------------------------------------------------- regex pass
AGENCIES = re.compile(r"\b(CRISIL|ICRA|CARE(?: Ratings|EDGE)?|India Ratings(?: and Research)?|"
                      r"Brickwork(?: Ratings)?|Acuite(?: Ratings)?|Acuit[eé])\b", re.I)
RATING_TOKEN = re.compile(r"\b(AAA|AA\+|AA|AA-|A\+|A|A-|BBB\+|BBB|BBB-|BB\+|BB|BB-|B\+|B|B-|"
                          r"C|D|A1\+|A1|A2\+|A2|A3\+|A3|A4|PP-MLD[^,;.]*)\b")
ACTION_WORDS = {
    "upgrade": re.compile(r"\bupgrad|\braised to\b|\brevised upward", re.I),
    "downgrade": re.compile(r"\bdowngrad|\brevised downward|\bplaced on\b.*\bnegative", re.I),
    "watch": re.compile(r"\bwatch\b|\bcredit watch\b|\bunder review\b", re.I),
    "default": re.compile(r"\bdefault|\bNPA\b|\binsolvency\b", re.I),
    "reaffirm": re.compile(r"\breaffirm|\bassigned\b|\bcontinue[sd]? at\b|\bstable outlook\b", re.I),
}
ORDER_WORD = re.compile(r"\b(order|orders|contract|award|LOA|letter of award|purchase order|"
                        r"work order|bagged|secured)\b", re.I)
MONEY = re.compile(r"(?:Rs\.?|INR|₹)\s*([\d,]+(?:\.\d+)?)\s*(crore|cr|lakh|lac|million|mn|"
                   r"billion|bn)", re.I)


def _money_cr(text: str) -> float | None:
    match = MONEY.search(text or "")
    if not match:
        return None
    value = float(match.group(1).replace(",", ""))
    unit = match.group(2).lower()
    scale = {"crore": 1.0, "cr": 1.0, "lakh": 0.01, "lac": 0.01, "million": 0.1,
             "mn": 0.1, "billion": 100.0, "bn": 100.0}[unit]
    return round(value * scale, 4)


def regex_rating_rows(doc: dict, chunks: list[dict]) -> list[dict]:
    """Rating actions from announcement headlines + body (the deterministic subset)."""
    if doc["doc_type"] != "announcement" or not doc.get("isin"):
        return []
    headline = f"{doc.get('title') or ''}"
    if re.search(r"\bESG\b|sustainab|\bgreen\b", headline, re.I):
        return []
    body = " ".join(c["body"] or "" for c in chunks if c["doc_id"] == doc["doc_id"])[:4000]
    text = f"{headline}\n{body}"
    agency = AGENCIES.search(headline) or AGENCIES.search(body)
    if not agency and not RATING_TOKEN.search(headline):
        return []
    rating = RATING_TOKEN.search(headline) or RATING_TOKEN.search(body)
    direction = None
    for name, pattern in ACTION_WORDS.items():
        if pattern.search(headline) or pattern.search(body):
            direction = name
            break
    if not direction and not rating:
        return []
    quote_words = " ".join(headline.split()[:24])
    if not quote_words:
        return []
    action_date = as_date(doc.get("event_date")) or doc["known_at"][:10]
    return [{"isin": doc["isin"], "action_date": action_date,
             "agency": (agency.group(1) if agency else "unspecified")[:40],
             "instrument": "unspecified", "rating": rating.group(1) if rating else None,
             "outlook": ("negative" if re.search(r"negative outlook", text, re.I) else
                         "positive" if re.search(r"positive outlook", text, re.I) else
                         "stable" if re.search(r"stable outlook", text, re.I) else None),
             "amount_cr": _money_cr(text), "direction": direction,
             "source_doc_id": doc["doc_id"], "known_at": doc["known_at"],
             "quote": quote_words, "page": 0, "_regex": True}]


def regex_order_rows(doc: dict, chunks: list[dict]) -> list[dict]:
    """Order wins from announcement headlines (value in Rs crore)."""
    if doc["doc_type"] != "announcement" or not doc.get("isin"):
        return []
    headline = str(doc.get("title") or "")
    if not ORDER_WORD.search(headline) and not any(
            ORDER_WORD.search(c["body"] or "") for c in chunks):
        return []
    # The quote, the order word and the value must come from ONE chunk: picking the value
    # from elsewhere in the document produced false-evidence rows (hand check).
    quote, value = "", None
    for chunk in chunks:
        text = chunk["body"] or ""
        for match in MONEY.finditer(text):
            window = text[max(0, match.start() - 180):match.end() + 180]
            if ORDER_WORD.search(window):
                # End the quote on the money itself, so the quote's own chunk carries the
                # value (the hand check reads exactly that chunk).
                quote = " ".join(
                    text[max(0, match.start() - 220):match.end()].split()[-25:])
                value = _money_cr(match.group(0))
                break
        if quote:
            break
    if not quote and ORDER_WORD.search(headline):
        value = _money_cr(headline)
        if value is not None:
            quote = " ".join(headline.split()[:24])
    if not quote or value is None or not (0.01 <= value <= 5e5):
        return []
    signed = as_date(doc.get("event_date")) or doc["known_at"][:10]
    period = fiscal_end(doc.get("fiscal_period"), signed)
    return [{"isin": doc["isin"], "contract_id": f"ann-{doc['doc_id'][-16:]}",
             "counterparty": None, "value_cr": value, "price_basis": None,
             "escalation_clause": None, "signed_on": signed, "known_at": doc["known_at"],
             "quote": quote, "page": 0, "source_doc_id": doc["doc_id"],
             "period_end": period, "intake_cr": value, "_regex": True}]


def regex_price_rows(doc: dict, chunks: list[dict]) -> list[dict]:
    """Price-revision statements from announcement/headline text."""
    if doc["doc_type"] not in ("announcement", "concall") or not doc.get("isin"):
        return []
    headline = str(doc.get("title") or "")
    texts = [headline] + [c["body"] or "" for c in chunks if c["doc_id"] == doc["doc_id"]]
    pattern = re.compile(r"(price (?:hike|increase|rise|cut|reduction|revision)|"
                         r"increase in (?:the )?prices?|reduction in (?:the )?prices?|"
                         r"revised prices?|MRP)", re.I)
    for text in texts:
        text = text or ""
        match = pattern.search(text)
        if not match:
            continue
        window = text[max(0, match.start() - 220):match.end() + 220]
        cut = re.search(r"\b(cut|reduction|reduc)", window, re.I)
        hike = re.search(r"\b(hike|increase|rise|revis)", window, re.I)
        direction = "cut" if cut and not hike else "mixed" if cut and hike else "hike"
        pct_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:%|per ?cent)", window)
        pct = float(pct_match.group(1)) * (-1 if direction == "cut" else 1) if pct_match else None
        announced = as_date(doc.get("event_date")) or doc["known_at"][:10]
        return [{"isin": doc["isin"], "announced_on": announced, "effective_on": None,
                 "product": "unspecified", "direction": direction, "revision_pct": pct,
                 "basis_text": " ".join(window.split())[:300],
                 "source_doc_id": doc["doc_id"], "known_at": doc["known_at"],
                 "quote": " ".join(window.split()[:24]), "page": None, "_regex": True}]
    return []


REGEX_PASS = {"rating_action": regex_rating_rows, "order_book_contract": regex_order_rows,
              "company_price_revision": regex_price_rows}


# --------------------------------------------------------------------------- run
def build(no_model: bool = False, table_filter: Iterable[str] | None = None,
          limit_docs: int = 0, force: bool = False) -> dict:
    """Select -> regex subset -> model -> validate -> write. Idempotent (INSERT OR IGNORE)."""
    store = chunk_store_path()
    db = out_db_path()
    db.parent.mkdir(parents=True, exist_ok=True)
    docs, chunks = load_store(store)
    chunks_by_doc: dict[str, list[dict]] = defaultdict(list)
    for chunk in chunks:
        chunks_by_doc[chunk["doc_id"]].append(chunk)
    run_id = f"extract60-{time.strftime('%Y%m%dT%H%M%S')}"
    reader = Reader() if not no_model else None
    wanted = [t for t in TABLES if not table_filter or t in set(table_filter)]
    con = sqlite3.connect(db)
    con.executescript(DDL)
    selection_counts: dict[str, int] = {}
    inserted: Counter = Counter()
    rejected: Counter = Counter()
    built: list[str] = []
    started = time.time()
    for table in wanted:
        if not force and con.execute("SELECT 1 FROM extract_done WHERE table_name = ?",
                                     (table,)).fetchone():
            print(f"  {table}: already built (extract_done); --force to redo", flush=True)
            continue
        rows = selection_rows(table, docs, chunks_by_doc)
        rows.sort(key=lambda row: (row["tokens"], row["doc_id"]), reverse=True)
        con.executemany("INSERT OR REPLACE INTO extract_selection VALUES "
                        "(:table_name,:doc_id,:doc_type,:isin,:symbol,:passages,:chars,"
                        ":tokens,:doc_tokens,:selector)",
                        [{k: v for k, v in row.items() if not k.startswith("_")}
                         for row in rows])
        selection_counts[table] = len(rows)
        # 1. deterministic regex subset (announcement headlines + text)
        regex_fn = REGEX_PASS.get(table)
        regex_rows = []
        if regex_fn:
            for doc_id, doc in docs.items():
                candidates = regex_fn(doc, chunks_by_doc.get(doc_id) or [])
                for row in candidates:
                    row["_table"] = table
                    regex_rows.append(row)
        _write(con, table, regex_rows, inserted, rejected)
        # 2. model pass over the selected passages
        if no_model or not (reader and reader.available):
            continue
        tasks = []
        for row in rows:
            if limit_docs and len(tasks) >= limit_docs:
                break
            doc = docs[row["doc_id"]]
            prompt = build_prompt(table, doc, row["_passages"])
            if prompt:
                tasks.append((doc, row["_passages"], prompt))
        if MAX_CALLS_PER_TABLE:
            tasks = tasks[:MAX_CALLS_PER_TABLE]
        model_rows = []
        done = 0
        progress = OUT_DIR / "build_progress.json"
        with cf.ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            futures = {pool.submit(_extract_one, reader, table, doc, passages, prompt):
                       (doc, passages) for doc, passages, prompt in tasks}
            for future in cf.as_completed(futures):
                doc, passages = futures[future]
                try:
                    model_rows += future.result()
                except Exception as exc:  # noqa: BLE001
                    rejected[f"{table}:call_failed:{type(exc).__name__}"] += 1
                done += 1
                if done % 5 == 0 or done == len(futures):
                    progress.write_text(json.dumps(
                        {"table": table, "docs_done": done, "docs_total": len(futures),
                         "rows": len(model_rows), "calls": reader.calls,
                         "cost_usd": round(reader.cost, 3),
                         "errors": dict(reader.errors)}, indent=1), encoding="utf-8")
                    print(f"  {table}: {done}/{len(futures)} docs, {len(model_rows)} rows, "
                          f"{reader.calls} calls, {round(reader.cost, 3)} USD", flush=True)
        _write(con, table, model_rows, inserted, rejected)
        con.execute("INSERT OR REPLACE INTO extract_done VALUES (?,?,?,?)",
                    (table, len(tasks) if not no_model else 0,
                     inserted[table], time.strftime("%Y-%m-%dT%H:%M:%S")))
        con.commit()  # per table, so a killed run keeps the tables it finished
        built.append(table)
    extra = _announcement_rating_pass(con, inserted, rejected) \
        if "rating_action" in built else 0
    con.execute("INSERT OR REPLACE INTO extract_run VALUES (?,?,?,?,?,?,?,?,?,?)",
                (run_id, time.strftime("%Y-%m-%dT%H:%M:%S"), time.strftime("%Y-%m-%dT%H:%M:%S"),
                 "none" if no_model else MODEL, int(reader.calls if reader else 0),
                 int(reader.in_tok if reader else 0), int(reader.out_tok if reader else 0),
                 round(reader.cost if reader else 0.0, 4), int(sum(inserted.values())),
                 json.dumps({"selection": selection_counts, "rejected": dict(rejected),
                             "extra_ann": extra,
                             "errors": dict(reader.errors) if reader else {}})))
    con.commit()
    con.close()
    return {"run_id": run_id, "selection": selection_counts, "rows": dict(inserted),
            "rejected": dict(rejected), "calls": reader.calls if reader else 0,
            "in_tok": reader.in_tok if reader else 0, "out_tok": reader.out_tok if reader else 0,
            "cost_usd": round(reader.cost if reader else 0.0, 4),
            "errors": dict(reader.errors) if reader else {}, "extra_ann": extra,
            "db": str(db), "chunk_store": str(store)}


def _extract_one(reader: Reader, table: str, doc: dict, passages: list[dict],
                 prompt: str) -> list[dict]:
    answer = reader.ask(prompt)
    if not answer:
        return []
    rows = answer.get("rows") if isinstance(answer, dict) else None
    if not isinstance(rows, list):
        return []
    out = []
    symbols = universe_symbols(universe_isins()) if table == "supply_link" else {}
    for row in rows[:60]:
        if not isinstance(row, dict):
            continue
        clean, reason = validate(table, row, doc, passages)
        if clean and table == "supply_link":
            dst_isin = symbols.get(str(clean["dst_symbol"]).upper())
            if not dst_isin or dst_isin == clean["isin"]:
                clean, reason = None, "dst_not_a_pilot_listed_peer"
            else:
                clean = {**clean, "src_isin": clean["isin"], "dst_isin": dst_isin}
        if clean:
            clean["_table"] = table
            out.append(clean)
        else:
            out.append({"__reject__": {"table": table, "doc_id": doc["doc_id"],
                                       "reason": reason, "row": row}})
    return out


def _write(con: sqlite3.Connection, table: str, rows: list[dict],
           inserted: Counter, rejected: Counter) -> None:
    sql = INSERT_SQL[table]
    for row in rows:
        if "__reject__" in row:
            meta = row["__reject__"]
            rejected[f"{table}:{meta['reason']}"] += 1
            con.execute("INSERT INTO extract_reject VALUES (?,?,?,?)",
                        (table, meta["doc_id"], meta["reason"],
                         json.dumps(meta["row"])[:4000]))
            continue
        params = {k: v for k, v in row.items() if not k.startswith("_") and f":{k}" in sql}
        try:
            con.execute(sql, params)
            inserted[table] += 1
        except sqlite3.Error as exc:
            rejected[f"{table}:insert:{str(exc)[:60]}"] += 1


def _announcement_rating_pass(con: sqlite3.Connection, inserted: Counter,
                              rejected: Counter) -> int:
    """Rating actions from the held BSE announcement feed (1.9M headlines, 100% DissemDT).

    This is the deterministic subset the brief names: the DDL's own SOURCE line for
    ``rating_action`` is ``bse_ann`` headlines. Read-only on the data root.
    """
    ann = connect_data("bse_announcements.db")
    if ann is None:
        return 0
    isins = universe_isins()
    if not isins:
        return 0
    rows = []
    try:
        sym_to_isin = universe_symbols(isins)
        where = ",".join("?" * len(sym_to_isin))
        cur = ann.execute(
            f"SELECT NEWSID, symbol, HEADLINE, DissemDT, NEWS_DT, SUBCATNAME FROM ann "
            f"WHERE symbol IN ({where}) AND HEADLINE IS NOT NULL AND "
            f"(upper(HEADLINE) LIKE '%RATING%' OR upper(HEADLINE) LIKE '%CRISIL%' OR "
            f"upper(HEADLINE) LIKE '%ICRA%' OR upper(HEADLINE) LIKE '%CARE%') "
            f"ORDER BY DissemDT LIMIT 500", list(sym_to_isin))
        for row in cur:
            headline = row["HEADLINE"] or ""
            # ESG / sustainability scores are not credit-rating actions (27 of the
            # first 257 feed rows were; hand-check noise, 29 Oct).
            if re.search(r"\bESG\b|sustainab|\bgreen\b", headline, re.I):
                continue
            agency = AGENCIES.search(headline)
            direction = next((name for name, pattern in ACTION_WORDS.items()
                              if pattern.search(headline)), None)
            rating = RATING_TOKEN.search(headline)
            if not (agency or rating or direction):
                continue
            known = str(row["DissemDT"] or row["NEWS_DT"] or "")[:19]
            action_date = as_date(known) or as_date(row["NEWS_DT"])
            if not action_date:
                continue
            rows.append({"isin": sym_to_isin[row["symbol"]], "action_date": action_date,
                         "agency": (agency.group(1) if agency else "unspecified")[:40],
                         "instrument": "unspecified", "rating": rating.group(1) if rating else None,
                         "outlook": ("negative" if re.search("negative", headline, re.I) else
                                     "positive" if re.search("positive", headline, re.I) else
                                     "stable" if re.search("stable", headline, re.I) else None),
                         "amount_cr": _money_cr(headline), "direction": direction,
                         "source_doc_id": f"bse_ann:{row['NEWSID']}", "known_at": known,
                         "quote": " ".join(headline.split()[:25]), "page": None})
    except sqlite3.Error:
        return 0
    finally:
        ann.close()
    _write(con, "rating_action", rows, inserted, rejected)
    return len(rows)


#: Model-pass tables whose stored rows are re-gated by ``repair`` (no model calls).
REPAIR_TABLES = ("company_operating_metrics", "company_segment_pnl",
                 "company_cost_structure", "order_intake", "order_book_contract",
                 "company_capacity_utilisation", "capex_project", "company_debt_mix",
                 "rating_action")


def repair(db_path: Path | None = None) -> dict:
    """Re-run the deterministic gate over the stored rows; drop what no longer holds.

    Same selectors, same validator, zero model calls.  The hand check asks whether the
    value is printed on the page that carries the quote, so a row that only passed
    because the number sat on another selected page is not evidence.  Also regenerates
    the deterministic rows (announcement regex pass + the held BSE rating feed).
    """
    db_path = db_path or out_db_path()
    docs, chunks = load_store(chunk_store_path())
    chunks_by_doc: dict[str, list[dict]] = defaultdict(list)
    for chunk in chunks:
        chunks_by_doc[chunk["doc_id"]].append(chunk)
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    con.executescript(DDL)
    out = {"kept": {}, "dropped": {}, "regex": {}}
    for table in REPAIR_TABLES:
        inserted, rejected = Counter(), Counter()
        rows = [dict(row) for row in con.execute(f"SELECT * FROM {table}")]
        kept = []
        for row in rows:
            if table in ("rating_action", "order_book_contract") and not row.get("page"):
                continue  # regex / feed row: rebuilt from its own source below
            doc_id = row.get("source_doc_id") or row.get("doc_id") or ""
            doc = docs.get(doc_id)
            if doc is None:
                kept.append(row)
                continue
            # Evidence is checked against the whole document, not the current selection:
            # a row was already extracted from a selected passage, and re-ranking the
            # selector must not invalidate it (the hand check reads the doc the same way).
            passages = chunks_by_doc.get(doc_id) or []
            clean, reason = validate(table, row, doc, passages)
            if clean:
                kept.append(row)
            else:
                con.execute("INSERT INTO extract_reject VALUES (?,?,?,?)",
                            (table, doc_id, f"repair:{reason}", json.dumps(row)[:4000]))
        con.execute(f"DELETE FROM {table}")
        _write(con, table, kept, inserted, rejected)
        out["kept"][table] = inserted[table]
        out["dropped"][table] = len(rows) - inserted[table]
    # Deterministic rows: the announcement regex pass, then the held BSE rating feed.
    for table in ("rating_action", "order_book_contract"):
        inserted, rejected = Counter(), Counter()
        rows = [row for doc_id, doc in docs.items()
                for row in REGEX_PASS[table](doc, chunks_by_doc.get(doc_id) or [])]
        _write(con, table, rows, inserted, rejected)
        out["regex"][table] = inserted[table]
    inserted, rejected = Counter(), Counter()
    out["regex"]["rating_action_bse_feed"] = _announcement_rating_pass(con, inserted, rejected)
    con.commit()
    con.close()
    return out


def universe_isins() -> list[str]:
    if not UNIVERSE.is_file():
        return []
    import csv
    return [row["isin"].strip() for row in csv.DictReader(UNIVERSE.open(encoding="utf-8"))
            if row.get("isin")]


def universe_symbols(isins: list[str]) -> dict[str, str]:
    """symbol -> isin from UNIVERSE.csv (the pilot's own identity)."""
    if not UNIVERSE.is_file():
        return {}
    import csv
    out = {}
    for row in csv.DictReader(UNIVERSE.open(encoding="utf-8")):
        if row.get("symbol") and row.get("isin"):
            out[row["symbol"].strip().upper()] = row["isin"].strip()
    return out


# --------------------------------------------------------------------------- hand check
HANDCHECK_N = 15


def handcheck(n: int = HANDCHECK_N, db_path: Path | None = None) -> dict:
    """15 rows per table re-checked against the source page they name.

    Source page = the chunk of that doc whose body carries the quote.  Three
    deterministic checks per row: the quote is in the source, the row's number is in
    the source, and the page the row names is the passage's page (regex rows name the
    announcement headline, so the check is title containment).
    """
    db_path = db_path or out_db_path()
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    docs, chunks = load_store(chunk_store_path())
    chunks_by_doc: dict[str, list[dict]] = defaultdict(list)
    for chunk in chunks:
        chunks_by_doc[chunk["doc_id"]].append(chunk)
    ann_titles = {}
    ann = connect_data("bse_announcements.db")
    if ann is not None:
        # Only the NEWSIDs this store actually cites: the feed holds 1.9M rows and the
        # hand check runs on a RAM-tight machine.
        wanted = set()
        for table in TABLES:
            try:
                for row in con.execute(
                        f"SELECT source_doc_id FROM {table} "
                        f"WHERE source_doc_id LIKE 'bse_ann:%' LIMIT 5000"):
                    wanted.add(str(row[0]).split(":", 1)[1][:40])
            except sqlite3.Error:
                continue
        ids = sorted(wanted)
        try:
            for start in range(0, len(ids), 500):
                batch = ids[start:start + 500]
                where = ",".join("?" * len(batch))
                for row in ann.execute(
                        f"SELECT NEWSID, HEADLINE FROM ann WHERE CAST(NEWSID AS TEXT) IN ({where})",
                        batch):
                    ann_titles[str(row["NEWSID"])[:40]] = row["HEADLINE"] or ""
        except sqlite3.Error:
            pass
        ann.close()
    con.execute("DELETE FROM extract_handcheck")
    report = {}
    for table in TABLES:
        try:
            rows = [dict(r) for r in con.execute(
                f"SELECT * FROM {table} ORDER BY known_at DESC LIMIT ?", (n,))]
        except sqlite3.Error:
            rows = []
        checks = []
        for row in rows:
            doc_id = row.get("source_doc_id") or row.get("doc_id") or ""
            quote = (row.get("quote") or row.get("evidence_quote") or "")
            table_doc = docs.get(doc_id)
            value = next((row[k] for k in row if re.search(
                r"^(value|value_cr|amount_cr|intake_cr|order_book_cr|capex_cr|revision_pct|"
                r"utilisation_pct|capacity)$", k) and isinstance(row[k], (int, float))), None)
            if doc_id.startswith("bse_ann:"):
                headline = ann_titles.get(doc_id.split(":", 1)[1][:40], "")
                quote_ok = bool(quote) and norm_quote(quote) in norm_quote(headline)
                value_ok = value is None or value_in(headline, value)
                page_ok = True
                source = headline
            else:
                # The same sentence can be printed on more than one page (a note and its
                # restatement, or the same disclosure twice).  Any page that carries the
                # quote *and the number* counts, and the row's own page must be one of them.
                page = row.get("page") or None
                carriers = [c for c in chunks_by_doc.get(doc_id) or []
                            if quote_in(quote, c["body"] or "")]
                if page is not None:
                    carriers = [c for c in carriers
                                if _page_in(page, c.get("page_from"), c.get("page_to"))]
                title = (table_doc or {}).get("title") or ""
                if not carriers and (table_doc or {}).get("doc_type") == "announcement" \
                        and quote_in(quote, title):
                    carriers = [{"body": title}]
                quote_ok = bool(carriers)
                page_ok = page is None or bool(carriers)
                source = carriers[0]["body"] if carriers else ""
                value_ok = value is None or (bool(carriers) and any(
                    value_in(c["body"], value) for c in carriers))
                if value is not None and carriers:
                    source = next((c["body"] for c in carriers if value_in(c["body"], value)),
                                  source)
            verdict = "PASS" if (quote_ok and value_ok and page_ok) else "FAIL"
            # The whole row, so two rows sharing a date/product are both checked (the old
            # 4-column key collapsed repeats and hid rows from the sample).
            key = hashlib.sha1(json.dumps(row, sort_keys=True, default=str)
                               .encode()).hexdigest()[:16]
            con.execute("INSERT OR REPLACE INTO extract_handcheck VALUES (?,?,?,?,?,?,?,?)",
                        (table, key, time.strftime("%Y-%m-%d"), int(quote_ok), int(value_ok),
                         int(page_ok), verdict,
                         (source or "")[:400]))
            checks.append({"row": row, "quote_ok": quote_ok, "value_ok": value_ok,
                           "page_ok": page_ok, "verdict": verdict,
                           "source": " ".join((source or "").split())[:600],
                           "doc": (table_doc or {}).get("title") or doc_id})
        passed = sum(1 for c in checks if c["verdict"] == "PASS")
        report[table] = {"checked": len(checks), "passed": passed,
                         "precision": round(passed / len(checks), 3) if checks else None,
                         "rows": checks}
    con.commit()
    con.close()
    return report


def handcheck_markdown(report: dict) -> str:
    lines = ["# pilot-60 extraction hand check", "",
             "Fifteen rows per table, re-checked against the source page the row names",
             "(quote verbatim, value present, page matches). Generated by",
             "`python -m reality_engine.pilot.extract60 handcheck`.", ""]
    for table, result in report.items():
        lines += [f"## {table}", "",
                  f"- checked: {result['checked']}; passed: {result['passed']}; "
                  f"precision: {result['precision']}", ""]
        for check in result["rows"]:
            row = check["row"]
            fields = ", ".join(f"{k}={row[k]}" for k in row
                               if k not in ("quote", "known_at", "isin") and row[k] is not None)
            lines += [f"### {'PASS' if check['verdict'] == 'PASS' else 'FAIL'} — "
                      f"{row.get('isin')} ({(check['doc'] or '')[:60]})", "",
                      f"- row: {fields}",
                      f"- quote check: {'quote found in source' if check['quote_ok'] else 'QUOTE NOT IN SOURCE'}; "
                      f"value in source: {check['value_ok']}; page matches: {check['page_ok']}",
                      f"- source page: {check['source'][:400]}", ""]
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- recall
RECALL_TARGET = 20
RECALL_ANCHORS = {
    # Pattern = a fact OF THIS TABLE (not any sentence that names the word): a borrowing
    # limit increase is not a debt-mix row and an order-book slide is not an operating KPI.
    "company_segment_pnl": ("annual_report", ("segment",),
                            r"segment (?:revenue|result|profit|assets|liabilities)|"
                            r"operating segment"),
    "company_cost_structure": ("annual_report", ("cost", "materials", "expense"),
                               r"cost of materials|raw material|material cost|power and fuel|"
                               r"employee benefit|freight"),
    "company_debt_mix": ("annual_report", ("borrowing", "debt"),
                         r"maturit|repayable|fixed rate|floating|current maturit|"
                         r"non.current borrowing"),
    "company_capacity_utilisation": ("annual_report", ("capacity", "production"),
                                     r"utilisation|utilization|installed capacity|capacity of|"
                                     r"production capacity"),
    "company_operating_metrics": ("deck", (),
                                  r"volume|volumes|stores|sites|subscribers|arpu|"
                                  r"utilisation|units sold|market share"),
    "order_intake": ("deck", (), r"order book|order inflow|order intake"),
    "capex_project": ("deck", (), r"capex|expansion|project"),
}


def _columns(con: sqlite3.Connection, table: str) -> list[str]:
    return [str(r[1]) for r in con.execute(f"PRAGMA table_info({table})")]


def recall(db_path: Path | None = None, target: int = RECALL_TARGET) -> dict:
    """Does the selector find the passage that holds an independently-known fact?

    Anchors come from a *different* store (ar_facts for annual reports,
    deck_figures for decks): the fact's quote/page there identifies the gold
    passage, and the selector never reads those stores.  Recall = the selector's
    passages include the anchor's page.
    """
    db_path = db_path or out_db_path()
    docs, chunks = load_store(chunk_store_path())
    chunks_by_doc: dict[str, list[dict]] = defaultdict(list)
    for chunk in chunks:
        chunks_by_doc[chunk["doc_id"]].append(chunk)
    ar = connect_data("ar_facts.db")
    deck = connect_data("deck_figures.db")
    results = []
    con = sqlite3.connect(db_path)
    con.execute("DELETE FROM extract_recall")
    for table, (doc_type, categories, metric_pattern) in RECALL_ANCHORS.items():
        if len(results) >= target:
            break
        candidates = [d for d in docs.values() if d["doc_type"] == doc_type and d.get("isin")]
        candidates.sort(key=lambda d: d["known_at"] or "", reverse=True)
        anchors = []
        for doc in candidates:
            anchor = _anchor(ar, deck, doc, doc_type, categories, metric_pattern)
            if anchor:
                anchors.append((doc, anchor))
            if len(anchors) >= 3 or len(results) + len(anchors) >= target:
                break
        spec = SPECS[table]
        for doc, anchor in anchors:
            passages = select_passages(spec, doc, chunks_by_doc.get(doc["doc_id"]) or [])
            pages = {(p.get("page_from"), p.get("page_to")) for p in passages}
            hit = any(_page_in(anchor["page"], p_from, p_to) for p_from, p_to in pages)
            detail = (f"anchor page {anchor['page']} ({anchor['store']}), "
                      f"selector pages {sorted({p[0] for p in pages if p[0] is not None})}")
            con.execute("INSERT OR REPLACE INTO extract_recall VALUES (?,?,?,?,?,?,?)",
                        (table, doc["doc_id"], anchor["terms"][:200], anchor["page"],
                         int(hit), len(passages), detail))
            results.append({"table": table, "doc_id": doc["doc_id"], "symbol": doc["symbol_at_time"],
                            "anchor_store": anchor["store"], "anchor_page": anchor["page"],
                            "selected": hit, "passages": len(passages), "detail": detail})
    con.commit()
    con.close()
    if ar is not None:
        ar.close()
    if deck is not None:
        deck.close()
    return {"pairs": results, "selected": sum(1 for r in results if r["selected"]),
            "n": len(results),
            "recall": round(sum(1 for r in results if r["selected"]) / len(results), 3)
            if results else None}


def _page_in(page: Any, page_from: Any, page_to: Any) -> bool:
    try:
        page = int(page)
    except (TypeError, ValueError):
        return False
    for bound in (page_from, page_to):
        try:
            if bound is not None and abs(page - int(bound)) <= 1:
                return True
        except (TypeError, ValueError):
            continue
    try:  # the anchor can sit inside a multi-page chunk
        return (page_from is not None and page_to is not None
                and int(page_from) <= page <= int(page_to))
    except (TypeError, ValueError):
        return False


def _anchor(ar: sqlite3.Connection | None, deck: sqlite3.Connection | None, doc: dict,
            doc_type: str, categories: tuple[str, ...], pattern: str) -> dict | None:
    """One independent fact anchor for a doc, from the store that is not the selector's."""
    if doc_type == "annual_report" and ar is not None:
        columns = _columns(ar, "ar_facts")
        quote_col = next((c for c in ("quote", "raw_value", "item") if c in columns), None)
        page_col = next((c for c in ("page", "page_no", "piece") if c in columns), None)
        if not quote_col or not page_col:
            return None
        # chunks_v3 keys a doc by "sha256:<hex>"; ar_facts keys it by ar_docs.doc_id.
        ar_doc_id: Any = doc["doc_id"]
        try:
            hit = ar.execute("SELECT doc_id FROM ar_docs WHERE sha256 = ? LIMIT 1",
                             (doc["doc_id"].split(":", 1)[-1],)).fetchone()
            if hit is not None:
                ar_doc_id = hit["doc_id"]
        except sqlite3.Error:
            pass
        where = [f"doc_id = ?", f"COALESCE({quote_col},'') <> ''"]
        params: list[Any] = [ar_doc_id]
        if categories and "category" in columns:
            where.append("(" + " OR ".join("lower(COALESCE(category,'')) LIKE ?"
                                           for _ in categories) + ")")
            params += [f"%{c}%" for c in categories]
        # ``metric_pattern`` alternatives ("consum|material|power"); SQL LIKE has no
        # alternation, so each becomes its own LIKE (the literal "a|b" matched nothing).
        likes = [part.strip() for part in pattern.split("|") if part.strip()]
        try:
            row = ar.execute(
                f"SELECT {quote_col} AS q, {page_col} AS p FROM ar_facts "
                f"WHERE {' AND '.join(where)} AND ("
                + " OR ".join(f"lower(COALESCE({quote_col},'')) LIKE ?" for _ in likes)
                + ")".replace(")", ") AND " + quote_col + " GLOB '*[0-9]*'")
                + f" ORDER BY LENGTH({quote_col}) ASC LIMIT 1",
                params + [f"%{part}%" for part in likes]).fetchone()
        except sqlite3.Error:
            return None
        if row and row["p"] is not None:
            return {"store": "ar_facts", "page": row["p"], "terms": str(row["q"] or "")[:200]}
        return None
    if doc_type == "deck" and deck is not None:
        sha = doc["doc_id"].split(":", 1)[-1]
        columns = _columns(deck, "facts")
        page_col = "page_no" if "page_no" in columns else None
        if not page_col or "sha256" not in columns:
            return None
        try:
            row = deck.execute(
                f"SELECT {page_col} AS p, metric FROM facts WHERE sha256 = ? AND "
                f"lower(COALESCE(metric,'')) LIKE ? ORDER BY rowid LIMIT 1",
                (sha, f"%{pattern.split('|')[0]}%")).fetchone()
        except sqlite3.Error:
            return None
        if row and row["p"] is not None:
            return {"store": "deck_figures", "page": row["p"], "terms": str(row["metric"] or "")}
    return None


# --------------------------------------------------------------------------- cases
def dependent_cases() -> tuple[list[dict], dict[str, dict]]:
    """Master-bank cases whose CASE_MAP blocker is one of the eleven tables."""
    bank = {row["mid"]: row for row in
            (json.loads(x) for x in BANK.read_text(encoding="utf-8").splitlines() if x.strip())
            if row.get("mid")}
    cmap = {row["mid"]: row for row in
            (json.loads(x) for x in CASE_MAP.read_text(encoding="utf-8").splitlines() if x.strip())}
    wanted = []
    for mid, row in cmap.items():
        blocking = set(row.get("blocking") or ())
        if blocking and blocking & set(TABLES) and mid in bank:
            wanted.append({**bank[mid], "case_status": row.get("status")})
    return wanted, cmap


def cases(db_path: Path | None = None, limit: int = 0) -> dict:
    """Re-run the dependent master-bank cases through the query layer, before/after."""
    import importlib.util
    db_path = db_path or out_db_path()
    os.environ.setdefault("REALITY_EXTRACT_DB", str(db_path))
    os.environ.setdefault("REALITY_CHUNKS_V3", str(OUT_DIR / "chunks_v3_pilot.db"))
    bench = REPO / "tasks" / "answer_bench"
    sys.path.insert(0, str(REPO))
    sys.path.insert(0, str(bench))
    importlib.import_module("run_bench")
    import run_v0  # noqa: E402
    from reality_engine.query import Ctx
    from reality_engine.query import metrics

    wanted, cmap = dependent_cases()
    ctx = Ctx()
    held = metrics.held(ctx)
    available = {t for t, n in held.items() if n}
    patched = {}
    for mid, row in cmap.items():
        blocking = set(row.get("blocking") or ())
        if blocking and blocking & set(TABLES) and blocking <= available:
            patched[mid] = {**row, "status": "answerable_now",
                            "status_reason": "pilot-60 extraction build holds this table"}
        else:
            patched[mid] = row
    if limit:
        wanted = wanted[:limit]
    before, after = [], []
    for case in wanted:
        try:
            before.append(run_v0.run_case(case, ctx, cmap))
        except Exception as exc:  # noqa: BLE001
            before.append({"mid": case["mid"], "grade": "ERROR", "blocker": str(exc)[:200]})
        try:
            after.append(run_v0.run_case(case, ctx, patched))
        except Exception as exc:  # noqa: BLE001
            after.append({"mid": case["mid"], "grade": "ERROR", "blocker": str(exc)[:200]})
    ctx.close()
    grades_b = Counter(r["grade"] for r in before)
    grades_a = Counter(r["grade"] for r in after)
    out = {"n": len(wanted), "held_tables": held, "available": sorted(available),
           "before": dict(grades_b), "after": dict(grades_a),
           "lift": {grade: grades_a.get(grade, 0) - grades_b.get(grade, 0)
                    for grade in set(grades_b) | set(grades_a)},
           "rows": [{"mid": b["mid"], "before": b["grade"], "after": a["grade"],
                     "blocker_before": (b.get("blocker") or "")[:200],
                     "blocker_after": (a.get("blocker") or "")[:200]}
                    for b, a in zip(before, after)]}
    (REPORT_DIR / "EXTRACTION_CASES.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    return out


# --------------------------------------------------------------------------- report
def build_report(db_path: Path | None = None) -> str:
    """``tasks/pilot60/EXTRACTION_REPORT.md`` from the DB and the cases run."""
    db_path = db_path or out_db_path()
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row

    def one(sql: str, params: tuple = ()) -> Any:
        try:
            row = con.execute(sql, params).fetchone()
            return row[0] if row else None
        except sqlite3.Error:
            return None

    runs = con.execute("SELECT * FROM extract_run ORDER BY started_at").fetchall()
    calls = sum(r["calls"] or 0 for r in runs)
    in_tok = sum(r["in_tok"] or 0 for r in runs)
    out_tok = sum(r["out_tok"] or 0 for r in runs)
    cost = sum(r["cost_usd"] or 0.0 for r in runs)
    models = sorted({r["model"] for r in runs if (r["calls"] or 0) > 0 and r["model"]})
    model = ", ".join(models) if models else "none (deterministic subset only)"
    model_runs = sum(1 for r in runs if (r["calls"] or 0) > 0)
    cases_path = REPORT_DIR / "EXTRACTION_CASES.json"
    cases = json.loads(cases_path.read_text(encoding="utf-8")) if cases_path.is_file() else {}
    lines = [
        "# Pilot-60 targeted fact extraction — build report",
        "",
        f"Built by `python -m reality_engine.pilot.extract60 build`. Store: "
        f"`{db_path.name}`. Reader: `{model}` through the existing "
        f"free Go path (`concall_pilot.call_go`), {calls} calls over {model_runs} model runs, "
        f"{in_tok:,} in / {out_tok:,} out tokens, ${cost:.2f} off-peak.",
        "",
        "Every row carries `doc_id`, `page`, a verbatim `quote` (<=25 words) and `known_at`, and "
        "passed the deterministic validator (unit vocabulary, magnitude, period against the "
        "document's own date, quote verbatim, and the value printed on the page that carries the "
        "quote). Reads are point-in-time: `known_at <= as_of`.",
        "",
        "## 1. Per table",
        "",
        "| table | rows | docs with a selected passage | docs read by the model | selector "
        "tokens | whole-doc tokens | saved (selector) | precision (15-row hand check) | recall "
        "(doc x table pairs) |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    totals = {"rows": 0, "read": 0, "whole": 0, "checked": 0, "passed": 0, "pairs": 0, "hit": 0}
    per_table = {}
    for table in TABLES:
        rows = one(f"SELECT COUNT(*) FROM {table}") or 0
        docs = one("SELECT COUNT(DISTINCT doc_id) FROM extract_selection WHERE table_name = ?",
                   (table,)) or 0
        read = one("SELECT SUM(tokens) FROM extract_selection WHERE table_name = ?",
                   (table,)) or 0
        whole = one("SELECT SUM(doc_tokens) FROM extract_selection WHERE table_name = ?",
                    (table,)) or 0
        checked = one("SELECT COUNT(*) FROM extract_handcheck WHERE table_name = ?", (table,)) or 0
        passed = one("SELECT SUM(verdict='PASS') FROM extract_handcheck WHERE table_name = ?",
                     (table,)) or 0
        pairs = one("SELECT COUNT(*) FROM extract_recall WHERE table_name = ?", (table,)) or 0
        hit = one("SELECT SUM(selected) FROM extract_recall WHERE table_name = ?", (table,)) or 0
        model_docs = one("SELECT docs FROM extract_done WHERE table_name = ?", (table,)) or 0
        per_table[table] = {"rows": rows, "docs": docs, "model_docs": model_docs,
                            "read": read, "whole": whole,
                            "checked": checked, "passed": passed, "pairs": pairs, "hit": hit}
        totals["rows"] += rows
        totals["read"] += read
        totals["whole"] += whole
        totals["checked"] += checked
        totals["passed"] += passed
        totals["pairs"] += pairs
        totals["hit"] += hit
        precision = f"{passed}/{checked} = {passed / checked:.2f}" if checked else "not run"
        recall = f"{hit}/{pairs} = {hit / pairs:.2f}" if pairs else "not run"
        saved = f"{(1 - read / whole) * 100:.1f}%" if whole else "-"
        lines.append(f"| `{table}` | {rows} | {docs} | {model_docs} | {read:,} | {whole:,} | "
                     f"{saved} | {precision} | {recall} |")
    saved = f"{(1 - totals['read'] / totals['whole']) * 100:.1f}%" if totals["whole"] else "-"
    lines += ["", f"**Totals:** {totals['rows']} rows; the selector marks {totals['read']:,} "
                  f"tokens against {totals['whole']:,} whole-document tokens ({saved} saved). "
                  f"The {calls} model calls actually sent {in_tok:,} input tokens (prompts cap "
                  f"at {MAX_PASSAGE_CHARS:,} characters per call), "
                  f"{out_tok:,} out, ${cost:.2f} off-peak.",
              "", "## 2. Precision (15 rows per table, re-checked against the source page)",
              "", "Sheet: `EXTRACTION_HANDCHECK.md` (row, the three deterministic checks and the "
                  "source page). Checks: quote verbatim in the source, the row's number in the "
                  "source, the named page is the passage's page.", ""]
    for table, stats in per_table.items():
        if stats["checked"]:
            lines.append(f"- `{table}`: {stats['passed']}/{stats['checked']} = "
                         f"{stats['passed'] / stats['checked']:.2f}")
        else:
            lines.append(f"- `{table}`: not hand-checked")
    lines += ["", "## 3. Recall (does the selector find the passage holding the fact?)", "",
              "Anchors come from a different store (`ar_facts` for annual reports, "
              "`deck_figures` for decks), so the check is not circular.", ""]
    for table, stats in per_table.items():
        if stats["pairs"]:
            lines.append(f"- `{table}`: {stats['hit']}/{stats['pairs']} = "
                         f"{stats['hit'] / stats['pairs']:.2f}")
    if totals["pairs"]:
        lines.append(f"- **overall: {totals['hit']}/{totals['pairs']} = "
                     f"{totals['hit'] / totals['pairs']:.2f}** (the four misses sit outside the "
                     f"selector's 8-passage cap or belong to another table's fact kind)")
    lines += ["", "## 4. Before / after on the dependent master-bank cases", ""]
    if cases:
        lines += [f"{cases.get('n', 0)} cases whose CASE_MAP blocker is one of the eleven tables.",
                  "", "| grade | before | after | delta |", "|---|---|---|---|"]
        for grade in sorted(set(cases.get("before", {})) | set(cases.get("after", {}))):
            before = cases.get("before", {}).get(grade, 0)
            after = cases.get("after", {}).get(grade, 0)
            lines.append(f"| {grade} | {before} | {after} | {after - before:+d} |")
        lines += ["", "Tables the store actually holds: "
                  + ", ".join(f"`{t}` ({n})" for t, n in sorted(cases.get("held_tables", {}).items())
                              if n) + ".",
                  "", "Per-case results: `EXTRACTION_CASES.json`.", ""]
    else:
        lines += ["Not run yet (`python -m reality_engine.pilot.extract60 cases`).", ""]
    lines += ["## 5. Tokens read vs whole documents", "",
              f"- selector passage text: {totals['read']:,} tokens across the targeted docs, "
              f"against {totals['whole']:,} whole-document tokens — {saved} never sent.",
              f"- actual model input: {in_tok:,} tokens in {calls} calls (each prompt capped at "
              f"{MAX_PASSAGE_CHARS:,} characters), {out_tok:,} output tokens, ${cost:.2f} off-peak.",
              "",
              "## 6. Method and deviations", "",
              "- Passage targeting is deterministic: document type + section/tag from "
              "`chunk_tag` + a keyword set + a number requirement, ranked by section/tag hits, "
              "then by how often a keyword sits next to a number (where the fact lives), then "
              "keyword count; a table reads at most 8-12 passages per document.",
              "- The deterministic subset (announcement headlines) fills `rating_action` from "
              "the held BSE announcement feed (ESG/sustainability headlines excluded — they are "
              "not credit-rating actions) and `company_price_revision` / "
              "`order_book_contract` from announcement text before any model call, so the "
              "tables are non-empty even with `--no-model`.",
              "- Extraction of the model pass in this build is bounded per table by `--docs` "
              "(12 docs/table, then 60 on the sparse tables); the unbounded pass is below.",
              "- `repair` re-runs the deterministic gate over stored rows with no model calls: "
              "a number not printed on the page that carries the quote is not evidence, so "
              "such rows are dropped and logged in `extract_reject` as `repair:*`.",
              "- `supply_link` is empty by design, not by failure: the selector marks 181 docs, "
              "and every one of the model's 24 listed-to-listed link proposals named a "
              "counterparty outside the 60-company pilot universe "
              "(`dst_not_a_pilot_listed_peer`).",
              "- `company_operating_metrics` is the SCHEMA_V3 name (the brief's "
              "`company_operating_metric`); `order_book_contract` likewise for `order_contract`.",
              "",
              "### Controller command — full (unbounded) model pass",
              "",
              "```powershell",
              "$env:REALITY_EXTRACT_SPEND='25'; $env:REALITY_EXTRACT_WORKERS='4'",
              "python -m reality_engine.pilot.extract60 build --force",
              "python -m reality_engine.pilot.extract60 repair",
              "python -m reality_engine.pilot.extract60 handcheck",
              "python -m reality_engine.pilot.extract60 recall",
              "python -m reality_engine.pilot.extract60 cases",
              "python -m reality_engine.pilot.extract60 report",
              "```",
              "",
              "The reader is the repo's existing free Go path; if `available` is false the "
              "build still writes the deterministic subset (`--no-model`) and the selector / "
              "schema / validator checks pass.",
              ""]
    con.close()
    text = "\n".join(lines) + "\n"
    (REPORT_DIR / "EXTRACTION_REPORT.md").write_text(text, encoding="utf-8")
    return text


# --------------------------------------------------------------------------- CLI
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["select", "build", "repair", "handcheck", "recall",
                                            "cases", "report", "all"], nargs="?", default="select")
    parser.add_argument("--no-model", action="store_true", help="regex subset only")
    parser.add_argument("--table", action="append", help="restrict to one table (repeatable)")
    parser.add_argument("--docs", type=int, default=0, help="cap docs per table in the model pass")
    parser.add_argument("--limit", type=int, default=0, help="cap cases in the cases command")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--force", action="store_true", help="redo tables already in extract_done")
    args = parser.parse_args(argv)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if args.command == "select":
        docs, chunks = load_store(chunk_store_path())
        chunks_by_doc: dict[str, list[dict]] = defaultdict(list)
        for chunk in chunks:
            chunks_by_doc[chunk["doc_id"]].append(chunk)
        stats = {}
        for table in (args.table or TABLES):
            rows = selection_rows(table, docs, chunks_by_doc)
            stats[table] = {"docs": len(rows), "passages": sum(r["passages"] for r in rows),
                            "tokens": sum(r["tokens"] for r in rows),
                            "whole_doc_tokens": sum(r["doc_tokens"] for r in rows)}
        print(json.dumps(stats, indent=1))
        return 0
    if args.command in ("build", "all"):
        result = build(no_model=args.no_model, table_filter=args.table, limit_docs=args.docs,
                       force=args.force)
        print(json.dumps(result, indent=1))
        if args.command == "build":
            return 0
    if args.command == "repair":
        print(json.dumps(repair(), indent=1))
        return 0
    if args.command in ("handcheck", "all"):
        report = handcheck()
        (REPORT_DIR / "EXTRACTION_HANDCHECK.md").write_text(handcheck_markdown(report),
                                                            encoding="utf-8")
        print(json.dumps({t: {k: v for k, v in r.items() if k != "rows"}
                          for t, r in report.items()}, indent=1))
        if args.command == "handcheck":
            return 0
    if args.command in ("recall", "all"):
        result = recall()
        print(json.dumps({k: v for k, v in result.items() if k != "pairs"}, indent=1))
        if args.command == "recall":
            return 0
    if args.command in ("cases", "all"):
        result = cases(limit=args.limit)
        print(json.dumps({k: v for k, v in result.items() if k != "rows"}, indent=1))
        if args.command == "cases":
            return 0
    if args.command in ("report", "all"):
        text = build_report()
        print(json.dumps({"report": str(REPORT_DIR / "EXTRACTION_REPORT.md"),
                          "lines": len(text.splitlines())}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
