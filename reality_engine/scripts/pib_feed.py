"""PIB (Press Information Bureau) English releases: daily feed + backfill (2026-10-19; Shivam: government policy change,
announced or in the pipeline, is a core pillar of the trading policy).

The old fetcher (run_pib_ingest / policy_press_client) walked release IDs one by one; PIB gives every language its own
ID, so 21 of 23 hits were Hindi/regional and 0 were ingested; it was never scheduled (2 PIB releases in the DB).

This uses PIB's own day listing (allRel.aspx, region 3 = PIB Delhi HQ, lang 1 = English, all ministries; ASP.NET
postback) and the release page PressReleasePage.aspx?PRID=..., which carries 'Posted On: 16 OCT 2026 3:08PM by PIB
Delhi' = the point-in-time stamp (IST, minute precision).
  pib_releases (prid, release_date, posted_at, ministry, title, relevant, body, fetched_at, doc_id)
      every English Delhi release title is kept; body fetched for relevant ones (policy ministries, or PMO / President /
      VP / Cabinet titles with policy words); bodies go into the search layer (raw_documents + chunks + FTS + vectors,
      source_type PIB_Press_Release, published_date = posting date) via PDFIngestor.ingest_text.
  pib_days (day, n, done_at)  resumability for the listing
Resumable: listed days and fetched bodies are skipped. Paced ~0.6 s per request.

    python -m reality_engine.scripts.pib_feed                      # last 3 days (daily)
    python -m reality_engine.scripts.pib_feed --start 2021-01-01   # backfill
"""
import argparse
import datetime as dt
import re
import sqlite3
import sys
import time
from pathlib import Path

import requests
from lxml import html

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
DB = ROOT / "reality_engine/data/equity_intelligence.db"
LIST_URL = "https://www.pib.gov.in/allRel.aspx?reg=3&lang=1"
PAGE_URL = "https://www.pib.gov.in/PressReleasePage.aspx?PRID={prid}&reg=3&lang=1"
DDL = """
CREATE TABLE IF NOT EXISTS pib_releases (prid INTEGER PRIMARY KEY, release_date TEXT, posted_at TEXT, ministry TEXT,
    title TEXT, relevant INTEGER, body TEXT, fetched_at TEXT, doc_id INTEGER);
CREATE INDEX IF NOT EXISTS idx_pib_date ON pib_releases(release_date);
CREATE TABLE IF NOT EXISTS pib_days (day TEXT PRIMARY KEY, n INTEGER, done_at TEXT);
"""
POLICY_MINISTRY = re.compile(
    r"cabinet|ccea|finance|commerce|heavy industr|power|petroleum|coal|mines|steel|railway|road transport|shipping|ports|"
    r"defence|electronics|chemical|pharma|fertili|agricultur|food processing|textile|micro,? ?small|renewable|"
    r"communications|telecom|civil aviation|corporate affairs|consumer affairs|statistics|niti|housing|jal shakti|"
    r"rural development|health|education|labour|environment|earth sciences|space|atomic|science|cooperation|"
    r"fisheries|animal husbandry|tourism|external affairs|home affairs|law|skill|panchayati|north-east|minority", re.I)
GATED = re.compile(r"president|vice president|prime minister|lok sabha|rajya sabha|election", re.I)
POLICY_WORDS = re.compile(r"approv|scheme|crore|policy|tariff|duty|pli|incentive|cabinet|budget|reform|notif|amend|"
                          r"bill|act\b|regulat|capex|invest|export|import|gst|tax|subsid|msp|auction|tender|launch|"
                          r"mission|programme|program|allocat|outlay|infrastructure|semiconductor|manufactur", re.I)
MON = {m: i for i, m in enumerate(["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"], 1)}


def session():
    s = requests.Session()
    s.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
                      "Referer": "https://www.pib.gov.in/"})
    return s


def list_day(s, d):
    """[(prid, ministry, title)] of English PIB Delhi releases dated d"""
    t = html.fromstring(s.get(LIST_URL, timeout=60).text)
    form = {i.get("name"): i.get("value", "") for i in t.xpath("//input[@type='hidden']") if i.get("name")}
    form.update({"ctl00$ContentPlaceHolder1$ddlMinistry": "0", "ctl00$ContentPlaceHolder1$ddlday": str(d.day),
                 "ctl00$ContentPlaceHolder1$ddlMonth": str(d.month), "ctl00$ContentPlaceHolder1$ddlYear": str(d.year),
                 "__EVENTTARGET": "ctl00$ContentPlaceHolder1$ddlday", "__EVENTARGUMENT": ""})
    t2 = html.fromstring(s.post(LIST_URL, data=form, timeout=90).text)
    out = []
    for ul in t2.xpath("//ul[@class='num']"):
        head = ul.xpath("preceding-sibling::*[1]")
        ministry = re.sub(r"\s+", " ", head[0].text_content()).strip() if head else None
        for a in ul.xpath(".//a[contains(@href,'PRID=')]"):
            m = re.search(r"PRID=(\d+)", a.get("href"))
            if m:
                out.append((int(m.group(1)), ministry, re.sub(r"\s+", " ", a.text_content()).strip()))
    return out


def relevant(ministry, title):
    """keep (fetch the body of) everything except ceremonial PMO / President / VP / Parliament items without a policy
    word; title-keyword relevance was both too loose (a ministry's cyber-security workshop) and too strict (a PIB
    waterways policy backgrounder) on 2026-10-16, so the policy register's LLM pass decides relevance instead"""
    if ministry and GATED.search(ministry):
        return bool(POLICY_WORDS.search(title or ""))
    return True


def fetch_body(s, prid):
    """(posted_at 'YYYY-MM-DDTHH:MM' IST, body text) from the release page"""
    t = html.fromstring(s.get(PAGE_URL.format(prid=prid), timeout=60).text)
    for bad in t.xpath("//script|//style|//noscript"):
        bad.drop_tree()
    txt = re.sub(r"[ \t\r\f\v]+", " ", t.text_content())
    txt = re.sub(r"\n\s*\n+", "\n\n", txt)
    m = re.search(r"Posted On:\s*(\d{1,2}) ([A-Z]{3}) (\d{4}) (\d{1,2}):(\d{2}) ?([AP]M)", txt)
    posted = None
    if m:
        h = int(m.group(4)) % 12 + (12 if m.group(6) == "PM" else 0)
        posted = f"{m.group(3)}-{MON[m.group(2)]:02d}-{int(m.group(1)):02d}T{h:02d}:{m.group(5)}"
        txt = txt[m.start():]
    end = re.search(r"\(Release ID:\s*\d+\)", txt)
    if end:
        txt = txt[:end.end()]
    return posted, txt.strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default=(dt.date.today() - dt.timedelta(days=3)).isoformat())
    ap.add_argument("--end", default=dt.date.today().isoformat())
    ap.add_argument("--no-ingest", action="store_true", help="store bodies only, skip the search layer")
    a = ap.parse_args()
    db = sqlite3.connect(DB, timeout=600)
    db.executescript(DDL)
    s = session()
    ingestor = None
    if not a.no_ingest:
        from reality_engine.db.database import db_manager
        from reality_engine.ingestion.pdf_ingestor import PDFIngestor
        ingestor = PDFIngestor(db=db_manager)
    d, end = dt.date.fromisoformat(a.start), dt.date.fromisoformat(a.end)
    recent = dt.date.today() - dt.timedelta(days=3)
    while d <= end:
        done = db.execute("SELECT 1 FROM pib_days WHERE day=?", (d.isoformat(),)).fetchone()
        if not done or d >= recent:          # recent days are re-listed (late releases)
            for attempt in range(4):
                try:
                    rows = list_day(s, d); break
                except Exception as e:  # noqa: BLE001
                    time.sleep(15 * (attempt + 1)); s = session(); rows = None
            if rows is not None:
                with db:
                    db.executemany("INSERT OR IGNORE INTO pib_releases (prid, release_date, ministry, title, relevant) "
                                   "VALUES (?,?,?,?,?)", [(p, d.isoformat(), m, t, int(relevant(m, t))) for p, m, t in rows])
                    db.execute("INSERT OR REPLACE INTO pib_days VALUES (?,?,?)",
                               (d.isoformat(), len(rows), dt.datetime.now().isoformat(timespec="seconds")))
            time.sleep(0.6)
        todo = db.execute("SELECT prid, ministry, title FROM pib_releases WHERE release_date=? AND relevant=1 AND body IS NULL",
                          (d.isoformat(),)).fetchall()
        got = 0
        for prid, ministry, title in todo:
            try:
                posted, body = fetch_body(s, prid)
            except Exception:  # noqa: BLE001
                time.sleep(5); s = session(); continue
            doc_id = None
            if ingestor and body and len(body) > 200:
                try:
                    res = ingestor.ingest_text(body, title=title, source_type="PIB_Press_Release",
                                               published_date=(posted or d.isoformat())[:10],
                                               source_url=PAGE_URL.format(prid=prid), creator_or_ministry=ministry)
                    doc_id = (res or {}).get("doc_id")
                except Exception:  # noqa: BLE001
                    pass
            with db:
                db.execute("UPDATE pib_releases SET posted_at=?, body=?, fetched_at=?, doc_id=? WHERE prid=?",
                           (posted, body, dt.datetime.now().isoformat(timespec="seconds"), doc_id, prid))
            got += 1
            time.sleep(0.6)
        n = db.execute("SELECT COUNT(*), SUM(relevant) FROM pib_releases WHERE release_date=?", (d.isoformat(),)).fetchone()
        print(f"{d} listed {n[0]} relevant {n[1]} bodies fetched now {got}", flush=True)
        d += dt.timedelta(days=1)


if __name__ == "__main__":
    main()
