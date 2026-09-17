"""Command-line interface, e.g. ``harvester run examples/books.yaml -e excel``."""

import asyncio
import inspect
import logging
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError
from rich.console import Console
from rich.logging import RichHandler
from rich.markup import escape
from rich.table import Table

from harvester import __version__
from harvester.config import ExportSpec, JobConfig, JobConfigError, load_job
from harvester.exporters import exporter_registry
from harvester.pipeline import RunReport, run_job
from harvester.transforms import transform_registry

app = typer.Typer(
    help="Declarative async web scraping: YAML in, clean data out.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()
err_console = Console(stderr=True)

JobFile = Annotated[
    Path, typer.Argument(exists=True, dir_okay=False, readable=True, help="YAML job file.")
]


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"harvester {__version__}")
        raise typer.Exit


@app.callback()
def main(
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="Show progress logs.")] = False,
    version: Annotated[
        bool,
        typer.Option("--version", callback=_version_callback, is_eager=True, help="Show version."),
    ] = False,
) -> None:
    logging.basicConfig(
        level=logging.INFO if verbose else logging.WARNING,
        format="%(message)s",
        handlers=[RichHandler(console=err_console, show_path=False)],
        force=True,
    )


@app.command()
def run(
    job_file: JobFile,
    export: Annotated[
        list[str] | None,
        typer.Option(
            "--export",
            "-e",
            metavar="FORMAT[:PATH]",
            help="Override the job's exports. Repeatable, e.g. -e excel -e csv:out.csv",
        ),
    ] = None,
    output_dir: Annotated[
        Path, typer.Option("--output-dir", "-o", file_okay=False, help="Where files are written.")
    ] = Path("output"),
    max_pages: Annotated[
        int | None, typer.Option(min=1, help="Override pagination.max_pages.")
    ] = None,
) -> None:
    """Crawl a job and export the results."""
    job = _load(job_file)
    if max_pages is not None and job.pagination is not None:
        pagination = job.pagination.model_copy(update={"max_pages": max_pages})
        job = job.model_copy(update={"pagination": pagination})
    exports = [_parse_export(value) for value in export] if export else None

    with console.status(f"Harvesting [bold]{escape(job.name)}[/]..."):
        report = asyncio.run(run_job(job, exports=exports, output_dir=output_dir))

    _print_report(report)
    if report.stats.pages_ok == 0:
        raise typer.Exit(1)


@app.command()
def validate(job_file: JobFile) -> None:
    """Check a job file without fetching anything."""
    job = _load(job_file)
    table = Table(title=f"Job '{escape(job.name)}' is valid", title_justify="left")
    for column in ("field", "selector", "attr", "transforms", "flags"):
        table.add_column(column)
    for name, spec in job.fields.items():
        flags = ", ".join(flag for flag in ("many", "required") if getattr(spec, flag))
        table.add_row(
            name,
            escape(spec.selector),
            escape(spec.attr or "text"),
            escape(" | ".join(spec.transforms)),
            flags,
        )
    console.print(table)


@app.command()
def plugins() -> None:
    """List available exporters and transforms."""
    registries: list[tuple[str, list[tuple[str, object]]]] = [
        ("Exporters", list(exporter_registry)),
        ("Transforms", list(transform_registry)),
    ]
    for title, entries in registries:
        table = Table(title=title, title_justify="left")
        table.add_column("name", style="bold cyan")
        table.add_column("description")
        for name, obj in entries:
            doc = (inspect.getdoc(obj) or "").split("\n", 1)[0]
            table.add_row(name, escape(doc))
        console.print(table)


def _load(job_file: Path) -> JobConfig:
    try:
        return load_job(job_file)
    except JobConfigError as exc:
        err_console.print(f"[red]error:[/] {escape(str(exc))}")
        raise typer.Exit(1) from exc


def _parse_export(value: str) -> ExportSpec:
    fmt, sep, path = value.partition(":")
    try:
        return ExportSpec(format=fmt, path=path if sep else None)
    except ValidationError as exc:
        raise typer.BadParameter(exc.errors()[0]["msg"], param_hint="--export") from exc


def _print_report(report: RunReport) -> None:
    stats = report.stats
    table = Table(
        title=f"Job '{escape(report.job)}' finished", show_header=False, title_justify="left"
    )
    table.add_column(style="bold")
    table.add_column()
    table.add_row("Pages", f"{stats.pages_ok} ok, {stats.pages_failed} failed")
    table.add_row("Items", f"{stats.items} scraped, {stats.items_skipped} skipped")
    table.add_row("Elapsed", f"{stats.elapsed:.2f}s")
    for path in report.outputs:
        table.add_row("Output", escape(str(path)))
    console.print(table)
