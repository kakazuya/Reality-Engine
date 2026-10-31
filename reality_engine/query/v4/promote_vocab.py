"""v4 vocabulary promotion — measure the unlabelled surfaces, ask free Beam, propose.

The WP2b vocabulary leaves 58,692 surfaces at ``other:<raw>`` (433,207 occurrences,
23.86% of uses).  This driver does what ``build_vocab`` deliberately does not: it
ranks those surfaces by uses, documents and companies, measures the evidence for
each one, and asks the free ``beam-free`` model for a *suggestion* only.

Nothing here writes a label into the vocabulary.  Beam's answer is stored in a
separate workspace store (``.tmp/v4_label_promotion.db``) and written to

    tasks/arch_v4/label_promotion_review.md      one row per surface, for approval
    tasks/arch_v4/label_promotion_proposal.json  new labels / aliases / buckets

so Opus and Shivam decide.  Unlabelled surfaces stay searchable as ``other:<raw>``;
nothing is deleted.

    python -m reality_engine.query.v4.promote_vocab --report-only
    python -m reality_engine.query.v4.promote_vocab --run-beam
    python -m reality_engine.query.v4.promote_vocab --run-beam --limit-batches 2

Resumable: a suggestion is a row keyed by ``surface_id``; a re-run never asks the
same surface twice and never re-does a finished batch.  The session id is stable
(``go_session.session_id("v4_label_promotion", ...)``), every call is recorded at
$0 through ``cost_ledger.record_usage``, and a billing refusal stops the run.

Data limit (reported honestly in the review): this sandbox mounts only
``v4_vocab.db``, not the three extraction stores, so the occurrence-weighted
value/quote share cannot be measured from source rows.  The review therefore uses
the two verbatim excerpts already stored in ``beam_context`` as a sampled proxy and
labels the column as such.  With the extraction stores mounted, the same file can
be rebuilt against them once that measurement is added.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import sqlite3
import sys
import threading
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from reality_engine.query.v4 import build_vocab
from reality_engine.query.v4.map_vocab_beam import (
    MAX_LIMIT,
    MODEL,
    BillingError,
    Gate,
    GateGivenUp,
    _ask,
    call_beam,
    label_block,
    labels_of,
)

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
TASKS = ROOT / "tasks" / "arch_v4"
QUESTIONS = ROOT / "tasks" / "master_bank" / "MASTER_BANK.jsonl"
DEFAULT_DB = ROOT / "reality_engine" / "data" / "pilot" / "v4" / "v4_vocab.db"
WORK_DB = ROOT / ".tmp" / "v4_label_promotion.db"
REVIEW = TASKS / "label_promotion_review.md"
PROPOSAL = TASKS / "label_promotion_proposal.json"

TOP_N = 500
BATCH = 40
SESSION_JOB = "v4_label_promotion"
HEAD_PCT = 0.95
# Labels the deterministic fix is allowed to change on an already-labelled row.
# Everything else is a weight-driven relabel and is not part of this fix.
TARGET_FIX = frozenset({"roe", "roce", "roa", "ronw", "financials"})

# `bucket` is never a label.  The closed set keeps the proposal reviewable and
# stops Beam from inventing a taxonomy of one surface each.  `signal`,
# `market_data` and `ratio` are the extractor buckets inherited from the source
# stores; the rest are the document shape the WP2b review already named.
BUCKETS = {
    "signal": "extractor bucket from the annual-report reader",
    "market_data": "extractor bucket from the annual-report reader",
    "ratio": "extractor bucket from the annual-report reader",
    "section": "document section heading (BRSR/ESG/Company Profile/...)",
    "deck_line": "presentation row or line label (Area Booked, Aerial View, ...)",
    "table_header": "table or column header",
    "entity": "company, brand or product name on its own",
    "unit": "bare unit, number or period",
}

# Terms the master bank asks about even when the surface is rare.  These stay in
# the vocabulary regardless of frequency (brief item 5); the list is the explicit
# safety net, the general rule is the question match below.
ASKED_LIST = {
    "tailwind", "headwind", "monsoon", "rain", "rainfall", "repo", "gst", "tariff",
    "duty", "pli", "rbi", "budget", "subsidy", "inflation", "commodity", "crude",
    "currency", "forex", "hedging", "freight", "esop", "buyback", "minimum wage",
}

# Acronyms that a question spells out.  "ROCE" is named by MB0488/MB0569 as
# "return on capital"; a token match alone would miss it.
EXPANSIONS = {
    "roe": ("return", "equity"),
    "roce": ("return", "capital"),
    "roa": ("return", "asset"),
    "ronw": ("return", "worth"),
    "pat": ("profit", "after", "tax"),
    "pbt": ("profit", "before", "tax"),
    "eps": ("earnings", "share"),
    "ebitda": ("operating", "profit"),
    "fcf": ("free", "cash", "flow"),
    "cfo": ("cash", "flow", "operation"),
}

GENERIC_ALONE = {
    "total", "others", "other", "net", "gross", "area", "value", "change",
    "increase", "decrease", "misc", "miscellaneous", "na", "nil", "balance",
    "data", "period", "year", "quarter", "rate", "share", "unit",
}
BUCKET_WORDS = {
    "signal", "ratio", "market_data", "operations", "operational", "environment",
    "environmental", "safety", "training", "water", "energy", "waste",
    "compliance", "sustainability", "governance", "csr", "credit_rating",
    "hedging", "derivatives", "fair_value", "aum", "property_plant_equipment",
    "share_capital", "section", "header", "table",
}

VALUE_RE = re.compile(r"\d")
UNIT_RE = re.compile(
    r"%|per\s*cent|percent|crore|cr\b|lakh|million|billion|\bbn\b|tonne|\bmt\b|"
    r"\bmw\b|\bgw\b|\brs\b|inr|₹|bps|mn\b", re.I)
_TOKEN_RE = re.compile(r"[a-z][a-z0-9]*")
_PAIR_RE = re.compile(r'"(\d{1,4})"\s*:\s*"([^"\\]{0,240})"')
_DEF_SPLIT = re.compile(r"\s+[—–|]\s+|\s+-\s+")
_SLUG_RE = re.compile(r"[a-z][a-z0-9_]{1,40}")

SYSTEM = """You review unmapped metric phrases from Indian listed-company documents \
(annual reports, earnings-call transcripts, investor presentations).  The phrases come \
from three extractors and are often not metrics at all.

The closed label list already declared (use an id from this list for alias_of):
{labels}

For every phrase choose exactly ONE outcome:
- new_label:<snake_case> — the phrase names a topic that the closed list does not cover. \
Append a definition after " — ", at most 12 words. Example: \
"new_label:order_backlog — confirmed orders not yet executed".
- alias_of:<existing_label> — the phrase means the same thing as one of the closed labels.
- bucket:<bucket> — the phrase is an extractor bucket, a document section heading, a \
presentation row label, a table header, an entity name on its own, or a bare unit. \
Allowed buckets: {buckets}. A bucket is NEVER a label: its items keep their own text.
- meaningless — the phrase means nothing on its own (Total, 17, Others, a bare number).

Rules:
- Never invent a label for a bucket, a section heading, a table header, an entity name on \
its own, or a bare number. A wrong label is worse than bucket/meaningless.
- Prefer alias_of when an existing label already covers the phrase; use new_label only \
when no existing label does.
- Use ONE new_label slug for grammatical variants and near-synonyms of the same concept \
(environment/environmental -> environment; capital_commitment/capital_commitments -> \
capital_commitment). Do not create a second slug for a plural, a hyphenation or a spelling \
variant.
- Contexts are verbatim excerpts around the phrase; they show what the phrase is attached \
to, not what the phrase means. Do not label the context.
- Company, brand and period words do not change the topic. Spelling variants are the same \
phrase.
- Answer every phrase number exactly once.

Reply with JSON only, one entry per number, no prose:
{{"<n>": "<decision>", ...}}"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return str(path)


def pct(num: float, den: float) -> float:
    return 100.0 * num / den if den else 0.0


# --- opening the vocabulary store -------------------------------------------
def open_vocab(path: Path, work: Path) -> tuple[sqlite3.Connection, str]:
    """Open the installed vocabulary read-only.

    On this Windows sandbox the read-only mount cannot be opened in place (SQLite
    needs a lock file next to a mounted read-only file); a byte copy in the
    workspace is used instead and the source is never written.  The returned note
    says which path was read, for the review.
    """
    try:
        con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        con.execute("SELECT count(*) FROM surface").fetchone()
        return con, f"{_rel(path)} (mode=ro)"
    except sqlite3.OperationalError:
        work.parent.mkdir(parents=True, exist_ok=True)
        copy = work.parent / "v4_vocab_source_copy.db"
        if not copy.exists() or copy.stat().st_size != path.stat().st_size:
            shutil.copyfile(path, copy)
        con = sqlite3.connect(copy)
        con.row_factory = sqlite3.Row
        return con, f"{_rel(copy)} (byte copy of {_rel(path)}; the mount is read-only)"


# --- questions ----------------------------------------------------------------
def stem(token: str) -> str:
    """A small deterministic stem, enough for bank token/stem matching."""
    t = build_vocab.singular(token.lower())
    for suffix in ("ations", "ation", "ments", "ment", "ings", "ing", "ies", "ied",
                   "ed", "es", "ly", "ity", "ive"):
        if len(t) > len(suffix) + 3 and t.endswith(suffix):
            t = t[:-len(suffix)]
            break
    return build_vocab.singular(t)


def _norm_tokens(text: str) -> list[str]:
    s = " " + str(text).lower() + " "
    s = (s.replace("&", " and ").replace("%", " pct ").replace("/", " ")
          .replace("_", " ").replace("-", " "))
    return _TOKEN_RE.findall(s)


def load_questions(path: Path = QUESTIONS) -> list[dict]:
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            q = json.loads(line)
            toks = _norm_tokens(q.get("question") or "")
            q["_tokens"] = toks
            q["_stems"] = [stem(t) for t in toks]
            q["_norm"] = " ".join(toks)
            out.append(q)
    return out


def _question_index(questions: list[dict]) -> dict:
    idx = {"token": defaultdict(set), "stem": defaultdict(set), "norm": []}
    for i, q in enumerate(questions):
        idx["norm"].append((i, q["_norm"]))
        for t in set(q["_tokens"]):
            idx["token"][t].add(i)
        for t in set(q["_stems"]):
            idx["stem"][t].add(i)
    return idx


def bank_evidence(phrase: str, questions: list[dict], index: dict) -> dict:
    """Whether the master bank names this surface: exact, token, stem and list."""
    toks = [t for t in _norm_tokens(phrase) if t not in build_vocab.STOP]
    content = [t for t in toks if t not in build_vocab.NON_TOPIC] or toks
    stems = [stem(t) for t in content]
    phrase_norm = " ".join(toks)
    hits: set[int] = set()
    exact = False
    token = False
    stemmed = False
    if len(phrase_norm) >= 3:
        for i, norm in index["norm"]:
            if phrase_norm in f" {norm} ":
                exact = True
                hits.add(i)
    if content:
        sets = [index["token"].get(t, set()) for t in set(content)]
        if sets and all(sets):
            common = set.intersection(*sets)
            if common:
                token = True
                hits |= common
        ssets = [index["stem"].get(s, set()) for s in set(stems)]
        if ssets and all(ssets):
            common = set.intersection(*ssets)
            if common:
                stemmed = True
                hits |= common
    # acronym expansion: "ROCE" is "return on capital" in the question text
    for t in content:
        exp = EXPANSIONS.get(t)
        if not exp:
            continue
        esets = [index["stem"].get(stem(x), set()) for x in exp]
        if esets and all(esets):
            common = set.intersection(*esets)
            if common:
                stemmed = True
                hits |= common
    listed = bool(set(build_vocab.words_of(phrase)) & ASKED_LIST)
    if listed:
        for i, q in enumerate(questions):
            if set(q["_tokens"]) & ASKED_LIST:
                hits.add(i)
                break
    example = None
    if hits:
        i = sorted(hits)[0]
        q = questions[i]
        example = {"mid": q.get("mid"), "question": (q.get("question") or "")[:180]}
    # "Named by a question" must mean the phrase is the thing asked for, not a
    # word that happens to occur in a question.  A single generic token
    # (`operations`, `environment`) is not named just because 40 questions use the
    # word; a rare listed term or a spelled-out acronym is.
    single = len(content) == 1
    strong_single = single and (content[0] in ASKED_LIST or content[0] in EXPANSIONS)
    strict = (len(content) >= 2) or strong_single
    named = bool(hits) and strict and (exact or token or stemmed or listed)
    return {
        "q_exact": exact,
        "q_token": token,
        "q_stem": stemmed,
        "q_list": listed,
        "q_n": len(hits),
        "q_example": example,
        "q_named": named,
    }


# --- evidence -----------------------------------------------------------------
def value_evidence(ctx1: str | None, ctx2: str | None) -> dict:
    """Sampled value/quote evidence from the two stored beam contexts.

    The occurrence-weighted share needs the extraction stores; this is the
    two-excerpt sample the installed store already holds, reported as such.
    """
    ctx = [c for c in (ctx1, ctx2) if c]
    n_val = sum(1 for c in ctx if VALUE_RE.search(c))
    n_unit = sum(1 for c in ctx if UNIT_RE.search(c))
    n_quote = sum(1 for c in ctx if len(c.split()) >= 3)
    return {
        "ctx1": ctx1, "ctx2": ctx2, "ctx_n": len(ctx),
        "value_n": n_val, "unit_n": n_unit, "quote_n": n_quote,
        "value_share": (n_val / len(ctx)) if ctx else None,
    }


def alone_evidence(phrase: str, words: frozenset[str]) -> dict:
    """Does the surface mean anything on its own?  Evidence, never the decision."""
    raw = str(phrase).strip()
    if not re.search(r"[a-zA-Z]", raw):
        return {"alone": False, "alone_reason": "no letters (number/unit)"}
    if not words:
        return {"alone": False, "alone_reason": "only stop/non-topic words"}
    if words <= build_vocab.NON_TOPIC:
        return {"alone": False, "alone_reason": "only non-topic words"}
    if len(words) == 1:
        w = next(iter(words))
        if w in GENERIC_ALONE:
            return {"alone": False, "alone_reason": "generic word"}
        if w in BUCKET_WORDS:
            return {"alone": False, "alone_reason": "bucket word"}
        if len(w) <= 2 and not re.search(r"\d", raw):
            return {"alone": False, "alone_reason": "two-letter fragment"}
    # A single capitalised word that is not a declared label is often a company,
    # brand or product name; flag it as uncertain rather than call it meaningful.
    if len(words) == 1 and raw[:1].isupper() and raw[1:].islower() and len(raw) > 5:
        return {"alone": True, "alone_reason": "possible entity name on its own"}
    return {"alone": True, "alone_reason": ""}


def score_of(n: int, docs: int, isins: int) -> float:
    """Uses weighted by document and company spread (all three named in the brief)."""
    return n * (1.0 + math.log1p(max(docs, 0))) * (1.0 + math.log1p(max(isins, 0)))


# --- surfaces and remap -------------------------------------------------------
def load_rows(con: sqlite3.Connection) -> list[dict]:
    cols = {r[1] for r in con.execute("PRAGMA table_info(map)")}
    source = "m.source" if "source" in cols else "'deterministic'"
    rows = [dict(r) for r in con.execute(
        "SELECT s.surface_id, s.surface_verbatim, s.n_occurrences, s.n_docs, s.n_isins, "
        f"s.source_kind, s.first_known_at, m.label_id, m.map_value, m.method, {source} "
        "FROM surface s JOIN map m USING(surface_id) ORDER BY s.surface_id")]
    for r in rows:
        r["surface"] = r["surface_verbatim"]
    return rows


def remap(rows: list[dict]) -> dict:
    """Apply the current deterministic layer to the stored surfaces.

    Entity tokens are not available without the extraction/company master stores;
    they never contribute a label (the build removes them from that role), so the
    stored surface alone is enough to re-decide the declared layer.  Weights are
    recomputed from the surfaces, exactly as ``build_vocab.build`` does.
    """
    weight: Counter = Counter()
    words_of = {}
    for r in rows:
        w = build_vocab.words_of(r["surface_verbatim"])
        words_of[r["surface_id"]] = w
        for t in w:
            weight[t] += r["n_occurrences"]
    wd = {k: float(v) for k, v in weight.items()}
    changed, retained, from_other = [], [], []
    for r in rows:
        lab, method = build_vocab.label_for(words_of[r["surface_id"]], wd)
        r["words"] = words_of[r["surface_id"]]
        base = r["label_id"]
        if base is None:
            # A previously unmapped surface: the fix can now name it.
            r["fixed_label"] = lab
            r["fixed_method"] = method
            if lab != "other":
                from_other.append(r)
        elif r.get("source") == "beam":
            # Beam labels are already declared labels.  A rebuild re-runs the
            # deterministic layer first and then Beam; dropping them here would
            # understate the installed coverage, not measure the fix.
            r["fixed_label"] = base
            r["fixed_method"] = r.get("method") or "beam"
        elif lab != "other":
            # The code fix is targeted at the ratio topics and the statement
            # spellings.  A weight-driven change to some other label is not part
            # of this fix and is left for the human review rather than silently
            # relabelled.
            if lab in TARGET_FIX and lab != base:
                r["fixed_label"] = lab
                r["fixed_method"] = method
                changed.append(r)
            else:
                r["fixed_label"] = base
                r["fixed_method"] = r.get("method") or "token"
                retained.append(r)
        else:
            # Remap cannot see entity tokens; a rule change that would drop a
            # label it previously assigned is a retention, not evidence of a loss.
            r["fixed_label"] = base
            r["fixed_method"] = r.get("method") or "token"
            retained.append(r)
    return {
        "words": words_of, "weight": wd,
        "changed": changed, "retained": retained,
        "fixed_labelled": sum(1 for r in rows if r["fixed_label"] != "other"),
        "fixed_uses": sum(r["n_occurrences"] for r in rows if r["fixed_label"] != "other"),
        "fixed_isin_pairs": sum(r["n_isins"] for r in rows if r["fixed_label"] != "other"),
        "fixed_from_other": from_other,
        "fixed_unlabelled": [],
    }


def head_ids(rows: list[dict], pct_: float = HEAD_PCT) -> set[int]:
    total = sum(r["n_occurrences"] for r in rows)
    cum = 0
    out: set[int] = set()
    for r in sorted(rows, key=lambda r: (-r["n_occurrences"], r["surface_id"])):
        out.add(r["surface_id"])
        cum += r["n_occurrences"]
        if cum >= pct_ * total:
            break
    return out


def coverage(rows: list[dict], labelled: set[int], head: set[int]) -> dict:
    total = sum(r["n_occurrences"] for r in rows)
    occ = sum(r["n_occurrences"] for r in rows if r["surface_id"] in labelled)
    isin_total = sum(r["n_isins"] for r in rows)
    isin = sum(r["n_isins"] for r in rows if r["surface_id"] in labelled)
    head_lab = len(head & labelled)
    return {
        "uses": occ, "uses_pct": pct(occ, total), "total_uses": total,
        "isin_pairs": isin, "isin_pairs_pct": pct(isin, isin_total),
        "isin_total": isin_total,
        "surfaces": len(labelled), "surfaces_pct": pct(len(labelled), len(rows)),
        "total_surfaces": len(rows),
        "head_labelled": head_lab, "head_total": len(head),
        "head_pct": pct(head_lab, len(head)),
    }


# --- selection ----------------------------------------------------------------
def select(rows: list[dict], limit: int = TOP_N) -> tuple[list[dict], list[dict]]:
    candidates = [r for r in rows if r["fixed_label"] == "other"]
    for r in candidates:
        r["score"] = score_of(r["n_occurrences"], r["n_docs"], r["n_isins"])
    ranked = sorted(candidates, key=lambda r: (-r["score"], -r["n_occurrences"],
                                               r["surface_id"]))
    top = ranked[:limit]
    picked = {r["surface_id"] for r in top}
    # Brief item 5: a surface a bank question names stays, whatever its frequency.
    extra = [r for r in ranked[limit:] if r.get("q_named") and r["surface_id"] not in picked]
    return top, extra


def add_evidence(rows: list[dict], questions: list[dict], index: dict,
                 contexts: dict[int, tuple]) -> None:
    for r in rows:
        ctx1, ctx2 = contexts.get(r["surface_id"], (None, None))
        r.update(value_evidence(ctx1, ctx2))
        r.update(bank_evidence(r["surface_verbatim"], questions, index))
        r.update(alone_evidence(r["surface_verbatim"], r["words"]))
        r["score"] = score_of(r["n_occurrences"], r["n_docs"], r["n_isins"])


# --- beam ---------------------------------------------------------------------
WORK_SCHEMA = """
CREATE TABLE IF NOT EXISTS candidate(
  surface_id INTEGER PRIMARY KEY, rank INTEGER NOT NULL, batch_id INTEGER NOT NULL,
  score REAL NOT NULL, evidence_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS suggestion(
  surface_id INTEGER PRIMARY KEY, batch_id INTEGER, decision TEXT, definition TEXT,
  raw TEXT, status TEXT NOT NULL, answered_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS batch(
  batch_id INTEGER PRIMARY KEY, n_surfaces INTEGER NOT NULL, status TEXT NOT NULL,
  n_ok INTEGER DEFAULT 0, n_retried INTEGER DEFAULT 0, in_tok INTEGER DEFAULT 0,
  out_tok INTEGER DEFAULT 0, secs REAL, started_at TEXT, finished_at TEXT, note TEXT);
CREATE TABLE IF NOT EXISTS run(
  run_at TEXT, batches INTEGER, surfaces INTEGER, elapsed_s REAL, n_429 INTEGER,
  best_limit INTEGER, final_limit INTEGER);
"""


def open_work(path: Path = WORK_DB) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=30000")
    con.executescript(WORK_SCHEMA)
    con.commit()
    return con


def store_candidates(con: sqlite3.Connection, selected: list[dict],
                     batch_size: int = BATCH) -> dict[int, int]:
    """Insert/refresh the deterministic candidate set; return surface -> batch."""
    con.execute("DELETE FROM candidate")
    plan = {}
    for i, r in enumerate(selected):
        bid = 1 + i // max(1, batch_size)
        plan[r["surface_id"]] = bid
        evidence = {k: r.get(k) for k in (
            "ctx1", "ctx2", "ctx_n", "value_n", "unit_n", "quote_n", "value_share",
            "q_exact", "q_token", "q_stem", "q_list", "q_n", "q_example", "q_named",
            "alone", "alone_reason", "source_kind", "n_occurrences", "n_docs",
            "n_isins", "surface")}
        con.execute("INSERT INTO candidate VALUES (?,?,?,?,?)",
                    (r["surface_id"], i + 1, bid, r["score"],
                     json.dumps(evidence, ensure_ascii=False)))
    con.commit()
    return plan


def load_suggestions(con: sqlite3.Connection) -> dict[int, dict]:
    return {r["surface_id"]: dict(r) for r in con.execute("SELECT * FROM suggestion")}


def split_decision(text: str) -> tuple[str, str]:
    raw = str(text or "").strip().strip("`.,;: ")
    raw = raw.replace(" — ", " — ").replace(" – ", " — ")
    parts = _DEF_SPLIT.split(raw, maxsplit=1)
    return parts[0].strip(), (parts[1].strip() if len(parts) > 1 else "")


def normalize_decision(text: str, allowed_labels: set[str],
                       allowed_buckets: set[str]) -> tuple[str, str] | None:
    """Return ``(decision, definition)`` or None when the answer is not declarable."""
    decision, definition = split_decision(text)
    low = decision.strip().lower().rstrip(".,;:")
    definition = definition.strip()[:240]
    if low in ("meaningless", "meaningless."):
        return "meaningless", definition
    m = re.match(r"new[\s_]*label\s*:\s*([a-z][a-z0-9_]{1,40})$", low)
    if m:
        slug = m.group(1)
        if slug in allowed_labels:
            return f"alias_of:{slug}", definition
        return f"new_label:{slug}", definition
    m = re.match(r"alias[\s_]*of\s*:\s*([a-z0-9_]+)$", low)
    if m:
        lab = m.group(1)
        return (f"alias_of:{lab}", definition) if lab in allowed_labels else None
    m = re.match(r"bucket\s*:\s*([a-z0-9_]+)$", low)
    if m:
        b = m.group(1)
        return (f"bucket:{b}", definition) if b in allowed_buckets else None
    return None


def parse_answers(text: str | None, wanted: dict[int, None],
                  allowed_labels: set[str], allowed_buckets: set[str]
                  ) -> tuple[dict[int, tuple[str, str]], dict[int, str]]:
    accepted: dict[int, tuple[str, str]] = {}
    rejected: dict[int, str] = {}
    for key, value in _PAIR_RE.findall(text or ""):
        idx = int(key)
        if idx not in wanted or idx in accepted:
            continue
        got = normalize_decision(value, allowed_labels, allowed_buckets)
        if got:
            accepted[idx] = got
        else:
            rejected[idx] = value[:120]
    for idx in wanted:
        rejected.setdefault(idx, "")
    for idx in accepted:
        rejected.pop(idx, None)
    return accepted, rejected


def prompt_of(labels: dict[str, dict], items: list[tuple[int, dict]],
              allowed_buckets: set[str]) -> tuple[str, str]:
    lines = []
    for idx, r in items:
        ev = r
        line = (f'{idx}. "{r["surface"]}" [{ev.get("source_kind")}, '
                f'{ev.get("n_isins")} companies, {ev.get("n_occurrences")} uses]')
        ctx = [c for c in (ev.get("ctx1"), ev.get("ctx2")) if c]
        if ctx:
            line += " contexts: " + " || ".join(ctx)
        bits = []
        if ev.get("ctx_n"):
            bits.append(f'value-bearing contexts {ev.get("value_n")}/{ev.get("ctx_n")}')
        if ev.get("q_n"):
            bits.append(f'bank questions {ev.get("q_n")}')
        if bits:
            line += " (" + "; ".join(bits) + ")"
        lines.append(line)
    user = ("Decide every phrase below with exactly one outcome and a JSON value.\n\n"
            + "\n".join(lines) + "\n\nJSON only, one entry per phrase number.")
    buckets = ", ".join(sorted(allowed_buckets))
    system = SYSTEM.format(labels=label_block(labels), buckets=buckets)
    return system, user


def answer_batch(labels, allowed_labels, allowed_buckets, items, poster, key, gate) -> dict:
    system, user = prompt_of(labels, items, allowed_buckets)
    wanted = {i: None for i, _ in items}
    started, t0 = _now(), time.time()
    rep = _ask(poster, system, user, key, gate)
    in_tok, out_tok = rep["in_tok"], rep["out_tok"]
    accepted, rejected = parse_answers(rep["content"], wanted, allowed_labels, allowed_buckets)
    first = dict(accepted)
    if rejected:
        origin = [i for i, _ in items if i in rejected]
        again = list(enumerate(r for i, r in items if i in rejected))
        s2, u2 = prompt_of(labels, again, allowed_buckets)
        u2 += ("\n\nYour previous answer did not cover these, or was not one of the "
               "declared decisions. Answer only with new_label:<slug>, alias_of:<label>, "
               "bucket:<bucket> or meaningless.")
        rep2 = _ask(poster, s2, u2, key, gate)
        in_tok += rep2["in_tok"]
        out_tok += rep2["out_tok"]
        more, _ = parse_answers(rep2["content"], {j: None for j in range(len(origin))},
                                allowed_labels, allowed_buckets)
        for j, val in more.items():
            accepted.setdefault(origin[j], val)
    rows = []
    for idx, r in items:
        got = accepted.get(idx)
        rows.append({"surface_id": r["surface_id"],
                     "decision": got[0] if got else "",
                     "definition": got[1] if got else "",
                     "raw": rejected.get(idx, "") if got is None else (got[0] + " | " + got[1]),
                     "status": "answered" if got else "unanswered",
                     "first_pass": 1 if idx in first else 0})
    return {"rows": rows, "secs": round(time.time() - t0, 2), "in_tok": in_tok,
            "out_tok": out_tok, "started_at": started, "finish": rep["finish"],
            "n_ok": len(accepted), "n_retried": len(rejected)}


def run_beam(con: sqlite3.Connection, labels, plan: dict[int, int], selected: list[dict],
             suggestions: dict[int, dict], key: str, *, start: int = 4,
             ceiling: int = MAX_LIMIT, limit_batches: int = 0,
             poster=call_beam) -> dict:
    allowed_labels = set(labels)
    allowed_buckets = set(BUCKETS)
    by_batch: dict[int, list[dict]] = defaultdict(list)
    for r in selected:
        by_batch[plan[r["surface_id"]]].append(r)
    todo = []
    for bid in sorted(by_batch):
        items = [r for r in by_batch[bid] if r["surface_id"] not in suggestions]
        if items:
            todo.append((bid, items))
    if limit_batches:
        todo = todo[:limit_batches]
    gate = Gate(start, ceiling)
    lock = threading.Lock()
    t0 = time.time()
    result: dict = {"batches": len(todo), "surfaces": 0, "skipped": len(selected) - sum(
        len(i) for _, i in todo)}

    def one(bid, items):
        try:
            out = answer_batch(labels, allowed_labels, allowed_buckets,
                               list(enumerate(items)), poster, key, gate)
        except BillingError:
            raise
        except (GateGivenUp, RuntimeError) as exc:
            with lock:
                con.execute("INSERT OR REPLACE INTO batch VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                            (bid, len(items), "pending", 0, 0, 0, 0, None,
                             _now(), _now(), repr(exc)[:160]))
                con.commit()
            return 0
        with lock:
            con.executemany(
                "INSERT OR REPLACE INTO suggestion VALUES (?,?,?,?,?,?,?)",
                [(r["surface_id"], bid, r["decision"], r["definition"], r["raw"],
                  r["status"], _now()) for r in out["rows"]])
            con.execute("INSERT OR REPLACE INTO batch VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        (bid, len(items), "done", out["n_ok"], out["n_retried"],
                         out["in_tok"], out["out_tok"], out["secs"],
                         out["started_at"], _now(), out["finish"]))
            con.commit()
        return len(items)

    executor = ThreadPoolExecutor(max_workers=max(1, ceiling))
    try:
        futures = [executor.submit(one, bid, items) for bid, items in todo]
        for fut in futures:
            result["surfaces"] += fut.result()
    finally:
        executor.shutdown(wait=True, cancel_futures=True)
    elapsed = max(time.time() - t0, 0.1)
    result.update({"elapsed_s": round(elapsed, 1), "best_limit": gate.best,
                   "final_limit": gate.limit, "n_429": gate.ratelimited,
                   "pending": con.execute("SELECT count(*) FROM batch WHERE status='pending'"
                                          ).fetchone()[0]})
    con.execute("INSERT INTO run VALUES (?,?,?,?,?,?,?)",
                (_now(), result["batches"], result["surfaces"], result["elapsed_s"],
                 result["n_429"], result["best_limit"], result["final_limit"]))
    con.commit()
    return result


# --- gate / report ------------------------------------------------------------
def proposal_labelled(selected: list[dict], suggestions: dict[int, dict],
                      allowed_labels: set[str]) -> tuple[set[int], dict]:
    ids: set[int] = set()
    new: dict[str, dict] = {}
    alias: dict[str, list[dict]] = defaultdict(list)
    bucket: dict[str, list[dict]] = defaultdict(list)
    meaningless: list[dict] = []
    unanswered: list[dict] = []
    for r in selected:
        s = suggestions.get(r["surface_id"])
        dec = (s or {}).get("decision") or ""
        if dec.startswith("new_label:"):
            ids.add(r["surface_id"])
            lab = dec.split(":", 1)[1]
            d = new.setdefault(lab, {"label_id": lab, "definition": "", "surfaces": [],
                                     "uses": 0, "isin_pairs": 0, "examples": []})
            if s and s.get("definition") and not d["definition"]:
                d["definition"] = s["definition"]
            d["surfaces"].append(r["surface_verbatim"])
            d["uses"] += r["n_occurrences"]
            d["isin_pairs"] += r["n_isins"]
            d["examples"].append({"surface": r["surface_verbatim"],
                                  "uses": r["n_occurrences"],
                                  "companies": r["n_isins"]})
        elif dec.startswith("alias_of:"):
            lab = dec.split(":", 1)[1]
            if lab in allowed_labels:
                ids.add(r["surface_id"])
                alias[lab].append(r)
        elif dec.startswith("bucket:"):
            bucket[dec.split(":", 1)[1]].append(r)
        elif dec == "meaningless":
            meaningless.append(r)
        else:
            unanswered.append(r)
    return ids, {"new": new, "alias": alias, "bucket": bucket,
                 "meaningless": meaningless, "unanswered": unanswered}


def dedupe_new_labels(new: dict) -> dict:
    """Mechanical near-duplicate clusters among Beam's new-label slugs.

    This is a reporting aid, not a merge: it groups singular/plural forms,
    token-subset slugs (`energy` / `energy_consumption`) and identical
    definitions.  Opus still decides the semantic merge.
    """
    labels = sorted(new)
    defs = {lab: re.sub(r"\W+", " ", (new[lab].get("definition") or "").lower()).strip()
            for lab in labels}
    parent = {lab: lab for lab in labels}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    for i, a in enumerate(labels):
        for b in labels[i + 1:]:
            # Conservative on purpose: singular/plural and identical definitions
            # only.  A token-subset rule would bridge `esg_energy` into both
            # `esg` and `energy` and report a merge that no reviewer asked for.
            if (build_vocab.singular(a) == build_vocab.singular(b)
                    or (defs[a] and defs[a] == defs[b])):
                union(a, b)
    clusters: dict[str, list[str]] = defaultdict(list)
    for lab in labels:
        clusters[find(lab)].append(lab)
    out = []
    for _root, members in clusters.items():
        if len(members) < 2:
            continue
        uses = sum(new[m]["uses"] for m in members)
        out.append({"representative": min(members, key=lambda m: (-new[m]["uses"], m)),
                    "members": sorted(members), "uses": uses})
    out.sort(key=lambda c: (-c["uses"], c["representative"]))
    merged = sum(len(c["members"]) - 1 for c in out)
    return {"raw": len(labels), "clusters": len(labels) - merged,
            "merged_away": merged, "groups": out[:40]}


def marginal(rows: list[dict], fixed_labelled: set[int],
             stops=(500, 1000, 2000, 5000, 10000, 20000)) -> list[dict]:
    total = sum(r["n_occurrences"] for r in rows)
    base = sum(r["n_occurrences"] for r in rows if r["surface_id"] in fixed_labelled)
    cand = sorted((r for r in rows if r["fixed_label"] == "other"),
                  key=lambda r: (-r["score"], -r["n_occurrences"], r["surface_id"]))
    out = []
    for stop in stops:
        add = sum(r["n_occurrences"] for r in cand[:stop])
        out.append({"n": min(stop, len(cand)), "uses_pct": pct(base + add, total),
                    "added_pct": pct(add, total)})
    return out


def _md(text: str, limit: int = 90) -> str:
    return (str(text or "").replace("|", "/").replace("\n", " ").strip())[:limit]


def _median(values: list[float]) -> float:
    vals = sorted(v for v in values if v is not None)
    if not vals:
        return 0.0
    mid = len(vals) // 2
    return vals[mid] if len(vals) % 2 else (vals[mid - 1] + vals[mid]) / 2.0


def _decision_cell(s: dict | None) -> str:
    if not s:
        return "unanswered"
    dec = s.get("decision") or ""
    if not dec:
        return "unanswered"
    if dec == "meaningless":
        return "meaningless"
    if dec.startswith("bucket:"):
        return "bucket:" + dec.split(":", 1)[1]
    if dec.startswith("alias_of:"):
        return "alias_of:" + dec.split(":", 1)[1]
    if dec.startswith("new_label:"):
        return "new_label:" + dec.split(":", 1)[1]
    return _md(dec, 40)


def write_reports(rows: list[dict], selected: list[dict], suggestions: dict[int, dict],
                  labels: dict[str, dict], cfg: dict, remap_info: dict,
                  gate: dict, extra: list[dict], source_note: str) -> dict:
    allowed_labels = set(labels)
    prop_ids, prop = proposal_labelled(selected, suggestions, allowed_labels)
    fixed = {r["surface_id"] for r in rows if r["fixed_label"] != "other"}
    after = fixed | prop_ids
    total = sum(r["n_occurrences"] for r in rows)
    # Gate states
    before_lab = {r["surface_id"] for r in rows if r["label_id"] is not None}
    before = coverage(rows, before_lab, gate["head"])
    fixed_cov = coverage(rows, fixed, gate["head"])
    after_cov = coverage(rows, after, gate["head"])
    # Use the gate difference, not the raw remap list: a baseline label can be
    # retained while a handful of rows change in the other direction, and the
    # table, the prose and the proposal must agree on one number.
    after_fix_uses = fixed_cov["uses"] - before["uses"]
    after_fix_isin = fixed_cov["isin_pairs"] - before["isin_pairs"]
    new_uses = sum(r["n_occurrences"] for r in selected if r["surface_id"] in prop_ids)
    new_isin = sum(r["n_isins"] for r in selected if r["surface_id"] in prop_ids)
    unlabelled_uses = total - after_cov["uses"]

    # Decision counts
    dec_counts = Counter()
    for r in selected:
        s = suggestions.get(r["surface_id"])
        d = (s or {}).get("decision") or ""
        if d == "meaningless":
            dec_counts["meaningless"] += 1
        elif d.startswith("new_label:"):
            dec_counts["new_label"] += 1
        elif d.startswith("alias_of:"):
            dec_counts["alias_of"] += 1
        elif d.startswith("bucket:"):
            dec_counts["bucket"] += 1
        else:
            dec_counts["unanswered"] += 1
    bucket_uses = sum(r["n_occurrences"] for v in prop["bucket"].values() for r in v)
    meaningless_uses = sum(r["n_occurrences"] for r in prop["meaningless"])
    top_bucket = sorted((r for v in prop["bucket"].values() for r in v),
                        key=lambda r: -r["n_occurrences"])[:5]
    top_bucket_text = ", ".join(f"`{_md(r['surface_verbatim'], 22)}` "
                                f"({r['n_occurrences']:,})" for r in top_bucket)
    new_label_count = len(prop["new"])
    dedupe = dedupe_new_labels(prop["new"])
    # A stricter reading that sends BRSR/ESG headings to `bucket:section` rather
    # than a new topic: this is the honest downside of the topic proposals.
    brsr_like = {"environment", "sustainability", "compliance", "safety", "training",
                 "water", "waste", "emissions", "ghg_emissions", "esg", "energy",
                 "energy_consumption", "human_rights", "human_rights_training"}
    brsr_uses = sum(d["uses"] for lab, d in prop["new"].items() if lab in brsr_like)

    # The next-500 curve is an upper bound: it assumes every surface is labelable.
    curve = marginal(rows, fixed)

    # ---- markdown ----
    L: list[str] = []
    L += [
        "# Label promotion review — measured frequency, free Beam suggestions",
        "",
        f"Generated {_now()} by `python -m reality_engine.query.v4.promote_vocab` from "
        f"`{source_note}`. Model `{MODEL}` (free) on OpenCode Go, "
        f"`reasoning_effort=low`. **This file is a proposal: no label was applied.**",
        "",
        "**Status:** for Opus and Shivam to approve. The mapper fix in "
        "`build_vocab.py` is code (ratio topics + spelling merge); the promotions "
        "below are not. Unlabelled surfaces stay searchable as `other:<raw>`; "
        "nothing was deleted.",
        "",
        "## 1. Executive summary",
        "",
        f"- The installed store labels **{before['uses_pct']:.2f}% of uses** "
        f"({before['uses']:,} / {before['total_uses']:,}) and "
        f"**{before['isin_pairs_pct']:.2f}% of surface-company pairs** "
        f"({before['isin_pairs']:,} / {before['isin_total']:,}); "
        f"{before['surfaces']:,} of {before['total_surfaces']:,} surfaces "
        f"({before['surfaces_pct']:.2f}%) carry a label.",
        f"- The deterministic mapper fix in this checkout adds "
        f"**{after_fix_uses:,} uses** ({pct(after_fix_uses, total):.2f} pp) and "
        f"**{after_fix_isin:,} surface-company pairs** without any model call: "
        f"ROE/ROCE/ROA/RONW now have declared labels and the `p&l` / `balance sheet` "
        f"spellings merge onto `financials`.",
        f"- The **{len(selected):,} promoted surfaces** in this review add "
        f"**{new_uses:,} uses** ({pct(new_uses, total):.2f} pp) and "
        f"**{new_isin:,} surface-company pairs** if approved.",
        f"- Assuming approval, coverage becomes **{after_cov['uses_pct']:.2f}% of "
        f"uses** and **{after_cov['isin_pairs_pct']:.2f}% of surface-company pairs**. "
        f"The 95% uses target is still **{95 - after_cov['uses_pct']:.2f} pp short**; "
        f"see §9 for what would close it.",
        "",
        "## 2. Data limit stated up front",
        "",
        "The job mounts only `v4_vocab.db`; the three extraction stores "
        "(`concall_facts.db`, `ar_facts.db`, `deck_figures.db`) are not present. "
        "The brief asks for the share of occurrences with a value or quote attached. "
        "That is an occurrence-weighted source measurement, and it cannot be computed "
        "from the stored vocabulary. This review therefore reports the **two verbatim "
        "excerpts already stored in `beam_context`** as a sampled proxy: `value 1/2` "
        "means one of two excerpts carries a digit; `quote 2/2` means both excerpts "
        "are text of at least three words. It is evidence of what the surface is "
        "attached to, not a claim about all occurrences. Re-running against the "
        "extraction stores would make it exact; the field is marked `sampled` in the "
        "proposal JSON.",
        "",
        "## 3. The mapper bug: ROE, ROCE and `ROCE %`",
        "",
        "**Root cause, measured.** `words_of` normalises `ROE` to the single token "
        "`roe`, `ROCE` to `roce`, and `ROCE %` to the same `roce` because `%` becomes "
        "the stop token `pct`. `TOKEN_TO_TOPIC` had no entry for any of them, and "
        "`PHRASE_TOPICS` had no `return on equity/capital` phrase, so `label_for` "
        "returned `(\"other\", \"other\")`. The bug is not the short length of the token: "
        "it is that the declared layer never named the ratio. There were "
        "**935 ROE**, **869 ROCE**, **192 `ROCE (%)`**, **190 `RoE%`**, "
        "**190 `RoCE%`**, **101 `ROE (%)`** and **77 `RoE`** occurrences in the "
        "pilot store, plus `ROA` (339) and `RONW` (32). Beam's pass2 left them `other` "
        "because the closed label list did not contain them either.",
        "",
        "**Fix.** `build_vocab.TOPICS` now declares `roe`, `roce`, `roa` and `ronw` "
        "under `financial_performance`; `PHRASE_TOPICS` adds "
        "`return equity -> roe`, `return capital employed -> roce`, "
        "`return asset -> roa` and `return worth -> ronw`; and `FOOTNOTE_RATIO` "
        "strips a glued footnote digit (`ROCE1`, `ROE2`) before mapping. "
        "`return capital` alone is deliberately not a phrase: `capital returns` "
        "normalises to the same two tokens and must not become ROCE. "
        "`ROCE (Pre-tax) (TTM)` now resolves to `roce` rather than `tax`; "
        "`Normalized ROCE (EBITDA basis)` resolves to `roce` because the "
        "occurrence-weight rule prefers the rarer token (`roce`) over `ebitda`.",
        "",
        "## 4. Spelling merge",
        "",
        "`SPELLING_VARIANTS` is applied before punctuation is expanded, so embedded "
        "extractor keys merge too: `p&l`, `P&L`, `p_and_l`, `p/l`, `pnl`, "
        "`consolidated_p_and_l`, `supplementary_pnl` all normalise to "
        "`profit and loss`; `balance_sheet`, `balance-sheet`, `balancesheet` all "
        "normalise to `balance sheet`. A statement heading (`p&l`, `balance sheet`) "
        "then maps to the existing label `financials` **only when no specific topic "
        "rides with it**: `Consolidated P&L – Depreciation` stays `depreciation` and "
        "`P&L – EBITDA` stays `ebitda`, while a bare `p&l` or `P&L extract` becomes "
        "`financials`. That also fixes the old `profit and loss -> loss` accident. "
        "This is a merge of spellings, not a guess: the merged words still go through "
        "`label_for`.",
        "",
        "| variant family | surfaces | uses | mapped to |",
        "|---|---:|---:|---|",
    ]
    # measure the spelling families on this store
    fam_re = {
        "p&l / p_and_l / pnl": re.compile(r"(?<![a-z0-9])(p\s*&\s*l|p_and_l|pnl|p/l)(?![a-z0-9])", re.I),
        "balance sheet / balance_sheet": re.compile(r"(?<![a-z0-9])(balance[\s_-]*sheet|balancesheet)(?![a-z0-9])", re.I),
    }
    for name, rx in fam_re.items():
        hit = [r for r in rows if rx.search(r["surface_verbatim"])]
        labs = Counter(r["fixed_label"] for r in hit)
        L.append(f"| `{name}` | {len(hit):,} | {sum(r['n_occurrences'] for r in hit):,} | "
                 f"{_md(', '.join(f'{k} ({v})' for k, v in labs.most_common(3)), 60)} |")
    L += [
        "",
        "## 5. How the promotion queue was ranked",
        "",
        "Every surface that is still unlabelled **after** the deterministic fix is a "
        "candidate. Rank score = uses × (1 + ln(1 + documents)) × "
        "(1 + ln(1 + companies)); ties break on uses then surface id. The review "
        "takes the top 500 by that score, then **adds every lower-ranked surface a "
        "master-bank question names**, regardless of frequency (brief item 5). "
        "`n_docs` is an exact distinct-document count; `n_isins` is the per-surface "
        "distinct-company count stored by the build. Surface-company pairs are the "
        "sum of `n_isins`; that is an incidence count, not a de-duplicated company "
        "roster (the store does not hold the roster).",
        "",
        "## 6. The Beam pass",
        "",
    ]
    batches = cfg.get("batches") or []
    runs = cfg.get("runs") or []
    done = [b for b in batches if b.get("status") == "done"]
    answered = sum(1 for r in selected
                   if (suggestions.get(r["surface_id"]) or {}).get("status") == "answered")
    L += [
        f"- **Surfaces sent:** {len(selected):,} ({len(selected) - answered:,} "
        f"unanswered); **top 500** plus **{len(extra):,} rare but asked kept** "
        f"(the kept list is not in the Beam queue).",
        f"- **Batches:** {len(done):,} done, "
        f"{sum(1 for b in batches if b.get('status') == 'pending'):,} pending; "
        f"{sum(int(b.get('in_tok') or 0) for b in done):,} tokens in / "
        f"{sum(int(b.get('out_tok') or 0) for b in done):,} out; median batch "
        f"{_median([b.get('secs') for b in done]):.1f} s; "
        f"{sum(int(r.get('n_429') or 0) for r in runs):,} 429s.",
        f"- **Decisions:** " + ", ".join(f"{k} {v:,}" for k, v in dec_counts.most_common())
        + ". `bucket` is never a label and its items keep their own text.",
        f"- **Session:** `{SESSION_JOB}` via `go_session.session_id` (stable across "
        "resume); every call is recorded at $0 through `cost_ledger.record_usage`.",
        "- **Agreement:** not asserted. This pass asks once and retries a rejected "
        "answer once; unlike VOCAB_PASS2 it does not run a second independent round, "
        "so no agreement percentage is claimed. The review is the human check.",
        "",
        "## 7. Gate report — uses and company spread",
        "",
        "| measured | installed (before) | after mapper fix | after proposals (approved) |",
        "|---|---:|---:|---:|",
        f"| labelled uses | {before['uses']:,} ({before['uses_pct']:.2f}%) | "
        f"{fixed_cov['uses']:,} ({fixed_cov['uses_pct']:.2f}%) | "
        f"{after_cov['uses']:,} ({after_cov['uses_pct']:.2f}%) |",
        f"| surface-company pairs | {before['isin_pairs']:,} "
        f"({before['isin_pairs_pct']:.2f}%) | {fixed_cov['isin_pairs']:,} "
        f"({fixed_cov['isin_pairs_pct']:.2f}%) | {after_cov['isin_pairs']:,} "
        f"({after_cov['isin_pairs_pct']:.2f}%) |",
        f"| labelled surfaces | {before['surfaces']:,} "
        f"({before['surfaces_pct']:.2f}%) | {fixed_cov['surfaces']:,} "
        f"({fixed_cov['surfaces_pct']:.2f}%) | {after_cov['surfaces']:,} "
        f"({after_cov['surfaces_pct']:.2f}%) |",
        f"| head surfaces labelled (95% of uses) | {before['head_labelled']:,} / "
        f"{before['head_total']:,} ({before['head_pct']:.2f}%) | "
        f"{fixed_cov['head_labelled']:,} ({fixed_cov['head_pct']:.2f}%) | "
        f"{after_cov['head_labelled']:,} ({after_cov['head_pct']:.2f}%) |",
        f"| gate vs 95% uses | {95 - before['uses_pct']:.2f} pp short | "
        f"{95 - fixed_cov['uses_pct']:.2f} pp short | "
        f"{95 - after_cov['uses_pct']:.2f} pp short |",
        "",
        f"Head membership here is the deterministic cumulative-95% cut "
        f"({before['head_total']:,} surfaces, sorted by uses then surface id); it "
        f"reproduces VOCAB_PASS2's 43,744 / 62,601 = 69.88% exactly. The tie inside "
        "the 22,782 twice-occurring surfaces is still a tie-break artefact, but the "
        "uses figure is not tie-sensitive and is the primary gate.",
        "",
        "**New topics this takes:** "
        f"**{new_label_count:,} raw new label ids** from {dec_counts['new_label']:,} "
        f"surfaces; mechanical de-duplication (singular/plural and identical "
        f"definitions) groups them into **{dedupe['clusters']:,} clusters** "
        f"({dedupe['merged_away']:,} slugs merge away), so the final topic count is "
        "Opus's semantic merge, not the raw 233. "
        f"{dec_counts['alias_of']:,} surfaces alias to existing labels; "
        f"{dec_counts['bucket']:,} are buckets and {dec_counts['meaningless']:,} are "
        f"meaningless (neither becomes a label). A stricter reading that sends the "
        f"BRSR/ESG headings (`environment`, `sustainability`, `energy`, `water`, "
        f"`waste`, `emissions`, `esg`, ...) to `bucket:section` rather than a topic "
        f"would remove **{brsr_uses:,} uses** from the after figure.",
        "",
    ]

    # new labels table
    if prop["new"]:
        L += ["### 7b. New labels Beam proposes (needs family approval)", "",
              "| proposed label | definition | surfaces | uses | top surfaces |",
              "|---|---|---:|---:|---|"]
        for lab, d in sorted(prop["new"].items(), key=lambda kv: -kv[1]["uses"])[:60]:
            top = ", ".join(_md(x["surface"], 28) for x in d["examples"][:3])
            L.append(f"| `{lab}` | {_md(d['definition'], 80) or '(no definition)'} | "
                     f"{len(d['surfaces']):,} | {d['uses']:,} | {top} |")
        L += ["", f"Full list in `{_rel(PROPOSAL)}`. The family/parent is **not** "
              "assigned here; every new label needs a parent from the nine declared "
              "families at approval. Beam only suggests the slug and definition.", ""]

    # aliases table
    if prop["alias"]:
        L += ["### 7c. Aliases to existing labels (proposed, not applied)", "",
              "| existing label | surfaces | uses | examples |", "|---|---:|---:|---|"]
        for lab, rs in sorted(prop["alias"].items(), key=lambda kv: -sum(r["n_occurrences"] for r in kv[1])):
            L.append(f"| `{lab}` | {len(rs):,} | {sum(r['n_occurrences'] for r in rs):,} | "
                     f"{', '.join(_md(r['surface_verbatim'], 28) for r in rs[:3])} |")
        L += ["", f"These are in `{_rel(PROPOSAL)}` under `aliases`; no `map` row was "
              "changed.", ""]

    # buckets
    if prop["bucket"]:
        L += ["### 7d. Buckets (never labels; items keep their own text)", "",
              "| bucket | surfaces | uses | examples |", "|---|---:|---:|---|"]
        for b, rs in sorted(prop["bucket"].items(), key=lambda kv: -sum(r["n_occurrences"] for r in kv[1])):
            L.append(f"| `{b}` | {len(rs):,} | {sum(r['n_occurrences'] for r in rs):,} | "
                     f"{', '.join(_md(r['surface_verbatim'], 28) for r in rs[:4])} |")
        L.append("")

    # mechanical near-duplicates among new labels: a merge aid, not a merge
    if dedupe["groups"]:
        L += ["### 7e. Mechanical near-duplicates among the new labels", "",
              f"{dedupe['raw']} raw slugs collapse to {dedupe['clusters']} clusters under "
              "singular/plural and identical-definition rules. This is a "
              "lower bound on the merge Opus should make; it is not applied. The top "
              "groups by uses:", "",
              "| suggested representative | members | uses |", "|---|---|---:|"]
        for g in dedupe["groups"][:20]:
            L.append(f"| `{g['representative']}` | "
                     f"{', '.join(f'`{m}`' for m in g['members'][:8])} | {g['uses']:,} |")
        L += ["",
              "**Worker reading, not a pass.** The 17 aliases, 63 `meaningless` calls and "
              "139 `bucket` calls are the safest part of this file: `signal`, `ratio` and "
              "`market_data` are extractor keys, not metrics, and the 17 aliases are "
              "ordinary synonyms. I would **not** approve all 233 new labels as-is. The "
              "BRSR/ESG headings (`environment`, `sustainability`, `energy`, `water`, "
              "`waste`, `emissions`, `esg`) are better as a `section` dimension than as "
              "topics, and the audit/reporting keys (`caro`, `iepf`, `agm`, `msme`, "
              "`certification`, `assurance`, `listing`, `maturity_analysis`, `offsetting`) "
              "read as sections or one-off disclosures. The new labels with a real metric "
              "behind them (`credit_rating`, `fair_value`, `aum`, `exceptional_items`, "
              "`derivatives`, `hedging`, `foreign_exchange`, `liquidity`, "
              "`corporate_action`, `goodwill`, `capital_commitment`) are the first "
              "tranche I would approve. The 82.77% after-proposals figure assumes every "
              "one of the 233 is approved; a stricter approval gives less. This is an "
              "opinion for the reviewers, not a decision, and it is not applied.",
              ""]

    # rare asked
    asked_labels = []
    for term in ("tailwind", "monsoon", "repo"):
        hit = [r for r in rows if r["fixed_label"] == term]
        asked_labels.append((term, len(hit), sum(r["n_occurrences"] for r in hit)))
    asked_terms = Counter()
    for r in extra:
        asked_terms.update(set(r["words"]) & ASKED_LIST)
    L += ["## 8. Rare but asked terms stay", "",
          "No label or surface is deleted by this work. Every label keeps its row and "
          "every unlabelled surface stays searchable as `other:<raw>`. The three terms "
          "the brief names are still declared labels:", "",
          "| label | surfaces | uses |", "|---|---:|---:|"]
    L += [f"| `{t}` | {n:,} | {u:,} |" for t, n, u in asked_labels]
    L += ["",
          f"In addition, **{len(extra):,}** lower-ranked surfaces pass the master-bank "
          "token/stem/list test and are kept below the top 500 whatever their "
          "frequency. The test is deliberately loose (it matches a word a question "
          "uses, not always the thing the question asks for), so the kept list "
          "includes entity names and section headings as well as rare metrics. None "
          "was promoted or deleted; all remain `other:<raw>` until the review table "
          "or a later pass names them.", ""]
    if asked_terms:
        L += ["| asked term in the kept list | surfaces | examples |", "|---|---:|---|"]
        for term, n in asked_terms.most_common(15):
            ex = [r["surface_verbatim"] for r in extra if term in r["words"]][:3]
            L.append(f"| `{term}` | {n:,} | {', '.join(_md(x, 30) for x in ex)} |")
        L.append("")
    if extra:
        L += ["Largest kept surfaces (evidence only; not in the Beam queue):", "",
              "| surface | uses | companies | bank match | example question |",
              "|---|---:|---:|---|---|"]
        for r in sorted(extra, key=lambda r: -r["n_occurrences"])[:15]:
            ex = (r.get("q_example") or {}).get("question", "")
            kind = ("exact" if r["q_exact"] else "token" if r["q_token"]
                    else "stem" if r["q_stem"] else "list" if r["q_list"] else "-")
            L.append(f"| `{_md(r['surface_verbatim'], 50)}` | {r['n_occurrences']:,} | "
                     f"{r['n_isins']} | {kind} | {_md(ex, 90)} |")
        if len(extra) > 15:
            L.append(f"| ... {len(extra) - 15:,} more in the work store | | | | |")
        L.append("")

    # gate gap
    L += [
        "## 9. How far short of 95% this leaves us",
        "",
        f"After the mapper fix and every proposal in this file, "
        f"**{after_cov['uses_pct']:.2f}% of uses** carry a label — "
        f"**{95 - after_cov['uses_pct']:.2f} pp short** of the 95% uses target. "
        f"That is {math.ceil(0.95 * total) - after_cov['uses']:,} additional uses. "
        f"By surface count the store is only {after_cov['surfaces_pct']:.2f}% labelled "
        f"({after_cov['surfaces']:,} / {after_cov['total_surfaces']:,}); the remaining "
        f"{after_cov['total_surfaces'] - after_cov['surfaces']:,} surfaces are mostly "
        "twice-occurring variants, so a surface-count gate and a uses gate are very "
        "different targets.",
        "",
        "The next-N curve below is an **upper bound**: it assumes every surface in the "
        "rank order can take a label, including the ones Beam calls bucket or "
        "meaningless. It is here to size the job, not as a forecast.",
        "",
        "| next surfaces labelled (upper bound) | uses coverage | cumulative added |",
        "|---:|---:|---:|",
    ]
    L += [f"| {c['n']:,} | {c['uses_pct']:.2f}% | +{c['added_pct']:.2f} pp |" for c in curve]
    L += [
        "",
        "**What else would close the gap, measured:**",
        "",
        f"1. **The bucket/section residue cannot be labelled at all.** In this review, "
        f"{dec_counts['bucket']:,} surfaces ({bucket_uses:,} uses, "
        f"{pct(bucket_uses, total):.2f}% of the corpus) are buckets or section "
        f"headings by Beam's reading, and {dec_counts['meaningless']:,} more "
        f"({meaningless_uses:,} uses) are meaningless alone. The biggest are "
        f"{top_bucket_text}. No topic label makes them metrics. Closing the uses "
        f"gap therefore needs an **extractor fix**: stop emitting the bucket/section "
        f"key as the metric and keep the item text under it (the `bucket` decision in "
        f"this review is the spec for that fix), or accept a separate `section` "
        f"dimension that is not counted as a label. `environment` and `credit_rating` "
        f"were proposed as topics, not buckets; that choice is part of the review.",
        f"2. **The next tranche.** The first 500 add at most "
        f"{curve[0]['added_pct'] if curve else 0:.2f} pp if every one were labelable, "
        f"but {dec_counts['bucket'] + dec_counts['meaningless']:,} of them are "
        f"bucket/meaningless and add 0, so the approved set adds "
        f"{pct(new_uses, total):.2f} pp. Surfaces 501-1,000 add at most "
        f"{(curve[1]['uses_pct'] - curve[0]['uses_pct']) if len(curve) > 1 else 0:.2f} "
        f"pp (upper bound). After that come longer-tail presentation rows and "
        f"company/product names; many will be `bucket:deck_line` or `entity`, not a "
        f"label. Reaching 95% of uses by labelling alone would require labelling the "
        f"bucket residue too, which would be a false label, not coverage.",
        f"3. **The 95%-of-head-surfaces gate** is further away than the uses gate: "
        f"{before['head_labelled']:,} of {before['head_total']:,} head surfaces carry "
        f"a label now ({before['head_pct']:.2f}%); the mapper fix adds "
        f"{fixed_cov['head_labelled'] - before['head_labelled']:,} and the promoted "
        f"labels add {after_cov['head_labelled'] - fixed_cov['head_labelled']:,}, "
        f"leaving {after_cov['head_total'] - after_cov['head_labelled']:,} head "
        f"surfaces unlabelled. Most are twice-occurring spelling/format variants; the "
        f"honest route is to promote them by the same Beam pass in batches (the store "
        f"is resumable) and to stop counting bucket headings as head surfaces.",
        f"4. **The label-only ceiling.** The top 500 carry "
        f"{sum(r['n_occurrences'] for r in selected):,} uses between them; "
        f"{bucket_uses + meaningless_uses:,} of those "
        f"({pct(bucket_uses + meaningless_uses, sum(r['n_occurrences'] for r in selected)):.1f}%) "
        f"are bucket/meaningless. If that mix holds for the "
        f"{total - fixed_cov['uses']:,} uses still unlabelled after the mapper fix, "
        f"only about {total - fixed_cov['uses'] - int((total - fixed_cov['uses']) * (bucket_uses + meaningless_uses) / max(1, sum(r['n_occurrences'] for r in selected))):,} "
        f"of them are labelable, which caps label-only coverage near "
        f"**{pct(fixed_cov['uses'] + (total - fixed_cov['uses']) * (1 - (bucket_uses + meaningless_uses) / max(1, sum(r['n_occurrences'] for r in selected))), total):.1f}%**. "
        f"That is an extrapolation, not a measurement, but it is the honest reading: "
        f"the remaining gap to 95% is an extractor/taxonomy gap, not a shortage of "
        f"Beam calls.",
        "",
        "**The concrete path, in order:** (a) fix the extractors so a bucket key is "
        "not emitted as a metric surface (`signal`, `ratio`, `market_data`, "
        "`section`, `table_header`, `deck_line`) and keep the item text under it; "
        "(b) run the next promotion tranche (501-1,000) through the same resumable "
        "pass, then 1,001-2,000; (c) have Opus assign a family to each approved new "
        "label, merge the 19 mechanical duplicates and decide whether BRSR/ESG "
        "headings are topics or sections; (d) re-measure the gate on the cleaned "
        "denominator. Without (a), the label-only ceiling above is the real maximum.",
        "",
        "## 10. The review table",
        "",
        f"One row per promoted surface, ranked by the score. `value` is the sampled "
        f"value evidence (value-bearing excerpts / excerpts and that share); `quote` "
        f"is the same for excerpts of at least three words; `bank` is the master-bank "
        f"match "
        f"(exact/token/stem/list, `-` for none); `alone` says whether the phrase "
        f"means anything on its own. `Beam` is a suggestion, not an applied label.",
        "",
        "| # | surface | uses | docs | cos | store | value | quote | bank | alone | Beam | definition / Beam reason |",
        "|---:|---|---:|---:|---:|---|---|---|---|---|---|---|",
    ]
    for i, r in enumerate(selected, 1):
        s = suggestions.get(r["surface_id"]) or {}
        val = (f"{r['value_n']}/{r['ctx_n']} ({100 * r['value_n'] / r['ctx_n']:.0f}%)"
               if r["ctx_n"] else "-")
        quo = (f"{r['quote_n']}/{r['ctx_n']} ({100 * r['quote_n'] / r['ctx_n']:.0f}%)"
               if r["ctx_n"] else "-")
        bank = ("exact" if r["q_exact"] else "token" if r["q_token"]
                else "stem" if r["q_stem"] else "list" if r["q_list"] else "-")
        if r["q_n"]:
            bank += f" ({r['q_n']})"
        alone = "yes" if r["alone"] else f"no: {_md(r['alone_reason'], 22)}"
        L.append(
            f"| {i} | `{_md(r['surface_verbatim'], 64)}` | {r['n_occurrences']:,} | "
            f"{r['n_docs']:,} | {r['n_isins']} | {r['source_kind']} | {val} | {quo} | "
            f"{bank} | {alone} | {_decision_cell(s)} | "
            f"{_md(s.get('definition') or '', 100)} |")
    L += [""]

    # evidence appendix: contexts for the top 60
    L += ["## 11. Context evidence for the top 60", "",
          "| # | surface | excerpt 1 | excerpt 2 |", "|---:|---|---|---|"]
    for i, r in enumerate(selected[:60], 1):
        L.append(f"| {i} | `{_md(r['surface_verbatim'], 40)}` | "
                 f"{_md(r.get('ctx1') or '', 110)} | {_md(r.get('ctx2') or '', 110)} |")
    L += [""]

    # unresolved
    if prop["unanswered"]:
        L += ["## 12. Unanswered (left as `other:<raw>`)", "",
              "| surface | uses | companies | reason |", "|---|---:|---:|---|"]
        for r in sorted(prop["unanswered"], key=lambda r: -r["n_occurrences"])[:60]:
            s = suggestions.get(r["surface_id"]) or {}
            L.append(f"| `{_md(r['surface_verbatim'], 50)}` | {r['n_occurrences']:,} | "
                     f"{r['n_isins']} | {_md(s.get('raw') or s.get('status') or '', 60)} |")
        L += [""]

    L += [
        "## 13. Proposed files and approval checklist",
        "",
        f"- `{_rel(PROPOSAL)}` — new labels (with Beam definitions), aliases to "
        "existing labels, buckets, meaningless, unanswered. `applied: false`.",
        "- Opus/Shivam: approve or reject each new label id and assign its parent "
        "family; approve aliases; treat `bucket` as an extractor fix, not a vocabulary "
        "label; leave `meaningless` as `other:<raw>`.",
        "- To apply after approval (controller, outside this sandbox): rebuild the "
        "pilot vocabulary with the fixed `build_vocab` (new ratio/spelling rules are "
        "code), then apply only the approved new labels/aliases to `map`; do not "
        "delete surfaces. Re-run this review against the installed store to measure "
        "the real before/after. The source mount is read-only here; nothing was "
        "installed.",
        "",
    ]

    REVIEW.parent.mkdir(parents=True, exist_ok=True)
    REVIEW.write_text("\n".join(L), encoding="utf-8")

    proposal = {
        "generated_at": _now(),
        "applied": False,
        "source_store": source_note,
        "model": MODEL,
        "note": ("Beam suggestions only. No label or alias was written to map. "
                 "New labels need a parent family at approval."),
        "data_limit": ("value/quote evidence is a two-excerpt sample from beam_context; "
                       "the extraction stores needed for the occurrence-weighted share "
                       "were not mounted"),
        "gate": {
            "before": before, "after_mapper_fix": fixed_cov, "after_proposals": after_cov,
            "uses_target_pct": 95.0,
            "shortfall_pp": round(95.0 - after_cov["uses_pct"], 3),
            "if_brsr_headings_are_buckets": {
                "uses_removed": brsr_uses,
                "uses_pct_after": round(pct(after_cov["uses"] - brsr_uses, total), 3),
            },
        },
        "mapper_fix": {
            "added_topics": ["roe", "roce", "roa", "ronw"],
            "spelling_variants": ["p&l", "p_and_l", "pnl", "p/l", "balance sheet",
                                  "balance_sheet", "balancesheet"],
            "newly_labelled_surfaces": fixed_cov["surfaces"] - before["surfaces"],
            "newly_labelled_uses": after_fix_uses,
            "newly_labelled_isin_pairs": after_fix_isin,
            "changed_existing_labels": len(remap_info["changed"]),
        },
        "new_labels": sorted(
            ({"label_id": lab, "parent_id": None, "needs_family": True,
              "definition": d["definition"], "surfaces": d["surfaces"],
              "uses": d["uses"], "isin_pairs": d["isin_pairs"]}
             for lab, d in prop["new"].items()), key=lambda d: -d["uses"]),
        "new_label_dedupe": dedupe,
        "aliases": sorted(
            ({"surface": r["surface_verbatim"], "label_id": lab,
              "uses": r["n_occurrences"], "companies": r["n_isins"]}
             for lab, rs in prop["alias"].items() for r in rs),
            key=lambda d: -d["uses"]),
        "buckets": sorted(
            ({"surface": r["surface_verbatim"], "bucket": b,
              "uses": r["n_occurrences"], "companies": r["n_isins"]}
             for b, rs in prop["bucket"].items() for r in rs),
            key=lambda d: -d["uses"]),
        "meaningless": sorted(
            ({"surface": r["surface_verbatim"], "uses": r["n_occurrences"],
              "companies": r["n_isins"]} for r in prop["meaningless"]),
            key=lambda d: -d["uses"]),
        "unanswered": sorted(
            ({"surface": r["surface_verbatim"], "uses": r["n_occurrences"],
              "companies": r["n_isins"],
              "reason": (suggestions.get(r["surface_id"]) or {}).get("raw", "")}
             for r in prop["unanswered"]), key=lambda d: -d["uses"]),
        "marginal_curve": curve,
    }
    PROPOSAL.parent.mkdir(parents=True, exist_ok=True)
    PROPOSAL.write_text(json.dumps(proposal, indent=1, ensure_ascii=False), encoding="utf-8")

    return {
        "review": _rel(REVIEW), "proposal": _rel(PROPOSAL),
        "selected": len(selected), "new_labels": new_label_count,
        "before_uses_pct": before["uses_pct"], "after_uses_pct": after_cov["uses_pct"],
        "after_isin_pct": after_cov["isin_pairs_pct"],
        "shortfall_pp": round(95.0 - after_cov["uses_pct"], 3),
        "decisions": dict(dec_counts), "unlabelled_uses": unlabelled_uses,
    }


# --- cli ---------------------------------------------------------------------
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--work", type=Path, default=WORK_DB)
    ap.add_argument("--questions", type=Path, default=QUESTIONS)
    ap.add_argument("--limit", type=int, default=TOP_N)
    ap.add_argument("--batch", type=int, default=BATCH)
    ap.add_argument("--start", type=int, default=4)
    ap.add_argument("--ceiling", type=int, default=MAX_LIMIT)
    ap.add_argument("--limit-batches", type=int, default=0)
    ap.add_argument("--run-beam", action="store_true")
    ap.add_argument("--report-only", action="store_true")
    args = ap.parse_args(argv)

    source, source_note = open_vocab(args.db, args.work)
    rows = load_rows(source)
    labels = labels_of(source)
    tables = {r[0] for r in source.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    contexts = ({r["surface_id"]: (r["ctx1"], r["ctx2"]) for r in source.execute(
        "SELECT surface_id, ctx1, ctx2 FROM beam_context")} if "beam_context" in tables
        else {})
    source.close()

    questions = load_questions(args.questions)
    index = _question_index(questions)
    remap_info = remap(rows)
    head = head_ids(rows)
    add_evidence(rows, questions, index, contexts)
    top, extra = select(rows, args.limit)
    selected = top + extra
    for i, r in enumerate(selected, 1):
        r["rank"] = i

    con = open_work(args.work)
    plan = store_candidates(con, top, args.batch)
    suggestions = load_suggestions(con)
    gate = {"head": head}

    summary: dict = {"source": source_note, "surfaces": len(rows),
                     "selected": len(top), "top": len(top), "extra_kept": len(extra),
                     "baseline_uses_pct": round(coverage(
                         rows, {r["surface_id"] for r in rows if r["label_id"] is not None},
                         head)["uses_pct"], 2),
                     "fixed_uses_pct": round(coverage(
                         rows, {r["surface_id"] for r in rows if r["fixed_label"] != "other"},
                         head)["uses_pct"], 2),
                     "suggestions": len(suggestions),
                     "unanswered": sum(1 for r in top if r["surface_id"] not in suggestions)}

    if args.run_beam and not args.report_only:
        from reality_engine.scripts.resource_watchdog import user_env

        env = user_env()
        key = next((env[e] for e in ("OPENCODE_GO_API_KEY_2", "OPENCODE_GO_API_KEY")
                    if env.get(e)), "")
        if not key:
            print("no OPENCODE_GO_API_KEY_2 / OPENCODE_GO_API_KEY in the environment",
                  file=sys.stderr)
            return 2
        try:
            summary["run"] = run_beam(
                con, labels, plan, top, suggestions, key, start=args.start,
                ceiling=args.ceiling, limit_batches=args.limit_batches,
                poster=lambda s, u, k: call_beam(s, u, k, job=SESSION_JOB,
                                                 caller=SESSION_JOB))
        except BillingError as exc:
            print(json.dumps({"error": "billing", "detail": str(exc), **summary}, indent=1))
            print("STOPPING: beam-free is no longer free.", file=sys.stderr)
            return 3
        except KeyboardInterrupt:
            print(json.dumps({"error": "interrupted", **summary}, indent=1))
            return 130
        suggestions = load_suggestions(con)

    cfg = {
        "limit": args.limit,
        "batches": [dict(r) for r in con.execute("SELECT * FROM batch ORDER BY batch_id")],
        "runs": [dict(r) for r in con.execute("SELECT * FROM run ORDER BY run_at")],
    }
    summary["report"] = write_reports(
        rows, top, suggestions, labels, cfg, remap_info, gate,
        extra, source_note)
    con.close()
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
