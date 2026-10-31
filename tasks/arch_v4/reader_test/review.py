"""Build the hand-grading packet from results.jsonl (no model calls)."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2]))
from tasks.arch_v4.reader_test import db, retrieve, verify  # noqa: E402

Q = {json.loads(l)["qid"]: json.loads(l) for l in (HERE / "questions.jsonl").read_text(encoding="utf-8").splitlines()}
R = [json.loads(l) for l in (HERE / "results.jsonl").read_text(encoding="utf-8").splitlines()]
RET = {json.loads(l)["qid"]: json.loads(l) for l in (HERE / "retrieval.jsonl").read_text(encoding="utf-8").splitlines()}


def clip(s: str, n: int = 420) -> str:
    return re.sub(r"\s+", " ", s or "").strip()[:n]


def main() -> None:
    con = db.connect()
    lines = ["# Reader test — hand-grading packet", ""]
    for r in R:
        q = Q[r["qid"]]
        ret = RET.get(r["qid"], {})
        chunks = ret.get("chunks", [])
        by_id = {c["chunk_id"]: c for c in chunks}
        lines.append(f"## {r['qid']} {r['mid']} {r['symbol']} — {r['status']}")
        lines.append("")
        lines.append(f"**Q:** {q['question']}")
        lines.append("")
        lines.append(f"as_of={q['as_of']} types={','.join(q['doc_types'])} template={q['template']} "
                     f"gold_found={(r.get('gold') or {}).get('found')} gold_in_top={r['gold_in_topk']} "
                     f"gold_rank={r['gold_rank']}")
        gt = (q.get("ground_truth") or "").strip()
        lines.append(f"**Bank gold:** {gt or '(none)'}")
        lines.append("")
        lines.append(f"**Answer:** {r.get('answer') or '(none)'}")
        lines.append("")
        lines.append(f"**Quote:** {r.get('quote') or '(none)'}")
        lines.append("")
        v = r.get("verify") or {}
        lines.append(f"**Verify:** status={r['status']} quote_ok={v.get('quote_ok')} "
                     f"kind={v.get('quote_match_kind')} number_ok={v.get('number_ok')} "
                     f"missing_numbers={v.get('missing_numbers')}")
        if r.get("missing"):
            lines.append(f"**Model says missing:** {r['missing']}")
        lines.append("")
        lines.append("**Retrieved chunks:**")
        for c in chunks:
            mark = " **GOLD**" if (r.get("gold") or {}).get("chunk_id") == c["chunk_id"] else ""
            lines.append(f"- [{c['chunk_id']}] {c['doc_type']} {c['known_at'][:10]} p{c.get('page_from')} "
                         f"score={c['rerank']} cov={c['term_coverage']} phr={c['phrase_hits']}{mark} — {clip(c['body'], 170)}")
        lines.append("")
        if v.get("quote_chunk_id") and v["quote_chunk_id"] in by_id:
            c = by_id[v["quote_chunk_id"]]
            lines.append("**Quote context:**")
            lines.append("")
            lines.append("> " + verify.quote_span(r.get("quote") or "", c, 650))
            lines.append("")
        g = r.get("gold") or {}
        if g.get("found"):
            lines.append(f"**Gold locator:** chunk {g.get('chunk_id')} {g.get('doc_type')} {str(g.get('known_at'))[:10]} "
                         f"overlap={g.get('overlap')} in_top={r['gold_in_topk']}")
            lines.append("")
        # corpus probe for not-stated rows: evidence beyond the ten shown?
        if r["status"] == "not_stated":
            terms = retrieve.terms_for_question(q)
            fq = retrieve.fts_or(terms)
            seen = {c["chunk_id"] for c in chunks}
            extra = []
            for c in db.search(con, isin=q["isin"], doc_types=["concall", "deck", "annual_report",
                                                              "results_notes", "announcement"],
                               as_of=q["as_of"], fts_query=fq, limit=80):
                if c["chunk_id"] in seen:
                    continue
                body = re.sub(r"\s+", " ", c["body"] or "").lower()
                cov = sum(1 for w in terms.words[:18] if retrieve._contains_word(body, w))
                if cov >= 3:
                    extra.append((cov, c))
            extra.sort(key=lambda x: -x[0])
            if extra:
                lines.append("**Corpus probe (not shown to the model):**")
                for cov, c in extra[:4]:
                    lines.append(f"- cov={cov} [{c['chunk_id']}] {c['doc_type']} {c['known_at'][:10]} — {clip(c['body'], 220)}")
                lines.append("")
        lines.append("")
    (HERE / "review.md").write_text("\n".join(lines), encoding="utf-8")
    print("wrote", HERE / "review.md", len(lines), "lines")


if __name__ == "__main__":
    main()
