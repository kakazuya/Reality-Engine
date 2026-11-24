"""T-242: which annual-report pages are worth a model read (Shivam 24 Nov: "useful sections of the annual report").

Round 2 (24 Nov, after a hand audit of 80 pages, ``D:/RealityEngine/t242/ar_audit/ar_audit.csv``: keep-list precision
42%, about half the useful pages dropped because no keep heading matched): the rule is now DROP-LIST FIRST. hy4 is
free, so a page is read unless its heading zone (first ``HEAD`` characters) names a boilerplate section, or it is prose
with no figure table.

``section_of(text)`` -> (section, keep?):
1. a heading-zone DROP section wins (auditor's report, governance, notice, CSR/BRSR, secretarial, remuneration,
   market data, cover letter, employee benefits / HR, primary statements, policies, and the note schedules XBRL
   already holds: PPE, share capital, other equity, deferred tax, payables, inventories, other income/expenses, EPS) -- except that a notes page
   ("Notes to / forming part of the financial statements", "other explanatory information" running headers) skips the
   primary-statement / policies / CSR drops (Eagle, 40 stores: ~340 off-balance notes pages were lost to those
   running headers);
2. a KEEP heading (MD&A, highlights, segment, operations, subsidiaries / AOC-1, off-balance notes, related-party
   amounts, hedges, disputes, ratios, material RPTs) keeps the page; a KEEP phrase lower on the page keeps it only on
   a figure table (``numeric_table``), so a narrative that mentions "related party transactions" stays out;
3. otherwise a figure table is kept as ``table`` (a model read of a correct schedule costs nothing but quota);
   prose is dropped.

``kept_pages(pages)`` applies this per report; an unheaded page right after a kept running section (MD&A, risks,
highlights) continues it only when it is not prose-only.  ``needs_ocr`` pages arrive with empty text and are dropped
unless they continue a kept section: their OCR text is not in the store until T-238 OCR runs.

``python -m reality_engine.v2.ar_sections --stores-root <root>`` prints kept / dropped counts per section.
"""
from __future__ import annotations

import argparse
import collections
import csv
import glob
import re
import sqlite3
from pathlib import Path

HEAD = 400
MIN_DIGIT_LINES = 8

DROP = {
    "auditor_report": r"independent auditor|auditor[’']?s report|report on the audit|key audit matter|\bcaro\b|"
                      r"companies \(auditor[’']?s report\) order",
    "audit_annex": r"annexure .{0,40}referred to in paragraph|certificate of non-disqualification|"
                   r"internal financial controls? (?:over|with reference to) financial reporting",
    "governance": r"corporate governance|board of directors comprised|board meetings|committee meetings|"
                  r"terms of reference|nomination and remuneration|stakeholders[’']? relationship|"
                  r"independent directors? .{0,40}(?:integrity|expertise)",
    "secretarial": r"secretarial audit|form no\.? mr-3|form mgt|annual return",
    "remuneration": r"remuneration of (?:directors|key managerial)|ratio of the remuneration|median remuneration",
    "notice": r"notice is hereby given|annual general meeting|e-voting|remote e-voting|item no\.?\s*\d|"
              r"explanatory statement|\bresolved\b",
    "market_data": r"market price data|share price performance|means of communication|distribution of shareholding|"
                   r"listing on stock exchanges|insider trading",
    "cover_letter": r"scrip code|dear sir|listing department",
    "employee": r"defined benefit|gratuity|actuarial|plan assets|employee benefit|"
                r"learning and development|human resource",
    "csr_brsr": r"corporate social responsibility|csr committee|business responsibility|brsr|"
                r"conservation of energy|technology absorption|essential indicators|leadership indicators|"
                r"principle \d|\bei-\d|ghg emissions|air emissions",
    "primary_statement": r"cash flow statement|statement of cash flows|(?:consolidated |standalone )?balance sheet|"
                         r"statement of profit and loss|statement of changes in equity",
    "xbrl_schedule": r"property,? plant (?:and|&) equipment|share capital|other equity|fair value hierarchy|"
                     r"deferred tax|financial instruments by category|other (?:current |non-current )?(?:assets|"
                     r"liabilities)|trade payables|inventories|cash and cash equivalents|other income|finance costs|"
                     r"other expenses|earnings per (?:equity )?share|intangible assets|right[- ]of[- ]use",
    "policies": r"material accounting policies|significant accounting policies|basis of preparation|"
                r"use of estimates and judgements",
}
NOTES_EXEMPT = {"primary_statement", "policies", "csr_brsr"}
NOTES_HEAD = re.compile(r"notes? (?:to|forming part of)|other explanatory information", re.I)

KEEP = {
    "mdna": r"management[’']?s? discussion|management discussion and analysis|financial performance review|"
            r"operational performance|details of significant changes",
    "highlights": r"financial highlights|key performance indicators|performance highlights|at a glance|"
                  r"(?:ten|10|five|5)[- ]year (?:financial )?(?:summary|highlights|performance|record)|"
                  r"financial summary|key metrics",
    "segment": r"segment information|operating segments?|segment[- ]wise|segment reporting|segment revenue",
    "operations": r"order book|order inflow|installed capacity|capacity utili[sz]ation|production volumes?|"
                  r"sales volumes?|plant[- ]wise|product[- ]wise",
    "subsidiaries": r"aoc-1|salient features of (?:the )?financial statements? of (?:the )?subsidiar|"
                    r"performance (?:and financial position )?of (?:each of )?the subsidiar",
    "notes_offbalance": r"contingent liabilit|capital commitments?|related party (?:transactions|disclosures)|"
                        r"name\(?s?\)? of the related part(?:y|ies)|"
                        r"terms of (?:repayment|borrowings)|security (?:offered|created) for (?:the )?borrowings|"
                        r"capital work[- ]in[- ]progress ageing|cwip ageing|trade receivables? ageing|"
                        r"disaggregat(?:ed|ion) (?:of )?revenue|revenue from contracts with customers|"
                        r"cash flow hedges?|notional (?:principal )?amounts?|forward contracts|"
                        r"redemption of .{0,40}debentures|non-convertible debentures",
    "ratios": r"analytical ratios|ratios to be disclosed|key financial ratios",
    "risks_outlook": r"risks and (?:threats|concerns)|opportunities and threats|outlook|industry structure",
    "disputes": r"pending litigations?|statutory dues .{0,60}dispute|forum where (?:the )?dispute is pending|"
                r"enforcement directorate|attached (?:the )?propert|show cause notice|\bnclt\b|investigation",
    "material_rpt": r"material (?:related party transactions|rpts?)|information provided by the management",
}

NEEDS_TABLE = {"notes_offbalance", "material_rpt", "subsidiaries"}   # audit: a narrative that names them has no amounts

_DROP = {k: re.compile(v, re.I) for k, v in DROP.items()}
_KEEP = {k: re.compile(v, re.I) for k, v in KEEP.items()}
_DIGIT_TOKEN = re.compile(r"\d[\d,]*(?:\.\d+)?")


def numeric_table(text: str) -> bool:
    """A page with a figure table: at least MIN_DIGIT_LINES lines carrying an amount, or (one-line text layers) at
    least 4x as many number tokens."""
    raw = str(text or "")
    lines = [line for line in raw.splitlines() if re.search(r"\d{2,}", line)]
    if len(lines) >= MIN_DIGIT_LINES:
        return True
    return len(_DIGIT_TOKEN.findall(raw)) >= 4 * MIN_DIGIT_LINES


def section_of(text: str) -> tuple[str, bool]:
    """(section name, keep?) for one annual-report page; ("", False) for prose nothing recognises."""
    t = re.sub(r"\s+", " ", str(text or ""))
    head = t[:HEAD]
    notes = bool(NOTES_HEAD.search(head))
    for name, rx in _DROP.items():
        if notes and name in NOTES_EXEMPT:
            continue
        if rx.search(head):
            return name, False
    table = numeric_table(text)
    for name, rx in _KEEP.items():
        if rx.search(head) and (table or name not in NEEDS_TABLE):
            return name, True
    if table:
        for name, rx in _KEEP.items():          # a keep phrase lower on the page counts only on a figure table
            if rx.search(t):
                return name, True
        return "table", True
    return "", False


def keep(text: str) -> bool:
    return section_of(text)[1]


CONTINUES = {"mdna", "risks_outlook", "highlights"}


def kept_pages(pages: list[tuple[int, str]]) -> dict[int, str]:
    """{page: section} to read in ONE annual report, given (page, text) of its candidate pages.

    An unrecognised page right after a kept page of a running narrative section (MD&A, risks, highlights) continues
    it; a drop heading ends it.  Empty text (a ``needs_ocr`` page) continues a running section too.
    """
    out: dict[int, str] = {}
    running, last = "", -10
    for page, text in sorted(pages):
        name, ok = section_of(text)
        if ok:
            out[page] = name
            running, last = (name if name in CONTINUES else ""), page
        elif not name and running and page - last <= 2:
            out[page] = running
            last = page
        else:
            running = ""
    return out


# ---- round 3 (24 Nov): safe regex drops, then hy4 triage ------------------------------------------------------------
# Scored on 160 hand-labelled gold pages (D:/RealityEngine/t242/ar_gold/gold.json, two Sonnet audits): round-1 keep-list
# precision 39% / recall 44%, round-2 drop-list 27% / 81%; hy4 triage alone 67% / 100% (32/32 useful pages kept);
# SAFE_DROP before it removes 30 of 160 pages and loses none.  Script tools: hy4_classify.py and eval.py beside gold.
SAFE_DROP = set(DROP) - {"xbrl_schedule", "primary_statement", "employee"}
TRIAGE_DB = Path("C:/RealityEngine/t242/ar_triage.db")
TRIAGE_CHARS = 6000
TRIAGE_PROMPT = """You are triaging one page of an Indian listed company's annual report (its text layer below).
Decide if a careful analyst should extract figures from this page. USEFUL means the page itself states company figures
or facts an investor wants that are NOT just lines of the primary statements (balance sheet, P&L, cash flow) and NOT
boilerplate. Useful examples: segment/geography/product tables, order book, capacity and utilisation, volumes, KPIs,
multi-year summaries, MD&A with figures and reasons, key ratios with reasons, contingent liabilities with amounts,
related-party transactions/balances with amounts, borrowing rates/terms/security, receivable or payable ageing,
hedges and FX exposure amounts, subsidiary/associate figures (AOC-1), litigation or tax demand amounts, use of issue
proceeds, acquisitions, events after the reporting date with amounts.
NOT useful: AGM notice, e-voting, governance, board/committee meetings, director bios, remuneration disclosures,
auditor's report and annexures, accounting policies, BRSR/ESG/CSR, HR narrative, ESOP terms, actuarial tables,
primary statements, routine schedules (PPE, share capital, other equity, inventories, cash, other income/expenses, EPS,
deferred tax), tables that are all NIL, contents pages.
Answer with ONE line of JSON only: {"useful": true or false, "section": "<2-4 words>"}

PAGE TEXT:
"""


def safe_drop(text: str) -> bool:
    """True when the page is certainly not worth a read: empty, or a SAFE_DROP heading (no useful gold page has one)."""
    if not str(text or "").strip():
        return True
    return section_of(text)[0] in SAFE_DROP


def _triage_db(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path), timeout=60, check_same_thread=False)
    con.execute("CREATE TABLE IF NOT EXISTS ar_triage (doc_key TEXT NOT NULL, page INTEGER NOT NULL, useful INTEGER, "
                "section TEXT, raw TEXT, read_at TEXT, PRIMARY KEY (doc_key, page))")
    return con


def triage(texts: dict[tuple[str, int], str], workers: int = 10, db: Path | None = None) -> dict[tuple[str, int], bool]:
    """{(doc_key, page): useful} from hy4 (text only, one line of JSON), cached in ``ar_triage``; a failed call is
    not cached and counts as useful (unsure = read; the reader's row checks still apply)."""
    import concurrent.futures as cf
    import datetime as dt
    import json

    from reality_engine.v2 import observations as obs

    con = _triage_db(db or TRIAGE_DB)
    out: dict[tuple[str, int], bool] = {}
    todo = []
    for key in texts:
        got = con.execute("SELECT useful FROM ar_triage WHERE doc_key=? AND page=?", key).fetchone()
        if got is not None:
            out[key] = bool(got[0])
        else:
            todo.append(key)

    def one(key: tuple[str, int]) -> tuple[tuple[str, int], dict | None, str]:
        text = re.sub(r"[ \t]+", " ", texts[key])[:TRIAGE_CHARS]
        r = obs.call_reader(TRIAGE_PROMPT + text, None, key[0], key[1])
        raw = r.get("output") or ""
        m = re.search(r"\{.*\}", raw, re.S)
        try:
            return key, (json.loads(m.group(0)) if m else None), raw
        except ValueError:
            return key, None, raw

    with cf.ThreadPoolExecutor(workers) as ex:
        for key, j, raw in ex.map(one, todo):
            if not isinstance(j, dict) or "useful" not in j:
                out[key] = True
                continue
            out[key] = bool(j.get("useful"))
            con.execute("INSERT OR REPLACE INTO ar_triage VALUES (?,?,?,?,?,?)",
                        (key[0], key[1], int(out[key]), str(j.get("section") or "")[:80], raw[:500],
                         dt.datetime.now().isoformat(timespec="seconds")))
            con.commit()
    con.close()
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="kept / dropped annual-report table pages per section")
    ap.add_argument("--stores-root", required=True)
    ap.add_argument("--limit-stores", type=int, default=0)
    a = ap.parse_args(argv)
    counts: collections.Counter[tuple[str, bool]] = collections.Counter()
    routes = sorted(glob.glob(f"{a.stores_root}/c*/routes.csv"))
    if a.limit_stores:
        routes = routes[:a.limit_stores]
    for f in routes:
        rows = [r for r in csv.DictReader(open(f, newline="", encoding="utf-8"))
                if r.get("doc_type") == "annual_report" and r.get("route") == "table_or_chart"]
        if not rows:
            continue
        stem = Path(f).parent.name
        con = sqlite3.connect(f"file:{Path(f).parent / (stem + '.db')}?mode=ro", uri=True, timeout=30)
        try:
            by_doc: dict[str, list[tuple[int, str]]] = collections.defaultdict(list)
            for r in rows:
                got = con.execute("SELECT text FROM doc_page WHERE doc_key=? AND page=?",
                                  (r["doc_key"], int(r["page"]))).fetchone()
                by_doc[r["doc_key"]].append((int(r["page"]), got[0] if got else ""))
            for pages in by_doc.values():
                kept = kept_pages(pages)
                for page, text in pages:
                    counts[(kept[page], True) if page in kept else (section_of(text)[0], False)] += 1
        finally:
            con.close()
    total = sum(counts.values())
    kept = sum(n for (s, k), n in counts.items() if k)
    print(f"annual-report table pages {total}: keep {kept} ({kept / max(total, 1):.0%})")
    for (s, k), n in counts.most_common():
        print(f"  {'KEEP' if k else 'drop'} {s or '(none)':20} {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
