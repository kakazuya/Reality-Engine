"""EVIDENCE: passages from the company's own documents, PIT-filtered in SQL.

Delegates to the ``reality-data`` document tools for a named page (``doc_page``),
and to the ``chunks_v3`` pilot store when it covers the ISIN.  Where it does not,
the fallback is the ``intelligence_fts`` index with the owner filter pushed into
the FTS5 match (``isin:INE...``), a PIT date bound and a LIMIT -- never a LIKE
scan over ``document_chunks`` and never the 5-store ``doc_find`` walk, which cost
2-6 s per miss.  ``doc_find`` remains the tool surface for callers outside the
query layer.

Coverage rule: chunks_v3 is authoritative for an ISIN it holds (a miss there is
a no_doc, not a reason to slow-fall-back); elsewhere the bounded FTS path is.
"""
from __future__ import annotations

import re
from datetime import date as _date
from datetime import timedelta
from typing import Any

from .. import rerank
from ..router import LIST_ASK
from . import envelope
from .facts import DOC_WINDOW_DAYS, TEXT_TERMS, asked_words, named_of

CHECKED = ["equity_intelligence.document_chunks", "ar_facts.ar_facts",
           "deck_figures.deck_sources", "bse_announcements.ann",
           "equity_intelligence.corporate_documents"]
CHECKED_FTS = ["equity_intelligence.intelligence_fts", "equity_intelligence.document_chunks"]
CHECKED_V3 = ["chunks_v3.chunk + chunk_fts", "chunks_v3.chunk_tag", "chunks_v3.doc"]

_STOP = {
    "the", "and", "for", "was", "were", "are", "what", "which", "how", "why", "who",
    "did", "does", "from", "that", "this", "with", "has", "have", "had", "its", "their",
    "company", "quarter", "year", "said", "say", "tell",
}
_FTS_WORD = re.compile(r"[A-Za-z][A-Za-z0-9]{2,}")
_PAGE_RE = re.compile(r"page\s*(\d{1,4})\s*(?:of|/)\s*(\d{1,4})", re.IGNORECASE)
_META_RE = re.compile(r"^\[Metadata:[^\]]*\]\s*")
_DOC_TYPE_RE = re.compile(r"Doc:\s*([A-Z_]+)")
_CHUNK_TYPE = {
    "CONCALL_TRANSCRIPT": "transcript",
    "INVESTOR_PRESENTATION": "deck",
    "ANNUAL_REPORT": "ar",
    "ANNOUNCEMENT": "announcement",
    "OTHER_FILING": "announcement",
    "PRESS_RELEASE": "announcement",
}
_SOURCE_TYPES = {
    "transcript": ("CONCALL_TRANSCRIPT",),
    "ar": ("ANNUAL_REPORT",),
    "deck": ("INVESTOR_PRESENTATION",),
    "announcement": ("ANNOUNCEMENT", "OTHER_FILING", "PRESS_RELEASE"),
}

#: Narrative concepts: the words the passage itself must carry, and the document
#: types the bank's ask expects that concept in (acquisitions -> announcements/AR,
#: facilities -> AR/deck, auditor -> AR/announcements).  A passage that does not
#: name the concept is not evidence for that ask, however many title words it shares.
NARRATIVE: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "acquisition": (("acquisition", "acquire", "acquired", "acquiring", "stake sale",
                     "stake purchase", "demerger", "amalgamation", "scheme of arrangement",
                     "takeover"),
                    ("announcement", "ar", "results_notes")),
    "products": (("product", "products", "offering", "offerings", "portfolio of"),
                 ("ar", "deck", "concall")),
    "facilities": (("facilit", "plant", "plant", "factory", "factories",
                    "manufacturing unit", "manufacturing units"),
                   ("ar", "deck")),
    "audit": (("auditor", "auditors", "audit", "qualified opinion", "unmodified opinion",
               "opinion"),
              ("ar", "announcement", "results_notes")),
    "listing": (("listing", "listed", "initial public offer", "ipo", "prospectus",
                 "grey market"),
                ("announcement", "deck", "concall")),
    "lag": (("lag", "lagged", "pass-through", "passthrough", "quarters", "months"),
            ()),
}


def _narratives_of(question: str) -> list[tuple[str, tuple[str, ...], tuple[str, ...]]]:
    """Every narrative concept the ask names (a two-part ask needs both)."""
    from ..gate import asked_concepts
    out = []
    for concept in asked_concepts(question or ""):
        spec = NARRATIVE.get(concept)
        if spec:
            out.append((concept, spec[0], spec[1]))
    return out[:2]


def _narrative_of(question: str) -> tuple[str, tuple[str, ...], tuple[str, ...]] | None:
    """The narrative concept the ask names (most specific first), if held."""
    found = _narratives_of(question)
    return found[0] if found else None


def _narrative_hits(text: str, narratives: list[tuple[str, tuple[str, ...],
                                                      tuple[str, ...]]]) -> int:
    """Concept hits across the asked narrative concepts (each term counts once)."""
    low = str(text or "").lower()
    hits = 0
    for _, terms, _ in narratives:
        hits += sum(1 for term in terms if term in low)
    return hits


def _narrative_types(narratives: list[tuple[str, tuple[str, ...],
                                            tuple[str, ...]]]) -> tuple[str, ...]:
    types: list[str] = []
    for _, _, doc_types in narratives:
        types += [doc_type for doc_type in doc_types if doc_type not in types]
    return tuple(types)


def _concept_hits(text: str, concept_terms: tuple[str, ...]) -> int:
    low = str(text or "").lower()
    return sum(1 for term in concept_terms if term in low)


def _prefer_doc_type(passages: list[dict[str, Any]],
                     doc_types: tuple[str, ...]) -> list[dict[str, Any]]:
    """Keep the passages filed in a type the concept lives in, when any is."""
    if not doc_types:
        return passages
    preferred = [p for p in passages if str(p.get("doc_type") or "") in doc_types]
    return preferred or passages


def _fts_query(terms: list[str]) -> str:
    """OR of quoted content words, with a de-pluralised form of each."""
    words: list[str] = []
    for term in terms:
        for word in _FTS_WORD.findall(str(term).lower()):
            if word in _STOP:
                continue
            words.append(word)
            if len(word) > 4 and word.endswith("s"):
                words.append(word[:-1])
    unique = list(dict.fromkeys(words))
    # Longest words first: they are the selective postings, and the OR union is
    # what a cold FTS read pays for.  When two or more words are >= 5 letters,
    # the short generic ones ("coal", "said") are dropped from the retrieval
    # query only -- the relevance filter below still scores every asked word.
    unique.sort(key=lambda word: (-len(word), word))
    selective = [word for word in unique if len(word) >= 5]
    chosen = selective if len(selective) >= 2 else unique
    return " OR ".join(f'"{word}"' for word in chosen[:8])


def _column_filter(field: str, value: Any) -> str:
    """A safe FTS5 column filter (``isin:INE...``) from an identity value."""
    if not value:
        return ""
    words = re.findall(r"[A-Za-z0-9]+", str(value))
    return f'{field}:"{" ".join(words)}"' if words else ""


def _snippet(text: Any, terms: list[str], width: int = 420) -> str:
    body = _META_RE.sub("", str(text or "")).strip()
    low = body.lower()
    hits = [low.find(str(t).lower()) for t in terms]
    hits = [h for h in hits if h >= 0]
    if not hits:
        return body[:width].strip()
    start = max(0, min(hits) - width // 4)
    return body[start:start + width].strip()


def _kind(row: dict[str, Any]) -> str | None:
    kind = _CHUNK_TYPE.get(str(row.get("source_type") or "").upper())
    if kind:
        return kind
    match = _DOC_TYPE_RE.search((row.get("content") or "")[:160])
    return _CHUNK_TYPE.get(match.group(1) if match else "", None)


def _doc_window(slots: dict[str, Any], as_of: str) -> tuple[str, str] | None:
    """The document-date window the gate allows for this ask (None = no bound).

    Named date / month asks judge the document's own date (±3d); a quarter or
    fiscal-year ask judges a row's own period label first and lets an unlabelled
    document through only when it was filed in the period's filing window.
    """
    basis = str(slots.get("period_basis") or "")
    low, high = str(slots.get("date_from") or "")[:10], str(slots.get("date_to") or "")[:10]
    if not low or not high:
        return None
    if basis in ("named date", "named dates", "month", "month span"):
        lo, hi = _shift(low, -DOC_WINDOW_DAYS), _shift(high, DOC_WINDOW_DAYS)
    elif basis in ("quarter end", "fiscal year end"):
        lo, hi = low, _shift(high, 300 if basis == "fiscal year end" else 180)
    elif basis in ("quarter span", "fiscal year span", "since"):
        lo, hi = low, high
    else:
        return None
    return lo, min(hi, str(as_of)[:10])


def _shift(day: str, days: int) -> str:
    return (_date.fromisoformat(day[:10]) + timedelta(days=days)).isoformat()


def _label_terms(want: str | None) -> list[str]:
    """LIKE terms matching the asked fiscal label in either spelling the stores use."""
    if not want:
        return []
    match = re.match(r"^Q([1-4])FY(\d{2})$", want)
    if match:
        year = 2000 + int(match.group(2))
        return [f"%q{match.group(1)}%fy{match.group(2)}%", f"%q{match.group(1)}%{year}%"]
    if want.startswith("FY"):
        year = 2000 + int(want[2:])
        return [f"%fy{want[2:]}%", f"%{year}%"]
    return [f"%{want.lower()}%"]


def _period_passages(passages: list[dict[str, Any]], slots: dict[str, Any],
                     as_of: str, named: dict[str, Any] | None = None
                     ) -> list[dict[str, Any]]:
    """Keep the passages the gate's period check accepts.

    The row's own label decides first (an FY ask keeps a Q4FY26 passage, shown at
    the asked granularity); a document without a label must fall in the window.
    A *named document* ask is judged on its filing date instead: the document's
    date is the period, not the fiscal label its KPIs carry.
    """
    from ..gate import _label
    from . import label_within
    if named and named.get("date"):
        anchor = _shift(str(named["date"]), 0)
        window = (_shift(anchor, -DOC_WINDOW_DAYS),
                  min(_shift(anchor, DOC_WINDOW_DAYS), str(as_of)[:10]))
    else:
        window = _doc_window(slots, as_of)
    want = "" if named else str(slots.get("period_label") or "")
    basis = str(slots.get("period_basis") or "")
    fiscal_basis = basis in ("quarter end", "fiscal year end", "quarter span",
                             "fiscal year span")
    out: list[dict[str, Any]] = []
    for passage in passages:
        got = _label("", str(passage.get("period") or ""))[1]
        if want and got and not label_within(got, want):
            continue
        day = str(passage.get("date") or "")[:10]
        if window and not (len(day) == 10 and window[0] <= day <= window[1]):
            continue
        if named:
            passage = dict(passage, period=day or None)
        elif fiscal_basis and want and label_within(got, want) and got != want:
            passage = dict(passage, period=want)
        out.append(passage)
    return out


def _v3_covers(ctx: Any, isin: str | None, symbol: str | None) -> bool:
    """Does the chunks_v3 pilot store hold documents for this identity?"""
    store = ctx.chunks_v3()
    key = isin or symbol
    if store is None or not key:
        return False
    cache_key = ("v3_covers", store[0], key)
    cached = ctx.cache_get(cache_key)
    if cached is not None:
        return bool(cached)
    try:
        row = store[1].execute(
            "SELECT 1 FROM doc WHERE isin=? OR symbol_at_time=? LIMIT 1",
            (isin or "", symbol or "")).fetchone()
        covered = row is not None
    except Exception:  # noqa: BLE001 - a broken pilot DB degrades to the FTS path
        return False
    ctx.cache_put(cache_key, covered)
    return covered


def _chunks_v3_search(ctx: Any, slots: dict[str, Any], as_of: str,
                      doc_type: str | None, limit: int = 5) -> list[dict[str, Any]]:
    """FTS first, then filter push-down on the already-matched row set.

    The FTS match is materialised first (26 ms measured) and the filters then
    run against ``chunk``: the opposite plan (filter ``chunk`` then scan the
    virtual table per row) took ~1 s on the same 37k-chunk store.  The period is
    pushed into the same SQL: a labelled document must be labelled in the asked
    quarter/FY; an unlabelled one must be filed in the period's filing window.
    """
    store = ctx.chunks_v3()
    match = _fts_query([str(t) for t in (slots.get("terms") or [])])
    if store is None or not match:
        return []
    con = store[1]
    where = ["c.known_at <= ?"]
    params: list[Any] = [as_of]
    window = _doc_window(slots, as_of)
    want = slots.get("period_label")
    if want and str(slots.get("period_basis") or "") in (
            "quarter end", "fiscal year end", "quarter span", "fiscal year span"):
        terms = _label_terms(str(want))
        labelled = " OR ".join(
            "lower(COALESCE(c.fiscal_period,'')) LIKE ? OR "
            "lower(COALESCE(d.fiscal_period,'')) LIKE ?" for _ in terms)
        tree = []
        for term in terms:
            tree += [term, term]
        bare = "COALESCE(NULLIF(c.fiscal_period,''), d.fiscal_period, '') = ''"
        if window:
            where.append(f"(({labelled}) OR ({bare} AND c.known_at >= ? AND c.known_at <= ?))")
            params.extend(tree + [window[0], window[1]])
        else:
            where.append(f"({labelled})")
            params.extend(tree)
    elif window:
        where.append("c.known_at >= ? AND c.known_at <= ?")
        params.extend([window[0], window[1]])
    isin = slots.get("isin")
    if isin:
        where.append("c.isin = ?")
        params.append(isin)
    else:
        symbol = slots.get("symbol")
        if symbol:
            where.append("upper(COALESCE(c.symbol_at_time,'')) = upper(?)")
            params.append(str(symbol))
    if doc_type:
        where.append("c.doc_type = ?")
        params.append(doc_type)
    section = slots.get("section")
    if section:
        where.append("c.section LIKE ?")
        params.append(f"%{section}%")
    speaker = slots.get("speaker")
    if speaker:
        where.append("c.speaker LIKE ?")
        params.append(f"%{speaker}%")
    tags = slots.get("tags") or slots.get("tag")
    if isinstance(tags, str):
        tags = [tags]
    ctes = [("hits AS MATERIALIZED (SELECT rowid AS chunk_id, "
             "bm25(chunk_fts, 0.2, 1.0) AS score FROM chunk_fts "
             "WHERE chunk_fts MATCH ?)")]
    tag_sql = ""
    if tags:
        # Materialised tag set: a plain join on chunk_tag picked the wrong plan
        # and cost ~1 s; the PK range scan costs ~100 ms.
        if len(tags) == 1:
            ctes.append("tagged AS MATERIALIZED (SELECT chunk_id FROM chunk_tag WHERE tag = ?)")
        else:
            ctes.append("tagged AS MATERIALIZED (SELECT chunk_id FROM chunk_tag "
                        f"WHERE tag IN ({','.join('?' * len(tags))}) GROUP BY chunk_id "
                        "HAVING COUNT(*) = ?)")
            tags = list(tags) + [len(tags)]
        tag_sql = " JOIN tagged ON tagged.chunk_id = hits.chunk_id"
    sql = (f"WITH {', '.join(ctes)} "
           f"SELECT c.doc_id, c.doc_type, c.known_at, c.page_from, c.section, c.speaker, "
           f"c.speaker_role, c.body, c.header, c.isin, c.symbol_at_time, c.fiscal_period, "
           f"d.fiscal_period "
           f"FROM hits{tag_sql} "
           f"JOIN chunk c ON c.chunk_id = hits.chunk_id "
           f"JOIN doc d ON d.doc_id = c.doc_id "
           f"WHERE {' AND '.join(where)} ORDER BY hits.score LIMIT ?")
    args = [match] + list(tags or []) + params + [limit]
    rows = con.execute(sql, args).fetchall()
    return [{"store": "chunks_v3", "doc_id": row[0], "doc_type": row[1],
             "date": row[2], "page": row[3], "section": row[4], "speaker": row[5],
             "speaker_role": row[6], "quote": row[7] or "", "header": row[8] or "",
             "isin": row[9], "symbol": row[10], "period": row[11] or row[12]}
            for row in rows]


def _fts_passages(ctx: Any, slots: dict[str, Any], terms: list[str], as_of: str,
                  doc_type: str | None, date: str | None,
                  limit: int = 30) -> list[dict[str, Any]]:
    """Bounded fallback: FTS5 match with the owner filter inside the MATCH.

    ``intelligence_fts`` holds one row per chunk; the ``isin:``/``symbol:``
    column filter makes SQLite intersect the company's postings before any row
    is materialised (~10-120 ms measured, against 1.5-2.5 s for the LIKE walk
    over the same company's chunks).  No LIKE, no five-store document walk, one
    statement with a LIMIT.
    """
    match = _fts_query(terms)
    # Prefer the ISIN: the chunk index stores it for every row, so a BSE code or
    # an old symbol in the ask still reaches the company's documents.
    isin = slots.get("isin") or _owner_isin(ctx, slots)
    scope = _column_filter("isin", isin) or _column_filter(
        "symbol", slots.get("symbol"))
    if not match or not scope:
        return []
    sql = ("SELECT f.symbol, f.source_type, f.document_date, d.doc_id, d.chunk_index, "
           "d.published_date, d.content FROM intelligence_fts f "
           "JOIN document_chunks d ON d.chunk_id = f.chunk_id "
           "WHERE f.intelligence_fts MATCH ? AND d.published_date <= ?")
    args: list[Any] = [f"{scope} AND ({match})", as_of]
    lo = hi = None
    if date:
        try:
            anchor = _date.fromisoformat(str(date)[:10])
            span = timedelta(days=DOC_WINDOW_DAYS)
            lo, hi = (anchor - span).isoformat(), min(
                (anchor + span).isoformat(), str(as_of)[:10])
        except ValueError:
            lo = hi = None
    else:
        window = _doc_window(slots, as_of)
        if window:
            lo, hi = window
    if lo and hi:
        sql += " AND d.published_date >= ? AND d.published_date <= ?"
        args += [lo, hi]
    types = _SOURCE_TYPES.get(str(doc_type or ""))
    if types:
        sql += f" AND f.source_type IN ({','.join('?' * len(types))})"
        args += list(types)
    sql += " LIMIT ?"
    args.append(max(int(limit), 10))
    rows = ctx.rows("equity_intelligence", sql, args)
    out: list[dict[str, Any]] = []
    for row in rows:
        kind = _kind(row)
        if doc_type and kind != doc_type:
            continue
        page = _PAGE_RE.search(row.get("content") or "")
        low = str(row.get("content") or "").lower()
        out.append({
            "store": "document_chunks", "doc_type": kind,
            "date": row.get("published_date"), "doc_id": row.get("doc_id"),
            "chunk_index": row.get("chunk_index"),
            "page": int(page.group(1)) if page else None,
            "page_count": int(page.group(2)) if page else None,
            "quote": _snippet(row.get("content"), terms),
            "score": sum(1 for term in terms if str(term).lower() in low),
        })
    out.sort(key=lambda p: (-p["score"], str(p.get("date") or "")), reverse=False)
    return out


def _corpus_passages(ctx: Any, terms: list[str], as_of: str,
                     date_to: str | None, date_from: str | None = None,
                     limit: int = 30) -> list[dict[str, Any]]:
    """Bounded corpus search over ``intelligence_fts`` (no dense index, no LLM)."""
    match = _fts_query(terms)
    if not match:
        return []
    sql = ("SELECT f.symbol, f.source_type, d.doc_id, d.published_date, d.content "
           "FROM intelligence_fts f JOIN document_chunks d ON d.chunk_id = f.chunk_id "
           "WHERE f.intelligence_fts MATCH ? AND d.published_date <= ?")
    args: list[Any] = [match, as_of]
    cap = str(date_to or "")[:10]
    if cap and cap < str(as_of)[:10]:
        sql += " AND d.published_date <= ?"
        args.append(cap)
    floor = str(date_from or "")[:10]
    if floor:
        sql += " AND d.published_date >= ?"
        args.append(floor)
    sql += " LIMIT ?"
    args.append(max(int(limit), 10))
    rows = ctx.rows("equity_intelligence", sql, args)
    out = []
    for row in rows:
        text = _META_RE.sub("", str(row.get("content") or "")).strip()
        low = text.lower()
        hits = sum(1 for term in terms if str(term).lower() in low)
        if not hits:
            continue
        out.append({"store": "document_chunks", "doc_type": _kind(row),
                    "date": row.get("published_date"), "doc_id": row.get("doc_id"),
                    "page": None, "text": _snippet(text, terms, 600),
                    "score": hits})
    out.sort(key=lambda p: (-p["score"], str(p.get("date") or "")), reverse=False)
    return out


def _owner_isin(ctx: Any, slots: dict[str, Any]) -> str | None:
    """The company's ISIN for the satellite stores (the router only fills it when
    the ask names one; a symbol ask still resolves with one indexed lookup)."""
    isin = slots.get("isin")
    if isin:
        return isin
    symbol = str(slots.get("symbol") or "")
    if not symbol:
        return None
    key = ("owner_isin", symbol.upper())
    cached = ctx.cache_get(key)
    if cached is not None:
        return cached or None
    found = None
    for db, sql in (
            ("equity_intelligence",
             "SELECT isin FROM master_companies WHERE upper(nse_symbol)=? LIMIT 1"),
            ("equity_intelligence",
             "SELECT isin FROM security_master WHERE upper(nse_symbol)=? LIMIT 1")):
        try:
            row = ctx.one(db, sql, (symbol.upper(),))
        except Exception:  # noqa: BLE001 - an identity store miss is not fatal
            row = None
        if row and row.get("isin"):
            found = row["isin"]
            break
    ctx.cache_put(key, found or "")
    return found


def _store_passages(ctx: Any, slots: dict[str, Any], terms: list[str], as_of: str,
                    doc_type: str | None, date: str | None,
                    limit: int = 20) -> list[dict[str, Any]]:
    """Bounded second store for a company's deck pages and AR facts.

    The vision reader's page text (``deck_figures.outputs``) and the annual-report
    fact quotes are not part of ``document_chunks`` for every company, so a deck/AR
    ask can miss on the chunk index alone.  Both queries are index-bounded: the
    company's deck sha list (``ix_deck_sources_isin``, <= 8 decks) and the company's
    AR facts (``ar_facts_isin``); each LIKE runs over that bounded row set only.
    """
    isin = _owner_isin(ctx, slots)
    if not isin or not terms:
        return []
    tokens = [str(t).lower() for t in terms][:6]
    out: list[dict[str, Any]] = []
    lo = hi = None
    if date:
        try:
            anchor = _date.fromisoformat(str(date)[:10])
            span = timedelta(days=DOC_WINDOW_DAYS)
            lo, hi = (anchor - span).isoformat(), min(
                (anchor + span).isoformat(), str(as_of)[:10])
        except ValueError:
            lo = hi = None
    else:
        window = _doc_window(slots, as_of)
        if window:
            lo, hi = window
    if doc_type in (None, "deck"):
        try:
            decks = ctx.rows(
                "deck_figures",
                "SELECT sha256, known_at FROM deck_sources WHERE isin=? AND known_at<=? "
                + ("AND known_at >= ? AND known_at <= ? " if lo else "")
                + "ORDER BY known_at DESC LIMIT ?",
                ((isin, as_of) if not lo else (isin, as_of, lo, hi)) + (8,))
        except Exception:  # noqa: BLE001 - a broken satellite store is not fatal
            decks = []
        clauses = " OR ".join("lower(raw_output) LIKE ?" for _ in tokens)
        for deck in decks:
            if not deck.get("sha256"):
                continue
            try:
                rows = ctx.rows(
                    "deck_figures",
                    "SELECT page_no, raw_output FROM outputs WHERE sha256=? "
                    f"AND ({clauses}) ORDER BY page_no LIMIT ?", (deck["sha256"],) + tuple(
                        f"%{token}%" for token in tokens) + (60,))
            except Exception:  # noqa: BLE001
                continue
            seen: set[Any] = set()
            for row in rows:
                if row["page_no"] in seen or not row.get("raw_output"):
                    continue
                seen.add(row["page_no"])
                low = str(row["raw_output"]).lower()
                hits = sum(1 for token in tokens if token in low)
                out.append({"store": "deck_figures", "doc_type": "deck",
                            "date": deck.get("known_at"), "doc_id": deck["sha256"],
                            "page": row["page_no"], "page_count": None,
                            "quote": _snippet(row["raw_output"], tokens),
                            "score": hits})
    if doc_type in (None, "ar"):
        try:
            clauses = " OR ".join("lower(item) LIKE ? OR lower(quote) LIKE ?"
                                  for _ in tokens)
            args: list[Any] = [isin, as_of]
            for token in tokens:
                args += [f"%{token}%", f"%{token}%"]
            rows = ctx.rows(
                "ar_facts",
                "SELECT doc_id, page, filed_at, item, quote FROM ar_facts "
                f"WHERE isin=? AND filed_at<=? AND ({clauses}) "
                "ORDER BY filed_at DESC LIMIT ?", args + [40])
        except Exception:  # noqa: BLE001
            rows = []
        if lo:
            rows = [row for row in rows
                    if lo <= str(row.get("filed_at") or "")[:10] <= hi]
        for row in rows:
            text = row.get("quote") or row.get("item") or ""
            low = str(text).lower()
            out.append({"store": "ar_facts", "doc_type": "ar",
                        "date": row.get("filed_at"), "doc_id": row.get("doc_id"),
                        "page": row.get("page"), "page_count": None,
                        "quote": _snippet(text, tokens),
                        "score": sum(1 for token in tokens if token in low)})
    out.sort(key=lambda p: (-p["score"], str(p.get("date") or "")), reverse=False)
    return out[:max(int(limit), 5)]


def _missing(res: dict[str, Any]) -> str:
    for key in ("reason", "detail", "why", "message", "hint"):
        if res.get(key):
            return str(res[key])
    nearest = res.get("nearest")
    if isinstance(nearest, list) and nearest:
        first = nearest[0]
        if isinstance(first, dict):
            return (f"nearest held: {first.get('doc_type')} {first.get('date')} "
                    f"{(first.get('title') or '')[:80]}")
    return "no passage carries the ask"


def plan(slots: dict[str, Any], as_of: str, ctx: Any) -> dict[str, Any]:
    needs = slots.get("needs", {})
    if not needs.get("text") and not needs.get("page"):
        return envelope("EVIDENCE", ok=True, na=True, checked=CHECKED,
                        detail="no passage asked; EVIDENCE not applicable")
    symbol = slots.get("symbol") or slots.get("isin")
    question = str(slots.get("question") or "")
    list_ask = bool(LIST_ASK.search(question))
    if list_ask:
        symbol = None  # a proxy company's documents cannot answer a corpus list
    status = str(slots.get("status") or "")
    gate = (status.split(":", 1)[-1] if status.startswith("needs_new_table:") else None)
    if not symbol:
        terms = [t for t in (slots.get("terms") or []) if len(t) > 3]
        if terms:
            if list_ask:
                detail = ("a complete company list needs a corpus-wide aggregation "
                          "(chunks_v3 / announcement index)")
                return envelope("EVIDENCE", ok=False, why="schema", checked=CHECKED_FTS,
                                gap="chunks_v3", detail=detail, nid_reason=detail)
            try:
                window = _doc_window(slots, as_of)
                passages = _corpus_passages(
                    ctx, terms, as_of, slots.get("date_to") or as_of,
                    date_from=window[0] if window else None, limit=30)
            except Exception as exc:  # noqa: BLE001
                return envelope("EVIDENCE", ok=False, why="tool", checked=CHECKED_FTS,
                                detail=f"corpus search failed: {type(exc).__name__}: {exc}")
            passages = [p for p in passages
                        if (p.get("date") or "")[:10] and (p.get("date") or "")[:10] <= as_of]
            passages = _period_passages(passages, slots, as_of)
            if passages:
                passages = rerank.rank(passages, terms=terms,
                                       metric_terms=TEXT_TERMS.get(
                                           str(slots.get("metric") or ""), ()),
                                       as_of=as_of)
                top = passages[:3]
                detail = " | ".join(
                    f"{p.get('doc_type')} {p.get('date')}: {(p.get('text') or '')[:180]}"
                    for p in top[:2])
                return envelope(
                    "EVIDENCE", ok=True,
                    rows=[{"ref": f"{p.get('doc_type')}:{p.get('doc_id')}",
                           "known_at": p.get("date")} for p in top],
                    provenance=[{"ref": f"search_docs:{p.get('doc_id')}",
                                 "known_at": p.get("date")} for p in top],
                    pit=f"corpus rows dated <= {as_of} in the SQL", checked=CHECKED_FTS,
                    detail=detail)
        detail = (f"corpus search found no passage for {', '.join(terms[:3]) or 'the ask'} "
                  f"known by {as_of}")
        if list_ask:
            return envelope("EVIDENCE", ok=False, why="schema", checked=CHECKED_FTS,
                            gap="chunks_v3", detail=f"{detail}; a complete company list "
                            "needs chunks_v3", nid_reason="BLOCKED_SCHEMA: chunks_v3")
        if gate:
            return envelope("EVIDENCE", ok=False, why="schema", checked=CHECKED_FTS, gap=gate,
                            detail=f"{detail}; precise retrieval needs {gate}",
                            nid_reason=f"BLOCKED_SCHEMA: {gate}")
        return envelope("EVIDENCE", ok=False, why="no_doc", checked=CHECKED_FTS, detail=detail,
                        nid_reason=detail)
    doc_type = slots.get("doc_type")
    named = named_of(slots)
    date = named["date"] if named else None
    if date is None and slots.get("period_basis") in ("named date", "named dates"):
        date = slots.get("date_from")
    try:
        if needs.get("page"):
            tool = ctx.tool("doc_page")
            res = tool(symbol, date or as_of, int(needs["page"]), doc_type=doc_type,
                       as_of=as_of)
            if res.get("found") and res.get("text"):
                doc = res.get("document") or {}
                doc_day = str(doc.get("date") or "")[:10]
                window = _doc_window(slots, as_of)
                if window and not (len(doc_day) == 10 and window[0] <= doc_day <= window[1]):
                    detail = (f"page {res.get('page')} is in the {doc.get('doc_type')} of "
                              f"{doc_day}, outside the asked period ({slots.get('period')})")
                    return envelope("EVIDENCE", ok=False, why="no_doc",
                                    checked=res.get("checked") or CHECKED,
                                    detail=detail, nid_reason=detail)
                detail = (f"{doc.get('doc_type')} {doc.get('date')} page {res.get('page')}"
                          f"/{res.get('page_count')}: {(res.get('text') or '')[:300]}")
                return envelope(
                    "EVIDENCE", ok=True,
                    rows=[{"ref": f"page:{doc.get('doc_id')}#{res.get('page')}",
                           "known_at": doc.get("date") or as_of,
                           "period": doc_day or None,
                           "quote": (res.get("text") or "")[:300],
                           "isin": slots.get("isin"), "symbol": slots.get("symbol"),
                           "doc_type": doc.get("doc_type"), "page": res.get("page")}],
                    provenance=[{"ref": f"doc_page:{doc.get('doc_id')}",
                                 "known_at": doc.get("date") or as_of}],
                    pit=f"document known_at <= {as_of}", checked=res.get("checked") or CHECKED,
                    degraded=res.get("warnings") or [], detail=detail)
            detail = _missing(res)
            return envelope("EVIDENCE", ok=False, why="no_doc", checked=res.get("checked") or CHECKED,
                            detail=detail, nid_reason=detail)

        terms = [t for t in (slots.get("terms") or []) if len(t) > 3] or slots.get("terms") or []
        symbol_words = {str(symbol).lower(), str(slots.get("symbol") or "").lower()}
        meaningful = [t for t in terms if t.lower() not in symbol_words] or terms
        narrative = _narrative_of(question)
        narratives = _narratives_of(question)
        if not named and doc_type is None and str(slots.get("period_basis") or "") in (
                "named date", "named dates"):
            # The date names a price/fact session ("close on 16 Oct 2026"), not a
            # filing: the narrative evidence may come from any document known by
            # as_of.  Only a named document bounds the passage dates.
            slots = dict(slots, date_from=None, date_to=None)
            date = None
        if meaningful and _v3_covers(ctx, slots.get("isin"), slots.get("symbol")):
            # The chunks_v3 store is the authoritative text index for a pilot
            # ISIN.  Ranked FTS is the relevance signal here: half the ask's
            # terms is a clean answer and one term is a degraded answer.
            try:
                candidates = _chunks_v3_search(ctx, slots, as_of, doc_type)
            except Exception:  # noqa: BLE001 - a broken pilot DB falls to the FTS path
                candidates = None
            # Retrieve each concept's own passages as well: the ask's words
            # ("products", "facilities") are often slide-title words, while the
            # concept's evidence sits on another page of the same document.
            for _, concept_terms, _ in narratives:
                try:
                    extra = _chunks_v3_search(
                        ctx, dict(slots, terms=list(dict.fromkeys(
                            [*concept_terms, *meaningful]))), as_of, doc_type)
                except Exception:  # noqa: BLE001
                    extra = []
                candidates = (candidates or []) + extra
            # Extraction rows (rating actions, price revisions, contracts, cost inputs,
            # supply links) are passages too: quote + page + known_at, PIT-filtered.
            try:
                from reality_engine.query import metrics
                extra = metrics.evidence_rows(ctx, str(slots.get("isin") or ""), as_of,
                                              str(slots.get("question") or ""))
                if extra:
                    candidates = extra + (candidates or [])
            except Exception:  # noqa: BLE001
                pass
            if candidates is not None:
                candidates = _period_passages(candidates, slots, as_of, named)
                need = max(1, (len(meaningful) + 1) // 2)
                clean, partial = [], []
                if narrative:
                    # Rank by the concepts the passage actually carries; a title page
                    # that shares "Investor Presentation" is not the answer.  A
                    # two-concept ask needs one carrying passage per concept.
                    picked: list[dict[str, Any]] = []
                    for _, concept_terms, concept_types in narratives:
                        carrying = []
                        for passage in candidates:
                            quote = (str(passage.get("quote") or "") + " "
                                     + str(passage.get("header") or ""))
                            carried = _concept_hits(quote, concept_terms)
                            if not carried:
                                continue
                            hits = sum(1 for term in meaningful
                                       if term.lower() in quote.lower())
                            carrying.append((carried * 2 + hits, passage))
                        carrying.sort(key=lambda item: -item[0])
                        ordered = [passage for _, passage in carrying]
                        ordered = _prefer_doc_type(ordered, concept_types)
                        if ordered:
                            picked.append(ordered[0])
                    for passage in candidates:
                        if len(picked) >= 3:
                            break
                        if passage not in picked:
                            picked.append(passage)
                    if picked and any(
                            _narrative_hits(str(p.get("quote") or "") + " "
                                            + str(p.get("header") or ""), narratives)
                            for p in picked):
                        chosen = picked[:3]
                        detail = " | ".join(
                            f"{p.get('doc_type')} {p.get('date')} p{p.get('page')} "
                            f"{(p.get('section') or '')[:40]}: {(p.get('quote') or '')[:180]}"
                            for p in chosen[:2])
                        return envelope(
                            "EVIDENCE", ok=True,
                            rows=[{"ref": f"chunks_v3:{p.get('doc_id')}#{p.get('page')}",
                                   "known_at": p.get("date"), "date": p.get("date"),
                                   "doc_type": p.get("doc_type"), "page": p.get("page"),
                                   "quote": (p.get("quote") or "")[:300],
                                   "section": p.get("section"),
                                   "isin": slots.get("isin") or p.get("isin"),
                                   "symbol": slots.get("symbol") or p.get("symbol"),
                                   "period": p.get("period")}
                                  for p in chosen],
                            provenance=[{"ref": f"chunks_v3:{p.get('doc_id')}#{p.get('page')}",
                                         "known_at": p.get("date")} for p in chosen],
                            pit=f"chunk known_at <= {as_of} pushed into the FTS + filter SQL",
                            checked=CHECKED_V3,
                            degraded=[],
                            detail=detail)
                    return envelope(
                        "EVIDENCE", ok=False, why="no_doc", checked=CHECKED_V3,
                        detail=f"no chunk of {symbol} carries the asked "
                               f"{', '.join(n for n, _, _ in narratives)} concept(s) "
                               f"known by {as_of}",
                        nid_reason="no passage in chunks_v3")
                for passage in candidates:
                    quote = str(passage.get("quote") or "").lower()
                    hits = sum(1 for term in meaningful if term.lower() in quote)
                    if hits >= need:
                        clean.append((hits, passage))
                    elif hits:
                        partial.append((hits, passage))
                clean.sort(key=lambda item: -item[0])
                partial.sort(key=lambda item: -item[0])
                if clean or partial:
                    chosen = [passage for _, passage in (clean or partial)[:3]]
                    detail = " | ".join(
                        f"{p.get('doc_type')} {p.get('date')} p{p.get('page')} "
                        f"{(p.get('section') or '')[:40]}: {(p.get('quote') or '')[:180]}"
                        for p in chosen[:2])
                    return envelope(
                        "EVIDENCE", ok=True,
                        rows=[{"ref": f"chunks_v3:{p.get('doc_id')}#{p.get('page')}",
                               "known_at": p.get("date"), "date": p.get("date"),
                               "doc_type": p.get("doc_type"), "page": p.get("page"),
                               "quote": (p.get("quote") or "")[:300],
                               "section": p.get("section"),
                               "isin": slots.get("isin") or p.get("isin"),
                               "symbol": slots.get("symbol") or p.get("symbol"),
                               "period": p.get("period")}
                              for p in chosen],
                        provenance=[{"ref": f"chunks_v3:{p.get('doc_id')}#{p.get('page')}",
                                     "known_at": p.get("date")} for p in chosen],
                        pit=f"chunk known_at <= {as_of} pushed into the FTS + filter SQL",
                        checked=CHECKED_V3,
                        degraded=([] if clean else ["chunks_v3: top passages match only part of the ask"]),
                        detail=detail)
                return envelope(
                    "EVIDENCE", ok=False, why="no_doc", checked=CHECKED_V3,
                    detail=f"no chunk of {symbol} carries {', '.join(meaningful[:3])} "
                           f"known by {as_of}", nid_reason="no passage in chunks_v3")

        override = getattr(ctx, "overrides", {}).get("doc_find")
        if override is not None:
            # An injected tool (tests, alternate retrievers) owns the passage set.
            res = override(symbol, " ".join(meaningful[:3]), doc_type=doc_type,
                           date=date, as_of=as_of)
            passages = [p for p in (res.get("passages") or [])
                        if (p.get("date") or "")[:10]
                        and (p.get("date") or "")[:10] <= as_of]
            passages = _period_passages(passages, slots, as_of, named)
            res = dict(res, checked=res.get("checked") or CHECKED_FTS)
        else:
            passages = _fts_passages(ctx, slots, meaningful, as_of, doc_type, date, limit=30)
            for _, concept_terms, _ in narratives:
                # The deck/AR read must be centred on the concept's own words: a
                # snippet around "presentation" is not the facilities page.
                try:
                    passages += _store_passages(
                        ctx, dict(slots, terms=list(concept_terms)),
                        list(concept_terms), as_of, doc_type, date)
                except Exception:  # noqa: BLE001 - a satellite store miss is not fatal
                    pass
            if not passages:
                # Chunk index miss for a deck/AR ask: the vision page text and the AR
                # fact quotes are separate stores; both reads are index-bounded.
                try:
                    passages = _store_passages(ctx, slots, meaningful, as_of, doc_type, date)
                except Exception:  # noqa: BLE001 - a satellite store miss is not fatal
                    passages = []
            passages = _period_passages(passages, slots, as_of, named)
            if narratives and passages:
                carrying = [p for p in passages if _narrative_hits(
                    str(p.get("quote") or p.get("text") or "") + " " + str(p.get("header") or ""),
                    narratives)]
                if carrying:
                    passages = _prefer_doc_type(carrying, _narrative_types(narratives))
            res = {"checked": CHECKED_FTS, "warnings": []}
        found_any = bool(passages)
        if meaningful and passages:
            # A passage only answers the hop when its own quote carries the ask's
            # meaningful terms (not just the company name).  At least half must hit.
            # A text ask with no numeric metric has no metric family to fall back
            # on: the query itself was the relevance test, so one hit is enough.
            need = 1 if not slots.get("metric") else max(1, (len(meaningful) + 1) // 2)
            metric_words = [word.lower() for word in
                            asked_words(question, str(slots.get("metric") or "") or None)]
            scored = []
            for passage in passages:
                quote = str(passage.get("quote") or passage.get("text") or "").lower()
                hits = sum(1 for term in meaningful if term.lower() in quote)
                metric_hit = any(word in quote for word in metric_words)
                carried = _narrative_hits(quote, narratives) if narratives else 0
                if carried or hits >= need or metric_hit:
                    scored.append((carried * 3 + hits + (1 if metric_hit else 0), passage))
            scored.sort(key=lambda item: -item[0])
            passages = [passage for _, passage in scored]
            if narratives:
                passages = _prefer_doc_type(passages, _narrative_types(narratives))
            if not passages:
                res["reason"] = (f"documents are held but no passage carries "
                                 f"{', '.join(meaningful[:3])}")
                found_any = True
        if not passages and not found_any:
            detail = (f"no passage of {symbol} carries {', '.join(meaningful[:3])} "
                      f"known by {as_of}")
            if gate:
                return envelope("EVIDENCE", ok=False, why="schema", checked=CHECKED_FTS, gap=gate,
                                detail=f"{detail}; precise retrieval needs {gate}",
                                nid_reason=f"BLOCKED_SCHEMA: {gate}")
            return envelope("EVIDENCE", ok=False, why="no_doc", checked=CHECKED_FTS,
                            detail=detail, nid_reason=detail)
        # Named-document preference: when the question names a document, its
        # passages only.  The nearest held document is not a substitute.
        if named and passages:
            anchor = _date.fromisoformat(str(named["date"])[:10])
            inside = []
            for passage in passages:
                try:
                    day = _date.fromisoformat(str(passage.get("date") or "")[:10])
                except ValueError:
                    continue
                if abs((day - anchor).days) <= DOC_WINDOW_DAYS:
                    inside.append(passage)
            if not inside:
                wanted = (f"the {named['doc_type']} of {named['date']} carries no passage for "
                          f"{', '.join(meaningful[:3]) or 'the ask'}; a different document is "
                          f"not the one asked for")
                return envelope("EVIDENCE", ok=False, why="no_doc",
                                checked=res.get("checked") or CHECKED_FTS, detail=wanted,
                                nid_reason=wanted)
            passages = inside
        metric_terms = asked_words(question, str(slots.get("metric") or "") or None)
        passages = rerank.rank(
            passages, terms=meaningful or terms, metric_terms=metric_terms,
            entity=str(slots.get("symbol") or slots.get("isin") or ""),
            named_date=(named or {}).get("date") or date, as_of=as_of)
        top = passages[:3]
        if narratives:
            # A two-concept ask needs one carrying passage per concept before the
            # generic ranking fills the remaining slots.
            picked: list[dict[str, Any]] = []
            for _, concept_terms, _ in narratives:
                for passage in passages:
                    text = str(passage.get("quote") or passage.get("text") or "")
                    if passage not in picked and _concept_hits(text, concept_terms):
                        picked.append(passage)
                        break
            for passage in passages:
                if len(picked) >= 3:
                    break
                if passage not in picked:
                    picked.append(passage)
            top = picked[:3]
        detail = " | ".join(
            f"{p.get('doc_type')} {p.get('date')} p{p.get('page')}: "
            f"{(p.get('quote') or '')[:180]}" for p in top[:2])
        return envelope(
            "EVIDENCE", ok=True,
            rows=[{"ref": f"{p.get('store')}:{p.get('doc_id')}#{p.get('page')}",
                   "known_at": p.get("date"), "date": p.get("date"),
                   "period": p.get("period"),
                   "isin": slots.get("isin") or p.get("isin"),
                   "symbol": slots.get("symbol") or p.get("symbol"),
                   "doc_type": p.get("doc_type"), "page": p.get("page"),
                   "quote": (p.get("quote") or "")[:300], "score": p.get("score")}
                  for p in top],
            provenance=[{"ref": f"{p.get('store')}:{p.get('doc_id')}",
                         "known_at": p.get("date")} for p in top],
            pit=f"chunk published_date / document known_at <= {as_of} in the SQL",
            checked=res.get("checked") or CHECKED_FTS,
            degraded=(res.get("warnings") or []) + (
                [f"named-document preference: {named['doc_type']} of {named['date']} "
                 f"(±{DOC_WINDOW_DAYS}d)"] if named else []),
            detail=detail)
    except Exception as exc:  # noqa: BLE001 - a tool failure is data, not a crash
        return envelope("EVIDENCE", ok=False, why="tool", checked=CHECKED_FTS,
                        detail=f"document tool failed: {type(exc).__name__}: {exc}")
