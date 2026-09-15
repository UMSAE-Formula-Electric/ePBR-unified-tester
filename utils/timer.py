"""Timing helpers for measurements that need repeating or bounding."""

from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Callable, Iterator

from core.logger import logger


def ave_function_result(func: Callable[[], float], total_count: int = 1, time_between: float = 0.0) -> float:
    """Mean of N calls, rounded to 3 dp. Kept name-compatible with the work framework."""
    if total_count <= 0:
        raise ValueError("total_count must be at least 1")

    total = 0.0
    for _ in range(total_count):
        total += func()
        if time_between:
            time.sleep(time_between)

    return round(total / total_count, 3)


@contextmanager
def measure_duration(description: str = "operation") -> Iterator[Callable[[], float]]:
    """Time a block. The yielded callable gives the elapsed seconds.

        with measure_duration("latch actuation") as elapsed:
            fire_latch()
        runner.add_result("LB_LATCH_TIME", elapsed())
    """
    start = time.time()
    finished: list[float] = []

    def elapsed() -> float:
        return finished[0] if finished else time.time() - start

    try:
        yield elapsed
    finally:
        finished.append(time.time() - start)
        logger.debug(f"'{description}' took {finished[0]:.4f}s")


class Stopwatch:
    """Explicit start/stop timing, for when a context manager doesn't fit."""

    def __init__(self) -> None:
        self.start_time = time.time()

    def reset(self) -> None:
        self.start_time = time.time()

    def elapsed(self) -> float:
        return time.time() - self.start_time

    def expired(self, timeout_s: float) -> bool:
        return self.elapsed() >= timeout_s
