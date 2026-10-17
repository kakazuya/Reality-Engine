"""Free re-read of annual-report pages whose text layer is unusable (garbled OCR, scans, digit-encoding fonts).

RapidOCR (DirectML) reads each such page image; the boxes are put back into rows (a table row stays on one line) and that
text replaces the PDF text layer. A free reader (default LongCat on the OpenCode Go API, as in the main run) reads the OCR
pieces with the main run's prompt. Each number is checked against the PDF text layer ('page'), then the OCR text of its
page ('ocr'), then the OCR piece ('piece'); else not_found. Per report, over the re-read pages, the new facts replace the
older ones (any reader, Claude Haiku included) only when they verify better: a lower not_found share AND at least 80% as
many verified numbers, the rule of ar_queue.import_docs. Replaced rows move to ar_facts_replaced; losing answers are
stored as model '<reader>:rejected'. Built 2026-10-16 for the 111 'garbled' reports of ar_queue/hard_diagnosis.csv.

  python -m reality_engine.scripts.ar_ocr_reread --run o01 --doc-ids 80107 --dry      # decide, store nothing
  python -m reality_engine.scripts.ar_ocr_reread --run o01 --doc-ids 80107            # store (answers are cached)
  python -m reality_engine.scripts.ar_ocr_reread --run o02 --doc-ids garbled --workers 16

OCR text and reader answers are cached under reality_engine/data/ar_queue/ocr/ (ocr text per report; answers per run),
so a re-run only reads what is missing. Facts carry prompt_version '<reader pv>-ocr' and piece numbers from 20000
(ingest_annual_reports.main resumes by piece number alone; low numbers would hide its own unread pieces).
"""
import argparse
import collections
import concurrent.futures as cf
import csv
import json
import sys
import threading
import time
from datetime import datetime

from reality_engine.scripts import ar_queue as aq
from reality_engine.scripts import ingest_annual_reports as ar

OCR_DIR = aq.QUEUE / "ocr"
PIECE_BASE = 20000
PIECE_CHARS = 18000
OCR_SIDE = 2400           # longest side of the page image for OCR (table digits are small)
UNUSABLE = ("garbled", "encoded", "no_text")


def now():
    return datetime.now().isoformat(timespec="seconds")


_ENG = []
_ENG_LOCK = threading.Lock()


def engine():
    with _ENG_LOCK:
        if not _ENG:
            from rapidocr import RapidOCR
            _ENG.append(RapidOCR(params={"EngineConfig.onnxruntime.use_dml": True, "Global.log_level": "ERROR",
                                         "Global.max_side_len": OCR_SIDE}))
    return _ENG[0]


def ocr_boxes(page):
    """RapidOCR boxes of a PDF page: [[y_top, y_bottom, x_left, x_right, text], ...] in page-image pixels."""
    import pymupdf
    zoom = OCR_SIDE / max(page.rect.width, page.rect.height)
    jpeg = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False).tobytes("jpeg", jpg_quality=90)
    r = engine()(jpeg)
    if r is None or r.boxes is None or not len(r.txts or ()):
        return []
    return [[round(float(min(p[1] for p in box))), round(float(max(p[1] for p in box))),
             round(float(min(p[0] for p in box))), round(float(max(p[0] for p in box))), t] for box, t in zip(r.boxes, r.txts)]


def gutter(items):
    """x of the gap between two prose columns, or None. A table's column gaps do not count: both sides must hold
    wide boxes (lines of prose), and almost no box may cross the gap."""
    if len(items) < 12:
        return None
    left, right = min(i[2] for i in items), max(i[3] for i in items)
    w = right - left
    best = None
    for k in range(30, 71, 2):
        x = left + w * k / 100
        cross = sum(i[2] < x < i[3] for i in items)
        L = [i[3] - i[2] for i in items if i[3] <= x]; R = [i[3] - i[2] for i in items if i[2] >= x]
        if len(L) < 5 or len(R) < 5 or cross > 0.05 * len(items):
            continue
        if sorted(L)[len(L) // 2] > 0.25 * w and sorted(R)[len(R) // 2] > 0.25 * w:
            if best is None or cross < best[0]:
                best = (cross, x)
    return best[1] if best else None


def layout(items):
    """Boxes back into text: prose columns read one after the other; within a column, boxes regrouped into rows
    (left to right, cells split by 3 spaces) so a table row stays on one line."""
    if not items:
        return ""
    x = gutter(items)
    if x is not None:
        return layout_rows([i for i in items if i[2] < x and not i[2] < x < i[3]] + [i for i in items if i[2] < x < i[3]]) \
            + "\n" + layout_rows([i for i in items if i[2] >= x])
    return layout_rows(items)


def layout_rows(items):
    if not items:
        return ""
    h = sorted(b - a for a, b, *_ in items)[len(items) // 2] or 1
    rows, cur, cy = [], [], None
    for a, b, x0, _, t in sorted(items, key=lambda i: (i[0] + i[1]) / 2):
        y = (a + b) / 2
        if cur and abs(y - cy) > 0.5 * h:
            rows.append(cur); cur = []
        if not cur:
            cy = y
        cur.append((x0, t))
    if cur:
        rows.append(cur)
    return "\n".join("   ".join(t for _, t in sorted(row)) for row in rows)


def ocr_doc(doc_id, path, pages_wanted):
    """{page: OCR text} for the wanted pages; the boxes are cached in ocr/<doc_id>.boxes.json."""
    f = OCR_DIR / f"{doc_id}.boxes.json"
    cache = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    todo = [n for n in pages_wanted if str(n) not in cache]
    if todo:
        import pymupdf
        pdf = pymupdf.open(path)
        try:
            for n in todo:
                try:
                    cache[str(n)] = ocr_boxes(pdf[n - 1])
                except Exception as e:
                    print(f"  {doc_id} p{n}: OCR failed {e}", flush=True); cache[str(n)] = []
        finally:
            pdf.close()
        OCR_DIR.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    return {n: layout(cache[str(n)]) for n in pages_wanted}


def doc_ids(con, spec):
    if spec == "garbled":
        with open(aq.QUEUE / "hard_diagnosis.csv", encoding="utf-8") as f:
            return [int(r["doc_id"]) for r in csv.DictReader(f) if r["cause"] == "garbled"]
    return aq.doc_ids_arg(con, spec)


def pieces_of(ocr):
    out, buf, first, last = [], "", None, None
    for n in sorted(ocr):
        if len(ocr[n].strip()) < 40:
            continue
        block = f"=== PAGE {n} ===\n{ocr[n]}\n"[:PIECE_CHARS]
        if buf and len(buf) + len(block) > PIECE_CHARS:
            out.append((first, last, buf)); buf, first = "", None
        if first is None:
            first = n
        buf += block; last = n
    if buf:
        out.append((first, last, buf))
    return out


class Pool:
    """Round-robin over the chosen model's readers, with retries; answers cached on disk."""

    def __init__(self, model, workers):
        rs = [r for r in ar.readers(ar.user_env()) if r["model"] == model]
        if not rs:
            sys.exit(f"no reader for {model}")
        import requests
        self.rs, self.http, self.i, self.lock = rs, requests.Session(), 0, threading.Lock()
        self.ex = cf.ThreadPoolExecutor(workers)

    def reader(self):
        with self.lock:
            self.i += 1
            return self.rs[self.i % len(self.rs)]

    def read(self, prompt, cache_f):
        if cache_f.exists():
            return json.loads(cache_f.read_text(encoding="utf-8"))
        err = None
        for attempt in range(4):
            r = self.reader(); t = time.time()
            try:
                res = ar.call(r, prompt, self.http)
                text, it, ot = res[:3]
                name = res[3]["name"] if len(res) > 3 else r["name"]
                if not ar.parse_lines(text) and not text.strip().upper().startswith("NONE"):
                    raise RuntimeError("no JSON lines in answer")
                out = {"name": name, "pv": r["pv"], "text": text, "in": it, "out": ot, "sec": round(time.time() - t, 1)}
                cache_f.parent.mkdir(parents=True, exist_ok=True)
                cache_f.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
                return out
            except Exception as e:
                err = str(e)[:200]
                time.sleep(30 * (attempt + 1))
        return {"error": err}


def decide(con, d, units, answers, pages, ocr, dry, run):
    """Check, compare with the older facts on the same pages, and store. Returns the report line."""
    doc_id = d["doc_id"]
    rows, pieces = [], []
    pv_new = None
    for (k, a, b, text), ans in zip(units, answers):
        if "error" in ans:
            return f"{doc_id} {d['symbol']}: piece {k} failed ({ans['error'][:80]}), not decided"
        pv_new = ans["pv"] + "-ocr"
        model = ans["name"].replace("@", "@ocr-", 1) if "@" in ans["name"] else ans["name"] + "@ocr"
        facts = ar.parse_lines(ans["text"])
        for f in facts:
            pg = int(f["page"]) if str(f.get("page", "")).isdigit() else None
            v = f.get("value")
            chk = ar.value_check(v, pages.get(pg), "")
            if chk == "not_found":
                c2 = ar.value_check(v, ocr.get(pg), text)
                chk = {"page": "ocr", "piece": "piece"}.get(c2, c2)
            rows.append((doc_id, PIECE_BASE + k, d["isin"], d["symbol"], d["fiscal_year"], d["filed_at"], pg,
                         str(f.get("category") or "")[:80], str(f.get("item") or "")[:500],
                         None if v is None else str(v)[:60], ar.to_number(v), str(f.get("unit") or "")[:40],
                         str(f.get("period") or "")[:40], str(f.get("basis") or "")[:20], str(f.get("quote") or "")[:300],
                         model, chk, pv_new))
        pieces.append([doc_id, PIECE_BASE + k, None, a, b, len(text), model, ans.get("sec"), ans.get("in"),
                       ans.get("out"), len(facts), "ok", None, ans["text"], now()])
    for p in pieces:
        p[2] = pv_new
    covered = sorted({n for _, a, b, _ in units for n in range(a, b + 1) if n in ocr and len(ocr[n].strip()) >= 40})
    q = (f"FROM ar_facts WHERE doc_id=? AND prompt_version NOT LIKE '%-ocr' AND model NOT LIKE '%:rejected' "
         f"AND page IN ({','.join('?' * len(covered))})")
    old = collections.Counter(dict(con.execute(f"SELECT value_check, COUNT(*) {q} AND value IS NOT NULL GROUP BY 1",
                                               (doc_id, *covered)).fetchall()))
    old_models = collections.Counter(dict(con.execute(f"SELECT model, COUNT(*) {q} GROUP BY 1", (doc_id, *covered)).fetchall()))
    new = collections.Counter(r[16] for r in rows if r[10] is not None)
    o_n, n_n = sum(old.values()), sum(new.values())
    o_v, n_v = old["page"] + old["piece"] + old["ocr"], new["page"] + new["piece"] + new["ocr"]
    o_s, n_s = old["not_found"] / max(1, o_n), new["not_found"] / max(1, n_n)
    # 2026-10-17: pages with no old numbers (whole scanned reports) never passed 'n_s < o_s' (0% vs 0%): take the OCR read
    better = n_n > 0 and ((o_n == 0 and n_v > 0) or (n_s < o_s and n_v >= 0.8 * o_v))
    line = (f"{doc_id} {d['symbol']} FY {d['fiscal_year'][:4]} pages {len(covered)}: old {o_n} numbers, not_found "
            f"{100 * o_s:.0f}%, verified {o_v} ({', '.join(f'{m}:{c}' for m, c in old_models.most_common(2))}) | ocr-read "
            f"{n_n} numbers, not_found {100 * n_s:.0f}%, verified {n_v} ({dict(new)}) -> {'REPLACE' if better else 'keep old'}")
    if dry:
        return line
    con.execute("CREATE TABLE IF NOT EXISTS ar_facts_replaced AS SELECT *, '' AS replaced_by, '' AS replaced_ts FROM ar_facts WHERE 0")
    con.execute("DELETE FROM ar_facts WHERE doc_id=? AND prompt_version=?", (doc_id, pv_new))
    con.execute("DELETE FROM ar_pieces WHERE doc_id=? AND prompt_version=?", (doc_id, pv_new))
    con.executemany("INSERT INTO ar_pieces VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", [tuple(p) for p in pieces])
    if better:
        con.execute(f"INSERT INTO ar_facts_replaced SELECT *, ?, ? {q}", (f"{run}:ocr", now(), doc_id, *covered))
        con.execute(f"DELETE {q}", (doc_id, *covered))
        con.executemany("INSERT INTO ar_facts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    else:
        con.executemany("INSERT INTO ar_facts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        [r[:15] + (r[15] + ":rejected",) + r[16:] for r in rows])
    con.commit()
    return line


def main(run, spec, model, workers, dry, kinds, limit):
    con = aq.connect()
    run_dir = OCR_DIR / "runs" / run
    run_dir.mkdir(parents=True, exist_ok=True)
    pool = Pool(model, workers)
    ids = doc_ids(con, spec)[:limit or None]
    pending, report = [], []
    out_f = run_dir / ("DECISIONS_DRY.md" if dry else "DECISIONS.md")

    def finish(block=False):
        for item in list(pending):
            d, units, futs, pages, ocr = item
            if not block and not all(f.done() for f in futs):
                continue
            pending.remove(item)
            line = decide(con, d, units, [f.result() for f in futs], pages, ocr, dry, run)
            report.append(line); print(line, flush=True)
            out_f.write_text("\n".join(report) + "\n", encoding="utf-8")

    t0 = time.time()
    for i, doc_id in enumerate(ids, 1):
        r = con.execute("SELECT doc_id, isin, symbol, company, fiscal_year, filed_at, path FROM ar_docs WHERE doc_id=?",
                        (doc_id,)).fetchone()
        if not r:
            print(f"{doc_id}: not in ar_docs"); continue
        d = dict(zip(("doc_id", "isin", "symbol", "company", "fiscal_year", "filed_at", "path"), r))
        try:
            pages = aq.page_texts(d["path"])
        except Exception as e:
            print(f"{doc_id}: {e}"); continue
        skipped = {x[0] for x in con.execute("SELECT page FROM ar_skipped_pages WHERE doc_id=?", (doc_id,))}
        want = [n for n, t in sorted(pages.items()) if n not in skipped and aq.page_kind(t) in kinds]
        if not want:
            print(f"{doc_id} {d['symbol']}: no unusable pages"); continue
        ocr = ocr_doc(doc_id, d["path"], want)
        units = [(k, a, b, text) for k, (a, b, text) in enumerate(pieces_of(ocr))]
        futs = []
        for k, a, b, text in units:
            prompt = pool.rs[0]["tmpl"].format(company=d["company"], symbol=d["symbol"], filed=str(d["filed_at"])[:10],
                                               text=text)
            futs.append(pool.ex.submit(pool.read, prompt, run_dir / str(doc_id) / f"{k:03d}.json"))
        pending.append((d, units, futs, pages, ocr))
        print(f"[{i}/{len(ids)} {time.time() - t0:.0f}s] {doc_id} {d['symbol']} FY {d['fiscal_year'][:4]}: OCR {len(want)} "
              f"pages -> {len(units)} pieces queued", flush=True)
        finish()
    finish(block=True)
    print(f"done: {len(report)} reports -> {out_f}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--doc-ids", default="garbled", help="'garbled' (hard_diagnosis.csv), 'hard', or a comma list")
    ap.add_argument("--model", default="longcat-2.5-preview-free", help="reader model id (from reader_profiles.json)")
    ap.add_argument("--workers", type=int, default=8, help="pieces read at once")
    ap.add_argument("--kinds", default=",".join(UNUSABLE), help="page kinds to OCR (ar_queue.page_kind)")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dry", action="store_true", help="decide only; store nothing")
    a = ap.parse_args()
    main(a.run, a.doc_ids, a.model, a.workers, a.dry, tuple(a.kinds.split(",")), a.limit)
