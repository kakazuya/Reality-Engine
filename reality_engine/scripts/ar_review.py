"""Annual-report extraction review, run after every 200 newly finished reports (Shivam 2026-10-13: "keep optimizing after
every 200 annual reports; we are writing a lot of boilerplate junk that can be cut out by CPU rules or ignored by the
models"). Started by the resource watchdog; safe to run by hand: python -m reality_engine.scripts.ar_review [--sample 60]

Report -> tasks/ar_study/reviews/review_<done>_<date>.md:
1. Boilerplate items: the most frequent normalised fact items (digits removed) and their share of all facts.
2. Repeats: facts whose item+value+period also appear in the same company's previous-year report.
3. Dead sections (CPU skip candidates): for a sample of finished reports, each page's heading (first text line) vs the
   facts that page produced. Headings seen on >= 30 pages that average < 0.2 facts/page are proposed as skip rules, with
   the share of all sampled facts a skip would lose. Nothing is applied automatically.
"""
import argparse
import random
import re
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "reality_engine" / "data" / "ar_facts.db"
OUT = ROOT / "tasks" / "ar_study" / "reviews"


def norm_item(s):
    s = re.sub(r"\d[\d,./%-]*", "#", (s or "").lower())
    return re.sub(r"\s+", " ", re.sub(r"[^a-z# ]", " ", s)).strip()[:80]


def heading(text, running=frozenset()):
    """First meaningful line of a page, skipping the report's running headers/footers (lines on >= 20% of its pages)."""
    for line in text.splitlines():
        t = re.sub(r"\s+", " ", line).strip()
        if re.sub(r"\d+", "#", t.lower()) in running:
            continue
        if len(t) >= 6 and re.search(r"[A-Za-z]{3}", t) and not re.fullmatch(r"[\d\s.,()%-]+", t):
            return re.sub(r"\d+", "#", t.lower())[:60]
    return "(none)"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=60)
    a = ap.parse_args()
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=120)
    done = c.execute("SELECT COUNT(*) FROM ar_docs WHERE status='done'").fetchone()[0]
    n_facts = c.execute("SELECT COUNT(*) FROM ar_facts").fetchone()[0]
    lines = [f"# AR extraction review at {done} finished reports ({datetime.now():%Y-%m-%d %H:%M})", "",
             f"Facts stored: {n_facts:,}.", ""]

    # 1. boilerplate items
    # 2026-10-15: full scans of ~3M facts ran for hours and blocked the WAL checkpoint; review the latest 300k facts
    lo = (c.execute("SELECT MAX(rowid) FROM ar_facts").fetchone()[0] or 0) - 300_000
    cnt = Counter()
    for (item,) in c.execute("SELECT item FROM ar_facts WHERE rowid > ?", (lo,)):
        cnt[norm_item(item)] += 1
    lines += ["## 1. Most frequent fact items (digits masked)", "", "| item | facts | share |", "|---|---|---|"]
    lines += [f"| {k} | {v:,} | {v / max(1, sum(cnt.values())):.2%} |" for k, v in cnt.most_common(40)]

    # 2. repeats vs previous year (same isin, fiscal year - 1, same item+value+period)
    # sampled: 20k recent numeric facts, each looked up in the same company's previous-year facts (isin index)
    rep = c.execute("""WITH a AS (SELECT isin, CAST(substr(fiscal_year,1,4) AS INT) fy, lower(item) it, value_raw v, period p
                         FROM ar_facts WHERE rowid > ? AND value_raw IS NOT NULL LIMIT 20000)
                       SELECT COUNT(*) FROM a WHERE EXISTS (SELECT 1 FROM ar_facts b WHERE b.isin=a.isin
                         AND CAST(substr(b.fiscal_year,1,4) AS INT)=a.fy-1 AND lower(b.item)=a.it AND b.value_raw=a.v AND b.period=a.p)""",
                    (lo,)).fetchone()[0]
    num = 20000
    lines += ["", "## 2. Year-over-year repeats", "",
              f"{rep:,} of {num:,} numeric facts ({rep / max(1, num):.1%}) repeat the same company's previous-year report "
              "(same item, value and period: mostly last year's comparative column)."]

    # 3. dead sections on a sample of finished reports
    docs = c.execute("SELECT doc_id, path FROM ar_docs WHERE status='done' AND n_pieces > 0").fetchall()
    random.seed(done); docs = random.sample(docs, min(a.sample, len(docs)))
    per_head, pages_head, total = defaultdict(int), defaultdict(int), 0
    zero_pages = text_pages = 0; dens = defaultdict(lambda: [0, 0])
    for doc_id, path in docs:
        facts = Counter(p for (p,) in c.execute("SELECT page FROM ar_facts WHERE doc_id=?", (doc_id,)) if p)
        total += sum(facts.values())
        try:
            pdf = pymupdf.open(path)
        except Exception:
            continue
        texts = [pdf[i].get_text() for i in range(len(pdf))]
        pdf.close()
        freq = Counter(k for t in texts for k in {re.sub(r"\d+", "#", re.sub(r"\s+", " ", l).strip().lower())
                                                    for l in t.splitlines() if l.strip()})
        running = frozenset(k for k, v in freq.items() if v >= max(5, 0.2 * len(texts)))
        for i, t in enumerate(texts):
            if len(t.strip()) < 40:
                continue
            h = heading(t, running); pages_head[h] += 1; per_head[h] += facts.get(i + 1, 0)
            zero_pages += facts.get(i + 1, 0) == 0; text_pages += 1
            digits = len(re.findall(r"\d", t))
            band = "0-20 digits" if digits <= 20 else "21-100" if digits <= 100 else "101-400" if digits <= 400 else ">400"
            dens[band][0] += 1; dens[band][1] += facts.get(i + 1, 0)
    cand = sorted(((h, n, per_head[h]) for h, n in pages_head.items() if n >= 30 and per_head[h] / n < 0.2),
                  key=lambda x: -x[1])
    lines += ["", f"## 3. Dead sections (sample of {len(docs)} finished reports, {total:,} facts)", "",
              "Headings on >= 30 pages averaging < 0.2 facts/page: candidate CPU skip rules.", "",
              "| heading | pages | facts there | facts/page | share of sampled facts lost |", "|---|---|---|---|---|"]
    lines += [f"| {h} | {n} | {f} | {f / n:.2f} | {f / max(1, total):.2%} |" for h, n, f in cand[:40]]
    lines += ["", f"Pages that produced no fact: {zero_pages:,} of {text_pages:,} text pages ({zero_pages / max(1, text_pages):.1%}).", "",
              "| digits on page | pages | facts | facts/page |", "|---|---|---|---|"]
    lines += [f"| {b} | {n:,} | {f:,} | {f / max(1, n):.2f} |" for b, (n, f) in sorted(dens.items())]
    pages_all = sum(pages_head.values()); pages_cand = sum(n for _, n, _ in cand); lost = sum(f for _, _, f in cand)
    lines += ["", f"Skipping all of them: {pages_cand:,} of {pages_all:,} text pages ({pages_cand / max(1, pages_all):.1%}) "
              f"for {lost:,} facts ({lost / max(1, total):.2%}) lost. Apply only rules that lose < 0.5% of facts."]
    OUT.mkdir(parents=True, exist_ok=True)
    f = OUT / f"review_{done}_{datetime.now():%Y%m%d_%H%M}.md"
    f.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f)


if __name__ == "__main__":
    main()
