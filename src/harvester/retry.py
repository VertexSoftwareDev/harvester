"""Async retry decorator with exponential backoff and jitter."""

import asyncio
import functools
import logging
import random
from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)


def retry[**P, R](
    *,
    attempts: int = 3,
    base_delay: float = 0.5,
    max_delay: float = 30.0,
    exceptions: tuple[type[BaseException], ...] = (Exception,),
    jitter: bool = True,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R]]]:
    """Retry an async callable when it raises one of *exceptions*.

    The n-th retry waits ``min(max_delay, base_delay * 2**(n-1))`` seconds, scaled
    into ``[50%, 100%]`` when *jitter* is on so that parallel workers don't retry in
    lockstep. *sleep* is injectable, which keeps tests instant.
    """
    if attempts < 1:
        raise ValueError("attempts must be >= 1")

    def decorator(func: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
        name = getattr(func, "__qualname__", type(func).__qualname__)

        @functools.wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            for attempt in range(1, attempts + 1):
                try:
                    return await func(*args, **kwargs)
                except exceptions as exc:
                    if attempt == attempts:
                        raise
                    delay = min(max_delay, base_delay * 2 ** (attempt - 1))
                    if jitter:
                        delay *= random.uniform(0.5, 1.0)
                    logger.info(
                        "%s failed (%s: %s), retry %d/%d in %.2fs",
                        name,
                        type(exc).__name__,
                        exc,
                        attempt,
                        attempts - 1,
                        delay,
                    )
                    await sleep(delay)
            raise AssertionError("unreachable")

        return wrapper

    return decorator
