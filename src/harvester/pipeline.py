"""Crawl orchestration: pagination, concurrency, stats and export."""

import asyncio
import logging
import time
from collections.abc import AsyncGenerator, Sequence
from contextlib import aclosing
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import httpx

from harvester.config import ExportSpec, JobConfig
from harvester.exporters import exporter_registry
from harvester.extract import ParsedPage, parse_page
from harvester.fetcher import Fetcher
from harvester.item import Item

logger = logging.getLogger(__name__)

DEFAULT_EXPORTS = (ExportSpec(format="json"),)


@dataclass(slots=True)
class CrawlStats:
    pages_ok: int = 0
    pages_failed: int = 0
    items: int = 0
    items_skipped: int = 0
    started_at: float = field(default_factory=time.perf_counter)
    finished_at: float | None = None

    @property
    def elapsed(self) -> float:
        end = self.finished_at if self.finished_at is not None else time.perf_counter()
        return end - self.started_at


class Crawler:
    """Breadth-first crawl of a job's start URLs and their pagination links.

    Each "level" of pages is fetched concurrently (bounded by the job's HTTP
    settings); items are yielded in page order, so output is deterministic.
    """

    def __init__(self, job: JobConfig, *, client: httpx.AsyncClient | None = None) -> None:
        self.job = job
        self.stats = CrawlStats()
        self._client = client

    async def crawl(self) -> AsyncGenerator[Item]:
        job = self.job
        self.stats = CrawlStats()
        frontier = list(dict.fromkeys(str(url) for url in job.start_urls))
        page_budget = job.pagination.max_pages if job.pagination else len(frontier)
        seen = set(frontier)
        scheduled = 0

        async with Fetcher(job.http, client=self._client) as fetcher:
            try:
                while frontier and scheduled < page_budget:
                    batch = frontier[: page_budget - scheduled]
                    scheduled += len(batch)
                    pages = await asyncio.gather(*(self._process(fetcher, url) for url in batch))

                    frontier = []
                    for page in pages:
                        if page is None:
                            continue
                        self.stats.items_skipped += page.skipped
                        for item in page.items:
                            self.stats.items += 1
                            yield item
                        for link in page.next_urls:
                            if link not in seen:
                                seen.add(link)
                                frontier.append(link)
            finally:
                self.stats.finished_at = time.perf_counter()

    async def _process(self, fetcher: Fetcher, url: str) -> ParsedPage | None:
        try:
            page = await fetcher.get(url)
        except httpx.HTTPError as exc:
            self.stats.pages_failed += 1
            logger.warning("Giving up on %s: %s", url, exc)
            return None
        self.stats.pages_ok += 1
        parsed = parse_page(page.text, page.url, self.job)
        logger.info("%s -> %d items", url, len(parsed.items))
        return parsed


@dataclass(frozen=True, slots=True)
class RunReport:
    job: str
    stats: CrawlStats
    outputs: tuple[Path, ...]


async def run_job(
    job: JobConfig,
    *,
    exports: Sequence[ExportSpec] | None = None,
    output_dir: Path = Path("output"),
    client: httpx.AsyncClient | None = None,
    now: datetime | None = None,
) -> RunReport:
    """Crawl *job* and write the items with every configured exporter."""
    crawler = Crawler(job, client=client)
    async with aclosing(crawler.crawl()) as stream:
        items = [item async for item in stream]

    outputs: list[Path] = []
    if crawler.stats.pages_ok == 0:
        # Nothing was fetched; empty files would look like a successful run.
        logger.error("Every page failed, skipping exports for %s", job.name)
        return RunReport(job=job.name, stats=crawler.stats, outputs=())

    now = now or datetime.now()
    specs = exports if exports is not None else (job.exports or DEFAULT_EXPORTS)
    for spec in specs:
        path = spec.resolve_path(job.name, output_dir, now)
        path.parent.mkdir(parents=True, exist_ok=True)
        exporter = exporter_registry.get(spec.format)()
        await asyncio.to_thread(exporter.export, items, path)
        logger.info("Wrote %d items to %s", len(items), path)
        outputs.append(path)

    return RunReport(job=job.name, stats=crawler.stats, outputs=tuple(outputs))
