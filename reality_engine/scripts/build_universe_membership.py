"""Build point-in-time theme universes from the data itself.

    python -m reality_engine.scripts.build_universe_membership \
        [--db PATH] [--data-root PATH] [--themes PATH] [--dry-run]

Every run rebuilds ``universe_membership`` and ``universe_candidates`` from evidence
and writes one diff row to ``universe_membership_runs``.  Source databases are opened
read-only; only the target ``--db`` is written (default:
``<data-root>/equity_intelligence.db``).

Signals, strongest first:
  segment    an AR / deck revenue-mix row: the theme segment's revenue divided by the
             company's total revenue from operations for the *same document, fiscal
             period and unit*.  A percent row counts only when it is a company
             revenue-mix line: market share, customer concentration, AUM / loan mix,
             targets and guidance are not weights.
  segment_sum
             the same row when the document states no total of its own: the segment
             table's own sum is the denominator, but only if that sum reconciles within
             1% to a revenue figure the document states elsewhere.  That reconciliation
             is what rejects a parent segment listed alongside its children.
  industry   NSE industry classification (``company_industry``) - unweighted.
  curated    seed in ``plugins/reality-data/server/universes.yaml`` - unweighted.

A theme may require an NSE industry family before a revenue row counts as a weight
(``segment_industry_keywords``), so a lubricant blender is not an OMC.

A member is either weighted (a ``segment`` share) or explicitly unweighted (``industry``
/ ``curated``); there is no zero weight.  ``subsidiary`` and ``stated_pivot`` hits are
evidence of interest, not of revenue, so they land in ``universe_candidates`` with their
quote and never in ``universe_membership``.

The latest fiscal year's weight applies from that year's filing date until the next
filed year, and expires two fiscal years after its own (``valid_to``), so a stale
weight drops out of a point-in-time query instead of silently persisting.  A row with
no disclosure date is dropped, never dated from the fiscal-year end.  Where a weight
expires the industry / curated row takes over, so every (theme, ISIN) chain hands over
exactly: no gap and no overlap (a chain with no unweighted row carries its last weight
forward to the next filed disclosure only).  The denominator is "revenue from
operations", then "total revenue", then "total income" - never the largest figure on
the page.

``pivot`` is true when the theme segment is the largest of one reconciling segment table
(>=3 distinct siblings whose sum matches the stated total within 1%).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sqlite3
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_THEMES = ROOT / "plugins" / "reality-data" / "server" / "universes.yaml"

#: A segment share below this is not a theme membership: 16.7% of revenue from a product
#: line is not "a dairy company".  Overridable per theme with ``min_segment_weight``.
DEFAULT_MIN_SEGMENT_WEIGHT = 0.5
#: ``valid_from`` fallback when the listing date is unknown (never the crawl date).
DEFAULT_VALID_FROM = "2019-01-01"

METHOD_RANK = {"segment": 3, "industry": 2, "curated": 1}
ENTRY_WORDS = ("enter", "entering", "foray", "launch", "commission", "new segment",
               "diversif", "set up", "setting up", "ventur", "expand", "expanding")

#: ``item`` (base, with the segment / unit suffix stripped) that means "whole revenue".
#: Numerator and denominator share this vocabulary, so a product line can never be
#: divided by another product line.
TOTAL_ITEMS = frozenset({
    "revenue from operations", "total revenue from operations", "revenue from operations total",
    "net revenue from operations", "gross revenue from operations", "total operating revenue",
    "total income from operations", "income from operations", "revenue", "total revenue",
    "total revenues", "turnover", "net turnover", "total turnover", "total income",
    "external revenue", "total external revenue", "net sales", "total sales",
})
#: Denominator preference (manager rule N9): revenue from operations, then total revenue,
#: then total income.  A page that states several bases must not silently take the max.
TOTAL_RANK: dict[str, int] = {}
for _rank, _bases in enumerate((
        ("revenue from operations", "total revenue from operations", "revenue from operations total",
         "net revenue from operations", "gross revenue from operations", "total operating revenue",
         "total income from operations", "income from operations"),
        ("revenue", "total revenue", "total revenues", "turnover", "net turnover", "total turnover",
         "external revenue", "total external revenue", "net sales", "total sales"),
        ("total income",))):
    for _base in _bases:
        TOTAL_RANK[_base] = _rank
assert set(TOTAL_ITEMS) == set(TOTAL_RANK)
#: Ind AS revenue note lines ("Revenue from contract with customers" + "Revenue from other
#: contracts"): a segment sum may reconcile to their total when the report states no
#: "Revenue from Operations" line of its own.
CONTRACT_BASES = ("revenue from contract", "revenue from contracts", "revenue from other contract")
#: Rows that look like revenue but are not company revenue mix, whatever the wording.
BLOCKED = ("asset", "liabilit", "capital employed", "investment", "employee", "depreciation",
           "interest cost", "finance cost", "tax expense", "customer", "market size",
           "market share", "market growth", "order book", "outstanding", "sanction",
           "disburse", "booking", "pipeline", "borrowing", "net worth", "debt", "pat",
           "ebitda", "margin", "growth", "cagr", "previous year", "prior year", "projected",
           "forecast", "target", "guidance", "receivable",
           "well being", "wellbeing", "shareholding", "promoter", "pledge", "unit sold",
           "volume", "price realisation", "cost per", "unorganised", "unorganized",
           "organized sector", "distributor", "dealer", "sales to", "marketing companies",
           "from major", "supplier", "procurement", "purchase", "tender", "proposed transaction",
           "related party", "subsidiary", "annexure", "comprehensive income", "end use")
#: Portfolio vocabulary: blocked only when the row is not the company's own revenue mix.
#: "Interest income from housing loans % of revenue" is a weight; "Mortgage contribution
#: to loan portfolio" is a loan mix and is not.
SOFT_BLOCKED = ("aum", "loan", "portfolio", "advances")
#: A percent row is a *company revenue mix* line only when it says so explicitly; a bare
#: "share of <anything>" is a market, portfolio or end-use statistic.
MIX_PATTERNS = ("revenue mix", "product mix", "business mix", "sales mix", "revenue contribution",
                "turnover contribution", "contribution to turnover", "contribution to revenue",
                "share of turnover", "share of revenue", "share of total turnover",
                "share of total revenue", "share of total income", "turnover share",
                "revenue share", "% of total", "of turnover", "of revenue", "of total revenue",
                "of total turnover", "% to total turnover", "% to total revenue",
                "principal business activity")
#: Segment-table rows that are not a business segment: totals, eliminations and
#: reconciling items must never join the sibling set.
NON_SEGMENT_LABELS = ("total", "less", "inter segment", "intersegment", "inter-segment",
                      "elimination", "adjustment", "unallocated")
REVENUE_WORD = re.compile(r"\b(revenue|turnover|sales|income)\b")
_UNIT_WORDS = frozenset(("rs", "inr", "rupees", "crore", "crores", "cr", "lakh", "lakhs", "lac",
                         "lacs", "million", "millions", "mn", "billion", "bn", "usd", "us$",
                         "thousand", "h", "percent", "%", "in"))
_YEARISH = re.compile(r"\b(?:19|20)\d{2}\b|^(?:fy|f\.?y\.?|q[1-4])\s*\d{0,4}$")


def _norm(text: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).strip()


def _hit(text: Any, keywords: list[str]) -> str:
    """Whole-token keyword match: "oil" matches "oil", not "boiler"."""
    hay = _norm(text)
    if not hay:
        return ""
    words = set(hay.split())
    for keyword in keywords:
        needle = _norm(keyword)
        if needle and (needle in hay if " " in needle else needle in words):
            return keyword
    return ""


def _date(value: Any) -> str:
    """ISO date from ISO timestamps and NSE's ``DD-Mon-YYYY 00:00:00``."""
    text = str(value or "").strip()
    if not text:
        return ""
    for candidate, fmt in ((text[:10], "%Y-%m-%d"), (text.split(" ")[0], "%d-%b-%Y")):
        try:
            return dt.datetime.strptime(candidate, fmt).date().isoformat()
        except ValueError:
            continue
    return ""


def _years(text: Any) -> set[int]:
    """Every fiscal / calendar year a period label names ("FY19", "FY24-25", "2019")."""
    low = str(text or "").lower()
    years = {int(y) for y in re.findall(r"\b(19\d{2}|20\d{2})\b", low)}
    if not re.search(r"\d{4}-\d{2}-\d{2}", low):  # "2018-19" is a span, "2026-03" is a date
        years |= {2000 + int(m.group(2)) for m in
                  re.finditer(r"\b(?:19|20)(\d{2})\s*[-/]\s*(\d{2})\b", low)}
    for match in re.finditer(r"(?:fy|f\.?y\.?)\s*(\d{2})(?!\d)(?:\s*[-/]\s*(\d{2}))?", low):
        years.add(2000 + int(match.group(1)))
        if match.group(2):
            years.add(2000 + int(match.group(2)))
    return years


def _money_unit(unit: Any) -> bool:
    low = _norm(unit)
    if not low or "%" in str(unit or ""):
        return False
    if any(tok in low.split() for tok in ("number", "share", "unit", "mmt", "mt", "mw", "gw", "km")):
        return False
    return any(tok in low.split() for tok in ("rs", "inr", "rupees", "crore", "crores", "cr",
                                              "lakh", "lakhs", "lac", "lacs", "million",
                                              "millions", "mn", "billion", "bn")) or "crore" in low


def _unit_scale(unit: Any) -> str:
    """Normalised unit bucket: ``Rs crore`` / ``CRORE`` / ``₹ Cr`` all become 'crore'."""
    words = set(_norm(unit).split())
    for bucket, tokens in (("crore", ("crore", "crores", "cr")),
                           ("lakh", ("lakh", "lakhs", "lac", "lacs")),
                           ("million", ("million", "millions", "mn")),
                           ("billion", ("billion", "bn")),
                           ("thousand", ("thousand",))):
        if words & set(tokens):
            return bucket
    return " ".join(sorted(words))


def _split_item(item: Any) -> tuple[str, str]:
    """``("revenue from operations", "petroleum")`` for ``Revenue from Operations (Petroleum)``.

    The suffix is the segment name; a currency / year suffix means the row is a total.
    Three shapes occur in the source: ``(Segment)``, ``: Segment`` and the segment-table
    form ``Revenue from Operations - Petroleum segment``.
    """
    text = str(item or "")
    base, suffix = text, ""
    paren = re.search(r"[\(\[]([^\)\]]*)[\)\]]", text)
    if paren:
        base = (text[:paren.start()] + " " + text[paren.end():]).strip(" :-,")
        suffix = paren.group(1)
    if ":" in base:
        head, _, tail = base.partition(":")
        base, suffix = head, f"{suffix} {tail}"
    for dash in (" - ", " – ", " — "):
        if dash in base:
            head, _, tail = base.partition(dash)
            if _norm(head) in TOTAL_ITEMS:
                base, suffix = head, f"{suffix} {tail}"
                break
    return _norm(base), _norm(suffix)


def _is_unit_suffix(suffix: str) -> bool:
    """True when a parenthetical suffix is a unit/citation, i.e. the row is a total."""
    if not suffix or _YEARISH.search(suffix):
        return True
    words = suffix.split()
    return all(word in _UNIT_WORDS for word in words)


def _segment_labels(item: Any, category: Any) -> tuple[str, str]:
    """(label to match the theme against, shared total base) or ("", "").

    Only a company revenue-mix row qualifies: a row whose item is the total-revenue
    phrase plus one segment name, or a segment-table row that itself names its revenue.
    """
    text = str(item or "")
    low = _norm(f"{text} {category}")
    if any(bad in low for bad in BLOCKED):
        return "", ""
    base, suffix = _split_item(text)
    if suffix and not _is_unit_suffix(suffix) and base in TOTAL_ITEMS:
        return suffix, base
    if not suffix and REVENUE_WORD.search(text) and "segment" in low:
        return _norm(text), ""
    return "", ""


def _is_mix_row(item: Any) -> bool:
    """True when the row says it is the company's own revenue mix.

    Three shapes count: a mix phrase ("revenue contribution", "of turnover"), the
    SEBI "Principal Business Activity: <products>" disclosure, and a product line
    that *is* a turnover share ("Milk turnover %").
    """
    low = _norm(item)
    if any(pattern in low for pattern in MIX_PATTERNS):
        return True
    return low.endswith(" turnover") or low.endswith(" turnover percent")


def _pct_weight(item: Any, category: Any, unit: Any, value: Any) -> float:
    """A percent row is a revenue share only when it is a company revenue-mix line."""
    if str(unit or "").strip() != "%" or value is None:
        return 0.0
    low = _norm(f"{item} {category}")
    if any(bad in low for bad in BLOCKED):
        return 0.0
    # The row itself must say it is a revenue mix; the category alone is not enough,
    # because the extractor files market and end-use statistics under "revenue_mix" too.
    mix = _is_mix_row(item)
    if not mix:
        return 0.0
    # Portfolio words are fine only for the company's own revenue mix: a lender states
    # its housing share as "interest income from housing loans % of revenue".
    if any(bad in _norm(item) for bad in SOFT_BLOCKED) \
            and not (REVENUE_WORD.search(low) and mix):
        return 0.0
    try:
        share = float(value) / 100.0
    except (TypeError, ValueError):
        return 0.0
    return share if 0.0 < share <= 1.0 else 0.0


def _open(path: Path) -> sqlite3.Connection | None:
    if not path.exists():
        return None
    return sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)


def _query(con: sqlite3.Connection | None, sql: str, params: tuple = ()) -> list[tuple]:
    if con is None:
        return []
    try:
        return con.execute(sql, params).fetchall()
    except sqlite3.DatabaseError:
        return []


def load_themes(path: Path) -> dict[str, Any]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return raw.get("themes") or {}


def _theme_of(text: Any, themes: dict[str, Any]) -> str:
    """First theme whose keywords hit and whose ``exclude_keywords`` do not."""
    for theme, cfg in themes.items():
        if _hit(text, cfg.get("exclude_keywords") or []):
            continue
        if _hit(text, cfg.get("keywords") or []):
            return theme
    return ""


def _keywords(themes: dict[str, Any]) -> list[str]:
    return [kw for cfg in themes.values() for kw in (cfg.get("keywords") or [])]


def _fts_query(keywords: list[str]) -> str:
    return " OR ".join('"' + str(kw).replace('"', "") + '"' for kw in keywords)


# ---------------------------------------------------------------------------
# Segment evidence: a theme segment's revenue over the company's total revenue
# ---------------------------------------------------------------------------
def _totals(rows: list[tuple]) -> tuple[dict[tuple, tuple[int, float]], dict[tuple, dict[int, set[float]]]]:
    """Stated total revenue per (doc, period, basis, unit[, piece]) and per unit scale.

    A value carries its base's rank (revenue from operations > total revenue > total
    income), so a page stating two bases keeps the preferred one instead of the larger.
    """
    exact: dict[tuple, tuple[int, float]] = {}
    loose: dict[tuple, dict[int, set[float]]] = {}
    for doc, piece, period, basis, unit, item, value in rows:
        base, suffix = _split_item(item)
        if base not in TOTAL_ITEMS or not _is_unit_suffix(suffix) or not value or value <= 0:
            continue
        rank = TOTAL_RANK[base]
        key = (doc, _norm(period), _norm(basis), _norm(unit))
        current = exact.get(key + (piece,))
        if current is None or (rank, -float(value)) < (current[0], -current[1]):
            exact[key + (piece,)] = (rank, float(value))
        loose.setdefault(key[:3] + (_unit_scale(unit),), {}).setdefault(rank, set()).add(float(value))
    return exact, loose


def _denominator(exact, loose, doc, piece, period, basis, unit) -> float:
    key = (doc, _norm(period), _norm(basis), _norm(unit))
    if exact.get(key + (piece,)):
        return exact[key + (piece,)][1]
    # The manager's rule is same document + period + unit; the page is only a tie-break,
    # so fall back to the document-level total when it is unambiguous.  Prefer revenue
    # from operations, then total revenue, then total income - never the largest.
    per_rank = loose.get(key[:3] + (_unit_scale(unit),)) or {}
    for rank in sorted(per_rank):
        values = per_rank[rank]
        return next(iter(values)) if len(values) == 1 else 0.0
    return 0.0


def _is_revenue_total(base: str) -> bool:
    return base in TOTAL_ITEMS or base.startswith(CONTRACT_BASES)


def _tables(rows: list[tuple]) -> dict[tuple, list[tuple[str, float]]]:
    """One segment-information table's rows, keyed by doc/piece/period/basis/unit/base."""
    out: dict[tuple, list[tuple[str, float]]] = {}
    for doc, piece, period, basis, unit, item, value in rows:
        base, suffix = _split_item(item)
        if base not in TOTAL_ITEMS or not suffix or _is_unit_suffix(suffix) \
                or not value or value <= 0:
            continue
        out.setdefault((doc, piece, _norm(period), _norm(basis), _unit_scale(unit), base),
                       []).append((suffix, float(value)))
    return out


def _siblings(rows: list[tuple[str, float]]) -> dict[str, float]:
    """Distinct business-segment labels only; a repeated label keeps its largest value."""
    out: dict[str, float] = {}
    for label, value in rows:
        if not label or any(bad in label for bad in NON_SEGMENT_LABELS):
            continue
        out[label] = max(out.get(label, 0.0), value)
    return out


def _stated(rows: list[tuple]) -> dict[tuple, list[tuple[str, float]]]:
    """Independently stated revenue figures per (doc, period, basis, unit scale)."""
    out: dict[tuple, list[tuple[str, float]]] = {}
    for doc, piece, period, basis, unit, item, value in rows:
        base, suffix = _split_item(item)
        if not _is_revenue_total(base) or not _is_unit_suffix(suffix) or not value or value <= 0:
            continue
        out.setdefault((doc, _norm(period), _norm(basis), _unit_scale(unit)), []).append(
            (str(item)[:120], float(value)))
    return out


def _reconciled(summed: float, stated: list[tuple[str, float]]) -> tuple[float, str]:
    """(closest stated revenue figure within 1% of ``summed``, its label) or (0.0, "").

    Candidates are each stated total plus the sum of the Ind AS "revenue from
    contract" lines, which are printed apart from each other.  The closest match wins,
    so a near miss does not beat the figure the report actually states.
    """
    candidates = list(stated)
    contract = [(label, value) for label, value in stated if "contract" in _norm(label)]
    for index, (label, value) in enumerate(contract):
        for other_label, other_value in contract[index + 1:]:
            candidates.append((f"{label} + {other_label}", value + other_value))
    best = (0.0, "")
    best_diff = 1.0
    for label, value in candidates:
        diff = abs(summed - value) / value
        if diff <= 0.01 and diff < best_diff:
            best_value, best_label, best_diff = value, label, diff
            best = (best_value, best_label)
    return best


def _segment_sum(siblings: dict[str, float], value: float,
                 stated: list[tuple[str, float]]) -> tuple[float, str]:
    """Theme segment over the summed siblings; only when the sum reconciles (N-segment_sum).

    Rules: one table, >=2 distinct segments, no total/elimination rows, and the sum must
    be within 1% of an independently stated revenue figure in the same document.  That
    reconciliation is also what rejects a parent segment listed alongside its children.
    """
    if len(siblings) < 2 or value <= 0:
        return 0.0, ""
    summed = sum(siblings.values())
    if not summed:
        return 0.0, ""
    figure, label = _reconciled(summed, stated)
    if not figure:
        return 0.0, ""
    return value / summed, f"segment sum {summed:,.2f} reconciles to {label} ({figure:,.2f})"


def _pivot(siblings: dict[str, float], value: float, total: float) -> bool:
    """N6: one segment table, >=3 distinct siblings, sum within 1% of the stated total."""
    if len(siblings) < 3 or not total:
        return False
    if abs(sum(siblings.values()) - total) / total > 0.01:
        return False
    return value >= max(siblings.values())


_LEGAL_WORDS = frozenset(("the", "of", "and", "limited", "ltd", "private", "pvt", "company",
                          "co", "corporation", "corp"))


def _doc_named(ar: sqlite3.Connection | None, doc: int, name: str, symbol: str) -> bool:
    """True when the document's own text names the company (manager rule N1).

    A wrong-file AR is filed under the right company, so ``ar_docs.company`` agrees while
    nothing inside the document does (LAKESHORE doc 127534: "Inadvertently the incorrect
    file of Annual Report was uploaded").  The extracted quote/item text is the only
    in-document text the builder can audit, so the company name or its symbol must appear
    there.
    """
    key = " ".join([word for word in _norm(name).split() if word not in _LEGAL_WORDS][:2])
    text = "(lower(COALESCE(quote,'')) || ' ' || lower(COALESCE(item,'')))"
    if key and _query(ar, f"SELECT 1 FROM ar_facts WHERE doc_id = ? AND {text} LIKE ? LIMIT 1",
                      (doc, f"%{key}%")):
        return True
    token = _norm(symbol)
    if not token:
        return False
    rows = _query(ar, f"SELECT {text} FROM ar_facts WHERE doc_id = ? AND {text} LIKE ? LIMIT 50",
                  (doc, f"%{token}%"))
    return any(token in _norm(row[0]).split() for row in rows)


def _ar_evidence(ar: sqlite3.Connection | None, themes: dict[str, Any], symbols: dict[str, str],
                 names: dict[str, str], blocked_docs: set[int]) -> list[dict[str, Any]]:
    keywords = _keywords(themes)
    if not keywords:
        return []
    # ar_facts has 32M rows: the FTS index picks the keyword rows, then only the matched
    # documents are read for the total-revenue denominator.  The cap truncates the hit set
    # (120,856 rows in 2026-10), so some real rows never reach the build; lifting it needs
    # a stricter industry gate first, because the BRSR "coke and refined petroleum
    # products" wording then admits lubricant blenders (CASTROLIND, GULFOILLUB,
    # PANAMAPET) to `omc_refining` and BRSR reporting-scope lines to `housing_finance`.
    hits = _query(
        ar,
        "SELECT a.doc_id, a.piece, a.isin, a.symbol, a.fiscal_year, a.filed_at, a.category, "
        "a.item, a.value, a.unit, a.period, a.basis FROM ar_facts_fts f "
        "JOIN ar_facts a ON a.rowid = f.rowid "
        "WHERE ar_facts_fts MATCH ? AND a.value IS NOT NULL LIMIT 20000",
        (_fts_query(keywords),),
    )
    doc_ids = sorted({int(r[0]) for r in hits if r[0] is not None})
    if not doc_ids:
        return []
    rows: list[tuple] = []
    # SQLite refuses more than ~999 bound parameters, and a silent empty denominator is
    # exactly the bug this replaces, so chunk instead of one huge IN ().
    for start in range(0, len(doc_ids), 400):
        chunk = doc_ids[start:start + 400]
        marks = ",".join("?" for _ in chunk)
        rows += _query(
            ar,
            "SELECT doc_id, piece, period, basis, unit, item, value FROM ar_facts "
            f"WHERE doc_id IN ({marks}) AND value > 0 AND unit <> '%' "
            "AND (lower(item) LIKE '%revenue%' OR lower(item) LIKE '%turnover%' "
            "OR lower(item) LIKE '%sales%' OR lower(item) LIKE '%income%')",
            tuple(chunk),
        )
    exact, loose = _totals(rows)
    tables = _tables(rows)
    stated = _stated(rows)

    out: list[dict[str, Any]] = []
    for doc, piece, isin, symbol, fiscal_year, filed_at, category, item, value, unit, period, basis in hits:
        if not isin or int(doc) in blocked_docs:
            continue
        theme = _theme_of(f"{item} {category}", themes)
        if not theme:
            continue
        fy_year = int(str(fiscal_year or "")[:4] or 0)
        if not fy_year:
            continue
        # The document's own fiscal year only: the comparative ("FY18") column of an
        # FY19 report is a prior-year figure, not current-year evidence.
        period_years = _years(period)
        if str(period or "").strip() not in ("", "-") and period_years and fy_year not in period_years:
            continue
        unit = str(unit or "")
        weight_source = "segment"
        reconciliation = ""
        if unit.strip() == "%":
            weight = _pct_weight(item, category, unit, value)
            label = _norm(item)
            pivot = False
        else:
            if not _money_unit(unit):
                continue
            label, base = _segment_labels(item, category)
            keywords = themes[theme].get("keywords") or []
            if not label or not _hit(label, keywords) \
                    or _hit(label, themes[theme].get("exclude_keywords") or []):
                continue
            table_key = (doc, piece, _norm(period), _norm(basis), _unit_scale(unit), base)
            siblings = _siblings(tables.get(table_key) or [])
            total = _denominator(exact, loose, doc, piece, period, basis, unit)
            reconciliation = ""
            if total:
                if not value or value <= 0 or float(value) > total:
                    continue
                weight = float(value) / total
            else:
                # No stated total in this document for the period: the segment table's
                # own sum is the denominator, but only when it reconciles.
                weight, reconciliation = _segment_sum(
                    siblings, float(value),
                    stated.get((doc, table_key[2], table_key[3], table_key[4])) or [])
                if weight <= 0:
                    continue
                weight_source = "segment_sum"
                total = sum(siblings.values())
            pivot = _pivot(siblings, float(value), total)
        if weight <= 0:
            continue
        symbols.setdefault(str(isin), str(symbol or ""))
        quote = f"{str(item)[:150]}: {value} {unit}".strip()
        if reconciliation:
            quote = f"{quote}; {reconciliation}"
        out.append({
            "theme": theme, "isin": str(isin), "method": "segment", "fiscal_year": fy_year,
            "valid_from": _date(filed_at), "weight": round(min(weight, 1.0), 6),
            "weight_source": weight_source,
            "evidence_id": f"ar_facts.db:ar_facts:{doc}:{piece}",
            "evidence_quote": quote,
            "pivot": bool(pivot), "_doc": int(doc),
        })
    named: dict[int, bool] = {}
    kept = []
    for item in out:
        doc = item.pop("_doc")
        if doc not in named:
            isin = item["isin"]
            named[doc] = _doc_named(ar, doc, names.get(isin, ""), symbols.get(isin, ""))
        if named[doc]:
            kept.append(item)
    return kept


def _deck_evidence(dk: sqlite3.Connection | None, themes: dict[str, Any],
                   symbols: dict[str, str]) -> list[dict[str, Any]]:
    keywords = _keywords(themes)
    if not keywords:
        return []
    # deck_sources.sha256 is not indexed, so resolve sources through a dict; the
    # FTS index itself matches in ~0.3s and the rowid join costs ~4s.
    sources = {
        str(sha): (isin, symbol, known_at)
        for sha, isin, symbol, known_at in _query(
            dk, "SELECT sha256, isin, symbol, known_at FROM deck_sources")
        if sha
    }
    rows = _query(
        dk,
        "SELECT f.sha256, f.metric, f.raw_number, f.value, f.unit, f.page_no, f.line_no, f.period "
        "FROM facts_metric_fts m JOIN facts f ON f.rowid = m.rowid "
        "WHERE facts_metric_fts MATCH ? AND f.value IS NOT NULL LIMIT 100000",
        (_fts_query(keywords),),
    )
    out = []
    for sha, metric, raw_number, value, unit, page, line, period in rows:
        isin, symbol, known_at = sources.get(str(sha), ("", "", ""))
        if not isin:
            continue
        theme = _theme_of(metric, themes)
        if not theme:
            continue
        # A deck has no denominator row to divide by, so only an explicit share counts.
        weight = _pct_weight(metric, "", unit, value)
        if weight <= 0:
            continue
        known = _date(known_at)
        years = _years(period) or _years(known)
        symbols.setdefault(str(isin), str(symbol or ""))
        out.append({
            "theme": theme, "isin": str(isin), "method": "segment",
            "fiscal_year": max(years) if years else int(known[:4] or 0),
            "valid_from": known, "weight": round(min(weight, 1.0), 6),
            "evidence_id": f"deck_figures.db:facts:{sha}:{page}:{line}",
            "evidence_quote": f"{str(metric)[:120]}: {raw_number} {unit}".strip(),
            "pivot": False,
        })
    return out


def _intervals(evidence: list[dict[str, Any]], themes: dict[str, Any]) -> tuple[list[dict[str, Any]], set[tuple[str, str]]]:
    """One membership row per fiscal year, each valid until the next filed year.

    ``valid_to`` is ``min(next filed year, two fiscal years after this one)``, so a
    weight older than two fiscal years with no newer evidence expires.
    """
    best: dict[tuple[str, str], dict[int, dict[str, Any]]] = {}
    for item in evidence:
        if not item.get("weight") or not item.get("fiscal_year"):
            continue
        theme = themes.get(item["theme"]) or {}
        floor = float(theme.get("min_segment_weight", DEFAULT_MIN_SEGMENT_WEIGHT))
        if float(item["weight"]) < floor:
            continue
        years = best.setdefault((item["theme"], item["isin"]), {})
        current = years.get(item["fiscal_year"])
        if current is None or float(item["weight"]) > float(current["weight"]):
            years[item["fiscal_year"]] = item

    rows: list[dict[str, Any]] = []
    for (theme, isin), years in best.items():
        # One disclosure can state several fiscal periods (a deck's FY25 + FY26 table),
        # so a date carries at most one observation: the most recent fiscal year in it.
        # A row with no disclosure date has no interval: never fall back to the fiscal
        # year end (manager rule N7).
        by_date: dict[str, dict[str, Any]] = {}
        for fy in sorted(years):
            item = years[fy]
            stamp = item["valid_from"]
            if not stamp:
                continue
            if stamp not in by_date or fy > by_date[stamp]["fiscal_year"]:
                by_date[stamp] = {**item, "fiscal_year": fy}
        ordered = sorted(by_date)
        for index, stamp in enumerate(ordered):
            item = by_date[stamp]
            expiry = f"{item['fiscal_year'] + 2}-03-31"
            following = ordered[index + 1] if index + 1 < len(ordered) else ""
            valid_to = min(expiry, following) if following and following > stamp else expiry
            if valid_to <= stamp:
                continue
            rows.append({
                "theme": theme, "isin": isin, "method": "segment",
                "weight_source": item.get("weight_source") or "segment",
                "valid_from": stamp, "valid_to": valid_to,
                "weight": item["weight"], "evidence_id": item["evidence_id"],
                "evidence_quote": item["evidence_quote"], "pivot": item["pivot"],
            })
    return rows, set(best)


# ---------------------------------------------------------------------------
# Unweighted evidence: industry classification and curated seeds
# ---------------------------------------------------------------------------
def _industry_evidence(eq: sqlite3.Connection | None, themes: dict[str, Any],
                       symbols: dict[str, str], listing: dict[str, str]) -> list[dict[str, Any]]:
    rows = _query(
        eq, "SELECT isin, symbol, sector, industry, basic_industry FROM company_industry"
    )
    out = []
    for isin, symbol, sector, industry, basic in rows:
        theme = next(
            (t for t, cfg in themes.items()
             if any(_norm(w) in (_norm(industry), _norm(basic)) for w in (cfg.get("industries") or []))),
            "",
        )
        if not theme or not isin:
            continue
        symbols.setdefault(str(isin), str(symbol or ""))
        out.append({
            "theme": theme, "isin": str(isin), "method": "industry", "weight": None,
            "weight_source": "industry",
            "valid_from": listing.get(str(isin)) or DEFAULT_VALID_FROM,
            "evidence_id": f"equity_intelligence.db:company_industry:{isin}",
            "evidence_quote": f"NSE industry: {sector} / {industry} / {basic}".strip(" /"),
            "pivot": False,
        })
    return out


def _curated_evidence(themes: dict[str, Any], sym_isin: dict[str, str],
                      listing: dict[str, str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Curated seeds as unweighted members; seeds with no ISIN are reported, not dropped."""
    out, unresolved = [], []
    for theme, cfg in themes.items():
        for seed in cfg.get("seeds") or []:
            symbol = str(seed.get("symbol") or "").upper()
            isin = sym_isin.get(symbol) or str(seed.get("isin") or "")
            if not symbol:
                continue
            if not isin:
                unresolved.append({"theme": theme, "symbol": symbol,
                                   "reason": str(seed.get("reason") or "")})
                continue
            out.append({
                "theme": theme, "isin": isin, "method": "curated", "weight": None,
                "weight_source": "curated",
                "valid_from": listing.get(isin) or DEFAULT_VALID_FROM,
                "evidence_id": f"universes.yaml:{theme}.seeds.{symbol}",
                "evidence_quote": str(seed.get("reason") or ""), "pivot": False,
            })
    return out, unresolved


def _subsidiary_evidence(ann: sqlite3.Connection | None, themes: dict[str, Any],
                         sym_isin: dict[str, str], code_isin: dict[str, str]) -> list[dict[str, Any]]:
    rows = _query(
        ann,
        "SELECT NEWSID, SCRIP_CD, symbol, HEADLINE, NEWSSUB, NEWS_DT FROM ann WHERE "
        "lower(HEADLINE) LIKE '%subsidiar%' OR lower(HEADLINE) LIKE '%acquisition%' "
        "OR lower(HEADLINE) LIKE '%joint venture%' OR lower(HEADLINE) LIKE '%amalgamation%' "
        "OR lower(NEWSSUB) LIKE '%subsidiar%' OR lower(NEWSSUB) LIKE '%acquisition%' "
        "OR lower(NEWSSUB) LIKE '%joint venture%'",
    )
    out = []
    for newsid, scrip, symbol, headline, newssub, news_dt in rows:
        theme = _theme_of(f"{headline} {newssub}", themes)
        if not theme:
            continue
        isin = sym_isin.get(str(symbol or "").upper()) or code_isin.get(str(scrip or ""))
        if not isin:
            continue
        out.append({
            "theme": theme, "isin": isin, "method": "subsidiary",
            "valid_from": _date(news_dt),
            "evidence_id": f"bse_announcements.db:ann:{newsid}",
            "evidence_quote": str(headline or newssub)[:180],
        })
    return out


def _pivot_evidence(cc: sqlite3.Connection | None, themes: dict[str, Any]) -> list[dict[str, Any]]:
    keywords = _keywords(themes)
    if not keywords:
        return []
    rows = _query(
        cc,
        "SELECT c.doc_id, c.idx, c.isin, c.filed_at, c.metric, c.statement, c.quote "
        "FROM cc_items_fts f JOIN cc_items c ON c.rowid = f.rowid "
        "WHERE cc_items_fts MATCH ? LIMIT 20000",
        (_fts_query(keywords),),
    )
    out = []
    for doc, idx, isin, filed_at, metric, statement, quote in rows:
        text = f"{metric} {statement} {quote}"
        theme = _theme_of(text, themes)
        if not theme or not isin or not _hit(text, list(ENTRY_WORDS)):
            continue
        out.append({
            "theme": theme, "isin": str(isin), "method": "stated_pivot",
            "valid_from": _date(filed_at),
            "evidence_id": f"concall_facts.db:cc_items:{doc}:{idx}",
            "evidence_quote": str(quote or statement or metric)[:180],
        })
    return out


# ---------------------------------------------------------------------------
# Rebuild + diff
# ---------------------------------------------------------------------------
def _company_maps(eq: sqlite3.Connection | None):
    sym_isin, code_isin, symbols, listing, industry = {}, {}, {}, {}, {}
    names: dict[str, str] = {}
    for isin, nse, bse, name in _query(
        eq, "SELECT isin, nse_symbol, bse_code, company_name FROM master_companies"
    ):
        isin = str(isin or "")
        if not isin:
            continue
        if name:
            names.setdefault(isin, str(name))
        for key in (nse, name):
            if key:
                sym_isin.setdefault(str(key).upper(), isin)
        if bse:
            code_isin.setdefault(str(bse), isin)
        if nse and isin not in symbols:
            symbols[isin] = str(nse)
    for isin, symbol, sector, label, basic, listed in _query(
        eq, "SELECT isin, symbol, sector, industry, basic_industry, listing_date FROM company_industry"
    ):
        if not isin:
            continue
        if symbol and isin not in symbols:
            symbols[str(isin)] = str(symbol)
        if symbol:
            sym_isin.setdefault(str(symbol).upper(), str(isin))
        if listed and _date(listed):
            listing[str(isin)] = _date(listed)
        industry[str(isin)] = (str(label or ""), str(basic or ""), str(sector or ""))
    return sym_isin, code_isin, symbols, listing, industry, names


def _rank(item: dict[str, Any]) -> tuple:
    return (METHOD_RANK[item["method"]], item.get("weight") is not None,
            float(item.get("weight") or 0.0))


def _excluded(themes: dict[str, Any], industry: dict[str, tuple[str, ...]]) -> set[tuple[str, str]]:
    """(theme, ISIN) pairs whose NSE industry disqualifies them: a bank is not a lender theme."""
    out: set[tuple[str, str]] = set()
    for isin, labels in industry.items():
        flat = [_norm(label) for label in labels]
        for theme, cfg in themes.items():
            wanted = cfg.get("exclude_industries") or []
            if any(_norm(word) in flat for word in wanted):
                out.add((theme, isin))
    return out


def _industry_gate(themes: dict[str, Any],
                   industry: dict[str, tuple[str, ...]]) -> set[tuple[str, str]]:
    """(theme, ISIN) pairs whose NSE industry keeps a segment weight eligible.

    A theme may require an industry family (``segment_industry_keywords``) before a
    revenue-mix row counts, so a lubricant blender's "Petroleum Products sales turnover"
    is not an OMC weight just because the words match.
    """
    out: set[tuple[str, str]] = set()
    for theme, cfg in themes.items():
        family = cfg.get("segment_industry_keywords") or []
        if not family:
            continue
        for isin, labels in industry.items():
            if any(_hit(label, family) for label in labels):
                out.add((theme, isin))
    return out


def _quarantined_docs(eq: sqlite3.Connection | None) -> set[int]:
    """ar_facts document ids keyed in ``substrate_quarantine`` (AGENTS.md rule 13)."""
    docs: set[int] = set()
    for row_key, in _query(eq, "SELECT row_key FROM substrate_quarantine"
                                " WHERE table_name IN ('ar_facts', 'ar_docs')"):
        head = str(row_key or "").split(":")[0].strip()
        if head.isdigit():
            docs.add(int(head))
    return docs


def _unweighted_row(item: dict[str, Any], valid_from: str, valid_to: str | None) -> dict[str, Any]:
    return {
        "theme": item["theme"], "isin": item["isin"], "method": item["method"],
        "weight_source": item["weight_source"], "valid_from": valid_from, "valid_to": valid_to,
        "weight": None, "evidence_id": item["evidence_id"],
        "evidence_quote": item["evidence_quote"], "pivot": False,
    }


def _chain(rows: list[dict[str, Any]], best: dict[tuple[str, str], dict[str, Any]]
           ) -> list[dict[str, Any]]:
    """Weighted intervals with an unweighted row filling every gap between them.

    While a weight applies the company is a weighted member; before, between and after
    the weighted intervals the industry / curated signal applies, so the (theme, ISIN)
    chain has no hole.  ``valid_to`` is half-open, so a handover is exact.

    A chain with no unweighted row (no NSE industry match, no curated seed) cannot be
    filled; there the last measurement carries forward to the next filed disclosure
    only, and still expires two fiscal years after its own (N4/N7).
    """
    weighted: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        weighted.setdefault((row["theme"], row["isin"]), []).append(row)
    out: list[dict[str, Any]] = []
    for key in sorted(set(weighted) | set(best)):
        chain = sorted(weighted.get(key) or [], key=lambda r: r["valid_from"])
        fallback = best.get(key)
        if fallback is None:
            for current, following in zip(chain, chain[1:]):
                if current["valid_to"] and current["valid_to"] < following["valid_from"]:
                    current["valid_to"] = following["valid_from"]
            out.extend(chain)
            continue
        # Coverage starts when the company first appears: its listing date or its first
        # measured weight, whichever is earlier (an SME's industry row can postdate its
        # first annual report).
        cursor = min([fallback["valid_from"]] + [r["valid_from"] for r in chain[:1]])
        for row in chain:
            if row["valid_from"] > cursor:
                out.append(_unweighted_row(fallback, cursor, row["valid_from"]))
            cursor = max(cursor, row["valid_to"])
            out.append(row)
        out.append(_unweighted_row(fallback, cursor, None))
    return out


def build(data_root: Path, themes_path: Path) -> dict[str, Any]:
    themes = load_themes(themes_path)
    eq_source = _open(data_root / "equity_intelligence.db")
    sym_isin, code_isin, symbols, listing, industry, names = _company_maps(eq_source)

    ar = _open(data_root / "ar_facts.db")
    dk = _open(data_root / "deck_figures.db")
    ann = _open(data_root / "bse_announcements.db")
    cc = _open(data_root / "concall_facts.db")
    try:
        segment = (_ar_evidence(ar, themes, symbols, names, _quarantined_docs(eq_source))
                   + _deck_evidence(dk, themes, symbols))
        curated, unresolved = _curated_evidence(themes, sym_isin, listing)
        evidence = (_industry_evidence(eq_source, themes, symbols, listing) + curated)
        candidates = (_subsidiary_evidence(ann, themes, sym_isin, code_isin)
                      + _pivot_evidence(cc, themes))
    finally:
        for con in (eq_source, ar, dk, ann, cc):
            if con is not None:
                con.close()

    excluded = _excluded(themes, industry)
    gate = _industry_gate(themes, industry)
    segment = [s for s in segment if (s["theme"], s["isin"]) not in excluded
               and (not themes[s["theme"]].get("segment_industry_keywords")
                    or (s["theme"], s["isin"]) in gate)]
    rows, _weighted = _intervals(segment, themes)
    # Where a measured weight expires, the unweighted signal takes over: the company is
    # still an OMC by industry classification even when no current revenue share exists.
    best: dict[tuple[str, str], dict[str, Any]] = {}
    for item in evidence:
        key = (item["theme"], item["isin"])
        current = best.get(key)
        if current is None or _rank(item) > _rank(current):
            best[key] = item
    rows = _chain(rows, best)
    for item in rows:
        item["symbol"] = symbols.get(item["isin"], "")
    rows.sort(key=lambda r: (r["theme"], -(float(r["weight"] or 0.0)),
                             -METHOD_RANK.get(r["method"], 0), r["isin"], r["valid_from"]))
    candidates.sort(key=lambda c: (c["theme"], c["isin"], c["valid_from"]))
    return {"rows": rows, "candidates": candidates, "unresolved": unresolved,
            "themes": themes}


def _existing(con: sqlite3.Connection) -> dict[tuple[str, str], tuple]:
    try:
        return {(str(r[0]), str(r[1])): tuple(r) for r in con.execute(
            "SELECT theme, isin, valid_from, valid_to, weight, method, pivot FROM universe_membership")}
    except sqlite3.DatabaseError:
        return {}


def _open_ended(valid_to: Any) -> bool:
    return valid_to in (None, "")


SCHEMA = (
    "CREATE TABLE IF NOT EXISTS universe_membership("
    " theme TEXT NOT NULL, isin TEXT NOT NULL, symbol TEXT, valid_from TEXT NOT NULL,"
    " valid_to TEXT, weight REAL, weight_source TEXT, method TEXT, evidence_id TEXT,"
    " evidence_quote TEXT, pivot INTEGER DEFAULT 0, built_at TEXT NOT NULL,"
    " PRIMARY KEY(theme, isin, valid_from));"
    "CREATE INDEX IF NOT EXISTS ix_universe_membership_theme"
    " ON universe_membership(theme, valid_from, valid_to);"
    "CREATE TABLE IF NOT EXISTS universe_candidates("
    " theme TEXT NOT NULL, isin TEXT NOT NULL, symbol TEXT, method TEXT NOT NULL,"
    " valid_from TEXT, evidence_id TEXT, evidence_quote TEXT, built_at TEXT NOT NULL,"
    " PRIMARY KEY(theme, isin, method, evidence_id));"
    "CREATE TABLE IF NOT EXISTS universe_membership_runs("
    " run_id TEXT PRIMARY KEY, built_at TEXT NOT NULL, joins TEXT NOT NULL,"
    " exits TEXT NOT NULL, pivots TEXT NOT NULL, report_json TEXT NOT NULL);"
)


def write(con: sqlite3.Connection, rows: list[dict[str, Any]], candidates: list[dict[str, Any]],
          unresolved: list[dict[str, Any]], built_at: str) -> dict[str, Any]:
    old = _existing(con)
    # The latest row per (theme, ISIN) is the one the diff compares.
    latest: dict[tuple[str, str], dict[str, Any]] = {}
    for row in sorted(rows, key=lambda r: (r["theme"], r["isin"], r["valid_from"])):
        latest[(row["theme"], row["isin"])] = row
    joins = sorted(k for k in latest if k not in old)
    exits = sorted(k for k in old if k not in latest
                   or (_open_ended(old[k][3]) and not _open_ended(latest[k].get("valid_to"))))
    pivots = sorted(k for k, r in latest.items()
                    if r["pivot"] and not (len(old.get(k, ())) > 6 and old[k][6]))
    run_id = dt.datetime.now().strftime("%Y%m%dT%H%M%S%f")
    con.executescript(SCHEMA)
    columns = {str(r[1]) for r in con.execute("PRAGMA table_info(universe_membership)")}
    if "weight_source" not in columns:  # a build from before weights had a source
        con.execute("ALTER TABLE universe_membership ADD COLUMN weight_source TEXT")
    with con:
        con.execute("DELETE FROM universe_membership")
        con.execute("DELETE FROM universe_candidates")
        con.executemany(
            "INSERT INTO universe_membership(theme, isin, symbol, valid_from, valid_to, weight,"
            " weight_source, method, evidence_id, evidence_quote, pivot, built_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            [(r["theme"], r["isin"], r.get("symbol") or "", r["valid_from"], r.get("valid_to"),
              None if r.get("weight") is None else float(r["weight"]),
              r["weight_source"], r["method"], r.get("evidence_id") or "",
              r.get("evidence_quote") or "", 1 if r.get("pivot") else 0, built_at) for r in rows],
        )
        con.executemany(
            "INSERT OR REPLACE INTO universe_candidates(theme, isin, symbol, method, valid_from,"
            " evidence_id, evidence_quote, built_at) VALUES (?,?,?,?,?,?,?,?)",
            [(c["theme"], c["isin"], c.get("symbol") or "", c["method"], c["valid_from"],
              c["evidence_id"], c["evidence_quote"], built_at) for c in candidates],
        )
        report = {"built_at": built_at, "members": len(rows), "themes": {},
                  "joins": len(joins), "exits": len(exits), "pivots": len(pivots),
                  "candidates": len(candidates), "unresolved_seeds": unresolved}
        for r in rows:
            report["themes"].setdefault(r["theme"], []).append(_public(r))
        con.execute(
            "INSERT INTO universe_membership_runs(run_id, built_at, joins, exits, pivots, report_json)"
            " VALUES (?,?,?,?,?,?)",
            (run_id, built_at, json.dumps(joins), json.dumps(exits),
             json.dumps(pivots), json.dumps(report)),
        )
    return {"run_id": run_id, "members": len(rows), "joins": len(joins), "exits": len(exits),
            "pivots": len(pivots), "candidates": len(candidates), "themes": report["themes"]}


def _public(row: dict[str, Any]) -> dict[str, Any]:
    return {"symbol": row.get("symbol"), "isin": row["isin"], "weight": row.get("weight"),
            "weight_source": row.get("weight_source") or row["method"], "method": row["method"],
            "since": row["valid_from"], "until": row.get("valid_to"),
            "evidence_id": row.get("evidence_id"), "evidence_quote": row.get("evidence_quote"),
            "pivot": bool(row.get("pivot"))}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", help="target equity_intelligence.db (default: <data-root>/equity_intelligence.db)")
    parser.add_argument("--data-root", default=os.environ.get("REALITY_DATA_ROOT"),
                        help="source data directory (default: REALITY_DATA_ROOT)")
    parser.add_argument("--themes", default=str(DEFAULT_THEMES))
    parser.add_argument("--theme", action="append", default=None,
                        help="only print these themes in the dry-run report (repeatable)")
    parser.add_argument("--dry-run", action="store_true", help="print the result, write nothing")
    args = parser.parse_args(argv)

    data_root = Path(args.data_root or ROOT / "reality_engine" / "data")
    target = Path(args.db or data_root / "equity_intelligence.db")
    built = build(data_root, Path(args.themes))
    rows = built["rows"]
    built_at = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    report = {"run_id": None, "built_at": built_at, "members": len(rows), "themes": {},
              "joins": 0, "exits": 0, "pivots": 0, "candidates": len(built["candidates"]),
              "unresolved_seeds": built["unresolved"], "dry_run": bool(args.dry_run),
              "target": str(target), "theme_count": len(built["themes"])}
    for r in rows:
        report["themes"].setdefault(r["theme"], []).append(_public(r))
    only = set(args.theme or ())
    for theme, members in report["themes"].items():
        members.sort(key=lambda m: (-(m["weight"] or 0), m["symbol"] or ""))
        if not only:
            del members[40:]
        elif theme not in only:
            report["themes"][theme] = []

    if args.dry_run:
        print(json.dumps(report, indent=1, default=str))
        return 0
    target.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(target, timeout=300)
    try:
        written = write(con, rows, built["candidates"], built["unresolved"], built_at)
    finally:
        con.close()
    report.update({k: written[k] for k in ("run_id", "members", "joins", "exits", "pivots", "candidates")})
    print(json.dumps({k: v for k, v in report.items() if k != "themes"}, default=str))
    print("members per theme:", {t: len(v) for t, v in written["themes"].items()})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
