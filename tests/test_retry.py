import pytest

from harvester.retry import retry


class FakeSleep:
    def __init__(self) -> None:
        self.delays: list[float] = []

    async def __call__(self, delay: float) -> None:
        self.delays.append(delay)


class Flaky:
    def __init__(self, failures: int, exc: type[Exception] = ConnectionError) -> None:
        self.failures = failures
        self.exc = exc
        self.calls = 0

    async def __call__(self, value: int) -> int:
        self.calls += 1
        if self.calls <= self.failures:
            raise self.exc(f"failure {self.calls}")
        return value * 2


async def test_retries_until_success_with_exponential_backoff() -> None:
    sleep, flaky = FakeSleep(), Flaky(failures=3)
    wrapped = retry(attempts=4, base_delay=0.5, jitter=False, sleep=sleep)(flaky)

    assert await wrapped(21) == 42
    assert flaky.calls == 4
    assert sleep.delays == [0.5, 1.0, 2.0]


async def test_delay_is_capped_and_jittered() -> None:
    sleep, flaky = FakeSleep(), Flaky(failures=4)
    wrapped = retry(attempts=5, base_delay=1, max_delay=3, sleep=sleep)(flaky)

    await wrapped(1)

    caps = [1, 2, 3, 3]
    assert all(cap / 2 <= delay <= cap for delay, cap in zip(sleep.delays, caps, strict=True))


async def test_reraises_after_last_attempt() -> None:
    sleep, flaky = FakeSleep(), Flaky(failures=10)
    wrapped = retry(attempts=3, sleep=sleep)(flaky)

    with pytest.raises(ConnectionError, match="failure 3"):
        await wrapped(1)
    assert flaky.calls == 3


async def test_other_exceptions_are_not_retried() -> None:
    sleep, flaky = FakeSleep(), Flaky(failures=1, exc=KeyError)
    wrapped = retry(attempts=3, exceptions=(ConnectionError,), sleep=sleep)(flaky)

    with pytest.raises(KeyError):
        await wrapped(1)
    assert flaky.calls == 1
    assert sleep.delays == []


def test_preserves_metadata() -> None:
    @retry()
    async def fetch_page(url: str) -> str:
        """Docstring survives."""
        return url

    assert fetch_page.__name__ == "fetch_page"
    assert fetch_page.__doc__ == "Docstring survives."


def test_rejects_invalid_attempts() -> None:
    with pytest.raises(ValueError, match="attempts"):
        retry(attempts=0)
