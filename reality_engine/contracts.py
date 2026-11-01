"""Typed write contracts for the 16 pilot measure tables (T-016).

A contract says, per table and measure: the unit the number may carry, the range
it must fall in, and the words its own quote must print next to the number.
``extract60._write`` calls :func:`check` on every row before the INSERT, so no
write path (Arm A code rows, the announcement regex pass, the BSE rating feed,
the model reader, ``repair``) can store a row that fails:

- The number must be in the quote AND a term naming the measure must sit within
  ``TERM_WINDOW`` characters of it: "30% digital contribution" cannot become
  NIM = 90, and "Order Book Rs 37,697 Cr." cannot become order intake.
- A number that only appears inside a label is rejected: the 4 in "Q4" is a
  label, not a value (``digit_from_label``).
- Unit and range are typed per measure (NIM 0-25%, capacity in kt/mtpa/mw,
  a percent in 0-100, money in Rs crore), so a megawatt capacity with unit
  ``inr_cr`` or a zero EPS cannot be written.
- Evidence is typed too: a document page (``page >= 1``), a structured XBRL
  filing (``source == "results_xbrl"``), or a BSE announcement headline
  (``source_doc_id`` starts with ``bse_ann:``); an announcement row may instead
  carry its headline. Every row still declares ``known_at`` and a period.

Rejections are counted per measure: the reason is
``contract:<measure>:<code>``.  ``extract60._write`` stores the rejected row and
that reason in ``extract_reject``; nothing is dropped silently.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any

__all__ = ["Measure", "TableContract", "CONTRACTS", "TERM_WINDOW", "check",
           "measure_of", "reject_summary"]

#: A measure term must sit this many characters from the number it explains.
TERM_WINDOW = 60
#: Percent-like numbers must fall in a true percentage.
PCT_RANGE = (0.0, 100.0)
INR_CR = ("inr_cr",)
PCT = ("pct",)
CAPACITY_UNITS = ("tpa", "tpd", "mtpa", "kt", "ktpa", "mt", "mn_tonnes", "tonnes",
                  "units", "lakh_units", "mw", "kw", "kilowatt", "kl", "nos")
VOLUME_UNITS = ("kt", "ktpa", "mt", "mn_tonnes", "tonnes", "units", "lakh_units")
OM_UNITS = ("count", "tonnes", "mt", "kt", "units", "sqft", "pct", "inr_cr",
            "inr_per_unit", "usd_mn", "kw", "mw", "kl", "days", "nos")
RATING_DIRECTIONS = ("upgrade", "downgrade", "reaffirm", "watch", "default")
PRICE_DIRECTIONS = ("hike", "cut", "mixed")
#: Announcement tables whose evidence is the filing's own headline, not a page.
HEADLINE_TABLES = ("rating_action", "order_book_contract", "company_price_revision")

_DATE_PREFIX = re.compile(r"^\d{4}-\d{2}-\d{2}")
#: Numeric tokens, with an explicit money suffix converted to Rs crore (the
#: printed suffix, never a table header the quote does not carry).
_NUM = re.compile(r"(?<![\w.])(-?\d[\d,]*(?:\.\d+)?)\s*"
                  r"(crore|cr\b|lakh|lac\b|million|mn\b|billion|bn\b|thousand|%)?", re.I)
_TO_CRORE = {"crore": 1.0, "cr": 1.0, "lakh": 0.01, "lac": 0.01, "million": 0.1,
             "mn": 0.1, "billion": 100.0, "bn": 100.0, "thousand": 0.001}
#: Labels whose digits are period names, never values ("Q4" is not 4.0).
_LABEL = re.compile(r"\b(?:Q[1-4]|H[12]|S[12]|9M|6M|3M|FY\s?'?\d{2,4}|"
                    r"Q[1-4]\s?'?FY\s?'?\d{2,4})\b", re.I)
_XBRL_EQUALS = re.compile(r"=\s*(-?\d+(?:\.\d+)?)")
#: Words too generic to identify a free-form measure on their own.
_STOPWORDS = {"the", "and", "for", "with", "from", "per", "total", "new", "net",
              "of", "in", "ms", "mm", "mn", "bn", "cr", "kt", "usd", "inr", "pct"}
_WORD = re.compile(r"[a-z]{3,}")
_NOT_A_LEVEL = re.compile(r"\bgrew\b|\bgrowth\b|\bdeclin|\brose\b|\bexpand|\bhigher\b|"
                          r"\blower\b|\bguidance\b|\bexpect|\bestimat", re.I)


@dataclass(frozen=True)
class Measure:
    """One number a table stores, with its typed unit, range and quote term."""

    key: str
    field: str
    units: tuple[str, ...]
    lo: float
    hi: float
    terms: str = ""
    unit_field: str | None = None
    optional: bool = False


@dataclass(frozen=True)
class TableContract:
    name: str
    period_field: str | None
    measures: dict[str, Measure]
    key_field: str | None = None
    vocab: bool = False             # the key field is a closed vocabulary
    text_fact: bool = False         # the row's fact is a direction/rating, not a number


def _m(key: str, field_name: str, units: tuple[str, ...], lo: float, hi: float,
       terms: str = "", unit_field: str | None = None) -> Measure:
    return Measure(key, field_name, units, lo, hi, terms, unit_field)


#: The 16 measure tables, each with its allowed measures.  A keyed table looks
#: its measure up under ``key_field``; an unkeyed table checks every measure it
#: carries and must carry at least one.
CONTRACTS: dict[str, TableContract] = {
    "company_segment_pnl": TableContract(
        "company_segment_pnl", "period_end", key_field="metric", vocab=True, measures={
            "revenue": _m("revenue", "value_cr", INR_CR, 0.01, 5e6, r"revenue|turnover|sales"),
            "ebit": _m("ebit", "value_cr", INR_CR, 0.01, 5e6, r"\bebit\b|operating profit"),
            "ebitda": _m("ebitda", "value_cr", INR_CR, 0.01, 5e6, r"\bebitda\b"),
            "segment_assets": _m("segment_assets", "value_cr", INR_CR, 0.01, 5e7,
                                 r"assets"),
            "segment_liabilities": _m("segment_liabilities", "value_cr", INR_CR, 0.01, 5e7,
                                      r"liabilit"),
            "capex": _m("capex", "value_cr", INR_CR, 0.01, 5e6,
                        r"capex|capital expenditure"),
        }),
    "company_operating_metrics": TableContract(
        "company_operating_metrics", "period_end", key_field="metric", measures={
            # Free-form metric name: its own words are the measure term (see check).
            "_": _m("metric", "value", OM_UNITS, -1e9, 1e9, "", unit_field="unit"),
        }),
    "company_cost_structure": TableContract(
        "company_cost_structure", "period_end", key_field="input_key", vocab=True,
        measures={
            "copper": _m("copper", "amount_cr", INR_CR, 0.01, 5e6, r"copper|cost|consumption"),
            "aluminium": _m("aluminium", "amount_cr", INR_CR, 0.01, 5e6,
                            r"alumin|cost|consumption"),
            "aluminum": _m("aluminum", "amount_cr", INR_CR, 0.01, 5e6,
                           r"alumin|cost|consumption"),
            "steel": _m("steel", "amount_cr", INR_CR, 0.01, 5e6, r"steel|cost|consumption"),
            "coking_coal": _m("coking_coal", "amount_cr", INR_CR, 0.01, 5e6,
                              r"coking coal|coal|cost|consumption"),
            "crude": _m("crude", "amount_cr", INR_CR, 0.01, 5e6, r"crude|cost|consumption"),
            "power": _m("power", "amount_cr", INR_CR, 0.01, 5e6,
                        r"power|electricity|cost|consumption"),
            "freight": _m("freight", "amount_cr", INR_CR, 0.01, 5e6, r"freight|cost"),
            "labour": _m("labour", "amount_cr", INR_CR, 0.01, 5e6, r"labour|labor|cost"),
            "labor": _m("labor", "amount_cr", INR_CR, 0.01, 5e6, r"labour|labor|cost"),
            "packaging": _m("packaging", "amount_cr", INR_CR, 0.01, 5e6, r"packaging|cost"),
            "fuel": _m("fuel", "amount_cr", INR_CR, 0.01, 5e6, r"fuel|cost|consumption"),
            "other": _m("other", "amount_cr", INR_CR, 0.01, 5e6, r"cost|expense|other"),
        }),
    "company_debt_mix": TableContract(
        "company_debt_mix", "period_end", key_field="bucket", measures={
            "amount_cr": _m("amount_cr", "amount_cr", INR_CR, 0.01, 5e6,
                            r"borrow|loan|debt|repay|maturit|credit|facility"),
            "rate_pct": _m("rate_pct", "rate_pct", PCT, 0.0, 30.0,
                           r"%|per ?cent|p\.a\.|bps"),
        }),
    "company_capacity_utilisation": TableContract(
        "company_capacity_utilisation", "period_end", key_field="product", measures={
            "capacity": _m("capacity", "capacity", CAPACITY_UNITS, 0.01, 1e7,
                           r"capacity|capacities|installed|production|plant",
                           unit_field="capacity_unit"),
            "utilisation_pct": _m("utilisation_pct", "utilisation_pct", PCT, 0.0, 100.0,
                                  r"utilisation|utilization|capacity|operating|plant"),
            "production": _m("production", "production", CAPACITY_UNITS, 0.01, 1e9,
                             r"production|output|manufactur|produced",
                             unit_field="capacity_unit"),
        }),
    "capex_project": TableContract(
        "capex_project", "announced_on", measures={
            "capex_cr": _m("capex_cr", "capex_cr", INR_CR, 0.01, 5e6,
                           r"capex|capital expenditure|investment|project|plant|commission"),
        }),
    "order_intake": TableContract(
        "order_intake", "period_end", measures={
            "intake_cr": _m("intake_cr", "intake_cr", INR_CR, 0.01, 5e5,
                            r"order intake|order inflow|orders received|new orders|"
                            r"order win|order wins|secured orders|intake"),
            "order_book_cr": _m("order_book_cr", "order_book_cr", INR_CR, 0.01, 5e6,
                                r"order book|order-book|book to bill|\bL1\b"),
            "book_to_bill": _m("book_to_bill", "book_to_bill", ("x",), 0.01, 50.0,
                               r"book to bill|book-to-bill|order book"),
        }),
    "order_book_contract": TableContract(
        "order_book_contract", "signed_on", measures={
            "value_cr": _m("value_cr", "value_cr", INR_CR, 0.01, 5e5,
                           r"award|contract|order|LOA|letter of award|bagged|secured|win"),
        }),
    "company_price_revision": TableContract(
        "company_price_revision", "announced_on", text_fact=True, measures={
            "revision_pct": _m("revision_pct", "revision_pct", PCT, -100.0, 100.0,
                               r"price|pricing|hike|increase|cut|reduc|revis|MRP"),
        }),
    "rating_action": TableContract(
        "rating_action", "action_date", text_fact=True, measures={
            "amount_cr": _m("amount_cr", "amount_cr", INR_CR, 0.01, 5e6, r"rating"),
        }),
    "supply_link": TableContract(
        "supply_link", None, measures={
            "share_of_cost_pct": _m("share_of_cost_pct", "share_of_cost_pct", PCT, 0.0, 100.0,
                                    r"supplier|customer|purchase|sales|joint venture|"
                                    r"subsidiar|holding company"),
        }),
    "balance_sheet_lines": TableContract(
        "balance_sheet_lines", "period_end", key_field="line_item", vocab=True, measures={
            "total_assets": _m("total_assets", "value_cr", INR_CR, 0.01, 5e7,
                               r"total\s?assets|assets"),
            "total_liabilities": _m("total_liabilities", "value_cr", INR_CR, 0.01, 5e7,
                                    r"liabilit"),
            "total_equity": _m("total_equity", "value_cr", INR_CR, 0.01, 5e7, r"equity"),
            "equity_owners": _m("equity_owners", "value_cr", INR_CR, 0.01, 5e7,
                                r"owners of the parent|equity attributable|equity"),
            "borrowings": _m("borrowings", "value_cr", INR_CR, 0.01, 5e7,
                             r"borrowing|debt"),
            "trade_receivables": _m("trade_receivables", "value_cr", INR_CR, 0.01, 5e7,
                                    r"trade\s?receivables|receivables"),
            "inventories": _m("inventories", "value_cr", INR_CR, 0.01, 5e7, r"inventor"),
            "cash_and_equivalents": _m("cash_and_equivalents", "value_cr", INR_CR, 0.01, 5e7,
                                       r"cash\s?and\s?cash|equivalents|cash"),
            "paid_up_capital": _m("paid_up_capital", "value_cr", INR_CR, 0.01, 5e7,
                                  r"paid\s?up|share capital"),
            "equity_and_liabilities": _m("equity_and_liabilities", "value_cr", INR_CR, 0.01,
                                         5e7, r"equity\s?and\s?liabilities"),
        }),
    "cash_flow_lines": TableContract(
        "cash_flow_lines", "period_end", key_field="line_item", vocab=True, measures={
            "operating_activities": _m("operating_activities", "value_cr", INR_CR, -5e7, 5e7,
                                       r"operating\s?activities|operations"),
            "investing_activities": _m("investing_activities", "value_cr", INR_CR, -5e7, 5e7,
                                       r"investing\s?activities|investment"),
            "financing_activities": _m("financing_activities", "value_cr", INR_CR, -5e7, 5e7,
                                       r"financing\s?activities|finance"),
            "closing_cash": _m("closing_cash", "value_cr", INR_CR, 0.01, 5e7,
                               r"cash\s?and\s?cash|equivalents|cash"),
            "depreciation": _m("depreciation", "value_cr", INR_CR, 0.01, 5e7,
                               r"depreciation|amortis|amortiz"),
            "capex": _m("capex", "value_cr", INR_CR, 0.01, 5e7,
                        r"capital expenditure|capex|purchase of.*assets|fixed assets"),
        }),
    "tax_reconciliation": TableContract(
        "tax_reconciliation", "period_end", key_field="item", vocab=True, measures={
            # A tax line is signed: a deferred-tax credit prints as a negative number.
            "current_tax": _m("current_tax", "amount_cr", INR_CR, -5e6, 5e6,
                              r"current\s?tax"),
            "deferred_tax": _m("deferred_tax", "amount_cr", INR_CR, -5e6, 5e6,
                               r"deferred\s?tax"),
            "tax_expense": _m("tax_expense", "amount_cr", INR_CR, -5e6, 5e6,
                              r"tax\s?expense|total tax|tax"),
            "profit_before_tax": _m("profit_before_tax", "amount_cr", INR_CR, -5e6, 5e6,
                                    r"profit\s?before\s?tax|\bPBT\b"),
            "effective_tax_rate": _m("effective_tax_rate", "effective_rate_pct", PCT, -100.0,
                                     100.0, r"effective tax|tax rate|TaxExpense|"
                                     r"ProfitBeforeTax|%"),
        }),
    "lender_metrics": TableContract(
        "lender_metrics", "period_end", key_field="metric", vocab=True,
        measures={
            "gnpa_pct": _m("gnpa_pct", "value", PCT, 0.0, 100.0,
                           r"\bGNPA\b|gross NPA|gross non[- ]performing", unit_field="unit"),
            "nnpa_pct": _m("nnpa_pct", "value", PCT, 0.0, 100.0,
                           r"\bNNPA\b|net NPA|net non[- ]performing", unit_field="unit"),
            "nim_pct": _m("nim_pct", "value", PCT, 0.0, 25.0,
                          r"\bNIM\b|net interest margin", unit_field="unit"),
            "casa_pct": _m("casa_pct", "value", PCT, 0.0, 100.0, r"\bCASA\b",
                           unit_field="unit"),
            "credit_cost_pct": _m("credit_cost_pct", "value", PCT, 0.0, 25.0,
                                  r"credit cost", unit_field="unit"),
            "capital_adequacy_pct": _m("capital_adequacy_pct", "value", PCT, 0.0, 100.0,
                                       r"capital adequacy", unit_field="unit"),
            "provision_coverage_pct": _m("provision_coverage_pct", "value", PCT, 0.0, 100.0,
                                         r"provision coverage|\bPCR\b", unit_field="unit"),
            "loan_book_cr": _m("loan_book_cr", "value", INR_CR, 0.01, 5e7,
                               r"loan book|loans|advances|AUM|assets under management",
                               unit_field="unit"),
            "advances_cr": _m("advances_cr", "value", INR_CR, 0.01, 5e7,
                              r"advances|loans|loan book", unit_field="unit"),
            "deposits_cr": _m("deposits_cr", "value", INR_CR, 0.01, 5e7, r"deposits",
                              unit_field="unit"),
        }),
    "unit_volume": TableContract(
        "unit_volume", "period_end", key_field="product", measures={
            "quantity": _m("quantity", "quantity", VOLUME_UNITS, 0.01, 1e9,
                           r"shipments?|production|volumes?|sales volume|output|"
                           r"dispatches|sold", unit_field="unit"),
        }),
}


def measure_of(reason: str) -> str:
    """The measure a contract reason belongs to, for per-measure reject counts."""
    parts = str(reason or "").split(":")
    return parts[1] if len(parts) >= 3 and parts[0] == "contract" else "-"


def reject_summary(reasons: list[str] | dict[str, int]) -> dict[str, int]:
    """Reject counts per measure from a list of reasons or a Counter."""
    counts: dict[str, int] = {}
    items = reasons.items() if isinstance(reasons, dict) else ((r, 1) for r in reasons)
    for reason, n in items:
        name = measure_of(reason)
        counts[name] = counts.get(name, 0) + int(n)
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


# --------------------------------------------------------------------------- helpers
def _num(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        found = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(found) or math.isinf(found) else found


def _spans(text: str) -> list[tuple[float, int, int]]:
    """(value in Rs crore, start, end) for every printed number in ``text``."""
    text = re.sub(r"(?:Rs\.|INR|₹)", lambda m: " " * len(m.group(0)), text or "")
    out = []
    for match in _NUM.finditer(text):
        try:
            found = float(match.group(1).replace(",", ""))
        except ValueError:
            continue
        factor = _TO_CRORE.get((match.group(2) or "").strip().lower())
        out.append((found if factor is None else found * factor, match.start(), match.end()))
    return out


def _in_tolerance(found: float, value: float) -> bool:
    return abs(found - value) <= max(abs(value) * 0.02, 0.011)


def _label_values(quote: str) -> list[float]:
    out = []
    for token in _LABEL.finditer(quote or ""):
        out.extend(float(d) for d in re.findall(r"\d+(?:\.\d+)?", token.group(0)))
    return out


def _key_words(key: str) -> list[str]:
    return [w for w in _WORD.findall(str(key or "").lower()) if w not in _STOPWORDS]


def _label(key: str, fallback: str) -> str:
    """A countable, safe measure label for a reject reason (the row key when it has one)."""
    safe = re.sub(r"[^a-z0-9_]+", "_", str(key or "").strip().lower()).strip("_")
    return (safe[:40] or fallback)


def _term_ok(text: str, terms: str, key: str) -> bool:
    """A measure term, or the free-form key's own words, in ``text``."""
    if terms and re.search(terms, text, re.I):
        return True
    return any(re.search(rf"\b{re.escape(w)}", text, re.I) for w in _key_words(key))


def _page_ok(row: dict, table: str) -> tuple[bool, str | None]:
    page = _num(row.get("page"))
    if page is not None and page >= 1:
        return True, None
    source = str(row.get("source") or "")
    if source == "results_xbrl":
        return True, None
    doc = str(row.get("source_doc_id") or row.get("doc_id") or "")
    if doc.startswith("bse_ann:") or table in HEADLINE_TABLES:
        return True, None
    return False, "contract:row:page_missing"


def _xbrl_value(quote: str, value: float) -> float | None:
    """The rupees figure printed in an XBRL quote, in Rs crore, when it matches."""
    match = _XBRL_EQUALS.search(quote or "")
    if not match:
        return None
    raw = float(match.group(1))
    return raw / 1e7 if _in_tolerance(raw / 1e7, value) else None


def _number_reason(quote: str, measure: Measure, value: float, key: str,
                   label: str, row: dict) -> str | None:
    """None when the quote carries the number with the measure term beside it."""
    xbrl = str(row.get("source") or "") == "results_xbrl"
    if xbrl and measure.units and measure.units[0] in ("inr_cr", "usd_mn"):
        if _xbrl_value(quote, value) is not None:
            return None if _term_ok(quote, measure.terms, key) \
                else f"contract:{label}:measure_term_absent"
    hits = [span for span in _spans(quote) if _in_tolerance(span[0], value)]
    if not hits:
        if any(_in_tolerance(found, value) for found in _label_values(quote)):
            return f"contract:{label}:digit_from_label"
        return f"contract:{label}:value_not_in_quote"
    for _, start, end in hits:
        window = quote[max(0, start - TERM_WINDOW):end + TERM_WINDOW]
        if _term_ok(window, measure.terms, key):
            return None
    return f"contract:{label}:measure_term_absent"


def _measure_ok(row: dict, measure: Measure, key: str) -> str | None:
    label = _label(key, measure.key)
    value = _num(row.get(measure.field))
    if value is None:
        return f"contract:{label}:value_missing"
    if measure.unit_field:
        unit = str(row.get(measure.unit_field) or "").strip().lower()
        if unit not in measure.units:
            return f"contract:{label}:unit:{unit or 'missing'}"
        if unit == "pct" and not (PCT_RANGE[0] <= value <= PCT_RANGE[1]):
            return f"contract:{label}:pct_out_of_range"
    if value == 0:
        return f"contract:{label}:zero_value"
    if value < measure.lo:
        return f"contract:{label}:value_below_range"
    if value > measure.hi:
        return f"contract:{label}:value_above_range"
    quote = str(row.get("quote") or row.get("evidence_quote") or "")
    if measure.key == "revision_pct" and _NOT_A_LEVEL.search(quote):
        return f"contract:{label}:growth_rate_not_level"
    return _number_reason(quote, measure, value, key, label, row)


def _check_text_fact(contract: TableContract, row: dict, quote: str) -> tuple[bool, str | None]:
    """A rating action or a price revision: the direction is the fact."""
    direction = str(row.get("direction") or "").strip().lower()
    if contract.name == "rating_action":
        if direction not in RATING_DIRECTIONS:
            return False, "contract:direction:vocabulary"
        if not re.search(r"rating|CRISIL|ICRA|CARE|India Ratings|Brickwork|Acuit|"
                         r"upgrad|downgrad|outlook|assigned|reaffirm", quote, re.I):
            return False, "contract:direction:measure_term_absent"
    else:
        if direction not in PRICE_DIRECTIONS:
            return False, "contract:direction:vocabulary"
        if not re.search(r"price|pricing|hike|increase|cut|reduc|revis|MRP", quote, re.I):
            return False, "contract:direction:measure_term_absent"
    for measure in contract.measures.values():
        if _num(row.get(measure.field)) is None:
            continue                      # optional numeric evidence (e.g. amount_cr)
        reason = _measure_ok(row, measure, "")
        if reason:
            return False, reason
    return True, None


def check(table: str, row: dict) -> tuple[bool, str | None]:
    """``(True, None)`` when the row may be written, else ``(False, reason)``."""
    contract = CONTRACTS.get(table)
    if contract is None:
        return True, None
    quote = str(row.get("quote") or row.get("evidence_quote") or "").strip()
    if not quote:
        return False, "contract:row:quote_missing"
    if not _DATE_PREFIX.match(str(row.get("known_at") or "")):
        return False, "contract:row:known_at_missing"
    if contract.period_field and not _DATE_PREFIX.match(
            str(row.get(contract.period_field) or "")):
        return False, f"contract:row:period_missing:{contract.period_field}"
    ok, reason = _page_ok(row, contract.name)
    if not ok:
        return False, reason
    if contract.text_fact:
        return _check_text_fact(contract, row, quote)
    key = str(row.get(contract.key_field) or "").strip().lower() if contract.key_field else ""
    if contract.key_field and not key:
        return False, "contract:row:key_missing"
    if contract.vocab:
        measure = contract.measures.get(key)
        if measure is None:
            return False, f"contract:{key or 'row'}:vocabulary"
        present = [measure] if _num(row.get(measure.field)) is not None else []
        if not present:
            return False, f"contract:{measure.key}:value_missing"
    else:
        present = [m for m in contract.measures.values()
                   if _num(row.get(m.field)) is not None]
        if not present:
            first = next(iter(contract.measures.values()))
            return False, f"contract:{first.key}:value_missing"
    for measure in present:
        reason = _measure_ok(row, measure, key)
        if reason:
            return False, reason
    return True, None
