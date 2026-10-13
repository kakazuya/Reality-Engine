"""Year-over-year page skip for annual-report reading (to-do 2026-10-13 in tasks/STATE.md).

A page is skipped only when it repeats the same company's previous-year annual report near word for word INCLUDING its
numbers: >= MIN_CONTAINMENT of the page's 8-word shingles (digits kept, only case and spacing normalised) occur in the
previous report, and the page has at least MIN_SHINGLES shingles. A page whose figures changed cannot pass, so tables
with new numbers are always read. The previous report must itself be in the reading inventory, so its copy of the page
is read (by either worker). A company's first report in the inventory has no reference and is read in full.
(The AR study's yoy.py masks numbers; that would skip tables with changed figures, so it is not used here.)

The previous report is read in a child process with a time limit (REF_TIMEOUT): on 2026-10-12 a malformed previous-year
PDF made PyMuPDF spin for hours inside the main AR run, holding the GIL, so the whole run (all readers) stood still from
~18:00 to 22:00. A reference that times out or fails gives no skip; the report is read in full.

  python -m reality_engine.scripts.ar_yoy <pdf>   (child mode: prints one shingle hash per line)
"""
import hashlib
import re
import subprocess
import sys
from functools import lru_cache

SHINGLE = 8
MIN_CONTAINMENT = 0.90
MIN_SHINGLES = 20
REF_TIMEOUT = 120
WORD = re.compile(r"[a-z0-9]+(?:[.,][0-9]+)*")


def _h(s):
    return int.from_bytes(hashlib.blake2b(s.encode("utf-8"), digest_size=8).digest(), "big")


def shingles(text):
    w = WORD.findall(text.lower())
    return {_h(" ".join(w[i:i + SHINGLE])) for i in range(len(w) - SHINGLE + 1)}


@lru_cache(maxsize=64)
def doc_shingles(path):
    """Shingle hashes of a whole PDF, computed in a child process; None when it fails or exceeds REF_TIMEOUT."""
    try:
        p = subprocess.run([sys.executable, "-m", "reality_engine.scripts.ar_yoy", path], capture_output=True, text=True,
                           timeout=REF_TIMEOUT, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return None
    if p.returncode != 0:
        return None
    return frozenset(int(x, 16) for x in p.stdout.split())


def previous_report(d, by_isin_fy):
    """The same company's report for the fiscal year before d's (dict from inventory), or None."""
    try:
        y = int(str(d["fiscal_year"])[:4])
    except (TypeError, ValueError):
        return None
    return by_isin_fy.get((d["isin"], y - 1))


def index_inventory(docs):
    idx = {}
    for d in docs:
        try:
            idx.setdefault((d["isin"], int(str(d["fiscal_year"])[:4])), d)
        except (TypeError, ValueError):
            pass
    return idx


def repeated_pages(pages, prev_path):
    """pages: [(page_no, text)]. Returns {page_no: containment} for pages that repeat the previous report."""
    ref = doc_shingles(prev_path)
    if not ref:
        return {}
    out = {}
    for n, t in pages:
        s = shingles(t)
        if len(s) < MIN_SHINGLES:
            continue
        c = len(s & ref) / len(s)
        if c >= MIN_CONTAINMENT:
            out[n] = round(c, 3)
    return out


if __name__ == "__main__":   # child: read one PDF, print its shingle hashes
    import pymupdf
    doc = pymupdf.open(sys.argv[1])
    hs = set()
    for page in doc:
        hs |= shingles(page.get_text())
    sys.stdout.write("\n".join(f"{h:x}" for h in hs))
