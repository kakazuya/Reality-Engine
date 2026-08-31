"""Refetch all true Investor Presentations with Method C, delete notices immediately."""
import sys, time, json, shutil
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from reality_engine.db.database import db_manager
from reality_engine.db.repository import repo
from reality_engine.ingestion.official_filing_client import official_filing_client
from reality_engine.ingestion.pdf_ingestor import PDFIngestor

BATCH = 150
MAX_BATCHES = 10
RATE = 0.5

def get_ip_wof(limit=5000):
    with db_manager.session() as conn:
        rows = conn.execute("SELECT id, symbol, isin, source_url, doc_date FROM corporate_documents WHERE doc_type='INVESTOR_PRESENTATION' AND (local_file_path IS NULL OR TRIM(local_file_path)='') ORDER BY id LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

def persist_archived(results):
    # results is list of per_symbol results from archive_many
    updated=0
    with db_manager.session() as conn:
        for pr in results:
            for r in pr.get("results",[]):
                if r.get("ok") and r.get("local_file_path") and r.get("source_url"):
                    # only persist if still INVESTOR_PRESENTATION? But method C already reclassified some to ANNOUNCEMENT before persist logic in archive_many updates doc_type. Here we persist path only for kept files; for reclassified, we want to delete file and not persist? archive_many already updated doc_type, but we still need to handle file deletion for reclassified.
                    # Check if doc_type after classify is ANNOUNCEMENT -> delete file and clear path
                    ctype = r.get("content_classified_type") or r.get("content_classified") or ""
                    # archive_many returns content_classified_type per result?
                    # fallback: if reclassified flag
                    if r.get("reclassified") or ctype=="ANNOUNCEMENT":
                        # delete file if exists
                        p = Path(r["local_file_path"])
                        if p.exists():
                            try: p.unlink()
                            except: pass
                        # keep DB as ANNOUNCEMENT with no path (already updated by archive_many)
                        continue
                    # kept as IP -> persist
                    conn.execute("UPDATE corporate_documents SET local_file_path=?, file_size_bytes=?, sha256_hash=?, is_processed=1 WHERE source_url=?",
                                 (r["local_file_path"], r.get("file_size_bytes",0), r.get("sha256_hash"), r["source_url"]))
                    updated+=1
        conn.commit()
    return updated

def main():
    print("=== Refetch all IP with Method C ===")
    total_archived=0; total_kept=0; total_reclassified=0
    ingestor = PDFIngestor()
    for b in range(MAX_BATCHES):
        wof = get_ip_wof(BATCH)
        if not wof:
            print(f"Batch {b+1}: no more IP wof, done")
            break
        # disk guard
        free_mb = shutil.disk_usage(str(ROOT)).free/1024/1024
        if free_mb < 500:
            print(f"Disk guard free {free_mb:.0f} <500MB abort")
            break
        # group by symbol
        by_sym=defaultdict(list)
        sym_isc={}
        for r in wof:
            sym=r["symbol"]
            by_sym[sym].append({"source_url":r["source_url"],"doc_type":"INVESTOR_PRESENTATION","source":"bse_official","discovery_source":"screener_discovery"})
            sym_isc[sym]=r.get("isin")
        discoveries=[{"symbol":s,"bse_code":None,"links":links} for s,links in by_sym.items()]
        print(f"Batch {b+1}: {len(wof)} links across {len(discoveries)} symbols, free {free_mb:.0f}MB")
        res = official_filing_client.archive_many(discoveries, max_workers=1, progress=False)
        # res contains per_symbol
        per = res.get("per_symbol",[])
        archived = sum(1 for pr in per for r in pr.get("results",[]) if r.get("ok"))
        reclassified = sum(1 for pr in per for r in pr.get("results",[]) if r.get("ok") and (r.get("content_classified_type")=="ANNOUNCEMENT" or r.get("reclassified")))
        print(f"  archived {archived}/{len(wof)} reclassified_to_announcement {reclassified}")
        total_archived+=archived
        total_reclassified+=reclassified
        kept = persist_archived(per)
        total_kept+=kept
        print(f"  persisted kept {kept}")
        # ingest kept
        ingested=0
        for pr in per:
            sym=pr.get("symbol")
            isin=sym_isc.get(sym)
            if not isin:
                try:
                    comp=repo.get_company_by_symbol(sym)
                    isin=comp.get("isin") if comp else None
                except: isin=None
            for r in pr.get("results",[]):
                if not r.get("ok"): continue
                ctype=r.get("content_classified_type") or ""
                if ctype=="ANNOUNCEMENT" or r.get("reclassified"):
                    continue
                p=r.get("local_file_path")
                if not p or not Path(p).exists():
                    continue
                try:
                    ret=ingestor.ingest_pdf(Path(p), symbol=sym, isin=isin, source_type="INVESTOR_PRESENTATION", source_url=r.get("source_url"))
                    if ret.get("status")=="ingested":
                        ingested+=1
                except Exception as e:
                    print(f"    ingest fail {p}: {e}")
        print(f"  ingested {ingested} into dense substrate")
        time.sleep(RATE)
        # check remaining
        remaining = len(get_ip_wof(1))
        print(f"  remaining IP wof ~{remaining} (approx, query next batch)")
        if remaining==0:
            break
    print(f"DONE total_archived {total_archived} kept {total_kept} reclassified {total_reclassified}")
    # final counts
    with db_manager.session() as conn:
        for doc_type in ["INVESTOR_PRESENTATION","ANNOUNCEMENT"]:
            row=conn.execute("SELECT COUNT(*), SUM(CASE WHEN local_file_path IS NOT NULL AND TRIM(local_file_path)!='' THEN 1 ELSE 0 END) FROM corporate_documents WHERE doc_type=?", (doc_type,)).fetchone()
            print(f"{doc_type}: total {row[0]} with_file {row[1]}")
        raw=conn.execute("SELECT COUNT(*) FROM raw_documents WHERE source_type='INVESTOR_PRESENTATION'").fetchone()[0]
        print(f"raw_documents INVESTOR_PRESENTATION {raw}")
        try:
            ch=conn.execute("SELECT COUNT(*) FROM document_chunks WHERE source_type='INVESTOR_PRESENTATION'").fetchone()[0]
            print(f"document_chunks INVESTOR_PRESENTATION {ch}")
        except: pass

if __name__=="__main__":
    main()
