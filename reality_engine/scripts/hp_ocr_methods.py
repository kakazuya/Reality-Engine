"""Run OCR engines over the frozen HP page set and save raw text plus boxes.

Every engine writes one JSONL row per page with the raw text and, where the
engine exposes them, line bounding boxes, so the gate score can be recomputed
or combined without running the engine again.

    python -m reality_engine.scripts.hp_ocr_methods run --engine media \
        --variant 3x --out C:\\RE\\ocr_test
    python -m reality_engine.scripts.hp_ocr_methods run --engine qnn \
        --variant 3x --out C:\\RE\\ocr_test

Engines: ``media`` (Windows.Media.Ocr), ``qnn`` and ``cpu`` (RapidOCR det960 +
rec32_960 ONNX), ``easyocr`` (Qualcomm AI Hub CRAFT + VGG/CTC), ``tesseract``
and ``ppocr`` (PP-OCRv5 ONNX).  Windows AI TextRecognizer rows are written by
its packaged helper in the same schema.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import subprocess
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

from reality_engine.scripts import hp_ocr_check as base
from reality_engine.scripts import hp_ocr_gate as gate
from reality_engine.scripts import hp_ocr_bench as bench

WORDLIKE = re.compile(r"[A-Za-z]{3,}")


def wordlike_tokens(text: str) -> int:
    return len(WORDLIKE.findall(text))


def image_for(page: dict, scale: float, cache: Path) -> Image.Image:
    """Render at ``scale`` (3x is the frozen image; other scales cached)."""
    if abs(scale - 3.0) < 1e-6:
        return Image.open(page["image"]).convert("RGB")
    cache.mkdir(parents=True, exist_ok=True)
    path = cache / f"{page['id']}_{scale:g}x.png"
    if path.exists():
        return Image.open(path).convert("RGB")
    pdf = Path(page["_base"]) / page["pdf"]
    image, _ = base.render(pdf, page["page"], scale=scale)
    image.save(path)
    return image


def write_row(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def load_manifest(path: Path) -> dict:
    manifest = gate.load_pages(path)
    base_dir = Path(manifest["base"])
    for page in manifest["pages"]:
        page["_base"] = str(base_dir)
    return manifest


def subset_pages(manifest: dict, args) -> list[dict]:
    pages = manifest["pages"]
    if args.only:
        pages = [p for p in pages if p["kind"] == args.only]
    if args.subset:
        wanted = set(json.loads(Path(args.subset).read_text(encoding="utf-8")))
        pages = [p for p in pages if p["id"] in wanted]
    if args.limit:
        pages = pages[: args.limit]
    return pages


# --------------------------------------------------------------------------- #
# Windows.Media.Ocr
# --------------------------------------------------------------------------- #

def otsu(gray: np.ndarray) -> int:
    histogram = np.bincount(gray.ravel(), minlength=256).astype(np.float64)
    total = histogram.sum()
    cumulative = np.cumsum(histogram)
    cumulative_mean = np.cumsum(histogram * np.arange(256))
    with np.errstate(divide="ignore", invalid="ignore"):
        between = ((cumulative_mean[-1] * cumulative / total - cumulative_mean) ** 2
                   / (cumulative * (total - cumulative)))
    between = np.nan_to_num(between)
    return int(between.argmax())


def binarise(image: Image.Image) -> Image.Image:
    gray = np.asarray(image.convert("L"), np.uint8)
    threshold = otsu(gray)
    mask = np.where(gray > threshold, 255, 0).astype(np.uint8)
    return Image.fromarray(mask, "L").convert("RGB")


def contrast(image: Image.Image) -> Image.Image:
    return ImageOps.autocontrast(image.convert("L"), cutoff=1).convert("RGB")


class MediaOcrEngine:
    name = "windows_media_ocr"

    def __init__(self):
        from winrt.windows.media.ocr import OcrEngine
        engine = OcrEngine.try_create_from_user_profile_languages()
        if engine is None:
            raise RuntimeError("no OCR language pack for the user profile")
        self.engine = engine
        self.max_side = OcrEngine.max_image_dimension
        self.device = "CPU"
        self.meta = {"max_image_dimension": self.max_side}

    def _bitmap(self, image: Image.Image):
        from winrt.windows.graphics.imaging import (BitmapAlphaMode, BitmapPixelFormat,
                                                    SoftwareBitmap)
        from winrt.windows.security.cryptography import CryptographicBuffer

        image = image.convert("RGBA")
        if max(image.size) > self.max_side:
            factor = self.max_side / max(image.size)
            image = image.resize((int(image.width * factor), int(image.height * factor)),
                                 Image.Resampling.LANCZOS)
        array = np.asarray(image, np.uint8)[:, :, [2, 1, 0, 3]]
        bitmap = SoftwareBitmap(BitmapPixelFormat.BGRA8, image.width, image.height,
                                BitmapAlphaMode.PREMULTIPLIED)
        bitmap.copy_from_buffer(CryptographicBuffer.create_from_byte_array(array.tobytes()))
        return bitmap

    async def _run(self, image):
        result = await self.engine.recognize_async(self._bitmap(image))
        lines = []
        for line in result.lines:
            rects = [word.bounding_rect for word in line.words]
            if rects:
                box = [min(r.x for r in rects), min(r.y for r in rects),
                       max(r.x + r.width for r in rects), max(r.y + r.height for r in rects)]
            else:
                box = [0.0, 0.0, 0.0, 0.0]
            words = sorted(line.words, key=lambda w: w.bounding_rect.x)
            text = " ".join(w.text for w in words) or line.text
            lines.append({"text": text, "box": box})
        lines.sort(key=lambda item: (round(item["box"][1] / 4), item["box"][0]))
        return "\n".join(item["text"] for item in lines), lines

    def run(self, image: Image.Image) -> tuple[str, list[dict], dict]:
        text, lines = asyncio.run(self._run(image))
        return text, lines, {"rotated": False}


def table_crops(image: Image.Image, min_width: int = 24, min_height: int = 14):
    """Cells between detected table rules, as (box, kind) rectangles.

    Horizontal rules are rows whose dark fraction is high; vertical rules are
    columns with the same property.  A dense table row is often skipped by
    Windows.Media.Ocr, so each band/cell is offered to the engine separately.
    """
    gray = np.asarray(image.convert("L"), np.uint8)
    dark = gray < 160
    _, width = dark.shape
    rows = dark.mean(axis=1)
    columns = dark.mean(axis=0)
    row_rules = np.flatnonzero(rows > 0.45)
    column_rules = np.flatnonzero(columns > 0.45)

    def groups(index):
        if index.size == 0:
            return []
        split = np.flatnonzero(np.diff(index) > 3)
        return np.split(index, split + 1)

    row_groups = [int(g.mean()) for g in groups(row_rules) if len(g) >= 1]
    column_groups = [int(g.mean()) for g in groups(column_rules) if len(g) >= 1]
    if len(row_groups) < 2:
        return []
    boxes = []
    for top, bottom in zip(row_groups, row_groups[1:]):
        if bottom - top < min_height:
            continue
        if len(column_groups) >= 2:
            for left, right in zip(column_groups, column_groups[1:]):
                if right - left >= min_width:
                    boxes.append((left + 1, top + 1, right - 1, bottom - 1))
        else:
            boxes.append((2, top + 1, width - 2, bottom - 1))
    return boxes


def media_rows(pages: list[dict], variant: str, out: Path, cache: Path) -> dict:
    scale = float(variant.split("_")[0].rstrip("x"))
    engine = MediaOcrEngine()
    rows_dir = out / "media" / "variants" / variant
    rows_path = rows_dir / "rows.jsonl"
    if rows_path.exists():
        rows_path.unlink()
    started = time.time()
    count = 0
    for page in pages:
        image = image_for(page, scale, cache)
        if variant.endswith("_contrast"):
            image = contrast(image)
        elif variant.endswith("_binary"):
            image = binarise(image)
        t0 = time.time()
        text, lines, meta = engine.run(image)
        rotated = None
        if len(gate.normalize(text)) < 40 or wordlike_tokens(text) < 3:
            best = (len(text), text, lines, None)
            for angle in (90, 270):
                candidate_image = image.rotate(angle, expand=True)
                alt_text, alt_lines, _ = engine.run(candidate_image)
                if len(alt_text) > best[0]:
                    best = (len(alt_text), alt_text, alt_lines, angle)
            text, lines = best[1], best[2]
            rotated = best[3]
        extra = ""
        if variant.endswith("_rows") or variant.endswith("_cells"):
            boxes = table_crops(image)
            pieces = []
            for box in boxes:
                crop = image.crop(tuple(int(v) for v in box))
                if crop.width < 8 or crop.height < 6:
                    continue
                crop_text, _, _ = engine.run(crop)
                if crop_text.strip():
                    pieces.append(crop_text)
            if pieces:
                main_numbers = set(gate.numbers(text))
                novel = []
                for piece in pieces:
                    if any(n not in main_numbers for n in gate.numbers(piece)):
                        novel.append(piece)
                extra = "\n".join(novel)
                text = text + ("\n" + extra if extra else "")
        elapsed = time.time() - t0
        write_row(rows_path, {
            "id": page["id"], "engine": engine.name, "variant": variant,
            "device": engine.device, "seconds": round(elapsed, 3),
            "text": text, "lines": lines,
            "meta": {**engine.meta, **meta, "rotated": rotated,
                     "scale": scale, "row_crops": len(table_crops(image)) if "_rows" in variant else 0,
                     "crop_chars": len(extra)},
        })
        count += 1
        print(f"{page['id']} {elapsed:5.2f}s {len(gate.normalize(text)):6d} chars", flush=True)
    return {"pages": count, "seconds": round(time.time() - started, 2),
            "rows": str(rows_path)}


# --------------------------------------------------------------------------- #
# RapidOCR ONNX (QNN HTP or CPU)
# --------------------------------------------------------------------------- #

class RapidOcrEngine:
    def __init__(self, provider: str, models: str = r"C:\RE\models_fixed"):
        self.name = "rapidocr_qnn" if provider.startswith("qnn") else "rapidocr_cpu"
        self.det = base.open_session(str(Path(models) / "det960.onnx"), provider)
        self.rec = base.open_session(str(Path(models) / "rec32_960.onnx"), provider)
        self.rec_w = self.rec.get_inputs()[0].shape[3]
        self.chars = base.load_chars(str(Path(models) / "rec32_960.onnx"))
        self.device = "NPU (QnnHtp)" if provider.startswith("qnn") else "CPU"
        self.provider = provider
        self.meta = {"provider": provider, "rec_width": self.rec_w}

    def _orientation(self, image: Image.Image):
        array, scale = base.det_prep(image)
        probability = self.det.run(None, {self.det.get_inputs()[0].name: array})[0][0, 0]
        boxes = base.det_post(probability, scale, thresh=0.3, split_lines=True)
        lines = []
        for box in boxes:
            pieces = base.line_chunks(box, image, self.rec_w)
            texts = []
            for piece, _ in pieces:
                prediction = self.rec.run(
                    None, {self.rec.get_inputs()[0].name:
                           base.rec_prep(image, piece, self.rec_w, "fit")})[0]
                value = base.decode(prediction, self.chars)
                if value:
                    texts.append(value)
            if texts:
                lines.append({"text": " ".join(texts),
                              "box": [round(v, 1) for v in box]})
        return "\n".join(item["text"] for item in lines), lines

    def run(self, image: Image.Image) -> tuple[str, list[dict], dict]:
        text, lines = self._orientation(image)
        rotated = None
        if len(gate.normalize(text)) < 40 or wordlike_tokens(text) < 3:
            best = (len(text), text, lines, None)
            for angle in (90, 270):
                alt_text, alt_lines = self._orientation(image.rotate(angle, expand=True))
                if len(alt_text) > best[0]:
                    best = (len(alt_text), alt_text, alt_lines, angle)
            text, lines = best[1], best[2]
            rotated = best[3]
        return text, lines, {"rotated": rotated}


def rapid_rows(pages: list[dict], provider: str, variant: str, out: Path,
               cache: Path) -> dict:
    scale = float(variant.split("_")[0].rstrip("x"))
    engine = RapidOcrEngine(provider)
    rows_path = out / ("qnn" if provider.startswith("qnn") else "cpu") / "variants" / variant / "rows.jsonl"
    if rows_path.exists():
        rows_path.unlink()
    started = time.time()
    count = 0
    for page in pages:
        image = image_for(page, scale, cache)
        if variant.endswith("_binary"):
            image = binarise(image)
        t0 = time.time()
        text, lines, meta = engine.run(image)
        elapsed = time.time() - t0
        write_row(rows_path, {
            "id": page["id"], "engine": engine.name, "variant": variant,
            "device": engine.device, "seconds": round(elapsed, 3),
            "text": text, "lines": lines,
            "meta": {**engine.meta, **meta, "scale": scale},
        })
        count += 1
        print(f"{page['id']} {elapsed:6.2f}s {len(gate.normalize(text)):6d} chars", flush=True)
    return {"pages": count, "seconds": round(time.time() - started, 2),
            "rows": str(rows_path)}


# --------------------------------------------------------------------------- #
# Qualcomm AI Hub EasyOCR
# --------------------------------------------------------------------------- #

class EasyOcrEngine:
    name = "qualcomm_easyocr"

    def __init__(self, models: str = r"C:\RE\models_easyocr\easyocr-onnx-float",
                 det_provider: str = "qnn-htp", rec_provider: str = "cpu"):
        root = Path(models)
        self.det = base.open_session(str(root / "detector.onnx"), det_provider)
        self.rec = base.open_session(str(root / "recognizer.onnx"), rec_provider)
        self.det_input = self.det.get_inputs()[0].name
        self.rec_input = self.rec.get_inputs()[0].name
        self.device = f"NPU det ({det_provider}) + CPU rec"
        self.meta = {"det_provider": det_provider, "rec_provider": rec_provider}

    def run(self, image: Image.Image) -> tuple[str, list[dict], dict]:
        array = np.asarray(image.convert("RGB").resize((800, 608), Image.Resampling.BILINEAR),
                           np.float32) / 255.0
        tensor = ((array - base.MEAN) / base.STD).transpose(2, 0, 1)[None]
        result = np.asarray(self.det.run(None, {self.det_input: tensor})[0])
        probability = result[0, :, :, 0]
        width = 1000
        height = max(1, int(round(probability.shape[0] * width / probability.shape[1])))
        small = np.asarray(Image.fromarray(probability).resize((width, height),
                                                              Image.Resampling.BILINEAR))
        boxes = base.det_post(small, 1.0, thresh=0.3, expand=1.4, split_lines=True)
        sx, sy = image.width / width, image.height / height
        lines = []
        for x0, y0, x1, y1 in boxes:
            crop = image.crop((int(x0 * sx), int(y0 * sy), int(x1 * sx), int(y1 * sy)))
            if crop.width < 2 or crop.height < 2:
                continue
            crop = crop.convert("L")
            crop_w = max(1, min(800, int(round(crop.width * 64 / crop.height))))
            crop = crop.resize((crop_w, 64), Image.Resampling.BILINEAR)
            canvas = Image.new("L", (800, 64), 0)
            canvas.paste(crop, (0, 0))
            tensor = (np.asarray(canvas, np.float32) / 255.0)[None, None]
            prediction = np.asarray(self.rec.run(None, {self.rec_input: tensor})[0])[0]
            indices = prediction.argmax(axis=1)
            out, previous = [], -1
            for index in indices.tolist():
                if index != 0 and index != previous:
                    out.append(bench.EASYOCR_CHARS[index - 1])
                previous = index
            text = "".join(out).strip()
            if text:
                lines.append({"text": text,
                              "box": [round(x0 * sx, 1), round(y0 * sy, 1),
                                      round(x1 * sx, 1), round(y1 * sy, 1)]})
        return "\n".join(item["text"] for item in lines), lines, {"rotated": False}


def easyocr_rows(pages: list[dict], out: Path, cache: Path, limit: int = 30) -> dict:
    engine = EasyOcrEngine()
    if limit:
        pages = pages[:limit]
    rows_path = out / "easyocr" / "variants" / "qnn_det_cpu_rec" / "rows.jsonl"
    if rows_path.exists():
        rows_path.unlink()
    started = time.time()
    count = 0
    for page in pages:
        image = image_for(page, 3.0, cache)
        t0 = time.time()
        text, lines, meta = engine.run(image)
        elapsed = time.time() - t0
        write_row(rows_path, {
            "id": page["id"], "engine": engine.name, "variant": "qnn_det_cpu_rec",
            "device": engine.device, "seconds": round(elapsed, 3),
            "text": text, "lines": lines, "meta": {**engine.meta, **meta},
        })
        count += 1
        print(f"{page['id']} {elapsed:6.2f}s {len(gate.normalize(text)):6d} chars", flush=True)
    return {"pages": count, "seconds": round(time.time() - started, 2),
            "rows": str(rows_path)}


# --------------------------------------------------------------------------- #
# Tesseract (native ARM64 or x64 under emulation)
# --------------------------------------------------------------------------- #

TESSERACT_CANDIDATES = [
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    "tesseract",
]


def tesseract_exe() -> str:
    for candidate in TESSERACT_CANDIDATES:
        path = Path(candidate)
        if path.exists():
            return str(path)
        if candidate == "tesseract":
            from shutil import which
            found = which(candidate)
            if found:
                return found
    raise FileNotFoundError("tesseract not installed")


def parse_tsv(output: str) -> list[dict]:
    """Group Tesseract TSV word rows into lines with page boxes."""
    lines: dict[tuple, dict] = {}
    for line in output.splitlines()[1:]:
        parts = line.split("\t")
        if len(parts) < 12 or parts[0] != "5":
            continue
        block, paragraph, line_no, word_no = (int(parts[i]) for i in range(1, 5))
        left, top, width, height = (int(parts[i]) for i in (6, 7, 8, 9))
        text = parts[11].strip()
        if not text:
            continue
        key = (block, paragraph, line_no)
        item = lines.setdefault(key, {"words": [], "box": [left, top, left + width, top + height]})
        item["words"].append((left, top, word_no, text))
        item["box"] = [min(item["box"][0], left), min(item["box"][1], top),
                       max(item["box"][2], left + width), max(item["box"][3], top + height)]
    out = []
    for item in lines.values():
        item["words"].sort(key=lambda w: (w[0], w[2]))
        out.append({"text": " ".join(w[3] for w in item["words"]), "box": item["box"]})
    out.sort(key=lambda item: (round(item["box"][1] / 6), item["box"][0]))
    return out


def tesseract_pass(exe: str, image_path: Path, psm: int, whitelist: str = "",
                   preserve_spaces: bool = True) -> tuple[str, list[dict]]:
    command = [exe, str(image_path), "stdout", "--psm", str(psm), "-l", "eng", "tsv"]
    if preserve_spaces:
        command += ["-c", "preserve_interword_spaces=1"]
    if whitelist:
        command += ["-c", f"tessedit_char_whitelist={whitelist}"]
    proc = subprocess.run(command, capture_output=True, text=True, encoding="utf-8",
                          errors="replace")
    if proc.returncode != 0:
        raise RuntimeError(f"tesseract failed: {proc.stderr[-500:]}")
    lines = parse_tsv(proc.stdout)
    return "\n".join(item["text"] for item in lines), lines


def tesseract_rows(pages: list[dict], out: Path, cache: Path, psm: int = 6,
                   variant: str = "psm6") -> dict:
    exe = tesseract_exe()
    version = subprocess.run([exe, "--version"], capture_output=True, text=True).stdout
    rows_path = out / "tesseract" / "variants" / variant / "rows.jsonl"
    if rows_path.exists():
        rows_path.unlink()
    started = time.time()
    count = 0
    scratch = out / "tesseract" / "scratch"
    scratch.mkdir(parents=True, exist_ok=True)
    for page in pages:
        image = image_for(page, 4.0, cache)
        png = scratch / f"{page['id']}.png"
        image.save(png)
        t0 = time.time()
        text, lines = tesseract_pass(exe, png, psm)
        digits = ""
        if page["kind"] == "table":
            digits, digit_lines = tesseract_pass(
                exe, png, psm, whitelist="0123456789.,()-+%")
            seen = set(gate.numbers(text))
            digits = "\n".join(line["text"] for line in digit_lines
                               if any(n not in seen for n in gate.numbers(line["text"])))
        elapsed = time.time() - t0
        write_row(rows_path, {
            "id": page["id"], "engine": "tesseract", "variant": variant,
            "device": "CPU (x64 under emulation)" if "ARM64" not in version else "CPU ARM64",
            "seconds": round(elapsed, 3), "text": text + ("\n" + digits if digits else ""),
            "lines": lines, "meta": {"psm": psm, "version": version.splitlines()[0],
                                      "digits_chars": len(digits), "scale": 4.0},
        })
        count += 1
        print(f"{page['id']} {elapsed:6.2f}s {len(gate.normalize(text)):6d} chars", flush=True)
    return {"pages": count, "seconds": round(time.time() - started, 2),
            "rows": str(rows_path), "version": version.splitlines()[0]}


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run")
    run.add_argument("--engine", required=True,
                     choices=("media", "qnn", "cpu", "easyocr", "tesseract", "ppocr"))
    run.add_argument("--variant", default="3x")
    run.add_argument("--out", default=r"C:\RE\ocr_test")
    run.add_argument("--pages", default=r"C:\RE\ocr_test\pages.json")
    run.add_argument("--only", choices=("table", "prose"))
    run.add_argument("--subset")
    run.add_argument("--limit", type=int, default=0)
    run.add_argument("--psm", type=int, default=6)
    sel = sub.add_parser("select")
    sel.add_argument("--engine", required=True)
    sel.add_argument("--variant", required=True)
    sel.add_argument("--out", default=r"C:\RE\ocr_test")
    conv = sub.add_parser("convert-windowsai")
    conv.add_argument("--raw", required=True)
    conv.add_argument("--out", default=r"C:\RE\ocr_test")
    conv.add_argument("--pages", default=r"C:\RE\ocr_test\pages.json")
    args = ap.parse_args()

    out = Path(args.out)
    if args.command == "convert-windowsai":
        result = convert_windowsai(Path(args.raw), out, Path(args.pages))
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "select":
        source = out / args.engine / "variants" / args.variant / "rows.jsonl"
        target = out / args.engine / "rows.jsonl"
        target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
        print(f"{source} -> {target}")
        return 0

    manifest = load_manifest(Path(args.pages))
    pages = subset_pages(manifest, args)
    cache = out / "renders"
    print(f"{len(pages)} pages, engine={args.engine} variant={args.variant}", flush=True)
    if args.engine == "media":
        result = media_rows(pages, args.variant, out, cache)
    elif args.engine in ("qnn", "cpu"):
        result = rapid_rows(pages, "qnn-htp" if args.engine == "qnn" else "cpu",
                            args.variant, out, cache)
    elif args.engine == "easyocr":
        result = easyocr_rows(pages, out, cache, limit=args.limit or 30)
    elif args.engine == "tesseract":
        result = tesseract_rows(pages, out, cache, psm=args.psm, variant=args.variant)
    else:
        result = ppocr_rows(pages, args.variant, out, cache)
    print(json.dumps(result, indent=2))
    return 0


def ppocr_rows(pages: list[dict], variant: str, out: Path, cache: Path) -> dict:
    """PP-OCRv5 mobile rec on CPU; 'hybrid' also uses the RapidOCR det960 boxes."""
    hybrid = "hybrid" in variant
    engine = PpOcrV5(r"C:\RE\models_ppocrv5", rapid_det=hybrid)
    rows_path = out / "ppocr" / "variants" / variant / "rows.jsonl"
    if rows_path.exists():
        rows_path.unlink()
    started = time.time()
    count = 0
    for page in pages:
        image = image_for(page, 3.0, cache)
        t0 = time.time()
        text, lines = (engine.run_hybrid(image) if hybrid else engine.run(image))
        elapsed = time.time() - t0
        write_row(rows_path, {
            "id": page["id"], "engine": "ppocrv5_hybrid" if hybrid else "ppocrv5_cpu",
            "variant": variant,
            "device": "CPU (ONNX Runtime, RapidOCR det960 + PP-OCRv5 rec)" if hybrid
                      else "CPU (ONNX Runtime, PP-OCRv5 det+rec)",
            "seconds": round(elapsed, 3),
            "text": text, "lines": lines,
            "meta": {"models": ("rapidocr det960 + " if hybrid else "")
                     + "PP-OCRv5_mobile_det_onnx + PP-OCRv5_mobile_rec_onnx",
                     "provider": "CPUExecutionProvider", "scale": 3.0},
        })
        count += 1
        print(f"{page['id']} {elapsed:6.2f}s {len(gate.normalize(text)):6d} chars", flush=True)
    return {"pages": count, "seconds": round(time.time() - started, 2),
            "rows": str(rows_path)}


class PpOcrV5:
    """PP-OCRv5 mobile detector + recogniser, official ONNX exports on CPU."""

    def __init__(self, models: str, rapid_det: bool = False):
        import onnxruntime as ort

        options = ort.SessionOptions()
        options.log_severity_level = 4
        self.det = ort.InferenceSession(str(Path(models) / "det.onnx"), options,
                                        providers=["CPUExecutionProvider"])
        self.rec = ort.InferenceSession(str(Path(models) / "rec.onnx"), options,
                                        providers=["CPUExecutionProvider"])
        lines = (Path(models) / "ppocrv5_dict.txt").read_text(encoding="utf-8").splitlines()
        self.chars = [""] + lines + [" "]
        self.det_input = self.det.get_inputs()[0].name
        self.rec_input = self.rec.get_inputs()[0].name
        self.rapid_det = None
        if rapid_det:
            self.rapid_det = base.open_session(r"C:\RE\models_fixed\det960.onnx", "cpu")

    def _detect(self, image: Image.Image):
        array = np.asarray(image.convert("RGB"), np.float32)[:, :, ::-1] / 255.0
        height, width = array.shape[:2]
        scale = 960.0 / max(width, height)
        new_w = max(32, int(round(width * scale / 32)) * 32)
        new_h = max(32, int(round(height * scale / 32)) * 32)
        resized = np.asarray(Image.fromarray((array * 255).astype(np.uint8)).resize(
            (new_w, new_h), Image.Resampling.LANCZOS), np.float32) / 255.0
        normal = (resized - np.array([0.485, 0.456, 0.406], np.float32)) / np.array(
            [0.229, 0.224, 0.225], np.float32)
        tensor = normal.transpose(2, 0, 1)[None]
        probability = self.det.run(None, {self.det_input: tensor})[0][0, 0]
        # One scale for both axes: the page is resized with the aspect kept.
        return base.det_post(probability, new_w / width, thresh=0.3, expand=1.5,
                             split_lines=True)

    def _recognise_piece(self, image: Image.Image, box) -> tuple[str, float]:
        x0, y0, x1, y1 = [int(round(v)) for v in box]
        x0, y0 = max(0, x0), max(0, y0)
        x1, y1 = min(image.width, x1), min(image.height, y1)
        if x1 - x0 < 2 or y1 - y0 < 2:
            return "", 0.0
        crop = image.crop((x0, y0, x1, y1)).convert("RGB")
        width = max(1, min(320, int(round(crop.width * 48 / crop.height))))
        crop = crop.resize((width, 48), Image.Resampling.BILINEAR)
        canvas = Image.new("RGB", (320, 48), (0, 0, 0))
        canvas.paste(crop, (0, 0))
        array = np.asarray(canvas, np.float32)[:, :, ::-1] / 255.0
        tensor = ((array - 0.5) / 0.5).transpose(2, 0, 1)[None]
        prediction = self.rec.run(None, {self.rec_input: tensor})[0][0]
        indices = prediction.argmax(axis=1)
        scores = prediction.max(axis=1)
        out, keep, previous = [], [], -1
        for index, score in zip(indices.tolist(), scores.tolist()):
            if index not in (0, previous) and index < len(self.chars):
                out.append(self.chars[index])
                keep.append(score)
            previous = index
        if not out or (keep and float(np.mean(keep)) < 0.35):
            return "", 0.0
        return "".join(out), float(np.mean(keep)) if keep else 0.0

    def _recognise(self, image: Image.Image, box) -> tuple[str, float]:
        # A full-width table line squashed into 320 px loses the figures; cut it
        # into rec-sized pieces exactly as the RapidOCR path does.
        pieces = base.line_chunks(box, image, 320)
        texts, scores = [], []
        for piece, _ in pieces:
            text, confidence = self._recognise_piece(image, piece)
            if text:
                texts.append(text)
                scores.append(confidence)
        return " ".join(texts), float(np.mean(scores)) if scores else 0.0

    def run(self, image: Image.Image) -> tuple[str, list[dict]]:
        lines = []
        for box in self._detect(image):
            text, confidence = self._recognise(image, box)
            if text:
                lines.append({"text": text,
                              "box": [round(v, 1) for v in box],
                              "confidence": round(confidence, 3)})
        return "\n".join(item["text"] for item in lines), lines

    def run_hybrid(self, image: Image.Image) -> tuple[str, list[dict]]:
        """PP-OCRv5 recogniser over the RapidOCR det960 boxes (proper DB unclip)."""
        if self.rapid_det is None:
            raise RuntimeError("rapid_det not loaded")
        array, scale = base.det_prep(image)
        probability = self.rapid_det.run(
            None, {self.rapid_det.get_inputs()[0].name: array})[0][0, 0]
        boxes = base.det_post(probability, scale, thresh=0.3, expand=1.4, split_lines=True)
        lines = []
        for box in boxes:
            text, confidence = self._recognise(image, box)
            if text:
                lines.append({"text": text,
                              "box": [round(v, 1) for v in box],
                              "confidence": round(confidence, 3)})
        return "\n".join(item["text"] for item in lines), lines


def convert_windowsai(raw: Path, out: Path, pages_path: Path) -> dict:
    """Map the packaged C# helper's output onto the frozen page ids."""
    manifest = gate.load_pages(pages_path)
    by_image = {str(Path(page["image"])): page["id"] for page in manifest["pages"]}
    rows_path = out / "windowsai" / "rows.jsonl"
    rows_path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with rows_path.open("w", encoding="utf-8") as handle:
        for line in raw.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            raw_row = json.loads(line)
            page_id = by_image.get(raw_row.get("path"))
            if page_id is None:
                continue
            lines = [{"text": item.get("text", ""), "box": item.get("box")}
                     for item in (raw_row.get("line_rows") or [])]
            handle.write(json.dumps({
                "id": page_id,
                "engine": "windows_ai_textrecognizer",
                "device": "Windows AI (Microsoft.Windows.AI.Imaging; NPU not named by the API)",
                "seconds": raw_row.get("seconds"),
                "text": raw_row.get("text") or "",
                "lines": lines,
                "meta": {"modules": raw_row.get("modules"),
                         "text_angle": raw_row.get("angle"),
                         "line_count": raw_row.get("lines"),
                         "cpu_seconds": raw_row.get("cpu_seconds"),
                         "error": raw_row.get("error")},
            }, ensure_ascii=False) + "\n")
            count += 1
    return {"pages": count, "rows": str(rows_path)}


if __name__ == "__main__":
    raise SystemExit(main())
