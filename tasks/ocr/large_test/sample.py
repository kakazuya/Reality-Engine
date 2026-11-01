# Frozen page sample for the larger TextRecognizer test (Claude, 1 Nov 2026). Seed fixed.
import collections, json, os, random, re, sys
import pypdfium2 as pdfium
RAW = "D:/RealityEngine/raw/pilot60_history/"
OUT = "D:/RealityEngine/ocr_large_20261101/"
NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")
TYPES = ["quarterly_results", "annual_report", "investor_presentation"]
random.seed(20261101)
os.makedirs(OUT + "truth", exist_ok=True)
pdfs = collections.defaultdict(list)
for co in sorted(os.listdir(RAW)):
    for t in TYPES:
        d = f"{RAW}{co}/{t}"
        if os.path.isdir(d):
            for f in sorted(os.listdir(d)):
                if f.lower().endswith(".pdf"):
                    pdfs[(co, t)].append(f"{co}/{t}/{f}")
print("companies", len({k[0] for k in pdfs}), {t: sum(len(v) for k, v in pdfs.items() if k[1] == t) for t in TYPES}, flush=True)

def image_share(pg):
    W, H = pg.get_size()
    best = 0.0
    for o in pg.get_objects(max_depth=2):
        if o.type == pdfium.raw.FPDF_PAGEOBJ_IMAGE:
            l, b, r, t = o.get_bounds()
            best = max(best, (r - l) * (t - b) / max(1.0, W * H))
    return best

digital, scan_docs = [], []
for (co, t), fs in sorted(pdfs.items()):
    random.shuffle(fs)
    got = 0
    for rel in fs[:12]:
        try:
            pdf = pdfium.PdfDocument(RAW + rel)
        except Exception:
            continue
        try:
            n = len(pdf)
            idx = list(range(n))
            random.shuffle(idx)
            shares, cand = [], []
            for i in idx[:60]:
                pg = pdf[i]
                s = image_share(pg)
                shares.append(s)
                tp = pg.get_textpage()
                txt = tp.get_text_range() or ""
                k = len(NUM.findall(txt))
                if s <= 0.10 and len(txt) >= 300:
                    kind = "table" if k >= 30 else "prose" if k <= 10 else None
                    if kind:
                        cand.append((i, kind, k, txt))
            if t == "quarterly_results" and n <= 12 and shares and sum(x > 0.5 for x in shares) >= 0.5 * len(shares):
                scan_docs.append({"company": co, "doc_type": t, "pdf": rel, "page_count": n})
            for i, kind, k, txt in cand[:4]:
                digital.append({"company": co, "doc_type": t, "pdf": rel, "page": i, "page_count": n, "kind": kind, "numbers": k, "truth": txt})
                got += 1
        finally:
            pdf.close()
        if got >= 12:
            break
    print(co, t, "digital so far", len(digital), "scan docs", len(scan_docs), flush=True)

random.shuffle(digital); random.shuffle(scan_docs)
tab = [x for x in digital if x["kind"] == "table"]
pro = [x for x in digital if x["kind"] == "prose"]
# cap per company so no single company dominates the score
def capped(rows, total, cap):
    seen, out = collections.Counter(), []
    for r in rows:
        if seen[r["company"]] < cap and len(out) < total:
            seen[r["company"]] += 1; out.append(r)
    return out
tab = capped(tab, 1000, 30); pro = capped(pro, 300, 10); scans = capped(scan_docs, 150, 6)
rows = []
for j, r in enumerate(tab + pro):
    r["id"] = f"D{j:05d}"
    open(f"{OUT}truth/{r['id']}.txt", "w", encoding="utf-8").write(r.pop("truth"))
    rows.append(r)
# split by company: tune on 15 companies, score on the rest, so settings cannot fit the score
cos = sorted({r["company"] for r in rows}); random.shuffle(cos)
tune = set(cos[:15])
for r in rows:
    r["split"] = "tune" if r["company"] in tune else "test"
json.dump({"digital": rows, "scan_docs": scans}, open(OUT + "sample.json", "w", encoding="utf-8"), indent=0)
print("FINAL digital", len(rows), collections.Counter((r["kind"], r["doc_type"], r["split"]) for r in rows), "companies", len(cos), "scan docs", len(scans), "scan pages", sum(s["page_count"] for s in scans))
