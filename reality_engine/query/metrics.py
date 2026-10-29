"""Typed reads over the pilot-60 extraction store (``metric_state``).

The build is ``reality_engine/pilot/extract60.py``: eleven factual tables filled
from targeted passages with quote/page/known_at.  This module is the read side
the planners use, so a master-bank case blocked on one of those tables answers
from the store instead of naming it missing.

Point-in-time rule: every row carries ``known_at`` (the statement's own filing
date), and every read filters ``known_at <= as_of`` in SQL.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
# The controller copies the build to the SSD pilot folder; a fresh worktree build stays in .tmp.
DEFAULT = REPO / "reality_engine" / "data" / "pilot" / "pilot60" / "extract_pilot60.db"
BUILD = REPO / ".tmp" / "pilot60" / "extract_pilot60.db"

#: table -> (value column, unit, item label expression) for SCREEN.
SCREEN_VALUE = {
    "company_operating_metrics": ("value", "unit", "metric"),
    "company_segment_pnl": ("value_cr", "INR_CRORE", "segment"),
    "company_cost_structure": ("share_of_cogs_pct", "PCT", "input_key"),
    "order_intake": ("order_book_cr", "INR_CRORE", "'order book'"),
    "order_book_contract": ("value_cr", "INR_CRORE", "counterparty"),
    "company_capacity_utilisation": ("utilisation_pct", "PCT", "product"),
    "capex_project": ("capex_cr", "INR_CRORE", "project"),
    "company_price_revision": ("revision_pct", "PCT", "product"),
    "company_debt_mix": ("amount_cr", "INR_CRORE", "bucket"),
    "rating_action": ("amount_cr", "INR_CRORE", "instrument"),
    "supply_link": ("share_of_cost_pct", "PCT", "relation"),
}

#: Which held table a question is about, most specific first.  The extraction
#: tables overlap on vocabulary ("capacity" / "capex"), so order matters.
SIGNALS: tuple[tuple[str, str], ...] = (
    ("rating_action", r"\b(rating action|credit rating|rated|re-?affirm|reaffirm|outlook|"
                      r"upgrade|downgrade|crisil|icra|care ratings|india ratings|brickwork)\b"),
    ("company_price_revision", r"\b(price hike|price increase|price cut|price revision|"
                              r"revision in price|revised price|mrp)\b"),
    ("order_book_contract", r"\b(order win|order wins|awarded|letter of award|\bloa\b|"
                            r"purchase order|work order|contract worth|bagged|secured)\b"),
    ("order_intake", r"\b(order book|order intake|order inflow|book[- ]to[- ]bill|"
                     r"orders received|new orders|order intake)\b"),
    ("company_capacity_utilisation", r"\b(utilisation|utilization|capacity addition|installed "
                                     r"capacity|production|plant capacity|throughput)\b"),
    ("capex_project", r"\b(capex|capital expenditure|commissioning|commissioned|greenfield|"
                      r"brownfield|expansion project)\b"),
    ("company_debt_mix", r"\b(debt mix|borrowing mix|maturity profile|repricing|"
                         r"fixed rate|floating rate|debt maturity)\b"),
    ("company_segment_pnl", r"\b(segment|segments|vertical|business vertical|jlr)\b"),
    ("company_operating_metrics", r"\b(stores?|same[- ]store|sites?|subscribers?|arpu|"
                                  r"volumes?|tonnes|throughput|units sold|market share|"
                                  r"per tonne|per store)\b"),
    ("supply_link", r"\b(supplier|supplies|sources? from|customer|related part|lives? from)\b"),
    ("company_cost_structure", r"\b(cost structure|input cost|raw material|"
                               r"share of cost|cogs)\b"),
)
#: The router's metric token also points at a table when the words are generic.
METRIC_TABLE = {"segment": ["company_segment_pnl"], "order": ["order_intake"],
                "capacity": ["company_capacity_utilisation", "capex_project"],
                "debt": ["company_debt_mix"], "rating": ["rating_action"],
                "pricing": ["company_price_revision"]}


def path() -> Path | None:
    override = os.environ.get("REALITY_EXTRACT_DB")
    if override:
        candidate = Path(override)
        return candidate if candidate.is_file() else None
    for candidate in (DEFAULT, BUILD):
        if candidate.is_file():
            return candidate
    return None


def held(ctx: Any) -> dict[str, int]:
    """table -> row count, from the store this context is pointed at ({} when absent)."""
    try:
        con = ctx.sqlite("metric_state")
    except Exception:  # noqa: BLE001 - no store is a degraded path, never a crash
        return {}
    out = {}
    for table in SCREEN_VALUE:
        try:
            row = con.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()
            out[table] = int(row["n"] if row and "n" in row.keys() else (row[0] if row else 0))
        except Exception:  # noqa: BLE001
            continue
    return out


def tables_for(question: str, metric: str | None = None) -> list[str]:
    low = (question or "").lower()
    found = [table for table, pattern in SIGNALS if re.search(pattern, low)]
    found += [t for t in METRIC_TABLE.get(metric or "", []) if t not in found]
    return found


def _rows(sql: str, params: tuple, ctx: Any) -> list[dict[str, Any]]:
    try:
        return ctx.rows("metric_state", sql, params)
    except Exception:  # noqa: BLE001
        return []


def _fact(store: str, item: str, value: Any, unit: str, period: str | None,
          known_at: str | None, doc_id: Any, page: Any = None,
          quote: str | None = None) -> dict[str, Any]:
    """Same shape as ``planners.facts._row`` so the assembly needs no branch."""
    return {"store": store, "item": item, "value": value, "unit": unit or "",
            "period": period, "known_at": known_at, "doc_id": doc_id, "page": page,
            "quote": (quote or "")[:400] or None, "context": None,
            "ref": f"{store}:{doc_id}{f'#{page}' if page else ''}"}


def facts_rows(ctx: Any, isin: str, as_of: str, question: str,
               metric: str | None = None, period: tuple[str | None, str | None] = (None, None),
               limit: int = 12) -> list[dict[str, Any]]:
    """Numeric facts for one ISIN from the extraction tables the question names."""
    wanted = tables_for(question, metric)
    if not wanted:
        return []
    where_period = ""
    params_period: list[Any] = []
    if period[0] and period[1]:
        where_period = " AND period_end >= ? AND period_end <= ?"
        params_period = [period[0], period[1]]
    out: list[dict[str, Any]] = []
    for table in wanted:
        if table in ("company_segment_pnl",):
            rows = _rows(
                "SELECT segment, period_end, metric, basis, value_cr, doc_id, page, known_at, "
                f"quote FROM company_segment_pnl WHERE isin = ? AND known_at <= ?{where_period} "
                "ORDER BY period_end DESC LIMIT ?",
                tuple([isin, as_of] + params_period + [limit]), ctx)
            out += [_fact("metric_state", f"{r['segment']} segment {r['metric']}", r["value_cr"],
                          "INR_CRORE", r["period_end"], r["known_at"], r["doc_id"], r["page"],
                          r["quote"]) for r in rows]
        elif table == "company_operating_metrics":
            rows = _rows(
                "SELECT metric, period_end, value, unit, source_doc_id, page, known_at, quote "
                f"FROM company_operating_metrics WHERE isin = ? AND known_at <= ?{where_period} "
                "ORDER BY period_end DESC LIMIT ?",
                tuple([isin, as_of] + params_period + [limit]), ctx)
            out += [_fact("metric_state", r["metric"], r["value"], r["unit"] or "",
                          r["period_end"], r["known_at"], r["source_doc_id"], r["page"],
                          r["quote"]) for r in rows]
        elif table == "order_intake":
            rows = _rows(
                "SELECT period_end, intake_cr, order_book_cr, book_to_bill, source_doc_id, page, "
                f"known_at, quote FROM order_intake WHERE isin = ? AND known_at <= ?{where_period} "
                "ORDER BY period_end DESC LIMIT ?",
                tuple([isin, as_of] + params_period + [limit]), ctx)
            for r in rows:
                for label, value, unit in (("order intake", r["intake_cr"], "INR_CRORE"),
                                           ("order book", r["order_book_cr"], "INR_CRORE"),
                                           ("book to bill", r["book_to_bill"], "X")):
                    if value is not None:
                        out.append(_fact("metric_state", label, value, unit, r["period_end"],
                                         r["known_at"], r["source_doc_id"], r["page"], r["quote"]))
        elif table == "company_capacity_utilisation":
            rows = _rows(
                "SELECT product, period_end, capacity, capacity_unit, utilisation_pct, production, "
                f"source_doc_id, page, known_at, quote FROM company_capacity_utilisation "
                f"WHERE isin = ? AND known_at <= ?{where_period} "
                "ORDER BY period_end DESC LIMIT ?",
                tuple([isin, as_of] + params_period + [limit]), ctx)
            for r in rows:
                if r["utilisation_pct"] is not None:
                    out.append(_fact("metric_state", f"{r['product']} utilisation",
                                     r["utilisation_pct"], "PCT", r["period_end"], r["known_at"],
                                     r["source_doc_id"], r["page"], r["quote"]))
                if r["capacity"] is not None:
                    out.append(_fact("metric_state", f"{r['product']} capacity", r["capacity"],
                                     r["capacity_unit"] or "", r["period_end"], r["known_at"],
                                     r["source_doc_id"], r["page"], r["quote"]))
        elif table == "company_debt_mix":
            rows = _rows(
                "SELECT bucket, period_end, amount_cr, rate_pct, doc_id, page, known_at, quote "
                f"FROM company_debt_mix WHERE isin = ? AND known_at <= ?{where_period} "
                "ORDER BY period_end DESC LIMIT ?",
                tuple([isin, as_of] + params_period + [limit]), ctx)
            for r in rows:
                if r["amount_cr"] is not None:
                    out.append(_fact("metric_state", f"{r['bucket']} borrowing", r["amount_cr"],
                                     "INR_CRORE", r["period_end"], r["known_at"], r["doc_id"],
                                     r["page"], r["quote"]))
        elif table == "capex_project":
            rows = _rows(
                "SELECT project, announced_on, capex_cr, status, source_doc_id, page, known_at, "
                f"quote FROM capex_project WHERE isin = ? AND known_at <= ? "
                "ORDER BY announced_on DESC LIMIT ?", (isin, as_of, limit), ctx)
            out += [_fact("metric_state", r["project"], r["capex_cr"], "INR_CRORE",
                          r["announced_on"], r["known_at"], r["source_doc_id"], r["page"],
                          r["quote"]) for r in rows if r["capex_cr"] is not None]
        elif table == "company_price_revision":
            rows = _rows(
                "SELECT product, announced_on, direction, revision_pct, source_doc_id, page, "
                f"known_at, quote FROM company_price_revision WHERE isin = ? AND known_at <= ? "
                "ORDER BY announced_on DESC LIMIT ?", (isin, as_of, limit), ctx)
            out += [_fact("metric_state", f"{r['product']} price {r['direction']}",
                          r["revision_pct"], "PCT", r["announced_on"], r["known_at"],
                          r["source_doc_id"], r["page"], r["quote"])
                    for r in rows if r["revision_pct"] is not None]
    return out


def evidence_rows(ctx: Any, isin: str, as_of: str, question: str,
                  limit: int = 6) -> list[dict[str, Any]]:
    """Passages from the extraction tables, in the chunks_v3 passage shape."""
    wanted = tables_for(question)
    if not wanted:
        return []
    out = []
    for table in wanted:
        if table not in ("rating_action", "company_price_revision", "supply_link",
                         "order_book_contract", "company_cost_structure"):
            continue
        if table == "rating_action":
            rows = _rows(
                "SELECT action_date AS date, agency, instrument, rating, outlook, direction, "
                "amount_cr, quote, page, known_at FROM rating_action "
                "WHERE isin = ? AND known_at <= ? ORDER BY action_date DESC LIMIT ?",
                (isin, as_of, limit), ctx)
            for r in rows:
                out.append({"store": "metric_state", "doc_id": r["instrument"] or "rating",
                            "doc_type": "rating_action", "date": r["known_at"], "page": r["page"],
                            "section": f"{r['agency'] or ''} {r['direction'] or ''}".strip(),
                            "speaker": None, "speaker_role": None, "quote": r["quote"] or "",
                            "header": f"{r['agency'] or ''} {r['rating'] or ''} "
                                      f"{r['outlook'] or ''} {r['date']}"})
        elif table == "company_price_revision":
            rows = _rows(
                "SELECT product, announced_on, direction, revision_pct, basis_text, quote, page, "
                "known_at FROM company_price_revision WHERE isin = ? AND known_at <= ? "
                "ORDER BY announced_on DESC LIMIT ?", (isin, as_of, limit), ctx)
            for r in rows:
                out.append({"store": "metric_state", "doc_id": r["product"] or "price",
                            "doc_type": "price_revision", "date": r["known_at"], "page": r["page"],
                            "section": f"price {r['direction']}", "speaker": None,
                            "speaker_role": None,
                            "quote": " ".join(str(x) for x in (r["basis_text"], r["quote"])
                                              if x)[:600],
                            "header": f"{r['product']} price {r['direction']} "
                                      f"{r['announced_on']}"})
        elif table == "supply_link":
            rows = _rows(
                "SELECT src_isin, dst_isin, relation, share_of_cost_pct, evidence_quote, known_at "
                "FROM supply_link WHERE (src_isin = ? OR dst_isin = ?) AND known_at <= ? "
                "ORDER BY known_at DESC LIMIT ?", (isin, isin, as_of, limit), ctx)
            for r in rows:
                out.append({"store": "metric_state", "doc_id": r["dst_isin"] or "link",
                            "doc_type": "supply_link", "date": r["known_at"], "page": None,
                            "section": r["relation"], "speaker": None, "speaker_role": None,
                            "quote": r["evidence_quote"] or "",
                            "header": f"{r['relation']} {r['dst_isin']}"})
        elif table == "order_book_contract":
            rows = _rows(
                "SELECT counterparty, value_cr, price_basis, signed_on, quote, page, known_at "
                "FROM order_book_contract WHERE isin = ? AND known_at <= ? "
                "ORDER BY signed_on DESC LIMIT ?", (isin, as_of, limit), ctx)
            for r in rows:
                out.append({"store": "metric_state", "doc_id": r["counterparty"] or "contract",
                            "doc_type": "order_book_contract", "date": r["known_at"],
                            "page": r["page"], "section": r["price_basis"] or "contract",
                            "speaker": None, "speaker_role": None, "quote": r["quote"] or "",
                            "header": f"{r['counterparty'] or ''} {r['value_cr']} cr "
                                      f"{r['signed_on'] or ''}"})
        elif table == "company_cost_structure":
            rows = _rows(
                "SELECT input_key, period_end, amount_cr, share_of_cogs_pct, quote, page, known_at "
                "FROM company_cost_structure WHERE isin = ? AND known_at <= ? "
                "ORDER BY period_end DESC LIMIT ?", (isin, as_of, limit), ctx)
            for r in rows:
                out.append({"store": "metric_state", "doc_id": r["input_key"],
                            "doc_type": "cost_structure", "date": r["known_at"], "page": r["page"],
                            "section": "cost structure", "speaker": None, "speaker_role": None,
                            "quote": r["quote"] or "",
                            "header": f"{r['input_key']} {r['amount_cr']} cr "
                                      f"{r['period_end']}"})
    return out


def screen(ctx: Any, question: str, as_of: str, table: str,
           limit: int = 15) -> list[dict[str, Any]]:
    """Rank held ISINs on one extraction table's value column, PIT-filtered."""
    value_col, unit, item_expr = SCREEN_VALUE.get(table) or (None, None, None)
    if not value_col:
        return []
    rows = _rows(
        f"SELECT isin, {item_expr} AS item, {value_col} AS value, period_end AS period, "
        f"known_at, doc_id, page FROM {table} WHERE known_at <= ? AND {value_col} IS NOT NULL "
        f"ORDER BY {value_col} DESC LIMIT ?", (as_of, limit * 4), ctx)
    seen: set[str] = set()
    out = []
    for row in rows:
        if row["isin"] in seen:
            continue
        seen.add(row["isin"])
        out.append({"isin": row["isin"], "item": row["item"], "value": row["value"],
                    "unit": unit, "period": row["period"], "known_at": row["known_at"],
                    "ref": f"metric_state:{table}:{row['doc_id']}#{row['page']}"})
        if len(out) >= limit:
            break
    return out
