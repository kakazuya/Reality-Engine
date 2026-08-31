"""
bench_method_b.py — Method B: Title-based DB backfill reclassification benchmark
CPU SQL-only (no GPU), isolated. Does NOT edit filing_discovery.py.
"""
from __future__ import annotations
import json, sys, time, sqlite3
from pathlib import Path
from typing import List, Dict, Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from reality_engine.config import DB_PATH

try:
    import fitz
    _FITZ="fitz"
except ImportError:
    import pymupdf as fitz
    _FITZ="pymupdf"

def would_reclassify(title:str, size:int)->bool:
    t=(title or "").upper()
    hit = any(k in t for k in ["INTIMATION","OUTCOME","INVESTOR MEET","BOARD MEET","REGULATION 30","EARNINGS CALL","CONFERENCE CALL"])
    if hit and size and size<500000:
        return True
    if t.strip()=="INVESTOR_PRESENTATION" and size and size<200000:
        return True
    return False

def oracle(path:Path):
    try:
        doc=fitz.open(str(path))
        pages=len(doc)
        txt=doc[0].get_text()[:3000].lower() if pages else ""
        doc.close()
        size=path.stat().st_size
        is_notice = pages<=3 and ("regulation 30" in txt or "intimation" in txt) and any(k in txt for k in ["investor meet","conference call","earnings call","board meeting"])
        is_ppt = pages>5 and ("investor presentation" in txt or sum(k in txt for k in ["revenue","ebitda","pat","segment","q1","q2","fy"])>=2)
        if is_ppt: return "INVESTOR_PRESENTATION"
        if is_notice: return "ANNOUNCEMENT"
        if size<150000 and pages<=2: return "ANNOUNCEMENT"
        if size>500000 and pages>5: return "INVESTOR_PRESENTATION"
        return "OTHER"
    except:
        return "OTHER"

def get_symbols(conn):
    rows=conn.execute("SELECT nse_symbol FROM master_companies WHERE is_nifty100=1 AND is_active=1 ORDER BY nse_symbol").fetchall()
    return [r[0] for r in rows if r[0]]

def main():
    import argparse
    ap=argparse.ArgumentParser()
    ap.add_argument("--json-out", type=str, default=str(ROOT/"reality_engine"/"scripts"/"bench_method_b.json"))
    args=ap.parse_args()
    print("="*78)
    print("Method B benchmark: Title-based DB backfill")
    print("="*78)
    with sqlite3.connect(str(DB_PATH)) as conn:
        conn.row_factory=sqlite3.Row
        syms=get_symbols(conn)
        print(f"BSE100 proxy is_nifty100=1: {len(syms)} sample {syms[:10]}")
        ph=",".join("?" for _ in syms)
        rows=conn.execute(f"SELECT id,symbol,title,file_size_bytes,local_file_path,source_url FROM corporate_documents WHERE symbol IN ({ph}) AND doc_type='INVESTOR_PRESENTATION'", syms).fetchall()
        docs=[dict(r) for r in rows]
        print(f"INVESTOR_PRESENTATION docs for BSE100: {len(docs)}")
        with_file=[d for d in docs if d["local_file_path"] and Path(d["local_file_path"]).exists()]
        print(f"with existing file: {len(with_file)}")
        # counts
        sql_hit=sum(1 for d in docs if would_reclassify(d.get("title",""), d.get("file_size_bytes") or 0))
        print(f"would_reclassify (SQL predicate) total: {sql_hit}/{len(docs)} ({round(100*sql_hit/len(docs),1) if docs else 0}%)")
        # overall contaminated estimate
        overall=conn.execute("SELECT COUNT(*) FROM corporate_documents WHERE doc_type='INVESTOR_PRESENTATION' AND (UPPER(title) LIKE '%INTIMATION%' OR UPPER(title) LIKE '%OUTCOME%' OR UPPER(title) LIKE '%INVESTOR MEET%' )").fetchone()[0]
        overall2=conn.execute("SELECT COUNT(*) FROM corporate_documents WHERE doc_type='INVESTOR_PRESENTATION'").fetchone()[0]
        print(f"overall contaminated pattern (title LIKE): {overall}/{overall2}")
        # benchmark per doc timing and ground truth
        y_true=[]; y_pred=[]
        t0=time.perf_counter()
        per=[]
        for d in with_file:
            p=Path(d["local_file_path"])
            t00=time.perf_counter()
            pred_is_ann = would_reclassify(d.get("title",""), d.get("file_size_bytes") or 0)
            pred = "ANNOUNCEMENT" if pred_is_ann else "INVESTOR_PRESENTATION"
            ms=(time.perf_counter()-t00)*1000
            gt=oracle(p)
            y_true.append(gt)
            y_pred.append(pred)
            per.append({"symbol":d["symbol"],"title":d["title"],"size":d["file_size_bytes"],"pred":pred,"gt":gt,"ms":round(ms,4),"path":str(p)})
        # metrics
        def metrics(yt,yp):
            tp=sum(1 for t,p in zip(yt,yp) if t=="INVESTOR_PRESENTATION" and p=="INVESTOR_PRESENTATION")
            fp=sum(1 for t,p in zip(yt,yp) if t!="INVESTOR_PRESENTATION" and p=="INVESTOR_PRESENTATION")
            fn=sum(1 for t,p in zip(yt,yp) if t=="INVESTOR_PRESENTATION" and p!="INVESTOR_PRESENTATION")
            tn=sum(1 for t,p in zip(yt,yp) if t!="INVESTOR_PRESENTATION" and p!="INVESTOR_PRESENTATION")
            acc=(tp+tn)/len(yt) if yt else 0
            prec=tp/(tp+fp) if tp+fp else 0
            rec=tp/(tp+fn) if tp+fn else 0
            f1=2*prec*rec/(prec+rec) if prec+rec else 0
            return {"accuracy":round(acc,4),"precision":round(prec,4),"recall":round(rec,4),"f1":round(f1,4),"tp":tp,"fp":fp,"fn":fn,"tn":tn}
        m=metrics(y_true,y_pred)
        print(f"Ground truth on {len(with_file)} files: accuracy {m['accuracy']*100:.1f}% precision {m['precision']*100:.1f}% recall {m['recall']*100:.1f}% F1 {m['f1']*100:.1f}% TP{ m['tp']} FP{ m['fp']} FN{ m['fn']} TN{ m['tn']}")
        # BANKINDIA case
        bank=None
        for d in with_file:
            if d["symbol"]=="BANKINDIA":
                bank=d; break
        if not bank:
            row=conn.execute("SELECT symbol,title,file_size_bytes,local_file_path FROM corporate_documents WHERE symbol='BANKINDIA' AND local_file_path IS NOT NULL LIMIT 1").fetchone()
            if row: bank=dict(row)
        if bank:
            hit=would_reclassify(bank.get("title",""), bank.get("file_size_bytes") or 0)
            print(f"BANKINDIA case title='{bank.get('title')}' size={bank.get('file_size_bytes')} would_reclassify={hit} -> {'CAUGHT' if hit else 'MISSED'}")
        # timing
        avg_ms=sum(p["ms"] for p in per)/len(per) if per else 0
        print(f"avg predicate ms per doc: {avg_ms:.4f} ms (microseconds) throughput {round(1000/avg_ms,0) if avg_ms else 0} docs/ms")
        summary={"method":"B","bse100_docs":len(docs),"with_file":len(with_file),"would_reclassify_total":sql_hit,"metrics":m,"avg_ms":round(avg_ms,4),"per_file":per[:20]}
        out=Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(summary,indent=2),encoding="utf-8")
        print(f"wrote {out}")
        print(json.dumps(summary,indent=2))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
