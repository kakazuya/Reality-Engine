"""Fetch macro policy documents 2019-2026 with their real publication dates, then ingest them (2026-10-17).

The August macro set was a sample: 2 years of speeches, wrong dates (state budgets carried the Union Budget's date or
the fetch date 2026-08-14, the ingestor's fallback) and a mislabelled RBI file. This builds a manifest of documents with
the date each was made public (point-in-time: a strategy may only see a document from that date), downloads them into
RAW_ROOT/macro_pdfs/<category>/<fy>/, and ingests each through PDFIngestor.ingest_macro_file with the date passed explicitly.

Sources (one module per source; each yields dicts: category, source_type, fy, date, url, title, creator):
  union   indiabudget.gov.in archive: speech, Budget at a Glance, Finance Bill memorandum, macro framework statement
  survey  indiabudget.gov.in archive: Economic Survey chapters / volumes / statistical appendix
  rbi     rbi.org.in: monetary policy statements, MPC minutes, Financial Stability Report, Annual Report
  states  PRS Legislative Research state budget analyses (one per state-year, dated by the budget presentation)

    python -m reality_engine.scripts.fetch_macro_docs --sources union,survey --dry
    python -m reality_engine.scripts.fetch_macro_docs --sources union,survey,rbi,states
"""
import argparse
import concurrent.futures as cf
import json
import re
import time
from pathlib import Path
from reality_engine.config import MACRO_PDFS_DIR

from curl_cffi import requests

DATA = Path(__file__).resolve().parents[1] / "data"
OUT = MACRO_PDFS_DIR
MANIFEST = OUT / "manifest.json"
IB = "https://www.indiabudget.gov.in"

# (archive folder, fiscal year, presentation date); the current year lives at the site root
UNION = [("budget2019-20", "FY2019-20", "2019-07-05"), ("budget2020-21", "FY2020-21", "2020-02-01"),
         ("budget2021-22", "FY2021-22", "2021-02-01"), ("budget2022-23", "FY2022-23", "2022-02-01"),
         ("budget2023-24", "FY2023-24", "2023-02-01"), ("budget2024-25(I)", "FY2024-25 interim", "2024-02-01"),
         ("budget2024-25", "FY2024-25", "2024-07-23"), ("budget2025-26", "FY2025-26", "2025-02-01"),
         ("", "FY2026-27", "2026-02-01")]
UNION_DOCS = [("doc/Budget_Speech.pdf", "Budget Speech"),
              ("doc/Budget_at_Glance/budget_at_a_glance.pdf", "Budget at a Glance"),
              ("doc/memo.pdf", "Memorandum explaining the Finance Bill"),
              ("doc/frbm1.pdf", "Macro-Economic Framework Statement")]
# Economic Survey: tabled the day before the budget (2019: 4 Jul; 2024: 22 Jul)
SURVEY = [("budget2019-20", "2018-19", "2019-07-04"), ("budget2020-21", "2019-20", "2020-01-31"),
          ("budget2021-22", "2020-21", "2021-01-29"), ("budget2022-23", "2021-22", "2022-01-31"),
          ("budget2023-24", "2022-23", "2023-01-31"), ("budget2024-25", "2023-24", "2024-07-22"),
          ("budget2025-26", "2024-25", "2025-01-31"), ("", "2025-26", "2026-01-29")]
SURVEY_DOCS = [("economicsurvey/doc/echapter.pdf", "chapters"), ("economicsurvey/doc/echapter_vol1.pdf", "volume 1"),
               ("economicsurvey/doc/echapter_vol2.pdf", "volume 2"),
               ("economicsurvey/doc/Statistical-Appendix-in-English.pdf", "statistical appendix")]


def session():
    return requests.Session(impersonate="chrome")


def union(s):
    for folder, fy, date in UNION:
        for path, name in UNION_DOCS:
            yield {"category": "central_budgets", "source_type": "Union_Budget", "fy": fy, "date": date,
                   "url": f"{IB}/{folder + '/' if folder else ''}{path}", "title": f"Union Budget {fy} - {name}",
                   "creator": "Ministry of Finance"}


def survey(s):
    for folder, yr, date in SURVEY:
        for path, name in SURVEY_DOCS:
            yield {"category": "central_surveys", "source_type": "Economic_Survey", "fy": f"FY{yr}", "date": date,
                   "url": f"{IB}/{folder + '/' if folder else ''}{path}", "title": f"Economic Survey {yr} - {name}",
                   "creator": "Ministry of Finance"}


RBI = "https://www.rbi.org.in/Scripts/"
MONTHS = {m: i for i, m in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split(), 1)}


def _form(html):
    return {n: (re.search(rf'name="{re.escape(n)}"[^>]*value="([^"]*)"', html) or [None, ""])[1]
            for n in ("__VIEWSTATE", "__VIEWSTATEGENERATOR", "__EVENTVALIDATION")}


def _rbi_release(s, prid):
    """(date, pdf url) of an RBI press release: the PDF link on the page and its 'Date : Oct 07, 2026' line."""
    h = s.get(f"{RBI}BS_PressReleaseDisplay.aspx?prid={prid}", timeout=60).text
    pdf = re.search(r"href=['\"](https://rbidocs\.rbi\.org\.in/rdocs/PressRelease/PDFs/[^'\"]+\.pdf)['\"]", h, re.I)
    d = re.search(r"Date\s*:\s*([A-Za-z]{3})[a-z]*\s+(\d{1,2}),\s*(\d{4})", h)
    date = f"{d.group(3)}-{MONTHS[d.group(1).lower()]:02d}-{int(d.group(2)):02d}" if d else None
    return date, pdf.group(1) if pdf else None


def rbi(s):
    """Monetary policy: statements / resolutions / Governor's statements and MPC minutes, RBI years 2019-2027."""
    h = s.get(f"{RBI}Annualpolicy.aspx", timeout=60).text
    seen = {}
    for yr in range(2019, 2028):
        f = _form(h); f.update({"__EVENTTARGET": "", "__EVENTARGUMENT": "", "hdnYear": str(yr)})
        page = s.post(f"{RBI}Annualpolicy.aspx", data=f, timeout=60).text
        for prid, title in re.findall(r'BS_PressReleaseDisplay\.aspx\?prid=(\d+)"[^>]*>([^<]+)<', page):
            seen.setdefault(prid, (title.strip(), yr))
        time.sleep(0.5)
    for prid, (title, yr) in sorted(seen.items()):
        if not re.search(r"(?i)minutes|statement|resolution|full document|monetary policy", title):
            continue
        date, pdf = _rbi_release(s, prid)
        if not (date and pdf) or date < "2019-01-01":
            continue
        kind = "RBI_MPC_Minutes" if "minutes" in title.lower() else "RBI_Monetary_Policy"
        fy = f"FY{yr - 1}-{str(yr)[2:]}"
        yield {"category": "rbi", "source_type": kind, "fy": fy, "date": date, "url": pdf,
               "title": f"RBI {title} ({date})", "creator": "Reserve Bank of India",
               "page": f"{RBI}BS_PressReleaseDisplay.aspx?prid={prid}"}
        time.sleep(0.3)


RBI_REPORTS = [(r"(?i)financial stability report", "RBI_Financial_Stability_Report"),
               (r"(?i)monetary policy report", "RBI_Monetary_Policy_Report"),
               (r"(?i)annual report (of the reserve bank|for the year|20\d\d)|releases annual report|rbi annual report",
                "RBI_Annual_Report")]


def rbi_reports(s):
    """FSR (half-yearly), Monetary Policy Report (half-yearly), RBI Annual Report: found in the monthly press-release
    archive (the publication pages load by JavaScript; rbidocs PDFs sit behind a bot check, so fetch() falls back to the
    release text, which carries the report's main findings)."""
    u = f"{RBI}BS_PressReleaseDisplay.aspx"
    h = s.get(u, timeout=60).text
    for yr in range(2019, 2027):
        for mo in range(1, 13):
            f = _form(h); f.update({"__EVENTTARGET": "", "__EVENTARGUMENT": "", "hdnYear": str(yr), "hdnMonth": str(mo)})
            try:
                page = s.post(u, data=f, timeout=60).text
            except Exception:
                continue
            for prid, title in re.findall(r"prid=(\d+)>([^<]+)<", page):
                kind = next((k for pat, k in RBI_REPORTS if re.search(pat, title)), None)
                if not kind or re.search(r"(?i)co-?operative|urban bank|statutory auditor", title):
                    continue
                date, pdf = _rbi_release(s, prid)
                if not date:
                    continue
                fy = f"FY{yr - 1}-{str(yr)[2:]}" if mo < 4 else f"FY{yr}-{str(yr + 1)[2:]}"
                yield {"category": "rbi", "source_type": kind, "fy": fy, "date": date,
                       "url": pdf or f"{RBI}BS_PressReleaseDisplay.aspx?prid={prid}", "title": f"RBI {title.strip()}",
                       "creator": "Reserve Bank of India", "page": f"{RBI}BS_PressReleaseDisplay.aspx?prid={prid}"}
            time.sleep(0.3)


PRS = "https://prsindia.org"
FULL_MONTHS = {m: i for i, m in enumerate("january february march april may june july august september october "
                                          "november december".split(), 1)}


def states(s):
    """PRS state budget analyses 2019-20 .. 2026-27, dated by the budget presentation the analysis states."""
    h = s.get(f"{PRS}/budgets/states", timeout=60).text
    pages = sorted(set(re.findall(r'href="(/budgets/states/([a-z-]+)-budget-analysis-(20(?:19|2\d))-(\d{2,4}))"', h)))
    for path, state, y0, _ in pages:
        try:
            page = s.get(PRS + path, timeout=60).text
        except Exception:
            continue
        pdf = re.search(r'href="([^"]+\.pdf)"', page, re.I)
        text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", page))
        d = re.search(r"present\w* [^.]{0,160}? on (\w+) (\d{1,2}), (\d{4})", text)
        if not pdf or not d or d.group(1).lower() not in FULL_MONTHS:
            print(f"  states: no pdf/date on {path}"); continue
        date = f"{d.group(3)}-{FULL_MONTHS[d.group(1).lower()]:02d}-{int(d.group(2)):02d}"
        name = state.replace("-", " ").title()
        fy = f"FY{y0}-{str(int(y0) + 1)[2:]}"
        url = pdf.group(1) if pdf.group(1).startswith("http") else PRS + pdf.group(1).replace(" ", "%20")
        yield {"category": f"state_{name.replace(' ', '_')}", "source_type": f"State_Budget_{name.replace(' ', '_')}",
               "fy": fy, "date": date, "url": url, "title": f"{name} Budget Analysis {fy} (PRS)",
               "creator": "PRS Legislative Research"}
        time.sleep(0.3)


SOURCES = {"union": union, "survey": survey, "rbi": rbi, "states": states, "rbi_reports": rbi_reports}


def fetch(item, s):
    sub = OUT / item["category"] / item["fy"].replace(" ", "_")
    sub.mkdir(parents=True, exist_ok=True)
    dest = sub / re.sub(r"[^\w.()-]+", "_", item["url"].rsplit("/", 1)[-1])
    for have in (dest, dest.with_suffix(".txt")):
        if have.exists() and have.stat().st_size > 500:
            return {**item, "path": str(have), "status": "have"}
    for attempt in range(3):
        try:
            r = s.get(item["url"], timeout=300)
            if r.status_code == 404:
                return {**item, "status": "404"}
            if r.status_code == 200 and r.content[:4] == b"%PDF":
                dest.write_bytes(r.content)
                return {**item, "path": str(dest), "status": "fetched", "bytes": len(r.content)}
            last = f"HTTP {r.status_code} {r.headers.get('content-type', '')[:20]}"
        except Exception as e:
            last = str(e)[:80]
        time.sleep(3)
    if item.get("page"):
        # 2026-10-17: rbidocs.rbi.org.in answers scripted downloads with a JavaScript bot check (HTML, not the PDF).
        # The press-release page on www.rbi.org.in carries the same statement / minutes as text: store that instead.
        try:
            h = s.get(item["page"], timeout=60).text
            i = h.find('class="tablebg"')
            j = h.find("Press Release:", i)
            body = h[i:j + 40] if i > 0 and j > i else ""
            text = re.sub(r"(?i)</p>|<br\s*/?>|</tr>", "\n", body)
            text = re.sub(r"[ \t]+", " ", re.sub(r"<[^>]+>", " ", text))
            text = re.sub(r"\n\s*\n+", "\n\n", text).strip()
            if len(text) > 500:
                dest = dest.with_suffix(".txt")
                dest.write_text(text, encoding="utf-8")
                return {**item, "path": str(dest), "status": "fetched_text", "bytes": len(text)}
        except Exception as e:
            last = f"{last}; page: {str(e)[:60]}"
    return {**item, "status": f"failed: {last}"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sources", default="union,survey")
    ap.add_argument("--dry", action="store_true", help="list the manifest only")
    ap.add_argument("--no-ingest", action="store_true")
    ap.add_argument("--workers", type=int, default=6)
    a = ap.parse_args()
    s = session()
    items = [it for name in a.sources.split(",") for it in SOURCES[name](s)]
    print(f"{len(items)} candidate documents")
    if a.dry:
        for it in items:
            print(it["date"], it["source_type"], it["url"])
        return
    with cf.ThreadPoolExecutor(a.workers) as ex:
        res = list(ex.map(lambda it: fetch(it, session()), items))
    got = [r for r in res if r.get("path")]
    for st in sorted({r["status"].split(":")[0] for r in res}):
        print(st, sum(r["status"].split(":")[0] == st for r in res))
    for r in res:
        if r["status"].startswith("failed"):
            print("  ", r["status"], r["url"])
    old = json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.exists() else []
    keep = {o["url"]: o for o in old}
    keep.update({r["url"]: r for r in got})
    MANIFEST.write_text(json.dumps(list(keep.values()), indent=1), encoding="utf-8")
    if a.no_ingest:
        return
    from reality_engine.ingestion.pdf_ingestor import PDFIngestor
    ing = PDFIngestor()
    counts = {}
    for r in got:
        out = {}
        try:
            if r["path"].endswith(".txt"):
                out = ing.ingest_text(Path(r["path"]).read_text(encoding="utf-8"), title=r["title"],
                                      source_type=r["source_type"], published_date=r["date"],
                                      source_url=r.get("page") or r["url"], fiscal_period=r["fy"],
                                      creator_or_ministry=r["creator"])
            else:
                out = ing.ingest_macro_file(r["path"], source_type=r["source_type"], fiscal_period=r["fy"],
                                            source_url=r["url"], title=r["title"], published_date=r["date"],
                                            creator_or_ministry=r["creator"])
            st = out.get("status")
        except Exception as e:
            st = f"error {str(e)[:60]}"
        counts[st] = counts.get(st, 0) + 1
        print(r["date"], r["title"][:60], "->", st, out.get("chunks", ""), flush=True)
    print("ingest:", counts)


if __name__ == "__main__":
    main()
