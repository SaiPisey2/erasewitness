import pytest

from erasewitness.normalise import contains_value, first_match, normalise


def test_normalise_folds_case_and_space() -> None:
    assert normalise("  My   SALARY\tis 42 LPA ") == "my salary is 42 lpa"


@pytest.mark.parametrize(
    ("haystack", "needle"),
    [
        ("My salary is 42 LPA.", "42 lpa"),
        ("earns 42,00,000 a year", "4200000"),
        ("earns 4,200,000", "42,00,000"),
        ("call 98765 43210 now", "9876543210"),
        ("ref (reference EW-004211)", "EW-004211"),
    ],
)
def test_contains_value_matches_formats(haystack: str, needle: str) -> None:
    assert contains_value(haystack, needle)


@pytest.mark.parametrize(
    ("haystack", "needle"),
    [
        ("earns 142 lakh", "42 lakh"),
        ("salary 42 LPAX", "42 LPA"),
        ("anything", ""),
    ],
)
def test_contains_value_rejects_partial(haystack: str, needle: str) -> None:
    assert not contains_value(haystack, needle)


def test_first_match_returns_first_needle_found() -> None:
    assert first_match("ref EW-004211 and 42 LPA", ["EW-004211", "42 LPA"]) == "EW-004211"
    assert first_match("nothing here", ["42 LPA"]) is None
