import json, glob, re, collections, os, sys
D = r"D:\RealityEngine\raw\nse_announcements\pilot_2026-10-28"
TRANSCRIPT = re.compile(r"transcri|con\.? ?call|conference call|earnings? call|analyst|investor meet", re.I)
DROP_DESC = {"Copy of Newspaper Publication","Trading Window","Certificate under SEBI (Depositories and Participants) Regulations, 2018",
 "Loss of Share Certificates","Issue of Duplicate Share Certificate","Record Date","Book Closure","Revised Record date","Address Change",
 "Structural Digital Database","Quarterly Compliance Report on Corporate governance - within 21 days from the end of the quarter",
 "Declaration for audit reports with unmodified opinion(s)","Committee Meeting Updates","Corrigendum","Integrated Filing- Governance",
 "ESOP/ESOS/ESPS","Change in Company Secretary/Compliance Officer","Trading Window-XBRL","Disclosure under SEBI Takeover Regulations","Monitoring Agency Report"}
MATERIAL = re.compile(r"order|contract|acqui|amalgamat|merger|demerg|scheme of arrangement|appoint|resign|cessation|change in (management|director|auditor)|"
 r"retire|demise|credit rating|rating|press release|investor presentation|earnings presentation|management commentary|financial result|outcome of board|"
 r"capacity|plant|product launch|memorandum|agreement|mou|litigation|dispute|insolvency|cirp|action\(s\)|penalt|fund ?rais|qualified institutional|"
 r"rights issue|preferential|allotment|issue of securities|bonus|dividend|buy ?back|open offer|offer for sale|diversif|disinvest|stake|subsidiar|joint venture|"
 r"fraud|default|clarification|price movement|spurt|news verification|monthly business|business update|guidance|material|fire|shutdown|resumption|strike|"
 r"related party|deviation|utilisation|integrated filing- financial|incorporat|restructur|tax|gst|search|raid|regulation 30", re.I)
NOISE_TEXT = re.compile(r"newspaper|advertis|share certificate|duplicate|trading window|scrutini[sz]er|postal ballot|notice of (the )?\d*\w* ?annual general|"
 r"book closure|record date|registrar|rta|contact details|functional website|large corporate|compliance certificate|74\(5\)|loss of", re.I)
def bucket(r):
    desc = r.get("desc") or ""; text = f"{desc} {r['raw'].get('attchmntText') or ''}"
    if TRANSCRIPT.search(desc) or re.search(r"transcri", text, re.I): return "transcript/meet"
    if desc in DROP_DESC: return "drop:procedural"
    if NOISE_TEXT.search(text) and not re.search(r"order|acqui|appoint|resign|rating|result", text, re.I): return "drop:procedural"
    if MATERIAL.search(text): return "material"
    if desc in ("Shareholders meeting",): return "drop:procedural"
    return "unclear"
rows = [json.loads(l) for f in glob.glob(D + r"\*.jsonl") for l in open(f, encoding="utf-8")]
c = collections.Counter(); b = collections.Counter(); ex = collections.defaultdict(list)
for r in rows:
    k = bucket(r); c[k] += 1
    try: b[k] += float(r["raw"].get("fileSize") or "0".split()[0])
    except Exception: pass
    ex[k].append(f"{r.get('desc')} | {(r['raw'].get('attchmntText') or '')[:110]}")
print(len(rows), dict(c))
import random; random.seed(7)
for k in ("unclear", "material", "drop:procedural"):
    print("==", k)
    for e in random.sample(ex[k], 14): print("  -", e.replace("\n", " "))
sizes = {}
for root, _, files in os.walk(D + r"\attachments"):
    for f in files: sizes[f] = os.path.getsize(os.path.join(root, f))
bb = collections.Counter(); hit = 0
for r in rows:
    name = os.path.basename(str(r["raw"].get("attchmntFile") or ""))
    if name in sizes: bb[bucket(r)] += sizes[name]; hit += 1
print("matched files", hit, {k: round(v/1e6) for k, v in bb.items()}, "MB total", round(sum(bb.values())/1e6))
def mb(s):
    m = re.match(r"([\d.]+)\s*(KB|MB|GB)?", str(s or ""), re.I)
    if not m: return 0
    v = float(m.group(1)); u = (m.group(2) or "MB").upper()
    return v / 1024 if u == "KB" else v * 1024 if u == "GB" else v
print("fileSize samples", [r["raw"].get("fileSize") for r in rows[:5]])
fs = collections.Counter()
for r in rows: fs[bucket(r)] += mb(r["raw"].get("fileSize"))
print({k: round(v) for k, v in fs.items()}, "MB by NSE fileSize")
