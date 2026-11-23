"""T-178: the first-build salvage script's number normaliser and verbatim check."""
from __future__ import annotations

from reality_engine.scripts.t178_salvage import appears_verbatim, norm_number, verbatim_numbers


def test_norm_number_drops_commas_tildes_and_percent():
    assert norm_number("(1,234.5)") == "-1234.5"
    assert norm_number("~84.71") == "84.71"
    assert norm_number("12.3%") == "12.3"
    assert norm_number("Rs. 1,200") == "1200"
    assert norm_number("(3,210)") == "-3210"


def test_norm_number_blank_is_empty():
    assert norm_number("") == ""
    assert norm_number(None) == ""
    assert norm_number("-") == ""


def test_appears_verbatim_same_normalisation():
    numbers = verbatim_numbers(["Land", "~84.71", "acres", "1,234.5", "(3,210)"])
    assert appears_verbatim("84.71", numbers)            # the tilde and the comma are decoration
    assert appears_verbatim("~84.71", numbers)
    assert appears_verbatim("(3,210)", numbers)
    assert not appears_verbatim("84.72", numbers)        # a different printed figure
    assert not appears_verbatim("3210", numbers)         # the page prints it in brackets (negative)
    assert not appears_verbatim("", numbers)
