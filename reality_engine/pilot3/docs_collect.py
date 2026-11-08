"""T-049 C: every held document of the 3 pilot companies, dated, as page text (no model, no OCR).

``python -m reality_engine.pilot3.docs_collect --out D:\\RealityEngine\\pilot3\\pages.db
[--symbols KEC,BAJFINANCE,HINDALCO]``

1. Finds every held PDF of the companies: folders named by NSE symbol or BSE code anywhere under the
   raw store (``pilot60_history/<SYM>``, ``annual_report/<SYM>``, ``decks/bse/<code>``,
   ``nse_announcements/*/attachments/<SYM>``, ...), the same under the old ``reality_engine/data``
   (``pdfs/<SYM>``, ``decks/bse/<code>``), and the sha256-named folders (``decks_full``,
   ``concall_pdfs``, ``kec_transcripts`` ...) by matching the file hash with the hashes the
   stores record for the company's ISINs (every ISIN in ``symbol_isin_history``).  Deduped by sha256.
2. Dates each file only from a filing record: the manifest of the company site, ``bse_announcements.ann``
   (NEWSID / attachment name), ``corporate_documents`` (sha, bse_newsid, id), ``deck_sources``,
   ``ar_docs``.  ``known_at`` is the raw dissemination timestamp (the 15:30 IST shift is the core
   builder's job); a file no record dates keeps ``known_at`` NULL and is reported.
3. Writes ``pages.db`` (``doc``, ``doc_page`` + FTS5 ``doc_page_fts``): text from the PDF text layer, a
   page under 50 characters is ``method='needs_ocr'`` with empty text.
4. Writes ``DOC_COVERAGE.xlsx``: counts and newest dates, the FY25-FY27 expected-but-missing
   documents, and the BSE announcement attachments whose headline is held but body is not (the fetch
   worklist).

Idempotent: a document whose sha256 is already in ``pages.db`` is not re-read.  Read-only on every store.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from reality_engine import raw_store
from reality_engine.db.readonly import connect_ro
from reality_engine.gap_loop.company import Company
from reality_engine.gap_loop.prepare import DOC_TYPES, MIN_PAGE_CHARS, _clean_page, _date_of, _title
from reality_engine.pilot3 import profile

RAW_ROOT = Path(os.environ.get("REALITY_RAW_ROOT", r"D:\RealityEngine\raw"))
LEGACY_PDFS = Path(os.environ.get("REALITY_PDFS_LEGACY_DIR", r"D:\RealityEngine\pdfs"))
DEFAULT_OUT = Path(r"D:\RealityEngine\pilot3\pages.db")
WINDOW_START = "2024-04-01"          # universe time window (company data FY2024-25+)
AS_OF = "2026-10-19"
GUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
SHA = re.compile(r"[0-9a-f]{64}")
SHA_DIRS = {"decks_full": "deck", "concall_pdfs": "transcript", "results_notes_refetch": "results",
            "results_pdfs": "results", "deck_page_text": "deck", "kec_transcripts": "transcript",
            "annual_report": "annual_report", "deck": "deck"}
CORP_TYPES = {"ANNUAL_REPORT": "annual_report", "CONCALL_TRANSCRIPT": "transcript",
              "INVESTOR_PRESENTATION": "deck", "FINANCIAL_RESULT": "results",
              "ANNOUNCEMENT": "announcement", "OTHER_FILING": "announcement"}
SUBCAT_TYPES = {"investor presentation": "deck", "earnings call transcript": "transcript",
                "financial results": "results", "press release / media release": "press_release",
                "annual report": "annual_report", "audio recording of earnings call": "audio_link"}
# A profile manifest's bucket -> doc_type (T-056); a bucket with no document behind it is not a document.
BUCKET_TYPES = {"annual_report": "annual_report", "investor_presentation": "deck", "concall_transcript": "transcript",
                "quarterly_results": "results", "results_press_release": "press_release",
                "material_filing": "announcement"}
# KEC files an order win as a Company Update / Press Release and only now and then under "Award of Order", so
# the sub-category alone loses most of a year's order filings (T-049, 4 Nov 2026: 5 of FY26's 18 were typed
# press_release with the generic title and no order question could find them).  The headline names the win.
ORDER_HEADLINE = re.compile(r"\bnew orders?\b.{0,40}\bsecured\b", re.I)
GENERIC_SUBCATS = {"press release / media release", "general", "clarification"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS doc(
    doc_key TEXT PRIMARY KEY, symbol TEXT NOT NULL, isin TEXT, doc_type TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '', filing_date TEXT, known_at TEXT, source_path TEXT NOT NULL,
    sha256 TEXT NOT NULL, pages INTEGER NOT NULL DEFAULT 0, source_record TEXT NOT NULL DEFAULT '',
    known_at_source TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS doc_page(
    doc_key TEXT NOT NULL, page INTEGER NOT NULL, text TEXT NOT NULL, method TEXT NOT NULL,
    known_at TEXT, PRIMARY KEY(doc_key, page));
CREATE INDEX IF NOT EXISTS doc_sha ON doc(sha256);
CREATE INDEX IF NOT EXISTS doc_symbol_type ON doc(symbol, doc_type, filing_date);
CREATE INDEX IF NOT EXISTS doc_page_known ON doc_page(known_at);
CREATE VIRTUAL TABLE IF NOT EXISTS doc_page_fts USING fts5(text);
CREATE TRIGGER IF NOT EXISTS doc_page_ai AFTER INSERT ON doc_page BEGIN
    INSERT INTO doc_page_fts(rowid, text) VALUES (new.rowid, new.text);
END;
CREATE TRIGGER IF NOT EXISTS doc_page_ad AFTER DELETE ON doc_page BEGIN
    DELETE FROM doc_page_fts WHERE rowid = old.rowid;
END;
CREATE TRIGGER IF NOT EXISTS doc_page_au AFTER UPDATE ON doc_page BEGIN
    DELETE FROM doc_page_fts WHERE rowid = old.rowid;
    INSERT INTO doc_page_fts(rowid, text) VALUES (new.rowid, new.text);
END;
"""


@dataclass
class Config:
    data_root: Path
    raw_roots: tuple[Path, ...] = (RAW_ROOT,)
    extra_roots: tuple[Path, ...] = (LEGACY_PDFS,)   # the old D: PDF pile, <SYMBOL>/<TYPE>/file.pdf
    companies: dict = field(default_factory=lambda: profile.companies())
    snapshot: Path | None = None


def default_data_root() -> Path:
    """``REALITY_DATA_ROOT``, else this checkout's ``reality_engine/data``, else (in a git worktree,
    whose data folder is nearly empty) the main checkout's."""
    env = os.environ.get("REALITY_DATA_ROOT")
    if env:
        return Path(env)
    here = Path(__file__).resolve().parents[1] / "data"
    if (here / "equity_intelligence.db").is_file():
        return here
    dotgit = here.parents[1] / ".git"
    if dotgit.is_file():  # "gitdir: <main>/.git/worktrees/<name>"
        match = re.search(r"gitdir:\s*(.+?)[/\\]\.git[/\\]worktrees", dotgit.read_text(encoding="utf-8"))
        if match:
            return Path(match.group(1)) / "reality_engine" / "data"
    return here


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _ro(path: Path):
    return connect_ro(path, timeout_s=180) if path.is_file() else None


def _table_exists(con, table: str) -> bool:
    return bool(con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone())


# ---------------------------------------------------------------------------- identities
def isin_history(cfg: Config, symbol: str) -> list[tuple[str, str, str]]:
    """``(isin, first_date, last_date)`` for the symbol from ``symbol_isin_history`` (truth snapshot,
    else the store's copy), merged with the ISINs configured for the company."""
    rows: list[tuple[str, str, str]] = []
    snaps = [cfg.snapshot] if cfg.snapshot else sorted((cfg.data_root / "snapshots").glob("truth_*.duckdb"))
    if snaps:
        try:
            import duckdb
            con = duckdb.connect(str(snaps[-1]), read_only=True)
            try:
                rows = [(r[0], str(r[1]), str(r[2])) for r in con.execute(
                    "SELECT isin, first_date, last_date FROM symbol_isin_history WHERE symbol=? "
                    "ORDER BY first_date", (symbol,)).fetchall()]
            finally:
                con.close()
        except Exception:
            rows = []
    if not rows:
        con = _ro(cfg.data_root / "equity_intelligence.db")
        if con is not None:
            try:
                if _table_exists(con, "symbol_isin_history"):
                    rows = [(r[0], str(r[1]), str(r[2])) for r in con.execute(
                        "SELECT isin, first_date, last_date FROM symbol_isin_history WHERE symbol=? "
                        "ORDER BY first_date", (symbol,))]
            finally:
                con.close()
    company = cfg.companies.get(symbol)
    for isin in (company.isins if company else ()):
        if isin not in {r[0] for r in rows}:
            rows.append((isin, "", ""))
    return rows


def isin_at(history: list[tuple[str, str, str]], date: str | None) -> str | None:
    if not history:
        return None
    if date:
        for isin, first, last in history:
            if first and last and first <= date <= last:
                return isin
    return history[-1][0]


# ---------------------------------------------------------------------------- filing records
class Records:
    """Everything that can date a held file, for one company, from the read-only stores."""

    def __init__(self, cfg: Config, company: Company, isins: list[str],
                 store: raw_store.RawStore | None = None):
        self.company = company
        self.isins = list(isins)
        self.store = store or raw_store.default_store()   # a raw file may be held only on Drive (T-102)
        self.ann_by_newsid: dict[str, dict] = {}
        self.ann_by_attachment: dict[str, dict] = {}
        self.ann_rows: list[dict] = []
        self.corp_by_sha: dict[str, dict] = {}
        self.corp_by_newsid: dict[str, dict] = {}
        self.corp_by_id: dict[str, dict] = {}
        self.by_sha: dict[str, dict] = {}       # deck_sources / ar_docs / manifests
        self.sha_names: set[str] = set()         # every sha256 a store says belongs to the company
        self.nse_by_attachment: dict[str, dict] = {}
        self._load_ann(cfg, company)
        self._load_corp(cfg, isins)
        self._load_decks_ar(cfg, isins)

    def _load_ann(self, cfg: Config, company: Company) -> None:
        con = _ro(cfg.data_root / "bse_announcements.db")
        if con is None:
            return
        try:
            for (newsid, att, headline, cat, sub, dissem, submitted, newsdt, size) in con.execute(
                "SELECT NEWSID, ATTACHMENTNAME, HEADLINE, CATEGORYNAME, SUBCATNAME, DissemDT, "
                "News_submission_dt, NEWS_DT, Fld_Attachsize FROM ann WHERE symbol=? OR SCRIP_CD=?",
                (company.symbol, company.bse_code)):
                row = {"NEWSID": str(newsid), "attachment": att or "", "headline": _title(headline),
                       "category": cat or "", "subcat": sub or "", "title": _ann_title(sub, cat, headline),
                       "known_at": dissem or submitted or newsdt,
                       "filing_date": _date_of(dissem or submitted or newsdt), "size": size,
                       "source": "bse_announcements.ann"}
                self.ann_rows.append(row)
                self.ann_by_newsid[row["NEWSID"].lower()] = row
                if att:
                    self.ann_by_attachment[str(att).lower()] = row
        finally:
            con.close()

    def _load_corp(self, cfg: Config, isins: list[str]) -> None:
        con = _ro(cfg.data_root / "equity_intelligence.db")
        if con is None or not _table_exists(con, "corporate_documents"):
            return
        marks = ",".join("?" * len(isins))
        try:
            for (doc_id, isin, doc_type, title, pub, call, dissem, newsid, sha, symbol, subcat) in con.execute(
                "SELECT id, isin, doc_type, title, publication_date, call_date, bse_dissem_ts, bse_newsid, "
                f"sha256_hash, symbol, bse_subcat FROM corporate_documents WHERE isin IN ({marks})", isins):
                when = dissem or pub or call  # doc_date is the crawl date: never used
                row = {"id": doc_id, "isin": isin, "doc_type": CORP_TYPES.get(str(doc_type).upper(), ""),
                       "title": _title(title, subcat), "known_at": when, "filing_date": _date_of(when),
                       "source": "equity_intelligence.corporate_documents", "NEWSID": newsid or ""}
                self.corp_by_id[str(doc_id)] = row
                if newsid:
                    self.corp_by_newsid[str(newsid).lower()] = row
                if sha:
                    self.corp_by_sha[str(sha).lower()] = row
                    self.sha_names.add(str(sha).lower())
        finally:
            con.close()

    def _load_decks_ar(self, cfg: Config, isins: list[str]) -> None:
        marks = ",".join("?" * len(isins))
        con = _ro(cfg.data_root / "deck_figures.db")
        if con is not None:
            try:
                for sha, known, title, source_id in con.execute(
                    f"SELECT sha256, known_at, title, source_id FROM deck_sources WHERE isin IN ({marks})", isins):
                    if sha:
                        self.by_sha.setdefault(sha.lower(), {
                            "doc_type": "deck", "title": _title(title), "known_at": known,
                            "filing_date": _date_of(known), "source": "deck_figures.deck_sources",
                            "NEWSID": source_id or ""})
                        self.sha_names.add(sha.lower())
                for (sha,) in con.execute(f"SELECT DISTINCT sha256 FROM pages WHERE isin IN ({marks})", isins):
                    if sha:
                        self.sha_names.add(sha.lower())
            finally:
                con.close()
        con = _ro(cfg.data_root / "ar_facts.db")
        if con is not None:
            try:
                for sha, filed, year in con.execute(
                    f"SELECT sha256, filed_at, fiscal_year FROM ar_docs WHERE isin IN ({marks})", isins):
                    if sha:
                        self.by_sha.setdefault(sha.lower(), {
                            "doc_type": "annual_report", "title": f"Annual report {year or ''}".strip(),
                            "known_at": filed, "filing_date": _date_of(filed), "source": "ar_facts.ar_docs",
                            "NEWSID": ""})
                        self.sha_names.add(sha.lower())
            finally:
                con.close()
        con = _ro(cfg.data_root / "equity_intelligence.db")
        if con is not None:
            try:
                if _table_exists(con, "raw_documents"):
                    for (sha,) in con.execute(
                        f"SELECT sha256_hash FROM raw_documents WHERE isin IN ({marks})", isins):
                        if sha:
                            self.sha_names.add(sha.lower())
            finally:
                con.close()

    def add_manifest(self, folder: Path) -> None:
        """The company site's own transcript list (``_manifest.json`` / ``_known_at.json``)."""
        for name in ("_manifest.json", "_known_at.json"):
            file = folder / name
            if not self.store.exists(file):
                continue
            try:
                with self.store.local(file) as source:
                    rows = json.loads(Path(source).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            for row in rows if isinstance(rows, list) else []:
                sha = str((row or {}).get("sha256") or "").lower()
                if not sha:
                    continue
                got = self.by_sha.setdefault(sha, {"doc_type": "transcript", "NEWSID": "",
                                                   "source": f"{folder.name}/{name}"})
                got.update(title=_title(row.get("title")), filing_date=_date_of(row.get("site_publish_date")),
                           known_at=row.get("known_at") or row.get("site_publish_date"))
                self.sha_names.add(sha)

    def add_pilot_manifest(self, csv_path: Path, isins: list[str]) -> None:
        """``pilot60_history/manifest.csv``: the BSE announcement record each history file was fetched
        for (newsid, dissemination time, attachment url).  Fills only what ``ann`` does not know."""
        import csv
        try:
            with self.store.local(csv_path) as source:
                with Path(source).open(encoding="utf-8", newline="") as fh:
                    for row in csv.DictReader(fh):
                        if row.get("isin") not in isins or not row.get("newsid"):
                            continue
                        rec = {"NEWSID": row["newsid"], "attachment": row["url"].rsplit("/", 1)[-1] if row.get("url") else "",
                               "headline": _title(row.get("headline")), "category": row.get("category") or "",
                               "subcat": row.get("subcat") or "", "title": _ann_title(row.get("subcat"), row.get("category"), row.get("headline")),
                               "known_at": row.get("dissem_ts"), "filing_date": _date_of(row.get("dissem_ts")),
                               "source": "pilot60_history/manifest.csv"}
                        self.ann_by_newsid.setdefault(rec["NEWSID"].lower(), rec)
                        if rec["attachment"]:
                            self.ann_by_attachment.setdefault(rec["attachment"].lower(), rec)
                        if row.get("sha256"):
                            self.by_sha.setdefault(row["sha256"].lower(), rec)
        except FileNotFoundError:
            return

    def add_nse(self, jsonl: Path) -> None:
        try:
            with self.store.local(jsonl) as source:
                text = Path(source).read_text(encoding="utf-8", errors="replace")
        except FileNotFoundError:
            return
        for line in text.splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            url = str(row.get("attachment_url") or "")
            if url:
                self.nse_by_attachment[url.rsplit("/", 1)[-1].lower()] = {
                    "title": _title(row.get("subject"), row.get("desc")), "known_at": row.get("known_at"),
                    "filing_date": _date_of(row.get("known_at")), "source": f"nse:{jsonl.parent.name}",
                    "NEWSID": str(row.get("seq_id") or ""), "doc_type": "announcement"}

    def sha_type(self, sha: str) -> str:
        """The specific type (annual_report, deck, transcript, results) a store records for this hash."""
        for rec in (self.corp_by_sha.get(sha), self.by_sha.get(sha)):
            if rec and rec.get("doc_type") not in (None, "", "announcement", "other"):
                return rec["doc_type"]
        return ""

    def lookup(self, path: Path, sha: str) -> dict | None:
        """The filing record dating this file: the ids in its name first (one PDF can be filed under
        several announcements, so the hash alone would give every copy the same record), then the hash."""
        name, stem = path.name.lower(), path.stem.lower()
        if name in self.nse_by_attachment:
            return self.nse_by_attachment[name]
        guids = GUID.findall(stem)
        for key in [stem, *guids]:
            if key in self.ann_by_newsid:
                return self.ann_by_newsid[key]
            if key in self.corp_by_newsid:
                return self.corp_by_newsid[key]
        for key in [name, *(g + ".pdf" for g in guids)]:
            if key in self.ann_by_attachment:
                return self.ann_by_attachment[key]
        if stem.isdigit() and stem in self.corp_by_id:
            return self.corp_by_id[stem]
        if sha in self.by_sha and self.by_sha[sha].get("known_at"):
            return self.by_sha[sha]
        if sha in self.corp_by_sha:
            return self.corp_by_sha[sha]
        return self.by_sha.get(sha)


# ---------------------------------------------------------------------------- discovery
def make_store(cfg: Config) -> raw_store.RawStore:
    """The raw store for this config's roots (the T-102 manifest names them ``raw`` and ``pdfs``)."""
    roots = {Path(p).name: Path(p) for p in (*cfg.raw_roots, *cfg.extra_roots)}
    return raw_store.RawStore(roots=roots)


def _walk_pdfs(folder: Path, store: raw_store.RawStore):
    """Every PDF under ``folder``: the local files plus the files only the manifest holds."""
    for pdf in store.walk(folder):
        if pdf.name.lower().endswith(".pdf"):
            yield pdf


def _named_dirs(base: Path, names: set[str], store: raw_store.RawStore, depth: int = 3):
    """Directories called one of ``names`` (case-insensitive) at most ``depth`` levels below ``base``."""
    if depth < 0:
        return
    for folder in store.subdirs(base):
        if folder.name.lower() in names:
            yield folder
        else:
            yield from _named_dirs(folder, names, store, depth - 1)


def _dir_type(path: Path, root: Path) -> str:
    for part in reversed(path.relative_to(root).parts[:-1]):
        part = part.lower()
        if part in DOC_TYPES:
            return DOC_TYPES[part]
        if part in SHA_DIRS:
            return SHA_DIRS[part]
    return "other"


def _company_manifest(root: Path, symbol: str, store: raw_store.RawStore) -> Path | None:
    """The company site's own manifest folder (``<symbol>_transcripts/_manifest.json``) when one is held."""
    wanted = symbol.lower()
    for folder in store.subdirs(root):
        name = folder.name.lower()
        # ``abb_transcripts`` is ABB's, ``abbott_transcripts`` is not: a bare prefix would read another company's list.
        if (name == wanted or name.startswith(wanted + "_")) and any(
                store.exists(folder / item) for item in ("_manifest.json", "_known_at.json")):
            return folder
    return None


def discover(cfg: Config, company: Company, records: Records,
             store: raw_store.RawStore) -> list[tuple[Path, Path, str]]:
    """``(file, root it lives under, directory-derived doc type)`` for every candidate PDF."""
    found: dict[str, tuple[Path, Path, str]] = {}
    names = {company.symbol.lower(), str(company.bse_code)}
    for root in [*cfg.raw_roots, *cfg.extra_roots, cfg.data_root]:
        bases = [root / "pdfs", root / "decks"] if root == cfg.data_root else [root]
        for base in bases:
            for folder in _named_dirs(base, names, store):
                for pdf in _walk_pdfs(folder, store):
                    found.setdefault(str(pdf), (pdf, root, _dir_type(pdf, root)))
    for root in cfg.raw_roots:
        site = _company_manifest(root, company.symbol, store)
        if site is not None:
            records.add_manifest(site)      # a company site's own transcript list, when one is held
        for dirname, kind in SHA_DIRS.items():
            folder = root / dirname
            for pdf in _walk_pdfs(folder, store):
                stem = pdf.stem.lower()
                if SHA.fullmatch(stem) and (stem in records.sha_names or stem in records.by_sha):
                    found.setdefault(str(pdf), (pdf, root, kind))
        manifest = root / "pilot60_history" / "manifest.csv"
        if store.exists(manifest):
            records.add_pilot_manifest(manifest, [i for i in company.isins] + records.isins)
        for jsonl in store.glob(root / "nse_announcements", f"*/{company.symbol}.jsonl"):
            records.add_nse(jsonl)
    return sorted(found.values(), key=lambda item: str(item[0]))


def _ann_title(subcat: object, category: object, headline: object) -> str:
    """The doc title: the sub-category, unless it is the generic one -- then the headline, which is what an
    order press release actually says ("new orders of Rs. 1,236 crores secured")."""
    sub = str(subcat or "")
    if sub.strip().lower() in GENERIC_SUBCATS:
        return _title(headline, sub, category)
    return _title(sub, category, headline)


def _refine_type(dir_type: str, record: dict | None, sha_type: str = "") -> str:
    """What a store says about this exact file first (an annual report is also filed under the AGM
    sub-category, a deck under the press-release one), then an order win in the headline, the BSE
    sub-category, the record's type and finally the folder the file was fetched into."""
    if sha_type:
        return sha_type
    if record is None:
        return dir_type
    if ORDER_HEADLINE.search(str(record.get("headline") or "")):
        return "announcement"
    sub = SUBCAT_TYPES.get(str(record.get("subcat") or "").lower())
    if sub:
        return sub
    kind = record.get("doc_type") or ""
    if kind and kind != "announcement":
        return kind
    return dir_type if dir_type != "other" else (kind or dir_type)


# ---------------------------------------------------------------------------- build pages.db
def connect_out(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=60)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    return conn


def _doc_key(path: Path, root: Path, cfg: Config) -> str:
    rel = path.relative_to(root).as_posix()
    return rel if root in cfg.raw_roots else f"{root.name}/{rel}"


def _extract(conn: sqlite3.Connection, doc_key: str, path: Path, known_at: str | None) -> tuple[int, dict]:
    import fitz
    stats = {"script_text": 0, "needs_ocr": 0, "error": ""}
    pages = 0
    try:
        with fitz.open(str(path)) as pdf:
            if pdf.needs_pass and not pdf.authenticate(""):
                raise ValueError("password protected")
            pages = pdf.page_count
            rows = []
            for number in range(1, pages + 1):
                text = _clean_page(pdf[number - 1].get_text("text"))
                method = "script_text" if len(text) >= MIN_PAGE_CHARS else "needs_ocr"
                stats[method] += 1
                rows.append((doc_key, number, text if method == "script_text" else "", method, known_at))
            conn.executemany("INSERT OR REPLACE INTO doc_page VALUES (?,?,?,?,?)", rows)
    except Exception as exc:  # corrupt or encrypted: the doc row records it
        stats["error"] = f"{type(exc).__name__}: {exc}"[:200]
    return pages, stats


def retype_agm(conn: sqlite3.Connection) -> int:
    """An annual report is filed with the AGM notice under the AGM sub-category; no store marks every
    one.  An ``announcement`` filed under AGM with 100 pages or more is an ``annual_report``."""
    cur = conn.execute("UPDATE doc SET doc_type='annual_report' WHERE doc_type='announcement' AND pages>=100 "
                       "AND json_extract(source_record,'$.subcat')='AGM'")
    conn.commit()
    return cur.rowcount


def collect(cfg: Config, symbols: tuple[str, ...], out: Path, log=print,
            set_aside: set[str] | None = None) -> dict:
    """Run steps 1-3 for the symbols; returns counts per symbol.

    ``set_aside`` is the identity scan's set-aside sha256 values (``doc_identity.doc_key``): such a file is counted
    and left out of pages.db, never deleted from the store."""
    conn = connect_out(out)
    counts: dict[str, dict] = {}
    held_newsids: dict[str, set] = {}
    started = time.time()
    store = make_store(cfg)
    for symbol in symbols:
        company = cfg.companies[symbol]
        history = isin_history(cfg, symbol)
        isins = [h[0] for h in history] or list(company.isins)
        records = Records(cfg, company, isins, store)
        candidates = discover(cfg, company, records, store)
        stat = counts[symbol] = {"files": len(candidates), "docs": 0, "dupes": 0, "pages": 0,
                                 "needs_ocr": 0, "undated": 0, "errors": 0, "skipped": 0, "set_aside": 0}
        held = held_newsids.setdefault(symbol, set())
        groups: dict[str, list] = {}
        # One download and one delete per company (T-102): the whole candidate list is fetched once,
        # then hashed and read from the temp copy.
        with store.prefetch([pdf for pdf, _root, _kind in candidates]):
            for pdf, root, dir_type in candidates:
                with store.local(pdf) as source:
                    sha = _sha256(Path(source))
                groups.setdefault(sha, []).append((pdf, root, dir_type, records.lookup(pdf, sha)))
            for sha, members in groups.items():
                if set_aside and sha in set_aside:
                    stat["set_aside"] += 1
                    continue
                # One document, possibly filed under several announcements (a results PDF is attached to the
                # board-meeting outcome and again to the results filing): the earliest dissemination is when
                # it became public, so that record dates the doc; every filing is kept in source_record.
                members.sort(key=lambda m: (not (m[3] or {}).get("known_at"), str((m[3] or {}).get("known_at") or ""), str(m[0])))
                pdf, root, dir_type, record = members[0]
                stat["dupes"] += len(members) - 1
                filings, seen_ids = [], set()
                for path, _root, _kind, rec in members:
                    if rec:
                        for ident in (rec.get("NEWSID"), rec.get("attachment")):
                            if ident:
                                held.add(str(ident).lower())
                        ident = str(rec.get("NEWSID") or rec.get("attachment") or rec.get("id") or path)
                        if ident not in seen_ids:
                            seen_ids.add(ident)
                            filings.append({"NEWSID": rec.get("NEWSID") or "", "attachment": rec.get("attachment") or "",
                                            "known_at": rec.get("known_at"), "subcat": rec.get("subcat") or "",
                                            "title": rec.get("title") or ""})
                old_key = conn.execute("SELECT doc_key FROM doc WHERE sha256=? AND symbol=? ORDER BY doc_key LIMIT 1",
                                       (sha, symbol)).fetchone()
                key = old_key[0] if old_key else _doc_key(pdf, root, cfg)
                known_at = (record or {}).get("known_at")
                filing_date = (record or {}).get("filing_date")
                doc_type = _refine_type(dir_type, record, records.sha_type(sha))
                isin = (record or {}).get("isin") or isin_at(history, filing_date)
                old = conn.execute("SELECT pages FROM doc WHERE doc_key=? AND sha256=?", (key, sha)).fetchone()
                if old is not None and conn.execute("SELECT COUNT(*) FROM doc_page WHERE doc_key=?", (key,)
                                                    ).fetchone()[0] >= (old[0] or 0):
                    pages = old[0]
                    page_stats = {"script_text": 0, "error": "", "needs_ocr": conn.execute(
                        "SELECT COUNT(*) FROM doc_page WHERE doc_key=? AND method='needs_ocr'", (key,)).fetchone()[0]}
                    conn.execute("UPDATE doc_page SET known_at=? WHERE doc_key=?", (known_at, key))
                    stat["skipped"] += 1
                else:
                    conn.execute("DELETE FROM doc_page WHERE doc_key=?", (key,))
                    with store.local(pdf) as source:
                        pages, page_stats = _extract(conn, key, Path(source), known_at)
                meta = {k: v for k, v in (record or {}).items() if k in
                        ("NEWSID", "attachment", "id", "category", "subcat", "headline", "size")}
                meta["dir_type"] = dir_type
                meta["filings"] = filings
                meta["paths"] = [str(m[0]) for m in members]
                if page_stats["error"]:
                    meta["error"] = page_stats["error"]
                    stat["errors"] += 1
                conn.execute("INSERT OR REPLACE INTO doc VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (
                    key, symbol, isin, doc_type, (record or {}).get("title") or pdf.stem, filing_date, known_at,
                    str(pdf), sha, pages, json.dumps(meta), (record or {}).get("source") or ""))
                conn.commit()
                stat["docs"] += 1
                stat["pages"] += pages
                stat["needs_ocr"] += page_stats["needs_ocr"]
                stat["undated"] += 0 if known_at else 1
        log(f"{symbol}: {stat} ({round(time.time() - started)}s)")
    log(f"retyped {retype_agm(conn)} AGM filings of 100+ pages as annual_report")
    conn.close()
    return counts


# ---------------------------------------------------------------------------- profile manifest (T-056)
def _manifest_rows(path: Path) -> list[dict]:
    """The ``status='ok'`` rows of a raw ``manifest.csv`` (a status that is not ok has no file behind it)."""
    import csv

    with path.open(encoding="utf-8", errors="replace", newline="") as fh:
        return [row for row in csv.DictReader(fh) if str(row.get("status") or "").strip().lower() == "ok"]


def _rel_key(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _manifest_path(row: dict, symbol: str, prof: profile.Profile) -> Path:
    """The local path a manifest row's file is stored at (the store may hold the copy on Drive)."""
    ident = str(row.get("newsid") or row.get("local_path") or row.get("url") or "").strip()
    local = str(row.get("local_path") or "").strip()
    path = Path(local) if local else prof.raw_root / symbol / str(row.get("bucket")) / f"{ident}.pdf"
    if local and not path.is_absolute():
        path = prof.raw_root / path
    return path


def collect_manifest(prof: profile.Profile, symbols: tuple[str, ...], out: Path, log=print,
                     store: raw_store.RawStore | None = None) -> dict:
    """pages.db from a profile's raw manifest only: the ``status='ok'`` rows of the requested companies.

    No store lookup and no directory walk: the manifest names each filing, its local file, its dissemination
    time and its bucket, so ``known_at`` is the row's ``dissem_ts`` and a row without one is counted, not
    written (a document that cannot be dated cannot prove it was public).  A bucket with no document behind it
    (``concall_audio_link``, ``skip``) and a row whose file is neither local nor on Drive do not become rows
    either.  A company is one ``prefetch``: every file it needs is downloaded once and deleted after."""
    conn = connect_out(out)
    counts: dict[str, dict] = {}
    started = time.time()
    rows = _manifest_rows(prof.manifest)
    # The profile's raw root plus the store's default roots, so a manifest row may name a file under the old
    # D: PDF pile (``pdfs``) that only Drive holds (T-126: FY25-FY27 rows added from corporate_documents).
    store = store or raw_store.RawStore(roots={**raw_store._default_roots(), prof.raw_root.name.lower(): prof.raw_root})
    for symbol in symbols:
        stat = counts[symbol] = {"rows": 0, "docs": 0, "pages": 0, "needs_ocr": 0, "undated": 0, "missing": 0,
                                 "errors": 0, "not_documents": 0, "dupes": 0}
        seen: set[str] = set()
        mine = [r for r in rows if str(r.get("symbol_at_time") or "").strip().upper() == symbol]
        with store.prefetch(_manifest_path(r, symbol, prof) for r in mine):
            for row in sorted(mine, key=lambda r: str(r.get("dissem_ts") or "")):
                stat["rows"] += 1
                doc_type = BUCKET_TYPES.get(str(row.get("bucket") or "").strip().lower())
                if doc_type is None:
                    stat["not_documents"] += 1
                    continue
                ident = str(row.get("newsid") or row.get("local_path") or row.get("url") or "").strip()
                if ident and ident in seen:
                    stat["dupes"] += 1
                    continue
                known_at = str(row.get("dissem_ts") or "").strip()
                if not known_at:
                    stat["undated"] += 1
                    continue
                path = _manifest_path(row, symbol, prof)
                if not store.exists(path):
                    stat["missing"] += 1
                    continue
                if ident:
                    seen.add(ident)
                key = _rel_key(path, prof.raw_root)
                with store.local(path) as source:
                    pages, page_stats = _extract(conn, key, Path(source), known_at)
                meta = {k: row.get(k) for k in ("newsid", "bucket", "category", "subcat", "headline", "url", "sha256")}
                conn.execute("INSERT OR REPLACE INTO doc VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (
                    key, symbol, row.get("isin"), doc_type,
                    _title(row.get("headline"), row.get("subcat"), row.get("category")) or path.stem,
                    _date_of(known_at), known_at, str(path), str(row.get("sha256") or ""), pages, json.dumps(meta),
                    "manifest.csv"))
                conn.commit()
                stat["docs"] += 1
                stat["pages"] += pages
                stat["needs_ocr"] += page_stats["needs_ocr"]
                if page_stats["error"]:
                    stat["errors"] += 1
        log(f"{symbol}: {stat} ({round(time.time() - started)}s)")
    conn.close()
    return counts


# ---------------------------------------------------------------------------- coverage workbook
def quarter_windows() -> list[tuple[str, str, str]]:
    """``(label, filing window start, end)`` for Q1 FY25 .. Q1 FY27; the last is cut at AS_OF."""
    out = []
    for fy in (25, 26, 27):
        y = 2000 + fy - 1
        spans = [(f"Q1 FY{fy}", f"{y}-07-01", f"{y}-09-30"), (f"Q2 FY{fy}", f"{y}-10-01", f"{y}-12-31"),
                 (f"Q3 FY{fy}", f"{y + 1}-01-01", f"{y + 1}-03-31"), (f"Q4 FY{fy}", f"{y + 1}-04-01", f"{y + 1}-06-30")]
        out += [s for s in spans if s[1] <= AS_OF]
    return [(a, b, min(c, AS_OF)) for a, b, c in out]


def _in(date: str | None, start: str, end: str) -> bool:
    return bool(date) and start <= date <= end


def coverage(cfg: Config, symbols: tuple[str, ...], out: Path, workbook: Path) -> dict:
    """Write the coverage workbook from ``pages.db``; returns the per-company summary."""
    from openpyxl import Workbook, load_workbook

    conn = sqlite3.connect(out)
    previous: list[list] = []
    if workbook.is_file():
        try:
            prior = load_workbook(workbook)
            if "runs" in prior.sheetnames:
                previous = [list(r) for r in prior["runs"].iter_rows(min_row=2, values_only=True)]
        except Exception:
            previous = []
    wb = Workbook()
    ws = wb.active
    ws.title = "summary"
    ws.append(["symbol", "doc_type", "docs", "pages", "needs_ocr_pages", "undated", "newest_filing_date",
               "newest_known_at", "oldest_filing_date"])
    summary: dict[str, dict] = {}
    for symbol in symbols:
        for row in conn.execute(
            "SELECT d.doc_type, COUNT(*), SUM(d.pages), "
            "(SELECT COUNT(*) FROM doc_page p JOIN doc x ON x.doc_key=p.doc_key WHERE x.symbol=d.symbol "
            " AND x.doc_type=d.doc_type AND p.method='needs_ocr'), SUM(d.known_at IS NULL), "
            "MAX(d.filing_date), MAX(d.known_at), MIN(d.filing_date) FROM doc d WHERE d.symbol=? "
            "GROUP BY d.doc_type ORDER BY d.doc_type", (symbol,)):
            ws.append([symbol, *row])
            summary.setdefault(symbol, {})[row[0]] = {"docs": row[1], "pages": row[2] or 0, "newest": row[5]}
        newest = conn.execute("SELECT MAX(known_at), COUNT(*), SUM(pages) FROM doc WHERE symbol=?", (symbol,)).fetchone()
        summary.setdefault(symbol, {})["_all"] = {"newest_known_at": newest[0], "docs": newest[1], "pages": newest[2] or 0}
    docs = {s: [dict(zip(("doc_type", "filing_date", "title", "source_record"), r)) for r in conn.execute(
        "SELECT doc_type, filing_date, title, source_record FROM doc WHERE symbol=?", (s,))] for s in symbols}

    miss = wb.create_sheet("missing")
    miss.append(["symbol", "kind", "period", "expected", "held", "detail"])
    work = wb.create_sheet("fetch_worklist")
    work.append(["symbol", "NEWSID", "attachment", "dissem_ts", "category", "subcat", "headline", "url"])
    for symbol in symbols:
        company = cfg.companies[symbol]
        records = Records(cfg, company, [h[0] for h in isin_history(cfg, symbol)] or list(company.isins))
        mine = docs[symbol]
        held_ids: set[str] = set()
        for d in mine:
            meta = json.loads(d["source_record"] or "{}")
            for k in ("NEWSID", "attachment"):
                if meta.get(k):
                    held_ids.add(str(meta[k]).lower())
            for filing in meta.get("filings", []):
                for k in ("NEWSID", "attachment"):
                    if filing.get(k):
                        held_ids.add(str(filing[k]).lower())
        for year, label in ((2025, "FY25"), (2026, "FY26")):
            n = sum(1 for d in mine if d["doc_type"] == "annual_report" and _in(d["filing_date"], f"{year}-04-01", f"{year}-12-31"))
            miss.append([symbol, "annual_report", label, 1, n, "" if n else f"no annual report filed Apr-Dec {year} held"])
        for label, start, end in quarter_windows():
            filings = [r for r in records.ann_rows if r["category"].lower() == "result"
                       and "financial result" in r["subcat"].lower() and _in(r["filing_date"], start, end)]
            held = [r for r in filings if r["NEWSID"].lower() in held_ids or r["attachment"].lower() in held_ids]
            res = sum(1 for d in mine if d["doc_type"] in ("results", "press_release") and _in(d["filing_date"], start, end))
            miss.append([symbol, "quarterly_results", label, max(len(filings), 1), max(len(held), res),
                         "" if (held or res) else "no results filing held" + ("" if filings else " (no BSE record either)")])
            for kind, win_end in (("deck", end), ("transcript", end)):
                n = sum(1 for d in mine if d["doc_type"] == kind and _in(d["filing_date"], start, win_end))
                miss.append([symbol, "investor_deck" if kind == "deck" else "earnings_call_transcript", label, 1, n,
                             "" if n else f"none held with filing date {start}..{win_end}"])
        ann_docs = [d for d in mine if d["doc_type"] in ("announcement", "press_release", "results", "deck", "transcript", "other")]
        newest_held = max((d["filing_date"] for d in ann_docs if d["filing_date"]), default=None)
        newest_rec = max((r["filing_date"] for r in records.ann_rows if r["filing_date"]), default=None)
        later = [r for r in records.ann_rows if r["attachment"] and newest_held and r["filing_date"] and r["filing_date"] > newest_held]
        miss.append([symbol, "announcements_after_newest_held_doc", f">{newest_held}", len(later), 0,
                     f"newest BSE record {newest_rec}; {len(later)} attachment rows newer than newest held doc"])
        gaps = [r for r in records.ann_rows if r["attachment"] and r["filing_date"] and r["filing_date"] >= WINDOW_START
                and r["NEWSID"].lower() not in held_ids and r["attachment"].lower() not in held_ids]
        total = sum(1 for r in records.ann_rows if r["attachment"] and r["filing_date"] and r["filing_date"] >= WINDOW_START)
        miss.append([symbol, "announcement_attachments", f"{WINDOW_START}..", total, total - len(gaps),
                     f"{len(gaps)} headline rows have no held body (see fetch_worklist)"])
        for r in sorted(gaps, key=lambda r: r["known_at"] or ""):
            work.append([symbol, r["NEWSID"], r["attachment"], r["known_at"], r["category"], r["subcat"],
                         r["headline"][:160], f"https://www.bseindia.com/xml-data/corpfiling/AttachHis/{r['attachment']}"])
        summary[symbol]["_missing_attachments"] = len(gaps)
    runs = wb.create_sheet("runs")
    runs.append(["run_at", "symbol", "docs", "pages", "newest_known_at", "missing_attachments"])
    for row in previous:
        runs.append(row)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for symbol in symbols:
        s = summary[symbol]
        runs.append([now, symbol, s["_all"]["docs"], s["_all"]["pages"], s["_all"]["newest_known_at"],
                     s["_missing_attachments"]])
    workbook.parent.mkdir(parents=True, exist_ok=True)
    wb.save(workbook)
    conn.close()
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="T-049 C: collect every held document of the pilot companies")
    parser.add_argument("--out", type=Path, default=None, help="default: the profile's pages_db, else D:\\RealityEngine\\pilot3\\pages.db")
    parser.add_argument("--profile", type=Path, default=None,
                        help="build profile JSON (T-056): read its manifest only and write its pages_db tables")
    parser.add_argument("--symbols", default=None, help="default: every company of the profile, else the pilot3 three")
    parser.add_argument("--coverage", type=Path, default=None, help="default: DOC_COVERAGE.xlsx beside --out")
    parser.add_argument("--data-root", type=Path, default=None)
    args = parser.parse_args(argv)
    if args.profile:
        prof = profile.load(args.profile)
        profile.activate(prof)
        symbols = tuple(s.strip().upper() for s in (args.symbols or ",".join(prof.symbols)).split(",") if s.strip())
        unknown = [s for s in symbols if s not in prof.symbols]
        if unknown:
            print(f"STOPPED unknown symbols {unknown}: profile {prof.name} has {list(prof.symbols)}", file=sys.stderr)
            return 2
        out = args.out or prof.pages_db
        counts = collect_manifest(prof, symbols, out)
        for symbol in symbols:
            s = counts[symbol]
            print(f"{symbol}: {s['docs']} docs, {s['pages']} pages ({s['undated']} undated, {s['missing']} files not held, "
                  f"{s['not_documents']} not documents, {s['needs_ocr']} needs_ocr pages) -> {out}")
        return 0
    symbols = tuple(s.strip().upper() for s in (args.symbols or ",".join(profile.symbols())).split(",") if s.strip())
    known = profile.companies()
    unknown = [s for s in symbols if s not in known]
    if unknown:
        print(f"STOPPED unknown symbols {unknown}: choose from {list(known)}", file=sys.stderr)
        return 2
    cfg = Config(data_root=args.data_root or default_data_root())
    counts = collect(cfg, symbols, args.out or DEFAULT_OUT)
    summary = coverage(cfg, symbols, args.out or DEFAULT_OUT,
                       args.coverage or (args.out or DEFAULT_OUT).parent / "DOC_COVERAGE.xlsx")
    for symbol in symbols:
        s = summary[symbol]["_all"]
        print(f"{symbol}: {s['docs']} docs, {s['pages']} pages, newest known_at {s['newest_known_at']}, "
              f"{summary[symbol]['_missing_attachments']} announcement attachments not held "
              f"[{counts[symbol]['undated']} undated, {counts[symbol]['needs_ocr']} needs_ocr pages]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
