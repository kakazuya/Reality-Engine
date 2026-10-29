"""FACTS: one metric (+period) from every stamped fact store, PIT-filtered in SQL.

Stores read: ``results_xbrl`` (filings + long facts), ``ar_facts``,
``deck_figures`` (pages -> facts), ``concall_facts`` (cc_docs -> cc_items).
A missing metric is reported as a schema gap, an empty company as no-doc.
"""
from __future__ import annotations

import re
from typing import Any

from reality_engine.query import compute

from . import envelope, fmt_num, isin_of, terms_clause

CHECKED = ["results_xbrl.filings", "results_xbrl.facts", "ar_facts.ar_facts",
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
    "cfo": ("%CashFlow%",),
    "order_book": ("%Order%",),
    "capacity": ("%Capacity%",),
    "promoter": ("%Shareholding%",),
    "valuation": ("%EarningsLossPerShare%", "%PaidUp%", "%FaceValue%"),
    "guidance": ("%Guidance%",),
    "audit": ("%Audit%", "%Opinion%"),
}

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
    "facilities": ("facilities", "plants", "manufacturing units", "factories"),
    "promoter": ("promoter", "shareholding"),
    "guidance": ("guidance", "outlook", "guided"),
    "valuation": ("pe", "p/e", "ev/ebitda", "valuation", "multiple"),
    "audit": ("audit", "auditor", "opinion"),
}

def _period_bounds(slots: dict[str, Any]) -> tuple[str | None, str | None]:
    basis = str(slots.get("period_basis") or "")
    if basis in ("quarter end", "fiscal year end", "month"):
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


def _deck_period_terms(slots: dict[str, Any]) -> tuple[list[str], str | None]:
    """(quarter-or-month labels, year) a deck figure must name to be the asked period."""
    basis = str(slots.get("period_basis") or "")
    day = str(slots.get("date_from") or "")
    if not day or basis not in ("quarter end", "fiscal year end"):
        return [], None
    try:
        month, year = int(day[5:7]), day[:4]
    except ValueError:
        return [], None
    if basis == "fiscal year end":
        return [f"fy{int(year) % 100:02d}"], year
    quarter = {6: "q1", 9: "q2", 12: "q3", 3: "q4"}.get(month, "")
    month_name = {3: "mar", 6: "jun", 9: "sep", 12: "dec"}.get(month, "")
    return [term for term in (quarter, month_name) if term], year


def _term_likes(metric: str | None, columns: list[str]) -> tuple[str, list[Any]]:
    words = TEXT_TERMS.get(metric or "") if metric else ()
    if metric and not words:
        words = (metric,)
    if not words:
        return "", []
    return terms_clause(words, columns, mode="or")


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
        label = re.sub(r"(?<!^)(?=[A-Z])", " ", row["concept"] or "")
        out.append(_row("results_xbrl", label, row["value"], row["unit"] or "INR",
                        str(row["period_end"] or filing["period_end"]),
                        filing["known_at"], row["file"], context=row["context"]))
    return out, len(filings)


def _ar(ctx: Any, isin: str, as_of: str, period: tuple[str | None, str | None],
        metric: str | None, named: dict[str, Any] | None = None) -> tuple[list[dict[str, Any]], int]:
    where = ["isin = ?", "COALESCE(filed_at,'') <> ''", "substr(filed_at,1,10) <= ?"]
    params: list[Any] = [isin, as_of]
    if named:
        low, high = _window(str(named["date"]))
        where.append("substr(filed_at,1,10) BETWEEN ? AND ?")
        params.extend([low, high])
    if period[0]:
        params.append(f"%{str(period[0])[:4]}%")
        where.append("COALESCE(fiscal_year,'') LIKE ?")
    clause, clause_params = _term_likes(metric, ["item", "category", "quote"])
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
          named: dict[str, Any] | None = None) -> tuple[list[dict[str, Any]], int]:
    where = ["p.isin = ?", "COALESCE(p.known_at,'') <> ''", "substr(p.known_at,1,10) <= ?"]
    params: list[Any] = [isin, as_of]
    if named:
        low, high = _window(str(named["date"]))
        where.append("substr(p.known_at,1,10) BETWEEN ? AND ?")
        params.extend([low, high])
    clause, clause_params = _term_likes(metric, ["f.metric"])
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
             named: dict[str, Any] | None = None) -> tuple[list[dict[str, Any]], int]:
    where = ["i.isin = ?", "COALESCE(d.filed_at,'') <> ''", "substr(d.filed_at,1,10) <= ?"]
    params: list[Any] = [isin, as_of]
    if named:
        low, high = _window(str(named["date"]))
        where.append("substr(d.filed_at,1,10) BETWEEN ? AND ?")
        params.extend([low, high])
    clause, clause_params = _term_likes(metric, ["i.metric", "i.statement", "i.quote"])
    if clause:
        where.append(clause)
        params.extend(clause_params)
    try:
        rows = ctx.rows(
            "concall_facts",
            "SELECT i.doc_id, i.metric, i.value, i.unit, i.period, i.quote, d.filed_at "
            "FROM cc_items i JOIN cc_docs d ON d.doc_id = i.doc_id "
            f"WHERE {' AND '.join(where)} ORDER BY d.filed_at DESC, i.idx LIMIT 160", params)
        return [_row("concall_facts", r["metric"] or "", r["value"], r["unit"], r["period"],
                     r["filed_at"], r["doc_id"], quote=r["quote"]) for r in rows], len(rows)
    except Exception:
        return [], 0


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


def plan(slots: dict[str, Any], as_of: str, ctx: Any) -> dict[str, Any]:
    metric = slots.get("metric")
    question = str(slots.get("question") or "")
    if not slots.get("needs", {}).get("financials"):
        return envelope("FACTS", ok=True, na=True, checked=CHECKED,
                        detail="no stored numeric metric asked; FACTS not applicable")
    if metric is None or metric in PRICE_METRICS:
        return envelope("FACTS", ok=True, na=True, checked=CHECKED,
                        detail="no stored numeric metric asked; FACTS not applicable")
    isin = isin_of(slots, ctx, as_of)
    if not isin:
        return envelope("FACTS", ok=True, na=True, checked=CHECKED,
                        detail="no company ISIN at as_of; FACTS not applicable")
    period = _period_bounds(slots)
    named = named_of(slots)
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
                got, candidates = _deck(ctx, isin, as_of, metric, _deck_period_terms(slots), named)
            elif store is _ar:
                got, candidates = _ar(ctx, isin, as_of, period, metric, named)
            else:
                got, candidates = _concall(ctx, isin, as_of, metric, named)
            rows = got
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
        for got, n in (_results(ctx, isin, as_of, period, metric),
                       _ar(ctx, isin, as_of, period, metric)
                       if slots.get("period_basis") != "quarter end" else ([], 0),
                       _deck(ctx, isin, as_of, metric, _deck_period_terms(slots)),
                       _concall(ctx, isin, as_of, metric)):
            rows += got
            candidates += n
        candidates += len(metric_store)
        if metric == "promoter":
            promoter = _promoter_facts(ctx, isin, as_of, question)
            rows = promoter + rows
            candidates += len(promoter)
    # Only numeric facts count as facts; a concall passage with a text payload
    # is evidence, not a figure.
    rows = [r for r in rows
            if isinstance(r.get("value"), (int, float)) and not isinstance(r.get("value"), bool)]
    if metric == "segment":
        # XBRL segment facts carry the amount but the member name is unmapped
        # (context is OneD/FourD); only an item that names the segment counts.
        generic = {"segment revenue", "segment revenue from operations",
                   "segment profit before tax", "segment profitloss before tax",
                   "segment assets", "segment liabilities", "net segment assets",
                   "net segment liabilities", "segment pbt before finance costs"}
        named_rows = [r for r in rows
                      if r.get("store") != "results_xbrl"
                      and str(r.get("item") or "").strip().lower() not in generic
                      and re.search(r"segment", str(r.get("item") or ""), re.I)]
        if not named_rows:
            # The pilot extraction store carries the segment note with the member name.
            named_rows = [r for r in _metric_store(ctx, isin, as_of, question, "segment", period)
                          if r.get("store") == "metric_state"]
        if not named_rows:
            detail = ("segment facts exist but the segment member names are not mapped; "
                      "a segment P&L by name needs company_segment_pnl / xbrl_concept_map")
            return envelope("FACTS", ok=False, why="schema", checked=CHECKED,
                            gap="company_segment_pnl", detail=detail, nid_reason=detail)
        rows = named_rows
    if metric == "net_npa":
        # Gross and net NPA share a concept family; the qualifier decides.
        if re.search(r"\bnet\b", question, re.I):
            rows = [r for r in rows if "net" in str(r.get("item") or "").lower()]
        elif re.search(r"\bgross\b", question, re.I):
            rows = [r for r in rows if "gross" in str(r.get("item") or "").lower()]
    computed = _computed(rows, metric)
    if computed:
        rows.insert(0, computed)
    degraded = []
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
