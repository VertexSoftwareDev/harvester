"""Value transforms applied to extracted fields.

In a job file transforms are chained with ``|``; arguments follow a colon::

    price: p.price_color | price
    rating: p.star-rating @class | regex:star-rating (\\w+) | lower

A transform receives the current value and a :class:`TransformContext`. The chain
stops as soon as a transform returns ``None``.
"""

import functools
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin

from harvester.plugins import Registry


@dataclass(frozen=True, slots=True)
class TransformContext:
    url: str
    """URL of the page the value was extracted from."""
    arg: str | None = None
    """Text after the colon in ``name:arg``, if any."""


type Transform = Callable[[Any, TransformContext], Any]

transform_registry: Registry[Transform] = Registry(
    "transform", entry_point_group="harvester.transforms"
)


def parse_transform(spec: str) -> tuple[str, str | None]:
    """Split ``"regex:(\\d+)"`` into ``("regex", "(\\d+)")``."""
    name, sep, arg = spec.partition(":")
    return name.strip(), arg if sep else None


def apply_transforms(value: Any, specs: Sequence[str], url: str) -> Any:
    for spec in specs:
        if value is None:
            break
        name, arg = parse_transform(spec)
        value = transform_registry.get(name)(value, TransformContext(url=url, arg=arg))
    return value


_NUMBER_RE = re.compile(r"[-+]?\d[\d.,\s]*")


def parse_number(text: str) -> float | None:
    """Parse the first number in *text*, tolerating currency symbols and locale formats.

    >>> parse_number("£1,234.50"), parse_number("1.234,50 TL"), parse_number("12,5")
    (1234.5, 1234.5, 12.5)
    """
    match = _NUMBER_RE.search(text)
    if match is None:
        return None
    raw = re.sub(r"\s", "", match.group()).rstrip(".,")
    dot, comma = raw.rfind("."), raw.rfind(",")
    if dot != -1 and comma != -1:
        # Whichever separator comes last is the decimal one.
        thousands, decimal = (",", ".") if dot > comma else (".", ",")
        raw = raw.replace(thousands, "").replace(decimal, ".")
    elif comma != -1:
        # "1,234" / "1,234,567" are thousands; "12,5" is a decimal comma.
        is_thousands = raw.count(",") > 1 or len(raw) - comma - 1 == 3
        raw = raw.replace(",", "" if is_thousands else ".")
    elif raw.count(".") > 1:
        raw = raw.replace(".", "")
    return float(raw)


@transform_registry.register("strip")
def strip(value: Any, ctx: TransformContext) -> str:
    """Trim and collapse whitespace."""
    return " ".join(str(value).split())


@transform_registry.register("lower")
def lower(value: Any, ctx: TransformContext) -> str:
    """Lowercase text."""
    return str(value).lower()


@transform_registry.register("upper")
def upper(value: Any, ctx: TransformContext) -> str:
    """Uppercase text."""
    return str(value).upper()


@transform_registry.register("price")
@transform_registry.register("float")
def to_float(value: Any, ctx: TransformContext) -> float | None:
    """First number in the text as a float ("£1,234.50" -> 1234.5)."""
    if isinstance(value, int | float):
        return float(value)
    return parse_number(str(value))


@transform_registry.register("int")
def to_int(value: Any, ctx: TransformContext) -> int | None:
    """First number in the text as an int ("In stock (22 available)" -> 22)."""
    number = to_float(value, ctx)
    return None if number is None else int(number)


@transform_registry.register("absolute_url")
def absolute_url(value: Any, ctx: TransformContext) -> str:
    """Resolve a relative link against the page URL."""
    return urljoin(ctx.url, str(value).strip())


@functools.lru_cache(maxsize=256)
def _compile(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern)


@transform_registry.register("regex")
def regex(value: Any, ctx: TransformContext) -> str | None:
    """``regex:PATTERN`` - first capture group (or whole match), None if no match."""
    if not ctx.arg:
        raise ValueError("regex transform needs a pattern, e.g. 'regex:(\\d+)'")
    match = _compile(ctx.arg).search(str(value))
    if match is None:
        return None
    return match.group(1) if match.re.groups else match.group(0)
