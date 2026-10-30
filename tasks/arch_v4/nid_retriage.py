#!/usr/bin/env python3
"""NID re-triage (v4.2 decision 3): for every ``proxy`` verdict, search what we already hold.

The first triage (`NID_TRIAGE.md`) sent 74 of the 150 NOT-IN-DATA cases to a proxy.  Shivam's
rule is that a proxy is the **last resort**: search everything held, fetch if the fetch is free
within a day, and only then bridge with a proxy that carries its ``search_log`` ref.  This
script produces that log, deterministically and read-only, with no model in the loop:

* resolve the company named in the question against ``master_companies`` (longest name match,
  then the symbol, then a six-digit BSE code);
* run one bounded probe per held structured store, scoped to that ISIN;
* run the document search the query layer uses (``lookups_docs.doc_find``) on the class terms;
* write every search, its filter and its top hits to ``nid_search_logs/<case>.json``.

It does **not** re-label a ticket.  ``candidate_real_evidence`` is a claim that a held row is
worth a human look, and the controller reviews these logs afterwards.

    python tasks/arch_v4/nid_retriage.py            # writes nid_search_logs/ + the summary
    python tasks/arch_v4/nid_retriage.py --check    # self-check only, no writes
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DATA = Path(os.environ.get("REALITY_DATA_ROOT") or (ROOT / "reality_engine" / "data"))
TRIAGE = HERE / "nid_triage.json"
OUT = HERE / "nid_search_logs"
SUMMARY = HERE / "nid_retriage_summary.json"
SERVER = ROOT / "plugins" / "reality-data" / "server"

sys.path.insert(0, str(ROOT))

# --------------------------------------------------------------------------- #
# The ten classes that own all 74 proxy tickets: the terms a deterministic
# search can look for, and the XBRL concept names the class actually needs.
# --------------------------------------------------------------------------- #
CLASSES: dict[str, dict] = {
    "bank_transmission": {
        "terms": ["net interest margin", "nim", "credit cost", "provision", "treasury"],
        "xbrl": ["InterestExpended", "InterestEarned", "NetProfitLossForPeriod"],
        "why": "NIM / credit cost is a formula over held XBRL legs"},
    "mechanism_lag": {
        "terms": ["commodity", "raw material", "input cost", "spread", "lag"],
        "xbrl": [],
        "why": "the mechanism is measurable from held price + commodity series"},
    "free_float_weight": {
        "terms": ["free float", "float", "promoter", "public shareholding", "weight"],
        "xbrl": [],
        "why": "shares x (1 - promoter) is arithmetic on held ownership"},
    "hfc_securitisation": {
        "terms": ["securitisation", "securitization", "assigned loans", "sell down", "housing loan"],
        "xbrl": ["Receivables", "LoansAndAdvances"],
        "why": "securitisation income is disclosed in the notes"},
    "valuation_judgement": {
        "terms": ["price to book", "pb", "roe", "payout", "free cash flow", "valuation"],
        "xbrl": ["NetProfitLossForPeriod", "NetWorth"],
        "why": "PB/ROE is a formula over held XBRL + price"},
    "float_income": {
        "terms": ["client funding", "float", "bank balance", "interest income", "idle cash"],
        "xbrl": [],
        "why": "the funding book is disclosed; the short rate is held"},
    "retail_mtm": {
        "terms": ["mark to market", "mtm", "retail holding", "public shareholding"],
        "xbrl": [],
        "why": "public % x shares x price change is an upper bound"},
    "second_order_suppliers": {
        "terms": ["supplier", "vendor", "customer", "supply chain", "second order"],
        "xbrl": [],
        "why": "named supplier/customer pairs are in the filings"},
    "policy_incidence": {
        "terms": ["duty", "tariff", "input cost", "raw material", "policy"],
        "xbrl": [],
        "why": "cost shares over policy events are held"},
    "forecast_scenario": {
        "terms": ["scenario", "if", "target", "guidance"],
        "xbrl": [],
        "why": "a scenario is arithmetic on held legs, never a target price"},
}

STOP = {
    "what", "which", "does", "with", "from", "this", "that", "have", "will", "about", "after",
    "before", "over", "under", "into", "they", "their", "there", "when", "where", "been",
    "would", "should", "could", "kya", "hai", "hain", "ka", "ke", "ki", "ko", "mein", "aur",
    "kitna", "kitni", "batao", "bata", "nse", "bse", "the", "and", "for", "not", "are", "was",
    "you", "our", "its", "any", "all", "per", "than", "then", "how", "why", "who", "can",
}


# --------------------------------------------------------------------------- #
# small helpers
# --------------------------------------------------------------------------- #
def connect_ro(path: Path, timeout_s: float = 20.0):
    """The only sanctioned read-only opener (AGENTS.md §3.2)."""
    from reality_engine.db.readonly import connect_ro as _ro
    return _ro(path, timeout_s=timeout_s)


def tokens(text: str) -> list[str]:
    """Content words of a question, in first-seen order, 3+ letters only."""
    seen: list[str] = []
    for raw in "".join(c if (c.isalnum() or c.isspace()) else " " for c in str(text)).split():
        w = raw.lower()
        if len(w) < 3 or w in STOP or w.isdigit() or w in seen:
            continue
        seen.append(w)
    return seen


def _like_terms(terms: list[str]) -> list[str]:
    """One LIKE pattern per term, longest first so the specific phrase is tried before the word."""
    return [f"%{t}%" for t in sorted({t.lower() for t in terms}, key=len, reverse=True)]


def probe_rows(con, sql: str, params: tuple, limit: int = 5) -> list[dict]:
    cur = con.execute(sql, params)
    cols = [d[0] for d in cur.description]
    out = []
    for row in cur.fetchmany(limit):
        out.append({c: (v if not isinstance(v, bytes) else f"<{len(v)} bytes>")
                    for c, v in zip(cols, row)})
    return out


def count_rows(con, sql: str, params: tuple) -> int:
    row = con.execute(sql, params).fetchone()
    return int(row[0]) if row else 0


# --------------------------------------------------------------------------- #
# entity resolution: deterministic, longest match wins
# --------------------------------------------------------------------------- #
_SUFFIX = {"LTD", "LIMITED", "PVT", "PRIVATE", "CO", "COMPANY", "CORP", "CORPORATION",
           "INC", "PLC", "INDIA", "INDUSTRIES", "INDUSTRY", "ENTERPRISES", "THE"}
_CONNECT = {"OF", "AND", "&", "THE", "DE", "DU"}
# A first token this generic identifies nobody; matching it would resolve the wrong company.
_GENERIC = {"UNITED", "GENERAL", "STANDARD", "NATIONAL", "INDIAN", "INDIA", "STATE", "NEW",
            "FIRST", "GLOBAL", "PREMIER", "ADVANCED", "MODERN", "ORIENTAL", "SUN", "STAR"}


def needles(name: str) -> list[str]:
    """Every form of a company name a question might print: full, suffix-stripped, first word.

    A question says "Muthoot's cost of funds", never "Muthoot Finance Ltd", so matching only the
    registered name resolved almost nothing (and let a ticker like RETALL match "retail").
    """
    toks = str(name).upper().replace("&", " & ").split()
    out: list[str] = []

    def add(ts: list[str]) -> None:
        s = " ".join(ts)
        if len(s) >= 3:
            out.append(s)
    add(toks)
    while len(toks) > 1 and toks[-1] in _SUFFIX and toks[-2] not in _CONNECT:
        toks = toks[:-1]
        add(toks)
    if len(toks[0]) >= 6 and toks[0] not in _GENERIC:
        add(toks[:1])
    return out


def load_entities() -> list[tuple[str, str, str]]:
    """(needle, isin, symbol) for every known issuer, longest needle first.

    ``security_master`` rather than ``master_companies``: it keeps delisted names, which is
    exactly the population a NOT-IN-DATA ticket tends to be about (§C.2's resolve stage).
    """
    con = connect_ro(DATA / "equity_intelligence.db", timeout_s=30)
    rows = con.execute(
        "SELECT isin, nse_symbol, name FROM security_master "
        "WHERE isin IS NOT NULL AND name IS NOT NULL AND length(name) >= 4").fetchall()
    con.close()
    out = []
    for isin, sym, name in rows:
        for needle in needles(name):
            out.append((needle, isin, sym))
    out.sort(key=lambda r: -len(r[0]))
    return out


def resolve_entity(question: str, entities: list[tuple[str, str, str]]) -> dict:
    q = " " + "".join(c if (c.isalnum() or c == "&") else " " for c in question).upper() + " "
    q = " ".join(q.split())
    for needle, isin, sym in entities:
        if f" {needle} " in f" {q} ":
            return {"resolved": sym, "isin": isin, "matched": needle}
    # A bare symbol is evidence only when the question wrote it as a symbol.  Upper-casing the
    # whole question first made "retail", "take", "premium" and "trust" resolve to real tickers.
    raw = [w.strip(".,:;()[]'\"") for w in str(question).split()]
    shouted = {w.upper() for w in raw if len(w) >= 4 and w.isupper()}
    for needle, isin, sym in entities:
        if sym and str(sym).upper() in shouted:
            return {"resolved": sym, "isin": isin, "matched": f"symbol {sym}"}
    for w in raw:
        if len(w) == 6 and w.isdigit():
            con = connect_ro(DATA / "equity_intelligence.db", timeout_s=20)
            row = con.execute(
                "SELECT isin, nse_symbol FROM security_master WHERE bse_code=?", (w,)).fetchone()
            con.close()
            if row:
                return {"resolved": row[1], "isin": row[0], "matched": f"BSE code {w}"}
    return {"resolved": None, "isin": None, "matched": None}


# --------------------------------------------------------------------------- #
# the probes: one per held structured store, each scoped to one ISIN
# --------------------------------------------------------------------------- #
def probe_xbrl(isin: str, concepts: list[str]) -> dict:
    if not concepts:
        return {"store": "results_xbrl.facts", "skipped": "class has no XBRL concept"}
    con = connect_ro(DATA / "results_xbrl.db")
    try:
        files = [r[0] for r in con.execute(
            "SELECT DISTINCT file FROM filings WHERE isin=? LIMIT 400", (isin,)).fetchall()]
        if not files:
            return {"store": "results_xbrl.facts", "filter": f"filings.isin={isin}",
                    "rows": 0, "hits": [], "note": "no XBRL filing for this ISIN"}
        marks = ",".join("?" * len(files))
        cmarks = ",".join("?" * len(concepts))
        where = f"file IN ({marks}) AND concept IN ({cmarks})"
        params = (*files, *concepts)
        n = count_rows(con, f"SELECT COUNT(*) FROM facts WHERE {where}", params)
        hits = probe_rows(
            con, f"SELECT file, concept, value, unit FROM facts WHERE {where} LIMIT 5", params)
        return {"store": "results_xbrl.facts", "filter": where.replace("?", "{}")[:200],
                "filings": len(files), "rows": n, "hits": hits}
    finally:
        con.close()


def probe_ar(isin: str, terms: list[str]) -> dict:
    if not terms:
        return {"store": "ar_facts", "skipped": "no terms"}
    con = connect_ro(DATA / "ar_facts.db")
    try:
        pats = _like_terms(terms)
        where = "isin=? AND (" + " OR ".join(["category LIKE ? OR item LIKE ?"] * len(pats)) + ")"
        params = (isin, *[p for pat in pats for p in (pat, pat)])
        n = count_rows(con, f"SELECT COUNT(*) FROM ar_facts WHERE {where}", params)
        hits = probe_rows(con, f"SELECT doc_id, category, item, quote FROM ar_facts "
                               f"WHERE {where} LIMIT 5", params)
        return {"store": "ar_facts", "filter": "isin + category|item LIKE class terms",
                "rows": n, "hits": hits}
    finally:
        con.close()


def probe_concall(isin: str, terms: list[str]) -> dict:
    if not terms:
        return {"store": "concall_facts.cc_items", "skipped": "no terms"}
    con = connect_ro(DATA / "concall_facts.db")
    try:
        pats = _like_terms(terms)
        where = "isin=? AND (" + " OR ".join(["metric LIKE ? OR statement LIKE ?"] * len(pats)) + ")"
        params = (isin, *[p for pat in pats for p in (pat, pat)])
        n = count_rows(con, f"SELECT COUNT(*) FROM cc_items WHERE {where}", params)
        hits = probe_rows(con, f"SELECT doc_id, metric, statement, quote FROM cc_items "
                               f"WHERE {where} LIMIT 5", params)
        return {"store": "concall_facts.cc_items", "filter": "isin + metric|statement LIKE terms",
                "rows": n, "hits": hits}
    finally:
        con.close()


def probe_deck(isin: str, terms: list[str]) -> dict:
    if not terms:
        return {"store": "deck_figures.facts", "skipped": "no terms"}
    con = connect_ro(DATA / "deck_figures.db")
    try:
        shas = [r[0] for r in con.execute(
            "SELECT DISTINCT sha256 FROM deck_sources WHERE isin=? LIMIT 400", (isin,)).fetchall()]
        if not shas:
            return {"store": "deck_figures.facts", "filter": f"deck_sources.isin={isin}",
                    "rows": 0, "hits": [], "note": "no deck for this ISIN"}
        pats = _like_terms(terms)
        marks = ",".join("?" * len(shas))
        where = f"sha256 IN ({marks}) AND (" + " OR ".join(["metric LIKE ?"] * len(pats)) + ")"
        params = (*shas, *pats)
        n = count_rows(con, f"SELECT COUNT(*) FROM facts WHERE {where}", params)
        hits = probe_rows(con, f"SELECT sha256, page_no, metric, value, unit FROM facts "
                               f"WHERE {where} LIMIT 5", params)
        return {"store": "deck_figures.facts", "filter": "sha256 of the company's decks + "
                                                        "metric LIKE terms",
                "decks": len(shas), "rows": n, "hits": hits}
    finally:
        con.close()


def probe_fts(spec_terms: list[str], limit: int = 5) -> dict:
    """Entity-free document search: the FTS5 index the query layer's dense leg falls back to.

    A ticket that names no company is still a ticket about text we may hold, so the search is
    not skipped — it is scoped by the class terms instead of by an ISIN.
    """
    if not spec_terms:
        return {"store": "intelligence_fts", "skipped": "class declares no terms"}
    con = connect_ro(DATA / "equity_intelligence.db", timeout_s=20)
    try:
        expr = " OR ".join('"%s"' % t.replace('"', "") for t in spec_terms[:3])
        rows = con.execute(
            "SELECT symbol, source_type, document_date, "
            "snippet(intelligence_fts, 5, '', '', ' … ', 18) AS hit "
            "FROM intelligence_fts WHERE intelligence_fts MATCH ? LIMIT ?",
            (expr, limit)).fetchall()
        return {"store": "intelligence_fts", "match": expr, "rows": len(rows),
                "hits": [{"symbol": r[0], "doc_type": r[1], "date": r[2], "snippet": r[3]}
                         for r in rows]}
    except Exception as exc:
        return {"store": "intelligence_fts", "match": spec_terms[:3],
                "error": f"{type(exc).__name__}: {exc}"}
    finally:
        con.close()


def probe_documents(symbol: str | None, terms: list[str], question: str) -> dict:
    """The query layer's own document search, not a second implementation of it."""
    if not symbol:
        return {"store": "lookups_docs.doc_find",
                "skipped": "no company resolved from the question"}
    if SERVER.exists():
        sys.path.insert(0, str(SERVER))
    try:
        import lookups_docs  # noqa: PLC0415 — needs SERVER on sys.path first
        query = " ".join(terms[:3]) or question
        out = lookups_docs.doc_find(symbol, query, top_k=5)
        return {"store": "lookups_docs.doc_find", "terms": query,
                "found": bool(out.get("found")), "checked": out.get("checked"),
                "rows": len(out.get("passages") or []),
                "hits": out.get("passages") or []}
    except Exception as exc:                     # a broken store must not kill the sweep
        return {"store": "lookups_docs.doc_find", "terms": " ".join(terms[:3]),
                "error": f"{type(exc).__name__}: {exc}"}


# --------------------------------------------------------------------------- #
# one case
# --------------------------------------------------------------------------- #
def retriage_case(case: dict, entities: list[tuple[str, str, str]]) -> dict:
    spec = CLASSES.get(case["class_id"], {"terms": [], "xbrl": []})
    question = case.get("question") or ""
    qterms = tokens(question)
    terms = list(dict.fromkeys([*spec["terms"], *qterms]))[:12]
    ent = resolve_entity(question, entities)

    searches = []
    if ent["isin"]:
        for fn in (probe_ar, probe_concall, probe_deck):
            searches.append(fn(ent["isin"], terms))
        searches.append(probe_xbrl(ent["isin"], spec.get("xbrl") or []))
    else:
        searches.append({"store": "structured", "skipped": "no company resolved from the question"})
    searches.append(probe_fts(spec.get("terms") or qterms))
    searches.append(probe_documents(ent["resolved"], spec.get("terms") or qterms, question))

    doc_stores = {"lookups_docs.doc_find", "intelligence_fts"}
    structured = sum(int(s.get("rows") or 0) for s in searches
                     if s.get("store") not in doc_stores)
    own_docs = sum(int(s.get("rows") or 0) for s in searches
                   if s.get("store") == "lookups_docs.doc_find")
    corpus = sum(int(s.get("rows") or 0) for s in searches
                 if s.get("store") == "intelligence_fts")
    doc_hits = own_docs
    # Three levels, kept apart on purpose.  A structured row is a held fact in the store the
    # class needs.  A passage from the company's OWN documents is candidate prose evidence.
    # A corpus match only says "this phrase exists somewhere in 2.3 M chunks" — every class
    # term does, so it is logged and explicitly not counted.
    level = ("structured" if structured else "document" if own_docs else
             "corpus" if corpus else "none")
    return {
        "case_id": case["case_id"],
        "class_id": case["class_id"],
        "verdict": case.get("verdict"),
        "question": question,
        "registry_reason": case.get("registry_reason"),
        "entity": ent,
        "search_terms": terms,
        "searches": searches,
        "structured_rows": structured,
        "own_document_hits": int(own_docs),
        "corpus_hits": int(corpus),
        "evidence_level": level,
        "candidate_real_evidence": level in {"structured", "document"},
        "review": "controller reviews this log; the ticket is NOT re-labelled here",
    }


# --------------------------------------------------------------------------- #
# self-check
# --------------------------------------------------------------------------- #
def demo() -> int:
    """The smallest thing that fails if the log logic breaks."""
    assert tokens("What is HDFC Bank's NIM in Q2?") == ["hdfc", "bank", "nim"]
    assert tokens("kya hai kitna") == []
    assert _like_terms(["a", "abc"]) == ["%abc%", "%a%"]
    case = {"case_id": "X", "class_id": "net_npa", "verdict": "b", "question": "Tata Motors ROE"}
    log = retriage_case(case, [("TATA MOTORS", "INE155A01022", "TATAMOTORS")])
    assert log["entity"]["resolved"] == "TATAMOTORS", log["entity"]
    assert {"case_id", "searches", "evidence_level", "candidate_real_evidence"} <= set(log)
    assert log["evidence_level"] in {"structured", "document", "corpus", "none"}
    assert needles("Muthoot Finance Ltd")[:2] == ["MUTHOOT FINANCE LTD", "MUTHOOT FINANCE"]
    assert "MUTHOOT" in needles("Muthoot Finance Ltd")
    assert needles("Bank of India Ltd")[:2] == ["BANK OF INDIA LTD", "BANK OF INDIA"]
    print("nid_retriage self-check PASS")
    return 0


def main(argv: list[str]) -> int:
    if "--check" in argv:
        return demo()
    triage = json.loads(TRIAGE.read_text(encoding="utf-8"))
    cases = [c for c in triage["cases"] if c.get("verdict") == "b"]
    entities = load_entities()
    OUT.mkdir(parents=True, exist_ok=True)
    for stale in OUT.glob("*.json"):
        stale.unlink()

    summary = {"question": "which proxy tickets already have held evidence?",
               "rule": triage.get("rule"), "proxy_tickets": len(cases), "by_class": {},
               "by_level": {"structured": 0, "document": 0, "corpus": 0, "none": 0},
               "cases": []}
    for i, case in enumerate(sorted(cases, key=lambda c: c["case_id"]), 1):
        log = retriage_case(case, entities)
        (OUT / f"{case['case_id']}.json").write_text(
            json.dumps(log, indent=2, default=str) + "\n", encoding="utf-8")
        summary["by_level"][log["evidence_level"]] += 1
        row = summary["by_class"].setdefault(
            case["class_id"], {"tickets": 0, "structured": 0, "document": 0,
                               "corpus": 0, "none": 0})
        row["tickets"] += 1
        row[log["evidence_level"]] += 1
        summary["cases"].append({"case_id": case["case_id"], "class_id": case["class_id"],
                                 "entity": log["entity"]["resolved"],
                                 "structured_rows": log["structured_rows"],
                                 "own_document_hits": log["own_document_hits"],
                                 "corpus_hits": log["corpus_hits"],
                                 "evidence_level": log["evidence_level"]})
        print(f"[{i:>2}/{len(cases)}] {case['case_id']} {case['class_id']:<22} "
              f"{log['entity']['resolved'] or '-':<12} "
              f"structured={log['structured_rows']:<6} own={log['own_document_hits']:<3} "
              f"corpus={log['corpus_hits']:<3} {log['evidence_level']}", flush=True)

    SUMMARY.write_text(json.dumps(summary, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"\nwrote {len(list(OUT.glob('*.json')))} logs to {OUT.name}/ and {SUMMARY.name}")
    print(f"candidate real evidence: structured {summary['by_level']['structured']}, "
          f"document {summary['by_level']['document']}, none {summary['by_level']['none']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
