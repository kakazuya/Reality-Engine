"""Replace sampled pages whose deck is absent from the gdrive archive, same year x page-type stratum, new fixed seed.

Appends replacements to work/sample.json and writes work/decks_topup.txt for rclone.
"""
import argparse
import json
import os
import random
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
from reality_engine.db.readonly import connect_ro  # noqa: E402

WORK = ROOT / "work"
DATA = Path(os.environ.get("REALITY_DATA_ROOT", r"C:\Users\warri\Downloads\Info_Diffusion_Model\reality_engine\data"))
SEED = 20261025


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only-sha", help="replace only the page from this deck (a replacement that was also missing)")
    args = ap.parse_args()
    sample = json.loads((WORK / "sample.json").read_text(encoding="utf-8"))
    rendered = json.loads((WORK / "pages.json").read_text(encoding="utf-8"))
    have = {(p["sha256"], p["page_no"]) for p in rendered}
    missing = [p for p in sample if (p["sha256"], p["page_no"]) not in have]
    if args.only_sha:
        missing = [p for p in missing if p["sha256"] == args.only_sha]
    print("missing", len(missing), Counter((p["year"], p["ptype"]) for p in missing))
    con = connect_ro(DATA / "deck_figures.db", timeout_s=180)
    used = {(p["sha256"], p["page_no"]) for p in sample}
    rng = random.Random(SEED)
    new = []
    for m in missing:
        rows = con.execute("""SELECT sha256, page_no, symbol, isin, known_at, doc_type, n_facts, text_numbers,
                                     text_chars, img_cov, primary_recall, second_recall
                              FROM pages WHERE final_model='claude-haiku-5-5' AND status='ok' AND n_facts >= 1
                                AND substr(known_at,1,4)=? AND ((?='table' AND n_facts>=15) OR (?='chart' AND n_facts BETWEEN 6 AND 14)
                                OR (?='kpi' AND n_facts BETWEEN 1 AND 5))""", (m["year"], m["ptype"], m["ptype"], m["ptype"])).fetchall()
        pool = []
        for r in rows:
            p = dict(zip(("sha256", "page_no", "symbol", "isin", "known_at", "doc_type", "n_facts", "text_numbers",
                          "text_chars", "img_cov", "primary_recall", "second_recall"), r))
            if (p["sha256"], p["page_no"]) in used:
                continue
            p["year"], p["ptype"] = m["year"], m["ptype"]
            pool.append(p)
        pool.sort(key=lambda p: (p["sha256"], p["page_no"]))
        pick = rng.choice(pool)
        used.add((pick["sha256"], pick["page_no"]))
        new.append(pick)
    # map to gdrive paths
    shas = sorted({p["sha256"] for p in new})
    src = {}
    for sha in shas:
        r = con.execute("SELECT local_path FROM deck_sources WHERE sha256=? AND local_path IS NOT NULL LIMIT 1", (sha,)).fetchone()
        if r:
            src[sha] = r[0]
    con.close()
    for p in new:
        norm = src[p["sha256"]].replace("/", "\\")
        p["remote"] = norm[norm.lower().find("\\data\\") + len("\\data\\"):].replace("\\", "/")
        p["pdf"] = f"work/pdfs/{p['sha256']}.pdf"
        p["png"] = f"work/pages/{p['sha256']}_p{p['page_no']:03d}.png"
    sample.extend(new)
    (WORK / "sample.json").write_text(json.dumps(sample, indent=1), encoding="utf-8")
    (WORK / "decks_topup.txt").write_text("\n".join(sorted({p["remote"] for p in new})) + "\n", encoding="utf-8")
    print("added", len(new), "unique decks", len({p["remote"] for p in new}))
    for p in new:
        print(p["year"], p["ptype"], p["symbol"], p["page_no"], p["remote"])


if __name__ == "__main__":
    main()
