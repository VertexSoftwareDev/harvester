"""Token-bucket rate limiter for asyncio."""

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Self


class RateLimiter:
    """Allow on average *rate* acquisitions per second, with bursts up to *burst*.

    Usable directly (``await limiter.acquire()``) or as ``async with limiter:``.
    Waiters are served in FIFO order because the lock is held while sleeping.
    """

    def __init__(
        self,
        rate: float,
        burst: int = 1,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if rate <= 0:
            raise ValueError("rate must be > 0")
        if burst < 1:
            raise ValueError("burst must be >= 1")
        self.rate = rate
        self.burst = burst
        self._clock = clock
        self._sleep = sleep
        self._tokens = float(burst)
        self._updated = clock()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            while True:
                now = self._clock()
                elapsed = now - self._updated
                self._tokens = min(self.burst, self._tokens + elapsed * self.rate)
                self._updated = now
                if self._tokens >= 1:
                    self._tokens -= 1
                    return
                await self._sleep((1 - self._tokens) / self.rate)

    async def __aenter__(self) -> Self:
        await self.acquire()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        return None
