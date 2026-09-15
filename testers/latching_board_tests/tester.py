"""Top-level test steps for the latching board.

Every function here whose name appears in parts.toml is a runnable step. The
runner finds it by name, in this file first and then anywhere under tests/.

The shape of a step:

    @test_step_result("RESULT_ID", ...)   # names every result it must produce
    @with_psu(PSU_Settings.NOMINAL_12V)   # setup/teardown as decorators
    def STEP_NAME(runner: TestRunner):
        measured = ...                    # do the measurement
        runner.add_result("RESULT_ID", measured)   # report it; limits decide pass/fail

A step never decides pass/fail itself. It measures and reports; the limits in
result_details.toml do the judging. That keeps the limits reviewable in one
place and stops "it passes now" edits from hiding in test logic.
"""

from __future__ import annotations

from core.decorators import test_step_result, with_psu
from core.logger import logger
from core.runner import TestRunner
from instruments.psu import PSU
from testers.latching_board_tests.config import (
    PSU_Settings,
    Relays,
    SerialCommands,
    Times,
)
from testers.latching_board_tests.utils import (
    bootup_setup,
    measure_voltage_at,
    reset_fixture,
)
from utils.serial_device import SerialDevices, SerialManager


@test_step_result("LB_FIXTURE_READY")
def SETUP(runner: TestRunner):
    """Put the bench in a known state before anything is measured.

    Runs first in every part number's step list. It makes the run repeatable:
    a previous failed run cannot leave a rail up or a relay latched.
    """
    reset_fixture()
    logger.info("Fixture reset: rails off, waveform off, relays released")
    runner.add_result("LB_FIXTURE_READY", True)


@test_step_result("LB_QUIESCENT_CURRENT", "LB_SUPPLY_VOLTAGE")
@with_psu(PSU_Settings.CURRENT_LIMITED)
def POWER_ON_CHECK(runner: TestRunner):
    """First power-up, current limited.

    The supply is limited well below the board's fault current, so a short or a
    backwards part trips the limit instead of damaging the board. Current is
    read before anything else is switched on, so it reflects the quiescent draw.
    """
    with PSU(off_on_exit=False) as psu:
        quiescent_current = psu.measure_current()

    supply_voltage = measure_voltage_at(Relays.SUPPLY_SENSE)

    runner.add_result("LB_QUIESCENT_CURRENT", quiescent_current)
    runner.add_result("LB_SUPPLY_VOLTAGE", supply_voltage)


@test_step_result("LB_CONSOLE_RESPONDS", "LB_FIRMWARE_VERSION")
@with_psu(PSU_Settings.NOMINAL_12V)
def FIRMWARE_CHECK(runner: TestRunner):
    """Confirm the board boots and reports the firmware version we expect."""
    console_ok = bootup_setup()
    runner.add_result("LB_CONSOLE_RESPONDS", console_ok)

    version = ""
    if console_ok:
        with SerialManager(SerialDevices.DUT) as ser:
            try:
                info = ser.send_command_and_parse(
                    SerialCommands.VERSION, timeout=Times.SERIAL_TIMEOUT_S
                )
                version = info.version
            except ValueError as e:
                # A parse failure is a real result, not a crash: record the
                # empty version and let the limit in result_details.toml fail it.
                logger.error(f"Could not read the firmware version: {e}")

    runner.add_result("LB_FIRMWARE_VERSION", version)


@test_step_result("LB_TEARDOWN_SAFE")
def TEARDOWN(runner: TestRunner):
    """Leave the bench safe whatever happened earlier.

    Runs last in every part number's step list, so the board can be unplugged
    without anything live.
    """
    reset_fixture()
    runner.add_result("LB_TEARDOWN_SAFE", True)
