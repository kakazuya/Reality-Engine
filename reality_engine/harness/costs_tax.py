"""Fixed 30 bp return debit and sell-date tax, with no live DB access.

Reuse sip_backtest's tax conventions: long iff holding >365 days, no tax
credit on losses, annual LTCG allowance used once per FY. The schedule must
be supplied from the snapshot, never sip_backtest's hardcoded schedule.
STT is not deducted from taxable gains. Conservatively tax gross capital
gain and debit all 30 bp separately; no assumed deduction for other fees.
"""
from .data import as_date
from reality_engine.processing.sip_backtest import LTCG_MIN_HOLD_DAYS, fy_of

ROUND_TRIP_COST = 0.003


def financial_year(day):
    return fy_of(as_date(day).isoformat())


class TaxRules:
    """Normalized snapshot intervals: rule, start, end, value.

    Normalization belongs to the schema-checked snapshot adapter. Rates
    are decimal fractions; interval endpoints are inclusive.
    """
    def __init__(self, intervals):
        self.intervals = list(intervals)

    def rule(self, name, sell_date):
        day = as_date(sell_date)
        rows = [r for r in self.intervals if r["rule"] == name
                and as_date(r["start"]) <= day
                and (r.get("end") is None or day <= as_date(r["end"]))]
        if len(rows) != 1:
            raise ValueError(f"Expected one tax rule {name} at {day}; got {len(rows)}")
        return float(rows[0]["value"])


def tax_on_gains(gains, sell_date, rules, exemption_used=None):
    """Reuse SIP's within-sale ST/LT bucket netting and FY allowance logic.

    gains contains gain (INR) and holding_days. No loss credit, cross-sale
    loss netting or carry-forward is assumed.
    """
    st = sum(g["gain"] for g in gains if g["holding_days"] <= LTCG_MIN_HOLD_DAYS)
    lt = sum(g["gain"] for g in gains if g["holding_days"] > LTCG_MIN_HOLD_DAYS)
    taxable_lt = max(0.0, lt)
    if exemption_used is not None and taxable_lt > 0:
        fy = financial_year(sell_date)
        remaining = max(0.0, rules.rule("ltcg_exempt", sell_date)
                        - exemption_used.get(fy, 0.0))
        used = min(taxable_lt, remaining)
        exemption_used[fy] = exemption_used.get(fy, 0.0) + used
        taxable_lt -= used
    return (max(0.0, st) * rules.rule("stcg_rate", sell_date)
            + taxable_lt * rules.rule("ltcg_rate", sell_date))


def sale(gross_return, buy_date, sell_date, rules, *, principal=1.0,
         exemption_used=None):
    """Event returns default to zero remaining LTCG allowance.

    A book passes a mutable FY allowance ledger. An isolated normalized
    event cannot claim the investor's entire annual exemption for itself.
    For 20/60-session H01 all gains are short term.
    """
    long = (as_date(sell_date) - as_date(buy_date)).days > LTCG_MIN_HOLD_DAYS
    rate = rules.rule("ltcg_rate" if long else "stcg_rate", sell_date)
    tax = tax_on_gains([{"gain": principal * gross_return,
                         "holding_days": (as_date(sell_date) - as_date(buy_date)).days}],
                       sell_date, rules, exemption_used)
    costs = principal * ROUND_TRIP_COST
    return {"net_return": gross_return - ROUND_TRIP_COST - tax / principal,
            "cost_inr": costs, "tax_inr": tax,
            "tax_rate": rate, "long_term": long}


def short_term_net(gross_return, sell_date_rates):
    """Vector form of sale for verified sub-one-year event windows."""
    import numpy as np
    return gross_return - ROUND_TRIP_COST - np.maximum(gross_return, 0.) * sell_date_rates
