"""Low-text pages (<200 chars in the text layer): how many figures does local OCR find there?"""
import sys, re
import pymupdf, numpy as np
from rapidocr import RapidOCR
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, '.')
from build_gold import SRC
import os; os.chdir('..')
eng = RapidOCR(); NUM = re.compile(r'\d[\d,]*\.\d+|\d{1,3}(?:,\d{2,3})+')
for sym, pdf in SRC.items():
    d = pymupdf.open(pdf); tot = 0; pages = []
    for i in range(len(d)):
        if len(d[i].get_text()) >= 200: continue
        pix = d[i].get_pixmap(dpi=150)
        img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, pix.n)[:, :, :3]
        r = eng(img); n = len(NUM.findall(' '.join(r.txts or [])))
        tot += n; pages.append((i + 1, n))
    print(sym, 'low-text pages', len(pages), 'figures found by OCR', tot, [p for p in pages if p[1]])
