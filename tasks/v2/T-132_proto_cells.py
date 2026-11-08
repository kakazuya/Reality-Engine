"""T-132 prototype: every printed table cell of a PDF page from word boxes (text layer), no model.

Rows from word y-centres; numeric tokens (numbers, (negatives), percents, '-') merged when split; a table block
is a run of rows with >= 2 numeric tokens (short label-only rows inside it are section labels); column anchors
cluster the right edges of the block's numbers; header = words above the block assigned to the nearest anchor.
Usage: python -I proto_cells.py <pdf> [pages like 3,5-7] [--json out.jsonl]
"""
import json
import re
import sys

import pymupdf

NUM = re.compile(r"^\(?[-–]?(?:₹|Rs\.?)?\d[\d,]*(?:\.\d+)?\)?%?$|^[-–—]$|^\(?\d*\.\d+\)?%?$")
FRAG = re.compile(r"^[\d,.()%-]+$")


def rows_of(words, tol=3.0):
    rows, cur, y = [], [], None
    for w in sorted(words, key=lambda w: ((w[1] + w[3]) / 2, w[0])):
        c = (w[1] + w[3]) / 2
        if y is None or abs(c - y) <= tol:
            cur.append(w)
            y = c if y is None else y
        else:
            rows.append(sorted(cur, key=lambda t: t[0]))
            cur, y = [w], c
    if cur:
        rows.append(sorted(cur, key=lambda t: t[0]))
    return rows


def tokens(row):
    out = []
    for w in row:
        t = w[4]
        if FRAG.match(t) and out and out[-1]["num"] and w[0] - out[-1]["x1"] <= 2.5 and not out[-1]["text"].endswith("%"):
            out[-1]["text"] += t
            out[-1]["x1"] = w[2]
            continue
        out.append({"x0": w[0], "x1": w[2], "text": t, "num": bool(FRAG.match(t)) or bool(NUM.match(t))})
    for o in out:
        o["num"] = bool(NUM.match(o["text"]))
    return out


def value(text):
    t = text.replace(",", "").replace("₹", "").replace("Rs.", "").replace("Rs", "").replace("–", "-")
    if t in ("-", "—"):
        return None
    neg = t.startswith("(") and t.endswith(")")
    t = t.strip("()").rstrip("%")
    try:
        v = float(t)
    except ValueError:
        return None
    return -v if neg else v


def anchors_of(block):
    xs = sorted(tk["x1"] for row in block for tk in row if tk["num"])
    cl = []
    for x in xs:
        if cl and x - cl[-1][-1] <= 6.0:
            cl[-1].append(x)
        else:
            cl.append([x])
    need = max(2, 0.3 * len(block))
    return [sum(c) / len(c) for c in cl if len(c) >= need]


def page_cells(page, pno):
    words = page.get_text("words")
    rows = [tokens(r) for r in rows_of(words)]
    blocks, cur, gap = [], [], 0
    for i, r in enumerate(rows):
        n = sum(t["num"] for t in r)
        if n >= 2:
            cur.append(i)
            gap = 0
        elif cur and gap < 2 and n == 0:
            cur.append(i)
            gap += 1
        else:
            if len([j for j in cur if sum(t["num"] for t in rows[j]) >= 2]) >= 2:
                blocks.append(cur)
            cur, gap = ([i] if n >= 2 else []), 0
    if len([j for j in cur if sum(t["num"] for t in rows[j]) >= 2]) >= 2:
        blocks.append(cur)
    out = []
    for tno, idx in enumerate(blocks):
        while idx and sum(t["num"] for t in rows[idx[-1]]) < 2:
            idx = idx[:-1]
        block = [rows[i] for i in idx]
        anchors = anchors_of(block)
        if len(anchors) < 1:
            continue
        gap0 = min((b - a for a, b in zip(anchors, anchors[1:])), default=60)
        # a column whose numbers are small integers left of every label is the printed row number, not data
        lab_x = [t["x0"] for r in block for t in r if not t["num"] and len(t["text"]) > 2]
        if len(anchors) > 1 and lab_x and anchors[0] < sorted(lab_x)[len(lab_x) // 2]:
            anchors = anchors[1:]
            gap0 = min((b - a for a, b in zip(anchors, anchors[1:])), default=60)
        left = anchors[0] - max(gap0, 40)
        hdr = {k: [] for k in range(len(anchors))}
        for hr in rows[max(0, idx[0] - 6): idx[0]]:
            for tk in hr:
                cx = (tk["x0"] + tk["x1"]) / 2
                if tk["x1"] < left:
                    continue
                k = min(range(len(anchors)), key=lambda a: abs(anchors[a] - tk["x1"]) if tk["num"] else abs(anchors[a] - 20 - cx))
                hdr[k].append(tk["text"])
        heads = [" ".join(hdr[k]) for k in range(len(anchors))]
        section = ""
        for rno, (i, r) in enumerate(zip(idx, block)):
            nums = [t for t in r if t["num"]]
            label = " ".join(t["text"] for t in r if t["x1"] <= left + 2 and not (t["num"] and t is r[0] and len(r) > 1))
            nums = [t for t in nums if t["x1"] > left + 2]
            if not nums:
                section = label
                continue
            gapw = min((b - a for a, b in zip(anchors, anchors[1:])), default=60)
            for t in nums:
                k = min(range(len(anchors)), key=lambda a: abs(anchors[a] - t["x1"]))
                if abs(anchors[k] - t["x1"]) > max(8, 0.45 * gapw):
                    k = -1
                out.append({"page": pno, "table_no": tno, "row_no": rno, "col_no": k,
                            "row_label": (section + " > " + label) if section and label else (label or section),
                            "col_header": heads[k] if k >= 0 else None, "value_text": t["text"], "value": value(t["text"])})
    return out


def main():
    doc = pymupdf.open(sys.argv[1])
    pages = range(len(doc))
    if len(sys.argv) > 2 and not sys.argv[2].startswith("--"):
        sel = []
        for part in sys.argv[2].split(","):
            a, _, b = part.partition("-")
            sel += list(range(int(a) - 1, int(b or a)))
        pages = sel
    allc = []
    for p in pages:
        allc += page_cells(doc[p], p + 1)
    if "--json" in sys.argv:
        with open(sys.argv[sys.argv.index("--json") + 1], "w", encoding="utf-8") as f:
            for c in allc:
                f.write(json.dumps(c, ensure_ascii=False) + "\n")
    print(f"cells {len(allc)} no_col {sum(c['col_no'] < 0 for c in allc)} no_header {sum(not c['col_header'] for c in allc)}")
    for c in allc[:int(dict(enumerate(sys.argv)).get(99, 70))]:
        print(f"p{c['page']} t{c['table_no']} r{c['row_no']} c{c['col_no']} | {c['row_label'][:40]:40} | {str(c['col_header'])[:28]:28} | {c['value_text']}")


if __name__ == "__main__":
    main()
