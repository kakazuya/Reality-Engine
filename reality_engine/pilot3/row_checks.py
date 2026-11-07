"""Independent row check layer for extracted rows (T-113; standing rule, Shivam 8 Nov).

The worker that wrote an extractor never checks it.  This module reads a built pilot3-style database READ-ONLY,
checks every ``guidance`` and ``kpi_series`` row with scripts that share nothing with the extractors (own number
parser, own label vocabulary ``row_checks_vocab.yaml``, own period arithmetic), and writes one verdict per row to a
separate output database:

    verified     every check that applies passed and the figure is pinned (a single reading, or corroborated
                 by another document or by the filed financial statements)
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
    multi_number      (kpi) the quote holds several numbers, so which column was taken is not pinned -> unverified
    cross_doc         (kpi) another document gives a different value for the same metric, period and scope
    fin_conflict      (kpi) the filed statements give a different figure for the same line and period
    variant           (kpi/guidance) pat/ebitda/revenue whose label says adjusted / before exceptional /
                      excluding / per ... -> unverified
    entity_mismatch   (kpi) the dimension and the entity name two different non-symbol subsidiaries -> unverified

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
        "fin_conflict", "part_not_total", "period_word"}
SOFT = {"value_scaled", "range_spread", "multi_number", "cross_doc", "no_vocab", "no_page_text",
        "unknown_sector", "label_weak", "label_context", "forward_context", "variant", "entity_mismatch"}

# Revenue / PAT / EBITDA / order rows must be a plausible share of the company's filed figure: a subsidiary or
# segment amount stored with dimension "total" is the classic "part stored as the total" mistake.
_FAMILY_FILED = {"revenue": "revenue", "pat": "pat", "ebitda": "ebitda",
                 "order_intake": "revenue", "order_book": "revenue"}
PART_SHARE = 0.15


def connect_readonly(db: str) -> sqlite3.Connection:
    """Read-only connection.  A WAL database in a directory the caller cannot write to needs its -shm; the
    fallback opens the checkpointed file immutable (refused when a -wal with uncommitted pages is present)."""
    try:
        return sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    except sqlite3.OperationalError:
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


_DELTA = re.compile(r"(?:reduction|decrease|increase|decline|rise|improvement|growth|drop)\s+(?:of|by)\s+(?:approximately|about|around|nearly|over|~)?\s*\W{0,3}$|(?:grew|rose|fell|declined|increased|decreased|improved|reduced|up|down|higher|lower)\s+by\s+(?:approximately|about|around|nearly|over|~)?\s*\W{0,3}$")
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


_DENOM = re.compile(r"(?<=%|t)\s+of\s+(?:our|the|total|average|its)?\s*[a-z]+(?:\s+[a-z]+)?|(?:per ?cent|bps|basis points)\s+of\s+(?:our|the|total|average|its)?\s*[a-z]+(?:\s+[a-z]+)?|\bto\s+(?:net|gross|total|average)\s+[a-z]+")


def nearest(hits: list[int], pos: int) -> int | None:
    return min((abs(h - pos) for h in hits), default=None)


# Sentences, periods and the wording that changes what a figure means.  These are the checker's own patterns:
# nothing here is imported from an extractor or from lexicon/.
_SENT_BREAK = re.compile(r"[.!?](?:\s+|$)|[►•|]")
_PERIOD_TOKEN = re.compile(
    r"(?:\b(?P<q>q[1-4])\b|\b(?P<h>h[12])\b|\b(?P<nine>9m|nine\s+months?)\b|"
    r"\b(?P<half>half[- ]?year)\b|\b(?P<ytd>ytd|year[- ]to[- ]date)\b)"
    r"(?:\s*(?:fy\s*)?['’]?(?P<yy>\d{2}))?", re.I)
_PAST_VERB = re.compile(
    r"\b(?:grew|grow|grown|delivered|achieved|reported|posted|stood|came\s+in|declined|rose|fell|"
    r"reduced|improved)\s+(?:at|of|to)?\s*$")
_VARIANT = re.compile(r"before (?:exceptional|one[- ]off|one[- ]time)|adjusted|excluding|\bper\s+(?!cent\b)")
# wording between a period token and the number that makes the token a comparative, not the number's own period
_COMPARATIVE = re.compile(r"\b(?:over|against|versus|vs|from|than|compared|ahead\s+of|prior|last|previous|"
                          r"higher|lower|up|down)\b", re.I)
PERIOD_REACH = 60   # a token further from the number than this names another figure in the same sentence


def sentence_bounds(text: str, pos: int) -> tuple[int, int]:
    """The sentence around ``pos`` in folded text: split on . ! ? and on bullets / bars."""
    left = 0
    for m in _SENT_BREAK.finditer(text, 0, pos):
        left = m.end()
    m = _SENT_BREAK.search(text, pos)
    return left, (m.start() if m else len(text))


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
        yy = m.group("yy")
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

    def fail(self, check: str, why: str) -> None:
        self.fails.append((check, why))


class Checker:
    def __init__(self, db: str, sectors: dict[str, str], vocab: Vocab | None = None):
        self.con = connect_readonly(db)
        self.con.row_factory = sqlite3.Row
        self.vocab = vocab or load_vocab()
        self.sectors = sectors
        self._page: dict[tuple[str, int], str | None] = {}
        self.doc_type = {r["doc_key"]: (r["doc_type"] or "") for r in self.con.execute("SELECT doc_key, doc_type FROM doc")}

    # -- shared --
    def page_text(self, doc_key: str, page: int) -> str | None:
        key = (doc_key, page)
        if key not in self._page:
            r = self.con.execute("SELECT text FROM doc_page WHERE doc_key=? AND page=?", key).fetchone()
            self._page[key] = r[0] if r and r[0] else None
        return self._page[key]

    def context_before(self, doc_key: str, page: int, quote: str, n: int = 500) -> str:
        """Folded page text just before the quote (the question asked, the previous sentence), '' if not found."""
        text = fold(self.page_text(doc_key, page) or "")
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
        q, t = squash(quote), squash(text)
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
        own = label_hits(m, text)
        if not own and pos is not None:
            # the clause around the number names ANOTHER metric and never this one: the number is that metric's
            # ("Return on assets is estimated at 4.4%-4.6%" stored as credit cost).  A word that is also one of
            # this metric's weak labels is not foreign: "Domestic sales were at 538,994" is a volume, though
            # "sales" is a strong revenue label too.
            lo_w, hi_w = max(0, pos - 160), pos + 60
            masked_w = _DENOM.sub(lambda mm: " " * len(mm.group(0)), text)
            for other in self.vocab.metrics.values():
                if other.name == m.name or other.name in m.related or m.name in other.related:
                    continue
                hit = next((mm for p in other.labels for mm in p.finditer(masked_w)
                            if lo_w <= mm.start() < hi_w and not any(w.search(mm.group(0)) for w in m.weak)), None)
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
        first_num = next((n[1] for n in numbers_in(text) if not _is_year(n[0]) and not _MONTH.match(text, n[2])), pos)
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

    def list_order_ok(self, m: Metric, text: str, pos: int) -> bool:
        """'Gross NPA and Net NPA stood at 1.33% and 0.53% respectively, as against 1.59% and 0.77%': labels listed
        first, numbers after in the same order (repeated for comparatives).  True when the row's number holds the
        row's label's place in that order."""
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
        after = [n for n in numbers_in(text) if n[1] >= last_end and not _is_year(n[0]) and not _MONTH.match(text, n[2])]
        if len(after) < 2:
            # fewer values than names printed: the labels are not a list of parallel values ("revenue and order
            # intake ... 1,550 crore and 540 crore respectively" quoted only up to its first value), so the
            # order test does not apply rather than failing the row
            return True
        idx = next((i for i, n in enumerate(after) if n[1] == pos), None)
        return idx is not None and idx % len(names) == names.index(m.name)

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

    def check_variant(self, v: Verdict, m: Metric | None, text: str, pos: int | None) -> None:
        """A pat / ebitda / revenue figure labelled adjusted, before exceptional / one-time, excluding, or per
        (share / tonne / franchise) is not the plain line unless the metric itself says so."""
        if m is None or pos is None or m.name not in ("revenue", "pat", "ebitda"):
            return
        if re.search(r"adjusted|_per_", (v.metric or "").lower()):
            return
        hit = _VARIANT.search(text[max(0, pos - 90):pos + 30])
        if hit:
            v.fail("variant", f"the label says '{hit.group(0)}', not the plain {m.name}")

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

    def finish(self, v: Verdict) -> Verdict:
        names = {c for c, _ in v.fails}
        if names & HARD:
            v.status = "quarantined"
        elif names:
            v.status = "verified" if v.corroborated and names <= {"multi_number", "value_scaled", "label_weak"} else "unverified"
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
            if pos is not None:
                window = text[max(0, pos - 90): pos + 60]
                hit = next((p.pattern for p in self.vocab.third_party if p.search(window)), None)
                if hit:
                    v.fail("third_party", f"third-party wording '{hit}' near the number")
                past = _PAST_VERB.search(text[max(0, pos - 60):pos])
                if past:
                    v.fail("past_figure", f"the number follows a realised-figure verb '{past.group(0).strip()}'")
            self.check_variant(v, m, text, pos)
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
        """(symbol, fiscal_period) -> rupee values of the filed revenue / PAT / EBITDA-like lines, any basis."""
        want = {"revenue": ("revenue_from_operations", "total_income"),
                "pat": ("pat", "pat_owners", "pat_continuing"),
                "ebitda": ("operating_profit",)}
        got: dict[tuple[str, str, str], list[float]] = defaultdict(list)
        for canon, lines in want.items():
            marks = ",".join("?" * len(lines))
            try:
                for r in self.con.execute(f"SELECT symbol, fiscal_period, value, scale FROM fin_quarter_current WHERE line_item IN ({marks})", lines):
                    if r["value"] is not None:
                        got[(r["symbol"], r["fiscal_period"], canon)].append(r["value"] * (r["scale"] or 1))
            except sqlite3.OperationalError:
                pass
            try:
                for r in self.con.execute(f"SELECT symbol, fiscal_year, value, scale FROM fin_annual_line WHERE line_item IN ({marks})", lines):
                    if r["value"] is not None:
                        got[(r["symbol"], r["fiscal_year"], canon)].append(r["value"] * (r["scale"] or 1))
            except sqlite3.OperationalError:
                pass
        return got

    def check_kpi(self) -> list[Verdict]:
        rows = self.con.execute("SELECT * FROM kpi_series").fetchall()
        fin = self._fin_values()
        # USD revenue has no filed rupee line to compare with: the company's own revenue rows for the period are
        # the yardstick (a product line / subsidiary sits far below their median)
        usd_rev: dict[tuple[str, str], list[tuple[int, float]]] = defaultdict(list)
        for r in rows:
            c = self.vocab.canon(r["metric"])
            if c and c.name == "revenue" and (r["unit"] or "").lower().startswith("usd") \
                    and r["dimension"] == "total" and (r["entity"] or r["symbol"]) == r["symbol"] \
                    and r["value"] is not None:
                usd_rev[(r["symbol"], r["fiscal_period"])].append((r["id"], r["value"] * (r["scale"] or 1)))
        # cross-document groups: same company, metric, scope and period, rupee-or-unit value
        groups: dict[tuple, list[tuple[int, str, float, str]]] = defaultdict(list)
        for r in rows:
            m = self.vocab.canon(r["metric"])
            key = (r["symbol"], r["metric"], r["dimension"], r["fiscal_period"], r["entity"] or r["symbol"], r["basis"])
            groups[key].append((r["id"], r["doc_key"], (r["value"] or 0) * (r["scale"] or 1), squash(r["quote"] or "")[:80]))
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
            # quarter's deck is the same source twice, not a second witness)
            peers = groups[key]
            mine = squash(r["quote"] or "")[:80]
            same = {q for i, d, a, q in peers if close(a, amount, 0.01) and d != r["doc_key"] and q != mine}
            diff = {q for i, d, a, q in peers if not close(a, amount, 0.01) and d != r["doc_key"] and q != mine}
            if same and len(same) > len(diff):
                v.corroborated = True
            if diff and len(diff) >= len(same):
                v.fail("cross_doc", f"{len(diff)} other source(s) give a different value, {len(same)} the same")
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
            if r["extractor_rule"] == "xbrl_segment":
                # a structured filing: no quote; the segment value is the tagged figure
                v.corroborated = True
                out.append(self.finish(v))
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
            if len({round(n, 4) for n, _, _ in nums}) > 2 and r["extractor_rule"] in ("table_v1", "chart_v1"):
                v.fail("multi_number", f"{len(nums)} numbers in the quote: column not pinned")
            ctx = self.context_before(r["doc_key"], r["page"], quote, 300)
            self.check_label(v, m, text, pos, ctx)
            if how == "exact":
                # the list-order test needs the number the row actually took: a rescaled match (an OCR
                # "0. 77%") is a soft value_scaled, not evidence about the list
                self.check_list(v, m, text, pos, ctx)
            self.check_period_word(v, text, pos, r["fiscal_period"], r["extractor_rule"] or "")
            if pos is not None and (m is None or m.kind != "growth_pct") and _DELTA.search(text[max(0, pos - 40):pos]):
                v.fail("delta_value", "the number is a change (reduction of / grew by), not the level")
            if not plausible(m.kind if m else "any", r["metric"], value, value, r["unit"]):
                v.fail("plausible", f"{value} {r['unit']} outside bounds")
            self.check_variant(v, m, text, pos)
            end = period_end(r["fiscal_period"])
            known = (r["known_at"] or "")[:10]
            if end and known and end > known:
                v.fail("future_period", f"{r['fiscal_period']} ends {end}, row known {known}")
            out.append(self.finish(v))
        return out


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
