"""Step 2: year-over-year diff of annual-report prose (CPU only).

Paragraph = run of consecutive non-table lines on a page (table lines are handled by the column parser / XBRL).
Each paragraph gets novelty = share of its 8-word shingles (numbers masked) NOT found anywhere in the previous
year's report of the same company. novelty >= NEW_AT -> 'new', else 'repeated'.
Without a previous report every paragraph is 'new' (baseline year).
"""
import re
import pymupdf
from columns import lines_of, cells_of

K = 8
NEW_AT = 0.4


def words(t):
    return re.sub(r'[\d,.]+', '#', re.sub(r'[^\w\s.,]', ' ', t.lower())).split()


def shingles(ws):
    return {' '.join(ws[i:i + K]) for i in range(len(ws) - K + 1)}


def report_shingles(pdf):
    old = set()
    for pg in pymupdf.open(pdf):
        old |= shingles(words(pg.get_text()))
    return old


def paragraphs(pdf):
    """[(page, text)] of non-table text runs."""
    out = []
    for i, pg in enumerate(pymupdf.open(pdf)):
        buf = []
        for ln in lines_of(pg):
            if cells_of(ln):
                if buf: out.append((i + 1, ' '.join(buf))); buf = []
                continue
            buf.append(' '.join(w for *_, w in ln['words']))
        if buf: out.append((i + 1, ' '.join(buf)))
    return [(p, t) for p, t in out if len(t) >= 25]


def diff(pdf, prev_pdf=None):
    old = report_shingles(prev_pdf) if prev_pdf else None
    res = []
    for p, t in paragraphs(pdf):
        sh = shingles(words(t))
        if old is None or not sh:
            nov = 1.0 if old is None else (0.0 if len(t) < 60 else 1.0)
        else:
            nov = 1 - len(sh & old) / len(sh)
        res.append({'page': p, 'text': t, 'novelty': round(nov, 2), 'status': 'new' if nov >= NEW_AT else 'repeated',
                    'baseline': old is None})
    return res
