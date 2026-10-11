"""Probe: pages where the text layer lost table figures. Does local OCR (RapidOCR, CPU here) recover them?"""
import sys, time, re
import pymupdf, numpy as np
from rapidocr import RapidOCR
sys.stdout.reconfigure(encoding='utf-8')
CASES = [('COCHINSHIP', r'..\..\..\reality_engine\data\pdfs\COCHINSHIP\ANNUAL_REPORT\20260923_5bc78e44_e5b8816d-997a-45e5-b6c8-1e873dc3d26a.pdf', 225),
         ('CONCOR', r'..\..\..\reality_engine\data\pdfs\CONCOR\ANNUAL_REPORT\20260923_81d5e86c_fe7b8106-5fd4-42d6-b262-3efd67a04fb7.pdf', 135)]
eng = RapidOCR()
NUM = re.compile(r'\d[\d,]*\.\d+')
for sym, pdf, pno in CASES:
    d = pymupdf.open(pdf); pg = d[pno - 1]
    tl = pg.get_text()
    pix = pg.get_pixmap(dpi=200)
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, pix.n)[:, :, :3]
    t0 = time.time(); r = eng(img); dt = time.time() - t0
    ocr = ' '.join(r.txts or [])
    a, b = set(NUM.findall(tl)), set(NUM.findall(ocr))
    print(f'{sym} p.{pno}: images on page {len(pg.get_images())}; text-layer decimals {len(a)}; OCR decimals {len(b)}; OCR-only {len(b - a)}; {dt:.1f}s')
    print('   OCR-only sample:', sorted(b - a)[:12])
