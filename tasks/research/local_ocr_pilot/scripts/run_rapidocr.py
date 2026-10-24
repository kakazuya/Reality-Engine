"""Arm 2 baseline: RapidOCR (the repo's processing/ocr_engine.py backend) on the rendered pages.

Uses the same RapidOCR v3 engine and DirectML switch as ocr_engine.py, but on the deck pipeline's 1600 px PNG and
without the engine's CLAHE preprocessing (the production page gate feeds the raw pixmap too). DirectML is ONNX Runtime's
GPU path on this box (no CUDA EP for RapidOCR); CPU is the fallback.

    python run_rapidocr.py --device dml|cpu [--limit N]

Output: work/ocr/rapidocr_<device>.jsonl (text, boxes, scores, seconds/page) + work/ocr/rapidocr_<device>/*.md
"""
import argparse
import json
import os
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "work"


def rows_from_boxes(result):
    """Reading order: group boxes whose vertical centres are within 10 px into one line, then sort by x."""
    txts = list(result.txts or ())
    boxes = result.boxes
    scores = list(result.scores or ())
    if boxes is None or len(boxes) != len(txts):
        return "\n".join(txts)
    items = []
    for t, b, s in zip(txts, boxes, scores):
        b = b.tolist() if hasattr(b, "tolist") else b
        xs = [p[0] for p in b]; ys = [p[1] for p in b]
        items.append((sum(ys) / 4, min(xs), t, float(s)))
    items.sort()
    lines, cur, cur_y = [], [], None
    for y, x, t, s in items:
        if cur_y is None or abs(y - cur_y) <= 10:
            cur.append((x, t)); cur_y = y if cur_y is None else (cur_y + y) / 2
        else:
            lines.append(" | ".join(t for _, t in sorted(cur)))
            cur, cur_y = [(x, t)], y
    if cur:
        lines.append(" | ".join(t for _, t in sorted(cur)))
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--device", choices=["dml", "cpu"], default="dml")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    from rapidocr import RapidOCR
    params = {"Global.log_level": "ERROR", "Global.max_side_len": 1600}
    if args.device == "dml":
        params["EngineConfig.onnxruntime.use_dml"] = True
    t0 = time.time()
    engine = RapidOCR(params=params)
    init_s = time.time() - t0
    pages = json.loads((WORK / "pages.json").read_text(encoding="utf-8"))
    if args.limit:
        pages = pages[:args.limit]
    out_dir = WORK / "ocr" / f"rapidocr_{args.device}"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_jsonl = WORK / "ocr" / f"rapidocr_{args.device}.jsonl"
    done = set()
    if out_jsonl.exists():
        for line in out_jsonl.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                done.add((r["sha256"], r["page_no"]))
    with out_jsonl.open("a", encoding="utf-8") as fh:
        for i, p in enumerate(pages):
            key = (p["sha256"], p["page_no"])
            if key in done:
                continue
            png = WORK / "pages" / f"{p['sha256']}_p{p['page_no']:03d}.png"
            t = time.time()
            try:
                res = engine(str(png))
                secs = time.time() - t
                text = rows_from_boxes(res) if res is not None else ""
                err = None
            except Exception as e:
                secs = time.time() - t
                text, err = "", f"{type(e).__name__}: {e}"
            rec = {"sha256": p["sha256"], "page_no": p["page_no"], "year": p["year"], "ptype": p["ptype"],
                   "seconds": round(secs, 3), "chars": len(text), "text": text, "error": err,
                   "device": args.device, "init_s": round(init_s, 2)}
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fh.flush()
            (out_dir / f"{p['sha256']}_p{p['page_no']:03d}.md").write_text(text, encoding="utf-8")
            if (i + 1) % 20 == 0:
                print(f"{i + 1}/{len(pages)} {secs:.2f}s last, {len(text)} chars", flush=True)
    print(f"done {len(pages)} pages, init {init_s:.2f}s -> {out_jsonl}")


if __name__ == "__main__":
    main()
