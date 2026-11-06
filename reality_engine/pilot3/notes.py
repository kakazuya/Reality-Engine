"""Rule-based annual-report note tables (T-091): ``rating_event``, ``concentration``, ``related_party_txn``.

CLI: ``python -m reality_engine.pilot3.notes --out <db> [--symbols KEC,BAJFINANCE] [--limit-docs N]``

No model, no OCR, no network.  The reader works on ``doc_page`` text and finds three kinds of note by general
wording and table shape, never by company name, page number or a per-company rule (all wording lives in
``notes_lexicon.yaml``):

* ``rating_event`` -- one row per agency / instrument / rating printed by a credit-rating table
  (``Rating agency`` + ``Programme`` + ``Ratings assigned`` columns, or ``Rating agency`` + ``Rating`` +
  ``Outlook``), with the migration cell of the table read as the action (``Nil`` is ``reaffirmed``, "Upgraded
  from" is ``upgraded``, and a table or sentence that states no action leaves it NULL); a prose sentence naming an agency and a rating ("... credit rating of AAA/Stable
  (long term) and A1+ (short term) on its bank facilities by CRISIL") is the same row shape; a company that
  states it holds no rating gets ``not_rated``; a rating-linked clause in any filing (coupon step-up on a
  downgrade, a recall right at a rating) gets ``trigger`` with the clause in ``trigger_text``.
* ``concentration`` -- one row per year column of a table that names a bucket (top 5/10/20, single largest) or
  a whole population (all trading houses, all dealers) and a measure (share of deposits, advances, exposure,
  revenue, purchases, liabilities), or of a prose sentence ("the top 20 depositors comprised of 4.81% of total
  deposits").  The year of each value is read from the table's own column header, so the current and prior year
  are separate rows whatever order the columns print in.
* ``related_party_txn`` -- one row per counterparty per year of a related-party note: the page must carry a
  related-party cue and a two-year column header, each row is an entity name (or a party heading such as
  "Remuneration to KMP") followed by its year values, and the printed heading above the row is the
  transaction type.  Standalone and consolidated notes stay apart through ``basis``; FY and prior year are
  separate rows through ``fiscal_year`` / ``period_end``.

``basis`` is read from the page's own header ("Notes to the Standalone Financial Statements" / "... Consolidated
..."); a page that carries none is ``not_stated`` rather than guessed.  ``entity`` is the company's legal name
from the ``company`` table, never a literal.  ``known_at`` is the document's filing time, so every row is
point-in-time.

What these rules cannot read (documented in ``docs/PILOT3_BLUEPRINT.md`` section 9f): a rating table whose
text extraction interleaves columns so no agency line stays with its ratings; a concentration table whose
labels wrap across three or more lines; a note that prints a single merged year column; a subsidiary's
standalone note whose page header names neither basis; and a trigger clause stated only as an image.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import time
from collections import Counter
from functools import lru_cache
from pathlib import Path

import yaml

from reality_engine.pilot3 import profile
from reality_engine.pilot3.schema import TABLES, NOTES_INDEXES

# Not under lexicon/: kpi.load_lexicon and transcripts read every yaml in that folder as a KPI lexicon.
LEXICON = Path(__file__).with_name("notes_lexicon.yaml")

NOTES = ("rating_event", "concentration", "related_party_txn")

COLS = {
    "rating_event": ("symbol isin fiscal_year entity basis agency instrument rating outlook action effective_date "
                     "trigger_text doc_key page quote known_at known_at_source extractor_rule").split(),
    "concentration": ("symbol isin fiscal_year entity basis dimension bucket measure pct value unit scale period_end "
                      "doc_key page quote known_at known_at_source extractor_rule").split(),
    "related_party_txn": ("symbol isin fiscal_year entity basis counterparty relationship txn_type amount balance "
                          "unit scale period_end doc_key page quote known_at known_at_source extractor_rule").split(),
}

MAX_QUOTE = 600

# --- numbers and lines -------------------------------------------------------------------------------------------
_NUM = re.compile(r"^\(?-?\d[\d,]*(?:\.\d+)?\)?%?$|^[-–—]$")
_PCT = re.compile(r"^\(?-?\d[\d,]*(?:\.\d+)?\)?%$")
_MONTHS = {"january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6, "july": 7,
           "august": 8, "september": 9, "october": 10, "november": 11, "december": 12}
_MONTH_NAMES = "|".join(_MONTHS)
_MONTH_DAY = re.compile(rf"\b({_MONTH_NAMES})\s+(\d{{1,2}})\b|\b(\d{{1,2}})\s+({_MONTH_NAMES})\b", re.I)


def _num(token: str) -> float | None:
    token = token.strip().replace(",", "").replace("%", "")
    neg = token.startswith("(") and token.endswith(")")
    token = token.strip("()")
    if token in ("-", "–", "—"):
        return None
    try:
        value = float(token)
    except ValueError:
        return None
    return -value if neg else value


def _is_pct(token: str) -> bool:
    return token.strip().endswith("%")


def split_row(line: str) -> tuple[str, list[str]]:
    """A printed table line as (label, trailing number cells).  ``Revenue from top five customers 12.7 12.0``
    -> ("Revenue from top five customers", ["12.7", "12.0"]); a line of values only has an empty label; a
    trailing "(1)" on a label line is a footnote marker, not a value."""
    parts = line.split()
    values: list[str] = []
    while parts and _NUM.match(parts[-1]):
        token = parts[-1]
        footnote = re.fullmatch(r"\((\d{1,2})\)", token)
        if footnote and 1 <= int(footnote.group(1)) <= 20 \
                and (len(parts) == 1 or not _NUM.match(parts[-2])):
            break
        values.insert(0, parts.pop())
    return " ".join(parts).strip(), values


def page_lines(text: str) -> list[str]:
    """The page's non-empty lines, with runs of number-only lines merged back into one row's cells (the page
    text of a PDF table prints each cell on its own line: a label, then 2026's cell, then 2025's cell)."""
    out: list[str] = []
    pending: list[str] = []
    for raw in text.splitlines():
        line = " ".join(raw.split())
        if not line:
            continue
        label, values = split_row(line)
        if label:
            if pending:
                out.append(" ".join(pending))
                pending = []
            out.append(line)
        else:
            pending.extend(values)
    if pending:
        out.append(" ".join(pending))
    return out


# --- lexicon ------------------------------------------------------------------------------------------------------
def _phrase(pattern: str) -> re.Pattern:
    """'Standard & Poor's' -> a pattern that tolerates the page's own apostrophe and spacing."""
    parts = [p for p in re.split(r"[^A-Za-z0-9]+", pattern.strip()) if p]
    return re.compile(r"\b" + r"[^A-Za-z0-9]+".join(map(re.escape, parts)) + r"\b", re.I)


@lru_cache(maxsize=1)
def lexicon() -> dict:
    data = yaml.safe_load(LEXICON.read_text(encoding="utf-8")) or {}
    out: dict = {}
    out["agencies"] = [(_phrase(a), a) for a in data.get("agencies", [])]
    out["rating"] = re.compile(data["rating_tokens"])
    out["outlooks"] = [(_phrase(o), o) for o in data.get("outlooks", [])]
    out["actions"] = {name: [re.compile(p, re.I) for p in pats] for name, pats in data.get("actions", {}).items()}
    out["not_rated"] = [re.compile(p, re.I) for p in data.get("not_rated", [])]
    out["rating_cues"] = [re.compile(p, re.I) for p in data.get("rating_cues", [])]
    out["trigger_cues"] = [re.compile(p, re.I) for p in data.get("trigger_cues", [])]
    out["dimensions"] = [(name, [re.compile(p, re.I) for p in pats]) for name, pats in data.get("dimensions", {}).items()]
    out["buckets"] = [(name, [re.compile(p, re.I) for p in pats]) for name, pats in data.get("buckets", {}).items()]
    out["measures"] = [(name, [re.compile(p, re.I) for p in pats]) for name, pats in data.get("measures", {}).items()]
    out["concentration_cues"] = [re.compile(p, re.I) for p in data.get("concentration_cues", [])]
    out["rpt_cues"] = [re.compile(p, re.I) for p in data.get("rpt_cues", [])]
    out["relationships"] = [(name, [re.compile(p, re.I) for p in pats])
                            for name, pats in data.get("relationships", {}).items()]
    out["party_categories"] = [(name, [re.compile(p, re.I) for p in pats])
                               for name, pats in data.get("party_categories", {}).items()]
    out["entity"] = re.compile(r"\b(?:" + "|".join(data.get("entity_suffixes", [])) + r")\s*$", re.I)
    out["balance_cues"] = [re.compile(p, re.I) for p in data.get("balance_cues", [])]
    out["prefilter"] = data.get("page_prefilter", {})
    return out


# --- page shape helpers -------------------------------------------------------------------------------------------
FY_RANGE = re.compile(r"\bFY\s*'?((?:19|20)\d{2})\s*[-–/]\s*(\d{2,4})\b", re.I)
BARE_YEAR = re.compile(r"(?<![\d,.])((?:19|20)\d{2})(?![\d,.]|[-–/]\d)")
_HEADER_WORDS = re.compile(r"\b(particulars|as at|as on|for the year|year ended|years ended|march|december|june|"
                           r"september|rs|inr|in|crore|crores|cr|amount|date|quarter|ended|the|of|and)\b", re.I)
_HEADER_ALLOWED = {"particulars", "as", "at", "on", "for", "the", "year", "years", "ended", "march", "june",
                   "september", "december", "fy", "rs", "inr", "crore", "crores", "cr", "in", "amount", "date",
                   "quarter", "to", "and", "of", "period", "end", "note", "schedule"}


def _year_tokens(line: str) -> list[int]:
    """The 4-digit years a header line prints; an "FY 2025-26" range names 2026 (its end), like a bare 2026."""
    years: list[int] = []
    for m in FY_RANGE.finditer(line):
        year = int(m.group(1))
        end = int(m.group(2))
        if end < 100:
            end = (year // 100) * 100 + end
        years.append(end)
    years.extend(int(m.group(1)) for m in BARE_YEAR.finditer(line))
    return years


def _header_ok(line: str) -> bool:
    """True when a line is only a year column header ("2026 2025", "FY 2025-26", "Year ended March 31, 2026"),
    never a sentence or a name that happens to carry a year."""
    if len(line) > 45:
        return False
    rest = BARE_YEAR.sub(" ", FY_RANGE.sub(" ", line))
    rest = _MONTH_DAY.sub(" ", rest)
    return all(w.lower() in _HEADER_ALLOWED for w in re.findall(r"[A-Za-z]+", rest))


def header_columns(lines: list[str], i: int) -> tuple[list[tuple[str, str]], int] | None:
    """The year columns printed at line ``i``: [(fiscal_year, period_end)], and the index of the first row line.
    A column is read by its own printed year, never by position, so a table that prints 2025 before 2026 keeps
    every value on the right year."""
    tokens: list[tuple[int, int]] = []
    window: list[str] = []
    for k in range(i, min(i + 4, len(lines))):
        line = lines[k]
        window.append(line)
        years = _year_tokens(line)
        if years and not _header_ok(line):
            return None
        tokens.extend((k, y) for y in years)
        if len(tokens) >= 2:
            break
        if k > i and len(line) > 60:
            return None
    if len(tokens) < 2:
        return None
    first, second = tokens[0], tokens[1]
    if first[1] == second[1]:
        return None
    for k, _y in tokens[:2]:
        if not _header_ok(lines[k]):
            return None
    context = " ".join(lines[max(0, i - 4):max(k for k, _y in tokens[:2]) + 1]) if window else ""
    md = None
    for m in _MONTH_DAY.finditer(context):
        month = _MONTHS[(m.group(1) or m.group(4)).lower()]
        day = int(m.group(2) or m.group(3))
        if 1 <= day <= 31:
            md = (month, day)
            break
    cols = []
    for _k, year in tokens[:2]:
        end = f"{year}-{md[0]:02d}-{md[1]:02d}" if md else f"{year}-03-31"
        cols.append((f"FY{year % 100:02d}", end))
    return cols, max(k for k, _y in tokens[:2]) + 1


def table_blocks(lines: list[str]) -> list[tuple[list[tuple[str, str]], list[dict], int]]:
    """Every year-columned table on a page: its year columns, its rows (label, heading, values, quote) and the
    line index its year header starts at.  A row is a label with its values on the same line, or a label line
    followed by its merged value line."""
    blocks: list[tuple[list[tuple[str, str]], list[dict], int]] = []
    i = 0
    while i < len(lines):
        head = header_columns(lines, i)
        if not head:
            i += 1
            continue
        cols, start = head
        rows: list[dict] = []
        heading: str | None = None
        pending: dict | None = None
        j = start
        while j < len(lines):
            if header_columns(lines, j):
                break
            line = lines[j]
            label, values = split_row(line)
            if not label and values and pending is not None:
                rows.append({"label": pending["label"], "heading": heading, "values": values,
                             "quote": " ".join(pending["quote"] + [line])})
                pending = None
            elif label and values:
                rows.append({"label": label, "heading": heading, "values": values, "quote": line})
                pending = None
            elif label:
                new = {"label": label, "quote": [line]}
                if pending is not None and re.match(r"[a-z]|\d+\.\s", label) \
                        and len(pending["label"]) + len(label) <= 160:
                    pending["label"] = f"{pending['label']} {label}"
                    pending["quote"].append(line)
                else:
                    pending = new
                next_is_value = j + 1 < len(lines) and split_row(lines[j + 1])[0] == ""
                if not next_is_value and 8 <= len(pending["label"]) <= 160 \
                        and not re.fullmatch(r"(?:[a-z]|[ivx]+|\d+)\.?", pending["label"], re.I):
                    heading = pending["label"]        # a heading is followed by another label, not by values
            j += 1
        blocks.append((cols, rows, i))
        i = j
    return blocks


# "(All amounts in Rs million, unless otherwise stated)", or a unit alone on its line ("Rs in Million")
_AMOUNTS_IN = re.compile(r"(?:\b(?:amounts?|figures?)\s+(?:are\s+)?in\s+\S{0,4}\s*|^\s*\S{0,3}\s*in\s+)"
                         r"(crores?|lakhs?|million|billion)\b", re.I | re.M)
_UNIT_WORDS = {"crore": ("inr_cr", 1e7), "lakh": ("inr_lakh", 1e5), "million": ("inr_mn", 1e6), "billion": ("inr_bn", 1e9)}


def unit_of(lines_before: str) -> tuple[str | None, float | None]:
    """(unit, scale) of a table's own unit note: a crore/lakh/million line is money, "(In %)" is a percentage."""
    if re.search(r"\(\s*(?:in\s+)?%\s*\)|\(\s*in\s+per\s?cent\s*\)", lines_before, re.I):
        return "pct", 1.0
    if re.search(r"\(\s*[^)]{0,24}crores?\s*\)", lines_before, re.I) or re.search(r"\bin\s+crores?\b", lines_before, re.I):
        return "inr_cr", 1e7
    if re.search(r"\(\s*[^)]{0,24}lakhs?\s*\)", lines_before, re.I):
        return "inr_lakh", 1e5
    if re.search(r"\(\s*[^)]{0,24}(?:million|mn)\s*\)", lines_before, re.I):
        return "inr_mn", 1e6
    if re.search(r"\(\s*[^)]{0,24}(?:billion|bn)\s*\)", lines_before, re.I):
        return "inr_bn", 1e9
    stated = _AMOUNTS_IN.search(lines_before)     # "(All amounts in ₹ million, unless otherwise stated)"
    if stated:
        return _UNIT_WORDS[stated.group(1).lower().rstrip("s")]
    return None, None


def page_unit(pages: list, index: int, back: int = 6) -> tuple[str | None, float | None]:
    """The money unit a note states on this page or on the pages before it: a note prints its unit once, at the top
    of the note or in the statement's running header, and the later pages inherit it.  None when nothing says."""
    for at in range(index, max(-1, index - back - 1), -1):
        unit, scale = unit_of(pages[at][1] or "")
        if unit and unit != "pct":
            return unit, scale
    return None, None


def basis_of(text: str) -> str:
    """The reporting basis of a page, from its own header; never guessed from the document type."""
    head = " ".join(text.split())[:600]
    if re.search(r"notes to the consolidated|financial statements: consolidated|consolidated financial statements",
                 head, re.I):
        return "consolidated"
    if re.search(r"notes to the standalone|financial statements: standalone|standalone financial statements",
                 head, re.I):
        return "standalone"
    return "not_stated"


def _sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.;])\s+", " ".join(text.split())) if s]


def _doc_fy(doc) -> str | None:
    """The fiscal year a document belongs to: an annual report / results file reports the year that ended, an
    announcement is dated inside the year in progress."""
    day = (doc["filing_date"] or doc["known_at"] or "")[:10]
    m = re.match(r"(\d{4})-(\d{2})", day)
    if not m:
        return None
    year, month = int(m.group(1)), int(m.group(2))
    if doc["doc_type"] in ("annual_report", "results"):
        year = year if month >= 4 else year - 1
    else:
        year = year + 1 if month >= 4 else year
    return f"FY{year % 100:02d}"


def _fy_period(fiscal_year: str | None) -> str | None:
    if not fiscal_year or not re.fullmatch(r"FY\d{2}", fiscal_year):
        return None
    return f"20{fiscal_year[2:]}-03-31"


# --- rating_event -------------------------------------------------------------------------------------------------
_HEADER_WORDS = re.compile(r"^(particulars|rating agency|agency|rating|ratings|outlook|programme|program|"
                           r"ratings assigned|migration in ratings|instrument|type of instrument)$", re.I)


_AGENCY_TAIL = {"rating", "ratings", "ltd", "limited", "global", "research", "private", "inc", "and", "of",
                "agency", "agencies", "services", "llc", "plc", "corp", "corporation", "india", "co"}


def _agency(line: str, lex: dict) -> str | None:
    """The agency a table CELL names: the line starts with the agency and the rest is the agency's own name
    suffix ("CRISIL Rating Ltd.", "India Ratings and Research Private Ltd."), never a prose line, a list of
    agencies or a rating cell ("CRISIL AAA/Stable")."""
    stripped = line.strip()
    if len(stripped) > 55:
        return None
    for pattern, name in lex["agencies"]:
        m = pattern.match(stripped)
        if not m:
            continue
        rest = stripped[m.end():]
        if lex["rating"].search(rest):
            continue
        words = re.findall(r"[A-Za-z]+", rest)
        if all(w.lower() in _AGENCY_TAIL for w in words):
            return name.strip()
    return None


def _outlook(text: str, lex: dict) -> str | None:
    for pattern, name in lex["outlooks"]:
        m = pattern.search(text)
        if m:
            return name
    return None


def _action_of(line: str, lex: dict) -> str | None:
    """The rating operation a migration / action cell states, or None when the line states none."""
    text = line.strip().rstrip(".")
    if len(text) > 220:
        return None
    if re.fullmatch(r"(?:nil|na|n\.?a\.?|-|–|—|not applicable)", text, re.I):
        return "reaffirmed"
    for name in ("upgraded", "downgraded", "assigned", "withdrawn", "reaffirmed"):
        for pattern in lex["actions"].get(name, []):
            if pattern.search(text):
                return name
    return None


def _rating_cell(line: str, lex: dict) -> tuple[str, str | None, str] | None:
    """(rating, outlook, text before the rating) when the line prints a rating symbol as its own cell."""
    m = lex["rating"].search(line)
    if not m or (m.start() > 0 and line[m.start() - 1].isalnum()):   # "C" inside "OTC" is no rating
        return None
    before = line[:m.start()].strip()
    after = line[m.end():].strip()
    if len(before) > 45 or len(after) > 60:
        return None
    if before and not re.search(r"\b(rating|rated|issuer|entity|assigned|long[- ]term|short[- ]term|"
                                r"instrument|programme|facilit(?:y|ies))\b", before, re.I) \
            and not re.fullmatch(r"[A-Z]{2,6}", before):
        return None
    outlook = None
    if after:
        tail = _outlook(after, lex)
        if tail is None and not re.fullmatch(r"[\s/()'\u2019.,:;-]*", after):
            return None
        outlook = tail
    return m.group(0).strip(), outlook, before


def _instrument(line: str, lex: dict | None = None) -> bool:
    """A programme / instrument cell: a short noun phrase of at least two words, no number and no full stop."""
    text = line.strip()
    return 8 <= len(text) <= 70 and len(text.split()) >= 2 and not _NUM.search(text) \
        and not text.endswith(".") and not re.search(r"[*#^]|\)$|\|", text) and not _HEADER_WORDS.match(text) \
        and not re.match(r"(?:with|and|or|of|from|to|for|in|on|as|by|at|the|a|an)\b", text, re.I) \
        and not (lex and _action_of(text, lex))


def rating_rows(symbol: str, isin: str, entity: str, doc, page: int, text: str, lex: dict) -> list[dict]:
    """``rating_event`` rows of one page: the rating table, the rating said in prose, or a not_rated statement."""
    lines = page_lines(text)
    collapsed = " ".join(text.split())
    if not any(cue.search(collapsed) for cue in lex["rating_cues"]):
        return []
    if re.search(r"credit rating of the related part|rating of the related part", collapsed, re.I):
        return []          # the note rates the counterparty, not the company
    fiscal_year = _doc_fy(doc)
    basis = basis_of(text)
    rows: list[dict] = []
    no_change = bool(re.search(r"no change in (?:the )?(?:credit )?ratings?", collapsed, re.I))

    # (1) the table path: agency cells and at least two rating cells
    agency_lines = [i for i, line in enumerate(lines) if _agency(line, lex)]
    rating_lines = [i for i, line in enumerate(lines) if _rating_cell(line, lex)]
    if agency_lines and len(rating_lines) >= 2:
        agency = instrument = None
        last: dict | None = None
        last_i = -10
        skip_next = False
        for i, line in enumerate(lines):
            if skip_next:
                skip_next = False
                continue
            name = _agency(line, lex)
            if name:
                agency, instrument, last = name, None, None
                continue
            cell = _rating_cell(line, lex)
            if cell and not _action_of(line, lex):
                rating, outlook, before = cell
                embedded = None
                for pattern, acname in lex["agencies"]:
                    m = pattern.match(before)
                    if m:
                        embedded = acname.strip()
                        break
                row_agency = embedded or agency
                if row_agency is None and i + 1 < len(lines):
                    ahead = _agency(lines[i + 1], lex)
                    if ahead:                       # a table that prints the agency after the rating
                        row_agency, skip_next = ahead, True
                row = {"agency": row_agency,
                       "instrument": (before[len(embedded):].strip(" -–—:") if embedded else instrument) or None,
                       "rating": rating, "outlook": outlook,
                       "action": "reaffirmed" if no_change else None}
                full = {"symbol": symbol, "isin": isin, "fiscal_year": fiscal_year, "entity": entity,
                        "basis": basis, **row, "effective_date": None, "trigger_text": None,
                        "doc_key": doc["doc_key"], "page": page, "quote": line,
                        "known_at": doc["known_at"], "known_at_source": "doc.known_at",
                        "extractor_rule": "rating_table_v1"}
                rows.append(full)
                last, last_i = full, i
                continue
            action = _action_of(line, lex)
            if action:
                if last is not None and i - last_i <= 2:
                    last["action"] = action
                if re.search(r"\b(?:from|to)\s*$", line.strip(), re.I):
                    skip_next = True          # the comparison base is printed on the next line
                continue
            tail = _outlook(line, lex)
            if tail and last is not None and i - last_i <= 2 and len(line) <= 40:
                last["outlook"] = tail
                continue
            if agency and _instrument(line, lex):
                instrument = line.strip()
                last = None          # a new programme begins; a later cell is not this row's note
        if rows:              # no action cell and no "no change" sentence: the action stays NULL, never assumed
            return rows

    # (2) a rating said in prose: one agency, no withdrawal, no comparison base ("from BBB-")
    for sentence in _sentences(collapsed):
        if not re.search(r"\bcredit rating|rating of|rated|ratings? (?:assigned|awarded)", sentence, re.I):
            continue
        if re.search(r"\bwithdrew|withdrawn|withdrawal\b", sentence, re.I):
            continue
        agencies = [name.strip() for pattern, name in lex["agencies"] if pattern.search(sentence)]
        if len(agencies) != 1:
            continue
        agency = agencies[0]
        tokens = []
        for token in lex["rating"].finditer(sentence):
            window = sentence[max(0, token.start() - 30):token.start()]
            preps = list(re.finditer(r"\b(from|to|into)\b", window, re.I))
            if preps and preps[-1].group(1).lower() == "from":
                continue                  # the rating the company moved FROM is not the rating in force
            tokens.append(token)
        if not tokens:
            continue
        cue = re.search(r"\b(?:credit rating|rating of|rated|rating)\b", sentence, re.I)
        if cue is None or tokens[0].start() < cue.end() - 2:
            continue
        instrument = None
        m = re.search(r"\bon\s+(?:its|the|our)\s+(.{3,50}?)\s+by\s", sentence, re.I)
        if m:
            instrument = m.group(1).strip(" ,.")
        action = None         # only what the sentence says; a bare statement of a rating is not a reaffirmation
        for name in ("upgraded", "downgraded", "assigned", "reaffirmed"):
            if any(p.search(sentence) for p in lex["actions"].get(name, [])):
                action = name
                break
        seen_tokens: set[str] = set()
        for token in tokens[:4]:
            rating = token.group(0).strip()
            if rating in seen_tokens:
                continue
            seen_tokens.add(rating)
            after = sentence[token.end():token.end() + 40]
            outlook = _outlook(after, lex)
            tenor = re.search(r"\(?\b(long[- ]term|short[- ]term)\b\)?", after, re.I)
            inst = instrument
            if inst and tenor:
                inst = f"{inst} ({tenor.group(1).lower()})"
            rows.append({"symbol": symbol, "isin": isin, "fiscal_year": fiscal_year, "entity": entity,
                         "basis": basis, "agency": agency, "instrument": inst, "rating": rating,
                         "outlook": outlook, "action": action, "effective_date": None, "trigger_text": None,
                         "doc_key": doc["doc_key"], "page": page, "quote": sentence[:MAX_QUOTE],
                         "known_at": doc["known_at"], "known_at_source": "doc.known_at",
                         "extractor_rule": "rating_prose_v1"})
        if rows:
            return rows

    # (3) a company that says it holds no rating
    for sentence in _sentences(collapsed):
        if any(p.search(sentence) for p in lex["not_rated"]):
            rows.append({"symbol": symbol, "isin": isin, "fiscal_year": fiscal_year, "entity": entity,
                         "basis": basis, "agency": None, "instrument": None, "rating": None, "outlook": None,
                         "action": "not_rated", "effective_date": None, "trigger_text": None,
                         "doc_key": doc["doc_key"], "page": page, "quote": sentence[:MAX_QUOTE],
                         "known_at": doc["known_at"], "known_at_source": "doc.known_at",
                         "extractor_rule": "rating_not_rated_v1"})
            break
    return rows


def trigger_rows(symbol: str, isin: str, entity: str, doc, page: int, text: str, lex: dict) -> list[dict]:
    """``rating_event`` rows with action ``trigger``: a rating-linked clause (coupon step-up, recall right)."""
    collapsed = " ".join(text.split())
    if not any(cue.search(collapsed) for cue in lex["trigger_cues"]):
        return []
    fiscal_year = _doc_fy(doc)
    basis = basis_of(text)
    instrument = None
    m = re.search(r"((?:[A-Z][\w-]*\s+){0,3}(?:non[- ]convertible\s+)?debentures?|NCDs?|bonds?)", collapsed)
    if m:
        instrument = m.group(1).strip()
    rows: list[dict] = []
    clauses = re.split(r"(?<=[.;])\s+(?=(?:If|In case|Upon|Where|In the event)\b)", collapsed)
    for clause in clauses:
        if not any(cue.search(clause) for cue in lex["trigger_cues"]):
            continue
        # a rating-linked clause names both a rating level and a consequence that moves money or the instrument
        if not (re.search(r"\b(downgrad\w*|rating falls|rating of (?:the )?instrument|below)\b", clause, re.I)
                and re.search(r"\b(coupon|interest rate|recall|redeem\w*|principal|step[- ]?(?:up|down))\b",
                              clause, re.I)
                and re.match(r"(?:If|In case|Upon|Where|In the event)\b", clause, re.I)):
            continue
        limit = None
        for token in lex["rating"].finditer(clause):
            limit = token.group(0).strip()
        if limit is None:
            continue
        rows.append({"symbol": symbol, "isin": isin, "fiscal_year": fiscal_year, "entity": entity,
                     "basis": basis, "agency": None, "instrument": instrument, "rating": limit, "outlook": None,
                     "action": "trigger", "effective_date": None, "trigger_text": clause[:MAX_QUOTE],
                     "doc_key": doc["doc_key"], "page": page, "quote": clause[:MAX_QUOTE],
                     "known_at": doc["known_at"], "known_at_source": "doc.known_at",
                     "extractor_rule": "rating_trigger_v1"})
    return rows


# --- concentration ------------------------------------------------------------------------------------------------
def _bucket(label: str, lex: dict) -> str | None:
    for name, patterns in lex["buckets"]:
        if any(p.search(label) for p in patterns):
            return name
    return None


def _dimension(label: str, lex: dict) -> str | None:
    for name, patterns in lex["dimensions"]:
        if any(p.search(label) for p in patterns):
            return name
    return None


def _measure(text: str, lex: dict) -> str | None:
    for name, patterns in lex["measures"]:
        if any(p.search(text) for p in patterns):
            return name
    return None


def _concentration_label(label: str, lex: dict, pct_table: bool = False) -> dict | None:
    """Read a concentration table label into {dimension, bucket, measure, is_share} or None.

    ``Total deposits of twenty largest depositors`` -> value of deposits, top_20;
    ``Percentage of deposits to twenty largest depositors to total deposits`` -> share of deposits, top_20;
    ``Purchases from top 10 trading houses as % of total purchases from trading houses`` -> share of purchases,
    top_10; ``Sales to dealers / distributors as % of total sales`` -> share of revenue, no bucket;
    ``Revenue from top five customers`` in a table printed in percent -> share of revenue, top_5."""
    label = label.strip()
    bucket = _bucket(label, lex)
    dimension = _dimension(label, lex)
    share = bool(re.search(r"as\s*%\s*of|percentage|percent\b|share of", label, re.I))
    measure = None
    if share:
        tail = re.split(r"as\s*%\s*of|to total|of total", label, flags=re.I)
        measure = _measure(tail[-1], lex) if tail else None
        if measure is None:
            return None
        return {"dimension": dimension, "bucket": bucket, "measure": f"share of {measure}", "is_share": True}
    m = re.match(r"(?:total|aggregate)\s+(.{3,60}?)\s+(?:of|to|from)\s+", label, re.I)
    if m and bucket:
        measure = _measure(m.group(1), lex)
        if measure:
            return {"dimension": dimension, "bucket": bucket, "measure": measure, "is_share": False}
    if pct_table and bucket and dimension:
        measure = _measure(label, lex)
        if measure:
            return {"dimension": dimension, "bucket": bucket, "measure": f"share of {measure}", "is_share": True}
    return None


def concentration_rows(symbol: str, isin: str, entity: str, doc, page: int, text: str, lex: dict) -> list[dict]:
    """``concentration`` rows of one page (a table with a bucket label, or a prose sentence)."""
    collapsed = " ".join(text.split())
    lines = page_lines(text)
    if not any(cue.search(collapsed) for cue in lex["concentration_cues"]):
        return []
    fiscal_year = _doc_fy(doc)
    basis = basis_of(text)
    default_period = _fy_period(fiscal_year)
    rows: list[dict] = []

    def emit(dimension, bucket, measure, pct, value, unit, scale, fiscal_year, period_end, quote, rule) -> None:
        rows.append({"symbol": symbol, "isin": isin, "fiscal_year": fiscal_year, "entity": entity, "basis": basis,
                     "dimension": dimension, "bucket": bucket, "measure": measure, "pct": pct, "value": value,
                     "unit": unit, "scale": scale, "period_end": period_end, "doc_key": doc["doc_key"],
                     "page": page, "quote": quote[:MAX_QUOTE], "known_at": doc["known_at"],
                     "known_at_source": "doc.known_at", "extractor_rule": rule})

    # (1) a two-year table: each row's values sit on their own column's fiscal year
    for cols, block_rows, header_start in table_blocks(lines):
        unit, scale = unit_of(" ".join(lines[max(0, header_start - 10):header_start + 2]))
        for row in block_rows:
            parsed = _concentration_label(row["label"], lex, pct_table=unit == "pct" or any(_is_pct(v) for v in row["values"]))
            if not parsed or not parsed["dimension"] or len(row["values"]) < len(cols):
                continue
            is_pct = parsed["is_share"] or any(_is_pct(v) for v in row["values"]) or unit == "pct"
            for (fy, period_end), token in zip(cols, row["values"]):
                number = _num(token)
                if number is None:
                    continue
                emit(parsed["dimension"], parsed["bucket"], parsed["measure"],
                     number if is_pct else None, None if is_pct else number,
                     "pct" if is_pct else unit, 1.0 if is_pct else scale,
                     fy, period_end, row["quote"] + " | " + row["label"], "conc_table_v1")
    # (2) prose: "the top 20 depositors comprised of 4.81% of total deposits"
    for sentence in _sentences(collapsed):
        if not re.search(r"\b(?:top|largest)\b", sentence, re.I) or "%" not in sentence:
            continue
        if re.search(r"\bno single|none of|not more than|less than|no customer|no borrower", sentence, re.I):
            continue
        m = re.search(r"\b(?:the\s+)?(?:top|largest)\s*(\d+|five|ten|twenty)?\s+(.{3,60}?)\s+"
                      r"(?:comprised|came|contributed|accounted|formed|were|is|was|represents?|constitut\w*)",
                      sentence, re.I)
        if not m:
            m = re.search(r"\b(?:top|largest)\s*(\d+|five|ten|twenty)?\s+([\w/\s-]{3,40}?)\s+(?:comprised|"
                          r"accounted|contributed|formed)", sentence, re.I)
        if not m:
            continue
        bucket = _bucket(f"top {m.group(1) or ''} largest", lex)
        dimension = _dimension(m.group(2), lex)
        pct_m = re.search(r"(-?\d[\d,]*(?:\.\d+)?)\s*%", sentence)
        total = re.search(r"of\s+(?:the\s+)?total\s+([\w\s]{3,30})", sentence, re.I)
        if not (bucket and dimension and pct_m and total):
            continue
        measure = _measure(total.group(1), lex)
        if not measure:
            continue
        period = default_period
        dm = _MONTH_DAY.search(sentence)
        ym = re.search(r"\b((?:19|20)\d{2})\b", sentence)
        if dm and ym:
            month = _MONTHS[(dm.group(1) or dm.group(4)).lower()]
            day = int(dm.group(2) or dm.group(3))
            period = f"{ym.group(1)}-{month:02d}-{day:02d}"
        emit(dimension, bucket, f"share of {measure}", _num(pct_m.group(1)), None, "pct", 1.0,
             f"FY{period[2:4]}" if period else fiscal_year, period, sentence, "conc_prose_v1")
    return rows


# --- related_party_txn --------------------------------------------------------------------------------------------
def _relationship(text: str, lex: dict) -> str | None:
    for name, patterns in lex["relationships"]:
        if any(p.search(text) for p in patterns):
            return name
    return None


def _party(text: str, lex: dict) -> str | None:
    """The party a heading or a row label names ("Remuneration to KMP" -> KMP, "Directors remuneration" ->
    Directors), or None when it names no party."""
    m = re.search(r"\b(key managerial personnel|KMPs?|directors?|promoters?|subsidiar(?:y|ies)|associates?|"
                  r"joint ventures?)\b", text, re.I)
    return m.group(1) if m else None


def _clean_label(label: str) -> str:
    label = re.sub(r"\s*\(\d+\)\s*$", "", label)          # a footnote marker
    label = re.sub(r"\s*[#*]+\s*$", "", label)
    return label.strip(" -:")


# a transaction row names what moved; a bare category row ("Member", "Chairman", "Meeting details") names nothing
TXN_WORDS = re.compile(r"\b(remuneration|salar(?:y|ies)|directors?.{0,20}(?:fees|remuneration)|payment|paid|"
                       r"received|receivable|payable|fees?|purchas\w*|sale|sales|sold|loan|advance|investment|"
                       r"dividend|interest|expense|reimburse\w*|transfer|royalty|rent|commission|contribution|"
                       r"deposit|borrowing|guarantee|income|charges?|proceeds|subscription|allotment)\b", re.I)


def _category_columns(lines: list[str], i: int, lex: dict):
    """The party-category header starting at line ``i``: [(category text, relationship)], the year columns, and
    the first row line.  A note that prints one column per party category ("Parent | Subsidiaries | Associate |
    Director") instead of the counterparty in the row is read through this shape."""
    cats: list[tuple[str, str]] = []
    years: list[int] = []
    j = i
    while j < min(i + 14, len(lines)):
        line = lines[j]
        if len(line) > 60 and not cats:
            return None                 # a sentence, not a column header
        for name, patterns in lex["party_categories"]:
            for pattern in patterns:
                for m in pattern.finditer(line):
                    if name != "total" and all(name != c[1] for c in cats):
                        cats.append((m.group(0).strip(), name))
        if _header_ok(line):
            years.extend(_year_tokens(line))
        j += 1
        if len(cats) >= 2 and years:
            break
    if len(cats) < 2:
        return None
    distinct: list[int] = []
    for year in years:
        if year not in distinct:
            distinct.append(year)
    return cats, [(f"FY{y % 100:02d}", f"{y}-03-31") for y in distinct[:2]], j


def category_rows(symbol: str, isin: str, entity: str, doc, page: int, text: str, lex: dict) -> list[dict]:
    """``related_party_txn`` rows of a party-category table: one row per row label and party category (and per
    year column when the category prints one), the category itself the counterparty."""
    lines = page_lines(text)
    basis = basis_of(text)
    fiscal_year = _doc_fy(doc)
    heads = []
    for i in range(len(lines)):
        head = _category_columns(lines, i, lex)
        if head:
            heads.append((i, head))
    if not heads:
        return []
    best = max(heads, key=lambda h: (len(h[1][1]), len(h[1][0])))
    cats, cols, start = best[1]
    if len(cats) < 3:
        return []
    # the category header must sit under the note's own wording, or a general table of the page is not a note
    if not any(re.search(r"related part|item/related", line, re.I) for line in lines[max(0, best[0] - 6):best[0] + 3]):
        return []
    if not cols:
        cols = [(fiscal_year, _fy_period(fiscal_year))] if fiscal_year else []
    if not cols:
        return []
    k = len(cols)
    width = len(cats) * k
    unit, scale = unit_of(" ".join(lines[:3]))
    rows: list[dict] = []
    pending: tuple[str, str] | None = None      # (label, quote): the values print on the next line
    for j in range(start, len(lines)):
        if _category_columns(lines, j, lex):
            break
        label, values = split_row(lines[j])
        label = _clean_label(label)
        if not label and values and pending is not None:
            row_label, row_quote, row_values = pending[0], pending[1], values
            pending = None
        elif label and values:
            row_label, row_quote, row_values = label, lines[j], values
            pending = None
        elif label:
            pending = (label, lines[j])
            continue
        else:
            continue
        if not row_label or len(row_label) > 100 or not re.match(r"[A-Za-z]", row_label) \
                or len(row_values) < width or " " not in row_label:
            continue
        if re.search(r"\b(?:annual report|integrated report|page \d+)\b", row_label, re.I):
            continue
        if not TXN_WORDS.search(row_label):
            continue                  # a category name or a column caption is not a transaction row
        is_balance = any(cue.search(row_label) for cue in lex["balance_cues"])
        for idx, token in enumerate(row_values[:width]):
            number = _num(token)
            if number is None:
                continue
            category, relationship = cats[idx // k]
            fy, period_end = cols[idx % k]
            rows.append({"symbol": symbol, "isin": isin, "fiscal_year": fy, "entity": entity, "basis": basis,
                         "counterparty": category, "relationship": relationship, "txn_type": row_label,
                         "amount": None if is_balance else number, "balance": number if is_balance else None,
                         "unit": unit, "scale": scale, "period_end": period_end, "doc_key": doc["doc_key"],
                         "page": page, "quote": (row_quote + " | " + row_label)[:MAX_QUOTE],
                         "known_at": doc["known_at"], "known_at_source": "doc.known_at",
                         "extractor_rule": "rpt_category_v1"})
    if len({r["counterparty"] for r in rows}) >= 2:
        return rows
    return []


def related_party_rows(symbol: str, isin: str, entity: str, doc, page: int, text: str, lex: dict) -> list[dict]:
    """``related_party_txn`` rows of one page: a related-party note with a two-year column header, each row a
    counterparty (or a party heading) and its printed year values.  The page cue is not required -- a note's
    continuation page prints only the table -- but a page must resolve at least three counterparties, so a
    two-column table of something else never becomes a transaction.  A note that prints one column per party
    category is read by ``category_rows``."""
    rows = _counterparty_rows(symbol, isin, entity, doc, page, text, lex)
    if rows:
        return rows
    return category_rows(symbol, isin, entity, doc, page, text, lex)


def _counterparty_rows(symbol: str, isin: str, entity: str, doc, page: int, text: str, lex: dict) -> list[dict]:
    lines = page_lines(text)
    blocks = table_blocks(lines)
    if not any(len(cols) >= 2 and len(block_rows) >= 3 for cols, block_rows, _h in blocks):
        return []
    basis = basis_of(text)
    rows: list[dict] = []
    for cols, block_rows, header_start in blocks:
        if len(cols) < 2:
            continue
        unit, scale = unit_of(" ".join(lines[max(0, header_start - 10):header_start + 2]))
        for row in block_rows:
            if len(row["values"]) != len(cols):
                continue
            label = _clean_label(row["label"])
            if not label or len(label) > 100 or not re.match(r"[A-Za-z]", label):
                continue
            if re.search(r"\b(?:annual report|integrated report|page \d+)\b", label, re.I):
                continue          # a running header/footer, not a counterparty
            heading = _clean_label(row["heading"] or "")
            named = lex["entity"].search(label)
            party = _party(label, lex)
            if named:
                counterparty = label
                txn_type = heading or None
                relationship = _relationship(heading, lex) if heading else None
            elif party and re.fullmatch(r"[A-Z][A-Za-z.'’()&-]*(?:\s+[A-Z][A-Za-z.'’()&-]*){1,4}", label):
                counterparty = label
                txn_type = heading or None
                relationship = _relationship(label, lex) or _relationship(heading, lex)
            elif party:
                counterparty = party
                txn_type = re.sub(r"^\s*" + re.escape(party) + r"\s*", "", label, flags=re.I) or label
                relationship = _relationship(label, lex)
                if not TXN_WORDS.search(txn_type):
                    continue        # a bare category row ("Member", "Chairman") is not a transaction
            elif _party(heading, lex) and heading:
                counterparty = _party(heading, lex)
                txn_type = label
                relationship = _relationship(heading, lex)
                if not TXN_WORDS.search(txn_type):
                    continue
            else:
                continue
            if txn_type and counterparty and txn_type.strip().lower() == counterparty.strip().lower():
                continue                  # a bare category line, not a transaction
            if counterparty and counterparty.startswith("-"):
                continue
            is_balance = any(cue.search(heading or label) for cue in lex["balance_cues"])
            for (fy, period_end), token in zip(cols, row["values"]):
                number = _num(token)
                if number is None:
                    continue
                rows.append({"symbol": symbol, "isin": isin, "fiscal_year": fy, "entity": entity, "basis": basis,
                             "counterparty": counterparty, "relationship": relationship or "related party",
                             "txn_type": txn_type, "amount": None if is_balance else number,
                             "balance": number if is_balance else None, "unit": unit, "scale": scale,
                             "period_end": period_end, "doc_key": doc["doc_key"], "page": page,
                             "quote": (row["quote"] + " | " + label)[:MAX_QUOTE], "known_at": doc["known_at"],
                             "known_at_source": "doc.known_at", "extractor_rule": "rpt_table_v1"})
    return rows


# --- the part -----------------------------------------------------------------------------------------------------
PAGE_EXTRACTORS = {
    "rating_event": rating_rows,
    "concentration": concentration_rows,
    "related_party_txn": related_party_rows,
}
_TABLES_OF_DOC_TYPE = {
    "annual_report": ("rating_event", "concentration", "related_party_txn"),
    "announcement": ("rating_event",),
}


def _entity_name(con: sqlite3.Connection, symbol: str) -> str:
    row = con.execute("SELECT name FROM company WHERE symbol=? AND name IS NOT NULL LIMIT 1", (symbol,)).fetchone()
    return row[0] if row else symbol


def _docs(con: sqlite3.Connection, symbol: str, doc_type: str):
    return con.execute(
        "SELECT doc_key, doc_type, isin, title, filing_date, known_at FROM doc WHERE symbol=? AND doc_type=? "
        "ORDER BY COALESCE(known_at, filing_date)", (symbol, doc_type)).fetchall()


def _prefilter_sql(words) -> str:
    clauses = " OR ".join("lower(text) LIKE ?" for _ in words)
    return f"SELECT page, text FROM doc_page WHERE doc_key=? AND ({clauses}) ORDER BY page"


RPT_NEAR = 4          # a related-party note continues up to this many pages past the last page with a cue


def run(out: str, symbols: list[str], limit_docs: int | None = None) -> dict:
    t0 = time.time()
    con = sqlite3.connect(out)
    con.row_factory = sqlite3.Row
    lex = lexicon()
    schema_ready = False
    ins: dict[str, str] = {}
    seen: dict[str, set] = {name: set() for name in NOTES}
    stats_all: dict = {}
    for symbol in symbols:
        for name in NOTES:
            if not con.execute("SELECT 1 FROM sqlite_master WHERE name=?", (name,)).fetchone():
                schema_ready = False
            else:
                con.execute(f"DELETE FROM {name} WHERE symbol=?", (symbol,))
        if not schema_ready:
            for name in NOTES:
                con.execute(TABLES[name].replace("CREATE TABLE ", "CREATE TABLE IF NOT EXISTS ", 1))
            for sql in NOTES_INDEXES:
                con.execute(sql)
            schema_ready = True
        for name in NOTES:
            ins.setdefault(name, f"INSERT INTO {name}({','.join(COLS[name])}) "
                                 f"VALUES({','.join('?' * len(COLS[name]))})")
        entity = _entity_name(con, symbol)
        st = stats_all[symbol] = Counter()
        symbol_started = time.time()
        for doc_type, names in _TABLES_OF_DOC_TYPE.items():
            words = [w.lower() for w in (lex["prefilter"].get(doc_type) or [])]
            for index, doc in enumerate(_docs(con, symbol, doc_type)):
                if limit_docs is not None and index >= limit_docs:
                    break
                docs_pages = con.execute("SELECT page, text FROM doc_page WHERE doc_key=? ORDER BY page",
                                         (doc["doc_key"],)).fetchall()
                follow = 0            # pages still inside the related-party note that started at a cue page
                for page_index, (page, text) in enumerate(docs_pages):
                    if not (text or "").strip():
                        continue
                    candidate = any(word in text.lower() for word in words)
                    if not candidate and follow <= 0:
                        continue
                    st["pages"] += 1
                    per_page: list[dict] = []
                    rpt: list[dict] = []
                    rpt_cue = any(cue.search(text) for cue in lex["rpt_cues"])
                    if doc_type == "annual_report" and (rpt_cue or follow > 0):
                        rpt = related_party_rows(symbol, doc["isin"], entity, doc, page, text, lex)
                        if any(r["unit"] is None for r in rpt):
                            unit, scale = page_unit(docs_pages, page_index)
                            for r in rpt:
                                if r["unit"] is None:
                                    r["unit"], r["scale"] = unit, scale
                        parties = {r["counterparty"] for r in rpt}
                        if len(parties) >= (1 if rpt_cue else 3):
                            follow = RPT_NEAR
                        else:
                            rpt = []
                            follow -= 1
                    if candidate and doc_type == "annual_report":
                        for name in names:
                            if name == "related_party_txn":
                                per_page.extend(rpt)
                            else:
                                per_page.extend(PAGE_EXTRACTORS[name](symbol, doc["isin"], entity, doc, page,
                                                                      text, lex))
                    elif doc_type == "annual_report":
                        per_page.extend(rpt)
                    elif candidate:
                        per_page.extend(trigger_rows(symbol, doc["isin"], entity, doc, page, text, lex))
                    for row in per_page:
                        name = ("rating_event" if row["extractor_rule"].startswith("rating_") else
                                "concentration" if row["extractor_rule"].startswith("conc_") else "related_party_txn")
                        sig = tuple(v for k, v in row.items() if k not in ("doc_key", "known_at",
                                                                           "known_at_source", "quote"))
                        if sig in seen[name]:
                            st["duplicate"] += 1
                            continue
                        seen[name].add(sig)
                        con.execute(ins[name], [row.get(c) for c in COLS[name]])
                        st[name] += 1
        con.commit()
        stats_all[symbol] = {**dict(st), "seconds": round(time.time() - symbol_started, 2)}
    stats_all["seconds"] = round(time.time() - t0, 1)
    stats_all["rows"] = {name: dict(con.execute(f"SELECT symbol, COUNT(*) FROM {name} GROUP BY symbol"))
                         for name in NOTES
                         if con.execute("SELECT 1 FROM sqlite_master WHERE name=?", (name,)).fetchone()}
    con.close()
    return stats_all


def main(argv=None):
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    ap.add_argument("--out", required=True)
    ap.add_argument("--symbols", default=None, help="default: every company of the profile, else every pilot3 company")
    ap.add_argument("--profile", default=None, help="build profile JSON (T-056): companies, pages db, raw root, output")
    ap.add_argument("--limit-docs", type=int, default=None)
    a = ap.parse_args(argv)
    if a.profile:
        profile.activate(profile.load(a.profile))
    symbols = [s.strip().upper() for s in (a.symbols or ",".join(profile.symbols())).split(",") if s.strip()]
    print(json.dumps(run(a.out, symbols, a.limit_docs), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
