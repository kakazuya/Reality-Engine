"""Verify the fetched decks and render the 200 sampled pages exactly like the deck pipeline.

The deck reader (reality_engine/scripts/extract_deck_figures.py, render_jpeg_b64) does NOT use a fixed DPI: it sets
zoom = 1600 / max(page.width, page.height), i.e. the longest side is 1600 px, JPEG quality 85. This script renders PNG
at the same pixel size (lossless, so OCR is not charged for JPEG artefacts the vision reader also saw).

Outputs: work/pdfs/<sha>.pdf, work/pages/<sha>_pNNN.png, work/text/<sha>_pNNN.txt, work/pages.json
"""
import hashlib
import json
import os
import shutil
import sys
import time
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
from reality_engine.scripts.extract_deck_figures import text_numbers  # noqa: E402

WORK = ROOT / "work"
MAX_SIDE = 1600


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def layout_features(page):
    """Cheap page-type evidence from vector drawings: table rules vs chart paths vs sparse KPI tiles."""
    w, h = page.rect.width, page.rect.height
    hl = vl = curves = 0
    for d in page.get_drawings():
        r = d["rect"]
        if r.width > 0.25 * w and r.height < 2.5:
            hl += 1
        if r.height > 0.15 * h and r.width < 2.5:
            vl += 1
        curves += sum(1 for it in d["items"] if it[0] in ("c", "qu"))
    sizes = [s["size"] for b in page.get_text("dict")["blocks"] if b.get("type") == 0
             for l in b["lines"] for s in l["spans"]]
    return {"h_rules": hl, "v_rules": vl, "curves": curves, "max_font": round(max(sizes), 1) if sizes else 0}


def main():
    sample = json.loads((WORK / "sample.json").read_text(encoding="utf-8"))
    (WORK / "pdfs").mkdir(parents=True, exist_ok=True)
    (WORK / "pages").mkdir(parents=True, exist_ok=True)
    (WORK / "text").mkdir(parents=True, exist_ok=True)
    by_sha = {}
    for p in sample:
        by_sha.setdefault(p["sha256"], []).append(p)
    pages_out, bad = [], []
    for sha, ps in by_sha.items():
        src = WORK / "gdrive" / ps[0]["remote"]
        dst = WORK / "pdfs" / f"{sha}.pdf"
        if not src.exists():
            bad.append({"sha256": sha, "error": "missing pdf", "remote": ps[0]["remote"]})
            continue
        got = sha256(src)
        if got != sha:
            bad.append({"sha256": sha, "error": f"sha mismatch {got}", "remote": ps[0]["remote"]})
            continue
        if not dst.exists():
            shutil.copyfile(src, dst)
        try:
            with pymupdf.open(dst) as doc:
                for p in ps:
                    no = p["page_no"]
                    if no > doc.page_count:
                        bad.append({"sha256": sha, "page_no": no, "error": f"page {no} > {doc.page_count}"})
                        continue
                    page = doc[no - 1]
                    t0 = time.time()
                    zoom = MAX_SIDE / max(page.rect.width, page.rect.height)
                    pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
                    png = WORK / "pages" / f"{sha}_p{no:03d}.png"
                    pix.save(png)
                    secs = time.time() - t0
                    text = page.get_text()
                    (WORK / "text" / f"{sha}_p{no:03d}.txt").write_text(text, encoding="utf-8")
                    feats = layout_features(page)
                    pages_out.append({**p, "render_s": round(secs, 3), "px": [pix.width, pix.height],
                                      "pdf_pages": doc.page_count, "text_numbers_check": len(text_numbers(text)),
                                      "text_chars_check": len(text.strip()), **feats})
        except Exception as e:  # a malformed PDF should not stop the pilot
            bad.append({"sha256": sha, "error": f"{type(e).__name__}: {e}"})
    (WORK / "pages.json").write_text(json.dumps(pages_out, indent=1), encoding="utf-8")
    print(f"rendered {len(pages_out)}/{len(sample)} pages from {len(by_sha)} decks; bad {len(bad)}")
    for b in bad[:10]:
        print("BAD", b)
    if pages_out:
        print("median render s", sorted(p["render_s"] for p in pages_out)[len(pages_out) // 2],
              "median px", sorted(p["px"][0] * p["px"][1] for p in pages_out)[len(pages_out) // 2])


if __name__ == "__main__":
    main()
