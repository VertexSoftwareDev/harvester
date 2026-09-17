import asyncio

import pytest

from harvester.ratelimit import RateLimiter


class FakeClock:
    """A clock that only moves when someone sleeps."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    async def sleep(self, delay: float) -> None:
        self.sleeps.append(delay)
        self.now += delay


async def test_spaces_out_requests() -> None:
    clock = FakeClock()
    limiter = RateLimiter(rate=2, clock=clock, sleep=clock.sleep)

    for _ in range(3):
        await limiter.acquire()

    assert clock.sleeps == pytest.approx([0.5, 0.5])
    assert clock.now == pytest.approx(1.0)


async def test_allows_bursts_then_throttles() -> None:
    clock = FakeClock()
    limiter = RateLimiter(rate=10, burst=3, clock=clock, sleep=clock.sleep)

    for _ in range(4):
        async with limiter:
            pass

    assert clock.sleeps == pytest.approx([0.1])


async def test_tokens_refill_while_idle() -> None:
    clock = FakeClock()
    limiter = RateLimiter(rate=1, burst=2, clock=clock, sleep=clock.sleep)
    await limiter.acquire()
    await limiter.acquire()

    clock.now += 5  # idle long enough to refill, but never above burst

    await limiter.acquire()
    await limiter.acquire()
    assert clock.sleeps == []


async def test_concurrent_callers_are_serialized() -> None:
    clock = FakeClock()
    limiter = RateLimiter(rate=4, clock=clock, sleep=clock.sleep)
    finished: list[float] = []

    async def worker() -> None:
        await limiter.acquire()
        finished.append(clock.now)

    await asyncio.gather(*(worker() for _ in range(5)))

    assert finished == pytest.approx([0, 0.25, 0.5, 0.75, 1.0])


@pytest.mark.parametrize(("rate", "burst"), [(0, 1), (-1, 1), (1, 0)])
def test_rejects_invalid_arguments(rate: float, burst: int) -> None:
    with pytest.raises(ValueError, match="must be"):
        RateLimiter(rate=rate, burst=burst)
