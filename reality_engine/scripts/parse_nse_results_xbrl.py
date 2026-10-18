"""
Parse the NSE financial-results XBRL files into a dated quarterly table.

Input (already downloaded by fetch_nse_api_raw --datasets nse_results_xbrl, nse_results_equities, nse_results_sme):
  raw_market/nse_results_xbrl/*.xml            one XBRL instance per results filing (INDAS / BANKING / NBFC / NONINDAS)
  raw_market/nse_results_{equities,sme}/*.json  NSE's results index: symbol, ISIN, period, consolidated, audited and the
                                                exchange dissemination time, keyed by the XBRL URL

Output: reality_engine/data/results_xbrl.db (separate file, so the main DB does not grow)
  filings   one row per XBRL file: identity, period, standalone/consolidated, audited, dissemination time (exchdisstime,
            the point-in-time stamp), taxonomy
  facts     every non-dimensional fact (no segment/axis members): concept, context, period start/end or instant, value
  quarterly view: one row per filing for the reporting period itself (DateOfStart/EndOfReportingPeriod), with the
            common Ind-AS line items pivoted out. Banks/NBFCs use other concepts: query `facts` for them.

Values are stored as filed (INR, not crores). Resumable: files already in `filings` are skipped.

    python -m reality_engine.scripts.parse_nse_results_xbrl            # all files
    python -m reality_engine.scripts.parse_nse_results_xbrl --limit 200
"""
import argparse
import glob
import json
import os
import sqlite3
import time
from datetime import datetime
from pathlib import Path

from lxml import etree

RAW = Path(__file__).resolve().parents[1] / "data" / "raw_market"
OUT = Path(__file__).resolve().parents[1] / "data" / "results_xbrl.db"
NS = {"xbrli": "http://www.xbrl.org/2003/instance"}
STD_CTX = __import__("re").compile(r"^(One|Two|Three|Four|Five|Six)(D|I)$")
TEXT_KEEP = {"Symbol", "ScripCode", "NameOfTheCompany", "ClassOfSecurity", "ReportingQuarter",
             "NatureOfReportStandaloneConsolidated", "WhetherResultsAreAuditedOrUnaudited", "DateOfStartOfReportingPeriod",
             "DateOfEndOfReportingPeriod", "DateOfStartOfFinancialYear", "DateOfEndOfFinancialYear",
             "DateOfBoardMeetingWhenFinancialResultsWereApproved", "DateOfEndOfBoardMeeting",
             "DeclarationOfUnmodifiedOpinionOrStatementOnImpactOfAuditQualification", "TypeOfCompany", "ISIN"}
PIVOT = ["RevenueFromOperations", "OtherIncome", "Income", "CostOfMaterialsConsumed", "EmployeeBenefitExpense",
         "FinanceCosts", "DepreciationDepletionAndAmortisationExpense", "OtherExpenses", "Expenses",
         "ProfitBeforeExceptionalItemsAndTax", "ExceptionalItemsBeforeTax", "ProfitBeforeTax", "TaxExpense",
         "ProfitLossForPeriodFromContinuingOperations", "ProfitLossForPeriod", "ProfitOrLossAttributableToOwnersOfParent",
         "ComprehensiveIncomeForThePeriod", "BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations",
         "DilutedEarningsLossPerShareFromContinuingAndDiscontinuedOperations", "PaidUpValueOfEquityShareCapital",
         "FaceValueOfEquityShareCapital"]
SCHEMA = """
CREATE TABLE IF NOT EXISTS filings (
  file TEXT PRIMARY KEY, taxonomy TEXT, xbrl_url TEXT, isin TEXT, symbol TEXT, scrip_code TEXT, company TEXT,
  index_period TEXT, reporting_quarter TEXT, consolidated TEXT, audited TEXT, period_start TEXT, period_end TEXT,
  fy_start TEXT, fy_end TEXT, board_meeting TEXT, broadcast_ts TEXT, dissem_ts TEXT, filing_ts TEXT,
  audit_opinion TEXT, n_facts INTEGER, status TEXT, parsed_at TEXT);
CREATE TABLE IF NOT EXISTS facts (
  file TEXT, concept TEXT, context TEXT, period_start TEXT, period_end TEXT, instant TEXT, value REAL, unit TEXT, decimals TEXT);
CREATE INDEX IF NOT EXISTS ix_facts_file ON facts(file);
CREATE INDEX IF NOT EXISTS ix_facts_concept ON facts(concept);
CREATE INDEX IF NOT EXISTS ix_filings_isin ON filings(isin, period_end);
"""


def nse_ts(s):
    """'30-Mar-2024 11:26:16' -> '2024-03-30T11:26:16' (IST, as published); None if blank."""
    for fmt in ("%d-%b-%Y %H:%M:%S", "%d-%b-%Y %H:%M", "%d-%b-%Y"):
        try:
            return datetime.strptime((s or "").strip(), fmt).isoformat()
        except ValueError:
            pass
    return None


def load_index():
    idx = {}
    for d in ("nse_results_equities", "nse_results_sme"):
        for f in glob.glob(str(RAW / d / "*.json")):
            try:
                rows = json.load(open(f, encoding="utf-8"))
            except Exception:
                continue
            rows = rows if isinstance(rows, list) else rows.get("data", [])
            for r in rows:
                u = r.get("xbrl") or ""
                if u.endswith(".xml"):
                    idx[os.path.basename(u)] = r
    # 'Integrated Filing - Financials' index (results from the Mar-2025 quarter; fetch_nse_api_raw --datasets
    # nse_integrated): mapped onto the old index's field names. broadcast_Date = when NSE published the filing = the
    # point-in-time stamp (creation_Date is ~15 s later); there is no ISIN in this index (the XBRL carries it).
    for d in ("nse_integrated_equities", "nse_integrated_sme"):
        for f in glob.glob(str(RAW / d / "*.json")):
            try:
                rows = json.load(open(f, encoding="utf-8"))
            except Exception:
                continue
            for r in rows:
                u = r.get("xbrl") or ""
                if u.endswith(".xml"):
                    idx[os.path.basename(u)] = {
                        "xbrl": u, "symbol": r.get("symbol"), "companyName": r.get("cmName") or r.get("smName"),
                        "period": f"Integrated-{r.get('type_Sub') or 'Original'}", "consolidated": r.get("consolidated"),
                        "audited": r.get("audited"), "broadCastDate": r.get("broadcast_Date"),
                        "exchdisstime": r.get("broadcast_Date"), "filingDate": r.get("creation_Date")}
    return idx


def parse(path):
    tree = etree.parse(str(path), etree.XMLParser(recover=True, huge_tree=True))
    root = tree.getroot()
    ctx = {}
    for c in root.findall("xbrli:context", NS):
        if c.find(".//xbrli:scenario", NS) is not None or c.find(".//xbrli:segment", NS) is not None:
            continue   # dimensional (segment / axis member) contexts are left out
        p = c.find("xbrli:period", NS)
        ctx[c.get("id")] = (p.findtext("xbrli:startDate", namespaces=NS), p.findtext("xbrli:endDate", namespaces=NS),
                            p.findtext("xbrli:instant", namespaces=NS))
    facts, text = [], {}
    for el in root:
        if not isinstance(el.tag, str):
            continue
        cref = el.get("contextRef")
        if cref not in ctx:
            # ~40k NSE files reference the standard contexts (OneD = this quarter, FourD = year to date, OneI = period
            # end, ...) without defining them; keep those, dated later from the filing's own reporting-period facts
            if not cref or not STD_CTX.match(cref):
                continue
            ctx[cref] = (None, None, None)
        concept = etree.QName(el).localname
        val = (el.text or "").strip()
        if concept in TEXT_KEEP:
            text.setdefault(concept, {})[cref] = val
        try:
            v = float(val)
        except ValueError:
            continue
        s, e, i = ctx[cref]
        facts.append((concept, cref, s, e, i, v, el.get("unitRef"), el.get("decimals")))
    return facts, text


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--reparse", action="store_true", help="drop files that gave no facts or failed, and parse them again")
    a = ap.parse_args()
    db = sqlite3.connect(OUT, timeout=120)
    db.executescript(SCHEMA)
    if a.reparse:
        with db:
            bad = [r[0] for r in db.execute("SELECT file FROM filings WHERE status <> 'ok'")]
            db.executemany("DELETE FROM facts WHERE file=?", [(b,) for b in bad])
            db.executemany("DELETE FROM filings WHERE file=?", [(b,) for b in bad])
        print("re-parsing", len(bad))
    done = {r[0] for r in db.execute("SELECT file FROM filings")}
    files = sorted(f for f in os.listdir(RAW / "nse_results_xbrl") if f.endswith(".xml") and f not in done)
    if a.limit:
        files = files[:a.limit]
    idx = load_index()
    print(f"files to parse {len(files)} (already {len(done)}), index entries {len(idx)}", flush=True)
    t0, n = time.time(), 0
    batch_f, batch_x = [], []
    for name in files:
        r = idx.get(name, {})
        try:
            facts, text = parse(RAW / "nse_results_xbrl" / name)
            first = lambda k: next(iter(text.get(k, {}).values()), None)   # noqa: E731
            per = text.get("DateOfStartOfReportingPeriod", {})
            status = "ok" if facts else "no_facts"
        except Exception as e:   # noqa: BLE001  (truncated/HTML error pages saved as .xml)
            facts, text, per, status = [], {}, {}, f"error: {str(e)[:80]}"
            first = lambda k: None   # noqa: E731
        batch_f.append((name, name.split("_")[0], r.get("xbrl"), r.get("isin") or first("ISIN"), r.get("symbol") or first("Symbol"),
                        first("ScripCode"), r.get("companyName") or first("NameOfTheCompany"), r.get("period"),
                        first("ReportingQuarter"), r.get("consolidated") or first("NatureOfReportStandaloneConsolidated"),
                        r.get("audited") or first("WhetherResultsAreAuditedOrUnaudited"),
                        text.get("DateOfStartOfReportingPeriod", {}).get("OneD") or first("DateOfStartOfReportingPeriod"),
                        text.get("DateOfEndOfReportingPeriod", {}).get("OneD") or first("DateOfEndOfReportingPeriod"),
                        first("DateOfStartOfFinancialYear"), first("DateOfEndOfFinancialYear"),
                        first("DateOfBoardMeetingWhenFinancialResultsWereApproved") or first("DateOfEndOfBoardMeeting"),
                        nse_ts(r.get("broadCastDate")), nse_ts(r.get("exchdisstime")), nse_ts(r.get("filingDate")),
                        first("DeclarationOfUnmodifiedOpinionOrStatementOnImpactOfAuditQualification"), len(facts), status,
                        datetime.now().isoformat(timespec="seconds")))
        batch_x.extend((name, *f) for f in facts)
        n += 1
        if n % 1000 == 0 or n == len(files):
            with db:
                db.executemany("INSERT OR REPLACE INTO filings VALUES (" + ",".join("?" * 23) + ")", batch_f)
                db.executemany("INSERT INTO facts VALUES (?,?,?,?,?,?,?,?,?)", batch_x)
            batch_f, batch_x = [], []
            print(f"{n}/{len(files)} ({n / (time.time() - t0):.0f} files/s)", flush=True)
    # the reporting period is context 'OneD' (NSE's standard id for the current quarter / half / year); dates on the
    # contexts are not trusted: some filers stamp the year-to-date context (FourD) with the quarter's dates
    cols = ",\n  ".join(f"MAX(CASE WHEN x.concept='{c}' THEN x.value END) AS {c}" for c in PIVOT)
    db.executescript(f"""DROP VIEW IF EXISTS quarterly;
CREATE VIEW quarterly AS
SELECT f.file, f.taxonomy, f.isin, f.symbol, f.scrip_code, f.company, f.consolidated, f.audited, f.period_start, f.period_end,
       f.index_period, f.reporting_quarter, f.board_meeting, f.dissem_ts, f.broadcast_ts,
  {cols}
FROM filings f JOIN facts x ON x.file = f.file AND x.context = 'OneD'
WHERE f.status = 'ok'
GROUP BY f.file;""")
    print(db.execute("SELECT status, COUNT(*) FROM filings GROUP BY 1").fetchall())
    print("with dissemination time", db.execute("SELECT COUNT(*) FROM filings WHERE dissem_ts IS NOT NULL").fetchone())


if __name__ == "__main__":
    main()
