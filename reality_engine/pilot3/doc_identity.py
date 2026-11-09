"""Identity verdict for one held document before anything is extracted from it (T-093).  Local checks, no model.

Four checks, one column each with a reason: company, fiscal year, type, date.  A failure sets the document aside; it is
never deleted, and the build reads the verdict.  ``check`` is a pure function of the first pages and what the filing
record says, so it can run over the whole universe in parallel.

    ok         every check passed
    set_aside  a check failed: another company's file, a newspaper notice labelled annual report, a 2022 report filed
               under a 2026 date
    unknown    the text is too thin to judge (scanned or garbled); the reason says so and nothing is guessed
    on_drive   the row has no file on disk but the Drive archive index holds it; no text check, unless a bounded sample
               fetch asks for it
    not_held   no file was found on disk or in the archive index

The company check reuses the name logic of ``scripts/ar_wrong_company_scan.py``: a first-page mismatch re-reads the
whole file for the auditor's-report pages, and its ISIN prefix or scrip code anywhere rescues a renamed company.  The
company name never appears in this module: names, pages and fiscal years come from the row and the text.

Read-only: no store is written here.  ``resolve_file`` reads a sha-to-path index built once over the raw store's
sha-named folders (``docs_collect.SHA_DIRS``) plus the Drive archive index kept by ``toolbelt/drive_fetch.py``.
"""
from __future__ import annotations

import hashlib
import os
import posixpath
import re
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path

from reality_engine import raw_store
from reality_engine.config import DATA_DIR, resolve_stored_path
from reality_engine.scripts import ar_queue
from reality_engine.scripts.ar_wrong_company_scan import AUDIT_RE, alias_tokens, page_hits

# Common English words, so a one-word company name that is an ordinary word needs "Ltd" beside it.  Words in at least half
# of ten annual reports, kept in the repo: the scan's own file under the raw store no longer exists.
ar_queue.VOCAB_F = Path(__file__).with_name("en_vocab.txt")

RAW_ROOT = Path(os.environ.get("REALITY_RAW_ROOT", r"D:\RealityEngine\raw"))
FIRST_PAGES = 5
THIN_CHARS = 200                 # fewer characters than this in the first pages: scanned or garbled, never guessed
AR_MIN_PAGES = 25                # a meeting notice is 15 pages; an annual report is 100+, so page count is type evidence
DRIVE_FETCH_LIMIT = 50           # the most files a measurement may download from Drive
_SHA = re.compile(r"[0-9a-f]{64}\Z")


@dataclass
class Expected:
    """What the filing record claims about the document."""
    symbol: str
    doc_type: str
    names: tuple[str, ...] = ()
    isin_prefixes: tuple[str, ...] = ()
    bse_codes: tuple[str, ...] = ()
    bse_subcat: str | None = None
    doc_date: str | None = None
    created_at: str | None = None
    bse_dissem_ts: str | None = None
    publication_date: str | None = None
    pit_source: str | None = None
    pages: int | None = None


@dataclass
class Verdict:
    verdict: str = "unknown"
    company: str = "not_checked"           # ok | mismatch | thin | not_checked
    company_reason: str = ""
    fiscal_year: str = "not_checked"       # ok | mismatch | thin | not_checked
    fiscal_year_reason: str = ""
    type: str = "not_checked"              # ok | mismatch | thin | not_checked
    type_reason: str = ""
    date: str = "not_checked"              # filing | crawl_date | unknown
    date_reason: str = ""
    filing_date: str | None = None         # the real filing date, from a filing record or the page-1 letter
    linked_url: str = ""                   # any http(s) link printed on page 1 (a web-link cover letter's target)
    text_chars: int = 0
    extra: dict = field(default_factory=dict)

    def row(self) -> dict:
        out = asdict(self)
        out.pop("extra")
        return out


# ---------------------------------------------------------------------------- company
def check_company(text: str, expected: Expected, evidence_text: str | None = None,
                  whole_text: str | None = None) -> tuple[str, str]:
    """Any of the company's names, its ISIN issuer prefix or its BSE scrip code in the first pages.

    ``evidence_text`` (the auditor's-report pages, found after a first-page miss) is the strong name evidence the
    scan uses for ``ok``: a parent's report names subsidiaries only in passing, while its auditor's report names the
    reporting company.  ``whole_text`` backstops the scan's ``former_name``: an own ISIN prefix or scrip code anywhere
    rescues a company renamed before the first page could name it."""
    aliases = [(name, alias_tokens(name)) for name in expected.names if alias_tokens(name)]
    hits = page_hits(aliases, text)
    if hits:
        return "ok", f"name: {hits[0]}"
    upper = text.upper()
    for prefix in expected.isin_prefixes:
        if prefix.upper() in upper:
            return "ok", f"ISIN prefix {prefix}"
    for code in expected.bse_codes:
        if code and code in text:
            return "ok", f"scrip code {code}"
    if evidence_text and evidence_text is not whole_text:
        hits = page_hits(aliases, evidence_text)
        if hits:
            return "ok", f"name {hits[0]} on the auditor's-report pages (late first mention)"
    if whole_text:
        upper = whole_text.upper()
        own = next((f"ISIN prefix {p}" for p in expected.isin_prefixes if p.upper() in upper), None) or \
              next((f"scrip code {c}" for c in expected.bse_codes if c and c in whole_text), None)
        if own:
            return "ok", f"{own} later in the file (former name)"
        hits = page_hits(aliases, whole_text)
        if hits:
            return "ok", f"name {hits[0]} later in the file (late first mention)"
    names = list(expected.names)[:2]
    return "mismatch", f"none of {names}, its ISIN prefix or scrip code in the first pages or the auditor's-report pages"


# ---------------------------------------------------------------------------- fiscal year
_MONTHS = ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
           "november", "december")
_MONTH_RE = "|".join(_MONTHS)
_RANGE_RE = re.compile(r"\b(20\d{2})\s*[-–/]\s*(\d{2}|20\d{2})\b")
_FY_RE = re.compile(r"\bFY\s*'?((?:20)?\d{2})\b", re.I)
_FISCAL_RE = re.compile(r"\bfiscal(?:\s+year)?\s+(20\d{2})\b", re.I)
_YEAR_END_RE = re.compile(
    rf"\b(?:year|period|quarter|half[- ]year|nine months|six months|three months)\s+ended\s+"
    rf"(?:\d{{1,2}}(?:st|nd|rd|th)?\s+(?:{_MONTH_RE})[,\s]+(20\d{{2}})"
    rf"|(?:{_MONTH_RE})\s+\d{{1,2}},?\s+(20\d{{2}})"
    rf"|\d{{1,2}}[./-]\d{{1,2}}[./-](20\d{{2}}))", re.I)
_ANNUAL_REPORT_RE = re.compile(
    r"\b(?:integrated\s+)?annual\s+report\b|\bintegrated\s+report\b|\bdirectors'?\s+report\b|"
    r"\bboard'?s\s+report\b|\bauditors'?\s+report\b|\bannual\s+accounts\b", re.I)
_PROCEEDINGS_RE = re.compile(
    r"\bsummary\s+of\s+proceedings\b|\bproceedings\s+of\s+the\s+(?:\d+(?:st|nd|rd|th)\s+)?annual\s+general\s+meeting\b|"
    r"\bdisclosure\s+of\s+voting\s+results\b", re.I)
_NEWSPAPER_RE = re.compile(
    r"\bnewspaper\s+(?:publication|advertisement|notice)\b|\be-?clippings?\b|\be-?paper\b|"
    r"\badvertisement\b.{0,80}\b(?:newspaper|edition|daily)\b|"
    r"\bpublished\s+in\b.{0,80}\b(?:newspaper|daily|edition)\b", re.I | re.S)
_TRANSCRIPT_RE = re.compile(
    r"\b(?:earnings|analyst|investor|post[- ]?results|conference|earnings\s+webinar)\s+call\b|"
    r"\bcall\s+transcript\b|\btranscript\b|\bconference\s+call\b|\bearnings\s+webinar\b|"
    r"\bmoderator\b|\bmanagement\s+(?:participants|representatives)\b|"
    r"\bquestion\s*(?:and|&)\s*answer\b", re.I)
_PRESENTATION_RE = re.compile(
    r"\binvestor\s+(?:presentation|deck)\b|\b(?:corporate|company|analyst)\s+presentation\b|"
    r"\bpresentation\s+(?:on|for)\b.{0,40}\b(?:investor|analyst)\b|\bsafe\s+harbou?r\b|"
    r"\bperformance\s+highlights\b|\binvestor\s+meet\b|\banalyst\s+meet\b", re.I | re.S)
_RESULTS_RE = re.compile(
    r"\b(?:unaudited|audited)\s+(?:standalone\s+and\s+consolidated\s+)?(?:financial\s+)?results\b|"
    r"\bfinancial\s+results\s+for\s+the\s+(?:quarter|year|half)\b|"
    r"\bstatement\s+of\s+(?:unaudited|audited)?\s*(?:financial\s+)?results\b|"
    r"\bstatement\s+of\s+profit\s+and\s+loss\b|\bbalance\s+sheet\b|\brevenue\s+from\s+operations\b", re.I)
_NOTICE_RE = re.compile(
    r"\bnotice\s+of\s+(?:the\s+)?(?:\d+(?:st|nd|rd|th)?\s+)?annual\s+general\s+meeting\b|"
    r"\bnotice\s+of\s+(?:the\s+)?agm\b|\bnotice\s+convening\b|"
    r"\bnotice\s+is\s+hereby\s+given\s+that\s+the\s+.{0,40}annual\s+general\s+meeting\b", re.I)
# A heading that only an annual report prints, at the top of a page: a notice's resolution also says "Balance Sheet
# as at", but mid-paragraph, so only the first lines of a page count.
_AR_HEAD_RE = re.compile(
    r"^(?:independent\s+)?auditors?.{0,8}report|^\s*balance\s+sheet\s+as\s+at|"
    r"^\s*statement\s+of\s+profit\s+and\s+loss|^\s*cash\s+flow\s+statement", re.I)

_COVER_LETTER_RE = re.compile(r"\bplease\s+find\s+enclosed\b|\benclosed\s+herewith\b|\bwe\s+enclose\b|"
                              r"\bplease\s+find\s+attached\b", re.I)
_TRANSCRIPT_BODY_RE = re.compile(r"\bmoderator\b|\bmanagement\s+(?:participants|representatives)\b|"
                                 r"\bquestion\s*(?:and|&)\s*answer\b|\bq\s*&\s*a\b", re.I)
# A real annual report runs to 40+ pages; below that the meeting notice alone can carry the words "annual report".
AR_SECTION_PAGES = 40
# doc_type -> the family the first-page text must show.  A label not in this map is not type-checked.
EXPECTED_KINDS = {"ANNUAL_REPORT": "annual_report", "CONCALL_TRANSCRIPT": "transcript",
                  "INVESTOR_PRESENTATION": "presentation", "FINANCIAL_RESULT": "results"}


def _fy_years(text: str) -> set[int]:
    years: set[int] = set()
    for m in _RANGE_RE.finditer(text):
        first, second = m.group(1), m.group(2)
        years.add(int(second) if len(second) == 4 else int(first[:2] + second))
    for m in _FY_RE.finditer(text):
        value = int(m.group(1))
        years.add(value if value >= 1900 else 2000 + value)
    for m in _FISCAL_RE.finditer(text):
        years.add(int(m.group(1)))
    for m in _YEAR_END_RE.finditer(text):
        years.add(int(next(g for g in m.groups() if g)))
    return years


def _anchor_date(expected: Expected) -> str | None:
    """The date the row claims the document belongs to: its filing record, else ``doc_date``."""
    for value in (expected.bse_dissem_ts, expected.publication_date, expected.doc_date):
        if value and str(value)[:10] >= "1990-01-01":
            return str(value)[:10]
    return None


def _fiscal_expected(expected: Expected) -> tuple[str, set[int] | None]:
    """``(kind, accepted end-years)`` for the label; ``("", None)`` when the label is not fiscal-year checked."""
    kind = "annual_report" if expected.doc_type == "ANNUAL_REPORT" else (
        "results" if expected.doc_type == "FINANCIAL_RESULT" else "")
    anchor = _anchor_date(expected)
    if not kind or not anchor:
        return kind, None
    try:
        filed = date.fromisoformat(anchor)
    except ValueError:
        return kind, None
    if kind == "annual_report":            # FY ending March Y is filed April..December Y
        return kind, {filed.year if filed.month >= 4 else filed.year - 1}
    return kind, {filed.year, filed.year - 1}   # a quarter filed in Jan/Feb still ends the year before


def _ar_section(whole_pages: dict[int, str] | None, first_pages: dict[int, str] | None = None) -> bool:
    """An annual report's section heading at the top of a page (its auditor's report, balance sheet, P&L or cash flow)."""
    for pages in (whole_pages, first_pages):
        for text in (pages or {}).values():
            lines = [ln.strip() for ln in (text or "").strip().splitlines()[:3] if ln.strip()]
            if any(len(ln) <= 90 and _AR_HEAD_RE.search(ln) for ln in lines):
                return True
    return False


def check_fiscal_year(text: str, expected: Expected, kind: str = "") -> tuple[str, str]:
    want, accepted = _fiscal_expected(expected)
    if not want:
        return "not_checked", ""
    if kind and kind != want:              # a newspaper notice's "FY 2026-27" ref is not this document's fiscal year
        return "not_checked", f"the text is a {kind}, not the label's {want.replace('_', ' ')}"
    if accepted is None:
        return "not_checked", "no filing date to check the fiscal year against"
    years = _fy_years(text)
    if not years:
        return "thin", "no fiscal year in the first pages"
    if years & accepted:
        return "ok", f"text FY {sorted(years & accepted)[-1]}"
    return "mismatch", f"text says FY {sorted(years)[-1]}, the record is dated {_anchor_date(expected)}"


_URL_RE = re.compile(r"https?://[^\s<>\"')]+", re.I)


def linked_url(text: str) -> str:
    """The first http(s) link printed on a page (a cover letter's web-link target), trailing punctuation removed."""
    match = _URL_RE.search(text or "")
    return match.group(0).rstrip(".,;:") if match else ""


def check_type(text: str, expected: Expected, pages: int | None,
               whole_pages: dict[int, str] | None = None) -> tuple[str, str]:
    want = EXPECTED_KINDS.get(expected.doc_type)
    if not want:
        return "not_checked", ""
    if want == "transcript" and pages is not None and pages <= 2 and not _TRANSCRIPT_BODY_RE.search(text):
        return "mismatch", f"cover_letter: label CONCALL_TRANSCRIPT but the text is a {pages}-page notification; " \
                           f"the transcript itself is not held"
    if want == "presentation" and pages is not None and pages <= 2 and \
            _COVER_LETTER_RE.search(text) and not _TRANSCRIPT_BODY_RE.search(text):
        return "mismatch", f"cover_letter: label {expected.doc_type} but the text is a {pages}-page covering letter"
    if want == "annual_report" and pages is not None and pages <= 3 and (
            _COVER_LETTER_RE.search(text) or re.search(r"\bweb[- ]link\b|\bavailable on the (?:Company'?s? )?website\b",
                                                       text, re.I)):
        return "mismatch", f"cover_letter: label ANNUAL_REPORT but the text is a {pages}-page web-link letter; " \
                           f"the annual report itself is not held"
    got = classify_type(text, pages, whole_pages)
    if got == want:
        hint = ""
        if expected.bse_subcat and _subcat_family(expected.bse_subcat) not in ("", want):
            hint = f"; the text beats the BSE category {expected.bse_subcat}"
        return "ok", f"{want}{hint}"
    if not got:
        if pages is None:                  # unit callers may hold only the text
            return "not_checked", ""
        if want == "annual_report" and pages < AR_MIN_PAGES:
            return "mismatch", f"label ANNUAL_REPORT but {pages} pages with no annual-report wording" + (
                f" (BSE category {expected.bse_subcat})" if expected.bse_subcat else "")
        return "thin", f"no {want} wording in the first pages (BSE category {expected.bse_subcat or 'none'})"
    return "mismatch", f"label {expected.doc_type} but the text is a {got}" + (
        f" (BSE category {expected.bse_subcat})" if expected.bse_subcat else "") + (
        f", {pages} pages" if pages is not None else "")


def classify_type(text: str, pages: int | None = None,
                  whole_pages: dict[int, str] | None = None) -> str:
    """What the first-page text is: annual_report | transcript | presentation | results | newspaper | notice | ''.

    Order matters.  A newspaper clipping and a transcript win over everything (their own letter names them); an
    annual report needs enough pages or a section heading, because a meeting notice also says "annual general
    meeting"; a notice wins over a results table mentioned in its ordinary business."""
    if _NEWSPAPER_RE.search(text) and (pages is None or pages <= 8):
        return "newspaper"
    if _PROCEEDINGS_RE.search(text):
        return "proceedings"
    if (pages is None or pages < 60) and _TRANSCRIPT_RE.search(text):   # a 100+ page document is not a call transcript
        return "transcript"
    if (pages is None or pages < 60) and _PRESENTATION_RE.search(text) and not _RESULTS_RE.search(text):
        return "presentation"
    section = _ar_section(whole_pages)
    if _ANNUAL_REPORT_RE.search(text) and (pages is None or pages >= AR_SECTION_PAGES or section):
        return "annual_report"
    if (pages is not None and pages >= 60 and section):   # a cover page may not say "annual report"
        return "annual_report"
    if pages is not None and pages >= 100:               # a 100+ page filing under ANNUAL_REPORT is the report booklet
        return "annual_report"
    if _NOTICE_RE.search(text):
        return "notice"
    if _RESULTS_RE.search(text):
        return "results"
    if _NEWSPAPER_RE.search(text):
        return "newspaper"
    return ""


def _subcat_family(subcat: str) -> str:
    """BSE sub-category -> family, using docs_collect's own map so the hint speaks the same vocabulary."""
    from reality_engine.pilot3.docs_collect import SUBCAT_TYPES
    return SUBCAT_TYPES.get(str(subcat or "").strip().lower(), "")


_MODERATOR_RE = re.compile(r"\bmoderator\b", re.I)


def moderator_line(text: str) -> bool:
    """The call's own moderator line on a page ("Moderator: Ladies and gentlemen, good day...") (T-159).

    This is the marker that separates a transcript from a document that only names a call: a Titan or Bharti
    Airtel intimation says "followed by a Q&A session" and an IndiGo deck lists "Q&A" in its agenda, while every
    call transcript prints the moderator's opening.  The T-157 audit used the same marker."""
    return bool(_MODERATOR_RE.search(text or ""))


# ---------------------------------------------------------------------------- date
_MONTH_NUM = {name: i + 1 for i, name in enumerate(_MONTHS)}
_LETTER_DATE_RES = (
    re.compile(rf"\b(?:{_MONTH_RE})\s+\d{{1,2}},?\s+(20\d{{2}})\b", re.I),
    re.compile(rf"\b\d{{1,2}}(?:st|nd|rd|th)?\s+(?:{_MONTH_RE}),?\s+(20\d{{2}})\b", re.I),
    re.compile(r"\b\d{1,2}[./-]\d{1,2}[./-](20\d{2})\b"),
    re.compile(r"\b(20\d{2})-\d{2}-\d{2}\b"),
)


def letter_date(text: str) -> str | None:
    """The first date printed on page 1 (a covering letter's own date), as ISO, when the record has none."""
    for pattern in _LETTER_DATE_RES:
        for m in pattern.finditer(text or ""):
            year = int(m.group(1))
            if not 1990 <= year <= 2035:
                continue
            raw = m.group(0)
            month = next((num for name, num in _MONTH_NUM.items() if name in raw.lower()), None)
            if month is None:
                parts = re.findall(r"\d+", raw)
                if len(parts) == 3 and len(parts[0]) == 4:
                    return f"{parts[0]}-{int(parts[1]):02d}-{int(parts[2]):02d}"
                if len(parts) == 3:
                    return f"{parts[2]}-{int(parts[1]):02d}-{int(parts[0]):02d}"
                continue
            day_match = re.search(r"\d{1,2}", raw)
            day = int(day_match.group(0)) if day_match else 1
            return f"{year}-{month:02d}-{day:02d}"
    return None

def check_date(expected: Expected, first_pages: dict[int, str] | None = None) -> tuple[str, str | None, str]:
    """The row's date: from a filing record, else the crawl date when nothing backs ``doc_date``.

    ``filing_date`` is the real date: ``bse_dissem_ts`` then ``publication_date``; when the record has neither and
    ``doc_date`` is only the crawl date, the covering letter's own date on page 1 is used."""
    record = expected.bse_dissem_ts or expected.publication_date
    if record:
        when = str(record)[:10]
        source = "bse_dissem_ts" if expected.bse_dissem_ts else "publication_date"
        return "filing", when, f"{source} {when}"
    doc = str(expected.doc_date)[:10] if expected.doc_date else ""
    created = str(expected.created_at)[:10] if expected.created_at else ""
    if doc and doc == created and not expected.pit_source:
        letter = letter_date((first_pages or {}).get(1, ""))
        reason = f"doc_date {doc} equals the crawl date and no BSE or PIT field backs it"
        if letter:
            reason += f"; the page-1 letter is dated {letter}"
        return "crawl_date", letter, reason
    if doc:
        return "filing", doc, f"doc_date {doc} (no BSE dissemination)"
    return "unknown", None, "no doc_date and no filing record"


# ---------------------------------------------------------------------------- verdict
def check(first_pages: dict[int, str], expected: Expected, whole_pages: dict[int, str] | None = None,
          evidence_text: str | None = None) -> Verdict:
    """The verdict from the first pages' text and the filing record.

    ``whole_pages`` (every page) is read only when the first pages miss the company or leave an annual report's type
    in doubt; ``evidence_text`` is its auditor's-report pages.  The common path opens nothing after the first pages."""
    text = "\n".join(first_pages[page] for page in sorted(first_pages))
    whole_text = "\n".join(whole_pages[page] for page in sorted(whole_pages)) if whole_pages else None
    result = Verdict(text_chars=len(text.strip()), linked_url=linked_url(first_pages.get(1, "")))
    result.date, result.filing_date, result.date_reason = check_date(expected, first_pages)
    if result.text_chars < THIN_CHARS:
        result.company = "thin"
        result.company_reason = f"{result.text_chars} characters in the first {len(first_pages)} pages"
        result.fiscal_year = "thin" if _fiscal_expected(expected)[0] else "not_checked"
        result.type = "thin" if expected.doc_type in EXPECTED_KINDS else "not_checked"
        result.verdict = "unknown"
        return result
    result.company, result.company_reason = check_company(text, expected, evidence_text, whole_text)
    result.type, result.type_reason = check_type(text, expected, expected.pages, whole_pages)
    if result.type == "mismatch":          # a newspaper notice's "FY 2026-27" ref is not a fiscal-year failure
        result.fiscal_year, result.fiscal_year_reason = "not_checked", "the text is not the label's document"
    else:
        result.fiscal_year, result.fiscal_year_reason = check_fiscal_year(
            whole_text or text, expected, classify_type(text, expected.pages, whole_pages))
    statuses = (result.company, result.fiscal_year, result.type)
    if "mismatch" in statuses:
        result.verdict = "set_aside"
    elif "thin" in statuses:
        result.verdict = "unknown"
    else:
        result.verdict = "ok"
    return result


# ---------------------------------------------------------------------------- file lookup
@dataclass
class FileIndex:
    """One sha-to-path map for the raw store plus the Drive archive index, built once and passed to every row."""
    raw_root: Path = RAW_ROOT
    disk: dict[str, Path] = field(default_factory=dict)          # sha256 -> local PDF
    drive: dict[str, str] = field(default_factory=dict)          # sha256 -> archive-relative path
    drive_files: dict[str, dict] = field(default_factory=dict)   # archive-relative path -> drive entry
    archive: dict = field(default_factory=dict)                  # drive_fetch's folder index
    index_path: Path | None = None

    def add_drive_index(self, path: Path) -> None:
        from reality_engine.toolbelt import drive_fetch
        loaded = drive_fetch.load_index(Path(path), drive_fetch.DEFAULT_REMOTE)
        self._merge_archive(loaded)
        if self.index_path is None:
            self.index_path = Path(path)

    def _merge_archive(self, archive: dict) -> None:
        folders = self.archive.setdefault("folders", {})
        for folder, bucket in (archive.get("folders") or {}).items():
            folders.setdefault(folder, bucket)
        self.archive.setdefault("remote", archive.get("remote") or "gdrive:InfoDiffusion_archive")
        self.archive.setdefault("schema", archive.get("schema", 1))
        self.reindex_drive()

    def reindex_drive(self) -> None:
        self.drive, self.drive_files = {}, {}
        for bucket in (self.archive.get("folders") or {}).values():
            for rel, entry in (bucket.get("files") or {}).items():
                self.drive_files[rel] = entry
                self.drive_files.setdefault(rel.lower(), entry)
                sha = str(entry.get("sha256") or "").lower()
                if _SHA.fullmatch(sha):
                    self.drive.setdefault(sha, rel)

    def add_drive_folder(self, folder: str, timeout: float = 300.0) -> None:
        """List one archive folder into the index (network, listing only: never a download)."""
        from reality_engine.toolbelt import drive_fetch
        if not folder or folder in (self.archive.get("folders") or {}):
            return
        drive_fetch.index_folder(self.archive, folder, timeout=timeout)
        self.reindex_drive()

    def save(self, path: Path) -> None:
        from reality_engine.toolbelt import drive_fetch
        path.parent.mkdir(parents=True, exist_ok=True)
        drive_fetch.save_index(path, self.archive)
        self.index_path = path

    def find(self, rel: str) -> str | None:
        """The archive path for an exact stored path, or the same file with a drifted crawl-date prefix."""
        from reality_engine.toolbelt import drive_fetch
        rel = rel.replace("\\", "/").lstrip("/")
        if rel in self.drive_files or rel.lower() in self.drive_files:
            return rel
        folder = posixpath.dirname(rel)
        suffix = drive_fetch.suffix_of(rel)
        if not suffix:
            return None
        for candidate in self.drive_files:
            if candidate.lower().startswith(folder.lower() + "/") and \
                    (drive_fetch.suffix_of(candidate) or "").lower() == suffix.lower():
                return candidate
        return None


def sha_index(raw_root: Path | None = None) -> dict[str, Path]:
    """``sha256 -> file`` over every sha-named PDF folder of the raw store (``docs_collect.SHA_DIRS``)."""
    from reality_engine.pilot3.docs_collect import SHA_DIRS
    root = Path(raw_root or RAW_ROOT)
    found: dict[str, Path] = {}
    for folder in SHA_DIRS:
        base = root / folder
        if not base.is_dir():
            continue
        for dirpath, _dirs, files in os.walk(base):
            for name in files:
                if name.lower().endswith(".pdf"):
                    stem = name[:-4].lower()
                    if _SHA.fullmatch(stem):
                        found.setdefault(stem, Path(dirpath) / name)
    return found


def drive_index_candidates() -> list[Path]:
    """The Drive index files to read: env, this worktree, then the main checkout's ``.tmp``."""
    out: list[Path] = []
    env = os.environ.get("REALITY_DRIVE_INDEX")
    if env:
        out.append(Path(env))
    out.append(Path(".tmp") / "drive_index.json")
    out.append(Path(".tmp") / "doc_identity_drive_index.json")
    for root in (os.environ.get("REALITY_DATA_ROOT"), str(DATA_DIR)):
        if root:
            out.append(Path(root).resolve().parents[1] / ".tmp" / "drive_index.json")
    seen, keep = set(), []
    for path in out:
        key = str(path.resolve()).lower()
        if key not in seen and Path(path).is_file():
            seen.add(key)
            keep.append(Path(path))
    return keep


def build_file_index(raw_root: Path | None = None, drive_indexes: list[Path] | None = None) -> FileIndex:
    index = FileIndex(raw_root=Path(raw_root or RAW_ROOT), disk=sha_index(raw_root))
    for path in (drive_indexes if drive_indexes is not None else drive_index_candidates()):
        index.add_drive_index(path)
    return index


_INDEX: FileIndex | None = None


def get_index() -> FileIndex:
    """The process-wide index (the eval and the scan build it once)."""
    global _INDEX
    if _INDEX is None:
        _INDEX = build_file_index()
    return _INDEX


def resolve_file(row, index: FileIndex | None = None) -> tuple[Path | None, str, str | None]:
    """``(path, where, archive_path)`` of a ``corporate_documents`` row.

    ``where`` is ``disk`` (path set), ``drive`` (archive_path set, not downloaded), ``missing`` (a hash but no file) or
    ``no_hash`` (no hash to search by).  The stored path is tried first, re-rooted by ``config.resolve_stored_path``;
    then the sha index; then the Drive archive index by sha or by the stored path itself."""
    index = index if index is not None else get_index()
    stored = row["local_file_path"]
    if stored:
        path = resolve_stored_path(stored)
        if path.is_file():
            return path, "disk", None
        drive = raw_store.default_store().drive_path(path)   # the T-102 upload moved the file off the disk
        if drive:
            return None, "drive", drive
    sha = (row["sha256_hash"] or "").strip().lower()
    if sha and sha in index.disk:
        return index.disk[sha], "disk", None
    rel = None
    if stored:
        try:
            from reality_engine.toolbelt.drive_fetch import local_to_remote
            rel = index.find(local_to_remote(stored))
        except ValueError:
            rel = None
    if rel:
        return None, "drive", rel
    if sha and sha in index.drive:
        return None, "drive", index.drive[sha]
    folder = ""
    if stored:
        try:
            from reality_engine.toolbelt.drive_fetch import local_to_remote
            remote = local_to_remote(stored)
            folder = remote.rsplit("/", 1)[0] if "/" in remote else ""
        except ValueError:
            folder = ""
    if folder and folder not in (index.archive.get("folders") or {}):
        return None, "not_indexed", None      # the archive folder was never listed: not found is not "missing"
    return None, ("missing" if sha else "no_hash"), None


def first_pages(path: Path, count: int = FIRST_PAGES) -> tuple[dict[int, str], int]:
    import pymupdf

    doc = pymupdf.open(path)
    try:
        text: dict[int, str] = {i + 1: str(doc[i].get_text()) for i in range(min(count, len(doc)))}
        return text, len(doc)
    finally:
        doc.close()


def whole_pdf(path: Path) -> tuple[dict[int, str], int]:
    """Every page's text, for the auditor's-report evidence after a first-page miss."""
    import pymupdf

    doc = pymupdf.open(path)
    try:
        text: dict[int, str] = {i + 1: str(doc[i].get_text()) for i in range(len(doc))}
        return text, len(doc)
    finally:
        doc.close()


def audit_evidence(pages: dict[int, str]) -> str:
    """The pages whose first 1,500 characters open an independent auditor's report (the scan's evidence pages)."""
    return "\n".join(text for text in pages.values() if AUDIT_RE.search((text or "")[:1500]))


def expected_for(conn: sqlite3.Connection, row, symbol: str | None = None) -> Expected:
    """What the record claims for a document row.  ``symbol`` overrides the row's, as a swapped-pair control does."""
    symbol = symbol or row["symbol"]
    company = conn.execute("SELECT isin, bse_code, company_name FROM master_companies WHERE nse_symbol=? LIMIT 1",
                           (symbol,)).fetchone()
    names, prefixes, codes = (), (), ()
    if company:
        names = (company["company_name"],) if company["company_name"] else ()
        prefixes = (company["isin"][:7],) if company["isin"] else ()
        codes = (str(company["bse_code"]),) if company["bse_code"] else ()
    return Expected(symbol=symbol, doc_type=row["doc_type"], names=names, isin_prefixes=prefixes, bse_codes=codes,
                    bse_subcat=row["bse_subcat"], doc_date=row["doc_date"], created_at=row["created_at"],
                    bse_dissem_ts=row["bse_dissem_ts"], publication_date=row["publication_date"],
                    pit_source=row["pit_source"])


def main_store() -> Path:
    """``equity_intelligence.db``: the worker's data root when it has one (a worktree holds no data)."""
    root = os.environ.get("REALITY_DATA_ROOT")
    return Path(root) / "equity_intelligence.db" if root else DATA_DIR / "equity_intelligence.db"


def check_row(conn: sqlite3.Connection, row, symbol: str | None = None, index: FileIndex | None = None,
              fetch=None) -> Verdict:
    """One ``corporate_documents`` row from its file to its verdict.

    ``fetch`` is an optional callable ``(archive_path) -> local Path | None`` with its own budget; it is the only way
    an ``on_drive`` row is ever downloaded, and the scan caps it at ``DRIVE_FETCH_LIMIT``."""
    path, where, remote = resolve_file(row, index)
    if where == "drive":
        path = fetch(remote) if fetch is not None else None
        if path is None:
            return Verdict(verdict="on_drive", company_reason="file is in the Drive archive; not downloaded",
                           extra={"where": "drive", "remote": remote})
    elif path is None:
        return Verdict(verdict="not_held", company_reason=f"no file: {where}", extra={"where": where})
    expected = expected_for(conn, row, symbol)
    try:
        pages, expected.pages = first_pages(path)
    except Exception as exc:               # unreadable PDF: never a guess
        return Verdict(verdict="unknown", company="thin",
                       company_reason=f"open failed: {type(exc).__name__}: {str(exc)[:80]}",
                       text_chars=0, extra={"where": where, "path": str(path)})
    result = check(pages, expected)
    need_whole = result.company == "mismatch" or (
        result.type == "mismatch" or result.fiscal_year == "thin") and (
        expected.doc_type == "ANNUAL_REPORT" and (expected.pages or 0) <= 500)
    if need_whole:                         # expensive only on a miss: the scan's late-name and small-AR evidence
        try:
            whole, pages_count = whole_pdf(path)
            expected.pages = pages_count
            result = check(pages, expected, whole_pages=whole, evidence_text=audit_evidence(whole))
        except Exception:
            pass
    result.extra = {"where": where, "path": str(path), "pages": expected.pages}
    return result


def identity_key(row) -> str:
    """The ``doc_identity.doc_key`` for a ``corporate_documents`` row: its sha256 (links to ``doc``), else ``corp:<id>``."""
    sha = (row["sha256_hash"] or "").strip().lower()
    return sha if _SHA.fullmatch(sha) else f"corp:{row['id']}"


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
