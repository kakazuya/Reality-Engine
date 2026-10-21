"""Daily cash book over one predeclared long H01 variant.

Inputs are normalized, schema-audited snapshot data. Fractional TR units
are a research convention. Rebalance equally on admissions, with unfilled
capacity held in cash. No borrowing and no shorting. Scheduled exits are
at close; an EOD kill liquidates at the NEXT executable session, so it can
overshoot 8%. Quotes may be carried only for valuation, never execution.
"""
import math
from collections import defaultdict
from .costs_tax import ROUND_TRIP_COST, tax_on_gains
from .data import as_date
from .execution import position_cap


def run_book(events, calendar, quotes, adtv, rules, benchmark_nav, *,
             has_open=True, capital=10_000_000.0, allocation_fraction=0.10,
             issuer_fraction=None, risk_policy=None):
    """events: entry, exit, isin; quotes[(isin,date)] = open/close mapping.

    adtv[(isin,date)] must be strictly lagged 20-session average value.
    benchmark_nav is an after-tax/cost daily unit NAV for a matched B5
    allocation; missing dates raise rather than silently shortening it.
    Negative surprise cohorts must never be passed as executable events.
    Current holding caps are checked at the previous close; required
    reductions execute next session. Exact equality is targeted on each
    admission; prices drift between admissions.
    """
    days = [d for d in calendar.days if 2021 <= d.year <= 2025]
    if not days:
        raise ValueError("No evidence-window sessions")
    for d in days:
        if d not in benchmark_nav or benchmark_nav[d] <= 0:
            raise ValueError(f"Missing B5 NAV on {d}")
    initial = capital * allocation_fraction
    cash, peak, total_peak = initial, initial, capital
    lots, stale, path = {}, {}, []
    entries = defaultdict(list)
    for event in events:
        if event.get("sign", "positive") != "positive":
            raise ValueError("Avoid cohorts cannot enter the long-only book")
        if event["entry"] in days and event["exit"] <= days[-1]:
            entries[event["entry"]].append(event)
    fees = taxes = 0.0
    allowance = {}
    killed_at = None
    pending_kill = False
    skipped = defaultdict(int)
    fills = []
    risk_decisions = []
    pending_risk = {}
    if issuer_fraction is not None and not 0 < issuer_fraction <= 1:
        raise ValueError('issuer_fraction must be in (0,1]')
    field = "open" if has_open else "close"

    def executable(isin, day, f):
        p = quotes.get((isin, day), {}).get(f)
        return p if p is not None and math.isfinite(p) and p > 0 else None

    def sell_units(isin, qty, price, day, reason):
        nonlocal cash, fees, taxes
        lot = lots[isin]
        qty = min(qty, lot["qty"])
        remaining, basis, gains = qty, 0.0, []
        for tranche in lot["tranches"]:
            take = min(remaining, tranche["qty"])
            if take > 0:
                paid = take * tranche["cost_price"]
                basis += paid
                gains.append({"gain": take * price - paid,
                              "holding_days": (as_date(day) - as_date(tranche["entry"])).days})
                tranche["qty"] -= take
                remaining -= take
        lot["tranches"] = [t for t in lot["tranches"] if t["qty"] > 1e-10]
        tax = tax_on_gains(gains, day, rules, allowance)
        fee = basis * ROUND_TRIP_COST / 2
        cash += qty * price - fee - tax
        fees += fee
        taxes += tax
        lot["qty"] -= qty
        fills.append({"date": day, "isin": isin, "side": "sell", "qty": qty,
                      "price": price, "fee": fee, "tax": tax,
                      "reason": reason})
        if lot["qty"] < 1e-10:
            del lots[isin]

    for day in days:
        exited_today = set()
        # A decision from yesterday's close cannot fill yesterday's close.
        if pending_kill:
            for isin in list(lots):
                p = executable(isin, day, field)
                if p is not None:
                    sell_units(isin, lots[isin]["qty"], p, day, "kill")
                else:
                    skipped["kill_missing_executable_quote"] += 1
        for isin in list(pending_risk):
            if isin not in lots:
                del pending_risk[isin]
                continue
            p = executable(isin, day, field)
            if p is not None:
                decision = pending_risk[isin]
                sell_units(isin, lots[isin]['qty'], p, day, decision['reason'])
                fills[-1].update({'risk_decision_date':decision['date'],
                                 'risk_signal_close':decision['observed_close'],
                                 'risk_weighted_cost':decision['weighted_cost'],
                                 'risk_peak_close':decision['peak_close']})
                exited_today.add(isin)
                del pending_risk[isin]
            else:
                skipped['risk_exit_missing_open'] += 1
        open_nav = cash + sum(lot['qty']*(executable(isin,day,field) or stale.get(isin,lot['cost_price']))
                              for isin,lot in lots.items())
        # Reduce cap breaches using today's lagged information at today's open.
        for isin in list(lots):
            p = executable(isin, day, field)
            cap = position_cap(adtv.get((isin, day), 0.0))
            if issuer_fraction is not None:
                cap = min(cap, open_nav*issuer_fraction)
            if p is not None and lots[isin]["qty"] * p > cap:
                sell_units(isin, lots[isin]["qty"] - cap / p, p, day, "liquidity_cap")
        admissions = []
        if not pending_kill and killed_at is None:
            for event in sorted(entries.get(day, []), key=lambda e: e["isin"]):
                isin = event["isin"]
                if isin in exited_today:
                    skipped['same_day_risk_reentry'] += 1
                elif risk_policy is not None and not risk_policy.admit(isin,day):
                    skipped['risk_admission_veto'] += 1
                elif isin in lots or any(e["isin"] == isin for e in admissions):
                    skipped["overlapping_same_isin"] += 1
                elif executable(isin, day, field) is None:
                    skipped["entry_missing_quote"] += 1
                else:
                    admissions.append(event)
        if admissions:
            # FIFO tranches preserve the clock and basis of every top-up.
            names = list(lots) + [e["isin"] for e in admissions]
            nav = cash + sum(lot["qty"] * (executable(i, day, field) or stale.get(i, lot["cost_price"]))
                             for i, lot in lots.items())
            target = nav / len(names)
            if issuer_fraction is not None:
                target = min(target,nav*issuer_fraction)
            for isin in list(lots):
                p = executable(isin, day, field)
                cap = min(target, position_cap(adtv.get((isin, day), 0.0)))
                if p is not None and lots[isin]["qty"] * p > cap:
                    sell_units(isin, lots[isin]["qty"] - cap / p, p, day, "equal_weight_admission")
            wants = {e["isin"]: min(target, position_cap(adtv.get((e["isin"], day), 0.0)))
                     for e in admissions}
            for isin, lot in lots.items():
                p = executable(isin, day, field)
                if p is not None:
                    wants[isin] = max(0.0, min(target, position_cap(adtv.get((isin, day), 0.0)))
                                      - lot["qty"] * p)
            required = sum(wants.values()) * (1 + ROUND_TRIP_COST / 2)
            scale = min(1.0, cash / required) if required > 0 else 0.0
            expiry = {e["isin"]: e["exit"] for e in admissions}
            for isin in sorted(wants):
                principal = wants[isin] * scale
                if principal <= 0:
                    skipped["zero_liquidity_capacity"] += 1
                    continue
                p = executable(isin, day, field)
                fee = principal * ROUND_TRIP_COST / 2
                cash -= principal + fee
                fees += fee
                tranche = {"entry": day, "qty": principal / p, "cost_price": p}
                if isin in lots:
                    lots[isin]["qty"] += principal / p
                    lots[isin]["tranches"].append(tranche)
                else:
                    lots[isin] = {"entry": day, "exit": expiry[isin], "qty": principal / p,
                                  "cost_price": p, "tranches": [tranche]}
                fills.append({"date": day, "isin": isin, "side": "buy", "qty": principal / p,
                              "price": p, "fee": fee, "tax": 0.0, "reason": "signal"})
        for isin in list(lots):
            close = executable(isin, day, "close")
            if close is not None:
                stale[isin] = close
            if day >= lots[isin]["exit"] and close is not None:
                sell_units(isin, lots[isin]["qty"], close, day, "scheduled_exit")
            elif day >= lots[isin]["exit"]:
                # Never discard the holding or pretend it exited at a stale
                # quote. It remains exposed, and is sold at next actual close.
                skipped["delayed_exit_missing_close"] += 1
            if isin in lots and risk_policy is not None:
                lot = lots[isin]
                if close is not None:
                    lot['peak_close'] = max(lot.get('peak_close',lot['cost_price']),close)
                reason = risk_policy.exit_reason(isin,day,lot,close)
                if reason and isin not in pending_risk:
                    reference = sum(t['qty']*t['cost_price'] for t in lot['tranches'])/lot['qty']
                    decision = {'date':day,'isin':isin,'reason':reason,'observed_close':close,
                                'weighted_cost':reference,'peak_close':lot.get('peak_close',lot['cost_price'])}
                    pending_risk[isin] = decision
                    risk_decisions.append(decision)
        # Every admitted event's scheduled exit is within this window. A
        # remaining lot at the terminal date has no executable exit quote.
        # Mark its recovery to zero as a bound; keep the unresolved lot in
        # the audit, and do not invent a sale or a tax loss credit.
        terminal_missing = day == days[-1] and bool(lots)
        nav = cash + (0.0 if terminal_missing else sum(
            lot["qty"] * stale.get(i, lot["cost_price"]) for i, lot in lots.items()))
        total = capital - initial + nav
        peak, total_peak = max(peak, nav), max(total_peak, total)
        dd, total_dd = 1 - nav / peak, 1 - total / total_peak
        market_down = len(path) > 0 and benchmark_nav[day] < benchmark_nav[path[-1]["date"]]
        portfolio_limit = 0.08 if market_down else 0.05
        if killed_at is None and (dd > 0.08 or total_dd > portfolio_limit):
            killed_at, pending_kill = day, True
        path.append({"date": day, "allocation_nav": nav, "total_nav": total,
                     "cash": cash, "drawdown": dd, "total_drawdown": total_dd,
                     "positions": len(lots), "b5_unit_nav": benchmark_nav[day]})
        if cash < -1e-6:
            raise AssertionError("Cash book borrowed money")
    years = (days[-1] - days[0]).days / 365.25
    final = path[-1]["allocation_nav"]
    # benchmark_nav is normalized to 1 BEFORE the first evidence session.
    b5_multiple = benchmark_nav[days[-1]]
    strategy_cagr = (final / initial) ** (1 / years) - 1
    benchmark_cagr = b5_multiple ** (1 / years) - 1
    return {"initial_allocation_inr": initial, "final_allocation_inr": final,
            "allocation_cagr": strategy_cagr,
            "total_capital_cagr": (path[-1]["total_nav"] / capital) ** (1 / years) - 1,
            "max_drawdown": max(p["drawdown"] for p in path),
            "portfolio_max_drawdown": max(p["total_drawdown"] for p in path),
            "b5_cagr": benchmark_cagr, "excess_cagr": strategy_cagr - benchmark_cagr,
            "kill_date": killed_at, "costs_inr": fees, "taxes_inr": taxes,
            "unresolved_holdings": lots, "skipped": dict(skipped),
            "fills": fills, "nav": path,
            "risk_decisions":risk_decisions,"issuer_fraction":issuer_fraction,
            "flags": ["fractional TR units", "equal weights targeted only at admissions",
                      "FIFO top-up tranches", "EOD kill fills next executable session",
                      "unresolved holdings marked stale until terminal zero-recovery bound; prevent promotion"]}
