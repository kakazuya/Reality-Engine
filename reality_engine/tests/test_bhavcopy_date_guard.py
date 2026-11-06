"""T-099: a bhavcopy is only that date's session when its own DATE1 column prints the date."""
from datetime import datetime

import pandas as pd

from reality_engine.ingestion.nse_client import bhavcopy_file_dates, bhavcopy_text_date_ok

HEAD = "SYMBOL, SERIES, DATE1, PREV_CLOSE, CLOSE_PRICE, DELIV_QTY, DELIV_PER\n"


def test_holiday_url_serving_previous_session_is_refused():
    # The raw cache file named 20 Oct 2026 holds the 19 Oct session (T-089 report, section 2).
    body = HEAD + "20MICRONS, EQ, 19-Oct-2026, 193.32, 185.60, 57402, 51.42\n"
    assert not bhavcopy_text_date_ok(body, datetime(2026, 10, 20))
    assert bhavcopy_text_date_ok(body, datetime(2026, 10, 19))


def test_file_dates_reads_padded_columns_and_values():
    frame = pd.DataFrame({" DATE1": [" 04-Nov-2021", " 04-Nov-2021"], " SYMBOL": ["INFY", "TCS"]})
    assert bhavcopy_file_dates(frame) == {"2021-11-04"}


def test_no_date_column_is_not_a_match():
    assert not bhavcopy_text_date_ok("SYMBOL, SERIES\nINFY, EQ\n", datetime(2026, 10, 19))
