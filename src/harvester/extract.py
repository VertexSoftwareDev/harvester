"""Turn HTML into structured items with CSS selectors."""

import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urljoin

from selectolax.parser import HTMLParser, Node

from harvester.config import FieldSpec, JobConfig
from harvester.item import Item
from harvester.transforms import apply_transforms

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ParsedPage:
    items: list[Item] = field(default_factory=list)
    next_urls: list[str] = field(default_factory=list)
    skipped: int = 0
    """Item containers dropped because a required field was empty."""


def parse_page(html: str, url: str, job: JobConfig) -> ParsedPage:
    tree = HTMLParser(html)
    result = ParsedPage()
    for container in tree.css(job.item):
        item = extract_item(container, url, job.fields)
        if item is None:
            result.skipped += 1
        else:
            result.items.append(item)

    if job.pagination is not None:
        for link in tree.css(job.pagination.next):
            if href := link.attributes.get("href"):
                result.next_urls.append(urljoin(url, href))
    return result


def extract_item(container: Node, url: str, fields: Mapping[str, FieldSpec]) -> Item | None:
    item: Item = {}
    for name, spec in fields.items():
        value = extract_field(container, url, spec)
        if spec.required and value in (None, "", []):
            logger.debug("Skipping item on %s: required field %r is empty", url, name)
            return None
        item[name] = value
    return item


def extract_field(container: Node, url: str, spec: FieldSpec) -> Any:
    if spec.many:
        values = (
            apply_transforms(_raw_value(node, spec.attr), spec.transforms, url)
            for node in container.css(spec.selector)
        )
        return [value for value in values if value is not None]

    node = container.css_first(spec.selector)
    if node is None:
        return None
    return apply_transforms(_raw_value(node, spec.attr), spec.transforms, url)


def _raw_value(node: Node, attr: str | None) -> str | None:
    if attr is None:
        text: str = node.text(deep=True, separator=" ", strip=True)
        return text
    value: str | None = node.attributes.get(attr)
    return value
