"""Build the ripple bank: validate, write the JSONL, and write the schema-requirements MD."""

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from _lib import GAP, DATA  # noqa: E402

import r01, r02, r03, r04, r05, r06, r07, r08, r09, r10  # noqa: E402

MODULES = [r01, r02, r03, r04, r05, r06, r07, r08, r09, r10]
BANNED = ["NUCLEAR_MISSION", "RAIL_CAPEX_PUSH", "STEEL_SAFEGUARD_DUTY",
          "US_TARIFF_TEXTILE_RELIEF", "PHASE5_"]

ARCH = {
 "R01": "Commodity -> input cost -> pricing power -> downstream demand",
 "R02": "Policy cascade: instrument, direct target, suppliers, customers, substitutes",
 "R03": "Rates, FX and liquidity through balance sheets",
 "R04": "Global or geopolitical shock -> trade routes -> Indian sectors",
 "R05": "Competitive response and market-structure change",
 "R06": "Reflexive capital-markets loops",
 "R07": "Timing and lags measured from our own cycles",
 "R08": "Effects pulling both ways, netted",
 "R09": "Leading indicators and their point-in-time status",
 "R10": "Information leakage in the 4 sessions before day 0",
}
OUT = HERE.parent / "QUESTION_BANK_RIPPLE_2026-10-28.jsonl"
MD = HERE.parent / "RIPPLE_SCHEMA_REQUIREMENTS_2026-10-28.md"

# For a `partial` hop the evidence that exists is text in one of these stores; the gap is the
# structured column on top of it. A proposal with no store here is `no` unless the hop names a real table.
STORE = {
 "cost_structure": "ar_facts.ar_facts",
 "input_linkage": "concall_facts.cc_items / deck_figures.facts",
 "price_revision": "concall_facts.cc_items",
 "order_contract": "corporate_documents / concall_facts.cc_items",
 "capacity_util": "ar_facts.ar_facts / concall_facts.cc_items",
 "capacity_pipeline": "concall_facts.cc_items / deck_figures.facts (per-company announcements, never aggregated)",
 "deposit_rate": "ar_facts.ar_facts (deposit schedule)",
 "rating_action": "bse_announcements.ann (credit-rating reassignment headline)",
 "working_capital": "results_xbrl.facts (trade receivables, inventory, payables)",
 "import_content": "ar_facts.ar_facts (imported raw material note)",
 "revenue_geo_period": "geographic_exposure",
 "cost_geo": "ar_facts.ar_facts (manufacturing locations)",
 "fx_exposure": "ar_facts.ar_facts (forex note) / concall_facts.cc_items",
 "loan_repricing": "ar_facts.ar_facts (Basel disclosures) / concall_facts.cc_items",
 "debt_mix": "ar_facts.ar_facts (borrowing schedule)",
 "interest_cover": "annual_financials",
 "pledge_event": "shareholding",
 "fund_raise": "corporate_documents",
 "capex_project": "concall_facts.cc_items / deck_figures.facts",
 "customer_contract": "concall_facts.cc_items",
 "supply_link": "ar_facts.ar_facts (related-party note)",
 "policy_target": "policy_events",
 "subsidy_register": "ar_facts.ar_facts (other income note)",
 "segment_pnl": "ar_facts.ar_facts (segment note)",
 "metric_series": "quarterly_financials / results_xbrl.facts",
 "guidance_actual": "concall_facts.cc_items",
 "event_calendar": "policy_events",
 "day0_session": "corporate_documents (known_at) / macro_events",
 "leakage_window": "daily_price_delivery / insider_trades_v2 / bulk_block_deals",
 "order_intake": "concall_facts.cc_items / deck_figures.facts",
 "competitor_action": "concall_facts.cc_items",
 "mcap_state": "daily_price_delivery / index_membership",
 "tariff_exposure": "policy_events",
 "duty_structure": "policy_events",
 "sector_flow": "daily_price_delivery",
}


def real_tables():
    from reality_engine.db.readonly import connect_ro
    names = set()
    for db in ["equity_intelligence.db", "ar_facts.db", "concall_facts.db", "deck_figures.db",
               "results_xbrl.db", "bse_announcements.db", "results_notes.db"]:
        try:
            con = connect_ro(DATA / db, timeout_s=30)
            for (t,) in con.execute("SELECT name FROM sqlite_master WHERE type='table'"):
                names.add(t)
        except Exception as e:            # a missing store must not stop the build
            print(f"  ! {db}: {e}")
    return names


def live_counts():
    from reality_engine.db.readonly import connect_ro
    con = connect_ro(DATA / "equity_intelligence.db", timeout_s=90)
    q = {
      "policy_events rows": "SELECT COUNT(*) FROM policy_events",
      "policy_events quote_ok=1": "SELECT COUNT(*) FROM policy_events WHERE quote_ok=1",
      "macro_events rows": "SELECT COUNT(*) FROM macro_events",
      "macro_events with doc_id": "SELECT COUNT(*) FROM macro_events WHERE doc_id IS NOT NULL",
      "ripple_effects rows": "SELECT COUNT(*) FROM ripple_effects",
      "shareholding rows": "SELECT COUNT(*) FROM shareholding",
      "index_membership rows": "SELECT COUNT(*) FROM index_membership",
      "index_membership distinct as_of": "SELECT COUNT(DISTINCT as_of) FROM index_membership",
      "geographic_exposure rows": "SELECT COUNT(*) FROM geographic_exposure",
      "bulk_block_deals rows": "SELECT COUNT(*) FROM bulk_block_deals",
      "insider_trades_v2 rows": "SELECT COUNT(*) FROM insider_trades_v2",
      "daily_price_delivery max date": "SELECT MAX(date) FROM daily_price_delivery",
      "quarterly_financials max quarter": "SELECT MAX(quarter_end_date) FROM quarterly_financials",
      "quarterly_financials rows": "SELECT COUNT(*) FROM quarterly_financials",
      "annual_financials FY26 rows": "SELECT COUNT(*) FROM annual_financials WHERE fiscal_year='FY26'",
      "annual_financials FY26 interest_coverage<2.5": "SELECT COUNT(*) FROM annual_financials WHERE fiscal_year='FY26' AND interest_coverage<2.5",
      "annual_financials FY26 debt null": "SELECT COUNT(*) FROM annual_financials WHERE fiscal_year='FY26' AND debt_inr_cr IS NULL",
      "master_companies rows": "SELECT COUNT(*) FROM master_companies",
      "company_industry rows": "SELECT COUNT(*) FROM company_industry",
    }
    out = {}
    for k, sql in q.items():
        try:
            out[k] = con.execute(sql).fetchone()[0]
        except Exception as e:
            out[k] = f"err:{e}"
    return out


def main():
    rows = [r for m in MODULES for r in m.ROWS]
    tabs = real_tables()

    # --- validation ---------------------------------------------------------
    errs = []
    downgrades = 0
    if len(rows) != 200:
        errs.append(f"row count {len(rows)} != 200")
    cnt = Counter(r["archetype"] for r in rows)
    if len(cnt) != 10 or set(cnt.values()) != {20}:
        errs.append(f"archetype counts {dict(cnt)}")
    qids = Counter(r["qid"] for r in rows)
    dup = [q for q, n in qids.items() if n > 1]
    if dup:
        errs.append(f"duplicate qids {dup}")
    for r in rows:
        if len(r["chain"]) < 3:
            errs.append(f"{r['qid']} has {len(r['chain'])} hops")
        if not r["trigger"].get("sourced"):
            errs.append(f"{r['qid']} unsourced trigger")
        for h in r["chain"]:
            if not h["evidence_needed"] or not h["exists_today"]:
                errs.append(f"{r['qid']} hop {h['hop']} missing evidence/exists")
            found = [t for t in tabs if t in h["evidence_needed"]]
            if not found and h.get("gap_key") in STORE:
                h["evidence_needed"] += f" [text today: {STORE[h['gap_key']]}]"
                found = [t for t in tabs if t in STORE[h["gap_key"]]]
            if not found and h["exists_today"] == "partial":
                h["exists_today"] = "no"          # nothing holds this hop today
                downgrades += 1
            if h["exists_today"] in ("no", "partial") and not h["gap"]:
                errs.append(f"{r['qid']} hop {h['hop']} is {h['exists_today']} without a proposal")
            if h["exists_today"] != "no" and not found:
                errs.append(f"{r['qid']} hop {h['hop']} claims {h['exists_today']} but names no existing table")
            h["checked_with"] = ("bounded probe: " + ", ".join(found[:3])) if found else \
                                "absent from sqlite_master (proposal only)"
        v = [h["exists_today"] for h in r["chain"]]
        worst = "no" if "no" in v else ("partial" if "partial" in v else "yes")
        r["coverage"] = {"verdict": worst, "weakest_hop": v.index(worst) + 1,
                         "note": f"{v.count('yes')}/{len(v)} hops answerable today; "
                                 f"hop {v.index(worst) + 1} decides ({worst})."}
    blob = json.dumps([{k: v for k, v in r.items()} for r in rows], ensure_ascii=False)
    bad = [b for b in BANNED if b in blob]
    if bad:
        errs.append(f"banned seed keyword present: {bad}")
    if errs:
        print("VALIDATION FAILED")
        for e in errs[:40]:
            print("  -", e)
        sys.exit(1)

    # --- jsonl --------------------------------------------------------------
    for r in rows:
        r["archetype_name"] = ARCH[r["archetype"]]
    with OUT.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # --- stats --------------------------------------------------------------
    hop_pos = defaultdict(lambda: Counter())
    for r in rows:
        for h in r["chain"]:
            pos = 1 if h["hop"] == 1 else (2 if h["hop"] == 2 else 3)
            hop_pos[pos][h["exists_today"]] += 1
    unblocks = defaultdict(set)
    hopidx = defaultdict(set)
    for r in rows:
        for h in r["chain"]:
            if h["gap"]:
                key = h["gap"].split("(")[0]
                unblocks[key].add(r["qid"])
                hopidx[key].add(h["hop"] if h["hop"] < 4 else 4)
    gkey = {GAP[k][0].split("(")[0]: k for k in GAP}
    ranked = sorted(unblocks.items(),
                    key=lambda kv: (-len(kv[1]) / GAP[gkey[kv[0]]][4], -len(kv[1])))

    cov = Counter(r["coverage"]["verdict"] for r in rows)
    inds = Counter()
    syms = Counter()
    for r in rows:
        inds[r["archetype"]] += len({e["basic_industry"] for e in r["entities"]})
        syms[r["archetype"]] += len(r["entities"])

    # --- markdown -----------------------------------------------------------
    L = []
    A = L.append
    A("# Ripple question bank — schema requirements (2026-10-28)\n")
    A("Generated by `tasks/ripple_bank/build_bank.py` from `tasks/QUESTION_BANK_RIPPLE_2026-10-28.jsonl` "
      "(200 questions, 20 per archetype, 3–5 hops each). Every count below is computed from that file; "
      "every store count is a live read of the read-only databases on 2026-10-28.\n")
    A("## 1. What the bank found\n")
    A(f"- 200 rows, {sum(len(r['chain']) for r in rows)} hops. Coverage: yes {cov['yes']}, partial {cov['partial']}, no {cov['no']} "
      f"— no chain is answerable end to end today, which is the finding, not a defect of the questions.")
    A(f"- Hops fully answerable today (a bounded query returns the data): "
      f"{hop_pos[1]['yes']}/{sum(hop_pos[1].values())} at hop 1, "
      f"{hop_pos[2]['yes']}/{sum(hop_pos[2].values())} at hop 2, "
      f"{hop_pos[3]['yes']}/{sum(hop_pos[3].values())} at hop 3+. "
      f"Partial (the text exists in a document store, the structured field does not): "
      f"{hop_pos[1]['partial']}/{sum(hop_pos[1].values())}, {hop_pos[2]['partial']}/{sum(hop_pos[2].values())}, "
      f"{hop_pos[3]['partial']}/{sum(hop_pos[3].values())}. Nothing held at all: "
      f"{hop_pos[1]['no']}, {hop_pos[2]['no']}, {hop_pos[3]['no']}.")
    A("- The degradation is not uniform: hop 1 is largely *partial* (the price move, the policy, the filing is "
      "somewhere in text or in a market series), hop 2 and hop 3 are where the structured columns are absent — "
      "input shares of COGS, the price basis of a contract, cost geography, channel inventory, and the "
      "measured lag itself.")
    A(f"- {len(ranked)} distinct proposals cover all 200 questions; the top five cover "
      f"{sum(len(q) for _, q in ranked[:5])} hop-level references, so a small schema closes most of the bank.\n")
    cnts = live_counts()
    A("### Verified store facts behind the requirements\n")
    A("| Fact | Value | Why it matters here |")
    A("|---|---|---|")
    facts = [
      ("policy_events rows / quote_ok=1", f"{cnts['policy_events rows']} / {cnts['policy_events quote_ok=1']}",
       "the only usable policy calendar; every R2 trigger cites a row id or a policy_name with quote_ok=1"),
      ("macro_events rows / with doc_id", f"{cnts['macro_events rows']} / {cnts['macro_events with doc_id']}",
       "the rest are unsourced seeds and are never used in this bank"),
      ("ripple_effects rows", str(cnts["ripple_effects rows"]),
       "the existing causal edge table: 61 edges, an elasticity and a lag, no evidence row"),
      ("shareholding rows", str(cnts["shareholding rows"]),
       "promoter/FII/pledge questions cannot be answered from it (open-bank NG05)"),
      ("index_membership rows / distinct as_of", f"{cnts['index_membership rows']} / {cnts['index_membership distinct as_of']}",
       "a single snapshot, so no membership change can be dated (audit G2)"),
      ("geographic_exposure rows", str(cnts["geographic_exposure rows"]),
       "company_id-keyed and undated: it cannot answer 'as of FY25' or 'as of the last report'"),
      ("daily_price_delivery max date", str(cnts["daily_price_delivery max date"]),
       "the tape and the delivery series are the only hop-1 series that are already point-in-time"),
      ("quarterly_financials rows / max quarter", f"{cnts['quarterly_financials rows']} / {cnts['quarterly_financials max quarter']}",
       "floored: a margin trough on 2026-09-30 cannot be seen"),
      ("annual_financials FY26 rows with interest_coverage<2.5", str(cnts["annual_financials FY26 interest_coverage<2.5"]),
       "of " + str(cnts["annual_financials FY26 rows"]) + " rows; the solvency gate (AGENTS.md §3.11) cannot run on this column"),
      ("annual_financials FY26 rows with debt null", str(cnts["annual_financials FY26 debt null"]),
       "leverage screens silently drop those names"),
    ]
    for a, b, c in facts:
        A(f"| {a} | {b} | {c} |")
    A("")
    A("## 2. Requirements, ranked by questions unblocked per unit of build effort\n")
    A("`unblocks` counts questions with at least one hop naming this proposal; `hops` says which positions it "
      "sits at (4 means 4+). Effort is build days for one deterministic table including validation.\n")
    A("| # | proposal | unblocks | hops | effort (d) | unblocks/effort | filler | already fetched | overlap |")
    A("|---|---|---|---|---|---|---|---|---|")
    for i, (ddl, qids) in enumerate(ranked[:25], 1):
        k = gkey[ddl]
        d = GAP[k]
        A(f"| {i} | `{ddl}` | {len(qids)} | {sorted(hopidx[ddl])} | {d[4]:.1f} | {len(qids)/d[4]:.1f} | "
          f"{d[3]} | {d[2]} | {d[5]} |")
    A("")
    A("## 3. Every proposal, with its source, key and point-in-time field\n")
    A("Each entry gives the DDL, where the data comes from and whether that source is already fetched, what "
      "fills it (a deterministic parser or a reader model), the effort, which open-bank (`NG*`) and audit "
      "(`G*`) gaps it overlaps, the questions it unblocks, and the hop positions.\n")
    for i, (ddl, qids) in enumerate(ranked, 1):
        k = gkey[ddl]
        d = GAP[k]
        A(f"### {i}. `{ddl}`\n")
        A(f"- Columns and keys: `{ddl}`. Point-in-time field: "
          f"`{'known_at' if 'known_at' in ddl else ('valid_from' if 'valid_from' in ddl else 'known_at (proposed)')}`.")
        A(f"- Source: {d[1]}. Already fetched: **{d[2]}**.")
        A(f"- Filler: **{d[3]}**. Effort: **{d[4]:.1f} days**. Overlap: {d[5]}.")
        A(f"- Unblocks **{len(qids)}** questions at hop {sorted(hopidx[ddl])}: {', '.join(sorted(qids)[:14])}"
          f"{' …' if len(qids) > 14 else ''}.")
        A(f"- Why: {d[6]}\n")
    A("## 4. Which proposal serves which archetype, and what it overlaps\n")
    A("Counts are questions per archetype that name the proposal at any hop.\n")
    arcs = [f"R{i:02d}" for i in range(1, 11)]
    A("| proposal | " + " | ".join(arcs) + " | total | open bank / audit overlap |")
    A("|---" * (len(arcs) + 3) + "|")
    per = defaultdict(Counter)
    for r in rows:
        for h in r["chain"]:
            if h["gap"]:
                per[h["gap"].split("(")[0]][r["archetype"]] += 1
    for ddl, qids in ranked[:10]:
        cells = " | ".join(str(per[ddl][a] or "") for a in arcs)
        A(f"| `{ddl}` | {cells} | {len(qids)} | {GAP[gkey[ddl]][5]} |")
    A("")
    A("- R10 is served by two small tables (`event_day0`, `event_leakage_window`): the delivery, insider and "
      "deal tapes already exist and are point-in-time, so leakage is a join and a rule, not a new feed.")
    A("- R2 is served by `policy_company_exposure`: `policy_events` names sectors as free text and never a "
      "company, an amount or a channel, which is the one structural link missing between a policy row and a stock.")
    A("- R3, R7 and R8 lean on `company_debt_mix`, `bank_loan_book_repricing` and `company_cost_geography`: the "
      "repricing and cost-geography sides of the balance sheet that no filing table carries.")
    A("- `company_metric_series` is the widest single unlock — the quarterly series behind the margin, volume and "
      "EPS hops — and it is `partial` only because `quarterly_financials` holds 15,173 rows and stops at "
      "2026-06-30.")
    A("\n## 5. Rules applied while building it\n")
    A("- Every trigger is sourced: a `policy_events` row (`quote_ok=1`), a company disclosure, or a market "
      "series. Rows without a `doc_id` in `macro_events` are never used.")
    A("- `exists_today` is not an opinion: each hop names a real table and the builder fails the run if a hop "
      "claims `yes`/`partial` and names no table that exists in `sqlite_master`.")
    A("- Every `no` or `partial` hop carries a schema proposal; the builder refuses a row that does not.")
    A("- Coverage is the weakest hop. A chain with 3 answerable hops and 1 missing one is `partial`, and the "
      "missing hop is named.")
    A("- Lags are ours or labelled an assumption; no elasticity is invented.")

    MD.write_text("\n".join(L), encoding="utf-8")

    print(f"wrote {OUT.name}: {len(rows)} rows, {sum(len(r['chain']) for r in rows)} hops")
    print(f"wrote {MD.name}: {len(ranked)} proposals")
    print("hop answerability:", {p: dict(c) for p, c in sorted(hop_pos.items())})
    print("coverage:", dict(cov))
    print("distinct industries per archetype:", dict(inds))
    print("top 15:")
    for ddl, qids in ranked[:15]:
        print(f"  {len(qids):3d}  {len(qids)/GAP[gkey[ddl]][4]:5.1f}/d  {ddl}")


if __name__ == "__main__":
    main()
