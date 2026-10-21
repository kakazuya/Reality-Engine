"""Year-by-year subset coverage. Missing data never become a zero feature."""
from .data import as_date


def coverage_report(u1_observations, financial_observations, signal_observations):
    """Inputs are (date, trading_isin), after PIT mapping and quarantine.

    U1 denominator: any eligible session in that calendar year, with all
    delisted names retained. Numerators intersect that denominator. Financial
    coverage uses trigger year, not financial period year. Signal coverage
    also requires twelve usable historical quarters. This reports snapshot
    support for H01; it cannot certify annual reports, concalls or decks.
    """
    def by_year(observations):
        groups = {y: set() for y in range(2021, 2026)}
        for day, isin in observations:
            y = as_date(day).year
            if y in groups:
                groups[y].add(isin)
        return groups
    universe = by_year(u1_observations)
    financial = by_year(financial_observations)
    signals = by_year(signal_observations)
    result = []
    for y, u in universe.items():
        f, s = financial[y] & u, signals[y] & u
        result.append({"year": y, "u1_isins": len(u), "financial_covered_isins": len(f),
                       "usable_surprise_isins": len(s),
                       "financial_coverage": len(f) / len(u) if u else None,
                       "signal_coverage": len(s) / len(u) if u else None,
                       "status": "provisional",
                       "full_data_completeness_gate_met": False})
    return result
