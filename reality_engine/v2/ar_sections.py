"""T-242: which annual-report pages are worth a model read (Shivam 24 Nov: "useful sections of the annual report").

An annual report's routed ``table_or_chart`` pages (~271k across the built stores) are mostly pages a model read adds
nothing to: the primary statements (XBRL already holds them), auditor's reports, governance, remuneration, AGM notices,
market-price tables, BRSR and CSR. ``section_of(text)`` names the section a page belongs to, read from its heading zone
(the first ``HEAD`` characters) and, for notes, from note titles anywhere on the page; ``keep(text)`` is True only for
sections in ``KEEP``.

Keep (figures a filing states only here): management discussion and analysis, financial / operating highlights and
multi-year summaries, segment information, order book / capacity / production, subsidiaries' salient features
(AOC-1), and the notes that carry off-statement facts: contingent liabilities and commitments, related parties,
borrowings terms, CWIP and receivable ageing, revenue disaggregation.

Drop wins over keep when the heading itself is a drop section (an auditor's report that mentions "contingent
liabilities" stays dropped). A page with no recognised section is dropped (unsure = no read); ``python -m
reality_engine.v2.ar_sections --stores-root <root>`` prints the kept / dropped counts per section so the rule is
measured, not assumed.
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

DROP = {
    "auditor_report": r"independent auditor|auditor[’']?s report|report on the audit|key audit matter|caro|"
                      r"companies \(auditor[’']?s report\) order",
    "governance": r"corporate governance|board of directors comprised|board meetings|committee meetings|"
                  r"terms of reference|nomination and remuneration|stakeholders[’']? relationship",
    "secretarial": r"secretarial audit|form no\.? mr-3|form mgt|annual return",
    "remuneration": r"remuneration of (?:directors|key managerial)|ratio of the remuneration|median remuneration",
    "notice": r"notice is hereby given|annual general meeting|e-voting|remote e-voting|item no\.?\s*\d|"
              r"explanatory statement",
    "csr_brsr": r"corporate social responsibility|csr committee|business responsibility|brsr|"
                r"conservation of energy|technology absorption",
    "market_data": r"market price data|share price performance|means of communication|distribution of shareholding|"
                   r"listing on stock exchanges|insider trading",
    "primary_statement": r"cash flow statement|statement of cash flows|balance sheet as at|"
                         r"statement of profit and loss|statement of changes in equity",
    "policies": r"material accounting policies|significant accounting policies|basis of preparation|"
                r"use of estimates and judgements",
    "cover_letter": r"scrip code|dear sir|listing department",
    "brsr_tables": r"essential indicators|leadership indicators|principle \d|\bei-\d|ghg emissions|air emissions",
    "audit_annex": r"annexure .{0,40}referred to in paragraph|certificate of non-disqualification|"
                   r"internal financial controls? (?:over|with reference to) financial reporting",
}

KEEP = {
    "mdna": r"management[’']?s? discussion|management discussion and analysis|financial performance review|"
            r"operational performance|key financial ratios|details of significant changes",
    "highlights": r"financial highlights|key performance indicators|performance highlights|at a glance|"
                  r"(?:ten|10|five|5)[- ]year (?:financial )?(?:summary|highlights|performance|record)|"
                  r"financial summary|key metrics",
    "segment": r"segment information|operating segments?|segment[- ]wise|segment reporting|segment revenue",
    "operations": r"order book|order inflow|installed capacity|capacity utili[sz]ation|production volumes?|"
                  r"sales volumes?|plant[- ]wise|product[- ]wise",
    "subsidiaries": r"aoc-1|salient features of the financial statements? of subsidiar|"
                    r"performance (?:and financial position )?of (?:each of )?the subsidiar",
    "notes_offbalance": r"contingent liabilit|capital commitments?|related party (?:transactions|disclosures)|"
                        r"terms of (?:repayment|borrowings)|security (?:offered|created) for (?:the )?borrowings|"
                        r"capital work[- ]in[- ]progress ageing|cwip ageing|trade receivables? ageing|"
                        r"disaggregat(?:ed|ion) (?:of )?revenue|revenue from contracts with customers",
    "directors_report": r"state of (?:the )?company[’']?s affairs|financial results|"
                        r"material changes and commitments",
    "ratios": r"analytical ratios|ratios to be disclosed|key financial ratios",
    "risks_outlook": r"risks and (?:threats|concerns)|opportunities and threats|outlook|industry structure",
    "disputes": r"pending litigations?|statutory dues .{0,60}dispute|forum where (?:the )?dispute is pending|"
                r"enforcement directorate|attached (?:the )?propert",
    "material_rpt": r"material (?:related party transactions|rpts?)|information provided by the management",
}

_DROP = {k: re.compile(v, re.I) for k, v in DROP.items()}
_KEEP = {k: re.compile(v, re.I) for k, v in KEEP.items()}


def section_of(text: str) -> tuple[str, bool]:
    """(section name, keep?) for one annual-report page; ("", False) when nothing is recognised."""
    t = re.sub(r"\s+", " ", str(text or ""))
    head = t[:HEAD]
    for name, rx in _DROP.items():
        if rx.search(head):
            return name, False
    for name, rx in _KEEP.items():
        if rx.search(head):
            return name, True
    for name in ("notes_offbalance", "segment", "operations", "subsidiaries", "ratios", "disputes"):  # lower on page
        if _KEEP[name].search(t):
            return name, True
    return "", False


def keep(text: str) -> bool:
    return section_of(text)[1]


CONTINUES = {"mdna", "risks_outlook", "highlights", "segment", "operations", "subsidiaries", "material_rpt"}


def kept_pages(pages: list[tuple[int, str]]) -> dict[int, str]:
    """{page: section} to read in ONE annual report, given (page, text) of its candidate pages.

    A section's heading sits on its first page only, so an unrecognised page right after a kept page of a running
    section (MD&A, risks, highlights, segment, operations, subsidiaries, material RPTs) continues that section; a
    page whose heading is a drop section ends it.
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
