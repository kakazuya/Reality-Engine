"""T-130: known_at of an XBRL results file the filing record left undated, read from the file name stamp."""
from reality_engine.gap_loop.prepare import xbrl_file_ts


def test_12h_stamp_read_as_pm_never_early():
    assert xbrl_file_ts("INTEGRATED_FILING_INDAS_1741830_19102026060630_WEB.xml") == "2026-10-19T18:06:30"
    # an 11:01 am filing is read 12 h late: later than the truth, never earlier
    assert xbrl_file_ts("INDAS_67438_403878_09022021110110_WEB.xml") == "2021-02-09T23:01:10"
    assert xbrl_file_ts("INDAS_1_2_09022021120110_WEB.xml") == "2021-02-09T12:01:10"


def test_24h_stamp():
    assert xbrl_file_ts("Integrated_file_20261020_191249443.xml") == "2026-10-20T19:12:49"


def test_no_stamp():
    assert xbrl_file_ts("abc.xml") is None
    assert xbrl_file_ts(None) is None
    assert xbrl_file_ts("X_32132026060630_WEB.xml") is None
