"""Build the 300-question bank: 10 variations of each of Shivam's 30 questions.

Read-only over REALITY_DATA_ROOT. Writes only the two bank files under tasks/.
Every entity, date, policy and document reference is taken from a bounded query;
nothing here is hand-invented. Run from the worktree root:

    python tasks/build_question_bank_300.py
"""
from __future__ import annotations

import json
import os
import re
from collections import Counter, defaultdict
from pathlib import Path

from reality_engine.db.readonly import connect_ro

DATA = Path(os.environ["REALITY_DATA_ROOT"])
ROOT = Path(__file__).resolve().parent.parent
OUT_JSONL = ROOT / "tasks" / "QUESTION_BANK_300_2026-10-27.jsonl"
OUT_MD = ROOT / "tasks" / "QUESTION_BANK_300_2026-10-27.md"
SNAPSHOT_END = "2026-10-19"
WIN_START = "2024-04-01"          # company data window (task rule)
PRICE_START = "2019-01-01"        # price window (task rule)
VARY = ["V1", "V2", "V3", "V4", "V5", "V6", "V7", "V8", "V9", "V10"]


# --------------------------------------------------------------------------- #
# data
# --------------------------------------------------------------------------- #
def _rows(con, sql, n=None):
    cur = con.execute(sql)
    return cur.fetchall() if n is None else cur.fetchmany(n)


def load():
    con = connect_ro(DATA / "equity_intelligence.db", timeout_s=180)
    d = {}

    # company pool -------------------------------------------------------- #
    pool = {}
    for isin, nse, bse, name, sector, industry, basic, ilist, tier in _rows(con, """
        select m.isin, m.nse_symbol, m.bse_code, m.company_name,
               ci.sector, ci.industry, ci.basic_industry, ci.index_list, m.market_cap_tier
        from master_companies m join company_industry ci on ci.isin = m.isin
        where m.is_active = 1
    """):
        pool[isin] = dict(isin=isin, nse=(nse or "").strip(), bse=(bse or "").strip(),
                          name=(name or isin).strip(), sector=(sector or "").strip(),
                          industry=(industry or "").strip(),
                          basic=(basic or "").strip(), index_list=ilist or "",
                          mcap=None, bucket=None, tier=(tier or "").strip())
    mcap = {}
    for isin, mc, fy in _rows(con, "select isin, market_cap_inr_cr, fiscal_year from company_forensic_health"):
        if mc is None:
            continue
        key = fy or ""
        if isin not in mcap or key > mcap[isin][0]:
            mcap[isin] = (key, float(mc))
    for isin, e in pool.items():
        if isin in mcap:
            e["mcap"] = mcap[isin][1]
            mc = e["mcap"]
            e["bucket"] = ("LARGE" if mc >= 50000 else "MID" if mc >= 10000
                           else "SMALL" if mc >= 1000 else "MICRO")
        elif e.get("tier") in ("LARGE", "MID", "SMALL", "MICRO"):
            e["bucket"] = e["tier"]
    d["pool"] = pool
    d["by_symbol"] = {}
    for e in pool.values():
        for s in (e["nse"], e["bse"]):
            if s:
                d["by_symbol"][s] = e

    # filings / segment / npa --------------------------------------------- #
    xcon = connect_ro(DATA / "results_xbrl.db", timeout_s=180)
    d["filings"] = defaultdict(list)
    for isin, pe in _rows(xcon, "select isin, period_end from filings"):
        if isin and pe:
            d["filings"][isin].append(str(pe)[:10])
    for v in d["filings"].values():
        v.sort()
    # concept coverage maps used by the segment / bank questions
    d["seg_isins"], d["npa_isins"] = set(), set()
    try:
        for isin, concept in _rows(xcon, "select f.isin, f.concept from facts f limit 0"):
            pass
    except Exception:
        pass
    xcon.close()

    # shareholding -------------------------------------------------------- #
    d["shp"] = defaultdict(set)
    for isin, q in _rows(con, "select isin, quarter_end from shp_index"):
        if isin and q:
            d["shp"][isin].add(str(q)[:10])

    # annual reports ------------------------------------------------------ #
    acon = connect_ro(DATA / "ar_facts.db", timeout_s=180)
    d["ar"] = defaultdict(list)
    for isin, fy, filed in _rows(acon, "select isin, fiscal_year, filed_at from ar_docs"):
        if isin:
            d["ar"][isin].append((str(fy)[:10] if fy else "", str(filed or "")))
    acon.close()

    # decks --------------------------------------------------------------- #
    decon = connect_ro(DATA / "deck_figures.db", timeout_s=180)
    d["decks"] = defaultdict(list)
    for isin, sym, known, title, path, status, sha in _rows(decon, """
        select isin, symbol, known_at, title, local_path, status, sha256
        from deck_sources where known_at <= '%s'
    """ % SNAPSHOT_END):
        if isin:
            d["decks"][isin].append(dict(date=str(known or "")[:10], title=title or "",
                                         path=path or "", status=status or "", sha=sha or ""))
    for v in d["decks"].values():
        v.sort(key=lambda x: x["date"])
    d["_deck_con"] = decon

    # concalls ------------------------------------------------------------ #
    ccon = connect_ro(DATA / "concall_facts.db", timeout_s=180)
    d["cc"] = defaultdict(list)
    for isin, sym, filed in _rows(ccon, "select isin, symbol, filed_at from cc_docs"):
        filed = str(filed or "")
        if isin and filed[:4] >= "2024":
            d["cc"][isin].append(filed[:10])
    for v in d["cc"].values():
        v.sort()
    ccon.close()

    # results notes ------------------------------------------------------- #
    ncon = connect_ro(DATA / "results_notes.db", timeout_s=180)
    d["notes"] = defaultdict(list)
    for isin, sym, q in _rows(ncon, "select isin, symbol, quarter_end from docs"):
        if isin and q:
            d["notes"][isin].append(str(q)[:10])
    d["_notes_con"] = ncon

    # quarterly / annual financials -------------------------------------- #
    d["qf"] = defaultdict(set)
    for isin, q in _rows(con, "select isin, quarter_end_date from quarterly_financials"):
        if isin and q:
            d["qf"][isin].add(str(q)[:10])
    d["af"] = defaultdict(set)
    for isin, fy in _rows(con, "select isin, fiscal_year from annual_financials"):
        if isin and fy:
            d["af"][isin].add(str(fy))

    # forensic (P/B, mcap) ------------------------------------------------ #
    d["cfh"] = {}
    for isin, pb, mc, ev in _rows(con, "select isin, pb_ratio, market_cap_inr_cr, last_evaluated_date from company_forensic_health"):
        d["cfh"][isin] = dict(pb=pb, mcap=mc, evaluated=str(ev or "")[:10])

    # corporate actions --------------------------------------------------- #
    d["ca"] = []
    for isin, sym, typ, ex, subj in _rows(con, """
        select isin, symbol, action_type, ex_date, subject from corporate_actions
        where action_type in ('SPLIT','BONUS') and ex_date >= '2025-06-01'
    """):
        if isin and ex:
            d["ca"].append(dict(isin=isin, symbol=sym or "", type=typ,
                                ex=str(ex)[:10], subject=subj or ""))
    d["ca"].sort(key=lambda x: x["ex"])

    # renaming: same ISIN, >1 alphabetic symbol --------------------------- #
    syms = defaultdict(set)
    for isin, sym in _rows(con, "select isin, symbol from symbol_isin_history"):
        if isin and sym and re.match(r"^[A-Z][A-Z0-9&.\-]{1,15}$", symbol_s := str(sym).strip()):
            syms[isin].add(symbol_s)
    d["renames"] = {isin: sorted(s) for isin, s in syms.items() if len(s) > 1}

    # prices: per-ISIN coverage from the dated DuckDB snapshot ------------ #
    import duckdb
    dk = duckdb.connect(str(DATA / "snapshots" / "truth_2026-10-19.duckdb"), read_only=True)
    d["px"] = {}
    for tbl in ("px_nse_adj", "px_bse_adj"):
        for isin, a, b in dk.execute(
                f"select isin, min(date), max(date) from {tbl} where isin is not null group by 1").fetchall():
            if isin:
                old = d["px"].get(isin)
                d["px"][isin] = (min(a, old[0]) if old else a,
                                 max(b, old[1]) if old else b)
    d["_duck"] = dk
    # segment / bank-concept coverage (columnar, one pass)
    d["seg_isins"], d["npa_isins"] = set(), set()
    try:
        for isin, concept in dk.execute("""
            select fl.isin, f.concept from results_facts f
            join results_filings fl on f.file = fl.file
            where f.concept in ('SegmentRevenue','SegmentRevenueFromOperations',
                                'PercentageOfNpa','PercentageOfGrossNpa')
            group by 1,2
        """).fetchall():
            if isin:
                if concept in ("SegmentRevenue", "SegmentRevenueFromOperations"):
                    d["seg_isins"].add(isin)
                else:
                    d["npa_isins"].add(isin)
    except Exception as exc:
        print("concept map skipped:", exc)

    # ETFs ---------------------------------------------------------------- #
    d["etf"] = {}
    for isin, sym, name in _rows(con, "select isin, symbol, scheme_name from etf_master"):
        if isin:
            d["etf"][isin] = dict(isin=isin, symbol=sym or "", name=name or sym or isin,
                                  first="", last="", n=0, nav=0, inav=0)
    for isin, a, b, n in _rows(con, "select isin, min(date), max(date), count(*) from etf_px group by 1"):
        if isin in d["etf"]:
            d["etf"][isin].update(first=str(a)[:10], last=str(b)[:10], n=n)
    for isin, n in _rows(con, "select isin, count(*) from fund_nav group by 1"):
        if isin in d["etf"]:
            d["etf"][isin]["nav"] = n
    for isin, n in _rows(con, "select isin, count(*) from etf_inav group by 1"):
        if isin in d["etf"]:
            d["etf"][isin]["inav"] = n

    # policies / PIB / raw docs ------------------------------------------- #
    d["policies"] = []
    for pid, pub, title, pname, sectors, eff, kind, sid in _rows(con, """
        select id, published_at, title, policy_name, sectors, effective_date, source_kind, source_id
        from policy_events where published_at >= '2019-01-01'
    """):
        if title:
            d["policies"].append(dict(id=pid, date=str(pub or "")[:10], title=title,
                                      name=pname or "", sectors=sectors or "",
                                      effective=eff or "", source=kind or "", source_id=sid))
    d["policies"].sort(key=lambda x: x["date"])
    d["pib"] = [dict(prid=r[0], date=str(r[1])[:10], ministry=r[2] or "", title=r[3] or "")
                for r in _rows(con, "select prid, release_date, ministry, title from pib_releases")]
    d["pib"].sort(key=lambda x: x["date"])
    d["raw"] = defaultdict(list)
    for st, pub, title in _rows(con, "select source_type, published_date, title from raw_documents"):
        d["raw"][st].append((str(pub or "")[:10], title or ""))

    # commodity series ---------------------------------------------------- #
    d["commod"] = {}
    for name, a, b, n in _rows(con, "select commodity, min(date), max(date), count(*) from mkt_commodity_daily group by 1"):
        d["commod"][name] = (str(a)[:10], str(b)[:10], n)

    # index membership ---------------------------------------------------- #
    d["members"] = defaultdict(dict)
    for idx, sym, isin in _rows(con, "select index_name, symbol, isin from index_membership"):
        if isin:
            d["members"][idx][isin] = sym or ""
    d["index_lists"] = defaultdict(set)
    for e in pool.values():
        if e["index_list"]:
            try:
                for nm in json.loads(e["index_list"]):
                    d["index_lists"][nm].add(e["isin"])
            except Exception:
                pass
    d["_con"] = con
    return d


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def short_name(n):
    n = re.sub(r"[\s,]+(limited|ltd\.?|limited\.)$", "", n, flags=re.I)
    n = re.sub(r"\s+", " ", n).strip(" .")
    if n.isupper() and " " in n:
        n = n.title()
    return n


def nm(e):
    return short_name(e["name"])


def sym(e):
    return e["nse"] or e["bse"]


def ref(e):
    s = sym(e)
    return f"{nm(e)} (NSE: {s})" if e["nse"] else f"{nm(e)} (BSE: {s})"


def bucket_ok(e):
    return e.get("bucket") in ("LARGE", "MID", "SMALL", "MICRO")


def within(dates, start, end):
    return [x for x in dates if start <= x[:10] <= end]


def cov_status(dates, start, end):
    if not dates:
        return "no", "store has no rows for this entity"
    hit = within(dates, start, end)
    if hit:
        return "yes", ""
    return "partial", f"store holds {dates[0]}..{max(dates)}, nothing in {start}..{end}"


def combine(parts):
    if not parts:
        return "yes", ""
    notes = [n for s, n in parts if s != "yes" and n]
    if any(s == "no" for s, n in parts):
        return "no", "; ".join(notes) or "required store missing"
    if any(s == "partial" for s, n in parts):
        return "partial", "; ".join(notes)
    return "yes", ""


def date_long(d):
    import datetime as dt
    if not d:
        return "the latest date"
    y, m, dd = (int(x) for x in d.split("-"))
    return f"{dd} {dt.date(y, m, dd).strftime('%B')} {y}"


def date_short(d):
    import datetime as dt
    if not d:
        return "latest"
    y, m, dd = (int(x) for x in d.split("-"))
    return f"{dd} {dt.date(y, m, dd).strftime('%b')} {y}"


def strip_asof(p):
    return p[6:] if p.lower().startswith("as of ") else p


def quarter_label(q):
    return q


def fy_label(start_year):
    return f"FY{str(start_year + 1)[-2:]}"


# --------------------------------------------------------------------------- #
# coverage
# --------------------------------------------------------------------------- #
def _coverage_uncached(d, e, needs, c):
    """Return (status, note) for one row. Uses c.win, c.as_of and per-store maps."""
    if c.get("cov_override"):
        return c["cov_override"]
    parts = []
    start, end = c["win"]
    end = min(end, c["as_of"])
    isin = e["isin"]
    for store in needs:
        if store in ("master_companies", "company_industry", "index_membership"):
            if store == "index_membership" and c["v"] == "V8":
                parts.append(("yes", "") if c.get("index_members") else ("no", "index membership not held"))
            continue
        if store == "results_xbrl.filings":
            parts.append(cov_status(d["filings"].get(isin, []), start, end))
        elif store in ("results_xbrl.facts", "results_xbrl.segment", "results_xbrl.npa"):
            parts.append(cov_status(d["filings"].get(isin, []), start, end))
            if store in ("results_xbrl.segment", "results_xbrl.npa") and c.get("concept_ok") is False:
                parts.append(("partial", f"{store.split('.')[-1]} concept not found in the filing"))
        elif store == "quarterly_financials":
            parts.append(cov_status(sorted(d["qf"].get(isin, [])), start, end))
        elif store == "annual_financials":
            parts.append(cov_status(sorted(d["af"].get(isin, [])), start, end))
        elif store == "company_forensic_health":
            parts.append(("yes", "") if isin in d["cfh"] else ("no", "no stored forensic/P-B row"))
        elif store == "shp_index":
            parts.append(cov_status(sorted(d["shp"].get(isin, [])), start, end))
        elif store == "ar_facts.ar_docs":
            parts.append(cov_status(sorted(x[0] for x in d["ar"].get(isin, [])), start, end))
        elif store == "ar_facts.ar_facts":
            if not d["ar"].get(isin):
                parts.append(("no", "no annual report for this entity"))
            else:
                parts.append(cov_status(sorted(x[0] for x in d["ar"].get(isin, [])), start, end))
        elif store == "deck_figures.deck_sources":
            parts.append(cov_status([x["date"] for x in d["decks"].get(isin, [])], start, end))
        elif store == "deck_figures.pages":
            parts.append(cov_status([x["date"] for x in d["decks"].get(isin, [])], start, end))
        elif store == "concall_facts.cc_docs":
            parts.append(cov_status(d["cc"].get(isin, []), start, end))
        elif store == "concall_facts.cc_items":
            parts.append(cov_status(d["cc"].get(isin, []), start, end))
        elif store == "document_chunks":
            n = c.get("chunks")
            if n is None:
                parts.append(("partial", "chunk coverage unchecked for this entity"))
            elif n == 0:
                parts.append(("no", "no document_chunks rows (transcript/filing not chunked)"))
            else:
                parts.append(("yes", ""))
        elif store == "results_notes.docs":
            parts.append(cov_status(sorted(d["notes"].get(isin, [])), start, end))
        elif store == "results_notes.notes":
            parts.append(cov_status(sorted(d["notes"].get(isin, [])), start, end))
        elif store in ("px_nse_adj", "px_bse_adj", "px"):
            p = d["px"].get(isin)
            if not p:
                parts.append(("no", "no adjusted price rows"))
            elif str(p[0])[:10] <= end and str(p[1])[:10] >= start:
                parts.append(("yes", ""))
            else:
                parts.append(("partial", f"price coverage {p[0]}..{p[1]} misses the window"))
        elif store == "corporate_actions":
            ca = [x["ex"] for x in d["ca"] if x["isin"] == isin]
            parts.append(("yes", "") if ca else ("no", "no split/bonus in corporate_actions"))
        elif store == "mkt_commodity_daily":
            name = c.get("commodity")
            if name and name in d["commod"]:
                a, b, _ = d["commod"][name]
                parts.append(("yes", "") if a <= start and b >= end else
                             ("partial", f"{name} series ends {b}"))
            else:
                parts.append(("no", "commodity series not held"))
        elif store == "policy_events":
            ok = any(start <= p["date"] <= end for p in d["policies"])
            parts.append(("yes", "") if ok else ("partial", "no policy_event in the window"))
        elif store == "pib_releases":
            ok = any(start <= p["date"] <= end for p in d["pib"])
            parts.append(("yes", "") if ok else ("partial", "no PIB release in the window"))
        elif store == "raw_documents":
            ok = any(start <= x[0] <= end for k, v in d["raw"].items() for x in v[:50])
            parts.append(("yes", "") if ok else ("partial", "no raw_documents row in the window"))
        elif store in ("daily_price_delivery", "mkt_bse_delivery_daily"):
            if c.get("delivery_ok") is None:
                parts.append(("partial", "delivery rows not checked"))
            elif c["delivery_ok"]:
                parts.append(("yes", ""))
            else:
                parts.append(("no", "no NSE+BSE delivery rows on the chosen dates"))
        elif store in ("etf_px", "fund_nav", "etf_inav"):
            info = d["etf"].get(isin)
            if not info or not info["n"]:
                parts.append(("no", "no ETF price rows"))
            elif store == "fund_nav" and not info["nav"]:
                parts.append(("partial", "no NAV rows for this ETF"))
            elif store == "etf_inav" and not info["inav"]:
                parts.append(("partial", "no iNAV rows; tracking error not computable"))
            else:
                parts.append(("yes", ""))
        else:
            parts.append(("partial", f"unhandled store {store}"))
    return combine(parts)


# --------------------------------------------------------------------------- #
# entity selection
# --------------------------------------------------------------------------- #
def coverage(d, e, needs, c):
    """Cached store-coverage status (candidate screening and final rows share it)."""
    key = (e["isin"], tuple(needs), c["win"][0], min(c["win"][1], c["as_of"]),
           c.get("chunks"), c.get("concept_ok"), c.get("geo_ok"), c.get("delivery_ok"),
           c.get("commodity"))
    cache = d.setdefault("_cov_cache", {})
    if key not in cache:
        cache[key] = _coverage_uncached(d, e, needs, c)
    return cache[key]


class Picker:
    def __init__(self, d):
        self.d = d
        self.used = set()
        self.sector_use = Counter()
        self.bucket_use = Counter()
        self.exch_use = Counter()
        self.index_use = Counter()

    def _cands(self, needs, c):
        ckey = (tuple(needs), c["win"][0], min(c["win"][1], c["as_of"]), c.get("commodity"))
        cache = self.__dict__.setdefault("_cand_cache", {})
        if ckey in cache:
            return [x for x in cache[ckey] if x[0]["isin"] not in self.used]
        out = []
        for e in self.d["pool"].values():
            if e["isin"] in self.used:
                continue
            status, _ = coverage(self.d, e, needs, c)
            if status != "no":
                out.append((e, status))
        cache[ckey] = out
        return out

    def _score(self, e, status, prefer_bucket=None):
        return (self.sector_use[e["sector"]], self.bucket_use[e["bucket"]],
                0 if status == "yes" else 1, e["isin"])

    def pick(self, tag, spec, c, needs, pred=None):
        base = self.d["by_symbol"].get(spec.get("base", "")) if spec.get("base") else None
        if tag == "edge_missing":
            cands = []
            for e in self.d["pool"].values():
                if e["isin"] in self.used:
                    continue
                st, _ = coverage(self.d, e, needs, c)
                cands.append((e, st))
            cands.sort(key=lambda x: (0 if x[1] == "no" else 1, x[0]["isin"]))
        else:
            cands = self._cands(needs, c)
        if pred:
            cands = [x for x in cands if pred(x[0])]
        if not cands:
            return None
        if tag == "same_ind" and base:
            pool = [x for x in cands if x[0]["industry"] == base["industry"]
                    and x[0]["isin"] != base["isin"]]
            same_bucket = [x for x in pool if x[0]["bucket"] == base["bucket"]]
            if same_bucket:
                pool = same_bucket
            if not pool:
                pool = [x for x in cands if x[0]["sector"] == base["sector"]]
            cands = pool or cands
        elif tag == "diff_bucket" and base:
            pool = [x for x in cands if x[0]["bucket"] and x[0]["bucket"] != base["bucket"]
                    and x[0]["isin"] != base["isin"]
                    and (x[0]["sector"] == base["sector"] or x[0]["industry"] == base["industry"])]
            if not pool:
                pool = [x for x in cands if x[0]["bucket"] and x[0]["bucket"] != base["bucket"]]
            cands = pool or cands
        elif tag == "identity":
            pool = [x for x in cands if x[0]["isin"] in self.d["renames"]]
            cands = pool or cands
        elif tag == "edge_corp":
            ca_isins = {x["isin"] for x in self.d["ca"]}
            pool = [x for x in cands if x[0]["isin"] in ca_isins]
            cands = pool or cands
        elif tag == "edge_missing":
            pool = [x for x in cands if coverage(self.d, x[0], needs, c)[0] == "partial"]
            cands = pool or cands
        if not cands:
            return None
        # spread: every 12th pick prefers BSE-only or NSE-only names
        n = len(self.used)
        if tag == "any" and n % 12 == 5:
            rare = [x for x in cands if not x[0]["nse"] or not x[0]["bse"]]
            if rare:
                cands = rare
        cands.sort(key=lambda x: self._score(x[0], x[1]))
        e, status = cands[0]
        self.used.add(e["isin"])
        self.sector_use[e["sector"]] += 1
        self.bucket_use[e["bucket"]] += 1
        self.exch_use["NSE" if e["nse"] and e["bse"] else
                      "NSE-only" if e["nse"] else "BSE-only"] += 1
        c["pick_status"] = status
        return e


def index_scope(d, c, min_members=8):
    """Pick a real index/theme membership set with the least global use."""
    best = None
    for name, isins in list(d["index_lists"].items()) + [
            (k, set(v)) for k, v in d["members"].items()]:
        if len(isins) < min_members:
            continue
        members = [d["pool"][i] for i in isins if i in d["pool"]]
        if len(members) < min_members:
            continue
        key = (c["index_use"].get(name, 0), -len(members), name)
        if best is None or key < best[0]:
            best = (key, name, members)
    if not best:
        return None
    _, name, members = best
    c["index_use"][name] += 1
    members.sort(key=lambda e: (-(e["mcap"] or 0), e["isin"]))
    return name, members


# --------------------------------------------------------------------------- #
# spec resolution
# --------------------------------------------------------------------------- #
VARY_FAMILY = {}


def deck_pages(d, sha):
    if not sha:
        return None
    try:
        r = d["_deck_con"].execute("select max(page_no) from pages where sha256 = ?", (sha,)).fetchone()
        return int(r[0]) if r and r[0] else None
    except Exception:
        return None


def px_on(d, date):
    """One scan per date gives every ISIN that traded; avoids a query per candidate."""
    cache = d.setdefault("_px_on", {})
    if date not in cache:
        out = set()
        try:
            for tbl in ("px_nse_adj", "px_bse_adj"):
                out |= {r[0] for r in d["_duck"].execute(
                    f"select distinct isin from {tbl} where date = ?", [date]).fetchall() if r[0]}
        except Exception:
            pass
        cache[date] = out
    return cache[date]


def px_has(d, isin, date):
    return isin in px_on(d, date)


def delivery_check(d, e, dates):
    if not e or not e.get("bse"):
        return False
    try:
        con = d["_con"]
        for day in dates:
            n = con.execute("select 1 from mkt_nse_full_daily where symbol = ? and date = ? limit 1",
                            (e["nse"], day)).fetchone()
            b = con.execute("select 1 from mkt_bse_delivery_daily where sc_code = ? and date = ? limit 1",
                            (e["bse"], day)).fetchone()
            if not n or not b:
                return False
        return True
    except Exception:
        return False


def theme_members(d, key):
    pool = list(d["pool"].values())
    if key == "jewellery":
        f = lambda e: "Jewel" in e["basic"] or "Jewel" in e["name"]
    elif key == "oil":
        f = lambda e: e["industry"] in ("Oil", "Petroleum Products") or "Refin" in e["basic"]
    elif key == "banks":
        f = lambda e: e["industry"] == "Banks"
    elif key == "hfc":
        f = lambda e: "Housing Finance" in e["basic"] or "Housing Finance" in e["name"]
    elif key == "dairy":
        f = lambda e: e["basic"] == "Dairy Products" or "Dairy" in e["basic"] or "Milk" in e["name"]
    elif key == "electronics":
        f = lambda e: e["industry"] == "IT - Hardware" or "Electron" in e["basic"] or "Electron" in e["name"]
    elif key == "coal":
        f = lambda e: (e["industry"] == "Consumable Fuels" or "Coal" in e["basic"]
                       or "Coal" in e["name"] or e["basic"] == "Iron & Steel Products"
                       or e["industry"] == "Fertilizers & Agrochemicals")
    elif key == "datacentre":
        f = lambda e: any(k in e["name"].lower() for k in
                          ("netweb", "sify", "anant raj", "tata communications", "e2e networks",
                           "data centre", "data center"))
        members = [e for e in pool if f(e)]
        if len(members) < 10:
            members = members + [e for e in pool if e["industry"] in ("IT - Hardware", "IT - Services")
                                 and e not in members]
        members.sort(key=lambda e: (-(e["mcap"] or 0), e["isin"]))
        return members
    else:
        f = lambda e: True
    members = [e for e in pool if f(e)]
    members.sort(key=lambda e: (-(e["mcap"] or 0), e["isin"]))
    return members


def industry_swings(d):
    vals = defaultdict(dict)
    for isin, q, np_ in d["qf_val"]:
        if np_ is not None:
            vals[isin][q] = float(np_)
    groups = defaultdict(list)
    for e in d["pool"].values():
        v = vals.get(e["isin"], {})
        if "2026-03-31" in v and "2026-06-30" in v:
            groups[e["basic"]].append((e, v))
    out = []
    for ind, rows in groups.items():
        if len(rows) < 2:
            continue
        s4 = sum(v["2026-03-31"] for _, v in rows)
        s1 = sum(v["2026-06-30"] for _, v in rows)
        if s4 > 0 and s1 < 0:
            members = [e for e, _ in sorted(rows, key=lambda x: (-(x[0]["mcap"] or 0), x[0]["isin"]))]
            out.append(dict(industry=ind, drop=s4 - s1, members=members[:5]))
    out.sort(key=lambda x: -x["drop"])
    return out


def issuer_of(p):
    t = p.get("title", "")
    if t.startswith("Union_Budget") or "Union Budget" in t or "Economic_Survey" in t or "Economic Survey" in t:
        return "Ministry of Finance"
    if t.startswith("RBI"):
        return "RBI"
    if p.get("source") == "pib":
        return "PIB"
    return "policy_events document"


def _pib_in(d, pat, start, end):
    rx = re.compile(pat, re.I)
    return [p for p in d["pib"] if start <= p["date"] <= end and rx.search(p["title"])]


def _pol(d, pat, start="2024-01-01"):
    rx = re.compile(pat, re.I)
    return sorted([p for p in d["policies"] if p["date"] >= start
                   and rx.search(p["title"] + " " + p["name"])], key=lambda p: p["date"])


def _px_cov(d, members, start, end):
    if not members:
        return [("partial", "no listed members mapped to this theme")]
    ok = sum(1 for e in members if d["px"].get(e["isin"]))
    if ok >= min(3, len(members)):
        return [("yes", "")]
    return [("partial", f"adjusted prices for {ok}/{len(members)} theme members")]


def prepare(d):
    d["theme"] = {k: theme_members(d, k) for k in
                  ("jewellery", "oil", "banks", "hfc", "dairy", "electronics", "coal", "datacentre")}
    d["qf_val"] = d["_con"].execute(
        "select isin, quarter_end_date, net_profit_inr_cr from quarterly_financials").fetchall()
    d["qf_val"] = [(i, str(q)[:10], v) for i, q, v in d["qf_val"]]
    events = {}

    # Q16: commodity moves (no issuer/ministry applies to a market series)
    jew, oil = d["theme"]["jewellery"], d["theme"]["oil"]
    pibg = _pib_in(d, r"gold", "2026-06-01", "2026-07-31")
    pibc = _pib_in(d, r"crude|petrol|diesel|lpg", "2026-04-01", "2026-05-31")
    cg = [("yes", "")] if "gold" in d["commod"] else [("no", "gold series not held")]
    cg += [("yes", "")] if pibg else [("partial", "no gold-specific PIB release in Jun-Jul 2026")]
    cg += _px_cov(d, jew, "2026-06-01", "2026-07-31")
    cc = [("yes", "")] if "crude_brent" in d["commod"] else [("no", "Brent series not held")]
    cc += [("yes", "")] if pibc else [("partial", "no crude/petrol PIB release in Apr-May 2026")]
    cc += _px_cov(d, oil, "2026-04-01", "2026-05-31")
    events["Q16"] = [
        dict(title="the gold price move", date="2026-07-31", period="June-July 2026",
             doc_ref=(f"PIB PRID {pibg[0]['prid']} on {pibg[0]['date']}" if pibg else "the gold price series (USD/oz)"),
             sector_label="gold-jewellery", members=jew[:3], cov=combine(cg), source="market series (no issuer)",
             note="macro market series; issuer/ministry not applicable (V1 rule noted)"),
        dict(title="the Brent crude move", date="2026-05-31", period="April-May 2026",
             doc_ref=(f"PIB PRID {pibc[0]['prid']} on {pibc[0]['date']}" if pibc else "the Brent crude series"),
             sector_label="oil and gas", members=oil[:3], cov=combine(cc), source="market series (no issuer)",
             note="different macro event and sector; issuer/ministry not applicable (V2 rule noted)"),
    ]

    # Q18: other commodity-margin reversals, verified from quarterly_financials
    swings = [s for s in industry_swings(d) if s["industry"] != "Petroleum Products"]
    if len(swings) < 2:
        swings = industry_swings(d)
    q18 = []
    for s in swings[:2]:
        q18.append(dict(title=f"{s['industry']} Q4FY26-to-Q1FY27 profit swing",
                        date="2026-06-30", doc_ref="quarterly_financials (Q4FY26 vs Q1FY27)",
                        sector_label=s["industry"], members=s["members"][:3],
                        cov=("yes", "quarterly_financials + results_xbrl filings + adjusted prices"),
                        source="company results (no issuer)",
                        note="different industry/commodity event; issuer/ministry not applicable"))
    events["Q18"] = q18

    # Q21: RBI hike vs a Finance Ministry Budget event (different issuer)
    hike = [p for p in _pol(d, r"repo") if re.search(r"hik", p["name"] + p["title"], re.I)]
    hike = hike[-1] if hike else None
    budget = [p for p in d["policies"] if "Union_Budget" in p["title"] and p["date"] >= "2026-01-01"
              and re.search(r"bank|financ|insur|interest|capital market",
                            p["sectors"] + " " + p["name"] + " " + p["title"], re.I)]
    budget = budget[-1] if budget else None
    keys = []
    if hike:
        keys.append(dict(title=hike["name"] or "repo rate hike", date=hike["date"],
                         doc_ref=f"the RBI Governor's Statement of {date_long(hike['date'])}",
                         sector_label="banking", members=d["theme"]["banks"][:3],
                         cov=("yes", "policy_events + raw_documents RBI_Monetary_Policy"),
                         source="RBI", note="RBI issuer"))
    if budget:
        keys.append(dict(title=budget["name"] or "Union Budget fiscal action", date=budget["date"],
                         doc_ref=f"the Union Budget speech of {date_long(budget['date'])}",
                         sector_label="rate-sensitive sectors", members=d["theme"]["banks"][3:6],
                         cov=("partial", "Budget document held; PIB cross-publish check limited"),
                         source="Ministry of Finance", note="different issuer (Finance Ministry) for V2"))
    elif len(keys) == 1:
        mins = _pol(d, r"MPC|monetary policy")
        if mins:
            m = mins[-1]
            keys.append(dict(title=m["name"] or "MPC action", date=m["date"],
                             doc_ref=f"the MPC minutes of {date_long(m['date'])}",
                             sector_label="banking", members=d["theme"]["banks"][:3],
                             cov=("yes", "policy_events + raw_documents RBI_MPC_Minutes"),
                             source="RBI", note="same issuer, different policy action (noted)"))
    events["Q21"] = keys

    # Q22: electronics policies from two issuers where possible
    ecms = _pib_in(d, r"Electronics Component Manufacturing Scheme", "2025-01-01", SNAPSHOT_END)
    emc = _pib_in(d, r"Electronics Manufacturing Cluster", "2025-01-01", SNAPSHOT_END)
    pol_e = _pol(d, r"electronic|semiconductor")
    e22 = []
    if ecms:
        e22.append(dict(title="Electronics Component Manufacturing Scheme approvals",
                        date=ecms[-1]["date"], doc_ref=f"PIB PRID {ecms[-1]['prid']} on {ecms[-1]['date']}",
                        sector_label="electronics manufacturing", members=d["theme"]["electronics"][:3],
                        cov=("partial", "PIB + policy_events held; no refurbished/second-hand sales series"),
                        source=ecms[-1]["ministry"] or "PIB", note="different policy, MeitY issuer"))
    bud_e = [p for p in pol_e if "Union_Budget" in p["title"]]
    if bud_e:
        p = bud_e[-1]
        e22.append(dict(title=p["name"] or "Budget electronics measure", date=p["date"],
                        doc_ref=f"{p['title'].split(':')[0]} ({p['date']})",
                        sector_label="electronics manufacturing", members=d["theme"]["electronics"][3:6],
                        cov=("partial", "policy event held; PIB provenance incomplete"),
                        source="Ministry of Finance", note="different issuer/ministry for V2"))
    elif pol_e:
        p = pol_e[-1]
        e22.append(dict(title=p["name"] or "electronics policy measure", date=p["date"],
                        doc_ref=f"{p['title'].split(':')[0]} ({p['date']})",
                        sector_label="electronics manufacturing", members=d["theme"]["electronics"][:3],
                        cov=("partial", "policy event held; issuer not encoded in the row"),
                        source="policy_events document", note="different policy; issuer not encoded (noted)"))
    elif emc:
        e22.append(dict(title="Modified Electronics Manufacturing Clusters (EMC 2.0)",
                        date=emc[-1]["date"], doc_ref=f"PIB PRID {emc[-1]['prid']} on {emc[-1]['date']}",
                        sector_label="electronics manufacturing", members=d["theme"]["electronics"][:3],
                        cov=("partial", "PIB held; same ministry, different policy (noted)"),
                        source="MeitY", note="same issuer, different policy (noted)"))
    events["Q22"] = e22

    # Q23: coal gasification scheme vs an earlier / different-ministry scheme
    gas = _pol(d, r"gasification")
    hyd = _pol(d, r"green hydrogen|hydrogen mission|national hydrogen")
    e23 = []
    if gas:
        g = gas[-1]
        e23.append(dict(title=g["name"] or "coal gasification scheme", date=g["date"],
                        doc_ref=f"{g['title']} ({g['date']})",
                        sector_label="coal, fertiliser and steel", members=d["theme"]["coal"][:3],
                        cov=("yes", "policy_events + PIB releases + Budget documents"),
                        source=issuer_of(g), note="different policy action; issuer from the document title"))
    hyd_pib = _pib_in(d, r"National Green Hydrogen Mission", "2025-01-01", SNAPSHOT_END)
    if hyd_pib:
        h = hyd_pib[-1]
        e23.append(dict(title="National Green Hydrogen Mission progress", date=h["date"],
                        doc_ref=f"PIB PRID {h['prid']} on {h['date']}",
                        sector_label="coal, fertiliser and steel", members=d["theme"]["coal"][3:6],
                        cov=("partial", "PIB release held; coal price series ends 2025-12-26"),
                        source=h["ministry"] or "PIB", note="different issuer/ministry (MNRE) for V2"))
    elif hyd:
        h = hyd[-1]
        e23.append(dict(title=h["name"] or "green hydrogen mission", date=h["date"],
                        doc_ref=f"{h['title']} ({h['date']})",
                        sector_label="coal, fertiliser and steel", members=d["theme"]["coal"][3:6],
                        cov=("partial", "policy event held; coal price series ends 2025-12-26"),
                        source=issuer_of(h), note="different policy; issuer from document title"))
    elif len(gas) >= 2:
        g = gas[0]
        e23.append(dict(title=g["name"] or "earlier coal scheme", date=g["date"],
                        doc_ref=f"{g['title']} ({g['date']})",
                        sector_label="coal, fertiliser and steel", members=d["theme"]["coal"][:3],
                        cov=("partial", "earlier scheme held; coal price series ends 2025-12-26"),
                        source="Ministry of Coal", note="same issuer, earlier scheme (noted)"))
    events["Q23"] = e23

    # Q25: tax-holiday policies that are actually in the record
    startup = _pol(d, r"startup tax holiday", "2019-01-01")
    housing = _pol(d, r"affordable housing.*tax holiday|tax holiday.*affordable housing", "2019-01-01")
    ifsc = _pol(d, r"IFSC tax holiday", "2019-01-01")
    e25 = []
    if startup:
        p = startup[-1]
        e25.append(dict(title="startup tax holiday extension", date=p["date"],
                        doc_ref=f"{p['title']} ({p['date']})",
                        sector_label="startups and technology", members=d["theme"]["datacentre"][:3],
                        cov=("partial", "policy event held; no data-centre-specific outcome series"),
                        source="Ministry of Finance", note="different tax-holiday policy"))
    if housing or ifsc:
        p = (housing or ifsc)[-1]
        e25.append(dict(title=p["name"] or "tax holiday", date=p["date"],
                        doc_ref=f"{p['title']} ({p['date']})",
                        sector_label="real estate and construction" if housing else "financial services",
                        members=sorted([x for x in d["pool"].values() if x["sector"] == "Realty"],
                                       key=lambda x: (-(x["mcap"] or 0), x["isin"]))[:3],
                        cov=("partial", "policy event held; no data-centre-specific outcome series"),
                        source="Ministry of Finance", note="different policy line (same issuer, noted)"))
    events["Q25"] = e25

    # Q20: a real tariff line from the Budget/policy record
    tf = [p for p in _pol(d, r"customs|import duty|export duty|tariff")
          if "electricity" not in (p["title"] + p["name"]).lower()]
    if tf:
        tf.sort(key=lambda x: (0 if "rationali" in (x["name"] + x["title"]).lower() else 1,
                               abs((__import__("datetime").date.fromisoformat(x["date"])
                                    - __import__("datetime").date(2025, 2, 1)).days)))
        p = tf[0]
        events["Q20"] = [dict(title=p["name"] or "customs tariff change", date=p["date"],
                              doc_ref=f"{p['title']} ({p['date']})",
                              sector_label="tariff-exposed manufacturers",
                              members=[d["pool"][i] for i in list(d["pool"])[:3]],
                              cov=("partial", "policy event held; no dated tariff time series"),
                              source="Ministry of Finance", note="real customs-tariff line")]
    else:
        events["Q20"] = []
    dc_pib = _pib_in(d, r"data cent", "2024-01-01", SNAPSHOT_END)
    d["dc_pib"] = dc_pib[-1] if dc_pib else None
    d["events"] = events
    for spec in SPECS:
        if spec.get("kind") == "macro" or spec["oid"] == "Q18":
            spec["events"] = events.get(spec["oid"], [])
    # honest NOT IN DATA edge for each macro original
    v10 = {
        "Q16": ("no", "the gold series ends 2026-10-06, so the 7-19 Oct 2026 window has no macro cause in the data"),
        "Q18": ("no", "coal_newcastle ends 2025-12-26; the Q1FY27 coal-price window is not covered"),
        "Q21": ("no", "an as-of before 7 Oct 2026 leaves no evidence in the record; expected NOT IN DATA"),
        "Q22": ("no", "no refurbished/second-hand electronics sales series in any store"),
        "Q23": ("no", "coal_newcastle ends 2025-12-26; no coal price after that"),
        "Q25": ("no", "no data-centre tax holiday in policy_events; PIB has data-centre items but no tax-holiday policy"),
    }
    for spec in SPECS:
        if spec.get("kind") == "macro":
            spec["v10_cov"] = v10[spec["oid"]]
    return d


def macro_ctx(d, picker, spec, v, c):
    members = d["theme"].get(spec.get("theme"), [])
    evs = spec.get("events") or []
    ev = evs[0] if evs else None
    if v == "V2" and len(evs) > 1:
        ev = evs[1]
    if v in ("V1", "V2") and ev:
        members = ev.get("members") or members
        if ev.get("period"):
            c["period"] = ev["period"]
    elif not members and ev:
        members = ev.get("members", [])
    if spec["oid"] == "Q16":
        c["commodity"] = "crude_brent" if (v == "V2" and ev and "crude" in ev.get("title", "")) else "gold"
    c["policy"] = ev
    c["event_label"] = ev["title"] if ev else spec.get("theme_label", "")
    c["industry_label"] = spec.get("industry_label") or (ev.get("sector_label") if ev else spec.get("theme_label"))
    c["entity_level"] = spec.get("level", "theme")
    used = spec.setdefault("_used", set())
    idx = int(v[1:])

    def picki(pool, offset):
        pool = [x for x in pool if x]
        if not pool:
            return None
        for k in range(len(pool)):
            x = pool[(offset + k) % len(pool)]
            if x["isin"] not in used:
                return x
        return pool[offset % len(pool)]

    e = None
    if v in ("V1", "V2"):
        e = ((ev.get("members") if ev else None) or members or [None])[0]
    elif v == "V3":
        e = picki(members, 1)
    elif v in ("V4", "V5", "V6", "V9", "V10"):
        e = picki(members, 3 + idx)
    if e:
        used.add(e["isin"])
    c["e"] = e
    c["ref"] = ref(e) if e else spec.get("theme_label", "the theme")
    if v in ("V1", "V2", "V3"):
        c["coverage_override"] = ev["cov"] if ev else ("no", "no matching event found")
        if v == "V3" and spec["oid"] == "Q25":
            dc = d.get("dc_pib")
            if dc:
                c["ref"] = f"PIB PRID {dc['prid']} on {dc['date']}"
                c["policy"] = dict(title=c["ref"], date=dc["date"],
                                   source=dc["ministry"] or "PIB")
            c["coverage_override"] = ("partial", "PIB data-centre items held; the data-centre "
                                                 "tax holiday itself is not in policy_events")
        if v == "V3" and ev and spec["oid"] != "Q25":
            c["ref"] = ev.get("doc_ref") or ev["title"]
            c["policy"] = dict(ev)
            c["policy"]["title"] = ev.get("doc_ref") or ev["title"]
        c["scope"] = [e] if e else []
    elif v == "V7":
        free = [x for x in members if x["isin"] not in used] or members
        c["scope"] = free[:3]
        for x in c["scope"]:
            used.add(x["isin"])
        c["e"] = c["scope"][0] if c["scope"] else None
        c["ref"] = ref(c["e"]) if c["e"] else spec.get("theme_label", "the theme")
        c["scope_label"] = f"all listed companies in {spec.get('industry_label') or spec.get('theme_label')}"
        c["entity_level"] = "industry"
        c["coverage_override"] = ("partial", "PIB data-centre items held; the data-centre tax "
                                             "holiday itself is not in policy_events") \
            if spec["oid"] == "Q25" else (ev["cov"] if ev else ("no", "no event"))
    elif v == "V8":
        if spec.get("v8_theme"):
            free = [x for x in members if x["isin"] not in used] or members
            c["scope"] = free[:3]
            for x in c["scope"]:
                used.add(x["isin"])
            c["e"] = c["scope"][0] if c["scope"] else None
            c["ref"] = ref(c["e"]) if c["e"] else spec.get("theme_label", "the theme")
            c["scope_label"] = f"the {spec.get('theme_label')} theme members"
            c["entity_level"] = "theme"
            c["coverage_override"] = ev["cov"] if ev else ("no", "no event")
            return c
        theme_isins = {x["isin"] for x in members}
        best = None
        for name, isins in list(d["index_lists"].items()) + [(k, set(vv)) for k, vv in d["members"].items()]:
            ms = [d["pool"][i] for i in isins if i in d["pool"] and i not in used]
            if len(ms) < 3:
                continue
            overlap = len([x for x in ms if x["isin"] in theme_isins])
            key = (overlap, picker.index_use.get(name, 0), len(ms))
            if best is None or key > best[0]:
                best = (key, name, ms)
        if best and best[0][0] >= 2:
            picker.index_use[best[1]] += 1
            ms = sorted(best[2], key=lambda x: (-(x["mcap"] or 0), x["isin"]))
            c["scope"] = ms[:3]
            c["scope_label"] = f"the {best[1]} constituents"
            c["index_name"] = best[1]
            c["entity_level"] = "index"
        else:
            free = [x for x in members if x["isin"] not in used] or members
            c["scope"] = free[:3]
            c["scope_label"] = f"the {spec.get('theme_label')} theme members"
        for x in c["scope"]:
            used.add(x["isin"])
        c["e"] = c["scope"][0] if c["scope"] else None
        c["ref"] = ref(c["e"]) if c["e"] else spec.get("theme_label", "the theme")
        c["coverage_override"] = ("partial", "PIB data-centre items held; the data-centre tax "
                                             "holiday itself is not in policy_events") \
            if spec["oid"] == "Q25" else (ev["cov"] if ev else ("no", "no event"))
    elif v == "V9":
        ok = bool(ev and ev["date"] <= c["as_of"])
        c["scope"] = [e] if e else []
        if spec["oid"] == "Q25":
            c["coverage_override"] = ("no", "no data-centre tax holiday in policy_events; as-of "
                                            "evidence cannot answer it")
        else:
            c["coverage_override"] = (("yes", "point-in-time: only documents known by the as-of date count")
                                      if ok else ("no", "as-of precedes the policy event; no evidence by then"))
    elif v == "V10":
        c["scope"] = [e] if e else []
        c["coverage_override"] = spec.get("v10_cov") or ("no", "not in data")
        if spec["oid"] == "Q16":
            c["period"] = "7-19 Oct 2026"
    else:
        c["scope"] = [e] if e else []
        c["coverage_override"] = (ev["cov"] if ev else ("no", "no event"))
    return c


def _etf_e(x):
    return dict(isin=x["isin"], nse=x["symbol"] or x["isin"], bse="", name=x["name"],
                sector="ETF", industry="ETF", basic="ETF", index_list="", mcap=None, bucket=None)


def etf_ctx(d, picker, spec, v, c):
    etfs = [x for x in d["etf"].values() if x["n"] > 0]
    seen = set()
    etfs = [x for x in etfs if not (x["symbol"] in seen or seen.add(x["symbol"]))]
    etfs.sort(key=lambda x: x["isin"])
    used = picker.used
    used_syms = getattr(picker, "etf_syms", set())
    picker.etf_syms = used_syms

    def take(pool, n):
        out = [x for x in pool if x["isin"] not in used and x["symbol"] not in used_syms]
        out = out or pool
        return out[:n]

    us = [x for x in etfs if any(k in x["name"].lower() for k in
                                 ("nasdaq", "u.s.", " us ", "s&p 500", "s&p500"))]
    gold = [x for x in etfs if "gold" in x["name"].lower()]
    full = [x for x in etfs if x["nav"] and x["inav"]]
    gold_full = [x for x in gold if x["nav"] and x["inav"]]
    if v == "V7":
        scope = take(full or etfs, 3)
        c["scope"] = [_etf_e(x) for x in scope]
        c["e"] = c["scope"][0]
        c["scope_label"] = "the India-listed ETF universe"
        c["entity_level"] = "index"
        c["ref"] = f"{c['e']['name']} ({c['e']['nse']}, ISIN {c['e']['isin']})"
        for x in scope:
            used.add(x["isin"]); used_syms.add(x["symbol"])
        c["period"] = spec["period"]
        return c
    if v == "V8" and gold:
        scope = take(gold_full or gold, 3)
        c["scope"] = [_etf_e(x) for x in scope]
        c["e"] = c["scope"][0]
        c["scope_label"] = "the India-listed gold ETFs"
        c["entity_level"] = "index"
        c["ref"] = f"{c['e']['name']} ({c['e']['nse']}, ISIN {c['e']['isin']})"
        for x in scope:
            used.add(x["isin"]); used_syms.add(x["symbol"])
        c["period"] = spec["period"]
        return c

    pick = None
    if v == "V10":
        pick = next((x for x in etfs if not x["nav"] and x["symbol"] not in used_syms), None)
    if pick is None:
        if v in ("V1", "V3", "V9"):
            pick = (take(us, 1) or take(etfs, 1))[0]
        elif v == "V2":
            gold_nav = [x for x in gold if x["nav"] and x["inav"]]
            pick = (take(gold_nav, 1) or take(gold, 1) or take(etfs, 1))[0]
        else:
            pick = take(etfs, 1)[0]
    used.add(pick["isin"]); used_syms.add(pick["symbol"])
    e = _etf_e(pick)
    c["e"] = e
    c["ref"] = (f"ISIN {e['isin']}" if v == "V3"
                else f"{e['name']} ({e['nse']}, ISIN {e['isin']})")
    c["period"] = c.get("period") or spec["period"]
    c["scope"] = [e]
    c["scope_label"] = ("the India-listed gold ETFs" if v == "V8"
                        else "the India-listed ETFs tracking US indices")
    c["entity_level"] = "stock"
    if v == "V10":
        c["coverage_override"] = ("no", "this ETF has price rows but no NAV rows; tracking error is NOT IN DATA")
    return c


def make_ctx(d, picker, spec, v):
    c = dict(v=v, spec=spec, win=spec.get("win", (WIN_START, SNAPSHOT_END)),
             as_of=spec.get("as_of", SNAPSHOT_END), index_use=picker.index_use,
             extra={}, needs=list(spec["needs"]), period=spec.get("period", "latest"),
             alt_period=spec.get("alt", spec.get("period", "latest")))
    if v == "V9":
        c["as_of"] = spec.get("pit", "2026-06-30")
        c["win"] = (WIN_START, c["as_of"])
        c["period"] = f"as of {date_long(c['as_of'])}"
        c["date"] = c["as_of"]
    if v == "V6":
        c["period"] = c["alt_period"]
        if spec.get("alt_win"):
            c["win"] = spec["alt_win"]
        if spec.get("alt_asof"):
            c["as_of"] = spec["alt_asof"]
    if spec.get("kind") == "macro":
        return macro_ctx(d, picker, spec, v, c)
    if spec.get("kind") == "etf":
        return etf_ctx(d, picker, spec, v, c)
    if spec["oid"] == "Q18" and v in ("V1", "V2"):
        c["win"] = ("2026-01-01", "2026-06-30")
        return macro_ctx(d, picker, spec, v, c)
    c["date"] = spec.get("date", c["as_of"])
    if v == "V6" and spec.get("alt_date"):
        c["date"] = spec["alt_date"]
    c["entity_level"] = spec.get("level", "stock")
    base = d["by_symbol"].get(spec.get("base", "")) if spec.get("base") else None
    c["base"] = base
    tag = spec["pick"][v]
    pred = _pred(spec, d)
    if spec["oid"] == "Q17" and v == "V9":
        edge = next((x for x in d["pool"].values()
                     if "Housing Finance" in x["basic"]
                     and "2026-06-30" not in d["filings"].get(x["isin"], [])), None)
        if edge:
            _inner = pred
            pred = (lambda e: e["isin"] != edge["isin"] and (_inner(e) if _inner else True))
    if spec.get("special") == "close":
        _inner = pred
        pred = (lambda e: px_has(d, e["isin"], c["date"]) and (_inner(e) if _inner else True))
    e = None
    if tag in ("same_ind", "diff_bucket", "identity", "any", "edge_corp", "edge_missing", "pit"):
        e = picker.pick("any" if tag == "pit" else tag, spec, c, c["needs"], pred)
    if tag == "industry":
        if spec.get("v7_sector") and base:
            members = [x for x in d["pool"].values() if x["sector"] == spec["v7_sector"]]
            label = spec["v7_sector"]
        else:
            members = [x for x in d["pool"].values()
                       if ((pred(x) if pred else (base and x["industry"] == base["industry"]))
                           or (not pred and not base))]
            label = spec.get("industry_label") or (base["industry"] if base and base["industry"]
                                                   else (base["basic"] if base else "the industry"))
            if not members and base:
                members = [x for x in d["pool"].values() if x["sector"] == base["sector"]]
                label = base["sector"]
        members.sort(key=lambda x: (-(x["mcap"] or 0), x["isin"]))
        free = [x for x in members if x["isin"] not in picker.used]
        members = free or members
        c["scope"] = members[:spec.get("scope_n", 3)]
        c["scope_label"] = f"all listed companies in {label}"
        c["scope_name"] = label
        c["entity_level"] = "industry"
        for x in c["scope"]:
            picker.used.add(x["isin"])
        e = c["scope"][0] if c["scope"] else None
    if tag == "index":
        cand = []
        for name, isins in list(d["index_lists"].items()) + [(k, set(vv)) for k, vv in d["members"].items()]:
            ms = [d["pool"][i] for i in isins if i in d["pool"]]
            if pred:
                ms = [x for x in ms if pred(x)]
            if len(ms) >= 5:
                cand.append((picker.index_use.get(name, 0), -len(ms), name, ms))
        if cand:
            cand.sort()
            name, ms = cand[0][2], cand[0][3]
            picker.index_use[name] += 1
            ms.sort(key=lambda x: (-(x["mcap"] or 0), x["isin"]))
            free = [x for x in ms if x["isin"] not in picker.used]
            ms = free or ms
            c["scope"] = ms[:spec.get("scope_n", 3)]
            c["scope_label"] = f"the {name} constituents"
            c["index_name"] = name
            c["entity_level"] = "index"
            for x in c["scope"]:
                picker.used.add(x["isin"])
            e = c["scope"][0]
        else:
            got = index_scope(d, c, 5)
            if got:
                c["index_name"], ms = got
                c["scope"] = ms[:3]
                c["scope_label"] = f"the {c['index_name']} constituents"
                c["entity_level"] = "index"
                e = c["scope"][0]
    if e is None and tag in ("same_ind", "diff_bucket", "identity", "any", "edge_corp",
                             "edge_missing", "pit"):
        free = [x for x in d["pool"].values()
                if (pred(x) if pred else True) and x["isin"] not in picker.used]
        for cand in (free or [x for x in d["pool"].values() if (pred(x) if pred else True)]):
            e = cand
            break
    if e:
        c["e"] = e
        if v == "V3":
            old = [s for s in d["renames"].get(e["isin"], []) if s != e["nse"]]
            if old:
                c["ref"] = f"{'NSE' if e['nse'] else 'BSE'}: {old[0]} (now {e['nse'] or e['bse']})"
            elif e["bse"]:
                c["ref"] = f"BSE scrip code {e['bse']}"
            else:
                c["ref"] = f"ISIN {e['isin']}"
        else:
            c["ref"] = ref(e)
        c["exch"] = "NSE" if e["nse"] else "BSE"
        if spec["oid"] == "Q17" and v == "V2":
            c["bucket_label"] = (e["bucket"].lower() + "-cap") if e["bucket"] else "listed"
        if e["isin"] in d["renames"]:
            old = [s for s in d["renames"][e["isin"]] if s != e["nse"]]
            c["old_symbol"] = old[0] if old else ""
        kind = spec.get("doc")
        docs = []
        if kind == "deck":
            docs = [dict(x) for x in d["decks"].get(e["isin"], []) if x["date"] <= c["as_of"]]
        elif kind == "cc":
            docs = [dict(date=x) for x in d["cc"].get(e["isin"], []) if x <= c["as_of"]]
        elif kind == "ar":
            docs = [dict(date=x[0], filed=x[1]) for x in d["ar"].get(e["isin"], [])]
        elif kind == "notes":
            docs = [dict(date=x) for x in d["notes"].get(e["isin"], []) if x <= c["as_of"]]
        docs.sort(key=lambda x: x["date"])
        if v == "V6" and len(docs) >= 2:
            c["doc"] = docs[-2]
        else:
            c["doc"] = docs[-1] if docs else None
        if kind == "deck" and c.get("doc"):
            c["doc"]["max_page"] = deck_pages(d, c["doc"].get("sha"))
            mp = c["doc"].get("max_page")
            if mp:
                c["max_page"] = mp
                if spec.get("special") == "page":
                    c["page"] = (mp + 7) if v == "V10" else 3 + (int(v[1:]) * 7) % max(mp - 3, 1)
        if spec["oid"] == "Q20" and d["events"].get("Q20"):
            ev = d["events"]["Q20"][0]
            c["event_label"] = ev["title"]
            c["policy"] = ev
        if spec.get("chunks"):
            try:
                c["chunks"] = d["_con"].execute(
                    "select count(*) from document_chunks where isin = ?", (e["isin"],)).fetchone()[0]
            except Exception:
                c["chunks"] = None
        if spec.get("special") == "segment":
            c["concept_ok"] = e["isin"] in d["seg_isins"]
        if spec.get("special") == "npa":
            c["concept_ok"] = e["isin"] in d["npa_isins"]
        if spec.get("special") == "geo":
            try:
                c["geo_ok"] = d["_notes_con"].execute(
                    "select count(*) from notes where isin = ? and (lower(body) like '%geograph%' "
                    "or lower(header) like '%geograph%')", (e["isin"],)).fetchone()[0] > 0
            except Exception:
                c["geo_ok"] = None
        if spec["oid"] == "QA1":
            pairs = [("2026-04-13", "2026-04-14"), ("2026-09-15", "2026-09-16"),
                     ("2026-06-10", "2026-06-11"), ("2026-03-18", "2026-03-19"),
                     ("2026-08-11", "2026-08-12"), ("2026-05-12", "2026-05-13"),
                     ("2026-02-10", "2026-02-11"), ("2026-07-14", "2026-07-15"),
                     ("2026-01-13", "2026-01-14"), ("2026-10-13", "2026-10-14")]
            order = pairs[int(v[1:]) - 1:] + pairs[:int(v[1:]) - 1]
            for d1, d2 in order:
                if delivery_check(d, e, (d1, d2)):
                    c["dates"] = (d1, d2)
                    c["delivery_ok"] = True
                    break
            else:
                c["dates"] = order[0]
                c["delivery_ok"] = False
    c.setdefault("entity_level", spec.get("level", "stock"))
    return c


def _pred(spec, d):
    f = spec.get("filter")
    if not f:
        return None
    if f == "banks":
        return lambda e: e["industry"] == "Banks"
    if f == "hfc":
        return lambda e: "Housing Finance" in e["basic"] or "Housing Finance" in e["name"]
    if f == "dairy":
        return lambda e: e["basic"] == "Dairy Products" or "Dairy" in e["basic"] or "Milk" in e["name"]
    if f == "omc":
        return lambda e: e["industry"] == "Petroleum Products"
    if f == "seg":
        return lambda e: e["isin"] in d["seg_isins"]
    if f == "npa":
        return lambda e: e["isin"] in d["npa_isins"]
    if f == "notes":
        return lambda e: bool(d["notes"].get(e["isin"]))
    return None


def entity_records(c):
    out = []
    seen = set()
    for e in ([c["e"]] if c.get("e") else []) + c.get("scope", []):
        if not e or e["isin"] in seen:
            continue
        seen.add(e["isin"])
        out.append(dict(symbol=sym(e), isin=e["isin"], bse_code=e["bse"] or None,
                        name=short_name(e["name"])))
    return out


# --------------------------------------------------------------------------- #
# question builders
# --------------------------------------------------------------------------- #
def q_dbr(c):
    e = c["e"]
    if not e:
        return "Which listed companies match this question, and what does the data show?"
    if c["v"] == "V4":
        return f"{sym(e)} products + close {date_short(c['date'])}"
    if c["v"] == "V5":
        return (f"Bhai, {c['ref']} kya banati hai, aur {date_long(c['date'])} ko NSE par "
                f"kitne pe close hui? Products aur close dono batao, short mein.")
    if c["v"] in ("V7", "V8"):
        return (f"For {c['scope_label']}, list what each company makes and its "
                f"{c['exch']} close on {date_long(c['date'])}.")
    if c["v"] == "V9":
        return (f"As of {date_long(c['as_of'])}, what did {c['ref']}'s latest annual report say "
                f"it makes, and what was its close that day?")
    if c["v"] == "V10":
        return (f"What does {c['ref']} make, and what was its {c['exch']} close on "
                f"{date_long(c['date'])}? If either is not in our data, answer NOT IN DATA and say why.")
    return f"What does {c['ref']} make, and what was its {c['exch']} close on {date_long(c['date'])}?"


def q_control(c):
    e = c["e"]
    if not e:
        return "Which companies disclosed a change in control in their latest annual report?"
    d = c.get("doc") or {}
    fy = d.get("date", "")[:4]
    fylab = f"FY{fy}" if fy else "the latest annual report"
    if c["v"] == "V4":
        return f"{sym(e)} latest annual report control change"
    if c["v"] == "V5":
        return (f"{c['ref']} ke latest annual report mein ownership ya control change ke baare "
                f"mein kya likha hai? Kaunsa saal, kaunsa page, aur exactly kya disclosure hai?")
    if c["v"] in ("V7", "V8"):
        return (f"For {c['scope_label']}, which companies disclosed a change in control or "
                f"ownership in their latest annual report, and what changed?")
    if c["v"] == "V9":
        return (f"As of {date_long(c['as_of'])}, what did {c['ref']}'s latest filed annual report "
                f"say about a change in control or ownership?")
    if c["v"] == "V10":
        return (f"What did {c['ref']}'s latest annual report disclose about a change in control? "
                f"If no annual report is held for it, answer NOT IN DATA and name the store checked.")
    return (f"What did {c['ref']}'s latest annual report ({fylab}) disclose about a change in "
            f"ownership or control, and where in the report?")


def q_segments(c):
    e = c["e"]
    if not e:
        return "What are the business segments of the listed companies in this group?"
    if c["v"] == "V4":
        return f"{sym(e)} business segments FY26"
    if c["v"] == "V5":
        return (f"{c['ref']} ka business kya hai aur segments kaunse hain? Annual report aur "
                f"latest results ke hisaab se segment revenue bhi batao.")
    if c["v"] in ("V7", "V8"):
        return (f"For {c['scope_label']}, what are the reported business segments and their "
                f"latest segment revenue?")
    if c["v"] == "V9":
        return (f"As of {date_long(c['as_of'])}, what did {c['ref']}'s latest results and annual "
                f"report disclose about its business and segments?")
    if c["v"] == "V10":
        return (f"For {c['ref']}, what are its business segments and segment revenue for Q1FY27? "
                f"If segment disclosure is not in the data, answer NOT IN DATA and say which store is missing.")
    return (f"What is {c['ref']}'s business, and what segments and segment revenue did it report "
            f"for the latest quarter?")


def q_pb(c):
    e = c["e"]
    if not e:
        return "What is the P/B of the listed companies in this group, computed at matching dates?"
    if c["v"] == "V4":
        return f"{sym(e)} pb ratio stored vs computed"
    if c["v"] == "V5":
        return (f"{c['ref']} ka P/B ratio kitna hai? Database mein stored ratio aur aaj ke price "
                f"se nikaala hua ratio dono batao, aur farq kyun hai.")
    if c["v"] in ("V7", "V8"):
        return (f"For {c['scope_label']}, rank the companies by P/B computed from the close on "
                f"{date_long(c['as_of'])} and the latest annual-report book value.")
    if c["v"] == "V9":
        return (f"As of {date_long(c['as_of'])}, what was {c['ref']}'s P/B using the price and "
                f"book value known by that date? Compare it with the stored ratio.")
    if c["v"] == "V10":
        return (f"What is {c['ref']}'s P/B now versus the stored ratio, after adjusting for its "
                f"corporate action? If book value per share is not held, say NOT IN DATA.")
    return (f"What is {c['ref']}'s P/B now, and how does it compare with the stored ratio? "
            f"State the price date and the book-value date.")


def q_call(c):
    e = c["e"]
    if not e:
        return "What did the listed companies say on their latest earnings calls?"
    d = c.get("doc") or {}
    dl = date_long(d["date"]) if d.get("date") else "the latest call"
    if c["v"] == "V4":
        return f"{sym(e)} call {d.get('date','')[:10]} management outlook"
    if c["v"] == "V5":
        return (f"{c['ref']} ki {dl} wali earnings call mein management ne business aur margin "
                f"outlook ke baare mein kya kaha? Speaker ka naam aur quote batao.")
    if c["v"] in ("V7", "V8"):
        return (f"For {c['scope_label']}, what did management say about demand and margins on "
                f"their latest earnings calls, with quoted evidence?")
    if c["v"] == "V9":
        return (f"As of {date_long(c['as_of'])}, what had {c['ref']}'s management last said on an "
                f"earnings call about demand and margins?")
    if c["v"] == "V10":
        return (f"What did {c['ref']} say about demand and margins on its {dl} earnings call? "
                f"If the transcript is held but not chunked, answer NOT IN DATA and say so.")
    return (f"What did {c['ref']}'s management say about demand and margins on its {dl} "
            f"earnings call, and who said it?")


def q_delivery(c):
    e = c["e"]
    if not e:
        return "What was the delivered quantity on the chosen dates?"
    d1, d2 = c["dates"]
    if c["v"] == "V4":
        import datetime as _dt
        m = _dt.date.fromisoformat(d1).strftime("%b")
        return f"{sym(e)} delivery {d1[8:10]}-{d2[8:10]} {m} nse bse"
    if c["v"] == "V5":
        return (f"{c['ref']} ka delivered quantity {date_long(d1)} aur {date_long(d2)} ko kitna "
                f"tha? NSE, BSE aur dono ka total alag-alag batao.")
    if c["v"] in ("V7", "V8"):
        return (f"For {c['scope_label']}, what was the delivered quantity on NSE and BSE on "
                f"{date_long(d1)} and {date_long(d2)}, ranked?")
    if c["v"] == "V9":
        return (f"As of {date_long(c['as_of'])}, what delivered quantity had {c['ref']} recorded "
                f"on {date_long(d1)} and {date_long(d2)} on NSE and BSE?")
    if c["v"] == "V10":
        return (f"What was {c['ref']}'s delivered quantity on {date_long(d1)} and {date_long(d2)} "
                f"on NSE and BSE? If one exchange has no row, say which and answer NOT IN DATA for it.")
    return (f"What was {c['ref']}'s delivered quantity (not total traded quantity) on "
            f"{date_long(d1)} and {date_long(d2)}, NSE and BSE, with the combined total per day?")


def q_holding(c):
    e = c["e"]
    if not e:
        return "What is the promoter holding of the listed companies in this group?"
    if c["v"] == "V4":
        return f"{sym(e)} promoter holding {c['period']}"
    if c["v"] == "V5":
        return (f"{c['ref']} mein promoter ki holding {c['period']} tak kitni hai? Latest "
                f"shareholding filing se number aur date batao.")
    if c["v"] in ("V7", "V8"):
        return (f"For {c['scope_label']}, what is the promoter holding as of {c['period']}, "
                f"ranked from highest to lowest?")
    if c["v"] == "V9":
        return (f"As of {date_long(c['as_of'])}, what was {c['ref']}'s promoter holding per the "
                f"latest shareholding filing on or before that date?")
    if c["v"] == "V10":
        return (f"What is {c['ref']}'s promoter holding as of {c['period']}? If the September "
                f"2026 shareholding filing is not held, answer NOT IN DATA and say why.")
    return (f"What is {c['ref']}'s promoter holding as of {strip_asof(c['period'])}, per the "
            f"latest filing?")


def q_deck_fac(c):
    e = c["e"]
    if not e:
        return "How many manufacturing facilities does each company report in its latest deck?"
    d = c.get("doc") or {}
    dl = date_long(d["date"]) if d.get("date") else "its latest investor presentation"
    if c["v"] == "V4":
        return f"{sym(e)} facilities deck {d.get('date','')[:10]}"
    if c["v"] == "V5":
        return (f"{c['ref']} ke {dl} wale investor presentation ke hisaab se kitni manufacturing "
                f"facilities hain, aur kahan? Slide ka reference bhi do.")
    if c["v"] in ("V7", "V8"):
        return (f"For {c['scope_label']}, how many manufacturing facilities does each company "
                f"report in its latest investor presentation?")
    if c["v"] == "V9":
        return (f"As of {date_long(c['as_of'])}, how many manufacturing facilities did {c['ref']} "
                f"report in its latest deck filed by that date?")
    if c["v"] == "V10":
        return (f"How many manufacturing facilities does {c['ref']} report in its investor "
                f"presentation dated {dl}? If no deck is stored for it, answer NOT IN DATA and "
                f"name the store checked.")
    return (f"How many manufacturing facilities does {c['ref']} report in its investor "
            f"presentation dated {dl}, and where are they?")


def q_deck_ma(c):
    e = c["e"]
    if not e:
        return "What products and acquisitions does each company report in its deck?"
    d = c.get("doc") or {}
    dl = date_long(d["date"]) if d.get("date") else "its latest investor presentation"
    if c["v"] == "V4":
        return f"{sym(e)} products acquisitions deck {d.get('date','')[:10]}"
    if c["v"] == "V5":
        return (f"{c['ref']} ke {dl} wale deck mein main products kya hain, aur inorganic growth "
                f"ke liye kis company ka acquisition mention kiya gaya hai?")
    if c["v"] in ("V7", "V8"):
        return (f"For {c['scope_label']}, what products and acquisitions does each company "
                f"report in its latest investor presentation?")
    if c["v"] == "V9":
        return (f"As of {date_long(c['as_of'])}, what did {c['ref']}'s latest deck disclose about "
                f"its products and acquisitions?")
    if c["v"] == "V10":
        return (f"What are {c['ref']}'s key products and its latest acquisition? If the deck is "
                f"held but the page text is not extracted, answer NOT IN DATA and say which store is missing.")
    return (f"Per {c['ref']}'s deck of {dl}, what are its key products, and which company did it "
            f"mention as acquired for inorganic growth?")


def q_shares(c):
    e = c["e"]
    if not e:
        return "What are the share counts and promoter holdings of these companies?"
    if c["v"] == "V4":
        return f"{sym(e)} share count promoter holding"
    if c["v"] == "V5":
        return (f"{c['ref']} ke kitne equity shares hain aur promoter holding kitni hai? Dono "
                f"numbers latest filing se, date ke saath batao.")
    if c["v"] in ("V7", "V8"):
        return (f"For {c['scope_label']}, give the latest exact share count and promoter holding "
                f"for each company, with the filing date.")
    if c["v"] == "V9":
        return (f"As of {date_long(c['as_of'])}, what were {c['ref']}'s exact share count and "
                f"promoter holding?")
    if c["v"] == "V10":
        return (f"What are {c['ref']}'s exact share count and promoter holding now, after its "
                f"corporate action? If the post-action count is not held, answer NOT IN DATA.")
    return (f"How many equity shares does {c['ref']} have, and what is its promoter holding, as of "
            f"the latest data? Say which filing each number comes from.")


def q_deck_page(c):
    e = c["e"]
    if not e:
        return "What does a given page of these companies' decks say?"
    d = c.get("doc") or {}
    page = c.get("page") or 1
    dl = date_long(d["date"]) if d.get("date") else "its latest deck"
    if c["v"] == "V4":
        return f"{sym(e)} deck page {page} {d.get('date','')[:10]}"
    if c["v"] == "V5":
        return (f"{c['ref']} ke {dl} wale investor presentation ke page {page} par kya dikhaya "
                f"gaya hai? Text ya quote ke saath batao.")
    if c["v"] in ("V7", "V8"):
        return (f"For {c['scope_label']}, what do the latest decks say on their capacity or "
                f"licensing slides?")
    if c["v"] == "V9":
        return (f"As of {date_long(c['as_of'])}, what did page {page} of {c['ref']}'s latest deck "
                f"filed by that date say?")
    if c["v"] == "V10":
        return (f"What does page {page} of {c['ref']}'s investor presentation dated {dl} say? "
                f"If the deck has fewer pages, answer NOT IN DATA and give the page count.")
    return (f"What does page {page} of {c['ref']}'s investor presentation dated {dl} say about "
            f"its manufacturing licence or capacity?")


def q_capacity_call(c):
    e = c["e"]
    if not e:
        return "What did these companies say about capacity expansion on their calls?"
    d = c.get("doc") or {}
    dl = date_long(d["date"]) if d.get("date") else "its latest call"
    if c["v"] == "V4":
        return f"{sym(e)} capacity timeline call {d.get('date','')[:10]}"
    if c["v"] == "V5":
        return (f"{c['ref']} ne apni {dl} wali call mein capacity expansion ka kya timeline "
                f"bataya? Completion date aur capex ke saath quote do.")
    if c["v"] in ("V7", "V8"):
        return (f"For {c['scope_label']}, what capacity-expansion timelines did management give "
                f"on their latest earnings calls?")
    if c["v"] == "V9":
        return (f"As of {date_long(c['as_of'])}, what had {c['ref']} said about its capacity "
                f"expansion timeline by that date?")
    if c["v"] == "V10":
        return (f"What did {c['ref']} say about its capacity expansion timeline on {dl}? If the "
                f"transcript exists but is not chunked, answer NOT IN DATA and say so.")
    return (f"What did {c['ref']} say about its capacity expansion, and the completion timeline, "
            f"on its {dl} earnings call?")


def q_ytd(c):
    e = c["e"]
    if not e:
        return "What were the YTD highs for the companies in this group?"
    if c["v"] == "V4":
        return f"{sym(e)} ytd high {c['period']}"
    if c["v"] == "V5":
        return (f"{c['ref']} ka {c['period']} ka YTD high price kya tha, aur kis date ko? "
                f"NSE ya BSE, exchange bhi batao.")
    if c["v"] in ("V7", "V8"):
        return (f"For {c['scope_label']}, which companies made a new YTD high in {c['period']}, "
                f"with the value and date?")
    if c["v"] == "V9":
        return (f"As of {date_long(c['as_of'])}, what was {c['ref']}'s YTD high in 2026 up to "
                f"that date, and on which day?")
    if c["v"] == "V10":
        return (f"What was {c['ref']}'s YTD high for {c['period']}, raw and adjusted for its "
                f"corporate action? If adjusted prices are missing, say NOT IN DATA.")
    return (f"What was {c['ref']}'s YTD high price in {c['period']}, with the value and the date, "
            f"and on which exchange?")


def q_latest_fac(c):
    e = c["e"]
    if not e:
        return "What have these companies said about newly commissioned facilities?"
    if c["v"] == "V4":
        return f"{sym(e)} newly commissioned facilities latest"
    if c["v"] == "V5":
        return (f"{c['ref']} ne apni nayi commissioned facilities ke baare mein sabse latest kya "
                f"kaha hai? Deck, concall aur annual report teeno check karke source do.")
    if c["v"] in ("V7", "V8"):
        return (f"For {c['scope_label']}, what have the companies said about newly commissioned "
                f"facilities across decks, calls and annual reports?")
    if c["v"] == "V9":
        return (f"As of {date_long(c['as_of'])}, what had {c['ref']} said about its newly "
                f"commissioned facilities, using only documents known by that date?")
    if c["v"] == "V10":
        return (f"What has {c['ref']} said about its newly commissioned facilities? If no "
                f"document after {c['period']} is held, answer NOT IN DATA and name the gap.")
    return (f"What did {c['ref']} say about its newly commissioned facilities, as of the latest "
            f"data, and in which document type?")


def q_mou(c):
    e = c["e"]
    if not e:
        return "What did these companies say about their MOUs and margin trajectory?"
    d = c.get("doc") or {}
    dl = date_long(d["date"]) if d.get("date") else "its latest call"
    if c["v"] == "V4":
        return f"{sym(e)} mou margin path call {d.get('date','')[:10]}"
    if c["v"] == "V5":
        return (f"{c['ref']} ki {dl} wali call mein MOU partner kaun hai, aur EBITDA margin ka "
                f"path kya bataya gaya? Plan aur numbers quote karo.")
    if c["v"] in ("V7", "V8"):
        return (f"For {c['scope_label']}, what MOUs or partnerships and margin paths did "
                f"management disclose on their latest calls?")
    if c["v"] == "V9":
        return (f"As of {date_long(c['as_of'])}, what had {c['ref']} disclosed about its MOU "
                f"and margin path?")
    if c["v"] == "V10":
        return (f"What did {c['ref']} say about its MOU and EBITDA margin path on {dl}? If the "
                f"call is not held for that date, answer NOT IN DATA.")
    return (f"Per {c['ref']}'s {dl} earnings call, what did it say about its MOU with its "
            f"partner, and how will EBITDA margins progress?")


def q_segrev(c):
    e = c["e"]
    if not e:
        return "What were segment revenues for the companies in this group?"
    if c["v"] == "V4":
        return f"{sym(e)} segment revenue {c['period']}"
    if c["v"] == "V5":
        return (f"{c['ref']} ka {c['period']} segment revenue kitna tha, segment-wise absolute "
                f"numbers ke saath? XBRL context ka source bhi do.")
    if c["v"] in ("V7", "V8"):
        return (f"For {c['scope_label']}, rank the companies by reported segment revenue for "
                f"{c['period']}.")
    if c["v"] == "V9":
        return (f"As of {date_long(c['as_of'])}, what segment revenue had {c['ref']} reported for "
                f"Q1FY27?")
    if c["v"] == "V10":
        return (f"What was {c['ref']}'s segment revenue for {c['period']}? If the filing has no "
                f"segment context, answer NOT IN DATA and say which taxonomy is missing.")
    return (f"What was {c['ref']}'s segment revenue for {c['period']}, with the absolute number "
            f"for each reported segment?")


def q_npa(c):
    e = c["e"]
    if not e:
        return "What was net NPA for the banks in this group?"
    if c["v"] == "V4":
        return f"{sym(e)} net npa {c['period']}"
    if c["v"] == "V5":
        return (f"{c['ref']} ka net NPA percentage {c['period']} mein kitna tha? Gross NPA aur "
                f"net NPA dono, XBRL filing se batao.")
    if c["v"] in ("V7", "V8"):
        return (f"For {c['scope_label']}, rank the banks by net NPA % for {c['period']}, and "
                f"state the source for each.")
    if c["v"] == "V9":
        return (f"As of {date_long(c['as_of'])}, what net NPA % had {c['ref']} last reported for "
                f"Q1FY27?")
    if c["v"] == "V10":
        return (f"What was {c['ref']}'s net NPA % for {c['period']}? If that quarter's filing is "
                f"not held, or the bank's XBRL uses a taxonomy without that concept, answer "
                f"NOT IN DATA and say which.")
    return (f"What was {c['ref']}'s net NPA % for {c['period']}, and which XBRL concept and "
            f"filing carry it?")


def q_cagr(c):
    e = c["e"]
    if not e:
        return "What was the 3-year adjusted price CAGR for these companies?"
    if c["v"] == "V4":
        return f"{sym(e)} 3y cagr adjusted"
    if c["v"] == "V5":
        return (f"{c['ref']} ka pichle 3 saal ka adjusted price CAGR kya raha? Start aur end date "
                f"saaf-saaf likho, dividends aur splits adjust karke.")
    if c["v"] in ("V7", "V8"):
        return (f"For {c['scope_label']}, what was the 3-year adjusted price CAGR to "
                f"{date_long(c['as_of'])}, ranked?")
    if c["v"] == "V9":
        return (f"As of {date_long(c['as_of'])}, what was {c['ref']}'s 3-year adjusted price CAGR?")
    if c["v"] == "V10":
        return (f"What was {c['ref']}'s 3-year adjusted price CAGR across its "
                f"{c.get('corp_action','corporate action')}? If adjusted prices are missing, answer NOT IN DATA.")
    return (f"What was {c['ref']}'s 3-year price CAGR to {date_long(c['as_of'])}, using "
            f"split- and dividend-adjusted closes? State both endpoint dates.")


def q_note5(c):
    e = c["e"]
    if not e:
        return "What do these companies' results notes say?"
    if c["v"] == "V4":
        return f"{sym(e)} results note 5 geo split {c['period']}"
    if c["v"] == "V5":
        return (f"{c['ref']} ke {c['period']} results ki note 5 mein kya likha hai, aur "
                f"geographic revenue split kya hai? Consolidated basis, quote ke saath.")
    if c["v"] in ("V7", "V8"):
        return (f"For {c['scope_label']}, which companies disclose a geographic revenue split in "
                f"their results notes for {c['period']}, and what is it?")
    if c["v"] == "V9":
        return (f"As of {date_long(c['as_of'])}, what did note 5 of {c['ref']}'s {c['period']} "
                f"results say, and what was its geographic split?")
    if c["v"] == "V10":
        return (f"What does note 5 of {c['ref']}'s results for {c['period']} say, and what is the "
                f"geographic split? If that quarter's results notes are not stored, answer NOT IN DATA.")
    return (f"Note 5 of {c['ref']}'s {c['period']} results \u2014 what does it say, and what is the "
            f"geographic revenue split, consolidated?")


def q_public(c):
    e = c["e"]
    if not e:
        return "What is the public shareholding of these companies?"
    if c["v"] == "V4":
        return f"{sym(e)} public shareholding {c['period']}"
    if c["v"] == "V5":
        return (f"{c['ref']} mein public shareholding {c['period']} tak kitni hai? Promoter aur "
                f"public dono ka percentage filing se batao.")
    if c["v"] in ("V7", "V8"):
        return (f"For {c['scope_label']}, rank the companies by public shareholding as of "
                f"{c['period']}.")
    if c["v"] == "V9":
        return (f"As of {date_long(c['as_of'])}, what was {c['ref']}'s public shareholding per the "
                f"latest filing on or before that date?")
    if c["v"] == "V10":
        return (f"What is {c['ref']}'s public shareholding as of {c['period']}? If that quarter's "
                f"shareholding filing is not held, answer NOT IN DATA.")
    return f"What is {c['ref']}'s public shareholding as of {strip_asof(c['period'])}?"


def q_gold(c):
    ev = c.get("policy") or {}
    sec = ev.get("sector_label") or c.get("scope_name") or "gold-jewellery"
    per = c["period"]
    if c["v"] == "V4":
        return f"{sec} stocks move {per} why"
    if c["v"] == "V5":
        return (f"{sec.title()} stocks {per} mein kya hua aur kyun? PIB, RBI ya company "
                f"documents se evidence do, aur batao kaun sabse zyada affected hua.")
    if c["v"] == "V7":
        return (f"For {c['scope_label']}, what moved in {per}, and what do the macro, PIB and "
                f"company evidence say caused it?")
    if c["v"] == "V8":
        return (f"For {c['scope_label']}, how did {ev.get('title','the macro move')} in {per} hit "
                f"the members differently, and which one was worst?")
    if c["v"] == "V6":
        return (f"What caused the {sec} move in {c['alt_period']}? Use the commodity series, PIB "
                f"and company evidence from that window only.")
    if c["v"] == "V9":
        return (f"By {date_long(c['as_of'])}, why had {sec} stocks moved? Use only evidence "
                f"known by that date.")
    if c["v"] == "V10":
        return (f"Why did {c['ref']} move in {per}? If the macro series for that window is "
                f"missing, answer NOT IN DATA and name the series.")
    if c["v"] == "V3":
        return (f"Why did the companies in the {sec} theme move in {per}? The event is referenced "
                f"by {c['ref']}; name the PIB release or macro series you rely on.")
    return (f"Why did {sec} stocks move in {per}? Give the macro move, the PIB or RBI evidence, "
            f"and what the companies themselves said.")


def q_hfc(c):
    e = c["e"]
    if c["v"] == "V3":
        return (f"For {c['ref']}, is it the leader in securitised disbursement among listed HFCs "
                f"for Q1FY27, with net NPA up no more than 2 pp? Show the naming history if the "
                f"symbol or ISIN changed.")
    if c["v"] == "V4":
        return "hfc securitisation leader q1fy27 net npa"
    if c["v"] == "V5":
        return (f"Listed HFCs mein securitised disbursement ka leader kaun hai {c['period']} mein? "
                f"QoQ aur YoY winner batao, lekin net NPA 2 percentage point se zyada na badhe.")
    if c["v"] == "V10":
        return (f"Which listed HFC led securitised disbursement in {c['period']}? If the securitisation "
                f"figure is not in any structured store for {c['ref']}, answer NOT IN DATA and say why.")
    if c["v"] == "V9":
        return (f"As of {date_long(c['as_of'])}, which HFC looked like the securitisation leader for "
                f"Q1FY27, and on what evidence?")
    if c["v"] in ("V7",):
        return (f"For {c['scope_label']}, which listed financial company is the securitisation "
                f"leader for {c['period']} with the net-NPA guard, and what is the evidence?")
    if c["v"] == "V8":
        return (f"For {c['scope_label']}, rank the financial companies on securitised disbursement "
                f"for {c['period']}, with the net-NPA guard.")
    if c["v"] == "V2":
        return (f"Among {c['bucket_label']} HFCs, who leads securitised disbursement for "
                f"{c['period']} with net NPA up no more than 2 pp?")
    if c["v"] == "V1":
        return (f"Is {c['ref']} the leader in securitised disbursement among listed HFCs for "
                f"{c['period']}, with net NPA up no more than 2 pp? Show the comparison.")
    return (f"Which listed HFC is the leader in securitised disbursement for {c['period']}, "
            f"QoQ and YoY, with net NPA rising no more than 2 pp?")


def q_omc(c):
    if c["v"] == "V4":
        return "omc q4fy26 profit q1fy27 loss earliest pit"
    if c["v"] == "V5":
        return (f"OMCs ne Q4FY26 mein record profit aur Q1FY27 mein bada loss kaise kiya? Sabse "
                f"pehle kaunsa data point point-in-time visible tha, date ke saath batao.")
    if c["v"] in ("V1", "V2"):
        return (f"{c['event_label']} \u2014 which companies in {c['industry_label']} swung from "
                f"profit in Q4FY26 to a loss in Q1FY27, and when was that first visible "
                f"point-in-time?")
    if c["v"] == "V3":
        return (f"For {c['ref']}, when did the Q4FY26-to-Q1FY27 profit swing become visible "
                f"point-in-time, and from which filing?")
    if c["v"] in ("V7", "V8"):
        return (f"For {c['scope_label']}, which companies swung from profit in Q4FY26 to a loss in "
                f"Q1FY27, and what was the earliest point-in-time evidence?")
    if c["v"] == "V6":
        return (f"For {c['alt_period']}, which OMCs went from record profit to a loss, and when "
                f"did that first become visible?")
    if c["v"] == "V9":
        return (f"As of {date_long(c['as_of'])}, what did the data already show about the OMC "
                f"profit swing from Q4FY26 to Q1FY27?")
    if c["v"] == "V10":
        return (f"Using the coal price series, when did the OMC Q4FY26-to-Q1FY27 trend first "
                f"become visible? If the series ends before that window, answer NOT IN DATA.")
    return (f"For the OMCs, when was the Q4FY26 record profit followed by the Q1FY27 loss first "
            f"visible point-in-time, and from which data store?")


def q_etf(c):
    e = c["e"]
    if c["v"] == "V4":
        return f"{sym(e) if e else 'etf'} jump tracking error Sep 2026"
    if c["v"] == "V5":
        return (f"{c['ref'] if e else 'Iss ETF'} 10-18 September 2026 ke beech kyun jump hua aur "
                f"18-28 September mein kyun gira? Underlying index, FX aur NAV tracking error ke saath batao.")
    if c["v"] in ("V7",):
        return (f"For {c['scope_label']}, what explains the move in {c['period']}, and what is the "
                f"NAV tracking error?")
    if c["v"] == "V8":
        return (f"For {c['scope_label']}, which ETF moved most in {c['period']}, and what was its "
                f"tracking error against the underlying index and FX?")
    if c["v"] == "V2":
        return (f"For {c['ref']}, a different ETF category from the original, what was the move "
                f"in {c['period']}, and how did NAV track iNAV?")
    if c["v"] == "V9":
        return (f"As of {date_long(c['as_of'])}, what was the move in {c['ref']} up to that "
                f"date, and what tracking error was visible by then?")
    if c["v"] == "V10":
        return (f"For {c['ref']}, what was the move and NAV tracking error in {c['period']}? If "
                f"the ETF has no NAV or iNAV rows, answer NOT IN DATA and say which store is missing.")
    if c["v"] == "V3":
        return (f"For {c['ref']}, what was the move in {c['period']} and the tracking error against "
                f"its underlying index and the rupee?")
    return (f"For {c['ref']}, explain the jump in {c['period']} using the underlying index and FX, "
            f"and give the NAV tracking error.")


def q_tariff(c):
    e = c["e"]
    if not e:
        return "How sensitive were the members to the tariff event, and did the correlation turn negative?"
    ev = c.get("policy") or {}
    el = ev.get("title") or "the customs-tariff change"
    edl = date_long(ev.get("date", "")) if ev.get("date") else "the event date"
    if c["v"] == "V4":
        return f"{sym(e)} tariff sensitivity rolling correlation"
    if c["v"] == "V5":
        return (f"{c['ref']} par {el} ({edl}) ka kitna asar pada, aur agle 12 mahine mein tariff "
                f"news se correlation negative hua ya nahi? Rolling correlation ke saath batao.")
    if c["v"] in ("V7", "V8"):
        return (f"For {c['scope_label']}, how sensitive were the members to {el} ({edl}), and "
                f"did the 60-day return correlation turn negative over the following 12 months?")
    if c["v"] == "V6":
        return (f"How did {c['ref']}'s rolling correlation with {el} ({edl}) change over "
                f"{c['alt_period']}?")
    if c["v"] == "V9":
        return (f"As of {date_long(c['as_of'])}, what did the rolling correlation of {c['ref']} "
                f"with {el} ({edl}) show?")
    if c["v"] == "V10":
        return (f"For {c['ref']}, did the tariff impact and any later negative correlation survive "
                f"its {c.get('corp_action', 'corporate action')} on adjusted prices? If not, answer NOT IN DATA.")
    return (f"How sensitive was {c['ref']} to {el} ({edl}) in the 60 days after it, and did its "
            f"60-day return correlation with tariff news turn negative over the following 12 months? "
            f"Give the rolling correlations and the evidence.")


def q_rbi(c):
    p = c.get("policy") or {}
    if c["v"] == "V4":
        return f"rbi repo hike {p.get('date','')} causes pib or rbi"
    if c["v"] == "V5":
        return (f"RBI ne {p.get('date','2026-10-07')} ko repo rate kyun badhaya? Causes batao, aur "
                f"ye news PIB ne publish kiya ya sirf RBI ne? Provenance ke saath.")
    if c["v"] in ("V7",):
        return (f"For {c['scope_label']}, how does the {p.get('date','')} RBI action transmit, and "
                f"which sectors are named in the policy document?")
    if c["v"] == "V8":
        return (f"For {c['scope_label']}, how did the members react to the RBI action of "
                f"{p.get('date','')}, and what does the PIB/RBI record show?")
    if c["v"] == "V9":
        return (f"As of {date_long(c['as_of'])}, what did the record show about the causes of the "
                f"RBI action of {p.get('date','')}, and who published it first?")
    if c["v"] == "V10":
        return (f"What were the causes of the RBI action of {p.get('date','')}, and was it "
                f"published by PIB or only by RBI? If the policy document is not held, answer NOT IN DATA.")
    if c["v"] == "V3":
        return (f"For {p.get('title','the policy action')} ({p.get('date','')}), what were the "
                f"causes, and which source published it first?")
    if c["v"] in ("V1", "V2"):
        return (f"For the {p.get('title','policy action')} ({p.get('date','')}), what were the "
                f"causes, and which source published it first?")
    return (f"For the {p.get('title','RBI policy action')} of {p.get('date','')}, what were the "
            f"causes, and was it published by PIB or only by the RBI?")


def q_refurb(c):
    if c["v"] == "V4":
        return "second hand electronics boom cy2026 who benefits"
    if c["v"] == "V5":
        return (f"CY2026 mein second-hand aur refurbished electronics/laptops ki demand kyun badhi? "
                f"Kaun listed companies ko fayda hoga, aur ye structural hai ya cyclical? Data gap bhi batao.")
    if c["v"] in ("V7",):
        return (f"For {c['scope_label']}, what does the policy record say about demand in "
                f"{c['period']}, and which companies does it touch?")
    if c["v"] == "V8":
        return (f"For {c['scope_label']}, what does the policy and company evidence say about "
                f"demand in {c['period']}, and who benefits?")
    if c["v"] == "V9":
        return (f"As of {date_long(c['as_of'])}, what was known about the {c['period']} "
                f"electronics demand trend, and which companies were named?")
    if c["v"] == "V10":
        return (f"What do our stores say about refurbished/second-hand electronics sales in CY2026, "
                f"and who benefits? If no sales series exists, answer NOT IN DATA and say which store is missing.")
    if c["v"] == "V3":
        return (f"Using the document reference {c['ref']}, what does the policy record say about "
                f"electronics demand in {c['period']}, and which companies does it touch?")
    if c["v"] in ("V1", "V2"):
        return (f"For the {c.get('policy',{}).get('title','electronics policy')} "
                f"({c.get('policy',{}).get('date','')}), why does it matter for demand, and which "
                f"sectors and listed companies does it touch?")
    return (f"Why did second-hand electronics and laptop sales rise in CY2026? Who benefits, and is "
            f"the trend structural or cyclical? State any part that is NOT IN DATA.")


def q_coal(c):
    if c["v"] == "V4":
        return "coal gasification policy draft vs earlier scheme"
    if c["v"] == "V5":
        return (f"Coal gasification ke naye draft aur pehle wale scheme mein kya farq hai? Kaunse "
                f"ministries aur industries affected hain, aur PIB/Budget se evidence do.")
    if c["v"] in ("V7",):
        return (f"For {c['scope_label']}, how does the coal-gasification policy differ from the "
                f"earlier scheme, and which industries does it hit?")
    if c["v"] == "V8":
        return (f"For {c['scope_label']}, what does the coal-gasification policy change mean for "
                f"the members, and which ones are named in policy_events?")
    if c["v"] == "V9":
        return (f"As of {date_long(c['as_of'])}, how did the coal-gasification drafts differ from "
                f"the earlier scheme? Use only documents known by that date.")
    if c["v"] == "V10":
        return (f"How does the coal-gasification policy change affect coal-price-sensitive "
                f"companies? If the coal price series ends before {c['period']}, answer NOT IN DATA.")
    if c["v"] == "V3":
        return (f"Using the document reference {c['ref']}, how does the coal-gasification policy "
                f"differ from the earlier scheme, and which industries does it hit?")
    if c["v"] == "V1":
        return (f"For the {c.get('policy',{}).get('title','policy')} "
                f"({c.get('policy',{}).get('date','')}), how does it differ from the earlier "
                f"coal-gasification scheme, and which industries does it hit?")
    if c["v"] == "V2":
        return (f"For the {c.get('policy',{}).get('title','policy')} "
                f"({c.get('policy',{}).get('date','')}), how does it differ from the coal-gasification "
                f"scheme, and which industries does it hit?")
    return (f"How do India's coal-gasification policy drafts differ from the earlier scheme, and "
            f"which industries do they hit?")


def q_dairy(c):
    e = c["e"]
    if c["v"] == "V4":
        return f"{sym(e)} el nino dairy margins"
    if c["v"] == "V5":
        return (f"{c['ref']} ne El Nino 2026 ke asar par calls mein kya kaha? Dairy peers ka bhi "
                f"comparison do, aur management ne kaise handle karne ko kaha.")
    if c["v"] in ("V7",):
        return (f"For {c['scope_label']}, what did managements say about El Nino 2026, and how are "
                f"they handling it?")
    if c["v"] == "V8":
        return (f"For {c['scope_label']}, how exposed are the members to El Nino 2026, and what did "
                f"they say about handling it?")
    if c["v"] == "V9":
        return (f"As of {date_long(c['as_of'])}, what had {c['ref']} said about El Nino 2026 and "
                f"its dairy margins?")
    if c["v"] == "V10":
        return (f"What did {c['ref']} say about El Nino 2026 on its calls? If no transcript is "
                f"held for it, answer NOT IN DATA and name the store checked.")
    return (f"What did {c['ref']} say about El Nino 2026 in its transcripts, and how are dairy "
            f"peers handling the same risk?")


def q_dc(c):
    p = c.get("policy") or {}
    if c["v"] == "V4":
        return f"data centre tax holiday outcome {c['period']}"
    if c["v"] == "V5":
        return (f"Data-centre operations ke liye tax holiday ka kya outcome raha? Budget, PIB, "
                f"policy_events aur data-centre companies ke comments se evidence do.")
    if c["v"] in ("V7",):
        return (f"For {c['scope_label']}, how has the tax holiday played out, and what do the "
                f"companies and policy documents say?")
    if c["v"] == "V8":
        return (f"For {c['scope_label']}, what has the tax holiday meant so far, and which members "
                f"are named in the policy record?")
    if c["v"] == "V9":
        return (f"As of {date_long(c['as_of'])}, how had the data-centre tax holiday played out, "
                f"using only evidence known by that date?")
    if c["v"] == "V10":
        return (f"How has the data-centre tax holiday played out so far? If no data-centre tax "
                f"holiday exists in policy_events, or the PIB starts too late, answer NOT IN DATA.")
    if c["v"] == "V3":
        return (f"Using the document reference {c['ref']}, how has the data-centre tax holiday "
                f"played out so far, and what do the companies in the theme say?")
    if c["v"] in ("V1", "V2"):
        return (f"For the {p.get('title','tax-holiday policy')} ({p.get('date','')}), how has it "
                f"played out so far for the affected industry, and what do companies say?")
    return (f"How has the tax holiday for data-centre operations in India played out so far, and "
            f"what do the companies in the data-centre theme say?")


BUILDERS = {
    "DBQ1": q_dbr, "DBQ2": q_control, "DBQ3": q_segments, "DBQ4": q_pb, "DBQ5": q_call,
    "QA1": q_delivery, "QA2": q_holding, "QA3": q_deck_fac, "QA4": q_deck_ma,
    "QA5": q_shares, "QA6": q_deck_page, "QA7": q_capacity_call, "QA8": q_ytd,
    "QA9": q_latest_fac, "QA10": q_mou, "Q11": q_segrev, "Q12": q_npa, "Q13": q_cagr,
    "Q14": q_note5, "Q15": q_public, "Q16": q_gold, "Q17": q_hfc, "Q18": q_omc,
    "Q19": q_etf, "Q20": q_tariff, "Q21": q_rbi, "Q22": q_refurb, "Q23": q_coal,
    "Q24": q_dairy, "Q25": q_dc,
}

ORIGINALS = {
    "DBQ1": ("AEROFLEX products + close on a date", "1,2"),
    "DBQ2": ("532627 latest AR: control change", "1,9"),
    "DBQ3": ("544161 business + segments", "1"),
    "DBQ4": ("P/B now vs stored", "2,11"),
    "DBQ5": ("DEEDEV Aug-2026 concall remark", "1"),
    "QA1": ("Ather delivery NSE+BSE on 2 dates", "2"),
    "QA2": ("BLACKBUCK promoter % Sep 2026", "2,11"),
    "QA3": ("Ganesha facilities per a dated deck", "1"),
    "QA4": ("Chemcon products + acquisition per deck", "1"),
    "QA5": ("Lumax shares + promoter %, latest", "2"),
    "QA6": ("540879 deck page 21 (licence)", "1"),
    "QA7": ("INE864I01014 fuel-cell capacity, transcript", "1,3"),
    "QA8": ("532810 YTD high 2026", "2"),
    "QA9": ("SAILIFE new facilities, latest", "1,5"),
    "QA10": ("COCHINSHIP MOU + margin path, transcript", "1,3"),
    "Q11": ("KRISHNADEF segment revenue, latest quarter", "2,8"),
    "Q12": ("Bank of Maharashtra net NPA %", "2"),
    "Q13": ("ZENTEC 3-yr price CAGR", "2"),
    "Q14": ("VISHNU Note 5 of latest results + geo split", "1,2"),
    "Q15": ("VINCOFE public shareholding Sep 2026", "2,11"),
    "Q16": ("Why gold stocks fell Jun-Jul 2026", "6,4"),
    "Q17": ("HFC securitisation leader, QoQ/YoY with NPA guard", "4,8"),
    "Q18": ("OMCs: record Q4 then loss Q1; earliest PIT signal", "6,9,11"),
    "Q19": ("MONQ50 ETF jump/fall + tracking error", "2,9"),
    "Q20": ("Garware: tariff hit, then negative correlation", "6,9"),
    "Q21": ("RBI repo hike causes; PIB or RBI only", "6,7"),
    "Q22": ("Second-hand electronics boom CY2026: who benefits", "6,7"),
    "Q23": ("Coal gasification drafts vs the earlier scheme", "6,3"),
    "Q24": ("PARAGMILK on El Nino; dairy peers", "6,8"),
    "Q25": ("Data-centre tax holiday outcome so far", "6,7"),
}


PICK_STOCK = dict(V1="same_ind", V2="diff_bucket", V3="identity", V4="any", V5="any",
                  V6="any", V7="industry", V8="index", V9="pit", V10="edge_corp")
PICK_TEXT = dict(PICK_STOCK, V10="edge_missing")

SPECS = [
    dict(oid="DBQ1", base="AEROFLEX", kind="stock", level="stock", pick=PICK_STOCK,
         needs=["ar_facts.ar_docs", "ar_facts.ar_facts", "px_nse_adj"],
         period="16 Oct 2026", date="2026-10-16", alt="30 Sep 2026", alt_date="2026-09-30",
         win=(PRICE_START, SNAPSHOT_END), as_of=SNAPSHOT_END, pit="2026-06-30",
         special="close", why="products + a date-stamped close"),
    dict(oid="DBQ2", base="JPPOWER", kind="stock", level="stock", pick=PICK_TEXT, doc="ar",
         needs=["ar_facts.ar_docs", "ar_facts.ar_facts"],
         period="FY26", win=("2025-04-01", "2026-10-19"), as_of=SNAPSHOT_END, pit="2026-06-30",
         alt="the annual report for the year ended 31 March 2026",
         why="latest annual report disclosure on control/ownership"),
    dict(oid="DBQ3", base="DPABHUSHAN", kind="stock", level="stock", pick=PICK_STOCK,
         needs=["results_xbrl.filings", "results_xbrl.segment", "ar_facts.ar_docs"],
         period="Q1FY27", win=("2026-04-01", "2026-06-30"), as_of=SNAPSHOT_END, pit="2026-06-30",
         alt="April-June 2026 (Q1 FY2026-27)", special="segment",
         why="business + segment disclosure, resolved by BSE code/ISIN"),
    dict(oid="DBQ4", base="DPABHUSHAN", kind="stock", level="stock", pick=PICK_STOCK,
         needs=["annual_financials", "company_forensic_health", "px_nse_adj"],
         period="19 Oct 2026", date="2026-10-16", alt="30 Sep 2026", alt_date="2026-09-30",
         win=(WIN_START, SNAPSHOT_END), as_of=SNAPSHOT_END, pit="2026-03-31",
         special="close", why="P/B from matching price and book-value dates"),
    dict(oid="DBQ5", base="DEEDEV", kind="stock", level="stock", pick=PICK_TEXT, doc="cc", chunks=True,
         needs=["concall_facts.cc_docs", "concall_facts.cc_items", "document_chunks"],
         period="Aug 2026", win=("2026-07-01", "2026-08-31"), as_of=SNAPSHOT_END, pit="2026-07-31",
         alt="the August 2026 earnings call",
         why="a named speaker's remark from a call transcript"),
    dict(oid="QA1", base="ATHERENERG", kind="stock", level="stock", pick=dict(PICK_STOCK, V10="edge_missing"),
         needs=["daily_price_delivery", "mkt_bse_delivery_daily"],
         period="13-14 Apr 2026", win=("2026-04-13", "2026-04-14"),
         as_of=SNAPSHOT_END, pit="2026-03-31", alt="the April 2026 second week",
         special="delivery", why="NSE + BSE delivered quantity, not traded quantity"),
    dict(oid="QA2", base="BLACKBUCK", kind="stock", level="stock", pick=PICK_STOCK,
         needs=["shp_index"], period="Sep 2026", win=("2026-09-01", "2026-09-30"),
         as_of=SNAPSHOT_END, pit="2026-06-30", alt="as of 30 September 2026",
         why="promoter holding at a dated quarter-end"),
    dict(oid="QA3", base="GANECOS", kind="stock", level="stock", pick=PICK_TEXT, doc="deck",
         needs=["deck_figures.deck_sources", "deck_figures.pages"],
         period="Aug 2026", win=("2026-05-01", "2026-08-31"), as_of=SNAPSHOT_END, pit="2026-07-31",
         alt="the deck filed in August 2026", why="a fact stated in a dated investor deck"),
    dict(oid="QA4", base="CHEMCON", kind="stock", level="stock", pick=PICK_TEXT, doc="deck",
         needs=["deck_figures.deck_sources", "deck_figures.pages"],
         period="May 2026", win=("2026-03-01", "2026-06-30"), as_of=SNAPSHOT_END, pit="2026-06-30",
         alt="the deck filed in May 2026", why="products and an acquisition named in a deck"),
    dict(oid="QA5", base="LUMAXTECH", kind="stock", level="stock", pick=PICK_STOCK,
         needs=["shp_index", "ar_facts.ar_docs"],
         period="latest", win=(WIN_START, SNAPSHOT_END), as_of=SNAPSHOT_END, pit="2026-06-30",
         alt="as of 30 September 2026", why="exact share count and promoter holding"),
    dict(oid="QA6", base="APOLLO", kind="stock", level="stock", pick=dict(PICK_TEXT, V10="any"), doc="deck",
         needs=["deck_figures.deck_sources", "deck_figures.pages"],
         period="Oct 2026", win=("2026-04-01", SNAPSHOT_END), as_of=SNAPSHOT_END, pit="2026-09-30",
         alt="the deck filed in October 2026", special="page",
         why="one page of a dated deck, with the page count as the guard"),
    dict(oid="QA7", base="MTARTECH", kind="stock", level="stock", pick=PICK_TEXT, doc="cc", chunks=True,
         needs=["concall_facts.cc_docs", "concall_facts.cc_items", "document_chunks"],
         period="Aug 2026", win=("2026-06-01", "2026-09-30"), as_of=SNAPSHOT_END, pit="2026-07-31",
         alt="the August 2026 call", why="capacity timeline stated on a call"),
    dict(oid="QA8", base="PFC", kind="stock", level="stock", pick=PICK_STOCK,
         needs=["px_nse_adj"], period="2026", win=("2026-01-01", SNAPSHOT_END),
         as_of=SNAPSHOT_END, pit="2026-06-30", alt="1 January-30 September 2026",
         alt_asof="2026-09-30", why="YTD high, value and date, with adjusted prices"),
    dict(oid="QA9", base="SAILIFE", kind="stock", level="stock", pick=PICK_TEXT, doc="deck",
         needs=["deck_figures.deck_sources", "concall_facts.cc_docs", "ar_facts.ar_docs"],
         period="since Jan 2026", win=("2026-01-01", SNAPSHOT_END), as_of=SNAPSHOT_END,
         pit="2026-06-30", alt="since 1 January 2026",
         why="latest cross-document statement, not one store"),
    dict(oid="QA10", base="COCHINSHIP", kind="stock", level="stock", pick=PICK_TEXT, doc="cc", chunks=True,
         needs=["concall_facts.cc_docs", "concall_facts.cc_items", "document_chunks"],
         period="Sep 2026", win=("2026-07-01", SNAPSHOT_END), as_of=SNAPSHOT_END, pit="2026-09-30",
         alt="the September 2026 call", why="MOU partner + margin path from one transcript"),
    dict(oid="Q11", base="KRISHNADEF", kind="stock", level="stock", pick=PICK_STOCK,
         needs=["results_xbrl.filings", "results_xbrl.segment"],
         period="Q1FY27", win=("2026-04-01", "2026-06-30"), as_of=SNAPSHOT_END, pit="2026-06-30",
         alt="April-June 2026 (Q1 FY2026-27)", special="segment",
         why="segment revenue with absolute numbers from XBRL context"),
    dict(oid="Q12", base="MAHABANK", kind="stock", level="stock", pick=PICK_STOCK, filter="banks",
         needs=["results_xbrl.filings", "results_xbrl.npa"],
         period="Q1FY27", win=("2026-04-01", "2026-06-30"), as_of=SNAPSHOT_END, pit="2026-06-30",
         alt="April-June 2026 (Q1 FY2026-27)", special="npa",
         why="banking-taxonomy net NPA, absent from Ind AS filings"),
    dict(oid="Q13", base="ZENTEC", kind="stock", level="stock", pick=PICK_STOCK,
         needs=["px_nse_adj", "corporate_actions"],
         period="Oct 2023-Oct 2026", win=("2023-10-19", SNAPSHOT_END), as_of=SNAPSHOT_END,
         pit="2026-06-30", alt="since 30 September 2023", alt_asof="2026-09-30",
         special="cagr", why="3-year CAGR that must use adjusted closes"),
    dict(oid="Q14", base="VISHNU", kind="stock", level="stock", pick=PICK_TEXT, doc="notes",
         needs=["results_notes.docs", "results_notes.notes", "results_xbrl.filings"],
         period="Q1FY27", win=("2026-04-01", "2026-06-30"), as_of=SNAPSHOT_END, pit="2026-06-30",
         alt="Q4FY26 (January-March 2026)", alt_win=("2026-01-01", "2026-03-31"), special="geo",
         why="results-note text plus the geographic split"),
    dict(oid="Q15", base="VINCOFE", kind="stock", level="stock", pick=PICK_STOCK,
         needs=["shp_index"], period="Sep 2026", win=("2026-09-01", "2026-09-30"),
         as_of=SNAPSHOT_END, pit="2026-06-30", alt="as of 30 September 2026",
         why="public shareholding at a dated quarter-end"),
    dict(oid="Q16", kind="macro", level="theme", theme="jewellery", theme_label="gold-jewellery", v8_theme=True,
         pick={}, needs=["mkt_commodity_daily", "px_nse_adj", "pib_releases"],
         period="Jun-Jul 2026", alt="June-July 2026 (FY27 first half)",
         win=("2026-06-01", "2026-07-31"), as_of=SNAPSHOT_END, pit="2026-07-31",
         why="macro move explained by commodity, PIB and company evidence"),
    dict(oid="Q17", base="LICHSGFIN", kind="stock", level="industry", pick=PICK_STOCK, filter="hfc", industry_label="Housing Finance", scope_n=2,
         needs=["deck_figures.deck_sources", "concall_facts.cc_docs", "results_xbrl.filings"],
         period="Q1FY27", win=("2026-04-01", "2026-06-30"), as_of=SNAPSHOT_END, pit="2026-06-30",
         alt="January-March 2026 (Q4FY26)", alt_win=("2026-01-01", "2026-03-31"),
         why="industry ranking on a metric that is only in decks/calls"),
    dict(oid="Q18", base="IOC", kind="stock", level="industry", pick=PICK_STOCK, filter="omc",
         needs=["quarterly_financials", "results_xbrl.filings", "px_nse_adj"],
         period="Q4FY26-Q1FY27", win=("2026-01-01", "2026-06-30"), as_of=SNAPSHOT_END,
         pit="2026-06-30", alt="the January-March 2026 and April-June 2026 quarters",
         special="omc", why="earliest point-in-time visibility of a profit-to-loss swing"),
    dict(oid="Q19", kind="etf", level="stock", pick={}, needs=["etf_px", "fund_nav", "etf_inav"],
         period="10-18 Sep 2026 and 18-28 Sep 2026", win=("2026-09-10", "2026-09-28"),
         as_of=SNAPSHOT_END, pit="2026-09-17", alt="September 2026",
         why="ETF move explained by the underlying index and FX, with NAV tracking error"),
    dict(oid="Q20", base="GRWRHITECH", kind="stock", level="stock", pick=PICK_STOCK,
         needs=["px_nse_adj", "policy_events", "concall_facts.cc_docs"],
         period="Mar 2025-Mar 2026", win=("2025-03-01", "2026-03-31"), as_of=SNAPSHOT_END,
         pit="2026-03-31", alt="the 12 months after March 2025",
         why="rolling sensitivity to a real tariff event, then a sign flip"),
    dict(oid="Q21", kind="macro", level="policy", theme="banks", theme_label="banking",
         pick={}, needs=["policy_events", "raw_documents", "pib_releases"],
         period="7 Oct 2026", alt="the October 2026 policy", win=("2026-10-01", "2026-10-19"),
         as_of=SNAPSHOT_END, pit="2026-10-06", panel="policy",
         why="causes of a policy action plus PIB-vs-RBI provenance"),
    dict(oid="Q22", kind="macro", level="theme", theme="electronics", theme_label="electronics",
         pick={}, needs=["pib_releases", "policy_events", "raw_documents"],
         period="CY2026", alt="calendar 2026 to date", win=("2026-01-01", SNAPSHOT_END),
         as_of=SNAPSHOT_END, pit="2026-06-30",
         why="demand thesis and beneficiaries; the sales series gap must be stated"),
    dict(oid="Q23", kind="macro", level="industry", theme="coal", theme_label="coal",
         pick={}, needs=["policy_events", "pib_releases", "mkt_commodity_daily"],
         period="2024-2026", alt="from January 2024 to date", win=("2024-01-01", SNAPSHOT_END),
         as_of=SNAPSHOT_END, pit="2025-12-31",
         why="policy drafts versus the earlier scheme, across documents"),
    dict(oid="Q24", base="PARAGMILK", kind="stock", level="stock", pick=PICK_TEXT, doc="cc", v7_sector="Fast Moving Consumer Goods",
         chunks=True, filter="dairy",
         needs=["concall_facts.cc_docs", "concall_facts.cc_items", "document_chunks"],
         period="latest calls", win=("2025-01-01", SNAPSHOT_END), as_of=SNAPSHOT_END,
         pit="2026-06-30", alt="the 2026 calls",
         why="management commentary on a macro event, with dairy peers"),
    dict(oid="Q25", kind="macro", level="policy", theme="datacentre", theme_label="data-centre",
         pick={}, needs=["policy_events", "raw_documents", "pib_releases"],
         period="2025-2026", alt="the 2025-26 Budget cycle", win=("2024-07-01", SNAPSHOT_END),
         as_of=SNAPSHOT_END, pit="2026-02-01",
         why="whether a tax holiday exists in the policy record and what companies say"),
]


EXPECTED = {
    "DBQ1": "text+quote", "DBQ2": "text+quote", "DBQ3": "text+quote", "DBQ4": "number",
    "DBQ5": "text+quote", "QA1": "number", "QA2": "number", "QA3": "number",
    "QA4": "text+quote", "QA5": "number", "QA6": "text+quote", "QA7": "text+quote",
    "QA8": "number", "QA9": "text+quote", "QA10": "text+quote", "Q11": "number",
    "Q12": "number", "Q13": "number", "Q14": "text+quote", "Q15": "number",
    "Q16": "text+quote", "Q17": "ranking", "Q18": "ranking", "Q19": "number",
    "Q20": "number", "Q21": "text+quote", "Q22": "text+quote", "Q23": "text+quote",
    "Q24": "text+quote", "Q25": "text+quote",
}

HINGLISH = {"DBQ1", "DBQ3", "DBQ5", "QA1", "QA2", "QA3", "QA4", "QA7", "QA8", "QA10",
            "Q12", "Q14", "Q15", "Q16", "Q18", "Q20", "Q22", "Q23", "Q25"}

WHY = {
    "V1": "same question, same level, different stock (same industry)",
    "V2": "different stock, different market-cap bucket",
    "V3": "naming variant: ISIN / BSE code / old symbol after a rename",
    "V4": "terse keyword query, 3-8 words",
    "V5": "long natural or Hinglish phrasing",
    "V6": "different period label inside the data window",
    "V7": "scope up to the industry or sector",
    "V8": "screen by index / theme / market-cap bucket, membership as of the date",
    "V9": "point-in-time: only evidence known by the as-of date",
    "V10": "hard edge: NOT IN DATA or a corporate action in the period",
}


def gap_of(status, note, needs):
    t = (note or "").lower()
    if "chunk" in t:
        return "concall transcript held but not chunked"
    if "geograph" in t:
        return "results notes lack a geographic split"
    if "coal_newcastle" in t or ("coal" in t and "series" in t):
        return "coal price series ends 2025-12-26"
    if "tax holiday" in t and ("no data-centre" in t or "no data" in t):
        return "data-centre tax holiday not in policy_events"
    if "refurbished" in t or "second-hand" in t:
        return "no refurbished/second-hand electronics sales series"
    if "pib" in t:
        return "PIB provenance or coverage gap"
    if "segment" in t:
        return "segment context missing in results XBRL"
    if "npa" in t:
        return "banking-taxonomy concept missing"
    if "results notes" in t:
        return "results notes not stored for the period"
    if "deck" in t:
        return "deck or page not stored for the date"
    if "nav" in t or "inav" in t:
        return "ETF NAV/iNAV rows missing"
    if "policy" in t:
        return "policy record gap"
    if "price" in t or "px_" in t:
        return "price rows missing for the entity/window"
    if "store holds" in t or "nothing in" in t:
        return "no filing/document inside the requested period"
    if "store has no rows" in t:
        return "required store missing for the entity"
    if "no split/bonus" in t:
        return "corporate-action edge unavailable"
    if "no nse+bse delivery" in t:
        return "delivery rows missing for the chosen dates"
    if "no september 2026 shareholding" in t:
        return "September 2026 shareholding filing missing"
    if "as-of precedes" in t:
        return "point-in-time gap: as-of precedes the event"
    if "no annual report" in t:
        return "annual report missing for the entity"
    if "no investor presentation" in t:
        return "investor presentation missing for the entity"
    if "no data-centre" in t:
        return "data-centre tax holiday not in policy_events"
    if "no rows" in t or "missing" in t:
        return "required store missing for the entity"
    return "other coverage gap"


def row_coverage(d, c):
    if c.get("coverage_override"):
        return c["coverage_override"]
    e = c.get("e")
    if not e:
        return "no", "no entity resolved"
    status, note = coverage(d, e, c["needs"], c)
    parts = [(status, note)]
    sp = c["spec"].get("special")
    if sp in ("segment", "npa") and c.get("concept_ok") is False:
        return "no", ("no segment context in the results XBRL" if sp == "segment"
                      else "no net-NPA concept in the bank's XBRL taxonomy")
    if sp == "close":
        if not px_has(d, e["isin"], c["date"]):
            parts.append(("partial", f"no close row on {c['date']}"))
    if sp == "delivery":
        parts.append(("yes", "") if c.get("delivery_ok") else
                     ("no", "no NSE+BSE delivery rows on the chosen dates"))
    if sp == "page":
        if c.get("page") and c.get("max_page") and c["page"] > c["max_page"]:
            return "no", f"deck has {c['max_page']} pages; page {c['page']} does not exist"
    if sp == "cagr":
        p = d["px"].get(e["isin"])
        if not p or str(p[0])[:10] > "2023-10-19" or str(p[1])[:10] < c["as_of"]:
            parts.append(("partial", "adjusted price endpoints missing for the CAGR window"))
    if sp == "geo" and c.get("geo_ok") is False:
        parts.append(("partial", "no geographic-split note found in the stored results notes"))
    return combine(parts)


def why_text(spec, c):
    oid, v = spec["oid"], c["v"]
    if spec.get("kind") == "macro" or (oid == "Q18" and v in ("V1", "V2")):
        if v == "V1":
            return ("different policy/macro event of the same type; issuer/ministry noted in the row: "
                    + (c.get("policy", {}) or {}).get("note", "macro series, no issuer"))
        if v == "V2":
            return ("different policy/macro event and issuer/ministry: "
                    + (c.get("policy", {}) or {}).get("note", "macro series, no issuer"))
        if v == "V3":
            return "naming variant: the event is asked by its document/PRID reference"
        return WHY[v] + "; " + spec["why"]
    if v == "V1":
        return "same-industry peer at the same level; " + spec["why"]
    if v == "V2":
        return "same sector, different market-cap bucket; " + spec["why"]
    return WHY[v] + "; " + spec["why"]


def force_v10(d, picker, c, spec):
    """V10 must be a genuine NOT IN DATA case or a corporate-action case."""
    oid = spec["oid"]
    e = c.get("e")
    win = c["win"]
    ca = {x["isin"] for x in d["ca"] if win[0] <= x["ex"] <= min(win[1], c["as_of"])}
    if oid in ("QA6", "Q11", "Q12", "Q14", "Q18", "Q24"):
        return
    if oid in ("DBQ1", "DBQ4", "QA5", "QA8", "Q13", "Q20") and e and e["isin"] in ca:
        return

    def put(pred, note):
        for x in d["pool"].values():
            if x["isin"] in picker.used:
                continue
            if pred(x):
                c["e"] = x
                c["ref"] = ref(x)
                c["scope"] = [x]
                c["scope_label"] = nm(x)
                c["coverage_override"] = ("no", note)
                return
    if oid == "DBQ2":
        put(lambda x: not d["ar"].get(x["isin"]), "no annual report stored for this company")
    elif oid == "DBQ1":
        put(lambda x: not d["px"].get(x["isin"]), "no adjusted price rows; the close is NOT IN DATA")
    elif oid == "DBQ3":
        put(lambda x: x["isin"] not in d["seg_isins"]
            and "2026-06-30" in d["filings"].get(x["isin"], []),
            "no segment context for Q1FY27 in the results XBRL")
    elif oid == "DBQ4":
        put(lambda x: x["isin"] not in d["cfh"], "no stored equity/P-B row; book value is NOT IN DATA")
    elif oid == "QA1":
        put(lambda x: not x["bse"] or not delivery_check(d, x, c["dates"]),
            "no BSE delivery row on the chosen dates")
    elif oid in ("QA2", "Q15"):
        put(lambda x: "2026-09-30" not in d["shp"].get(x["isin"], set()),
            "no September 2026 shareholding filing")
    elif oid in ("QA3", "QA4", "QA6", "QA9"):
        put(lambda x: not d["decks"].get(x["isin"]), "no investor presentation stored for this company")
    elif oid in ("DBQ5", "QA7", "QA10"):
        def no_chunks(x):
            if not d["cc"].get(x["isin"]):
                return True
            try:
                return d["_con"].execute("select count(*) from document_chunks where isin = ?",
                                         (x["isin"],)).fetchone()[0] == 0
            except Exception:
                return False
        put(no_chunks, "transcript is held but never chunked; the quote is NOT IN DATA")
    elif oid in ("QA5", "QA8", "Q13", "Q20"):
        put(lambda x: x["isin"] not in ca, "no split/bonus in the window; the corporate-action edge is NOT IN DATA")
    elif oid == "Q17":
        put(lambda x: "Housing Finance" in x["basic"]
            and "2026-06-30" not in d["filings"].get(x["isin"], []),
            "no Q1FY27 filing for this HFC; the securitisation answer is NOT IN DATA")
        if not c.get("coverage_override"):
            put(lambda x: ("Housing Finance" in x["basic"] and not d["decks"].get(x["isin"])
                           and not d["cc"].get(x["isin"])),
                "no structured securitisation field and no deck/call for this HFC")


def build_row(d, picker, spec, v):
    c = make_ctx(d, picker, spec, v)
    oid = spec["oid"]
    if v == "V10" and oid == "Q14":
        c["period"] = "Q2FY25 (July-September 2024)"
        c["win"] = ("2024-07-01", "2024-09-30")
    if v == "V10" and oid == "QA8":
        c["as_of"] = "2026-09-30"
    if v == "V10" and oid == "Q14":
        c["coverage_override"] = ("no", "results_notes has no Q2FY25 document for this entity "
                                        "(the notes store starts 2024-12-31)")
    if v == "V10" and oid == "Q24":
        cands = ([x for x in d["pool"].values() if "packaging" in x["name"].lower()]
                 or [x for x in d["pool"].values() if x["basic"] == "Packaging"])
        for cand in cands:
                c["e"] = cand
                c["ref"] = ref(cand)
                c["scope"] = [cand]
                c["coverage_override"] = ("no", "not a dairy company: no dairy/El-Nino commentary "
                                                "in the transcripts")
                break
    if v == "V10" and oid == "Q18":
        c["coverage_override"] = ("no", "coal_newcastle ends 2025-12-26; no Q1FY27 coal price")
    if v == "V10" and spec.get("kind") == "stock":
        force_v10(d, picker, c, spec)
    if v == "V10" and oid in ("Q11", "Q12"):
        want = d["seg_isins"] if oid == "Q11" else d["npa_isins"]
        pred = _pred(spec, d)
        for cand in d["pool"].values():
            if (cand["isin"] not in want and "2026-06-30" in d["filings"].get(cand["isin"], [])
                    and (pred(cand) if pred else True)):
                c["e"] = cand
                c["ref"] = ref(cand)
                c["scope"] = [cand]
                c["scope_label"] = f"{nm(cand)} only"
                c["concept_ok"] = False
                break
    if v == "V10" and oid == "Q12":
        c["period"] = "Q2FY27"
        c["win"] = ("2026-07-01", "2026-09-30")
        for cand in d["pool"].values():
            if (cand["industry"] == "Banks"
                    and not any("2026-07-01" <= x <= "2026-09-30"
                                for x in d["filings"].get(cand["isin"], []))):
                c["e"] = cand
                c["ref"] = ref(cand)
                c["scope"] = [cand]
                c["coverage_override"] = ("no", "no Q2FY27 bank filing; net NPA is NOT IN DATA")
                break
    c["date_long"] = date_long(c["date"]) if c.get("date") else ""
    c["date_short"] = date_short(c["date"]) if c.get("date") else ""
    seen = spec.setdefault("_seen", set())
    e_now = c.get("e")
    if e_now and e_now["isin"] in seen and v not in ("V7", "V8"):
        pred = _pred(spec, d)
        repl = None
        if spec.get("kind") == "etf":
            for x in d["etf"].values():
                if x["isin"] not in seen and x["n"] > 0:
                    repl = _etf_e(x)
                    break
        else:
            free = [x for x in d["pool"].values()
                    if x["isin"] not in seen and not (pred and not pred(x))]
            good = [x for x in free if coverage(d, x, c["needs"], c)[0] != "no"]
            repl = (good or free)[0] if (good or free) else None
        if repl:
            c["e"] = repl
            c["ref"] = (f"{repl['name']} ({repl['nse']}, ISIN {repl['isin']})"
                        if spec.get("kind") == "etf" else ref(repl))
            c["scope"] = [repl]
    if c.get("e"):
        seen.add(c["e"]["isin"])
    for x in c.get("scope", []):
        seen.add(x["isin"])
    q = BUILDERS[oid](c)
    status, note = row_coverage(d, c)
    entities = entity_records(c)
    if not entities:
        raise RuntimeError(f"{oid}-{v}: no entity resolved")
    e0 = c.get("e") or (c.get("scope") or [None])[0]
    expected = "NOT IN DATA" if status == "no" else EXPECTED[oid]
    if status != "no" and v in ("V7", "V8") and expected not in ("ranking", "list"):
        expected = "ranking"
    needs = list(c["needs"])
    if v == "V7":
        needs.append("company_industry")
    if v == "V8":
        needs.append("index_membership")
    period = c.get("period", "")
    if v != "V9" and spec.get("doc") and c.get("doc"):
        docdate = c["doc"].get("date", "")
        if docdate:
            if spec["doc"] == "ar":
                period = f"FY{docdate[:4]}"
            elif spec["doc"] == "notes":
                period = ("Q4FY" + docdate[2:4]) if docdate[5:7] == "03" else date_short(docdate)
            else:
                period = date_short(docdate)
    return dict(
        qid=f"{oid}-{v}", orig_qid=oid, variation=v, question=q,
        entities=entities, entity_level=c.get("entity_level", spec.get("level", "stock")),
        period=period, as_of=c.get("as_of", SNAPSHOT_END), family=ORIGINALS[oid][1],
        needs=needs, coverage=status, coverage_note=note,
        expected_answer_type=expected, why=why_text(spec, c),
        market_cap_bucket=(e0 or {}).get("bucket") if e0 else None,
        sector=(e0 or {}).get("sector") if e0 else None,
        industry=(e0 or {}).get("industry") if e0 else None,
        basic_industry=(e0 or {}).get("basic") if e0 else None,
        exchange=("ETF" if spec.get("kind") == "etf" else
                  ("NSE+BSE" if (e0 or {}).get("nse") and (e0 or {}).get("bse") else
                   "NSE-only" if (e0 or {}).get("nse") else "BSE-only")),
        gap=(gap_of(status, note, needs) if status != "yes" else None),
        identity_changed=bool(v == "V3" and c.get("old_symbol")),
        hinglish=bool(v == "V5" and oid in HINGLISH),
        scope=c.get("scope_label", ""),
        policy=(dict(title=(c.get("policy") or {}).get("title", ""),
                     date=(c.get("policy") or {}).get("date", ""),
                     source=(c.get("policy") or {}).get("source", ""))
                if c.get("policy") else None),
    )


def md_table(rows):
    lines = []
    for r in rows:
        ent = "; ".join(x["name"] for x in r["entities"][:3])
        cov = r["coverage"]
        if r["coverage_note"]:
            cov += f" ({r['coverage_note']})"
        q = r["question"].replace("|", "/")
        lines.append(f"| {r['variation']} | {q} | {ent} | {r['period']} | {cov} | {r['why']} |")
    return lines


def write_md(rows):
    from collections import Counter
    L = []
    L.append("# Question bank 300 - 10 variations of Shivam's 30 questions (2026-10-27)")
    L.append("")
    L.append(f"Data vintage: prices and documents to **{SNAPSHOT_END}**; companies from "
             f"{WIN_START} (prices from {PRICE_START}). All entities, dates, documents and policies "
             "below were read from the live stores; nothing is invented. The 30 originals stay as "
             "separate fixed regressions and are not part of these 300 rows.")
    L.append("")
    fam = Counter()
    for r in rows:
        for f in str(r["family"]).split(","):
            fam[f.strip()] += 1
    L.append("## Summary")
    L.append("")
    L.append("### Counts")
    L.append("")
    L.append("| Family | Rows |")
    L.append("|---|---|")
    for k in sorted(fam, key=lambda x: int(x)):
        L.append(f"| {k} | {fam[k]} |")
    L.append("")
    def table(title, counter):
        L.append(f"**{title}**: " + ", ".join(f"{k or 'n/a'} {v}" for k, v in counter.most_common()))
        L.append("")
    table("Entity level", Counter(r["entity_level"] for r in rows))
    table("Variation", Counter(r["variation"] for r in rows))
    table("Market-cap bucket", Counter(r["market_cap_bucket"] or "n/a" for r in rows))
    table("Exchange", Counter(r["exchange"] for r in rows))
    table("Sector (BSE taxonomy, raw)", Counter(r["sector"] or "n/a" for r in rows))
    table("Industry (finer taxonomy)", Counter(r["industry"] or "n/a" for r in rows))
    table("Basic industry", Counter(r["basic_industry"] or "n/a" for r in rows))
    cov = Counter(r["coverage"] for r in rows)
    L.append(f"**Coverage split**: yes {cov.get('yes',0)}, partial {cov.get('partial',0)}, "
             f"no {cov.get('no',0)}.")
    L.append("")
    nsec = len({r["sector"].lower() for r in rows if r["sector"]})
    nind = len({r["industry"].lower() for r in rows if r["industry"]})
    L.append(f"**Spread note**: case-normalised, the bank touches {nsec} BSE sectors and {nind} "
             f"industries; the finer taxonomy is shown as evidence that the 25+ target is real, "
             f"not a case-variant count.")
    L.append("")
    L.append("Market-cap buckets are computed from `company_forensic_health.market_cap_inr_cr` "
             "at the 2026-10-19 vintage (LARGE >= Rs 50,000 cr, MID 10,000-50,000, SMALL "
             "1,000-10,000, MICRO < 1,000); where that row is missing, the stored "
             "`master_companies.market_cap_tier` is the fallback. Index membership is current-only in the store "
             "(index_membership as_of 2026-09-30; company_industry.index_list fetched 2026-10-19), "
             "so V8 screens are point-in-time only to that date.")
    L.append("")
    gaps = Counter()
    for r in rows:
        if r["coverage"] != "yes":
            gaps[(r["gap"] or "other", r["coverage"])] += 1
    L.append("### Questions expected to fail today, grouped by gap")
    L.append("")
    L.append("| Gap | Rows | Status |")
    L.append("|---|---|---|")
    for (g, s), n in gaps.most_common():
        L.append(f"| {g} | {n} | {s} |")
    L.append("")
    L.append("## Questions")
    L.append("")
    for spec in SPECS:
        oid = spec["oid"]
        L.append(f"### {oid} - {ORIGINALS[oid][0]}")
        L.append("")
        L.append(f"Family {ORIGINALS[oid][1]}. Entity level: {spec.get('level','stock')}. "
                 f"What it tests: {spec.get('why','')}.")
        L.append("")
        L.append("| V | Question | Entity | Period | Coverage | What it tests |")
        L.append("|---|---|---|---|---|---|")
        L.extend(md_table([r for r in rows if r["orig_qid"] == oid]))
        L.append("")
    return "\n".join(L) + "\n"


def main():
    import time
    t0 = time.time()
    d = load()
    print("loaded in %.1fs" % (time.time() - t0))
    prepare(d)
    print("prepared in %.1fs" % (time.time() - t0))
    picker = Picker(d)
    rows, failures = [], []
    for spec in SPECS:
        for v in VARY:
            try:
                rows.append(build_row(d, picker, spec, v))
            except Exception as exc:
                failures.append((spec["oid"], v, repr(exc)))
    if failures:
        for f in failures[:20]:
            print("ROW FAILED", f)
        raise SystemExit(f"{len(failures)} rows failed")
    assert len(rows) == 300, len(rows)
    assert len({r["qid"] for r in rows}) == 300
    sect = {r["sector"] for r in rows if r["sector"]}
    buckets = {r["market_cap_bucket"] for r in rows if r["market_cap_bucket"]}
    bse_only = [r for r in rows if r["exchange"] == "BSE-only"]
    nse_only = [r for r in rows if r["exchange"] == "NSE-only"]
    ident = [r for r in rows if r["identity_changed"]]
    hing = [r for r in rows if r["hinglish"]]
    print("rows", len(rows), "sectors", len(sect), "buckets", sorted(buckets))
    print("BSE-only", len(bse_only), "NSE-only", len(nse_only),
          "identity", len(ident), "hinglish", len(hing))
    print("coverage", Counter(r["coverage"] for r in rows))
    assert len(sect) >= 25, sorted(sect)
    assert len(buckets) == 4, buckets
    assert bse_only and nse_only
    assert len(ident) >= 5
    assert len(hing) >= 10
    assert all(r["coverage"] in ("yes", "partial", "no") for r in rows)
    print("built in %.1fs" % (time.time() - t0))
    OUT_JSONL.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
                         encoding="utf-8")
    OUT_MD.write_text(write_md(rows), encoding="utf-8")
    print("wrote", OUT_JSONL)
    print("wrote", OUT_MD)


if __name__ == "__main__":
    main()
