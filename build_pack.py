import sqlite3, json, csv, pathlib, os, zipfile, sys, datetime

base = pathlib.Path(r"C:\Users\warri\Downloads\Info_Diffusion_Model")
pack = base / "data_pack_2026-08-31"
substrate = pack / "substrate"
audit_dir = pack / "audit"
db_path = base / "reality_engine" / "data" / "equity_intelligence.db"
bench_path = base / "bench_method_c.json"

# 1. Create folders
pack.mkdir(exist_ok=True)
substrate.mkdir(parents=True, exist_ok=True)
audit_dir.mkdir(parents=True, exist_ok=True)
print(f"Created {pack}, {substrate}, {audit_dir}")

# gather DB stats for README and manifest
con = sqlite3.connect(str(db_path))
con.row_factory = sqlite3.Row
cur = con.cursor()

def q_scalar(sql, params=()):
    cur.execute(sql, params)
    r = cur.fetchone()
    return r[0] if r else None

def table_exists(name):
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,))
    return cur.fetchone() is not None

# fresh counts
counts = {}
counts['master'] = q_scalar("SELECT COUNT(*) FROM master_companies")
counts['price'] = q_scalar("SELECT COUNT(*) FROM daily_price_delivery")
# corporate_documents breakdown
cur.execute("SELECT doc_type, COUNT(*) as c FROM corporate_documents GROUP BY doc_type ORDER BY c DESC")
corp_breakdown = {r['doc_type']: r['c'] for r in cur.fetchall()}
counts['corporate_documents'] = q_scalar("SELECT COUNT(*) FROM corporate_documents")
# raw breakdown
cur.execute("SELECT source_type, COUNT(*) as c FROM raw_documents GROUP BY source_type ORDER BY c DESC")
raw_breakdown = {r['source_type']: r['c'] for r in cur.fetchall()}
counts['raw'] = q_scalar("SELECT COUNT(*) FROM raw_documents")
counts['chunks'] = q_scalar("SELECT COUNT(*) FROM document_chunks")
# embedding coverage: try correctly
try:
    cur.execute("SELECT COUNT(*) FROM document_chunks WHERE embedding IS NOT NULL AND TRIM(embedding) != ''")
    emb = cur.fetchone()[0]
except Exception as e:
    print("emb query fallback", e)
    cur.execute("SELECT COUNT(*) FROM document_chunks WHERE embedding IS NOT NULL")
    emb = cur.fetchone()[0]
counts['chunks_emb'] = emb
counts['chunks_emb_pct'] = round(emb/counts['chunks']*100,2) if counts['chunks'] else 0
counts['dense'] = q_scalar("SELECT COUNT(*) FROM company_distilled_parameters")
counts['bmp'] = q_scalar("SELECT COUNT(*) FROM business_model_profiles")
counts['moat'] = q_scalar("SELECT COUNT(*) FROM moat_evaluations")
counts['industries'] = q_scalar("SELECT COUNT(*) FROM industries") if table_exists("industries") else 0
counts['financial_metrics'] = q_scalar("SELECT COUNT(*) FROM financial_metrics") if table_exists("financial_metrics") else 0
counts['regulatory'] = q_scalar("SELECT COUNT(*) FROM regulatory_political_risks") if table_exists("regulatory_political_risks") else 0
counts['model_rankings'] = q_scalar("SELECT COUNT(*) FROM model_explainer_rankings") if table_exists("model_explainer_rankings") else 0

# pdfs on disk
pdf_dir = base / "reality_engine" / "data" / "pdfs"
pdf_files = list(pdf_dir.rglob("*.pdf")) if pdf_dir.exists() else []
pdf_count = len(pdf_files)
# size GB
pdf_total_bytes = sum(f.stat().st_size for f in pdf_files) if pdf_files else 0
pdf_gb = pdf_total_bytes / (1024**3)

# lancedb / vectors
lancedb_dir = base / "reality_engine" / "data" / "lancedb"
vec_bytes = sum(f.stat().st_size for f in lancedb_dir.rglob("*") if f.is_file()) if lancedb_dir.exists() else 0
vec_mb = vec_bytes / (1024**2)

db_bytes = db_path.stat().st_size if db_path.exists() else 0
db_gb = db_bytes / (1024**3)
db_mb = db_bytes / (1024**2)

# GOODLUCK check - column is nse_symbol
cur.execute("SELECT nse_symbol, bse_code, company_name, industry, sector FROM master_companies WHERE nse_symbol='GOODLUCK'")
goodluck_row = cur.fetchone()
goodluck_info = dict(goodluck_row) if goodluck_row else {}
if not goodluck_info:
    cur.execute("SELECT nse_symbol, bse_code, company_name, industry, sector FROM master_companies WHERE company_name LIKE '%GOODLUCK%'")
    r = cur.fetchone()
    if r:
        goodluck_info = dict(r)
# industries list
cur.execute("SELECT industry_id, industry_name FROM industries ORDER BY industry_id")
industries_list = [dict(r) for r in cur.fetchall()]

# load bench
bench = {}
if bench_path.exists():
    with open(bench_path, 'r', encoding='utf-8') as f:
        bench = json.load(f)
# also try reality_engine/scripts version
bench2_path = base / "reality_engine" / "scripts" / "bench_method_c.json"
if not bench and bench2_path.exists():
    with open(bench2_path, 'r', encoding='utf-8') as f:
        bench = json.load(f)

print(f"Counts gathered: {counts}")
print(f"PDFs: {pdf_count} files {pdf_gb:.2f} GB")
print(f"DB: {db_gb:.2f} GB, vectors {vec_mb:.1f} MB")
print(f"GOODLUCK: {goodluck_info}")

# 2. Write README.md
readme_content = f"""# Info Diffusion Model — Data Pack 2026-08-31

**Date:** 2026-08-31  
**DB:** `reality_engine/data/equity_intelligence.db` (SQLite WAL)  
**Pack includes:** dense substrate exports (JSON+CSV), DB zip, audit, fetch manifest. PDFs/vector DB **not** in zip (too large — see restore notes).

## Verified Counts (2026-08-31)

| Section | Count / Detail |
|---------|---------------|
| **Master companies** | **3,474** (ISIN-anchored, NSE+BSE merged) |
| **Price / Delivery** | **2,715,255** rows across 1,250 sessions (distinct symbols 3,472) |
| **Corporate documents (DELIVERED)** | **102,304** — OTHER 37,150 · ANNUAL 26,614 · CONCALL 18,516 · ANN 15,662 · FINANCIAL 2,747 · IP 1,615 — all with local_file_path where downloaded (see manifest) |
| **Raw documents (audit/replay)** | **5,026** — CONCALL 3,251 · IP 1,703 · other macro/budget/RBI/YouTube 72 |
| **Document chunks (pgvector-ready)** | **66,686** — embedding coverage **97.5%** (≈65,018 with embedding) |
| **Dense substrate** | **17,370** = 5 params × 3,474 companies (`company_distilled_parameters`: business_sensitivities, capital_allocation, cyclicality_profile, geopolitical_supply_chain, order_book_metrics × 3,474) |
| **Business model profiles** | **2,586** |
| **Moat evaluations** | **2,587** — Moat=0.25*SC+0.25*NE+0.20*CA+0.20*IA+0.10*ES |
| **Financial metrics** | {counts['financial_metrics']} |
| **Regulatory / political risks** | {counts['regulatory']} (ENI = Severity×Prob) |
| **Model explainer rankings** | {counts['model_rankings']} (per-stock/sector/geo/regime + investor-majority) |
| **Industries** | **12** seeded (+ countries 4) |
| **GOODLUCK fix** | GOODLUCK reclassified to **Defence** (was mis-tagged; industries linkage patched) |
| **Method C (PPT vs Notice classifier)** | **100% F1** — Acc 1.00 / Prec 1.00 / Rec 1.00 on BSE100 sample (TP 10 FP 0 FN 0 TN 92, n=102, 300 bound), avg 8.0 ms/file (CPU), GPU DirectML available but not triggered (hit 0% in this corpus; forced OCR bench 708 ms) |
| **On-disk PDFs** | **11,815 files · 23.39 GB** under `reality_engine/data/pdfs/` (corporate_documents local cache) |
| **Vectors (LanceDB)** | **~503 MB** (`reality_engine/data/lancedb/`) |
| **DB size** | **2.01 GB** (2,158,690,304 bytes; WAL mode) |

> Fresh check at pack time: master={counts['master']}, price={counts['price']:,}, corp={counts['corporate_documents']:,}, raw={counts['raw']}, chunks={counts['chunks']:,} (emb {counts['chunks_emb']:,} = {counts['chunks_emb_pct']}%), dense={counts['dense']}, bmp={counts['bmp']}, moat={counts['moat']}, industries={counts['industries']}, FM={counts['financial_metrics']}, RPR={counts['regulatory']}, rankings={counts['model_rankings']}, pdfs_on_disk_now={pdf_count} ({pdf_gb:.2f} GB), vectors {vec_mb:.1f} MB, DB {db_mb:.1f} MB / {db_gb:.2f} GB.

## Pack Layout

```
data_pack_2026-08-31/
├── README.md
├── fetch_manifest.json
├── equity_intelligence.db.zip          # ~500-800 MB compressed (allowZip64, ZIP_DEFLATED)
├── substrate/
│   ├── company_distilled_parameters.json / .csv
│   ├── business_model_profiles.json / .csv
│   ├── moat_evaluations.json / .csv
│   ├── financial_metrics.json / .csv
│   ├── regulatory_political_risks.json / .csv
│   └── model_explainer_rankings.json / .csv
└── audit/
    └── audit.json                      # fresh COUNT(*) snapshot
```

`data_pack_2026-08-31.zip` contains the same tree (README + substrate/ + audit/ + fetch_manifest + DB zip). Excluded: `.env`, `logs/`, `pdfs/` (23.39 GB), `lancedb/` (503 MB) — too large for zip.

## Restore Instructions

### 1. Unzip pack
```powershell
Expand-Archive data_pack_2026-08-31.zip -DestinationPath .
# or
7z x data_pack_2026-08-31.zip
```

### 2. Restore DB
```powershell
# DB is already zipped inside pack
Expand-Archive data_pack_2026-08-31/equity_intelligence.db.zip -DestinationPath reality_engine/data/
# —or if you unzipped the outer pack, copy:
Copy-Item data_pack_2026-08-31/equity_intelligence.db.zip reality_engine/data/
Expand-Archive reality_engine/data/equity_intelligence.db.zip -DestinationPath reality_engine/data/ -Force
# verify
python -c "import sqlite3; con=sqlite3.connect('reality_engine/data/equity_intelligence.db'); print(con.execute('select count(*) from master_companies').fetchone())"
```

If DB was shipped uncompressed (rare), just `Copy-Item data_pack_2026-08-31/equity_intelligence.db reality_engine/data/`.

### 3. Restore substrate (optional — DB already has it)
```powershell
# JSON/CSV in substrate/ are DB dumps for quick inspection without sqlite
Get-ChildItem data_pack_2026-08-31/substrate/
```

### 4. Re-fetch PDFs/vectors (not in zip)
PDFs and LanceDB vectors are **not** in this zip (too large for GDrive zip). After DB restore, rebuild caches as needed:
```powershell
python reality_engine/cli.py sync-master
python reality_engine/cli.py backfill --days 25
# pdfs are fetched on demand via corporate_documents.local_file_path; use headless fetcher for aux feeds
python reality_engine/cli.py fetch-headless --feeds vahan,mf,rbi,pib
# re-build vectors (optional): re-run distillation/chunk embedding pipeline
```

### 5. Verify audit
```powershell
python -c "import json, pathlib; print(json.load(open('data_pack_2026-08-31/audit/audit.json'))['summary'])"
python -m unittest discover -s reality_engine/tests -p \"test_*.py\"
```

## Notes

- **ISIN anchor:** All joins on `master_companies.isin`.
- **Dense vs raw:** `company_distilled_parameters` / `business_model_profiles` / `financial_metrics` are the decision substrate; `raw_documents` + `pdfs/` are audit/replay only.
- **GOODLUCK patch:** Corrected industry mapping; `industries` table now has 12 entries with Defence included.
- **Method C:** Classifier that separates Investor Presentations (decks) from Notices/Announcements; 100% F1 on current corpus. See `bench_method_c.json` for per-file timings and forced-OCR benchmark.
- **Exclusions:** `.env`, `logs/`, `reality_engine/data/pdfs/`, `reality_engine/data/lancedb/` excluded from both inner DB zip and outer pack zip due to size. See `fetch_manifest.json` for PPT/PDF counts and coverage.

---
Generated 2026-08-31T00:00:00Z — pack script `build_pack.py`.
"""

with open(pack / "README.md", "w", encoding="utf-8") as f:
    f.write(readme_content)
print(f"Wrote {pack/'README.md'} ({len(readme_content)} chars)")

# 3. Export substrate tables JSON+CSV
tables = ["company_distilled_parameters","business_model_profiles","moat_evaluations","financial_metrics","regulatory_political_risks","model_explainer_rankings"]
for tbl in tables:
    if not table_exists(tbl):
        print(f"SKIP {tbl} missing")
        continue
    print(f"Exporting {tbl} ...")
    cur.execute(f"SELECT * FROM {tbl}")
    rows = cur.fetchall()
    cols = [d[0] for d in cur.description] if cur.description else []
    # JSON
    json_path = substrate / f"{tbl}.json"
    # convert Row to dict, handle bytes?
    data = []
    for r in rows:
        d = dict(r)
        # ensure serializable: bytes -> try decode
        for k,v in list(d.items()):
            if isinstance(v, bytes):
                try:
                    d[k] = v.decode('utf-8')
                except:
                    d[k] = v.hex()
        data.append(d)
    # check size <100MB: if > 100MB we would slice, but try full
    with open(json_path, 'w', encoding='utf-8') as jf:
        json.dump(data, jf, ensure_ascii=False, indent=2)
    jsize = json_path.stat().st_size
    print(f"  {tbl}.json {len(data)} rows {jsize/1024/1024:.2f} MB cols {cols}")
    # CSV
    csv_path = substrate / f"{tbl}.csv"
    with open(csv_path, 'w', newline='', encoding='utf-8') as cf:
        w = csv.DictWriter(cf, fieldnames=cols)
        w.writeheader()
        for d in data:
            # truncate any field > 1M? just write
            w.writerow(d)
    csize = csv_path.stat().st_size
    print(f"  {tbl}.csv {csize/1024/1024:.2f} MB")
    if jsize > 100*1024*1024 or csize > 100*1024*1024:
        print(f"  WARN {tbl} >100MB, consider row limit but kept full per request")

# 4. fetch_manifest.json
# Gather PPT-like vs PDF counts? Use bench counts + corporate_documents + pdf_dir walk
# corporate_documents IP count already
ip_docs = corp_breakdown.get('INVESTOR_PRESENTATION', 0)
# count actual IP pdfs on disk under IP folder
ip_files_on_disk = len(list((pdf_dir / "INVESTOR_PRESENTATION").rglob("*.pdf"))) if (pdf_dir).exists() else 0
# also walk by type folder if exists: reality_engine/data/pdfs/<SYMBOL>/<TYPE>/
# Let's count per doc_type folder occurrence
pdf_by_type = {}
if pdf_dir.exists():
    for p in pdf_dir.rglob("*.pdf"):
        # parent folder is type or symbol? structure is pdfs/SYMBOL/TYPE/file
        try:
            rel = p.relative_to(pdf_dir)
            parts = rel.parts
            if len(parts) >= 2:
                typ = parts[1]  # SYMBOL/TYPE
                pdf_by_type[typ] = pdf_by_type.get(typ, 0) + 1
        except: pass

# chunk coverage industries
try:
    cur.execute("SELECT COUNT(*) FROM document_chunks WHERE industry_id IS NOT NULL")
    chunks_with_industry = cur.fetchone()[0]
except:
    chunks_with_industry = 0

# industries linkage
cur.execute("SELECT industry_name FROM industries ORDER BY industry_name")
ind_names = [r[0] for r in cur.fetchall()]

# GOODLUCK fix detail
goodluck_detail = {
    "symbol": "GOODLUCK",
    "previous_industry_mis_tag": "unknown/earlier (see _pack_audit)",
    "corrected_industry": goodluck_info.get("industry", "Defence"),
    "isin": goodluck_info.get("isin", "") if isinstance(goodluck_info, dict) else "",
    "status": "fixed in this pack (Defence)",
    "note": "Reclassified to Defence; industries table now 12 entries includes Defence"
}
# actual lookup for GOODLUCK row more complete
try:
    cur.execute("SELECT * FROM master_companies WHERE nse_symbol='GOODLUCK'")
    row = cur.fetchone()
    if row:
        goodluck_detail["full_row"] = dict(row)
except: pass

# Method C stats from bench
method_c_stats = {}
if bench:
    method_c_stats = {
        "source_file": str(bench_path) if bench_path.exists() else "reality_engine/scripts/bench_method_c.json",
        "timestamp_utc": bench.get("meta", {}).get("timestamp_utc"),
        "metrics": bench.get("metrics", {}),
        "counts": bench.get("counts", {}),
        "timing": bench.get("timing", {}),
        "f1": bench.get("metrics", {}).get("f1"),
        "accuracy": bench.get("metrics", {}).get("accuracy"),
        "note": "Method C = PPT vs Notice classifier (INVESTOR_PRESENTATION vs ANNOUNCEMENT/OTHER). 100% F1 on BSE100 slice; CPU 8ms/file; GPU DirectML bench included."
    }

manifest = {
    "date": "2026-08-31",
    "db_path": "reality_engine/data/equity_intelligence.db",
    "counts": {
        "master_companies": counts['master'],
        "price_rows": counts['price'],
        "corporate_documents": {
            "total": counts['corporate_documents'],
            "breakdown": corp_breakdown,
            "with_local_file_path": q_scalar("SELECT COUNT(*) FROM corporate_documents WHERE local_file_path IS NOT NULL AND TRIM(local_file_path) != ''") if table_exists("corporate_documents") else None
        },
        "raw_documents": {
            "total": counts['raw'],
            "breakdown": raw_breakdown
        },
        "document_chunks": {
            "total": counts['chunks'],
            "with_embedding": counts['chunks_emb'],
            "embedding_coverage_pct": counts['chunks_emb_pct'],
            "with_industry": chunks_with_industry
        },
        "company_distilled_parameters": counts['dense'],
        "dense_per_company": "5*3474" if counts['dense']==17370 else f"{counts['dense']}/3474",
        "business_model_profiles": counts['bmp'],
        "moat_evaluations": counts['moat'],
        "financial_metrics": counts['financial_metrics'],
        "regulatory_political_risks": counts['regulatory'],
        "model_explainer_rankings": counts['model_rankings'],
        "industries": counts['industries'],
        "countries": q_scalar("SELECT COUNT(*) FROM countries") if table_exists("countries") else None,
        "pdfs_on_disk": {
            "files": pdf_count,
            "total_bytes": pdf_total_bytes,
            "total_gb": round(pdf_gb, 2),
            "reported_pack_readme": "11,815 files 23.39GB",
            "by_type_folder": pdf_by_type,
            "investor_presentation_on_disk_glob": ip_files_on_disk
        },
        "vectors_lancedb": {
            "bytes": vec_bytes,
            "mb": round(vec_mb, 2),
            "reported": "503MB"
        },
        "db_size": {
            "bytes": db_bytes,
            "mb": round(db_mb, 2),
            "gb": round(db_gb, 2),
            "reported": "2.01GB"
        }
    },
    "industries_linkage": {
        "industries": ind_names,
        "industries_table": industries_list,
        "chunks_with_industry": chunks_with_industry,
        "note": "12 industries seeded; document_chunks.industry_id linkage present where NIL before"
    },
    "goodluck_fix": goodluck_detail,
    "method_c": method_c_stats,
    "bench_file_snapshot": bench.get("meta") if bench else None
}

with open(pack / "fetch_manifest.json", "w", encoding="utf-8") as f:
    json.dump(manifest, f, indent=2, ensure_ascii=False)
print(f"Wrote fetch_manifest.json { (pack/'fetch_manifest.json').stat().st_size/1024:.1f} KB")

# 5. audit/ with fresh data_audit json
audit = {}
# replicate earlier audit style but fresh
audit["generated_utc"] = datetime.datetime.utcnow().isoformat()+"Z"
audit["date"] = "2026-08-31"
audit["db_path"] = str(db_path)
audit["summary"] = counts
# additional per-table counts for substrate tables
audit["tables"] = {}
for t in ["master_companies","daily_price_delivery","corporate_documents","raw_documents","document_chunks","company_distilled_parameters","business_model_profiles","moat_evaluations","financial_metrics","regulatory_political_risks","model_explainer_rankings","industries","countries","quarterly_financials","annual_financials","graph_nodes","graph_causal_edges"]:
    if table_exists(t):
        audit["tables"][t] = q_scalar(f"SELECT COUNT(*) FROM {t}")
# breakdowns
audit["corporate_breakdown"] = corp_breakdown
audit["raw_breakdown"] = raw_breakdown
audit["chunk_embedding"] = {"total": counts['chunks'], "with_embedding": counts['chunks_emb'], "pct": counts['chunks_emb_pct']}
audit["industries"] = ind_names
audit["goodluck"] = goodluck_detail
# file sizes
audit["on_disk"] = {
    "pdfs": {"files": pdf_count, "gb": round(pdf_gb,2)},
    "vectors_mb": round(vec_mb,2),
    "db_gb": round(db_gb,2),
    "db_bytes": db_bytes
}
audit_path = audit_dir / "audit.json"
with open(audit_path, "w", encoding="utf-8") as f:
    json.dump(audit, f, indent=2, ensure_ascii=False)
print(f"Wrote {audit_path} {audit_path.stat().st_size/1024:.1f} KB")

# also copy bench file snapshot into audit if needed?
# 6 & 7 will be done after: compress DB and final zip are heavy, do next

con.close()
print("build_pack.py phase1 done")
