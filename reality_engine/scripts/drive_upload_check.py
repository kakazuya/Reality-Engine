"""Which local PDFs / decks are not on Google Drive yet (2026-10-19, after the power cut stopped Shivam's browser upload).

Lists Drive folder InfoDiffusion_archive (id DRIVE_FOLDER, the 17-Oct one; a second folder with the same name holds
db_backups) through the read-only rclone remote 'gdrive_ro' (setup_gdrive_readonly.py), then compares every local file
by relative path + size (a same-name file of the same size anywhere in the area also counts). Drive folder prefixes
InfoDiffusion_to_upload/, InfoDiffusion_remaining/ and remaining_pdfs/ are all accepted, so re-uploads in new folders
are recognised.

Local areas: Downloads/InfoDiffusion_to_upload/{pdfs,decks} (hard links into the project data) and
D:/RealityEngine/pdfs. Output in reality_engine/data/drive_upload_check/: SUMMARY.txt, missing_<area>.txt,
size_mismatch_<area>.txt. With --links, the missing files are hard-linked (no extra space) into
Downloads/InfoDiffusion_remaining/{pdfs,decks} and D:/RealityEngine/remaining_pdfs, rebuilt from scratch each run,
so those folders always hold exactly what is left to upload. Do NOT use --links while run_pdf_upload.cmd is running
(it uploads from those folders).

    python -m reality_engine.scripts.drive_upload_check [--links]
"""
import argparse
import collections
import json
import os
import shutil
import subprocess
from pathlib import Path

RCLONE = r"C:\Users\warri\AppData\Local\Microsoft\WinGet\Packages\Rclone.Rclone_Microsoft.Winget.Source_8wekyb3d8bbwe\rclone-v1.75.1-windows-amd64\rclone.exe"
# 17-Oct InfoDiffusion_archive (browser uploads) and 19-Oct one created by rclone (run_pdf_upload.cmd uploads there:
# pdfs/, decks/, D_pdfs/; db_backups/ is skipped)
DRIVE_FOLDERS = ["1aSQEfkMMGmpEpDDq7tI9MH7kmNJNemTH", "1A3MOQnFsYw27Vk4DVmypfdIHR9ERydHB"]
OUT = Path(__file__).resolve().parents[1] / "data" / "drive_upload_check"
PREFIXES = ("InfoDiffusion_to_upload/", "InfoDiffusion_remaining/")
AREAS = [  # label, area, local root, remaining-links folder
    ("to_upload_pdfs", "pdfs", r"C:\Users\warri\Downloads\InfoDiffusion_to_upload\pdfs",
     r"C:\Users\warri\Downloads\InfoDiffusion_remaining\pdfs"),
    ("to_upload_decks", "decks", r"C:\Users\warri\Downloads\InfoDiffusion_to_upload\decks",
     r"C:\Users\warri\Downloads\InfoDiffusion_remaining\decks"),
    ("D_RealityEngine_pdfs", "pdfs", r"D:\RealityEngine\pdfs", r"D:\RealityEngine\remaining_pdfs"),
]


def drive_files():
    items = []
    for fid in DRIVE_FOLDERS:
        r = subprocess.run([RCLONE, "lsjson", "-R", "--files-only", "--fast-list", "--no-mimetype", "gdrive_ro:",
                            "--drive-root-folder-id", fid], capture_output=True, text=True, check=True)
        items += [x for x in json.loads(r.stdout) if not x["Path"].startswith("db_backups/")]
    exact, by_name = {}, collections.defaultdict(set)
    for x in items:
        p = x["Path"]
        for pre in PREFIXES:
            if p.startswith(pre):
                p = p[len(pre):]
        for alt in ("remaining_pdfs/", "D_pdfs/"):
            if p.startswith(alt):
                p = "pdfs/" + p[len(alt):]
        exact[p.lower()] = x["Size"]
        by_name[(p.split("/")[0], p.rsplit("/", 1)[-1].lower())].add(x["Size"])
    return exact, by_name


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--links", action="store_true")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    exact, by_name = drive_files()
    summary = [f"Drive files listed: {len(exact)}"]
    for label, area, root, dest in AREAS:
        have = miss = diff = 0
        miss_b = 0
        ml, dl = [], []
        for dp, _, fs in os.walk(root):
            for f in fs:
                full = os.path.join(dp, f)
                key = (area + "/" + os.path.relpath(full, root).replace(os.sep, "/")).lower()
                sz = os.path.getsize(full)
                if exact.get(key) == sz or sz in by_name.get((area, f.lower()), ()):
                    have += 1
                elif key in exact:
                    diff += 1; dl.append(f"{full}\t{sz}\tdrive {exact[key]}")
                else:
                    miss += 1; miss_b += sz; ml.append(full)
        (OUT / f"missing_{label}.txt").write_text("\n".join(ml), encoding="utf-8")
        (OUT / f"size_mismatch_{label}.txt").write_text("\n".join(dl), encoding="utf-8")
        summary.append(f"{label}: local {have + miss + diff}, on Drive {have}, missing {miss} "
                       f"({miss_b / 2**30:.1f} GiB), size differs {diff}")
        if a.links:
            shutil.rmtree(dest, ignore_errors=True)
            for full in ml + [x.split("\t")[0] for x in dl]:
                tgt = os.path.join(dest, os.path.relpath(full, root))
                os.makedirs(os.path.dirname(tgt), exist_ok=True)
                os.link(full, tgt)
    (OUT / "SUMMARY.txt").write_text("\n".join(summary) + "\n", encoding="utf-8")
    print("\n".join(summary))


if __name__ == "__main__":
    main()
