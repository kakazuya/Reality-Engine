"""Independent row check layer for extracted rows (T-113; standing rule, Shivam 8 Nov).

The worker that wrote an extractor never checks it.  This module reads a built pilot3-style database READ-ONLY,
checks every ``guidance`` and ``kpi_series`` row with scripts that share nothing with the extractors (own number
parser, own label vocabulary ``row_checks_vocab.yaml``, own period arithmetic), and writes one verdict per row to a
separate output database:

    verified     every check that applies passed and the figure is pinned: for a kpi row that means an
                 independent second source (another document or the filed statements; an ``xbrl_segment``
                 row IS the filing), otherwise soft ``single_source``
    unverified   nothing failed, but something could not be pinned (served only with that label)
    quarantined  a hard check failed (never served)

Checks (``check`` names in ``row_check_fail``):
    quote_on_page     the stored quote is on the cited page (whitespace and case folded)
    value_present     the stored value (low / high for guidance) is a number in the quote
    value_scaled      the value appears only after a power-of-ten rescale (unit not pinned) -> unverified
    label_present     a label of the row's metric is in the quote
    label_conflict    another metric's label sits closer to the number than any label of the row's metric
    label_foreign     no label of the row's metric, a foreign label in the number's clause
    sector_fit        the metric belongs to the company's sector family
    third_party       (guidance) the number sits near system / industry / GDP / regulator wording
    forward_word      (guidance) the quote carries no forward word (expect, guide, target, ...)
    past_figure       (guidance) the number follows a realised-figure verb ("we grew at 12%")
    null_value        (guidance) no number stored
    range_order       low > high
    range_spread      (guidance) high / low > 3 (two figures merged into one range) -> unverified
    plausible         value outside the metric kind's bounds
    future_period     (kpi) a reported figure for a period that had not ended when it was known
    past_target       (guidance) a target for a period that had ended before it was said
    part_not_total    (kpi) dimension "total" but the amount is a small fraction of the filed figure
    period_word       (kpi) the number's sentence names a different period than the row
    currency          the label-to-number span prints another currency than the row's unit
    target_frame      (guidance) the number's sentence frames it as medium/long term or a CAGR while the
                      target_period is one fiscal year
    target_year       (guidance) the number's sentence prints a fiscal year that is not the target's year
    not_pinned        (guidance) verified needs all of: a strong label within 45 chars in the sentence; no scope
                      word between the label and the number; a forward word in the sentence; the target period in
                      the sentence or a this/next/full-year phrase with the doc date; no realised figure -> soft
    multi_number      (kpi) the quote holds several numbers, or its label is followed by more than 2 values of
                      the row's unit, so which column was taken is not pinned -> unverified unless corroborated
    history_row       (kpi) more than 5 values of the unit after the label (a long history row) -> verified only
                      via a filed figure
    scale_doubt       (kpi) an amount below 10 in inr_mn / inr_cr on a total revenue / PAT / EBITDA / capex / debt /
                      order row -> verified only via a filed figure
    cross_doc         (kpi) an independent witness (one that passes every hard check and is not multi_number)
                      gives a value more than 1.5% away for the same key
    fin_conflict      (kpi) the filed statements give a different figure for the same line and period
    not_company_speaker (kpi) the number sits in an analyst's question or wording ("you said", "can you", "?")
    range_value       (kpi) the number is one end of a printed range ("5 to 6000"), not a level
    unit_kind         (kpi) a days row without a days word, or a percent row without % / per cent / bps at the
                      number
    uncorroborated    (kpi) a total revenue / PAT / EBITDA / order amount with no filed statement and no second
                      source -> unverified
    net_cash_sign     (kpi/guidance) a net_debt row whose words say net cash with a positive value, or net debt
                      with a negative value the quote does not print as a minus / bracket
    page_unit         (kpi) the page's declared scale ("in million", "Rs. in Mn", "(in Crores)") is not the
                      row's unit
    same_doc_conflict (kpi) two rows of the same company / metric / scope / period from the SAME document
                      disagree by more than 1.5% after scale -> unverified (unless one is a variant)
    question_next     (kpi) the speaker cannot be found and the sentence after the number asks a question ->
                      unverified, never a quarantine
    variant           (kpi/guidance) pat/ebitda/revenue/net debt or a margin / ratio whose label says adjusted,
                      before exceptional, excluding, excl., ex-, pre/post Ind AS, of which, per ... -> unverified
    entity_mismatch   (kpi) the dimension and the entity name two different non-symbol subsidiaries -> unverified
    dimension_word    (kpi) a total row whose quote names a segment / business word just before its label ->
                      unverified
    scope_word        (kpi) the label-to-number span names a part scope (per store, facility, project, mix,
                      share, "of revenue", excluding ...) on a total row -> unverified

Round 10 (a hidden read of six unseen companies split the wrong verified kpi rows into six general classes):

    footnote_note     the number sits inside a footnote that starts between the metric's label and it
                      ("Net Debt *Includes investments in liquid funds and FDs of INR 3,165 crores")
    projection        (kpi) the number's sentence is a rating agency's estimate on a rating page, or a fiscal
                      year later than the row's own follows the number -> unverified
    regulated_rate    (kpi) the number's sentence is about "return on equity" and a regulator / tariff / allowed
                      / normative word: a regulated utility's permitted rate, not the company's earned ratio
    segment_scope     (kpi) a total row whose number's sentence names a segment / vertical -> unverified
    past_level        (kpi) the number's sentence names an earlier fiscal year, or frames a past level ("had
                      almost neared") -> unverified
    single_source     (kpi) nothing failed but no independent document or filed statement agrees -> unverified

Run:  python -m reality_engine.pilot3.row_checks --db D:/RealityEngine/pilot10/pilot10.db --out OUT.db
      [--profile tasks/night_loop/pilot10_profile.json] [--tables guidance,kpi_series]
      [--report DIR [--sample N --seed S --status verified]]
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import random
import re
import sqlite3
import statistics
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import yaml

VERSION = "row_checks_v2"
VOCAB_PATH = Path(__file__).with_name("row_checks_vocab.yaml")

HARD = {"list_order", "delta_value", "quote_on_page", "value_present", "label_present", "label_conflict", "label_foreign", "sector_fit", "third_party",
        "forward_word", "past_figure", "null_value", "range_order", "plausible", "future_period", "past_target",
        "fin_conflict", "part_not_total", "period_word", "currency", "target_frame", "target_year",
        "not_company_speaker", "range_value", "unit_kind", "net_cash_sign", "page_unit",
        "footnote_note", "regulated_rate"}
SOFT = {"value_scaled", "range_spread", "multi_number", "cross_doc", "no_vocab", "no_page_text",
        "unknown_sector", "label_weak", "label_context", "forward_context", "variant", "entity_mismatch",
        "dimension_word", "not_pinned", "scope_word", "uncorroborated", "history_row", "scale_doubt",
        "same_doc_conflict", "question_next", "projection", "segment_scope", "past_level", "single_source"}

# Revenue / PAT / EBITDA / order rows must be a plausible share of the company's filed figure: a subsidiary or
# segment amount stored with dimension "total" is the classic "part stored as the total" mistake.
_FAMILY_FILED = {"revenue": "revenue", "pat": "pat", "ebitda": "ebitda",
                 "order_intake": "revenue", "order_book": "revenue"}
_SCALE_FAMILIES = {"capex", "revenue", "pat", "ebitda", "net_debt", "order_intake", "order_book"}
PART_SHARE = 0.15


def connect_readonly(db: str) -> sqlite3.Connection:
    """Read-only connection.  A WAL database in a directory the caller cannot write to needs its -shm; the
    fallback opens the checkpointed file immutable (refused when a -wal with uncommitted pages is present).
    SQLite opens lazily, so the mode=ro handle is probed with one query before it is trusted."""
    con = None
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        con.execute("SELECT count(*) FROM sqlite_master")
        return con
    except sqlite3.OperationalError:
        if con is not None:
            con.close()
        if Path(db + "-wal").exists():
            raise
        return sqlite3.connect(f"file:{db}?mode=ro&immutable=1", uri=True)

# ---------------------------------------------------------------------------------------------- text helpers

_WS = re.compile(r"\s+")


def fold(text: str | None) -> str:
    """Lower case, NFKC, typographic dashes/quotes to ASCII, all whitespace to one space."""
    if not text:
        return ""
    t = unicodedata.normalize("NFKC", text)
    t = t.replace("\u2013", "-").replace("\u2014", "-").replace("\u2212", "-").replace("\u2019", "'")
    t = t.replace("\u2018", "'").replace("\u201c", '"').replace("\u201d", '"').replace("\ufffd", " ")
    return _WS.sub(" ", t).strip().lower()


def squash(text: str) -> str:
    """Fold and then drop every non-alphanumeric character: robust containment across line breaks and bullets."""
    return re.sub(r"[^0-9a-z]", "", fold(text))


# Own number reader: Indian and western grouping, decimals, a leading sign.  Returns (value, start, end).
_NUM = re.compile(r"(?<![\d,])(?<!\d\.)(?:\d{1,3}(?:,\d{2,3})+|\d+)(?:\.\d+)?|(?<![\d.A-Za-z])\.\d+")


def numbers_in(text: str) -> list[tuple[float, int, int]]:
    """Every number in ``text`` with its span.  Glued units are fine ("26%", "Rs.2,711", "INR11,000").  A '-' is a
    sign only at the start or after a space or '(' -- in "20%-22%" or "1.45%-1.60%" it is a range dash."""
    out = []
    for m in _NUM.finditer(text):
        raw = m.group(0).replace(",", "")
        try:
            val = float(raw)
        except ValueError:
            continue
        start = m.start()
        if start >= 1 and text[start - 1] == "-" and (start == 1 or text[start - 2] in " (\n"):
            val, start = -val, start - 1
        out.append((val, start, m.end()))
    return out


_DELTA = re.compile(r"(?:reduction|decrease|increase|decline|rise|improv(?:e|ed|es|ing|ement)|growth|drop)\s+(?:of|by)\s+(?:approximately|about|around|nearly|over|~)?\s*\W{0,3}$|(?:grew|rose|fell|declined|increased|decreased|improved|improve|reduced|up|down|higher|lower)\s+by\s+(?:approximately|about|around|nearly|over|~)?\s*\W{0,3}$")
_BREAK = re.compile(r"(?:\.|;|►|•|\|)\s+")
_MONTH = re.compile(r"\s*(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b")


def _is_year(x: float) -> bool:
    return x == int(x) and 1990 <= x <= 2040


def close(a: float, b: float, rel: float = 0.006) -> bool:
    if a == b:
        return True
    if a == 0 or b == 0:
        return abs(a - b) < 1e-9
    return abs(a - b) / max(abs(a), abs(b)) <= rel


def find_value(value: float, nums: list[tuple[float, int, int]]) -> tuple[str, int | None]:
    """('exact', pos) when the value is a number in the quote, ('scaled', pos) when it is one only after a
    power-of-ten rescale, ('absent', None) otherwise.  A negative value also matches its absolute number
    (quotes print losses as (12.3) or 'loss of 12.3')."""
    for n, s, _ in nums:
        if close(abs(n), abs(value)):
            return "exact", s
    for n, s, _ in nums:
        for k in (-7, -5, -3, -2, -1, 1, 2, 3, 5, 7):
            if close(abs(n) * 10 ** k, abs(value)):
                return "scaled", s
    return "absent", None


def delta_hit(text: str, value: float | None, nums: list[tuple[float, int, int]]) -> str | None:
    """A match of ``value`` that sits directly after a change verb ("improve by 1%", "grew by 12%"): the stored
    number is a delta, not the level.  Checking every occurrence avoids pinning the "1" inside "Q1"."""
    if value is None:
        return None
    for n, s, _ in nums:
        if close(abs(n), abs(value)):
            hit = _DELTA.search(text[max(0, s - 40):s])
            if hit:
                return hit.group(0).strip()
    return None


# ------------------------------------------------------------------------------------------------- periods

def period_end(label: str | None) -> str | None:
    """Last day of a fiscal period label (Indian April-March year): FY26, Q2FY27, H1FY26, 9MFY26."""
    if not label:
        return None
    m = re.fullmatch(r"(?:(Q[1-4])|(H[12])|(9M))?FY(\d{2})", label.strip().upper())
    if not m:
        return None
    yy = 2000 + int(m.group(4))
    q, h, nine = m.group(1), m.group(2), m.group(3)
    if q:
        return {"Q1": f"{yy-1}-06-30", "Q2": f"{yy-1}-09-30", "Q3": f"{yy-1}-12-31", "Q4": f"{yy}-03-31"}[q]
    if h:
        return f"{yy-1}-09-30" if h == "H1" else f"{yy}-03-31"
    if nine:
        return f"{yy-1}-12-31"
    return f"{yy}-03-31"


# --------------------------------------------------------------------------------------------- vocabulary

@dataclass
class Metric:
    name: str
    labels: list[re.Pattern]
    weak: list[re.Pattern]
    sectors: list[str] | None
    kind: str
    related: tuple[str, ...] = ()


@dataclass
class Vocab:
    metrics: dict[str, Metric]
    alias: dict[str, str]
    third_party: list[re.Pattern]
    forward: list[re.Pattern]

    def canon(self, metric: str) -> Metric | None:
        key = self.alias.get(metric)
        return self.metrics.get(key) if key else None


def load_vocab(path: Path = VOCAB_PATH) -> Vocab:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    metrics, alias = {}, {}
    for name, spec in raw["metrics"].items():
        m = Metric(name=name,
                   labels=[re.compile(p, re.I) for p in spec.get("labels", [])],
                   weak=[re.compile(p, re.I) for p in spec.get("weak", [])],
                   sectors=list(spec["sectors"]) if spec.get("sectors") else None,
                   kind=spec.get("kind", "any"), related=tuple(spec.get("related", ())))
        metrics[name] = m
        alias[name] = name
        for a in spec.get("aliases", []):
            alias[a] = name
    return Vocab(metrics, alias,
                 [re.compile(p, re.I) for p in raw.get("third_party", [])],
                 [re.compile(p, re.I) for p in raw.get("forward", [])])


def label_hits(metric: Metric, text: str) -> list[int]:
    """Positions (centre) of every strong label of ``metric`` in ``text``."""
    out = []
    for p in metric.labels:
        out += [(m.start() + m.end()) // 2 for m in p.finditer(text)]
    return out


_DENOM = re.compile(r"(?<=%)\s+of\s+(?:our|the|total|average|its)?\s*[a-z]+(?:\s+[a-z]+)?|(?:per ?cent|bps|basis points)\s+of\s+(?:our|the|total|average|its)?\s*[a-z]+(?:\s+[a-z]+)?|\bto\s+(?:net|gross|total|average)\s+[a-z]+")


def nearest(hits: list[int], pos: int) -> int | None:
    return min((abs(h - pos) for h in hits), default=None)


# Sentences, periods and the wording that changes what a figure means.  These are the checker's own patterns:
# nothing here is imported from an extractor or from lexicon/.
_SENT_BREAK = re.compile(r"[.!?](?:\s+|$)|[►•|]")
_PERIOD_TOKEN = re.compile(
    r"(?:\b(?P<q>q[1-4])\b|\b(?P<h>h[12])\b|\b(?P<nine>9m|nine\s+months?)\b|"
    r"\b(?P<half>half[- ]?year)\b|\b(?P<ytd>ytd|year[- ]to[- ]date)\b)"
    r"(?:\s*(?:fy\s*)?['’]?(?P<yy>\d{2,4}))?", re.I)
_PAST_VERB = re.compile(
    r"\b(?:grew|grow|grown|delivered|achieved|reported|posted|stood|came\s+in|declined|rose|fell|"
    r"reduced|improved)\s+(?:at|of|to)?\s*$")
_VARIANT = re.compile(r"before (?:exceptional|one[- ]off|one[- ]time)|adjusted|excluding|\bexcl\.?\b|"
                      r"\bex[- ]|\b(?:pre|post)[- ]?ind as\s*\d*\b|\bof which\b")
# "per share / tonne / franchise" makes a financial line a unit variant; on a margin / ratio it is scope, not
# a variant, and a table's "AUM per franchise" is another row's unit.
_VARIANT_PER = re.compile(r"(?<!as )\bper\s+(?!cent\b)")
# "IndAS116", "Ind-AS 116", "IND-AS" and "Ind AS 116" are the same qualifier; normalise before matching.
_IND_AS = re.compile(r"ind[\s\-]*as", re.I)


def normalise_ind_as(text: str) -> str:
    """'pre IndAS116', 'pre-Ind AS 116' and 'pre IND-AS' all compare as 'pre ind as 116'."""
    return _IND_AS.sub("ind as", text)
# wording between a period token and the number that makes the token a comparative, not the number's own period
_COMPARATIVE = re.compile(r"\b(?:over|against|versus|vs|from|than|compared|ahead\s+of|prior|last|previous|"
                          r"higher|lower|up|down)\b", re.I)
PERIOD_REACH = 60   # a token further from the number than this names another figure in the same sentence


def sentence_bounds(text: str, pos: int) -> tuple[int, int]:
    """The sentence around ``pos`` in folded text: split on . ! ? and on bullets / bars, but not at an
    abbreviation ("Rs. 80 crore") or an initial."""
    left = 0
    for m in _SENT_BREAK.finditer(text, 0, pos):
        if _abbreviation(text, m.start()):
            continue
        left = m.end()
    for m in _SENT_BREAK.finditer(text, pos):
        if _abbreviation(text, m.start()):
            continue
        return left, m.start()
    return left, len(text)


_ABBREV = re.compile(r"(?:\b(?:rs|mr|mrs|dr|ltd|co|inc|no|vs|fig|approx|pvt)|\b[a-z])\.$", re.I)


def _abbreviation(text: str, dot: int) -> bool:
    """True when the '.' at ``dot`` belongs to an abbreviation, not a sentence end."""
    return text[dot] == "." and bool(_ABBREV.search(text[max(0, dot - 7):dot + 1]))


def _two_digit_year(raw: str | None) -> str:
    """'FY2026' and 'FY26' both give '26'."""
    if not raw:
        return ""
    return raw[-2:] if len(raw) == 4 else raw


def period_key(label: str | None) -> str | None:
    """Canonical comparable key for a row's fiscal period: q2fy26, h1fy26, 9mfy26, fy26, ytd."""
    if not label:
        return None
    s = re.sub(r"\s+", "", label.upper())
    if s in ("YTD", "YEAR-TO-DATE"):
        return "ytd"
    m = re.fullmatch(r"(?:(Q[1-4])|(H[12])|(9M))?FY(\d{2})", s)
    if not m:
        return None
    head = (m.group(1) or m.group(2) or m.group(3) or "").lower()
    return head + "fy" + m.group(4)


def period_tokens(text: str, pos: int) -> tuple[set[str], set[str]]:
    """(tokens that name the number's own period, tokens named only in a comparative phrase such as
    "7.52%, an improvement over Q1 FY26").  A comparative token can still be the row's period (a comparative
    column extracted as its own row), so it is kept separately rather than dropped."""
    plain: set[str] = set()
    comparative: set[str] = set()
    for m in _PERIOD_TOKEN.finditer(text):
        if abs(m.start() - pos) > PERIOD_REACH:
            continue
        gap = text[m.end():pos] if m.end() <= pos else text[pos:m.start()]
        yy = _two_digit_year(m.group("yy"))
        suffix = "fy" + yy if yy else ""
        if m.group("q"):
            token = m.group("q").lower() + suffix
        elif m.group("h"):
            token = m.group("h").lower() + suffix
        elif m.group("nine"):
            token = "9m" + suffix
        elif m.group("half"):
            token = "h1" + suffix
        elif m.group("ytd"):
            token = "ytd"
        else:
            continue
        (comparative if _COMPARATIVE.search(gap) else plain).add(token)
    return plain, comparative


def period_matches(tokens: set[str], key: str) -> bool:
    for t in tokens:
        if t == key or (len(t) <= 3 and key.startswith(t)):
            return True
    return False


# The currency a figure is printed in: the nearest marker before the number wins ("$ 6,724 $ 5,176" is USD,
# "Rs 2,050 crore ($ 246 million)" is INR at the rupee number).  The row's unit must agree with it.
_CURRENCY = re.compile(
    r"(?P<usd>[$£€]|\bUSD\b|\bUS\s+dollars?\b|\bdollars?\b|\bEUR\b|\beuros?\b|\bGBP\b)"
    r"|(?P<inr>₹|`|\bRs\.?\b|\bINR\b|\bcrores?\b|\blakhs?\b)", re.I)

# A segment word from the company's own non-total dimensions, and a capitalised noun phrase ("Aluminium
# Upstream"), in the 60 characters before a total row's label.
_DIM_STOP = {"total", "other", "others", "segment", "business", "consolidated", "standalone",
             "finance", "financial", "services"}
_QUALIFIER = {"the", "our", "this", "that", "these", "those", "its", "their", "his", "her", "adjusted",
              "reported", "consolidated", "standalone", "underlying", "normalised", "normalized", "proforma",
              "estimated", "annualised", "annualized", "overall", "combined", "net", "gross", "total",
              "company", "business", "segment", "quarter", "year", "years", "months", "nine", "half",
              "first", "second", "third", "fourth", "in", "on", "at", "for", "from", "and", "of", "to",
              "with", "by", "as", "rs", "inr", "usd", "us", "fy", "h1", "h2", "q1", "q2", "q3", "q4"}
_CAP_PHRASE = re.compile(r"\b([A-Z][A-Za-z&.]{2,}(?:\s+[A-Z][A-Za-z&.]{2,}){1,3})\b")

# Guidance target frames: a multi-year frame or a quarter word in the number's own sentence, and an explicit
# fiscal year printed there, are compared with the row's target_period.
_MULTI_YEAR = re.compile(r"\b(?:medium|long)[- ]term\b|\bmedium\s+to\s+long[- ]term\b|\bcagr\b", re.I)
# a frame word about the past ("which has been our CAGR for the last 3 to 5 years") is not the target's frame
_FRAME_PAST = re.compile(r"\b(?:has been|have been|was|were|for the last|over the last|in the last)\b", re.I)
_FY_RANGE = re.compile(r"\b(?:fy\s*)?['’]?((?:19|20)?\d{2})\s*[-–/]\s*['’]?((?:19|20)?\d{2})\b", re.I)
_FY_TOKEN = re.compile(r"\b(?:fy|year)\s*['’]?((?:19|20)?\d{2})\b", re.I)

# Verified is a high bar: a reported figure ("was", "stood at", "for the quarter ended") does not govern a target,
# and a period phrase gives the target year only with the document date.
_ACTUAL = re.compile(r"\b(?:was|were|stood at|delivered|reported|posted|came in at|"
                     r"for the (?:quarter|nine months|9m|half[- ]year) ended)\b", re.I)
_YEAR_PHRASE = re.compile(r"\b(?:this|next|current|full)\s+(?:fiscal\s+)?year\b|\bthis fiscal\b|"
                          r"\bnext fiscal\b|\bfor the year\b|\bclose the year\b", re.I)
# A part scope between the label and the number makes a figure unpinnable for the company (or for the total row).
_SCOPE_WORD = re.compile(
    r"\b(?:facility|facilities|plant|plants|project|projects|maintenance|segment|segments|division|divisions|"
    r"international|domestic|mix|share|contribution|threshold)\b|\bexcluding\b|\bex[- ]|\bper\s+(?!cent\b)[a-z]+|"
    r"\b(?:of|for)\s+(?:the |this |our |total |last |next )*(?:year'?s? )?(?:revenue|sales|turnover)\b", re.I)

# KPI additions: an analyst's question is not the company's number, a printed range end is not a level, and a
# unit word has to stand next to the number.
_ANALYST_PHRASE = re.compile(r"\byou said\b|\bi wanted to understand\b|\bcan you\b|\bcould you\b|\bwhat is\b|"
                             r"\bwhat are\b|\bhow much\b|\bhow do\b|\bplease explain\b|\bwould you\b|"
                             r"\btrying to understand\b|\bmy question\b|\bjust wanted to\b", re.I)
_SPEAKER_LINE = re.compile(r"(?m)^[ \t]*([A-Z][A-Za-z .&'()\-]{1,60}?)\s*(?::|\s[-–]\s)")
# A speaker label is a person or a role, not prose that happens to start a line ("Coming to the order book
# status", "Some of the key highlights include", "FIVE"): the previous-page fallback exposed those.
_SPEAKER_ROLES = {"moderator", "analyst", "operator", "management", "host", "speaker", "participant",
                  "coordinator", "moderator/operator"}
_SPEAKER_STOP = {"the", "a", "an", "in", "on", "at", "for", "from", "with", "to", "of", "and", "or", "this",
                 "that", "these", "those", "our", "we", "it", "some", "all", "key", "highlights", "update",
                 "updates", "business", "segment", "performance", "demand", "status", "numbers", "company"}


def plausible_speaker(name: str) -> bool:
    tokens = [t for t in re.split(r"\s+", (name or "").strip()) if t]
    if not tokens or len(tokens) > 6:
        return False
    if len(tokens) == 1:
        return tokens[0].strip(".:").lower() in _SPEAKER_ROLES
    for token in tokens:
        if token.lower().strip(".,") in _SPEAKER_STOP or not token[0].isupper():
            return False
    return True
_MGMT_HEADING = re.compile(r"\b(management|company participants|executives|corporate participants|participants)\b", re.I)
_MGMT_ROLE = re.compile(r"\b(?:managing director|chief executive|chief financial|chief operating|chief technology|"
                        r"ceo|cfo|coo|cto|director|president|vice president|chairman|company secretary)\b", re.I)
_RANGE_BEFORE = re.compile(r"\d[\d,.]*\s*(?:to|[-–])\s*$")
_RANGE_AFTER = re.compile(r"\s*(?:to|[-–])\s*\d[\d,.]*")
_DAYS_WORD = re.compile(r"\b(?:days?|dso|dio|dpo)\b", re.I)
_PCT_WORD = re.compile(r"%|per ?cent|percent|bps|basis points", re.I)
_PAST_GOVERN = re.compile(r"\b(?:increased|grew|rose|fell|declined|delivered|achieved|reported|posted|stood|"
                          r"reached|recorded|witnessed|improved|reduced|decreased|was|were)\b", re.I)

# Round 10: six general classes from a hidden read of unseen companies.  A footnote's own amount, a rating
# agency's projection, a regulator's allowed rate, a segment named in a total row's quote, a nearer foreign
# label, and a past level in narrative.
_FOOTNOTE_MARK = re.compile(r"[*†‡]|\((?:[1-9]|1[0-9])\)")
_NOTE_PHRASE = re.compile(r"\b(?:includes?|excluding|excludes?|compris(?:es|ing)|net\s+of|represents|"
                          r"refer(?:\s+to)?\s+note|see\s+note|is\s+inclusive)\b", re.I)
_RATING_PAGE = re.compile(r"rating\s+(?:rationale|action|outlook|committee)|credit\s+rating|rating\s+agency|"
                          r"\b(?:icra|crisil|care(?:edge)?\s+ratings?|india\s+ratings|brickwork|acuite)\b", re.I)
_PROJECTION = re.compile(r"\bis\s+estimated\s+at\b|\bis\s+expected\s+to\b|\bexpected\s+to\s+"
                         r"(?:remain|be|improve|stay)\b|\bestimated\s+at\b|\bprojected\s+at\b|"
                         r"\bforecast\s+at\b|\bwe\s+expect\b|\boutlook\b|\brating\b", re.I)
_REGULATOR = re.compile(r"\b(?:regulators?|regulatory|tariffs?|allow(?:s|ed)?|normative|regulated|regulation|"
                        r"appellate|true[- ]?up|serc|cerc|nerc)\b", re.I)
_ROE_PHRASE = re.compile(r"\breturn\s+on\s+(?:average\s+)?(?:net\s*worth|equity)\b|\broe\b", re.I)
_SEGMENT_NOUN = re.compile(r"\b([a-z][a-z&'\-]{2,})\s+(?:business|vertical|segment|division|arm|subsidiary|"
                           r"franchise|portfolio)\b", re.I)
# words that qualify a whole-company noun ("our business", "the core business") rather than name a segment
_SEGMENT_STOP = {"the", "our", "this", "that", "these", "those", "its", "their", "your", "his", "her", "a", "an",
                 "and", "or", "of", "in", "on", "at", "for", "to", "with", "by", "from", "as", "is", "was",
                 "were", "are", "be", "been", "whole", "entire", "overall", "total", "combined", "consolidated",
                 "standalone", "core", "main", "key", "primary", "principal", "existing", "current", "new",
                 "same", "other", "others", "company", "group", "flagship", "growing", "larger", "largest",
                 "smaller", "one", "two", "each", "every", "all"}
_PAST_LEVEL = re.compile(r"\bback\s+in\b|\bpreviously\b|\bat\s+that\s+time\b|\byears?\s+earlier\b|"
                         r"\bhad\s+(?:almost\s+|nearly\s+)?(?:neared|nearing|touched|crossed|peaked|reached)\b|"
                         r"\b(?:was|were)\s+(?:nearing|approaching)\b", re.I)
_UNIT_WORD = {
    "pct": r"%|per ?cent|percent|bps|basis points",
    "bps": r"%|per ?cent|percent|bps|basis points",
    "days": r"\b(?:days?|dso|dio|dpo)\b",
    "inr": r"₹|`|\b(?:rs\.?|inr|crores?|cr|lakhs?|lakh|mn|bn|million|billion)\b",
    "usd": r"[$]|\b(?:usd|dollars?|million|billion|mn|bn)\b",
    "count": r"\b(?:million|mn|mm|crore|cr|lakh|units?|nos?|count)\b",
}

# A cumulative / year-to-date phrase in the number's own sentence contradicts a quarter row (round 8).
_CUMULATIVE = re.compile(
    r"\b(?:up[- ]to[- ]date|up[- ]to[- ]now|till\s+date|to\s+date|so\s+far|cumulative(?:ly)?|"
    r"since\s+(?:april|january|the\s+start|the\s+beginning|the\s+year\s+began)|"
    r"year[\s-]to[\s-]date|fytd|financial\s+year\s+to[\s-]date)\b", re.I)

# The sign a net-debt figure is printed with: "net cash" is the opposite of a positive net debt, and a negative
# net debt is right only when the quote prints the minus or a bracket (round 8).
_SIGN_WORD = re.compile(r"\b(?:net\s*cash(?:\s*positive)?|cash\s*surplus|net\s*(?:negative\s*)?debt|gross\s*debt|"
                        r"borrowings?)\b", re.I)
_CASH_POS = re.compile(r"\b(?:net\s*cash|net\s*cash\s*positive|cash\s*surplus)\b", re.I)

# A page-level scale declaration ("All amounts are in million of Indian Rupees", "(Rs. in Mn)", "(₹ Million)",
# "(in Crores)", "Rs. lakh"): the nearest one above the number sets the page's scale (round 8).
_PAGE_UNIT = re.compile(
    r"(?:all\s+)?(?:amounts?|figures?|numbers?|values?)\s+(?:are\s+)?(?:stated\s+)?in\s+"
    r"(?:rs\.?|inr|₹|`)?\s*(million|mn|billion|bn|crores?|cr|lakhs?|lacs?|thousand)\b"
    r"|(?:rs\.?|inr|₹|`)\s*\.?\s*in\s+(million|mn|billion|bn|crores?|cr|lakhs?|lacs?|thousand)\b"
    r"|\(\s*(?:in\s+)?(?:rs\.?|inr|₹|`)?\s*(?:in\s+)?(million|mn|billion|bn|crores?|cr|lakhs?|lacs?|thousand)\s*\)"
    r"|(?:rs\.?|inr|₹|`)\s*\.?\s*(million|mn|billion|bn|crores?|cr|lakhs?|lacs?|thousand)\b"
    r"|\bin\s+(million|mn|billion|bn|crores?|cr|lakhs?|lacs?|thousand)\s+(?:of\s+)?"
    r"(?:indian\s+rupees?|inr|rupees?)\b", re.I)
_MAGNITUDE_WORD = re.compile(r"\b(?:million|mn|billion|bn|crores?|cr|lakhs?|lacs?|thousand)\b", re.I)
_MAGNITUDE = {"million": "mn", "mn": "mn", "billion": "bn", "bn": "bn", "crore": "cr", "crores": "cr",
              "cr": "cr", "lakh": "lakh", "lakhs": "lakh", "lac": "lakh", "lacs": "lakh", "thousand": "thousand"}


def unit_family(text: str) -> str:
    """inr / usd / '' for a unit declaration or unit string.  A page that declares rupees says nothing about a
    row printed in dollars on the same page (a US-GAAP table under an Indian header), so only a declaration of
    the row's own currency can prove a scale error."""
    if re.search(r"[₹`]|\brs\.?\b|\binr\b|\brupees?\b|\bcrores?\b|\blakhs?\b|\blacs?\b", text or "", re.I):
        return "inr"
    if re.search(r"[$]|\busd\b|\bdollars?\b", text or "", re.I):
        return "usd"
    return ""

# The sentence right after the number asks a question: an analyst's follow-up, not the company's figure.
_QUESTION_NEXT = re.compile(r"\?|\b(?:trying to understand|could you|can you|would you|please explain|"
                            r"my question|just wanted to|how do you|how would you)\b", re.I)


def _as_year(raw: str) -> int | None:
    if not raw or not raw.isdigit():
        return None
    year = int(raw)
    if len(raw) == 2:
        year += 2000
    return year if 1990 <= year <= 2035 else None


def fiscal_years(text: str) -> set[str]:
    """Explicit fiscal years printed in one sentence: a range takes its end year ("20-21" -> fy21,
    "FY2024-2025" -> fy25), an FY token its own year; a comparative ("vs FY24") is not the number's target."""
    out: set[str] = set()
    spans: list[tuple[int, int]] = []
    for mm in _FY_RANGE.finditer(text):
        if _COMPARATIVE.search(text[max(0, mm.start() - 25):mm.start()]):
            continue
        if text[mm.end():mm.end() + 2].lstrip().startswith("%"):
            continue                       # "22-24%" is a percentage range, not fiscal years
        y1, y2 = _as_year(mm.group(1)), _as_year(mm.group(2))
        four_digit = any(len(g) == 4 for g in (mm.group(1), mm.group(2)))
        if y1 and y2 and (four_digit or mm.group(0).lstrip().lower().startswith("fy") or y2 == y1 + 1):
            out.add(f"fy{y2 % 100:02d}")
            spans.append(mm.span())
    for mm in _FY_TOKEN.finditer(text):
        if any(a <= mm.start() < b for a, b in spans):
            continue
        if _COMPARATIVE.search(text[max(0, mm.start() - 25):mm.start()]):
            continue
        year = _as_year(mm.group(1))
        if year:
            out.add(f"fy{year % 100:02d}")
    return out


def fiscal_ending_year(date: str | None) -> int | None:
    """Fiscal year end for a document date (Indian April-March): 2026-05-01 -> 2027."""
    if not date or len(date) < 7:
        return None
    try:
        year, month = int(date[0:4]), int(date[5:7])
    except ValueError:
        return None
    return year + 1 if month >= 4 else year


# "in FY23", "in fiscal 2026", "financial year 2025": a fiscal-year reference in words and digits, kept apart
# from fiscal_years() because a kpi row needs the year's distance from its own period, not a canonical label.
_FY_AFTER = re.compile(r"\b(?:fy|fiscal(?:\s+year)?|financial\s+year|year)\s*['’]?((?:19|20)\d{2}|\d{2})\b", re.I)


def period_fiscal_year(period: str | None) -> int | None:
    """The fiscal year a row's period belongs to: Q2FY26 -> 2026, FY25 -> 2025, ytd -> None."""
    key = period_key(period)
    mm = re.search(r"fy(\d{2})$", key or "")
    return 2000 + int(mm.group(1)) if mm else None


def plain_fiscal_years(text: str) -> set[int]:
    """Fiscal years printed as a plain (non-comparative) reference: 'in FY23', 'in fiscal 2026'.  A range takes
    its end year ('FY 2025-26' is 2026), and a year named in a comparative ('vs FY24', 'up from the year 2024')
    is another figure's year, not this sentence's."""
    out: set[int] = set()
    spans: list[tuple[int, int]] = []
    for mm in _FY_RANGE.finditer(text):
        if _COMPARATIVE.search(text[max(0, mm.start() - 25):mm.start()]):
            continue
        y1, y2 = _as_year(mm.group(1)), _as_year(mm.group(2))
        four_digit = any(len(g) == 4 for g in (mm.group(1), mm.group(2)))
        if y1 and y2 and (four_digit or mm.group(0).lstrip().lower().startswith("fy") or y2 == y1 + 1):
            out.add(y2)
            spans.append(mm.span())
    for mm in _FY_AFTER.finditer(text):
        if any(a <= mm.start() < b for a, b in spans):
            continue
        if _COMPARATIVE.search(text[max(0, mm.start() - 25):mm.start()]):
            continue
        raw = mm.group(1)
        out.add(int(raw) if len(raw) == 4 else 2000 + int(raw))
    return out


def nearest_strong_label(m: Metric, text: str, pos: int, lo: int = 0,
                         hi: int | None = None) -> tuple[int, int, int] | None:
    """(signed distance, start, end) of the strong label of ``m`` nearest the number, inside [lo, hi]."""
    hi = len(text) if hi is None else hi
    best: tuple[int, int, int] | None = None
    for pattern in m.labels:
        for mm in pattern.finditer(text):
            if mm.start() < lo or mm.end() > hi:
                continue
            dist = pos - mm.end() if mm.end() <= pos else mm.start() - pos
            if best is None or abs(dist) < abs(best[0]):
                best = (dist, mm.start(), mm.end())
    return best


# ----------------------------------------------------------------------------------------------- bounds

def plausible(kind: str, metric: str, lo: float | None, hi: float | None, unit: str) -> bool:
    u = (unit or "").lower()
    vals = [v for v in (lo, hi) if v is not None]
    if not vals:
        return True
    if kind == "level_pct" or (kind in ("bps_or_pct", "any") and u == "pct"):
        return all(-100 <= v <= 100 for v in vals)
    if kind == "growth_pct":
        return all(-100 <= v <= 400 for v in vals) if u in ("pct", "") else True
    if kind == "bps_or_pct":
        return all(-1000 <= v <= 3000 for v in vals) if u == "bps" else True
    if kind == "days":
        return all(-400 <= v <= 1500 for v in vals)
    if kind == "multiple":
        return all(-50 <= v <= 200 for v in vals)
    return True


# ------------------------------------------------------------------------------- filed-statement scale
# A store that prints "₹ in mn" / "rs lakh" but leaves scale=1 is reporting a number that is not rupees: the
# printed unit's scale is the trustworthy one (round 9).  An ambiguous unit text names two scales and is no
# witness at all.
_UNIT_SCALE = {"bn": 1e9, "billion": 1e9, "mn": 1e6, "million": 1e6,
               "cr": 1e7, "crore": 1e7, "crores": 1e7,
               "lakh": 1e5, "lakhs": 1e5, "lac": 1e5, "lacs": 1e5}
MICRO_FILED = 1e7        # Rs 1 crore
BIG_REVENUE = 1e9        # Rs 100 crore


def unit_scales(unit: str | None) -> set[float]:
    """The rupee scales a unit text names ("₹ in mn" -> {1e6}, "rs lakh" -> {1e5}); empty when it names none."""
    return {_UNIT_SCALE[t] for t in re.findall(r"[a-z]+", (unit or "").lower()) if t in _UNIT_SCALE}


def filed_rupees(value: float | None, unit: str | None, scale: float | None) -> float | None:
    """Rupee amount of a filed line, or None when the row cannot witness anything: a unit that names exactly one
    scale is the scale (a store's scale=1 beside "in mn" is a bug), an ambiguous unit text or a non-positive
    value is dropped."""
    if value is None or value <= 0:
        return None
    scales = unit_scales(unit)
    if len(scales) > 1:
        return None
    if scales:
        return value * next(iter(scales))
    return value * (scale if scale not in (None, 0) else 1)


# ------------------------------------------------------------------------------------------- the checker

@dataclass
class Verdict:
    table: str
    row_id: int
    symbol: str
    metric: str
    canon: str
    sector: str
    doc_type: str
    rule: str
    status: str = "verified"
    fails: list[tuple[str, str]] = field(default_factory=list)
    corroborated: bool = False
    filed_only: bool = False

    def fail(self, check: str, why: str) -> None:
        self.fails.append((check, why))


class Checker:
    def __init__(self, db: str, sectors: dict[str, str], vocab: Vocab | None = None):
        self.con = connect_readonly(db)
        self.con.row_factory = sqlite3.Row
        self.vocab = vocab or load_vocab()
        self.sectors = sectors
        self._page: dict[tuple[str, int], str | None] = {}
        self._page_fold: dict[tuple[str, int], str] = {}
        self._page_squash: dict[tuple[str, int], str] = {}
        self.doc_type = {r["doc_key"]: (r["doc_type"] or "") for r in self.con.execute("SELECT doc_key, doc_type FROM doc")}
        self.company_words = {(r["symbol"] or "").upper(): {w.lower() for w in re.findall(r"[A-Za-z]{3,}", r["name"] or "")}
                              for r in self.con.execute("SELECT symbol, name FROM company")}
        self._mgmt: dict[str, str] = {}
        self._witness_cache: dict[int, bool] = {}

    # -- shared --
    def page_text(self, doc_key: str, page: int) -> str | None:
        key = (doc_key, page)
        if key not in self._page:
            r = self.con.execute("SELECT text FROM doc_page WHERE doc_key=? AND page=?", key).fetchone()
            self._page[key] = r[0] if r and r[0] else None
        return self._page[key]

    def page_fold(self, doc_key: str, page: int) -> str:
        key = (doc_key, page)
        if key not in self._page_fold:
            self._page_fold[key] = fold(self.page_text(doc_key, page) or "")
        return self._page_fold[key]

    def page_squash(self, doc_key: str, page: int) -> str:
        """The squashed page text, computed once per page (check_quote squashes it for every row)."""
        key = (doc_key, page)
        if key not in self._page_squash:
            self._page_squash[key] = squash(self.page_text(doc_key, page) or "")
        return self._page_squash[key]

    def context_before(self, doc_key: str, page: int, quote: str, n: int = 500) -> str:
        """Folded page text just before the quote (the question asked, the previous sentence), '' if not found."""
        text = self.page_fold(doc_key, page)
        q = fold(quote)
        for cut in (q[:40], q[:25], q[-25:]):
            if cut and (i := text.find(cut)) >= 0:
                return text[max(0, i - n): i]
        return ""

    def check_quote(self, v: Verdict, quote: str, doc_key: str, page: int) -> None:
        text = self.page_text(doc_key, page)
        if text is None:
            v.fail("no_page_text", f"{doc_key} p{page} has no page text")
            return
        q, t = squash(quote), self.page_squash(doc_key, page)
        if not q:
            v.fail("quote_on_page", "empty quote")
        elif q not in t:
            # a quote that joins two sentences or trims a bullet: accept when 90% of its 40-char shingles are on the page
            sh = [q[i:i + 40] for i in range(0, max(1, len(q) - 39), 20)]
            hit = sum(1 for s in sh if s in t)
            if hit / len(sh) < 0.9:
                v.fail("quote_on_page", f"{hit}/{len(sh)} quote pieces on the page")

    def check_sector(self, v: Verdict, m: Metric | None) -> None:
        if m is None or not m.sectors:
            return
        if v.sector in ("", "unknown"):
            v.fail("unknown_sector", "company has no sector family; sector fit not checked")
            return
        if v.sector not in m.sectors:
            v.fail("sector_fit", f"{m.name} belongs to {'/'.join(m.sectors)}, company is {v.sector}")

    def check_label(self, v: Verdict, m: Metric | None, text: str, pos: int | None, context: str = "") -> None:
        if m is None:
            v.fail("no_vocab", f"metric {v.metric} has no checker vocabulary")
            return
        # a denominator ("2% of revenue") names the base, not the metric: it is not a label of this row.  When the
        # denominator is the metric's own name ("17% of EBITDA margin"), it is the label and stays.
        words = [w for w in re.split(r"[^a-z]+", m.name) if len(w) > 2]

        def keep(mm: re.Match) -> str:
            span = mm.group(0).lower()
            return mm.group(0) if words and all(w in span for w in words) else " " * len(mm.group(0))

        own = label_hits(m, _DENOM.sub(keep, text))
        if not own and pos is not None:
            # the clause around the number names ANOTHER metric and never this one: the number is that metric's
            # ("Return on assets is estimated at 4.4%-4.6%" stored as credit cost).  A word that is also one of
            # this metric's weak labels is not foreign: "Domestic sales were at 538,994" is a volume, though
            # "sales" is a strong revenue label too.  A label AFTER a weakly-present number belongs to the next
            # figure, not this one ("leverage ratio at 3.5x and liquidity of $2.9 billion").
            weak_present = any(p.search(text) for p in m.weak)
            lo_w, hi_w = max(0, pos - 160), pos + 60
            masked_w = _DENOM.sub(lambda mm: " " * len(mm.group(0)), text)
            for other in self.vocab.metrics.values():
                if other.name == m.name or other.name in m.related or m.name in other.related:
                    continue
                hit = next((mm for p in other.labels for mm in p.finditer(masked_w)
                            if lo_w <= mm.start() < hi_w and not (weak_present and mm.start() > pos)
                            and not any(w.search(mm.group(0)) for w in m.weak)), None)
                if hit:
                    v.fail("label_foreign", f"the number's clause names {other.name} ('{hit.group(0)}'), never {m.name}")
                    return
        if not own:
            if any(p.search(text) for p in m.weak):
                v.fail("label_weak", "only a generic label of the metric in the quote")
                own = [(mm.start() + mm.end()) // 2 for p in m.weak for mm in p.finditer(text)]
            elif context and label_hits(m, context):
                # the metric is named just before the quote (the analyst's question, the previous sentence):
                # plausible, but the quote alone does not pin it
                v.fail("label_context", f"{m.name} named only in the text before the quote")
                return
            else:
                v.fail("label_present", f"no label of {m.name} in the quote or just before it")
                return
        if pos is None:
            return
        # a denominator ("2.5% of our revenues", "40 bps of AUM") names the base, not the metric: blank it
        masked = _DENOM.sub(lambda mm: " " * len(mm.group(0)), text)
        own_spans = [(mm.start(), mm.end()) for p in m.labels for mm in p.finditer(text)] or                     [(mm.start(), mm.end()) for p in m.weak for mm in p.finditer(text)]
        anchor = min(own, key=lambda h: abs(h - pos))
        lo, hi = sorted((anchor, pos))
        # a competing label counts only when it sits BETWEEN the row's own nearest label and the number, is not
        # part of the row's own label ("net debt / EBITDA" holds "EBITDA"), and is not a related metric
        for other in self.vocab.metrics.values():
            if other.name == m.name or other.name in m.related or m.name in other.related:
                continue
            for p in other.labels:
                for mm in p.finditer(masked):
                    c = (mm.start() + mm.end()) // 2
                    if not (lo < c < hi):
                        continue
                    if any(a - 2 <= mm.start() and mm.end() <= b + 2 for a, b in own_spans):
                        continue
                    if any(a - 2 <= c <= b + 2 for a, b in own_spans):
                        continue
                    qual = _VARIANT.search(text[min(lo, hi):max(lo, hi)])
                    if qual:
                        # "EBITDA pre Ind AS & excl. other income": the foreign label sits inside a qualifier
                        # phrase, which makes the row a variant (soft), not a different metric (hard)
                        if not any(c == "variant" for c, _ in v.fails):
                            v.fail("variant", f"a qualifier phrase '{qual.group(0).strip()}' sits between the "
                                              f"{m.name} label and the number")
                        return
                    if self.list_order_ok(m, masked, pos):
                        return
                    v.fail("label_conflict", f"label '{mm.group(0)}' of {other.name} sits between the {m.name} label and the number")
                    return

    def check_list(self, v: Verdict, m: Metric | None, text: str, pos: int | None, context: str) -> None:
        """A 'Gross NPA and Net NPA stood at a% and b% ... as against c% and d%' list whose head the quote cut off:
        rebuild it from the text just before the quote and check the number's place in it."""
        if m is None or pos is None:
            return
        tail = context[-160:]
        ext = tail + " " + text
        epos = pos + len(tail) + 1
        masked = _DENOM.sub(lambda mm: " " * len(mm.group(0)), ext)
        # the list's own sentence: walk back over sentence breaks until the piece before the number names a metric
        starts = [0] + [mm.end() for mm in _BREAK.finditer(masked, 0, epos)]
        for st in reversed(starts):
            if any(p.search(masked, st, epos) for p in m.labels):
                masked, epos = masked[st:], epos - st
                break
        names = self._list_names(masked, epos)
        if len(names) >= 2 and m.name in names and not self.list_order_ok(m, masked, epos):
            v.fail("list_order", f"listed {' / '.join(names)}: the number holds another metric's place")

    def _list_names(self, text: str, pos: int) -> list[str]:
        """Metric labels named one after another (joined by and / & / ,) before the first value number."""
        first_num = next((n[1] for n in numbers_in(text) if not _is_year(n[0]) and not _MONTH.match(text, n[2])
                          and not (n[1] > 0 and text[n[1] - 1].isalpha())
                          and not _DELTA.search(text[max(0, n[1] - 40):n[1]])), pos)
        hits = []
        for other in self.vocab.metrics.values():
            for p in other.labels:
                for mm in p.finditer(text):
                    if mm.end() <= first_num:
                        hits.append((mm.start(), mm.end(), other.name))
        hits.sort()
        names: list[str] = []
        last = None
        for a, b, name in hits:
            if last and a < last[1]:
                continue
            if last and names and name != names[-1]:
                gap = text[last[1]:a]
                if not re.fullmatch(r"[\s\-()'a-z]{0,25}?(and|&|,)[\s()'a-z]{0,25}", gap):
                    names = []
            if not names or names[-1] != name:
                names.append(name)
            last = (a, b)
        return names

    def list_place(self, m: Metric, text: str, pos: int) -> bool | None:
        """'Gross NPA and Net NPA stood at 1.33% and 0.53% respectively, as against 1.59% and 0.77%': labels listed
        first, numbers after in the same order (repeated for comparatives).  True when the row's number holds the
        row's label's place, False when it holds another's, None when the quote is no list (fewer values than
        labels printed, so the labels are not parallel values of one list)."""
        hits = []
        for other in self.vocab.metrics.values():
            for p in other.labels:
                for mm in p.finditer(text):
                    if mm.start() < pos:
                        hits.append((mm.start(), mm.end(), other.name))
        hits.sort()
        names: list[str] = []
        last_end = -1
        for a, b, name in hits:
            if a < last_end:          # overlapping hit of a longer label already taken
                continue
            if not names or names[-1] != name:
                names.append(name)
            last_end = b
        if len(names) < 2 or m.name not in names:
            return False
        # a change ("improved by 27 basis points") and a quarter label ("Q2") are not listed levels
        after = [n for n in numbers_in(text) if n[1] >= last_end and not _is_year(n[0]) and not _MONTH.match(text, n[2])
                 and not (n[1] > 0 and text[n[1] - 1].isalpha())
                 and not _DELTA.search(text[max(0, n[1] - 40):n[1]])]
        if len(after) < 2:
            return None
        idx = next((i for i, n in enumerate(after) if n[1] == pos), None)
        return idx is not None and idx % len(names) == names.index(m.name)

    def list_order_ok(self, m: Metric, text: str, pos: int) -> bool:
        """True when the row's number holds the row's label's place in a printed list, or the quote prints fewer
        values than labels (the list test does not apply rather than failing the row)."""
        return self.list_place(m, text, pos) is not False

    def check_part(self, v: Verdict, canon: str, amount: float | None, unit: str, symbol: str, period: str,
                   rid: int, fin: dict, usd_rev: dict) -> None:
        """dimension 'total' but the amount is only a small part of the company's figure (a subsidiary or a
        product line stored as the whole).  USD revenue has no filed rupee line: compare with the company's other
        revenue rows for the same period, where a part sits far below the median."""
        if canon not in _FAMILY_FILED or amount is None:
            return
        unit = (unit or "").lower()
        if canon == "revenue" and unit.startswith("usd"):
            peers = [a for i, a in usd_rev.get((symbol, period), ()) if i != rid]
            if len(peers) >= 2:
                med = statistics.median(peers)
                if med > 0 and abs(amount) < PART_SHARE * med:
                    v.fail("part_not_total", f"{amount / 1e6:.0f} mn is {abs(amount) / med:.0%} of the "
                                             f"{med / 1e6:.0f} mn peer median for {period}")
            return
        if not unit.startswith("inr"):
            return
        filed = fin.get((symbol, period, _FAMILY_FILED[canon]))
        if not filed:
            return
        anchor = max(filed, key=abs)
        if anchor and abs(amount) < PART_SHARE * abs(anchor):
            v.fail("part_not_total", f"{amount / 1e7:.0f} cr is under {PART_SHARE:.0%} of the filed "
                                     f"{_FAMILY_FILED[canon]} {anchor / 1e7:.0f} cr for {period}")

    def check_period_word(self, v: Verdict, text: str, pos: int | None, fiscal_period: str, rule: str = "") -> None:
        """The number's own sentence names a period (Q2 FY26, H1, nine months, YTD): the row must hold it.  A
        table/chart quote has no sentence and its dates are column headers outside the quote: skip those."""
        key = period_key(fiscal_period)
        if key is None or pos is None or rule in ("table_v1", "chart_v1"):
            return
        lo, hi = sentence_bounds(text, pos)
        plain, comparative = period_tokens(text[lo:hi], pos - lo)
        if plain and not period_matches(plain, key) and not period_matches(comparative, key):
            v.fail("period_word", f"the number's sentence names {'/'.join(sorted(plain))}, row is {fiscal_period}")
        elif key.startswith("q") and "ytd" not in plain and "ytd" not in comparative:
            hit = _CUMULATIVE.search(text[lo:min(hi, pos + 40)])
            if hit:
                v.fail("period_word", f"the number's sentence is cumulative ('{hit.group(0).strip()}'), "
                                      f"row is {fiscal_period}")

    def check_net_cash_sign(self, v: Verdict, m: Metric | None, text: str, pos: int | None,
                            value: float | None) -> None:
        """A net_debt row's sign: "net cash" printed with a positive value, or "net debt" printed with a negative
        value the quote does not show as a minus / bracket, is the opposite of the words printed."""
        if m is None or m.name != "net_debt" or pos is None or not value:
            return
        lo, _ = sentence_bounds(text, pos)
        hits = list(_SIGN_WORD.finditer(text[lo:pos]))
        if not hits:
            return
        last = hits[-1]
        if value > 0 and _CASH_POS.search(last.group(0)):
            v.fail("net_cash_sign", f"the quote says '{last.group(0).strip()}' but the value is stored +{value:g}")
        elif value < 0 and not _CASH_POS.search(last.group(0)):
            printed = (pos < len(text) and text[pos] == "-") or (pos > 0 and text[pos - 1] in "(-") \
                or bool(re.search(r"\b(?:minus|negative)\b[^.;]{0,15}$", text[max(0, pos - 30):pos]))
            if not printed:
                v.fail("net_cash_sign", f"the quote says '{last.group(0).strip()}' but the value is stored "
                                        f"{value:g} without a printed minus or bracket")

    def check_page_unit(self, v: Verdict, text: str, pos: int | None, doc_key: str, page: int, quote: str,
                        unit: str) -> None:
        """The page declares one scale above the table ("All amounts are in million of Indian Rupees",
        "(Rs. in Mn)", "(in Crores)"); a row whose unit names another scale is a rescale error, unless the quote
        prints its own scale word at the number."""
        m_u = re.fullmatch(r"(?:inr|usd)_(mn|cr|bn|lakh|thousand)", (unit or "").lower())
        if pos is None or not m_u:
            return
        if _MAGNITUDE_WORD.search(text[max(0, pos - 60):pos + 40]):
            return
        decl = None
        for mm in _PAGE_UNIT.finditer(self.context_before(doc_key, page, quote, 3000)):
            decl = mm
        if decl is None:
            return
        raw = next((g for g in decl.groups() if g), "")
        declared = _MAGNITUDE.get(raw.lower().rstrip("s"), "")
        declared_family = unit_family(decl.group(0))
        row_family = "usd" if (unit or "").lower().startswith("usd") else "inr"
        if declared_family and declared_family != row_family:
            return
        if declared and declared != m_u.group(1):
            v.fail("page_unit", f"the page declares '{decl.group(0).strip()}' but the row unit is {unit}")

    def check_question_next(self, v: Verdict, text: str, pos: int | None) -> None:
        """The speaker could not be found; a question in the sentence right after the number means the figure is
        at most unverified, never a quarantine."""
        if pos is None:
            return
        _, hi = sentence_bounds(text, pos)
        if hi >= len(text) - 1:
            return
        _, hi2 = sentence_bounds(text, hi + 1)
        hit = _QUESTION_NEXT.search(text[hi + 1:hi2])
        if hit:
            v.fail("question_next", f"the sentence after the number asks ('{hit.group(0).strip()}')")

    def check_variant(self, v: Verdict, m: Metric | None, text: str, pos: int | None) -> None:
        """A pat / ebitda / revenue / net-debt figure, or a margin / ratio, labelled adjusted, before exceptional /
        one-time, excluding, excl., ex-, pre/post Ind AS, of which, or per (share / tonne / franchise) is not the
        plain line unless the metric itself says so."""
        if m is None or pos is None:
            return
        if re.search(r"adjusted|_per_|excl|pre[_ -]?ind|post[_ -]?ind", (v.metric or "").lower()):
            return
        if not (m.name in ("revenue", "pat", "ebitda", "net_debt")
                or m.kind in ("level_pct", "bps_or_pct", "multiple", "per_unit")):
            return
        if any(c == "variant" for c, _ in v.fails):
            return
        window = normalise_ind_as(text[max(0, pos - 90):pos + 30])
        hit = _VARIANT.search(window)
        if hit is None and m.name in ("revenue", "pat", "ebitda", "net_debt"):
            hit = _VARIANT_PER.search(window)
        if hit:
            v.fail("variant", f"the label says '{hit.group(0)}', not the plain {m.name}")

    def check_target_frame(self, v: Verdict, text: str, pos: int | None, period: str) -> None:
        """The number's own sentence frames it as medium/long term or a CAGR while the row's target_period is
        one fiscal year: the frame and the target disagree."""
        key = period_key(period)
        if key is None or pos is None:
            return
        lo, hi = sentence_bounds(text, pos)
        sent = text[lo:hi]
        for hit in _MULTI_YEAR.finditer(sent):
            if _FRAME_PAST.search(sent[max(0, hit.start() - 45):hit.start()]):
                continue
            v.fail("target_frame", f"the number's sentence frames it as '{hit.group(0).strip()}', target is {period}")
            return

    def check_target_year(self, v: Verdict, text: str, pos: int | None, period: str) -> None:
        """The number's sentence prints a fiscal year or a fiscal-year range that is not the target's year."""
        key = period_key(period)
        if key is None or pos is None:
            return
        m = re.search(r"fy(\d{2})$", key)
        if not m:
            return
        target = "fy" + m.group(1)
        lo, hi = sentence_bounds(text, pos)
        years = fiscal_years(text[lo:hi])
        if years and target not in years:
            v.fail("target_year", f"the number's sentence names {sorted(years)}, target is {period}")

    def scope_hit(self, m: Metric | None, span: str, metric: str) -> str | None:
        """A part-scope word in the label-to-number span, unless this row is that part (per-unit metric, a ratio
        of revenue, or the metric's own name says the scope)."""
        name = (metric or "").lower()
        per_ok = (m is not None and m.kind == "per_unit") or "_per_" in name
        ratio_ok = (m is not None and m.kind in ("level_pct", "bps_or_pct", "multiple"))
        for mm in _SCOPE_WORD.finditer(span):
            word = mm.group(0).strip().lower()
            if word.startswith("per ") and per_ok:
                continue
            if word.startswith("of ") and ratio_ok:
                continue
            key = word.split()[0].strip("-")
            if key and key in name:
                continue
            return word
        return None

    def check_scope_word(self, v: Verdict, m: Metric | None, text: str, pos: int | None, metric: str) -> None:
        """A total kpi row whose label-to-number span names a part scope ("per store", "facility", "of revenue")."""
        if m is None or pos is None:
            return
        label = nearest_strong_label(m, text, pos)
        if label is None or abs(label[0]) > 80:
            return
        _, start, end = label
        span = (text[end:pos] if end <= pos else text[pos:start]) + " " + text[pos:pos + 30]
        word = self.scope_hit(m, span, metric)
        if word:
            v.fail("scope_word", f"the label-to-number span names scope '{word}'")

    def period_stated(self, sent: str, period: str, doc_date: str | None) -> bool:
        """The target period is printed in the sentence, or the sentence anchors "this/next/full year" and the
        document date gives that fiscal year."""
        key = period_key(period)
        if key is None:
            return bool(_MULTI_YEAR.search(sent) and (period or "").lower() in ("medium_term", "long_term"))
        for mm in _PERIOD_TOKEN.finditer(sent):
            yy = _two_digit_year(mm.group("yy"))
            suffix = "fy" + yy if yy else ""
            if mm.group("q"):
                token = mm.group("q").lower() + suffix
            elif mm.group("h"):
                token = mm.group("h").lower() + suffix
            elif mm.group("nine"):
                token = "9m" + suffix
            elif mm.group("half"):
                token = "h1" + suffix
            elif mm.group("ytd"):
                token = "ytd"
            else:
                continue
            if token == key:
                return True
            if len(token) <= 3 and key.startswith(token) and f"fy{key[-2:]}" in fiscal_years(sent):
                return True
        if key.startswith("fy") and key in fiscal_years(sent):
            return True
        m = _YEAR_PHRASE.search(sent)
        if m:
            base = fiscal_ending_year(doc_date)
            if base is not None:
                target = base + 1 if m.group(0).lower().startswith("next") else base
                if key == f"fy{target % 100:02d}":
                    return True
        return False

    def check_pinned(self, v: Verdict, m: Metric | None, text: str, pos: int | None, period: str,
                     doc_date: str | None) -> None:
        """Verified needs all of a-e; anything missing is soft not_pinned, never a quarantine."""
        if m is None or pos is None:
            return
        lo, hi = sentence_bounds(text, pos)
        sent = text[lo:hi]
        why: list[str] = []
        label = nearest_strong_label(m, text, pos, lo, hi)
        if label is None or abs(label[0]) > 45:
            why.append("a: no strong label within 45 chars in the sentence")
        if label is not None:
            _, start, end = label
            span = (text[end:pos] if end <= pos else text[pos:start]) + " " + text[pos:pos + 30]
            word = self.scope_hit(m, span, v.metric)
            if word:
                why.append(f"b: scope word '{word}'")
        if not any(p.search(sent) for p in self.vocab.forward):
            why.append("c: no forward word in the sentence")
        if not self.period_stated(sent, period, doc_date):
            why.append("d: target period not stated")
        actual = _ACTUAL.search(text[max(0, pos - 50):pos])
        if actual:
            why.append(f"e: reported actual '{actual.group(0)}'")
        if why:
            v.fail("not_pinned", "; ".join(why))

    def check_entity(self, v: Verdict, row: sqlite3.Row) -> None:
        """Dimension and entity name two different subsidiaries (neither is the listed company)."""
        dim = (row["dimension"] or "").strip()
        ent = (row["entity"] or "").strip()
        sym = (row["symbol"] or "").strip()
        if not dim or not ent or dim.lower() == "total" or ent.lower() == sym.lower():
            return
        if dim.lower() == ent.lower():
            return
        v.fail("entity_mismatch", f"dimension '{dim}' and entity '{ent}' name different subsidiaries")

    def unit_value_count(self, text: str, unit: str, label_end: int) -> int:
        """How many values of the row's unit the quote prints after ``label_end`` ("10.3% 10.2% ..." is 3+)."""
        u = (unit or "").lower()
        family = "pct" if u in ("pct", "bps") else "days" if u == "days" else \
            "usd" if u.startswith("usd") else "inr" if u.startswith("inr") else "count"
        marker = re.compile(_UNIT_WORD[family], re.I)
        header = text[max(0, label_end - 40):min(len(text), label_end + 15)]
        count = 0
        for n, start, end in numbers_in(text):
            if start < label_end or _is_year(n) or _MONTH.match(text, end):
                continue
            if start > 0 and text[start - 1].isalpha():
                continue
            window = text[end:end + 12]
            if family in ("pct", "days"):
                hit = marker.search(window)          # a percent/day sign belongs after its number
            else:
                hit = marker.search(window + " " + text[max(0, start - 12):start])
            if hit:
                count += 1
            elif marker.search(header) and not (end < len(text) and text[end].isalpha()):
                count += 1      # a bare table cell, but not a period label ("9M", "Q2")
        return count

    def quote_value_count(self, m: Metric | None, text: str, value: float | None,
                          unit: str) -> tuple[int | None, int]:
        """(position of the row's number, how many values of its unit follow the label)."""
        nums = numbers_in(text)
        pos = None
        if value is not None:
            _, pos = find_value(value, nums)
            if (unit or "") == "bps":
                how2, pos2 = find_value(value / 100, nums)
                if how2 == "exact":
                    pos = pos2
        label = nearest_strong_label(m, text, pos) if m is not None and pos is not None else None
        label_end = pos or 0
        if label is not None and pos is not None and label[2] <= pos:
            label_end = label[2]
        return pos, self.unit_value_count(text, unit, label_end)

    def check_multi_number(self, v: Verdict, m: Metric | None, text: str, pos: int | None, unit: str,
                           rule: str) -> None:
        """A label followed by more than two values of the row's unit (a table header row) does not pin a column;
        any rule, and the row is verified only when another source agrees."""
        if pos is None:
            return
        label_end = pos
        if m is not None:
            label = nearest_strong_label(m, text, pos)
            if label is not None and label[2] <= pos:
                label_end = label[2]
        count = self.unit_value_count(text, unit, label_end)
        if count > 2:
            v.fail("multi_number", f"{count} {unit or 'unit'} values after the label: column not pinned")
        if count > 5:
            v.fail("history_row", f"{count} values after the label: a history row, only a filed figure pins it")
            v.filed_only = True
        if rule in ("table_v1", "chart_v1") and len({round(n, 4) for n, _, _ in numbers_in(text)}) > 2:
            v.fail("multi_number", f"{len(numbers_in(text))} numbers in the quote: column not pinned")

    def check_scale_doubt(self, v: Verdict, canon: str, value: float | None, unit: str, dimension: str,
                          entity: str, symbol: str) -> None:
        """An amount below 10 in inr_mn / inr_cr on a total line is usually a unit-scale slip (2.2 for 2,200):
        only a filed figure pins it."""
        u = (unit or "").lower()
        if canon not in _SCALE_FAMILIES or dimension != "total" or (entity or symbol) != symbol:
            return
        if u not in ("inr_mn", "inr_cr") or value is None or abs(value) >= 10:
            return
        v.fail("scale_doubt", f"{value} {unit} is below 10 for {canon}: unit scale not pinned")
        v.filed_only = True

    def witness_ok(self, r: sqlite3.Row, fin: dict, usd_rev: dict, dim_words: dict) -> bool:
        """A witness counts only when its own row passes every hard check and is not multi_number."""
        rid = r["id"]
        if rid in self._witness_cache:
            return self._witness_cache[rid]
        m = self.vocab.canon(r["metric"])
        canon = m.name if m else ""
        if r["extractor_rule"] == "xbrl_segment":
            self._witness_cache[rid] = True
            return True
        v = Verdict("kpi_series", rid, r["symbol"], r["metric"], canon, self.sectors.get(r["symbol"], ""),
                    r["source_type"] or self.doc_type.get(r["doc_key"], ""), r["extractor_rule"] or "")
        value = r["value"]
        amount = (value or 0) * (r["scale"] or 1)
        if canon in ("revenue", "pat", "ebitda") and r["dimension"] == "total" \
                and (r["entity"] or r["symbol"]) == r["symbol"] and (r["unit"] or "").startswith("inr"):
            filed = fin.get((r["symbol"], r["fiscal_period"], canon))
            if filed and canon != "ebitda" and not any(close(f, amount, 0.01) for f in filed):
                self._witness_cache[rid] = False
                return False
        if canon and r["dimension"] == "total" and (r["entity"] or r["symbol"]) == r["symbol"]:
            self.check_part(v, canon, amount, r["unit"] or "", r["symbol"], r["fiscal_period"], rid, fin, usd_rev)
        quote = r["quote"] or ""
        text = fold(quote)
        self.check_quote(v, quote, r["doc_key"], r["page"])
        self.check_sector(v, m)
        self.check_entity(v, r)
        nums = numbers_in(text)
        how, pos = find_value(value, nums)
        if (r["unit"] or "") == "bps":
            how2, pos2 = find_value(value / 100, nums)
            if how2 == "exact":
                how, pos = how2, pos2
        if how == "absent":
            v.fail("value_present", f"{value} not in the quote")
        _, count = self.quote_value_count(m, text, value, r["unit"] or "")
        if count > 2:
            self._witness_cache[rid] = False
            return False
        self.check_multi_number(v, m, text, pos, r["unit"] or "", r["extractor_rule"] or "")
        ctx = self.context_before(r["doc_key"], r["page"], quote, 300)
        self.check_label(v, m, text, pos, ctx)
        self.check_nearer_label(v, m, text, pos, reach=10 ** 9, same_side=True, mask_denominators=True)
        self.check_footnote(v, m, text, pos)
        self.check_regulated_rate(v, m, text, pos, r["unit"] or "")
        self.check_currency(v, m, text, pos, r["unit"] or "")
        self.check_net_cash_sign(v, m, text, pos, value)
        self.check_page_unit(v, text, pos, r["doc_key"], r["page"], quote, r["unit"] or "")
        self.check_company_speaker(v, text, pos, r["doc_key"], r["page"], quote)
        self.check_speaker_turn(v, r["doc_key"], r["page"], quote, text, pos)
        self.check_range(v, text, pos)
        self.check_unit_kind(v, m, text, pos, r["unit"] or "")
        if r["dimension"] == "total":
            self.check_dimension_word(v, m, quote, value, r["symbol"], dim_words)
            self.check_scope_word(v, m, text, pos, r["metric"])
        if how == "exact":
            self.check_list(v, m, text, pos, ctx)
        self.check_period_word(v, text, pos, r["fiscal_period"], r["extractor_rule"] or "")
        if m is None or m.kind != "growth_pct":
            if delta_hit(text, value, nums):
                v.fail("delta_value", "a change, not the level")
        if not plausible(m.kind if m else "any", r["metric"], value, value, r["unit"]):
            v.fail("plausible", "outside bounds")
        self.check_variant(v, m, text, pos)
        end = period_end(r["fiscal_period"])
        known = (r["known_at"] or "")[:10]
        if end and known and end > known:
            v.fail("future_period", "period had not ended")
        ok = not (set(c for c, _ in v.fails) & HARD)
        self._witness_cache[rid] = ok
        return ok

    def check_company_speaker(self, v: Verdict, text: str, pos: int | None, doc_key: str, page: int,
                              quote: str) -> None:
        """An analyst's question or request is not the company's figure."""
        if pos is None:
            return
        lo, hi = sentence_bounds(text, pos)
        sent = text[lo:hi]
        if "?" in sent:
            v.fail("not_company_speaker", "the number sits in a question")
            return
        hit = _ANALYST_PHRASE.search(sent)
        if hit:
            v.fail("not_company_speaker", f"the number's sentence is analyst wording ('{hit.group(0)}')")
            return
        ctx = self.context_before(doc_key, page, quote, 300)
        labels = re.findall(r"(?:^|[\s.])([a-z][a-z .&'-]{0,30}):\s", ctx)
        if labels and ("analyst" in labels[-1] or "moderator" in labels[-1]):
            v.fail("not_company_speaker", f"the speaker just before the quote is '{labels[-1].strip()}'")

    def management_text(self, doc_key: str) -> str:
        """The document's participant pages: lines carrying a management role, and the headings' following lines."""
        if doc_key in self._mgmt:
            return self._mgmt[doc_key]
        collected: list[str] = []
        try:
            pages = self.con.execute("SELECT text FROM doc_page WHERE doc_key=? ORDER BY page LIMIT 4",
                                     (doc_key,)).fetchall()
        except sqlite3.OperationalError:
            pages = []
        for page in pages:
            lines = [line.strip() for line in (page["text"] or "").splitlines()]
            for i, line in enumerate(lines):
                if not line:
                    continue
                if _MGMT_ROLE.search(line):
                    if i and re.match(r"^(?:mr|mrs|ms|dr)\.?\s+[a-z]", lines[i - 1], re.I) and len(lines[i - 1]) < 80:
                        collected.append(lines[i - 1])
                    collected.append(line)
                if _MGMT_HEADING.search(line.lower()) and len(line) < 90:
                    collected.append(line)
                    collected.extend(nxt for nxt in lines[i + 1:i + 4] if nxt and len(nxt) < 80)
            if len(collected) >= 80:
                break
        self._mgmt[doc_key] = "\n".join(collected[:80]).lower()
        return self._mgmt[doc_key]

    def speaker_turn(self, doc_key: str, page: int, quote: str) -> tuple[str, str] | None:
        """(speaker name, text of the turn before it) for the speaker turn that contains the quote.  A turn that
        starts on the previous page is read from that page's tail (the Tejas analyst question of round 8)."""
        raw = self.page_text(doc_key, page) or ""
        words = quote.split()[:8]
        if not words:
            return None
        pre = (self.page_text(doc_key, page - 1) or "")[-2000:] if page > 1 else ""
        whole = pre + "\n" + raw if pre else raw
        found = re.search(r"\s+".join(map(re.escape, words)), whole)
        if found is None or found.start() < len(pre):
            return None
        last = None
        for mm in _SPEAKER_LINE.finditer(whole, 0, found.start()):
            if plausible_speaker(mm.group(1)):
                last = mm
        if last is None:
            return None
        prev = None
        for mm in _SPEAKER_LINE.finditer(whole, 0, last.start()):
            if plausible_speaker(mm.group(1)):
                prev = mm
        before = whole[prev.end():last.start()] if prev else whole[:last.start()]
        return last.group(1).strip(), before.rstrip()

    def check_speaker_turn(self, v: Verdict, doc_key: str, page: int, quote: str, text: str,
                           pos: int | None) -> None:
        """The quote's speaker turn is the company's only when the speaker is in the document's management list
        or answers the question just before; any other named turn is an analyst.  Transcripts only.  When the
        speaker cannot be found, a question right after the number is soft question_next."""
        if self.doc_type.get(doc_key) != "transcript":
            return
        turn = self.speaker_turn(doc_key, page, quote)
        if turn is None:
            self.check_question_next(v, text, pos)
            return
        mgmt = self.management_text(doc_key)
        if not mgmt:
            return
        name, before = turn
        low = name.lower()
        if "analyst" in low or "moderator" in low:
            v.fail("not_company_speaker", f"the quote is in the '{name}' turn")
            return
        tokens = [t for t in re.sub(r"[^a-z ]", " ", low).split() if t not in ("mr", "mrs", "ms", "dr", "and")]
        if tokens:
            if " ".join(tokens) in mgmt:
                return
            if len(tokens[0]) >= 4 and tokens[0] in mgmt:
                return
        if before.endswith("?"):
            return
        v.fail("not_company_speaker", f"speaker '{name}' is not in the document's management list")

    def check_range(self, v: Verdict, text: str, pos: int | None) -> None:
        """One end of a printed "5 to 6000" range is not a level."""
        if pos is None:
            return
        nums = numbers_in(text)
        idx = next((i for i, (_, start, _) in enumerate(nums) if start == pos), None)
        if idx is None:
            return

        def value_token(i: int) -> bool:
            n, start, end = nums[i]
            return not _is_year(n) and not (start > 0 and text[start - 1].isalpha()) \
                and not _MONTH.match(text, end)

        if idx > 0 and value_token(idx - 1) and re.fullmatch(r"\s*(?:to|[-–])\s*", text[nums[idx - 1][2]:pos]):
            v.fail("range_value", "the number is one end of a printed range")
        elif idx + 1 < len(nums) and value_token(idx + 1) and re.fullmatch(r"\s*(?:to|[-–])\s*", text[nums[idx][2]:nums[idx + 1][1]]):
            v.fail("range_value", "the number is one end of a printed range")

    def check_unit_kind(self, v: Verdict, m: Metric | None, text: str, pos: int | None, unit: str) -> None:
        """A days row needs a days word, a percent row a % / per cent / bps, next to the number."""
        if pos is None:
            return
        u = (unit or "").lower()
        kind = m.kind if m else ""
        if u == "days" or kind == "days":
            if not _DAYS_WORD.search(text[max(0, pos - 25):pos + 25]):
                v.fail("unit_kind", "days row without a days word at the number")
        if u in ("pct", "bps") or kind in ("level_pct", "bps_or_pct", "growth_pct"):
            if not _PCT_WORD.search(text[max(0, pos - 40):pos + 15]):
                label = nearest_strong_label(m, text, pos) if m is not None else None
                # a label naming the ratio ("EBITDA Margins 7.1") is the unit context, a bare table cell
                if label is None or abs(label[0]) > 45 or not re.search(
                        r"margin|ratio|yield|rate|share|growth|percent|pct|bps|return|roa|roe|roce|solvency|"
                        r"adequacy|penetration|utili[sz]ation", text[label[1]:label[2]].lower()):
                    v.fail("unit_kind", f"{u or kind} row without % / per cent / bps at the number")

    def check_nearer_label(self, v: Verdict, m: Metric | None, text: str, pos: int | None,
                           reach: int = 45, same_side: bool = False,
                           mask_denominators: bool = False) -> None:
        """Another metric's strong label nearer the number than the row's own label is the row's real metric
        ("50 crores of revenue ... 20% of EBITDA margins" stored as revenue growth; round 10 for kpi: "gross
        debt ... a cash of INR 3,165 crores" stored as gross debt).  ``same_side`` compares only labels on the
        row's own side of the number, so a metric named after it ("AUM ... 7,984 crore and PAT by 50%") is not
        taken as claiming the number; ``mask_denominators`` ignores the base phrase ("as a % of NOV")."""
        if m is None or pos is None:
            return
        own = nearest_strong_label(m, text, pos)
        if own is None or abs(own[0]) > reach or abs(own[0]) <= 15:
            # a label within 15 chars of the number already pins it; a nearer foreign label would lie between
            # the two and check_label has quarantined that (the scan below is the far-label case)
            return
        if own[2] <= pos and _VARIANT.search(text[own[2]:pos]):
            return      # a qualifier phrase ("EBITDA margin excluding other income") is the soft variant
        own_before = own[2] <= pos
        # a denominator ("as a % of NOV", "net NPAs to net advances") names the base, not the number's metric
        scanned = _DENOM.sub(lambda mm: " " * len(mm.group(0)), text) if mask_denominators else text
        own_spans = [(mm.start(), mm.end()) for p in (*m.labels, *m.weak) for mm in p.finditer(text)]
        best: tuple[int, str, str, int, int] | None = None
        for other in self.vocab.metrics.values():
            if other.name == m.name or other.name in m.related or m.name in other.related:
                continue
            for pattern in other.labels:
                for mm in pattern.finditer(scanned):
                    if same_side and (mm.end() <= pos) != own_before:
                        continue
                    if any(a - 2 <= mm.start() and mm.end() <= b + 2 for a, b in own_spans):
                        continue      # inside the row's own label ("net cash" holds "cash balance")
                    if mm.group(0)[0].isdigit() and mm.start() > 0 and scanned[mm.start() - 1] in "0123456789.,":
                        continue      # the "49 m" fragment of "13.49 million", not a persistency label
                    if any(w.search(mm.group(0)) for w in m.weak):
                        continue
                    if mm.group(0).lower().startswith(("revenue", "sale", "turnover")) and re.search(
                            r"\b(?:of|for)\s+(?:our|the|total|its)?\s*$", scanned[max(0, mm.start() - 14):mm.start()]):
                        continue      # "2.5% of our revenues": the base, not the row's metric
                    dist = pos - mm.end() if mm.end() <= pos else mm.start() - pos
                    if best is None or abs(dist) < abs(best[0]):
                        best = (dist, other.name, mm.group(0), mm.start(), mm.end())
        if best is None or abs(best[0]) >= abs(own[0]):
            return
        # a printed list ("Gross NPA and Net NPA stood at a% and b%") puts each label in front of its own value
        if self.list_place(m, scanned, pos) is True:
            return
        # the quote may cut the list after its first value ("Gross NPA and Net NPA ... stood at 1.24%"): the two
        # labels are joined as a list, so the first value can still be the first label's
        a, b = sorted(((own[1], own[2]), (best[3], best[4])))
        join = text[a[1]:b[0]]
        if len(join) <= 30 and re.search(r"(?:^|\s)(?:and|&)(?:\s|$)|,", join) and self.list_order_ok(m, scanned, pos):
            return
        v.fail("label_conflict", f"{best[1]} label '{best[2]}' is nearer the number than {m.name}")

    def check_currency(self, v: Verdict, m: Metric | None, text: str, pos: int | None, unit: str) -> None:
        """The label-to-number span prints a currency that is not the row's unit: the nearest currency marker
        before the number decides ("Adjusted Net Debt $ 6,724 $ 5,176" is a USD figure in an inr_cr row)."""
        u = (unit or "").lower()
        if pos is None or not (u.startswith("inr") or u.startswith("usd")):
            return
        lo = max(0, pos - 12)
        if m is not None:
            ends = [mm.end() for p in (*m.labels, *m.weak) for mm in p.finditer(text, 0, pos)]
            if ends:
                lo = max(max(ends), pos - 80)
        marks = list(_CURRENCY.finditer(text[lo:pos]))
        if not marks:
            return
        last = max(marks, key=lambda mm: mm.start())
        if u.startswith("inr") and last.group("usd"):
            v.fail("currency", f"unit {unit} but the number is printed in {last.group(0)!r}")
        elif u.startswith("usd") and last.group("inr"):
            v.fail("currency", f"unit {unit} but the number is printed in {last.group(0)!r}")

    def check_dimension_word(self, v: Verdict, m: Metric | None, quote: str, value: float | None,
                             symbol: str, dim_words: dict[str, set[str]]) -> None:
        """A total row whose quote names a segment just before its label ("Aluminium Upstream ... EBITDA per
        tonne", "Renewables ... Revenues of Rs 122 Cr"): the amount is probably that segment's, not the total."""
        if m is None or value is None or not quote:
            return
        _, rpos = find_value(value, numbers_in(quote))
        if rpos is None:
            return
        starts = [mm.start() for p in (*m.labels, *m.weak) for mm in p.finditer(quote) if mm.end() <= rpos]
        if not starts:
            return
        window = quote[max(0, max(starts) - 60): max(starts)]
        if any(p.search(_WS.sub(" ", window)) for p in m.labels):
            # the window holds the metric's own full name before its abbreviation ("Return on Average Assets
            # (RoA)", "Profit  After Tax (PAT)"): not a segment word
            return
        low = window.lower()
        for word in sorted(dim_words.get(symbol, ())):
            if re.search(rf"(?<![a-z]){re.escape(word)}(?![a-z])", low):
                v.fail("dimension_word", f"the {m.name} label follows segment word '{word}' but the row is total")
                return
        company = self.company_words.get((symbol or "").upper(), set())
        for mm in _CAP_PHRASE.finditer(window):
            words = [w.strip(".").lower() for w in mm.group(1).split()]
            if sum(1 for w in words if w not in _QUALIFIER) < 2:
                continue
            if company and all(w in company for w in words):
                continue
            v.fail("dimension_word", f"the {m.name} label follows '{mm.group(1).strip()}' but the row is total")
            return

    # -- round 10: six general wrong classes ------------------------------------------------
    def check_footnote(self, v: Verdict, m: Metric | None, text: str, pos: int | None) -> None:
        """A footnote marker between the metric's label and the number: the number belongs to the note
        ("Net Debt *Includes investments in liquid funds and FDs of INR 3,165 crores"), not to the label."""
        if m is None or pos is None:
            return
        label = nearest_strong_label(m, text, pos)
        if label is None or label[2] > pos:
            return
        span = text[label[2]:pos]
        mark = _FOOTNOTE_MARK.search(span)
        if not mark:
            return
        tail = span[mark.end():]
        if label_hits(m, tail) or not _NOTE_PHRASE.search(tail):
            return
        v.fail("footnote_note", f"the number follows a footnote note ('{tail.strip()[:60]}')")

    def check_projection(self, v: Verdict, m: Metric | None, text: str, pos: int | None, doc_key: str,
                         page: int, fiscal_period: str) -> None:
        """A projection is not the company's actual: the number's sentence on a rating rationale page is the
        agency's estimate ("is estimated at 1.1 times in fiscal 2026 and is expected to remain stable"), and a
        fiscal year later than the row's own, right after the number, names a future level."""
        if pos is None:
            return
        lo, hi = sentence_bounds(text, pos)
        if _PROJECTION.search(text[lo:hi]) and _RATING_PAGE.search(self.page_fold(doc_key, page)):
            v.fail("projection", "the number's sentence is a rating agency's projection")
            return
        year = period_fiscal_year(fiscal_period)
        if year is None:
            return
        later = {y for y in plain_fiscal_years(text[pos:pos + 45]) if y > year}
        if later:
            v.fail("projection", f"fiscal {min(later)} follows the number on a {fiscal_period} row")

    def check_regulated_rate(self, v: Verdict, m: Metric | None, text: str, pos: int | None, unit: str) -> None:
        """A regulated utility's allowed / normative return is the tariff's rate, not the company's earned ratio
        ("The tariff allows a return on equity of 15.5%")."""
        if pos is None:
            return
        kind = m.kind if m else ""
        if not ((unit or "").lower() in ("pct", "bps") or kind in ("level_pct", "bps_or_pct", "multiple")):
            return
        lo, hi = sentence_bounds(text, pos)
        sentence = text[lo:hi]
        if _ROE_PHRASE.search(sentence) and _REGULATOR.search(sentence):
            v.fail("regulated_rate", "the number sits in a regulator / tariff sentence about return on equity")

    def check_segment_scope(self, v: Verdict, m: Metric | None, text: str, pos: int | None, symbol: str,
                            dim_words: dict[str, set[str]]) -> None:
        """A total row whose number's own clause names a segment / vertical ("Revenue of our flagship hospital
        business stood at 500 crore"): the amount is probably that part's, not the total's.  The window is the
        label-to-number span and 40 characters after the number, so a segment list elsewhere in a deck quote
        does not count."""
        if pos is None:
            return
        label = nearest_strong_label(m, text, pos) if m is not None else None
        start = label[1] if label is not None and label[1] <= pos else max(0, pos - 80)
        window = text[max(0, start - 40):pos + 40]
        low = window.lower()
        name_words = set(re.split(r"[^a-z]+", m.name)) if m is not None else set()
        for word in sorted(dim_words.get(symbol, ())):
            if word in name_words:
                continue        # the company's own dimension word is part of this metric's name
            if re.search(rf"(?<![a-z]){re.escape(word)}(?![a-z])", low):
                v.fail("segment_scope", f"the number's clause names the company's own segment '{word}'")
                return
        for mm in _SEGMENT_NOUN.finditer(window):
            lead = re.sub(r"['’]s$", "", mm.group(1).lower())
            if lead not in _SEGMENT_STOP and lead not in name_words:
                v.fail("segment_scope", f"the number's clause names a segment ('{mm.group(0).strip()}')")
                return

    def check_past_level(self, v: Verdict, m: Metric | None, text: str, pos: int | None,
                         fiscal_period: str, rule: str = "") -> None:
        """A level said about an earlier time is not this period's level ("net debt had almost neared INR
        20,000 crores in FY23" stored for the call's quarter).  A table / chart quote's years are column
        headers, not the number's own time (period_word makes the same exception)."""
        if pos is None or rule in ("table_v1", "chart_v1"):
            return
        lo, hi = sentence_bounds(text, pos)
        sentence = text[lo:hi]
        year = period_fiscal_year(fiscal_period)
        earlier = {y for y in plain_fiscal_years(text[max(lo, pos - 120):min(hi, pos + 60)])
                   if year is not None and y < year}
        if earlier:
            v.fail("past_level", f"the number's sentence names fiscal {max(earlier)} on a {fiscal_period} row")
            return
        hit = _PAST_LEVEL.search(sentence)
        if hit:
            v.fail("past_level", f"the number's sentence frames a past level ('{hit.group(0).strip()}')")

    def finish(self, v: Verdict) -> Verdict:
        names = {c for c, _ in v.fails}
        if names & HARD:
            v.status = "quarantined"
        elif names:
            # corroboration proves the number is printed twice, not that a weak label names this metric or that
            # a variant is the plain line: label_weak / variant never verify (round 9)
            v.status = "verified" if v.corroborated and names <= {"multi_number", "value_scaled",
                                                                  "history_row", "scale_doubt"} else "unverified"
        elif v.table == "kpi_series" and not v.corroborated and v.rule != "xbrl_segment":
            # an uncorroborated kpi figure is right about half the time on companies nobody tuned on (hidden
            # read, 8 Nov): verified needs a second independent source; an xbrl_segment row IS the filing
            v.fail("single_source", "no independent second source for this figure")
            v.status = "unverified"
        else:
            v.status = "verified"
        return v

    # -- guidance --
    def check_guidance(self) -> list[Verdict]:
        out = []
        for r in self.con.execute("SELECT * FROM guidance"):
            m = self.vocab.canon(r["metric"])
            v = Verdict("guidance", r["id"], r["symbol"], r["metric"], m.name if m else "", self.sectors.get(r["symbol"], ""),
                        self.doc_type.get(r["doc_key"], ""), r["extractor_rule"] or "")
            quote = r["quote"] or ""
            text = fold(quote)
            self.check_quote(v, quote, r["doc_key"], r["page"])
            self.check_sector(v, m)
            lo, hi = r["low"], r["high"]
            if lo is None and hi is None:
                v.fail("null_value", "no number stored")
                pos = None
            else:
                nums = numbers_in(text)
                pos = None
                for val in {x for x in (lo, hi) if x is not None}:
                    how, p = find_value(val, nums)
                    if how == "absent":
                        v.fail("value_present", f"{val} not in the quote")
                    elif how == "scaled":
                        v.fail("value_scaled", f"{val} only after rescale")
                    if p is not None and pos is None:
                        pos = p
                if lo is not None and hi is not None:
                    if lo > hi:
                        v.fail("range_order", f"low {lo} > high {hi}")
                    elif lo > 0 and hi / lo > 3:
                        v.fail("range_spread", f"high/low {hi / lo:.1f}")
                kind = m.kind if m else "any"
                if not plausible(kind, r["metric"], lo, hi, r["unit"]):
                    v.fail("plausible", f"{lo}-{hi} {r['unit']} outside {kind} bounds")
            context = self.context_before(r["doc_key"], r["page"], quote, 3000)
            self.check_label(v, m, text, pos, context)
            self.check_nearer_label(v, m, text, pos)
            self.check_currency(v, m, text, pos, r["unit"] or "")
            self.check_net_cash_sign(v, m, text, pos, lo if lo is not None else hi)
            if pos is not None:
                window = text[max(0, pos - 90): pos + 60]
                hit = next((p.pattern for p in self.vocab.third_party if p.search(window)), None)
                if hit:
                    v.fail("third_party", f"third-party wording '{hit}' near the number")
                past = _PAST_VERB.search(text[max(0, pos - 60):pos])
                if past:
                    v.fail("past_figure", f"the number follows a realised-figure verb '{past.group(0).strip()}'")
                governed = _PAST_GOVERN.search(text[max(0, pos - 45):pos])
                if governed:
                    v.fail("past_figure", f"a past-tense verb '{governed.group(0)}' governs the number")
                if m is None or m.kind != "growth_pct":
                    # a growth target is worded "growth of 12%", so the delta test is for level/amount metrics
                    for val in (lo, hi):
                        delta = delta_hit(text, val, nums)
                        if delta:
                            v.fail("delta_value", f"the number is a change ('{delta}'), not the level")
                            break
            self.check_variant(v, m, text, pos)
            self.check_target_frame(v, text, pos, r["target_period"])
            self.check_target_year(v, text, pos, r["target_period"])
            self.check_pinned(v, m, text, pos, r["target_period"],
                              (r["said_on"] or r["known_at"] or "")[:10])
            if not any(p.search(text) for p in self.vocab.forward):
                if any(p.search(context[-250:]) for p in self.vocab.forward):
                    v.fail("forward_context", "forward word only just before the quote")
                else:
                    v.fail("forward_word", "no forward word in the quote or just before it")
            end = period_end(r["target_period"])
            said = (r["said_on"] or r["known_at"] or "")[:10]
            if end and said and end < said and (r["target_period"] or "").startswith(("Q", "H", "9M")):
                v.fail("past_target", f"target {r['target_period']} ended {end}, said {said}")
            out.append(self.finish(v))
        return out

    # -- kpi --
    def _fin_values(self) -> dict[tuple[str, str, str], list[float]]:
        """(symbol, fiscal_period) -> rupee values of the filed revenue / PAT / EBITDA-like lines, any basis.
        The printed unit decides the scale when it names one; a filed figure below Rs 1 crore never witnesses
        revenue / PAT for a company whose other filed revenue is above Rs 100 crore."""
        want = {"revenue": ("revenue_from_operations", "total_income"),
                "pat": ("pat", "pat_owners", "pat_continuing"),
                "ebitda": ("operating_profit",)}
        got: dict[tuple[str, str, str], list[float]] = defaultdict(list)
        for canon, lines in want.items():
            marks = ",".join("?" * len(lines))
            try:
                for r in self.con.execute(f"SELECT symbol, fiscal_period, value, unit, scale FROM fin_quarter_current WHERE line_item IN ({marks})", lines):
                    amount = filed_rupees(r["value"], r["unit"], r["scale"])
                    if amount is not None:
                        got[(r["symbol"], r["fiscal_period"], canon)].append(amount)
            except sqlite3.OperationalError:
                pass
            try:
                for r in self.con.execute(f"SELECT symbol, fiscal_year, value, unit, scale FROM fin_annual_line WHERE line_item IN ({marks})", lines):
                    amount = filed_rupees(r["value"], r["unit"], r["scale"])
                    if amount is not None:
                        got[(r["symbol"], r["fiscal_year"], canon)].append(amount)
            except sqlite3.OperationalError:
                pass
        revenue_max: dict[str, float] = {}
        for (symbol, _period, canon), values in got.items():
            if canon == "revenue" and values:
                revenue_max[symbol] = max(revenue_max.get(symbol, 0.0), max(values))
        for key in list(got):
            symbol, _period, canon = key
            if canon in ("revenue", "pat") and revenue_max.get(symbol, 0.0) > BIG_REVENUE:
                kept = [v for v in got[key] if v >= MICRO_FILED]
                if kept:
                    got[key] = kept
                else:
                    del got[key]
        return got

    def check_kpi(self) -> list[Verdict]:
        rows = self.con.execute("SELECT * FROM kpi_series").fetchall()
        fin = self._fin_values()
        # two rows for the same key from the SAME document must agree (a doc that prints one figure twice)
        same_doc: dict[tuple, list[int]] = defaultdict(list)
        for r in rows:
            same_doc[(r["symbol"], r["metric"], r["dimension"], r["fiscal_period"], r["basis"],
                      r["doc_key"])].append(r["id"])
        # USD revenue has no filed rupee line to compare with: the company's own revenue rows for the period are
        # the yardstick (a product line / subsidiary sits far below their median)
        usd_rev: dict[tuple[str, str], list[tuple[int, float]]] = defaultdict(list)
        for r in rows:
            c = self.vocab.canon(r["metric"])
            if c and c.name == "revenue" and (r["unit"] or "").lower().startswith("usd") \
                    and r["dimension"] == "total" and (r["entity"] or r["symbol"]) == r["symbol"] \
                    and r["value"] is not None and r["value"] > 0:
                usd_rev[(r["symbol"], r["fiscal_period"])].append((r["id"], r["value"] * (r["scale"] or 1)))
        # cross-document groups: same company, metric, scope and period, rupee-or-unit value; `single` says the
        # quote prints at most one value of the unit after the label (only such a quote can corroborate a column)
        groups: dict[tuple, list[tuple[int, str, float, str, bool]]] = defaultdict(list)
        for r in rows:
            m = self.vocab.canon(r["metric"])
            key = (r["symbol"], r["metric"], r["dimension"], r["fiscal_period"], r["entity"] or r["symbol"], r["basis"])
            text = fold(r["quote"] or "")
            _, count = self.quote_value_count(m, text, r["value"], r["unit"] or "")
            groups[key].append((r["id"], r["doc_key"], (r["value"] or 0) * (r["scale"] or 1),
                                squash(r["quote"] or "")[:80], count <= 1))
        # the company's own non-total dimension words: a total row whose quote names one is probably that part
        dim_words: dict[str, set[str]] = defaultdict(set)
        for r in rows:
            dim = (r["dimension"] or "").strip().lower()
            if dim and dim != "total":
                for w in re.split(r"[^a-z0-9]+", dim):
                    if len(w) >= 3 and w not in _DIM_STOP:
                        dim_words[r["symbol"]].add(w)
        by_id = {r["id"]: r for r in rows}
        out = []
        for r in rows:
            m = self.vocab.canon(r["metric"])
            v = Verdict("kpi_series", r["id"], r["symbol"], r["metric"], m.name if m else "", self.sectors.get(r["symbol"], ""),
                        r["source_type"] or self.doc_type.get(r["doc_key"], ""), r["extractor_rule"] or "")
            value = r["value"]
            amount = (value or 0) * (r["scale"] or 1)
            # corroboration first: another document with the same value, or the filed statements
            key = (r["symbol"], r["metric"], r["dimension"], r["fiscal_period"], r["entity"] or r["symbol"], r["basis"])
            # independent sources only: another document AND another wording (a deck table copied into the next
            # quarter's deck is the same source twice, not a second witness), and the witness itself must pass
            # every hard check and not be multi_number
            peers = groups[key]
            mine = squash(r["quote"] or "")[:80]
            valid = [(a, q, single) for i, d, a, q, single in peers
                     if d != r["doc_key"] and q != mine and self.witness_ok(by_id[i], fin, usd_rev, dim_words)]
            # two multi-column quotes agreeing do not corroborate each other: only a single-valued source does
            same = {q for a, q, single in valid if single and close(a, amount, 0.01)}
            diff = [a for a, _, _ in valid if not close(a, amount, 0.015)]
            if diff:
                v.fail("cross_doc", f"{len(diff)} independent source(s) disagree by more than 1.5%")
            canon = m.name if m else ""
            if canon in ("revenue", "pat", "ebitda") and r["dimension"] == "total" and (r["entity"] or r["symbol"]) == r["symbol"] \
                    and (r["unit"] or "").startswith("inr"):
                filed = fin.get((r["symbol"], r["fiscal_period"], canon))
                if filed:
                    if any(close(f, amount, 0.01) for f in filed):
                        v.corroborated = True
                    elif canon != "ebitda":
                        v.fail("fin_conflict", f"filed {canon} for {r['fiscal_period']}: {sorted(set(round(f / 1e7, 1) for f in filed))} cr, row {round(amount / 1e7, 1)} cr")
            if canon and r["dimension"] == "total" and (r["entity"] or r["symbol"]) == r["symbol"]:
                self.check_part(v, canon, amount, r["unit"] or "", r["symbol"], r["fiscal_period"], r["id"], fin, usd_rev)
                if r["extractor_rule"] != "xbrl_segment":
                    self.check_scale_doubt(v, canon, value, r["unit"] or "", r["dimension"],
                                           r["entity"] or "", r["symbol"])
                if r["extractor_rule"] != "xbrl_segment" and not v.corroborated:
                    # a total amount with nothing filed and no second source is served only as unverified
                    if canon in ("order_intake", "order_book"):
                        v.fail("uncorroborated", f"total {canon} with no filed statement and no second source")
                    elif canon in ("revenue", "pat", "ebitda") and not fin.get((r["symbol"], r["fiscal_period"], canon)):
                        v.fail("uncorroborated", f"total {canon} with no filed statement and no second source")
            if r["extractor_rule"] == "xbrl_segment":
                # a structured filing: no quote; the segment value is the tagged figure
                v.corroborated = True
                out.append(v)
                continue
            quote = r["quote"] or ""
            text = fold(quote)
            self.check_quote(v, quote, r["doc_key"], r["page"])
            self.check_sector(v, m)
            self.check_entity(v, r)
            nums = numbers_in(text)
            how, pos = find_value(value, nums)
            if (r["unit"] or "") == "bps" and value is not None:
                # a bps row is printed as a percentage ("credit cost of 0.18%"): the percent reading pins the
                # number; the plain reading can land on an unrelated 18 (a growth rate) later in the quote
                how2, pos2 = find_value(value / 100, nums)
                if how2 == "exact":
                    how, pos = how2, pos2
            if how == "absent":
                v.fail("value_present", f"{value} not in the quote")
            elif how == "scaled":
                v.fail("value_scaled", f"{value} only after rescale")
            self.check_multi_number(v, m, text, pos, r["unit"] or "", r["extractor_rule"] or "")
            ctx = self.context_before(r["doc_key"], r["page"], quote, 300)
            self.check_label(v, m, text, pos, ctx)
            self.check_nearer_label(v, m, text, pos, reach=10 ** 9, same_side=True, mask_denominators=True)
            self.check_footnote(v, m, text, pos)
            self.check_projection(v, m, text, pos, r["doc_key"], r["page"], r["fiscal_period"])
            self.check_regulated_rate(v, m, text, pos, r["unit"] or "")
            self.check_currency(v, m, text, pos, r["unit"] or "")
            self.check_net_cash_sign(v, m, text, pos, value)
            self.check_page_unit(v, text, pos, r["doc_key"], r["page"], quote, r["unit"] or "")
            self.check_company_speaker(v, text, pos, r["doc_key"], r["page"], quote)
            self.check_speaker_turn(v, r["doc_key"], r["page"], quote, text, pos)
            self.check_range(v, text, pos)
            self.check_unit_kind(v, m, text, pos, r["unit"] or "")
            if r["dimension"] == "total":
                self.check_dimension_word(v, m, quote, value, r["symbol"], dim_words)
                self.check_scope_word(v, m, text, pos, r["metric"])
                self.check_segment_scope(v, m, text, pos, r["symbol"], dim_words)
            if how == "exact":
                # the list-order test needs the number the row actually took: a rescaled match (an OCR
                # "0. 77%") is a soft value_scaled, not evidence about the list
                self.check_list(v, m, text, pos, ctx)
            self.check_period_word(v, text, pos, r["fiscal_period"], r["extractor_rule"] or "")
            self.check_past_level(v, m, text, pos, r["fiscal_period"], r["extractor_rule"] or "")
            if m is None or m.kind != "growth_pct":
                delta = delta_hit(text, value, nums)
                if delta:
                    v.fail("delta_value", f"the number is a change ('{delta}'), not the level")
            if not plausible(m.kind if m else "any", r["metric"], value, value, r["unit"]):
                v.fail("plausible", f"{value} {r['unit']} outside bounds")
            self.check_variant(v, m, text, pos)
            end = period_end(r["fiscal_period"])
            known = (r["known_at"] or "")[:10]
            if end and known and end > known:
                v.fail("future_period", f"{r['fiscal_period']} ends {end}, row known {known}")
            # decided last: a history / scale-doubt row is only pinnable by a filed figure
            if same and not v.filed_only:
                v.corroborated = True
            out.append(v)
        self.mark_same_doc_conflicts(out, by_id, same_doc, fin)
        return [self.finish(v) for v in out]

    def mark_same_doc_conflicts(self, out: list[Verdict], by_id: dict[int, sqlite3.Row],
                                groups: dict[tuple, list[int]], fin: dict) -> None:
        """Two rows of the same company / metric / scope / period from the SAME document that disagree by more
        than 1.5% after scale are both soft same_doc_conflict, unless one is a variant of the line or the filed
        statement pins one of the two figures (the filed statement arbitrates the document's own disagreement)."""
        got = {v.row_id: v for v in out}
        for ids in groups.values():
            ids = [i for i in ids if i in got]
            for a in range(len(ids)):
                for b in range(a + 1, len(ids)):
                    ra, rb = by_id.get(ids[a]), by_id.get(ids[b])
                    if ra is None or rb is None:
                        continue
                    amount_a = (ra["value"] or 0) * (ra["scale"] or 1)
                    amount_b = (rb["value"] or 0) * (rb["scale"] or 1)
                    if close(amount_a, amount_b, 0.015):
                        continue
                    va, vb = got[ids[a]], got[ids[b]]
                    if any(c == "variant" for c, _ in (*va.fails, *vb.fails)):
                        continue
                    canon = self.vocab.canon(ra["metric"])
                    filed = fin.get((ra["symbol"], ra["fiscal_period"], canon.name if canon else ""), ())
                    if any(close(amount_a, f, 0.01) or close(amount_b, f, 0.01) for f in filed):
                        continue
                    why = f"one document prints {amount_a:.6g} and {amount_b:.6g} for the same key"
                    for v in (va, vb):
                        if not any(c == "same_doc_conflict" for c, _ in v.fails):
                            v.fail("same_doc_conflict", why)


# ------------------------------------------------------------------------------------------------ output

def sectors_from(profile: str | None, con: sqlite3.Connection) -> dict[str, str]:
    """Company -> sector family: the profile's (generated by make_profile from the exchange taxonomy), else the
    exchange taxonomy in the main store, else 'unknown'."""
    out: dict[str, str] = {}
    if profile:
        p = json.loads(Path(profile).read_text(encoding="utf-8"))
        for c in p.get("companies", []):
            out[c["symbol"]] = c.get("sector") or "unknown"
    syms = [r[0] for r in con.execute("SELECT DISTINCT symbol FROM company")]
    missing = [s for s in syms if s not in out]
    if missing:
        try:
            from reality_engine.pilot3 import make_profile as mp
            store = sqlite3.connect(f"file:{mp.main_store()}?mode=ro", uri=True)
            store.row_factory = sqlite3.Row
            table = mp.sector_map()
            for s in missing:
                try:
                    out[s] = mp.company_row(store, s, table)["sector"]
                except Exception:
                    out[s] = "unknown"
        except Exception:
            for s in missing:
                out.setdefault(s, "unknown")
    return out


def write(out_db: str, verdicts: list[Verdict]) -> None:
    con = sqlite3.connect(out_db)
    con.executescript("""
        DROP TABLE IF EXISTS row_check; DROP TABLE IF EXISTS row_check_fail;
        CREATE TABLE row_check (tbl TEXT, row_id INTEGER, symbol TEXT, metric TEXT, canon TEXT, sector TEXT,
            doc_type TEXT, rule TEXT, status TEXT, corroborated INTEGER, checker TEXT, PRIMARY KEY (tbl, row_id));
        CREATE TABLE row_check_fail (tbl TEXT, row_id INTEGER, check_name TEXT, hard INTEGER, why TEXT);
    """)
    con.executemany("INSERT INTO row_check VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    [(v.table, v.row_id, v.symbol, v.metric, v.canon, v.sector, v.doc_type, v.rule, v.status,
                      int(v.corroborated), VERSION) for v in verdicts])
    con.executemany("INSERT INTO row_check_fail VALUES (?,?,?,?,?)",
                    [(v.table, v.row_id, c, int(c in HARD), w) for v in verdicts for c, w in v.fails])
    con.commit()
    con.close()


def summary(verdicts: list[Verdict]) -> dict:
    s: dict = {"rows": len(verdicts), "status": defaultdict(int), "by_table": defaultdict(lambda: defaultdict(int)),
               "fails": defaultdict(int)}
    for v in verdicts:
        s["status"][v.status] += 1
        s["by_table"][v.table][v.status] += 1
        for c, _ in v.fails:
            s["fails"][f"{v.table}:{c}"] += 1
    return json.loads(json.dumps(s))


def write_summary(path: Path, verdicts: list[Verdict]) -> None:
    """status counts by metric x sector x document type x extractor rule (one row per cell)."""
    cells: dict[tuple, int] = defaultdict(int)
    for v in verdicts:
        cells[(v.table, v.metric, v.sector, v.doc_type, v.rule, v.status)] += 1
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["table", "metric", "sector", "doc_type", "rule", "status", "count"])
        for key in sorted(cells):
            w.writerow([*key, cells[key]])


def write_sample(path: Path, db: str, verdicts: list[Verdict], n: int, seed: int, status: str) -> None:
    """N random rows of one status, with the stored row and its failed checks, for a human read."""
    pool = [v for v in verdicts if v.status == status]
    random.Random(seed).shuffle(pool)
    chosen = pool[:n]
    con = connect_readonly(db)
    con.row_factory = sqlite3.Row
    rows: dict[tuple, sqlite3.Row] = {}
    for table in sorted({v.table for v in chosen}):
        ids = [v.row_id for v in chosen if v.table == table]
        marks = ",".join("?" * len(ids))
        for r in con.execute(f"SELECT * FROM {table} WHERE id IN ({marks})", ids):
            rows[(table, r["id"])] = r
    con.close()
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, delimiter="\t", lineterminator="\n")
        w.writerow(["id", "table", "symbol", "metric", "dimension", "period", "value", "unit", "quote", "fails"])
        for v in chosen:
            r = rows.get((v.table, v.row_id))
            if r is None:
                continue
            if v.table == "guidance":
                dim, period = "", r["target_period"]
                value = f"{r['low']}-{r['high']}" if r["high"] is not None else str(r["low"])
            else:
                dim, period, value = r["dimension"], r["fiscal_period"], r["value"]
            quote = (r["quote"] or "").replace("\n", " ").replace("\t", " ")
            w.writerow([v.row_id, v.table, v.symbol, v.metric, dim, period, value, r["unit"], quote,
                        ";".join(c for c, _ in v.fails)])


def run(db: str, out: str, profile: str | None = None, tables: tuple[str, ...] = ("guidance", "kpi_series"),
        report: str | None = None, sample: int = 0, seed: int = 0, status: str = "verified") -> dict:
    con = connect_readonly(db)
    sectors = sectors_from(profile, con)
    con.close()
    ch = Checker(db, sectors)
    verdicts: list[Verdict] = []
    if "guidance" in tables:
        verdicts += ch.check_guidance()
    if "kpi_series" in tables:
        verdicts += ch.check_kpi()
    ch.con.close()          # no read handle left on the build (Windows keeps the file open otherwise)
    write(out, verdicts)
    if report:
        report_dir = Path(report)
        report_dir.mkdir(parents=True, exist_ok=True)
        write_summary(report_dir / "row_checks_summary.csv", verdicts)
        if sample:
            write_sample(report_dir / "row_checks_sample.tsv", db, verdicts, sample, seed, status)
    return summary(verdicts)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=(__doc__ or "Independent row checks").splitlines()[0])
    ap.add_argument("--db", required=True, help="built database, opened read-only")
    ap.add_argument("--out", required=True, help="verdict database (row_check, row_check_fail)")
    ap.add_argument("--profile", default=None)
    ap.add_argument("--tables", default="guidance,kpi_series")
    ap.add_argument("--report", default=None, help="directory for row_checks_summary.csv and the sample TSV")
    ap.add_argument("--sample", type=int, default=0, help="N random rows for the human read (needs --report)")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--status", default="verified", choices=["verified", "unverified", "quarantined"])
    a = ap.parse_args(argv)
    if a.sample and not a.report:
        ap.error("--sample needs --report DIR")
    print(json.dumps(run(a.db, a.out, a.profile, tuple(a.tables.split(",")), a.report, a.sample, a.seed, a.status), indent=1))


if __name__ == "__main__":
    main()
