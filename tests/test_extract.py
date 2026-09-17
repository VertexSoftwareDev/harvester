from harvester.config import FieldSpec
from harvester.extract import parse_page
from tests.conftest import BASE, PAGE_1, PAGE_2, JobFactory


def test_parse_page_extracts_items_and_next_link(make_job: JobFactory) -> None:
    page = parse_page(PAGE_1, BASE + "page-1.html", make_job())

    assert page.items == [
        {
            "title": "A Light in the Attic",
            "price": 51.77,
            "availability": "In stock",
            "rating": "three",
            "url": BASE + "book-1.html",
        },
        {
            "title": "Tipping the Velvet",
            "price": 53.74,
            "availability": "In stock",
            "rating": "one",
            "url": BASE + "book-2.html",
        },
    ]
    assert page.skipped == 1
    assert page.next_urls == [BASE + "page-2.html"]


def test_missing_optional_fields_are_none(make_job: JobFactory) -> None:
    job = make_job(fields={"title": "h3 a @title", "missing": "span.nope"})

    page = parse_page(PAGE_2, BASE + "page-2.html", job)

    assert page.items == [{"title": "Soumission", "missing": None}]


def test_many_collects_all_matches(make_job: JobFactory) -> None:
    job = make_job(
        fields={
            "title": "h3 a @title",
            "tags": FieldSpec(selector="a.tag", many=True, transforms=("upper",)),
        }
    )

    page = parse_page(PAGE_1, BASE, job)

    assert [item["tags"] for item in page.items] == [["POETRY", "CLASSIC"], [], []]


def test_no_pagination_means_no_next_urls(make_job: JobFactory) -> None:
    page = parse_page(PAGE_1, BASE, make_job(pagination=None))
    assert page.next_urls == []
