"""PIB phase 2 (PIPELINE_TODO A2, 2026-10-19): Hindi / Urdu releases of PIB Delhi and every regional PIB office in every
language it publishes, with translations of English releases marked. pib_feed.py (English, PIB Delhi) is unchanged.

Listing: allRel.aspx?reg=R&lang=L, one ASP.NET postback per (office, language, day); the form state of each answer is
reused for the next day, so a day costs one request per (office, language). Offices and their languages come from
the page's own selects (29 offices; e.g. Mumbai: English, Marathi, Konkani; Chennai: English, Tamil, Hindi).
A release is one PRID; the same PRID shows under several offices (kept once, first office seen).

Body page: PressReleasePage.aspx?PRID=..; the posting stamp has the same form in every language
('<label>: 15 OCT 2026 7:14PM by PIB Mumbai') -> posted_at (IST, minute) and posted_by.

Translations (is the release a translation of an English one?):
  1 release_link  the page links '(Release ID: N)' to another PRID N that is an English release -> translation_of N
  2 embedding     (separate pass, --match) EmbeddingGemma over title + first 1,000 chars vs English releases of the
                  same / previous day; best cosine >= threshold -> translation_of (threshold tuned on a hand-checked
                  sample, A2 check)
Unique non-English releases keep the original text; the policy register answers in English, quoting the original.

Tables (equity_intelligence.db): pib_ml_releases, pib_ml_days, pib_ml_langs.

    python -m reality_engine.scripts.pib_regional --start 2026-09-26 --end 2026-10-15     # listing + bodies
    python -m reality_engine.scripts.pib_regional --start 2021-01-01                      # backfill (newest first)
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
LIST = "https://www.pib.gov.in/allRel.aspx?reg={reg}&lang={lang}"
PAGE = "https://www.pib.gov.in/PressReleasePage.aspx?PRID={prid}&reg={reg}&lang={lang}"
PACE = 0.5
DDL = """
CREATE TABLE IF NOT EXISTS pib_ml_langs (reg INTEGER, reg_name TEXT, lang INTEGER, lang_name TEXT, PRIMARY KEY (reg, lang));
CREATE TABLE IF NOT EXISTS pib_ml_days (day TEXT, reg INTEGER, lang INTEGER, n INTEGER, done_at TEXT,
    PRIMARY KEY (day, reg, lang));
CREATE TABLE IF NOT EXISTS pib_ml_releases (prid INTEGER PRIMARY KEY, release_date TEXT, reg INTEGER, lang INTEGER,
    lang_name TEXT, ministry TEXT, title TEXT, posted_at TEXT, posted_by TEXT, body TEXT, linked_prid INTEGER,
    translation_of INTEGER, match_method TEXT, match_sim REAL, fetched_at TEXT, doc_id INTEGER);
CREATE INDEX IF NOT EXISTS idx_pib_ml_date ON pib_ml_releases(release_date);
"""
STAMP = re.compile(r":\s*(\d{1,2}) ([A-Z]{3}) (\d{4}) (\d{1,2}):(\d{2}) ?([AP]M) by (PIB [A-Za-z .&]+?)(?=\s|$)")
MON = {m: i for i, m in enumerate(["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"], 1)}


def session():
    s = requests.Session()
    s.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
                      "Referer": "https://www.pib.gov.in/"})
    return s


def hidden(t):
    return {i.get("name"): i.get("value", "") for i in t.xpath("//input[@type='hidden']") if i.get("name")}


def offices(s, db):
    """[(reg, reg_name, lang, lang_name)] from the page selects; cached in pib_ml_langs."""
    rows = db.execute("SELECT reg, reg_name, lang, lang_name FROM pib_ml_langs").fetchall()
    if rows:
        return rows
    t = html.fromstring(s.get(LIST.format(reg=3, lang=1), timeout=60).text)
    regs = [(int(o.get("value")), o.text_content().strip()) for o in t.xpath("//select[@name='ctl00$Bar1$ddlregion']//option")]
    out = []
    for reg, name in regs:
        tr = html.fromstring(s.get(LIST.format(reg=reg, lang=1), timeout=60).text)
        for o in tr.xpath("//select[@name='ctl00$Bar1$ddlLang']//option"):
            out.append((reg, name, int(o.get("value")), o.text_content().strip()))
        time.sleep(PACE)
    with db:
        db.executemany("INSERT OR REPLACE INTO pib_ml_langs VALUES (?,?,?,?)", out)
    return out


class Lister:
    """One (office, language) listing; keeps the last answer's form state so each day is a single POST."""

    def __init__(self, s, reg, lang):
        self.s, self.url = s, LIST.format(reg=reg, lang=lang)
        self.form = hidden(html.fromstring(s.get(self.url, timeout=60).text))

    def day(self, d):
        f = dict(self.form)
        f.update({"ctl00$ContentPlaceHolder1$ddlMinistry": "0", "ctl00$ContentPlaceHolder1$ddlday": str(d.day),
                  "ctl00$ContentPlaceHolder1$ddlMonth": str(d.month), "ctl00$ContentPlaceHolder1$ddlYear": str(d.year),
                  "__EVENTTARGET": "ctl00$ContentPlaceHolder1$ddlday", "__EVENTARGUMENT": ""})
        t = html.fromstring(self.s.post(self.url, data=f, timeout=90).text)
        self.form = hidden(t) or self.form
        out = []
        for ul in t.xpath("//ul[@class='num']"):
            head = ul.xpath("preceding-sibling::*[1]")
            ministry = re.sub(r"\s+", " ", head[0].text_content()).strip() if head else None
            for a in ul.xpath(".//a[contains(@href,'PRID=')]"):
                m = re.search(r"PRID=(\d+)", a.get("href"))
                if m:
                    out.append((int(m.group(1)), ministry, re.sub(r"\s+", " ", a.text_content()).strip()))
        return out


def fetch_body(s, prid, reg, lang):
    """(posted_at IST 'YYYY-MM-DDTHH:MM', posted_by, body, linked English PRID or None)"""
    t = html.fromstring(s.get(PAGE.format(prid=prid, reg=reg, lang=lang), timeout=60).text)
    for bad in t.xpath("//script|//style|//noscript"):
        bad.drop_tree()
    txt = re.sub(r"[ \t\r\f\v]+", " ", t.text_content())
    txt = re.sub(r"\n\s*\n+", "\n\n", txt)
    m = STAMP.search(txt)
    posted = by = None
    if m:
        h = int(m.group(4)) % 12 + (12 if m.group(6) == "PM" else 0)
        posted = f"{m.group(3)}-{MON[m.group(2)]:02d}-{int(m.group(1)):02d}T{h:02d}:{m.group(5)}"
        by = m.group(7).strip()
        txt = txt[m.start():]
    ids = [int(x) for x in re.findall(r"\(Release ID:\s*(\d+)\)", txt)]
    linked = next((i for i in ids if i != prid), None)
    own = re.search(rf"\(Release ID:\s*{prid}\)", txt)
    cut = own.end() if own else (re.search(r"\(Release ID:\s*\d+\)", txt).end() if ids else min(len(txt), 20000))
    return posted, by, txt[:cut].strip(), linked


MATCH_DDL = """CREATE TABLE IF NOT EXISTS pib_ml_match (prid INTEGER, mode TEXT, best_prid INTEGER, best_sim REAL,
    second_sim REAL, n_candidates INTEGER, matched_at TEXT, PRIMARY KEY (prid, mode))"""


def cpu_gemma(threads=4):
    """EmbeddingGemma on CPU (the GPU belongs to the re-embed job): ~19 titles/s, ~2 title+body texts/s."""
    import onnxruntime as ort
    from reality_engine.scripts.embed_model_test import Model
    m = Model("embeddinggemma")
    so = ort.SessionOptions()
    so.intra_op_num_threads = threads
    m.sess = ort.InferenceSession(str(m.dir / "onnx/model.onnx"), so, providers=["CPUExecutionProvider"])
    m.provider = "CPU"
    return m


def match_pass(db, start, end, mode="title"):
    """Best English candidate (same or previous day) per non-English release by cosine of EmbeddingGemma vectors.
    mode 'title': title only; 'body': title + first 1,000 characters of the body. Results in pib_ml_match; the
    threshold that turns a match into translation_of is set from the release_link positives + hand checks."""
    import numpy as np
    db.execute(MATCH_DDL)
    m = cpu_gemma()
    def text(t, b):
        return t if mode == "title" else t + "\n" + (b or "")[:1000]
    eng = {}
    for prid, d, t, b in db.execute(
            "SELECT prid, release_date, title, body FROM pib_releases WHERE release_date BETWEEN date(?, '-1 day') AND ? "
            "UNION SELECT prid, release_date, title, body FROM pib_ml_releases WHERE lang_name = 'English' "
            "AND release_date BETWEEN date(?, '-1 day') AND ?", (start, end, start, end)):
        eng[prid] = (d, text(t, b))
    ids = list(eng)
    ev = m.embed([eng[i][1] for i in ids], bs=16 if mode == "title" else 4) if ids else np.zeros((0, 768))
    edate = np.array([eng[i][0] for i in ids])
    todo = db.execute("SELECT prid, release_date, title, body FROM pib_ml_releases WHERE lang_name <> 'English' "
                      "AND release_date BETWEEN ? AND ? AND prid NOT IN (SELECT prid FROM pib_ml_match WHERE mode = ?)",
                      (start, end, mode)).fetchall()
    print(f"match {mode}: {len(ids)} English candidates, {len(todo)} releases", flush=True)
    now = dt.datetime.now().isoformat(timespec="seconds")
    for s in range(0, len(todo), 64):
        part = todo[s:s + 64]
        qv = m.embed([text(t, b) for _, _, t, b in part], bs=16 if mode == "title" else 4)
        out = []
        for (prid, d, _, _), q in zip(part, qv):
            prev = (dt.date.fromisoformat(d) - dt.timedelta(days=1)).isoformat()
            idx = np.flatnonzero((edate == d) | (edate == prev))
            if not len(idx):
                out.append((prid, mode, None, None, None, 0, now)); continue
            sims = ev[idx] @ q
            o = np.argsort(-sims)
            out.append((prid, mode, ids[idx[o[0]]], float(sims[o[0]]), float(sims[o[1]]) if len(o) > 1 else None,
                        len(idx), now))
        with db:
            db.executemany("INSERT OR REPLACE INTO pib_ml_match VALUES (?,?,?,?,?,?,?)", out)
    print(f"match {mode} done", flush=True)


def link_pass(db):
    """translation_of = the linked PRID when that PRID is an English release (PIB Delhi English in pib_releases, or an
    English release listed here). Run after fetching: the English original may be fetched after its translation."""
    with db:
        n = db.execute("""
            UPDATE pib_ml_releases SET translation_of = linked_prid, match_method = 'release_link', match_sim = NULL
             WHERE linked_prid IS NOT NULL AND (match_method IS NULL OR match_method = 'release_link')
               AND lang_name <> 'English'
               AND (linked_prid IN (SELECT prid FROM pib_releases)
                    OR linked_prid IN (SELECT prid FROM pib_ml_releases WHERE lang_name = 'English'))""").rowcount
    return n


# A2 thresholds, set 2026-10-19 on 2026-09-26..10-15 (7,208 non-English releases; PIB Delhi English fetched for the
# window). Body pass: top-1 = the page's own release link for 121 of 124 (97.6%); hand check 10 per band: >= 0.72
# 40/40 correct, 0.65-0.72 ~7/10, < 0.65 3/10 (Odia / Manipuri embed poorly). Title pass alone: sim >= 0.70 with a
# 0.05 lead over the runner-up agrees with the body pass 98.9% and settles ~2/3 of translations without a body fetch.
BODY_SIM = 0.72
TITLE_SIM, TITLE_MARGIN = 0.70, 0.05


def apply_matches(db, start, end):
    """translation_of from the match passes, never over a release_link: body >= BODY_SIM ('embed_body'), else title
    >= TITLE_SIM with a TITLE_MARGIN lead ('embed_title'). Everything else stays NULL (unique or unsure)."""
    with db:
        nb = db.execute("""
            UPDATE pib_ml_releases AS r SET translation_of = m.best_prid, match_method = 'embed_body', match_sim = m.best_sim
              FROM pib_ml_match m
             WHERE m.prid = r.prid AND m.mode = 'body' AND m.best_sim >= ? AND r.release_date BETWEEN ? AND ?
               AND COALESCE(r.match_method, '') <> 'release_link'""", (BODY_SIM, start, end)).rowcount
        nt = db.execute("""
            UPDATE pib_ml_releases AS r SET translation_of = m.best_prid, match_method = 'embed_title', match_sim = m.best_sim
              FROM pib_ml_match m
             WHERE m.prid = r.prid AND m.mode = 'title' AND m.best_sim >= ? AND m.best_sim - COALESCE(m.second_sim, 0) >= ?
               AND r.release_date BETWEEN ? AND ? AND r.translation_of IS NULL""",
                        (TITLE_SIM, TITLE_MARGIN, start, end)).rowcount
    print(f"apply: embed_body {nb}, embed_title {nt}", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default=(dt.date.today() - dt.timedelta(days=3)).isoformat())
    ap.add_argument("--end", default=dt.date.today().isoformat())
    ap.add_argument("--match", choices=["title", "body"], help="embedding match pass only (no fetching)")
    ap.add_argument("--apply", action="store_true", help="set translation_of from the match passes (A2 thresholds)")
    a = ap.parse_args()
    db = sqlite3.connect(DB, timeout=600)
    db.executescript(DDL)
    if a.match:
        return match_pass(db, a.start, a.end, a.match)
    if a.apply:
        print(f"release_link {link_pass(db)}", flush=True)
        return apply_matches(db, a.start, a.end)
    s = session()
    combos = [(r, rn, l, ln) for r, rn, l, ln in offices(s, db) if not (r == 3 and l == 1)]   # Delhi English: pib_feed
    english = {r[0] for r in db.execute("SELECT prid FROM pib_releases")}
    start, d = dt.date.fromisoformat(a.start), dt.date.fromisoformat(a.end)
    recent = dt.date.today() - dt.timedelta(days=3)
    listers = {}
    while d >= start:                                   # newest first
        t0, new = time.time(), 0
        for reg, rname, lang, lname in combos:
            if db.execute("SELECT 1 FROM pib_ml_days WHERE day=? AND reg=? AND lang=?", (d.isoformat(), reg, lang)
                          ).fetchone() and d < recent:
                continue
            rows = None
            for attempt in range(3):
                try:
                    if (reg, lang) not in listers:
                        listers[(reg, lang)] = Lister(s, reg, lang)
                        time.sleep(PACE)
                    rows = listers[(reg, lang)].day(d)
                    break
                except Exception:  # noqa: BLE001
                    listers.pop((reg, lang), None); s = session(); time.sleep(10 * (attempt + 1))
            time.sleep(PACE)
            if rows is None:
                continue
            fresh = [(p, m, t) for p, m, t in rows if p not in english]
            with db:
                db.executemany("INSERT OR IGNORE INTO pib_ml_releases (prid, release_date, reg, lang, lang_name, "
                               "ministry, title) VALUES (?,?,?,?,?,?,?)",
                               [(p, d.isoformat(), reg, lang, lname, m, t) for p, m, t in fresh])
                db.execute("INSERT OR REPLACE INTO pib_ml_days VALUES (?,?,?,?,?)",
                           (d.isoformat(), reg, lang, len(rows), dt.datetime.now().isoformat(timespec="seconds")))
        todo = db.execute("SELECT prid, reg, lang FROM pib_ml_releases WHERE release_date=? AND fetched_at IS NULL",
                          (d.isoformat(),)).fetchall()
        for prid, reg, lang in todo:
            try:
                posted, by, body, linked = fetch_body(s, prid, reg, lang)
            except Exception:  # noqa: BLE001
                time.sleep(5); s = session(); listers.clear(); continue
            tr = linked if linked in english else None
            with db:
                db.execute("UPDATE pib_ml_releases SET posted_at=?, posted_by=?, body=?, linked_prid=?, translation_of=?, "
                           "match_method=?, fetched_at=? WHERE prid=?",
                           (posted, by, body, linked, tr, "release_link" if tr else None,
                            dt.datetime.now().isoformat(timespec="seconds"), prid))
            new += 1
            time.sleep(PACE)
        link_pass(db)
        n = db.execute("SELECT COUNT(*), SUM(translation_of IS NOT NULL) FROM pib_ml_releases WHERE release_date=?",
                       (d.isoformat(),)).fetchone()
        print(f"{d} releases {n[0]} linked-translations {n[1]} bodies now {new} ({time.time() - t0:.0f}s)", flush=True)
        d -= dt.timedelta(days=1)


if __name__ == "__main__":
    main()
