"""Helpers shared by the equipment tests."""

from __future__ import annotations

import time
from typing import Optional, Tuple

from config.settings import is_simulated
from core.logger import logger
from instruments.dmm import DMM, INVALID_RESULT, Function
from instruments.function_generator import FunctionGenerator
from testers.equipment_tests.config import Samples, Times

# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------


def identity_looks_right(idn: str, hints: Tuple[str, ...]) -> bool:
    return any(hint.upper() in idn.upper() for hint in hints)


def report_identity(name: str, idn: str, hints: Tuple[str, ...]) -> None:
    """Log an identity string clearly enough to copy into the limits later."""
    if not idn:
        logger.error(f"{name}: no response to *IDN?")
        return

    logger.info(f"{name} identifies as: {idn}")
    if not identity_looks_right(idn, hints):
        logger.warning(
            f"{name}: that doesn't mention any of {hints}. If it is the right instrument, "
            f"tighten the regex in result_details.toml to match what it actually reports."
        )


# ---------------------------------------------------------------------------
# DMM measurement
# ---------------------------------------------------------------------------


def measure(
    function: Function,
    samples: int = Samples.DC,
    settle_s: float = Times.DMM_FUNCTION_SETTLE_S,
    sim_reading: Optional[float] = None,
) -> float:
    """Average a few readings on one DMM function.

    `sim_reading` only has an effect in simulate mode, where it stands in for the
    measurement. It's there because the simulated DMM is a lookup table with one
    canned value per function, and these tests deliberately measure different
    things through the same function - 0 V with the leads shorted, 12 V from the
    supply. Passing the value the step expects lets a dry run exercise the limits
    and the reporting instead of failing on an artefact of the simulator.

    On real hardware this argument is ignored completely.
    """
    if is_simulated() and sim_reading is not None:
        logger.debug(f"[sim] {function.name} -> {sim_reading}")
        return float(sim_reading)

    with DMM() as dmm:
        dmm.set_function(function)
        time.sleep(settle_s)
        return dmm.measure_average(function, samples=samples, delay_s=Times.BETWEEN_SAMPLES_S)


def measure_dc_volts(sim_reading: Optional[float] = None, samples: int = Samples.DC) -> float:
    return measure(Function.DC_VOLTAGE, samples=samples, sim_reading=sim_reading)


def measure_resistance(sim_reading: Optional[float] = None, samples: int = Samples.RESISTANCE) -> float:
    return measure(Function.RESISTANCE, samples=samples, sim_reading=sim_reading)


def read_dmm_identity() -> str:
    """*IDN? from the DMM, or "" if it can't be reached."""
    try:
        with DMM() as dmm:
            return dmm.identify()
    except Exception as e:
        logger.error(f"Could not reach the DMM: {e}")
        return ""


# ---------------------------------------------------------------------------
# Function generator
# ---------------------------------------------------------------------------


def read_fg_identity() -> str:
    """*IDN? from the function generator, or "" if it can't be reached."""
    try:
        with FunctionGenerator(off_on_exit=False) as fg:
            return fg.identify()
    except Exception as e:
        logger.error(f"Could not reach the function generator: {e}")
        return ""


def stop_fg() -> None:
    """Switch every FG output off. Safe to call when the FG isn't reachable."""
    try:
        with FunctionGenerator(off_on_exit=False) as fg:
            fg.disable_all_outputs()
    except Exception as e:
        logger.warning(f"Could not turn the function generator off: {e}")


# ---------------------------------------------------------------------------
# Comparing
# ---------------------------------------------------------------------------


def percent_error(measured: float, expected: float) -> float:
    """Signed error as a percentage of the expected value.

    Recording the error rather than the raw reading means one fixed limit covers
    a measurement whose expected value is only known at run time - the supply
    voltage and the resistor value, both typed in by the operator.
    """
    if expected == 0:
        raise ValueError("percent_error needs a non-zero expected value")
    return round((measured - expected) / abs(expected) * 100.0, 4)


def describe(measured: float, expected: float, units: str = "") -> str:
    """One-line comparison for the log."""
    if measured == INVALID_RESULT:
        return f"no reading (expected {expected}{units})"
    try:
        error = f"{percent_error(measured, expected):+.3f}%"
    except ValueError:
        error = f"{measured - expected:+.4f}{units}"
    return f"{measured:.4f}{units} vs expected {expected:.4f}{units} ({error})"
