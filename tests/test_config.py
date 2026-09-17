from datetime import datetime
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from harvester.config import ExportSpec, FieldSpec, JobConfigError, load_job
from tests.conftest import JobFactory, job_data

EXAMPLES = sorted((Path(__file__).parents[1] / "examples").glob("*.yaml"))


@pytest.mark.parametrize(
    ("shorthand", "selector", "attr", "transforms"),
    [
        ("h3 a", "h3 a", None, ()),
        ("h3 a @title", "h3 a", "title", ()),
        ("p.price_color | price", "p.price_color", None, ("price",)),
        ("a.link @href | absolute_url | strip", "a.link", "href", ("absolute_url", "strip")),
        (r"p @class | regex:(\w+)|x", "p", "class", (r"regex:(\w+)|x",)),
    ],
)
def test_field_shorthand(
    shorthand: str, selector: str, attr: str | None, transforms: tuple[str, ...]
) -> None:
    spec = FieldSpec.model_validate(shorthand)
    assert (spec.selector, spec.attr, spec.transforms) == (selector, attr, transforms)


def test_unknown_transform_suggests_closest_name() -> None:
    with pytest.raises(ValidationError, match="Did you mean 'price'"):
        FieldSpec.model_validate("p | prise")


def test_unknown_exporter_is_rejected() -> None:
    with pytest.raises(ValidationError, match="Unknown exporter 'xls'"):
        ExportSpec(format="xls")


def test_bad_path_template_is_rejected() -> None:
    with pytest.raises(ValidationError, match="invalid path template"):
        ExportSpec(format="csv", path="{nope}.csv")


def test_export_path_resolution() -> None:
    now = datetime(2026, 9, 17, 8, 30, 0)
    assert ExportSpec(format="excel").resolve_path("books", Path("out"), now) == Path(
        "out/books.xlsx"
    )
    templated = ExportSpec(format="csv", path="{name}/{date}-{timestamp}.csv")
    assert templated.resolve_path("books", Path("out"), now) == Path(
        "out/books/2026-09-17-20260917-083000.csv"
    )


def test_config_is_immutable(make_job: JobFactory) -> None:
    job = make_job()
    with pytest.raises(ValidationError):
        job.name = "other"  # type: ignore[misc]


def test_extra_keys_are_rejected(make_job: JobFactory) -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        make_job(paginaton={"next": "a"})


def test_load_job_defaults_name_to_file_stem(tmp_path: Path) -> None:
    data = job_data()
    del data["name"]
    path = tmp_path / "my-shop.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")

    job = load_job(path)

    assert job.name == "my-shop"
    assert job.fields["price"].transforms == ("price",)


def test_load_job_reports_every_problem(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text("start_urls: [not-a-url]\nitem: ''\nfields: {}\n", encoding="utf-8")

    with pytest.raises(JobConfigError) as excinfo:
        load_job(path)

    message = str(excinfo.value)
    assert "start_urls.0" in message
    assert "item" in message
    assert "fields" in message


@pytest.mark.parametrize(
    ("content", "error"),
    [("a: [unclosed", "Invalid YAML"), ("- just\n- a list\n", "expected a mapping")],
)
def test_load_job_rejects_malformed_files(tmp_path: Path, content: str, error: str) -> None:
    path = tmp_path / "job.yaml"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(JobConfigError, match=error):
        load_job(path)


def test_load_job_missing_file(tmp_path: Path) -> None:
    with pytest.raises(JobConfigError, match="Cannot read"):
        load_job(tmp_path / "missing.yaml")


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.name)
def test_examples_are_valid(path: Path) -> None:
    load_job(path)
