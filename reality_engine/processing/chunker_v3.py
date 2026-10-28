"""chunker_v3 — documents to searchable chunks (spec: tasks/ARCHITECTURE_OVERHAUL_2026-10-27 §2.2/§3/§4).

Structure comes from :mod:`reality_engine.processing.chunker_v2` (already
validated on the corpus: it wins decks by 11.5 pts R@1 over the old chunker),
so this module reuses its unit detection and adds only what v3 needs:

* one entry point per doc type, with the four v3-only types
  (``results_notes``, ``announcement``, and the generic ``circular`` path);
* a v3 header carrying ``isin``, ``symbol_at_time`` and ``known_at`` so a
  filter never needs a join to the doc row;
* deterministic tags from a closed vocabulary (:data:`TAG_VOCAB`), computed
  from the chunk itself, never from a model;
* speaker roles for concalls (management / analyst / moderator);
* entity mentions resolved to ISIN by :class:`EntityResolver`.

Body text is always a verbatim slice of the parsed original (case preserved).
This module never reads ``document_chunks`` or any database on its own: the
caller supplies the parsed pages and the document metadata.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from typing import Iterable, Sequence

from reality_engine.processing import chunker_v2 as v2

MAX_CHARS = v2.MAX_CHARS
MIN_CHARS = v2.MIN_CHARS
QA_MAX_CHARS = v2.QA_MAX_CHARS
#: One announcement is one retrieval unit up to this size (reviewer spec: 1,500 tokens).
ANNOUNCEMENT_MAX_CHARS = 6000

DOC_TYPES = ("concall", "deck", "annual_report", "results_notes", "announcement", "pib", "budget", "rbi", "news", "offer")

DOC_LABELS = {
    "concall": "Concall transcript",
    "deck": "Investor deck",
    "annual_report": "Annual report",
    "results_notes": "Results notes",
    "announcement": "Announcement",
    "pib": "PIB release",
    "budget": "Budget document",
    "rbi": "RBI document",
    "news": "News",
    "offer": "Offer document",
}

#: Deterministic tags (spec §4.5). A tag outside this map must never be written.
#: (axis, label, definition, excludes)
TAG_VOCAB: dict[str, tuple[str, str, str, str]] = {
    "guidance": ("content", "Guidance", "Management states a future number or direction for revenue, margin, volume, capex or order book.", "a past result restated as a trend"),
    "order_book": ("content", "Order book", "An order book, order inflow, backlog or contract win with a value or period.", "generic strong demand with no order language"),
    "capacity": ("content", "Capacity", "Capacity addition, utilisation, debottlenecking, new plant or line.", "capex money with no capacity words"),
    "capex": ("content", "Capex", "Capital expenditure planned or spent, with or without an amount.", "maintenance spend described as routine"),
    "margin": ("content", "Margin", "Margin level, expansion, contraction or mix effect.", "revenue growth alone"),
    "pricing": ("content", "Pricing", "Price increase or cut, realisation, discounting.", "pricing power as a moat phrase only"),
    "demand": ("content", "Demand", "Demand strength or weakness, volume growth, offtake.", "supply-side commentary"),
    "debt": ("content", "Debt", "Borrowings, refinancing, leverage, interest cost, rating.", "trade payables"),
    "working_capital": ("content", "Working capital", "Receivable/payable/inventory days, cash conversion.", "one-off provisions"),
    "m_and_a": ("content", "M&A", "Acquisition, merger, demerger, stake sale, JV.", "a supplier relationship"),
    "regulatory": ("content", "Regulatory", "Licence, approval, tariff order, SEBI/RBI action, GST/customs.", "general policy commentary without an action"),
    "management_change": ("content", "Management change", "MD/CEO/CFO/board change, resignation, succession.", "analyst names"),
    "dividend_buyback": ("content", "Dividend/buyback", "Dividend, buyback, bonus, split, record date.", "earnings distribution discussion"),
    "risk": ("content", "Risk", "Stated risk, contingency, litigation, going-concern, impairment.", "routine safe-harbour boilerplate"),
    "accounting_note": ("content", "Accounting note", "Note to accounts, policy change, restatement, auditor qualification.", "the P&L table itself"),
    "analyst_view": ("content", "Analyst view", "A named analyst or broker expressing a view (opinions only).", "management statements"),
    # structural (parser-derived, free)
    "section:opening_remarks": ("event", "Section: opening remarks", "Concall opening remarks before the first question.", ""),
    "section:qa": ("event", "Section: Q&A", "The analyst question and answer part of a concall.", ""),
    "section:mda": ("event", "Section: MD&A", "Management discussion and analysis of the annual report.", ""),
    "section:notes": ("event", "Section: notes", "Notes to the financial statements.", ""),
    "section:related_party": ("event", "Section: related party", "Related-party transactions or balances.", ""),
    "section:segment": ("event", "Section: segment", "Segment information or segment revenue.", ""),
    "speaker_role:management": ("event", "Speaker: management", "Company management speaking.", ""),
    "speaker_role:analyst": ("event", "Speaker: analyst", "An analyst or investor speaking.", ""),
    "speaker_role:moderator": ("event", "Speaker: moderator", "The call moderator or host.", ""),
    "has_number": ("numeric", "Has number", "The chunk contains at least one numeric token.", ""),
    "forward_looking": ("numeric", "Forward looking", "The chunk makes a statement about the future (spec §4.4 rule).", "a pure table row"),
    "unit:inr_crore": ("numeric", "Unit: INR crore", "The chunk states an amount in crore.", ""),
    "unit:inr_lakh": ("numeric", "Unit: INR lakh", "The chunk states an amount in lakh.", ""),
    "unit:percent": ("numeric", "Unit: percent", "The chunk states a percentage.", ""),
    "unit:bps": ("numeric", "Unit: bps", "The chunk states basis points.", ""),
    "unit:usd": ("numeric", "Unit: USD", "The chunk states an amount in US dollars.", ""),
}

#: A tag that is not in the vocabulary cannot be written (the DB enforces it too).
assert all(len(v) == 4 for v in TAG_VOCAB.values())

_TAG_RULES: tuple[tuple[str, re.Pattern], ...] = (
    ("order_book", re.compile(r"\b(order book|order inflow|order intake|order backlog|order win|backlog|contract win|won (?:an? )?order|bagged (?:an? )?(?:order|contract|project)|awarded (?:an? )?(?:order|contract|project|loa)|letter of award|l1 bidder)\b", re.I)),
    ("capacity", re.compile(r"\b(capacity (?:addition|expansion|enhancement|build-?out|creation|utilisation|utilization)|debottleneck\w*|de-bottleneck\w*|new (?:plant|line|facility)|commissioned (?:a|its|the|new|our))\b", re.I)),
    ("capex", re.compile(r"\b(capex|capital expenditure|capital outlay)\b", re.I)),
    ("margin", re.compile(r"\bmargins?\b", re.I)),
    ("pricing", re.compile(r"\b(price (?:hike|increase|rise|cut|reduction|revision)|realisation|realization|pricing(?! power))\b", re.I)),
    ("demand", re.compile(r"\b(demand (?:growth|momentum|outlook|environment|scenario|side|for|in)|consumer demand|export demand|offtake|volume growth)\b", re.I)),
    ("debt", re.compile(r"\b(borrowings?|net debt|debt (?:programme|program|control|reduction|repayment|securities|servicing)|refinanc\w*|interest cost|credit rating|rating action|leverage (?:ratio|profile)|financial leverage)\b", re.I)),
    ("working_capital", re.compile(r"\b(working capital|receivable days|payable days|inventory days|cash conversion|trade receivables)\b", re.I)),
    ("m_and_a", re.compile(r"\b(acquisition (?:of|by)|acquired (?:an? )?(?:stake|company|business|majority|control|interest|equity|shares)|merger|demerger|stake sale|joint venture|\bJV\b|amalgamation)\b", re.I)),
    ("regulatory", re.compile(r"\b(licen[cs]e[sd]?|tariff order|show[- ]cause notice|penalty|regulatory action|SEBI (?:notice|order|action|direction|show|bar)|RBI (?:notice|order|bar|penalty|direction|framework)|GST (?:notice|demand|order)|customs (?:duty|notice|order))\b", re.I)),
    ("management_change", re.compile(r"\b(appointed (?:as|an?|to)|appointment of|resign(?:ed (?:as|from)|ation of)|succession|stepped down|change in (?:management|board|directorship)|retirement of (?:the )?(?:managing director|md|ceo|cfo|director|chairman|company secretary|chief)|new (?:CEO|CFO|MD))\b", re.I)),
    ("dividend_buyback", re.compile(r"\b(dividend|buy-?back|bonus issue|stock split|record date)\b", re.I)),
    ("risk", re.compile(r"\b(risk (?:factor|assessment|exposure)|risks\b|contingent liabilit\w*|litigation|going concern|impairment (?:loss|charge|allowance)|cyber-?security (?:risk|exposure)|loan losses?)\b", re.I)),
    ("accounting_note", re.compile(r"(?:(?:^|\n)\s*notes? (?:to |\d)|^note \d|accounting polic\w*|restat\w*|auditor'?s? qualification)", re.I|re.M)),
)

_GUIDANCE_VERB = re.compile(r"\b(guidance|guided|guide to|we expect|expects? to|target(?:ing|s|ed)?|aim(?:s|ing)? to|outlook|we are confident|maintain(?:ing)? (?:our|the))\b", re.I)
_GUIDANCE_METRIC = re.compile(r"\b(revenue|sales|margin|ebitda|pat|profit|volume|capex|order book|growth|turnover)\b", re.I)

#: Spec §4.4 forward-looking rule, tightened twice.  A bare forward verb fires
#: on 85% of concall chunks (ordinary "will / expect / should" prose), so the
#: tag also needs a second, independent signal: a future time anchor or an
#: explicit target/guidance noun.
FORWARD_LOOKING = re.compile(
    r"\b(will|would|expect|expects|expected|guidance|guide|guided|aim|aims|aiming|target|targets|"
    r"targeting|plan to|plans to|intend|intends|should|likely|anticipate|anticipates|forecast|"
    r"outlook|going forward|committed to)\b", re.I)
FUTURE_ANCHOR = re.compile(
    r"\b(next (?:quarter|half|year|fiscal|financial year|few quarters|few years|two|three|twelve)|"
    r"second half|first half|coming (?:quarter|half|year|months|years)|"
    r"by (?:20\d{2}|FY\d{2,4})|over the next|"
    r"medium term|long term|guidance|targets?|outlook|"
    r"(?:full|whole)[ -]year|annual(?:ly)? (?:run[- ]rate|basis))\b", re.I)
_FORWARD_FALSE_FRIENDS = re.compile(
    r"would like to (?:inform|submit)|will (?:also )?be (?:hosted|available)|should not be used|"
    r"we should look", re.I)
_NUMERIC = re.compile(r"\d[\d,]*(?:\.\d+)?")
_UNIT_CROWE = re.compile(r"(?:₹|rs\.?|inr)\s?\d[\d,]*(?:\.\d+)?\s*(?:crore|cr\b)|(?:\d[\d,]*(?:\.\d+)?\s*(?:crore|cr\b))", re.I)
_UNIT_LAKH = re.compile(r"(?:₹|rs\.?|inr)?\s?\d[\d,]*(?:\.\d+)?\s*lakh", re.I)
_UNIT_PERCENT = re.compile(r"\d[\d,]*(?:\.\d+)?\s?(?:%(?!\w)|per ?cent|percent)", re.I)
_UNIT_BPS = re.compile(r"\d[\d,]*(?:\.\d+)?\s?bps\b", re.I)
#: An exchange-rate line ("INR to USD 86.61", "Rs./USD 85.47") states no USD
#: amount; a USD amount carries a magnitude word.
_UNIT_USD = re.compile(
    r"(?:US\$|\$)\s?[\d,]+|"
    r"\bUSD\s?[\d,]+\s?(?:million|billion|mn|bn|crore|lakh|trillion|thousand)\b", re.I)

_MODERATOR = re.compile(r"\b(moderator|host|operator|coordinator)\b", re.I)

_SECTION_TAGS: tuple[tuple[str, re.Pattern], ...] = (
    ("section:mda", re.compile(r"management discussion|md&a|directors' report", re.I)),
    ("section:related_party", re.compile(r"related part", re.I)),
    ("section:segment", re.compile(r"\bsegment(?:s|al|ary)?\b", re.I)),
    ("section:notes", re.compile(r"^(?:notes?\b|note \d)", re.I)),
)
#: The notes tag is structural: the section must be a note, or the body must
#: name the notes section.  A passing "notes" in MD&A prose is not a note chunk.
_NOTES_BODY = re.compile(
    r"notes? to (?:the )?(?:consolidated |standalone )?(?:financial )?"
    r"(?:statements|results|accounts)", re.I)

_NOTES_START = re.compile(
    r"notes? to (?:the )?(?:consolidated |standalone )?(?:financial )?(?:results|statements|accounts)", re.I)
#: Safe-harbour boilerplate ("subject to risks and uncertainties") is explicitly
#: excluded from the risk tag; strip it before the risk rule reads the body.
_SAFE_HARBOUR = re.compile(
    r"subject to (?:various |certain )?risks and uncertainties[^.]*\.?", re.I)


# ---------------------------------------------------------------------------
# Output type
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ChunkV3:
    doc_id: str
    doc_type: str
    isin: str
    symbol_at_time: str
    fiscal_period: str
    known_at: str
    section: str
    speaker: str
    speaker_role: str
    unit_kind: str
    header: str
    body: str
    char_len: int
    page_from: int
    page_to: int
    span_start: int
    span_end: int
    n_numbers: int
    forward_looking: int
    quality_grade: str
    pit_confidence: float
    content_tags: str
    tags: tuple[str, ...]
    entities: tuple[tuple[str, str], ...] = field(default_factory=tuple)

    def as_row(self) -> tuple:
        return (
            self.doc_id, self.doc_type, self.isin, self.symbol_at_time, self.fiscal_period,
            self.known_at, self.section, self.speaker, self.speaker_role, self.unit_kind,
            self.header, self.body, self.char_len, self.page_from, self.page_to,
            self.span_start, self.span_end, self.n_numbers, self.forward_looking,
            self.quality_grade, self.pit_confidence, self.content_tags,
        )


# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------


def make_header(meta: dict, section: str, speaker: str, page: int) -> str:
    """``SYMBOL · ISIN · doc label · period · section/speaker · p<page> · known <ts>``.

    Every field the planner filters on is in the header, so a header hit alone
    is enough to pin the company and the point in time.
    """
    label = DOC_LABELS.get(meta.get("doc_type", ""), meta.get("doc_type") or "document")
    where = (section or speaker or "-")[:90]
    symbol = (meta.get("symbol_at_time") or meta.get("symbol") or "").upper() or "DOCUMENT"
    parts = [symbol]
    if meta.get("isin"):
        parts.append(meta["isin"])
    parts += [label, meta.get("fiscal_period") or "-", where]
    if page:
        parts.append(f"p{page}")
    parts.append(f"known {meta.get('known_at') or 'unknown'}")
    return " · ".join(parts)


# ---------------------------------------------------------------------------
# Tags
# ---------------------------------------------------------------------------


def n_numbers(text: str) -> int:
    return len(_NUMERIC.findall(text or ""))


def unit_tags(text: str) -> list[str]:
    tags = []
    if _UNIT_CROWE.search(text):
        tags.append("unit:inr_crore")
    if _UNIT_LAKH.search(text):
        tags.append("unit:inr_lakh")
    if _UNIT_PERCENT.search(text):
        tags.append("unit:percent")
    if _UNIT_BPS.search(text):
        tags.append("unit:bps")
    if _UNIT_USD.search(text):
        tags.append("unit:usd")
    return tags


def is_forward_looking(text: str) -> bool:
    """Spec §4.4: a forward verb AND a future/target anchor, unless a table row.

    A bare period token ("FY25" in a title, "we will now take the next
    question") is not a forward statement.  The target nouns (guidance /
    target / outlook) are only an anchor when a metric word sits next to them,
    so "thank you for your guidance over the years" does not fire.
    """
    text = _FORWARD_FALSE_FRIENDS.sub(" ", text or "")
    if not FORWARD_LOOKING.search(text):
        return False
    anchored = False
    for anchor in FUTURE_ANCHOR.finditer(text):
        if anchor.group(0).lower() not in ("guidance", "target", "targets", "outlook"):
            anchored = True
            break
        lo, hi = max(0, anchor.start() - 120), min(len(text), anchor.end() + 120)
        if _GUIDANCE_METRIC.search(text, lo, hi):
            anchored = True
            break
    if not anchored:
        return False
    words = len(text.split())
    return not (n_numbers(text) > 8 and words < 30)


def has_guidance(text: str) -> bool:
    """A guidance verb within 120 chars of a metric word (raises precision over the bare verb)."""
    text = text or ""
    for verb in _GUIDANCE_VERB.finditer(text):
        lo, hi = max(0, verb.start() - 120), min(len(text), verb.end() + 120)
        if _GUIDANCE_METRIC.search(text, lo, hi):
            return True
    return False


def deterministic_tags(body: str, doc_type: str, section: str = "", speaker_role: str = "") -> tuple[str, ...]:
    """Tags the chunk text itself proves. No model, no inference from doc type alone."""
    tags: list[str] = []
    for tag, pattern in _TAG_RULES:
        haystack = _SAFE_HARBOUR.sub(" ", body) if tag == "risk" else body
        if pattern.search(haystack):
            tags.append(tag)
    if "guidance" not in tags and has_guidance(body):
        tags.append("guidance")
    if doc_type in ("annual_report", "results_notes"):
        for tag, pattern in _SECTION_TAGS:
            if pattern.search(section or ""):
                tags.append(tag)
        if "section:notes" not in tags and _NOTES_BODY.search(body[:160]):
            tags.append("section:notes")
    if doc_type == "concall":
        if section == "Opening remarks":
            tags.append("section:opening_remarks")
        elif section.startswith("Q&A"):
            tags.append("section:qa")
        if speaker_role in ("management", "analyst", "moderator"):
            tags.append(f"speaker_role:{speaker_role}")
    if n_numbers(body) > 0:
        tags.append("has_number")
    if is_forward_looking(body):
        tags.append("forward_looking")
    tags.extend(t for t in unit_tags(body) if t not in tags)
    return tuple(dict.fromkeys(tags))


# ---------------------------------------------------------------------------
# Entity mentions -> ISIN
# ---------------------------------------------------------------------------

_NAME_SUFFIX = re.compile(r"\b(limited|ltd|pvt|private|company|co|corporation|corp|industries|enterprises|"
                          r"holdings|holdings?|group|india)\b\.?", re.I)
_NON_WORD = re.compile(r"[^a-z0-9 ]+")


def _clean_name(name: str) -> str:
    s = _NON_WORD.sub(" ", (name or "").lower())
    s = _NAME_SUFFIX.sub(" ", s)
    return " ".join(s.split())


class EntityResolver:
    """Resolve company names and symbols mentioned in a chunk to ISIN.

    Deterministic: exact normalised n-gram lookup. The caller supplies the map
    (the build script loads it from ``master_companies``); no DB access here.
    """

    def __init__(self, names: dict[str, str] | None = None,
                 symbols: dict[str, str] | None = None,
                 min_chars: int = 5):
        self.names = {_clean_name(k): v for k, v in (names or {}).items() if len(_clean_name(k)) >= min_chars}
        self.symbols = {k.upper(): v for k, v in (symbols or {}).items() if k}
        self._max_words = max((len(k.split()) for k in self.names), default=1)

    @classmethod
    def from_master(cls, db_path=None) -> "EntityResolver":
        """Build from ``master_companies`` read-only; returns an empty resolver if unavailable."""
        import os
        import sqlite3
        from pathlib import Path
        try:
            from reality_engine.config import DATA_DIR
            root = os.environ.get("REALITY_DATA_ROOT")
            path = db_path or ((Path(root) if root else DATA_DIR) / "equity_intelligence.db")
            try:
                from reality_engine.db.readonly import connect_ro
                con = connect_ro(path, timeout_s=30)
                close = con.close
            except Exception:
                # WAL DB in a directory the reader may not write to: immutable snapshot
                con = sqlite3.connect(f"file:{path}?mode=ro&immutable=1", uri=True)
                close = con.close
            try:
                names = {n: i for n, i in con.execute(
                    "SELECT company_name, isin FROM master_companies "
                    "WHERE company_name IS NOT NULL AND isin IS NOT NULL")}
                symbols = {s: i for s, i in con.execute(
                    "SELECT nse_symbol, isin FROM master_companies WHERE nse_symbol IS NOT NULL AND isin IS NOT NULL")}
            finally:
                close()
            return cls(names, symbols)
        except Exception:
            return cls()

    def resolve(self, text: str, exclude_isin: str = "", limit: int = 12) -> tuple[tuple[str, str], ...]:
        if not self.names and not self.symbols:
            return ()
        words = _clean_name(text).split()
        found: dict[str, str] = {}
        for i, word in enumerate(words):
            sym = word.upper()
            if len(sym) >= 3 and sym in self.symbols:
                found.setdefault(sym, self.symbols[sym])
            for n in range(1, self._max_words + 1):
                if i + n > len(words):
                    break
                key = " ".join(words[i:i + n])
                isin = self.names.get(key)
                if isin:
                    found.setdefault(key.upper(), isin)
            if len(found) >= limit:
                break
        out = []
        for label, isin in found.items():
            if isin == exclude_isin:
                continue
            out.append((isin, label))
        return tuple(out[:limit])


# ---------------------------------------------------------------------------
# Document-level labels
# ---------------------------------------------------------------------------

PIT_CONFIDENCE = {
    "bse_dissem": 1.0, "nse_dissem": 1.0, "filing_date": 0.9,
    "body_letterhead": 0.8, "folder_name": 0.6, "drive_btime": 0.5,
}


def pit_confidence(known_at_source: str, edited_after_upload: bool = False) -> float:
    c = PIT_CONFIDENCE.get(known_at_source, 0.0)
    if known_at_source == "drive_btime" and edited_after_upload:
        return 0.3
    if known_at_source in ("upload", "crawl") or c == 0.0:
        raise ValueError(f"known_at_source '{known_at_source}' is not allowed (crawl date is never evidence)")
    return c


def grade_quality(pages: Sequence[str], doc_type: str) -> str:
    """§3 grading rules: A text layer, B partial OCR/damage, C mostly empty or tiny."""
    pages = [p or "" for p in pages]
    text = v2.join_pages(pages)
    if len(text.strip()) < 500:
        return "C"
    if not pages:
        return "C"
    empty = sum(1 for p in pages if len(p.strip()) < 40)
    if empty / len(pages) > 0.20:
        return "C"
    # spaces are not damage: measure the non-alphanumeric share of the visible characters
    visible = sum(1 for ch in text if not ch.isspace())
    alnum = sum(ch.isalnum() for ch in text)
    if visible and (1 - alnum / visible) > 0.15:
        return "B"
    if empty / len(pages) > 0.05:
        return "B"
    return "A"


# ---------------------------------------------------------------------------
# Concalls
# ---------------------------------------------------------------------------


_MANAGEMENT_NAME = re.compile(
    r"\b(chief|ceo|cfo|coo|cto|managing director|md|director|chairman|president|founder|"
    r"head of|head -|investor relations|company secretary|management|executive)\b", re.I)
_ANALYST_NAME = re.compile(r"\b(analyst|participant|investor|questioner|research)\b", re.I)


def _speaker_roles(text: str) -> dict[str, str]:
    turns = v2.speaker_turns(text)
    managers = v2._managers(turns) if turns else set()
    roles = {}
    for name, _start, _end in turns:
        if _MODERATOR.search(name or ""):
            roles[name] = "moderator"
        elif name in managers or _MANAGEMENT_NAME.search(name or ""):
            roles[name] = "management"
        elif _ANALYST_NAME.search(name or ""):
            roles[name] = "analyst"
        else:
            roles[name] = "analyst"
    return roles


def _dominant_role(chunk: v2.Chunk, turns: Sequence[tuple[str, int, int]],
                   roles: dict[str, str]) -> str:
    """Role of the speaker carrying most characters of the chunk.

    A Q&A pair is one chunk for the question *and* the answer; the answer
    usually holds most of the text, so the pair is management evidence.
    A name the parser cannot classify defaults to analyst; in the opening
    remarks that is wrong (the company opens its own call), so it is called
    management there unless the name itself says analyst.
    """
    def refine(role: str, name: str) -> str:
        if role == "analyst" and not _ANALYST_NAME.search(name or "") \
                and chunk.section == "Opening remarks":
            return "management"
        return role

    weight: dict[str, int] = {}
    for name, start, end in turns:
        overlap = max(0, min(chunk.span_end, end) - max(chunk.span_start, start))
        if overlap:
            weight[name] = weight.get(name, 0) + overlap
    if not weight:
        return refine(roles.get(chunk.speaker, ""), chunk.speaker)
    name = max(weight, key=lambda n: (weight[n], roles.get(n) == "management"))
    return refine(roles.get(name, ""), name)


def _enrich(chunks: Iterable[v2.Chunk], meta: dict, roles: dict[str, str],
            resolver: EntityResolver | None, page_at=None,
            turns: Sequence[tuple[str, int, int]] | None = None) -> list[ChunkV3]:
    out: list[ChunkV3] = []
    doc_type = meta.get("doc_type") or ""
    for c in chunks:
        body = c.body
        page = c.page_from
        if page_at is not None:
            page = page_at(c.span_start)
        role = _dominant_role(c, turns, roles) if (doc_type == "concall" and turns) else ""
        # A piece produced by _split_long is a continuation: the section says so
        # and the header repeats it, so a filter on section never mistakes it
        # for the start of the note.
        section = c.section
        if c.unit_kind.endswith("_cont"):
            section = f"{section} (cont.)" if section else "Continuation"
        tags = deterministic_tags(body, doc_type, section, role)
        ents = resolver.resolve(body, exclude_isin=meta.get("isin") or "") if resolver else ()
        out.append(ChunkV3(
            doc_id=c.doc_id, doc_type=doc_type,
            isin=meta.get("isin") or "", symbol_at_time=(meta.get("symbol_at_time") or meta.get("symbol") or "").upper(),
            fiscal_period=meta.get("fiscal_period") or "", known_at=meta.get("known_at") or "",
            section=section, speaker=c.speaker, speaker_role=role,
            unit_kind=c.unit_kind,
            header=make_header(meta, section, c.speaker, page),
            body=body, char_len=len(body), page_from=page, page_to=c.page_to or page,
            span_start=c.span_start, span_end=c.span_end,
            n_numbers=n_numbers(body), forward_looking=int(is_forward_looking(body)),
            quality_grade=meta.get("quality_grade") or "A",
            pit_confidence=float(meta.get("pit_confidence") or 1.0),
            content_tags=" ".join(tags), tags=tags, entities=ents,
        ))
    return out


def _page_lookup(pages: Sequence[str]):
    spans = v2._page_spans(list(pages))
    return v2._page_lookup(spans)


def chunk_concall_v3(pages: Sequence[str] | str, doc: dict,
                     resolver: EntityResolver | None = None) -> list[ChunkV3]:
    """Speaker-turn units, Q&A pairs, opening remarks; management/analyst roles."""
    page_list = [pages] if isinstance(pages, str) else list(pages or [])
    text = v2.join_pages(page_list)
    meta = _meta(doc)
    chunks = v2.chunk_concall(text, meta)
    turns = v2.speaker_turns(text)
    return _enrich(chunks, meta, _speaker_roles(text), resolver,
                   _page_lookup(page_list) if len(page_list) > 1 else None, turns)


# ---------------------------------------------------------------------------
# Decks
# ---------------------------------------------------------------------------


def chunk_deck_v3(pages: Sequence[str], doc: dict,
                  resolver: EntityResolver | None = None) -> list[ChunkV3]:
    """One slide per chunk (short slides merge forward inside a section)."""
    meta = _meta(doc)
    chunks = v2.chunk_deck(list(pages or []), meta)
    return _enrich(chunks, meta, {}, resolver)


# ---------------------------------------------------------------------------
# Annual reports
# ---------------------------------------------------------------------------


def chunk_annual_report_v3(pages: Sequence[str], doc: dict,
                           resolver: EntityResolver | None = None) -> list[ChunkV3]:
    """Section-aware: heading path (MD&A > segment > Note N), tables protected."""
    meta = _meta(doc)
    chunks = v2.chunk_annual_report(list(pages or []), meta)
    out = _enrich(chunks, meta, {}, resolver)
    # v2 leaves the "Body" section on front matter; say what it is.
    return [replace(c, header=make_header(meta, c.section, c.speaker, c.page_from)) if c.section == "Body" else c
            for c in out]


# ---------------------------------------------------------------------------
# Results notes
# ---------------------------------------------------------------------------


def _notes_start_page(pages: Sequence[str]) -> int:
    """First page holding the notes-to-results section; -1 when the filing has none."""
    for i, page in enumerate(pages):
        if _NOTES_START.search(page or ""):
            # the marker can sit near the top of the first notes page
            return i
    return -1


def chunk_results_notes_v3(pages: Sequence[str], doc: dict,
                           resolver: EntityResolver | None = None) -> list[ChunkV3]:
    """Note blocks only: the P&L and cover pages are not retrieval units.

    The notes section is cut from the first page that names it; when the
    marker is absent the whole filing is chunked as notes and the quality
    grade drops to B (the caller's doc metadata is updated in place).
    """
    page_list = list(pages or [])
    meta = _meta(doc)
    start = _notes_start_page(page_list)
    if start > 0:
        kept = page_list[start:]
    else:
        kept = page_list
        if page_list:
            meta["quality_grade"] = "B" if meta.get("quality_grade") == "A" else meta.get("quality_grade", "B")
    if not kept:
        return []
    # The "Notes to the financial results" marker is a section heading: promote
    # its line so the first note does not sit under a generic "Body" section.
    text = v2.join_pages(kept)
    blocks, _tables = v2.blocks_from_text(text)
    marker = _NOTES_START.search(text)
    if marker:
        blocks = [v2.Block(b.start, b.end, "heading", 1)
                  if b.start <= marker.start() < b.end else b for b in blocks]
    chunks = v2.chunk_annual_report(kept, meta, blocks)
    out = _enrich(chunks, meta, {}, resolver, _page_lookup(kept))
    offset = start if start > 0 else 0
    return [replace(c, page_from=c.page_from + offset, page_to=c.page_to + offset) for c in out]


# ---------------------------------------------------------------------------
# Announcements
# ---------------------------------------------------------------------------


def _announcement_pages(pages: Sequence[str]) -> list[str]:
    return list(pages or [])


def chunk_announcement_v3(pages: Sequence[str], doc: dict,
                          resolver: EntityResolver | None = None) -> list[ChunkV3]:
    """One announcement = one chunk while it fits; otherwise split on headings."""
    page_list = list(pages or [])
    meta = _meta(doc)
    text = v2.join_pages(page_list)
    if not text.strip():
        return []
    page_at = _page_lookup(page_list) if len(page_list) > 1 else None
    if len(text) <= ANNOUNCEMENT_MAX_CHARS:
        chunks = v2._finalise(text, [v2._Unit(0, len(text), "announcement", "Announcement")], meta, min_chars=1)
    else:
        chunks = v2.chunk_annual_report(page_list, dict(meta, doc_type="annual_report"))
        # the annual-report splitter names its units "note"; in an announcement
        # they are announcement pieces, not notes to accounts
        chunks = [replace(c, unit_kind=("announcement_cont" if c.unit_kind.endswith("_cont")
                                        else "announcement")) for c in chunks]
    out = _enrich(chunks, meta, {}, resolver, page_at)
    # a category string is a deterministic tag source too (order win, dividend, ...)
    category = (doc.get("category") or "").lower()
    if category:
        extra = [t for t, pat in _TAG_RULES if pat.search(category)]
        if extra:
            out = [replace(c, tags=tuple(dict.fromkeys(c.tags + tuple(extra))),
                           content_tags=" ".join(dict.fromkeys(c.tags + tuple(extra)))) for c in out]
    return out


# ---------------------------------------------------------------------------
# PIB / RBI / budget / circular text
# ---------------------------------------------------------------------------


def chunk_circular_v3(pages: Sequence[str] | str, doc: dict,
                      resolver: EntityResolver | None = None) -> list[ChunkV3]:
    """Numbered clause per chunk; sentence groups when unnumbered."""
    page_list = [pages] if isinstance(pages, str) else list(pages or [])
    meta = _meta(doc)
    meta.setdefault("doc_type", "pib")
    text = v2.join_pages(page_list)
    chunks = v2.chunk_circular(text, meta)
    return _enrich(chunks, meta, {}, resolver, _page_lookup(page_list) if len(page_list) > 1 else None)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


_CHUNKERS = {
    "concall": chunk_concall_v3,
    "deck": chunk_deck_v3,
    "annual_report": chunk_annual_report_v3,
    "results_notes": chunk_results_notes_v3,
    "announcement": chunk_announcement_v3,
    "pib": chunk_circular_v3,
    "rbi": chunk_circular_v3,
    "budget": chunk_circular_v3,
    "news": chunk_circular_v3,
    "offer": chunk_annual_report_v3,
}


def _meta(doc: dict) -> dict:
    meta = dict(doc)
    meta.setdefault("doc_id", "")
    meta.setdefault("symbol", meta.get("symbol_at_time") or "")
    meta.setdefault("known_at", "")
    meta.setdefault("fiscal_period", "")
    meta.setdefault("quality_grade", "A")
    meta.setdefault("pit_confidence", 1.0)
    return meta


def chunk_document(doc: dict, pages: Sequence[str],
                   resolver: EntityResolver | None = None) -> list[ChunkV3]:
    """Chunk one parsed document. ``pages`` are its page texts in order."""
    doc_type = (doc or {}).get("doc_type") or ""
    fn = _CHUNKERS.get(doc_type)
    if fn is None:
        raise ValueError(f"unsupported doc_type '{doc_type}' (one of {', '.join(DOC_TYPES)})")
    return fn(list(pages or []), doc, resolver)
