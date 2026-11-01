"""Cut the thin deck pages, plus a random check sample of image-backed pages, into one-page PDFs and send them to the HP."""
import json
import random
import sqlite3
import sys
import tarfile
from pathlib import Path

import pymupdf

sys.path.insert(0, "reality_engine/scripts")
import hp_run  # noqa: E402

ISINS = ("INE296A01032", "INE038A01020", "INE389H01022")
OUT = Path(r"C:\Users\warri\AppData\Local\Temp\claude\C--Users-warri-Downloads-Info-Diffusion-Model\b8444ef0-b222-4eab-a05a-1767a1698f9d\scratchpad\thin")
OUT.mkdir(exist_ok=True)
c = sqlite3.connect("file:reality_engine/data/pilot/pilot60/chunks_v3_pilot.db?mode=ro", uri=True)
plan, pool = [], []
for isin, sym, dt, sha, path, known in c.execute("select isin, symbol_at_time, doc_type, sha256, raw_path, known_at from doc where isin in (?,?,?) and doc_type='deck'", ISINS).fetchall():
    with pymupdf.open(path) as pdf:
        for i, page in enumerate(pdf, 1):
            row = {"isin": isin, "symbol": sym, "doc_type": dt, "doc_date": str(known)[:10], "sha256": sha, "page": i, "existing_chars": len(page.get_text()), "existing_text": page.get_text()}
            if row["existing_chars"] < 200:
                plan.append({**row, "why": "thin"})
            elif page.get_images():
                pool.append({**row, "why": "layer_check"})
random.Random(20261102).shuffle(pool)
plan += pool[:100]
tar_path = OUT / "proto3_pages.tar"
with tarfile.open(tar_path, "w") as tar:
    by_doc = {}
    for row in plan:
        by_doc.setdefault(row["sha256"], []).append(row)
    paths = {s: p for s, p in c.execute("select sha256, raw_path from doc where isin in (?,?,?)", ISINS)}
    for sha, rows in by_doc.items():
        with pymupdf.open(paths[sha]) as src:
            for row in rows:
                one = pymupdf.open()
                one.insert_pdf(src, from_page=row["page"] - 1, to_page=row["page"] - 1)
                name = f"{sha[:16]}_{row['page']:04d}.pdf"
                row["file_name"] = name
                one.save(OUT / name)
                one.close()
                tar.add(OUT / name, arcname=name)
                (OUT / name).unlink()
    (OUT / "plan.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in plan), encoding="utf-8")
    tar.add(OUT / "plan.jsonl", arcname="plan.jsonl")
print("pages", len(plan), "thin", sum(r["why"] == "thin" for r in plan), "tar MB", round(tar_path.stat().st_size / 1e6, 1))
print(hp_run._ssh(["powershell", "-NoProfile", "-Command", "New-Item -ItemType Directory -Force C:/RE/raw/proto3_pages | Out-Null; 'ok'"]).stdout)
done = hp_run._ssh(["tar", "-xf", "-", "-C", "C:/RE/raw/proto3_pages"], input_bytes=tar_path.read_bytes())
print("untar rc", done.returncode, done.stderr[:200])
print(hp_run._ssh(["powershell", "-NoProfile", "-Command", "(Get-ChildItem C:/RE/raw/proto3_pages).Count"]).stdout)
