"""Policy register: dated policy changes extracted from Government / RBI documents (2026-10-19, Shivam: policy change -
announced or still in the pipeline - is a core pillar of the trading policy).

Sources: pib_releases (body + minute posting time), and search-layer documents (Union / State budgets, Economic
Surveys, RBI policy / minutes / reports, PRS) rebuilt from their chunks. Long documents are cut into ~24k-character
sections. Reader: an LLM through OpenCode Go (default LongCat free, so the DeepSeek allowance stays on concalls).

policy_events (one row per policy change):
  source_kind, source_id, published_at (PIT: PIB posting minute / document publication date), title,
  policy_name, instrument (tax|customs_duty|tariff_trade|pli_incentive|subsidy|scheme|capex_sanction|procurement|
  regulation|price_control|msp|auction_allocation|monetary|licensing|other), stage (signal|consultation|draft|
  approved|announced|notified|effective|extended|withdrawn), direction_for_industry (positive|negative|mixed|neutral),
  sectors (json), companies (json), products, amount_inr_crore, old_value, new_value, unit, effective_date, end_date,
  geography, quote (verbatim), quote_ok (machine check), model, extracted_at
policy_docs: per source document: status, n_events, is_policy, tokens.

    python -m reality_engine.scripts.policy_register --source pib --limit 40
    python -m reality_engine.scripts.policy_register --source doc --doc-ids 63
"""
import argparse
import concurrent.futures as cf
import datetime as dt
import json
import re
import sqlite3
from pathlib import Path

from reality_engine.scripts import ingest_annual_reports as ar
from reality_engine.scripts.concall_pilot import call_go, parse_json

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "reality_engine/data/equity_intelligence.db"
# 12k characters per section (was 24k: answers of 50+ events took minutes, broke as JSON and blocked the run;
# sections already read at 24k keep their ids 0.. and are not re-read unless their numbering differs)
SECTION = 12000
DDL = """
CREATE TABLE IF NOT EXISTS policy_events (id INTEGER PRIMARY KEY AUTOINCREMENT, source_kind TEXT, source_id TEXT,
    section INTEGER, published_at TEXT, title TEXT, policy_name TEXT, instrument TEXT, stage TEXT,
    direction_for_industry TEXT, sectors TEXT, companies TEXT, products TEXT, amount_inr_crore REAL, old_value TEXT,
    new_value TEXT, unit TEXT, effective_date TEXT, end_date TEXT, geography TEXT, quote TEXT, quote_ok INTEGER,
    model TEXT, extracted_at TEXT);
CREATE INDEX IF NOT EXISTS idx_policy_pub ON policy_events(published_at);
CREATE TABLE IF NOT EXISTS policy_docs (source_kind TEXT, source_id TEXT, section INTEGER, status TEXT, is_policy INTEGER,
    n_events INTEGER, in_tok INTEGER, out_tok INTEGER, model TEXT, done_at TEXT, error TEXT,
    PRIMARY KEY (source_kind, source_id, section));
"""
PROMPT = """You read an Indian Government / RBI document and list every POLICY CHANGE in it that could affect listed
companies, sectors or markets: taxes and duties, tariffs and trade measures, PLI / incentives / subsidies, schemes and
missions with money, capex sanctions and project approvals, procurement, regulation and rule changes, price controls,
MSP, auctions / allocations, monetary and banking measures, licensing. Also list SIGNALS of change still in the
pipeline (consultation papers, draft rules, 'the government is considering', committee recommendations, budget
announcements to be notified later). Ignore ceremonies, greetings, visits, awareness events and statistics without a
policy change.

Return ONE JSON object only: {"is_policy": true|false, "events": [ {
 "policy_name": "short name", "instrument": "tax|customs_duty|tariff_trade|pli_incentive|subsidy|scheme|capex_sanction|procurement|regulation|price_control|msp|auction_allocation|monetary|licensing|other",
 "stage": "signal|consultation|draft|approved|announced|notified|effective|extended|withdrawn",
 "direction_for_industry": "positive|negative|mixed|neutral",
 "sectors": ["..."], "companies": ["named companies only"], "products": "goods/services affected or null",
 "amount_inr_crore": number or null, "old_value": "as written or null", "new_value": "as written or null", "unit": "%|INR crore|...|null",
 "effective_date": "YYYY-MM-DD or as written or null", "end_date": "... or null", "geography": "India|state name|...",
 "quote": "verbatim span (<= 40 words) from the document that states this change" } ] }
Rules: quote must be copied character for character; never invent values or dates; amounts in INR crore only when the
document gives them (convert lakh crore -> crore: 1 lakh crore = 100000 crore; write the original in old/new_value if
unsure). If the document is not in English, still answer in English and keep the quote in the original language.

DOCUMENT ({kind}, published {published}): {title}
{text}
"""


def norm(s):
    return " ".join(re.findall(r"\w+", (s or "").lower()))


def sources(con, kind, limit, doc_ids):
    if kind == "pib":
        q = ("SELECT 'pib', CAST(prid AS TEXT), COALESCE(posted_at, release_date), title, body FROM pib_releases "
             "WHERE body IS NOT NULL AND length(body) > 300 AND relevant=1 AND NOT EXISTS (SELECT 1 FROM policy_docs d "
             "WHERE d.source_kind='pib' AND d.source_id=CAST(prid AS TEXT) AND d.status='ok') ORDER BY prid DESC")
        rows = con.execute(q + (f" LIMIT {limit}" if limit else "")).fetchall()
        return [(k, i, p, t, b, 0) for k, i, p, t, b in rows]
    out = []
    for d in doc_ids:
        title, pub, st = con.execute("SELECT title, published_date, source_type FROM raw_documents WHERE doc_id=?", (d,)).fetchone()
        text = "\n".join(r[0] for r in con.execute("SELECT content FROM document_chunks WHERE doc_id=? ORDER BY chunk_index", (d,)))
        text = re.sub(r"\[Metadata:[^\]]*\]\n?", "", text)
        parts = [text[i:i + SECTION] for i in range(0, len(text), SECTION)]
        out += [("doc", str(d), pub, f"{st}: {title}", p, n) for n, p in enumerate(parts)]
    return out


def run_one(item, model, key, con_path):
    kind, sid, pub, title, text, section = item
    p = PROMPT.replace("{kind}", kind).replace("{published}", str(pub)).replace("{title}", title or "").replace("{text}", text)
    data, err = None, None
    for attempt in range(3):   # long answers sometimes come back as broken JSON (1 of 5 budget sections in the pilot)
        try:
            out, it, ot = call_go(model, p, key)
            data = parse_json(out)
            break
        except Exception as e:  # noqa: BLE001
            err = str(e)[:200]
    if data is None:
        return (kind, sid, section, "error", None, 0, None, None, model, dt.datetime.now().isoformat(timespec="seconds"), err), []
    nt = norm(text)
    rows = []
    for ev in data.get("events") or []:
        if not isinstance(ev, dict):
            continue
        q = ev.get("quote") or ""
        amt = ev.get("amount_inr_crore")
        try:
            amt = float(amt) if amt not in (None, "") else None
        except (TypeError, ValueError):
            amt = None
        def sc(k):   # scalar field; the model sometimes answers a list (products as a list crashed the run 2026-10-19)
            v = ev.get(k)
            return json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v
        if not isinstance(q, str):
            q = json.dumps(q, ensure_ascii=False)
        rows.append((kind, sid, section, pub, title, sc("policy_name"), sc("instrument"), sc("stage"),
                     sc("direction_for_industry"), json.dumps(ev.get("sectors") or [], ensure_ascii=False),
                     json.dumps(ev.get("companies") or [], ensure_ascii=False), sc("products"), amt,
                     sc("old_value"), sc("new_value"), sc("unit"), sc("effective_date"), sc("end_date"),
                     sc("geography"), q, int(bool(q) and norm(q)[:120] in nt), model,
                     dt.datetime.now().isoformat(timespec="seconds")))
    doc = (kind, sid, section, "ok", int(bool(data.get("is_policy"))), len(rows), it, ot, model,
           dt.datetime.now().isoformat(timespec="seconds"), None)
    return doc, rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=["pib", "doc"], default="pib")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--doc-ids", default="")
    ap.add_argument("--doc-types", default="", help="raw_documents.source_type LIKE patterns, comma-separated "
                    "(SQL LIKE patterns, e.g. Union_Budget,Economic_Survey; use %% as wildcard); sections already done are skipped")
    ap.add_argument("--model", default="longcat-2.5-preview-free")
    ap.add_argument("--key", default="OPENCODE_GO_API_KEY")
    ap.add_argument("--workers", type=int, default=8)
    a = ap.parse_args()
    con = sqlite3.connect(DB, timeout=600)
    con.executescript(DDL)
    ids = [int(x) for x in a.doc_ids.split(",") if x]
    for pat in [x for x in a.doc_types.split(",") if x]:
        ids += [r[0] for r in con.execute("SELECT doc_id FROM raw_documents WHERE source_type LIKE ?", (pat,))]
    items = sources(con, a.source, a.limit, sorted(set(ids)))
    done = {(k, i, s) for k, i, s in con.execute("SELECT source_kind, source_id, section FROM policy_docs WHERE status='ok'")}
    items = [it for it in items if (it[0], it[1], it[5]) not in done]
    print(f"sections to read: {len(items)}", flush=True)
    key = ar.user_env()[a.key]
    n_ev = 0
    with cf.ThreadPoolExecutor(a.workers) as ex:
        futs = [ex.submit(run_one, it, a.model, key, DB) for it in items]
        for fut in cf.as_completed(futs):   # save each section as soon as it is read (map() waited in queue order)
            doc, rows = fut.result()
            with con:
                con.execute("DELETE FROM policy_events WHERE source_kind=? AND source_id=? AND section=?", doc[:3])
                con.executemany("INSERT INTO policy_events (source_kind, source_id, section, published_at, title, "
                                "policy_name, instrument, stage, direction_for_industry, sectors, companies, products, "
                                "amount_inr_crore, old_value, new_value, unit, effective_date, end_date, geography, quote, "
                                "quote_ok, model, extracted_at) VALUES (" + ",".join("?" * 23) + ")", rows)
                con.execute("INSERT OR REPLACE INTO policy_docs VALUES (?,?,?,?,?,?,?,?,?,?,?)", doc)
            n_ev += len(rows)
            print(doc[0], doc[1], doc[2], doc[3], "events", len(rows), flush=True)
    print("events", n_ev)


if __name__ == "__main__":
    main()
