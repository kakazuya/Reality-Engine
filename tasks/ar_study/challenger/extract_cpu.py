"""Challenger: rule-only (CPU) annual-report extraction, no LLM.

Per report it:
  1. classifies every page into a section family by heading rules;
  2. drops boilerplate families outright;
  3. keeps statutory signal blocks whole (auditor KAM / EoM / modifications, C&AG comments, CARO, secretarial
     observations) plus lines hit by a fixed red-flag lexicon (with a few lines of context);
  4. turns tabular pages into (label, values) rows: PyMuPDF table finder first, then a text-layer fallback that
     pairs a label line with the numeric lines that follow it;
  5. tags each page with unit (lakh / crore / million) and scope (standalone / consolidated).

Output: challenger/out/<SYMBOL>.json
"""
import json, re, sys, time
from pathlib import Path
import pymupdf
from columns import parse_page as parse_columns

sys.stdout.reconfigure(encoding='utf-8')
HERE = Path(__file__).parent
OUT = HERE / 'out'

SECTION_RULES = [  # first match in the page top wins; order matters
    ('cag', r'comments? of the comptroller (and|&) auditor general'),
    ('caro', r"companies \(auditor'?s report\) order|annexure\W+\w?\W*to the independent auditor"),
    ('auditor', r"independent auditor'?s report"),
    ('secretarial', r'secretarial audit report|form no\.? ?mr-?3'),
    ('brsr', r'business responsibility (and|&) sustainability'),
    ('csr', r'annual report on (the )?csr|report on csr activities'),
    ('aoc1', r'form\s*(no\.?)?\s*aoc\s*-?\s*1'),
    ('aoc2', r'form\s*(no\.?)?\s*aoc\s*-?\s*2'),
    ('cg', r'corporate governance report|report on corporate governance'),
    ('mda', r'management discussion'),
    ('agm', r'notice is hereby given|agm notice|notice of (the )?\d+\w* annual general meeting'),
    ('fs_statement', r'^\s*(standalone |consolidated )?(balance sheet as at|statement of profit (and|&) loss for|statement of cash flows? for|cash flow statement for|statement of changes in equity)'),
    ('notes', r'notes (to|forming part of) (the )?(standalone |consolidated )?financial statements|^\s*note\s*\d+\s*:'),
    ('directors', r"(directors'?|board'?s) report"),
]
SECTION_RX = [(n, re.compile(p, re.I | re.M)) for n, p in SECTION_RULES]
DROP = {'agm', 'cg_proc'}          # agm notice: dropped (special resolutions caught by lexicon would need agm kept; see notes)
TABLE_FAMILIES = {'notes', 'fs_statement', 'brsr', 'csr', 'aoc1', 'aoc2', 'cg', 'caro', 'directors', 'mda', 'overview'}
KEEP_WHOLE = {'cag', 'caro'}
AUDIT_TRIGGERS = re.compile(r'key audit matter|emphasis of matter|qualified opinion|basis for (qualified|adverse)|adverse opinion|'
                            r'disclaimer of opinion|material uncertainty|going concern|other matters?\b|audit trail|edit log|unable to comment', re.I)
SECRETARIAL_TRIGGERS = re.compile(r'subject to the following|observation|non-?complian|penalt|fine[sd]?\b|show cause|delay', re.I)
# Frozen generic red-flag / change lexicon (written once, not tuned per company).
LEXICON = re.compile(
    r'\bdelay(ed|s)?\b|liquidated damages|arbitrat|\bdisput|litigation|show cause|penalt|fraud|whistle.?blow|resign|going concern|'
    r'\bdefault(ed|s)?\b|overdue|restructur|written off|write.?off|impair|disallow|under protest|not acknowledged as debt|'
    r'revers(al|ed)|cancel(l)?(ed|ation)|terminat|suspend|new regulation|amendment to|emission trading|\bets\b|\beuas?\b|carbon (tax|price|credit)|'
    r'sanction|embargo|credit rating|upgrade|downgrade|pledge|material uncertainty|subsequent event|after the (balance sheet|reporting) date|'
    r'not (been )?(recogni[sz]ed|provided)|unspent|deficien|qualification', re.I)
# Banks / NBFCs: default, overdue, restructuring, impairment, write-off, NPA and rating language are routine
# vocabulary there, so their word list keeps only the strong signals.
LEXICON_FIN = re.compile(
    r'liquidated damages|arbitrat|show cause|penalt|fraud|whistle.?blow|resign|going concern|under protest|'
    r'not acknowledged as debt|new regulation|embargo|sanction(ed)? by (rbi|sebi)|divergence|material uncertainty|'
    r'subsequent event|after the (balance sheet|reporting) date|not (been )?(recogni[sz]ed|provided)|deficien|qualification|'
    r'supervisory|monetary penalty|regulatory action|restriction', re.I)
UNIT_RX = re.compile(r'\bin\s*(lakhs?|lacs?|crores?|million|mn|thousands?)\b|\((?:[^)]{0,6})?(lakhs?|lacs?|crores?|cr|million)\.?\)', re.I)
NUMLINE = re.compile(r'^\s*\(?-?[\d,]+(\.\d+)?\)?\s*%?\s*$')
CONTEXT = 3


def clean(t):
    return re.sub('[�’‘`]', "'", t)


def unit_of(text):
    m = UNIT_RX.search(text[:1500])
    if not m: return None
    u = (m.group(1) or m.group(2)).lower()
    return 'lakh' if u.startswith(('lakh', 'lac')) else 'crore' if u.startswith('crore') else 'million' if u.startswith(('million', 'mn')) else 'thousand'


def classify(pages):
    fam, cur = [], 'overview'
    for t in pages:
        top = t[:700] + '\n' + t[-300:]
        for name, rx in SECTION_RX:
            if rx.search(top):
                cur = name
                break
        fam.append(cur)
    return fam


def label_rows_from_text(text):
    """Fallback table reader: a label line followed by 1+ numeric lines."""
    rows, label, nums = [], None, []
    for line in (l.strip() for l in text.splitlines()):
        if not line: continue
        if NUMLINE.match(line):
            nums.append(line)
            continue
        if label and nums: rows.append({'label': label, 'values': nums})
        label, nums = line, []
    if label and nums: rows.append({'label': label, 'values': nums})
    return rows


RATING_RX = re.compile(r'\b(CRISIL|ICRA|CARE|IND|India Ratings|BWR|Brickwork|Acuite|ACUITE|Infomerics)\b[\s:]*'
                       r'((?:PP-MLD\s*)?(?:AAA|AA\+|AA-|AA|A1\+|A1|A2\+|A2|A\+|A-|BBB\+|BBB-|BBB|BB\+|BB)(?![\w+-])(?:\s*\((?:CE|SO)\))?)'
                       r'(?:\s*[;/(:]\s*(Stable|Positive|Negative|Developing|Watch[^)\n]*))?')


def rating_rows(text):
    return [{'label': f'credit rating {m.group(1)}', 'values': [m.group(2)], 'outlook': m.group(3), 'via': 'rating-rule'}
            for m in RATING_RX.finditer(text)]


def word_rows(page):
    """Layout fallback: rebuild table rows from word positions (same baseline), label = text left of the numbers."""
    rows, lines = [], {}
    for x0, y0, x1, y1, w, *_ in page.get_text('words'):
        key = round((y0 + y1) / 2 / 3)
        lines.setdefault(key, []).append((x0, w))
    for key in sorted(lines):
        ws = sorted(lines[key])
        vals = [w for _, w in ws if NUMLINE.match(w)]
        lab = ' '.join(w for _, w in ws if not NUMLINE.match(w))
        if vals and len(re.findall(r'[A-Za-z]', lab)) >= 4:
            rows.append({'label': lab[:200], 'values': vals, 'via': 'layout'})
    return rows


def table_rows(page):
    rows = []
    try:
        for tb in page.find_tables().tables:
            for r in tb.extract():
                cells = [(c or '').replace('\n', ' ').strip() for c in r]
                vals = [c for c in cells if c and NUMLINE.match(c)]
                labs = [c for c in cells if c and not NUMLINE.match(c)]
                if vals: rows.append({'label': ' | '.join(labs)[:200], 'values': vals, 'via': 'table'})
    except Exception as e:
        rows.append({'error': str(e)})
    return rows


def run(symbol, pdf, fy=2024, sector=None):
    lex = LEXICON_FIN if sector == 'Financial Services' else LEXICON
    t0 = time.time()
    doc = pymupdf.open(pdf)
    pages = [clean(doc[i].get_text()) for i in range(len(doc))]
    fams = classify(pages)
    unit, out = None, {'symbol': symbol, 'pdf': str(pdf), 'fy': fy, 'pages': []}
    carry = None
    for i, (t, fam) in enumerate(zip(pages, fams)):
        pno = i + 1
        unit = unit_of(t) or unit
        scope = 'consolidated' if re.search(r'consolidated', t[:400], re.I) else 'standalone'
        rec = {'page': pno, 'family': fam, 'unit': unit, 'scope': scope, 'chars': len(t), 'kept': [], 'rows': []}
        if fam in DROP:
            rec['dropped'] = True
            out['pages'].append(rec); continue
        lines = t.splitlines()
        if fam in KEEP_WHOLE:
            rec['kept'].append({'why': fam, 'text': t})
        elif fam == 'auditor':
            rec['kept'].append({'why': 'auditor', 'text': t})
        elif fam == 'secretarial' and SECRETARIAL_TRIGGERS.search(t):
            rec['kept'].append({'why': 'secretarial-trigger', 'text': t})
        else:
            hit = set()
            for j, l in enumerate(lines):
                if lex.search(l) or AUDIT_TRIGGERS.search(l): hit.update(range(max(0, j - CONTEXT), min(len(lines), j + CONTEXT + 1)))
            if hit:
                rec['kept'].append({'why': 'lexicon', 'text': '\n'.join(lines[j] for j in sorted(hit))})
        if True:   # tables on every non-dropped page; section tags only steer kept text
            recs, carry = parse_columns(doc[i], fy, carry)
            rows = [{'label': r['label'], 'values': [r['raw']], 'value': r['value'], 'column': r['column'], 'period': r['period'],
                     'unit': r['unit'] or (None if r['raw'].endswith('%') else unit), 'note': r['note'], 'ncols': r['ncols'], 'block': f"{r.get('half', '')}{r['block']}", 'row': r['row'], 'col': r['col'], 'confidence': r['confidence'], 'via': 'columns'} for r in recs]
            have = {r['values'][0] for r in rows}
            rows += [dict(r, via='text') for r in label_rows_from_text(t) if not set(r['values']) <= have]
            rec['rows'] = rows
        rec['rows'] += rating_rows(t)
        out['pages'].append(rec)
    out['seconds'] = round(time.time() - t0, 1)
    OUT.mkdir(exist_ok=True)
    (OUT / f'{symbol}.json').write_text(json.dumps(out, ensure_ascii=False), encoding='utf-8')
    return out


if __name__ == '__main__':
    sys.path.insert(0, str(HERE))
    from build_gold import SRC
    import os
    os.chdir(HERE.parent)
    for s, p in SRC.items():
        o = run(s, p)
        n_rows = sum(len(pg['rows']) for pg in o['pages'])
        kept = sum(len(k['text']) for pg in o['pages'] for k in pg['kept'])
        total = sum(pg['chars'] for pg in o['pages'])
        print(f"{s}: {len(o['pages'])} pages, {o['seconds']}s, rows {n_rows}, kept text {kept/total:.1%} of {total:,} chars")
