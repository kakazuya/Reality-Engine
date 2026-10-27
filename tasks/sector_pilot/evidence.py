"""Collect locally-held business evidence for sampled companies (read-only).

Usage:  python evidence.py            # fill evidence.json for every sample row
        python evidence.py --isin ISIN  # add/replace one company
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

from reality_engine.db.readonly import connect_ro

OUT = Path(__file__).resolve().parent
DATA = Path(os.environ["REALITY_DATA_ROOT"])
FY_CUTOFF = "2025-03-31"

eq = connect_ro(DATA / "equity_intelligence.db", timeout_s=120)
ar = connect_ro(DATA / "ar_facts.db", timeout_s=120)
df = connect_ro(DATA / "deck_figures.db", timeout_s=120)
cf = connect_ro(DATA / "concall_facts.db", timeout_s=120)

NOISE = {
    "related_party", "related-party transactions", "related_party_transaction",
    "related-party transaction", "related_party_transactions", "borrowings", "tax", "expense",
    "employee_benefits", "employee benefits - DBO reconciliation", "cash_flow",
    "cash_flow_statement", "deferred_tax", "governance", "auditor", "csr",
    "remuneration", "trade_payable", "trade_payable_ageing", "receivables",
    "receivables_ageing", "contingent_liability", "leases", "dividend", "depreciation",
}
BIZ_HINT = re.compile(
    r"segment|business|manufactur|product|service|revenue|industry|portfolio|brand|"
    r"order book|customer|export|plant|capacity", re.I)


def gather(isin: str) -> dict:
    ev = {"isin": isin, "seg_rows": [], "ar_quotes": [], "ar_chunks": [],
          "deck_facts": [], "concall": [], "sources": []}

    seg = ar.execute(
        "select fiscal_year,category,item,value_raw,value,unit,period,basis,quote from ar_facts "
        "where isin=? and fiscal_year>=? and (category='segment' or lower(item) like '%segment%') "
        "order by fiscal_year desc limit 40", (isin, FY_CUTOFF)).fetchall()
    if seg:
        latest = max(x[0] for x in seg)
        for fy, cat, item, vraw, val, unit, period, basis, quote in seg:
            if fy != latest:
                continue
            ev["seg_rows"].append({"fy": fy, "item": (item or "")[:220],
                                   "value_raw": vraw, "value": val, "unit": unit,
                                   "period": period, "basis": basis,
                                   "quote": (quote or "")[:300]})
        ev["sources"].append({"store": "ar_facts.db/ar_facts",
                              "doc": f"isin={isin} fiscal_year={latest}",
                              "note": "segment rows"})

    quotes = ar.execute(
        "select fiscal_year,category,item,quote from ar_facts where isin=? and fiscal_year>=? "
        "and quote is not null and length(quote)>=45 order by length(quote) desc limit 60",
        (isin, FY_CUTOFF)).fetchall()
    kept = 0
    for fy, cat, item, quote in quotes:
        c = (cat or "").strip().lower()
        if c in NOISE or not BIZ_HINT.search(quote or ""):
            continue
        ev["ar_quotes"].append({"fy": fy, "category": (cat or "")[:60],
                                "item": (item or "")[:160], "quote": quote[:320]})
        kept += 1
        if kept >= 10:
            break
    if kept:
        ev["sources"].append({"store": "ar_facts.db/ar_facts",
                              "doc": f"isin={isin} FY>={FY_CUTOFF}",
                              "note": "business quotes"})

    # AR text: the business-description passages of the newest reports. Chunks
    # are scored locally (business terms +, boilerplate -) because a fixed phrase
    # list too often lands on the cover letter or a financial-statement note.
    raw = eq.execute(
        "select doc_id,published_date,title,source_type from raw_documents where isin=? "
        "and source_type in ('ANNUAL_REPORT','AR') order by published_date desc limit 2",
        (isin,)).fetchall()
    GOOD = re.compile(r"engaged in|business of|manufactur|our products?|product portfolio|"
                      r"services? (?:to|offered)|company overview|business overview|"
                      r"about (?:us|the company)|core business|key products|"
                      r"segment|solutions|brands?", re.I)
    BAD = re.compile(r"related part|corporate social|auditor|secretarial|balance sheet|"
                     r"notes to (?:the )?financial|statement of profit|share capital|"
                     r"board of directors|annual general meeting|remuneration", re.I)
    for did, pub, title, _st in raw:
        cand = eq.execute(
            "select chunk_index,content from document_chunks where doc_id=? "
            "and length(content)>450 order by chunk_index limit 60", (did,)).fetchall()
        scored = []
        for cidx, content in cand:
            text = re.sub(r"^\[Metadata:[^\]]*\]\s*", "", content)
            score = len(GOOD.findall(text)) - 2 * len(BAD.findall(text))
            if score > 0:
                scored.append((score, cidx, text))
        scored.sort(key=lambda x: (-x[0], x[1]))
        for score, cidx, text in scored[:5]:
            ev["ar_chunks"].append({"chunk_index": cidx, "doc_id": did,
                                    "score": score, "text": text[:1200]})
        if ev["ar_chunks"]:
            ev["sources"].append({"store": "equity_intelligence.db/document_chunks",
                                  "doc": f"doc_id={did} ({pub}) {str(title)[:40]}",
                                  "note": "AR business text"})
            break

    # investor-presentation text when the AR text is missing
    if not ev["ar_chunks"]:
        pres = eq.execute(
            "select doc_id,published_date,title from raw_documents where isin=? "
            "and source_type='INVESTOR_PRESENTATION' order by published_date desc limit 1",
            (isin,)).fetchall()
        if pres:
            did, pub, title = pres[0]
            chunks = eq.execute(
                "select chunk_index,content from document_chunks where doc_id=? "
                "and (content like '%segment%' or content like '%business%' "
                "or content like '%revenue%') order by chunk_index limit 6", (did,)).fetchall()
            for cidx, content in chunks:
                if not content or len(content) < 200:
                    continue
                ev["ar_chunks"].append({"chunk_index": cidx, "doc_id": did,
                                        "text": content[:900], "source": "presentation"})
                if len(ev["ar_chunks"]) >= 4:
                    break
            if ev["ar_chunks"]:
                ev["sources"].append({"store": "equity_intelligence.db/document_chunks",
                                      "doc": f"doc_id={did} ({pub}) presentation",
                                      "note": "deck text"})

    decks = df.execute(
        "select sha256,known_at,title from deck_sources where isin=? "
        "order by known_at desc limit 2", (isin,)).fetchall()
    for sha, known, title in decks:
        facts = df.execute(
            "select metric,period,raw_number,value,unit from facts where sha256=? "
            "and (metric like '%revenue%' or metric like '%segment%' or metric like '%sale%') "
            "limit 8", (sha,)).fetchall()
        for metric, period, raw_number, value, unit in facts:
            ev["deck_facts"].append({"known_at": known, "metric": (metric or "")[:100],
                                     "period": period, "value": value, "unit": unit,
                                     "sha256": sha})
        if facts:
            ev["sources"].append({"store": "deck_figures.db/facts",
                                  "doc": f"sha256={sha[:12]} known_at={known}",
                                  "note": "deck facts"})
            break

    cds = cf.execute(
        "select doc_id,filed_at from cc_docs where isin=? and status='done' "
        "order by filed_at desc limit 1", (isin,)).fetchall()
    if cds:
        did = cds[0][0]
        items = cf.execute(
            "select metric,statement,quote from cc_items where doc_id=? "
            "and (metric like '%segment%' or statement like '%business%' "
            "or statement like '%revenue%' or statement like '%product%') limit 6", (did,)).fetchall()
        for metric, statement, quote in items:
            ev["concall"].append({"metric": (metric or "")[:120],
                                  "statement": (statement or "")[:220],
                                  "quote": (quote or "")[:260]})
        if items:
            ev["sources"].append({"store": "concall_facts.db/cc_items",
                                  "doc": f"doc_id={did} filed={cds[0][1]}",
                                  "note": "concall"})
    return ev


def main() -> None:
    path = OUT / "evidence.json"
    evidence = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    if "--isin" in sys.argv:
        isin = sys.argv[sys.argv.index("--isin") + 1]
        evidence[isin] = gather(isin)
        path.write_text(json.dumps(evidence, indent=1, ensure_ascii=False), encoding="utf-8")
        print(f"updated {isin}: {evidence[isin]['sources']}")
        return
    rows = json.loads((OUT / "sample.json").read_text(encoding="utf-8"))["rows"]
    for i, r in enumerate(rows, 1):
        evidence[r["isin"]] = gather(r["isin"])
        if i % 20 == 0:
            print(f"{i}/200 {r['symbol']}", flush=True)
    path.write_text(json.dumps(evidence, indent=1, ensure_ascii=False), encoding="utf-8")
    print("wrote", len(evidence))


if __name__ == "__main__":
    main()
