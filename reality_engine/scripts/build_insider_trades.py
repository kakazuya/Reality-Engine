"""Normalized insider trades (insider_trades_v2) from the raw feeds already on disk.

Why: ``insider_trades`` has 0 rows — its only filler is NSEClient.fetch_insider_trades(),
whose NSE endpoint now returns nothing — while load_market_raw.py already stored the
real disclosures in three raw tables.  This script turns them into one point-in-time
table.  The legacy table is left untouched (and empty); readers move to v2.

Sources (read-only):
  nse_legacy    mkt_nse_insider                   2019-01 .. 2026-05-02 (disseminated)
                one row per NSE PIT disclosure (Buy/Sell/Pledge/Pledge Revoke/Pledge Invoke).
  nse_pit_xbrl  mkt_nse_pit_filings + mkt_nse_pit_xbrl_facts  from 2026-05-03
                NSE moved to XBRL filings; the XML is already parsed into (xml_file,
                context_id, concept, value, unit) facts by parse_pit_xml().
  bse           mkt_bse_insider                   2019-01 .. 2022-06
                BSE monthly CSV rows kept as raw_json with BSE's own column labels.

NSE PIT XBRL concept mapping (one row per <context>; NSE's spellings are kept, including
the "Acquistion" typo).  The context named ``MainI`` is filing-level, every other context
is one disclosed transaction:
  NameOfThePerson                                                       -> person_name
  CategoryOfPerson                                                      -> person_category
  SecuritiesAcquiredOrDisposedTransactionType                            -> transaction_type
  ModeOfAcquisitionOrDisposal                                           -> mode
  TypeOfInstrument                                                      -> security_type
  SecuritiesAcquiredOrDisposedNumberOfSecurity                          -> qty
  SecuritiesAcquiredOrDisposedValueOfSecurity                           -> value_inr (INR)
  SecuritiesHeldPriorToAcquisitionOrDisposalPercentageOfShareholding    -> before_pct (x100)
  SecuritiesHeldPostAcquistionOrDisposalPercentageOfShareholding        -> after_pct (x100)
  DateOfAllotmentAdviceOrAcquisitionOfSharesOrSaleOfSharesSpecifyFromDate -> trade_from
  DateOfAllotmentAdviceOrAcquisitionOfSharesOrSaleOfSharesSpecifyToDate   -> trade_to
  DateOfIntimationToCompany                                             -> intimation_date
  ExchangeOnWhichTheTradeWasExecuted                                    -> not stored
  (MainI) Symbol / ISINCode                                             -> symbol / isin
  (MainI) RevisedFilling                                                -> is_revision
The percentages are XBRL "pure" fractions (0..1, verified 0.0..1.0 in the live DB) while
the legacy NSE feed publishes percent (e.g. 38.28), so they are multiplied by 100.
Derivative contexts (only 6 filings, 56 contexts) carry TypeOfContract, NumberOfUnits /
NotionalValue and BuyNumberOfUnits and are mapped as one BUY row with mode
DERIVATIVE_CONTRACT; they have no holding percentages.

Normalization:
  transaction_type  BUY / SELL / PLEDGE / REVOKE / OTHER
                    (Acquisition|Buy -> BUY, Disposal|Sell -> SELL, Creation|Pledge -> PLEDGE,
                     Release|Pledge Revoke -> REVOKE, Invocation|Pledge Invoke -> OTHER)
  mode              MARKET_PURCHASE / MARKET_SALE / ESOP / OFF_MARKET / GIFT / INTER_SE_TRANSFER
                    / PLEDGE_CREATION / PLEDGE_RELEASE / PLEDGE_INVOCATION / PREFERENTIAL_OFFER
                    / CONVERSION / SCHEME / RIGHTS / BONUS / ALLOTMENT / BUYBACK / BLOCK_DEAL
                    / INHERITANCE / DERIVATIVE_CONTRACT / OTHER, else the uppercased raw mode.
                    BSE publishes only Mode="Market" (all 153,904 rows), so BSE rows take
                    mode=MARKET; BSE also has no intimation date and no dissemination timestamp.

ISIN: NSE legacy has only a symbol, so it is resolved through symbol_isin_history valid on
the trade date (nearest window when a symbol has a gap), then security_master / a
non-synthetic master_companies row.  XBRL filings carry ISINCode (used when it is a real
ISIN; ZZZ999Z99999 placeholders fall back to history); BSE rows carry the target ISIN.
BSE symbol is filled from security_master.nse_symbol by ISIN.

Point in time: ``known_at`` is the exchange dissemination timestamp as stored (IST,
'YYYY-MM-DD HH:MM:SS'); BSE rows have no such stamp and keep known_at NULL.  Readers that
pass an as_of_date exclude NULL/known_at-after-as_of rows, so a BSE-only row is never
visible to a backtest that cannot prove when it was published.

Dedupe across NSE and BSE (the same trade is often filed on both): matching key is
  (isin, normalized person, qty, transaction side) + BSE trade date inside the NSE
  trade_from..trade_to window.
Pairing is one-to-one inside each key, so two genuine same-size trades by the same person
on the same day are not collapsed.  The NSE row is kept (it has known_at/intimation) and
the BSE row is dropped with also_on='bse' recorded.  Name normalization is uppercase,
punctuation -> space, collapse spaces, drop MR/MRS/MS/DR/SHRI/SMT prefixes.  BSE's person
column is the promoter's full legal name while NSE's acquirer_name is often a trust/filing
entity ("Gautam S. Adani & Rajesh S Adani (on behalf of ...)"), so only ~2.5% of BSE rows
match; the unmatched BSE rows are kept as their own trades, never dropped.

Revisions: NSE marks a re-filed disclosure with submission_type='Revision' and/or
RevisedFilling=true, but prev_app_id points at app ids that were never archived (0 of 9
resolve), so supersede prefers the latest earlier filing for the same symbol whose trade
window overlaps the revision and shares a (normalized person, side); when the revision
moved the dates it falls back to the latest filing sharing person+side.  The original's
matching rows get is_superseded=1 and the revision rows get is_revision=1 +
supersedes=<original source_key(s)> (comma separated).  Superseded rows stay in the table
for audit; repository.get_recent_insider_trades() filters is_superseded=0.

Idempotent: insider_trades_v2 is dropped and rebuilt inside one transaction when not
--dry-run.  --dry-run reads the DB read-only and prints the same coverage report.

Usage:
    python -m reality_engine.scripts.build_insider_trades --dry-run --db <path>
    python -m reality_engine.scripts.build_insider_trades --db <path>
"""

import argparse
import json
import re
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from reality_engine import config as cfg

V2_TABLE = "insider_trades_v2"
MIN_PLAUSIBLE_DATE = "2000-01-01"

DDL = """
CREATE TABLE insider_trades_v2 (
    source TEXT NOT NULL,
    source_key TEXT PRIMARY KEY,
    symbol TEXT,
    isin TEXT,
    company TEXT,
    person_name TEXT,
    person_category TEXT,
    transaction_type TEXT NOT NULL,
    mode TEXT,
    security_type TEXT,
    qty REAL,
    value_inr REAL,
    before_pct REAL,
    after_pct REAL,
    trade_from TEXT,
    trade_to TEXT,
    intimation_date TEXT,
    trade_from_raw TEXT,
    trade_to_raw TEXT,
    intimation_date_raw TEXT,
    date_flag TEXT,               -- implausible_trade_date / implausible_intimation_date, comma separated
    known_at TEXT,
    is_revision INTEGER NOT NULL DEFAULT 0,
    supersedes TEXT,
    is_superseded INTEGER NOT NULL DEFAULT 0,
    also_on TEXT
)"""

INDEXES = (
    "CREATE INDEX idx_itv2_isin ON insider_trades_v2(isin, trade_from)",
    "CREATE INDEX idx_itv2_symbol ON insider_trades_v2(symbol, trade_from)",
    "CREATE INDEX idx_itv2_known ON insider_trades_v2(known_at)",
)

ROW_COLS = (
    "source", "source_key", "symbol", "isin", "company", "person_name", "person_category",
    "transaction_type", "mode", "security_type", "qty", "value_inr", "before_pct", "after_pct",
    "trade_from", "trade_to", "intimation_date", "trade_from_raw", "trade_to_raw",
    "intimation_date_raw", "date_flag", "known_at", "is_revision", "supersedes",
    "is_superseded", "also_on",
)

TXN_MAP = {
    "buy": "BUY", "acquisition": "BUY",
    "sell": "SELL", "disposal": "SELL",
    "pledge": "PLEDGE", "creation": "PLEDGE",
    "pledge revoke": "REVOKE", "release": "REVOKE",
    "pledge invoke": "OTHER", "invocation": "OTHER",
}

MODE_MAP = {
    "market purchase": "MARKET_PURCHASE", "market sale": "MARKET_SALE", "market": "MARKET",
    "esop": "ESOP", "esos": "ESOP",
    "off market": "OFF_MARKET", "gift": "GIFT", "inter-se-transfer": "INTER_SE_TRANSFER",
    "pledge creation": "PLEDGE_CREATION",
    "revokation of pledge": "PLEDGE_RELEASE", "revocation of pledge": "PLEDGE_RELEASE",
    "pledge release": "PLEDGE_RELEASE", "invocation of pledge": "PLEDGE_INVOCATION",
    "preferential offer": "PREFERENTIAL_OFFER", "conversion of security": "CONVERSION",
    "scheme of amalgamation/merger/demerger/arrangement": "SCHEME",
    "public right": "RIGHTS", "bonus": "BONUS", "allotment": "ALLOTMENT", "buy back": "BUYBACK",
    "block deal": "BLOCK_DEAL", "inheritance": "INHERITANCE", "others": "OTHER",
    "derivative contract": "DERIVATIVE_CONTRACT",
}

PIT_FROM = "DateOfAllotmentAdviceOrAcquisitionOfSharesOrSaleOfSharesSpecifyFromDate"
PIT_TO = "DateOfAllotmentAdviceOrAcquisitionOfSharesOrSaleOfSharesSpecifyToDate"
PIT_INTIM = "DateOfIntimationToCompany"
PIT_QTY = "SecuritiesAcquiredOrDisposedNumberOfSecurity"
PIT_VALUE = "SecuritiesAcquiredOrDisposedValueOfSecurity"
PIT_TXN = "SecuritiesAcquiredOrDisposedTransactionType"
PIT_MODE = "ModeOfAcquisitionOrDisposal"
PIT_BEFORE_PCT = "SecuritiesHeldPriorToAcquisitionOrDisposalPercentageOfShareholding"
PIT_AFTER_PCT = "SecuritiesHeldPostAcquistionOrDisposalPercentageOfShareholding"

BSE_COMPANY = "Name of the Target Company"
BSE_ISIN = "ISIN of Target Company"
BSE_PERSON = "Name(s) of the promoter and/or persons in promoter group"
BSE_QTY = "Shares acquired / disposed(No. of shares)"
BSE_VALUE = "Shares acquired / disposed(Value of Security)"
BSE_TXN = "Shares acquired / disposed(Transaction type (Acquisition/ Disposal / Pledge / Revocation / Invocation ))"
BSE_BEFORE_PCT = "Shares held prior to acquisition / disposal(% of total equity share capital of TC)"
BSE_AFTER_PCT = "Shares held after the acquisition/ disposal(% of total equity share capital of TC)"
BSE_DATE = "Date of credit/debit of shares in depository account/ transfer of physical shares"
BSE_MODE = "Mode of Acquisition/Disposal"
BSE_PROMOTER = "Promoter / Non-Promoter"

TITLE_RE = re.compile(r"^(?:MR|MRS|MS|DR|SHRI|SMT|M S)\s+")
ISO_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
ISO_TS_RE = re.compile(r"(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2})(?::(\d{2}))?")
ISIN_RE = re.compile(r"IN[A-Z0-9]{10}")
SEAM_MONTHS = tuple(f"2026-{m:02d}" for m in range(3, 11))


# ----------------------------------------------------------------------------
# small parsers
# ----------------------------------------------------------------------------
def clean(value):
    """Text field -> stripped string, empty placeholders -> None."""
    if value is None:
        return None
    text = str(value).strip()
    return None if text in ("", "-", "NA", "N/A", "Nil", "NIL", "nan", "None") else text


def num(value):
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    if text in ("", "-", "NA", "Nil", "nan"):
        return None
    try:
        return float(text)
    except ValueError:
        return None


def iso_date(value):
    """Strict 'YYYY-MM-DD' out of a date or timestamp string."""
    text = (value or "").strip()
    if not ISO_DATE_RE.match(text):
        return None
    day = text[:10]
    try:
        datetime.strptime(day, "%Y-%m-%d")
    except ValueError:
        return None
    return day


def iso_ts(value):
    """'2019-01-31 23:13' -> '2019-01-31 23:13:00' (IST, stored as published)."""
    text = (value or "").strip()
    match = ISO_TS_RE.match(text)
    if not match:
        day = iso_date(text)
        return f"{day} 00:00:00" if day else None
    return f"{match.group(1)} {match.group(2)}:{match.group(3) or '00'}"


def bse_date(value):
    """BSE publishes both '1/31/2019 12:00:00 AM' and '28-06-2019 00:00:00'."""
    text = (value or "").strip().split(" ")[0]
    for fmt in ("%m/%d/%Y", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return None


def norm_person(value):
    """Entity-resolution key for a person/trust name (same rule as the H02 cards)."""
    text = re.sub(r"[^A-Z0-9 ]+", " ", (value or "").upper())
    text = re.sub(r"\s+", " ", text).strip()
    return TITLE_RE.sub("", text).strip()


def tx_type(value):
    return TXN_MAP.get((value or "").strip().lower(), "OTHER")


def mode_norm(value):
    raw = clean(value)
    if raw is None:
        return None
    return MODE_MAP.get(raw.lower(), re.sub(r"\s+", "_", raw.upper()))


def pct(value, scale=1.0):
    got = num(value)
    return None if got is None else round(got * scale, 6)


def _plausible_upper(known_at, today=None):
    """known_at date + 1 day; today when the row has no dissemination stamp."""
    day = iso_date((known_at or "")[:10])
    if day:
        return (datetime.strptime(day, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
    return today or datetime.now().strftime("%Y-%m-%d")


def date_is_implausible(day, known_at, today=None):
    """NSE publishes typo dates (1922, 3034); do not guess a correction."""
    if not day:
        return False
    if day < MIN_PLAUSIBLE_DATE:
        return True
    return day > _plausible_upper(known_at, today)


DATE_FIELDS = (
    ("trade_from", "trade_from_raw", "implausible_trade_date"),
    ("trade_to", "trade_to_raw", "implausible_trade_date"),
    ("intimation_date", "intimation_date_raw", "implausible_intimation_date"),
)


def apply_date_flags(rows, today=None, audit=None):
    """NULL implausible dates, keep the published text in *_raw, flag the row.

    A date is implausible before 2000-01-01 or after known_at + 1 day (today
    when known_at is NULL).  The raw text is always retained so a later pass can
    audit the source without a rebuild guessing what the typo meant.
    """
    counts = Counter()
    for row in rows:
        flags = []
        for field, raw_field, token in DATE_FIELDS:
            if row.get(raw_field) is None:
                row[raw_field] = row.get(field)
            if date_is_implausible(row.get(field), row.get("known_at"), today):
                row[field] = None
                if token not in flags:
                    flags.append(token)
        row["date_flag"] = ",".join(flags) or None
        for token in flags:
            counts[token] += 1
        if flags:
            counts["rows_with_implausible_date"] += 1
    if audit is not None:
        for token in ("implausible_trade_date", "implausible_intimation_date",
                      "rows_with_implausible_date"):
            audit[token] = counts[token]
    return counts


# ----------------------------------------------------------------------------
# ISIN / symbol resolution
# ----------------------------------------------------------------------------
class IsinMap:
    """Dated NSE symbol->ISIN windows plus static symbol lookups."""

    def __init__(self, conn):
        self.windows = defaultdict(list)
        for symbol, isin, first, last in conn.execute(
                "SELECT symbol, isin, first_date, last_date FROM symbol_isin_history "
                "WHERE exchange='NSE' ORDER BY symbol, first_date"):
            self.windows[symbol].append((first or "", last or "", isin))
        self.static = {}
        self.symbol_by_isin = {}
        for isin, symbol in conn.execute("SELECT isin, nse_symbol FROM security_master"):
            self.symbol_by_isin[isin] = symbol
            if symbol:
                self.static.setdefault(symbol, isin)
        for isin, symbol in conn.execute("SELECT isin, nse_symbol FROM master_companies WHERE nse_symbol IS NOT NULL"):
            if isin and not str(isin).startswith("INE_AUTO"):
                self.static.setdefault(symbol, isin)

    def for_nse(self, symbol, day):
        wins = self.windows.get(symbol)
        if not wins:
            return self.static.get(symbol)
        if day:
            starts = [a for a, _, _ in wins]
            i = 0
            for j, start in enumerate(starts):
                if start <= day:
                    i = j
                else:
                    break
            if wins[i][0] <= day <= wins[i][1]:
                return wins[i][2]
            return wins[max(i, 0)][2]  # nearest window: before first / in a gap / after last
        return wins[-1][2]

    def symbol(self, isin):
        return self.symbol_by_isin.get(isin)


def valid_isin(value):
    text = clean(value)
    return text if text and ISIN_RE.fullmatch(text) else None


# ----------------------------------------------------------------------------
# source loaders -> list of dicts in ROW_COLS
# ----------------------------------------------------------------------------
def load_legacy(conn, imap, audit):
    rows = []
    for (did, symbol, company, acquirer, category, sec_type, txn, acq_mode, qty, value,
         buy_qty, buy_value, sell_qty, sell_value, before_pct, after_pct, acq_from, acq_to,
         intim, disseminated) in conn.execute(
            "SELECT did, symbol, company, acquirer_name, person_category, security_type, "
            "transaction_type, acquisition_mode, securities_qty, securities_value, buy_qty, "
            "buy_value, sell_qty, sell_value, before_pct, after_pct, acq_from, acq_to, "
            "intimation_date, disseminated_at FROM mkt_nse_insider"):
        trade_from = iso_date(acq_from)
        known_at = iso_ts(disseminated)
        side = tx_type(txn)
        qty_value = num(qty)
        if qty_value is None:
            qty_value = num(buy_qty) if side == "BUY" else num(sell_qty)
            if qty_value is None:
                qty_value = num(buy_qty) if num(buy_qty) is not None else num(sell_qty)
        value_inr = num(value)
        if value_inr is None:
            value_inr = num(buy_value) if side == "BUY" else num(sell_value)
            if value_inr is None:
                value_inr = num(buy_value) if num(buy_value) is not None else num(sell_value)
        isin = imap.for_nse(symbol, trade_from or iso_date(disseminated) or iso_date(intim))
        if not isin:
            audit["unresolved_isin"] += 1
        rows.append({
            "source": "nse_legacy",
            "source_key": f"nse_legacy:{did}",
            "symbol": clean(symbol),
            "isin": isin,
            "company": clean(company),
            "person_name": clean(acquirer),
            "person_category": clean(category),
            "transaction_type": side,
            "mode": mode_norm(acq_mode),
            "security_type": clean(sec_type),
            "qty": qty_value,
            "value_inr": value_inr,
            "before_pct": pct(before_pct),
            "after_pct": pct(after_pct),
            "trade_from": trade_from,
            "trade_to": iso_date(acq_to),
            "intimation_date": iso_date(intim),
            "trade_from_raw": clean(acq_from),
            "trade_to_raw": clean(acq_to),
            "intimation_date_raw": clean(intim),
            "date_flag": None,
            "known_at": known_at,
            "is_revision": 0,
            "supersedes": None,
            "is_superseded": 0,
            "also_on": None,
        })
    return rows


def load_pit(conn, imap, audit):
    """Group PIT XBRL facts by xml_file + context; attach the filing for symbol/known_at."""
    filings = [dict(zip(
        ("app_id", "segment", "symbol", "company", "submission_type", "broadcast_at",
         "disseminated_at", "revision_remark", "prev_app_id", "xml_url"),
        row)) for row in conn.execute(
        "SELECT app_id, segment, symbol, company, submission_type, broadcast_at, "
        "disseminated_at, revision_remark, prev_app_id, xml_url FROM mkt_nse_pit_filings")]
    xml_files = [r[0] for r in conn.execute("SELECT DISTINCT xml_file FROM mkt_nse_pit_xbrl_facts")]

    by_xml = {}
    for filing in filings:
        base = (filing["xml_url"] or "").rsplit("/", 1)[-1]
        hit = next((x for x in xml_files if base and (x == base or x.endswith("_" + base))), None)
        if not hit:
            audit["filings_without_facts"].append((filing["app_id"], filing["segment"], filing["symbol"]))
            continue
        # the same URL is filed once under equities and once under sme: keep one copy
        if hit not in by_xml or (by_xml[hit]["segment"] != "equities" and filing["segment"] == "equities"):
            by_xml[hit] = filing

    contexts = defaultdict(dict)
    for xml_file, context_id, concept, value, unit in conn.execute(
            "SELECT xml_file, context_id, concept, value, unit FROM mkt_nse_pit_xbrl_facts"):
        contexts[(xml_file, context_id)][concept] = value

    rows = []
    for (xml_file, context_id), facts in contexts.items():
        filing = by_xml.get(xml_file, {})
        main = contexts[(xml_file, "MainI")] if (xml_file, "MainI") in contexts else {}
        if PIT_TXN in facts:
            kind = "trade"
        elif "TypeOfContract" in facts:
            kind = "contract"
        else:
            if context_id != "MainI":
                audit["unmapped_contexts"].append((xml_file, context_id))
            continue
        audit[kind + "_contexts"] += 1

        trade_from = iso_date(facts.get(PIT_FROM))
        trade_to = iso_date(facts.get(PIT_TO))
        known_at = iso_ts(filing.get("disseminated_at") or filing.get("broadcast_at"))
        symbol = clean(main.get("Symbol")) or clean(filing.get("symbol"))
        isin = valid_isin(main.get("ISINCode")) or imap.for_nse(symbol, trade_from or (known_at or "")[:10])
        if not isin:
            audit["unresolved_isin"] += 1
        if not symbol:
            symbol = imap.symbol(isin)
        if kind == "trade":
            side = tx_type(facts.get(PIT_TXN))
            qty = num(facts.get(PIT_QTY))
            value = num(facts.get(PIT_VALUE))
            before = pct(facts.get(PIT_BEFORE_PCT), 100.0)
            after = pct(facts.get(PIT_AFTER_PCT), 100.0)
            mode = mode_norm(facts.get(PIT_MODE))
            sec_type = clean(facts.get("TypeOfInstrument"))
        else:
            # Derivative contract disclosure: units + notional value, no holding percentages.
            side = "BUY" if num(facts.get("BuyNumberOfUnits")) is not None else "OTHER"
            qty = num(facts.get("NumberOfUnits"))
            value = num(facts.get("NotionalValue"))
            before = after = None
            mode = "DERIVATIVE_CONTRACT"
            sec_type = " ".join(x for x in (clean(facts.get("TypeOfInstrument")),
                                            clean(facts.get("TypeOfContract"))) if x) or None
        rows.append({
            "source": "nse_pit_xbrl",
            "source_key": f"nse_pit_xbrl:{xml_file}:{context_id}",
            "symbol": symbol,
            "isin": isin,
            "company": clean(filing.get("company")) or clean(main.get("NameOfTheCompany")),
            "person_name": clean(facts.get("NameOfThePerson")),
            "person_category": clean(facts.get("CategoryOfPerson")),
            "transaction_type": side,
            "mode": mode,
            "security_type": sec_type,
            "qty": qty,
            "value_inr": value,
            "before_pct": before,
            "after_pct": after,
            "trade_from": trade_from,
            "trade_to": trade_to,
            "intimation_date": iso_date(facts.get(PIT_INTIM)),
            "trade_from_raw": clean(facts.get(PIT_FROM)),
            "trade_to_raw": clean(facts.get(PIT_TO)),
            "intimation_date_raw": clean(facts.get(PIT_INTIM)),
            "date_flag": None,
            "known_at": known_at,
            "is_revision": 1 if (filing.get("submission_type") == "Revision"
                                 or str(main.get("RevisedFilling")).lower() == "true") else 0,
            "supersedes": None,
            "is_superseded": 0,
            "also_on": None,
            "_xml": xml_file,
            "_filing": filing.get("app_id") or xml_file,
        })
    audit["filings_used"] = len(by_xml)
    return rows, by_xml


def apply_revisions(pit_rows, audit):
    """Supersede the earlier filing a revision corrects (prev_app_id is unusable: see header)."""
    def row_key(row):
        return (norm_person(row["person_name"]), row["transaction_type"])

    def span(row):
        return row["trade_from"], row["trade_to"] or row["trade_from"]

    def overlaps(a, b):
        a_from, a_to = span(a)
        b_from, b_to = span(b)
        return bool(a_from and a_to and b_from and b_to and max(a_from, b_from) <= min(a_to, b_to))

    by_filing = defaultdict(list)
    for row in pit_rows:
        by_filing[row["_filing"]].append(row)
    filings = {}
    for row in pit_rows:
        filings[row["_filing"]] = {
            "app_id": row["_filing"],
            "xml": row["_xml"],
            "symbol": row["symbol"],
            "known_at": row["known_at"] or "",
            "is_revision": row["is_revision"],
        }
    known = [f for f in filings.values() if f["is_revision"]]
    audit["revision_filings"] = len(known)

    ordered = sorted(filings.values(), key=lambda f: (f["known_at"], str(f["app_id"])))
    prior_by_symbol = defaultdict(list)
    for filing in ordered:
        own = by_filing[filing["app_id"]]
        if not filing["is_revision"]:
            prior_by_symbol[filing["symbol"]].append(filing)
            continue
        audit["revision_rows"] += len(own)
        own_by_key = defaultdict(list)
        for row in own:
            own_by_key[row_key(row)].append(row)
        target = None
        # Prefer an original whose trade window overlaps the revision; only when the
        # revision moved the dates (or they are missing) fall back to person+side.
        for require_overlap in (True, False):
            for previous in reversed(prior_by_symbol[filing["symbol"]]):
                their_by_key = defaultdict(list)
                for row in by_filing[previous["app_id"]]:
                    their_by_key[row_key(row)].append(row)
                if not own_by_key.keys() & their_by_key.keys():
                    continue
                if not require_overlap or any(overlaps(a, b)
                                              for key in own_by_key.keys() & their_by_key.keys()
                                              for a in own_by_key[key] for b in their_by_key[key]):
                    target = previous
                    break
            if target is not None:
                break
        if target is None:
            audit["revisions_without_original"] += 1
        else:
            target_keys = own_by_key.keys() & {row_key(r) for r in by_filing[target["app_id"]]}
            replaced_by_key = defaultdict(list)
            for row in by_filing[target["app_id"]]:
                if row_key(row) in target_keys:
                    replaced_by_key[row_key(row)].append(row["source_key"])
                    row["is_superseded"] = 1
                    audit["superseded_rows"] += 1
            for row in own:
                keys = replaced_by_key.get(row_key(row))
                if keys:
                    row["supersedes"] = ",".join(keys) or None
        prior_by_symbol[filing["symbol"]].append(filing)


def load_bse(conn, imap, audit):
    rows = []
    for file, line_no, company, isin, person, raw_json in conn.execute(
            "SELECT file, line_no, company, isin, person, raw_json FROM mkt_bse_insider"):
        raw = json.loads(raw_json) if raw_json else {}
        raw_isin = clean(raw.get(BSE_ISIN)) or clean(isin)
        raw_company = clean(raw.get(BSE_COMPANY)) or clean(company)
        person_name = clean(raw.get(BSE_PERSON)) or clean(person)
        side = tx_type(raw.get(BSE_TXN))
        trade_from = bse_date(raw.get(BSE_DATE))
        if trade_from is None:
            audit["bse_rows_without_date"] += 1
        rows.append({
            "source": "bse",
            "source_key": f"bse:{file}:{line_no}",
            "symbol": imap.symbol(raw_isin),
            "isin": raw_isin,
            "company": raw_company,
            "person_name": person_name,
            "person_category": clean(raw.get(BSE_PROMOTER)),
            "transaction_type": side,
            "mode": mode_norm(raw.get(BSE_MODE)),
            "security_type": None,
            "qty": num(raw.get(BSE_QTY)),
            "value_inr": num(raw.get(BSE_VALUE)),
            "before_pct": pct(raw.get(BSE_BEFORE_PCT)),
            "after_pct": pct(raw.get(BSE_AFTER_PCT)),
            "trade_from": trade_from,
            "trade_to": trade_from,
            "intimation_date": None,
            "trade_from_raw": clean(raw.get(BSE_DATE)),
            "trade_to_raw": clean(raw.get(BSE_DATE)),
            "intimation_date_raw": None,
            "date_flag": None,
            "known_at": None,
            "is_revision": 0,
            "supersedes": None,
            "is_superseded": 0,
            "also_on": None,
        })
    return rows


# ----------------------------------------------------------------------------
# cross-exchange dedupe
# ----------------------------------------------------------------------------
def dedupe_bse(rows, audit):
    """Pair each BSE row with an unpaired NSE row of the same disclosed trade."""
    def key(row):
        qty = row["qty"]
        return (row["isin"], norm_person(row["person_name"]),
                None if qty is None else round(qty, 4), row["transaction_type"])

    index = defaultdict(list)
    for i, row in enumerate(rows):
        if row["source"] == "bse" or row["is_superseded"] or not row["isin"] or row["qty"] is None:
            continue
        index[key(row)].append(i)

    dropped = set()
    for i, row in enumerate(rows):
        if row["source"] != "bse" or not row["isin"] or row["qty"] is None or not row["trade_from"]:
            continue
        for j in list(index.get(key(row), [])):
            nse = rows[j]
            if nse["trade_from"] and nse["trade_from"] <= row["trade_from"] <= (nse["trade_to"] or nse["trade_from"]):
                nse["also_on"] = "bse" if not nse["also_on"] else nse["also_on"] + ",bse"
                index[key(row)].remove(j)
                dropped.add(i)
                audit["dedupe_matched"] += 1
                break
    kept = [row for i, row in enumerate(rows) if i not in dropped]
    audit["bse_rows_dropped"] = len(dropped)
    return kept


# ----------------------------------------------------------------------------
# build + report
# ----------------------------------------------------------------------------
def build(conn, dry_run=False):
    """Rebuild insider_trades_v2.  The caller owns the transaction."""
    audit = Counter()
    audit.update({
        "unresolved_isin": 0, "filings_without_facts": [], "unmapped_contexts": [],
        "trade_contexts": 0, "contract_contexts": 0, "revision_filings": 0,
        "revision_rows": 0, "superseded_rows": 0, "revisions_without_original": 0,
        "dedupe_matched": 0, "bse_rows_dropped": 0, "bse_rows_without_date": 0,
        "implausible_trade_date": 0, "implausible_intimation_date": 0,
        "rows_with_implausible_date": 0,
    })
    imap = IsinMap(conn)
    rows = load_legacy(conn, imap, audit)
    pit_rows, _ = load_pit(conn, imap, audit)
    apply_revisions(pit_rows, audit)
    rows += pit_rows
    rows += load_bse(conn, imap, audit)
    rows = dedupe_bse(rows, audit)
    apply_date_flags(rows, audit=audit)
    for row in rows:
        row.pop("_xml", None)
        row.pop("_filing", None)

    summary = summarize(rows, audit)
    if not dry_run:
        conn.execute(f"DROP TABLE IF EXISTS {V2_TABLE}")
        conn.execute(DDL)
        for index in INDEXES:
            conn.execute(index)
        conn.executemany(
            f"INSERT INTO {V2_TABLE} ({','.join(ROW_COLS)}) VALUES ({','.join('?' * len(ROW_COLS))})",
            [tuple(row[c] for c in ROW_COLS) for row in rows])
    summary["dry_run"] = dry_run
    return summary


def summarize(rows, audit):
    by_source = Counter(row["source"] for row in rows)
    by_year = Counter()
    seam_trade = Counter()
    seam_known = Counter()
    for row in rows:
        year = (row["trade_from"] or row["known_at"] or "?")[:4]
        by_year[(year, row["source"])] += 1
        month = (row["trade_from"] or "")[:7]
        if month:
            seam_trade[(month, row["source"])] += 1
        known = (row["known_at"] or "")[:7]
        if known:
            seam_known[(known, row["source"])] += 1
    nulls = {field: sum(1 for row in rows if row[field] is None)
             for field in ("isin", "qty", "value_inr", "known_at")}
    isins = {row["isin"] for row in rows if row["isin"]}
    isins_by_source = {source: {row["isin"] for row in rows
                                if row["source"] == source and row["isin"]}
                       for source in by_source}
    known_span = {}
    for source in by_source:
        stamps = [row["known_at"] for row in rows if row["source"] == source and row["known_at"]]
        known_span[source] = (min(stamps), max(stamps)) if stamps else (None, None)
    unmapped_modes = Counter(row["mode"] for row in rows
                             if row["mode"] and row["mode"] not in MODE_MAP.values()
                             and row["mode"] != "MARKET")
    odd_years = sum(1 for row in rows
                    if row["trade_from"] and not "2013" <= row["trade_from"][:4] <= "2026")
    return {
        "rows": len(rows),
        "by_source": dict(by_source),
        "by_year": by_year,
        "seam_trade": seam_trade,
        "seam_known": seam_known,
        "nulls": nulls,
        "distinct_isins": len(isins),
        "distinct_isins_by_source": {k: len(v) for k, v in isins_by_source.items()},
        "known_span": known_span,
        "audit": audit,
        "unmapped_modes": unmapped_modes,
        "odd_year_rows": odd_years,
    }


def report(summary):
    audit = summary["audit"]
    rows = summary["rows"]
    print("=" * 78)
    print(f"  INSIDER TRADES V2 COVERAGE{' (DRY RUN - nothing written)' if summary['dry_run'] else ''}")
    print("=" * 78)
    print(f"  rows: {rows:,}  " + "  ".join(f"{s}={n:,}" for s, n in sorted(summary["by_source"].items())))
    print(f"  distinct ISINs: {summary['distinct_isins']:,}  " + "  ".join(
        f"{s}={n:,}" for s, n in sorted(summary["distinct_isins_by_source"].items())))
    total = max(1, rows)
    print("  null rates: " + "  ".join(
        f"{field}={summary['nulls'][field]:,} ({100.0 * summary['nulls'][field] / total:.1f}%)"
        for field in ("isin", "qty", "value_inr", "known_at")))
    print(f"  dedupe: {audit['dedupe_matched']:,} BSE rows folded into NSE rows (also_on='bse'); "
          f"{audit['bse_rows_dropped']:,} dropped")
    print(f"  revisions: {audit['revision_filings']} filings / {audit['revision_rows']:,} rows, "
          f"{audit['superseded_rows']:,} original rows superseded, "
          f"{audit['revisions_without_original']} with no matching original")
    print(f"  PIT XBRL: {audit['trade_contexts']:,} trade contexts, "
          f"{audit['contract_contexts']} derivative contexts, "
          f"{len(audit['unmapped_contexts'])} unmapped contexts")
    print(f"  unresolved ISIN: {audit['unresolved_isin']:,} rows; "
          f"BSE rows without a date: {audit['bse_rows_without_date']:,}; "
          f"filings without parsed facts: {len(audit['filings_without_facts'])}")
    if summary["unmapped_modes"]:
        print("  non-vocabulary modes: " + ", ".join(
            f"{m}={n}" for m, n in summary["unmapped_modes"].most_common(8)))
    print(f"  implausible dates nulled: {audit['rows_with_implausible_date']} rows "
          f"(trade={audit['implausible_trade_date']}, "
          f"intimation={audit['implausible_intimation_date']}); raw text kept in *_raw")

    print("\n  rows per source per year (trade_from year, else known_at year)")
    sources = sorted(summary["by_source"])
    years = sorted({year for year, _ in summary["by_year"]})
    print("  year    " + "".join(f"{s:>16}" for s in sources) + f"{'total':>14}")
    for year in years:
        counts = [summary["by_year"].get((year, source), 0) for source in sources]
        print(f"  {year:<8}" + "".join(f"{n:>16,}" for n in counts) + f"{sum(counts):>14,}")

    print("\n  2026-03..2026-10 seam (NSE legacy -> PIT XBRL hand-over)")
    print("  month     legacy(trade) xbrl(trade) legacy(known) xbrl(known)   total(known)")
    for month in SEAM_MONTHS:
        lt = summary["seam_trade"].get((month, "nse_legacy"), 0)
        xt = summary["seam_trade"].get((month, "nse_pit_xbrl"), 0)
        lk = summary["seam_known"].get((month, "nse_legacy"), 0)
        xk = summary["seam_known"].get((month, "nse_pit_xbrl"), 0)
        print(f"  {month}  {lt:>12,} {xt:>11,} {lk:>13,} {xk:>11,} {lk + xk:>14,}")
    span = summary["known_span"]
    print("  known_at span: " + "  ".join(
        f"{source} {span[source][0]} .. {span[source][1]}" if span[source][0]
        else f"{source} (no dissemination stamp)" for source in sources))
    print("=" * 78)


def connect(path, read_only):
    if read_only:
        return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=120)
    conn = sqlite3.connect(str(path), timeout=180, isolation_level=None)
    conn.execute("PRAGMA busy_timeout = 180000")
    return conn


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=str(cfg.DB_PATH), help="SQLite DB path (default: config DB)")
    ap.add_argument("--dry-run", action="store_true", help="read the DB read-only and print the report only")
    args = ap.parse_args()

    conn = connect(Path(args.db), args.dry_run)
    try:
        if not args.dry_run:
            conn.execute("BEGIN IMMEDIATE")
        summary = build(conn, args.dry_run)
        if not args.dry_run:
            conn.execute("COMMIT")
    except Exception:
        if not args.dry_run:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.OperationalError:
                pass
        raise
    finally:
        conn.close()
    report(summary)


if __name__ == "__main__":
    main()
