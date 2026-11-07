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
    sector_fit        the metric belongs to the company's sector family
    third_party       (guidance) the number sits near system / industry / GDP / regulator wording
    forward_word      (guidance) the quote carries no forward word (expect, guide, target, ...)
    null_value        (guidance) no number stored
    range_order       low > high
    range_spread      (guidance) high / low > 3 (two figures merged into one range) -> unverified
    plausible         value outside the metric kind's bounds
    future_period     (kpi) a reported figure for a period that had not ended when it was known
    past_target       (guidance) a target for a period that had ended before it was said
    multi_number      (kpi) the quote holds several numbers, so which column was taken is not pinned -> unverified
    cross_doc         (kpi) another document gives a different value for the same metric, period and scope
    fin_conflict      (kpi) the filed statements give a different figure for the same line and period

Run:  python -m reality_engine.pilot3.row_checks --db D:/RealityEngine/pilot10/pilot10.db --out OUT.db
      [--profile tasks/night_loop/pilot10_profile.json] [--tables guidance,kpi_series] [--report]
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sqlite3
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import yaml

VERSION = "row_checks_v1"
VOCAB_PATH = Path(__file__).with_name("row_checks_vocab.yaml")

HARD = {"list_order", "delta_value", "quote_on_page", "value_present", "label_present", "label_conflict", "label_foreign", "sector_fit", "third_party",
        "forward_word", "null_value", "range_order", "plausible", "future_period", "past_target",
        "fin_conflict"}
SOFT = {"value_scaled", "range_spread", "multi_number", "cross_doc", "no_vocab", "no_page_text",
        "unknown_sector", "label_weak", "label_context", "forward_context"}

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
_NUM = re.compile(r"(?<![\d,])(?<!\d\.)(?:\d{1,3}(?:,\d{2,3})+|\d+)(?:\.\d+)?|(?<![\d.])\.\d+")


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


# ----------------------------------------------------------------------------------------------- bounds

def plausible(kind: str, metric: str, lo: float, hi: float, unit: str) -> bool:
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
        self.con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
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
            # ("Return on assets is estimated at 4.4%-4.6%" stored as credit cost)
            lo_w, hi_w = max(0, pos - 70), pos + 40
            masked_w = _DENOM.sub(lambda mm: " " * len(mm.group(0)), text)
            for other in self.vocab.metrics.values():
                if other.name == m.name or other.name in m.related or m.name in other.related:
                    continue
                hit = next((mm for p in other.labels for mm in p.finditer(masked_w) if lo_w <= mm.start() < hi_w), None)
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
        idx = next((i for i, n in enumerate(after) if n[1] == pos), None)
        return idx is not None and idx % len(names) == names.index(m.name)

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
    def _fin_values(self) -> dict[tuple[str, str], list[float]]:
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
        # cross-document groups: same company, metric, scope and period, rupee-or-unit value
        groups: dict[tuple, list[tuple[int, str, float]]] = defaultdict(list)
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
            if r["extractor_rule"] == "xbrl_segment":
                # a structured filing: no quote; the segment value is the tagged figure
                v.corroborated = True
                out.append(self.finish(v))
                continue
            quote = r["quote"] or ""
            text = fold(quote)
            self.check_quote(v, quote, r["doc_key"], r["page"])
            self.check_sector(v, m)
            nums = numbers_in(text)
            how, pos = find_value(value, nums)
            if how != "exact" and (r["unit"] or "") == "bps" and value is not None:
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
            self.check_list(v, m, text, pos, ctx)
            if pos is not None and (m is None or m.kind != "growth_pct") and _DELTA.search(text[max(0, pos - 40):pos]):
                v.fail("delta_value", "the number is a change (reduction of / grew by), not the level")
            if not plausible(m.kind if m else "any", r["metric"], value, value, r["unit"]):
                v.fail("plausible", f"{value} {r['unit']} outside bounds")
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


def run(db: str, out: str, profile: str | None = None, tables: tuple[str, ...] = ("guidance", "kpi_series")) -> dict:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    sectors = sectors_from(profile, con)
    con.close()
    ch = Checker(db, sectors)
    verdicts: list[Verdict] = []
    if "guidance" in tables:
        verdicts += ch.check_guidance()
    if "kpi_series" in tables:
        verdicts += ch.check_kpi()
    write(out, verdicts)
    return summary(verdicts)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", required=True, help="built database, opened read-only")
    ap.add_argument("--out", required=True, help="verdict database (row_check, row_check_fail)")
    ap.add_argument("--profile", default=None)
    ap.add_argument("--tables", default="guidance,kpi_series")
    a = ap.parse_args(argv)
    print(json.dumps(run(a.db, a.out, a.profile, tuple(a.tables.split(","))), indent=1))


if __name__ == "__main__":
    main()
