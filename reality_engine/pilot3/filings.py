"""T-223 (R-014): per-store filing register -> table ``filing`` and view ``filing_coverage``.

A store can tell "the company never filed it" from "we did not fetch it" from "we hold only a cover letter with
a link" only when every exchange filing is listed beside the store's held documents:

* **Sources (read-only)**:
  * BSE ``bse_announcements.db`` table ``ann``, queried bounded by ``SCRIP_CD = company.bse_code`` via
    :func:`reality_engine.db.readonly.connect_ro`.
  * NSE JSONL listings under ``D:/RealityEngine/raw/nse_announcements/<run folder>/<SYMBOL>.jsonl``
    (``tg_queue_2026-11-16``, ``run_2026-10-28``, ``pilot_2026-10-28``, ``transcript_gap_2026-10-28``),
    deduplicated by ``seq_id``.
  * Held documents in the store's ``doc`` and ``doc_page`` tables.
* **Hint, never type**: ``kind_hint`` (``results``, ``annual_report``, ``transcript``, ``deck``,
  ``call_recording``, ``call_intimation``, ``rating``, ``order_win``, ``shareholding``, ``other``) is inferred
  from exchange labels only and is never written into ``doc.doc_type``; a document's type stays our own
  page-based ``doc.doc_type``.
* **Matching**: attachment file name (BSE ``ATTACHMENTNAME`` or basename of NSE ``attchmntFile``) equal to
  basename of ``doc.source_key``, else whitespace-normalised ``doc.title`` equal to the headline prefix and
  ``doc.known_at`` within 1 day of ``filed_at`` (paired 1-to-1 per exchange by smallest time gap).
* **Window & exchange twins**:
  * Filings before ``WINDOW_START`` (``2024-04-01``) that are not held get ``status='out_of_window'`` (held ones
    stay ``held`` / ``link_only``).
  * An in-window ``not_fetched`` filing whose OTHER exchange has a held/link-only filing within 1 day is marked
    ``status='held_twin'`` with ``twin_filing_id`` when attachment sizes agree within 2% (BSE ``Fld_Attachsize``
    vs NSE ``file_size``/``raw.attFileSize``); if either size is missing, it requires the same ``kind_hint`` and
    exactly one held candidate on that day.
* **Statuses**: ``held``, ``link_only`` (matched held doc has ``<= 3`` pages, mentions
  call/transcript/presentation/recording, and carries a URL via :func:`linked_transcripts.stub_urls` /
  :func:`linked_transcripts.urls_from_text`), ``held_twin``, ``not_fetched``, ``no_attachment``, or
  ``out_of_window``.

CLI: ``python -m reality_engine.pilot3.filings --out <store.db> [--symbols SYM1,SYM2]``
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

from reality_engine.db.readonly import connect_ro
from reality_engine.pilot3 import data_root, linked_transcripts, schema

DEFAULT_NSE_ROOT = Path(r"D:\RealityEngine\raw\nse_announcements")
NSE_FOLDERS = ("tg_queue_2026-11-16", "run_2026-10-28", "pilot_2026-10-28", "transcript_gap_2026-10-28")
WINDOW_START = "2024-04-01"
HEADLINE_MAX = 400
LINK_MAX_PAGES = 3
MATCH_WINDOW_SECONDS = 86400
TWIN_SIZE_TOLERANCE = 0.02

_SIZE_RE = re.compile(r"^([\d,]+(?:\.\d+)?)\s*(b|bytes?|kb|kib|mb|mib|gb|gib)?$", re.I)
_SIZE_MULTS = {
    "": 1.0, "b": 1.0, "byte": 1.0, "bytes": 1.0,
    "kb": 1024.0, "kib": 1024.0,
    "mb": 1024.0 ** 2, "mib": 1024.0 ** 2,
    "gb": 1024.0 ** 3, "gib": 1024.0 ** 3,
}

_LINK_KEYWORD = re.compile(r"(?<![a-z])(?:concall|call|transcript|presentation|recording)s?(?![a-z])", re.I)
_RECORDING_RE = re.compile(
    r"(?:audio|video|earnings\s+call|conference\s+call|investor\s+call)\s+recording"
    r"|link\s+of\s+recording|recording\s+of\s+(?:the\s+)?(?:earnings|conference|investor)\s+call",
    re.I,
)
_TRANSCRIPT_RE = re.compile(
    r"\bearnings\s+call\s+transcript\b|\bconcall\s+transcript\b"
    r"|\btranscript\s+of\s+(?:the\s+)?(?:earnings|conference|investor|analyst)\b"
    r"|about\s+transcript\b",
    re.I,
)
_DECK_RE = re.compile(
    r"\b(?:investor|earnings|corporate|financial)\s+presentation\b|\binvestor\s+deck\b",
    re.I,
)
_CALL_INTIMATION_RE = re.compile(
    r"\b(?:conference\s+call|earnings\s+call|investor\s+call|analyst\s*/?\s*investor\s+meet|schedule\s+of\s+meet)\b",
    re.I,
)
_ANNUAL_REPORT_RE = re.compile(r"\bannual\s+report\b", re.I)
_NOT_ANNUAL_REPORT_RE = re.compile(r"\b(?:annual\s+secretarial|scrutinizer)\b", re.I)
_RESULTS_RE = re.compile(r"\bfinancial\s+results?\b|\bintegrated\s+fil+ing\s*[\(\-]?\s*financial", re.I)
_NOT_RESULTS_RE = re.compile(r"\b(?:board\s+meeting\s+intimation|clarification|trading\s+window)\b", re.I)


@dataclass(frozen=True)
class _Filing:
    exchange: str
    filing_id: str
    symbol: str
    isin: str | None
    filed_at: str | None
    exchange_category: str | None
    exchange_subcategory: str | None
    headline: str
    attachment: str | None
    size_bytes: float | None
    size_label: str | None
    kind_hint: str


@dataclass(frozen=True)
class _Doc:
    doc_key: str
    doc_type: str
    title_norm: str
    known_at: str | None
    pages: int
    source_key: str | None
    source_basename: str


def _norm(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _basename(path_or_url: object) -> str:
    text = str(path_or_url or "").strip()
    if not text:
        return ""
    clean = text.split("?", 1)[0].split("#", 1)[0].replace("\\", "/")
    return os.path.basename(clean).lower()


def _parse_size_bytes(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if value > 0 else None
    text = str(value).strip()
    if not text or text in ("-", "None", "null", "NA", "N/A"):
        return None
    match = _SIZE_RE.match(text)
    if not match:
        return None
    num = float(match.group(1).replace(",", ""))
    mult = _SIZE_MULTS.get((match.group(2) or "").lower())
    if mult is None or num <= 0:
        return None
    return num * mult


def _iso_dt(value: object) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    if re.match(r"^\d{4}-\d{2}-\d{2}", text):
        return text
    for fmt in ("%d-%b-%Y %H:%M:%S", "%d-%b-%Y", "%d/%m/%Y %H:%M:%S", "%d/%m/%Y"):
        try:
            dt = datetime.strptime(text, fmt)
            return dt.strftime("%Y-%m-%dT%H:%M:%S") if "%H" in fmt else dt.strftime("%Y-%m-%d")
        except ValueError:
            continue
    return text


def _parse_dt(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    iso = _iso_dt(text) or text
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(iso[:26], fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(iso[:19])
    except ValueError:
        return None


def _in_window(filed_at: str | None) -> bool:
    day = (filed_at or "")[:10]
    return not (len(day) == 10 and day < WINDOW_START)


def classify_kind_hint(
    category: str | None,
    subcategory: str | None,
    headline: str | None,
    extra: str | None = None,
) -> str:
    """Classify ``kind_hint`` strictly from exchange labels (never used as ``doc.doc_type``)."""
    cat = (category or "").strip().lower()
    sub = (subcategory or "").strip().lower()
    text = f"{sub} {headline or ''} {extra or ''}".strip()

    if "audio recording" in sub or "video recording" in sub or _RECORDING_RE.search(text):
        return "call_recording"
    if "presentation" in sub and "transcript" not in cat and not _TRANSCRIPT_RE.search(text):
        return "deck"
    if "transcript" in sub or cat == "transcript" or _TRANSCRIPT_RE.search(text):
        return "transcript"
    if _DECK_RE.search(text):
        return "deck"
    if "analyst / investor meet" in sub or "investor meet" in sub or cat == "meet":
        return "call_intimation"
    if "annual report" in sub or (_ANNUAL_REPORT_RE.search(text) and not _NOT_ANNUAL_REPORT_RE.search(text)):
        return "annual_report"
    if (
        cat == "result"
        or sub in ("financial results", "integrated filing (financial)", "financial result updates",
                   "integrated filing- financial", "integrated filing-financial", "publish audited results")
        or ("integrated filing" in cat and "financial" in sub)
        or (sub == "outcome of board meeting" and "financial result" in text.lower())
        or (_RESULTS_RE.search(extra or headline or "") and not _NOT_RESULTS_RE.search(text))
    ):
        return "results"
    if "credit rating" in sub or "credit rating" in (extra or "").lower():
        return "rating"
    if "award of order" in sub or "receipt of order" in sub or "bagging/receiving of orders" in sub or "awarding of order" in sub:
        return "order_win"
    if sub == "shareholding" or ("shareholding" in sub and "shareholders meeting" not in sub):
        return "shareholding"
    if _CALL_INTIMATION_RE.search(text) and not _NOT_RESULTS_RE.search(text):
        return "call_intimation"
    return "other"


def _pick_isin(company_rows: list[tuple[str | None, str | None, str | None]], filed_at: str | None) -> str | None:
    day = (filed_at or "")[:10]
    real = [r for r in company_rows if r[0] and not str(r[0]).startswith("INE_AUTO")]
    pool = real or company_rows
    if day:
        for isin, start, end in pool:
            if isin and start and end and str(start)[:10] <= day <= str(end)[:10]:
                return isin
    for isin, _start, _end in pool:
        if isin:
            return isin
    return None


def _load_bse_filings(
    bse_db: Path,
    targets: dict[str, dict],
) -> dict[str, list[_Filing]]:
    """Load BSE ``ann`` rows for target symbols using a bounded ``SCRIP_CD IN (...)`` query."""
    out: dict[str, list[_Filing]] = {sym: [] for sym in targets}
    if not bse_db.is_file():
        return out
    code_to_syms: dict[str, list[str]] = {}
    params: list[object] = []
    for sym, info in targets.items():
        code = str(info["bse_code"] or "").strip()
        if not code:
            continue
        code_to_syms.setdefault(code, []).append(sym)
        params.append(code)
        if code.isdigit():
            params.append(int(code))
    if not params:
        return out
    params = list(dict.fromkeys(params))
    marks = ",".join("?" * len(params))
    con = connect_ro(bse_db, timeout_s=60)
    try:
        cols = {row[1] for row in con.execute("PRAGMA table_info(ann)")}
        size_col = "Fld_Attachsize" if "Fld_Attachsize" in cols else "NULL AS Fld_Attachsize"
        sql = (
            "SELECT NEWSID, SCRIP_CD, ATTACHMENTNAME, NEWSSUB, HEADLINE, CATEGORYNAME, SUBCATNAME, "
            f"NEWS_DT, DissemDT, {size_col} FROM ann WHERE SCRIP_CD IN ({marks})"
        )
        rows = con.execute(sql, params).fetchall()
    finally:
        con.close()

    for newsid, scrip_cd, att, newssub, headline, cat, subcat, news_dt, dissem_dt, attach_size in rows:
        code = str(scrip_cd or "").strip()
        syms = code_to_syms.get(code, [])
        if not syms:
            continue
        filed_at = _iso_dt(dissem_dt or news_dt)
        hl_text = _norm(headline) or _norm(newssub)
        cat_clean = _norm(cat) or None
        sub_clean = _norm(subcat) or None
        att_clean = str(att or "").strip() or None
        size_bytes = _parse_size_bytes(attach_size)
        size_label = f"{int(size_bytes)} B" if size_bytes is not None else None
        hint = classify_kind_hint(cat_clean, sub_clean, hl_text, _norm(newssub))
        for sym in syms:
            out[sym].append(_Filing(
                exchange="BSE",
                filing_id=str(newsid),
                symbol=sym,
                isin=_pick_isin(targets[sym]["isins"], filed_at),
                filed_at=filed_at,
                exchange_category=cat_clean,
                exchange_subcategory=sub_clean,
                headline=hl_text[:HEADLINE_MAX],
                attachment=att_clean,
                size_bytes=size_bytes,
                size_label=size_label,
                kind_hint=hint,
            ))
    return out


def _load_nse_filings(nse_root: Path, targets: dict[str, dict]) -> dict[str, list[_Filing]]:
    """Load NSE JSONL filings across ``NSE_FOLDERS``, deduplicated by ``seq_id``."""
    out: dict[str, list[_Filing]] = {sym: [] for sym in targets}
    if not nse_root.is_dir():
        return out
    for sym, info in targets.items():
        seen_seq: set[str] = set()
        for folder in NSE_FOLDERS:
            path = nse_root / folder / f"{sym}.jsonl"
            if not path.is_file():
                continue
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                if not line.strip():
                    continue
                try:
                    obj = json.loads(line)
                except ValueError:
                    continue
                raw = obj.get("raw") or {}
                seq = str(obj.get("seq_id") or raw.get("seq_id") or "").strip()
                if seq and seq in seen_seq:
                    continue
                if seq:
                    seen_seq.add(seq)
                filed_at = _iso_dt(obj.get("known_at") or raw.get("exchdisstime") or raw.get("an_dt"))
                desc = _norm(obj.get("desc") or obj.get("subject"))
                txt = _norm(raw.get("attchmntText"))
                if desc and txt and txt.lower() != desc.lower():
                    headline = f"{desc} — {txt}"
                else:
                    headline = desc or txt
                att = str(raw.get("attchmntFile") or obj.get("attachment_url") or "").strip() or None
                raw_size = obj.get("file_size") or raw.get("attFileSize")
                size_bytes = _parse_size_bytes(raw_size)
                size_label = str(raw_size).strip() if size_bytes is not None else None
                cat = _norm(obj.get("kind") or obj.get("subject")) or None
                sub = desc or _norm(obj.get("subject")) or None
                isin = str(obj.get("isin") or raw.get("sm_isin") or "").strip() or _pick_isin(info["isins"], filed_at)
                fid = seq or f"{filed_at or ''}:{_basename(att)}"
                hint = classify_kind_hint(cat, sub, headline, txt)
                out[sym].append(_Filing(
                    exchange="NSE",
                    filing_id=fid,
                    symbol=sym,
                    isin=isin,
                    filed_at=filed_at,
                    exchange_category=cat,
                    exchange_subcategory=sub,
                    headline=headline[:HEADLINE_MAX],
                    attachment=att,
                    size_bytes=size_bytes,
                    size_label=size_label,
                    kind_hint=hint,
                ))
    return out


def _is_linked_doc(doc: _Doc, sym: str = "") -> bool:
    sk = (doc.source_key or "").replace("\\", "/").lower()
    seg = f"linked_docs/{sym.lower()}/" if sym else "linked_docs/"
    return f"/{seg}" in sk or sk.startswith(seg)


def _match_filings_to_docs(filings: list[_Filing], docs: list[_Doc]) -> dict[int, int]:
    """Return ``{filing_idx: doc_idx}`` for filings that carry an attachment and match a held doc."""
    by_basename: dict[str, int] = {}
    for d_idx, doc in enumerate(docs):
        if doc.source_basename and doc.source_basename not in by_basename:
            by_basename[doc.source_basename] = d_idx

    matched: dict[int, int] = {}
    used_per_exchange: set[tuple[str, int]] = set()

    # Pass 0 (Fix A): NSE all-digit seq_id -> nse_{filing_id}.pdf (1-to-1 per exchange)
    for f_idx, f in enumerate(filings):
        if f.exchange != "NSE" or not (f.filing_id.isascii() and f.filing_id.isdigit()):
            continue
        d_idx = by_basename.get(f"nse_{f.filing_id}.pdf")
        if d_idx is not None and (f.exchange, d_idx) not in used_per_exchange:
            matched[f_idx] = d_idx
            used_per_exchange.add((f.exchange, d_idx))

    # Pass 1: exact attachment file name == basename of doc.source_key
    for f_idx, f in enumerate(filings):
        if f_idx in matched or not f.attachment:
            continue
        bn = _basename(f.attachment)
        if bn and bn in by_basename:
            d_idx = by_basename[bn]
            if (f.exchange, d_idx) not in used_per_exchange:
                matched[f_idx] = d_idx
                used_per_exchange.add((f.exchange, d_idx))

    # Pass 2: doc.title equal to headline prefix AND doc.known_at within 1 day of filed_at (1-to-1 per exchange)
    doc_dts = [_parse_dt(d.known_at) for d in docs]
    candidates: list[tuple[float, int, int]] = []
    for f_idx, f in enumerate(filings):
        if f_idx in matched or not f.attachment or not f.headline:
            continue
        f_dt = _parse_dt(f.filed_at)
        if f_dt is None:
            continue
        hl_norm = _norm(f.headline)
        for d_idx, doc in enumerate(docs):
            if (f.exchange, d_idx) in used_per_exchange or not doc.title_norm or _is_linked_doc(doc):
                continue
            d_dt = doc_dts[d_idx]
            if d_dt is None:
                continue
            gap = abs((d_dt - f_dt).total_seconds())
            if gap <= MATCH_WINDOW_SECONDS and hl_norm.startswith(doc.title_norm):
                candidates.append((gap, f_idx, d_idx))

    candidates.sort(key=lambda item: (item[0], item[1], item[2]))
    for _gap, f_idx, d_idx in candidates:
        f = filings[f_idx]
        if f_idx in matched or (f.exchange, d_idx) in used_per_exchange:
            continue
        matched[f_idx] = d_idx
        used_per_exchange.add((f.exchange, d_idx))
    return matched


def _doc_links(conn: sqlite3.Connection, doc: _Doc) -> list[str]:
    """Return URLs for a held doc of ``<= 3`` pages mentioning call/transcript/presentation/recording."""
    if doc.pages is None or doc.pages > LINK_MAX_PAGES:
        return []
    texts = [row[0] or "" for row in conn.execute("SELECT text FROM doc_page WHERE doc_key=? ORDER BY page", (doc.doc_key,))]
    joined = "\n".join(texts)
    if not _LINK_KEYWORD.search(joined):
        return []
    # Reuse linked_transcripts helpers: stub_urls (PDF annotations + .pdf text URLs) and urls_from_text (all URLs).
    urls = [*linked_transcripts.stub_urls(conn, doc.doc_key, doc.source_key), *linked_transcripts.urls_from_text(joined)]
    return list(dict.fromkeys(urls))


def _find_twin(
    f: _Filing,
    f_dt: datetime | None,
    held_other: list[tuple[_Filing, datetime | None]],
) -> _Filing | None:
    """Match an in-window ``not_fetched`` filing to a held twin on the OTHER exchange.

    Within 1 day, attachment sizes within 2% match unconditionally; if either size is missing, require the same
    ``kind_hint`` AND exactly one held candidate on that day.  Never pairs two filings of the same exchange.
    """
    if f_dt is None or not held_other:
        return None
    if f.size_bytes is not None:
        size_hits: list[tuple[float, float, _Filing]] = []
        for cand, c_dt in held_other:
            if cand.exchange == f.exchange or c_dt is None or cand.size_bytes is None:
                continue
            gap = abs((c_dt - f_dt).total_seconds())
            if gap > MATCH_WINDOW_SECONDS:
                continue
            rel = abs(f.size_bytes - cand.size_bytes) / max(f.size_bytes, cand.size_bytes)
            if rel <= TWIN_SIZE_TOLERANCE:
                size_hits.append((rel, gap, cand))
        if size_hits:
            size_hits.sort(key=lambda item: (item[0], item[1], item[2].filing_id))
            return size_hits[0][2]

    f_day = (f.filed_at or "")[:10]
    if len(f_day) != 10:
        return None
    same_day = [
        cand for cand, _c_dt in held_other
        if cand.exchange != f.exchange and (cand.filed_at or "")[:10] == f_day and cand.kind_hint == f.kind_hint
    ]
    if len(same_day) == 1 and (f.size_bytes is None or same_day[0].size_bytes is None):
        return same_day[0]
    return None


def _process_symbol(
    conn: sqlite3.Connection,
    sym: str,
    filings: list[_Filing],
    docs: list[_Doc],
) -> dict:
    matches = _match_filings_to_docs(filings, docs)
    matched_doc_indices = set(matches.values())
    linked_docs = [doc for doc in docs if _is_linked_doc(doc, sym)]
    link_cache: dict[str, list[str]] = {}
    filing_dts = [_parse_dt(f.filed_at) for f in filings]

    # First pass: direct held / link_only vs no_attachment / not_fetched / out_of_window
    prelim: list[tuple[str, str | None, str | None, int | None, str | None]] = []
    held_by_exchange: dict[str, list[tuple[_Filing, datetime | None]]] = {"BSE": [], "NSE": []}
    for f_idx, f in enumerate(filings):
        d_idx = matches.get(f_idx)
        if d_idx is not None:
            doc = docs[d_idx]
            if doc.doc_key not in link_cache:
                link_cache[doc.doc_key] = _doc_links(conn, doc)
            urls = link_cache[doc.doc_key]
            if urls:
                status, lu = "link_only", json.dumps(urls)
            else:
                status, lu = "held", None
            prelim.append((status, doc.doc_key, doc.doc_type, doc.pages, lu))
            held_by_exchange.setdefault(f.exchange, []).append((f, filing_dts[f_idx]))
        elif not _in_window(f.filed_at):
            prelim.append(("out_of_window", None, None, None, None))
        elif not f.attachment:
            prelim.append(("no_attachment", None, None, None, None))
        else:
            prelim.append(("not_fetched", None, None, None, None))

    rows: list[tuple] = []
    by_exchange: Counter[str] = Counter()
    by_status: Counter[str] = Counter()
    hint_x_status: dict[str, Counter[str]] = {}
    link_only_rows: list[dict] = []
    twin_pairs: list[dict] = []

    for f_idx, f in enumerate(filings):
        status, held_doc_key, held_doc_type, held_pages, link_urls_json = prelim[f_idx]
        twin_filing_id: str | None = None
        resolved_doc_key: str | None = None
        prefix = f"{f.exchange.lower()}_{f.filing_id.lower()}_"
        resolved_doc = next((d for d in linked_docs if d.source_basename.startswith(prefix)), None)
        if status in ("link_only", "not_fetched") and resolved_doc is not None:
            status = "link_held"
            resolved_doc_key = resolved_doc.doc_key
        elif status == "not_fetched":
            other_ex = "NSE" if f.exchange == "BSE" else "BSE"
            twin = _find_twin(f, filing_dts[f_idx], held_by_exchange.get(other_ex, []))
            if twin is not None:
                status = "held_twin"
                twin_filing_id = twin.filing_id
                twin_pairs.append({
                    "exchange": f.exchange,
                    "filing_id": f.filing_id,
                    "twin_exchange": twin.exchange,
                    "twin_filing_id": twin.filing_id,
                    "filed_at": f.filed_at,
                    "kind_hint": f.kind_hint,
                    "headline": f.headline[:100],
                    "size": f.size_label,
                    "twin_headline": twin.headline[:100],
                    "twin_size": twin.size_label,
                })
        elif status == "link_only":
            urls = json.loads(link_urls_json or "[]")
            link_only_rows.append({
                "exchange": f.exchange,
                "filing_id": f.filing_id,
                "filed_at": f.filed_at,
                "headline": f.headline[:80],
                "first_url": urls[0] if urls else "",
                "kind_hint": f.kind_hint,
                "held_doc_type": held_doc_type,
                "held_doc_key": held_doc_key,
            })

        by_exchange[f.exchange] += 1
        by_status[status] += 1
        hint_x_status.setdefault(f.kind_hint, Counter())[status] += 1
        rows.append((
            f.exchange, f.filing_id, f.symbol, f.isin, f.filed_at, f.exchange_category,
            f.exchange_subcategory, f.headline, f.attachment, f.kind_hint,
            held_doc_key, held_doc_type, held_pages, link_urls_json, twin_filing_id,
            resolved_doc_key, status,
        ))

    conn.execute("DELETE FROM filing WHERE symbol=?", (sym,))
    if rows:
        conn.executemany(
            "INSERT INTO filing (exchange, filing_id, symbol, isin, filed_at, exchange_category, "
            "exchange_subcategory, headline, attachment, kind_hint, held_doc_key, held_doc_type, "
            "held_pages, link_urls, twin_filing_id, resolved_doc_key, status) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            rows,
        )

    unmatched_docs = [docs[i] for i in range(len(docs)) if i not in matched_doc_indices]
    res_ar_docs = [d for d in docs if d.doc_type in ("results", "annual_report")]
    res_ar_unmatched = [d for d in unmatched_docs if d.doc_type in ("results", "annual_report")]

    return {
        "filings": len(rows),
        "by_exchange": dict(sorted(by_exchange.items())),
        "by_status": dict(sorted(by_status.items())),
        "kind_hint_x_status": {k: dict(sorted(v.items())) for k, v in sorted(hint_x_status.items())},
        "held_docs_total": len(docs),
        "held_docs_unmatched": len(unmatched_docs),
        "held_results_ar_total": len(res_ar_docs),
        "held_results_ar_unmatched": len(res_ar_unmatched),
        "twin_pairs_count": len(twin_pairs),
        "twin_pairs": twin_pairs,
        "link_only_rows": link_only_rows,
    }


def run(
    store_db: str | Path | sqlite3.Connection,
    symbols: Iterable[str] | None = None,
    *,
    bse_db: str | Path | None = None,
    nse_root: str | Path | None = None,
) -> dict:
    """Populate the ``filing`` table and ``filing_coverage`` view for ``symbols`` (or all companies in the store)."""
    own = not isinstance(store_db, sqlite3.Connection)
    conn = sqlite3.connect(store_db, timeout=60) if own else store_db
    try:
        schema.ensure(conn, ("filing",))
        schema.ensure_columns(
            conn,
            "filing",
            (
                "ALTER TABLE filing ADD COLUMN twin_filing_id TEXT",
                "ALTER TABLE filing ADD COLUMN resolved_doc_key TEXT",
            ),
        )
        schema.ensure_views(conn)
        wanted = {s.strip().upper() for s in symbols if s and s.strip()} if symbols is not None else None
        targets: dict[str, dict] = {}
        for sym, isin, isin_from, isin_to, bse_code in conn.execute(
            "SELECT symbol, isin, isin_from, isin_to, bse_code FROM company ORDER BY symbol"
        ):
            sym_u = str(sym or "").strip().upper()
            if not sym_u or (wanted is not None and sym_u not in wanted):
                continue
            entry = targets.setdefault(sym_u, {"bse_code": bse_code, "isins": []})
            if bse_code and not entry["bse_code"]:
                entry["bse_code"] = bse_code
            entry["isins"].append((isin, isin_from, isin_to))

        bse_path = Path(bse_db) if bse_db is not None else data_root() / "bse_announcements.db"
        nse_dir = Path(nse_root) if nse_root is not None else DEFAULT_NSE_ROOT
        bse_filings = _load_bse_filings(bse_path, targets)
        nse_filings = _load_nse_filings(nse_dir, targets)

        docs_by_sym: dict[str, list[_Doc]] = {sym: [] for sym in targets}
        for dk, sym, dt, title, fd, ka, pages, sk in conn.execute(
            "SELECT doc_key, symbol, doc_type, title, filing_date, known_at, pages, source_key FROM doc ORDER BY doc_key"
        ):
            sym_u = str(sym or "").strip().upper()
            if sym_u not in docs_by_sym:
                continue
            docs_by_sym[sym_u].append(_Doc(
                doc_key=str(dk),
                doc_type=str(dt or ""),
                title_norm=_norm(title),
                known_at=ka or fd,
                pages=int(pages) if pages is not None else 0,
                source_key=sk,
                source_basename=_basename(sk),
            ))

        summary: dict[str, dict] = {}
        for sym in sorted(targets):
            combined = [*bse_filings.get(sym, ()), *nse_filings.get(sym, ())]
            summary[sym] = _process_symbol(conn, sym, combined, docs_by_sym.get(sym, []))
        conn.commit()
        return summary
    finally:
        if own:
            conn.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    grp = ap.add_mutually_exclusive_group(required=True)
    grp.add_argument("--out", help="pilot3 SQLite store path")
    grp.add_argument("--store", help="alias for --out")
    ap.add_argument("--symbols", default=None, help="comma-separated symbols (default: all in company)")
    ap.add_argument("--bse-db", default=None, help="optional path to bse_announcements.db")
    ap.add_argument("--nse-root", default=None, help="optional path to nse_announcements root")
    args = ap.parse_args(argv)
    db = args.out or args.store
    syms = [s.strip() for s in args.symbols.split(",") if s.strip()] if args.symbols else None
    result = run(db, syms, bse_db=args.bse_db, nse_root=args.nse_root)
    print(json.dumps(result, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
