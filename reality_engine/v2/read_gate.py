"""T-241 (Shivam, 24 Nov 2026): maker-checker-verifier gate for bulk model reading (hy4 observations).

maker = the reader model; checker = the row_checks script layer; verifier = an independent hand read.

1. Before a run of more than ``PILOT_PAGES`` pages, every doc type read needs a gate entry for the CURRENT reader
   fingerprint (sha256 of the prompt template + reader id): either ``verdict: pass`` from a reviewer who is not the
   prompt's author, or an ``override`` by Shivam with a reason.  Changing the prompt changes the fingerprint, so an
   old pass no longer counts (rule 3: new instructions go through the same gate).
2. During a run, each ``CHECKPOINT_PAGES`` pages read into an output DB (counted in its ``page_read`` ledger) write
   a seeded sample of ``SAMPLE_ROWS`` rows to ``<out>.audit/ckpt_NNNN.jsonl``.  A later run on that DB refuses to
   start while any checkpoint has no grade file or a failed one, so a failed audit stops the reading.
3. Coverage: ``python -m reality_engine.v2.read_gate status --out <db>`` prints the ledger counts; job_watch's hy4
   entry flags a stall when they stop growing.

Gate entries live in ``reality_engine/v2/read_gates.json`` (tracked in git, so every pass and override is on
record).  CLI: ``status``, ``record`` (a reviewer's verdict), ``override`` (Shivam only), ``grade`` (a checkpoint).
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import random
import sqlite3
import sys
from pathlib import Path
from typing import Any

PILOT_PAGES = 200
CHECKPOINT_PAGES = 2000
SAMPLE_ROWS = 60
GATE_FILE = Path(__file__).with_name("read_gates.json")


class GateError(RuntimeError):
    """A bulk read is not allowed: no passing audit, or an ungraded/failed checkpoint."""


def _now() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M")


def fingerprint(doc_type: str) -> str:
    """The reader's identity for ``doc_type``: its prompt template and reader id (12 hex chars)."""
    from reality_engine.v2 import observations as obs

    template = obs.template_for(doc_type)
    return hashlib.sha256(f"{obs.OBS_READER}\n{template}".encode("utf-8")).hexdigest()[:12]


def load(path: Path | None = None) -> list[dict[str, Any]]:
    path = path or GATE_FILE
    if not path.is_file():
        return []
    return list(json.loads(path.read_text(encoding="utf-8")).get("gates") or [])


def save(entries: list[dict[str, Any]], path: Path | None = None) -> None:
    path = path or GATE_FILE
    path.write_text(json.dumps({"gates": entries}, indent=1) + "\n", encoding="utf-8")


def allowed(doc_type: str, fp: str, entries: list[dict[str, Any]], out: str | Path = "") -> dict[str, Any] | None:
    """The latest entry that allows ``doc_type`` at fingerprint ``fp`` for output ``out`` (None when none does).

    An override may carry ``scope``: a substring the output DB path must contain (e.g. one run's file)."""
    ok = None
    for e in entries:
        if e.get("doc_type") != doc_type or e.get("fingerprint") != fp:
            continue
        if e.get("verdict") == "pass" and e.get("reviewer") and e.get("reviewer") != e.get("author"):
            ok = e
        elif e.get("verdict") == "override" and str(e.get("by") or "").lower() == "shivam" and e.get("reason") \
                and e.get("quote"):
            if str(e.get("scope") or "") in Path(str(out)).as_posix():
                ok = e
        elif e.get("verdict") == "fail":
            ok = None                       # a later fail withdraws an earlier pass
    return ok


def audit_dir(out: str | Path) -> Path:
    return Path(f"{out}.audit")


def pending_checkpoints(out: str | Path) -> list[str]:
    """Checkpoint samples with no grade, or a failed grade."""
    d = audit_dir(out)
    bad = []
    for sample in sorted(d.glob("ckpt_*.jsonl")) if d.is_dir() else []:
        grade = sample.with_suffix(".grade.json")
        if not grade.is_file():
            bad.append(f"{sample.name}: not graded")
            continue
        verdict = json.loads(grade.read_text(encoding="utf-8")).get("verdict")
        if verdict != "pass":
            bad.append(f"{sample.name}: {verdict}")
    return bad


def check(doc_types: list[str], pages: int, out: str | Path, gate_file: Path | None = None) -> None:
    """Raise GateError unless this run may start (see the module docstring)."""
    bad = pending_checkpoints(out)
    if bad:
        raise GateError(f"audit checkpoints of {out} need a passing grade first: {'; '.join(bad)} "
                        f"(python -m reality_engine.v2.read_gate grade ...)")
    done = _ledger_count(out)
    if done + pages <= PILOT_PAGES:     # the pilot allowance is per output DB, so chunked runs cannot dodge it
        return
    pages = done + pages
    entries = load(gate_file)
    for doc_type in doc_types:
        fp = fingerprint(doc_type)
        if allowed(doc_type, fp, entries, out) is None:
            raise GateError(f"no passing independent audit for doc type {doc_type!r} at reader fingerprint {fp}; "
                            f"a bulk run of {pages} pages needs one (hand-read >= {SAMPLE_ROWS} seeded rows, "
                            f"then read_gate record), or Shivam's override")


def _ledger_count(out: str | Path) -> int:
    """Pages already in ``out``'s page_read ledger (0 when the DB or table does not exist yet)."""
    path = Path(str(out))
    if str(out) == ":memory:" or not path.is_file():
        return 0
    try:
        con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=30)
        try:
            return int(con.execute("SELECT COUNT(*) FROM page_read").fetchone()[0])
        finally:
            con.close()
    except sqlite3.Error:
        return 0


def _pages_read(con: sqlite3.Connection) -> int:
    return int(con.execute("SELECT COUNT(*) FROM page_read").fetchone()[0])


def maybe_checkpoint(con: sqlite3.Connection, out: str | Path, seed: int = 241) -> Path | None:
    """Write the next audit sample when the ledger has crossed another CHECKPOINT_PAGES pages."""
    if str(out) == ":memory:":
        return None
    n = _pages_read(con)
    k = n // CHECKPOINT_PAGES
    if k < 1:
        return None
    d = audit_dir(out)
    sample = d / f"ckpt_{k:04d}.jsonl"
    if sample.is_file():
        return None
    d.mkdir(parents=True, exist_ok=True)
    pages = con.execute("SELECT doc_key, page FROM page_read WHERE outcome='rows' ORDER BY read_at DESC LIMIT ?",
                        (CHECKPOINT_PAGES,)).fetchall()
    keys = {(str(a), int(b)) for a, b in pages}
    rows = [r for r in con.execute("SELECT observation_id, symbol, doc_key, page, record_type, measure, "
                                   "printed_label, value, value_high, value_text, unit, scale, period, period_source, "
                                   "basis, statement, speaker, status, status_reason FROM observation WHERE status != 'quarantined'")
            if (str(r[2]), int(r[3])) in keys]
    cols = ["observation_id", "symbol", "doc_key", "page", "record_type", "measure", "printed_label", "value",
            "value_high", "value_text", "unit", "scale", "period", "period_source", "basis", "statement", "speaker",
            "status", "status_reason"]
    pick = random.Random(seed + k).sample(rows, min(SAMPLE_ROWS, len(rows)))
    with sample.open("w", encoding="utf-8") as fh:
        for r in pick:
            fh.write(json.dumps(dict(zip(cols, r)), ensure_ascii=False) + "\n")
    print(f"AUDIT: checkpoint {sample} ({len(pick)} rows, {n} pages read) - grade it before the next run",
          file=sys.stderr)
    return sample


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    st = sub.add_parser("status")
    st.add_argument("--out", action="append", default=[])
    rec = sub.add_parser("record")
    rec.add_argument("--doc-type", required=True)
    rec.add_argument("--verdict", choices=["pass", "fail"], required=True)
    rec.add_argument("--reviewer", required=True)
    rec.add_argument("--author", required=True, help="who wrote the reader prompt being judged")
    rec.add_argument("--evidence", required=True, help="graded sample file (>= 60 rows) or report")
    rec.add_argument("--rows", type=int, required=True)
    rec.add_argument("--note", default="")
    ov = sub.add_parser("override")
    ov.add_argument("--doc-type", required=True)
    ov.add_argument("--by", required=True)
    ov.add_argument("--reason", required=True)
    ov.add_argument("--quote", required=True, help="Shivam's own words and the time he gave them (for audit)")
    ov.add_argument("--scope", default="", help="only output DBs whose path contains this text")
    gr = sub.add_parser("grade")
    gr.add_argument("--ckpt", required=True)
    gr.add_argument("--verdict", choices=["pass", "fail"], required=True)
    gr.add_argument("--reviewer", required=True)
    gr.add_argument("--counts", default="", help="right/partial/wrong/junk, e.g. 40/12/5/3")
    gr.add_argument("--note", default="")
    a = ap.parse_args(argv)
    entries = load()
    if a.cmd == "status":
        for doc_type in ("transcript", "deck", "annual_report", "results"):
            e = allowed(doc_type, fingerprint(doc_type), entries)
            print(f"{doc_type:14s} fp={fingerprint(doc_type)} -> "
                  f"{(e or {}).get('verdict', 'BLOCKED')} {(e or {}).get('reviewer') or (e or {}).get('by') or ''}")
        for out in a.out:
            print(f"{out}: pending {pending_checkpoints(out) or 'none'}")
            try:
                con = sqlite3.connect(f"file:{Path(out).as_posix()}?mode=ro", uri=True, timeout=5)
                print("  page_read", dict(con.execute("SELECT outcome, COUNT(*) FROM page_read GROUP BY 1")))
                con.close()
            except sqlite3.Error as exc:
                print(f"  page_read unreadable: {exc}")
        return 0
    if a.cmd == "record":
        if a.reviewer.strip().lower() == a.author.strip().lower():
            print("REFUSED: the reviewer may not be the prompt's author", file=sys.stderr)
            return 2
        if a.verdict == "pass" and a.rows < SAMPLE_ROWS:
            print(f"REFUSED: a pass needs >= {SAMPLE_ROWS} hand-read rows", file=sys.stderr)
            return 2
        entries.append({"doc_type": a.doc_type, "fingerprint": fingerprint(a.doc_type), "verdict": a.verdict,
                        "reviewer": a.reviewer, "author": a.author, "rows": a.rows, "evidence": a.evidence,
                        "note": a.note, "at": _now()})
    elif a.cmd == "override":
        if a.by.strip().lower() != "shivam":
            print("REFUSED: only Shivam overrides the gate", file=sys.stderr)
            return 2
        entries.append({"doc_type": a.doc_type, "fingerprint": fingerprint(a.doc_type), "verdict": "override",
                        "by": a.by, "reason": a.reason, "quote": a.quote, "scope": a.scope,
                        "at": _now()})
    elif a.cmd == "grade":
        sample = Path(a.ckpt)
        if not sample.is_file():
            print(f"REFUSED: no checkpoint {sample}", file=sys.stderr)
            return 2
        sample.with_suffix(".grade.json").write_text(json.dumps(
            {"verdict": a.verdict, "reviewer": a.reviewer, "counts": a.counts, "note": a.note, "at": _now()},
            indent=1), encoding="utf-8")
        print(f"graded {sample.name}: {a.verdict}")
        return 0
    save(entries)
    print(f"recorded {a.cmd} for {a.doc_type}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
