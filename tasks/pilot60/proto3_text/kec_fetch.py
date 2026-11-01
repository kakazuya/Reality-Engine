"""List KEC's transcript page and save the transcript PDFs to D. Raw fetch only; nothing is loaded."""
import hashlib
import json
import re
import sys
from pathlib import Path
from urllib.parse import urljoin

import requests

OUT = Path(r"D:\RealityEngine\raw\kec_transcripts")
OUT.mkdir(parents=True, exist_ok=True)
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130 Safari/537.36"}
r = requests.get("https://www.kecrpg.com/earning-call-transcripts", headers=UA, timeout=40)
print("page", r.status_code, len(r.text))
(OUT / "_listing.html").write_text(r.text, encoding="utf-8")
links = sorted({urljoin(r.url, h) for h in re.findall(r'href="([^"]+\.pdf[^"]*)"', r.text, flags=re.I)})
print("pdf links", len(links))
for l in links[:60]:
    print(" ", l[:120])
if "--save" in sys.argv:
    manifest = []
    for url in links:
        got = requests.get(url, headers=UA, timeout=90)
        if got.status_code != 200 or not got.content.startswith(b"%PDF"):
            print("skip", got.status_code, url[:100])
            continue
        sha = hashlib.sha256(got.content).hexdigest()
        (OUT / f"{sha}.pdf").write_bytes(got.content)
        manifest.append({"url": url, "sha256": sha, "bytes": len(got.content), "last_modified": got.headers.get("Last-Modified")})
    (OUT / "_manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    print("saved", len(manifest))
