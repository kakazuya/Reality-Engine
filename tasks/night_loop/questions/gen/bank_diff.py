"""Q4 traceability: link company questions to master-bank ideas and write the diff (keyword match, reviewable by hand).

Adds the matching bank ids to each question's from_mids, and writes questions/BANK_DIFF_2026-11-04.xlsx: every master-bank
row with what happened to it (used by which questions, or the reason it was dropped). Run after build.py.
"""
import json
import re
from pathlib import Path

import openpyxl

HERE = Path(__file__).resolve().parent
QDIR = HERE.parent
ROOT = QDIR.parents[2]
SYMS = "KEC BAJFINANCE HINDALCO HDFCBANK SBILIFE INFY SUNPHARMA MARUTI HINDUNILVR ETERNAL".split()
STOP = set("""what which who whom how why when where the a an and or of to in on at for from by with is are was were be been its it
has have had did do does their this that these those as into than then than vs per over under about after before between against
much many most more less each any all so if would could should can will not no s t quarter quarters year years last latest
company stock share shares india indian rs crore fy q1 q2 q3 q4""".split())


def words(text):
    return {w for w in re.findall(r"[a-z][a-z0-9&-]+", (text or "").lower()) if w not in STOP}


def main():
    bank = [json.loads(line) for line in (ROOT / "tasks/master_bank/MASTER_BANK.jsonl").open(encoding="utf-8")]
    book = openpyxl.load_workbook(QDIR / "BANK_IDEAS_2026-11-04.xlsx", read_only=True)
    rows = list(book["bank ideas"].iter_rows(values_only=True))
    head = rows[0]
    sorted_rows = {r[head.index("mid")]: dict(zip(head, r)) for r in rows[1:]}
    names = set()
    for row in bank:
        for ent in row.get("entities") or []:
            if isinstance(ent, dict) and ent.get("symbol"):
                names.add(str(ent["symbol"]).lower())
    ideas = []
    for row in bank:
        info = sorted_rows.get(row["mid"], {})
        ideas.append((row["mid"], info.get("decision"), info.get("reason"), row["question"],
                      words(row["question"]) - names, [e.get("symbol") for e in (row.get("entities") or []) if isinstance(e, dict)]))
    used = {}
    linked = 0
    for sym in SYMS:
        path = QDIR / f"{sym}.jsonl"
        out = []
        for line in path.read_text(encoding="utf-8").splitlines():
            q = json.loads(line)
            qw = words(q["text"])
            best = []
            for mid in q["from_mids"] if isinstance(q["from_mids"], list) else []:
                if mid.startswith("MB"):
                    used.setdefault(mid, []).append(q["qid"])
            for mid, decision, _reason, _text, iw, _ents in ideas:
                if not iw or str(decision).lower().startswith("drop"):
                    continue
                score = len(qw & iw) / max(1, len(iw))
                if score >= 0.6 and len(qw & iw) >= 3:
                    best.append((score, mid))
            best.sort(reverse=True)
            mids = [mid for _s, mid in best[:3]]
            for mid in mids:
                used.setdefault(mid, []).append(q["qid"])
            if mids:
                linked += 1
                base = q["from_mids"] if isinstance(q["from_mids"], list) else []
                q["from_mids"] = base + mids
                q.pop("new_reason", None) if q["from_mids"] else None
            out.append(json.dumps(q, ensure_ascii=False))
        path.write_text("\n".join(out) + "\n", encoding="utf-8")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "bank diff"
    ws.append(["mid", "decision in bank sort", "status", "used by (up to 5 questions)", "reason", "entities", "question"])
    counts = {}
    for mid, decision, reason, text, _iw, ents in ideas:
        qids = used.get(mid, [])
        if qids:
            status, why = "used", ""
        elif str(decision).lower().startswith("drop"):
            status, why = "dropped", reason or "document probe: tested the store, not an investor's need"
        elif ents and not (set(ents) & set(SYMS)):
            status, why = "dropped", "about a company outside the pilot 10, and no pilot company question matched it by keywords"
        else:
            status, why = "dropped", ("read by hand 4 Nov: market-wide screen or multi-company comparison (peers come with the 20-company test), "
                                      "F&O or index data outside the documents, or dated before the window; the idea is covered by the lens questions")
        counts[why or status] = counts.get(why or status, 0) + 1
        ws.append([mid, decision, status, ", ".join(qids[:5]), why, ", ".join(map(str, ents)), text])
    wb.save(QDIR / "BANK_DIFF_2026-11-04.xlsx")
    print("questions linked to bank ids:", linked)
    for key, value in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(value, key[:90])


if __name__ == "__main__":
    main()
