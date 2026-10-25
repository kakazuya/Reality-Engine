"""Which local PDFs / decks are safe to delete? (Shivam 2026-10-20: free the PC disk; the laptop is the workstation.)

Lists every file in both Drive archive folders through the read-only remote 'gdrive_ro' (sees browser uploads and both
rclone clients' uploads) with Drive's MD5, then MD5-hashes each local candidate and matches it by file name + size + MD5
(paths differ between upload batches, so the name is the key, never the folder). Candidates: PDFS_DIR
(D:\\RealityEngine\\pdfs) except CONCALL_TRANSCRIPT (the readers still need those), and the D decks folder. Writes
data/logs/cleanup_verified.txt (one local path per line, safe to delete) and cleanup_unverified.txt (kept), and prints
totals. Read-only: deletes nothing.

    python -m reality_engine.scripts.cleanup_verify
"""
import hashlib
import json
import os
import subprocess
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from reality_engine.config import PDFS_DIR, raw_dir

from reality_engine.scripts.drive_upload_check import DRIVE_FOLDERS, RCLONE

DATA = Path(__file__).resolve().parents[1] / "data"
LOGS = DATA / "logs"
AREAS = list(dict.fromkeys([PDFS_DIR, raw_dir("decks")]))
KEEP_TYPES = {"CONCALL_TRANSCRIPT"}


def drive_index():
    idx = defaultdict(set)   # name -> {(size, md5)}
    for fid in DRIVE_FOLDERS:
        r = subprocess.run([RCLONE, "lsjson", "-R", "--files-only", "--fast-list", "--no-mimetype", "--hash",
                            "--hash-type", "md5", "gdrive_ro:", "--drive-root-folder-id", fid],
                           capture_output=True, text=True, check=True)
        for f in json.loads(r.stdout):
            md5 = (f.get("Hashes") or {}).get("md5")
            if md5:
                idx[f["Name"]].add((f["Size"], md5))
    return idx


def md5(path):
    h = hashlib.md5()
    with open(path, "rb") as fh:
        for b in iter(lambda: fh.read(4 << 20), b""):
            h.update(b)
    return h.hexdigest()


def main():
    idx = drive_index()
    print(f"Drive files with md5: {sum(len(v) for v in idx.values())}", flush=True)
    cands = []
    for area in AREAS:
        for dp, _, fn in os.walk(area):
            if area.name == "pdfs" and any(t in Path(dp).parts for t in KEEP_TYPES):
                continue
            cands += [Path(dp) / f for f in fn]

    def judge(p):
        try:
            size = p.stat().st_size
            ok = any(s == size for s, _ in idx.get(p.name, ())) and (size, md5(p)) in idx[p.name]
            return p, size, ok
        except OSError:
            return p, 0, False

    good, bad = [], []
    with ThreadPoolExecutor(4) as ex:
        for i, (p, size, ok) in enumerate(ex.map(judge, cands), 1):
            (good if ok else bad).append((p, size))
            if i % 5000 == 0:
                print(f"  {i}/{len(cands)} checked", flush=True)
    (LOGS / "cleanup_verified.txt").write_text("\n".join(str(p) for p, _ in good), encoding="utf-8")
    (LOGS / "cleanup_unverified.txt").write_text("\n".join(str(p) for p, _ in bad), encoding="utf-8")
    for name, rows in (("verified (safe to delete)", good), ("NOT verified (kept)", bad)):
        by = defaultdict(lambda: [0, 0])
        for p, s in rows:
            key = f"{p.drive}{'decks' if 'decks' in p.parts else 'pdfs'}"
            by[key][0] += 1; by[key][1] += s
        print(name, {k: f"{n} files {s / 1e9:.1f} GB" for k, (n, s) in by.items()})


if __name__ == "__main__":
    main()
