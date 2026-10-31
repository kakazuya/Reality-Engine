"""v4 WP8 — label the head surfaces with free Beam (§A.9, §H.8).

The deterministic mapper names 37,204 of the 62,601 head surfaces; the rest are
``other:<raw>``.  This driver sends those remaining surfaces to the free
``beam-free`` model on OpenCode Go in batches of ~50, with the closed label list
and each surface's two verbatim contexts, machine-checks every answer (a declared
label id or ``other``), retries a rejected answer once, then writes ``other``.

    python -m reality_engine.query.v4.map_vocab_beam --out .tmp/v4_vocab_pass2.db
    python -m reality_engine.query.v4.map_vocab_beam --agreement
    python -m reality_engine.query.v4.map_vocab_beam --status
    python -m reality_engine.query.v4.map_vocab_beam --report

``.tmp/v4_vocab_pass2.db`` is a copy of the WP2b store with one added column,
``map.source`` (``deterministic`` | ``beam``), plus the beam audit tables and the
recomputed report.  Resumable: a finished batch is a ``beam_batch`` row and the
batch plan is a pure function of the store, so a re-run skips what is done and
never redoes it.  Two rounds: round 1 maps the workload, round 2 re-maps a random
sample of head surfaces in a different batch composition to measure agreement.

Free model only: HTTP 402, or a body naming billing/quota/credits, stops the run.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import random
import re
import sqlite3
import sys
import threading
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import requests

from reality_engine.db.readonly import connect_ro
from reality_engine.scripts.go_session import session_id
from reality_engine.toolbelt.cost_ledger import record_usage

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
UNIVERSE = ROOT / "tasks" / "pilot60" / "UNIVERSE.csv"
URL = "https://opencode.ai/zen/go/v1/chat/completions"
MODEL = "beam-free"
KEY_ENVS = ("OPENCODE_GO_API_KEY_2", "OPENCODE_GO_API_KEY")
BATCH = 50
CONTEXT_CHARS = 150
AGREEMENT_N = 500
SAMPLE_N = 100
ROUND2_BASE = 9000
SEED = 20261031
# ``beam-free`` is a reasoning model: at its default effort a 50-phrase batch
# spends the whole token budget thinking and the answer is truncated mid-JSON.
# "low" still reasons (measured ~530 reasoning tokens for 8 phrases, same labels)
# and leaves room for all 50 pairs.
REASONING_EFFORT = "low"
MAX_TOKENS = 8000
HEAD_SURFACES = 62_601          # the declared head: 95% of 1,815,581 occurrences
HEAD_LABELLED = 37_204          # what the deterministic pass named
MAX_LIMIT = 128                 # probe ceiling; the clean level actually reached is reported

SYSTEM = """You label metric phrases extracted from Indian listed-company documents \
(annual reports, earnings-call transcripts, investor presentations).

The closed label list (answer with exactly one id from it, or "other"):
{labels}

How to answer:
- The label says what the phrase is ABOUT, never what was said about it. Direction, value, \
period, certainty and unit are not labels.
- Synonyms and word order do not matter: if the phrase names something the list covers, use \
that id (e.g. "sales mix" -> revenue, "order inflow" -> order_intake, "capex plan" -> capex).
- "other" when the phrase is a bucket word, a bare unit, a ratio with no metric named, a \
company/brand/product name on its own, or nothing on the list names it. A wrong label is \
worse than "other": when two labels are both defensible, answer "other".
- Company, brand and period words do not change the topic.

Reply with JSON only, one entry per phrase number, no prose:
{{"<n>": "<label_id>", ...}}"""


class BillingError(RuntimeError):
    """The model answered with a billing/quota error: stop, do not retry."""


class RateLimited(RuntimeError):
    """HTTP 429: the provider is refusing more parallel work."""


class GateGivenUp(RuntimeError):
    """A batch kept hitting 429: leave it pending for the next run, keep the rest."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def data_root() -> Path:
    return Path(os.environ.get("REALITY_DATA_ROOT", ROOT / "reality_engine" / "data"))


# --- store -------------------------------------------------------------------
BEAM_SCHEMA = """
CREATE TABLE IF NOT EXISTS beam_batch(
  batch_id INTEGER PRIMARY KEY, round INTEGER NOT NULL, variant TEXT,
  status TEXT NOT NULL, n_surfaces INTEGER NOT NULL, n_ok INTEGER NOT NULL DEFAULT 0,
  n_retried INTEGER NOT NULL DEFAULT 0, n_other INTEGER NOT NULL DEFAULT 0,
  n_ok_first INTEGER NOT NULL DEFAULT 0, secs REAL,
  in_tok INTEGER DEFAULT 0, out_tok INTEGER DEFAULT 0,
  started_at TEXT, finished_at TEXT, note TEXT);
CREATE TABLE IF NOT EXISTS beam_answer(
  surface_id INTEGER NOT NULL, round INTEGER NOT NULL, variant TEXT NOT NULL DEFAULT '',
  batch_id INTEGER, label_raw TEXT, label_id TEXT, first_pass INTEGER NOT NULL,
  attempts INTEGER NOT NULL, answered_at TEXT NOT NULL,
  PRIMARY KEY (surface_id, round, variant));
CREATE TABLE IF NOT EXISTS beam_context(
  surface_id INTEGER PRIMARY KEY, ctx1 TEXT, ctx2 TEXT);
CREATE TABLE IF NOT EXISTS beam_run(
  run_at TEXT, round INTEGER, batches INTEGER, surfaces INTEGER, elapsed_s REAL,
  best_limit INTEGER, final_limit INTEGER, n_429 INTEGER, calls_per_min REAL);
"""


def open_pass2(path: Path, vocab: Path) -> sqlite3.Connection:
    """Open (creating from a copy of ``vocab``) the pass2 store; idempotent."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        src = sqlite3.connect(f"file:{vocab.as_posix()}?mode=ro", uri=True)
        dst = sqlite3.connect(path)
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
    con = sqlite3.connect(path, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=30000")
    if "source" not in {r[1] for r in con.execute("PRAGMA table_info(map)")}:
        con.execute("ALTER TABLE map ADD COLUMN source TEXT NOT NULL DEFAULT 'deterministic'")
    con.executescript(BEAM_SCHEMA)
    con.commit()
    return con


def labels_of(con: sqlite3.Connection) -> dict[str, dict]:
    rows = con.execute("SELECT label_id, parent_id, definition FROM label WHERE level=2 "
                       "ORDER BY label_id").fetchall()
    return {r["label_id"]: {"parent": r["parent_id"], "definition": r["definition"] or ""}
            for r in rows}


def label_block(labels: dict[str, dict]) -> str:
    return "\n".join(f"- {tid} [{v['parent']}]: {v['definition']}"
                     for tid, v in sorted(labels.items()))


# --- workload ----------------------------------------------------------------
def workload(con: sqlite3.Connection, unmapped: Path) -> list[dict]:
    """The head surfaces the deterministic pass could not name, biggest first."""
    declared = json.loads(unmapped.read_text(encoding="utf-8"))
    names = {r["surface"] for r in declared}
    rows = con.execute(
        "SELECT s.surface_id, s.surface_verbatim, s.n_occurrences, s.n_isins, s.source_kind, "
        "m.label_id FROM surface s JOIN map m USING(surface_id)").fetchall()
    out = [{"surface_id": r["surface_id"], "surface": r["surface_verbatim"],
            "n": r["n_occurrences"], "n_isins": r["n_isins"],
            "source_kind": r["source_kind"], "label_id": r["label_id"]}
           for r in rows if r["surface_verbatim"] in names]
    out.sort(key=lambda r: (-r["n"], r["surface_id"]))
    return out


def head_surfaces(con: sqlite3.Connection) -> list[dict]:
    """The pool the agreement round draws from: every surface in the head."""
    rows = con.execute(
        "SELECT surface_id, surface_verbatim, n_occurrences, n_isins, source_kind "
        "FROM surface WHERE n_occurrences >= 2").fetchall()
    return [{"surface_id": r["surface_id"], "surface": r["surface_verbatim"],
             "n": r["n_occurrences"], "n_isins": r["n_isins"],
             "source_kind": r["source_kind"]} for r in rows]


def plan(rows: list[dict], base: int = 1, size: int = BATCH) -> list[tuple[int, list[dict]]]:
    """Deterministic batch plan: (batch_id, surfaces) — the same every run."""
    return [(base + i // size, rows[i:i + size]) for i in range(0, len(rows), size)]


def plan_agreement(rows: list[dict], n: int = AGREEMENT_N,
                   seed: int = SEED) -> tuple[list, list]:
    """Two independently composed batch sets over the same random head surfaces."""
    rng = random.Random(seed)
    sample = rng.sample(rows, min(n, len(rows)))
    a, b = list(sample), list(sample)
    rng.shuffle(a)
    rng.shuffle(b)
    return plan(a, ROUND2_BASE), plan(b, ROUND2_BASE + 1000)


# --- contexts ----------------------------------------------------------------
def pilot_isins() -> list[str]:
    with open(UNIVERSE, encoding="utf-8") as f:
        return [r["isin"] for r in csv.DictReader(f) if r.get("isin")]


def _cut(text: str | None) -> str | None:
    if not text:
        return None
    text = " ".join(str(text).split())
    return text[:CONTEXT_CHARS] or None


def collect_contexts(data_root_path: Path, isins: list[str],
                     wanted: set[str]) -> dict[str, list]:
    """Up to two verbatim excerpts per surface, from the store that holds it."""
    out: dict[str, list[str]] = defaultdict(list)

    def add(surface, text):
        if surface in wanted and text and len(out[surface]) < 2:
            out[surface].append(text)

    q = ",".join("?" * len(isins))
    con = connect_ro(data_root_path / "concall_facts.db", timeout_s=300, immutable=True)
    try:
        for metric, statement, quote in con.execute(
                f"SELECT metric, statement, quote FROM cc_items WHERE isin IN ({q})", isins):
            add(metric, _cut(statement) or _cut(quote))
    finally:
        con.close()

    con = connect_ro(data_root_path / "ar_facts.db", timeout_s=1800, immutable=True)
    try:
        for category, item, quote in con.execute(
                f"SELECT category, item, quote FROM ar_facts WHERE isin IN ({q})", isins):
            add(category, _cut(item) or _cut(quote))
    finally:
        con.close()

    con = connect_ro(data_root_path / "deck_figures.db", timeout_s=900, immutable=True)
    try:
        hashes = [r[0] for r in con.execute(
            f"SELECT DISTINCT sha256 FROM pages WHERE isin IN ({q})", isins)]
        for i in range(0, len(hashes), 400):
            chunk = hashes[i:i + 400]
            hq = ",".join("?" * len(chunk))
            for metric, period, raw, unit in con.execute(
                    f"SELECT metric, period, raw_number, unit FROM facts "
                    f"WHERE sha256 IN ({hq})", chunk):
                bits = [b for b in (period, raw, unit) if b and b != "-"]
                add(metric, "printed: " + " ".join(bits) if bits else None)
    finally:
        con.close()
    return dict(out)


def ensure_contexts(con: sqlite3.Connection, data_root_path: Path,
                    rows: list[dict]) -> dict[int, list]:
    """Fill ``beam_context`` once for the workload; a re-run reads it back."""
    def read():
        return {r["surface_id"]: [r["ctx1"], r["ctx2"]]
                for r in con.execute("SELECT surface_id, ctx1, ctx2 FROM beam_context")}
    have = read()
    missing = [r for r in rows if r["surface_id"] not in have]
    if missing:
        found = collect_contexts(data_root_path, pilot_isins(),
                                 {r["surface"] for r in missing})
        con.executemany(
            "INSERT OR REPLACE INTO beam_context VALUES (?,?,?)",
            [(r["surface_id"], *(found.get(r["surface"], []) + [None, None])[:2])
             for r in missing])
        con.commit()
        have = read()
    return have


# --- prompt / parse ----------------------------------------------------------
def prompt_of(labels: dict[str, dict], items: list[tuple[int, dict]],
              contexts: dict[int, list]) -> tuple[str, str]:
    lines = []
    for idx, r in items:
        ctx = [c for c in contexts.get(r["surface_id"], []) if c]
        line = (f'{idx}. "{r["surface"]}" [{r["source_kind"]}, {r["n_isins"]} companies, '
                f'{r["n"]} occurrences]')
        if ctx:
            line += " contexts: " + " || ".join(ctx)
        lines.append(line)
    user = ("Label every phrase below with exactly one label id or \"other\".\n\n"
            + "\n".join(lines) + "\n\nJSON only, one entry per phrase number.")
    return SYSTEM.format(labels=label_block(labels)), user


_PAIR = re.compile(r'"(\d{1,4})"\s*:\s*"([^"\\]{0,40})"')


def parse_answers(text: str | None, wanted: dict[int, None],
                  allowed: set[str]) -> tuple[dict[int, str], dict[int, str]]:
    """(accepted idx -> declared label id, rejected idx -> raw answer or ``""``).

    Tolerant on purpose: a truncated or fenced JSON body still yields the complete
    pairs, and anything that is not a declared id is *rejected*, never mapped.
    """
    accepted: dict[int, str] = {}
    rejected: dict[int, str] = {}
    for key, value in _PAIR.findall(text or ""):
        idx = int(key)
        if idx not in wanted or idx in accepted:
            continue
        raw = value.strip().strip("`.,;: ").lower()
        if raw == "other":
            accepted[idx] = "other"
        elif raw in allowed:
            accepted[idx] = raw
        else:
            rejected[idx] = raw
    for idx in wanted:
        rejected.setdefault(idx, "")
    accepted = {k: v for k, v in accepted.items()}
    for idx in accepted:
        rejected.pop(idx, None)
    return accepted, rejected


# --- model call --------------------------------------------------------------
def call_beam(system: str, user: str, key: str, *, timeout: int = 300,
              job: str = "v4_vocab_pass2", caller: str = "v4_vocab_pass2") -> dict:
    """One request; raises RateLimited / BillingError, retries a 5xx twice.

    ``job`` is the stable OpenCode session tag (``go_session.session_id`` hashes
    the job, model and key together); it stays constant across a resumable run.
    ``caller`` is the ledger label, kept separate so a promotion run is not
    charged to the pass2 job in ``tasks/ledgers/spend.jsonl``.
    """
    key = key or ""
    last = ""
    body = {"model": MODEL, "max_tokens": MAX_TOKENS,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}]}
    if REASONING_EFFORT:
        body["reasoning_effort"] = REASONING_EFFORT
    for attempt in range(3):
        try:
            r = requests.post(
                URL, timeout=timeout,
                headers={"Authorization": f"Bearer {key}",
                         "x-opencode-session": session_id(job, MODEL, key)},
                json=body)
        except requests.RequestException as exc:
            last = repr(exc)[:200]
            time.sleep(3 * (attempt + 1))
            continue
        body = r.text or ""
        if r.status_code == 429:
            raise RateLimited(body[:120])
        if r.status_code == 200:
            data = r.json()
            choice = (data.get("choices") or [{}])[0]
            usage = data.get("usage") or {}
            record_usage(MODEL, usage, caller)
            return {"content": (choice.get("message") or {}).get("content") or "",
                    "finish": choice.get("finish_reason"),
                    "in_tok": int(usage.get("prompt_tokens") or 0),
                    "out_tok": int(usage.get("completion_tokens") or 0)}
        # a non-200 body is where a billing/quota refusal shows up: never on a 200
        if r.status_code == 402 or re.search(r"billing|quota|insufficient|credit", body, re.I):
            raise BillingError(f"HTTP {r.status_code}: {body[:200]}")
        last = f"HTTP {r.status_code}: {body[:160]}"
        time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"{MODEL} failed after 3 tries: {last}")


class Gate:
    """Adaptive concurrency: double after 20 clean calls, halve on a 429."""

    def __init__(self, start: int = 4, ceiling: int = MAX_LIMIT):
        self.limit = max(1, start)
        self.ceiling = max(self.limit, ceiling)
        self.active = 0
        self.clean = 0
        self.ratelimited = 0
        self.denied: set[int] = set()
        self.best = self.limit
        self.cv = threading.Condition()

    def __enter__(self):
        with self.cv:
            while self.active >= self.limit:
                self.cv.wait(0.5)
            self.active += 1
        return self

    def __exit__(self, *exc):
        with self.cv:
            self.active -= 1
            self.cv.notify_all()

    def ok(self):
        with self.cv:
            self.clean += 1
            if self.clean % 20 == 0:
                up = min(self.limit * 2, self.ceiling)
                while up in self.denied and up > self.limit:
                    up //= 2
                if up > self.limit:
                    self.limit = up
                    self.best = max(self.best, self.limit)
                    self.cv.notify_all()

    def limited(self):
        with self.cv:
            self.ratelimited += 1
            self.denied.add(self.limit)
            self.limit = max(1, self.limit // 2)
            self.cv.notify_all()


def _ask(poster, system, user, key, gate) -> dict:
    """One gated call; every 429 lowers the limit and backs off before retrying.

    The provider rate-limits by *slowing down* first and 429s later, so a 429 is
    never fatal for the run: after six attempts the batch is left pending.
    """
    last: Exception | None = None
    for attempt in range(6):
        with gate:
            try:
                rep = poster(system, user, key)
                gate.ok()
                return rep
            except RateLimited as exc:
                gate.limited()
                last = exc
        time.sleep(min(60.0, 2.0 ** attempt) * (0.7 + 0.6 * random.random()))
    raise GateGivenUp(str(last))


def answer_batch(labels, allowed, items, contexts, poster, key, gate) -> dict:
    """One batch: ask, machine-check, retry the rejected once, then ``other``."""
    system, user = prompt_of(labels, items, contexts)
    wanted = {i: None for i, _ in items}
    started, t0 = _now(), time.time()
    rep = _ask(poster, system, user, key, gate)
    in_tok, out_tok = rep["in_tok"], rep["out_tok"]
    accepted, rejected = parse_answers(rep["content"], wanted, allowed)
    first = dict(accepted)
    if rejected:
        # renumbered 0..k-1: the model never has to echo an index it did not see
        origin = [i for i, _ in items if i in rejected]
        again = list(enumerate(r for i, r in items if i in rejected))
        s2, u2 = prompt_of(labels, again, contexts)
        u2 += ("\n\nYour previous answer did not cover these, or was not one of the "
               "declared ids. Answer only with declared ids from the list, or \"other\".")
        rep2 = _ask(poster, s2, u2, key, gate)
        in_tok += rep2["in_tok"]
        out_tok += rep2["out_tok"]
        more, _ = parse_answers(rep2["content"], {j: None for j in range(len(origin))},
                                allowed)
        for j, val in more.items():
            accepted.setdefault(origin[j], val)
    rows = []
    for idx, surface in items:
        lab = accepted.get(idx)
        rows.append({"surface_id": surface["surface_id"],
                     "label_raw": lab or rejected.get(idx, ""),
                     "label_id": None if lab in (None, "other") else lab,
                     "first_pass": 1 if idx in first else 0,
                     "attempts": 1 if idx in first else 2})
    return {"rows": rows, "secs": round(time.time() - t0, 2), "in_tok": in_tok,
            "out_tok": out_tok, "started_at": started, "finish": rep["finish"],
            "n_ok": len(accepted), "n_other": sum(1 for v in accepted.values() if v == "other"),
            "n_ok_first": len(first), "n_retried": len(rejected)}


def run(con: sqlite3.Connection, labels, items_by_batch, context_of, key, *,
        poster=call_beam, start: int = 4, ceiling: int = MAX_LIMIT, limit_batches: int = 0,
        round_no: int = 1, variant: str = "") -> dict:
    """Run every batch with no ``beam_batch`` row yet, writing as each finishes."""
    allowed = set(labels)
    done = {r["batch_id"] for r in con.execute(
        "SELECT batch_id FROM beam_batch WHERE status='done'")}
    todo = [(bid, items) for bid, items in items_by_batch if bid not in done]
    if limit_batches:
        todo = todo[:limit_batches]
    gate = Gate(start, ceiling)
    lock = threading.Lock()
    t0 = time.time()
    result = {"round": round_no, "variant": variant, "batches": len(todo),
              "skipped": len(items_by_batch) - len(todo), "surfaces": 0}

    def one(bid, items):
        try:
            out = answer_batch(labels, allowed, list(enumerate(items)), context_of,
                               poster, key, gate)
        except BillingError:
            raise
        except (GateGivenUp, RuntimeError) as exc:
            # a batch that ran out of retries stays pending for the next run
            with lock:
                con.execute(
                    "INSERT OR REPLACE INTO beam_batch VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (bid, round_no, variant, "pending", len(items), 0, 0, 0, 0, None,
                     0, 0, _now(), _now(), repr(exc)[:120]))
                con.commit()
            return 0
        with lock:
            con.execute(
                "INSERT OR REPLACE INTO beam_batch VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (bid, round_no, variant, "done", len(items), out["n_ok"], out["n_retried"],
                 out["n_other"], out["n_ok_first"], out["secs"], out["in_tok"],
                 out["out_tok"], out["started_at"], _now(), out["finish"]))
            con.executemany(
                "INSERT OR REPLACE INTO beam_answer VALUES (?,?,?,?,?,?,?,?,?)",
                [(r["surface_id"], round_no, variant, bid, r["label_raw"], r["label_id"],
                  r["first_pass"], r["attempts"], _now()) for r in out["rows"]])
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
    result.update({"elapsed_s": round(elapsed, 1), "final_limit": gate.limit,
                   "best_limit": gate.best, "n_429": gate.ratelimited,
                   "pending": con.execute("SELECT count(*) FROM beam_batch WHERE "
                                          "status='pending' AND round=?",
                                          (round_no,)).fetchone()[0],
                   "calls_per_min": round(len(todo) / elapsed * 60, 1)})
    con.execute("INSERT INTO beam_run VALUES (?,?,?,?,?,?,?,?,?)",
                (_now(), round_no, result["batches"], result["surfaces"],
                 result["elapsed_s"], result["best_limit"], result["final_limit"],
                 result["n_429"], result["calls_per_min"]))
    con.commit()
    return result


# --- apply + report ----------------------------------------------------------
def apply(con: sqlite3.Connection) -> dict:
    """Write round-1 beam answers into ``map`` (idempotent), keeping the source."""
    rows = con.execute(
        "SELECT a.surface_id, a.label_id, s.surface_verbatim FROM beam_answer a "
        "JOIN surface s USING(surface_id) WHERE a.round=1").fetchall()
    for r in rows:
        if r["label_id"]:
            con.execute("UPDATE map SET label_id=?, map_value=?, method='beam', "
                        "confidence=NULL, source='beam' WHERE surface_id=?",
                        (r["label_id"], r["label_id"], r["surface_id"]))
        else:
            con.execute("UPDATE map SET label_id=NULL, map_value=?, method='beam:other', "
                        "confidence=NULL, source='beam' WHERE surface_id=?",
                        ("other:" + r["surface_verbatim"], r["surface_id"]))
    con.commit()
    return {"updated": len(rows)}


def counts(con: sqlite3.Connection, root: Path | None = None) -> dict:
    head = json.loads(((root or data_root()) / "pilot" / "v4" / "unmapped_head.json")
                      .read_text(encoding="utf-8"))
    names = {r["surface"] for r in head}
    rows = con.execute("SELECT s.surface_verbatim, s.n_occurrences, s.source_kind, "
                       "m.label_id FROM surface s JOIN map m USING(surface_id)").fetchall()
    total = sum(r["n_occurrences"] for r in rows)
    work = [r for r in rows if r["surface_verbatim"] in names]
    labelled = sum(1 for r in work if r["label_id"])
    by_source, other_by_source = Counter(), Counter()
    for r in work:
        by_source[r["source_kind"]] += 1
        if not r["label_id"]:
            other_by_source[r["source_kind"]] += 1
    head_labelled = HEAD_LABELLED + labelled
    return {
        "surfaces": len(rows), "occurrences": total,
        "head_surfaces": HEAD_SURFACES, "head_labelled": head_labelled,
        "head_labelled_pct": round(100.0 * head_labelled / HEAD_SURFACES, 2),
        "gate_met": head_labelled / HEAD_SURFACES >= 0.95,
        "workload": len(work), "workload_labelled": labelled,
        "workload_other": len(work) - labelled,
        "workload_other_pct": round(100.0 * (len(work) - labelled) / max(1, len(work)), 2),
        "workload_labelled_occ_pct": round(
            100.0 * sum(r["n_occurrences"] for r in work if r["label_id"])
            / max(1, sum(r["n_occurrences"] for r in work)), 2),
        "workload_occurrence_pct": round(
            100.0 * sum(r["n_occurrences"] for r in work) / max(1, total), 2),
        "other_share_by_source": {k: round(100.0 * other_by_source[k] / max(1, n), 2)
                                  for k, n in sorted(by_source.items())},
        "map_source": {r[0]: r[1] for r in con.execute(
            "SELECT source, count(*) FROM map GROUP BY 1")},
    }


def agreement(con: sqlite3.Connection) -> dict:
    """Round-2 A vs B: how often the mapper repeats itself in a different batch."""
    a = {r["surface_id"]: r["label_id"] or "other" for r in con.execute(
        "SELECT surface_id, label_id FROM beam_answer WHERE round=2 AND variant='A'")}
    b = {r["surface_id"]: r["label_id"] or "other" for r in con.execute(
        "SELECT surface_id, label_id FROM beam_answer WHERE round=2 AND variant='B'")}
    both = sorted(set(a) & set(b))
    det = {r["surface_id"]: r["label_id"] or "other" for r in con.execute(
        "SELECT surface_id, label_id FROM map WHERE source='deterministic'")
    } if both else {}
    text = {r["surface_id"]: r["surface_verbatim"] for r in con.execute(
        "SELECT surface_id, surface_verbatim FROM surface")}
    overlap = [sid for sid in both if sid in det]
    return {"n": len(both),
            "agree": sum(1 for sid in both if a[sid] == b[sid]),
            "agreement_pct": round(100.0 * sum(1 for sid in both if a[sid] == b[sid])
                                   / max(1, len(both)), 2),
            "vs_deterministic_n": len(overlap),
            "vs_deterministic_agree": sum(1 for sid in overlap if det[sid] == a[sid]),
            "disagreements": [{"surface_id": sid, "surface": text.get(sid, "")[:60],
                               "a": a[sid], "b": b[sid]}
                              for sid in both if a[sid] != b[sid]][:40]}


def sample_rows(con: sqlite3.Connection, n: int = SAMPLE_N, seed: int = SEED + 1) -> list[dict]:
    """Stratified by source kind and occurrence band, over the beam mappings."""
    rows = [dict(r) for r in con.execute(
        "SELECT s.surface_id, s.surface_verbatim, s.n_occurrences, s.source_kind, "
        "s.n_isins, m.label_id, c.ctx1, c.ctx2 FROM surface s JOIN map m USING(surface_id) "
        "LEFT JOIN beam_context c USING(surface_id) WHERE m.source='beam'")]
    band = lambda k: 0 if k >= 100 else (1 if k >= 10 else 2)
    strata: dict[tuple, list] = defaultdict(list)
    for r in rows:
        strata[(r["source_kind"], band(r["n_occurrences"]))].append(r)
    rng = random.Random(seed)
    picked: list[dict] = []
    for key in sorted(strata):
        group = strata[key]
        share = max(1, round(n * len(group) / max(1, len(rows))))
        picked += rng.sample(group, min(share, len(group)))
    rng.shuffle(picked)
    return picked[:n]


def _median(values) -> float:
    values = sorted(v for v in values if v)
    return values[len(values) // 2] if values else 0.0


def _min(values) -> float:
    values = [v for v in values if v is not None]
    return min(values) if values else 0.0


def _max(values) -> float:
    values = [v for v in values if v is not None]
    return max(values) if values else 0.0


def _rate(batches: list[dict]) -> float:
    """Round-1 batches per minute over their own start/finish span."""
    span = [b for b in batches if b["round"] == 1 and b["finished_at"]]
    if not span:
        return 0.0
    t0 = min(b["started_at"] for b in span)
    t1 = max(b["finished_at"] for b in span)
    fmt = "%Y-%m-%dT%H:%M:%S%z"
    try:
        secs = (datetime.strptime(t1, fmt) - datetime.strptime(t0, fmt)).total_seconds()
    except ValueError:
        return 0.0
    return len(span) / max(secs / 60.0, 0.01)


def write_reports(con: sqlite3.Connection, out_dir: Path, root: Path | None = None) -> dict:
    stats = counts(con, root)
    agree = agreement(con)
    batches = [dict(r) for r in con.execute("SELECT * FROM beam_batch ORDER BY batch_id")]
    runs = [dict(r) for r in con.execute("SELECT * FROM beam_run ORDER BY run_at")]
    families = {r["label_id"]: r["parent_id"] for r in con.execute(
        "SELECT label_id, parent_id FROM label WHERE level=2")}
    used = Counter(r[0] for r in con.execute(
        "SELECT label_id FROM map WHERE source='beam' AND label_id IS NOT NULL"))
    sample = sample_rows(con)
    lines = [
        "# VOCAB_PASS2 — the head surfaces labelled by free Beam",
        "",
        f"Generated {_now()} by `python -m reality_engine.query.v4.map_vocab_beam`; model "
        f"`{MODEL}` (free) on OpenCode Go. The store is `.tmp/v4_vocab_pass2.db`, a copy of "
        "the WP2b vocabulary with `map.source` (deterministic | beam) on every row.",
        "",
        "**Install (controller):** back up the pilot store, then copy this file over "
        "`reality_engine/data/pilot/v4/v4_vocab.db`. Everything downstream reads `map`, "
        "which keeps its old values for deterministic rows and carries the Beam answer "
        "plus `source='beam'` for the rest. No other table changed shape except the one "
        "added column.",
        "",
        "## 1. The gate (§A.9 option b)",
        "",
        "| measured | value |",
        "|---|---:|",
        f"| head surfaces (the declared 95% of occurrences) | {stats['head_surfaces']:,} |",
        f"| named by the deterministic pass | {HEAD_LABELLED:,} (59.43%) |",
        f"| sent to Beam (this pass) | {stats['workload']:,} |",
        f"| Beam answered with an exact label | {stats['workload_labelled']:,} "
        f"({100 - stats['workload_other_pct']:.2f}% of the workload) |",
        f"| Beam answered `other:<raw>` | {stats['workload_other']:,} "
        f"({stats['workload_other_pct']:.2f}%) |",
        f"| **head surfaces carrying an exact label** | **{stats['head_labelled']:,} / "
        f"{stats['head_surfaces']:,} = {stats['head_labelled_pct']:.2f}%** |",
        f"| gate (>= 95% exact labels) | **{'MET' if stats['gate_met'] else 'NOT MET'}** |",
        f"| workload share of occurrences | {stats['workload_occurrence_pct']:.2f}% |",
        f"| workload **occurrences** now carrying an exact label | "
        f"{stats['workload_labelled_occ_pct']:.2f}% |",
        "",
        "Head membership note: sorting the store by occurrences puts the 95% cut inside "
        "the 22,782 surfaces that occur exactly twice, so which of them are \"in the "
        "head\" is a tie-break artefact. `unmapped_head.json` (the WP2b dump this pass "
        "consumes) puts **all 7,430 unmapped twice-occurring surfaces** in the head and "
        "fills the rest with labelled ones, which is the largest workload and gives the "
        "62,601 / 37,204 / 25,397 split in the brief. A different tie order gives the "
        "same 62,601 total and the same gate arithmetic, because the surfaces it swaps "
        "are already labelled. `1,815,581` occurrences is the corrected figure "
        "(`VOCAB_PASS1.md` §1, corrected here).",
        "",
        "The `other:<raw>` share per document type inside the workload:",
        "",
        "| document type | Beam `other` share |",
        "|---|---:|",
    ]
    lines += [f"| {k} | {v:.2f}% |" for k, v in stats["other_share_by_source"].items()]
    lines += [
        "",
        "## 1b. Why the head gate is not met — what the `other` surfaces actually are",
        "",
        "The dataset's most frequent unmapped surfaces are not metrics at all; they are "
        "extractor buckets and section headings, so `other` is the correct answer:",
        "",
        "| surface | occurrences | document type |",
        "|---|---:|---|",
    ]
    lines += [f"| `{r['surface_verbatim'][:60]}` | {r['n_occurrences']:,} | {r['source_kind']} |"
              for r in con.execute(
                  "SELECT s.surface_verbatim, s.n_occurrences, s.source_kind FROM surface s "
                  "JOIN map m USING(surface_id) WHERE m.label_id IS NULL "
                  "ORDER BY s.n_occurrences DESC LIMIT 20")]
    lines += [
        "",
        "To reach 95% of the 62,601 head surfaces, 15,727 of the 18,857 remaining `other` "
        "surfaces would each have to take a declared label. They are, by document type, "
        "annual-report/BRSR section headings (`Company Profile`, `Data breach`, "
        "`ESG-climate`, `NGRBC principle-wise performance`), presentation line labels "
        "(`Area Booked`, `Others`, `Aerial View`) and extractor buckets (`signal`, "
        "`market_data`, `ratio`). No declared topic names them, so the fix is vocabulary "
        "**promotion**, not a better mapper: the promotion queue is the "
        "`other_cluster` table inherited from the WP2b pass (26,261 clusters, 173 queued "
        "at >=20 occurrences / >=3 companies / >=2 doc types), and it has to be "
        "re-clustered against this store after install because the `other` set shrank.",
        "",
        "## 2. Calls and throughput",
        "",
        "| measured | value |",
        "|---|---:|",
        f"| batches (round 1 / round 2A / round 2B) | "
        f"{sum(1 for b in batches if b['round'] == 1)} / "
        f"{sum(1 for b in batches if b['round'] == 2 and b['variant'] == 'A')} / "
        f"{sum(1 for b in batches if b['round'] == 2 and b['variant'] == 'B')} |",
        f"| surfaces mapped (round 1 / round 2) | "
        f"{sum(b['n_surfaces'] for b in batches if b['round'] == 1):,} / "
        f"{sum(b['n_surfaces'] for b in batches if b['round'] == 2):,} |",
        f"| answers accepted on the first ask | "
        f"{sum(b['n_ok_first'] for b in batches):,} / "
        f"{sum(b['n_surfaces'] for b in batches):,} |",
        f"| first-answer rejects, retried once | {sum(b['n_retried'] for b in batches):,} |",
        f"| tokens in / out | {sum(b['in_tok'] or 0 for b in batches):,} / "
        f"{sum(b['out_tok'] or 0 for b in batches):,} |",
        f"| batch wall time: min / median / max | "
        f"{_min(b['secs'] for b in batches):.1f} / "
        f"{_median(b['secs'] for b in batches):.1f} / "
        f"{_max(b['secs'] for b in batches):.1f} s |",
        f"| sustained throughput, round 1 | {_rate(batches):.1f} batches/min |",
        f"| 429s (in runs that completed) | {sum(r['n_429'] or 0 for r in runs)} |",
        "",
        "**How the ceiling was measured.** Concurrency is not fixed: the gate starts "
        "at the value passed on the command line, doubles after every 20 clean calls and "
        "halves on every 429, never returning to a level that 429'd. What the provider "
        "did, measured: it throttled by **slowness first** — the first 100 s ran 57 "
        "batches at limit 4 (~34 batches/min, 6 s each), then batch wall time grew to "
        "20-360 s for the same 50 phrases with the same token counts, so the run "
        "settled near 10 batches/min and no 429 appeared for 495 batches. It then "
        "rate-limited with an HTTP 429 `Upstream request failed: Rate limit exceeded` "
        "and one such 429 used to end the run; a 429 now lowers the limit, backs off "
        "and retries six times before leaving that batch pending for the next run, so "
        "the finish and the agreement round ran with zero 429s at limit 2. The honest "
        "ceiling on this account tonight is *not* a concurrency number: it is the "
        "provider's queue, and the measured output is thousands of phrases an hour.",
        "Every call is written to `tasks/ledgers/spend.jsonl` at $0 through "
        "`cost_ledger.record_usage`.",
        "",
        "## 3. Agreement (500 head surfaces mapped twice, different batches)",
        "",
        f"- pairs with both answers: **{agree['n']}**; identical label: "
        f"**{agree['agree']}** -> **{agree['agreement_pct']:.2f}% agreement**",
        f"- of those already labelled deterministically ({agree['vs_deterministic_n']}), "
        f"Beam's label equals the deterministic label on "
        f"{agree['vs_deterministic_agree']}",
        f"- read honestly: {100 - agree['agreement_pct']:.1f}% of these surfaces were "
        "labelled differently by the same model in a different batch, so a single Beam "
        "label on an ambiguous phrase is not reproducible. That is the reason the "
        "conservative prompt answers `other` when two labels are defensible.",
        "",
        "## 4. The labels Beam used",
        "",
        "| label | family | surfaces |",
        "|---|---|---:|",
    ]
    lines += [f"| {lab} | {families.get(lab, '-')} | {n:,} |"
              for lab, n in used.most_common(30)]
    lines += ["", "## 5. Hand check", "",
              f"A stratified sample of {len(sample)} Beam mappings is in "
              "`vocab_pass2_sample.md`. Precision is **not** asserted here; the hand "
              "check is the controller's, and the worker's own reading is reported "
              "separately in that file.", ""]
    if agree["disagreements"]:
        lines += ["## 6. Round-2 disagreements (first 40)", "",
                  "Same surface, same model, a different batch: the label changed.", "",
                  "| surface | batch A | batch B |", "|---|---|---|"]
        lines += [f"| `{d['surface']}` | {d['a']} | {d['b']} |"
                  for d in agree["disagreements"]]
        lines.append("")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "VOCAB_PASS2.md").write_text("\n".join(lines), encoding="utf-8")

    def band(k):
        return ">=100" if k >= 100 else ("10-99" if k >= 10 else "2-9")
    rows = ["# vocab_pass2_sample — 100 Beam mappings for the hand check", "",
            "Stratified by document type and occurrence band (>=100 / 10-99 / 2-9). "
            "`beam label` is what the model answered; `hand check` is the controller's "
            "column (✓ exact / ~ family-only / ✗ wrong); `worker reading` is this "
            "worker's opinion, not a pass.", "",
            "| # | surface (verbatim) | doc | occ | contexts | beam label | hand check | "
            "worker reading |", "|---:|---|---|---:|---|---|---|---|"]
    for i, r in enumerate(sample, 1):
        ctx = " || ".join(c for c in (r.get("ctx1"), r.get("ctx2")) if c)
        ctx = ctx.replace("|", "/")[:220]
        rows.append(f"| {i} | `{r['surface_verbatim'][:70]}` | {r['source_kind']} | "
                    f"{r['n_occurrences']} ({band(r['n_occurrences'])}) | {ctx} | "
                    f"{r['label_id'] or 'other'} | | |")
    # the worker's reading of the sample is hand-written: keep it across regenerations
    sample_path = out_dir / "vocab_pass2_sample.md"
    kept = ""
    if sample_path.exists():
        old = sample_path.read_text(encoding="utf-8")
        if "## Worker reading" in old:
            kept = old.split("## Worker reading", 1)[1].strip("\n")
    rows += ["", "## Worker reading", "",
             kept or ("Written by the worker after reading the table above. It is an "
                      "opinion, not the hand check."), ""]
    sample_path.write_text("\n".join(rows), encoding="utf-8")
    return {"stats": stats, "agreement": {k: v for k, v in agree.items()
                                          if k != "disagreements"},
            "sample": len(sample)}


# --- cli ---------------------------------------------------------------------
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--out", type=Path, default=Path(".tmp/v4_vocab_pass2.db"))
    ap.add_argument("--vocab", type=Path, default=None)
    ap.add_argument("--unmapped", type=Path, default=None)
    ap.add_argument("--limit-batches", type=int, default=0, help="stop after N new batches")
    ap.add_argument("--start", type=int, default=4, help="initial concurrency")
    ap.add_argument("--ceiling", type=int, default=MAX_LIMIT)
    ap.add_argument("--agreement", action="store_true", help="also run the round-2 check")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--report", action="store_true")
    args = ap.parse_args(argv)
    root = data_root()
    vocab = args.vocab or root / "pilot" / "v4" / "v4_vocab.db"
    unmapped = args.unmapped or root / "pilot" / "v4" / "unmapped_head.json"
    con = open_pass2(args.out, vocab)

    if args.status:
        print(json.dumps({"counts": counts(con, root), "agreement": agreement(con)},
                         indent=1))
        return 0
    if args.report:
        print(json.dumps(write_reports(con, ROOT / "tasks" / "arch_v4", root), indent=1))
        return 0

    key = next((os.environ[e] for e in KEY_ENVS if os.environ.get(e)), "")
    if not key:
        print("no OPENCODE_GO_API_KEY_2 / OPENCODE_GO_API_KEY in the environment",
              file=sys.stderr)
        return 2
    labels = labels_of(con)
    rows = workload(con, unmapped)
    ctx = ensure_contexts(con, root, rows)
    print(json.dumps({"workload": len(rows), "labels": len(labels),
                      "with_context": sum(1 for r in rows if ctx.get(r["surface_id"]))},
                     indent=1))
    summary: dict = {}
    try:
        summary["round1"] = run(con, labels, plan(rows), ctx, key, start=args.start,
                                ceiling=args.ceiling, limit_batches=args.limit_batches)
        if args.agreement:
            a, b = plan_agreement(head_surfaces(con))
            summary["round2a"] = run(con, labels, a, {}, key, start=args.start,
                                     ceiling=args.ceiling, round_no=2, variant="A",
                                     limit_batches=args.limit_batches)
            summary["round2b"] = run(con, labels, b, {}, key, start=args.start,
                                     ceiling=args.ceiling, round_no=2, variant="B",
                                     limit_batches=args.limit_batches)
    except BillingError as exc:
        print(json.dumps({"error": "billing", "detail": str(exc), **summary}, indent=1))
        print("STOPPING: beam-free is no longer free.", file=sys.stderr)
        return 3
    except KeyboardInterrupt:
        print(json.dumps({"error": "interrupted", **summary}, indent=1))
        return 130
    summary["applied"] = apply(con)
    summary["counts"] = counts(con, root)
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
