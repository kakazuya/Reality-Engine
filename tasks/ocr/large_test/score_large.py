"""Scorer for the larger TextRecognizer test. Written by Claude; do not change.
usage: score_large.py ROWS.jsonl [--split tune|test] ; ROWS rows: {"id": page id or "<pdf>#<page>", "text": ...}"""
import collections, json, random, re, sys
OUT = sys.argv[3] if len(sys.argv) > 3 else "."
NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")
WORD = re.compile(r"[A-Za-z]{3,}")
ROMAN = re.compile(r"\(?\b(?=[ivxlcIVXLC])M{0,3}(?:C[MD]|D?C{0,3})(?:X[CL]|L?X{0,3})(?:I[XV]|V?I{0,3})\b\)?", re.I)
def nums(t): return {m.group().replace(",", "") for m in NUM.finditer(t or "")}
def words(t): return collections.Counter(w.lower() for w in WORD.findall(t or ""))
def romans(t):
    c = collections.Counter()
    for m in ROMAN.finditer(t or ""):
        g = m.group()
        b = g.strip("()").lower()
        if b and (len(b) >= 2 or g.startswith("(")):
            c[b] += 1
    return c
def add(a, T, O, multi=False):
    if multi:
        a[0] += sum((T & O).values()); a[1] += sum((T - O).values()); a[2] += sum((O - T).values())
    else:
        a[0] += len(T & O); a[1] += len(T - O); a[2] += len(O - T)
def rp(a): return round(a[0] / max(1, a[0] + a[1]), 4), round(a[0] / max(1, a[0] + a[2]), 4), a[0] + a[1]
def main():
    rows_path = sys.argv[1]; split = sys.argv[2] if len(sys.argv) > 2 else "tune"
    S = json.load(open(OUT + "/sample.json", encoding="utf-8"))
    rows = {}
    for l in open(rows_path, encoding="utf-8"):
        r = json.loads(l); rows[r["id"]] = r.get("text") or ""
    P = [p for p in S["digital"] if p["split"] == split]
    miss = [p["id"] for p in P if p["id"] not in rows]
    per = collections.defaultdict(lambda: [0, 0, 0])
    out = {"pages": len(P), "missing_rows": len(miss)}
    for name, sel in (("table", [p for p in P if p["kind"] == "table"]),
                      *[(f"table_{t}", [p for p in P if p["kind"] == "table" and p["doc_type"] == t]) for t in ("annual_report", "quarterly_results", "investor_presentation")],
                      ("prose", [p for p in P if p["kind"] == "prose"])):
        n, w, ro = [0, 0, 0], [0, 0, 0], [0, 0, 0]
        for p in sel:
            if p["id"] not in rows: continue
            t = open(f"{OUT}/truth/{p['id']}.txt", encoding="utf-8", errors="ignore").read(); o = rows[p["id"]]
            add(n, nums(t), nums(o)); add(w, words(t), words(o), True); add(ro, romans(t), romans(o), True)
            if name == "table": add(per[p["company"]], nums(t), nums(o))
        out[name] = {"pages": len(sel), "numbers": rp(n), "words": rp(w), "roman": rp(ro)}
    # company bootstrap on the table number scores, since pages inside a company are not independent
    cos = sorted(per); random.seed(1); R, Q = [], []
    for _ in range(1000):
        a = [0, 0, 0]
        for c in random.choices(cos, k=len(cos)):
            for i in range(3): a[i] += per[c][i]
        R.append(a[0] / max(1, a[0] + a[1])); Q.append(a[0] / max(1, a[0] + a[2]))
    R.sort(); Q.sort()
    if R: out["table_numbers_95pct_range"] = {"found": [round(R[25], 4), round(R[974], 4)], "correct": [round(Q[25], 4), round(Q[974], 4)]}
    # scanned results filings: share of XBRL rupee facts found anywhere in the filing's text
    T = json.load(open(OUT + "/scan_xbrl_truth.json", encoding="utf-8"))
    tot = hit = docs = 0
    for pdf, d in T.items():
        keys = [k for k in rows if k.startswith(pdf + "#")]
        if not keys: continue
        docs += 1
        O = nums("\n".join(rows[k] for k in keys))
        for v in d["values"]:
            forms = set()
            for div in (1, 1e3, 1e5, 1e6, 1e7):
                for dp in (0, 1, 2, 3):
                    f = f"{v / div:.{dp}f}"
                    if len(f.replace(".", "").lstrip("0")) >= 3:
                        forms.add(f)
            tot += 1; hit += bool(forms & O)
    out["scan_xbrl"] = {"docs": docs, "facts": tot, "found": round(hit / max(1, tot), 4)}
    print(json.dumps(out, indent=1))
main()
