import pathlib, zipfile, os, sys, time
base = pathlib.Path(r"C:\Users\warri\Downloads\Info_Diffusion_Model")
pack = base / "data_pack_2026-08-31"
db_path = base / "reality_engine" / "data" / "equity_intelligence.db"
db_zip_path = pack / "equity_intelligence.db.zip"
outer_zip = base / "data_pack_2026-08-31.zip"

print(f"Compressing DB {db_path} -> {db_zip_path}")
print(f"DB size {db_path.stat().st_size/1024/1024/1024:.2f} GB")
start = time.time()
# use ZIP_DEFLATED, allowZip64, compresslevel 1 for speed? default 6
# For large DB, use compresslevel 1 to be faster but still decent ratio. Requirement says ZIP_DEFLATED.
try:
    with zipfile.ZipFile(db_zip_path, 'w', compression=zipfile.ZIP_DEFLATED, allowZip64=True, compresslevel=1) as z:
        # arcname just equity_intelligence.db
        z.write(db_path, arcname="equity_intelligence.db")
    print(f"DB zip done in {time.time()-start:.1f}s, size {db_zip_path.stat().st_size/1024/1024:.1f} MB")
except Exception as e:
    print(f"DB zip failed {e}", file=sys.stderr)
    raise

# final outer zip
print(f"Creating outer zip {outer_zip}")
start = time.time()
# outer will contain README, substrate/, audit/, fetch_manifest, and DB zip
# Exclude .env, logs, pdfs, lancedb already not in pack
with zipfile.ZipFile(outer_zip, 'w', compression=zipfile.ZIP_DEFLATED, allowZip64=True, compresslevel=1) as outer:
    for p in pack.rglob("*"):
        if p.is_file():
            # preserve relative to base? want data_pack_2026-08-31/ prefix inside zip
            arc = p.relative_to(base)
            # skip if somehow .env inside pack? not
            outer.write(p, arcname=str(arc))
            print(f" added {arc} {p.stat().st_size/1024/1024:.2f} MB")
# also ensure we didn't double-add outer zip itself
elapsed = time.time()-start
size_mb = outer_zip.stat().st_size/1024/1024
print(f"Outer zip done in {elapsed:.1f}s, size {size_mb:.1f} MB ({size_mb/1024:.2f} GB)")
# verify contents
with zipfile.ZipFile(outer_zip, 'r') as z:
    infos = z.infolist()
    print(f"Outer contains {len(infos)} entries:")
    for i in infos[:50]:
        print(f"  {i.filename} {i.file_size/1024/1024:.2f} MB comp {i.compress_size/1024/1024:.2f} MB")
    if len(infos)>50:
        print(f"  ... +{len(infos)-50} more")
