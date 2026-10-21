"""U1 filtering, independent of today's active/listed flag."""
import math
from statistics import mean, median

DEFAULT_MEDIAN_VALUE_INR = 5_000_000.0
POSITION_ADTV_FRACTION = 0.10


def liquidity(history, threshold=DEFAULT_MEDIAN_VALUE_INR):
    """Exactly 20 prior market sessions; missing values are not zero-imputed.

    Caller supplies one value per prior exchange session, strictly before the
    signal date. Requiring all 20 is deliberately conservative for suspensions.
    """
    values = list(history)[-20:]
    valid = len(values) == 20 and all(
        v is not None and math.isfinite(v) and v >= 0 for v in values)
    if not valid:
        return {"eligible": False, "median_value_inr": None, "adtv_inr": None,
                "threshold_inr": threshold}
    return {"eligible": median(values) >= threshold,
            "median_value_inr": median(values), "adtv_inr": mean(values),
            "threshold_inr": threshold}


def eligible(raw_close, history, *, in_security_master, quarantined=False,
             threshold=DEFAULT_MEDIAN_VALUE_INR):
    info = liquidity(history, threshold)
    info["eligible"] = bool(info["eligible"] and in_security_master
                            and not quarantined and raw_close is not None
                            and math.isfinite(raw_close) and raw_close >= 10)
    return info
