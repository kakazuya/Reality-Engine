"""
BSE Bhavcopy Backfill Pipeline Module
=====================================
Gives BSE-only active scrips price history.

The NSE deliverable Bhavcopy is the sole feed that populates
``daily_price_delivery``.  After the universe expansion in
``ingestion/master_sync.py`` a large block of BSE-only actives now live in
``master_companies`` but have **no** price rows, so every downstream consumer
(technicals, screening, explainers) is blind to them.

Two BSE sources feed this module:

* **UDiFF CM Bhavcopy** (``BhavCopy_BSE_CM_0_0_0_YYYYMMDD_F_0000.CSV``) — the
  current daily file, ISIN-keyed, covers the last 250 sessions and onward.
* **Legacy archive** (``EQ<DDMMYY>_CSV.ZIP``) — the pre-UDiFF daily file, has
  **no** ISIN column and is therefore joined ``SC_CODE -> master_companies.bse_code``.
  Verified live for 2006-06-16 .. 2024-04-18 (retired by 2024-07-18).

Neither file carries delivery data, so the delivery columns are written in the
same shape the NSE path writes them (0 for the NOT NULL delivery fields, NULL
for the derived ratios) and are left for the technical engine to recompute.

Contract
--------
* Only rows whose ISIN already exists in ``master_companies`` are inserted
  (FK safety); unknown-ISIN rows are counted, never inserted.  A legacy row
  whose ``SC_CODE`` matches no ``master_companies.bse_code`` is counted
  ``rows_skipped_unknown_code``.
* A pre-existing ``(date, symbol)`` row is never overwritten: the NSE feed
  carries delivery data BSE lacks, so BSE is strictly a gap-filler.  Skips are
  counted.
* Up-to-date by design: rows not yet admitted by the universe sync are counted
  and skipped, so the whole backfill is re-runnable after that sync.
* Fail-closed: a fetch/parse failure on one date or one row is recorded in
  ``errors`` and never aborts the run.
"""

import io
import logging
import zipfile
from datetime import date as _date, datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import pandas as pd

from reality_engine.ingestion.bse_client import (
    BSE_LEGACY_BHAVCOPY_URL_TEMPLATE,
    bse_bytes,
    bse_client,
)
from reality_engine.db.repository import repo

logger = logging.getLogger("reality_engine.bse_backfill")

# Exchange weekday holidays, shared with the rest of the pipeline (NSE and BSE
# observe the same holiday list).  Skipping them client-side avoids a bhavcopy
# probe that can only come back as the SPA shell.  The set is refreshed each
# December; an unknown holiday simply costs one extra probe.
try:  # pragma: no cover - trivial import guard
    from reality_engine.pipeline.data_audit import NSE_WEEKDAY_HOLIDAYS as _KNOWN_WEEKDAY_HOLIDAYS
except Exception:  # pragma: no cover
    _KNOWN_WEEKDAY_HOLIDAYS = frozenset()  # type: ignore[assignment]

# Latest session BSE published in the legacy (pre-UDiFF) archive layout.
# Verified live 2026-09-19: EQ<DDMMYY>_CSV.ZIP returns a real ZIP up to
# 2024-04-18; the layout was retired by 2024-07-18.  Scanning past this date
# can only return the SPA shell, so ranges are clamped to it.
_LEGACY_LAST_DATE = _date(2024, 4, 18)

# Legacy NET_TURNOV is rupees (verified against a known scrip's NSE turnover);
# daily_price_delivery.turnover_lacs is lacs, so divide.
_LEGACY_TURNOVER_DIVISOR = 100000.0

# Safety cap on a single legacy scan: 5 years of weekdays is ~1,300 probes.
_MAX_LEGACY_WINDOW_DAYS = 5 * 365

# A long window is tens of thousands of rows per session, so parsed records are
# handed to the write path in bounded batches instead of one multi-million-row
# list (a 5-year legacy scan would otherwise hold millions of dicts in memory).
_FLUSH_RECORDS = 50_000

# Tokens that mean "no value" in a UDiFF cell.
_BLANK_TOKENS = {"", "-", "--", "na", "n/a", "nan", "null", "none"}

# Columns written to daily_price_delivery — identical set/order to the NSE
# backfill so downstream reads see one consistent row shape.
_INSERT_COLUMNS = [
    "date", "symbol", "isin", "series", "open", "high", "low", "close", "prev_close",
    "change_pct", "total_volume", "turnover_lacs", "num_trades",
    "deliverable_volume", "delivery_pct", "delivery_spike_ratio",
    "delivery_conviction_score", "sma_20", "sma_50", "sma_200", "rsi_14",
    "high_52w", "low_52w", "distance_from_52w_high_pct",
]

_COUNT_KEYS = (
    "dates_requested",
    "dates_fetched",
    "rows_seen",
    "rows_inserted",
    "rows_skipped_existing",
    "rows_skipped_unknown_isin",
    "rows_skipped_unknown_code",
)


# ---------------------------------------------------------------------------
# Cell helpers
# ---------------------------------------------------------------------------
def _clean_str(value: Any) -> str:
    """Normalize a raw UDiFF cell to a stripped string ('' when absent)."""
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def _to_float(value: Any) -> Optional[float]:
    """Parse a numeric cell; returns None for blanks, '-' and junk."""
    s = _clean_str(value)
    if s.lower() in _BLANK_TOKENS:
        return None
    try:
        v = float(s.replace(",", ""))
    except (TypeError, ValueError):
        return None
    if pd.isna(v):
        return None
    return v


def _to_int(value: Any) -> int:
    """Parse an integer cell; blanks/junk collapse to 0 (NOT NULL columns)."""
    f = _to_float(value)
    if f is None:
        return 0
    return int(f)


def _coerce_date(value: Any, fallback: datetime) -> str:
    """Resolve a UDiFF TradDt cell to the DB's 'YYYY-MM-DD' text form."""
    s = _clean_str(value)
    if s:
        for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d"):
            try:
                return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
            except ValueError:
                continue
    return fallback.strftime("%Y-%m-%d")


def _change_pct(close: float, prev_close: Optional[float]) -> float:
    """Percent change vs the previous close; 0.0 when there is no usable base."""
    if prev_close is not None and prev_close > 0:
        return round(((close - prev_close) / prev_close) * 100.0, 2)
    return 0.0


def _norm_code(value: Any) -> str:
    """Normalize a BSE scrip code for joining ('0500002' / '500002.0' -> '500002')."""
    s = _clean_str(value)
    if not s:
        return ""
    if s.endswith(".0"):
        s = s[:-2]
    if s.isdigit():
        return str(int(s))
    return s


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------
def parse_bhavcopy_frame(df: Optional[pd.DataFrame], requested_date: datetime) -> List[Dict[str, Any]]:
    """Normalize a raw BSE UDiFF CM frame into daily_price_delivery-shaped dicts.

    Rows with no usable close price (blank / '-') or no ISIN are dropped; they
    carry no price history and would only pollute the table.
    """
    records: List[Dict[str, Any]] = []
    if df is None or df.empty:
        return records

    frame = df.copy()
    frame.columns = [str(c).strip() for c in frame.columns]

    for _, raw in frame.iterrows():
        isin = _clean_str(raw.get("ISIN"))
        close = _to_float(raw.get("ClsPric"))
        if not isin or close is None:
            continue

        open_ = _to_float(raw.get("OpnPric"))
        high = _to_float(raw.get("HghPric"))
        low = _to_float(raw.get("LwPric"))
        prev_close = _to_float(raw.get("PrvsClsgPric"))
        turnover = _to_float(raw.get("TtlTrfVal"))

        symbol = _clean_str(raw.get("TckrSymb"))
        records.append({
            "date": _coerce_date(raw.get("TradDt"), requested_date),
            "symbol": symbol,
            "isin": isin,
            "series": _clean_str(raw.get("SctySrs")) or "EQ",
            "open": open_ if open_ is not None else 0.0,
            "high": high if high is not None else 0.0,
            "low": low if low is not None else 0.0,
            "close": close,
            "prev_close": prev_close if prev_close is not None else 0.0,
            "change_pct": _change_pct(close, prev_close),
            "total_volume": _to_int(raw.get("TtlTradgVol")),
            # BSE TtlTrfVal is in rupees; the NSE column is in lacs.
            "turnover_lacs": round((turnover / 100000.0), 2) if turnover is not None else 0.0,
            "num_trades": _to_int(raw.get("TtlNbOfTxsExctd")),
        })
    return records


def parse_legacy_frame(df: Optional[pd.DataFrame], requested_date: datetime) -> List[Dict[str, Any]]:
    """Normalize a legacy ``EQ<DDMMYY>.CSV`` frame (keyed by ``SC_CODE``, no ISIN).

    The returned dicts carry ``bse_code`` instead of ``isin``/``symbol``; the
    write path resolves those from ``master_companies`` (the legacy archive has
    neither an ISIN nor a scrip ticker, only the numeric code and the name).
    Rows with no usable close price or no code are dropped.
    """
    records: List[Dict[str, Any]] = []
    if df is None or df.empty:
        return records

    frame = df.copy()
    frame.columns = [str(c).strip().lstrip("\ufeff") for c in frame.columns]

    for _, raw in frame.iterrows():
        code = _norm_code(raw.get("SC_CODE"))
        close = _to_float(raw.get("CLOSE"))
        if not code or close is None:
            continue

        open_ = _to_float(raw.get("OPEN"))
        high = _to_float(raw.get("HIGH"))
        low = _to_float(raw.get("LOW"))
        prev_close = _to_float(raw.get("PREVCLOSE"))
        turnover = _to_float(raw.get("NET_TURNOV"))

        records.append({
            "date": requested_date.strftime("%Y-%m-%d"),
            "bse_code": code,
            "series": _clean_str(raw.get("SC_GROUP")) or "EQ",
            "open": open_ if open_ is not None else 0.0,
            "high": high if high is not None else 0.0,
            "low": low if low is not None else 0.0,
            "close": close,
            "prev_close": prev_close if prev_close is not None else 0.0,
            "change_pct": _change_pct(close, prev_close),
            "total_volume": _to_int(raw.get("NO_OF_SHRS")),
            "turnover_lacs": (round(turnover / _LEGACY_TURNOVER_DIVISOR, 2)
                              if turnover is not None else 0.0),
            "num_trades": _to_int(raw.get("NO_TRADES")),
        })
    return records


# ---------------------------------------------------------------------------
# Fetchers
# ---------------------------------------------------------------------------
def _default_fetcher(target_date: datetime) -> Optional[pd.DataFrame]:
    """Live fetcher — the BSE UDiFF CM Bhavcopy for a session."""
    return bse_client.fetch_bhavcopy(target_date)


def legacy_zip_url(target_date: datetime) -> str:
    """Legacy archive URL for a session (``EQ<DDMMYY>_CSV.ZIP``)."""
    return BSE_LEGACY_BHAVCOPY_URL_TEMPLATE.format(ddmmyy=target_date.strftime("%d%m%y"))


def fetch_legacy_zip(target_date: datetime, *, session: Any = None) -> Optional[pd.DataFrame]:
    """Download and open the legacy ``EQ<DDMMYY>_CSV.ZIP`` for a session.

    Returns None when BSE has no archive for that date (the retired layout
    answers with the SPA shell), when the download is not a ZIP, or when the
    member is not the legacy bhavcopy (``SC_CODE`` header).
    """
    url = legacy_zip_url(target_date)
    body = bse_bytes(url, session=session)
    if body is None:
        logger.info("No legacy BSE archive for %s", target_date.strftime("%Y-%m-%d"))
        return None

    wanted = f"EQ{target_date.strftime('%d%m%y')}.CSV"
    try:
        with zipfile.ZipFile(io.BytesIO(body)) as zf:
            names = zf.namelist()
            member = wanted if wanted in names else next(
                (n for n in names if n.upper().endswith(".CSV")), None
            )
            if member is None:
                logger.warning("Legacy BSE archive %s has no CSV member (%s)", url, names[:5])
                return None
            with zf.open(member) as fh:
                df = pd.read_csv(io.BytesIO(fh.read()))
    except Exception as e:
        logger.warning("Legacy BSE archive %s unreadable: %s", url, e)
        return None

    df.columns = [str(c).strip().lstrip("\ufeff") for c in df.columns]
    if df.empty or "SC_CODE" not in df.columns:
        logger.warning("Legacy BSE archive %s is not a legacy bhavcopy (columns=%s)",
                       url, list(df.columns)[:5])
        return None
    return df


def _default_legacy_fetcher(target_date: datetime) -> Optional[pd.DataFrame]:
    """Live fetcher — the legacy ``EQ<DDMMYY>_CSV.ZIP`` archive for a session."""
    return fetch_legacy_zip(target_date)


def _is_session(day: _date, holidays: Set[str]) -> bool:
    """Mon-Fri and not a known exchange holiday."""
    if day.weekday() >= 5:
        return False
    return day.isoformat() not in holidays


def _as_datetime(value: Any) -> Optional[datetime]:
    """Coerce date/datetime/'YYYY-MM-DD' to a midnight datetime (None when unusable)."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(hour=0, minute=0, second=0, microsecond=0)
    if isinstance(value, _date):
        return datetime(value.year, value.month, value.day)
    try:
        return datetime.strptime(str(value), "%Y-%m-%d")
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Universe resolution
# ---------------------------------------------------------------------------
def _load_master(manager: Any, result: Dict[str, Any], label: str):
    """Read the ISIN/symbol/code maps the write path needs.

    Returns ``(known_isins, isin_symbol, code_index)`` or None when the master
    lookup itself failed (recorded in ``errors``); ``code_index`` maps a
    normalized BSE scrip code to ``(isin, symbol)`` and only holds
    ``master_companies`` rows that actually carry a code and a symbol.
    """
    try:
        with manager.session() as conn:
            rows = conn.execute(
                "SELECT isin, nse_symbol, bse_code FROM master_companies"
            ).fetchall()
    except Exception as e:
        result["errors"].append({"date": None, "source": label,
                                 "error": f"master lookup failed: {e}"})
        return None

    known_isins: Set[str] = set()
    isin_symbol: Dict[str, str] = {}
    code_index: Dict[str, Tuple[str, str]] = {}
    for r in rows:
        isin = (r["isin"] or "").strip()
        if not isin:
            continue
        known_isins.add(isin)
        symbol = (r["nse_symbol"] or "").strip()
        if symbol:
            isin_symbol[isin] = symbol
        code = _norm_code(r["bse_code"])
        if code and symbol:
            code_index[code] = (isin, symbol)
    return known_isins, isin_symbol, code_index


# ---------------------------------------------------------------------------
# Write path (skip-if-present + bulk insert)
# ---------------------------------------------------------------------------
def _existing_keys(conn: Any, dates: List[str]) -> Tuple[Set[Tuple[str, str]], Set[Tuple[str, str]]]:
    """``(date, symbol)`` and ``(date, isin)`` keys already in the price table."""
    by_symbol: Set[Tuple[str, str]] = set()
    by_isin: Set[Tuple[str, str]] = set()
    for i in range(0, len(dates), 500):
        chunk = dates[i:i + 500]
        placeholders = ",".join("?" for _ in chunk)
        for row in conn.execute(
            f"SELECT date, symbol, isin FROM daily_price_delivery WHERE date IN ({placeholders})",
            chunk,
        ):
            day = str(row["date"])
            if row["symbol"]:
                by_symbol.add((day, row["symbol"]))
            if row["isin"]:
                by_isin.add((day, row["isin"]))
    return by_symbol, by_isin


def _shape_row(rec: Dict[str, Any]) -> None:
    """Fill the columns the BSE feed cannot know (mirrors the NSE row shape).

    ``deliverable_volume`` / ``delivery_pct`` are NOT NULL, so they take 0 (as
    the NSE path does for a session with no delivery row); everything derived
    stays NULL and is the technical engine's to compute.
    """
    rec["deliverable_volume"] = 0
    rec["delivery_pct"] = 0.0
    for derived in ("delivery_spike_ratio", "delivery_conviction_score",
                    "sma_20", "sma_50", "sma_200", "rsi_14",
                    "high_52w", "low_52w", "distance_from_52w_high_pct"):
        rec[derived] = None


def _write_records(records: List[Dict[str, Any]], manager: Any, result: Dict[str, Any],
                   dry_run: bool, label: str) -> None:
    """Skip-if-present, shape, and bulk-insert records; updates ``result`` in place.

    The existence check and the insert share one transaction so a concurrent
    writer cannot slip an NSE row between them and be overwritten.
    """
    if not records:
        return

    deduped: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for rec in records:
        deduped.setdefault((rec["date"], rec["symbol"]), rec)
    ordered = list(deduped.values())
    dates = sorted({rec["date"] for rec in ordered})

    try:
        with manager.session() as conn:
            existing_sym, existing_isin = _existing_keys(conn, dates)
            to_insert: List[Dict[str, Any]] = []
            for rec in ordered:
                if ((rec["date"], rec["symbol"]) in existing_sym
                        or (rec["date"], rec["isin"]) in existing_isin):
                    result["rows_skipped_existing"] += 1
                    continue
                to_insert.append(rec)

            # Shape first: the BSE feed cannot know the delivery/derived columns.
            for rec in to_insert:
                _shape_row(rec)

            if not dry_run and to_insert:
                df_out = pd.DataFrame(to_insert)[_INSERT_COLUMNS]
                df_out.to_sql("temp_bse_bhav", conn, if_exists="replace", index=False)
                conn.execute("""
                    INSERT OR REPLACE INTO daily_price_delivery (
                        date, symbol, isin, series, open, high, low, close, prev_close,
                        change_pct, total_volume, turnover_lacs, num_trades,
                        deliverable_volume, delivery_pct, delivery_spike_ratio,
                        delivery_conviction_score, sma_20, sma_50, sma_200, rsi_14,
                        high_52w, low_52w, distance_from_52w_high_pct
                    ) SELECT * FROM temp_bse_bhav
                """)
                conn.execute("DROP TABLE IF EXISTS temp_bse_bhav")
    except Exception as e:
        result["errors"].append({"date": None, "source": label, "error": f"insert failed: {e}"})
        return

    for rec in to_insert:
        result["rows_inserted"] += 1
        result["per_date_inserted"][rec["date"]] = result["per_date_inserted"].get(rec["date"], 0) + 1


# ---------------------------------------------------------------------------
# UDiFF (current) range
# ---------------------------------------------------------------------------
def _candidate_sessions(
    days: int,
    end_date: Optional[Any],
    fetcher: Callable[[datetime], Optional[pd.DataFrame]],
    result: Dict[str, Any],
    holidays: Set[str],
) -> List[Tuple[datetime, pd.DataFrame]]:
    """Scan backwards over trading days collecting up to ``days`` sessions with data.

    Weekends and known holidays are skipped before any request; every other
    weekday is probed and counted in ``dates_requested``.  ``dates_fetched``
    counts the probes that returned a non-empty file — a session BSE has no
    file for (e.g. an unaudited holiday) simply does not count.  A raise from
    the fetcher is isolated into ``errors`` and scanning continues.
    """
    cursor = _as_datetime(end_date)
    if cursor is None:
        if end_date is not None:
            logger.warning("BSE backfill: unusable end_date %r — scanning from now", end_date)
        cursor = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

    found: List[Tuple[datetime, pd.DataFrame]] = []
    max_scan = max(days * 3, days)
    scanned = 0
    while len(found) < days and scanned < max_scan:
        if _is_session(cursor.date(), holidays):
            result["dates_requested"] += 1
            try:
                df = fetcher(cursor)
            except Exception as e:  # per-date isolation
                result["errors"].append({
                    "date": cursor.strftime("%Y-%m-%d"), "source": "udiff", "error": str(e),
                })
                df = None
            if df is not None and not df.empty:
                found.append((cursor, df))
        cursor -= timedelta(days=1)
        scanned += 1

    found.sort(key=lambda pair: pair[0])
    return found


def backfill_bse_range(
    days: int = 250,
    end_date: Optional[Any] = None,
    db: Any = None,
    dry_run: bool = True,
    fetcher: Optional[Callable[[datetime], Optional[pd.DataFrame]]] = None,
    holidays: Optional[Set[str]] = None,
) -> Dict[str, Any]:
    """Backfill BSE UDiFF price history for the most recent ``days`` sessions.

    Args:
        days: number of sessions to target (scanned backwards over weekdays).
        end_date: newest session to consider (datetime/date/'YYYY-MM-DD'); default now.
        db: DatabaseManager (or Repository) to use; defaults to the live repo.
        dry_run: when True nothing is written — ``rows_inserted`` reports how many
            rows *would* have been inserted.
        fetcher: injectable ``callable(datetime) -> DataFrame|None`` for tests.
        holidays: extra 'YYYY-MM-DD' holiday strings (on top of the shared calendar).

    Returns:
        dict with ``dates_requested``, ``dates_fetched``, ``rows_seen``,
        ``rows_inserted``, ``rows_skipped_existing``, ``rows_skipped_unknown_isin``,
        ``rows_skipped_unknown_code`` (always 0 here), ``errors`` and
        ``per_date_inserted`` (date -> inserted count).
    """
    manager = getattr(db, "db", db) or repo.db
    fetch = fetcher or _default_fetcher
    holiday_set = set(_KNOWN_WEEKDAY_HOLIDAYS) | set(holidays or ())

    result: Dict[str, Any] = {key: 0 for key in _COUNT_KEYS}
    result["errors"] = []
    result["per_date_inserted"] = {}

    sessions = _candidate_sessions(days, end_date, fetch, result, holiday_set)
    result["dates_fetched"] = len(sessions)
    if not sessions:
        logger.warning("BSE backfill: no sessions with data found in range.")
        return result

    master = _load_master(manager, result, "udiff")
    if master is None:
        return result
    known_isins, isin_symbol, _ = master

    pending: List[Dict[str, Any]] = []
    for session_date, frame in sessions:
        try:
            records = parse_bhavcopy_frame(frame, session_date)
        except Exception as e:  # per-date isolation
            result["errors"].append({
                "date": session_date.strftime("%Y-%m-%d"), "source": "udiff", "error": str(e),
            })
            continue

        # Every data row in the file is "seen"; rows dropped for a blank close
        # price / missing ISIN are seen but never reach a skip bucket.
        result["rows_seen"] += len(frame)
        for rec in records:
            try:
                if rec["isin"] not in known_isins:
                    result["rows_skipped_unknown_isin"] += 1
                    continue
                # Prefer the master's ticker so dual-listed scrips collapse onto
                # the NSE symbol (and are therefore seen as already-present).
                rec["symbol"] = isin_symbol.get(rec["isin"]) or rec["symbol"]
                if not rec["symbol"]:
                    logger.debug("BSE row without symbol dropped: isin=%s", rec["isin"])
                    continue
                pending.append(rec)
            except Exception as e:  # per-row isolation
                result["errors"].append({
                    "date": rec.get("date"), "symbol": rec.get("symbol"),
                    "source": "udiff", "error": str(e),
                })
        if len(pending) >= _FLUSH_RECORDS:
            _write_records(pending, manager, result, dry_run, "udiff")
            pending = []

    _write_records(pending, manager, result, dry_run, "udiff")

    logger.info(
        "BSE UDiFF backfill (dry_run=%s): %d sessions, %d seen, %d inserted, "
        "%d skipped-existing, %d unknown-isin, %d errors.",
        dry_run, result["dates_fetched"], result["rows_seen"], result["rows_inserted"],
        result["rows_skipped_existing"], result["rows_skipped_unknown_isin"],
        len(result["errors"]),
    )
    return result


# ---------------------------------------------------------------------------
# Legacy (pre-UDiFF) range
# ---------------------------------------------------------------------------
def backfill_legacy_range(
    years: int = 1,
    end_date: Optional[Any] = None,
    db: Any = None,
    dry_run: bool = True,
    fetcher: Optional[Callable[[datetime], Optional[pd.DataFrame]]] = None,
    holidays: Optional[Set[str]] = None,
) -> Dict[str, Any]:
    """Backfill a bounded window of the legacy ``EQ<DDMMYY>_CSV.ZIP`` archive.

    Args:
        years: window length in years (one year at a time keeps the probe count
            sane: ~260 weekday requests).  Clamped to 5 years.
        end_date: newest legacy session to probe; default and hard ceiling is
            ``_LEGACY_LAST_DATE`` (the layout was retired after it).
        db / dry_run / fetcher / holidays: as in :func:`backfill_bse_range`.

    Returns the same count shape as :func:`backfill_bse_range`, with
    ``rows_skipped_unknown_code`` counting legacy rows whose ``SC_CODE`` maps to
    no ``master_companies`` row (or to a row with no symbol to key on).
    """
    manager = getattr(db, "db", db) or repo.db
    fetch = fetcher or _default_legacy_fetcher
    holiday_set = set(_KNOWN_WEEKDAY_HOLIDAYS) | set(holidays or ())

    result: Dict[str, Any] = {key: 0 for key in _COUNT_KEYS}
    result["errors"] = []
    result["per_date_inserted"] = {}

    end_dt = _as_datetime(end_date) or datetime.combine(_LEGACY_LAST_DATE, datetime.min.time())
    ceiling = datetime.combine(_LEGACY_LAST_DATE, datetime.min.time())
    if end_dt > ceiling:
        logger.info("Legacy BSE archive retired after %s; clamping end date", _LEGACY_LAST_DATE)
        end_dt = ceiling
    window_days = max(1, int(years)) * 365
    if window_days > _MAX_LEGACY_WINDOW_DAYS:
        logger.warning("Legacy window clamped to %d days", _MAX_LEGACY_WINDOW_DAYS)
        window_days = _MAX_LEGACY_WINDOW_DAYS
    start_dt = end_dt - timedelta(days=window_days)

    master = _load_master(manager, result, "legacy")
    if master is None:
        return result
    _, _, code_index = master

    pending: List[Dict[str, Any]] = []
    cursor = start_dt
    while cursor <= end_dt:
        if _is_session(cursor.date(), holiday_set):
            result["dates_requested"] += 1
            try:
                frame = fetch(cursor)
            except Exception as e:  # per-date isolation
                result["errors"].append({
                    "date": cursor.strftime("%Y-%m-%d"), "source": "legacy", "error": str(e),
                })
                frame = None
            if frame is not None and not frame.empty:
                result["dates_fetched"] += 1
                try:
                    records = parse_legacy_frame(frame, cursor)
                except Exception as e:
                    result["errors"].append({
                        "date": cursor.strftime("%Y-%m-%d"), "source": "legacy", "error": str(e),
                    })
                    records = []
                result["rows_seen"] += len(frame)
                for rec in records:
                    try:
                        hit = code_index.get(rec["bse_code"])
                        if hit is None:
                            result["rows_skipped_unknown_code"] += 1
                            continue
                        rec["isin"], rec["symbol"] = hit
                        pending.append(rec)
                    except Exception as e:  # per-row isolation
                        result["errors"].append({
                            "date": rec.get("date"), "code": rec.get("bse_code"),
                            "source": "legacy", "error": str(e),
                        })
        if len(pending) >= _FLUSH_RECORDS:
            _write_records(pending, manager, result, dry_run, "legacy")
            pending = []
        cursor += timedelta(days=1)

    _write_records(pending, manager, result, dry_run, "legacy")

    logger.info(
        "BSE legacy backfill (dry_run=%s): %d/%d sessions with data, %d seen, "
        "%d inserted, %d skipped-existing, %d unknown-code, %d errors.",
        dry_run, result["dates_fetched"], result["dates_requested"], result["rows_seen"],
        result["rows_inserted"], result["rows_skipped_existing"],
        result["rows_skipped_unknown_code"], len(result["errors"]),
    )
    return result


# ---------------------------------------------------------------------------
# Unified entry point
# ---------------------------------------------------------------------------
def backfill_bse(
    days: int = 250,
    legacy_years: int = 0,
    end_date: Optional[Any] = None,
    db: Any = None,
    dry_run: bool = True,
    fetcher: Optional[Callable[[datetime], Optional[pd.DataFrame]]] = None,
    legacy_fetcher: Optional[Callable[[datetime], Optional[pd.DataFrame]]] = None,
    holidays: Optional[Set[str]] = None,
) -> Dict[str, Any]:
    """Backfill every BSE security: current UDiFF sessions plus optional legacy years.

    Args:
        days: UDiFF sessions to target (default: the last 250 trading sessions).
        legacy_years: years of the retired ``EQ<DDMMYY>_CSV.ZIP`` archive to add
            (0 = skip; 1 = one bounded year at a time).
        end_date: newest UDiFF session (default now); the legacy window is
            clamped to ``_LEGACY_LAST_DATE``.
        db: DatabaseManager (or Repository); defaults to the live repo.
        dry_run: True writes nothing and only counts what would be inserted.
        fetcher / legacy_fetcher: injectable per-phase frame fetchers for tests.
        holidays: extra 'YYYY-MM-DD' holiday strings.

    Returns:
        ``dates_requested``, ``dates_fetched``, ``rows_seen``, ``rows_inserted``,
        ``rows_skipped_existing``, ``rows_skipped_unknown_isin``,
        ``rows_skipped_unknown_code``, ``errors[]`` (each tagged with its
        ``source``), ``per_date_inserted``, plus ``udiff`` / ``legacy``
        sub-results and ``dry_run``.  Never raises.
    """
    manager: Any = None
    manager_error: Optional[str] = None
    try:
        manager = getattr(db, "db", db) or repo.db
    except Exception as e:  # a broken db handle must not escape either
        manager_error = f"db resolution failed: {e}"
        logger.error("BSE backfill: %s", manager_error)

    result: Dict[str, Any] = {key: 0 for key in _COUNT_KEYS}
    result["errors"] = []
    result["per_date_inserted"] = {}
    result["dry_run"] = dry_run

    if manager_error is not None:
        for source in ("udiff", "legacy"):
            result[source] = {key: 0 for key in _COUNT_KEYS}
            result[source]["errors"] = [{"date": None, "source": source, "error": manager_error}]
            result[source]["per_date_inserted"] = {}
        result["errors"] = [dict(result[s]["errors"][0]) for s in ("udiff", "legacy")]
        return result

    try:
        udiff = backfill_bse_range(
            days=days, end_date=end_date, db=manager, dry_run=dry_run,
            fetcher=fetcher, holidays=holidays,
        )
    except Exception as e:  # never raise out of the backfill
        logger.error("BSE UDiFF backfill aborted: %s", e)
        udiff = {key: 0 for key in _COUNT_KEYS}
        udiff["errors"] = [{"date": None, "source": "udiff", "error": str(e)}]
        udiff["per_date_inserted"] = {}
    result["udiff"] = udiff

    legacy: Dict[str, Any] = {key: 0 for key in _COUNT_KEYS}
    legacy["errors"] = []
    legacy["per_date_inserted"] = {}
    if legacy_years:
        try:
            legacy = backfill_legacy_range(
                years=legacy_years, end_date=end_date, db=manager, dry_run=dry_run,
                fetcher=legacy_fetcher, holidays=holidays,
            )
        except Exception as e:
            logger.error("BSE legacy backfill aborted: %s", e)
            legacy["errors"] = [{"date": None, "source": "legacy", "error": str(e)}]
    result["legacy"] = legacy

    for key in _COUNT_KEYS:
        result[key] = udiff.get(key, 0) + legacy.get(key, 0)
    result["errors"] = list(udiff.get("errors") or []) + list(legacy.get("errors") or [])
    for phase in (udiff, legacy):
        for day, count in (phase.get("per_date_inserted") or {}).items():
            result["per_date_inserted"][day] = result["per_date_inserted"].get(day, 0) + count

    logger.info(
        "BSE backfill (dry_run=%s): %d sessions, %d seen, %d inserted, "
        "%d skipped-existing, %d unknown-isin, %d unknown-code, %d errors.",
        dry_run, result["dates_fetched"], result["rows_seen"], result["rows_inserted"],
        result["rows_skipped_existing"], result["rows_skipped_unknown_isin"],
        result["rows_skipped_unknown_code"], len(result["errors"]),
    )
    return result


__all__ = [
    "backfill_bse",
    "backfill_bse_range",
    "backfill_legacy_range",
    "fetch_legacy_zip",
    "legacy_zip_url",
    "parse_bhavcopy_frame",
    "parse_legacy_frame",
]
