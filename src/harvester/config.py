"""Job configuration: YAML files validated into immutable Pydantic models."""

import re
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from harvester.exporters import exporter_registry
from harvester.plugins import PluginNotFoundError
from harvester.transforms import parse_transform, transform_registry

DEFAULT_USER_AGENT = "Mozilla/5.0 (compatible; harvester/0.1)"

_PIPE_RE = re.compile(r"\s+\|\s+")


class JobConfigError(Exception):
    """A job file could not be read or is invalid."""


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class FieldSpec(_Model):
    """How to extract one field from an item container.

    Accepts a shorthand string: ``"<css selector> [@attribute] [| transform ...]"``.
    """

    selector: str = Field(min_length=1)
    attr: str | None = None
    many: bool = False
    required: bool = False
    transforms: tuple[str, ...] = ()

    @model_validator(mode="before")
    @classmethod
    def _expand_shorthand(cls, data: Any) -> Any:
        if not isinstance(data, str):
            return data
        selector, *pipes = _PIPE_RE.split(data.strip())
        head, sep, attr = selector.rpartition(" @")
        if sep:
            return {"selector": head.strip(), "attr": attr.strip(), "transforms": pipes}
        return {"selector": selector, "transforms": pipes}

    @field_validator("transforms")
    @classmethod
    def _transforms_exist(cls, specs: tuple[str, ...]) -> tuple[str, ...]:
        for spec in specs:
            try:
                transform_registry.get(parse_transform(spec)[0])
            except PluginNotFoundError as exc:
                raise ValueError(str(exc)) from None
        return specs


class Pagination(_Model):
    next: str = Field(min_length=1, description="CSS selector of the 'next page' link.")
    max_pages: int = Field(default=10, ge=1, description="Total page budget for the job.")


class HttpSettings(_Model):
    concurrency: int = Field(default=5, ge=1, le=100)
    rate_limit: float | None = Field(default=2.0, gt=0, description="Requests per second.")
    retries: int = Field(default=3, ge=1, le=10, description="Attempts per request.")
    backoff: float = Field(default=0.5, ge=0, description="Base retry delay in seconds.")
    timeout: float = Field(default=20.0, gt=0)
    headers: dict[str, str] = Field(default_factory=lambda: {"User-Agent": DEFAULT_USER_AGENT})


class ExportSpec(_Model):
    format: str
    path: str | None = Field(
        default=None,
        description="File name relative to the output dir; supports {name}, {date}, {timestamp}.",
    )

    @field_validator("format")
    @classmethod
    def _exporter_exists(cls, value: str) -> str:
        try:
            exporter_registry.get(value)
        except PluginNotFoundError as exc:
            raise ValueError(str(exc)) from None
        return value

    @field_validator("path")
    @classmethod
    def _template_is_valid(cls, value: str | None) -> str | None:
        if value is not None:
            try:
                render_path_template(value, name="job", now=datetime.now())
            except (KeyError, IndexError, ValueError) as exc:
                raise ValueError(f"invalid path template {value!r}: {exc!r}") from None
        return value

    def resolve_path(self, job_name: str, output_dir: Path, now: datetime) -> Path:
        extension = exporter_registry.get(self.format).extension
        template = self.path or f"{{name}}.{extension}"
        return output_dir / render_path_template(template, name=job_name, now=now)


def render_path_template(template: str, *, name: str, now: datetime) -> str:
    return template.format(name=name, date=f"{now:%Y-%m-%d}", timestamp=f"{now:%Y%m%d-%H%M%S}")


class JobConfig(_Model):
    name: str = Field(pattern=r"^[\w.-]+$")
    start_urls: tuple[AnyHttpUrl, ...] = Field(min_length=1)
    item: str = Field(min_length=1, description="CSS selector matching one element per item.")
    fields: dict[str, FieldSpec] = Field(min_length=1)
    pagination: Pagination | None = None
    http: HttpSettings = Field(default_factory=HttpSettings)
    exports: tuple[ExportSpec, ...] = ()


def load_job(path: str | Path) -> JobConfig:
    """Read and validate a YAML job file. The job name defaults to the file stem."""
    path = Path(path)
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise JobConfigError(f"Cannot read {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise JobConfigError(f"Invalid YAML in {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise JobConfigError(f"{path}: expected a mapping at the top level")

    raw.setdefault("name", path.stem)
    try:
        return JobConfig.model_validate(raw)
    except ValidationError as exc:
        problems = "\n".join(
            f"  - {'.'.join(str(p) for p in err['loc']) or '<root>'}: {err['msg']}"
            for err in exc.errors()
        )
        raise JobConfigError(f"{path} is invalid:\n{problems}") from exc
