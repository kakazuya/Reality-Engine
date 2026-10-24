"""Draw the 200-page pilot sample from deck_figures.db (Haiku final pages), stratified by year and page type.

Page type is a deterministic proxy from Haiku's own page record, because the page type has to be known before the PDF
is fetched:
  table  n_facts >= 15   (dense grids / data tables)
  chart  6..14 facts     (bar/line charts with data labels)
  kpi    1..5 facts      (KPI tiles / single-number slides)
Pages with 0 final facts are excluded (nothing to recall). Seed is fixed.

Output: work/sample.json, work/sample.csv, work/decks.txt (rclone --files-from list).
"""
import json
import os
import random
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
from reality_engine.db.readonly import connect_ro  # noqa: E402

DATA = Path(os.environ.get("REALITY_DATA_ROOT", r"C:\Users\warri\Downloads\Info_Diffusion_Model\reality_engine\data"))
DB = DATA / "deck_figures.db"
OUT = ROOT / "work"
SEED = 20261024
N = 200
# year -> (kpi, chart, table); 25 per year plus 50 more in 2021 (63% of the universe), proportional to supply
ALLOC = {
    "2021": (23, 22, 25),
    "2022": (9, 8, 9),
    "2023": (9, 8, 9),
    "2024": (9, 8, 9),
    "2025": (9, 8, 9),
    "2026": (9, 8, 9),
}


def band(n):
    if n >= 15:
        return "table"
    if n >= 6:
        return "chart"
    if n >= 1:
        return "kpi"
    return None


def main():
    con = connect_ro(DB, timeout_s=180)
    rows = con.execute("""SELECT sha256, page_no, symbol, isin, known_at, doc_type, n_facts, text_numbers, text_chars,
                                 img_cov, primary_recall, second_recall
                          FROM pages WHERE final_model='claude-haiku-5-5' AND status='ok' AND n_facts >= 1""").fetchall()
    con.close()
    pages = [dict(zip(("sha256", "page_no", "symbol", "isin", "known_at", "doc_type", "n_facts", "text_numbers",
                       "text_chars", "img_cov", "primary_recall", "second_recall"), r)) for r in rows]
    for p in pages:
        p["year"] = (p["known_at"] or "")[:4]
        p["ptype"] = band(p["n_facts"])
    strata = defaultdict(list)
    for p in pages:
        strata[(p["year"], p["ptype"])].append(p)
    rng = random.Random(SEED)
    picked, short = [], []
    for y, alloc in ALLOC.items():
        for t, n in zip(("kpi", "chart", "table"), alloc):
            pool = sorted(strata[(y, t)], key=lambda p: (p["sha256"], p["page_no"]))
            if len(pool) < n:
                short.append((y, t, len(pool), n))
                n = len(pool)
            picked.extend(rng.sample(pool, n))
    # top up from the largest under-used cells if a cell was short
    need = N - len(picked)
    if need > 0:
        have = {(p["sha256"], p["page_no"]) for p in picked}
        rest = sorted((p for p in pages if (p["sha256"], p["page_no"]) not in have),
                      key=lambda p: (p["sha256"], p["page_no"]))
        picked.extend(rng.sample(rest, need))
    assert len(picked) == N, len(picked)

    # deck path: deck_sources.local_path -> gdrive relative path under InfoDiffusion_archive/decks
    con = connect_ro(DB)
    shas = sorted({p["sha256"] for p in picked})
    src = {}
    for i in range(0, len(shas), 500):
        chunk = shas[i:i + 500]
        q = "SELECT sha256, local_path, status FROM deck_sources WHERE sha256 IN (%s)" % ",".join("?" * len(chunk))
        for sha, lp, st in con.execute(q, chunk):
            if lp and (sha not in src or st == "ok"):
                src[sha] = lp
    con.close()
    remote = {}
    for sha, lp in src.items():
        norm = lp.replace("/", "\\")
        key = "\\data\\"
        idx = norm.lower().find(key)
        if idx < 0:
            raise SystemExit(f"cannot derive remote path from {lp}")
        remote[sha] = norm[idx + len(key):].replace("\\", "/")
    missing = [s for s in shas if s not in remote]
    if missing:
        raise SystemExit(f"{len(missing)} sampled decks have no deck_sources.local_path: {missing[:3]}")

    for p in picked:
        p["remote"] = remote[p["sha256"]]
        p["pdf"] = f"work/pdfs/{p['sha256']}.pdf"
        p["png"] = f"work/pages/{p['sha256']}_p{p['page_no']:03d}.png"
    picked.sort(key=lambda p: (p["year"], p["ptype"], p["sha256"], p["page_no"]))
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "sample.json").write_text(json.dumps(picked, indent=1), encoding="utf-8")
    with (OUT / "sample.csv").open("w", encoding="utf-8") as fh:
        fh.write("sha256,page_no,year,ptype,symbol,known_at,n_facts,text_numbers,img_cov,remote\n")
        for p in picked:
            fh.write(f"{p['sha256']},{p['page_no']},{p['year']},{p['ptype']},{p['symbol']},{p['known_at']},"
                     f"{p['n_facts']},{p['text_numbers']},{p['img_cov']},{p['remote']}\n")
    files = sorted({p["remote"] for p in picked})
    (OUT / "decks.txt").write_text("\n".join(files) + "\n", encoding="utf-8")
    print("picked", len(picked), "unique decks", len(files), "short cells", short)
    print("by year", Counter(p["year"] for p in picked))
    print("by type", Counter(p["ptype"] for p in picked))
    print("by year/type", Counter((p["year"], p["ptype"]) for p in picked))


if __name__ == "__main__":
    main()
