"""Large Windows AI TextRecognizer accuracy test on the HP OmniBook.

The engine (``Microsoft.Windows.AI.Imaging.TextRecognizer``) only answers from a
signed MSIX with package identity launched in the interactive session, so this
driver never calls it directly: it renders pages with pypdfium2, writes a
manifest, registers/starts the ``RETextRecBench`` scheduled task (interactive
logon token, action = the package execution alias), waits for the helper's
``<out>.done`` sentinel and reads the JSONL rows back.

This module is the experiment driver, not the engine helper:

* ``run`` renders a split (``tune`` or ``test``) at one DPI with one clean-up
  variant, optional tiling and optional ``ImageScaler`` upscaling, then runs the
  batch and writes ``rows.jsonl`` / ``words.jsonl`` under ``work/<name>``.
* ``score`` invokes the read-only scorer ``C:\\RE\\ocr_large\\score_large.py``.
* ``report`` tabulates number-token confidence bands and the two flag-only
  checks (letters inside numeric tokens, totals that do not add up).
* ``test`` renders and runs every test page of both kinds once and writes
  ``C:\\RE\\ocr_large\\rows\\<setting>\\test.jsonl`` and ``test_words.jsonl``.

No raw data outside ``C:\\RE\\ocr_large`` is read.  Rendering uses at most four
worker processes; the NPU batch is one process at a time.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(r"C:\RE\ocr_large")
WORK = ROOT / "work"
ROWS = ROOT / "rows"
SCORER = ROOT / "score_large.py"
TASK = "RETextRecBench"
ALIAS = Path(os.environ.get("LOCALAPPDATA", r"C:\Users\zen7s\AppData\Local")) / \
    "Microsoft" / "WindowsApps" / "textrec.exe"


def _current_user() -> str:
    """The interactive account to run the packaged helper as.

    The worker's environment is inherited from the service (USERNAME=SYSTEM),
    so the token owner, not the environment, is what the scheduled task needs.
    """
    try:
        name = subprocess.run(["whoami"], capture_output=True, text=True,
                              check=False).stdout.strip()
        if name:
            return name
    except OSError:
        pass
    return f"{os.environ.get('COMPUTERNAME', 'SUMIT_HP')}\\zen7s"


USER = _current_user()

NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")
WORD = re.compile(r"[A-Za-z]{3,}")
TOKEN = re.compile(r"[^\s]+")


# --------------------------------------------------------------------------- #
# Sample / page lists
# --------------------------------------------------------------------------- #

def load_sample() -> dict:
    return json.loads((ROOT / "sample.json").read_text(encoding="utf-8"))


def pdf_path(relative: str) -> Path:
    return ROOT / "pdf" / relative.replace("/", os.sep)


def digital_pages(split: str) -> list[dict]:
    return [p for p in load_sample()["digital"] if p["split"] == split]


def scanned_pages(split: str) -> list[dict]:
    """Every page of every scanned filing in the split, one entry per page."""
    out = []
    for doc in load_sample()["scan_docs"]:
        if doc["split"] != split:
            continue
        for page in range(doc["page_count"]):
            out.append({
                "id": f"{doc['pdf']}#{page}",
                "pdf": doc["pdf"],
                "page": page,
                "key": f"S{len(out):05d}",
                "kind": "scan",
            })
    return out


# --------------------------------------------------------------------------- #
# Image transforms (PIL + numpy only; no cv2 on this ARM64 box)
# --------------------------------------------------------------------------- #

def _deskew(image):
    from PIL import Image
    import numpy as np

    gray = image.convert("L")
    small = gray.resize((max(1, gray.width // 4), max(1, gray.height // 4)))
    best_angle, best_score = 0.0, -1.0
    for step in range(-12, 13):
        angle = step * 0.25
        rotated = np.asarray(small.rotate(angle, resample=Image.Resampling.BILINEAR,
                                          fillcolor=255), dtype=np.float32)
        score = float(rotated.mean(axis=1).var())
        if score > best_score:
            best_angle, best_score = angle, score
    if abs(best_angle) < 0.26:
        return image.convert("RGB")
    return image.rotate(best_angle, resample=Image.Resampling.BICUBIC, fillcolor=255).convert("RGB")


def variant_image(image, variant: str | None):
    """Apply one clean-up lever to a rendered page."""
    from PIL import Image, ImageFilter, ImageOps

    if not variant or variant == "none":
        return image.convert("RGB")
    if variant == "gray":
        return image.convert("L").convert("RGB")
    if variant == "contrast":
        return ImageOps.autocontrast(image.convert("L"), cutoff=1).convert("RGB")
    if variant == "unsharp":
        return image.convert("RGB").filter(
            ImageFilter.UnsharpMask(radius=1.5, percent=180, threshold=2))
    if variant == "bw":
        gray = image.convert("L")
        local = gray.filter(ImageFilter.BoxBlur(15))
        import numpy as np
        g = np.asarray(gray, dtype=np.int16)
        mean = np.asarray(local, dtype=np.int16)
        binary = np.where(g > mean - 8, 255, 0).astype("uint8")
        return Image.fromarray(binary, "L").convert("RGB")
    if variant == "deskew":
        return _deskew(image)
    raise ValueError(f"unknown variant {variant!r}")


def _render_job(job):
    key, pdf, page, dpi, out, variant = job
    import pypdfium2 as pdfium

    document = pdfium.PdfDocument(pdf)
    try:
        image = document[page].render(scale=dpi / 72).to_pil()
    finally:
        document.close()
    image = variant_image(image, variant)
    image.save(out, format="PNG")
    return key, image.size


def _tile_job(job):
    """Render a page and save overlapping tiles; return tile geometry."""
    key, pdf, page, dpi, folder, overlap = job
    import pypdfium2 as pdfium

    document = pdfium.PdfDocument(pdf)
    try:
        image = document[page].render(scale=dpi / 72).to_pil()
    finally:
        document.close()
    width, height = image.size
    base_w, base_h = width // 2, height // 2
    pad_w, pad_h = int(base_w * overlap), int(base_h * overlap)
    tiles = []
    for row in range(2):
        for col in range(2):
            x0 = max(0, col * base_w - pad_w)
            y0 = max(0, row * base_h - pad_h)
            x1 = min(width, (col + 1) * base_w + pad_w)
            y1 = min(height, (row + 1) * base_h + pad_h)
            path = Path(folder) / f"{key}_t{row}{col}.png"
            image.crop((x0, y0, x1, y1)).save(path, format="PNG")
            tiles.append({"tile": f"{key}_t{row}{col}", "path": str(path),
                          "x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0,
                          "page_w": width, "page_h": height, "key": key})
    return key, tiles


def render_pages(entries: list[dict], dpi: int, variant: str | None,
                 folder: Path, workers: int = 4, force: bool = False) -> list[dict]:
    folder.mkdir(parents=True, exist_ok=True)
    jobs = []
    for entry in entries:
        out = folder / f"{entry['key']}.png"
        if force or not out.exists():
            jobs.append((entry["key"], str(pdf_path(entry["pdf"])), entry["page"],
                         dpi, str(out), variant))
        entry["image"] = str(out)
    if jobs:
        with ProcessPoolExecutor(max_workers=min(4, workers)) as pool:
            for _ in pool.map(_render_job, jobs, chunksize=4):
                pass
    return entries


def render_tiles(entries: list[dict], dpi: int, folder: Path, overlap: float = 0.10,
                 workers: int = 4, force: bool = False) -> list[dict]:
    folder.mkdir(parents=True, exist_ok=True)
    jobs = []
    for entry in entries:
        marker = folder / f"{entry['key']}_t00.png"
        if force or not marker.exists():
            jobs.append((entry["key"], str(pdf_path(entry["pdf"])), entry["page"],
                         dpi, str(folder), overlap))
    tiles = []
    if jobs:
        with ProcessPoolExecutor(max_workers=min(4, workers)) as pool:
            for _key, produced in pool.map(_tile_job, jobs, chunksize=2):
                tiles.extend(produced)
    else:
        for entry in entries:
            for row in range(2):
                for col in range(2):
                    path = folder / f"{entry['key']}_t{row}{col}.png"
                    from PIL import Image
                    with Image.open(path) as image:
                        width, height = image.size
                    tiles.append({"tile": f"{entry['key']}_t{row}{col}",
                                  "path": str(path), "x": 0, "y": 0,
                                  "w": width, "h": height, "page_w": width,
                                  "page_h": height, "key": entry["key"]})
    return tiles


# --------------------------------------------------------------------------- #
# Packaged helper: scheduled task in the interactive session
# --------------------------------------------------------------------------- #

def _powershell(script: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        capture_output=True, text=True, check=False)


def start_batch(manifest: Path, out: Path, alias: Path = ALIAS, task: str = TASK,
                scale: int = 0, options: str | None = None) -> None:
    args = f'--manifest "{manifest}" --out "{out}"'
    if scale:
        args += f" --scale {scale}"
    if options:
        args += f" --options \"{options}\""
    script = (
        "$ErrorActionPreference='Stop'; "
        f"$a=New-ScheduledTaskAction -Execute '{alias}' -Argument '{args}'; "
        f"$p=New-ScheduledTaskPrincipal -UserId '{USER}' -LogonType Interactive -RunLevel Highest; "
        f"Register-ScheduledTask -TaskName '{task}' -Action $a -Principal $p -Force | Out-Null; "
        f"Start-ScheduledTask -TaskName '{task}'")
    result = _powershell(script)
    if result.returncode != 0:
        raise RuntimeError("task launch failed: " + result.stderr[-800:])


def wait_done(out: Path, timeout: float) -> dict:
    done = Path(str(out) + ".done")
    deadline = time.time() + timeout
    while time.time() < deadline:
        if done.exists():
            try:
                return json.loads(done.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                time.sleep(0.5)
                continue
        time.sleep(1.0)
    raise TimeoutError(f"no {done} after {timeout:.0f}s")


def run_entries(name: str, entries: list[dict], scale: int = 0,
                options: str | None = None, batch: int = 200,
                timeout_per_page: float = 8.0, alias: Path = ALIAS,
                task: str = TASK, key_field: str = "image",
                retries: int = 2) -> list[dict]:
    """Run the packaged helper over entries (each needs 'id' and key_field).

    TextRecognizer returns a sporadic NullReferenceException on a small share of
    images (observed ~0.5% of calls, unrelated to image size).  Failed rows are
    re-run in a fresh process up to ``retries`` times and replaced, so a lever
    is scored on its recognition, not on a transient engine failure.
    """
    folder = WORK / name
    folder.mkdir(parents=True, exist_ok=True)
    by_id = {entry["id"]: entry for entry in entries}
    rows: list[dict] = []
    meta = {"batches": [], "scale": scale, "options": options, "retries": 0}
    chunk_index = 0

    def run_chunk(chunk: list[dict], tag: str) -> list[dict]:
        nonlocal chunk_index
        manifest = folder / f"manifest_{chunk_index:03d}.txt"
        out = folder / f"raw_{chunk_index:03d}.jsonl"
        chunk_index += 1
        manifest.write_text("\n".join(
            json.dumps({"id": entry["id"], "path": entry[key_field]})
            for entry in chunk) + "\n", encoding="utf-8")
        for path in (out, Path(str(out) + ".done")):
            path.unlink(missing_ok=True)
        start_batch(manifest, out, alias=alias, task=task, scale=scale, options=options)
        done = wait_done(out, timeout=max(300.0, len(chunk) * timeout_per_page))
        got = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()
               if line.strip()]
        if len(got) != len(chunk):
            raise RuntimeError(f"{name} {tag}: {len(got)} rows for {len(chunk)} images")
        meta["batches"].append({"images": len(chunk), "seconds": done.get("seconds"),
                                "scale": done.get("scale"), "scaler": done.get("scaler"),
                                "modules": done.get("modules")})
        return got

    for index in range(0, len(entries), batch):
        rows.extend(run_chunk(entries[index:index + batch], f"batch {index // batch}"))
    for _ in range(retries):
        failed = [row for row in rows if row.get("error")]
        if not failed:
            break
        meta["retries"] += 1
        retry_entries = [by_id[row["id"]] for row in failed if row["id"] in by_id]
        replaced = {row["id"]: row for row in run_chunk(retry_entries, "retry")}
        rows = [replaced.get(row["id"], row) for row in rows]
    (folder / "raw.jsonl").write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8")
    (folder / "run_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return rows


def text_rows(rows: list[dict]) -> list[dict]:
    return [{"id": row["id"], "text": row.get("text") or ""} for row in rows]


def word_rows(rows: list[dict]) -> list[dict]:
    out = []
    for row in rows:
        words = []
        for line in row.get("line_rows") or []:
            words.extend(line.get("words") or [])
        out.append({"id": row["id"], "words": words})
    return out


def write_rows(name: str, rows: list[dict]) -> tuple[Path, Path]:
    folder = WORK / name
    folder.mkdir(parents=True, exist_ok=True)
    text_path = folder / "rows.jsonl"
    word_path = folder / "words.jsonl"
    text_path.write_text("\n".join(json.dumps(r, ensure_ascii=False)
                                   for r in text_rows(rows)) + "\n", encoding="utf-8")
    word_path.write_text("\n".join(json.dumps(r, ensure_ascii=False)
                                   for r in word_rows(rows)) + "\n", encoding="utf-8")
    return text_path, word_path


# --------------------------------------------------------------------------- #
# Tiles -> page
# --------------------------------------------------------------------------- #

def _norm_text(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (text or "").lower())


def _iou(a, b) -> float:
    x0 = max(a[0], b[0])
    y0 = max(a[1], b[1])
    x1 = min(a[2], b[2])
    y1 = min(a[3], b[3])
    inter = max(0.0, x1 - x0) * max(0.0, y1 - y0)
    area_a = max(1.0, (a[2] - a[0]) * (a[3] - a[1]))
    area_b = max(1.0, (b[2] - b[0]) * (b[3] - b[1]))
    return inter / (area_a + area_b - inter)


def _join_seams(lines: list[dict]) -> list[dict]:
    """Join one physical line split by a tile seam (adjacent boxes, same row)."""
    changed = True
    while changed:
        changed = False
        merged: list[dict] = []
        used = set()
        for index, line in enumerate(lines):
            if index in used:
                continue
            current = line
            for other_index in range(index + 1, len(lines)):
                if other_index in used:
                    continue
                other = lines[other_index]
                box_a, box_b = current["box"], other["box"]
                height = min(box_a[3] - box_a[1], box_b[3] - box_b[1])
                overlap = min(box_a[3], box_b[3]) - max(box_a[1], box_b[1])
                if height <= 0 or overlap < 0.6 * height:
                    continue
                if box_a[2] < box_b[0]:
                    gap, left, right = box_b[0] - box_a[2], current, other
                elif box_b[2] < box_a[0]:
                    gap, left, right = box_a[0] - box_b[2], other, current
                else:
                    continue
                if gap > 0.9 * height:
                    continue
                if _norm_text(left["text"]) in _norm_text(right["text"]) or \
                        _norm_text(right["text"]) in _norm_text(left["text"]):
                    continue
                words = sorted((left.get("words") or []) + (right.get("words") or []),
                               key=lambda word: word["box"][0])
                current = {
                    "text": (left["text"] + " " + right["text"]).strip(),
                    "box": [min(box_a[0], box_b[0]), min(box_a[1], box_b[1]),
                            max(box_a[2], box_b[2]), max(box_a[3], box_b[3])],
                    "style": left.get("style"),
                    "style_confidence": left.get("style_confidence"),
                    "words": words,
                }
                used.add(other_index)
                changed = True
            merged.append(current)
        lines = merged
    return lines


def merge_tiles(tile_rows: list[dict], tile_meta: dict[str, dict],
                page_entries: dict[str, dict]) -> list[dict]:
    """Shift tile lines into page coordinates, dedupe seams and rebuild page order."""
    per_page: dict[str, dict] = {}
    for row in tile_rows:
        meta = tile_meta.get(row["id"])
        if not meta:
            continue
        page = per_page.setdefault(meta["key"], {"lines": [], "angle": 0.0,
                                                 "page_w": meta["page_w"],
                                                 "page_h": meta["page_h"]})
        ox, oy = meta["x"], meta["y"]
        for line in row.get("line_rows") or []:
            box = line.get("box") or [0, 0, 0, 0]
            shifted = [box[0] + ox, box[1] + oy, box[2] + ox, box[3] + oy]
            words = []
            for word in line.get("words") or []:
                wb = word.get("box") or [0, 0, 0, 0]
                words.append({"text": word.get("text", ""),
                              "confidence": word.get("confidence"),
                              "box": [wb[0] + ox, wb[1] + oy,
                                      wb[2] + ox, wb[3] + oy]})
            page["lines"].append({"text": line.get("text", ""), "box": shifted,
                                  "style": line.get("style"),
                                  "style_confidence": line.get("style_confidence"),
                                  "words": words})
        if row.get("angle"):
            page["angle"] = row["angle"]

    merged = []
    for key, page in per_page.items():
        entry = page_entries[key]
        width, height = page["page_w"], page["page_h"]
        best: list[dict] = []
        for line in page["lines"]:
            x0, y0, x1, y1 = line["box"]
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            if not (0 <= cx <= width and 0 <= cy <= height) or not _norm_text(line["text"]):
                continue
            duplicate = False
            for kept in best:
                if _iou(kept["box"], line["box"]) > 0.55:
                    if len(line["text"]) > len(kept["text"]):
                        kept.update(line)
                    duplicate = True
                    break
                if _norm_text(kept["text"]) == _norm_text(line["text"]) and \
                        abs((kept["box"][0] + kept["box"][2]) / 2 - cx) < 0.5 * width and \
                        abs((kept["box"][1] + kept["box"][3]) / 2 - cy) < 0.5 * height:
                    duplicate = True
                    break
            if not duplicate:
                best.append(line)

        lines = _join_seams(best)
        # Within a visual line the engine order is left-to-right; binning by the
        # line height keeps a table row together when baselines differ by a few px.
        heights = sorted(max(1.0, line["box"][3] - line["box"][1]) for line in lines)
        bin_size = max(8.0, 0.5 * heights[len(heights) // 2]) if heights else 12.0
        lines.sort(key=lambda line: (round(line["box"][1] / bin_size), line["box"][0]))

        for line in lines:
            dedup_words = []
            for word in line.get("words") or []:
                if not any(
                        w["text"] == word["text"] and
                        abs(w["box"][0] - word["box"][0]) < 8 and
                        abs(w["box"][1] - word["box"][1]) < 8
                        for w in dedup_words):
                    dedup_words.append(word)
            line["words"] = dedup_words

        merged.append({
            "id": entry["id"],
            "path": entry.get("image", ""),
            "text": "\n".join(line["text"] for line in lines),
            "width": width,
            "height": height,
            "max_box_x": max((line["box"][2] for line in lines), default=0),
            "max_box_y": max((line["box"][3] for line in lines), default=0),
            "angle": page["angle"],
            "line_rows": lines,
            "seconds": None,
            "error": None,
            "tiles": 4,
        })
    order = {entry["key"]: index for index, entry in enumerate(page_entries.values())}
    merged.sort(key=lambda row: order.get(row.get("id"), 0))
    return merged


# --------------------------------------------------------------------------- #
# Scoring / reporting
# --------------------------------------------------------------------------- #

def score(name: str, split: str = "tune") -> dict:
    folder = WORK / name
    result = subprocess.run([sys.executable, str(SCORER), str(folder / "rows.jsonl"),
                             split, str(ROOT)], capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError("scorer failed: " + result.stderr[-1000:])
    data = json.loads(result.stdout)
    (folder / f"score_{split}.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    return data


def f1(entry: list) -> float:
    recall, precision = entry[0], entry[1]
    return 0.0 if recall + precision == 0 else 2 * recall * precision / (recall + precision)


def rank_score(data: dict) -> float:
    """One number to compare settings on the tune split (equal-weight F1)."""
    groups = [data.get("table", {}), data.get("prose", {})]
    values = []
    for group in groups:
        for field in ("numbers", "words", "roman"):
            values.append(f1(group.get(field, [0, 0, 0])))
    return round(sum(values) / len(values), 4)


def confidence_report(name: str) -> dict:
    folder = WORK / name
    words = {row["id"]: row["words"] for row in
             map(json.loads, (folder / "words.jsonl").read_text(encoding="utf-8").splitlines())}
    bands = [(0.0, 0.5), (0.5, 0.67), (0.67, 0.8), (0.8, 0.9),
             (0.9, 0.95), (0.95, 0.99), (0.99, 1.0001)]
    stats = [{"band": f"{low:g}-{high:g}", "tokens": 0, "wrong": 0} for low, high in bands]
    total = wrong = 0
    per_page = []
    for page in digital_pages("tune"):
        truth = (ROOT / "truth" / f"{page['id']}.txt").read_text(
            encoding="utf-8", errors="ignore")
        truth_numbers = {m.group().replace(",", "") for m in NUM.finditer(truth)}
        tokens = []
        for word in words.get(page["id"], []):
            text = (word.get("text") or "").strip()
            match = re.fullmatch(r"\(?(\d[\d,]*(?:\.\d+)?)\)?%?", text)
            if not match:
                continue
            value = match.group(1).replace(",", "")
            confidence = word.get("confidence")
            if confidence is None:
                continue
            tokens.append((value, float(confidence), value in truth_numbers))
        page_total = len(tokens)
        page_wrong = sum(1 for _, _, ok in tokens if not ok)
        per_page.append({"id": page["id"], "tokens": page_total, "wrong": page_wrong})
        for value, confidence, ok in tokens:
            total += 1
            wrong += 0 if ok else 1
            for index, (low, high) in enumerate(bands):
                if low <= confidence < high:
                    stats[index]["tokens"] += 1
                    stats[index]["wrong"] += 0 if ok else 1
                    break
    for item in stats:
        item["share_wrong"] = round(item["wrong"] / item["tokens"], 4) if item["tokens"] else None
    # Recompute from the raw token stream for the cut-off table.
    stream = []
    for page in digital_pages("tune"):
        truth = (ROOT / "truth" / f"{page['id']}.txt").read_text(
            encoding="utf-8", errors="ignore")
        truth_numbers = {m.group().replace(",", "") for m in NUM.finditer(truth)}
        for word in words.get(page["id"], []):
            text = (word.get("text") or "").strip()
            match = re.fullmatch(r"\(?(\d[\d,]*(?:\.\d+)?)\)?%?", text)
            if not match or word.get("confidence") is None:
                continue
            value = match.group(1).replace(",", "")
            stream.append((float(word["confidence"]), value in truth_numbers))
    cutoff_rows = []
    for cutoff in (0.5, 0.67, 0.8, 0.9, 0.95, 0.99):
        flagged = [ok for confidence, ok in stream if confidence < cutoff]
        cutoff_rows.append({
            "cutoff": cutoff,
            "share_tokens_checked": round(len(flagged) / len(stream), 4) if stream else None,
            "wrong_caught_share": round(sum(1 for ok in flagged if not ok)
                                        / max(1, wrong), 4),
        })
    report = {"name": name, "tokens": total, "wrong": wrong,
              "wrong_share": round(wrong / total, 4) if total else None,
              "bands": stats, "cutoffs": cutoff_rows}
    (folder / "confidence.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


LETTER_NUMBER = re.compile(r"^(?=.*\d)(?=.*[A-Za-z])[\dOoIlSsZzBb.,()%-]{2,8}$")
# Legitimate alphanumerics that are not digit/letter substitutions: fiscal
# labels, ordinals and unit suffixes.
ALNUM_OK = re.compile(
    r"^(?:FY\d{2,4}|Q\d(?:FY\d{2,4})?|H\d(?:FY\d{2,4})?|"
    r"\d+(?:st|nd|rd|th)|"
    r"(?:kg|mm|cm|km|ml|kw|mw|gw|kv|mt|bn|mn|crore|lakh|rs|inr|usd|bps|bp|nm))$",
    re.IGNORECASE)
NUMBER_ONLY = re.compile(r"^[\d][\d,\.]*$")


def flag_report(name: str) -> dict:
    folder = WORK / name
    words = {row["id"]: row["words"] for row in
             map(json.loads, (folder / "words.jsonl").read_text(encoding="utf-8").splitlines())}
    raw = {row["id"]: row for row in
           map(json.loads, (folder / "raw.jsonl").read_text(encoding="utf-8").splitlines())}
    letters = {"flagged": 0, "true_errors": 0, "false_alarms": 0, "examples": []}
    totals = {"flagged": 0, "true_errors": 0, "false_alarms": 0, "examples": []}
    for page in digital_pages("tune"):
        truth = (ROOT / "truth" / f"{page['id']}.txt").read_text(
            encoding="utf-8", errors="ignore")
        truth_numbers = {m.group().replace(",", "") for m in NUM.finditer(truth)}
        truth_words = {w.lower() for w in TOKEN.findall(truth)}
        for word in words.get(page["id"], []):
            text = (word.get("text") or "").strip()
            if not LETTER_NUMBER.match(text) or ALNUM_OK.match(text):
                continue
            letters["flagged"] += 1
            if text.lower() in truth_words or text.lower().strip(".,()") in truth_words:
                letters["false_alarms"] += 1
            else:
                letters["true_errors"] += 1
                if len(letters["examples"]) < 8:
                    letters["examples"].append({"page": page["id"], "token": text})
        row = raw.get(page["id"])
        if not row:
            continue
        lines = row.get("line_rows") or []
        numeric_rows = []
        for line in lines:
            values = []
            for word in line.get("words") or []:
                text = (word.get("text") or "").strip()
                if NUMBER_ONLY.match(text) and len(text) <= 18:
                    try:
                        values.append((word["box"][0], float(text.replace(",", ""))))
                    except ValueError:
                        pass
            if values:
                numeric_rows.append((line, values))
        for index, (line, values) in enumerate(numeric_rows):
            if "total" not in (line.get("text") or "").lower():
                continue
            previous = [item for item in numeric_rows[max(0, index - 6):index]]
            if len(previous) < 2:
                continue
            expected = []
            for x, _ in values:
                column = []
                for _, previous_values in previous:
                    nearest = min(previous_values, key=lambda pair: abs(pair[0] - x))
                    if abs(nearest[0] - x) < 40:
                        column.append(nearest[1])
                expected.append(sum(column) if column else None)
            bad = False
            for (_, actual), want in zip(values, expected):
                if want is None:
                    continue
                if abs(actual - want) > max(0.5, abs(want) * 0.005):
                    bad = True
            if not bad:
                continue
            totals["flagged"] += 1
            actuals = {f"{value:g}" for _, value in values}
            if actuals & truth_numbers:
                totals["false_alarms"] += 1
            else:
                totals["true_errors"] += 1
                if len(totals["examples"]) < 8:
                    totals["examples"].append({"page": page["id"],
                                               "line": (line.get("text") or "")[:80],
                                               "values": sorted(actuals)[:6]})
    report = {"name": name, "letters_in_numbers": letters, "totals": totals}
    (folder / "flags.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #

def command_run(args) -> int:
    if args.split == "tune":
        entries = digital_pages("tune") + [e for e in scanned_pages("tune")]
        for entry in entries[:len(digital_pages("tune"))]:
            entry["key"] = entry["id"]
    else:
        entries = digital_pages("test") + scanned_pages("test")
        for entry in entries[:len(digital_pages("test"))]:
            entry["key"] = entry["id"]
    if args.only == "digital":
        entries = [entry for entry in entries if entry.get("kind") != "scan"]
    elif args.only == "scan":
        entries = [entry for entry in entries if entry.get("kind") == "scan"]
    if args.limit:
        entries = entries[: args.limit]
    folder = WORK / args.name
    folder.mkdir(parents=True, exist_ok=True)
    if args.tile:
        tiles = render_tiles(entries, args.dpi, folder / "tiles", force=True)
        tile_meta = {tile["tile"]: tile for tile in tiles}
        page_entries = {entry["key"]: entry for entry in entries}
        tile_rows = run_entries(args.name, [{"id": t["tile"], "image": t["path"]}
                                            for t in tiles],
                                scale=args.scale, options=args.options,
                                alias=Path(args.alias) if args.alias else ALIAS,
                                task=args.task, key_field="image")
        rows = merge_tiles(tile_rows, tile_meta, page_entries)
        # keep the tile geometry next to the result
        (folder / "tiles.json").write_text(json.dumps(tiles, indent=2), encoding="utf-8")
    else:
        entries = render_pages(entries, args.dpi, args.variant, folder / "images",
                               force=args.force)
        rows = run_entries(args.name, entries, scale=args.scale,
                           options=args.options,
                           alias=Path(args.alias) if args.alias else ALIAS,
                           task=args.task, batch=args.batch)
    write_rows(args.name, rows)
    meta = {"name": args.name, "split": args.split, "dpi": args.dpi,
            "variant": args.variant, "tile": bool(args.tile), "scale": args.scale,
            "limit": args.limit, "only": args.only, "pages": len(entries),
            "seconds": sum(b.get("seconds") or 0 for b in
                           json.loads((folder / "run_meta.json").read_text())["batches"])
            if (folder / "run_meta.json").exists() else None}
    (folder / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(json.dumps({"name": args.name, "pages": len(entries),
                      "rows": len(rows), "meta": meta}, indent=2))
    return 0


def command_score(args) -> int:
    data = score(args.name, args.split)
    print(json.dumps({"name": args.name, "rank_score": rank_score(data),
                      "table": data.get("table"), "prose": data.get("prose"),
                      "missing_rows": data.get("missing_rows"),
                      "scan_xbrl": data.get("scan_xbrl")}, indent=2))
    return 0


def command_report(args) -> int:
    print(json.dumps(confidence_report(args.name), indent=2))
    print(json.dumps(flag_report(args.name), indent=2))
    return 0


def command_test(args) -> int:
    entries = digital_pages("test") + scanned_pages("test")
    for entry in entries[:len(digital_pages("test"))]:
        entry["key"] = entry["id"]
    folder = WORK / f"test_{args.setting}"
    folder.mkdir(parents=True, exist_ok=True)
    if args.tile:
        tiles = render_tiles(entries, args.dpi, folder / "tiles", force=True)
        tile_meta = {tile["tile"]: tile for tile in tiles}
        page_entries = {entry["key"]: entry for entry in entries}
        tile_rows = run_entries(f"test_{args.setting}",
                                [{"id": t["tile"], "image": t["path"]} for t in tiles],
                                scale=args.scale, options=args.options)
        rows = merge_tiles(tile_rows, tile_meta, page_entries)
    else:
        entries = render_pages(entries, args.dpi, args.variant, folder / "images", force=True)
        rows = run_entries(f"test_{args.setting}", entries, scale=args.scale,
                           options=args.options)
    out = ROWS / args.setting
    out.mkdir(parents=True, exist_ok=True)
    (out / "test.jsonl").write_text("\n".join(
        json.dumps(r, ensure_ascii=False) for r in text_rows(rows)) + "\n", encoding="utf-8")
    (out / "test_words.jsonl").write_text("\n".join(
        json.dumps(r, ensure_ascii=False) for r in word_rows(rows)) + "\n", encoding="utf-8")
    expected = {entry["id"] for entry in entries}
    got = {row["id"] for row in rows}
    meta = {"setting": args.setting, "dpi": args.dpi, "variant": args.variant,
            "tile": bool(args.tile), "scale": args.scale,
            "pages": len(entries), "rows": len(rows),
            "missing_ids": sorted(expected - got), "extra_ids": sorted(got - expected)}
    (out / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(json.dumps(meta, indent=2))
    return 0


def command_scan_check(args) -> int:
    """Prove one scanned page is recognised from its rendered image, not a text layer."""
    import numpy as np
    import pypdfium2 as pdfium

    doc = next(item for item in load_sample()["scan_docs"] if item["split"] == "tune")
    document = pdfium.PdfDocument(str(pdf_path(doc["pdf"])))
    try:
        page = document[args.page]
        layer = page.get_textpage().get_text_range() or ""
        image = page.render(scale=args.dpi / 72).to_pil()
    finally:
        document.close()
    folder = WORK / "scan_check"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{Path(doc['pdf']).stem}_{args.page}.png"
    image.save(path, format="PNG")
    gray = np.asarray(image.convert("L"))
    dark = float((gray < 200).mean())
    entry = {"id": f"{doc['pdf']}#{args.page}", "path": str(path), "key": "scan"}
    rows = run_entries("scan_check", [entry], batch=1, key_field="path")
    row = rows[0]
    report = {"pdf": doc["pdf"], "page": args.page, "image": str(path),
              "image_size": list(image.size), "dark_share": round(dark, 4),
              "text_layer_chars": len(layer.strip()),
              "text_layer_start": layer.strip()[:200],
              "ocr_chars": len(row["text"]), "ocr_start": row["text"][:400],
              "error": row.get("error")}
    (folder / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run")
    run.add_argument("--name", required=True)
    run.add_argument("--split", choices=("tune", "test"), default="tune")
    run.add_argument("--only", choices=("all", "digital", "scan"), default="all")
    run.add_argument("--dpi", type=int, default=200)
    run.add_argument("--variant", default="none")
    run.add_argument("--tile", action="store_true")
    run.add_argument("--scale", type=int, default=0)
    run.add_argument("--options", default=None)
    run.add_argument("--alias", default=None)
    run.add_argument("--task", default=TASK)
    run.add_argument("--limit", type=int, default=0)
    run.add_argument("--batch", type=int, default=200)
    run.add_argument("--force", action="store_true")
    run.set_defaults(func=command_run)

    sc = sub.add_parser("score")
    sc.add_argument("--name", required=True)
    sc.add_argument("--split", choices=("tune", "test"), default="tune")
    sc.set_defaults(func=command_score)

    rep = sub.add_parser("report")
    rep.add_argument("--name", required=True)
    rep.set_defaults(func=command_report)

    test = sub.add_parser("test")
    test.add_argument("--setting", required=True)
    test.add_argument("--dpi", type=int, default=200)
    test.add_argument("--variant", default="none")
    test.add_argument("--tile", action="store_true")
    test.add_argument("--scale", type=int, default=0)
    test.add_argument("--options", default=None)
    test.set_defaults(func=command_test)

    check = sub.add_parser("scan-check")
    check.add_argument("--page", type=int, default=0)
    check.add_argument("--dpi", type=int, default=300)
    check.set_defaults(func=command_scan_check)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
