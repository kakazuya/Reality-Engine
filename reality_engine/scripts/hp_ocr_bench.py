"""Compare OCR engines on the HP's 20 text-layer pages and 20 scanned pages.

The baseline path (RapidOCR det/rec ONNX on the QNN HTP NPU with the numpy
post-processing in :mod:`reality_engine.scripts.hp_ocr_check`) is scored against
the PDF text layer.  Every other engine is scored on the same rendered page and
truth so the numbers are comparable.

Beyond the plain character accuracy of ``hp_ocr_check`` this reports:

* ``order_free``: token-level accuracy after sorting both sides, so a page whose
  words are all right but whose table reading order differs is not punished;
* ``numbers``: exact-number recall (distinct numbers in the truth that appear in
  the OCR after comma normalisation) -- the figure that matters in filings;
* ``accuracy_lines``: the line-sorted character accuracy used in section 10.

Engine adapters live here rather than in ``hp_ocr_check`` because they have
different dependencies (Windows.Media.Ocr, a C# Windows App SDK helper, ONNX
runtime providers) and only this script needs the common metric.

The Windows App SDK ``TextRecognizer`` adapter below is superseded by
``reality_engine.scripts.hp_ocr_large`` and the packaged helper in
``reality_engine/tools/textrec/``: the engine only answers from a signed MSIX
with package identity launched in the interactive session, so the plain
subprocess call in this module cannot reach it.

    python -m reality_engine.scripts.hp_ocr_bench --engine qnn --mode textlayer \
        --models C:\\RE\\models_fixed --out C:\\RE\\bench\\out

The scanned pages have no text layer, so they are scored only on page rate and,
when ``--keys`` is given, on the hand-read key numbers for that page.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import time
from pathlib import Path

import numpy as np
from PIL import Image

from reality_engine.scripts import hp_ocr_check as base

WORD = re.compile(r"\S+")
NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


def normalize(text: str) -> str:
    return " ".join(text.split())


def weight(text: str) -> int:
    """Sequence length used to normalise an edit distance (characters)."""
    return len(text)


def order_free_score(truth_tokens: list[str], ocr_tokens: list[str]) -> float:
    """Bag-of-words accuracy: the same characters, with word order ignored.

    Sorting the tokens and then taking the ordinary character accuracy keeps
    this comparable with ``accuracy`` (a typo inside a word costs its characters,
    not a whole token) while a table read column-by-column is no longer punished
    for putting the right words in a different order.
    """
    truth_sorted = " ".join(sorted(t.casefold() for t in truth_tokens))
    ocr_sorted = " ".join(sorted(t.casefold() for t in ocr_tokens))
    if not truth_sorted:
        return 0.0
    return max(0.0, 1.0 - base.edit_distance(truth_sorted, ocr_sorted) / len(truth_sorted))


def numbers(text: str) -> list[str]:
    """Distinct numbers, commas removed so 1,433 and 1433 compare equal."""
    out = []
    for match in NUMBER.findall(text):
        value = match.replace(",", "").rstrip(".")
        if value and value not in out:
            out.append(value)
    return out


def score(truth: str, ocr: str) -> dict:
    truth_n, ocr_n = normalize(truth), normalize(ocr)
    truth_tokens = WORD.findall(truth_n)
    ocr_tokens = WORD.findall(ocr_n)
    if not truth_n:
        return {}
    folded = 1.0 - base.edit_distance(truth_n.casefold(), ocr_n.casefold()) / len(truth_n)
    order_free = order_free_score(truth_tokens, ocr_tokens)
    truth_numbers, ocr_numbers = numbers(truth_n), numbers(ocr_n)
    found = [n for n in truth_numbers if n in ocr_numbers]
    return {
        "accuracy": round(max(0.0, folded), 4),
        "order_free": round(max(0.0, order_free), 4),
        "number_recall": round(len(found) / len(truth_numbers), 4) if truth_numbers else None,
        "number_truth": len(truth_numbers),
        "number_found": len(found),
        "truth_chars": len(truth_n),
        "ocr_chars": len(ocr_n),
    }


PAGE_TYPES = {
    # Statutory annexures whose truth is a field/value table rather than prose.
    "ASHIANA__45a28a8f": "table",   # SEBI Form C continual-disclosure form
    "PRESTIGE__3afb2252": "table",  # Annexure I corporate-guarantee particulars
    "STLTECH__373691c5": "slide",   # investor-presentation safe-harbour page
}


def page_type(page_id: str = "") -> str:
    """letter / table / slide.

    The corpus is 17 letters, two statutory annexures and one presentation page;
    the two annexures are named explicitly because a numeric-line heuristic also
    fires on ordinary letters with address blocks.  Rotated pages are scored
    separately through the ``rotated`` flag, not as a truth type.
    """
    if page_id in PAGE_TYPES:
        return PAGE_TYPES[page_id]
    return "letter"


# --------------------------------------------------------------------------- #
# Engines
# --------------------------------------------------------------------------- #

def npu_modules() -> list[str]:
    """Loaded modules that identify an accelerator (NPU/DSP) or the Windows AI stack.

    The HP exposes no NPU performance counter, so the loaded backend DLL is the
    evidence: ``QnnHtp.dll`` means the Hexagon tensor backend is in this process,
    ``Microsoft.Windows.AI.*.dll`` means the Windows AI stack is.
    """
    import ctypes

    kernel32 = ctypes.WinDLL("kernel32")
    psapi = ctypes.WinDLL("psapi")
    kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    psapi.EnumProcessModules.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                         ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong)]
    psapi.EnumProcessModules.restype = ctypes.c_int
    psapi.GetModuleBaseNameW.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                        ctypes.c_wchar_p, ctypes.c_ulong]
    psapi.GetModuleBaseNameW.restype = ctypes.c_ulong
    handle = kernel32.GetCurrentProcess()
    modules = (ctypes.c_void_p * 4096)()
    needed = ctypes.c_ulong(0)
    if not psapi.EnumProcessModules(handle, ctypes.byref(modules), ctypes.sizeof(modules),
                                    ctypes.byref(needed)):
        return []
    names = []
    for index in range(needed.value // ctypes.sizeof(ctypes.c_void_p)):
        buffer = ctypes.create_unicode_buffer(260)
        if psapi.GetModuleBaseNameW(handle, modules[index], buffer, 260):
            names.append(buffer.value)
    return sorted({n for n in names if re.search(
        r"qnn|htp|npu|hexagon|windows\.ai|Windows\.Vision|AI\.Imaging", n, re.I)})


class QnnRapidOCR:
    """The current HP pipeline: det960 + rec32_960 on QNN HTP, numpy post-processing."""

    name = "qnn_rapidocr"

    def __init__(self, models: str, provider: str = "qnn-htp", thresh: float = 0.3):
        self.det = base.open_session(str(Path(models) / "det960.onnx"), provider)
        self.rec = base.open_session(str(Path(models) / "rec32_960.onnx"), provider)
        self.rec_w = self.rec.get_inputs()[0].shape[3]
        self.chars = base.load_chars(str(Path(models) / "rec32_960.onnx"))
        self.thresh = thresh
        self.providers = self.det.get_providers()

    def run(self, image) -> tuple[str, dict]:
        text = base.run_orientation(image, self.det, self.rec, self.chars, self.rec_w,
                                    "fit", self.thresh, True)
        rotated = False
        if len(text) < 40:
            for angle in (90, 270):
                alternative = base.run_orientation(image.rotate(angle, expand=True),
                                                   self.det, self.rec, self.chars,
                                                   self.rec_w, "fit", self.thresh, True)
                if len(alternative) > len(text):
                    text, rotated = alternative, True
        return text, {"rotated": rotated, "device": "NPU (QnnHtp)"}


class MediaOcr:
    """Windows.Media.Ocr -- the OCR engine that ships with Windows itself."""

    name = "windows_media_ocr"

    def __init__(self):
        from winrt.windows.media.ocr import OcrEngine
        engine = OcrEngine.try_create_from_user_profile_languages()
        if engine is None:
            raise RuntimeError("no OCR language pack for the user profile")
        self.engine = engine
        self.max_side = OcrEngine.max_image_dimension
        self.providers = []

    def _bitmap(self, image):
        from winrt.windows.graphics.imaging import BitmapAlphaMode, BitmapPixelFormat, SoftwareBitmap
        from winrt.windows.security.cryptography import CryptographicBuffer

        image = image.convert("RGBA")
        if max(image.size) > self.max_side:
            scale = self.max_side / max(image.size)
            image = image.resize((int(image.width * scale), int(image.height * scale)))
        array = np.asarray(image, np.uint8)[:, :, [2, 1, 0, 3]]  # RGBA -> BGRA
        bitmap = SoftwareBitmap(BitmapPixelFormat.BGRA8, image.width, image.height,
                                BitmapAlphaMode.PREMULTIPLIED)
        bitmap.copy_from_buffer(CryptographicBuffer.create_from_byte_array(
            array.tobytes()))
        return bitmap

    async def _run(self, image):
        result = await self.engine.recognize_async(self._bitmap(image))
        lines = []
        for line in result.lines:
            rects = [word.bounding_rect for word in line.words]
            left = min((r.x for r in rects), default=0.0)
            top = min((r.y for r in rects), default=0.0)
            lines.append((top, left, line.text))
        # Recognition order is not reading order on forms; sorting the lines by
        # their own bounding boxes measures how much of the gap is just order.
        by_position = "\n".join(text for _, _, text in sorted(lines))
        return result.text or "", by_position

    def run(self, image) -> tuple[str, dict]:
        text, by_position = asyncio.run(self._run(image))
        return text, {"rotated": False, "text_by_pos": by_position,
                      "device": "see modules"}


EASYOCR_CHARS = (
    "0123456789!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~ \u20ac"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
)


class EasyOcrQnn:
    """Qualcomm AI Hub EasyOCR: CRAFT detector + VGG/CTC recogniser.

    The asset is the public ``easyocr-onnx-float`` release (Apache-2.0, no
    account).  The detector is the standard CRAFT network (20.8M parameters,
    output is (text score, link score) per half-resolution pixel); the
    recogniser is EasyOCR's ``english_g2`` VGG model with an LSTM sequence
    layer, 96-character alphabet + CTC blank.
    """

    name = "qualcomm_easyocr"

    def __init__(self, models: str, det_provider: str = "qnn-htp",
                 rec_provider: str = "cpu", thresh: float = 0.3,
                 expand: float = 1.4, split: bool = True):
        root = Path(models)
        self.det = base.open_session(str(root / "detector.onnx"), det_provider)
        self.rec = base.open_session(str(root / "recognizer.onnx"), rec_provider)
        self.providers = {"detector": self.det.get_providers(),
                          "recogniser": self.rec.get_providers()}
        self.det_input = self.det.get_inputs()[0].name
        self.rec_input = self.rec.get_inputs()[0].name
        self.thresh, self.expand, self.split = thresh, expand, split

    def _detect(self, image) -> list[tuple[float, float, float, float]]:
        array = np.asarray(image.convert("RGB").resize((800, 608), Image.Resampling.BILINEAR),
                           np.float32) / 255.0
        tensor = ((array - base.MEAN) / base.STD).transpose(2, 0, 1)[None]
        result = np.asarray(self.det.run(None, {self.det_input: tensor})[0])
        prob = result[0, :, :, 0]
        # Work at a fixed 1000-px width, then map the boxes back to the page.
        width = 1000
        height = max(1, int(round(prob.shape[0] * width / prob.shape[1])))
        small = np.asarray(Image.fromarray(prob).resize((width, height),
                                                       Image.Resampling.BILINEAR))
        boxes = base.det_post(small, 1.0, thresh=self.thresh, expand=self.expand,
                              split_lines=self.split)
        sx, sy = image.width / width, image.height / height
        return [(x0 * sx, y0 * sy, x1 * sx, y1 * sy) for x0, y0, x1, y1 in boxes]

    def _recognise(self, image, box) -> str:
        x0, y0, x1, y1 = [int(round(v)) for v in box]
        x0, y0 = max(0, x0), max(0, y0)
        x1, y1 = min(image.width, x1), min(image.height, y1)
        if x1 - x0 < 2 or y1 - y0 < 2:
            return ""
        crop = image.crop((x0, y0, x1, y1)).convert("L")
        width = max(1, min(800, int(round(crop.width * 64 / crop.height))))
        crop = crop.resize((width, 64), Image.Resampling.BILINEAR)
        canvas = Image.new("L", (800, 64), 0)
        canvas.paste(crop, (0, 0))
        tensor = (np.asarray(canvas, np.float32) / 255.0)[None, None]
        prediction = np.asarray(self.rec.run(None, {self.rec_input: tensor})[0])[0]
        indices = prediction.argmax(axis=1)
        out, previous = [], -1
        for index in indices.tolist():
            if index != 0 and index != previous:
                out.append(EASYOCR_CHARS[index - 1])
            previous = index
        return "".join(out).strip()

    def run(self, image) -> tuple[str, dict]:
        lines = []
        for box in self._detect(image):
            text = self._recognise(image, box)
            if text:
                lines.append(text)
        return "\n".join(lines), {"rotated": False, "device": "see modules"}


class TextRecognizerCli:
    """Windows App SDK Microsoft.Windows.AI.Text.TextRecognizer, run by a C# helper.

    The helper is a separate process because PyWinRT has no projection for the
    Windows App SDK namespaces; it takes a manifest of image paths and writes
    one JSON row per image.
    """

    name = "windows_ai_textrecognizer"

    def __init__(self, exe: str | None = None):
        self.exe = exe or str(Path(r"C:\RE\bench\textrec\bin\out\textrec.exe"))
        self.providers = []

    def run_batch(self, images: list[Path], out_path: Path) -> dict:
        import subprocess

        manifest = out_path.with_suffix(".manifest.txt")
        manifest.write_text("\n".join(str(p) for p in images), encoding="utf-8")
        started = time.time()
        proc = subprocess.run([self.exe, "--manifest", str(manifest),
                               "--out", str(out_path)], capture_output=True, text=True)
        elapsed = time.time() - started
        if proc.returncode != 0:
            raise RuntimeError(f"textrec failed ({proc.returncode}): {proc.stderr[-800:]}")
        rows = {}
        for line in out_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                rows[row["path"]] = row
        return {"rows": rows, "seconds": elapsed, "stderr": proc.stderr[-400:]}


# --------------------------------------------------------------------------- #
# Driver
# --------------------------------------------------------------------------- #

def textlayer_pages(text_dir: Path):
    for pdf in sorted(text_dir.glob("*.pdf")):
        image, page, truth = base.best_text_page(pdf)
        if len(normalize(truth)) < base.MIN_TRUTH_CHARS:
            continue
        yield pdf.stem, image, page, truth


def scanned_pages(list_path: Path, base_dir: Path):
    entries = [line.split("|") for line in
               list_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    for index, (relative, page) in enumerate(entries):
        image, page_number = base.render(base_dir / relative, int(page))
        yield f"{index:02d}_{Path(relative).stem[:8]}", image, page_number, relative


def summarize(rows: list[dict], seconds: float) -> dict:
    def mean(values):
        values = [v for v in values if v is not None]
        return round(sum(values) / len(values), 4) if values else None

    out = {"pages": len(rows), "seconds": round(seconds, 2),
           "pages_per_min": round(len(rows) / seconds * 60, 2) if seconds else None,
           "accuracy": mean(r.get("accuracy") for r in rows),
           "order_free": mean(r.get("order_free") for r in rows),
           "accuracy_lines": mean(r.get("accuracy_lines") for r in rows),
           "number_recall": mean(r.get("number_recall") for r in rows),
           "by_type": {}}
    for kind in ("letter", "table", "slide", "rotated"):
        group = [r for r in rows if r.get("type") == kind or (kind == "rotated" and r.get("rotated"))]
        if group:
            out["by_type"][kind] = {
                "pages": len(group),
                "accuracy": mean(r.get("accuracy") for r in group),
                "order_free": mean(r.get("order_free") for r in group),
                "number_recall": mean(r.get("number_recall") for r in group),
            }
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", required=True,
                    choices=("qnn", "media", "textrec", "easyocr"))
    ap.add_argument("--mode", required=True, choices=("textlayer", "scanned"))
    ap.add_argument("--text-dir", default=r"C:\RE\ocr_text")
    ap.add_argument("--list", default=r"C:\RE\pages30.txt")
    ap.add_argument("--base", default=r"C:\RE\raw\pilot60_history")
    ap.add_argument("--models", default=r"C:\RE\models_fixed")
    ap.add_argument("--easyocr-dir", default=r"C:\RE\models_easyocr\easyocr-onnx-float")
    ap.add_argument("--det-provider", default="qnn-htp")
    ap.add_argument("--rec-provider", default="cpu")
    ap.add_argument("--easy-thresh", type=float, default=0.3)
    ap.add_argument("--easy-expand", type=float, default=1.4)
    ap.add_argument("--easy-split", action="store_true", default=True)
    ap.add_argument("--out", default=r"C:\RE\bench\out")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--keys", help="scanned mode: JSON {page_id: [numbers]}")
    ap.add_argument("--exe", default=None, help="textrec helper exe")
    ap.add_argument("--debug-rotate", action="store_true",
                    help="textlayer: also OCR the 90-degree turn (rotated-page group)")
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    if args.mode == "textlayer":
        pages = list(textlayer_pages(Path(args.text_dir)))
    else:
        pages = list(scanned_pages(Path(args.list), Path(args.base)))
    if args.limit:
        pages = pages[: args.limit]

    keys = json.loads(Path(args.keys).read_text(encoding="utf-8")) if args.keys else {}
    rows, started = [], time.time()

    if args.engine == "textrec":
        engine = TextRecognizerCli(args.exe)
        images = out / f"pages_{args.mode}"
        images.mkdir(exist_ok=True)
        paths = []
        for page_id, image, page, truth in pages:
            path = images / f"{page_id}.png"
            image.save(path)
            paths.append(path)
        batch = engine.run_batch(paths, out / f"textrec_{args.mode}.jsonl")
        for (page_id, image, page, truth), path in zip(pages, paths):
            row = batch["rows"].get(str(path), {})
            text = row.get("text", "")
            item = {"id": page_id, "page": page, "engine": engine.name,
                    "seconds": row.get("seconds"), "device": row.get("device", ""),
                    "rotated": bool(row.get("rotated", False)), "ocr_start": normalize(text)[:240]}
            if args.mode == "textlayer":
                item.update(score(truth, text))
                item.update(base_metrics(truth, text))
                item["type"] = page_type(truth)
            else:
                item["ocr_chars"] = len(normalize(text))
                item.update(key_score(page_id, text, keys))
            rows.append(item)
        seconds = float(batch["seconds"])
    else:
        if args.engine == "qnn":
            engine = QnnRapidOCR(args.models)
        elif args.engine == "media":
            engine = MediaOcr()
        else:
            engine = EasyOcrQnn(args.easyocr_dir, args.det_provider, args.rec_provider,
                                args.easy_thresh, args.easy_expand, args.easy_split)
        for page_id, image, page, truth in pages:
            t0, cpu0 = time.time(), time.process_time()
            text, meta = engine.run(image)
            elapsed, cpu = time.time() - t0, time.process_time() - cpu0
            item = {"id": page_id, "page": page, "engine": engine.name,
                    "seconds": round(elapsed, 3), "cpu_seconds": round(cpu, 3),
                    "device": meta.get("device", ""),
                    "modules": npu_modules(),
                    "rotated": meta.get("rotated", False),
                    "ocr_start": normalize(text)[:240]}
            if args.mode == "textlayer":
                item.update(score(truth, text))
                item.update(base_metrics(truth, text))
                item["type"] = page_type(page_id)
                if meta.get("text_by_pos"):
                    alternative = score(truth, meta["text_by_pos"])
                    item["accuracy_pos"] = alternative["accuracy"]
                    item["order_free_pos"] = alternative["order_free"]
            else:
                item["ocr_chars"] = len(normalize(text))
                item.update(key_score(page_id, text, keys))
            rows.append(item)
            print(f"{page_id:24s} {elapsed:6.2f}s  {item.get('accuracy', '')} "
                  f"{normalize(text)[:70]}", flush=True)
        seconds = time.time() - started

    summary = summarize(rows, seconds)
    summary["engine"] = engine.name
    summary["mode"] = args.mode
    summary["providers"] = getattr(engine, "providers", [])

    stem = f"{engine.name}_{args.mode}"
    rows_path = out / f"rows_{stem}.jsonl"
    rows_path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
                         encoding="utf-8")
    (out / f"summary_{stem}.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    print(rows_path)
    return 0


def base_metrics(truth: str, ocr: str) -> dict:
    _, lines, _ = base.accuracy(truth, ocr)
    return {"accuracy_lines": round(lines or 0.0, 4)}


def key_score(page_id: str, text: str, keys: dict) -> dict:
    expected = keys.get(page_id)
    if not expected:
        return {}
    found = [n for n in expected if n in numbers(text)]
    return {"key_numbers": len(expected), "key_found": len(found),
            "key_recall": round(len(found) / len(expected), 4)}


if __name__ == "__main__":
    raise SystemExit(main())
