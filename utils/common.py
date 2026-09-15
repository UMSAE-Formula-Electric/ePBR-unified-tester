"""Small numeric and timing helpers that show up in nearly every test step."""

from __future__ import annotations

import statistics
import time
from typing import Callable, Iterable, Iterator, List, Optional, Sequence

from core.logger import logger


def is_within_tolerance(value: float, expected: float, tolerance: float) -> bool:
    """Absolute tolerance check, logged so a failure is readable in the log."""
    low, high = expected - tolerance, expected + tolerance
    result = abs(value - expected) <= tolerance
    logger.debug(f"{low:.3f} <= {value:.3f} <= {high:.3f} -> {'ok' if result else 'out of tolerance'}")
    return result


def is_within_percent(value: float, expected: float, percent: float) -> bool:
    """Relative tolerance, e.g. is_within_percent(measured, 12.0, 5) for +/-5%."""
    if expected == 0:
        return abs(value) <= percent / 100.0
    return is_within_tolerance(value, expected, abs(expected) * percent / 100.0)


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def frange(start: float, stop: float, step: float, precision: int = 6) -> Iterator[float]:
    """range() for floats, counting in both directions without accumulating error.

    Stepping a rail voltage to find a threshold:

        for voltage in frange(3.0, 5.0, 0.1):
            psu.set_voltage(voltage)
    """
    if step == 0:
        raise ValueError("step cannot be 0")

    direction = 1 if stop > start else -1
    step = abs(step) * direction

    count = 0
    while True:
        value = start + count * step
        if (value - stop) * direction >= 0:
            break
        yield round(value, precision)
        count += 1


def wait_until(
    condition: Callable[[], bool],
    timeout_s: float = 10.0,
    poll_s: float = 0.1,
    description: str = "condition",
) -> bool:
    """Poll until `condition()` is true or the timeout expires.

    Prefer this over a bare sleep: it returns as soon as the DUT is ready, so
    the whole test suite stays fast, and it says so in the log when it doesn't.
    """
    start = time.time()
    while time.time() - start < timeout_s:
        try:
            if condition():
                logger.debug(f"'{description}' met after {time.time() - start:.2f}s")
                return True
        except Exception as e:
            logger.debug(f"While waiting for '{description}': {e}")
        time.sleep(poll_s)

    logger.warning(f"Timed out after {timeout_s}s waiting for '{description}'")
    return False


def wait_for_stable(
    read: Callable[[], float],
    tolerance: float,
    settle_s: float = 1.0,
    timeout_s: float = 10.0,
    poll_s: float = 0.1,
) -> Optional[float]:
    """Wait for a reading to hold steady, then return it.

    'Steady' means every sample stays within `tolerance` of the first one for
    `settle_s`. Returns None if it never settles - a thermal or charging value
    that won't settle is itself a finding.
    """
    start = time.time()

    while time.time() - start < timeout_s:
        reference = read()
        settle_start = time.time()
        stable = True

        while time.time() - settle_start < settle_s:
            if abs(read() - reference) > tolerance:
                stable = False
                break
            time.sleep(poll_s)

        if stable:
            logger.debug(f"Reading settled at {reference:.3f} after {time.time() - start:.2f}s")
            return reference

    logger.warning(f"Reading never settled within {tolerance} over {timeout_s}s")
    return None


def average(read: Callable[[], float], samples: int = 5, delay_s: float = 0.05) -> float:
    """Mean of N calls to `read` - quiets a noisy measurement."""
    values = sample(read, samples=samples, delay_s=delay_s)
    return round(statistics.fmean(values), 6) if values else 0.0


def sample(read: Callable[[], float], samples: int = 5, delay_s: float = 0.05) -> List[float]:
    values = []
    for _ in range(samples):
        values.append(read())
        if delay_s:
            time.sleep(delay_s)
    return values


def peak_to_peak(values: Sequence[float]) -> float:
    """Ripple, in the same units as the samples."""
    return round(max(values) - min(values), 6) if values else 0.0


def all_within(values: Iterable[float], low: float, high: float) -> bool:
    return all(low <= value <= high for value in values)


def any_outside(values: Iterable[float], low: float, high: float) -> bool:
    return any(value < low or value > high for value in values)


def count_transitions(values: Sequence[float], low: float, high: float) -> int:
    """Number of low<->high crossings in a sample series.

    A cheap way to tell a toggling line from a stuck one when you only have a
    DMM: sample fast, then check the crossings.
    """
    transitions = 0
    last_state: Optional[int] = None

    for value in values:
        if value <= low:
            state = 0
        elif value >= high:
            state = 1
        else:
            continue  # in the dead band, not a definite level

        if last_state is not None and state != last_state:
            transitions += 1
        last_state = state

    return transitions


def is_toggling(values: Sequence[float], low: float, high: float, min_transitions: int = 3) -> bool:
    return count_transitions(values, low, high) >= min_transitions
