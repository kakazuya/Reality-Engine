"""List KEC's transcript page and save the transcript PDFs to D. Raw fetch only; nothing is loaded."""
import hashlib
import json
import re
import sqlite3
import sys
from pathlib import Path
from urllib.parse import quote, urljoin

import requests

OUT = Path(r"D:\RealityEngine\raw\kec_transcripts")
OUT.mkdir(parents=True, exist_ok=True)
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130 Safari/537.36"}
r = requests.get("https://www.kecrpg.com/earning-call-transcripts", headers=UA, timeout=40)
print("page", r.status_code, len(r.text))
(OUT / "_listing.html").write_text(r.text, encoding="utf-8")
# The page builds its links in script from a JSON object keyed by fiscal year, so the plain HTML has no hrefs.
blob = re.search(r"var data = (\{.*?\});?\s*$", r.text, flags=re.M)
if not blob:
    sys.exit("no data object in the page; the site changed")
calls = [row for rows in json.loads(blob.group(1)).values() for row in rows if row.get("link")]
calls.sort(key=lambda row: row["publishDate"])
print("transcripts listed", len(calls))
for row in calls:
    print(" ", row["publishDate"], row["title"], row["link"].rsplit("/", 1)[-1][:70])
if "--save" in sys.argv:
    manifest = []
    for row in calls:
        url = urljoin("https://www.kecrpg.com/", quote(row["link"], safe="/%:"))  # older links already carry %20
        got = requests.get(url, headers=UA, timeout=90)
        if got.status_code != 200 or not got.content.startswith(b"%PDF"):
            print("skip", got.status_code, url[:100])
            continue
        sha = hashlib.sha256(got.content).hexdigest()
        (OUT / f"{sha}.pdf").write_bytes(got.content)
        manifest.append({"title": row["title"], "site_publish_date": row["publishDate"], "url": url, "sha256": sha, "bytes": len(got.content), "last_modified": got.headers.get("Last-Modified")})
    (OUT / "_manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    print("saved", len(manifest), "of", len(calls))
if "--pair" in sys.argv:
    # known_at comes from the filed cover letter. The site's publishDate is wrong for two quarters (Q4 FY25 shows 2025-01-03), so pair on the file's Last-Modified, which must fall within 2 days of the filing.
    from datetime import datetime
    from email.utils import parsedate_to_datetime

    con = sqlite3.connect("file:reality_engine/data/pilot/pilot60/chunks_v3_pilot.db?mode=ro", uri=True)
    letters = con.execute("select doc_id, sha256, known_at from doc where isin='INE389H01022' and doc_type='concall' order by known_at").fetchall()
    manifest = json.loads((OUT / "_manifest.json").read_text(encoding="utf-8"))
    pairs = []
    for doc_id, sha, known_at in letters:
        filed = datetime.fromisoformat(known_at)
        near = [m for m in manifest if abs((parsedate_to_datetime(m["last_modified"]).replace(tzinfo=None) - filed).total_seconds()) < 2 * 86400]
        if len(near) != 1:
            sys.exit(f"{known_at}: {len(near)} transcripts near this filing, expected 1")
        pairs.append({**near[0], "cover_letter_doc_id": doc_id, "cover_letter_sha256": sha, "known_at": known_at})
    (OUT / "_known_at.json").write_text(json.dumps(pairs, indent=1), encoding="utf-8")
    for pair in pairs:
        print(pair["known_at"], pair["title"], pair["last_modified"][5:16])
