"""T-213 round 15: five code checks over one answer set (run B), no model call.

Reads the answer set written by a T-199 run (``answers.jsonl`` + ``calls.jsonl``) and
one store, and reports per answer five checks plus a follow-up text built ONLY from
the failed checks.  A repair agent (``tasks/handoff/T-213_R15_REPAIR_BRIEF.md``)
re-answers only the flagged lines; the checker never needs the grades.

Checks
------
C1 look-ahead   every cited source is known by ``as_of``, and every document the
                answer text names (fiscal year + annual report, quarter + call) exists
                with ``known_at <= as_of``.
C2 calls covered a question asking how something changed across calls (or over named
                quarters / the last four quarters) must cite every transcript in that
                window.
C3 speaker      a management-attributed sentence's figures must sit on a cited page
                under a management speaker label; the fact names the speaker the page
                shows instead.
C4 scope        a segment-scoped question: the sentence carries a scope word, and the
                segment's own printed figure (found in the store for the same date and
                metric) is the one the answer uses.
C5 dug          a "not found / not stated" part needs at least three of search,
                semantic, topic, cells and statements, a ``page`` read, and four
                distinct lookup tools in ``calls.jsonl``.

CLI::

    python -m reality_engine.answer.answer_checker --db <store> --answers <dir> \\
        --out <file.jsonl> [--qid BS-031 ...]

One output line per answer: ``{"qid", "checks": [{"id", "ok", "fact"}], "followup"}``.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence, cast

from reality_engine.db.readonly import connect_ro

__all__ = [
    "Answer",
    "Call",
    "Check",
    "Store",
    "check_c1",
    "check_c2",
    "check_c3",
    "check_c4",
    "check_c5",
    "check_answer",
    "followup_text",
    "load_answer_set",
    "main",
]

CHECKS = ("C1", "C2", "C3", "C4", "C5")

# ---------------------------------------------------------------- answer records


@dataclass(frozen=True)
class Source:
    doc_key: str
    doc_type: str
    page: int | None
    known_at: str


@dataclass(frozen=True)
class Answer:
    qid: str
    question: str
    as_of: str
    text: str
    sources: tuple[Source, ...]


@dataclass(frozen=True)
class Call:
    qid: str
    tool: str
    args: dict


@dataclass(frozen=True)
class Check:
    id: str
    ok: bool
    fact: str = ""
    look: tuple[str, ...] = ()


def _source(row: dict) -> Source:
    try:
        page = int(row["page"]) if row.get("page") not in (None, "") else None
    except (TypeError, ValueError):
        page = None
    return Source(
        doc_key=str(row.get("doc_key") or ""),
        doc_type=str(row.get("doc_type") or ""),
        page=page,
        known_at=str(row.get("known_at") or ""),
    )


def _answer(row: dict) -> Answer:
    return Answer(
        qid=str(row.get("qid") or ""),
        question=str(row.get("question") or ""),
        as_of=str(row.get("as_of") or "")[:10],
        text=str(row.get("answer") or ""),
        sources=tuple(_source(s) for s in row.get("sources") or [] if isinstance(s, dict)),
    )


def load_answer_set(folder: str | Path) -> tuple[list[Answer], list[Call]]:
    """``(answers, calls)`` from one answer folder; ``calls.jsonl`` may be absent."""
    folder = Path(folder)
    answers: list[Answer] = []
    calls: list[Call] = []
    path = folder / "answers.jsonl"
    if not path.is_file():
        raise SystemExit(f"no answers.jsonl under {folder}")
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            answers.append(_answer(json.loads(line)))
    calls_path = folder / "calls.jsonl"
    if calls_path.is_file():
        for line in calls_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            raw = row.get("args")
            try:
                args = json.loads(raw) if isinstance(raw, str) else dict(raw or {})
            except (TypeError, ValueError):
                args = {}
            calls.append(Call(qid=str(row.get("qid") or ""), tool=str(row.get("tool") or ""), args=args))
    return answers, calls


# ---------------------------------------------------------------- text helpers

_STOPWORDS = frozenset(
    """
    a an the and or of for to in on at by with from as is was were are be been being
    it its they their this that these those there here what which who whom whose how
    did does do done has have had will would can could should may might must not no
    but if when where why much many more most less least than then so such into out
    up down off again further once during before after above below both few other
    same own very just now last next first second third fourth one two three four five
    six seven eight nine ten year years earlier previous quarter quarterly month months
    half full fy crores crore lakh lakhs million millions billion billions mn bn cr
    rs inr usd percent cent per also only about over under between across each every
    all any some tell told say says said stated state according since while whereas
    let us me i we you he she them his her our your mt ma am pm
    what which how why when where who whom whose
    """.split()
)

_MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "oct": 10,
    "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}

_ABBREV_RE = re.compile(
    r"\b(rs|cr|crores?|approx|no|nos|viz|etc|i\.e|e\.g|pp|vs|ltd|co|inc|"
    r"jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec|fy)\.(?=\s|$)",
    re.IGNORECASE,
)
_PROTECT = "\u2024"


def sentences(text: str) -> list[str]:
    """Sentence spans without splitting ``Rs. 12`` or ``Mar. 2026``."""
    guarded = _ABBREV_RE.sub(lambda m: m.group(1) + _PROTECT, text)
    parts = re.split(r"(?<=[.!?;])\s+(?=[A-Z0-9(\"'“])|\n{2,}", guarded)
    return [p.replace(_PROTECT, ".").strip() for p in parts if p.strip()]


def words(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9][a-z0-9'&.\-]*", text.lower())]


def content_words(text: str) -> list[str]:
    out: list[str] = []
    for w in words(text):
        for piece in w.split("-"):
            piece = piece.strip(".'&")
            if len(piece) > 2 and piece not in _STOPWORDS and not piece.isdigit():
                out.append(piece)
    return out


@dataclass(frozen=True)
class Figure:
    value: float
    token: str
    kind: str  # "money" | "pct"
    pair: tuple[str, str] | None = None  # a printed range, "12-13 crore"


_SCALE = r"(?:crores?|crs?|lakhs?|lacs?|millions?|mn|billions?|bn)"
_CUR = r"(?:Rs\.?|INR|₹|\$|USD|US\$)"
_MONEY_RE = re.compile(rf"{_CUR}\s*(\d[\d,]*(?:\.\d+)?)\s*{_SCALE}\b", re.IGNORECASE)
_SCALE_ONLY_RE = re.compile(rf"(\d[\d,]*(?:\.\d+)?)\s*{_SCALE}\b", re.IGNORECASE)
_CURRENCY_ONLY_RE = re.compile(rf"{_CUR}\s*(\d[\d,]*(?:\.\d+)?)", re.IGNORECASE)
_PCT_RE = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(?:%|per\s*cent\b|percent\b)", re.IGNORECASE)


def figures(text: str) -> list[Figure]:
    """Money amounts (with a scale word or a currency) and percentages, in order."""
    spans: list[tuple[int, int, Figure]] = []

    def add(m: re.Match[str], kind: str) -> None:
        token = m.group(1).replace(",", "")
        try:
            value = float(token)
        except ValueError:
            return
        spans.append((m.start(), m.end(), Figure(value, token, kind)))

    for m in _MONEY_RE.finditer(text):
        add(m, "money")
    for m in _PCT_RE.finditer(text):
        add(m, "pct")
    for m in _SCALE_ONLY_RE.finditer(text):
        add(m, "money")
    for m in _CURRENCY_ONLY_RE.finditer(text):
        add(m, "money")
    kept: list[tuple[int, int, Figure]] = []
    for start, end, fig in sorted(spans):
        if any(start < k_end and end > k_start for k_start, k_end, _ in kept):
            continue
        kept.append((start, end, fig))
    merged: list[tuple[int, int, Figure]] = []
    i = 0
    while i < len(kept):
        start, end, fig = kept[i]
        if i + 1 < len(kept):
            n_start, n_end, n_fig = kept[i + 1]
            gap = text[end:n_start]
            if fig.kind == n_fig.kind == "money" and re.fullmatch(r"\s*[-–]\s*", gap):
                fig = Figure(fig.value, fig.token, "money", pair=(fig.token, n_fig.token))
                end = n_end
                i += 1
        merged.append((start, end, fig))
        i += 1
    return [fig for _, _, fig in merged]


def _strip_thousands(text: str) -> str:
    return re.sub(r"(?<=\d),(?=\d{3}(?!\d))", "", text)


def _token_re(token: str, kind: str) -> re.Pattern[str]:
    body = re.escape(token)
    if kind == "pct":
        return re.compile(rf"(?<![\d.]){body}(?![\d.])(?=\s*(?:%|per\s*cent|percent))", re.IGNORECASE)
    return re.compile(rf"(?<![\d.]){body}(?![\d.])")


def find_figure(page_text: str, fig: Figure) -> list[int]:
    """Positions where the figure's own number appears in ``page_text``."""
    flat = _strip_thousands(page_text)
    if fig.pair:
        first, second = fig.pair
        pattern = re.compile(
            rf"(?<![\d.]){re.escape(first)}(?![\d.])\s*(?:{_SCALE})?\s*[-–]\s*"
            rf"(?:{_CUR})?\s*{re.escape(second)}(?![\d.])",
            re.IGNORECASE,
        )
        return [m.start() for m in pattern.finditer(flat)]
    hits = [m.start() for m in _token_re(fig.token, fig.kind).finditer(flat)]
    if hits or "." in fig.token or len(fig.token) > 2:
        return hits
    # A short integer (5, 300) needs the money marker beside it on the same line.
    out: list[int] = []
    for m in _token_re(fig.token, "money").finditer(flat):
        near = flat[max(0, m.start() - 24): m.end() + 24].lower()
        if re.search(r"(rs\.?|inr|₹|\$|usd|" + _SCALE + ")", near):
            out.append(m.start())
    return out


_CALL_RE = re.compile(r"\bQ([1-4])FY(\d{2})\b", re.IGNORECASE)
_FY_RE = re.compile(r"\bFY(\d{2})\b", re.IGNORECASE)
_AR_RE = re.compile(r"\b(?:annual\s+report|annual_report|AR)\b", re.IGNORECASE)
_CALL_WORD_RE = re.compile(
    r"\b(?:earnings\s+call|concall|con-call|transcript|call)\b", re.IGNORECASE
)
_DOC_TYPE_WORDS = {
    "annual_report": r"(?:annual\s+report|annual_report|AR|AOC-?1|AOC)",
    "transcript": r"(?:earnings\s+call|concall|con-call|transcript|call)",
    "deck": r"(?:investor\s+presentation|investors?\s+presentation|presentation|deck|investor\s+update)",
    "results": r"(?:results|financial\s+results)",
    "announcement": r"(?:announcement|press\s+release|filing)",
}


def _date_end(as_of: str) -> str:
    as_of = (as_of or "").strip()
    return as_of if len(as_of) > 10 else f"{as_of}T23:59:59"


def _late(known_at: str, as_of: str) -> bool:
    known = (known_at or "").strip()[:19]
    return bool(known) and known > _date_end(as_of)


def _quarter_end(label: str) -> tuple[str, int, int]:
    """``Q2FY27`` -> (2026-09-30, fiscal year, quarter)."""
    m = re.fullmatch(r"Q([1-4])FY(\d{2})", label.upper())
    if not m:
        raise ValueError(label)
    q, fy = int(m.group(1)), 2000 + int(m.group(2))
    start = fy - 1
    month_day = {1: (6, 30), 2: (9, 30), 3: (12, 31), 4: (3, 31)}[q]
    year = start + (1 if q == 4 else 0)
    return f"{year:04d}-{month_day[0]:02d}-{month_day[1]:02d}", fy, q


def _dates(text: str) -> list[tuple[int, int, int]]:
    out: list[tuple[int, int, int]] = []
    for m in re.finditer(r"\b(\d{1,2})\s*(?:st|nd|rd|th)?\s+([A-Za-z]{3,9})\.?,?\s+(\d{4})\b", text):
        mon = _MONTHS.get(m.group(2).lower()[:9]) or _MONTHS.get(m.group(2).lower()[:4])
        if mon:
            out.append((int(m.group(3)), mon, int(m.group(1))))
    for m in re.finditer(r"\b([A-Za-z]{3,9})\.?\s+(\d{1,2}),?\s+(\d{4})\b", text):
        mon = _MONTHS.get(m.group(1).lower()[:9]) or _MONTHS.get(m.group(1).lower()[:4])
        if mon:
            out.append((int(m.group(3)), mon, int(m.group(2))))
    return out


def _short(known_at: str) -> str:
    return (known_at or "")[:16]


# ---------------------------------------------------------------- the store


class Store:
    """Read-only view of one company store: docs, pages, statements."""

    def __init__(self, path: str | Path):
        self.path = str(path)
        self.con = connect_ro(path, timeout_s=30.0)
        self.con.row_factory = sqlite3.Row
        self.docs: list[sqlite3.Row] = self._query(
            "SELECT doc_key, doc_type, filing_date, known_at FROM doc ORDER BY known_at")
        self._transcripts: list[sqlite3.Row] | None = None
        self._pages: dict[tuple[str, int], str] = {}
        self._speakers: dict[str, set[str]] = {}
        self._doc_pages: dict[str, list[int]] | None = None

    def _query(self, sql: str, params: Sequence[object] = ()) -> list[sqlite3.Row]:
        return cast("list[sqlite3.Row]", list(cast("Iterable[object]", self.con.execute(sql, params))))

    def _one(self, sql: str, params: Sequence[object] = ()) -> sqlite3.Row | None:
        return cast("sqlite3.Row | None", cast("Any", self.con.execute(sql, params)).fetchone())

    # -- documents
    def transcripts(self) -> list[sqlite3.Row]:
        if self._transcripts is None:
            self._transcripts = self._query(
                "SELECT doc_key, call_period, MIN(call_date) AS call_date, "
                "MAX(known_at) AS known_at, COUNT(*) AS n "
                "FROM transcript_statement GROUP BY doc_key, call_period ORDER BY call_date"
            )
        return self._transcripts

    def transcript_for(self, period: str) -> sqlite3.Row | None:
        period = period.upper()
        rows = [r for r in self.transcripts() if str(r["call_period"]).upper() == period]
        return rows[0] if rows else None

    # -- pages
    def page(self, doc_key: str, page: int) -> str:
        key = (doc_key, int(page))
        if key not in self._pages:
            row = self._one("SELECT text FROM doc_page WHERE doc_key=? AND page=?",
                            (doc_key, int(page)))
            self._pages[key] = str(row["text"] or "") if row else ""
        return self._pages[key]

    def doc_pages(self, doc_key: str) -> list[int]:
        if self._doc_pages is None:
            self._doc_pages = {}
            for r in self._query("SELECT doc_key, page FROM doc_page"):
                self._doc_pages.setdefault(str(r["doc_key"]), []).append(int(r["page"]))
            for pages in self._doc_pages.values():
                pages.sort()
        return self._doc_pages.get(doc_key, [])

    def pages_like_any(self, any_words: Sequence[str], must: str, as_of: str,
                       limit: int = 300) -> list[sqlite3.Row]:
        """Pages holding ``must`` and at least one of ``any_words`` (either name may miss)."""
        words = [w for w in dict.fromkeys(any_words) if w]
        if not words:
            return []
        sql = ("SELECT doc_key, page, text, known_at FROM doc_page WHERE known_at <= ? AND ("
               + " OR ".join("lower(text) LIKE ?" for _ in words) + ") AND lower(text) LIKE ?")
        params: list[object] = [_date_end(as_of), *(f"%{w.lower()}%" for w in words),
                                f"%{must.lower()}%"]
        sql += " LIMIT ?"
        params.append(limit)
        return self._query(sql, params)

    # -- management speakers
    def management_speakers(self, doc_key: str) -> set[str]:
        if doc_key not in self._speakers:
            names: set[str] = set()
            for r in self._query(
                "SELECT DISTINCT speaker FROM transcript_statement "
                "WHERE doc_key=? AND lower(role) IN ('md', 'mgmt', 'management', 'ceo', 'cfo')",
                (doc_key,),
            ):
                if r["speaker"]:
                    names.add(_norm_name(str(r["speaker"])))
            self._speakers[doc_key] = names
        return self._speakers[doc_key]


def _norm_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()


_LABEL_RE = re.compile(
    r"(?m)^[ \t]*([A-Z][A-Za-z.'’\-]*(?:[ \t]+[A-Z][A-Za-z.'’\-]*){0,4})[ \t]*:"
)


def page_turns(text: str) -> list[tuple[int, str]]:
    """``(start, label)`` for every speaker label that starts a line."""
    return [(m.start(1), m.group(1).strip()) for m in _LABEL_RE.finditer(text)]


def speaker_at(store: Store, doc_key: str, page_text: str, pos: int) -> str:
    """The label a position sits under, or ``''`` before the first label."""
    label = ""
    for start, name in page_turns(page_text):
        if start > pos:
            break
        label = name
    return label


def _is_management(store: Store, doc_key: str, label: str) -> bool:
    if not label:
        return False
    norm = _norm_name(label)
    if norm in store.management_speakers(doc_key):
        return True
    return bool(re.search(r"\b(managing director|cfo|ceo|management)\b", label, re.IGNORECASE))


# ---------------------------------------------------------------- C1 look-ahead


def _named_documents(text: str) -> list[tuple[str, str]]:
    """``(doc_type, period)`` documents the answer text names in words."""
    found: list[tuple[str, str]] = []

    def push(kind: str, period: str) -> None:
        item = (kind, period.upper())
        if item not in found:
            found.append(item)

    for m in re.finditer(
        r"(?:Q[1-4]FY\d{2})\b[^.;\n]{0,24}?\b(?:earnings\s+call|concall|con-call|transcript|call)\b",
        text,
        re.IGNORECASE,
    ):
        push("transcript", _CALL_RE.search(m.group(0)).group(0))  # type: ignore[union-attr]
    for m in re.finditer(
        r"\b(?:earnings\s+call|concall|con-call|transcript|call)\b[^.;\n]{0,16}?(Q[1-4]FY\d{2})\b",
        text,
        re.IGNORECASE,
    ):
        push("transcript", m.group(1))
    for m in re.finditer(
        r"(?:FY\d{2})\b[^.;\n]{0,24}?\b(?:annual\s+report|annual_report|AR|AOC-?1)\b",
        text,
        re.IGNORECASE,
    ):
        push("annual_report", _FY_RE.search(m.group(0)).group(0))  # type: ignore[union-attr]
    for m in re.finditer(
        r"\b(?:annual\s+report|annual_report|AR|AOC-?1)\b[^.;\n]{0,16}?(FY\d{2})\b",
        text,
        re.IGNORECASE,
    ):
        push("annual_report", m.group(1))
    for m in re.finditer(
        r"\b(?:Q[1-4]FY\d{2})\b[^.;\n]{0,24}?\b(?:investor\s+presentation|investors?\s+presentation|"
        r"presentation|deck|investor\s+update|press\s+release|results)\b",
        text,
        re.IGNORECASE,
    ):
        m0 = m.group(0)
        kind = "deck" if re.search(r"presentation|deck|investor\s+update", m0, re.IGNORECASE) else (
            "results" if re.search(r"results", m0, re.IGNORECASE) else "announcement")
        push(kind, _CALL_RE.search(m0).group(0))  # type: ignore[union-attr]
    return found


def _doc_matches(store: Store, kind: str, period: str) -> list[sqlite3.Row]:
    """Store documents of ``kind`` that answer to a named period."""
    if kind == "transcript":
        period = period.upper()
        keys = {str(r["doc_key"]) for r in store.transcripts() if str(r["call_period"]).upper() == period}
        return [d for d in store.docs if str(d["doc_key"]) in keys]
    if kind == "annual_report":
        year = 2000 + int(period[2:])
        out = []
        for d in store.docs:
            if str(d["doc_type"]) != "annual_report":
                continue
            filing = str(d["filing_date"] or "")
            if filing[:4].isdigit() and int(filing[:4]) == year:
                out.append(d)
        return out
    # deck/results/announcement: filed between the quarter end and the next quarter end.
    end, _, _ = _quarter_end(period)
    start, _, _ = _quarter_end(f"Q4FY{int(period[4:]) - 1:02d}")
    out = []
    for d in store.docs:
        if str(d["doc_type"]) != kind:
            continue
        filing = str(d["filing_date"] or "")[:10]
        if filing and start <= filing <= end:
            out.append(d)
    return out


def check_c1(answer: Answer, store: Store) -> Check:
    late: list[str] = []
    for src in answer.sources:
        if _late(src.known_at, answer.as_of):
            late.append(
                f"source {src.doc_key} p{src.page} is known at {_short(src.known_at)}, "
                f"after as_of {answer.as_of}"
            )
    for kind, period in _named_documents(answer.text):
        rows = _doc_matches(store, kind, period)
        name = f"{period} {kind.replace('_', ' ')}"
        if not rows:
            if kind in {"deck", "results", "announcement"}:
                try:
                    end, _, _ = _quarter_end(period)
                except ValueError:
                    end = ""
                if end and end <= answer_date(answer.as_of):
                    continue  # unresolvable, but it could have existed by as_of
            late.append(f"{name} does not exist in the store")
            continue
        known = [r for r in rows if not _late(str(r["known_at"]), answer.as_of)]
        if known:
            continue
        first = min(rows, key=lambda r: str(r["known_at"]))
        late.append(
            f"the answer names the {name} ({first['doc_key']}) but it is known at "
            f"{_short(str(first['known_at']))}, after as_of {answer.as_of}"
        )
    if not late:
        return Check("C1", True)
    look = [s.doc_key for s in answer.sources if not _late(s.known_at, answer.as_of)]
    return Check("C1", False, "; ".join(late), tuple(dict.fromkeys(look)))


# ---------------------------------------------------------------- C2 calls covered

_CHANGE_RE = re.compile(
    r"\b(chang(?:e|ed|es|ing)|across|between\s+(?:the\s+)?calls?|over\s+the\s+calls?|"
    r"each\s+call|every\s+call|revise[ds]?|trend)\b",
    re.IGNORECASE,
)
# A change over the figures printed in two quarter labels is not a call-coverage question.
_CALL_CONTEXT_RE = re.compile(
    r"\b(calls?|concall|con-call|transcripts?|management|guidance|commentary)\b", re.IGNORECASE
)
_FY_SPAN_RE = re.compile(r"\bFY(\d{2})\s*(?:-|–|to|and|&)\s*(?:FY)?(\d{2})\b", re.IGNORECASE)


def _window_periods(question: str, store: Store, as_of: str) -> tuple[set[str], str]:
    """Call periods the question's change window names, and a label for the fact."""
    periods = {m.group(0).upper() for m in _CALL_RE.finditer(question)}
    if periods:
        return periods, "the calls the question names"
    fys: set[int] = set()
    for m in _FY_SPAN_RE.finditer(question):
        lo, hi = sorted((int(m.group(1)), int(m.group(2))))
        fys.update(range(lo, hi + 1))
    fys.update(int(m.group(1)) for m in _FY_RE.finditer(question))
    if fys:
        out = {f"Q{q}FY{fy:02d}" for fy in fys for q in (1, 2, 3, 4)}
        return out, "the fiscal years the question names"
    recent = [str(r["call_period"]).upper() for r in store.transcripts()
              if str(r["call_date"] or "")[:10] <= answer_date(as_of)]
    return set(recent[-4:]), "the last four calls up to as_of"


def answer_date(as_of: str) -> str:
    return (as_of or "")[:10]


def check_c2(answer: Answer, store: Store) -> Check:
    if not _CHANGE_RE.search(answer.question) or not _CALL_CONTEXT_RE.search(answer.question):
        return Check("C2", True)
    window, label = _window_periods(answer.question, store, answer.as_of)
    if not window:
        return Check("C2", True)
    required = [
        r for r in store.transcripts()
        if str(r["call_period"]).upper() in window
        and str(r["call_date"] or "")[:10] <= answer_date(answer.as_of)
        and not _late(str(r["known_at"]), answer.as_of)
    ]
    if not required:
        return Check("C2", True)
    cited = {s.doc_key for s in answer.sources if s.doc_type == "transcript"}
    for kind, period in _named_documents(answer.text):
        if kind == "transcript":
            for r in _doc_matches(store, "transcript", period):
                cited.add(str(r["doc_key"]))
    missing = [r for r in required if str(r["doc_key"]) not in cited]
    if not missing:
        return Check("C2", True)
    fact = (
        f"the question asks how it changed ({label}); {len(required)} calls are in that window "
        f"and the answer cites {len(required) - len(missing)}"
    )
    calls = [
        f"{r['call_period']} call {r['doc_key']} ({str(r['call_date'])[:10]})" for r in missing
    ]
    return Check("C2", False, fact + ": missing " + ", ".join(calls),
                 tuple(str(r["doc_key"]) for r in missing))


# ---------------------------------------------------------------- C3 speaker

_ATTRIBUTION_RE = re.compile(
    r"\b(?:management|mgmt|the\s+company)\b[^.]{0,48}?\b(?:said|says|say|saying|stated|states|stating|"
    r"guided|guides|guiding|added|noted|noting|indicated|indicating|clarified|believes|expects|"
    r"expected|disclaimed|confirmed|reiterated|maintains|flagged|told|shared)\b"
    r"|\b(?:cfo|md|managing\s+director)\b",
    re.IGNORECASE,
)
_AFFIRM_RE = re.compile(r"\b(?:correct|right|yes|exactly|that's\s+right|perfect)\b", re.IGNORECASE)


def _cited_transcripts(answer: Answer) -> list[tuple[str, int | None]]:
    out: list[tuple[str, int | None]] = []
    for s in answer.sources:
        if s.doc_type == "transcript":
            out.append((s.doc_key, s.page))
    return out


def _management_before(store: Store, doc_key: str, text: str, pos: int) -> list[str]:
    """Labels that start before a position on the page (a management one backs it)."""
    return [name for start, name in page_turns(text) if start < pos]


def _management_evidence(store: Store, doc_key: str, page: int, fig: Figure) -> str | None:
    """``'management'``/``'<label>'``/``None``: who the page shows before the figure."""
    text = store.page(doc_key, page)
    hits = find_figure(text, fig)
    if not hits:
        return None
    earlier = _management_before(store, doc_key, text, hits[0])
    if any(_is_management(store, doc_key, name) for name in earlier):
        return "management"
    label = earlier[-1] if earlier else speaker_at(store, doc_key, text, hits[0])
    # A short management turn straight after may confirm the figure ("Correct.").
    for start, name in page_turns(text):
        if start > hits[0] and _is_management(store, doc_key, name):
            turn_text = text[start: start + 120]
            if _AFFIRM_RE.search(turn_text) and len(turn_text) < 120:
                return "management"
    return label


def check_c3(answer: Answer, store: Store) -> Check:
    cited = _cited_transcripts(answer)
    if not cited:
        return Check("C3", True)
    problems: list[str] = []
    for sentence in sentences(answer.text):
        if not _ATTRIBUTION_RE.search(sentence):
            continue
        figs = figures(sentence)
        if not figs:
            continue
        named = {m.group(0).upper() for m in _CALL_RE.finditer(sentence)}
        pages = list(cited)
        if named:
            allowed = {str(r["doc_key"]) for p in named
                       if (r := store.transcript_for(p)) is not None}
            if allowed:
                pages = [(d, p) for d, p in pages if d in allowed]
        if not pages:
            problems.append(
                f"the sentence names {'/'.join(sorted(named))} and attributes figures to management, "
                f"but no page of that call is cited"
            )
            continue
        for fig in figs:
            found = False
            shown = ""
            where = ""
            for doc_key, page in pages:
                if page is None:
                    continue
                evidence = _management_evidence(store, doc_key, int(page), fig)
                if evidence is None:
                    continue
                found = True
                shown, where = evidence, f"{doc_key} p{page}"
                if evidence == "management":
                    break
            if found and shown == "management":
                continue
            if found and shown:
                problems.append(
                    f"the sentence attributes {_figure_text(fig)} to management, but the cited page "
                    f"{where} shows it under '{shown}'"
                )
            elif found:
                problems.append(
                    f"the sentence attributes {_figure_text(fig)} to management, but on the cited "
                    f"page {where} it sits before any speaker label"
                )
            else:
                if any(_statement_holds(store, d, fig) for d, _ in pages):
                    continue
                off = _elsewhere_in_cited(store, [d for d, _ in pages], fig)
                if off and off[1] == "management":
                    continue  # off the cited page, but under a management label
                if off:
                    problems.append(
                        f"the sentence attributes {_figure_text(fig)} to management; the cited page "
                        f"does not hold it, the transcript shows it at {off[0]} under '{off[1]}'"
                    )
                else:
                    problems.append(
                        f"the sentence attributes {_figure_text(fig)} to management, but it is not on "
                        f"the cited transcript pages"
                    )
    if not problems:
        return Check("C3", True)
    return Check("C3", False, " | ".join(dict.fromkeys(problems)),
                 tuple(dict.fromkeys(doc for doc, _ in cited)))


def _statement_holds(store: Store, doc_key: str, fig: Figure) -> bool:
    """The store's own management statement rows for the document carry the figure."""
    for row in store._query(
        "SELECT quote FROM transcript_statement WHERE doc_key=? AND "
        "lower(role) IN ('md', 'mgmt', 'management', 'ceo', 'cfo')",
        (doc_key,),
    ):
        if find_figure(str(row["quote"] or ""), fig):
            return True
    return False


def _elsewhere_in_cited(store: Store, doc_keys: Sequence[str], fig: Figure) -> tuple[str, str] | None:
    """Where the figure sits in the cited documents, if not on the cited page."""
    for doc_key in dict.fromkeys(doc_keys):
        for page in store.doc_pages(doc_key):
            text = store.page(doc_key, page)
            hits = find_figure(text, fig)
            if not hits:
                continue
            label = speaker_at(store, doc_key, text, hits[0])
            if _is_management(store, doc_key, label):
                return f"{doc_key} p{page}", "management"
            return f"{doc_key} p{page}", label or "no speaker label"
    return None


def _figure_text(fig: Figure) -> str:
    suffix = "%" if fig.kind == "pct" else " crore"
    if fig.pair:
        return f"{fig.pair[0]}-{fig.pair[1]}{suffix}"
    return f"{fig.token}{suffix}"


# ---------------------------------------------------------------- C4 scope

_SEGMENT_RE = re.compile(
    r"(?:the\s+|that\s+)?((?:[A-Z][\w&.\-’']*|and|of|for)"
    r"(?:\s+(?:[A-Z][\w&.\-’']*|and|of|for)){0,10})\s+"
    r"(?:business|segment|division|unit|vertical)\b"
)
_GENERIC_SCOPE_RE = re.compile(
    r"\b(company\s*[- ]?\s*wide|company\s+level|consolidated|group\s+level|overall|total|"
    r"aggregate|as\s+a\s+whole|blended)\b",
    re.IGNORECASE,
)


_QUESTION_WORDS = {
    "what", "which", "how", "why", "when", "where", "who", "whom", "whose", "did",
    "does", "do", "is", "was", "were", "are", "has", "have", "had", "by",
}


def _segment_phrase(question: str) -> str:
    for m in _SEGMENT_RE.finditer(question):
        parts = m.group(1).split()
        while parts and parts[0].lower() in _QUESTION_WORDS:
            parts.pop(0)
        phrase = " ".join(parts)
        if len(content_words(phrase)) >= 2:
            return phrase
    # \"... the <Name> order book ... to that segment's revenue\": no business/segment tail.
    if re.search(r"\bsegments?'?", question, re.IGNORECASE):
        for m in re.finditer(
            r"((?:[A-Z][\w&.\-’']*)(?:\s+(?:[A-Z][\w&.\-’']*|and|of|for)){1,10})", question
        ):
            phrase = " ".join(m.group(1).split())
            if len(content_words(phrase)) >= 2:
                return phrase
    return ""


def _ngrams(text: str, sizes: Iterable[int] = (2, 3)) -> list[tuple[str, ...]]:
    """Contiguous word n-grams of a question, hyphens and punctuation flattened."""
    tokens = [t for t in re.split(r"[\s/&]+", text.lower()) if t]
    tokens = [re.sub(r"[^a-z0-9\-']", "", t).strip("-") for t in tokens]
    tokens = [t for t in tokens if t]
    out: list[tuple[str, ...]] = []
    for n in sizes:
        for i in range(len(tokens) - n + 1):
            out.append(tuple(tokens[i:i + n]))
    return out


def _flat_tokens(text: str) -> list[str]:
    return [t for t in re.split(r"[\s/&]+", text.lower()) if t]


def _has_phrase(sentence: str, gram: tuple[str, ...]) -> bool:
    flat = _flat_tokens(sentence)
    flat = [re.sub(r"[^a-z0-9\-']", "", t).strip("-") for t in flat]
    return any(tuple(flat[i:i + len(gram)]) == gram for i in range(len(flat) - len(gram) + 1))


def _quarter_window(label: str) -> tuple[str, str]:
    end, _, q = _quarter_end(label)
    y, m, _ = (int(x) for x in end.split("-"))
    start_month = {1: 4, 2: 7, 3: 10, 4: 1}[q]
    start_year = y if q == 4 else y
    return f"{start_year:04d}-{start_month:02d}-01", end


def _period_ok(sentence: str, question: str) -> bool:
    """The sentence falls in the date or quarter the question names."""
    dates = set(_dates(question))
    periods = {m.group(0).upper() for m in _CALL_RE.finditer(question)}
    if not dates and not periods:
        return True
    sent_dates = set(_dates(sentence))
    if dates and (dates & sent_dates):
        return True
    for period in periods:
        if period in sentence.upper():
            return True
        try:
            start, end = _quarter_window(period)
        except ValueError:
            continue
        if any(start <= f"{y:04d}-{mo:02d}-{d:02d}" <= end for y, mo, d in sent_dates):
            return True
    return False


def _segment_ordinal(store: Store, phrase: str, as_of: str) -> int | None:
    """The segment number the company prints for this phrase (\"Segment 1 – <name>\")."""
    tokens = set(content_words(phrase))
    if not tokens:
        return None
    for row in store._query(
        "SELECT text FROM doc_page WHERE known_at <= ? AND (lower(text) LIKE '%segment 1%' "
        "OR lower(text) LIKE '%segment 2%' OR lower(text) LIKE '%segment 3%') LIMIT 200",
        (_date_end(as_of),),
    ):
        for m in re.finditer(r"Segment\s+([1-4])\s*[–\-:]\s*([^\n]{3,120})", str(row["text"])):
            name = set(content_words(m.group(2)))
            if len(tokens & name) >= max(2, len(tokens) // 2):
                return int(m.group(1))
    return None


def _scope_ok(sentence: str, segment_tokens: set[str], ordinal: int | None) -> bool:
    if _GENERIC_SCOPE_RE.search(sentence):
        return True
    tokens = set(content_words(sentence))
    if segment_tokens & tokens:
        return True
    if ordinal is not None and re.search(rf"\bsegment\s+{ordinal}\b", sentence, re.IGNORECASE):
        return True
    return bool(re.search(r"\bsegment\s+(?:one|two|three|four)\b", sentence, re.IGNORECASE)) and ordinal is not None


def _metric_grams(question: str, phrase: str) -> list[tuple[str, ...]]:
    seg_tokens = set(content_words(phrase))
    return [
        g for g in _ngrams(question)
        if any(w not in _STOPWORDS for w in g)
        and not all(w in seg_tokens or w in _STOPWORDS for w in g)
    ]


def _printed_segment_figures(
    store: Store, phrase: str, question: str, as_of: str
) -> list[tuple[float, str, int, str]]:
    """The segment's own printed figures for the question's metric and date."""
    seg_tokens = set(content_words(phrase))
    seg_words = sorted(seg_tokens, key=len, reverse=True)
    metric = _metric_grams(question, phrase)
    seeds = sorted({w for g in metric for w in g if w not in _STOPWORDS and w not in seg_tokens},
                   key=len)
    seeds = [w for w in seeds if len(w) >= 4]
    if not seg_words or not metric or not seeds:
        return []
    anchors = [w for w in sorted(seg_words, key=len) if len(w) >= 4][:3] or seg_words[:1]
    rows = store.pages_like_any(anchors, seeds[0], as_of=as_of)
    out: list[tuple[float, str, int, str]] = []
    for row in rows:
        text = str(row["text"] or "")
        for sent in sentences(text):
            low = sent.lower()
            if not any(w in low for w in seg_words):
                continue
            if sum(1 for g in metric if _has_phrase(sent, g)) < 2:
                continue
            if not _period_ok(sent, question):
                continue
            for fig in figures(sent):
                if fig.kind == "money":
                    out.append((fig.value, str(row["doc_key"]), int(row["page"]), sent.strip()[:220]))
    return out


def check_c4(answer: Answer, store: Store) -> Check:
    phrase = _segment_phrase(answer.question)
    if not phrase:
        return Check("C4", True)
    seg_tokens = set(content_words(phrase))
    ordinal = _segment_ordinal(store, phrase, answer.as_of)
    problems: list[str] = []
    money = [f for f in figures(answer.text) if f.kind == "money"]

    # (a) a money figure in a segment-scoped answer carries a scope word.
    for sentence in sentences(answer.text):
        sentence_money = [f for f in figures(sentence) if f.kind == "money"]
        if not sentence_money or _scope_ok(sentence, seg_tokens, ordinal):
            continue
        problems.append(
            f"the answer gives {_figure_text(sentence_money[0])} without saying whether it is the "
            f"'{phrase}' figure or the company-wide figure"
        )
        break

    # (b) the segment's own printed figure for the same metric and date is used.
    printed = _printed_segment_figures(store, phrase, answer.question, answer.as_of)
    printed_values = {value for value, *_ in printed}
    if printed and money and not (printed_values & {f.value for f in money}):
        near = [p for p in printed if any(0.5 * p[0] <= f.value <= 2.0 * p[0] for f in money)]
        if near:
            value, doc_key, page, sent = near[0]
            grams = _metric_grams(answer.question, phrase)
            metric_sentence = max(
                sentences(answer.text),
                key=lambda s: sum(1 for g in grams if _has_phrase(s, g)),
                default="",
            )
            ranked = [f for f in figures(metric_sentence)
                      if f.kind == "money" and 0.5 * value <= f.value <= 2.0 * value]
            shown = (ranked[0].token if ranked
                     else min(money, key=lambda f: abs(f.value - value)).token)
            problems.append(
                f"the answer uses {shown} for the '{phrase}' figure, but the store prints "
                f"{value:,.2f} for it on {doc_key} p{page} (\"{sent[:120]}\")"
            )
    if not problems:
        return Check("C4", True)
    look = tuple(dict.fromkeys(d for _, d, _, _ in printed))
    return Check("C4", False, " | ".join(problems), look)


# ---------------------------------------------------------------- C5 dug

_NOT_FOUND_RE = re.compile(
    r"\b(?:not\s+found|not\s+stated|not\s+disclosed|not\s+available|does\s+not\s+disclose|"
    r"data\s+not\s+found|not\s+in\s+the\s+store|nothing\s+in\s+the\s+store|no\s+such\s+figure)\b",
    re.IGNORECASE,
)
_TEXT_TOOLS = ("search", "semantic", "topic", "cells", "statements")
_LOOKUP_TOOLS = set(_TEXT_TOOLS) | {
    "fact", "fin", "ratio", "kpi", "guidance", "holding", "tech", "docs", "calc", "sql",
}


def _tool_name(name: str) -> str:
    name = name.strip().lower()
    for prefix in ("mcp__reality-data__", "mcp__p3ask__", "p3ask__", "pilot3_"):
        if name.startswith(prefix):
            name = name[len(prefix):]
    return name


def check_c5(answer: Answer, calls: Sequence[Call], store: Store) -> Check:
    if not _NOT_FOUND_RE.search(answer.text):
        return Check("C5", True)
    used = {_tool_name(c.tool) for c in calls if c.qid == answer.qid}
    text_used = [t for t in _TEXT_TOOLS if t in used]
    lookups = sorted(used & _LOOKUP_TOOLS)
    pages = "page" in used
    problems: list[str] = []
    if len(text_used) < 3:
        problems.append(
            f"the answer says a part is not found but only {len(text_used)} of "
            f"search/semantic/topic/cells/statements were used ({', '.join(text_used) or 'none'})"
        )
    if not pages:
        problems.append("no page was read before the not-found part")
    if len(lookups) < 4:
        problems.append(
            f"only {len(lookups)} distinct lookup tools were used "
            f"({', '.join(lookups) or 'none'}); four routes are needed before 'not found'"
        )
    if not problems:
        return Check("C5", True)
    return Check("C5", False, "; ".join(problems))


# ---------------------------------------------------------------- assembly


def check_answer(answer: Answer, calls: Sequence[Call], store: Store) -> list[Check]:
    return [
        check_c1(answer, store),
        check_c2(answer, store),
        check_c3(answer, store),
        check_c4(answer, store),
        check_c5(answer, calls, store),
    ]


def followup_text(checks: Sequence[Check]) -> str:
    lines: list[str] = []
    for check in checks:
        if check.ok:
            continue
        line = f"Check failed: {check.id} - {check.fact}."
        if check.look:
            line += " Look again in " + "; ".join(check.look) + "."
        lines.append(line)
    return " ".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="answer_checker", description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--db", required=True, help="company store to read (read-only)")
    ap.add_argument("--answers", required=True, help="folder with answers.jsonl (+ calls.jsonl)")
    ap.add_argument("--out", required=True, help="JSONL output, one line per answer")
    ap.add_argument("--qid", action="append", default=None, help="only these qids (repeatable)")
    args = ap.parse_args(argv)

    answers, calls = load_answer_set(args.answers)
    wanted = {q.upper() for q in args.qid or []}
    if wanted:
        answers = [a for a in answers if a.qid.upper() in wanted]
    store = Store(args.db)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    flagged = 0
    by_check = {cid: 0 for cid in CHECKS}
    with out.open("w", encoding="utf-8") as fh:
        for answer in answers:
            checks = check_answer(answer, calls, store)
            failed = [c for c in checks if not c.ok]
            if failed:
                flagged += 1
                for c in failed:
                    by_check[c.id] += 1
            row = {
                "qid": answer.qid,
                "checks": [{"id": c.id, "ok": c.ok, "fact": c.fact} for c in checks],
                "followup": followup_text(checks),
            }
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(
        f"{len(answers)} answers, {flagged} flagged; "
        + ", ".join(f"{cid} {by_check[cid]}" for cid in CHECKS)
        + f"; wrote {out}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
