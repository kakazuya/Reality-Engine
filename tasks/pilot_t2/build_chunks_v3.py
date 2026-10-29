"""Build the chunks_v3 pilot store for the 30-ISIN PILOT_SPEC universe.

    python tasks/pilot_t2/build_chunks_v3.py [--limit N] [--workers 1]

Writes ``.tmp/pilot/chunks_v3_pilot.db`` (overridable with REALITY_CHUNKS_V3) with
the §A DDL from ``tasks/arch_v3/SCHEMA_V3.sql`` plus ``chunk_entity`` and the
additive ``doc.needs_ocr`` column.

Read-only on D: and every DB.  known_at comes from the filing record only
(BSE DissemDT, NSE exchdisstime, cc_docs.filed_at, ar_docs.filed_at,
deck_sources.known_at); a crawl/file date is never used.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sqlite3
import sys
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from reality_engine.db.readonly import connect_ro  # noqa: E402
from reality_engine.processing import chunker_v3 as v3  # noqa: E402

DATA = Path(os.environ.get("REALITY_DATA_ROOT",
                           r"C:\Users\warri\Downloads\Info_Diffusion_Model\reality_engine\data"))
D_RAW = Path(r"D:\RealityEngine\raw")
D_PDFS = Path(r"D:\RealityEngine\pdfs")
CUTOFF = "2024-04-01"
OUT_DIR = REPO / "tasks" / "pilot_t2"
DB_PATH = Path(os.environ.get("REALITY_CHUNKS_V3") or (REPO / ".tmp" / "pilot" / "chunks_v3_pilot.db"))
# results notes: the page store built by scripts/fetch_results_notes_text.py, and the
# PDF cache it shares (the BSE Pname uuid is the file name under the raw root).
RESULTS_NOTES_DB = Path(os.environ.get("REALITY_RESULTS_NOTES_DB")
                        or (REPO / ".tmp" / "results_notes" / "results_notes.db"))
RESULTS_RAW = Path(os.environ.get("REALITY_RESULTS_RAW") or (REPO / ".tmp" / "results_notes_raw"))

TYPE_PRIORITY = {"annual_report": 0, "concall": 1, "results_notes": 2, "deck": 3, "announcement": 4}
DOC_TYPE_MAP = {"CONCALL_TRANSCRIPT": "concall", "ANNUAL_REPORT": "annual_report",
                "INVESTOR_PRESENTATION": "deck", "FINANCIAL_RESULT": "results_notes",
                "RESULTS": "results_notes", "ANNOUNCEMENT": "announcement",
                "OFFER_DOCUMENT": "offer"}
UUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
LONG_NUM_RE = re.compile(r"\d{4,}")

SCHEMA = (REPO / "tasks" / "arch_v3" / "SCHEMA_V3.sql").read_text(encoding="utf-8")
CHUNK_ENTITY_DDL = """
CREATE TABLE IF NOT EXISTS chunk_entity (
    isin     TEXT NOT NULL,
    symbol   TEXT NOT NULL,
    chunk_id INTEGER NOT NULL,
    PRIMARY KEY (isin, symbol, chunk_id)
) WITHOUT ROWID;
"""


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------


@dataclass
class DocMeta:
    doc_id: str
    source: str
    doc_type: str
    isin: str
    symbol: str
    title: str
    known_at: str
    known_at_src: str
    pit_conf: float
    fiscal_period: str
    raw_path: str
    raw_url: str = ""
    source_ref: str = ""
    event_date: str = ""
    category: str = ""


@dataclass
class Draft:
    meta: DocMeta
    sha256: str
    path: Path
    source_ref: str = ""
    pages: list[str] | None = None  # page text from the results_notes store (no PDF needed)


def ro(path: Path) -> sqlite3.Connection:
    con = connect_ro(path, timeout_s=90)
    con.row_factory = sqlite3.Row
    return con


def parse_ts(value: str | None) -> str | None:
    """Normalise a filing timestamp to ISO-8601 IST text (date-only -> 23:59:59)."""
    if not value:
        return None
    s = str(value).strip()
    if not s:
        return None
    if re.match(r"^\d{4}-\d{2}-\d{2}$", s):
        return s + "T23:59:59"
    s = s.replace(" ", "T")
    m = re.match(r"^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})", s)
    if m:
        return f"{m.group(1)}T{m.group(2)}"
    for fmt in ("%d-%b-%YT%H:%M:%S", "%d-%m-%YT%H:%M:%S", "%d-%b-%YT%H:%M"):
        try:
            return time.strftime("%Y-%m-%dT%H:%M:%S", time.strptime(s, fmt))
        except ValueError:
            pass
    return None


def norm_symbol(value: str | None) -> str:
    return (value or "").strip().upper().replace("&", "_")


def pilot_isins() -> list[str]:
    spec = (REPO / "tasks" / "arch_v3" / "PILOT_SPEC.md").read_text(encoding="utf-8")
    return re.findall(r"\|\s*\d+\s*\|\s*(INE[A-Z0-9]{9})\s*\|", spec)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def isin_alias(isins: list[str]) -> dict[str, str]:
    """Old ISIN -> pilot ISIN for the same company (split/face-value rekeys).

    Evidence is ``symbol_isin_history``: the pilot symbol traded under two ISINs.
    Without this an APLAPOLLO call from 2024 is invisible to a filter on today's
    ISIN.  Two of the thirty pilot ISINs have a predecessor in FY25+ scope.
    """
    con = ro(DATA / "equity_intelligence.db")
    spec = (REPO / "tasks" / "arch_v3" / "PILOT_SPEC.md").read_text(encoding="utf-8")
    pilot_symbol = {sym: isin for isin, sym in
                    re.findall(r"\|\s*\d+\s*\|\s*(INE[A-Z0-9]{9})\s*\|\s*([A-Z0-9&-]+)\s*\|", spec)}
    if not pilot_symbol:
        q = ",".join("?" * len(isins))
        pilot_symbol = {r["symbol"]: r["isin"] for r in con.execute(
            f"SELECT isin, symbol FROM corporate_documents WHERE isin IN ({q}) GROUP BY isin",
            isins)}
    symbols = sorted(s for s in pilot_symbol if s)
    alias: dict[str, str] = {}
    if symbols:
        for r in con.execute(
                f"SELECT symbol, isin FROM symbol_isin_history "
                f"WHERE symbol IN ({','.join('?' * len(symbols))})", symbols):
            target = pilot_symbol.get(r["symbol"])
            if target and r["isin"] != target:
                alias[r["isin"]] = target
    return alias


class FileIndex:
    """Basename index over the D: PDF trees (one walk, then O(1) lookups)."""

    def __init__(self) -> None:
        self.paths: list[Path] = []
        self.by_name: dict[str, list[Path]] = {}
        t0 = time.perf_counter()
        for root in (D_PDFS, D_RAW):
            if root.is_dir():
                for p in root.rglob("*.pdf"):
                    self.paths.append(p)
                    self.by_name.setdefault(p.name.lower(), []).append(p)
        print(f"indexed {len(self.paths)} D: PDFs in {time.perf_counter() - t0:.1f}s")

    def by_sha(self, sha: str) -> Path | None:
        hits = self.by_name.get(f"{sha.lower()}.pdf")
        return hits[0] if hits else None

    def by_key(self, symbol: str, text: str) -> Path | None:
        """Find a PDF whose name carries a uuid/long number from ``text``."""
        keys = [m.group(0).lower() for m in UUID_RE.finditer(text or "")]
        keys += [m.group(0) for m in LONG_NUM_RE.finditer(Path(text or "").name)]
        if not keys:
            return None
        sym = symbol.lower()
        for key in keys:
            for name, paths in self.by_name.items():
                if key in name:
                    for p in paths:
                        if sym and sym in str(p).lower():
                            return p
        return None


# ---------------------------------------------------------------------------
# Registry loads
# ---------------------------------------------------------------------------


def load_annual_reports(isins: list[str], index: FileIndex) -> list[Draft]:
    con = ro(DATA / "ar_facts.db")
    q = ",".join("?" * len(isins))
    rows = con.execute(
        f"SELECT doc_id, isin, symbol, fiscal_year, filed_at, filed_at_source, sha256, path "
        f"FROM ar_docs WHERE isin IN ({q}) AND filed_at >= ? ORDER BY filed_at", isins + [CUTOFF])
    out = []
    for r in rows:
        path = Path(r["path"]) if r["path"] else None
        if not (path and path.is_file()):
            path = index.by_key(r["symbol"] or "", r["path"] or "") or index.by_sha(r["sha256"] or "")
        if not path:
            out.append(Draft(_ar_meta(r, "", None), r["sha256"] or "", Path(""), r["doc_id"]))
            continue
        fy = (r["fiscal_year"] or "")[:4]
        out.append(Draft(_ar_meta(r, str(path), fy), r["sha256"] or "", path, r["doc_id"]))
    return out


def _ar_meta(r: sqlite3.Row, raw_path: str, fy: str) -> DocMeta:
    src = (r["filed_at_source"] or "").lower()
    known_src = src if src in v3.PIT_CONFIDENCE else "filing_date"
    return DocMeta(
        doc_id=(r["sha256"] or f"ar_facts:{r['doc_id']}"),
        source="ar_facts.ar_docs", doc_type="annual_report", isin=r["isin"],
        symbol=norm_symbol(r["symbol"]), title=f"{r['symbol']} annual report {r['fiscal_year']}",
        known_at=parse_ts(r["filed_at"]) or "", known_at_src=known_src,
        pit_conf=v3.pit_confidence(known_src), fiscal_period=f"FY{fy[2:]}" if fy else "",
        raw_path=raw_path, source_ref=str(r["doc_id"]), event_date=(r["filed_at"] or "")[:10])


def load_concalls(isins: list[str], index: FileIndex) -> list[Draft]:
    con = ro(DATA / "equity_intelligence.db")
    q = ",".join("?" * len(isins))
    rows = con.execute(
        f"SELECT id, isin, symbol, title, publication_date, bse_dissem_ts, call_date, "
        f"sha256_hash, local_file_path, source_url, fiscal_period_end "
        f"FROM corporate_documents WHERE isin IN ({q}) AND doc_type='CONCALL_TRANSCRIPT' "
        f"AND COALESCE(bse_dissem_ts, publication_date) >= ? ORDER BY bse_dissem_ts",
        isins + [CUTOFF]).fetchall()
    cc = ro(DATA / "concall_facts.db")
    filed = {}
    try:
        for r in cc.execute("SELECT doc_id, filed_at, period_q, period_fy FROM cc_docs"):
            filed[int(r["doc_id"])] = r
    except Exception:  # noqa: BLE001 - the fallback is optional
        pass
    out = []
    for r in rows:
        known, src = parse_ts(r["bse_dissem_ts"]), "bse_dissem"
        if not known:
            known, src = parse_ts(r["publication_date"]), "filing_date"
        if not known and int(r["id"]) in filed:
            known, src = parse_ts(filed[int(r["id"])]["filed_at"]), "filing_date"
        if not known:
            continue
        path = index.by_sha(r["sha256_hash"] or "")
        if not path and r["local_file_path"]:
            path = index.by_name.get(Path(r["local_file_path"]).name.lower(), [None])[0]
        if not path:
            path = index.by_key(r["symbol"] or "", r["local_file_path"] or "")
        period = ""
        if not period and int(r["id"]) in filed:
            fr = filed[int(r["id"])]
            if fr["period_q"] and fr["period_fy"]:
                period = f"Q{int(fr['period_q'])}FY{int(fr['period_fy']) % 100:02d}"
        meta = DocMeta(
            doc_id=(r["sha256_hash"] or f"corporate_documents:{r['id']}"),
            source="corporate_documents", doc_type="concall", isin=r["isin"],
            symbol=norm_symbol(r["symbol"]), title=r["title"] or "Concall transcript",
            known_at=known, known_at_src=src, pit_conf=v3.pit_confidence(src),
            fiscal_period=period, raw_path=str(path) if path else "",
            raw_url=r["source_url"] or "", source_ref=str(r["id"]),
            event_date=(r["call_date"] or "")[:10])
        out.append(Draft(meta, r["sha256_hash"] or "", path or Path(""), str(r["id"])))
    return out


def load_decks(isins: list[str], index: FileIndex) -> list[Draft]:
    con = ro(DATA / "deck_figures.db")
    q = ",".join("?" * len(isins))
    rows = con.execute(
        f"SELECT source, source_id, symbol, isin, known_at, title, url, local_path, sha256 "
        f"FROM deck_sources WHERE isin IN ({q}) AND known_at >= ? ORDER BY known_at",
        isins + [CUTOFF])
    out = []
    for r in rows:
        path = index.by_sha(r["sha256"] or "")
        if not path and r["local_path"] and Path(r["local_path"]).is_file():
            path = Path(r["local_path"])
        if not path:
            path = index.by_key(r["symbol"] or "", f"{r['source_id'] or ''} {r['local_path'] or ''}")
        known = parse_ts(r["known_at"])
        if not known:
            continue
        src = "bse_dissem" if (r["source"] or "").lower() == "bse" else "nse_dissem"
        meta = DocMeta(
            doc_id=(r["sha256"] or f"deck_sources:{r['source_id']}"),
            source="deck_sources", doc_type="deck", isin=r["isin"],
            symbol=norm_symbol(r["symbol"]), title=r["title"] or "Investor deck",
            known_at=known, known_at_src=src, pit_conf=v3.pit_confidence(src),
            fiscal_period="", raw_path=str(path) if path else "", raw_url=r["url"] or "",
            source_ref=str(r["source_id"]), event_date=known[:10])
        out.append(Draft(meta, r["sha256"] or "", path or Path(""), str(r["source_id"])))
    return out


def load_results_notes(isins: list[str], index: FileIndex) -> list[Draft]:
    """Resolve a results document by its stored pages, else by its Pname uuid PDF.

    The pages come from ``RESULTS_NOTES_DB`` keyed ISIN + period + newsid; the newsid
    is the BSE announcement of the ``Pname`` attachment in ``source_url``.  When the
    page store has nothing for it, the PDF of that Pname name (staged under
    ``RESULTS_RAW`` from the Drive copy) is the fallback.  ``known_at`` is the BSE
    announcement time (``ann.DissemDT``), never a crawl date.
    """
    con = ro(DATA / "equity_intelligence.db")
    q = ",".join("?" * len(isins))
    rows = con.execute(
        f"SELECT id, isin, symbol, title, publication_date, bse_dissem_ts, sha256_hash, "
        f"source_url, fiscal_period_end FROM corporate_documents WHERE isin IN ({q}) "
        f"AND doc_type IN ('FINANCIAL_RESULT','RESULTS') "
        f"AND COALESCE(bse_dissem_ts, publication_date) >= ?", isins + [CUTOFF]).fetchall()
    con.close()
    attachments = []
    for r in rows:
        m = PNAME_RE.search(r["source_url"] or "")
        if m:
            attachments.append(m.group(1).lower())
    newsids = _newsid_index(sorted(set(attachments)))
    raw = _raw_pdf_index()
    store = None
    if RESULTS_NOTES_DB.is_file():
        try:
            store = ro(RESULTS_NOTES_DB)
            if not store.execute("SELECT 1 FROM sqlite_master WHERE type='table' "
                                 "AND name='results_notes'").fetchone():
                store.close()
                store = None
        except Exception:  # noqa: BLE001 - a missing page store is a fallback, not a failure
            store = None
    out = []
    try:
        for r in rows:
            m = PNAME_RE.search(r["source_url"] or "")
            attachment = m.group(1) if m else ""
            newsid, dissem = newsids.get(attachment.lower(), ("", ""))
            known = parse_ts(dissem) or parse_ts(r["bse_dissem_ts"]) or parse_ts(r["publication_date"])
            if not known:
                continue
            src = "bse_dissem" if dissem or r["bse_dissem_ts"] else "filing_date"
            period = (r["fiscal_period_end"] or "")[:10]
            pages = None
            stored = _stored_pages(store, r["isin"], period, newsid) if (store and newsid) else None
            if stored:
                period, stored_known, pages = stored
                known = parse_ts(stored_known) or known
            path = raw.get(attachment.lower()) if attachment else None
            if path is None and newsid:
                path = raw.get(f"{newsid}.pdf")
            meta = DocMeta(
                doc_id=(r["sha256_hash"] or f"corporate_documents:{r['id']}"),
                source="corporate_documents", doc_type="results_notes", isin=r["isin"],
                symbol=norm_symbol(r["symbol"]), title=r["title"] or "Results notes",
                known_at=known, known_at_src=src, pit_conf=v3.pit_confidence(src),
                fiscal_period=_quarter_label(period), raw_path=str(path) if path else "",
                raw_url=r["source_url"] or "", source_ref=str(r["id"]), event_date=known[:10])
            out.append(Draft(meta, r["sha256_hash"] or "", path or Path(""), str(r["id"]), pages))
    finally:
        if store is not None:
            store.close()
    return out


PNAME_RE = re.compile(r"[?&]Pname=([^&\s]+)", re.IGNORECASE)


def _quarter_label(period_end: str) -> str:
    """``2026-06-30`` -> ``Q1FY27`` (empty when the period is unknown)."""
    try:
        d = date.fromisoformat(str(period_end)[:10])
    except (ValueError, TypeError):
        return ""
    q = {3: 4, 6: 1, 9: 2, 12: 3}.get(d.month)
    if not q:
        return ""
    return f"Q{q}FY{(d.year + 1 if d.month != 3 else d.year) % 100:02d}"


def _raw_pdf_index() -> dict[str, Path]:
    """Basename -> path for the results-notes PDF cache (Pname and newsid names)."""
    out: dict[str, Path] = {}
    if RESULTS_RAW.is_dir():
        for p in RESULTS_RAW.rglob("*.pdf"):
            out.setdefault(p.name.lower(), p)
    return out


def _newsid_index(attachments: list[str]) -> dict[str, tuple[str, str]]:
    """BSE attachment name (the Pname uuid) -> (NEWSID, DissemDT)."""
    if not attachments:
        return {}
    out: dict[str, tuple[str, str]] = {}
    con = ro(DATA / "bse_announcements.db")
    try:
        for i in range(0, len(attachments), 400):
            batch = attachments[i:i + 400]
            q = ",".join("?" * len(batch))
            for r in con.execute(f"SELECT ATTACHMENTNAME, NEWSID, DissemDT FROM ann "
                                 f"WHERE ATTACHMENTNAME IN ({q})", batch):
                if r["DissemDT"]:
                    out[r["ATTACHMENTNAME"].lower()] = (str(r["NEWSID"]), r["DissemDT"])
    finally:
        con.close()
    return out


def _stored_pages(con: sqlite3.Connection, isin: str, period: str,
                  newsid: str) -> tuple[str, str, list[str]] | None:
    """(period_end, known_at, page texts) from results_notes, keyed ISIN+period+newsid."""
    sql = ("SELECT period_end, known_at, page_no, text FROM results_notes "
           "WHERE isin = ? AND source_newsid = ?")
    params: list[str] = [isin, newsid]
    if period:
        sql += " AND period_end = ?"
        params.append(period)
    rows = con.execute(sql + " ORDER BY period_end, page_no", params).fetchall()
    if not rows:
        return None
    period_end = rows[0]["period_end"]
    pages = [r["text"] or "" for r in rows if r["period_end"] == period_end]
    return period_end, rows[0]["known_at"] or "", pages



def load_bse_announcements(isins: list[str], index: FileIndex) -> list[Draft]:
    """The pilot fetch manifests (material announcements downloaded today)."""
    ann = ro(DATA / "bse_announcements.db")
    meta_by_newsid = {}
    cd = ro(DATA / "equity_intelligence.db")
    q = ",".join("?" * len(isins))
    by_symbol = {}
    for r in cd.execute(f"SELECT isin, symbol FROM corporate_documents WHERE isin IN ({q}) "
                        f"GROUP BY isin", isins):
        by_symbol[norm_symbol(r["symbol"])] = r["isin"]
    syms = sorted(by_symbol)
    for r in ann.execute(
            "SELECT NEWSID, symbol, DissemDT, HEADLINE, NEWSSUB, SUBCATNAME, ATTACHMENTNAME "
            f"FROM ann WHERE symbol IN ({','.join('?' * len(syms))})", syms):
        meta_by_newsid[str(r["NEWSID"])] = r
        if r["ATTACHMENTNAME"]:
            meta_by_newsid.setdefault(r["ATTACHMENTNAME"].lower(), r)
    out = []
    seen = set()
    for manifest in sorted((D_RAW / "originals_lists").glob("todo_*.manifest.csv")):
        if "annual_report" in manifest.name or "deck" in manifest.name:
            continue
        for row in csv.DictReader(manifest.open(encoding="utf-8", newline="")):
            sym = norm_symbol(row.get("symbol"))
            if sym not in by_symbol or row.get("status") != "ok":
                continue
            key = str(row.get("key") or "")
            path = Path(row.get("path") or "")
            if not key or not path.is_file() or str(path) in seen:
                continue
            seen.add(str(path))
            record = meta_by_newsid.get(key)
            if not record:
                # the BSE fetch key is an internal id; the attachment file name is
                # the join to the filing record (and its dissemination timestamp)
                record = meta_by_newsid.get(Path(row.get("url") or "").name.lower())
            known = parse_ts(record["DissemDT"]) if record else None
            if not known:
                continue
            title = (record["HEADLINE"] or record["NEWSSUB"] or "Announcement") if record else "Announcement"
            category = (record["SUBCATNAME"] or "") if record else ""
            ref = str(record["NEWSID"]) if record else key
            meta = DocMeta(
                doc_id=f"bse_ann:{ref}", source="bse_announcements.ann",
                doc_type="announcement", isin=by_symbol[sym], symbol=sym, title=title,
                known_at=known, known_at_src="bse_dissem", pit_conf=v3.pit_confidence("bse_dissem"),
                fiscal_period="", raw_path=str(path), raw_url=row.get("url") or "",
                source_ref=ref, event_date=known[:10], category=category)
            out.append(Draft(meta, "", path, ref))
    return out


def load_nse_attachments(isins: list[str], index: FileIndex) -> list[Draft]:
    """NSE announcement attachments fetched today (`nse_announcements/*/attachments`)."""
    cd = ro(DATA / "equity_intelligence.db")
    q = ",".join("?" * len(isins))
    by_symbol = {norm_symbol(r["symbol"]): r["isin"] for r in cd.execute(
        f"SELECT isin, symbol FROM corporate_documents WHERE isin IN ({q}) GROUP BY isin", isins)}
    out = []
    seen = set()
    for run in sorted((D_RAW / "nse_announcements").glob("*")):
        att = run / "attachments"
        if not att.is_dir():
            continue
        for sym, isin in by_symbol.items():
            sym_dir = att / sym
            if not sym_dir.is_dir():
                continue
            jsonl = run / f"{sym}.jsonl"
            rows = []
            if jsonl.is_file():
                rows = [json.loads(line) for line in jsonl.read_text(encoding="utf-8").splitlines()
                        if line.strip()]
            for row in rows:
                url = row.get("attachment_url") or ""
                local = sym_dir / Path(url).name
                if not local.is_file() or str(local) in seen:
                    continue
                known = parse_ts(row.get("known_at"))
                if not known:
                    continue
                seen.add(str(local))
                kind = str(row.get("kind") or "")
                doc_type = "concall" if kind == "transcript" else "announcement"
                title = (row.get("raw") or {}).get("attchmntText") or row.get("desc") or kind or "NSE filing"
                meta = DocMeta(
                    doc_id=f"nse_ann:{row.get('seq_id') or local.name}", source="nse_announcements",
                    doc_type=doc_type, isin=by_symbol.get(sym) or row.get("isin") or isin,
                    symbol=sym,
                    title=str(title)[:400], known_at=known, known_at_src="nse_dissem",
                    pit_conf=v3.pit_confidence("nse_dissem"), fiscal_period="",
                    raw_path=str(local), raw_url=url, source_ref=str(row.get("seq_id") or ""),
                    event_date=known[:10], category=str(row.get("bucket") or ""))
                out.append(Draft(meta, "", local, meta.source_ref))
    return out


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


def open_store(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    con = sqlite3.connect(path)
    a = SCHEMA.index("-- §A  chunks_v3.db")
    b = SCHEMA.index("-- §B  market_state.db")
    con.executescript(SCHEMA[a:b])
    con.executescript(CHUNK_ENTITY_DDL)
    con.execute("ALTER TABLE doc ADD COLUMN needs_ocr INTEGER NOT NULL DEFAULT 0")
    con.commit()
    return con


def write_doc(con: sqlite3.Connection, draft: Draft, sha: str, grade: str, needs_ocr: int,
              pages: int, chars: int, run_id: str) -> None:
    m = draft.meta
    con.execute(
        "INSERT OR REPLACE INTO doc (doc_id, sha256, source, doc_type, source_class, isin, "
        "symbol_at_time, title, event_date, known_at, known_at_src, pit_conf, fiscal_period, "
        "page_count, parse_route, quality_grade, char_count, raw_path, raw_url, build_run, needs_ocr) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (m.doc_id, sha or None, m.source, m.doc_type, "truth", m.isin, m.symbol, m.title[:500],
         m.event_date, m.known_at, m.known_at_src, m.pit_conf, m.fiscal_period, pages,
         "pymupdf_text", grade, chars, m.raw_path, m.raw_url, run_id, needs_ocr))


def write_chunks(con: sqlite3.Connection, draft: Draft, chunks: list[v3.ChunkV3]) -> int:
    m = draft.meta
    n = 0
    for i, c in enumerate(chunks):
        cur = con.execute(
            "INSERT INTO chunk (doc_id, chunk_index, header, body, char_len, section, speaker, "
            "speaker_role, unit_kind, page_from, page_to, span_start, span_end, isin, "
            "symbol_at_time, doc_type, source_class, known_at, event_date, fiscal_period, "
            "n_numbers, forward_looking, quality_grade, pit_conf, content_tags) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (m.doc_id, i, c.header, c.body, c.char_len, c.section, c.speaker or None,
             c.speaker_role or "unknown", c.unit_kind, c.page_from, c.page_to, c.span_start,
             c.span_end, c.isin, c.symbol_at_time, c.doc_type, "truth", c.known_at, m.event_date,
             c.fiscal_period, c.n_numbers, c.forward_looking, c.quality_grade, c.pit_confidence,
             c.content_tags))
        chunk_id = cur.lastrowid
        n += 1
        for tag in c.tags:
            con.execute("INSERT OR IGNORE INTO chunk_tag (tag, chunk_id, tagger, confidence) "
                        "VALUES (?,?,?,?)", (tag, chunk_id, "deterministic", 1.0))
        for isin, label in c.entities:
            con.execute("INSERT OR IGNORE INTO chunk_entity (isin, symbol, chunk_id) VALUES (?,?,?)",
                        (isin, label, chunk_id))
    return n


def write_tag_vocab(con: sqlite3.Connection) -> None:
    for tag, (axis, label, definition, excludes) in v3.TAG_VOCAB.items():
        con.execute("INSERT OR REPLACE INTO tag_vocab (tag, axis, label, definition, excludes) "
                    "VALUES (?,?,?,?,?)", (tag, axis, label, definition, excludes))


def build(limit: int | None = None) -> dict:
    isins = pilot_isins()
    print(f"pilot ISINs: {len(isins)}")
    index = FileIndex()
    drafts = (load_annual_reports(isins, index) + load_concalls(isins, index)
              + load_decks(isins, index) + load_results_notes(isins, index)
              + load_bse_announcements(isins, index) + load_nse_attachments(isins, index))
    alias = isin_alias(isins)
    if alias:
        print(f"ISIN predecessors remapped to the pilot ISIN: {alias}")
        for draft in drafts:
            draft.meta.isin = alias.get(draft.meta.isin, draft.meta.isin)
    print(f"registry drafts: {len(drafts)}")

    # Dedupe by content: the same PDF fetched through two registries is one doc.
    chosen: dict[str, Draft] = {}
    for d in drafts:
        key = d.sha256 or (d.meta.doc_id if d.path else "")
        if not key:
            continue
        old = chosen.get(key)
        if old is None or TYPE_PRIORITY.get(d.meta.doc_type, 9) < TYPE_PRIORITY.get(old.meta.doc_type, 9):
            chosen[key] = d
    ordered = sorted(chosen.values(), key=lambda d: (TYPE_PRIORITY.get(d.meta.doc_type, 9),
                                                     d.meta.known_at, d.meta.doc_id))
    print(f"unique drafts: {len(ordered)} (resolvable files: "
          f"{sum(1 for d in ordered if d.path)})")
    if limit:
        ordered = ordered[:limit]

    con = open_store(DB_PATH)
    write_tag_vocab(con)
    import fitz  # PyMuPDF
    print("loading entity resolver from master_companies ...", flush=True)
    resolver = v3.EntityResolver.from_master()
    print(f"entity resolver ready ({len(resolver.names)} names)", flush=True)
    run_id = time.strftime("pilot-%Y%m%d-%H%M%S")
    started = time.perf_counter()
    stats = {"docs": 0, "docs_no_file": 0, "docs_scanned": 0, "chunks": 0,
             "by_type": {}, "known_at_checks": []}
    written_shas: set[str] = set()
    for i, d in enumerate(ordered, 1):
        label = f"{i}/{len(ordered)} {d.meta.doc_type} {d.meta.symbol} {d.meta.known_at[:10]}"
        if i <= 3 or i % 10 == 0:
            print(f"  {label}: start", flush=True)
        if d.pages is not None:
            # Page text came from the results_notes store: no PDF read (the PDF may
            # live only in Drive).  The content hash keys the same dedupe as a file.
            sha = hashlib.sha256("\n".join(d.pages).encode("utf-8")).hexdigest()
            pages = d.pages
        elif not d.path or not d.path.is_file():
            stats["docs_no_file"] += 1
            continue
        else:
            try:
                sha = sha256_file(d.path)
                with fitz.open(d.path) as pdf:
                    pages = [page.get_text("text") or "" for page in pdf]
            except Exception as exc:  # noqa: BLE001 - one bad PDF is data, not a crash
                print(f"  {label}: parse failed {type(exc).__name__}: {exc}")
                continue
        if sha in written_shas:
            continue  # the same bytes reached the store through another registry
        written_shas.add(sha)
        d.sha256 = sha
        d.meta.doc_id = f"sha256:{sha}"
        meta = d.meta
        text = "".join(pages)
        grade = v3.grade_quality(pages, meta.doc_type)
        needs_ocr = 1 if len(text.strip()) < 500 else 0
        write_doc(con, d, sha, grade, needs_ocr, len(pages), len(text), run_id)
        chunks = []
        if not needs_ocr:
            chunks = v3.chunk_document(
                {"doc_id": meta.doc_id, "doc_type": meta.doc_type, "isin": meta.isin,
                 "symbol_at_time": meta.symbol, "fiscal_period": meta.fiscal_period,
                 "known_at": meta.known_at, "quality_grade": grade,
                 "pit_confidence": meta.pit_conf, "category": meta.category},
                pages, resolver)
        n = write_chunks(con, d, chunks)
        stats["docs"] += 1
        stats["docs_scanned"] += needs_ocr
        stats["chunks"] += n
        stats["by_type"][meta.doc_type] = stats["by_type"].get(meta.doc_type, 0) + 1
        if sum(1 for c in stats["known_at_checks"] if c["doc_type"] == meta.doc_type) < 5 \
                and len(stats["known_at_checks"]) < 20:
            stats["known_at_checks"].append({
                "doc_id": meta.doc_id, "doc_type": meta.doc_type, "source_ref": d.source_ref,
                "source": meta.source, "known_at": meta.known_at,
                "known_at_src": meta.known_at_src, "pit_conf": meta.pit_conf,
                "record_known_at": known_at_from_record(d), "raw_path": meta.raw_path})
        if i % 25 == 0:
            print(f"  {label}: {n} chunks (total {stats['chunks']})")
    con.commit()
    elapsed = time.perf_counter() - started
    con.execute("INSERT INTO build_run (run_id, started_at, ended_at, doc_type, docs_in, docs_ok, "
                "docs_failed, chunks_out, tags_out, notes) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (run_id, time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(started - elapsed)),
                 time.strftime("%Y-%m-%dT%H:%M:%S"), "all", len(ordered), stats["docs"],
                 stats["docs_no_file"], stats["chunks"], 0,
                 f"{elapsed:.1f}s; scanned={stats['docs_scanned']}"))
    con.commit()
    stats["elapsed_s"] = round(elapsed, 1)
    stats["db_bytes"] = DB_PATH.stat().st_size
    write_coverage(con, ordered)
    con.close()
    return stats


def known_at_from_record(draft: Draft) -> str | None:
    """Re-read the filing record for the build's first-20 check."""
    m = draft.meta
    try:
        if m.doc_type == "annual_report":
            con = ro(DATA / "ar_facts.db")
            r = con.execute("SELECT filed_at FROM ar_docs WHERE doc_id=?", (int(draft.source_ref),)).fetchone()
            return parse_ts(r["filed_at"]) if r else None
        if m.source_ref and m.source_ref.isdigit() and m.doc_type in ("concall", "results_notes"):
            con = ro(DATA / "equity_intelligence.db")
            r = con.execute("SELECT COALESCE(bse_dissem_ts, publication_date) AS k "
                            "FROM corporate_documents WHERE id=?", (int(m.source_ref),)).fetchone()
            return parse_ts(r["k"]) if r else None
        if m.doc_type == "deck":
            con = ro(DATA / "deck_figures.db")
            r = con.execute("SELECT known_at FROM deck_sources WHERE source_id=? AND isin=?",
                            (m.source_ref, m.isin)).fetchone()
            return parse_ts(r["known_at"]) if r else None
        if m.source == "bse_announcements.ann":
            con = ro(DATA / "bse_announcements.db")
            r = con.execute("SELECT DissemDT FROM ann WHERE NEWSID=?", (m.source_ref,)).fetchone()
            return parse_ts(r["DissemDT"]) if r else None
    except Exception:  # noqa: BLE001 - a check failure is reported, not raised
        return None
    return m.known_at


def write_coverage(con: sqlite3.Connection, ordered: list[Draft]) -> None:
    """Coverage: registry docs (FY25+) vs docs written, per ISIN x doc_type."""
    isins = pilot_isins()
    expected: dict[tuple[str, str], list[dict]] = {}
    ar = ro(DATA / "ar_facts.db")
    q = ",".join("?" * len(isins))
    for r in ar.execute(f"SELECT isin, doc_id, symbol, fiscal_year, filed_at FROM ar_docs "
                        f"WHERE isin IN ({q}) AND filed_at >= ?", isins + [CUTOFF]):
        expected.setdefault((r["isin"], "annual_report"), []).append(
            {"ref": str(r["doc_id"]), "date": (r["filed_at"] or "")[:10],
             "title": f"{r['symbol']} AR {r['fiscal_year']}"})
    ei = ro(DATA / "equity_intelligence.db")
    for r in ei.execute(f"SELECT isin, id, symbol, title, COALESCE(bse_dissem_ts, publication_date) "
                        f"AS k, doc_type FROM corporate_documents WHERE isin IN ({q}) "
                        f"AND COALESCE(bse_dissem_ts, publication_date) >= ?", isins + [CUTOFF]):
        dt = DOC_TYPE_MAP.get(r["doc_type"])
        if dt in ("concall", "results_notes"):
            expected.setdefault((r["isin"], dt), []).append(
                {"ref": str(r["id"]), "date": (r["k"] or "")[:10], "title": r["title"] or ""})
    dk = ro(DATA / "deck_figures.db")
    for r in dk.execute(f"SELECT isin, source_id, title, known_at FROM deck_sources "
                        f"WHERE isin IN ({q}) AND known_at >= ?", isins + [CUTOFF]):
        expected.setdefault((r["isin"], "deck"), []).append(
            {"ref": r["source_id"], "date": (r["known_at"] or "")[:10], "title": r["title"] or ""})
    # announcements: the fetched manifest list is the expectation
    for d in ordered:
        if d.meta.doc_type == "announcement":
            expected.setdefault((d.meta.isin, "announcement"), []).append(
                {"ref": d.meta.source_ref, "date": d.meta.known_at[:10], "title": d.meta.title[:120]})
    found = {}
    for row in con.execute("SELECT isin, doc_type, COUNT(*) n FROM doc GROUP BY isin, doc_type"):
        found[(row[0], row[1])] = row[2]
    report = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "cutoff": CUTOFF,
              "by_isin": {}, "totals": {}}
    for isin in isins:
        report["by_isin"][isin] = {}
        for dt in ("annual_report", "concall", "deck", "results_notes", "announcement"):
            exp = expected.get((isin, dt), [])
            got = found.get((isin, dt), 0)
            missing = []
            # a registry file is missing when nothing was written for that ISIN/type
            # beyond what resolved; list every expected ref not written as sha/doc id
            written_refs = {d.meta.source_ref for d in ordered
                            if d.meta.isin == isin and d.meta.doc_type == dt
                            and (d.meta.raw_path or d.pages)}
            missing = [e for e in exp if e["ref"] not in written_refs]
            report["by_isin"][isin][dt] = {"expected": len(exp), "found": got,
                                           "missing": missing[:200],
                                           "missing_count": len(missing)}
            t = report["totals"].setdefault(dt, {"expected": 0, "found": 0})
            t["expected"] += len(exp)
            t["found"] += got
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "coverage.json").write_text(json.dumps(report, indent=1), encoding="utf-8")


def refresh() -> dict:
    """In-place repair: ISIN predecessors and every deterministic tag."""
    con = sqlite3.connect(DB_PATH)
    alias = isin_alias(pilot_isins())
    for old, new in alias.items():
        con.execute("UPDATE doc SET isin=? WHERE isin=?", (new, old))
        con.execute("UPDATE chunk SET isin=? WHERE isin=?", (new, old))
        print(f"  remapped {old} -> {new}")
    before = con.execute("SELECT AVG(forward_looking) FROM chunk WHERE doc_type='concall'"
                         ).fetchone()[0] or 0.0
    # Opening remarks by an unclassified name are management, not analyst.
    fixed = 0
    for chunk_id, speaker in con.execute(
            "SELECT chunk_id, speaker FROM chunk WHERE doc_type='concall' "
            "AND section='Opening remarks' AND speaker_role='analyst'").fetchall():
        if speaker and not v3._ANALYST_NAME.search(speaker):
            con.execute("UPDATE chunk SET speaker_role='management' WHERE chunk_id=?",
                        (chunk_id,))
            fixed += 1
    # Long announcements were split by the AR splitter; their units are
    # announcement pieces, not notes to accounts.
    con.execute("UPDATE chunk SET unit_kind='announcement_cont' WHERE doc_type='announcement' "
                "AND unit_kind LIKE '%\\_cont' ESCAPE '\\'")
    con.execute("UPDATE chunk SET unit_kind='announcement' WHERE doc_type='announcement' "
                "AND unit_kind NOT LIKE '%\\_cont' ESCAPE '\\'")
    count = 0
    rows = con.execute("SELECT chunk_id, body, doc_type, section, speaker_role FROM chunk"
                       ).fetchall()
    for chunk_id, body, doc_type, section, role in rows:
        tags = v3.deterministic_tags(body or "", doc_type or "", section or "", role or "")
        flag = int("forward_looking" in tags)
        con.execute("UPDATE chunk SET forward_looking=?, content_tags=? WHERE chunk_id=?",
                    (flag, " ".join(tags), chunk_id))
        con.execute("DELETE FROM chunk_tag WHERE chunk_id=?", (chunk_id,))
        con.executemany("INSERT OR IGNORE INTO chunk_tag (tag, chunk_id, tagger, confidence) "
                        "VALUES (?, ?, 'deterministic', 1.0)", [(t, chunk_id) for t in tags])
        count += flag
    con.commit()
    after = con.execute("SELECT AVG(forward_looking) FROM chunk WHERE doc_type='concall'"
                        ).fetchone()[0] or 0.0
    con.close()
    result = {"alias": alias, "forward_looking_chunks": count, "retagged_chunks": len(rows),
              "opening_roles_fixed": fixed,
              "concall_share_before": round(before, 3), "concall_share_after": round(after, 3)}
    print(json.dumps(result, indent=2))
    return result


class _NoIndex:
    """Loader stub for the coverage re-run: refs only, no file resolution."""
    by_name: dict = {}

    def by_sha(self, sha):
        return None

    def by_key(self, symbol, text):
        return None


def coverage_only() -> dict:
    isins = pilot_isins()
    drafts = (load_annual_reports(isins, _NoIndex()) + load_concalls(isins, _NoIndex())
              + load_decks(isins, _NoIndex()) + load_results_notes(isins, _NoIndex())
              + load_bse_announcements(isins, _NoIndex()) + load_nse_attachments(isins, _NoIndex()))
    alias = isin_alias(isins)
    for draft in drafts:
        draft.meta.isin = alias.get(draft.meta.isin, draft.meta.isin)
    con = sqlite3.connect(DB_PATH)
    write_coverage(con, drafts)
    con.close()
    print(f"coverage rewritten from {len(drafts)} registry rows -> coverage.json")
    return {}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int)
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--coverage", action="store_true")
    args = ap.parse_args(argv[1:])
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if args.refresh:
        refresh()
        return 0
    if args.coverage:
        coverage_only()
        return 0
    stats = build(args.limit)
    print(json.dumps({k: v for k, v in stats.items() if k != "known_at_checks"}, indent=2))
    checks = stats.get("known_at_checks") or []
    bad = [c for c in checks if c["known_at"] != c["record_known_at"]]
    lines = ["# known_at check — first %d rows vs the filing record" % len(checks), "",
             "| doc_id | type | source ref | chunk known_at | record known_at | match |",
             "|---|---|---|---|---|---|"]
    for c in checks:
        ok = "OK" if c["known_at"] == c["record_known_at"] else "MISMATCH"
        lines.append(f"| {c['doc_id'][:40]} | {c['doc_type']} | {c['source_ref']} | "
                     f"{c['known_at']} | {c['record_known_at']} | {ok} |")
    lines += ["", f"mismatches: {len(bad)} / {len(checks)}"]
    (OUT_DIR / "known_at_check.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"known_at check: {len(bad)} mismatch / {len(checks)} rows -> known_at_check.md")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
