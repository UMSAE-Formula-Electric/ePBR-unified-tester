"""DMM checks that need only test leads and one known resistor.

Each step asks the operator to set the leads up, so they can be run in any
order without the previous step's fixture state mattering.
"""

from __future__ import annotations

from core.decorators import operator_confirm, test_step_result
from core.logger import logger
from core.runner import TestRunner
from instruments.dmm import INVALID_RESULT
from testers.instrument_checkout.config import Defaults, Prompts, Thresholds
from testers.instrument_checkout.utils import (
    measure_dc_volts,
    measure_resistance,
    percent_error,
)
from utils.operator import ask_float


@test_step_result("BENCH_DMM_SHORTED_V", "BENCH_DMM_LEAD_RESISTANCE")
@operator_confirm(Prompts.SHORT_LEADS)
def DMM_SHORTED_LEADS(runner: TestRunner):
    """With the leads shorted, check the DMM's zero and the leads' own resistance.

    The DC reading catches an offset problem. The resistance reading is the test
    leads themselves, which is worth knowing: it's the error floor on every
    low-resistance measurement you'll ever take with them.
    """
    shorted_volts = measure_dc_volts()
    lead_resistance = measure_resistance()

    logger.info(f"Shorted leads: {shorted_volts:.6f} V, {lead_resistance:.4f} ohm")
    if lead_resistance > Thresholds.SHORTED_LEADS_OHMS:
        logger.warning(
            f"{lead_resistance:.2f} ohm is high for a short. Check the leads are really "
            f"touching and are seated in the V/ohm and COM inputs."
        )

    runner.add_result("BENCH_DMM_SHORTED_V", shorted_volts)
    runner.add_result("BENCH_DMM_LEAD_RESISTANCE", lead_resistance)


@test_step_result("BENCH_DMM_OPEN_CIRCUIT")
@operator_confirm(Prompts.OPEN_LEADS)
def DMM_OPEN_LEADS(runner: TestRunner):
    """With nothing connected, resistance should read as an open circuit.

    The 5492B signals over-range with a very large number rather than an error,
    so "open" means "above the threshold" instead of a special value.
    """
    resistance = measure_resistance()
    is_open = resistance == INVALID_RESULT or resistance > Thresholds.OPEN_CIRCUIT_OHMS

    logger.info(f"Open leads read {resistance:.4g} ohm -> {'open' if is_open else 'NOT open'}")

    runner.add_result("BENCH_DMM_OPEN_CIRCUIT", is_open)


@test_step_result("BENCH_DMM_RESISTOR_ERROR")
@operator_confirm(Prompts.FIT_RESISTOR)
def DMM_KNOWN_RESISTOR(runner: TestRunner):
    """Measure a resistor the operator identifies, and report the error.

    The resistor's value isn't known until run time, so the recorded result is
    the *percentage error* rather than the reading. That way one fixed limit in
    result_details.toml covers any resistor you happen to have in the drawer.

    The resistor's own tolerance is only logged, not enforced: a 5% resistor
    reading 3% high tells you about the resistor, not the meter.
    """
    nominal = ask_float(
        Prompts.RESISTOR_VALUE, default=Defaults.RESISTOR_OHMS, minimum=0.001
    )
    tolerance_pct = ask_float(
        Prompts.RESISTOR_TOLERANCE, default=Defaults.RESISTOR_TOLERANCE_PCT, minimum=0.0
    )

    measured = measure_resistance()
    error_pct = percent_error(measured, nominal)

    logger.info(
        f"Resistor: marked {nominal:g} ohm +/-{tolerance_pct:g}%, "
        f"measured {measured:.4f} ohm ({error_pct:+.3f}%)"
    )
    if abs(error_pct) > tolerance_pct:
        logger.warning(
            f"Outside the resistor's own {tolerance_pct:g}% tolerance. That's usually the "
            f"resistor rather than the meter - check against a second resistor before "
            f"suspecting the DMM."
        )

    runner.context["resistor_nominal_ohms"] = nominal
    runner.context["resistor_measured_ohms"] = measured

    runner.add_result("BENCH_DMM_RESISTOR_ERROR", error_pct)
