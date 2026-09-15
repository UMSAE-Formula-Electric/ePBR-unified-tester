"""Latch behaviour steps.

Steps in tests/ work exactly like the ones in tester.py - the runner searches
both. Split them into files (and subfolders, any depth) by subsystem once
tester.py starts getting long.

These four steps are written to be worked examples of the patterns you'll
reuse: measuring through the relay bank, driving an input with the function
generator, cross-checking firmware against the pin, and sweeping a threshold.
Adapt them once the real board is on the bench.
"""

from __future__ import annotations

import time

from core.decorators import requires_results, test_step_result, with_fg, with_psu
from core.logger import logger
from core.results import DEFAULT_RESULT
from core.runner import TestRunner
from instruments.dmm import Function
from testers.latching_board_tests.config import (
    FG_Settings,
    LatchState,
    PSU_Settings,
    Relays,
    Thresholds,
    Times,
)
from testers.latching_board_tests.utils import (
    clear_latch,
    latch_is_electrically_set,
    measure_at,
    measure_voltage_at,
    read_latch_state,
    sample_at,
    set_latch,
)
from utils.common import frange, is_toggling
from utils.timer import measure_duration


@test_step_result("LB_COIL_RESISTANCE")
@with_psu(PSU_Settings.NOMINAL_12V)
def COIL_RESISTANCE_TEST(runner: TestRunner):
    """Measure the latch coil, as a check for an open or shorted winding.

    Resistance is read with the coil undriven - driving it first would put the
    coil's own current through the DMM's ohms source and give a meaningless number.
    """
    resistance = measure_at(Relays.COIL_SENSE, Function.RESISTANCE, samples=3)
    runner.add_result("LB_COIL_RESISTANCE", resistance)


@test_step_result("LB_LATCH_SETS", "LB_LATCH_CLEARS", "LB_LATCH_OUTPUT_V")
@with_psu(PSU_Settings.NOMINAL_12V)
def LATCH_SET_CLEAR_TEST(runner: TestRunner):
    """Set the latch, then clear it, checking firmware and pin agree each time.

    Reading both the console state and the output pin catches the case where
    firmware believes the latch moved but the driver stage didn't follow.
    """
    set_latch()
    state_after_set = read_latch_state()
    output_voltage = measure_voltage_at(Relays.LATCH_SENSE)
    pin_high = output_voltage >= Thresholds.LOGIC_HIGH_V
    set_ok = state_after_set == LatchState.LATCHED and pin_high

    if state_after_set == LatchState.LATCHED and not pin_high:
        logger.error(f"Firmware reports LATCHED but the output pin reads {output_voltage:.3f}V")

    clear_latch()
    state_after_clear = read_latch_state()
    cleared_voltage = measure_voltage_at(Relays.LATCH_SENSE)
    clear_ok = state_after_clear == LatchState.UNLATCHED and cleared_voltage <= Thresholds.LOGIC_LOW_V

    runner.add_result("LB_LATCH_SETS", set_ok)
    runner.add_result("LB_LATCH_CLEARS", clear_ok)
    runner.add_result("LB_LATCH_OUTPUT_V", output_voltage)


@test_step_result("LB_TRIGGER_RESPONDS", "LB_LATCH_ACTUATE_TIME")
@with_psu(PSU_Settings.NOMINAL_12V)
@with_fg(FG_Settings.TRIGGER_5V_1HZ)
def TRIGGER_INPUT_TEST(runner: TestRunner):
    """Drive the trigger input with the FG and check the latch follows.

    The waveform is slow (1 Hz) on purpose: it can be followed with the DMM
    through the relay bank, no scope needed.
    """
    clear_latch()

    samples = sample_at(Relays.LATCH_SENSE, Function.DC_VOLTAGE, samples=40, delay_s=0.05)
    responds = is_toggling(
        samples,
        low=Thresholds.LOGIC_LOW_V,
        high=Thresholds.LOGIC_HIGH_V,
        min_transitions=3,
    )
    logger.debug(f"Latch output over 2s: min={min(samples):.3f}V max={max(samples):.3f}V")

    with measure_duration("latch actuation") as elapsed:
        set_latch()
        actuated = latch_is_electrically_set()
    actuate_time = elapsed() if actuated else DEFAULT_RESULT

    runner.add_result("LB_TRIGGER_RESPONDS", responds)
    runner.add_result("LB_LATCH_ACTUATE_TIME", actuate_time)


@test_step_result("LB_TRIGGER_THRESHOLD_V")
@requires_results("LB_TRIGGER_RESPONDS")
@with_psu(PSU_Settings.NOMINAL_12V)
@with_fg(FG_Settings.OFF)
def TRIGGER_THRESHOLD_TEST(runner: TestRunner):
    """Find the voltage at which the trigger input actually fires.

    Walks the FG's DC level up until the latch sets, and reports the level that
    did it. @requires_results skips this step when the basic trigger test never
    passed - no point hunting for a threshold on an input that doesn't respond.
    """
    from instruments.function_generator import FunctionGenerator

    threshold = DEFAULT_RESULT

    with FunctionGenerator(off_on_exit=True) as fg:
        fg.enable_output()

        for level in frange(0.5, 5.0, 0.1):
            clear_latch()
            fg.set_dc_level(level)
            time.sleep(Times.LATCH_ACTUATE_S)

            if latch_is_electrically_set():
                threshold = level
                logger.info(f"Trigger fired at {level:.2f}V")
                break
        else:
            logger.error("The latch never fired across the 0.5-5.0V sweep")

    runner.add_result("LB_TRIGGER_THRESHOLD_V", threshold)
