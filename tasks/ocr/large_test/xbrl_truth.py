# Machine truth for scanned results filings: XBRL rupee facts of the same filing date.
import csv, json, sqlite3, collections, datetime as dt, os
OUT="D:/RealityEngine/ocr_large_20261101/"
S=json.load(open(OUT+"sample.json",encoding="utf-8"))
man={}
for r in csv.DictReader(open("D:/RealityEngine/raw/pilot60_history/manifest.csv",encoding="utf-8",errors="ignore")):
    for k,v in r.items():
        if v and v.lower().endswith(".pdf"):
            man[os.path.basename(v.replace("\\","/"))]=r
print("manifest rows",len(man), "columns", list(next(iter(man.values())).keys()) if man else None)
db=sqlite3.connect("file:C:/Users/warri/Downloads/Info_Diffusion_Model/reality_engine/data/results_xbrl.db?mode=ro",uri=True)
print([c[1] for c in db.execute("pragma table_info(facts)")])
truth={};miss=collections.Counter()
for d in S["scan_docs"]:
    m=man.get(os.path.basename(d["pdf"]))
    if not m: miss["no manifest"]+=1; continue
    date=None
    for k in m:
        if "date" in k.lower() or "ts" in k.lower():
            try: date=dt.date.fromisoformat(m[k][:10]); break
            except Exception: pass
    if not date: miss["no date"]+=1; continue
    sym=m.get("symbol") or d["company"]
    fs=[r[0] for r in db.execute("select file from filings where symbol=? and substr(dissem_ts,1,10) between ? and ?",(sym,str(date-dt.timedelta(days=2)),str(date+dt.timedelta(days=2))))]
    if not fs: miss["no xbrl filing"]+=1; continue
    vals=set()
    for f in fs:
        for c,v,u in db.execute(f"select concept,value,unit from facts where file=?",(f,)):
            try: x=float(v)
            except Exception: continue
            if abs(x)>=1e5 and "INR" in str(u).upper(): vals.add(abs(x))
    if len(vals)<5: miss["few facts"]+=1; continue
    truth[d["pdf"]]={"date":str(date),"files":fs,"values":sorted(vals)}
json.dump(truth,open(OUT+"scan_xbrl_truth.json","w"))
print("docs with truth",len(truth),"of",len(S["scan_docs"]),"facts",sum(len(t["values"]) for t in truth.values()),dict(miss))
