"""Executable dates/prices; no stale quote substituted at either endpoint."""
import math
from .data import EVIDENCE_END


def trade_window(calendar, trigger, horizon, quotes, *, has_open=True,
                 evidence_end=EVIDENCE_END):
    """N sessions AFTER entry; entry is strictly t+1, exit at entry+N close.

    quotes maps exchange-session dates to {'open': ..., 'close': ...}. Use
    consistently adjusted quotes (including dividend adjustment for TR).
    A missing open on a schema that has opens rejects the trade.
    """
    entry = calendar.next_session(trigger)
    exit_day = calendar.offset(entry, horizon) if entry else None
    if not exit_day or exit_day > evidence_end:
        return None
    field = "open" if has_open else "close"
    a = quotes.get(entry, {}).get(field)
    scheduled_exit = exit_day
    b = quotes.get(exit_day, {}).get("close")
    if b is None or not math.isfinite(b) or b <= 0:
        later = [d for d in calendar.days if scheduled_exit < d <= evidence_end]
        for d in later:
            candidate = quotes.get(d, {}).get("close")
            if candidate is not None and math.isfinite(candidate) and candidate > 0:
                exit_day, b = d, candidate
                break
    if any(x is None or not math.isfinite(x) or x <= 0 for x in (a, b)):
        return None
    return {"entry": entry, "exit": exit_day, "scheduled_exit": scheduled_exit, "entry_price": a,
            "exit_price": b, "gross_return": b / a - 1,
            "entry_close_fallback": not has_open}


def position_cap(adtv_inr):
    return max(0.0, adtv_inr * 0.10)


def next_close_indices(closes):
    """Earliest actual positive close at/after each row; len(rows) if absent.

    Only resolves scheduled liquidation. Never used to select an admission.
    A missing quote with a later quote must never become a total-loss bound.
    """
    import numpy as np
    t, n = closes.shape
    out = np.full((t + 1, n), t, dtype=np.int32)
    for i in range(t - 1, -1, -1):
        out[i] = np.where(np.isfinite(closes[i]) & (closes[i] > 0), i, out[i + 1])
    return out
