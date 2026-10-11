"""Column-header parser for annual-report tables (CPU only, PyMuPDF word positions).

For each page:
  1. rebuild text lines from word boxes (same baseline = one line); re-join numbers split by kerning ("2 .78");
  2. find table blocks: runs of numeric lines, allowing short label/header lines in between; a prose line or a
     large vertical gap ends a block;
  3. find the block's value columns by clustering the right edges of numeric cells (figures are right-aligned);
  4. read column headers from the text lines just above the block and from header lines inside it, assigning each
     word to the column under it; a word sitting in the gap between two columns (a group header such as a JV name
     over its current/previous-year pair) goes to both;
  5. a block at the top of a page with no header of its own inherits the previous page's header when the column
     count matches (tables continued across pages);
  6. attach wrapped label lines to the nearest numeric line by vertical distance;
  7. map headers (or a period-like row label) to a fiscal-year end, and the block to a unit;
  8. emit one record per (row, value column): label, column header, period, unit, value, raw, note ref.
"""
import re
from statistics import median

NUM_TOKEN = re.compile(r'^\(?-?(\d{1,3}(,\d{2,3})+|\d+)(\.\d+)?\)?%?$')
DASH = re.compile(r'^[-–—]$')
YEAR = re.compile(r'^\(?(19|20)\d{2}\)?$')
UNIT_RX = re.compile(r'\b(?:in|In|IN)\s*(?:[^\w\s]{0,3}\s*)?(lakhs?|lacs?|crores?|cr\.?|million|mn|thousands?|billion)\b|'
                     r'\(\s*(?:[^\w()]{0,3}|rs\.?|inr|`|j|k|h)?\s*(?:in\s*)?(lakhs?|lacs?|crores?|cr|million|mn|thousands?)\.?\s*\)', re.I)
PERIOD_RX = [   # order matters: explicit ranges before bare "FY 2022"
    (re.compile(r'\b(20\d{2})\s*[-–/]\s*(\d{2,4})\b'), 'range'),
    (re.compile(r'(?:31|30)(?:st|th)?[\s./-]*(?:0?3|mar\w*)[\s./,-]*(20\d{2}|\d{2})\b', re.I), 'year'),
    (re.compile(r'(?:mar\w*)[\s.,-]*(?:31|30)(?:st|th)?[\s.,-]*(20\d{2})', re.I), 'year'),
    (re.compile(r"\b(?:fy|f\.y\.)\s*['’]?\s*(20\d{2}|\d{2})\b", re.I), 'year'),
    (re.compile(r'^\s*\(?(20\d{2})\)?\s*$'), 'year'),
]
CURRENT_RX = re.compile(r'current\s*(financial\s*)?(year|period)|this\s*year', re.I)
PREVIOUS_RX = re.compile(r'previous\s*(financial\s*)?(year|period)|prior\s*year|preceding\s*year|\bp\.?y\.?\b|last\s*year', re.I)
NOTE_RX = re.compile(r'^\s*(note|notes|note\s*no\.?|sch(edule)?|ref\.?)\s*$', re.I)


def is_num(w):
    return (bool(NUM_TOKEN.match(w)) and not YEAR.match(w)) or bool(DASH.match(w))


def to_float(raw):
    if DASH.match(raw): return None
    neg = raw.startswith('(') or raw.startswith('-')
    try: f = float(raw.strip('()%').replace(',', '').lstrip('-'))
    except ValueError: return None
    return -f if neg else f


def gutter(page):
    """x of a vertical gutter splitting a two-page spread, or None."""
    W = page.rect.width
    if W < page.rect.height * 1.2: return None
    words = page.get_text('words')
    if len(words) < 40: return None
    best = None
    for c in range(int(0.42 * W), int(0.58 * W), 4):
        cross = sum(1 for w in words if w[0] < c < w[2])
        left = sum(1 for w in words if w[2] <= c)
        if left < 0.15 * len(words) or len(words) - left - cross < 0.15 * len(words): continue
        if best is None or cross < best[0]: best = (cross, c)
    return best[1] if best and best[0] <= 0.01 * len(words) else None


def lines_of(page, clip=None):
    rows = {}
    for x0, y0, x1, y1, w, *_ in page.get_text('words', clip=clip):
        rows.setdefault(round((y0 + y1) / 2 / 2.5), []).append([x0, x1, w, (y0 + y1) / 2])
    out = []
    for key in sorted(rows):
        ws = sorted(rows[key])
        merged = []
        for w in ws:   # "2" ".78" -> "2.78";  "(" "157.86)" -> "(157.86)"
            if merged and w[0] - merged[-1][1] < 4 and ((w[2].startswith('.') and merged[-1][2][-1:].isdigit()) or merged[-1][2] in ('(', '-')):
                merged[-1][1], merged[-1][2] = w[1], merged[-1][2] + w[2]
            else:
                merged.append(list(w))
        out.append({'y': median(w[3] for w in merged), 'words': [(a, b, t) for a, b, t, _ in merged]})
    return out


def label_end(line):
    """Right edge of the last real word (2+ letters); numbers left of it belong to the label ("Less than 1 year")."""
    xs = [x1 for x0, x1, t in line['words'] if len(re.findall(r'[A-Za-z]', t)) >= 2]
    return max(xs) if xs else -1


def cells_of(line):
    end = label_end(line)
    return [(x0, x1, t) for x0, x1, t in line['words'] if is_num(t) and x0 > end]


def text_of(line):
    return ' '.join(t for *_, t in line['words'])


def is_prose(line, W):
    """A sentence line: no value cells at its right, wide and wordy. Long labels followed by figures stay table rows."""
    txt = ' '.join(t for x0, x1, t in line['words'] if not is_num(t))
    letters = len(re.findall(r'[A-Za-z]', txt))
    span = line['words'][-1][1] - line['words'][0][0]
    return letters > 220 or (not cells_of(line) and letters > 45 and span > 0.5 * W)


def cluster(edges, tol=12.0):
    cols = []
    for e in sorted(edges):
        if cols and e - cols[-1][-1] <= tol: cols[-1].append(e)
        else: cols.append([e])
    return [(min(c), max(c), len(c)) for c in cols]


def period_of(text, fy):
    t = (text or '').strip()
    if not t: return None
    p = _period(t, fy)
    return p if p else _period(t.replace(' ', ''), fy)


def _period(t, fy):
    for rx, kind in PERIOD_RX:
        m = rx.search(t)
        if not m: continue
        if kind == 'year':
            y = int(m.group(1)); return f'{y + 2000 if y < 100 else y}-03-31'
        a, b = int(m.group(1)), int(m.group(2)); b = b + 2000 if b < 100 else b
        if b == a + 1: return f'{b}-03-31'
    if re.search(r'mar', t, re.I):   # words out of order: "31, 2024 March"
        ys = set(re.findall(r'(20\d{2})', t))
        if len(ys) == 1: return f'{ys.pop()}-03-31'
    if PREVIOUS_RX.search(t): return f'{fy - 1}-03-31'
    if CURRENT_RX.search(t): return f'{fy}-03-31'
    return None


COUNT_LABEL = re.compile(r'\b(number of|no\. of|employees|workers|permanent|headcount|injur|fatalit|borrowers|complaints|meetings|shareholders|directors|trainings?|beneficiar|persons|male|female|men|women|nos\.?)\b', re.I)
RUPEE_ABS = re.compile(r'\((?:amount\s*)?in\s*(?:\u20b9|rs\.?|inr|`|\')\s*\)|amount\s*in\s*(?:\u20b9|rs\.?|inr)(?!\s*(?:lakh|crore|cr|million|mn|thousand))', re.I)


def unit_of(text):
    if text and RUPEE_ABS.search(text) and not UNIT_RX.search(text): return 'rupee'
    m = UNIT_RX.search(text or '')
    if not m: return None
    u = (m.group(1) or m.group(2)).lower()
    return ('lakh' if u.startswith(('lakh', 'lac')) else 'crore' if u.startswith('cr') else
            'million' if u.startswith(('million', 'mn')) else 'billion' if u.startswith('billion') else 'thousand')


def blocks_of(lines, W):
    gaps = [b['y'] - a['y'] for a, b in zip(lines, lines[1:])]
    lh = max(8.0, median(gaps)) if gaps else 12.0
    blocks, cur, last_num_y = [], [], None
    for i, ln in enumerate(lines):
        if is_prose(ln, W):
            if cur: blocks.append(cur); cur = []
            continue
        if cells_of(ln):
            if cur and last_num_y is not None and ln['y'] - last_num_y > 4.5 * lh:
                blocks.append(cur); cur = []
            cur.append(i); last_num_y = ln['y']
        elif cur:
            cur.append(i)      # label / header line inside a table
    if cur: blocks.append(cur)
    return [[i for i in b] for b in blocks if sum(1 for i in b if cells_of(lines[i])) >= 1]


def parse_page(page, fy, carry=None):
    """Returns (records, header_state for the next page). Two-page spreads are parsed half by half."""
    g = gutter(page)
    if g is None:
        return parse_area(page, fy, carry, None)
    import pymupdf
    r = page.rect
    left, carry = parse_area(page, fy, carry, pymupdf.Rect(r.x0, r.y0, g, r.y1))
    right, carry = parse_area(page, fy, carry, pymupdf.Rect(g, r.y0, r.x1, r.y1))
    for rec in left: rec['half'] = 'L'
    for rec in right: rec['half'] = 'R'
    return left + right, carry


def parse_area(page, fy, carry, clip):
    lines = lines_of(page, clip)
    if not lines: return [], carry
    W = (clip or page.rect).width
    H = page.rect.height
    page_unit = unit_of(' '.join(text_of(l) for l in lines[:14]))
    records, last_state = [], carry
    for bno, blk in enumerate(blocks_of(lines, W)):
        num_idx = [i for i in blk if cells_of(lines[i])]
        cols = [c for c in cluster([x1 for i in num_idx for x0, x1, t in cells_of(lines[i])]) if c[2] >= max(1, 0.2 * len(num_idx))]
        if not cols: continue
        widths = [x1 - x0 for i in num_idx for x0, x1, t in cells_of(lines[i])]
        wmax = max(widths) if widths else 30
        spans = [(lo - wmax - 4, hi + 4) for lo, hi, n in cols]
        label_edge = spans[0][0]
        # header lines: above the block (stop at prose, numbers that are not periods, or a big gap) + inside the block
        hdr = []
        j = blk[0] - 1
        while j >= 0 and len(hdr) < 12:
            ln = lines[j]
            if is_prose(ln, W) or lines[j + 1]['y'] - ln['y'] > 45: break
            if cells_of(ln): break
            hdr.insert(0, ln); j -= 1
        inside_hdr = [lines[i] for i in blk if not cells_of(lines[i]) and any((x0 + x1) / 2 > label_edge for x0, x1, _ in lines[i]['words'])]
        heads = [''] * len(cols)
        for ln in hdr + inside_hdr:
            # words close together form a phrase; a phrase spanning several columns ("As at 31 March") is a group
            # header and goes to every column it covers; a word in the gap between two columns goes to both
            phrases = []
            for x0, x1, t in ln['words']:
                if (x0 + x1) / 2 < label_edge - 2: continue
                if phrases and x0 - phrases[-1][1] < 6: phrases[-1] = (phrases[-1][0], x1, phrases[-1][2] + ' ' + t)
                else: phrases.append((x0, x1, t))
            for x0, x1, t in phrases:
                hit = [k for k, (a, b) in enumerate(spans) if x0 < b and x1 > a and min(x1, b) - max(x0, a) >= 0.3 * min(x1 - x0, b - a)]
                if not hit:
                    c = (x0 + x1) / 2
                    hit = [k for k in range(len(spans) - 1) if spans[k][1] < c < spans[k + 1][0]]
                    hit = [hit[0], hit[0] + 1] if hit else []
                for k in hit: heads[k] = (heads[k] + ' ' + t).strip()
        top_of_page = lines[blk[0]]['y'] < 0.2 * H
        if not any(heads) and top_of_page and carry and len(carry['heads']) == len(cols):
            heads, inherited = list(carry['heads']), True
        else:
            inherited = False
        context = ' '.join(text_of(l) for l in lines[max(0, blk[0] - 9):blk[0]])
        unit = unit_of(context) or unit_of(' '.join(heads)) or (carry or {}).get('unit') if inherited else (unit_of(context) or unit_of(' '.join(heads)) or page_unit)
        periods = [period_of(h, fy) for h in heads]
        if not any(periods) and len(cols) == 2:
            periods = [f'{fy}-03-31*', f'{fy - 1}-03-31*']     # Indian ARs print the current year first
        col_raws = [[t for i in num_idx for x0, x1, t in cells_of(lines[i]) if cols[k][0] - 3 <= x1 <= cols[k][1] + 3] for k in range(len(cols))]
        has_dec = [any(re.search(r'\.\d', t) for t in r) for r in col_raws]
        small_int = [bool(r) and all(re.fullmatch(r'\d{1,3}[A-Za-z]?|[-\u2013]', t) for t in r) for r in col_raws]
        note_col0 = [small_int[k] and any(has_dec[j] for j in range(len(cols)) if j != k) and k < len(cols) - 1 for k in range(len(cols))]
        note_col = [note_col0[k] or bool(NOTE_RX.match(h)) or all(re.fullmatch(r'\d{1,2}(\.\d)?|[-]', t) for i in num_idx for x0, x1, t in cells_of(lines[i])
                                                    if spans[k][0] <= (x0 + x1) / 2 <= spans[k][1]) for k, h in enumerate(heads)]
        # labels: own left text + wrapped label lines attached to the nearest numeric line
        labels = {i: ' '.join(t for x0, x1, t in lines[i]['words'] if x1 <= max(label_edge + 2, label_end(lines[i]) + 1) and (x0, x1, t) not in cells_of(lines[i])) for i in num_idx}
        for i in blk:
            if cells_of(lines[i]) or lines[i] in inside_hdr: continue
            frag = ' '.join(t for x0, x1, t in lines[i]['words'] if x1 <= label_edge + 2)
            if not frag: continue
            y = lines[i]['y']
            k = min(num_idx, key=lambda n: (abs(lines[n]['y'] - y), -lines[n]['y']))
            below = [n for n in num_idx if lines[n]['y'] > y]
            # a heading ("EQUITY AND LIABILITIES") or any fragment under a Total row starts the next row, never extends the total
            if lines[k]['y'] < y and below and (re.match(r'\s*total\b', labels[k], re.I) or (frag.isupper() and len(frag) > 6)):
                k = below[0]
            labels[k] = (frag + ' ' + labels[k]).strip() if lines[i]['y'] < lines[k]['y'] else (labels[k] + ' ' + frag).strip()
        value_cols = [k for k in range(len(cols)) if not note_col[k]]
        conf = round((sum(1 for k in value_cols if heads[k]) / max(1, len(value_cols))) * 0.4
                     + (sum(1 for k in value_cols if periods[k]) / max(1, len(value_cols))) * 0.3
                     + (sum(1 for i in num_idx if len(re.findall(r'[A-Za-z]', labels[i])) >= 4) / len(num_idx)) * 0.3, 2)
        col_unit = []
        for k, h in enumerate(heads):
            raws = [t for i in num_idx for x0, x1, t in cells_of(lines[i]) if cols[k][0] - 3 <= x1 <= cols[k][1] + 3]
            if '%' in h or (raws and sum(r.endswith('%') for r in raws) >= 0.5 * len(raws)): col_unit.append('%')
            elif re.search(r'holding|\bno\.?\s*of\b|number of|\bshares\b|\bnos\.?\b|\bcount\b|employees|workers|\bdin\b|\bmale\b|\bfemale\b', h, re.I): col_unit.append('count')
            elif re.search(r'\b(usd|us\$|\$\s*million|in\s*usd)\b', h + ' ' + context, re.I): col_unit.append('usd')
            else: col_unit.append(unit)
        for i in num_idx:
            row_period = period_of(labels[i], fy)
            note = None
            for x0, x1, t in cells_of(lines[i]):
                k = next((k for k, (a, b) in enumerate(spans) if cols[k][0] - 3 <= x1 <= cols[k][1] + 3), None)
                if k is None: continue
                if note_col[k]: note = t; continue
                records.append({'label': labels[i][:200], 'column': heads[k][:120], 'period': row_period or periods[k],
                                'unit': '%' if (t.endswith('%') or re.search(r'\(%\)|\bin %|%\s*$|\bratio\b|\bper cent\b|\bpercentage\b', labels[i], re.I)) else ('count' if COUNT_LABEL.search(labels[i] + ' ' + heads[k]) and col_unit[k] not in ('%',) else col_unit[k]), 'block': bno, 'row': i, 'col': k, 'value': to_float(t), 'raw': t, 'note': note, 'ncols': len(cols),
                                'inherited_header': inherited, 'confidence': conf, 'y': round(lines[i]['y'], 1)})
        last_state = {'heads': heads, 'unit': unit}
    return records, last_state
