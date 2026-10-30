"""OCR accuracy check for the QNN NPU path: scanned pages and text-layer ground truth.

The NPU/CPU agreement number (0.971) does not prove accuracy: the numpy
post-processing can produce garbled text that both devices agree on.  This
check measures the NPU output against the PDF's own text layer, which is truth
for those pages.

    python -m reality_engine.scripts.hp_ocr_check --mode textlayer \
        --text-dir C:\\RE\\ocr_text --models C:\\RE\\models_fixed \
        --provider qnn-htp --out C:\\RE\\ocr_check

    python -m reality_engine.scripts.hp_ocr_check --mode scanned \
        --list C:\\RE\\pages30.txt --base C:\\RE\\raw\\pilot60_history \
        --models C:\\RE\\models_fixed --provider qnn-htp --out C:\\RE\\ocr_check

``--rec-width clip`` reproduces the old fixed-320 clipping so the same 20 pages
can be compared against the fixed path.  ``--rec-width auto`` reads the rec
model's own fixed width (the QNN graphs are shape-locked).

Output: ``rows.jsonl`` (one row per page) plus a printed summary.  Accuracy is
1 - edit_distance(truth, ocr) / len(truth), on whitespace-normalised text.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

import numpy as np
from PIL import Image

MEAN = np.array([0.485, 0.456, 0.406], np.float32)
STD = np.array([0.229, 0.224, 0.225], np.float32)
DET_SIZE = 960
REC_H = 48
MIN_TRUTH_CHARS = 200
_QNN_REGISTERED = False


def open_session(path: str, provider: str, threads: int = 8):
    import onnxruntime as ort

    options = ort.SessionOptions()
    options.intra_op_num_threads = threads
    options.log_severity_level = 3
    if provider.startswith("qnn"):
        global _QNN_REGISTERED
        import onnxruntime_qnn as qnn

        here = os.path.dirname(str(qnn.__file__))
        if not _QNN_REGISTERED:
            os.add_dll_directory(here)
            ort.register_execution_provider_library("qnn", qnn.get_library_path())
            _QNN_REGISTERED = True
        backend = os.path.join(here, "QnnHtp.dll" if provider == "qnn-htp" else "QnnGpu.dll")
        options.add_session_config_entry("session.disable_cpu_ep_fallback", "1")
        return ort.InferenceSession(path, options, providers=["qnn"],
                                    provider_options=[{"backend_path": backend}])
    return ort.InferenceSession(path, options, providers=["CPUExecutionProvider"])


def render(pdf: Path, page_index: int, scale: float = 3.0):
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(str(pdf))
    number = len(doc)
    index = number // 2 if page_index < 0 else max(0, min(page_index, number - 1))
    image = doc[index].render(scale=scale).to_pil().convert("RGB")
    doc.close()
    return image, index


def best_text_page(pdf: Path, scale: float = 3.0):
    """The page with the most text-layer characters (a clean page to compare on)."""
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(str(pdf))
    best = (-1, "")
    for i in range(len(doc)):
        text = doc[i].get_textpage().get_text_range()
        if len(text) > best[0]:
            best = (len(text), i)
    index = best[1]
    image = doc[index].render(scale=scale).to_pil().convert("RGB")
    text = doc[index].get_textpage().get_text_range()
    doc.close()
    return image, index, text


def det_prep(image: Image.Image):
    width, height = image.size
    scale = DET_SIZE / max(width, height)
    new = (max(1, int(round(width * scale))), max(1, int(round(height * scale))))
    canvas = Image.new("RGB", (DET_SIZE, DET_SIZE), (255, 255, 255))
    canvas.paste(image.resize(new, Image.Resampling.BILINEAR), (0, 0))
    array = np.asarray(canvas, np.float32) / 255.0
    return ((array - MEAN) / STD).transpose(2, 0, 1)[None], scale


def components(mask: np.ndarray):
    """Connected components of an HxW bool mask as (x0, y0, x1, y1) boxes."""
    parent: list[int] = []
    runs: list[tuple[int, int, int, int]] = []

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    previous: list[tuple[int, int, int]] = []
    for y in range(mask.shape[0]):
        indices = np.flatnonzero(mask[y])
        if indices.size == 0:
            previous = []
            continue
        diffs = np.diff(indices)
        starts = np.r_[indices[0], indices[1:][diffs > 1]]
        ends = np.r_[indices[:-1][diffs > 1], indices[-1]]
        current = []
        j = 0
        for start, end in zip(starts.tolist(), ends.tolist()):
            rid = len(parent)
            parent.append(rid)
            runs.append((start, end, y, rid))
            while j < len(previous) and previous[j][1] < start:
                j += 1
            k = j
            while k < len(previous) and previous[k][0] <= end:
                union(rid, previous[k][2])
                k += 1
            current.append((start, end, rid))
        previous = current

    boxes: dict[int, list[int]] = {}
    for start, end, y, rid in runs:
        root = find(rid)
        box = boxes.get(root)
        if box is None:
            boxes[root] = [start, y, end, y]
        else:
            box[0] = min(box[0], start)
            box[1] = min(box[1], y)
            box[2] = max(box[2], end)
            box[3] = max(box[3], y)
    return [tuple(b) for b in boxes.values()]


def row_bands(sub: np.ndarray, min_height: int = 5, min_gap: int = 2):
    """Split one component's mask into text-line bands by low-density rows.

    The numpy replacement for the DB post-processing found connected components
    of the whole probability map; on a dense page several text lines merge into
    one component, and one recognition pass over that block loses most of the
    text.  A component is therefore cut into lines at rows where almost nothing
    is foreground (two consecutive rows, so a gap inside a glyph never cuts).
    """
    if sub.size == 0:
        return []
    rows = sub.sum(axis=1)
    valley = rows <= max(1, int(0.06 * sub.shape[1]))
    bands, start, run = [], None, 0
    for y, empty in enumerate(valley.tolist()):
        if empty:
            run += 1
            if start is not None and run >= min_gap:
                if y - run - start + 1 >= min_height:
                    bands.append((start, y - run))
                start = None
            continue
        run = 0
        if start is None:
            start = y
    if start is not None and len(rows) - start >= min_height:
        bands.append((start, len(rows) - 1))
    return bands


def det_post(prob: np.ndarray, scale: float, thresh: float = 0.3, expand: float = 1.4,
             split_lines: bool = True):
    mask = prob > thresh
    out = []
    for x0, y0, x1, y1 in components(mask):
        if x1 - x0 + 1 < 4 or y1 - y0 + 1 < 4:
            continue
        sub = mask[y0:y1 + 1, x0:x1 + 1]
        bands = row_bands(sub) if split_lines else [(0, y1 - y0)]
        for start, end in bands:
            cols = np.flatnonzero(sub[start:end + 1].any(axis=0))
            if cols.size == 0:
                continue
            bx0, bx1 = x0 + int(cols[0]), x0 + int(cols[-1])
            by0, by1 = y0 + start, y0 + end
            cx, cy = (bx0 + bx1) / 2, (by0 + by1) / 2
            half_w = (bx1 - bx0 + 1) * expand / 2
            half_h = (by1 - by0 + 1) * expand / 2
            out.append((max(0.0, cx - half_w) / scale, max(0.0, cy - half_h) / scale,
                        (cx + half_w) / scale, (cy + half_h) / scale))
    out.sort(key=lambda b: (round(b[1] / 8), b[0]))
    return out


def line_chunks(box, image: Image.Image, rec_w: int):
    """Split a wide line into rec-sized pieces instead of squashing it.

    The rec graph is shape-locked (48 x rec_w), while a full-width line on an A4
    page is ~50x taller than wide.  Squeezing that into 960 px distorts glyphs
    past recognition (and the old path silently clipped it).  Each chunk keeps a
    natural aspect ratio; a chunk boundary lands on the emptiest column nearby
    so words are cut at spaces where possible.
    """
    x0, y0, x1, y1 = [int(v) for v in box]
    x0, y0 = max(0, x0), max(0, y0)
    x1 = min(image.width, max(x0 + 2, x1))
    y1 = min(image.height, max(y0 + 2, y1))
    height = max(1, y1 - y0)
    ratio = (x1 - x0) * REC_H / height
    count = max(1, int(np.ceil(ratio / rec_w)))
    if count == 1:
        return [((x0, y0, x1, y1), True)]
    step = (x1 - x0) / count
    columns = np.asarray(image.crop((x0, y0, x1, y1)).convert("L"), np.float32).mean(axis=0)
    chunks, start = [], x0
    first = True
    for i in range(1, count):
        target = int(round(x0 + i * step))
        window = 40
        low, high = max(start + 4, target - window), min(x1 - 4, target + window)
        if low < high:
            cut = low + int(np.argmin(columns[low - x0:high - x0]))
        else:
            cut = target
        # A cut at an all-white column is a word gap (join with a space); a cut
        # inside a glyph is not, and the two halves must join with no space.
        gap = float(columns[max(0, cut - x0 - 1):cut - x0 + 2].max()) < 245
        chunks.append(((start, y0, cut, y1), first or not gap))
        start, first = cut, False
    chunks.append(((start, y0, x1, y1), first or True))
    return chunks


def rec_prep(image: Image.Image, box, rec_w: int, mode: str) -> np.ndarray:
    """Crop one line and fit it into rec_h x rec_w.

    ``clip`` is the old benched path: a wide line was resized to its true aspect
    width and then pasted into a fixed-width canvas, which silently kept only
    the left edge (the likely cause of truncated/garbled long lines).  ``fit``
    keeps every glyph: the line is scaled to the canvas width instead.
    """
    x0, y0, x1, y1 = [int(v) for v in box]
    x0, y0 = max(0, x0), max(0, y0)
    x1 = min(image.width, max(x0 + 2, x1))
    y1 = min(image.height, max(y0 + 2, y1))
    crop = image.crop((x0, y0, x1, y1))
    width = max(1, int(round(crop.width * REC_H / max(1, crop.height))))
    if width > rec_w:
        if mode == "clip":
            crop = crop.resize((width, REC_H), Image.Resampling.BILINEAR)
            crop = crop.crop((0, 0, rec_w, REC_H))
        else:
            crop = crop.resize((rec_w, REC_H), Image.Resampling.BILINEAR)
    else:
        crop = crop.resize((width, REC_H), Image.Resampling.BILINEAR)
    canvas = Image.new("RGB", (rec_w, REC_H), (255, 255, 255))
    canvas.paste(crop, (0, 0))
    array = np.asarray(canvas, np.float32) / 255.0
    return ((array - MEAN) / STD).transpose(2, 0, 1)[None]


def decode(pred: np.ndarray, chars: list[str], min_conf: float = 0.4) -> str:
    indices = pred.argmax(axis=2)[0]
    confidence = pred.max(axis=2)[0]
    out, keep, previous = [], [], -1
    for index, conf in zip(indices.tolist(), confidence.tolist()):
        if index != 0 and index != previous:
            out.append(chars[index])
            keep.append(conf)
        previous = index
    if not out or float(np.mean(keep)) < min_conf:
        return ""
    return "".join(out)


def load_chars(rec_path: str) -> list[str]:
    import onnxruntime as ort

    meta = ort.InferenceSession(rec_path, providers=["CPUExecutionProvider"]).get_modelmeta()
    return ["blank"] + meta.custom_metadata_map["character"].splitlines() + [" "]


def run_page(image, det, rec, chars, rec_w: int, mode: str = "fit",
             thresh: float = 0.3, split_lines: bool = True):
    text = run_orientation(image, det, rec, chars, rec_w, mode, thresh, split_lines)
    if len(text) >= 40:
        return text
    # A landscape table printed on a portrait page (or a rotated scan) keeps the
    # detector's boxes empty; retry the two quarter turns and keep the best.
    for angle in (90, 270):
        alternative = run_orientation(image.rotate(angle, expand=True), det, rec, chars,
                                      rec_w, mode, thresh, split_lines)
        if len(alternative) > len(text):
            text = alternative
    return text


def run_orientation(image, det, rec, chars, rec_w: int, mode: str, thresh: float,
                    split_lines: bool):
    array, scale = det_prep(image)
    prob = det.run(None, {det.get_inputs()[0].name: array})[0][0, 0]
    lines = []
    boxes = det_post(prob, scale, thresh=thresh, split_lines=split_lines)
    for box in boxes:
        pieces = line_chunks(box, image, rec_w) if mode == "fit" else [((box), True)]
        texts = []
        for piece, _ in pieces:
            pred = rec.run(None, {rec.get_inputs()[0].name: rec_prep(image, piece, rec_w, mode)})[0]
            text = decode(pred, chars)
            if text:
                texts.append(text)
        if texts:
            joined = texts[0]
            for i, text in enumerate(texts[1:], start=1):
                joined += (" " if pieces[i][1] else "") + text
            lines.append(joined)
    return "\n".join(lines)


def normalize(text: str) -> str:
    return " ".join(text.split())


def edit_distance(a: str, b: str) -> int:
    """Levenshtein distance, one vectorised row per character of ``a``."""
    if not a:
        return len(b)
    if not b:
        return len(a)
    if len(a) > len(b):
        a, b = b, a
    n, m = len(a), len(b)
    previous = np.arange(m + 1, dtype=np.int64)
    for i, ca in enumerate(a, start=1):
        cost = (np.frombuffer(b.encode("utf-32-le"), dtype=np.uint32) != ord(ca)).astype(np.int64)
        seed = np.minimum(previous[1:] + 1, previous[:-1] + cost)
        current = np.empty(m + 1, dtype=np.int64)
        current[0] = i
        current[1:] = np.minimum.accumulate(seed - np.arange(1, m + 1)) + np.arange(1, m + 1)
        previous = current
    return int(previous[m])


def accuracy(truth: str, ocr: str):
    """(folded accuracy, line-sorted accuracy, edit distance) against the text layer.

    ``folded`` is the ordinary character accuracy on whitespace-normalised,
    case-folded text.  ``lines`` sorts the lines of both sides first, so a page
    whose PDF content stream puts a letterhead after the body (a text-layer
    order artefact, not an OCR error) is not scored as one huge misalignment.
    """
    truth_n, ocr_n = normalize(truth), normalize(ocr)
    if not truth_n:
        return None, None, 0
    folded_t, folded_o = truth_n.casefold(), ocr_n.casefold()
    distance = edit_distance(folded_t, folded_o)
    folded = max(0.0, 1.0 - distance / len(folded_t))
    by_line_t = "\n".join(sorted(normalize(line).casefold()
                                 for line in truth.splitlines() if line.strip()))
    by_line_o = "\n".join(sorted(normalize(line).casefold()
                                 for line in ocr.splitlines() if line.strip()))
    line_distance = edit_distance(by_line_t, by_line_o)
    lines = max(0.0, 1.0 - line_distance / len(by_line_t)) if by_line_t else 0.0
    return folded, lines, distance


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=("scanned", "textlayer"), required=True)
    ap.add_argument("--list", help="scanned mode: file with relative/pdf/path.pdf|page per line")
    ap.add_argument("--base", help="scanned mode: directory the list paths are relative to")
    ap.add_argument("--text-dir", help="textlayer mode: directory of PDFs with a real text layer")
    ap.add_argument("--models", required=True)
    ap.add_argument("--provider", default="qnn-htp", choices=("cpu", "qnn-htp", "qnn-gpu"))
    ap.add_argument("--out", required=True)
    ap.add_argument("--rec-width", default="auto", help="auto, a fixed width, or 'clip' (old path)")
    ap.add_argument("--rec-model", default="rec32_960.onnx",
                    help="rec ONNX under --models (rec320.onnx for the old clip comparison)")
    ap.add_argument("--det-thresh", type=float, default=0.3)
    ap.add_argument("--no-split-lines", action="store_true",
                    help="keep whole connected components (the old block-level path)")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    split_lines = not args.no_split_lines

    det = open_session(str(Path(args.models) / "det960.onnx"), args.provider)
    rec = open_session(str(Path(args.models) / args.rec_model), args.provider)
    rec_w = rec.get_inputs()[0].shape[3]
    mode = "fit"
    if args.rec_width == "clip":
        rec_w, mode = 320, "clip"
    elif args.rec_width != "auto":
        rec_w = int(args.rec_width)
    chars = load_chars(str(Path(args.models) / args.rec_model))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    rows_path = out / (f"rows_{args.mode}_{args.provider}_{mode}_{rec_w}"
                       f"_t{args.det_thresh:g}_{'split' if split_lines else 'block'}.jsonl")
    rows = []
    started = time.time()
    with rows_path.open("w", encoding="utf-8") as handle:
        if args.mode == "textlayer":
            pdfs = sorted(Path(args.text_dir).glob("*.pdf"))
            if args.limit:
                pdfs = pdfs[: args.limit]
            for pdf in pdfs:
                image, page, truth = best_text_page(pdf)
                if len(normalize(truth)) < MIN_TRUTH_CHARS:
                    print(f"{pdf.stem}: skipped (text layer {len(normalize(truth))} chars)", flush=True)
                    continue
                ocr = run_page(image, det, rec, chars, rec_w, mode,
                               thresh=args.det_thresh, split_lines=split_lines)
                folded, lines, distance = accuracy(truth, ocr)
                row = {"id": pdf.stem, "pdf": pdf.name, "page": page,
                       "truth_chars": len(normalize(truth)), "ocr_chars": len(normalize(ocr)),
                       "distance": distance, "accuracy": round(folded or 0.0, 4),
                       "accuracy_lines": round(lines or 0.0, 4),
                       "ocr_start": normalize(ocr)[:200], "truth_start": normalize(truth)[:200]}
                rows.append(row)
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
                handle.flush()
                print(f"{pdf.stem:28s} p{page:<3d} truth={row['truth_chars']:5d} "
                      f"ocr={row['ocr_chars']:5d} acc={row['accuracy']:.3f} "
                      f"lines={row['accuracy_lines']:.3f}", flush=True)
        else:
            entries = [line.split("|") for line in
                       Path(args.list).read_text(encoding="utf-8").splitlines() if line.strip()]
            if args.limit:
                entries = entries[: args.limit]
            base = Path(args.base)
            for index, (relative, page) in enumerate(entries):
                image, page_number = render(base / relative, int(page))
                ocr = run_page(image, det, rec, chars, rec_w, mode,
                               thresh=args.det_thresh, split_lines=split_lines)
                row = {"id": f"{index:02d}_{Path(relative).stem[:8]}", "pdf": relative,
                       "page": page_number, "ocr_chars": len(normalize(ocr)),
                       "ocr_start": normalize(ocr)[:200]}
                rows.append(row)
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
                handle.flush()
                print(f"{row['id']:16s} p{page_number:<3d} ocr={row['ocr_chars']:5d} "
                      f"{normalize(ocr)[:90]}", flush=True)
    seconds = time.time() - started
    print(f"\n{len(rows)} pages in {seconds:.1f}s ({len(rows) / seconds * 60:.1f} pages/min)")
    if args.mode == "textlayer" and rows:
        scores = [r["accuracy"] for r in rows]
        line_scores = [r["accuracy_lines"] for r in rows]
        print(f"mean accuracy {sum(scores) / len(scores):.4f}  min {min(scores):.4f}  "
              f">=0.95: {sum(1 for s in scores if s >= 0.95)}/{len(scores)}")
        print(f"mean line-sorted accuracy {sum(line_scores) / len(line_scores):.4f}  "
              f">=0.95: {sum(1 for s in line_scores if s >= 0.95)}/{len(line_scores)}")
    print(rows_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
