"""Prepare the 60-instance hand check (20 per bucket) and score it.

    python tasks/pilot60/hand_check.py            # writes HAND_CHECK_60.md + .json
    python tasks/pilot60/hand_check.py --score    # reads verdicts from HAND_CHECK_60.json

Each sampled row is printed with its answer, its evidence and the source rows behind
that evidence (chunks_v3 doc/chunk, price row, XBRL/facts row), so the reviewer can
judge correctness against what is actually held.  Deterministic checks are computed for
every row; the human verdict is stored per row in HAND_CHECK_60.json (``verdict`` =
OK|WRONG|PARTIAL and ``note``).
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
OUT = REPO / "tasks" / "pilot60"
CHUNKS = Path(os.environ.get("REALITY_CHUNKS_V3") or (REPO / ".tmp" / "pilot60" / "chunks_v3_pilot.db"))
DATA = Path(os.environ.get("REALITY_DATA_ROOT",
                           r"C:\Users\warri\Downloads\Info_Diffusion_Model\reality_engine\data"))
SEED = 20261028
BUCKETS = ("LARGE", "MID-SMALL", "MICRO")


def ro(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def load(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def pick_rows() -> list[dict]:
    rows = [r for r in load(OUT / "RESULTS_INSTANCES.jsonl") if r.get("kind") == "stock"]
    rng = random.Random(SEED)
    picked = []
    for bucket in BUCKETS:
        pool = [r for r in rows if r.get("bucket") == bucket]
        answered = [r for r in pool if r["grade"] == "ANSWERED"]
        partial = [r for r in pool if r["grade"] in ("PARTIAL", "WRONG")]
        chosen = answered[:20]
        if len(chosen) < 20:
            chosen += rng.sample(partial, min(20 - len(chosen), len(partial)))
        picked += chosen
    return picked


def evidence_sources(row: dict, inst: dict) -> list[str]:
    """Re-read what the evidence refs point at."""
    entity_isins = {str(e.get("isin")) for e in inst.get("entities") or [] if e.get("isin")}
    out = []
    seen = set()
    for ref in (row.get("evidence") or [])[:4]:
        ref = str(ref)
        if ref in seen:
            continue
        seen.add(ref)
        if ref.startswith("chunks_v3:"):
            doc_id = ref.split(":", 1)[1].split("#")[0]
            out.append(chunk_source(doc_id, entity_isins, inst.get("as_of")))
        elif ":" in ref and "ISIN" not in ref:
            out.append(f"ref {ref}")
    return out


def chunk_source(doc_id: str, entity_isins: set[str], as_of: str | None) -> str:
    if not CHUNKS.is_file():
        return "chunks_v3 store missing"
    con = ro(CHUNKS)
    try:
        doc = con.execute("SELECT isin, symbol, doc_type, known_at, title FROM doc "
                          "WHERE doc_id IN (?, ?)", (doc_id, f"sha256:{doc_id}")).fetchone()
        if not doc:
            return f"doc {doc_id[:20]} not in chunks_v3"
        latest = con.execute("SELECT MAX(known_at) AS k FROM doc WHERE isin=? AND doc_type=? "
                             "AND known_at <= ?",
                             (doc["isin"], doc["doc_type"], as_of or "2099-12-31")).fetchone()
        body = con.execute("SELECT body FROM chunk WHERE doc_id IN (?, ?) LIMIT 1",
                           (doc_id, f"sha256:{doc_id}")).fetchone()
        entity_ok = "yes" if doc["isin"] in entity_isins or any(
            i[:7] == doc["isin"][:7] for i in entity_isins) else "NO"
        pit = "yes" if not as_of or str(doc["known_at"])[:10] <= as_of else "NO"
        return (f"doc {doc['symbol']} {doc['doc_type']} known_at={str(doc['known_at'])[:10]} "
                f"entity_match={entity_ok} pit={pit} latest={latest['k'] and str(latest['k'])[:10]}"
                f" | {(body['body'] if body else '')[:90]}")
    finally:
        con.close()


def auto_checks(row: dict, inst: dict) -> list[str]:
    checks = []
    srcs = evidence_sources(row, inst)
    for src in srcs:
        if "entity_match=NO" in src:
            checks.append("EVIDENCE ENTITY MISMATCH")
        if "pit=NO" in src:
            checks.append("EVIDENCE AFTER as_of")
    if row.get("pit"):
        checks.append("PIT: " + "; ".join(row["pit"])[:120])
    if not srcs and row["grade"] == "ANSWERED":
        checks.append("ANSWERED WITH NO EVIDENCE REF")
    return checks


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--score", action="store_true")
    args = ap.parse_args(argv)
    inst_by_mid = {r["mid"]: r for r in load(OUT / "INSTANCES.jsonl")}
    if args.score:
        scored = json.loads((OUT / "HAND_CHECK_60.json").read_text(encoding="utf-8"))
        counts = Counter(r["verdict"] for r in scored["rows"])
        total = sum(counts.values())
        ok = counts.get("OK", 0)
        scored["precision"] = round(ok / total, 4) if total else 0.0
        scored["counts"] = dict(counts)
        (OUT / "HAND_CHECK_60.json").write_text(json.dumps(scored, indent=1), encoding="utf-8")
        print(f"hand-check precision: {ok}/{total} = {scored['precision']:.1%}  {dict(counts)}")
        return 0
    picked = pick_rows()
    lines = ["# Hand check — 60 pilot instance answers (20 per bucket)", "",
             "Source rows behind each answer are re-read from chunks_v3 / the live stores. "
             "Auto checks flag a wrong entity, evidence after as_of, or no evidence at all.", ""]
    rows = []
    for i, row in enumerate(picked, 1):
        inst = inst_by_mid.get(row["mid"], {})
        checks = auto_checks(row, inst)
        entity = ", ".join(f"{e.get('symbol')}({e.get('isin')})"
                           for e in inst.get("entities") or [])
        block = [f"## {i}. {row['mid']} — {row.get('bucket')} — {row.get('sector')}",
                 f"- entity: {entity}",
                 f"- question: {str(row.get('question') or '')[:140]}",
                 f"- grade: {row['grade']} | answer: {str(row.get('answer') or '')[:320]}",
                 f"- evidence: {', '.join(str(e) for e in (row.get('evidence') or [])[:3])}"]
        block += [f"- source: {src}" for src in evidence_sources(row, inst)]
        block += [f"- auto: {c}" for c in checks] or ["- auto: clean"]
        lines += block + [""]
        rows.append({"mid": row["mid"], "parent_mid": row.get("parent_mid"),
                     "bucket": row.get("bucket"), "sector": row.get("sector"),
                     "grade": row["grade"], "entity": entity,
                     "question": row.get("question"), "answer": row.get("answer"),
                     "evidence": row.get("evidence"), "auto": checks,
                     "verdict": "OK" if not checks else "WRONG", "note": ""})
    (OUT / "HAND_CHECK_60.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (OUT / "HAND_CHECK_60.json").write_text(json.dumps(
        {"seed": SEED, "rows": rows, "precision": None}, indent=1), encoding="utf-8")
    print(f"{len(rows)} rows -> HAND_CHECK_60.md / .json; verdicts default from auto checks, "
          f"review and edit the json, then run --score")
    return 0


if __name__ == "__main__":
    sys.exit(main())
