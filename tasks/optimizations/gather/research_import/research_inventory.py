"""Inventory of the research library by folder (depth N) x file type, unique files only (dups from the CSV skipped)."""
import collections
import csv
import os
import sys

LP = "\\\\?\\"
root, drive, dupcsv, depth, out = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4]), sys.argv[5]
dups = {r["path"] for r in csv.DictReader(open(dupcsv, encoding="utf-8")) if r["keep"] == "dup"}
KIND = {"mp4": "video", "mkv": "video", "mov": "video", "docx": "doc", "doc": "doc", "pdf": "pdf",
        "xlsx": "sheet", "xls": "sheet", "csv": "sheet", "pptx": "deck", "png": "image", "jpg": "image",
        "jpeg": "image"}
agg = collections.defaultdict(lambda: collections.defaultdict(lambda: [0, 0]))
leaf = collections.defaultdict(set)
for base, label in ((root, ""), (drive, "[rclone] ")):
    for d, _, fs in os.walk(LP + os.path.abspath(base)):
        for f in fs:
            p = os.path.join(d, f)[len(LP):]
            if f.startswith("_") or p in dups:
                continue
            rel = os.path.relpath(p, base).split(os.sep)
            key = label + " / ".join(rel[:-1][:depth]) if len(rel) > 1 else label + "(root)"
            k = KIND.get(f.rsplit(".", 1)[-1].lower(), "other")
            a = agg[key][k]
            a[0] += 1
            a[1] += os.path.getsize(LP + p)
            if len(rel) > depth + 1:
                leaf[key].add(rel[depth])
kinds = ["doc", "pdf", "sheet", "deck", "video", "image", "other"]
with open(out, "w", encoding="utf-8") as fh:
    fh.write("| folder | " + " | ".join(kinds) + " | GB | subfolders |\n|" + "---|" * (len(kinds) + 3) + "\n")
    tot = collections.defaultdict(lambda: [0, 0])
    for key in sorted(agg):
        row = agg[key]
        gb = sum(v[1] for v in row.values()) / 1e9
        for k, v in row.items():
            tot[k][0] += v[0]
            tot[k][1] += v[1]
        fh.write(f"| {key} | " + " | ".join(str(row[k][0]) if row[k][0] else "" for k in kinds)
                 + f" | {gb:.2f} | {len(leaf[key]) or ''} |\n")
    fh.write("| **total** | " + " | ".join(str(tot[k][0]) for k in kinds)
             + f" | {sum(v[1] for v in tot.values()) / 1e9:.2f} | |\n")
    fh.write("\nGB by type: " + ", ".join(f"{k} {tot[k][1] / 1e9:.2f}" for k in kinds) + "\n")
print("rows", len(agg))
