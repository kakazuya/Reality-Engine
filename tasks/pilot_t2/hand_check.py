"""50-chunk hand check: boundary quality and tag precision on the pilot store.

    python tasks/pilot_t2/hand_check.py                 # write hand_check_50.md/json
    python tasks/pilot_t2/hand_check.py --score verdicts.json
    python tasks/pilot_t2/hand_check.py --summary

The sample is stratified: 10 chunks per doc type, evenly spaced through the
store.  Each tag instance carries the text its rule matched, so the judge only
has to accept or reject a short context, not re-read the whole corpus.
The verdict file is ``{"tag:<id>": 0|1}`` for tag instances and
``{"boundary:<id>": 0|1}`` for chunk boundaries.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from reality_engine.db.readonly import connect_ro  # noqa: E402
from reality_engine.processing import chunker_v3 as v3  # noqa: E402

DB = Path(os.environ.get("REALITY_CHUNKS_V3") or (REPO / ".tmp" / "pilot" / "chunks_v3_pilot.db"))
OUT = Path(__file__).resolve().parent
TYPES = ("concall", "deck", "annual_report", "results_notes", "announcement")



def ro(path: Path) -> sqlite3.Connection:
    con = connect_ro(path, timeout_s=30)
    con.row_factory = sqlite3.Row
    return con


def wilson(ok: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return 0.0, 0.0
    p = ok / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return p, max(0.0, centre - margin)


def sample(con: sqlite3.Connection, total: int = 50) -> list[sqlite3.Row]:
    """Evenly spaced chunks, stratified over the doc types the store actually has."""
    per_type: dict[str, list[sqlite3.Row]] = {}
    for doc_type in TYPES:
        rows = con.execute(
            "SELECT chunk_id, doc_id, doc_type, isin, symbol_at_time, known_at, doc_type, "
            "section, speaker, speaker_role, unit_kind, header, body, page_from, page_to, "
            "forward_looking, content_tags FROM chunk WHERE doc_type=? ORDER BY chunk_id",
            (doc_type,)).fetchall()
        if rows:
            per_type[doc_type] = rows
    types = list(per_type)
    if not types:
        return []
    out: list[sqlite3.Row] = []
    base, extra = divmod(total, len(types))
    for index, doc_type in enumerate(types):
        rows = per_type[doc_type]
        want = base + (1 if index < extra else 0)
        take = min(want, len(rows))
        step = max(1, len(rows) // take)
        out.extend(rows[::step][:take])
    return out


def _context(pattern: re.Pattern, body: str) -> str:
    match = pattern.search(body)
    if not match:
        return ""
    lo, hi = max(0, match.start() - 70), min(len(body), match.end() + 70)
    return " ".join(body[lo:hi].split())


def tag_instances(chunk: sqlite3.Row) -> list[dict]:
    body = chunk["body"] or ""
    tags = v3.deterministic_tags(body, chunk["doc_type"], chunk["section"] or "",
                                chunk["speaker_role"] or "")
    out = []
    for tag in tags:
        rule = dict(v3._TAG_RULES).get(tag)
        context = ""
        if rule is not None:
            context = _context(rule, body)
        elif tag == "guidance":
            for verb in v3._GUIDANCE_VERB.finditer(body):
                lo, hi = max(0, verb.start() - 120), min(len(body), verb.end() + 120)
                metric = v3._GUIDANCE_METRIC.search(body, lo, hi)
                if metric:
                    context = f"verb={verb.group(0)!r} metric={metric.group(0)!r}"
                    break
        elif tag == "forward_looking":
            verb = v3.FORWARD_LOOKING.search(body)
            anchor = v3.FUTURE_ANCHOR.search(body)
            context = "verb=%r anchor=%r" % (verb.group(0) if verb else "",
                                             anchor.group(0) if anchor else "")
        elif tag.startswith("section:"):
            context = f"section={chunk['section']!r}"
        elif tag.startswith("speaker_role:"):
            context = f"speaker={chunk['speaker']!r} role={chunk['speaker_role']!r}"
        elif tag.startswith("unit:"):
            context = _context({"unit:inr_crore": v3._UNIT_CROWE, "unit:inr_lakh": v3._UNIT_LAKH,
                                "unit:percent": v3._UNIT_PERCENT, "unit:bps": v3._UNIT_BPS,
                                "unit:usd": v3._UNIT_USD}[tag], body)
        elif tag == "has_number":
            context = v3._NUMERIC.search(body).group(0) if v3._NUMERIC.search(body) else ""
        out.append({"tag": tag, "context": context[:240]})
    return out


def boundary_verdict(chunk: sqlite3.Row) -> tuple[bool, str]:
    body = (chunk["body"] or "").strip()
    if not body:
        return False, "empty"
    unit = chunk["unit_kind"] or ""
    if unit.startswith(("slide", "announcement")):
        return True, unit
    if unit.endswith("_cont") and "(cont.)" not in (chunk["section"] or ""):
        return False, "continuation not marked"
    start_ok = body[0].isupper() or not body[0].isalpha()
    tail = body.rstrip().rstrip("\"')]\u2019")
    end_ok = tail.endswith((".", "!", "?", ":", ";", "%")) or _row_like(body)
    if not start_ok:
        return False, "starts lowercase/mid-sentence: " + body[:60]
    if not end_ok:
        return False, "ends mid-sentence: " + body[-60:]
    return True, "structural"


def _row_like(body: str) -> bool:
    last = body.splitlines()[-1] if body else ""
    return len(v3._NUMERIC.findall(last)) >= 2


def write_sample() -> None:
    con = ro(DB)
    chunks = sample(con)
    lines = ["# 50-chunk hand check — pilot chunks_v3", "",
             f"store: `{DB}`", ""]
    payload = {"chunks": [], "tag_instances": []}
    for i, c in enumerate(chunks, 1):
        ok, why = boundary_verdict(c)
        inst = {"id": f"boundary:{i}", "chunk_id": c["chunk_id"], "doc_type": c["doc_type"],
                "auto": ok, "reason": why}
        payload["chunks"].append(inst)
        lines += [f"## {i}. {c['doc_type']} {c['symbol_at_time']} {c['known_at'][:10]} "
                  f"({c['unit_kind']})",
                  f"section: `{c['section']}`  page {c['page_from']}-{c['page_to']}  "
                  f"len {len(c['body'])}",
                  f"start: `{c['body'][:110]}`",
                  f"end:   `{c['body'][-110:]}`",
                  f"boundary: {'PASS' if ok else 'FAIL'} — {why}", "",
                  "tags: " + (", ".join(t["tag"] for t in tag_instances(c)) or "-"), ""]
        for j, t in enumerate(tag_instances(c), 1):
            tid = f"tag:{c['chunk_id']}:{j}"
            payload["tag_instances"].append(
                {"id": tid, "chunk_id": c["chunk_id"], "doc_type": c["doc_type"],
                 "tag": t["tag"], "context": t["context"]})
            lines.append(f"- `{tid}` **{t['tag']}** — {t['context']}")
        lines.append("")
    (OUT / "hand_check_50.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (OUT / "hand_check_50.json").write_text(json.dumps(payload, indent=1), encoding="utf-8")
    print(f"wrote hand_check_50.md: {len(chunks)} chunks, "
          f"{len(payload['tag_instances'])} tag instances")


def score(path: Path) -> None:
    verdicts = json.loads(path.read_text(encoding="utf-8"))
    payload = json.loads((OUT / "hand_check_50.json").read_text(encoding="utf-8"))
    bounds = [verdicts.get(c["id"], 1 if c["auto"] else 0) for c in payload["chunks"]]
    b_ok, b_n = sum(bounds), len(bounds)
    tags = payload["tag_instances"]
    verdict = [verdicts.get(t["id"]) for t in tags]
    judged = [(t["tag"], v) for t, v in zip(tags, verdict)]
    ok = sum(v for _, v in judged if v is not None)
    n = sum(1 for _, v in judged if v is not None)
    p, lo = wilson(ok, n)
    p_b, lo_b = wilson(b_ok, b_n)
    by_tag: dict[str, list[int]] = {}
    for tag, v in judged:
        if v is not None:
            by_tag.setdefault(tag, []).append(v)
    lines = ["# Hand-check score", "",
             f"- boundary: {b_ok}/{b_n} = {p_b:.3f} (Wilson 95% LB {lo_b:.3f})",
             f"- tags: {ok}/{n} = {p:.3f} (Wilson 95% LB {lo:.3f})", "",
             "| tag | correct | judged | precision |", "|---|---:|---:|---:|"]
    for tag in sorted(by_tag):
        vals = by_tag[tag]
        lines.append(f"| {tag} | {sum(vals)} | {len(vals)} | {sum(vals) / len(vals):.2f} |")
    (OUT / "HAND_CHECK_SCORE.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


def summary() -> None:
    con = ro(DB)
    print("documents by type:")
    for row in con.execute("SELECT doc_type, COUNT(*) n, SUM(needs_ocr) ocr FROM doc "
                           "GROUP BY doc_type ORDER BY n DESC"):
        print(f"  {row['doc_type']:15s} docs={row['n']:4d} needs_ocr={row['ocr'] or 0}")
    print("chunks by type:")
    for row in con.execute("SELECT doc_type, COUNT(*) n, AVG(char_len) avg FROM chunk "
                           "GROUP BY doc_type ORDER BY n DESC"):
        print(f"  {row['doc_type']:15s} chunks={row['n']:6d} mean_chars={row['avg']:.0f}")
    total = con.execute("SELECT COUNT(*) FROM chunk").fetchone()[0]
    docs = con.execute("SELECT COUNT(*) FROM doc").fetchone()[0]
    print(f"total: {docs} docs, {total} chunks")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--score", type=Path)
    ap.add_argument("--summary", action="store_true")
    args = ap.parse_args(argv[1:])
    if args.score:
        score(args.score)
    elif args.summary:
        summary()
    else:
        write_sample()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
