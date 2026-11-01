"""Build the pilot question bank from Claude's hand-written rules. Read-only on stores. Run: python tasks/pilot60/pilot_bank/run.py"""
from __future__ import annotations

import collections
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import engine as E  # noqa: E402

G = {  # business groups, written by hand from each company's held business description
    "lender": "BAJFINANCE ESAFSFB EDELWEISS", "bank": "ESAFSFB", "wealth": "ANANDRATHI EDELWEISS BAJFINANCE",
    "metal": "HINDALCO SAIL IMPEXFERRO", "steel": "SAIL APLAPOLLO TIRUPATIFL IMPEXFERRO", "alu": "HINDALCO",
    "cement": "GRASIM DALBHARAT BIGBLOC", "power": "POWERGRID NLCINDIA", "oil": "HINDPETRO HINDOILEXP ATGL",
    "auto": "BOSCHLTD TMPV TIRUPATIFL", "pharma": "SUNPHARMA ALKEM", "chem": "PIDILITIND ANURAS JUBLINGREA ASAHISONG VIKASWSP",
    "fmcg": "HINDUNILVR UBL DOLLAR", "it": "TATAELXSI COMPINFO PANACHE", "telecom": "IDEA TEJASNET STLTECH",
    "realty": "DLF PRESTIGE ASHIANA AURUM", "epc": "KEC ASHOKA WPIL UNIVASTU DHARAN", "textile": "WELSPUNLIV DOLLAR",
    "jewel": "KALYANKJIL RAJESHEXPO", "qsr": "SPECIALITY UFBL", "hotel": "INDHOTEL", "airport": "GMRAIRPORT",
    "pack": "UFLEX DDEVPLSTIK", "defence": "URAVIDEF TEJASNET", "capgood": "HEGAM WPIL KEC APLAPOLLO BOSCHLTD",
    "sugar": "SIMBHALS", "retail": "KHADIM KALYANKJIL DOLLAR", "media": "HMVL", "elec": "TEJASNET STLTECH BOSCHLTD PANACHE",
    "export": "SUNPHARMA ALKEM WELSPUNLIV TATAELXSI ANURAS HEGAM RAJESHEXPO ASAHISONG UFLEX DOLLAR JUBLINGREA",
    "import": "HINDPETRO TEJASNET STLTECH KALYANKJIL RAJESHEXPO BOSCHLTD", "infra": "POWERGRID GMRAIRPORT ASHOKA KEC NLCINDIA",
    "paint": "PIDILITIND ASAHISONG GRASIM", "ipo": "ANANDRATHI KALYANKJIL DDEVPLSTIK ESAFSFB URAVIDEF", "input": "DDEVPLSTIK APLAPOLLO UFLEX KEC",
    "fertagri": "JUBLINGREA VIKASWSP AGVENTURES SIMBHALS", "holdco": "GRASIM EDELWEISS AGVENTURES",
}
G = {k: v.split() for k, v in G.items()}
RULES: dict = {}
ORDER: list = []
READS: dict = {}
SEEN: set = set()


def load_reads():
    path = Path(__file__).parent / "reads.jsonl"
    if path.exists():
        for line in open(path, encoding="utf-8"):
            o = json.loads(line)
            READS[(o["parent_mid"], o["symbol"], o["ev"])] = o


def read_of(mid, sym, r):
    return READS.get((mid, sym, r.get("ev")))


def read_ok(mid, sym, r):
    """A stock is out only once DeepSeek has read its passages and they state nothing."""
    got = read_of(mid, sym, r)
    if os.environ.get("BANK_FINAL") and not got:
        return False  # the final bank carries only passages that have been read
    return not (got and got["verdict"] == "NO")


def _add(mid, **kw):
    mid = "MB" + mid
    assert mid not in RULES, mid
    RULES[mid] = kw
    ORDER.append(mid)


def S(mid, q, ev=None, t="CDAN", fit=None, as_of=None, ann=None):
    _add(mid, kind="S", q=q, ev=ev, t=t, fit=fit, as_of=as_of, ann=ann)


def M(mid, q, ev=None, t="CDANX", fit=None, as_of=None, min_n=2, pol=None, idx=None):
    _add(mid, kind="M", q=q, ev=ev, t=t, fit=fit, as_of=as_of, min_n=min_n, pol=pol, idx=idx)


def K(mid, q, chk=(), as_of=None, pol=None, ev=None, t="CDANX"):
    _add(mid, kind="K", q=q, chk=chk, as_of=as_of, pol=pol, ev=ev, t=t)


def X(mid, why):
    _add(mid, kind="X", why=why)


def CH(mid, ev, fit=None, t="CDANX", min_n=2, pol=None):
    """A chain question with no asserted fact: keep the parent's words, scope it to named pilot stocks."""
    _add(mid, kind="CH", ev=ev, fit=fit, t=t, min_n=min_n, as_of=None, pol=pol, idx=None)


def fits(rule):
    f = rule.get("fit")
    if not f:
        return None
    out = []
    for g in f.split():
        out += G.get(g, [g])
    return set(out)


def stale(fact, as_of):
    # a name with no session close to the row's date cannot answer a current question
    return fact.get("last_iso", "") < min(as_of, "2026-09-01")


def row(rid, mid, kind, bucket, stocks, text, as_of, parent, old, r, ev, ann=None):
    prev = next((o for o in old if o["mid"] == rid), None)
    old_text = prev["question"] if prev else parent["question"]
    return {"mid": rid, "parent_mid": mid, "kind": kind, "bucket": bucket,
            "entities": [{"isin": s["isin"], "symbol": s["sym"]} for s in stocks],
            "question": text, "old_question": old_text, "changed": text != old_text, "as_of": as_of,
            "family": parent.get("family"), "entity_level": "stock" if kind == "stock" else ("market" if kind == "market" else "pilot_set"),
            "answer_kind": parent.get("answer_kind"), "template": parent.get("template"), "source_bank": parent["source_bank"],
            "regression": bool(parent.get("regression")), "period": None,
            "fact_check": {"evidence": ev, "announcement": ann, "ev_query": r.get("ev"), "fit": r.get("fit"),
                           "reads": [read_of(mid, s["sym"], r) for s in stocks if read_of(mid, s["sym"], r)]}}


def stock_rows(st, mid, r, as_of, parent, old):
    allowed = fits(r)
    hits = st.hits(r["ev"], r["t"], as_of) if r.get("ev") else None
    old_by_bucket = {o["bucket"]: o["entities"][0].get("symbol") for o in old if o.get("entities")}
    rows = []
    for bucket, suffix in E.BUCKET_SUFFIX.items():
        cands = []
        for s in st.u:
            if s["bucket"] != bucket or (allowed and s["sym"] not in allowed):
                continue
            f = dict(st.facts(s["isin"]))
            if stale(f, as_of) or (hits is not None and s["isin"] not in hits) or (r.get("ev") and not read_ok(mid, s["sym"], r)):
                continue
            ev = hits[s["isin"]][1] if hits is not None else None
            got = read_of(mid, s["sym"], r)
            if got and got.get("chunk_id") and got["verdict"] in ("YES", "PARTIAL"):
                # the date and page in the question are those of the passage that was verified
                ev = dict(st.chunk_ref(got["chunk_id"]) or ev, snippet=got.get("quote"))
            ann = None
            if r.get("ann"):
                ann = st.ann(s["isin"], r["ann"], as_of)
                if not ann:
                    continue
                f.update(ann_date=E.fmt_date(ann["date"]), ann_time=ann["time"], ann_head=ann["headline"])
            text = E.fill(r["q"], f, ev)
            if text is None or not E.dates_have_sessions(text, [x[0] for x in st.px(s["isin"])]):
                continue
            got = read_of(mid, s["sym"], r)
            rank = {"YES": 100000, "PARTIAL": 50000}.get(got["verdict"], 0) if got else 0
            score = rank + (hits[s["isin"]][0] if hits is not None else 0) + (1000 if old_by_bucket.get(bucket) == s["sym"] else 0)
            cands.append((score, s["sym"], s, text, ev, ann))
        # one question text appears once: a repeat moves to the next stock
        cands = [c for c in cands if c[3] not in SEEN]
        if cands:
            cands.sort(key=lambda c: (-c[0], c[1]))
            _, _, s, text, ev, ann = cands[0]
            SEEN.add(text)
            rows.append(row(f"{mid}#{suffix}", mid, "stock", bucket, [s], text, as_of, parent, old, r, [ev] if ev else [], ann))
    return rows


def member(st, isin, code, as_of):
    return st.ms.execute("SELECT 1 FROM company_membership_pit WHERE isin=? AND index_code=? AND added_on<=? AND (removed_on IS NULL OR removed_on>?)",
                         (isin, code, as_of, as_of)).fetchone() is not None


def check_market(st, chks):
    """Each asserted market fact is re-read here; a mismatch returns the fact, and the row is not published."""
    for c in chks:
        if c[0] == "idx":
            r = st.eq.execute("SELECT pct_change FROM mkt_nse_index_daily WHERE index_name=? AND date=?", (c[1], c[2])).fetchone()
            if not r or r[0] is None or abs(r[0] - c[3]) > 0.11:
                return f"{c[1]} {c[2]} claimed {c[3]} stored {r}"
        elif c[0] == "comm":
            r = st.eq.execute("SELECT close FROM mkt_commodity_daily WHERE commodity=? AND date<=? ORDER BY date DESC LIMIT 1", (c[1], c[2])).fetchone()
            if not r or abs(r[0] / c[3] - 1) > 0.01:
                return f"{c[1]} {c[2]} claimed {c[3]} stored {r}"
        elif c[0] == "date":
            if not st.eq.execute("SELECT 1 FROM mkt_fii_dii_cash WHERE date=?", (c[1],)).fetchone():
                return f"no fii row {c[1]}"
        elif c[0] == "cells":
            if not st.eq.execute("SELECT 1 FROM mkt_report_cells WHERE source=? AND file=? LIMIT 1", (c[1], c[2])).fetchone():
                return f"no report cells {c[1]} {c[2]}"
    return None


def main():
    root = E.ROOT
    bank = {}
    for line in open(root / "tasks/master_bank/MASTER_BANK.jsonl", encoding="utf-8"):
        o = json.loads(line)
        bank[o["mid"]] = o
    inst = collections.defaultdict(list)
    for line in open(root / "tasks/pilot60/INSTANCES.jsonl", encoding="utf-8"):
        o = json.loads(line)
        inst[o["parent_mid"]].append(o)
    load_reads()
    missing = [m for m in bank if m not in RULES]
    if missing:
        sys.exit(f"no rule for {len(missing)}: {missing[:40]}")
    st = E.Store()
    rows, removed, weak = [], [], []
    for n, mid in enumerate(ORDER):
        if n % 100 == 0:
            print(f"[{n}/{len(ORDER)}] queries={len(st._hits)}", flush=True)
        r, p, old = RULES[mid], bank[mid], inst[mid]
        as_of = r.get("as_of") or E.SNAPSHOT
        if r["kind"] == "X":
            removed.append({"mid": mid, "old_question": p["question"], "why": r["why"]})
            continue
        if r["kind"] == "S":
            got = stock_rows(st, mid, r, as_of, p, old)
            if not got:
                weak.append(mid + ":no-stock")
            rows += got
            continue
        ev, stocks = [], []
        if r.get("pol"):
            n = st.eq.execute("SELECT COUNT(*) FROM policy_events WHERE substr(published_at,1,10)<=? AND (title LIKE ? OR policy_name LIKE ? OR quote LIKE ?)",
                              (as_of, *[f"%{r['pol']}%"] * 3)).fetchone()[0]
            if not n:
                weak.append(mid + ":policy")
                continue
            ev.append({"policy_events_matches": n, "term": r["pol"]})
        if r["kind"] == "K":
            bad = check_market(st, r.get("chk", ()))
            if bad:
                weak.append(f"{mid}:{bad}")
                continue
            if r.get("ev"):
                h = st.hits(r["ev"], r["t"], as_of)
                if not h:
                    weak.append(mid + ":no-evidence")
                    continue
                ev += [v[1] for v in list(h.values())[:3]]
            if r["q"] in SEEN:
                weak.append(f"{mid}:same text as another question")
                continue
            SEEN.add(r["q"])
            rows.append(row(mid, mid, "market", "ALL", [], r["q"], as_of, p, old, r, ev))
            continue
        allowed = fits(r)
        h = st.hits(r["ev"], r["t"], as_of) if r.get("ev") else {s["isin"]: [1, None] for s in st.u}
        for s in st.u:
            if s["isin"] in h and (not allowed or s["sym"] in allowed) and not stale(st.facts(s["isin"]), as_of) and (not r.get("ev") or read_ok(mid, s["sym"], r)):
                if r.get("idx") and not member(st, s["isin"], r["idx"], as_of):
                    continue
                stocks.append(s)
        stocks.sort(key=lambda s: (-{"YES": 2, "PARTIAL": 1}.get((read_of(mid, s["sym"], r) or {}).get("verdict"), 0), -h[s["isin"]][0]))
        stocks = stocks[:8]
        if len(stocks) < r["min_n"]:
            weak.append(f"{mid}:cohort={len(stocks)}")
            continue
        names = [s["name"] for s in stocks]
        cohort = ", ".join(names[:-1]) + " and " + names[-1] if len(names) > 1 else names[0]
        if r["kind"] == "CH":
            base = p["question"].replace("listed ", "").replace("Listed ", "")
            text = f"{base} Answer only for {cohort}, from their filings and the held series."
        else:
            text = r["q"].replace("{cohort}", cohort)
        ev += [h[s["isin"]][1] for s in stocks if h[s["isin"]][1]]
        if text in SEEN:
            weak.append(f"{mid}:same text as another question")
            continue
        SEEN.add(text)
        rows.append(row(mid, mid, "pilot_set", "ALL", stocks, text, as_of, p, old, r, ev))
    st.save()
    E.json_dump(root / "tasks/pilot60/PILOT_BANK_2026-10-31.jsonl", rows)
    # a question with no stock left is removed, with the reason on record
    for w in weak:
        mid = w.split(":")[0]
        removed.append({"mid": mid, "old_question": bank[mid]["question"], "why": ("Same wording as another question after the rewrite" if "same text" in w else "No pilot stock's documents state this: DeepSeek read the passages, quotes checked, none qualified")})
    E.json_dump(root / "tasks/pilot60/PILOT_BANK_REMOVED_2026-10-31.jsonl", removed)
    print("rows", len(rows), "parents", len({x["parent_mid"] for x in rows}), "removed", len(removed), "weak", len(weak), "changed", sum(x["changed"] for x in rows))
    print("kinds", collections.Counter(x["kind"] for x in rows), "buckets", collections.Counter(x["bucket"] for x in rows))
    print("stocks used", len({e["symbol"] for x in rows for e in x["entities"]}), collections.Counter(e["symbol"] for x in rows for e in x["entities"]).most_common(12))
    print("weak", weak)
    unread = sum(1 for x in rows if RULES[x["parent_mid"]].get("ev") and x["kind"] != "market" and any(
        read_of(x["parent_mid"], e["symbol"], RULES[x["parent_mid"]]) is None for e in x["entities"]))
    print("rows with an unread stock", unread)
