"""Tests for the rating-rationale fetcher (T-139). No network is touched."""

import shutil
import uuid
from pathlib import Path

import pytest

from reality_engine.ingestion import rating_rationale_client as rr


# ---------------------------------------------------------------------------
# rating / outlook / action parsers
# ---------------------------------------------------------------------------

def test_parse_crisil_table_line():
    fields = rr.parse_rating_line("CRISIL AAA/Stable (Reaffirmed)")
    assert fields["rating"] == "CRISIL AAA"
    assert fields["outlook"] == "Stable"
    assert fields["action"] == "reaffirmed"


def test_parse_care_table_line():
    fields = rr.parse_rating_line("CARE AAA; Stable Reaffirmed")
    assert fields["rating"] == "CARE AAA"
    assert fields["outlook"] == "Stable"
    assert fields["action"] == "reaffirmed"


def test_parse_icra_table_line():
    fields = rr.parse_rating_line("[ICRA]AA+ (Stable); reaffirmed")
    assert fields["rating"] == "[ICRA]AA+"
    assert fields["outlook"] == "Stable"
    assert fields["action"] == "reaffirmed"


def test_parse_line_without_rating_is_blank():
    fields = rr.parse_rating_line("The company reported revenue growth of 12%.")
    assert fields == {"rating": "", "outlook": "", "action": "", "instrument": ""}


def test_parse_care_filename_dates():
    assert rr.date_from_care_filename("202607120719_Havells_India_Limited.pdf") == "2026-07-12"
    assert rr.date_from_care_filename("20092022061900_Havells_India_Limited.pdf") == "2022-09-20"
    assert rr.date_from_care_filename("Havells India Limited-07-03-2020.pdf") == "2020-03-07"


# ---------------------------------------------------------------------------
# HTML -> text
# ---------------------------------------------------------------------------

def test_html_to_text_strips_scripts_and_navigation():
    markup = """
    <html><head><style>.x{color:red}</style>
    <script>var secret = "do not keep";</script></head>
    <body><nav>Home | About</nav>
    <h1>Rating rationale</h1>
    <p>CRISIL AAA/Stable (Reaffirmed) is based on <b>strong</b> cash flows.</p>
    <script>tracker()</script></body></html>
    """
    text = rr.html_to_text(markup)
    assert "Rating rationale" in text
    assert "strong" in text
    assert "secret" not in text
    assert "tracker" not in text
    assert "Home | About" not in text
    assert "color:red" not in text


# ---------------------------------------------------------------------------
# index skips a URL already fetched
# ---------------------------------------------------------------------------

class _NoFetch:
    def get(self, *args, **kwargs):  # pragma: no cover - must never run
        raise AssertionError("fetcher called for an indexed URL")


def test_index_skips_known_url():
    # pytest's tmp_path fixture is denied in the worker sandbox; a temp dir
    # under .tmp is writable.
    work = Path(".tmp") / f"rr-test-{uuid.uuid4().hex[:8]}"
    work.mkdir(parents=True)
    try:
        out = work / "ratings"
        out.mkdir()
        url = "https://www.careratings.com/upload/CompanyFiles/PR/202607120719_Havells_India_Limited.pdf"
        (out / "index.csv").write_text(
            "symbol,agency,rating_date,url,instrument,rating,outlook,action,chars,sha256,fetched_at\n"
            f"HAVELLS,CARE,2026-07-12,{url},,,,,\n",
            encoding="utf-8",
        )
        seen = rr.load_index(out / "index.csv")
        candidate = rr.Candidate(
            symbol="HAVELLS", company="Havells India Limited", agency="CARE",
            url=url, rating_date="2026-07-12",
        )
        assert rr.save_candidate(candidate, out, _NoFetch(), seen) is None  # type: ignore[arg-type]
    finally:
        shutil.rmtree(work, ignore_errors=True)


# ---------------------------------------------------------------------------
# rate limiter
# ---------------------------------------------------------------------------

def test_rate_limiter_spaces_calls_to_one_host():
    now = [100.0]
    sleeps: list[float] = []

    def clock() -> float:
        return now[0]

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        now[0] += seconds

    limiter = rr.RateLimiter(min_interval=1.0, clock=clock, sleep=sleep)
    limiter.wait("www.careratings.com")
    now[0] += 0.25  # the next request comes back quickly
    limiter.wait("www.careratings.com")
    assert sleeps == pytest.approx([0.75])
    # a different host is not delayed
    limiter.wait("www.icra.in")
    assert sleeps == pytest.approx([0.75])
