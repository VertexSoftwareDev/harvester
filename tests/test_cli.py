from pathlib import Path

import respx
import yaml
from typer.testing import CliRunner

from harvester import __version__
from harvester.cli import app
from tests.conftest import BASE, PAGE_1, PAGE_2, job_data

runner = CliRunner()
EXAMPLE = Path(__file__).parents[1] / "examples" / "books.yaml"


def write_job(tmp_path: Path, **overrides: object) -> Path:
    path = tmp_path / "books.yaml"
    path.write_text(yaml.safe_dump(job_data(**overrides)), encoding="utf-8")
    return path


def test_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_validate_example() -> None:
    result = runner.invoke(app, ["validate", str(EXAMPLE)])
    assert result.exit_code == 0, result.output
    assert "is valid" in result.output
    assert "price" in result.output


def test_validate_reports_errors(tmp_path: Path) -> None:
    job_file = write_job(tmp_path, item="")
    result = runner.invoke(app, ["validate", str(job_file)])
    assert result.exit_code == 1


def test_plugins_lists_builtins() -> None:
    result = runner.invoke(app, ["plugins"])
    assert result.exit_code == 0
    for name in ("excel", "jsonl", "price", "absolute_url"):
        assert name in result.output


def test_run(respx_mock: respx.MockRouter, tmp_path: Path) -> None:
    respx_mock.get(BASE + "page-1.html").respond(200, html=PAGE_1)
    respx_mock.get(BASE + "page-2.html").respond(200, html=PAGE_2)
    job_file = write_job(tmp_path)
    out = tmp_path / "out"

    result = runner.invoke(
        app,
        ["run", str(job_file), "-e", "csv", "-e", "excel:report.xlsx", "-o", str(out),
         "--max-pages", "1"],
    )  # fmt: skip

    assert result.exit_code == 0, result.output
    assert (out / "books.csv").exists()
    assert (out / "report.xlsx").exists()
    assert "2 scraped, 1 skipped" in result.output


def test_run_rejects_unknown_export_format(tmp_path: Path) -> None:
    result = runner.invoke(app, ["run", str(write_job(tmp_path)), "-e", "pdf"])
    assert result.exit_code == 2
    assert "Unknown exporter" in result.output


def test_run_exits_nonzero_when_every_page_fails(
    respx_mock: respx.MockRouter, tmp_path: Path
) -> None:
    respx_mock.get(BASE + "page-1.html").respond(404)
    out = tmp_path / "out"
    result = runner.invoke(app, ["run", str(write_job(tmp_path)), "-o", str(out)])
    assert result.exit_code == 1
    assert not out.exists()
