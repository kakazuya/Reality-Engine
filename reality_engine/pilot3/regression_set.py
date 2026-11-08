"""Frozen hand-labelled regression set for the pilot3 extractors and row checker (T-122).

Every extractor or checker change re-scores the rows Opus hand-read on 7-8 Nov 2026 across every company read so
far (pilot10, unseen6, hold6, fresh6).  A row he read as right must never become quarantined; a row he read as
wrong must never become verified.  Row ids change on every rebuild, so a label keys on content:

    (table, symbol, metric, dimension, period, basis, value, high, unit, doc_key, page, first 80 chars of the
     squashed quote)

``tasks/regression/labels.csv`` is the frozen set: one row per hand-read row with its label (right / partly /
wrong) and the note's reason.  A new hand read appends to it; no script rewrites an old label.

Score one set against a built database and its verdict database::

    python -m reality_engine.pilot3.regression_set score --label tasks/regression/labels.csv \\
        --set hold6 --db <hold6.db> --rc <rc_hold6.db>

Score the four sets (rebuilding each verdict database with ``row_checks`` first), which is the pre-merge gate::

    python -m reality_engine.pilot3.regression_set score --all

Exit code 1 on any FAIL (a right row now quarantined, a wrong row now verified).  WARN does not fail the run:
a partly row now verified, a labelled row no longer found (an extractor change dropped it: still a regression to
look at), a row with no verdict.  Read-only on the source database; the verdict database is written under
``.tmp/regression/``.
"""
from __future__ import annotations

import argparse
import csv
import math
import os
import sqlite3
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from reality_engine.pilot3 import row_checks

DEFAULT_LABELS = Path("tasks/regression/labels.csv")
OUT_DIR = Path(".tmp/regression")
LABEL_VALUES = ("right", "partly", "wrong")
SET_NAMES = ("pilot10", "unseen6", "hold6", "fresh6")

# The eight-November hold-out builds, one per set.  The evaluation stores live in the reader's scratch directory;
# point T122_DB_<SET> / T122_PROFILE_<SET> at the current copies when they move.
SETS: dict[str, dict[str, str]] = {
    "pilot10": {"db": r"D:\RealityEngine\pilot10\pilot10.db",
                "profile": "tasks/night_loop/pilot10_profile.json"},
    "unseen6": {"db": r"C:\Users\warri\AppData\Local\Temp\claude\12b5f02fd3b7ce95\fa93aa0b-0c04-408d-a8f4-f7630af29fed\scratchpad\ho\u6_eval.db",
                "profile": r"C:\Users\warri\AppData\Local\Temp\claude\12b5f02fd3b7ce95\fa93aa0b-0c04-408d-a8f4-f7630af29fed\scratchpad\ho\unseen6_profile.json"},
    "hold6": {"db": r"C:\Users\warri\AppData\Local\Temp\claude\12b5f02fd3b7ce95\fa93aa0b-0c04-408d-a8f4-f7630af29fed\scratchpad\ho\h6_eval.db",
              "profile": r"C:\Users\warri\AppData\Local\Temp\claude\12b5f02fd3b7ce95\fa93aa0b-0c04-408d-a8f4-f7630af29fed\scratchpad\ho\hold6_profile.json"},
    "fresh6": {"db": r"C:\Users\warri\AppData\Local\Temp\claude\12b5f02fd3b7ce95\fa93aa0b-0c04-408d-a8f4-f7630af29fed\scratchpad\fresh6\fresh6.db",
               "profile": r"C:\Users\warri\AppData\Local\Temp\claude\12b5f02fd3b7ce95\fa93aa0b-0c04-408d-a8f4-f7630af29fed\scratchpad\fresh6\fresh6_profile.json"},
}


def set_paths(name: str) -> tuple[str, str]:
    """(db, profile) for a set, with the T122_DB_<SET> / T122_PROFILE_<SET> overrides."""
    env = name.upper()
    spec = SETS[name]
    return os.environ.get(f"T122_DB_{env}", spec["db"]), os.environ.get(f"T122_PROFILE_{env}", spec["profile"])


@dataclass(frozen=True)
class Label:
    set: str
    table: str
    symbol: str
    metric: str
    dimension: str
    period: str
    basis: str
    value: str
    high: str
    unit: str
    doc_key: str
    page: str
    quote80: str
    label: str
    reason: str = ""
    source: str = ""


@dataclass
class SetResult:
    set: str
    db: str
    rc: str
    labels: int = 0
    fail: int = 0
    warn: int = 0
    ok: int = 0
    not_found: int = 0
    by_company: dict[str, dict[str, int]] = field(default_factory=dict)
    lines: list[str] = field(default_factory=list)


def load_labels(path: Path = DEFAULT_LABELS) -> list[Label]:
    with Path(path).open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        raise SystemExit(f"{path}: no labels")
    missing = {"table", "label"} - set(rows[0])
    if missing:
        raise SystemExit(f"{path}: missing columns {sorted(missing)}")
    out = []
    for r in rows:
        if r["label"] not in LABEL_VALUES:
            raise SystemExit(f"{path}: unknown label {r['label']!r} for {r['symbol']} {r['metric']}")
        out.append(Label(set=r["set"], table=r["table"], symbol=r["symbol"], metric=r["metric"],
                         dimension=r.get("dimension", ""), period=r.get("period", ""),
                         basis=r.get("basis", ""), value=r.get("value", ""), high=r.get("high", ""),
                         unit=r.get("unit", ""), doc_key=r.get("doc_key", ""), page=r.get("page", ""),
                         quote80=r.get("quote80", ""), label=r["label"],
                         reason=r.get("reason", ""), source=r.get("source", "")))
    return out


def _close(a: float, b: float) -> bool:
    return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-9)


def _row_matches(row: dict, lab: Label) -> bool:
    squashed = row_checks.squash(row.get("quote") or "")[:80]
    if squashed != lab.quote80:
        return False
    if lab.doc_key and (row.get("doc_key") or "") != lab.doc_key:
        return False
    if lab.page and str(row.get("page") if row.get("page") is not None else "") != lab.page:
        return False
    if not lab.value:
        return False
    if lab.table == "guidance":
        if not _close(float(row["low"] or 0.0), float(lab.value)):
            return False
        high = None if not lab.high else float(lab.high)
        return (row.get("high") is None and high is None) or (
            row.get("high") is not None and high is not None and _close(float(row["high"]), high))
    if (row.get("dimension") or "") != lab.dimension or (row.get("basis") or "") != lab.basis:
        return False
    return _close(float(row["value"]), float(lab.value))


def find_rows(con: sqlite3.Connection, lab: Label) -> list[dict]:
    """Source rows whose content key equals the label's. Ids are deliberately not used."""
    con.row_factory = sqlite3.Row
    period_col = "target_period" if lab.table == "guidance" else "fiscal_period"
    sql = f"SELECT * FROM {lab.table} WHERE symbol=? AND metric=? AND {period_col}=? AND unit IS ?"
    rows = [dict(r) for r in con.execute(sql, (lab.symbol, lab.metric, lab.period, lab.unit))]
    return [r for r in rows if _row_matches(r, lab)]


def _open(path: str) -> sqlite3.Connection:
    """row_checks builds a file: URI from the path, so Windows backslashes must go."""
    return row_checks.connect_readonly(Path(path).as_posix())


def score_set(labels: list[Label], db: str, rc: str, name: str) -> SetResult:
    """Join each label to its verdict by content: right->quarantined and wrong->verified are FAIL."""
    res = SetResult(set=name, db=db, rc=rc)
    con_db = _open(db)
    con_rc = _open(rc)
    try:
        verdict = {(r[0], r[1]): r[2] for r in con_rc.execute("SELECT tbl, row_id, status FROM row_check")}
        for lab in labels:
            if lab.set != name:
                continue
            res.labels += 1
            comp = res.by_company.setdefault(lab.symbol, {"labels": 0, "fail": 0, "warn": 0, "ok": 0})
            comp["labels"] += 1
            found = find_rows(con_db, lab)
            if not found:
                res.not_found += 1
                res.warn += 1
                comp["warn"] += 1
                res.lines.append(f"WARN not-found      {name} {lab.symbol} {lab.metric} {lab.period} "
                                 f"label={lab.label} ({lab.source})")
                continue
            statuses = [verdict.get((lab.table, r["id"]), "no-verdict") for r in found]
            ids = [r["id"] for r in found]
            bad = None
            if lab.label == "right" and "quarantined" in statuses:
                bad = "FAIL right-row-quarantined"
            elif lab.label == "wrong" and "verified" in statuses:
                bad = "FAIL wrong-row-verified"
            elif lab.label == "partly" and "verified" in statuses:
                bad = "WARN partly-row-verified"
            elif "no-verdict" in statuses:
                bad = "WARN no-verdict"
            if bad is None:
                res.ok += 1
                comp["ok"] += 1
                continue
            if bad.startswith("FAIL"):
                res.fail += 1
                comp["fail"] += 1
            else:
                res.warn += 1
                comp["warn"] += 1
            res.lines.append(f"{bad:<24} {name} {lab.symbol} {lab.metric} {lab.period} ids={ids} "
                             f"status={statuses} label={lab.label} ({lab.reason or lab.source})")
    finally:
        con_db.close()
        con_rc.close()
    return res


def _print_result(res: SetResult) -> None:
    print(f"\n== {res.set}  db={res.db}")
    print(f"   rc={res.rc}")
    print(f"   labels {res.labels}  FAIL {res.fail}  WARN {res.warn}  ok {res.ok}  not-found {res.not_found}")
    for line in res.lines:
        print("   " + line)
    if res.by_company:
        print(f"   {'company':<14} labels fail warn ok")
        for sym in sorted(res.by_company):
            c = res.by_company[sym]
            print(f"   {sym:<14} {c['labels']:>6} {c['fail']:>4} {c['warn']:>4} {c['ok']:>3}")


def run_all(labels: list[Label], out_dir: Path = OUT_DIR) -> list[SetResult]:
    """Rebuild each set's verdict database with the current checker, then score the frozen labels."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for name in SET_NAMES:
        db, profile = set_paths(name)
        if not Path(db).exists():
            res = SetResult(set=name, db=db, rc="")
            res.lines.append(f"FAIL set-unavailable  {name}: no database at {db} "
                             f"(set T122_DB_{name.upper()})")
            res.fail += 1
            results.append(res)
            continue
        rc = out_dir / f"rc_{name}.db"
        row_checks.run(Path(db).as_posix(), str(rc), profile if Path(profile).exists() else None,
                       ("guidance", "kpi_series"))
        results.append(score_set(labels, db, str(rc), name))
    return results


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("command", nargs="?", choices=["score"], default="score",
                    help="the only command is score (supported for the documented call form)")
    ap.add_argument("--label", default=str(DEFAULT_LABELS), help="frozen labels CSV")
    ap.add_argument("--set", dest="setname", choices=SET_NAMES, help="one set to score")
    ap.add_argument("--db", help="built database the set was read from")
    ap.add_argument("--rc", help="row_checks verdict database for that build")
    ap.add_argument("--all", action="store_true", help="score the four sets, rebuilding their verdict databases")
    ap.add_argument("--out-dir", default=str(OUT_DIR), help="where --all writes its verdict databases")
    a = ap.parse_args(argv)
    labels = load_labels(Path(a.label))
    if a.all:
        results = run_all(labels, Path(a.out_dir))
    else:
        if not (a.setname and a.db and a.rc):
            ap.error("--set needs --db and --rc (or use --all)")
        results = [score_set(labels, a.db, a.rc, a.setname)]
    print(f"T-122 regression set: {a.label}")
    print(f"{'set':<10} {'labels':>6} {'FAIL':>5} {'WARN':>5} {'ok':>4} {'not-found':>10}")
    for r in results:
        print(f"{r.set:<10} {r.labels:>6} {r.fail:>5} {r.warn:>5} {r.ok:>4} {r.not_found:>10}")
    for r in results:
        _print_result(r)
    fails = sum(r.fail for r in results)
    print(f"\n{'PASS' if not fails else 'FAIL'}: {fails} FAIL across {len(results)} set(s), "
          f"{sum(r.labels for r in results)} labels")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
