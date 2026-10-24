"""Build A1: 200 BSE announcements stratified over the 8 most common categories (Sep-Oct 2026).

State = headline + subject (+ first ~1500 chars of attachment text when downloadable).
Downloads attachments to cache/a1_pdf, extracts text with PyMuPDF, writes data/a1_items.json.
"""
import json
import re
import random
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

ROOT = Path(r"C:\Users\warri\Downloads\IDM-worktrees\20261024T172743Z-a480564b")
DATA = Path(r"C:\Users\warri\Downloads\Info_Diffusion_Model\reality_engine\data")
OUT = ROOT / "tasks/research/decision_pilot"
CACHE = OUT / "cache/a1_pdf"
CATS = ["Company Update", "AGM/EGM", "Insider Trading / SAST", "Others",
        "Board Meeting", "Corp. Action", "Mutual Fund", "Result"]


def norm_cat(s):
    s = re.sub(r"\s+", " ", (s or "").strip())
    if s.lower() == "corp action":
        return "Corp. Action"
    return s


def fetch_text(row):
    name = row["attachment"] or ""
    if not name.lower().endswith(".pdf"):
        return None
    dest = CACHE / name
    if not dest.exists():
        url = f"https://www.bseindia.com/xml-data/corpfiling/AttachLive/{name}"
        try:
            r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=40)
            if r.status_code != 200 or not r.content.startswith(b"%PDF"):
                return None
            dest.write_bytes(r.content)
        except Exception:
            return None
    try:
        import pymupdf
        doc = pymupdf.open(dest)
        txt = "\n".join(page.get_text() for page in doc)
        doc.close()
        txt = re.sub(r"[ \t]+", " ", txt)
        txt = re.sub(r"\n{2,}", "\n", txt).strip()
        return txt[:1500] if len(txt) >= 120 else None
    except Exception:
        return None


def main():
    con = sqlite3.connect(f"file:{DATA / 'bse_announcements.db'}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    rows = con.execute("""select NEWSID, SCRIP_CD, symbol, DT_TM, CATEGORYNAME, SUBCATNAME,
        HEADLINE, NEWSSUB, ATTACHMENTNAME from ann where DT_TM>=? and DT_TM<?""",
                       ("2026-09-01", "2026-11-01")).fetchall()
    by = {}
    for r in rows:
        c = norm_cat(r["CATEGORYNAME"])
        if c in CATS:
            by.setdefault(c, []).append(dict(r))
    rng = random.Random(20261024)
    items = []
    for c in CATS:
        pool = by.get(c, [])
        print(c, len(pool))
        for r in rng.sample(pool, min(25, len(pool))):
            items.append({"arm": "A1", "id": r["NEWSID"], "symbol": r["symbol"],
                          "label": c, "exchange_category": r["CATEGORYNAME"],
                          "subcategory": r["SUBCATNAME"], "date": r["DT_TM"],
                          "headline": (r["HEADLINE"] or "").strip(),
                          "subject": (r["NEWSSUB"] or "").strip(),
                          "attachment": r["ATTACHMENTNAME"]})
    CACHE.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(8) as ex:
        texts = list(ex.map(fetch_text, items))
    have = 0
    for it, t in zip(items, texts):
        it["attachment_text"] = t
        have += bool(t)
        body = "\n".join(x for x in [it["headline"], it["subject"]] if x)
        it["state"] = body + ("\n\n" + t if t else "")
    print(f"items={len(items)} attachment_text={have} ({have/len(items):.0%})")
    out = OUT / "data/a1_items.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    json.dump(items, open(out, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    print("wrote", out)


if __name__ == "__main__":
    main()
