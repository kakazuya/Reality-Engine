"""One-call market lookups: ``delivery``, ``price_extreme``, ``holding``.

Each tool resolves the company once (NSE symbol / BSE code / ISIN / name), then
hard-codes the table, keys and preference order so a worker never has to guess
SQL.  Everything here is read-only and bounded by a date range or an ISIN key;
``core`` owns the connections, ``resolve_one`` and provenance.

When nothing matches, every tool returns ``{"found": False, "checked": [...],
"hint": ...}`` instead of an empty list, so the next call is obvious.
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Any, Iterable, Sequence

import core

DUCK = core.DUCK_KEY
_MAX_DATES = 60
_MAX_SPAN_DAYS = 120

# AR items that carry the company's *total* share count.  The extraction is
# per-document prose, so the name varies; the match is on the normalised item
# plus a plausibility guard against the XBRL-derived count below.
_SHARE_TOTAL = re.compile(
    r"\btotal shares\b|\btotal (number of )?(equity )?shares\b|\bgrand total shares\b")
_SHARE_TOTAL_BAD = re.compile(
    r"holder|promoter|pledge|demat|traded|distribution|suspense|bonus|weighted average|"
    r"ipo|to be issued|esop|option|buyback|buy-back|sub-division|categor|bucket|of total|"
    r"related part|associate|subsidiar|held \(count\)|complaint|dividend|"
    r"public|retail|mutual fund|insurance|\bfii\b|\bfpi\b|nri|foreign|huf|iepf|"
    r"corporate|clearing"
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------
def _not_found(query: str, checked: Sequence[str], hint: str, **extra: Any) -> dict[str, Any]:
    out: dict[str, Any] = {"found": False, "query": query, "checked": list(checked), "hint": hint}
    out.update(extra)
    return out


def _prov(keys: dict[str, Sequence[str]], **extra: Any) -> dict[str, Any]:
    """Provenance for every store touched by one answer."""
    dbs = {key: core.provenance(key, tables) for key, tables in keys.items()}
    out: dict[str, Any] = {
        "read_only": True,
        "generated_at": dbs[next(iter(dbs))]["generated_at"],
        "databases": dbs,
    }
    out.update(extra)
    return out


def _duck(sql: str, params: Sequence[Any] = (), timeout: float = 2.0) -> list[dict[str, Any]]:
    columns, rows = core._run_duck(sql, params, timeout=timeout)
    return [dict(zip(columns, row)) for row in rows]


def _sqlite(key: str, sql: str, params: Sequence[Any] = (), timeout: float = 3.0) -> list[dict[str, Any]]:
    return [dict(row) for row in core._run_sqlite(key, sql, params, timeout=timeout)]


def _identity(query: str) -> dict[str, Any] | None:
    try:
        return core.resolve_one(query)
    except core.DataError:
        return None


def _nse_keys(identity: dict[str, Any], query: str) -> tuple[list[str], list[str]]:
    return core._identity_isins(identity), core._identity_symbols(identity, query)


def _bse_keys(identity: dict[str, Any], query: str) -> tuple[list[str], list[str]]:
    codes = [str(v) for v in (identity.get("bse_code"), query) if v]
    for h in identity.get("isin_history", []):
        if h.get("exchange") == "BSE" and h.get("symbol"):
            codes.append(str(h["symbol"]))
    codes = [c.upper() for c in dict.fromkeys(codes) if c]
    return core._identity_isins(identity), codes


def _key_filter(identity: dict[str, Any], query: str, exchange: str) -> tuple[str, list[Any]]:
    """``(sql predicate, params)`` matching one exchange's identity columns."""
    isins, codes = (_nse_keys if exchange == "NSE" else _bse_keys)(identity, query)
    parts: list[str] = []
    params: list[Any] = []
    for column, values in (("isin", isins),
                           ("upper(symbol)" if exchange == "NSE" else "sc_code", codes)):
        if not values:
            continue
        clause, vals = core._in_clause(values)
        parts.append(f"{column} IN {clause}")
        params.extend(vals)
    if exchange == "BSE":  # some px_bse rows store the NSE ticker in `symbol`
        clause, vals = core._in_clause([s.upper() for s in _nse_keys(identity, query)[1]])
        if vals:
            parts.append(f"upper(symbol) IN {clause}")
            params.extend(vals)
    if not parts:
        raise core.DataError("not_found", f"no NSE symbol, BSE code or ISIN for {query!r}")
    return "(" + " OR ".join(parts) + ")", params


def _latest_snapshot_date() -> dt.date:
    rows = _duck("SELECT max(date) AS d FROM px_nse")
    value = rows[0]["d"] if rows else None
    if value is None:
        raise core.DataError("snapshot_empty", "px_nse has no dates")
    return value if isinstance(value, dt.date) else dt.date.fromisoformat(str(value)[:10])


# ---------------------------------------------------------------------------
# delivery
# ---------------------------------------------------------------------------
def _date_list(dates: Sequence[str] | str, end: str | None) -> list[dt.date]:
    if isinstance(dates, str):
        start = core._parse_date(dates, "dates")
        if start is None:
            raise core.DataError("bad_date", "dates is required")
        if end:
            last = core._parse_date(end, "end")
            span = (last - start).days
            if span < 0:
                raise core.DataError("bad_range", f"end {last} is before start {start}")
            if span > _MAX_SPAN_DAYS:
                raise core.DataError("bad_range", f"window is longer than {_MAX_SPAN_DAYS} days")
            out = [start + dt.timedelta(days=i) for i in range(span + 1)]
        else:
            out = [start]
    elif dates:
        if end:
            raise core.DataError("bad_request", "pass either a list of dates or one date plus end")
        out = [core._parse_date(d, "dates") for d in dates]
    else:
        raise core.DataError("bad_request", "dates must be a date list or a single date")
    unique = [d for d in dict.fromkeys(out) if d is not None]
    unique.sort()
    if not unique:
        raise core.DataError("bad_date", "no usable dates")
    if len(unique) > _MAX_DATES:
        raise core.DataError("bad_range", f"at most {_MAX_DATES} dates per call")
    return unique


def _exchange_rows(table: str, identity: dict[str, Any], query: str,
                   days: list[dt.date]) -> dict[str, dict[str, Any]]:
    """Per-date aggregated volume/delivery for one exchange (raw tables only)."""
    predicate, params = _key_filter(identity, query, "NSE" if table == "px_nse" else "BSE")
    rows = _duck(
        f"SELECT date, volume, deliverable_qty FROM {table} "
        f"WHERE {predicate} AND date BETWEEN ? AND ?",
        [*params, days[0], days[-1]],
    )
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        day = row["date"]
        key = day.isoformat() if isinstance(day, dt.date) else str(day)[:10]
        acc = grouped.setdefault(key, {"volume": 0, "deliverable_qty": 0, "rows": 0})
        acc["volume"] += int(row["volume"] or 0)
        acc["deliverable_qty"] += int(row["deliverable_qty"] or 0)
        acc["rows"] += 1
    out = {}
    for key, acc in grouped.items():
        volume = acc["volume"]
        out[key] = {
            "volume": volume or None,
            "deliverable_qty": acc["deliverable_qty"] if acc["deliverable_qty"] else None,
            "delivery_pct": (round(acc["deliverable_qty"] / volume * 100, 2)
                             if volume and acc["deliverable_qty"] else None),
        }
    return out


def delivery(symbol: str, dates: Sequence[str] | str, end: str | None = None) -> dict[str, Any]:
    """Deliverable quantity + delivery % per exchange for one or more dates.

    ``dates`` is a list (``["2026-04-13", "2026-04-14"]``) or one date; with
    ``end`` a single date becomes an inclusive calendar span.  Always reads the
    raw ``px_nse`` / ``px_bse`` tables (never adjusted).
    """
    days = _date_list(dates, end)
    identity = _identity(symbol)
    if identity is None:
        return _not_found(
            symbol,
            ["security_master.nse_symbol/symbol_isin_history.symbol",
             "nse_master.symbol", "bse_master.symbol/bse_code"],
            f'resolve("{symbol}") then delivery(<nse_symbol>, ...)',
        )

    nse = _exchange_rows("px_nse", identity, symbol, days)
    bse = _exchange_rows("px_bse", identity, symbol, days)
    day_clause, day_params = core._in_clause([d.isoformat() for d in days])
    trading_days = {
        (row["date"].isoformat() if isinstance(row["date"], dt.date) else str(row["date"])[:10])
        for row in _duck(f"SELECT DISTINCT date FROM px_nse WHERE date IN {day_clause}", day_params)
    }

    rows: list[dict[str, Any]] = []
    totals = {"deliverable_qty": 0, "volume": 0, "days": 0}
    for day in days:
        key = day.isoformat()
        n, b = nse.get(key), bse.get(key)
        missing = [name for name, got in (("NSE", n), ("BSE", b)) if got is None]
        if n and b:
            status = "ok"
        elif n or b:
            status = "partial"
        elif key in trading_days:
            status = "missing_for_symbol"
        else:
            status = "no_trading"
        deliverable = sum(v["deliverable_qty"] or 0 for v in (n, b) if v)
        volume = sum(v["volume"] or 0 for v in (n, b) if v)
        if deliverable:
            totals["deliverable_qty"] += deliverable
            totals["volume"] += volume
            totals["days"] += 1
        rows.append({
            "date": key,
            "status": status,
            "nse": n,
            "bse": b,
            "deliverable_qty_sum": deliverable or None,
            "volume_sum": volume or None,
            "delivery_pct_combined": (round(deliverable / volume * 100, 2)
                                      if volume and deliverable else None),
            "missing_exchanges": missing if status != "ok" else [],
        })

    if not any(row["status"] == "ok" or row["status"] == "partial" for row in rows):
        statuses = {row["status"] for row in rows}
        return _not_found(
            symbol,
            ["px_nse.isin/symbol + date", "px_bse.isin/sc_code + date"],
            'price(symbol, "YYYY-MM-DD") to check the symbol trades on that date',
            company=identity.get("name"), isin=identity.get("isin"),
            dates=[row["date"] for row in rows], statuses=sorted(statuses),
            rows=rows,
        )

    totals["delivery_pct"] = (round(totals["deliverable_qty"] / totals["volume"] * 100, 2)
                              if totals["volume"] else None)
    return {
        "found": True,
        "symbol": identity.get("nse_symbol") or str(symbol).upper(),
        "company": identity.get("name"),
        "isin": identity.get("isin"),
        "bse_code": identity.get("bse_code"),
        "adjusted": False,
        "rows": rows,
        "totals": totals,
        "provenance": _prov({DUCK: ["px_nse", "px_bse"]}, price_basis="raw (unadjusted)"),
    }


# ---------------------------------------------------------------------------
# price_extreme
# ---------------------------------------------------------------------------
_EXTREME = {"high": ("high", "desc", "adj_high"), "low": ("low", "asc", "adj_low")}


def _one_extreme(identity: dict[str, Any], query: str, table: str, exchange: str,
                 kind: str, start: dt.date, end: dt.date, adjusted: bool) -> dict[str, Any] | None:
    column, direction, adj_column = _EXTREME[kind]
    if adjusted:
        column = adj_column
    predicate, params = _key_filter(identity, query, exchange)
    rows = _duck(
        f"SELECT date, {column} AS value FROM {table} WHERE {predicate} "
        f"AND date BETWEEN ? AND ? AND {column} IS NOT NULL "
        f"ORDER BY {column} {direction.upper()}, date LIMIT 1",
        [*params, start, end],
    )
    if not rows:
        return None
    row = rows[0]
    day = row["date"]
    return {"value": row["value"],
            "date": day.isoformat() if isinstance(day, dt.date) else str(day)[:10],
            "exchange": exchange}


def price_extreme(symbol: str, start: str | None = None, end: str | None = None,
                  kind: str = "high", adjusted: bool = False) -> dict[str, Any]:
    """Widest high/low (and its date) across both exchanges, NSE + BSE.

    The default window is calendar YTD: ``start`` = Jan 1 of the snapshot's last
    date, ``end`` = the snapshot's last date (reported as data freshness).
    """
    kind = str(kind or "high").strip().lower()
    if kind not in ("high", "low", "both"):
        raise core.DataError("bad_request", "kind must be high, low or both")
    identity = _identity(symbol)
    if identity is None:
        return _not_found(
            symbol,
            ["security_master.nse_symbol/bse_code", "symbol_isin_history"],
            f'resolve("{symbol}") to get an NSE symbol or BSE code, then retry',
        )

    latest = _latest_snapshot_date()
    start_d = core._parse_date(start, "start") if start else dt.date(latest.year, 1, 1)
    end_d = core._parse_date(end, "end") if end else latest
    if end_d < start_d:
        raise core.DataError("bad_range", f"end {end_d} is before start {start_d}")
    if (end_d - start_d).days > 3660:
        raise core.DataError("bad_range", "window is longer than 10 years; narrow it")

    tables = (("px_nse_adj", "NSE"), ("px_bse_adj", "BSE")) if adjusted else (("px_nse", "NSE"), ("px_bse", "BSE"))
    kinds = ("high", "low") if kind == "both" else (kind,)
    by_kind: dict[str, dict[str, Any]] = {}
    for name in kinds:
        per_exchange = {}
        for table, exchange in tables:
            hit = _one_extreme(identity, symbol, table, exchange, name, start_d, end_d, adjusted)
            if hit:
                per_exchange[exchange] = hit
        if not per_exchange:
            continue
        overall_name = max(per_exchange, key=lambda e: per_exchange[e]["value"]) if name == "high" \
            else min(per_exchange, key=lambda e: per_exchange[e]["value"])
        overall = per_exchange[overall_name]
        by_kind[name] = {
            "value": overall["value"], "date": overall["date"], "exchange": overall["exchange"],
            "overall_exchange": overall_name,
            "by_exchange": per_exchange,
        }

    if not by_kind:
        return _not_found(
            symbol,
            [f"px_nse.isin/symbol + date >= {start_d}", f"px_bse.isin/sc_code + date >= {start_d}"],
            f'price("{symbol}", "{start_d}", "{end_d}") to see which dates do have bars',
            company=identity.get("name"), isin=identity.get("isin"),
            window={"start": start_d.isoformat(), "end": end_d.isoformat()},
        )

    return {
        "found": True,
        "symbol": identity.get("nse_symbol") or str(symbol).upper(),
        "company": identity.get("name"),
        "isin": identity.get("isin"),
        "kind": kind,
        "adjusted": bool(adjusted),
        "window": {"start": start_d.isoformat(), "end": end_d.isoformat(),
                   "default_ytd": not start and not end},
        "snapshot_end": latest.isoformat(),
        "data_freshness": f"prices through {latest.isoformat()} (DuckDB snapshot max date)",
        "extremes": by_kind,
        "provenance": _prov({DUCK: [t for t, _ in tables]},
                            price_basis="adjusted" if adjusted else "raw"),
    }


# ---------------------------------------------------------------------------
# holding
# ---------------------------------------------------------------------------
def _shareholding(identity: dict[str, Any], query: str, as_of: dt.date) -> tuple[dict[str, Any] | None, bool]:
    isins, _ = _nse_keys(identity, query)
    clause, params = core._in_clause(isins)
    symbols, symbol_params = core._in_clause(core._identity_symbols(identity, query))
    rows = _duck(
        "SELECT quarter_end, broadcast_at, submission_date, promoter_pct, public_pct, "
        "revised, isin, symbol FROM shp_index "
        f"WHERE (isin IN {clause} OR upper(symbol) IN {symbols}) AND quarter_end <= ? "
        "ORDER BY quarter_end DESC, broadcast_at DESC LIMIT 12",
        [*params, *symbol_params, as_of.isoformat()],
    )
    if not rows:
        return None, False
    latest_quarter = rows[0]["quarter_end"]
    chosen = next((r for r in rows if r["quarter_end"] == latest_quarter), rows[0])
    return {
        "quarter_end": chosen["quarter_end"],
        "promoter_pct": chosen["promoter_pct"],
        "public_pct": chosen["public_pct"],
        "broadcast_at": chosen["broadcast_at"],
        "submission_date": chosen["submission_date"],
        "revised": chosen["revised"],
        "isin": chosen["isin"],
        "symbol": chosen["symbol"],
        "source": "shp_index",
    }, True


def _ar_candidates(identity: dict[str, Any]) -> list[dict[str, Any]]:
    """Exact share counts stated in annual-report text (shareholding pattern)."""
    isins, _ = _nse_keys(identity, "")
    clause, params = core._in_clause(isins)
    if not params:
        return []
    rows = _sqlite(
        "ar_facts",
        "SELECT doc_id, page, item, value, unit, period, fiscal_year, category, "
        "substr(quote, 1, 200) AS quote FROM ar_facts "
        f"WHERE isin IN {clause} AND unit = 'number' AND value IS NOT NULL "
        "ORDER BY fiscal_year DESC, doc_id DESC LIMIT 400",
        params,
    )
    out = []
    for row in rows:
        item = str(row["item"] or "")
        low = item.lower()
        if "share" not in low or not _SHARE_TOTAL.search(low) or _SHARE_TOTAL_BAD.search(low):
            continue
        try:
            value = int(round(float(row["value"])))
        except (TypeError, ValueError):
            continue
        if value < 10_000:
            continue
        out.append({
            "value": value,
            "source": "ar_facts",
            "kind": "exact",
            "date": row["period"] or (f"FY{row['fiscal_year']}" if row["fiscal_year"] else None),
            "fiscal_year": row["fiscal_year"],
            "doc_id": row["doc_id"],
            "page": row["page"],
            "item": item,
            "quote": row["quote"],
        })
    return out


def _xbrl_candidate(identity: dict[str, Any]) -> dict[str, Any] | None:
    """Paid-up capital / face value: a count, but reported in thousands."""
    isins, _ = _nse_keys(identity, "")
    clause, params = core._in_clause(isins)
    if not params:
        return None
    filings = _sqlite(
        "results_xbrl",
        "SELECT f.file, f.period_end, f.symbol, f.consolidated FROM filings f "
        "JOIN filings_isin fi ON fi.file = f.file "
        f"WHERE fi.isin IN {clause} ORDER BY f.period_end DESC LIMIT 4",
        params,
    )
    if not filings:
        return None
    file_clause, file_params = core._in_clause([f["file"] for f in filings])
    facts = _sqlite(
        "results_xbrl",
        "SELECT file, concept, context, value, unit FROM facts "
        f"WHERE file IN {file_clause} AND concept IN "
        "('PaidUpValueOfEquityShareCapital','FaceValueOfEquityShareCapital') AND value IS NOT NULL",
        file_params,
    )
    by_file: dict[str, dict[str, float]] = {}
    for row in facts:
        bucket = by_file.setdefault(row["file"], {})
        bucket.setdefault(row["concept"], float(row["value"]))
    period = {f["file"]: f["period_end"] for f in filings}
    for filing in filings:  # newest first
        values = by_file.get(filing["file"]) or {}
        paid = values.get("PaidUpValueOfEquityShareCapital")
        face = values.get("FaceValueOfEquityShareCapital")
        if not paid or not face:
            continue
        derived = int(round(paid / face))
        return {
            "value": derived,
            "source": "results_xbrl",
            "kind": "derived",
            "date": period.get(filing["file"]),
            "doc_id": filing["file"],
            "page": None,
            "item": "PaidUpValueOfEquityShareCapital / FaceValueOfEquityShareCapital",
            "quote": f"{paid:,.0f} / {face:,.2f} = {derived:,} shares",
            "paid_up_value": paid,
            "face_value": face,
            "rounded_upstream": paid % 1000 == 0,
        }
    return None


def holding(symbol: str, as_of: str | None = None) -> dict[str, Any]:
    """Promoter/public %, total shares and every share-count candidate found.

    Shareholding comes from ``shp_index`` (latest quarter <= ``as_of``); the
    total share count prefers an exact integer stated in an annual-report
    shareholding pattern over an XBRL paid-up/face-value division (which is
    rounded because paid-up capital is reported in thousands).
    """
    as_of_d = core._parse_date(as_of, "as_of") or dt.date.today()
    identity = _identity(symbol)
    if identity is None:
        return _not_found(
            symbol,
            ["security_master.nse_symbol/bse_code", "shp_index.symbol/isin"],
            f'resolve("{symbol}") then holding(<nse_symbol>)',
        )

    shareholding, has_shp = _shareholding(identity, symbol, as_of_d)
    candidates = _ar_candidates(identity)
    xbrl = _xbrl_candidate(identity)
    if xbrl:
        candidates.append(xbrl)

    # Plausibility guard: a candidate within 20% of the XBRL-derived count is the
    # real total; this drops prose rows such as "Total Shareholders" or
    # "Total number of shares held by Promoters" that slip past the name filter.
    reference = xbrl["value"] if xbrl else None
    exact = [c for c in candidates if c["kind"] == "exact"
             and (reference is None or abs(c["value"] - reference) <= 0.2 * reference)]
    exact.sort(key=lambda c: (c.get("fiscal_year") or 0, c["doc_id"] or 0), reverse=True)
    best = exact[0] if exact else (xbrl or (candidates[0] if candidates else None))

    xbrl_rounded = bool(xbrl and best and best["kind"] == "exact" and best["value"] != xbrl["value"])

    if not has_shp and not candidates:
        return _not_found(
            symbol,
            [f"shp_index.isin/symbol + quarter_end <= {as_of_d}",
             "ar_facts.isin + category='shareholding'",
             "results_xbrl.filings_isin.isin -> facts.concept"],
            f'facts("{symbol}", kind="ar") for the annual-report statements, '
            'or price(symbol, date) if only prices are needed',
            company=identity.get("name"), isin=identity.get("isin"),
        )

    notes = []
    if not has_shp:
        notes.append(f"shp_index has no quarter_end <= {as_of_d} for this ISIN/symbol")
    notes.append("shp_index carries promoter_pct/public_pct only, no share-count column")
    if xbrl and not exact:
        notes.append("no exact AR share count passed the plausibility guard; total_shares is the "
                     "XBRL paid-up/face division, which is rounded because paid-up capital is "
                     "reported in thousands")
    if xbrl_rounded:
        notes.append(f"XBRL-derived {xbrl['value']:,} differs from the exact "
                     f"{best['value']:,}: trust the AR figure")

    return {
        "found": True,
        "symbol": identity.get("nse_symbol") or str(symbol).upper(),
        "company": identity.get("name"),
        "isin": identity.get("isin"),
        "as_of": as_of_d.isoformat(),
        "shareholding": shareholding,
        "promoter_pct": (shareholding or {}).get("promoter_pct"),
        "public_pct": (shareholding or {}).get("public_pct"),
        "total_shares": best["value"] if best else None,
        "best_share_count": best["value"] if best else None,
        "best_share_count_source": ({k: v for k, v in best.items() if k not in ("paid_up_value",)}
                                    if best else None),
        "share_count_candidates": candidates,
        "xbrl_rounded": xbrl_rounded,
        "notes": notes,
        "provenance": _prov({DUCK: ["shp_index"], "ar_facts": ["ar_facts"],
                             "results_xbrl": ["filings", "filings_isin", "facts"]}),
    }
