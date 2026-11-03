"""Oracle report for T-049 B/E (reality_engine/pilot3/kpi_oracle.py): compare kpi_series / transcript_statement with the gap loop's check-passing answers.

python -m reality_engine.pilot3.kpi_oracle [--kpi .tmp/pilot3_kpi.db] [--tr .tmp/pilot3_tr.db] [--sample 40] [--detail]
Test set = questions mapped to kpi_series (K) or transcript_statement (T) in T048_QUESTION_COVERAGE_2026-11-03.xlsx.
Oracle = newest answers row per qid with status answered in the three sandbox dbs (answer_json.numbers / sources).
"""
import argparse
import json
import random
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from reality_engine.pilot3 import kpi, transcripts  # noqa: E402

SANDBOX = Path("D:/RealityEngine/sandbox")
COV = ROOT / "tasks/arch_v4/T048_QUESTION_COVERAGE_2026-11-03.xlsx"
SYMS = {"KEC": "kec", "BAJFINANCE": "bajfinance", "HINDALCO": "hindalco"}
TOL = 0.005


def coverage():
    import openpyxl
    ws = openpyxl.load_workbook(COV, read_only=True)["questions_300"]
    out = {}
    for r in list(ws.iter_rows(values_only=True))[1:]:
        t = str(r[6])
        tag = "K" if "kpi_series" in t else ("T" if "transcript_statement" in t else None)
        if tag:
            out[r[1]] = (tag, r[0], r[3])
    return out


def oracle_answers(sym):
    c = sqlite3.connect(f"file:{(SANDBOX / (SYMS[sym] + '_loop') / (SYMS[sym] + '.db')).as_posix()}?mode=ro", uri=True)
    res = {}
    for qid, status, aj in c.execute("SELECT qid, status, answer_json FROM answers ORDER BY round, rowid"):
        res[qid] = (status, aj)
    docs = c.execute("SELECT max(known_at) FROM docs WHERE doc_type IN ('deck','results','press_release','annual_report')").fetchone()[0]
    try:   # decks_full PDFs on disk are read by kpi.py too: a source is "newer than the held PDFs" only beyond those
        for sha, kn in c.execute("SELECT sha256, max(known_at) FROM deck_figures GROUP BY sha256"):
            if (kpi.RAW_ROOT / "decks_full" / sha[:2] / f"{sha}.pdf").exists() and kn and (not docs or kn > docs):
                docs = kn
    except sqlite3.Error:
        pass
    return {q: json.loads(a) for q, (s, a) in res.items() if s == "answered"}, docs


def canon_value(v, unit):
    """-> (value, family) with crore/usd_mn/kt/pct/bps/days/x families so scales compare."""
    u = (unit or "").lower()
    if u in ("inr_cr", "crore", "cr", "inr crore"):
        return v, "inr_cr"
    if u in ("inr_mn", "inr_million", "million_inr"):
        return v / 10.0, "inr_cr"
    if u in ("usd_mn", "usd_million", "usd mn"):
        return v, "usd_mn"
    if u in ("usd_bn", "usd_billion"):
        return v * 1000.0, "usd_mn"
    if u in ("kt", "kilotonnes", "thousand_tonnes"):
        return v, "kt"
    if u in ("tonnes", "tonne", "t"):
        return v / 1000.0, "kt"
    if u in ("mt", "million_tonnes"):
        return v * 1000.0, "kt"
    if u in ("pct", "percent", "%"):
        return v, "pct"
    if u in ("count_mn", "mn", "million", "count_million"):
        return v, "count_mn"
    return v, u


def close(a, b):
    return abs(a - b) <= TOL * max(abs(a), abs(b), 1e-9)


def row_close(r, v, metric=""):
    """A stored row matches an oracle value at 0.5%, or within half a unit of the row's last printed decimal
    (4.6 printed in the deck matches 4.56 of the annual report), or - for a bps metric - when the oracle holds percent."""
    x = canon_value(r[3], r[4])[0]
    if close(x, v) or (metric.endswith("_bps") and close(x, v * 100.0)):
        return True
    m = re.search(r"\.(\d+)", str(r[11] or ""))
    half = 0.5 * 10 ** -(len(m.group(1)) if m else 0) if r[4] in ("pct", "x", "usd_mn", "inr_cr") else 0.0
    return half > 0 and abs(x - v) <= half + 1e-9


def period_ok(oracle_per, row_per):
    if oracle_per is None:
        return True
    if oracle_per == row_per:
        return True
    return oracle_per.startswith("FY") and row_per == "Q4" + oracle_per


def fy_sum_hit(rows_by, sym, metric, fy, v):
    """F_FY_SUM: the oracle's fiscal-year value equals the sum of four stored quarters of one segment (best tier each)."""
    yy = fy[2:4]
    by_dim = defaultdict(dict)
    for r in rows_by[(sym, metric)]:
        m = re.fullmatch(r"Q([1-4])FY" + yy, r[5])
        if m:
            q = int(m.group(1))
            cur = by_dim[r[2]].get(q)
            if cur is None or r[10] > cur[10]:
                by_dim[r[2]][q] = r
    return any(len(qs) == 4 and close(sum(canon_value(r[3], r[4])[0] for r in qs.values()), v) for qs in by_dim.values())


def run_kpi(args):
    entries, dims = kpi.load_lexicon()
    cov = coverage()
    con = sqlite3.connect(args.kpi)
    rows_by = defaultdict(list)
    has_conf = any(c[1] == "conf_rank" for c in con.execute("PRAGMA table_info(kpi_series)"))
    conf = "conf_rank" if has_conf else ("CASE extractor_rule WHEN 'table_v1' THEN 4 WHEN 'chart_v1' THEN 3 "
                                         "WHEN 'sentence_default_v1' THEN 1 ELSE 2 END")      # older dbs: rank by rule
    for r in con.execute(f"SELECT symbol, metric, dimension, value, unit, fiscal_period, doc_key, page, extractor_rule, known_at, {conf}, raw_value FROM kpi_series"):
        rows_by[(r[0], r[1])].append(r)
    table = defaultdict(Counter)
    detail = []
    for sym in SYMS:
        ans, last_pdf = oracle_answers(sym)
        for qid, (tag, comp, qtext) in cov.items():
            if tag != "K" or comp != sym or qid not in ans:
                continue
            for n in ans[qid].get("numbers", []):
                measure = str(n.get("measure", ""))
                hits = kpi.label_matches(entries, sym, measure)
                if not hits or not isinstance(n.get("value"), (int, float)):
                    table["(unmapped label)"]["oracle"] += 1
                    table["(unmapped label)"]["unmapped"] += 1
                    continue
                e = hits[0][0]
                key = e.metric
                pers = kpi.parse_periods(str(n.get("period", "")))
                opn = pers[0].canon if pers else None
                v, fam = canon_value(float(n["value"]), n.get("unit"))
                table[key]["oracle"] += 1
                cands = [r for r in rows_by[(sym, e.metric)] if period_ok(opn, r[5])]
                ok = [r for r in cands if row_close(r, v, e.metric)]
                if cands:
                    top = max(r[10] for r in cands)
                    top_rows = [r for r in cands if r[10] == top]
                    table[key]["top_rows"] += len(top_rows)
                    table[key]["all_rows"] += len(cands)
                    if any(row_close(r, v, e.metric) for r in top_rows):
                        table[key]["top_repro"] += 1       # the best-confidence tier already holds the oracle value
                if ok:
                    table[key]["reproduced"] += 1
                elif cands:
                    table[key]["mismatched"] += 1
                    detail.append(f"MISMATCH {qid} {key} {opn}: oracle {v:g} ({n.get('table')}#{n.get('rowid')}) vs "
                                  + "; ".join(f"{r[3]:g}@{r[5]}/{r[2]} {r[6][-12:]}p{r[7]}" for r in cands[:2]))
                elif opn and opn.startswith("FY") and fy_sum_hit(rows_by, sym, e.metric, opn, v):
                    table[key]["reproduced"] += 1
                    table[key]["by_fy_sum"] += 1
                else:
                    kn = str(n.get("known_at") or "")
                    newer = bool(kn) and last_pdf and kn > last_pdf
                    table[key]["missed_source_newer" if newer else "missed"] += 1
                    if args.detail:
                        detail.append(f"MISSED {qid} {key} {opn} {v:g} ({n.get('table')}) {'[source newer than held pdfs]' if newer else ''}")
    print(f"{'KPI':28} {'oracle':>6} {'repro':>6} {'mism':>5} {'miss':>5} {'miss-newsrc':>11} {'unmapped':>8}  repro%  top-tier-repro  rows/num(top,all)")
    tot = Counter()
    for k, c in sorted(table.items(), key=lambda kv: -kv[1]["oracle"]):
        print(f"{k:28} {c['oracle']:6} {c['reproduced']:6} {c['mismatched']:5} {c['missed']:5} {c['missed_source_newer']:11} {c['unmapped']:8}  "
              f"{100 * c['reproduced'] / max(c['oracle'], 1):5.0f}%  {c['top_repro']:14}  {c['top_rows'] / max(c['reproduced'] + c['mismatched'], 1):.1f},{c['all_rows'] / max(c['reproduced'] + c['mismatched'], 1):.1f}")
        tot.update(c)
    print(f"{'TOTAL':28} {tot['oracle']:6} {tot['reproduced']:6} {tot['mismatched']:5} {tot['missed']:5} {tot['missed_source_newer']:11} {tot['unmapped']:8}  "
          f"{100 * tot['reproduced'] / max(tot['oracle'], 1):5.0f}%")
    print(f"{tot['by_fy_sum']} of the reproduced numbers are fiscal-year sums of four stored quarters (formula F_FY_SUM)")
    print(f"best-confidence tier reproduces {tot['top_repro']} of {tot['reproduced']} reproduced numbers; candidate rows per number: "
          f"{tot['top_rows'] / max(tot['reproduced'] + tot['mismatched'], 1):.1f} in the top tier, {tot['all_rows'] / max(tot['reproduced'] + tot['mismatched'], 1):.1f} in all")
    heldable = tot["oracle"] - tot["missed_source_newer"] - tot["unmapped"]
    print(f"reproduced / (oracle numbers whose source is not newer than the held PDFs and whose label maps) = "
          f"{tot['reproduced']}/{heldable} = {100 * tot['reproduced'] / max(heldable, 1):.0f}%")
    for d in detail[:args.max_detail]:
        print(" ", d[:230])
    return tot


def page_text(src, sym, doc_key, page, args):
    """Page text a stored quote must sit in: sandbox doc_text, else the decks_full PDF text layer, else the OCR page."""
    r = src.execute("SELECT text FROM doc_text WHERE doc_key=? AND page=?", (doc_key, page)).fetchone()
    if r and r[0]:
        return r[0]
    if getattr(args, "ocr_db", None):
        o = sqlite3.connect(args.ocr_db).execute("SELECT text FROM ocr_page WHERE symbol=? AND doc_key=? AND page=?",
                                                 (sym, doc_key, page)).fetchone()
        if o:
            return o[0]
    if doc_key.startswith("decks_full/"):
        try:
            import pymupdf
            return pymupdf.open(str(kpi.RAW_ROOT / doc_key))[page - 1].get_text("text")
        except Exception:
            return None
    return None


def sample_check(args):
    """40 random stored rows per company: quote is a substring of the page text, unit and period sane."""
    rnd = random.Random(7)
    con = sqlite3.connect(args.kpi)
    bad_tot = 0
    for sym in SYMS:
        src = sqlite3.connect(f"file:{(SANDBOX / (SYMS[sym] + '_loop') / (SYMS[sym] + '.db')).as_posix()}?mode=ro", uri=True)
        rows = con.execute("SELECT id, metric, value, unit, fiscal_period, doc_key, page, quote, extractor_rule FROM kpi_series WHERE symbol=?", (sym,)).fetchall()
        pick = rnd.sample(rows, min(args.sample, len(rows)))
        bad = []
        for r in pick:
            txt = page_text(src, sym, r[5], r[6], args)
            if txt is None:
                continue
            why = []
            if r[7] not in txt:
                why.append("quote not in page")
            if not re.fullmatch(r"(Q[1-4]|9M|6M|3M|12M|H[12])?FY\d\d", r[4]) and not re.fullmatch(r"Q[1-4]FY\d\d", r[4]):
                why.append("period")
            if r[3] in ("pct",) and not (0 <= r[2] <= 100000):
                why.append("pct range")
            if r[2] < 0 and r[1] not in ("net_debt",):
                why.append("negative")
            if why:
                bad.append((r[0], r[1], r[2], r[4], r[8], "/".join(why)))
        bad_tot += len(bad)
        print(f"sample {sym}: {len(pick)} rows checked by script, {len(bad)} failed {bad[:3]}")
    return bad_tot


def run_tr(args):
    cov = coverage()
    topics, _ = transcripts.load_topics()
    con = sqlite3.connect(args.tr)
    stm = defaultdict(list)
    for r in con.execute("SELECT symbol, doc_key, page, topics, numbers_json, statement FROM transcript_statement"):
        stm[(r[0], r[1], r[2])].append(r)
    by_sym_doc = defaultdict(list)
    for (s, d, p), v in stm.items():
        by_sym_doc[(s, d)].extend(v)
    print("\nTRANSCRIPT QUESTIONS (T): oracle-cited transcript pages, statements stored on them, topic tag hit, oracle numbers found")
    print(f"{'qid':16} {'cited_pages':>11} {'with_stmts':>10} {'tag_hit':>7} {'nums':>9}  expected tags")
    agg = Counter()
    for sym in SYMS:
        ans, _ = oracle_answers(sym)
        for qid, (tag, comp, qtext) in sorted(cov.items()):
            if tag != "T" or comp != sym or qid not in ans:
                continue
            a = ans[qid]
            cited = {(s.get("doc_key"), s.get("page")) for s in a.get("sources", []) if s.get("doc_key") and "transcript" in str(s.get("doc_key")) or
                     (s.get("doc_key") and (sym, s.get("doc_key")) in by_sym_doc)}
            exp = [t for t in transcripts.tag_topics(topics, sym, qtext) if t != "other"]
            have = [c for c in cited if (sym, c[0], c[1]) in stm]
            hit = [c for c in have if any(set(exp) & set(r[3].split(",")) for r in stm[(sym, c[0], c[1])])]
            nums_o = [n for n in a.get("numbers", []) if isinstance(n.get("value"), (int, float))]
            found = 0
            for n in nums_o:
                v, _ = canon_value(float(n["value"]), n.get("unit"))
                ok = False
                for (s2, d2), rs in by_sym_doc.items():
                    if s2 != sym:
                        continue
                    for r in rs:
                        for x in json.loads(r[4]):
                            if close(canon_value(x["value"], x["unit"])[0], v):
                                ok = True
                                break
                        if ok:
                            break
                    if ok:
                        break
                found += ok
            agg["q"] += 1
            agg["cited"] += len(cited)
            agg["have"] += len(have)
            agg["hit"] += len(hit)
            agg["nums_o"] += len(nums_o)
            agg["nums_f"] += found
            agg["q_with_cited"] += bool(cited)
            agg["q_all_pages"] += bool(cited) and len(have) == len(cited)
            print(f"{qid:16} {len(cited):11} {len(have):10} {len(hit):7} {found:4}/{len(nums_o):<4}  {','.join(exp)[:60]}")
    print(f"TOTAL T questions {agg['q']}: oracle-cited transcript pages {agg['cited']}, with stored statements {agg['have']}, "
          f"tag-hit pages {agg['hit']}; questions citing a transcript {agg['q_with_cited']}, all cited pages covered {agg['q_all_pages']}; "
          f"oracle numbers found in statements {agg['nums_f']}/{agg['nums_o']}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kpi", default=str(ROOT / ".tmp/pilot3_kpi.db"))
    ap.add_argument("--tr", default=str(ROOT / ".tmp/pilot3_tr.db"))
    ap.add_argument("--sample", type=int, default=40)
    ap.add_argument("--ocr-db", default=None, help="ocr_page db: OCR-read quotes are checked against the stored OCR text")
    ap.add_argument("--detail", action="store_true")
    ap.add_argument("--max-detail", type=int, default=25)
    ap.add_argument("--only", choices=["kpi", "tr", "sample"], default=None)
    a = ap.parse_args()
    if a.only in (None, "kpi"):
        run_kpi(a)
    if a.only in (None, "sample"):
        sample_check(a)
    if a.only in (None, "tr"):
        run_tr(a)


if __name__ == "__main__":
    main()
