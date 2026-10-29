"""FACTS: one metric (+period) from every stamped fact store, PIT-filtered in SQL.

Stores read: ``results_xbrl`` (filings + long facts), ``ar_facts``,
``deck_figures`` (pages -> facts), ``concall_facts`` (cc_docs -> cc_items).
A missing metric is reported as a schema gap, an empty company as no-doc.
"""
from __future__ import annotations

import re
from typing import Any

from reality_engine.query import compute

from . import envelope, fmt_num, in_period, isin_of, normalise_label, terms_clause

CHECKED = ["results_xbrl.filings", "results_xbrl.facts", "ar_facts.ar_facts",
           "facts_pilot.company_segment_pnl",
           "deck_figures.pages", "deck_figures.facts", "concall_facts.cc_items"]

PRICE_METRICS = {"cagr", "return", "range", "gap", "rsi", "delivery"}

CONCEPT_TERMS: dict[str, tuple[str, ...]] = {
    "segment": ("%Segment%",),
    "revenue": ("%Revenue%", "%Income%"),
    "pat": ("%ProfitLoss%", "%Profit%", "%ProfitAfterTax%"),
    "ebitda": ("%Ebitda%", "%OperatingProfit%", "%ProfitBefore%"),
    "eps": ("%EarningsLossPerShare%",),
    "net_npa": ("%NonPerforming%", "%NPA%"),
    "margin": ("%Margin%",),
    "dso": ("%Receivable%", "%Debtor%"),
    # The operating cash flow line is the concept; "%CashFlow%" alone also pulls
    # investing/financing lines, which carry the word but not the number asked.
    "cfo": ("%CashFlowsFromUsedInOperatingActivities%", "%CashFlowsFromUsedInOperations%",
            "%CashFlowFromOperating%"),
    "order_book": ("%Order%",),
    "capacity": ("%Capacity%",),
    "capex": ("%PropertyPlantAndEquipment%", "%CapitalExpenditure%", "%CapitalWork%"),
    "dividend": ("%Dividend%",),
    "working_capital": ("%Inventor%", "%TradeReceivable%", "%TradePayable%",
                        "%Receivable%", "%Payable%"),
    "promoter": ("%Shareholding%",),
    "valuation": ("%EarningsLossPerShare%", "%PaidUp%", "%FaceValue%"),
    "guidance": ("%Guidance%",),
    "audit": ("%Audit%", "%Opinion%"),
}

#: XBRL concept -> the row label the answer contract shows.  The camel-case split
#: is not a label: "PurchaseOfPropertyPlantAndEquipment..." answers nothing ("capex"
#: is the word the ask uses), and "PercentageOfNpa" states neither "net" nor "%".
CONCEPT_LABELS: dict[str, str] = {
    "PercentageOfNpa": "Net NPA %",
    "PercentageOfGrossNpa": "Gross NPA %",
    "NonPerformingAssets": "Net NPA (amount)",
    "GrossNonPerformingAssets": "Gross NPA (amount)",
    "PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities":
        "Capex (purchase of property, plant and equipment)",
    "PurchaseOfPropertyPlantAndEquipmentCapitalWorkInProgress": "Capex (capital work in progress)",
    "CashFlowsFromUsedInOperatingActivities": "Cash flow from operations",
    "CashFlowsFromUsedInOperations": "Cash flow from operations",
    "DividendsPaidClassifiedAsFinancingActivities": "Dividends paid (cash flow statement)",
    "DividendPerShare": "Dividend per share",
    "SegmentRevenue": "Segment revenue (total)",
    "SegmentRevenueFromOperations": "Segment revenue (total)",
    "RevenueFromOperations": "Revenue from operations",
    "ProfitLossForPeriod": "Profit after tax",
    "ProfitLossFromOrdinaryActivitiesAfterTax": "Profit after tax",
    "ProfitBeforeTax": "Profit before tax",
}
#: Concepts stated as a fraction of one (unit "pure") and shown as a percentage.
PERCENT_CONCEPTS = {"PercentageOfNpa", "PercentageOfGrossNpa"}

TEXT_TERMS: dict[str, tuple[str, ...]] = {
    "segment": ("segment", "business mix", "vertical"),
    "revenue": ("revenue", "turnover", "sales", "income"),
    "pat": ("profit", "pat", "net profit"),
    "ebitda": ("ebitda", "operating profit"),
    "eps": ("eps", "earnings per share"),
    "net_npa": ("npa", "non performing", "non-performing"),
    "margin": ("margin",),
    "dso": ("receivable", "debtor", "collection"),
    "cfo": ("cash flow", "cfo"),
    "order_book": ("order book", "orderbook", "orders"),
    "capacity": ("capacity", "utilisation", "utilization"),
    "capex": ("capex", "capital expenditure", "capital spending", "capital work"),
    "facilities": ("facilities", "plants", "manufacturing units", "factories"),
    "promoter": ("promoter", "shareholding"),
    "guidance": ("guidance", "outlook", "guided"),
    "valuation": ("pe", "p/e", "ev/ebitda", "valuation", "multiple"),
    "audit": ("audit", "auditor", "opinion"),
}


#: Concepts FACTS serves as a numeric metric.  The router names most of them;
#: this is the fallback when it routes no metric at all ("ROIC through the cycle",
#: "dividend policy") and FACTS is still the planner that holds the number.
FACTS_CONCEPTS = ("segment", "revenue", "pat", "ebitda", "eps", "net_npa", "margin",
                  "dso", "cfo", "order_book", "capacity", "capex", "dividend",
                  "working_capital", "roic", "guidance", "valuation", "audit", "promoter")


def asked_metric(question: str) -> str | None:
    """The stored numeric metric an ask names when the router routed none."""
    from ..gate import asked_concepts
    for concept in asked_concepts(question):
        if concept in FACTS_CONCEPTS:
            return concept
    return None


def _t1_rows(ctx: Any, name: str, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    """Rows from a T1 pilot store, read immutable when the build is outside the sandbox."""
    try:
        return ctx.rows(name, sql, params)
    except Exception:  # noqa: BLE001 - the build dir may not be writable for a WAL open
        from ..ctx import t1_path
        path = t1_path(name)
        if path is None or not path.is_file():
            raise
    from reality_engine.db.readonly import connect_ro
    con = connect_ro(path, timeout_s=15, immutable=True)
    try:
        cur = con.execute(sql, tuple(params))
        cols = [col[0] for col in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]
    finally:
        con.close()


def _segment_pnl(ctx: Any, isin: str, as_of: str,
                 period: tuple[str | None, str | None]) -> tuple[list[dict[str, Any]], int]:
    """Segment revenue/PBT by segment name from ``company_segment_pnl`` (T1).

    The XBRL facts carry the amount but not the member name; this table carries
    both, so a "segment revenue" ask is answered by the field that holds it.
    """
    where = ["isin = ?", "known_at <= ?"]
    params: list[Any] = [isin, as_of]
    if period[0] and period[1]:
        where.append("period_end >= ? AND period_end <= ?")
        params.extend([period[0], period[1]])
    try:
        rows = _t1_rows(
            ctx, "facts_pilot",
            "SELECT segment, period_end, metric, basis, value_cr, share_of_total_pct, "
            "doc_id, page, known_at FROM company_segment_pnl "
            f"WHERE {' AND '.join(where)} ORDER BY period_end DESC, segment LIMIT 120",
            tuple(params))
    except Exception:  # noqa: BLE001 - the T1 build is optional in a plain data root
        return [], 0
    out = []
    for r in rows:
        if r.get("value_cr") is None:
            continue
        share = r.get("share_of_total_pct")
        label = f"{r.get('segment')} segment {str(r.get('metric') or '').replace('_', ' ')}"
        if share is not None:
            label += f" ({float(share):.1f}% of total)"
        out.append(_row("company_segment_pnl", label, r["value_cr"], "Rs crore",
                        str(r.get("period_end") or ""), r.get("known_at"), r.get("doc_id"),
                        r.get("page")))
    return out, len(rows)

def _period_bounds(slots: dict[str, Any]) -> tuple[str | None, str | None]:
    basis = str(slots.get("period_basis") or "")
    if basis in ("quarter end", "fiscal year end", "month", "month span",
                 "quarter span", "fiscal year span"):
        return slots.get("date_from"), slots.get("date_to")
    return None, None


DOC_WINDOW_DAYS = 3


def named_of(slots: dict[str, Any]) -> dict[str, Any] | None:
    """The document the question names (date/type), or None -> newest as of."""
    from ..router import named_document
    named = named_document({"question": slots.get("question") or ""})
    if named:
        return named
    if slots.get("doc_type") and str(slots.get("period_basis") or "") in ("named date",
                                                                           "named dates"):
        return {"doc_type": slots["doc_type"], "date": slots.get("date_from")}
    return None


def _window(day: str) -> tuple[str, str]:
    from datetime import date, timedelta
    anchor = date.fromisoformat(day[:10])
    return ((anchor - timedelta(days=DOC_WINDOW_DAYS)).isoformat(),
            (anchor + timedelta(days=DOC_WINDOW_DAYS)).isoformat())


def _quarter_of(day: str) -> tuple[str, str]:
    """The quarter end a call/deck of that day reports on (Mar/Jun/Sep/Dec 31).

    A 4 November call reports the 30 September quarter; the named date is what the
    question anchors on, so the reader gets that quarter's figure and not the
    newest one held.
    """
    from datetime import date
    anchor = date.fromisoformat(str(day)[:10])
    ends = [date(anchor.year, month, day_)
            for month, day_ in ((3, 31), (6, 30), (9, 30), (12, 31))]
    past = [end for end in ends if end <= anchor]
    end = past[-1] if past else date(anchor.year - 1, 12, 31)
    return end.isoformat(), end.isoformat()


def _deck_period_terms(slots: dict[str, Any]) -> tuple[list[str], str | None]:
    """(quarter-or-month labels, year) a deck figure must name to be the asked period."""
    basis = str(slots.get("period_basis") or "")
    day = str(slots.get("date_from") or "")
    if not day or basis not in ("quarter end", "fiscal year end", "quarter span",
                                "fiscal year span"):
        return [], None
    try:
        start_year, month = int(day[:4]), int(day[5:7])
    except ValueError:
        return [], None
    high_year = int(str(slots.get("date_to") or day)[:4])
    if basis in ("fiscal year end", "fiscal year span"):
        terms: list[str] = []
        for fy in range(start_year, high_year + 1):
            terms += [f"fy{fy % 100:02d}", f"fy{fy}", str(fy)]
        return sorted(set(terms)), None
    quarter = {6: "q1", 9: "q2", 12: "q3", 3: "q4"}.get(month, "")
    month_name = {3: "mar", 6: "jun", 9: "sep", 12: "dec"}.get(month, "")
    fy = start_year if month == 3 else start_year + 1
    terms = [f"fy{fy % 100:02d}", f"fy{fy}", str(start_year)]
    if quarter:
        terms += [quarter, f"{quarter}fy{fy % 100:02d}", f"{quarter} fy{fy % 100:02d}"]
    words = [term for term in (quarter, month_name) if term]
    return sorted(set(terms + words)), None


def asked_words(question: str, metric: str | None) -> tuple[str, ...]:
    """The words that carry *every* concept the ask names, not just the first metric.

    A two-part ask ("capacity expansion ... with capex") must be answered on both
    parts: the fact search reads the union, so a row for each part can come back.
    """
    from ..gate import ASK_CONCEPTS, asked_concepts
    words: list[str] = list(TEXT_TERMS.get(metric or "", ()))
    if metric and not words:
        words.append(str(metric))
    for concept in asked_concepts(question):
        if concept == metric:
            continue
        words.extend(TEXT_TERMS.get(concept) or ASK_CONCEPTS.get(concept, ((), ()))[0])
    out: list[str] = []
    for word in words:
        if word not in out:
            out.append(word)
    return tuple(out[:10])


def concept_heads(question: str, metric: str | None) -> tuple[str, ...]:
    """One search word per concept the ask names (the store's leading alias)."""
    from ..gate import ASK_CONCEPTS, asked_concepts
    heads: list[str] = []
    concepts = asked_concepts(question) or ([metric] if metric else [])
    for concept in concepts:
        words = TEXT_TERMS.get(concept) or ASK_CONCEPTS.get(concept, ((), ()))[0]
        if not words and concept == metric:
            words = (concept,)
        if words and words[0] not in heads:
            heads.append(words[0])
    return tuple(heads[:6])


def _term_likes(metric: str | None, columns: list[str],
                words: tuple[str, ...] | None = None) -> tuple[str, list[Any]]:
    if words is None:
        words = TEXT_TERMS.get(metric or "") or ((metric,) if metric else ())
    if not words:
        return "", []
    return terms_clause(list(words), columns, mode="or")


def _fiscal_terms(low: str, high: str | None) -> list[str]:
    """LIKE terms that name every fiscal year between two period ends.

    ``fiscal_year`` is written "FY26", "FY 2025-26" or "2026-03-31" across the
    stores, so both spellings are matched (a "%2026%" alone misses "FY26").
    """
    def fy_of(day: str) -> int:
        year, month = int(str(day)[:4]), int(str(day)[5:7] or 3)
        return year + 1 if month > 3 else year
    first, last = fy_of(low), fy_of(str(high or low)[:10])
    if last < first:
        first, last = last, first
    terms = []
    for fy in range(first, last + 1):
        terms += [f"%fy{fy % 100:02d}%", f"%{fy}%"]
    return terms


def _row(store: str, item: str, value: Any, unit: str | None, period: str | None,
         known_at: str | None, doc_id: Any, page: Any = None, quote: str | None = None,
         context: str | None = None) -> dict[str, Any]:
    return {"store": store, "item": item, "value": value, "unit": unit or "",
            "period": period, "known_at": known_at, "doc_id": doc_id, "page": page,
            "quote": (quote or "")[:400] or None, "context": context,
            "ref": f"{store}:{doc_id}{f'#{page}' if page else ''}"}


def _results(ctx: Any, isin: str, as_of: str, period: tuple[str | None, str | None],
             metric: str | None) -> tuple[list[dict[str, Any]], int]:
    where = ["fi.isin = ?",
             "COALESCE(f.dissem_ts, f.broadcast_ts, f.filing_ts) <> ''",
             "substr(COALESCE(f.dissem_ts, f.broadcast_ts, f.filing_ts),1,10) <= ?"]
    params: list[Any] = [isin, as_of]
    if period[0] and period[1]:
        where.append("f.period_end >= ? AND f.period_end <= ?")
        params.extend([period[0], period[1]])
    try:
        filings = ctx.rows(
            "results_xbrl",
            "SELECT f.file, f.period_end, f.xbrl_url, "
            "COALESCE(f.dissem_ts, f.broadcast_ts, f.filing_ts) AS known_at "
            "FROM filings f JOIN filings_isin fi ON fi.file = f.file "
            f"WHERE {' AND '.join(where)} ORDER BY f.period_end DESC LIMIT 12", params)
        if not filings:
            return [], 0
        files = [r["file"] for r in filings]
        marks = ",".join("?" * len(files))
        concepts = CONCEPT_TERMS.get(metric or "")
        sql = ("SELECT file, concept, context, period_start, period_end, value, unit FROM facts "
               f"WHERE file IN ({marks}) AND value IS NOT NULL")
        args: list[Any] = list(files)
        if concepts:
            sql += " AND (" + " OR ".join("concept LIKE ?" for _ in concepts) + ")"
            args.extend(concepts)
        elif metric:
            # The ask names a concept this schedule does not classify (order book,
            # capacity, guidance, loan growth): a revenue or PBT row is another
            # concept, not the answer.  Only an unnamed numeric ask reads the base.
            return [], len(filings)
        else:
            base = ("RevenueFromOperations", "Income", "ProfitLossForPeriod", "ProfitBeforeTax")
            sql += " AND concept IN (" + ",".join("?" * len(base)) + ")"
            args.extend(base)
        sql += " ORDER BY period_end DESC, concept, file LIMIT 160"
        facts = ctx.rows("results_xbrl", sql, args)
    except Exception:
        return [], 0
    by_file = {r["file"]: r for r in filings}
    out = []
    for row in facts:
        filing = by_file.get(row["file"])
        if not filing:
            continue
        concept = row["concept"] or ""
        label = CONCEPT_LABELS.get(concept) or re.sub(r"(?<!^)(?=[A-Z])", " ", concept)
        value, unit = row["value"], row["unit"] or "INR"
        if concept in PERCENT_CONCEPTS and str(unit).lower() == "pure":
            value = float(value) * 100.0  # XBRL states the ratio (0.005 = 0.50%)
            unit = "%"
        out.append(_row("results_xbrl", label, value, unit,
                        str(row["period_end"] or filing["period_end"]),
                        filing["known_at"], row["file"], context=row["context"]))
    return out, len(filings)


def _ar(ctx: Any, isin: str, as_of: str, period: tuple[str | None, str | None],
        metric: str | None, named: dict[str, Any] | None = None,
        words: tuple[str, ...] | None = None) -> tuple[list[dict[str, Any]], int]:
    where = ["isin = ?", "COALESCE(filed_at,'') <> ''", "substr(filed_at,1,10) <= ?"]
    params: list[Any] = [isin, as_of]
    if named:
        low, high = _window(str(named["date"]))
        where.append("substr(filed_at,1,10) BETWEEN ? AND ?")
        params.extend([low, high])
    if period[0]:
        terms = _fiscal_terms(period[0], period[1])
        where.append("(" + " OR ".join("COALESCE(fiscal_year,'') LIKE ?"
                                       for _ in terms) + ")")
        params.extend(terms)
    clause, clause_params = _term_likes(metric, ["item", "category", "quote"], words)
    if clause:
        where.append(clause)
        params.extend(clause_params)
    try:
        rows = ctx.rows(
            "ar_facts",
            "SELECT doc_id, page, fiscal_year, filed_at, category, item, value, unit, period, "
            "quote FROM ar_facts "
            f"WHERE {' AND '.join(where)} ORDER BY fiscal_year DESC, page LIMIT 160", params)
        if not rows:
            return [], 0
        return [_row("ar_facts", r["item"] or r["category"] or "", r["value"], r["unit"],
                     r["period"] or r["fiscal_year"], r["filed_at"], r["doc_id"], r["page"],
                     r["quote"]) for r in rows if r["value"] is not None], len(rows)
    except Exception:
        return [], 0


def _deck(ctx: Any, isin: str, as_of: str, metric: str | None,
          period_terms: tuple[list[str], str | None] | None = None,
          named: dict[str, Any] | None = None,
          words: tuple[str, ...] | None = None) -> tuple[list[dict[str, Any]], int]:
    where = ["p.isin = ?", "COALESCE(p.known_at,'') <> ''", "substr(p.known_at,1,10) <= ?"]
    params: list[Any] = [isin, as_of]
    if named:
        low, high = _window(str(named["date"]))
        where.append("substr(p.known_at,1,10) BETWEEN ? AND ?")
        params.extend([low, high])
    clause, clause_params = _term_likes(metric, ["f.metric"], words)
    if clause:
        where.append(clause)
        params.extend(clause_params)
    terms, year = period_terms or ([], None)
    if terms:
        where.append("(" + " OR ".join("lower(COALESCE(f.period,'')) LIKE ?"
                                       for _ in terms) + ")")
        params.extend([f"%{term}%" for term in terms])
    if year:
        where.append("lower(COALESCE(f.period,'')) LIKE ?")
        params.append(f"%{year}%")
    try:
        pages = ctx.one("deck_figures",
                        "SELECT COUNT(*) AS n FROM pages WHERE isin=? AND substr(COALESCE(known_at,''),1,10) <= ?",
                        (isin, as_of))
        rows = ctx.rows(
            "deck_figures",
            "SELECT f.sha256, f.page_no, f.metric, f.period, f.value, f.unit, p.known_at, p.doc_type "
            "FROM pages p JOIN facts f ON f.sha256=p.sha256 AND f.page_no=p.page_no "
            f"WHERE {' AND '.join(where)} ORDER BY p.known_at DESC, f.page_no LIMIT 160", params)
        return [_row("deck_figures", r["metric"], r["value"], r["unit"], r["period"],
                     r["known_at"], r["sha256"], r["page_no"]) for r in rows], int((pages or {}).get("n") or 0)
    except Exception:
        return [], 0


def _concall(ctx: Any, isin: str, as_of: str, metric: str | None,
             named: dict[str, Any] | None = None,
             words: tuple[str, ...] | None = None) -> tuple[list[dict[str, Any]], int]:
    where = ["i.isin = ?", "COALESCE(d.filed_at,'') <> ''", "substr(d.filed_at,1,10) <= ?"]
    params: list[Any] = [isin, as_of]
    if named:
        low, high = _window(str(named["date"]))
        where.append("substr(d.filed_at,1,10) BETWEEN ? AND ?")
        params.extend([low, high])
    clause, clause_params = _term_likes(metric, ["i.metric", "i.statement", "i.quote"],
                                        words)
    if clause:
        where.append(clause)
        params.extend(clause_params)
    try:
        rows = ctx.rows(
            "concall_facts",
            "SELECT i.doc_id, i.metric, i.value, i.unit, i.period, i.quote, d.filed_at "
            "FROM cc_items i JOIN cc_docs d ON d.doc_id = i.doc_id "
            f"WHERE {' AND '.join(where)} ORDER BY d.filed_at DESC, i.idx LIMIT 160", params)
        # The extraction store keeps its figure as text ("1,801", "350 to 400"):
        # a value that states a number is a fact, not only a passage.
        return [_row("concall_facts", r["metric"] or "", _number(r["value"]), r["unit"],
                     r["period"], r["filed_at"], r["doc_id"], quote=r["quote"])
                for r in rows], len(rows)
    except Exception:
        return [], 0


def _number(value: Any) -> Any:
    """The number an extracted value states, else the text unchanged."""
    parsed = compute.first_number(value)
    return parsed if parsed is not None else value


def _computed(rows: list[dict[str, Any]], metric: str | None) -> dict[str, Any] | None:
    def pick(*needles: str) -> dict[str, Any] | None:
        for row in sorted(rows, key=lambda r: str(r.get("period") or ""), reverse=True):
            low = f"{row.get('item') or ''} {row.get('quote') or ''}".lower()
            if row.get("value") is not None and all(n in low for n in needles):
                return row
        return None

    if metric == "dso":
        revenue = pick("revenue") or pick("sales") or pick("turnover")
        receivables = pick("receivable") or pick("debtor")
        if revenue and receivables:
            days = compute.ratio(receivables["value"], revenue["value"])
            if days is not None:
                return {"store": "computed", "item": "DSO (receivables/revenue x 365)",
                        "value": days * 365.0, "unit": "days",
                        "period": receivables.get("period"), "known_at": receivables.get("known_at"),
                        "doc_id": None, "page": None, "context": "computed",
                        "quote": f"{fmt_num(receivables['value'])} / {fmt_num(revenue['value'])} x 365",
                        "ref": "computed:dso"}
    if metric == "cfo":
        cfo = pick("cash flow", "operat") or pick("cfo")
        pat = pick("profit")
        if cfo and pat:
            ratio = compute.ratio(cfo["value"], pat["value"])
            if ratio is not None:
                return {"store": "computed", "item": "CFO / PAT", "value": ratio, "unit": "x",
                        "period": cfo.get("period"), "known_at": cfo.get("known_at"),
                        "doc_id": None, "page": None, "context": "computed",
                        "quote": f"{fmt_num(cfo['value'])} / {fmt_num(pat['value'])}",
                        "ref": "computed:cfo_pat"}
    return None


def _promoter_facts(ctx: Any, isin: str, as_of: str,
                    question: str) -> list[dict[str, Any]]:
    """Promoter/public holding quarters from shp_index, PIT on broadcast_at."""
    try:
        rows = ctx.rows(
            "equity_intelligence",
            "SELECT quarter_end, promoter_pct, public_pct, broadcast_at FROM shp_index "
            "WHERE isin = ? AND COALESCE(broadcast_at,'') <> '' "
            "AND substr(broadcast_at,1,10) <= ? ORDER BY quarter_end DESC LIMIT 5",
            (isin, as_of))
    except Exception:
        return []
    out = []
    want_public = bool(re.search(r"\bpublic\b", question, re.I))
    want_promoter = bool(re.search(r"\bpromoter\b", question, re.I)) and not want_public
    for row in rows:
        if row["promoter_pct"] is not None and not want_public:
            out.append(_row("shp_index", "Promoter holding %", row["promoter_pct"], "%",
                            row["quarter_end"], row["broadcast_at"], row["quarter_end"]))
        if row["public_pct"] is not None and not want_promoter:
            out.append(_row("shp_index", "Public holding %", row["public_pct"], "%",
                            row["quarter_end"], row["broadcast_at"], row["quarter_end"]))
    if len(rows) >= 2 and re.search(r"raise|increase|fall|decline|change|dilut|stake",
                                    question, re.I):
        delta = compute.delta(rows[1]["promoter_pct"], rows[0]["promoter_pct"])
        if delta is not None:
            row = {"store": "computed", "item": "Promoter holding change (pp)",
                   "value": delta, "unit": "pp", "period": row_period(rows),
                   "known_at": rows[0]["broadcast_at"], "doc_id": None, "page": None,
                   "context": "computed",
                   "quote": f"{rows[1]['quarter_end']} -> {rows[0]['quarter_end']}",
                   "ref": "computed:promoter_change"}
            out.insert(0, row)
    if re.search(r"share|float|dilut", question, re.I):
        try:
            capital = ctx.rows(
                "results_xbrl",
                "SELECT f.file, x.concept, x.value, "
                "COALESCE(f.dissem_ts,f.broadcast_ts,f.filing_ts) AS known_at FROM filings f "
                "JOIN filings_isin fi ON fi.file = f.file JOIN facts x ON x.file = f.file "
                "WHERE fi.isin = ? AND x.concept IN ('PaidUpValueOfEquityShareCapital', "
                "'FaceValueOfEquityShareCapital') AND x.value IS NOT NULL "
                "AND COALESCE(f.dissem_ts,f.broadcast_ts,f.filing_ts) <> '' "
                "AND substr(COALESCE(f.dissem_ts,f.broadcast_ts,f.filing_ts),1,10) <= ? "
                "ORDER BY f.period_end DESC LIMIT 8", (isin, as_of))
        except Exception:
            capital = []
        paid = next((r for r in capital if r["concept"] == "PaidUpValueOfEquityShareCapital"), None)
        face = next((r for r in capital if r["concept"] == "FaceValueOfEquityShareCapital"), None)
        if paid and face and face["value"]:
            shares = float(paid["value"]) / float(face["value"])
            out.insert(0, {"store": "computed", "item": "Shares outstanding (paid-up/face value)",
                           "value": shares, "unit": "shares", "period": None,
                           "known_at": paid.get("known_at"), "doc_id": paid["file"], "page": None,
                           "context": "computed",
                           "quote": f"{paid['value']:g} / {face['value']:g}",
                           "ref": f"results_xbrl:{paid['file']}"})
    return out


def row_period(rows: list[dict[str, Any]]) -> str:
    return f"{rows[1]['quarter_end']} -> {rows[0]['quarter_end']}"


def _metric_store(ctx: Any, isin: str, as_of: str, question: str, metric: str | None,
                  period: tuple[str | None, str | None]) -> list[dict[str, Any]]:
    """Facts from the pilot-60 extraction tables (``metric_state``), when built."""
    try:
        from reality_engine.query import metrics
        return metrics.facts_rows(ctx, isin, as_of, question, metric, period)
    except Exception:  # noqa: BLE001 - no store / bad row shape degrades to the held stores
        return []


def _pilot_store(ctx: Any, isin: str, as_of: str, metric: str | None,
                 period: tuple[str | None, str | None],
                 kind: str | None) -> list[dict[str, Any]]:
    """Facts from the T1 build (``facts_pilot``), when the run configured it."""
    try:
        from reality_engine.query import metrics
        return metrics.pilot_rows(ctx, isin, as_of, metric, period, kind)
    except Exception:  # noqa: BLE001 - no T1 build / bad row shape degrades to the held stores
        return []


def _series_kind(slots: dict[str, Any]) -> str | None:
    """The ``period_kind`` a period ask names (a Q4FY26 row is not the FY26 row)."""
    basis = str(slots.get("period_basis") or "")
    if basis in ("quarter end", "quarter span"):
        return "quarter"
    if basis in ("fiscal year end", "fiscal year span"):
        return "fy"
    return None


def _pilot_period(slots: dict[str, Any]) -> tuple[tuple[str | None, str | None], str | None,
                                                  str | None]:
    """(period bounds, period_kind, date to stamp) for the numeric fact build.

    A "named date" ask ("on its 4 November call") names the document, not a period
    end: the figures are the quarter that call reports on, and the row is stamped
    with the named date (the same rule the named-document branch applies).
    """
    basis = str(slots.get("period_basis") or "")
    if basis in ("named date", "named dates") and slots.get("date_from"):
        return _quarter_of(str(slots["date_from"])), "quarter", str(slots["date_from"])
    return _period_bounds(slots), _series_kind(slots), None


def plan(slots: dict[str, Any], as_of: str, ctx: Any) -> dict[str, Any]:
    metric = slots.get("metric")
    question = str(slots.get("question") or "")
    routed = metric is not None and metric not in PRICE_METRICS
    if metric is None or metric in PRICE_METRICS:
        # The router names a metric for most numeric asks, and routes "return on
        # capital" as a price "return"; when the question names a concept these
        # stores hold (ROIC, working capital, dividend), FACTS answers that.
        metric = asked_metric(question) or metric
    if metric is None or metric in PRICE_METRICS:
        return envelope("FACTS", ok=True, na=True, checked=CHECKED,
                        detail="no stored numeric metric asked; FACTS not applicable")
    if not slots.get("needs", {}).get("financials") and routed:
        return envelope("FACTS", ok=True, na=True, checked=CHECKED,
                        detail="no stored numeric metric asked; FACTS not applicable")
    isin = isin_of(slots, ctx, as_of)
    if not isin:
        return envelope("FACTS", ok=True, na=True, checked=CHECKED,
                        detail="no company ISIN at as_of; FACTS not applicable")
    period = _period_bounds(slots)
    named = named_of(slots)
    words = asked_words(question, metric)
    rows: list[dict[str, Any]] = []
    candidates = 0
    if named:
        # Named document preference: only that document's store, only the
        # filing date within ±3 days.  A miss is not a licence to answer from an
        # older document the question did not name.
        store = {"deck": _deck, "ar": _ar, "transcript": _concall}.get(str(named["doc_type"]))
        doc_note = f"{named['doc_type']} of {named['date']} (±{DOC_WINDOW_DAYS}d filing date)"
        if store is not None:
            if store is _deck:
                got, candidates = _deck(ctx, isin, as_of, metric, _deck_period_terms(slots),
                                        named, words)
            elif store is _ar:
                got, candidates = _ar(ctx, isin, as_of, period, metric, named, words)
            else:
                got, candidates = _concall(ctx, isin, as_of, metric, named, words)
            rows = got
            # The named document's date IS the asked period: its own KPI label
            # ("FY26" on a Q1FY27 deck) is not a different period.
            for row in rows:
                row["period"] = named["date"]
        else:
            return envelope("FACTS", ok=True, na=True, checked=CHECKED,
                            detail=f"{named['doc_type']} text is EVIDENCE, not a fact store")
        if not rows:
            detail = (f"the {doc_note} carries no extracted {metric} fact; "
                      f"the passage is EVIDENCE, not a FACTS row")
            return envelope("FACTS", ok=True, na=True, checked=CHECKED, detail=detail,
                            degraded=[f"named-document preference: {doc_note}; no older document used"])
    else:
        metric_store = _metric_store(ctx, isin, as_of, question, metric, period)
        rows += metric_store
        # A two-part ask ("capacity expansion with capex", "EBITDA margins") names a
        # concept of its own per part: each part gets its own store search, so the
        # rows that answer one part cannot crowd out the other inside the top rows.
        from ..gate import asked_concepts
        from reality_engine.query import metrics as metric_reads
        searches = [metric]
        for concept in asked_concepts(question):
            if concept != metric and concept in (CONCEPT_TERMS | TEXT_TERMS) \
                    and concept not in searches:
                searches.append(concept)
        searches = searches[:3]
        for concept in searches:
            search_words = words if concept == metric else asked_words(question, concept)
            for got, n in (_results(ctx, isin, as_of, period, concept),
                           _ar(ctx, isin, as_of, period, concept, words=search_words)
                           if slots.get("period_basis") not in ("quarter end", "quarter span")
                           else ([], 0),
                           _deck(ctx, isin, as_of, concept, _deck_period_terms(slots),
                                 words=search_words),
                           _concall(ctx, isin, as_of, concept, words=search_words)):
                rows += got
                candidates += n
        # The whole-market XBRL fact build: revenue/PAT/EPS are held there per
        # quarter (and FY), and the ratios the bank asks by name are derived from
        # those components rather than reported from a store that never had them.
        pilot_period, pilot_kind, stamp = _pilot_period(slots)
        wanted = [metric] + [c for c in searches if c != metric
                             and c in metric_reads.SERIES_KEYS][:2]
        pilot: list[dict[str, Any]] = []
        for name in wanted:
            pilot += _pilot_store(ctx, isin, as_of, name, pilot_period, pilot_kind)
        for row in pilot:
            if stamp:
                row["context"] = f"quarter ended {row.get('period')}"
                row["period"] = stamp
        rows = pilot + rows
        candidates += len(metric_store) + len(pilot)
        if metric == "promoter":
            promoter = _promoter_facts(ctx, isin, as_of, question)
            rows = promoter + rows
            candidates += len(promoter)
    # Every fact row names the asked entity (the gate reads isin/symbol, and a
    # store id is not an identity).
    for row in rows:
        row.setdefault("isin", isin)
        if slots.get("symbol"):
            row.setdefault("symbol", slots["symbol"])
    # Only numeric facts count as facts; a concall passage with a text payload
    # is evidence, not a figure.
    rows = [r for r in rows
            if isinstance(r.get("value"), (int, float)) and not isinstance(r.get("value"), bool)]
    if not rows and named:
        # The named document states no number for this concept (a transcript quote
        # is EVIDENCE): the figures behind it are the quarter it reports on, and the
        # named date stays the row's period (the document IS the period asked).
        fallback = _pilot_store(ctx, isin, as_of, metric, _quarter_of(str(named["date"])),
                                "quarter")
        if fallback:
            for row in fallback:
                row["period"] = named["date"]
            rows = fallback
            candidates += len(fallback)
            named = None  # the rows are that quarter's; their period is the anchor
    if metric == "segment":
        # Segment revenue by member lives in company_segment_pnl (T1).  The member
        # row states both halves of a "segment revenue" ask; when only the note's
        # own total is held (a quarter has no by-member row in the annual build),
        # that total still carries the concept, and the revenue line is returned
        # beside it so neither half of the ask goes unanswered.
        segment_rows, seg_candidates = _segment_pnl(ctx, isin, as_of, period)
        candidates += seg_candidates
        generic = {"segment revenue", "segment revenue from operations",
                   "segment profit before tax", "segment profitloss before tax",
                   "segment assets", "segment liabilities", "net segment assets",
                   "net segment liabilities", "segment pbt before finance costs",
                   "inter segment revenue"}
        member_rows = list(segment_rows) or [
            r for r in rows
            if r.get("store") != "results_xbrl"
            and str(r.get("item") or "").strip().lower() not in generic
            and re.search(r"segment", str(r.get("item") or ""), re.I)]
        total_rows = [r for r in rows
                      if re.search(r"segment", str(r.get("item") or ""), re.I)
                      and r not in member_rows]
        if not member_rows and not total_rows:
            # The pilot extraction store carries the segment note with the member name.
            member_rows = [r for r in _metric_store(ctx, isin, as_of, question, "segment",
                                                    period)
                           if r.get("store") == "metric_state"]
        if not member_rows and not total_rows:
            detail = ("segment facts exist but the segment member names are not mapped "
                      "for this period; a segment P&L by name needs company_segment_pnl "
                      "(annual only in the T1 build) / xbrl_concept_map")
            return envelope("FACTS", ok=False, why="schema", checked=CHECKED,
                            gap="company_segment_pnl", detail=detail, nid_reason=detail)
        wants_split = bool(re.search(r"\beach\b|\bsplit\b|segment[- ]wise|by segment|"
                                     r"break-?up|per segment|segments'|各", question, re.I))
        if not member_rows and wants_split:
            # The note's own total is not "the number for each reported segment":
            # say what is held instead of passing a total off as the split.
            total = next((r for r in total_rows
                          if re.match(r"segment revenue",
                                      str(r.get("item") or "").strip().lower())), None)
            detail = ("the segment note's total for this period is held"
                      + (f" ({fmt_num(total['value'], total.get('unit'))})" if total else "")
                      + ", but the per-member split for this period is not: "
                        "company_segment_pnl is annual in the T1 build")
            return envelope("FACTS", ok=False, why="schema", checked=CHECKED,
                            gap="company_segment_pnl", detail=detail, nid_reason=detail)
        revenue_rows = _pilot_store(ctx, isin, as_of, "revenue", *_pilot_period(slots)[:2])
        rows = (member_rows or total_rows) + [r for r in revenue_rows
                                              if r not in (member_rows or total_rows)]
    if metric == "net_npa":
        # Gross and net NPA share a concept family; the qualifier decides.
        if re.search(r"\bnet\b", question, re.I):
            rows = [r for r in rows if "net" in str(r.get("item") or "").lower()]
        elif re.search(r"\bgross\b", question, re.I):
            rows = [r for r in rows if "gross" in str(r.get("item") or "").lower()]
    computed = _computed(rows, metric)
    if computed:
        rows.insert(0, computed)
    # Honour the resolved period: a fact from another quarter/month/date is not
    # the answer.  An FY ask shows a Q4FY26 fact filed for that year as FY26.
    if str(slots.get("period_basis") or "") in ("quarter end", "fiscal year end",
                                                "quarter span", "fiscal year span"):
        normalise_label(rows, slots.get("period_label"))
    kept = in_period(rows, slots, named, hop="FACTS")
    dropped = len(rows) - len(kept)
    rows = kept
    degraded = []
    if dropped:
        degraded.append(f"{dropped} fact row(s) outside the asked period were dropped")
    if not period[0] and not named:
        degraded.append("no period in the ask; newest facts shown")
    if named:
        degraded.append(f"named-document preference: only the {named['doc_type']} of "
                        f"{named['date']} (±{DOC_WINDOW_DAYS}d filing date) was read")
    if not rows:
        why = "schema" if candidates else "no_doc"
        detail = (f"facts exist for {slots.get('symbol') or isin} but none carries the asked "
                  f"metric ({metric or 'numeric ask'})"
                  if candidates else
                  f"no {metric or 'numeric'} fact filed on or before {as_of} for "
                  f"{slots.get('symbol') or isin}")
        return envelope("FACTS", ok=False, why=why, checked=CHECKED, degraded=degraded,
                        detail=detail, nid_reason=detail)
    # Newest document first: the question asked "latest" unless it named a
    # period or a document (the named window already narrowed the rows).  Within
    # one document the row that names the asked words leads ("Manufacturing
    # Facilities" before "Warangal facilities operationalized").
    terms = [str(t).lower() for t in (slots.get("terms") or [])]

    def hits(row: dict[str, Any]) -> int:
        text = f"{row.get('item') or ''} {row.get('period') or ''}".lower()
        return sum(1 for term in terms if term in text)

    ranked = sorted(rows, key=lambda r: (
        1 if r.get("store") == "computed" else 0,
        str(r.get("known_at") or ""), hits(r), str(r.get("period") or "")), reverse=True)
    top = ranked[:6]
    heads = concept_heads(question, metric)
    if len(heads) > 1:
        # A two-part ask must show a row for every concept it names: the newest
        # six rows can all carry the same one, so one row per concept goes first.
        def text_of(row: dict[str, Any]) -> str:
            return f"{row.get('item') or ''} {row.get('quote') or ''}".lower()

        picked: list[dict[str, Any]] = []
        for head in heads:
            for row in ranked:
                if row not in picked and head in text_of(row):
                    picked.append(row)
                    break
        for row in ranked:
            if len(picked) >= 6:
                break
            if row not in picked:
                picked.append(row)
        top = picked[:6]
    detail = "; ".join(
        f"{r['item']} {r['period'] or ''} = {fmt_num(r['value'], r['unit'])} "
        f"({r['store']}, known {str(r.get('known_at'))[:10]})" for r in top[:3])
    if named:
        detail = f"named {named['doc_type']} {named['date']}: " + detail
    return envelope(
        "FACTS", ok=True, rows=top,
        provenance=[{"ref": r["ref"], "known_at": r.get("known_at")} for r in top],
        pit=f"row filing timestamp <= {as_of} (results dissem_ts, ar filed_at, deck known_at, concall filed_at)",
        checked=CHECKED, degraded=degraded, detail=detail)
