# Calibration for the scanned-filing score: how many XBRL facts appear in the text of DIGITAL results filings,
# and in the hidden text layers of the SCANNED test filings. Claude, 1 Nov 2026.
import csv, json, os, re, sqlite3, datetime as dt, collections, random
import pypdfium2 as pdfium
OUT="D:/RealityEngine/ocr_large_20261101/"; RAW="D:/RealityEngine/raw/pilot60_history/"
S=json.load(open(OUT+"sample.json",encoding="utf-8")); T=json.load(open(OUT+"scan_xbrl_truth.json"))
NUM=re.compile(r"\d[\d,]*(?:\.\d+)?")
nums=lambda t:{m.group().replace(",","") for m in NUM.finditer(t or "")}
man={}
for r in csv.DictReader(open(RAW+"manifest.csv",encoding="utf-8",errors="ignore")):
    man[os.path.basename((r["local_path"] or "").replace("\\","/"))]=r
db=sqlite3.connect("file:C:/Users/warri/Downloads/Info_Diffusion_Model/reality_engine/data/results_xbrl.db?mode=ro",uri=True)
def facts(pdf):
    m=man.get(os.path.basename(pdf))
    if not m: return None
    d=dt.date.fromisoformat(m["dissem_ts"][:10]); sym=m["symbol_at_time"]
    vals=set()
    for (f,) in db.execute("select file from filings where symbol=? and substr(dissem_ts,1,10) between ? and ?",(sym,str(d-dt.timedelta(days=2)),str(d+dt.timedelta(days=2)))).fetchall():
        for v,u in db.execute("select value,unit from facts where file=?",(f,)):
            try:x=float(v)
            except Exception:continue
            if abs(x)>=1e5 and "INR" in str(u).upper(): vals.add(abs(x))
    return vals if len(vals)>=5 else None
def forms(v):
    o=set()
    for div in (1,1e3,1e5,1e6,1e7):
        for dp in (0,1,2,3):
            f=f"{v/div:.{dp}f}"
            if len(f.replace(".","").lstrip("0"))>=3:o.add(f)
    return o
def layer(pdf):
    p=pdfium.PdfDocument(RAW+pdf)
    try:return "\n".join(p[i].get_textpage().get_text_range() or "" for i in range(len(p)))
    finally:p.close()
def score(items):
    tot=hit=0
    for pdf,vals in items:
        O=nums(layer(pdf))
        for v in vals:tot+=1;hit+=bool(forms(v)&O)
    return {"docs":len(items),"facts":tot,"found":round(hit/max(1,tot),4)}
scan=[d for d in S["scan_docs"] if d["split"]=="test" and d["pdf"] in T]
print("hidden layers of scanned test filings",score([(d["pdf"],set(T[d["pdf"]]["values"])) for d in scan]),flush=True)
random.seed(7); seen=set(); dig=[]
ps=[p for p in S["digital"] if p["doc_type"]=="quarterly_results" and p["split"]=="test"]; random.shuffle(ps)
for p in ps:
    if p["pdf"] in seen:continue
    seen.add(p["pdf"]); pdf=pdfium.PdfDocument(RAW+p["pdf"]); n=len(pdf); pdf.close()
    if n>12:continue
    v=facts(p["pdf"])
    if v: dig.append((p["pdf"],v))
    if len(dig)>=80:break
print("digital results filings, the ceiling",score(dig),flush=True)
