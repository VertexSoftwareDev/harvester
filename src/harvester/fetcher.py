"""HTTP layer: connection pooling, concurrency limit, rate limiting and retries."""

import asyncio
import ssl
from dataclasses import dataclass
from typing import Self

import httpx
import truststore

from harvester.config import HttpSettings
from harvester.ratelimit import RateLimiter
from harvester.retry import retry

RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})


class RetryableStatusError(httpx.HTTPStatusError):
    """A response status that is worth retrying (throttling, server errors)."""


@dataclass(frozen=True, slots=True)
class Page:
    url: str
    """Final URL, after redirects."""
    status: int
    text: str


class Fetcher:
    """Fetch pages politely. Owns its HTTP client unless one is passed in."""

    def __init__(self, settings: HttpSettings, *, client: httpx.AsyncClient | None = None) -> None:
        self._settings = settings
        self._owns_client = client is None
        # The OS trust store works behind corporate proxies and antivirus TLS inspection,
        # where certifi's bundled CA list fails.
        self._client = client or httpx.AsyncClient(
            follow_redirects=True, verify=truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        )
        self._semaphore = asyncio.Semaphore(settings.concurrency)
        self._limiter = RateLimiter(settings.rate_limit) if settings.rate_limit else None
        self._get_with_retry = retry(
            attempts=settings.retries,
            base_delay=settings.backoff,
            exceptions=(httpx.TransportError, RetryableStatusError),
        )(self._get_once)

    async def get(self, url: str) -> Page:
        """GET *url*; raises :class:`httpx.HTTPError` once retries are exhausted."""
        return await self._get_with_retry(url)

    async def _get_once(self, url: str) -> Page:
        # Backoff sleeps happen outside the semaphore, so a retrying request
        # doesn't block a concurrency slot.
        async with self._semaphore:
            if self._limiter is not None:
                await self._limiter.acquire()
            response = await self._client.get(
                url, headers=self._settings.headers, timeout=self._settings.timeout
            )
        if response.status_code in RETRYABLE_STATUS:
            raise RetryableStatusError(
                f"HTTP {response.status_code} for {url}",
                request=response.request,
                response=response,
            )
        response.raise_for_status()
        return Page(url=str(response.url), status=response.status_code, text=response.text)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()
