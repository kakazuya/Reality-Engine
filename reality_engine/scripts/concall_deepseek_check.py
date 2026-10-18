"""Validation of concall_facts.db against its sources (2026-10-18, Shivam: test labels / PIT / metadata on a sample
before reading all 2026 transcripts). Read-only. Prints each check with counts and failing examples.

    python -m reality_engine.scripts.concall_deepseek_check [--since-run 2026-10-18T22:00]
"""
import argparse
import datetime as dt
import json
import re
import sqlite3
from pathlib import Path

from reality_engine.scripts.concall_period import expected_quarters as fy_quarter, parse_period

ROOT = Path(__file__).resolve().parents[2]
MAIN = ROOT / "reality_engine/data/equity_intelligence.db"
OUT = ROOT / "reality_engine/data/concall_facts.db"
ENUMS = {"basis": {"standalone", "consolidated", "segment", "unknown", None, ""},
         "direction": {"new", "raised", "maintained", "lowered", "withdrawn", "unclear", None, ""},
         "firmness": {"firm", "indicative", "aspirational", None, ""},  # stored NULL when the model wrote anything else
         "signal": {"positive", "neutral", "negative", "mixed", None, ""}}
STOP = {"limited", "ltd", "india", "the", "and", "of", "company", "industries", "corporation", "&", "(india)"}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--since-run", default="")
    a = ap.parse_args()
    out = sqlite3.connect(f"file:{OUT}?mode=ro", uri=True)
    main_db = sqlite3.connect(f"file:{MAIN}?mode=ro", uri=True)
    docs = out.execute("SELECT doc_id, isin, symbol, filed_at, status, raw_json, chars FROM cc_docs WHERE run_at >= ?",
                       (a.since_run,)).fetchall()
    print(f"docs checked: {len(docs)}  status: " + json.dumps(
        {s: sum(1 for d in docs if d[4] == s) for s in sorted({d[4] for d in docs})}))
    fails = {}
    info = []

    def fail(check, ex):
        fails.setdefault(check, []).append(ex)

    names = {i: n for i, n in main_db.execute("SELECT isin, company_name FROM master_companies")}
    for doc_id, isin, sym, filed, status, raw, chars in docs:
        src = main_db.execute("SELECT isin, symbol, bse_dissem_ts, publication_date, call_date, doc_date, local_file_path, sha256_hash "
                              "FROM corporate_documents WHERE id=?", (doc_id,)).fetchone()
        real = src[2] or src[3] or src[4]
        # 1 PIT date = the source filing time exactly, never the crawl date
        if filed != real:
            fail("pit_filed_at_mismatch", (doc_id, sym, filed, real))
        if filed and src[5] and filed[:10] == src[5][:10] and not src[2] and not src[3]:
            fail("pit_only_doc_date", (doc_id, sym, filed))
        # 2 identity
        if (isin, sym) != (src[0], src[1]):
            fail("identity_mismatch", (doc_id, isin, sym, src[0], src[1]))
        if status == "skip_duplicate":
            sib = main_db.execute("SELECT MIN(COALESCE(bse_dissem_ts,publication_date,call_date)) FROM corporate_documents "
                                  "WHERE doc_type='CONCALL_TRANSCRIPT' AND id<>? AND (sha256_hash=? OR (isin=? AND "
                                  "substr(COALESCE(bse_dissem_ts,publication_date,call_date),1,10)=?))",
                                  (doc_id, src[7], isin, (real or "")[:10])).fetchone()[0]
            if not sib or sib > real:
                fail("pit_duplicate_kept_later_filing", (doc_id, sym, real, sib))
            continue
        if status != "ok":
            continue
        import pymupdf
        with pymupdf.open(src[6]) as d:
            text = "\n".join(p.get_text() for p in d)
        low = text.lower()
        words = [w for w in re.findall(r"[a-z0-9&]+", (names.get(isin) or "").lower()) if w not in STOP and len(w) > 2]
        if words and not any(w in low[:20000] for w in words[:2]):
            fail("identity_name_not_in_text", (doc_id, sym, names.get(isin)))
        if not any(k in low for k in ("moderator", "operator", "question", "participant")):
            fail("not_a_call_transcript", (doc_id, sym, chars))
        data = json.loads(raw)
        per = parse_period(data.get("period_discussed"))
        stored = out.execute("SELECT period_q, period_fy FROM cc_docs WHERE doc_id=?", (doc_id,)).fetchone()
        if per and tuple(stored) != per:
            fail("period_columns_not_normalised", (doc_id, sym, stored, per))
        exp = fy_quarter(dt.date.fromisoformat(real[:10]))
        if per is None and re.search(r"BUSINESS UPDATE|OUTLOOK|ACQUISITION|INVESTOR DAY|ANALYST MEET",
                                     (data.get("period_discussed") or "").upper()):
            info.append((doc_id, sym, data.get("period_discussed")))   # event call, not a quarterly results call
        elif per is None:
            fail("period_unparsed", (doc_id, sym, data.get("period_discussed")))
        elif per not in exp:
            fail("period_vs_filing_date", (doc_id, sym, data.get("period_discussed"), real[:10], exp))
        items = out.execute("SELECT list_name, filed_at, isin, basis, direction, firmness, signal, period, quote "
                            "FROM cc_items WHERE doc_id=?", (doc_id,)).fetchall()
        if not items:
            fail("no_items", (doc_id, sym))
        for ln, f2, i2, basis, direc, firm, sig, period, quote in items:
            if f2 != filed or i2 != isin:
                fail("item_meta_mismatch", (doc_id, ln, f2, i2)); break
        for ln, _, _, basis, direc, firm, sig, period, quote in items:
            for k, v in (("basis", basis), ("direction", direc), ("firmness", firm), ("signal", sig)):
                if v not in ENUMS[k]:
                    fail(f"enum_{k}", (doc_id, ln, v))
            if ln == "guidance" and (not period or period == "unspecified"):
                vague = True
            if ln == "guidance" and not period:
                fail("guidance_without_period", (doc_id, sym, quote[:60] if quote else None))
    skipped = [d for d in docs if d[4] == "skip_cover_letter"]
    print(f"cover letters skipped: {len(skipped)}, chars max {max([d[6] or 0 for d in skipped], default=0)}")
    print(f"event calls (no quarter, not a failure): {len(info)} {info[:3]}")
    for check, ex in sorted(fails.items()):
        print(f"FAIL {check}: {len(ex)}  e.g. {ex[:3]}")
    print("ALL CHECKS PASSED" if not fails else f"{len(fails)} checks failed")


if __name__ == "__main__":
    main()
