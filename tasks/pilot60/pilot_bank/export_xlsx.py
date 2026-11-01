"""Write the pilot question bank to Excel: questions, pilot companies, removed questions, notes."""
from __future__ import annotations

import collections
import csv
import json
import re
import sys
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

sys.path.insert(0, str(Path(__file__).parent))
import engine as E  # noqa: E402

ROOT = E.ROOT
OUT = ROOT / "tasks/pilot60/PILOT_BANK_QUESTIONS_2026-10-31.xlsx"
SUPPORT = {"YES": "Answer stated in document", "PARTIAL": "Part stated in document", "DATA": "Price, filing or policy data"}
KIND = {"stock": "One company", "pilot_set": "Group of pilot companies", "market": "Market or policy"}
LABEL = {"concall": "Earnings call", "deck": "Investor presentation", "annual_report": "Annual report", "results_notes": "Results", "announcement": "Filing"}
ILLEGAL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
FONT = "Arial"


def clean(v):
    return ILLEGAL.sub(" ", v) if isinstance(v, str) else v


def sheet(wb, title, header, rows, widths, wrap=()):
    ws = wb.create_sheet(title)
    ws.append(header)
    for r in rows:
        ws.append([clean(x) for x in r])
    for cell in ws[1]:
        cell.font = Font(name=FONT, bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="1F3864")
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    for row in ws.iter_rows(min_row=2):
        for c in row:
            c.font = Font(name=FONT, size=10)
            c.alignment = Alignment(vertical="top", wrap_text=c.column in wrap)
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    return ws


def main():
    st = E.Store()
    rows = [json.loads(x) for x in open(ROOT / "tasks/pilot60/PILOT_BANK_2026-10-31.jsonl", encoding="utf-8")]
    removed = [json.loads(x) for x in open(ROOT / "tasks/pilot60/PILOT_BANK_REMOVED_2026-10-31.jsonl", encoding="utf-8")]
    q_rows, per = [], collections.Counter()
    for r in rows:
        reads = r["fact_check"].get("reads") or []
        verdicts = [x["verdict"] for x in reads]
        support = "YES" if "YES" in verdicts else "PARTIAL" if "PARTIAL" in verdicts else "DATA"
        best = next((x for x in reads if x["verdict"] == support), None)
        syms = [e["symbol"] for e in r["entities"]]
        per.update(syms)
        names = ", ".join(E.NAMES[s] for s in syms)
        q_rows.append([r["mid"], r["question"], names or "None (market or policy)", KIND[r["kind"]], r["bucket"].title() if r["bucket"] != "ALL" else "All", r["as_of"],
                       SUPPORT[support], LABEL.get(best.get("doc_type"), "") if best else "", (best.get("date") or "") if best else "",
                       best.get("page") if best else None, best.get("quote") if best else "", "Yes" if r["changed"] else "No", r["old_question"]])
    wb = Workbook()
    wb.remove(wb.active)
    n_q = len(q_rows)
    sheet(wb, "Questions", ["Question ID", "Question", "Companies", "Scope", "Market-cap bucket", "As of", "What supports it", "Source document", "Document date", "Page", "Verified quote (verbatim)", "Rewritten?", "Old question"],
          q_rows, [12, 70, 30, 16, 12, 11, 24, 18, 11, 6, 60, 10, 60], wrap=(2, 3, 11, 13))
    comp = []
    for u in csv.DictReader(open(ROOT / "tasks/pilot60/UNIVERSE.csv", encoding="utf-8")):
        sym = u["symbol"] or E.EXTRA_SYM[u["isin"]]
        f = st.facts(u["isin"])
        master = st.eq.execute("SELECT company_name FROM master_companies WHERE isin=?", (u["isin"],)).fetchone()
        full = master[0] if master and master[0] != sym else E.NAMES[sym]
        comp.append([E.NAMES[sym], full, sym, u["isin"], u["bucket"].title(), f.get("basic_industry") or f.get("industry") or u["sector"], round(float(u["mcap_cr"])) if u["mcap_cr"] else None, f.get("last_iso"), per[sym]])
    order = {"Large": 0, "Mid-Small": 1, "Micro": 2}
    comp.sort(key=lambda c: (order[c[4]], -(c[6] or 0)))
    ws = sheet(wb, "Pilot Companies", ["Company", "Name in company master", "Symbol", "ISIN", "Market-cap bucket", "Business", "Market cap (Rs crore)", "Last price held", "Questions using it"],
               comp, [32, 40, 14, 16, 12, 38, 12, 12, 11])
    for row in ws.iter_rows(min_row=2, min_col=7, max_col=7):
        row[0].number_format = "#,##0"
    # Shivam's comments of 1 Nov are kept on every export; a question he restored stays listed with its ruling
    rulings = {x["mid"]: x for x in json.load(open(ROOT / "tasks/pilot60/PILOT_BANK_REMOVED_RULINGS_2026-11-01.json", encoding="utf-8"))}
    listed = removed + [x for m, x in rulings.items() if m not in {r["mid"] for r in removed}]
    sheet(wb, "Removed Questions", ["Question ID", "Old question", "Why it was removed", "Shivam's Comments", "What happens now"],
          [[x["mid"], x["old_question"], x["why"], rulings.get(x["mid"], {}).get("comment"), rulings.get(x["mid"], {}).get("action")] for x in listed], [12, 70, 50, 50, 40], wrap=(2, 3, 4, 5))
    notes = wb.create_sheet("Notes")
    lines = [
        ("Pilot question bank, 31 October 2026", None),
        ("Questions in the bank", n_q),
        ("Answer stated in document", sum(q[6] == SUPPORT["YES"] for q in q_rows)),
        ("Part stated in document", sum(q[6] == SUPPORT["PARTIAL"] for q in q_rows)),
        ("Price, filing or policy data", sum(q[6] == SUPPORT["DATA"] for q in q_rows)),
        ("Original questions removed (1,073 originals in all)", len({r['mid'] for r in removed})),
        ("Pilot companies", len(comp)),
        (None, None),
        ("What was checked", None),
        ("Every price move and date in a question was read from the stores for that company, and the audit found no failures.", None),
        ("No company outside the 60 pilot companies is named.", None),
        ("A document-based question needs a passage DeepSeek quoted from that company's documents; the quote was checked as verbatim.", None),
        ("What this does not prove", None),
        ("Hand checks of 80 document-based rows found about 1 in 7 passes weak: the quote is real but does not truly answer the question. See the Verified quote column.", None),
        ("'Part stated' means the documents cover one part; judgement questions usually fall here.", None),
        ("'Price, filing or policy data' rows were checked for held data, not by reading an answer. They have not been answered.", None),
        ("Chain questions keep their general wording and are answered only for the named companies, so a few read broadly for those companies.", None),
        ("Where a call has no held call date, the document date is the date the transcript was filed.", None),
        ("Companies with few or no questions have thin or old data; see Last price held on the Pilot Companies sheet.", None),
    ]
    for a, b in lines:
        notes.append([a, b])
    for row in notes.iter_rows():
        for c in row:
            c.font = Font(name=FONT, size=10)
            c.alignment = Alignment(wrap_text=c.column == 1, vertical="top")
    for r in (1, 9, 13):
        notes.cell(r, 1).font = Font(name=FONT, size=11, bold=True)
    notes.column_dimensions["A"].width = 100
    notes.column_dimensions["B"].width = 10
    wb.save(OUT)
    print(OUT, "questions", n_q, "removed", len(removed), "companies", len(comp), "no-question companies", [c[2] for c in comp if not c[8]])


if __name__ == "__main__":
    main()
