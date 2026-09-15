"""Helpers shared by the latching board's test steps.

Anything used by more than one step belongs here: fixture sequencing, board
bring-up, measurement routines that involve more than one instrument. Steps
should read as a short list of intentions, with the mechanics down here.
"""

from __future__ import annotations

import time
from typing import List, Optional

from core.logger import logger
from instruments.dmm import DMM, Function
from instruments.psu import PSU
from instruments.relay import RelayBank
from testers.latching_board_tests.config import (
    PSU_Settings,
    Relays,
    SerialCommands,
    Thresholds,
    Times,
)
from utils.common import wait_until
from utils.serial_device import SerialDevices, SerialManager

# ---------------------------------------------------------------------------
# Board bring-up
# ---------------------------------------------------------------------------


def power_cycle(off_time_s: float = Times.POWER_CYCLE_S, boot_time_s: float = Times.BOOTUP_S) -> None:
    """Drop the rail, bring it back, wait for the board to boot."""
    logger.debug("Power cycling the board")
    with PSU(off_on_exit=False) as psu:
        psu.disable_output()
        time.sleep(off_time_s)
        psu.apply(PSU_Settings.NOMINAL_12V)
    time.sleep(boot_time_s)


def wait_for_console(timeout_s: float = Times.SERIAL_BOOT_TIMEOUT_S) -> bool:
    """Poll the console until it answers, so steps don't guess at boot time."""

    def console_responds() -> bool:
        with SerialManager(SerialDevices.DUT, timeout=Times.SERIAL_TIMEOUT_S) as ser:
            return bool(ser.send_command(SerialCommands.ENTER, timeout=Times.SERIAL_TIMEOUT_S))

    return wait_until(console_responds, timeout_s=timeout_s, description="DUT console")


def bootup_setup(power_cycle_first: bool = True) -> bool:
    """Standard start-of-step state: board powered, console answering, relays released."""
    if power_cycle_first:
        power_cycle()

    with RelayBank() as relay:
        relay.all_closed()

    return wait_for_console()


# ---------------------------------------------------------------------------
# Measurement through the relay bank
# ---------------------------------------------------------------------------


def measure_at(
    channel: int,
    function: Function = Function.DC_VOLTAGE,
    samples: int = 3,
    settle_s: float = Times.DMM_SETTLE_S,
) -> float:
    """Route the DMM to one test point and take an averaged reading.

    Opening exactly one channel keeps the DMM from ever seeing two nodes at
    once, which is the failure mode that quietly corrupts readings.
    """
    with RelayBank() as relay:
        relay.open_only(channel, settle_s=Times.RELAY_SETTLE_S)
        time.sleep(settle_s)

        with DMM() as dmm:
            return dmm.measure_average(function, samples=samples)


def measure_voltage_at(channel: int, samples: int = 3) -> float:
    return measure_at(channel, Function.DC_VOLTAGE, samples=samples)


def measure_resistance_at(channel: int, samples: int = 3) -> float:
    return measure_at(channel, Function.RESISTANCE, samples=samples)


def sample_at(
    channel: int,
    function: Function = Function.DC_VOLTAGE,
    samples: int = 20,
    delay_s: float = 0.02,
) -> List[float]:
    """A burst of readings at one test point - use it to see ripple or toggling."""
    with RelayBank() as relay:
        relay.open_only(channel, settle_s=Times.RELAY_SETTLE_S)
        with DMM() as dmm:
            return dmm.measure_samples(function, samples=samples, delay_s=delay_s)


def is_continuous_at(channel: int, threshold_ohms: float = Thresholds.CONTINUITY_OHMS) -> bool:
    resistance = measure_resistance_at(channel)
    return 0 <= resistance <= threshold_ohms


def supply_current() -> float:
    """What the board is drawing right now, read from the PSU."""
    with PSU(off_on_exit=False) as psu:
        return psu.measure_current()


# ---------------------------------------------------------------------------
# Latch control
# ---------------------------------------------------------------------------


def set_latch() -> None:
    with SerialManager(SerialDevices.DUT) as ser:
        ser.send_command(SerialCommands.LATCH_SET, timeout=Times.SERIAL_TIMEOUT_S)
    time.sleep(Times.LATCH_ACTUATE_S)


def clear_latch() -> None:
    with SerialManager(SerialDevices.DUT) as ser:
        ser.send_command(SerialCommands.LATCH_CLEAR, timeout=Times.SERIAL_TIMEOUT_S)
    time.sleep(Times.LATCH_ACTUATE_S)


def read_latch_state() -> Optional[str]:
    """The board's own view of the latch, or None if the console didn't answer."""
    with SerialManager(SerialDevices.DUT) as ser:
        response = ser.send_command(SerialCommands.LATCH_STATUS, timeout=Times.SERIAL_TIMEOUT_S)

    status = SerialCommands.LATCH_STATUS.parser.try_parse(response)
    if status is None:
        logger.warning(f"Could not parse latch status from: {response!r}")
        return None
    return status.state  # type: ignore[attr-defined]


def latch_is_electrically_set(
    channel: int = Relays.LATCH_SENSE,
    high_threshold_v: float = Thresholds.LOGIC_HIGH_V,
) -> bool:
    """Confirm the latch at the pin, not just in firmware.

    Worth doing separately from the console reading: a board that reports
    LATCHED while the output pin stays low is exactly the fault a production
    tester exists to catch.
    """
    return measure_voltage_at(channel) >= high_threshold_v


def reset_fixture() -> None:
    """Return the bench to a safe idle state: rails off, waveform off, relays released."""
    from instruments.function_generator import fg_off
    from instruments.psu import psu_off

    try:
        fg_off()
    except Exception as e:
        logger.warning(f"Could not turn the FG off: {e}")
    try:
        psu_off()
    except Exception as e:
        logger.warning(f"Could not turn the PSU off: {e}")
    try:
        with RelayBank() as relay:
            relay.all_closed()
    except Exception as e:
        logger.warning(f"Could not release the relay bank: {e}")
