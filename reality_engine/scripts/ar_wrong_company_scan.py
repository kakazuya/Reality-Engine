"""Find annual-report PDFs in ar_docs that are another company's report. Read-only; free local checks only.

Per report it opens the PDF with PyMuPDF (same text as ar_queue.page_texts) and looks for the company in three ways:
  name   - the company name (master_companies.company_name, else ar_docs.company), normalised (no Ltd/Limited/punctuation)
           on the evidence pages: the first 5 pages and the independent auditor's report pages; then anywhere
  isin   - the ISIN issuer prefix (INE603D...) anywhere in the text (survives face-value changes: only the serial changes)
  scrip  - the BSE scrip code anywhere in the text (covering letters to BSE quote it: "Scrip Code: 532408")
and where BSE's AnnualReport API listed the file (equity_intelligence.bse_annual_reports, by file key).

Names include every name the BSE scrip / ISIN traded under since 2019 (mkt_bse_eq_daily) and NSE names by symbol, so a
renamed company matches its old name (Megasoft -> Sigma Advanced Systems, PH Trading -> Vega Jewellers).

verdict:
  ok           a name found on the evidence pages (found on the first 5 pages: the rest of the report is not read)
  name_late    a name found only off the evidence pages: renames often look like this, but so does another company's
               report that mentions this one (negative control: 1 of 400 swapped pairs). Check by hand
  former_name  no name, but own ISIN prefix or scrip code is in the text: a rename older than the bhavcopy history
  listed_only  no name / ISIN / scrip in readable text; only BSE's listing ties the file to the company. NOT proof:
               BSE lists Home First Finance's notice under Venus Remedies (doc 92565). Check by hand
  candidate    readable text and nothing ties the file to the company: possibly another company's report
  unknown      fewer than 2 clean evidence pages (scanned, encoded, garbled, PDF portfolio) and nothing matched

  python -m reality_engine.scripts.ar_wrong_company_scan --data <repo>/reality_engine/data --workers 6
  python -m reality_engine.scripts.ar_wrong_company_scan --data ... --doc-ids 79913,125476,125486 --out-dir <scratch>
Writes <out-dir>/wrong_company_scan_all.csv (every report) and wrong_company_candidates.csv (candidate, listed_only,
name_late: the reports to check by hand).
"""
import argparse
import collections
import csv
import json
import multiprocessing as mp
import re
import sqlite3
import sys
from pathlib import Path
from reality_engine.config import raw_dir

from reality_engine.scripts import ar_queue

EVIDENCE_FIRST = 5
DROP = {"limited", "ltd", "the", "pvt", "private", "co", "company", "corp", "corpn", "corporation", "inc"}
AUDIT_RE = re.compile(r"independent\s+auditor", re.I)
FORMERLY_RE = re.compile(r"\(?\s*(?:formerly|earlier)\s+(?:known\s+as\s+)?[:\-]?\s*((?:[A-Z][\w&'.\-]*\s+){1,6}?)(?:LIMITED|Limited|LTD|Ltd)", re.S)
NAME_RE = re.compile(r"((?:\b[A-Z][A-Za-z0-9&'.\-]*[ \t]+){1,6}?)(?:LIMITED|Limited|LTD\b\.?|Ltd\b\.?)")
ISIN_RE = re.compile(r"\bIN[EF][A-Z0-9]{9}\b")
# names every report quotes that are never the reporting company
GENERIC = re.compile(r"^(bse|national stock exchange|stock exchange|national securities depository|central depository|"
                     r"link intime|bigshare|kfin|karvy|purva sharegistry|skyline financial|mcs share|cameo corporate|"
                     r"satellite corporate|adroit corporate|beetal|niche technologies|maheshwari datamatics|"
                     r"sharex|abhipra|alankit|bank|reserve bank|state bank|hdfc bank|icici bank|axis bank|"
                     r"metropolitan stock exchange|calcutta stock exchange|india|of india|and|for|from|to|of|by|"
                     r"credit analysis|crisil|care ratings|india ratings|icra)\b")


def norm(s):
    s = (s or "").lower().replace("&", " and ")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return " ".join(w for w in s.split() if w not in DROP)


def file_key(path):
    base = re.sub(r"(\.pdf)+$", "", Path(path).name, flags=re.I).lower()
    return re.sub(r"^\d{8}_[0-9a-f]{8}_", "", base)


def tokens_match(alias, toks):
    """alias tokens appear in order, consecutively, in the page tokens. A token matches a page token it prefixes, or,
    from 4 letters, whose letters it contains in order with the same first letter (bhavcopy shorthand: 'TRADG', 'FERT')."""
    def tok_ok(a, t):
        if len(a) <= 2:            # 'b and a' must not match any b-word followed by 'and' and an a-word
            return t == a
        if t.startswith(a):
            return True
        if len(a) < 4 or a[0] != t[0]:
            return False
        it = iter(t)
        return all(ch in it for ch in a)
    k = len(alias)
    return any(all(tok_ok(alias[j], toks[i + j]) for j in range(k)) for i in range(len(toks) - k + 1))


def page_hits(aliases, text):
    """Labels of the aliases found on a page. One-word names ('GATI', 'MMTC', 'INNOVATIVE') count only when written as
    '<word> Ltd/Limited/Corp/Company', or when the word is not common English; one-word squashed names need 8+ letters."""
    toks = norm(text).split()
    st = set(toks)
    low = None
    squashed = None
    out = []
    for lab, al in aliases:
        if len(al) > 1:
            hit = tokens_match(al, toks)
            if not hit and len("".join(al)) >= 10:   # spacing differs: 'Sterling Green Woods' vs 'STERLING GREENWOODS'
                squashed = squashed if squashed is not None else "".join(toks)
                hit = "".join(al) in squashed
        elif al[0] in st:
            low = low if low is not None else re.sub(r"[^a-z0-9]+", " ", text.lower())
            hit = (len(al[0]) >= 5 and al[0] not in ar_queue.vocab() and not al[0].isdigit()) or \
                re.search(rf"\b{re.escape(al[0])} (?:limited|ltd|corp|corporation|company|co)\b", low) is not None
        elif len(al[0]) >= 8 and not al[0].isdigit() and al[0] not in ar_queue.vocab():   # AARVINFRA, MAHAANIMPEX
            squashed = squashed if squashed is not None else "".join(toks)
            hit = al[0] in squashed
        else:
            hit = False
        if hit:
            out.append(lab)
    return out


def alias_tokens(name):
    """Normalised tokens; drops a trailing word BSE cut off mid-way ('... JEWELLERY LIMI', '... SERVICES LIM')."""
    al = norm(name).split()
    while len(al) > 1 and len(al[-1]) >= 2 and any(w.startswith(al[-1]) and w != al[-1] for w in ("limited", "private", "corporation", "company")):
        al.pop()
    return tuple(al)


def load_docs(data, doc_ids):
    con = sqlite3.connect(f"file:{data / 'ar_facts.db'}?mode=ro", uri=True, timeout=120)
    sql = "SELECT doc_id, isin, symbol, company, fiscal_year, path, status, error FROM ar_docs"
    rows = con.execute(sql + (f" WHERE doc_id IN ({','.join('?' * len(doc_ids))})" if doc_ids else "") + " ORDER BY doc_id",
                       doc_ids or ()).fetchall()
    n_facts = dict(con.execute("SELECT doc_id, COUNT(*) FROM ar_facts GROUP BY doc_id")) if not doc_ids else {
        r[0]: con.execute("SELECT COUNT(*) FROM ar_facts WHERE doc_id=?", (r[0],)).fetchone()[0] for r in rows}
    con.close()
    eq = sqlite3.connect(f"file:{data / 'equity_intelligence.db'}?mode=ro", uri=True, timeout=120)
    by_isin, by_sym = {}, {}
    names = collections.defaultdict(set)          # normalised name -> {isin} (to resolve names found in the text)
    for isin, sym, bse, name in eq.execute("SELECT isin, nse_symbol, bse_code, company_name FROM master_companies"):
        by_isin[isin] = (sym, bse, name)
        if sym:
            by_sym[sym] = (isin, bse, name)
        if name and len(norm(name).split()) >= 2 and not isin.startswith("INE_AUTO"):
            names[norm(name)].add(isin)
    listed = collections.defaultdict(set)
    for scrip, key in eq.execute("SELECT scripcode, file_key FROM bse_annual_reports"):
        listed[key].add(scrip)
    # every name a scrip / ISIN / symbol traded under on BSE since 2019: current and former names
    bse_names, code_by_isin, code_by_sym, isin_by_code = (collections.defaultdict(set) for _ in range(4))
    rows_bse = eq.execute("SELECT DISTINCT sc_code, isin, symbol, name FROM mkt_bse_eq_daily").fetchall()
    for code, isin, sym, name in rows_bse:
        if isin:
            code_by_isin[isin].add(code)
            isin_by_code[code].add(isin)
        if sym:
            code_by_sym[sym].add(code)
        if name:
            bse_names[code].add(name)
    other = collections.defaultdict(set)     # NSE names by symbol
    for q in ("SELECT DISTINCT symbol, company_name FROM corporate_actions", "SELECT DISTINCT symbol, company FROM mkt_nse_insider",
              "SELECT DISTINCT symbol, company FROM mkt_nse_sast"):
        for sym, name in eq.execute(q):
            if sym and name:
                other[sym].add(name)
    eq.close()
    jobs = []
    for doc_id, isin, sym, company, fy, path, status, error in rows:
        m, s = by_isin.get(isin), by_sym.get(sym)   # INE_AUTO_* rows carry only the symbol as name and no bse code
        opts = [x for x in ((m or (0, 0, None))[2], (s or (0, 0, None))[2], company) if x]
        name = next((x for x in opts if norm(x) != norm(sym)), opts[0] if opts else sym)
        real = {i for i in (isin, s and s[0]) if i and not i.startswith("INE_AUTO")}
        codes = {c for c in ((m and m[1]), (s and s[1])) if c} | {c for i in real for c in code_by_isin.get(i, ())}
        if not real:   # BSE symbols can clash with another company's NSE symbol: by symbol only without a real ISIN
            codes |= code_by_sym.get(sym, set())
        from_listing = not codes
        if from_listing:  # the scrip BSE listed the file under (we fetched it by this company's scrip code)
            codes = set(listed.get(file_key(path), ()))
        isins = {i for i in (isin, s and s[0]) if i and not i.startswith("INE_AUTO")} | {i for c in codes for i in isin_by_code.get(c, ())}
        alias_names = set(opts) | other.get(sym, set()) | {x for c in codes for x in bse_names.get(c, ())}
        aliases, seen = [], set()
        for a in sorted(alias_names, key=lambda x: (x != name, x)):
            al = alias_tokens(a)
            if al and al not in seen and len("".join(al)) >= 3:
                seen.add(al)
                aliases.append((a, al))
        if not aliases and len(norm(sym)) >= 3:    # nothing but the symbol: look for it as a word
            aliases = [(sym, tuple(norm(sym).split()))]
        jobs.append(dict(doc_id=doc_id, isin=isin, symbol=sym, company=company, name=name, aliases=aliases,
                         bse=" ".join(sorted(codes)), codes=sorted(codes), from_listing=from_listing, isin_prefixes=sorted({i[:7] for i in isins}),
                         fy=fy, path=path, status=status, error=error or "", n_facts=n_facts.get(doc_id, 0),
                         listed_under=sorted(listed.get(file_key(path), ()))))
    return jobs, names, by_isin


def scan(job):
    out = dict(job)
    aliases = job["aliases"]
    try:
        import pymupdf
        doc = pymupdf.open(job["path"])
        try:   # fast path: a name on the first pages -> ok without reading the whole report
            n = len(doc)
            head = {i + 1: doc[i].get_text() for i in range(min(EVIDENCE_FIRST, n))}
            hits = {p: page_hits(aliases, t) for p, t in head.items()}
            hit = [p for p, h in hits.items() if h]
            texts = None if hit else {i + 1: doc[i].get_text() for i in range(n)}   # same text as ar_queue.page_texts
        finally:
            doc.close()
    except Exception as e:   # missing / broken file
        out.update(verdict="unknown", reason=f"open failed: {type(e).__name__}: {str(e)[:80]}")
        return out
    if hit:
        out.update(verdict="ok", n_pages=n, evidence_pages=sorted(head), name_pages=hit,
                   matched=collections.Counter(a for p in hit for a in hits[p]).most_common(2))
        return out
    audit = [p for p, t in texts.items() if AUDIT_RE.search(t[:1500])]
    ev = sorted(set(range(1, min(EVIDENCE_FIRST, n) + 1)) | set(audit[:8]))
    kinds = {p: ar_queue.page_kind(texts[p]) for p in ev}
    clean_ev = [p for p in ev if kinds[p] == "clean"]
    hits = {p: page_hits(aliases, t) for p, t in texts.items()}
    name_pages_ev = [p for p in ev if hits[p]]
    name_pages_all = name_pages_ev or [p for p in texts if hits[p]]
    isin_pages = [p for p, t in texts.items() if any(x in t.upper() for x in job["isin_prefixes"])]
    scrip_re = re.compile(r"(?<!\d)(?:" + "|".join(job["codes"]) + r")(?!\d)") if job["codes"] else None
    scrip_pages = [p for p, t in texts.items() if scrip_re and scrip_re.search(t)]
    own_listed = not job["from_listing"] and bool(set(job["codes"]) & set(job["listed_under"]))
    matched = collections.Counter(a for p in name_pages_all for a in hits[p]).most_common(2)
    names = collections.Counter()
    for p in ev:
        for m in NAME_RE.finditer(texts[p]):
            k = " ".join(m.group(1).split())
            if 3 <= len(k) <= 70 and not GENERIC.match(k.lower()):
                names[k.upper()] += 1
    formerly = collections.Counter(" ".join(m.group(1).split()).upper() for t in texts.values() for m in FORMERLY_RE.finditer(t))
    isins = collections.Counter(m for t in texts.values() for m in ISIN_RE.findall(t.upper()))
    if name_pages_ev:
        verdict = "ok"
    elif name_pages_all:
        verdict = "name_late"
    elif isin_pages or scrip_pages:
        verdict = "former_name"
    elif len(clean_ev) < 2:
        verdict = "unknown"
    elif own_listed:
        verdict = "listed_only"
    else:
        verdict = "candidate"
    out.update(verdict=verdict, matched=matched, n_pages=n, evidence_pages=ev, clean_evidence_pages=clean_ev,
               page_kinds=collections.Counter(kinds.values()), name_pages=name_pages_all[:10], isin_pages=isin_pages[:10],
               scrip_pages=scrip_pages[:10], own_scrip_listed=own_listed, top_names=names.most_common(5),
               formerly=formerly.most_common(3), isins_found=isins.most_common(5))
    return out


def resolve(r, names, by_isin):
    """Name the company the text points at: another master company's ISIN in the text, else a top name in master."""
    own = r["isin"]
    for isin, c in r.get("isins_found") or ():
        for full, m in by_isin.items():
            if full[:7] == isin[:7] and full != own:
                return f"{m[2]} ({full}, ISIN x{c})"
    for nm, c in r.get("top_names") or ():
        hit = names.get(norm(nm))
        if hit and own not in hit:
            isin = sorted(hit)[0]
            return f"{by_isin[isin][2]} ({isin}, name x{c})"
    return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=Path, required=True, help="reality_engine/data of the live checkout")
    ap.add_argument("--doc-ids", default="")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--out-dir", type=Path)
    a = ap.parse_args()
    ar_queue.VOCAB_F = raw_dir("ar_queue") / "en_vocab.txt"
    out_dir = a.out_dir or raw_dir("ar_queue")
    out_dir.mkdir(parents=True, exist_ok=True)
    ids = [int(x) for x in a.doc_ids.split(",") if x.strip()]
    jobs, names, by_isin = load_docs(a.data, ids)
    print(f"{len(jobs)} reports", file=sys.stderr)
    res = []
    with mp.Pool(a.workers, initializer=_init, initargs=(str(ar_queue.VOCAB_F),)) as pool:
        for i, r in enumerate(pool.imap_unordered(scan, jobs, chunksize=4), 1):
            res.append(r)
            if i % 500 == 0:
                print(f"{i}/{len(jobs)} {collections.Counter(x['verdict'] for x in res)}", file=sys.stderr, flush=True)
    res.sort(key=lambda r: r["doc_id"])
    cols = ["doc_id", "symbol", "isin", "company", "name_checked", "fiscal_year", "status", "n_facts", "verdict", "matched_name",
            "points_to", "top_names", "formerly", "isins_found", "evidence_pages", "clean_evidence_pages", "name_pages",
            "isin_pages", "scrip_pages", "bse_code", "bse_listed_under", "own_scrip_listed", "n_pages", "reason",
            "error", "path"]
    rows = []
    for r in res:
        rows.append({"doc_id": r["doc_id"], "symbol": r["symbol"], "isin": r["isin"], "company": r["company"],
                     "name_checked": r["name"], "fiscal_year": r["fy"], "status": r["status"], "n_facts": r["n_facts"],
                     "verdict": r["verdict"], "matched_name": "; ".join(a for a, _ in r.get("matched") or ()), "points_to": resolve(r, names, by_isin) if r["verdict"] != "ok" else "",
                     "top_names": "; ".join(f"{k} x{c}" for k, c in r.get("top_names") or ()),
                     "formerly": "; ".join(f"{k} x{c}" for k, c in r.get("formerly") or ()),
                     "isins_found": "; ".join(f"{k} x{c}" for k, c in r.get("isins_found") or ()),
                     **{k: " ".join(map(str, r.get(k) or ())) for k in ("evidence_pages", "clean_evidence_pages", "name_pages", "isin_pages", "scrip_pages")},
                     "bse_code": r["bse"] or "", "bse_listed_under": " ".join(r["listed_under"]),
                     "own_scrip_listed": int(bool(r.get("own_scrip_listed"))), "n_pages": r.get("n_pages", ""),
                     "reason": r.get("reason", ""), "error": r["error"], "path": r["path"]})
    for fname, keep in (("wrong_company_scan_all.csv", lambda x: True), ("wrong_company_candidates.csv", lambda x: x["verdict"] in ("candidate", "listed_only", "name_late"))):
        with open(out_dir / fname, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, cols)
            w.writeheader()
            w.writerows(x for x in rows if keep(x))
    print(json.dumps(collections.Counter(x["verdict"] for x in rows)), "->", out_dir)


def _init(vocab):
    ar_queue.VOCAB_F = Path(vocab)


if __name__ == "__main__":
    main()
