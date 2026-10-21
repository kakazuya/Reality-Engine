"""Snapshot-only data access; no live database imports or connections.

The diffusion study's session indexing and lagged-information convention are
retained. No forward-filled quote is ever an executable trade price.
"""
from bisect import bisect_right
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT = ROOT / "reality_engine/data/snapshots/truth_2026-10-19.duckdb"
EVIDENCE_START = date(2021, 1, 1)
EVIDENCE_END = date(2025, 12, 31)


def as_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


class Snapshot:
    def __init__(self, path=SNAPSHOT):
        import duckdb
        self.path = Path(path).resolve()
        if self.path != SNAPSHOT.resolve():
            raise ValueError("Only the authorized dated snapshot may be opened")
        self.connection = duckdb.connect(str(self.path), read_only=True)

    def describe(self, table):
        tables = {r[0] for r in self.connection.execute("SHOW TABLES").fetchall()}
        if table not in tables:
            raise ValueError(f"Absent snapshot table: {table}")
        return self.connection.execute(f'DESCRIBE "{table}"').fetchall()

    def close(self):
        self.connection.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class Calendar:
    def __init__(self, dates):
        self.days = tuple(sorted(set(map(as_date, dates))))

    @classmethod
    def normal_sessions(cls, dates):
        """Predeclared weekday-only research calendar; omit special weekends.

        Entry, liquidity windows, horizons and B5 all use this same calendar.
        This deliberately omits genuine Saturday budget/drill sessions too.
        """
        return cls(d for d in map(as_date, dates) if d.weekday() < 5)

    def next_session(self, trigger):
        """Strictly next exchange session after the trigger's IST calendar date.

        Intraday filings also wait until the following session. Weekend filings
        enter Monday, with no extra artificial day's delay.
        """
        i = bisect_right(self.days, as_date(trigger))
        return self.days[i] if i < len(self.days) else None

    def offset(self, day, n):
        i = bisect_right(self.days, as_date(day)) - 1
        if i < 0 or self.days[i] != as_date(day):
            return None
        j = i + n
        return self.days[j] if 0 <= j < len(self.days) else None


def price_asof(quotes, day):
    """Last observed (date, price) at or before day; valuation only."""
    days = sorted(quotes)
    i = bisect_right(days, as_date(day)) - 1
    return (days[i], quotes[days[i]]) if i >= 0 else (None, None)
