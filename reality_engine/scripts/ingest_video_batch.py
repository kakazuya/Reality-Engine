"""Frames + OCR + DB load for transcribed member videos (Telegram Daily Bytes etc.).

Inputs (per video id, produced earlier):
  reality_engine/data/video_cache/<id>.mp4            downloaded video (<=1080p)
  reality_engine/data/video_out/<id>/transcript.json  whisper.cpp segments (offsets in ms)
  analysis/tg_video_links.csv, analysis/yt_probe.csv  Telegram post time / topic and YouTube title

Steps: ffmpeg frame every 5 s -> drop near-duplicate frames (cv2 mean-abs-diff) -> RapidOCR ->
       raw_documents + document_chunks (transcript windows AND slide-OCR chunks, both with
       timestamp_start_sec/_end_sec) + intelligence_fts. Frames are deleted after OCR; the video
       file is deleted after a successful load only with --delete-media.

PIT: event_date = the Telegram post time (UTC ISO) - when members could first see it - with
event_source='telegram_post_ts'. The YouTube upload date is NOT used as the market-known time.

  python reality_engine/scripts/ingest_video_batch.py --ids QKVH7Y8MDKc --dry-run
  python reality_engine/scripts/ingest_video_batch.py --all [--delete-media]
  python reality_engine/scripts/ingest_video_batch.py --rollback QKVH7Y8MDKc
"""
from __future__ import annotations

import argparse
import csv
import json
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "reality_engine/data/equity_intelligence.db"
CACHE = ROOT / "reality_engine/data/video_cache"
OUT = ROOT / "reality_engine/data/video_out"
FRAME_EVERY_S = 5
DIFF_THRESHOLD = 6.0          # mean abs pixel diff (0-255, 64x36 grayscale) to keep a frame
TRANSCRIPT_WINDOW_MS = 75_000  # aggregate whisper segments into ~75 s chunks
MIN_OCR_CHARS = 25


def _meta():
    links = {}
    for r in csv.DictReader(open(ROOT / "analysis/tg_video_links.csv", encoding="utf-8")):
        links.setdefault(r["video_id"], r)   # first (earliest listed = newest) occurrence
    titles = {r["video_id"]: r for r in csv.DictReader(open(ROOT / "analysis/yt_probe.csv", encoding="utf-8"))}
    return links, titles


def extract_kept_frames(video: Path, workdir: Path):
    """Return [(t_seconds, jpg_path)] for frames that differ from the last kept one."""
    import cv2
    pattern = workdir / "f_%05d.jpg"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(video), "-vf",
                    f"fps=1/{FRAME_EVERY_S},scale=1280:-2", "-q:v", "3", str(pattern)], check=True)
    kept, last = [], None
    for i, p in enumerate(sorted(workdir.glob("f_*.jpg"))):
        img = cv2.imread(str(p), cv2.IMREAD_GRAYSCALE)
        small = cv2.resize(img, (64, 36)).astype("float32")
        if last is None or float(abs(small - last).mean()) > DIFF_THRESHOLD:
            kept.append((i * FRAME_EVERY_S, p))
            last = small
    return kept


def ocr_frames(kept):
    from rapidocr_onnxruntime import RapidOCR
    engine = RapidOCR()
    out = []
    for t, p in kept:
        res, _ = engine(str(p))
        if not res:
            continue
        text = " ".join(r[1] for r in res if float(r[2]) >= 0.5).strip()
        if len(text) >= MIN_OCR_CHARS:
            out.append((t, text[:1500]))
    return out


def transcript_chunks(vid: str):
    segs = json.load(open(OUT / vid / "transcript.json", encoding="utf-8", errors="replace"))["transcription"]  # whisper can split a multibyte char
    chunks, cur, start = [], [], None
    for s in segs:
        a, b, txt = s["offsets"]["from"], s["offsets"]["to"], s["text"].strip()
        if not txt:
            continue
        if start is None:
            start = a
        cur.append(txt)
        if b - start >= TRANSCRIPT_WINDOW_MS:
            chunks.append((start // 1000, b // 1000, " ".join(cur)))
            cur, start = [], None
    if cur:
        chunks.append((start // 1000, segs[-1]["offsets"]["to"] // 1000, " ".join(cur)))
    return chunks


def load(conn, vid, meta, title_row, tchunks, slides):
    sha = f"yt:{vid}"
    if conn.execute("SELECT 1 FROM raw_documents WHERE sha256_hash=?", (sha,)).fetchone():
        return "exists"
    posted = meta["posted_utc"]
    topic = meta["topic"]
    title = (title_row or {}).get("title") or vid
    src_type = "YouTube_" + topic.replace(" ", "").replace("-", "")
    conn.execute(
        "INSERT INTO raw_documents (title, source_type, published_date, source_url, creator_or_ministry, sha256_hash,"
        " event_date, event_source, doc_version) VALUES (?,?,?,?,?,?,?,?,1)",
        (title, src_type, posted[:10], f"https://youtu.be/{vid}",
         f"Financially Free / {topic} (Telegram msg {meta['message_id']})", sha, posted, "telegram_post_ts"))
    doc_id = conn.execute("SELECT doc_id FROM raw_documents WHERE sha256_hash=?", (sha,)).fetchone()[0]
    rows = [(a, b, f"[Metadata: Symbol:  | Doc: {src_type} | Date: {posted[:10]} | t={a}s-{b}s]\n{txt}", "transcript")
            for a, b, txt in tchunks]
    rows += [(t, t + FRAME_EVERY_S, f"[Metadata: Symbol:  | Doc: {src_type}_SLIDE | Date: {posted[:10]} | t={t}s]\n[SLIDE OCR] {txt}", "slide")
             for t, txt in slides]
    for idx, (a, b, content, kind) in enumerate(rows):
        chunk_index = idx if kind == "transcript" else 100000 + idx
        conn.execute(
            "INSERT OR IGNORE INTO document_chunks (doc_id, chunk_index, content, published_date, timestamp_start_sec,"
            " timestamp_end_sec, symbol, isin, event_date, event_source, doc_version) VALUES (?,?,?,?,?,?,?,?,?,?,1)",
            (doc_id, chunk_index, content, posted[:10], a, b, "", "", posted, "telegram_post_ts"))
        cid = conn.execute("SELECT chunk_id FROM document_chunks WHERE doc_id=? AND chunk_index=?", (doc_id, chunk_index)).fetchone()[0]
        conn.execute(
            "INSERT INTO intelligence_fts(chunk_id, symbol, isin, source_type, document_date, document_text) VALUES (?,?,?,?,?,?)",
            (str(cid), "", "", src_type if kind == "transcript" else src_type + "_SLIDE", posted[:10], content))
    return f"loaded doc_id={doc_id} transcript_chunks={len(tchunks)} slide_chunks={len(slides)}"


def rollback(conn, vid):
    row = conn.execute("SELECT doc_id FROM raw_documents WHERE sha256_hash=?", (f"yt:{vid}",)).fetchone()
    if not row:
        return "nothing to roll back"
    doc_id = row[0]
    cids = [str(r[0]) for r in conn.execute("SELECT chunk_id FROM document_chunks WHERE doc_id=?", (doc_id,))]
    conn.executemany("DELETE FROM intelligence_fts WHERE chunk_id=?", [(c,) for c in cids])
    conn.execute("DELETE FROM document_chunks WHERE doc_id=?", (doc_id,))
    conn.execute("DELETE FROM raw_documents WHERE doc_id=?", (doc_id,))
    return f"removed doc {doc_id} and {len(cids)} chunks"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", default="")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--delete-media", action="store_true")
    ap.add_argument("--rollback", default="")
    a = ap.parse_args()
    conn = sqlite3.connect(DB, timeout=600)
    if a.rollback:
        with conn:
            print(rollback(conn, a.rollback))
        return 0
    links, titles = _meta()
    ids = [v for v in a.ids.split(",") if v] if a.ids else sorted(p.parent.name for p in OUT.glob("*/transcript.json")) if a.all else []
    for vid in ids:
        if not (OUT / vid / "transcript.json").exists() or not (CACHE / f"{vid}.mp4").exists():
            print(vid, "skip (missing transcript or video)")
            continue
        tmp = Path(tempfile.mkdtemp(prefix="frames_"))
        try:
            kept = extract_kept_frames(CACHE / f"{vid}.mp4", tmp)
            slides = ocr_frames(kept)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        tchunks = transcript_chunks(vid)
        msg = f"kept_frames={len(kept)} slide_ocr={len(slides)} transcript_chunks={len(tchunks)}"
        if a.dry_run:
            print(vid, "DRY", msg)
            continue
        with conn:
            res = load(conn, vid, links[vid], titles.get(vid), tchunks, slides)
        print(vid, res, msg, flush=True)
        if a.delete_media and res.startswith("loaded"):
            (CACHE / f"{vid}.mp4").unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
