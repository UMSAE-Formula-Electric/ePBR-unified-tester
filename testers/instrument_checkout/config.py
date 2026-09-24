"""Constants for the bench instrument checkout.

This tester's "DUT" is the bench itself: the BK 4052 function generator and the
BK 5492B DMM. It confirms both talk to the PC, and then cross-checks them
against each other by feeding the FG's output into the DMM.

That cross-check is worth having for its own sake - two independent instruments
agreeing on a voltage is decent evidence both are working - and it's also how
you'll shake out cabling, drivers and SCPI quirks before a real board is
involved.
"""

from __future__ import annotations

from dataclasses import dataclass

from instruments.function_generator import FG_Setting, Waveforms
from utils.serial_device import BaseSerialCommandParser

# ---------------------------------------------------------------------------
# Wiring
# ---------------------------------------------------------------------------

FG_CHANNEL = 1

# The FG's output amplitude depends on what load it thinks it's driving. A DMM
# is effectively an open circuit, so the FG must be set to high-Z. If it is set
# to 50 ohm instead, every voltage below comes out at twice the programmed
# value. `default_load = "HZ"` in config/station.toml handles this, and
# LOOPBACK_DC_LEVELS calls it out explicitly if the readings look doubled.
EXPECTED_LOAD = "HZ"
DOUBLED_READING_RATIO = 2.0
DOUBLED_RATIO_TOLERANCE = 0.15


class Prompts:
    """What the operator gets asked. Kept here so the wording is in one place."""

    BENCH_READY = "Both instruments powered on and connected to this PC by USB?"
    CONNECT_LOOPBACK = (
        f"Connect FG CH{FG_CHANNEL} output to the DMM's V/ohm and COM inputs "
        "(BNC-to-banana, signal to V, shield to COM). Connected?"
    )
    DISCONNECT_LOOPBACK = "Disconnect the FG from the DMM inputs. Done?"
    SHORT_LEADS = "Touch the DMM's two test leads together (or fit the shorting link). Shorted?"
    OPEN_LEADS = "Separate the DMM's test leads so nothing is connected. Open?"
    FIT_RESISTOR = "Connect a known resistor across the DMM's leads. Connected?"
    RESISTOR_VALUE = "Resistor's marked value in ohms"
    RESISTOR_TOLERANCE = "Resistor's marked tolerance in percent"


class Defaults:
    """Auto-answers used when the run is unattended (simulate mode, piped output)."""

    RESISTOR_OHMS = 10_000.0
    RESISTOR_TOLERANCE_PCT = 1.0


# ---------------------------------------------------------------------------
# Function generator settings
# ---------------------------------------------------------------------------


class FG_Settings:
    """Named waveforms fed into the DMM."""

    OFF = FG_Setting(waveform=Waveforms.DC, low_v=0.0, high_v=0.0, channel=FG_CHANNEL)

    # Square wave at a fixed 50% duty. A DMM in DC mode averages over many
    # cycles, so it should read the midpoint of the two levels.
    SQUARE_0_5V = FG_Setting(
        waveform=Waveforms.SQUARE,
        period=1.0 / 1000.0,
        duty_cycle=50.0,
        low_v=0.0,
        high_v=5.0,
        channel=FG_CHANNEL,
        settle_s=0.3,
    )

    # Same idea at 25% duty: the DC average becomes a direct read-out of the
    # duty cycle, which is how you check duty with a DMM and no scope.
    SQUARE_25_PERCENT = FG_Setting(
        waveform=Waveforms.SQUARE,
        period=1.0 / 1000.0,
        duty_cycle=25.0,
        low_v=0.0,
        high_v=4.0,
        channel=FG_CHANNEL,
        settle_s=0.3,
    )

    # Sine centred on 0 V: the DMM's AC range should read the RMS value,
    # which for a sine is the peak divided by root two.
    SINE_2VPP_1KHZ = FG_Setting(
        waveform=Waveforms.SINE,
        period=1.0 / 1000.0,
        low_v=-1.0,
        high_v=1.0,
        channel=FG_CHANNEL,
        settle_s=0.3,
    )

    # Bigger amplitude for the frequency counter, which needs a decent swing.
    SINE_5VPP_1KHZ = FG_Setting(
        waveform=Waveforms.SINE,
        period=1.0 / 1000.0,
        low_v=-2.5,
        high_v=2.5,
        channel=FG_CHANNEL,
        settle_s=0.3,
    )


# ---------------------------------------------------------------------------
# Expected values
# ---------------------------------------------------------------------------


class Expected:
    """What each measurement should come out as, derived from the FG setting.

    These are the *nominal* values. How far off is acceptable is set by the
    limits in result_details.toml, not here.
    """

    # DC levels swept in the loopback test, in volts.
    DC_SWEEP_LEVELS = (0.0, 1.0, 2.5, 5.0)

    SQUARE_AVERAGE_V = 2.5  # 0-5 V at 50%
    DUTY_AVERAGE_V = 1.0  # 0-4 V at 25%
    SINE_RMS_V = 0.7071  # 2 Vpp sine, peak 1 V
    FREQUENCY_HZ = 1000.0


class Times:
    """Every delay in this tester, in one place."""

    FG_SETTLE_S = 0.4  # after programming a waveform, before measuring
    DMM_FUNCTION_SETTLE_S = 0.5  # after switching measurement function
    AC_SETTLE_S = 1.0  # AC and frequency need longer than DC
    BETWEEN_SAMPLES_S = 0.05


class Samples:
    """How many readings each measurement averages over."""

    DC = 3
    AC = 3
    FREQUENCY = 3
    RESISTANCE = 3


class Thresholds:
    """Thresholds used to interpret a reading, as opposed to pass/fail limits.

    The 5492B reports an over-range as a very large number rather than an
    error, so "open circuit" means "bigger than this".
    """

    OPEN_CIRCUIT_OHMS = 1_000_000.0
    SHORTED_LEADS_OHMS = 5.0


# ---------------------------------------------------------------------------
# Instrument identity
# ---------------------------------------------------------------------------


@dataclass
class IdnInfo(BaseSerialCommandParser):
    """Splits a standard SCPI *IDN? reply: maker, model, serial, firmware.

    Not used over serial here - it's reused as a plain regex parser for the
    identity strings, which is the same job.
    """

    pattern = r"^([^,]+),([^,]+),([^,]*),(.*)$"
    manufacturer: str
    model: str
    serial_number: str
    firmware: str

    def summary(self) -> str:
        return f"{self.manufacturer.strip()} {self.model.strip()} (fw {self.firmware.strip()})"


# Substrings that suggest the right instrument answered. These are only used to
# log a warning, never to fail a test - see result_details.toml, where the
# identity limits are deliberately permissive until you've seen the real strings.
EXPECTED_DMM_HINTS = ("5492", "BK", "B&K", "BK PRECISION")
EXPECTED_FG_HINTS = ("4052", "BK", "B&K", "BK PRECISION")
