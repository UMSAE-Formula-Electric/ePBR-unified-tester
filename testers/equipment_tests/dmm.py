"""BK Precision 5492B checks.

Run on its own, with only the DMM connected to the PC:

    python main.py run DMM-CHECK -S DMM01

Everything here works by connecting something you already know the value of and
asking whether the meter agrees. You need test leads, a bench supply, and one
resistor. The tests prompt you for each of those as they go, so you can follow
along without reading this first.
"""

from __future__ import annotations

from core.decorators import operator_confirm, test_step_result
from core.logger import logger
from core.runner import TestRunner
from instruments.dmm import INVALID_RESULT
from testers.equipment_tests.config import (
    EXPECTED_DMM_HINTS,
    Defaults,
    Prompts,
    Thresholds,
)
from testers.equipment_tests.utils import (
    describe,
    measure_dc_volts,
    measure_resistance,
    percent_error,
    read_dmm_identity,
    report_identity,
)
from utils.operator import ask_float, confirm


@test_step_result("DMM_RESPONDS", "DMM_IDN")
@operator_confirm(Prompts.DMM_CONNECTED)
def DMM_IDENTITY(runner: TestRunner):
    """Ask the DMM who it is.

    A failure here is nearly always the COM port or the DMM's I/O menu rather
    than the instrument. `python main.py ports` shows what the PC can see.
    """
    idn = read_dmm_identity()
    report_identity("DMM", idn, EXPECTED_DMM_HINTS)

    runner.add_result("DMM_RESPONDS", bool(idn))
    runner.add_result("DMM_IDN", idn)


@test_step_result("DMM_ZERO_V", "DMM_LEAD_RESISTANCE")
@operator_confirm(Prompts.SHORT_LEADS)
def DMM_SHORTED_LEADS(runner: TestRunner):
    """With the leads shorted, check the meter's zero and the leads themselves.

    The voltage reading catches an offset problem. The resistance reading is the
    leads' own resistance, which is worth knowing on its own: it's the error
    floor under every low-resistance measurement you'll take with them.
    """
    zero_volts = measure_dc_volts(sim_reading=0.0002)
    lead_resistance = measure_resistance(sim_reading=0.18)

    logger.info(f"Shorted leads: {zero_volts:.6f} V, {lead_resistance:.4f} ohm")
    if lead_resistance > Thresholds.SHORTED_LEADS_OHMS:
        logger.warning(
            f"{lead_resistance:.2f} ohm is high for a short - check the leads are really "
            f"touching and are seated in the V/ohm and COM inputs."
        )

    runner.add_result("DMM_ZERO_V", zero_volts)
    runner.add_result("DMM_LEAD_RESISTANCE", lead_resistance)


@test_step_result("DMM_OPEN_CIRCUIT")
@operator_confirm(Prompts.OPEN_LEADS)
def DMM_OPEN_LEADS(runner: TestRunner):
    """With nothing connected, resistance should read as an open circuit.

    The 5492B reports an over-range as a very large number rather than an error,
    so "open" means "above the threshold" instead of a special value.
    """
    resistance = measure_resistance(sim_reading=1.2e9)
    is_open = resistance == INVALID_RESULT or resistance > Thresholds.OPEN_CIRCUIT_OHMS

    logger.info(f"Open leads read {resistance:.4g} ohm -> {'open' if is_open else 'NOT open'}")

    runner.add_result("DMM_OPEN_CIRCUIT", is_open)


@test_step_result("DMM_SUPPLY_READING", "DMM_SUPPLY_ERROR")
@operator_confirm(Prompts.CONNECT_SUPPLY)
def DMM_DC_VOLTAGE(runner: TestRunner):
    """Measure a bench supply and check the DMM agrees with what it's set to.

    You type in the supply's setting, so the recorded result is the *percentage
    error* rather than the reading. One fixed limit then covers any supply
    voltage - 12 V today, 5 V or 24 V another day, with nothing to edit.

    The raw reading is recorded too, with a wide sanity limit. That's what
    catches the meter being on the wrong function or range, which a percentage
    error alone can hide.
    """
    set_voltage = ask_float(
        Prompts.SUPPLY_VOLTAGE, default=Defaults.SUPPLY_VOLTS, minimum=0.0
    )

    measured = measure_dc_volts(sim_reading=set_voltage * 1.001)
    error_pct = percent_error(measured, set_voltage) if set_voltage else 0.0

    logger.info(f"Supply: {describe(measured, set_voltage, 'V')}")
    if measured < Thresholds.SUPPLY_SANITY_MIN_V <= set_voltage:
        logger.error(
            "Reading is near zero while the supply is set well above it. Check the supply's "
            "output is actually enabled and the leads are in the V and COM inputs."
        )

    runner.context["supply_set_v"] = set_voltage
    runner.context["supply_measured_v"] = measured

    runner.add_result("DMM_SUPPLY_READING", measured)
    runner.add_result("DMM_SUPPLY_ERROR", error_pct)


@test_step_result("DMM_RESISTOR_ERROR")
@operator_confirm(Prompts.CONNECT_RESISTOR)
def DMM_RESISTANCE(runner: TestRunner):
    """Measure a known resistor and report the error.

    Same pattern as the supply check: the value is only known at run time, so
    the error is what gets recorded and judged.

    The resistor's own tolerance is logged but not enforced. A 5% resistor
    reading 3% high tells you about the resistor, not about the meter.
    """
    nominal = ask_float(
        Prompts.RESISTOR_VALUE, default=Defaults.RESISTOR_OHMS, minimum=0.001
    )
    tolerance_pct = ask_float(
        Prompts.RESISTOR_TOLERANCE, default=Defaults.RESISTOR_TOLERANCE_PCT, minimum=0.0
    )

    measured = measure_resistance(sim_reading=nominal * 1.002)
    error_pct = percent_error(measured, nominal)

    logger.info(
        f"Resistor: marked {nominal:g} ohm +/-{tolerance_pct:g}%, "
        f"measured {measured:.4f} ohm ({error_pct:+.3f}%)"
    )
    if abs(error_pct) > tolerance_pct:
        logger.warning(
            f"Outside the resistor's own {tolerance_pct:g}% tolerance. That's usually the "
            f"resistor rather than the meter - try a second resistor before suspecting the DMM."
        )

    runner.add_result("DMM_RESISTOR_ERROR", error_pct)


@test_step_result("DMM_TEARDOWN_SAFE")
def DMM_TEARDOWN(runner: TestRunner):
    """Have the operator disconnect the supply, so nothing is left live."""
    disconnected = confirm(Prompts.DISCONNECT_SUPPLY, default=True)
    runner.add_result("DMM_TEARDOWN_SAFE", disconnected)
