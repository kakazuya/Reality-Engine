#!/usr/bin/env python3
"""
Reality Engine Data Packer — creates ≤5GB zip splits for GDrive.
Categories:
  1. price_volume_data — reality_engine/data/bhavcopy
  2. concalls — reality_engine/data/pdfs/**/CONCALL_TRANSCRIPT
  3. ppts — reality_engine/data/pdfs/**/INVESTOR_PRESENTATION
  4. rbi_and_budgets — reality_engine/data/macro_pdfs

Each zip ≤5GB by *uncompressed* accumulated size (so compressed will also be ≤5GB for PDFs).
Uses ZIP_DEFLATED, allowZip64=True, single-writer.
Excludes .env files explicitly.
Logs to stdout and data_pack_split/pack_log.txt
"""
import pathlib
import zipfile
import os
import sys
import time
from datetime import datetime

PROJECT_ROOT = pathlib.Path.cwd()
OUTPUT_DIR = PROJECT_ROOT / "data_pack_split"
# Ensure output dir exists
OUTPUT_DIR.mkdir(exist_ok=True)

MAX_BYTES = 5 * 1024**3  # 5 GiB = 5368709120 bytes ; use GiB as spec says GB; also provide 5*1000^3 note
# Use GiB threshold; if user expects decimal GB (5*1000^3=5e9), GiB is slightly larger so still safely >5e9 but we cap at GiB to guarantee ≤5GB decimal would still be ≤5 GiB? Actually 5 GiB > 5 GB decimal, so to guarantee ≤5GB we should use 5 GB decimal = 5_000_000_000.
# We'll use 5GB decimal = 5_000_000_000 to be absolutely safe for GDrive limit (some providers count decimal).
# Spec says "≤5GB each" — ambiguous GiB vs GB. Use decimal 5_000_000_000 to be safe, plus small buffer 100MB.
# Let's set to 4_900_000_000 to leave compression overhead buffer (~100MB) and ensure compressed <5GB even if ZIP overhead.
# But easiest: use 5*1024^3 and also ensure compressed not exceed — we will verify after.
# We'll use 5 GiB - 50MB buffer = 5318709120

MAX_BYTES = 5 * 1024**3  # keep exact 5GiB per spec instruction "5GB threshold"
# To be safe, we will use 5GB decimal if needed: uncomment next line to tighten
# MAX_BYTES = 5_000_000_000

DATE_STR = "2026-08-31"
LOG_PATH = OUTPUT_DIR / "pack_log.txt"

def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line + "\n")

def collect_files_price_volume():
    root = PROJECT_ROOT / "reality_engine" / "data" / "bhavcopy"
    files = [p for p in root.rglob("*") if p.is_file() and p.name != ".env" and not p.name.startswith(".env.")]
    files.sort()
    return files, root

def collect_files_macro():
    root = PROJECT_ROOT / "reality_engine" / "data" / "macro_pdfs"
    files = [p for p in root.rglob("*") if p.is_file() and p.name != ".env" and not p.name.startswith(".env.")]
    files.sort()
    return files, root

def collect_files_by_parent(parent_name):
    root = PROJECT_ROOT / "reality_engine" / "data" / "pdfs"
    # Walk and pick files where parent directory name == parent_name (e.g., CONCALL_TRANSCRIPT)
    files = []
    for p in root.rglob("*"):
        if p.is_file():
            if p.name == ".env" or p.name.startswith(".env."):
                continue
            if p.parent.name == parent_name:
                # also skip .env in path
                if ".env" in p.parts:
                    continue
                files.append(p)
    files.sort()
    return files, root

def measure_files(files):
    total = sum(p.stat().st_size for p in files)
    return len(files), total

def split_files_by_size(files, max_bytes):
    """Split sorted files into chunks where sum of sizes per chunk ≤ max_bytes"""
    chunks = []
    current = []
    cur_size = 0
    for f in files:
        sz = f.stat().st_size
        # If single file larger than max_bytes (unlikely: largest 122MB), put alone
        if sz > max_bytes:
            if current:
                chunks.append(current)
                current = []
                cur_size = 0
            chunks.append([f])
            continue
        if cur_size + sz > max_bytes and current:
            chunks.append(current)
            current = [f]
            cur_size = sz
        else:
            current.append(f)
            cur_size += sz
    if current:
        chunks.append(current)
    return chunks

def create_zip_chunk(files_chunk, zip_path, base_for_arcname=None):
    """
    Create one zip file from files_chunk.
    arcname: relative to PROJECT_ROOT to preserve reality_engine/data/... structure
    base_for_arcname: if provided, make arcname relative to that base (not used now)
    """
    log(f"Creating {zip_path.name} with {len(files_chunk)} files, raw {sum(p.stat().st_size for p in files_chunk)/1024**3:.3f} GB")
    start = time.time()
    count = 0
    # Ensure parent dir exists
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(zip_path, 'w', compression=zipfile.ZIP_DEFLATED, allowZip64=True, compresslevel=6) as zf:
            for fp in files_chunk:
                # Exclude .env just in case
                if fp.name == ".env" or ".env" in fp.parts:
                    continue
                # Preserve path relative to project root
                try:
                    arc = fp.relative_to(PROJECT_ROOT).as_posix()
                except ValueError:
                    arc = fp.name
                # Also ensure we don't accidentally include .env in arc
                if ".env" in arc:
                    log(f"  SKIP .env path {arc}")
                    continue
                zf.write(fp, arcname=arc)
                count += 1
                if count % 1000 == 0:
                    log(f"  ... {count}/{len(files_chunk)} files written to {zip_path.name}")
        elapsed = time.time() - start
        # Measure zip size
        zsize = zip_path.stat().st_size
        log(f"Finished {zip_path.name}: {count} files, zip size {zsize} bytes ({zsize/1024**3:.3f} GB, {zsize/1024**2:.1f} MB) in {elapsed:.1f}s")
        if zsize > MAX_BYTES:
            log(f"WARNING: {zip_path.name} compressed size {zsize/1024**3:.3f} GB exceeds {MAX_BYTES/1024**3:.3f} GB threshold! Consider tighter splitting.")
        # Also report raw size for audit
        raw = sum(p.stat().st_size for p in files_chunk)
        log(f"  raw size {raw} bytes ({raw/1024**3:.3f} GB) -> compressed ratio {zsize/raw:.3f}" if raw else "  empty chunk")
        return count, zsize
    except Exception as e:
        log(f"ERROR creating {zip_path}: {e}")
        import traceback
        log(traceback.format_exc())
        raise

def process_category(label, files, zip_name_template, split_needed_threshold=MAX_BYTES):
    """
    files: list of Path
    zip_name_template: e.g., "data_pack_price_volume_2026-08-31.zip" or with {part}
    If total raw > MAX_BYTES, split into parts.
    Returns list of (zip_path, file_count, zip_bytes, raw_bytes)
    """
    total_count, total_bytes = measure_files(files)
    log(f"\n=== Category: {label} ===")
    log(f"Source files: {total_count}, raw total {total_bytes} bytes ({total_bytes/1024**3:.3f} GB, {total_bytes/1024**2:.1f} MB)")
    if total_count == 0:
        log(f"  No files for {label}, skipping")
        return []

    # Check for .env leakage
    env_hits = [p for p in files if ".env" in p.name or ".env" in str(p)]
    if env_hits:
        log(f"  FILTERED {len(env_hits)} .env-related paths (excluded)")

    results = []
    if total_bytes > MAX_BYTES:
        chunks = split_files_by_size(files, MAX_BYTES)
        log(f"  Splitting into {len(chunks)} parts (threshold {MAX_BYTES/1024**3:.3f} GB per part)")
        for idx, chunk in enumerate(chunks, start=1):
            raw = sum(p.stat().st_size for p in chunk)
            # Determine zip name
            if "{part}" in zip_name_template:
                zname = zip_name_template.format(part=idx)
            else:
                # auto insert _partN before .zip
                if zip_name_template.endswith(".zip"):
                    zname = zip_name_template[:-4] + f"_part{idx}.zip"
                else:
                    zname = zip_name_template + f"_part{idx}"
            zpath = OUTPUT_DIR / zname
            # Also handle case where single chunk but we already split? Keep naming.
            # If chunk count ==1, we could keep original name without part, but spec says part1 etc for concalls. Keep part naming.
            cnt, zbytes = create_zip_chunk(chunk, zpath)
            results.append((zpath, cnt, zbytes, raw))
    else:
        # Single zip
        zpath = OUTPUT_DIR / zip_name_template
        cnt, zbytes = create_zip_chunk(files, zpath)
        raw = total_bytes
        results.append((zpath, cnt, zbytes, raw))

    return results

def main():
    # Clear log
    if LOG_PATH.exists():
        LOG_PATH.unlink()
    log(f"=== Reality Engine Data Packer started {datetime.now().isoformat()} ===")
    log(f"Project root: {PROJECT_ROOT}")
    log(f"Output dir: {OUTPUT_DIR}")
    log(f"MAX_BYTES per zip (raw): {MAX_BYTES} ({MAX_BYTES/1024**3:.3f} GiB, {MAX_BYTES/1e9:.3f} GB decimal)")
    log(f"Date string: {DATE_STR}")
    log(f"Python: {sys.version}")
    # Ensure no .env in output? Check .env exists
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        log(f"NOTE: .env exists at {env_path} — will be EXCLUDED from all zips")
    else:
        log(f".env not found at project root — no exclusion needed")

    all_results = []

    # 1. price_volume_data
    files, root = collect_files_price_volume()
    res = process_category("price_volume_data (reality_engine/data/bhavcopy)", files, f"data_pack_price_volume_{DATE_STR}.zip")
    all_results.extend(res)

    # 2. concalls
    files, root = collect_files_by_parent("CONCALL_TRANSCRIPT")
    res = process_category("concalls (reality_engine/data/pdfs/**/CONCALL_TRANSCRIPT)", files, f"data_pack_concalls_{DATE_STR}_part{{part}}.zip")
    all_results.extend(res)

    # 3. ppts
    files, root = collect_files_by_parent("INVESTOR_PRESENTATION")
    res = process_category("ppts (reality_engine/data/pdfs/**/INVESTOR_PRESENTATION)", files, f"data_pack_ppts_{DATE_STR}.zip")
    all_results.extend(res)

    # 4. rbi_and_budgets
    files, root = collect_files_macro()
    res = process_category("rbi_and_budgets (reality_engine/data/macro_pdfs)", files, f"data_pack_macro_rbi_budgets_{DATE_STR}.zip")
    all_results.extend(res)

    # Summary
    log("\n=== SUMMARY ===")
    total_zip_bytes = 0
    total_files = 0
    total_raw = 0
    for zpath, cnt, zbytes, raw in all_results:
        gb = zbytes / 1024**3
        gb_raw = raw / 1024**3
        log(f"{zpath.name} : {cnt} files, zip {zbytes} bytes ({gb:.3f} GB), raw {raw} bytes ({gb_raw:.3f} GB) -> {zpath}")
        total_zip_bytes += zbytes
        total_files += cnt
        total_raw += raw

    log(f"\nTOTAL: {len(all_results)} zip(s), {total_files} files, combined zip size {total_zip_bytes} bytes ({total_zip_bytes/1024**3:.3f} GB, {total_zip_bytes/1e9:.3f} GB decimal)")
    log(f"Combined raw size {total_raw} bytes ({total_raw/1024**3:.3f} GB)")
    # List output dir
    log("\n=== Output directory listing ===")
    for p in sorted(OUTPUT_DIR.glob("*.zip")):
        sz = p.stat().st_size
        log(f"  {p.name} : {sz/1024**3:.3f} GB ({sz/1024**2:.1f} MB) : {p}")
    # Also check for project root zips (if any)
    for p in sorted(PROJECT_ROOT.glob("data_pack_*.zip")):
        sz = p.stat().st_size
        log(f"  ROOT {p.name} : {sz/1024**3:.3f} GB")

    # Verify each zip <=5GB compressed
    log("\n=== Verification <=5GB (compressed) ===")
    ok = True
    for zpath, cnt, zbytes, raw in all_results:
        if zbytes > 5 * 1024**3:
            log(f"FAIL: {zpath.name} is {zbytes/1024**3:.3f} GB >5 GiB")
            ok = False
        elif zbytes > 5_000_000_000:
            log(f"WARN: {zpath.name} is {zbytes/1e9:.3f} GB decimal >5.0 GB (but <=5 GiB)")
        else:
            log(f"PASS: {zpath.name} {zbytes/1024**3:.3f} GiB OK")
    if ok:
        log("All zips PASS compressed <=5 GiB")
        log("Some zips exceed limit -- recommend re-split with tighter MAX_BYTES")

    # Verify .env not in any zip
    log("\n=== Verify .env not in zips ===")
    for zpath, _, _, _ in all_results:
        with zipfile.ZipFile(zpath, 'r') as zf:
            names = zf.namelist()
            env_in = [n for n in names if ".env" in n]
            if env_in:
                log(f"FAIL: .env found in {zpath.name}: {env_in[:5]}")
                ok = False
            else:
                log(f"PASS: no .env in {zpath.name} ({len(names)} entries)")
    log("\n=== Done ===")

if __name__ == "__main__":
    main()
