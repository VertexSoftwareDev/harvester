from typing import Any

import pytest

from harvester.plugins import PluginNotFoundError
from harvester.transforms import apply_transforms, parse_number, parse_transform

URL = "https://shop.test/catalogue/page-1.html"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("£51.77", 51.77),
        ("$1,234.56", 1234.56),
        ("1.234,56 €", 1234.56),
        ("12,5 TL", 12.5),
        ("1,234", 1234.0),
        ("1,234,567", 1234567.0),
        ("1.234.567", 1234567.0),
        ("1 234,50", 1234.5),
        ("-3 degrees", -3.0),
        ("Total: 42.", 42.0),
        ("free", None),
    ],
)
def test_parse_number(text: str, expected: float | None) -> None:
    assert parse_number(text) == expected


@pytest.mark.parametrize(
    ("value", "specs", "expected"),
    [
        ("  In \n stock ", ["strip"], "In stock"),
        ("MiXeD", ["lower"], "mixed"),
        ("MiXeD", ["upper"], "MIXED"),
        ("In stock (22 available)", ["int"], 22),
        ("£9.99", ["price"], 9.99),
        (7, ["float"], 7.0),
        ("../book-1.html", ["absolute_url"], "https://shop.test/book-1.html"),
        ("star-rating Three", [r"regex:star-rating (\w+)", "lower"], "three"),
        ("order 123", [r"regex:\d+"], "123"),
        ("no digits", [r"regex:\d+", "int"], None),
        ("n/a", ["price", "int"], None),
    ],
)
def test_apply_transforms(value: Any, specs: list[str], expected: Any) -> None:
    assert apply_transforms(value, specs, URL) == expected


def test_parse_transform_keeps_colons_in_argument() -> None:
    assert parse_transform("regex:a:b") == ("regex", "a:b")
    assert parse_transform("strip") == ("strip", None)


def test_regex_requires_pattern() -> None:
    with pytest.raises(ValueError, match="needs a pattern"):
        apply_transforms("x", ["regex"], URL)


def test_unknown_transform() -> None:
    with pytest.raises(PluginNotFoundError):
        apply_transforms("x", ["nope"], URL)
