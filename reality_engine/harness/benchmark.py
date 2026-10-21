"""B5 selection frozen before each month, using strictly earlier TRI data."""
from bisect import bisect_right
from datetime import date, timedelta

INDEX_NAMES = ("Nifty Smallcap 250", "BSE 250 SmallCap", "Nifty Midcap 150",
               "BSE Sensex", "BSE IPO")


def previous_year(day):
    try:
        return day.replace(year=day.year - 1)
    except ValueError:
        return day.replace(year=day.year - 1, day=28)


def select_month(series, month_start):
    """series: canonical index name -> {date: (tri, method)}.

    End = last observed session before month start. Base = last session on
    or before end minus one calendar year. Require all five, with quotes
    no more than seven days stale. Missing peers never silently drop out.
    """
    cutoff = month_start - timedelta(days=1)
    candidates = []
    for name in INDEX_NAMES:
        rows = series.get(name, {})
        days = sorted(d for d in rows if d <= cutoff)
        if not days or (cutoff - days[-1]).days > 7:
            return None
        end = days[-1]
        target = previous_year(end)
        i = bisect_right(days, target) - 1
        if i < 0 or (target - days[i]).days > 7:
            return None
        base = days[i]
        if rows[base][0] <= 0 or rows[end][0] <= 0:
            return None
        candidates.append({"index": name, "trailing_return": rows[end][0] / rows[base][0] - 1,
                           "base_date": base, "asof_date": end,
                           "method": rows[end][1], "base_method": rows[base][1]})
    chosen = max(candidates, key=lambda r: (r["trailing_return"], r["index"]))
    return {**chosen, "month": month_start, "window": "12 calendar months"}


def monthly_choices(series, start=date(2021, 1, 1), end=date(2025, 12, 31)):
    out = []
    day = start.replace(day=1)
    while day <= end:
        choice = select_month(series, day)
        if choice is None:
            raise ValueError(f"Incomplete five-index B5 lookback for {day}")
        out.append(choice)
        day = date(day.year + (day.month == 12), day.month % 12 + 1, 1)
    return out


class B5Path:
    """Monthly B5 chain with explicitly flagged previous-close entry proxy.

    index_tri has no opens. Each daily leg uses the selected index's
    previous session TRI close through today's TRI close. No splice in index
    levels is treated as a return. This timing mismatch is a report deviation.
    """
    def __init__(self, series, calendar, rules):
        import numpy as np
        normal_days = set(calendar.days)
        self.series = {name: {day: value for day,value in rows.items() if day in normal_days}
                       for name,rows in series.items()}
        self.calendar, self.rules = calendar, rules
        self.choices = monthly_choices(self.series)
        chosen = {r['month']: r['index'] for r in self.choices}
        self.names, self.factors = [], []
        self.regime_up = []
        for i, day in enumerate(calendar.days):
            name = chosen.get(day.replace(day=1))
            self.names.append(name)
            if name is None:
                self.factors.append(1.)
                self.regime_up.append(False)
                continue
            if i == 0:
                raise ValueError('B5 lacks prior-session anchor')
            previous = calendar.days[i-1]
            rows = self.series[name]
            if day not in rows or previous not in rows:
                raise ValueError(f'B5 missing exact TRI quote: {name} {day}')
            self.factors.append(rows[day][0]/rows[previous][0])
            # Regime is known before entry: selected index's prior 63 sessions.
            base = calendar.days[max(0,i-64)]
            self.regime_up.append(rows[previous][0] >= rows[base][0])
        self.factors = np.array(self.factors)
        self.regime_up = np.array(self.regime_up)
        self.gross_nav = np.cumprod(self.factors)

    def event_return(self, entry, exit):
        """After-tax/cost benchmark, realizing at each actual index change.

        Every distinct-index segment is a round trip. Rechoosing the same
        index creates no turnover. Sale dates determine the snapshot tax rate.
        Event normalization claims no annual LTCG allowance.
        """
        from .costs_tax import sale
        value, gross, start = 1., 1., entry
        for i in range(entry,exit+1):
            if i > entry and self.names[i] != self.names[i-1]:
                net = sale(gross-1,self.calendar.days[start],self.calendar.days[i-1],self.rules)
                value *= 1+net['net_return']
                gross, start = 1., i
            gross *= self.factors[i]
        net = sale(gross-1,self.calendar.days[start],self.calendar.days[exit],self.rules)
        return value*(1+net['net_return'])-1

    def book_nav(self, principal=1_000_000.):
        """Cash-equity index proxy, annual exemption shared across all switches.

        Fees are half the original principal at buy and sell. No loss credit.
        Mark-to-market NAV pays tax on switching and terminal liquidation.
        """
        from .costs_tax import sale, ROUND_TRIP_COST
        first = next(i for i,n in enumerate(self.names) if n is not None)
        half = ROUND_TRIP_COST/2
        capital = principal/(1+half)
        value = capital
        start = first
        allowance = {}
        nav, total_tax, total_cost = {}, 0., principal-capital
        for i in range(first,len(self.names)):
            if i > first and self.names[i] != self.names[i-1]:
                result = sale(value/capital-1,self.calendar.days[start],self.calendar.days[i],
                              self.rules,principal=capital,exemption_used=allowance)
                fee = capital*half
                cash = value-result['tax_inr']-fee
                total_tax += result['tax_inr']
                total_cost += fee
                capital = cash/(1+half)
                total_cost += cash-capital
                value, start = capital, i
            value *= self.factors[i]
            if i == len(self.names)-1:
                result = sale(value/capital-1,self.calendar.days[start],self.calendar.days[i],
                              self.rules,principal=capital,exemption_used=allowance)
                value -= result['tax_inr']+capital*half
                total_tax += result['tax_inr']
                total_cost += capital*half
            nav[self.calendar.days[i]] = value/principal
        return nav, {'costs_inr': total_cost,'taxes_inr': total_tax,
                     'entry_proxy': 'previous-session TRI close; no index opens in snapshot'}
