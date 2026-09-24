"""Helpers shared by the instrument checkout steps."""

from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Iterator, Optional, Tuple

from core.logger import logger
from instruments.dmm import DMM, INVALID_RESULT, Function
from instruments.function_generator import FG_Setting, FunctionGenerator
from testers.instrument_checkout.config import (
    DOUBLED_RATIO_TOLERANCE,
    DOUBLED_READING_RATIO,
    FG_CHANNEL,
    Samples,
    Times,
)

# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------


def identity_looks_right(idn: str, hints: Tuple[str, ...]) -> bool:
    """Does this *IDN? string mention anything we'd expect from the instrument?"""
    upper = idn.upper()
    return any(hint.upper() in upper for hint in hints)


def report_identity(name: str, idn: str, hints: Tuple[str, ...]) -> None:
    """Log an identity string, loudly enough that it's easy to copy into the limits."""
    if not idn:
        logger.error(f"{name}: no response to *IDN?")
        return

    logger.info(f"{name} identifies as: {idn}")
    if not identity_looks_right(idn, hints):
        logger.warning(
            f"{name}: that doesn't mention any of {hints}. If it's the right instrument, "
            f"tighten the regex in result_details.toml to match what it actually reports."
        )


# ---------------------------------------------------------------------------
# Function generator
# ---------------------------------------------------------------------------


@contextmanager
def drive(setting: FG_Setting) -> Iterator[FunctionGenerator]:
    """Program a waveform, switch the output on, and guarantee it goes off after.

    Yields the open FunctionGenerator so the caller can keep adjusting it
    without reopening the connection:

        with drive(FG_Settings.SQUARE_0_5V) as fg:
            fg.set_duty_cycle(25)
    """
    with FunctionGenerator(off_on_exit=True) as fg:
        fg.apply_setting(setting, channel=FG_CHANNEL, enable=True)
        time.sleep(Times.FG_SETTLE_S)
        yield fg


def drive_dc(fg: FunctionGenerator, voltage: float) -> None:
    """Put a flat DC level on the FG output and let it settle."""
    fg.set_dc_level(voltage, channel=FG_CHANNEL)
    time.sleep(Times.FG_SETTLE_S)


def stop_fg() -> None:
    """Switch every FG output off. Safe to call when the FG isn't reachable."""
    try:
        with FunctionGenerator(off_on_exit=False) as fg:
            fg.disable_all_outputs()
    except Exception as e:
        logger.warning(f"Could not turn the function generator off: {e}")


# ---------------------------------------------------------------------------
# DMM
# ---------------------------------------------------------------------------


def measure(
    function: Function,
    samples: int = Samples.DC,
    settle_s: float = Times.DMM_FUNCTION_SETTLE_S,
) -> float:
    """Average a few readings on one DMM function.

    Opens and closes the DMM each time. That's slower than holding it open, but
    it keeps each step independent, which matters more while you're finding out
    how the instruments behave.
    """
    with DMM() as dmm:
        dmm.set_function(function)
        time.sleep(settle_s)
        return dmm.measure_average(function, samples=samples, delay_s=Times.BETWEEN_SAMPLES_S)


def measure_dc_volts(samples: int = Samples.DC) -> float:
    return measure(Function.DC_VOLTAGE, samples=samples)


def measure_ac_volts(samples: int = Samples.AC) -> float:
    return measure(Function.AC_VOLTAGE, samples=samples, settle_s=Times.AC_SETTLE_S)


def measure_resistance(samples: int = Samples.RESISTANCE) -> float:
    return measure(Function.RESISTANCE, samples=samples)


def measure_frequency(samples: int = Samples.FREQUENCY) -> float:
    return measure(Function.FREQUENCY, samples=samples, settle_s=Times.AC_SETTLE_S)


# ---------------------------------------------------------------------------
# Comparing the two
# ---------------------------------------------------------------------------


def percent_error(measured: float, expected: float) -> float:
    """Signed error as a percentage of the expected value.

    Reporting the error rather than the raw reading lets one limit cover a
    measurement whose expected value is only known at run time - the resistor
    check, where the operator types in the value.
    """
    if expected == 0:
        raise ValueError("percent_error needs a non-zero expected value")
    return round((measured - expected) / abs(expected) * 100.0, 4)


def warn_if_doubled(measured: float, expected: float) -> bool:
    """Flag the classic FG mistake: output set for 50 ohm while driving high-Z.

    Every voltage comes out twice what was asked for. It looks like a broken
    instrument and it's really a one-line setting, so it's worth naming
    explicitly the moment the numbers look like this.
    """
    if expected == 0 or measured == INVALID_RESULT:
        return False

    ratio = measured / expected
    doubled = abs(ratio - DOUBLED_READING_RATIO) <= DOUBLED_RATIO_TOLERANCE
    if doubled:
        logger.error(
            f"Reading is {ratio:.2f}x the programmed level. The function generator is "
            f"almost certainly set for a 50 ohm load while driving the DMM's high impedance. "
            f"Set its output load to high-Z (config/station.toml: default_load = \"HZ\")."
        )
    return doubled


def describe(measured: float, expected: float, units: str = "") -> str:
    """One-line comparison for the log."""
    if measured == INVALID_RESULT:
        return f"no reading (expected {expected}{units})"
    try:
        error = f"{percent_error(measured, expected):+.2f}%"
    except ValueError:
        error = f"{measured - expected:+.4f}{units}"
    return f"{measured:.4f}{units} vs expected {expected:.4f}{units} ({error})"


def worst_error(errors: list, default: Optional[float] = None) -> float:
    """Largest absolute error in a sweep - the number the limit is applied to."""
    if not errors:
        return default if default is not None else INVALID_RESULT
    return round(max(errors, key=abs), 6)
