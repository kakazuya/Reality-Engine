"""Shared machinery for the ripple question bank.

Every row is authored in r01..r10 as R(...)/H(...) literals. This module resolves the
named symbols against master_companies (read-only), expands the gap keys to full schema
proposals, enforces the acceptance rules and computes coverage as the weakest hop.
"""

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

DATA = Path(r"C:\Users\warri\Downloads\Info_Diffusion_Model\reality_engine\data")

# --- schema proposals -----------------------------------------------------------
# key -> (ddl, source, fetched, filler, effort_days, overlap, note)
# effort_days is build effort for one deterministic table incl. validation.
# overlap: open-bank NG ids and audit G ids.
GAP = {
 "cost_structure": (
   "company_cost_structure(isin, period, input_key, share_of_cogs_pct, basis, source_doc, known_at)",
   "AR note on raw material consumption + segment note", "partial", "deterministic+reader", 3.0, "NG10 / G11",
   "Input mix as a share of COGS per company-period. ar_facts holds the raw-material line by category but never as a share of COGS."),
 "pass_through": (
   "pass_through_history(isin, shock_series, shock_start, shock_pct, margin_trough_period, margin_recovery_period, lag_quarters, source_doc, known_at)",
   "derived from quarterly results + the dated input series", "no", "deterministic", 3.0, "new / G12",
   "The measured lag: regress the margin trough on the input shock across past cycles. Cannot exist before the input series exists."),
 "commodity_series": (
   "commodity_price_daily(series_key, date, value, unit, currency, source, known_at)",
   "external: LME/MCX/crude/coal/rubber/cotton/steel HRC series", "no", "deterministic", 4.0, "NG11 / G12",
   "No dated commodity table exists in equity_intelligence.db; processing/factor_spine.py holds code, not a queryable series."),
 "price_revision": (
   "company_price_revision(isin, product, effective_date, pct_change, basis, source_doc, known_at)",
   "concall/deck/AR price-hike statements", "partial", "reader", 3.0, "article-level, open bank NG29",
   "A price hike is announced in several calls in several words; without this you cannot date the hike or size it."),
 "order_contract": (
   "order_book_contract(isin, contract_id, customer_isin, value_inr_cr, price_basis, escalation_clause, award_date, cod_date, source_doc, known_at)",
   "concall order-book tables, deck annexures, exchange order-win filings", "partial", "reader", 5.0, "NG15/NG25",
   "Order book value is quoted as one number; fixed-versus-indexed and escalation clauses are the part that decides who eats an input shock."),
 "capacity_util": (
   "company_capacity_utilisation(isin, period, product, unit, installed, produced, sold, source_doc, known_at)",
   "AR capacity note + concall utilisation statements", "partial", "reader", 4.0, "NG12",
   "Capacity is quoted in prose ('~85% utilised'); the series does not exist."),
 "capacity_pipeline": (
   "industry_capacity_pipeline(industry, project_id, sponsor_isin, product, capacity, unit, announced_date, cod_date, status, source_doc, known_at)",
   "concall/deck capex announcements + PIB/state single-window approvals", "no", "reader", 4.0, "NG14/NG22",
   "Announced industry capacity is scattered across calls; nothing aggregates it, so a glut cannot be seen forming."),
 "working_capital": (
   "company_working_capital(isin, period, inventory_days, receivable_days, payable_days, cash_cycle_days, net_wc_inr, source_doc, known_at)",
   "XBRL trade receivables/inventory/payables + AR schedule", "partial", "deterministic", 2.0, "G11",
   "The XBRL facts exist and are unmapped; annual_financials holds only OCF, never days."),
 "import_content": (
   "company_import_content(isin, period, input_key, import_share_pct, fx_hedge_pct, source_doc, known_at)",
   "AR note (imported vs indigenous raw material), concall FX hedging comment", "partial", "reader", 3.0, "NG10",
   "ARs print 'imported raw material' as a rupee figure in the notes; it is not extracted and not linked to FX."),
 "revenue_geo_period": (
   "company_revenue_geography(isin, period, country, revenue_pct, basis, source_doc, known_at)",
   "segment note (geographical) + deck", "partial", "deterministic", 1.5, "G11",
   "geographic_exposure exists (3,568 rows, revenue_share_pct filled) but is company_id-keyed, undated and single-snapshot, so it cannot answer 'as of FY25'."),
 "cost_geo": (
   "company_cost_geography(isin, period, country, cogs_pct, source_doc, known_at)",
   "AR note on manufacturing locations, deck supply-chain slide", "no", "reader", 3.0, "new / NG10",
   "The debit side of the FX question. Never disclosed as a table; only assets and revenue are given."),
 "fx_exposure": (
   "company_fx_exposure(isin, period, currency, revenue_inr_cr, cost_inr_cr, net_open_inr_cr, hedge_pct, source_doc, known_at)",
   "AR FX note / hedging disclosure, concall hedging comment", "partial", "reader", 3.0, "NG10",
   "Revenue by geography is not cost by geography; netting the two needs both sides."),
 "loan_repricing": (
   "bank_loan_book_repricing(isin, as_of, repo_linked_pct, eblr_pct, mclr_pct, fixed_pct, source_doc, known_at)",
   "AR Basel/Pillar 3 disclosures, concall NIM walk", "partial", "reader", 4.0, "new",
   "Deposit-vs-loan repricing asymmetry is the whole NIM question; no table carries the loan-book repricing split."),
 "deposit_rate": (
   "bank_deposit_rate(isin, as_of, product, rate_pct, share_pct, source_doc, known_at)",
   "AR deposit schedule, quarterly deck", "partial", "reader", 3.0, "new",
   "Term-deposit card rates are published but not harvested per bank per quarter."),
 "debt_mix": (
   "company_debt_mix(isin, as_of, instrument, share_pct, rate_pct, maturity_months, secured, source_doc, known_at)",
   "AR borrowing schedule, rating rationale", "partial", "deterministic+reader", 3.0, "new",
   "annual_financials gives total debt and one blended cover; it cannot say how much reprices next quarter."),
 "interest_cover": (
   "company_interest_cover(isin, period, ebit_inr_cr, interest_expense_inr_cr, cover_x, fx_loss_excluded, source_doc, known_at)",
   "XBRL finance cost + P&L, computed not copied", "no", "deterministic", 1.5, "new (solvency gate)",
   "annual_financials.interest_coverage has 0 rows below 2.5x across 3,245 FY26 rows, so the stored ratio cannot rank solvency."),
 "rating_action": (
   "rating_action(isin, agency, action_date, rating, outlook, action, source_doc, known_at)",
   "exchange filings + agency press releases", "no", "reader", 3.0, "NG08",
   "Rating actions arrive as PDF attachments; the attachment text is not extracted (NG01)."),
 "tariff_exposure": (
   "tariff_exposure(isin, partner_country, hs_code, tariff_pct, effective_date, revenue_pct, source_doc, known_at)",
   "US/EU customs schedules + company export disclosure", "no", "deterministic+reader", 5.0, "NG10 / G10",
   "policy_events carries the rate as text ('50% since August 2025'); nothing maps a tariff to a company's product line and revenue share."),
 "freight_series": (
   "freight_rate_daily(route, date, rate_usd, unit, source, known_at)",
   "external: container/Baltic/WCI indices", "no", "deterministic", 3.0, "NG11 / G12",
   "No freight series is held, so 'freight up' cannot be dated or sized."),
 "transit_days": (
   "shipment_transit(route, week, transit_days, source, known_at)",
   "external: carrier schedules / port authority", "no", "deterministic", 3.0, "NG11",
   "Transit time is the hop that turns a route shock into inventory days; it is not held."),
 "pledge_event": (
   "promoter_pledge_event(isin, event_date, shares_pledged, pct_of_promoter, pct_of_equity, pledgee, release_date, source_doc, known_at)",
   "shareholding pattern (Reg-31) + exchange pledge disclosures", "partial", "deterministic", 2.0, "NG05/NG07",
   "shareholding holds 40 rows and pledge events carry no quantity; percentage exists only as a point-in-time cell."),
 "fund_raise": (
   "fund_raise(isin, instrument, announce_date, issue_date, size_inr_cr, price_inr, dilution_pct, objects_json, source_doc, known_at)",
   "board outcome + EGM notice + placement document", "no", "reader", 3.0, "NG09",
   "QIP/OFS/rights are in announcements as headline text; the objects of the issue are in the annexure nobody extracts."),
 "fund_use": (
   "fund_utilisation(isin, fund_raise_id, period, objects_head, deployed_inr_cr, source_doc, known_at)",
   "quarterly monitoring report / annual-progress annexure", "no", "deterministic+reader", 3.0, "NG09",
   "The 'use of proceeds so far' table is filed quarterly and never parsed, so raised money cannot be tied to capex."),
 "capex_project": (
   "capex_project(isin, project_id, product, capacity, unit, capex_inr_cr, announced_date, cod_planned, cod_actual, source_doc, known_at)",
   "concall capacity statements + deck + AR MD&A", "partial", "reader", 4.0, "NG12/NG14",
   "Commissioning dates are stated in prose and restated across calls; slippage needs the dated statements kept, not the last one."),
 "supply_link": (
   "supply_link(isin_supplier, isin_buyer, product, supplier_revenue_share_pct, buyer_cogs_share_pct, source_doc, known_at)",
   "AR related-party note + concall named suppliers", "partial", "reader", 5.0, "NG22",
   "ripple_effects holds 61 edges with an elasticity and no evidence row; a weighted listed-to-listed edge table does not exist."),
 "policy_target": (
   "policy_company_exposure(policy_id, isin, channel, direction, revenue_pct, cost_pct, source_doc, known_at)",
   "PIB/budget/RBI text + the company's own disclosure of the scheme", "no", "reader", 5.0, "G10",
   "policy_events names sectors as free text ('Textiles & Apparel'); it never names a company, an amount or a channel."),
 "subsidy_register": (
   "subsidy_register(policy_id, isin, period, amount_inr_cr, stage, clawback, source_doc, known_at)",
   "PLI/scheme disbursement releases, company AR other income note", "no", "deterministic+reader", 4.0, "NG26/G10",
   "Incentive receipt is inside 'other income'; the scheme year and clawback terms are not structured."),
 "sector_flow": (
   "sector_flow_daily(date, sector, fii_inr_cr, dii_inr_cr, source, known_at)",
   "derived from FII/DII daily + holdings; sector attribution from the deal tape", "partial", "deterministic", 3.0, "NG18",
   "fii_dii_cash is market-wide only; no sector or stock split exists."),
 "segment_pnl": (
   "company_segment_pnl(isin, period, segment, revenue_inr_cr, ebit_inr_cr, source_doc, known_at)",
   "XBRL segment contexts + AR segment note", "partial", "deterministic", 2.5, "G11",
   "Segment contexts in XBRL are unmapped, which is why a segment number cannot be read for most filings."),
 "metric_series": (
   "company_metric_series(isin, metric_key, period_end, value, unit, source, known_at)",
   "XBRL + results notes, full universe", "partial", "deterministic", 2.0, "G9/G11",
   "quarterly_financials holds 15,173 rows against 45,517 FY25+ XBRL filings and stops at 2026-06-30; a hop on a margin trough needs the full series."),
 "guidance_actual": (
   "guidance_vs_actual(isin, metric_key, period, guided_low, guided_high, stated_on, actual, source_doc, known_at)",
   "concall guidance + the later reported number", "no", "reader", 4.0, "NG24",
   "concall_facts stores guidance as text with a period; it is never joined to the reported figure."),
 "duty_structure": (
   "import_duty_structure(hs_code, date, bcd_pct, safeguard_pct, source, known_at)",
   "customs notifications / CBIC", "no", "deterministic", 3.0, "G10",
   "Duty changes sit in CBIC notifications as text; policy_events has the headline, not the HS line."),
 "event_calendar": (
   "event_calendar(event_id, kind, title, event_date, known_at, source_doc)",
   "policy_events + PIB + exchange + external geopolitical record", "partial", "deterministic", 2.0, "NG21",
   "policy_events is a good calendar for RBI/budget releases; geopolitical and commodity shocks have no sourced row anywhere."),
 "day0_session": (
   "event_day0(event_id, isin, known_at, day0_session, timing_bucket, rule)",
   "known_at from every store, mapped to the trading calendar", "partial", "deterministic", 1.0, "NG27",
   "The 3:30/4-session rule is a decision (NEXT_SESSIONS_PLAN 2026-10-27) but no table applies it."),
 "leakage_window": (
   "event_leakage_window(event_id, isin, session, sessions_before_day0, delivery_pct, delivery_spike_ratio, price_move_pct, actor_bucket)",
   "daily_price_delivery + insider_trades_v2 + bulk_block_deals", "partial", "deterministic", 1.5, "NG28",
   "The inputs exist and are joinable; nothing normalises them into a pre-day-0 window per event."),
 "rainfall": (
   "rainfall_daily(state, district, date, rainfall_mm, departure_pct, source, known_at)",
   "external: IMD district rainfall", "no", "deterministic", 3.0, "NG11 / G12",
   "No weather series is held, so a monsoon-deficit chain has no first hop."),
 "rural_wage": (
   "rural_wage_series(state, month, mgnregs_person_days, avg_wage_inr, source, known_at)",
   "MGNREGA MIS + labour bureau", "no", "deterministic", 3.0, "NG11",
   "Rural income is the hop between a scheme allocation and two-wheeler volume; it is not held."),
 "order_intake": (
   "order_intake(isin, period, order_inflow_inr_cr, order_book_inr_cr, book_to_bill, source_doc, known_at)",
   "concall order-book statement + deck", "partial", "reader", 4.0, "NG15",
   "Order book is quoted as a single number in some calls and omitted in others; there is no per-quarter series."),
 "competitor_action": (
   "competitor_action(isin_actor, isin_target, action, action_date, metric_pct, source_doc, known_at)",
   "concall price-cut statements, deck, exchange filing", "no", "reader", 3.0, "new",
   "A competitor's price cut is only ever described in prose; nothing dates it or links actor to target."),
 "share_shift": (
   "market_share_shift(product, period, isin_gainer, isin_loser, share_change_pct, source_doc, known_at)",
   "both companies' disclosed volumes + industry body data", "no", "reader", 4.0, "new",
   "Share shift needs two companies' volumes on one product line; segment P&L and volume series are both missing."),
 "mcap_state": (
   "company_state_daily(isin, date, close, shares_out, market_cap_inr_cr, mcap_bucket, index_json, known_at)",
   "XBRL paid-up/face x adj_factor_cum + index circulars", "partial", "deterministic", 3.0, "G1/G2",
   "Price exists daily; shares outstanding and bucket do not, and index_membership is one 300-row snapshot."),
}

# --- formula strings for rubric text --------------------------------------------
DIR = {"up": "up", "down": "down", "mixed": "mixed"}

GAP["fund_utilisation"] = GAP["fund_use"]   # one proposal, two names used while authoring


def T(kind, ref, in_store, note=""):
    """A trigger is only allowed if it is sourced. in_store=False means the shock has no
    row anywhere in our stores, which must then show up as a hop-level gap."""
    return {"kind": kind, "ref": ref, "sourced": True, "in_store": in_store, "note": note}


_CACHE = {}
_CON = None


def _resolve(names):
    global _CON
    if _CON is None:
        from reality_engine.db.readonly import connect_ro
        _CON = connect_ro(DATA / "equity_intelligence.db", timeout_s=60)
    out, missing = [], []
    for s in names:
        if s in _CACHE:
            row = _CACHE[s]
        else:
            row = _CON.execute(
                """SELECT m.nse_symbol, m.isin, m.company_name, m.market_cap_tier, c.basic_industry
                   FROM master_companies m LEFT JOIN company_industry c ON c.isin = m.isin
                   WHERE m.nse_symbol = ? LIMIT 1""", (s,)).fetchone()
            _CACHE[s] = row
        if not row or not row[0]:
            missing.append(s)
            continue
        out.append({"symbol": row[0], "isin": row[1], "name": row[2],
                    "basic_industry": row[4], "market_cap_tier": row[3]})
    if missing:
        raise SystemExit(f"UNRESOLVED SYMBOLS: {missing}")
    return out


def H(frm, to, mech, direction, lag, evidence, exists, gap=None):
    assert direction in DIR, direction
    assert exists in ("yes", "partial", "no"), exists
    return {"from": frm, "to": to, "mechanism": mech, "direction": direction,
            "expected_lag": lag, "evidence_needed": evidence, "exists_today": exists,
            "gap": GAP[gap][0] if (gap and gap not in ("-", None)) else None,
            "gap_key": gap if (gap and gap not in ("-", None)) else None}


DEFAULT_FORBIDDEN = [
    "hindsight: using a later document, price move or restatement to explain an earlier hop",
    "invented elasticity, pass-through rate or lag that is not measured from our own history or labelled an assumption",
    "opinion (analyst note, Telegram post, broker target) presented as fact",
    "unsourced or seeded macro event, or a policy date that is not in the document's known_at",
]


def R(qid, question, syms, chain, steps, trigger, as_of=None, extra_forbidden=(), gt=None, gt_query=None):
    ar = qid.split("-")[0]
    verdicts = [h["exists_today"] for h in chain]
    worst = "no" if "no" in verdicts else ("partial" if "partial" in verdicts else "yes")
    weakest = verdicts.index(worst) + 1
    row = {
        "qid": qid,
        "archetype": ar,
        "question": question,
        "entities": _resolve(syms),
        "trigger": trigger,
        "as_of": as_of,
        "chain": [dict(hop=i + 1, **h) for i, h in enumerate(chain)],
        "rubric": {
            "required_steps": list(steps),
            "forbidden": DEFAULT_FORBIDDEN + list(extra_forbidden),
            "ground_truth": gt,
            "ground_truth_query": gt_query,
        },
        "coverage": {
            "verdict": worst,
            "weakest_hop": weakest,
            "note": f"{sum(v == 'yes' for v in verdicts)}/{len(verdicts)} hops answerable today; "
                    f"hop {weakest} decides ({worst}).",
        },
    }
    return row
