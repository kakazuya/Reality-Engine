"""Factor loaders — fetch the external series the factor spine is missing.

``factor_spine`` owns the *read* contract; this module owns the *load* half:
it resolves a live source, parses it, and hands observations to
``register_series`` / ``upsert_observations``. Design §4.1-§4.2.

What this module exists to prevent
----------------------------------
The same look-ahead machine ``factor_spine`` guards, arriving from the other
direction. A loader that stamps ``as_of_date = date.today()`` on a 1960
commodity price produces a spine that is internally consistent, passes
``lookahead_audit`` (0 violations, vacuously), and is a pure fiction. So the
rules below are not conventions, they are the design:

**1. ``as_of_date`` comes FROM THE FILE or it does not exist.**
    * World Bank: the workbook's own ``A4`` cell, ``'Updated on September 02,
      2026'``. Parsed by :func:`parse_updated_on`.
    * PPAC: the notification's own ``Dated:`` line, recovered by OCR. Failing
      that, the Unix-epoch upload prefix in the filename — which is
      *inferred*, and therefore forces ``is_point_in_time=0`` /
      ``availability_contract='pita_estimated'`` on the series.
    If no date can be recovered, the load is **refused**. There is no
    fallback to today, because a fallback to today IS the bug. The system
    clock appears in exactly one column here — ``retrieved_at`` — which
    design R3 declares is never a read predicate.

**2. A number is never guessed, interpolated, or carried forward.**
    A missing cell stays NULL. A regex that does not match yields an honest
    NULL with an explicit ``extraction_status`` reason. Three OCR/extraction
    tiers are tried in order and the tier that actually produced text is
    *reported*, not assumed.

**3. A source that cannot be reached returns a failure record, never an
    exception.** Design §4.1: "A loader that cannot reach its source returns
    ``[]`` and records the failure; it never raises into the pipeline." Every
    public fetch returns a dict with ``status`` in ``{'ok', 'partial',
    'failed', 'refused'}`` and a human-readable ``reason``.

Two layout facts that a naive parser gets wrong
----------------------------------------------
Verified against the live file (2026-09-29, 586,735 bytes, 806 data rows,
``1960M01``..``2026M08``):

* **"Monthly Prices" is not ``sheet1.xml``.** Workbook order is
  ``Mismatch Details -> sheet1, Monthly Prices -> sheet2, Monthly Indices ->
  sheet3, Description -> sheet4, Index Weights -> sheet5``. Reading
  ``sheet1.xml`` silently yields the *Mismatch Details* table — plausible
  numbers, wrong table, no error. Resolution therefore goes through
  ``xl/_rels/workbook.xml.rels`` by sheet NAME (:func:`resolve_sheet_part`).
* **The header row is not simply "row 5".** It is the pre-data row with the
  most non-empty text cells, and rows 5 (commodity names) and 6 (units) *tie*
  at 71 cells. The tie is broken toward the upper row — the labels sit above
  their units. :func:`_ranked_header_rows` returns candidates in preference
  order and the parser falls through them until a series column is actually
  found, so a future file that re-weights the rows degrades into "no columns
  matched" (loud) rather than "wrong columns" (silent).

Dependencies
------------
**Standard library only** for the XLSX path: ``zipfile`` + ``xml.etree``.
``openpyxl`` and ``pandas`` are deliberately not used — adding a dependency to
parse one sheet is the wrong trade, and ``zipfile`` is already the right tool.
``fitz``/PyMuPDF and the repo's ``FinancialOCREngine`` are imported
*defensively* inside functions: ``requirements.txt:29`` has PyMuPDF commented
out, so a module-level import would make this file unimportable on a clean
install.

Scope
-----
Fetches and parses only. Writes go through ``load_series``, which is
**dry-run by default** and, in dry-run, touches no database at all.
"""

from __future__ import annotations

import calendar
import hashlib
import io
import logging
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Sequence, Tuple

from reality_engine.processing.factor_spine import (
    _validate_registry_entry,
    ensure_factor_spine_schema,
    register_series,
    upsert_observations,
)

logger = logging.getLogger("reality_engine.factor_loaders")

IST = timezone(timedelta(hours=5, minutes=30), "IST")


# ---------------------------------------------------------------------------
# Source constants
#
# The World Bank's xlsx lives under a *content-addressed* doc id
# (``/doc/<hash>-0050012026/related/...``) that changes with every publication.
# The 2021-era URL that circulated in older notes STOPS at 2024M12 and is
# wrong. So no data URL is hardcoded: the landing page is the constant, and
# the file URL is resolved from it at fetch time (:func:`resolve_pink_sheet_url`).
# ---------------------------------------------------------------------------
WB_LANDING_URL = "https://www.worldbank.org/en/research/commodity-markets"
WB_SHEET_NAME = "Monthly Prices"
WB_SOURCE = "vendor:world_bank_pink_sheet"
WB_LICENSE = (
    "World Bank Pink Sheet, free to use with attribution; review before "
    "redistribution. Vendored series is not a World Bank-endorsed product."
)

#: PPAC (Petroleum Planning & Analysis Cell, MoPNG) publishes the domestic
#: APM natural-gas price as a one-page IMAGE-ONLY PDF notification. There is
#: no JSON/CSV/table endpoint, and the site's route namespace is a
#: soft-404 (every slug under /page/prices/ returns the same 38 KB shell with
#: HTTP 200), so the index page is the only reliable entry point and HTTP
#: status alone must never be trusted as proof a document exists.
PPAC_INDEX_URL = "https://ppac.gov.in/"
PPAC_SOURCE = "vendor:ppac_gas_notification"
PPAC_LICENSE = (
    "PPAC public notification (Govt. of India). Cite PPAC; review before "
    "redistribution."
)

#: Filename discriminators for the APM gas-price notification. Kept as data so
#: an operator can widen the net without editing logic.
PPAC_DOC_PATTERN = re.compile(
    r"(?:domestic[_\s-]*natural[_\s-]*gas[_\s-]*price|apm[_\s-]*gas)", re.I
)

DEFAULT_CACHE_DIRNAME = "factor_cache"

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


# ---------------------------------------------------------------------------
# The series this module can load, as spine registry entries.
#
# ``LOADER_SERIES_REGISTRY`` is validated against
# ``factor_spine._validate_registry_entry`` by the test suite, so a field
# rename in the spine fails here at import-of-test time rather than at the
# first real load.
#
# Sources use the ``vendor:<name>`` escape hatch
# (``_validate_registry_entry``: ALLOWED_SOURCES or a ``vendor:`` prefix),
# because the Pink Sheet and PPAC are neither Indian statutory publishers nor
# the "manual"/"fixture" buckets the spine's built-in vocabulary names.
# ---------------------------------------------------------------------------
LOADER_SERIES_REGISTRY: Tuple[Dict[str, Any], ...] = (
    dict(
        factor_key="WB.CRUDE_OIL_AVG",
        display_name="Crude oil, average (World Bank Pink Sheet)",
        family="crude_energy",
        unit="usd_per_bbl",
        frequency="monthly",
        value_semantics="level",
        source=WB_SOURCE,
        source_url=WB_LANDING_URL,
        license=WB_LICENSE,
        current_status="active",
        aggregation_policy="last",
        max_lookback_days=400,
        expected_publication_lag_days=45,
        is_point_in_time=1,
        availability_contract="pita_strict",
        methodology_notes=(
            "Monthly average crude oil price, US$/bbl, nominal. The workbook's "
            "own 'Updated on <date>' cell is the as_of_date for every row in "
            "the file: a single publication date governs the whole table, "
            "because the Pink Sheet restates history in place."
        ),
    ),
    dict(
        factor_key="WB.CRUDE_OIL_BRENT",
        display_name="Crude oil, Brent (World Bank Pink Sheet)",
        family="crude_energy",
        unit="usd_per_bbl",
        frequency="monthly",
        value_semantics="level",
        source=WB_SOURCE,
        source_url=WB_LANDING_URL,
        license=WB_LICENSE,
        current_status="active",
        aggregation_policy="last",
        max_lookback_days=400,
        expected_publication_lag_days=45,
        is_point_in_time=1,
        availability_contract="pita_strict",
        methodology_notes="Monthly Brent crude, US$/bbl, nominal. See WB.CRUDE_OIL_AVG.",
    ),
    dict(
        factor_key="WB.NATURAL_GAS_US",
        display_name="Natural gas, US (World Bank Pink Sheet)",
        family="crude_energy",
        unit="usd_per_mmbtu",
        frequency="monthly",
        value_semantics="level",
        source=WB_SOURCE,
        source_url=WB_LANDING_URL,
        license=WB_LICENSE,
        current_status="active",
        aggregation_policy="last",
        max_lookback_days=400,
        expected_publication_lag_days=45,
        is_point_in_time=1,
        availability_contract="pita_strict",
        methodology_notes="Henry Hub benchmark, US$/mmbtu, monthly nominal. See WB.CRUDE_OIL_AVG.",
    ),
    dict(
        factor_key="WB.COAL_AUSTRALIAN",
        display_name="Coal, Australian (World Bank Pink Sheet)",
        family="crude_energy",
        unit="usd_per_metric_tonne",
        frequency="monthly",
        value_semantics="level",
        source=WB_SOURCE,
        source_url=WB_LANDING_URL,
        license=WB_LICENSE,
        current_status="active",
        aggregation_policy="last",
        max_lookback_days=400,
        expected_publication_lag_days=45,
        is_point_in_time=1,
        availability_contract="pita_strict",
        methodology_notes="Australian thermal coal, US$/metric tonne, monthly nominal. See WB.CRUDE_OIL_AVG.",
    ),
    dict(
        factor_key="WB.IRON_ORE",
        display_name="Iron ore, cfr spot (World Bank Pink Sheet)",
        family="metals",
        unit="usd_per_dmtu",
        frequency="monthly",
        value_semantics="level",
        source=WB_SOURCE,
        source_url=WB_LANDING_URL,
        license=WB_LICENSE,
        current_status="active",
        aggregation_policy="last",
        max_lookback_days=400,
        expected_publication_lag_days=45,
        is_point_in_time=1,
        availability_contract="pita_strict",
        methodology_notes="Iron ore cfr spot, US$/dmtu, monthly nominal. See WB.CRUDE_OIL_AVG.",
    ),
    dict(
        factor_key="IN.PPAC.GAS_APM",
        display_name="Domestic APM natural gas price (PPAC notification)",
        family="crude_energy",
        unit="usd_per_mmbtu",
        frequency="monthly",
        value_semantics="level",
        source=PPAC_SOURCE,
        source_url=PPAC_INDEX_URL,
        license=PPAC_LICENSE,
        current_status="active",
        aggregation_policy="last",
        max_lookback_days=400,
        expected_publication_lag_days=35,
        # The notification's 'Dated:' line is recovered by OCR, and when OCR is
        # unavailable the date falls back to the filename's Unix-epoch upload
        # prefix. That fallback is INFERRED, and design §1.4 makes
        # is_point_in_time a property of the SERIES (uniformly trustworthy or
        # uniformly estimated) — so the whole series is labelled, not just the
        # rows that happened to need the fallback.
        is_point_in_time=0,
        availability_contract="pita_estimated",
        methodology_notes=(
            "APM (domestic natural gas) price notified by MoPNG via PPAC for a "
            "calendar month, US$/mmbtu on GCV basis. as_of_date is the "
            "notification's own 'Dated:' line when OCR recovers it, else the "
            "Unix-epoch upload prefix in the filename (INFERRED). Value is "
            "taken from the 'notified as US$ X/MMBTU' sentence only; the "
            "separate ONGC/OIL nomination-field CEILING price in the same "
            "document is a different number and is never substituted."
        ),
    ),
)

LOADER_SERIES_KEYS: Tuple[str, ...] = tuple(e["factor_key"] for e in LOADER_SERIES_REGISTRY)
_REGISTRY_BY_KEY: Dict[str, Dict[str, Any]] = {e["factor_key"]: e for e in LOADER_SERIES_REGISTRY}

#: Which Pink Sheet column backs which series. Resolved by *header text*, not
#: by column letter: the Pink Sheet inserts and reorders columns between
#: publications, so a hardcoded 'B' would silently start meaning something
#: else. Matched against a normalised form of the header cell
#: (:func:`_normalise_header`).
WB_COLUMN_MATCHERS: Tuple[Tuple[str, str], ...] = (
    ("WB.CRUDE_OIL_AVG", "crude_oil_average"),
    ("WB.CRUDE_OIL_BRENT", "crude_oil_brent"),
    ("WB.NATURAL_GAS_US", "natural_gas_us"),
    ("WB.COAL_AUSTRALIAN", "coal_australian"),
    ("WB.IRON_ORE", "iron_ore_cfr_spot"),
)

#: The Pink Sheet column-backed series, as factor_keys. Split out so
#: ``_world_bank_observations`` does not re-derive it per call.
WB_SERIES_KEYS: Tuple[str, ...] = tuple(k for k, _ in WB_COLUMN_MATCHERS)

#: The one PPAC series the notification path can produce. Named as a constant
#: rather than a bare string so the reachability check below and
#: ``_ppac_observations`` cannot drift apart.
PPAC_SERIES_KEY: str = "IN.PPAC.GAS_APM"


def validate_loader_registry(entries: Sequence[Dict[str, Any]] = LOADER_SERIES_REGISTRY) -> int:
    """Validate this module's registry against the spine's own contract.

    Every entry is run through ``factor_spine._validate_registry_entry`` — the
    *same* function ``register_series`` applies — so a spine-side field rename
    or vocabulary change fails here, in one place, instead of at the first real
    load. The file header's claim that "the test suite validates the registry"
    is only true if a function like this exists; it does, and the test suite
    calls it.

    It also checks the two loader-local invariants the spine cannot see:

    * every Pink Sheet column matcher names a registered series (otherwise a
      matched column is written to a series that does not exist), and
    * every registered series is reachable from a source (a series no source
      can produce is a promise this module cannot keep).

    Returns the number of entries validated; raises ``ValueError`` on the first
    violation.
    """
    for entry in entries:
        _validate_registry_entry(entry)
    keys = {str(e.get("factor_key")) for e in entries}
    for key, _normalised in WB_COLUMN_MATCHERS:
        if key not in keys:
            raise ValueError(
                f"WB_COLUMN_MATCHERS names {key!r}, which is not in the loader registry"
            )
    for key in sorted(keys):
        if key not in WB_SERIES_KEYS and key != PPAC_SERIES_KEY:
            raise ValueError(f"{key}: registered but no loader source can produce it")
    return len(entries)


#: Eagerly validated at import so a registry/spine contract break is a loud
#: import error, not a silent failure three sources later.
LOADER_REGISTRY_VALIDATED: int = validate_loader_registry()



# ---------------------------------------------------------------------------
# Small shared helpers
# ---------------------------------------------------------------------------
def _now_iso() -> str:
    """Fetch-time stamp. The ONLY clock read in this module's load path.

    Goes to ``retrieved_at`` and nowhere else. Design R3: ``retrieved_at`` is
    a property of *us*; ``as_of_date`` is a property of the *world* and must
    come from the source document.
    """
    return datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")


def _today_iso() -> str:
    """Today's date, used ONLY as a refusal guard (never as a knowledge date)."""
    return datetime.now(IST).date().isoformat()


def _default_cache_dir() -> Path:
    try:
        from reality_engine import config

        return Path(config.DATA_DIR) / DEFAULT_CACHE_DIRNAME
    except Exception:  # pragma: no cover - config is importable in practice
        import tempfile

        return Path(tempfile.gettempdir()) / DEFAULT_CACHE_DIRNAME


def _resolve_cache_dir(cache_dir: Optional[str]) -> Path:
    path = Path(cache_dir) if cache_dir else _default_cache_dir()
    path.mkdir(parents=True, exist_ok=True)
    return path


def _cache_file(cache_dir: Optional[str], url: str, suffix: str) -> Path:
    """Content-addressed cache path. The hash keeps a 2024 doc-id URL and its
    2026 replacement in different files instead of overwriting each other."""
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
    return _resolve_cache_dir(cache_dir) / f"{digest}{suffix}"


def _http_get(url: str, *, timeout: int = 120, attempts: int = 2,
              accept: str = "*/*", referer: Optional[str] = None) -> bytes:
    """GET with a minimal browser-shaped header set and one retry.

    Raises on failure; every caller converts that into a ``status='failed'``
    record rather than letting it escape into the pipeline (design §4.1).
    """
    headers = {
        "User-Agent": _USER_AGENT,
        "Accept": accept,
        "Accept-Language": "en-US,en;q=0.9",
    }
    if referer:
        headers["Referer"] = referer
    last: Optional[Exception] = None
    for attempt in range(attempts):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except (urllib.error.URLError, urllib.error.HTTPError, OSError) as exc:
            last = exc
            if attempt + 1 < attempts:
                time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"GET failed after {attempts} attempt(s): {url} ({last})")


def _fetch_cached(url: str, path: Path, *, timeout: int, force_refresh: bool,
                  accept: str, referer: Optional[str]) -> Tuple[bytes, bool]:
    """Return ``(payload, from_cache)``. A cached payload is reused by default.

    Reuse is safe precisely because ``as_of_date`` travels *with* the bytes: a
    cached workbook still reports its own 'Updated on ...' date, so a stale
    cache produces an honestly older spine, never a falsely current one.
    """
    if not force_refresh and path.exists() and path.stat().st_size > 0:
        return path.read_bytes(), True
    payload = _http_get(url, timeout=timeout, accept=accept, referer=referer)
    tmp = path.with_suffix(path.suffix + ".part")
    tmp.write_bytes(payload)
    os.replace(tmp, path)
    return payload, False


def _is_number(text: str) -> bool:
    try:
        float(text)
        return True
    except (TypeError, ValueError):
        return False


#: Cell sentinels the Pink Sheet uses for "no observation this month". They
#: are TEXT in a numeric column, which is exactly why a naive float() cast
#: either crashes or, worse, coerces them to 0.0. Every one of these becomes
#: an honest NULL.
_MISSING_CELL_SENTINELS = frozenset(
    {"", "-", "--", "...", "\ufffd", "\ufffe", "n/a", "na", "nan", "null", "none"}
)


def _to_float(text: Optional[str]) -> Optional[float]:
    """Parse a Pink Sheet cell. Non-numeric, sentinel, and blank all become
    None — a *missing* observation, never a zero and never a carry-forward."""
    if text is None:
        return None
    s = str(text).strip()
    if s.lower() in _MISSING_CELL_SENTINELS:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _normalise_header(text: str) -> str:
    """``'Iron ore, cfr spot'`` -> ``'iron_ore_cfr_spot'``.

    Footnote markers (``'Coal, South African **'``) and stray punctuation are
    removed so a series matcher keeps working when the publisher adds a note.
    """
    s = str(text).replace("*", " ").lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_")


def _month_bounds(period: str) -> Optional[Tuple[str, str]]:
    """``'1960M01'`` -> ``('1960-01-01', '1960-01-31')``.

    Returns None for anything that is not a ``YYYYMmm`` period label. A month
    label is the *measured period*, never the knowledge date; conflating the
    two is design R2's bug.
    """
    m = re.match(r"^(\d{4})[Mm](\d{1,2})$", str(period).strip())
    if not m:
        return None
    year, month = int(m.group(1)), int(m.group(2))
    if not 1 <= month <= 12:
        return None
    last = calendar.monthrange(year, month)[1]
    return f"{year:04d}-{month:02d}-01", f"{year:04d}-{month:02d}-{last:02d}"


# ---------------------------------------------------------------------------
# Tolerant date parsing. Every pattern here has been checked against the live
# "Updated on <Month DD, YYYY>" cell; the alternates exist because publishers
# reformat, and a date parser that only accepts one spelling turns a formatting
# change into a silent loss of the knowledge date.
# ---------------------------------------------------------------------------
_MONTHS = {
    m.lower(): i
    for i, m in enumerate(
        ["January", "February", "March", "April", "May", "June", "July",
         "August", "September", "October", "November", "December"], start=1)
}
_MONTHS.update({
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
})

#: ``Updated on`` is matched case-insensitively and tolerates the variants the
#: publisher has shipped: "Updated on", "Last Updated On", "Updated:" (no 'on'),
#: and "Data updated on".
_UPDATED_ON_RE = re.compile(
    r"(?i)\b(?:last\s+|data\s+)?updated\s*(?:on|:)\s*"
    r"([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})"
)
_UPDATED_ON_DMY_RE = re.compile(
    r"(?i)\b(?:last\s+|data\s+)?updated\s*(?:on|:)\s*"
    r"(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]{3,9})\.?,?\s+(\d{4})"
)
_UPDATED_ON_NUMERIC_RE = re.compile(
    r"(?i)\b(?:last\s+|data\s+)?updated\s*(?:on|:)\s*"
    r"(\d{1,2})[./-](\d{1,2})[./-](\d{4})"
)


def _mk_iso(year: int, month: int, day: int) -> Optional[str]:
    if not 1 <= month <= 12 or not 1 <= day <= 31:
        return None
    try:
        last = calendar.monthrange(year, month)[1]
    except (ValueError, calendar.IllegalMonthError):
        return None
    if day > last:
        return None
    return f"{year:04d}-{month:02d}-{day:02d}"


def parse_updated_on(text: Optional[str]) -> Optional[str]:
    """Extract an ISO date from a ``'Updated on ...'`` string.

    Returns ``None`` when nothing date-like is present. ``None`` is the
    load-blocking answer: the caller must refuse the load rather than fall
    back to the system clock, because a fallback to today is precisely the
    look-ahead this module is built to prevent.
    """
    if not text:
        return None
    blob = str(text)
    m = _UPDATED_ON_RE.search(blob)
    if m:
        month = _MONTHS.get(m.group(1).lower())
        if month:
            got = _mk_iso(int(m.group(3)), month, int(m.group(2)))
            if got:
                return got
    m = _UPDATED_ON_DMY_RE.search(blob)
    if m:
        month = _MONTHS.get(m.group(2).lower())
        if month:
            got = _mk_iso(int(m.group(3)), month, int(m.group(1)))
            if got:
                return got
    m = _UPDATED_ON_NUMERIC_RE.search(blob)
    if m:
        got = _mk_iso(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        if got:
            return got
    return None


def parse_dated_field(text: Optional[str]) -> Optional[str]:
    """Parse a bare ``'31.08.2026'`` / ``'31-08-2026'`` / ``'2026-08-31'``.

    Used for PPAC's ``Dated:`` line, which has no 'Updated on' prefix. The
    ``Updated on`` patterns are tried first so a string carrying both is
    resolved by its explicit publication marker.
    """
    if not text:
        return None
    blob = str(text)
    iso = parse_updated_on(blob)
    if iso:
        return iso
    m = re.search(r"(?i)\bdated\s*[::]\s*(\d{1,2})[./-](\d{1,2})[./-](\d{4})", blob)
    if m:
        got = _mk_iso(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        if got:
            return got
    m = re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", blob)
    if m:
        return _mk_iso(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return None


# ===========================================================================
# XLSX — stdlib only (zipfile + xml.etree). No openpyxl, no pandas.
# ===========================================================================
_NS_MAIN = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_NS_DOCREL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_NS_PKGREL = "{http://schemas.openxmlformats.org/package/2006/relationships}"

_CELL_REF_RE = re.compile(r"^([A-Z]+)(\d+)$")
_PERIOD_CELL = "A"
_PERIOD_RE = re.compile(r"^\d{4}[Mm]\d{1,2}$")


def _col_letters(ref: str) -> Tuple[str, int]:
    m = _CELL_REF_RE.match(str(ref or ""))
    return (m.group(1), int(m.group(2))) if m else ("", 0)


def _col_index(letters: str) -> int:
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch) - 64)
    return n


def _col_name(index: int) -> str:
    name = ""
    while index > 0:
        index, rem = divmod(index - 1, 26)
        name = chr(65 + rem) + name
    return name


def _read_shared_strings(zf: zipfile.ZipFile) -> List[str]:
    """Read ``xl/sharedStrings.xml`` if present. Absent is legal (inline-only
    workbooks) and yields an empty table, not an error."""
    if "xl/sharedStrings.xml" not in zf.namelist():
        return []
    root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
    out: List[str] = []
    for si in root:
        out.append("".join(t.text or "" for t in si.iter(f"{_NS_MAIN}t")))
    return out


def list_sheet_parts(zf: zipfile.ZipFile) -> List[Tuple[str, str]]:
    """``[(sheet_name, zip_part), ...]`` in workbook order, resolved via rels."""
    wb = ET.fromstring(zf.read("xl/workbook.xml"))
    rels: Dict[str, str] = {}
    if "xl/_rels/workbook.xml.rels" in zf.namelist():
        for rel in ET.fromstring(zf.read("xl/_rels/workbook.xml.rels")):
            rels[rel.get("Id") or ""] = rel.get("Target") or ""
    out: List[Tuple[str, str]] = []
    sheets = wb.find(f"{_NS_MAIN}sheets")
    for sh in (sheets if sheets is not None else []):
        rid = sh.get(f"{_NS_DOCREL}id")
        target = rels.get(rid or "", "")
        out.append((sh.get("name") or "", _normalise_part(target)))
    return out


def _normalise_part(target: str) -> str:
    """rels targets are workbook-relative and may be absolute or use '..'."""
    if not target:
        return ""
    if target.startswith("/"):
        return target.lstrip("/")
    joined = os.path.normpath(os.path.join("xl", target)).replace("\\", "/")
    return joined


def resolve_sheet_part(zf: zipfile.ZipFile, sheet_name: str) -> str:
    """Return the zip part path for ``sheet_name``.

    THE fix for the silent-wrong-table defect. ``sheet1.xml`` is *not*
    "the first sheet's data" in any meaningful sense — it is whatever part the
    rels happen to bind first, and in the Pink Sheet that is the
    "Mismatch Details" diagnostic table. Resolution is by NAME, through
    ``xl/_rels/workbook.xml.rels``.
    """
    for name, part in list_sheet_parts(zf):
        if name.strip().lower() == sheet_name.strip().lower():
            if part and part in zf.namelist():
                return part
    raise KeyError(
        f"worksheet {sheet_name!r} not found; workbook sheets = "
        f"{[n for n, _ in list_sheet_parts(zf)]}"
    )


def read_sheet_rows(zf: zipfile.ZipFile, part: str) -> Dict[int, Dict[int, str]]:
    """``{row_number: {col_index: raw_cell_text}}`` for one worksheet part.

    Handles every cell type the spec allows: shared (``t='s'``), inline
    (``t='inlineStr'``), formula result (``t='str'``), number (no ``t``) and
    boolean. A styled-but-empty cell carries no ``<v>`` and becomes ``''``.
    """
    shared = _read_shared_strings(zf)
    root = ET.fromstring(zf.read(part))
    rows: Dict[int, Dict[int, str]] = {}
    for c in root.iter(f"{_NS_MAIN}c"):
        letters, rownum = _col_letters(c.get("r") or "")
        if not letters:
            continue
        ctype = c.get("t")
        v = c.find(f"{_NS_MAIN}v")
        if ctype == "s":
            if v is not None and v.text is not None:
                try:
                    text = shared[int(v.text)]
                except (ValueError, IndexError):
                    text = ""
            else:
                text = ""
        elif ctype == "inlineStr":
            is_el = c.find(f"{_NS_MAIN}is")
            text = "".join(t.text or "" for t in is_el.iter(f"{_NS_MAIN}t")) if is_el is not None else ""
        elif ctype == "b":
            text = (v.text or "") if v is not None else ""
        else:
            text = (v.text or "") if v is not None else ""
        rows.setdefault(rownum, {})[_col_index(letters)] = text
    return rows


def _ranked_header_rows(rows: Dict[int, Dict[int, str]]) -> List[int]:
    """Candidate header rows, best first.

    The header is the pre-data row carrying the most non-empty TEXT cells.
    Two subtleties, both verified against the live file:

    * The scan STOPS at the first row whose period-column cell parses as a
      ``YYYYMmm`` label — that is the first data row, so nothing after it can
      be a header.
    * In the real workbook the names row (5) and the units row (6) *tie* at 71
      text cells. A strict ``>`` keeps the FIRST row to reach the maximum, so
      the labels row wins and the units row never displaces it. (They also
      differ in kind — units are parenthesised like ``($/bbl)`` — but relying
      on that would be a guess, whereas "the upper row wins a tie" is a
      property of the layout that the caller can fall through if the tie ever
      resolves the other way.)
    """
    period_col = _col_index(_PERIOD_CELL)
    best: List[Tuple[int, int]] = []
    for rownum in sorted(rows):
        if rownum <= 1:
            continue
        cells = rows[rownum]
        label = (cells.get(period_col) or "").strip()
        if _PERIOD_RE.match(label):
            break  # first data row; the header search ends here
        score = sum(1 for text in cells.values() if text.strip() and not _is_number(text))
        if score:
            best.append((score, rownum))
    best.sort(key=lambda pair: (-pair[0], pair[1]))
    return [rownum for _score, rownum in best]


def _find_as_of_date(rows: Dict[int, Dict[int, str]]) -> Optional[str]:
    """Scan the whole sheet's column A for an 'Updated on ...' string.

    Returned verbatim from the file. The system clock is never a candidate.
    """
    for rownum in sorted(rows):
        text = (rows[rownum].get(_col_index(_PERIOD_CELL)) or "").strip()
        if re.search(r"(?i)updated", text):
            found = parse_updated_on(text)
            if found:
                return found
    return None


def parse_world_bank_pink_sheet(
    payload: bytes,
    sheet_name: str = WB_SHEET_NAME,
    matchers: Sequence[Tuple[str, str]] = WB_COLUMN_MATCHERS,
) -> Dict[str, Any]:
    """Parse a Pink Sheet workbook into per-period, per-series values.

    Pure function of ``payload`` — no clock, no network, no DB. That is what
    makes it directly testable against a hand-built fixture, and it is why
    ``as_of_date`` can be asserted to come from the file.

    Returns a dict with ``status``, ``as_of_date`` (``None`` when the file does
    not state one), ``sheet_part``, ``column_map``, ``rows`` and ``units``.
    """
    try:
        zf = zipfile.ZipFile(io.BytesIO(payload))
    except (zipfile.BadZipFile, OSError) as exc:
        return {"status": "failed", "reason": f"not a readable xlsx: {exc}",
                "as_of_date": None, "rows": [], "column_map": {}}

    try:
        part = resolve_sheet_part(zf, sheet_name)
    except (KeyError, ET.ParseError, OSError) as exc:
        return {"status": "failed", "reason": str(exc),
                "as_of_date": None, "rows": [], "column_map": {}}

    try:
        rows = read_sheet_rows(zf, part)
    except (ET.ParseError, OSError, KeyError) as exc:
        return {"status": "failed", "reason": f"unreadable sheet {part}: {exc}",
                "as_of_date": None, "sheet_part": part, "rows": [], "column_map": {}}

    as_of_date = _find_as_of_date(rows)
    period_col = _col_index(_PERIOD_CELL)

    # Try each candidate header row in preference order and take the first that
    # actually yields a series column. Falling through means a future layout
    # change produces "no columns matched" (loud) rather than a plausible set
    # of wrong columns (silent).
    column_map: Dict[str, int] = {}
    units: Dict[str, str] = {}
    header_row: Optional[int] = None
    wanted = {normalised: key for key, normalised in matchers}
    for candidate in _ranked_header_rows(rows):
        cells = rows.get(candidate, {})
        found: Dict[str, int] = {}
        for col_idx, raw in cells.items():
            key = wanted.get(_normalise_header(raw))
            if key and key not in found:
                found[key] = col_idx
        if found:
            column_map, header_row = found, candidate
            break
        # NOTE: no per-candidate `units` capture here. A previous version of
        # this loop carried one, iterating `column_map` while still inside the
        # candidate scan — and `column_map` is only ever assigned on the
        # `if found: break` path, so it was `{}` at that point and the block
        # assigned an empty dict, i.e. it was dead code wearing the costume of
        # a fallback. Units are taken once, after the scan wins, from the row
        # beneath the winning header (the real workbook's row 6).
    if not column_map:
        return {
            "status": "failed",
            "reason": (
                f"no series column matched in sheet {part!r} "
                f"(expected one of {[n for _k, n in matchers]}); the layout "
                f"changed and this parser must be re-pointed deliberately"
            ),
            "as_of_date": as_of_date,
            "sheet_part": part,
            "column_map": {},
            "rows": [],
        }

    # Units live on the row DIRECTLY beneath the winning header (row 6 under
    # the real workbook's row-5 labels). Skip fully-blank rows so a stray
    # spacer cannot silently blank every unit.
    unit_row = next(
        (r for r in sorted(rows)
         if r > (header_row or 0)
         and any((rows[r].get(col_idx) or "").strip() for col_idx in column_map.values())),
        None,
    )
    if unit_row is not None:
        unit_cells = rows.get(unit_row, {})
        units = {key: (unit_cells.get(col_idx) or "").strip()
                 for key, col_idx in column_map.items()}

    data_row = min((r for r in rows if r > (header_row or 0)
                    and _PERIOD_RE.match((rows[r].get(period_col) or "").strip())),
                   default=None)
    parsed: List[Dict[str, Any]] = []
    if data_row is not None:
        for rownum in sorted(r for r in rows if r >= data_row):
            cells = rows[rownum]
            period = (cells.get(period_col) or "").strip()
            if not _PERIOD_RE.match(period):
                continue
            bounds = _month_bounds(period)
            if not bounds:
                continue
            values = {key: _to_float(cells.get(col_idx)) for key, col_idx in column_map.items()}
            parsed.append({
                "period": period,
                "period_start": bounds[0],
                "period_end": bounds[1],
                "values": values,
                "n_null": sum(1 for v in values.values() if v is None),
            })

    return {
        "status": "ok" if parsed else "failed",
        "reason": None if parsed else f"no {sheet_name!r} data rows found in {part}",
        "as_of_date": as_of_date,
        "sheet_part": part,
        "sheet_name": sheet_name,
        "header_row": header_row,
        "data_first_row": data_row,
        "column_map": column_map,
        "units": units,
        "rows": parsed,
        "n_rows": len(parsed),
    }


def resolve_pink_sheet_url(html: str, base_url: str = WB_LANDING_URL) -> Optional[str]:
    """Find the live monthly-history xlsx link in the landing page HTML.

    The download URL is content-addressed and changes with every publication,
    so it is resolved at fetch time and never hardcoded. A stale hardcoded URL
    ends at 2024M12 and produces a spine that is quietly two years stale.
    """
    best: Optional[str] = None
    for m in re.finditer(
        r"""(?i)(?:href|src)\s*=\s*["']([^"']*CMO-Historical-Data-Monthly\.xlsx[^"']*)["']""",
        html or "",
    ):
        candidate = urllib.parse.urljoin(base_url, m.group(1).strip())
        if candidate.lower().endswith(".xlsx"):
            best = candidate
    if best is None:
        for m in re.finditer(r"""(?i)(https?://[^"'<>\s]*CMO-Historical-Data-Monthly\.xlsx)""",
                             html or ""):
            best = m.group(1)
    return best


def fetch_world_bank_pink_sheet(
    cache_dir: Optional[str] = None,
    *,
    force_refresh: bool = False,
    timeout: int = 180,
    landing_url: str = WB_LANDING_URL,
) -> Dict[str, Any]:
    """Resolve, download and parse the live World Bank Pink Sheet.

    Never raises: an unreachable source returns
    ``{'status': 'failed', 'reason': ...}`` (design §4.1).

    ``as_of_date`` in the result is the workbook's own ``'Updated on ...'``
    cell. If the file does not carry one, ``as_of_date`` is ``None`` and
    ``load_series`` refuses the load — it is never replaced with today's date.
    """
    retrieved_at = _now_iso()
    landing_path = _cache_file(cache_dir, landing_url, ".html")
    try:
        html_bytes, from_cache = _fetch_cached(
            landing_url, landing_path, timeout=min(timeout, 60),
            force_refresh=force_refresh, accept="text/html,*/*;q=0.8", referer=None,
        )
    except Exception as exc:
        return {"status": "failed", "source": WB_SOURCE,
                "reason": f"landing page unreachable: {exc}",
                "as_of_date": None, "source_url": None, "rows": [],
                "retrieved_at": retrieved_at}

    html = html_bytes.decode("utf-8", "replace")
    url = resolve_pink_sheet_url(html, landing_url)
    if not url:
        return {"status": "failed", "source": WB_SOURCE,
                "reason": f"no {WB_SHEET_NAME!r} xlsx link found on {landing_url}",
                "as_of_date": None, "source_url": None, "rows": [],
                "retrieved_at": retrieved_at}

    xlsx_path = _cache_file(cache_dir, url, ".xlsx")
    try:
        payload, xlsx_from_cache = _fetch_cached(
            url, xlsx_path, timeout=timeout, force_refresh=force_refresh,
            accept="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,*/*",
            referer=landing_url,
        )
    except Exception as exc:
        return {"status": "failed", "source": WB_SOURCE,
                "reason": f"workbook download failed: {exc}",
                "as_of_date": None, "source_url": url, "rows": [],
                "retrieved_at": retrieved_at}

    parsed = parse_world_bank_pink_sheet(payload)
    parsed.update({
        "source": WB_SOURCE,
        "source_url": url,
        "landing_url": landing_url,
        "retrieved_at": retrieved_at,
        "bytes": len(payload),
        "from_cache": xlsx_from_cache,
        "landing_from_cache": from_cache,
    })
    if parsed["status"] == "ok" and not parsed.get("as_of_date"):
        parsed["status"] = "refused"
        parsed["reason"] = (
            "workbook carries no 'Updated on <date>' stamp; as_of_date is "
            "unknown, and substituting today would be a look-ahead"
        )
    return parsed


# ===========================================================================
# PPAC — image-only PDFs. Three extraction tiers, honestly reported.
# ===========================================================================
#: Tier 1, the PDF's own text layer. Returns '' for a scan.
_PdfTextFn = Callable[[bytes], str]
#: Tier 2, rasterise page 1 and OCR it with the repo's engine.
_OcrFn = Callable[[bytes], Tuple[str, str]]

EXTRACTION_TEXT_LAYER = "pdf_text_layer"
EXTRACTION_OCR = "rasterize_then_ocr"
EXTRACTION_NONE = "no_text_recovered"

#: A text layer shorter than this is treated as absent. Scans return '' or a
#: stray fragment; a real text layer is hundreds of characters. Defined HERE,
#: above :func:`extract_pdf_text`, because the ladder reads it at call time and
#: a constant that first appears *after* its use reads as a name that only
#: exists on some import orders.
_MIN_TEXT_LAYER_CHARS = 40


def _fitz_page_text(payload: bytes, page: int = 0) -> str:
    """Tier 1. ``fitz`` (PyMuPDF) is imported HERE, not at module scope:
    ``requirements.txt:29`` has it commented out, so a top-level import would
    make this file unimportable wherever PyMuPDF is absent."""
    import fitz  # noqa: PLC0415  (deliberately deferred; see requirements.txt:29)

    with fitz.open(stream=payload, filetype="pdf") as doc:
        if page >= doc.page_count:
            return ""
        return doc[page].get_text() or ""


def _fitz_rasterize_ocr(payload: bytes, dpi: int = 200, page: int = 0) -> Tuple[str, str]:
    """Tier 2. Rasterise page 1 to a pixmap, OCR the image.

    This is the route the PPAC scan actually needs: measured on the live
    "Domestic Natural Gas Price for Sep-2026" notification, the text layer
    returns **0 characters** (one embedded image, no OCR text object) while
    rasterising at 200 dpi and running the repo's ``FinancialOCREngine``
    recovers the full notification in ~1.7 s at 0.98 mean confidence,
    including the ``Dated:`` line and the ``USS 9.00/MMBTU`` price.

    Returns ``(text, tier_name)``.
    """
    import fitz  # noqa: PLC0415  (deferred, as above)

    from reality_engine.processing.ocr_engine import FinancialOCREngine  # noqa: PLC0415

    with fitz.open(stream=payload, filetype="pdf") as doc:
        if page >= doc.page_count:
            return "", ""
        pixmap = doc[page].get_pixmap(dpi=dpi)
        png = pixmap.tobytes("png")
    result = FinancialOCREngine().process_image(png)
    return str(result.get("raw_text") or ""), EXTRACTION_OCR


def extract_pdf_text(payload: bytes, *, text_fn: Optional[_PdfTextFn] = None,
                     ocr_fn: Optional[_OcrFn] = None) -> Dict[str, Any]:
    """Run the extraction ladder and REPORT which tier actually worked.

    Tier 1: the PDF's own text layer.
    Tier 2: rasterise page 1, OCR it.
    Tier 3: give up honestly — ``extraction_status`` names the failure and the
    caller stores NULL with that reason. A number is never guessed, and no
    tier is assumed to have worked.

    ``text_fn``/``ocr_fn`` are injection points so the ladder is unit-testable
    without PyMuPDF, ONNX, a GPU, or a network.
    """
    if text_fn is None:
        def text_fn(data: bytes) -> str:  # noqa: ANN001
            return _fitz_page_text(data)

    if ocr_fn is None:
        def ocr_fn(data: bytes) -> Tuple[str, str]:  # noqa: ANN001
            return _fitz_rasterize_ocr(data)

    attempted: List[str] = []
    try:
        tier1 = text_fn(payload) or ""
        attempted.append(EXTRACTION_TEXT_LAYER)
        if len(tier1.strip()) >= _MIN_TEXT_LAYER_CHARS:
            return {"text": tier1, "extraction_status": EXTRACTION_TEXT_LAYER,
                    "tiers_attempted": attempted, "reason": None}
        reason1 = (f"text layer empty or {len(tier1.strip())} chars "
                   f"(below the {_MIN_TEXT_LAYER_CHARS}-char floor)")
    except Exception as exc:
        reason1 = f"text-layer extraction failed: {type(exc).__name__}: {exc}"
        attempted.append(f"{EXTRACTION_TEXT_LAYER}(error)")

    try:
        tier2_text, tier2_name = ocr_fn(payload)
        attempted.append(tier2_name or EXTRACTION_OCR)
        if tier2_text and tier2_text.strip():
            return {"text": tier2_text, "extraction_status": EXTRACTION_OCR,
                    "tiers_attempted": attempted,
                    "reason": f"tier 1 unusable ({reason1}); OCR used instead"}
    except Exception as exc:
        attempted.append(f"{EXTRACTION_OCR}(error)")
        reason2 = f"rasterize+OCR failed: {type(exc).__name__}: {exc}"
        return {"text": "", "extraction_status": EXTRACTION_NONE,
                "tiers_attempted": attempted,
                "reason": f"tier 1 unusable ({reason1}); tier 2 failed ({reason2})"}

    return {"text": "", "extraction_status": EXTRACTION_NONE,
            "tiers_attempted": attempted,
            "reason": f"tier 1 unusable ({reason1}); tier 2 returned no text"}


#: An ``href``/``src`` attribute whose value is a ``.pdf`` URL.
_PDF_HREF_RE = re.compile(r"""(?i)(?:href|src)\s*=\s*["']([^"']+\.pdf[^"']*)["']""")


def _iter_pdf_href_matches(html: str) -> Iterator[re.Match]:
    """Yield every ``href``/``src`` ``.pdf`` match, raw and entity-decoded.

    Two passes because PPAC's index escapes the query separator as ``&amp;``:
    ``?file=x&amp;y=z`` is invisible to a scan of the raw text, and a
    single-pass version of this that tried to express "scan both" as
    ``re.finditer(pat, html, re.sub('&amp;', '&', html))`` raised
    ``TypeError: unsupported operand type(s) for &: 'str' and 'int'`` on every
    call under Python 3.11+ — the third positional argument of ``finditer``
    is ``flags``, not a second string.
    """
    for text in (html or "", (html or "").replace("&amp;", "&")):
        for m in _PDF_HREF_RE.finditer(text):
            yield m


def discover_ppac_gas_documents(html: str, base_url: str = PPAC_INDEX_URL) -> List[Dict[str, Any]]:
    """Find dated AP(M) gas-price PDF links in an index page.

    Two things this must get right, both verified on the live homepage
    (310 KB, 36 PDF links, 35 carrying an epoch prefix):

    * **De-duplication.** PPAC exposes the same document under both
      ``?file=<path>`` and ``?fileDownload=<path>``, which is where the
      observed 32-links-to-16-documents ratio comes from. Two URLs naming the
      same ``<path>`` are one document.
    * **Repeated uploads.** The same filename appears under two different
      epoch prefixes (e.g. ``1790574117_`` and ``1790573931_`` for one
      daily-price PDF). Deduplicating on the *filename* collapses those too,
      keeping the earliest epoch.

    HTTP 200 is never proof of existence here: every slug under
    ``/page/prices/`` returns the same 38 KB soft-404 shell.
    """
    # Two haystacks (raw + entity-decoded), not one. See
    # :func:`_iter_pdf_href_matches` for why this cannot be a single
    # ``finditer`` call with a substituted string.
    blob = html or ""
    seen: Dict[str, Dict[str, Any]] = {}
    for m in _iter_pdf_href_matches(blob):
        raw = m.group(1).strip()
        absolute = urllib.parse.urljoin(base_url, raw)
        parsed = urllib.parse.urlparse(absolute)
        if parsed.scheme not in ("http", "https"):
            continue
        query = urllib.parse.parse_qs(parsed.query)
        payload = ""
        for param in ("file", "fileDownload", "filedownload", "FILE"):
            if query.get(param):
                payload = query[param][0]
                break
        filename = os.path.basename(payload or parsed.path)
        if not filename.lower().endswith(".pdf"):
            continue
        if not PPAC_DOC_PATTERN.search(filename):
            continue
        epoch = re.match(r"^(\d{10})_", filename)
        # Dedupe on the document, not the URL: the epoch prefix is an upload
        # artefact, and 'file='/'fileDownload=' are two doors to one room.
        dedupe_key = re.sub(r"^\d{10}_", "", filename).lower()
        record = {
            "url": absolute,
            "filename": filename,
            "doc_key": dedupe_key,
            "epoch": int(epoch.group(1)) if epoch else None,
            "epoch_date": _epoch_date(int(epoch.group(1))) if epoch else None,
        }
        prior = seen.get(dedupe_key)
        if prior is None:
            seen[dedupe_key] = record
        elif record["epoch"] and (not prior["epoch"] or record["epoch"] < prior["epoch"]):
            # Same document uploaded twice: keep the EARLIEST upload, because
            # the later prefix is a re-upload and would date the same content
            # later than it became knowable.
            seen[dedupe_key] = record
    return sorted(seen.values(), key=lambda r: (r["epoch"] or 0, r["filename"]))


def _epoch_date(epoch: int) -> Optional[str]:
    """Unix-epoch seconds -> ISO date (UTC).

    Source-derived, not a clock read: the integer comes from the filename.
    It is still an INFERENCE about when the document became public, which is
    why its series is registered ``is_point_in_time=0`` / ``pita_estimated``.
    """
    try:
        return datetime.fromtimestamp(int(epoch), tz=timezone.utc).date().isoformat()
    except (OverflowError, OSError, ValueError, TypeError):
        return None


_PPAC_PRICE_RE = re.compile(
    r"(?i)\bnotified\s+as\b[^0-9]{0,16}?([0-9]+(?:\.[0-9]+)?)\s*/\s*MMBTU"
)
_PPAC_PERIOD_RE = re.compile(
    r"(?i)\bperiod\s+(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)\.?,?\s+(\d{4})"
    r"\s+to\s+(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)\.?,?\s+(\d{4})"
)
_PPAC_FILENAME_PERIOD_RE = re.compile(
    r"(?i)for[_\s-]*([A-Za-z]{3,9})[_\s-]*(\d{4})"
)


def parse_ppac_gas_notification(text: Optional[str], *, filename: str = "") -> Dict[str, Any]:
    """Extract the notified APM price, its period, and its publication date.

    HONESTY CONTRACT: the price is read **only** from the sentence that
    notifies it (``'... is notified as USS 9.00/MMBTU ...'``). The same
    document also states a *ceiling* price for ONGC/OIL nomination fields
    (``'... shall be subject to a ceiling of USS 7.00/MMBTU ...'``), which is
    a different number for a different population of gas. A looser pattern
    would happily return 7.00 as "the APM price" — so the pattern is anchored
    on 'notified as', and the ceiling is extracted separately and labelled.

    ``as_of_date`` prefers the document's own ``Dated:`` line and falls back to
    the filename's epoch prefix, reporting which was used in
    ``as_of_date_source``. The fallback is inferred, never a clock read.
    """
    out: Dict[str, Any] = {
        "value": None,
        "unit": "usd_per_mmbtu",
        "ceiling_value": None,
        "period_start": None,
        "period_end": None,
        "as_of_date": None,
        "as_of_date_source": None,
        "extraction_status": EXTRACTION_NONE,
        "reason": "no text supplied",
    }
    if not text or not text.strip():
        out["reason"] = "no text recovered from the document"
        return out
    out["extraction_status"] = "text_parsed"

    m = _PPAC_PRICE_RE.search(text)
    if m:
        out["value"] = float(m.group(1))
    else:
        out["reason"] = (
            "no 'notified as US$ <n>/MMBTU' sentence found; the value is NULL "
            "rather than guessed (the document's separate ceiling price is not "
            "a substitute)"
        )
    c = re.search(r"(?i)\bceiling\s+of\b[^0-9]{0,16}?([0-9]+(?:\.[0-9]+)?)\s*/\s*MMBTU", text)
    if c:
        out["ceiling_value"] = float(c.group(1))

    p = _PPAC_PERIOD_RE.search(text)
    if p:
        # Six capture groups, in document order:
        #   1=day1 2=month1 3=year1 | 4=day2 5=month2 6=year2
        # The previous unpacking read groups 2/3/4 and 5/6/7 — every slot
        # after month1 was shifted by one place, and group(7) never existed,
        # so this raised IndexError on every PPAC document that carried a
        # period line. There are six groups, not seven.
        d1, m1, y1 = int(p.group(1)), _MONTHS.get(p.group(2).lower()), int(p.group(3))
        d2, m2, y2 = int(p.group(4)), _MONTHS.get(p.group(5).lower()), int(p.group(6))
        if m1 and m2:
            out["period_start"] = _mk_iso(y1, m1, d1)
            out["period_end"] = _mk_iso(y2, m2, d2)
    if not out["period_start"]:
        fp = _PPAC_FILENAME_PERIOD_RE.search(filename)
        if fp:
            month = _MONTHS.get(fp.group(1).lower())
            if month:
                last = calendar.monthrange(int(fp.group(2)), month)[1]
                out["period_start"] = f"{int(fp.group(2)):04d}-{month:02d}-01"
                out["period_end"] = f"{int(fp.group(2)):04d}-{month:02d}-{last:02d}"
                out["period_source"] = "filename_inferred"
    if not out["period_start"]:
        out["reason"] = (out["reason"] or "") + "; reference period unparseable"

    dated = parse_dated_field(text)
    if dated:
        out["as_of_date"] = dated
        out["as_of_date_source"] = "document_dated_line"
    else:
        ep = re.match(r"^(\d{10})_", filename or "")
        if ep:
            out["as_of_date"] = _epoch_date(int(ep.group(1)))
            out["as_of_date_source"] = "filename_epoch_inferred"
        if not out["as_of_date"]:
            out["reason"] = (out["reason"] or "") + \
                "; no publication date recoverable from the document or filename"
    return out


def fetch_ppac_gas_prices(
    cache_dir: Optional[str] = None,
    *,
    force_refresh: bool = False,
    timeout: int = 180,
    index_url: str = PPAC_INDEX_URL,
    max_documents: int = 4,
    download: bool = True,
    text_fn: Optional[_PdfTextFn] = None,
    ocr_fn: Optional[_OcrFn] = None,
) -> Dict[str, Any]:
    """Discover, de-duplicate, download and extract the PPAC APM gas notification.

    Never raises. ``extraction_status`` on each document says which of the
    three tiers produced text (``pdf_text_layer`` / ``rasterize_then_ocr`` /
    ``no_text_recovered``) and ``reason`` says why a lower tier won. If no
    tier works the observation is an honest NULL — a missing number is a
    reportable state, and inventing one is not.
    """
    retrieved_at = _now_iso()
    report: Dict[str, Any] = {
        "status": "failed",
        "source": PPAC_SOURCE,
        "source_url": index_url,
        "retrieved_at": retrieved_at,
        "as_of_date": None,
        "documents": [],
        "n_links_seen": 0,
        "reason": None,
    }

    index_path = _cache_file(cache_dir, index_url, ".html")
    try:
        html_bytes, _from_cache = _fetch_cached(
            index_url, index_path, timeout=min(timeout, 60),
            force_refresh=force_refresh, accept="text/html,*/*;q=0.8", referer=None,
        )
    except Exception as exc:
        report["reason"] = f"PPAC index unreachable: {exc}"
        return report

    docs = discover_ppac_gas_documents(html_bytes.decode("utf-8", "replace"), index_url)
    report["n_documents_discovered"] = len(docs)
    if not docs:
        report["reason"] = (
            f"no AP(M) gas-price PDF link found on {index_url}; the page layout "
            f"or filename convention changed"
        )
        return report
    # Newest first: the loader wants the most recent notification, and PPAC
    # re-uploads older ones under fresh epoch prefixes.
    docs = sorted(docs, key=lambda d: (d["epoch"] or 0), reverse=True)[:max_documents]

    for doc in docs:
        entry: Dict[str, Any] = dict(doc)
        if not download:
            entry["extraction_status"] = "not_downloaded"
            report["documents"].append(entry)
            continue
        pdf_path = _cache_file(cache_dir, doc["url"], ".pdf")
        try:
            payload, from_cache = _fetch_cached(
                doc["url"], pdf_path, timeout=timeout, force_refresh=force_refresh,
                accept="application/pdf,*/*", referer=index_url,
            )
        except Exception as exc:
            entry["extraction_status"] = EXTRACTION_NONE
            entry["reason"] = f"download failed: {exc}"
            report["documents"].append(entry)
            continue
        entry["bytes"] = len(payload)
        entry["from_cache"] = from_cache
        # A PDF that does not start with %PDF- is a soft-404 page, not a
        # document. Treating it as one produces OCR of an error page.
        if not payload.startswith(b"%PDF-"):
            entry["extraction_status"] = EXTRACTION_NONE
            entry["reason"] = "response is not a PDF (soft-404 page)"
            report["documents"].append(entry)
            continue

        extracted = extract_pdf_text(payload, text_fn=text_fn, ocr_fn=ocr_fn)
        entry["extraction_status"] = extracted["extraction_status"]
        entry["tiers_attempted"] = extracted["tiers_attempted"]
        entry["reason"] = extracted["reason"]
        entry["n_chars"] = len(extracted["text"] or "")
        parsed = parse_ppac_gas_notification(extracted["text"], filename=doc["filename"])
        for key in ("value", "unit", "ceiling_value", "period_start", "period_end",
                    "as_of_date", "as_of_date_source", "reason"):
            if key in parsed:
                entry[key] = parsed[key]
        report["documents"].append(entry)

    usable = [d for d in report["documents"] if d.get("value") is not None]
    if usable:
        newest = max(usable, key=lambda d: (d.get("epoch") or 0))
        report["status"] = "ok" if len(usable) == len(report["documents"]) else "partial"
        report["as_of_date"] = newest.get("as_of_date")
        report["series"] = usable
        report["reason"] = (
            None if report["status"] == "ok"
            else f"{len(report['documents']) - len(usable)} of "
                 f"{len(report['documents'])} documents yielded no value"
        )
    else:
        report["status"] = "refused"
        report["reason"] = (
            "no PPAC document produced both a price and a reference period; "
            "observations are NULL rather than estimated. Per-document "
            "extraction_status/reason explain which tier was tried."
        )
    return report


# ---------------------------------------------------------------------------
# Observation assembly + the orchestrator
# ---------------------------------------------------------------------------
def _world_bank_observations(parsed: Dict[str, Any], series_keys: Optional[Sequence[str]],
                             ) -> List[Tuple[str, List[Dict[str, Any]]]]:
    """Turn a parsed Pink Sheet into ``[(factor_key, observation_rows), ...]``."""
    if parsed.get("status") != "ok":
        return []
    as_of = parsed.get("as_of_date")
    if not as_of:
        return []
    wanted = set(WB_SERIES_KEYS)
    if series_keys:
        wanted &= {str(k) for k in series_keys}
    # ...then keep only the columns THIS SHEET actually carries. Iterating the
    # whole WB_SERIES_KEYS registry emitted an all-NULL entry for every
    # registered series absent from the workbook, which is a different claim:
    # a NULL means "this month had no value", not "this series is not in this
    # file". Those rows would carry an as_of_date and a note naming a header
    # row for a column that never existed.
    wanted &= set(parsed.get("column_map") or {})
    out: List[Tuple[str, List[Dict[str, Any]]]] = []
    for key in sorted(wanted):
        rows: List[Dict[str, Any]] = []
        for r in parsed.get("rows", []):
            value = r["values"].get(key)
            rows.append({
                "period_start": r["period_start"],
                "period_end": r["period_end"],
                "value": value,               # None is a legal, meaningful observation
                "unit": _REGISTRY_BY_KEY[key]["unit"],
                "as_of_date": as_of,          # FROM THE FILE, never from the clock
                "source": WB_SOURCE,
                "source_url": parsed.get("source_url"),
                "notes": (
                    f"WB Pink Sheet period {r['period']}; sheet part "
                    f"{parsed.get('sheet_part')}; header row {parsed.get('header_row')}"
                ),
            })
        if rows:
            out.append((key, rows))
    return out


def _ppac_observations(report: Dict[str, Any], series_keys: Optional[Sequence[str]],
                       ) -> List[Tuple[str, List[Dict[str, Any]]]]:
    key = PPAC_SERIES_KEY
    if series_keys and key not in {str(k) for k in series_keys}:
        return []
    if report.get("status") not in ("ok", "partial"):
        return []
    rows: List[Dict[str, Any]] = []
    for doc in report.get("series", []):
        rows.append({
            "period_start": doc.get("period_start"),
            "period_end": doc.get("period_end"),
            "value": doc.get("value"),
            "unit": _REGISTRY_BY_KEY[key]["unit"],
            "as_of_date": doc.get("as_of_date"),
            "source": PPAC_SOURCE,
            "source_url": doc.get("url"),
            "confidence": 0.9 if doc.get("as_of_date_source") == "document_dated_line" else 0.6,
            "notes": (
                f"PPAC notification {doc.get('filename')}; extraction="
                f"{doc.get('extraction_status')}; as_of_date_source="
                f"{doc.get('as_of_date_source')}"
                + (f"; ceiling={doc.get('ceiling_value')}" if doc.get("ceiling_value") is not None else "")
            ),
        })
    return [(key, rows)] if rows else []


DEFAULT_SOURCES: Tuple[str, ...] = ("world_bank", "ppac")


def load_series(
    manager: Optional[Any] = None,
    *,
    series_keys: Optional[Sequence[str]] = None,
    cache_dir: Optional[str] = None,
    sources: Sequence[str] = DEFAULT_SOURCES,
    dry_run: bool = True,
    force_refresh: bool = False,
    fetcher: Optional[Callable[[], Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Fetch and (unless ``dry_run``) write the loader's series into the spine.

    **Dry-run by default, and a dry run touches no database at all** — not
    even ``ensure_factor_spine_schema``. A loader that creates schema as a side
    effect of a preview has already violated the preview's contract.

    Vintage chaining is explicit because ``upsert_observations`` does **not**
    auto-increment: a restated month must be written as ``vintage = MAX+1`` or
    it silently overwrites history and the as-of resolver becomes a lie. An
    identical re-load (same ``as_of_date`` and same value) is NOT a new
    release and reuses the existing vintage, so re-running a load is
    idempotent.

    ``fetcher`` is an injection point: pass a callable returning a parsed
    payload to drive this whole path with no network. Tests use it; production
    does not.

    ``status`` is one of ``dry_run`` / ``failed`` / ``partial`` / ``ok`` /
    ``no_usable_observations``, and each means exactly one thing:
    ``no_usable_observations`` is a *clean* run that loaded nothing (sources
    parsed, no error raised, no datable observation survived) — reported
    separately from ``ok`` so that a caller can never read a no-op load as a
    successful one.
    """
    report: Dict[str, Any] = {
        "dry_run": bool(dry_run),
        "sources": list(sources),
        "series": {},
        "n_registered": 0,
        "n_written": 0,
        "errors": [],
        "as_of_dates": {},
    }
    wanted = {str(k) for k in series_keys} if series_keys else None

    payloads: Dict[str, Dict[str, Any]] = {}
    if "world_bank" in sources:
        try:
            payloads["world_bank"] = fetcher() if fetcher else fetch_world_bank_pink_sheet(
                cache_dir, force_refresh=force_refresh
            )
        except Exception as exc:  # design 4.1: never raise into the pipeline
            report["errors"].append(f"world_bank fetch raised {type(exc).__name__}: {exc}")
    if "ppac" in sources:
        try:
            payloads["ppac"] = fetch_ppac_gas_prices(cache_dir, force_refresh=force_refresh)
        except Exception as exc:
            report["errors"].append(f"ppac fetch raised {type(exc).__name__}: {exc}")

    plan: List[Tuple[str, List[Dict[str, Any]]]] = []
    for source_name, parsed in payloads.items():
        if source_name == "world_bank":
            if parsed.get("status") != "ok":
                report["errors"].append(
                    f"world_bank: {parsed.get('status')} — {parsed.get('reason')}"
                )
            plan.extend(_world_bank_observations(parsed, wanted))
        elif source_name == "ppac":
            if parsed.get("status") not in ("ok", "partial"):
                report["errors"].append(
                    f"ppac: {parsed.get('status')} — {parsed.get('reason')}"
                )
            plan.extend(_ppac_observations(parsed, wanted))

    for key, rows in plan:
        as_of_dates = sorted({r["as_of_date"] for r in rows if r.get("as_of_date")})
        report["as_of_dates"][key] = as_of_dates
        entry = {
            "n_observations": len(rows),
            "n_values": sum(1 for r in rows if r.get("value") is not None),
            "n_honest_nulls": sum(1 for r in rows if r.get("value") is None),
            "as_of_date": as_of_dates[0] if as_of_dates else None,
            "written": 0,
        }
        report["series"][key] = entry
        if dry_run:
            continue

        # --- write path -------------------------------------------------
        if not as_of_dates:
            entry["status"] = "refused"
            entry["reason"] = "no as_of_date: nothing may be written, today is not a substitute"
            report["errors"].append(f"{key}: refused, no as_of_date")
            continue
        today = _today_iso()
        future = [d for d in as_of_dates if d > today]
        if future:
            entry["status"] = "refused"
            entry["reason"] = f"as_of_date {future} is in the future"
            report["errors"].append(f"{key}: refused, future as_of_date {future}")
            continue
        try:
            ensure_factor_spine_schema(manager)
            report["n_registered"] += register_series(manager, [dict(_REGISTRY_BY_KEY[key])])
            entry["written"] = _write_with_vintage_chain(manager, key, rows)
            report["n_written"] += entry["written"]
            entry["status"] = "ok"
        except Exception as exc:
            entry["status"] = "failed"
            entry["reason"] = f"{type(exc).__name__}: {exc}"
            report["errors"].append(f"{key}: write failed: {entry['reason']}")
    if dry_run:
        report["status"] = "dry_run"
    elif report["errors"] and not report["n_written"]:
        report["status"] = "failed"
    elif report["errors"]:
        report["status"] = "partial"
    elif not plan and not report["n_written"]:
        # The sources parsed cleanly and raised nothing, yet there was nothing
        # to load: no datable observation survived, so no row was written and
        # no series was registered. "ok" here would claim a load that never
        # happened, and a caller reading only ``status`` could not tell the
        # difference. Distinct from "failed" (which needs an error) and from
        # "ok" (which needs a write).
        report["status"] = "no_usable_observations"
    else:
        report["status"] = "ok"
    return report


def _vintage_map(conn: Any, series_id: int) -> Dict[Tuple[str, str], Tuple[int, str, Any]]:
    """``{(period_start, period_end): (vintage, as_of_date, value)}`` for the
    newest known vintage of each period. One query per series, not one per row:
    the Pink Sheet is ~800 monthly rows across 5 series."""
    out: Dict[Tuple[str, str], Tuple[int, str, Any]] = {}
    for ps, pe, vt, ao, val in conn.execute(
        "SELECT period_start, period_end, vintage, as_of_date, value "
        "FROM factor_observation WHERE series_id = ? ORDER BY vintage",
        (series_id,),
    ).fetchall():
        out[(ps, pe)] = (int(vt), ao, val)
    return out


def _write_with_vintage_chain(manager: Any, series_key: str,
                              rows: Sequence[Dict[str, Any]]) -> int:
    """Write observations, assigning the correct ``vintage`` to each.

    The rule, stated once:

    * period unknown            -> ``vintage = 1`` (first release);
    * newest known vintage has
      the SAME ``as_of_date`` and the SAME value -> reuse that vintage
      (a re-load is not a new release, so a re-run is idempotent);
    * otherwise                 -> ``vintage = MAX(vintage) + 1`` (a restatement,
      which ``upsert_observations`` will chain and flip ``is_latest`` on).
    """
    written = 0
    with _session(manager) as conn:
        ref = conn.execute(
            "SELECT series_id FROM factor_series WHERE factor_key = ?", (series_key,)
        ).fetchone()
        if ref is None:
            raise ValueError(f"unknown series_key {series_key!r} (register it first)")
        series_id = int(ref[0])
        known = _vintage_map(conn, series_id)

    for row in rows:
        if not row.get("period_start") or not row.get("as_of_date"):
            logger.warning("skipping %s observation with no period/as_of: %r",
                           series_key, row)
            continue
        prior = known.get((row["period_start"], row["period_end"]))
        if prior is None:
            vintage = 1
        elif prior[1] == row["as_of_date"] and _same_value(prior[2], row.get("value")):
            vintage = prior[0]
        else:
            vintage = prior[0] + 1
        payload = dict(row)
        payload["vintage"] = vintage
        payload["is_latest"] = 1
        written += upsert_observations(manager, series_key, [payload])
        known[(row["period_start"], row["period_end"])] = (
            vintage, row["as_of_date"], row.get("value"),
        )
    return written


def _same_value(a: Any, b: Any) -> bool:
    if a is None or b is None:
        return a is None and b is None
    try:
        return abs(float(a) - float(b)) <= 1e-9 * max(1.0, abs(float(b)))
    except (TypeError, ValueError):
        return a == b


@contextmanager
def _session(target: Optional[Any]) -> Iterator[Any]:
    """Mirror of ``factor_spine._session`` — accepts a DatabaseManager or a raw
    sqlite3 connection. Duplicated rather than imported because it is a private
    helper; the public surface we use (``register_series`` /
    ``upsert_observations`` / ``ensure_factor_spine_schema``) is enough."""
    if target is None:
        from reality_engine.db.database import db_manager

        target = db_manager
    if hasattr(target, "session"):
        with target.session() as conn:
            yield conn
    else:
        yield target


__all__ = [
    "LOADER_SERIES_REGISTRY",
    "LOADER_SERIES_KEYS",
    "LOADER_REGISTRY_VALIDATED",
    "validate_loader_registry",
    "WB_COLUMN_MATCHERS",
    "WB_SERIES_KEYS",
    "WB_LANDING_URL",
    "WB_SHEET_NAME",
    "WB_SOURCE",
    "WB_LICENSE",
    "PPAC_INDEX_URL",
    "PPAC_SOURCE",
    "PPAC_LICENSE",
    "PPAC_SERIES_KEY",
    "DEFAULT_SOURCES",
    "EXTRACTION_TEXT_LAYER",
    "EXTRACTION_OCR",
    "EXTRACTION_NONE",
    "parse_world_bank_pink_sheet",
    "resolve_pink_sheet_url",
    "resolve_sheet_part",
    "list_sheet_parts",
    "read_sheet_rows",
    "parse_updated_on",
    "parse_dated_field",
    "parse_ppac_gas_notification",
    "discover_ppac_gas_documents",
    "extract_pdf_text",
    "fetch_world_bank_pink_sheet",
    "fetch_ppac_gas_prices",
    "load_series",
]
