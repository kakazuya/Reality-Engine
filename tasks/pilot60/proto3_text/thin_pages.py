"""Send every PDF of the 3 companies to the HP with a plan of every page, for OCR (T-040).

Each page is marked: "thin" has under 400 characters on the PDF page, so its OCR text is added
as a passage; "layer_check" keeps the text layer for reading, and its OCR text is the second
source for the number check. All 352 pages under 200 sit inside multi-page chunks, so chunk
length cannot show this. KEC's transcripts are included so they are covered once loaded.
"""
import json
import sqlite3
import sys
import tarfile
from pathlib import Path

import pymupdf

sys.path.insert(0, "reality_engine/scripts")
import hp_run  # noqa: E402

ISINS = ("INE296A01032", "INE038A01020", "INE389H01022")
THIN_CHARS = 400
OUT = Path(".tmp/proto3/all_pages")
OUT.mkdir(parents=True, exist_ok=True)
KEC = Path(r"D:\RealityEngine\raw\kec_transcripts")

con = sqlite3.connect("file:reality_engine/data/pilot/pilot60/chunks_v3_pilot.db?mode=ro", uri=True)
docs = [
    {"isin": isin, "symbol": sym, "doc_type": dt, "doc_date": str(known)[:10], "sha256": sha, "path": path}
    for isin, sym, dt, sha, path, known in con.execute(
        "select isin, symbol_at_time, doc_type, sha256, raw_path, known_at from doc where isin in (?,?,?)", ISINS)
]
for pair in json.loads((KEC / "_known_at.json").read_text(encoding="utf-8")):
    docs.append({"isin": "INE389H01022", "symbol": "KEC", "doc_type": "concall", "doc_date": pair["known_at"][:10],
                 "sha256": pair["sha256"], "path": str(KEC / f"{pair['sha256']}.pdf")})

plan, sent, skipped = [], {}, []
for doc in docs:
    try:
        pdf = pymupdf.open(doc["path"])
    except Exception as exc:  # noqa: BLE001 - reported below, never dropped silently
        skipped.append((doc["doc_type"], doc["path"], str(exc)[:80]))
        continue
    with pdf:
        file_name = f"{doc['sha256'][:16]}.pdf"
        sent[file_name] = doc["path"]
        for number, page in enumerate(pdf, 1):
            text = page.get_text()
            plan.append({"isin": doc["isin"], "symbol": doc["symbol"], "doc_type": doc["doc_type"],
                         "doc_date": doc["doc_date"], "sha256": doc["sha256"], "file_name": file_name,
                         "page": number, "existing_chars": len(text), "existing_text": text,
                         "why": "thin" if len(text) < THIN_CHARS else "layer_check"})

(OUT / "plan.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in plan), encoding="utf-8")
tar_path = OUT / "proto3_docs.tar"
with tarfile.open(tar_path, "w") as tar:
    tar.add(OUT / "plan.jsonl", arcname="plan.jsonl")
    for name, path in sent.items():
        tar.add(path, arcname=name)
print("docs", len(docs), "pdfs", len(sent), "pages", len(plan), "thin", sum(r["why"] == "thin" for r in plan),
      "tar MB", round(tar_path.stat().st_size / 1e6, 1))
print("skipped", len(skipped), skipped[:10])
print("HP free GB", hp_run.ps("[math]::Round((Get-PSDrive C).Free/1GB,1)").strip())
dest = hp_run.remote("raw", "proto3_docs")
hp_run.ps(f"New-Item -ItemType Directory -Force -Path '{dest}' | Out-Null")
done = hp_run._ssh(["tar", "-xf", "-", "-C", dest], input_bytes=tar_path.read_bytes(), timeout=3000)
print("untar rc", done.returncode)
print("files on HP", hp_run.ps(f"(Get-ChildItem '{dest}').Count").strip(), "expected", len(sent) + 1)
