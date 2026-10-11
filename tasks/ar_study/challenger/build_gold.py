"""Build the gold fact set for the challenger study from the Haiku readers' output.

A gold fact = a number a Haiku reader cited with a page, that really appears on that page (+-1) of the PDF text.
Plus the hand-checked must-find list (headline signals), which carries a 'kind' (number or prose).
"""
import csv, glob, io, json, re, sys
sys.stdout.reconfigure(encoding='utf-8')
import pymupdf
SRC = {
  'COCHINSHIP': r'..\..\reality_engine\data\pdfs\COCHINSHIP\ANNUAL_REPORT\20260923_5bc78e44_e5b8816d-997a-45e5-b6c8-1e873dc3d26a.pdf',
  'CONCOR': r'..\..\reality_engine\data\pdfs\CONCOR\ANNUAL_REPORT\20260923_81d5e86c_fe7b8106-5fd4-42d6-b262-3efd67a04fb7.pdf',
  'GESHIP': r'src\GESHIP_FY24_AR.pdf',
}
NUM = re.compile(r'(?<![\w.])\(?-?\d{1,3}(?:,\d{2,3})*(?:\.\d+)?%?|\d+\.\d+%?')
PAGE = re.compile(r'\bpp?\.?\s*(\d{1,3})(?:\s*[-–]\s*(\d{1,3}))?', re.I)

def norm(n):
    return n.replace(',', '').replace('(', '').replace(')', '').replace('%', '').lstrip('-')

def interesting(n):
    v = norm(n)
    try: f = float(v)
    except ValueError: return False
    if '.' not in v and 1990 <= f <= 2035: return False      # years
    if '.' not in v and ',' not in n and not n.endswith('%'): return False  # bare ints: page refs, note numbers, counts
    return len(v.replace('.', '')) >= 3

def page_texts(pdf):
    d = pymupdf.open(pdf)
    return {i + 1: d[i].get_text() for i in range(len(d))}

def snippets():
    """(symbol, text, source) for every reader statement."""
    for sym in SRC:
        files = glob.glob(f'parts/{sym}_*.csv') + glob.glob(f'parts_v2/{sym}_*.csv')
        for f in files:
            t = open(f, encoding='utf-8').read()
            i = t.find('# NOTES')
            body, notes = (t, '') if i < 0 else (t[:i], t[i:])
            for r in csv.DictReader(io.StringIO(body.strip())):
                for col in ('items_to_extract', 'example_quote_or_page'):
                    yield sym, f"{r.get(col) or ''} [pages {r.get('pages') or ''}]", f
            for line in notes.splitlines():
                if line.strip(): yield sym, line, f

def main():
    texts = {s: page_texts(p) for s, p in SRC.items()}
    plain = {s: {p: norm_text(t) for p, t in tx.items()} for s, tx in texts.items()}
    gold = {}
    for sym, text, f in snippets():
        pages = set()
        for a, b in PAGE.findall(text):
            a = int(a); b = int(b) if b else a
            if 0 < a <= b < a + 15: pages.update(range(a, b + 1))
        if not pages: continue
        for n in NUM.findall(text):
            if not interesting(n): continue
            v = norm(n)
            rx = re.compile(r'(?<!\d)(?<!\d\.)' + re.escape(v) + r'(?![\d])')
            hit = [p for p in sorted(pages) for q in (p - 1, p, p + 1) if q in plain[sym] and rx.search(plain[sym][q])]
            if not hit: continue
            q = next(q for p in hit for q in (p, p - 1, p + 1) if q in plain[sym] and rx.search(plain[sym][q]))
            key = (sym, v, q)
            if key not in gold:
                gold[key] = {'symbol': sym, 'value': v, 'page': q, 'context': text.strip()[:220], 'kind': 'number', 'source': 'reader'}
    out = list(gold.values())
    json.dump(out, open('challenger/gold_numbers.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    from collections import Counter
    print('gold numbers', len(out), Counter(g['symbol'] for g in out))

def norm_text(t):
    return t.replace(',', '')

if __name__ == '__main__':
    main()
